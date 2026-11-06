"""The person's memory (P42-1, ADR 0008): a few lines about them, their work and their decisions, the same for every
employee, that each new chat process of an employee is given.

``<state>/memory/`` (owner only):

  * ``memory.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "entries": [...], "cards_off": [...]}``. A line is
    ``{id, kind, text, created_at, updated_at, source, confirmed_warning}``; at most 50 lines, 200 characters each, 4,000
    together. A file that cannot be read safely is never guessed at: the page says so, and a chat goes on without memory.
  * ``log.jsonl`` (0600, append-only, 1 MiB, then a new file and one old one kept): what was done and to which line (its id,
    its kind, how it came), never a word of the line.

Who writes: only the person, through the browser's ``/api/memory*`` routes of vbear/server.py (they carry ``X-VBear``). The
functions that change the file (``add``, ``delete``; later ``edit``, ``clear``, ``set_card``) are called from there and from
nowhere else: no module of the chief of staff, of dispatch, of groups or of the chat service imports them, and a test
(tests/test_autonomy_guard.py) keeps it so. The chat service only *reads* (``for_card``). Nothing here writes
``config.json``, starts a program, installs a skill, makes or changes a role card, or answers a question of a chat.

What may be saved is decided by ``runtime/memory_rules.check``, the same function the daemon runs again before it builds a
chat's system prompt. Words of a line are in ``memory.json`` and in what ``view`` answers, and nowhere else: not in an error,
not in a log, not in the chat's record.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import time
from typing import Any, NamedTuple

from . import config as cfg
from .api_error import ApiError
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import memory_rules as mr

DIR = "memory"
LOG_MAX = 1 << 20
CARDS_OFF_MAX = 200
SCHEMA = 1
ENTRY_RE = re.compile(r"^m-[0-9a-f]{10}\Z")
PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
HOW = ("typed", "chat", "group", "suggested")
SOURCE_KEYS = {"how", "chat_id", "group_id", "turn", "suggestion_id", "speaker"}
SPEAKERS = ("you", "employee", None)
ENTRY_KEYS = {"id", "kind", "text", "created_at", "updated_at", "source", "confirmed_warning"}
WHERE_TEXT = ("員工開新程序時，記憶會跟著送給 Anthropic（Claude Code 的員工）或 OpenAI（Codex 的員工）。"
              "不要寫密碼、帳號、卡號；VBear 看到像這樣的內容會擋下。")
UNREADABLE = ("記憶的檔案有問題，VBear 先不碰它：聊天照常，但這段時間員工不帶記憶。請檢查狀態資料夾裡的 memory 資料夾"
              "（權限、是不是連結，或有沒有 memory.json.corrupted）。")


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _entry_problem(entry) -> str | None:
    if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
        return "欄位不符"
    if not (isinstance(entry["id"], str) and ENTRY_RE.match(entry["id"])):
        return "id"
    if entry["kind"] not in mr.KINDS:
        return "kind"
    if not (isinstance(entry["text"], str) and 1 <= len(entry["text"]) <= mr.MAX_TEXT):
        return "text"
    if not (_num(entry["created_at"]) and _num(entry["updated_at"])):
        return "time"
    source = entry["source"]
    if not (isinstance(source, dict) and source.get("how") in HOW and set(source) <= SOURCE_KEYS
            and source.get("speaker") in SPEAKERS):
        return "source"
    if not isinstance(entry["confirmed_warning"], bool):
        return "confirmed_warning"
    return None


def _problem(key, value) -> str | None:
    """Why a top-level piece of memory.json is not one this module wrote (None when it is). Never names a word of a line."""
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "entries":
        if not isinstance(value, list) or len(value) > mr.MAX_ENTRIES:
            return "entries"
        for entry in value:
            if _entry_problem(entry):
                return "entries"
        ids = [e["id"] for e in value]
        if len(set(ids)) != len(ids) or sum(len(e["text"]) for e in value) > mr.MAX_TOTAL:
            return "entries"
        return None
    if key == "cards_off":
        ok = (isinstance(value, list) and len(value) <= CARDS_OFF_MAX
              and all(isinstance(x, str) and PROFILE_RE.match(x) for x in value) and len(set(value)) == len(value))
        return None if ok else "cards_off"
    return "key"


store = GuardedJsonStore(f"{DIR}/memory.json", "記憶", _problem)


def _folder(create: bool) -> Any:
    """The memory folder, owner only, and not a link: Path, or None when it does not exist and ``create`` is false. StoreError
    for anything that is not ours to use."""
    path = cfg.state_dir() / DIR
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if not create:
            return None
        cfg.ensure_state_dir()
        path.mkdir(mode=cfg.STATE_DIR_MODE, exist_ok=True)
        st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise StoreError("記憶的資料夾不是這個使用者自己的資料夾（或是連結）")
    if stat.S_IMODE(st.st_mode) != cfg.STATE_DIR_MODE:
        os.chmod(path, cfg.STATE_DIR_MODE)
    return path


def _unreadable(exc: Exception) -> ApiError:
    return ApiError(503, "memory_unreadable", UNREADABLE)


def _read() -> dict:
    """The file as a dict with all three keys; StoreError when it cannot be read (a missing file is empty memory)."""
    data = store.load()
    return {"v": SCHEMA, "entries": list(data.get("entries", [])), "cards_off": list(data.get("cards_off", []))}


def _ordered(entries) -> list:
    return sorted(entries, key=lambda e: (mr.KINDS.index(e["kind"]), e["created_at"], e["id"]))


def _used(entries) -> dict:
    return {"count": len(entries), "chars": sum(len(e["text"]) for e in entries),
            "max_count": mr.MAX_ENTRIES, "max_chars": mr.MAX_TOTAL}


# ---- reading -----------------------------------------------------------------------------------------------------------

def view() -> dict:
    """What GET /api/memory shows: the lines in page order (each marked ``blocked`` with the rule's code when the rules now
    refuse it), the use, and whether the file could be read. Never raises for a file that cannot be read: it says so."""
    base = {"entries": [], "used": _used([]), "readable": True, "where_text": WHERE_TEXT, "problem": None}
    try:
        if _folder(False) is None:
            return base
        data = _read()
    except StoreError:
        return dict(base, readable=False, problem=UNREADABLE)
    entries = [dict(e, blocked=mr.check(e["text"])["refuse"]) for e in _ordered(data["entries"])]
    return dict(base, entries=entries, used=_used(data["entries"]))


class ChatMemory(NamedTuple):
    readable: bool
    on: bool
    entries: list


def for_card(profile_id) -> ChatMemory:
    """What a new chat process of this role card is given: ``on`` is false when the card is switched off, ``readable`` false
    when the file could not be read (then nothing is given, and the chat page says so). The lines are {kind, text} in page
    order. Reads only."""
    try:
        if _folder(False) is None:
            return ChatMemory(True, True, [])
        data = _read()
    except StoreError:
        return ChatMemory(False, False, [])
    if profile_id in data["cards_off"]:
        return ChatMemory(True, False, [])
    return ChatMemory(True, True, [{"kind": e["kind"], "text": e["text"]} for e in _ordered(data["entries"])])


# ---- the person's changes (called from the browser's routes only) ------------------------------------------------------

def _log(what: str, entry: dict | None = None, now: float | None = None) -> None:
    """One line, only the action and which line. A full log (1 MiB) becomes ``log.jsonl.1`` and a new one starts."""
    folder = _folder(True)
    path = folder / "log.jsonl"
    try:
        if os.lstat(path).st_size >= LOG_MAX:
            os.replace(path, folder / "log.jsonl.1")
    except FileNotFoundError:
        pass
    line = {"at": round(time.time() if now is None else now, 3), "what": what}
    if entry is not None:
        line.update(id=entry["id"], kind=entry["kind"], how=entry["source"]["how"])
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        os.fchmod(fd, cfg.STATE_FILE_MODE)
        os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _body(body, allowed: set, required: set) -> dict:
    if not isinstance(body, dict) or not required <= set(body) or set(body) - allowed:
        raise ApiError(400, "bad_request", "只接受 " + "、".join(sorted(allowed)) + "。")
    return body


def _line_checked(kind, text, confirm) -> str:
    """The trimmed text of a line the person may save, or ApiError: refused (400) or in need of a confirmation (409)."""
    if kind not in mr.KINDS:
        raise ApiError(400, "bad_request", "kind 只能是 about_you、work 或 decision。")
    if not isinstance(text, str):
        raise ApiError(400, "bad_request", "text 必須是文字。")
    if not isinstance(confirm, bool):
        raise ApiError(400, "bad_request", "confirm_warning 必須是 true 或 false。")
    text = text.strip()
    got = mr.check(text)
    if got["refuse"]:
        raise ApiError(400, "memory_refused", mr.REFUSE_TEXT[got["refuse"]], refuse=got["refuse"])
    return text


def _confirmed(text, confirm) -> bool:
    warn = mr.check(text)["warn"]
    if warn and not confirm:
        raise ApiError(409, "memory_confirm", mr.WARN_TEXT[warn[0]], warn=warn, warn_text=[mr.WARN_TEXT[w] for w in warn])
    return bool(warn)


def add(body, now: float | None = None) -> dict:
    """Save one line: ``{kind, text}`` and, for a line that needs it, ``confirm_warning: true``. ``{"entry": ...}``, or
    ApiError: bad_request (400), memory_refused (400, with the rule's code in ``refuse``), memory_full (409), memory_confirm
    (409, with ``warn``) or memory_unreadable (503)."""
    body = _body(body, {"kind", "text", "confirm_warning"}, {"kind", "text"})
    confirm = body.get("confirm_warning", False)
    text = _line_checked(body["kind"], body["text"], confirm)
    try:
        _folder(True)
        with store.locked():
            data = _read()
            entries = data["entries"]
            now = time.time() if now is None else now
            entry = {"id": "m-" + secrets.token_hex(5), "kind": body["kind"], "text": text, "created_at": now, "updated_at": now,
                     "source": {"how": "typed", "speaker": None}, "confirmed_warning": False}
            grown = entries + [entry]
            if (len(grown) > mr.MAX_ENTRIES or sum(len(e["text"]) for e in grown) > mr.MAX_TOTAL
                    or len(mr.block([{"kind": e["kind"], "text": e["text"]} for e in _ordered(grown)])) > mr.MAX_BLOCK):
                raise ApiError(409, "memory_full", f"記憶滿了（{mr.MAX_ENTRIES} 條或 {mr.MAX_TOTAL:,} 字），請先刪掉幾條。")
            entry["confirmed_warning"] = _confirmed(text, confirm)
            data["entries"] = grown
            store.save(data)
            _log("added", entry, now)
    except StoreError as exc:
        raise _unreadable(exc) from None
    except OSError as exc:
        raise _unreadable(exc) from None
    return {"entry": entry}


def delete(entry_id) -> dict:
    """Remove one line. ApiError 404 when there is no such line."""
    try:
        _folder(True)
        with store.locked():
            data = _read()
            found = next((e for e in data["entries"] if e["id"] == entry_id), None) if isinstance(entry_id, str) else None
            if found is None:
                raise ApiError(404, "not_found", "找不到這一條記憶。")
            data["entries"] = [e for e in data["entries"] if e is not found]
            store.save(data)
            _log("deleted", found)
    except StoreError as exc:
        raise _unreadable(exc) from None
    except OSError as exc:
        raise _unreadable(exc) from None
    return {"deleted": entry_id}
