"""P59 documents: the changelog and the security model say what v0.25.4 changed and what it did not (the display-only version memory, the import fix, the qa tool, the two notes about
money), the words they quote are the code's, the version is 0.25.4 (v0.25.3 is the section just behind v0.25.4's), and nothing they added names a person or a machine.

Seams: the text of the documents (whitespace flattened) and the code's constants."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_p47_docs import flat, problems, raw, section

ROOT = Path(__file__).resolve().parent.parent


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.25.4", "## v0.25.3"))
        cls.security = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(section(cls.security, "## Display-only version cache (v0.25.4)"))
        cls.architecture = flat(raw("docs", "ARCHITECTURE.md"))

    def test_the_changelog_has_this_release_and_the_version_is_the_release(self):
        import vbear
        self.assertIn("\n## v0.25.4 — small fixes\n", self.changelog)          # (v0.25.5, v0.25.6 and v0.26.0 put themselves in front of it)
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.26.0 — "), self.changelog[:60])
        self.assertLess(self.changelog.index("## v0.25.4"), self.changelog.index("## v0.25.3"))
        self.assertEqual(vbear.__version__, "0.26.0")          # (it was 0.25.4 before v0.25.5 was put in front of it, and 0.25.5 before v0.25.6)
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.25.4"), [])

    def test_the_changelog_says_what_changed_what_did_not_and_what_is_not_tried(self):
        for part in ("no longer starts Claude Code on every read", "kept for 30 seconds", "read again at once when the program changed", "never kept", "3 reads, 3 starts", "3 reads, 1 start",
                     "Codex and AGY were already kept for 10 seconds", "still read the version fresh, every time", "`check_cli_version_for_display`", "carries no file identity",
                     "`vbear/zh_simplified.py`", "imports every module of the package alone", "`--ask-for-approval`", "`about:blank`", "`vbear-setup-pick`",
                     "chief of staff reads the chat and builds its list of cards first", "A known gap in the day's money", "US$0.10 a press", "200 records", "unchanged",
                     "23a", "23b", "`DisplayVersionCacheRules`", "Going back to v0.25.3", "Nothing to convert", "Not tried on a real Mac", "known limits", "change time"):
            self.assertIn(part, self.first, part)

    def test_the_security_model_says_what_is_kept_and_what_is_not_and_why_a_start_is_not_touched(self):
        import vbear.runtime.cli_versions as cv
        for part in ("Display-only version cache (v0.25.4)", "`check_cli_version_for_display`", "`invalidate_display_cache`", "`DISPLAY_CACHE_TTL_S` = 30 seconds", "`DISPLAY_CACHE_MAX` = 16",
                     "`ai_tool_status.CACHE_TTL_S`", "never stored", "`_binary_identity=None`", "`version_assertion_missing`", "`_claude_fields`", "`_verify_claude`", "does **not** run `--version` itself",
                     "`_chat_precheck`", "`drift`", "(device, inode, mode, size, mtime_ns, ctime_ns)", "on every call, before the cache is looked at", "`ai_tool_status.report(force=True)`",
                     "`ClaudeVerifier._finish`", "`ChatVerifier._finish`", "Guard rules 23a and 23b", "`DisplayVersionCacheRules`", "Going back to v0.25.3", "Residual risk and not verified",
                     "Codex and AGY already keep their whole state for 10 seconds", "Nothing in `/api/chats` starts Grok or MCODE"):
            self.assertIn(part, self.model, part)
        self.assertEqual(cv.DISPLAY_CACHE_TTL_S, 30.0)
        self.assertEqual(cv.DISPLAY_CACHE_MAX, 16)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.25.4"), [])
        self.assertEqual(self.security[self.security.index("## Display-only version cache (v0.25.4)") + 5:].count("\n## "), 3, "only v0.25.5's, v0.25.6's and v0.26.0's sections follow v0.25.4's")          # (v0.25.5 added 「New versions of Claude Code and AGY (v0.25.5)」)
        self.assertIn("## An employee knows its own name (v0.25.3)", self.security)
        self.assertLess(self.security.index("## An employee knows its own name (v0.25.3)"), self.security.index("## Display-only version cache (v0.25.4)"))

    def test_the_security_model_and_the_architecture_name_the_guard_rules_and_the_tests(self):
        for part in ("`tests/test_p59_display_versions.py`", "`ChatService.claude_display()`"):
            self.assertIn(part, self.model, part)
        text = (ROOT / "tests" / "test_autonomy_guard.py").read_text(encoding="utf-8")
        for rule in "ab":
            self.assertIn(f"     23{rule}  ", text, rule)
        self.assertIn("`cli_versions.check_cli_version_for_display`", self.architecture)
        self.assertIn("v0.25.4", self.architecture)
        self.assertEqual(problems(self.architecture, "ARCHITECTURE"), [])

    def test_the_two_notes_about_money_are_in_the_security_model(self):
        gap = flat(self.security[self.security.index("### A known gap in the day's money"):self.security.index("### Residual risks of skills and routines")])
        for part in ("Checked again in v0.25.4", "`CALL_USD` = US$0.10", "`MAX_RECORDS`", "`_chat_day_spent`", "`meeting_limits.daily_usd` is the one day for everything", "at most what 「整理成技能」 spent that day"):
            self.assertIn(part, gap, part)
        chief = flat(self.security[self.security.index("### The chief of staff reads before it looks at the day's money"):])
        for part in ("`_context`", "the scan", "nothing is sent, no model is called, nothing is spent", "`_blockers`", "`stale_preview`", "`tests/test_p59_spend_notes.py`"):
            self.assertIn(part, chief, part)
        self.assertEqual(problems(gap + chief, "SECURITY-MODEL money notes"), [])

    def test_the_test_files_exist(self):
        for name in ("test_p59_display_versions.py", "test_p59_imports.py", "test_p59_spend_notes.py", "p59_fakes.py"):
            self.assertTrue((ROOT / "tests" / name).is_file(), name)
        self.assertTrue((ROOT / "vbear" / "zh_simplified.py").is_file())


if __name__ == "__main__":
    unittest.main()
