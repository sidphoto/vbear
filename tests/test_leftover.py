"""P42-0: the tool the tests use to prove they leave no background process behind (tests/leftover.py).

The samples here are real processes started on purpose and *not* closed, to show the check fails on them
(and then closes them, but only those whose VBEAR_HOME is under the folder the test gave)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests import leftover

ROOT = Path(__file__).resolve().parent.parent
SLEEPER = "import time; time.sleep(60)"


class LeftoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbl-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.procs = []
        self.addCleanup(self.close_procs)

    def close_procs(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait(5)

    def spawn(self, argv, home):
        p = subprocess.Popen(argv, cwd=ROOT, env={**os.environ, "VBEAR_HOME": str(home), "HOME": str(self.tmp)},
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def test_a_process_whose_home_is_under_the_folder_is_found_and_one_elsewhere_is_not(self):
        mine = self.spawn([sys.executable, "-c", SLEEPER], self.tmp / "st")
        other = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbl-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, other, True)
        theirs = self.spawn([sys.executable, "-c", SLEEPER], other / "st")
        found = [pid for pid, _ in leftover.find(self.tmp)]
        self.assertIn(mine.pid, found)
        self.assertNotIn(theirs.pid, found)
        self.assertNotIn(os.getpid(), found)
        self.assertNotIn(mine.pid, [pid for pid, _ in leftover.find(other)])

    def test_the_folder_may_be_given_by_either_name_of_tmp(self):
        mine = self.spawn([sys.executable, "-c", SLEEPER], self.tmp / "st")
        alias = Path("/tmp") / self.tmp.name                     # /tmp is a link to /private/tmp on macOS
        self.assertIn(mine.pid, [pid for pid, _ in leftover.find(alias)])

    def test_a_folder_with_a_similar_name_is_not_under_it(self):
        mine = self.spawn([sys.executable, "-c", SLEEPER], str(self.tmp) + "2/st")
        self.assertNotIn(mine.pid, [pid for pid, _ in leftover.find(self.tmp)])

    def test_the_check_fails_on_a_runtimed_nobody_closed_and_then_closes_it(self):
        home = self.tmp / "st"
        p = self.spawn([sys.executable, "-m", "vbear", "runtimed"], home)
        with self.assertRaises(AssertionError) as ctx:
            leftover.assert_clean(self.tmp)
        self.assertIn(str(p.pid), str(ctx.exception))
        p.wait(10)                                                        # the one it found is ended
        leftover.assert_clean(self.tmp)                                  # and now there is nothing left

    def test_the_check_passes_when_the_process_was_closed_by_the_test(self):
        p = self.spawn([sys.executable, "-c", SLEEPER], self.tmp / "st")
        p.kill()
        p.wait(5)
        leftover.assert_clean(self.tmp)

    def test_what_a_found_process_started_is_found_too(self):
        code = ("import subprocess, sys, time; "
                "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], env={}); "
                "print(c.pid, flush=True); time.sleep(60)")
        p = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "VBEAR_HOME": str(self.tmp / "st")},
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.addCleanup(p.stdout.close)
        child = int(p.stdout.readline())
        self.addCleanup(self._kill, child)
        found = [pid for pid, _ in leftover.find(self.tmp)]
        self.assertIn(p.pid, found)
        self.assertIn(child, found, "a child with a bare environment is still under the daemon")

    @staticmethod
    def _kill(pid):
        try:
            os.kill(pid, 9)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
