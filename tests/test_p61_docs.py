"""P61 documents (v0.25.6): the evidence file says how AGY 1.5.8 was looked at, what the tables say and what was not shown (the new administrator controls included), the changelog and the
security model say what the release changed and what it did not, the words they quote are the code's, the version is 0.25.6 (v0.25.5 is the section just behind v0.25.6's), and nothing they
added names a person or a machine.

Seams: the text of the documents (whitespace flattened) and the public tables of the protocol modules."""
from __future__ import annotations

import unittest
from pathlib import Path

import vbear
from tests.test_p47_docs import flat, problems, raw, section
from vbear import admin_policy as ap
from vbear.runtime import agy_chat_env as env
from vbear.runtime import agy_chat_protocol as acp
from vbear.runtime import cli_versions

ROOT = Path(__file__).resolve().parent.parent
SECTION = "## AGY 1.5.8 (v0.25.6)"


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "evidence", "agy-1.5.8-chat.md")
        cls.agy = flat(cls.raw)

    def test_it_says_what_was_looked_at_how_and_what_was_not_shown(self):
        for word in ("2026-11-13", "b127126993e1c5b7e0b1ef80fa9bbe6955ddb85a5d76a3310b6096acc7eb000a", "235,205,648", "`1.5.8`", "byte for byte", "`Authentication required`",
                     "No prompt was sent", "64 paths: 42 files and 22 folders", "40 files have the same SHA-256", "2 files differ", "`.checksum`", "`skills/mcp-app-development/SKILL.md`",
                     "Nothing was added, nothing disappeared, no mode changed, no new folder appeared", "belongs to the version about to start",
                     "evidence for the tables, not a verification", "boundary_check --mode agy-chat", "Not shown, on purpose"):
            self.assertIn(word, self.agy, word)

    def test_it_reads_the_new_administrator_controls_and_says_what_stays_open(self):
        for word in ("`authControls`", "`disableConsumerLogin`", "`wifProvider`", "`gcpProjectId`", "`gcpLocation`", "`licenseType`", "`applyPermissionPresetCeiling`",
                     "`FetchAdminControls`", "`AdminSettings`", "18", "26", "`MDM`", "no new file path, no new managed-preferences domain and no new `ANTIGRAVITY_*` variable",
                     "whatever it holds", "needs no new entry", "not a place on this Mac's disk", "Not verified", "`com.google.antigravity.companion`", "Open point",
                     "still not added", "`GetMcpAllowlist`", "`IsMcpEnabled`"):
            self.assertIn(word, self.agy, word)

    def test_the_changed_skill_file_is_read_against_the_places_vbear_refuses(self):
        for word in ("`config/plugins`", "`home_forbidden`", "`config/mcp_config.json`", "`${PLUGIN_ROOT}`", "`${PLUGIN_DATA}`", "already refused or never created"):
            self.assertIn(word, self.agy, word)

    def test_nothing_in_it_names_a_person_or_a_machine(self):
        self.assertEqual(problems(self.agy, "agy-1.5.8-chat.md"), [])

    def test_it_pastes_no_content_of_a_program(self):
        """Only names, hashes and counts: no line of a built-in file and no code of the AGY binary."""
        for marker in ("function(", "=>{", "import{", "```", "---\nname:"):
            self.assertNotIn(marker, self.agy, marker)

    def test_the_hashes_of_the_evidence_are_the_tables(self):
        self.assertIn("b127126993e1c5b7e0b1ef80fa9bbe6955ddb85a5d76a3310b6096acc7eb000a", self.raw)
        new, old = acp.VERSIONS["1.5.8"], acp.VERSIONS["1.5.7"]
        self.assertEqual((len(new.builtin_sha256), len(new.builtin_paths), len(env.builtin_table("1.5.8").dirs)), (42, 64, 22))
        self.assertEqual(sum(1 for (p, h), (q, g) in zip(new.builtin_sha256, old.builtin_sha256) if h == g), 40)
        self.assertEqual(sorted(p for (p, h), (q, g) in zip(new.builtin_sha256, old.builtin_sha256) if h != g), [".checksum", "skills/mcp-app-development/SKILL.md"])


