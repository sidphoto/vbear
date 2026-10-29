"""Phase C1 Agent Profile storage tests.

These exercise the same fail-closed invariants tasks.py's own suite proves
(tasks.test_tasks.TasksFailClosedTests, TasksCrossProcessTests etc.): a
non-missing read failure or an on-disk entry that doesn't match this
module's own schema must never be silently treated as an empty store or
silently dropped, and every cross-process write must hold the flock.
"""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ORIGINAL_PATH = os.environ.get("PATH", "")
# Same reuse-guard as tests/test_tasks.py:18-24 / tests/test_console.py —
# don't overwrite a HOME already pinned by a sibling module loaded earlier
# by `unittest discover`, or every test across the suite would observe the
# wrong fake-home.
if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-profile-test-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_profiles as ap  # noqa: E402


def _reset_state_dir():
    sd = Path(os.environ["VBEAR_HOME"])
    if sd.exists():
        shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)


def _sample(name="Alpha", tool="claude", model_id="opus-4.1",
            skills=None, prof="writer"):
    return {
        "name": name,
        "profession_role_id": prof,
        "model": {"tool": tool, "model_id": model_id},
        "equipped_skill_ids": list(skills or []),
        "permission_intents": {"read": "allow", "write": "deny",
                                "test": "unspecified", "deploy": "deny"},
    }


def _mp_save_worker(args):
    payload, i = args
    from vbear import agent_profiles as local
    return local.save_profile(None, payload, known_skills=set(),
                              known_roles={"writer", "reviewer"})["id"]


class StorageShapeTests(unittest.TestCase):
    def setUp(self):
        _reset_state_dir()

    def tearDown(self):
        marker = ap._corrupt_marker_path()
        if marker.exists() or marker.is_symlink():
            marker.unlink()
        for f in ap._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)
        if ap._path().exists() or ap._path().is_symlink():
            try:
                ap._path().chmod(0o600)
            except OSError:
                pass
            ap._path().unlink()

    def test_empty_state_lists_none(self):
        self.assertEqual(ap.list_profiles(), [])

    def test_save_create_returns_normalised_record(self):
        rec = ap.save_profile(None, _sample(skills=["alpha", "beta"]),
                              known_skills={"alpha", "beta"},
                              known_roles={"writer"})
        self.assertTrue(rec["id"].startswith("prof-"))
        self.assertEqual(rec["name"], "Alpha")
        self.assertEqual(rec["model"], {"tool": "claude", "model_id": "opus-4.1"})
        self.assertEqual(rec["equipped_skill_ids"], ["alpha", "beta"])
        self.assertEqual(rec["permission_intents"]["read"], "allow")
        self.assertEqual(rec["permission_intents"]["write"], "deny")
        self.assertTrue(rec["enabled"])
        self.assertEqual(rec["_unresolved"], {"profession": False, "skills": []})

    def test_save_writes_file_owner_only(self):
        ap.save_profile(None, _sample(), known_skills=set(),
                        known_roles=set())
        path = ap._path()
        st = path.stat()
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600,
                         "agent_profiles.json must be 0600")
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700,
                         "state dir must be 0700")
        self.assertEqual(st.st_nlink, 1,
                         "file must have exactly one hard link (no hardlink aliasing)")

    def test_update_keeps_created_at(self):
        rec1 = ap.save_profile(None, _sample(name="first"), known_skills=set(),
                               known_roles=set())
        time.sleep(0.01)
        rec2 = ap.save_profile(rec1["id"], _sample(name="second"),
                               known_skills=set(), known_roles=set())
        self.assertEqual(rec2["created_at"], rec1["created_at"],
                         "created_at must survive an update")
        self.assertGreater(rec2["updated_at"], rec1["updated_at"],
                           "updated_at must advance on update")

    def test_duplicate_creates_independent_profile(self):
        rec1 = ap.save_profile(None, _sample(name="Original"),
                               known_skills=set(), known_roles=set())
        dup = ap.duplicate_profile(rec1["id"], known_skills=set(),
                                   known_roles=set())
        self.assertNotEqual(dup["id"], rec1["id"])
        self.assertTrue(dup["name"].startswith("Original"))
        self.assertEqual(dup["model"], rec1["model"])
        self.assertEqual(dup["equipped_skill_ids"], rec1["equipped_skill_ids"])
        self.assertEqual(dup["permission_intents"], rec1["permission_intents"])
        self.assertEqual(ap.list_profiles(known_skills=set(),
                                          known_roles=set()).__len__(), 2)

    def test_duplicate_unknown_returns_none(self):
        self.assertIsNone(ap.duplicate_profile("prof-does-not-exist",
                                               known_skills=set(),
                                               known_roles=set()))

    def test_delete_returns_bool(self):
        rec = ap.save_profile(None, _sample(), known_skills=set(),
                              known_roles=set())
        self.assertTrue(ap.delete_profile(rec["id"]))
        self.assertFalse(ap.delete_profile(rec["id"]))
        self.assertFalse(ap.delete_profile("not-even-an-id"))

    def test_cap_at_max_profiles(self):
        # The cap only blocks new creates; this test seeds the file via the
        # public path so it goes through the normal save_profile validation.
        from vbear.agent_profiles import MAX_PROFILES, _path
        data = {}
        for i in range(MAX_PROFILES):
            data[f"prof-prefill-{i:03d}"] = {
                "id": f"prof-prefill-{i:03d}",
                "name": f"x{i}",
                "profession_role_id": None,
                "model": {"tool": "claude", "model_id": "a"},
                "equipped_skill_ids": [],
                "permission_intents": {"read": "unspecified", "write": "unspecified",
                                        "test": "unspecified", "deploy": "unspecified"},
                "enabled": True,
                "created_at": time.time(), "updated_at": time.time(),
            }
        ap._path().parent.mkdir(parents=True, exist_ok=True)
        cfg_state = ap._path()
        from vbear import config as cfg
        cfg.write_private(cfg_state, json.dumps(data))
        # We must have exactly the seeded records (none re-validated would
        # be silently dropped; their shape matches this module's so the load
        # can pass).
        self.assertEqual(len(ap.list_profiles(known_skills=set(),
                                              known_roles=set())), MAX_PROFILES)
        with self.assertRaises(ValueError):
            ap.save_profile(None, _sample(name="overflow"),
                            known_skills=set(), known_roles=set())
        # Duplicate must respect the same cap (AGY review 2026-09-25, Medium).
        with self.assertRaises(ValueError):
            ap.duplicate_profile("prof-prefill-000", known_skills=set(),
                                 known_roles=set())
        self.assertEqual(len(ap.list_profiles(known_skills=set(),
                                              known_roles=set())), MAX_PROFILES)


