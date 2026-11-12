#!/usr/bin/env python3
"""P54: screenshots of VBear's pages made from made-up data, so that a person (or the coordinator) can look at what the pages really draw.

A developer tool, never part of the product, **standard library only** (and the sibling ``qa_p47.py``, whose ``Browser`` and ``Page`` are reused as they
are: one headless Chrome driven over ``--remote-debugging-pipe``, **no TCP debugging port**). It does two things.

1. It starts a **stub console**: a small HTTP server bound to ``127.0.0.1`` only, on the port of ``--port`` (default 7811; **7788, 7789 and 7795 to 7803
   are refused** before anything starts: the first two are the person's own VBear, the others are the ports of the real checks). It serves the files of
   ``web/`` and answers every ``GET /api/...`` the pages read with a fixed, invented JSON (names such as 「虛構 CEO」; no real name, path, account or
   address). It does not import the ``vbear`` server, reads no state folder, runs no outside program and sends nothing anywhere. **Every POST, PUT, PATCH
   and DELETE is answered 409 and its path is recorded**: taking screenshots must not write anything, and the result file lists what was tried (it should be
   an empty list; a page that wrote while being photographed is a finding).
2. It opens the stub in Chrome and, for each scene (a page, in a state), takes the screenshots of the sizes below into ``--out``:
   1280x800 light, 1280x800 dark and 400x800 light (dark is ``document.documentElement.dataset.theme = "dark"``). A scene is the data of the stub (its
   ``world``), an address, and the presses the person would make (a list of steps: click, fill, a script, wait). ``--list`` prints the scenes.

Which folders. ``--tmp`` must be a folder you made for this run (``mktemp -d /tmp/v54.XXXX``): Chrome's own profile goes to ``<tmp>/chrome``; it must not be
under a dot folder of the person's home. ``--out`` is where the PNG files and ``shots-stub-result.json`` go. The result file has the file names, the steps
that found nothing to press, the console errors the page wrote, and the writes the page tried; never a token or a conversation (all the data is invented).

    T=$(mktemp -d /tmp/v54.XXXX) && python3 tools/shots_stub.py --tmp "$T" --out "$T/shots" --chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    python3 tools/shots_stub.py --list
    python3 tools/shots_stub.py --tmp "$T" --out "$T/shots" --only home-fresh,chat-rich

Exit code 0 only when every scene was photographed, every step found what it pressed and **no write was tried**. The tests (tests/test_shots_stub.py)
start no browser and no server: they test the pure parts (the refused ports, the 409 for every write, that the invented data holds nothing real, the scenes).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DEFAULT_PORT = 7811
RESERVED_PORTS = (7788, 7789, *range(7795, 7804))          # the person's own VBear (7788, 7789) and the ports of the real checks (7795 to 7803)
CHROME_DEFAULT = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
SIZES = (("desktop-light", 1280, 800, "light"), ("desktop-dark", 1280, 800, "dark"), ("phone-light", 400, 800, "light"))
PRIVATE_DOT_FOLDERS = (".vbear", ".claude", ".codex", ".gemini", ".ssh", ".config", ".agents")
RUN_FOLDERS_ALLOWED = ".codex/projects/sid-console/runs/"   # the one place of a dot folder where the pictures may go


def port_refusal(port) -> str | None:
    """Why this port may not be used (None when it may)."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        return f"port {port!r} is not a port number from 1024 to 65535"
    if port in RESERVED_PORTS:
        return f"port {port} is reserved (the person's own VBear is on 7788 and 7789; 7795 to 7803 are the ports of the real checks)"
    return None


def path_refusal(path, *, output: bool = False, home: Path | None = None) -> str | None:
    """Why this folder may not be used: nothing under a dot folder of the person's home (``output=True`` allows the runs folder of the coordinator)."""
    home = (home if home is not None else Path.home()).resolve()
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return f"{path} cannot be resolved"
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return None
    parts = relative.parts
    if parts and parts[0] in PRIVATE_DOT_FOLDERS:
        if output and relative.as_posix().startswith(RUN_FOLDERS_ALLOWED):
            return None
        return f"{resolved} is inside {home / parts[0]}, which this tool never touches"
    return None


# ---- the invented data -------------------------------------------------------------------------------------------------------------------

def _h(n: int, width: int) -> str:
    return f"{n:0{width}x}"


def prof_id(n: int) -> str:
    return "prof-" + _h(n, 12)


def chat_id(n: int) -> str:
    return "c-" + _h(n, 16)


def card_id(n: int) -> str:
    return "k-" + _h(n, 16)


CEO, ENG, WRITER, REVIEW = prof_id(0xA1), prof_id(0xA2), prof_id(0xA3), prof_id(0xA4)
NAME = {CEO: "虛構 CEO", ENG: "虛構工程師", WRITER: "虛構寫手", REVIEW: "虛構審查"}
POSITION = {CEO: "planner", ENG: "executor", WRITER: "executor", REVIEW: "reviewer"}
TOOL = {CEO: "claude", ENG: "claude", WRITER: "codex", REVIEW: "agy"}


