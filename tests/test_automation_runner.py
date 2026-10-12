"""Phase 3, segment 3 (S3 design 2, 5, 6; v11.1): the runner's loop against a
real daemon, the synthetic Claude and Codex and a real git repository. The
runner is driven tick by tick (its thread is not started); no model."""

import json
import os
import time

from tests.test_flow_review_api import ReviewApiCase
from vbear import executor_report, flows, tasks
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
        # every text ends with the fixed report request that names ITS OWN dispatch id (the file's name): the
        # synthetic CLI reported for the turns only because of it
        for p in text_dir.glob("*.txt"):
            self.assertTrue(p.read_text().endswith(executor_report.report_request(p.stem)), p.name)
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


class PhaseTests(RunnerCase):
    """The flow page's phase follows the automatic cycle by itself (S3 alignment item 8), and the user's
    attention list is still the automation's own: stopped or at the merge gate, nothing in between."""

    def view(self):
        st, v = self.call(f"/api/flows/{self.fid}")
        self.assertEqual(st, 200, v)
        return v["flow"]

    def test_the_phase_follows_approval_dispatch_report_review_fix_and_the_gate(self):
        with flows.store.locked():                                   # the page can compare HEAD with the review
            data = flows.store.load()
            data[self.fid]["roles"]["executor"]["workdir"] = str(self.work)
            flows.store.save(data)
        self.assertEqual(self.view()["phase"]["key"], "planning")
        self.enable()
        v = self.view()
        self.assertEqual((v["phase"]["key"], v["attention"]), ("implementing", False))
        self.start_executor()
        self.commit_work("first")
        self.fake_mode("needs_work")
        self.run_until(lambda: "auto_review_result" in self.kinds(), "the first review's result")
        v = self.view()
        self.assertEqual((v["phase"]["key"], v["phase"]["round"], v["attention"]), ("needs_fix", 1, False))
        self.commit_work("fix")
        self.fake_mode("ok")
        self.run_until(lambda: self.last_event()["kind"] == "auto_stopped"
                       and self.last_event()["reason_code"] == "awaiting_merge", "the merge gate")
        v = self.view()
        self.assertEqual((v["phase"]["key"], v["phase"]["round"]), ("awaiting_merge", 2))
        self.assertEqual([len(r["reviews"]) for r in v["rounds"]], [1, 1])
        self.assertEqual((v["warnings"], v["stray_reviews"]), ([], []))
        # the attention list says what the automation says, as before
        self.assertTrue(v["attention"])
        self.assertEqual(v["attention_reason"], "自動執行完成：審查通過、各項核對成立，停在合併關卡等你")
        st, listing = self.call("/api/flows")
        mine = next(f for f in listing["flows"] if f["id"] == self.fid)
        self.assertEqual((mine["attention"], mine["attention_reason"]), (True, v["attention_reason"]))
        # and the merge gate itself is what it was: the same checks, not the phase
        self.assertTrue(self.gate()["open"])


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
        # the user presses continue (the runner never does) once the stopped review has ended (it is invalid
        # then: pressing earlier is refused, because that review would hold the flow again when it ends)
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["status"]["state"] == "idle", msg="idle")
        self.wait_for(lambda: self.reviews() and self.reviews()[-1]["state"] in ("cleaned", "manual_review"),
                      msg="the stopped review to end")
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


class EventWriteTests(RunnerCase):
    def test_when_an_event_cannot_be_written_the_flow_is_stopped_not_continued(self):
        from unittest import mock
        self.enable()
        self.start_executor()
        self.commit_work("work")
        real = flows.append_automation_event

        def refuse_intents(flow_id, kind, fields):
            if kind == "auto_dispatch_intent":
                raise ValueError("這個流程的事件已達上限")
            return real(flow_id, kind, fields)
        with mock.patch.object(flows, "append_automation_event", refuse_intents):
            action = self.runner.tick()[self.fid]
        self.assertTrue(action.startswith("stopped:"), action)
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertNotIn("auto_dispatch_intent", self.kinds())
        self.assertEqual(len(self.executor_status()["sessions"][-1]["status"]["dispatches"]), 0)


