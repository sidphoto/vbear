"""P32-4: what the wizard's profession picker is given. The catalog's professions carry the author's description (cut),
a guess at the position (derived, with the keyword), the skills the template declares, the model it names and whether
it can be used; /api/roles carries the same guess. Nothing here reads a real home, runs a CLI or sends anything.

Run: python3 -m unittest tests.test_p32_professions -v
"""

from __future__ import annotations

import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_agent_profiles_api import _fresh_console, _request  # noqa: F401  (also pins the fake HOME)

from vbear.scan import claude as claude_scan  # noqa: E402


def sourced(value, origin="author", detail="front matter"):
    return {"value": value, "origin": origin, "detail": detail}


def role(**changes):
    data = {"role_id": "r-1", "name": "Legal Counsel", "tool": "codex", "kind": "subagent",
            "path": "/do-not-send/agent.toml", "description": sourced("Finds new trends in the market."),
            "capabilities": sourced("private capabilities"), "model": sourced("gpt-fake-1"),
            "skill_link_ids": [], "skill_link_basis": "undeclared", "warnings": []}
    data.update(changes)
    return data


class CatalogProfessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.console, cls.httpd, cls.port = _fresh_console()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def professions(self, roles, path="/api/agent-builder/catalog"):
        self.console.store._static = {"skills": [], "roles": roles}
        self.console.store._static_stamp = None
        try:
            status, body = _request("GET", self.port, path)
        finally:
            self.console.store._static = None
        self.assertEqual(status, 200)
        return body

    def catalog(self, roles):
        return {p["role_id"]: p for p in self.professions(roles)["professions"]}

    def test_a_profession_carries_exactly_these_fields(self):
        got = self.catalog([role()])["r-1"]
        self.assertEqual(sorted(got), sorted([
            "role_id", "name", "tool", "kind", "skill_link_count", "skill_link_basis", "description", "department",
            "declared_skill_ids", "model_hint", "unavailable"]))
        self.assertNotIn("do-not-send", json.dumps(got), "no path")
        self.assertNotIn("private capabilities", json.dumps(got))

    def test_description_is_the_authors_first_300_characters_with_its_origin_and_nothing_otherwise(self):
        got = self.catalog([
            role(role_id="a", description=sourced("word " * 200)),
            role(role_id="b", description=sourced("VBear's own", origin="derived")),
            role(role_id="c", description=sourced(None, origin="missing")),
            role(role_id="d", description=sourced("   ")),
            role(role_id="e", description="not an object")])
        self.assertEqual(got["a"]["description"], {"value": ("word " * 200)[:300], "origin": "author"})
        for key in "bcde":
            self.assertIsNone(got[key]["description"], key)

    def test_department_is_the_guess_with_its_keyword_and_null_when_there_is_none(self):
        got = self.catalog([role(),
                            role(role_id="z", name="Zebra", description=sourced("Plain words.")),
                            role(role_id="y", name="Zebra", description=sourced("Audits the code."))])
        self.assertEqual(got["r-1"]["department"], {"id": "legal", "keyword": "legal", "origin": "derived"})
        self.assertIsNone(got["z"]["department"])
        self.assertEqual(got["y"]["department"]["id"], "reviewer", "the author's first sentence, when the name says nothing")

    def test_a_description_that_is_not_the_authors_is_not_read_for_the_guess(self):
        got = self.catalog([role(role_id="z", name="Zebra", description=sourced("Audits the code.", origin="derived"))])
        self.assertIsNone(got["z"]["department"])

    def test_declared_skills_only_when_the_template_declares_them_at_most_50(self):
        ids = [f"s-{i}" for i in range(80)]
        got = self.catalog([
            role(role_id="a", skill_link_ids=ids, skill_link_basis="declared"),
            role(role_id="b", skill_link_ids=["s-1"], skill_link_basis="load_scope"),
            role(role_id="c", skill_link_ids=["s-1"], skill_link_basis="undeclared"),
            role(role_id="d", skill_link_ids=["s-1", 7, None, ""], skill_link_basis="declared")])
        self.assertEqual(got["a"]["declared_skill_ids"], ids[:50])
        self.assertEqual(got["b"]["declared_skill_ids"], [])
        self.assertEqual(got["c"]["declared_skill_ids"], [])
        self.assertEqual(got["d"]["declared_skill_ids"], ["s-1"])
        self.assertEqual(got["a"]["skill_link_count"], 80, "the count is still the whole count")

    def test_model_hint_is_what_the_author_wrote_unless_it_is_inherit(self):
        got = self.catalog([
            role(role_id="a", model=sourced("opus")),
            role(role_id="b", model=sourced("inherit")),
            role(role_id="c", model=sourced("Inherit ")),
            role(role_id="d", model=sourced("claude-from-config", origin="derived")),
            role(role_id="e", model=sourced(None, origin="missing")),
            role(role_id="f", model=sourced("x" * 500)),
            role(role_id="g", model=sourced("gpt\x00-fake\x1b[31m\n-2")),
            role(role_id="h", model=7)])
        self.assertEqual(got["a"]["model_hint"], "opus")
        for key in "bcde":
            self.assertIsNone(got[key]["model_hint"], key)
        self.assertEqual(got["f"]["model_hint"], "x" * 200)
        self.assertEqual(got["g"]["model_hint"], "gpt-fake[31m-2")
        self.assertIsNone(got["h"]["model_hint"])

    def test_unavailable_says_so_for_a_plugin_that_is_switched_off(self):
        off = claude_scan.plugin_disabled_warning("fake-plugin@fake-market")
        got = self.catalog([
            role(role_id="a", warnings=[off]),
            role(role_id="b", warnings=["外掛 x@y 的啟用狀態未記錄"]),
            role(role_id="c", warnings=[]),
            role(role_id="d", warnings=["some other warning", off])])
        self.assertEqual(got["a"]["unavailable"], "外掛已停用")
        self.assertIsNone(got["b"]["unavailable"], "not recorded is not switched off")
        self.assertIsNone(got["c"]["unavailable"])
        self.assertEqual(got["d"]["unavailable"], "外掛已停用")

    def test_roles_endpoint_carries_the_same_guess(self):
        body = self.professions([role(), role(role_id="z", name="Zebra", description=sourced("Plain words."))], "/api/roles")
        by_id = {r["role_id"]: r for r in body["roles"]}
        self.assertEqual(by_id["r-1"]["department"], {"id": "legal", "keyword": "legal", "origin": "derived"})
        self.assertIsNone(by_id["z"]["department"])

    def test_the_catalog_still_lists_every_role_the_scan_found(self):
        body = self.professions([role(), role(role_id="cli-codex", kind="cli", name="Codex 主代理",
                                              description=sourced("VBear's own", origin="derived"))])
        self.assertEqual([p["role_id"] for p in body["professions"]], ["r-1", "cli-codex"],
                         "the page leaves out the tool itself; the catalog is not the one to hide it")


