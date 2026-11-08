"""The routine runner (P44-2, ADR 0010 points 3 to 5): the console thread that, when a routine's time comes, reminds the person or (with
「自己動手」 item 3) starts the run, sends it, waits for its turn and records how it ended.

It is shaped like ``dispatch_runner.DispatchRunner``:

* one thread, one pass every 15 seconds (``tick``); one runner per state folder (``<state>/routine-runner.lock``, flock);
* every decision is a record of ``<state>/routines/runs.jsonl`` and the state of a run is read from it on every pass, so a restart
  goes on by reading. A run whose message may or may not have gone (the console went away between the send and the record) is looked up
  in its chat: a message that is there is recorded, one that is not makes the run ``uncertain``, and **nothing is ever sent again by
  itself**;
* a slot is run at most once: ``routines.new_run`` refuses a (routine, slot) that has a run, in any state, so a restart, a clock set back,
  a double press or a repeated pass cannot make a second one.

What a pass does, in this order (the later batches add to the places marked):

1. ``_look``: for every routine that is on, the slots that became due since the last look (a slot is **on time** for 2 minutes after
   its time): with item 3 off, a reminder (``waiting``: nothing is sent, nothing costs); with item 3 on, the run is queued (``starting``,
   ``by: auto3``). A slot that is older than that is recorded ``missed`` and not listed. (P44-3 puts the heartbeat and the wake-up list
   here: it changes what is done with a late slot, not the rest.) Reminders nobody pressed are put away (``missed``) at the routine's next
   time or after 12 hours; those of a routine that was switched off or deleted are ``dismissed``.
2. ``_drive``: one run at a time. The run that is going (``running``, or ``starting`` with a chat) is looked after; when none is going, the
   oldest queued run begins: the day's lamp and the routines' daily limit are looked at, a new one-person chat is opened with the
   employee (``ChatService.create``), the message goes out through ``ChatService.send_for_routine`` and the run is ``running``.
   (P44-4: the pass then calls ``self.auto_continue.tick()`` once, the dispatches that stopped for a limit; see ``_continue``.)

Item 3 is read in one place, ``_auto``: the ``routines`` key of the autonomy block (through ``autonomy``'s reader); a missing key, a value that is not ``True``, a config that
cannot be read: off. With it off the runner writes only ``waiting``, ``missed``, ``dismissed``, ``skipped``, ``failed`` records for slots
and starts runs only for the person's press (``start_waiting``, ``start_now``).

What it does not do (and ``tests/test_autonomy_guard.py`` keeps it that way): write ``config.json``, make or change role cards, start a
program or a terminal, install a skill, or answer a question of a chat. A run is a turn in a chat of its own, so the chat's rules hold: every
command and every file change asks the person, a card nobody answers in 5 minutes is a refusal, a turn costs at most the per-turn limit,
and the day's limit holds. Nothing here writes a name or a word of a routine into a record: the runs file has ids, times, states and money.
"""

from __future__ import annotations

import datetime
import fcntl
import os
import re
import threading
import time
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from . import autonomy, config as cfg, meetings as mt, routine_rules as rr, routines as rt
from .api_error import ApiError

TICK_S = 15.0
LOCK_NAME = "routine-runner.lock"
READ_MISSES = 15                       # passes (about 4 minutes) a chat may fail to be read while a turn is waited for
PAGES_MAX = 100
SCANS_KEPT = 32
CLOSE_TRIES = 5
DAILY = ("red", "budget")              # the chat's own refusals that mean the day's money is used up
TRANSIENT = ("busy", "limit", "restarting")
MAYBE_SENT = ("unavailable", "bad_reply")      # the answer never came: the message may have gone
ERRORS_MAX = 3                         # unexpected troubles with one run before it is a failed run


def _code(value) -> str:
    return re.sub(r"[^a-z_0-9]", "_", str(value).lower())[:64] or "error"


