"""The Codex chat check (vbear/codex_chat_check.py, ``boundary_check --mode codex-chat``) against a fake Codex that does what
each message of the check asks (tests/fake_codex_check_server.py): a well-behaved one passes and is recorded; one that
breaks a rule the check watches for fails that check and is not recorded. Synthetic HOME and state under /tmp; no model,
no network, and the real codex is never run."""

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
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests import codex_chat_fixtures as ccf
from vbear import admin_policy, boundary_check, codex_chat_check as cc, config as cfg
from vbear.runtime import agent_sessions, cli_versions, codex_chat_protocol as ccp
from vbear.runtime import codex_chat_session as ccs

VERSION = "0.163.0"
THREAD = "00000000-0000-4000-8000-0000000000aa"
STEPS = ("stream", "ask", "edit", "patch", "outside", "interrupt", "memory")
ALL_CHECKS = ("admin_policy", "initialize", "mcp_empty", "home_no_config_at_start", "project_settings_sent", "stream_text", "ls_asks", "edit_steer", "edit_works",
              "deny_works", "patch_card", "outside_patch_refused", "interrupt_works", "resume_memory", "tokens_cumulative",
              "thread_deleted", "idle_close", "home_clean", "no_account_data", "records_clean", "cost_within_limit",
              "cleanup")


class CheckCase(unittest.TestCase):
    policy = None

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbk-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "st"
        self.state.mkdir(mode=0o700)
        self.chat_home = self.state / "codex-chat-home"
        self.chat_home.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        verified = mock.patch.object(cli_versions, "CODEX_CHAT_VERIFIED_VERSIONS", ())
        verified.start()
        self.addCleanup(verified.stop)
        policy = mock.patch("vbear.admin_policy.check_codex", side_effect=lambda version, root="/": self.policy or
                            admin_policy.PolicyCheck(True))
        policy.start()
        self.addCleanup(policy.stop)
        self.conf_path = self.home / "fake-codex.json"
        self.binary = Path(ccf.write_launcher(self.tmp / "codex", self.conf_path, "tests.fake_codex_check_server"))
        self.fake()
        self.hooks = (ccs.CodexChatProcess._on_fact, ccs.CodexChatProcess.tick)

    def fake(self, flags=None, **conf):
        base = {"version": VERSION, "login_status": 0, "clean": True, "thread_id": THREAD,
                "start": {"fixture": "a"}, "resume": {"fixture": "b-resume"}, "flags": flags or {}}
        base.update(conf)
        self.conf_path.write_text(json.dumps(base))

    def check(self, flags=None, *, version=VERSION, out=None, **conf):
        if flags is not None or conf:
            self.fake(flags, **conf)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.run(str(self.binary), version, out or str(self.out / "report.json"))
        report = json.loads((Path(out) if out else self.out / "report.json").read_text())
        return code, report

    def fake_log(self):
        path = Path(str(self.conf_path) + ".log.jsonl")
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def verified(self):
        return cli_versions.codex_chat_verified_versions()

    def assert_failed(self, code, report, name=None):
        self.assertNotEqual(code, 0, report.get("error"))
        self.assertFalse(report["passed"])
        if name:
            self.assertFalse(report["checks"][name]["pass"], report["checks"].get(name))
        self.assertEqual(self.verified(), (), "a failed check records nothing")
        self.assertFalse((self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE).exists())


