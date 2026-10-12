"""Administrator policy and system config layers (vbear/admin_policy.py,
design 2.1 and 5.2). Every check runs against a temporary root and a
temporary home; the real /Library, /etc and ~/.claude are never looked at."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import admin_policy as ap

CLAUDE = "2.1.292"
CODEX = "0.160.0"
PREFS = "Library/Managed Preferences"


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbap-")))
        self.home = self.root / "Users" / "someone"
        self.home.mkdir(parents=True)
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

    def claude(self):
        return ap.check_claude(CLAUDE, str(self.root), str(self.home))

    def codex(self):
        return ap.check_codex(CODEX, str(self.root))

    def test_clean_root_passes(self):
        self.assertTrue(self.claude().ok)
        self.assertTrue(self.codex().ok)
        self.make("Library/Application Support/Other/file")       # other vendors do not matter
        self.make(f"{PREFS}/com.example.other.plist")
        self.make(f"{PREFS}/alice/com.example.other.plist")
        self.assertTrue(self.claude().ok)
        self.assertTrue(self.codex().ok)

    def test_any_known_source_refuses_without_reading_it(self):
        cases = [
            ("claude", "Library/Application Support/ClaudeCode", True),
            ("claude", "Library/Application Support/ClaudeCode/managed-settings.json", False),
            ("claude", "Library/Application Support/ClaudeCode/managed-settings.d/a.json", False),
            ("claude", "Library/Application Support/ClaudeCode/managed-mcp.json", False),
            ("claude", f"{PREFS}/com.anthropic.claudecode.plist", False),
            ("claude", f"{PREFS}/alice/com.anthropic.claudecode.plist", False),
            ("codex", "etc/codex", True),
            ("codex", "etc/codex/managed_config.toml", False),
            ("codex", "etc/codex/requirements.toml", False),
            ("codex", "etc/codex/config.toml", False),
            ("codex", f"{PREFS}/com.openai.codex.plist", False),
            ("codex", f"{PREFS}/bob/com.openai.codex.plist", False),
        ]
        for tool, rel, directory in cases:
            with self.subTest(tool=tool, source=rel):
                self._cleanup()
                self.home.mkdir(parents=True)
                p = self.make(rel, directory=directory)
                p.chmod(0o000) if not directory else None              # unreadable: still found by lstat
                r = self.claude() if tool == "claude" else self.codex()
                self.assertFalse(r.ok)
                self.assertTrue(r.found)
                self.assertIn("/", r.found[0])
                self.assertIn("管理員", r.reason())
                other = self.codex() if tool == "claude" else self.claude()
                self.assertTrue(other.ok, "one tool's source does not block the other")

    def test_a_symlink_or_empty_file_is_a_source_too(self):
        (self.root / "Library/Application Support").mkdir(parents=True)
        (self.root / "Library/Application Support/ClaudeCode").symlink_to("/nonexistent-target")
        self.assertFalse(self.claude().ok)                        # dangling symlink still exists
        (self.root / "etc").mkdir()
        (self.root / "etc/codex").write_text("")
        self.assertFalse(self.codex().ok)

    def test_cannot_establish_refuses(self):
        support = self.make("Library/Application Support", directory=True)
        support.chmod(0o000)
        r = self.claude()
        self.assertFalse(r.ok)
        self.assertFalse(r.found)
        self.assertTrue(r.problems)
        self.assertIn("無法確認", r.problems[0])
        support.chmod(0o755)
        prefs = self.make(PREFS, directory=True)
        prefs.chmod(0o000)
        self.assertFalse(self.codex().ok)                         # cannot list the managed preferences
        prefs.chmod(0o755)
        self.assertTrue(self.codex().ok)

    def test_managed_preferences_oddities_refuse(self):
        prefs = self.make(PREFS, directory=True)
        (prefs / "alice").symlink_to(self.root)                    # a per-user entry that is a symlink
        self.assertFalse(self.claude().ok)
        (prefs / "alice").unlink()
        shutil.rmtree(prefs)
        (self.root / PREFS).symlink_to(self.root)                  # the directory itself
        self.assertFalse(self.codex().ok)
        (self.root / PREFS).unlink()
        (self.root / PREFS).write_text("")                         # not a directory
        self.assertFalse(self.claude().ok)

    def test_too_many_entries_refuse(self):
        prefs = self.make(PREFS, directory=True)
        for i in range(5):
            (prefs / f"u{i}").mkdir()
        with mock.patch.object(ap, "MANAGED_PREFS_MAX_ENTRIES", 3):
            self.assertFalse(self.claude().ok)
        self.assertTrue(self.claude().ok)

    def test_unknown_versions_cannot_launch(self):
        for version in ("2.1.291", "2.1.286", "9.9.9", "", None, 2, ["2.1.292"]):
            with self.subTest(version=version):
                r = ap.check_claude(version, str(self.root), str(self.home))
                self.assertFalse(r.ok)
                self.assertIn("清單", r.reason())
        self.assertFalse(ap.check_codex("0.159.2", str(self.root)).ok)

    def test_server_managed_settings_cache_refuses(self):
        cache = self.home / ".claude" / "remote-settings.json"
        cache.parent.mkdir()
        self.assertTrue(self.claude().ok)
        for kind in ("file", "empty", "symlink", "directory"):
            with self.subTest(kind=kind):
                if kind == "file":
                    cache.write_text('{"env": {}}')
                elif kind == "empty":
                    cache.write_text("")
                elif kind == "symlink":
                    cache.symlink_to("/nonexistent")
                else:
                    cache.mkdir()
                r = self.claude()
                self.assertFalse(r.ok)
                self.assertEqual(r.found, ["~/.claude/remote-settings.json"])
                self.assertTrue(self.codex().ok, "the cache is a Claude Code source only")
                cache.rmdir() if kind == "directory" else cache.unlink()
        self.assertTrue(self.claude().ok)

    def test_server_managed_settings_cache_cannot_be_established(self):
        claude_dir = self.home / ".claude"
        claude_dir.mkdir()
        claude_dir.chmod(0o000)
        r = self.claude()
        self.assertFalse(r.ok)
        self.assertIn("~/.claude/remote-settings.json", r.problems[0])
        claude_dir.chmod(0o700)
        claude_dir.rmdir()
        claude_dir.write_text("")                                  # .claude is a file: ENOTDIR
        self.assertFalse(self.claude().ok)
        for home in ("", "relative/home", 5):
            with self.subTest(home=home):
                self.assertFalse(ap.check_claude(CLAUDE, str(self.root), home).ok)

    def test_a_parent_that_is_a_file_refuses(self):
        # Codex S2a-1 #1: ENOTDIR leaves existence open; it used to read as absent.
        for rel in ("etc", "Library", "Library/Application Support", "Library/Managed Preferences"):
            with self.subTest(parent=rel):
                self._cleanup()
                self.home.mkdir(parents=True)
                self.make(rel)
                tool_results = {"claude": self.claude(), "codex": self.codex()}
                if rel == "etc":
                    self.assertFalse(tool_results["codex"].ok)
                    self.assertTrue(tool_results["codex"].problems)
                else:
                    self.assertFalse(tool_results["claude"].ok)
                    self.assertTrue(tool_results["claude"].problems)
                if rel in ("Library", "Library/Managed Preferences"):
                    self.assertFalse(tool_results["codex"].ok, "the managed preferences are shared")
                elif rel == "Library/Application Support":
                    self.assertTrue(tool_results["codex"].ok, "Codex does not read Application Support")

    def test_never_raises(self):
        with mock.patch.object(ap, "_check", side_effect=RuntimeError("boom")):
            self.assertFalse(self.claude().ok)
            self.assertFalse(self.codex().ok)

    def test_source_lists_are_the_reviewed_constants(self):
        claude = {"paths": ("Library/Application Support/ClaudeCode",), "domain": "com.anthropic.claudecode",
                  "home_paths": (".claude/remote-settings.json",)}
        self.assertEqual(ap.CLAUDE_SOURCES, {"2.1.292": claude, "2.1.296": claude})
        self.assertEqual(ap.CODEX_SOURCES, {"0.160.0": {"paths": ("etc/codex",), "domain": "com.openai.codex",
                                                        "home_paths": ()}})


if __name__ == "__main__":
    unittest.main()
