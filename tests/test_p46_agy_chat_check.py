"""The AGY chat check (vbear/agy_chat_check.py, ``boundary_check --mode agy-chat``, P46-4) against a fake AGY that does what each message of
the check asks (tests/fake_agy_acp_check.py): a well-behaved one passes and is recorded; one that breaks a rule the check watches for
fails that check and is not recorded. Synthetic HOME and state under /tmp; no model, no network, and the real agy is never run: the
only program that is executed is the fake launcher in this test's own folder."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests import fake_agy_acp_check as fake
from tests import leftover
from vbear import admin_policy, agy_chat_check as cc, agy_verify, boundary_check, claude_verify, config as cfg
from vbear.runtime import agy_chat_env, agy_chat_protocol as acp, chat_protocol as cp, cli_versions

VERSION = "1.5.3"
SCALE = 0.03                           # the fake's `sleep 60` lasts 60 x this many seconds
ALL_CHECKS = ("admin_policy", "no_home_hooks", "initialize", "session_id_uuid", "stream_text", "system_prompt_applied", "strict_settings",
              "read_inside", "ls_asks", "deny_works", "edit_works", "outside_edit_refused", "outside_shell_blocked", "bypass_refused",
              "network_blocked", "link_read_safe", "stop_works", "resume_memory", "set_model_each_process", "home_clean",
              "settings_untouched", "no_account_data", "records_clean", "usage_adds_up", "cost_within_limit", "cleanup")


class CheckCase(unittest.TestCase):
    policy = None

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(leftover.assert_clean, self.tmp)        # runs after the daemon is stopped and before the folder goes
        self.state = self.tmp / "st"
        self.state.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state), "HOME": str(self.home), "TMPDIR": str(self.tmpdir),
                                           "VBEAR_RUNTIME_AUTOSTART": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.assertTrue(str(Path.home()).startswith(str(self.tmp)), "the synthetic HOME is the one in use")
        for target, value in (("vbear.admin_policy.check_agy", None), ):
            policy = mock.patch(target, side_effect=lambda version, root="/": self.policy or admin_policy.PolicyCheck(True))
            policy.start()
            self.addCleanup(policy.stop)
        for name, value in (("STOP_DELAY", 0.3), ("AFTER_STOP_WAIT", 2.0)):
            patch = mock.patch.object(cc, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        # a root under /tmp is the test's own; the guard against it has a test of its own
        patch = mock.patch.object(cc, "find_left", lambda root: [])
        patch.start()
        self.addCleanup(patch.stop)
        self.conf_path = self.home / "fake-agy.json"
        self.binary = Path(fake.write_launcher(self.tmp / "agy", self.conf_path))
        self.fake()

    def fake(self, flags=None, **conf):
        base = {"version": VERSION, "time_scale": SCALE, "flags": flags or {}}
        base.update(conf)
        self.conf_path.write_text(json.dumps(base))

    def check(self, flags=None, *, version=VERSION, out=None, shared=True, tmp_root=True, **conf):
        if flags is not None or conf:
            self.fake(flags, **conf)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.run(str(self.binary), version, out or str(self.out / "report.json"), shared=shared,
                          tmp_root=str(self.state) if tmp_root else None)
        self.printed = buf.getvalue()
        path = Path(out) if out else self.out / "report.json"
        return code, json.loads(path.read_text())

    def fake_log(self):
        path = Path(str(self.conf_path) + ".log.jsonl")
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def verified(self):
        return cli_versions.agy_chat_verified_versions()

    def assert_failed(self, code, report, name=None, shared=False):
        self.assertNotEqual(code, 0, report.get("error"))
        self.assertFalse(report["passed"])
        if name:
            table = report["shared_steps"] if shared else report["checks"]
            self.assertFalse(table[name]["pass"], table.get(name))
        self.assertEqual(self.verified(), (), "a failed check records nothing")
        self.assertFalse((self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).exists())


class PassTests(CheckCase):
    """One well-behaved run, looked at from every side (a run is a few dozen turns: it is made once)."""

    def run_once(self):
        return self.check()

    def test_a_well_behaved_agy_passes_and_is_recorded(self):
        self.assertEqual(self.verified(), ())
        code, report = self.run_once()
        self.assertEqual((code, report["passed"], report.get("error")), (0, True, None), report)
        for name in ALL_CHECKS:
            self.assertTrue(report["checks"][name]["pass"], (name, report["checks"][name]))
        self.assertEqual((report["mode"], report["agy_version"], report["shared"]), ("agy-chat", VERSION, "passed"))
        self.assertTrue(all(v["pass"] for v in report["shared_steps"].values()), report["shared_steps"])
        self.assertTrue(set(cc.SHARED_STEPS) <= set(report["shared_steps"]))
        self.assertNotIn("codex_version", report)
        self.assertNotIn("claude_version", report)
        self.assertEqual(self.verified(), (VERSION,))
        self.assertEqual(cli_versions.agy_chat_shared_verified_versions(), (VERSION,))
        record = json.loads((self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).read_text())["versions"][VERSION]
        self.assertEqual((record["passed"], record["report"]), (True, str(self.out / "report.json")))
        self.assertEqual(stat.S_IMODE(os.stat(self.out / "report.json").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).st_mode), 0o600)
        for other in (cli_versions.LOCAL_CHAT_VERIFIED_FILE, cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE):
            self.assertFalse((self.state / other).exists(), "Claude's and Codex's records are other files")
        self.assertFalse([n for n in os.listdir(self.state) if n.startswith("agc-")], "the check's folder is gone")

    def test_it_is_judged_from_what_vbear_wrote_and_what_the_files_hold_and_every_choice_is_allow_once_or_reject_once(self):
        code, report = self.check()
        self.assertEqual(code, 0, report.get("error"))
        log = self.fake_log()
        starts = [r for r in log if r["event"] == "start"]
        self.assertGreaterEqual(len(starts), 5)
        for start in starts:
            self.assertEqual(start["argv"][0], "acp")
            self.assertIn("--sandbox", start["argv"])
            self.assertIn("--disable-telemetry", start["argv"])
            self.assertEqual(start["env_keys"], sorted(acp.constants_for(VERSION).env_keys))
            for banned in ("--dangerously-skip-permissions", "--login", "--app-data-dir", "--process-per-session",
                           "--include-default-customizations"):
                self.assertNotIn(banned, start["argv"])
        gemini = [s["argv"][s["argv"].index("--gemini-dir") + 1] for s in starts]
        self.assertTrue(all("/agc-" in g for g in gemini), "no process uses the person's own settings folder")
        self.assertTrue(any(g.endswith("/gs") for g in gemini), "the strict process has a folder of its own")
        self.assertTrue(any("--add-dir" in s["argv"] for s in starts), "the shared folder part has its folder named")
        lines = [r["line"] for r in log if r["event"] == "stdin"]
        methods = [x["method"] for x in lines if "method" in x]
        self.assertEqual(sorted(set(methods)), ["initialize", "session/cancel", "session/new", "session/prompt", "session/resume",
                                                "session/set_model"])
        self.assertEqual(methods.count("session/set_model"), methods.count("session/new") + methods.count("session/resume"))
        chosen = [x["result"]["outcome"].get("optionId") for x in lines if "method" not in x and isinstance(x.get("result"), dict)
                  and "outcome" in x["result"]]
        self.assertEqual(sorted(set(chosen)), ["allow", "deny"])

    def test_the_report_holds_names_of_what_agy_printed_and_no_account_data(self):
        code, report = self.check()
        self.assertEqual(code, 0, report.get("error"))
        proto = report["observations"]["protocol"]
        for method in ("initialize", "session/new", "session/set_model", "session/prompt", "session/cancel", "session/resume"):
            self.assertIn(method, proto["methods_out"])
        self.assertTrue(proto["system_prompt_sent"])
        for kind in ("agent_message_chunk", "tool_call", "tool_call_update", "available_commands_update", "agent_thought_chunk"):
            self.assertIn(kind, proto["updates"])
        self.assertIn("session/request_permission", proto["methods_in"])
        self.assertEqual(sorted(proto["option_kinds"]), ["allow_once", "reject_once"])
        self.assertIn("CommandLine", proto["raw_input_fields"]["execute"])
        self.assertIn("Path", proto["raw_input_fields"]["edit"])
        self.assertIn("totalTokens", proto["usage_fields"])
        self.assertIn("cancelled", proto["stop_reasons"])
        self.assertIn("sessionId", proto["result_fields"]["session_new"])
        text = (self.out / "report.json").read_text() + self.printed
        for sensitive in ("fake-tier-alpha", "fake-auth-1", "Made-up sign-in", "fake-skill-alpha", "fake-skill-beta", "authMethods",
                          '"tier"', "person@example.org"):
            self.assertNotIn(sensitive, text)
        self.assertTrue(report["observations"]["home_items"])
        self.assertFalse([n for n in report["observations"]["home_items"] if "fake-skill" in n])

    def test_what_the_plan_left_open_is_answered_one_by_one_in_the_report_and_in_words(self):
        code, report = self.check()
        self.assertEqual(code, 0, report.get("error"))
        answers = {a["assumption"]: a for a in report["assumptions"]}
        self.assertEqual(len(answers), len(cc.ASSUMPTIONS))
        self.assertTrue(all(a["result"] in ("confirmed", "observed") for a in answers.values()), answers)
        wanted = ("systemPrompt.append", "sessionId", "strict", "工作資料夾內的讀取", "--disable-telemetry", "--add-dir", "session/cancel",
                  "BypassSandbox", "TMPDIR", "ACP 欄位形狀")
        for word in wanted:
            self.assertTrue([t for t in answers if word in t], word)
        self.assertEqual(report["observations"]["bypass"], "requested_and_refused_by_vbear")
        self.assertEqual(report["observations"]["link_read"], "violation_stopped")
        self.assertEqual(report["observations"]["read_inside"], {"asked": "not_asked"})
        self.assertTrue(report["observations"]["stop"]["command_running"])
        self.assertEqual(report["observations"]["strict"]["asked"], True)
        self.assertTrue(report["observations"]["tmp_write"]["written"])
        self.assertIn("結果：通過", self.printed)
        self.assertIn("[確認] 系統指示", self.printed)
        self.assertIn("花費", self.printed)

    def test_the_spend_is_within_the_limit_and_counted_by_the_estimate(self):
        code, report = self.check()
        self.assertEqual(code, 0, report.get("error"))
        total = sum(Decimal(t["cost_usd"]) for t in report["turns"])
        self.assertLessEqual(Decimal(report["spent_usd"]), cc.TOTAL_USD + cc.SHARED_TOTAL_USD)
        self.assertGreaterEqual(Decimal(report["spent_usd"]), total)
        self.assertEqual(cc.TOTAL_USD + cc.SHARED_TOTAL_USD, Decimal("1.50"))
        for step in ("stream", "settings", "read_inside", "ask", "deny", "edit", "outside_edit", "outside_shell", "bypass", "network",
                     "link_read", "tmp_write", "stop", "resume", "resume_ask"):
            self.assertGreater(cc.STEP_CAP_USD[step], 0)
        self.assertEqual(sorted(cc.SHARED_CAP_USD), ["shared_git", "shared_link", "shared_shell", "shared_write"])
        self.assertTrue(all(t["tokens"] is None or isinstance(t["tokens"], int) for t in report["turns"]))

    def test_without_shared_the_report_says_the_folder_part_was_not_run_and_the_check_still_passes(self):
        code, report = self.check(shared=False)
        self.assertEqual((code, report["passed"], report["shared"]), (0, True, "failed"), report.get("error"))
        self.assertEqual(list(report["shared_steps"]), ["not_run"])
        self.assertEqual(self.verified(), (VERSION,))
        self.assertEqual(cli_versions.agy_chat_shared_verified_versions(), (), "recorded as checked, but not with the shared folder")

    def test_the_check_s_own_folders_are_in_the_state_folder_and_never_in_a_temporary_folder(self):
        seen = []
        original = cc.under
        with mock.patch.object(cc, "temp_dirs", lambda: ["/nonexistent-temp-folder"]), \
                mock.patch.object(cc, "under", lambda p, f: (seen.append(str(p)), original(p, f))[1]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cc.run(str(self.binary), VERSION, str(self.out / "report.json"), shared=False)
        report = json.loads((self.out / "report.json").read_text())
        self.assertEqual(code, 0, report.get("error"))
        starts = [r for r in self.fake_log() if r["event"] == "start"]
        self.assertTrue(all(f"{self.state}/agc-" in s["cwd"] for s in starts), [s["cwd"] for s in starts])
        self.assertEqual(seen, [str(self.state)])


class RefusalTests(CheckCase):
    def test_a_state_folder_in_a_temporary_folder_is_refused_before_anything_starts(self):
        code, report = self.check(tmp_root=False)
        self.assertEqual(code, 2)
        self.assertFalse(report["passed"])
        self.assertIn("暫存資料夾", report["error"])
        self.assertEqual(self.fake_log(), [], "nothing was started")
        self.assertEqual([n for n in os.listdir(self.state) if n.startswith("agc-")], [])
        self.assertIn("結果：沒有跑完", self.printed)

    def test_the_temporary_folders_include_tmp_and_tmpdir(self):
        folders = cc.temp_dirs()
        for folder in ("/private/tmp", os.path.realpath(str(self.tmpdir))):
            self.assertIn(folder, folders)
        self.assertTrue(cc.under("/tmp/x", folders))
        self.assertFalse(cc.under("/Users/example/state", folders))

    def test_hooks_in_the_persons_agy_settings_stop_it_before_anything_starts(self):
        (self.home / ".agents").mkdir()
        (self.home / ".agents" / "hooks.json").write_text("{}")
        code, report = self.check()
        self.assertEqual(code, 2)
        self.assertFalse(report["checks"]["no_home_hooks"]["pass"])
        self.assertIn("hooks", report["error"])
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.verified(), ())

    def test_an_administrator_policy_fails_it_and_nothing_starts(self):
        self.policy = admin_policy.PolicyCheck(False, found=("x",), problems=("p",))
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertFalse(report["checks"]["admin_policy"]["pass"])
        self.assertEqual(self.fake_log(), [])

    def test_a_version_without_constants_cannot_be_checked(self):
        code, report = self.check(version="9.9.9")
        self.assertEqual(code, 2)
        self.assertIn("沒有聊天模式的常數", report["error"])
        self.assertEqual(self.fake_log(), [])

    def test_not_signed_in_is_said_in_the_reports_words_and_the_run_stops_at_the_first_turn(self):
        # the fake's session/new answers an authentication error: the daemon records it and the check stops with the reason
        self.fake({"auth_error": True})
        code, report = self.check()
        self.assertNotEqual(code, 0)
        self.assertIn("還沒登入", report["error"])
        self.assertEqual(self.verified(), ())


class FailureTests(CheckCase):
    """Each rule the check watches for, broken by the fake (or by VBear's own code, for the ones VBear itself guarantees)."""

    def test_a_system_prompt_that_is_not_applied_fails(self):
        code, report = self.check({"no_system_prompt": True})
        self.assert_failed(code, report, "system_prompt_applied")

    def test_a_session_id_that_is_not_a_uuid_fails_the_first_turn(self):
        code, report = self.check({"session_id_not_uuid": True})
        self.assert_failed(code, report)
        self.assertFalse(report["checks"]["initialize"]["pass"] and report["checks"]["session_id_uuid"]["pass"])
        self.assertIn("第一回合", report["error"])

    def test_settings_that_agy_does_not_read_fail_the_strict_step(self):
        code, report = self.check({"strict_ignored": True})
        self.assert_failed(code, report, "strict_settings")

    def test_a_command_that_runs_without_a_card_fails_and_vbear_stops_the_chat(self):
        code, report = self.check({"ls_unasked": True})
        self.assert_failed(code, report, "ls_asks")
        self.assertFalse(report["checks"]["records_clean"]["pass"])

    def test_a_refused_rm_that_runs_anyway_fails(self):
        code, report = self.check({"deny_ignored": True})
        self.assert_failed(code, report, "deny_works")

    def test_a_change_that_did_not_take_effect_fails(self):
        code, report = self.check({"edit_ignored": True})
        self.assert_failed(code, report, "edit_works")

    def test_a_file_that_appears_outside_after_the_file_tool_was_refused_fails(self):
        code, report = self.check({"outside_edit_escapes": True})
        self.assert_failed(code, report, "outside_edit_refused")

    def test_a_sandbox_that_lets_a_write_out_or_a_read_of_the_decoy_through_fails(self):
        code, report = self.check({"outside_escapes": True})
        self.assert_failed(code, report, "outside_shell_blocked")
        self.assertTrue(report["checks"]["outside_shell_blocked"]["decoy_seen"])
        self.assertTrue(report["checks"]["outside_shell_blocked"]["file_outside"])
        self.assertFalse((self.state / "agc-x").exists())

    def test_a_network_that_works_fails(self):
        code, report = self.check({"network_works": True})
        self.assert_failed(code, report, "network_blocked")

    def test_the_decoys_code_word_in_a_reply_fails_whatever_the_route(self):
        code, report = self.check({"link_leaks": True})
        self.assert_failed(code, report, "link_read_safe")
        self.assertNotIn("DECOY-", json.dumps(report), "the report never holds the code word")

    def test_a_read_through_the_link_that_asks_is_shown_as_a_card_and_refused_and_nothing_leaks(self):
        code, report = self.check({"link_read_asks": True})
        self.assertEqual((code, report["passed"]), (0, True), report.get("error"))
        self.assertEqual(report["observations"]["link_read"], "read_request_seen")

    def test_a_command_that_goes_on_after_the_cancel_fails(self):
        code, report = self.check({"cancel_keeps_running": True})
        self.assert_failed(code, report, "stop_works")
        self.assertTrue(report["checks"]["stop_works"]["slept_file"])

    def test_a_session_that_does_not_remember_after_resume_fails(self):
        code, report = self.check({"forgets": True})
        self.assert_failed(code, report, "resume_memory")

    def test_an_item_vbear_forbids_in_the_settings_folder_fails(self):
        code, report = self.check({"home_item": True})
        self.assert_failed(code, report, "home_clean")

    def test_settings_json_changed_by_agy_stops_the_chat(self):
        code, report = self.check({"settings_changed": True})
        self.assert_failed(code, report)
        self.assertIn("設定檔", report["error"])

    def test_a_usage_that_does_not_add_up_fails(self):
        code, report = self.check({"bad_usage": True})
        self.assert_failed(code, report, "usage_adds_up")

    def test_an_email_in_a_reply_fails_and_never_reaches_the_report(self):
        code, report = self.check({"email_in_reply": True})
        self.assert_failed(code, report, "no_account_data")
        self.assertNotIn("person@example.org", (self.out / "report.json").read_text())
        self.assertNotIn("person@example.org", self.printed)

    def test_a_skill_name_the_check_was_told_of_fails_and_never_reaches_the_report(self):
        with mock.patch.object(cc, "EXTRA_SENSITIVE", ("fake-skill-alpha",)):
            code, report = self.check({"skill_in_reply": True})
        self.assert_failed(code, report, "no_account_data")
        self.assertNotIn("fake-skill-alpha", (self.out / "report.json").read_text())

    def test_a_request_to_run_outside_the_sandbox_that_became_a_card_fails(self):
        decide = acp.AgyTracker._decide

        def broken(tracker, rec, raw, options):           # a VBear that does not see the key
            return decide(tracker, rec, {k: v for k, v in raw.items() if k != "BypassSandbox"}, options)
        with mock.patch.object(acp.AgyTracker, "_decide", broken):
            code, report = self.check()
        self.assert_failed(code, report, "bypass_refused")
        self.assertEqual(report["observations"]["bypass"], "card_shown")

    def test_a_file_tool_outside_that_became_a_card_fails(self):
        shown = cp.Judgement("ask", "test", "content")
        with mock.patch.object(acp, "judge_file_change", lambda *a, **k: shown):
            code, report = self.check()
        self.assert_failed(code, report, "outside_edit_refused")

    def test_a_process_or_folder_left_behind_fails_the_cleanup(self):
        with mock.patch.object(cc, "find_left", lambda root: [4242]):
            code, report = self.check()
        self.assert_failed(code, report, "cleanup")
        self.assertIn(4242, report["checks"]["cleanup"]["processes_left"])
        left = []
        with mock.patch.object(cc.shutil, "rmtree", lambda path, ignore_errors=False: left.append(path)):
            code, report = self.check()
        self.assertTrue(report["checks"]["cleanup"]["temp_left"])
        self.assertFalse(report["checks"]["cleanup"]["pass"])
        for path in left:
            shutil.rmtree(path, True)

    def test_a_failed_run_still_deletes_what_it_made_and_leaves_no_process(self):
        code, report = self.check({"no_system_prompt": True})
        self.assertNotEqual(code, 0)
        self.assertTrue(report["checks"]["cleanup"]["pass"], report["checks"]["cleanup"])
        self.assertEqual([n for n in os.listdir(self.state) if n.startswith("agc-")], [])


class SharedFailureTests(CheckCase):
    def test_a_sandbox_that_does_not_open_the_shared_folder_fails_the_shared_part_only(self):
        code, report = self.check({"add_dir_ignored": True})
        self.assertEqual((code, report["passed"], report["shared"]), (0, True, "failed"), report.get("error"))
        self.assertFalse(report["shared_steps"]["shared_shell_card"]["pass"])
        self.assertEqual(self.verified(), (VERSION,))
        self.assertEqual(cli_versions.agy_chat_shared_verified_versions(), ())

    def test_a_write_through_a_link_that_leads_outside_fails_the_shared_part(self):
        code, report = self.check({"outside_edit_escapes": True, "only_shared": True})
        self.assertEqual((code, report["passed"], report["shared"]), (0, True, "failed"), report.get("error"))
        self.assertFalse(report["shared_steps"]["shared_link_refused"]["pass"], report["shared_steps"])

    def test_a_shared_folder_part_does_not_run_when_the_main_part_failed(self):
        code, report = self.check({"no_system_prompt": True})
        self.assertEqual(report["shared"], "failed")
        self.assertEqual(list(report["shared_steps"]), ["not_run"])


class UnitTests(unittest.TestCase):
    def test_leaks_finds_the_keys_an_email_a_told_name_and_a_path(self):
        self.assertEqual(cc.leaks('{"tier": "x"} {"authMethods": []} a@example.org /home/x', ("/home/x",)),
                         ["authMethods", "tier", "email", "path"])
        self.assertEqual(cc.leaks("plain text"), [])
        with mock.patch.object(cc, "EXTRA_SENSITIVE", ("some-skill",)):
            self.assertEqual(cc.leaks("uses some-skill"), ["name"])

    def test_the_words_are_random_each_time_and_the_instruction_names_the_system_word(self):
        a, b = cc.Words(), cc.Words()
        self.assertNotEqual((a.system, a.memory, a.decoy, a.tmp_name), (b.system, b.memory, b.decoy, b.tmp_name))
        self.assertIn(a.system, a.instructions)
        self.assertTrue(a.decoy.startswith("DECOY-") and len(a.decoy) > 12)

    def test_every_message_is_tagged_with_its_step_and_names_what_it_wants_exactly(self):
        w = cc.Words()
        msgs = cc.prompts(w, Path("/x/decoy"), "/x/tmp")
        for step, text in msgs.items():
            self.assertTrue(text.startswith(f"[vbear-check:{step}]"), step)
        self.assertEqual(set(msgs), set(cc.STEP_CAP_USD) - set())
        self.assertIn("/x/decoy/secret.txt", msgs["link_read"])
        self.assertIn(w.tmp_name, msgs["tmp_write"])
        self.assertIn(w.memory, msgs["resume"])
        self.assertNotIn(w.decoy, " ".join(msgs.values()), "the code word of the decoy is in no message")
        for step in cc.SHARED_PROMPTS:
            self.assertTrue(cc.SHARED_PROMPTS[step].startswith(f"[vbear-check:{step}]"))

    def test_find_left_names_a_process_whose_arguments_name_the_root_and_not_this_one(self):
        root = Path(tempfile.mkdtemp(prefix="vba-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, root, True)
        proc = subprocess.Popen(["sh", "-c", "sleep 30; true", str(root / "marker")], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(proc.wait)
        self.addCleanup(os.killpg, proc.pid, 15)
        real = subprocess.run

        def only_ps(argv, **kw):
            if argv[0] != "/bin/ps":
                raise OSError("no lsof in this test")
            return real(argv, **kw)
        with mock.patch.object(cc.subprocess, "run", only_ps):
            self.assertEqual(cc.find_left(root), [proc.pid])
            self.assertEqual(cc.find_left(root / "other"), [])

    def test_the_summary_names_the_step_that_failed_and_what_it_was_for(self):
        report = {"agy_version": VERSION, "passed": False, "checks": {"initialize": {"pass": True}, "edit_works": {
            "pass": False, "note": "改內容再問"}}, "shared": "failed", "shared_steps": {"shared_shell_card": {"pass": False}},
                  "assumptions": [{"assumption": "x", "result": "failed"}], "spent_usd": "0.52", "turns": [1, 2]}
        text = cc.summary_text(report, Path("/x/r.json"), 1)
        self.assertIn("結果：沒有通過", text)
        self.assertIn("失敗的步驟：edit_works——改內容再問", text)
        self.assertIn("共用資料夾：沒有通過（shared_shell_card）", text)
        self.assertIn("US$0.52，2 個回合", text)
        self.assertIn("報告檔：/x/r.json", text)
        self.assertNotIn("initialize", text)


class CommandLineTests(CheckCase):
    def test_boundary_check_has_the_mode_and_runs_the_check_on_the_agy_it_is_given(self):
        self.assertIn("agy-chat", boundary_check.MODES)
        buf = io.StringIO()
        argv = ["boundary_check", "--mode", "agy-chat", "--agy", str(self.binary), "--out", str(self.out / "r.json")]
        with mock.patch("sys.argv", argv), mock.patch.object(cc, "run", return_value=0) as run, contextlib.redirect_stdout(buf):
            self.assertEqual(boundary_check.main(), 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[1], VERSION)
        self.assertEqual(run.call_args.kwargs, {"shared": False})
        with mock.patch("sys.argv", argv + ["--shared"]), mock.patch.object(cc, "run", return_value=0) as run, \
                contextlib.redirect_stdout(buf):
            boundary_check.main()
        self.assertEqual(run.call_args.kwargs, {"shared": True})

    def test_without_agy_the_one_on_the_terminals_search_path_is_found(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(mode=0o700)
        shutil.copy(self.binary, bin_dir / "agy")
        os.chmod(bin_dir / "agy", 0o755)
        buf = io.StringIO()
        with mock.patch("vbear.runtime.daemon.cli_search_path", lambda: str(bin_dir)), \
                mock.patch.object(cc, "run", return_value=0) as run, contextlib.redirect_stdout(buf):
            self.assertEqual(cc.main(None, str(self.out / "r.json")), 0)
        self.assertEqual(run.call_args.args[1], VERSION)

    def test_no_agy_on_the_search_path_is_said_in_words_and_exit_code_is_2(self):
        buf = io.StringIO()
        with mock.patch("vbear.runtime.daemon.cli_search_path", lambda: str(self.tmp / "none")), contextlib.redirect_stdout(buf):
            self.assertEqual(cc.main(None, str(self.out / "r.json")), 2)
        self.assertIn("找不到 AGY", buf.getvalue())
        self.assertIn("結果：沒有跑完", buf.getvalue())


class VerifierTests(unittest.TestCase):
    """agy_verify.AgyChatVerifier runs the check in a child process and counts a pass only when the version is on the verified list
    afterwards, as the Codex one does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbx-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "st"
        self.state.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state), "HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def run_verifier(self, rc, *, report=None, record=False):
        verifier = agy_verify.AgyChatVerifier()
        done = mock.Mock(returncode=rc, stdout="", stderr="")
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"], seen["kw"] = argv, kw
            out = Path(argv[argv.index("--out") + 1])
            if report is not None:
                out.write_text(json.dumps(report))
                out.chmod(0o600)
            if record:
                cfg.write_private(self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE, json.dumps({"versions": {
                    VERSION: {"passed": True, "verified_at": "2026-11-09T00:00:00+0000", "report": str(out)}}}))
            return done
        with mock.patch.object(claude_verify.subprocess, "run", fake_run):
            verifier._run("/unused/agy", VERSION)
        return verifier.status(), seen

    def test_the_child_is_the_agy_chat_check_with_the_shared_folder_writing_to_the_reports_folder(self):
        ok = {"mode": "agy-chat", "passed": True, "agy_version": VERSION, "shared": "passed", "shared_steps": {"a": {"pass": True}}}
        status_, seen = self.run_verifier(0, report=ok, record=True)
        argv = seen["argv"]
        self.assertEqual(argv[1:3], ["-B", "-m"])
        self.assertEqual(argv[argv.index("--mode") + 1], "agy-chat")
        self.assertIn("--shared", argv)
        self.assertEqual(Path(argv[argv.index("--out") + 1]), claude_verify.reports_dir() / f"agy-{VERSION}-chat.json")
        for banned in ("--claude", "--codex", "--agy"):
            self.assertNotIn(banned, argv)
        self.assertGreater(seen["kw"]["timeout"], claude_verify.CHAT_RUN_TIMEOUT, "AGY's turns are slow: it may run longer")
        self.assertEqual((status_["running"], status_["result"], status_["shared"]), (False, "passed", "passed"), status_)
        self.assertIn("AGY", status_["message"])

    def test_the_others_keep_their_timeout(self):
        from vbear import codex_verify
        self.assertIsNone(claude_verify.ChatVerifier.TIMEOUT)
        self.assertIsNone(codex_verify.CodexChatVerifier.TIMEOUT)

    def test_a_pass_needs_the_version_to_be_on_the_list(self):
        ok = {"mode": "agy-chat", "passed": True, "agy_version": VERSION}
        status_, _ = self.run_verifier(0, report=ok, record=False)
        self.assertEqual(status_["result"], "error")

    def test_a_failed_check_names_what_failed(self):
        report = {"mode": "agy-chat", "passed": False, "agy_version": VERSION,
                  "checks": {"edit_works": {"pass": False}, "initialize": {"pass": True}}}
        status_, _ = self.run_verifier(1, report=report)
        self.assertEqual((status_["result"], status_["failed"]), ("failed", ["edit_works"]))
        self.assertIn("edit_works", status_["message"])

    def test_a_check_that_could_not_run_says_why_in_the_reports_own_words(self):
        report = {"mode": "agy-chat", "passed": False, "agy_version": None, "error": "AGY 還沒登入。請到「開始設定」按 AGY 的「登入」"}
        status_, _ = self.run_verifier(2, report=report)
        self.assertEqual(status_["result"], "failed")
        self.assertIn("登入", status_["message"])
        status_, _ = self.run_verifier(2)
        self.assertIn("沒有完成", status_["message"])

    def test_a_pass_makes_the_next_look_at_agy_fresh(self):
        ok = {"mode": "agy-chat", "passed": True, "agy_version": VERSION}
        with mock.patch.object(agy_chat_env, "invalidate") as inv:
            self.run_verifier(0, report=ok, record=True)
        inv.assert_called()

    def test_the_console_has_one_and_the_chat_service_is_given_it(self):
        from vbear import server
        source = Path(server.__file__).read_text()
        self.assertIn("self.agy_chat_verifier = agy_verify.AgyChatVerifier()", source)
        self.assertIn('agy_verifier=getattr(self, "agy_chat_verifier", None)', source)


if __name__ == "__main__":
    unittest.main()
