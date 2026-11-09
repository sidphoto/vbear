"""v0.20 P46-3: the chat endpoints choose the engine from the role card's AI tool, and an AGY card chats. A console in front of a
runtime daemon whose AGY is the fake one of tests/fake_agy_acp.py (synthetic scripts, not recordings). Synthetic HOME and VBEAR_HOME
under /tmp; nothing reaches a model or the network, and the real agy is never run."""

from __future__ import annotations

import json
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests import agy_chat_fixtures as fx
from tests.test_chat_api import Http
from tests.test_p46_agy_chat_daemon import SESSION, USAGE_COST, VERSION, AgyCase
from vbear import agent_profiles as ap, chat_service, config as cfg, server
from vbear.runtime import agy_chat_protocol as acp, chat_engines, chat_store as cs, cli_versions

READY = {"state": "ready", "installed": True, "version": VERSION, "verified": True, "shared_verified": False,
         "admin_policy_ok": True, "hooks_ok": True, "why": "", "verified_versions": [VERSION]}


def status(state, **over):
    base = dict(READY, state=state)
    base.update({"not_installed": dict(installed=False, version=None, verified=False, admin_policy_ok=None, hooks_ok=None,
                                       why="找不到 AGY。請先安裝 AGY。"),
                 "unsupported": dict(verified=False, admin_policy_ok=None, hooks_ok=None, why="AGY 9.9.9 不是 VBear 能聊天的版本。"),
                 "unverified": dict(verified=False, admin_policy_ok=None, hooks_ok=None, verified_versions=[],
                                    why="AGY 1.5.3 的聊天模式還沒有通過驗證。"),
                 "policy": dict(admin_policy_ok=False, why="這台 Mac 上有管理員政策：/etc/antigravity"),
                 "hooks": dict(hooks_ok=False, why="你自己的 AGY 設定裡有會自動執行的指令。"),
                 "folder": dict(why="聊天用的 AGY 設定資料夾裡有 GEMINI.md，不是 VBear 放的"),
                 "version_unreadable": dict(why="AGY 沒有印出剛好是版本號的一行"),
                 "ready": {}}[state])
    base.update(over)
    return base


class FakeVerifier:
    """Stands for the AGY chat check's verifier: records what it was asked."""

    def __init__(self):
        self.started = []

    def status(self):
        return {"running": bool(self.started)}

    def start(self, binary, version):
        self.started.append((binary, version))
        return {"running": True, "version": version}


class ApiCase(AgyCase, Http):
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
        self.svc.agy = lambda: dict(READY)
        self.svc.agy_binary = lambda: (str(self.binary), VERSION)
        self.svc.claude = lambda: (None, None, "測試裡沒有 Claude Code")
        self.svc.codex = lambda: {"state": "not_installed", "installed": False, "version": None, "verified": False, "why": "測試裡沒有 Codex"}
        self.svc.codex_binary = lambda: None
        self.svc.restart_pause = 0.05
        self.svc.delete_pause = 0.05
        self.emp = self.card("虛構的 AGY 員工")

    def card(self, name, tool="agy", **over):
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


