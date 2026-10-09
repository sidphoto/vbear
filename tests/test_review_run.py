"""One Codex review process (vbear/runtime/review_run.py): pipes, output
caps, early ends, and how its process group is ended. The "Codex" here is a
small Python script; no model is called."""

import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import review_fixtures as rf
from vbear.runtime import review_run as rr
from vbear.runtime import stream_session

C = rf.C


def events_bytes(text=None):
    evs, _, _ = rf.valid_run(text=text)
    return rf.lines(evs)


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vbrr-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "codex-home"
        self.scratch = self.tmp / "scratch"
        self.run_home = self.tmp / "run-home"
        for d in (self.home, self.scratch, self.run_home):
            d.mkdir(mode=0o700)
        self.job = self.tmp / "job"
        self.job.mkdir(mode=0o700)
        self.logs, self.procs = [], []
        self.addCleanup(self.reap_leftovers)

    def reap_leftovers(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                p.wait(timeout=2)
            except Exception:
                pass
        for pidfile in self.tmp.glob("*.pid"):
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def spawn(self, code, **over):
        proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=str(self.scratch), start_new_session=True,
                                env={**os.environ, "PYTHONUNBUFFERED": "1", "TMPD": str(self.tmp),
                                     "HOMEDIR": str(self.home)})
        self.procs.append(proc)
        start = stream_session.capture_leader(proc.pid)
        ev = os.open(self.job / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        er = os.open(self.job / "stderr.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        kw = dict(job_id="r-0123456789abcdef", c=C, proc=proc, events_fd=ev, stderr_fd=er, leader_start=start,
                  codex_home=self.home, scratch=str(self.scratch), run_home=str(self.run_home), timeout_s=30.0,
                  max_responses=100, log=self.logs.append, now=time.monotonic())
        kw.update(over)
        return rr.ReviewRun(**kw)

    def drive(self, run, timeout=25.0):
        sel = selectors.DefaultSelector()
        regs = {}
        for name, fd in (("out", run.stdout), ("err", run.stderr)):
            sel.register(fd, selectors.EVENT_READ, name)
            regs[name] = fd
        end = time.monotonic() + timeout
        while not run.finished and time.monotonic() < end:
            for key, _ in sel.select(0.05):
                if key.data not in regs:
                    continue
                (run.on_stdout if key.data == "out" else run.on_stderr)(time.monotonic())
            for name, eof in (("out", run.stdout_eof), ("err", run.stderr_eof)):
                if eof and name in regs:
                    try:
                        sel.unregister(regs.pop(name))
                    except (KeyError, ValueError):
                        pass
            run.tick(time.monotonic())
        self.assertTrue(run.finished, f"the run did not finish; logs {self.logs[-3:]}")
        return run.outcome

    def group_gone(self, pid):
        try:
            os.killpg(pid, 0)
            return False
        except ProcessLookupError:
            return True
        except PermissionError:
            return False


WRITE_EVENTS = "import os,sys;sys.stdout.buffer.write(open(os.environ['TMPD']+'/events.bin','rb').read());sys.stdout.flush()"


class NormalEndTests(RunCase):
    def test_a_normal_review(self):
        (self.tmp / "events.bin").write_bytes(events_bytes())
        run = self.spawn(WRITE_EVENTS + ";sys.stderr.write('some log\\n')")
        out = self.drive(run)
        self.assertEqual((out["exit_code"], out["exit_signal"], out["terminated_for"], out["manual_review"]),
                         (0, None, None, None))
        self.assertEqual((out["invalid_reasons"], out["partial_line"], out["write_failed"]), ([], False, False))
        self.assertEqual((self.job / "events.jsonl").read_bytes(), events_bytes())
        self.assertEqual(out["events_bytes"], len(events_bytes()))
        self.assertEqual((self.job / "stderr.log").read_bytes(), b"some log\n")
        self.assertEqual(run.tracker.finish().thread_id, rf.THREAD)
        self.assertTrue(run.reaped and not out["leader_held"])
        self.assertTrue(self.group_gone(run.pid))

    def test_a_non_zero_exit_is_recorded(self):
        run = self.spawn("import sys; sys.exit(3)")
        out = self.drive(run)
        self.assertEqual((out["exit_code"], out["terminated_for"]), (3, None))

    def test_a_signal_death_is_recorded(self):
        run = self.spawn("import os,signal; os.kill(os.getpid(), signal.SIGUSR1)")
        out = self.drive(run)
        self.assertEqual((out["exit_code"], out["exit_signal"]), (None, signal.SIGUSR1))

    def test_a_partial_last_line_is_noted(self):
        run = self.spawn("import sys; sys.stdout.write('{\"type\":\"thread.started\",\"thread_id\":\"" + rf.THREAD + "\"}\\n{\"type\"')")
        out = self.drive(run)
        self.assertTrue(out["partial_line"])


class EndedEarlyTests(RunCase):
    HANG = "import time; time.sleep(600)"

    def test_an_event_that_breaks_a_rule_ends_the_review(self):
        run = self.spawn("import sys,time; sys.stdout.write('{\"type\":\"error\",\"message\":\"x\"}\\n'); "
                         "sys.stdout.flush(); time.sleep(600)")
        out = self.drive(run)
        self.assertEqual(out["terminated_for"], "events_invalid")
        self.assertTrue(any("失敗事件" in r for r in out["invalid_reasons"]))
        self.assertTrue(self.group_gone(run.pid))
        self.assertTrue(run.reaped)

    def test_events_past_the_cap_end_the_review_with_a_bounded_file(self):
        with mock.patch.object(rr, "EVENTS_CAP", 1000):
            run = self.spawn("import sys,time; sys.stdout.write('x'*5000); sys.stdout.flush(); time.sleep(600)")
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "events_cap")
        self.assertEqual((self.job / "events.jsonl").stat().st_size, 1000)           # nothing past the cap
        self.assertTrue(any("寫入上限" in r for r in out["invalid_reasons"]))

    def test_stderr_past_the_cap_ends_the_review(self):
        with mock.patch.object(rr, "STDERR_CAP", 100):
            run = self.spawn("import sys,time; sys.stderr.write('e'*5000); sys.stderr.flush(); time.sleep(600)")
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "stderr_cap")
        self.assertEqual((self.job / "stderr.log").stat().st_size, 100)

    def test_a_line_over_one_mib_ends_the_review(self):
        run = self.spawn("import sys,time; sys.stdout.write('x'*(1200000)); sys.stdout.flush(); time.sleep(600)")
        out = self.drive(run)
        self.assertEqual(out["terminated_for"], "events_invalid")
        self.assertTrue(any("1 MiB" in r for r in out["invalid_reasons"]))

    def test_the_timeout(self):
        run = self.spawn(self.HANG, timeout_s=0.5)
        out = self.drive(run)
        self.assertEqual(out["terminated_for"], "timeout")
        self.assertIn("審查逾時", out["invalid_reasons"])
        self.assertTrue(self.group_gone(run.pid))

    def rollout_writer(self, n, extra=""):
        day = time.strftime("%Y/%m/%d")
        return ("import os,sys,time,json\n"
                f"sys.stdout.write(json.dumps({{'type':'thread.started','thread_id':'{rf.THREAD}'}})+'\\n'); sys.stdout.flush()\n"
                f"d=os.environ['HOMEDIR']+'/sessions/{day}'; os.makedirs(d)\n"
                f"f=open(d+'/rollout-x-{rf.THREAD}.jsonl','w')\n"
                f"for i in range({n}):\n"
                "    f.write(json.dumps({'ordinal':i,'type':'token_usage_record','payload':{}})+'\\n'); f.flush(); time.sleep(0.05)\n"
                + extra + "time.sleep(600)\n")

    def test_more_model_responses_than_the_limit_end_the_review(self):
        with mock.patch.object(rr, "WATCH_EVERY", 0.05):
            run = self.spawn(self.rollout_writer(8), max_responses=3)
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "responses")
        self.assertGreater(out["responses_seen"], 3)
        self.assertIn("模型回應數超過單次審查的上限", out["invalid_reasons"])

    def test_exactly_the_limit_is_allowed(self):
        with mock.patch.object(rr, "WATCH_EVERY", 0.05):
            run = self.spawn(self.rollout_writer(3, extra="sys.exit(0)\n"), max_responses=3)
            out = self.drive(run)
        self.assertEqual((out["terminated_for"], out["exit_code"]), (None, 0))

    def test_two_rollouts_for_the_thread_end_the_review(self):
        # both exist when the monitor first looks (a later second one is caught by
        # the final validation, which searches again)
        day = time.strftime("%Y/%m/%d")
        code = ("import os,sys,time,json\n"
                f"d=os.environ['HOMEDIR']+'/sessions/{day}'; os.makedirs(d)\n"
                f"open(d+'/rollout-x-{rf.THREAD}.jsonl','w').write('x\\n')\n"
                f"open(d+'/rollout-y-{rf.THREAD}.jsonl','w').write('x\\n')\n"
                f"sys.stdout.write(json.dumps({{'type':'thread.started','thread_id':'{rf.THREAD}'}})+'\\n')\n"
                "sys.stdout.flush()\ntime.sleep(600)\n")
        with mock.patch.object(rr, "WATCH_EVERY", 0.05):
            run = self.spawn(code)
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "rollout_problem")
        self.assertTrue(any("不只一份" in r for r in out["invalid_reasons"]))

    def test_codex_home_over_its_threshold_ends_the_review(self):
        with mock.patch.object(rr.review_codex, "HOME_LIMIT", 1000), mock.patch.object(rr, "DISK_EVERY", 0.1):
            run = self.spawn("import os,time; open(os.environ['HOMEDIR']+'/big','wb').write(b'x'*5000); time.sleep(600)")
            run.next_disk = time.monotonic() + 0.1
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "disk_home")

    def test_scratch_and_run_home_together_over_their_threshold_end_the_review(self):
        with mock.patch.object(rr.review_codex, "WORK_LIMIT", 1000), mock.patch.object(rr, "DISK_EVERY", 0.1):
            run = self.spawn("import time; open('big','wb').write(b'x'*5000); time.sleep(600)")
            run.next_disk = time.monotonic() + 0.1
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "disk_scratch")

    def test_a_directory_that_cannot_be_counted_counts_as_over(self):
        with mock.patch.object(rr.review_codex, "tree_size", return_value=None), mock.patch.object(rr, "DISK_EVERY", 0.1):
            run = self.spawn(self.HANG)
            run.next_disk = time.monotonic() + 0.1
            out = self.drive(run)
        self.assertEqual(out["terminated_for"], "disk_home")

    def test_a_pipe_read_error_is_not_an_eof(self):
        real = os.read
        run = self.spawn(self.HANG)

        def read(fd, n):
            if fd == run.stdout:
                raise OSError(5, "Input/output error")
            return real(fd, n)
        with mock.patch.object(rr.os, "read", read):
            run.on_stdout(time.monotonic())
        self.assertEqual(run.terminated_for, "pipe_error")
        self.assertTrue(any("errno 5" in r for r in run.invalid))
        self.drive(run)

    def test_an_output_file_that_cannot_be_written_ends_the_review(self):
        run = self.spawn("import sys,time; sys.stdout.write('hello\\n'); sys.stdout.flush(); time.sleep(600)")
        os.close(run.events_fd)                               # the next write gets EBADF
        out = self.drive(run)
        self.assertTrue(out["write_failed"])
        self.assertEqual(out["terminated_for"], "write_error")
        self.assertTrue(any("無法寫入" in r for r in out["invalid_reasons"]))
        run.events_fd = os.open(os.devnull, os.O_WRONLY)       # so the cleanup's close has something to close

    def test_a_write_that_makes_no_progress_is_an_error(self):
        run = self.spawn("import sys,time; sys.stdout.write('hello\\n'); sys.stdout.flush(); time.sleep(600)")
        with mock.patch.object(rr.os, "write", return_value=0):
            out = self.drive(run)
        self.assertTrue(out["write_failed"])


