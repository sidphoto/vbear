"""v0.13 P38-8: the first CEO. GET /api/first-ceo tells the page whether the person still has no card to chat with, which
ready AI tool the CEO card would use, and the words to fill in (name, instructions, the opening sentence); the card itself
is made with the ordinary POST /api/agent-profiles. Over HTTP with the runtime daemon in a thread
(tests/test_t16_setup.SetupCase); every AI tool is a stand-in file, no AI tool is started and nothing leaves this computer.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.test_t16_setup import CANARY, SetupCase
from vbear import agent_profiles, first_ceo


class FirstCeoCase(SetupCase):
    def plan(self):
        st, r = self.req("GET", "/api/first-ceo")
        self.assertEqual(st, 200, r)
        return r

    def make_card(self, tool="claude", **over):
        body = {"name": "虛構員工", "model": {"tool": tool, "model_id": ""}, **over}
        st, r = self.req("POST", "/api/agent-profiles", body)
        self.assertEqual(st, 200, r)
        return r["profile"]

    def ready(self, *names):
        for name in names:
            self.install(name)
            self.set_exit(name, 0)


class WhichToolTests(FirstCeoCase):
    def test_no_ready_tool_sends_the_person_back_to_the_start_up(self):
        r = self.plan()
        self.assertIs(r["needed"], True)
        self.assertIs(r["can_create"], False)
        self.assertEqual(r["go"], "setup")
        self.assertIsNone(r["tool"])
        self.assertTrue(r["reason"])

    def test_a_tool_that_is_installed_but_not_logged_in_is_not_ready(self):
        self.install("claude")
        self.set_exit("claude", 1)
        r = self.plan()
        self.assertEqual((r["can_create"], r["go"], r["tool"]), (False, "setup", None))

    def test_a_ready_claude_code_is_the_tool(self):
        self.ready("claude")
        r = self.plan()
        self.assertEqual((r["needed"], r["can_create"], r["tool"], r["go"]), (True, True, "claude", None))
        self.assertEqual(r["tool_name"], "Claude Code")
        self.assertEqual(r["launch_mode"], "safe")

    def test_claude_code_wins_when_both_are_ready(self):
        self.ready("claude", "codex")
        self.assertEqual(self.plan()["tool"], "claude")

    def test_codex_is_the_tool_when_claude_code_is_not_ready(self):
        self.install("claude")
        self.set_exit("claude", 1)
        self.ready("codex")
        r = self.plan()
        self.assertEqual((r["can_create"], r["tool"], r["tool_name"]), (True, "codex", "Codex"))
        self.assertEqual(r["launch_mode"], "safe")
        # the chat of Codex logs in on its own: the page is told before the card is made, not after
        self.assertIs(r["chat_ready"], False)
        self.assertIn("聊天用的 Codex", r["chat_note"])

    def test_a_tool_that_only_has_a_mark_is_never_the_ceo(self):
        # AGY, Grok and MCODE cannot chat yet: ready for them is not a reason to make a CEO card on them
        self.install("agy")
        self.assertEqual(self.req("POST", "/api/setup/tools/agy/marker", {"done": True})[0], 200)
        r = self.plan()
        self.assertEqual((r["can_create"], r["go"], r["tool"]), (False, "setup", None))


class WhenIsItNeededTests(FirstCeoCase):
    def test_no_card_at_all_needs_one(self):
        self.ready("claude")
        self.assertIs(self.plan()["needed"], True)

    def test_a_card_that_can_chat_means_no_step(self):
        self.ready("claude")
        self.make_card("claude")
        r = self.plan()
        self.assertIs(r["needed"], False)
        self.assertIs(r["can_create"], False)
        self.assertIsNone(r["go"])

    def test_a_codex_card_that_can_chat_means_no_step(self):
        self.ready("claude")
        self.make_card("codex")
        self.assertIs(self.plan()["needed"], False)

    def test_cards_that_cannot_chat_still_need_the_step(self):
        self.ready("claude")
        self.make_card("grok")
        self.make_card("claude", enabled=False)
        self.assertIs(self.plan()["needed"], True)

    def test_a_person_with_a_card_costs_the_lobby_no_tool_run(self):
        # the lobby asks on every visit: when the step is not needed, no AI tool is asked about its version or login
        self.ready("claude", "codex")
        self.make_card("claude")
        self.assertIs(self.plan()["needed"], False)
        self.assertEqual(self.calls(), [])

    def test_a_card_that_can_chat_means_no_step_even_with_no_tool_ready(self):
        self.make_card("claude")
        r = self.plan()
        self.assertEqual((r["needed"], r["go"]), (False, None))


class TheCardTests(FirstCeoCase):
    def test_the_plan_makes_a_safe_mode_card_on_the_ready_tool(self):
        self.ready("claude")
        r = self.plan()
        body = {"name": r["name"], "position": r["position"], "instructions": r["instructions"], "launch_mode": r["launch_mode"],
                "model": {"tool": r["tool"], "model_id": ""}}
        saved = self.make_card(r["tool"], **{k: v for k, v in body.items() if k != "model"})
        self.assertEqual(saved["model"]["tool"], "claude")
        self.assertEqual(saved["launch_mode"], "safe")
        self.assertEqual(agent_profiles.effective_launch_mode(saved), "safe")
        self.assertEqual(saved["name"], "CEO")
        self.assertEqual(saved["position"], "planner")
        self.assertTrue(saved["enabled"])
        # and now the step is over
        self.assertIs(self.plan()["needed"], False)
        # the chat list calls the card one it can chat with
        st, listing = self.req("GET", "/api/chats")
        self.assertEqual(st, 200, listing)
        self.assertTrue([c for c in listing["cards"] if c["id"] == saved["id"] and c["can_chat"] is True])

    def test_the_words_the_page_fills_in_are_plain_and_fit_the_card(self):
        self.ready("claude")
        r = self.plan()
        self.assertEqual(r["name"], "CEO")
        self.assertLessEqual(len(r["instructions"]), agent_profiles.MAX_INSTRUCTIONS)
        self.assertEqual(agent_profiles.clean_instructions(r["instructions"]), r["instructions"])
        self.assertLessEqual(len(r["opening"]), 200)
        self.assertIn("三個問題", r["opening"])
        self.assertIn(r["position"], agent_profiles.POSITIONS)
        # nothing that sounds like a terminal, and nothing that promises what does not exist yet
        words = r["instructions"] + r["opening"] + r["reason"]
        for bad in ("CLI", "終端機", "sandbox", "token", "派工給"):
            self.assertNotIn(bad, words)

    def test_the_answer_carries_no_command_path_or_login_code(self):
        self.ready("claude", "codex")
        raw = json.dumps(self.plan(), ensure_ascii=False)
        self.assertNotIn(CANARY, raw)
        self.assertNotIn(str(self.tmp), raw)
        self.assertNotIn(str(self.bindir), raw)
        self.assertIsNone(re.search(r"/Users/|/home/|/tmp/", raw))

    def test_asking_changes_nothing(self):
        self.ready("claude")
        self.plan()
        self.plan()
        st, r = self.req("GET", "/api/agent-profiles")
        self.assertEqual((st, r["profiles"]), (200, []))

    def test_the_module_picks_the_same_without_a_server(self):
        rows = [{"id": "claude", "ready": False}, {"id": "codex", "ready": True, "chat_login": {"state": "logged_in"}}]
        plan = first_ceo.plan([], rows)
        self.assertEqual((plan["tool"], plan["chat_ready"]), ("codex", True))
        self.assertEqual(first_ceo.plan([], [])["go"], "setup")


class TheHomeNoteTests(FirstCeoCase):
    """first_ceo_id: the card the home page offers a first chat with, put away once the person has used or dismissed it."""

    def test_the_id_is_written_through_the_config_and_cleared(self):
        self.ready("claude")
        card = self.make_card("claude", name="CEO")
        st, r = self.req("POST", "/api/config", {"first_ceo_id": card["id"]})
        self.assertEqual(st, 200, r)
        st, got = self.req("GET", "/api/config")
        self.assertEqual(got["config"]["first_ceo_id"], card["id"])
        st, r = self.req("POST", "/api/config", {"first_ceo_id": ""})
        self.assertEqual(st, 200, r)
        self.assertEqual(self.req("GET", "/api/config")[1]["config"]["first_ceo_id"], "")

    def test_only_a_card_id_or_nothing_is_accepted(self):
        for bad in (5, None, ["x"], {"a": 1}, "../etc", "x" * 65, "a b"):
            st, r = self.req("POST", "/api/config", {"first_ceo_id": bad})
            self.assertEqual(st, 400, (bad, r))

    def test_the_default_is_nothing(self):
        self.assertEqual(self.req("GET", "/api/config")[1]["config"]["first_ceo_id"], "")


class DocsTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_the_changelog_the_glossary_and_the_architecture_say_what_the_step_is(self):
        log = (self.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        log = log[log.index("## v0.13.0"):log.index("## v0.12.0")]
        for phrase in ("(P38-8)", "`GET /api/first-ceo`", "`first_ceo_id`", "`#/ceo`", "safe mode", "only put in the box", "「輪到 p」"):
            self.assertIn(phrase, log, phrase)
        glossary = (self.ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
        self.assertIn("**CEO**：", glossary)
        self.assertIn("它是一張普通的角色卡，只會聊天；建員工和派工是幕僚長的事", glossary)     # v0.15: the chief of staff exists now
        arch = (self.ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("/api/first-ceo", arch)
        self.assertIn("first_ceo_id", arch)


if __name__ == "__main__":
    unittest.main()
