"""The 「驗證這個版本」 job: runs the boundary check twice and records a pass."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import claude_verify
from vbear.runtime import cli_versions


class ClaudeVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "st"
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def fake_runs(self, results):
        """Stand-in for the child process: writes a report and exits as told."""
        calls = []

        def run(argv, **kw):
            mode = argv[argv.index("--mode") + 1]
            out = Path(argv[argv.index("--out") + 1])
            ok = results[mode]
            checks = {"own_work_write": {"pass": True}, "tcp_internet": {"pass": ok}}
            out.write_text(json.dumps({"claude_version": "2.1.299", "passed": ok, "checks": checks}))
            calls.append(mode)
            return mock.Mock(returncode=0 if ok else 1)
        return run, calls

    def run_job(self, results):
        run, calls = self.fake_runs(results)
        v = claude_verify.ClaudeVerifier()
        with mock.patch("subprocess.run", side_effect=run):
            v.start("/x/claude", "2.1.299")
            for _ in range(100):
                if not v.status()["running"]:
                    break
                time.sleep(0.02)
        return v.status(), calls

    def test_both_modes_pass_records_the_version(self):
        status, calls = self.run_job({"headless": True, "interactive": True})
        self.assertEqual((status["result"], calls), ("passed", ["headless", "interactive"]))
        self.assertIn("2.1.299", cli_versions.local_verified_versions())
        self.assertIn("2.1.299", cli_versions.verified_versions("claude"))
        path = self.home / cli_versions.LOCAL_VERIFIED_FILE
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_a_failure_records_nothing_and_names_the_check(self):
        status, calls = self.run_job({"headless": False, "interactive": True})
        self.assertEqual((status["result"], calls), ("failed", ["headless"]))
        self.assertEqual(status["failed"], ["tcp_internet"])
        self.assertEqual(cli_versions.local_verified_versions(), {})

    def test_interactive_failure_after_headless_pass_records_nothing(self):
        status, _ = self.run_job({"headless": True, "interactive": False})
        self.assertEqual(status["result"], "failed")
        self.assertEqual(cli_versions.local_verified_versions(), {})

    def test_only_one_job_at_a_time(self):
        v = claude_verify.ClaudeVerifier()
        v._state = {"running": True, "version": "2.1.299"}
        with mock.patch("threading.Thread") as thread:
            self.assertTrue(v.start("/x/claude", "2.1.300")["running"])
            thread.assert_not_called()

    def test_record_keeps_other_versions_and_ignores_garbage(self):
        claude_verify.record_pass("2.1.299", "/x", {"interactive": "r1"})
        claude_verify.record_pass("2.1.300", "/x", {"interactive": "r2"})
        self.assertEqual(sorted(cli_versions.local_verified_versions()), ["2.1.299", "2.1.300"])
        (self.home / cli_versions.LOCAL_VERIFIED_FILE).write_text("not json")
        self.assertEqual(cli_versions.local_verified_versions(), {})
        self.assertNotIn("2.1.299", cli_versions.verified_versions("claude"))
        self.assertEqual(cli_versions.verified_versions("codex"), ("0.159.2",))  # never local


if __name__ == "__main__":
    unittest.main()
