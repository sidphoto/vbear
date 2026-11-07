"""P43-2 (ADR 0009): the shared folder for a Codex employee, and the check it needs, from the person's side. The page's switch for a Codex card asks
the person to confirm that what the employee reads goes to OpenAI; a message of an employee whose switch is on is sent only for a version of
the AI tool that passed the chat check with the shared folder (``shared_unverified``, said by the console before anything is sent and by the
daemon again), the chat page says so and the check button asks for the check again; an employee whose switch is off chats as always. Every
name, card and file is made up; the AI tools are the fakes of tests/."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests import chat_fixtures as cf
from tests import test_chat_api as tca
from tests import test_p38_codex_chat_api as cxa
from tests.test_chat_daemon import clean
from tests.test_p38_codex_chat_daemon import VERSION as CODEX_VERSION
from vbear import chat_service, config as cfg
from vbear.runtime import chat_store as cs, cli_versions, codex_chat_protocol as ccp, memory_rules as mr, shared_rules as sr


class CodexCase(cxa.ApiCase):
    checked = True

    def setUp(self):
        super().setUp()
        self.ok = mock.patch.object(cli_versions, "shared_verified", return_value=self.checked)
        self.ok.start()
        self.addCleanup(self.ok.stop)
        self.shared = sr.shared_path(cfg.state_dir())
        self.meta = cfg.state_dir() / "shared-meta"

    def switch(self, pid, on=True, **extra):
        return self.call("/api/shared/cards", "POST", {"profile_id": pid, "on": on, **extra})

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def configs(self, index=-1):
        argv = self.starts()[index]["argv"]
        return [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]


class SwitchTests(CodexCase):
    def test_a_codex_card_needs_the_person_to_confirm_that_files_go_to_openai(self):
        for body in ({}, {"confirm_company": False}):
            status, out = self.switch(self.emp, **body)
            self.assertEqual((status, out["code"]), (409, "shared_confirm"), body)
            self.assertEqual(out["warn"], ["send_to_openai"])
            self.assertIn("OpenAI", out["warn_text"][0])
        self.assertFalse(self.meta.exists(), "nothing was written")
        self.assertFalse(os.path.lexists(self.shared), "no folder was made")

    def test_with_the_confirmation_it_is_on_and_the_folder_is_made_and_the_log_names_no_file(self):
        status, out = self.switch(self.emp, confirm_company=True)
        self.assertEqual((status, out["on"]), (200, True), out)
        self.assertEqual(os.lstat(self.shared).st_mode & 0o7777, 0o700)
        self.assertEqual(json.loads((self.meta / "settings.json").read_text())["cards_on"], [self.emp])
        [line] = [json.loads(x) for x in (self.meta / "log.jsonl").read_text().splitlines()]
        self.assertEqual((line["what"], line["profile_id"], line["how"]), ("card_on", self.emp, "page"))
        self.assertEqual(set(line), {"at", "what", "profile_id", "how"})

    def test_off_needs_no_confirmation_and_deletes_nothing(self):
        self.switch(self.emp, confirm_company=True)
        (Path(self.shared) / "keep.md").write_text("fictional")
        status, out = self.switch(self.emp, False)
        self.assertEqual((status, out["on"]), (200, False), out)
        self.assertEqual((Path(self.shared) / "keep.md").read_text(), "fictional")

    def test_the_confirmation_must_be_a_real_boolean_and_other_keys_are_refused(self):
        for extra in ({"confirm_company": "yes"}, {"confirm_company": 1}, {"confirm_company": None}, {"how": "group"}, {"path": "/etc"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.switch(self.emp, **extra)[0], 400)
        self.assertFalse(self.meta.exists())

    def test_a_card_of_a_tool_that_cannot_chat_is_still_refused(self):
        grok = self.card("Grok 員工", "grok")
        status, out = self.switch(grok, confirm_company=True)
        self.assertEqual(status, 400, out)

    def test_the_card_the_service_reads_says_yes_only_for_the_engines_that_have_the_folder(self):
        self.switch(self.emp, confirm_company=True)
        self.assertTrue(self.svc._shared(self.emp, "codex-chat"))
        self.assertFalse(self.svc._shared(self.emp, "grok-chat"))
        self.assertFalse(self.svc._shared("emp-nobody", "codex-chat"))

    def test_the_page_lists_the_codex_card_as_on_with_the_company_and_whether_it_was_checked(self):
        self.switch(self.emp, confirm_company=True)
        status, out = self.call("/api/shared")
        self.assertEqual(status, 200, out)
        [row] = [c for c in out["cards"] if c["profile_id"] == self.emp]
        self.assertEqual((row["company"], row["on"], row["can_chat"], row["verified"]), ("OpenAI", True, True, True))
        self.ok.stop()
        with mock.patch.object(cli_versions, "shared_verified", return_value=False):
            [row] = [c for c in self.call("/api/shared")[1]["cards"] if c["profile_id"] == self.emp]
        self.assertIs(row["verified"], False)
        self.ok.start()

    def test_a_version_the_service_cannot_read_is_unknown_not_unchecked(self):
        self.svc.codex_binary = lambda: None
        [row] = [c for c in self.call("/api/shared")[1]["cards"] if c["profile_id"] == self.emp]
        self.assertIsNone(row["verified"])


class ChatTests(CodexCase):
    def talk(self, chat_id, n, text="你好"):
        status, out = self.say(chat_id, text)
        self.assertEqual(status, 202, out)
        end = self.wait_http_turn(chat_id, n)
        self.assertEqual(end["reason"], "result")

    def test_a_checked_version_with_the_switch_on_gets_the_root_and_is_told(self):
        self.switch(self.emp, confirm_company=True)
        self.configure(start=[0])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.assertEqual(self.configs()[-1], ccp.shared_root_setting(self.shared))
        begin = next(x for x in self.stdin() if x.get("method") == "thread/start")
        self.assertEqual(begin["params"]["developerInstructions"], mr.combine(None, mr.block([]), sr.block(self.shared)))
        turn = next(x for x in self.stdin() if x.get("method") == "turn/start")
        self.assertEqual(turn["params"]["sandboxPolicy"]["writableRoots"], [self.shared])
        self.assertEqual(cs.prompt_start(cfg.state_dir(), chat_id)["sha"], mr.prompt_sha(None, mr.block([]), sr.block(self.shared)))

    def test_with_the_switch_off_nothing_of_it_is_there(self):
        self.configure(start=[0])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.assertNotIn("writable_roots", json.dumps(self.starts()))
        begin = next(x for x in self.stdin() if x.get("method") == "thread/start")
        self.assertEqual(begin["params"]["developerInstructions"], mr.block([]))
        self.assertFalse(os.path.lexists(self.shared))

    def test_a_message_through_the_group_and_dispatch_doors_follows_the_same_switch(self):
        self.switch(self.emp, confirm_company=True)
        self.configure(start=[0])
        chat_id = self.open_http()
        self.assertTrue(self.svc.send_for_dispatch(chat_id, "接力的一句話", {"dispatch": "d-0123456789ab", "step": 1})["turn"])
        self.wait_http_turn(chat_id, 1)
        self.assertEqual(self.configs()[-1], ccp.shared_root_setting(self.shared))

    def test_a_folder_that_is_not_right_stops_the_message_with_words_for_a_person(self):
        self.switch(self.emp, confirm_company=True)
        os.chmod(self.shared, 0o755)
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_unsafe"))
        self.assertNotIn(self.shared, json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.fake_log(), [])

    def test_the_chat_page_says_the_folder_is_on_and_usable(self):
        chat_id = self.open_http()
        self.assertEqual(self.view(chat_id)["shared"], {"on": False, "usable": False, "code": None})
        self.switch(self.emp, confirm_company=True)
        self.assertEqual(self.view(chat_id)["shared"], {"on": True, "usable": True, "code": None})


class NotCheckedTests(CodexCase):
    checked = False

    def test_the_message_is_refused_before_anything_is_sent_made_or_written(self):
        self.switch(self.emp, confirm_company=True)
        self.configure(start=[0])
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_unverified"))
        self.assertIn("共用資料夾", out["error"])
        self.assertIn(CODEX_VERSION, out["error"])
        self.assertIn("ChatGPT", out["error"])
        self.assertEqual(self.fake_log(), [], "no process")
        self.assertEqual(cs.read_events(cfg.state_dir(), chat_id).records[-1]["kind"], "chat_created")

    def test_the_card_off_chats_as_always_on_the_same_version(self):
        self.configure(start=[0])
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual(status, 202, out)
        self.assertEqual(self.wait_http_turn(chat_id, 1)["reason"], "result")

    def test_the_chat_page_says_so_in_a_code_the_page_can_act_on(self):
        chat_id = self.open_http()
        self.switch(self.emp, confirm_company=True)
        self.assertEqual(self.view(chat_id)["shared"], {"on": True, "usable": False, "code": "shared_unverified"})

    def test_the_daemon_refuses_it_again_if_the_console_did_not(self):
        self.switch(self.emp, confirm_company=True)
        self.configure(start=[0])
        chat_id = self.open_http()
        self.svc._shared_verified = lambda engine, version: True        # a console that let it through
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_unverified"), out)
        self.assertEqual(self.fake_log(), [])


class VerifyTests(CodexCase):
    def setUp(self):
        super().setUp()
        self.svc.codex_verifier = cxa.FakeVerifier()
        p = mock.patch.object(chat_service.admin_policy, "check_codex", return_value=mock.Mock(ok=True))
        p.start()
        self.addCleanup(p.stop)

    def post(self, body):
        return self.call("/api/chat-support/verify", "POST", body)

    def test_a_chat_verified_version_is_not_checked_again_unless_the_shared_folder_is_asked_for(self):
        self.svc.codex = lambda: cxa.status("ready")
        status, out = self.post({"engine": "codex"})
        self.assertEqual((status, out["already_verified"]), (202, True))
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_with_the_shared_folder_asked_for_a_version_that_lacks_it_is_checked(self):
        self.svc.codex = lambda: cxa.status("ready")
        with mock.patch.object(cli_versions, "shared_verified", return_value=False):
            status, out = self.post({"engine": "codex", "shared": True})
        self.assertEqual((status, out["ok"]), (202, True), out)
        self.assertNotIn("already_verified", out)
        self.assertEqual(self.svc.codex_verifier.started, [(self.svc.codex_verifier.started[0][0], CODEX_VERSION)])

    def test_with_the_shared_folder_asked_for_a_version_that_has_it_is_not_checked_again(self):
        self.svc.codex = lambda: cxa.status("ready")
        status, out = self.post({"engine": "codex", "shared": True})
        self.assertEqual((status, out["already_verified"]), (202, True))
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_the_check_is_not_started_when_it_could_not_pass(self):
        with mock.patch.object(cli_versions, "shared_verified", return_value=False):
            self.svc.codex = lambda: cxa.status("not_logged_in")
            status, out = self.post({"engine": "codex", "shared": True})
            self.assertEqual((status, out["code"]), (409, "not_logged_in"), out)
            self.svc.codex = lambda: cxa.status("ready")
            denied = mock.Mock(ok=False, reason=lambda: "這台 Mac 上有管理員政策")
            with mock.patch.object(chat_service.admin_policy, "check_codex", return_value=denied):
                status, out = self.post({"engine": "codex", "shared": True})
            self.assertEqual((status, out["code"]), (409, "admin_policy"))
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_shared_must_be_a_boolean(self):
        for bad in ("yes", 1, None, []):
            self.assertEqual(self.post({"engine": "codex", "shared": bad})[0], 400, bad)
        self.assertEqual(self.svc.codex_verifier.started, [])


class ClaudeCase(tca.ApiCase):
    checked = True

    def setUp(self):
        super().setUp()
        self.ok = mock.patch.object(cli_versions, "shared_verified", return_value=self.checked)
        self.ok.start()
        self.addCleanup(self.ok.stop)
        self.shared = sr.shared_path(cfg.state_dir())

    def switch(self, pid, on=True, **extra):
        return self.call("/api/shared/cards", "POST", {"profile_id": pid, "on": on, **extra})


class ClaudeNotCheckedTests(ClaudeCase):
    checked = False

    def test_the_message_is_refused_before_anything_is_sent(self):
        self.switch(self.emp)
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_unverified"))
        self.assertIn(cf.VERSION, out["error"])
        self.assertIn("Claude Code", out["error"])
        self.assertEqual(self.fake_log(), [], "no process")

    def test_off_the_same_version_chats_as_always(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)

    def test_the_chat_page_says_so_and_the_shared_page_lists_the_card_as_unchecked(self):
        chat_id = self.open_http()
        self.switch(self.emp)
        self.assertEqual(self.view(chat_id)["shared"], {"on": True, "usable": False, "code": "shared_unverified"})
        [row] = [c for c in self.call("/api/shared")[1]["cards"] if c["profile_id"] == self.emp]
        self.assertIs(row["verified"], False)

    def test_the_version_is_looked_up_once_in_a_while_not_for_every_page_poll(self):
        calls = []
        real = self.svc.claude
        self.svc.claude = lambda: calls.append(1) or real()
        chat_id = self.open_http()
        self.switch(self.emp)
        for _ in range(5):
            self.view(chat_id)
        self.assertLessEqual(len(calls), 1)

    def test_a_version_that_cannot_be_read_is_not_called_unchecked(self):
        self.svc.claude = lambda: (None, None, "測試裡沒有 Claude Code")
        self.switch(self.emp)
        chat_id = self.open_http()
        self.assertEqual(self.view(chat_id)["shared"], {"on": True, "usable": True, "code": None})
        [row] = [c for c in self.call("/api/shared")[1]["cards"] if c["profile_id"] == self.emp]
        self.assertIsNone(row["verified"])


class ClaudeVerifyTests(ClaudeCase):
    def setUp(self):
        super().setUp()
        self.started = []
        self.svc.verifier = mock.Mock(start=lambda b, v: self.started.append((b, v)) or {"running": True, "version": v},
                                      status=lambda: {"running": False})
        p = mock.patch.object(chat_service.cli_versions, "CHAT_VERIFIED_VERSIONS", (cf.VERSION,))
        p.start()
        self.addCleanup(p.stop)

    def test_a_chat_verified_version_is_checked_again_only_when_the_shared_folder_is_asked_for_and_lacking(self):
        status, out = self.call("/api/chat-support/verify", "POST", {})
        self.assertEqual((status, out["already_verified"]), (202, True))
        status, out = self.call("/api/chat-support/verify", "POST", {"shared": True})
        self.assertEqual((status, out["already_verified"]), (202, True), "it has passed with the folder")
        self.assertEqual(self.started, [])
        with mock.patch.object(cli_versions, "shared_verified", return_value=False):
            status, out = self.call("/api/chat-support/verify", "POST", {"shared": True})
            self.assertEqual((status, out["status"]["running"]), (202, True), out)
            status, out = self.call("/api/chat-support/verify", "POST", {})
            self.assertEqual((status, out["already_verified"]), (202, True), "without asking, nothing changes")
        self.assertEqual(self.started, [(str(self.binary), cf.VERSION)])

    def test_the_body_is_closed(self):
        for bad in ({"shared": "yes"}, {"shared": 1}, {"shared": None}, {"shared": True, "x": 1}):
            self.assertEqual(self.call("/api/chat-support/verify", "POST", bad)[0], 400, bad)
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()
