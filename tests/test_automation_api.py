"""Phase 3, segment 2 (S3 design 2, 9; v11.1): approving a plan and turning
automatic mode on from the console, switching it off, and what the manual
routes say meanwhile. A real daemon, the synthetic Claude and Codex; no model."""

import hashlib
import json
import os
import time

from tests.test_flow_review_api import ReviewApiCase
from vbear import acceptance as acc
from vbear import automation, flows, tasks
from vbear.runtime import pipeline_store


class AutoApiCase(ReviewApiCase):
    def setUp(self):
        super().setUp()
        tasks.save_task(self.tid, {"title": "實作 add()", "workdir": str(self.work), "goal": "完成 add 函式",
                                   "scope": ["add.py"], "acceptance_criteria": ["單元測試涵蓋邊界", "\x01危險"]})

    def preview(self, body=None):
        return self.call(f"/api/flows/{self.fid}/automation-preview", "POST", body or {})

    def confirm(self, preview_id):
        return self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": preview_id})

    def enable(self):
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        st, r = self.confirm(pre["preview_id"])
        self.assertEqual(st, 200, r)
        return pre, r

    def mode(self):
        return self.call(f"/api/flows/{self.fid}/automation")[1]


class PreviewTests(AutoApiCase):
    def test_the_preview_shows_the_plan_the_values_and_every_part_of_the_text(self):
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        self.assertIn("任務：實作 add()", pre["plan_text"])
        self.assertIn("目標：完成 add 函式", pre["plan_text"])
        self.assertIn("\\u0001危險", pre["plan_text"])                                  # control characters are visible
        raw = pre["plan_text"].encode()
        self.assertEqual((pre["plan_sha256"], pre["plan_bytes"]), (hashlib.sha256(raw).hexdigest(), len(raw)))
        self.assertEqual([s["id"] for s in pre["auto_text"]["zh"]["sections"]],
                         ["does", "limits", "accounts", "not_auto", "forwarding", "git_writable", "stop", "residual"])
        self.assertEqual(pre["auto_text"]["zh"]["version"], acc.AUTO_RISK_TEXT_VERSION)
        self.assertEqual(len(pre["risk_text"]["zh"]["items"]), 3)                        # the S2 risks, same source
        self.assertEqual(pre["fixed_rules"], ["連續失敗 1 次就停止（不能調整）"])
        limits = {x["name"]: x["value"] for x in pre["values"]["limits"]}
        self.assertEqual(limits["max_elapsed_h"], 4)                                     # prefilled lower (design 4)
        self.assertEqual(len(limits), 9)
        self.assertFalse(any(len(v) >= 64 for k, v in pre["values"].items() if isinstance(v, str)))
        st, pre2 = self.preview({"limits": {"max_elapsed_h": 2, "max_reviews": 3}})
        self.assertEqual(st, 200, pre2)
        limits = {x["name"]: x["value"] for x in pre2["values"]["limits"]}
        self.assertEqual((limits["max_elapsed_h"], limits["max_reviews"]), (2, 3))

    def test_refusals(self):
        for body, code in (({"x": 1}, "bad_request"), ({"limits": {"max_elapsed_h": 999}}, "bad_limits"),
                           ({"limits": {"nope": 1}}, "bad_limits"), ({"executor_model": "haiku"}, "bad_model")):
            st, r = self.preview(body)
            self.assertEqual((st, r["code"]), (400, code), (body, r))
        st, r = self.confirm("0" * 32)
        self.assertEqual((st, r["code"]), (404, "not_found"))
        st, r = self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": "x", "text": "y"})
        self.assertEqual((st, r["code"]), (400, "bad_request"))
        st, pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {})   # an S2 preview is not an S3 one
        st, r = self.confirm(pre["preview_id"])
        self.assertEqual(st, 409, r)

    def test_a_stopped_flow_is_not_offered_automatic_mode(self):
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        st, r = self.preview()
        self.assertEqual((st, r["code"]), (409, "held"))


