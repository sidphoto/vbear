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

    def test_probe_result_is_bounded_strict_json_with_exact_schema(self):
        path = self.tmp / "probe-result.json"
        good = {name: {"allowed": True} for name in stream_check.EXPECT}
        good["tmpdir_is_own_scratch"]["detail"] = "/private/tmp/sc-test/"
        path.write_text(json.dumps(good))
        self.assertEqual(stream_check.read_probe_result(path), good)

        path.write_text(json.dumps({**good, "unexpected": {"allowed": True}}))
        self.assertEqual(stream_check.read_probe_result(path), {})
        path.write_text('{"own_work_write":{"allowed":true,"allowed":false}}')
        self.assertEqual(stream_check.read_probe_result(path), {})
        path.unlink()
        outside = self.tmp / "outside-result.json"
        outside.write_text(json.dumps(good))
        path.symlink_to(outside)
        self.assertEqual(stream_check.read_probe_result(path), {})

    def test_run_against_the_fake(self):
        out = self.tmp / "report.json"
        private = self.tmp / "t"                                        # this test's own temp root
        private.mkdir()
        code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out),
                                tmp_root=str(private))
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
        # Only what this run used: other test runs on the machine (another
        # worktree, a reviewer) create and remove their own sc-* meanwhile.
        self.assertEqual(os.listdir(private), [])
        root, scratch = report["temp_paths"]
        self.assertEqual(Path(root).parent, private)
        self.assertTrue(Path(scratch).name.startswith("sc-"))
        self.assertFalse(stream_check.present(root) or stream_check.present(scratch))
        self.assertEqual(report["checks"]["cleanup"], {"pass": True, "left": [], "errors": []})

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
        private = self.tmp / "t"
        private.mkdir()
        with mock.patch("vbear.stream_check.shutil.rmtree", rmtree), \
                mock.patch("vbear.stream_check.tempfile.mkdtemp", mkdtemp):
            code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out),
                                    tmp_root=str(private))
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
        private = self.tmp / "t"
        private.mkdir()
        with mock.patch.object(stream_check, "_run", all_pass), \
                mock.patch.object(stream_check, "remove_tree"):         # a removal that silently did nothing
            code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out),
                                    tmp_root=str(private))
        report = json.loads(out.read_text())
        self.assertEqual((code, report["passed"], report["checks"]["cleanup"]["pass"]), (1, False, False))
        self.assertEqual([p.name.startswith("vbp-") for p in private.iterdir()], [True])   # left, and only here

    def test_the_endpoint_pin_needs_the_control_to_connect(self):
        # Review B3: without a control connection nothing shows the project
        # file was read, so the pin is not proven.
        self.assertTrue(stream_check.endpoint_pinned(0, 7, True))
        self.assertFalse(stream_check.endpoint_pinned(0, 0, True))       # control never connected
        self.assertFalse(stream_check.endpoint_pinned(1, 7, True))       # the run itself connected
        self.assertFalse(stream_check.endpoint_pinned(0, 7, False))
        out = self.tmp / "report.json"
        private = self.tmp / "t"
        private.mkdir()
        stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out), tmp_root=str(private))
        pin = json.loads(out.read_text())["checks"]["endpoint_pin"]
        self.assertEqual((pin["connections"], pin["control_connections"], pin["pass"]), (0, 0, False))

    def test_a_failure_creating_the_state_still_removes_the_root(self):
        # Review B4.
        out = self.tmp / "report.json"
        private = self.tmp / "t"
        private.mkdir()
        real = Path.mkdir

        def mkdir(path, *args, **kw):
            if path.name == "st":
                raise OSError(28, "No space left on device")
            return real(path, *args, **kw)
        with mock.patch.object(Path, "mkdir", mkdir):
            code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out),
                                    tmp_root=str(private))
        report = json.loads(out.read_text())
        self.assertEqual((code, report["passed"]), (2, False))
        self.assertIn("No space left", report["error"])
        self.assertEqual(os.listdir(private), [])

    def test_the_probe_never_signals_after_reaping(self):
        # Review round 4 #2: signals only to a verified, unreaped leader's
        # group; reaped only when the group is proven empty; nothing after.
        from vbear.runtime import stream_session
        events = []
        real_killpg, real_waitpid = os.killpg, os.waitpid

        def killpg(pgid, sig):
            events.append(("signal", pgid))
            return real_killpg(pgid, sig)

        def waitpid(pid, opts):
            events.append(("reap", pid))
            return real_waitpid(pid, opts)
        out = self.tmp / "report.json"
        private = self.tmp / "t"
        private.mkdir()
        import subprocess
        real_popen, leaders = subprocess.Popen, []

        def popen(argv, *args, **kw):
            proc = real_popen(argv, *args, **kw)
            if "--session-id" in argv:                                   # the stream CLI, not the control
                leaders.append(proc.pid)
            return proc
        with mock.patch.object(stream_session.os, "killpg", killpg), \
                mock.patch.object(stream_session.os, "waitpid", waitpid), \
                mock.patch.object(stream_check.subprocess, "Popen", popen):
            stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out),
                             tmp_root=str(private))
        report = json.loads(out.read_text())
        self.assertEqual(report["checks"]["process"], {"pass": True, "problem": None})
        pid, = leaders
        mine = [e for e in events if e[1] == pid]
        self.assertEqual([e for e in mine if e[0] == "reap"], [("reap", pid)])     # reaped once
        self.assertEqual(mine[-1], ("reap", pid))                                  # nothing after it

    def test_a_group_not_proven_gone_keeps_everything_for_review(self):
        # Review round 5 B-2: no removal, no second attempt, no signal; the
        # Popen object is held so nothing reaps the leader.
        from vbear.runtime import stream_session
        out = self.tmp / "report.json"
        private = self.tmp / "t"
        private.mkdir()
        held_before = len(stream_check._HELD)
        with mock.patch.object(stream_session, "end_spawned", return_value="群組仍有程序（test）") as end, \
                mock.patch.object(stream_session.os, "killpg") as killpg:
            code = stream_check.run(str(self.binary), "2.1.292", "claude-haiku-4-5-20251001", str(out),
                                    tmp_root=str(private))
        report = json.loads(out.read_text())
        self.assertEqual(end.call_count, 1)
        killpg.assert_not_called()
        self.assertNotEqual(code, 0)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"]["process"], {"pass": False, "problem": "群組仍有程序（test）"})
        root, scratch = report["kept_for_review"]
        self.assertTrue(os.path.isdir(root) and os.path.isdir(scratch))       # left for a person
        self.assertEqual(report["checks"]["cleanup"]["kept_for_review"], [root, scratch])
        self.assertEqual(len(stream_check._HELD), held_before + 1)
        proc = stream_check._HELD.pop()                                    # the test is the person here
        proc.wait()
        shutil.rmtree(root)
        shutil.rmtree(scratch)

    def test_a_reaped_leader_is_never_signalled(self):
        import subprocess
        from vbear.runtime import stream_session
        proc = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True)
        start = stream_session.capture_leader(proc.pid)
        os.kill(proc.pid, 9)
        proc.wait()                                                      # reaped by someone else
        with mock.patch.object(stream_session.os, "killpg") as killpg:
            problem = stream_session.end_spawned(proc, start)
        killpg.assert_not_called()
        self.assertIn("不送訊號", problem)

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
