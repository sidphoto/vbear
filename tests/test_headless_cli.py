"""The shared runner of one headless CLI call (translations and meetings). No real CLI: owned synthetic scripts only."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import config as cfg, headless_cli as hc

SCRIPT = '''#!{python}
import os, sys, time
from pathlib import Path
prompt = sys.stdin.read()
{body}
'''


class HeadlessCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-headless-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        home = self.root / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"),
                                             "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)

    def script(self, body):
        path = self.root / "fake-cli"
        path.write_text(SCRIPT.format(python=sys.executable, body=body))
        path.chmod(0o700)
        return lambda tmp: [str(path)]

    def run_cli(self, body, **kw):
        kw.setdefault("timeout", 5)
        kw.setdefault("max_output", 4096)
        kw.setdefault("blocked_name", "headless-test.blocked")
        return hc.run(self.script(body), kw.pop("prompt", b"hello"), kw.pop("cancel", threading.Event()), **kw)

    def test_it_returns_the_output_and_the_exit_code_from_an_empty_directory(self):
        result = self.run_cli("assert not list(Path.cwd().iterdir())\n"
                              "assert set(os.environ) <= {'PATH','HOME','USER','LOGNAME','LANG','TMPDIR','LC_CTYPE','__CF_USER_TEXT_ENCODING'}\n"
                              "print('got:' + prompt)")
        self.assertEqual(result.output, b"got:hello\n")
        self.assertEqual(result.returncode, 0)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_a_nonzero_exit_is_cli_failed_and_keeps_the_code(self):
        with self.assertRaises(hc.HeadlessError) as cm:
            self.run_cli("sys.stderr.write('PRIVATE_ACCOUNT_INFO')\nsys.exit(7)")
        self.assertEqual((cm.exception.code, cm.exception.returncode), ("cli_failed", 7))
        self.assertNotIn("PRIVATE_ACCOUNT_INFO", str(cm.exception))

    def test_output_over_the_limit_is_invalid_output(self):
        with self.assertRaises(hc.HeadlessError) as cm:
            self.run_cli("print('x' * 9000)", max_output=4096)
        self.assertEqual(cm.exception.code, "invalid_output")

    def test_timeout_and_cancel_end_the_whole_process_group(self):
        marker = self.root / "grandchild-pid"
        body = ("import subprocess\n"
                f"p = subprocess.Popen(['sleep', '30']); Path({str(marker)!r}).write_text(str(p.pid))\n"
                "time.sleep(30)")
        for cancel in (False, True):
            event = threading.Event()
            if cancel:
                event.set()
            with self.subTest(cancel=cancel), self.assertRaises(hc.HeadlessError) as cm:
                self.run_cli(body, cancel=event, timeout=0.3)
            self.assertEqual(cm.exception.code, "cancelled" if cancel else "timeout")
            if marker.exists():
                with self.assertRaises(ProcessLookupError):
                    for _ in range(100):
                        os.kill(int(marker.read_text()), 0)
                        time.sleep(0.02)
                marker.unlink()

    def test_on_line_sees_each_complete_line_and_can_stop_the_call_at_once(self):
        seen = []
        result = self.run_cli("print('a'); print('b'); sys.stdout.write('c')", on_line=seen.append)
        self.assertEqual(seen, [b"a", b"b"])  # the unfinished last line is not a line yet
        self.assertEqual(result.output, b"a\nb\nc")

        def stop(line):
            if line == b"bad":
                raise hc.HeadlessError("tools_not_clean")
        started = time.monotonic()
        with self.assertRaises(hc.HeadlessError) as cm:
            self.run_cli("print('ok', flush=True); print('bad', flush=True); time.sleep(20)", on_line=stop, timeout=15)
        self.assertEqual(cm.exception.code, "tools_not_clean")
        self.assertLess(time.monotonic() - started, 10)

    def test_an_unconfirmed_group_writes_its_own_blocked_marker_only(self):
        with mock.patch.object(hc, "group_exists", return_value=True), \
             mock.patch.object(hc.time, "sleep"), self.assertRaises(hc.HeadlessError) as cm:
            self.run_cli("print('x')", blocked_name="meeting-worker.blocked")
        self.assertEqual(cm.exception.code, "process_unconfirmed")
        self.assertTrue((cfg.state_dir() / "meeting-worker.blocked").exists())
        self.assertFalse((cfg.state_dir() / "translation-worker.blocked").exists())

    def test_the_worker_lock_is_per_name_exclusive_and_stops_at_a_blocked_marker(self):
        fd = hc.acquire_worker("meeting-worker")
        try:
            with self.assertRaises(hc.HeadlessError) as cm:
                hc.acquire_worker("meeting-worker")
            self.assertEqual(cm.exception.code, "busy")
            other = hc.acquire_worker("translation-worker")  # another worker is not in its way
            os.close(other)
        finally:
            os.close(fd)
        cfg.write_private(cfg.state_dir() / "meeting-worker.blocked", "process_unconfirmed\n")
        with self.assertRaises(hc.HeadlessError) as cm:
            hc.acquire_worker("meeting-worker")
        self.assertEqual(cm.exception.code, "process_unconfirmed")


if __name__ == "__main__":
    unittest.main()