class ConfirmTests(AutoApiCase):
    def test_one_confirmation_writes_the_plan_the_acceptance_and_the_mode(self):
        pre, r = self.enable()
        flow = flows.get_flow(self.fid)
        ev = next(e for e in reversed(flow["events"]) if e["kind"] == "risk_acknowledged")
        self.assertEqual(r["approval_id"], f"auto-{ev['seq']}")
        self.assertEqual((ev["plan_sha256"], ev["plan_bytes"], ev["auto_text_version"]),
                         (pre["plan_sha256"], pre["plan_bytes"], acc.AUTO_RISK_TEXT_VERSION))
        self.assertEqual(ev["automation_scope"], list(acc.AUTO_SCOPE))
        self.assertEqual(ev["limits"]["max_elapsed_h"], 4)
        self.assertEqual(flow["events"][-1]["kind"], "automation_mode")
        self.assertEqual(flow["events"][-1]["approval_seq"], ev["seq"])
        plan = self.base / "automation" / self.fid / "plan.txt"
        self.assertEqual(plan.read_text(), pre["plan_text"])                              # what the screen showed
        self.assertEqual(oct(plan.stat().st_mode & 0o777), "0o600")
        info = pipeline_store.mode_info(self.base, self.fid)
        self.assertEqual((info["mode"], info["approval_id"]), ("auto", r["approval_id"]))
        m = self.mode()
        self.assertEqual((m["mode"], m["approval"]["plan_sha256"]), ("auto", pre["plan_sha256"]))
        self.assertEqual(automation.read_plan(self.base, self.fid, sha256=pre["plan_sha256"], size=pre["plan_bytes"]),
                         pre["plan_text"])
        # the values the event holds are the preview's, not anything the browser sent
        st, view = self.call(f"/api/flows/{self.fid}")
        self.assertEqual(st, 200, view)
        self.assertEqual(view["flow"]["automation"]["mode"], "auto")

    def test_a_preview_is_used_once(self):
        st, pre = self.preview()
        self.assertEqual(self.confirm(pre["preview_id"])[0], 200)
        st, r = self.confirm(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "consumed"))

    def test_a_fact_that_changed_voids_the_preview_and_nothing_is_written(self):
        st, pre = self.preview()
        self.host.claude = "9.9.9"                                                       # the CLI was updated meanwhile
        st, r = self.confirm(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "conflict"), r)
        self.assertFalse((self.base / "automation" / self.fid / "plan.txt").exists())
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")
        self.assertFalse(any(acc.is_auto_event(e) for e in flows.get_flow(self.fid)["events"]))

    def test_a_flow_that_was_stopped_after_the_preview_is_not_switched_on(self):
        st, pre = self.preview()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        st, r = self.confirm(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "conflict"), r)
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")

    def test_the_daemon_has_the_last_word(self):
        st, pre = self.preview()
        from unittest import mock
        from vbear import daemon_client
        with mock.patch.object(daemon_client, "call", side_effect=daemon_client.DaemonError(
                409, "refused", "還有尚未解除的失敗")):
            st, r = self.confirm(pre["preview_id"])
        self.assertEqual(st, 409, r)
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")
        # the acceptance is recorded (it is a valid acceptance), the plan is there, but nothing runs
        self.assertTrue((self.base / "automation" / self.fid / "plan.txt").exists())


class ManualRoutesTests(AutoApiCase):
    def test_manual_actions_are_refused_in_automatic_mode(self):
        self.enable()
        self.start_executor()                                                            # starting a session stays a human act
        for path, body in ((f"/api/flows/{self.fid}/dispatch-preview", {"launch_id": self.launch, "text": "x"}),
                           (f"/api/flows/{self.fid}/dispatch", {"preview_id": "0" * 32}),
                           (f"/api/flows/{self.fid}/review", {}),
                           (f"/api/flows/{self.fid}/acceptance-preview", {}),
                           (f"/api/flows/{self.fid}/acceptance", {"preview_id": "0" * 32})):
            st, r = self.call(path, "POST", body)
            self.assertEqual((st, r["code"]), (409, "automation_active"), (path, r))
        s = self.executor_status()
        self.assertEqual(s["automation"]["mode"], "auto")

    def test_stopping_is_recorded_and_switching_back_needs_a_stopped_flow(self):
        self.enable()
        st, r = self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})
        self.assertEqual(st, 409, r)
        self.assertIn("已停止", r["error"])
        st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
        self.assertEqual(st, 200, r)
        stop = flows.get_flow(self.fid)["events"][-1]
        self.assertEqual((stop["kind"], stop["source"], stop["reason_code"]), ("auto_stopped", "automation", "user_stop"))
        st, r = self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})
        self.assertEqual((st, r["mode"]), (200, "manual"))
        self.assertEqual(flows.get_flow(self.fid)["events"][-1]["kind"], "automation_mode")
        self.assertEqual(self.mode()["mode"], "manual")
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {"x": 1})[0], 400)
        # manual again: the manual routes work again (the flow is still stopped until "continue")
        st, r = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {})
        self.assertEqual(st, 200, r)


