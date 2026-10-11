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

    def kill_and_reap(self, pid, timeout=15.0):
        """The executor dies with the daemon that held it: kill it and WAIT until it is gone (we are its parent:
        the daemon runs in this process), so that nothing is left running and no later step races its death."""
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        end = time.monotonic() + timeout
        while True:
            try:
                done, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return                                  # already reaped
            if done == pid:
                return
            if time.monotonic() >= end:
                self.fail(f"process {pid} did not exit")
            time.sleep(0.02)

    def old_session_after_restart(self):
        """The user's view of the old session after the daemon restarted: its terminal state, then the user's own
        'close session' (which has nothing left to stop and says so), before anything else is done."""
        s = self.executor_status()["sessions"][-1]
        self.assertEqual(s["manifest_state"], "ended", s)                     # the daemon's recovery ended it
        self.assertFalse(s["status"]["live"])
        self.assertEqual(s["status"]["state"], "recovered")
        st, r = self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": s["launch_id"]})
        self.assertNotEqual(st, 500, r)                                       # a clear answer, not a crash
        self.assertIn(st, (200, 404, 409), r)
        after = self.executor_status()["sessions"][-1]
        self.assertEqual((after["launch_id"], after["manifest_state"]), (s["launch_id"], "ended"))
        return s["launch_id"], st, r

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

    def test_continue_waits_for_a_review_that_the_stop_is_still_ending(self):
        # the late failure of an aborted review would undo a release made before it: refused until it is over
        from unittest import mock
        self.setup_run()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        running = {"job_id": "r-" + "9" * 16, "state": "running", "outcome": None, "round": 1}
        with mock.patch.object(self.console.executor, "_flow_reviews", return_value=[running]):
            st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual((st, r["code"]), (409, "cannot_continue"))
        self.assertTrue(any("審查沒有結束" in x for x in r["reasons"]), r)
        # and the daemon says the same to a console that did not check
        from vbear import daemon_client

        class Job:
            job_id, pipeline_id = "r-" + "9" * 16, self.fid
        self.dm._reviews["r-" + "9" * 16] = Job()
        try:
            with self.assertRaises(daemon_client.DaemonError) as cm:
                daemon_client.call(self.console.executor.runtime, "pipeline_release", pipeline=self.fid)
            self.assertIn("審查正在結束", str(cm.exception))
        finally:
            self.dm._reviews.pop("r-" + "9" * 16, None)
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


class WritingBoundaryTests(Boundary):
    """S3 design 10: the dispatch is still being written when the console restarts."""

    def test_a_dispatch_still_in_writing_is_waited_for_not_queued_or_sent_again(self):
        from vbear.runtime import stream_session
        self.setup_run()
        calls = []
        real_call, real_send = self.console.executor._call, self.console.executor._send

        def counting_call(op, **kw):
            calls.append(op)
            return real_call(op, **kw)

        def counting_send(fields):
            calls.append("stream_send")
            return real_send(fields)
        with mock.patch.object(stream_session.StreamSession, "on_writable", return_value=False):
            # the daemon has the line but the pipe does not take it: the turn stays in "writing"
            self.tick_until_died(self.after_real_call("_send"))
            self.assertEqual(self.kinds(), ["auto_dispatch_intent"])
            d = next(e for e in flows.get_flow(self.fid)["events"] if e["kind"] == "auto_dispatch_intent")["dispatch_id"]
            self.wait_for(lambda: any(x["dispatch_id"] == d and x["status"] == "writing"
                                      for x in self.executor_status()["sessions"][-1]["status"]["dispatches"]),
                          msg="the dispatch to be in writing")
            self.fresh_runner()                                               # the console restarted
            with mock.patch.object(self.console.executor, "_call", counting_call), \
                    mock.patch.object(self.console.executor, "_send", counting_send):
                actions = [self.runner.tick()[self.fid] for _ in range(6)]
            self.assertTrue(all(a.startswith("waiting:") for a in actions), actions)
            self.assertNotIn("dispatch_prepare", calls)                       # not prepared again
            self.assertNotIn("stream_send", calls)                            # not queued again
            self.assertEqual(self.kinds(), ["auto_dispatch_intent"])          # and nothing was claimed
        # the original write goes on and completes: the same dispatch id is found, recorded, and the run ends
        self.finish_to_gate()
        self.assertEqual(len(self.journal().turns), 1)
        self.assertEqual(self.kinds().count("auto_dispatch_intent"), 1)
        self.assertEqual(self.kinds().count("auto_dispatch_sent"), 1)
        self.assertEqual(list(self.journal().turns), [d])


