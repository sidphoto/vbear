#!/usr/bin/env python3
"""One real stream executor turn through VBear's runtime daemon, end to end.

A developer check after ``boundary_check --mode stream`` has passed: it runs
the whole production path once with the real CLI, in a temporary VBEAR_HOME
that is deleted at the end:

  flow + task + a risk acceptance (planner decision S2a-2 Q4), whose
  executor_login_fingerprint is computed in this process from
  ~/.claude.json by login_identity (never printed, kept only in the
  temporary flows.json); the stream verification record pointing at the
  passing stream report; a git repository as the task work directory;
  then open_stream -> dispatch_prepare -> stream_send -> stream_status,
  the report checked against the files (executor_report.verify), close.

    python3 tools/stream_daemon_probe.py --claude ~/.local/share/claude/versions/2.1.292 \\
        --stream-report _sandbox/<run>/stream-report.json --out _sandbox/<run>/daemon-report.json

One dispatch: the model is asked to call StructuredOutput once.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TURN_TIMEOUT = 300.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", required=True)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--stream-report", required=True, help="the passing boundary_check --mode stream report")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    report = {"tool": "stream_daemon_probe", "started": time.time(), "claude": args.claude, "model": args.model,
              "cleanup_errors": []}
    from vbear.stream_check import present, remove_tree
    root = Path(tempfile.mkdtemp(prefix="vbe-", dir="/private/tmp"))
    try:                    # review B4: creating the state is inside the cleanup too
        state = root / "st"
        state.mkdir(mode=0o700)
        os.environ["VBEAR_HOME"] = str(state)
        report.update(_run(args, root, state, report["cleanup_errors"]))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        remove_tree(root, report["cleanup_errors"])        # never ignore_errors (review B5)
    report["temp_removed"] = not present(root)
    report["temp_ls"] = subprocess.run(["ls", "-ld", str(root)], capture_output=True, text=True).stderr.strip()
    report["passed"] = bool(report.get("valid") and report.get("verify") == [] and not report.get("error")
                            and report.get("closed_state") == "ended" and report["temp_removed"]
                            and not report["cleanup_errors"])
    report["finished"] = time.time()
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({k: report.get(k) for k in ("passed", "valid", "reasons", "verify", "model_responses",
                                                  "total_cost_usd", "closed_state", "error", "temp_removed")},
                     ensure_ascii=False, indent=1))
    return 0 if report["passed"] else 1


def _git(cwd, *a):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@invalid",
           "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@invalid"}
    return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *a], cwd=cwd, env=env,
                          capture_output=True, text=True, check=True).stdout.strip()


def _run(args, root: Path, state: Path, cleanup_errors: list) -> dict:
    from vbear.stream_check import present, remove_tree
    from vbear import acceptance, flows, login_identity, tasks
    from vbear.runtime import agent_sessions as a
    from vbear.runtime import cli_versions, stream_journal
    from vbear.runtime import daemon as d

    out: dict = {}
    binary = str(Path(args.claude).expanduser())
    version = Path(binary).name
    # The version is stream-verified here only through the passing report.
    (state / cli_versions.LOCAL_STREAM_VERIFIED_FILE).write_text(json.dumps({"versions": {version: {
        "passed": True, "report": str(Path(args.stream_report).resolve()), "verified_at": time.ctime()}}}))
    os.chmod(state / cli_versions.LOCAL_STREAM_VERIFIED_FILE, 0o600)
    if version not in cli_versions.stream_verified_versions():
        raise RuntimeError("the stream report does not back this version")
    work = root / "work"
    work.mkdir()
    _git(work, "init", "-q")
    (work / "README").write_text("probe\n")
    _git(work, "add", "README")
    _git(work, "commit", "-q", "-m", "probe")
    head = _git(work, "rev-parse", "HEAD")
    tid = tasks.save_task(None, {"title": "stream probe"})["id"]
    roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
             "reviewers": [{"name": "c", "family": "openai"}]}
    fid = flows.create_flow({"task_id": tid, "roles": roles}, lambda t: True)["id"]
    key = login_identity.create_login_key(state, valid_acceptances=acceptance.count_valid(flows.store.load(), None))
    fp = login_identity.claude_login_fingerprint(os.path.join(os.path.expanduser("~"), ".claude.json"), key)
    out["claude_json_fields_usable"] = fp.ok
    if not fp.ok:
        raise RuntimeError("~/.claude.json has no usable account fields")
    with flows.store.locked():
        data = flows.store.load()
        ev = data[fid]["events"]
        ev.append({"seq": len(ev) + 1, "at": time.time(), "kind": "risk_acknowledged", "source": "console",
                   "note": "", "text_version": acceptance.RISK_TEXT_VERSION, "codex_version": "0.160.0",
                   "model": "gpt-6-luna", "executor_claude_version": version, "executor_model": args.model,
                   "executor_login_fingerprint": fp.hmac, "login_fingerprint": "0" * 64,
                   "login_key_id": key.key_id,
                   "limits": {**acceptance.DEFAULT_LIMITS, "executor_budget_usd": 1.0}})
        flows.store.save(data)
    del fp, key
    logs: list[str] = []
    dm = d.Daemon(state, log=logs.append)
    dm.start()
    thread = threading.Thread(target=dm.serve_forever, daemon=True)
    thread.start()
    m = None
    try:
        m = a.prepare_stream_launch(state, str(work), cli_binary=binary, cli_version=version,
                                    cli_identity=a.binary_identity(binary), model_id=args.model, pipeline_id=fid,
                                    task_id=tid, allowed_root=str(root))
        rpc = lambda op, **kw: d.rpc(op, base=state, timeout=30, **kw)  # noqa: E731
        r = rpc("open_stream", launch_id=m["launch_id"])
        out["open"] = {"ok": r.get("ok"), "error": r.get("error")}
        if not r.get("ok"):
            raise RuntimeError(f"open_stream refused: {r.get('error')}")
        dispatch = str(uuid.uuid4())
        rep = {"v": 1, "dispatch_id": dispatch, "status": "done", "head": head,
               "tests": {"command": "none", "result": "not_run", "summary": "probe"}, "notes": "probe"}
        text = ("Do not run any command. Call the StructuredOutput tool with exactly this JSON: "
                + json.dumps(rep, separators=(",", ":")))
        for op, kw in (("dispatch_prepare", {"text": text, "approval": {"kind": "preview", "id": "probe"}}),
                       ("stream_send", {})):
            r = rpc(op, launch_id=m["launch_id"], pipeline=fid, dispatch_id=dispatch, **kw)
            if not r.get("ok"):
                raise RuntimeError(f"{op} refused: {r.get('error')}")
        deadline = time.monotonic() + TURN_TIMEOUT
        status = None
        while time.monotonic() < deadline:
            status = rpc("stream_status", launch_id=m["launch_id"])["result"]
            turn = status["dispatches"][0] if status["dispatches"] else {}
            if turn.get("status") in ("ended", "failed") or status["state"] in ("error", "uncertain", "exited"):
                break
            time.sleep(0.5)
        turn = status["dispatches"][0]
        out.update(valid=turn["valid"], reasons=turn["reasons"], dispatch_status=turn["status"],
                   session_state=status["state"], model_responses=status["responses"],
                   total_cost_usd=status["total_cost_usd"], num_turns=status["num_turns"])
        s = dm._streams.get(m["launch_id"])
        result = s.js.turns[dispatch].result if s is not None else None
        from vbear import executor_report
        out["verify"] = executor_report.verify(result["structured_output"], str(work)) \
            if result and result.get("structured_output") else ["沒有回報"]
        rpc("stream_close", launch_id=m["launch_id"])
        end = time.monotonic() + 30
        while time.monotonic() < end and m["launch_id"] in dm._streams:
            time.sleep(0.2)
        manifest = json.loads((Path(m["launch_dir"]["path"]) / "manifest.json").read_text())
        out["closed_state"] = manifest["state"]
        fd = os.open(m["launch_dir"]["path"], os.O_RDONLY | os.O_DIRECTORY)
        try:
            res = stream_journal.read(fd)
        finally:
            os.close(fd)
        out["journal_problem"] = res.problem
        out["journal_state"] = res.state.state
    finally:
        dm.stop()
        thread.join(10)
        dm.close()
        if m is not None and present(m["scratch"]["path"]):
            remove_tree(m["scratch"]["path"], cleanup_errors)
        out["daemon_log"] = [line for line in logs if "listening" not in line][-10:]
    return out


if __name__ == "__main__":
    sys.exit(main())
