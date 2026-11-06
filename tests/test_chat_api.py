"""The chat endpoints (P36-2) over a real loopback server. The config rules first (no daemon needed); the chats
themselves run through a real runtime daemon with the fake Claude Code of tests/fake_chat_cli.py, further down."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests import chat_fixtures as cf
from tests.test_chat_daemon import MODEL, SECRETS_OF_INIT, ChatCase, clean
from vbear import agent_profiles as ap, chat_service, config as cfg, server
from vbear.index import Store
from vbear.runtime import chat_store as cs


class Http:
    """Calls against a Console's handler."""
    token = "synthetic-test-token"

    def call(self, path, method="GET", body=None, raw=None, headers=None):
        hdr = {"Authorization": f"Bearer {self.token}", "X-VBear": "1",
               "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        hdr.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")


class ConfigTests(Http, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-chat-config-test-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"),
                                             "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = self.token
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.runtime = mock.Mock(binary=lambda: "unused")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def test_chat_limits_are_validated_on_write(self):
        status, out = self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 1.25}})
        self.assertEqual(status, 200, out)
        self.assertEqual(cfg.load()["chat_limits"], {"per_turn_usd": 1.25})
        self.assertEqual(cs.limits_from(cfg.load()), {"per_turn_usd": Decimal("1.25")})
        self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})
        for bad in ({"per_turn_usd": 0}, {"per_turn_usd": -1}, {"per_turn_usd": 5.01}, {"per_turn_usd": "1"},
                    {"per_turn_usd": True}, {"per_turn_usd": 0.001}, {"daily_usd": 1}, {}, [], "x", 3):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("/api/config", "POST", {"chat_limits": bad})[0], 400)
        self.assertEqual(self.call("/api/config", "POST", raw=b'{"chat_limits": {"per_turn_usd": NaN}}')[0], 400)
        self.assertEqual(cfg.load()["chat_limits"], {"per_turn_usd": 1.25}, "a refused write changes nothing")
        # the cap is the most one turn may ever cost, and it stays under the day
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 5}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 3}})[0], 200)
        status, out = self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 4}})
        self.assertEqual(status, 400, out)
        self.assertIn("每天", out["error"])
        # the day raised in the same request is the day the turn's limit is checked against
        status, out = self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 4}, "meeting_limits": {"daily_usd": 10}})
        self.assertEqual(status, 200, out)
        self.assertEqual(cfg.load()["chat_limits"], {"per_turn_usd": 4.0})

    def test_the_config_answer_carries_the_limit_the_daemon_reads(self):
        self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 0.75}})
        status, view = self.call("/api/config")
        self.assertEqual((status, view["config"]["chat_limits"]), (200, {"per_turn_usd": 0.75}))


class ApiCase(ChatCase, Http):
    """A console in front of the case's runtime daemon (tests/test_chat_daemon.py ChatCase), whose Claude Code is the
    fake one. The role cards are real files in the synthetic HOME."""

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
        self.svc.claude = lambda: (str(self.binary), cf.VERSION, "")
        self.svc.restart_pause = 0.05
        self.svc.delete_pause = 0.05
        self.emp = self.card("虛構員工")

    def card(self, name, tool="claude", **over):
        body = {"name": name, "position": "pm", "model": {"tool": tool}}
        body.update(over)
        return ap.save_profile(None, body)["id"]

    def open_http(self, profile=None):
        status, out = self.call("/api/chats", "POST", {"profile_id": profile or self.emp})
        self.assertEqual(status, 201, out)
        return out["chat"]["id"]

    def say(self, chat_id, text="你好"):
        return self.call(f"/api/chats/{chat_id}/messages", "POST", {"text": text})

    def view(self, chat_id, after=0):
        status, out = self.call(f"/api/chats/{chat_id}?after={after}")
        self.assertEqual(status, 200, out)
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