class PassTests(CheckCase):
    def test_a_well_behaved_codex_passes_and_is_recorded(self):
        self.assertEqual(self.verified(), ())
        code, report = self.check()
        self.assertEqual((code, report["passed"], report.get("error")), (0, True, None), report)
        for name in ALL_CHECKS:
            self.assertTrue(report["checks"][name]["pass"], (name, report["checks"][name]))
        self.assertEqual((report["mode"], report["codex_version"]), ("codex-chat", VERSION))
        self.assertNotIn("claude_version", report)
        self.assertEqual(self.verified(), (VERSION,))
        record = json.loads((self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE).read_text())["versions"][VERSION]
        self.assertEqual((record["passed"], record["report"]), (True, str(self.out / "report.json")))
        self.assertEqual(stat.S_IMODE(os.stat(self.out / "report.json").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE).st_mode), 0o600)
        self.assertEqual(len(report["turns"]), len(STEPS))
        self.assertFalse((self.state / cli_versions.LOCAL_CHAT_VERIFIED_FILE).exists(), "Claude's record is another file")

    def test_what_it_made_each_step_is_in_the_report_and_the_spend_is_within_the_limit(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        obs = report["observations"]
        self.assertTrue(obs["instructions_followed"] in (True, False))
        self.assertEqual(obs["steer"], {"accepted": True, "failed_code": None, "fallback_turn": False})
        self.assertEqual(obs["unknown_request"].split("：")[0], "未觀察")
        total = sum(Decimal(t["cost_usd"]) for t in report["turns"])
        self.assertLessEqual(total, cc.TOTAL_USD)
        self.assertEqual(report["spent_usd"], str(total))
        for step in STEPS:
            self.assertIn(step, cc.STEP_CAP_USD)
            self.assertGreater(cc.STEP_CAP_USD[step], 0)
        self.assertLessEqual(max(cc.STEP_CAP_USD.values()), cc.TOTAL_USD)
        self.assertEqual(cc.TOTAL_USD, Decimal("0.30"))

    def test_every_allowance_is_for_the_command_or_file_it_asked_for_and_never_more(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        lines = [r["line"] for r in self.fake_log() if r["event"] == "stdin"]
        text = json.dumps(lines)
        for word in ("acceptForSession", "acceptWithExecpolicyAmendment", "applyNetworkPolicyAmendment", "cancel"):
            self.assertNotIn(word, text)
        decisions = [x["result"]["decision"] for x in lines if "method" not in x and isinstance(x.get("result"), dict)
                     and "decision" in x["result"]]
        self.assertEqual(sorted(set(decisions)), ["accept", "decline"])
        self.assertEqual(decisions.count("accept"), 4)       # ls -a, the changed command, the patch, the shell write outside
        methods = [x["method"] for x in lines if "method" in x]
        self.assertEqual(methods.count("turn/start"), len(STEPS))
        self.assertEqual(methods.count("turn/steer"), 1)
        self.assertEqual(methods.count("turn/interrupt"), 1)
        self.assertEqual(methods.count("thread/delete"), 1)
        self.assertEqual(methods.count("thread/resume"), 1)
        self.assertEqual(methods.count("thread/start"), 1)
        self.assertEqual(methods.count("mcpServerStatus/list"), 2)

    def test_codex_gets_the_persons_own_chat_folder_and_the_fixed_argv_and_environment(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        self.assertEqual(len(starts), 2, "one process for the steps up to the interrupt, one after it")
        consts = ccp.VERSIONS[VERSION]
        for start in starts:
            self.assertEqual(start["argv"], ccp.argv_for(consts, start["cwd"]))
            self.assertEqual(sorted(start["env_keys"]), sorted(consts.env_keys))
            self.assertEqual(start["codex_home"], str(self.chat_home))
            self.assertIn("/chat-work/", start["cwd"])
            self.assertNotIn(str(self.state) + "/chat-work", str(self.chat_home))
        begin = next(x["line"] for x in self.fake_log() if x["event"] == "stdin"
                     and x["line"].get("method") == "thread/start")
        self.assertEqual(begin["params"]["developerInstructions"], cc.INSTRUCTIONS)

    def test_the_check_leaves_nothing_behind_and_puts_the_process_back(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(os.environ["VBEAR_HOME"], str(self.state))
        self.assertEqual((ccs.CodexChatProcess._on_fact, ccs.CodexChatProcess.tick), self.hooks)
        self.assertEqual([p.name for p in self.out.iterdir()], ["report.json"])
        self.assertEqual(sorted(p.name for p in self.state.iterdir()),
                         ["codex-chat-home", "codex-chat-verified.json"], "its temporary state folder is gone")
        self.assertTrue(report["checks"]["cleanup"]["pass"])
        self.assertEqual(sorted(p.name for p in self.chat_home.iterdir()), [], "nothing was left in the person's folder")
        for rec in self.fake_log():
            if rec["event"] == "start":
                with self.assertRaises(ProcessLookupError):
                    os.kill(rec["pid"], 0)

    def test_the_thread_it_made_is_deleted_and_its_file_is_gone(self):
        code, report = self.check({"rollout": True})
        self.assertEqual(code, 0, report.get("error"))
        self.assertEqual(report["observations"]["thread_file"], {"before": 1, "after": 0})
        self.assertTrue(report["checks"]["thread_deleted"]["pass"])
        self.assertEqual(list((self.chat_home / "sessions").glob("*.jsonl")), [])

    def test_nothing_of_the_account_is_in_the_report(self):
        code, report = self.check({"rollout": True})
        text = json.dumps(report, ensure_ascii=False)
        for secret in ccf.SENSITIVE + ("fake_plan", "fake-limit", str(self.chat_home), "gpt-6.1-sol-user"):
            self.assertNotIn(secret, text)
        self.assertNotRegex(text, cc.EMAIL_RE.pattern)

    def test_the_default_report_goes_to_the_verifications_folder(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.run(str(self.binary), VERSION, None)
        self.assertEqual(code, 0)
        path = self.state / "verifications" / f"codex-{VERSION}-chat.json"
        self.assertEqual(json.loads(path.read_text())["mode"], "codex-chat")
        self.assertEqual(self.verified(), (VERSION,))

    def test_a_report_that_is_changed_or_gone_stops_counting(self):
        self.assertEqual(self.check()[0], 0)
        report = self.out / "report.json"
        data = json.loads(report.read_text())
        data["passed"] = False
        report.write_text(json.dumps(data))
        report.chmod(0o600)
        self.assertEqual(self.verified(), ())
        report.unlink()
        self.assertEqual(self.verified(), ())

    def test_a_report_of_the_claude_chat_check_does_not_count(self):
        self.assertEqual(self.check()[0], 0)
        report = self.out / "report.json"
        data = json.loads(report.read_text())
        data["mode"] = "chat"
        report.write_text(json.dumps(data))
        report.chmod(0o600)
        self.assertEqual(self.verified(), ())

    def test_a_pass_keeps_the_versions_that_passed_before(self):
        path = self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE
        other = self.out / "other.json"
        other.write_text(json.dumps({"mode": "codex-chat", "passed": True, "codex_version": "0.170.0"}))
        other.chmod(0o600)
        cfg.write_private(path, json.dumps({"versions": {"0.170.0": {
            "passed": True, "verified_at": "2026-11-05T00:00:00+0000", "report": str(other)}}}))
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.verified(), ("0.163.0", "0.170.0"))

    def test_instructions_not_followed_is_reported_but_does_not_fail_the_check(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertFalse(report["observations"]["instructions_followed"], "the fake does not follow instructions")


class FailTests(CheckCase):
    def test_a_command_that_runs_without_asking_fails(self):
        code, report = self.check({"ls_unasked": True})
        self.assert_failed(code, report, "ls_asks")

    def test_a_changed_command_that_does_not_take_effect_fails(self):
        code, report = self.check({"edit_ignored": True})
        self.assert_failed(code, report, "edit_works")
        self.assertTrue(report["checks"]["edit_steer"]["pass"])

    def test_a_steer_codex_refuses_fails_and_names_the_step_and_does_not_fall_back_silently(self):
        code, report = self.check({"steer_rejected": True})
        self.assert_failed(code, report, "edit_steer")
        step = report["checks"]["edit_steer"]
        self.assertIn("turn/steer", step["note"])
        self.assertIn("edit", step["note"])
        self.assertEqual(step["failed_code"], -32600)
        self.assertEqual({k: report["observations"]["steer"][k] for k in ("accepted", "failed_code")},
                         {"accepted": False, "failed_code": -32600})
        self.assertFalse(report["checks"]["edit_works"]["pass"])
        # the run went on and the other steps ran
        self.assertTrue(report["checks"]["deny_works"]["pass"], report["checks"]["deny_works"])
        self.assertTrue(report["checks"]["patch_card"]["pass"], "the steps after it ran")
        # VBear's fallback (the changed text as the next message) was stopped, not left to run
        steer = report["observations"]["steer"]
        self.assertTrue(steer["fallback_turn"], "VBear sent the changed text as a new turn: said, and stopped")
        self.assertEqual(report["turns"][2]["reason"], "result")
        self.assertEqual(report["turns"][3]["reason"], "stopped")
        self.assertEqual(Decimal(report["turns"][3]["cost_usd"]), cc.STEP_CAP_USD["edit"], "a stopped turn costs its cap")

    def test_a_declined_command_that_still_runs_fails(self):
        code, report = self.check({"deny_ignored": True})
        self.assert_failed(code, report, "deny_works")

    def test_an_allowed_shell_write_outside_is_only_noted_and_does_not_decide_the_result(self):
        code, report = self.check({"outside_escapes": True})
        self.assertEqual((code, report["passed"], report.get("error")), (0, True, None), report)
        self.assertTrue(report["checks"]["outside_patch_refused"]["pass"])
        outside = report["observations"]["outside"]
        self.assertEqual(outside["patch"], "declined_by_vbear")
        self.assertEqual((outside["shell"], outside["shell_wrote_outside"]), ("allowed", True))
        self.assertEqual(self.verified(), (VERSION,))

    def test_an_allowed_shell_write_that_stayed_in_is_noted_too(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        outside = report["observations"]["outside"]
        self.assertEqual((outside["shell"], outside["shell_wrote_outside"]), ("allowed", False))
        self.assertEqual(outside["files_removed"], True)

    def test_the_check_removes_the_files_it_caused_outside_itself_before_the_next_step(self):
        real, seen = cc._run_steps, {}

        def steps(s, work, outside, real_home, checks, obs):
            real(s, work, outside, real_home, checks, obs)
            seen["left"] = sorted(p.name for p in outside.iterdir())
        with mock.patch.object(cc, "_run_steps", steps):
            code, report = self.check({"outside_escapes": True})
        self.assertEqual(code, 0, report)
        self.assertEqual(report["observations"]["outside"]["shell_wrote_outside"], True)
        self.assertEqual(seen["left"], [], "the folder outside is empty again")

    def test_apply_patch_that_writes_outside_the_work_folder_fails(self):
        code, report = self.check({"outside_patch_escapes": True})
        self.assert_failed(code, report, "outside_patch_refused")
        self.assertEqual(report["checks"]["outside_patch_refused"]["files_outside"], ["outside-probe.txt"])

    def test_apply_patch_outside_that_gets_a_card_fails(self):
        asks = mock.patch.object(ccp, "judge_file_change", return_value=ccp.Judgement("ask", "x"))
        with asks:
            code, report = self.check()
        self.assert_failed(code, report, "outside_patch_refused")
        self.assertEqual(report["observations"]["outside"]["patch"], "card_shown")

    def test_a_resumed_thread_that_forgot_fails(self):
        code, report = self.check({"forgets": True})
        self.assert_failed(code, report, "resume_memory")

    def test_a_token_total_that_goes_back_after_resume_fails(self):
        code, report = self.check({"tokens_back": True})
        self.assert_failed(code, report, "tokens_cumulative")

    def test_mcp_servers_in_the_list_fail_and_stop_the_run_before_anything_costs(self):
        code, report = self.check(clean=False)
        self.assert_failed(code, report, "mcp_empty")
        self.assertIn("error", report)
        self.assertEqual(len(report["turns"]), 1)
        self.assertEqual(Decimal(report["turns"][0]["cost_usd"]), 0)

    def test_an_interrupt_codex_refuses_fails(self):
        code, report = self.check({"interrupt_rejected": True})
        self.assert_failed(code, report, "interrupt_works")

    def test_a_delete_codex_refuses_fails(self):
        code, report = self.check({"delete_fails": True})
        self.assert_failed(code, report, "thread_deleted")

    def test_a_process_that_does_not_end_when_stdin_closes_in_time_fails(self):
        with mock.patch.object(cc, "CLOSE_DEADLINE", 2.0):
            code, report = self.check({"ignore_eof": True})
        self.assert_failed(code, report, "idle_close")
        self.assertNotEqual(report["checks"]["idle_close"]["returncode"], 0)

    def test_a_process_that_ends_late_but_by_itself_fails_the_deadline(self):
        with mock.patch.object(cc, "CLOSE_DEADLINE", 1.0):
            code, report = self.check({"late_exit": True}, exit_delay=3)
        self.assert_failed(code, report, "idle_close")

    def test_a_process_that_is_still_alive_at_the_end_fails(self):
        with mock.patch.object(cc, "_alive", side_effect=lambda pids: sorted(pids)[:1]):
            code, report = self.check()
        self.assert_failed(code, report, "cleanup")
        self.assertTrue(report["checks"]["cleanup"]["processes_left"])

    def test_a_scratch_folder_that_is_left_fails(self):
        with mock.patch.object(agent_sessions, "cleanup_launch", return_value={"cleaned": False}):
            code, report = self.check()
        self.assert_failed(code, report, "cleanup")
        self.assertTrue(report["checks"]["cleanup"]["scratch_left"])
        self.assertFalse(any(Path(p).exists() for p in report["checks"]["cleanup"]["scratch_left"]),
                         "and the check removes what it found")

    def test_a_settings_file_codex_writes_into_the_persons_folder_fails(self):
        real = ccs.CodexChatProcess.delete_thread

        def delete(this):
            (self.chat_home / "config.toml").write_text("x = 1\n")
            return real(this)
        with mock.patch.object(ccs.CodexChatProcess, "delete_thread", delete):
            code, report = self.check()
        self.assert_failed(code, report, "home_clean")

    def test_a_trust_entry_written_at_start_fails_at_that_step_not_only_at_the_end(self):
        code, report = self.check({"ignores_trust": True})
        self.assert_failed(code, report, "home_no_config_at_start")

    def test_a_chat_started_without_the_project_settings_fails(self):
        real = ccp.argv_for

        def without(consts, workdir):
            argv = real(consts, workdir)
            drop = {i for i, a in enumerate(argv) if a == "-c" and argv[i + 1].startswith(("projects=", "project_root_markers"))}
            return [a for i, a in enumerate(argv) if i not in drop and i - 1 not in drop]
        with mock.patch.object(ccp, "argv_for", without):
            code, report = self.check()
        self.assert_failed(code, report, "home_no_config_at_start")

    def test_the_report_says_both_project_settings_were_sent_without_a_path(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        sent = report["observations"]["project_settings"]
        self.assertEqual(sent, {"project_root_markers": "[]", "project_trust": "untrusted", "processes": 2})
        self.assertTrue(report["checks"]["project_settings_sent"]["pass"])
        self.assertNotIn("chat-work", json.dumps(report))
        for rec in self.fake_log():
            if rec["event"] == "start":
                self.assertIn("project_root_markers=[]", rec["argv"])
                self.assertTrue(any(a.startswith("projects={") for a in rec["argv"]))
        self.assertFalse((self.chat_home / "config.toml").exists())

    def test_a_turn_that_reaches_its_cap_fails(self):
        code, report = self.check(call_tokens=60000)       # one call costs US$0.06, more than any step's cap
        self.assert_failed(code, report)
        self.assertIn("limit", [t["reason"] for t in report["turns"]])

    def test_the_total_limit_stops_the_run(self):
        with mock.patch.object(cc, "TOTAL_USD", Decimal("0.03")):
            code, report = self.check()
        self.assert_failed(code, report)
        self.assertIn("總花費", report["error"])
        self.assertLess(len(report["turns"]), len(STEPS))

    def test_another_version_than_the_one_named_fails(self):
        code, report = self.check({}, version="0.999.0")
        self.assertEqual(code, 2)
        self.assertIn("沒有聊天模式的常數", report["error"])
        self.assertEqual(self.fake_log(), [], "nothing was started")
        self.assertEqual(self.verified(), ())

    def test_a_python_without_waitid_fails_before_anything_starts(self):
        before = set(self.state.iterdir())
        with mock.patch.object(cc.stream_session, "waitid_problem", return_value="這個 Python（3.9.6）沒有 os.waitid"):
            code, report = self.check()
        self.assertEqual((code, report["passed"]), (2, False))
        self.assertIn("os.waitid", report["error"])
        self.assertEqual(self.fake_log(), [], "no process was started")
        self.assertEqual(set(self.state.iterdir()), before, "and no temporary folder was made")

    def test_an_administrator_policy_stops_the_check_before_any_model_call(self):
        self.policy = admin_policy.PolicyCheck(False, found=["/etc/codex"])
        code, report = self.check()
        self.assert_failed(code, report, "admin_policy")
        self.assertIn("error", report)
        self.assertFalse([x for x in self.fake_log() if x["event"] == "start"], "no app-server was started")

    def test_no_chat_login_stops_the_check_before_any_app_server_starts(self):
        self.fake(login_status=1)
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertIn("登入", report["error"])
        self.assertFalse([x for x in self.fake_log() if x["event"] == "start"])
        self.assertEqual(self.verified(), ())

    def test_no_chat_folder_stops_the_check(self):
        self.chat_home.rmdir()
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertIn("登入", report["error"])
        self.assertEqual(self.fake_log(), [])

    def test_a_chat_folder_with_someone_elses_config_stops_the_check(self):
        (self.chat_home / "config.toml").write_text("x = 1\n")
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertIn("config.toml", report["error"])
        self.assertFalse([x for x in self.fake_log() if x["event"] == "start"])

    def test_the_hooks_are_put_back_after_a_failure(self):
        self.check({"ls_unasked": True})
        self.assertEqual((ccs.CodexChatProcess._on_fact, ccs.CodexChatProcess.tick), self.hooks)
        self.assertEqual(os.environ["VBEAR_HOME"], str(self.state))


class EarlyStopTests(CheckCase):
    def stop_after_one_turn(self, end_process):
        def steps(s, work, outside, real_home, checks, obs):
            s.open()
            n = s.say("stream", cc.PROMPTS["stream"])
            s.drive(n, lambda card, i: ("deny", None))
            if end_process:
                s.end_now()
            raise cc.CheckError("stopped here on purpose")
        with mock.patch.object(cc, "_run_steps", steps):
            return self.check({"rollout": True})

    def test_a_run_that_stops_early_with_an_idle_process_still_deletes_its_thread(self):
        code, report = self.stop_after_one_turn(False)
        self.assert_failed(code, report)
        self.assertTrue(report["checks"]["thread_deleted"]["pass"], report["checks"]["thread_deleted"])
        self.assertEqual(report["observations"]["thread_file"], {"before": 1, "after": 0})
        self.assertTrue(report["checks"]["idle_close"]["pass"])
        self.assertTrue(report["checks"]["cleanup"]["pass"])

    def test_a_run_that_stops_early_without_a_process_says_the_thread_was_left(self):
        code, report = self.stop_after_one_turn(True)
        self.assert_failed(code, report, "thread_deleted")
        self.assertTrue(report["checks"]["thread_deleted"]["left"])
        self.assertEqual(report["observations"]["thread_file"], {"before": 1, "after": 1})
        self.assertEqual(len(list((self.chat_home / "sessions").glob("*.jsonl"))), 1)


class LeakTests(unittest.TestCase):
    def test_what_counts_as_account_data(self):
        self.assertEqual(cc.leaks('{"codexHome": "x"}'), ["codexHome"])
        self.assertEqual(cc.leaks('"userAgent"'), ["userAgent"])
        self.assertEqual(cc.leaks("planType credits"), [])             # a bare word is not a key in a record
        self.assertEqual(cc.leaks('{"planType":"x","credits":{}}'), ["credits", "planType"])
        self.assertEqual(cc.leaks("write to fictional.person@example.org"), ["email"])
        self.assertEqual(cc.leaks("a path /x/y", extra=("/x/y",)), ["path"])
        self.assertEqual(cc.leaks("all fine"), [])


class CommandTests(CheckCase):
    def test_boundary_check_takes_mode_codex_chat(self):
        out = self.out / "cli-report.json"
        buf = io.StringIO()
        argv = ["boundary_check", "--mode", "codex-chat", "--codex", str(self.binary), "--out", str(out)]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
            code = boundary_check.main()
        self.assertEqual(code, 0, buf.getvalue()[-800:])
        self.assertEqual(json.loads(out.read_text())["mode"], "codex-chat")
        self.assertEqual(self.verified(), (VERSION,))
        printed = json.loads(buf.getvalue())
        self.assertEqual((printed["mode"], printed["passed"], printed["codex_version"]), ("codex-chat", True, VERSION))
        self.assertNotIn("claude_version", printed)

    def test_it_does_not_need_a_claude_code(self):
        argv = ["boundary_check", "--mode", "codex-chat", "--codex", str(self.binary), "--out", str(self.out / "r.json")]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(boundary_check, "pick_claude", side_effect=AssertionError("no claude")):
            self.assertEqual(boundary_check.main(), 0)

    def test_a_python_without_waitid_is_refused_first_as_for_mode_chat(self):
        argv = ["boundary_check", "--mode", "codex-chat", "--codex", str(self.binary), "--out", str(self.out / "r.json")]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(cc.stream_session, "waitid_problem", return_value="no waitid"):
            self.assertEqual(boundary_check.main(), 2)
        self.assertEqual(self.fake_log(), [], "not even codex --version was run")

    def test_a_codex_that_does_not_print_its_version_is_not_checked(self):
        self.fake(version="0.999.0")
        argv = ["boundary_check", "--mode", "codex-chat", "--codex", str(self.binary), "--out", str(self.out / "r.json")]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(boundary_check.main(), 2)
        self.assertEqual(self.verified(), ())

    def test_the_other_modes_keep_their_choices(self):
        self.assertIn("codex-chat", boundary_check.MODES)
        for mode in ("headless", "interactive", "stream", "chat"):
            self.assertIn(mode, boundary_check.MODES)


class SharedTests(CheckCase):
    """P43-2 (ADR 0009): the shared folder part of the check, in a second chat. Its result is the report's ``shared``; a failure
    there leaves ``passed`` and the record of the chat check alone."""

    def check(self, flags=None, **conf):
        if flags is not None or conf:
            self.fake(flags, **conf)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.run(str(self.binary), VERSION, str(self.out / "report.json"), shared=True)
        return code, json.loads((self.out / "report.json").read_text())

    def assert_shared(self, report, ok, failed=()):
        self.assertEqual(report["shared"], "passed" if ok else "failed", report["shared_steps"])
        for name in failed:
            self.assertFalse(report["shared_steps"][name]["pass"], (name, report["shared_steps"]))

    def test_a_well_behaved_codex_passes_the_shared_part_and_it_is_in_the_report(self):
        code, report = self.check()
        self.assertEqual((code, report["passed"], report.get("error")), (0, True, None), report)
        self.assert_shared(report, True)
        self.assertEqual(set(report["shared_steps"]), set(cc.SHARED_STEPS))
        self.assertTrue(all(c["pass"] for c in report["shared_steps"].values()), report["shared_steps"])
        self.assertEqual(len(report["turns"]), len(STEPS), "the main chat keeps its seven turns")
        self.assertEqual(report["observations"]["shared"], {"patch": "card_shown", "shell": "card_shown", "link": "declined_by_vbear"})
        self.assertTrue(cli_versions.shared_verified("codex-chat", VERSION))

    def test_the_shared_process_has_the_folder_as_its_one_more_root_and_the_main_chat_does_not(self):
        code, report = self.check()
        self.assertEqual(code, 0)
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        self.assertEqual(len(starts), 3, "two for the main chat, one for the shared one")
        consts = ccp.VERSIONS[VERSION]
        for start in starts[:2]:
            self.assertEqual(start["argv"], ccp.argv_for(consts, start["cwd"]), "the main chat is what it was")
        shared = starts[2]["argv"]
        roots = [a for a in shared if a.startswith("sandbox_workspace_write.writable_roots=")]
        self.assertEqual(len(roots), 1)
        self.assertEqual(shared, ccp.argv_for(consts, starts[2]["cwd"], shared=json.loads(roots[0].split("=", 1)[1])[0]))
        self.assertNotIn("--add-dir", shared)

    def test_nothing_is_left_behind_and_nothing_of_the_persons_is_touched(self):
        code, report = self.check({"rollout": True})
        self.assertEqual(code, 0, report.get("error"))
        self.assertTrue(report["checks"]["cleanup"]["pass"])
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["codex-chat-home", "codex-chat-verified.json"])
        self.assertEqual(list((self.chat_home / "sessions").glob("*.jsonl")), [], "both threads were deleted")
        self.assertEqual(report["observations"]["shared_thread_file"], {"before": 1, "after": 0})
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("vbear-check-patch", text)
        self.assertNotIn("vbear-check-shell", text)
        for rec in self.fake_log():
            if rec["event"] == "start":
                with self.assertRaises(ProcessLookupError):
                    os.kill(rec["pid"], 0)

    def test_the_spend_stays_within_both_limits(self):
        code, report = self.check()
        main = sum(Decimal(t["cost_usd"]) for t in report["turns"])
        self.assertLessEqual(main, cc.TOTAL_USD)
        self.assertLessEqual(max(cc.SHARED_CAP_USD.values()), cc.SHARED_TOTAL_USD)
        self.assertLessEqual(sum(cc.SHARED_CAP_USD.values()), cc.SHARED_TOTAL_USD + Decimal("0.02"))

    def test_a_thread_answer_that_does_not_name_the_folder_fails_the_shared_part_only(self):
        for roots in ("empty", "extra", "extra_first"):
            with self.subTest(roots=roots):
                code, report = self.check(roots=roots) if roots != "empty" else self.check(roots="empty")
                if roots == "empty":
                    self.assertEqual((code, report["passed"]), (0, True), "the main chat has no root: an empty answer is right")
                self.assert_shared(report, False)
                self.assertFalse(cli_versions.shared_verified("codex-chat", VERSION))

    def test_a_patch_in_the_folder_that_is_written_without_a_card_fails_the_shared_part(self):
        code, report = self.check({"shared_patch_unasked": True})
        self.assertEqual((code, report["passed"]), (0, True))
        self.assert_shared(report, False, ["shared_patch_card"])

    def test_a_patch_through_a_link_that_gets_written_fails_the_shared_part(self):
        code, report = self.check({"shared_link_escapes": True})
        self.assertEqual((code, report["passed"]), (0, True))
        self.assert_shared(report, False, ["shared_link_refused"])

    def test_a_link_patch_that_vbear_would_ask_about_fails_the_shared_part(self):
        real = ccp.judge_file_change

        def lenient(changes, workdir, *a, **kw):
            if any("vbear-check-link" in str(c.get("path")) for c in changes):
                return ccp.Judgement("ask", "x")
            return real(changes, workdir, *a, **kw)
        with mock.patch.object(ccp, "judge_file_change", lenient):
            code, report = self.check()
        self.assertEqual((code, report["passed"]), (0, True))
        self.assert_shared(report, False, ["shared_link_refused"])

    def test_the_old_report_without_the_shared_part_still_counts_as_chat_verified_but_not_for_the_folder(self):
        code, report = self.check()
        data = json.loads((self.out / "report.json").read_text())
        for key in ("shared", "shared_steps"):
            data.pop(key)
        (self.out / "report.json").write_text(json.dumps(data))
        (self.out / "report.json").chmod(0o600)
        self.assertEqual(self.verified(), (VERSION,))
        self.assertFalse(cli_versions.shared_verified("codex-chat", VERSION))

    def test_without_asking_for_it_the_report_says_it_was_not_run_and_no_process_was_made_for_it(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.run(str(self.binary), VERSION, str(self.out / "report.json"))
        report = json.loads((self.out / "report.json").read_text())
        self.assertEqual((code, report["passed"], report["shared"]), (0, True, "failed"))
        self.assertEqual(list(report["shared_steps"]), ["not_run"])
        self.assertEqual(len([x for x in self.fake_log() if x["event"] == "start"]), 2)

    def test_the_command_line_check_does_it(self):
        out = self.out / "cli-report.json"
        argv = ["boundary_check", "--mode", "codex-chat", "--codex", str(self.binary), "--out", str(out)]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(boundary_check.main(), 0)
        self.assertEqual(json.loads(out.read_text())["shared"], "passed")

    def test_when_the_main_part_fails_the_shared_part_is_not_run(self):
        code, report = self.check({"deny_ignored": True})
        self.assert_failed(code, report, "deny_works")
        self.assert_shared(report, False)
        self.assertEqual(list(report["shared_steps"]), ["not_run"])


class DaemonHookTests(CheckCase):
    def test_a_daemon_without_the_hook_still_wants_its_own_chat_folder(self):
        from vbear.runtime import daemon as d
        dm = d.Daemon(self.state, log=lambda _line: None)
        self.assertIsNone(dm.codex_chat_home)
        self.assertEqual(dm.codex_chat_probe_versions, frozenset())


if __name__ == "__main__":
    unittest.main()
