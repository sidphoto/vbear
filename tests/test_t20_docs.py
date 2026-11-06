"""v0.12 task 8: the READMEs, the changelog and the security documents say what the start-up page, the new AI tools, the
daily limit, the tick on 我了解 and the try button are; the first-time page is said to be an illustration; and no screen says
that VBear cannot start AGY."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat((ROOT.joinpath(*parts)).read_text(encoding="utf-8"))


class ReadmeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")

    def test_the_english_readme(self):
        for phrase in ("The start-up page (開始設定)", "Grok", "xAI", "full mode only", "MCODE", "hidden", "顯示 MCODE",
                       "US$1, US$3 or US$10", "US$3", "每天上限", "我了解", "New role cards start in safe mode",
                       "試一下", "under US$0.01", "第一次打開 VBear", "illustration", "not a screenshot", "強制打開",
                       "就緒", "我登入好了", "`grok [-m X]`", "`mcode [-m X]`"):
            self.assertIn(phrase, self.en, phrase)
        self.assertNotIn("but it does not install it", self.en)
        self.assertNotIn("VBear 還不會啟動", self.en)

    def test_the_chinese_readme(self):
        for phrase in ("開始設定", "Grok", "xAI", "只能用完整模式", "MCODE", "隱藏", "顯示 MCODE", "US$1、US$3 或 US$10", "預設 US$3",
                       "每天上限", "我了解", "新的角色卡預設是安全模式", "試一下", "不到 US$0.01", "第一次打開 VBear", "示意圖",
                       "不是你電腦的真實畫面", "強制打開", "就緒", "我登入好了", "`grok [-m X]`", "`mcode [-m X]`",
                       "方案用量上限"):
            self.assertIn(phrase, self.zh, phrase)
        self.assertNotIn("VBear 還不會啟動", self.zh)
        self.assertNotIn("但不會替你安裝", self.zh)

    def test_codex_is_full_mode_only_in_both(self):
        self.assertRegex(self.en, r"Codex CLI \| yes \| yes: `codex \[-m X\]`[^|]*\| no[^|]*full mode only")
        self.assertRegex(self.zh, r"Codex CLI \| 可以 \| 可以：`codex \[-m X\]`[^|]*\| 不行[^|]*只能用完整模式")


class ChangelogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.head = text[text.index("## v0.12.0"):text.index("## v0.11.0")]
        cls.changelog_start = text
        cls.unreleased = flat(text[text.index("## v0.12.0"):text.index("## v0.11.0")])

    def test_the_release_comes_first(self):
        self.assertTrue(self.head.startswith("## v0.12.0 — the start-up page"), self.head[:60])
        self.assertTrue(self.changelog_start.startswith("# Changelog\n\n## v0.13.0 — Codex chat"), self.changelog_start[:60])
        self.assertNotIn("not released", self.unreleased)

    def test_it_covers_the_eight_tasks(self):
        for phrase in ("`#/setup`", "`#/welcome`", "`welcome_seen`", "Open Anyway", "illustration", "Grok", "MCODE", "`show_mcode`",
                       "`~/.grok/bin`", "`~/.minimax-code/bin`", "我了解", "`full_mode_not_acknowledged`", "safe mode",
                       "試一下", "`setup-try.json`", "US$0.01", "每天上限", "US$1", "US$3", "US$10", "`setup_done`",
                       "`setup_notice`", "`setup_marks.json`", "exit code", "這個功能目前需要 Claude Code", "--ask-for-approval",
                       "The tool list is in one place", "`open_setup`"):
            self.assertIn(phrase, self.unreleased, phrase)

    def test_it_says_what_going_back_to_v0_11_0_does(self):
        self.assertIn("Going back to v0.11.0", self.unreleased)
        for phrase in ("`setup_marks.json`", "`setup-try.json`", "`welcome_seen`", "`show_mcode`", "does not count",
                       "agent_profiles.json", "damaged", "Grok or MCODE"):
            self.assertIn(phrase, self.unreleased, phrase)


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.model_section = cls.model[cls.model.index("## The start-up page (v0.12)"):]
        cls.security = read("SECURITY.md")

    def test_the_model_has_one_section_for_the_start_up_page(self):
        s = self.model_section
        for phrase in ("only from the list in `vbear/ai_tools.py`", "never from the request", "`open_setup`",
                       "only the exit code", "not captured", "scratch folder", "process group", "`setup-try.json`",
                       "daily limit", "US$0.01", "`welcome_seen`", "illustration", "`--ask-for-approval`", "before `exec`",
                       "Grok", "MCODE", "`show_mcode`"):
            self.assertIn(phrase, s, phrase)

    def test_security_md_lists_the_start_up_page_in_scope(self):
        for phrase in ("start-up page", "only from the server's list", "a try", "exit code"):
            self.assertIn(phrase, self.security, phrase)


class NoStaleAgySentenceTests(unittest.TestCase):
    def test_no_screen_or_doc_says_vbear_cannot_start_agy(self):
        for part in ("vbear", "web"):
            for path in (ROOT / part).rglob("*"):
                if path.suffix in (".py", ".js", ".html", ".css") and "vendor" not in path.parts:
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("還不會啟動 AGY", text, str(path))
                    self.assertNotIn("VBear 不啟動 AGY", text, str(path))
        for name in ("README.md", "README.zh-TW.md"):
            self.assertNotIn("還不會啟動 AGY", (ROOT / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