def profile(pid: str, enabled: bool = True) -> dict:
    return {"id": pid, "name": NAME[pid], "position": POSITION[pid], "model": {"tool": TOOL[pid], "model_id": ""}, "enabled": enabled, "launch_mode": "safe"}


def card(pid: str, can_chat: bool = True, reason: str | None = None, code: str | None = None, enabled: bool = True) -> dict:
    return {"id": pid, "name": NAME[pid], "position": POSITION[pid], "tool": TOOL[pid], "engine": TOOL[pid] + "-chat", "enabled": enabled, "can_chat": can_chat, "code": code,
            "reason": reason, "instructions": pid == CEO}


def chat_row(cid: str, pid: str, now: float, ago: float, text: str, turns: int = 2, waiting: bool = False, spent: str = "0.04") -> dict:
    return {"id": cid, "profile_id": pid, "engine": TOOL[pid] + "-chat", "created_at": now - ago - 600, "last_at": now - ago, "last_kind": "reply", "last_text": text, "turns": turns,
            "spent_usd": spent, "open": waiting, "waiting": waiting, "problem": None}


def support(state: str = "verified", detected: str = "2.1.300", message: str = "") -> dict:
    return {"engine": "claude-chat", "detected": detected, "verified": [detected] if state == "verified" else [], "state": state, "message": message, "policy": {"ok": True, "found": [], "problems": [], "reason": ""},
            "verify": {"running": False}, "money": "按下去會用你自己的方案做一次很短的對話，最多花 US$0.05。",
            "codex": {"engine": "codex-chat", "state": "ready", "installed": True, "version": "0.9.1", "verified": True, "logged_in": True, "admin_policy_ok": True, "why": "", "verify": {"running": False}, "money": "用你自己的方案做一次很短的對話。"},
            "agy": {"engine": "agy-chat", "state": "unverified", "installed": True, "version": "3.0.2", "verified": False, "admin_policy_ok": True, "why": "", "verify": {"running": False}, "money": "用你自己的方案做一次很短的對話。"}}


def tool_row(tid: str, name: str, **over) -> dict:
    byStatus = tid in ("claude", "codex")
    row = {"id": tid, "name": name, "short": name, "blurb": f"{name} 是虛構的說明：要有它的付費方案才能用。", "hidden": False, "installed": False, "version": None, "install_problem": "not_found",
           "login_by": "status" if byStatus else "mark", "login": "unknown" if byStatus else "not_marked", "can_mark": not byStatus, "marked_at": None, "state": "not_installed", "ready": False,
           "login_regions": []}
    if tid == "codex":
        row["chat_login"] = {"state": "not_logged_in", "problem": ""}
    row.update(over)
    return row


def tool_ready(tid: str, name: str, version: str) -> dict:
    byStatus = tid in ("claude", "codex")
    over = {"installed": True, "version": version, "install_problem": "", "state": "ready", "ready": True, "login": "logged_in" if byStatus else "marked", "marked_at": 1.5}
    if tid == "codex":
        over["chat_login"] = {"state": "logged_in", "problem": ""}
    return tool_row(tid, name, **over)


def tool_installed(tid: str, name: str, version: str) -> dict:
    byStatus = tid in ("claude", "codex")
    return tool_row(tid, name, installed=True, version=version, install_problem="", state="not_logged_in", login="not_logged_in" if byStatus else "not_marked")


class Seq:
    """The records of one invented chat: a counter and the time they happened."""

    def __init__(self, now: float, start_ago: float = 900.0):
        self.n = 0
        self.t = now - start_ago
        self.records: list[dict] = []

    def add(self, kind: str, **data) -> dict:
        self.n += 1
        self.t += 7
        rec = {"seq": self.n, "at": self.t, "kind": kind, **data}
        self.records.append(rec)
        return rec


def permission_card(n: int = 1, command: str = "rm -rf ./虛構的暫存資料夾") -> dict:
    return {"card_id": card_id(n), "token": "t" * 32, "turn": 2, "tool": "Bash", "input": {"command": command, "description": "把虛構的暫存資料夾刪掉"}, "editable": "command",
            "reason": "每個指令都要你允許才會執行", "expires_in": 280}


