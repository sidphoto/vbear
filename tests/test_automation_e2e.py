"""Phase 3, segment 6 (S3 design 10): the acceptance scenarios, with the
synthetic Claude and Codex (no model; the real-model runs come after the
planner has the user's authorisation). The scenarios already covered by the
segment tests are listed in docs/ARCHITECTURE; here are the ones that join
several of them: a second console, a stop during a turn, a daemon restart then
a console restart then the recovery, and a ledger that cannot be rebuilt."""

import os
import time
from unittest import mock

from tests.test_automation_recovery import Boundary
from vbear import flows
from vbear import runner as runner_mod
from vbear.api_error import ApiError
from vbear.runtime import pipeline_store, quota


class E2E(Boundary):
    def residual_processes(self):
        """The review jobs and stream sessions the daemon still holds (none after a clean end)."""
        return {"reviews": sorted(self.dm._reviews), "streams": sorted(self.dm._streams)}


class SecondConsoleTests(E2E):
    def test_another_console_cannot_do_by_hand_what_the_mode_forbids_and_does_not_run_the_flow(self):
        from vbear.server import Console
        self.setup_run()
        second = Console(self.port + 1)
        second.executor.managed_root = self.tmp
        # the runner is one per state directory
        self.assertTrue(self.runner.acquire())
        self.assertFalse(second.runner.acquire())
        self.assertFalse(second.runner.start())
        self.assertIn("runner.lock", second.runner.last_error)
        # the mode is the daemon's: the other instance sees it and is refused too
        with self.assertRaises(ApiError) as cm:
            second.executor.dispatch_preview(self.fid, {"launch_id": self.launch, "text": "手動派工"})
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "automation_active"))
        with self.assertRaises(ApiError) as cm:
            second.review.start(self.fid, {})
        self.assertEqual(cm.exception.code, "automation_active")
        # and a manual approval sent to the daemon directly (a console that did not check) is refused there
        from vbear import daemon_client
        with self.assertRaises(daemon_client.DaemonError):
            daemon_client.call(second.executor.runtime, "dispatch_prepare", launch_id=self.launch, pipeline=self.fid,
                               dispatch_id="0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", text="x",
                               approval={"kind": "preview", "id": "pv-1"})
        with self.assertRaises(daemon_client.DaemonError):
            daemon_client.call(second.executor.runtime, "review_start", pipeline=self.fid, round=9, commit="a" * 40,
                               approval={"kind": "preview", "id": "pv-1"})
        self.runner.release()


class StopDuringATurnTests(E2E):
    def test_after_the_stop_the_turn_finishes_by_itself_and_nothing_follows(self):
        self.enable()
        self.start_executor("slow")                              # the synthetic turn takes about 1.5 s
        self.commit_work("work")
        self.run_until(lambda: "auto_dispatch_sent" in self.kinds(), "the dispatch to be sent")
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["status"]["state"] == "idle", msg="the turn to end")
        turns = self.journal().turns
        self.assertEqual(len(turns), 1)
        self.assertTrue(all(t.status in ("ended",) for t in turns.values()))      # the turn ran to its end
        before = self.kinds()
        for _ in range(5):
            self.assertEqual(self.runner.tick()[self.fid], "held")
            time.sleep(0.1)
        self.assertEqual(self.kinds(), before)                                    # no report, no review, no dispatch
        self.assertNotIn("auto_review_intent", self.kinds())
        self.assertEqual(self.reviews(), [])
        self.assertEqual(self.residual_processes()["reviews"], [])