class AgyChatThroughHttpTests(ApiCase):
    def test_an_agy_card_opens_an_agy_chat_and_the_whole_way_works(self):
        self.configure("permission")
        chat_id = self.open_http()
        self.assertEqual(cs.load(self.base, chat_id)["engine"], "agy-chat")
        status_, out = self.say(chat_id, "run ls")
        self.assertEqual((status_, out["ok"], out["turn"], out["process"]), (202, True, 1, "new"), out)
        card = self.wait_http_card(chat_id)
        self.assertEqual((card["tool"], card["editable"], card["input"]), ("command", "command", {"command": "ls -a", "cwd": "."}))
        status_, lst = self.call("/api/chats")
        mine = next(c for c in lst["chats"] if c["id"] == chat_id)
        self.assertEqual((mine["engine"], mine["waiting"], mine["open"]), ("agy-chat", True, True))
        status_, out = self.answer_http(chat_id, card, "allow")
        self.assertEqual((status_, out["ok"]), (200, True))
        end = self.wait_http_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["estimate"], end["tokens"], end["cost_usd"]), ("result", True, 86000, USAGE_COST))
        v = self.view(chat_id)
        self.assertEqual((v["chat"]["engine"], v["card"]["tool"], v["card"]["engine"], v["card"]["can_chat"]),
                         ("agy-chat", "agy", "agy-chat", True))
        ready = next(r for r in v["records"] if r["kind"] == "session_ready")
        self.assertEqual(ready["cli_version"], VERSION, "a neutral field, not claude_code_version")
        self.assertEqual(next(r for r in v["records"] if r["kind"] == "session_bound")["thread_id"], SESSION)

    def test_a_card_with_a_model_of_its_own_still_chats_with_the_one_model_of_the_version(self):
        mine = self.card("有模型的員工", model={"tool": "agy", "model_id": "gemini-4-argon-medium"})
        self.configure("text")
        chat_id = self.open_http(mine)
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        model = next(x for x in self.stdin() if x.get("method") == "session/set_model")
        self.assertEqual(model["params"]["modelId"], acp.VERSIONS[VERSION].model_id)

    def test_the_cards_own_instructions_go_in_and_the_positions_default_does_not(self):
        mine = self.card("有指示的員工", instructions="先說結論，再說理由。")
        self.configure("text")
        chat_id = self.open_http(mine)
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        new = next(x for x in self.stdin() if x.get("method") == "session/new")
        sent = new["params"]["_meta"]["antigravity"]["systemPrompt"]["append"]
        self.assertTrue(sent.startswith("先說結論，再說理由。"), sent)

    def test_deleting_an_agy_chat_keeps_the_copy_agy_made_in_its_own_folder(self):
        self.configure("text")
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        copy = self.base / "agy-chat-home" / "antigravity-cli" / "conversations" / "fake.pb"
        copy.parent.mkdir(parents=True)
        copy.write_text("{}")
        status_, out = self.call(f"/api/chats/{chat_id}", "DELETE")
        self.assertEqual((status_, out["deleted"]), (200, chat_id), out)
        self.assertFalse((self.base / "chats" / chat_id).exists())
        self.assertTrue(copy.exists(), "AGY's own copy is not VBear's to delete")


class CardGateTests(ApiCase):
    def test_a_card_of_a_tool_that_cannot_chat_is_refused_and_says_which_and_what_can(self):
        for tool, label in (("grok", "Grok"), ("shared", "共用")):
            with self.subTest(tool=tool):
                other = self.card(f"{tool}員工", tool)
                status_, out = self.call("/api/chats", "POST", {"profile_id": other})
                self.assertEqual((status_, out["code"]), (409, "card_tool_unsupported"))
                self.assertIn(label, out["error"])
                for name in ("Claude Code", "Codex", "AGY"):
                    self.assertIn(name, out["error"])
        self.assertEqual(cs.list_ids(self.base), [])

    def test_the_list_marks_an_agy_card_as_one_that_may_chat_with_its_engine(self):
        status_, lst = self.call("/api/chats")
        by = {c["id"]: c for c in lst["cards"]}
        self.assertEqual((by[self.emp]["can_chat"], by[self.emp]["engine"]), (True, "agy-chat"))

    def test_a_card_whose_tool_changed_after_the_chat_began_cannot_send_and_nothing_starts(self):
        chat_id = self.open_http()
        for tool in ("claude", "codex"):
            ap.save_profile(self.emp, {"model": {"tool": tool}})
            status_, out = self.say(chat_id)
            self.assertEqual((status_, out["code"]), (409, "card_tool_changed"), tool)
            self.assertIn("新的聊天", out["error"])
        ap.save_profile(self.emp, {"model": {"tool": "grok"}})
        self.assertEqual(self.say(chat_id)[1]["code"], "card_tool_unsupported")
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_a_claude_chat_whose_card_became_agy_cannot_send(self):
        claude = self.card("Claude 員工", "claude")
        chat_id = self.open_http(claude)
        self.assertEqual(cs.load(self.base, chat_id)["engine"], "claude-chat")
        ap.save_profile(claude, {"model": {"tool": "agy"}})
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "card_tool_changed"))
        self.assertEqual(self.fake_log(), [])