def rich_records(now: float) -> list[dict]:
    s = Seq(now)
    s.add("user_message", turn=1, text="幫我整理這週的待辦，順便把虛構專案裡過期的暫存檔清掉。")
    s.add("process_started", mode="new", budget_usd="0.5", instructions=True)
    s.add("tool_call", turn=1, tool_use_id="t1", tool="Read", summary="待辦.md")
    s.add("tool_result", turn=1, tool_use_id="t1", tool="Read", is_error=False, text="12 行", truncated=False)
    s.add("tool_call", turn=1, tool_use_id="t2", tool="Read", summary="本週行事曆.md")
    s.add("tool_result", turn=1, tool_use_id="t2", tool="Read", is_error=False, text="9 行", truncated=False)
    s.add("auto_allowed", turn=1, tool_use_id="t3", tool="Read", summary="虛構專案/README.md", reason="folder")
    s.add("reply", turn=1, text="我看完了。這週有 5 件事，其中 2 件和暫存檔有關。\n\n1. 週三前交虛構報告\n2. 清掉虛構專案裡過期的暫存檔\n3. 回覆三封信\n\n要我先清暫存檔嗎？", truncated=False)
    s.add("turn_ended", turn=1, cost_usd="0.0123", reported=True, total_usd=0.0123, reason="result", subtype="success", is_error=False)
    s.add("user_message", turn=2, text="好，先清暫存檔，再把清單整理成一張表。")
    s.add("tool_call", turn=2, tool_use_id="t4", tool="Bash", summary="ls ./虛構專案/tmp")
    s.add("tool_result", turn=2, tool_use_id="t4", tool="Bash", is_error=False, text="a.tmp b.tmp", truncated=False)
    s.add("tool_call", turn=2, tool_use_id="t5", tool="Bash", summary="rm ./虛構專案/tmp/a.tmp")
    s.add("denied", turn=2, tool_use_id="t5", tool="Bash", summary="rm ./虛構專案/tmp/a.tmp", reason="outside", by="vbear")
    s.add("error", turn=2, message="這個指令不在你允許的資料夾裡，所以沒有執行。")
    s.add("tool_call", turn=2, tool_use_id="t6", tool="Read", summary="虛構專案/tmp")
    s.add("tool_result", turn=2, tool_use_id="t6", tool="Read", is_error=True, text="找不到", truncated=False)
    s.add("reply", turn=2, text="有一個指令被擋下來了，因為它不在允許的資料夾裡。我換一個做法，需要你決定。", truncated=False)
    s.add("card", turn=2, card_id=card_id(1), tool="Bash", input={"command": "rm -rf ./虛構的暫存資料夾"}, editable="command", state="asked", reason="")
    s.add("turn_ended", turn=2, cost_usd="0.0210", reported=True, total_usd=0.0333, reason="result", subtype="success", is_error=False)
    return s.records


def decided_records(now: float) -> list[dict]:
    s = Seq(now)
    s.add("user_message", turn=1, text="幫我把虛構專案的暫存檔清掉。")
    s.add("tool_call", turn=1, tool_use_id="t1", tool="Bash", summary="ls")
    s.add("tool_result", turn=1, tool_use_id="t1", tool="Bash", is_error=False, text="a.tmp", truncated=False)
    s.add("card", turn=1, card_id=card_id(2), tool="Bash", input={"command": "rm a.tmp"}, editable="command", state="asked", reason="")
    s.add("card_decision", turn=1, card_id=card_id(2), decision="allow", value=None)
    s.add("tool_call", turn=1, tool_use_id="t2", tool="Bash", summary="rm a.tmp")
    s.add("tool_result", turn=1, tool_use_id="t2", tool="Bash", is_error=False, text="", truncated=False)
    s.add("reply", turn=1, text="清好了，剩下的檔案都還在。", truncated=False)
    s.add("turn_ended", turn=1, cost_usd="0.0150", reported=True, total_usd=0.015, reason="result", subtype="success", is_error=False)
    return s.records


def working_records(now: float) -> list[dict]:
    s = Seq(now, 120)
    s.add("user_message", turn=1, text="請幫我把這週的待辦寫成一封給主管的簡短週報。")
    s.add("process_started", mode="new", budget_usd="0.5", instructions=True)
    s.add("tool_call", turn=1, tool_use_id="t1", tool="Read", summary="待辦.md")
    s.add("tool_result", turn=1, tool_use_id="t1", tool="Read", is_error=False, text="12 行", truncated=False)
    return s.records


def pair(now: float) -> list[dict]:
    s = Seq(now, 400)
    s.add("user_message", turn=1, text="你好")
    s.add("reply", turn=1, text="你好，我是虛構 CEO。有什麼我可以幫你的？", truncated=False)
    s.add("turn_ended", turn=1, cost_usd="0.0040", reported=True, total_usd=0.004, reason="result", subtype="success", is_error=False)
    return s.records


@dataclass
class World:
    """What the stub console answers in one scene. Everything is invented."""

    name: str
    profiles: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    chats: list = field(default_factory=list)
    support: dict = field(default_factory=support)
    ledger: dict = field(default_factory=lambda: {"lamp": "green", "spent_usd": "0.31", "daily_usd": "3", "includes": ["chats"]})
    waiting: list = field(default_factory=list)
    routines: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    details: dict = field(default_factory=dict)          # chat id -> {"records": [...], "live": {...}}
    config: dict = field(default_factory=dict)
    plan_tool: str = "claude"
    templates: dict = field(default_factory=dict)
    verified_chat: bool = True


def _world_common() -> list:
    return [profile(CEO), profile(ENG), profile(WRITER)]


