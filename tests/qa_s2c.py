"""S2c end-to-end QA harness (design 3, 4, 5, 8, 9, 10).

A throwaway console and a real runtime daemon in a temporary state directory,
with the synthetic Claude and Codex programs of the flow API tests. No
model, no real account, no real ~/.vbear and no network is involved; the
synthetic ~/.claude.json and auth files hold made-up identities.

  python3 -m unittest tests.qa_s2c -v          the scripted walk-through (every step printed)
  VBEAR_QA_SERVE=1 python3 -m unittest tests.qa_s2c.Serve -v
      the same environment, left running for a person or a browser tool:
      the URL to open is printed. The flow starts WITHOUT a risk
      acceptance, so the dialog is the first thing to try. Stop with Ctrl-C
      (or set VBEAR_QA_SECONDS).

What to look at in the browser (the flow page, 「流程」 -> the flow):
  1. 風險接受: 接受殘餘風險… -> three risks in full, nine limits, the tick;
     change a limit (the preview is voided), 套用並重新預覽, accept.
  2. 串流執行者: 啟動執行者; the usage lines; two-step 停止.
  3. 派工: type text, 預覽 (shows the exact text), 核准並送出.
  4. 執行者回報: 執行者自述 and VBear 讀檔核對 side by side.
  5. Codex 審查: start, wait; the report is plain text; 把意見轉給執行者… only
     fills the dispatch box.
  6. 合併與 push 關卡: conditions; commands appear only when open, copy only.
  7. 這個流程保存的資料: 刪除 is refused while the executor runs.
"""

from __future__ import annotations

import os
import time
import unittest

from tests import stream_fixtures as fx
from tests.test_flow_review_api import ReviewApiCase
from vbear import flows, risk_acceptance as ra


class _Harness(ReviewApiCase):
    steps = 0

    def step(self, text: str) -> None:
        type(self).steps += 1
        print(f"\n[{self.steps:02d}] {text}", flush=True)

    def say(self, text: str) -> None:
        print(f"     {text}", flush=True)

    def without_acceptance(self) -> None:
        """The fixture records an acceptance directly; take it away so the
        dialog's own path (preview, confirm) is what runs."""
        with flows.store.locked():
            data = flows.store.load()
            ev = data[self.fid]["events"]
            data[self.fid]["events"] = [e for e in ev if e["kind"] != "risk_acknowledged"]
            flows.store.save(data)
        ra._facts_cache.clear()

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#auth={self.token}"


