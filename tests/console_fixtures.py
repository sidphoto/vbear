"""The console's HTTP surface in front of a real runtime daemon (S2c tests):
a mixin for the daemon test cases of test_runtimed_stream / test_runtimed_review."""

import json
import os
import threading
import urllib.error
import urllib.request
from unittest import mock

from tests.test_risk_acceptance import FakeHost
from vbear import config as cfg
from vbear import risk_acceptance as ra
from vbear import tasks


class ConsoleMixin:
    """Mix in before a StreamCase (or ReviewCase): after its setUp, a console
    server on a free port whose runtime is that case's daemon, a fake host
    that agrees with its acceptance, and the helper the tests call with."""

    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        from vbear.server import Console, make_handler
        tasks.save_task(self.tid, {"title": "t", "workdir": str(self.work)})
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for src in conf["sources"]:
            src["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        env = mock.patch.dict(os.environ, {"VBEAR_RUNTIME_AUTOSTART": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.console = Console(self.port)
        self.console.executor.managed_root = self.tmp
        self.token = self.console.auth_token
        self.httpd.RequestHandlerClass = make_handler(self.console)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self._stop_http)
        self.host = FakeHost(self.tmp)
        self.host.binary = str(self.binary)
        self.host.claude_binary = lambda cwd=None: (self.host.binary, self.host.claude, "")
        self.host.claude_json = lambda: self.home / ".claude.json"                # the account the acceptance bound
        # a logged-in dedicated Codex home, and an acceptance that binds to it, so that the facts the
        # screen compares (status) are the ones that were accepted
        codex_home = self.base / "codex-home"
        codex_home.mkdir(mode=0o700, exist_ok=True)
        (codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": "acct-0001"}}))
        os.chmod(codex_home / "auth.json", 0o600)
        self.accept()
        ra._facts_cache.clear()
        p = mock.patch.object(ra, "DEFAULT_HOST", self.host)
        p.start()
        self.addCleanup(p.stop)

    def _stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, path, method="GET", body=None, token=True):
        h = {"X-VBear": "1", "Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {self.token}"
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"null")
            e.close()
            return e.code, data