class PlanFileTests(AutoApiCase):
    def test_a_missing_or_changed_plan_is_refused(self):
        pre, _ = self.enable()
        plan = self.base / "automation" / self.fid / "plan.txt"
        args = dict(sha256=pre["plan_sha256"], size=pre["plan_bytes"])
        plan.write_text(pre["plan_text"] + " ")
        with self.assertRaises(automation.ApiError) as cm:
            automation.read_plan(self.base, self.fid, **args)
        self.assertEqual(cm.exception.code, "plan_changed")
        plan.unlink()
        with self.assertRaises(automation.ApiError) as cm:
            automation.read_plan(self.base, self.fid, **args)
        self.assertEqual(cm.exception.code, "plan_missing")
        plan.symlink_to(self.work)
        with self.assertRaises(automation.ApiError):
            automation.read_plan(self.base, self.fid, **args)

    def test_the_text_is_built_from_the_task_card_only(self):
        t = {"title": "T", "goal": "G", "scope": ["a", "b"], "acceptance_criteria": ["c"], "evidence": []}
        self.assertEqual(automation.build_plan_text(t), "任務：T\n目標：G\n範圍：\n- a\n- b\n驗收條件：\n- c")
        self.assertEqual(automation.build_plan_text({"title": "只有標題"}), "任務：只有標題")


