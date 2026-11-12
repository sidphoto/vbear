"""P46-2 / P56-2: the administrator policy sources of AGY 1.5.3 and 1.5.6 (vbear/admin_policy.py). Every check runs against a temporary root; the real
/etc and /Library are never looked at, and no AGY is started."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import admin_policy as ap

AGY = "1.5.3"
AGY_156 = "1.5.6"
APP_SUPPORT = "Library/Application Support/Antigravity"
PREFS = "Library/Managed Preferences"


class AgyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbag-")))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for dirpath, dirnames, _ in os.walk(self.root):
            for d in dirnames:
                try:
                    os.chmod(os.path.join(dirpath, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, rel, *, directory=False):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if directory:
            p.mkdir()
        else:
            p.write_text("x")
        return p

    def agy(self, version=AGY):
        return ap.check_agy(version, str(self.root))

    def test_the_list_is_the_one_the_plan_names(self):
        self.assertEqual(set(ap.AGY_SOURCES), {AGY, AGY_156})       # (v0.25.2 added 1.5.6; 1.5.3's entry below is unchanged)
        spec = ap.AGY_SOURCES[AGY]
        self.assertEqual(tuple(spec["paths"]), ("etc/antigravity",))
        self.assertEqual(spec["domain"], "com.google.antigravity")
        self.assertEqual(tuple(spec["home_paths"]), ())

    def test_1_5_6_has_the_list_of_1_5_3_and_one_more_place_the_strings_of_the_real_program_name(self):
        """The strings of the real 1.5.6 hold /Library/Application Support/Antigravity once; the 1.5.3 reading left that fragment out as
        unexplained. For 1.5.6 it is a source (only stricter); 1.5.3's list does not change."""
        old, new = ap.AGY_SOURCES[AGY], ap.AGY_SOURCES[AGY_156]
        self.assertEqual(tuple(new["paths"]), ("etc/antigravity", APP_SUPPORT))
        self.assertTrue(set(old["paths"]) < set(new["paths"]), "a later version never has fewer sources than the earlier one")
        self.assertEqual(new["domain"], old["domain"])
        self.assertEqual(tuple(new["home_paths"]), tuple(old["home_paths"]))

    def test_1_5_6_refuses_on_the_new_place_and_1_5_3_does_not(self):
        self.assertTrue(self.agy(AGY_156).ok)
        for rel, directory in ((APP_SUPPORT, True), (f"{APP_SUPPORT}/anything.json", False), (f"{APP_SUPPORT}/sub/deeper", False)):
            with self.subTest(source=rel):
                self._cleanup()
                self.root.mkdir(parents=True)
                p = self.make(rel, directory=directory)
                if not directory:
                    p.chmod(0o000)
                r = self.agy(AGY_156)
                self.assertFalse(r.ok)
                self.assertTrue(r.found)
                self.assertIn("管理員", r.reason())
                self.assertTrue(self.agy(AGY).ok, "1.5.3's list is the one of v0.25.0")
        self._cleanup()
        self.root.mkdir(parents=True)
        (self.root / "Library/Application Support").mkdir(parents=True)
        (self.root / APP_SUPPORT).symlink_to("/nonexistent-target")        # a dangling link is a source too
        self.assertFalse(self.agy(AGY_156).ok)

    def test_the_new_place_is_said_to_be_unconfirmed_not_to_be_an_administrator_policy(self):          # R1
        """Nothing shows what ``/Library/Application Support/Antigravity`` is, so the sentence does not claim a policy: it says the use
        is not confirmed and that this is why the chat does not start. The confirmed sources keep their old sentence."""
        self.make(APP_SUPPORT, directory=True)
        r = self.agy(AGY_156)
        self.assertFalse(r.ok)
        self.assertEqual(r.found, ["/" + APP_SUPPORT])
        self.assertEqual(r.unconfirmed, ["/" + APP_SUPPORT])
        self.assertIn("/" + APP_SUPPORT, r.reason())
        self.assertIn("還不能確認", r.reason())
        self.assertNotIn("存在管理員政策", r.reason())
        self.make("etc/antigravity", directory=True)
        r = self.agy(AGY_156)
        self.assertEqual(r.found, ["/etc/antigravity", "/" + APP_SUPPORT])
        self.assertEqual(r.unconfirmed, ["/" + APP_SUPPORT])
        self.assertIn("存在管理員政策或系統設定：/etc/antigravity", r.reason())
        self.assertIn("還不能確認", r.reason())
        self._cleanup()
        self.root.mkdir(parents=True)
        self.make("etc/antigravity", directory=True)
        r = self.agy(AGY)
        self.assertEqual((r.unconfirmed, r.reason()), ([], "存在管理員政策或系統設定：/etc/antigravity。請使用者或系統管理員處理後再啟動。"))

    def test_1_5_6_cannot_start_when_the_new_place_cannot_be_looked_at(self):
        support = self.make("Library/Application Support", directory=True)
        support.chmod(0o000)
        r = self.agy(AGY_156)
        support.chmod(0o755)
        self.assertFalse(r.ok)
        self.assertTrue(r.problems)
        self.assertIn("無法確認", r.problems[0])
        self.assertTrue(self.agy(AGY_156).ok)

    def test_1_5_6_keeps_every_source_of_1_5_3(self):
        for rel, directory in (("etc/antigravity", True), ("etc/antigravity/admin_settings.json", False),
                               (f"{PREFS}/com.google.antigravity.plist", False), (f"{PREFS}/alice/com.google.antigravity.plist", False)):
            with self.subTest(source=rel):
                self._cleanup()
                self.root.mkdir(parents=True)
                self.make(rel, directory=directory)
                self.assertFalse(self.agy(AGY_156).ok)

    def test_a_clean_root_passes_and_other_vendors_do_not_matter(self):
        self.assertTrue(self.agy().ok)
        self.make("etc/codex", directory=True)
        self.make("Library/Application Support/Antigravity/file")        # an unexplained fragment in the strings: not a source
        self.make(f"{PREFS}/com.example.other.plist")
        self.make(f"{PREFS}/alice/com.example.other.plist")
        self.assertTrue(self.agy().ok)

    def test_any_known_source_refuses_without_reading_it(self):
        cases = [
            ("etc/antigravity", True),
            ("etc/antigravity/admin_settings.json", False),
            ("etc/antigravity/anything-a-later-version-adds.json", False),
            (f"{PREFS}/com.google.antigravity.plist", False),
            (f"{PREFS}/alice/com.google.antigravity.plist", False),
        ]
        for rel, directory in cases:
            with self.subTest(source=rel):
                self._cleanup()
                self.root.mkdir(parents=True)
                p = self.make(rel, directory=directory)
                if not directory:
                    p.chmod(0o000)                                       # unreadable: still found by lstat
                r = self.agy()
                self.assertFalse(r.ok)
                self.assertTrue(r.found)
                self.assertIn("管理員", r.reason())

    def test_a_dangling_link_or_an_empty_file_is_a_source_too(self):
        (self.root / "etc").mkdir()
        (self.root / "etc/antigravity").symlink_to("/nonexistent-target")
        self.assertFalse(self.agy().ok)
        (self.root / "etc/antigravity").unlink()
        (self.root / "etc/antigravity").write_text("")
        self.assertFalse(self.agy().ok)

    def test_cannot_establish_refuses(self):
        etc = self.make("etc", directory=True)
        etc.chmod(0o000)
        r = self.agy()
        self.assertFalse(r.ok)
        self.assertTrue(r.problems)
        self.assertIn("無法確認", r.problems[0])
        etc.chmod(0o755)
        prefs = self.make(PREFS, directory=True)
        prefs.chmod(0o000)
        self.assertFalse(self.agy().ok)                                   # cannot list the managed preferences
        prefs.chmod(0o755)
        self.assertTrue(self.agy().ok)

    def test_managed_preferences_oddities_refuse(self):
        prefs = self.make(PREFS, directory=True)
        (prefs / "alice").symlink_to(self.root)
        self.assertFalse(self.agy().ok)
        (prefs / "alice").unlink()
        shutil.rmtree(prefs)
        (self.root / PREFS).write_text("")                                # not a directory
        self.assertFalse(self.agy().ok)

    def test_a_version_without_a_list_cannot_start(self):
        for version in ("1.5.2", "1.5.4", "2.0.0", "", None, 2, ["1.5.3"]):
            with self.subTest(version=version):
                r = ap.check_agy(version, str(self.root))
                self.assertFalse(r.ok)
                self.assertIn("清單", r.reason())
                self.assertIn("AGY", r.reason())

    def test_it_never_raises(self):
        with mock.patch.object(ap, "_check", side_effect=RuntimeError("boom")):
            r = self.agy()
        self.assertFalse(r.ok)
        self.assertTrue(r.problems)

    def test_the_other_tools_lists_are_unchanged(self):
        self.assertEqual(set(ap.CODEX_SOURCES), {"0.160.0", "0.163.0", "0.167.0"})            # (0.167.0: v0.22.1, the same list as 0.163.0's)
        self.assertEqual(tuple(ap.CODEX_SOURCES["0.163.0"]["paths"]), ("etc/codex",))
        self.assertNotIn(AGY, ap.CLAUDE_SOURCES)


if __name__ == "__main__":
    unittest.main()