class WholeWayTests(ApiCase):
    def test_open_say_allow_and_read_the_record(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        status, out = self.say(chat_id, "run ls")
        self.assertEqual((status, out["ok"], out["turn"], out["cap_usd"], out["process"]), (202, True, 1, "0.5", "new"), out)
        card = self.wait_http_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("Bash", "command"))
        status, lst = self.call("/api/chats")
        mine = next(c for c in lst["chats"] if c["id"] == chat_id)
        self.assertEqual((status, mine["waiting"], mine["open"], mine["turns"], mine["last_text"]), (200, True, True, 1, "run ls"))
        status, out = self.call(f"/api/chats/{chat_id}/answer", "POST",
                                {"card_id": card["card_id"], "token": card["token"], "decision": "allow"})
        self.assertEqual((status, out), (200, {"ok": True, "answered": card["card_id"]}))
        end = self.wait_http_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["reported"]), ("result", True))
        v = self.view(chat_id)
        kinds = [r["kind"] for r in v["records"]]
        for k in ("chat_created", "user_message", "process_started", "card", "card_decision", "reply", "turn_ended"):
            self.assertIn(k, kinds)
        self.assertEqual((v["chat"]["profile_id"], v["card"]["name"], v["card"]["can_chat"], v["runtime"]["available"]),
                         (self.emp, "虛構員工", True, True))
        status, lst = self.call("/api/chats")
        mine = next(c for c in lst["chats"] if c["id"] == chat_id)
        self.assertEqual((mine["waiting"], mine["open"], mine["last_kind"]), (False, False, "reply"))
        self.assertEqual(mine["spent_usd"], end["cost_usd"])
        # nothing of the initialize answer is in what the page gets
        text = json.dumps([v, lst], ensure_ascii=False)
        for secret in SECRETS_OF_INIT:
            self.assertNotIn(secret, text)

    def test_a_record_is_read_in_pages_from_where_the_page_left_off(self):
        self.configure([clean("ask", 4)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        everything = self.view(chat_id)["records"]
        first = self.view(chat_id, after=2)["records"]
        self.assertEqual([r["seq"] for r in first], [r["seq"] for r in everything if r["seq"] > 2])
        self.assertEqual(self.call(f"/api/chats/{chat_id}?after=x")[0], 400)
        self.assertEqual(self.call(f"/api/chats/{chat_id}?after=-1")[0], 400)

    def test_stop_and_delete(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_card(chat_id)
        status, out = self.call(f"/api/chats/{chat_id}/stop", "POST", {})
        self.assertEqual((status, out["stopped"]), (200, True))
        end = self.wait_http_turn(chat_id, 1)
        self.assertEqual(end["reason"], "stopped")
        self.wait_gone(chat_id)
        self.assertEqual(self.call(f"/api/chats/{chat_id}/stop", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call(f"/api/chats/{chat_id}", "DELETE")[0], 200)
        self.assertEqual(self.call(f"/api/chats/{chat_id}")[0], 404)
        self.assertFalse((self.base / "chats" / chat_id).exists())

    def test_delete_closes_an_idle_process_first(self):
        self.configure([clean("ask", 4)])
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        self.assertIn(chat_id, self.dm._chats)
        status, out = self.call(f"/api/chats/{chat_id}", "DELETE")
        self.assertEqual((status, out["deleted"]), (200, chat_id), out)
        self.assertNotIn(chat_id, self.dm._chats)

    def test_delete_while_a_turn_runs_says_to_stop_first(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_card(chat_id)
        status, out = self.call(f"/api/chats/{chat_id}", "DELETE")
        self.assertEqual((status, out["code"]), (409, "busy"))
        self.assertIn("停止", out["error"])
        self.assertTrue((self.base / "chats" / chat_id).exists())

    def test_modify_then_allow_through_the_page(self):
        self.configure([clean("ask", 1)])
        chat_id = self.open_http()
        self.say(chat_id, "echo something")
        card = self.wait_http_card(chat_id)
        status, out = self.call(f"/api/chats/{chat_id}/answer", "POST",
                                {"card_id": card["card_id"], "token": card["token"], "decision": "modify",
                                 "value": "echo changed-by-user"})
        self.assertEqual(status, 200, out)
        self.wait_http_turn(chat_id, 1)
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"]["updatedInput"]["command"], "echo changed-by-user")


class CardGateTests(ApiCase):
    def test_a_disabled_card_cannot_open_a_chat_and_says_why(self):
        off = self.card("停用員工", enabled=False)
        status, out = self.call("/api/chats", "POST", {"profile_id": off})
        self.assertEqual((status, out["code"]), (409, "card_disabled"))
        self.assertIn("停用", out["error"])
        self.assertEqual(os.listdir(self.base / "chats") if (self.base / "chats").exists() else [], [])

    def test_a_card_of_another_tool_cannot_open_a_chat_and_says_which_tool(self):
        for tool, label in (("grok", "Grok"), ("agy", "AGY"), ("shared", "共用")):
            with self.subTest(tool=tool):
                other = self.card(f"{tool}員工", tool)
                status, out = self.call("/api/chats", "POST", {"profile_id": other})
                self.assertEqual((status, out["code"]), (409, "card_tool_unsupported"))
                self.assertIn(label, out["error"])
                self.assertIn("Claude Code", out["error"])

    def test_an_unknown_card_and_bad_bodies(self):
        self.assertEqual(self.call("/api/chats", "POST", {"profile_id": "nope-1"})[1]["code"], "no_card")
        for bad in ({}, {"profile_id": 5}, {"profile_id": self.emp, "x": 1}, []):
            self.assertEqual(self.call("/api/chats", "POST", bad)[0], 400, bad)
        self.assertEqual(self.call("/api/chats", "POST", raw=b"[1,2]")[0], 400)
        self.assertEqual(self.call("/api/chats", "POST", raw=b"{nope")[0], 400)

    def test_a_card_switched_off_after_the_chat_began_cannot_send_and_nothing_starts(self):
        chat_id = self.open_http()
        ap.save_profile(self.emp, {"enabled": False})
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "card_disabled"))
        ap.save_profile(self.emp, {"enabled": True, "model": {"tool": "codex"}})
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "card_tool_changed"))
        ap.save_profile(self.emp, {"enabled": True, "model": {"tool": "grok"}})
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "card_tool_unsupported"))
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_the_list_marks_each_card_with_whether_it_may_chat(self):
        off = self.card("停用員工", enabled=False)
        other = self.card("Grok 員工", "grok")
        status, lst = self.call("/api/chats")
        by = {c["id"]: c for c in lst["cards"]}
        self.assertEqual((by[self.emp]["can_chat"], by[self.emp]["reason"]), (True, None))
        self.assertEqual((by[off]["can_chat"], by[off]["code"]), (False, "card_disabled"))
        self.assertEqual((by[other]["can_chat"], by[other]["code"]), (False, "card_tool_unsupported"))
        self.assertIn("Grok", by[other]["reason"])


