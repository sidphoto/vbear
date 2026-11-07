"""Find (and end) the processes a test left running under its own temporary folder (P42-0).

A process belongs to a test when the VBEAR_HOME in its environment is that test's temporary folder or something under
it; so does every process that one started. Only ``ps`` is read. Only a process found that way is ever sent a signal,
never one picked by name, so a runtimed of the person using VBear (whose VBEAR_HOME is not under a test's folder) is
not touched. ``assert_clean`` is what a test registers with ``addCleanup`` right after it makes its folder.
"""
import os
import re
import signal
import subprocess
import time

_HOME = re.compile(r"(?:^|\s)VBEAR_HOME=(\S+)")


def _real(path) -> str:
    return os.path.realpath(str(path)).rstrip("/")


def _under(path, root: str) -> bool:
    path = _real(path)
    return path == root or path.startswith(root + "/")


def _ps(*fields) -> list[list[str]]:
    out = subprocess.run(["ps", "-E", "-ww", "-axo", ",".join(f"{f}=" for f in fields)], capture_output=True, text=True,
                         timeout=30).stdout
    return [line.split(None, len(fields) - 1) for line in out.splitlines() if line.strip()]


def find(root) -> list[tuple[int, str]]:
    """``(pid, VBEAR_HOME)`` of every process whose VBEAR_HOME is under ``root``, and of everything they started.
    This process and its parents are never listed."""
    root = _real(root)
    me = {os.getpid(), os.getppid()}
    mine: dict[int, str] = {}
    for row in _ps("pid", "command"):
        if len(row) < 2 or not row[0].isdigit():
            continue
        m = _HOME.search(row[1])
        if m and _under(m.group(1), root) and int(row[0]) not in me:
            mine[int(row[0])] = _real(m.group(1))
    children: dict[int, list[int]] = {}
    for pid, ppid in _ps("pid", "ppid"):
        children.setdefault(int(ppid), []).append(int(pid))
    stack = list(mine)
    while stack:
        for kid in children.get(stack.pop(), []):
            if kid not in mine and kid not in me:
                mine[kid] = root
                stack.append(kid)
    return sorted(mine.items())


def reap(root, wait: float = 5.0) -> list[int]:
    """End what ``find`` lists (TERM, then KILL after ``wait`` seconds). Returns the pids that were found."""
    found = [pid for pid, _ in find(root)]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in found:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        end = time.monotonic() + wait
        while time.monotonic() < end and any(_alive(pid) for pid in found):
            time.sleep(0.05)
        if not any(_alive(pid) for pid in found):
            break
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                                    # a child of ours that ended but is not yet waited for
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def assert_clean(root) -> None:
    """Fail if a process under ``root`` is still running. What it found is ended first, so a failure leaves nothing."""
    found = find(root)
    if found:
        reap(root)
        raise AssertionError("processes the test left running (pid, VBEAR_HOME): " + ", ".join(f"{p} {h}" for p, h in found))
