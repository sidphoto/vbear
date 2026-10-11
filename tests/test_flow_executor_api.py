"""The executor and dispatch routes of the console against a real runtime
daemon and the synthetic stream CLI of test_runtimed_stream (S2c-2): start,
status, preview and approve a dispatch, stop and continue, close. No Claude,
no Codex, no model."""

import json
import os
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from tests import stream_fixtures as fx
from tests.test_risk_acceptance import FakeHost
from tests.test_runtimed_stream import StreamCase
from vbear import acceptance as acc
from vbear import config as cfg
from vbear import flows, previews as pv, risk_acceptance as ra, tasks
from vbear.runtime import agent_sessions as a
from vbear.runtime import pipeline_store


class ApiCase(StreamCase):
    """StreamCase's daemon, flow, acceptance and fake CLI, behind the console's HTTP surface."""

    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        from vbear.server import Console, make_handler
        tasks.save_task(self.tid, {"title": "t", "workdir": str(self.work)})
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for src in conf["sources"]:
            src["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        env = mock.patch.dict(os.environ, {"VBEAR_RUNTIME_AUTOSTART": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.console = Console(self.port)
        self.console.executor.managed_root = self.tmp
        self.token = self.console.auth_token
        self.httpd.RequestHandlerClass = make_handler(self.console)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self._stop_http)
        self.host = FakeHost(self.tmp)
        self.host.binary = str(self.binary)
        self.host.claude_binary = lambda cwd=None: (self.host.binary, self.host.claude, "")
        self.host.claude_json = lambda: self.home / ".claude.json"                # the account the acceptance bound
        # a logged-in dedicated Codex home, and an acceptance that binds to it, so that the facts the
        # screen compares (status) are the ones that were accepted
        codex_home = self.base / "codex-home"
        codex_home.mkdir(mode=0o700, exist_ok=True)
        (codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": "acct-0001"}}))
        os.chmod(codex_home / "auth.json", 0o600)
        self.accept()
        ra._facts_cache.clear()
        p = mock.patch.object(ra, "DEFAULT_HOST", self.host)
        p.start()
        self.addCleanup(p.stop)

    def _stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, path, method="GET", body=None, token=True):
        h = {"X-VBear": "1", "Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {self.token}"
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"null")
            e.close()
            return e.code, data

    def api_start(self, mode="ok"):
        (self.work / "fake-mode").write_text(mode)
        st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {})
        self.assertEqual(st, 200, r)
        self.pids.append(self.launched()["pid"])
        return r["launch_id"]

    def executor(self):
        st, r = self.call(f"/api/flows/{self.fid}/executor")
        self.assertEqual(st, 200, r)
        return r

    def session(self, launch_id):
        return next(s for s in self.executor()["sessions"] if s["launch_id"] == launch_id)

    def preview(self, launch_id, text="請完成工作"):
        return self.call(f"/api/flows/{self.fid}/dispatch-preview", "POST", {"launch_id": launch_id, "text": text})

    def approve(self, preview_id):
        return self.call(f"/api/flows/{self.fid}/dispatch", "POST", {"preview_id": preview_id})

    def run_dispatch(self, launch_id, text="請完成工作"):
        st, pre = self.preview(launch_id, text)
        self.assertEqual(st, 200, pre)
        st, r = self.approve(pre["preview_id"])
        self.assertEqual(st, 200, r)
        return pre

    def wait_turn(self, launch_id, dispatch_id, statuses=("ended", "failed")):
        def done():
            s = self.session(launch_id)["status"]
            t = next((x for x in (s or {}).get("dispatches", []) if x["dispatch_id"] == dispatch_id), None)
            return t if t and t["status"] in statuses else None
        return self.wait_for(done, msg="the turn to end")