class InstructionsApiTests(ApiCase):
    def argv(self):
        return next(x for x in self.fake_log() if x["event"] == "start")["argv"]

    def test_only_the_cards_own_instructions_go_in(self):
        mine = self.card("有指示的員工", instructions="先說結論，再說理由。")
        self.configure([clean("text", 0)])
        chat_id = self.open_http(mine)
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        argv = self.argv()
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1], "先說結論，再說理由。")

    def test_a_position_default_is_not_sent_as_the_cards_own(self):
        # a PM card without instructions of its own: instructions_of() offers the position's text as the default
        self.assertEqual(ap.instructions_of(ap.get_profile(self.emp))["source"], "default")
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        self.assertNotIn("--append-system-prompt", self.argv())
        self.assertNotIn(ap.instructions_of(ap.get_profile(self.emp))["default"], json.dumps(self.fake_log()))


class MeaningOfCodesTests(ApiCase):
    """Each refusal of the daemon reaches the page as a sentence of its own, with the status of its code."""

    def test_every_code_the_daemon_side_can_give_has_a_sentence(self):
        import re
        root = Path(server.__file__).resolve().parent / "runtime"
        found = set()
        for name, patterns in (("daemon_chat.py", [r'_err\(rid, "([a-z_]+)"']), ("chat_session.py", [r'return "([a-z_]+)", ']),
                               ("codex_chat_session.py", [r'return "([a-z_]+)", ']),
                               ("chat_store.py", [r'ChatStoreError\("([a-z_]+)"']),
                               ("agent_sessions.py", [r'LaunchRefused\("([a-z_]+)"'])):
            text = (root / name).read_text()
            for pat in patterns:
                found |= set(re.findall(pat, text))
        found |= {"spend_unknown", "unavailable", "bad_reply"}
        found -= {"alive", "unknown"}                     # chat_session's liveness words, not refusals
        missing = sorted(found - set(chat_service.CODE_TEXT))
        self.assertEqual(missing, [])
        for code in found:
            status, text = chat_service.CODE_TEXT[code]
            self.assertTrue(400 <= status <= 599 and text.endswith("。"), code)
            self.assertNotIn(code, chat_service.explain(code), "no bare code in the sentence")

    def test_the_five_the_page_must_explain_are_plain_sentences(self):
        want = {"refused": "又檢查了一次", "expired": "5 分鐘", "restarting": "再按一次", "spend_unknown": "今天已經花了多少",
                "damaged": "紀錄有問題"}
        for code, word in want.items():
            self.assertIn(word, chat_service.explain(code, "原因"), code)
        self.assertIn("原因：細節", chat_service.explain("refused", "細節"))

    def test_expired_refused_and_gone_cards_reach_the_page_with_their_sentences(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.say(chat_id)
        card = self.wait_http_card(chat_id)
        answer = lambda token=card["token"], cid=card["card_id"]: self.call(
            f"/api/chats/{chat_id}/answer", "POST", {"card_id": cid, "token": token, "decision": "deny"})
        status, out = answer(token="wrong")
        self.assertEqual((status, out["code"]), (403, "bad_token"))
        self.assertNotIn(card["token"], json.dumps(out))
        self.assertEqual(answer()[0], 200)
        status, out = answer()
        self.assertEqual((status, out["code"]), (409, "gone"))
        self.assertIn("回覆過", out["error"])

    def test_an_expired_card_says_so(self):
        self.dm.chat_card_ttl = 0.4
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.say(chat_id)
        card = self.wait_http_card(chat_id)
        time.sleep(0.5)
        status, out = self.call(f"/api/chats/{chat_id}/answer", "POST",
                                {"card_id": card["card_id"], "token": card["token"], "decision": "allow"})
        self.assertIn(out["code"], ("expired", "gone"))
        if out["code"] == "expired":
            self.assertEqual(status, 409)
            self.assertIn("5 分鐘", out["error"])

    def test_a_card_that_became_unsafe_is_refused_and_says_what_happened(self):
        work = Path(cs.ensure_work_dir(self.base, self.emp))
        outside = self.tmp / "outside"
        outside.mkdir()
        (work / "sub").mkdir()
        ask = {"type": "control_request", "request_id": "r-write-1", "request": {
            "subtype": "can_use_tool", "tool_name": "Write", "tool_use_id": "toolu_w1",
            "input": {"file_path": str(work / "sub" / "a.txt"), "content": "x"}}}
        self.configure([[{"ask": ask}] + clean("ask", 4)])
        chat_id = self.open_http()
        self.say(chat_id)
        card = self.wait_http_card(chat_id)
        (work / "sub").rmdir()
        (work / "sub").symlink_to(outside)
        status, out = self.call(f"/api/chats/{chat_id}/answer", "POST",
                                {"card_id": card["card_id"], "token": card["token"], "decision": "allow"})
        self.assertEqual((status, out["code"]), (409, "refused"))
        self.assertIn("又檢查了一次", out["error"])
        self.assertIn("原因：", out["error"])
        self.assertEqual(os.listdir(outside), [])

    def test_a_day_that_cannot_be_counted_is_said_and_nothing_starts(self):
        chat_id = self.open_http()
        other = self.open_http(self.card("另一位"))
        (self.base / "chats" / other / "events.jsonl").write_text("not json\n")
        os.chmod(self.base / "chats" / other / "events.jsonl", 0o600)
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "spend_unknown"))
        self.assertIn("今天已經花了多少", out["error"])
        self.assertEqual(self.fake_log(), [])

    def test_a_chat_with_a_damaged_record_is_said_in_the_list_and_cannot_be_sent_to_or_deleted(self):
        chat_id = self.open_http()
        path = self.base / "chats" / chat_id / "events.jsonl"
        path.write_bytes(path.read_bytes() + b"{broken")
        status, lst = self.call("/api/chats")
        mine = next(c for c in lst["chats"] if c["id"] == chat_id)
        self.assertTrue(mine["problem"])
        # a record that does not read whole also makes today's money unknown, which is what a send meets first
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "spend_unknown"))
        status, out = self.call(f"/api/chats/{chat_id}", "DELETE")
        self.assertEqual((status, out["code"]), (409, "damaged"), out)
        self.assertIn("紀錄有問題", out["error"])
        self.assertTrue((self.base / "chats" / chat_id).exists(), "its cost must not vanish with it")

    def test_restarting_is_tried_again_by_itself_and_then_said(self):
        self.configure([clean("ask", 4), clean("ask", 4)])
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        calls = []
        real = self.svc._call

        def flaky(op, **kw):
            if op == "chat_send":
                calls.append(op)
                if len(calls) < 3:
                    raise chat_service.api_error("restarting")
            return real(op, **kw)
        with mock.patch.object(self.svc, "_call", flaky):
            status, out = self.say(chat_id, "again")
        self.assertEqual((status, len(calls)), (202, 3), out)
        always = lambda op, **kw: (_ for _ in ()).throw(chat_service.api_error("restarting"))
        with mock.patch.object(self.svc, "_call", always):
            status, out = self.say(chat_id, "again")
        self.assertEqual((status, out["code"]), (409, "restarting"))
        self.assertIn("訊息還沒有送出", out["error"])

    def test_a_red_lamp_says_so(self):
        self.call("/api/config", "POST", {"meeting_limits": {"per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.01}})
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)            # US$0.01 is left: this turn may start, at that cap
        self.wait_http_card(chat_id)
        self.call(f"/api/chats/{chat_id}/stop", "POST", {})
        self.assertEqual(self.wait_http_turn(chat_id, 1)["cost_usd"], "0.01")      # stopped: it costs its cap
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "red"))
        self.assertIn("亮紅燈", out["error"])
        self.assertEqual(self.call("/api/chats")[1]["ledger"]["lamp"], "red")


