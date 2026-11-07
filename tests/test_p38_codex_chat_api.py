"""v0.13 P38-5: the chat endpoints choose the engine from the role card's AI tool. A console in front of a runtime daemon
whose Codex is the fake one of tests/fake_codex_app_server.py (replaying the recordings made with 0.163.0). Synthetic HOME
and VBEAR_HOME under /tmp; nothing reaches a model or the network, and the real codex is never run."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.test_chat_api import Http
from tests.test_p38_codex_chat_daemon import THREAD, VERSION, CodexCase
from vbear import agent_profiles as ap, chat_service, claude_verify, config as cfg, server
from vbear.runtime import chat_store as cs, cli_versions, memory_rules

READY = {"state": "ready", "installed": True, "version": VERSION, "verified": True, "logged_in": True,
         "admin_policy_ok": True, "why": "", "verified_versions": [VERSION]}


def status(state, **over):
    base = dict(READY, state=state)
    base.update({"not_installed": dict(installed=False, version=None, verified=False, logged_in=None, admin_policy_ok=None,
                                       why="找不到用官方安裝指令裝的 Codex。請到「開始設定」安裝 Codex。"),
                 "unverified": dict(verified=False, logged_in=None, admin_policy_ok=None, verified_versions=[],
                                    why="Codex 0.163.0 還沒有通過聊天驗證。"),
                 "policy": dict(admin_policy_ok=False, why="這台 Mac 上有管理員政策：/etc/codex"),
                 "folder": dict(why="聊天用的 Codex 資料夾裡有 config.toml，不是 VBear 放的"),
                 "version_unreadable": dict(why="Codex 0.163.0 沒有印出剛好是 codex-cli 0.163.0 的版本行"),
                 "not_logged_in": dict(logged_in=False, why="聊天用的 Codex 還沒有登入。請到「開始設定」按「讓聊天用的 Codex 登入」。"),
                 "ready": {}}[state])
    base.update(over)
    return base


class FakeVerifier:
    """Stands for claude_verify.ChatVerifier / codex_verify.CodexChatVerifier: records what it was asked."""

    def __init__(self):
        self.started = []

    def status(self):
        return {"running": bool(self.started)}

    def start(self, binary, version):
        self.started.append((binary, version))
        return {"running": True, "version": version}


class ApiCase(CodexCase, Http):
    def setUp(self):
        super().setUp()
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for src in conf["sources"]:
            src["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.console = server.Console(self.httpd.server_address[1])
        self.token = self.console.auth_token
        self.httpd.RequestHandlerClass = server.make_handler(self.console)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.svc = self.console.chat_service()
        self.svc.codex = lambda: dict(READY)
        self.svc.codex_binary = lambda: (str(self.binary), VERSION)
        self.svc.claude = lambda: (None, None, "測試裡沒有 Claude Code")
        self.svc.restart_pause = 0.05
        self.svc.delete_pause = 0.05
        self.emp = self.card("虛構的 Codex 員工")

    def card(self, name, tool="codex", **over):
        body = {"name": name, "position": "pm", "model": {"tool": tool}}
        body.update(over)
        return ap.save_profile(None, body)["id"]

    def open_http(self, profile=None):
        status_, out = self.call("/api/chats", "POST", {"profile_id": profile or self.emp})
        self.assertEqual(status_, 201, out)
        return out["chat"]["id"]

    def say(self, chat_id, text="你好"):
        return self.call(f"/api/chats/{chat_id}/messages", "POST", {"text": text})

    def view(self, chat_id, after=0):
        status_, out = self.call(f"/api/chats/{chat_id}?after={after}")
        self.assertEqual(status_, 200, out)
        return out

    def wait_view(self, chat_id, pred, what):
        def got():
            v = self.view(chat_id)
            return v if pred(v) else None
        return self.wait(got, what)

    def wait_http_card(self, chat_id):
        return self.wait_view(chat_id, lambda v: v["live"] and v["live"]["cards"], "a card")["live"]["cards"][0]

    def wait_http_turn(self, chat_id, n):
        v = self.wait_view(chat_id, lambda v: any(r["kind"] == "turn_ended" and r["turn"] == n for r in v["records"]),
                           f"the end of turn {n}")
        return next(r for r in v["records"] if r["kind"] == "turn_ended" and r["turn"] == n)

    def answer_http(self, chat_id, card, decision, value=None):
        body = {"card_id": card["card_id"], "token": card["token"], "decision": decision}
        if value is not None:
            body["value"] = value
        return self.call(f"/api/chats/{chat_id}/answer", "POST", body)


class CodexChatThroughHttpTests(ApiCase):
    def test_a_codex_card_opens_a_codex_chat_and_the_whole_way_works(self):
        self.configure(start=[1])
        chat_id = self.open_http()
        self.assertEqual(cs.load(self.base, chat_id)["engine"], "codex-chat")
        status_, out = self.say(chat_id, "run ls")
        self.assertEqual((status_, out["ok"], out["turn"], out["process"]), (202, True, 1, "new"), out)
        card = self.wait_http_card(chat_id)
        self.assertEqual((card["tool"], card["editable"], card["input"]["command"]), ("command", "command", "/bin/zsh -lc 'ls -a'"))
        status_, lst = self.call("/api/chats")
        mine = next(c for c in lst["chats"] if c["id"] == chat_id)
        self.assertEqual((mine["engine"], mine["waiting"], mine["open"]), ("codex-chat", True, True))
        status_, out = self.answer_http(chat_id, card, "allow")
        self.assertEqual((status_, out["ok"]), (200, True))
        end = self.wait_http_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["estimate"], end["tokens"], end["cost_usd"]), ("result", True, 36426, "0.04"))
        v = self.view(chat_id)
        self.assertEqual((v["chat"]["engine"], v["card"]["tool"], v["card"]["engine"], v["card"]["can_chat"]),
                         ("codex-chat", "codex", "codex-chat", True))
        ready = next(r for r in v["records"] if r["kind"] == "session_ready")
        self.assertEqual(ready["cli_version"], VERSION, "a neutral field, not claude_code_version")
        self.assertNotIn("claude_code_version", ready)
        self.assertEqual(next(r for r in v["records"] if r["kind"] == "session_bound")["thread_id"], THREAD)
        self.assertTrue(any(r["kind"] == "plan_usage" for r in v["records"]))

    def test_a_card_with_a_model_of_its_own_names_it_to_codex(self):
        mine = self.card("有模型的員工", model={"tool": "codex", "model_id": "gpt-test-model"})
        self.configure(start=[0])
        chat_id = self.open_http(mine)
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        begin = next(x for x in self.stdin() if x.get("method") == "thread/start")
        self.assertEqual(begin["params"]["model"], "gpt-test-model")

    def test_a_card_without_a_model_names_none(self):
        self.configure(start=[0])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        begin = next(x for x in self.stdin() if x.get("method") == "thread/start")
        self.assertNotIn("model", begin["params"])

    def test_the_cards_own_instructions_go_in_and_the_positions_default_does_not(self):
        mine = self.card("有指示的員工", instructions="先說結論，再說理由。")
        self.configure(start=[0])
        chat_id = self.open_http(mine)
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        begin = next(x for x in self.stdin() if x.get("method") == "thread/start")
        self.assertEqual(begin["params"]["developerInstructions"], "先說結論，再說理由。\n\n" + memory_rules.block([]))   # P42-1: then the memory paragraph

    def test_deleting_a_codex_chat_keeps_the_copy_codex_made_in_its_own_folder(self):
        self.configure(start=[0])
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        copy = self.chat_home / "sessions" / "2026" / "rollout-fake.jsonl"
        copy.parent.mkdir(parents=True)
        copy.write_text("{}")
        status_, out = self.call(f"/api/chats/{chat_id}", "DELETE")
        self.assertEqual((status_, out["deleted"]), (200, chat_id), out)
        self.assertFalse((self.base / "chats" / chat_id).exists())
        self.assertTrue(copy.exists(), "Codex's own copy is not VBear's to delete (said in the confirmation)")


class NoRuntimeOfItsOwnTests(ApiCase):
    def test_the_console_in_front_of_the_case_daemon_never_starts_a_daemon_itself(self):
        self.assertFalse(self.console.runtime.autostart)


class CardGateTests(ApiCase):
    def test_a_card_of_a_tool_that_cannot_chat_is_refused_and_says_which_and_what_can(self):
        for tool, label in (("grok", "Grok"), ("agy", "AGY"), ("shared", "共用")):
            with self.subTest(tool=tool):
                other = self.card(f"{tool}員工", tool)
                status_, out = self.call("/api/chats", "POST", {"profile_id": other})
                self.assertEqual((status_, out["code"]), (409, "card_tool_unsupported"))
                self.assertIn(label, out["error"])
                self.assertIn("Claude Code", out["error"])
                self.assertIn("Codex", out["error"])
        self.assertEqual(cs.list_ids(self.base), [])

    def test_the_list_marks_each_card_with_whether_it_may_chat_and_with_which_engine(self):
        off = self.card("停用員工", enabled=False)
        grok = self.card("Grok 員工", "grok")
        claude = self.card("Claude 員工", "claude")
        status_, lst = self.call("/api/chats")
        by = {c["id"]: c for c in lst["cards"]}
        self.assertEqual((by[self.emp]["can_chat"], by[self.emp]["engine"]), (True, "codex-chat"))
        self.assertEqual((by[claude]["can_chat"], by[claude]["engine"]), (True, "claude-chat"))
        self.assertEqual((by[off]["can_chat"], by[off]["code"]), (False, "card_disabled"))
        self.assertEqual((by[grok]["can_chat"], by[grok]["code"], by[grok]["engine"]), (False, "card_tool_unsupported", None))

    def test_a_card_whose_tool_changed_after_the_chat_began_cannot_send_and_nothing_starts(self):
        chat_id = self.open_http()
        ap.save_profile(self.emp, {"model": {"tool": "claude"}})
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "card_tool_changed"))
        self.assertIn("新的聊天", out["error"])
        ap.save_profile(self.emp, {"model": {"tool": "grok"}})
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "card_tool_unsupported"))
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_a_claude_chat_whose_card_became_codex_cannot_send(self):
        claude = self.card("Claude 員工", "claude")
        chat_id = self.open_http(claude)
        self.assertEqual(cs.load(self.base, chat_id)["engine"], "claude-chat")
        ap.save_profile(claude, {"model": {"tool": "codex"}})
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "card_tool_changed"))
        self.assertEqual(self.fake_log(), [])

    def test_a_card_switched_off_cannot_send(self):
        chat_id = self.open_http()
        ap.save_profile(self.emp, {"enabled": False})
        self.assertEqual(self.say(chat_id)[1]["code"], "card_disabled")
        self.assertEqual(self.fake_log(), [])


class NotReadyTests(ApiCase):
    """The service says why before it asks the daemon, in the page's words, and starts nothing."""

    def test_each_state_that_is_not_ready_is_refused_with_its_reason(self):
        want = {"not_installed": ("invalid_binary", "安裝 Codex"), "unverified": ("unverified", "驗證"),
                "policy": ("admin_policy", "/etc/codex"), "folder": ("codex_home", "config.toml"),
                "version_unreadable": ("codex_version", "版本"), "not_logged_in": ("not_logged_in", "讓聊天用的 Codex 登入")}
        chat_id = self.open_http()
        self.svc.codex_binary = lambda: None
        for state, (code, word) in want.items():
            with self.subTest(state=state):
                self.svc.codex = lambda state=state: status(state)
                status_, out = self.say(chat_id)
                self.assertEqual((status_, out["code"]), (409, code), out)
                self.assertIn(word, out["error"])
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_a_ready_state_with_no_binary_is_refused_too(self):
        chat_id = self.open_http()
        self.svc.codex_binary = lambda: None
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "invalid_binary"))
        self.assertEqual(self.fake_log(), [])

    def test_the_daemon_still_refuses_what_the_service_let_through(self):
        # the service's state is only a courtesy; the daemon checks the verified list itself
        chat_id = self.open_http()
        with mock.patch.object(cli_versions, "CODEX_CHAT_VERIFIED_VERSIONS", ()):
            status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "unverified"))
        self.assertEqual(self.fake_log(), [])