class RestartThenRecoveryTests(E2E):
    def test_daemon_restart_then_console_restart_then_the_user_recovers(self):
        self.enable()
        self.start_executor("slow")
        self.commit_work("work")
        self.run_until(lambda: "auto_dispatch_sent" in self.kinds(), "the dispatch to be sent")
        old_pid = self.launched()["pid"]
        self.crash_daemon()
        self.kill_and_reap(old_pid)                                # the executor of the old daemon is gone, and waited for
        self.restart_daemon()
        self.fresh_runner()                                        # the console restarts too
        before = self.kinds()
        for _ in range(5):
            self.assertEqual(self.runner.tick()[self.fid], "held")
        self.assertEqual([k for k in self.kinds() if k != "auto_stopped"], [k for k in before if k != "auto_stopped"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertEqual(self.reviews(), [])
        # the user recovers. The old turn has no result, so v29.7 charges its worst case: the whole budget. Continuing
        # needs more room, which is a new acceptance (and so a new approval of the automatic mode).
        s = self.executor_status()
        self.assertTrue(s["unresolved_failure"], s["failures"])
        self.old_session_after_restart()                                            # look at it, close it, then continue
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual((st, r["code"]), (409, "cannot_continue"), r)
        self.assertIn("已用完執行者額度", r["error"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))                 # nothing was released
        old_ids = [e["dispatch_id"] for e in flows.get_flow(self.fid)["events"] if e["kind"] == "auto_dispatch_intent"]
        self.assertEqual(len(old_ids), 1)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})[0], 200)
        st, pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {"limits": {"executor_budget_usd": 40}})
        self.assertEqual(st, 200, pre)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})[0], 200)
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)
        st, pre = self.call(f"/api/flows/{self.fid}/automation-preview", "POST", {"limits": {"executor_budget_usd": 40}})
        self.assertEqual(st, 200, pre)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})[0], 200)
        self.start_executor("ok")                                                   # a new executor: the user's
        self.commit_work("after the restart")
        self.finish_to_gate()
        # the dispatch without a result was not sent again; the new cycle made its own, and it passed
        new_ids = [e["dispatch_id"] for e in flows.get_flow(self.fid)["events"] if e["kind"] == "auto_dispatch_intent"]
        self.assertEqual(len(new_ids), 2)
        in_new_session = [d["dispatch_id"] for d in self.executor_status()["sessions"][-1]["status"]["dispatches"]]
        self.assertEqual(in_new_session, [new_ids[1]])
        self.assertEqual([r["round"] for r in self.reviews()], [1])


class LedgerTests(E2E):
    def test_a_ledger_that_cannot_be_rebuilt_stops_the_flow_with_the_reason(self):
        self.enable()
        self.start_executor()
        self.commit_work("work")
        self.dm._ledger.used = None                                # as after a failed rebuild
        self.dm._ledger.problem = "額度無法核算，需要人工檢查（測試）"
        with mock.patch.object(quota, "scan", side_effect=quota.ScanFailed("測試")):
            self.run_until(lambda: self.stop_reason() is not None, "a stop")
        self.assertEqual(self.stop_reason()["reason_code"], "dispatch_refused")
        self.assertIn("額度", self.stop_reason()["detail"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertEqual(self.journal().turns, {})


class WholeRunEvidenceTests(E2E):
    def test_every_event_is_marked_and_nothing_is_left_running(self):
        self.setup_run("needs_work")
        self.run_until(lambda: "auto_review_result" in self.kinds(), "the first verdict")
        self.commit_work("fix")
        self.fake_mode("ok")
        self.finish_to_gate()
        events = flows.get_flow(self.fid)["events"]
        sources = {e["kind"]: e["source"] for e in events}
        self.assertEqual(sources["automation_mode"], "console")
        self.assertEqual(sources["risk_acknowledged"], "console")
        self.assertTrue(all(e["source"] == "automation" for e in events if e["kind"].startswith("auto_")))
        # the reviews: valid, whole records; the daemon holds nothing
        for r in self.reviews():
            self.assertEqual((r["outcome"], r["record"], r["state"]), ("valid", "complete", "cleaned"))
        self.assertEqual(self.residual_processes()["reviews"], [])
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))
        # the runner never released anything and never started a session
        self.assertEqual(len(self.executor_status()["sessions"]), 1)
        self.assertFalse((self.base / "holds" / self.fid).exists())
