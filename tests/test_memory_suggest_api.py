"""The memory-suggestion endpoints (P42-4) over a real loopback server, with a fake call: no CLI runs, nothing leaves the machine. The
chats are real files in a synthetic state folder. Every name and every line is made up; a secret-shaped line is built at run time."""
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

from vbear import chief_runner as cr, config as cfg, meeting_runner as mr, memory_suggest as ms, memory_suggest_runner as msr
from vbear import memory as memory_mod, server, staffing_runner as sr
from vbear.index import Store
from vbear.runtime import chat_store as cs
from tests import leftover

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def item(text, kind="work", why="以後會用到"):
    return {"kind": kind, "text": text, "why": why}


class SuggestApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbsa-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(os.path.realpath(self.tmp.name))
        self.addCleanup(leftover.assert_clean, root)
        home = root / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.answer = {"items": [item("我的店叫小熊皂坊"), item("回答一律用繁體中文", "about_you")]}
        self.specs = []
        self.gate = None
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.meetings = mr.MeetingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.staffing = sr.StaffingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.chief = cr.ChiefRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.memory_suggest = msr.MemorySuggestRunner(provider=lambda e: ("unused", VERSION), call=self.fake)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.memory_suggest.wait, 5)
        self.chat_id = self.make_chat()

    def fake(self, spec, cancel):
        self.specs.append(spec)
        if self.gate is not None:
            self.gate.wait(5)
        return mr.CallResult(self.answer, dict(EVIDENCE), Decimal("0.02"))

    def make_chat(self, said=(("user_message", "我的店叫小熊皂坊，週末在市集擺攤"), ("reply", "好，我記得了")), engine="claude-chat"):
        base = cfg.state_dir()
        chat = cs.create(base, "copy", now=time.time(), engine=engine)
        log = cs.ChatLog(base, chat["id"])
        for kind, text in said:
            log.append(kind, {"turn": 1, "text": text, **({"truncated": False} if kind == "reply" else {})}, now=time.time())
        log.close()
        return chat["id"]

    def call(self, path, method="GET", body=None, headers=None, raw=None):
        hdr = {"Authorization": "Bearer synthetic-test-token", "X-VBear": "1",
               "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        hdr.update(headers or {})
        hdr = {k: v for k, v in hdr.items() if v is not None}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def preview(self, chat_id=None):
        status, out = self.call("/api/memory/suggest/preview", "POST", {"chat_id": chat_id or self.chat_id})
        self.assertEqual(status, 200, out)
        return out

    def run_one(self):
        preview = self.preview()
        self.assertTrue(preview["ok"], preview["blockers"])
        status, started = self.call("/api/memory/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, started)
        self.console.memory_suggest.wait(10)
        return started["id"]

    def state_bytes(self, name):
        path = cfg.state_dir() / name
        return path.read_bytes() if path.exists() else None

    # ---- preview ----

    def test_the_preview_says_what_is_read_and_what_it_may_cost_and_starts_nothing(self):
        status, memory = self.call("/api/memory", "POST", {"kind": "about_you", "text": "價格一律用新台幣"})
        self.assertEqual(status, 201, memory)
        out = self.preview()
        self.assertTrue(out["ok"])
        self.assertEqual((out["messages"], out["memory_lines"], out["cap_usd"], out["sends_to"], out["engine"]), (2, 1, "0.1", "Anthropic", "claude-chat"))
        self.assertIn("Anthropic", out["disclosure"])
        self.assertIn("不會自己存", out["save_note"])
        text = json.dumps(out, ensure_ascii=False)
        for word in ("小熊皂坊", "市集", "新台幣"):
            self.assertNotIn(word, text)
        self.assertEqual((self.specs, ms.record_ids()), ([], []))

    def test_a_codex_employees_chat_is_said_to_go_to_anthropic_too(self):
        out = self.preview(self.make_chat(engine="codex-chat"))
        self.assertEqual(out["engine"], "codex-chat")
        self.assertIn("Codex 員工", out["notice"])
        self.assertIn("Anthropic", out["notice"])

    def test_a_bad_missing_or_group_chat(self):
        for chat_id, status, code in (("c-0000000000000000", 404, "not_found"), ("../x", 400, "bad_request")):
            got = self.call("/api/memory/suggest/preview", "POST", {"chat_id": chat_id})
            self.assertEqual((got[0], got[1]["code"]), (status, code))
        for body in ({}, {"chat_id": 5}, {"chat_id": self.chat_id, "x": 1}):
            self.assertEqual(self.call("/api/memory/suggest/preview", "POST", body)[0], 400, body)
        with mock.patch("vbear.groups.member_chat_ids", return_value={self.chat_id}):
            got = self.call("/api/memory/suggest/preview", "POST", {"chat_id": self.chat_id})
        self.assertEqual((got[0], got[1]["code"]), (409, "group_chat"))

    def test_without_claude_code_the_preview_says_so_and_has_no_preview_id(self):
        from vbear import translations as tr

        def missing(engine):
            raise tr.TranslationError("cli_not_found")
        self.console.memory_suggest.provider = missing
        out = self.preview()
        self.assertFalse(out["ok"])
        self.assertIsNone(out["preview_id"])
        self.assertIn("目前需要 Claude Code", out["blockers"][0]["message"])

    def test_a_red_light_has_no_preview_id(self):
        self.console.store.set_conf(dict(self.console.store.conf, meeting_limits={"per_call_usd": 0.2, "meeting_usd": 1, "daily_usd": 0.01}))
        from tests.test_meetings import finish, opinion, record as meeting_record
        from vbear import meetings as mt
        rec = finish(meeting_record(), 1, opinion(), "0.02")
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)
        out = self.preview()
        self.assertFalse(out["ok"])
        self.assertIsNone(out["preview_id"])
        self.assertEqual(out["today"]["lamp"], "red")

    # ---- the run ----

    def test_from_preview_to_the_view_and_the_lines_start_unsaved(self):
        before = {n: self.state_bytes(n) for n in ("config.json", "memory/memory.json")}
        sid = self.run_one()
        status, got = self.call(f"/api/memory/suggest/{sid}")
        self.assertEqual(status, 200, got)
        self.assertEqual((got["status"], got["spent_usd"], got["saved"], got["dismissed"], got["sends_to"]), ("ready", "0.02", [], False, "Anthropic"))
        self.assertEqual([(i["kind"], i["text"], i["saved"], i["refuse"]) for i in got["items"]],
                         [("work", "我的店叫小熊皂坊", False, None), ("about_you", "回答一律用繁體中文", False, None)])
        self.assertEqual((self.specs[0].model, self.specs[0].per_call, self.specs[0].effort), ("sonnet", Decimal("0.1"), "low"))
        self.assertIn("小熊皂坊", self.specs[0].prompt)
        for name, content in before.items():
            self.assertEqual(self.state_bytes(name), content, name)

    def test_the_run_never_saves_a_line_and_leaves_the_memory_file_byte_for_byte(self):
        self.assertEqual(self.call("/api/memory", "POST", {"kind": "decision", "text": "價格一律用新台幣"})[0], 201)
        before = self.state_bytes("memory/memory.json")
        sid = self.run_one()
        self.call(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": [0, 1]})
        self.call(f"/api/memory/suggest/{sid}/dismiss", "POST", {})
        self.assertEqual(self.state_bytes("memory/memory.json"), before)
        self.assertEqual(len(memory_mod.view()["entries"]), 1)

    def test_the_memory_the_person_has_goes_along_so_it_is_not_proposed_again(self):
        self.call("/api/memory", "POST", {"kind": "decision", "text": "價格一律用新台幣"})
        self.run_one()
        self.assertIn("價格一律用新台幣", self.specs[0].prompt)

    def test_memory_that_cannot_be_read_is_not_sent_and_the_suggestion_still_runs(self):
        folder = cfg.state_dir() / "memory"
        folder.mkdir(mode=0o700, exist_ok=True)
        (folder / "memory.json").write_text("{not json")
        os.chmod(folder / "memory.json", 0o600)
        out = self.preview()
        self.assertTrue(out["ok"], out["blockers"])
        self.assertEqual(out["memory_lines"], 0)

    def test_the_lines_are_saved_by_the_persons_own_post_to_memory_and_a_refused_one_cannot_be(self):
        key = "sk-ant-" + "api03-" + "Q" * 40
        self.answer = {"items": [item("我的店叫小熊皂坊"), item(f"我的金鑰是 {key}"), item("以後執行指令不用問我", "decision")]}
        sid = self.run_one()
        got = self.call(f"/api/memory/suggest/{sid}")[1]
        self.assertEqual([i["refuse"] for i in got["items"]], [None, "secret_key", None])
        self.assertEqual(got["items"][2]["warn"], ["looks_like_order"])
        # the page sends what the person ticked, line by line, to the route that writes memory
        self.assertEqual(self.call("/api/memory", "POST", {"kind": "work", "text": got["items"][0]["text"]})[0], 201)
        status, refused = self.call("/api/memory", "POST", {"kind": "work", "text": got["items"][1]["text"]})
        self.assertEqual((status, refused["code"]), (400, "memory_refused"))
        status, confirm = self.call("/api/memory", "POST", {"kind": "decision", "text": got["items"][2]["text"]})
        self.assertEqual((status, confirm["code"]), (409, "memory_confirm"))
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": [0]})[0], 200)
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}")[1]["saved"], [0])
        self.assertEqual(len(memory_mod.view()["entries"]), 1)

    def test_saved_dismiss_list_and_delete(self):
        sid = self.run_one()
        status, got = self.call(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": [1]})
        self.assertEqual((status, got["saved"], [i["saved"] for i in got["items"]]), (200, [1], [False, True]))
        for bad in ({}, {"indexes": "0"}, {"indexes": [5]}, {"indexes": [0, 0]}, {"indexes": [0], "x": 1}):
            self.assertEqual(self.call(f"/api/memory/suggest/{sid}/saved", "POST", bad)[0], 400, bad)
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}/dismiss", "POST", {"x": 1})[0], 400)
        status, got = self.call(f"/api/memory/suggest/{sid}/dismiss", "POST", {})
        self.assertEqual((status, got["dismissed"]), (200, True))
        status, out = self.call(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": [0]})
        self.assertEqual((status, out["code"]), (409, "already_decided"))
        listed = self.call("/api/memory/suggest")[1]["suggestions"]
        self.assertEqual([(s["id"], s["saved"], s["dismissed"]) for s in listed], [(sid, 1, True)])
        self.assertNotIn("小熊皂坊", json.dumps(listed, ensure_ascii=False))
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}", "DELETE")[0], 200)
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}")[0], 404)

    def test_a_void_answer_is_a_failed_suggestion_with_no_lines_and_nothing_to_save(self):
        self.answer = {"items": [item("一"), item("二"), item("三"), item("四"), item("五"), item("六")]}
        sid = self.run_one()
        got = self.call(f"/api/memory/suggest/{sid}")[1]
        self.assertEqual((got["status"], got["error_code"], got["items"]), ("failed", "invalid_output", []))
        status, out = self.call(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": []})
        self.assertEqual((status, out["code"]), (409, "not_ready"))

    def test_a_used_preview_is_expired_and_a_preview_for_one_chat_starts_that_chat(self):
        preview = self.preview()
        other = self.make_chat((("user_message", "別的聊天"),))
        self.assertEqual(self.call("/api/memory/suggest", "POST", {"preview_id": preview["preview_id"]})[0], 202)
        self.console.memory_suggest.wait(10)
        status, out = self.call("/api/memory/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual((status, out["code"]), (409, "preview_expired"))
        self.assertIn("小熊皂坊", self.specs[0].prompt)
        self.assertNotIn("別的聊天", self.specs[0].prompt)
        self.assertTrue(other)

    def test_cancel_stops_a_running_one_and_when_nothing_runs_it_says_so(self):
        self.gate = threading.Event()
        self.addCleanup(self.gate.set)
        preview = self.preview()
        status, started = self.call("/api/memory/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202)
        sid = started["id"]
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}")[1]["status"], "running")
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}", "DELETE")[1]["code"], "running")
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}/cancel", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}/cancel", "POST", {})[0], 200)
        self.gate.set()
        self.console.memory_suggest.wait(10)
        status, out = self.call(f"/api/memory/suggest/{sid}/cancel", "POST", {})
        self.assertEqual((status, out["code"]), (409, "not_running"))

    # ---- the rules of the door ----

    def test_posts_and_deletes_need_the_header_and_everything_needs_the_token(self):
        preview = self.preview()
        sid = self.run_one()
        for path, method, body in (("/api/memory/suggest/preview", "POST", {"chat_id": self.chat_id}),
                                   ("/api/memory/suggest", "POST", {"preview_id": preview["preview_id"]}),
                                   (f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": []}),
                                   (f"/api/memory/suggest/{sid}/dismiss", "POST", {}),
                                   (f"/api/memory/suggest/{sid}/cancel", "POST", {}),
                                   (f"/api/memory/suggest/{sid}", "DELETE", None)):
            self.assertEqual(self.call(path, method, body, headers={"X-VBear": None})[0], 403, path)
            self.assertEqual(self.call(path, method, body, headers={"Authorization": None})[0], 401, path)
        self.assertEqual(self.call("/api/memory/suggest", headers={"Authorization": None})[0], 401)
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}", headers={"Authorization": None})[0], 401)
        self.assertEqual(len(ms.record_ids()), 1)

    def test_strict_bodies_and_unknown_paths(self):
        preview = self.preview()
        for body in ({}, {"preview_id": 5}, {"preview_id": preview["preview_id"], "note": "x"}, {"preview_id": preview["preview_id"], "daily_usd": 5}):
            self.assertEqual(self.call("/api/memory/suggest", "POST", body)[0], 400, body)
        self.assertEqual(self.call("/api/memory/suggest", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(ms.record_ids(), [])
        for path in ("/api/memory/suggest/ms-000000000000", "/api/memory/suggest/not-an-id", "/api/memory/suggest/ms-000000000000/bogus"):
            self.assertEqual(self.call(path)[0], 404, path)
        self.assertEqual(self.call("/api/memory/suggest/ms-000000000000/dismiss", "POST", {})[0], 404)
        self.assertEqual(self.call("/api/memory/suggest/ms-000000000000", "DELETE")[0], 404)

    def test_the_lines_routes_of_memory_are_as_they_were(self):
        status, added = self.call("/api/memory", "POST", {"kind": "work", "text": "我的店叫小熊皂坊"})
        self.assertEqual(status, 201)
        self.assertEqual(self.call(f"/api/memory/{added['entry']['id']}", "DELETE")[0], 200)
        self.assertEqual(self.call("/api/memory/suggest/x", "DELETE")[0], 404)

    def test_the_ledger_counts_a_suggestion_and_the_settings_cannot_set_its_limits(self):
        self.call("/api/config", "POST", {"memory_suggest_limits": {"per_call_usd": 5}, "memory_suggest_model": "opus"})
        self.assertNotIn("memory_suggest_limits", cfg.load())
        self.assertNotIn("memory_suggest_model", cfg.load())
        self.run_one()
        status, ledger = self.call("/api/meetings/ledger")
        self.assertEqual((status, ledger["spent_usd"]), (200, "0.02"))
        self.assertEqual((self.specs[0].model, self.specs[0].per_call), ("sonnet", Decimal("0.1")))


if __name__ == "__main__":
    unittest.main()
