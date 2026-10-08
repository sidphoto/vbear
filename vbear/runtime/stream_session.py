"""One stream executor session owned by the runtime daemon (design 2.1,
2.3, 2.4, 5.8). The daemon's selectors loop calls on_stdout / on_stderr /
on_writable when a pipe is ready and tick() on every pass.

  * stdin, stdout and stderr are non-blocking pipes. One dispatch line at a
    time is written, within 10 s (monotonic) or the dispatch failed.
  * stdout is split at newlines; a partial line over 1 MiB, a line that is
    not strict JSON, or any protocol error stops the session from taking
    dispatches. Every event goes through the EventTracker; the facts it
    returns are appended to the journal, whose JournalState is the state.
  * Cumulative caps: stdout 256 MiB, 200 000 events per session, 50 000 per
    turn, stderr 64 MiB (only the last 64 KiB kept). Passing one ends the
    session.
  * Timers: 30 s from written to the replay, 10 s from result to the
    completed lifecycle, 15 min without any stdout event, and the turn's
    hard timeout. A model-response cap ends the session.
  * The leader is never reaped before cleanup: its exit is seen with
    waitid(WEXITED|WNOHANG|WNOWAIT), so its PID, and with it the process
    group id, cannot be reused while VBear may still signal the group.
    Signals go to that group only (killpg); a descendant that left the
    group is not chased, the launch is kept for manual review instead.
"""

from __future__ import annotations

import os
import signal
import time

from .. import strictjson
from . import proctrack, stream_journal, stream_protocol as sp

STDOUT_MAX = 256 << 20
EVENTS_MAX = 200_000
TURN_EVENTS_MAX = 50_000
STDERR_MAX = 64 << 20
STDERR_TAIL = 64 << 10
LINE_MAX = strictjson.CLAUDE_STDOUT.unit_bytes
READ_CHUNK = 64 << 10
READ_BUDGET = 16
WRITE_DEADLINE = 10.0
CONFIRM_DEADLINE = 30.0
FINISH_DEADLINE = 10.0
NO_PROGRESS = 15 * 60.0
DRAIN_AFTER_EXIT = 2.0
TERM_GRACE = 2.0
KILL_GRACE = 2.0
OBSERVE_EVERY = 1.0


