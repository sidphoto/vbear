"""tools/review_daemon_probe.py against the stand-in Codex of
test_runtimed_review: the tool itself keeps working until the real run. No
Codex, no model, no login; a synthetic auth.json."""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_runtimed_review import FAKE_CODEX, REPO


class ProbeToolTests(unittest.TestCase):
    def test_the_probe_runs_a_whole_review_and_leaves_only_the_codex_home(self):
        root = Path(tempfile.mkdtemp(prefix="vbp-", dir="/private/tmp"))      # a short path: the socket lives in the state
        self.addCleanup(shutil.rmtree, root, True)
        state, out = root / "state", root / "out"
        (state / "codex-home").mkdir(parents=True, mode=0o700)
        os.chmod(state, 0o700)
        auth = state / "codex-home" / "auth.json"
        auth.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": "acct-secret-0001"}}))
        os.chmod(auth, 0o600)
        arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        bindir = root / "home/.codex/packages/standalone/releases" / f"0.160.0-{arch}-apple-darwin" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "codex").write_text(FAKE_CODEX % {"py": sys.executable, "repo": REPO})
        (bindir / "codex").chmod(0o700)
        run = subprocess.run([sys.executable, str(Path(REPO) / "tools/review_daemon_probe.py"), "--state", str(state),
                              "--out", str(out), "--home", str(root / "home")], capture_output=True, text=True,
                             timeout=300)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        report = json.loads((out / "review-probe-report.json").read_text())
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["review"]["outcome"], "valid")
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["cleanup_errors"], [])
        self.assertEqual(os.listdir(state), ["codex-home"])                      # everything else it made is gone
        self.assertEqual(auth.read_text().count("acct-secret-0001"), 1)         # the login file is untouched
        for p in out.iterdir():                                                  # no account identifier in what it kept
            self.assertNotIn("acct-secret-0001", p.read_text())
        obs = report["observed"]
        self.assertIn("turn.completed", obs["events"]["sequence"])
        self.assertIn("session_meta", obs["rollout"]["record_types"])
        self.assertEqual(report["codex_mcp_list"]["stdout"].strip(), "[]")

    def test_without_a_login_it_stops_before_doing_anything(self):
        root = Path(tempfile.mkdtemp(prefix="vbp-", dir="/private/tmp"))
        self.addCleanup(shutil.rmtree, root, True)
        state = root / "state"
        (state / "codex-home").mkdir(parents=True, mode=0o700)
        run = subprocess.run([sys.executable, str(Path(REPO) / "tools/review_daemon_probe.py"), "--state", str(state),
                              "--out", str(root / "out")], capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 1)
        report = json.loads((root / "out" / "review-probe-report.json").read_text())
        self.assertIn("not logged in", report["error"])
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(os.listdir(state), ["codex-home"])


if __name__ == "__main__":
    unittest.main()