class SchemaStrictnessTests(unittest.TestCase):
    def setUp(self):
        _reset_state_dir()

    def _save_or_raise(self, body):
        return ap.save_profile(None, body, known_skills=set(),
                               known_roles=set())

    def test_unknown_top_level_field_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_or_raise({"name": "x", "model": {"tool": "claude",
                                  "model_id": "a"}, "mystery": True})
        self.assertIn("未支援", str(ctx.exception))

    def test_unknown_permission_key_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_or_raise({"name": "x", "model": {"tool": "claude",
                                  "model_id": "a"},
                                  "permission_intents": {"read": "allow",
                                                         "sudo": "allow"}})
        self.assertIn("未支援", str(ctx.exception))

    def test_invalid_permission_value_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_or_raise({"name": "x", "model": {"tool": "claude",
                                  "model_id": "a"},
                                  "permission_intents": {"read": "force"}})
        self.assertIn("allow", str(ctx.exception))

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ValueError):
            self._save_or_raise({"name": "x",
                                  "model": {"tool": "rogue", "model_id": "a"}})

    def test_name_must_be_non_empty(self):
        with self.assertRaises(ValueError):
            self._save_or_raise({"name": "  ", "model": {"tool": "claude",
                                   "model_id": "a"}})

    def test_equipped_must_be_a_list(self):
        with self.assertRaises(ValueError):
            self._save_or_raise({"name": "x",
                                  "model": {"tool": "claude", "model_id": "a"},
                                  "equipped_skill_ids": "alpha"})

    def test_cap_on_equipped_skill_ids(self):
        big = list(range(ap.MAX_SKILLS_PER_PROFILE + 1))
        with self.assertRaises(ValueError):
            self._save_or_raise({"name": "x",
                                  "model": {"tool": "claude", "model_id": "a"},
                                  "equipped_skill_ids": [str(s) for s in big]})

    def test_invalid_id_is_rejected(self):
        with self.assertRaises(ValueError):
            ap.save_profile("not valid!!", _sample(), known_skills=set(),
                            known_roles=set())


