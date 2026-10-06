"""One-time move of the pre-rename state directory (~/.sid-console -> ~/.vbear)."""

import fcntl
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import config as cfg


class LegacyStateDirMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {k: v for k, v in os.environ.items() if k not in ("VBEAR_HOME", "SID_CONSOLE_HOME")}
        patches = [mock.patch.dict(os.environ, env, clear=True),
                   mock.patch.object(Path, "home", return_value=self.home)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.legacy = self.home / ".sid-console"
        self.current = self.home / ".vbear"

    def tearDown(self):
        self.tmp.cleanup()

    def make_legacy(self):
        self.legacy.mkdir(mode=0o700)
        (self.legacy / "config.json").write_text('{"port": 7788}')
        return self.legacy

    def test_moves_once_and_keeps_contents(self):
        self.make_legacy()
        self.assertEqual(cfg.state_dir(), self.legacy)  # used in place until moved
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "moved")
        self.assertFalse(self.legacy.exists())
        self.assertEqual((self.current / "config.json").read_text(), '{"port": 7788}')
        self.assertEqual(cfg.state_dir(), self.current)
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "none")

    def test_never_merges_into_an_existing_new_directory(self):
        self.make_legacy()
        self.current.mkdir()
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "conflict")
        self.assertTrue((self.legacy / "config.json").exists())
        self.assertEqual(cfg.state_dir(), self.current)

    def test_kept_while_old_console_is_listening(self):
        self.make_legacy()
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: True), "kept:console_running")
        self.assertTrue(self.legacy.exists())

    def test_checks_the_port_the_old_console_was_configured_for(self):
        legacy = self.make_legacy()
        (legacy / "config.json").write_text('{"port": 7790}')
        seen = []
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: seen.append(port) or port == 7790),
                         "kept:console_running")
        self.assertEqual(seen, [7790])

    def test_rename_failure_keeps_the_old_directory_in_use(self):
        legacy = self.make_legacy()
        with mock.patch("os.rename", side_effect=PermissionError("denied")):
            self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "kept:rename_failed")
        self.assertEqual(cfg.state_dir(), legacy)

    def test_kept_while_a_runtime_holds_the_lock(self):
        legacy = self.make_legacy()
        fd = os.open(legacy / "runtimed.lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "kept:runtime_running")
        self.assertTrue(legacy.exists())
        self.assertFalse(self.current.exists())

    def test_kept_while_managed_launches_wait_for_cleanup(self):
        legacy = self.make_legacy()
        (legacy / "sessions" / "L1").mkdir(parents=True)
        self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "kept:managed_launches_pending")
        self.assertTrue(legacy.exists())

    def test_explicit_home_override_is_never_migrated(self):
        self.make_legacy()
        with mock.patch.dict(os.environ, {"SID_CONSOLE_HOME": str(self.legacy)}):
            self.assertEqual(cfg.state_dir(), self.legacy)  # old variable still honoured
            self.assertEqual(cfg.migrate_legacy_state_dir(lambda port: False), "none")
        self.assertTrue(self.legacy.exists())


if __name__ == "__main__":
    unittest.main()