class ApprovalUnitTests(AutoApiCase):
    """The S3-2 review: one approval is one unit across processes; the daemon reads the plan file itself; an
    event that cannot be written is not a success."""

    def test_two_approvals_confirmed_at_once_leave_a_plan_that_is_the_one_the_mode_is_bound_to(self):
        import threading
        from unittest import mock
        st, a = self.preview()
        tasks.save_task(self.tid, {"title": "實作 add()", "workdir": str(self.work), "goal": "另一個目標"})
        st, b = self.preview()
        self.assertNotEqual(a["plan_sha256"], b["plan_sha256"])
        real = flows.append_risk_acknowledged
        order = []

        def slow(flow_id, fields):
            order.append(fields["plan_sha256"])
            time.sleep(0.4)                                  # A is inside the unit when B arrives
            return real(flow_id, fields)
        out = {}
        with mock.patch.object(flows, "append_risk_acknowledged", slow):
            def go(name, pre):
                out[name] = self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
            ta = threading.Thread(target=go, args=("a", a))
            tb = threading.Thread(target=go, args=("b", b))
            ta.start()
            time.sleep(0.1)
            tb.start()
            ta.join(60)
            tb.join(60)
        self.assertEqual(out["a"][0], 200, out)
        info = pipeline_store.mode_info(self.base, self.fid)
        self.assertEqual(info["mode"], "auto")
        seq = int(info["approval_id"].split("-")[1])
        ev = flows.get_flow(self.fid)["events"][seq - 1]
        plan = (self.base / "automation" / self.fid / "plan.txt").read_bytes()
        self.assertEqual(hashlib.sha256(plan).hexdigest(), ev["plan_sha256"])        # file and mode agree
        # the two did not interleave: each event's plan was written whole before the next began
        self.assertEqual(len(order), len(set(order)))

    def test_the_daemon_reads_the_plan_file_before_switching_on_and_on_every_automatic_dispatch(self):
        from vbear import daemon_client
        pre, r = self.enable()
        plan = self.base / "automation" / self.fid / "plan.txt"
        # switched on: tamper -> an automatic dispatch is refused by the daemon
        self.start_executor()
        mode = pipeline_store.mode_info(self.base, self.fid)
        good = plan.read_bytes()
        plan.write_bytes(good + b"\n")
        with self.assertRaises(daemon_client.DaemonError) as cm:
            daemon_client.call(self.console.executor.runtime, "dispatch_prepare", launch_id=self.launch,
                               pipeline=self.fid, dispatch_id="0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", text="x",
                               approval={"kind": "automation", "id": mode["approval_id"]})
        self.assertIn("plan.txt", str(cm.exception))
        # stopped, back to manual, the file gone: it cannot be switched on again with that approval
        plan.write_bytes(good)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        plan.unlink()
        with self.assertRaises(daemon_client.DaemonError) as cm:
            daemon_client.call(self.console.executor.runtime, "pipeline_mode_set", pipeline=self.fid, mode="auto",
                               approval={"kind": "automation", "id": mode["approval_id"]})
        self.assertIn("計畫文字", str(cm.exception))
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "manual")

    def test_not_enough_room_for_the_events_a_run_can_write_is_refused_up_front(self):
        with flows.store.locked():
            data = flows.store.load()
            ev = data[self.fid]["events"]
            while len(ev) < flows.MAX_EVENTS - 30:
                ev.append({"seq": len(ev) + 1, "at": time.time(), "kind": "note", "source": "manual", "note": "x"})
            flows.store.save(data)
        st, r = self.preview()
        self.assertEqual((st, r["code"]), (409, "no_event_room"))
        # a smaller run fits: 2 dispatches, 1 review = 2*3 + 1*4 + 22 = 32 > 30 still not; 1 and 1 = 29
        st, r = self.preview({"limits": {"max_dispatches": 1, "max_reviews": 1}})
        self.assertEqual(st, 200, r)

    def test_a_switch_on_that_cannot_be_recorded_stops_the_flow_and_says_so(self):
        from unittest import mock
        st, pre = self.preview()
        with mock.patch.object(flows, "append_automation_event", side_effect=ValueError("事件已達上限")):
            st, r = self.confirm(pre["preview_id"])
        self.assertEqual((st, r["code"]), (500, "event_write"))
        self.assertIn("流程已停止", r["error"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))          # on, but held: it does nothing

    def test_a_stop_whose_event_cannot_be_written_says_so_in_the_answer(self):
        from unittest import mock
        self.enable()
        with mock.patch.object(flows, "append_automation_event", side_effect=ValueError("事件已達上限")):
            st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
        self.assertEqual(st, 200, r)
        self.assertFalse(r["event_written"])
        self.assertIn("無法寫入時間軸", r["event_problem"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))

    def test_the_lock_file_is_part_of_the_flows_own_data(self):
        from vbear.runtime import flow_data
        self.enable()
        d = self.base / "automation" / self.fid
        self.assertTrue((d / ".lock").exists())
        self.assertEqual(sorted(p.name for p in d.iterdir()), [".lock", "plan.txt"])
        pl = flow_data.plan(self.base, self.fid, self.tid)
        self.assertIsNotNone(pl.automation_inode)


class ScreenDataTests(AutoApiCase):
    """S3-5: what the flow view and the automation status carry for the screens."""

    def view(self):
        st, r = self.call(f"/api/flows/{self.fid}")
        self.assertEqual(st, 200, r)
        return r["flow"]

    def test_a_manual_flow_has_no_automatic_attention(self):
        v = self.view()
        self.assertEqual(v["automation"]["mode"], "manual")
        self.assertEqual(v["attention_reason"], v["phase"]["reason"])

    def test_an_automatic_flow_shows_its_step_and_is_for_the_user_when_stopped_or_at_the_gate(self):
        self.enable()
        v = self.view()
        self.assertEqual((v["automation"]["mode"], v["automation"]["step"], v["automation"]["held"]),
                         ("auto", "first_dispatch", False))
        self.assertIn("計畫全文", v["automation"]["step_label"])
        self.assertFalse(v["attention"])
        st, au = self.call(f"/api/flows/{self.fid}/automation")
        self.assertEqual(au["step"]["step"], "first_dispatch")
        self.assertIn("接著", "接著" + au["step"]["after"])
        # stopped: for the user, with the reason
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        v = self.view()
        self.assertTrue(v["attention"])
        self.assertIn("自動執行已停止", v["attention_reason"])
        self.assertTrue(self.call(f"/api/flows/{self.fid}/automation")[1]["step"]["held"])
        # at the merge gate: a PASS and the runner's announcement
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        j = "r-" + "1" * 16
        flows.append_automation_event(self.fid, "auto_review_result",
                                      {"round": 1, "job_id": j, "commit": "a" * 40, "verdict": "PASS", "valid": True})
        flows.append_automation_event(self.fid, "auto_stopped",
                                      {"reason_code": "awaiting_merge", "detail": "審查通過"})
        v = self.view()
        self.assertTrue(v["attention"])
        self.assertTrue(v["automation"]["awaiting_merge"])
        self.assertIn("合併關卡", v["attention_reason"])
        self.assertTrue(any(e["source_label"] == flows.AUTOMATION_LABEL for e in v["events"]))


