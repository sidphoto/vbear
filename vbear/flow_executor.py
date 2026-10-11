"""A flow's stream executor and its dispatches, as the console serves them
(design 2.1, 3.1, 3.2, 6, 7, 10; S2c-2).

The console decides nothing about the executor that the daemon does not check
again: it prepares a launch, asks the daemon to open it, previews and sends
dispatches, and reads what the daemon and the files say. What it adds is the
order the design demands:

  * start: a valid acceptance first; the pinned Claude Code must be the version
    that was accepted; then prepare (the console writes the launch's manifest
    and settings; the daemon counts them when it opens the launch), then
    open_stream. A launch that was prepared and not opened is removed.
  * dispatch: the user previews a text; the server keeps the sanitised text
    (design 3.3) and its hash under a random id. The approval carries only
    that id. In one flow-wide critical section the record is consumed and the
    facts are looked at again (the acceptance still valid, the session live
    and idle, the flow not stopped); then dispatch_prepare and stream_send, in
    that order, with the stored text. Anything that does not fit is a 409 and
    the preview is void.
  * status: one read model per flow for the screen, from the files and the
    daemon: the acceptance, the stop and why, the accounting against the
    limits, every failure with whether it was released, every stream session
    with its dispatches (the executor's own report apart from VBear's file
    checks), and the worst-case counting statement of design v29.7.

Nothing here runs git, a shell or a model.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from . import (acceptance, config as cfg, daemon_client, flows, git_head, login_identity, previews, risk_acceptance,
               tasks)
from .api_error import ApiError
from .runtime import agent_sessions, pipeline_store, stream_flow
from .runtime import stream_protocol as sp
from .daemon_client import DaemonError

DISPATCH_KEYS = frozenset({"launch_id", "text"})
SEND_ATTEMPTS = 3
# a review the daemon is finishing may have its outcome in the manifest a moment before result.json; the screens
# give it this long (stream_flow.settling) before they call the record missing or damaged
REVIEW_SETTLE_S = 2.0
SEND_PAUSE = 0.3
LAUNCH_RE = agent_sessions.LAUNCH_RE


def _daemon(exc: DaemonError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def ordered_sessions(manifests: list[dict]) -> tuple[list[dict], str | None]:
    """The flow's stream sessions oldest first, by the time the daemon-side
    manifest says they were created, never by name (a launch id is random).
    (sessions, problem): ``problem`` is a sentence when the order cannot be
    told (a time that is missing, not a finite number, or the same for two
    sessions); nothing then treats any session as "the newest" (fail closed,
    Gemini S2c-3 review). The list is still returned, in a stable order, for
    showing."""
    def key(m):
        c = m.get("created")
        ok = isinstance(c, (int, float)) and not isinstance(c, bool) and c == c and abs(c) != float("inf")
        return (0 if ok else 1, c if ok else 0.0, m.get("launch_id", ""))
    ordered = sorted(manifests, key=key)
    times = [m.get("created") for m in ordered]
    bad = [m.get("launch_id") for m in ordered
           if not (isinstance(m.get("created"), (int, float)) and not isinstance(m.get("created"), bool)
                   and m["created"] == m["created"] and abs(m["created"]) != float("inf"))]
    if bad:
        return ordered, f"session {bad[0]} 沒有可用的建立時間，無法判斷哪一個是最新的"
    if len(manifests) > 1 and len(set(times)) != len(times):
        return ordered, "有兩個 session 的建立時間相同，無法判斷哪一個是最新的"
    return ordered, None


class FlowExecutor:
    def __init__(self, runtime, store: previews.PreviewStore, *, managed_root, host=None):
        self.runtime, self.store = runtime, store
        self.managed_root = Path(managed_root)
        self.host = host
        self._locks: dict[str, threading.Lock] = {}
        self._mutex = threading.Lock()

    def _host(self):
        return self.host or risk_acceptance.DEFAULT_HOST

    def _lock(self, flow_id: str) -> threading.Lock:
        """The flow's critical section (design 3.1: "the same flow lock")."""
        with self._mutex:
            return self._locks.setdefault(flow_id, threading.Lock())

    def _call(self, op: str, **fields) -> dict:
        try:
            return daemon_client.call(self.runtime, op, **fields)
        except DaemonError as exc:
            raise _daemon(exc) from exc

    # ---- shared checks -------------------------------------------------------------------------------

    @staticmethod
    def _flow(flow_id: str) -> dict:
        try:
            return flows.get_flow(flow_id)
        except KeyError:
            raise ApiError(404, "no_flow", "找不到這個流程") from None

    @staticmethod
    def _valid_acceptance(flow: dict) -> dict:
        """The newest acceptance that counts now, or 409 "no_acceptance" that
        says why not."""
        state = cfg.state_dir()
        try:
            key_id = login_identity.load_login_key(state).key_id
        except login_identity.KeyUnavailable as exc:
            raise ApiError(409, "no_acceptance", f"沒有有效的風險接受（{exc}），請先接受殘餘風險") from exc
        acc = acceptance.latest_valid(flow, key_id)
        if acc is None:
            raise ApiError(409, "no_acceptance", "這個流程沒有有效的風險接受，請先接受殘餘風險")
        return acc

    @staticmethod
    def _workdir(flow: dict) -> str:
        try:
            task = tasks.get_task(flow["task_id"])
        except tasks.TaskStorageError as exc:
            raise ApiError(409, "no_workdir", f"任務卡無法讀取（{exc}）") from exc
        workdir = task.get("workdir") if task else None
        if not (isinstance(workdir, str) and workdir):
            raise ApiError(409, "no_workdir", "這張任務卡沒有工作目錄，無法啟動執行者")
        return workdir

    @staticmethod
    def _sessions(flow_id: str, started: bool = True) -> list[dict]:
        try:
            return stream_flow.flow_sessions(cfg.state_dir(), flow_id, started=started)
        except stream_flow.FlowRefused as exc:
            raise ApiError(409, exc.code, f"無法核對這個流程的 session（{exc}）") from exc

    def _own_launch(self, flow_id: str, launch_id) -> dict:
        if not (isinstance(launch_id, str) and LAUNCH_RE.match(launch_id)):
            raise ApiError(400, "bad_request", "launch_id 格式不符")
        for m in self._sessions(flow_id, started=True):
            if m["launch_id"] == launch_id:
                return m
        raise ApiError(404, "no_session", "這個流程沒有這個串流 session")

    # ---- the executor ----------------------------------------------------------------------------------

    def start(self, flow_id: str, body) -> dict:
        """Prepare and open a stream executor session for the flow."""
        if body not in (None, {}):
            raise ApiError(400, "bad_request", "不接受任何欄位：版本與模型取自風險接受")
        with self._lock(flow_id):
            flow = self._flow(flow_id)
            acc = self._valid_acceptance(flow)
            base = cfg.state_dir()
            hold = pipeline_store.hold_info(base, flow_id)
            if hold["held"]:
                raise ApiError(409, "held", f"這個流程已停止（{hold['reason']}），要先按「繼續」")
            workdir = self._workdir(flow)
            binary, version, why = self._host().claude_binary(workdir)
            if binary is None:
                raise ApiError(409, "claude_version", f"讀不到 Claude Code 的版本（{why}）")
            if version != acc["executor_claude_version"]:
                raise ApiError(409, "reaccept", f"Claude Code 現在是 {version}，接受時是 "
                               f"{acc['executor_claude_version']}，請重新接受")
            try:
                m = agent_sessions.prepare_stream_launch(
                    base, workdir, cli_binary=binary, cli_version=version,
                    cli_identity=agent_sessions.binary_identity(binary), model_id=acc["executor_model"],
                    pipeline_id=flow_id, task_id=flow["task_id"], allowed_root=str(self.managed_root.resolve()))
            except agent_sessions.LaunchRefused as exc:
                raise ApiError(409, getattr(exc, "code", "refused"), f"無法準備執行者：{exc}") from exc
            except OSError as exc:
                raise ApiError(500, "prepare", f"無法準備執行者（{exc.strerror or type(exc).__name__}）") from exc
            try:
                result = self._call("open_stream", timeout=60.0, launch_id=m["launch_id"])
            except BaseException as exc:
                # Prepared, never opened: take it back, whatever went wrong (Gemini S2c-2 review: not only the
                # errors this module raises itself). A launch the daemon did open is not "prepared" any more
                # and discard_prepared leaves it alone.
                agent_sessions.discard_prepared(base, m["launch_id"])
                if isinstance(exc, ApiError):
                    raise
                if isinstance(exc, Exception):
                    raise ApiError(500, "internal", f"啟動執行者時發生未預期的錯誤（{type(exc).__name__}）") from exc
                raise
            return {"launch_id": m["launch_id"], "session": result}

    def close(self, flow_id: str, body) -> dict:
        if not isinstance(body, dict) or set(body) != {"launch_id"}:
            raise ApiError(400, "bad_request", "只接受 launch_id")
        with self._lock(flow_id):
            self._flow(flow_id)
            m = self._own_launch(flow_id, body["launch_id"])
            return self._call("stream_close", timeout=30.0, launch_id=m["launch_id"])

    # ---- stop and continue -------------------------------------------------------------------------------

    def hold(self, flow_id: str, body) -> dict:
        reason = "使用者在主控台按了停止"
        if body not in (None, {}):
            if not isinstance(body, dict) or set(body) - {"reason"} or not isinstance(body.get("reason", ""), str):
                raise ApiError(400, "bad_request", "只接受 reason（字串）")
            reason = (body.get("reason") or reason)[:200]
        self._flow(flow_id)
        result = self._call("pipeline_hold", pipeline=flow_id, reason=reason)
        # a stop of an automatic flow is a record of its own (S3 design 6): the console writes it after the daemon did
        if pipeline_store.mode_info(cfg.state_dir(), flow_id)["mode"] == "auto":
            try:
                flows.append_automation_event(flow_id, "auto_stopped", {"reason_code": "user_stop", "detail": reason})
            except Exception as exc:
                # the daemon's stop has taken effect; what could not be written is said, not swallowed
                result = {**result, "event_written": False,
                          "event_problem": f"流程已停止，但「停止」事件無法寫入時間軸（{exc}）"}
        return result

    def release(self, flow_id: str, body) -> dict:
        """The user's "continue" (design 7, v29.8). The daemon refuses while a
        failed session is still open and says so."""
        if body not in (None, {}):
            raise ApiError(400, "bad_request", "不接受任何欄位")
        flow = self._flow(flow_id)
        if pipeline_store.mode_info(cfg.state_dir(), flow_id)["mode"] == "auto":
            problems = self._continue_problems(flow)
            if problems:
                raise ApiError(409, "cannot_continue", "不能繼續：" + "；".join(problems), reasons=problems)
        return self._call("pipeline_release", pipeline=flow_id)

    @staticmethod
    def _flow_reviews(flow: dict) -> list[dict]:
        return stream_flow.flow_reviews(cfg.state_dir(), flow["id"], flow["task_id"])

    def _continue_problems(self, flow: dict) -> list[str]:
        """S3 design 6: what has to hold before an automatic flow is let go
        again. (The daemon refuses a release while a failed session is open;
        that, and a usable quota ledger, are its to say.)"""
        why: list[str] = []
        base = cfg.state_dir()
        acc = risk_acceptance.status(flow)
        if acc["state"] != "valid":
            why.append(f"風險接受目前不算數（{acc.get('reason') or acc['state']}）")
        try:
            workdir = self._workdir(flow)
            if git_head.read_head(workdir).get("commit") is None:
                why.append("讀不到執行者工作目錄的 HEAD")
        except ApiError as exc:
            why.append(str(exc))
        try:
            reviews = self._flow_reviews(flow)
            if any(m["state"] == "manual_review" or m["outcome"] == "manual_review" for m in reviews):
                why.append("有審查在 manual_review，要先由人處理")
            if any(m["state"] in ("prepared", "launching", "running", "finished", "invalid") for m in reviews):
                why.append("還有審查沒有結束（剛被停止中止的審查要等它收尾；結束後會是無效審查，到時再按繼續）")
        except stream_flow.FlowRefused as exc:
            why.append(f"審查紀錄無法核對（{exc}）")
        try:
            ctx = stream_flow.load(base, flow["id"])
            stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False, ignore_unresolved=True)
        except stream_flow.FlowRefused as exc:
            why.append(f"上限或接受：{exc}")
        return why

    # ---- dispatch ----------------------------------------------------------------------------------------

    def _session_readiness(self, flow_id: str, launch_id: str) -> tuple[bool, str]:
        """(ready, why not) from the daemon: the session is live and idle."""
        try:
            st = daemon_client.call(self.runtime, "stream_status", launch_id=launch_id)
        except DaemonError as exc:
            return False, str(exc)
        if not st.get("live"):
            return False, "這個 session 已經不在執行"
        if st.get("journal_problem") or st.get("journal_write_failed"):
            return False, "這個 session 的日誌有問題"
        if st.get("state") != "idle":
            return False, f"session 現在是「{st.get('state')}」，要等它回到 idle 才能派工"
        return True, ""

    def dispatch_preview(self, flow_id: str, body) -> dict:
        if not isinstance(body, dict) or set(body) != DISPATCH_KEYS:
            raise ApiError(400, "bad_request", "只接受 launch_id 與 text")
        flow = self._flow(flow_id)
        risk_acceptance.refuse_if_automatic(flow_id, "手動派工")
        self._valid_acceptance(flow)
        m = self._own_launch(flow_id, body["launch_id"])
        try:
            text = sp.sanitize(body["text"])                  # a lone surrogate is refused, never replaced
        except ValueError as exc:
            raise ApiError(400, "bad_text", str(exc)) from exc
        if not text.strip():
            raise ApiError(400, "bad_text", "派工內容不能是空的")
        dispatch_id = str(uuid.uuid4())
        try:                                                  # the line the daemon will build: never truncated
            sp.dispatch_line(text, str(uuid.uuid4()), dispatch_id)
        except ValueError as exc:
            raise ApiError(400, "too_long", str(exc)) from exc
        ready, why = self._session_readiness(flow_id, m["launch_id"])
        try:
            rec = self.store.create("dispatch", flow_id, {
                "launch_id": m["launch_id"], "dispatch_id": dispatch_id, "text": text,
                "text_sha256": sp.sha256_hex(text.encode("utf-8"))})
        except previews.PreviewError as exc:
            raise ApiError(exc.status, exc.code, str(exc)) from exc
        original = body["text"]
        return {"preview_id": rec["preview_id"], "expires_at": rec["expires"], "ttl_s": previews.TTL,
                "dispatch_id": dispatch_id, "launch_id": m["launch_id"], "text": text,
                "text_sha256": rec["data"]["text_sha256"], "bytes": len(text.encode("utf-8")),
                "rewritten": text != original, "ready": ready, "not_ready_reason": why}

    def dispatch_confirm(self, flow_id: str, body) -> dict:
        if not isinstance(body, dict) or set(body) != {"preview_id"}:
            raise ApiError(400, "bad_request", "只接受 preview_id；派工內容一律取自預覽紀錄")
        with self._lock(flow_id):
            flow = self._flow(flow_id)
            risk_acceptance.refuse_if_automatic(flow_id, "手動派工")

            def check(rec: dict) -> None:
                data = rec["data"]
                try:
                    self._valid_acceptance(flow)
                    self._own_launch(flow_id, data["launch_id"])
                except ApiError as exc:
                    raise previews.PreviewError("conflict", f"預覽之後的情況已改變（{exc}），請重新預覽") from exc
                hold = pipeline_store.hold_info(cfg.state_dir(), flow_id)
                if hold["held"]:
                    raise previews.PreviewError("conflict", f"這個流程已停止（{hold['reason']}），請重新預覽")
                ready, why = self._session_readiness(flow_id, data["launch_id"])
                if not ready:
                    raise previews.PreviewError("conflict", f"現在不能派工：{why}")
            try:
                rec = self.store.consume(body["preview_id"], kind="dispatch", flow_id=flow_id, check=check)
            except previews.PreviewError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            d = rec["data"]
            fields = {"launch_id": d["launch_id"], "pipeline": flow_id, "dispatch_id": d["dispatch_id"]}
            self._call("dispatch_prepare", timeout=30.0, text=d["text"],
                       approval={"kind": "preview", "id": rec["preview_id"]}, **fields)
        # The critical section ends here: the dispatch is prepared, and the daemon accepts at most one prepared,
        # unsent dispatch per session, so nothing can slip in before this one is sent. Waiting between attempts
        # to reach the daemon must not hold up every other action on the flow (Gemini S2c-2 review).
        result = self._send(fields)
        return {"dispatch_id": d["dispatch_id"], "launch_id": d["launch_id"], "result": result}

    def _send(self, fields: dict) -> dict:
        """stream_send is idempotent, so a lost answer is asked again; a
        refusal is final (the dispatch stays prepared and counted, and the
        screen says so)."""
        last: ApiError | None = None
        for attempt in range(SEND_ATTEMPTS):
            try:
                return daemon_client.call(self.runtime, "stream_send", timeout=30.0, **fields)
            except DaemonError as exc:
                last = _daemon(exc)
                if exc.code != "unavailable":
                    break
                time.sleep(SEND_PAUSE)
        assert last is not None
        raise ApiError(last.status, last.code, f"派工已準備但還沒送出：{last}", dispatch_id=fields["dispatch_id"],
                       prepared=True)

    # ---- the read model ---------------------------------------------------------------------------------------

    def status(self, flow_id: str) -> dict:
        flow = self._flow(flow_id)
        base = cfg.state_dir()
        mode = pipeline_store.mode_info(base, flow_id)
        out: dict = {"flow_id": flow_id, "acceptance": risk_acceptance.status(flow),
                     "automation": {"mode": mode["mode"], "approval_id": mode["approval_id"],
                                    "problem": mode["problem"]},
                     "hold": pipeline_store.hold_info(base, flow_id), "workdir": None, "workdir_problem": None,
                     "accounting": None, "failures": [], "unresolved_failure": None, "sessions": [],
                     "sessions_problem": None}
        try:
            out["workdir"] = self._workdir(flow)
        except ApiError as exc:
            out["workdir_problem"] = str(exc)
        ctx = None
        try:
            with stream_flow.settling(REVIEW_SETTLE_S):
                ctx = stream_flow.load(base, flow_id)
        except stream_flow.FlowRefused as exc:
            out["accounting"] = {"ok": False, "code": exc.code, "message": str(exc)}
        if ctx is not None:
            out["accounting"] = _accounting(ctx)
            out["failures"] = _failures(ctx)
            out["unresolved_failure"] = stream_flow.unresolved_failure(ctx)
        try:
            manifests = stream_flow.flow_sessions(base, flow_id, started=bool(ctx and ctx.started_at is not None))
        except stream_flow.FlowRefused as exc:
            out["sessions_problem"] = str(exc)
            manifests = []
        manifests, order_problem = ordered_sessions(manifests)         # oldest first, by creation time
        out["sessions_order_problem"] = order_problem
        for m in manifests:
            out["sessions"].append(self._session_view(m))
        live = [s for s in out["sessions"] if s["manifest_state"] in ("launching", "running")]
        # one non-ended session per flow is the rule; if the files show more, none is called "current"
        out["current_launch_id"] = live[0]["launch_id"] if len(live) == 1 else None
        # a hint for the screen, never the authority: the daemon decides again at open_stream
        out["can_start"] = bool(out["acceptance"]["state"] == "valid" and not out["hold"]["held"] and not live
                                and out["workdir"] and not out["unresolved_failure"]
                                and out["accounting"] and out["accounting"].get("ok") and not out["sessions_problem"])
        return out

    def _session_view(self, m: dict) -> dict:
        view = {"launch_id": m["launch_id"], "manifest_state": m.get("state"), "created": m.get("created"),
                "model_id": m.get("model_id"), "cli_version": m.get("cli_version"),
                "retained_reason": m.get("retained_reason"), "status": None, "status_problem": None}
        try:
            st = daemon_client.call(self.runtime, "stream_status", launch_id=m["launch_id"])
        except DaemonError as exc:
            view["status_problem"] = str(exc)
            return view
        view["status"] = {k: st.get(k) for k in (
            "live", "state", "journal_problem", "journal_write_failed", "dispatches", "total_cost_usd", "responses",
            "num_turns", "closed_reasons", "exit")}
        view["worst_case"] = _worst_case(st)
        return view


