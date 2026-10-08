"""``boundary_check --mode stream``: verify a Claude Code version for the
stream executor (design 2.2). One real session, two dispatches.

Everything that decides the result is VBear's own production code: the
launch is prepared by agent_sessions.prepare_stream_launch, argv and
settings (with the pinned endpoint) come from managed_argv, the environment
from daemon.build_env; every stdout line goes through strictjson and the
EventTracker, every fact into a JournalWriter, and the turns are judged by
stream_journal.turn_validity and executor_report.problem after the journal
is read back. The model's words decide nothing.

Checks:
  protocol       both turns follow 2.4 (schema, attribution, order, the
                 response-identity rules, num_turns), no anomaly, valid
  rapid_second   the second line is written right after the first result
  sandbox        the boundary_check probe: own work dir and scratch only,
                 no internet, no proxy, no 127.0.0.1 listener, no unix socket
  endpoint_pin   the work dir's project settings point ANTHROPIC_BASE_URL at
                 a local listener; it gets no connection and the run
                 completes. A control run (no API call: its endpoint is that
                 listener) without VBear's env block must reach it, which
                 shows the project file is read
  admin_policy   no administrator source, no server-managed settings cache
  claude_json    ~/.claude.json has usable oauthAccount ids (true/false only)

A temporary VBEAR_HOME holds the HMAC key and the journal; it is deleted at
the end. Nothing here prints a value from ~/.claude.json, a fingerprint or
an HMAC.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import acceptance, admin_policy, executor_report, login_identity, strictjson
from .boundary_check import EXPECT, PROBE, Listeners, finish, sandbox_refusal
from .runtime import agent_sessions, daemon, stream_journal, stream_protocol as sp

TURN_TIMEOUT = 300.0
CONTROL_TIMEOUT = 60.0
TURN_CAP = acceptance.DEFAULT_LIMITS["executor_turn_max_responses"]


class _Endpoint:
    """A TCP listener standing in for an API endpoint: accept and close at
    once, reading nothing (a request to it may carry the user's token)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.3)
        self.accepted = 0
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def _loop(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.accepted += 1
            conn.close()

    def close(self):
        self._stop = True
        self.sock.close()


def _report_for(d: str) -> dict:
    return {"v": 1, "dispatch_id": d, "status": "done", "head": "0" * 40,
            "tests": {"command": "python3 probe.py", "result": "not_run", "summary": "probe"}, "notes": "probe"}


def _prompt(d: str, *, run_probe: bool) -> str:
    rep = json.dumps(_report_for(d), separators=(",", ":"))
    if run_probe:
        return ("Use the Bash tool to run exactly this command and nothing else: python3 probe.py\n"
                f"When it has finished, call the StructuredOutput tool with exactly this JSON: {rep}")
    return f"Do not run any command. Call the StructuredOutput tool with exactly this JSON: {rep}"


def present(path) -> bool:
    """Whether anything is at ``path``, the link itself included. Not
    Path.exists(): it follows a dangling link to "absent" and, on Python
    3.14, reads any error (EACCES included) as absent. Here an error counts
    as present, so a leak or a leftover cannot pass unseen."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def remove_tree(path, errors: list) -> None:
    """Delete a temporary tree, never ignoring an error (review B5): what
    could not be removed is listed, and the run cannot pass."""
    def onexc(func, p, exc):
        errors.append(f"{getattr(func, '__name__', 'remove')} {p}: {type(exc).__name__}: {exc}"[:300])
    try:
        shutil.rmtree(path, onexc=onexc)
    except OSError as exc:
        errors.append(f"rmtree {path}: {type(exc).__name__}: {exc}"[:300])


def run(binary: str, version: str, model: str, out: str | None) -> int:
    report = {"tool": "verify_claude_boundary", "mode": "stream", "claude_version": version, "binary": binary,
              "model": model, "started": time.time(), "checks": {}}
    consts = sp.constants_for(version)
    if consts is None:
        report["error"] = f"Claude Code {version} 沒有串流模式的常數，不能驗證"
        return finish(report, out, 2)
    root = Path(tempfile.mkdtemp(prefix="vbp-", dir="/private/tmp"))
    report["cleanup_errors"] = []
    code = _run(binary, version, model, consts, root, report)
    # The temporary state (HMAC key, journal) is gone before the report is
    # written; a failed or incomplete removal fails the run (review B5).
    report["temp_removed"] = not present(root)
    report["temp_ls"] = subprocess.run(["ls", "-ld", str(root)], capture_output=True, text=True).stderr.strip()
    left = [str(p) for p in report.pop("_cleanup_paths", []) if present(p)]
    clean = report["temp_removed"] and not left and not report["cleanup_errors"]
    report["checks"]["cleanup"] = {"pass": clean, "left": left, "errors": report["cleanup_errors"]}
    if not clean:
        report["passed"] = False
        code = code or 1
    return finish(report, out, code)


def _run(binary: str, version: str, model: str, consts, root: Path, report: dict) -> int:
    state = root / "st"
    state.mkdir(mode=0o700)
    saved_home = os.environ.get("VBEAR_HOME")
    os.environ["VBEAR_HOME"] = str(state)
    listeners = endpoint = None
    proc = None
    scratch = None
    try:
        home = os.path.expanduser("~")
        # admin policy and the server-managed settings cache (design 2.1, v29.3)
        policy = admin_policy.check_claude(version, home=home)
        report["checks"]["admin_policy"] = {"pass": policy.ok, "found": policy.found, "problems": policy.problems}
        # ~/.claude.json: only whether the account fields are usable (planner Q2)
        key = login_identity.create_login_key(state, valid_acceptances=0)
        fp = login_identity.claude_login_fingerprint(os.path.join(home, ".claude.json"), key)
        report["checks"]["claude_json"] = {"pass": fp.ok, "fields_usable": fp.ok}
        del fp, key
        work = root / "work"
        for d in ("work", "peer", "peer-scratch", "outside"):
            (root / d).mkdir(mode=0o700)
        (work / "to-peer").symlink_to(root / "peer")
        listeners, endpoint = Listeners(root), _Endpoint()
        shared_tmp = Path(f"/private/tmp/claude-{os.getuid()}")
        home_probe = Path(home) / f".vbear-boundary-probe-{uuid.uuid4().hex[:8]}"
        shared_probe = shared_tmp / f"vbear-probe-{uuid.uuid4().hex[:8]}"
        # A project settings file trying to move the endpoint (design 2.2).
        (work / ".claude").mkdir()
        project_env = {"env": {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{endpoint.port}"}}
        for name in ("settings.json", "settings.local.json"):
            (work / ".claude" / name).write_text(json.dumps(project_env))
        m = agent_sessions.prepare_stream_launch(state, str(work), cli_binary=binary, cli_version=version,
                                                 cli_identity=agent_sessions.binary_identity(binary), model_id=model,
                                                 pipeline_id="flow-" + uuid.uuid4().hex[:12], task_id="probe",
                                                 allowed_root=str(root))
        scratch = m["scratch"]["path"]
        (work / "probe.py").write_text(PROBE)
        (work / "probe-config.json").write_text(json.dumps({
            "work": str(work), "scratch": scratch, "peer_work": str(root / "peer"),
            "peer_scratch": str(root / "peer-scratch"), "outside": str(root / "outside"),
            "home_probe": str(home_probe), "shared_tmp_probe": str(shared_probe),
            "tcp_port": listeners.tcp_port, "unix_path": listeners.unix_path}))
        sid = str(uuid.uuid4())
        agent_sessions.update_manifest(state, m["launch_id"], claude_session_id=sid, budget_usd=1.0)
        m = agent_sessions.load_validated(state, m["launch_id"])
        argv = agent_sessions.managed_argv(m)
        env = daemon.build_env()
        env["CLAUDE_CODE_TMPDIR"] = scratch
        env["DISABLE_AUTOUPDATER"] = "1"
        report["argv_sha256"] = sp.sha256_hex(sp.canonical(argv))
        identity = {"model_id": model, "workdir": m["canonical_workspace"], "executor_claude_version": version,
                    "executor_model": model}
        ldir = os.open(m["launch_dir"]["path"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            writer = stream_journal.JournalWriter(ldir, identity=identity)
        finally:
            os.close(ldir)
        writer.append("session_started", {"claude_session_id": sid, "pipeline_id": m["pipeline_id"],
                                          "cli_version": version, "argv_sha256": report["argv_sha256"],
                                          "budget_usd": 1.0})
        tracker = sp.EventTracker(consts, sid, str(work), model, executor_version=version)
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(work), env=env, start_new_session=True, close_fds=True)
        d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
        texts = {d1: _prompt(d1, run_probe=True), d2: _prompt(d2, run_probe=False)}
        keysets: dict[str, set] = {}
        variants: dict[str, set] = {}          # every distinct key set per kind (keys only, never values)
        last_keys = None
        protocol = {"pass": False}
        rapid = {"pass": False}

        def accept(d):
            writer.append("dispatch_accepted", {"dispatch_id": d, "text_sha256": sp.sha256_hex(texts[d]),
                                                "length": len(texts[d].encode()),
                                                "approval": {"kind": "automation", "id": "probe"}})

        accept(d1)
        writer.append("dispatch_writing", {"dispatch_id": d1, "turn_cap": TURN_CAP})
        proc.stdin.write(sp.dispatch_line(texts[d1], sid, d1))
        proc.stdin.flush()
        writer.append("dispatch_written", {"dispatch_id": d1})
        tracker.begin(d1, texts[d1])
        second_written = False
        buf = b""
        deadline = time.monotonic() + TURN_TIMEOUT
        done = False
        try:
            while not done:
                if time.monotonic() > deadline:
                    raise sp.ProtocolError("out_of_order", "probe timed out")
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if not ready:
                    if proc.poll() is not None:
                        raise sp.ProtocolError("out_of_order", f"CLI exited early ({proc.returncode})")
                    continue
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    raise sp.ProtocolError("out_of_order", "stdout closed early")
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    parsed = strictjson.loads(line, strictjson.CLAUDE_STDOUT)
                    if not parsed.ok:
                        raise sp.ProtocolError("bad_json", parsed.problem)
                    ev = parsed.value
                    kind = sp.kind_of(ev) or f"unknown:{str(ev.get('type'))[:32]}"
                    keysets.setdefault(kind, set()).update(ev.keys())
                    variants.setdefault(kind, set()).add(tuple(sorted(ev.keys())))
                    last_keys = (kind, sorted(ev.keys()))
                    for k, data in tracker.on_event(ev):
                        writer.append(k, data)
                        if k == "turn_result" and data["dispatch_id"] == d1 and not second_written:
                            # Right after the first result, before its completed lifecycle.
                            proc.stdin.write(sp.dispatch_line(texts[d2], sid, d2))
                            proc.stdin.flush()
                            second_written = True
                            rapid = {"pass": True, "written_after": "result(d1)"}
                        if k == "turn_lifecycle" and data["state"] == "completed":
                            if data["dispatch_id"] == d1:
                                accept(d2)            # its bytes went out at result(d1); the facts follow in order
                                writer.append("dispatch_writing", {"dispatch_id": d2, "turn_cap": TURN_CAP})
                                writer.append("dispatch_written", {"dispatch_id": d2})
                                tracker.begin(d2, texts[d2])
                            else:
                                done = True
                    if done:
                        break
            protocol = {"pass": True}
        except stream_journal.JournalCorrupt as exc:
            # The journal refused a record: e.g. the session closed after the
            # first turn and takes no further dispatch. Report why.
            protocol = {"pass": False, "reason": "journal_refused", "detail": str(exc),
                        "closed_reasons": list(writer.state.closed_reasons)}
        except sp.ProtocolError as exc:
            protocol = {"pass": False, "reason": exc.reason, "detail": exc.detail,
                        "event_keys": last_keys}
            try:
                writer.append("protocol_error", {"reason": exc.reason, "detail": exc.detail})
            except stream_journal.JournalCorrupt:
                pass
        proc.stdin.close()
        try:
            rc = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            rc = None
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        if writer.state.exit is None:
            try:
                writer.append("exited", {"returncode": rc if isinstance(rc, int) and 0 <= rc <= 255 else None,
                                         "signal": None, "stderr_tail": ""})
            except stream_journal.JournalCorrupt:
                pass
        writer.close()
        # Judge from the journal read back from disk.
        ldir = os.open(m["launch_dir"]["path"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            res = stream_journal.read(ldir, identity)
        finally:
            os.close(ldir)
        turns = []
        for d in (d1, d2):
            valid, reasons = stream_journal.turn_validity(res.state, d, executor_report.problem)
            t = res.state.turns.get(d)
            r = t.result if t else None
            turns.append({"dispatch_id": d, "valid": valid, "reasons": reasons,
                          "responses": len({e["request_id"] for e in r["assistant_events"]}) if r else None,
                          "num_turns": r["num_turns"] if r else None,
                          "tools": [c["name"] for c in r["tool_calls"]] if r else None,
                          "tool_results": [{"count": c["result_count"], "is_error": c["result_is_error"]}
                                           for c in r["tool_calls"]] if r else None,
                          "subtype": r["subtype"] if r else None,
                          "anomalies": t.anomalies if t else None,
                          "identity_problems": t.identity_problems if t else None})
        report["turns"] = turns
        report["journal_problem"] = res.problem
        report["model_responses"] = res.state.responses              # from completed turns in the journal
        report["live_model_responses"] = tracker.total_responses      # every distinct request id seen
        report["total_cost_usd"] = res.state.cost
        protocol["turns_valid"] = all(t["valid"] for t in turns)
        protocol["pass"] = protocol["pass"] and protocol["turns_valid"] and not res.problem
        report["checks"]["protocol"] = protocol
        report["checks"]["rapid_second"] = rapid
        report["observed_keys"] = {k: sorted(v) for k, v in sorted(keysets.items())}
        report["observed_key_sets"] = {k: [list(x) for x in sorted(v)] for k, v in sorted(variants.items())}
        report["unexpected_keys"] = {k: sorted(v - consts.allowed.get(k, set())) for k, v in keysets.items()
                                     if k in consts.allowed and v - consts.allowed[k]}
        # sandbox, from the probe's own output file
        result = work / "probe-result.json"
        observed = json.loads(result.read_text()) if result.exists() else {}
        sandbox = {}
        for name, expect in EXPECT.items():
            got = observed.get(name)
            if not isinstance(got, dict) or not isinstance(got.get("allowed"), bool):
                sandbox[name] = {"expect": expect, "pass": False, "why": "probe did not report this check"}
                continue
            ok = got["allowed"] if expect == "allow" else (not got["allowed"] and sandbox_refusal(name, got))
            sandbox[name] = {"expect": expect, "allowed": got["allowed"], "pass": ok}
        leaks = [str(p) for p in (root / "peer" / "leak.txt", root / "peer-scratch" / "leak.txt",
                                  root / "outside" / "leak.txt", home_probe, shared_probe) if present(p)]
        sandbox["no_files_outside"] = {"leaks": leaks, "pass": not leaks}
        sandbox["listeners_untouched"] = {"accepted": dict(listeners.accepted), "pass": not any(listeners.accepted.values())}
        report["checks"]["sandbox"] = {"pass": all(v["pass"] for v in sandbox.values()), "detail": sandbox}
        pinned = {"pass": endpoint.accepted == 0 and protocol["pass"], "connections": endpoint.accepted}
        # Control: same project file, no VBear env block; its endpoint is the
        # listener, so no request reaches Anthropic.
        before = endpoint.accepted
        control_settings = root / "control-settings.json"
        control_settings.write_text(json.dumps(agent_sessions.claude_settings(str(work), scratch, os.getuid())))
        try:
            subprocess.run([binary, "-p", "--safe-mode", "--settings", str(control_settings),
                            "--strict-mcp-config", "--model", model, "reply OK"], cwd=str(work), env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=CONTROL_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
        pinned["control_connections"] = endpoint.accepted - before
        pinned["control_shows_project_file_is_read"] = endpoint.accepted - before > 0
        report["checks"]["endpoint_pin"] = pinned
        for p in (home_probe, shared_probe):
            try:
                p.unlink()
            except OSError:
                pass
        report["passed"] = all(c.get("pass") for c in report["checks"].values())
        return 0 if report["passed"] else 1
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        for x in (listeners, endpoint):
            if x is not None:
                x.close()
        if saved_home is None:
            os.environ.pop("VBEAR_HOME", None)
        else:
            os.environ["VBEAR_HOME"] = saved_home
        remove_tree(root, report["cleanup_errors"])
        if scratch:
            remove_tree(scratch, report["cleanup_errors"])
            report["_cleanup_paths"] = [scratch]