class ListAndSupportTests(ApiCase):
    def test_the_list_carries_cards_support_limits_and_the_ledger(self):
        self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 0.25}})
        self.console.store.set_conf(cfg.load())
        status, lst = self.call("/api/chats")
        self.assertEqual(status, 200)
        self.assertEqual(lst["limits"], {"per_turn_usd": "0.25", "daily_usd": "3"})
        self.assertEqual((lst["ledger"]["lamp"], lst["ledger"]["includes"]), ("green", ["meetings", "staffing", "chats", "setup_try", "chief"]))
        self.assertIsNone(lst["ledger_error"])
        self.assertEqual(lst["chats"], [])
        self.assertEqual(lst["support"]["detected"], cf.VERSION)

    def test_support_says_unverified_and_how_to_verify(self):
        with mock.patch.object(chat_service.cli_versions, "CHAT_VERIFIED_VERSIONS", ()):
            status, out = self.call("/api/chat-support")
            sup = out["support"]
        self.assertEqual((status, sup["state"], sup["detected"]), (200, "unverified", cf.VERSION))
        self.assertIn("還沒有通過驗證", sup["message"])
        self.assertEqual(sup["verified"], [])

    def test_support_per_state(self):
        verified = lambda: self.call("/api/chat-support")[1]["support"]
        self.assertEqual(verified()["state"], "verified")
        self.svc.claude = lambda: (None, None, "找不到 claude")
        self.assertEqual((verified()["state"], verified()["detected"]), ("unknown", None))
        self.assertIn("找不到 claude", verified()["message"])
        self.svc.claude = lambda: ("/x/claude", "9.9.9", "")
        self.assertEqual(verified()["state"], "unsupported")
        self.svc.claude = lambda: (str(self.binary), cf.VERSION, "")
        fake = mock.Mock(ok=False, found=["/Library/Application Support/ClaudeCode"], problems=[],
                         reason=lambda: "存在管理員政策")
        with mock.patch.object(chat_service.admin_policy, "check_claude", return_value=fake):
            sup = verified()
        self.assertEqual((sup["state"], sup["policy"]["found"]), ("policy", ["/Library/Application Support/ClaudeCode"]))

    def test_verify_start_needs_the_header_and_is_refused_when_it_could_not_pass(self):
        started = []
        self.svc.verifier = mock.Mock(start=lambda b, v: started.append((b, v)) or {"running": True, "version": v},
                                      status=lambda: {"running": False})
        with mock.patch.object(chat_service.cli_versions, "CHAT_VERIFIED_VERSIONS", ()):
            status, out = self.call("/api/chat-support/verify", "POST", {}, headers={"X-VBear": "0"})
            self.assertEqual(status, 403)
            self.assertEqual(started, [])
            self.assertEqual(self.call("/api/chat-support/verify", "POST", {"version": "9.9.9"})[1]["code"], "version_changed")
            self.assertEqual(self.call("/api/chat-support/verify", "POST", {"x": 1})[0], 400)
            fake = mock.Mock(ok=False, found=["x"], problems=[], reason=lambda: "存在管理員政策")
            with mock.patch.object(chat_service.admin_policy, "check_claude", return_value=fake):
                status, out = self.call("/api/chat-support/verify", "POST", {})
            self.assertEqual((status, out["code"]), (409, "admin_policy"))
            self.assertEqual(started, [], "no money is spent on a check that cannot pass")
            status, out = self.call("/api/chat-support/verify", "POST", {"version": cf.VERSION})
            self.assertEqual((status, out["status"]["running"]), (202, True))
            self.assertEqual(started, [(str(self.binary), cf.VERSION)])
        status, out = self.call("/api/chat-support/verify", "POST", {})
        self.assertEqual((status, out["already_verified"]), (202, True))
        self.assertEqual(len(started), 1)