class GroupEndTests(RunCase):
    def test_a_member_left_in_the_group_is_ended_before_the_leader_is_reaped(self):
        # the leader exits at once; a child that ignores TERM stays in its group
        code = ("import subprocess,sys,os\n"
                "subprocess.Popen([sys.executable,'-c',\"import signal,time,os;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "open(os.environ['TMPD']+'/child.pid','w').write(str(os.getpid()));time.sleep(600)\"])\n"
                "import time\nwhile not os.path.exists(os.environ['TMPD']+'/child.pid'): time.sleep(0.01)\n")
        with mock.patch.object(rr, "TERM_GRACE", 0.3), mock.patch.object(rr, "KILL_GRACE", 0.3):
            run = self.spawn(code)
            out = self.drive(run)
        self.assertEqual((out["exit_code"], out["terminated_for"], out["manual_review"]), (0, "group_left_over", None))
        self.assertTrue(self.group_gone(run.pid))
        self.assertTrue(run.reaped)

    def test_a_descendant_that_left_the_group_means_manual_review(self):
        code = ("import subprocess,os,time\n"
                "p=subprocess.Popen(['sleep','600'],start_new_session=True)\n"
                "open(os.environ['TMPD']+'/escaped.pid','w').write(str(p.pid))\n"
                "time.sleep(1.5)\n")
        run = self.spawn(code)
        out = self.drive(run)
        self.assertIn("離開了程序群組", out["manual_review"])
        self.assertTrue(run.reaped)                           # the group itself was empty
        os.kill(int((self.tmp / "escaped.pid").read_text()), 0)    # and the escaped child was not chased

    def test_a_group_that_cannot_be_proven_empty_keeps_the_leader_unreaped(self):
        reaped = []
        real = os.waitpid
        member = {"pid": 2, "ppid": 1, "pgid": 0, "uid": os.getuid(), "stat": "R", "start": "1.000000"}
        run = self.spawn("import sys; sys.exit(0)")
        with mock.patch.object(run, "_members", lambda: ([dict(member, pgid=run.pgid)], [])), \
                mock.patch.object(rr, "TERM_GRACE", 0.1), mock.patch.object(rr, "KILL_GRACE", 0.1), \
                mock.patch.object(rr, "KILL_GIVE_UP", 0.2), \
                mock.patch.object(rr.os, "waitpid", lambda p, o: (reaped.append(p), real(p, o))[1]):
            out = self.drive(run)
        self.assertIn("SIGKILL 後仍有程序存活", out["manual_review"])
        self.assertTrue(out["leader_held"])
        self.assertEqual(reaped, [])                           # never reaped (design 5.8)
        self.assertTrue(stream_session.leader_exited(run.pid))  # still our zombie

    def test_no_process_table_keeps_the_leader_unreaped(self):
        run = self.spawn("import sys; sys.exit(0)")
        with mock.patch.object(run, "_members", lambda: (None, None)), mock.patch.object(rr, "TABLE_GIVE_UP", 0.3):
            out = self.drive(run)
        self.assertIn("無法取得程序表", out["manual_review"])
        self.assertTrue(out["leader_held"])
        self.assertTrue(stream_session.leader_exited(run.pid))

    def test_nothing_is_signalled_when_the_leader_cannot_be_identified(self):
        code = ("import signal,sys,time,os\n"
                "signal.signal(signal.SIGTERM, lambda *a: (open(os.environ['TMPD']+'/got-sigterm','w').close(), sys.exit(1)))\n"
                "time.sleep(600)\n")
        run = self.spawn(code, leader_start="1600000000.000000", timeout_s=0.3)
        out = self.drive(run)
        time.sleep(0.5)
        self.assertFalse((self.tmp / "got-sigterm").exists())
        self.assertIn("不送訊號", out["manual_review"])
        self.assertTrue(out["leader_held"])
        self.assertFalse(run.reaped)

    def test_an_unexpected_waitid_error_gives_the_run_up_without_signals(self):
        # Codex S2b part 3 review #6: not an exception out of tick
        sent = []
        run = self.spawn("import time; time.sleep(600)")
        real_waitid = os.waitid
        with mock.patch.object(rr.os, "killpg", lambda p, sg: sent.append((p, sg))), \
                mock.patch.object(rr.os, "waitid", side_effect=OSError(22, "Invalid argument")):
            run.tick(time.monotonic())
        self.assertTrue(run.finished)
        self.assertIn("無法確認 leader 是否結束", run.outcome["manual_review"])
        self.assertIn("不送訊號", run.outcome["manual_review"])
        self.assertTrue(run.outcome["leader_held"])
        self.assertFalse(run.reaped)
        self.assertEqual(sent, [])
        os.kill(run.pid, 0)                                       # alive, untouched

    def test_an_unexpected_waitpid_error_leaves_the_leader_held(self):
        run = self.spawn("import sys; sys.exit(0)")
        reaped = []
        with mock.patch.object(rr.os, "waitpid", side_effect=OSError(22, "Invalid argument")):
            out = self.drive(run)
        self.assertIn("回收 leader 失敗", out["manual_review"])
        self.assertTrue(out["leader_held"])
        self.assertFalse(run.reaped)
        self.assertTrue(stream_session.leader_exited(run.pid))    # still our unreaped zombie

    def test_a_leader_that_is_no_longer_our_child_is_not_an_error(self):
        run = self.spawn("import sys; sys.exit(0)")
        real = os.waitid

        def waitid(*a, **kw):
            raise ChildProcessError(10, "No child processes")
        with mock.patch.object(rr.os, "waitid", waitid):
            run.tick(time.monotonic())
        self.assertFalse(run.finished)                            # logged, not given up on (the old rule)
        self.assertTrue(any("not our child" in line for line in self.logs))

    def test_a_review_that_ends_by_itself_is_not_signalled_at_all(self):
        sent = []
        real = os.killpg
        run = self.spawn("import sys; sys.exit(0)")
        with mock.patch.object(rr.os, "killpg", lambda p, s: (sent.append((p, s)), real(p, s))[1]):
            self.drive(run)
        self.assertEqual(sent, [])


class ObservedTests(RunCase):
    def test_new_descendants_are_flagged_for_the_manifest(self):
        code = "import subprocess,time\nsubprocess.Popen(['sleep','3'])\ntime.sleep(2)\n"
        run = self.spawn(code)
        seen = False
        with mock.patch.object(rr, "OBSERVE_EVERY", 0.05):
            end = time.monotonic() + 10
            sel = selectors.DefaultSelector()
            sel.register(run.stdout, selectors.EVENT_READ, "o")
            sel.register(run.stderr, selectors.EVENT_READ, "e")
            while not run.finished and time.monotonic() < end:
                for key, _ in sel.select(0.05):
                    (run.on_stdout if key.data == "o" else run.on_stderr)(time.monotonic())
                run.tick(time.monotonic())
                seen = seen or run.observed_dirty
                for name, eof, fd in (("o", run.stdout_eof, run.stdout), ("e", run.stderr_eof, run.stderr)):
                    if eof:
                        try:
                            sel.unregister(fd)
                        except (KeyError, ValueError):
                            pass
        self.assertTrue(seen)


if __name__ == "__main__":
    unittest.main()
