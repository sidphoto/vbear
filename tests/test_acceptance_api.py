"""The risk-acceptance routes of the console (S2c-1): POST
/api/flows/<id>/acceptance-preview and /acceptance, and the acceptance state
in the flow view. A fake host stands in for the machine."""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from tests.test_risk_acceptance import FakeHost, roles
from vbear import acceptance as acc
from vbear import config as cfg
from vbear import flows, risk_acceptance as ra, tasks


class AcceptanceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from vbear.server import Console, make_handler
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(os.path.realpath(cls.tmp.name))
        cls.state = cls.root / "st"
        cls.state.mkdir(mode=0o700)
        cls.env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(cls.state), "VBEAR_RUNTIME_AUTOSTART": "0"})
        cls.env.start()
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for src in conf["sources"]:
            src["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        cls.port = cls.httpd.server_address[1]
        cls.console = Console(cls.port)
        cls.token = cls.console.auth_token
        cls.httpd.RequestHandlerClass = make_handler(cls.console)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.env.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.host = FakeHost(self.root)
        p = mock.patch.object(ra, "DEFAULT_HOST", self.host)
        p.start()
        self.addCleanup(p.stop)
        v = mock.patch("vbear.runtime.cli_versions.stream_verified_versions", return_value=("2.1.292",))
        v.start()
        self.addCleanup(v.stop)
        (self.root / "claude.json").write_text(json.dumps({"oauthAccount": {
            "accountUuid": "11111111-2222-3333-4444-555555555555",
            "organizationUuid": "66666666-7777-8888-9999-000000000000"}}))
        home = self.state / "codex-home"
        home.mkdir(mode=0o700, exist_ok=True)
        (home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": "acct-0001"}}))
        os.chmod(home / "auth.json", 0o600)
        tid = tasks.save_task(None, {"title": "接受測試"})["id"]
        self.fid = flows.create_flow({"task_id": tid, "roles": roles()}, lambda t: True)["id"]

    def call(self, path, method="GET", body=None, token=True, write_header=True):
        h = {"Content-Type": "application/json"}
        if write_header:
            h["X-VBear"] = "1"
        if token:
            h["Authorization"] = f"Bearer {self.token}"
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"null")
            e.close()
            return e.code, data

    def test_preview_then_confirm_and_the_flow_shows_it(self):
        st, flow = self.call(f"/api/flows/{self.fid}")
        self.assertEqual(flow["flow"]["acceptance"]["state"], "none")
        st, pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {"limits": {"max_reviews": 4}})
        self.assertEqual(st, 200, pre)
        self.assertTrue(pre["ok"])
        self.assertEqual(len(pre["risk_text"]["zh"]["items"]), 3)
        self.assertNotRegex(json.dumps(pre), r"[0-9a-f]{64}")
        st, done = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual(st, 200, done)
        f = done["flow"]
        self.assertEqual(f["acceptance"]["state"], "valid")
        ev = f["events"][-1]
        self.assertEqual((ev["kind"], ev["source"], ev["label"], ev["source_label"]),
                         ("risk_acknowledged", "console", "接受殘餘風險", flows.CONSOLE_LABEL))
        self.assertEqual(f["acceptance"]["values"]["limits"][0]["value"], 4)
        self.assertEqual(self.call(f"/api/flows/{self.fid}")[1]["flow"]["acceptance"]["state"], "valid")
        self.assertIn(self.fid, [x["id"] for x in self.call("/api/flows")[1]["flows"]])

    def test_errors_carry_a_status_a_message_and_a_code(self):
        st, r = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": "0" * 32})
        self.assertEqual((st, r["code"]), (404, "not_found"))
        self.assertIn("error", r)
        st, r = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": "0" * 32, "limits": {}})
        self.assertEqual((st, r["code"]), (400, "bad_request"))
        st, r = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {"limits": {"max_reviews": 99}})
        self.assertEqual((st, r["code"]), (400, "bad_limits"))
        st, r = self.call("/api/flows/flow-ffffffffffff/acceptance-preview", "POST", {})
        self.assertEqual((st, r["code"]), (404, "no_flow"))
        pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {})[1]
        self.assertEqual(self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})[0], 200)
        st, r = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual((st, r["code"]), (409, "consumed"))

    def test_a_missing_login_tells_the_screen_what_to_run(self):
        os.unlink(self.state / "codex-home" / "auth.json")
        st, r = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {})
        self.assertEqual((st, r["code"]), (409, "needs_login"))
        self.assertTrue(r["login_command"].startswith(f"CODEX_HOME={self.state / 'codex-home'} "))
        self.assertTrue(r["login_command"].endswith("login -c cli_auth_credentials_store=file"))
        self.assertEqual(r["codex_home"], str(self.state / "codex-home"))

    def test_a_change_between_preview_and_confirm_is_a_409_and_nothing_is_recorded(self):
        pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {})[1]
        (self.state / "codex-home" / "auth.json").write_text(json.dumps(
            {"auth_mode": "chatgpt", "tokens": {"account_id": "acct-OTHER"}}))
        st, r = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual((st, r["code"]), (409, "conflict"))
        self.assertIn("login_fingerprint", r["error"])
        self.assertEqual(self.call(f"/api/flows/{self.fid}")[1]["flow"]["acceptance"]["state"], "none")

    def test_the_manual_events_route_cannot_write_an_acceptance(self):
        st, r = self.call(f"/api/flows/{self.fid}/events", "POST", {"kind": "risk_acknowledged"})
        self.assertEqual(st, 400)
        fields = acc.DEFAULT_LIMITS
        st, r = self.call(f"/api/flows/{self.fid}/events", "POST",
                          {"kind": "note", "text_version": acc.RISK_TEXT_VERSION, "limits": fields})
        self.assertEqual(st, 400)
        self.assertEqual(self.call(f"/api/flows/{self.fid}")[1]["flow"]["acceptance"]["state"], "none")

    def test_token_and_the_write_header_are_required(self):
        for path in (f"/api/flows/{self.fid}/acceptance-preview", f"/api/flows/{self.fid}/acceptance"):
            self.assertEqual(self.call(path, "POST", {}, token=False)[0], 401)
            self.assertEqual(self.call(path, "POST", {}, write_header=False)[0], 403)

    def test_the_preview_is_a_file_under_the_state_directory(self):
        pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {})[1]
        path = self.state / "previews" / f"{pre['preview_id']}.json"
        self.assertTrue(path.is_file())
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(json.loads(path.read_text())["kind"], "acceptance")


if __name__ == "__main__":
    unittest.main()
