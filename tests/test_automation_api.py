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
