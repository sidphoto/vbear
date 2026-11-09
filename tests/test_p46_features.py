"""v0.20 P46-5 (ADR 0012): the other features take an AGY employee in, the way they took a Codex one (ADR 0006-0011). Memory and the shared
folder are off for AGY and switch on only with the person's yes to Google; the groups, the chief of staff, the dispatches, the routines,
the two suggestions, the team templates and the first CEO name Google where they name a company. Everything here is made up: a synthetic
HOME and VBEAR_HOME under /tmp, an AGY that is a stand-in answer of the chat service, no real AI tool is run and nothing reaches a network."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import sys

from tests.group_fixtures import GroupBase
from tests.test_chief_runner import Base as ChiefBase, card as chief_card, plan as chief_plan
from tests.test_p46_agy_chat_api import ApiCase, READY
from vbear.runtime import chat_store as cs
from vbear import agent_profiles as ap, ai_tool_status, chat_service, chief, chief_runner, dispatch, groups, memory, shared_folder
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


class GroupsWithAgyTests(GroupBase):
    """ADR 0007: an AGY card is a member like any other (two or three, mixed); the notes name the companies the words go to."""

    def setUp(self):
        super().setUp()
        self.service.agy = lambda: dict(READY)
        self.service.agy_binary = lambda: (sys.executable, "1.5.3")
        self.agy_hand = ap.save_profile(None, {"name": "虛構AGY員工", "position": "social", "model": {"tool": "agy"}})["id"]
        self.agy_two = ap.save_profile(None, {"name": "虛構AGY員工二", "position": "accountant", "model": {"tool": "agy"}})["id"]

    def test_an_agy_card_joins_and_gets_an_agy_chat(self):
        got = self.make_group(self.writer, self.agy_hand)
        self.assertEqual([m["name"] for m in got["group"]["members"]], ["文案小編", "虛構AGY員工"])
        self.assertEqual(groups.TOOL_NAME["agy"], "AGY")
        mine = next(m for m in got["group"]["members"] if m["name"] == "虛構AGY員工")
        self.assertEqual(mine["tool"], "agy")
        self.assertEqual(cs.load(self.service.base, self.chat_ids(got["group"]["id"])[self.agy_hand])["engine"], "agy-chat")

    def test_claude_and_agy_name_anthropic_and_google(self):
        notes = self.make_group(self.writer, self.agy_hand)["notes"]
        self.assertEqual(len(notes), 1)
        self.assertIn("Claude Code 和 AGY", notes[0])
        self.assertIn("Anthropic 和 Google", notes[0])
        self.assertNotIn("OpenAI", notes[0])

    def test_all_three_companies_are_named(self):
        notes = self.make_group(self.writer, self.codex_hand, self.agy_hand)["notes"]
        self.assertEqual(len(notes), 1)
        for word in ("Claude Code", "Codex", "AGY", "Anthropic", "OpenAI", "Google"):
            self.assertIn(word, notes[0])

    def test_codex_and_agy_name_openai_and_google(self):
        notes = self.make_group(self.codex_hand, self.agy_hand)["notes"]
        self.assertIn("OpenAI 和 Google", notes[0])
        self.assertNotIn("Anthropic", notes[0])

    def test_one_company_says_nothing(self):
        self.assertEqual(self.make_group(self.agy_hand, self.agy_two)["notes"], [])
        self.assertEqual(self.make_group(self.writer, self.accountant)["notes"], [])

    def test_claude_and_codex_keep_the_old_sentence_to_the_letter(self):
        self.assertEqual(self.make_group(self.writer, self.codex_hand)["notes"],
                         ["群組裡有 Claude Code 和 Codex 的員工，群組裡的對話會同時送給 Anthropic 和 OpenAI。"])

    def test_an_agy_member_joining_says_where_the_words_go(self):
        gid = self.make_group(self.writer, self.accountant)["group"]["id"]
        got = self.groups.members(gid, {"add": [self.agy_hand]})
        self.assertEqual(len(got["notes"]), 1)
        self.assertIn("Google", got["notes"][0])

    def test_the_codes_that_are_about_one_agy_employee_skip_her_and_the_rest_go_on(self):
        from vbear import group_runner
        for code in ("agy_version", "agy_home", "agy_hooks", "agy_workdir"):
            self.assertIn(code, group_runner.SKIP_CODES)
            self.assertIn(code, chat_service.CODE_TEXT)

    def test_a_skipped_agy_employee_is_named_by_her_tool(self):
        text = groups.skip_text("agy_hooks", "虛構AGY員工", groups.TOOL_NAME["agy"])
        self.assertIn("虛構AGY員工這次沒有回答", text)
        self.assertIn("hooks", text)


class ChiefAndDispatchWithAgyTests(ChiefBase):
    """ADR 0006: the chief of staff and the dispatches take an AGY employee in; the chief of staff itself still needs Claude Code."""

    def setUp(self):
        super().setUp()
        self.profiles["ceo3"] = chief_card("ceo3", "planner", tool="agy", name="第三個CEO")
        self.profiles["worker"] = chief_card("worker", "social", tool="agy", name="AGY小編")
        self.tools = ("claude", "codex", "agy")

    def test_an_agy_chat_that_is_ready_counts_as_a_tool_that_can_chat(self):
        self.assertEqual(chief_runner.usable_tools({"state": "verified", "agy": {"state": "ready"}}), ("claude", "agy"))
        self.assertEqual(chief_runner.usable_tools({"state": "unknown", "agy": {"state": "ready"}}), ("agy",))
        self.assertEqual(chief_runner.usable_tools({"state": "verified", "agy": {"state": "unverified"}}), ("claude",))
        self.assertEqual(chief_runner.usable_tools({"state": "verified", "codex": {"state": "ready"}, "agy": {"state": "ready"}}),
                         ("claude", "codex", "agy"))

    def test_the_words_for_no_tool_name_all_three(self):
        text = str(chief.ChiefError("no_chat_tool"))
        for word in ("Claude Code", "Codex", "AGY"):
            self.assertIn(word, text)

    def test_an_agy_ceo_is_told_the_chat_goes_to_claude_code(self):
        chat_id = self.chat("ceo3", [("user", "你好")], engine="agy-chat")
        preview = self.board().preview(chat_id, self.sources())
        self.assertEqual(preview["ceo_tool"], "agy")
        self.assertEqual(preview["notice"], "這張 CEO 是 AGY 的角色卡：你和它的對話會送給 Claude Code（Anthropic）整理成提議。")
        self.assertEqual(preview["sends_to"], "Claude Code")
        self.assertIn("agy", preview["tools"])

    def test_a_claude_ceo_has_no_notice_and_the_codex_one_is_as_it_was(self):
        self.assertIsNone(self.board().preview(self.chat_id, self.sources())["notice"])
        chat_id = self.chat("ceo2", [("user", "你好")], engine="codex-chat")
        self.assertEqual(self.board().preview(chat_id, self.sources())["notice"],
                         "這張 CEO 是 Codex 的角色卡：你和它的對話會送給 Claude Code（Anthropic）整理成提議。")

    def test_the_chief_may_name_an_agy_employee_to_take_and_a_new_one_to_make(self):
        shown, _ = chief.candidates(list(self.profiles.values()), self.tools)
        self.assertIn("agy", [c["tool"] for c in shown])
        out = chief.validate_plan(chief_plan(
            team=[{"who": "C1", "why": "會寫文案"}, {"who": "N1", "why": "排時間表"}],
            new_cards=[{"ref": "N1", "name": "新來的AGY", "position": "pm", "tool": "agy", "model_alias": "opus", "why": "沒有合適的人"}],
            steps=[{"who": "N1", "text": "請排時間表。"}]), shown, self.tools)
        self.assertEqual([c["tool"] for c in out["kept"]["new_cards"]], ["agy"])
        self.assertEqual(out["kept"]["new_cards"][0]["model_alias"], "", "only a Claude Code employee takes a model alias")
        self.assertIn("model_alias_cleared", [n["code"] for n in out["notes"]])
        self.assertIn("agy", chief.plan_schema(self.tools)["properties"]["new_cards"]["items"]["properties"]["tool"]["enum"])

    def test_a_new_agy_employee_is_made_in_safe_mode_with_no_model_and_nothing_switched_on(self):
        body = dispatch.card_body({"ref": "N1", "name": "新來的AGY", "position": "pm", "tool": "agy", "model_alias": ""})
        self.assertEqual((body["launch_mode"], body["model"], body["equipped_skill_ids"], body["enabled"]),
                         ("safe", {"tool": "agy", "model_id": ""}, [], True))
        self.assertEqual(set(body) & {"memory", "shared", "shared_folder", "confirm_company"}, set(), "memory and the shared folder stay off")


if __name__ == "__main__":
    unittest.main()