class SupportTests(ApiCase):
    def test_the_answer_names_both_engines_and_keeps_the_claude_keys(self):
        status_, out = self.call("/api/chat-support")
        self.assertEqual(status_, 200, out)
        s = out["support"]
        self.assertEqual((s["engine"], s["codex"]["engine"], s["codex"]["state"]), ("claude-chat", "codex-chat", "ready"))
        for key in ("detected", "verified", "state", "message", "policy", "verify", "money"):
            self.assertIn(key, s)
        self.assertIn("ChatGPT", s["codex"]["money"])
        self.assertIn("估算", s["codex"]["money"])
        self.assertIn("不是帳單", s["codex"]["money"])
        status_, lst = self.call("/api/chats")
        self.assertEqual(lst["support"]["codex"]["engine"], "codex-chat")

    def test_every_state_of_codex_reaches_the_page_as_the_service_found_it(self):
        for state in ("not_installed", "unverified", "policy", "folder", "version_unreadable", "not_logged_in", "ready"):
            with self.subTest(state=state):
                self.svc.codex = lambda state=state: status(state)
                got = self.call("/api/chat-support")[1]["support"]["codex"]
                self.assertEqual((got["state"], got["why"]), (state, status(state)["why"]))

    def test_the_codex_part_carries_the_state_of_its_own_verification(self):
        self.svc.codex_verifier = FakeVerifier()
        got = self.call("/api/chat-support")[1]["support"]
        self.assertEqual(got["codex"]["verify"], {"running": False})
        self.svc.codex_verifier.start("b", VERSION)
        got = self.call("/api/chat-support")[1]["support"]
        self.assertEqual(got["codex"]["verify"], {"running": True})
        self.assertEqual(got["verify"], {"running": False}, "Claude's verifier is not Codex's")


class VerifyTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.svc.codex_verifier = FakeVerifier()
        self.svc.codex = lambda: status("unverified", version=VERSION)
        p = mock.patch.object(chat_service.admin_policy, "check_codex", return_value=mock.Mock(ok=True))
        p.start()
        self.addCleanup(p.stop)

    def post(self, body):
        return self.call("/api/chat-support/verify", "POST", body)

    def test_codex_is_verified_by_its_own_check(self):
        status_, out = self.post({"engine": "codex"})
        self.assertEqual((status_, out["ok"]), (202, True), out)
        self.assertEqual(out["status"], {"running": True, "version": VERSION})
        self.assertEqual(len(self.svc.codex_verifier.started), 1)
        self.assertEqual(self.svc.codex_verifier.started[0][1], VERSION)

    def test_a_version_the_page_did_not_see_is_refused(self):
        status_, out = self.post({"engine": "codex", "version": "0.1.0"})
        self.assertEqual((status_, out["code"]), (409, "version_changed"))
        self.assertEqual(self.svc.codex_verifier.started, [])
        self.assertEqual(self.post({"engine": "codex", "version": VERSION})[0], 202)

    def test_a_verified_version_is_not_checked_again(self):
        self.svc.codex = lambda: status("ready")
        status_, out = self.post({"engine": "codex"})
        self.assertEqual((status_, out["already_verified"]), (202, True))
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_a_check_that_could_not_pass_is_not_started(self):
        for state, code in (("not_installed", "invalid_binary"), ("policy", "admin_policy"), ("version_unreadable", "codex_version"),
                            ("folder", "codex_home")):
            with self.subTest(state=state):
                self.svc.codex = lambda state=state: status(state, verified=False)
                status_, out = self.post({"engine": "codex"})
                self.assertEqual((status_, out["code"]), (409, code), out)
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_an_administrator_policy_found_now_stops_it_before_any_model_call(self):
        denied = mock.Mock(ok=False, reason=lambda: "這台 Mac 上有管理員政策：/etc/codex")
        with mock.patch.object(chat_service.admin_policy, "check_codex", return_value=denied):
            status_, out = self.post({"engine": "codex"})
        self.assertEqual((status_, out["code"]), (409, "admin_policy"))
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_a_version_that_passed_before_is_not_checked_again_whatever_else_is_wrong_now(self):
        self.svc.codex = lambda: status("not_logged_in")
        status_, out = self.post({"engine": "codex"})
        self.assertEqual((status_, out["already_verified"]), (202, True))
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_an_engine_that_does_not_exist_and_other_keys_are_bad_requests(self):
        for bad in ({"engine": "grok"}, {"engine": "codex-chat"}, {"engine": 5}, {"engine": "codex", "x": 1}, {"x": 1}):
            with self.subTest(bad=bad):
                self.assertEqual(self.post(bad)[0], 400, bad)
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_no_engine_still_means_claude_code(self):
        verifier = FakeVerifier()
        self.svc.verifier = verifier
        self.svc.claude = lambda: ("/x/claude", "2.1.318", "")
        with mock.patch.object(chat_service.admin_policy, "check_claude", return_value=mock.Mock(ok=True)):
            status_, out = self.post({})
        self.assertEqual((status_, out["ok"]), (202, True), out)
        self.assertEqual(verifier.started, [("/x/claude", "2.1.318")])
        self.assertEqual(self.svc.codex_verifier.started, [])

    def test_a_console_without_the_codex_verifier_says_so(self):
        self.svc.codex_verifier = None
        status_, out = self.post({"engine": "codex"})
        self.assertEqual((status_, out["code"]), (503, "unavailable"))


