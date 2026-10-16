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
