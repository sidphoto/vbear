"""Dispatch (P40-3): what happens to the chief of staff's proposal once it is kept: the record, the proposal card's confirmation,
「自己動手」 and 「AI 自己做了什麼」.

A dispatch is the work the chief of staff proposed, in steps, each for one employee. This module holds:

  * the record (``<state>/dispatch/d-<12 hex>.json``, 0600, one file each), its events (append-only: the server fills ``seq``
    and ``at``; ``by`` says who decided: ``you``, ``auto1`` / ``auto2`` (自己動手 item 1 / 2) or ``vbear``) and its states
    (proposed, confirming, running, paused, done, stopped, dismissed). The events are the only source of 「AI 自己做了什麼」;
  * ``Dispatcher.from_proposal``: a kept proposal becomes a ``proposed`` dispatch (the hook of the chief of staff's runner), and
    then 「自己動手」 may go on: item 1 makes the new employees, item 2 starts the dispatch, as ADR 0006 point 4 says (the table
    is in ``from_proposal``);
  * ``confirm``: the person's changed plan is checked again with the rules of the proposal (never looser: tool, position,
    length, steps, people), then the new employees (safe mode, the position's fixed words, no skill) and the task card are made,
    each as an intent event, the write and a result event, so that a stop in the middle is told afterwards as ``uncertain``;
  * ``dismiss``, ``withdraw_card`` (the employee is switched off, never deleted), ``delete`` (the dispatch and the proposal
    only; employees, task cards and chats stay), ``recover_all`` and ``actions``.

Sending the steps is not here (``vbear/dispatch_runner.py``, P40-4): a confirmed dispatch is ``running`` with every step
``pending``; ``stop`` and ``resume`` (the buttons 「停止」 and 「繼續」) are carried out by the runner attached as ``control`` and
answer 409 ``no_runner`` while there is none. Nothing here writes ``config.json``, starts a program or a
terminal, installs a skill or answers a question in a chat; ``tests/test_autonomy_guard.py`` keeps it that way. What is said of
the chat with the CEO never gets here: only the proposal does.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from . import agent_profiles as ap, autonomy, chat_service, chief, config as cfg, meetings as mt, model_options, position_guide, strictjson, tasks
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import chat_store as cs

DIR = "dispatch"
MAX_RECORDS = 200
MAX_FILE = 256 * 1024
MAX_EVENTS = 80
DISPATCH_ID_RE = cs.DISPATCH_RE
CHIEF_ID_RE = chief.CHIEF_ID_RE
ALIAS_RE = re.compile(r"^[CN][1-9][0-9]?\Z")

STATES = ("proposed", "confirming", "running", "paused", "done", "stopped", "dismissed")
DELETABLE_STATES = ("proposed", "dismissed", "done", "stopped")
BYS = ("you", "auto1", "auto2", "vbear")
BY_TEXT = {"you": "你確認的", "auto1": "自己動手第 1 項", "auto2": "自己動手第 2 項", "vbear": "VBear"}
# What the person pressed after the confirmation was not a confirmation (P40-6): the words for these events when ``by`` is "you".
PRESSED_KINDS = ("card_withdrawn", "continued", "stopped", "dismissed")
PRESSED_TEXT = "你按的"


def by_text_of(ev: dict) -> str:
    """Who decided an event, in words: 「你確認的」 for what the confirmation started, 「你按的」 for a withdrawal, a stop, a
    continue and a dismissal, the 「自己動手」 item or VBear otherwise."""
    return PRESSED_TEXT if ev["by"] == "you" and ev["kind"] in PRESSED_KINDS else BY_TEXT[ev["by"]]
STEP_STATES = ("pending", "sending", "running", "ended")

TITLE_MAX, GOAL_MAX, NAME_MAX, TEXT_MAX = 80, 500, 40, 1500
MAX_STEPS, MAX_NEW, MAX_TEAM = chief.MAX_STEPS, chief.MAX_NEW, chief.MAX_TEAM

ERRORS = {
    "bad_request": "請求不符格式",
    "not_found": "找不到這份派工",
    "storage": "派工的紀錄無法安全讀寫，請人工檢查狀態目錄",
    "too_many": f"派工已有 {MAX_RECORDS} 份，請先刪除不需要的",
    "not_proposed": "這份派工已經不在等你確認的狀態",
    "proposal_changed": "你看到的提議和現在的不一樣，請重新整理再確認",
    "card_unavailable": "有一位要派工的員工現在不能用了（已停用或已刪除）",
    "card_withdrawn": "有一位新員工已經撤回了，計畫裡還有步驟要交給他",
    "card_changed": "有一位要派工的員工在提議之後被改過了，請重新整理再確認",
    "tool_unavailable": "有一個 AI 工具現在不能聊天了",
    "create_failed": "建立員工或任務卡沒有成功",
    "no_runner": "還沒有 runner：停止與繼續要等派工執行起來才能用",
    "not_active": "這份派工沒有在進行（沒有在做，也沒有暫停），不能停止",
    "not_paused": "這份派工沒有暫停，不用按繼續",
    "chat_unreadable": "讀不到那一步的聊天，無法確認訊息有沒有送出，所以現在不能繼續。請先到那位員工的聊天看一下",
    "turn_running": "這位員工正在做事，等這一回合結束或先按停止，再撤回",
    "already_withdrawn": "這位員工已經撤回了",
    "not_deletable": "這份派工還在進行，不能刪除",
}
STATUS = {"bad_request": 400, "not_found": 404, "storage": 503}


class DispatchError(Exception):
    """A refusal in the person's words; ``code`` says which, ``status`` is the HTTP status the console answers with."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or ERRORS[code])
        self.code = code
        self.status = STATUS.get(code, 409)


def _bad(message: str) -> DispatchError:
    return DispatchError("bad_request", message)


# ---- why a dispatch is paused, in words --------------------------------------------------------------------------

