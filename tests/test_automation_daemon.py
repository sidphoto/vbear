"""Phase 3, segment 1 (S3 design 2, 3, v11.1): the flow's mode in the daemon,
the approvals it accepts in each mode, the stop at a daemon restart, and the
event kinds the runner will write. Synthetic Claude CLI; no model."""

import json
import os
import time
import unittest

from tests import stream_fixtures as fx
from tests.test_runtimed_stream import StreamCase
from vbear import acceptance as acc
from vbear import flows
from vbear.runtime import daemon as d
from vbear.runtime import flow_data, pipeline_store


class AutoCase(StreamCase):
    def accept_auto(self, plan_text="計畫全文", write_plan=True, **override):
        """An acceptance that also approves the plan: the nine fields and the four automation ones, and the plan
        file those name (the daemon reads it again before it switches the mode on)."""
        import hashlib
        from vbear import login_identity
        raw = plan_text.encode()
        if write_plan:
            d = self.base / "automation" / self.fid
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d.parent, 0o700)
            os.chmod(d, 0o700)
            (d / "plan.txt").write_bytes(raw)
            os.chmod(d / "plan.txt", 0o600)
        override.setdefault("plan_sha256", hashlib.sha256(raw).hexdigest())
        override.setdefault("plan_bytes", len(raw))
        fp = login_identity.claude_login_fingerprint(self.home / ".claude.json", self.key).hmac
        fields = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
                  "executor_claude_version": "2.1.292", "executor_model": fx.MODEL,
                  "executor_login_fingerprint": fp, "login_fingerprint": "b" * 64, "login_key_id": self.key.key_id,
                  "limits": {**acc.DEFAULT_LIMITS, "max_elapsed_h": 4},
                  "auto_text_version": acc.AUTO_RISK_TEXT_VERSION, "automation_scope": list(acc.AUTO_SCOPE),
                  **override}
        with flows.store.locked():
            data = flows.store.load()
            ev = data[self.fid]["events"]
            seq = len(ev) + 1
            ev.append({"seq": seq, "at": time.time(), "kind": "risk_acknowledged", "source": "console", "note": "",
                       **fields})
            flows.store.save(data)
        return seq

    def set_mode(self, mode, seq=None, **kw):
        approval = {"kind": "automation", "id": f"auto-{seq}"} if seq is not None else None
        fields = {"pipeline": self.fid, "mode": mode, **kw}
        if approval is not None or mode == "auto":
            fields["approval"] = approval
        return self.rpc("pipeline_mode_set", **fields)

    def prepare_with(self, launch_id, approval, text="請完成工作"):
        return self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=fx.new_uuid(),
                        text=text, approval=approval)