class StartTests(ApiCase):
    def test_start_prepares_opens_and_the_status_shows_it(self):
        before = self.dm._ledger.used
        st0 = self.executor()
        self.assertTrue(st0["can_start"])
        self.assertEqual(st0["acceptance"]["state"], "valid")
        launch_id = self.api_start()
        s = self.executor()
        self.assertEqual(s["current_launch_id"], launch_id)
        self.assertFalse(s["can_start"])
        sess = self.session(launch_id)
        self.assertEqual((sess["manifest_state"], sess["status"]["live"], sess["status"]["state"]),
                         ("running", True, "idle"))
        self.assertGreater(self.dm._ledger.used, before)                          # the prepared files are counted
        self.assertTrue(s["accounting"]["ok"])
        self.assertEqual(s["accounting"]["limits"]["max_dispatches"], 20)
        self.assertEqual(s["workdir"], str(self.work))
        self.assertFalse(s["hold"]["held"])

    def test_a_second_start_is_refused_and_leaves_no_prepared_launch_behind(self):
        self.api_start()
        names = sorted(os.listdir(self.base / "sessions"))
        st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {})
        self.assertEqual(st, 409, r)
        self.assertEqual(sorted(os.listdir(self.base / "sessions")), names)       # the new prepare was taken back

    def test_refusals_before_anything_is_prepared(self):
        def refused(code, fragment=""):
            st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {})
            self.assertEqual((st, r["code"]), (409, code), r)
            self.assertIn(fragment, r["error"])
            self.assertFalse((self.base / "sessions").exists() and os.listdir(self.base / "sessions"))
        pipeline_store.hold(self.base, self.fid, "user stop")
        refused("held", "user stop")
        pipeline_store.release(self.base, self.fid)
        self.host.claude = "2.1.299"
        refused("reaccept", "2.1.299")
        self.host.claude = "2.1.292"
        tasks.save_task(self.tid, {"title": "t", "workdir": None})
        refused("no_workdir")
        tasks.save_task(self.tid, {"title": "t", "workdir": str(self.work)})
        self.host.claude_binary = lambda cwd=None: (None, None, "找不到")
        refused("claude_version")

    def test_no_valid_acceptance_no_executor(self):
        with mock.patch.object(acc, "RISK_TEXT_VERSION", "2099-01-01.1"):
            st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {})
        self.assertEqual((st, r["code"]), (409, "no_acceptance"))
        st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {"model": "claude-opus-5-5"})
        self.assertEqual((st, r["code"]), (400, "bad_request"))                    # the model is the accepted one

    def test_the_status_of_an_unknown_flow_and_token_rules(self):
        self.assertEqual(self.call("/api/flows/flow-ffffffffffff/executor")[0], 404)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/executor", token=False)[0], 401)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/executor", "POST", {}, token=False)[0], 401)