class ModeEventTests(RunnerCase):
    def test_a_mode_that_the_timeline_does_not_account_for_is_not_acted_on(self):
        # on in the daemon, with a valid approval, but no automation_mode event (the write that failed)
        pre = self.call(f"/api/flows/{self.fid}/automation-preview", "POST", {})[1]
        from unittest import mock
        with mock.patch.object(flows, "append_automation_event", side_effect=OSError(5, "io")):
            self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
        # the flow was held by the confirmation; the user continues, as they would
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "auto")
        self.start_executor()
        self.commit_work("work")
        action = self.runner.tick()[self.fid]
        self.assertEqual(action, "stopped:mode_event_missing")
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertNotIn("auto_dispatch_intent", self.kinds())
        self.assertEqual(self.stop_reason()["reason_code"], "mode_event_missing")


class ApprovalRaceTests(RunnerCase):
    def test_a_runner_that_sees_an_approval_half_done_waits_it_does_not_stop_the_flow(self):
        """The daemon has switched the mode and the console has not yet written the timeline's record: the runner,
        looking in that window, must wait (the approval holds the lock), not conclude and stop."""
        from unittest import mock
        from vbear import automation
        st, pre = self.call(f"/api/flows/{self.fid}/automation-preview", "POST", {})
        self.assertEqual(st, 200, pre)
        seen = {}
        real = flows.append_automation_event

        def barrier(flow_id, kind, fields):
            if kind == "automation_mode" and fields["mode"] == "auto":
                seen["action"] = self.runner.step(self.fid)              # the runner looks right here
                seen["mode"] = pipeline_store.mode_info(self.base, self.fid)["mode"]
                seen["events"] = [e["kind"] for e in flows.get_flow(self.fid)["events"]]
            return real(flow_id, kind, fields)
        with mock.patch.object(automation.flows, "append_automation_event", barrier):
            st, r = self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual(st, 200, r)
        self.assertEqual(seen["mode"], "auto")                                # the window was real
        self.assertNotIn("automation_mode", seen["events"])
        self.assertTrue(seen["action"].startswith("waiting:"), seen["action"])
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))
        self.assertIsNone(self.stop_reason())
        # and once the approval is whole, the runner proceeds as usual
        self.assertTrue(self.runner.step(self.fid).startswith("waiting:"))     # (no session yet: nothing to do)
        self.assertIsNone(self.stop_reason())


class LockInodeTests(RunnerCase):
    def test_an_approval_that_waited_while_the_directory_was_taken_away_is_refused(self):
        import fcntl
        import threading
        from vbear import automation
        from vbear.api_error import ApiError
        from unittest import mock
        automation.write_plan(self.base, self.fid, "計畫")
        lock = self.base / "automation" / self.fid / ".lock"
        holder = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(holder, fcntl.LOCK_EX)                                   # another console holds it
        out = {}
        blocked = threading.Event()
        real_flock = fcntl.flock

        def flock(fd, op):
            try:
                return real_flock(fd, op)
            except BlockingIOError:
                blocked.set()                                                # the waiter has really met the lock
                raise

        def waiter():
            try:
                with automation.plan_lock(self.base, self.fid):
                    out["got"] = True
            except ApiError as exc:
                out["error"] = (exc.status, exc.code)
        with mock.patch.object(automation.fcntl, "flock", flock):
            t = threading.Thread(target=waiter)
            t.start()
            self.assertTrue(blocked.wait(10), "the waiter never reached the lock")
        self.assertEqual(out, {})
        moved = self.tmp / "taken-away"
        os.rename(self.base / "automation" / self.fid, moved)                # the deletion moved the directory
        os.close(holder)                                                     # the lock is released
        t.join(10)
        self.assertEqual(out.get("error"), (409, "deleting"), out)
        self.assertNotIn("got", out)
        self.assertFalse((self.base / "automation" / self.fid / "plan.txt").exists())

    def test_an_approval_for_a_flow_that_is_gone_is_refused_under_the_lock(self):
        from vbear import automation
        from vbear.api_error import ApiError
        automation.write_plan(self.base, self.fid, "計畫")
        with mock_flow_gone(self.fid):
            with self.assertRaises(ApiError) as cm:
                with automation.plan_lock(self.base, self.fid):
                    pass
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "no_flow"))