def build_world(name: str, now: float) -> World:
    """The world of one scene (a name of ``WORLDS``)."""
    if name not in WORLDS:
        raise KeyError(name)
    w = World(name=name)
    w.tools = [tool_ready("claude", "Claude Code", "2.1.300"), tool_row("codex", "Codex CLI"), tool_row("agy", "Antigravity（AGY）"), tool_row("grok", "Grok")]
    w.config = {"advanced_mode": False, "setup_done": True, "first_ceo_id": "", "onboarding_dismissed": True, "setup_notice": False}
    if name in ("first-empty", "first-ready", "first-unknown"):
        w.profiles, w.cards, w.chats = [], [], []
        if name == "first-empty":
            w.tools = [tool_row("claude", "Claude Code"), tool_installed("codex", "Codex CLI", "0.9.1"), tool_row("agy", "Antigravity（AGY）"), tool_row("grok", "Grok")]
            w.support = support("unverified", "0.9.1", "Codex CLI 0.9.1 還沒通過聊天驗證。")
        elif name == "first-ready":
            w.tools = [tool_ready("claude", "Claude Code", "2.1.300"), tool_ready("codex", "Codex CLI", "0.9.1"), tool_row("agy", "Antigravity（AGY）"), tool_row("grok", "Grok")]
            w.support = support("verified", "2.1.300")
        else:
            w.tools = [tool_ready("claude", "Claude Code", "2.1.999"), tool_row("codex", "Codex CLI"), tool_row("agy", "Antigravity（AGY）"), tool_row("grok", "Grok")]
            w.support = support("unsupported", "2.1.999", "VBear 還不認得 Claude Code 2.1.999，所以先不能用它聊天。")
        return w
    w.profiles = _world_common()
    w.cards = [card(CEO), card(ENG), card(WRITER)]
    w.support = support()
    if name == "home-fresh":
        w.chats = []
    elif name in ("home-busy", "home-who", "chat-list"):
        w.chats = [chat_row(chat_id(1), CEO, now, 300, "我整理好了，有一件事要你決定。", turns=3, waiting=True),
                   chat_row(chat_id(2), ENG, now, 3600 * 3, "測試都過了。", turns=4),
                   chat_row(chat_id(3), WRITER, now, 3600 * 26, "貼文草稿已經放在上面。", turns=2),
                   chat_row(chat_id(4), CEO, now, 3600 * 70, "好的，下週見。", turns=6)]
        if name != "chat-list":
            w.chats = w.chats + []
        else:
            w.chats = w.chats[:3]
        if name == "home-busy":
            w.waiting = [{"kind": "routine_due", "name": "晨間整理", "run_id": "run-1", "slot": "2026-11-10T08:00"}]
    if name == "home-who":
        w.cards = [card(CEO), card(ENG), card(WRITER), card(REVIEW, can_chat=False, code="card_disabled", reason="這張角色卡已停用，啟用之後才能聊天。", enabled=False)]
        w.profiles = _world_common() + [profile(REVIEW, enabled=False)]
        w.chats = [chat_row(chat_id(1), CEO, now, 3600, "你好，我是虛構 CEO。", turns=1)]
    if name in ("chat-rich", "chat-decided", "chat-working", "chat-first", "chat-limit"):
        w.chats = [chat_row(chat_id(1), CEO, now, 60, "…", turns=2)]
        w.cards = [card(CEO), card(ENG), card(WRITER), card(REVIEW, can_chat=False, code="card_disabled", reason="這張角色卡已停用，啟用之後才能聊天。", enabled=False)]
        w.profiles = _world_common() + [profile(REVIEW, enabled=False)]
        cid = chat_id(1)
        if name == "chat-rich":
            w.details[cid] = {"records": rich_records(now), "live": {"state": "waiting_for_you", "turn": 2, "partial": "", "partial_truncated": False, "model": "haiku", "cards": [permission_card()]}}
            w.chats[0]["waiting"] = True
        elif name == "chat-decided":
            w.details[cid] = {"records": decided_records(now), "live": {"state": "idle", "turn": None, "partial": "", "partial_truncated": False, "model": "haiku", "cards": []}}
        elif name == "chat-working":
            w.details[cid] = {"records": working_records(now), "live": {"state": "working", "turn": 1, "partial": "好的，我先把這週的待辦分成三組：必須這週做完的、可以延到下週的，還有", "partial_truncated": False,
                                                                           "model": "haiku", "cards": []}}
        elif name == "chat-first":
            w.chats = []
            w.details[cid] = {"records": [], "live": {"state": "idle", "turn": None, "partial": "", "partial_truncated": False, "model": "haiku", "cards": []}}
            w.chats = [chat_row(cid, CEO, now, 10, "", turns=0)]
        elif name == "chat-limit":
            w.details[cid] = {"records": pair(now), "live": {"state": "idle", "turn": None, "partial": "", "partial_truncated": False, "model": "haiku", "cards": []}}
            w.ledger = {"lamp": "red", "spent_usd": "3.02", "daily_usd": "3", "includes": ["chats"]}
    if name in ("held-policy", "held-unknown"):         # P57: the CEO uses Claude Code, which this made-up computer holds back; Codex can chat, AGY needs its safety check
        w.chats = [chat_row(chat_id(1), CEO, now, 3600, "你好，我是虛構 CEO。", turns=1)]
        w.support = support("policy", "2.1.318", "這台 Mac 上有管理員政策或系統設定，可能蓋過 VBear 的設定，所以不啟動聊天。") if name == "held-policy" \
            else support("unsupported", "2.1.999", "VBear 還不認得 Claude Code 2.1.999，所以先不能用它聊天。")
    if name == "settings":
        w.chats = [chat_row(chat_id(1), CEO, now, 300, "好", turns=1)]
    if name == "templates":
        w.chats = [chat_row(chat_id(1), CEO, now, 300, "好", turns=1)]
        w.templates = {"ok": True, "builtin": [], "mine": [], "mine_readable": True, "problems": [], "applies": [], "counts": {"cards": 3, "skills": 1, "routines": 1},
                       "current": {"cards": [{"id": CEO, "name": NAME[CEO], "position": "planner", "tool": "claude", "can_chat": True},
                                             {"id": ENG, "name": NAME[ENG], "position": "executor", "tool": "claude", "can_chat": True},
                                             {"id": WRITER, "name": NAME[WRITER], "position": None, "tool": "codex", "can_chat": True}],
                                   "skills": [{"id": "k-aaaaaaaaaaaa", "name": "每日小結"}], "routines": [{"id": "r-aaaaaaaaaaaa", "name": "收工整理"}]},
                       "limits": {"max_mine": 20, "max_name": 40, "per_template": {"cards": 12, "skills": 24, "routines": 12}, "per_apply": {"cards": 12, "skills": 24, "routines": 12}},
                       "tools": {"claude": {"ready": True, "why": ""}, "codex": {"ready": True, "why": ""}, "default": "claude"}}
    return w


