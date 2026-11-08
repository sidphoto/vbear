"""P44-3: keeping the Mac from sleeping while employees work (ADR 0010 point 6). Only ever a fake command: nothing here starts
``caffeinate`` or any program, and nothing waits for real time (a hand-moved clock). The argv is checked word for word."""
from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest import mock

from tests.routine_fixtures import RoutineBase, at
from vbear import keep_awake, routines as rt, server

ARGV = ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]


class FakeProcess:
    def __init__(self):
        self.ended = False
        self.terminated = 0

    def poll(self):
        return 0 if self.ended else None

    def terminate(self):
        self.terminated += 1
        self.ended = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.ended = True


class FakeCommand:
    """What the console hands over in place of the real launch: records the argv it gets."""

    def __init__(self):
        self.calls: list = []
        self.processes: list[FakeProcess] = []
        self.fail = False

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.fail:
            raise OSError("no such program")
        self.processes.append(FakeProcess())
        return self.processes[-1]


class TheArgvTests(unittest.TestCase):
    def test_the_argv_is_fixed_and_has_the_consoles_own_pid(self):
        self.assertEqual(keep_awake.argv(), ARGV)
        self.assertEqual(keep_awake.argv(), keep_awake.argv(), "nothing changes between calls")

    def test_the_real_launch_runs_that_argv_without_a_shell_and_nothing_else(self):
        with mock.patch.object(keep_awake.subprocess, "Popen") as popen:
            got = keep_awake.launch(keep_awake.argv())
        self.assertIs(got, popen.return_value)
        (args,), kwargs = popen.call_args
        self.assertEqual(args, ARGV)
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertEqual({k: v for k, v in kwargs.items() if k in ("stdin", "stdout", "stderr")},
                         {"stdin": keep_awake.subprocess.DEVNULL, "stdout": keep_awake.subprocess.DEVNULL, "stderr": keep_awake.subprocess.DEVNULL})

    def test_the_real_launch_refuses_any_other_argv(self):
        for argv in (["/bin/echo", "x"], ARGV + ["x"], ["/usr/bin/caffeinate", "-d", "-w", str(os.getpid())], ["/usr/bin/caffeinate", "-i", "-w", "1"],
                     "/usr/bin/caffeinate -i", [], None):
            with mock.patch.object(keep_awake.subprocess, "Popen") as popen:
                with self.assertRaises(ValueError):
                    keep_awake.launch(argv)
            popen.assert_not_called()

    def test_a_console_built_any_other_way_has_no_command_and_starts_nothing(self):
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory(prefix="vbk-")
        self.addCleanup(tmp.cleanup)
        home = Path(os.path.realpath(tmp.name)) / "h"
        (home / ".vbear").mkdir(parents=True, mode=0o700)
        env = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        env.start()
        self.addCleanup(env.stop)
        console = server.Console(0)                    # no daemon is started: VBEAR_RUNTIME_AUTOSTART=0
        self.assertIsNone(console.keep_awake_command)
        with mock.patch.object(keep_awake.subprocess, "Popen") as popen:
            self.assertIsNone(console._keep_awake_launch(keep_awake.argv()))
            runner = console.routine_runner()
            self.assertIs(runner.keep_awake._launch.__self__, console)
            runner.keep_awake.update(True, 1000.0)
        popen.assert_not_called()
        console.keep_awake_command = lambda command: ("handed", command)
        self.assertEqual(console._keep_awake_launch(["x"]), ("handed", ["x"]))


