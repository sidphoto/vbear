"""The chat check (vbear/chat_check.py, ``boundary_check --mode chat``) against a fake Claude Code that decides from the
words of each message (tests/fake_chat_probe_cli.py): a well-behaved one passes and is recorded; one that breaks a
rule the check watches for fails that check and is not recorded. Synthetic HOME and state under /tmp; no model, no
network."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import admin_policy, boundary_check, chat_check, claude_verify, config as cfg
from vbear.runtime import chat_protocol as cp, chat_session, cli_versions
from tests import leftover

REPO = str(Path(__file__).resolve().parent.parent)
VERSION = "2.1.318"
LAUNCHER = ("#!%(py)s -I\nimport runpy, sys\nsys.path.insert(0, %(repo)r)\n"
            "runpy.run_module('tests.fake_chat_probe_cli', run_name='__main__')\n")


class CheckCase(unittest.TestCase):
    policy = None

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbk-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(leftover.assert_clean, self.tmp)             # the check's own daemon and employee are gone
        self.state = self.tmp / "st"
        self.state.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.work = self.tmp / "run"
        self.work.mkdir()
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        verified = mock.patch.object(cli_versions, "CHAT_VERIFIED_VERSIONS", ())
        verified.start()
        self.addCleanup(verified.stop)
        policy = mock.patch("vbear.admin_policy.check_claude",
                            side_effect=lambda version, home=None: self.policy or admin_policy.PolicyCheck(True))
        policy.start()
        self.addCleanup(policy.stop)
        self.binary = self.tmp / "claude"
        self.binary.write_text(LAUNCHER % {"py": sys.executable, "repo": REPO})
        self.binary.chmod(0o700)
        self.fake({})
        self.init_tracker, self.answer = cp.ChatTracker._on_system_init, chat_session.ChatProcess.answer

    def fake(self, conf):
        (self.home / "fake-probe.json").write_text(json.dumps(conf))

    def check(self, conf=None, *, version=VERSION, out=None):
        if conf is not None:
            self.fake(conf)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = chat_check.run(str(self.binary), version, "haiku", out or str(self.work / "report.json"),
                                  tmp_root=str(self.work))
        report = json.loads((Path(out) if out else self.work / "report.json").read_text())
        return code, report

    def verified(self):
        return cli_versions.chat_verified_versions()

    def assert_failed(self, code, report, name):
        self.assertNotEqual(code, 0, report.get("error"))
        self.assertFalse(report["passed"])
        if name:
            self.assertFalse(report["checks"][name]["pass"], report["checks"].get(name))
        self.assertEqual(self.verified(), (), "a failed check records nothing")
        self.assertFalse((self.state / cli_versions.LOCAL_CHAT_VERIFIED_FILE).exists())


class PassTests(CheckCase):
    def test_a_well_behaved_claude_code_passes_and_is_recorded(self):
        self.assertEqual(self.verified(), ())
        code, report = self.check()
        self.assertEqual((code, report["passed"], report.get("error")), (0, True, None), report)
        for name in ("admin_policy", "initialize", "instructions_arg", "partial_stream", "bash_asks", "modify_works",
                     "sandbox_confined", "tmp_dir_clean", "deny_works", "unknown_control_reply", "resume_memory",
                     "cost_cumulative", "resume_budget", "init_clean", "init_not_kept", "records_clean", "cleanup"):
            self.assertTrue(report["checks"][name]["pass"], (name, report["checks"][name]))
        self.assertEqual((report["mode"], report["claude_version"], report["model"]), ("chat", VERSION, "haiku"))
        self.assertEqual(self.verified(), (VERSION,))
        record = json.loads((self.state / cli_versions.LOCAL_CHAT_VERIFIED_FILE).read_text())["versions"][VERSION]
        self.assertEqual((record["passed"], record["report"]), (True, str(self.work / "report.json")))
        mode = stat.S_IMODE(os.stat(self.work / "report.json").st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(len(report["turns"]), 6)
        self.assertTrue(report["observations"]["instructions_followed"])
        budget = report["observations"]["resume_budget"]
        self.assertEqual((budget["budget_usd"], budget["informative"], budget["counts_previous"]), ("0.01", False, None))

    def test_the_check_leaves_nothing_behind_and_puts_the_process_back(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(os.environ["VBEAR_HOME"], str(self.state))
        self.assertIs(cp.ChatTracker._on_system_init, self.init_tracker)
        self.assertIs(chat_session.ChatProcess.answer, self.answer)
        self.assertEqual([p.name for p in self.work.iterdir()], ["report.json"], "its temporary state is gone")
        self.assertFalse([p for p in Path("/private/tmp").glob("sc-*") if p.name in json.dumps(report)])
        self.assertTrue(report["checks"]["cleanup"]["pass"])
        # the check's own state folder was not the person's: no chat of it is there
        self.assertFalse((self.state / "chats").exists())

    def test_nothing_of_the_initialize_answer_is_in_the_report(self):
        code, report = self.check()
        text = json.dumps(report, ensure_ascii=False)
        for secret in ("fictional.person", "fictional-command", "fictional-model", "Fictional Org"):
            self.assertNotIn(secret, text)

    def test_the_default_report_goes_to_the_verifications_folder(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = chat_check.run(str(self.binary), VERSION, None, None, tmp_root=str(self.work))
        self.assertEqual(code, 0)
        path = self.state / "verifications" / f"claude-{VERSION}-chat.json"
        self.assertEqual(json.loads(path.read_text())["model"], chat_check.CHAT_MODEL)
        self.assertEqual(self.verified(), (VERSION,))

    def test_a_report_that_is_changed_or_gone_stops_counting(self):
        self.assertEqual(self.check()[0], 0)
        report = self.work / "report.json"
        data = json.loads(report.read_text())
        data["passed"] = False
        report.write_text(json.dumps(data))
        report.chmod(0o600)
        self.assertEqual(self.verified(), ())
        report.unlink()
        self.assertEqual(self.verified(), ())

    def test_a_pass_keeps_the_versions_that_passed_before(self):
        path = self.state / cli_versions.LOCAL_CHAT_VERIFIED_FILE
        other = self.work / "other.json"
        other.write_text(json.dumps({"mode": "chat", "passed": True, "claude_version": "2.1.400"}))
        other.chmod(0o600)
        cfg.write_private(path, json.dumps({"versions": {"2.1.400": {
            "passed": True, "verified_at": "2026-11-05T00:00:00+0000", "report": str(other)}}}))
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.verified(), ("2.1.318", "2.1.400"))

    def test_instructions_not_followed_is_reported_but_does_not_fail_the_check(self):
        code, report = self.check({"instructions_honored": False})
        self.assertEqual(code, 0)
        self.assertFalse(report["observations"]["instructions_followed"])

    def test_a_budget_that_counts_what_was_spent_before_is_seen(self):
        code, report = self.check({"cost": 0.004, "budget_counts_previous": True})
        self.assertEqual(code, 0, report.get("error"))
        budget = report["observations"]["resume_budget"]
        self.assertEqual((budget["informative"], budget["counts_previous"], budget["subtype"]),
                         (True, True, "error_max_budget_usd"))
        self.assertTrue(report["checks"]["resume_budget"]["pass"])

    def test_a_budget_that_does_not_is_seen_too(self):
        code, report = self.check({"cost": 0.004})
        self.assertEqual(code, 0, report.get("error"))
        budget = report["observations"]["resume_budget"]
        self.assertEqual((budget["informative"], budget["counts_previous"], budget["subtype"]),
                         (True, False, "success"))


class FailTests(CheckCase):
    def test_a_bash_that_runs_without_asking_fails(self):
        code, report = self.check({"bash_asks": False})
        self.assert_failed(code, report, None)
        self.assertFalse(report["checks"].get("bash_asks", {"pass": False})["pass"])

    def test_a_denied_command_that_still_runs_fails(self):
        code, report = self.check({"deny_ignored": True})
        self.assert_failed(code, report, "deny_works")
        self.assertTrue(report["checks"]["deny_works"]["file_created"])

    def test_a_sandbox_that_lets_a_write_out_fails(self):
        code, report = self.check({"sandbox": "open"})
        self.assert_failed(code, report, "sandbox_confined")
        self.assertTrue(report["checks"]["sandbox_confined"]["outside_written"])

    def test_the_shared_tmp_error_fails(self):
        code, report = self.check({"tmp_error": True})
        self.assert_failed(code, report, "tmp_dir_clean")

    def test_the_extra_folders_of_the_persons_own_settings_do_not_reach_the_chat(self):
        """The real 2.1.318 names them in system/init unless ``--setting-sources ""`` is in the argv: the check passes
        because VBear's chat argv has it, and the log of the fake shows it."""
        code, report = self.check({"user_extra_dirs": ["/fictional/user-dir-1", "/fictional/user-dir-2"]})
        self.assertEqual((code, report["passed"], report.get("error")), (0, True, None), report)
        self.assertTrue(report["checks"]["init_clean"]["pass"])
        starts = [json.loads(x) for x in (self.home / "fake-probe-log.jsonl").read_text().splitlines()
                  if json.loads(x)["event"] == "start"]
        self.assertTrue(starts)
        for start in starts:
            i = start["argv"].index("--setting-sources")
            self.assertEqual(start["argv"][i + 1], "")

    def test_a_python_without_waitid_fails_before_anything_starts(self):
        before = set(self.work.iterdir())
        with mock.patch.object(chat_check.stream_session, "waitid_problem", return_value="這個 Python（3.9.6）沒有 os.waitid"):
            code, report = self.check()
        self.assertEqual((code, report["passed"]), (2, False))
        self.assertIn("os.waitid", report["error"])
        self.assertFalse((self.home / "fake-probe-log.jsonl").exists(), "no process was started")
        self.assertEqual(set(self.work.iterdir()) - before, {self.work / "report.json"}, "and no temporary folder was made")
        self.assertEqual(self.verified(), ())

    def test_extra_folders_in_the_init_event_fail(self):
        code, report = self.check({"extra_dirs": ["/fictional/extra"]})
        self.assert_failed(code, report, None)
        self.assertIn("額外資料夾", json.dumps(report, ensure_ascii=False))

    def test_a_resumed_session_that_forgot_fails(self):
        code, report = self.check({"remember": False})
        self.assert_failed(code, report, "resume_memory")

    def test_no_text_before_the_reply_is_whole_fails(self):
        code, report = self.check({"stream": False})
        self.assert_failed(code, report, "partial_stream")

    def test_a_total_that_goes_back_after_resume_fails(self):
        code, report = self.check({"cumulative": False})
        self.assert_failed(code, report, "cost_cumulative")

    def test_a_cli_that_cannot_take_the_error_reply_fails(self):
        code, report = self.check({"error_reply_fatal": True})
        self.assert_failed(code, report, None)
        self.assertFalse(report["checks"].get("unknown_control_reply", {"pass": False})["pass"])

    def test_another_version_than_the_one_named_fails(self):
        code, report = self.check({"version": "2.1.999"})
        self.assert_failed(code, report, None)

    def test_a_refused_initialize_fails(self):
        code, report = self.check({"init_error": True})
        self.assert_failed(code, report, None)

    def test_a_version_without_constants_is_not_checked(self):
        code, report = self.check(version="9.9.9")
        self.assertEqual(code, 2)
        self.assertIn("沒有聊天模式的常數", report["error"])
        self.assertFalse(report["passed"])
        self.assertEqual(self.verified(), ())
        self.assertFalse(list(Path(self.work).glob("vbc-*")), "no daemon, no temporary folder")

    def test_an_administrator_policy_stops_the_check_before_any_model_call(self):
        self.policy = admin_policy.PolicyCheck(False, found=["/Library/Application Support/ClaudeCode"])
        code, report = self.check()
        self.assert_failed(code, report, "admin_policy")
        self.assertIn("管理員政策", report["error"])
        self.assertFalse((self.home / "fake-probe-log.jsonl").exists(), "no process was started")

    def test_the_hooks_are_put_back_after_a_failure(self):
        self.check({"bash_asks": False})
        self.assertIs(cp.ChatTracker._on_system_init, self.init_tracker)
        self.assertIs(chat_session.ChatProcess.answer, self.answer)
        self.assertEqual(os.environ["VBEAR_HOME"], str(self.state))


