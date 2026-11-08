"""「自己動手」 item 5 (P44-4, ADR 0010 point 6, ADR 0003): a dispatch that stopped for a limit goes on by itself when the limit is over.

A dispatch pauses for the day's money (``daily_limit``, usable again at the local midnight) or for the AI tool's plan (``plan_limit``,
usable again at the time the AI tool said, which Codex gives and Claude Code does not). The page counts down to that time
(``countdown``). This module is what happens at the time:

* with item 5 off (anything but ``True`` at ``autonomy.read(conf)["auto_continue"]``, which is read in one place, ``_on``): nothing is
  pressed. The pause is only a row in the line over every page (``waiting_rows``) and the person presses 「繼續」 as before;
* with it on, two minutes after the time VBear presses 「繼續」 itself, as ``resume(dispatch_id, pause_seq)`` (the console hands over
  ``DispatchRunner.resume_dispatch(did, by="vbear", ...)``): the dispatch record gets a ``continued`` event by ``vbear`` (a value v0.17.1
  reads) and ``<state>/routines/auto-continue.jsonl`` one line, ``{at, dispatch_id, event_seq, pause_seq, reason, item: 5}``.

Only these: a pause that needs somebody to look (``uncertain``, ``interrupted``, ``runner_error``, ``turn_*``, ``busy``, ``limit`` ...), a
time the AI tool did not give, a time that went by more than 12 hours ago (VBear was closed or the Mac slept), a lamp that is still red or
a ledger that cannot be read, a plan whose last report is still full or cannot be read, a step that may or may not have been sent. Those
are only listed. Limits: once for each pause, 3 for each dispatch, 5 a day in all, and none when the dispatch stopped again within 10 minutes
for the same reason. The counts are read from the dispatch's own record as well as from the log, so a log that cannot be written does not
make the limits forget. A press that failed is not tried again for that pause.

A group never goes on by itself (ADR 0007 point 3): its paused round is only a row with the countdown, and ``group*.py`` do not import
this module. Nothing here writes ``config.json``, a role card or a chat, starts a program, or answers a question of a chat; the press
goes through the runner's own ``resume_dispatch``, after which the runner sends the next step with the chat's rules (every command and file
change asks the person, the day's limit holds). The log has ids, times, a reason code and a count: no name, no text.
"""

from __future__ import annotations

import datetime
import json
import os
import stat
import time

from . import autonomy, config as cfg, countdown, dispatch, groups

GRACE_S = 120.0                # the press comes this long after the time the limit is over
STALE_S = 12 * 3600.0          # a time that went by longer ago than this is only listed
PER_DISPATCH = 3
PER_DAY = 5
REPEAT_S = 600.0               # stopped again for the same reason within this long after a press: no more presses for that dispatch
LOG_NAME = "auto-continue.jsonl"
LOG_MAX = 1 << 20
STUCK = ("sending", "running")  # a step in one of these may have gone out: the person looks first


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def usage_full(usage, now: float) -> bool:
    """Whether the AI tool's last report says the plan is still full (True for a report that cannot be read, and for one that says full with
    no time to be usable again: the check fails closed)."""
    if not isinstance(usage, dict):
        return True
    explained = False
    for window in ("primary", "secondary"):
        pct, resets = usage.get(f"{window}_pct"), usage.get(f"{window}_resets_at")
        if isinstance(pct, int) and not isinstance(pct, bool) and pct >= 100:
            explained = True
            if not (isinstance(resets, int) and not isinstance(resets, bool) and resets <= now):
                return True                                   # no time to be usable again, or a time still ahead
    return bool(usage.get("reached")) and not explained       # "reached" that no window explains is not known to be over


