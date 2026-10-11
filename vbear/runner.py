"""The automation runner (S3 design 2, 3, 5, 6; v11.1): the console thread that,
for a flow in automatic mode, dispatches the approved plan, waits for the
turn, checks the executor's report, starts a review, forwards NEEDS WORK
comments to the executor and stops at the merge gate.

What it is and is not:

* It decides nothing the files and the daemon do not already say. The state
  of a flow is derived from its automation events (``derive``) and the
  daemon's answers on every tick; nothing else is kept. A restart of the
  console therefore resumes by reading, which is the recovery table of S3
  design 3: an intent event without its result is completed with the same
  ``dispatch_id`` or round (the daemon makes both idempotent) or, when the
  daemon says the work is already there, only recorded.
* Every action is three steps: an intent event, the daemon RPC, a result
  event. The daemon is also the enforcer: in automatic mode it accepts only
  the automation approval (S3-1), so a runner that is wrong cannot do what the
  mode does not allow.
* It never writes the quota-protected directories (the daemon's dispatch_prepare
  stores the text), never runs git, never starts an executor session and never
  calls ``pipeline_release``: continuing after a stop is the user's.
* One runner per state directory: ``<state>/runner.lock`` (flock).
* Anything it cannot read, or does not understand, is a stop (a hold plus an
  ``auto_stopped`` event with the reason), never a guess.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import threading
import time
import uuid

from . import acceptance, automation, config as cfg, flows, login_identity, risk_acceptance
from .api_error import ApiError
from .flow_executor import FlowExecutor
from .flow_review import FlowReview
from .runtime import pipeline_store, stream_flow
from .runtime import stream_protocol as sp

TICK_S = 2.0
BUSY_LIMIT_S = 60.0                       # an approval that has held its lock this long is not "in progress"
LOCK_NAME = "runner.lock"
MAX_TEXT_BYTES = 60 << 10                 # under the daemon's 64 KiB line, with room for the envelope
REPORT_REQUEST = ("\n\n---\n回報要求：完成後請用結構化輸出回報 status（done / blocked / needs_input）、head（你目前 HEAD 的"
                  "完整 commit）、tests.result（passed / failed / not_run）、tests.summary 與 notes。")
FORWARD_REQUEST = "\n\n---\n請依上面標明為資料的審查意見修正，修正後 commit，並重新回報。"
_WAITING = ("accepted", "writing", "written", "confirmed")
ABORT_MARK = "流程被停止，審查中止"          # daemon_review._review_hold: what a stop writes into the review's reasons


def derive(events: list[dict]) -> dict:
    """What the flow is waiting for, from its events alone: the cycle since
    the automatic mode was last switched on. {"step": ..., plus the ids the
    step needs}. ``auto_stopped`` events are barriers in the timeline and not
    steps: after the user continues, the step they interrupted is derived
    again."""
    start = 0
    for i, e in enumerate(events):
        if e.get("kind") == "automation_mode" and e.get("mode") == "auto":
            start = i + 1
    rel = [e for e in events[start:] if e.get("kind") in flows.AUTOMATION_KINDS]
    steps = [e for e in rel if e["kind"] != "auto_stopped"]
    if not steps:
        return {"step": "first_dispatch"}
    last = steps[-1]
    k = last["kind"]
    if k == "auto_dispatch_intent":
        before = steps[-2] if len(steps) >= 2 else None
        forward = before["job_id"] if before and before["kind"] == "auto_review_result" \
            and before["verdict"] == "NEEDS WORK" else None
        return {"step": "resume_dispatch", "dispatch_id": last["dispatch_id"], "sha256": last["text_sha256"],
                "length": last["length"], "forward_job": forward}
    if k == "auto_dispatch_sent":
        return {"step": "await_turn", "dispatch_id": last["dispatch_id"]}
    if k == "auto_report":
        return {"step": "start_review", "dispatch_id": last["dispatch_id"], "commit": last["commit"]}
    if k == "auto_review_intent":
        return {"step": "resume_review", "round": last["round"], "commit": last["commit"]}
    if k == "auto_review_started":
        return {"step": "await_review", "round": last["round"], "job_id": last["job_id"],
                "commit": last["commit"] if "commit" in last else None}
    if k == "auto_review_aborted":
        # S3 design 6: the stop ended that round (it is invalid and a round is never run twice); after the
        # user's continue the same commit is reviewed again in the NEXT round, if HEAD is still it
        return {"step": "start_review", "commit": last["commit"], "aborted_round": last["round"]}
    if k == "auto_review_result":
        if last["verdict"] == "NEEDS WORK":
            return {"step": "forward", "round": last["round"], "job_id": last["job_id"], "commit": last["commit"]}
        if last["verdict"] == "PASS":
            return {"step": "gate", "round": last["round"], "job_id": last["job_id"], "commit": last["commit"],
                    "announced": rel[-1]["kind"] == "auto_stopped" and rel[-1]["reason_code"] == "awaiting_merge"}
        return {"step": "blocked", "round": last["round"], "job_id": last["job_id"]}
    return {"step": "unknown"}


STEP_LABELS = {
    "first_dispatch": ("下一步：把核准的計畫全文派給執行者", "等執行者 session 回到 idle 就派工"),
    "resume_dispatch": ("派工意圖已寫入，確認它是否已送出", "以同一個派工 id 補完，不會重複派工"),
    "await_turn": ("等執行者這一輪結束，並核對它的回報", "回報通過 VBear 讀檔核對後啟動審查"),
    "start_review": ("下一步：啟動 Codex 審查回報的 commit", "審查次數與上限一併檢查"),
    "resume_review": ("審查意圖已寫入，確認它是否已啟動", "以同一個輪次補完，不會重複審查"),
    "await_review": ("等 Codex 審查結束", "有效的結論才會被採用"),
    "forward": ("下一步：把審查意見（標明為資料）轉給執行者", "不再逐則核准；全文過長就停止，不截斷"),
    "gate": ("審查通過，停在合併關卡", "合併與 push 由你決定，VBear 只顯示指令"),
    "blocked": ("審查的結論是 BLOCKED，等你處理", "停止後不會自動恢復"),
    "unknown": ("狀態無法對應", "停止，等你處理"),
}


def describe(events: list[dict]) -> dict:
    """What the screen says about the cycle: the step, in words, and what comes after."""
    state = derive(events)
    label, after = STEP_LABELS.get(state["step"], STEP_LABELS["unknown"])
    return {"step": state["step"], "label": label, "after": after,
            "awaiting_merge": state["step"] == "gate" and bool(state.get("announced"))}


class AutomationRunner:
    def __init__(self, executor: FlowExecutor, review: FlowReview, *, clock=time.time, monotonic=time.monotonic):
        self.executor = executor
        self.review = review
        self.clock = clock                    # wall time: what the limits are compared with
        self.monotonic = monotonic            # durations (how long an approval has been "in progress")
        self._lock_fd: int | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self.last_error: str | None = None
        self.log: list[str] = []
        self._why: tuple[str, str] | None = None
        self._busy_since: dict[str, float] = {}

    # ---- lifecycle -------------------------------------------------------------------------------------

    def acquire(self) -> bool:
        """The one runner of this state directory. False when another console
        has it (then this one runs no automatic flow)."""
        if self._lock_fd is not None:
            return True
        cfg.ensure_state_dir()
        path = cfg.state_dir() / LOCK_NAME
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def release(self) -> None:
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)                       # closing releases the flock
            finally:
                self._lock_fd = None

    def start(self) -> bool:
        if not self.acquire():
            self.last_error = "另一個主控台已經在執行自動流程（runner.lock 被占用）"
            return False
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="vbear-runner", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None
        self.release()

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception as exc:                          # never let the thread die
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stopping.wait(TICK_S)

    # ---- one pass ----------------------------------------------------------------------------------------

    def tick(self) -> dict[str, str]:
        """One step for every flow in automatic mode: {flow_id: what it did}."""
        base = cfg.state_dir()
        try:
            names = pipeline_store.mode_flows(base)
        except pipeline_store.StoreRefused as exc:
            self.last_error = f"modes/ 無法列出：{exc}"
            return {}
        out = {}
        for flow_id in names:
            try:
                with self.executor._lock(flow_id):
                    out[flow_id] = self.step(flow_id)
            except KeyError:
                out[flow_id] = "no_flow"
            except Exception as exc:                          # one flow's trouble stops that flow, loudly
                out[flow_id] = self._stop_quietly(flow_id, "runner_error", f"runner 發生未預期的錯誤（{type(exc).__name__}）")
        return out

    # ---- events and stops --------------------------------------------------------------------------------

    @staticmethod
    def _mode_event_present(events: list[dict], seq: int) -> bool:
        return any(e["kind"] == "automation_mode" and e.get("mode") == "auto" and e.get("approval_seq") == seq
                   for e in events)

    def _event(self, flow_id: str, kind: str, fields: dict) -> None:
        flows.append_automation_event(flow_id, kind, fields)

    def _last_event(self, flow_id: str) -> dict | None:
        events = flows.get_flow(flow_id)["events"]
        return events[-1] if events else None

    def _stop(self, flow_id: str, code: str, detail: str) -> str:
        """Stop: the daemon holds the flow, then the event says why. A stop
        with the same code and detail as the last event is not written again."""
        detail = detail[:300]
        try:
            if not pipeline_store.hold_marker_exists(cfg.state_dir(), flow_id):
                self.executor._call("pipeline_hold", pipeline=flow_id, reason=f"自動執行停止：{detail}"[:256])
        except ApiError as exc:
            detail = f"{detail}（要求 daemon 停止時失敗：{exc}）"[:300]
        last = self._last_event(flow_id)
        if not (last and last["kind"] == "auto_stopped" and last["reason_code"] == code and last["detail"] == detail):
            try:
                self._event(flow_id, "auto_stopped", {"reason_code": code, "detail": detail})
            except ValueError:
                pass
        return f"stopped:{code}"

    def _stop_quietly(self, flow_id: str, code: str, detail: str) -> str:
        try:
            return self._stop(flow_id, code, detail)
        except Exception:
            return f"stopped:{code}"

    # ---- one flow --------------------------------------------------------------------------------------------

    def _checked(self, flow_id: str) -> tuple[dict | None, tuple[str, str] | None]:
        """Fresh reads of everything a stop for "the approval, the acceptance, the mode or the record do not agree"
        would rest on: (context, None) when they agree, (None, (code, why)) when they do not."""
        base = cfg.state_dir()
        flow = flows.get_flow(flow_id)
        mode = pipeline_store.mode_info(base, flow_id)
        if mode["mode"] != "auto":
            return {"manual": True}, None
        if mode["problem"]:
            return None, ("mode_record", f"自動執行的模式紀錄不可信（{mode['problem']}）")
        acc = risk_acceptance.status(flow)
        if acc["state"] != "valid":
            return None, ("acceptance", f"風險接受目前不算數（{acc.get('reason') or acc['state']}）")
        seq = acceptance.approval_seq(mode["approval_id"])
        events = flow["events"]
        if seq is None or not (1 <= seq <= len(events)) or not acceptance.is_auto_event(events[seq - 1]):
            return None, ("approval", "找不到自動執行核准的那一筆接受")
        newest = None
        try:
            key = login_identity.load_login_key(base)
            newest = acceptance.latest_valid(flow, key.key_id)
        except login_identity.KeyUnavailable as exc:
            return None, ("acceptance", f"登入指紋金鑰不可用（{exc}）")
        if newest is None or newest.get("seq") != seq:
            return None, ("approval_replaced", "自動執行核准的那一筆接受已被更新的接受取代")
        # The mode must be on the record: an "auto" the daemon holds that no automation_mode event of this approval
        # accounts for is not something to act on (the switch-on could not be audited)
        if not self._mode_event_present(events, seq):
            return None, ("mode_event_missing", "daemon 的模式是自動，但時間軸沒有對應這次核准的開啟紀錄")
        return {"flow": flow, "mode": mode, "events": events, "approval_event": events[seq - 1], "seq": seq,
                "approval": {"kind": "automation", "id": mode["approval_id"]}}, None

    def step(self, flow_id: str) -> str:
        base = cfg.state_dir()
        mode = pipeline_store.mode_info(base, flow_id)
        if mode["mode"] != "auto":
            self._busy_since.pop(flow_id, None)
            return "manual"
        hold = pipeline_store.hold_info(base, flow_id)
        if hold["held"]:
            last = self._last_event(flow_id)
            if not (last and last["kind"] == "auto_stopped"):         # a stop the daemon decided: say so once
                try:
                    self._event(flow_id, "auto_stopped", {"reason_code": "daemon_hold",
                                                           "detail": (hold["reason"] or "流程已停止")[:300]})
                except ValueError:
                    pass
            return "held"
        ctx, problem = self._checked(flow_id)
        if problem is not None:
            # These reads were made one after another, and an approval in progress (in this console or another)
            # changes exactly these things. No stop is concluded from them alone: with the approval lock held
            # (nothing is then being approved) they are read again, and only what still does not agree stops the
            # flow. Busy = an approval is in progress: wait (for a bounded time). Not there / not ours = stop.
            with automation.try_plan_lock(base, flow_id) as (lock, why):
                if lock == automation.BUSY:
                    since = self._busy_since.setdefault(flow_id, self.monotonic())
                    if self.monotonic() - since > BUSY_LIMIT_S:
                        self._busy_since.pop(flow_id, None)
                        return self._stop(flow_id, "approval_stuck",
                                          f"核准已經進行超過 {int(BUSY_LIMIT_S)} 秒仍沒有結束，停止並請你檢查")
                    return "waiting:核准進行中"
                self._busy_since.pop(flow_id, None)
                if lock == automation.UNAVAILABLE:
                    return self._stop(flow_id, "approval_lock_unavailable", why)
                ctx, problem = self._checked(flow_id)
            if problem is not None:
                return self._stop(flow_id, *problem)
        self._busy_since.pop(flow_id, None)
        if ctx.get("manual"):
            return "manual"
        flow, events, approval_event, approval = ctx["flow"], ctx["events"], ctx["approval_event"], ctx["approval"]
        state = derive(events)
        step = state["step"]
        if step == "first_dispatch":
            return self._dispatch(flow_id, approval, approval_event, None, None)
        if step == "resume_dispatch":
            return self._resume_dispatch(flow_id, approval, approval_event, state)
        if step == "await_turn":
            return self._await_turn(flow_id, state)
        if step == "start_review":
            return self._start_review(flow_id, approval, state)
        if step == "resume_review":
            return self._resume_review(flow_id, approval, state)
        if step == "await_review":
            return self._await_review(flow_id, state)
        if step == "forward":
            return self._dispatch(flow_id, approval, approval_event, state["job_id"], state)
        if step == "gate":
            return self._gate(flow_id, state)
        if step == "blocked":
            return self._stop(flow_id, "review_blocked", "審查的結論是 BLOCKED，要由你處理")
        return self._stop(flow_id, "state_inconsistent", "恢復時狀態不一致")

    # -- the text of a dispatch ---------------------------------------------------------------------------

    def _text(self, flow_id: str, approval_event: dict, forward_job: str | None) -> str | None:
        """The dispatch text, or None (the caller stops) with ``self._why`` set. Deterministic: the same inputs
        give the same text, which is what lets a recovery check it against the intent's hash."""
        try:
            if forward_job is None:
                plan = automation.read_plan(cfg.state_dir(), flow_id, sha256=approval_event["plan_sha256"],
                                            size=approval_event["plan_bytes"])
                text = plan + REPORT_REQUEST
            else:
                draft = self.review.opinion_draft(flow_id, forward_job)
        except ApiError as exc:
            self._why = (exc.code if exc.code.startswith(("plan_", "no_")) else "text_unavailable",
                         f"派工全文無法產生：{exc}")
            return None
        if forward_job is not None:
            if draft.get("truncated"):
                self._why = ("review_too_long", "要轉送的審查意見過長，派工全文會超過上限（不截斷），要由你處理")
                return None
            text = draft["text"] + FORWARD_REQUEST
        text = sp.sanitize(text)
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            self._why = ("text_too_long", "派工全文超過 64 KiB 上限（不截斷），要由你處理")
            return None
        return text

    def _limits_ok(self, flow_id: str, *, review: bool = False) -> str | None:
        try:
            ctx = stream_flow.load(cfg.state_dir(), flow_id)
            stream_flow.check_limits(ctx, now=self.clock(), counting_dispatch=not review,
                                     counting_review=review)
        except stream_flow.FlowRefused as exc:
            return str(exc)
        return None

    def _session(self, flow_id: str) -> tuple[str | None, str]:
        """(launch_id, why not): the live idle session the next dispatch goes to."""
        st = self.executor.status(flow_id)
        launch = st.get("current_launch_id")
        if not launch:
            return None, "沒有執行中的執行者 session（啟動執行者要由你來做）"
        ready, why = self.executor._session_readiness(flow_id, launch)
        return (launch, "") if ready else (None, why)

    # -- dispatch ------------------------------------------------------------------------------------------------

    def _dispatch(self, flow_id, approval, approval_event, forward_job, state) -> str:
        self._why = None
        text = self._text(flow_id, approval_event, forward_job)
        if text is None:
            return self._stop(flow_id, *self._why)
        problem = self._limits_ok(flow_id)
        if problem:
            return self._stop(flow_id, "limit", problem)
        launch, why = self._session(flow_id)
        if launch is None:
            return f"waiting:{why}"
        d = str(uuid.uuid4())
        raw = text.encode("utf-8")
        self._event(flow_id, "auto_dispatch_intent",
                    {"dispatch_id": d, "text_sha256": hashlib.sha256(raw).hexdigest(), "length": len(raw)})
        return self._prepare_and_send(flow_id, launch, d, text, approval)

    def _prepare_and_send(self, flow_id, launch, d, text, approval) -> str:
        fields = {"launch_id": launch, "pipeline": flow_id, "dispatch_id": d}
        try:
            self.executor._call("dispatch_prepare", timeout=30.0, text=text, approval=approval, **fields)
            self.executor._send(fields)
        except ApiError as exc:
            return self._stop(flow_id, "dispatch_refused", f"派工被拒或沒有送出：{exc}")
        self._event(flow_id, "auto_dispatch_sent", {"dispatch_id": d})
        return "dispatched"

    def _resume_dispatch(self, flow_id, approval, approval_event, state) -> str:
        """An intent without its "sent": the daemon's record decides (S3 design 3)."""
        d = state["dispatch_id"]
        entry = self._entry(flow_id, d)
        if entry is not None:
            status = entry["status"]
            if status == "writing":
                return "waiting:派工還在寫入中"
            if status == "accepted":                          # prepared in some session, not sent: send it there
                try:
                    self.executor._send({"launch_id": entry["launch_id"], "pipeline": flow_id, "dispatch_id": d})
                except ApiError as exc:
                    return self._stop(flow_id, "dispatch_refused", f"派工被拒或沒有送出：{exc}")
                self._event(flow_id, "auto_dispatch_sent", {"dispatch_id": d})
                return "dispatched"
            if status in ("written", "confirmed", "ended"):
                self._event(flow_id, "auto_dispatch_sent", {"dispatch_id": d})
                return "recorded"
            return self._stop(flow_id, "dispatch_failed", f"派工 {d[:8]} 沒有送達（狀態 {status}），不重送")
        # not prepared anywhere: the same text again, which must be what the intent says
        self._why = None
        text = self._text(flow_id, approval_event, state.get("forward_job"))
        if text is None:
            return self._stop(flow_id, *self._why)
        raw = text.encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != state["sha256"] or len(raw) != state["length"]:
            return self._stop(flow_id, "text_changed", "恢復時重新產生的派工全文與意圖紀錄不符，不送出")
        launch, why = self._session(flow_id)
        if launch is None:
            return f"waiting:{why}"
        return self._prepare_and_send(flow_id, launch, d, text, approval)

    # -- the turn --------------------------------------------------------------------------------------------

    def _entry(self, flow_id: str, dispatch_id: str) -> dict | None:
        reports = self.review.reports(flow_id)
        return next((e for e in reports["reports"] if e["dispatch_id"] == dispatch_id), None)

    def _await_turn(self, flow_id, state) -> str:
        d = state["dispatch_id"]
        try:
            entry = self._entry(flow_id, d)
        except ApiError as exc:
            return self._stop(flow_id, "state_unreadable", f"無法讀取派工的狀態：{exc}")
        if entry is None:
            return self._stop(flow_id, "dispatch_missing", f"找不到派工 {d[:8]} 的紀錄")
        if entry["status"] in _WAITING:
            return "waiting:回合進行中"
        if entry["status"] != "ended":
            return self._stop(flow_id, "turn_failed", f"這一輪沒有正常結束（狀態 {entry['status']}）")
        if not entry["valid"]:
            return self._stop(flow_id, "turn_invalid", "這一輪不是有效回合：" + "；".join(entry["reasons"] or ["原因不明"]))
        report = entry["report"]
        if not isinstance(report, dict):
            return self._stop(flow_id, "no_report", "沒有有效的執行者回報")
        if report.get("status") != "done":
            return self._stop(flow_id, f"report_{report.get('status')}", f"執行者回報的狀態是 {report.get('status')}")
        tests = (report.get("tests") or {}).get("result")
        if tests != "passed":
            return self._stop(flow_id, "tests_not_passed", f"執行者回報的測試結果是 {tests}（不送審，交給你決定）")
        if not entry["latest"]:
            return self._stop(flow_id, "state_inconsistent", "這一輪的回報不是最新的回報")
        if not entry["usable"]:
            bad = [c["label"] + (f"（{c['detail']}）" if c["detail"] else "") for c in entry["checks"] or []
                   if c["ok"] is not True]
            return self._stop(flow_id, "report_unchecked", "VBear 讀檔核對沒有全部通過：" + "；".join(bad))
        self._event(flow_id, "auto_report", {"dispatch_id": d, "commit": report["head"], "status": "done",
                                             "tests_result": "passed"})
        return "reported"

    # -- the review --------------------------------------------------------------------------------------------

    def _start_review(self, flow_id, approval, state) -> str:
        problem = self._limits_ok(flow_id, review=True)
        if problem:
            return self._stop(flow_id, "limit", problem)
        try:
            rnd, commit = self.review.plan_start(flow_id)
        except ApiError as exc:
            return self._stop(flow_id, f"review_{exc.code}", f"不能啟動審查：{exc}")
        if commit != state["commit"]:
            return self._stop(flow_id, "state_inconsistent", "要審的 commit 與回報不一致")
        self._event(flow_id, "auto_review_intent", {"round": rnd, "commit": commit})
        return self._send_review(flow_id, approval, rnd, commit)

    def _send_review(self, flow_id, approval, rnd, commit) -> str:
        try:
            res = self.executor._call("review_start", timeout=120.0, pipeline=flow_id, round=rnd, commit=commit,
                                      approval=approval)
        except ApiError as exc:
            return self._stop(flow_id, "review_refused", f"審查被拒：{exc}")
        job = res.get("job_id")
        if not (isinstance(job, str) and flows._JOB_RE.match(job)):
            return self._stop(flow_id, "state_inconsistent", "daemon 的審查回覆沒有 job id")
        self._event(flow_id, "auto_review_started", {"round": rnd, "job_id": job})
        return "review_started"

    def _resume_review(self, flow_id, approval, state) -> str:
        rnd = state["round"]
        mine = next((m for m in self.review._review_manifests(flows.get_flow(flow_id)) if m["round"] == rnd), None)
        if mine is not None:
            if mine["commit"] != state["commit"]:
                return self._stop(flow_id, "state_inconsistent", f"輪次 {rnd} 的審查不是針對意圖的 commit")
            self._event(flow_id, "auto_review_started", {"round": rnd, "job_id": mine["job_id"]})
            return "recorded"
        problem = self._limits_ok(flow_id, review=True)
        if problem:
            return self._stop(flow_id, "limit", problem)
        return self._send_review(flow_id, approval, rnd, state["commit"])

    def _await_review(self, flow_id, state) -> str:
        try:
            entries = self.review.reviews(flow_id)["reviews"]
        except ApiError as exc:
            return self._stop(flow_id, "state_unreadable", f"無法讀取審查的狀態：{exc}")
        entry = next((x for x in entries if x["job_id"] == state["job_id"]), None)
        if entry is None:
            return self._stop(flow_id, "review_missing", f"找不到審查 {state['job_id']}")
        if entry["state"] in ("prepared", "launching", "running"):
            return "waiting:審查進行中"
        if entry["state"] == "manual_review" or entry["outcome"] == "manual_review":
            return self._stop(flow_id, "review_manual", "審查需要人工處理（manual_review）")
        if entry["outcome"] == "invalid" and any(ABORT_MARK in str(r) for r in entry.get("invalid_reasons") or []):
            self._event(flow_id, "auto_review_aborted",
                        {"round": entry["round"], "job_id": entry["job_id"], "commit": entry["commit"]})
            return "review_aborted"
        if entry["outcome"] != "valid":
            return self._stop(flow_id, "review_invalid", "審查無效：" + "；".join(entry.get("invalid_reasons") or ["原因不明"]))
        if entry.get("record") != "complete":
            return self._stop(flow_id, "review_record", "審查紀錄不完整")
        verdict = (entry.get("result") or {}).get("verdict")
        if verdict not in flows.AUTO_VERDICTS:
            return self._stop(flow_id, "review_verdict", "審查沒有可辨識的結論")
        self._event(flow_id, "auto_review_result", {"round": entry["round"], "job_id": entry["job_id"],
                                                     "commit": entry["commit"], "verdict": verdict, "valid": True})
        return f"review_result:{verdict}"

    # -- the merge gate --------------------------------------------------------------------------------------

    def _gate(self, flow_id, state) -> str:
        if state.get("announced"):
            return "awaiting_merge"
        gate = self.review.merge_gate(flow_id)
        if not gate["open"]:
            bad = [c["label"] + (f"（{c['detail']}）" if c["detail"] else "") for c in gate["conditions"]
                   if c["ok"] is not True]
            return self._stop(flow_id, "gate_closed", "審查通過，但合併關卡的條件沒有全部成立：" + "；".join(bad))
        self._event(flow_id, "auto_stopped", {"reason_code": "awaiting_merge",
                                               "detail": "審查通過，各項核對成立；停在合併關卡等你"})
        return "awaiting_merge"