class WireTests(ApiCase):
    def test_writes_need_the_header_the_origin_and_the_token(self):
        chat_id = self.open_http()
        for path, body in (("/api/chats", {"profile_id": self.emp}), (f"/api/chats/{chat_id}/messages", {"text": "x"}),
                           (f"/api/chats/{chat_id}/stop", {})):
            self.assertEqual(self.call(path, "POST", body, headers={"X-VBear": "0"})[0], 403, path)
            self.assertEqual(self.call(path, "POST", body, headers={"Origin": "http://evil.example"})[0], 403, path)
            self.assertEqual(self.call(path, "POST", body, headers={"Authorization": "Bearer nope"})[0], 401, path)
        self.assertEqual(self.call(f"/api/chats/{chat_id}", "DELETE", headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call("/api/chats", headers={"Authorization": "Bearer nope"})[0], 401)
        self.assertEqual(self.fake_log(), [])

    def test_ids_and_paths_are_strict(self):
        for path in ("/api/chats/x", "/api/chats/c-1", "/api/chats/c-0123456789abcdef/other", "/api/chats/../x",
                     "/api/chats/c-0123456789abcdefg"):
            self.assertEqual(self.call(path)[0], 404, path)
        self.assertEqual(self.call("/api/chats/c-0123456789abcdef")[0], 404)       # well formed, not there
        self.assertEqual(self.call("/api/chats/c-0123456789abcdef/messages", "POST", {"text": "x"})[0], 404)
        self.assertEqual(self.call("/api/chats/c-0123456789abcdef/messages")[0], 404)   # a GET of a write path

    def test_a_message_must_be_text(self):
        chat_id = self.open_http()
        for bad in ({}, {"text": 5}, {"text": ""}, {"text": "  "}, {"text": "x", "y": 1}, {"text": "x" * 40000}):
            status, out = self.say(chat_id) if False else self.call(f"/api/chats/{chat_id}/messages", "POST", bad)
            self.assertIn(status, (400, 413), (bad.keys(), out))
        self.assertEqual(self.fake_log(), [])

    def test_answer_bodies_are_strict(self):
        chat_id = self.open_http()
        for bad in ({}, {"card_id": "k", "token": "t"}, {"card_id": 1, "token": "t", "decision": "allow"},
                    {"card_id": "k", "token": "t", "decision": "allow", "value": 5},
                    {"card_id": "k", "token": "t", "decision": "allow", "extra": 1}):
            self.assertEqual(self.call(f"/api/chats/{chat_id}/answer", "POST", bad)[0], 400, bad)

    def test_no_secret_shaped_text_reaches_the_page_from_a_chat(self):
        self.configure([[{"emit": [{"type": "system", "subtype": "init"}]}] + clean("ask", 4)])
        chat_id = self.open_http()
        self.say(chat_id, "my key is sk-ant-api03-FICTIONALFICTIONALFICTIONAL")
        self.wait_http_turn(chat_id, 1)
        self.assertNotIn("FICTIONALFICTIONAL", json.dumps(self.view(chat_id)))


class StreamTests(ApiCase):
    def open_stream(self, chat_id, after=0, headers=None):
        hdr = {"Authorization": f"Bearer {self.token}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}"}
        hdr.update(headers or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}/api/chats/{chat_id}/stream?after={after}",
                                     headers=hdr)
        return urllib.request.urlopen(req, timeout=15)

    @staticmethod
    def events(resp, until, limit=40):
        got = []
        for _ in range(limit):
            line = resp.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                got.append(json.loads(line[6:]))
                if until(got):
                    break
        return got

    def test_the_stream_sends_the_card_and_then_the_end_of_the_turn(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.say(chat_id, "run ls")
        with self.open_stream(chat_id) as resp:
            self.assertEqual(resp.headers["Content-Type"], "text/event-stream; charset=utf-8")
            got = self.events(resp, lambda g: any(e["live"] and e["live"]["cards"] for e in g))
            card = next(e["live"]["cards"][0] for e in got if e["live"] and e["live"]["cards"])
            self.assertEqual(self.call(f"/api/chats/{chat_id}/answer", "POST",
                                       {"card_id": card["card_id"], "token": card["token"], "decision": "allow"})[0], 200)
            more = self.events(resp, lambda g: any(r["kind"] == "turn_ended" for e in g for r in e["records"]))
        records = [r for e in got + more for r in e["records"]]
        self.assertEqual([r["seq"] for r in records], sorted({r["seq"] for r in records}), "every record once, in order")
        self.assertIn("turn_ended", [r["kind"] for r in records])
        self.assertTrue(all(e["ok"] for e in got + more))

    def test_the_stream_needs_the_header_and_a_chat_and_a_place(self):
        chat_id = self.open_http()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.open_stream(chat_id, headers={"X-VBear": "0"})
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.open_stream("c-0123456789abcdef")
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()
        opened = [self.open_stream(chat_id) for _ in range(server.CHAT_STREAMS_MAX)]
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.open_stream(chat_id)
            self.assertEqual(ctx.exception.code, 429)
            ctx.exception.close()
        finally:
            for r in opened:
                r.close()

    def test_a_stream_ends_when_its_chat_is_deleted(self):
        chat_id = self.open_http()
        with self.open_stream(chat_id) as resp:
            self.events(resp, lambda g: True)
            self.assertEqual(self.call(f"/api/chats/{chat_id}", "DELETE")[0], 200)
            got = self.events(resp, lambda g: any(e.get("ok") is False for e in g))
        self.assertEqual(got[-1]["code"], "not_found")


class WithoutTheDaemonTests(ApiCase):
    def test_the_record_is_still_readable_and_sending_says_the_runtime_is_away(self):
        self.configure([clean("ask", 4)])
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        self.stop_daemon()
        v = self.view(chat_id)
        self.assertEqual((v["runtime"]["available"], v["live"]), (False, None))
        self.assertIn("turn_ended", [r["kind"] for r in v["records"]])
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (503, "unavailable"))
        self.start_daemon()


if __name__ == "__main__":
    unittest.main()
