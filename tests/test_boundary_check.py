"""PTY probe cleanup ordering; no model or real runtime is started."""
import os
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vbear import boundary_check as b
from vbear.runtime import proctrack


class ProbeCleanupTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, HOME=tmp, VBEAR_HOME=tmp,
                                          VBEAR_RUNTIME_AUTOSTART="0"))

    def run_probe(self, rows, *, lost=False, permission=False):
        events = []
        clock = iter(n * 0.5 for n in range(100))
        info = SimpleNamespace(si_pid=43210, si_code=os.CLD_EXITED, si_status=7)
        def kill(pgid, sig):
            events.append(("kill", sig))
            if permission:
                raise PermissionError()
        def waitid(*args):
            self.assertEqual(args[-1], os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if lost:
                raise ChildProcessError()
            return info
        with mock.patch.object(b.pty, "fork", return_value=(43210, 42)), \
             mock.patch.object(b.select, "select", return_value=([42], [], [])), \
             mock.patch.object(b.os, "read", return_value=b""), \
             mock.patch.object(b.os, "close"), \
             mock.patch.object(b.os, "getpgid", return_value=43210), \
             mock.patch.object(b.os, "waitid", side_effect=waitid), \
             mock.patch.object(b.os, "waitpid", side_effect=lambda *a: events.append(("reap", 0)) or (43210, 0)), \
             mock.patch.object(b.os, "killpg", side_effect=kill), \
             mock.patch.object(proctrack, "process_table", side_effect=rows), \
             mock.patch.object(b.time, "monotonic", side_effect=lambda: next(clock)), \
             mock.patch.object(b.time, "sleep"), mock.patch.object(b.sys, "stderr") as err:
            b.run_interactive(["unused"], {}, "/unused", Path("/unused/result"))
        return events, err

    def test_exited_leader_live_child_signals_before_reap(self):
        live = [{"pgid": 43210, "stat": "R"}]
        events, _ = self.run_probe([live, live, live, []])
        self.assertEqual(events, [("kill", signal.SIGHUP), ("kill", signal.SIGTERM), ("reap", 0)])

    def test_zombie_only_eperm_reaps_without_later_signal(self):
        events, _ = self.run_probe([[{"pgid": 43210, "stat": "Z"}]], permission=True)
        self.assertEqual(events, [("kill", signal.SIGHUP), ("reap", 0)])

    def test_lost_child_never_signalled(self):
        events, err = self.run_probe([], lost=True)
        self.assertEqual(events, [])
        self.assertTrue(err.write.called)

    def test_unavailable_table_keeps_leader(self):
        events, err = self.run_probe(proctrack.ProcessTableUnavailable("synthetic"))
        self.assertEqual(events, [("kill", signal.SIGHUP), ("kill", signal.SIGTERM),
                                  ("kill", signal.SIGKILL)])
        self.assertTrue(err.write.called)