class CommandTests(CheckCase):
    def test_boundary_check_takes_mode_chat(self):
        out = self.work / "cli-report.json"
        buf = io.StringIO()
        argv = ["boundary_check", "--mode", "chat", "--claude", str(self.binary), "--out", str(out)]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
            code = boundary_check.main()
        self.assertEqual(code, 0, buf.getvalue()[-500:])
        self.assertEqual(json.loads(out.read_text())["mode"], "chat")
        self.assertEqual(self.verified(), (VERSION,))
        printed = json.loads(buf.getvalue())
        self.assertEqual((printed["mode"], printed["passed"]), ("chat", True))

    def test_the_other_modes_keep_their_default_model(self):
        self.assertEqual(boundary_check.DEFAULT_MODEL, "claude-haiku-4-5-20251001")
        with mock.patch.object(sys, "argv", ["boundary_check", "--mode", "chat", "--help"]):
            with contextlib.redirect_stdout(io.StringIO()) as buf, self.assertRaises(SystemExit):
                boundary_check.main()
        self.assertIn("chat", buf.getvalue())


class VerifierTests(CheckCase):
    def run_verifier(self, rc, *, report=None, record=False):
        verifier = claude_verify.ChatVerifier()
        done = mock.Mock(returncode=rc, stdout="", stderr="")

        def fake_run(argv, **kw):
            self.assertEqual(argv[1:3], ["-B", "-m"])
            self.assertIn("--mode", argv)
            self.assertEqual(argv[argv.index("--mode") + 1], "chat")
            out = Path(argv[argv.index("--out") + 1])
            if report is not None:
                out.write_text(json.dumps(report))
                out.chmod(0o600)
            if record:
                cfg.write_private(self.state / cli_versions.LOCAL_CHAT_VERIFIED_FILE, json.dumps({"versions": {
                    VERSION: {"passed": True, "verified_at": "2026-11-05T00:00:00+0000", "report": str(out)}}}))
            return done
        with mock.patch.object(claude_verify.subprocess, "run", fake_run):
            verifier._run(str(self.binary), VERSION)
        return verifier.status()

    def test_a_pass_needs_the_version_to_be_on_the_list(self):
        ok = {"mode": "chat", "passed": True, "claude_version": VERSION}
        status = self.run_verifier(0, report=ok, record=True)
        self.assertEqual((status["running"], status["result"]), (False, "passed"), status)
        (self.state / cli_versions.LOCAL_CHAT_VERIFIED_FILE).unlink()
        status = self.run_verifier(0, report=ok, record=False)
        self.assertEqual(status["result"], "error")

    def test_a_failed_check_names_what_failed(self):
        report = {"mode": "chat", "passed": False, "claude_version": VERSION,
                  "checks": {"bash_asks": {"pass": False}, "init_clean": {"pass": True}}}
        status = self.run_verifier(1, report=report)
        self.assertEqual((status["result"], status["failed"]), ("failed", ["bash_asks"]))
        self.assertIn("bash_asks", status["message"])

    def test_a_check_that_did_not_finish_says_so(self):
        status = self.run_verifier(2)
        self.assertEqual(status["result"], "failed")
        self.assertIn("沒有完成", status["message"])


if __name__ == "__main__":
    unittest.main()
