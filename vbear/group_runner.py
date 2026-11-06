"""The group runner (v0.16, P41-1, ADR 0007 points 3, 5 and 6): the console thread that asks the employees of a round one after the
other, in the order of the group, waits for each turn, and ends the round.

It is shaped like ``dispatch_runner.DispatchRunner``:

* one thread, one pass every 2 seconds (``tick``), one action for each group on a pass; one runner per state folder
  (``<state>/group-runner.lock``, flock);
* every action is an intent line, the call, a result line, all in the group's log; the state of a round is read from the log on every
  pass, so a restart goes on by reading. A turn whose intent has no ``turn_sent`` pauses the round as ``uncertain`` and nothing is sent
  again by itself;
* anything it cannot read or does not understand is a pause with the reason, never a guess.

A turn is a turn of the member's own chat (``ChatService.send_for_group``): the chat's rules keep: every command and every file change
asks the person, a turn costs at most the per-turn limit, the day's limit holds. Before each send it checks the day's lamp (red, or a
ledger that cannot be read, sends nothing).

What it does not do (and ``tests/test_autonomy_guard.py`` keeps it that way): start a round (only the person's words do: the route
that writes ``said``), decide whom to ask from what an employee wrote, answer a question of a chat, close an employee's process, write
``config.json``, make or change a role card, start a program or a terminal, install a skill, or go on by itself after a pause (the
countdown and the automatic continuation are v0.18.0).
"""
from __future__ import annotations

import datetime
import fcntl
import os
import threading
import time

from . import config as cfg, groups
from .api_error import ApiError

TICK_S = 2.0
LOCK_NAME = "group-runner.lock"
READ_MISSES = 15                      # passes (about 30 seconds) a chat may fail to be read while a turn is waited for
DAILY = ("red", "budget")             # the chat's own refusals that mean the day's money is used up
MAYBE_SENT = ("unavailable", "bad_reply")     # the answer never came: the message may have gone


def tomorrow_midnight(now: float) -> float:
    """The local midnight that ends the day ``now`` is in: when the day's money is counted afresh."""
    day = datetime.date.fromtimestamp(now) + datetime.timedelta(days=1)
    return datetime.datetime.combine(day, datetime.time.min).timestamp()


class _Stale(Exception):
    """The log is no longer in the state this action was decided in: do nothing."""


