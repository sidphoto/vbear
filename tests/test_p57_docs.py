"""P57 documents: ADR 0019 is final (and says what it adds to ADR 0017), the changelog, the security model, the architecture and the glossary say what v0.25.1 changed and what it did not,
the words they quote are the page's, the files of guard rule 21 are there and each carries its number, the version is 0.25.1, and nothing they added names a person or a machine.

Seams: the text of the documents (whitespace flattened), the page's source for the words it uses, and the files of the guard rule."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_p47_docs import flat, problems, raw, section

ROOT = Path(__file__).resolve().parent.parent


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "adr", "0019-switch-tool-when-held.md")
        cls.adr = flat(cls.raw)

    def test_it_is_final_and_has_the_sections_of_the_others(self):
        self.assertTrue(self.raw.startswith("# 0019 "))
        self.assertIn("狀態：已決定", self.adr)
        for heading in ("## 背景", "## 決定", "## 沒有改的", "## 考慮過的其他選項", "## 後果", "## 守門規則 21"):
            self.assertIn(heading, self.raw, heading)
        for left_over in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(left_over, self.raw, left_over)
        self.assertEqual(problems(self.adr, "ADR 0019"), [])

    def test_it_says_the_press_only_opens_a_confirmation_and_the_write_is_the_ordinary_one(self):
        for part in ("按下去不會馬上改", "只有「確認」那一下寫入", "`POST /api/agent-profiles/<id>`", '{"model": {"tool": …, "model_id": ""}}', "與員工編輯表單換工具時是同一個寫入",
                     "不多讀任何 API", "`card_tool_changed`", "資料流向", "不自動檢查", "`policy`", "`unsupported`", "沒有新增 API 路徑", "`homeChatsOf`"):
            self.assertIn(part, self.adr, part)

    def test_the_rules_21a_to_21d_are_named_with_their_file_and_20_and_0018_are_not_taken(self):
        for part in ("21a 換工具的寫入只由確認鈕的 click 送出", "21b 那個寫入的 body 只有 `model`", "21c 確認區一定有資料流向那一句", "tests/frontend/p57_switch.cjs",
                     "21d 「試一下」失敗時，工具印在錯誤輸出的東西看過就丟", "SetupTryStderrRules", "tests/test_setup_try_failures.py"):
            self.assertIn(part, self.adr, part)
        self.assertNotIn("守門規則 20", self.adr)
        self.assertFalse(list((ROOT / "docs" / "adr").glob("0018-*")), "0018 belongs to another release")


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.25.1", "## v0.25.0"))
        cls.model = flat(section(raw("docs", "SECURITY-MODEL.md"), "## Switch the AI tool of a held-back employee (v0.25.1)"))
        cls.arch = flat(section(raw("docs", "ARCHITECTURE.md"), "## Switch the AI tool of a held-back employee — `web/app.js`, `web/style.css` (v0.25.1)"))
        cls.glossary = raw("GLOSSARY.md")
        cls.app = raw("web", "app.js")

    def test_the_changelog_has_this_release_and_the_version_is_the_release(self):
        import vbear
        self.assertIn("## v0.25.1 — ", self.changelog)
        self.assertLess(self.changelog.index("## v0.25.1"), self.changelog.index("## v0.25.0"))
        self.assertEqual(vbear.__version__, "0.25.1")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.25.1"), [])

    def test_the_changelog_says_what_changed_what_did_not_and_what_is_not_tried(self):
        for part in ("A button to use another AI", "A press only opens a confirmation", "It is the ordinary employee write, with only `model`", "`POST /api/agent-profiles/<id>`", "no new path",
                     "Then the new tool's own state", "The reason says the next step", "not touched, loosened or worked around", "Old chats are not sent into", "Rule 21a", "21b", "21c",
                     "Money.", "Not tried on a real Mac", "Going back to v0.25.0"):
            self.assertIn(part, self.first, part)

    def test_the_changelog_says_a_failed_try_is_no_longer_always_not_logged_in(self):
        for part in ("no longer says \"not logged in\" for every failure", "last 4 KiB", "never stored, logged or shown", "a login answer outranks a limit, which outranks a connection problem",
                     "登入檢查是通過的，不用再登入", "exit code (a number) is behind 「技術細節」", "Only Codex has a real sample", "Guard rule 21d", "`vbear/setup_try.py`", "`vbear/headless_cli.py`",
                     "The cost booking, the confirmation, the 60 seconds and the one-at-a-time lock are unchanged", "is not known (the new sentence and the exit code are there"):
            self.assertIn(part, self.first, part)

    def test_the_security_model_says_the_error_output_tail_is_read_only_to_tell_failures_apart(self):
        for part in ("reads the tail of the tool's error output, only to tell a few failures apart", "guard rule 21d", "`headless_cli.run(stderr_tail=4096)`", "never block on a full pipe",
                     "keeps in memory only its last 4 KiB", "`setup_try.classify_failure`", "to nothing else", "first class that matches in that order wins", "not stored, logged, written to a file",
                     "the error output of a try that succeeds is not read for anything", "Only Codex has a real sample", "unchanged"):
            self.assertIn(part, self.model, part)
        older = flat(section(raw("docs", "SECURITY-MODEL.md"), "**A try is isolated and booked.**", "**The daily limit the person picks only ever lowers other limits.**"))
        self.assertIn("also the last 4 KiB of the error output", older)
        self.assertIn("dropped", older)

    def test_the_security_model_says_it_is_only_the_screen_and_one_confirmed_write(self):
        for part in ("only what the screen shows", "no route (API path), no kind of request", "rule 21", "Nothing about the hold is loosened", "Only 「確認，改用 …」 sends", "guard rule 21a",
                     "The data flow changes", "21c", "Residual risks"):
            self.assertIn(part, self.model, part)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.25.1"), [])

    def test_the_architecture_names_things_the_page_has(self):
        for name in ("chatSwitchOptions", "switchToolNode", "switchToolConfirmNode", "switchToolHost", "switchToolConfirm", "switchToolUi", "homeChatsOf"):
            self.assertIn(name, self.arch, name)
            self.assertRegex(self.app, rf"(function|const) {name}\b", f"web/app.js has {name}")
        for part in ("21a to 21c", "15b", "setupTryWords", "setupLoginPasses", "classify_failure", "stderr_tail", "21d"):
            self.assertIn(part, self.arch, part)
        for name in ("setupTryWords", "setupLoginPasses"):
            self.assertRegex(self.app, rf"function {name}\b", f"web/app.js has {name}")
        self.assertEqual(problems(self.arch, "ARCHITECTURE v0.25.1"), [])

    def test_the_glossary_has_the_new_word_and_the_page_says_it(self):
        self.assertIn("**改用另一家**：", self.glossary)
        self.assertIn('switchTool:    { use: "改用另一家"', self.app)
        for word in ("確認，改用", "先不要", "之後跟他說的話會送到", "之前用", "可以讓", "改用別家 AI", "不確定有沒有改成", "還沒安裝，不能改用"):
            self.assertIn(word, self.app, word)
        self.assertEqual(problems(self.glossary, "GLOSSARY"), [])


class GuardFilesTests(unittest.TestCase):
    def test_the_file_of_rule_21_is_there_and_carries_its_numbers(self):
        spec = raw("tests", "frontend", "p57_switch.cjs")
        for rule in ("21a", "21b", "21c"):
            self.assertIn(rule, spec, rule)
        guard = raw("tests", "test_autonomy_guard.py")
        for part in ("class Guard21FilesAreThere", "class SetupTryStderrRules", "     21a  ", "     21b  ", "     21c  ", "     21d  "):
            self.assertIn(part, guard, part)
        self.assertIn("21d", raw("tests", "test_setup_try_failures.py"))

    def test_the_words_of_the_server_for_a_failed_try_are_the_page_s(self):
        from vbear import setup_try
        app = raw("web", "app.js")
        self.assertIn(setup_try.RESULT_WORDS["failed"].replace("{name}", "${name}"), app, "the page says the same unknown-reason sentence as the server")
        self.assertIn("登入檢查是通過的，不用再登入", app)
        for code in ("limit", "network", "failed"):
            self.assertIn(code, setup_try.RESULT_WORDS)
            self.assertNotIn("請先按「登入」", setup_try.RESULT_WORDS[code], code)

    def test_rules_15b_to_19_are_still_there(self):
        guard = raw("tests", "test_autonomy_guard.py")
        self.assertIn("class NothingNewIsAsked", guard)
        for part in ("class Guard16FilesAreThere", "class Guard17FilesAreThere", "class Guard18FilesAreThere", "class Guard19FilesAreThere"):
            self.assertIn(part, guard, part)


if __name__ == "__main__":
    unittest.main()
