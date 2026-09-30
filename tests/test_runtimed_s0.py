"""Phase R2 S0: runtime daemon skeleton (contract v2 §3, §10 S0).

Paths live under /tmp (not the per-user TMPDIR) because macOS limits
sockaddr_un.sun_path to 104 bytes.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from sidconsole.runtime import daemon as d

ROOT = Path(__file__).resolve().parent.parent


class DaemonCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sidr2-", dir="/tmp"))
        self.base = self.tmp / "st"
        self.daemons: list[tuple[d.Daemon, threading.Thread]] = []

    def tearDown(self):
        for dm, t in self.daemons:
            dm.stop()
            t.join(3)
            dm.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_daemon(self, **kw) -> d.Daemon:
        dm = d.Daemon(self.base, log=lambda m: None, **kw)
        dm.start()
        t = threading.Thread(target=dm.serve_forever, daemon=True)
        t.start()
        self.daemons.append((dm, t))
        return dm

    def raw(self, payload: bytes, timeout=2.0) -> bytes:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(d.socket_path(self.base)))
            s.sendall(payload)
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    return buf
                buf += chunk


class StartupSecurityTests(DaemonCase):
    def test_modes_dir_0700_socket_0600(self):
        self.run_daemon()
        self.assertEqual(stat.S_IMODE(os.lstat(self.base).st_mode), 0o700)
        st = os.lstat(d.socket_path(self.base))
        self.assertTrue(stat.S_ISSOCK(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(d.lock_path(self.base)).st_mode), 0o600)

    def test_umask_restored_after_start(self):
        before = os.umask(0o022)
        try:
            self.run_daemon()
            self.assertEqual(os.umask(0o022), 0o022)
        finally:
            os.umask(before)

    def test_second_daemon_refused_and_first_untouched(self):
        self.run_daemon()
        ino = os.lstat(d.socket_path(self.base)).st_ino
        second = d.Daemon(self.base, log=lambda m: None)
        with self.assertRaises(d.AlreadyRunning):
            second.start()
        self.assertEqual(os.lstat(d.socket_path(self.base)).st_ino, ino)
        self.assertTrue(d.rpc("hello", base=self.base)["ok"])

    def test_stale_socket_is_recovered(self):
        os.makedirs(self.base, mode=0o700)
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(d.socket_path(self.base)))
        stale.close()  # file left behind, nobody listening (crash / kill -9)
        self.run_daemon()
        self.assertTrue(d.rpc("hello", base=self.base)["ok"])

    def test_symlink_socket_path_refused(self):
        os.makedirs(self.base, mode=0o700)
        target = self.tmp / "elsewhere"
        target.write_text("x")
        os.symlink(target, d.socket_path(self.base))
        with self.assertRaises(d.UnsafePath):
            d.Daemon(self.base, log=lambda m: None).start()
        self.assertTrue(target.exists())
        self.assertTrue(os.path.islink(d.socket_path(self.base)))

    def test_regular_file_socket_path_refused(self):
        os.makedirs(self.base, mode=0o700)
        d.socket_path(self.base).write_text("keep me")
        with self.assertRaises(d.UnsafePath):
            d.Daemon(self.base, log=lambda m: None).start()
        self.assertEqual(d.socket_path(self.base).read_text(), "keep me")

    def test_refused_start_releases_lock(self):
        os.makedirs(self.base, mode=0o700)
        d.socket_path(self.base).write_text("x")
        with self.assertRaises(d.UnsafePath):
            d.Daemon(self.base, log=lambda m: None).start()
        d.socket_path(self.base).unlink()
        self.run_daemon()  # lock must not be leaked by the failed start

    def test_symlink_lock_refused(self):
        os.makedirs(self.base, mode=0o700)
        target = self.tmp / "victim"
        target.write_text("original")
        os.symlink(target, d.lock_path(self.base))
        with self.assertRaises(d.UnsafePath):
            d.Daemon(self.base, log=lambda m: None).start()
        self.assertEqual(target.read_text(), "original")

    def test_loose_dir_permissions_refused(self):
        os.makedirs(self.base, mode=0o700)
        os.chmod(self.base, 0o755)
        with self.assertRaises(d.UnsafePath):
            d.Daemon(self.base, log=lambda m: None).start()

    def test_symlinked_state_dir_refused(self):
        real = self.tmp / "real"
        os.makedirs(real, mode=0o700)
        os.symlink(real, self.base)
        with self.assertRaises(d.UnsafePath):
            d.Daemon(self.base, log=lambda m: None).start()

    def test_failure_after_bind_releases_everything(self):
        dm = d.Daemon(self.base, log=lambda m: None)
        with mock.patch.object(d.selectors, "DefaultSelector", side_effect=OSError("no fds")):
            with self.assertRaises(OSError):
                dm.start()
        self.assertFalse(d.socket_path(self.base).exists())
        self.assertIsNone(dm._lock_fd)
        self.assertEqual((dm._wake_r, dm._wake_w), (-1, -1))
        self.run_daemon()  # lock released, path free

    def test_overlong_socket_path_refused(self):
        deep = self.tmp / ("x" * 120)
        with self.assertRaises(d.UnsafePath):
            d.Daemon(deep, log=lambda m: None).start()


class PeerCredentialTests(DaemonCase):
    def test_parse_xucred(self):
        raw = (0).to_bytes(4, sys.byteorder) + (501).to_bytes(4, sys.byteorder) + b"\0" * 68
        self.assertEqual(d.parse_xucred(raw), 501)
        with self.assertRaises(ValueError):
            d.parse_xucred(b"\0" * 4)
        with self.assertRaises(ValueError):
            d.parse_xucred((7).to_bytes(4, sys.byteorder) + b"\0" * 72)

    def test_real_peer_uid_is_ours(self):
        self.run_daemon()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.connect(str(d.socket_path(self.base)))
            # our own client end: peer is the daemon (same process/uid)
            self.assertEqual(d.peer_uid(c), os.getuid())

    def test_uid_mismatch_rejected(self):
        self.run_daemon(expected_uid=os.getuid() + 1)
        with self.assertRaises((ConnectionError, OSError)):
            d.rpc("hello", base=self.base)

    def test_credential_failure_fails_closed(self):
        self.run_daemon()
        with mock.patch.object(d, "peer_uid", side_effect=OSError("boom")):
            with self.assertRaises((ConnectionError, OSError)):
                d.rpc("hello", base=self.base)
        self.assertTrue(d.rpc("hello", base=self.base)["ok"])


class RpcTests(DaemonCase):
    def setUp(self):
        super().setUp()
        self.run_daemon()

    def resp(self, obj) -> dict:
        return json.loads(self.raw(json.dumps(obj).encode() + b"\n"))

    def test_hello(self):
        r = d.rpc("hello", base=self.base, request_id="abc")
        self.assertEqual(r["id"], "abc")
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"]["protocol"], 1)
        self.assertEqual(r["result"]["pid"], os.getpid())

    def test_one_request_per_connection(self):
        out = self.raw(b'{"v":1,"id":"a","op":"hello"}\n{"v":1,"id":"b","op":"hello"}\n')
        lines = [l for l in out.split(b"\n") if l]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["id"], "a")

    def test_bad_requests(self):
        cases = [
            (b"not json\n", None),
            (b"[1,2]\n", None),
            (json.dumps({"v": 1, "op": "hello"}).encode() + b"\n", None),
            (json.dumps({"v": 2, "id": "x", "op": "hello"}).encode() + b"\n", "x"),
            (json.dumps({"v": 1, "id": "x", "op": "nope"}).encode() + b"\n", "x"),
            (json.dumps({"v": 1, "id": "x", "op": "hello", "extra": 1}).encode() + b"\n", "x"),
            (json.dumps({"v": 1, "id": "x", "op": "shutdown", "force": "yes"}).encode() + b"\n", "x"),
        ]
        for payload, rid in cases:
            with self.subTest(payload=payload):
                r = json.loads(self.raw(payload))
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "bad_request")
                self.assertEqual(r["id"], rid)
        self.assertTrue(d.rpc("hello", base=self.base)["ok"])  # daemon survived

    def test_oversized_request_rejected(self):
        r = json.loads(self.raw(b"a" * (d.MAX_LINE + 10)))
        self.assertEqual(r["error"]["code"], "bad_request")

    def test_idle_connection_dropped(self):
        dm = self.daemons[0][0]
        dm.idle_timeout = 0.3
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(str(d.socket_path(self.base)))
            s.sendall(b'{"v":1')  # never finishes the line
            self.assertEqual(s.recv(10), b"")
        self.assertTrue(d.rpc("hello", base=self.base)["ok"])

    def test_shutdown_removes_socket(self):
        dm, t = self.daemons[0]
        self.assertTrue(d.rpc("shutdown", base=self.base)["ok"])
        t.join(3)
        self.assertFalse(t.is_alive())
        dm.close()
        self.assertFalse(d.socket_path(self.base).exists())
        self.run_daemon()  # lock released: a new daemon can start


class CliProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sidr2-", dir="/tmp"))
        self.env = {**os.environ, "SID_CONSOLE_HOME": str(self.tmp / "st")}
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(3)
            if p.stderr:
                p.stderr.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spawn(self):
        p = subprocess.Popen([sys.executable, "-m", "sidconsole", "runtimed"], cwd=ROOT,
                             env=self.env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.procs.append(p)
        return p

    def wait_hello(self):
        for _ in range(60):
            try:
                return d.rpc("hello", base=self.tmp / "st", timeout=0.5)
            except OSError:
                time.sleep(0.1)
        self.fail("runtimed never answered hello")

    def test_cli_lifecycle(self):
        first = self.spawn()
        r = self.wait_hello()
        self.assertEqual(r["result"]["pid"], first.pid)
        second = self.spawn()
        self.assertEqual(second.wait(10), 3)
        self.assertEqual(first.poll(), None)
        d.rpc("shutdown", base=self.tmp / "st")
        self.assertEqual(first.wait(10), 0)
        self.assertFalse((self.tmp / "st" / d.SOCKET_NAME).exists())

    def test_sigterm_cleans_up(self):
        p = self.spawn()
        self.wait_hello()
        p.terminate()
        self.assertEqual(p.wait(10), 0)
        self.assertFalse((self.tmp / "st" / d.SOCKET_NAME).exists())

    def test_kill9_then_restart_recovers(self):
        p = self.spawn()
        self.wait_hello()
        p.kill()
        p.wait(5)
        self.assertTrue((self.tmp / "st" / d.SOCKET_NAME).exists())  # stale left behind
        p2 = self.spawn()
        self.assertEqual(self.wait_hello()["result"]["pid"], p2.pid)
        d.rpc("shutdown", base=self.tmp / "st")
        self.assertEqual(p2.wait(10), 0)


if __name__ == "__main__":
    unittest.main()