class ModeSetTests(AutoCase):
    def test_manual_is_the_default_and_automation_approvals_are_refused_in_it(self):
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")
        launch, _ = self.open()
        r = self.prepare_with(launch, {"kind": "automation", "id": "auto-1"})
        self.assertFalse(r["ok"], r)
        self.assertIn("手動模式", r["error"]["message"])
        r = self.prepare_with(launch, {"kind": "preview", "id": "pv-1"})
        self.assertTrue(r["ok"], r)

    def test_switching_on_needs_the_acceptance_that_approved_the_plan(self):
        r = self.set_mode("auto", seq=1)                         # the fixture's acceptance has no automation fields
        self.assertFalse(r["ok"], r)
        self.assertIn("自動執行風險文字不符", r["error"]["message"])
        seq = self.accept_auto()
        for approval in (None, {"kind": "preview", "id": f"auto-{seq}"}, {"kind": "automation", "id": "x"},
                         {"kind": "automation", "id": f"auto-{seq}", "extra": 1}):
            r = self.rpc("pipeline_mode_set", pipeline=self.fid, mode="auto", approval=approval)
            self.assertEqual(r["error"]["code"], "bad_request", (approval, r))
        r = self.set_mode("auto", seq=seq + 7)                   # an event that does not exist
        self.assertFalse(r["ok"], r)
        r = self.set_mode("auto", seq=seq)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"], {"pipeline": self.fid, "mode": "auto", "approval_id": f"auto-{seq}"})
        info = pipeline_store.mode_info(self.base, self.fid)
        self.assertEqual((info["mode"], info["approval_id"], info["problem"]), ("auto", f"auto-{seq}", None))
        self.assertEqual(oct((self.base / "modes" / self.fid).stat().st_mode & 0o777), "0o600")

    def test_an_old_automation_text_version_is_not_accepted(self):
        seq = self.accept_auto(auto_text_version="2026-10-08.1")
        r = self.set_mode("auto", seq=seq)
        self.assertFalse(r["ok"], r)
        self.assertIn("與目前的自動執行風險文字不符", r["error"]["message"])

    def test_it_must_be_the_newest_valid_acceptance(self):
        seq = self.accept_auto()
        self.accept()                                            # a later acceptance (without automation fields)
        r = self.set_mode("auto", seq=seq)
        self.assertFalse(r["ok"], r)
        self.assertIn("取代", r["error"]["message"])

    def test_a_stopped_flow_or_an_unreleased_failure_cannot_be_switched_on(self):
        seq = self.accept_auto()
        self.assertTrue(self.rpc("pipeline_hold", pipeline=self.fid, reason="x")["ok"])
        r = self.set_mode("auto", seq=seq)
        self.assertFalse(r["ok"], r)
        self.assertIn("已停止", r["error"]["message"])
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        # an unreleased failure: the hold file is gone (lost) but the failure is on disk (v29.8)
        launch, _ = self.open("exit")
        self.dispatch(launch)
        self.wait_for(lambda: pipeline_store.is_held(self.base, self.fid), msg="the failure to hold the flow")
        self.rpc("stream_close", launch_id=launch)
        self.wait_for(lambda: self.manifest(launch)["state"] in ("ended", "manual_review"), msg="closed")
        os.unlink(self.base / "holds" / self.fid)
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))
        r = self.set_mode("auto", seq=seq)
        self.assertFalse(r["ok"], r)
        self.assertTrue("尚未解除的失敗" in r["error"]["message"] or "失敗" in r["error"]["message"], r)
        self.assertFalse((self.base / "modes" / self.fid).exists())

    def test_switching_back_is_only_for_a_stopped_flow(self):
        seq = self.accept_auto()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        r = self.set_mode("manual")
        self.assertFalse(r["ok"], r)
        self.assertIn("已停止", r["error"]["message"])
        self.assertTrue(self.rpc("pipeline_hold", pipeline=self.fid, reason="user")["ok"])
        r = self.set_mode("manual", approval=None)
        self.assertTrue(r["ok"], r)
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")
        self.assertFalse((self.base / "modes" / self.fid).exists())
        self.assertEqual(self.rpc("pipeline_mode_set", pipeline=self.fid, mode="manual",
                                  approval={"kind": "automation", "id": "auto-1"})["error"]["code"], "bad_request")


