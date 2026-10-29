"""P34-2: the security model and the changelog say what the paste button, the instructions and the launch mode are."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class DocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = (ROOT / "docs" / "SECURITY-MODEL.md").read_text(encoding="utf-8")
        cls.changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_terminals_says_the_paste_button_never_presses_enter(self):
        terminals = self.model.split("## Terminals", 1)[1].split("\n## ", 1)[0]
        self.assertIn("貼上職位指示", terminals)
        self.assertIn("VBear never sends Enter", terminals)
        self.assertIn("bracketed paste", terminals)
        self.assertIn("/api/agent-profiles/<id>/instructions", terminals)

    def test_starter_cards_says_what_the_instructions_and_the_mode_are(self):
        cards = self.model.split("### Starter cards and the wizard's launch check", 1)[1].split("\n### ", 1)[0]
        for phrase in ("`instructions`", "`launch_mode`", "full_mode_not_available", "enforced if launched",
                       "armor_items", "not applicable", "The suggested work folder is advice"):
            self.assertIn(phrase, cards)

    def test_the_changelog_names_the_new_things(self):
        entry = self.changelog.split("## v0.9.0", 1)[1].split("\n## ", 1)[0]
        for phrase in ("貼上職位指示", "完整模式", "安全模式", "法規與合規", "財務與帳務", "skill index version is now 3"):
            self.assertIn(phrase, entry)


if __name__ == "__main__":
    unittest.main()