class TheMachineTests(unittest.TestCase):
    def setUp(self):
        self.command = FakeCommand()
        self.ka = keep_awake.KeepAwake(launch=self.command)

    def test_work_starts_it_once_with_the_fixed_argv(self):
        self.ka.update(True, 100.0)
        self.ka.update(True, 115.0)
        self.ka.update(True, 130.0)
        self.assertEqual(self.command.calls, [ARGV])

    def test_no_work_ends_it_only_after_thirty_seconds(self):
        self.ka.update(True, 100.0)
        self.ka.update(False, 115.0)
        self.ka.update(False, 129.0)
        self.assertEqual(self.command.processes[0].terminated, 0)
        self.ka.update(False, 130.0)
        self.assertEqual(self.command.processes[0].terminated, 1)
        self.ka.update(False, 200.0)
        self.assertEqual(len(self.command.calls), 1, "and does not start again by itself")

    def test_work_that_comes_back_in_time_keeps_the_same_process(self):
        self.ka.update(True, 100.0)
        self.ka.update(False, 120.0)
        self.ka.update(True, 125.0)
        self.ka.update(False, 150.0)
        self.assertEqual((len(self.command.calls), self.command.processes[0].terminated), (1, 0), "the 30 seconds count from the last work")
        self.ka.update(False, 155.0)
        self.assertEqual(self.command.processes[0].terminated, 1)

    def test_work_after_it_ended_starts_a_new_one(self):
        self.ka.update(True, 100.0)
        self.ka.update(False, 131.0)
        self.ka.update(True, 200.0)
        self.assertEqual(len(self.command.calls), 2)

    def test_switched_off_never_starts_and_stops_at_once(self):
        self.ka.update(True, 100.0, on=False)
        self.assertEqual(self.command.calls, [])
        self.ka.update(True, 110.0)
        self.ka.update(True, 112.0, on=False)
        self.assertEqual(self.command.processes[0].terminated, 1)

    def test_a_command_that_fails_is_tried_again_only_after_a_minute_and_never_raises(self):
        self.command.fail = True
        self.ka.update(True, 100.0)
        self.ka.update(True, 130.0)
        self.assertEqual(len(self.command.calls), 1)
        self.ka.update(True, 160.0)
        self.assertEqual(len(self.command.calls), 2)
        self.assertTrue(self.ka.last_error)

    def test_a_process_that_ended_by_itself_is_replaced_not_more_than_once_a_minute(self):
        self.ka.update(True, 100.0)
        self.command.processes[0].ended = True
        self.ka.update(True, 115.0)
        self.assertEqual(len(self.command.calls), 1)
        self.ka.update(True, 161.0)
        self.assertEqual(len(self.command.calls), 2)

    def test_no_command_at_all_does_nothing(self):
        ka = keep_awake.KeepAwake(launch=lambda argv: None)
        ka.update(True, 100.0)
        ka.update(False, 200.0)
        ka.close()

    def test_closing_ends_it(self):
        self.ka.update(True, 100.0)
        self.ka.close()
        self.assertEqual(self.command.processes[0].terminated, 1)
        self.ka.close()
        self.assertEqual(self.command.processes[0].terminated, 1)


class TheSettingTests(RoutineBase):
    def test_the_default_is_off_and_the_setting_is_kept_beside_the_limit(self):
        self.assertFalse(rt.read_settings()[0]["keep_awake"])
        got = rt.set_settings({"keep_awake": True}, Decimal("3"))
        self.assertEqual(got["settings"], {"daily_usd": None, "keep_awake": True})
        rt.set_settings({"daily_usd": 0.75}, Decimal("3"))
        self.assertEqual(rt.read_settings()[0], {"daily_usd": 0.75, "keep_awake": True}, "the other one stays as it was")
        rt.set_settings({"keep_awake": False}, Decimal("3"))
        self.assertEqual(rt.read_settings()[0], {"daily_usd": 0.75, "keep_awake": False})
        rt.set_settings({"daily_usd": None, "keep_awake": True}, Decimal("3"))
        self.assertEqual(rt.read_settings()[0], {"daily_usd": None, "keep_awake": True})

    def test_nothing_but_a_boolean_is_taken(self):
        for bad in ({"keep_awake": 1}, {"keep_awake": "true"}, {"keep_awake": None}, {"keep_awake": True, "x": 1}):
            with self.assertRaises(Exception):
                rt.set_settings(bad, Decimal("3"))
        self.assertFalse(rt.read_settings()[0]["keep_awake"])


