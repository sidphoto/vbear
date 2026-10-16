"""The card front end keeps a few words that the server also sends (the armor levels behind a shield, the safe-mode
slot rule). They are copied into web/app.js; this test makes a change on either side fail here instead of drawing a
shield that says more than the level does (design card-play 6.3, R1)."""

from __future__ import annotations

import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vbear import agent_launch, loadout  # noqa: E402

APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _shield_table() -> dict:
    block = re.search(r"const ARMOR_LEVEL_SHIELD = \{(.*?)\n\};", APP, re.S)
    assert block, "ARMOR_LEVEL_SHIELD is not in web/app.js"
    return dict(re.findall(r'"([^"]+)":\s*"([a-z]+)"', block.group(1)))


class ShieldTableTests(unittest.TestCase):
    def test_only_enforced_intent_and_unrestricted_have_a_shield_and_the_words_are_the_servers(self):
        self.assertEqual(_shield_table(), {
            agent_launch.ENFORCED: "enforced",
            agent_launch.INTENT: "recorded",
            agent_launch.UNRESTRICTED: "none",
        })

    def test_no_other_level_word_has_a_shield(self):
        others = {agent_launch.PARTIAL, agent_launch.UNVERIFIED, agent_launch.UNKNOWN, agent_launch.NOT_GRANTED}
        self.assertFalse(others & set(_shield_table()))

    def test_every_level_the_armor_can_hold_is_a_known_constant(self):
        levels = {lv for g in agent_launch.armor_groups("claude") for lv in g["levels"]}
        self.assertEqual(levels, {agent_launch.ENFORCED, agent_launch.PARTIAL, agent_launch.NOT_GRANTED,
                                  agent_launch.INTENT, agent_launch.UNRESTRICTED, agent_launch.UNVERIFIED,
                                  agent_launch.UNKNOWN})


class StarterIntentsAndCodexLightTests(unittest.TestCase):
    """v1.2 R10 and R11: the page holds no copy of the launch rules; it reads them from the server."""

    CLOSED = {"enabled": False, "approved_domains": []}

    def test_the_page_has_no_copy_of_the_verified_combination(self):
        compact = re.sub(r"\s+", "", APP)
        for literal in ('read:"allow",write:"allow",test:"allow",deploy:"deny"',
                        'read:"allow",write:"deny"', "VERIFIED_INTENTS"):
            self.assertNotIn(literal, compact, literal)
        body = re.search(r"function permissionSuggestion\(catalog, position\) \{(.*?)\n\}", APP, re.S).group(1)
        self.assertIn("starter_deck", body)
        self.assertIn("verifiedIntents(catalog)", body)
        self.assertIn("catalog.verified_intents", re.search(r"function verifiedIntents\(catalog\) \{(.*?)\}", APP, re.S).group(1))

    def test_the_page_asks_the_server_why_a_combination_cannot_go(self):
        self.assertIn("/api/agent-builder/intent-check?", APP)
        # and no launch_blockers code is spelled out for that purpose in the wizard
        wizard = APP[APP.index("function openCardWizard"):APP.index("// ---- the starter deck")]
        for code in ("readonly_unverified", "read_deny_unenforceable", "test_deny_unenforceable", "intents_not_supported"):
            self.assertNotIn(code, wizard, code)

    def test_a_card_with_the_verified_intents_is_blocked_only_by_codex_reasons_and_only_for_codex(self):
        codex = {"model": {"tool": "codex"}, "enabled": True, "permission_intents": dict(agent_launch.VERIFIED_INTENTS)}
        claude = {"model": {"tool": "claude"}, "enabled": True, "permission_intents": dict(agent_launch.VERIFIED_INTENTS)}
        codes = [b["code"] for b in agent_launch.launch_blockers(codex, True, self.CLOSED)]
        self.assertTrue(codes and all(c.startswith("codex_") for c in codes), codes)
        self.assertEqual(agent_launch.launch_blockers(claude, True, self.CLOSED), [])
        # a reason about anything else keeps the plain prefix-free code the page tells apart by
        other = agent_launch.launch_blockers({**codex, "permission_intents": {**agent_launch.VERIFIED_INTENTS, "write": "deny"}},
                                             True, self.CLOSED)
        self.assertTrue(any(not b["code"].startswith("codex_") for b in other))

    def test_the_light_tells_codex_reasons_apart_by_their_prefix_and_by_nothing_else(self):
        body = re.search(r"function cardDeparture\(p, loadoutState\) \{(.*?)\n\}\n", APP, re.S).group(1)
        self.assertIn('startsWith("codex_")', body)
        self.assertIn("blockers.every(", body)


class WillLoadTests(unittest.TestCase):
    def test_no_tool_loads_a_chosen_skill_today(self):
        for tool in ("claude", "codex", "shared", None, "agy"):
            self.assertIs(loadout._will_load(tool, "any"), False, tool)

    def test_the_front_end_reads_the_field_and_not_a_word(self):
        # the slot state is decided by one function that looks at will_load === true and at nothing else
        body = re.search(r"function cardSlotState\(item\) \{(.*?)\}", APP, re.S).group(1)
        self.assertIn("will_load === true", body)
        self.assertNotIn("title", body)
        self.assertNotIn("note", body)


if __name__ == "__main__":
    unittest.main()