class NotReadyTests(ApiCase):
    """The service says why before it asks the daemon, in the page's words, and starts nothing."""

    def test_each_state_that_is_not_ready_is_refused_with_its_reason(self):
        want = {"not_installed": ("invalid_binary", "安裝 AGY"), "unsupported": ("agy_version", "9.9.9"),
                "unverified": ("unverified", "驗證"), "policy": ("admin_policy", "/etc/antigravity"),
                "hooks": ("agy_hooks", "自動執行"), "folder": ("agy_home", "GEMINI.md"), "version_unreadable": ("agy_version", "版本")}
        chat_id = self.open_http()
        self.svc.agy_binary = lambda: None
        for state, (code, word) in want.items():
            with self.subTest(state=state):
                self.svc.agy = lambda state=state: status(state)
                status_, out = self.say(chat_id)
                self.assertEqual((status_, out["code"]), (409, code), out)
                self.assertIn(word, out["error"])
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_a_ready_state_with_no_binary_is_refused_too(self):
        chat_id = self.open_http()
        self.svc.agy_binary = lambda: None
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "invalid_binary"))
        self.assertEqual(self.fake_log(), [])

    def test_the_daemon_still_refuses_what_the_service_let_through(self):
        # the service's state is only a courtesy; the daemon checks the verified list itself
        chat_id = self.open_http()
        with mock.patch.object(cli_versions, "AGY_CHAT_VERIFIED_VERSIONS", ()):
            status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "unverified"))
        self.assertEqual(self.fake_log(), [])

    def test_the_daemons_own_refusals_reach_the_page_in_words(self):
        chat_id = self.open_http()
        hooks = self.home / ".agents" / "hooks.json"
        hooks.parent.mkdir()
        hooks.write_text("{}")
        status_, out = self.say(chat_id)
        self.assertEqual((status_, out["code"]), (409, "agy_hooks"))
        self.assertIn("hooks.json", out["error"])
        self.assertNotIn("CLI", out["error"])


class SupportTests(ApiCase):
    def test_the_answer_names_the_third_engine_and_keeps_the_other_keys(self):
        status_, out = self.call("/api/chat-support")
        self.assertEqual(status_, 200, out)
        s = out["support"]
        self.assertEqual((s["engine"], s["agy"]["engine"], s["agy"]["state"]), ("claude-chat", "agy-chat", "ready"))
        for key in ("detected", "verified", "state", "message", "policy", "verify", "money", "codex"):
            self.assertIn(key, s)
        for word in ("Google", "估算", "不是帳單"):
            self.assertIn(word, s["agy"]["money"])
        self.assertEqual(s["agy"]["money"], chat_engines.AGY_MONEY)
        status_, lst = self.call("/api/chats")
        self.assertEqual(lst["support"]["agy"]["engine"], "agy-chat")

    def test_every_state_of_agy_reaches_the_page_as_the_service_found_it(self):
        for state in ("not_installed", "unsupported", "unverified", "policy", "hooks", "folder", "version_unreadable", "ready"):
            with self.subTest(state=state):
                self.svc.agy = lambda state=state: status(state)
                got = self.call("/api/chat-support")[1]["support"]["agy"]
                self.assertEqual((got["state"], got["why"]), (state, status(state)["why"]))

    def test_the_agy_part_carries_the_state_of_its_own_verification(self):
        self.svc.agy_verifier = FakeVerifier()
        got = self.call("/api/chat-support")[1]["support"]
        self.assertEqual(got["agy"]["verify"], {"running": False})
        self.svc.agy_verifier.start("b", VERSION)
        got = self.call("/api/chat-support")[1]["support"]
        self.assertEqual(got["agy"]["verify"], {"running": True})
        self.assertEqual(got["verify"], {"running": False}, "Claude's verifier is not AGY's")


class VerifyTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.svc.agy_verifier = FakeVerifier()
        self.svc.agy = lambda: status("unverified", version=VERSION)
        p = mock.patch.object(chat_service.admin_policy, "check_agy", return_value=mock.Mock(ok=True))
        p.start()
        self.addCleanup(p.stop)

    def post(self, body):
        return self.call("/api/chat-support/verify", "POST", body)

    def test_agy_is_verified_by_its_own_check(self):
        status_, out = self.post({"engine": "agy"})
        self.assertEqual((status_, out["ok"]), (202, True), out)
        self.assertEqual(out["status"], {"running": True, "version": VERSION})
        self.assertEqual(self.svc.agy_verifier.started, [("", VERSION)])

    def test_a_version_the_page_did_not_see_is_refused(self):
        status_, out = self.post({"engine": "agy", "version": "0.1.0"})
        self.assertEqual((status_, out["code"]), (409, "version_changed"))
        self.assertEqual(self.svc.agy_verifier.started, [])
        self.assertEqual(self.post({"engine": "agy", "version": VERSION})[0], 202)

    def test_a_verified_version_is_not_checked_again(self):
        self.svc.agy = lambda: status("ready")
        status_, out = self.post({"engine": "agy"})
        self.assertEqual((status_, out["already_verified"]), (202, True))
        self.assertEqual(self.svc.agy_verifier.started, [])

    def test_a_verified_version_without_the_shared_folder_part_is_checked_again_when_asked(self):
        self.svc.agy = lambda: status("ready")
        status_, out = self.post({"engine": "agy", "shared": True})
        self.assertEqual((status_, out["ok"]), (202, True), out)
        self.assertNotIn("already_verified", out)
        self.assertEqual(len(self.svc.agy_verifier.started), 1)

    def test_a_check_that_could_not_pass_is_not_started(self):
        for state, code in (("not_installed", "invalid_binary"), ("unsupported", "agy_version"), ("policy", "admin_policy"),
                            ("hooks", "agy_hooks"), ("folder", "agy_home"), ("version_unreadable", "agy_version")):
            with self.subTest(state=state):
                self.svc.agy = lambda state=state: status(state, verified=False)
                status_, out = self.post({"engine": "agy"})
                self.assertEqual((status_, out["code"]), (409, code), out)
        self.assertEqual(self.svc.agy_verifier.started, [])

    def test_an_administrator_policy_found_now_stops_it_before_any_model_call(self):
        denied = mock.Mock(ok=False, reason=lambda: "這台 Mac 上有管理員政策：/etc/antigravity")
        with mock.patch.object(chat_service.admin_policy, "check_agy", return_value=denied):
            status_, out = self.post({"engine": "agy"})
        self.assertEqual((status_, out["code"]), (409, "admin_policy"))
        self.assertEqual(self.svc.agy_verifier.started, [])

    def test_an_engine_that_does_not_exist_and_other_keys_are_bad_requests(self):
        for bad in ({"engine": "grok"}, {"engine": "agy-chat"}, {"engine": 5}, {"engine": "agy", "x": 1}):
            with self.subTest(bad=bad):
                self.assertEqual(self.post(bad)[0], 400, bad)
        self.assertEqual(self.svc.agy_verifier.started, [])

    def test_a_console_without_the_agy_verifier_says_so(self):
        self.svc.agy_verifier = None
        status_, out = self.post({"engine": "agy"})
        self.assertEqual((status_, out["code"]), (503, "unavailable"))


class WordsTests(unittest.TestCase):
    NEW = ("agy_home", "agy_hooks", "agy_workdir", "agy_version")

    def test_the_new_codes_have_sentences_and_none_is_bare(self):
        for code in self.NEW:
            status_, text = chat_service.CODE_TEXT[code]
            self.assertTrue(409 == status_ and text.endswith("。"), code)
            self.assertNotIn(code, chat_service.explain(code))
            for engineering in ("CLI", "stdio", "JSON", "manifest", "sandbox"):
                self.assertNotIn(engineering, text, code)

    def test_the_sentences_that_the_engines_share_name_all_three_tools(self):
        for code in ("card_tool_unsupported", "invalid_binary", "shared_unverified"):
            text = chat_service.CODE_TEXT[code][1]
            for name in ("Claude Code", "Codex", "AGY"):
                self.assertIn(name, text, code)

    def test_every_code_the_agy_side_can_give_has_a_sentence(self):
        root = Path(server.__file__).resolve().parent / "runtime"
        found = set()
        for name, patterns in (("agy_chat_session.py", [r'return "([a-z_]+)", ']), ("daemon_chat.py", [r'_err\(rid, "([a-z_]+)"']),
                               ("agy_chat_env.py", [r'AgyRefused\("([a-z_]+)"'])):
            found |= {c for pat in patterns for c in re.findall(pat, (root / name).read_text())}
        found |= {"agy_home", "agy_workdir", "shared_unsafe"}                    # the daemon maps AgyRefused's words to these
        found -= {"alive", "unknown", "unsafe_path", "foreign_settings", "too_big", "not_installed", "unsafe_binary",
                  "version_unreadable", "unsupported"}                             # agy_chat_env's own words, mapped before they leave
        self.assertEqual(sorted(found - set(chat_service.CODE_TEXT)), [])

    def test_what_a_person_reads_of_the_session_is_everyday_words(self):
        from vbear.runtime import agy_chat_session as acs
        for text in (acs.NOT_LOGGED_IN, acs.RESUME_FAILED, acs.NO_MODEL.format(model="m"), *acs.FAILED_STEP.values()):
            self.assertNotIn("CLI", text)
            self.assertNotIn("ACP", text)
            self.assertNotIn("JSON", text)
            self.assertNotIn("session", text.lower())


class OneEngineEachTests(unittest.TestCase):
    def test_the_third_row_is_the_only_thing_the_service_needed_to_know(self):
        row = chat_engines.by_tool("agy")
        for name in (row.fields, row.verify):
            self.assertTrue(callable(getattr(chat_service.ChatService, name)))
        self.assertEqual(chat_service.engine_of({"model": {"tool": "agy"}}), "agy-chat")
        self.assertEqual(chat_service.card_gate({"model": {"tool": "agy"}}), (True, "", ""))


if __name__ == "__main__":
    unittest.main()
