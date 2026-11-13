"""P50-4 documents: ADR 0015 is final (and ADR 0013 points to it), the changelog, both READMEs, the security model, the architecture, the reference and the
glossary say what v0.23.0 changed and what it did not, the words they quote are the page's, the files of guard rule 17 are there and each carries its number, the
version is the release's (0.25.0 since P52), and nothing P50-4 added names a person or a machine.

Seams: the text of the documents (whitespace flattened), the page's source for the words it uses, and the files of the guard rule."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_p47_docs import flat, problems, raw, section

ROOT = Path(__file__).resolve().parent.parent


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "adr", "0015-chat-first-home.md")
        cls.adr = flat(cls.raw)

    def test_it_is_final_and_has_the_sections_of_the_others(self):
        self.assertTrue(self.raw.startswith("# 0015 "))
        self.assertIn("狀態：已決定", self.adr)
        for heading in ("## 背景", "## 決定", "## 考慮過的其他選項", "## 後果", "## 守門規則 17", "## 這版沒有改的邊界", "## 真機驗證"):
            self.assertIn(heading, self.raw, heading)
        for left_over in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(left_over, self.raw, left_over)
        self.assertEqual(problems(self.adr, "ADR 0015"), [])

    def test_it_corrects_decisions_1_and_3_of_adr_0013_and_says_it_only_changes_the_screen(self):
        for part in ("修正 ADR 0013 第 1 點", "修正 ADR 0013 第 3 點", "只改畫面", "不新增 API 路徑", "15b 不改、照舊通過", "`href`、`data-nav` 不變", "不另外讀、不設計時器"):
            self.assertIn(part, self.adr, part)
        old = flat(raw("docs", "adr", "0013-plain-navigation.md"))
        self.assertIn("v0.23.0 修正（ADR 0015）", old)
        self.assertGreaterEqual(old.count("ADR 0015"), 2)

    def test_the_rules_17a_17b_17c_are_named_with_their_files(self):
        for part in ("17a 範例句只填字、不送", "17b 左欄「最近」不另外讀、不設計時器", "17c 首頁輸入框只有 Cmd/Ctrl + Enter 送出", "tests/test_autonomy_guard.py"):
            self.assertIn(part, self.adr, part)


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.23.0", "## v0.22.1"))
        model = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(section(model, "## Chat-first home (v0.23)"))
        cls.arch = flat(section(raw("docs", "ARCHITECTURE.md"), "## Chat-first home — `web/index.html`, `web/app.js`, `web/style.css` (v0.23)"))
        cls.glossary = raw("GLOSSARY.md")
        cls.app = raw("web", "app.js")
        cls.index = raw("web", "index.html")

    def test_the_changelog_starts_with_this_release_and_the_version_is_the_release(self):
        import vbear
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.25.5 — "), self.changelog[:60])      # (v0.25.5, v0.25.4, v0.25.3, v0.25.2, v0.25.1, v0.25.0 and v0.24.0 put themselves in front of v0.23.0's)
        self.assertIn("\n## v0.23.0 — ", self.changelog)
        self.assertLess(self.changelog.index("## v0.23.0"), self.changelog.index("## v0.22.1"))
        self.assertEqual(vbear.__version__, "0.25.5")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.23.0"), [])

    def test_the_changelog_says_what_changed_what_did_not_and_what_is_not_tried(self):
        for part in ("今天想做什麼？", "新對話", "最近", "Rule 17a", "17b", "17c", "Rule 15b", "Money.", "Nothing here costs anything", "Not tried on a real Mac", "no request of its own", "Going back to v0.22.1"):
            self.assertIn(part, self.first, part)

    def test_the_security_model_says_it_is_only_the_screen(self):
        for part in ("no file under `vbear/` changed except the version number", "no new route, request", "rule 17c", "rule 17a", "rule 17b", "15b", "`GET /api/chats`", "`setInterval`/`setTimeout`"):
            self.assertIn(part, self.model, part)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.23"), [])

    def test_the_architecture_names_things_the_page_has(self):
        for name in ("viewHome", "homeWaiting", "homeGreeting", "homeAsk", "homeAskGrow", "homeAskKeydown", "homeExampleFill", "homeTeam", "homeToday", "homeNothingFocused",
                     "navRecentRows", "drawNavRecent", "wireNavMenu", "syncNavMenu"):
            self.assertIn(name, self.arch, name)
            self.assertRegex(self.app, rf"(function|const) {name}\b", f"web/app.js has {name}")
        for rule in ("17a", "17b", "17c", "15b"):
            self.assertIn(rule, self.arch, rule)
        for hook in ('id="nav-toggle"', 'id="side-panel"', 'id="nav-recent"', 'id="nav-backdrop"', 'data-nav="home"'):
            self.assertIn(hook, self.index, hook)
        self.assertEqual(problems(self.arch, "ARCHITECTURE v0.23"), [])

    def test_the_glossary_has_the_two_new_words_and_the_page_says_them(self):
        for word in ("**新對話**：", "**最近**：", "不另外讀、不設計時器", "`href=\"#/\"`、`data-nav=\"home\"` 不變"):
            self.assertIn(word, self.glossary, word)
        self.assertIn('newChat:       { use: "新對話"', self.app)
        self.assertIn('recent:        { use: "最近"', self.app)
        for word in ("新對話", "最近", "今天想做什麼？", "新增員工", "有事等你決定"):
            self.assertIn(word, self.app + self.index, word)

    def test_both_readmes_and_the_reference_say_the_bar_has_new_chat_and_recent(self):
        en, zh, ref = flat(raw("README.md")), flat(raw("README.zh-TW.md")), flat(raw("docs", "REFERENCE.zh-TW.md"))
        self.assertIn("The bar on the left has 新對話", en)
        self.assertIn("左邊選單有「新對話」「最近」", zh)
        self.assertIn("v0.23 起選單項叫「新對話」", ref)
        self.assertIn("| 首頁（v0.21 起；以前叫冒險者大廳） |", ref)
        for text in (en, zh):
            self.assertIn("今天想做什麼？", text)
            self.assertIn("ADR 0015", text)


class GuardFilesTests(unittest.TestCase):
    def test_the_files_of_rule_17_are_there_and_carry_its_number(self):
        for rule, parts in (("17a", ("tests", "frontend", "p50_home.cjs")), ("17c", ("tests", "frontend", "p50_home.cjs")), ("17b", ("tests", "frontend", "p50_nav.cjs"))):
            self.assertIn(rule, raw(*parts), "/".join(parts))
        guard = raw("tests", "test_autonomy_guard.py")
        for part in ("class ChatFirstHomeRules", "class Guard17FilesAreThere", "     17a  ", "     17b  ", "     17c  "):
            self.assertIn(part, guard, part)
        self.assertTrue((ROOT / "tests" / "frontend" / "p50_theme.cjs").is_file())

    def test_rule_15b_is_still_there_unchanged_in_kind(self):
        guard = raw("tests", "test_autonomy_guard.py")
        self.assertIn("class NothingNewIsAsked", guard)
        self.assertIn("def test_15b_the_page_uses_no_path_that_v0200_did_not", guard)
        self.assertRegex(guard, re.compile(r"15b\s+nothing new is asked of the server"))


if __name__ == "__main__":
    unittest.main()