class EnforcementTests(AutoCase):
    def test_in_auto_only_the_approval_the_mode_was_switched_on_with_is_accepted(self):
        seq = self.accept_auto()
        launch, _ = self.open()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        r = self.prepare_with(launch, {"kind": "preview", "id": "pv-1"})
        self.assertFalse(r["ok"], r)
        self.assertIn("手動派工與手動審查一律拒絕", r["error"]["message"])
        r = self.prepare_with(launch, {"kind": "automation", "id": f"auto-{seq + 1}"})
        self.assertFalse(r["ok"], r)
        r = self.prepare_with(launch, {"kind": "automation", "id": f"auto-{seq}"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.journal(launch).state.turns[r["result"]["dispatch_id"]].approval,
                         {"kind": "automation", "id": f"auto-{seq}"})

    def test_a_review_start_follows_the_mode_too(self):
        seq = self.accept_auto()
        self.open()
        base = dict(pipeline=self.fid, round=1, commit="a" * 40)
        r = self.rpc("review_start", **base, approval={"kind": "automation", "id": f"auto-{seq}"})
        self.assertIn("手動模式", r["error"]["message"])                 # manual mode: an automation approval is refused
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        for approval in (None, {"kind": "preview", "id": "pv-1"}, {"kind": "automation", "id": f"auto-{seq + 1}"}):
            r = self.rpc("review_start", **base, **({"approval": approval} if approval else {}))
            self.assertFalse(r["ok"], r)
            self.assertIn("一律拒絕", r["error"]["message"])
        r = self.rpc("review_start", **base, approval={"kind": "automation", "id": f"auto-{seq}"})
        self.assertFalse(r["ok"], r)                                    # past the gate, refused by something else
        self.assertNotIn("一律拒絕", r["error"]["message"])
        self.assertNotIn("手動模式", r["error"]["message"])
        r = self.rpc("review_start", pipeline=self.fid, round=1, commit="a" * 40, approval="x")
        self.assertEqual(r["error"]["code"], "bad_request")

    def test_a_newer_acceptance_ends_the_automation_approval(self):
        seq = self.accept_auto()
        launch, _ = self.open()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        self.accept()                                                   # the limits were re-accepted by hand
        r = self.prepare_with(launch, {"kind": "automation", "id": f"auto-{seq}"})
        self.assertFalse(r["ok"], r)
        self.assertIn("取代", r["error"]["message"])

    def test_an_unreadable_mode_record_is_auto_with_no_approval_that_can_match(self):
        seq = self.accept_auto()
        launch, _ = self.open()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        (self.base / "modes" / self.fid).write_text("{")
        info = pipeline_store.mode_info(self.base, self.fid)
        self.assertEqual((info["mode"], info["approval_id"]), ("auto", None))
        self.assertTrue(info["problem"])
        r = self.prepare_with(launch, {"kind": "automation", "id": f"auto-{seq}"})
        self.assertFalse(r["ok"], r)
        self.assertIn("模式紀錄不可信", r["error"]["message"])
        r = self.prepare_with(launch, {"kind": "preview", "id": "pv-1"})
        self.assertFalse(r["ok"], r)                                    # and it is not manual either


class RestartTests(AutoCase):
    def test_a_restart_stops_every_automatic_flow_before_any_request(self):
        seq = self.accept_auto()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))
        self.crash_daemon()
        self.restart_daemon()
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        info = pipeline_store.hold_info(self.base, self.fid)
        self.assertEqual(info["reason"], "daemon 重啟")
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "auto")      # the mode stays
        r = self.rpc("pipeline_mode_set", pipeline=self.fid, mode="auto",
                     approval={"kind": "automation", "id": f"auto-{seq}"})
        self.assertIn("已停止", r["error"]["message"])

    def test_a_manual_flow_is_not_stopped_by_a_restart(self):
        self.crash_daemon()
        self.restart_daemon()
        self.assertFalse(pipeline_store.is_held(self.base, self.fid))

    def test_an_unreadable_mode_record_is_stopped_with_the_reason(self):
        seq = self.accept_auto()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        (self.base / "modes" / self.fid).write_text("{")
        self.crash_daemon()
        self.restart_daemon()
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertIn("模式紀錄不可信", pipeline_store.hold_info(self.base, self.fid)["reason"])

    def test_a_mode_directory_that_cannot_be_understood_means_the_daemon_does_not_start(self):
        self.crash_daemon()
        (self.base / "modes").mkdir(mode=0o700, exist_ok=True)
        (self.base / "modes" / "not-a-flow").write_text("x")
        dm = d.Daemon(self.base, log=self.logs.append)
        with self.assertRaises(d.RuntimedError) as cm:
            dm.start()
        self.assertIn("無法判斷哪些流程是自動執行", str(cm.exception))
        (self.base / "modes" / "not-a-flow").unlink()
        self.restart_daemon()                                          # and with it gone it starts again


