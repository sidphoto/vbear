"""boundary_check --mode stream (vbear/stream_check.py) against the fake
stream CLI: no model is called, HOME is synthetic and the administrator
check runs against a temporary root. The fake does not run probe.py, so the
sandbox check fails here; the protocol path, the rapid second dispatch, the
report's privacy and the cleanup are what is checked."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_runtimed_stream import FAKE_STREAM_CLI, REPO
from vbear import admin_policy, stream_check

ACCOUNT = "11111111-2222-3333-4444-555555555555"
ORG = "66666666-7777-8888-9999-000000000000"


class StreamCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbsc-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "home").mkdir()
        (self.tmp / "home" / ".claude.json").write_text(json.dumps({"oauthAccount": {
            "accountUuid": ACCOUNT, "organizationUuid": ORG, "emailAddress": "someone@example.invalid"}}))
        (self.tmp / "root").mkdir()
        self.binary = self.tmp / "claude"
        self.binary.write_text(FAKE_STREAM_CLI % {"py": sys.executable, "repo": REPO})
        self.binary.chmod(0o700)
        env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home"), "VBEAR_HOME": str(self.tmp / "unused")})
        env.start()
        self.addCleanup(env.stop)
        real = admin_policy.check_claude
        p = mock.patch("vbear.stream_check.admin_policy.check_claude",
                       side_effect=lambda v, home=None: real(v, root=str(self.tmp / "root"), home=home))
        p.start()
        self.addCleanup(p.stop)

    def test_run_against_the_fake(self):
        out = self.tmp / "report.json"
        before = set(os.listdir("/private/tmp"))
        code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out))
        report = json.loads(out.read_text())
        checks = {k: v["pass"] for k, v in report["checks"].items()}
        self.assertEqual(code, 1)                                       # sandbox: the fake runs no probe
        self.assertEqual({k: checks[k] for k in ("protocol", "rapid_second", "admin_policy", "claude_json")},
                         {"protocol": True, "rapid_second": True, "admin_policy": True, "claude_json": True})
        self.assertFalse(checks["sandbox"])
        self.assertEqual([t["valid"] for t in report["turns"]], [True, True])
        self.assertEqual(report["live_model_responses"], 2)
        self.assertTrue(report["temp_removed"])
        self.assertIn("No such file", report["temp_ls"])
        text = out.read_text()
        for secret in (ACCOUNT, ORG, "someone@example.invalid"):
            self.assertNotIn(secret, text)                              # booleans only
        self.assertNotIn("hmac", text.lower())
        self.assertEqual(os.environ["VBEAR_HOME"], str(self.tmp / "unused"))   # restored
        leftovers = {n for n in set(os.listdir("/private/tmp")) - before if n.startswith(("vbp-", "sc-"))}
        self.assertEqual(leftovers, set())

    def test_a_failed_cleanup_fails_the_run(self):
        # Part 2 review B5: never ignore_errors; what is left fails the run.
        out = self.tmp / "report.json"
        real = shutil.rmtree

        def rmtree(path, *args, **kw):
            if os.path.basename(str(path)).startswith("vbp-"):
                raise PermissionError(13, "Permission denied", str(path))
            return real(path, *args, **kw)
        roots = []
        real_mkdtemp = tempfile.mkdtemp

        def mkdtemp(*args, **kw):
            roots.append(real_mkdtemp(*args, **kw))
            return roots[-1]
        with mock.patch("vbear.stream_check.shutil.rmtree", rmtree), \
                mock.patch("vbear.stream_check.tempfile.mkdtemp", mkdtemp):
            code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out))
        for r in roots:
            self.addCleanup(real, r, True)
        report = json.loads(out.read_text())
        self.assertNotEqual(code, 0)
        self.assertFalse(report["passed"])
        self.assertFalse(report["temp_removed"])
        self.assertFalse(report["checks"]["cleanup"]["pass"])
        self.assertTrue(report["checks"]["cleanup"]["errors"])

    def test_cleanup_alone_decides_a_run_that_otherwise_passed(self):
        out = self.tmp / "report.json"

        def all_pass(binary, version, model, consts, root, report):
            (root / "hmac-key").write_text("k")                  # left behind: no removal ran
            report["checks"] = {"protocol": {"pass": True}}
            report["passed"] = True
            return 0
        with mock.patch.object(stream_check, "_run", all_pass):
            code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out))
        report = json.loads(out.read_text())
        self.assertEqual((code, report["passed"], report["checks"]["cleanup"]["pass"]), (1, False, False))
        for r in Path("/private/tmp").glob("vbp-*"):
            if (r / "hmac-key").exists():
                shutil.rmtree(r)

    def test_remove_tree_lists_what_it_could_not_remove(self):
        locked = self.tmp / "locked"
        (locked / "inner").mkdir(parents=True)
        (locked / "inner" / "f").write_text("x")
        (locked / "inner").chmod(0o500)
        self.addCleanup((locked / "inner").chmod, 0o700)
        errors = []
        stream_check.remove_tree(locked, errors)
        self.assertTrue(errors)
        self.assertTrue(stream_check.present(locked / "inner" / "f"))

    def test_present_counts_errors_and_dangling_links(self):
        # R4 audit: Path.exists() misses a dangling link and reads EACCES as
        # absent; a leak or a leftover must not pass unseen.
        self.assertFalse(stream_check.present(self.tmp / "nothing"))
        (self.tmp / "dangling").symlink_to(self.tmp / "nothing")
        self.assertFalse((self.tmp / "dangling").exists())
        self.assertTrue(stream_check.present(self.tmp / "dangling"))
        with mock.patch("vbear.stream_check.os.lstat", side_effect=PermissionError(13, "Permission denied")):
            self.assertTrue(stream_check.present(self.tmp / "nothing"))

    def test_a_version_without_constants_is_refused(self):
        out = self.tmp / "report.json"
        self.assertEqual(stream_check.run(str(self.binary), "2.1.293", "claude-haiku-4-5-20251001", str(out)), 2)
        self.assertIn("常數", json.loads(out.read_text())["error"])


if __name__ == "__main__":
    unittest.main()
