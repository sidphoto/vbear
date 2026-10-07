#!/usr/bin/env python3
"""Re-runnable boundary check for VBear's managed Claude Code launch.

Runs one real Claude Code session with exactly the settings and arguments
VBear uses (``claude_settings`` / ``claude_argv``), asks a small model to run
one probe script with the Bash tool, and checks what the sandbox allowed:

  allowed   own work directory, own scratch directory
  refused   peer directories, a symlink into a peer, an outside directory,
            a file in HOME, the shared /tmp/claude-<uid>, direct TCP to the
            internet, HTTPS through the sandbox proxy, TCP to a local
            listener on 127.0.0.1, a local unix socket

Results come from the probe's own output file and errno values, never from
the model's reply. Each run makes ONE model call.

The interactive run also checks Claude Code's terminal title, which VBear
uses to tell "working" from "waiting" (vbear/activity.py), in the same
session: the idle mark ✳ before the prompt is typed, the ◐/◑ spinner after
it, ✳ again when the turn ends, and spinner frames no further apart than
activity.SPINNER_STALE_S. Only each title's first-character class is kept,
never its text. The title result is reported separately (``title``); it does
not change the boundary result or the exit status.

    python3 -m vbear.boundary_check --mode headless
    python3 -m vbear.boundary_check --mode interactive --claude ~/.local/share/claude/versions/2.1.291
    (or tools/verify_claude_boundary.py with the same arguments)

Exit status: 0 all checks passed, 1 a check failed, 2 the run itself failed.
Nothing outside the temporary run directory is left behind; the HOME probe
file is removed if the sandbox ever let it be created (and that is a failure).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pty
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .activity import SPINNER_STALE_S
from .runtime import agent_sessions, daemon
from .runtime.osc_title import TitleTracker

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
RUN_TIMEOUT = 240.0
IDLE_WAIT = 30.0     # after the probe result, how long to wait for the idle title
PROMPT_WAIT = 25.0   # how long to wait for the idle title before typing anyway
EXPECT = {
    "own_work_write": "allow",
    "own_scratch_write": "allow",
    "tmpdir_is_own_scratch": "allow",
    "peer_work_write": "deny",
    "peer_scratch_write": "deny",
    "symlink_to_peer_write": "deny",
    "outside_write": "deny",
    "home_write": "deny",
    "shared_claude_tmp_write": "deny",
    "tcp_internet": "deny",
    "https_via_proxy": "deny",
    "tcp_loopback_listener": "deny",
    "unix_socket_listener": "deny",
}

PROBE = r'''
import json, os, socket, sys, urllib.request
cfg = json.load(open("probe-config.json"))
out = {}

def attempt(name, fn):
    try:
        fn()
        out[name] = {"allowed": True}
    except Exception as e:
        out[name] = {"allowed": False, "error": type(e).__name__,
                     "errno": getattr(e, "errno", None), "detail": str(e)[:160]}

def write(path):
    with open(path, "w") as f:
        f.write("probe")

attempt("own_work_write", lambda: write(os.path.join(cfg["work"], "own-ok.txt")))
attempt("own_scratch_write", lambda: write(os.path.join(cfg["scratch"], "own-ok.txt")))
tmpdir = os.environ.get("TMPDIR", "")
out["tmpdir_is_own_scratch"] = {"allowed": tmpdir.startswith(cfg["scratch"]), "detail": tmpdir}
attempt("peer_work_write", lambda: write(os.path.join(cfg["peer_work"], "leak.txt")))
attempt("peer_scratch_write", lambda: write(os.path.join(cfg["peer_scratch"], "leak.txt")))
attempt("symlink_to_peer_write", lambda: write(os.path.join(cfg["work"], "to-peer", "leak.txt")))
attempt("outside_write", lambda: write(os.path.join(cfg["outside"], "leak.txt")))
attempt("home_write", lambda: write(cfg["home_probe"]))
attempt("shared_claude_tmp_write", lambda: write(cfg["shared_tmp_probe"]))
attempt("tcp_internet", lambda: socket.create_connection(("1.1.1.1", 443), timeout=5).close())
attempt("https_via_proxy", lambda: urllib.request.urlopen("https://example.com/", timeout=10).close())
attempt("tcp_loopback_listener", lambda: socket.create_connection(("127.0.0.1", cfg["tcp_port"]), timeout=5).close())
def unix():
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(cfg["unix_path"])
    s.close()
attempt("unix_socket_listener", unix)
json.dump(out, open("probe-result.json", "w"), indent=1)
print("PROBE_DONE")
'''

PROMPT = ("Use the Bash tool to run exactly this command and nothing else: python3 probe.py   "
          "Then reply with the single word DONE.")


SANDBOX_ERRNOS = (1, 13)  # EPERM, EACCES


def sandbox_refusal(name: str, got: dict) -> bool:
    """A refusal counts only if it is the sandbox's: EPERM/EACCES from the OS,
    or the sandbox proxy refusing the CONNECT. A missing path, a typo or a
    timeout must not pass as a refusal."""
    if name == "https_via_proxy":
        return "Tunnel connection failed: 403" in str(got.get("detail", ""))
    return got.get("errno") in SANDBOX_ERRNOS


def pick_claude(explicit: str | None) -> str:
    if explicit:
        return str(Path(explicit).expanduser())
    versions = Path.home() / ".local/share/claude/versions"
    if versions.is_dir():
        found = sorted((p for p in versions.iterdir() if re.fullmatch(r"\d+\.\d+\.\d+", p.name)),
                       key=lambda p: tuple(int(x) for x in p.name.split(".")))
        if found:
            return str(found[-1])
    which = shutil.which("claude")
    if not which:
        raise SystemExit("找不到 claude；請用 --claude 指定")
    return which


def claude_version(binary: str) -> str:
    proc = subprocess.run([binary, "--safe-mode", "--version"], capture_output=True, text=True,
                          timeout=15)
    m = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+) \(Claude Code\)", proc.stdout.strip())
    if proc.returncode != 0 or not m:
        raise SystemExit(f"無法判斷版本（exit {proc.returncode}）：{proc.stdout[:80]!r}")
    return m.group(1)


class Listeners:
    """A TCP listener on 127.0.0.1 and a unix socket, outside the sandbox."""

    def __init__(self, root: Path):
        self.tcp = socket.socket()
        self.tcp.bind(("127.0.0.1", 0))
        self.tcp.listen(4)
        self.unix_path = str(root / "l.sock")
        self.unix = socket.socket(socket.AF_UNIX)
        self.unix.bind(self.unix_path)
        self.unix.listen(4)
        self.accepted = {"tcp": 0, "unix": 0}
        self._stop = False
        for name, sock in (("tcp", self.tcp), ("unix", self.unix)):
            threading.Thread(target=self._accept, args=(name, sock), daemon=True).start()

    @property
    def tcp_port(self) -> int:
        return self.tcp.getsockname()[1]

    def _accept(self, name, sock):
        sock.settimeout(0.5)
        while not self._stop:
            try:
                conn, _ = sock.accept()
            except OSError:
                continue
            self.accepted[name] += 1
            conn.close()

    def close(self):
        self._stop = True
        self.tcp.close()
        self.unix.close()


def run_headless(argv: list[str], env: dict, cwd: str) -> str:
    proc = subprocess.run(argv + ["-p", PROMPT], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=RUN_TIMEOUT)
    return f"exit={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"


class TitleObservation:
    """The class of every terminal title the session sets, with its time.

    Chunks are split after each OSC terminator so that two titles arriving in
    one read are both seen. Title text is never kept."""

    _AFTER_TERMINATOR = re.compile(rb"(?<=\x07)|(?<=\x1b\\)")

    def __init__(self, start: float):
        self.start = start
        self.tracker = TitleTracker()
        self.events: list[tuple[float, str]] = []

    def feed(self, chunk: bytes, now: float) -> None:
        for piece in self._AFTER_TERMINATOR.split(chunk):
            if not piece:
                continue
            before = self.tracker.titles
            self.tracker.feed(piece, now)
            if self.tracker.titles > before:
                self.events.append((round(now - self.start, 3), self.tracker.state))

    @property
    def state(self) -> str | None:
        return self.tracker.state


_TITLE_EXPECT = {
    "idle_before_prompt": "✳ before the prompt is typed",
    "working_after_prompt": "◐/◑ after the prompt",
    "idle_after_turn": "✳ again after the last working frame",
    "spinner_cadence": f"two or more working frames in a row, at most {SPINNER_STALE_S:g} s apart",
}


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _event_problem(events, typed_at) -> str | None:
    """Why these events cannot be judged, or None. Times must be finite and
    never go back; the order of events is what every check relies on."""
    if typed_at is not None and not _finite(typed_at):
        return "送出提示的時間不是有效的數字"
    prev = None
    for e in events:
        if not (isinstance(e, (list, tuple)) and len(e) == 2 and isinstance(e[1], str)):
            return "標題事件的格式不符"
        if not _finite(e[0]):
            return "標題事件缺少有效的時間"
        if prev is not None and e[0] < prev:
            return "標題事件的時間倒退"
        prev = e[0]
    return None


def title_checks(events: list[tuple[float, str]], typed_at: float | None) -> dict:
    """The four title checks for one interactive run (times relative to start).
    Malformed, non-finite or backward times fail every check, with the reason."""
    problem = _event_problem(events, typed_at)
    if problem:
        return {"passed": False, "problem": problem,
                "checks": {n: {"pass": False, "expect": x, "why": problem} for n, x in _TITLE_EXPECT.items()},
                "typed_at": typed_at if _finite(typed_at) else None, "events": []}
    before = [s for t, s in events if typed_at is None or t < typed_at]
    after = [(t, s) for t, s in events if typed_at is not None and t >= typed_at]
    working_times = [t for t, s in after if s == "working"]
    last_working = working_times[-1] if working_times else None
    idle_after = last_working is not None and any(
        s == "waiting" and t > last_working for t, s in after)
    # Gaps between consecutive working frames inside one uninterrupted working run.
    # Only gaps over 0 count: titles from one read share a timestamp, and a
    # 0 s gap is not evidence that the spinner keeps updating. At least one
    # such gap must be measured.
    max_gap, prev, gaps = 0.0, None, 0
    for t, s in after:
        if s == "working":
            if prev is None:
                prev = t
            elif t > prev:
                max_gap = max(max_gap, t - prev)
                gaps += 1
                prev = t
        else:
            prev = None
    cadence_ok = gaps > 0 and max_gap <= SPINNER_STALE_S
    checks = {
        "idle_before_prompt": {"pass": typed_at is not None and "waiting" in before,
                               "expect": _TITLE_EXPECT["idle_before_prompt"]},
        "working_after_prompt": {"pass": bool(working_times), "expect": _TITLE_EXPECT["working_after_prompt"]},
        "idle_after_turn": {"pass": idle_after, "expect": _TITLE_EXPECT["idle_after_turn"]},
        "spinner_cadence": {"pass": cadence_ok,
                            "expect": _TITLE_EXPECT["spinner_cadence"],
                            "max_gap_s": round(max_gap, 3) if gaps else None, "gaps": gaps,
                            **({} if gaps else {"why": "沒有觀察到持續的轉圈更新（工作中的標題少於兩個連續畫面）"})},
    }
    return {"passed": all(c["pass"] for c in checks.values()), "checks": checks,
            "typed_at": typed_at, "events": [[t, s] for t, s in events]}


def run_interactive(argv: list[str], env: dict, cwd: str, result: Path,
                    idle_wait: float = IDLE_WAIT, prompt_wait: float = PROMPT_WAIT) -> tuple[str, dict]:
    """The real launch shape: Claude Code's TUI in a PTY, prompt typed in.
    Returns the transcript tail and the title check."""
    pid, fd = pty.fork()
    if pid == 0:  # child
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
    transcript = bytearray()
    start = time.monotonic()
    deadline = start + RUN_TIMEOUT
    last_output = start
    titles = TitleObservation(start)
    typed_at = None
    result_at = None
    try:
        while time.monotonic() < deadline:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                now = time.monotonic()
                transcript += chunk
                titles.feed(chunk, now)
                last_output = now
            now = time.monotonic()
            # Type once the idle title is up and the TUI has been quiet for
            # 1.5 s, or after PROMPT_WAIT whatever it shows (the title check
            # then fails; the boundary check still runs).
            idle_and_quiet = titles.state == "waiting" and now - last_output > 1.5 and now - start > 2
            if typed_at is None and (idle_and_quiet or now - start > prompt_wait):
                os.write(fd, PROMPT.encode())
                time.sleep(0.5)
                os.write(fd, b"\r")
                typed_at = round(time.monotonic() - start, 3)
            if typed_at is not None and result_at is None and result.exists():
                result_at = now
            if result_at is not None:
                # Keep the session until the turn ends (idle title after the
                # spinner), bounded, so the title check sees the whole turn.
                if title_checks(titles.events, typed_at)["checks"]["idle_after_turn"]["pass"]:
                    time.sleep(0.5)
                    break
                if now - result_at > idle_wait:
                    break
    finally:
        # Close the PTY first: a child blocked writing to a full PTY cannot exit
        # while we wait on it. Then reap with a deadline, never blocking forever.
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = None
        os.close(fd)
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
            if pgid is not None:
                try:
                    os.killpg(pgid, sig)
                except OSError:
                    pass
            end = time.monotonic() + 2
            while time.monotonic() < end:
                try:
                    done, _ = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    done = pid
                if done:
                    break
                time.sleep(0.1)
            else:
                continue
            break
        if pgid is not None:  # leftovers that ignored SIGHUP/SIGTERM
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
    raw = re.sub(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", b"", bytes(transcript))  # titles: class only, above
    text = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", raw).decode("utf-8", "replace")
    return f"typed={typed_at is not None}\n{text[-2000:]}", title_checks(titles.events, typed_at)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--claude", help="Claude Code binary (default: newest in ~/.local/share/claude/versions)")
    ap.add_argument("--mode", choices=("headless", "interactive"), default="headless")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", help="write the JSON report here")
    args = ap.parse_args()

    binary = pick_claude(args.claude)
    version = claude_version(binary)
    uid = os.getuid()
    root = Path(tempfile.mkdtemp(prefix="vbv-", dir="/private/tmp"))
    scratch = Path(tempfile.mkdtemp(prefix=agent_sessions.SCRATCH_PREFIX,
                                    dir=agent_sessions.SCRATCH_PARENT))
    home_probe = Path.home() / f".vbear-boundary-probe-{secrets.token_hex(4)}"
    shared_tmp = Path(f"/private/tmp/claude-{uid}")
    shared_probe = shared_tmp / f"vbear-probe-{secrets.token_hex(4)}"
    shared_existed = shared_tmp.exists()
    listeners = None
    report = {"tool": "verify_claude_boundary", "claude_version": version, "binary": binary,
              "mode": args.mode, "model": args.model, "started": time.time()}
    try:
        if len(agent_sessions.per_uid_tmp(str(scratch), uid).encode()) > 44:
            raise SystemExit("scratch 路徑過長，Claude 會改用共用暫存區")
        work, peer_work, peer_scratch, outside = (root / n for n in ("work", "peer", "peer-scratch", "outside"))
        for d in (work, peer_work, peer_scratch, outside):
            d.mkdir(mode=0o700)
        (work / "to-peer").symlink_to(peer_work)
        shared_tmp.mkdir(mode=0o700, exist_ok=True)
        listeners = Listeners(root)
        (work / "probe.py").write_text(PROBE)
        (work / "probe-config.json").write_text(json.dumps({
            "work": str(work), "scratch": str(scratch), "peer_work": str(peer_work),
            "peer_scratch": str(peer_scratch), "outside": str(outside),
            "home_probe": str(home_probe), "shared_tmp_probe": str(shared_probe),
            "tcp_port": listeners.tcp_port, "unix_path": listeners.unix_path}))
        settings = root / "settings.json"
        settings.write_text(json.dumps(agent_sessions.claude_settings(str(work), str(scratch), uid)))
        argv = agent_sessions.claude_argv({"cli_binary": binary, "settings_path": str(settings),
                                           "model_id": args.model})
        env = daemon.build_env()
        env["CLAUDE_CODE_TMPDIR"] = str(scratch)
        env["DISABLE_AUTOUPDATER"] = "1"
        result = work / "probe-result.json"
        if args.mode == "headless":
            report["transcript_tail"] = run_headless(argv, env, str(work))
        else:
            report["transcript_tail"], report["title"] = run_interactive(argv, env, str(work), result)
        if not result.exists():
            report["error"] = "probe-result.json 沒有產生（模型沒有執行 probe，或執行被擋下）"
            return finish(report, args.out, 2)
        observed = json.loads(result.read_text())
        checks = {}
        for name, expect in EXPECT.items():
            got = observed.get(name)
            if not isinstance(got, dict) or not isinstance(got.get("allowed"), bool):
                checks[name] = {"expect": expect, "pass": False, "why": "probe did not report this check"}
                continue
            allowed = got["allowed"]
            if expect == "allow":
                ok = allowed
            else:  # refused, and refused by the sandbox, not by some other failure
                ok = not allowed and sandbox_refusal(name, got)
            checks[name] = {"expect": expect, "allowed": allowed, "pass": ok,
                            **{k: got[k] for k in ("error", "errno", "detail") if k in got}}
        # The sandbox must not have created anything it refused.
        leaks = [str(p) for p in (peer_work / "leak.txt", peer_scratch / "leak.txt",
                                  outside / "leak.txt", home_probe, shared_probe) if p.exists()]
        checks["no_files_outside"] = {"expect": "none", "leaks": leaks, "pass": not leaks}
        checks["listeners_untouched"] = {"expect": "0 connections", "accepted": dict(listeners.accepted),
                                         "pass": not any(listeners.accepted.values())}
        report["checks"] = checks
        report["passed"] = all(c["pass"] for c in checks.values())
        return finish(report, args.out, 0 if report["passed"] else 1)
    finally:
        if listeners:
            listeners.close()
        for p in (home_probe, shared_probe):
            try:
                p.unlink()
            except OSError:
                pass
        if not shared_existed:
            try:
                shared_tmp.rmdir()
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)


def finish(report: dict, out: str | None, code: int) -> int:
    report["finished"] = time.time()
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if out:
        Path(out).write_text(text + "\n")
    summary = {k: v["pass"] for k, v in (report.get("checks") or {}).items()}
    print(json.dumps({"claude_version": report["claude_version"], "mode": report["mode"],
                      "passed": report.get("passed"), "error": report.get("error"),
                      "checks": summary,
                      "title": ({k: v["pass"] for k, v in report["title"]["checks"].items()}
                                if report.get("title") else None)}, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
