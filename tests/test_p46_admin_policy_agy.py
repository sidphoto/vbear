"""P46-2: the administrator policy sources of AGY 1.5.3 (vbear/admin_policy.py). Every check runs against a temporary root; the real
/etc and /Library are never looked at, and no AGY is started."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import admin_policy as ap

AGY = "1.5.3"
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
        self.assertEqual(set(ap.AGY_SOURCES), {AGY})
        spec = ap.AGY_SOURCES[AGY]
        self.assertEqual(tuple(spec["paths"]), ("etc/antigravity",))
        self.assertEqual(spec["domain"], "com.google.antigravity")
        self.assertEqual(tuple(spec["home_paths"]), ())

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
        self.assertEqual(set(ap.CODEX_SOURCES), {"0.160.0", "0.163.0"})
        self.assertEqual(tuple(ap.CODEX_SOURCES["0.163.0"]["paths"]), ("etc/codex",))
        self.assertNotIn(AGY, ap.CLAUDE_SOURCES)


if __name__ == "__main__":
    unittest.main()