class WordsTests(unittest.TestCase):
    def test_the_new_codes_have_sentences_and_none_is_bare(self):
        for code in ("card_tool_unsupported", "card_tool_changed", "codex_version", "not_logged_in", "codex_home"):
            status_, text = chat_service.CODE_TEXT[code]
            self.assertTrue(409 == status_ and text.endswith("。"), code)
            self.assertNotIn(code, chat_service.explain(code))
        self.assertNotIn("card_not_claude", chat_service.CODE_TEXT)
        self.assertIn("Codex", chat_service.CODE_TEXT["not_logged_in"][1])
        self.assertIn("新的聊天", chat_service.CODE_TEXT["card_tool_changed"][1])

    def test_the_sentences_that_both_engines_share_do_not_name_only_claude_code(self):
        for code in ("unverified", "unsupported_version", "drift", "invalid_binary", "admin_policy", "violation"):
            if code in chat_service.CODE_TEXT:
                text = chat_service.CODE_TEXT[code][1]
                self.assertTrue("Claude Code" not in text or "Codex" in text, code)

    def test_every_code_the_codex_session_can_give_has_a_sentence(self):
        import re
        text = (Path(server.__file__).resolve().parent / "runtime" / "codex_chat_session.py").read_text()
        found = set(re.findall(r'return "([a-z_]+)", ', text)) - {"alive", "unknown"}
        self.assertTrue({"gone", "expired", "bad_token", "bad_request", "refused"} <= found, found)
        self.assertEqual(sorted(found - set(chat_service.CODE_TEXT)), [])