class GroupRunner:
    def __init__(self, group_service, *, clock=time.time, tick_s: float = TICK_S):
        self.g = group_service
        self.clock = clock
        self.tick_s = tick_s
        self._lock_fd: int | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self.last_error: str | None = None
        self._misses: dict[str, int] = {}
        self._quiet: dict[str, tuple] = {}       # group id -> the log's stamp when it had nothing for the runner to do

    # ---- lifecycle ----------------------------------------------------------------------------------------------------

    def acquire(self) -> bool:
        if self._lock_fd is not None:
            return True
        cfg.ensure_state_dir()
        fd = os.open(cfg.state_dir() / LOCK_NAME, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def release(self) -> None:
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            finally:
                self._lock_fd = None

    def start(self) -> bool:
        if not self.acquire():
            self.last_error = "另一個主控台已經在執行群組（group-runner.lock 被占用）"
            return False
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="vbear-group-runner", daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(5)
        self.release()

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception as exc:                          # never let the thread die
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stopping.wait(self.tick_s)

    # ---- one pass -----------------------------------------------------------------------------------------------------

    def tick(self) -> dict[str, str]:
        """One action for every group whose round is on: {group id: what it did}."""
        out: dict[str, str] = {}
        ids = groups.record_ids()
        for gone in set(self._quiet) - set(ids):
            self._quiet.pop(gone, None)
        for gid in ids:
            stamp = self._stamp(gid)
            if stamp is not None and self._quiet.get(gid) == stamp:
                continue                                          # nothing changed in a log that has nothing to do
            try:
                result = self._advance(gid)
            except _Stale:
                result = "stale"
            except groups.GroupError as exc:
                self.last_error = f"{exc.code}: {exc}"
                result = ""
            except Exception as exc:                              # one group's trouble pauses that group, loudly
                self.last_error = f"{type(exc).__name__}: {exc}"
                result = self._pause_quietly(gid, "runner_error")
            if result == "quiet":
                self._quiet[gid] = stamp
            else:
                self._quiet.pop(gid, None)
                if result:
                    out[gid] = result
        return out

    @staticmethod
    def _stamp(gid: str):
        try:
            st = os.stat(groups.folder() / gid / groups.LOG)
        except OSError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    # ---- one group ----------------------------------------------------------------------------------------------------

    def _advance(self, gid: str) -> str:
        rec = groups.load(gid)
        events = groups.read_log(gid)
        if events.problem:
            return "quiet"                                         # read-only: the page says so
        rnd = groups.current_round(events.records)
        if groups.round_state(rnd) != "running":
            return "quiet"                                         # idle, or paused until the person decides
        member = groups.next_member(rec, rnd)
        if member is None:
            return self._end_round(gid, rnd["n"])
        pid = member["profile_id"]
        slot = rnd["per"].get(pid, {})
        if "sent" in slot:
            return self._wait_for(gid, rnd, member, slot["sent"])
        if "intent" in slot:                                       # an intent whose result was never written
            return self._pause(gid, rnd["n"], "uncertain")
        return self._send(gid, rnd, member)

    def _tx(self, gid: str, n: int, change) -> str:
        """One transaction on the log; ``change(tx, rnd)`` runs only when round ``n`` is still on (running)."""
        with groups.log_tx(gid, self.clock) as tx:
            rnd = groups.current_round(tx.records)
            if rnd is None or rnd["n"] != n or groups.round_state(rnd) != "running":
                raise _Stale()
            return change(tx, rnd)

    def _end_round(self, gid: str, n: int) -> str:
        def change(tx, rnd):
            tx.append("round_ended", round=n, how="done")
            return "done"
        return self._tx(gid, n, change)

    def _pause(self, gid: str, n: int, reason: str, until: float | None = None) -> str:
        def change(tx, rnd):
            tx.append("paused", round=n, reason=str(reason)[:64] or "error", until=until)
            return f"paused:{reason}"
        try:
            return self._tx(gid, n, change)
        except _Stale:
            return "stale"

    def _pause_quietly(self, gid: str, reason: str) -> str:
        try:
            rnd = groups.current_round(groups.read_log(gid).records)
            return self._pause(gid, rnd["n"], reason) if rnd else ""
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return ""

    # ---- sending a turn -----------------------------------------------------------------------------------------------

    def _gate(self) -> tuple[str, float | None] | None:
        """Why nothing may be sent now, as (reason, until), or None: the day's lamp is red, or the ledger cannot say."""
        try:
            ledger = self.g.ledger()
            lamp = ledger.get("lamp") if isinstance(ledger, dict) else None
        except Exception:
            return "spend_unknown", None
        if lamp == "red":
            return "daily_limit", tomorrow_midnight(self.clock())
        if lamp not in ("green", "yellow"):
            return "spend_unknown", None
        return None

    def _skip(self, gid: str, n: int, pid: str, reason: str) -> str:
        def change(tx, rnd):
            if groups.done_with(rnd, pid):
                raise _Stale()
            tx.append("skipped", round=n, profile_id=pid, reason=reason)
            return f"skipped:{pid}"
        return self._tx(gid, n, change)

    def _send(self, gid: str, rnd: dict, member: dict) -> str:
        n, pid = rnd["n"], member["profile_id"]
        gate = self._gate()
        if gate is not None:
            return self._pause(gid, n, *gate)
        chats = self.g.chats()
        try:
            card = next((c for c in chats.cards() if c["id"] == pid), None)
        except ApiError as exc:
            return self._pause(gid, n, exc.code)
        if card is None or card["can_chat"] is not True:
            return self._skip(gid, n, pid, (card or {}).get("code") or "no_card")
        try:
            text = self.g.message_for(gid, pid)
        except ApiError as exc:
            return self._pause(gid, n, exc.code)
        chat_id = member["chat_id"]

        def intent(tx, now_rnd):
            slot = now_rnd["per"].get(pid, {})
            if "intent" in slot or "sent" in slot or groups.done_with(now_rnd, pid):
                raise _Stale()
            tx.append("turn_intent", round=n, profile_id=pid)
            return ""
        self._tx(gid, n, intent)
        try:
            result = chats.send_for_group(chat_id, text)
        except ApiError as exc:
            return self._refused(gid, n, exc.code)

        with groups.log_tx(gid, self.clock) as tx:             # the message is out: the line goes in whatever happened since
            tx.append("turn_sent", round=n, profile_id=pid, chat_id=chat_id, turn=result["turn"])
        self._misses.pop(gid, None)
        return f"sent:{pid}"

    def _refused(self, gid: str, n: int, code: str) -> str:
        """What a refusal of the chat (or of the daemon) means: the day's money is used up (pause until tomorrow); an answer that never
        came (the message may have gone: pause as ``uncertain``, send nothing again); anything else pauses with the chat's own code."""
        if code in MAYBE_SENT:
            return self._pause(gid, n, "uncertain")
        if code in DAILY:
            return self._pause(gid, n, "daily_limit", tomorrow_midnight(self.clock()))
        return self._pause(gid, n, code)

    # ---- waiting for a turn -------------------------------------------------------------------------------------------

    def _wait_for(self, gid: str, rnd: dict, member: dict, sent: dict) -> str:
        n, pid = rnd["n"], member["profile_id"]
        try:
            scan = self.g.scan(sent["chat_id"])
        except ApiError as exc:
            misses = self._misses[gid] = self._misses.get(gid, 0) + 1
            if misses < READ_MISSES:
                return f"unreadable:{pid}"
            self._misses.pop(gid, None)
            return self._pause(gid, n, exc.code)
        self._misses.pop(gid, None)
        ended = scan["turns"].get(sent["turn"], {}).get("turn_ended")
        if ended is None:
            return self._pause(gid, n, "damaged") if scan["problem"] else f"waiting:{pid}"
        normal = ended["reason"] == "result" and not ended["is_error"]
        reason = "result" if normal else ("is_error" if ended["reason"] == "result" else ended["reason"])

        def change(tx, now_rnd):
            if "ended" in now_rnd["per"].get(pid, {}):
                raise _Stale()
            tx.append("turn_ended", round=n, profile_id=pid, reason=reason, cost_usd=ended["cost_usd"])
            if reason == "violation":
                tx.append("paused", round=n, reason="violation", until=None)
                return "paused:violation"
            return f"ended:{pid}"
        return self._tx(gid, n, change)