class ApprovalFailureTests(AutoApiCase):
    """S3-2 review round 2."""

    def test_any_failure_writing_the_switch_on_event_holds_the_flow(self):
        from unittest import mock
        st, pre = self.preview()
        with mock.patch.object(flows, "append_automation_event", side_effect=OSError(28, "disk full")):
            st, r = self.confirm(pre["preview_id"])
        self.assertEqual((st, r["code"]), (500, "event_write"))
        self.assertIn("流程已停止", r["error"])
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))
        self.assertEqual(pipeline_store.mode_info(self.base, self.fid)["mode"], "auto")      # on, and held

    def test_when_even_the_stop_cannot_be_asked_for_it_says_so(self):
        from unittest import mock
        from vbear import daemon_client
        st, pre = self.preview()
        real = self.console.executor._call

        def calls(op, **kw):
            if op == "pipeline_hold":
                raise ApiError(503, "unavailable", "背景程序沒有回應")
            return real(op, **kw)
        with mock.patch.object(flows, "append_automation_event", side_effect=OSError(5, "io")), \
                mock.patch.object(self.console.executor, "_call", side_effect=calls):
            st, r = self.confirm(pre["preview_id"])
        self.assertEqual((st, r["code"]), (500, "event_write_not_stopped"))
        self.assertIn("可能仍在自動模式", r["error"])
        self.assertIn("停止流程", r["error"])

    def test_a_deletion_does_not_take_a_flow_whose_approval_is_in_progress(self):
        import fcntl
        from vbear.runtime import flow_data
        self.enable()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        pl = flow_data.plan(self.base, self.fid, self.tid)
        self.assertEqual(flow_data.blockers(pl), [])
        fd = os.open(self.base / "automation" / self.fid / ".lock", os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)                                   # an approval is inside its unit
        try:
            with self.assertRaises(flow_data.FlowDataRefused) as cm:
                flow_data.remove(self.base, pl)
            self.assertIn("正在開啟自動執行", str(cm.exception))
            self.assertFalse(cm.exception.partial)                       # nothing was moved
            self.assertTrue((self.base / "automation" / self.fid / "plan.txt").exists())
            st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
            self.assertEqual(st, 409, r)
            self.assertIn("正在開啟自動執行", r["error"])
        finally:
            os.close(fd)
        st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})     # the lock is free: it goes
        self.assertEqual(st, 200, r)

    def test_an_approval_that_finds_the_flow_being_deleted_writes_nothing(self):
        st, pre = self.preview()
        tomb = self.base / "deleting" / self.fid
        tomb.mkdir(parents=True, mode=0o700)
        os.chmod(tomb.parent, 0o700)
        n = len(flows.get_flow(self.fid)["events"])
        st, r = self.confirm(pre["preview_id"])
        self.assertEqual(st, 409, r)
        self.assertEqual(len(flows.get_flow(self.fid)["events"]), n)
        self.assertFalse((self.base / "automation" / self.fid / "plan.txt").exists())


