"""The person's memory (P42-1, ADR 0008): a few lines about them, their work and their decisions, the same for every
employee, that each new chat process of an employee is given.

``<state>/memory/`` (owner only):

  * ``memory.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "entries": [...], "cards_off": [...], "cards_on": [...]}``. A line is
    ``{id, kind, text, created_at, updated_at, source, confirmed_warning}``; at most 50 lines, 200 characters each, 4,000
    together. A file that cannot be read safely is never guessed at: the page says so, and a chat goes on without memory.
  * ``log.jsonl`` (0600, append-only, 1 MiB, then a new file and one old one kept): what was done and to which line (its id,
    its kind, how it came), never a word of the line.

Who writes: only the person, through the browser's ``/api/memory*`` routes of vbear/server.py (they carry ``X-VBear``). The
functions that change the file (``add``, ``edit``, ``delete``, ``clear``, ``set_card``; ``export`` only adds a line to the log)
are called from there and from nowhere else: no module of the chief of staff, of dispatch, of groups or of the chat service imports them, and a test
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

from . import config as cfg, groups
from .api_error import ApiError
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import chat_store as cs, memory_rules as mr

DIR = "memory"
LOG_MAX = 1 << 20
CARDS_OFF_MAX = 200
SCHEMA = 1
ENTRY_RE = re.compile(r"^m-[0-9a-f]{10}\Z")
PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
HOW = ("typed", "chat", "group", "suggested")
SOURCE_KEYS = {"how", "chat_id", "group_id", "turn", "suggestion_id", "speaker"}
SPEAKERS = ("you", "employee", None)
SAID_BY = ("you", "employee")                  # who said the words a line was made from (a chat or a group)
SUGGESTION_RE = re.compile(r"^ms-[0-9a-f]{12}\Z")
TURN_MAX = 1_000_000
CLEAR_WORDS = "全部刪除"
SOURCE_TEXT = {"typed": "你寫的", "chat": "從聊天記住的", "group": "從群組記住的", "suggested": "整理提議、你確認的"}
KIND_TITLE = {"about_you": "關於你", "work": "你的工作", "decision": "決定"}
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
    if key in ("cards_off", "cards_on"):
        ok = (isinstance(value, list) and len(value) <= CARDS_OFF_MAX
              and all(isinstance(x, str) and PROFILE_RE.match(x) for x in value) and len(set(value)) == len(value))
        return None if ok else key
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
    return {"v": SCHEMA, "entries": list(data.get("entries", [])), "cards_off": list(data.get("cards_off", [])),
            "cards_on": list(data.get("cards_on", []))}


# Whether a role card takes memory along when the person has not said (v0.17, the person's choice): Claude Code cards do, Codex
# cards do not (memory goes to OpenAI there, so the person switches it on). An engine not listed (cannot chat) takes none.
DEFAULT_ON = {"claude-chat": True, "codex-chat": False}


def card_on(profile_id, engine, cards_off, cards_on) -> bool:
    if profile_id in cards_on:
        return True
    if profile_id in cards_off:
        return False
    return DEFAULT_ON.get(engine, False)


def _ordered(entries) -> list:
    return sorted(entries, key=lambda e: (mr.KINDS.index(e["kind"]), e["created_at"], e["id"]))


def _used(entries) -> dict:
    return {"count": len(entries), "chars": sum(len(e["text"]) for e in entries),
            "max_count": mr.MAX_ENTRIES, "max_chars": mr.MAX_TOTAL}


# ---- reading -----------------------------------------------------------------------------------------------------------

def view() -> dict:
    """What GET /api/memory shows: the lines in page order (each marked ``blocked`` with the rule's code when the rules now
    refuse it), the use, and whether the file could be read. Never raises for a file that cannot be read: it says so."""
    base = {"entries": [], "used": _used([]), "readable": True, "where_text": WHERE_TEXT, "problem": None,
            "cards_off": [], "cards_on": []}
    try:
        if _folder(False) is None:
            return base
        data = _read()
    except StoreError:
        return dict(base, readable=False, problem=UNREADABLE)
    entries = [dict(e, blocked=mr.check(e["text"])["refuse"]) for e in _ordered(data["entries"])]
    return dict(base, entries=entries, used=_used(data["entries"]), cards_off=data["cards_off"],
                cards_on=data["cards_on"])


COMPANY = {"claude-chat": "Anthropic", "codex-chat": "OpenAI"}


def cards_view(cards, cards_off, cards_on) -> list:
    """The role cards as the memory page lists them: who takes memory with them, and which company it goes to. ``cards`` are
    the chat service's cards ({id, name, tool, engine, can_chat, ...}); a card that cannot chat has no company."""
    return [{"profile_id": c.get("id"), "name": c.get("name"), "tool": c.get("tool"), "company": COMPANY.get(c.get("engine")),
             "can_chat": c.get("can_chat") is True, "on": card_on(c.get("id"), c.get("engine"), cards_off, cards_on)}
            for c in cards if isinstance(c, dict)]