PAUSE_TEXT = {
    "daily_limit": "今天的花費到了每天上限 US${limit}，本機明天 0:00 重新計算；到時候按「繼續」接著做第 {n} 步。",
    "plan_limit": "{tool} 的方案用量到了上限，{when}。",
    "busy": "這位員工還在別的聊天裡工作，等他做完再按「繼續」。",
    "limit": "同時聊天的員工已經到上限，先關掉別的聊天，再按「繼續」。",
    "restarting": "員工的程序正在重新啟動，稍後再按「繼續」。",
    "uncertain": "VBear 不確定剛才有沒有建好（員工、任務卡或送出的訊息）。請先到員工頁、任務頁和聊天看一下，再決定要不要按「繼續」（可能會再建一張，或再送一次）。",
    "interrupted": "派工在建立員工與任務卡的途中被中斷了。請到員工頁與任務頁看一下，再決定要不要按「繼續」。",
    "create_failed": "建立員工或任務卡沒有成功，什麼都沒有送出。請檢查之後再試。",
    "runner_error": "派工執行時出了預料之外的問題，已經先暫停。請稍後按「繼續」再試一次。",
    # a turn that did not end the normal way: what happened, then what 「繼續」 does
    "turn_stopped": "第 {n} 步的回合被停止了（可能是在聊天裡按了停止）。",
    "turn_timeout": "第 {n} 步等太久，逾時了。",
    "turn_process_exit": "第 {n} 步做到一半，員工的程序結束了。",
    "turn_violation": "第 {n} 步的員工違反了 VBear 的設定，VBear 把它停掉了。",
    "turn_daemon_restart": "VBear 的背景程序重新啟動，第 {n} 步被中斷了。",
    "turn_error": "第 {n} 步出了錯。",
    "turn_not_sent": "第 {n} 步的訊息沒有送到員工那裡。",
    "turn_limit": "第 {n} 步用到了每回合的花費上限，被停下來了。",
    "turn_is_error": "員工回報第 {n} 步沒有成功。",
}
TURN_SUFFIX = "要接著做下一步，請按「繼續」（會附上這一步的回覆，並標明它可能不完整）。"
_PAUSE_DEFAULTS = {"limit": "未知", "n": "?", "tool": "AI 工具", "when": "恢復時間未知"}


def pause_text(reason: str, **context) -> str:
    """The sentence for a pause. A time that has no source is 「未知」. A reason this table does not know is the code of a chat
    refusal when the chat service has a sentence for it (said in its words), else it is said as it is."""
    template = PAUSE_TEXT.get(reason)
    if template is None:
        if isinstance(reason, str) and reason in chat_service.CODE_TEXT:
            return chat_service.explain(reason)
        return f"暫停了（原因代碼「{str(reason)[:64]}」），VBear 沒有這個代碼的說明。"
    text = template.format_map({**_PAUSE_DEFAULTS, **{k: v for k, v in context.items() if v is not None}})
    return text + TURN_SUFFIX if reason.startswith("turn_") else text


# ---- the record ------------------------------------------------------------------------------------------------------

_RECORD_KEYS = {"id", "chief_id", "chat_id", "created_at", "state", "started_by", "summary", "questions", "notes", "team", "tools",
                "proposal_sha", "proposal_plan", "plan", "cards", "made", "task_id", "steps", "pause", "events"}
_PLAN_KEYS = {"title", "goal", "deliverables", "new_cards", "steps"}
_NEW_CARD_KEYS = {"ref", "name", "position", "tool", "model_alias"}
_STEP_KEYS = {"seq", "who", "name", "profile_id", "chat_id", "text", "state", "turn", "cost_usd", "ended_reason"}
_CARD_KEYS = {"profile_id", "revision", "name", "position", "tool"}


def _text_ok(value, limit: int, *, empty: bool = True) -> bool:
    return isinstance(value, str) and len(value) <= limit and (empty or bool(value.strip()))


def _texts_ok(value, count: int, limit: int) -> bool:
    return isinstance(value, list) and len(value) <= count and all(_text_ok(v, limit) for v in value)


def _profile_id_ok(value) -> bool:
    return isinstance(value, str) and bool(chief.PROFILE_ID_RE.match(value))


def _plan_problem(plan) -> str | None:
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        return "計畫欄位不符"
    if not _text_ok(plan["title"], TITLE_MAX) or not _text_ok(plan["goal"], GOAL_MAX):
        return "計畫的名稱或目標不符"
    if not _texts_ok(plan["deliverables"], chief.MAX_DELIVERABLES, 120):
        return "計畫的交付物不符"
    cards = plan["new_cards"]
    if not isinstance(cards, list) or len(cards) > MAX_NEW:
        return "計畫的新員工不符"
    for c in cards:
        if (not isinstance(c, dict) or set(c) != _NEW_CARD_KEYS or not isinstance(c["ref"], str) or not chief.NEW_REF_RE.match(c["ref"])
                or not _text_ok(c["name"], NAME_MAX, empty=False) or c["position"] not in chief.NEW_POSITIONS
                or c["tool"] not in ap.TOOL_ORDER or c["model_alias"] not in model_options.CLAUDE_ALIASES + ("",)):
            return "計畫的新員工不符"
    steps = plan["steps"]
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        return "計畫的步驟不符"
    for s in steps:
        if not isinstance(s, dict) or set(s) != {"who", "text"} or not isinstance(s["who"], str) or not ALIAS_RE.match(s["who"]) \
                or not _text_ok(s["text"], TEXT_MAX, empty=False):
            return "計畫的步驟不符"
    return None


def _step_problem(step) -> str | None:
    if not isinstance(step, dict) or set(step) != _STEP_KEYS:
        return "步驟欄位不符"
    if type(step["seq"]) is not int or not 1 <= step["seq"] <= MAX_STEPS or not isinstance(step["who"], str) or not ALIAS_RE.match(step["who"]):
        return "步驟編號不符"
    if not _text_ok(step["name"], 200) or not _text_ok(step["text"], TEXT_MAX, empty=False):
        return "步驟文字不符"
    if step["profile_id"] is not None and not _profile_id_ok(step["profile_id"]):
        return "步驟的員工不符"
    if step["chat_id"] is not None and not (isinstance(step["chat_id"], str) and chief.CHAT_ID_RE.match(step["chat_id"])):
        return "步驟的聊天不符"
    if step["state"] not in STEP_STATES:
        return "步驟狀態不符"
    if step["turn"] is not None and (type(step["turn"]) is not int or step["turn"] < 1):
        return "步驟回合不符"
    if step["cost_usd"] is not None and mt.money(step["cost_usd"]) is None:
        return "步驟花費不符"
    if step["ended_reason"] is not None and not _text_ok(step["ended_reason"], 64):
        return "步驟結束原因不符"
    return None