class DispatchTests(ApiCase):
    def test_preview_approve_and_the_report_apart_from_the_file_checks(self):
        launch_id = self.api_start()
        pre = self.run_dispatch(launch_id)
        turn = self.wait_turn(launch_id, pre["dispatch_id"])
        self.assertEqual((turn["status"], turn["valid"], turn["reasons"]), ("ended", True, []))
        self.assertEqual(turn["report"]["dispatch_id"], pre["dispatch_id"])            # the executor's own words
        self.assertTrue(turn["file_checks"])                                           # VBear's file checks, separate
        saved = (self.base / "pipelines" / self.tid / "dispatches" / f"{pre['dispatch_id']}.txt").read_text()
        self.assertEqual(saved, pre["text"])                                           # the text sent is the text previewed
        s = self.executor()
        self.assertEqual(s["accounting"]["dispatches"], 1)
        self.assertEqual(s["accounting"]["responses"], self.session(launch_id)["status"]["responses"])
        self.assertIsNone(self.session(launch_id)["worst_case"])

    def test_the_preview_shows_what_will_be_sent(self):
        launch_id = self.api_start()
        st, pre = self.preview(launch_id, "第一行\n\t縮排\x01控制‮反向")
        self.assertEqual(st, 200, pre)
        self.assertTrue(pre["rewritten"])
        self.assertEqual(pre["text"], "第一行\n\t縮排\\u0001控制\\u202e反向")
        self.assertEqual(pre["bytes"], len(pre["text"].encode()))
        self.assertTrue(pre["ready"])
        self.assertRegex(pre["dispatch_id"], r"^[0-9a-f-]{36}$")
        rec = json.loads((self.base / "previews" / f"{pre['preview_id']}.json").read_text())
        self.assertEqual(rec["data"]["text"], pre["text"])                             # the file holds what the screen showed
        st, plain = self.preview(launch_id, "普通文字")
        self.assertFalse(plain["rewritten"])

    def test_bad_texts_and_bodies(self):
        launch_id = self.api_start()
        for text, code in (("", "bad_text"), ("   \n", "bad_text"), ("x" * 65400, "too_long"), (5, "bad_text"),
                           ("\ud800", "bad_text")):
            with self.subTest(text=str(text)[:10]):
                st, r = self.preview(launch_id, text)
                self.assertEqual((st, r["code"]), (400, code), r)
        for body in ({"launch_id": launch_id}, {"text": "x"}, {"launch_id": launch_id, "text": "x", "approval": 1},
                     {"launch_id": "l-xyz", "text": "x"}):
            st, r = self.call(f"/api/flows/{self.fid}/dispatch-preview", "POST", body)
            self.assertEqual(st, 400, body)
        st, r = self.preview("l-" + "0" * 16)
        self.assertEqual((st, r["code"]), (404, "no_session"))
        # the largest text that still fits one line passes; the HTTP body limit stops anything beyond it
        self.assertEqual(self.preview(launch_id, "x" * 60000)[0], 200)
        st, r = self.preview(launch_id, "x" * 70000)
        self.assertEqual(st, 413, r)

    def test_only_the_preview_id_is_taken_and_it_is_good_once(self):
        launch_id = self.api_start()
        pre = self.preview(launch_id)[1]
        for body in ({}, {"preview_id": pre["preview_id"], "text": "改過"}, {"preview_id": 5}):
            st, r = self.call(f"/api/flows/{self.fid}/dispatch", "POST", body)
            self.assertEqual(st, 400, body)
        self.assertEqual(self.approve(pre["preview_id"])[0], 200)
        st, r = self.approve(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "consumed"))
        self.wait_turn(launch_id, pre["dispatch_id"])
        self.assertEqual(self.executor()["accounting"]["dispatches"], 1)               # one dispatch, not two

    def test_an_expired_or_other_flows_preview(self):
        launch_id = self.api_start()
        pre = self.preview(launch_id)[1]
        with mock.patch.object(self.console.preview_records, "_clock", return_value=pre["expires_at"] + 1):
            st, r = self.approve(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "expired"))
        st, r = self.call("/api/flows/flow-ffffffffffff/dispatch", "POST", {"preview_id": self.preview(launch_id)[1]["preview_id"]})
        self.assertEqual(st, 404)

    def test_a_busy_session_flags_the_preview_and_refuses_the_approval(self):
        launch_id = self.api_start("hang")
        first = self.run_dispatch(launch_id)
        self.wait_for(lambda: (self.work / "hang-ready").exists(), msg="the turn to hang")
        st, pre = self.preview(launch_id, "第二則")
        self.assertEqual(st, 200)
        self.assertFalse(pre["ready"])
        self.assertIn("idle", pre["not_ready_reason"])
        st, r = self.approve(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "conflict"))
        self.assertIn("現在不能派工", r["error"])
        self.assertEqual(self.executor()["accounting"]["dispatches"], 1)               # nothing was prepared for it
        self.assertEqual(self.approve(pre["preview_id"])[1]["code"], "consumed")        # and the preview is void

    def test_a_stopped_flow_refuses_the_approval(self):
        launch_id = self.api_start()
        pre = self.preview(launch_id)[1]
        st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {"reason": "我先停下來"})
        self.assertEqual(st, 200, r)
        st, r = self.approve(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "conflict"))
        self.assertIn("我先停下來", r["error"])
        self.assertEqual(self.executor()["accounting"]["dispatches"], 0)

    def test_an_acceptance_that_stopped_counting_refuses_the_approval(self):
        launch_id = self.api_start()
        pre = self.preview(launch_id)[1]
        with mock.patch.object(acc, "RISK_TEXT_VERSION", "2099-01-01.1"):
            st, r = self.approve(pre["preview_id"])
        self.assertEqual((st, r["code"]), (409, "conflict"))
        self.assertEqual(self.executor()["accounting"]["dispatches"], 0)

    def test_a_dispatch_the_daemon_refuses_after_the_approval_says_so(self):
        launch_id = self.api_start()
        self.accept(max_dispatches=1)                                                   # a new acceptance with a smaller limit
        self.run_dispatch(launch_id)
        second = self.preview(launch_id, "第二則")[1]
        self.wait_for(lambda: self.session(launch_id)["status"]["state"] == "idle", msg="idle again")
        st, r = self.approve(second["preview_id"])
        self.assertEqual((st, r["code"]), (409, "refused"), r)                           # the daemon's limit, as it says it
        self.assertIn("派工則數上限", r["error"])