class SessionReadyTests(unittest.TestCase):
    def test_the_old_field_name_still_reads_and_the_neutral_one_does_too(self):
        old = {"seq": 2, "at": 1.0, "kind": "session_ready", "claude_code_version": "2.1.318", "permission_mode": "default",
               "model": "haiku"}
        new = {"seq": 2, "at": 1.0, "kind": "session_ready", "cli_version": "0.163.0", "permission_mode": "untrusted",
               "model": "gpt-x"}
        self.assertIsNone(cs.record_problem(old))
        self.assertIsNone(cs.record_problem(new))
        both = dict(new, claude_code_version="2.1.318")
        self.assertIsNotNone(cs.record_problem(both))
        neither = {k: v for k, v in new.items() if k != "cli_version"}
        self.assertIsNotNone(cs.record_problem(neither))
        self.assertIsNotNone(cs.record_problem(dict(new, cli_version=5)))


class CodexVerifierTests(unittest.TestCase):
    """codex_verify.CodexChatVerifier runs the check in a child process and counts a pass only when the version is on the
    verified list afterwards, as the Claude one does."""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(prefix="vbx-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "st"
        self.state.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state), "HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def run_verifier(self, rc, *, report=None, record=False):
        from vbear import codex_verify
        verifier = codex_verify.CodexChatVerifier()
        done = mock.Mock(returncode=rc, stdout="", stderr="")
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"] = argv
            out = Path(argv[argv.index("--out") + 1])
            if report is not None:
                out.write_text(json.dumps(report))
                out.chmod(0o600)
            if record:
                cfg.write_private(self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE, json.dumps({"versions": {
                    VERSION: {"passed": True, "verified_at": "2026-11-06T00:00:00+0000", "report": str(out)}}}))
            return done
        with mock.patch.object(claude_verify.subprocess, "run", fake_run):
            verifier._run("/unused/codex", VERSION)
        return verifier.status(), seen["argv"]

    def test_the_child_is_the_codex_chat_check_writing_to_the_reports_folder(self):
        ok = {"mode": "codex-chat", "passed": True, "codex_version": VERSION}
        status_, argv = self.run_verifier(0, report=ok, record=True)
        self.assertEqual(argv[1:3], ["-B", "-m"])
        self.assertEqual(argv[argv.index("--mode") + 1], "codex-chat")
        self.assertEqual(Path(argv[argv.index("--out") + 1]), claude_verify.reports_dir() / f"codex-{VERSION}-chat.json")
        self.assertNotIn("--claude", argv)
        self.assertEqual((status_["running"], status_["result"]), (False, "passed"), status_)
        self.assertIn("Codex", status_["message"])

    def test_a_pass_needs_the_version_to_be_on_the_list(self):
        ok = {"mode": "codex-chat", "passed": True, "codex_version": VERSION}
        status_, _ = self.run_verifier(0, report=ok, record=False)
        self.assertEqual(status_["result"], "error")

    def test_a_failed_check_names_what_failed(self):
        report = {"mode": "codex-chat", "passed": False, "codex_version": VERSION,
                  "checks": {"edit_works": {"pass": False}, "initialize": {"pass": True}}}
        status_, _ = self.run_verifier(1, report=report)
        self.assertEqual((status_["result"], status_["failed"]), ("failed", ["edit_works"]))
        self.assertIn("edit_works", status_["message"])

    def test_a_check_that_could_not_run_says_why_in_the_reports_own_words(self):
        report = {"mode": "codex-chat", "passed": False, "codex_version": None,
                  "error": "聊天用的 Codex 還沒有登入：請先到「開始設定」按「讓聊天用的 Codex 登入」"}
        status_, _ = self.run_verifier(2, report=report)
        self.assertEqual(status_["result"], "failed")
        self.assertIn("讓聊天用的 Codex 登入", status_["message"])
        status_, _ = self.run_verifier(2)
        self.assertIn("沒有完成", status_["message"])

    def test_a_pass_makes_the_next_look_at_codex_fresh(self):
        from vbear.runtime import codex_chat_env
        ok = {"mode": "codex-chat", "passed": True, "codex_version": VERSION}
        with mock.patch.object(codex_chat_env, "invalidate") as inv:
            self.run_verifier(0, report=ok, record=True)
        inv.assert_called()


if __name__ == "__main__":
    unittest.main()
