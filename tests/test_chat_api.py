"""The chat endpoints (P36-2) over a real loopback server. The config rules first (no daemon needed); the chats
themselves run through a real runtime daemon with the fake Claude Code of tests/fake_chat_cli.py, further down."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from vbear import config as cfg, server
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


if __name__ == "__main__":
    unittest.main()