class EventSchemaTests(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        from unittest import mock
        from vbear import tasks
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.tmp)})
        env.start()
        self.addCleanup(env.stop)
        tid = tasks.save_task(None, {"title": "t"})["id"]
        roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
                 "reviewers": [{"name": "c", "family": "openai"}]}
        self.fid = flows.create_flow({"task_id": tid, "roles": roles}, lambda t: True)["id"]

    def test_the_runners_events_have_fixed_fields_and_a_source(self):
        uid = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
        ok = [("auto_dispatch_intent", {"dispatch_id": uid, "text_sha256": "a" * 64, "length": 100}),
              ("auto_dispatch_sent", {"dispatch_id": uid}),
              ("auto_report", {"dispatch_id": uid, "commit": "b" * 40, "status": "done", "tests_result": "passed"}),
              ("auto_review_intent", {"round": 1, "commit": "b" * 40}),
              ("auto_review_started", {"round": 1, "job_id": "r-" + "1" * 16}),
              ("auto_review_result", {"round": 1, "job_id": "r-" + "1" * 16, "commit": "b" * 40,
                                      "verdict": "NEEDS WORK", "valid": True}),
              ("auto_stopped", {"reason_code": "head_unchanged", "detail": "HEAD 沒有改變"})]
        for kind, fields in ok:
            e = flows.append_automation_event(self.fid, kind, fields)
            self.assertEqual(e["source"], "automation")
            self.assertEqual(e["kind"], kind)
        flows.append_event  # (manual route stays closed to these kinds, below)
        flow = flows.get_flow(self.fid)
        self.assertEqual([e["seq"] for e in flow["events"]], list(range(1, len(ok) + 1)))
        view_events = flows.view(flow, heads=lambda w: {"commit": None, "error": "x"}, task_title=lambda t: "t",
                                 live=None, now=time.time())["events"]
        self.assertTrue(all(e["source_label"] == flows.AUTOMATION_LABEL for e in view_events))

    def test_bad_fields_and_wrong_sources_are_refused(self):
        uid = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
        bad = [("auto_dispatch_intent", {"dispatch_id": "x", "text_sha256": "a" * 64, "length": 100}),
               ("auto_dispatch_intent", {"dispatch_id": uid, "text_sha256": "a" * 64, "length": 70000}),
               ("auto_dispatch_intent", {"dispatch_id": uid, "text_sha256": "a" * 64}),
               ("auto_report", {"dispatch_id": uid, "commit": "b" * 40, "status": "maybe", "tests_result": "passed"}),
               ("auto_review_started", {"round": 0, "job_id": "r-" + "1" * 16}),
               ("auto_review_result", {"round": 1, "job_id": "r-" + "1" * 16, "commit": "b" * 40,
                                       "verdict": "PASS", "valid": "yes"}),
               ("auto_stopped", {"reason_code": "Has Space", "detail": "x"}),
               ("automation_mode", {"mode": "auto", "approval_seq": 5}),         # an acceptance that is not there yet
               ("automation_mode", {"mode": "manual", "approval_seq": 1}),
               ("note", {"note": "x"})]
        for kind, fields in bad:
            with self.assertRaises(ValueError, msg=(kind, fields)):
                flows.append_automation_event(self.fid, kind, fields)
        self.assertEqual(flows.get_flow(self.fid)["events"], [])
        for kind in flows.AUTOMATION_KINDS + ("automation_mode", "risk_acknowledged"):      # no manual route writes them
            with self.assertRaises(ValueError):
                flows.append_event(self.fid, {"kind": kind, "note": ""})

    def test_an_acceptance_has_all_four_automation_fields_or_none(self):
        base = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
                "executor_claude_version": "2.1.292", "executor_model": fx.MODEL, "executor_login_fingerprint": "a" * 64,
                "login_fingerprint": "b" * 64, "login_key_id": "c" * 16, "limits": dict(acc.DEFAULT_LIMITS)}
        auto = {"auto_text_version": acc.AUTO_RISK_TEXT_VERSION, "automation_scope": list(acc.AUTO_SCOPE),
                "plan_sha256": "d" * 64, "plan_bytes": 10}
        self.assertIsNone(acc.record_problem(base))
        self.assertIsNone(acc.record_problem({**base, **auto}))
        for drop in auto:
            partial = {**base, **{k: v for k, v in auto.items() if k != drop}}
            self.assertIsNotNone(acc.record_problem(partial), drop)
        self.assertIsNotNone(acc.record_problem({**base, **auto, "automation_scope": ["dispatch"]}))
        self.assertIsNotNone(acc.record_problem({**base, **auto, "plan_bytes": 0}))
        self.assertIsNotNone(acc.record_problem({**base, **auto, "plan_bytes": acc.PLAN_MAX_BYTES + 1}))
        self.assertIsNotNone(acc.record_problem({**base, **auto, "plan_sha256": "xyz"}))
        flows.append_risk_acknowledged(self.fid, {**base, **auto})
        with self.assertRaises(ValueError):
            flows.append_risk_acknowledged(self.fid, {**base, "plan_sha256": "d" * 64})
        ev = flows.get_flow(self.fid)["events"][0]
        self.assertTrue(acc.is_auto_event(ev))
        self.assertEqual(acc.approval_id(ev), "auto-1")


