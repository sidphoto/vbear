#!/usr/bin/env python3
"""One real Codex review through VBear's runtime daemon, end to end (S2b probe).

A developer check, run by hand after the user has logged in the dedicated
CODEX_HOME once (planner decision S2b; nothing here logs in or reads a
credential except to compute the login fingerprint inside this process):

    CODEX_HOME=<state>/codex-home codex login -c cli_auth_credentials_store=file   # by the user

    python3 tools/review_daemon_probe.py --state _sandbox/vbear-home --out _sandbox/<run>

It runs the whole production path once, with the real pinned Codex:

  * the state directory is the given one (it must hold ``codex-home`` with
    the login); everything else this tool creates in it is removed at the
    end, and ``codex-home`` is left as it is;
  * a flow, a task, a synthetic ``.claude.json`` in a temporary HOME, a risk
    acceptance whose Codex login fingerprint is computed in this process
    from ``codex-home/auth.json`` (never printed or stored outside the
    temporary flows.json);
  * a two-commit git repository as the task's work directory; an executor
    session played by the synthetic stream CLI of the daemon tests (no
    Claude, no model), only so that the flow has its start record with the
    base commit;
  * ``VERIFIED_VERSIONS`` is set to the probed version inside this process
    only, so the review can start before the constants are verified;
  * ``review_start`` once: the one step that calls a model (one
    ``codex exec``). ``codex --version`` and ``codex mcp list --json`` run
    too, without a model;
  * the review's outcome and, redacted, what Codex really wrote: the event
    kinds and their fields, the rollout's record kinds, fields and values
    that describe the run (originator, source, provider, approval policy,
    sandbox, network profile, multi-agent mode, tool names, the usage
    chain). Account and user identifiers are replaced by "<redacted>"; long
    strings by their length.

The report is what ``codex_constants`` is corrected from.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

REVIEW_WAIT = 25 * 60.0
SECRET_KEY_PARTS = ("account", "user_id", "email", "organization", "token", "secret", "password", "auth")
KEEP_STRING = 120


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="state directory holding codex-home (the logged-in dedicated home)")
    ap.add_argument("--out", required=True, help="directory for the redacted report")
    ap.add_argument("--version", default="0.160.0")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--home", default=str(Path.home()), help="the home the pinned Codex is installed under")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = Path(args.state).resolve()
    report: dict = {"tool": "review_daemon_probe", "started": time.time(), "version": args.version,
                    "model": args.model, "model_calls": 0, "cleanup_errors": []}
    before = set(os.listdir(state)) if state.is_dir() else set()
    secrets = _secret_values(state / "codex-home" / "auth.json")      # in memory, only to prove nothing leaks
    root = Path(tempfile.mkdtemp(prefix="vbe-", dir="/private/tmp"))
    try:
        if "codex-home" not in before or not (state / "codex-home" / "auth.json").exists():
            raise RuntimeError("the dedicated codex-home is not logged in (no auth.json); the user logs in first")
        report.update(_run(args, root, state, out_dir, report))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _cleanup(state, before, root, report["cleanup_errors"])
    report["temp_removed"] = not root.exists()
    # the proof that the temporary directory is gone (ls -ld says "No such file")
    report["temp_ls"] = subprocess.run(["ls", "-ld", str(root)], capture_output=True, text=True).stderr.strip()
    report["finished"] = time.time()
    report["passed"] = bool(report.get("review", {}).get("outcome") == "valid" and not report.get("error")
                            and report["temp_removed"] and not report["cleanup_errors"])
    body = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    leaks = _leak_scan(out_dir, secrets, body)
    report["leak_check"] = {"files_scanned": leaks["scanned"], "found": len(leaks["found"]),
                            "hard": leaks["hard"], "soft": leaks["soft"]}
    if leaks["hard"]:
        # an identifier or token of auth.json is in a file: that file does not stay on disk
        for name in sorted({h.split(":")[0] for h in leaks["hard"]}):
            if name != "review-probe-report.json" and (out_dir / name).exists():
                (out_dir / name).unlink()
        report = {"tool": report["tool"], "error": "leak check failed: " + "; ".join(leaks["hard"]),
                  "passed": False, "model_calls": report["model_calls"], "leak_check": report["leak_check"]}
    elif leaks["soft"]:
        report["passed"] = False                         # a hit of a heuristic check: a person looks before it is shared
        report["error"] = report.get("error") or "leak check: heuristic hits to examine: " + "; ".join(leaks["soft"])
    body = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    (out_dir / "review-probe-report.json").write_text(body)
    os.chmod(out_dir / "review-probe-report.json", 0o600)
    print(json.dumps({k: report.get(k) for k in ("passed", "review", "model_calls", "error", "temp_removed",
                                                  "temp_ls", "leak_check")}, ensure_ascii=False, indent=1))
    return 0 if report["passed"] else 1


def _secret_values(auth: Path) -> list[str]:
    """The identifiers and tokens in auth.json that must never reach an
    output file, only for the leak scan below. Never printed or stored."""
    out: list[str] = []
    try:
        data = json.loads(auth.read_text())
    except (OSError, ValueError):
        return out

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and len(v) >= 8:
            out.append(v)
    walk(data)
    return out


def _leak_scan(out_dir: Path, secrets: list[str], report_body: str) -> dict:
    """Every file the tool keeps, and the report itself, must hold none of
    the identifiers and tokens of auth.json, no 64-hex fingerprint (HMACs
    and sha256 digests alike) and no JWT-shaped string. (No hex digest is
    expected in what is kept; a hit is examined by hand.)"""
    import re
    texts = {"review-probe-report.json": report_body}
    for p in out_dir.iterdir():
        if p.is_file() and p.name != "review-probe-report.json":
            try:
                texts[p.name] = p.read_text()
            except OSError:
                texts[p.name] = ""
    hard, soft = [], []
    for name, text in texts.items():
        if any(s in text for s in secrets):
            hard.append(f"{name}: an identifier or token of auth.json")
        if re.search(r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])", text):
            soft.append(f"{name}: a 64-hex string")
        if re.search(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", text):
            soft.append(f"{name}: a JWT-shaped string")
    return {"scanned": len(texts), "found": hard + soft, "hard": hard, "soft": soft}


def _cleanup(state: Path, before: set, root: Path, errors: list) -> None:
    """Everything this run made in the state directory goes (codex-home and
    what was there before stay); never ignore_errors."""
    try:
        for name in sorted(set(os.listdir(state)) - before):
            p = state / name
            try:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            except OSError as exc:
                errors.append(f"{name}: {type(exc).__name__}")
    except OSError as exc:
        errors.append(f"state: {type(exc).__name__}")
    try:
        shutil.rmtree(root)
    except OSError as exc:
        errors.append(f"temp: {type(exc).__name__}")


def _git(cwd, *a):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@invalid",
           "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@invalid"}
    return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *a], cwd=cwd, env=env,
                          capture_output=True, text=True, check=True).stdout.strip()


def _run(args, root: Path, state: Path, out_dir: Path, report: dict) -> dict:
    from unittest import mock

    from tests import stream_fixtures as fx
    from tests.test_runtimed_stream import FAKE_STREAM_CLI
    from vbear import acceptance, flows, login_identity, tasks
    from vbear.runtime import agent_sessions as a
    from vbear.runtime import codex_constants as cc
    from vbear.runtime import daemon as d
    from vbear.runtime import pipeline_store, review_store

    out: dict = {}
    fake_home = root / "home"
    fake_home.mkdir()
    (fake_home / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "accountUuid": "11111111-2222-3333-4444-555555555555",
        "organizationUuid": "66666666-7777-8888-9999-000000000000"}}))
    os.environ["VBEAR_HOME"] = str(state)
    os.environ["HOME"] = str(fake_home)
    work = root / "work"
    work.mkdir()
    _git(work, "init", "-q")
    (work / "README").write_text("probe\n")
    _git(work, "add", "README")
    _git(work, "commit", "-q", "-m", "base")
    base_commit = _git(work, "rev-parse", "HEAD")
    fx.fake_repo  # noqa: B018  (the executor session reads HEAD from the files; the repository is real)
    claude = root / "claude"
    claude.write_text(FAKE_STREAM_CLI % {"py": sys.executable, "repo": str(REPO)})
    claude.chmod(0o700)
    tid = tasks.save_task(None, {"title": "review probe", "workdir": str(work)})["id"]
    roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
             "reviewers": [{"name": "c", "family": "openai"}]}
    fid = flows.create_flow({"task_id": tid, "roles": roles}, lambda t: True)["id"]
    key = login_identity.create_login_key(state, valid_acceptances=0)
    claude_fp = login_identity.claude_login_fingerprint(fake_home / ".claude.json", key)
    codex_fp = login_identity.codex_login_fingerprint(state / "codex-home", key)
    out["codex_login_fingerprint_usable"] = codex_fp.ok
    if not codex_fp.ok:
        raise RuntimeError(f"the codex-home login cannot be fingerprinted ({codex_fp.problem})")
    with flows.store.locked():
        data = flows.store.load()
        ev = data[fid]["events"]
        ev.append({"seq": len(ev) + 1, "at": time.time(), "kind": "risk_acknowledged", "source": "console",
                   "note": "", "text_version": acceptance.RISK_TEXT_VERSION, "codex_version": args.version,
                   "model": args.model, "executor_claude_version": "2.1.292", "executor_model": fx.MODEL,
                   "executor_login_fingerprint": claude_fp.hmac, "login_fingerprint": codex_fp.hmac,
                   "login_key_id": key.key_id, "limits": {**acceptance.DEFAULT_LIMITS}})
        flows.store.save(data)
    del claude_fp, codex_fp, key
    logs: list[str] = []
    patches = [mock.patch.object(cc, "VERIFIED_VERSIONS", (args.version,))]
    for p in patches:
        p.start()
    dm = d.Daemon(state, log=logs.append)
    dm.review_home = args.home
    dm.start()
    thread = threading.Thread(target=dm.serve_forever, daemon=True)
    thread.start()
    rpc = lambda op, **kw: d.rpc(op, base=state, timeout=60, **kw)  # noqa: E731
    scratch_paths: list[str] = []
    try:
        # the executor session: only so that the flow has its start record
        m = a.prepare_stream_launch(state, str(work), cli_binary=str(claude), cli_version="2.1.292",
                                    cli_identity=a.binary_identity(str(claude)), model_id=fx.MODEL,
                                    pipeline_id=fid, task_id=tid, allowed_root=str(root))
        scratch_paths.append(m["scratch"]["path"])
        (work / "fake-mode").write_text("ok")
        r = rpc("open_stream", launch_id=m["launch_id"])
        if not r.get("ok"):
            raise RuntimeError(f"open_stream refused: {r.get('error')}")
        rpc("stream_close", launch_id=m["launch_id"])
        end = time.monotonic() + 60
        while time.monotonic() < end and m["launch_id"] in dm._streams:
            time.sleep(0.2)
        # the work to review: a small change with a plain defect to find
        (work / "fake-mode").unlink()
        (work / "calc.py").write_text("def average(xs):\n    return sum(xs) / len(xs)\n")
        _git(work, "add", "calc.py")
        _git(work, "commit", "-q", "-m", "add average")
        commit = _git(work, "rev-parse", "HEAD")
        out["base_commit"], out["commit"] = base_commit, commit
        r = rpc("review_start", pipeline=fid, round=1, commit=commit)
        out["review_start"] = {"ok": r.get("ok"), "error": r.get("error")}
        if not r.get("ok"):
            raise RuntimeError(f"review_start refused: {r.get('error')}")
        report["model_calls"] = 1
        job = r["result"]["job_id"]
        deadline = time.monotonic() + REVIEW_WAIT
        status = r["result"]
        while time.monotonic() < deadline:
            status = rpc("review_status", job_id=job)["result"]
            if status["state"] in ("cleaned", "manual_review"):
                break
            time.sleep(1.0)
        else:
            rpc("review_cancel", job_id=job)
            time.sleep(10)
            status = rpc("review_status", job_id=job)["result"]
        out["review"] = {k: status.get(k) for k in ("state", "outcome", "exit_code", "invalid_reasons", "record",
                                                   "result", "retained_reason", "thread_id")}
        out["review"]["responses_in_rollout"] = None
        record = state / "pipelines" / tid / "reviews" / "1"
        out["observed"] = _observe(record, out_dir)
        out["codex_mcp_list"] = _mcp_list(args, state)
        # what CODEX_HOME holds now, by name and kind (never contents): the links Codex made
        from vbear.runtime import review_codex
        links: list = []
        out["codex_home_size"] = review_codex.home_size(state / "codex-home", links)
        out["codex_home_links_counted"] = links
    finally:
        dm.stop()
        thread.join(10)
        dm.close()
        for p in patches:
            p.stop()
        out["daemon_log"] = [line for line in logs if "listening" not in line][-15:]
        for path in scratch_paths:
            shutil.rmtree(path, ignore_errors=True)
    return out


def _mcp_list(args, state: Path) -> dict:
    """What `codex mcp list --json` really prints with the review's settings."""
    from vbear.runtime import codex_constants as cc
    from vbear.runtime import review_codex
    c = cc.VERSIONS[args.version]
    binary = review_codex.codex_binary(args.version, home=args.home)
    with tempfile.TemporaryDirectory(prefix="mcp-", dir="/private/tmp") as tmp_home:
        os.chmod(tmp_home, 0o700)
        env = review_codex.build_env(str(state / "codex-home"), tmp_home)
        code, stdout, error = review_codex.run_argv(review_codex.mcp_list_argv(c, binary), env, 30.0)
    return {"exit_code": code, "stdout": stdout.decode("utf-8", "replace")[:500], "error": error}


