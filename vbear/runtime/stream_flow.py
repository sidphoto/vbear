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

import json
import math
import os
import stat
import time
from pathlib import Path
from dataclasses import dataclass, field

from .. import acceptance, flows, login_identity
from ..jsonstore import StoreError
from . import agent_sessions, pipeline_store, stream_journal
from . import stream_protocol as sp

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class FlowRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Totals:
    responses: int = 0
    spent_usd: float = 0.0
    sessions: list = field(default_factory=list)
    accepted: set = field(default_factory=set)                  # dispatch ids some session of the flow accepted
    pending_or_orphan_texts: list = field(default_factory=list)  # saved texts no journal accepted (sorted ids)

    @property
    def dispatches(self) -> int:
        """What counts against max_dispatches: accepted dispatches plus saved
        texts without an acceptance. Design 3.5 treats the latter as orphans
        (disk use, listed for a person), not dispatches; but one may be a
        prepare whose acceptance is still to be written (the same id sent
        again completes it), so counting it is deliberately more conservative
        than the design (planner ruling, Codex S2a-2 p1 R5 #2)."""
        return len(self.accepted) + len(self.pending_or_orphan_texts)


@dataclass
class FlowContext:
    pipeline_id: str
    task_id: str
    acceptance: dict
    limits: dict
    key: login_identity.LoginKey
    started_at: float | None
    totals: Totals
    resolved: frozenset = frozenset()     # v29.8 / round 6: failure identities the user has released


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


def _journal_present(root, name: str) -> bool:
    # lstat, not Path.exists(): on Python 3.14 that returns False on any
    # OSError (EACCES included), which would read as "no journal".
    try:
        os.lstat(root / name / agent_sessions.JOURNAL)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FlowRefused("count_unavailable",
                          f"launch {name} 的日誌無法檢查（{exc.strerror}），無法核算流程用量") from exc
    return True


def flow_sessions(base, pipeline_id: str, *, started: bool) -> list[dict]:
    """Every stream launch of the flow that has a journal, as manifests.
    Anything that could hide usage refuses (Codex S2a-2 p1 R2 #1, R5 #1):
    a sessions root that is not a plain directory or cannot be listed; an
    entry that is not a launch directory (VBear puts nothing else there); a
    launch directory that is not the one its manifest names (renamed or
    copied); a manifest that cannot be read or has an unknown engine; a
    terminal (claude/codex) manifest that is not exactly that schema, names
    a flow, or sits next to a stream journal; a flow that has started but
    whose sessions are gone. Only a stream launch of another flow is skipped,
    and only a flow that never started may have none."""
    root = agent_sessions.sessions_root(base)
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        if started:
            raise FlowRefused("count_unavailable", "流程已啟動過，但找不到 session 資料夾，無法核算用量")
        return []
    except OSError as exc:
        raise FlowRefused("count_unavailable", f"session 資料夾無法檢查（{exc.strerror}）") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise FlowRefused("count_unavailable", "session 資料夾不是一般資料夾，無法核算用量")
    try:
        names = sorted(os.listdir(root))
    except OSError as exc:
        raise FlowRefused("count_unavailable", f"session 資料夾無法列出（{exc.strerror}）") from exc
    uid = os.getuid()
    out = []
    for name in names:
        if not agent_sessions.LAUNCH_RE.match(name):
            raise FlowRefused("count_unavailable", f"session 資料夾裡有不認得的項目 {name[:64]!r}，無法核算流程用量")
        try:
            lst = os.lstat(root / name)
            m = agent_sessions._read_manifest(agent_sessions.launch_dir(base, name), uid)
        except (OSError, agent_sessions.LaunchRefused) as exc:
            raise FlowRefused("count_unavailable", f"launch {name} 的 manifest 無法讀取，無法核算流程用量") from exc
        if (not stat.S_ISDIR(lst.st_mode) or m.get("launch_id") != name
                or m.get("launch_dir") != {"path": str(root / name), "inode": lst.st_ino, "uid": uid}):
            raise FlowRefused("count_unavailable", f"launch {name} 的資料夾與 manifest 不符（改名或複製過），無法核算流程用量")
        engine = m.get("engine")
        if engine == "claude-stream":     # _read_manifest checked the stream schema
            if m.get("pipeline_id") != pipeline_id:
                continue                  # another flow's session: a filter, not an error
            if _journal_present(root, name):
                out.append(m)
            elif not (m.get("state") == "prepared" and m.get("native_session_id") is None and m.get("leader") is None):
                # Only a launch that never had a process may lack a journal (the
                # journal is created before the process starts). Any other one
                # would make the flow's totals silently low (Codex S2a-2 p1 #3).
                raise FlowRefused("count_unavailable",
                                  f"launch {name} 的日誌不見了（狀態 {str(m.get('state'))[:32]}），無法核算流程用量")
        elif engine in ("claude", "codex"):
            problem = agent_sessions.managed_manifest_problem(m)
            if problem or "pipeline_id" in m or _journal_present(root, name):
                raise FlowRefused("count_unavailable",
                                  f"launch {name} 標示為 {engine}，但不是完整的終端 session 紀錄"
                                  f"（{problem or '帶有流程欄位或串流日誌'}），無法核算流程用量")
        else:
            raise FlowRefused("count_unavailable", f"launch {name} 的引擎不認得，無法核算流程用量")
    if started and not out:
        raise FlowRefused("count_unavailable", "流程已啟動過，但找不到它的任何 session 日誌，無法核算用量")
    return out


