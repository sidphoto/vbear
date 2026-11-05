"""A chat's record (P36-1): <state>/chats/<chat_id>/ with chat.json and an append-only events.jsonl, the role card's
work folder, and what the chats cost today. Synthetic HOME and VBEAR_HOME; no process is started."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear.runtime import chat_store as cs

KEY = "sk-ant-" + "fictionalfictional0123456789"          # shaped like a key, made up


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcs-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        self.now = time.time()

    def chat(self, profile="emp-1"):
        return cs.create(self.base, profile, now=self.now)

    def add(self, chat_id, kind, **data):
        log = cs.ChatLog(self.base, chat_id)
        try:
            return log.append(kind, data, now=self.now)
        finally:
            log.close()

    def turn(self, chat_id, n, cap="0.50", cost=None, total=None, at=None):
        at = self.now if at is None else at
        log = cs.ChatLog(self.base, chat_id)
        try:
            log.append("user_message", {"turn": n, "text": "hi"}, now=at)
            log.append("turn_started", {"turn": n, "cap_usd": cap}, now=at)
            if cost is not None:
                log.append("turn_ended", {"turn": n, "cost_usd": cost, "reported": total is not None,
                                          "total_usd": total, "reason": "result", "subtype": "success",
                                          "is_error": False}, now=at)
        finally:
            log.close()


class CreateTests(StoreCase):
    def test_a_new_chat(self):
        c = self.chat()
        self.assertTrue(cs.CHAT_RE.match(c["id"]))
        self.assertTrue(cs.UUID_RE.match(c["claude_session_id"]))
        self.assertEqual(cs.load(self.base, c["id"]), c)
        self.assertEqual(cs.list_ids(self.base), [c["id"]])
        d = self.base / "chats" / c["id"]
        for p, mode in ((self.base / "chats", 0o700), (d, 0o700), (d / "chat.json", 0o600),
                        (d / "events.jsonl", 0o600)):
            self.assertEqual(stat.S_IMODE(os.lstat(p).st_mode), mode, p)
        ev = cs.read_events(self.base, c["id"])
        self.assertEqual(ev.problem, "")
        self.assertEqual([(r["seq"], r["kind"], r["profile_id"]) for r in ev.records], [(1, "chat_created", "emp-1")])

    def test_ids_and_limits(self):
        for bad in ("../x", "c-ABC", "", None, "c-" + "0" * 15):
            with self.assertRaises(cs.ChatStoreError):
                cs.load(self.base, bad)
        with self.assertRaises(cs.ChatStoreError):
            cs.create(self.base, "../escape", now=self.now)
        with mock.patch.object(cs, "MAX_CHATS", 2):
            self.chat()
            self.chat()
            with self.assertRaises(cs.ChatStoreError) as cm:
                self.chat()
            self.assertEqual(cm.exception.code, "too_many")

    def test_a_link_or_a_changed_record_is_refused(self):
        c = self.chat()
        d = self.base / "chats" / c["id"]
        other = self.tmp / "elsewhere"
        shutil.move(str(d), str(other))
        d.symlink_to(other)
        with self.assertRaises(cs.ChatStoreError):
            cs.load(self.base, c["id"])
        with self.assertRaises(cs.ChatStoreError):
            cs.ChatLog(self.base, c["id"])
        d.unlink()
        shutil.move(str(other), str(d))
        rec = json.loads((d / "chat.json").read_text())
        (d / "chat.json").write_text(json.dumps(dict(rec, extra=1)))
        (d / "chat.json").chmod(0o600)
        with self.assertRaises(cs.ChatStoreError):
            cs.load(self.base, c["id"])


class EventTests(StoreCase):
    def test_append_and_read_after(self):
        c = self.chat()
        self.turn(c["id"], 1, cost="0.01", total=0.01)
        recs = cs.read_events(self.base, c["id"]).records
        self.assertEqual([r["seq"] for r in recs], [1, 2, 3, 4])
        self.assertEqual([r["kind"] for r in cs.read_events(self.base, c["id"], after=2).records],
                         ["turn_started", "turn_ended"])
        ev = cs.read_events(self.base, c["id"], after=0, limit=2)
        self.assertEqual([r["seq"] for r in ev.records], [1, 2])
        self.assertEqual(ev.last_seq, 4)

    def test_secrets_are_masked_and_long_text_cut_before_it_is_written(self):
        c = self.chat()
        self.add(c["id"], "user_message", turn=1, text=f"my key is {KEY}")
        self.add(c["id"], "reply", turn=1, text="x" * (cs.MAX_REPLY + 10), truncated=False)
        self.add(c["id"], "card", turn=1, card_id="k-0123456789abcdef", tool="Bash",
                 input={"command": f"curl -H 'Authorization: Bearer {KEY}1' x"}, editable="command", state="asked",
                 reason="r")
        self.add(c["id"], "tool_result", turn=1, tool_use_id="toolu_1", tool="Bash", is_error=False,
                 text=f"token={KEY}\n" + "y" * 5000, truncated=False, source="user_temporary")
        raw = (self.base / "chats" / c["id"] / "events.jsonl").read_text()
        self.assertNotIn("fictionalfictional", raw)
        recs = cs.read_events(self.base, c["id"]).records
        reply = next(r for r in recs if r["kind"] == "reply")
        self.assertEqual((len(reply["text"]), reply["truncated"]), (cs.MAX_REPLY, True))
        res = next(r for r in recs if r["kind"] == "tool_result")
        self.assertTrue(res["truncated"])
        self.assertLessEqual(len(res["text"]), cs.MAX_EXCERPT)

    def test_nested_card_input_and_reasons_are_masked_and_cut(self):
        """Automated security review finding 2 (P36-1): a card's input is masked by key name and value at every
        level, every string in it is cut, and the reason of a card, an auto-allow and a refusal is masked too."""
        c = self.chat()
        self.add(c["id"], "card", turn=1, card_id="k-0123456789abcdef", tool="Edit",
                 input={"file_path": "/WORK/a", "edits": [{"old_string": "a", "new_string": "z" * (cs.MAX_EXCERPT + 50),
                                                            "meta": {"api_key": "plainvalue1", "token": "plainvalue2"}}],
                        "opts": {"nested": {"password": "hunter2hunter2"}}},
                 editable="new_string", state="asked", reason=f"because {KEY}")
        self.add(c["id"], "auto_allowed", turn=1, tool_use_id="toolu_2", tool="Read", summary="/WORK/a",
                 reason=f"token={KEY}")
        self.add(c["id"], "denied", turn=1, tool_use_id="toolu_3", tool="Write", summary="/x",
                 reason=f"key {KEY}", by="vbear")
        raw = (self.base / "chats" / c["id"] / "events.jsonl").read_text()
        for secret in ("fictionalfictional", "plainvalue1", "plainvalue2", "hunter2hunter2"):
            self.assertNotIn(secret, raw)
        card = next(r for r in cs.read_events(self.base, c["id"]).records if r["kind"] == "card")
        edit = card["input"]["edits"][0]
        self.assertEqual(len(edit["new_string"]), cs.MAX_EXCERPT)
        self.assertEqual(edit["old_string"], "a")
        self.assertEqual(card["input"]["file_path"], "/WORK/a")

    def test_what_is_written_always_reads_back(self):
        """A card input nested deeper than the reader allows is cut short instead of making the file unreadable."""
        c = self.chat()
        deep = "x"
        for _ in range(40):
            deep = {"a": deep}
        self.add(c["id"], "card", turn=1, card_id="k-0123456789abcdef", tool="Other", input={"d": deep},
                 editable=None, state="asked", reason="r")
        ev = cs.read_events(self.base, c["id"])
        self.assertEqual(ev.problem, "")
        self.assertEqual(len(ev.records), 2)

    def test_a_wrong_record_is_refused_and_nothing_is_written(self):
        c = self.chat()
        size = (self.base / "chats" / c["id"] / "events.jsonl").stat().st_size
        for kind, data in (("no_such_kind", {}), ("user_message", {"turn": 1}),
                           ("user_message", {"turn": 1, "text": "x", "extra": 1}),
                           ("user_message", {"turn": 0, "text": "x"}), ("turn_started", {"turn": 1, "cap_usd": "-1"}),
                           ("turn_started", {"turn": 1, "cap_usd": "NaN"}), ("user_message", {"turn": 1, "text": "\ud800"})):
            with self.assertRaises(cs.ChatStoreError, msg=kind):
                self.add(c["id"], kind, **data)
        self.assertEqual((self.base / "chats" / c["id"] / "events.jsonl").stat().st_size, size)

    def test_a_damaged_or_cut_file_is_reported_and_not_appended_to(self):
        c = self.chat()
        path = self.base / "chats" / c["id"] / "events.jsonl"
        with open(path, "a") as f:
            f.write('{"seq": 2, "at": 1')
        ev = cs.read_events(self.base, c["id"])
        self.assertTrue(ev.problem)
        self.assertEqual(len(ev.records), 1)
        with self.assertRaises(cs.ChatStoreError):
            cs.ChatLog(self.base, c["id"])
        path.write_text(path.read_text().split("\n")[0] + "\n" + json.dumps(
            {"seq": 2, "at": self.now, "kind": "user_message", "turn": 1, "text": "x", "x": 1}) + "\n")
        self.assertTrue(cs.read_events(self.base, c["id"]).problem)

    def test_the_file_has_a_size_limit(self):
        c = self.chat()
        with mock.patch.object(cs, "MAX_EVENTS_BYTES", 600):
            log = cs.ChatLog(self.base, c["id"])
            try:
                with self.assertRaises(cs.ChatStoreError) as cm:
                    for n in range(1, 20):
                        log.append("user_message", {"turn": n, "text": "y" * 100}, now=self.now)
                self.assertEqual(cm.exception.code, "full")
            finally:
                log.close()


class DeriveTests(StoreCase):
    def test_turns_costs_and_the_last_total(self):
        c = self.chat()
        self.turn(c["id"], 1, cost="0.001", total=0.001)
        self.turn(c["id"], 2, cap="0.40", cost="0.40", total=None)            # stopped: the cap
        self.turn(c["id"], 3, cap="0.30")                                      # still running
        st = cs.derive(cs.read_events(self.base, c["id"]).records)
        self.assertEqual([(t.turn, t.cap, t.cost) for t in st.turns],
                         [(1, Decimal("0.50"), Decimal("0.001")), (2, Decimal("0.40"), Decimal("0.40")),
                          (3, Decimal("0.30"), None)])
        self.assertEqual(st.last_total, 0.001)
        self.assertEqual(st.next_turn, 4)
        self.assertEqual(st.open_turn.turn, 3)
        self.assertFalse(st.session_ready)
        self.add(c["id"], "session_ready", claude_code_version="2.1.318", permission_mode="default",
                 model="claude-haiku-5-5")
        self.assertTrue(cs.derive(cs.read_events(self.base, c["id"]).records).session_ready)

    def test_recovery_closes_a_turn_a_stopped_daemon_left_at_its_cap(self):
        c = self.chat()
        self.turn(c["id"], 1, cap="0.25")
        self.add(c["id"], "process_started", mode="new", budget_usd="0.25", instructions=False)
        self.assertEqual(cs.recover(self.base, now=self.now), [c["id"]])
        recs = cs.read_events(self.base, c["id"]).records
        end = [r for r in recs if r["kind"] == "turn_ended"]
        self.assertEqual([(r["cost_usd"], r["reported"], r["reason"]) for r in end], [("0.25", False, "daemon_restart")])
        self.assertEqual(recs[-1]["kind"], "process_ended")
        self.assertEqual(cs.recover(self.base, now=self.now), [])


class SpendTests(StoreCase):
    def test_today_counts_costs_and_running_caps_not_yesterday(self):
        a, b = self.chat(), self.chat("emp-2")
        self.turn(a["id"], 1, cost="0.10", total=0.1)
        self.turn(a["id"], 2, cap="0.30")
        self.turn(b["id"], 1, cost="0.05", total=0.05, at=self.now - 3 * 86400)
        self.assertEqual(cs.day_spent(self.base, self.now), Decimal("0.40"))

    def test_deleting_a_chat_keeps_what_it_cost_today(self):
        a = self.chat()
        self.turn(a["id"], 1, cost="0.10", total=0.1)
        self.turn(a["id"], 2, cost="0.20", total=0.3, at=self.now - 3 * 86400)
        cs.delete(self.base, a["id"], now=self.now)
        self.assertFalse((self.base / "chats" / a["id"]).exists())
        self.assertEqual(cs.list_ids(self.base), [])
        self.assertEqual(cs.day_spent(self.base, self.now), Decimal("0.10"))
        with self.assertRaises(cs.ChatStoreError):
            cs.delete(self.base, a["id"], now=self.now)

    def test_the_limits(self):
        self.assertEqual(cs.limits_from({}), {"per_turn_usd": Decimal("0.50")})
        self.assertEqual(cs.limits_from({"chat_limits": {"per_turn_usd": 1.25}}), {"per_turn_usd": Decimal("1.25")})
        for bad in (0, -1, 6, "1", True, None, float("nan")):
            self.assertEqual(cs.limits_from({"chat_limits": {"per_turn_usd": bad}}),
                             {"per_turn_usd": Decimal("0.50")}, bad)

    def test_a_chat_reads_as_a_record_the_meetings_day_can_count(self):
        from vbear import meetings as mt
        a = self.chat()
        self.turn(a["id"], 1, cost="0.10", total=0.1)
        self.turn(a["id"], 2, cap="0.30")
        ids, load, per_call = cs.spend_kind()
        self.assertIn(a["id"], ids())
        rec = load(a["id"])
        self.assertEqual(mt.daily_spent([rec], self.now, per_call), Decimal("0.40"))
        cs.ChatLog(self.base, a["id"]).close()


class WorkDirTests(StoreCase):
    def test_one_private_folder_per_role_card(self):
        a = cs.ensure_work_dir(self.base, "Emp")
        self.assertEqual(cs.ensure_work_dir(self.base, "Emp"), a)
        b = cs.ensure_work_dir(self.base, "emp")                          # a case-blind file system: still apart
        self.assertNotEqual(a, b)
        self.assertEqual(os.path.dirname(a), str(self.base / "chat-work"))
        self.assertEqual(stat.S_IMODE(os.lstat(a).st_mode), 0o700)
        with self.assertRaises(cs.ChatStoreError):
            cs.ensure_work_dir(self.base, "../x")
        os.rmdir(b)
        os.symlink(self.tmp, b)
        with self.assertRaises(cs.ChatStoreError):
            cs.ensure_work_dir(self.base, "emp")


if __name__ == "__main__":
    unittest.main()
