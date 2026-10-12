#!/usr/bin/env python3
"""Capture the raw stdout events of one real stream-executor turn that edits files and commits.

A developer tool, run by hand when a Claude Code version shows an event VBear does not know (S3 real end-to-end, run 1,
2026-10-12: ``system/vcs_state_changed`` after a commit). It uses VBear's own launch (``prepare_stream_launch``,
``managed_argv``, ``daemon.build_env``) in a temporary VBEAR_HOME and work directory (a git repository), writes one
dispatch that creates a file, commits it and then edits it again, reads stdout until the turn's ``result`` and ends the
process the way the daemon does. Every raw line goes to ``--out`` (owner-only, never committed: it holds the model's
words and paths); what is printed is only event kinds and field names with types.

    python3 tools/stream_capture.py --claude ~/.local/share/claude/versions/2.1.296 --out raw-events.jsonl
    # (a file name: it is created in <worktree>/_sandbox/captures/, which is not in the repository)

One real model turn (a few responses, well under USD 0.05: the launch's own budget is USD 0.10).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TURN_TIMEOUT = 240.0
ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = ("_sandbox", "captures")          # below the worktree root; ``_sandbox`` is not in the repository
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def open_capture_dir(root: Path = ROOT, parts: tuple = CAPTURE_DIR) -> int:
    """A descriptor on ``<root>/_sandbox/captures``, opened one component at a time with O_NOFOLLOW from the
    worktree root (created owner-only when missing), each one checked to be ours and not writable by others. What
    is written later goes through this descriptor, so replacing a path component with a link afterwards changes
    nothing: the descriptor still names the directory that was checked."""
    fd = os.open(root, _DIR)
    try:
        for name in parts:
            try:
                nfd = os.open(name, _DIR, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(name, 0o700, dir_fd=fd)
                nfd = os.open(name, _DIR, dir_fd=fd)
            os.close(fd)
            fd = nfd
            st = os.fstat(fd)
            if st.st_uid != os.geteuid() or st.st_mode & 0o022:
                raise SystemExit(f"{name}: not a directory of this user that others cannot write")
        return fd
    except BaseException:
        os.close(fd)
        raise


def create_capture(dirfd: int, name: str) -> int:
    """A new file in that directory: owner-only, never a link and never an existing file (a name only: the raw
    lines hold the model's words, so they go to one fixed place)."""
    if not NAME_RE.match(name) or name.startswith("."):
        raise SystemExit("--out is a file name (letters, digits, . _ -), not a path")
    try:
        return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                       dir_fd=dirfd)
    except FileExistsError:
        raise SystemExit(f"--out: {name} already exists in _sandbox/captures (nothing is overwritten)") from None


def _git(cwd, *a):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "cap", "GIT_AUTHOR_EMAIL": "cap@example.invalid",
           "GIT_COMMITTER_NAME": "cap", "GIT_COMMITTER_EMAIL": "cap@example.invalid"}
    return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *a], cwd=cwd, env=env,
                          capture_output=True, text=True, check=True).stdout.strip()


