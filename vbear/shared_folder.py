"""The shared folder, the person's side (P43-1, ADR 0009): which employees may use it, what the page shows, and the button that opens
it in Finder.

The folder is ``<state>/shared`` (runtime/shared_rules.py decides whether it is safe and what may be written in it). Everything this
module keeps is in ``<state>/shared-meta/`` (owner only), which an employee's sandbox cannot write, because an employee can write the
shared folder and nothing in the shared folder may decide a permission:

  * ``settings.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "cards_on": [role card id, ...]}``, at most 200 ids. Every employee is
    OFF until the person switches them on. A file that cannot be read safely is never guessed at: the page says so and every employee
    is off (fail closed).
  * ``log.jsonl`` (0600, append-only, 1 MiB, then a new file and one old one kept): ``{at, what, profile_id?, how}`` with ``what`` one
    of card_on, card_off, revealed and ``how`` one of page, group, dispatch. Never a file name, never a word of a file.

Who writes: only the person, through the browser's routes of vbear/server.py (they carry ``X-VBear``). ``set_card`` is called from
there and from nowhere else (tests/test_autonomy_guard.py keeps it so); no module of the chief of staff, of dispatch, of groups, of
memory or of the chat service imports it. The chat service only *reads* (``for_card``). Nothing here writes ``config.json``, starts a
program (Finder is opened by a function the console passes in), installs a skill, makes or changes a role card, or answers a
question of a chat.

VBear does not read a file of the shared folder: the listing uses names, sizes and times only, links are not followed, and a name is
never written to a log or an error.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any

from . import config as cfg
from .api_error import ApiError
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import shared_rules as sr

DIR = "shared-meta"
LOG_MAX = 1 << 20
CARDS_MAX = 200
SCHEMA = 1
FILES_MAX = 200                                # files named on the page
PROFILE_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
HOW = ("page", "group", "dispatch")
COMPANY = {"claude-chat": "Anthropic", "codex-chat": "OpenAI"}
# The engines whose employees can use the shared folder now. P43-2 adds codex-chat; until then a Codex card is refused with
# ``card_tool_unsupported`` and ``for_card`` says no for it, whatever the file says.
SUPPORTED_ENGINES = ("claude-chat",)
FINDER = "/usr/bin/open"
IS_MAC = sys.platform == "darwin"
UNREADABLE = ("共用資料夾的設定有問題，VBear 先不碰它：在你修好之前，所有員工都當成不能用共用資料夾。請檢查狀態資料夾裡的 "
              "shared-meta 資料夾（權限、是不是連結，或有沒有 settings.json.corrupted）。")
UNSAFE_TEXT = ("共用資料夾的位置不安全（可能被換成連結或權限被改過），VBear 不會用它。請到共用資料夾頁看說明。")


def _problem(key, value) -> str | None:
    """Why a top-level piece of settings.json is not one this module wrote (None when it is)."""
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "cards_on":
        ok = (isinstance(value, list) and len(value) <= CARDS_MAX and all(isinstance(x, str) and PROFILE_ID_OK.match(x) for x in value)
              and len(set(value)) == len(value))
        return None if ok else key
    return "key"


store = GuardedJsonStore(f"{DIR}/settings.json", "共用資料夾的設定", _problem)


def folder() -> str:
    """The shared folder of this state folder (the only path the console ever uses)."""
    return sr.shared_path(cfg.state_dir())


def _home() -> str:
    return str(Path.home())


def _meta(create: bool) -> Any:
    """``<state>/shared-meta``, owner only and not a link: Path, or None when it is not there and ``create`` is false. StoreError
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
        raise StoreError("共用資料夾的紀錄資料夾不是這個使用者自己的資料夾（或是連結）")
    if stat.S_IMODE(st.st_mode) != cfg.STATE_DIR_MODE:
        os.chmod(path, cfg.STATE_DIR_MODE)
    return path


def _unreadable(exc: Exception) -> ApiError:
    return ApiError(503, "shared_unreadable", UNREADABLE)