def _count(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


# kind -> {field: check}; the fields an event has besides seq, at, kind and by (a step is ``step``: ``seq`` is the event's own number)
_EVENT_FIELDS = {
    "proposed": {},
    "confirmed": {"edited": lambda v: type(v) is bool},
    "dismissed": {},
    "card_intent": {"ref": lambda v: isinstance(v, str) and bool(chief.NEW_REF_RE.match(v))},
    "card_created": {"ref": lambda v: isinstance(v, str) and bool(chief.NEW_REF_RE.match(v)), "profile_id": _profile_id_ok},
    "task_intent": {},
    "task_created": {"task_id": lambda v: isinstance(v, str) and 0 < len(v) <= 64},
    "step_intent": {"step": lambda v: _count(v, 1, MAX_STEPS)},
    "step_sent": {"step": lambda v: _count(v, 1, MAX_STEPS), "chat_id": lambda v: isinstance(v, str) and bool(chief.CHAT_ID_RE.match(v)),
                  "turn": lambda v: _count(v, 1, 10 ** 6)},
    "step_ended": {"step": lambda v: _count(v, 1, MAX_STEPS), "reason": lambda v: _text_ok(v, 64, empty=False),
                   "cost_usd": lambda v: mt.money(v) is not None},
    "paused": {"reason": lambda v: _text_ok(v, 64, empty=False)},
    "continued": {},
    "stopped": {},
    "card_withdrawn": {"profile_id": _profile_id_ok},
    "done": {},
}
_EVENT_OPTIONAL = {"paused": {"until": lambda v: v is None or mt._epoch(v)}}


def _event_problem(ev) -> str | None:
    if not isinstance(ev, dict) or ev.get("kind") not in _EVENT_FIELDS:
        return "事件種類不符"
    spec, optional = _EVENT_FIELDS[ev["kind"]], _EVENT_OPTIONAL.get(ev["kind"], {})
    body = set(ev) - {"seq", "at", "kind", "by"}
    if not set(spec) <= body or body - set(spec) - set(optional) or not _count(ev.get("seq"), 1, MAX_EVENTS):
        return "事件欄位不符"
    if not mt._epoch(ev.get("at")) or ev.get("by") not in BYS:
        return "事件時間或決定者不符"
    for name, check in {**spec, **optional}.items():
        if name in ev and not check(ev[name]):
            return f"事件 {name} 不符"
    return None


def record_problem(rec) -> str | None:
    """None, or why this is not a dispatch this module could have written."""
    if not isinstance(rec, dict) or set(rec) != _RECORD_KEYS:
        return "欄位不符"
    if not isinstance(rec["id"], str) or not DISPATCH_ID_RE.match(rec["id"]):
        return "id 不符"
    if not isinstance(rec["chief_id"], str) or not CHIEF_ID_RE.match(rec["chief_id"]):
        return "幕僚長的紀錄識別碼不符"
    if not isinstance(rec["chat_id"], str) or not chief.CHAT_ID_RE.match(rec["chat_id"]):
        return "chat_id 不符"
    if not mt._epoch(rec["created_at"]):
        return "時間不符"
    if rec["state"] not in STATES:
        return "狀態不符"
    if rec["started_by"] not in (None, "you", "auto2"):
        return "開始的人不符"
    if not _text_ok(rec["summary"], 300) or not _texts_ok(rec["questions"], chief.MAX_QUESTIONS, 150):
        return "說明或問題不符"
    notes = rec["notes"]
    if not isinstance(notes, list) or any(not isinstance(n, dict) or set(n) != {"code", "text"} or n["code"] not in chief.NOTES
                                          or not _text_ok(n["text"], 300) for n in notes):
        return "註記不符"
    team = rec["team"]
    if not isinstance(team, list) or len(team) > MAX_TEAM or any(
            not isinstance(t, dict) or set(t) != {"who", "why"} or not isinstance(t["who"], str) or not ALIAS_RE.match(t["who"])
            or not _text_ok(t["why"], 120) for t in team):
        return "隊伍不符"
    tools = rec["tools"]
    if not isinstance(tools, list) or len(tools) > len(ap.TOOL_ORDER) or any(t not in ap.TOOL_ORDER for t in tools):
        return "工具不符"
    if not isinstance(rec["proposal_sha"], str) or not mt.HEX64_RE.match(rec["proposal_sha"]):
        return "提議雜湊不符"
    for key in ("proposal_plan", "plan"):
        if (problem := _plan_problem(rec[key])) is not None:
            return problem
    cards = rec["cards"]
    if not isinstance(cards, dict) or len(cards) > chief.MAX_CARDS or any(
            not isinstance(k, str) or not chief.CARD_ALIAS_RE.match(k) or not isinstance(v, dict) or set(v) != _CARD_KEYS
            or not _profile_id_ok(v["profile_id"]) or not isinstance(v["revision"], str) or not mt.HEX64_RE.match(v["revision"])
            or not all(_text_ok(v[f], 200) for f in ("name", "position", "tool")) for k, v in cards.items()):
        return "員工清單不符"
    made = rec["made"]
    if not isinstance(made, dict) or any(not isinstance(k, str) or not chief.NEW_REF_RE.match(k) or not _profile_id_ok(v)
                                         for k, v in made.items()):
        return "建好的員工不符"
    if rec["task_id"] is not None and not (isinstance(rec["task_id"], str) and 0 < len(rec["task_id"]) <= 64):
        return "任務卡不符"
    steps = rec["steps"]
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        return "步驟數量不符"
    for i, step in enumerate(steps, 1):
        if (problem := _step_problem(step)) is not None or step["seq"] != i:
            return problem or "步驟順序不符"
    pause = rec["pause"]
    if pause is not None and (not isinstance(pause, dict) or set(pause) != {"reason", "until"}
                              or not _text_ok(pause["reason"], 64, empty=False) or (pause["until"] is not None and not mt._epoch(pause["until"]))):
        return "暫停不符"
    events = rec["events"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        return "事件數量不符"
    for i, ev in enumerate(events, 1):
        if (problem := _event_problem(ev)) is not None or ev["seq"] != i:
            return problem or "事件順序不符"
    return None


class DispatchStore(GuardedJsonStore):
    """One dispatch, one file (0600) in a 0700 folder of its own; ``load`` checks the record as a whole and a damaged one is
    quarantined behind a marker that blocks it alone (as the chief of staff's store does)."""

    def __init__(self, dispatch_id: str):
        if not isinstance(dispatch_id, str) or not DISPATCH_ID_RE.match(dispatch_id):
            raise _bad("派工的識別碼不符")
        self.dispatch_id = dispatch_id
        super().__init__(f"{DIR}/{dispatch_id}.json", "派工的紀錄", lambda key, value: None)

    def locked(self, timeout: float = 10.0):
        self._make_folder()
        return super().locked(timeout)

    def _make_folder(self):
        cfg.ensure_state_dir()
        os.makedirs(self.path().parent, mode=cfg.STATE_DIR_MODE, exist_ok=True)
        os.chmod(self.path().parent, cfg.STATE_DIR_MODE)

    def _read_raw(self):
        try:
            fd, st = strictjson.open_owned(self.path(), max_bytes=MAX_FILE)
        except strictjson.ReadRefused as exc:
            if exc.missing:
                return None
            raise OSError("派工的紀錄拒絕讀取") from exc
        try:
            if st.st_nlink != 1:
                raise OSError("派工的紀錄有多個連結")
            return strictjson.read_fd(fd, MAX_FILE).decode("utf-8")
        except strictjson.ReadRefused as exc:
            raise OSError("派工的紀錄超過大小限制") from exc
        finally:
            os.close(fd)

    def load(self):
        data = super().load()
        if data:
            problem = record_problem(data)
            if problem is None and data["id"] != self.dispatch_id:
                problem = "id 與檔名不一致"
            if problem is not None:
                where = self._quarantine(ValueError(problem))
                raise StoreError(f"派工的紀錄結構不符（{problem}），已隔離至 {where}，請人工復原後刪除 {self.marker_path()} 以恢復讀寫")
        return data

    def save(self, data):
        problem = record_problem(data)
        if problem is not None:
            raise StoreError(f"拒絕寫入不符結構的派工紀錄（{problem}）")
        if len(json.dumps(data, ensure_ascii=False, indent=2).encode()) > MAX_FILE:
            raise StoreError("派工的紀錄超過 256 KiB，拒絕寫入")
        self._make_folder()
        super().save(data)


def folder() -> Path:
    return cfg.state_dir() / DIR


def record_ids() -> list[str]:
    """The ids of the records in the folder: a record file, or the marker a damaged one left (so that it stays listed)."""
    try:
        names = os.listdir(folder())
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise DispatchError("storage") from exc
    found = {n.split(".", 1)[0] for n in names if n.endswith((".json", ".json.corrupted"))}
    return sorted(i for i in found if DISPATCH_ID_RE.match(i))


def load(dispatch_id: str) -> dict:
    try:
        data = DispatchStore(dispatch_id).load()
    except StoreError as exc:
        raise DispatchError("storage", str(exc)) from None
    if not data:
        raise DispatchError("not_found")
    return data


def _canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def new_id() -> str:
    return "d-" + secrets.token_hex(6)


# ---- what an event says, and the view ----------------------------------------------------------------------------------

def _name_of(rec: dict, who: str) -> str:
    for c in rec["plan"]["new_cards"]:
        if c["ref"] == who:
            return c["name"]
    card = rec["cards"].get(who)
    return card["name"] if card else ""


def _step_name(rec: dict, seq: int) -> str:
    for s in rec["steps"]:
        if s["seq"] == seq:
            return s["name"]
    return ""


def _tool_of(rec: dict, who: str) -> str | None:
    for c in rec["plan"]["new_cards"]:
        if c["ref"] == who:
            return c["tool"]
    card = rec["cards"].get(who)
    return card["tool"] if card else None


def pause_context(rec: dict, ev: dict, daily_usd: Decimal | None = None) -> dict:
    """What a pause's sentence needs, as it was when the pause was written: the step it is about (the one that ended badly for a
    turn that did not end the normal way or a plan's limit, the one that was to go out for the rest), the AI tool of its employee,
    the daily limit in force and the time the AI tool said it would be usable again (none is 「未知」)."""
    before = [e for e in rec["events"] if e["seq"] < ev["seq"] and e["kind"] == "step_ended"]
    reason = ev["reason"]
    after_a_turn = reason.startswith("turn_") or reason == "plan_limit"
    n = (before[-1]["step"] if after_a_turn else before[-1]["step"] + 1) if before else (None if after_a_turn else 1)
    context: dict = {"n": n}
    if daily_usd is not None:
        context["limit"] = mt.fmt(daily_usd)
    step = next((s for s in rec["steps"] if s["seq"] == n), None)
    if step is not None:
        context["tool"] = chat_service.tool_label(_tool_of(rec, step["who"]))
    until = ev.get("until")
    if until is not None:
        context["when"] = "預計 " + time.strftime("%m/%d %H:%M", time.localtime(until)) + " 恢復（AI 工具說的）"
    return context


def describe(rec: dict, ev: dict, daily_usd: Decimal | None = None) -> str:
    """What an event says to the person, in words. The names are the cards' (as the person's page shows them); nothing of the
    conversation with the CEO is ever in a record, so none can be here."""
    kind = ev["kind"]
    if kind == "proposed":
        return "幕僚長提出了一份派工提議"
    if kind == "confirmed":
        return "確認了派工，開始準備" if ev["by"] == "you" else "照幕僚長的提議開始派工"
    if kind == "dismissed":
        return "不採用這份提議"
    if kind == "card_created":
        return f"建了新員工「{_name_of(rec, ev['ref'])}」（安全模式，沒有技能）"
    if kind == "card_intent":
        done = any(e["kind"] == "card_created" and e["ref"] == ev["ref"] for e in rec["events"])
        return f"建新員工「{_name_of(rec, ev['ref'])}」" + ("" if done else "（沒有看到結果，不確定有沒有建好）")
    if kind == "task_created":
        return "建了一張任務卡"
    if kind == "task_intent":
        done = any(e["kind"] == "task_created" for e in rec["events"])
        return "建任務卡" + ("" if done else "（沒有看到結果，不確定有沒有建好）")
    if kind == "step_intent":
        return f"準備送出第 {ev['step']} 步給「{_step_name(rec, ev['step'])}」"
    if kind == "step_sent":
        return f"送出第 {ev['step']} 步給「{_step_name(rec, ev['step'])}」（已經送出，收不回來）"
    if kind == "step_ended":
        return f"第 {ev['step']} 步結束（{ev['reason']}）"
    if kind == "paused":
        return "暫停：" + pause_text(ev["reason"], **pause_context(rec, ev, daily_usd))
    if kind == "continued":
        return "繼續派工"
    if kind == "stopped":
        return "停止派工"
    if kind == "card_withdrawn":
        name = next((_name_of(rec, ref) for ref, pid in rec["made"].items() if pid == ev["profile_id"]), "")
        return f"撤回了新員工「{name}」（停用，沒有刪除）"
    return "派工做完了"


def _withdrawn(rec: dict) -> set:
    return {e["profile_id"] for e in rec["events"] if e["kind"] == "card_withdrawn"}


def can_delete(rec: dict) -> bool:
    return rec["state"] in DELETABLE_STATES or (rec["state"] == "paused" and all(s["state"] == "pending" for s in rec["steps"]))


def view(rec: dict, *, per_turn: Decimal | None = None, day_left: Decimal | None = None, daily_usd: Decimal | None = None) -> dict:
    """A dispatch as the API shows it: its plan with names for the codes, the steps, what the person may do, and, when the
    limits are known, the most it may cost. No word of the conversation (the record holds none)."""
    plan = copy.deepcopy(rec["plan"])
    for item in plan["steps"]:
        item["name"] = _name_of(rec, item["who"])
    new = {c["ref"] for c in plan["new_cards"]}
    team = [{**t, "kind": "new" if t["who"] in new else "existing", "name": _name_of(rec, t["who"])} for t in rec["team"]]
    withdrawn = _withdrawn(rec)
    made = [{"ref": ref, "name": _name_of(rec, ref), "profile_id": pid, "withdrawn": pid in withdrawn} for ref, pid in rec["made"].items()]
    state = rec["state"]
    steps = len(rec["steps"]) or len(plan["steps"])
    cost = {"steps": steps, "per_turn_usd": mt.fmt(per_turn) if per_turn is not None else None,
            "max_usd": mt.fmt(per_turn * steps) if per_turn is not None else None,
            "day_left_usd": mt.fmt(day_left) if day_left is not None else None}
    pause = rec["pause"]
    pause_words = None
    if pause is not None:
        paused_at = next((e for e in reversed(rec["events"]) if e["kind"] == "paused"),
                         {"seq": MAX_EVENTS + 1, "reason": pause["reason"], "until": pause["until"]})
        pause_words = pause_text(pause["reason"], **pause_context(rec, paused_at, daily_usd))
    return {"id": rec["id"], "chief_id": rec["chief_id"], "chat_id": rec["chat_id"], "created_at": rec["created_at"], "state": state,
            "started_by": rec["started_by"], "started_by_text": BY_TEXT.get(rec["started_by"]), "summary": rec["summary"],
            "questions": list(rec["questions"]), "notes": copy.deepcopy(rec["notes"]), "team": team,
            "proposal_sha": rec["proposal_sha"], "plan": plan, "edited": rec["plan"] != rec["proposal_plan"], "steps": copy.deepcopy(rec["steps"]),
            "task_id": rec["task_id"], "created_cards": made, "tools": list(rec["tools"]), "cost": cost,
            "pause": None if pause is None else {"reason": pause["reason"], "until": pause["until"], "text": pause_words},
            "events": [{**e, "what": describe(rec, e, daily_usd), "by_text": by_text_of(e)} for e in rec["events"]],
            "can": {"confirm": state == "proposed" and bool(plan["steps"]), "dismiss": state == "proposed",
                    "stop": state in ("running", "paused"), "continue": state == "paused", "delete": can_delete(rec),
                    "withdraw": [m["profile_id"] for m in made if not m["withdrawn"]]}}


def summary_row(rec: dict) -> dict:
    return {"id": rec["id"], "chief_id": rec["chief_id"], "chat_id": rec["chat_id"], "created_at": rec["created_at"], "state": rec["state"],
            "title": rec["plan"]["title"], "steps": len(rec["steps"]) or len(rec["plan"]["steps"]), "started_by": rec["started_by"]}


# ---- the confirmation's rules -----------------------------------------------------------------------------------------------

def _line(value, limit: int, label: str, *, one_line: bool = False) -> str:
    try:
        text = mt.clean_line(value, limit, label, required=True)
    except mt.MeetingError as exc:
        raise _bad(str(exc)) from None
    if one_line and "\n" in text:
        raise _bad(f"{label} 只能一行")
    return text


def checked_plan(body, rec: dict) -> dict:
    """The person's changed plan, checked with the proposal's rules and never looser (the tools the proposal could name, the
    positions it could name, no more steps, people or new employees than it could have, its lengths): the plan to keep, or
    DispatchError (400 for the shape, 409 when it is not the proposal that was shown). What was already made stays as it is."""
    if not isinstance(body, dict) or set(body) != {"proposal_sha", "title", "goal", "new_cards", "steps"}:
        raise _bad("只需要 proposal_sha、title、goal、new_cards、steps")
    sha = body["proposal_sha"]
    if not isinstance(sha, str) or not mt.HEX64_RE.match(sha):
        raise _bad("proposal_sha 不符格式")
    if sha != rec["proposal_sha"]:
        raise DispatchError("proposal_changed")
    title, goal = _line(body["title"], TITLE_MAX, "任務名稱"), _line(body["goal"], GOAL_MAX, "任務目標")
    proposed = {c["ref"] for c in rec["proposal_plan"]["new_cards"]}
    raw_cards = body["new_cards"]
    if not isinstance(raw_cards, list) or len(raw_cards) > MAX_NEW:
        raise _bad(f"新員工最多 {MAX_NEW} 位")
    made = rec["made"]
    new_cards: list[dict] = [c for c in rec["plan"]["new_cards"] if c["ref"] in made]   # made already: it is as it was made
    for raw in raw_cards:
        if not isinstance(raw, dict) or set(raw) != _NEW_CARD_KEYS:
            raise _bad("新員工的欄位不符")
        ref = raw["ref"]
        if not isinstance(ref, str) or ref not in proposed or any(c["ref"] == ref for c in new_cards) and ref not in made:
            raise _bad("新員工的代號不是提議裡的，或重複了")
        if ref in made:
            continue                     # the employee is made already (自己動手 item 1): it stays as it was made
        if raw["position"] not in chief.NEW_POSITIONS:
            raise _bad("新員工的職位不能是 CEO，也必須是已知的職位")
        if raw["tool"] not in rec["tools"]:
            raise _bad("新員工的 AI 工具不在提議可以用的範圍")
        if raw["model_alias"] not in model_options.CLAUDE_ALIASES + ("",) or (raw["tool"] != "claude" and raw["model_alias"]):
            raise _bad("模型別名不符（只有 Claude Code 的員工可以填，而且必須是已知的別名）")
        new_cards.append({"ref": ref, "name": _line(raw["name"], NAME_MAX, "新員工的名字", one_line=True), "position": raw["position"],
                          "tool": raw["tool"], "model_alias": raw["model_alias"]})
    raw_steps = body["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise _bad(f"步驟必須是 1 到 {MAX_STEPS} 步")
    refs = {c["ref"] for c in new_cards}
    steps = []
    for n, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict) or set(raw) != {"who", "text"} or not isinstance(raw["who"], str):
            raise _bad(f"第 {n} 步的欄位不符")
        if raw["who"] not in refs and raw["who"] not in rec["cards"]:
            raise _bad(f"第 {n} 步指到清單外的員工，或指到已經拿掉的新員工")
        steps.append({"who": raw["who"], "text": _line(raw["text"], TEXT_MAX, f"第 {n} 步的內容")})
    if len({s["who"] for s in steps}) > MAX_TEAM:
        raise _bad(f"一次最多找 {MAX_TEAM} 位員工")
    return {"title": title, "goal": goal, "deliverables": list(rec["proposal_plan"]["deliverables"]), "new_cards": new_cards, "steps": steps}


def card_body(item: dict) -> dict:
    """The employee VBear makes from a new card of the plan: always safe mode, the position's own fixed words as its
    instructions (never a word the chief of staff wrote), no skill, and the AI tool and model the plan names."""
    position = item["position"]
    model_id = ""
    if item["tool"] == "claude":
        suggested = next((r["suggested_model_alias"] for r in ap.POSITION_TABLE if r["id"] == position), None)
        model_id = item["model_alias"] or (suggested if suggested in model_options.CLAUDE_ALIASES else "")
    return {"name": item["name"], "position": position, "instructions": position_guide.GUIDE[position]["prompt"],
            "launch_mode": "safe", "model": {"tool": item["tool"], "model_id": model_id}, "equipped_skill_ids": [], "enabled": True}


# ---- the dispatcher ----------------------------------------------------------------------------------------------------------

class Dispatcher:
    """What the console does with dispatches. ``conf``: a function returning the console's config; ``tools``: the AI tools
    whose chat can run now; ``link(chief_id, dispatch_id)``: records the dispatch on the chief of staff's proposal;
    ``busy(chat_id)``: whether a turn is running in that chat (an answer it cannot give counts as yes); ``day_left``: a function
    returning what the day has left, or None."""

    def __init__(self, *, conf: Callable[[], dict], tools: Callable[[], tuple], link: Callable[[str, str], None],
                 busy: Callable[[str], bool] | None = None, day_left: Callable[[], Decimal | None] | None = None,
                 clock: Callable[[], float] = time.time):
        self.conf, self.tools, self.link, self.clock = conf, tools, link, clock
        self.busy = busy or (lambda chat_id: False)
        self.day_left = day_left or (lambda: None)
        self.lock = threading.Lock()
        self.control = None                  # the runner (vbear/dispatch_runner.py): it carries out stop and resume

    # -- the record ------------------------------------------------------------------------------------------------

    def _mutate(self, dispatch_id: str, change: Callable[[dict], None]) -> dict:
        store = DispatchStore(dispatch_id)
        try:
            with store.locked():
                rec = store.load()
                if not rec:
                    raise DispatchError("not_found")
                change(rec)
                store.save(rec)
                return rec
        except StoreError as exc:
            raise DispatchError("storage", str(exc)) from None

    def _event(self, rec: dict, kind: str, by: str, **fields) -> None:
        rec["events"].append({"seq": len(rec["events"]) + 1, "at": self.clock(), "kind": kind, "by": by, **fields})

    def _pause(self, dispatch_id: str, reason: str, by: str = "vbear", until: float | None = None) -> dict:
        def change(rec):
            rec["state"], rec["pause"] = "paused", {"reason": reason, "until": until}
            self._event(rec, "paused", by, reason=reason, **({"until": until} if until is not None else {}))
        return self._mutate(dispatch_id, change)

    # what the runner uses (one transaction on a record, an event for it)
    def mutate(self, dispatch_id: str, change: Callable[[dict], None]) -> dict:
        return self._mutate(dispatch_id, change)

    def add_event(self, rec: dict, kind: str, by: str, **fields) -> None:
        self._event(rec, kind, by, **fields)

    def _view(self, rec: dict) -> dict:
        conf = self.conf()
        per_turn = cs.limits_from(conf)["per_turn_usd"]
        try:
            left = self.day_left()
        except Exception:
            left = None
        return view(rec, per_turn=per_turn, day_left=left, daily_usd=mt.limits_from(conf)["daily_usd"])

    def _by_chief(self, chief_id: str) -> str | None:
        for did in record_ids():
            try:
                if load(did)["chief_id"] == chief_id:
                    return did
            except DispatchError:
                continue
        return None

    # -- from a proposal ----------------------------------------------------------------------------------------

    def from_proposal(self, chief_id: str) -> str:
        """The dispatch for a kept proposal (the ``on_proposal`` hook of the chief of staff's runner): a ``proposed`` record,
        linked on the proposal, and then 「自己動手」, in the table of ADR 0006 point 4:

            item 1 (new employees)   item 2 (dispatch)   when the proposal arrives
            off                      off                 stays on the proposal card
            on                       off                 the new employees are made (auto1); stays on the card
            off                      on                  nobody new, no note, no question: starts (auto2); else stays
            on                       on                  no note, no question: new employees (auto1), then starts (auto2);
                                                         else only the new employees; stays on the card

        Asked twice for one proposal it answers the dispatch it made the first time."""
        with self.lock:
            did = self._by_chief(chief_id)
            if did is not None:
                return did
            crec = chief.load(chief_id)
            turn = crec["turns"][0]
            if turn["output"] is None:
                raise _bad("這份幕僚長的提議還沒有結果")
            kept, notes = turn["output"]["kept"], turn["output"]["notes"]
            if len(record_ids()) >= MAX_RECORDS:
                raise DispatchError("too_many")
            store_id = new_id()
            while DispatchStore(store_id).path().exists() or DispatchStore(store_id).marker_path().exists():
                store_id = new_id()
            plan = {"title": kept["task"]["title"].strip(), "goal": kept["task"]["goal"].strip(),
                    "deliverables": list(kept["task"]["deliverables"]),
                    "new_cards": [{k: c[k] for k in ("ref", "name", "position", "tool", "model_alias")} for c in kept["new_cards"]],
                    "steps": [{"who": s["who"], "text": s["text"]} for s in kept["steps"]]}
            rec = {"id": store_id, "chief_id": chief_id, "chat_id": crec["chat_id"], "created_at": self.clock(), "state": "proposed",
                   "started_by": None, "summary": kept["summary"], "questions": list(kept["questions"]), "notes": copy.deepcopy(notes),
                   "team": [{"who": t["who"], "why": t["why"]} for t in kept["team"]], "tools": list(crec["sent"]["tools"]),
                   "proposal_sha": _canonical_sha(kept), "proposal_plan": plan, "plan": copy.deepcopy(plan),
                   "cards": {c["alias"]: {k: c[k] for k in ("profile_id", "revision", "name", "position", "tool")}
                             for c in crec["sent"]["cards"]},
                   "made": {}, "task_id": None, "steps": [], "pause": None, "events": []}
            self._event(rec, "proposed", "vbear")
            store = DispatchStore(store_id)
            try:
                with store.locked():
                    store.save(rec)
            except StoreError as exc:
                raise DispatchError("storage", str(exc)) from None
            try:
                self.link(chief_id, store_id)
            except BaseException:
                self._remove_file(store_id)
                raise
        self._go_on_by_itself(store_id)
        return store_id

    def _go_on_by_itself(self, dispatch_id: str) -> None:
        ticks = autonomy.read(self.conf())
        rec = load(dispatch_id)
        if ticks["create_cards"] and rec["plan"]["new_cards"]:
            self._make_cards(dispatch_id, "auto1")
            rec = load(dispatch_id)
        clean = not rec["notes"] and not rec["questions"] and bool(rec["plan"]["steps"])
        if (ticks["dispatch"] and clean and rec["state"] == "proposed"
                and all(c["ref"] in rec["made"] for c in rec["plan"]["new_cards"])):
            body = {"proposal_sha": rec["proposal_sha"], "title": rec["plan"]["title"], "goal": rec["plan"]["goal"],
                    "new_cards": copy.deepcopy(rec["plan"]["new_cards"]), "steps": copy.deepcopy(rec["plan"]["steps"])}
            self.confirm(dispatch_id, body, by="auto2")

    # -- reading -------------------------------------------------------------------------------------------------

    def get(self, dispatch_id: str) -> dict:
        return self._view(load(dispatch_id))

    def list(self) -> dict:
        out = []
        for did in record_ids():
            try:
                out.append(summary_row(load(did)))
            except DispatchError as exc:
                out.append({"id": did, "blocked": True, "error": str(exc)})
        out.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return {"dispatch": out}

    # -- confirming ----------------------------------------------------------------------------------------------

    def confirm(self, dispatch_id: str, body, *, by: str = "you") -> dict:
        """The person's confirmation of the proposal card (``by`` is ``auto2`` when 「自己動手」 item 2 starts it): the plan is
        checked again, then the new employees and the task card are made and the dispatch is ``running``. Refused (and nothing
        changed) with 400 for a plan the rules do not allow, 409 when it is not the proposal that was shown, when the dispatch
        is no longer waiting, or when an employee or tool is not what it was."""
        if by not in ("you", "auto2"):
            raise _bad("開始的人不符")
        edited = {}

        def start(rec):
            if rec["state"] != "proposed":
                raise DispatchError("not_proposed")
            plan = checked_plan(body, rec)
            self._check_world(rec, plan)
            edited["value"] = plan != rec["proposal_plan"]
            made = rec["made"]
            by_ref = {c["ref"]: c for c in plan["new_cards"]}
            rec["plan"], rec["state"], rec["started_by"] = plan, "confirming", by
            rec["steps"] = [{"seq": n, "who": s["who"], "name": (by_ref[s["who"]]["name"] if s["who"] in by_ref else rec["cards"][s["who"]]["name"]),
                             "profile_id": made.get(s["who"]) if s["who"] in by_ref else rec["cards"][s["who"]]["profile_id"],
                             "chat_id": None, "text": s["text"], "state": "pending", "turn": None, "cost_usd": None, "ended_reason": None}
                            for n, s in enumerate(plan["steps"], 1)]
            self._event(rec, "confirmed", by, edited=edited["value"])
        self._mutate(dispatch_id, start)
        self._build(dispatch_id, by)
        return self.get(dispatch_id)

    def _check_world(self, rec: dict, plan: dict) -> None:
        """The cards and tools the plan relies on are still what the proposal saw (a conflict, never a guess)."""
        tools = tuple(self.tools())
        for who in sorted({s["who"] for s in plan["steps"]} & set(rec["cards"])):
            info = rec["cards"][who]
            try:
                profile = ap.get_profile_readonly(info["profile_id"])
            except ap.AgentProfileStorageError:
                raise DispatchError("storage", "角色資料無法讀取，請到角色頁處理") from None
            if profile is None or profile.get("enabled") is False:
                raise DispatchError("card_unavailable")
            if ap.profile_digest(profile) != info["revision"]:
                raise DispatchError("card_changed")
            if info["tool"] not in tools:
                raise DispatchError("tool_unavailable")
        withdrawn = _withdrawn(rec)
        for who in sorted({s["who"] for s in plan["steps"]} & set(rec["made"])):
            pid = rec["made"][who]               # an employee 「自己動手第 1 項」 made while the proposal waited (P40-6)
            if pid in withdrawn:
                raise DispatchError("card_withdrawn", f"新員工「{_name_of(rec, who)}」已經撤回（停用）了，計畫裡還有步驟要交給他。"
                                                      "請把那些步驟改交給別人或刪掉，再確認。")
            try:
                profile = ap.get_profile_readonly(pid)
            except ap.AgentProfileStorageError:
                raise DispatchError("storage", "角色資料無法讀取，請到角色頁處理") from None
            if profile is None or profile.get("enabled") is False:
                raise DispatchError("card_unavailable")
        for item in plan["new_cards"]:
            if item["ref"] not in rec["made"] and item["tool"] not in tools:
                raise DispatchError("tool_unavailable")

    def _make_cards(self, dispatch_id: str, by: str) -> None:
        for item in load(dispatch_id)["plan"]["new_cards"]:
            if item["ref"] in load(dispatch_id)["made"]:
                continue
            ref = item["ref"]
            self._mutate(dispatch_id, lambda rec, ref=ref: self._event(rec, "card_intent", by, ref=ref))
            try:
                saved = ap.save_profile(None, card_body(item))
            except Exception as exc:
                self._pause(dispatch_id, "create_failed")
                raise DispatchError("create_failed", f"建立員工「{item['name']}」沒有成功：{str(exc)[:150]}") from None

            def made(rec, ref=ref, pid=saved["id"]):
                rec["made"][ref] = pid
                self._event(rec, "card_created", by, ref=ref, profile_id=pid)
            self._mutate(dispatch_id, made)

    def _make_task(self, dispatch_id: str, by: str) -> None:
        rec = load(dispatch_id)
        if rec["task_id"] is not None:
            return
        self._mutate(dispatch_id, lambda r: self._event(r, "task_intent", by))
        plan = rec["plan"]
        try:
            saved = tasks.save_task(None, {"title": plan["title"], "goal": plan["goal"], "deliverables": list(plan["deliverables"])})
        except Exception as exc:
            self._pause(dispatch_id, "create_failed")
            raise DispatchError("create_failed", f"建立任務卡沒有成功：{str(exc)[:150]}") from None

        def made(r):
            r["task_id"] = saved["id"]
            self._event(r, "task_created", by, task_id=saved["id"])
        self._mutate(dispatch_id, made)

    def _build(self, dispatch_id: str, by: str) -> None:
        self._make_cards(dispatch_id, by)
        self._make_task(dispatch_id, by)
        self._finish(dispatch_id)

    def _finish(self, dispatch_id: str) -> None:
        """Everything is made: the steps name their employees and the dispatch is running (its steps are the runner's)."""
        def change(rec):
            for step in rec["steps"]:
                if step["profile_id"] is None:
                    step["profile_id"] = rec["made"][step["who"]]
            rec["state"] = "running"
        self._mutate(dispatch_id, change)

    # -- the rest of what a person does ----------------------------------------------------------------------------

    def dismiss(self, dispatch_id: str) -> dict:
        def change(rec):
            if rec["state"] != "proposed":
                raise DispatchError("not_proposed")
            rec["state"] = "dismissed"
            self._event(rec, "dismissed", "you")
        self._mutate(dispatch_id, change)
        return self.get(dispatch_id)

    def stop(self, dispatch_id: str) -> dict:
        """「停止」: nothing more is sent, and a turn that is running is stopped (carried out by the runner)."""
        load(dispatch_id)
        if self.control is None:
            raise DispatchError("no_runner")
        return self.control.stop_dispatch(dispatch_id)

    def resume(self, dispatch_id: str) -> dict:
        """「繼續」: a paused dispatch goes on (carried out by the runner); never by itself."""
        load(dispatch_id)
        if self.control is None:
            raise DispatchError("no_runner")
        return self.control.resume_dispatch(dispatch_id)

    def withdraw_card(self, dispatch_id: str, body) -> dict:
        """Switch off an employee VBear made for this dispatch (never deleted: the chats stay). Refused while a turn of that
        employee's is running."""
        if not isinstance(body, dict) or set(body) != {"profile_id"} or not _profile_id_ok(body["profile_id"]):
            raise _bad("只需要 profile_id")
        pid = body["profile_id"]
        rec = load(dispatch_id)
        if pid not in rec["made"].values():
            raise _bad("這不是這份派工建的員工")
        if pid in _withdrawn(rec):
            raise DispatchError("already_withdrawn")
        for step in rec["steps"]:
            if step["profile_id"] == pid and (step["state"] in ("sending", "running") or (step["chat_id"] and self._busy(step["chat_id"]))):
                raise DispatchError("turn_running")
        try:
            profile = ap.get_profile_readonly(pid)
        except ap.AgentProfileStorageError:
            raise DispatchError("storage", "角色資料無法讀取，請到角色頁處理") from None
        if profile is None:
            raise DispatchError("not_found", "找不到這位員工（可能已經被刪除）")
        try:
            ap.save_profile(pid, {"enabled": False})
        except Exception as exc:
            raise DispatchError("storage", f"撤回沒有成功：{str(exc)[:150]}") from None
        self._mutate(dispatch_id, lambda r: self._event(r, "card_withdrawn", "you", profile_id=pid))
        return self.get(dispatch_id)

    def _busy(self, chat_id: str) -> bool:
        try:
            return bool(self.busy(chat_id))
        except Exception:
            return True                      # a turn that cannot be ruled out is a turn

    def delete(self, dispatch_id: str) -> None:
        """Remove the dispatch and the proposal it came from. The employees, the task card and the chats are the person's and stay."""
        rec = load(dispatch_id)
        if not can_delete(rec):
            raise DispatchError("not_deletable")
        self._remove_file(dispatch_id)
        try:
            chief.delete(rec["chief_id"])
        except chief.ChiefError as exc:
            if exc.code != "not_found":
                raise DispatchError("storage", str(exc)) from None

    @staticmethod
    def _remove_file(dispatch_id: str) -> None:
        store = DispatchStore(dispatch_id)
        try:
            with store.locked():
                if store.path().exists():
                    store.path().unlink()
        except StoreError as exc:
            raise DispatchError("storage", str(exc)) from None

    # -- after a restart ---------------------------------------------------------------------------------------------

    def recover_all(self) -> list[str]:
        """Dispatches a stopped console left in the middle of making what they need: with an intent that has no result, the
        dispatch is paused as ``uncertain`` (the person looks at the employees and the task cards, then decides); one that
        was only between two writes as ``interrupted``. Nothing is made again, nothing is sent. Returns the dispatches paused."""
        paused = []
        for did in record_ids():
            try:
                rec = load(did)
            except DispatchError:
                continue
            open_intent = any(
                (e["kind"] == "card_intent" and not any(r["kind"] == "card_created" and r["ref"] == e["ref"] for r in rec["events"]))
                or (e["kind"] == "task_intent" and not any(r["kind"] == "task_created" for r in rec["events"]))
                for e in rec["events"])
            if rec["state"] == "confirming" or (rec["state"] == "proposed" and open_intent):
                self._pause(did, "uncertain" if open_intent else "interrupted")
                paused.append(did)
        return paused

    # -- 「AI 自己做了什麼」 -------------------------------------------------------------------------------------------

    def actions(self, limit: int = 200) -> dict:
        """Every event of every dispatch, the newest first, at most ``limit``: {at, dispatch_id, seq, kind, what, by, by_text,
        profile_id (of a card that was made or withdrawn, else None), can_stop, can_withdraw}. ``unreadable`` counts the dispatches that could not be read (they are not guessed at)."""
        rows, unreadable = [], 0
        daily = mt.limits_from(self.conf())["daily_usd"]
        for did in record_ids():
            try:
                rec = load(did)
            except DispatchError:
                unreadable += 1
                continue
            withdrawn = _withdrawn(rec)
            live = rec["state"] in ("running", "paused")
            for ev in rec["events"]:
                rows.append({"at": ev["at"], "dispatch_id": did, "seq": ev["seq"], "kind": ev["kind"], "what": describe(rec, ev, daily),
                             "by": ev["by"], "by_text": by_text_of(ev), "profile_id": ev.get("profile_id"),
                             "can_stop": live and ev["kind"] in ("confirmed", "step_sent"),
                             "can_withdraw": ev["kind"] == "card_created" and ev["profile_id"] not in withdrawn})
        rows.sort(key=lambda r: (r["at"], r["seq"]), reverse=True)
        return {"actions": rows[:limit], "unreadable": unreadable}