class ChatMemory(NamedTuple):
    readable: bool
    on: bool
    entries: list


def for_card(profile_id, engine) -> ChatMemory:
    """What a new chat process of this role card is given: ``on`` is false when the card is switched off (a Codex card, if the
    person never switched it on: ``DEFAULT_ON``), ``readable`` false
    when the file could not be read (then nothing is given, and the chat page says so). The lines are {kind, text} in page
    order. Reads only."""
    try:
        if _folder(False) is None:
            return ChatMemory(True, True, [])
        data = _read()
    except StoreError:
        return ChatMemory(False, False, [])
    if not card_on(profile_id, engine, data["cards_off"], data["cards_on"]):
        return ChatMemory(True, False, [])
    return ChatMemory(True, True, [{"kind": e["kind"], "text": e["text"]} for e in _ordered(data["entries"])])


# ---- the person's changes (called from the browser's routes only) ------------------------------------------------------

def _log(what: str, entry: dict | None = None, now: float | None = None, **extra) -> None:
    """One line, only the action and which line (``extra``: a card's id or a count, never a word of a line). A full log (1 MiB)
    becomes ``log.jsonl.1`` and a new one starts."""
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
    line.update(extra)
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


def _exists_chat(chat_id) -> bool:
    try:
        cs.load(cfg.state_dir(), chat_id)
    except cs.ChatStoreError:
        return False
    return True


def _exists_group(group_id) -> bool:
    try:
        groups.load(group_id)
    except groups.GroupError:
        return False
    return True


def _exists_suggestion(suggestion_id) -> bool:
    """A suggestion (P42-4) is a plain file ``<state>/memory/suggest/ms-<12 hex>.json`` of ours: not a link, not a folder."""
    try:
        st = os.lstat(cfg.state_dir() / DIR / "suggest" / f"{suggestion_id}.json")
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()


def _source(source) -> dict:
    """Where a line came from, as the page says it: ``{how: "chat", chat_id, turn, speaker}``, ``{how: "group", group_id, turn,
    speaker}`` (``speaker`` is "you" or "employee"; ``turn`` is the turn of the chat, or the number of the thing said in the
    group) or ``{how: "suggested", suggestion_id}``. The closed shape, and the place must exist (ApiError 400 otherwise)."""
    bad = ApiError(400, "bad_request", "source 的格式不符。")
    gone = ApiError(400, "bad_request", "找不到這句話是從哪裡來的（聊天、群組或整理提議已經不在了）。")
    if not isinstance(source, dict) or not isinstance(source.get("how"), str):
        raise bad
    how = source["how"]
    keys = {"chat": {"how", "chat_id", "turn", "speaker"}, "group": {"how", "group_id", "turn", "speaker"},
            "suggested": {"how", "suggestion_id"}}.get(how)
    if keys is None or set(source) != keys:
        raise bad
    if how == "suggested":
        sid = source["suggestion_id"]
        if not (isinstance(sid, str) and SUGGESTION_RE.match(sid)):
            raise bad
        if not _exists_suggestion(sid):
            raise gone
        return {"how": how, "suggestion_id": sid, "speaker": None}
    turn = source["turn"]
    if not (type(turn) is int and 0 <= turn <= TURN_MAX) or source["speaker"] not in SAID_BY:
        raise bad
    name, pattern, exists = (("chat_id", cs.CHAT_RE, _exists_chat) if how == "chat"
                             else ("group_id", groups.GROUP_ID_RE, _exists_group))
    where = source[name]
    if not (isinstance(where, str) and pattern.match(where)):
        raise bad
    if not exists(where):
        raise gone
    return {"how": how, name: where, "turn": turn, "speaker": source["speaker"]}


