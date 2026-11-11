"""v0.22.1 documents: the evidence files of Claude Code 2.1.322 and Codex 0.167.0 say what was compared and how, AGY 1.5.5 is written down as not added (and
the code agrees), the changelog and the security model say what the release changed and what it did not, and none of it names a person or a machine.

Seams: the text of the documents (whitespace flattened) and the public tables of the three protocol modules."""
from __future__ import annotations

import unittest

import vbear
from tests.test_p47_docs import flat, problems, raw, section
from vbear import admin_policy as ap
from vbear.runtime import agy_chat_protocol as acp
from vbear.runtime import chat_protocol as cp
from vbear.runtime import cli_versions
from vbear.runtime import codex_chat_protocol as ccp


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claude = flat(raw("docs", "evidence", "claude-code-2.1.322-chat.md"))
        cls.codex = flat(raw("docs", "evidence", "codex-0.167.0-chat.md"))
        cls.agy = flat(raw("docs", "evidence", "agy-1.5.5-not-added.md"))

    def test_claude_says_what_was_compared_with_which_file_and_how(self):
        for word in ("2026-11-11", "`--help`", "identical", "313 lines", "`strings -a`", "policy-limits.json", "2.1.319",
                     "a9d237949db816a0b7afd88a9a8e1df36b3a597a30f5a41d1c0539eb180a3450", "1f53587e92dee8e089fa349188a4cda64fa34ace6e7b0ca2ee278ddaa3cc2ebd",
                     "is **not** in any verified list", "boundary_check --mode chat"):
            self.assertIn(word, self.claude, word)

    def test_codex_says_what_was_compared_with_which_file_and_how(self):
        for word in ("2026-11-11", "0.163.0", "0.167.0", "/etc/codex", "com.openai.codex", "`--startup-sign-out`", "`generate-json-schema`",
                     "`humanCommand`", "`realtime_conversation` and `worktrees`", "`removed`", "an empty temporary folder", "starts no",
                     "8813367285524ac798dd96d1b071aea30d58708c7226fd236cd275cf1cfdee31", "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc",
                     "**not** in `CODEX_CHAT_VERIFIED_VERSIONS`", "boundary_check --mode codex-chat"):
            self.assertIn(word, self.codex, word)

    def test_agy_says_why_1_5_5_was_not_added(self):
        for word in ("not added", "`skills/native_swarm/SKILL.md`", "25f6eb1e3b43a5589a776ce6e53b29896ef13bc6449716ee578ea09e95ef197f",
                     "2e8009f09eff39c5e2658bb2e518159f1d403c3fd0548ef871bd225bb0d47b44", "`.manifest`", "`builtin_sha256`", "a run of the real 1.5.5",
                     "42b591f206a868dd0b924d5b6b396638a108539367695a5dbe2f7dcfdbf4d6f3", "**unchanged**"):
            self.assertIn(word, self.agy, word)

    def test_nothing_in_them_names_a_person_or_a_machine(self):
        for label, text in (("claude", self.claude), ("codex", self.codex), ("agy", self.agy)):
            self.assertEqual(problems(text, label), [])


class TablesTests(unittest.TestCase):
    def test_the_new_versions_are_known_and_not_verified(self):
        self.assertIn("2.1.322", cp.VERSIONS)
        self.assertIn("0.167.0", ccp.VERSIONS)
        self.assertEqual(ap.CLAUDE_SOURCES["2.1.322"], ap.CLAUDE_SOURCES["2.1.319"])
        self.assertEqual(ap.CODEX_SOURCES["0.167.0"], ap.CODEX_SOURCES["0.163.0"])
        for versions in (cli_versions.CHAT_VERIFIED_VERSIONS, cli_versions.CODEX_CHAT_VERIFIED_VERSIONS, cli_versions.AGY_CHAT_VERIFIED_VERSIONS):
            self.assertNotIn("2.1.322", versions)
            self.assertNotIn("0.167.0", versions)
            self.assertNotIn("1.5.5", versions)

    def test_agy_1_5_5_is_not_added_anywhere(self):
        self.assertEqual(sorted(ap.AGY_SOURCES), ["1.5.3"])
        self.assertEqual(sorted(acp.VERSIONS), ["1.5.3"])
        self.assertIsNone(acp.constants_for("1.5.5"))
        self.assertFalse(ap.check_agy("1.5.5", "/nonexistent-root-for-vbear-test").ok)


class ChangelogAndModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = raw("CHANGELOG.md")
        cls.text = text
        cls.first = flat(section(text, "## v0.22.1", "## v0.22.0"))
        model = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(model[model.index("## New versions of the AI tools (v0.22.1)"):])

    def test_the_release_is_first_and_the_version_is_the_release(self):
        self.assertTrue(self.text.startswith("# Changelog\n\n## v0.22.1 — Claude Code 2.1.322 and Codex 0.167.0\n"), self.text[:90])
        self.assertEqual(vbear.__version__, "0.22.1")
        self.assertNotIn("Unreleased", self.first)

    def test_the_changelog_says_what_was_added_what_was_not_and_what_is_still_to_do(self):
        for word in ("2.1.322", "0.167.0", "You still press 「聊天安全檢查」", "AGY 1.5.5 is not added", "`native_swarm/SKILL.md`", "`realtime_conversation` and `worktrees`",
                     "`docs/evidence/claude-code-2.1.322-chat.md`", "`docs/evidence/codex-0.167.0-chat.md`", "`docs/evidence/agy-1.5.5-not-added.md`",
                     "**Money.**", "**Known limits.**", "Start-up boundary"):
            self.assertIn(word, self.first, word)
        self.assertEqual(problems(self.first, "CHANGELOG v0.22.1"), [])

    def test_the_security_model_names_the_boundary_it_touched_and_the_residual_risks(self):
        for word in ("`vbear/admin_policy.py`", "`vbear/runtime/chat_protocol.py`", "`vbear/runtime/codex_chat_protocol.py`", "never one that is trusted", "Residual risks",
                     "`humanCommand`", "AGY is not part of it", "`docs/evidence/agy-1.5.5-not-added.md`"):
            self.assertIn(word, self.model, word)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.22.1"), [])


if __name__ == "__main__":
    unittest.main()
