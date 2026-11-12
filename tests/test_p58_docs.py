"""P58 documents: ADR 0020 is final, the changelog, the security model and the glossary say what v0.25.3 changed and what it did not (the name goes to the company, only a new chat has it, the
record gained one field), the words they quote are the code's, the files of guard rule 22 are there and carry their numbers, the version is 0.25.3 (v0.25.2 is the section just behind v0.25.3's), and
nothing they added names a person or a machine.

Seams: the text of the documents (whitespace flattened), the code's constants for the words, and the files of the guard rule."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_p47_docs import flat, problems, raw, section

ROOT = Path(__file__).resolve().parent.parent


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "adr", "0020-employee-knows-its-name.md")
        cls.adr = flat(cls.raw)

    def test_it_is_final_and_has_the_sections_of_the_others(self):
        self.assertTrue(self.raw.startswith("# 0020 "))
        self.assertIn("狀態：已決定", self.adr)
        for heading in ("## 背景", "## 決定", "## 沒有改的", "## 考慮過的其他選項", "## 後果", "## 守門規則 22"):
            self.assertIn(heading, self.raw, heading)
        for left_over in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(left_over, self.raw, left_over)
        self.assertEqual(problems(self.adr, "ADR 0020"), [])

    def test_it_says_where_the_sentence_goes_what_is_cleaned_and_what_a_chat_that_exists_keeps(self):
        from vbear.runtime import memory_rules as mr
        for part in ("`--append-system-prompt`", "`developerInstructions`", "`systemPrompt.append`", "`memory_rules.combine`", "最前面", "64 字", "整段不送", "`prepare_identity`", "9,500",
                     "`chat-prompt/<id>.json`", "`identity: true`", "升級不會把舊對話全標成「改了」", "只有開新對話才生效", "`process_started`", "選填布林 `identity`", "送到這位員工用的那家公司",
                     "群組聊天、例行工作、派工步驟", "沒有新增 API 路徑", "降版", "22a", "22b", "22c", "EmployeeNameRules", "tests/test_p58_identity.py", "tests/frontend/p58_chat.cjs"):
            self.assertIn(part, self.adr, part)
        self.assertIn(mr.IDENTITY_HEAD.strip(), self.adr)
        self.assertEqual(len(list((ROOT / "docs" / "adr").glob("0020-*"))), 1)


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.25.3", "## v0.25.2"))
        cls.security = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(section(cls.security, "## An employee knows its own name (v0.25.3)"))
        cls.glossary = raw("GLOSSARY.md")

    def test_the_changelog_has_this_release_and_the_version_is_the_release(self):
        import vbear
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.25.3 — "), self.changelog[:60])
        self.assertLess(self.changelog.index("## v0.25.3"), self.changelog.index("## v0.25.2"))
        self.assertEqual(vbear.__version__, "0.25.3")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.25.3"), [])

    def test_the_changelog_says_what_changed_what_did_not_and_what_is_not_tried(self):
        for part in ("an employee knows its own name", "fixed sentence", "in front of everything else", "the employees you already have", "Only a new chat starts with it",
                     "The name goes to the company", "Anthropic, OpenAI or Google", "64 characters", "is not sent at all", "帶著名字和職位", "沒有帶名字和職位", "9,500",
                     "Not tried on a real Mac", "22a:", "22b:", "22c:", "`identity`", "Going back to v0.25.2", "open new chats"):
            self.assertIn(part, self.first, part)

    def test_the_changelog_quotes_the_sentence_the_code_makes(self):
        from vbear.runtime import memory_rules as mr
        sentence = mr.identity_block({"name": "阿福CEO", "position": "CEO"}, "codex-chat")
        self.assertIn(sentence.split("] ", 1)[1], self.first)

    def test_the_security_model_says_what_leaves_the_machine_and_how(self):
        for part in ("changes what VBear sends to an AI company", "Anthropic for a Claude Code employee", "OpenAI for a Codex employee", "Google for an AGY employee", "`identity_parts`", "`prepare_identity`",
                     "is **not sent at all**", "64 characters", "guard rule 22a", "22b", "22c", "MAX_CHAT_APPEND_PROMPT", "9,500", "Only a new session has it", "`chat-prompt/<id>.json`", "`identity: true`",
                     "optional boolean `identity`", "guard rule 15b names it", "Residual risk", "Not verified", "Meetings, the chief of staff"):
            self.assertIn(part, self.model, part)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.25.3"), [])
        self.assertNotIn("\n## ", self.security[self.security.index("## An employee knows its own name (v0.25.3)") + 5:], "v0.25.3's is the last section")

    def test_the_glossary_has_the_new_word(self):
        self.assertIn("**身分段**：", self.glossary)
        self.assertEqual(problems(self.glossary, "GLOSSARY"), [])


class GuardFilesTests(unittest.TestCase):
    def test_the_files_of_rule_22_are_there_and_carry_its_numbers(self):
        guard = raw("tests", "test_autonomy_guard.py")
        for part in ("class EmployeeNameRules", "     22a  ", "     22b  ", "     22c  ", "def identity_first_problems", "def identity_clean_problems", "def identity_fixed_problems"):
            self.assertIn(part, guard, part)
        spec = raw("tests", "test_p58_identity.py")
        for part in ("class ClaudeIdentityTests", "class CodexIdentityTests", "class AgyIdentityTests", "class ServiceTests", "class FingerprintTests"):
            self.assertIn(part, spec, part)
        self.assertIn("process_started", raw("tests", "frontend", "p58_chat.cjs"))

    def test_the_words_of_the_page_are_the_ones_the_documents_quote(self):
        app = raw("web", "app.js")
        for word in ("帶著名字和職位", "沒有帶名字和職位", "名字、職位、固定指示"):
            self.assertIn(word, app, word)

    def test_rule_15b_names_the_one_field_it_allows(self):
        guard = raw("tests", "test_autonomy_guard.py")
        self.assertIn("CHAT_OPTIONAL_ADDED", guard)
        self.assertIn('"process_started": ("identity",)', guard)


if __name__ == "__main__":
    unittest.main()
