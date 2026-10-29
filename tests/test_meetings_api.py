"""The meeting endpoints (P34-4) over a real loopback server, with a fake call: no CLI runs, nothing leaves the machine."""
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

from vbear import agent_profiles as ap, config as cfg, meeting_runner as mr, meetings as mt, server, tasks
from vbear.index import Store

VERSION = "2.1.296"
OPINION = {"stance": "支持", "summary": "可以做", "points": ["一"], "risks": [], "needs_chairman": False}
DECISION = {"decision": "照做", "rationale": "沒問題", "dissent_addressed": [], "actions": [{"type": "寫草稿", "text": "寫"}],
            "escalate": False, "escalate_reason": "", "follow_up_topics": []}
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def fake_call(spec, cancel):
    return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION, dict(EVIDENCE), Decimal("0.01"))


class MeetingApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-meetings-api-test-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.meetings = mr.MeetingRunner(provider=lambda engine: ("unused", VERSION), call=fake_call)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.meetings.wait, 5)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.ceo, self.pm, self.legal = card("CEO", "planner"), card("PM", "pm"), card("法務", "legal")
        self.task_id = tasks.save_task(None, {"title": "改按鈕", "goal": "讓它變大"})["id"]

    def call(self, path, method="GET", body=None, headers=None, raw=None):
        hdr = {"Authorization": "Bearer synthetic-test-token", "X-VBear": "1",
               "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        hdr.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def body(self, **kw):
        body = {"topic": "要不要改按鈕", "chair_profile_id": self.ceo, "speaker_profile_ids": [self.pm, self.legal]}
        body.update(kw)
        return body

    def meet(self, **kw):
        status, preview = self.call("/api/meetings/preview", "POST", self.body(**kw))
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["startable"], preview["blockers"])
        status, view = self.call("/api/meetings", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, view)
        self.console.meetings.wait(10)
        return view["id"]

    def test_the_whole_way_preview_start_read_decide_delete(self):
        mid = self.meet(task_id=self.task_id, context="補充")
        status, view = self.call(f"/api/meetings/{mid}")
        self.assertEqual((status, view["status"], view["chairman"]["state"]), (200, "decided", "not_needed"))
        self.assertEqual([t["state"] for t in view["turns"]], ["done"] * 3)
        status, listing = self.call("/api/meetings")
        self.assertEqual([m["id"] for m in listing["meetings"]], [mid])
        status, ledger = self.call("/api/meetings/ledger")
        self.assertEqual((status, ledger["spent_usd"], ledger["lamp"], ledger["daily_usd"]), (200, "0.03", "green", "3"))
        status, out = self.call(f"/api/meetings/{mid}/chairman", "POST", {"decision": "reject", "note": "不要"})
        self.assertEqual((status, out["status"]), (200, "rejected"))
        self.assertEqual(self.call(f"/api/meetings/{mid}/chairman", "POST", {"decision": "reject"})[0], 409)
        self.assertEqual(self.call(f"/api/meetings/{mid}", "DELETE")[0], 200)
        self.assertEqual(self.call(f"/api/meetings/{mid}")[0], 404)

    def test_a_retry_goes_through_its_own_preview(self):
        failed = {"n": 0}

        def call(spec, cancel):
            if spec.kind == "opinion" and failed["n"] == 0:
                failed["n"] += 1
                raise mr.CallFailed("cli_failed", dict(EVIDENCE), None)
            return fake_call(spec, cancel)
        self.console.meetings = mr.MeetingRunner(provider=lambda e: ("unused", VERSION), call=call)
        mid = self.meet()
        status, view = self.call(f"/api/meetings/{mid}")
        self.assertEqual(view["retryable"], [1])
        status, preview = self.call(f"/api/meetings/{mid}/retry-preview", "POST", {"seq": 1})
        self.assertEqual((status, preview["startable"], preview["calls"]), (200, True, 2))
        # a preview of another meeting's retry does not open this one
        self.assertEqual(self.call("/api/meetings/m-ffffffffffff/retry", "POST", {"preview_id": preview["preview_id"]})[0], 409)
        status, out = self.call(f"/api/meetings/{mid}/retry", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, out)
        self.console.meetings.wait(10)
        self.assertEqual(self.call(f"/api/meetings/{mid}")[1]["turns"][0]["state"], "done")
        self.assertEqual(self.call(f"/api/meetings/{mid}/retry", "POST", {"preview_id": preview["preview_id"]})[0], 409)  # used once

    def test_cancel_of_a_meeting_that_is_not_running_is_a_conflict(self):
        mid = self.meet()
        self.assertEqual(self.call(f"/api/meetings/{mid}/cancel", "POST", {})[0], 409)

    def test_reads_run_nothing_and_a_preview_starts_no_program_but_the_version_check(self):
        mid = self.meet()
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no CLI")):
            for path in ("/api/meetings", "/api/meetings/ledger", f"/api/meetings/{mid}"):
                self.assertEqual(self.call(path)[0], 200, path)

    def test_the_same_guards_as_every_other_endpoint(self):
        mid = self.meet()
        for path, method, body in (("/api/meetings/preview", "POST", self.body()), ("/api/meetings", "POST", {"preview_id": "x"}),
                                   (f"/api/meetings/{mid}/chairman", "POST", {"decision": "reject"}), (f"/api/meetings/{mid}", "DELETE", None)):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, method, body, headers={"Authorization": "Bearer wrong"})[0], 401)
                self.assertEqual(self.call(path, method, body, headers={"X-VBear": "0"})[0], 403)
                self.assertEqual(self.call(path, method, body, headers={"Origin": "http://evil.example"})[0], 403)
        for path in ("/api/meetings", "/api/meetings/ledger", f"/api/meetings/{mid}"):
            with self.subTest(path=path):
                self.assertEqual(self.call(path, headers={"Authorization": "Bearer wrong"})[0], 401)
                self.assertEqual(self.call(path, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.call("/api/meetings/preview", "POST", {"x": "a" * 66000})[0], 413)

    def test_malformed_input_is_refused_not_guessed(self):
        mid = self.meet()
        cases = [self.body(topic=float("nan")), self.body(topic=True), self.body(topic=["x"]), self.body(topic="x" * 501),
                 self.body(context="x" * 4001), self.body(flags="spend"), self.body(flags=[True]), self.body(flags=["nope"]),
                 self.body(task_id=5), self.body(task_id="../x"), self.body(chair_profile_id=5), self.body(chair_profile_id=[]),
                 self.body(speaker_profile_ids="pm"), self.body(speaker_profile_ids=[1, 2]), self.body(speaker_profile_ids=[]),
                 self.body(speaker_profile_ids=[self.pm] * 2), self.body(unknown=1), self.body(speaker_profile_ids=None)]
        for body in cases:
            with self.subTest(body=str(body)[:60]):
                status, out = self.call("/api/meetings/preview", "POST", raw=json.dumps(body).encode())
                self.assertIn(status, (400, 404), out)
        for raw in (b"[]", b'"x"', b"null", b"{bad", b'{"topic": NaN}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.call("/api/meetings/preview", "POST", raw=raw)[0], 400)
        for body in ({}, {"preview_id": 5}, {"preview_id": None}, {"preview_id": "pv-x", "extra": 1}, {"preview_id": float("nan")}, []):
            with self.subTest(start=body):
                self.assertIn(self.call("/api/meetings", "POST", raw=json.dumps(body).encode())[0], (400, 409))
        for body in ({}, {"decision": "x"}, {"decision": True}, {"decision": "reject", "note": 5}, {"decision": "reject", "z": 1}):
            with self.subTest(chair=body):
                self.assertEqual(self.call(f"/api/meetings/{mid}/chairman", "POST", raw=json.dumps(body).encode())[0], 400)
        for body in ({}, {"seq": "1"}, {"seq": True}, {"seq": float("nan")}, {"seq": 1, "x": 1}, {"seq": 99}):
            with self.subTest(retry=body):
                self.assertEqual(self.call(f"/api/meetings/{mid}/retry-preview", "POST", raw=json.dumps(body).encode())[0], 400)
        self.assertEqual(self.call("/api/meetings/m-nothing")[0], 404)
        self.assertEqual(self.call("/api/meetings/m-0123456789ab/unknown", "POST", {})[0], 404)

    def test_meeting_limits_in_the_config_are_validated_on_write(self):
        status, out = self.call("/api/config", "POST", {"meeting_limits": {"per_call_usd": 0.3}})
        self.assertEqual(status, 200, out)
        self.assertEqual(cfg.load()["meeting_limits"], {"per_call_usd": 0.3, "meeting_usd": 1.5, "daily_usd": 3.0})
        self.assertEqual(self.call("/api/meetings/ledger")[1]["per_call_usd"], "0.3")
        for bad in ({"per_call_usd": True}, {"per_call_usd": 2}, {"meeting_usd": 11}, {"x": 1}, {"daily_usd": 1}, [], "x", None, {"per_call_usd": "0.1"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": bad})[0], 400)
        self.assertEqual(self.call("/api/config", "POST", raw=b'{"meeting_limits": {"daily_usd": NaN}}')[0], 400)
        self.assertEqual(cfg.load()["meeting_limits"]["per_call_usd"], 0.3)

    def test_a_meeting_never_touches_the_task_card(self):
        before = tasks.get_task(self.task_id)
        self.meet(task_id=self.task_id)
        self.assertEqual(tasks.get_task(self.task_id), before)
        self.assertFalse((cfg.state_dir() / "flows.json").exists())


if __name__ == "__main__":
    unittest.main()