def add(body, now: float | None = None) -> dict:
    """Save one line: ``{kind, text}``, ``confirm_warning: true`` for a line that needs it, and ``source`` when the person made it
    from words in a chat, a group or a suggestion (see ``_source``; none means typed). ``{"entry": ...}``, or
    ApiError: bad_request (400), memory_refused (400, with the rule's code in ``refuse``), memory_full (409), memory_confirm
    (409, with ``warn``) or memory_unreadable (503)."""
    body = _body(body, {"kind", "text", "confirm_warning", "source"}, {"kind", "text"})
    confirm = body.get("confirm_warning", False)
    source = _source(body["source"]) if "source" in body else {"how": "typed", "speaker": None}
    text = _line_checked(body["kind"], body["text"], confirm)
    try:
        _folder(True)
        with store.locked():
            data = _read()
            entries = data["entries"]
            now = time.time() if now is None else now
            entry = {"id": "m-" + secrets.token_hex(5), "kind": body["kind"], "text": text, "created_at": now, "updated_at": now,
                     "source": source, "confirmed_warning": False}
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


def edit(entry_id, body, now: float | None = None) -> dict:
    """Change the kind or the text of one line (``{kind?, text?, confirm_warning?}``, at least one of the first two). The line
    keeps its id, its birth and its source; the same checks as ``add``, in the same order (refused, full, confirm). ``{"entry"}``,
    or ApiError: bad_request, memory_refused, memory_full, memory_confirm, memory_unreadable, not_found."""
    body = _body(body, {"kind", "text", "confirm_warning"}, set())
    if not ({"kind", "text"} & set(body)):
        raise ApiError(400, "bad_request", "要改 kind 或 text。")
    confirm = body.get("confirm_warning", False)
    try:
        _folder(True)
        with store.locked():
            data = _read()
            found = next((e for e in data["entries"] if e["id"] == entry_id), None) if isinstance(entry_id, str) else None
            if found is None:
                raise ApiError(404, "not_found", "找不到這一條記憶。")
            kind = body.get("kind", found["kind"])
            text = _line_checked(kind, body.get("text", found["text"]), confirm)
            now = time.time() if now is None else now
            changed = dict(found, kind=kind, text=text, updated_at=max(now, found["created_at"]))
            grown = [changed if e is found else e for e in data["entries"]]
            if (sum(len(e["text"]) for e in grown) > mr.MAX_TOTAL
                    or len(mr.block([{"kind": e["kind"], "text": e["text"]} for e in _ordered(grown)])) > mr.MAX_BLOCK):
                raise ApiError(409, "memory_full", f"記憶滿了（{mr.MAX_ENTRIES} 條或 {mr.MAX_TOTAL:,} 字），請先刪掉幾條。")
            changed["confirmed_warning"] = _confirmed(text, confirm)
            data["entries"] = grown
            store.save(data)
            _log("edited", changed, now)
    except StoreError as exc:
        raise _unreadable(exc) from None
    except OSError as exc:
        raise _unreadable(exc) from None
    return {"entry": changed}


def clear(body, now: float | None = None) -> dict:
    """Remove every line (the switches of the cards stay). The body must be exactly ``{confirm: "全部刪除"}``."""
    body = _body(body, {"confirm"}, {"confirm"})
    if body["confirm"] != CLEAR_WORDS:
        raise ApiError(400, "bad_request", f"要全部刪除，請輸入「{CLEAR_WORDS}」。")
    try:
        _folder(True)
        with store.locked():
            data = _read()
            count = len(data["entries"])
            data["entries"] = []
            store.save(data)
            _log("cleared", None, now, count=count)
    except StoreError as exc:
        raise _unreadable(exc) from None
    except OSError as exc:
        raise _unreadable(exc) from None
    return {"cleared": count}


