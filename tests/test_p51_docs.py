"""P51-4 documents: ADR 0016 is final (and ADR 0013 points to it), the changelog, the security model, the architecture and the glossary say what v0.24.0 changed and
what it did not, the words they quote are the page's, the files of guard rule 18 are there and each carries its number, the version is the release's (0.25.0 since P52), and nothing P51-4 added
names a person or a machine.

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
        cls.raw = raw("docs", "adr", "0016-chat-reads-like-text.md")
        cls.adr = flat(cls.raw)

    def test_it_is_final_and_has_the_sections_of_the_others(self):
        self.assertTrue(self.raw.startswith("# 0016 "))
        self.assertIn("狀態：已決定", self.adr)
        for heading in ("## 背景", "## 決定", "## 考慮過的其他選項", "## 後果", "## 守門規則 18", "## 這版沒有改的邊界", "## 真機驗證"):
            self.assertIn(heading, self.raw, heading)
        for left_over in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(left_over, self.raw, left_over)
        self.assertEqual(problems(self.adr, "ADR 0016"), [])

    def test_it_corrects_point_6_of_adr_0013_and_says_what_is_never_folded(self):
        for part in ("修正 ADR 0013 第 6 點", "只改畫面", "不新增 API 路徑", "15b 照舊通過", "永遠直接看得到、不得收進任何摺疊", "摺疊是純顯示", "選取本身不送出任何訊息",
                     "`turn_ended` 的原因不是「做完了」", "摘要行沒有金額", "輸入法組字中的 Enter 不送"):
            self.assertIn(part, self.adr, part)
        old = flat(raw("docs", "adr", "0013-plain-navigation.md"))
        self.assertIn("v0.24.0 修正（ADR 0016）", old)
        self.assertGreaterEqual(old.count("ADR 0016"), 1)

    def test_the_rules_18a_to_18d_are_named_with_their_files(self):
        for part in ("18a 摺疊只收工作紀錄", "18b 換員工不送出、不寫入", "18c 聊天頁輸入框只有 Cmd/Ctrl + Enter 送出", "18d 摺疊的摘要行沒有金額", "tests/test_autonomy_guard.py"):
            self.assertIn(part, self.adr, part)


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.24.0", "## v0.23.0"))
        cls.model = flat(section(raw("docs", "SECURITY-MODEL.md"), "## Chat reads like text (v0.24)"))
        cls.arch = flat(section(raw("docs", "ARCHITECTURE.md"), "## Chat reads like text — `web/app.js`, `web/style.css` (v0.24)"))
        cls.glossary = raw("GLOSSARY.md")
        cls.app = raw("web", "app.js")

    def test_the_changelog_starts_with_this_release_and_the_version_is_the_release(self):
        import vbear
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.25.6 — "), self.changelog[:60])      # (v0.25.6, v0.25.5, v0.25.4, v0.25.3, v0.25.2, v0.25.1 and v0.25.0 put themselves in front of v0.24.0's)
        self.assertIn("\n## v0.24.0 — ", self.changelog)
        self.assertLess(self.changelog.index("## v0.24.0"), self.changelog.index("## v0.23.0"))
        self.assertEqual(vbear.__version__, "0.25.6")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.24.0"), [])

    def test_the_changelog_says_what_changed_what_did_not_and_what_is_not_tried(self):
        for part in ("Words, not boxes", "The work is one line", "Nothing that needs you is folded", "whom you talk to", "A one-row head", "Rule 18a", "18b", "18c", "18d", "15b (no new",
                     "Money.", "Nothing here costs anything", "Not tried on a real Mac", "Going back to v0.23.0"):
            self.assertIn(part, self.first, part)

    def test_the_security_model_says_it_is_only_the_screen(self):
        for part in ("no file under `vbear/` changed except the version number", "no new route, request", "rule 18a", "rule 18b", "rule 18c", "rule 18d", "15b", "`GET /api/chats`",
                     "`!e.isComposing`", "Folding hides no decision and no record", "Changing whom you talk to sends nothing", "Residual risk"):
            self.assertIn(part, self.model, part)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.24"), [])

    def test_the_architecture_names_things_the_page_has(self):
        for name in ("chatColumn", "chatLine", "chatTimeNode", "chatIsQuiet", "chatQuietLog", "chatQuietSummary", "whoPicker", "chatWhoGo", "chatWhoLater", "homeAsk", "chatHeadLine",
                     "chatRow", "CHAT_QUIET_KINDS"):
            self.assertIn(name, self.arch, name)
            self.assertRegex(self.app, rf"(function|const) {name}\b", f"web/app.js has {name}")
        for rule in ("18a", "18b", "18c", "18d", "15b"):
            self.assertIn(rule, self.arch, rule)
        self.assertEqual(problems(self.arch, "ARCHITECTURE v0.24"), [])

    def test_the_glossary_has_the_two_new_words_and_the_page_says_them(self):
        for word in ("**細節**：", "**要跟誰說**：", "每一筆紀錄都還在頁面裡", "選取本身不送出任何訊息"):
            self.assertIn(word, self.glossary, word)
        self.assertIn('chatFold:      { use: "細節"', self.app)
        self.assertIn('whoTo:         { use: "要跟誰說"', self.app)
        for word in ("細節", "用了 ${", "還不能聊", "現在對"):
            self.assertIn(word, self.app, word)


class GuardFilesTests(unittest.TestCase):
    def test_the_files_of_rule_18_are_there_and_carry_its_number(self):
        for rule, parts in (("18a", ("tests", "frontend", "p51_chat.cjs")), ("18d", ("tests", "frontend", "p51_chat.cjs")), ("18b", ("tests", "frontend", "p51_who.cjs")),
                            ("18c", ("tests", "frontend", "p51_who.cjs"))):
            self.assertIn(rule, raw(*parts), "/".join(parts))
        guard = raw("tests", "test_autonomy_guard.py")
        for part in ("class ChatReadsLikeTextRules", "class Guard18FilesAreThere", "     18a  ", "     18b  ", "     18c  ", "     18d  "):
            self.assertIn(part, guard, part)
        self.assertTrue((ROOT / "tests" / "frontend" / "p51_head.cjs").is_file())

    def test_rules_15b_and_17_are_still_there_unchanged_in_kind(self):
        guard = raw("tests", "test_autonomy_guard.py")
        self.assertIn("class NothingNewIsAsked", guard)
        self.assertIn("def test_15b_the_page_uses_no_path_that_v0200_did_not", guard)
        self.assertRegex(guard, re.compile(r"15b\s+nothing new is asked of the server"))
        for part in ("class ChatFirstHomeRules", "class Guard17FilesAreThere"):
            self.assertIn(part, guard, part)


if __name__ == "__main__":
    unittest.main()