class UnresolvedReferenceTests(unittest.TestCase):
    def setUp(self):
        _reset_state_dir()

    def test_missing_skill_is_kept_and_flagged(self):
        rec = ap.save_profile(None, _sample(skills=["real", "ghost"]),
                              known_skills={"real"}, known_roles={"writer"})
        self.assertEqual(rec["equipped_skill_ids"], ["real", "ghost"])
        self.assertEqual(rec["_unresolved"]["skills"], ["ghost"])

    def test_missing_profession_is_kept_and_flagged(self):
        rec = ap.save_profile(None, _sample(prof="ghost-prof"),
                              known_skills=set(), known_roles={"writer"})
        self.assertEqual(rec["profession_role_id"], "ghost-prof")
        self.assertTrue(rec["_unresolved"]["profession"])

    def test_update_without_profession_key_keeps_the_stored_profession(self):
        # the card list's 停用／啟用 posts only {"enabled": ...}
        rec = ap.save_profile(None, _sample(prof="writer"), known_skills=set(),
                              known_roles={"writer"})
        rec2 = ap.save_profile(rec["id"], {"enabled": False}, known_skills=set(),
                               known_roles={"writer"})
        self.assertFalse(rec2["enabled"])
        self.assertEqual(rec2["profession_role_id"], "writer")
        on_disk = ap.get_profile(rec["id"], known_skills=set(), known_roles={"writer"})
        self.assertEqual(on_disk["profession_role_id"], "writer")

    def test_update_without_profession_key_keeps_an_unresolved_profession(self):
        rec = ap.save_profile(None, _sample(prof="ghost-prof"), known_skills=set(),
                              known_roles=set())
        rec2 = ap.save_profile(rec["id"], {"enabled": False}, known_skills=set(),
                               known_roles=set())
        self.assertEqual(rec2["profession_role_id"], "ghost-prof")
        self.assertTrue(rec2["_unresolved"]["profession"])

    def test_update_with_null_or_empty_profession_clears_it(self):
        for cleared in (None, "", "   "):
            rec = ap.save_profile(None, _sample(prof="writer"), known_skills=set(),
                                  known_roles={"writer"})
            rec2 = ap.save_profile(rec["id"], {"profession_role_id": cleared},
                                   known_skills=set(), known_roles={"writer"})
            self.assertIsNone(rec2["profession_role_id"], repr(cleared))
            self.assertFalse(rec2["_unresolved"]["profession"], repr(cleared))

    def test_update_with_a_new_profession_replaces_it(self):
        rec = ap.save_profile(None, _sample(prof="writer"), known_skills=set(),
                              known_roles={"writer", "reviewer"})
        rec2 = ap.save_profile(rec["id"], {"profession_role_id": "reviewer"},
                               known_skills=set(), known_roles={"writer", "reviewer"})
        self.assertEqual(rec2["profession_role_id"], "reviewer")

    def test_new_profile_without_profession_key_has_none(self):
        body = _sample()
        del body["profession_role_id"]
        rec = ap.save_profile(None, body, known_skills=set(), known_roles={"writer"})
        self.assertIsNone(rec["profession_role_id"])

    def test_non_string_profession_is_still_rejected_on_update(self):
        rec = ap.save_profile(None, _sample(prof="writer"), known_skills=set(),
                              known_roles={"writer"})
        with self.assertRaises(ValueError):
            ap.save_profile(rec["id"], {"profession_role_id": 5}, known_skills=set(),
                            known_roles={"writer"})

    def test_load_all_re_decorates_against_today_catalog(self):
        rec = ap.save_profile(None, _sample(skills=["now-missing"]),
                              known_skills={"now-missing"}, known_roles=set())
        # Skill disappears from the catalog; the reference must NOT be lost.
        rec_loaded = ap.get_profile(rec["id"], known_skills=set(),
                                   known_roles=set())
        self.assertEqual(rec_loaded["equipped_skill_ids"], ["now-missing"])
        self.assertEqual(rec_loaded["_unresolved"]["skills"], ["now-missing"])