class PluginDisabledWarningTests(unittest.TestCase):
    def test_the_warning_is_one_sentence_made_in_one_place(self):
        text = claude_scan.plugin_disabled_warning("p@m")
        self.assertEqual(text, "外掛 p@m 在 settings.json 中停用，此角色目前不可用")
        self.assertTrue(claude_scan.is_plugin_disabled_warning(text))
        for other in ("外掛 p@m 的啟用狀態未記錄", "", None, 5, "在 settings.json 中停用，此角色目前不可用"):
            self.assertFalse(claude_scan.is_plugin_disabled_warning(other), repr(other))

    def test_the_scan_of_a_switched_off_plugin_uses_that_sentence(self):
        with tempfile.TemporaryDirectory(prefix="vbear-p32-plugin-") as tmp:
            install = Path(tmp) / "fake-plugin"
            (install / ".claude-plugin").mkdir(parents=True)
            (install / "agents").mkdir()
            (install / ".claude-plugin" / "plugin.json").write_text(json.dumps({"agents": ["agents/helper.md"]}))
            (install / "agents" / "helper.md").write_text("---\nname: helper\ndescription: Helps out.\n---\nBody.\n")
            facts = {"installed": {str(install): {"plugin": "fake-plugin@fake-market"}},
                     "enabled": {"fake-plugin@fake-market": False}}
            roles = claude_scan.scan_plugin_agents(facts)
        self.assertEqual(len(roles), 1)
        self.assertTrue(any(claude_scan.is_plugin_disabled_warning(w) for w in roles[0].warnings), roles[0].warnings)
        self.assertIn(claude_scan.plugin_disabled_warning("fake-plugin@fake-market"), roles[0].warnings)


if __name__ == "__main__":
    unittest.main()