class TheRunnerTests(RoutineBase):
    """The runner tells the machine whether anyone works: a routine's run that is going, or a dispatch that is running."""

    def setUp(self):
        super().setUp()
        self.command = FakeCommand()
        self.dispatching = [False]
        self.runner.keep_awake = keep_awake.KeepAwake(launch=self.command)
        self.runner.also_working = lambda: self.dispatching[0]
        self.item3(True)

    def switch(self, on):
        from vbear import routines as routines
        routines.set_settings({"keep_awake": on}, Decimal("3"))

    def test_switched_off_nothing_is_ever_started_however_much_work_there_is(self):
        self.routine()
        self.dispatching[0] = True
        self.tick_to(8, 0, 10)
        self.assertEqual(self.states(), ["running"])
        self.tick_after(15)
        self.assertEqual(self.command.calls, [])

    def test_on_and_a_run_going_it_starts_with_the_fixed_argv_and_ends_thirty_seconds_after_the_run(self):
        self.switch(True)
        self.routine()
        self.tick_to(7, 59, 55)
        self.assertEqual(self.command.calls, [], "no work yet")
        self.tick_to(8, 0, 10)
        self.assertEqual(self.command.calls, [ARGV])
        self.daemon.finish(self.runs()[0]["chat_id"], reply="好", cost="0.01")
        self.tick_after(15)
        self.assertEqual(self.states(), ["done"])
        process = self.command.processes[0]
        self.tick_after(14)
        self.assertEqual(process.terminated, 0)
        self.tick_after(15)
        self.assertEqual(process.terminated, 1)
        self.assertEqual(len(self.command.calls), 1)

    def test_a_dispatch_that_is_running_counts_too(self):
        self.switch(True)
        self.tick_to(8, 0, 0)
        self.assertEqual(self.command.calls, [])
        self.dispatching[0] = True
        self.tick_after(15)
        self.assertEqual(self.command.calls, [ARGV])
        self.dispatching[0] = False
        self.tick_after(15)
        self.tick_after(15)
        self.assertEqual(self.command.processes[0].terminated, 1)

    def test_switching_it_off_ends_it_at_once(self):
        self.switch(True)
        self.dispatching[0] = True
        self.tick_to(8, 0, 0)
        self.assertEqual(len(self.command.calls), 1)
        self.switch(False)
        self.tick_after(15)
        self.assertEqual(self.command.processes[0].terminated, 1)

    def test_a_queued_run_that_has_not_begun_is_not_work(self):
        self.switch(True)
        self.routine()
        self.daemon.refuse = ["busy"] * 100                          # the employee is busy: the run waits
        self.tick_to(8, 0, 10)
        self.assertEqual(self.states(), ["starting"])
        self.assertEqual(self.command.calls, [])

    def test_closing_the_runner_ends_it(self):
        self.switch(True)
        self.dispatching[0] = True
        self.tick_to(8, 0, 0)
        self.runner.close()
        self.assertEqual(self.command.processes[0].terminated, 1)

    def test_a_fault_of_the_command_never_stops_the_runner(self):
        self.switch(True)
        self.command.fail = True
        self.routine()
        self.tick_to(8, 0, 10)
        self.assertEqual(self.states(), ["running"])
        self.assertEqual(len(self.sent()), 1)

    def test_a_routine_does_not_depend_on_the_setting_to_run(self):
        self.routine()
        self.tick_to(8, 0, 10)
        self.assertEqual(len(self.sent()), 1)


class DispatchRunningTests(unittest.TestCase):
    def test_the_check_reads_the_records_and_says_false_when_it_cannot(self):
        with mock.patch.object(keep_awake.dispatch, "record_ids", side_effect=OSError("x")):
            self.assertFalse(keep_awake.dispatch_running())
        with mock.patch.object(keep_awake.dispatch, "record_ids", return_value=["d-1", "d-2"]), \
                mock.patch.object(keep_awake.dispatch, "load", side_effect=[{"state": "paused"}, {"state": "running"}]):
            self.assertTrue(keep_awake.dispatch_running())
        with mock.patch.object(keep_awake.dispatch, "record_ids", return_value=["d-1"]), \
                mock.patch.object(keep_awake.dispatch, "load", return_value={"state": "done"}):
            self.assertFalse(keep_awake.dispatch_running())
        with mock.patch.object(keep_awake.dispatch, "record_ids", return_value=["d-1", "d-2"]), \
                mock.patch.object(keep_awake.dispatch, "load", side_effect=[keep_awake.dispatch.DispatchError("storage"), {"state": "running"}]):
            self.assertTrue(keep_awake.dispatch_running(), "a record that cannot be read is skipped")


if __name__ == "__main__":
    unittest.main()
