"""P25: an App-launched VBear finds Claude Code installed under ~/.local/bin.

The App starts Python with a fixed PATH. Every lookup of `claude` goes through one
definition (daemon.extra_path); these tests use fake executables in a fake HOME only."""
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vbear import translations as tr
from vbear.runtime import cli_versions, daemon, review_codex

APP_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ROOT = Path(__file__).resolve().parent.parent


class FakeHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-p25-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve() / "home"
        self.bin = self.home / ".local" / "bin"
        self.bin.mkdir(parents=True)
        self.vbear_home = self.home / ".vbear"
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "PATH": APP_PATH,
                                               "VBEAR_HOME": str(self.vbear_home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_claude(self, text="2.1.296 (Claude Code)"):
        path = self.bin / "claude"
        path.write_text(f"#!{sys.executable}\nprint({text!r})\n", encoding="utf-8")
        path.chmod(0o700)
        return path


class CentralDefinition(FakeHome):
    def test_extra_path_ends_with_local_bin_and_keeps_system_order(self):
        extra = daemon.extra_path(str(self.home))
        self.assertEqual(extra, ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
                                 str(self.bin)))

    def test_extra_path_refuses_a_home_that_is_not_a_plain_absolute_directory_name(self):
        for bad in ("", "relative/home", "/tmp/a:b", "/tmp/a\0b"):
            with self.subTest(home=bad):
                self.assertNotIn(".local/bin", " ".join(daemon.extra_path(bad)))

    def test_build_env_appends_after_the_apps_fixed_path(self):
        env = daemon.build_env()
        self.assertEqual(env["PATH"], APP_PATH + ":" + str(self.bin))

    def test_build_env_keeps_the_users_own_order_and_does_not_duplicate(self):
        mine = f"/mine/bin:{self.bin}:/usr/bin"
        env = daemon.build_env({"PATH": mine})
        parts = env["PATH"].split(":")
        self.assertEqual(parts[:3], ["/mine/bin", str(self.bin), "/usr/bin"])
        self.assertEqual(parts.count(str(self.bin)), 1)

    def test_review_environment_does_not_gain_the_user_bin(self):
        env = review_codex.build_env("/state/codex-home", "/state/run-home")
        self.assertNotIn(str(self.bin), env["PATH"].split(":"))

    def test_swift_launcher_path_matches_the_python_definition(self):
        text = (ROOT / "macos" / "VBear" / "main.swift").read_text(encoding="utf-8")
        match = re.search(r'var path = "([^"]+)"', text)
        self.assertIsNotNone(match, "pythonEnvironment must build PATH in a variable")
        self.assertEqual(match.group(1), APP_PATH)
        self.assertIn('path += ":" + home + "/.local/bin"', text)
        self.assertIn('child["PATH"] = path', text)
        self.assertNotIn('child["PATH"] = "/opt/homebrew', text)
        self.assertEqual(daemon.build_env()["PATH"], match.group(1) + ":" + str(self.bin))


class TranslationLookup(FakeHome):
    def test_claude_under_local_bin_is_found_with_the_apps_path(self):
        claude = self.fake_claude()
        self.assertEqual(tr.claude_identity(), (str(claude), "2.1.296"))

    def test_missing_claude_is_cli_not_found_not_an_unverified_boundary(self):
        with self.assertRaises(tr.TranslationError) as cm:
            tr.claude_identity()
        self.assertEqual(cm.exception.code, "cli_not_found")
        text = tr.ERRORS["cli_not_found"]
        self.assertIn("找不到 Claude Code", text)
        self.assertIn(".local/bin", text)
        self.assertNotIn("還沒驗證", text)
        for call in (lambda: tr.resolve_provider("claude"), lambda: tr._verify_boundary("claude")):
            with self.assertRaises(tr.TranslationError) as cm:
                call()
            self.assertEqual(cm.exception.code, "cli_not_found")

    def test_unreadable_version_is_still_an_unverified_boundary(self):
        self.fake_claude("not a version")
        with self.assertRaises(tr.TranslationError) as cm:
            tr.claude_identity()
        self.assertEqual(cm.exception.code, "boundary_unverified")

    def test_codex_message_is_unchanged(self):
        with self.assertRaises(tr.TranslationError) as cm:
            tr.resolve_provider("codex")
        self.assertEqual(cm.exception.code, "boundary_unverified")
        self.assertEqual(tr.ERRORS["boundary_unverified"],
                         "這個 Claude Code 版本的翻譯安全邊界還沒驗證；Codex 翻譯仍未開放")

    def test_a_found_but_unverified_claude_still_needs_verification(self):
        self.fake_claude()
        with self.assertRaises(tr.TranslationError) as cm:
            tr.resolve_provider("claude")
        self.assertEqual(cm.exception.code, "boundary_unverified")

    def test_batch_stops_on_cli_not_found(self):
        source = (ROOT / "vbear" / "translations.py").read_text(encoding="utf-8")
        self.assertRegex(source, r'if code in \([^)]*"cli_not_found"[^)]*\):\s*\n\s*break')


class VersionCheckLookup(FakeHome):
    def test_launch_version_check_finds_claude_under_local_bin(self):
        claude = self.fake_claude("2.1.296 (Claude Code)")
        # The fake prints its version for any argv; the real launch check passes --safe-mode.
        result = cli_versions.check_cli_version("claude", None, cwd=str(self.home), allow_unverified=True)
        self.assertNotEqual(result.error_code, "binary_not_found", result.as_dict())
        self.assertEqual(result.binary_path, str(claude))
        self.assertEqual(result.observed_version, "2.1.296")

    def test_without_claude_the_version_check_still_says_not_found(self):
        result = cli_versions.check_cli_version("claude", None, cwd=str(self.home), allow_unverified=True)
        self.assertEqual(result.error_code, "binary_not_found")

    def test_daemon_resolves_a_plain_claude_command_for_a_session(self):
        claude = self.fake_claude()
        env = daemon.build_env()
        self.assertEqual(daemon._resolve("claude", str(self.home), env["PATH"]), str(claude))


if __name__ == "__main__":
    unittest.main()
