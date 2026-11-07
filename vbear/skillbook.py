"""The person's skills (P44-1, ADR 0010): ways of doing a job that the person saved in VBear, to be put in the box of a chat or a
group, read over, and sent as the person's own words. A skill is a name (40 characters) and some words (4,000 characters, line
breaks allowed). It is NOT one of the "skill cards" (``armory``, ``loadout``, ``skill_fit``, ``scan``: the skill files of the AI tools,
which VBear only lists).

``<state>/skillbook/`` (owner only):

  * ``skills.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "skills": [...]}``. A skill is ``{id, name, text, source, created_at,
    updated_at}``; ``id`` is ``k-<12 hex>``; ``source`` is ``{how: "typed"}``, ``{how: "said" | "reply", chat_id | group_id}`` (the
    person's own words, or an employee's, in a chat or a group) or ``{how: "suggested", suggestion_id}`` (P44-5). At most 100
    skills. A file that cannot be read safely is never guessed at or mended: the page says so and nothing is saved over it.
  * ``log.jsonl`` (0600, append-only, 1 MiB, then a new file and one old one kept): ``{at, action: add | edit | delete, id}``, never
    a word of a name or a text.

Who writes: only the person, through the browser's ``/api/my-skills*`` routes of vbear/server.py (they carry ``X-VBear``). The
functions that change the file (``add``, ``edit``, ``delete``, ``store``) are called from there and from nowhere else; a test
(tests/test_autonomy_guard.py) keeps it so. Nothing here writes ``config.json``, starts a program, installs a skill of an AI tool,
makes or changes a role card, answers a question of a chat or reaches the system prompt of any chat: a skill is only ever sent as
the words of the person, typed (or put there) in the box and sent by the person.

What may be saved is decided by ``runtime/memory_rules.check_text``, the rules of the memory.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import time
from typing import Any

from . import config as cfg, groups
from .api_error import ApiError
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import chat_store as cs, memory_rules as mr

DIR = "skillbook"
LOG_MAX = 1 << 20
SCHEMA = 1
MAX_SKILLS = 100
MAX_NAME = 40
MAX_TEXT = 4000
SKILL_RE = re.compile(r"^k-[0-9a-f]{12}\Z")
SUGGESTION_RE = re.compile(r"^ks-[0-9a-f]{12}\Z")
HOW = ("typed", "said", "reply", "suggested")
SKILL_KEYS = {"id", "name", "text", "source", "created_at", "updated_at"}
SOURCE_KEYS = {"typed": set(), "said": {"chat_id", "group_id"}, "reply": {"chat_id", "group_id"}, "suggested": {"suggestion_id"}}
UNREADABLE = ("技能的檔案有問題，VBear 先不碰它：現在看不到也存不了技能，聊天照常。請檢查狀態資料夾裡的 skillbook 資料夾"
              "（權限、是不是連結，或有沒有 skills.json.corrupted）。")
REFUSE_TEXT = {
    "bad_text": ("名稱或內容的格式不行：名稱 1 到 40 個字、不能換行；內容 1 到 4,000 個字；都不能是空的，不能有看不見的字元，"
                 "也不能含 VBear 的標記或存取權杖的名稱。"),
    "secret_password": "技能裡不能有密碼或驗證碼，請換個說法（例如只寫「密碼在我自己的密碼管理器」）。",
    "secret_key": "這看起來像金鑰或登入用的代碼，技能裡不能有。",
    "secret_account": "技能裡不能有帳號或 email。",
    "secret_payment": "技能裡不能有卡號、身分證字號或銀行帳號。",
}
WARN_TEXT = {
    "looks_like_order": ("這段看起來像在叫員工不問你就做事。技能不會讓員工不問你就做事：用它時它只是你對員工說的話，"
                         "每個指令、每個檔案修改照舊都會問你。確定要存嗎？"),
    "personal": "這看起來有電話或地址。用技能時它會跟著你送出的訊息送給 AI 公司。確定要存嗎？",
    "employee_words": "這段是員工寫的，存成技能後，你用它時會變成你對員工說的話。確定要存嗎？",
}
HOW_TEXT = {"typed": "你寫的", "said": "從你說的話存的", "reply": "從員工說的話存的", "suggested": "整理提議、你確認的"}


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _source_problem(source) -> bool:
    if not isinstance(source, dict) or source.get("how") not in HOW:
        return True
    how = source["how"]
    keys = set(source) - {"how"}
    if how == "typed":
        return bool(keys)
    if how == "suggested":
        return keys != {"suggestion_id"} or not (isinstance(source["suggestion_id"], str) and SUGGESTION_RE.match(source["suggestion_id"]))
    if len(keys) != 1 or not keys <= SOURCE_KEYS[how]:
        return True
    (name,) = keys
    pattern = cs.CHAT_RE if name == "chat_id" else groups.GROUP_ID_RE
    return not (isinstance(source[name], str) and pattern.match(source[name]))


def _skill_problem(skill) -> bool:
    return not (isinstance(skill, dict) and set(skill) == SKILL_KEYS
                and isinstance(skill["id"], str) and SKILL_RE.match(skill["id"])
                and isinstance(skill["name"], str) and 1 <= len(skill["name"]) <= MAX_NAME
                and isinstance(skill["text"], str) and 1 <= len(skill["text"]) <= MAX_TEXT
                and _num(skill["created_at"]) and _num(skill["updated_at"]) and not _source_problem(skill["source"]))


def _problem(key, value) -> str | None:
    """Why a top-level piece of skills.json is not one this module wrote (None when it is). Never names a word of a skill."""
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "skills":
        if not isinstance(value, list) or len(value) > MAX_SKILLS or any(_skill_problem(s) for s in value):
            return "skills"
        ids = [s["id"] for s in value]
        return None if len(set(ids)) == len(ids) else "skills"
    return "key"


store = GuardedJsonStore(f"{DIR}/skills.json", "技能", _problem)


def _folder(create: bool) -> Any:
    """The skillbook folder, owner only, and not a link: Path, or None when it does not exist and ``create`` is false.
    StoreError for anything that is not ours to use."""
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
        raise StoreError("技能的資料夾不是這個使用者自己的資料夾（或是連結）")
    if stat.S_IMODE(st.st_mode) != cfg.STATE_DIR_MODE:
        os.chmod(path, cfg.STATE_DIR_MODE)
    return path


def _unreadable(exc: Exception) -> ApiError:
    return ApiError(503, "skills_unreadable", UNREADABLE)


def _read() -> dict:
    """The file as a dict with both keys; StoreError when it cannot be read (a missing file is an empty book)."""
    data = store.load()
    return {"v": SCHEMA, "skills": list(data.get("skills", []))}


def _ordered(skills) -> list:
    return sorted(skills, key=lambda s: (-s["created_at"], s["id"]))


# ---- reading -----------------------------------------------------------------------------------------------------------

def view() -> dict:
    """What GET /api/my-skills shows: the skills, newest first, with their words, the limits, and whether the file could be read.
    Never raises for a file that cannot be read: it says so (``readable`` false and ``problem``). Looking creates nothing."""
    base = {"skills": [], "used": {"count": 0}, "limits": {"max_skills": MAX_SKILLS, "max_name": MAX_NAME, "max_text": MAX_TEXT},
            "readable": True, "problem": None}
    try:
        if _folder(False) is None:
            return base
        data = _read()
    except StoreError:
        return dict(base, readable=False, problem=UNREADABLE)
    return dict(base, skills=[dict(s) for s in _ordered(data["skills"])], used={"count": len(data["skills"])})


# ---- the person's changes (called from the browser's routes only) ------------------------------------------------------

def _log(action: str, skill_id: str, now: float | None = None) -> None:
    """One line: what was done and to which skill (its id), never a word. A full log (1 MiB) becomes ``log.jsonl.1``."""
    folder = _folder(True)
    path = folder / "log.jsonl"
    try:
        if os.lstat(path).st_size >= LOG_MAX:
            os.replace(path, folder / "log.jsonl.1")
    except FileNotFoundError:
        pass
    line = {"at": round(time.time() if now is None else now, 3), "action": action, "id": skill_id}
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


def _confirm_flag(body) -> bool:
    confirm = body.get("confirm_warning", False)
    if not isinstance(confirm, bool):
        raise ApiError(400, "bad_request", "confirm_warning 必須是 true 或 false。")
    return confirm


def _words(name, text) -> tuple[str, str, list]:
    """The trimmed name and text of a skill the person may save, and the warnings that need a yes; ApiError 400 for a name or text
    that is not a string, or that the rules refuse (the code of the rule in ``refuse``, the field in ``field``)."""
    if not isinstance(name, str) or not isinstance(text, str):
        raise ApiError(400, "bad_request", "name 與 text 必須是文字。")
    name, text = name.strip(), text.strip()
    warn: list = []
    for field, value, limit, multiline in (("name", name, MAX_NAME, False), ("text", text, MAX_TEXT, True)):
        got = mr.check_text(value, limit, multiline=multiline)
        if got["refuse"]:
            raise ApiError(400, "skill_refused", REFUSE_TEXT[got["refuse"]], refuse=got["refuse"], field=field)
        warn += [w for w in got["warn"] if w not in warn]
    return name, text, warn


def _confirmed(warn: list, confirm: bool) -> None:
    if warn and not confirm:
        raise ApiError(409, "confirm_warning", WARN_TEXT[warn[0]], warn=warn, warn_text=[WARN_TEXT[w] for w in warn])


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
    """A suggestion (P44-5) is a plain file ``<state>/skillbook/suggest/ks-<12 hex>.json`` of ours: not a link, not a folder."""
    try:
        st = os.lstat(cfg.state_dir() / DIR / "suggest" / f"{suggestion_id}.json")
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()


def _source(source) -> dict:
    """Where a skill came from, as the closed shape (see the module's docstring), and the place must exist: ApiError 400."""
    bad = ApiError(400, "bad_request", "source 的格式不符。")
    gone = ApiError(400, "bad_request", "找不到這段話是從哪裡來的（聊天、群組或整理提議已經不在了）。")
    if _source_problem(source):
        raise bad
    how = source["how"]
    if how == "typed":
        return {"how": "typed"}
    if how == "suggested":
        if not _exists_suggestion(source["suggestion_id"]):
            raise gone
        return {"how": how, "suggestion_id": source["suggestion_id"]}
    (name,) = set(source) - {"how"}
    if not (_exists_chat if name == "chat_id" else _exists_group)(source[name]):
        raise gone
    return {"how": how, name: source[name]}


def add(body, now: float | None = None) -> dict:
    """Save one skill: ``{name, text}``, ``confirm_warning: true`` when the page asked for a yes, and ``source`` when the person made
    it from words in a chat or a group (or from a suggestion); none means typed. ``{"skill": ...}``, or ApiError: bad_request (400),
    skill_refused (400, the rule's code in ``refuse``), skill_full (409), confirm_warning (409, with ``warn``; the words of an
    employee always need it) or skills_unreadable (503)."""
    body = _body(body, {"name", "text", "source", "confirm_warning"}, {"name", "text"})
    confirm = _confirm_flag(body)
    source = _source(body["source"]) if "source" in body else {"how": "typed"}
    name, text, warn = _words(body["name"], body["text"])
    if source["how"] == "reply":
        warn.append("employee_words")
    try:
        _folder(True)
        with store.locked():
            data = _read()
            if len(data["skills"]) >= MAX_SKILLS:
                raise ApiError(409, "skill_full", f"技能滿了（最多 {MAX_SKILLS} 個），請先刪掉幾個。")
            _confirmed(warn, confirm)
            now = time.time() if now is None else now
            ids = {s["id"] for s in data["skills"]}
            skill_id = "k-" + secrets.token_hex(6)
            while skill_id in ids:
                skill_id = "k-" + secrets.token_hex(6)
            skill = {"id": skill_id, "name": name, "text": text, "source": source, "created_at": now, "updated_at": now}
            data["skills"] = data["skills"] + [skill]
            store.save(data)
            _log("add", skill_id, now)
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"skill": skill}


