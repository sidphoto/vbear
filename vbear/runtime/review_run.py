"""One Codex review process owned by the runtime daemon (design 5.2, 5.4, 5.8,
6): its pipes, its two output files under hard caps, the checks that end it
early, and how its process group is ended.

The daemon's loop calls ``on_stdout`` / ``on_stderr`` when a pipe is ready and
``tick`` on every pass; nothing blocks. What this class does and does not do:

  * stdout (``--json`` events) and stderr go to ``events.jsonl`` and
    ``stderr.log`` in the job directory, written here, each with a hard cap
    (8 MiB, 1 MiB). Past the cap nothing more is written, the review is
    ended and is invalid. Every event also goes through the EventsTracker.
  * Early ends (all make the review invalid, with the reason): the review's
    own timeout; more model responses than the limit (the rollout is read
    every second and its token_usage_record lines counted: a monitor, not a
    proof); CODEX_HOME over its threshold, or the review's scratch and run
    home together over theirs (every 5 s; anything not countable is "over");
    an event that breaks a rule; an output file that cannot be written.
  * The process group follows design 5.8: the leader's exit is seen with
    waitid(WNOWAIT) and it is never reaped before the group is proven empty;
    signals go to that group only, and only after the leader's identity was
    checked (stream_session.leader_check); a descendant that left the group
    means manual review; when the group cannot be proven empty, or no
    signal may be sent, the run is given up *without* reaping the leader,
    which the daemon keeps holding.

It never decides whether the review is valid: that is review_finish's job,
from ``outcome``.
"""

from __future__ import annotations

import datetime
import os
import signal
import time

from .. import strictjson
from . import codex_constants as cc
from . import proctrack, review_codex, review_validate, stream_session

EVENTS_CAP = 8 << 20
STDERR_CAP = 1 << 20
READ_CHUNK = 64 << 10
READ_BUDGET = 16
WATCH_EVERY = 1.0
DISK_EVERY = 5.0
OBSERVE_EVERY = 1.0
DRAIN_AFTER_EXIT = 2.0
TERM_GRACE = 2.0
KILL_GRACE = 2.0
KILL_GIVE_UP = 10.0
TABLE_GIVE_UP = 30.0
EVENT_LINE_MAX = strictjson.CODEX_EVENTS.unit_bytes


class RolloutWatch:
    """Counts the model responses of a running review: the token_usage_record
    lines of its rollout, read incrementally through one descriptor opened
    the safe way (review_validate.open_rollout). A monitor; the proof is
    review_validate.validate_rollout after the process has ended."""

    def __init__(self, c: cc.CodexConstants, codex_home):
        self.c, self.codex_home = c, codex_home
        self.fd: int | None = None
        self.buf = bytearray()
        self.size = 0
        self.responses = 0
        self.problem: str | None = None

    def poll(self, thread_id: str, dates) -> None:
        if self.problem:
            return
        try:
            if self.fd is None:
                try:
                    self.fd, _, _ = review_validate.open_rollout(self.codex_home, self.c, thread_id, dates)
                except review_validate.ReviewInvalid as exc:
                    if exc.code == "not_found":
                        return                       # Codex has not written it yet
                    self.problem = "；".join(exc.reasons[:2])
                    return
            while True:
                chunk = os.read(self.fd, READ_CHUNK)
                if not chunk:
                    return
                self.size += len(chunk)
                if self.size > review_validate.ROLLOUT_MAX:
                    self.problem = "rollout 超過 64 MiB"
                    return
                self.buf += chunk
                while True:
                    cut = self.buf.find(b"\n")
                    if cut < 0:
                        break
                    line = bytes(self.buf[:cut])
                    del self.buf[:cut + 1]
                    if b"token_usage_record" in line:
                        parsed = strictjson.loads_object(line, strictjson.ROLLOUT)
                        if parsed.ok and parsed.value.get("type") == "token_usage_record":
                            self.responses += 1
                if len(self.buf) > strictjson.ROLLOUT.unit_bytes:
                    self.problem = "rollout 有一行過長"
                    return
        except OSError as exc:
            self.problem = f"rollout 無法讀取（{exc.strerror or type(exc).__name__}）"
        except Exception as exc:
            self.problem = f"rollout 無法監測（{type(exc).__name__}）"

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


