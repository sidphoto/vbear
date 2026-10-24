"""P22: which skills Antigravity (AGY) reads, judged from files only (VBear never runs agy).

AGY reads a project's .agents/skills, ~/.gemini/antigravity-cli/skills, and every folder listed in
~/.gemini/config/skills.json (direct children only, or the include_only list). These tests build a synthetic
HOME with a fake skills.json and fake skill folders, and lock what the index marks and what it refuses.

Run: python3 -m unittest tests.test_p22_agy_skills -v
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import config as cfg  # noqa: E402
from vbear import index, loadout  # noqa: E402
from vbear.scan import agy  # noqa: E402


def write_skill(folder: Path, name: str, description: str = "A made-up skill for tests.") -> Path:
    d = folder / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nBody.\n",
                                encoding="utf-8")
    return d / "SKILL.md"


class AgyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-p22-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve() / "home"
        self.home.mkdir()
        env = unittest.mock.patch.dict(os.environ, {"HOME": str(self.home), "VBEAR_HOME": str(self.home / ".vbear"),
                                                    "VBEAR_RUNTIME_AUTOSTART": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.outside = Path(self.tmp.name).resolve() / "outside"
        self.outside.mkdir()

    # --- fixtures -----------------------------------------------------------------------------------------
    def config_file(self, data=None, raw: bytes | None = None) -> Path:
        path = self.home / ".gemini" / "config" / "skills.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if raw is not None else json.dumps(data).encode("utf-8"))
        return path

    def entries(self, *items):
        return self.config_file({"entries": list(items)})

    def build(self, project_roots=()):
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        conf["project_roots"] = [str(p) for p in project_roots]
        conf["usage_enabled"] = False
        return index.build_static(conf)

    def by_name(self, data, name):
        return [s for s in data["skills"] if s["name"] == name]

    def agy_rows(self, data):
        return [r for r in data["sources"] if r["tool"] == "agy"]

    def config_row(self, data):
        rows = [r for r in data["sources"] if r.get("kind") == "config" and r["tool"] == "agy"]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]


class ListedFolderTests(AgyCase):
    def test_a_listed_folder_that_is_already_a_source_is_marked_not_duplicated(self):
        write_skill(self.home / ".codex" / "skills", "alpha")
        write_skill(self.home / ".codex" / "skills", "beta")
        self.entries({"path": str(self.home / ".codex" / "skills")})
        data = self.build()
        for name in ("alpha", "beta"):
            found = self.by_name(data, name)
            self.assertEqual(len(found), 1, f"{name} must not get a second record")
            self.assertEqual(found[0]["tool"], "codex")
            self.assertIn("agy", found[0]["read_by"])
            self.assertIn("skills.json", found[0]["read_by_evidence"]["agy"])
        self.assertEqual(self.agy_rows(data)[0]["kind"], "config", "no new skills source was made")
        self.assertEqual([r for r in self.agy_rows(data) if r["kind"] == "skills"], [])

    def test_a_tilde_path_is_accepted(self):
        write_skill(self.home / ".codex" / "skills", "alpha")
        self.entries({"path": "~/.codex/skills"})
        self.assertIn("agy", self.by_name(self.build(), "alpha")[0]["read_by"])

    def test_only_direct_children_are_read_so_a_nested_skill_is_not_marked(self):
        write_skill(self.home / ".codex" / "skills", "alpha")
        write_skill(self.home / ".codex" / "skills" / "group", "nested")
        self.entries({"path": "~/.codex/skills"})
        data = self.build()
        self.assertIn("agy", self.by_name(data, "alpha")[0]["read_by"])
        self.assertEqual(self.by_name(data, "nested")[0]["read_by"], [])

    def test_a_new_folder_makes_an_agy_source_with_agy_records(self):
        write_skill(self.home / "my-agy-skills", "fresh")
        self.entries({"path": "~/my-agy-skills"})
        data = self.build()
        rec = self.by_name(data, "fresh")[0]
        self.assertEqual(rec["tool"], "agy")
        self.assertEqual(rec["read_by"], ["agy"])
        self.assertEqual(Path(rec["path"]).parent.parent, self.home / "my-agy-skills")
        rows = [r for r in self.agy_rows(data) if r["kind"] == "skills"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["exists"])
        self.assertEqual(rows[0]["count"], 1)
        self.assertTrue(rows[0]["discovered"])
        self.assertEqual(rec["skill_id"], index.stable_id("agy", rec["path"]))

    def test_the_same_folder_listed_twice_gives_one_record(self):
        write_skill(self.home / "my-agy-skills", "fresh")
        self.entries({"path": "~/my-agy-skills"}, {"path": str(self.home / "my-agy-skills") + "/"})
        self.assertEqual(len(self.by_name(self.build(), "fresh")), 1)

    def test_include_only_marks_and_makes_only_the_listed_skills(self):
        write_skill(self.home / ".codex" / "skills", "alpha")
        write_skill(self.home / ".codex" / "skills", "beta")
        write_skill(self.home / "pack", "one")
        write_skill(self.home / "pack", "two")
        write_skill(self.home / "pack" / "group", "deep")
        self.entries({"path": "~/.codex/skills", "include_only": ["beta"]},
                     {"path": "~/pack", "include_only": ["two", "group/deep"]})
        data = self.build()
        self.assertEqual(self.by_name(data, "alpha")[0]["read_by"], [])
        self.assertIn("agy", self.by_name(data, "beta")[0]["read_by"])
        self.assertEqual(self.by_name(data, "one"), [])
        self.assertEqual(self.by_name(data, "two")[0]["tool"], "agy")
        self.assertEqual(self.by_name(data, "deep")[0]["tool"], "agy", "a nested skill is read when listed")

    def test_an_empty_include_only_reads_nothing(self):
        write_skill(self.home / "pack", "one")
        self.entries({"path": "~/pack", "include_only": []})
        self.assertEqual(self.by_name(self.build(), "one"), [])

    def test_a_bad_include_only_skips_the_entry_instead_of_widening_it(self):
        write_skill(self.home / "pack", "one")
        for bad in ("one", [1, 2], {"a": 1}, ["../x"], ["/abs"], [""], ["a\\b"]):
            with self.subTest(include_only=bad):
                self.entries({"path": "~/pack", "include_only": bad})
                data = self.build()
                self.assertEqual(self.by_name(data, "one"), [])
                self.assertTrue(self.config_row(data)["issues"], "the entry is reported")

    def test_global_agy_folder_is_scanned_without_any_skills_json(self):
        write_skill(self.home / ".gemini" / "antigravity-cli" / "skills", "globalone")
        write_skill(self.home / ".gemini" / "antigravity-cli" / "skills" / "grp", "nested")
        data = self.build()
        rec = self.by_name(data, "globalone")[0]
        self.assertEqual(rec["tool"], "agy")
        self.assertEqual(rec["read_by"], ["agy"])
        self.assertEqual(self.by_name(data, "nested"), [], "direct children only")
        rows = [r for r in self.agy_rows(data) if r["kind"] == "skills"]
        self.assertEqual([r["path"] for r in rows], ["~/.gemini/antigravity-cli/skills"])
        self.assertFalse([r for r in data["sources"] if r.get("kind") == "config"], "no skills.json, no config row")

    def test_global_folder_listed_in_skills_json_is_one_source(self):
        write_skill(self.home / ".gemini" / "antigravity-cli" / "skills", "globalone")
        self.entries({"path": "~/.gemini/antigravity-cli/skills"})
        data = self.build()
        self.assertEqual(len(self.by_name(data, "globalone")), 1)
        self.assertEqual(len([r for r in self.agy_rows(data) if r["kind"] == "skills"]), 1)


class DefaultsAreNotAgyTests(AgyCase):
    def test_the_shared_store_is_not_read_by_agy_unless_listed(self):
        write_skill(self.home / ".agents" / "skills", "shared-one")
        data = self.build()
        self.assertEqual(self.by_name(data, "shared-one")[0]["read_by"], [])
        self.entries({"path": "~/.agents/skills"})
        marked = self.by_name(self.build(), "shared-one")[0]
        self.assertEqual(marked["tool"], "shared")
        self.assertIn("agy", marked["read_by"])

    def test_claude_and_codex_skills_are_not_read_by_agy_by_default(self):
        write_skill(self.home / ".claude" / "skills", "cl")
        write_skill(self.home / ".codex" / "skills", "cx")
        data = self.build()
        self.assertEqual(self.by_name(data, "cl")[0]["read_by"], [])
        self.assertEqual(self.by_name(data, "cx")[0]["read_by"], [])

    def test_a_project_agents_skills_folder_is_read_by_agy_the_other_project_folders_are_not(self):
        proj = self.home / "projects" / "demo"
        write_skill(proj / ".agents" / "skills", "proj-agents")
        write_skill(proj / ".agents" / "skills" / "grp", "proj-nested")
        write_skill(proj / ".codex" / "skills", "proj-codex")
        write_skill(proj / ".claude" / "skills", "proj-claude")
        data = self.build(project_roots=[self.home / "projects"])
        agents = self.by_name(data, "proj-agents")[0]
        self.assertEqual(agents["tool"], "codex", "the record keeps the camp it had")
        self.assertEqual(agents["scope"], "project")
        self.assertIn("agy", agents["read_by"])
        self.assertIn(".agents/skills", agents["read_by_evidence"]["agy"])
        self.assertEqual(self.by_name(data, "proj-nested")[0]["read_by"], [])
        self.assertEqual(self.by_name(data, "proj-codex")[0]["read_by"], [])
        self.assertEqual(self.by_name(data, "proj-claude")[0]["read_by"], [])

    def test_the_old_dot_agent_folder_is_not_scanned(self):
        proj = self.home / "projects" / "demo"
        write_skill(proj / ".agent" / "skills", "legacy")
        self.assertEqual(self.by_name(self.build(project_roots=[self.home / "projects"]), "legacy"), [])

    def test_nothing_is_marked_when_there_is_no_agy_setup(self):
        write_skill(self.home / ".codex" / "skills", "cx")
        data = self.build()
        self.assertTrue(all(s["read_by"] == [] for s in data["skills"]))
        self.assertEqual(self.agy_rows(data), [])


PREFIX = "AGY 設定檔 skills.json："


class RefusedConfigTests(AgyCase):
    def assert_refused(self, data, note):
        row = self.config_row(data)
        self.assertTrue(row["issues"], note)
        for issue in row["issues"]:
            self.assertIsInstance(issue, str)
        self.assertEqual([i for i in data["problems"] if i.startswith(PREFIX)], [PREFIX + i for i in row["issues"]],
                         "also listed in problems, the same text with the row's name in front")
        self.assertEqual([s for s in data["skills"] if s["tool"] == "agy"], [], note)

    def test_broken_json_counts_as_no_file_and_is_reported(self):
        write_skill(self.home / ".codex" / "skills", "alpha")
        self.config_file(raw=b"{ not json")
        data = self.build()
        self.assert_refused(data, "bad json")
        self.assertEqual(self.by_name(data, "alpha")[0]["read_by"], [])

    def test_non_json_shapes_are_reported(self):
        for raw in (b"[]", b"null", b'{"entries": 5}', b'{"entries": {"a": 1}}', b"{}", b"\xff\xfe\x00",
                    b"[" * 5000 + b"]" * 5000):
            with self.subTest(raw=raw[:20]):
                self.config_file(raw=raw)
                data = self.build()
                row = self.config_row(data)
                if raw == b"{}":
                    self.assertEqual(row["count"], 0)  # no entries key: nothing listed, nothing to report
                else:
                    self.assertTrue(row["issues"])

    def test_an_oversized_file_is_not_parsed(self):
        write_skill(self.home / "pack", "one")
        body = json.dumps({"entries": [{"path": "~/pack"}], "pad": "x" * (agy.MAX_CONFIG_BYTES + 10)})
        self.config_file(raw=body.encode())
        data = self.build()
        self.assert_refused(data, "oversized")
        self.assertEqual(self.by_name(data, "one"), [])

    def test_too_many_entries_reads_only_the_first_ones_and_says_so(self):
        for i in range(3):
            write_skill(self.home / f"pack{i}", f"s{i}")
        items = [{"path": f"~/pack{i}"} for i in range(3)] + [{"path": "~/nothing%d" % i} for i in range(agy.MAX_ENTRIES)]
        self.entries(*items)
        data = self.build()
        self.assertEqual(len(self.by_name(data, "s0")), 1)
        self.assertTrue(any("上限" in i for i in self.config_row(data)["issues"]))

    def test_non_string_and_missing_paths_are_skipped_the_good_entry_still_counts(self):
        write_skill(self.home / "pack", "one")
        self.entries({"path": 5}, {"path": None}, {"path": ["~/pack"]}, {"nopath": 1}, "text", 7, {"path": ""},
                     {"path": "~/pack"})
        data = self.build()
        self.assertEqual(self.by_name(data, "one")[0]["tool"], "agy")
        self.assertGreaterEqual(len(self.config_row(data)["issues"]), 1)

    def test_paths_outside_the_home_folder_are_skipped(self):
        write_skill(self.outside, "elsewhere")
        for path in (str(self.outside), "/etc", "/tmp", "/", "relative/dir", "skills", "./skills", "~root/skills",
                     "~/../outside", str(self.home), "~", "~/", str(self.home) + "/../outside", "file:///etc",
                     "~/pack\x00x"):
            with self.subTest(path=path):
                self.entries({"path": path})
                data = self.build()
                self.assert_refused(data, path)

    def test_a_symlink_that_leaves_the_home_folder_is_not_followed(self):
        write_skill(self.outside, "elsewhere")
        link = self.home / "link-out"
        link.symlink_to(self.outside, target_is_directory=True)
        self.entries({"path": "~/link-out"})
        data = self.build()
        self.assert_refused(data, "symlink")
        self.assertEqual(self.by_name(data, "elsewhere"), [])

    def test_a_symlinked_skill_folder_inside_a_listed_folder_is_ignored(self):
        pack = self.home / "pack"
        pack.mkdir()
        write_skill(self.outside, "elsewhere")
        (pack / "elsewhere").symlink_to(self.outside / "elsewhere", target_is_directory=True)
        self.entries({"path": "~/pack"})
        self.assertEqual(self.by_name(self.build(), "elsewhere"), [])

    def test_a_skill_file_that_is_a_symlink_out_of_the_folder_is_not_read(self):
        pack = self.home / "pack"
        (pack / "leak").mkdir(parents=True)
        secret = self.outside / "SKILL.md"
        secret.write_text("---\nname: leak\ndescription: should not be read\n---\n", encoding="utf-8")
        (pack / "leak" / "SKILL.md").symlink_to(secret)
        self.entries({"path": "~/pack"})
        rec = self.by_name(self.build(), "leak")
        for r in rec:
            self.assertNotIn("should not be read", json.dumps(r))

    def test_a_skills_json_that_is_a_symlink_out_of_the_home_folder_counts_as_no_file(self):
        write_skill(self.home / "pack", "one")
        target = self.outside / "skills.json"
        target.write_text(json.dumps({"entries": [{"path": "~/pack"}]}), encoding="utf-8")
        link = self.home / ".gemini" / "config" / "skills.json"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        data = self.build()
        self.assertEqual(self.by_name(data, "one"), [])
        self.assertTrue(self.config_row(data)["issues"])

    def test_credential_folders_are_refused_even_inside_the_home_folder(self):
        for name in (".ssh", ".aws", ".gnupg"):
            (self.home / name).mkdir()
            write_skill(self.home / name, "bait")
        for name in (".ssh", ".aws", ".gnupg"):
            with self.subTest(folder=name):
                self.entries({"path": f"~/{name}"})
                data = self.build()
                self.assert_refused(data, name)
                self.assertEqual(self.by_name(data, "bait"), [])

    def test_a_missing_folder_is_reported_and_does_not_crash(self):
        self.entries({"path": "~/not-there"})
        data = self.build()
        self.assertTrue(any("不存在" in i for i in self.config_row(data)["issues"]))

    def test_a_listed_folder_inside_a_source_the_user_turned_off_is_not_scanned(self):
        write_skill(self.home / ".codex" / "skills", "alpha")
        self.entries({"path": "~/.codex/skills"})
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        conf["project_roots"] = []
        for src in conf["sources"]:
            if src["source_id"] == "codex-skills":
                src["enabled"] = False
        data = index.build_static(conf)
        self.assertEqual(self.by_name(data, "alpha"), [])
        self.assertTrue(any("關閉" in p for p in data["problems"]))


class OnlyTheTwoFilesAreReadTests(AgyCase):
    def test_nothing_else_under_dot_gemini_is_opened_or_listed(self):
        gem = self.home / ".gemini"
        write_skill(gem / "antigravity-cli" / "skills", "globalone")
        for rel in ("oauth_creds.json", "settings.json", "config/auth.json", "config/other.json",
                    "antigravity-cli/credentials.json", "antigravity-cli/plugins/p/skills/x/SKILL.md"):
            f = gem / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("{}", encoding="utf-8")
        self.entries({"path": "~/.gemini/antigravity-cli/skills"})
        touched: list[str] = []
        real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
        real_scandir, real_listdir = os.scandir, os.listdir

        def note(p):
            try:
                touched.append(os.fspath(p))
            except TypeError:
                pass

        def fake_open(p, *a, **k):
            note(p)
            return real_open(p, *a, **k)

        def fake_io_open(p, *a, **k):
            note(p)
            return real_io_open(p, *a, **k)

        def fake_os_open(p, *a, **k):
            note(p)
            return real_os_open(p, *a, **k)

        def fake_scandir(p=".", *a, **k):
            note(p)
            return real_scandir(p, *a, **k)

        def fake_listdir(p=".", *a, **k):
            note(p)
            return real_listdir(p, *a, **k)

        with unittest.mock.patch.object(builtins, "open", fake_open), \
                unittest.mock.patch.object(io, "open", fake_io_open), \
                unittest.mock.patch.object(os, "open", fake_os_open), \
                unittest.mock.patch.object(os, "scandir", fake_scandir), \
                unittest.mock.patch.object(os, "listdir", fake_listdir):
            data = self.build()
        self.assertTrue(self.by_name(data, "globalone"))
        allowed = (str(gem / "config" / "skills.json"), str(gem / "antigravity-cli" / "skills"))
        for path in touched:
            if str(gem) in path:
                self.assertTrue(path.startswith(allowed), f"opened or listed {path}")
        self.assertFalse([p for p in touched if p.endswith(("oauth_creds.json", "auth.json", "credentials.json",
                                                            "settings.json", "other.json"))
                          and str(gem) in p and not p.endswith("config/skills.json")])


class SkillCardAndLoadoutTests(AgyCase):
    def test_the_index_version_moved_so_an_old_index_is_scanned_again(self):
        self.assertGreaterEqual(index.INDEX_VERSION, 2)

    def test_agy_records_do_not_steal_a_subagents_skill_link(self):
        write_skill(self.home / ".claude" / "skills", "shared-name")
        write_skill(self.home / "pack", "shared-name")
        agents = self.home / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "helper.md").write_text("---\nname: helper\ndescription: d\nskills: shared-name\n---\nBody\n",
                                          encoding="utf-8")
        self.entries({"path": "~/pack"})
        data = self.build()
        claude_id = [s["skill_id"] for s in self.by_name(data, "shared-name") if s["tool"] == "claude"][0]
        helper = [r for r in data["roles"] if r["name"] == "helper"][0]
        self.assertEqual(helper["skill_link_ids"], [claude_id])


def _static():
    def rec(sid, tool, read_by=(), evidence=None):
        return {"skill_id": sid, "name": sid, "invoke_name": sid, "tool": tool, "scope": "user", "activation": "active",
                "path": f"/s/{sid}/SKILL.md", "read_by": list(read_by),
                "read_by_evidence": {"agy": evidence} if evidence else {},
                "description": {"value": "d", "origin": "author", "detail": "x"}}
    return {"index_version": index.INDEX_VERSION, "generated_at": 1.0, "roles": [], "skills": [
        rec("s-shared", "shared"), rec("s-codex", "codex", ["agy"], "AGY 的設定檔 skills.json 列出"),
        rec("s-own", "agy", ["agy"], "位於 AGY 的全域技能資料夾"), rec("s-claude", "claude")]}


def _profile(tool, skills):
    return {"id": "p1", "name": "N", "profession_role_id": None, "model": {"tool": tool, "model_id": ""},
            "equipped_skill_ids": skills, "permission_intents": {"read": "allow", "write": "allow", "test": "allow",
                                                                  "deploy": "deny"},
            "enabled": True, "created_at": 1.0, "updated_at": 1.0}


class LoadoutAndCardTests(unittest.TestCase):
    def test_an_agy_card_says_for_each_skill_whether_agy_reads_it(self):
        ids = ["s-shared", "s-codex", "s-own", "s-claude", "gone"]
        items = loadout.build(_profile("agy", ids), _static(), None, None)["skills"]["items"]
        self.assertEqual({i["skill_id"]: i["agy_reads"] for i in items},
                         {"s-shared": False, "s-codex": True, "s-own": True, "s-claude": False, "gone": None})
        self.assertTrue(all(i["will_load"] is False for i in items), "still only a collection")

    def test_an_agy_card_with_no_index_loaded_says_unknown(self):
        items = loadout.build(_profile("agy", ["s-codex"]), None, None, None)["skills"]["items"]
        self.assertIsNone(items[0]["agy_reads"])

    def test_other_cards_carry_no_agy_field(self):
        for tool in ("claude", "codex", "shared"):
            items = loadout.build(_profile(tool, ["s-shared"]), _static(), None, None)["skills"]["items"]
            self.assertNotIn("agy_reads", items[0], tool)

    def test_the_note_on_an_agy_card_is_the_honest_one(self):
        note = loadout.build(_profile("agy", []), _static(), None, None)["skills"]["note"]
        self.assertEqual(note, loadout.AGY_SKILLS_NOTE)
        self.assertNotIn("不知道 AGY 會讀哪些技能", note)
        self.assertIn("不代表 AGY 會載入", note)
        self.assertIn("內建與外掛", note)

    def test_the_skill_card_names_agy_as_a_reader_with_its_evidence(self):
        card = loadout.skill_card(_static(), "s-codex", [], None)["skill"]
        self.assertEqual(card["read_by"]["value"], ["agy"])
        self.assertEqual(card["read_by"]["origin"], "derived")
        self.assertIn("skills.json", card["read_by"]["detail"])
        plain = loadout.skill_card(_static(), "s-shared", [], None)["skill"]
        self.assertIsNone(plain["read_by"]["value"])
        self.assertEqual(plain["read_by"]["origin"], "missing")


if __name__ == "__main__":
    unittest.main()


class IssueWordingTests(AgyCase):
    """P23: under the config row's own title its issues do not repeat the title; the overview problems, which have no
    row title above them, keep it. Both say the same thing."""

    def test_row_issues_have_no_prefix_and_overview_problems_have_it(self):
        write_skill(self.home / "pack", "one")
        self.entries({"path": "/etc"}, {"path": "~/pack", "include_only": "one"}, 5)
        data = self.build()
        row = self.config_row(data)
        self.assertGreaterEqual(len(row["issues"]), 3, row["issues"])
        for issue in row["issues"]:
            self.assertFalse(issue.startswith("AGY 設定檔"), issue)
            self.assertNotIn("skills.json", issue)
            self.assertIn(PREFIX + issue, data["problems"], "the overview has the same text with the name in front")
        mine = [p for p in data["problems"] if p.startswith(PREFIX)]
        self.assertEqual(mine, [PREFIX + i for i in row["issues"]], "same items, same order, only the prefix differs")

    def test_a_refused_file_is_worded_the_same_way(self):
        self.config_file(raw=b"{ not json")
        data = self.build()
        row = self.config_row(data)
        self.assertEqual(row["issues"], ["不是有效的 JSON，當成沒有這個檔"])
        self.assertIn(PREFIX + "不是有效的 JSON，當成沒有這個檔", data["problems"])

    def test_the_row_title_is_unchanged(self):
        self.entries({"path": "~/missing"})
        self.assertEqual(self.config_row(self.build())["label"], "AGY 設定檔 skills.json")