def _pipeline_view(base, pipeline_id: str, task_id: str):
    """(started_at, {dispatch id: text bytes}) from the flow's directory, or
    None when that directory does not exist at all. Any other problem
    refuses; nothing is read as zero or empty on an error."""
    try:
        with pipeline_store.Pipeline(base, task_id, create=False) as p:
            started = p.started_at(pipeline_id)
            texts = {d: p.read_text(d) for d in p.text_names()}
            released = p.release_record(pipeline_id)
    except pipeline_store.StoreRefused as exc:
        if exc.missing:
            return None
        raise FlowRefused("count_unavailable", f"流程資料無法讀取（{exc}）") from exc
    except OSError as exc:
        raise FlowRefused("count_unavailable", f"流程資料無法讀取（{exc.strerror}）") from exc
    return started, texts, released


def totals(base, pipeline_id: str, task_id: str, view) -> Totals:
    """Usage over every stream session of the flow, cross-checked against
    the saved dispatch texts (design 3.5: a text is saved before its
    dispatch is accepted, so every accepted dispatch has its text with the
    recorded hash and length; a text without an accepted record is an orphan
    from a crash and is counted too). Anything inconsistent refuses."""
    started, texts, _ = view if view is not None else (None, {}, None)
    sessions = flow_sessions(base, pipeline_id, started=started is not None)
    if sessions and view is None:
        raise FlowRefused("count_unavailable", "流程有 session 紀錄，但流程資料夾不見了，無法核算用量")
    if sessions and started is None:
        raise FlowRefused("count_unavailable", "流程有 session 紀錄，但沒有開始時間紀錄，無法核算經過時間")
    t = Totals()
    for m in sessions:
        res = _journal_state(base, m["launch_id"])
        if res.problem:
            raise FlowRefused("count_unavailable", f"session {m['launch_id']} 的日誌無法使用（{res.problem}）")
        js = res.state
        # v29.7: a dispatch that may have reached the CLI without a result
        # counts at its worst case (its turn cap; the session's budget).
        t.responses += js.counted_responses
        t.spent_usd += js.counted_cost    # total_cost_usd is per process: the session's last value
        t.sessions.append({"launch_id": m["launch_id"], "state": js.state, "manifest_state": m.get("state"),
                           "dispatches": js.dispatch_count(),
                           "unfinished": js.unfinished(), **_failure(m, js)})
        for d in js.order:
            if d in t.accepted:
                raise FlowRefused("count_unavailable", f"派工 {d} 被兩個 session 接受過")
            t.accepted.add(d)
            turn = js.turns[d]
            data = texts.get(d)
            if data is None:
                raise FlowRefused("count_unavailable", f"派工 {d} 已被接受，但它的全文不見了")
            if len(data) != turn.length or sp.sha256_hex(data) != turn.text_sha256:
                raise FlowRefused("count_unavailable", f"派工 {d} 的全文與接受時的紀錄不同")
    if not math.isfinite(t.spent_usd):
        raise FlowRefused("count_unavailable", "執行者花費的累計值不是有限數")
    t.pending_or_orphan_texts = sorted(set(texts) - t.accepted)
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
    view = _pipeline_view(base, pipeline_id, task_id)
    started = view[0] if view is not None else None
    return FlowContext(pipeline_id, task_id, acc, dict(limits), key, started,
                       totals(base, pipeline_id, task_id, view),
                       frozenset(view[2]["resolved"]) if view is not None and view[2] is not None else frozenset())


