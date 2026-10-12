"""The armor's meaning is a pure function (agent_launch.armor_items), and the preview's seven labels are the same
text they were before it was pulled out of ``derive_labels``.

tests/armor_labels_golden.json was produced by the code as it was before the extraction (see tests/armor_cases.py),
for Claude Code verified / unverified / not known, the network shape verified or not, the Codex evidence record
complete or missing, a work directory or none, and a launch that was not prepared.
"""

import builtins
import json
import unittest
from pathlib import Path
from unittest import mock

from vbear import agent_launch as al
from tests import armor_cases

GOLDEN = Path(__file__).resolve().parent / "armor_labels_golden.json"


class VerbatimTests(unittest.TestCase):
    def test_every_case_is_the_text_it_was_before(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual([g["case"] for g in golden], armor_cases.cases())
        self.assertGreater(len(golden), 50)
        for g in golden:
            with self.subTest(case=g["case"]):
                self.assertEqual(armor_cases.render(g["case"]), g["labels"])      # the JSON text, key order included

    def test_the_cases_cover_what_the_design_names(self):
        golden = [json.loads(g["labels"]) for g in json.loads(GOLDEN.read_text(encoding="utf-8"))]
        levels = {tuple(v["level"] for v in d.values()) for d in golden}
        self.assertIn(("僅意圖", "部分強制", "僅意圖", "未限制", "不授予", al.ENFORCED, al.ENFORCED), levels)   # verified
        self.assertTrue(any(l[1] == al.UNVERIFIED for l in levels))                                     # unverified
        self.assertTrue(any(l[5] == al.UNKNOWN and l[1] == "部分強制" for l in levels))          # network not verified
        self.assertTrue(any(l[1] == al.ENFORCED and l[3] == "未限制" for l in levels))            # Codex proven; .git
        self.assertTrue(any(l[1] == al.UNKNOWN and l[3] == "未限制" for l in levels))            # Codex evidence missing
        self.assertTrue(any(set(l) == {al.UNKNOWN} for l in levels))                              # not prepared


class PureTests(unittest.TestCase):
    def test_four_values_in_and_no_io(self):
        # Nothing here may touch a file, a process or the clock.
        with mock.patch.object(builtins, "open", side_effect=AssertionError("file read")), \
             mock.patch("pathlib.Path.read_text", side_effect=AssertionError("file read")), \
             mock.patch("pathlib.Path.stat", side_effect=AssertionError("stat")), \
             mock.patch("subprocess.run", side_effect=AssertionError("process")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("process")), \
             mock.patch.object(al, "_codex_evidence_reference", side_effect=AssertionError("evidence read")), \
             mock.patch.object(al.cli_versions, "local_verified_versions", side_effect=AssertionError("versions")):
            for tool in ("claude", "codex"):
                for verified in (True, False, None):
                    for net in (True, False):
                        for codex_ok in (True, False):
                            items = al.armor_items(tool, verified, net, codex_ok)
                            self.assertEqual(tuple(items), al.ARMOR_NAMES)

    def test_each_item_has_the_semantic_fields_only(self):
        for tool, verified in (("claude", True), ("claude", False), ("claude", None), ("codex", None)):
            for name, it in al.armor_items(tool, verified, True, True).items():
                with self.subTest(tool=tool, verified=verified, name=name):
                    self.assertEqual(set(it), {"level", "note", "group", "scope", "evidence", "unknown_reason"})
                    self.assertIn(it["group"], {g for g, _ in al.ARMOR_GROUPS})
                    self.assertTrue(it["note"])
                    # it names the work directory, a version or an evidence file, it never holds one
                    self.assertTrue(all(isinstance(e, str) and "/" not in e for e in it["evidence"]))
                    self.assertTrue(it["scope"] is None or it["scope"] in {
                        al.SCOPE_WRITE, al.SCOPE_WORKDIR, al.SCOPE_CODEX_WRITE, al.SCOPE_CODEX_GIT})

    def test_groups_follow_the_level_and_never_flatter_it(self):
        group = {al.ENFORCED: "blocked", al.PARTIAL: "partial", al.NOT_GRANTED: "not_granted",
                 al.INTENT: "not_blocked", al.UNRESTRICTED: "not_blocked",
                 al.UNVERIFIED: "unproven", al.UNKNOWN: "unproven"}
        seen = set()
        for tool, verified in (("claude", True), ("claude", False), ("claude", None), ("codex", None)):
            for net in (True, False):
                for ok in (True, False):
                    for it in al.armor_items(tool, verified, net, ok).values():
                        self.assertEqual(it["group"], group[it["level"]])
                        seen.add(it["level"])
        self.assertEqual(seen, set(group))
        # Only a proven, verified setting is ever in the group named "blocked".
        for it in al.armor_items("claude", None, True, True).values():
            self.assertNotEqual(it["group"], "blocked")
        for it in al.armor_items("claude", False, True, True).values():
            self.assertNotEqual(it["group"], "blocked")
        for it in al.armor_items("codex", None, True, False).values():
            self.assertNotEqual(it["group"], "blocked")

    def test_an_unknown_claude_version_claims_no_protection(self):
        items = al.armor_items("claude", None, True, True)
        self.assertEqual(items["Write"]["level"], al.UNKNOWN)
        self.assertEqual(items["Network"]["level"], al.UNKNOWN)
        self.assertEqual(items["Filesystem"]["level"], al.UNKNOWN)
        self.assertEqual(items["Commit"]["level"], al.UNRESTRICTED)       # a weakness is stated whatever the version


class PageTableTests(unittest.TestCase):
    def test_the_pages_group_table_is_the_servers(self):
        """web/app.js frames a preview's labels in five groups from its own table (the preview carries no group);
        the table must be the one agent_launch defines, so a new level cannot land in the wrong group."""
        import re
        source = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
        block = source[source.index("const ARMOR_GROUPS_UI = ["):]
        block = block[:block.index("];")]
        rows = re.findall(r'\{ id: "(\w+)", label: "([^"]+)", levels: \[([^\]]*)\] \}', block)
        page = [(i, label, re.findall(r'"([^"]+)"', levels)) for i, label, levels in rows]
        server = [(g, label, list(al.ARMOR_GROUP_LEVELS[g])) for g, label in al.ARMOR_GROUPS]
        self.assertEqual(page, server)
        # every level the pure function can emit is in one of the groups
        known = {lv for _, _, levels in server for lv in levels}
        emitted = set()
        for tool, verified in (("claude", True), ("claude", False), ("claude", None), ("codex", None)):
            for net in (True, False):
                for ok in (True, False):
                    emitted |= {it["level"] for it in al.armor_items(tool, verified, net, ok).values()}
        self.assertTrue(emitted <= known, emitted - known)


if __name__ == "__main__":
    unittest.main()