class FailClosedOnReadTests(unittest.TestCase):
    def setUp(self):
        _reset_state_dir()
        marker = ap._corrupt_marker_path()
        if marker.exists():
            marker.unlink()
        for f in ap._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)

    def tearDown(self):
        marker = ap._corrupt_marker_path()
        if marker.exists() or marker.is_symlink():
            marker.unlink()
        for f in ap._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)
        if ap._path().exists() or ap._path().is_symlink():
            try:
                ap._path().chmod(0o600)
            except OSError:
                pass
            ap._path().unlink()

    def test_malformed_entry_fails_closed_and_is_quarantined(self):
        ap.save_profile("t-real", _sample(name="Important"),
                        known_skills=set(), known_roles=set())
        path = ap._path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["t-broken"] = {
            "id": "t-broken", "name": "x",
            "model": {"tool": "rogue", "model_id": "y"},
        }
        path.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaises(ap.AgentProfileStorageError):
            ap.list_profiles()
        with self.assertRaises(ap.AgentProfileStorageError):
            ap.get_profile("t-real")
        # Critically: a save attempted after this must NOT silently start
        # from an empty store and clobber the file with just the new task.
        with self.assertRaises(ap.AgentProfileStorageError):
            ap.save_profile(None, _sample(name="must-not-get-through"),
                            known_skills=set(), known_roles=set())

        marker = ap._corrupt_marker_path()
        self.assertTrue(marker.exists())
        quarantine = list(ap._path().parent.glob("agent_profiles.json.corrupt-*"))
        self.assertEqual(len(quarantine), 1)
        self.assertIn("t-real", quarantine[0].read_text(encoding="utf-8"),
                      "quarantined file must preserve the original data")

        # Explicit human recovery clears the block.
        marker.unlink()
        self.assertEqual(ap.list_profiles(), [])
        ap.save_profile("t-after-recovery", _sample(name="Works again"),
                        known_skills=set(), known_roles=set())
        self.assertIsNotNone(ap.get_profile("t-after-recovery"))

    def test_marker_write_failure_leaves_corrupt_file_in_place(self):
        path = ap._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json!!!", encoding="utf-8")
        with mock.patch.object(ap, "_write_marker",
                               side_effect=OSError("disk full (simulated)")):
            with self.assertRaises(ap.AgentProfileStorageError):
                ap.list_profiles()
        marker = ap._corrupt_marker_path()
        self.assertFalse(marker.exists())
        self.assertTrue(path.exists())
        self.assertIn("not valid json", path.read_text(encoding="utf-8"))
        self.assertEqual(list(path.parent.glob("agent_profiles.json.corrupt-*")),
                         [])
        # The store must still be blocked meanwhile.
        with self.assertRaises(ap.AgentProfileStorageError):
            with mock.patch.object(ap, "_write_marker",
                                   side_effect=OSError("disk full (simulated)")):
                ap.save_profile(None, _sample(name="must-not-get-through"),
                                known_skills=set(), known_roles=set())
        self.assertIn("not valid json", path.read_text(encoding="utf-8"))

    def test_quarantine_move_failure_leaves_store_blocked(self):
        path = ap._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"broken": ', encoding="utf-8")

        real_rename = Path.rename

        def fail_quarantine_move(self_path, target):
            if ".corrupt-" in str(target):
                raise OSError("cross-device link (simulated)")
            return real_rename(self_path, target)

        with mock.patch.object(Path, "rename", fail_quarantine_move):
            with self.assertRaises(ap.AgentProfileStorageError):
                ap.list_profiles()
        marker = ap._corrupt_marker_path()
        self.assertTrue(marker.exists())
        self.assertTrue(path.exists())
        self.assertIn("broken", path.read_text(encoding="utf-8"))
        with self.assertRaises(ap.AgentProfileStorageError):
            ap.list_profiles()
        with self.assertRaises(ap.AgentProfileStorageError):
            ap.save_profile(None, _sample(name="must-not-get-through"),
                            known_skills=set(), known_roles=set())

    def test_directory_fsync_failure_is_not_mistaken_for_failed_move(self):
        path = ap._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[not an object]", encoding="utf-8")
        with mock.patch.object(ap, "_fsync_dir",
                               side_effect=OSError("fsync refused (simulated)")):
            with self.assertRaises(ap.AgentProfileStorageError) as ctx:
                ap.list_profiles()
        message = str(ctx.exception)
        self.assertNotIn("無法搬移", message)
        self.assertNotIn("無法寫入復原標記", message)
        marker = ap._corrupt_marker_path()
        self.assertTrue(marker.exists())
        self.assertFalse(path.exists(), "the corrupt file really was moved aside")
        quarantine = list(ap._path().parent.glob("agent_profiles.json.corrupt-*"))
        self.assertEqual(len(quarantine), 1)

    def test_read_fails_closed_on_symlink(self):
        path = ap._path()
        real_target = path.parent / "elsewhere.json"
        real_target.write_text(json.dumps({"t-elsewhere": _sample(name="x")}),
                               encoding="utf-8")
        path.symlink_to(real_target)
        with self.assertRaises(ap.AgentProfileStorageError):
            ap.list_profiles()
        with self.assertRaises(ap.AgentProfileStorageError):
            ap.save_profile(None, _sample(name="must-not-silently-succeed"),
                            known_skills=set(), known_roles=set())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root bypasses file permission checks")
    def test_read_fails_closed_on_permission_denied(self):
        ap.save_profile("t-before-perm", _sample(name="must-survive"),
                        known_skills=set(), known_roles=set())
        path = ap._path()
        path.chmod(0o000)
        try:
            with self.assertRaises(ap.AgentProfileStorageError):
                ap.list_profiles()
            with self.assertRaises(ap.AgentProfileStorageError):
                ap.get_profile("t-before-perm")
        finally:
            path.chmod(0o600)
        self.assertIsNotNone(ap.get_profile("t-before-perm"))


