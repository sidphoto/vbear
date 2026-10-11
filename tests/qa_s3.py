"""S3 QA harness (design 10, "the approval screen checked by hand"): a throwaway
console and a real runtime daemon in a temporary state directory with the
synthetic Claude and Codex of the flow tests. No model, no real account, no
real ~/.vbear, no network.

  python3 -m unittest tests.qa_s3.Walkthrough -v        the scripted run (every step printed)
  VBEAR_QA_SERVE=1 python3 -m unittest tests.qa_s3.Serve -v
      the same environment left running for a person or a browser tool, with
      the runner thread started, so approving the plan in the browser really
      sets the loop going. Optional VBEAR_QA_NEEDS_WORK=1: the first review
      says NEEDS WORK and a helper commits the "fix", so the whole cycle
      (dispatch, report, review, forward, review, merge gate) can be watched.
      Stop with Ctrl-C (or set VBEAR_QA_SECONDS).

What to check in the browser (the flow page, 「流程」 -> the flow):
  1. 自動執行 -> 核准計畫並開啟自動執行…: the plan text in full; the eight
     parts A–H; the fixed rule; the three residual risks in full; both
     account prefixes; nine limits (elapsed 4 h); the tick gates the button.
  2. Compare with the record: the preview file under <state>/previews/<id>.json
     (printed paths) and, after approving, the risk_acknowledged event in
     <state>/flows.json (its auto_text_version, plan_sha256 equal what the
     dialog showed; automation/<flow>/plan.txt is the text shown).
  3. 串流執行者 -> 啟動執行者 (a human act), then watch 目前步驟 change, the
     timeline name each event 自動（runner）, usage against limits.
  4. In automatic mode: the dispatch box, review start and manual acceptance
     are off and say why.
  5. 停止流程 (asked twice): stopped; nothing resumes by itself; 切回手動.
  6. The home page 「需要你處理」 lists the stopped flow with its reason and
     the flow waiting at the merge gate.
"""

from __future__ import annotations

import json
import os
import threading
import time
import unittest

from tests.test_automation_runner import RunnerCase
from vbear import flows


class _Harness(RunnerCase):
    steps = 0

    def step(self, text: str) -> None:
        type(self).steps += 1
        print(f"\n[{self.steps:02d}] {text}", flush=True)

    def say(self, text: str) -> None:
        print(f"     {text}", flush=True)

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#auth={self.token}"


class Walkthrough(_Harness):
    def test_walkthrough(self):
        self.step("manual flow: nothing runs by itself")
        self.assertEqual(self.runner.tick(), {})
        st, au = self.call(f"/api/flows/{self.fid}/automation")
        self.assertEqual((st, au["mode"]), (200, "manual"))

        self.step("approve the plan and turn automatic mode on (one preview, one confirmation)")
        st, pre = self.call(f"/api/flows/{self.fid}/automation-preview", "POST", {})
        self.assertEqual(st, 200, pre)
        self.say(f"plan {pre['plan_bytes']} bytes, sha256 {pre['plan_sha256'][:16]}…; "
                 f"{len(pre['auto_text']['zh']['sections'])} parts; {len(pre['values']['limits'])} limits; "
                 f"fixed rule: {pre['fixed_rules'][0]}")
        self.say(f"executor account {pre['values']['executor_account']}, reviewer account {pre['values']['review_account']}")
        rec = json.loads((self.base / "previews" / f"{pre['preview_id']}.json").read_text())
        self.assertEqual(rec["data"]["plan_text"], pre["plan_text"])               # the record is what the screen shows
        self.assertEqual(rec["data"]["fields"]["limits"]["max_elapsed_h"], 4)
        st, r = self.call(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
        self.assertEqual(st, 200, r)
        ev = next(e for e in reversed(flows.get_flow(self.fid)["events"]) if e["kind"] == "risk_acknowledged")
        self.assertEqual((ev["plan_sha256"], ev["auto_text_version"]), (pre["plan_sha256"], pre["auto_text"]["zh"]["version"]))
        self.assertEqual((self.base / "automation" / self.fid / "plan.txt").read_text(), pre["plan_text"])
        self.say(f"recorded as event {ev['seq']}; approval id {r['approval_id']}")

        self.step("manual actions are refused while it is on")
        st, r = self.call(f"/api/flows/{self.fid}/review", "POST", {})
        self.assertEqual((st, r["code"]), (409, "automation_active"))
        self.say(r["error"])

        self.step("the user starts the executor; the loop runs: NEEDS WORK, a fix, PASS, the merge gate")
        self.start_executor()
        self.commit_work("first")
        self.fake_mode("needs_work")
        self.run_until(lambda: "auto_review_result" in self.kinds(), "the first verdict")
        self.say("first verdict NEEDS WORK; the executor 'fixes' it and the reviewer will pass")
        self.commit_work("fix")
        self.fake_mode("ok")
        self.run_until(lambda: self.last_event()["kind"] == "auto_stopped"
                       and self.last_event()["reason_code"] == "awaiting_merge", "the merge gate")
        for e in flows.get_flow(self.fid)["events"]:
            if e["kind"].startswith("auto_") or e["kind"] == "automation_mode":
                self.say(f"{e['seq']:>3}  {e['source']:<10} {e['kind']}")
        g = self.gate()
        self.say(f"merge gate open={g['open']}; commands (text only): {len(g['commands'])}")
        self.assertTrue(g["open"])

        self.step("the flow view says it is waiting for you")
        st, v = self.call(f"/api/flows/{self.fid}")
        self.assertTrue(v["flow"]["attention"])
        self.say(v["flow"]["attention_reason"])
        print("\nS3 WALKTHROUGH OK", flush=True)


@unittest.skipUnless(os.environ.get("VBEAR_QA_SERVE") == "1", "set VBEAR_QA_SERVE=1 to leave the console running")
class Serve(_Harness):
    def test_serve(self):
        seconds = float(os.environ.get("VBEAR_QA_SECONDS", "3600"))
        stop = threading.Event()
        # The synthetic work directory needs a commit the executor "has made": without one the executor's report
        # does not match the files and the flow is (rightly) stopped on the first turn (AGY QA).
        self.commit_work("initial work")
        started = self.console.runner.start()
        helper = None
        if os.environ.get("VBEAR_QA_NEEDS_WORK") == "1":
            self.fake_mode("needs_work")

            def autopilot():
                fixed = False
                while not stop.is_set():
                    try:
                        events = flows.get_flow(self.fid)["events"]
                        if not fixed and any(e["kind"] == "auto_review_result" and e["verdict"] == "NEEDS WORK"
                                             for e in events):
                            self.commit_work("fix")
                            self.fake_mode("ok")
                            fixed = True
                    except Exception:
                        pass
                    time.sleep(0.3)
            helper = threading.Thread(target=autopilot, daemon=True)
            helper.start()
        print("\nVBear S3 QA console (synthetic Claude/Codex, throwaway state):", flush=True)
        print(f"  open   {self.url()}", flush=True)
        print(f"  state  {self.base}   (previews/, flows.json, automation/{self.fid}/plan.txt)", flush=True)
        print(f"  flow   #/flows/{self.fid}", flush=True)
        print(f"  runner thread: {'running' if started else 'NOT running'}", flush=True)
        print("  Ctrl-C to stop", flush=True)
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            self.console.runner.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
