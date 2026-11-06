"""The chat engine table (P39-1): a new chat engine is one more row of ``chat_engines.TABLE``, not an ``if engine == ...``
in every place that chats. A made-up engine (``fake-chat``, AI tool ``fakeai``) is added by patching one row into the
table; nothing here starts a process, reaches a model or touches the network. Synthetic state folder under /tmp."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import chat_service
from vbear.api_error import ApiError
from vbear.runtime import agent_sessions as a, chat_engines as ce, chat_store as cs, daemon_chat

FAKE_UUID_FIELD = "fake_session_id"
FAKE = ce.ChatEngine(
    engine="fake-chat", tool="fakeai", noun="Fake 聊天", check_mode="fake-chat", uuid_fields=(FAKE_UUID_FIELD,),
    daemon_send="_fake_send", manifest_problem="fake_chat_manifest_problem", launch_settings="fake_chat_expected_settings",
    support_key="fake", state="fake_state", binary="fake_binary", verifier="fake_verifier",
    fields="_fake_fields", verify="_verify_fake", money="Fake 的記帳說明。")
FAKE_PROFILE = {"id": "p-fake", "name": "Fake", "enabled": True, "model": {"tool": "fakeai", "model_id": None}}


class TableCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbe-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.object(ce, "TABLE", ce.TABLE + (FAKE,)),
                  mock.patch.object(a, "fake_chat_manifest_problem", lambda m: "fake problem", create=True)):
            p.start()
            self.addCleanup(p.stop)


class RowIsEnoughTests(TableCase):
    def test_the_card_gate_and_the_engine_follow_from_the_row(self):
        self.assertEqual(chat_service.card_gate(FAKE_PROFILE), (True, "", ""))
        self.assertEqual(chat_service.engine_of(FAKE_PROFILE), "fake-chat")
        other = dict(FAKE_PROFILE, model={"tool": "nobody"})
        self.assertEqual(chat_service.card_gate(other)[1], "card_tool_unsupported")
        self.assertIsNone(chat_service.engine_of(other))

    def test_the_store_creates_and_reads_a_chat_of_the_engine(self):
        chat = cs.create(self.tmp, "p-fake", now=1.0, engine="fake-chat")
        self.assertEqual(set(chat), {"v", "id", "profile_id", "created_at", "engine", FAKE_UUID_FIELD})
        self.assertEqual(cs.load(self.tmp, chat["id"]), chat)
        with self.assertRaises(cs.ChatStoreError):
            cs.create(self.tmp, "p-fake", now=1.0, engine="nope-chat")

    def test_the_store_still_refuses_a_bad_field_of_the_engine(self):
        chat = cs.create(self.tmp, "p-fake", now=1.0, engine="fake-chat")
        path = self.tmp / "chats" / chat["id"] / cs.CHAT_JSON
        os.chmod(path, 0o600)
        path.write_text(path.read_text().replace(chat[FAKE_UUID_FIELD], "not-a-uuid"))
        with self.assertRaises(cs.ChatStoreError) as ctx:
            cs.load(self.tmp, chat["id"])
        self.assertEqual(ctx.exception.code, "damaged")

    def test_support_names_the_engine_with_its_state_verifier_and_money(self):
        service = chat_service.ChatService(mock.Mock(), claude=lambda: (None, None, "no claude"),
                                           codex=lambda: {"state": "not_installed"}, base=self.tmp)
        service.fake_state = lambda: {"state": "ready", "version": "9.9.9"}
        service.fake_verifier = mock.Mock(status=lambda: {"running": False})
        got = service.support()
        self.assertEqual(got["fake"], {"state": "ready", "version": "9.9.9", "engine": "fake-chat",
                                       "money": "Fake 的記帳說明。", "verify": {"running": False}})
        self.assertEqual(got["codex"]["engine"], "codex-chat")          # the rows that were there are still there

    def test_verify_goes_to_the_rows_method_and_an_unknown_tool_is_refused(self):
        service = chat_service.ChatService(mock.Mock(), base=self.tmp)
        service._verify_fake = lambda wanted: {"asked": wanted}
        self.assertEqual(service.verify_start({"engine": "fakeai", "version": "1.2.3"}), {"asked": "1.2.3"})
        with self.assertRaises(ApiError) as ctx:
            service.verify_start({"engine": "nobody"})
        self.assertEqual(ctx.exception.code, "bad_request")

    def test_a_message_asks_the_daemon_with_the_fields_the_row_builds(self):
        chat = cs.create(self.tmp, "p-fake", now=1.0, engine="fake-chat")
        service = chat_service.ChatService(mock.Mock(), profile=lambda pid: FAKE_PROFILE, base=self.tmp)
        service._fake_fields = lambda chat_id, text, profile: {"chat_id": chat_id, "text": text, "engine": "fake-chat",
                                                               "model_id": None}
        with mock.patch.object(chat_service.daemon_client, "call",
                               return_value={"turn": 1, "cap_usd": "0.50", "process": "new"}) as call:
            got = service.send(chat["id"], {"text": "hello"})
        self.assertEqual(got, {"turn": 1, "cap_usd": "0.50", "process": "new"})
        self.assertEqual(call.call_args.args[1], "chat_send")
        self.assertEqual(call.call_args.kwargs["engine"], "fake-chat")
        self.assertEqual(call.call_args.kwargs["text"], "hello")

    def test_a_chat_whose_card_changed_tool_cannot_go_on(self):
        chat = cs.create(self.tmp, "p-fake", now=1.0, engine="fake-chat")
        claude_card = dict(FAKE_PROFILE, model={"tool": "claude"})
        service = chat_service.ChatService(mock.Mock(), profile=lambda pid: claude_card, base=self.tmp)
        with self.assertRaises(ApiError) as ctx:
            service.send(chat["id"], {"text": "hello"})
        self.assertEqual(ctx.exception.code, "card_tool_changed")

    def test_the_daemon_sends_a_message_through_the_rows_method(self):
        seen = []
        tmp = self.tmp

        class Ops(daemon_chat.ChatOps):
            base = tmp
            _shutdown_requested = False

            def _fake_send(self, rid, chat, text, cli, model_id, instructions):
                seen.append((rid, chat["engine"], text, model_id, instructions))
                return daemon_chat._ok(rid, {"turn": 1, "cap_usd": "0.50", "process": "new"})

        chat = cs.create(self.tmp, "p-fake", now=1.0, engine="fake-chat")
        cli = {"binary": "/x/fake", "version": "1.0.0", "identity": [1, 2]}
        got = Ops()._op_chat_send("r1", {"chat_id": chat["id"], "text": "hello", "cli": cli, "model_id": None,
                                         "engine": "fake-chat"})
        self.assertEqual(got["result"]["process"], "new")
        self.assertEqual(seen, [("r1", "fake-chat", "hello", None, None)])
        wrong = Ops()._op_chat_send("r2", {"chat_id": chat["id"], "text": "hi", "cli": cli, "model_id": None,
                                           "engine": "claude-chat"})
        self.assertEqual(wrong["error"]["code"], "bad_request")

    def test_the_launch_code_knows_the_engine_and_will_not_run_it_in_a_terminal(self):
        self.assertTrue(a.is_known_engine("fake-chat"))
        self.assertFalse(a.is_known_engine("nope-chat"))
        self.assertEqual(a.chat_engine_manifest_problem({"engine": "fake-chat"}), "Fake 聊天 manifest 不符（fake problem）")
        with self.assertRaises(a.LaunchRefused) as ctx:
            a.managed_argv({"engine": "fake-chat"})
        self.assertEqual(ctx.exception.code, "manifest_invalid")
        self.assertIn("Fake 聊天", str(ctx.exception))


class RowsThatWereThereTests(unittest.TestCase):
    def test_the_two_engines_of_v0_13_are_rows_with_their_old_names(self):
        self.assertEqual([(r.tool, r.engine, r.check_mode) for r in ce.TABLE],
                         [("claude", "claude-chat", "chat"), ("codex", "codex-chat", "codex-chat")])
        self.assertEqual(ce.engine_ids(), ("claude-chat", "codex-chat"))
        self.assertIs(ce.by_tool("codex"), ce.by_engine("codex-chat"))
        self.assertIsNone(ce.by_tool(["not", "hashable"]))
        self.assertIsNone(ce.by_engine("grok-chat"))