def edit(skill_id, body, now: float | None = None) -> dict:
    """Change the name or the text of one skill (``{name?, text?, confirm_warning?}``, at least one of the first two). The skill
    keeps its id, its birth and its source; the same checks as ``add``. ``{"skill"}``, or ApiError: bad_request, skill_refused,
    confirm_warning, skills_unreadable, not_found."""
    body = _body(body, {"name", "text", "confirm_warning"}, set())
    if not ({"name", "text"} & set(body)):
        raise ApiError(400, "bad_request", "要改 name 或 text。")
    confirm = _confirm_flag(body)
    try:
        _folder(True)
        with store.locked():
            data = _read()
            found = next((s for s in data["skills"] if s["id"] == skill_id), None) if isinstance(skill_id, str) else None
            if found is None:
                raise ApiError(404, "not_found", "找不到這個技能。")
            name, text, warn = _words(body.get("name", found["name"]), body.get("text", found["text"]))
            _confirmed(warn, confirm)
            now = time.time() if now is None else now
            changed = dict(found, name=name, text=text, updated_at=max(now, found["created_at"]))
            data["skills"] = [changed if s is found else s for s in data["skills"]]
            store.save(data)
            _log("edit", skill_id, now)
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"skill": changed}


def delete(skill_id) -> dict:
    """Remove one skill. ApiError 404 when there is no such skill."""
    try:
        _folder(True)
        with store.locked():
            data = _read()
            found = next((s for s in data["skills"] if s["id"] == skill_id), None) if isinstance(skill_id, str) else None
            if found is None:
                raise ApiError(404, "not_found", "找不到這個技能。")
            data["skills"] = [s for s in data["skills"] if s is not found]
            store.save(data)
            _log("delete", skill_id)
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"deleted": skill_id}