class RoutineRunner:
    """``chats``: a function returning the chat service (create, send_for_routine, get, stop, close, cards). ``ledger``: a function
    returning the day's ledger (``lamp`` and the spend); one that cannot answer starts nothing. ``conf``: a function returning the
    console's configuration (read for item 3 and for the day's limit only). ``tz``: a ``zoneinfo`` zone, or None for the machine's own."""

    def __init__(self, *, chats, ledger, conf, clock=time.time, tz=None, tick_s: float = TICK_S, auto_continue=None):
        self._chats = chats
        self.ledger = ledger
        self.conf = conf
        self.clock = clock
        self.tz = tz
        self.tick_s = tick_s
        self.auto_continue = auto_continue                 # P44-4: what the pass calls after the routines' own work (None: nothing)
        self.last_error: str | None = None
        self._lock_fd: int | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._poke = threading.Event()
        self._seen: float | None = None                    # the instant of the last look at the slots
        self._reserved: dict[str, str] = {}                # run id -> a chat opened for it that the employee's refusal left empty
        self._wait: dict[str, dict] = {}                   # run id -> {"first", "next"} while an employee is busy or the room is full
        self._misses: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._scans: OrderedDict[str, dict] = OrderedDict()
        self._closing: dict[str, int] = {}

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
            self.last_error = "另一個主控台已經在執行例行工作（routine-runner.lock 被占用）"
            return False
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="vbear-routine-runner", daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        self._stopping.set()
        self._poke.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(5)
        self.release()

    def poke(self) -> None:
        """Look again now instead of at the next pass (the person has just pressed a button)."""
        self._poke.set()

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception as exc:                          # never let the thread die
                self.last_error = f"{type(exc).__name__}"
            self._poke.wait(self.tick_s)
            self._poke.clear()

    # ---- item 3 and the money -----------------------------------------------------------------------------------------------

    def _conf(self):
        try:
            return self.conf()
        except Exception:
            return None

    def _auto(self) -> bool:
        """Whether a routine starts by itself: 「自己動手」 item 3 and nothing else. False for anything that is not ``True``."""
        try:
            return autonomy.read(self._conf())["routines"] is True
        except Exception:
            return False

    def _day_usd(self) -> Decimal:
        return Decimal(mt.limits_from(self._conf() if isinstance(self._conf(), dict) else {})["daily_usd"])

    def _local_day(self, ts: float) -> datetime.date:
        return datetime.datetime.fromtimestamp(ts, self.tz).date()

    def spent_today(self, runs: list | None = None) -> Decimal:
        """What the runs that began today (the local day) cost, from their records; a run still going counts for nothing yet."""
        runs = rt.read_runs()[0] if runs is None else runs
        today = self._local_day(self.clock())
        total = Decimal(0)
        for run in runs:
            if run["cost_usd"] is not None and run["started_at"] is not None and self._local_day(run["started_at"]) == today:
                try:
                    total += Decimal(run["cost_usd"])
                except InvalidOperation:
                    pass
        return total

    def limits(self) -> dict:
        """What the page says about money: the day's limit, the routines' limit in force (the person's setting or half the day's, never above
        the day's), what routines spent today, and the day's lamp and spend (None where the ledger cannot say)."""
        day = self._day_usd()
        settings, _ = rt.read_settings()
        out = {"day_usd": day, "routine_usd": rr.effective_daily_usd(settings["daily_usd"], day), "routine_spent_usd": self.spent_today(),
               "default_usd": rr.default_daily_usd(day), "lamp": None, "spent_usd": None, "left_usd": None}
        try:
            ledger = self.ledger()
            if isinstance(ledger, dict):
                out["lamp"] = ledger.get("lamp")
                spent = Decimal(str(ledger.get("spent_usd")))
                out["spent_usd"], out["left_usd"] = spent, max(Decimal(0), day - spent)
        except Exception:
            pass
        return out

    def _gate(self, runs: list) -> str | None:
        """Why no run may begin now, or None: the day's lamp is red or the ledger cannot say, or routines have spent their share."""
        try:
            ledger = self.ledger()
            lamp = ledger.get("lamp") if isinstance(ledger, dict) else None
        except Exception:
            return "spend_unknown"
        if lamp == "red":
            return "daily_limit"
        if lamp not in ("green", "yellow"):
            return "spend_unknown"
        settings, _ = rt.read_settings()
        if self.spent_today(runs) >= rr.effective_daily_usd(settings["daily_usd"], self._day_usd()):
            return "routine_limit"
        return None

    # ---- one pass -------------------------------------------------------------------------------------------------------------

    def tick(self) -> dict:
        """One pass: {run id: what was done}. Nothing is done while the routines or the runs cannot be read (``last_error`` says so)."""
        now = self.clock()
        out: dict = {}
        routines, problem = rt.read_routines()
        runs, runs_problem = rt.read_runs()
        if problem or runs_problem:
            self.last_error = problem or runs_problem
            self._continue()                                  # a routine file that cannot be read is no reason to leave a dispatch waiting
            return out
        self.last_error = None
        auto = self._auto()
        out.update(self._look(now, routines, runs, auto))
        out.update(self._drive(now, routines))
        self._continue()
        self._seen = now
        self._drain_closing()
        return {k: v for k, v in out.items() if v}

    def _continue(self) -> None:
        """P44-4, the one line this runner has for 「倒數接續」: the dispatches that stopped for a limit (``auto_continue.tick()``). Its trouble is
        its own: a code in ``last_error``, never the routines' work undone."""
        if self.auto_continue is None:
            return
        try:
            self.auto_continue.tick()
        except Exception:
            self.last_error = "continue_failed"

    # ---- looking at the slots ----------------------------------------------------------------------------------------------------

    def _look(self, now: float, routines: list, runs: list, auto: bool) -> dict:
        out: dict = {}
        taken = {(r["routine_id"], r["slot"]) for r in runs}
        floor = min(self._seen, now) if self._seen is not None else now - rr.ON_TIME_S
        for routine in routines:
            if not routine["enabled"]:
                continue
            since = max(routine["enabled_at"] or 0.0, floor)
            for slot, due in rr.slots_between(routine, since, now, self.tz):
                if (routine["id"], slot) in taken:
                    continue
                if now - due >= rr.ON_TIME_S:
                    made = rt.new_run(routine["id"], slot, state="missed", why="on_time", reason="late", now=now)
                elif auto:                                    # item 3: the run begins by itself (read once, above)
                    made = rt.new_run(routine["id"], slot, state="starting", why="on_time", by="auto3", now=now)
                else:
                    made = rt.new_run(routine["id"], slot, state="waiting", why="on_time", now=now)
                if made is not None:
                    out[made["run_id"]] = made["state"]
        out.update(self._put_away(now, routines))
        return out

    def _put_away(self, now: float, routines: list) -> dict:
        """The reminders nobody pressed: a routine that is gone or off, the routine's next time, or 12 hours."""
        out: dict = {}
        by_id = {r["id"]: r for r in routines}
        for run in rt.read_runs()[0]:
            if run["state"] != "waiting":
                continue
            routine = by_id.get(run["routine_id"])
            if routine is None or not routine["enabled"]:
                got = rt.update_run(run["run_id"], ("waiting",), now=now, state="dismissed", reason="deleted" if routine is None else "disabled")
            else:
                due = rr.slot_due(run["slot"], self.tz) or run["at"]
                nxt = rr.next_due(routine, due, self.tz)
                if (nxt is not None and now >= nxt[1]) or now - run["at"] >= rr.WAITING_FOR_S:
                    got = rt.update_run(run["run_id"], ("waiting",), now=now, state="missed", reason="unanswered")
                else:
                    continue
            if got is not None:
                out[run["run_id"]] = got["state"]
        return out

    # ---- one run at a time ------------------------------------------------------------------------------------------------------------

    def _drive(self, now: float, routines: list) -> dict:
        out: dict = {}
        runs = rt.read_runs()[0]
        going = [r for r in runs if r["state"] == "running" or (r["state"] == "starting" and r["chat_id"])]
        for run in sorted(going, key=lambda r: (r["started_at"] or 0.0, r["run_id"])):
            out[run["run_id"]] = self._guard(run, self._wait_for if run["state"] == "running" else self._resolve, now)
        runs = rt.read_runs()[0]
        if any(r["state"] == "running" or (r["state"] == "starting" and r["chat_id"]) for r in runs):
            return out                                        # one at a time: the others wait their turn
        queued = sorted((r for r in runs if r["state"] == "starting"),
                        key=lambda r: (rr.slot_due(r["slot"], self.tz) or 0.0, r["started_at"] or 0.0, r["run_id"]))
        if queued:
            out[queued[0]["run_id"]] = self._guard(queued[0], lambda run, at: self._begin(run, at, routines, runs), now)
        return out

    def _guard(self, run: dict, action, now: float) -> str:
        """One run's trouble is that run's: after a few unexpected errors it is a failed run, and nothing else stops."""
        try:
            return action(run, now) or ""
        except ApiError as exc:
            self.last_error = f"{exc.code}"
            return self._fail(run, _code(exc.code), now)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}"
            count = self._errors[run["run_id"]] = self._errors.get(run["run_id"], 0) + 1
            return self._fail(run, "runner_error", now) if count >= ERRORS_MAX else ""

    def _fail(self, run: dict, reason: str, now: float) -> str:
        got = rt.update_run(run["run_id"], ("starting", "running"), now=now, state="failed", reason=reason)
        self._forget(run["run_id"])
        return f"failed:{reason}" if got else ""

    def _forget(self, run_id: str) -> None:
        for table in (self._reserved, self._wait, self._misses, self._errors):
            table.pop(run_id, None)

    def _find(self, routines: list, run: dict):
        return next((r for r in routines if r["id"] == run["routine_id"]), None)

    # ---- beginning a run ------------------------------------------------------------------------------------------------------------------

    def _begin(self, run: dict, now: float, routines: list, runs: list) -> str:
        run_id = run["run_id"]
        routine = self._find(routines, run)
        if routine is None or (not routine["enabled"] and run["why"] != "now" and run["by"] == "auto3"):
            got = rt.update_run(run_id, ("starting",), now=now, state="dismissed", reason="deleted" if routine is None else "disabled")
            self._forget(run_id)
            return "dismissed" if got else ""
        wait = self._wait.get(run_id)
        if wait and now < wait["next"]:
            return ""                                          # an employee who was busy: not asked again yet
        why = self._gate(runs)
        if why is not None:
            got = rt.update_run(run_id, ("starting",), now=now, state="skipped", reason=why)
            self._forget(run_id)
            return f"skipped:{why}" if got else ""
        chats = self._chats()
        chat_id = self._reserved.get(run_id)
        if chat_id is None:
            try:
                chat_id = chats.create({"profile_id": routine["profile_id"]})["chat"]["id"]
            except ApiError as exc:
                return self._refused(run, None, exc.code, now, sent=False)
        if rt.update_run(run_id, ("starting",), now=now, chat_id=chat_id) is None:
            return ""                                          # decided meanwhile (the routine was switched off, the run put away)
        try:
            result = chats.send_for_routine(chat_id, rr.message_text(routine["name"], run["slot"], routine["text"]))
        except ApiError as exc:
            return self._refused(run, chat_id, exc.code, now, sent=True)
        got = rt.update_run(run_id, ("starting",), now=now, state="running", turn=result["turn"])
        self._forget(run_id)
        return f"sent:{result['turn']}" if got else ""

    def _refused(self, run: dict, chat_id, code: str, now: float, *, sent: bool) -> str:
        """What a refusal of the chat or of the daemon means for a run: the day's money is used up (skipped); the employee or the room is
        busy (asked again every 30 seconds for 12 minutes, then skipped); an answer that never came (look in the chat); anything else is a
        failed run with the chat's own code."""
        run_id = run["run_id"]
        if sent and code in MAYBE_SENT:
            return self._resolve(run | {"chat_id": chat_id}, now)
        if sent:                                               # clean refusal before anything was written: the run has no chat again
            self._reserved[run_id] = chat_id
            rt.update_run(run_id, ("starting",), now=now, chat_id=None)
        if code in DAILY:
            rt.update_run(run_id, ("starting",), now=now, state="skipped", reason="daily_limit")
            self._forget(run_id)
            return "skipped:daily_limit"
        if code == "spend_unknown":
            rt.update_run(run_id, ("starting",), now=now, state="skipped", reason="spend_unknown")
            self._forget(run_id)
            return "skipped:spend_unknown"
        if code in TRANSIENT:
            wait = self._wait.setdefault(run_id, {"first": now, "next": now})
            if now - wait["first"] >= rr.BUSY_FOR_S:
                rt.update_run(run_id, ("starting",), now=now, state="skipped", reason="busy")
                self._forget(run_id)
                return "skipped:busy"
            wait["next"] = now + rr.BUSY_RETRY_S
            return f"retry:{code}"
        return self._fail(run, _code(code), now)

    # ---- a run whose message may or may not have gone ---------------------------------------------------------------------------------------

    def _scan(self, chat_id: str) -> dict:
        """What the chat's record says (read once, then only what is new): the turn of its first message, and for each turn how it ended.
        ApiError when the chat cannot be read."""
        chats = self._chats()
        scan = self._scans.pop(chat_id, None) or {"after": 0, "first_turn": None, "turns": {}, "problem": ""}
        for _ in range(PAGES_MAX):
            got = chats.get(chat_id, scan["after"])
            for rec in got["records"]:
                if rec["kind"] == "user_message" and scan["first_turn"] is None:
                    scan["first_turn"] = rec["turn"]
                elif rec["kind"] == "turn_ended":
                    scan["turns"][rec["turn"]] = rec
            scan["after"], scan["problem"] = got["next_after"], got.get("problem") or ""
            if not got["more"]:
                break
        self._scans[chat_id] = scan
        while len(self._scans) > SCANS_KEPT:
            self._scans.popitem(last=False)
        return scan

    def _resolve(self, run: dict, now: float) -> str:
        """A run that has a chat and no turn (the console went away between the send and the record, or the answer never came): the chat
        says whether the message is there. It is: recorded, never sent again. It is not: ``uncertain``, and nobody sends it for the person."""
        run_id = run["run_id"]
        try:
            turn = self._scan(run["chat_id"])["first_turn"]
        except ApiError as exc:
            misses = self._misses[run_id] = self._misses.get(run_id, 0) + 1
            if misses < READ_MISSES:
                return "unreadable"
            self._forget(run_id)
            rt.update_run(run_id, ("starting",), now=now, state="uncertain", reason=_code(exc.code))
            return "uncertain"
        self._misses.pop(run_id, None)
        if turn is None:
            rt.update_run(run_id, ("starting",), now=now, state="uncertain", reason="not_found")
            self._forget(run_id)
            return "uncertain"
        got = rt.update_run(run_id, ("starting",), now=now, state="running", turn=turn)
        self._forget(run_id)
        return f"found:{turn}" if got else ""

    # ---- waiting for the turn -----------------------------------------------------------------------------------------------------------------

    def _wait_for(self, run: dict, now: float) -> str:
        run_id = run["run_id"]
        try:
            scan = self._scan(run["chat_id"])
        except ApiError as exc:
            misses = self._misses[run_id] = self._misses.get(run_id, 0) + 1
            if misses < READ_MISSES:
                return "unreadable"
            return self._fail(run, _code(exc.code), now)
        self._misses.pop(run_id, None)
        ended = scan["turns"].get(run["turn"])
        if ended is None:
            return self._fail(run, "damaged", now) if scan["problem"] else "waiting"
        normal = ended["reason"] == "result" and not ended["is_error"]
        reason = "result" if normal else ("is_error" if ended["reason"] == "result" else _code(ended["reason"]))
        got = rt.update_run(run_id, ("running",), now=now, state="done" if normal else "failed", reason=reason,
                            cost_usd=str(ended["cost_usd"]))
        self._forget(run_id)
        self._closing[run["chat_id"]] = 0
        self._drain_closing()
        return f"{'done' if normal else 'failed'}:{reason}" if got else ""

    def _drain_closing(self) -> None:
        for chat_id in list(self._closing):
            try:
                self._chats().close(chat_id)
            except ApiError as exc:
                self._closing[chat_id] += 1
                if exc.code == "busy" and self._closing[chat_id] < CLOSE_TRIES:
                    continue
            except Exception:
                pass
            self._closing.pop(chat_id, None)

    # ---- what the person presses ------------------------------------------------------------------------------------------------------------------

    def start_waiting(self, run_id: str) -> dict:
        """「現在開始」 on a reminder: the run is queued as the person's own decision (``by: you``) and begins at the next pass (at once:
        ``poke``). ApiError 409 when the reminder is no longer waiting (it was started, skipped or put away)."""
        got = rt.update_run(run_id, ("waiting",), now=self.clock(), state="starting", by="you")
        if got is None:
            raise ApiError(409, "routine_gone", "這個提醒已經處理過，或已經收起來了。")
        self.poke()
        return got

    def skip_waiting(self, run_id: str) -> dict:
        """「這次跳過」: nothing is sent; the slot is used."""
        got = rt.update_run(run_id, ("waiting",), now=self.clock(), state="skipped", by="you", reason="you")
        if got is None:
            raise ApiError(409, "routine_gone", "這個提醒已經處理過，或已經收起來了。")
        return got

    def start_now(self, routine_id: str) -> dict:
        """「現在開始」 on a routine, whenever the person wants (also for one that is off): a run for this minute, ``why: now``. 404 for a
        routine that is not there; 409 when this minute already has a run of the routine."""
        routines, problem = rt.read_routines()
        if problem:
            raise ApiError(503, "routines_unreadable", rt.UNREADABLE)
        if not any(r["id"] == routine_id for r in routines):
            raise ApiError(404, "not_found", "找不到這件例行工作。")
        now = self.clock()
        slot = rr.slot_key(datetime.datetime.fromtimestamp(now, self.tz).replace(tzinfo=None))
        got = rt.new_run(routine_id, slot, state="starting", why="now", by="you", now=now)
        if got is None:
            raise ApiError(409, "routine_already", "這一分鐘已經開始過這件例行工作了。")
        self.poke()
        return got

    # ---- what the pages read -------------------------------------------------------------------------------------------------------------------

    def waiting_rows(self) -> list:
        """The reminders that wait for the person, for the line on every page: {kind, run_id, routine_id, name, slot, due_at}. Only a name,
        a time and ids: no content."""
        routines, problem = rt.read_routines()
        runs, runs_problem = rt.read_runs()
        if problem or runs_problem:
            return []
        by_id = {r["id"]: r for r in routines}
        rows = []
        for run in runs:
            routine = by_id.get(run["routine_id"])
            if run["state"] == "waiting" and routine is not None and routine["enabled"]:
                rows.append({"kind": "routine_due", "run_id": run["run_id"], "routine_id": routine["id"], "name": routine["name"],
                             "slot": run["slot"], "due_at": rr.slot_due(run["slot"], self.tz)})
        return sorted(rows, key=lambda row: (row["due_at"] or 0.0, row["run_id"]))

    def actions(self) -> list:
        """The runs VBear began by itself (item 3), for 「AI 自己做了什麼」: {at, kind, what, by, by_text, routine_id, chat_id, run_id}."""
        routines, _ = rt.read_routines()
        names = {r["id"]: r["name"] for r in routines}
        rows = []
        for run in rt.read_runs()[0]:
            if run["by"] != "auto3" or run["started_at"] is None:
                continue
            name = names.get(run["routine_id"])
            label = f"「{name}」" if name else "（已刪除的例行工作）"
            what = f"例行工作{label}補做了一次" if run["why"] == "catch_up" else f"例行工作{label}開始了"
            rows.append({"at": run["started_at"], "kind": "routine_started", "what": what, "by": "auto3", "by_text": "自己動手第 3 項",
                         "routine_id": run["routine_id"], "chat_id": run["chat_id"], "run_id": run["run_id"], "slot": run["slot"]})
        return rows