def mock_flow_gone(flow_id):
    from unittest import mock
    return mock.patch.object(flows, "get_flow", side_effect=KeyError(flow_id))


class StaleSnapshotTests(RunnerCase):
    """The S3-5 review, round 2: no stop is concluded from reads that an approval in progress could have made
    stale; the lock is taken, the reads are made again, and only what still disagrees stops the flow."""

    def make_auto_flow(self):
        self.enable()
        self.start_executor()
        self.commit_work("work")

    def test_a_disagreement_that_the_second_read_does_not_confirm_is_not_a_stop(self):
        from unittest import mock
        self.make_auto_flow()
        real = runner_mod.AutomationRunner._checked
        calls = []

        def stale_first(self_, flow_id):
            calls.append(1)
            if len(calls) == 1:                                   # what a read racing an approval would have seen
                return None, ("approval", "找不到自動執行核准的那一筆接受")
            return real(self_, flow_id)
        with mock.patch.object(runner_mod.AutomationRunner, "_checked", stale_first):
            action = self.runner.step(self.fid)
        self.assertEqual(len(calls), 2)                           # read again, under the lock
        self.assertFalse(action.startswith("stopped:"), action)
        self.assertIsNone(self.stop_reason())
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))

    def test_a_disagreement_that_the_second_read_confirms_is_a_stop_with_its_own_reason(self):
        from unittest import mock
        self.make_auto_flow()
        with mock.patch.object(runner_mod.AutomationRunner, "_checked",
                               return_value=(None, ("acceptance", "風險接受目前不算數（測試）"))):
            action = self.runner.step(self.fid)
        self.assertEqual(action, "stopped:acceptance")
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))

    def test_a_newer_acceptance_than_the_one_the_mode_was_approved_with_is_a_stop(self):
        self.make_auto_flow()
        self.accept()                                             # a later acceptance appears (not by the console's route)
        action = self.runner.step(self.fid)
        self.assertEqual(action, "stopped:approval_replaced")

    def make_disagreeing_flow(self):
        """A flow whose timeline lacks the switch-on record (so the first read disagrees)."""
        from unittest import mock
        pre = self.call(f"/api/flows/{self.fid}/automation-preview", "POST", {})[1]
        with mock.patch.object(flows, "append_automation_event", side_effect=OSError(5, "io")):
            self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)

    def test_a_lock_file_that_is_not_there_is_a_stop_not_an_approval_in_progress(self):
        self.make_disagreeing_flow()
        (self.base / "automation" / self.fid / ".lock").unlink()
        self.assertEqual(self.runner.step(self.fid), "stopped:approval_lock_unavailable")
        self.assertIn("鎖檔", self.stop_reason()["detail"])

    def test_a_directory_that_is_not_there_is_a_stop(self):
        import shutil
        self.make_disagreeing_flow()
        shutil.rmtree(self.base / "automation" / self.fid)
        self.assertEqual(self.runner.step(self.fid), "stopped:approval_lock_unavailable")

    def test_a_lock_that_is_not_a_plain_file_of_ours_is_a_stop(self):
        self.make_disagreeing_flow()
        lock = self.base / "automation" / self.fid / ".lock"
        lock.unlink()
        os.symlink(self.work, lock)                               # a link where the lock file should be
        self.assertEqual(self.runner.step(self.fid), "stopped:approval_lock_unavailable")

    def test_an_approval_that_never_ends_is_waited_for_a_while_and_then_stopped(self):
        import fcntl
        self.make_disagreeing_flow()
        lock = self.base / "automation" / self.fid / ".lock"
        fd = os.open(lock, os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)                            # an approval that has been inside its unit
        now = [1000.0]
        self.runner.monotonic = lambda: now[0]
        try:
            self.assertTrue(self.runner.step(self.fid).startswith("waiting:"))
            now[0] += runner_mod.BUSY_LIMIT_S - 1
            self.assertTrue(self.runner.step(self.fid).startswith("waiting:"))      # still within the limit
            now[0] += 2
            self.assertEqual(self.runner.step(self.fid), "stopped:approval_stuck")
        finally:
            os.close(fd)
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
