"""Bridge to a single herdr pane's terminal stream (plan: terminal workbench A).

Each pane gets at most one `herdr terminal session observe|control` child
process at a time (A0 finding: a `control` connection's stdout already
carries the same `terminal.frame` messages as `observe`, so there is never a
need for two child processes on the same pane — switching between "watch
only" and "can type" means stopping one child and starting the other, not
running both).

Everything here is plumbing between that child process and an in-memory
queue; server.py turns the queue into an SSE response and turns POST bodies
into writes on the child's stdin. Nothing here touches HTTP.
"""

from __future__ import annotations

import base64
import json
import queue
import subprocess
import threading

QUEUE_MAX = 200  # bounded so a stalled consumer cannot grow memory without limit
MAX_CONCURRENT_PANES = 4  # one herdr child process each; a personal, local tool


class PaneSession:
    """One `herdr terminal session observe|control` child process and its
    output queue. `mode` is "observe" (read-only) or "control" (can accept
    input); moving between them means creating a new PaneSession, not
    mutating this one — see TerminalBridge.takeover()/release().
    """

    def __init__(self, pane_id: str, herdr_bin: str, mode: str, cols: int, rows: int):
        self.pane_id = pane_id
        self.mode = mode
        self.cols = cols
        self.rows = rows
        self.queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self.closed = False
        self.close_reason: str | None = None
        self._bridge_interrupted = False
        args = [herdr_bin, "terminal", "session", mode, pane_id,
                "--cols", str(cols), "--rows", str(rows)]
        if mode == "control":
            args.append("--takeover")  # our own stop-before-start already avoids most
            # conflicts; --takeover only matters if something outside this bridge (the
            # herdr GUI itself, or another CLI) is also attached.
        self._proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, start_new_session=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"sid-console-term-{pane_id}")
        self._reader.start()

    # reading --------------------------------------------------------------

    def _push(self, msg) -> None:
        while True:
            try:
                self.queue.put_nowait(msg)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()  # drop the oldest frame to make room
                except queue.Empty:
                    pass

    def _read_loop(self) -> None:
        reason = None
        try:
            for raw_line in self._proc.stdout:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "terminal.closed":
                    reason = str(msg.get("reason") or "已結束")
                    self._push(msg)
                    break
                self._push(msg)
        except (OSError, ValueError):
            pass
        finally:
            self.closed = True
            if reason is None:
                # The child's stdout ended without a terminal.closed line: the
                # bridge (our subprocess) was interrupted, not the pane itself.
                self._bridge_interrupted = True
                reason = "橋接連線中斷（未收到結束訊息，Terminal 本身可能仍在執行）"
                self._push({"type": "terminal.closed", "reason": reason,
                            "bridge_interrupted": True})
            self.close_reason = reason
            self._push(None)  # sentinel: no more messages will arrive

    # writing ----------------------------------------------------------

    def _write(self, msg: dict) -> bool:
        if self.mode != "control" or self._proc.poll() is not None:
            return False
        try:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def send_input(self, raw_bytes: bytes) -> bool:
        return self._write({"type": "terminal.input",
                            "bytes": base64.b64encode(raw_bytes).decode("ascii")})

    def resize(self, cols: int, rows: int) -> bool:
        self.cols, self.rows = cols, rows
        return self._write({"type": "terminal.resize", "cols": cols, "rows": rows})

    def release_control(self) -> bool:
        return self._write({"type": "terminal.release"})

    # lifecycle --------------------------------------------------------

    def stop(self) -> None:
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass
        self._reader.join(timeout=2)
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


class TerminalBridge:
    """Tracks at most one PaneSession per pane, across HTTP requests.

    A GET (the SSE stream) and POSTs (input, takeover, release) for the same
    pane arrive on different request threads; this class is the only shared,
    lock-protected state between them.
    """

    def __init__(self, herdr_bin_getter):
        self._sessions: dict[str, PaneSession] = {}
        self._lock = threading.Lock()
        self._herdr_bin = herdr_bin_getter

    def _purge_closed_locked(self) -> None:
        for pane_id in [p for p, s in self._sessions.items() if s.closed]:
            self._sessions.pop(pane_id, None)

    def get(self, pane_id: str) -> PaneSession | None:
        with self._lock:
            return self._sessions.get(pane_id)

    def open_observer(self, pane_id: str, cols: int = 80, rows: int = 24) -> PaneSession | None:
        """The pane's current session, opening a new observe-mode one if
        there isn't a live session yet. Returns None only when the
        concurrent-pane limit is reached and this pane isn't already open.
        """
        with self._lock:
            self._purge_closed_locked()
            existing = self._sessions.get(pane_id)
            if existing is not None:
                return existing
            if len(self._sessions) >= MAX_CONCURRENT_PANES:
                return None
            bin_path = self._herdr_bin()
            if not bin_path:
                return None
            sess = PaneSession(pane_id, bin_path, "observe", cols, rows)
            self._sessions[pane_id] = sess
            return sess

    def takeover(self, pane_id: str, cols: int = 80, rows: int = 24) -> PaneSession | None:
        """Stop whatever session this pane has (if any) and start a fresh
        control-mode one. The caller's existing SSE loop notices the swap by
        polling get(pane_id) and switches to the new session's queue.

        The new session is spawned and installed *before* the old one is
        stopped, so `_sessions[pane_id]` is never briefly absent: an SSE
        handler that reads `get(pane_id)` at exactly the wrong moment would
        otherwise see nothing there and treat the pane as gone.
        """
        with self._lock:
            self._purge_closed_locked()
            old = self._sessions.get(pane_id)
            bin_path = self._herdr_bin()
        if not bin_path:
            return None
        sess = PaneSession(pane_id, bin_path, "control", cols, rows)
        with self._lock:
            self._sessions[pane_id] = sess  # atomic swap; the key stays present throughout
        if old is not None:
            old.stop()
        return sess

    def release(self, pane_id: str) -> PaneSession | None:
        """Drop back from control to observe. Returns the new observe
        session, or None if the pane had no session to release.

        Ordering matters here the same way it does in takeover(), for a
        subtler reason: calling old.release_control() *before* the new
        session is installed asks the old session to end right away, and its
        own reader thread can then race an SSE handler's "this session ended
        on its own, clean it up" path — popping `old` out of `_sessions`
        before this method gets a chance to install `new` in its place. The
        old session isn't told to end until after the swap is installed, so
        by the time it does, every reader has already moved on to `new`.
        """
        with self._lock:
            self._purge_closed_locked()
            old = self._sessions.get(pane_id)
            bin_path = self._herdr_bin() if old is not None else None
        if old is None:
            return None
        if not bin_path:
            with self._lock:
                if self._sessions.get(pane_id) is old:
                    self._sessions.pop(pane_id, None)
            old.stop()
            return None
        new = PaneSession(pane_id, bin_path, "observe", old.cols, old.rows)
        with self._lock:
            if self._sessions.get(pane_id) is old:
                self._sessions[pane_id] = new  # swap installed before old is told to end
            else:
                new.stop()
                return self._sessions.get(pane_id)  # a concurrent takeover already won
        if old.mode == "control":
            old.release_control()
        old.stop()
        return new

    def close_if_current(self, pane_id: str, expected: PaneSession) -> None:
        """Used by the SSE handler when its stream ends: stop `expected`
        only if it is still the pane's active session. If a takeover already
        replaced it, the replacement is left running untouched.
        """
        with self._lock:
            if self._sessions.get(pane_id) is not expected:
                return
            self._sessions.pop(pane_id, None)
        expected.stop()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for sess in sessions:
            sess.stop()
