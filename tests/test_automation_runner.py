"""Phase 3, segment 3 (S3 design 2, 5, 6; v11.1): the runner's loop against a
real daemon, the synthetic Claude and Codex and a real git repository. The
runner is driven tick by tick (its thread is not started); no model."""

import json
import time

from tests.test_flow_review_api import ReviewApiCase
from vbear import flows, tasks
from vbear import runner as runner_mod
from vbear.runtime import pipeline_store

TIMEOUT = 90.0


class RunnerCase(ReviewApiCase):
    def setUp(self):
        super().setUp()
        tasks.save_task(self.tid, {"title": "實作 add()", "workdir": str(self.work), "goal": "完成 add 函式",
                                   "acceptance_criteria": ["單元測試涵蓋邊界"]})
        self.runner = self.console.runner

    def enable(self):
        st, pre = self.call(f"/api/flows/{self.fid}/automation-preview", "POST", {})
        self.assertEqual(st, 200, pre)
        st, r = self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual(st, 200, r)
        return pre

    def kinds(self):
        return [e["kind"] for e in flows.get_flow(self.fid)["events"] if e["kind"].startswith("auto_")]

    def run_until(self, pred, msg, seconds=TIMEOUT):
        end = time.monotonic() + seconds
        seen = []
        while time.monotonic() < end:
            seen.append(self.runner.tick().get(self.fid))
            if pred():
                return seen
            time.sleep(0.15)
        self.fail(f"timed out waiting for {msg}; actions {seen[-8:]}; events {self.kinds()}")

    def last_event(self):
        return flows.get_flow(self.fid)["events"][-1]

    def stop_reason(self):
        return next((e for e in reversed(flows.get_flow(self.fid)["events"]) if e["kind"] == "auto_stopped"), None)


class CycleTests(RunnerCase):
    def test_needs_work_then_a_new_commit_then_pass_stops_at_the_merge_gate(self):
        pre = self.enable()
        self.start_executor()
        self.commit_work("first")
        self.fake_mode("needs_work")
        self.run_until(lambda: "auto_review_result" in self.kinds(), "the first review's result")
        res = [e for e in flows.get_flow(self.fid)["events"] if e["kind"] == "auto_review_result"][-1]
        self.assertEqual((res["verdict"], res["round"]), ("NEEDS WORK", 1))
        # the executor's fix, and a reviewer that now passes
        self.commit_work("fix")
        self.fake_mode("ok")
        self.run_until(lambda: self.last_event()["kind"] == "auto_stopped"
                       and self.last_event()["reason_code"] == "awaiting_merge", "the merge gate")
        kinds = self.kinds()
        self.assertEqual(kinds, ["auto_dispatch_intent", "auto_dispatch_sent", "auto_report", "auto_review_intent",
                                 "auto_review_started", "auto_review_result",
                                 "auto_dispatch_intent", "auto_dispatch_sent", "auto_report", "auto_review_intent",
                                 "auto_review_started", "auto_review_result", "auto_stopped"])
        events = flows.get_flow(self.fid)["events"]
        self.assertTrue(all(e["source"] == "automation" for e in events if e["kind"].startswith("auto_")))
        self.assertEqual([e["verdict"] for e in events if e["kind"] == "auto_review_result"], ["NEEDS WORK", "PASS"])
        # the first dispatch carried the approved plan, the second the review comments as data
        st = self.executor_status()
        sent = {}
        for d in st["sessions"][-1]["status"]["dispatches"]:
            sent[d["dispatch_id"]] = d
        import os
        from vbear.runtime import stream_journal
        fd = os.open(self.base / "sessions" / self.launch, os.O_RDONLY | os.O_DIRECTORY)
        try:
            turns = stream_journal.read(fd).state.turns
        finally:
            os.close(fd)
        self.assertEqual({t.approval["kind"] for t in turns.values()}, {"automation"})
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(turns), 2)
        text_dir = self.base / "pipelines" / self.tid / "dispatches"
        texts = sorted(p.read_text() for p in text_dir.glob("*.txt"))
        self.assertTrue(any(pre["plan_text"] in t and "回報要求" in t for t in texts))
        self.assertTrue(any("審查意見開始" in t and "請依上面標明為資料" in t for t in texts))
        # nothing in the flow was held, and the gate is open for the user
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))
        self.assertTrue(self.gate()["open"])
        self.assertEqual(self.runner.tick()[self.fid], "awaiting_merge")             # idle: nothing more is done
        self.assertEqual(self.kinds().count("auto_stopped"), 1)

    def test_the_runner_never_acts_before_a_session_exists_or_in_manual_mode(self):
        self.assertEqual(self.runner.tick(), {})                                    # manual: no flow of its own
        self.enable()
        self.assertTrue(self.runner.tick()[self.fid].startswith("waiting:"))
        self.assertEqual(self.kinds(), [])
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))