class DeletionWindowTests(AutoApiCase):
    def test_nothing_new_can_be_created_for_a_flow_between_its_purge_and_the_removal_of_its_record(self):
        """The window the S3-2 review found: the data is purged, the record is not yet removed. An approval from
        another console that starts then must be refused and must create nothing."""
        from unittest import mock
        from vbear import automation as automation_mod
        from vbear.api_error import ApiError
        self.enable()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        real = flows.delete_flow
        seen = {}

        def probe(flow_id):
            seen["marker"] = (self.base / "deleting" / flow_id).is_dir()
            seen["automation_dir"] = (self.base / "automation" / flow_id).exists()
            try:
                with automation_mod.plan_lock(self.base, flow_id):
                    seen["got"] = True
            except ApiError as exc:
                seen["error"] = (exc.status, exc.code)
            seen["created"] = (self.base / "automation" / flow_id).exists()
            return real(flow_id)
        with mock.patch.object(flows, "delete_flow", probe):
            st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
        self.assertEqual(st, 200, r)
        self.assertTrue(seen["marker"], "the marker is still there when the record is about to go")
        self.assertFalse(seen["automation_dir"])
        self.assertEqual(seen["error"], (409, "deleting"))
        self.assertNotIn("got", seen)
        self.assertFalse(seen["created"], "the refused approval created nothing")
        # afterwards the marker is gone with the record, and nothing of the flow is left
        self.assertFalse((self.base / "deleting" / self.fid).exists())
        self.assertFalse((self.base / "automation" / self.fid).exists())

    def test_an_orphan_marker_of_a_flow_whose_record_is_gone_is_swept_when_the_daemon_starts(self):
        from vbear.runtime import flow_data
        orphan = self.base / "deleting" / "flow-aaaaaaaaaaaa"
        orphan.mkdir(parents=True, mode=0o700)
        os.chmod(orphan.parent, 0o700)
        kept = self.base / "deleting" / "flow-bbbbbbbbbbbb"
        kept.mkdir(mode=0o700)
        (kept / "left").write_text("x")                                     # not empty: not ours to remove
        swept = flow_data.sweep_orphans(self.base, {self.fid})
        self.assertEqual(swept, ["flow-aaaaaaaaaaaa"])
        self.assertFalse(orphan.exists())
        self.assertTrue(kept.exists())
        # the daemon refuses to remove the marker of a flow whose record is still there
        from vbear import daemon_client
        with self.assertRaises(daemon_client.DaemonError):
            daemon_client.call(self.console.executor.runtime, "flow_delete_done", pipeline=self.fid)


class DeletionLifecycleTests(AutoApiCase):
    """S3-5 review round 3: every place a deletion can stop has a way out that needs no restart."""

    def deletable(self):
        self.enable()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/automation/disable", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)

    def stop_after_the_record(self):
        """Delete, but the console 'dies' before it asks the daemon to finish: the record is gone, the marker stays."""
        from unittest import mock
        from vbear import daemon_client
        real = daemon_client.call

        def refuse_done(runtime, op, **kw):
            if op == "flow_delete_done":
                raise daemon_client.DaemonError(503, "unavailable", "背景程序沒有回應")
            return real(runtime, op, **kw)
        with mock.patch("vbear.flow_storage.daemon_client.call", refuse_done):
            st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
        self.assertEqual(st, 200, r)
        self.assertTrue((self.base / "deleting" / self.fid).is_dir())
        with self.assertRaises(KeyError):
            flows.get_flow(self.fid)

    def test_delete_of_a_flow_whose_record_is_gone_finishes_its_marker(self):
        self.deletable()
        self.stop_after_the_record()
        st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
        self.assertEqual(st, 200, r)                                   # not a 404: this IS the way out
        self.assertTrue(r["marker_finished"])
        self.assertFalse((self.base / "deleting" / self.fid).exists())

    def test_reading_the_list_finishes_orphan_markers(self):
        self.deletable()
        self.stop_after_the_record()
        st, r = self.call("/api/flows/storage")
        self.assertEqual(st, 200, r)
        self.assertFalse((self.base / "deleting" / self.fid).exists())

    def test_a_marker_that_holds_something_is_left_for_a_person_and_says_so(self):
        self.deletable()
        self.stop_after_the_record()
        (self.base / "deleting" / self.fid / "left-over").write_text("x")
        st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
        self.assertNotEqual(st, 200, r)
        self.assertIn("交人工處理", r["error"])
        self.assertTrue((self.base / "deleting" / self.fid / "left-over").exists())
        self.assertEqual(self.call("/api/flows/storage")[0], 200)       # listing is not broken by it

    def test_an_unknown_flow_without_a_marker_is_still_a_404(self):
        st, r = self.call("/api/flows/flow-ffffffffffff/delete", "POST", {"flow_id": "flow-ffffffffffff"})
        self.assertEqual(st, 404, r)

    def test_an_approval_that_arrives_after_the_deletion_leaves_nothing_behind(self):
        from vbear import automation as automation_mod
        from vbear.api_error import ApiError
        gone = "flow-abcabcabcabc"                                       # a flow whose record is not there (any more)
        with self.assertRaises(ApiError) as cm:
            with automation_mod.plan_lock(self.base, gone):
                pass
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "no_flow"))
        self.assertFalse((self.base / "automation" / gone).exists())

    def test_the_daemon_sweeps_a_lock_only_directory_of_a_flow_that_is_gone_and_nothing_else(self):
        from vbear.runtime import flow_data
        base = self.base / "automation"
        base.mkdir(mode=0o700, exist_ok=True)
        os.chmod(base, 0o700)
        lock_only = base / "flow-111111111111"
        lock_only.mkdir(mode=0o700)
        (lock_only / ".lock").write_text("")
        with_plan = base / "flow-222222222222"
        with_plan.mkdir(mode=0o700)
        (with_plan / ".lock").write_text("")
        (with_plan / "plan.txt").write_text("a plan")
        known = base / self.fid
        swept = flow_data.sweep_orphans(self.base, {self.fid})
        self.assertIn("automation/flow-111111111111", swept)
        self.assertFalse(lock_only.exists())
        self.assertTrue(with_plan.exists())                              # something of value: left for a person
        self.assertNotIn(f"automation/{self.fid}", swept)

    def test_finishing_a_marker_checks_what_it_removes(self):
        from vbear.runtime import flow_data
        deleting = self.base / "deleting"
        deleting.mkdir(mode=0o700, exist_ok=True)
        os.chmod(deleting, 0o700)
        link_target = self.tmp / "elsewhere"
        link_target.mkdir(mode=0o700)
        os.symlink(link_target, deleting / "flow-333333333333")          # a link where the marker should be
        with self.assertRaises(flow_data.FlowDataRefused):
            flow_data.finish(self.base, "flow-333333333333")
        self.assertTrue(link_target.exists())
        os.unlink(deleting / "flow-333333333333")
        public = deleting / "flow-444444444444"
        public.mkdir(mode=0o755)
        os.chmod(public, 0o755)                                          # not private: not ours to remove
        with self.assertRaises(flow_data.FlowDataRefused):
            flow_data.finish(self.base, "flow-444444444444")
        self.assertTrue(public.exists())


