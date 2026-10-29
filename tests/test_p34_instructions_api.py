"""P34-2 over HTTP: the catalog serves the guide and the launch modes, a card saves and reads back its instructions and
launch mode, the terminal's paste button reads the text from the server, the pass says the mode, the boundaries and the
folder suggestion, and a card set to full mode is not started as a safe one.

A synthetic stand-in plays the CLI. No Claude, Codex or model is started.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

from tests.test_agent_launch_api import GOOD
from tests.test_runtimed_managed import FAKE_CLI, FAKE_CODEX_CLI
from tests.test_runtimed_s3 import ServerCase
from vbear import agent_profiles, position_guide


class P342ApiCase(ServerCase):
    """The harness of the pass tests (tests/test_agent_launch_api.PreviewApiCase) without its tests, which would
    otherwise run again under every class below."""
    kind = "native"

    def setUp(self):
        super().setUp()
        self.tmp = Path(os.path.realpath(self.tmp))
        self.work = self.tmp / "work"
        self.work.mkdir()
        (self.work / "fake-mode").write_text("none")
        self.binary = self.tmp / "claude"
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.286"}, encoding="utf-8")
        self.binary.chmod(0o700)
        self.pin = mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(self.binary))
        self.pin.start()
        self.codex_binary = self.tmp / "codex"
        self.codex_binary.write_text(FAKE_CODEX_CLI % {"py": sys.executable}, encoding="utf-8")
        self.codex_binary.chmod(0o700)
        self.codex_pin = mock.patch("vbear.runtime.native._pinned_codex_binary", return_value=str(self.codex_binary))
        self.codex_pin.start()
        self.console.managed_root = self.tmp
        self.scratches: list[str] = []

    def tearDown(self):
        self.codex_pin.stop()
        self.pin.stop()
        super().tearDown()
        for p in self.scratches:
            if p.startswith("/private/tmp/sc-"):
                shutil.rmtree(p, ignore_errors=True)

    def save(self, **extra) -> str:
        body = {"name": "p-" + os.urandom(3).hex(), "model": {"tool": "claude", "model_id": ""},
                "permission_intents": GOOD, "enabled": True, **extra}
        st, r = self.req("POST", "/api/agent-profiles", body)
        self.assertEqual(st, 200, r)
        return r["profile"]["id"]

    def preview(self, profile_id, **kw):
        body = {"profile_id": profile_id, "workdir": str(self.work), "commit": True, **kw}
        st, r = self.req("POST", "/api/native/agent-previews", body)
        if st == 200 and r["preview"]["canonical_paths"]["scratch"]:
            self.scratches.append(r["preview"]["canonical_paths"]["scratch"])
        return st, r

    def dm_rpc(self, op, **kw):
        from vbear.runtime import daemon as d
        return d.rpc(op, base=self.home, timeout=15.0, **kw)

    def sessions(self):
        return self.dm_rpc("list")["result"]["sessions"]

    def get_profile(self, pid):
        st, r = self.req("GET", f"/api/agent-profiles/{pid}")
        self.assertEqual(st, 200, r)
        return r["profile"]


class CatalogTests(P342ApiCase):
    def test_the_catalog_serves_the_guide_the_modes_and_the_limits(self):
        st, cat = self.req("GET", "/api/agent-builder/catalog")
        self.assertEqual(st, 200)
        self.assertEqual(list(cat["position_guide"]), agent_profiles.POSITIONS and list(position_guide.GUIDE))
        legal = cat["position_guide"]["legal"]
        self.assertEqual(legal["prompt"], position_guide.GUIDE["legal"]["prompt"])
        self.assertEqual(legal["skill_categories"], ["security", "legal"])
        self.assertEqual(legal["suggested_folder"], "法務報告")
        self.assertEqual(sorted(legal["views"]), ["agy", "claude", "codex", "shared"])
        self.assertEqual(legal["views"]["claude"]["full"]["launch_mode"], "full")
        self.assertEqual([m["id"] for m in cat["launch_modes"]], ["full", "safe"])
        self.assertEqual(cat["default_launch_mode"], "full")
        self.assertIs(cat["full_mode_launchable"], False)
        self.assertEqual(cat["max_instructions"], 2000)
        self.assertIn("貼上職位指示", cat["instructions_where"])
        self.assertIn("legal", {c["id"] for c in cat["skill_categories"]} | {"legal"})

    def test_the_position_table_the_page_repeats_is_not_changed_by_the_guide(self):
        _, cat = self.req("GET", "/api/agent-builder/catalog")
        for row in cat["position_table"]:
            self.assertNotIn("prompt", row)
            self.assertNotIn("boundaries", row)


class SaveAndReadTests(P342ApiCase):
    def test_instructions_and_mode_are_saved_listed_kept_and_cleared(self):
        pid = self.save(position="legal", instructions="自訂的指示", launch_mode="safe")
        card = self.get_profile(pid)
        self.assertEqual((card["instructions"], card["launch_mode"]), ("自訂的指示", "safe"))
        st, r = self.req("POST", f"/api/agent-profiles/{pid}", {"enabled": False})
        self.assertEqual(st, 200)
        self.assertEqual((r["profile"]["instructions"], r["profile"]["launch_mode"]), ("自訂的指示", "safe"))
        st, r = self.req("POST", f"/api/agent-profiles/{pid}", {"instructions": None, "launch_mode": None})
        self.assertEqual(st, 200)
        self.assertNotIn("instructions", r["profile"])
        self.assertNotIn("launch_mode", r["profile"])

    def test_bad_values_are_refused_with_400(self):
        base = {"name": "x", "model": {"tool": "claude", "model_id": ""}, "permission_intents": GOOD}
        for extra in ({"instructions": "字" * 2001}, {"instructions": "a\x00b"}, {"instructions": 5}, {"instructions": ["x"]},
                      {"launch_mode": "turbo"}, {"launch_mode": 1}, {"launch_mode": True}, {"launch_mode": float("nan")}):
            st, r = self.req("POST", "/api/agent-profiles", {**base, **extra})
            self.assertEqual(st, 400, extra)

    def test_a_card_without_either_key_reads_back_without_them(self):
        card = self.get_profile(self.save(position="executor"))
        self.assertNotIn("instructions", card)
        self.assertNotIn("launch_mode", card)

    def test_a_copy_carries_both(self):
        pid = self.save(instructions="自訂", launch_mode="full")
        st, r = self.req("POST", f"/api/agent-profiles/{pid}/duplicate", {})
        self.assertEqual(st, 200)
        self.assertEqual((r["profile"]["instructions"], r["profile"]["launch_mode"]), ("自訂", "full"))


class InstructionsEndpointTests(P342ApiCase):
    def test_the_text_the_paste_button_uses(self):
        custom = self.save(name="Law", position="legal", instructions="自訂的指示")
        st, r = self.req("GET", f"/api/agent-profiles/{custom}/instructions")
        self.assertEqual((st, r["source"], r["text"], r["position"], r["name"]), (200, "custom", "自訂的指示", "legal", "Law"))
        default = self.save(position="legal")
        st, r = self.req("GET", f"/api/agent-profiles/{default}/instructions")
        self.assertEqual((r["source"], r["text"]), ("default", position_guide.GUIDE["legal"]["prompt"]))
        bare = self.save()
        st, r = self.req("GET", f"/api/agent-profiles/{bare}/instructions")
        self.assertEqual((st, r["source"], r["text"]), (200, "none", None))

    def test_a_retired_position_reads_as_the_one_it_became(self):
        pid = self.save()
        path = agent_profiles._path()
        data = json.loads(path.read_text())
        data[pid]["position"] = "design"
        path.write_text(json.dumps(data))
        os.chmod(path, 0o600)
        st, r = self.req("GET", f"/api/agent-profiles/{pid}/instructions")
        self.assertEqual((st, r["position"], r["source"]), (200, "art", "default"))

    def test_an_unknown_card_is_404_and_the_read_changes_nothing(self):
        st, _ = self.req("GET", "/api/agent-profiles/prof-nope/instructions")
        self.assertEqual(st, 404)
        pid = self.save(instructions="x")
        before = agent_profiles._path().read_bytes()
        self.req("GET", f"/api/agent-profiles/{pid}/instructions")
        self.assertEqual(agent_profiles._path().read_bytes(), before)

    def test_a_damaged_store_says_so_and_is_not_quarantined_by_the_read(self):
        pid = self.save()
        path = agent_profiles._path()
        path.write_text("{ not json")
        os.chmod(path, 0o600)
        st, r = self.req("GET", f"/api/agent-profiles/{pid}/instructions")
        self.assertEqual((st, r["code"]), (409, "profile_store_damaged"))
        self.assertTrue(path.exists())
        self.assertFalse(agent_profiles._corrupt_marker_path().exists())


class PassTests(P342ApiCase):
    def test_a_safe_card_gets_the_mode_the_boundaries_and_a_folder_suggestion(self):
        pid = self.save(position="art", launch_mode="safe")
        st, r = self.preview(pid)
        self.assertEqual(st, 200, r)
        pv = r["preview"]
        self.assertTrue(pv["launchable"])
        self.assertEqual((pv["launch_mode"], pv["position"]), ("safe", "art"))
        self.assertIn("擋得住", pv["mode_note"])
        kinds = {b["id"]: b["kind"] for b in pv["boundaries"]["items"]}
        self.assertEqual(kinds["asset_folder"], "enforced_if_launched")
        self.assertEqual(kinds["generation"], "not_possible")
        # the work folder here is named "work", not "素材": a suggestion, and the path itself is not repeated
        self.assertIn("素材", pv["folder_warning"])
        self.assertIn("work", pv["folder_warning"])
        self.assertNotIn(str(self.tmp), pv["folder_warning"])

    def test_a_folder_named_as_suggested_is_quiet(self):
        folder = self.tmp / "素材"
        folder.mkdir()
        (folder / "fake-mode").write_text("none")
        pid = self.save(position="art")
        st, r = self.preview(pid, workdir=str(folder))
        self.assertEqual(st, 200, r)
        self.assertIsNone(r["preview"]["folder_warning"])

    def test_a_card_without_a_position_has_no_boundaries_and_no_warning(self):
        st, r = self.preview(self.save())
        pv = r["preview"]
        self.assertEqual((pv["launch_mode"], pv["position"], pv["boundaries"], pv["folder_warning"]), ("safe", None, None, None))

    def test_a_full_mode_card_is_not_started_and_nothing_is_prepared(self):
        pid = self.save(position="executor", launch_mode="full")
        before = self.sessions()
        st, r = self.preview(pid)
        self.assertEqual(st, 200, r)
        pv = r["preview"]
        self.assertFalse(pv["launchable"])
        self.assertIsNone(pv["preview_id"])
        self.assertEqual([x["code"] for x in pv["reasons"]], ["full_mode_not_available"])
        self.assertIsNone(pv["settings_digest"])
        self.assertEqual(pv["launch_mode"], "full")
        self.assertEqual({b["kind"] for b in pv["boundaries"]["items"]}, {"reminder"})
        self.assertEqual(self.sessions(), before, "no session was started")

    def test_the_loadout_of_a_full_card_says_it_cannot_depart_and_has_no_armor(self):
        pid = self.save(position="executor", launch_mode="full")
        st, ld = self.req("GET", f"/api/agent-profiles/{pid}/loadout")
        self.assertEqual(st, 200)
        self.assertEqual([b["code"] for b in ld["blockers"]], ["full_mode_not_available"])
        self.assertFalse(ld["armor"]["applicable"])
        self.assertEqual(ld["launch_mode"]["mode"], "full")

    def test_the_loadout_of_an_old_card_is_safe_and_says_nothing_was_set(self):
        pid = self.save(position="executor")
        st, ld = self.req("GET", f"/api/agent-profiles/{pid}/loadout")
        self.assertEqual((ld["launch_mode"]["mode"], ld["launch_mode"]["stored"]), ("safe", False))
        self.assertEqual(ld["blockers"], [])
        self.assertEqual(ld["instructions"]["source"], "default")
        self.assertFalse(ld["instructions"]["automatic"])
