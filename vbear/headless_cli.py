"""One bounded, cancellable headless CLI call, shared by translations and meetings.

The runner knows nothing about what the call is for: it starts the program in a new process group with an empty
scratch directory as its working directory, writes the prompt to stdin, reads at most ``max_output`` bytes of stdout,
and ends the whole group however the call ends. No credential is copied in: the environment is the few variables the
signed-in CLI needs. A group that cannot be confirmed gone writes a ``.blocked`` marker (its name is the caller's), and
the caller's worker refuses to start again until a person removes it.

``on_line`` is for a caller that must judge the stream while it runs: it is called with every complete stdout line, and
raising from it stops the call at once (the group is killed on the way out).

The program's error output is thrown away (``/dev/null``) unless the caller passes ``stderr_tail`` (a number of bytes).
Then it is read all the way while the call runs, so the program can never block on a full pipe, and only the last
``stderr_tail`` bytes are kept, in memory. They are handed over in one place only: ``HeadlessError.stderr_tail`` of a
``cli_failed`` (a non-zero exit, or the program ended before it read the prompt), for a caller that wants to tell a few
known failures apart by a look at them. They are never written to a file or logged here, and never part of the
exception's text. Waiting for the error output never takes longer than waiting for the program: the call ends when the
program's output ends and the program has ended, whoever else still holds the error pipe.
"""
from __future__ import annotations

import fcntl
import os
import selectors
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from . import config as cfg


class HeadlessError(Exception):
    """Why a call ended without a usable result. ``code`` is one of cancelled, timeout, invalid_output, cli_failed,
    process_unconfirmed, busy, or a code a caller's ``on_line`` raised. ``returncode`` is the program's exit code
    when it got that far. ``stderr_tail`` is the end of its error output, only for a ``cli_failed`` of a call that
    asked for it (``run(stderr_tail=...)``); empty otherwise. It is not part of ``str(exception)``."""

    def __init__(self, code: str, returncode: int | None = None, stderr_tail: bytes = b""):
        self.code = code
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        super().__init__(code)


@dataclass(frozen=True)
class Run:
    output: bytes
    returncode: int
    duration_ms: int


def group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def run(argv: Callable[[str], list[str]], prompt: bytes, cancel, *, timeout: float, max_output: int,
        blocked_name: str, prefix: str = "vbear-headless-",
        on_line: Callable[[bytes], None] | None = None, stderr_tail: int = 0) -> Run:
    """Run ``argv(scratch)`` and return what it printed. ``cancel`` is a threading.Event. ``stderr_tail``: 0 (the
    default) throws the error output away; a number keeps that many of its last bytes for a ``cli_failed``."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LOGNAME", "LANG") if k in os.environ}
        # The authenticated CLI normally needs HOME. No config or credentials
        # are copied into the scratch directory, prompt, cache or error text.
        env["TMPDIR"] = tmp
        proc = None
        tail = bytearray()                      # the last bytes of the error output (only when the caller asked for them)

        def drain_err() -> None:
            """Read what the error pipe holds now (never waits), keep only the last ``stderr_tail`` bytes."""
            if not stderr_tail or proc.stderr is None or proc.stderr.closed:
                return
            for _ in range(256):
                try:
                    chunk = os.read(proc.stderr.fileno(), 65536)
                except (BlockingIOError, OSError):
                    return
                if not chunk:
                    return
                tail.extend(chunk)
                if len(tail) > stderr_tail:
                    del tail[:len(tail) - stderr_tail]

        try:
            proc = subprocess.Popen(argv(tmp), cwd=tmp, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE if stderr_tail else subprocess.DEVNULL,
                                    start_new_session=True)
            deadline, output, pending = time.monotonic() + timeout, bytearray(), bytearray()
            with selectors.DefaultSelector() as sel:
                os.set_blocking(proc.stdin.fileno(), False)
                os.set_blocking(proc.stdout.fileno(), False)
                sel.register(proc.stdin, selectors.EVENT_WRITE, "in")
                sel.register(proc.stdout, selectors.EVENT_READ, "out")
                if stderr_tail:
                    os.set_blocking(proc.stderr.fileno(), False)
                    sel.register(proc.stderr, selectors.EVENT_READ, "err")
                # the loop ends when the prompt is written and stdout is closed: the error pipe never keeps it going
                while any(k.data != "err" for k in sel.get_map().values()):
                    if cancel.is_set():
                        raise HeadlessError("cancelled")
                    if time.monotonic() >= deadline:
                        raise HeadlessError("timeout")
                    for key, _ in sel.select(0.05):
                        if key.data == "err":
                            drain_err()
                        elif key.data == "in":
                            sent = os.write(key.fd, prompt[:8192])
                            prompt = prompt[sent:]
                            if not prompt:
                                sel.unregister(key.fileobj)
                                proc.stdin.close()
                        else:
                            chunk = os.read(key.fd, 8192)
                            if not chunk:
                                sel.unregister(key.fileobj)
                            output.extend(chunk)
                            if len(output) > max_output:
                                raise HeadlessError("invalid_output")
                            if on_line is not None and chunk:
                                pending.extend(chunk)
                                while (cut := pending.find(b"\n")) >= 0:
                                    line = bytes(pending[:cut])
                                    del pending[:cut + 1]
                                    on_line(line)
                while proc.poll() is None:
                    drain_err()
                    if cancel.wait(0.02):
                        raise HeadlessError("cancelled")
                    if time.monotonic() >= deadline:
                        raise HeadlessError("timeout")
                drain_err()
            if proc.returncode != 0:
                raise HeadlessError("cli_failed", proc.returncode, bytes(tail))
            return Run(bytes(output), proc.returncode, int((time.monotonic() - started) * 1000))
        except (OSError, ValueError):
            code = None
            if proc is not None and stderr_tail:    # it may have ended before it read the prompt: give it a moment to say why
                for _ in range(15):
                    code = proc.poll()
                    if code is not None:
                        break
                    drain_err()
                    time.sleep(0.02)
                drain_err()
            raise HeadlessError("cli_failed", code, bytes(tail)) from None
        finally:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
                proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
                for _ in range(20):
                    if not group_exists(proc.pid):
                        break
                    time.sleep(0.01)
                else:
                    cfg.ensure_state_dir()
                    cfg.write_private(cfg.state_dir() / blocked_name, "process_unconfirmed\n")
                    raise HeadlessError("process_unconfirmed")


def acquire_worker(name: str, *, check_blocked: bool = True) -> int:
    """Take the exclusive lock of one worker (``<name>.lock`` in the state directory) and return its descriptor; the
    caller closes it when the worker is done. ``busy`` when another holds it, ``process_unconfirmed`` while a
    ``<name>.blocked`` marker is there (checked again after the lock is taken). ``check_blocked=False`` is for the one
    caller that only tidies records and starts no program."""
    cfg.ensure_state_dir()
    blocked = cfg.state_dir() / f"{name}.blocked"
    if check_blocked and blocked.exists():
        raise HeadlessError("process_unconfirmed")
    fd = os.open(cfg.state_dir() / f"{name}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise HeadlessError("busy") from None
        if check_blocked and blocked.exists():
            raise HeadlessError("process_unconfirmed")
    except BaseException:
        os.close(fd)
        raise
    return fd
