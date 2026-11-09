"""v0.20 P46-5 (ADR 0012): the other features take an AGY employee in, the way they took a Codex one (ADR 0006-0011). Memory and the shared
folder are off for AGY and switch on only with the person's yes to Google; the groups, the chief of staff, the dispatches, the routines,
the two suggestions, the team templates and the first CEO name Google where they name a company. Everything here is made up: a synthetic
HOME and VBEAR_HOME under /tmp, an AGY that is a stand-in answer of the chat service, no real AI tool is run and nothing reaches a network."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from tests.test_p46_agy_chat_api import ApiCase
from vbear import ai_tool_status, memory, shared_folder
from vbear.runtime import cli_versions


class AiToolStatusTests(unittest.TestCase):
    """The AGY row of the start-up page says whether the AGY that is installed has passed the chat check: read from the record, no command."""

    def row(self, version, verified):
        tool = next(t for t in ai_tool_status.ai_tools.REGISTRY if t.id == "agy")
        calls = []

        def run(argv, timeout, want_output):
            calls.append(list(argv[1:]))
            return (0, version + "\n") if want_output else (0, "")

        with mock.patch.object(ai_tool_status, "find_binary", return_value="/nowhere/agy"), \
                mock.patch.object(ai_tool_status, "_run", side_effect=run), \
                mock.patch.object(cli_versions, "agy_chat_verified_versions", return_value=tuple(verified)):
            return ai_tool_status._inspect(tool, 1.0), calls

    def test_an_installed_version_that_passed_is_verified(self):
        row, calls = self.row("1.5.3", ["1.5.3"])
        self.assertEqual(row["chat"], {"verified": True})
        self.assertEqual(calls, [["--version"]], "only the version is asked; the chat state is read from the record")

    def test_a_version_that_did_not_pass_is_not(self):
        row, _ = self.row("1.5.3", [])
        self.assertEqual(row["chat"], {"verified": False})
        row, _ = self.row("1.5.3", ["1.5.2"])
        self.assertEqual(row["chat"], {"verified": False})

    def test_not_installed_is_not_verified_and_no_other_tool_has_the_key(self):
        tool = next(t for t in ai_tool_status.ai_tools.REGISTRY if t.id == "agy")
        with mock.patch.object(ai_tool_status, "find_binary", return_value=None):
            self.assertEqual(ai_tool_status._inspect(tool, None)["chat"], {"verified": False})
        grok = next(t for t in ai_tool_status.ai_tools.REGISTRY if t.id == "grok")
        with mock.patch.object(ai_tool_status, "find_binary", return_value=None):
            self.assertNotIn("chat", ai_tool_status._inspect(grok, None))


class MemoryForAgyTests(ApiCase):
    """ADR 0008, ADR 0012: memory is off for an AGY employee until the person says yes to Google."""

    def test_the_default_is_off_and_the_company_is_google(self):
        self.assertIs(memory.DEFAULT_ON["agy-chat"], False)
        self.assertEqual(memory.COMPANY["agy-chat"], "Google")
        status, out = self.call("/api/memory")
        self.assertEqual(status, 200, out)
        mine = next(c for c in out["cards"] if c["profile_id"] == self.emp)
        self.assertEqual((mine["company"], mine["can_chat"], mine["on"]), ("Google", True, False))
        self.assertIn("Google", out["where_text"])
        self.assertIn("Anthropic", out["where_text"])
        self.assertIn("OpenAI", out["where_text"])

    def test_switching_on_without_the_yes_is_409_and_with_it_is_200(self):
        before = self.call("/api/memory")[1]
        status, out = self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True})
        self.assertEqual((status, out["code"], out["warn"]), (409, "memory_confirm", ["send_to_google"]), out)
        self.assertIn("Google", out["warn_text"][0])
        self.assertIn("Google", out["error"])
        status, out = self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": False})
        self.assertEqual((status, out["code"]), (409, "memory_confirm"))
        self.assertEqual(self.call("/api/memory")[1]["cards"], before["cards"], "a refusal changes nothing")
        status, out = self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": True})
        self.assertEqual((status, out), (200, dict(out, ok=True, profile_id=self.emp, on=True)))
        mine = next(c for c in self.call("/api/memory")[1]["cards"] if c["profile_id"] == self.emp)
        self.assertTrue(mine["on"])

    def test_switching_off_needs_no_yes(self):
        self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": True})
        status, out = self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": False})
        self.assertEqual((status, out["on"]), (200, False))

    def test_a_new_agy_card_does_not_take_memory_to_a_chat(self):
        status, out = self.call("/api/memory", "POST", {"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"})
        self.assertEqual(status, 201, out)
        self.assertEqual(memory.for_card(self.emp, "agy-chat"), memory.ChatMemory(True, False, []))
        self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": True})
        self.assertEqual(memory.for_card(self.emp, "agy-chat"), memory.ChatMemory(True, True, [{"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"}]))


class SharedFolderForAgyTests(ApiCase):
    """ADR 0009, ADR 0012: the shared folder is off for an AGY employee until the person says yes to Google, and the whole AGY part can be lifted
    out by taking ``agy-chat`` out of ``SUPPORTED_ENGINES``."""

    def test_agy_is_supported_and_names_google(self):
        self.assertIn("agy-chat", shared_folder.SUPPORTED_ENGINES)
        self.assertEqual(shared_folder.COMPANY["agy-chat"], "Google")
        status, out = self.call("/api/shared")
        self.assertEqual(status, 200, out)
        mine = next(c for c in out["cards"] if c["profile_id"] == self.emp)
        self.assertEqual((mine["company"], mine["on"], mine["can_chat"]), ("Google", False, True))

    def test_switching_on_takes_the_yes_to_google_and_says_google(self):
        status, out = self.call("/api/shared/cards", "POST", {"profile_id": self.emp, "on": True})
        self.assertEqual((status, out["code"], out["warn"]), (409, "shared_confirm", ["send_to_google"]), out)
        self.assertIn("Google", out["warn_text"][0])
        self.assertNotIn("OpenAI", out["warn_text"][0])
        self.assertFalse(shared_folder.for_card(self.emp, "agy-chat"))
        status, out = self.call("/api/shared/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": True})
        self.assertEqual((status, out["on"]), (200, True), out)
        self.assertTrue(shared_folder.for_card(self.emp, "agy-chat"))

    def test_the_ticks_of_a_group_or_a_dispatch_say_google_too(self):
        cards = [{"id": self.emp, "engine": "agy-chat", "tool": "agy", "can_chat": True}]
        with self.assertRaises(shared_folder.ApiError) as ctx:
            shared_folder.plan_cards([self.emp], cards)
        self.assertEqual((ctx.exception.status, ctx.exception.code, ctx.exception.extra.get("warn")), (409, "shared_confirm", ["send_to_google"]))
        self.assertIn("Google", str(ctx.exception))
        self.assertEqual(shared_folder.plan_cards([self.emp], cards, True), [self.emp])
        with self.assertRaises(shared_folder.ApiError) as ctx:
            shared_folder.plan_cards([], cards, False, new_engines=["agy-chat"])
        self.assertEqual(ctx.exception.code, "shared_confirm")

    def test_taken_out_the_part_for_agy_is_gone_and_nothing_else_changes(self):
        with mock.patch.object(shared_folder, "SUPPORTED_ENGINES", ("claude-chat", "codex-chat")):
            status, out = self.call("/api/shared/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": True})
            self.assertEqual((status, out["code"]), (400, "card_tool_unsupported"), out)
            self.assertFalse(shared_folder.for_card(self.emp, "agy-chat"))
            mine = next(c for c in shared_folder.cards_view([{"id": self.emp, "engine": "agy-chat", "tool": "agy", "can_chat": True}], [self.emp])
                        if c["profile_id"] == self.emp)
            self.assertFalse(mine["on"], "whatever the file says")
            self.assertIsNone(mine["verified"])


if __name__ == "__main__":
    unittest.main()