def _shape(value):
    """A value's type, never the value (a nested object keeps its keys)."""
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", required=True)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    # before anything is launched or any model is called: the directory is checked and the file made
    dirfd = open_capture_dir()
    try:
        raw_fd = create_capture(dirfd, args.out)
    finally:
        os.close(dirfd)
    from vbear import strictjson
    from vbear.runtime import agent_sessions, daemon, stream_session
    from vbear.runtime import stream_protocol as sp
    from vbear.stream_check import present, remove_tree

    binary = str(Path(args.claude).expanduser())
    version = Path(binary).name
    root = Path(tempfile.mkdtemp(prefix="vbc-", dir="/private/tmp"))
    errors: list = []
    saved = os.environ.get("VBEAR_HOME")
    summary: dict = {"claude_version": version, "kinds": {}, "key_shapes": {}}
    proc = None
    leader = None
    scratch = None
    try:
        state = root / "st"
        state.mkdir(mode=0o700)
        os.environ["VBEAR_HOME"] = str(state)
        work = root / "work"
        work.mkdir(mode=0o700)
        _git(work, "init", "-q", "-b", "main")
        _git(work, "config", "user.name", "cap")
        _git(work, "config", "user.email", "cap@example.invalid")
        (work / "README.md").write_text("capture\n")
        _git(work, "add", "README.md")
        _git(work, "commit", "-q", "-m", "base")
        m = agent_sessions.prepare_stream_launch(state, str(work), cli_binary=binary, cli_version=version,
                                                 cli_identity=agent_sessions.binary_identity(binary),
                                                 model_id=args.model, pipeline_id="flow-" + uuid.uuid4().hex[:12],
                                                 task_id="capture", allowed_root=str(root))
        scratch = m["scratch"]["path"]
        sid = str(uuid.uuid4())
        agent_sessions.update_manifest(state, m["launch_id"], claude_session_id=sid, budget_usd=0.10)
        m = agent_sessions.load_validated(state, m["launch_id"])
        argv = agent_sessions.managed_argv(m)
        env = daemon.build_env()
        env["CLAUDE_CODE_TMPDIR"] = scratch
        env["DISABLE_AUTOUPDATER"] = "1"
        dispatch = str(uuid.uuid4())
        report = {"v": 1, "dispatch_id": dispatch, "status": "done", "head": "<git rev-parse HEAD>",
                  "tests": {"command": "none", "result": "not_run", "summary": "n/a"}, "notes": "ok"}
        text = ("Do these in the current directory with the Bash tool, in order: 1) create hello.py containing "
                "print('hi'); 2) git add hello.py and git commit -m 'add hello' (the identity is already set); "
                "3) append the line print('bye') to hello.py and do not commit it. Then call the StructuredOutput "
                "tool once with exactly this JSON, replacing head with the output of git rev-parse HEAD: "
                + json.dumps(report, separators=(",", ":")))
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(work), env=env, start_new_session=True, close_fds=True)
        leader = stream_session.capture_leader(proc.pid)
        proc.stdin.write(sp.dispatch_line(text, sid, dispatch))
        proc.stdin.flush()
        buf, deadline, got_result = b"", time.monotonic() + TURN_TIMEOUT, False
        fdopened, raw_fd = raw_fd, None                      # the file object owns it from here
        with os.fdopen(fdopened, "wb") as raw:
            while not got_result and time.monotonic() < deadline:
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if not ready:
                    if stream_session.leader_exited(proc.pid):
                        break
                    continue
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    raw.write(line + b"\n")
                    parsed = strictjson.loads(line, strictjson.CLAUDE_STDOUT)
                    if not parsed.ok:
                        summary.setdefault("unparsed_lines", 0)
                        summary["unparsed_lines"] += 1
                        continue
                    ev = parsed.value
                    name = ev.get("type") if isinstance(ev, dict) else type(ev).__name__
                    sub = ev.get("subtype") if isinstance(ev, dict) else None
                    kind = f"{name}/{sub}" if sub else str(name)
                    summary["kinds"][kind] = summary["kinds"].get(kind, 0) + 1
                    if isinstance(ev, dict):
                        shapes = summary["key_shapes"].setdefault(kind, [])
                        shape = _shape(ev)
                        if shape not in shapes:
                            shapes.append(shape)
                    if name == "result":
                        got_result = True
                        break
        summary["got_result"] = got_result
        proc.stdin.close()
        end = time.monotonic() + 20
        while not stream_session.leader_exited(proc.pid) and time.monotonic() < end:
            time.sleep(0.05)
        problem = stream_session.end_spawned(proc, leader)
        summary["process_problem"] = problem
        for f in (proc.stdin, proc.stdout, proc.stderr):
            try:
                f.close()
            except OSError:
                pass
        proc = None
    finally:
        if raw_fd is not None:
            os.close(raw_fd)
        if proc is not None:
            summary["process_problem"] = stream_session.end_spawned(proc, leader)
        if scratch and present(scratch):
            remove_tree(scratch, errors)
        remove_tree(root, errors)
        if saved is None:
            os.environ.pop("VBEAR_HOME", None)
        else:
            os.environ["VBEAR_HOME"] = saved
    summary["cleanup_errors"] = errors
    summary["temp_removed"] = not present(root)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary.get("got_result") and not errors and summary["temp_removed"] else 1


if __name__ == "__main__":
    sys.exit(main())