class UnsentDispatchTests(AutoApiCase):
    """S3 final review round 2: a manual dispatch that was prepared and not sent. The console says so before it
    offers automatic mode, and has a way to send exactly that dispatch (or the session can be closed)."""

    def prepared_unsent(self):
        from unittest import mock
        from vbear import flow_executor
        from vbear.api_error import ApiError
        launch_id = self.start_executor()
        st, pre = self.preview_dispatch(launch_id)
        self.assertEqual(st, 200, pre)
        with mock.patch.object(flow_executor.FlowExecutor, "_send",
                               side_effect=ApiError(503, "unavailable", "背景程序沒有回應")):
            st, r = self.call(f"/api/flows/{self.fid}/dispatch", "POST", {"preview_id": pre["preview_id"]})
        self.assertNotEqual(st, 200, r)                                          # prepared, and not sent
        return launch_id, pre["dispatch_id"]

    def preview_dispatch(self, launch_id, text="請完成工作"):
        return self.call(f"/api/flows/{self.fid}/dispatch-preview", "POST", {"launch_id": launch_id, "text": text})

    def send(self, launch_id, dispatch_id):
        return self.call(f"/api/flows/{self.fid}/dispatch-send", "POST",
                         {"launch_id": launch_id, "dispatch_id": dispatch_id})

    def session(self, launch_id):
        return next(x for x in self.executor_status()["sessions"] if x["launch_id"] == launch_id)

    def approve(self, preview_id):
        return self.call(f"/api/flows/{self.fid}/dispatch", "POST", {"preview_id": preview_id})

    def wait_turn(self, launch_id, dispatch_id):
        def done():
            st = self.session(launch_id)["status"] or {}
            t = next((x for x in st.get("dispatches", []) if x["dispatch_id"] == dispatch_id), None)
            return t if t and t["status"] in ("ended", "failed") else None
        return self.wait_for(done, msg="the turn to end")

    def test_the_view_shows_it_and_automatic_mode_is_not_offered(self):
        launch_id, d = self.prepared_unsent()
        s = self.session(launch_id)
        self.assertEqual(s["status"]["unsent"], d)
        st, r = self.preview()
        self.assertEqual((st, r["code"]), (409, "unsent_dispatch"), r)
        self.assertEqual(r["dispatch_id"], d)
        self.assertIn("請先送出或處理它", r["error"])

    def test_a_second_prepare_is_refused_and_the_first_one_can_be_sent(self):
        launch_id, d = self.prepared_unsent()
        st, pre = self.preview_dispatch(launch_id, "第二則")
        st, r = self.approve(pre["preview_id"])
        self.assertEqual(st, 409, r)
        self.assertIn("已有一則準備好但還沒送出", r["error"])
        st, r = self.send(launch_id, d)
        self.assertEqual(st, 200, r)
        self.assertEqual(r["dispatch_id"], d)
        self.wait_turn(launch_id, d)
        self.assertIsNone(self.session(launch_id)["status"]["unsent"])
        st, r = self.send(launch_id, d)                                          # nothing is unsent now
        self.assertEqual((st, r["code"]), (409, "not_unsent"), r)
        self.assertEqual(self.preview()[0], 200)                                 # and the mode can be offered again

    def test_only_the_dispatch_that_is_unsent_can_be_sent_here(self):
        launch_id, d = self.prepared_unsent()
        import uuid
        st, r = self.send(launch_id, str(uuid.uuid4()))
        self.assertEqual((st, r["code"]), (409, "not_unsent"), r)
        for body in ({"launch_id": launch_id}, {"launch_id": launch_id, "dispatch_id": d, "text": "改過"},
                     {"launch_id": launch_id, "dispatch_id": "x"}):
            st, r = self.call(f"/api/flows/{self.fid}/dispatch-send", "POST", body)
            self.assertEqual(st, 400, body)
        st, r = self.send("l-" + "0" * 16, d)
        self.assertEqual((st, r["code"]), (404, "no_session"))
        self.assertEqual(self.session(launch_id)["status"]["unsent"], d)         # still there, still the same one

    def test_a_stopped_flow_does_not_send_it_and_continue_does(self):
        launch_id, d = self.prepared_unsent()
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        st, r = self.send(launch_id, d)
        self.assertEqual((st, r["code"]), (409, "held"), r)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        self.assertEqual(self.send(launch_id, d)[0], 200)

    def test_closing_the_session_is_the_other_way_out(self):
        launch_id, d = self.prepared_unsent()
        st, r = self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": launch_id})
        self.assertEqual(st, 200, r)
        self.wait_for(lambda: self.session(launch_id)["manifest_state"] == "ended", msg="the session to end")
        self.assertEqual(self.preview()[0], 200)                                 # nothing unsent in a live session

    def test_in_automatic_mode_the_manual_send_is_refused(self):
        self.enable()
        import uuid
        st, r = self.send("l-" + "0" * 16, str(uuid.uuid4()))
        self.assertEqual((st, r["code"]), (409, "automation_active"), r)

    def test_the_same_dispatch_is_written_once_however_it_is_sent(self):
        """dispatch-send is not a second use of the preview's approval: it completes a dispatch the consumed preview
        already made, and the daemon writes one dispatch id once (a repeat, or two at once, is only a status)."""
        import threading
        launch_id, d = self.prepared_unsent()
        answers, barrier = [], threading.Barrier(3)

        def send():
            barrier.wait()
            answers.append(self.send(launch_id, d))

        def confirm_again():                                   # the preview of that dispatch is gone: consumed
            barrier.wait()
            answers.append(self.call(f"/api/flows/{self.fid}/dispatch", "POST", {"preview_id": "0" * 32}))
        threads = [threading.Thread(target=send), threading.Thread(target=send), threading.Thread(target=confirm_again)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(len(answers), 3)
        self.assertTrue(any(st == 200 for st, _ in answers), answers)           # the send was granted to someone
        self.wait_turn(launch_id, d)
        lines = (self.base / "sessions" / launch_id / "journal.jsonl").read_text().splitlines()
        writing = [x for x in lines if '"kind":"dispatch_writing"' in x.replace(" ", "")]
        self.assertEqual(len(writing), 1, writing)             # one write, whoever asked and however often
        st, r = self.send(launch_id, d)                         # and a later request is not a resend
        self.assertEqual((st, r["code"]), (409, "not_unsent"), r)