class StopTests(RunnerCase):
    def start_with(self, report=None):
        self.enable()
        self.start_executor()
        self.commit_work("first")
        if report is not None:
            (self.work / "fake-report.json").write_text(json.dumps(report))

    def assertStopped(self, code):
        self.run_until(lambda: self.stop_reason() is not None and pipeline_store.is_held(self.base, self.fid),
                       f"a stop for {code}")
        self.assertEqual(self.stop_reason()["reason_code"], code, self.stop_reason())
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertNotIn("auto_review_intent", self.kinds())

    def test_tests_that_did_not_pass_are_not_sent_to_review(self):
        self.start_with({"tests": {"command": "t", "result": "failed", "summary": "1 failed"}})
        self.assertStopped("tests_not_passed")

    def test_blocked_and_needs_input_reports_stop(self):
        self.start_with({"status": "blocked"})
        self.assertStopped("report_blocked")

    def test_a_report_that_does_not_match_the_files_stops(self):
        self.enable()
        self.start_executor()
        self.commit_work("first", report_head=False)                                # the CLI reports 000...
        self.assertStopped("report_unchecked")

    def test_a_blocked_verdict_stops(self):
        self.enable()
        self.start_executor()
        self.commit_work("first")
        self.fake_mode("blocked")
        self.run_until(lambda: self.stop_reason() is not None, "a stop")
        self.assertEqual(self.stop_reason()["reason_code"], "review_blocked")
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))

    def test_an_invalid_review_stops_and_the_daemon_holds(self):
        self.enable()
        self.start_executor()
        self.commit_work("first")
        self.fake_mode("exit3")
        self.run_until(lambda: self.stop_reason() is not None, "a stop")
        self.assertIn(self.stop_reason()["reason_code"], ("review_invalid", "daemon_hold"))
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))

    def test_a_changed_acceptance_stops_before_anything_is_sent(self):
        self.enable()
        self.start_executor()
        self.commit_work("first")
        self.host.claude = "9.9.9"                                                  # the CLI was updated
        from vbear import risk_acceptance as ra
        ra._facts_cache.clear()
        self.run_until(lambda: self.stop_reason() is not None, "a stop")
        self.assertEqual(self.stop_reason()["reason_code"], "acceptance")
        self.assertNotIn("auto_dispatch_intent", self.kinds())

    def test_a_user_stop_ends_the_loop_and_continue_resumes_it(self):
        self.enable()
        self.start_executor()
        self.commit_work("first")
        self.run_until(lambda: "auto_review_started" in self.kinds(), "a review to start")
        st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
        self.assertEqual(st, 200, r)
        before = self.kinds()
        for _ in range(3):
            self.assertEqual(self.runner.tick()[self.fid], "held")
        self.assertEqual(self.kinds(), before)                                       # the route wrote the stop; no more
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertEqual(self.stop_reason()["reason_code"], "user_stop")
        # the user presses continue (the runner never does): it picks up from the events
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["status"]["state"] == "idle", msg="idle")
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)
        self.run_until(lambda: self.last_event()["kind"] == "auto_stopped"
                       and self.last_event()["reason_code"] != "user_stop", "the loop to finish or stop again")