def _failure(m: dict, js: stream_journal.JournalState) -> dict:
    """A session's failures (design v29.8) with their identities (review
    round 6): "<launch>#<seq>" for each failure fact in its journal, and
    "<launch>#manual_review#<retained_at as stored>" when it was kept for a
    person. Whether a failure is resolved is decided by identity only; the
    time is for display."""
    lid = m["launch_id"]
    ids = [(f"{lid}#{seq}", why, t) for why, t, seq in js.failures]
    if m.get("state") == "manual_review":
        raw = json.dumps(m.get("retained_at"))
        ids.append((f"{lid}#manual_review#{raw}", f"交人工處理：{str(m.get('retained_reason'))[:200]}",
                    m.get("retained_at")))
    return {"failure_ids": [i for i, _, _ in ids], "failures": [{"id": i, "why": w, "at": t} for i, w, t in ids]}


def unresolved_failure(ctx: FlowContext) -> str | None:
    """v29.8: any failure of the flow the user has not released yet, by
    identity. Recomputed from the journals and manifests, so neither a lost
    hold file nor the clock lets the flow go on."""
    for x in ctx.totals.sessions:
        for f in x["failures"]:
            if f["id"] not in ctx.resolved:
                return f"session {x['launch_id']}：{f['why']}"
    return None


def failure_ids(base, pipeline_id: str) -> list[str]:
    """Every failure identity of the flow on disk now, for pipeline_release.
    Anything unreadable refuses (a release never assumes)."""
    out = []
    for m in flow_sessions(base, pipeline_id, started=False):
        res = _journal_state(base, m["launch_id"])
        if res.problem:
            raise FlowRefused("count_unavailable", f"session {m['launch_id']} 的日誌無法使用（{res.problem}）")
        out += _failure(m, res.state)["failure_ids"]
    return out


def _never_ran(base, rec: dict) -> str | None:
    """None when the start record's launch provably never had a process
    (design v29.7): it does not exist, or it is still "prepared" with no
    session id, leader or journal (Popen always follows the journal); and
    no stream launch of the flow has a journal. Else why it is kept."""
    root = agent_sessions.sessions_root(base)
    name = rec["launch_id"]
    try:
        names = sorted(os.listdir(root))
    except FileNotFoundError:
        names = []
    except OSError as exc:
        return f"session 資料夾無法列出（{exc.strerror}）"
    uid = os.getuid()
    for other in names:
        if not agent_sessions.LAUNCH_RE.match(other):
            return f"session 資料夾裡有不認得的項目 {other[:64]!r}"
        try:
            m = agent_sessions._read_manifest(agent_sessions.launch_dir(base, other), uid)
            journal = agent_sessions._lexists(root / other / agent_sessions.JOURNAL)
        except (OSError, agent_sessions.LaunchRefused) as exc:
            return f"launch {other} 無法檢查（{exc}）"
        if other == name:
            if (m.get("engine") != "claude-stream" or m.get("pipeline_id") != rec["pipeline_id"]
                    or m.get("state") != "prepared" or m.get("native_session_id") is not None
                    or m.get("leader") is not None or journal):
                return f"開始紀錄指向的 launch {name} 不是從未啟動的狀態"
        elif m.get("engine") == "claude-stream" and m.get("pipeline_id") == rec["pipeline_id"] and journal:
            return f"流程的 launch {other} 有日誌"
    return None