WORLDS = ("first-empty", "first-ready", "first-unknown", "home-fresh", "home-busy", "home-who", "chat-rich", "chat-decided", "chat-working", "chat-first", "chat-limit", "chat-list", "settings", "templates", "held-policy", "held-unknown")


def first_ceo_plan(tool: str) -> dict:
    names = {"claude": "Claude Code", "codex": "Codex CLI", "agy": "Antigravity（AGY）", "grok": "Grok"}
    return {"ok": True, "needed": True, "can_create": True, "go": None, "reason": "", "tool": tool, "tool_name": names.get(tool, tool), "name": "CEO", "position": "planner", "launch_mode": "safe",
            "instructions": "你是我的 CEO（執行長）。請用一般人聽得懂的話跟我說話。", "opening": "你好，請先問我三個問題，了解我想做什麼。", "chat_ready": None, "chat_note": ""}


class Fake:
    """The answers of the stub console for one world. Pure: nothing is read or written here; ``writes`` records the paths of the requests that were refused."""

    def __init__(self, world: World, now: float):
        self.w, self.now = world, now
        self.writes: list[str] = []

    def chats(self) -> dict:
        w = self.w
        return {"ok": True, "chats": w.chats, "more": 0, "cards": w.cards, "support": w.support, "limits": {"per_turn_usd": "0.5", "daily_usd": "3"}, "ledger": w.ledger, "ledger_error": None,
                "problems": [], "scratch": ""}

    def detail(self, cid: str, after: int) -> tuple[int, dict]:
        w = self.w
        row = next((c for c in w.chats if c["id"] == cid), None)
        data = w.details.get(cid)
        if row is None or data is None:
            return 404, {"error": "找不到這段對話"}
        records = [r for r in data["records"] if r["seq"] > after]
        last = data["records"][-1]["seq"] if data["records"] else 0
        owner = next((c for c in w.cards if c["id"] == row["profile_id"]), w.cards[0])
        return 200, {"ok": True, "chat": {"id": cid, "profile_id": row["profile_id"], "created_at": row["created_at"], "engine": row["engine"]}, "card": owner, "records": records,
                     "live": data["live"], "runtime": {"available": True, "message": ""}, "next_after": last, "last_seq": last, "more": False, "problem": None}

    def answer(self, method: str, target: str) -> tuple[int, dict]:
        """(status, JSON) for one request. A write is refused with 409 and its path is recorded."""
        parts = urlsplit(target)
        path, query = parts.path, parse_qs(parts.query)
        if method.upper() in WRITE_METHODS:
            self.writes.append(f"{method.upper()} {path}")
            return 409, {"error": "這是截圖用的假主控台，不接受任何寫入。", "code": "stub_read_only"}
        w = self.w
        if path == "/api/config":
            return 200, {"config": dict(w.config), "state_dir": "(stub)", "runtime_socket": ""}
        if path == "/api/agent-profiles":
            return 200, {"ok": True, "profiles": w.profiles}
        if path == "/api/agent-builder/catalog":
            return 200, {"ok": True, "tool_list": [], "skills": []}
        if path == "/api/chats":
            return 200, self.chats()
        m = re.fullmatch(r"/api/chats/(c-[0-9a-f]{16})", path)
        if m:
            try:
                after = int((query.get("after") or ["0"])[0])
            except ValueError:
                after = 0
            return self.detail(m.group(1), after)
        if re.fullmatch(r"/api/chats/c-[0-9a-f]{16}/stream", path):
            return 404, {"error": "no stream in the stub"}
        if path == "/api/meetings/ledger":
            return 200, w.ledger
        if path == "/api/routines":
            return 200, {"routines": w.routines, "readable": True, "cards": w.cards, "waiting": [r for r in w.waiting if r["kind"] in ("routine_due", "routine_missed")], "settings": {}, "limits": {},
                         "today": {}, "autonomy": {}}
        if path == "/api/waiting":
            return 200, {"waiting": w.waiting}
        if path in ("/api/flows",):
            return 200, {"ok": True, "flows": []}
        if path == "/api/meetings":
            return 200, {"meetings": []}
        if path == "/api/staffing":
            return 200, {"staffing": []}
        if path == "/api/dispatch":
            return 200, {"dispatch": []}
        if path == "/api/groups":
            return 200, {"groups": []}
        if path == "/api/live":
            return 200, {"runtime": {"available": True, "problems": []}, "sessions": [], "attention": [], "projects": [], "panes": [], "usage": {"sessions": []}}
        if path == "/api/tasks":
            return 200, {"ok": True, "tasks": []}
        if path == "/api/setup/tools":
            return 200, {"ok": True, "any_ready": any(t.get("ready") for t in w.tools), "setup_done": True, "tools": w.tools}
        if path == "/api/first-ceo":
            tool = (query.get("tool") or [w.plan_tool])[0]
            return 200, first_ceo_plan(tool)
        if path == "/api/setup/daily-limit":
            return 200, {"ok": True, "daily_usd": 3, "choices": [1, 3, 10]}
        if path == "/api/overview":
            return 200, {"ok": True, "totals": {"active": 0}, "generated_at": self.now, "stale": False, "skills_with_problems": [], "sources": [], "facts": {}, "problems": []}
        if path == "/api/skills":
            return 200, {"skills": [], "categories": []}
        if path == "/api/roles":
            return 200, {"roles": []}
        if path == "/api/translations":
            return 200, {"entries": {}, "counts": {}, "jobs": []}
        if path == "/api/role-translations":
            return 200, {"entries": {}, "counts": {}, "jobs": []}
        if path == "/api/settings/autonomy":
            return 200, {"autonomy": {}, "items": [], "never": []}
        if path == "/api/templates":
            return 200, w.templates or {"ok": True, "builtin": [], "mine": [], "mine_readable": True, "problems": [], "applies": [], "counts": {}, "current": {}}
        if path == "/api/memory":
            return 200, {"ok": True, "items": [], "limits": {}}
        return 200, {}