def _read() -> dict:
    data = store.load()
    return {"v": SCHEMA, "cards_on": list(data.get("cards_on", []))}


def cards_on() -> tuple[bool, list]:
    """(whether the settings could be read, the ids switched on). Reads only; unreadable means nobody is on."""
    try:
        if _meta(False) is None:
            return True, []
        return True, _read()["cards_on"]
    except (StoreError, OSError):
        return False, []


def for_card(profile_id, engine) -> bool:
    """Whether this role card may use the shared folder in a new message: switched on by the person, its AI tool one that can use it, and
    the settings readable. Anything else is off. Reads only (the chat service calls this)."""
    if engine not in SUPPORTED_ENGINES:
        return False
    readable, on = cards_on()
    return readable and profile_id in on


# ---- reading ---------------------------------------------------------------------------------------------------------------

def where_text() -> str:
    """The place as the page says it: the home folder written ``~``."""
    path = folder()
    home = os.path.realpath(_home())
    return "~" + path[len(home):] if path.startswith(home.rstrip(os.sep) + os.sep) else path


def _name(rel: str) -> str:
    """A file name as the page shows it. A name that cannot be sent as text is replaced; any other name is shown as it is (the page
    sets it as text)."""
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        return "（檔名無法顯示）"
    return rel


def listing(path: str) -> dict:
    """What is in the folder, by names and sizes alone: ``{used, links, files}``. Links are not followed and no file is opened.
    ``files`` are the files and links (not the folders), newest first, at most FILES_MAX."""
    found = []
    size = entries = links = 0
    over = False
    try:
        for rel, st, link in sr.walk(path, sr.MAX_ENTRIES):
            entries += 1
            if entries > sr.MAX_ENTRIES:
                over = True
                break
            if link:
                links += 1
            if not stat.S_ISDIR(st.st_mode):
                if not link:
                    size += st.st_size
                found.append((st.st_mtime_ns, rel, st.st_size, link))
    except OSError:
        over = True
    over = over or size > sr.MAX_BYTES
    found.sort(key=lambda x: (-x[0], x[1]))
    files = [{"name": _name(rel), "size": sz, "mtime": ns / 1e9, "link": link} for ns, rel, sz, link in found[:FILES_MAX]]
    return {"used": {"bytes": size, "entries": min(entries, sr.MAX_ENTRIES + 1), "max_bytes": sr.MAX_BYTES,
                     "max_entries": sr.MAX_ENTRIES, "over": over}, "links": links, "files": files}


def cards_view(cards, on) -> list:
    """The role cards as the page lists them: who may use the folder, and which company reads what they read. ``verified`` is
    None: whether this AI tool's version has passed the check with the shared folder is P43-2's to say."""
    return [{"profile_id": c.get("id"), "name": c.get("name"), "tool": c.get("tool"), "company": COMPANY.get(c.get("engine")),
             "can_chat": c.get("can_chat") is True,
             "on": c.get("engine") in SUPPORTED_ENGINES and c.get("id") in on, "verified": None}
            for c in cards if isinstance(c, dict)]


def view(cards) -> dict:
    """What GET /api/shared shows. Never raises for settings that cannot be read, or for a folder that is not right: it says so."""
    out = {"where_text": where_text(), "exists": False, "problem": None,
           "used": {"bytes": 0, "entries": 0, "max_bytes": sr.MAX_BYTES, "max_entries": sr.MAX_ENTRIES, "over": False},
           "links": 0, "files": [], "readable": True}
    path = folder()
    readable, on = cards_on()
    out["readable"] = readable
    out["cards"] = cards_view(cards, on)
    out["exists"] = os.path.lexists(path)
    if out["exists"]:
        problem = sr.folder_problem(path, str(cfg.state_dir()), _home())
        if problem:
            out["problem"] = problem
        else:
            out.update(listing(path))
    return out


# ---- the person's changes (called from the browser's routes only) --------------------------------------------------------

