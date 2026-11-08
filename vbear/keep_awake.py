"""Keeping the Mac from sleeping while employees work (P44-3, ADR 0010 point 6). The one program VBear starts that is not an AI tool, and
the one module in ``vbear/`` that names it.

What it is: while the person has switched the setting on (``<state>/routines/settings.json``, ``keep_awake``, off by default) and a
routine's run is going or a dispatch is running, VBear runs the system's own tool for it, with an argv that is a constant: the program,
``-i`` (do not sleep just for being idle) and ``-w <the console's own pid>`` (it ends by itself when the console does). No shell, no
other argument, nothing taken from a record, a request or a setting. When there is no work for 30 seconds it is ended. It does not keep
a closed lid awake, and it does not wake a sleeping Mac for a routine's time (no wake-up is ever scheduled).

Who may start it: only ``serve()`` hands ``launch`` to a console (``Console.keep_awake_command``); a console built any other way (every
test's) has none and starts nothing. ``KeepAwake`` is handed to the routine runner, which tells it once a pass whether anyone works: the
runner itself starts no program (tests/test_autonomy_guard.py keeps ``routine*.py`` free of ``subprocess``).
"""

from __future__ import annotations

import os
import subprocess

from . import dispatch

GRACE_S = 30.0          # no work for this long: the process is ended
RETRY_S = 60.0          # a process that could not be started, or that ended by itself, is not started again sooner than this
STOP_WAIT_S = 2.0


def argv() -> list:
    """The one argv: fixed, with the console's own pid."""
    return ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]


def launch(command):
    """The real thing ``serve()`` hands to the console: start exactly ``argv()``, no shell, no input, no output. ValueError for anything else."""
    if command != argv():
        raise ValueError("this is not the argv that is run")
    return subprocess.Popen(argv(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def dispatch_running() -> bool:
    """Whether a dispatch is running now (read from the records; one that cannot be read is skipped, none readable is False)."""
    try:
        ids = dispatch.record_ids()
    except Exception:
        return False
    for dispatch_id in ids:
        try:
            if dispatch.load(dispatch_id)["state"] == "running":
                return True
        except Exception:
            continue
    return False


class KeepAwake:
    """``launch``: a function taking the argv and returning a process object (``poll``, ``terminate``; ``wait`` and ``kill`` when it has
    them) or None (no command: nothing is started). ``update(working, now, on=True)`` is called once a pass."""

    def __init__(self, launch):
        self._launch = launch
        self._proc = None
        self._last_work: float | None = None
        self._started_at = 0.0
        self._retry_at = 0.0
        self.last_error: str | None = None

    def _alive(self) -> bool:
        if self._proc is None:
            return False
        try:
            if self._proc.poll() is None:
                return True
        except Exception:
            pass
        self._proc = None                                  # it ended by itself: not started again sooner than RETRY_S after its start
        self._retry_at = max(self._retry_at, self._started_at + RETRY_S)
        return False

    def update(self, working: bool, now: float, *, on: bool = True) -> None:
        """``on``: the person's setting. Off: nothing is started and a process that runs is ended at once. On: work starts it (once; not
        sooner than ``RETRY_S`` after a failure or after it ended by itself), and ``GRACE_S`` without work ends it."""
        alive = self._alive()
        if not on:
            self._stop()
            return
        if working:
            self._last_work = now
            if not alive and now >= self._retry_at:
                self._start(now)
        elif alive and (self._last_work is None or now - self._last_work >= GRACE_S):
            self._stop()

    def _start(self, now: float) -> None:
        self._started_at = now
        try:
            self._proc = self._launch(argv())
            self.last_error = None
        except Exception as exc:
            self._proc = None
            self.last_error = type(exc).__name__
            self._retry_at = now + RETRY_S

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            wait = getattr(proc, "wait", None)
            if wait is not None:
                try:
                    wait(STOP_WAIT_S)
                except Exception:
                    kill = getattr(proc, "kill", None)
                    if kill is not None:
                        kill()
        except Exception as exc:
            self.last_error = type(exc).__name__

    def close(self) -> None:
        self._stop()
