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

    python3 tools/verify_claude_boundary.py --mode headless
    python3 tools/verify_claude_boundary.py --mode interactive --claude ~/.local/share/claude/versions/2.1.291

Exit status: 0 all checks passed, 1 a check failed, 2 the run itself failed.
Nothing outside the temporary run directory is left behind; the HOME probe
file is removed if the sandbox ever let it be created (and that is a failure).
"""

from __future__ import annotations

import argparse
import json
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear.runtime import agent_sessions, cli_versions, daemon  # noqa: E402

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
RUN_TIMEOUT = 240.0
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
    out = subprocess.run([binary, "--safe-mode", "--version"], capture_output=True, text=True,
                         timeout=15).stdout
    m = re.search(r"([0-9]+\.[0-9]+\.[0-9]+) \(Claude Code\)", out)
    if not m:
        raise SystemExit(f"無法判斷版本：{out[:80]!r}")
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


def run_interactive(argv: list[str], env: dict, cwd: str, result: Path) -> str:
    """The real launch shape: Claude Code's TUI in a PTY, prompt typed in."""
    pid, fd = pty.fork()
    if pid == 0:  # child
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
    transcript = bytearray()
    deadline = time.monotonic() + RUN_TIMEOUT
    typed = False
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
                transcript += chunk
            if not typed and len(transcript) > 200 and time.monotonic() > deadline - RUN_TIMEOUT + 6:
                os.write(fd, PROMPT.encode())
                time.sleep(0.5)
                os.write(fd, b"\r")
                typed = True
            if typed and result.exists():
                time.sleep(2)
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
    text = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", bytes(transcript)).decode("utf-8", "replace")
    return f"typed={typed}\n{text[-2000:]}"


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
            report["transcript_tail"] = run_interactive(argv, env, str(work), result)
        if not result.exists():
            report["error"] = "probe-result.json 沒有產生（模型沒有執行 probe，或執行被擋下）"
            return finish(report, args.out, 2)
        observed = json.loads(result.read_text())
        checks = {}
        for name, expect in EXPECT.items():
            got = observed.get(name) or {}
            allowed = bool(got.get("allowed"))
            checks[name] = {"expect": expect, "allowed": allowed,
                            "pass": allowed == (expect == "allow"),
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
                      "checks": summary}, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
