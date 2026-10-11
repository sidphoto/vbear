"""Flows: one piece of work carried by several agents, shown as a board.

Stage 1 of VBear's multi-agent support is look-only. A flow belongs to one
task card and holds:

  roles   who plans, who executes, who reviews, each with a model family
  events  an append-only log (plan submitted/approved, implementation
          started, executor report, review result, merge/push done, notes)

Everything shown about a flow is derived from those events and from live
data on every read; nothing derived is stored, and the client can set none
of it. In particular:

  * a review counts as a pass only when the reviewer's and the executor's
    model families are both known and different (recorded on the event, so
    editing roles later cannot turn an old review into a pass);
  * a pass binds to the commit it reviewed, and it is current only while the
    executor's working directory is on exactly that commit, read from the
    repository's files by git_head (VBear runs no git);
  * every event recorded in this stage comes from a form, and says so:
    「手動記錄（未驗證）」.

Nothing here starts, sends or runs anything. The store follows tasks.json's
rules through jsonstore: 0600 atomic writes, a cross-process lock, and a
blocked state instead of silent recovery when the file is not what this
module writes.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from typing import Any, Callable

from pathlib import Path

from . import acceptance, git_head, strictjson
from .activity import CLOCK_SKEW_S, MAX_EPOCH_S
from .jsonstore import GuardedJsonStore, StoreError
from .numbers import finite_real
from .tasks import VALID_ID_RE as TASK_ID_RE

# \Z, not $: $ also matches before a trailing newline ("<sha>\n" would pass).
FLOW_ID_RE = re.compile(r"^flow-[0-9a-f]{12}\Z")
SESSION_RE = re.compile(r"^n-[0-9a-f]{12}\Z")
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
FAMILIES = ("anthropic", "openai", "google", "minimax", "other", "unknown")
FAMILY_LABELS = {"anthropic": "Anthropic（Claude）", "openai": "OpenAI（Codex）", "google": "Google（Gemini）",
                 "minimax": "MiniMax", "other": "其他", "unknown": "不明"}
VERDICTS = ("PASS", "NEEDS_WORK", "BLOCKED")
# "manual": typed into a form (unverified). "console": written by the console
# itself from a server-held preview; only risk_acknowledged (design 10, S2c).
SOURCES = ("manual", "console")
EVENT_KINDS = ("plan_submitted", "plan_approved", "implementation_started", "executor_report",
               "review_result", "merge_done", "push_done", "note", "roles_changed", "risk_acknowledged")
CLIENT_KINDS = tuple(k for k in EVENT_KINDS if k not in ("roles_changed", "risk_acknowledged"))
KIND_LABELS = {"plan_submitted": "提出計畫", "plan_approved": "計畫核准", "implementation_started": "開始實作",
               "executor_report": "執行者回報", "review_result": "審查結果", "merge_done": "已合併",
               "push_done": "已 push", "note": "備註", "roles_changed": "角色變更",
               "risk_acknowledged": "接受殘餘風險"}
# Fields a client may send per kind (besides kind and note).
KIND_FIELDS = {"executor_report": frozenset({"commit"}),
               "review_result": frozenset({"reviewer", "verdict", "commit"})}
PHASES = {
    "planning": "計畫中", "awaiting_approval": "等核准", "implementing": "實作中",
    "in_review": "審查中", "needs_fix": "等修正", "awaiting_merge": "審查通過・等合併",
    "review_stale": "審查結果已過期", "review_unverified": "審查通過・無法核對 HEAD",
    "awaiting_push": "等 push", "done": "完成",
}
ATTENTION_PHASES = frozenset({"awaiting_approval", "awaiting_merge", "awaiting_push", "review_unverified"})
MANUAL_LABEL = "手動記錄（未驗證）"
CONSOLE_LABEL = "主控台依預覽記錄"

MAX_FLOWS = 200
MAX_EVENTS = 500
MAX_REVIEWERS = 4
MAX_NAME = 80
MAX_NOTE = 2000
MAX_PATH = 1024
# How old the console's cached live view may be before session states in it
# stop being shown as current. The flows pages load /api/live (cached for at
# most index.LIVE_TTL_S = 3 s) right before reading flows, and the home page
# refreshes every 5 s, so a healthy view is a few seconds old even after a
# slow build. One older than this means the last refresh failed or nothing
# refreshed for that long, while an Agent's working/waiting state changes in
# seconds.
LIVE_STALE_S = 30.0

_BASE_EVENT_KEYS = frozenset({"seq", "at", "kind", "source", "note"})
_STORED_KIND_KEYS = {
    "executor_report": frozenset({"commit"}),
    "review_result": frozenset({"reviewer", "verdict", "commit", "executor_family"}),
    "roles_changed": frozenset({"roles"}),
    "risk_acknowledged": acceptance.FIELDS,
}


def _epoch(value) -> float | None:
    t = finite_real(value)
    return t if t is not None and 0 < t < MAX_EPOCH_S else None


def _is_int(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _short_text(value, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and "\x00" not in value


# --- stored shape (anything else blocks the store) ---------------------------

def _role_problem(role, *, executor: bool) -> str | None:
    if not isinstance(role, dict):
        return "角色不是物件"
    allowed = {"name", "family", "model"} | ({"session_id", "workdir"} if executor else set())
    if set(role) - allowed:
        return "角色含未知欄位"
    if not (_short_text(role.get("name"), MAX_NAME) and role["name"].strip()):
        return "角色名稱不合法"
    if role.get("family") not in FAMILIES:
        return "模型家族不合法"
    # Optional keys are absent when unset; this module never stores null or "".
    if "model" in role and not (_short_text(role["model"], MAX_NAME) and role["model"]):
        return "模型名稱不合法"
    if executor:
        if "session_id" in role and not (isinstance(role["session_id"], str) and SESSION_RE.match(role["session_id"])):
            return "session id 不合法"
        if "workdir" in role and not (_short_text(role["workdir"], MAX_PATH) and os.path.isabs(role["workdir"])):
            return "工作目錄不合法"
    return None


def _roles_problem(roles) -> str | None:
    if not isinstance(roles, dict) or set(roles) != {"planner", "executor", "reviewers"}:
        return "roles 必須剛好有 planner、executor、reviewers"
    for key in ("planner", "executor"):
        problem = _role_problem(roles[key], executor=key == "executor")
        if problem:
            return f"{key}：{problem}"
    reviewers = roles["reviewers"]
    if not isinstance(reviewers, list) or not 1 <= len(reviewers) <= MAX_REVIEWERS:
        return f"reviewers 必須是 1–{MAX_REVIEWERS} 位"
    for i, r in enumerate(reviewers):
        problem = _role_problem(r, executor=False)
        if problem:
            return f"reviewers[{i}]：{problem}"
    return None


def _event_problem(event, index: int, prev_at: float | None) -> str | None:
    if not isinstance(event, dict):
        return "事件不是物件"
    kind = event.get("kind")
    if kind not in EVENT_KINDS:
        return "事件種類不合法"
    if set(event) != _BASE_EVENT_KEYS | _STORED_KIND_KEYS.get(kind, frozenset()):
        return "事件欄位不符"
    if not _is_int(event.get("seq"), index + 1, index + 1):
        return "事件序號不連續"
    at = _epoch(event.get("at"))
    if at is None:
        return "事件時間不合法"
    if prev_at is not None and at < prev_at:
        return "事件時間倒退"
    if event.get("source") not in SOURCES:
        return "事件來源不合法"
    if (event["source"] == "console") != (kind == "risk_acknowledged"):
        return "事件來源與種類不符"
    if not _short_text(event.get("note"), MAX_NOTE):
        return "備註不合法"
    if kind in ("executor_report", "review_result"):
        if not (isinstance(event.get("commit"), str) and COMMIT_RE.match(event["commit"])):
            return "commit 不合法"
    if kind == "review_result":
        if event.get("verdict") not in VERDICTS:
            return "審查結論不合法"
        if event.get("executor_family") not in FAMILIES:
            return "執行者模型家族不合法"
        rev = event.get("reviewer")
        if not (isinstance(rev, dict) and set(rev) == {"index", "name", "family"}
                and _is_int(rev.get("index"), 0, MAX_REVIEWERS - 1)
                and _short_text(rev.get("name"), MAX_NAME) and rev.get("family") in FAMILIES):
            return "審查者紀錄不合法"
    if kind == "roles_changed" and _roles_problem(event.get("roles")):
        return "角色紀錄不合法"
    if kind == "risk_acknowledged":
        problem = acceptance.record_problem(acceptance.acceptance_fields(event))
        if problem:
            return f"風險接受紀錄不合法（{problem}）"
    return None


def _entry_problem(key, value) -> str | None:
    if not (isinstance(key, str) and FLOW_ID_RE.match(key)):
        return "鍵值不是有效的流程識別碼"
    if not isinstance(value, dict):
        return "值不是物件"
    if set(value) != {"id", "task_id", "created_at", "roles", "events"}:
        return "流程欄位不符"
    if value.get("id") != key:
        return "id 欄位與鍵值不一致"
    if not (isinstance(value.get("task_id"), str) and TASK_ID_RE.match(value["task_id"])):
        return "task_id 不合法"
    if _epoch(value.get("created_at")) is None:
        return "created_at 不合法"
    problem = _roles_problem(value.get("roles"))
    if problem:
        return problem
    events = value.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        return "events 不是清單或超過上限"
    prev = None
    for i, event in enumerate(events):
        problem = _event_problem(event, i, prev)
        if problem:
            return f"events[{i}]：{problem}"
        prev = _epoch(event["at"])
    return None


store = GuardedJsonStore("flows.json", "流程儲存", _entry_problem)

# flows.json for readers that must not write: the runtime daemon (planner
# decision S2a-2 Q3). 200 flows x 500 events is far below these limits.
FLOWS_LIMITS = strictjson.Limits(32 << 20, 4_000_000, 16, 32 << 20)


def read_only_snapshot(state_dir=None) -> dict:
    """All flows, read strictly and never repaired: the corruption marker,
    an unsafe file, a strict-JSON failure, a limit or any entry this module
    could not have written raises StoreError. Unlike ``store.load`` it
    quarantines nothing; a missing file is an empty store."""
    base = Path(state_dir) if state_dir is not None else store.path().parent
    if (base / (store.filename + ".corrupted")).exists():
        raise StoreError("流程儲存先前偵測到損毀，需人工復原")
    parsed = strictjson.load_owned_object(base / store.filename, FLOWS_LIMITS)
    if not parsed.ok:
        if parsed.problem == "檔案不存在":
            return {}
        raise StoreError(f"流程儲存無法安全讀取（{parsed.problem}）")
    for key, value in parsed.value.items():
        problem = _entry_problem(key, value)
        if problem:
            raise StoreError(f"流程儲存含有不符結構的項目（{problem}）")
    return parsed.value


# --- input from the API (strict; ValueError on anything else) ----------------

def _clean_role(raw, *, executor: bool) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("角色必須是物件")
    allowed = {"name", "family", "model"} | ({"session_id", "workdir"} if executor else set())
    extra = set(raw) - allowed
    if extra:
        raise ValueError(f"角色不接受的欄位：{', '.join(sorted(map(str, extra)))}")
    name = raw.get("name")
    if not (isinstance(name, str) and name.strip() and len(name.strip()) <= MAX_NAME and "\x00" not in name):
        raise ValueError(f"角色名稱必須是 1–{MAX_NAME} 字的文字")
    if raw.get("family") not in FAMILIES:
        raise ValueError("模型家族必須是 " + "、".join(FAMILIES) + " 之一")
    role = {"name": name.strip(), "family": raw["family"]}
    model = raw.get("model")
    if model not in (None, ""):
        if not (isinstance(model, str) and len(model) <= MAX_NAME and "\x00" not in model):
            raise ValueError(f"模型名稱最多 {MAX_NAME} 字")
        if model.strip():
            role["model"] = model.strip()
    if executor:
        sid = raw.get("session_id")
        if sid not in (None, ""):
            if not (isinstance(sid, str) and SESSION_RE.match(sid)):
                raise ValueError("session id 格式不符（n- 加 12 碼十六進位）")
            role["session_id"] = sid
        wd = raw.get("workdir")
        if wd not in (None, ""):
            if not (isinstance(wd, str) and len(wd) <= MAX_PATH and "\x00" not in wd and os.path.isabs(wd)):
                raise ValueError("工作目錄必須是絕對路徑")
            wd = os.path.normpath(wd)
            if not os.path.isdir(wd):
                raise ValueError("工作目錄不存在")
            role["workdir"] = wd
    return role


def _clean_roles(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("roles 必須是物件")
    if set(raw) != {"planner", "executor", "reviewers"}:
        raise ValueError("roles 必須剛好有 planner、executor、reviewers")
    reviewers = raw["reviewers"]
    if not isinstance(reviewers, list) or not 1 <= len(reviewers) <= MAX_REVIEWERS:
        raise ValueError(f"審查者必須是 1–{MAX_REVIEWERS} 位")
    return {"planner": _clean_role(raw["planner"], executor=False),
            "executor": _clean_role(raw["executor"], executor=True),
            "reviewers": [_clean_role(r, executor=False) for r in reviewers]}


def _now_after(events: list) -> float:
    """Server time for a new event, never before the last one (a clock that
    stepped back must not make the log fail its own ordering check)."""
    now = _epoch(time.time())
    if now is None:
        raise StoreError("系統時間無效，無法記錄事件")
    last = _epoch(events[-1]["at"]) if events else None
    return max(now, last) if last is not None else now


def _get(flows: dict, flow_id) -> dict:
    if not (isinstance(flow_id, str) and FLOW_ID_RE.match(flow_id)):
        raise KeyError(flow_id)
    flow = flows.get(flow_id)
    if flow is None:
        raise KeyError(flow_id)
    return flow


def create_flow(body, task_exists: Callable[[str], bool]) -> dict:
    if not isinstance(body, dict):
        raise ValueError("請求必須是物件")
    extra = set(body) - {"task_id", "roles"}
    if extra:
        raise ValueError(f"不接受的欄位：{', '.join(sorted(map(str, extra)))}")
    task_id = body.get("task_id")
    if not (isinstance(task_id, str) and TASK_ID_RE.match(task_id)):
        raise ValueError("task_id 不合法")
    if not task_exists(task_id):
        raise ValueError("找不到這張任務卡")
    roles = _clean_roles(body.get("roles"))
    with store.locked():
        flows = store.load()
        if any(f["task_id"] == task_id for f in flows.values()):
            raise ValueError("這張任務卡已經有流程（一張任務卡對應一個流程）")
        if len(flows) >= MAX_FLOWS:
            raise ValueError(f"流程已達上限 {MAX_FLOWS} 個")
        flow_id = "flow-" + secrets.token_hex(6)
        flows[flow_id] = {"id": flow_id, "task_id": task_id, "created_at": _now_after([]),
                          "roles": roles, "events": []}
        store.save(flows)
        return flows[flow_id]


def append_event(flow_id, body) -> dict:
    """Record one manual event. The server sets time, sequence and source,
    and snapshots the families a review is judged by."""
    if not isinstance(body, dict):
        raise ValueError("請求必須是物件")
    kind = body.get("kind")
    if kind not in CLIENT_KINDS:
        raise ValueError("事件種類必須是 " + "、".join(CLIENT_KINDS) + " 之一")
    allowed = {"kind", "note"} | KIND_FIELDS.get(kind, frozenset())
    extra = set(body) - allowed
    if extra:
        raise ValueError(f"「{KIND_LABELS[kind]}」不接受的欄位：{', '.join(sorted(map(str, extra)))}")
    note = body.get("note", "")
    if not (isinstance(note, str) and len(note) <= MAX_NOTE and "\x00" not in note):
        raise ValueError(f"備註最多 {MAX_NOTE} 字")
    with store.locked():
        flows = store.load()
        flow = _get(flows, flow_id)
        if len(flow["events"]) >= MAX_EVENTS:
            raise ValueError(f"這個流程的事件已達上限 {MAX_EVENTS} 筆")
        event = {"seq": len(flow["events"]) + 1, "at": _now_after(flow["events"]), "kind": kind,
                 "source": "manual", "note": note}
        if kind in ("executor_report", "review_result"):
            commit = body.get("commit")
            if not (isinstance(commit, str) and COMMIT_RE.match(commit)):
                raise ValueError("commit 必須是完整的 40 或 64 碼小寫十六進位")
            event["commit"] = commit
        if kind == "review_result":
            if body.get("verdict") not in VERDICTS:
                raise ValueError("審查結論必須是 PASS、NEEDS_WORK、BLOCKED 之一")
            index = body.get("reviewer")
            reviewers = flow["roles"]["reviewers"]
            if not _is_int(index, 0, len(reviewers) - 1):
                raise ValueError("reviewer 必須是審查者的編號")
            r = reviewers[index]
            event.update(verdict=body["verdict"], executor_family=flow["roles"]["executor"]["family"],
                         reviewer={"index": index, "name": r["name"], "family": r["family"]})
        flow["events"].append(event)
        store.save(flows)
        return flow


def append_risk_acknowledged(flow_id, fields) -> dict:
    """Record a risk acceptance (design 10). Only the console's preview
    confirmation calls this, with the values of a server-held preview: the
    fields are validated as an acceptance (exactly the nine, each of its type
    and range) and the event's source is "console", which no manual route can
    write (append_event refuses the kind)."""
    problem = acceptance.record_problem(fields)
    if problem:
        raise ValueError(f"風險接受的內容不合法（{problem}）")
    with store.locked():
        flows = store.load()
        flow = _get(flows, flow_id)
        if len(flow["events"]) >= MAX_EVENTS:
            raise ValueError(f"這個流程的事件已達上限 {MAX_EVENTS} 筆")
        flow["events"].append({"seq": len(flow["events"]) + 1, "at": _now_after(flow["events"]),
                               "kind": "risk_acknowledged", "source": "console", "note": "", **fields})
        store.save(flows)
        return flow


def set_roles(flow_id, body) -> dict:
    if not isinstance(body, dict) or set(body) != {"roles"}:
        raise ValueError("請求必須只有 roles")
    roles = _clean_roles(body["roles"])
    with store.locked():
        flows = store.load()
        flow = _get(flows, flow_id)
        if len(flow["events"]) >= MAX_EVENTS:
            raise ValueError(f"這個流程的事件已達上限 {MAX_EVENTS} 筆")
        flow["roles"] = roles
        flow["events"].append({"seq": len(flow["events"]) + 1, "at": _now_after(flow["events"]),
                               "kind": "roles_changed", "source": "manual", "note": "", "roles": roles})
        store.save(flows)
        return flow


# --- derivation (every read; nothing stored) --------------------------------

def _independent(executor_family: str, reviewer_family: str) -> tuple[bool, str]:
    if reviewer_family in ("unknown", "other") or executor_family in ("unknown", "other"):
        return False, "模型家族不明（或為「其他」），無法確認是獨立審查，不算通過"
    if reviewer_family == executor_family:
        return False, f"審查者與執行者同為 {FAMILY_LABELS[reviewer_family]}，不算獨立審查，不算通過"
    return True, ""


def _short(commit) -> str:
    return commit[:7] if isinstance(commit, str) else "—"


def derive(flow: dict, heads: Callable[[str], dict]) -> dict:
    """Phase, review rounds and commit binding from the events, plus the
    executor's HEAD read now. ``flow`` is a stored flow (already validated).

    Once a merge is recorded, the round's commit is closed: later reviews of
    it, or a report of it again, are kept and shown but never move the phase
    back (a late PASS must not turn 「完成」 into 「等合併」; a late objection is
    flagged). Only a report of a different commit opens a new round."""
    state, reason = "planning", "還沒有提出計畫"
    current_commit, passed_commit = None, None
    closed = False          # the current round's commit has been merged
    rounds: list[dict] = []
    stray: list[dict] = []
    warnings: list[str] = []
    for e in flow["events"]:
        kind = e["kind"]
        if kind == "plan_submitted":
            state, reason = "awaiting_approval", "計畫已提出，等你核准"
        elif kind in ("plan_approved", "implementation_started"):
            if state in ("planning", "awaiting_approval", "implementing"):
                state, reason = "implementing", "執行者實作中"
        elif kind == "executor_report":
            if closed and e["commit"] == current_commit:
                warnings.append(f"合併後又回報同一個 commit {_short(e['commit'])}，不開始新一輪")
                continue
            current_commit, passed_commit, closed = e["commit"], None, False
            rounds.append({"round": len(rounds) + 1, "commit": e["commit"], "reported_at": e["at"], "reviews": []})
            state, reason = "in_review", f"等待審查 {_short(e['commit'])}（第 {len(rounds)} 輪）"
        elif kind == "review_result":
            counted, why = _independent(e["executor_family"], e["reviewer"]["family"])
            row = {"reviewer": e["reviewer"]["name"], "family": e["reviewer"]["family"],
                   "executor_family": e["executor_family"], "verdict": e["verdict"], "commit": e["commit"],
                   "at": e["at"], "seq": e["seq"],
                   "counts_as_pass": e["verdict"] == "PASS" and counted,
                   "why": why if e["verdict"] == "PASS" and not counted else ""}
            if rounds and e["commit"] == current_commit and closed:
                row["counts_as_pass"] = False
                row["why"] = "合併後才記錄的審查，不改變階段"
                rounds[-1]["reviews"].append(row)
                if e["verdict"] != "PASS":
                    warnings.append(f"合併後才記錄的審查結論 {e['verdict']}（{e['reviewer']['name']}，"
                                    f"commit {_short(e['commit'])}）")
            elif rounds and e["commit"] == current_commit:
                rounds[-1]["reviews"].append(row)
                if e["verdict"] != "PASS":
                    state, reason = "needs_fix", f"審查結論 {e['verdict']}，等執行者修正"
                    passed_commit = None
                elif counted:
                    state, reason, passed_commit = "review_passed", "", e["commit"]
                elif passed_commit is None:
                    state, reason = "in_review", why
            else:
                row["why"] = "這筆審查的 commit 不是最新一次回報的 commit"
                row["counts_as_pass"] = False
                stray.append(row)
        elif kind == "merge_done":
            if state not in ("review_passed",):
                warnings.append("合併時沒有對應最新 commit 的有效審查通過")
            state, reason, closed = "awaiting_push", "已合併，等 push", True
        elif kind == "push_done":
            if state != "awaiting_push":
                warnings.append("push 之前沒有合併的紀錄")
            state, reason = "done", "已 push"
    binding = None
    if state == "review_passed":
        workdir = flow["roles"]["executor"].get("workdir")
        if not workdir:
            state, reason = "review_unverified", "沒有設定執行者的工作目錄，無法核對審查的 commit 是否仍是目前版本"
            binding = {"state": "unverified", "reviewed": passed_commit, "head": None, "detail": reason}
        else:
            head = heads(workdir) or {}
            commit = head.get("commit")
            if not (isinstance(commit, str) and COMMIT_RE.match(commit)):
                why = head.get("error") or "原因不明"
                state, reason = "review_unverified", f"讀不到執行者目前的 commit（{why}）"
                binding = {"state": "unverified", "reviewed": passed_commit, "head": None, "detail": reason}
            elif commit != passed_commit:
                state = "review_stale"
                reason = (f"審查通過的是 {_short(passed_commit)}，執行者目前在 {_short(commit)}："
                          "審查結果已過期，需要重新審查")
                binding = {"state": "stale", "reviewed": passed_commit, "head": commit, "detail": reason}
            else:
                state, reason = "awaiting_merge", f"審查通過的 {_short(commit)} 就是執行者目前的 commit，等你合併"
                binding = {"state": "current", "reviewed": passed_commit, "head": commit,
                           "detail": "只比對 commit，看不到未提交的修改"}
    label = PHASES[state]
    if state == "in_review" and rounds:
        label = f"審查第 {len(rounds)} 輪"
    return {"phase": {"key": state, "label": label, "reason": reason, "round": len(rounds)},
            "attention": state in ATTENTION_PHASES, "binding": binding, "rounds": rounds,
            "stray_reviews": stray, "warnings": warnings}


def _role_view(role: dict) -> dict:
    return {**role, "family_label": FAMILY_LABELS.get(role.get("family"), "不明")}


_LIVE_LABELS = {"working": "工作中", "waiting": "等你回覆", "needs-input": "需要你處理",
                "exited": "已結束", "unknown": "狀態未知"}


def live_freshness(live, now) -> dict:
    """How old the cached live view is. Its time is checked like any time
    this module did not just take: finite and in range, not ahead of now by
    more than the clock-skew allowance; within it, a clock that stepped back
    reads as age 0."""
    if live is None:
        return {"state": "missing", "generated_at": None, "age_s": None, "detail": "主控台還沒有即時資料"}
    now_t = _epoch(now)
    gen = _epoch(live.get("generated_at")) if isinstance(live, dict) else None
    if now_t is None or gen is None:
        return {"state": "invalid", "generated_at": None, "age_s": None, "detail": "即時資料沒有可用的產生時間"}
    if gen > now_t + CLOCK_SKEW_S:
        return {"state": "invalid", "generated_at": None, "age_s": None,
                "detail": "即時資料的產生時間比現在還晚，無法判斷新舊"}
    age = max(0.0, now_t - gen)               # both bounded by MAX_EPOCH_S: no overflow
    shown = int(age)                          # whole seconds, for display only
    if age > LIVE_STALE_S:                    # judged on the exact age: 30.1 s is already stale
        return {"state": "stale", "generated_at": gen, "age_s": shown,
                "detail": f"即時資料超過 {LIVE_STALE_S:g} 秒沒有更新（約 {shown} 秒前），不代表現在"}
    return {"state": "fresh", "generated_at": gen, "age_s": shown, "detail": f"即時資料是 {shown} 秒前的"}


def executor_live(session_id, live, now) -> dict:
    """The executor session's state from the cached live view, never shown
    as current unless the view is fresh and the runtime answered."""
    if not session_id:
        return {"state": "unbound", "label": "未綁定 session", "reason": "沒有設定執行者的 session", "freshness": None}
    fresh = live_freshness(live, now)
    if fresh["state"] == "missing":
        return {"state": "not_loaded", "label": "即時狀態未載入", "reason": fresh["detail"], "freshness": fresh}
    if fresh["state"] == "invalid":
        return {"state": "unknown", "label": "即時狀態時間不明", "reason": fresh["detail"], "freshness": fresh}
    runtime = live.get("runtime") if isinstance(live.get("runtime"), dict) else {}
    sessions = [x for x in live.get("sessions") or () if isinstance(x, dict)] \
        if isinstance(live.get("sessions"), list) else []
    panes = [x for x in live.get("panes") or () if isinstance(x, dict)] if isinstance(live.get("panes"), list) else []
    match = next((x for x in sessions if x.get("terminal_id") == session_id), None)
    if runtime.get("available") is False:     # only an explicit False proves it did not answer
        label, state, reason = "runtime 未連線", "unknown", "無法判斷 session 狀態"
    elif runtime.get("available") is not True:
        label, state, reason = "runtime 狀態不明", "unknown", "即時資料沒有可用的 runtime 狀態，無法判斷 session 狀態"
    elif match is not None:
        state = match.get("status") if match.get("status") in _LIVE_LABELS else "unknown"
        act = match.get("activity") if isinstance(match.get("activity"), dict) else {}
        label, reason = _LIVE_LABELS[state], act.get("reason") if isinstance(act.get("reason"), str) else ""
    elif any(p.get("pane_id") == session_id for p in panes):
        label, state, reason = "狀態未知", "unknown", "不是 Agent session"
    else:
        label, state, reason = "找不到 session", "missing", "這個 session 不在終端機清單（可能已結束）"
    if fresh["state"] == "stale":
        return {"state": "stale", "label": "即時狀態已過期",
                "reason": f"{fresh['detail']}；當時是「{label}」", "freshness": fresh}
    return {"state": state, "label": label, "reason": reason, "freshness": fresh}


# Whole login fingerprints are secrets of the user's accounts (an HMAC of the
# account identity): the server keeps them in the stored event and in the
# preview record and nothing that leaves it carries one. The projection of an
# event does the cutting in this one place (Codex S2c-1 review): the first 16
# hex digits under a *_prefix name, never the whole value.
_FINGERPRINT_FIELDS = {"executor_login_fingerprint": "executor_login_fingerprint_prefix",
                       "login_fingerprint": "login_fingerprint_prefix"}
FINGERPRINT_PREFIX = 16


def public_event(event: dict) -> dict:
    """A stored event as the API may show it."""
    out = dict(event)
    for name, shown in _FINGERPRINT_FIELDS.items():
        if name in out:
            value = out.pop(name)
            out[shown] = value[:FINGERPRINT_PREFIX] if isinstance(value, str) else None
    return out


def view(flow: dict, *, heads: Callable[[str], dict], task_title: Callable[[str], str | None],
         live: dict | None, now: float) -> dict:
    derived = derive(flow, heads)
    roles = flow["roles"]
    title = task_title(flow["task_id"])
    return {
        "id": flow["id"], "task_id": flow["task_id"], "task_title": title, "task_missing": title is None,
        "created_at": flow["created_at"],
        "roles": {"planner": _role_view(roles["planner"]), "executor": _role_view(roles["executor"]),
                  "reviewers": [_role_view(r) for r in roles["reviewers"]]},
        **derived,
        "latest_review": next((r for rnd in reversed(derived["rounds"]) for r in reversed(rnd["reviews"])), None),
        "executor_live": executor_live(roles["executor"].get("session_id"), live, now),
        "events": [{**public_event(e), "label": KIND_LABELS[e["kind"]],
                    "source_label": CONSOLE_LABEL if e["source"] == "console" else MANUAL_LABEL}
                   for e in flow["events"]],
    }


def delete_flow(flow_id) -> dict:
    """Remove a flow's own record (S2c-5). Its data on disk is the daemon's and
    is deleted first (flow_storage); KeyError when there is no such flow."""
    with store.locked():
        flows = store.load()
        flow = _get(flows, flow_id)
        del flows[flow_id]
        store.save(flows)
        return flow


def list_flows() -> list[dict]:
    return list(store.load().values())


def get_flow(flow_id) -> dict:
    return _get(store.load(), flow_id)


def head_reader(workdir: str) -> dict:
    return git_head.read_head(workdir)