class AutoContinue:
    """``conf``: a function returning the console's configuration (read for item 5 only). ``ledger``: a function returning the day's ledger
    (``lamp``). ``resume``: ``(dispatch_id, pause_seq) -> None``, the runner's press as ``vbear`` (raises when it cannot). ``usage``:
    ``(dispatch_id) -> the AI tool's last plan report or None`` (raises when the chat cannot be read). ``tz``: a zone, or None for the machine's."""

    def __init__(self, *, conf, ledger, resume, usage, clock=time.time, tz=None):
        self.conf = conf
        self.ledger = ledger
        self.resume = resume
        self.usage = usage
        self.clock = clock
        self.tz = tz
        self.last_error: str | None = None
        self._failed: set = set()                             # (dispatch id, pause seq) whose press failed: not tried again

    # ---- item 5 -------------------------------------------------------------------------------------------------------------

    def _on(self) -> bool:
        """Whether VBear presses 「繼續」 itself: 「自己動手」 item 5 and nothing else. False for anything that is not ``True``."""
        try:
            return autonomy.read(self.conf())["auto_continue"] is True
        except Exception:
            return False

    # ---- what the dispatches say ------------------------------------------------------------------------------------------------

    @staticmethod
    def _records() -> list:
        out = []
        for did in dispatch.record_ids():
            try:
                out.append(dispatch.load(did))
            except Exception:
                continue                                       # a record that cannot be read is not guessed at
        return out

    @staticmethod
    def _pause(rec: dict) -> dict | None:
        """The pause a record is in: {dispatch_id, name, reason, until, pause_seq, pause_at}, or None. ``pause_seq`` is None when the record
        has no ``paused`` event to point at (then nothing is pressed)."""
        pause = rec.get("pause")
        if rec.get("state") != "paused" or not isinstance(pause, dict):
            return None
        event = next((e for e in reversed(rec["events"]) if e["kind"] == "paused"), None)
        if event is not None and event.get("reason") != pause["reason"]:
            event = None
        return {"dispatch_id": rec["id"], "name": rec["plan"]["title"], "reason": pause["reason"], "until": pause["until"],
                "pause_seq": event["seq"] if event else None, "pause_at": event["at"] if event else None}

    @staticmethod
    def _presses(rec: dict) -> list:
        """The presses VBear made on this dispatch, from its own record: [(at, event seq, reason of the pause it ended)]."""
        out, reason = [], None
        for e in rec["events"]:
            if e["kind"] == "paused":
                reason = e["reason"]
            elif e["kind"] == "continued" and e["by"] == "vbear":
                out.append((e["at"], e["seq"], reason))
        return out

    # ---- the log ----------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _folder(make: bool):
        path = cfg.state_dir() / "routines"
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            if not make:
                return None
            cfg.ensure_state_dir()
            path.mkdir(mode=cfg.STATE_DIR_MODE, exist_ok=True)
            st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise OSError("not our own folder")
        return path

    def _log_rows(self) -> list:
        """Every line of the log that makes sense (the old half first); a line that does not is skipped."""
        try:
            folder = self._folder(False)
        except OSError:
            return []
        rows: list = []
        for name in (LOG_NAME + ".1", LOG_NAME):
            if folder is None:
                break
            try:
                raw = (folder / name).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for line in raw.splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(row, dict) and row.get("item") == 5 and isinstance(row.get("dispatch_id"), str) and _num(row.get("at"))
                        and _num(row.get("event_seq")) and _num(row.get("pause_seq"))):
                    rows.append(row)
        return rows

    def _append(self, row: dict) -> None:
        folder = self._folder(True)
        path = folder / LOG_NAME
        try:
            if os.lstat(path).st_size >= LOG_MAX:
                os.replace(path, folder / (LOG_NAME + ".1"))
        except FileNotFoundError:
            pass
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
        try:
            os.fchmod(fd, cfg.STATE_FILE_MODE)
            os.write(fd, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
        finally:
            os.close(fd)

    def taken(self) -> set:
        """{(dispatch id, event seq)} of the ``continued`` events that were item 5's, for 「AI 自己做了什麼」."""
        return {(r["dispatch_id"], int(r["event_seq"])) for r in self._log_rows()}

    # ---- the pass ---------------------------------------------------------------------------------------------------------------------

    def _day(self, ts: float) -> datetime.date:
        return datetime.datetime.fromtimestamp(ts, self.tz).date()

    def tick(self) -> dict:
        """One pass: {dispatch id: "continued" | "failed"} for what was pressed. With item 5 off nothing is read and nothing is pressed."""
        if not self._on():
            return {}
        now = self.clock()
        out: dict = {}
        records = self._records()
        log = self._log_rows()
        today = self._day(now)
        day_log = sum(1 for r in log if self._day(r["at"]) == today)
        day_rec = sum(1 for rec in records for at, _, _ in self._presses(rec) if self._day(at) == today)
        day = max(day_log, day_rec)
        for rec in records:
            info = self._pause(rec)
            if info is None or info["reason"] not in countdown.REASONS:
                continue
            why = self._why_not(rec, info, now, log, day)
            if why is not None:
                continue
            key = (info["dispatch_id"], info["pause_seq"])
            try:
                self.resume(info["dispatch_id"], info["pause_seq"])
            except Exception:
                self._failed.add(key)
                self.last_error = "resume_failed"
                out[info["dispatch_id"]] = "failed"
                continue
            day += 1
            out[info["dispatch_id"]] = "continued"
            self._record(info, now)
        return out

    def _why_not(self, rec: dict, info: dict, now: float, log: list, day: int) -> str | None:
        """None when this pause may be pressed now, else why not (a short code: kept for the tests and the reader, never written down)."""
        did, seq, until = info["dispatch_id"], info["pause_seq"], info["until"]
        if seq is None or info["pause_at"] is None:
            return "no_event"
        if not _num(until) or until <= 0:
            return "unknown"
        if now < until + GRACE_S:
            return "counting"
        if now - until > STALE_S:
            return "stale"
        if (did, seq) in self._failed:
            return "failed_before"
        if any(r["dispatch_id"] == did and r["pause_seq"] == seq for r in log):
            return "once"
        if any(s["state"] in STUCK for s in rec["steps"]):
            return "unsettled"
        mine = [r for r in log if r["dispatch_id"] == did]
        presses = self._presses(rec)
        if max(len(mine), len(presses)) >= PER_DISPATCH:
            return "dispatch_limit"
        if day >= PER_DAY:
            return "day_limit"
        before = [(r["at"], r["event_seq"], r.get("reason")) for r in mine] + presses
        if any(reason == info["reason"] and s < seq and info["pause_at"] - at <= REPEAT_S for at, s, reason in before):
            return "repeat"
        if not self._lamp_ok():
            return "lamp"
        if info["reason"] == "plan_limit":
            try:
                if usage_full(self.usage(did), now):
                    return "usage"
            except Exception:
                return "usage"
        return None

    def _lamp_ok(self) -> bool:
        try:
            ledger = self.ledger()
            return isinstance(ledger, dict) and ledger.get("lamp") in ("green", "yellow")
        except Exception:
            return False

    def _record(self, info: dict, now: float) -> None:
        """One line in the log for a press that was made. A log that cannot be written is said by ``last_error`` and changes nothing else."""
        try:
            rec = dispatch.load(info["dispatch_id"])
            event = next((e for e in reversed(rec["events"]) if e["kind"] == "continued" and e["by"] == "vbear"), None)
            if event is None:
                return
            self._append({"at": now, "dispatch_id": info["dispatch_id"], "event_seq": event["seq"], "pause_seq": info["pause_seq"],
                          "reason": info["reason"], "item": 5})
        except Exception:
            self.last_error = "log_failed"

    # ---- what the pages read -------------------------------------------------------------------------------------------------------

    def waiting_rows(self) -> list:
        """The paused dispatches and groups that wait for a limit to be over, for the line over every page: {kind, ..., name, state, until,
        text}. A name, a time and an id each: no content. A dispatch's reason is also given; a group's is always the day's money."""
        now = self.clock()
        rows: list = []
        for rec in self._records():
            info = self._pause(rec)
            if info is None or info["reason"] not in countdown.REASONS:
                continue
            words = countdown.words(info["reason"], info["until"], now, self.tz)
            rows.append({"kind": "dispatch_resume", "dispatch_id": info["dispatch_id"], "name": info["name"], "reason": info["reason"],
                         "state": words["state"], "until": words["until"], "text": words["text"]})
        for gid in groups.record_ids():
            try:
                events = groups.read_log(gid)
                if events.problem:
                    continue
                rnd = groups.current_round(events.records)
                if rnd is None or groups.round_state(rnd) != "paused" or groups.stopped(rnd) or rnd["pause"]["reason"] != "daily_limit":
                    continue
                name = groups.load(gid)["name"]
                words = countdown.words("daily_limit", rnd["pause"]["until"], now, self.tz)
            except Exception:
                continue
            rows.append({"kind": "group_resume", "group_id": gid, "name": name, "state": words["state"], "until": words["until"],
                         "text": words["text"]})
        return sorted(rows, key=lambda r: (r["until"] is None, r["until"] or 0.0, r.get("dispatch_id") or r.get("group_id")))
