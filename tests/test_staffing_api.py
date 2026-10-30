"""The staffing meeting endpoints (P35-2) over a real loopback server, with a fake call: no CLI runs, nothing leaves the
machine. The skills are a synthetic index in memory, their Chinese summaries an owned translations.json in the fake home."""
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

from vbear import agent_profiles as ap, config as cfg, meeting_runner as mr, server, staffing as st, staffing_runner as sr
from vbear import tasks, translations as tr
from vbear.index import Store

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def skill(sid, name, cats, excerpt):
    return {"skill_id": sid, "name": name, "invoke_name": name, "tool": "claude", "read_by": [], "scope": "user",
            "activation": "active", "mtime": 1, "excerpt": excerpt, "description": excerpt, "categories": cats}


def answer(spec, cancel):
    if spec.kind == "proposal":
        out = {"summary": "照發言組隊", "team": [], "staff": [], "new_cards": [], "skill_gaps": [], "risks": [],
               "questions_for_chairman": [], "opinions_used": []}
    else:
        out = {"summary": "需要前端", "needs": [], "recommend": [], "skills": [], "skill_gaps": [], "risks": []}
    return mr.CallResult(out, dict(EVIDENCE), Decimal("0.01"))


class StaffingApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-staffing-api-test-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.skills = [skill("s-front", "網站前端", ["frontend"], "Build web pages (fictional)."),
                       skill("s-law", "授權檢查", ["legal"], "Check licences (fictional).")]
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
        c.store = Store()
        c.store._static = {"skills": self.skills, "roles": []}
        c.store.set_conf(cfg.load())
        c.meetings = mr.MeetingRunner(provider=lambda engine: ("unused", VERSION), call=answer)
        c.staffing = sr.StaffingRunner(provider=lambda engine: ("unused", VERSION), call=answer)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.staffing.wait, 5)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.ceo, self.pm, self.legal = card("虛構CEO", "planner"), card("虛構PM", "pm"), card("虛構法務", "legal")
        self.eng = card("虛構工程師", "executor")
        self.task_id = tasks.save_task(None, {"title": "官網改版（虛構）", "goal": "改首頁並確認圖片授權", "scope": ["前端頁面"]})["id"]

    def call(self, path, method="GET", body=None, raw=None):
        hdr = {"Authorization": "Bearer synthetic-test-token", "X-VBear": "1",
               "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def body(self, **kw):
        body = {"task_id": self.task_id, "chair_profile_id": self.ceo, "speaker_profile_ids": [self.pm, self.legal]}
        body.update(kw)
        return body

    def run_one(self):
        status, preview = self.call("/api/staffing/preview", "POST", self.body())
        self.assertEqual(status, 200, preview)
        status, started = self.call("/api/staffing", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, started)
        self.console.staffing.wait(10)
        return started["id"]

    def test_suggest_reads_only(self):
        status, out = self.call(f"/api/staffing/suggest?task_id={self.task_id}")
        self.assertEqual(status, 200, out)
        self.assertEqual([s["profile_id"] for s in out["suggested"]], [self.pm, self.eng, self.legal])
        self.assertEqual(out["chairs"], [{"profile_id": self.ceo, "name": "虛構CEO"}])
        self.assertEqual(self.call("/api/staffing/suggest?task_id=t-404")[0], 404)
        self.assertEqual(self.call("/api/staffing/suggest?task_id=..%2Fx")[0], 400)
        self.assertEqual(self.call("/api/staffing/suggest")[0], 400)
        self.assertEqual(st.record_ids(), [])

    def test_a_staffing_meeting_from_preview_to_the_chairman(self):
        sid = self.run_one()
        status, got = self.call(f"/api/staffing/{sid}")
        self.assertEqual(status, 200, got)
        self.assertEqual((got["status"], got["changed_cards"], got["task_id"]), ("ready", [], self.task_id))
        status, listing = self.call(f"/api/staffing?task_id={self.task_id}")
        self.assertEqual([x["id"] for x in listing["staffing"]], [sid])
        self.assertEqual(self.call("/api/staffing?task_id=other-task")[1]["staffing"], [])
        self.assertEqual(self.call("/api/staffing?task_id=..%2Fx")[0], 400)
        self.assertEqual(self.call(f"/api/staffing/{sid}/cancel", "POST", {})[1]["code"], "not_running")
        status, out = self.call(f"/api/staffing/{sid}/chairman", "POST", {"decision": "adopt", "note": "照辦（虛構）"})
        self.assertEqual((status, out["status"], out["chairman"]["adopted"]), (200, "adopted", None))
        self.assertEqual(self.call(f"/api/staffing/{sid}", "DELETE"), (200, {"ok": True, "deleted": sid}))
        self.assertEqual(self.call(f"/api/staffing/{sid}")[0], 404)

    def test_the_ceo_is_given_a_fresh_chinese_summary_and_never_a_stale_one(self):
        summary = {"what": "做網站前端的虛構摘要", "when": "要改網頁時", "needs": "原文未提供"}
        entry = {"lang": "zh-TW", "source_hash": tr.source_hash(self.skills[0]), "created_at": time.time(), "engine": "claude",
                 "model": tr.MODELS["claude"], "cli_version": VERSION, "summary": summary, "description_zh": "虛構的說明"}
        stale = dict(entry, source_hash="0" * 64, summary=dict(summary, what="過期的虛構摘要"))
        store = tr.TranslationStore()
        with store.locked():
            store.save({"version": 1, "entries": {"s-front": entry, "s-law": stale}})
        status, preview = self.call("/api/staffing/preview", "POST", self.body())
        self.assertEqual(status, 200, preview)
        self.assertIn("做網站前端的虛構摘要", preview["chair"]["prompt"])
        self.assertNotIn("過期的虛構摘要", preview["chair"]["prompt"])
        self.assertIn("Check licences (fictional).", preview["chair"]["prompt"])

    def test_the_requests_are_strict_and_the_addresses_exact(self):
        self.assertEqual(self.call("/api/staffing/preview", "POST", self.body(extra=1))[0], 400)
        self.assertEqual(self.call("/api/staffing/preview", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(self.call("/api/staffing/preview", "POST", self.body(task_id="t-404"))[0], 404)
        self.assertEqual(self.call("/api/staffing", "POST", {"preview_id": "pv-x", "more": 1})[0], 400)
        self.assertEqual(self.call("/api/staffing", "POST", {"preview_id": "pv-0000000000000000"})[1]["code"], "preview_expired")
        for path in ("/api/staffing/s-zzz", "/api/staffing/s-0123456789ab/unknown", "/api/staffing/m-0123456789ab"):
            with self.subTest(path=path):
                self.assertEqual(self.call(path)[0], 404)
                self.assertEqual(self.call(path, "DELETE")[0], 404)
        self.assertEqual(self.call("/api/staffing/s-0123456789ab")[0], 404)
        self.assertEqual(self.call("/api/staffing/s-0123456789ab/retry-preview", "POST", {"seq": 1})[0], 404)

    def test_a_retry_over_the_api(self):
        calls = {"n": 0}

        def flaky(spec, cancel):
            calls["n"] += 1
            if calls["n"] == 1:
                raise mr.CallFailed("cli_failed", dict(EVIDENCE, exit_code=1), None)
            return answer(spec, cancel)
        self.console.staffing.call = flaky
        sid = self.run_one()
        status, preview = self.call(f"/api/staffing/{sid}/retry-preview", "POST", {"seq": 1})
        self.assertEqual((status, preview["calls"], preview["proposal_again"]), (200, 2, True))
        other = "s-0123456789ab"
        self.assertEqual(self.call(f"/api/staffing/{other}/retry", "POST", {"preview_id": preview["preview_id"]})[1]["code"],
                         "preview_expired")
        status, out = self.call(f"/api/staffing/{sid}/retry", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, out)
        self.console.staffing.wait(10)
        self.assertEqual(self.call(f"/api/staffing/{sid}")[1]["status"], "ready")

    def test_the_staffing_limits_are_validated_on_write_and_the_ledger_adds_both(self):
        status, out = self.call("/api/config", "POST", {"staffing_limits": {"total_usd": 2.5}})
        self.assertEqual(status, 200, out)
        self.assertEqual(cfg.load()["staffing_limits"], {"proposal_call_usd": 0.5, "total_usd": 2.5})
        for bad in ({"total_usd": 5}, {"proposal_call_usd": 3}, {"per_call_usd": 0.1}, {"total_usd": "2"}, [], "x"):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("/api/config", "POST", {"staffing_limits": bad})[0], 400)
        self.assertEqual(self.call("/api/config", "POST", raw=b'{"staffing_limits": {"total_usd": NaN}}')[0], 400)
        # the day raised in the same request is the day the record's limit is checked against
        status, out = self.call("/api/config", "POST", {"staffing_limits": {"total_usd": 8}, "meeting_limits": {"daily_usd": 10}})
        self.assertEqual(status, 200, out)
        self.assertEqual(cfg.load()["staffing_limits"]["total_usd"], 8.0)
        self.run_one()
        status, ledger = self.call("/api/meetings/ledger")
        self.assertEqual((ledger["spent_usd"], ledger["includes"]), ("0.03", ["meetings", "staffing"]))

    def test_the_two_runners_are_built_together(self):
        fresh = server.Console.__new__(server.Console)
        fresh.lock = threading.Lock()
        with mock.patch.object(mr, "MeetingRunner") as meetings, mock.patch.object(sr, "StaffingRunner") as staffing:
            self.assertIs(fresh.meeting_runner(), meetings.return_value)
            self.assertEqual((meetings.call_count, staffing.call_count), (1, 1))
            self.assertIs(fresh.staffing_runner(), staffing.return_value)
            self.assertEqual((meetings.call_count, staffing.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
