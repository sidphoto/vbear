"""P52 / P53 documents: ADR 0017 is final (and says what it corrects), the changelog, the security model, the architecture, the glossary and both READMEs say what v0.25.0
changed and what it did not, the words they quote are the page's, the files of guard rule 19 are there and each carries its number, the version is 0.25.0, and nothing
they added names a person or a machine.

Seams: the text of the documents (whitespace flattened), the page's source for the words it uses, and the files of the guard rule."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_p47_docs import flat, problems, raw, section

ROOT = Path(__file__).resolve().parent.parent


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "adr", "0017-first-run-on-one-page.md")
        cls.adr = flat(cls.raw)

    def test_it_is_final_and_has_the_sections_of_the_others(self):
        self.assertTrue(self.raw.startswith("# 0017 "))
        self.assertIn("狀態：已決定", self.adr)
        for heading in ("## 背景", "## 決定", "## 修正的舊決定", "## 沒有改的", "## 考慮過的其他選項", "## 後果", "## 守門規則 19"):
            self.assertIn(heading, self.raw, heading)
        for left_over in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(left_over, self.raw, left_over)
        self.assertEqual(problems(self.adr, "ADR 0017"), [])

    def test_it_says_what_it_corrects_and_what_stays_the_persons_press(self):
        for part in ("ADR 0013 第 3 點", "ADR 0014 第 1、3、8 點", "只改畫面", "每一步仍然是使用者自己按", "按「確認，開始」才送", "`setup_done`", "不再把人導去開始設定頁",
                     "避免繞圈", "沒有新增", "版本號只在伺服器回的資料裡真的有時才寫", "技術細節", "first-checks", "準備好就能開始"):
            self.assertIn(part, self.adr, part)

    def test_the_rules_19a_to_19c_are_named_with_their_files(self):
        for part in ("19a 首頁第一次使用區塊的安全檢查", "19b 建立 CEO 的請求只在", "19c", "tests/frontend/p52_first_run.cjs", "tests/frontend/p52_words.cjs"):
            self.assertIn(part, self.adr, part)


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.25.0", "## v0.24.0"))
        cls.model = flat(section(raw("docs", "SECURITY-MODEL.md"), "## First run on one page (v0.25)"))
        cls.arch = flat(section(raw("docs", "ARCHITECTURE.md"), "## First run on one page — `web/app.js`, `web/style.css` (v0.25)"))
        cls.glossary = raw("GLOSSARY.md")
        cls.app = raw("web", "app.js")

    def test_the_changelog_starts_with_this_release_and_the_version_is_the_release(self):
        import vbear
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.26.0 — "), self.changelog[:60])      # (v0.25.5 is the second now, v0.25.4 the third, v0.25.3 the fourth)
        self.assertLess(self.changelog.index("## v0.25.4"), self.changelog.index("## v0.25.3"))
        self.assertLess(self.changelog.index("## v0.25.3"), self.changelog.index("## v0.25.2"))
        self.assertLess(self.changelog.index("## v0.25.2"), self.changelog.index("## v0.25.1"))
        self.assertLess(self.changelog.index("## v0.25.1"), self.changelog.index("## v0.25.0"))
        self.assertLess(self.changelog.index("## v0.25.0"), self.changelog.index("## v0.24.0"))
        self.assertEqual(vbear.__version__, "0.26.0")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.25.0"), [])

    def test_the_changelog_says_what_changed_what_did_not_and_what_is_not_tried(self):
        for part in ("One page for the first run", "New people are no longer sent to the start-up page", "in plain words", "Three small fixes", "Rule 19a", "19b", "19c", "15b (no new",
                     "Two things the review of v0.23.0 asked for", "the toast", "Guard rule 17 is stronger", "The main action comes first once a tool can chat", "Money.", "Not tried on a real Mac", "Going back to v0.24.0", "`setup_done`", "「確認，開始」"):
            self.assertIn(part, self.first, part)

    def test_the_security_model_says_it_is_only_the_screen_and_one_press(self):
        for part in ("only what the screen shows", "no route (API path), no kind of request", "rule 19", "Every step is still the person's own press", "only 「確認，開始」 sends",
                     "`setup_done` is written by one press", "guard rule 19b", "never written into the code: guard rule 19c", "Residual risks"):
            self.assertIn(part, self.model, part)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.25"), [])

    def test_the_architecture_names_things_the_page_has(self):
        for name in ("homeFirstRun", "setupKit", "setupDailyBox", "ceoCreate", "versionUnknownWords", "setupMissingLine", "welcomeWanted", "setupPickerNode", "chatPrepState"):
            self.assertIn(name, self.arch, name)
            self.assertRegex(self.app, rf"(function|const) {name}\b", f"web/app.js has {name}")
        self.assertNotIn("homeFirstSteps(", self.app)
        for rule in ("19a", "19b", "19c", "15b"):
            self.assertIn(rule, self.arch, rule)
        self.assertEqual(problems(self.arch, "ARCHITECTURE v0.25"), [])

    def test_the_glossary_has_the_new_words_and_the_page_says_them(self):
        for word in ("**第一次使用（首頁）**：", "**還不認得這一版**：", "**還差一步**：", "不替你選、不自動檢查、不自動建立"):
            self.assertIn(word, self.glossary, word)
        for key in ('firstRun:      { use: "第一次使用"', 'versionUnknown: { use: "還不認得這一版"', 'oneStepLeft:   { use: "還差一步"'):
            self.assertIn(key, self.app, key)
        for word in ("先選一家你有在用的 AI", "選了就能開始聊，之後隨時可以再加。", "建立 CEO，開始聊", "到開始設定看全部 AI 工具", "正在看你的 AI 工具…", "我知道了，開始"):
            self.assertIn(word, self.app, word)

    def test_both_readmes_describe_the_first_run_on_the_home_page(self):
        en, zh = flat(raw("README.md")), flat(raw("README.zh-TW.md"))
        for part in ("Since v0.25", "先選一家你有在用的 AI", "建立 CEO，開始聊", "not sent to the start-up page", "ADR 0017"):
            self.assertIn(part, en, part)
        for part in ("從 v0.25 起", "先選一家你有在用的 AI", "建立 CEO，開始聊", "不再把你帶去開始設定頁", "ADR 0017"):
            self.assertIn(part, zh, part)
        self.assertNotIn("the home page shows three steps", en)
        self.assertNotIn("首頁只有三步", zh)


class GuardFilesTests(unittest.TestCase):
    def test_the_files_of_rule_19_are_there_and_carry_its_number(self):
        for rule, parts in (("19a", ("tests", "frontend", "p52_first_run.cjs")), ("19b", ("tests", "frontend", "p52_first_run.cjs")), ("19c", ("tests", "frontend", "p52_words.cjs"))):
            self.assertIn(rule, raw(*parts), "/".join(parts))
        guard = raw("tests", "test_autonomy_guard.py")
        for part in ("class Guard19FilesAreThere", "     19a  ", "     19b  ", "     19c  "):
            self.assertIn(part, guard, part)
        self.assertTrue((ROOT / "tests" / "frontend" / "p52_small.cjs").is_file())

    def test_rules_15b_to_18_are_still_there(self):
        guard = raw("tests", "test_autonomy_guard.py")
        self.assertIn("class NothingNewIsAsked", guard)
        for part in ("class Guard16FilesAreThere", "class ChatFirstHomeRules", "class Guard17FilesAreThere", "class ChatReadsLikeTextRules", "class Guard18FilesAreThere"):
            self.assertIn(part, guard, part)


if __name__ == "__main__":
    unittest.main()