COMPANY_WARN = {"send_to_openai": "打開之後，員工開新程序時，記憶會跟著送給 OpenAI（Codex 的公司）。確定要讓這位員工帶記憶嗎？"}


def set_card(body, cards, now: float | None = None) -> dict:
    """Switch memory on or off for one role card: ``{profile_id, on, confirm_company?}``. ``cards`` are the chat service's cards
    (``{id, engine, ...}``): the card must be there and its AI tool must be one that chats. Switching a card on whose tool
    belongs to OpenAI takes ``confirm_company: true`` (409 ``memory_confirm`` with ``warn: ["send_to_openai"]`` without it). A
    state that is the card's default is not kept in the file."""
    body = _body(body, {"profile_id", "on", "confirm_company"}, {"profile_id", "on"})
    pid, on = body["profile_id"], body["on"]
    if not (isinstance(pid, str) and PROFILE_RE.match(pid)) or not isinstance(on, bool):
        raise ApiError(400, "bad_request", "profile_id 必須是員工的識別碼，on 必須是 true 或 false。")
    confirm = body.get("confirm_company", False)
    if not isinstance(confirm, bool):
        raise ApiError(400, "bad_request", "confirm_company 必須是 true 或 false。")
    card = next((c for c in cards if isinstance(c, dict) and c.get("id") == pid), None)
    if card is None:
        raise ApiError(404, "not_found", "找不到這位員工。")
    engine = card.get("engine")
    if engine not in COMPANY:
        raise ApiError(400, "bad_request", "這位員工的 AI 工具還不能聊天，用不到記憶。")
    if on and COMPANY[engine] == "OpenAI" and not confirm:
        raise ApiError(409, "memory_confirm", COMPANY_WARN["send_to_openai"], warn=["send_to_openai"],
                       warn_text=[COMPANY_WARN["send_to_openai"]])
    try:
        _folder(True)
        with store.locked():
            data = _read()
            off = [x for x in data["cards_off"] if x != pid]
            keep_on = [x for x in data["cards_on"] if x != pid]
            if on != DEFAULT_ON.get(engine, False):
                (keep_on if on else off).append(pid)
            if len(off) > CARDS_OFF_MAX or len(keep_on) > CARDS_OFF_MAX:
                raise ApiError(409, "memory_full", "開關的紀錄滿了。")
            data["cards_off"], data["cards_on"] = off, keep_on
            store.save(data)
            _log("card_on" if on else "card_off", None, now, id=pid)
    except StoreError as exc:
        raise _unreadable(exc) from None
    except OSError as exc:
        raise _unreadable(exc) from None
    return {"profile_id": pid, "on": on}


def _says(source: dict) -> str:
    text = SOURCE_TEXT[source["how"]]
    if source["how"] in ("chat", "group") and source.get("speaker") in SAID_BY:
        text += "（你說的）" if source["speaker"] == "you" else "（員工說的）"
    return text


def export(now: float | None = None) -> dict:
    """The memory as one Markdown file for the browser to download: ``{filename, text}``. Three headings, one line for each line
    of memory with where it came from and the day it was saved; no id of a chat, a group or a line. A line is added to the log."""
    now = time.time() if now is None else now
    try:
        data = _read() if _folder(False) is not None else {"entries": []}
        out = ["# VBear 記憶", "", "匯出於 " + time.strftime("%Y-%m-%d", time.localtime(now)) + "。這是你自己的記憶，員工開新程序時會帶著它。", ""]
        for kind in mr.KINDS:
            out += [f"## {KIND_TITLE[kind]}", ""]
            lines = [e for e in _ordered(data["entries"]) if e["kind"] == kind]
            out += [f"- {e['text']}（{_says(e['source'])}，{time.strftime('%Y-%m-%d', time.localtime(e['created_at']))}）"
                    for e in lines] or ["（目前沒有）"]
            out.append("")
        _log("exported", None, now, count=len(data["entries"]))
    except StoreError as exc:
        raise _unreadable(exc) from None
    except OSError as exc:
        raise _unreadable(exc) from None
    return {"filename": time.strftime("vbear-記憶-%Y%m%d.md", time.localtime(now)), "text": "\n".join(out)}
