"""P34-2/3: the security model and the changelog say what the paste button, the instructions, the launch mode, a full-mode launch and the plan's instructions are."""

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
        for phrase in ("`instructions`", "`launch_mode`", "enforced if launched",
                       "armor_items", "not applicable", "The suggested work folder is advice"):
            self.assertIn(phrase, cards)
        self.assertNotIn("full_mode_not_available", cards)
        self.assertNotIn("cannot be launched yet", cards)

    def test_full_mode_launches_says_vbear_limits_nothing_and_what_it_does_build(self):
        full = self.model.split("## Full-mode launches", 1)[1].split("\n## ", 1)[0]
        for phrase in ("VBear limits nothing", "沒有限制這張卡", "no sandbox", "`--safe-mode`", "never a shell string",
                       "`open_full`", "`--append-system-prompt`", "starts with `-`", "VBear did not verify",
                       "never presses", "`cli_drift`", "狀態未知", "not applied", "A card without `launch_mode` is safe"):
            self.assertIn(phrase, full)

    def test_phase_3_says_the_plan_opens_with_the_executor_cards_instructions(self):
        phase = self.model.split("## Phase 3 automatic mode", 1)[1].split("\n## ", 1)[0]
        approval = phase.split("### The approval", 1)[1].split("\n### ", 1)[0]
        for phrase in ("executor card's instructions open the plan", "職位指示（來自角色卡", "`plan.txt`",
                       "exactly the text it was before", "already approved flow keeps its own"):
            self.assertIn(phrase, approval)

    def test_the_changelog_names_the_new_things(self):
        entry = self.changelog.split("## v0.9.0", 1)[1].split("\n## ", 1)[0]
        for phrase in ("貼上職位指示", "完整模式", "安全模式", "法規與合規", "財務與帳務", "skill index version is now 3",
                       "--append-system-prompt", "VBear 沒有限制這張卡", "加上職位指示"):
            self.assertIn(phrase, entry)
        self.assertNotIn("完整模式的出發還沒開放", entry)


if __name__ == "__main__":
    unittest.main()