class DeletionInterplayTests(AutoCase):
    def test_an_automatic_flow_is_not_deletable_and_its_records_go_with_a_deletion(self):
        seq = self.accept_auto()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        pl = flow_data.plan(self.base, self.fid, self.tid)
        self.assertTrue(pl.auto)
        self.assertTrue(any("自動執行模式" in x for x in flow_data.blockers(pl)))
        # stop and switch back: now only the stop marker is left to say no
        self.assertTrue(self.rpc("pipeline_hold", pipeline=self.fid, reason="u")["ok"])
        self.assertTrue(self.set_mode("manual")["ok"])
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        pl = flow_data.plan(self.base, self.fid, self.tid)          # accept_auto() wrote automation/<flow>/plan.txt
        self.assertFalse(pl.auto)
        self.assertEqual(flow_data.blockers(pl), [])
        self.assertEqual(pl.automation_bytes, len("計畫全文".encode()))
        flow_data.remove(self.base, pl)
        self.assertFalse((self.base / "automation" / self.fid).exists())
        self.assertEqual(os.listdir(self.base / "deleting" / self.fid), [])      # the marker stays until finish()
        self.assertTrue(flow_data.finish(self.base, self.fid))
        self.assertFalse((self.base / "deleting" / self.fid).exists())

    def test_a_mode_record_left_by_a_begun_deletion_is_removed_with_it(self):
        seq = self.accept_auto()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        pl = flow_data.plan(self.base, self.fid, self.tid)
        flow_data.remove(self.base, pl)                  # the caller checked the blockers; a begun deletion finishes
        self.assertFalse((self.base / "modes" / self.fid).exists())

    def test_a_foreign_file_in_the_plan_directory_refuses(self):
        (self.base / "automation" / self.fid).mkdir(parents=True, mode=0o700)
        os.chmod(self.base / "automation", 0o700)
        (self.base / "automation" / self.fid / "other").write_text("x")
        with self.assertRaises(flow_data.FlowDataRefused):
            flow_data.plan(self.base, self.fid, self.tid)


if __name__ == "__main__":
    unittest.main()