class FinishedTurnAcrossARestartTests(Boundary):
    def test_a_turn_that_ended_before_the_daemon_restart_is_validated_after_the_user_continues(self):
        self.setup_run()
        self.tick_until_died(self.after_real_call("_send"))                    # sent, not yet recorded as sent
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["status"]["dispatches"][0]["status"] == "ended",
                      msg="the turn to end")
        pid = self.launched()["pid"]
        self.crash_daemon()
        self.kill_and_reap(pid)
        self.restart_daemon()
        self.fresh_runner()
        before = self.kinds()
        for _ in range(3):
            self.assertEqual(self.runner.tick()[self.fid], "held")            # stopped: nothing is done
        self.assertEqual(self.kinds(), before + ["auto_stopped"])
        self.assertFalse(self.executor_status()["unresolved_failure"])        # it had a result: no failure to release
        self.old_session_after_restart()                                      # the user's order: look, close, then continue
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)
        self.start_executor()                                                  # the user's new executor
        self.finish_to_gate()
        # the finished turn was validated as it was; no second dispatch; one review of that commit
        self.assertEqual(self.kinds().count("auto_dispatch_intent"), 1)
        self.assertEqual(len(self.executor_status()["sessions"][-1]["status"]["dispatches"]), 0)
        self.assertEqual([r["round"] for r in self.reviews()], [1])
        report = next(e for e in flows.get_flow(self.fid)["events"] if e["kind"] == "auto_report")
        self.assertEqual(report["commit"], self.commit)


class ReviewStateTable(Boundary):
    """What the runner does for every state a review job's manifest can be in (S3 design 3, table row 4)."""

    ABORT = "流程被停止，審查中止"

    def run_with(self, entry):
        r = runner_mod.AutomationRunner(self.console.executor, self.console.review)
        recorded = {"events": [], "stops": []}

        class Review:
            def reviews(_self, flow_id):
                return {"reviews": [] if entry is None else [entry]}
        r.review = Review()
        r._event = lambda flow_id, kind, fields: recorded["events"].append((kind, fields))
        r._stop = lambda flow_id, code, detail: recorded["stops"].append(code) or f"stopped:{code}"
        action = r._await_review(self.fid, {"round": 1, "job_id": "r-" + "1" * 16, "commit": "a" * 40})
        return action, recorded

    def entry(self, state, outcome, verdict=None, record="complete", reasons=None):
        return {"job_id": "r-" + "1" * 16, "round": 1, "commit": "a" * 40, "state": state, "outcome": outcome,
                "record": record, "invalid_reasons": reasons,
                "result": {"valid": outcome == "valid", "verdict": verdict} if verdict else None}

    def test_every_state_has_one_action(self):
        cases = [
            # (state, outcome, verdict, record, reasons) -> ("waiting" | ("stop", code) | ("event", kind, ...))
            (("prepared", None), "waiting"),
            (("launching", None), "waiting"),
            (("running", None), "waiting"),
            (("finished", "valid", "PASS"), ("event", "auto_review_result", "PASS")),
            (("finished", "valid", "NEEDS WORK"), ("event", "auto_review_result", "NEEDS WORK")),
            (("finished", "valid", "BLOCKED"), ("event", "auto_review_result", "BLOCKED")),      # then derive says blocked
            (("cleaned", "valid", "PASS"), ("event", "auto_review_result", "PASS")),
            (("cleaned", "valid", "NEEDS WORK"), ("event", "auto_review_result", "NEEDS WORK")),
            (("finished", "valid", "PASS", "absent"), ("stop", "review_record")),
            (("finished", "valid", "MAYBE"), ("stop", "review_verdict")),
            (("invalid", "invalid", None, "absent", ["rollout 不符"]), ("stop", "review_invalid")),
            (("cleaned", "invalid", None, "complete", ["審查逾時"]), ("stop", "review_invalid")),
            (("cleaned", "invalid", None, "complete", [self.ABORT]), ("event", "auto_review_aborted")),
            (("invalid", "invalid", None, "complete", ["x", self.ABORT]), ("event", "auto_review_aborted")),
            (("manual_review", "manual_review"), ("stop", "review_manual")),
            (("cleaned", "manual_review"), ("stop", "review_manual")),
        ]
        for spec, want in cases:
            with self.subTest(spec=spec):
                state, outcome, *rest = spec
                action, rec = self.run_with(self.entry(state, outcome, *rest))
                if want == "waiting":
                    self.assertTrue(action.startswith("waiting:"), action)
                    self.assertEqual((rec["events"], rec["stops"]), ([], []))
                elif want[0] == "stop":
                    self.assertEqual(rec["stops"], [want[1]], (action, rec))
                    self.assertEqual(rec["events"], [])
                else:
                    self.assertEqual(rec["stops"], [])
                    self.assertEqual(len(rec["events"]), 1)
                    self.assertEqual(rec["events"][0][0], want[1])
                    if len(want) > 2:
                        self.assertEqual(rec["events"][0][1]["verdict"], want[2])
        action, rec = self.run_with(None)                                       # a job that is not there at all
        self.assertEqual(rec["stops"], ["review_missing"])
