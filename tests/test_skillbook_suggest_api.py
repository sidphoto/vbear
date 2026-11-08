"""The skill-suggestion endpoints (P44-5) over a real loopback server, with a fake call: no CLI runs, nothing leaves the machine. The chats
are real files in a synthetic state folder. Every name and every text is made up; a secret-shaped text is built at run time."""
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

from vbear import chief_runner as cr, config as cfg, meeting_runner as mr, memory_suggest_runner as msr, server, skillbook, staffing_runner as sr
from vbear import skillbook_suggest as ks, skillbook_suggest_runner as ksr
from vbear.index import Store
from vbear.runtime import chat_store as cs
from tests import leftover

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def item(name="市集日報", text="請把昨天市集的銷售整理成一段話。\n1. 先列賣了什麼\n2. 再寫天氣", note="根據你前面說的步驟"):
    return {"name": name, "text": text, "note": note}


class SkillSuggestApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbka-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(os.path.realpath(self.tmp.name))
        self.addCleanup(leftover.assert_clean, root)
        home = root / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.answer = {"items": [item()]}
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
        c.memory_suggest = msr.MemorySuggestRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.skill_suggest = ksr.SkillSuggestRunner(provider=lambda e: ("unused", VERSION), call=self.fake)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.skill_suggest.wait, 5)
        self.chat_id = self.make_chat()

    def fake(self, spec, cancel):
        self.specs.append(spec)
        if self.gate is not None:
            self.gate.wait(5)
        return mr.CallResult(self.answer, dict(EVIDENCE), Decimal("0.02"))

    def make_chat(self, said=(("user_message", "每天早上我要把市集的銷售整理成一段話"), ("reply", "好，先列賣了什麼")), engine="claude-chat"):
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
        status, out = self.call("/api/my-skills/suggest/preview", "POST", {"chat_id": chat_id or self.chat_id})
        self.assertEqual(status, 200, out)
        return out

    def run_one(self):
        preview = self.preview()
        self.assertTrue(preview["ok"], preview["blockers"])
        status, started = self.call("/api/my-skills/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, started)
        self.console.skill_suggest.wait(10)
        return started["id"]

    def state_bytes(self, name):
        path = cfg.state_dir() / name
        return path.read_bytes() if path.exists() else None

    # ---- preview ----

    def test_the_preview_says_what_is_read_and_what_it_may_cost_and_starts_nothing(self):
        out = self.preview()
        self.assertTrue(out["ok"])
        self.assertEqual((out["messages"], out["cap_usd"], out["sends_to"], out["engine"]), (2, "0.1", "Anthropic", "claude-chat"))
        self.assertIn("Anthropic", out["disclosure"])
        self.assertIn("不會自己存", out["save_note"])
        text = json.dumps(out, ensure_ascii=False)
        for word in ("市集", "銷售"):
            self.assertNotIn(word, text)
        self.assertEqual((self.specs, ks.record_ids()), ([], []))

    def test_a_codex_employees_chat_is_said_to_go_to_anthropic_too(self):
        out = self.preview(self.make_chat(engine="codex-chat"))
        self.assertEqual(out["engine"], "codex-chat")
        self.assertIn("Codex 員工", out["notice"])
        self.assertIn("Anthropic", out["notice"])

    def test_a_bad_missing_or_group_chat(self):
        for chat_id, status, code in (("c-0000000000000000", 404, "not_found"), ("../x", 400, "bad_request")):
            got = self.call("/api/my-skills/suggest/preview", "POST", {"chat_id": chat_id})
            self.assertEqual((got[0], got[1]["code"]), (status, code))
        for body in ({}, {"chat_id": 5}, {"chat_id": self.chat_id, "x": 1}):
            self.assertEqual(self.call("/api/my-skills/suggest/preview", "POST", body)[0], 400, body)
        with mock.patch("vbear.groups.member_chat_ids", return_value={self.chat_id}):
            got = self.call("/api/my-skills/suggest/preview", "POST", {"chat_id": self.chat_id})
        self.assertEqual((got[0], got[1]["code"]), (409, "group_chat"))

    def test_without_claude_code_the_preview_says_so_and_has_no_preview_id(self):
        from vbear import translations as tr

        def missing(engine):
            raise tr.TranslationError("cli_not_found")
        self.console.skill_suggest.provider = missing
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

    def test_from_preview_to_the_view_and_nothing_is_saved_by_the_run(self):
        self.assertEqual(self.call("/api/my-skills", "POST", {"name": "舊技能", "text": "請寫一段話"})[0], 201)
        before = {n: self.state_bytes(n) for n in ("config.json", "skillbook/skills.json", "skillbook/log.jsonl")}
        sid = self.run_one()
        status, got = self.call(f"/api/my-skills/suggest/{sid}")
        self.assertEqual(status, 200, got)
        self.assertEqual((got["status"], got["spent_usd"], got["saved"], got["dismissed"], got["sends_to"]), ("ready", "0.02", False, False, "Anthropic"))
        self.assertEqual([(i["name"], i["text"], i["note"], i["saved"], i["refuse"]) for i in got["items"]],
                         [("市集日報", item()["text"], item()["note"], False, None)])
        self.assertEqual((self.specs[0].model, self.specs[0].per_call, self.specs[0].effort), ("sonnet", Decimal("0.1"), "low"))
        self.assertIn("銷售", self.specs[0].prompt)
        for name, content in before.items():
            self.assertEqual(self.state_bytes(name), content, name)
        self.assertEqual(len(skillbook.view()["skills"]), 1)

    def test_the_suggestion_is_saved_only_by_the_persons_own_post_with_how_suggested(self):
        sid = self.run_one()
        got = self.call(f"/api/my-skills/suggest/{sid}")[1]["items"][0]
        # the box of 存成技能 sends what the person kept, to the route that writes skills
        status, saved = self.call("/api/my-skills", "POST", {"name": got["name"], "text": got["text"],
                                                              "source": {"how": "suggested", "suggestion_id": sid}})
        self.assertEqual(status, 201, saved)
        self.assertEqual(saved["skill"]["source"], {"how": "suggested", "suggestion_id": sid})
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}/saved", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}")[1]["saved"], True)
        self.assertEqual(len(skillbook.view()["skills"]), 1)

    def test_a_suggestion_that_is_not_there_cannot_be_the_source_of_a_skill(self):
        status, out = self.call("/api/my-skills", "POST", {"name": "x", "text": "請寫一段話", "source": {"how": "suggested", "suggestion_id": "ks-000000000000"}})
        self.assertEqual((status, out["code"]), (400, "bad_request"))
        self.assertEqual(skillbook.view()["skills"], [])

    def test_a_refused_proposal_is_shown_so_and_the_skill_route_refuses_it(self):
        key = "sk-ant-" + "api03-" + "Q" * 40
        self.answer = {"items": [item(text=f"請用這個金鑰 {key} 登入")]}
        sid = self.run_one()
        got = self.call(f"/api/my-skills/suggest/{sid}")[1]["items"][0]
        self.assertEqual(got["refuse"], "secret_key")
        status, out = self.call("/api/my-skills", "POST", {"name": got["name"], "text": got["text"], "source": {"how": "suggested", "suggestion_id": sid}})
        self.assertEqual((status, out["code"]), (400, "skill_refused"))

    def test_saved_dismiss_list_and_delete(self):
        sid = self.run_one()
        for bad in ({"x": 1}, {"indexes": [0]}):
            self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}/saved", "POST", bad)[0], 400, bad)
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}/dismiss", "POST", {"x": 1})[0], 400)
        status, got = self.call(f"/api/my-skills/suggest/{sid}/saved", "POST", {})
        self.assertEqual((status, got["saved"], [i["saved"] for i in got["items"]]), (200, True, [True]))
        status, got = self.call(f"/api/my-skills/suggest/{sid}/dismiss", "POST", {})
        self.assertEqual((status, got["dismissed"]), (200, True))
        status, out = self.call(f"/api/my-skills/suggest/{sid}/saved", "POST", {})
        self.assertEqual((status, out["code"]), (409, "already_decided"))
        listed = self.call("/api/my-skills/suggest")[1]["suggestions"]
        self.assertEqual([(s["id"], s["saved"], s["dismissed"], s["found"]) for s in listed], [(sid, True, True, 1)])
        self.assertNotIn("市集日報", json.dumps(listed, ensure_ascii=False))
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}", "DELETE")[0], 200)
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}")[0], 404)

    def test_a_void_answer_is_a_failed_suggestion_with_nothing_to_save(self):
        self.answer = {"items": [item(), item("二")]}
        sid = self.run_one()
        got = self.call(f"/api/my-skills/suggest/{sid}")[1]
        self.assertEqual((got["status"], got["error_code"], got["items"]), ("failed", "invalid_output", []))
        status, out = self.call(f"/api/my-skills/suggest/{sid}/saved", "POST", {})
        self.assertEqual((status, out["code"]), (409, "not_ready"))

    def test_nothing_worth_keeping_is_an_empty_ready_suggestion(self):
        self.answer = {"items": []}
        got = self.call(f"/api/my-skills/suggest/{self.run_one()}")[1]
        self.assertEqual((got["status"], got["items"], got["spent_usd"]), ("ready", [], "0.02"))

    def test_a_used_preview_is_expired(self):
        preview = self.preview()
        self.assertEqual(self.call("/api/my-skills/suggest", "POST", {"preview_id": preview["preview_id"]})[0], 202)
        self.console.skill_suggest.wait(10)
        status, out = self.call("/api/my-skills/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual((status, out["code"]), (409, "preview_expired"))

    def test_cancel_stops_a_running_one_and_when_nothing_runs_it_says_so(self):
        self.gate = threading.Event()
        self.addCleanup(self.gate.set)
        preview = self.preview()
        status, started = self.call("/api/my-skills/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202)
        sid = started["id"]
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}")[1]["status"], "running")
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}", "DELETE")[1]["code"], "running")
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}/cancel", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}/cancel", "POST", {})[0], 200)
        self.gate.set()
        self.console.skill_suggest.wait(10)
        status, out = self.call(f"/api/my-skills/suggest/{sid}/cancel", "POST", {})
        self.assertEqual((status, out["code"]), (409, "not_running"))

    # ---- the rules of the door ----

    def test_posts_and_deletes_need_the_header_and_everything_needs_the_token(self):
        preview = self.preview()
        sid = self.run_one()
        for path, method, body in (("/api/my-skills/suggest/preview", "POST", {"chat_id": self.chat_id}),
                                   ("/api/my-skills/suggest", "POST", {"preview_id": preview["preview_id"]}),
                                   (f"/api/my-skills/suggest/{sid}/saved", "POST", {}),
                                   (f"/api/my-skills/suggest/{sid}/dismiss", "POST", {}),
                                   (f"/api/my-skills/suggest/{sid}/cancel", "POST", {}),
                                   (f"/api/my-skills/suggest/{sid}", "DELETE", None)):
            self.assertEqual(self.call(path, method, body, headers={"X-VBear": None})[0], 403, path)
            self.assertEqual(self.call(path, method, body, headers={"Authorization": None})[0], 401, path)
        self.assertEqual(self.call("/api/my-skills/suggest", headers={"Authorization": None})[0], 401)
        self.assertEqual(self.call(f"/api/my-skills/suggest/{sid}", headers={"Authorization": None})[0], 401)
        self.assertEqual(len(ks.record_ids()), 1)

    def test_strict_bodies_and_unknown_paths(self):
        preview = self.preview()
        for body in ({}, {"preview_id": 5}, {"preview_id": preview["preview_id"], "note": "x"}, {"preview_id": preview["preview_id"], "daily_usd": 5}):
            self.assertEqual(self.call("/api/my-skills/suggest", "POST", body)[0], 400, body)
        self.assertEqual(self.call("/api/my-skills/suggest", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(ks.record_ids(), [])
        for path in ("/api/my-skills/suggest/ks-000000000000", "/api/my-skills/suggest/not-an-id", "/api/my-skills/suggest/ks-000000000000/bogus"):
            self.assertEqual(self.call(path)[0], 404, path)
        self.assertEqual(self.call("/api/my-skills/suggest/ks-000000000000/dismiss", "POST", {})[0], 404)
        self.assertEqual(self.call("/api/my-skills/suggest/ks-000000000000", "DELETE")[0], 404)

    def test_the_skill_routes_are_as_they_were(self):
        status, added = self.call("/api/my-skills", "POST", {"name": "市集日報", "text": "請寫一段話"})
        self.assertEqual(status, 201)
        self.assertEqual(self.call(f"/api/my-skills/{added['skill']['id']}/delete", "POST", {})[0], 200)
        self.assertEqual(self.call("/api/my-skills/suggest/x", "DELETE")[0], 404)
        self.assertEqual(self.call("/api/my-skills")[1]["skills"], [])

    def test_the_ledger_counts_a_suggestion_and_the_settings_cannot_set_its_limits(self):
        self.call("/api/config", "POST", {"skill_suggest_limits": {"per_call_usd": 5}, "skill_suggest_model": "opus"})
        self.assertNotIn("skill_suggest_limits", cfg.load())
        self.assertNotIn("skill_suggest_model", cfg.load())
        self.run_one()
        status, ledger = self.call("/api/meetings/ledger")
        self.assertEqual((status, ledger["spent_usd"]), (200, "0.02"))
        self.assertIn("skill_suggest", ledger["includes"])
        self.assertEqual((self.specs[0].model, self.specs[0].per_call), ("sonnet", Decimal("0.1")))


if __name__ == "__main__":
    unittest.main()