class LiveCheckTests(AutoCase):
    """S3 final review: in automatic mode the daemon looks at the executor's account and CLI now, before the
    prepare and again before the send, and judges the approval again before the send."""

    def switch_on(self):
        seq = self.accept_auto()
        launch, _ = self.open()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        return seq, launch

    def change_account(self):
        (self.home / ".claude.json").write_text(json.dumps({"oauthAccount": {
            "accountUuid": "99999999-2222-3333-4444-555555555555",
            "organizationUuid": "66666666-7777-8888-9999-000000000000"}}))

    def prepared(self, launch, seq):
        d = fx.new_uuid()
        r = self.rpc("dispatch_prepare", launch_id=launch, pipeline=self.fid, dispatch_id=d, text="請完成工作",
                     approval={"kind": "automation", "id": f"auto-{seq}"})
        return d, r

    def test_a_changed_account_before_the_prepare_is_refused_and_stops_the_flow(self):
        seq, launch = self.switch_on()
        self.change_account()
        d, r = self.prepared(launch, seq)
        self.assertFalse(r["ok"], r)
        self.assertIn("帳號", r["error"]["message"])
        self.assertIn("流程已停止", r["error"]["message"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertIn("自動執行停止", pipeline_store.hold_info(self.base, self.fid)["reason"])
        self.assertEqual(self.journal(launch).state.turns, {})                       # nothing was written

    def test_a_changed_account_between_the_prepare_and_the_send_is_refused_and_stops_the_flow(self):
        seq, launch = self.switch_on()
        d, r = self.prepared(launch, seq)
        self.assertTrue(r["ok"], r)
        self.change_account()
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertFalse(r["ok"], r)
        self.assertIn("帳號", r["error"]["message"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertEqual(self.journal(launch).state.turns[d].status, "accepted")      # never written to the CLI
        self.assertFalse(self.dm._streams[launch].writing)

    def test_a_newer_acceptance_between_the_prepare_and_the_send_is_refused(self):
        seq, launch = self.switch_on()
        d, r = self.prepared(launch, seq)
        self.assertTrue(r["ok"], r)
        self.accept()                                                          # a manual acceptance replaces it
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertFalse(r["ok"], r)
        self.assertIn("取代", r["error"]["message"])
        self.assertEqual(self.journal(launch).state.turns[d].status, "accepted")

    def test_a_changed_plan_file_between_the_prepare_and_the_send_is_refused(self):
        seq, launch = self.switch_on()
        d, r = self.prepared(launch, seq)
        self.assertTrue(r["ok"], r)
        plan = self.base / "automation" / self.fid / "plan.txt"
        plan.write_text(plan.read_text() + "x")
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertFalse(r["ok"], r)
        self.assertIn("plan.txt", r["error"]["message"])
        self.assertEqual(self.journal(launch).state.turns[d].status, "accepted")

    def test_everything_unchanged_sends(self):
        seq, launch = self.switch_on()
        d, r = self.prepared(launch, seq)
        self.assertTrue(r["ok"], r)
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertTrue(r["ok"], r)
        # The turn must have its result: until then it is an unfinished dispatch and counts at the session's
        # whole budget (v29.7), and a repeated send is judged against the limits first (part 2 review round 4 #3),
        # so on a busy machine "written" is too early and the repeat is refused for the budget.
        self.wait_for(lambda: self.journal(launch).state.turns[d].status == "ended", msg="the turn to end")
        # a send repeated for a dispatch that is already written is a status, whatever happened since
        self.change_account()
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertTrue(r["ok"], r)

    def test_a_manual_dispatch_prepared_before_the_switch_cannot_be_sent_in_automatic_mode(self):
        launch, _ = self.open()
        d = self.dispatch_prepare_only(launch)
        seq = self.accept_auto()
        # the daemon's own switch now refuses while a dispatch is unsent (UnsentDispatchTests); the send's gate is
        # the second line, so the mode is set here as a record that was already auto would be
        pipeline_store.mode_set(self.base, self.fid, "auto", f"auto-{seq}")
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertFalse(r["ok"], r)
        self.assertIn("手動派工與手動審查一律拒絕", r["error"]["message"])

    def dispatch_prepare_only(self, launch):
        d = fx.new_uuid()
        r = self.rpc("dispatch_prepare", launch_id=launch, pipeline=self.fid, dispatch_id=d, text="手動",
                     approval={"kind": "preview", "id": "pv-1"})
        self.assertTrue(r["ok"], r)
        return d

    def test_manual_mode_is_not_judged_by_the_live_account_at_send(self):
        # S2 design 3.1 re-checks the executor's account when a session starts, not on every dispatch; the live
        # check is the automatic mode's own requirement (S3 design 2)
        launch, _ = self.open()
        d = self.dispatch_prepare_only(launch)
        self.change_account()
        r = self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)
        self.assertTrue(r["ok"], r)


class UnsentDispatchTests(AutoCase):
    """S3 final review round 2: a dispatch that is prepared and not sent blocks the switch to automatic mode (its
    approval is a manual preview that automatic mode refuses, and a session accepts one unsent dispatch only)."""

    def prepare_manual(self, launch):
        d = fx.new_uuid()
        r = self.rpc("dispatch_prepare", launch_id=launch, pipeline=self.fid, dispatch_id=d, text="手動",
                     approval={"kind": "preview", "id": "pv-1"})
        self.assertTrue(r["ok"], r)
        return d

    def test_a_prepared_manual_dispatch_blocks_the_switch_and_a_sent_one_does_not(self):
        launch, _ = self.open()
        seq = self.accept_auto()
        d = self.prepare_manual(launch)
        r = self.set_mode("auto", seq=seq)
        self.assertFalse(r["ok"], r)
        self.assertIn("還有一則手動派工已準備但還沒送出", r["error"]["message"])
        self.assertIn("請先送出或處理它，再開啟自動執行", r["error"]["message"])
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")
        self.assertEqual(self.status(launch)["unsent"], d)                       # the console can see it
        self.assertTrue(self.rpc("stream_send", launch_id=launch, pipeline=self.fid, dispatch_id=d)["ok"])
        self.wait_for(lambda: self.status(launch)["unsent"] is None, msg="the dispatch to be written")
        r = self.set_mode("auto", seq=seq)
        self.assertTrue(r["ok"], r)

    def test_closing_the_session_is_the_other_way_out(self):
        launch, _ = self.open()
        seq = self.accept_auto()
        self.prepare_manual(launch)
        self.assertFalse(self.set_mode("auto", seq=seq)["ok"])
        self.assertTrue(self.rpc("stream_close", launch_id=launch)["ok"])
        self.wait_for(lambda: launch not in self.dm._streams, msg="the session to end")
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])

    def test_a_prepare_and_the_switch_asked_at_once_are_not_both_granted(self):
        import threading
        launch, _ = self.open()
        seq = self.accept_auto()
        answers, barrier = {}, threading.Barrier(2)

        def prepare():
            barrier.wait()
            answers["prepare"] = self.rpc("dispatch_prepare", launch_id=launch, pipeline=self.fid,
                                          dispatch_id=fx.new_uuid(), text="手動",
                                          approval={"kind": "preview", "id": "pv-1"})

        def switch():
            barrier.wait()
            answers["switch"] = self.set_mode("auto", seq=seq)
        threads = [threading.Thread(target=prepare), threading.Thread(target=switch)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(set(answers), {"prepare", "switch"})
        granted = [k for k, v in answers.items() if v["ok"]]
        self.assertEqual(len(granted), 1, answers)                              # exactly one of the two
        if granted == ["switch"]:
            self.assertIn("手動派工與手動審查一律拒絕", answers["prepare"]["error"]["message"])
        else:
            self.assertIn("已準備但還沒送出", answers["switch"]["error"]["message"])

    def test_the_other_direction_an_unsent_automatic_dispatch_blocks_switching_back(self):
        launch, _ = self.open()
        seq = self.accept_auto()
        self.assertTrue(self.set_mode("auto", seq=seq)["ok"])
        d = fx.new_uuid()
        r = self.rpc("dispatch_prepare", launch_id=launch, pipeline=self.fid, dispatch_id=d, text="自動",
                     approval={"kind": "automation", "id": f"auto-{seq}"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.rpc("pipeline_hold", pipeline=self.fid, reason="測試")["ok"])
        r = self.set_mode("manual")
        self.assertFalse(r["ok"], r)
        self.assertIn("還有一則自動派工已準備但還沒送出", r["error"]["message"])
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "auto")
        self.assertTrue(self.rpc("stream_close", launch_id=launch)["ok"])
        self.wait_for(lambda: launch not in self.dm._streams, msg="the session to end")
        self.assertTrue(self.set_mode("manual")["ok"])