class CardPositionFieldTests(unittest.TestCase):
    """P32-3: the suggested position is a field of the role card, not only a note in the browser."""

    def setUp(self):
        _reset_state_dir()

    def tearDown(self):
        marker = ap._corrupt_marker_path()
        if marker.exists() or marker.is_symlink():
            marker.unlink()
        for f in ap._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)
        if ap._path().exists() or ap._path().is_symlink():
            ap._path().unlink()

    def _save(self, pid, body):
        return ap.save_profile(pid, body, known_skills=set(), known_roles={"writer"})

    def _on_disk(self, pid):
        return json.loads(ap._path().read_text(encoding="utf-8"))[pid]

    def test_every_listed_position_is_stored_and_read_back(self):
        for position in ap.POSITIONS:
            rec = self._save(None, {**_sample(), "position": position})
            self.assertEqual(rec["position"], position)
            self.assertEqual(self._on_disk(rec["id"])["position"], position)
            got = ap.get_profile(rec["id"], known_skills=set(), known_roles={"writer"})
            self.assertEqual(got["position"], position)

    def test_update_without_position_key_keeps_the_stored_position(self):
        # the workbench 停用／啟用 posts only {"enabled": ...}
        rec = self._save(None, {**_sample(), "position": "legal"})
        for flag in (False, True):
            rec2 = self._save(rec["id"], {"enabled": flag})
            self.assertEqual(rec2["enabled"], flag)
            self.assertEqual(rec2["position"], "legal")
            self.assertEqual(self._on_disk(rec["id"])["position"], "legal")
        # a full save that leaves the key out (an older page) keeps it too
        rec3 = self._save(rec["id"], _sample(name="Renamed"))
        self.assertEqual(rec3["position"], "legal")

    def test_update_with_null_or_empty_position_clears_it(self):
        for cleared in (None, ""):
            rec = self._save(None, {**_sample(), "position": "accountant"})
            rec2 = self._save(rec["id"], {"position": cleared})
            self.assertNotIn("position", rec2, repr(cleared))
            self.assertNotIn("position", self._on_disk(rec["id"]), repr(cleared))

    def test_update_with_a_new_position_replaces_it(self):
        rec = self._save(None, {**_sample(), "position": "planner"})
        rec2 = self._save(rec["id"], {"position": "social"})
        self.assertEqual(rec2["position"], "social")

    def test_unknown_or_non_string_position_is_rejected_on_save(self):
        rec = self._save(None, {**_sample(), "position": "planner"})
        for bad in ("boss", "QA", " qa", "qa ", " ", 5, True, ["qa"], {"id": "qa"}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self._save(None, {**_sample(), "position": bad})
            with self.assertRaises(ValueError, msg=repr(bad)):
                self._save(rec["id"], {"position": bad})
        self.assertEqual(self._on_disk(rec["id"])["position"], "planner")
        self.assertEqual(len(ap.list_profiles(known_skills=set(), known_roles={"writer"})), 1)

    def test_a_card_without_a_position_has_no_position_key_on_disk(self):
        rec = self._save(None, _sample())
        self.assertNotIn("position", rec)
        self.assertNotIn("position", self._on_disk(rec["id"]))
        rec2 = self._save(None, {**_sample(), "position": None})
        self.assertNotIn("position", self._on_disk(rec2["id"]))

    def test_digest_of_a_card_without_a_position_is_unchanged(self):
        # a golden value: cards saved before P32-3 keep the revision a task card recorded for them
        card = {"id": "prof-gold", "name": "Gold", "profession_role_id": "writer",
                "model": {"tool": "claude", "model_id": "opus"}, "equipped_skill_ids": ["a"],
                "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
                "enabled": True, "created_at": 1000.0, "updated_at": 2000.0}
        self.assertEqual(ap.profile_digest(card),
                         "5b3dd856d36ba42913c23c774fe2e927ccb7cea56f0ea728128424e57769216c")
        # a position counts in the revision, as any other field does
        self.assertNotEqual(ap.profile_digest({**card, "position": "legal"}), ap.profile_digest(card))

    def test_a_position_this_build_does_not_know_is_kept_and_not_quarantined(self):
        rec = self._save(None, {**_sample(), "position": "planner"})
        data = json.loads(ap._path().read_text(encoding="utf-8"))
        data[rec["id"]]["position"] = "future-position"
        ap._path().write_text(json.dumps(data), encoding="utf-8")
        # reading does not isolate the file, and the value is handed on as it is
        got = ap.get_profile(rec["id"], known_skills=set(), known_roles={"writer"})
        self.assertEqual(got["position"], "future-position")
        self.assertFalse(ap._corrupt_marker_path().exists())
        # a save that leaves the key out keeps it; so does a copy
        rec2 = self._save(rec["id"], {"enabled": False})
        self.assertEqual(rec2["position"], "future-position")
        dup = ap.duplicate_profile(rec["id"], known_skills=set(), known_roles={"writer"})
        self.assertEqual(dup["position"], "future-position")
        self.assertEqual(self._on_disk(dup["id"])["position"], "future-position")
        # only an explicit clear removes it
        rec3 = self._save(rec["id"], {"position": None})
        self.assertNotIn("position", rec3)

    def test_a_retired_position_is_refused_on_save_and_kept_when_read(self):
        # P34-1: the ids only the unreleased v0.9.0 wrote are no longer accepted, but a card that carries one is not
        # damaged: it is read, copied and left alone by a save that does not mention the position
        for old in ap.RETIRED_POSITIONS:
            with self.assertRaises(ValueError, msg=old):
                self._save(None, {**_sample(), "position": old})
        rec = self._save(None, {**_sample(), "position": "planner"})
        data = json.loads(ap._path().read_text(encoding="utf-8"))
        data[rec["id"]]["position"] = "qa"
        ap._path().write_text(json.dumps(data), encoding="utf-8")
        got = ap.get_profile(rec["id"], known_skills=set(), known_roles={"writer"})
        self.assertEqual(got["position"], "qa")
        self.assertFalse(ap._corrupt_marker_path().exists())
        with self.assertRaises(ValueError):
            self._save(rec["id"], {"position": "research"})
        self.assertEqual(self._on_disk(rec["id"])["position"], "qa")
        rec2 = self._save(rec["id"], {"enabled": False})
        self.assertEqual(rec2["position"], "qa")
        dup = ap.duplicate_profile(rec["id"], known_skills=set(), known_roles={"writer"})
        self.assertEqual(dup["position"], "qa")
        self.assertEqual(self._save(rec["id"], {"position": "reviewer"})["position"], "reviewer")

    def test_a_stored_position_of_the_wrong_type_is_a_storage_error(self):
        for bad in (5, ["qa"], {"id": "qa"}, "x" * 33):
            _reset_state_dir()
            marker = ap._corrupt_marker_path()
            if marker.exists():
                marker.unlink()
            rec = self._save(None, _sample())
            data = json.loads(ap._path().read_text(encoding="utf-8"))
            data[rec["id"]]["position"] = bad
            ap._path().write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ap.AgentProfileStorageError, msg=repr(bad)):
                ap.list_profiles()
            self.assertTrue(ap._corrupt_marker_path().exists(), repr(bad))

    def test_duplicate_copies_the_position(self):
        rec = self._save(None, {**_sample(name="Original"), "position": "art"})
        dup = ap.duplicate_profile(rec["id"], known_skills=set(), known_roles={"writer"})
        self.assertEqual(dup["position"], "art")
        self.assertEqual(self._on_disk(dup["id"])["position"], "art")
        plain = self._save(None, _sample(name="Plain"))
        dup2 = ap.duplicate_profile(plain["id"], known_skills=set(), known_roles={"writer"})
        self.assertNotIn("position", self._on_disk(dup2["id"]))


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        _reset_state_dir()
        marker = ap._corrupt_marker_path()
        if marker.exists():
            marker.unlink()
        for f in ap._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)
        if ap._lock_path().exists():
            ap._lock_path().unlink()

    def test_concurrent_creates_all_persist_with_unique_ids(self):
        n_threads = 12
        created_ids = []
        lock = threading.Lock()
        errors = []

        def worker(i):
            try:
                t = ap.save_profile(None, _sample(name=f"concurrent {i}"),
                                    known_skills=set(), known_roles=set())
                with lock:
                    created_ids.append(t["id"])
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"concurrent save_profile must not raise: {errors}")
        self.assertEqual(len(created_ids), n_threads)
        self.assertEqual(len(set(created_ids)), n_threads,
                         "every concurrently-created profile must get a unique id")
        all_profiles = ap.list_profiles(known_skills=set(), known_roles=set())
        self.assertEqual(len(all_profiles), n_threads)
        raw = json.loads(ap._path().read_text(encoding="utf-8"))
        self.assertEqual(len(raw), n_threads)

    def test_concurrent_update_of_the_same_profile_never_corrupts_the_file(self):
        ap.save_profile("t-hot", _sample(name="shared"),
                        known_skills=set(), known_roles=set())
        errors = []

        def worker(i):
            try:
                ap.save_profile("t-hot",
                                _sample(name=f"v{i}"),
                                known_skills=set(), known_roles=set())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        raw = json.loads(ap._path().read_text(encoding="utf-8"))
        self.assertIn("t-hot", raw)
        current = ap.get_profile("t-hot", known_skills=set(),
                                  known_roles=set())
        self.assertEqual(raw["t-hot"]["name"], current["name"],
                         "on-disk shape must match what load_all returned")


class CrossProcessTests(unittest.TestCase):
    def setUp(self):
        _reset_state_dir()
        marker = ap._corrupt_marker_path()
        if marker.exists():
            marker.unlink()
        for f in ap._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)
        if ap._lock_path().exists():
            ap._lock_path().unlink()

    def test_concurrent_creates_across_separate_processes_are_not_lost(self):
        n = 24
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(processes=8) as pool:
            ids = pool.map(_mp_save_worker,
                           [(_sample(name=f"x{i}"), i) for i in range(n)])
        self.assertEqual(len(ids), n)
        self.assertEqual(len(set(ids)), n,
                         "every concurrently-created profile across processes "
                         "must get a unique id")
        all_profiles = ap.list_profiles(known_skills=set(),
                                         known_roles={"writer", "reviewer"})
        self.assertEqual(len(all_profiles), n)
        raw = json.loads(ap._path().read_text(encoding="utf-8"))
        self.assertEqual(len(raw), n)


if __name__ == "__main__":
    unittest.main()