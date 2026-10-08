"""A flow as the daemon sees it before it starts or feeds a stream executor.

Everything is read again for every decision; nothing a caller sends is
trusted for it (planner decisions 2026-10-08, S2a-2 Q1/Q3/Q4):

  * the flow and its task, from flows.json, read only (a store that cannot
    be read safely refuses);
  * the newest risk acceptance valid now (acceptance.latest_valid) and the
    limits it carries, re-checked against the hard caps (design 6);
  * whether the flow is stopped (design 7);
  * when its first stream session started (daemon's own record);
  * totals over every stream session of the flow, recomputed from their
    journals and the saved dispatch texts: dispatches, model responses,
    the executor's spend. A journal that cannot be read refuses (design 6:
    a missing or malformed count stops new dispatches).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field

from .. import acceptance, flows, login_identity
from ..jsonstore import StoreError
from . import agent_sessions, pipeline_store, stream_journal

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class FlowRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Totals:
    dispatches: int = 0
    responses: int = 0
    spent_usd: float = 0.0
    sessions: list = field(default_factory=list)


@dataclass
class FlowContext:
    pipeline_id: str
    task_id: str
    acceptance: dict
    limits: dict
    key: login_identity.LoginKey
    started_at: float | None
    totals: Totals


def _journal_state(base, launch_id: str) -> stream_journal.ReadResult:
    path = agent_sessions.launch_dir(base, launch_id)
    try:
        fd = os.open(str(path), _DIR)
    except OSError as exc:
        return stream_journal.ReadResult(stream_journal.JournalState(), f"無法開啟 launch 資料夾（{exc.strerror}）")
    try:
        return stream_journal.read(fd)
    finally:
        os.close(fd)


def flow_sessions(base, pipeline_id: str) -> list[dict]:
    """Every stream launch of the flow that has a journal, as manifests.
    A manifest that cannot be read refuses: it could belong to this flow."""
    root = agent_sessions.sessions_root(base)
    if not root.is_dir():
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if not agent_sessions.LAUNCH_RE.match(name):
            continue
        try:
            m = agent_sessions._read_manifest(agent_sessions.launch_dir(base, name), os.getuid())
        except (OSError, agent_sessions.LaunchRefused) as exc:
            raise FlowRefused("count_unavailable", f"launch {name} 的 manifest 無法讀取，無法核算流程用量") from exc
        if m.get("engine") == "claude-stream" and m.get("pipeline_id") == pipeline_id \
                and (root / name / agent_sessions.JOURNAL).exists():
            out.append(m)
    return out


def totals(base, pipeline_id: str, task_id: str) -> Totals:
    t = Totals()
    for m in flow_sessions(base, pipeline_id):
        res = _journal_state(base, m["launch_id"])
        if res.problem:
            raise FlowRefused("count_unavailable", f"session {m['launch_id']} 的日誌無法使用（{res.problem}）")
        js = res.state
        t.responses += js.responses
        t.spent_usd += js.cost            # total_cost_usd is per process: the session's last value
        t.sessions.append({"launch_id": m["launch_id"], "state": js.state, "dispatches": js.dispatch_count()})
    try:
        with pipeline_store.Pipeline(base, task_id, create=False) as p:
            t.dispatches = len(p.text_names())
    except pipeline_store.StoreRefused as exc:
        if "不存在" not in str(exc):
            raise FlowRefused("count_unavailable", f"派工紀錄無法讀取（{exc}）") from exc
    return t


def load(base, pipeline_id: str) -> FlowContext:
    try:
        all_flows = flows.read_only_snapshot(base)
    except StoreError as exc:
        raise FlowRefused("flow_unavailable", f"流程紀錄無法讀取（{exc}）") from exc
    flow = all_flows.get(pipeline_id) if isinstance(pipeline_id, str) else None
    if flow is None:
        raise FlowRefused("no_flow", "找不到這個流程")
    try:
        key = login_identity.load_login_key(base)
    except login_identity.KeyUnavailable as exc:
        raise FlowRefused("no_acceptance", f"沒有有效的風險接受（{exc}），請在流程中重新接受") from exc
    acc = acceptance.latest_valid(flow, key.key_id)
    if acc is None:
        raise FlowRefused("no_acceptance", "這個流程沒有有效的風險接受，請先接受殘餘風險")
    limits = acc["limits"]
    problem = acceptance.limits_problem(limits)
    if problem:
        raise FlowRefused("no_acceptance", f"接受的上限不合規（{problem}）")
    task_id = flow["task_id"]
    try:
        with pipeline_store.Pipeline(base, task_id, create=False) as p:
            started = p.started_at(pipeline_id)
    except pipeline_store.StoreRefused as exc:
        if "不存在" not in str(exc):
            raise FlowRefused("count_unavailable", str(exc)) from exc
        started = None
    return FlowContext(pipeline_id, task_id, acc, dict(limits), key, started, totals(base, pipeline_id, task_id))


def check_limits(ctx: FlowContext, *, now: float, counting_dispatch: bool, live_responses: int = 0) -> None:
    """Design 6, for dispatch_prepare (counting_dispatch) and stream_send."""
    lim, tot = ctx.limits, ctx.totals
    if ctx.started_at is not None and now - ctx.started_at > lim["max_elapsed_h"] * 3600:
        raise FlowRefused("limit", f"已達經過時間上限（{lim['max_elapsed_h']} 小時）")
    if counting_dispatch and tot.dispatches >= lim["max_dispatches"]:
        raise FlowRefused("limit", f"已達派工則數上限（{lim['max_dispatches']}）")
    if tot.responses + live_responses >= lim["executor_total_max_responses"]:
        raise FlowRefused("limit", f"已達流程的模型回應數上限（{lim['executor_total_max_responses']}）")
    if tot.spent_usd >= lim["executor_budget_usd"]:
        raise FlowRefused("limit", "已用完執行者額度")


def remaining_budget(ctx: FlowContext) -> float:
    """What --max-budget-usd gets: the budget left, rounded down to cents."""
    left = math.floor((ctx.limits["executor_budget_usd"] - ctx.totals.spent_usd) * 100) / 100
    if not math.isfinite(left) or left <= 0:
        raise FlowRefused("limit", "已用完執行者額度")
    return left


def check_executor(ctx: FlowContext, *, cli_version: str, model_id: str, claude_json: str) -> None:
    """Design 10 / planner Q4: the acceptance must cover this executor, and
    the Claude login now must be the one accepted."""
    acc = ctx.acceptance
    if acc["executor_claude_version"] != cli_version or acc["executor_model"] != model_id:
        raise FlowRefused("reaccept", "接受時的 Claude Code 版本或模型與這次不同，請重新接受")
    fp = login_identity.claude_login_fingerprint(claude_json, ctx.key)
    if not fp.ok:
        raise FlowRefused("no_login", f"無法取得執行者的帳號指紋（{fp.problem}）")
    if fp.hmac != acc["executor_login_fingerprint"]:
        raise FlowRefused("reaccept", "執行者的 Claude 帳號與接受時不同，請重新接受")


def now() -> float:
    return time.time()