# ---- the stub console (HTTP) -------------------------------------------------------------------------------------------------------------

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".json": "application/json", ".ico": "image/x-icon", ".woff2": "font/woff2", ".map": "application/json"}


def static_path(request_path: str, web: Path = WEB) -> Path | None:
    """The file of ``web/`` that an address names (None for anything outside it or that is not a file)."""
    path = urlsplit(request_path).path
    if path in ("", "/"):
        path = "/index.html"
    if ".." in path.split("/") or "\\" in path or "\0" in path:
        return None
    target = (web / path.lstrip("/")).resolve()
    try:
        target.relative_to(web.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


class Stub:
    """The server and what it answers now (``scene`` is switched by the runner between pages)."""

    def __init__(self, port: int):
        refusal = port_refusal(port)
        if refusal:
            raise ValueError(refusal)
        self.port = port
        self.fake = Fake(build_world("home-fresh", time.time()), time.time())
        self.all_writes: list[str] = []
        self.lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):          # no line per request
                return

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _api(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(min(length, 1 << 20))
                with stub.lock:
                    status, data = stub.fake.answer(self.command, self.path)
                self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

            def do_GET(self):
                if urlsplit(self.path).path.startswith("/api/"):
                    self._api()
                    return
                found = static_path(self.path)
                if found is None:
                    self._send(404, b"not found", "text/plain")
                    return
                self._send(200, found.read_bytes(), CONTENT_TYPES.get(found.suffix, "application/octet-stream"))

            do_POST = do_PUT = do_PATCH = do_DELETE = _api

        ThreadingHTTPServer.request_queue_size = 128           # a page asks for twenty things at once; the default queue of 5 refuses some
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def use(self, world: str) -> None:
        with self.lock:
            self.all_writes.extend(self.fake.writes)
            self.fake = Fake(build_world(world, time.time()), time.time())

    def writes(self) -> list[str]:
        with self.lock:
            return list(self.all_writes) + list(self.fake.writes)


# ---- the scenes ----------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Scene:
    slug: str
    title: str
    world: str
    hash: str
    steps: tuple = ()
    sizes: tuple = tuple(s[0] for s in SIZES)


BOTTOM = ("js", "window.scrollTo(0, document.documentElement.scrollHeight)")
OPEN_WHO = ("click", '[data-ask="who"]')
SCENES: tuple[Scene, ...] = (
    Scene("home-fresh", "首頁：有可以聊的 CEO、沒聊過", "home-fresh", "#/"),
    Scene("home-busy-closed", "首頁：聊過、2 件事等你決定（藥丸收起）、左欄最近 4 列", "home-busy", "#/"),
    Scene("home-busy-open", "首頁：同上，藥丸展開", "home-busy", "#/", (("click", ".home-pill"),)),
    Scene("home-who", "首頁：換員工清單打開", "home-who", "#/", (OPEN_WHO,)),
    Scene("chat-rich", "聊天頁：一段像樣的對話，摺疊收起，最後一張要你決定的卡", "chat-rich", "#/chat/" + chat_id(1), (BOTTOM,)),
    Scene("chat-rich-open", "聊天頁：同上，摺疊展開", "chat-rich", "#/chat/" + chat_id(1), (("js", "document.querySelectorAll('[data-chat=\"quiet-group\"]').forEach((d) => { d.open = true; })"),
                                                                                  ("js", "document.querySelectorAll('[data-chat=\"quiet-group\"]')[1].scrollIntoView({ block: 'center' })"))),
    Scene("chat-rich-top", "聊天頁：同上，頁首與最前面幾則", "chat-rich", "#/chat/" + chat_id(1)),
    Scene("chat-who", "聊天頁：換員工清單打開", "chat-rich", "#/chat/" + chat_id(1), (BOTTOM, OPEN_WHO)),
    Scene("chat-decided", "聊天頁：已決定的卡與完成的對話", "chat-decided", "#/chat/" + chat_id(1), (BOTTOM,)),
    Scene("chat-working", "聊天頁：員工正在寫與停止這一回合", "chat-working", "#/chat/" + chat_id(1), (BOTTOM,)),
    Scene("chat-first", "聊天頁：CEO 第一次對話的兩個開場選項", "chat-first", "#/chat/" + chat_id(1)),
    Scene("chat-limit", "聊天頁：碰到每天上限（今天的用量已到上限；員工的回覆照舊，頁面畫出伺服器拒絕送出時的那段說明）", "chat-limit", "#/chat/" + chat_id(1),
          (("js", "setKids(document.querySelector('[data-chat=\"limit-box\"]'), limitReachedNotice(null))"), BOTTOM)),
    Scene("chat-list", "對話紀錄清單頁：3 段對話，1 段有事等你", "chat-list", "#/chat"),
    Scene("first-empty-pick", "沒有員工的首頁：選了 ChatGPT（Codex）後展開準備步驟", "first-empty", "#/", (("click", '[data-setup-pick-go="codex"]'),)),
    Scene("first-ready", "沒有員工的首頁：可以聊了，名字欄與建立 CEO", "first-ready", "#/", (("click", '[data-setup-pick-go="codex"]'),)),
    Scene("first-unknown", "沒有員工的首頁：版本還不認得", "first-unknown", "#/", (("click", '[data-setup-pick-go="claude"]'),)),
    Scene("held-home", "首頁：CEO 的 Claude Code 被管理員設定擋住，可以改用別家 AI（確認區關著）", "held-policy", "#/"),
    Scene("held-prep", "聊天準備頁：同上（管理員設定）", "held-policy", "#/chat?profile=" + CEO),
    Scene("held-confirm", "聊天準備頁：按了「改用 OpenAI ChatGPT（Codex）」，確認區打開（沒有按確認，所以什麼都沒送）", "held-policy", "#/chat?profile=" + CEO, (("click", '[data-switch="pick"]'),)),
    Scene("held-unknown", "聊天準備頁：Claude Code 版本還不認得，可以改用別家 AI", "held-unknown", "#/chat?profile=" + CEO),
    Scene("settings", "設定頁（用量與上限在通知上面）", "settings", "#/settings"),
    Scene("templates-save", "存成團隊範本的對話框", "templates", "#/templates", (("js", "document.querySelectorAll('[data-templates=\"now\"] input[type=checkbox]').forEach((b) => b.click())"),
                                                                                       ("click", '[data-tpl-action="save-now"]')), ("phone-light", "desktop-light")),
    Scene("drawer-open", "手機抽屜打開（有最近）", "home-busy", "#/", (("click", "#nav-toggle"),), ("phone-light",)),
)
SCENE_SLUGS = tuple(s.slug for s in SCENES)


def shot_name(index: int, scene: Scene, size: str) -> str:
    return f"{index:02d}-{scene.slug}-{size}.png"


def sizes_of(scene: Scene) -> list[tuple]:
    return [s for s in SIZES if s[0] in scene.sizes]


# ---- the run -------------------------------------------------------------------------------------------------------------------------------

def _load_qa47():
    found = sys.modules.get("qa_p47")
    if found is not None:
        return found
    spec = importlib.util.spec_from_file_location("qa_p47", Path(__file__).resolve().parent / "qa_p47.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_p47"] = module
    spec.loader.exec_module(module)
    return module


JS_THEME = "(t => { document.documentElement.dataset.theme = t; return true; })(%s)"
JS_ERRORS = "(window.__shotErrors || [])"
JS_HOOK = """(() => { if (!window.__shotErrors) { window.__shotErrors = []; window.addEventListener('error', (e) => window.__shotErrors.push(String(e.message).slice(0, 160))); } return true; })()"""
JS_METRICS = """(() => { const d = document.documentElement; const side = document.querySelector('nav.side'); const r = side ? side.getBoundingClientRect() : null;
  return { overflowX: d.scrollWidth > d.clientWidth + 1, scrollWidth: d.scrollWidth, clientWidth: d.clientWidth, sideHeight: r ? Math.round(r.height) : null }; })()"""


def run_scene(page, stub: Stub, scene: Scene, index: int, out: Path, qa47, base: str, result: dict) -> None:
    for size, width, height, theme in sizes_of(scene):
        stub.use(scene.world)
        page.viewport(width, height)
        page.b.call("Storage.clearDataForOrigin", {"origin": base, "storageTypes": "all"}, session=page.session)       # a choice of an earlier scene must not come back
        page.open(f"{base}/?scene={scene.slug}-{size}{scene.hash}")
        page.ev(JS_HOOK)
        page.settle(0.6, cap=10.0)
        for step in scene.steps:
            kind = step[0]
            if kind == "click":
                if not page.click(step[1]):
                    result["missing"].append(f"{scene.slug}/{size}: nothing to press at {step[1]}")
                page.settle(0.5)
            elif kind == "fill":
                if not page.fill(step[1], step[2]):
                    result["missing"].append(f"{scene.slug}/{size}: nothing to fill at {step[1]}")
            elif kind == "js":
                page.ev(step[1])
                time.sleep(0.3)
            elif kind == "wait":
                time.sleep(float(step[1]))
        if theme == "dark":
            page.ev(JS_THEME % json.dumps("dark"))
        else:
            page.ev(JS_THEME % json.dumps("light"))
        time.sleep(0.25)
        name = shot_name(index, scene, size)
        page.shot(out / name)
        metrics = page.ev(JS_METRICS) or {}
        errors = page.ev(JS_ERRORS) or []
        result["shots"].append({"file": name, "scene": scene.slug, "size": size, **metrics, "errors": errors})
        if metrics.get("overflowX") and width < 500:
            result["findings"].append(f"{name}: the page scrolls sideways ({metrics.get('scrollWidth')} > {metrics.get('clientWidth')})")


def main(argv=None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Screenshots of VBear's pages from made-up data (a stub console on 127.0.0.1 and a headless Chrome).")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--tmp", help="a folder made for this run (Chrome's profile goes there)")
    ap.add_argument("--out", help="where the PNG files and shots-stub-result.json go")
    ap.add_argument("--chrome", default=CHROME_DEFAULT)
    ap.add_argument("--only", default="", help="scene slugs, comma separated (default: all)")
    ap.add_argument("--list", action="store_true", help="print the scenes and stop")
    args = ap.parse_args(argv)
    if args.list:
        for i, s in enumerate(SCENES, 1):
            out(f"{i:02d} {s.slug:20s} {s.title}  [{', '.join(s.sizes)}]")
        return 0
    why = port_refusal(args.port)
    if why:
        out(f"refused: {why}")
        return 2
    if not args.tmp or not args.out:
        out("refused: --tmp and --out are needed")
        return 2
    for label, value, is_out in (("--tmp", args.tmp, False), ("--out", args.out, True)):
        why = path_refusal(value, output=is_out)
        if why:
            out(f"refused: {label}: {why}")
            return 2
    wanted = [s for s in args.only.split(",") if s]
    unknown = [s for s in wanted if s not in SCENE_SLUGS]
    if unknown:
        out(f"refused: no such scene: {', '.join(unknown)}")
        return 2
    tmp, outdir = Path(args.tmp), Path(args.out)
    if not tmp.is_dir():
        out("refused: --tmp must be a folder that exists (mktemp -d /tmp/v54.XXXX)")
        return 2
    outdir.mkdir(parents=True, exist_ok=True)
    qa47 = _load_qa47()
    qa47.CHROME_CAP_S = 30 * 60                   # this Chrome only draws invented pages; the 5 minutes of the real checks would end a long list of scenes
    qa47.WAIT_CAP_S = 60
    stub = Stub(args.port)
    stub.start()
    browser = None
    result = {"tool": "shots_stub", "port": args.port, "shots": [], "missing": [], "findings": [], "writes": [], "scenes": []}
    try:
        browser = qa47.Browser(args.chrome, tmp / "chrome")
        page = qa47.Page(browser, f"http://127.0.0.1:{args.port}")
        base = f"http://127.0.0.1:{args.port}"
        for i, scene in enumerate(SCENES, 1):
            if wanted and scene.slug not in wanted:
                continue
            result["scenes"].append(scene.slug)
            out(f"{i:02d} {scene.slug}: {scene.title}")
            run_scene(page, stub, scene, i, outdir, qa47, base, result)
    except qa47.Stop as e:
        result["findings"].append(f"stopped: {e}")
    finally:
        if browser is not None:
            browser.close()
        result["writes"] = stub.writes()
        stub.stop()
        (outdir / "shots-stub-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    out(f"{len(result['shots'])} shots, {len(result['missing'])} steps that found nothing, {len(result['writes'])} writes tried, {len(result['findings'])} findings")
    for line in result["missing"] + result["findings"]:
        out("  " + line)
    for w in result["writes"]:
        out("  write tried: " + w)
    return 0 if not (result["missing"] or result["writes"] or result["findings"]) else 1


if __name__ == "__main__":
    sys.exit(main())
