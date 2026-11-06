"""P40-3: a message VBear sends for a dispatch carries its ``origin`` (the dispatch and the step) into the chat's record.

Three seams: the chat record (``user_message`` may hold an ``origin``; a record of before still reads), the runtime daemon's
``chat_send`` (checks the shape, writes it into the record, a new process or a reused one), and the console (only an internal
method of the chat service can send one; the browser's route refuses it). Synthetic HOME and VBEAR_HOME; the Claude Code is the
fake one of the chat tests; nothing reaches a model or the network."""

from __future__ import annotations

import unittest

from tests.test_chat_api import ApiCase
from tests.test_chat_daemon import ChatCase, clean
from tests.test_chat_store import StoreCase
from tests.test_p38_codex_chat_daemon import CodexCase
from vbear.runtime import chat_store as cs

ORIGIN = {"dispatch": "d-0123456789ab", "step": 2}


class RecordTests(StoreCase):
    def test_a_user_message_may_hold_an_origin_and_reads_back_with_it(self):
        chat = self.chat()
        self.add(chat["id"], "user_message", turn=1, text="hello", origin=dict(ORIGIN))
        self.add(chat["id"], "user_message", turn=2, text="hi again")
        recs = [r for r in cs.read_events(self.base, chat["id"]).records if r["kind"] == "user_message"]
        self.assertEqual(recs[0]["origin"], ORIGIN)
        self.assertNotIn("origin", recs[1], "a record of before has none, and reads as it did")
        self.assertIsNone(cs.record_problem(recs[0]))
        self.assertIsNone(cs.record_problem(recs[1]))

    def test_an_origin_of_another_shape_is_not_kept(self):
        chat = self.chat()
        for bad in ({"dispatch": "d-0123456789ab"}, {"dispatch": "d-0123456789ab", "step": 0},
                    {"dispatch": "d-0123456789ab", "step": 5}, {"dispatch": "d-0123456789ab", "step": True},
                    {"dispatch": "d-0123456789AB", "step": 1}, {"dispatch": "x-0123456789ab", "step": 1},
                    {"dispatch": "d-0123456789ab", "step": 1, "by": "you"}, "d-0123456789ab", None, 3, []):
            with self.assertRaises(cs.ChatStoreError, msg=repr(bad)):
                self.add(chat["id"], "user_message", turn=1, text="hello", origin=bad)
        self.assertEqual([r for r in cs.read_events(self.base, chat["id"]).records if r["kind"] == "user_message"], [])

    def test_only_a_user_message_has_an_origin(self):
        chat = self.chat()
        with self.assertRaises(cs.ChatStoreError):
            self.add(chat["id"], "turn_started", turn=1, cap_usd="0.50", origin=dict(ORIGIN))

    def test_the_shape_check_is_one_function(self):
        self.assertTrue(cs.origin_ok(dict(ORIGIN)))
        self.assertFalse(cs.origin_ok({"dispatch": "d-0123456789ab", "step": 9}))


class DaemonTests(ChatCase):
    def test_chat_send_writes_the_origin_into_the_record_for_a_new_process_and_a_reused_one(self):
        self.configure([clean("ask", 4), clean("ask", 4)])
        chat_id = self.open_chat()
        r = self.rpc("chat_send", chat_id=chat_id, text="step one", cli=self.cli(), model_id="claude-haiku-5-5",
                     origin={"dispatch": "d-0123456789ab", "step": 1})
        self.assertTrue(r["ok"], r)
        self.wait(lambda: any(x["kind"] == "turn_ended" for x in self.events(chat_id)[0]), "the first turn")
        r = self.rpc("chat_send", chat_id=chat_id, text="step two", cli=self.cli(), model_id="claude-haiku-5-5",
                     origin={"dispatch": "d-0123456789ab", "step": 2})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["process"], "reused")
        said = [x for x in self.events(chat_id)[0] if x["kind"] == "user_message"]
        self.assertEqual([x["origin"] for x in said],
                         [{"dispatch": "d-0123456789ab", "step": 1}, {"dispatch": "d-0123456789ab", "step": 2}])

    def test_a_message_without_an_origin_is_as_before(self):
        self.configure([clean("ask", 4)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        said = next(x for x in self.events(chat_id)[0] if x["kind"] == "user_message")
        self.assertNotIn("origin", said)

    def test_an_origin_of_another_shape_is_refused_before_anything_starts(self):
        chat_id = self.open_chat()
        for bad in ({"dispatch": "d-0123456789ab", "step": 7}, {"dispatch": "nope", "step": 1}, "d-0123456789ab", {}):
            r = self.rpc("chat_send", chat_id=chat_id, text="x", cli=self.cli(), model_id="claude-haiku-5-5", origin=bad)
            self.assertFalse(r["ok"], bad)
            self.assertEqual(r["error"]["code"], "bad_request")
        self.assertEqual(self.fake_log(), [], "nothing was started")
        self.assertEqual([x for x in self.events(chat_id)[0] if x["kind"] == "user_message"], [])


class CodexDaemonTests(CodexCase):
    def test_a_codex_chat_writes_the_origin_too(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        r = self.send(chat_id, "step one", origin={"dispatch": "d-0123456789ab", "step": 3})
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        said = next(x for x in self.events(chat_id)[0] if x["kind"] == "user_message")
        self.assertEqual(said["origin"], {"dispatch": "d-0123456789ab", "step": 3})

    def test_a_bad_origin_is_refused_before_a_process_starts(self):
        chat_id = self.open_chat()
        r = self.send(chat_id, "x", origin={"dispatch": "d-0123456789ab", "step": 0})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_request"))
        self.assertEqual(self.fake_log(), [])


class ConsoleTests(ApiCase):
    def test_the_browsers_route_does_not_take_an_origin(self):
        chat_id = self.open_http()
        status, out = self.call(f"/api/chats/{chat_id}/messages", "POST", {"text": "hi", "origin": dict(ORIGIN)})
        self.assertEqual(status, 400, out)
        self.assertEqual(self.fake_log(), [])

    def test_the_services_internal_method_sends_with_an_origin(self):
        self.configure([clean("ask", 4)])
        chat_id = self.open_http()
        out = self.svc.send_for_dispatch(chat_id, "step one", dict(ORIGIN))
        self.assertEqual(out["turn"], 1)
        v = self.view(chat_id)
        said = next(r for r in v["records"] if r["kind"] == "user_message")
        self.assertEqual((said["text"], said["origin"]), ("step one", ORIGIN))

    def test_the_internal_method_refuses_what_the_route_refuses(self):
        chat_id = self.open_http()
        from vbear.api_error import ApiError
        for bad_text in ("", "   ", None):
            with self.assertRaises(ApiError):
                self.svc.send_for_dispatch(chat_id, bad_text, dict(ORIGIN))
        with self.assertRaises(ApiError):
            self.svc.send_for_dispatch(chat_id, "x", {"dispatch": "d-0123456789ab", "step": 99})


if __name__ == "__main__":
    unittest.main()