class StopAndCloseTests(ApiCase):
    def test_hold_continue_and_close_with_a_failed_session(self):
        launch_id = self.api_start("exit")
        pre = self.run_dispatch(launch_id)
        self.wait_for(lambda: self.executor()["hold"]["held"], msg="the failure to hold the flow")
        s = self.executor()
        self.assertIn("failure", s["hold"]["reason"])
        self.assertTrue(s["unresolved_failure"])
        sess = self.session(launch_id)
        wc = sess["worst_case"]
        self.assertIsNotNone(wc)
        self.assertIn("上一輪沒有結果，費用未知，以最壞情況計入", wc["text"])
        self.assertIn("要繼續就需要重新接受", wc["text"])
        self.assertEqual(wc["responses"], 200)                                          # the turn cap, the worst case
        self.assertGreater(wc["usd"], 0)
        self.assertFalse(s["can_start"])
        self.assertTrue(all(not f["released"] for f in s["failures"]))
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        if sess["manifest_state"] not in ("ended", "manual_review"):
            self.assertEqual(st, 409, r)                                                # the failed session first
            self.assertEqual(self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": launch_id})[0], 200)
            self.wait_for(lambda: self.session(launch_id)["manifest_state"] in ("ended", "manual_review"), msg="closed")
            st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)
        after = self.executor()
        self.assertFalse(after["hold"]["held"])
        self.assertTrue(after["failures"] and all(f["released"] for f in after["failures"]))
        self.assertIsNone(after["unresolved_failure"])

    def test_close_ends_the_session_and_only_a_flows_own_launch_can_be_closed(self):
        launch_id = self.api_start()
        st, r = self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": "l-" + "0" * 16})
        self.assertEqual((st, r["code"]), (404, "no_session"))
        for body in ({}, {"launch_id": launch_id, "x": 1}, {"launch_id": 5}):
            self.assertEqual(self.call(f"/api/flows/{self.fid}/executor/close", "POST", body)[0], 400)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": launch_id})[0], 200)
        self.wait_for(lambda: self.session(launch_id)["manifest_state"] == "ended", msg="the session to end")
        self.assertTrue(self.executor()["can_start"])

    def test_hold_and_continue_bodies(self):
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {"reason": 5})[0], 400)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call("/api/flows/flow-ffffffffffff/hold", "POST", {})[0], 404)
        self.assertEqual(self.call(f"/api/flows/{self.fid}/hold", "POST", {})[0], 200)
        info = self.executor()["hold"]
        self.assertTrue(info["held"])
        self.assertIn("使用者在主控台按了停止", info["reason"])
        self.assertEqual(self.call(f"/api/flows/{self.fid}/continue", "POST", {})[0], 200)
        self.assertFalse(self.executor()["hold"]["held"])


class ReadModelTests(ApiCase):
    def test_accounting_failures_and_unavailable_parts_are_said_not_hidden(self):
        s = self.executor()
        self.assertEqual(s["sessions"], [])
        self.assertTrue(s["accounting"]["ok"])
        with mock.patch("vbear.flow_executor.stream_flow.load",
                        side_effect=__import__("vbear.runtime.stream_flow", fromlist=["x"]).FlowRefused("count_unavailable", "壞了")):
            s = self.executor()
        self.assertEqual((s["accounting"]["ok"], s["accounting"]["code"]), (False, "count_unavailable"))
        self.assertFalse(s["can_start"])                                                # not offered when it cannot be counted

    def test_a_daemon_that_cannot_be_reached_is_a_503_for_actions_and_a_note_in_the_status(self):
        launch_id = self.api_start()
        real = self.console.runtime._rpc

        def down(op, timeout=2.0, **fields):
            raise ConnectionRefusedError(61, "refused")
        with mock.patch.object(self.console.runtime, "_rpc", down), \
                mock.patch.object(self.console.runtime, "ensure_daemon", return_value=False):
            sess = self.session(launch_id)
            self.assertIsNone(sess["status"])
            self.assertIn("無法連線", sess["status_problem"])
            st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
            self.assertEqual((st, r["code"]), (503, "unavailable"))
            st, r = self.preview(launch_id)
            self.assertEqual(st, 200)                                                    # a preview can still be made
            self.assertFalse(r["ready"])


if __name__ == "__main__":
    unittest.main()