def recover_start_records(base) -> list[dict]:
    """Daemon start (design v29.7): a start record left by an open that
    crashed before its journal existed would keep the flow refused forever
    ("started, but no session"). It is removed exactly (flow, time and
    launch) when that launch provably never ran; anything else is kept for
    a person."""
    root = Path(os.path.realpath(base)) / pipeline_store.PIPELINES
    try:
        tasks = sorted(os.listdir(root))
    except FileNotFoundError:
        return []
    except OSError as exc:
        return [{"task": None, "kept": f"流程資料夾無法列出（{exc.strerror}）"}]
    out = []
    for task in tasks:
        try:
            with pipeline_store.Pipeline(base, task, create=False) as p:
                rec = p.start_record()
                if rec is None:
                    continue
                why = _never_ran(base, rec)
                if why is None:
                    p.remove_start(rec["pipeline_id"], rec["started_at"], launch_id=rec["launch_id"])
                    out.append({"task": task, "pipeline_id": rec["pipeline_id"], "removed": rec["launch_id"]})
                elif not _flow_has_journal(base, rec["pipeline_id"]):
                    out.append({"task": task, "pipeline_id": rec["pipeline_id"], "kept": why})
        except (OSError, pipeline_store.StoreRefused) as exc:
            out.append({"task": task, "kept": str(exc)})
    return out


def _flow_has_journal(base, pipeline_id: str) -> bool:
    """For the log only: a started flow with a session journal is normal."""
    try:
        return bool(flow_sessions(base, pipeline_id, started=False))
    except FlowRefused:
        return False


def check_limits(ctx: FlowContext, *, now: float, counting_dispatch: bool, live_responses: int = 0) -> None:
    """Design 6, for dispatch_prepare (counting_dispatch) and stream_send."""
    lim, tot = ctx.limits, ctx.totals
    failed = unresolved_failure(ctx)                     # v29.8: one failure stops the flow
    if failed:
        raise FlowRefused("failed", f"流程有尚未「繼續」的失敗（{failed}），需要使用者先按「繼續」")
    if not (isinstance(tot.spent_usd, (int, float)) and math.isfinite(tot.spent_usd)):
        raise FlowRefused("count_unavailable", "執行者花費的累計值不是有限數")   # NaN passes every comparison
    if ctx.started_at is not None:
        if (not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now)
                or not isinstance(ctx.started_at, (int, float)) or isinstance(ctx.started_at, bool)
                or not math.isfinite(ctx.started_at)):
            raise FlowRefused("count_unavailable", "流程經過時間無法核對")
        elapsed = now - ctx.started_at
        if not math.isfinite(elapsed) or elapsed < 0:
            raise FlowRefused("count_unavailable", "系統時鐘異常，流程經過時間無法核對")
        if elapsed >= lim["max_elapsed_h"] * 3600:
            raise FlowRefused("limit", f"已達經過時間上限（{lim['max_elapsed_h']} 小時）")
    if counting_dispatch and tot.dispatches >= lim["max_dispatches"]:
        raise FlowRefused("limit", f"已達派工則數上限（{lim['max_dispatches']}）")
    if tot.responses + live_responses >= lim["executor_total_max_responses"]:
        raise FlowRefused("limit", f"已達流程的模型回應數上限（{lim['executor_total_max_responses']}）")
    if tot.spent_usd >= lim["executor_budget_usd"]:
        raise FlowRefused("limit", "已用完執行者額度")


def remaining_budget(ctx: FlowContext) -> float:
    """What --max-budget-usd gets: the budget left, rounded down to cents.
    A spend or budget that is not a finite number refuses (never an
    OverflowError from rounding infinity)."""
    spent, budget = ctx.totals.spent_usd, ctx.limits["executor_budget_usd"]
    if not (isinstance(spent, (int, float)) and math.isfinite(spent)
            and isinstance(budget, (int, float)) and math.isfinite(budget)):
        raise FlowRefused("count_unavailable", "執行者額度或花費不是有限數")
    left = budget - spent
    if not math.isfinite(left) or left <= 0:
        raise FlowRefused("limit", "已用完執行者額度")
    left = math.floor(left * 100) / 100
    if left <= 0:
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
