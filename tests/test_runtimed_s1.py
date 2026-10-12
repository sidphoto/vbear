"""Phase R2 S1: PTY sessions in the runtime daemon (contract v2 §4, §6, §10 S1).

Only synthetic programs are started (/bin/sh, python -c): no Claude or Codex
(user decision §9.3).
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear.runtime import daemon as d

PY = sys.executable
CLOSE_TIMEOUT = 10.0


def gone(pid: int) -> bool:
    """True when pid is neither running nor a zombie."""
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return r.returncode != 0 or not r.stdout.strip()


class SessionCase(unittest.TestCase):
    def setUp(self):
        # A host that ignores SIGHUP (some IDEs, agent runners, CI) passes
        # SIG_IGN on to the shells these tests start, so the daemon's SIGHUP
        # would not end them (Gemini review of ae56eb7). Default it here.
        previous = signal.signal(signal.SIGHUP, signal.SIG_DFL)
        self.addCleanup(signal.signal, signal.SIGHUP, previous)
        self.tmp = Path(tempfile.mkdtemp(prefix="sidr2-", dir="/tmp"))
        self.base = self.tmp / "st"
        self.dm = d.Daemon(self.base, log=lambda m: None)
        self.dm.start()
        self.thread = threading.Thread(target=self.dm.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rpc(self, op, **kw):
        return d.rpc(op, base=self.base, timeout=CLOSE_TIMEOUT, **kw)

    def open(self, argv, **kw) -> str:
        r = self.rpc("open", argv=argv, cwd=str(self.tmp), **kw)
        self.assertTrue(r["ok"], r)
        return r["result"]["session_id"]

    def output(self, sid) -> bytes:
        s = self.dm._sessions.get(sid)
        return bytes(s.scrollback) if s else b""

    def info(self, sid):
        for s in self.rpc("list")["result"]["sessions"]:
            if s["session_id"] == sid:
                return s
        return None

    def wait_for(self, pred, timeout=5.0, msg="condition"):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            time.sleep(0.02)
        self.fail(f"timed out waiting for {msg}")

    def wait_out(self, sid, needle: bytes, timeout=5.0):
        self.wait_for(lambda: needle in self.output(sid), timeout, f"{needle!r}")


class LifecycleTests(SessionCase):
    def test_open_list_close_roundtrip(self):
        # The point is that close sends SIGHUP first and the session ends on it.
        # Under heavy load the shell can take longer than the 1 s HUP_GRACE to
        # exit, and the daemon then escalates to SIGTERM (seen in CI); give the
        # SIGHUP step room here. CLOSE_WAIT (the reply deadline) stays longer.
        hup = mock.patch.object(d, "HUP_GRACE", 5.0)
        hup.start()
        self.addCleanup(hup.stop)
        self.assertLess(d.HUP_GRACE, d.CLOSE_WAIT)
        sid = self.open(["/bin/sh", "-c", "echo ready; exec sleep 100"])
        self.assertRegex(sid, r"^n-[0-9a-f]{12}$")
        self.wait_out(sid, b"ready")
        info = self.info(sid)
        self.assertFalse(info["exited"])
        self.assertEqual(info["pid"], info["pgid"])
        self.assertEqual(self.rpc("hello")["result"]["sessions"], 1)
        r = self.rpc("close", session_id=sid)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["exit_code"], -signal.SIGHUP)
        self.assertFalse(r["result"]["forced"])
        self.assertTrue(gone(info["pid"]))
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    def test_real_controlling_tty_and_size(self):
        sid = self.open(["/bin/sh", "-c", "test -t 0 && echo IS_TTY; stty size; "
                         "ps -o tty= -p $$; echo TTY_DONE; sleep 100"], cols=100, rows=30)
        # Wait for the last marker: ps forks slowly under load (flake in run 1).
        self.wait_out(sid, b"TTY_DONE", timeout=10)
        self.assertIn(b"30 100", self.output(sid))
        out = self.output(sid)
        self.assertIn(b"IS_TTY", out)
        self.assertRegex(out, rb"ttys\d+")  # the PTY is our controlling terminal
        self.rpc("close", session_id=sid)

    def test_natural_exit_is_reaped_no_zombie(self):
        sid = self.open(["/bin/sh", "-c", "echo bye; exit 7"])
        self.wait_for(lambda: (self.info(sid) or {}).get("exited"), msg="exit")
        info = self.info(sid)
        self.assertEqual(info["exit_code"], 7)
        self.wait_for(lambda: gone(info["pid"]), 2.0, "reap (no Z state)")
        self.assertIn(b"bye", self.output(sid))
        r = self.rpc("close", session_id=sid)
        self.assertEqual(r["result"]["exit_code"], 7)
        self.assertFalse(r["result"]["forced"])

    def test_grandchild_in_group_is_cleaned(self):
        sid = self.open(["/bin/sh", "-c", "sleep 100 & echo GC=$!; wait"])
        self.wait_out(sid, b"GC=")
        gc = int(re.search(rb"GC=(\d+)", self.output(sid)).group(1))
        self.assertFalse(gone(gc))
        self.assertTrue(self.rpc("close", session_id=sid)["ok"])
        self.wait_for(lambda: gone(gc), 3.0, "grandchild gone")

    def test_hup_ignored_escalates_to_term(self):
        sid = self.open([PY, "-c", "import signal,time;signal.signal(signal.SIGHUP,signal.SIG_IGN);"
                         "print('armed',flush=True);time.sleep(100)"])
        self.wait_out(sid, b"armed")
        t0 = time.monotonic()
        r = self.rpc("close", session_id=sid)["result"]
        elapsed = time.monotonic() - t0
        self.assertEqual(r["exit_code"], -signal.SIGTERM)
        self.assertFalse(r["forced"])
        self.assertGreaterEqual(elapsed, d.HUP_GRACE - 0.1)
        self.assertLess(elapsed, d.HUP_GRACE + d.TERM_GRACE)

    def test_hup_and_term_ignored_escalates_to_kill(self):
        pid_holder = {}
        sid = self.open([PY, "-c", "import signal,time\nfor s in (signal.SIGHUP,signal.SIGTERM):"
                         " signal.signal(s,signal.SIG_IGN)\nprint('armed',flush=True);time.sleep(100)"])
        self.wait_out(sid, b"armed")
        pid_holder["pid"] = self.info(sid)["pid"]
        t0 = time.monotonic()
        r = self.rpc("close", session_id=sid)["result"]
        elapsed = time.monotonic() - t0
        self.assertEqual(r["exit_code"], -signal.SIGKILL)
        self.assertTrue(r["forced"])
        self.assertGreaterEqual(elapsed, d.HUP_GRACE + d.TERM_GRACE - 0.1)
        self.assertLess(elapsed, d.HUP_GRACE + d.TERM_GRACE + d.KILL_GRACE + 1)
        self.assertTrue(gone(pid_holder["pid"]))

    def test_heavy_output_on_term_still_exits_in_term_phase(self):
        # §10 S1: the master keeps draining while we wait, so a child that
        # writes a lot while handling SIGTERM is not stuck on a full PTY.
        code = ("import signal,sys,time\n"
                "signal.signal(signal.SIGHUP,signal.SIG_IGN)\n"
                "def h(*a):\n sys.stdout.buffer.write(b'x'*1_000_000);sys.stdout.flush();sys.exit(0)\n"
                "signal.signal(signal.SIGTERM,h)\nprint('armed',flush=True)\ntime.sleep(100)")
        sid = self.open([PY, "-c", code])
        self.wait_out(sid, b"armed")
        r = self.rpc("close", session_id=sid)["result"]
        self.assertEqual(r["exit_code"], 0)
        self.assertFalse(r["forced"])

    def test_other_session_keeps_streaming_during_close(self):
        busy = self.open([PY, "-c", "import time\nwhile True: print('t',flush=True);time.sleep(0.01)"])
        stuck = self.open([PY, "-c", "import signal,time\nfor s in (signal.SIGHUP,signal.SIGTERM):"
                           " signal.signal(s,signal.SIG_IGN)\nprint('armed',flush=True);time.sleep(100)"])
        self.wait_out(stuck, b"armed")
        self.wait_out(busy, b"t")
        changes, done = [], threading.Event()    # when the other session's output total moved

        def sample():
            last_total = -1
            while not done.is_set():
                s = self.dm._sessions.get(busy)
                total = s.total if s else -1
                if total != last_total:
                    changes.append(time.monotonic())
                    last_total = total
                time.sleep(0.005)

        t = threading.Thread(target=sample)
        t.start()
        begin = time.monotonic()
        self.rpc("close", session_id=stuck)  # ~3s through HUP -> TERM -> KILL
        end = time.monotonic()
        done.set()
        t.join()
        window = end - begin
        # How often the other session's output moves is up to that program's own timer, which a CI virtual machine
        # stretches (a count of 48 or 49 changes in a 3 s close was seen there, 250 on a laptop), so the count is
        # not the test. What a close that blocked the daemon loop would do is stall the other session for at least a
        # grace period (HUP_GRACE, 1 s): the longest time without a change over the whole close, including from its
        # start to the first change and from the last change to its end (a stall that never ends in another change
        # has no gap between two changes, only a trailing one), must stay under half of it. Half separates a
        # blocked loop from a busy machine's scheduling delay (0.27 s seen under load).
        self.assertGreaterEqual(window, d.HUP_GRACE + d.TERM_GRACE - 0.1,
                                "the close did not go through the escalation, so nothing overlapped it")
        stamps = [begin] + [c for c in changes if begin <= c <= end] + [end]
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        floor = int(window / (d.HUP_GRACE / 2))   # what "never idle for half a grace period" already implies
        self.assertGreaterEqual(
            len(stamps) - 2, floor,
            f"the other session's output moved {len(stamps) - 2} times in a {window:.1f} s close; fewer than {floor} "
            f"means it was idle for stretches (longest {max(gaps):.2f} s) while the daemon had no one else to serve")
        self.assertLess(max(gaps), d.HUP_GRACE / 2,
                        f"other session stalled during close (longest {max(gaps):.2f} s of {window:.1f} s, "
                        f"{len(stamps) - 2} changes)")
        self.rpc("close", session_id=busy)

    def test_double_close_both_answered_then_not_found(self):
        # HUP ignored -> close lasts ~1s, so both requests land while it is in progress.
        sid = self.open([PY, "-c", "import signal,time;signal.signal(signal.SIGHUP,signal.SIG_IGN);"
                         "print('armed',flush=True);time.sleep(100)"])
        self.wait_out(sid, b"armed")
        results = []
        ths = [threading.Thread(target=lambda: results.append(self.rpc("close", session_id=sid)))
               for _ in range(2)]
        for th in ths:
            th.start()
        for th in ths:
            th.join(CLOSE_TIMEOUT)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["ok"] for r in results), results)
        self.assertEqual({r["result"]["exit_code"] for r in results}, {-signal.SIGTERM})
        self.assertEqual(self.rpc("close", session_id=sid)["error"]["code"], "not_found")

    def test_client_abort_during_deferred_close(self):
        sid = self.open([PY, "-c", "import signal,time;signal.signal(signal.SIGHUP,signal.SIG_IGN);"
                         "print('armed',flush=True);time.sleep(100)"])
        self.wait_out(sid, b"armed")
        pid = self.info(sid)["pid"]
        import json, socket as so
        with so.socket(so.AF_UNIX, so.SOCK_STREAM) as s:
            s.connect(str(d.socket_path(self.base)))
            s.sendall(json.dumps({"v": 1, "id": "abort", "op": "close",
                                  "session_id": sid}).encode() + b"\n")
            time.sleep(0.1)
        # client gone mid-close: the session must still finish and the loop live on
        self.wait_for(lambda: self.info(sid) is None, 6.0, "session finalized")
        self.assertTrue(gone(pid))
        self.assertTrue(self.rpc("hello")["ok"])

    def test_close_after_natural_exit_sends_no_signal(self):
        sid = self.open(["/bin/sh", "-c", "exit 3"])
        self.wait_for(lambda: (self.info(sid) or {}).get("exited"), msg="exit")
        self.wait_for(lambda: not self.dm._sessions[sid].group_alive(), 2.0, "group empty")
        with mock.patch.object(d.Session, "signal") as sig:
            r = self.rpc("close", session_id=sid)
        self.assertEqual(r["result"]["exit_code"], 3)
        sig.assert_not_called()

    def test_spawn_failure_after_popen_leaves_no_orphan(self):
        started = []
        real_popen = d.subprocess.Popen

        def spy(*a, **kw):
            p = real_popen(*a, **kw)
            started.append(p.pid)
            return p
        real_register = self.dm._sel.register

        def register(fileobj, events, data=None):
            if isinstance(fileobj, int):  # the PTY master; client sockets pass through
                raise OSError("selector full")
            return real_register(fileobj, events, data)
        # Do not mock Session itself: serve_forever uses isinstance(data, Session).
        with mock.patch.object(d.subprocess, "Popen", side_effect=spy), \
             mock.patch.object(self.dm._sel, "register", side_effect=register):
            r = self.rpc("open", argv=["/bin/sh", "-c", "exec sleep 100"], cwd=str(self.tmp))
        self.assertEqual(r["error"]["code"], "internal")
        self.assertFalse(r.get("ok", False))
        self.assertEqual(len(started), 1)
        self.wait_for(lambda: gone(started[0]), 3.0, "orphan killed")
        self.assertEqual(self.dm._sessions, {})

    def test_scrollback_ring_is_capped(self):
        sid = self.open([PY, "-c", "import sys,time;sys.stdout.buffer.write(b'y'*3_000_000);"
                         "sys.stdout.flush();time.sleep(100)"])
        self.wait_for(lambda: (self.dm._sessions[sid].total >= 3_000_000), 20, "3MB output")
        self.assertEqual(len(self.dm._sessions[sid].scrollback), d.SCROLLBACK_MAX)
        self.rpc("close", session_id=sid)


class ValidationTests(SessionCase):
    def test_session_limit(self):
        self.dm.max_sessions = 2
        self.open(["/bin/sh", "-c", "exec sleep 100"])
        self.open(["/bin/sh", "-c", "exec sleep 100"])
        r = self.rpc("open", argv=["/bin/sh"], cwd=str(self.tmp))
        self.assertEqual(r["error"]["code"], "limit")

    def test_open_rejects_bad_input(self):
        cwd = str(self.tmp)
        cases = [
            dict(argv=[], cwd=cwd), dict(argv="sh", cwd=cwd), dict(argv=[""], cwd=cwd),
            dict(argv=[1], cwd=cwd), dict(argv=["/bin/sh"], cwd="relative"),
            dict(argv=["/bin/sh"], cwd=cwd + "/missing"), dict(argv=["/bin/sh"]),
            dict(argv=["/bin/sh"], cwd=cwd, cols=0), dict(argv=["/bin/sh"], cwd=cwd, rows=True),
            dict(argv=["/bin/sh"], cwd=cwd, env={"SECRET": "x"}),
            dict(argv=["/bin/sh"], cwd=cwd, env={"PATH": 1}),
            dict(argv=["/bin/sh"], cwd=cwd, shell=True),
        ]
        for kw in cases:
            with self.subTest(kw=kw):
                self.assertEqual(self.rpc("open", **kw)["error"]["code"], "bad_request")
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    def test_missing_command_not_found(self):
        r = self.rpc("open", argv=["sid-no-such-command-xyz"], cwd=str(self.tmp))
        self.assertEqual(r["error"]["code"], "not_found")

    def test_close_rejects_bad_ids(self):
        self.assertEqual(self.rpc("close", session_id="../x")["error"]["code"], "bad_request")
        self.assertEqual(self.rpc("close", session_id="n-000000000000")["error"]["code"], "not_found")

    def test_env_allowlist_and_path(self):
        # Isolate the daemon fallback from the developer/CI shell's TERM.
        with mock.patch.dict(os.environ, {"SID_R2_SECRET": "leak", "PATH": "/usr/bin:/bin", "TERM": ""}):
            sid = self.open(["/usr/bin/env"])
            self.wait_for(lambda: (self.info(sid) or {}).get("exited"), msg="env exit")
        out = self.output(sid).decode()
        self.assertNotIn("SID_R2_SECRET", out)
        self.assertIn("TERM=xterm-256color", out)
        self.assertRegex(out, r"PATH=/usr/bin:/bin:.*/opt/homebrew/bin")
        keys = {line.split("=", 1)[0] for line in out.splitlines() if "=" in line}
        # macOS CoreFoundation injects __CF_USER_TEXT_ENCODING into every
        # process it starts; it is not inherited from the daemon.
        self.assertLessEqual(keys - {"__CF_USER_TEXT_ENCODING"},
                             set(d.ENV_ALLOW) | set(d.ENV_IDENTITY))
        import pwd
        me = pwd.getpwuid(os.getuid()).pw_name
        self.assertIn(f"USER={me}", out.splitlines())
        self.assertIn(f"LOGNAME={me}", out.splitlines())

    def test_identity_inherited_without_env_and_not_overridable(self):
        import pwd
        me = pwd.getpwuid(os.getuid()).pw_name
        with mock.patch.dict(os.environ, {"USER": "", "LOGNAME": ""}):
            env = d.build_env({"PATH": "/usr/bin"})
        self.assertEqual((env["USER"], env["LOGNAME"]), (me, me))
        r = self.rpc("open", argv=["/bin/sh"], cwd=str(self.tmp), env={"USER": "root"})
        self.assertEqual(r["error"]["code"], "bad_request")
        self.assertEqual(d.build_env({"USER": "root"})["USER"], me)


class ShutdownTests(SessionCase):
    def test_shutdown_requires_force_with_sessions(self):
        sid = self.open(["/bin/sh", "-c", "exec sleep 100"])
        pid = self.info(sid)["pid"]
        self.assertEqual(self.rpc("shutdown")["error"]["code"], "busy")
        r = self.rpc("shutdown", force=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"]["sessions"], 1)
        self.thread.join(CLOSE_TIMEOUT)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(gone(pid))

    def test_open_refused_while_shutting_down(self):
        sid = self.open([PY, "-c", "import signal,time;signal.signal(signal.SIGHUP,signal.SIG_IGN);"
                         "print('armed',flush=True);time.sleep(100)"])
        self.wait_out(sid, b"armed")  # HUP ignored: shutdown stays in progress ~1s
        self.rpc("shutdown", force=True)
        r = self.rpc("open", argv=["/bin/sh"], cwd=str(self.tmp))
        self.assertEqual(r["error"]["code"], "limit")

    def test_daemon_close_kills_sessions(self):
        sid = self.open([PY, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                         "print('armed',flush=True);time.sleep(100)"])
        self.wait_out(sid, b"armed")
        pid = self.info(sid)["pid"]
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        self.assertTrue(gone(pid))
        self.assertEqual(self.dm._sessions, {})


class ReapOrderingTests(unittest.TestCase):
    """No live runtime; synthetic child identity and process-table snapshots."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, HOME=self.tmp, VBEAR_HOME=self.tmp,
                                          VBEAR_RUNTIME_AUTOSTART="0"))
        self.events = []
        self.proc = mock.Mock(pid=43210, returncode=None)
        self.proc.poll.side_effect = lambda: self.events.append("popen.poll") or 7
        self.proc.wait.side_effect = lambda **kw: self.events.append("popen.wait") or 7
        self.s = d.Session("synthetic", self.proc, -1, [], self.tmp, 80, 24)
        self.info = type("Exit", (), {"si_status": 7, "si_code": os.CLD_EXITED})()
        self.enterContext(mock.patch.object(d.os, "waitid", return_value=self.info))
        self.enterContext(mock.patch.object(d.os, "waitpid", side_effect=self.reap))
        self.enterContext(mock.patch.object(d.os, "killpg", side_effect=lambda pg, sig: self.events.append(sig)))
        self.table = self.enterContext(mock.patch.object(d.proctrack, "process_table", return_value=[]))
        self.dm = d.Daemon(Path(self.tmp) / "runtime", log=mock.Mock())
        self.dm._sessions[self.s.sid] = self.s
        self.dm._next_prepared_sweep = float("inf")
        self.dm._stream_tick = mock.Mock()
        self.dm._review_tick = mock.Mock()

    def reap(self, pid, flags):
        self.events.append("waitpid")
        return pid, 7 << 8

    def test_tick_signals_live_child_before_reaping_leader(self):
        self.table.return_value = [{"pgid": self.s.pgid, "stat": "R"}]
        self.dm._begin_close(self.s)
        self.dm._tick(self.s.deadline + 0.1)
        self.dm._tick(self.s.deadline + 0.1)
        self.assertEqual(self.events, [signal.SIGHUP, signal.SIGTERM, signal.SIGKILL])
        self.table.return_value = [{"pgid": self.s.pgid, "stat": "Z"}]
        self.dm._tick(self.s.deadline + 0.1)
        self.s.signal(signal.SIGKILL)
        self.assertEqual(self.events, [signal.SIGHUP, signal.SIGTERM, signal.SIGKILL, "waitpid"])
        self.assertEqual(self.s.exit_code, 7)
        self.assertEqual(self.proc.returncode, 7)

    def test_shutdown_signals_before_reap(self):
        def kill(pg, sig):
            self.events.append(sig)
            self.table.return_value = []
        self.table.return_value = [{"pgid": self.s.pgid, "stat": "R"}]
        with mock.patch.object(d.os, "killpg", side_effect=kill):
            self.dm._kill_all_sessions()
        self.s.signal(signal.SIGKILL)
        self.assertEqual(self.events, [signal.SIGTERM, "waitpid"])

    def test_lost_leader_refuses_all_groups_and_logs_review(self):
        self.s.extra_groups = [43211]
        with mock.patch.object(d.os, "waitid", side_effect=ChildProcessError):
            self.dm._begin_close(self.s)
            self.dm._tick(self.s.deadline + 0.1)
            self.dm._finalize(self.s)
        self.assertEqual(self.events, [])
        self.assertTrue(self.dm._log.called)
        self.assertTrue(self.s.manual_review)

    def test_unavailable_table_retains_popen_without_reaping(self):
        self.table.side_effect = d.proctrack.ProcessTableUnavailable("synthetic")
        self.s.poll()
        self.dm._finalize(self.s)
        self.assertEqual(self.events, [])
        self.assertIs(self.dm._held_leaders[0]["proc"], self.proc)

    def test_natural_exit_reaps_once_and_preserves_signalled_exit_code(self):
        self.info.si_code, self.info.si_status = os.CLD_KILLED, signal.SIGTERM
        self.dm._tick(0)
        self.dm._tick(0)
        self.s.signal(signal.SIGKILL)
        self.assertEqual(self.events, ["waitpid"])
        self.assertEqual(self.s.exit_code, -signal.SIGTERM)
        self.assertEqual(self.proc.returncode, -signal.SIGTERM)

    def test_managed_extra_group_keeps_leader_until_signals_complete(self):
        self.s.extra_alive = True
        self.s.extra_groups = [43211]
        self.s.poll()
        self.assertFalse(self.s.reap_if_empty())
        self.s.signal(signal.SIGTERM)
        self.s.extra_alive = False
        self.assertTrue(self.s.reap_if_empty())
        self.s.signal(signal.SIGKILL)
        self.assertEqual(self.events, [signal.SIGTERM, signal.SIGTERM, "waitpid"])

    def test_zombie_only_eperm_reaps_after_signal(self):
        self.table.return_value = [{"pgid": self.s.pgid, "stat": "Z"}]
        def kill(pg, sig):
            self.events.append(sig)
            raise PermissionError()
        with mock.patch.object(d.os, "killpg", side_effect=kill):
            self.s.signal(signal.SIGTERM)
            self.assertTrue(self.s.reap_if_empty())
            self.s.signal(signal.SIGKILL)
        self.assertEqual(self.events, [signal.SIGTERM, "waitpid"])

    def test_spawn_setup_failure_signals_and_proves_empty_before_reap(self):
        self.table.side_effect = [[{"pgid": self.s.pgid, "stat": "R"}], []]
        with mock.patch.object(d.os, "openpty", return_value=(42, 43)), \
             mock.patch.object(d, "_set_winsize"), mock.patch.object(d.os, "close"), \
             mock.patch.object(d.os, "set_blocking", side_effect=OSError("synthetic")), \
             mock.patch.object(d.subprocess, "Popen", return_value=self.proc):
            with self.assertRaisesRegex(OSError, "synthetic"):
                self.dm._spawn(["unused"], self.tmp, 80, 24, {})
        self.assertEqual(self.events, [signal.SIGKILL, "waitpid"])
        self.assertEqual(self.dm._held_leaders, [])


class WaitidOwnershipTests(unittest.TestCase):
    def test_poll_keeps_real_exited_leader_waitable(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ, HOME=tmp, VBEAR_HOME=tmp, VBEAR_RUNTIME_AUTOSTART="0"):
            proc = subprocess.Popen([PY, "-I", "-S", "-c", "raise SystemExit(7)"],
                                    env=dict(os.environ), start_new_session=True)
            s = d.Session("synthetic", proc, -1, [], tmp, 80, 24)
            try:
                deadline = time.monotonic() + 3
                while s.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(s.exit_code, 7)
                self.assertIsNone(proc.returncode)
                pid, status = os.waitpid(proc.pid, os.WNOHANG)
                self.assertEqual(pid, proc.pid)  # poll did not consume the exit
                proc.returncode = os.waitstatus_to_exitcode(status)
            finally:
                proc.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
