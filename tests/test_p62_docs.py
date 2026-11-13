"""P62 documents (v0.26.0): ADR 0021, the changelog and the security model say what the release keeps, when it is used, what it checks and what it did not see; the words they quote are the
code's (the modes, the number of copies, the folder, the record's fields), the version is 0.26.0 (v0.25.6 is the section just behind v0.26.0's), and nothing they added names a person or a
machine.

Seams: the text of the documents (whitespace flattened) and the public constants of the module."""
from __future__ import annotations

import unittest
from pathlib import Path

import vbear
from tests.test_p47_docs import flat, problems, raw, section
from vbear.runtime import agy_kept

ROOT = Path(__file__).resolve().parent.parent
SECTION = "## Keeping the verified AGY (v0.26.0)"


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adr = flat(raw("docs", "adr", "0021-keep-the-verified-agy.md"))

    def test_it_says_the_decision_the_options_left_out_and_the_residual_risks(self):
        for word in ("驗的就是存的那一份", "SHA-256", "0500", "0700", "O_EXCL", "PATH 上沒有 `agy`", "daemon 端", "每個工具最多保留 2 份",
                     "考慮過的其他選項", "後果", "Google 若拒絕舊版連線", "守門 25", "沒有 `sha256` 的舊紀錄", "補記", "不改回"):
            self.assertIn(word, self.adr, word)

    def test_nothing_in_it_names_a_person_or_a_machine(self):
        self.assertEqual(problems(self.adr, "0021"), [])


class ConstantsTests(unittest.TestCase):
    def test_the_documents_quote_the_code(self):
        self.assertEqual(agy_kept.FILE_MODE, 0o500)
        self.assertEqual(agy_kept.KEEP, 2)
        self.assertEqual(agy_kept.BINARY_NAME, "agy")
        self.assertEqual(agy_kept.root("/x/state"), "/x/state/tools/agy")


class ChangelogAndModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.26.0", "## v0.25.6"))
        cls.security = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(cls.security[cls.security.index(SECTION):])

    def test_the_release_is_first_and_the_version_is_the_release(self):
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.26.0 — Chat keeps working when AGY updates itself\n"), self.changelog[:90])
        self.assertLess(self.changelog.index("## v0.26.0"), self.changelog.index("## v0.25.6"))
        self.assertEqual(vbear.__version__, "0.26.0")
        self.assertNotIn("Unreleased", self.first)

    def test_the_changelog_says_what_is_kept_when_it_is_used_and_what_stays(self):
        for word in ("press the check once on this version", "Claude Code and Codex are not changed", "SHA-256", "250 MB", "two at most", "tools/agy/", "never falls back",
                     "does not count", "Google may refuse", "No real AGY was copied or run", "Going back to v0.25.6", "guard rule 25", "no existing check was loosened", "Money"):
            self.assertIn(word, self.first, word)

    def test_the_security_model_names_the_boundary_it_touched_and_the_residual_risks(self):
        for word in ("touches the start-up boundary on purpose", "vbear/runtime/agy_kept.py", "pinned_binary", "_agy_spawn", "check_for_launch", "`sha256` and `size`, never a path", "`O_EXCL` and `O_NOFOLLOW`",
                     "mode exactly 0700", "mode exactly 0500", "`st_nlink` 1", "equals the record's", "does not fall back", "Never when AGY is not installed", "Residual risks", "Google may refuse an old AGY",
                     "KeptAgyRules", "25a to 25e", "rules 1 to 24 are unchanged word for word", "What was not tested", "Going back to v0.25.6", "delete `<state>/tools/agy/`"):
            self.assertIn(word, self.model, word)

    def test_the_security_model_is_the_last_section_and_nothing_names_a_person(self):
        self.assertNotIn("\n## ", self.security[self.security.index(SECTION) + 5:], "v0.26.0's is the last section")
        self.assertLess(self.security.index("## AGY 1.5.8 (v0.25.6)"), self.security.index(SECTION))
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.26.0"), [])
        self.assertEqual(problems(self.first, "CHANGELOG v0.26.0"), [])

    def test_the_glossary_and_the_reference_say_it(self):
        self.assertIn("**保留的已驗證版本**", raw("GLOSSARY.md"))
        self.assertIn("tools/agy", flat(raw("docs", "REFERENCE.zh-TW.md")))

    def test_the_guard_rule_and_the_tests_are_there(self):
        self.assertTrue((ROOT / "tests" / "test_p62_kept_agy.py").is_file())
        self.assertIn("class KeptAgyRules", (ROOT / "tests" / "test_autonomy_guard.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
