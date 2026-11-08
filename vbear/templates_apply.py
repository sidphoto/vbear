"""The record of the applies of the team templates and the rules of 「復原這次套用」 (P45-2, ADR 0011).

A team template is applied by the console (``server.py``): it makes the employees, the skills and the routines one by one with the write
functions the person's own presses use, and writes down here what it made. This module is the notebook and the rule book. It makes no
employee, no skill and no routine, and it deletes none: it calls no write function of the cards, the skills or the routines, and imports
neither the skills nor the routines. The console hands it the facts it needs (what the person has now, which routines ever ran) and does
the deleting with the ordinary delete functions, after the person has seen the list and pressed 「刪掉這些」.

``<state>/templates/`` (owner only, 0700):

  * ``applies.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "applies": [...]}``, at most the last 50 applies, oldest first. An apply is
    ``{id, at, tool, state, undone_at, items}``: ``id`` is ``ta-<12 hex>``, ``state`` is ``applying`` | ``done`` | ``partial`` |
    ``interrupted``. An item is ``{kind, id, from, state, why, fp, at}``: ``kind`` is ``card`` | ``skill`` | ``routine``; ``id`` is the id
    the ordinary write function made (a skill's and a routine's is not known before it is made, so it is null while the state is
    ``intent``); ``from`` is ``{template, key}`` (the id of the team template and the key in it); ``state`` is ``intent`` (about to be
    made), ``made``, ``failed``, ``unknown`` (the console stopped in the middle of it, so it may or may not exist) or ``deleted`` (by an
    undo); ``why`` is the code of what stopped it; ``fp`` is the fingerprint of what was made, as it was made. **No name and no word of a
    card, a skill or a routine is kept here**: a name is read from the person's own files when the list is shown. A file that cannot be
    read safely is never guessed at or mended: the applies and the undo wait.
  * ``log.jsonl`` (0600, append only, 1 MiB, then a new file and one old one kept): ``{at, what, id, counts}``, with ``what`` one of
    ``applied`` | ``undo`` (P45-3 adds its own), the id of the apply and the numbers made or deleted of each kind. Never a word.

Who writes: the browser's ``/api/templates`` routes of ``server.py`` call the functions that change the record (``begin_apply``,
``record_item``, ``end_apply``, ``record_undo``, ``recover``, ``applies_store``) and nobody else does (tests/test_autonomy_guard.py keeps it
so). Nothing here writes ``config.json``, the memory, the shared folder, starts a program or answers a chat.

What an undo may delete is decided by ``undo_plan`` and nothing else, and it is careful: only what this apply made and recorded as made;
only what is still there and has the fingerprint it had when it was made (the person changed nothing); for a routine, only when no run, no
reminder and no miss was ever recorded for it; for an employee, only when no chat, group, dispatch, meeting, task, terminal record, memory
or shared-folder switch mentions him and no routine that stays is given to him. Whatever cannot be read counts as used and stays.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from pathlib import Path

from . import agent_profiles, config as cfg
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import chat_store

DIR = "templates"
SCHEMA = 1
MAX_APPLIES = 50
MAX_ITEMS = 60                      # 12 employees, 24 skills and 12 routines at most, with room for an intent that was replaced
LOG_MAX = 1 << 20
MENTION_FILE_MAX = 4 << 20          # a file the search of 「提到他」 reads, at the most
MENTION_FILES_MAX = 20000           # files the search reads, all together
APPLY_RE = re.compile(r"^ta-[0-9a-f]{12}\Z")
ITEM_ID_RE = {"card": re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z"), "skill": re.compile(r"^k-[0-9a-f]{12}\Z"), "routine": re.compile(r"^r-[0-9a-f]{12}\Z")}
TEMPLATE_RE = re.compile(r"^(?:shop|creator|studio|life|tm-[0-9a-f]{12})\Z")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}\Z")
WHY_RE = re.compile(r"^[a-z][a-z_]{0,39}\Z")
FP_RE = re.compile(r"^[0-9a-f]{64}\Z")
TOOLS = ("claude", "codex")
STATES = ("applying", "done", "partial", "interrupted")
ITEM_STATES = ("intent", "made", "failed", "unknown", "deleted")
KINDS = ("card", "skill", "routine")
COUNT_KEY = {"card": "cards", "skill": "skills", "routine": "routines"}
APPLY_KEYS = {"id", "at", "tool", "state", "undone_at", "items"}
ITEM_KEYS = {"kind", "id", "from", "state", "why", "fp", "at"}
UNREADABLE = ("團隊範本的套用紀錄有問題，VBear 先不碰它：現在不能套用團隊範本，也不能復原。請檢查狀態資料夾裡的 templates 資料夾"
              "（權限、是不是連結，或有沒有 applies.json.corrupted）。")

# Why something stays when the person presses 復原這次套用, in the words of the screen. The first reason that holds is the one said.
KEPT_TEXT = {
    ("card", "unreadable"): "讀不到紀錄，先留著",
    ("card", "changed"): "你改過他的卡",
    ("card", "chatted"): "你跟他聊過天",
    ("card", "in_use"): "他在群組、派工、會議或任務裡",
    ("card", "switches"): "你改過他的記憶或共用資料夾開關",
    ("card", "routine_kept"): "留下來的例行工作還交給他",
    ("skill", "unreadable"): "讀不到紀錄，先留著",
    ("skill", "changed"): "你改過",
    ("routine", "unreadable"): "讀不到紀錄，先留著",
    ("routine", "changed"): "你改過或打開過",
    ("routine", "ran"): "它提醒過或做過",
}
CARD_ORDER = ("unreadable", "changed", "chatted", "in_use", "switches", "routine_kept")
TERMINAL_NOTE = "如果你在終端機用過這些員工，VBear 看不出來；確定再刪。"
SKILL_NOTE = "VBear 不記錄技能有沒有被用過，只看有沒有改過。"
INTERRUPTED_NOTE = ("這次套用中斷了，最後一個技能或例行工作可能已經建好但沒記到，復原不會刪它；請到技能頁、例行工作頁看看。")


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _ref_problem(value) -> bool:
    return not (isinstance(value, dict) and set(value) == {"template", "key"} and isinstance(value["template"], str)
                and TEMPLATE_RE.match(value["template"]) and isinstance(value["key"], str) and KEY_RE.match(value["key"]))


def problem_of_item(item) -> str | None:
    """Why an item is not one this module wrote (None when it is). Never names a word of one."""
    if not (isinstance(item, dict) and set(item) == ITEM_KEYS):
        return "item"
    if item["kind"] not in KINDS or item["state"] not in ITEM_STATES:
        return "kind"
    if item["id"] is not None and not (isinstance(item["id"], str) and ITEM_ID_RE[item["kind"]].match(item["id"])):
        return "id"
    if item["id"] is None and item["state"] in ("made", "deleted"):
        return "id"
    if _ref_problem(item["from"]):
        return "from"
    if item["why"] is not None and not (isinstance(item["why"], str) and WHY_RE.match(item["why"])):
        return "why"
    if item["fp"] is not None and not (isinstance(item["fp"], str) and FP_RE.match(item["fp"])):
        return "fp"
    if not _num(item["at"]):
        return "at"
    return None


def problem_of_apply(apply) -> str | None:
    if not (isinstance(apply, dict) and set(apply) == APPLY_KEYS):
        return "apply"
    if not (isinstance(apply["id"], str) and APPLY_RE.match(apply["id"])):
        return "id"
    if apply["tool"] not in TOOLS or apply["state"] not in STATES:
        return "tool"
    if not _num(apply["at"]) or (apply["undone_at"] is not None and not _num(apply["undone_at"])):
        return "at"
    items = apply["items"]
    if not isinstance(items, list) or len(items) > MAX_ITEMS or any(problem_of_item(i) for i in items):
        return "items"
    return None


def _problem(key, value) -> str | None:
    """Why a top-level piece of applies.json is not one this module wrote (None when it is). Never names a word of a card."""
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "applies":
        if not isinstance(value, list) or len(value) > MAX_APPLIES or any(problem_of_apply(a) for a in value):
            return "applies"
        ids = [a["id"] for a in value]
        return None if len(set(ids)) == len(ids) else "applies"
    return "key"


applies_store = GuardedJsonStore(f"{DIR}/applies.json", "套用紀錄", _problem)


def _folder(create: bool):
    """The folder of the templates, owner only and not a link: Path, or None when it does not exist and ``create`` is false. StoreError for
    anything that is not ours to use."""
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
        raise StoreError("團隊範本的資料夾不是這個使用者自己的資料夾（或是連結）")
    if stat.S_IMODE(st.st_mode) != cfg.STATE_DIR_MODE:
        os.chmod(path, cfg.STATE_DIR_MODE)
    return path


def _log(what: str, apply_id: str, counts: dict, now: float | None = None) -> None:
    """One line: what happened, to which apply (its id), how many of each kind. A full log (1 MiB) becomes ``log.jsonl.1``."""
    folder = _folder(True)
    path = folder / "log.jsonl"
    try:
        if os.lstat(path).st_size >= LOG_MAX:
            os.replace(path, folder / "log.jsonl.1")
    except FileNotFoundError:
        pass
    line = {"at": round(time.time() if now is None else now, 3), "what": what, "id": apply_id, "counts": counts}
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        os.fchmod(fd, cfg.STATE_FILE_MODE)
        os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _counts(items, states) -> dict:
    out = {"cards": 0, "skills": 0, "routines": 0}
    for item in items:
        if item["state"] in states:
            out[COUNT_KEY[item["kind"]]] += 1
    return out


def _load() -> list:
    try:
        return list(applies_store.load().get("applies", []))
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc


def _save(applies: list) -> None:
    applies_store.save({"v": SCHEMA, "applies": applies[-MAX_APPLIES:]})


def _find(applies: list, apply_id):
    found = next((a for a in applies if a["id"] == apply_id), None) if isinstance(apply_id, str) else None
    if found is None:
        raise StoreError("找不到這次套用的紀錄")
    return found


# ---- reading --------------------------------------------------------------------------------------------------------------------

def read_applies() -> list:
    """The applies, newest first. StoreError when the file cannot be read safely. Looking creates nothing."""
    try:
        if _folder(False) is None:
            return []
        return list(reversed(_load()))
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc


def public(apply: dict, names: dict) -> dict:
    """An apply as the screen is sent it: its items with the name each has now in the person's own files (``names`` is
    ``{(kind, id): name}``; none for what is gone or was never made), how many of each kind were made, how many are still there to undo. The
    record itself keeps no name, and no fingerprint goes to the screen."""
    counts = {"cards": 0, "skills": 0, "routines": 0}
    left = dict(counts)
    items = []
    for item in apply["items"]:
        key = COUNT_KEY[item["kind"]]
        if item["state"] in ("made", "deleted"):
            counts[key] += 1
        if item["state"] == "made":
            left[key] += 1
        items.append({"kind": item["kind"], "id": item["id"], "from": dict(item["from"]), "state": item["state"], "why": item["why"],
                      "name": names.get((item["kind"], item["id"])) if item["state"] == "made" and item["id"] else None})
    return {"id": apply["id"], "at": apply["at"], "tool": apply["tool"], "state": apply["state"], "undone_at": apply["undone_at"],
            "counts": counts, "left": left, "items": items}


# ---- the notebook (called from the console's routes only) ------------------------------------------------------------------------

def begin_apply(tool: str, now: float | None = None) -> str:
    """Open a record for an apply that is starting: ``ta-<12 hex>``, state ``applying``. The oldest beyond 50 are dropped."""
    if tool not in TOOLS:
        raise StoreError("tool")
    now = time.time() if now is None else now
    try:
        _folder(True)
        with applies_store.locked():
            applies = _load()
            ids = {a["id"] for a in applies}
            apply_id = "ta-" + secrets.token_hex(6)
            while apply_id in ids:
                apply_id = "ta-" + secrets.token_hex(6)
            applies.append({"id": apply_id, "at": now, "tool": tool, "state": "applying", "undone_at": None, "items": []})
            _save(applies)
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc
    return apply_id


def record_item(apply_id: str, item: dict, index: int | None = None) -> int:
    """Write one item of an apply down: appended (``index`` None), or put in place of the one at ``index`` (an ``intent`` that became
    ``made`` or ``failed``). The place it has is returned. StoreError for an item of another shape or an apply that is not open."""
    bad = problem_of_item(item)
    if bad:
        raise StoreError("item")
    try:
        with applies_store.locked():
            applies = _load()
            apply = _find(applies, apply_id)
            if apply["state"] != "applying" or len(apply["items"]) + (index is None) > MAX_ITEMS:
                raise StoreError("apply")
            if index is None:
                apply["items"] = apply["items"] + [dict(item)]
                index = len(apply["items"]) - 1
            else:
                old = apply["items"][index] if 0 <= index < len(apply["items"]) else None
                if old is None or old["kind"] != item["kind"] or old["from"] != item["from"]:
                    raise StoreError("item")
                apply["items"] = [dict(item) if n == index else x for n, x in enumerate(apply["items"])]
            _save(applies)
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc
    return index


def end_apply(apply_id: str, state: str, now: float | None = None) -> None:
    """Close an apply as ``done`` or ``partial``."""
    if state not in ("done", "partial", "interrupted"):
        raise StoreError("state")
    now = time.time() if now is None else now
    try:
        with applies_store.locked():
            applies = _load()
            apply = _find(applies, apply_id)
            apply["state"] = state
            _save(applies)
            counts = _counts(apply["items"], ("made",))
        _log("applied", apply_id, counts, now)
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc


def record_undo(apply_id: str, item_ids, now: float | None = None, *, log: bool = True) -> None:
    """The ids of items that an undo deleted: their state becomes ``deleted`` and the apply gets the time. Only an item that is recorded as
    made can be one; any other id is a StoreError and nothing is written. The console writes this after every single delete (so that a stop
    in the middle loses nothing) with ``log=False`` and then one line for the whole press with ``log_undo``."""
    ids = list(item_ids)
    now = time.time() if now is None else now
    try:
        with applies_store.locked():
            applies = _load()
            apply = _find(applies, apply_id)
            made = {i["id"] for i in apply["items"] if i["state"] == "made"}
            if not ids or not set(ids) <= made:
                raise StoreError("id")
            changed = [dict(i, state="deleted", at=now) if i["id"] in ids and i["state"] == "made" else i for i in apply["items"]]
            gone = [i for i in changed if i["state"] == "deleted" and i["id"] in ids]
            apply["items"], apply["undone_at"] = changed, now
            _save(applies)
            counts = _counts(gone, ("deleted",))
        if log:
            _log("undo", apply_id, counts, now)
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc


def log_undo(apply_id: str, kinds, now: float | None = None) -> None:
    """One line in the log for a press of 復原這次套用: how many of each kind it deleted (``kinds`` are the kinds, ``card`` ``skill`` ``routine``)."""
    counts = {"cards": 0, "skills": 0, "routines": 0}
    for kind in kinds:
        counts[COUNT_KEY[kind]] += 1
    try:
        _log("undo", apply_id, counts, now)
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc


def recover(digest_of) -> int:
    """At the start of the console, before it serves: every apply still ``applying`` was left by a console that stopped. It becomes
    ``interrupted``. An employee whose id was written before he was made (``intent``) is ``made`` if he is there (``digest_of(id)`` gives his
    digest as he is now: nobody could have changed him while the console was stopped), ``failed`` if he is not, and ``unknown`` if he cannot
    be looked at. A skill or a routine has no id before it is made, so its ``intent`` becomes ``unknown`` and no undo ever touches it.
    Returns how many applies were closed."""
    try:
        if _folder(False) is None:
            return 0
        with applies_store.locked():
            applies = _load()
            open_ones = [a for a in applies if a["state"] == "applying"]
            if not open_ones:
                return 0
            now = time.time()
            for apply in open_ones:
                items = []
                for item in apply["items"]:
                    if item["state"] == "intent":
                        if item["kind"] == "card" and item["id"] is not None:
                            try:
                                digest = digest_of(item["id"])
                            except Exception:
                                item = dict(item, state="unknown", at=now)
                            else:
                                item = dict(item, state="made", fp=digest, at=now) if digest else dict(item, state="failed", why="interrupted", at=now)
                        else:
                            item = dict(item, state="unknown", at=now)
                    items.append(item)
                apply["items"], apply["state"] = items, "interrupted"
            _save(applies)
        for apply in open_ones:
            _log("applied", apply["id"], _counts(apply["items"], ("made",)), now)
        return len(open_ones)
    except OSError as exc:
        raise StoreError(UNREADABLE) from exc


# ---- fingerprints and 「提到他」 -----------------------------------------------------------------------------------------------

def fingerprint(kind: str, record: dict) -> str:
    """What a thing was when it was made: an employee's digest (the whole card, so any save of it counts as a change), and for a skill and a
    routine the digest of the whole record (``updated_at`` and ``enabled`` are in it)."""
    if kind == "card":
        return agent_profiles.profile_digest(record)
    blob = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


MENTION_ROOTS = (("groups", "in_use"), ("dispatch", "in_use"), ("chief", "in_use"), ("meetings", "in_use"), ("staffing", "in_use"),
                 ("sessions", "in_use"), ("shared-meta", "switches"))
MENTION_FILES = (("flows.json", "in_use"), ("tasks.json", "in_use"), ("memory/memory.json", "switches"))


def card_mentions(state_dir, profile_ids) -> dict:
    """For each employee id, the reasons to keep him that the files under the state folder give: ``chatted`` (a chat of his, or his work
    folder), ``in_use`` (a group, a dispatch, the chief of staff, a meeting, a team meeting, a terminal launch, a flow or a task), ``switches``
    (his memory or shared-folder switch was ever written), ``unreadable`` (something could not be read, so nothing can be ruled out). Only
    ordinary files are read, links are not followed, one file at most 4 MiB, 20,000 files all together, every file once. Read only."""
    ids = [p for p in profile_ids if isinstance(p, str) and p]
    found = {p: set() for p in ids}
    if not ids:
        return found
    needles = {p: p.encode("utf-8") for p in ids}
    base = Path(state_dir)
    budget = [MENTION_FILES_MAX]

    def unreadable():
        for p in ids:
            found[p].add("unreadable")

    def read_file(path: Path, reason: str) -> None:
        budget[0] -= 1
        if budget[0] < 0:
            unreadable()
            return
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            unreadable()
            return
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MENTION_FILE_MAX:
                unreadable()
                return
            with os.fdopen(fd, "rb") as fh:
                fd = -1
                data = fh.read(MENTION_FILE_MAX + 1)
        except OSError:
            unreadable()
            return
        finally:
            if fd != -1:
                os.close(fd)
        if len(data) > MENTION_FILE_MAX:
            unreadable()
            return
        for p, needle in needles.items():
            if needle in data:
                found[p].add(reason)

    def walk(root: Path, reason: str) -> None:
        try:
            st = os.lstat(root)
        except FileNotFoundError:
            return
        except OSError:
            unreadable()
            return
        if not stat.S_ISDIR(st.st_mode):
            unreadable()
            return
        stack = [root]
        while stack:
            folder = stack.pop()
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                unreadable()
                continue
            for entry in entries:
                try:
                    kind = entry.stat(follow_symlinks=False).st_mode
                except OSError:
                    unreadable()
                    continue
                if stat.S_ISDIR(kind):
                    stack.append(Path(entry.path))
                elif stat.S_ISREG(kind):
                    read_file(Path(entry.path), reason)
                else:
                    unreadable()                       # a link or anything else is not followed and cannot be ruled out
                if budget[0] < 0:
                    return

    chats = base / "chats"
    try:
        st = os.lstat(chats)
    except FileNotFoundError:
        st = None
    except OSError:
        unreadable()
        st = None
    if st is not None:
        if not stat.S_ISDIR(st.st_mode):
            unreadable()
        else:
            try:
                names = sorted(e.name for e in os.scandir(chats))
            except OSError:
                unreadable()
                names = []
            for name in names:
                one = chats / name
                try:
                    kind = os.lstat(one).st_mode
                except OSError:
                    unreadable()
                    continue
                if not stat.S_ISDIR(kind):
                    unreadable()
                    continue
                try:
                    os.lstat(one / "chat.json")
                except FileNotFoundError:
                    continue
                except OSError:
                    unreadable()
                    continue
                read_file(one / "chat.json", "chatted")
    for p in ids:
        try:
            os.lstat(base / "chat-work" / chat_store.work_dir_name(p))
        except FileNotFoundError:
            continue
        except OSError:
            found[p].add("unreadable")
            continue
        found[p].add("chatted")
    for name, reason in MENTION_ROOTS:
        walk(base / name, reason)
    for relative, reason in MENTION_FILES:
        path = base / relative
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError:
            unreadable()
            continue
        read_file(path, reason)
    return found


# ---- the rules of the undo ----------------------------------------------------------------------------------------------------

def undo_plan(apply: dict, facts: dict) -> dict:
    """What an undo of ``apply`` would do now: ``{delete, keep, gone, unsure}``. ``delete`` and ``keep`` and ``gone`` are lists of
    ``{kind, id}`` (``keep`` also has ``why``), routines first, then skills, then employees. ``unsure`` counts the items that stay out of it
    because it is not known what they are (``intent``, ``unknown``).

    ``facts`` is what the console read just now, nothing here reads a file: ``cards`` ``{id: digest}``, ``skills`` ``{id: fingerprint}``,
    ``routines`` ``{id: {fp, profile_id}}`` (each None when the file could not be read), ``run_ids`` (the routines that have any run, a
    reminder or a miss; None when the runs could not be read), ``mentions`` (``card_mentions``). Only an item recorded as ``made`` is ever
    looked at; an id that is not in the record is never named."""
    made = {kind: [i for i in apply["items"] if i["kind"] == kind and i["state"] == "made" and i["id"]] for kind in KINDS}
    out = {"delete": [], "keep": [], "gone": [], "unsure": sum(1 for i in apply["items"] if i["state"] in ("intent", "unknown"))}
    routines, run_ids = facts.get("routines"), facts.get("run_ids")

    def keep(kind, ident, why):
        out["keep"].append({"kind": kind, "id": ident, "why": why})

    def drop(kind, ident):
        out["delete"].append({"kind": kind, "id": ident})

    going = set()
    for item in made["routine"]:
        ident = item["id"]
        if routines is None or run_ids is None:
            keep("routine", ident, "unreadable")
        elif ident not in routines:
            out["gone"].append({"kind": "routine", "id": ident})
        elif routines[ident]["fp"] != item["fp"]:
            keep("routine", ident, "changed")
        elif ident in run_ids:
            keep("routine", ident, "ran")
        else:
            drop("routine", ident)
            going.add(ident)
    skills = facts.get("skills")
    for item in made["skill"]:
        ident = item["id"]
        if skills is None:
            keep("skill", ident, "unreadable")
        elif ident not in skills:
            out["gone"].append({"kind": "skill", "id": ident})
        elif skills[ident] != item["fp"]:
            keep("skill", ident, "changed")
        else:
            drop("skill", ident)
    cards, mentions = facts.get("cards"), facts.get("mentions") or {}
    for item in made["card"]:
        ident = item["id"]
        if cards is not None and ident not in cards:
            out["gone"].append({"kind": "card", "id": ident})
            continue
        reasons = set(mentions.get(ident, ()))
        if cards is None or routines is None:
            reasons.add("unreadable")
        elif cards[ident] != item["fp"]:
            reasons.add("changed")
        if routines is not None and any(r["profile_id"] == ident for rid, r in routines.items() if rid not in going):
            reasons.add("routine_kept")
        why = next((r for r in CARD_ORDER if r in reasons), None)
        if why is None:
            drop("card", ident)
        else:
            keep("card", ident, why)
    return out
