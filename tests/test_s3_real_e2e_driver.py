"""tools/s3_real_e2e.py: the driver's own cleanup checks (not its scenarios). No model, no console, no daemon: the
state directory is a temporary one and the commands are replaced."""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOL = Path(__file__).resolve().parent.parent / "tools" / "s3_real_e2e.py"


def load():
    spec = importlib.util.spec_from_file_location("s3_real_e2e_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CleanupCheckTests(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbs3-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(self.m, "STATE", self.tmp / "vbear-home")
        p.start()
        self.addCleanup(p.stop)
        (self.tmp / "vbear-home").mkdir()

    def lock(self, text):
        (self.tmp / "vbear-home" / "runtimed.lock").write_text(text)

    def test_the_lock_file(self):
        self.assertEqual(self.m.daemon_pids(), [])                       # no file: no daemon started
        self.lock(f"{os.getpid()}\n")
        self.assertEqual(self.m.daemon_pids(), [os.getpid()])
        self.lock("999999999\n")                                         # a pid that is gone
        self.assertEqual(self.m.daemon_pids(), [])
        for bad in ("", "garbage", "12 34", "-5", "1" * 20, "12\nextra"):
            with self.subTest(content=bad):
                self.lock(bad)
                with self.assertRaises(self.m.CommandFailed):            # never "no daemon"
                    self.m.daemon_pids()
        p = self.tmp / "vbear-home" / "runtimed.lock"
        p.unlink()
        p.mkdir()                                                        # unreadable as a file
        with self.assertRaises(self.m.CommandFailed):
            self.m.daemon_pids()

    def test_a_hello_that_fails_in_any_other_way_is_an_error(self):
        for exc in (PermissionError(13, "denied"), TimeoutError("slow"), OSError(5, "io")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(self.m, "daemon_rpc", side_effect=exc):
                    with self.assertRaises(self.m.CommandFailed):
                        self.m.shutdown_daemon()

    def test_not_running_needs_no_process_holding_the_state_directory(self):
        for exc in (FileNotFoundError(2, "no socket"), ConnectionRefusedError(61, "refused")):
            with mock.patch.object(self.m, "daemon_rpc", side_effect=exc):
                with mock.patch.object(self.m, "processes_with_state", return_value={}):
                    self.assertEqual(self.m.shutdown_daemon()["still_alive"], [])
                with mock.patch.object(self.m, "processes_with_state", return_value={4242: "python -m vbear runtimed"}):
                    self.assertEqual(self.m.shutdown_daemon()["still_alive"], [4242])      # unreachable but alive

    def test_a_failed_ps_is_an_error_not_an_empty_list(self):
        with mock.patch.object(self.m, "run_cmd", return_value=(1, "", "ps: boom")):
            with self.assertRaises(self.m.CommandFailed):
                self.m.processes_with_state()
        with mock.patch.object(self.m, "run_cmd", side_effect=self.m.CommandFailed("ps: TimeoutExpired")):
            with self.assertRaises(self.m.CommandFailed):
                self.m.processes_with_state()

    def test_ps_lists_the_processes_that_name_the_state_directory_but_not_the_driver(self):
        state = str(self.tmp / "vbear-home")
        out = (f"  100 python3 -m vbear runtimed VBEAR_HOME={state} HOME=/x\n"
               f"  101 /bin/other something else\n"
               f"  {os.getpid()} python3 tools/s3_real_e2e.py VBEAR_HOME={state}\n")
        with mock.patch.object(self.m, "run_cmd", return_value=(0, out, "")):
            self.assertEqual(list(self.m.processes_with_state()), [100])

    def test_lsof_exit_one_is_nothing_only_when_silent(self):
        with mock.patch.object(self.m, "run_cmd", return_value=(1, "", "")):
            self.assertEqual(self.m.lsof("-p", "1"), "")
        with mock.patch.object(self.m, "run_cmd", return_value=(1, "", "lsof: WARNING")):
            with self.assertRaises(self.m.CommandFailed):
                self.m.lsof("-p", "1")
        with mock.patch.object(self.m, "run_cmd", return_value=(2, "", "")):
            with self.assertRaises(self.m.CommandFailed):
                self.m.lsof("-p", "1")


if __name__ == "__main__":
    unittest.main()