class StreamSession:
    def __init__(self, *, sid: str, launch_id: str, manifest: dict, proc, writer: stream_journal.JournalWriter,
                 tracker: sp.EventTracker, prior_responses: int, log, now: float):
        self.sid = sid
        self.launch_id = launch_id
        self.manifest = manifest
        self.pipeline_id = manifest["pipeline_id"]
        self.task_id = manifest["task_id"]
        self.cli_version = manifest["cli_version"]
        self.claude_session_id = manifest["claude_session_id"]
        self.cwd = manifest["canonical_workspace"]
        self.proc = proc                      # held; never poll()/wait() before cleanup
        self.pid = self.pgid = proc.pid
        self.stdin = proc.stdin.fileno()
        self.stdout = proc.stdout.fileno()
        self.stderr = proc.stderr.fileno()
        for fd in (self.stdin, self.stdout, self.stderr):
            os.set_blocking(fd, False)
        self.writer = writer
        self.tracker = tracker
        self.prior_responses = prior_responses    # earlier sessions of the flow
        self._log = log
        self.started = time.time()
        self.buf = bytearray()
        self.err_tail = bytearray()
        self.stdout_total = self.stderr_total = self.events_total = 0
        self.stdout_eof = self.stderr_eof = False
        self.interpreting = True                  # False after a protocol error: drain only
        self.journal_broken = ""
        # the write in progress
        self.writing: str | None = None
        self.write_text = ""
        self.wbuf = memoryview(b"")
        self.write_deadline = 0.0
        # timers of the turn
        self.sent_at = self.turn_started = self.last_event = self.finishing_since = 0.0
        self.turn_cap = self.total_cap = 0
        self.turn_timeout = 0.0
        # exit and termination
        self.exit_info = None
        self.exit_seen = 0.0
        self.exit_recorded = False
        self.phase: str | None = None             # None | "term" | "kill"
        self.phase_deadline = 0.0
        self.close_reason = ""
        self.finished = False
        self.outcome: dict | None = None
        self.descendants = proctrack.DescendantTracker(self.pid)
        self.next_observe = now
        self.registered: set[str] = set()         # which pipes the daemon's selector watches

    # ---- state ----------------------------------------------------------------

    @property
    def js(self) -> stream_journal.JournalState:
        return self.writer.state

    @property
    def state(self) -> str:
        if self.journal_broken:
            return "error"
        if self.writing is not None:
            return "writing"
        return self.js.state

    def accepts_dispatch(self) -> str | None:
        """None when a new dispatch may be prepared or sent, else why not."""
        if self.phase is not None or self.exit_info is not None:
            return "session 正在結束"
        if self.state != "idle":
            return f"session 狀態是 {self.state}，不是 idle"
        if self.js.closed_reasons:
            return "session 不再接受派工：" + "；".join(self.js.closed_reasons)
        return None

    def info(self) -> dict:
        return {"session_id": self.sid, "pid": self.pid, "pgid": self.pgid, "argv": [], "cwd": self.cwd,
                "cols": 0, "rows": 0, "started": self.started, "exited": self.exit_info is not None,
                "exit_code": self._returncode(), "closing": self.phase is not None,
                "output_bytes": self.stdout_total, "attachments": 0, "control_attachment": None,
                "managed": self.launch_id, "engine": "claude-stream", "kind": None,
                "cli_version": self.cli_version,
                "activity_evidence": {"claude_stream": {"state": self.state}}}

    # ---- journal ----------------------------------------------------------------

    def record(self, kind: str, data: dict) -> bool:
        if self.journal_broken:
            return False
        try:
            self.writer.append(kind, data)
            return True
        except (stream_journal.JournalCorrupt, OSError) as exc:
            self.journal_broken = f"{type(exc).__name__}: {exc}"
            self._log(f"{self.sid}: journal write failed, ending the session: {self.journal_broken}")
            self.interpreting = False
            self.terminate("日誌無法寫入")
            return False

    def protocol_error(self, reason: str, detail: str = ""):
        self.interpreting = False
        self.tracker.reset_after_failure()
        self.writing = None
        if self.js.state != "exited":
            self.record("protocol_error", {"reason": reason, "detail": detail[:1024]})

    def fail(self, reason: str):
        """dispatch_failed for the dispatch in flight (design 2.4)."""
        d = self.writing if self.writing is not None else (self.js.current or self.js.pending)
        self.writing = None
        self.tracker.reset_after_failure()
        if d is not None and self.js.state not in stream_journal.TERMINAL:
            self.record("dispatch_failed", {"dispatch_id": d, "reason": reason})

    def over_limit(self, reason: str):
        self.protocol_error(reason)
        self.terminate(f"超過上限（{reason}）")

    # ---- writing ------------------------------------------------------------------

    def start_write(self, dispatch_id: str, text: str, line: bytes, now: float, *, turn_cap: int,
                    total_cap: int, turn_timeout: float):
        self.writing, self.write_text = dispatch_id, text
        self.wbuf = memoryview(line)
        self.write_deadline = now + WRITE_DEADLINE
        self.turn_cap, self.total_cap, self.turn_timeout = turn_cap, total_cap, turn_timeout

    def on_writable(self, now: float) -> bool:
        """Write what the pipe takes. True when there is nothing left to write."""
        if self.writing is None:
            return True
        try:
            n = os.write(self.stdin, self.wbuf)
        except BlockingIOError:
            return False
        except OSError:
            self.fail("partial_write")
            return True
        self.wbuf = self.wbuf[n:]
        if self.wbuf:
            return False
        d, text = self.writing, self.write_text
        self.writing = None
        if self.record("dispatch_written", {"dispatch_id": d}):
            self.tracker.begin(d, text)
            self.sent_at = self.turn_started = self.last_event = now
        return True

    # ---- reading ------------------------------------------------------------------

    def on_stdout(self, now: float) -> None:
        for _ in range(READ_BUDGET):
            try:
                chunk = os.read(self.stdout, READ_CHUNK)
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            if not chunk:
                self.stdout_eof = True
                return
            self.stdout_total += len(chunk)
            if self.stdout_total > STDOUT_MAX:
                self.over_limit("stdout_limit")
            self.buf += chunk
            while True:
                cut = self.buf.find(b"\n")
                if cut < 0:
                    break
                line = bytes(self.buf[:cut])
                del self.buf[:cut + 1]
                self._on_line(line, now)
            if len(self.buf) > LINE_MAX:
                if self.interpreting:
                    self.protocol_error("bad_json", "一行超過 1 MiB")
                self.buf.clear()

    def _on_line(self, line: bytes, now: float) -> None:
        self.events_total += 1
        if self.events_total > EVENTS_MAX and self.interpreting:
            self.over_limit("event_limit")
        if not self.interpreting or self.state in stream_journal.TERMINAL:
            return
        parsed = strictjson.loads(line, strictjson.CLAUDE_STDOUT)
        if not parsed.ok:
            self.protocol_error("bad_json", parsed.problem)
            return
        if self.state == "writing":
            self.protocol_error("event_while_writing")
            return
        try:
            facts = self.tracker.on_event(parsed.value)
        except sp.ProtocolError as exc:
            self.protocol_error(exc.reason, exc.detail)
            return
        except Exception as exc:  # never let an event escape the loop (design 2.3)
            self.protocol_error("bad_json", f"{type(exc).__name__}")
            return
        self.last_event = now
        for kind, data in facts:
            if not self.record(kind, data):
                return
            if kind == "turn_result":
                self.finishing_since = now
        turn = self.tracker.turn
        if turn is not None:
            if turn.events > TURN_EVENTS_MAX:
                self.over_limit("turn_event_limit")
            elif (turn.responses >= self.turn_cap
                  or self.prior_responses + self.tracker.total_responses >= self.total_cap):
                self.fail("response_cap")
                self.terminate("已達模型回應數上限")

    def on_stderr(self, now: float) -> None:
        for _ in range(READ_BUDGET):
            try:
                chunk = os.read(self.stderr, READ_CHUNK)
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            if not chunk:
                self.stderr_eof = True
                return
            self.stderr_total += len(chunk)
            self.err_tail += chunk
            if len(self.err_tail) > STDERR_TAIL:
                del self.err_tail[:len(self.err_tail) - STDERR_TAIL]
            if self.stderr_total > STDERR_MAX and self.interpreting:
                self.over_limit("stderr_limit")

    # ---- timers, exit, termination ----------------------------------------------------

    def terminate(self, reason: str) -> None:
        """TERM to the group, KILL after a grace period (design 5.8)."""
        if self.phase is None and not self.finished:
            self.close_reason = reason
            self.phase, self.phase_deadline = "term", time.monotonic() + TERM_GRACE
            self._killpg(signal.SIGTERM)

    def _killpg(self, sig: int) -> None:
        # The leader is our unreaped child, so this group id is ours.
        if self.pgid <= 1 or self.pgid == os.getpgrp():
            return
        try:
            os.killpg(self.pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _poll_exit(self, now: float) -> None:
        if self.exit_info is not None:
            return
        try:
            info = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            info = None
            self._log(f"{self.sid}: leader is not our child any more")
        if info is not None:
            self.exit_info, self.exit_seen = info, now

    def _returncode(self):
        info = self.exit_info
        if info is None:
            return None
        return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status

    def tick(self, now: float) -> None:
        if self.finished:
            return
        if now >= self.next_observe:
            self.next_observe = now + OBSERVE_EVERY
            try:
                self.descendants.observe()
            except proctrack.ProcessTableUnavailable:
                pass
        st = self.state
        if self.writing is not None and now > self.write_deadline:
            self.fail("partial_write")
        elif st == "sent" and now - self.sent_at > CONFIRM_DEADLINE:
            self.fail("not_confirmed")
        elif st == "running" and now - self.last_event > NO_PROGRESS:
            self.fail("no_progress")
        elif st == "running" and self.turn_timeout and now - self.turn_started > self.turn_timeout:
            self.fail("turn_timeout")
        elif st == "finishing" and now - self.finishing_since > FINISH_DEADLINE:
            self.fail("no_completed")
        self._poll_exit(now)
        if self.exit_info is not None and not self.exit_recorded:
            if (self.stdout_eof and self.stderr_eof) or now - self.exit_seen > DRAIN_AFTER_EXIT:
                self._record_exit()
        self._advance_termination(now)

    def _record_exit(self) -> None:
        self.exit_recorded = True
        if self.js.state in ("sent", "running", "finishing"):
            self.fail("process_exited")            # the turn in flight; a prepared one is closed by "exited"
        info = self.exit_info
        killed = info.si_code != os.CLD_EXITED
        returncode = None if killed else info.si_status
        sig = info.si_status if killed and 1 <= info.si_status <= 31 else None
        if returncode is not None and not 0 <= returncode <= 255:
            returncode = None
        if self.js.exit is None:
            self.record("exited", {"returncode": returncode, "signal": sig,
                                   "stderr_tail": self.err_tail.decode("utf-8", "replace")[-STDERR_TAIL // 4:]})

    def _group_members(self):
        """Live members of our group (not zombies), or None when unknown."""
        try:
            rows = proctrack.process_table()
        except proctrack.ProcessTableUnavailable:
            return None, None
        live = [r for r in rows if r["pgid"] == self.pgid and "Z" not in r["stat"]]
        return live, rows

    def _advance_termination(self, now: float) -> None:
        """``now`` is monotonic, like every deadline here."""
        if not self.exit_recorded:
            if self.phase == "term" and now > self.phase_deadline:
                self.phase, self.phase_deadline = "kill", now + KILL_GRACE
                self._killpg(signal.SIGKILL)
            return
        live, rows = self._group_members()
        if live:
            if self.phase is None:
                self.close_reason = self.close_reason or "程序已結束，清理其餘程序"
                self.phase, self.phase_deadline = "term", now + TERM_GRACE
                self._killpg(signal.SIGTERM)
            elif self.phase == "term" and now > self.phase_deadline:
                self.phase, self.phase_deadline = "kill", now + KILL_GRACE
                self._killpg(signal.SIGKILL)
            elif self.phase == "kill" and now > self.phase_deadline + 10:
                self._finish(manual_review="程序群組在 SIGKILL 後仍有程序存活")
            return
        if live is None:
            if now > self.exit_seen + 30:
                self._finish(manual_review="無法取得程序表，無法證明所有程序都已結束")
            return
        escaped = [r for r in self.descendants.live(rows) if r["pgid"] != self.pgid]
        if escaped:
            self._finish(manual_review="有後代離開了程序群組：" + ", ".join(str(r["pid"]) for r in escaped[:8]))
            return
        self._finish(manual_review=None)

    def _finish(self, *, manual_review: str | None) -> None:
        """The group is empty (or we give up on proving it): reap the leader,
        close our ends. The daemon then cleans up or retains the launch."""
        try:
            os.waitpid(self.pid, 0)
            self.proc.returncode = self._returncode()
        except ChildProcessError:
            pass
        for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                f.close()
            except OSError:
                pass
        self.writer.close()
        self.outcome = {"launch_id": self.launch_id, "manual_review": manual_review,
                        "journal_bytes": self.writer.size, "close_reason": self.close_reason}
        self.finished = True              # last: whoever sees finished sees the outcome