def _accounting(ctx) -> dict:
    t, lim = ctx.totals, ctx.limits
    now = time.time()
    elapsed = (now - ctx.started_at) if ctx.started_at is not None else None
    return {"ok": True, "started_at": ctx.started_at, "elapsed_s": elapsed,
            "dispatches": t.dispatches, "responses": t.responses, "spent_usd": t.spent_usd,
            "reviews": len(t.reviews), "limits": dict(lim),
            "remaining": {"dispatches": lim["max_dispatches"] - t.dispatches,
                          "responses": lim["executor_total_max_responses"] - t.responses,
                          "reviews": lim["max_reviews"] - len(t.reviews),
                          "budget_usd": round(lim["executor_budget_usd"] - t.spent_usd, 2),
                          "hours": None if elapsed is None else round(lim["max_elapsed_h"] - elapsed / 3600, 2)}}


def _failures(ctx) -> list[dict]:
    out = []
    for s in ctx.totals.sessions:
        for f in s["failures"]:
            out.append({"id": f["id"], "kind": "session", "launch_id": s["launch_id"], "why": f["why"],
                        "at": f["at"], "released": f["id"] in ctx.resolved})
    for r in ctx.totals.reviews:
        for f in r["failures"]:
            out.append({"id": f["id"], "kind": "review", "job_id": r["job_id"], "why": f["why"], "at": f["at"],
                        "released": f["id"] in ctx.resolved})
    return out


def _worst_case(st: dict) -> dict | None:
    """Design v29.7, said as it is: a turn that may have reached the CLI and
    has no result is counted at its worst case. None when nothing is."""
    unfinished = st.get("unfinished") or []
    recovered = st.get("recovered")
    if not unfinished and not recovered:
        return None
    return {"unfinished": list(unfinished), "recovered": recovered, "responses": st.get("counted_responses"),
            "usd": st.get("counted_cost_usd"),
            "text": (f"上一輪沒有結果，費用未知，以最壞情況計入（回應數 {st.get('counted_responses')}、"
                     f"USD {st.get('counted_cost_usd')}）。要繼續就需要重新接受風險，必要時調高額度。")}
