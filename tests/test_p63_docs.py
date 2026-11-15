"""P63 documents (v0.26.1): the evidence file says how AGY 1.5.9 was looked at, what the tables say and, above all, what was **not** compared (no copy of 1.5.8 was kept), the changelog and the
security model say what the release changed and what it did not, the words they quote are the code's, the version is 0.26.1 (v0.26.0 is the section just behind v0.26.1's), and nothing they
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
SECTION = "## AGY 1.5.9 (v0.26.1)"


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "evidence", "agy-1.5.9-chat.md")
        cls.agy = flat(cls.raw)

    def test_it_says_what_was_looked_at_how_and_what_was_not_shown(self):
        for word in ("2026-11-15", "fad3628ad91fe8613a72f074a1c5fde7cd816517788a5b9be96703f7d256741a", "223,424,816", "`1.5.9`", "`Authentication required`",
                     "No prompt was sent", "66 paths: 43 files and 23 folders", "37 files have the same SHA-256", "5 files differ", "1 file is new", "`skills/swarm_pane/SKILL.md`",
                     "`.checksum`", "`.manifest`", "`plugins/swarm/sidecars/swarm_board/app.js`", "`plugins/swarm/sidecars/swarm_board/hive.js`", "`skills/native_swarm/SKILL.md`",
                     "belongs to the version about to start", "evidence for the tables, not a verification", "boundary_check --mode agy-chat", "Not shown, on purpose"):
            self.assertIn(word, self.agy, word)

    def test_it_says_what_was_not_compared_instead_of_calling_it_the_same(self):
        for word in ("Not compared byte for byte with 1.5.8's helps", "No copy of 1.5.8's", "`_meta.antigravity`", "cannot be said", "about 12 MB smaller", "was not looked into",
                     "no difference between them was seen", "not an analysis, and not a comparison with 1.5.8's scripts", "03f89b56579e2bf4a01bb6041369a93c2366c9ca97d2d4b5529458518d472250"):
            self.assertIn(word, self.agy, word)
        self.assertNotIn("byte for byte the same as 1.5.8", self.agy)

    def test_it_reads_the_administrator_places_and_says_what_stays_open(self):
        for word in ("`models.list`", "`FetchAdminControls`", "`authControls`", "No new file path, no new managed-preferences domain and no new administrator place", "whatever it holds",
                     "not a place on this Mac's disk", "Not verified", "`com.google.antigravity.companion`", "still not added", "`BypassSandbox`", "No rule was loosened because of any count"):
            self.assertIn(word, self.agy, word)

    def test_nothing_in_it_names_a_person_or_a_machine(self):
        self.assertEqual(problems(self.agy, "agy-1.5.9-chat.md"), [])

    def test_it_pastes_no_content_of_a_program(self):
        """Only names, hashes and counts: no line of a built-in file and no code of the AGY binary."""
        for marker in ("function(", "=>{", "import{", "```", "---\nname:", "async function"):
            self.assertNotIn(marker, self.agy, marker)

    def test_the_hashes_of_the_evidence_are_the_tables(self):
        self.assertIn("fad3628ad91fe8613a72f074a1c5fde7cd816517788a5b9be96703f7d256741a", self.raw)
        new, old = acp.VERSIONS["1.5.9"], acp.VERSIONS["1.5.8"]
        self.assertEqual((len(new.builtin_sha256), len(new.builtin_paths), len(env.builtin_table("1.5.9").dirs)), (43, 66, 23))
        newer, older = dict(new.builtin_sha256), dict(old.builtin_sha256)
        self.assertEqual(sum(1 for p in older if newer[p] == older[p]), 37)
        self.assertEqual(sorted(p for p in older if newer[p] != older[p]),
                         [".checksum", ".manifest", "plugins/swarm/sidecars/swarm_board/app.js", "plugins/swarm/sidecars/swarm_board/hive.js", "skills/native_swarm/SKILL.md"])
        self.assertEqual(sorted(set(newer) - set(older)), ["skills/swarm_pane/SKILL.md"])
        self.assertIn(older[".manifest"], self.raw, "the 1.5.8 manifest hash the new manifest minus its one line was matched to")


class TablesTests(unittest.TestCase):
    def test_1_5_9_is_known_has_the_sources_of_1_5_8_and_is_in_no_verified_list(self):
        self.assertIn("1.5.9", acp.VERSIONS)
        self.assertEqual(ap.AGY_SOURCES["1.5.9"], ap.AGY_SOURCES["1.5.8"])
        self.assertEqual(ap.AGY_SOURCES["1.5.9"], ap.AGY_SOURCES["1.5.6"])
        self.assertIsNot(ap.AGY_SOURCES["1.5.9"], ap.AGY_SOURCES["1.5.8"])
        self.assertNotIn("1.5.9", cli_versions.AGY_CHAT_VERIFIED_VERSIONS)
        self.assertEqual(env.NEWEST_VERSION, "1.5.9")
        self.assertEqual(env.KNOWN_VERSIONS, ("1.5.3", "1.5.6", "1.5.7", "1.5.8", "1.5.9"))
        self.assertTrue((ROOT / "docs" / "evidence" / "agy-1.5.9-chat.md").is_file())


class ChangelogAndModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changelog = raw("CHANGELOG.md")
        cls.first = flat(section(cls.changelog, "## v0.26.1", "## v0.26.0"))
        cls.security = raw("docs", "SECURITY-MODEL.md")
        cls.model = flat(cls.security[cls.security.index(SECTION):])

    def test_the_release_is_first_and_the_version_is_the_release(self):
        self.assertTrue(self.changelog.startswith("# Changelog\n\n## v0.26.1 — VBear knows AGY 1.5.9\n"), self.changelog[:70])
        self.assertLess(self.changelog.index("## v0.26.1"), self.changelog.index("## v0.26.0"))
        self.assertEqual(vbear.__version__, "0.26.1")
        self.assertNotIn("Unreleased", self.first)
        self.assertEqual(problems(self.first, "CHANGELOG v0.26.1"), [])

    def test_the_changelog_says_what_was_added_what_was_not_compared_and_that_the_kept_copy_needs_one_press(self):
        for word in ("1.5.9", "you press 「聊天安全檢查」 once on your own Mac for 1.5.9", "a pass for 1.5.8 does not count for it", "the kept copy only starts to protect you after you press it once",
                     "`skills/swarm_pane`", "66 paths and 43 files", "37 are identical", "five changed", "`app.js` and `hive.js`", "exact fingerprint", "does **not** say", "may or may not be new",
                     "about 12 MB smaller", "`models.list`", "whatever it holds", "No guard rule was changed or loosened", "rule 20 now covers 1.5.9", "`tests/test_p63_docs.py`",
                     "`docs/evidence/agy-1.5.9-chat.md`", "**Money.**", "What was not seen, and known limits", "Going back to v0.26.0", "Nothing to convert"):
            self.assertIn(word, self.first, word)

    def test_the_security_model_names_the_boundary_it_touched_and_the_residual_risks(self):
        for word in ("`vbear/runtime/agy_chat_protocol.py`", "`vbear/admin_policy.py`", "`vbear/runtime/agy_chat_env.py` and the kept-copy code of v0.26.0 did not change", "never one that is trusted",
                     "a pass of 1.5.8 does not count for 1.5.9", "66 paths and 43 files", "37 files have the same bytes", "`skills/swarm_pane`", "no byte-for-byte comparison",
                     "`AGY_SOURCES[\"1.5.9\"]` is 1.5.8's list", "`models.list`", "whatever it holds", "Guard rule 20 covers 1.5.9 by itself", "the rule itself was not changed", "Residual risks",
                     "The controls fetched from the server", "ADR 0018", "Going back to v0.26.0", "`docs/evidence/agy-1.5.9-chat.md`", "The kept copy of v0.26.0 is made by that very press"):
            self.assertIn(word, self.model, word)
        self.assertEqual(problems(self.model, "SECURITY-MODEL v0.26.1"), [])
        self.assertNotIn("\n## ", self.security[self.security.index(SECTION) + 5:], "v0.26.1's is the last section")
        self.assertLess(self.security.index("## Keeping the verified AGY (v0.26.0)"), self.security.index(SECTION))

    def test_the_older_statements_about_the_tables_name_the_new_version(self):
        self.assertIn("(`1.5.3`, `1.5.6`, `1.5.7`, `1.5.8` and `1.5.9`)", flat(self.security))
        self.assertIn("認得 1.5.3、1.5.6、1.5.7、1.5.8 與 1.5.9", flat(raw("docs", "REFERENCE.zh-TW.md")))
        self.assertIn("目前 1.5.3、1.5.6、1.5.7、1.5.8 與 1.5.9", flat(raw("GLOSSARY.md")))
        adr = flat(raw("docs", "adr", "0018-agy-version-tables.md"))
        self.assertIn("## 補記（v0.26.1：認得 AGY 1.5.9）", adr)
        self.assertIn("路徑表不是 1.5.8 的", adr)


if __name__ == "__main__":
    unittest.main()
