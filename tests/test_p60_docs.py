"""P60 documents (v0.25.5): the two evidence files say how Claude Code 2.1.323 and AGY 1.5.7 were looked at and what was not shown, the changelog and the security model say what the release
changed and what it did not, the words they quote are the code's, the version is 0.25.5 (v0.25.4 is the section just behind v0.25.5's), and nothing they added names a person or a machine.

Seams: the text of the documents (whitespace flattened) and the public tables of the protocol modules."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

import vbear
from tests.test_p47_docs import flat, problems, raw, section
from vbear import admin_policy as ap
from vbear.runtime import agy_chat_env as env
from vbear.runtime import agy_chat_protocol as acp
from vbear.runtime import chat_protocol as cp
from vbear.runtime import cli_versions

ROOT = Path(__file__).resolve().parent.parent


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claude = flat(raw("docs", "evidence", "claude-code-2.1.323-chat.md"))
        cls.agy = flat(raw("docs", "evidence", "agy-1.5.7-chat.md"))

    def test_claude_says_what_was_compared_with_which_file_and_how(self):
        for word in ("2026-11-13", "`--help`", "`rm <id>`", "313 lines against 315", "`strings -a`", "policy-limits.json", "2.1.322",
                     "5432918d904a9b6afef7bb79d20df24d76052eabc1f41bceb84091d21f8889a7", "a9d237949db816a0b7afd88a9a8e1df36b3a597a30f5a41d1c0539eb180a3450",
                     "`--managed-settings-in-initialize`", "`--await-initialize`", "`managedSettings`", "guard rule 24", "VBear **does** write an `initialize`",
                     "Not shown", "is **not** in any verified list", "boundary_check --mode chat"):
            self.assertIn(word, self.claude, word)
        for flag in ("--include-partial-messages", "--permission-prompt-tool", "--setting-sources", "--strict-mcp-config", "--append-system-prompt", "--max-budget-usd", "--session-id",
                     "--disallowedTools"):
            self.assertIn(f"`{flag}`", self.claude, flag)

    def test_agy_says_what_was_looked_at_how_and_what_was_not_shown(self):
        for word in ("2026-11-13", "e872cc54b5381f401c798fc947937a0a930876b849bc3fee654996ba4ab236a8", "234,512,352", "`1.5.7`", "word for word", "`Authentication required`",
                     "No prompt was sent", "64 paths: 42 files and 22 folders", "34 files have the same SHA-256", "7 files differ", "1 file is new", "`skills/mcp-app-development/SKILL.md`",
                     "`.checksum`", "`.manifest`", "`plugins/swarm/sidecars/swarm_board/hive.css`", "`skills/native_swarm/SKILL.md`",
                     "`skills/swarm_narrator/SKILL.md`", "`skills/antigravity_guide/references/app.md`", "belongs to the version about to start", "`com.google.antigravity.companion`",
                     "Open point", "evidence for the tables, not a verification", "boundary_check --mode agy-chat",
                     "Not shown, on purpose"):
            self.assertIn(word, self.agy, word)

    def test_nothing_in_them_names_a_person_or_a_machine(self):
        for label, text in (("claude", self.claude), ("agy", self.agy)):
            self.assertEqual(problems(text, label), [])

    def test_neither_file_pastes_content_of_a_program(self):
        """Only names, hashes and counts: no line of a built-in file and no code of the Claude Code binary."""
        for label, text in (("claude", self.claude), ("agy", self.agy)):
            for marker in ("function(", "=>{", "import{", "```", "---\nname:"):
                self.assertNotIn(marker, text, f"{label}: {marker}")


class TablesTests(unittest.TestCase):
    def test_the_new_versions_are_known_and_in_no_verified_list(self):
        self.assertIn("2.1.323", cp.VERSIONS)
        self.assertEqual(ap.CLAUDE_SOURCES["2.1.323"], ap.CLAUDE_SOURCES["2.1.322"])
        self.assertIn("1.5.7", acp.VERSIONS)
        self.assertEqual(ap.AGY_SOURCES["1.5.7"], ap.AGY_SOURCES["1.5.6"])
        self.assertNotIn("2.1.323", cli_versions.CHAT_VERIFIED_VERSIONS)
        self.assertNotIn("1.5.7", cli_versions.AGY_CHAT_VERIFIED_VERSIONS)

    def test_the_hashes_in_the_evidence_are_the_tables(self):
        agy_text = raw("docs", "evidence", "agy-1.5.7-chat.md")
        self.assertIn("e872cc54b5381f401c798fc947937a0a930876b849bc3fee654996ba4ab236a8", agy_text)
        self.assertEqual(len(acp.VERSIONS["1.5.7"].builtin_sha256), 42)
        self.assertEqual(len(acp.VERSIONS["1.5.7"].builtin_paths), 64)
        self.assertEqual(len(env.builtin_table("1.5.7").dirs), 22)
        self.assertEqual(env.NEWEST_VERSION, "1.5.7")
        self.assertEqual(hashlib.sha256(b"").hexdigest(), dict(acp.VERSIONS["1.5.7"].builtin_sha256)["keep.txt"])


class ChangelogAndModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.25.5", "## v0.25.4"))
        security = raw("docs", "SECURITY-MODEL.md")
        cls.security = security
        cls.model = flat(security[security.index("## New versions of Claude Code and AGY (v0.25.5)"):])

    def test_the_release_is_first_and_the_version_is_the_release(self):
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.25.5 — VBear knows Claude Code 2.1.323 and AGY 1.5.7\n"), self.changelog[:90])
        self.assertLess(self.changelog.index("## v0.25.5"), self.changelog.index("## v0.25.4"))
        self.assertEqual(vbear.__version__, "0.25.5")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.25.5"), [])

    def test_the_changelog_says_what_was_added_what_was_not_seen_and_what_is_still_to_do(self):
        for word in ("2.1.323", "1.5.7", "you still press 「聊天安全檢查」 once on your own Mac for each", "a pass for an older version does not count for the new one",
                     "`rm <id>`", "A new door in Claude Code 2.1.323, and VBear does not use it", "`initialize`", "24", "ignore settings it is sent", "one new built-in skill",
                     "`skills/mcp-app-development`", "42 files", "34 files are identical", "7 of its own built-in files changed", "`hive.js`", "accepted for 1.5.7 and refused for 1.5.6",
                     "ADR 0018, unchanged", "`docs/evidence/agy-1.5.7-chat.md`", "`docs/evidence/claude-code-2.1.323-chat.md`", "`ManagedSettingsAreNeverSent`", "rule 20 now covers 1.5.7",
                     "**Money.**", "What was not seen, and known limits", "again does not know it until a new release", "`com.google.antigravity.companion`", "organisation's managed settings still cannot chat",
                     "Going back to v0.25.4", "Nothing to convert", "`web/app.js` did not change"):
            self.assertIn(word, self.first, word)

    def test_the_security_model_names_the_boundary_it_touched_and_the_residual_risks(self):
        for word in ("`vbear/runtime/chat_protocol.py`", "`vbear/runtime/agy_chat_protocol.py`", "`vbear/admin_policy.py`", "never one that is trusted", "Residual risks",
                     "`--managed-settings-in-initialize`", "`--await-initialize`", "Guard rule 24", "24a", "24b", "24c", "`ManagedSettingsAreNeverSent`", "Not shown:",
                     "64 paths", "`skills/mcp-app-development`", "`builtin_table(version)`", "never \"a path of any known version\"", "`hive.js`", "ADR 0018",
                     "`com.google.antigravity.*`", "Guard rule 20 covers 1.5.7 by itself", "Going back to v0.25.4", "`docs/evidence/claude-code-2.1.323-chat.md`", "`docs/evidence/agy-1.5.7-chat.md`"):
            self.assertIn(word, self.model, word)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.25.5"), [])
        self.assertNotIn("\n## ", self.security[self.security.index("## New versions of Claude Code and AGY (v0.25.5)") + 5:], "v0.25.5's is the last section")
        self.assertLess(self.security.index("## Display-only version cache (v0.25.4)"), self.security.index("## New versions of Claude Code and AGY (v0.25.5)"))

    def test_the_older_statements_about_the_tables_name_the_new_versions(self):
        security = flat(self.security)
        self.assertIn("For 2.1.318, 2.1.319, 2.1.322 and 2.1.323 (the same list)", security)
        self.assertIn("(`1.5.3`, `1.5.6` and `1.5.7`)", security)
        reference = flat(raw("docs", "REFERENCE.zh-TW.md"))
        self.assertIn("2.1.318、2.1.319、2.1.322 與 2.1.323 另外把", reference)
        self.assertIn("認得 1.5.3、1.5.6 與 1.5.7", reference)
        self.assertIn("目前 1.5.3、1.5.6 與 1.5.7", flat(raw("GLOSSARY.md")))

    def test_the_guard_rule_and_the_test_files_exist(self):
        text = (ROOT / "tests" / "test_autonomy_guard.py").read_text(encoding="utf-8")
        for rule in "abc":
            self.assertIn(f"     24{rule}  ", text, rule)
        self.assertIn("  24. (P60, v0.25.5)", text)
        self.assertTrue((ROOT / "docs" / "evidence" / "claude-code-2.1.323-chat.md").is_file())
        self.assertTrue((ROOT / "docs" / "evidence" / "agy-1.5.7-chat.md").is_file())


if __name__ == "__main__":
    unittest.main()