class ReviewRun:
    def __init__(self, *, job_id: str, c: cc.CodexConstants, proc, events_fd: int, stderr_fd: int,
                 leader_start: str | None, codex_home, scratch: str, run_home: str, timeout_s: float,
                 max_responses: int, log, now: float, wall=time.time):
        self.job_id, self.c, self.proc = job_id, c, proc
        self.pid = self.pgid = proc.pid
        self.leader_start = leader_start
        self.stdout, self.stderr = proc.stdout.fileno(), proc.stderr.fileno()
        for fd in (self.stdout, self.stderr):
            os.set_blocking(fd, False)
        self.events_fd, self.stderr_fd = events_fd, stderr_fd
        self.codex_home, self.scratch, self.run_home = codex_home, scratch, run_home
        self.timeout_s, self.max_responses = timeout_s, max_responses
        self._log, self._wall = log, wall
        self.started = now
        self.started_wall = wall()
        self.tracker = review_validate.EventsTracker(c)
        self.parsing = True
        self.buf = bytearray()
        self.events_bytes = self.stderr_bytes = 0
        self.invalid: list[str] = []
        self.terminated_for: str | None = None
        self.write_failed = False
        self.stdout_eof = self.stderr_eof = False
        self.exit_info = None
        self.exit_seen = 0.0
        self.exit_recorded = False
        self.exit_code: int | None = None
        self.exit_signal: int | None = None
        self.phase: str | None = None
        self.phase_deadline = 0.0
        self.escape_deadline: float | None = None   # see stream_session.ESCAPE_GRACE
        self.escape_next = 0.0
        self.finished = False
        self.reaped = False
        self.outcome: dict | None = None
        self.watch = RolloutWatch(c, codex_home)
        self.descendants = proctrack.DescendantTracker(self.pid)
        self.observed_dirty = False
        self.next_observe = self.next_watch = now
        self.next_disk = now + DISK_EVERY
        self.registered: set[str] = set()

    # ---- reasons -------------------------------------------------------------------------------

    def bad(self, reason: str) -> None:
        if reason not in self.invalid and len(self.invalid) < review_validate.MAX_REASONS:
            self.invalid.append(reason)

    # ---- output ----------------------------------------------------------------------------------

    def _save(self, fd: int, data: bytes, kind: str) -> bool:
        """Every byte or an error (a short write is continued, no progress is
        an error). False and the review ends when it cannot be written."""
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                if n <= 0:
                    raise OSError(5, "寫入沒有進展")
                view = view[n:]
            return True
        except OSError as exc:
            self.write_failed = True
            self.bad(f"{kind} 無法寫入（{exc.strerror or type(exc).__name__}）")
            self.terminate("write_error")
            return False

    def _capture(self, fd: int, chunk: bytes, have: int, cap: int, kind: str) -> int:
        """Write what fits under the cap; the part past it is dropped, and
        passing the cap ends the review. Returns the new byte count."""
        if self.write_failed:
            return have
        room = cap - have
        keep = chunk[:max(0, room)]
        if keep and not self._save(fd, keep, kind):
            return have
        if len(chunk) > room:
            self.bad(f"{kind} 超過 {cap >> 20} MiB 的寫入上限")
            self.terminate(f"{kind}_cap")
        return have + len(keep)

    def on_stdout(self, now: float) -> None:
        for _ in range(READ_BUDGET):
            if self.finished:
                return
            try:
                chunk = os.read(self.stdout, READ_CHUNK)
            except BlockingIOError:
                return
            except InterruptedError:
                continue
            except OSError as exc:
                self.stdout_eof = True
                self.bad(f"stdout 讀取錯誤（errno {exc.errno}）")      # not an EOF: output may be lost
                self.terminate("pipe_error")
                return
            if not chunk:
                self.stdout_eof = True
                return
            self.events_bytes = self._capture(self.events_fd, chunk, self.events_bytes, EVENTS_CAP, "events")
            if self.parsing:
                self.buf += chunk
                while True:
                    cut = self.buf.find(b"\n")
                    if cut < 0:
                        break
                    line = bytes(self.buf[:cut])
                    del self.buf[:cut + 1]
                    self._event(line)
                    if not self.parsing:
                        break
                if self.parsing and len(self.buf) > EVENT_LINE_MAX:
                    self.parsing = False
                    self.bad("有一行事件超過 1 MiB")
                    self.terminate("events_invalid")

    def _event(self, line: bytes) -> None:
        try:
            self.tracker.feed(line)
        except review_validate.ReviewInvalid as exc:
            self.parsing = False
            for r in exc.reasons:
                self.bad(r)
            self.terminate("events_invalid")

    def on_stderr(self, now: float) -> None:
        for _ in range(READ_BUDGET):
            if self.finished:
                return
            try:
                chunk = os.read(self.stderr, READ_CHUNK)
            except BlockingIOError:
                return
            except InterruptedError:
                continue
            except OSError as exc:
                self.stderr_eof = True
                self.bad(f"stderr 讀取錯誤（errno {exc.errno}）")
                self.terminate("pipe_error")
                return
            if not chunk:
                self.stderr_eof = True
                return
            self.stderr_bytes = self._capture(self.stderr_fd, chunk, self.stderr_bytes, STDERR_CAP, "stderr")

    # ---- timers and monitors ----------------------------------------------------------------------

    def tick(self, now: float) -> None:
        if self.finished:
            return
        if now >= self.next_observe:
            self.next_observe = now + OBSERVE_EVERY
            try:
                if self.descendants.observe():
                    self.observed_dirty = True
            except proctrack.ProcessTableUnavailable:
                pass
        if self.phase is None and not self.exit_recorded:
            self._monitor(now)
        self._poll_exit(now)
        if self.exit_info is not None and not self.exit_recorded:
            if (self.stdout_eof and self.stderr_eof) or now - self.exit_seen > DRAIN_AFTER_EXIT:
                self._record_exit()
        self._advance(now)

    def _monitor(self, now: float) -> None:
        if now - self.started > self.timeout_s:
            self.bad("審查逾時")
            self.terminate("timeout")
            return
        if now >= self.next_watch and self.tracker.thread_id:
            self.next_watch = now + WATCH_EVERY
            wall = self._wall()
            dates = [datetime.datetime.fromtimestamp(self.started_wall), datetime.datetime.fromtimestamp(wall)]
            self.watch.poll(self.tracker.thread_id, dates)
            if self.watch.problem:
                self.bad(f"rollout 監測：{self.watch.problem}")
                self.terminate("rollout_problem")
                return
            if self.watch.responses > self.max_responses:
                self.bad("模型回應數超過單次審查的上限")
                self.terminate("responses")
                return
        if now >= self.next_disk:
            self.next_disk = now + DISK_EVERY
            if review_codex.over_limit(review_codex.home_size(self.codex_home), review_codex.HOME_LIMIT):
                self.bad("CODEX_HOME 超過監測門檻，或無法完整計算")
                self.terminate("disk_home")
            elif review_codex.over_limit(review_codex.work_size(self.scratch, self.run_home),
                                         review_codex.WORK_LIMIT):
                self.bad("審查暫存區與 HOME 合計超過 2 GiB，或無法完整計算")
                self.terminate("disk_scratch")

    # ---- signals (design 5.8) ----------------------------------------------------------------------

    def terminate(self, reason: str) -> None:
        """TERM to the group, KILL after a grace period; the first reason is
        the one kept."""
        if self.terminated_for is None:
            self.terminated_for = reason
        if self.phase is None and not self.finished and not self.exit_recorded:
            self.phase, self.phase_deadline = "term", time.monotonic() + TERM_GRACE
            self._killpg(signal.SIGTERM)

    def _killpg(self, sig: int) -> None:
        """Only to this job's group, after the leader's identity was checked;
        when that fails nothing is sent and the run is given up."""
        if self.finished:
            return
        why = stream_session.leader_check(self.pid, self.pgid, self.leader_start)
        if why:
            self._abandon(f"不送訊號（{why}），交人工處理")
            return
        try:
            os.killpg(self.pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _poll_exit(self, now: float) -> None:
        if self.exit_info is not None or self.finished:
            return
        try:
            info = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            info = None
            self._log(f"{self.job_id}: leader is not our child any more")
        except OSError as exc:
            # We cannot tell whether the leader is gone: nothing is signalled,
            # nothing is reaped, the daemon keeps holding it (design 5.8).
            self._abandon(f"無法確認 leader 是否結束（{exc.strerror or type(exc).__name__}），不送訊號、不回收，交人工處理")
            return
        if info is not None:
            self.exit_info, self.exit_seen = info, now

    def _record_exit(self) -> None:
        self.exit_recorded = True
        info = self.exit_info
        if info.si_code == os.CLD_EXITED:
            self.exit_code = info.si_status if 0 <= info.si_status <= 255 else None
        else:
            self.exit_signal = info.si_status if 1 <= info.si_status <= 31 else None

    def _members(self, ps_timeout: float | None = None):
        try:
            rows = proctrack.process_table(ps_timeout) if ps_timeout else proctrack.process_table()
        except proctrack.ProcessTableUnavailable:
            return None, None
        return [r for r in rows if r["pgid"] == self.pgid and "Z" not in r["stat"]], rows

    def _advance(self, now: float) -> None:
        if self.finished:
            return
        mono = time.monotonic()
        if not self.exit_recorded:
            if self.phase == "term" and mono > self.phase_deadline:
                self.phase, self.phase_deadline = "kill", mono + KILL_GRACE
                self._killpg(signal.SIGKILL)
            return
        if self.escape_deadline is not None and mono < self.escape_next:
            return                                # in the grace, between two looks at the process table
        live, rows = (self._members(stream_session.ESCAPE_PS_TIMEOUT) if self.escape_deadline is not None
                      else self._members())
        if live:
            if self.phase is None:
                self.terminated_for = self.terminated_for or "group_left_over"
                self.phase, self.phase_deadline = "term", mono + TERM_GRACE
                self._killpg(signal.SIGTERM)
            elif self.phase == "term" and mono > self.phase_deadline:
                self.phase, self.phase_deadline = "kill", mono + KILL_GRACE
                self._killpg(signal.SIGKILL)
            elif self.phase == "kill" and mono > self.phase_deadline + KILL_GIVE_UP:
                self._finish(manual_review="程序群組在 SIGKILL 後仍有程序存活", reap=False)
            return
        if live is None:
            if now > self.exit_seen + TABLE_GIVE_UP:
                self._finish(manual_review="無法取得程序表，無法證明所有程序都已結束", reap=False)
            return
        escaped = [r for r in self.descendants.live(rows) if r["pgid"] != self.pgid]
        if escaped:
            # A process we saw below the leader is outside its (empty) group: a command the CLI ran in a group of
            # its own, or started as it was stopped. It ends by itself once its parent is gone, so wait for it,
            # polling, without signalling (design v29.15); the run is not over meanwhile, so the flow stays held
            # and "continue" is refused as for any unfinished review.
            if self.escape_deadline is None:
                self.escape_deadline = mono + stream_session.ESCAPE_GRACE
            if mono < self.escape_deadline:
                self.escape_next = mono + stream_session.escape_every(proctrack.SOURCE)
                return
            self._finish(manual_review="有後代離開了程序群組：" + ", ".join(str(r["pid"]) for r in escaped[:8]))
            return
        self._finish(manual_review=None)

    # ---- the end ---------------------------------------------------------------------------------------

    def _close_ends(self) -> None:
        for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        for fd in (self.events_fd, self.stderr_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        self.watch.close()

    def _outcome(self, manual_review: str | None) -> dict:
        return {"job_id": self.job_id, "manual_review": manual_review, "leader_held": not self.reaped,
                "exit_code": self.exit_code, "exit_signal": self.exit_signal,
                "terminated_for": self.terminated_for, "invalid_reasons": list(self.invalid),
                "events_bytes": self.events_bytes, "stderr_bytes": self.stderr_bytes,
                "partial_line": bool(self.buf), "write_failed": self.write_failed,
                "responses_seen": self.watch.responses}

    def _returncode(self) -> int:
        """What Popen would have recorded: the exit code, or minus the signal that ended it."""
        if self.exit_code is not None:
            return self.exit_code
        if self.exit_signal:
            return -int(self.exit_signal)
        return 0

    def _finish(self, *, manual_review: str | None, reap: bool = True) -> None:
        """The group is empty (or given up on): reap the leader only when the
        group is proven empty, close our ends."""
        if self.finished:
            return
        if reap:
            try:
                os.waitpid(self.pid, 0)
                self.reaped = True
                self.proc.returncode = self._returncode()        # Popen's own convention; it is never left None
            except ChildProcessError:
                self.reaped = True
                if self.proc.returncode is None:
                    self.proc.returncode = self._returncode()
            except OSError as exc:
                # Not reaped, and it cannot be proven it is: the daemon holds
                # the leader and a person looks (design 5.8).
                manual_review = (manual_review or
                                 f"回收 leader 失敗（{exc.strerror or type(exc).__name__}），交人工處理")
        self._close_ends()
        self.outcome = self._outcome(manual_review)
        self.finished = True                    # last: whoever sees finished sees the outcome

    def _abandon(self, reason: str) -> None:
        """Stop managing without signalling or reaping."""
        if self.finished:
            return
        self._log(f"{self.job_id}: {reason}")
        self._close_ends()
        self.outcome = self._outcome(reason)
        self.outcome["leader_held"] = not self.reaped
        self.finished = True
