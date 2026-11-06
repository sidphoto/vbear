"""The chief of staff's endpoints (P40-1) over a real loopback server, with a fake call: no CLI runs, nothing leaves the machine.
The chats are real files in a synthetic state folder; the AI tools that can chat are what the test says."""
import hashlib
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

from vbear import agent_profiles as ap, chief, chief_runner as cr, config as cfg, meeting_runner as mr, server, staffing_runner as sr
from vbear.index import Store
from vbear.runtime import chat_store as cs

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def plan():
    return {"summary": "先寫介紹", "task": {"title": "週末市集攤位", "goal": "準備賣手工皂的攤位", "deliverables": ["攤位介紹"]},
            "team": [{"who": "C1", "why": "會寫文案"}, {"who": "N1", "why": "要算成本"}],
            "new_cards": [{"ref": "N1", "name": "會計師", "position": "accountant", "tool": "claude", "model_alias": "haiku", "why": "算價"}],
            "steps": [{"who": "C1", "text": "請寫一份攤位介紹。"}, {"who": "N1", "text": "請算成本與定價。"}], "questions": []}


class ChiefApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbca-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.answer = plan()
        self.specs = []
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.meetings = mr.MeetingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.staffing = sr.StaffingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.chief = cr.ChiefRunner(provider=lambda e: ("unused", VERSION), call=self.fake)
        c.chief_tools = lambda: ("claude",)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.chief.wait, 5)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.ceo, self.writer, self.pm = card("虛構CEO", "planner"), card("文案小編", "social"), card("專案經理", "pm")
        self.chat_id = self.make_chat(self.ceo)

    def fake(self, spec, cancel):
        self.specs.append(spec)
        return mr.CallResult(self.answer, dict(EVIDENCE), Decimal("0.02"))

    def make_chat(self, profile_id, said=(("user_message", "我想在週末市集擺攤賣手工皂"), ("reply", "好，先問你預算"))):
        base = cfg.state_dir()
        chat = cs.create(base, profile_id, now=time.time())
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

    def run_one(self, note=None):
        status, preview = self.call(f"/api/chief/preview?chat_id={self.chat_id}")
        self.assertEqual(status, 200, preview)
        body = {"preview_id": preview["preview_id"]}
        if note is not None:
            body["note"] = note
        status, started = self.call("/api/chief", "POST", body)
        self.assertEqual(status, 202, started)
        self.console.chief.wait(10)
        return started["chief_id"]

    def test_the_preview_reads_nothing_aloud_and_starts_nothing(self):
        status, preview = self.call(f"/api/chief/preview?chat_id={self.chat_id}")
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["ok"])
        self.assertEqual((preview["messages"], preview["cards"], preview["tools"], preview["cap_usd"], preview["sends_to"]),
                         (2, 2, ["claude"], "0.3", "Claude Code"))
        self.assertEqual(preview["day_left_usd"], "3")
        text = json.dumps(preview, ensure_ascii=False)
        for word in ("手工皂", "預算", "文案小編", self.writer):
            self.assertNotIn(word, text)
        self.assertEqual((self.specs, chief.record_ids()), ([], []))

    def test_a_proposal_from_preview_to_the_view(self):
        config_before = (cfg.state_dir() / "config.json").read_bytes() if (cfg.state_dir() / "config.json").exists() else None
        cid = self.run_one(note="預算兩千元")
        status, got = self.call(f"/api/chief/{cid}")
        self.assertEqual(status, 200, got)
        self.assertEqual((got["status"], got["spent_usd"], got["dispatch_id"], got["notes"]), ("ready", "0.02", None, []))
        self.assertEqual([(s["who"], s["name"]) for s in got["plan"]["steps"]], [("C1", "專案經理"), ("N1", "會計師")])
        self.assertEqual([t["kind"] for t in got["plan"]["team"]], ["existing", "new"])
        text = json.dumps(got, ensure_ascii=False)
        for word in (self.pm, self.writer, self.ceo, "預算兩千元", "手工皂的攤位" + "x"):
            self.assertNotIn(word, text)
        self.assertEqual(self.call("/api/chief")[1]["chief"][0]["id"], cid)
        self.assertEqual(self.specs[0].model, "sonnet")
        self.assertIn("預算兩千元", self.specs[0].prompt)
        after = (cfg.state_dir() / "config.json").read_bytes() if (cfg.state_dir() / "config.json").exists() else None
        self.assertEqual(config_before, after)

    def test_what_a_proposal_wrote_into_the_prompt_hash_matches(self):
        cid = self.run_one()
        rec = chief.load(cid)
        self.assertEqual(rec["turns"][0]["prompt_sha256"], hashlib.sha256(self.specs[0].prompt.encode()).hexdigest())

    def test_a_chat_with_anyone_but_a_ceo_is_refused(self):
        other = self.make_chat(self.writer)
        status, out = self.call(f"/api/chief/preview?chat_id={other}")
        self.assertEqual((status, out["code"]), (409, "not_ceo"))

    def test_a_missing_or_bad_chat_id(self):
        self.assertEqual(self.call("/api/chief/preview?chat_id=c-0000000000000000")[0], 404)
        self.assertEqual(self.call("/api/chief/preview?chat_id=..%2Fx")[0], 400)
        self.assertEqual(self.call("/api/chief/preview")[0], 400)

    def test_a_post_needs_the_header_and_the_right_fields(self):
        status, preview = self.call(f"/api/chief/preview?chat_id={self.chat_id}")
        pid = preview["preview_id"]
        self.assertEqual(self.call("/api/chief", "POST", {"preview_id": pid}, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.call("/api/chief", "POST", {"preview_id": pid}, headers={"Authorization": None})[0], 401)
        for body in ({}, {"preview_id": 5}, {"preview_id": pid, "daily_usd": 5}, {"preview_id": pid, "launch_mode": "full"},
                     {"preview_id": pid, "note": 5}):
            self.assertEqual(self.call("/api/chief", "POST", body)[0], 400, body)
        self.assertEqual(self.call("/api/chief", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(chief.record_ids(), [])
        self.assertEqual(self.call("/api/chief", "POST", {"preview_id": pid})[0], 202)

    def test_a_used_preview_is_expired(self):
        self.run_one()
        status, out = self.call("/api/chief", "POST", {"preview_id": "pv-0000000000000000"})
        self.assertEqual((status, out["code"]), (409, "preview_expired"))

    def test_a_failed_call_is_retried_through_the_api_and_a_third_failure_blocks(self):
        self.answer = {"nonsense": 1}
        cid = self.run_one()
        status, got = self.call(f"/api/chief/{cid}")
        self.assertEqual((got["status"], got["error_code"], got["retryable"]), ("failed", "invalid_output", [1]))
        self.assertEqual(self.call(f"/api/chief/{cid}/retry", "POST", {"x": 1})[0], 400)
        self.answer = plan()
        status, out = self.call(f"/api/chief/{cid}/retry", "POST", {})
        self.assertEqual(status, 202, out)
        self.console.chief.wait(10)
        got = self.call(f"/api/chief/{cid}")[1]
        self.assertEqual((got["status"], got["attempts"], got["spent_usd"]), ("ready", 2, "0.04"))
        status, out = self.call(f"/api/chief/{cid}/retry", "POST", {})
        self.assertEqual((status, out["code"]), (409, "not_retryable"))

    def test_cancel_when_nothing_runs(self):
        cid = self.run_one()
        status, out = self.call(f"/api/chief/{cid}/cancel", "POST", {})
        self.assertEqual((status, out["code"]), (409, "not_running"))
        self.assertEqual(self.call(f"/api/chief/{cid}/cancel", "POST", {"x": 1})[0], 400)

    def test_unknown_paths_and_ids(self):
        self.assertEqual(self.call("/api/chief/cos-000000000000")[0], 404)
        self.assertEqual(self.call("/api/chief/not-an-id")[0], 404)
        self.assertEqual(self.call("/api/chief/cos-000000000000/bogus", "POST", {})[0], 404)
        self.assertEqual(self.call("/api/chief/cos-000000000000", "POST", {})[0], 404)

    def test_without_claude_code_the_preview_says_so_and_has_no_preview_id(self):
        from vbear import translations as tr

        def missing(engine):
            raise tr.TranslationError("cli_not_found")
        self.console.chief.provider = missing
        status, preview = self.call(f"/api/chief/preview?chat_id={self.chat_id}")
        self.assertEqual(status, 200)
        self.assertFalse(preview["ok"])
        self.assertIsNone(preview["preview_id"])
        self.assertIn("幕僚長目前需要 Claude Code", preview["blockers"][0]["message"])

    def test_the_tools_a_new_employee_may_name_are_the_chats_that_can_run_now(self):
        class Service:
            @staticmethod
            def support():
                return {"state": "verified", "codex": {"state": "not_logged_in"}}
        self.console.chat_service = lambda: Service()
        self.assertEqual(server.Console.chief_tools(self.console), ("claude",))

    def test_the_ledger_lists_the_chief_of_staff_and_counts_it(self):
        self.run_one()
        status, ledger = self.call("/api/meetings/ledger")
        self.assertEqual((status, ledger["spent_usd"]), (200, "0.02"))
        self.assertIn("chief", ledger["includes"])

    def test_the_settings_cannot_set_the_chiefs_limits(self):
        self.call("/api/config", "POST", {"chief_limits": {"per_call_usd": 5}, "chief_model": "opus"})
        self.assertNotIn("chief_limits", cfg.load())
        self.assertNotIn("chief_model", cfg.load())
        self.run_one()
        self.assertEqual((self.specs[0].model, self.specs[0].per_call), ("sonnet", Decimal("0.3")))


if __name__ == "__main__":
    unittest.main()