# ---- what Codex wrote, redacted ----------------------------------------------------------------------

def _redact(value, key: str = ""):
    """Structure and short plain values; identifiers and secrets replaced,
    long strings reduced to their length."""
    if any(part in key.lower() for part in SECRET_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value[:20]] + ([f"<{len(value) - 20} more>"] if len(value) > 20 else [])
    if isinstance(value, str) and len(value) > KEEP_STRING:
        return f"<string of {len(value)} characters>"
    return value


def _keys(objs: list[dict]) -> dict:
    out: dict = {}
    for o in objs:
        for k, v in o.items():
            out.setdefault(k, set()).add(type(v).__name__)
    return {k: sorted(v) for k, v in sorted(out.items())}


def _read_jsonl(path: Path):
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        return f"unreadable ({type(exc).__name__})"


def _observe(record: Path, out_dir: Path) -> dict:
    """Event kinds and fields, rollout record kinds and the values that
    describe the run, from the saved record. Also a redacted copy of both
    files for reading by hand."""
    obs: dict = {"record_files": sorted(p.name for p in record.iterdir()) if record.is_dir() else None}
    events = _read_jsonl(record / "events.jsonl")
    if isinstance(events, list):
        kinds: dict = {}
        for e in events:
            kinds.setdefault(e.get("type"), []).append(e)
        obs["events"] = {
            "sequence": [e.get("type") for e in events],
            "fields_by_kind": {k: _keys([e for e in v]) for k, v in kinds.items()},
            "item_types": sorted({e["item"].get("type") for e in events if isinstance(e.get("item"), dict)}),
            "item_fields": _keys([e["item"] for e in events if isinstance(e.get("item"), dict)]),
            "usage": next((e.get("usage") for e in events if e.get("type") == "turn.completed"), None),
            "thread_started": _redact(next((e for e in events if e.get("type") == "thread.started"), None)),
        }
        (out_dir / "events.redacted.jsonl").write_text("\n".join(json.dumps(_redact(e)) for e in events) + "\n")
    else:
        obs["events"] = events
    rollout = _read_jsonl(record / "rollout.jsonl")
    if isinstance(rollout, list):
        by_type: dict = {}
        for r in rollout:
            by_type.setdefault(r.get("type"), []).append(r)
        payload_kinds: dict = {}
        for r in rollout:
            p = r.get("payload")
            if isinstance(p, dict):
                payload_kinds.setdefault(f"{r.get('type')}/{p.get('type')}", []).append(p)
        meta = by_type.get("session_meta", [{}])[0].get("payload", {})
        ctx = [r.get("payload", {}) for r in by_type.get("turn_context", [])]
        tools = sorted({(r.get("payload") or {}).get("name") for r in rollout
                        if isinstance((r.get("payload") or {}), dict) and (r.get("payload") or {}).get("name")})
        obs["rollout"] = {
            "record_top_keys": _keys(rollout),
            "record_types": {k: len(v) for k, v in by_type.items()},
            "payload_kinds": {k: {"count": len(v), "fields": _keys(v)} for k, v in sorted(payload_kinds.items())},
            "session_meta": _redact(meta),
            "world_state": _redact(by_type.get("world_state", [{}])[0].get("payload")),
            "turn_context": [_redact(c) for c in ctx],
            "tool_names": tools,
            "usage_chain": [
                {"usage": p.get("usage"), "turn": p.get("turn_token_usage"), "thread": p.get("thread_token_usage")}
                for p in (r.get("payload", {}) for r in by_type.get("token_usage_record", []))],
            "task_complete": _redact(next((r.get("payload") for r in rollout
                                           if isinstance(r.get("payload"), dict)
                                           and r["payload"].get("type") == "task_complete"), None)),
        }
        (out_dir / "rollout.redacted.jsonl").write_text("\n".join(json.dumps(_redact(r)) for r in rollout) + "\n")
    else:
        obs["rollout"] = rollout
    try:
        obs["last_md"] = (record / "last.md").read_text()[:4000]
    except OSError:
        obs["last_md"] = None
    try:
        obs["stderr_log"] = (record / "stderr.log").read_text()[:4000]
    except OSError:
        obs["stderr_log"] = None
    return obs


if __name__ == "__main__":
    sys.exit(main())
