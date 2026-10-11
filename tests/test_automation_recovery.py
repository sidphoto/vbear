"""Phase 3, segment 4 (S3 design 3, 6, 10): the runner after an interruption
at every action boundary, a stop and a continue, the aborted review, and a
restart of the daemon. The interruption is a BaseException the runner does not
catch (as a killed console would not write anything more); a fresh runner
then takes over from the files. Real daemon, synthetic CLIs; no model."""

import os
import time
from unittest import mock

from tests.test_automation_runner import RunnerCase
from vbear import flows
from vbear import runner as runner_mod
from vbear.runtime import pipeline_store, stream_journal


class Died(BaseException):
    """The console was killed at this point."""


class Boundary(RunnerCase):
    def fresh_runner(self):
        r = runner_mod.AutomationRunner(self.console.executor, self.console.review)
        self.runner = r
        return r

    def tick_until_died(self, patcher):
        with patcher:
            for _ in range(200):
                try:
                    self.runner.tick()
                except Died:
                    return
                time.sleep(0.1)
        self.fail("the runner was never interrupted")

    def after_real_call(self, executor_attr, op=None):
        """Patch an executor method so that it does its work and the runner then 'dies' before it can record it."""
        real = getattr(self.console.executor, executor_attr)

        def wrapper(*a, **kw):
            result = real(*a, **kw)
            if op is None or a[0] == op:
                raise Died()
            return result
        return mock.patch.object(self.console.executor, executor_attr, wrapper)

    def journal(self):
        fd = os.open(self.base / "sessions" / self.launch, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return stream_journal.read(fd).state
        finally:
            os.close(fd)

    def finish_to_gate(self):
        self.run_until(lambda: self.last_event()["kind"] == "auto_stopped"
                       and self.last_event()["reason_code"] == "awaiting_merge", "the merge gate")

    def setup_run(self, mode="ok"):
        self.enable()
        self.start_executor()
        self.commit_work("work")
        self.fake_mode(mode)


class DispatchBoundaryTests(Boundary):
    def test_prepared_and_the_console_dies_before_the_send(self):
        self.setup_run()
        self.tick_until_died(self.after_real_call("_call", "dispatch_prepare"))
        self.assertEqual(self.kinds(), ["auto_dispatch_intent"])
        self.assertEqual(len(self.journal().turns), 1)                       # accepted, never sent
        self.fresh_runner()
        self.finish_to_gate()
        self.assertEqual(len(self.journal().turns), 1)                       # one dispatch, not two
        self.assertEqual(self.kinds().count("auto_dispatch_intent"), 1)
        self.assertEqual(self.kinds().count("auto_dispatch_sent"), 1)

    def test_sent_and_the_console_dies_before_the_event(self):
        self.setup_run()
        self.tick_until_died(self.after_real_call("_send"))
        self.assertEqual(self.kinds(), ["auto_dispatch_intent"])
        self.fresh_runner()
        self.finish_to_gate()
        self.assertEqual(len(self.journal().turns), 1)
        self.assertEqual(self.kinds().count("auto_dispatch_sent"), 1)

    def test_the_intent_is_written_and_nothing_else(self):
        self.setup_run()
        with mock.patch.object(runner_mod.AutomationRunner, "_prepare_and_send", side_effect=Died()):
            try:
                for _ in range(100):
                    self.runner.tick()
                    time.sleep(0.1)
            except Died:
                pass
        self.assertEqual(self.kinds(), ["auto_dispatch_intent"])
        self.assertEqual(len(self.journal().turns), 0)
        self.fresh_runner()                                                  # the same text is made again and must match
        self.finish_to_gate()
        self.assertEqual(len(self.journal().turns), 1)

    def test_a_plan_that_no_longer_matches_is_never_sent(self):
        self.setup_run()
        with mock.patch.object(runner_mod.AutomationRunner, "_prepare_and_send", side_effect=Died()):
            try:
                for _ in range(100):
                    self.runner.tick()
                    time.sleep(0.1)
            except Died:
                pass
        plan = self.base / "automation" / self.fid / "plan.txt"
        plan.write_text(plan.read_text() + "\n多一行")                          # tampered between the intent and the retry
        self.fresh_runner()
        self.run_until(lambda: self.stop_reason() is not None, "a stop")
        self.assertIn(self.stop_reason()["reason_code"], ("plan_changed", "text_changed"))
        self.assertEqual(len(self.journal().turns), 0)
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))


