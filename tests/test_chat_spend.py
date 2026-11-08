"""The chats share the day's limit with the meetings and the staffing meetings (P36-1): the boards count a chat's
turns (a running one at its cap), and the ledger says it includes them. A chat record that does not read whole makes
the day unknown, never less, for the chats, the meetings and the staffing meetings alike, unless all of it was written
before that day. Synthetic HOME and VBEAR_HOME; no CLI runs."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests import test_staffing_runner as tsr
from vbear import config as cfg, meeting_runner as mr, meetings as mt, staffing as st, staffing_runner as sr
from vbear.runtime import chat_store as cs

LATER = 2 * 86400                  # a day after tomorrow: whatever is written now was written before it


def spend(base, profile="emp-1", *, costs=("0.12", None), cap="0.3") -> str:
    """A chat with one turn per cost (None: still running), written now."""
    chat = cs.create(base, profile, now=time.time())
    log = cs.ChatLog(base, chat["id"])
    try:
        for n, cost in enumerate(costs, 1):
            log.append("user_message", {"turn": n, "text": "hi"}, now=time.time())
            log.append("turn_started", {"turn": n, "cap_usd": cap}, now=time.time())
            if cost:
                log.append("turn_ended", {"turn": n, "cost_usd": cost, "reported": True, "total_usd": float(cost),
                                          "reason": "result", "subtype": "success", "is_error": False},
                           now=time.time())
    finally:
        log.close()
    return chat["id"]


def cut_second_line(base, chat_id):
    path = Path(base) / "chats" / chat_id / "events.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    lines[1] = lines[1][: len(lines[1]) // 2] + "\n"
    path.write_text("".join(lines))


class ChatDay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbsp-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        self.chat_id = spend(self.base)
        self.meetings = mr.MeetingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        self.staffing = sr.StaffingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)

    def assert_unknown(self):
        with self.assertRaises(cs.ChatStoreError) as got:
            cs.day_spent(self.base, time.time())
        self.assertEqual(got.exception.code, "spend_unknown")
        for runner in (self.meetings, self.staffing):
            for ask in (runner._day, lambda: runner._blockers(Decimal("0.1"), Decimal("1"), mt.limits_from({})),
                        runner.spend_records):
                with self.assertRaises(mt.MeetingError) as got:
                    ask()
                self.assertEqual(got.exception.code, "spend_unknown", (runner, ask))
        with self.assertRaises(mt.MeetingError) as got:
            self.meetings.ledger({})
        self.assertEqual(got.exception.code, "spend_unknown")


class SharedDayTests(ChatDay):
    def test_both_boards_count_the_chats(self):
        for runner in (self.meetings, self.staffing):
            self.assertEqual(runner._day(), Decimal("0.42"), runner)          # 0.12 spent, 0.30 running at its cap
        ledger = self.meetings.ledger({})
        self.assertEqual((ledger["spent_usd"], ledger["includes"]), ("0.42", ["meetings", "staffing", "chats", "setup_try", "chief", "memory_suggest", "skill_suggest"]))
        self.assertEqual(ledger["lamp"], "green")


class DamagedRecordTests(ChatDay):
    def test_a_chat_damaged_in_the_middle_makes_the_day_unknown(self):
        cut_second_line(self.base, self.chat_id)
        self.assertTrue(cs.read_events(self.base, self.chat_id).problem)
        self.assert_unknown()

    def test_a_chat_missing_its_events_makes_the_day_unknown(self):
        (self.base / "chats" / self.chat_id / "events.jsonl").unlink()
        self.assert_unknown()

    def test_chats_that_cannot_be_listed_make_the_day_unknown(self):
        os.chmod(self.base / "chats", 0o750)
        self.addCleanup(os.chmod, self.base / "chats", 0o700)
        self.assert_unknown()

    def test_a_deleted_chats_damaged_spend_record_makes_the_day_unknown(self):
        done = spend(self.base, "emp-2", costs=("0.05",))
        cs.delete(self.base, done, now=time.time())
        self.assertEqual(cs.day_spent(self.base, time.time()), Decimal("0.47"))
        path = self.base / "chat-spend" / f"{done}.json"
        path.write_text(path.read_text()[:-20])
        self.assert_unknown()

    def test_a_spend_record_that_is_gone_counts_nothing(self):
        done = spend(self.base, "emp-2", costs=("0.05",))
        cs.delete(self.base, done, now=time.time())
        (self.base / "chat-spend" / f"{done}.json").unlink()         # pruned: the chat folder is gone too
        self.assertEqual(cs.day_spent(self.base, time.time()), Decimal("0.42"))

    def test_a_chat_half_way_through_its_deletion_counts_what_it_kept(self):
        done = spend(self.base, "emp-2", costs=("0.05",))
        real_rmdir = os.rmdir
        seen = []

        def rmdir(path, *a, **k):                    # the moment its files are gone but not its folder
            seen.append(cs.day_spent(self.base, time.time()))
            return real_rmdir(path, *a, **k)
        with mock.patch("vbear.runtime.chat_store.os.rmdir", rmdir):
            cs.delete(self.base, done, now=time.time())
        self.assertEqual(seen, [Decimal("0.47")])

    def test_a_record_written_before_the_day_cannot_change_it(self):
        cut_second_line(self.base, self.chat_id)
        other = spend(self.base, "emp-2", costs=("0.05",))
        cs.delete(self.base, other, now=time.time())
        path = self.base / "chat-spend" / f"{other}.json"
        path.write_text(path.read_text()[:-20])
        self.assertEqual(cs.day_spent(self.base, time.time() + LATER), Decimal(0))

    def test_a_damaged_chat_is_not_deleted(self):
        cut_second_line(self.base, self.chat_id)
        with self.assertRaises(cs.ChatStoreError) as got:
            cs.delete(self.base, self.chat_id, now=time.time())
        self.assertEqual(got.exception.code, "damaged")
        self.assertTrue((self.base / "chats" / self.chat_id / "events.jsonl").exists())
        self.assertFalse((self.base / "chat-spend").exists())


class StaffingMeetingTests(tsr.Base):
    """A staffing meeting, end to end with a fake call, while a chat record of today stops reading whole."""

    def setUp(self):
        super().setUp()
        base = cfg.state_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.chat_id = spend(base, costs=("0.01",))

    def test_a_start_after_the_chat_was_damaged_says_the_day_is_unknown(self):
        runner = self.board()
        src = self.sources()
        preview = runner.preview(self.body(), src)
        self.assertTrue(preview["startable"], preview["blockers"])
        cut_second_line(cfg.state_dir(), self.chat_id)
        for ask in (lambda: runner.start(preview["preview_id"], src), lambda: runner.preview(self.body(), src)):
            with self.assertRaises(mt.MeetingError) as got:
                ask()
            self.assertEqual(got.exception.code, "spend_unknown")
        self.assertEqual(st.record_ids(), [])
        self.assertEqual(self.specs, [])

    def test_a_chat_damaged_during_the_meeting_stops_its_next_calls(self):
        def call(spec, cancel):
            self.specs.append(spec)
            cut_second_line(cfg.state_dir(), self.chat_id)
            return mr.CallResult(self.answer(spec), dict(tsr.EVIDENCE), Decimal("0.01"))
        m = self.run_board(self.board(call))
        self.assertEqual(len(self.specs), 1)
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]],
                         [("done", None), ("skipped", "spend_unknown"), ("skipped", "spend_unknown")])


if __name__ == "__main__":
    unittest.main()
