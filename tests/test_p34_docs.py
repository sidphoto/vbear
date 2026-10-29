"""P34-2/3: the security model and the changelog say what the paste button, the instructions, the launch mode, a full-mode launch and the plan's instructions are.
P34-6: the READMEs and REFERENCE.zh-TW say what v0.9.0 is."""

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

    def test_meetings_says_what_is_sent_what_is_checked_and_what_is_not_proven(self):
        meetings = self.model.split("## Meetings (tool-less headless speech)", 1)[1].split("\n## ", 1)[0]
        for phrase in ("new outbound data path", "never its folder", "`proxy`", "used once", "five minutes", "`translations.translation_argv`",
                       "checks its own init event as the line arrives", "revoked", "`meeting_limits`", "`cost_source`",
                       "`decimal.Decimal`", "twice at most", "`interrupted`", "`meeting-worker.blocked`", "R1–R8",
                       "only to raise the verdict", "wire transfer", "未驗證身分", "writes no task card, no flow",
                       "not read isolation", "查無出處，需人工複核"):
            self.assertIn(phrase, meetings)
        self.assertNotIn("which do not exist yet", self.model)

    def test_the_changelog_names_the_new_things(self):
        entry = self.changelog.split("## v0.9.0", 1)[1].split("\n## ", 1)[0]
        for phrase in ("貼上職位指示", "完整模式", "安全模式", "法規與合規", "財務與帳務", "skill index version is now 3",
                       "--append-system-prompt", "VBear 沒有限制這張卡", "加上職位指示"):
            self.assertIn(phrase, entry)
        self.assertNotIn("完整模式的出發還沒開放", entry)


def _flat(text: str) -> str:
    """The text with each run of white space made one space, so a sentence is found across a line break."""
    return " ".join(text.split())


class ReadmeTests(unittest.TestCase):
    """P34-6: the two READMEs and REFERENCE.zh-TW say what v0.9.0 is (the full and the safe launch, the instructions, the
    meetings) and no longer say what stopped being true."""

    @classmethod
    def setUpClass(cls):
        cls.en = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.zh = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
        cls.ref = (ROOT / "docs" / "REFERENCE.zh-TW.md").read_text(encoding="utf-8")

    def test_what_stopped_being_true_is_gone(self):
        en, zh = _flat(self.en), _flat(self.zh)
        for stale in ("Launching from a role card works with Claude Code only for now",
                      "Read-only, network-enabled and Codex launches are planned, not built",
                      "VBear starts Claude Code in its safe mode. By Claude Code's own help",
                      "Real translation execution is currently blocked",
                      "three ready cards (a planner, an executor and a reviewer)"):
            self.assertNotIn(stale, en, stale)
        for stale in ("目前用角色卡啟動的只有 Claude Code", "唯讀、可連網與 Codex 的啟動還在規劃，尚未提供",
                      "VBear 啟動 Claude Code 時用的是它的安全模式。依 Claude Code 自己的說明", "本版尚未啟用真實翻譯",
                      "一次拿三張現成的卡（規劃、執行、審查各一張"):
            self.assertNotIn(stale, zh, stale)

    def test_the_promises_are_said_of_the_safe_launch_and_full_mode_limits_nothing(self):
        en, zh = _flat(self.en), _flat(self.zh)
        promises_en = _flat(self.en.split("## What VBear promises, in short", 1)[1].split("\n## ", 1)[0])
        promises_zh = _flat(self.zh.split("## VBear 的承諾（簡短版）", 1)[1].split("\n## ", 1)[0])
        self.assertIn("in safe mode", promises_en.split("**It does not hold:**")[0])
        self.assertIn("full mode", promises_en)
        self.assertIn("VBear limits nothing", promises_en)
        self.assertIn("安全模式", promises_zh.split("**守不住的：**")[0])
        self.assertIn("完整模式", promises_zh)
        self.assertIn("VBear 不加任何限制", promises_zh)
        for text in (en, zh):
            for phrase in ("`launch_mode`", "--append-system-prompt", "VBear 沒有限制這張卡", "貼上職位指示", "--safe-mode"):
                self.assertIn(phrase, text, phrase)
        self.assertIn("A card saved before v0.9.0", en)
        self.assertIn("v0.9.0 以前存的卡", zh)

    def test_the_supported_agents_table_has_both_ways_of_starting(self):
        for text, head, rows in (
                (self.en, "## Supported agents", ("| Claude Code |", "| Codex CLI |", "| Antigravity (AGY) |")),
                (self.zh, "## 支援的 Agent", ("| Claude Code |", "| Codex CLI |", "| Antigravity（AGY） |"))):
            table = text.split(head, 1)[1].split("\n\n", 1)[1].split("\n\n", 1)[0]
            header = table.splitlines()[0]
            self.assertTrue("Full mode" in header or "完整模式" in header, header)
            self.assertTrue("Safe mode" in header or "安全模式" in header, header)
            for row in rows:
                self.assertIn(row, table)
        self.assertNotIn("**not yet.** The preview explains why", self.en)
        self.assertNotIn("**還不行。** 預覽會說明原因", self.zh)

    def test_the_readmes_describe_the_meetings(self):
        for text, row, menu in ((self.en, "| **Meeting** |", "辦公室, 會議, 終端機"),
                                (self.zh, "| **會議** |", "「辦公室」「會議」「終端機」")):
            flat = _flat(text)
            self.assertIn(row, text)
            self.assertIn(menu, flat)
            for phrase in ("`#/meetings`", "StructuredOutput", "R1–R8", "`meeting_limits`", "Anthropic", "未驗證身分"):
                self.assertIn(phrase, flat, phrase)
        self.assertIn("no tools at all", _flat(self.en))
        self.assertIn("never carries out a decision", _flat(self.en))
        self.assertIn("完全沒有工具", _flat(self.zh))
        self.assertIn("VBear 不會去執行決定", _flat(self.zh))

    def test_the_reference_lists_the_meetings_page_its_files_and_its_modules(self):
        pages = self.ref.split("## 畫面", 1)[1].split("\n## ", 1)[0]
        self.assertIn("| 會議 |", pages)
        self.assertIn("會議室", pages)
        self.assertIn("董事長桌", pages)
        self.assertIn("| 角色卡池 |", pages)
        state = self.ref.split("## 狀態目錄", 1)[1].split("\n## ", 1)[0]
        for name in ("`meetings/`", "`meeting-worker.lock`", "`translation-boundaries.json`"):
            self.assertIn(name, state, name)
        layout = self.ref.split("## 結構", 1)[1]
        for module in ("meetings.py", "meeting_rules.py", "meeting_runner.py", "headless_cli.py", "position_guide.py",
                       "agent_profiles.py"):
            self.assertIn(module, layout, module)
        security = self.ref.split("## 安全", 1)[1].split("\n## ", 1)[0]
        self.assertIn("完整模式", security)
        self.assertIn("會議", security)
        self.assertNotIn("內容逐字搬移", self.ref)


if __name__ == "__main__":
    unittest.main()