class ReviewBoundaryTests(Boundary):
    def test_review_started_and_the_console_dies_before_the_event(self):
        self.setup_run()
        self.tick_until_died(self.after_real_call("_call", "review_start"))
        self.assertEqual(self.kinds()[-1], "auto_review_intent")
        self.fresh_runner()
        self.finish_to_gate()
        self.assertEqual(len(self.reviews()), 1)                             # one job for round 1
        self.assertEqual(self.kinds().count("auto_review_intent"), 1)
        self.assertEqual(self.kinds().count("auto_review_started"), 1)

    def test_the_review_intent_alone_is_completed_with_the_same_round(self):
        self.setup_run()
        with mock.patch.object(runner_mod.AutomationRunner, "_send_review", side_effect=Died()):
            try:
                for _ in range(200):
                    self.runner.tick()
                    time.sleep(0.1)
            except Died:
                pass
        self.assertEqual(self.kinds()[-1], "auto_review_intent")
        self.assertEqual(self.reviews(), [])
        self.fresh_runner()
        self.finish_to_gate()
        self.assertEqual([r["round"] for r in self.reviews()], [1])


class StopAndContinueTests(Boundary):
    def test_a_review_ended_by_a_stop_is_run_again_as_the_next_round(self):
        self.setup_run("hang")
        self.run_until(lambda: "auto_review_started" in self.kinds(), "the review to start")
        st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
        self.assertEqual(st, 200, r)
        self.wait_for(lambda: self.reviews()[0]["state"] in ("cleaned", "manual_review"), msg="the review to end")
        self.assertEqual(self.reviews()[0]["outcome"], "invalid")
        self.fake_mode("ok")
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["status"]["state"] == "idle", msg="idle")
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)
        self.finish_to_gate()
        self.assertIn("auto_review_aborted", self.kinds())
        rounds = {x["round"]: x["outcome"] for x in self.reviews()}
        self.assertEqual(rounds, {1: "invalid", 2: "valid"})                 # counted: two reviews were made
        events = flows.get_flow(self.fid)["events"]
        aborted = next(e for e in events if e["kind"] == "auto_review_aborted")
        self.assertEqual((aborted["round"], aborted["commit"]), (1, self.commit))

    def test_when_head_moved_meanwhile_no_new_review_is_started(self):
        self.setup_run("hang")
        self.run_until(lambda: "auto_review_started" in self.kinds(), "the review to start")
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.wait_for(lambda: self.reviews()[0]["state"] in ("cleaned", "manual_review"), msg="the review to end")
        self.git("commit", "-q", "--allow-empty", "-m", "someone moved on")      # HEAD is no longer the reviewed commit
        self.fake_mode("ok")
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["status"]["state"] == "idle", msg="idle")
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        self.run_until(lambda: self.stop_reason() is not None and self.stop_reason()["reason_code"] != "user_stop",
                       "a stop that waits for the user")
        self.assertEqual(len(self.reviews()), 1)                             # no second round was started
        self.assertIn("review_", self.stop_reason()["reason_code"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))

    def test_continue_checks_its_premises_for_an_automatic_flow(self):
        self.setup_run()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.host.claude = "9.9.9"
        from vbear import risk_acceptance as ra
        ra._facts_cache.clear()
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual((st, r["code"]), (409, "cannot_continue"))
        self.assertTrue(any("風險接受" in x for x in r["reasons"]), r)
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))            # nothing was released
        self.host.claude = "2.1.292"
        ra._facts_cache.clear()
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)

    def test_a_dispatch_that_arrives_after_the_stop_is_refused_and_counts_for_nothing(self):
        self.setup_run()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        mode = pipeline_store.mode_info(self.base, self.fid)
        from vbear import daemon_client                                      # the daemon is asked directly, as a late runner would
        with self.assertRaises(daemon_client.DaemonError):
            daemon_client.call(self.console.executor.runtime, "dispatch_prepare", launch_id=self.launch,
                               pipeline=self.fid, dispatch_id="0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", text="late",
                               approval={"kind": "automation", "id": mode["approval_id"]})
        self.assertEqual(len(self.journal().turns), 0)


class DaemonRestartTests(Boundary):
    def test_a_restart_leaves_the_flow_stopped_and_the_runner_does_nothing(self):
        self.setup_run("slow")
        self.run_until(lambda: "auto_dispatch_sent" in self.kinds(), "a dispatch to be sent")
        before = self.kinds()
        self.crash_daemon()
        self.restart_daemon()
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertIn("daemon 重啟", pipeline_store.hold_info(self.base, self.fid)["reason"])   # (or the recovery's own)
        for _ in range(4):
            self.assertEqual(self.runner.tick()[self.fid], "held")
        after = self.kinds()
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(after[len(before):], ["auto_stopped"])                # said once, then silence
        self.assertEqual(flows.get_flow(self.fid)["events"][-1]["reason_code"], "daemon_hold")
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "auto")   # the mode itself stays