class TablesTests(unittest.TestCase):
    def test_1_5_8_is_known_has_the_sources_of_1_5_7_and_is_in_no_verified_list(self):
        self.assertIn("1.5.8", acp.VERSIONS)
        self.assertEqual(ap.AGY_SOURCES["1.5.8"], ap.AGY_SOURCES["1.5.7"])
        self.assertEqual(ap.AGY_SOURCES["1.5.8"], ap.AGY_SOURCES["1.5.6"])
        self.assertNotIn("1.5.8", cli_versions.AGY_CHAT_VERIFIED_VERSIONS)
        self.assertEqual(env.NEWEST_VERSION, "1.5.8")
        self.assertEqual(env.KNOWN_VERSIONS, ("1.5.3", "1.5.6", "1.5.7", "1.5.8"))
        self.assertTrue((ROOT / "docs" / "evidence" / "agy-1.5.8-chat.md").is_file())


class ChangelogAndModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.25.6", "## v0.25.5"))
        cls.security = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(cls.security[cls.security.index(SECTION):])

    def test_the_release_is_first_and_the_version_is_the_release(self):
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.25.6 — VBear knows AGY 1.5.8\n"), self.changelog[:70])
        self.assertLess(self.changelog.index("## v0.25.6"), self.changelog.index("## v0.25.5"))
        self.assertEqual(vbear.__version__, "0.25.6")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.25.6"), [])

    def test_the_changelog_says_what_was_added_what_was_not_seen_and_what_is_still_to_do(self):
        for word in ("1.5.8", "you still press 「聊天安全檢查」 once on your own Mac for 1.5.8", "a pass for 1.5.7 does not count for it", "byte for byte 1.5.7's",
                     "the same 64 paths and 42 files", "40 are identical", "`.checksum`", "`skills/mcp-app-development/SKILL.md`", "ADR 0018, unchanged",
                     "`authControls`", "a switch for web fetching", "a switch for remote control", "a ceiling on the permission preset", "whatever it holds",
                     "not a file on your Mac", "the strings cannot prove the list of places complete", "`com.google.antigravity.*`",
                     "No guard rule was changed or loosened", "rule 20 now covers 1.5.8", "`tests/test_p61_docs.py`", "`docs/evidence/agy-1.5.8-chat.md`", "`web/app.js` did not change",
                     "**Money.**", "What was not seen, and known limits", "again does not know it until a new release", "v0.26.0", "Going back to v0.25.5", "Nothing to convert"):
            self.assertIn(word, self.first, word)

    def test_the_security_model_names_the_boundary_it_touched_and_the_residual_risks(self):
        for word in ("`vbear/runtime/agy_chat_protocol.py`", "`vbear/admin_policy.py`", "`vbear/runtime/agy_chat_env.py` did not change", "never one that is trusted",
                     "a pass of 1.5.7 does not count for 1.5.8", "64 paths and 42 files", "40 files have the same bytes", "`skills/mcp-app-development/SKILL.md`",
                     "`AGY_SOURCES[\"1.5.8\"]` is 1.5.7's list", "`authControls`", "whatever it holds", "never reads its content", "`com.google.antigravity.*`",
                     "Guard rule 20 covers 1.5.8 by itself", "the rule itself was not changed", "Residual risks", "The controls fetched from the server", "ADR 0018",
                     "Going back to v0.25.5", "`docs/evidence/agy-1.5.8-chat.md`"):
            self.assertIn(word, self.model, word)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.25.6"), [])
        self.assertNotIn("\n## ", self.security[self.security.index(SECTION) + 5:], "v0.25.6's is the last section")
        self.assertLess(self.security.index("## New versions of Claude Code and AGY (v0.25.5)"), self.security.index(SECTION))

    def test_the_older_statements_about_the_tables_name_the_new_version(self):
        self.assertIn("(`1.5.3`, `1.5.6`, `1.5.7` and `1.5.8`)", flat(self.security))
        self.assertIn("認得 1.5.3、1.5.6、1.5.7 與 1.5.8", flat(raw("docs", "REFERENCE.zh-TW.md")))
        self.assertIn("目前 1.5.3、1.5.6、1.5.7 與 1.5.8", flat(raw("GLOSSARY.md")))
        adr = flat(raw("docs", "adr", "0018-agy-version-tables.md"))
        self.assertIn("## 補記（v0.25.6：認得 AGY 1.5.8）", adr)
        self.assertIn("路徑表就是 1.5.7 的", adr)


if __name__ == "__main__":
    unittest.main()
