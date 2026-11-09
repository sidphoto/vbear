"""v0.20 P46-3: an AGY chat adds no kind of event to the chat record (ADR 0012): a chat written by v0.20.0 reads as a damaged one in
v0.19.0 only because of its engine value, never because of an event it does not know. The chats are played through the daemon with the
fake agy of tests/fake_agy_acp.py; synthetic HOME and VBEAR_HOME under /tmp."""

from __future__ import annotations

import json
import unittest

from tests.test_p46_agy_chat_daemon import AgyCase, file_call, permission
from vbear.runtime import chat_store as cs

# The kinds the chat record had in v0.19.0 (e0fc412), written out: a kind added to the store or written by an AGY chat fails here.
V0190_KINDS = frozenset({
    "chat_created", "user_message", "turn_started", "process_started", "session_ready", "reply", "tool_call", "tool_result", "card",
    "card_decision", "auto_allowed", "denied", "turn_ended", "process_ended", "anomaly", "error", "session_bound", "usage",
    "plan_usage", "card_edit_sent"})
V0190_FIELDS = {"v", "id", "profile_id", "created_at", "engine"}


class TheRecordHasNoNewKindTests(AgyCase):
    def test_the_store_has_the_kinds_it_had(self):
        self.assertEqual(set(cs.KINDS), V0190_KINDS)

    def test_every_kind_an_agy_chat_writes_is_one_of_them_and_reads_whole(self):
        written = set()
        # a plain turn, a command card allowed, one refused, a file card, an edit-and-ask-again, a read outside, a stop
        scenarios = [("text", None), ("permission", "allow"), ("permission", "deny"), (permission(**file_call()), "allow"),
                     ("edit-input", "modify"), ("cancel", "stop"), ("no-ask", None), ("auth-error", None)]
        for index, (script, how) in enumerate(scenarios):
            with self.subTest(script=script if isinstance(script, str) else "file", how=how):
                self.conf_path.with_name(self.conf_path.name + ".state.json").unlink(missing_ok=True)
                self.configure(script)
                chat_id = self.open_chat(f"emp-{index + 1}")
                self.assertTrue(self.send(chat_id)["ok"])
                if how in ("allow", "deny"):
                    self.assertTrue(self.answer(chat_id, self.wait_card(chat_id), how)["ok"])
                elif how == "modify":
                    first = self.wait_card(chat_id)
                    self.assertTrue(self.answer(chat_id, first, "modify", "echo two")["ok"])
                    second = self.wait(lambda: next((c for c in (self.events(chat_id)[1] or {}).get("cards", [])
                                                     if c["card_id"] != first["card_id"]), None), "the second card")
                    self.assertTrue(self.answer(chat_id, second, "allow")["ok"])
                    self.wait_turn(chat_id, 2)
                elif how == "stop":
                    self.wait_card(chat_id)
                    self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
                self.wait_turn(chat_id, 1)
                self.rpc("chat_close", chat_id=chat_id)
                self.wait_gone(chat_id)
                events = cs.read_events(self.base, chat_id)
                self.assertFalse(events.problem)
                for record in events.records:
                    self.assertIsNone(cs.record_problem(record), record)
                    written.add(record["kind"])
                state = cs.derive(events.records)
                self.assertIsNone(state.open_turn)
                self.assertFalse(state.process_open)
        self.assertLessEqual(written, V0190_KINDS)
        # what the scenarios were chosen to reach
        for kind in ("chat_created", "user_message", "turn_started", "process_started", "session_ready", "session_bound", "usage", "reply",
                     "tool_call", "tool_result", "card", "card_decision", "turn_ended", "process_ended", "error", "card_edit_sent"):
            self.assertIn(kind, written, kind)

    def test_the_only_thing_the_chat_file_says_about_the_engine_is_its_value(self):
        chat_id = self.open_chat()
        chat = json.loads((self.base / "chats" / chat_id / "chat.json").read_text())
        self.assertEqual(set(chat), V0190_FIELDS)
        self.assertEqual(chat["engine"], "agy-chat")
        self.configure("text")
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        again = json.loads((self.base / "chats" / chat_id / "chat.json").read_text())
        self.assertEqual(again, chat)

    def test_the_session_is_kept_the_way_a_codex_thread_is(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        state = cs.derive(cs.read_events(self.base, chat_id).records)
        self.assertEqual(state.thread_id, "00000000-0000-4000-8000-0000000000a1")
        self.assertEqual(state.next_turn, 2)


if __name__ == "__main__":
    unittest.main()
