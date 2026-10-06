"""Phase R2 S3: runtime_kind switch, daemon autostart, native session API.

Synthetic programs only (user decision §9.3). The Herdr runtime has been removed;
a config written while it existed is migrated to native once.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from vbear import config as cfg
from vbear import runtime as rt
from vbear.runtime import daemon as d

PY = sys.executable
ECHO = [PY, "-c", "import sys\nfor l in sys.stdin: print('ECHO:'+l.strip(),flush=True)"]


class FactoryTests(unittest.TestCase):
    def test_default_is_native_and_config_default(self):
        self.assertIsInstance(rt.get_runtime(), rt.NativeRuntime)
        self.assertEqual(cfg.DEFAULT_CONFIG["runtime_kind"], "native")
        self.assertNotIn("herdr_bin", cfg.DEFAULT_CONFIG)

    def test_native_kind(self):
        r = rt.get_runtime(kind="native", base=Path("/tmp/sidr2-nowhere"))
        self.assertIsInstance(r, rt.NativeRuntime)
        self.assertFalse(r.autostart)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(rt.NotSupported):
            rt.get_runtime(kind="native-2026")


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sidr2-", dir="/tmp"))
        self.base = self.tmp / "st"

    def tearDown(self):
        try:
            d.rpc("shutdown", base=self.base, force=True, timeout=10)
        except OSError:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_autostart_means_no_spawn(self):
        r = rt.NativeRuntime(self.base)
        self.assertFalse(r.is_available())
        self.assertFalse(d.socket_path(self.base).exists())

    def test_autostart_spawns_detached_daemon(self):
        r = rt.NativeRuntime(self.base, autostart=True)
        self.assertTrue(r.is_available())
        proc = r._spawned[0]
        pid = d.rpc("hello", base=self.base)["result"]["pid"]
        self.assertEqual(pid, proc.pid)
        self.assertEqual(os.getpgid(pid), pid)  # own session: survives the server
        info = r.create_session({"argv": ["/bin/sh", "-c", "exec sleep 100"], "cwd": str(self.tmp)})
        self.assertRegex(info["session_id"], r"^n-[0-9a-f]{12}$")
        r.close_all()  # server exit: attachments only
        self.assertEqual(len(d.rpc("list", base=self.base)["result"]["sessions"]), 1)
        self.assertTrue(d.rpc("shutdown", base=self.base, force=True, timeout=10)["ok"])
        self.assertEqual(proc.wait(10), 0)
        self.assertTrue((self.base / "runtimed.log").exists())
        self.assertEqual(os.stat(self.base / "runtimed.log").st_mode & 0o777, 0o600)


class ServerCase(unittest.TestCase):
    kind = "native"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sidr2-", dir="/tmp"))
        self.home = self.tmp / "st"
        self.home.mkdir(mode=0o700)
        self.env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        self.env.start()
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for s in conf["sources"]:
            s["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False, runtime_kind=self.kind)
        cfg.save(conf)
        self.dm = None
        if self.kind == "native":
            self.dm = d.Daemon(self.home, log=lambda m: None)
            self.dm.start()
            self.dthread = threading.Thread(target=self.dm.serve_forever, daemon=True)
            self.dthread.start()
        from vbear import server
        self.server = server
        import socket as so
        with so.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.console = server.Console(self.port)
        if isinstance(self.console.runtime, rt.NativeRuntime):
            self.console.runtime.autostart = False  # tests run their own in-thread daemon
        # make_handler reads console.port for the Host allow-list, so build it after.
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.console))
        self.hthread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.hthread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.console.runtime.close_all()
        if self.dm is not None:
            self.dm.stop()
            self.dthread.join(5)
            self.dm.close()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, timeout=15):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        h = {"Host": f"127.0.0.1:{self.port}", "X-VBear": "1"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.status, json.loads(r.read() or b"null")
        c.close()
        return out


class NativeServerTests(ServerCase):
    def stream(self, sid, want: str, timeout=8.0):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        c.request("GET", f"/api/term/{sid}/stream?cols=80&rows=24",
                  headers={"Host": f"127.0.0.1:{self.port}", "X-VBear": "1"})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        acc, end = "", time.monotonic() + timeout
        while time.monotonic() < end and want not in acc:
            line = r.fp.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                m = json.loads(line[6:])
                if m.get("type") == "terminal.frame":
                    acc += base64.b64decode(m["bytes"]).decode("utf-8", "replace")
        c.close()
        return acc

    def test_config_reports_active_kind(self):
        st, body = self.req("GET", "/api/config")
        self.assertEqual(st, 200)
        self.assertEqual(body["runtime_kind_active"], "native")
        self.assertIsInstance(self.console.runtime, rt.NativeRuntime)
        self.assertIs(self.console.store.runtime, self.console.runtime)

    def test_open_stream_takeover_input_close(self):
        st, body = self.req("POST", "/api/native/sessions",
                            {"argv": ECHO, "cwd": str(Path.home())})
        self.assertEqual(st, 200, body)
        sid = body["session"]["session_id"]
        results = {}
        t = threading.Thread(target=lambda: results.setdefault("out", self.stream(sid, "ECHO:ping")))
        t.start()
        self.wait(lambda: self.console.runtime.get(sid) is not None)
        st, body = self.req("POST", f"/api/term/{sid}/control", {"action": "takeover"})
        self.assertEqual((st, body["mode"]), (200, "control"))
        st, _ = self.req("POST", f"/api/term/{sid}/input", {"text": "ping\n"})
        self.assertEqual(st, 200)
        t.join(10)
        self.assertIn("ECHO:ping", results.get("out", ""))
        st, body = self.req("POST", f"/api/native/sessions/{sid}/close")
        self.assertEqual((st, body["closed"]), (200, sid))
        self.assertEqual(self.req("POST", f"/api/native/sessions/{sid}/close")[0], 404)

    def wait(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            time.sleep(0.02)
        self.fail("timeout")

    def test_open_validation(self):
        cases = [
            {"argv": "sh"}, {"argv": []}, {"argv": [""]},
            {"argv": ["/bin/sh"], "cwd": "relative"},
            {"argv": ["/bin/sh"], "cwd": "/"},            # outside home
            {"argv": ["/bin/sh"], "cwd": str(Path.home() / "sid-no-such-dir-xyz")},
            {"argv": ["sid-no-such-cmd-xyz"], "cwd": str(Path.home())},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.req("POST", "/api/native/sessions", body)[0], 400)
        self.assertEqual(self.req("POST", "/api/native/sessions/bad/close")[0], 400)

    def test_write_guard(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/native/sessions", body=b"{}",
                  headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(c.getresponse().status, 403)
        c.close()

    def test_daemon_down_message_is_native(self):
        self.dm.stop(); self.dthread.join(5); self.dm.close(); self.dm = None
        self.assertIn("VBear runtime", self.console.runtime_unavailable_message())
        st, body = self.req("POST", "/api/native/sessions", {"argv": ["/bin/sh"]})
        self.assertEqual(st, 503)

    def test_runtime_kind_is_no_longer_writable(self):
        st, body = self.req("POST", "/api/config", {"runtime_kind": "herdr"})
        self.assertEqual(st, 200)
        self.assertEqual(body["config"]["runtime_kind"], "native")
        self.assertNotIn("restart_needed", body)

    def test_focus_endpoint_is_gone(self):
        st, _ = self.req("POST", "/api/focus", {"target": "n-0123456789ab"})
        self.assertNotEqual(st, 200)


class HerdrConfigMigrationTests(ServerCase):
    """A state directory whose config still says runtime_kind=herdr."""
    kind = "herdr"

    def setUp(self):
        super().setUp()
        raw = json.loads(cfg.config_path().read_text())
        # The setUp above already loaded (and migrated) it once; re-create the old shape.
        raw.update(runtime_kind="herdr", herdr_bin="/opt/herdr")
        raw.pop("herdr_migrated_at", None)
        cfg.config_path().write_text(json.dumps(raw))

    def test_old_herdr_config_is_migrated_once_and_persisted(self):
        conf = cfg.load()
        self.assertEqual(conf["runtime_kind"], "native")
        self.assertNotIn("herdr_bin", conf)
        stamp = conf["herdr_migrated_at"]
        on_disk = json.loads(cfg.config_path().read_text())
        self.assertEqual(on_disk["runtime_kind"], "native")
        self.assertNotIn("herdr_bin", on_disk)
        self.assertEqual(cfg.load()["herdr_migrated_at"], stamp)   # not re-stamped

    def test_console_runs_native_and_the_notice_can_be_acknowledged(self):
        self.assertIsInstance(self.console.runtime, rt.NativeRuntime)
        cfg.load()
        st, body = self.req("POST", "/api/config", {"herdr_migration_acknowledged": True})
        self.assertEqual(st, 200)
        self.assertIs(body["config"]["herdr_migration_acknowledged"], True)
        self.assertIn("herdr_migrated_at", body["config"])


if __name__ == "__main__":
    unittest.main()