class Walkthrough(_Harness):
    def test_walkthrough(self):
        self.without_acceptance()
        st, r = self.call(f"/api/flows/{self.fid}/executor")
        self.step("no acceptance yet: the executor cannot start")
        self.assertEqual(r["acceptance"]["state"], "none")
        self.assertFalse(r["can_start"])
        st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {})
        self.assertEqual((st, r["code"]), (409, "no_acceptance"))
        self.say(f"refused: {r['error']}")

        self.step("accept the residual risks: preview, then confirm with only the id")
        st, pre = self.call(f"/api/flows/{self.fid}/acceptance-preview", "POST", {"executor_model": fx.MODEL})
        self.assertEqual(st, 200, pre)
        self.assertEqual(len(pre["risk_text"]["zh"]["items"]), 3)
        self.assertEqual(len(pre["values"]["limits"]), 9)
        self.say(f"three risks, nine limits, text version {pre['values']['text_version']}, expires {pre['expires_at']:.0f}")
        st, r = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual(st, 200, r)
        st, again = self.call(f"/api/flows/{self.fid}/acceptance", "POST", {"preview_id": pre["preview_id"]})
        self.assertNotEqual(st, 200, "a preview is used once")
        self.say(f"the same preview again: {st} {again.get('code')}")
        self.assertEqual(self.executor_status()["acceptance"]["state"], "valid")

        self.step("start the managed executor, send one approved dispatch, read the report")
        self.start_executor()
        self.say(f"session {self.launch} live")
        self.commit_work("qa work")
        dispatch_id, entry = self.turn("QA：請完成工作")
        self.assertTrue(entry["valid"])
        self.say(f"dispatch {dispatch_id[:8]}: executor says {entry['report']['status']} at {entry['report']['head'][:10]}")
        self.say("VBear's own checks: " + ", ".join(f"{c['id']}={c['ok']}" for c in entry["checks"]))
        self.assertTrue(entry["latest"] and entry["usable"])

        self.step("a dispatch is not sent until it is approved")
        n = len(self.executor_status()["sessions"][-1]["status"].get("dispatches") or [])
        st, pre = self.call(f"/api/flows/{self.fid}/dispatch-preview", "POST",
                            {"launch_id": self.launch, "text": "第二則\u0001含控制字元"})
        self.assertEqual(st, 200, pre)
        self.assertTrue(pre["rewritten"])
        self.say(f"previewed (rewritten={pre['rewritten']}): {pre['text']!r}")
        time.sleep(0.5)
        self.assertEqual(len(self.executor_status()["sessions"][-1]["status"].get("dispatches") or []), n)

        self.step("ask Codex for a review of the latest commit")
        job, rv = self.run_review()
        self.say(f"round {rv['round']}: state {rv['state']}, outcome {rv['outcome']}, "
                 f"verdict {(rv.get('result') or {}).get('verdict')}")
        self.assertIn(rv["outcome"], ("valid", "invalid"))
        if rv["report"] and rv["report"]["text"]:
            self.assertEqual(rv["report"]["format"], "plain_text")
            st, d = self.call(f"/api/flows/{self.fid}/reviews/{job}/draft")
            if st == 200:
                self.say(f"opinion draft: {len(d['text'])} characters, format {d['format']}")

        self.step("the merge gate shows conditions; commands only when it is open")
        g = self.gate()
        for c in g["conditions"]:
            self.say(f"{c['id']}: {c['ok']}  {c['label']}")
        if not g["open"]:
            self.assertEqual(g["commands"], [])
        else:
            for c in g["commands"]:
                self.say(f"command (text only): {c['command']}")

        self.step("storage: this flow is listed, and cannot be deleted while the executor runs")
        usage = self.call("/api/flows/storage")[1]
        mine = next(x for x in usage["flows"] if x["flow_id"] == self.fid)
        self.say(f"{mine['bytes']} bytes, {mine['sessions']} session(s), {mine['reviews']} review(s), "
                 f"deletable={mine['deletable']}: {mine['reasons']}")
        self.assertFalse(mine["deletable"])
        st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.say(f"delete refused: {r['error']}")

        self.step("close the executor, then delete the flow")
        st, r = self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": self.launch})
        self.assertEqual(st, 200, r)
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["manifest_state"] == "ended", msg="ended")
        st, r = self.call(f"/api/flows/{self.fid}/delete", "POST", {"flow_id": self.fid})
        self.assertEqual(st, 200, r)
        self.say(f"deleted: {r['bytes']} bytes freed; removed {r['removed']}")
        self.assertEqual(self.call(f"/api/flows/{self.fid}")[0], 404)
        self.assertEqual(self.call("/api/flows/storage")[1]["used_bytes"], 0)
        print("\nWALKTHROUGH OK", flush=True)


@unittest.skipUnless(os.environ.get("VBEAR_QA_SERVE") == "1", "set VBEAR_QA_SERVE=1 to leave the console running")
class Serve(_Harness):
    def test_serve(self):
        self.without_acceptance()
        seconds = float(os.environ.get("VBEAR_QA_SECONDS", "3600"))
        print("\nVBear S2c QA console (synthetic Claude/Codex, throwaway state):", flush=True)
        print(f"  open   {self.url()}", flush=True)
        print(f"  state  {self.base}", flush=True)
        print(f"  flow   #/flows/{self.fid}", flush=True)
        print("  Ctrl-C to stop", flush=True)
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