def _log(what: str, now: float | None = None, **extra) -> None:
    """One line: what was done, to whom and how it came. A full log (1 MiB) becomes ``log.jsonl.1`` and a new one starts."""
    folder_ = _meta(True)
    path = folder_ / "log.jsonl"
    try:
        if os.lstat(path).st_size >= LOG_MAX:
            os.replace(path, folder_ / "log.jsonl.1")
    except FileNotFoundError:
        pass
    line = {"at": round(time.time() if now is None else now, 3), "what": what}
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


def set_card(body, cards, how: str = "page", now: float | None = None) -> dict:
    """Switch the shared folder on or off for one role card: ``{profile_id, on, confirm_company?}``. ``cards`` are the chat service's cards
    (``{id, engine, ...}``): the card must be there and its AI tool one that chats. Only the browser's routes call this (the
    browser's ``X-VBear`` is checked for every POST). A card of an AI tool the folder is not open to yet (Codex, until P43-2) is
    refused with 400 ``card_tool_unsupported``. Switching on makes the folder when it is not there and refuses (409 ``shared_unsafe``) one that is
    not right, without mending it; switching off always works and deletes nothing. ``how`` is page, group or dispatch."""
    body = _body(body, {"profile_id", "on", "confirm_company"}, {"profile_id", "on"})
    pid, on = body["profile_id"], body["on"]
    if not (isinstance(pid, str) and PROFILE_ID_OK.match(pid)) or not isinstance(on, bool):
        raise ApiError(400, "bad_request", "profile_id 必須是員工的識別碼，on 必須是 true 或 false。")
    if not isinstance(body.get("confirm_company", False), bool) or how not in HOW:
        raise ApiError(400, "bad_request", "confirm_company 必須是 true 或 false。")
    card = next((c for c in cards if isinstance(c, dict) and c.get("id") == pid), None)
    if card is None:
        raise ApiError(404, "not_found", "找不到這位員工。")
    engine = card.get("engine")
    if engine not in COMPANY:
        raise ApiError(400, "bad_request", "這位員工的 AI 工具還不能聊天，用不到共用資料夾。")
    if engine not in SUPPORTED_ENGINES:
        raise ApiError(400, "card_tool_unsupported", "這位員工的 AI 工具還不能用共用資料夾。")
    if on and sr.ensure_folder(str(cfg.state_dir()), _home()):
        raise ApiError(409, "shared_unsafe", UNSAFE_TEXT)
    try:
        _meta(True)
        with store.locked():
            data = _read()
            kept = [x for x in data["cards_on"] if x != pid]
            if on:
                kept.append(pid)
            if len(kept) > CARDS_MAX:
                raise ApiError(409, "shared_settings_full", "開關的紀錄滿了。")
            data["cards_on"] = kept
            store.save(data)
            _log("card_on" if on else "card_off", now, profile_id=pid, how=how)
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"profile_id": pid, "on": on}


def reveal(opener, now: float | None = None) -> dict:
    """Open the shared folder in Finder, by calling ``opener(["/usr/bin/open", <path>])`` (the console passes the function in; this
    module starts no program). 503 ``reveal_unavailable`` without one, 400 ``not_mac`` off a Mac, 409 ``shared_unsafe`` for a folder that
    is not right (made first when it is not there), 502 ``reveal_failed`` when the program fails. Nothing from the request is in the
    command; the log gets one line, ``revealed``."""
    if opener is None:
        raise ApiError(503, "reveal_unavailable", "這個主控台沒有接上「在 Finder 打開」。")
    if not IS_MAC:
        raise ApiError(400, "not_mac", "只有 Mac 能打開 Finder。")
    if sr.ensure_folder(str(cfg.state_dir()), _home()):
        raise ApiError(409, "shared_unsafe", UNSAFE_TEXT)
    try:
        opener([FINDER, folder()])
    except Exception:                      # whatever it was: the page says it did not work, without a path
        raise ApiError(502, "reveal_failed", "沒能用 Finder 打開共用資料夾。") from None
    try:
        _log("revealed", now, how="page")
    except (StoreError, OSError):
        pass                               # the folder is open; a record that cannot be written is not a reason to say it failed
    return {"revealed": True}