class DeriveTests(RunnerCase):
    def ev(self, kind, **f):
        return {"kind": kind, "source": "automation", **f}

    def test_every_event_maps_to_one_next_step(self):
        mode = {"kind": "automation_mode", "mode": "auto", "source": "console"}
        d1, j1 = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", "r-" + "1" * 16
        c = "a" * 40
        cases = [
            ([mode], {"step": "first_dispatch"}),
            ([mode, self.ev("auto_dispatch_intent", dispatch_id=d1, text_sha256="b" * 64, length=3)],
             {"step": "resume_dispatch", "dispatch_id": d1}),
            ([mode, self.ev("auto_dispatch_intent", dispatch_id=d1, text_sha256="b" * 64, length=3),
              self.ev("auto_dispatch_sent", dispatch_id=d1)], {"step": "await_turn", "dispatch_id": d1}),
            ([mode, self.ev("auto_report", dispatch_id=d1, commit=c, status="done", tests_result="passed")],
             {"step": "start_review", "commit": c}),
            ([mode, self.ev("auto_review_intent", round=1, commit=c)], {"step": "resume_review", "round": 1}),
            ([mode, self.ev("auto_review_started", round=1, job_id=j1)], {"step": "await_review", "job_id": j1}),
            ([mode, self.ev("auto_review_result", round=1, job_id=j1, commit=c, verdict="NEEDS WORK", valid=True)],
             {"step": "forward", "job_id": j1}),
            ([mode, self.ev("auto_review_result", round=1, job_id=j1, commit=c, verdict="BLOCKED", valid=True)],
             {"step": "blocked"}),
            ([mode, self.ev("auto_review_result", round=1, job_id=j1, commit=c, verdict="PASS", valid=True)],
             {"step": "gate", "announced": False}),
            ([mode, self.ev("auto_review_result", round=1, job_id=j1, commit=c, verdict="PASS", valid=True),
              self.ev("auto_stopped", reason_code="awaiting_merge", detail="x")], {"step": "gate", "announced": True}),
            # a stop is a barrier, not a step: what it interrupted is derived again
            ([mode, self.ev("auto_dispatch_intent", dispatch_id=d1, text_sha256="b" * 64, length=3),
              self.ev("auto_dispatch_sent", dispatch_id=d1), self.ev("auto_stopped", reason_code="x", detail="y")],
             {"step": "await_turn", "dispatch_id": d1}),
            # a new switch-on starts a new cycle
            ([mode, self.ev("auto_report", dispatch_id=d1, commit=c, status="done", tests_result="passed"), mode],
             {"step": "first_dispatch"}),
        ]
        for events, want in cases:
            got = runner_mod.derive(events)
            for k, v in want.items():
                self.assertEqual(got.get(k), v, (events[-1]["kind"], got))

    def test_a_forwarding_intent_remembers_which_review_it_forwards(self):
        mode = {"kind": "automation_mode", "mode": "auto", "source": "console"}
        j1, d2 = "r-" + "1" * 16, "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4e"
        got = runner_mod.derive([mode, self.ev("auto_review_result", round=1, job_id=j1, commit="a" * 40,
                                               verdict="NEEDS WORK", valid=True),
                                 self.ev("auto_dispatch_intent", dispatch_id=d2, text_sha256="c" * 64, length=9)])
        self.assertEqual((got["step"], got["forward_job"]), ("resume_dispatch", j1))


class LockTests(RunnerCase):
    def test_one_runner_per_state_directory(self):
        self.assertTrue(self.runner.acquire())
        other = runner_mod.AutomationRunner(self.console.executor, self.console.review)
        self.assertFalse(other.acquire())
        self.runner.release()
        self.assertTrue(other.acquire())
        other.release()
