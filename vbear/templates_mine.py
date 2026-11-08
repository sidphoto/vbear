"""The person's own team templates (團隊範本, P45-3, ADR 0011): a copy of the employees, skills and routines the person has now, or of the
items they ticked in other team templates, kept on this computer to be applied again or ticked from again.

``<state>/templates/`` (owner only, 0700):

  * ``mine.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "templates": [...]}``. A template is the closed shape of ``templates.py``
    (``{id, name, builtin: false, cards, skills, routines}``, ``about`` may be left out); its id is ``tm-<12 hex>``; at most 20. One field
    more, or one less, makes the whole file unreadable: it is not mended, not written over, and the built-in four still work.
  * ``log.jsonl`` (0600, append only, 1 MiB, then a new file and one old one kept): ``{at, what: saved_mine | renamed_mine | deleted_mine,
    id, counts?}``, never a name or a word (the applies of P45-2 write ``applied`` and ``undo`` lines into the same file).

What is kept of an employee: the name, the position (when this build lists it), the standing instructions the person wrote on the card
(not the position's default text) and the Claude alias of the model. Nothing else: not the AI tool, not the launch mode (a full-mode employee
is kept as a template employee, and applying makes every employee in safe mode), not the skill cards, the profession, the permission
records, whether the card is switched off, the memory or the shared folder, the chats, the work folder, an id or a time. Of a skill: the name
and the words (no source, no id). Of a routine: the name, the words, the days and the times, and who it is for when that employee is saved
too (else nobody, and applying asks); never whether it is switched on, its runs or the employee's id. The copy is of this moment: changing the
original later does not change it.

Who writes: only the person, through the browser's ``/api/templates/mine*`` routes of vbear/server.py (they carry ``X-VBear``). The functions
that change the file (``save_mine``, ``rename_mine``, ``delete_mine``, ``mine_store``) are called from there and from nowhere else; a test
(tests/test_autonomy_guard.py) keeps it so. Nothing here writes a role card, a skill or a routine, writes ``config.json``, starts a program or
reaches the network: there is no way to export, import, send or fetch a template.

What may be saved is decided by ``runtime/memory_rules.check_text`` over every word of the new template (``templates.warnings_of``), and what
refuses is not repeated in the answer: it names the kind, the place in the request and the field, never the words.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import stat
import time
from typing import Any

from . import agent_profiles, config as cfg, templates as tp, templates_builtin
from .api_error import ApiError
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import memory_rules

DIR = "templates"
LOG_MAX = 1 << 20
SCHEMA = 1
UNREADABLE = ("你存的團隊範本的檔案有問題，VBear 先不碰它：現在看不到也存不了你自己的團隊範本，VBear 內建的團隊範本照常可以用。"
              "請檢查狀態資料夾裡的 templates 資料夾（權限、是不是連結，或有沒有 mine.json.corrupted）。")
SAVE_WARN_TEXT = {
    "looks_like_order": ("這段看起來像在叫員工不問你就做事。團隊範本不會讓員工不問你就做事：員工一律用安全模式，"
                         "每個指令、每個檔案修改照舊都會問你。確定要存進團隊範本嗎？"),
    "personal": "這看起來有電話或地址。團隊範本的字套用後會成為員工的固定指示、技能或例行工作的內容，之後會跟著訊息送給 AI 公司。確定要存進團隊範本嗎？",
}
REFUSE_SAVE_TEXT = {
    "bad_text": "有格式不行的字（空的、太長、有看不見的字元，或含 VBear 的標記）",
    "secret_password": "有密碼或驗證碼",
    "secret_key": "有像金鑰或登入用代碼的東西",
    "secret_account": "有帳號或 email",
    "secret_payment": "有卡號、身分證字號或銀行帳號",
}
PLACE_WORD = {"cards": "員工", "skills": "技能", "routines": "例行工作", "template": "團隊範本"}
FIELD_WORD = {"name": "名稱", "instructions": "固定指示", "text": "內容"}
NOTE_FULL_MODE = "完整模式不會存進團隊範本：這位員工存下來沒有出發模式，套用時一律是安全模式。"
NOTE_NO_ASSIGNEE = "這件例行工作交給的員工沒有一起存，套用時要再選一位員工。"

_FROM_KEY = {"cards": "profile_id", "skills": "skill_id", "routines": "routine_id"}


def _problem(key, value) -> str | None:
    """Why a top-level piece of mine.json is not one this module wrote (None when it is). Never names a word of a template."""
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "templates":
        if not isinstance(value, list) or len(value) > tp.MAX_MINE:
            return "templates"
        if any(tp.template_problem(t, builtin=False) is not None for t in value):
            return "templates"
        ids = [t["id"] for t in value]
        return None if len(set(ids)) == len(ids) else "templates"
    return "key"


mine_store = GuardedJsonStore(f"{DIR}/mine.json", "團隊範本", _problem)


def _folder(create: bool) -> Any:
    """The templates folder, owner only, and not a link: Path, or None when it does not exist and ``create`` is false.
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
        raise StoreError("團隊範本的資料夾不是這個使用者自己的資料夾（或是連結）")
    if stat.S_IMODE(st.st_mode) != cfg.STATE_DIR_MODE:
        os.chmod(path, cfg.STATE_DIR_MODE)
    return path


def _unreadable() -> ApiError:
    return ApiError(503, "templates_unreadable", UNREADABLE)


def _read() -> list:
    """The saved templates; StoreError when the file cannot be read (a missing file is none)."""
    return list(mine_store.load().get("templates", []))


def read_mine() -> tuple[list, bool, str | None]:
    """``(templates, readable, problem)``: the person's own team templates in the order they were saved; ``problem`` is a sentence when the file
    cannot be read (then the list is empty). Looking creates nothing."""
    try:
        if _folder(False) is None:
            return [], True, None
        return _read(), True, None
    except (StoreError, OSError):
        return [], False, UNREADABLE


def _log(what: str, template_id: str, counts: dict | None = None, now: float | None = None) -> None:
    """One line: what was done and to which template (its id), never a word. A full log (1 MiB) becomes ``log.jsonl.1``."""
    folder = _folder(True)
    path = folder / "log.jsonl"
    try:
        if os.lstat(path).st_size >= LOG_MAX:
            os.replace(path, folder / "log.jsonl.1")
    except FileNotFoundError:
        pass
    line: dict[str, Any] = {"at": round(time.time() if now is None else now, 3), "what": what, "id": template_id}
    if counts is not None:
        line["counts"] = counts
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        os.fchmod(fd, cfg.STATE_FILE_MODE)
        os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


# ---- the request ------------------------------------------------------------------------------------------------------------------

def _bad(text: str) -> ApiError:
    return ApiError(400, "bad_request", text)


def _confirm_flag(body) -> bool:
    confirm = body.get("confirm_warning", False)
    if not isinstance(confirm, bool):
        raise _bad("confirm_warning 必須是 true 或 false。")
    return confirm


def _name_of(body) -> str:
    name = body.get("name")
    if not isinstance(name, str):
        raise _bad("name 必須是文字。")
    return name.strip()


def _rows(body: dict, kind: str) -> list:
    rows = body.get(kind, [])
    if not isinstance(rows, list):
        raise _bad(f"{kind} 必須是陣列。")
    for row in rows:
        if not isinstance(row, dict) or not (set(row) == {"from"} or set(row) == {_FROM_KEY[kind]}):
            raise _bad(f"每個{PLACE_WORD[kind]}只接受 from（團隊範本裡的項目）或 {_FROM_KEY[kind]}（你現在有的）其中一個。")
    return rows


def _check_request(body) -> tuple[str, dict, bool]:
    allowed = {"name", "cards", "skills", "routines", "confirm_warning"}
    if not isinstance(body, dict) or "name" not in body or set(body) - allowed:
        raise _bad("只接受 name、cards、skills、routines、confirm_warning，而且要有 name。")
    confirm = _confirm_flag(body)
    name = _name_of(body)
    rows = {kind: _rows(body, kind) for kind in tp.KINDS}
    if not any(rows.values()):
        raise _bad("至少要有一項。")
    return name, rows, confirm


def _ref(value, templates: dict, kind: str):
    """(template id, item) of ``{"template": id, "key": key}``, else ApiError 400."""
    if not (isinstance(value, dict) and set(value) == {"template", "key"} and isinstance(value["template"], str) and isinstance(value["key"], str)):
        raise _bad(f"{PLACE_WORD[kind]}的 from 要是 {{template, key}}。")
    template = templates.get(value["template"])
    if template is None:
        raise _bad("找不到這個團隊範本。")
    item = next((x for x in template[kind] if x["key"] == value["key"]), None)
    if item is None:
        raise _bad(f"這個團隊範本裡沒有這個{PLACE_WORD[kind]}。")
    return template["id"], item


def _by_id(items, item_id, what: str):
    found = next((x for x in items if isinstance(x, dict) and x.get("id") == item_id), None) if isinstance(item_id, str) else None
    if found is None:
        raise ApiError(404, "not_found", f"找不到這個{what}（可能剛被刪掉了）。")
    return found


def _card_of(profile) -> tuple[dict, bool]:
    """The five things of an employee that a team template keeps, and whether the card is one that starts in full mode."""
    model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
    instructions = agent_profiles.instructions_of(profile)
    position = agent_profiles.position_of(profile)
    alias = model.get("model_id")
    card = {"name": profile.get("name"), "position": position if position in tp.POSITIONS else None,
            "instructions": instructions["text"] if instructions["source"] == "custom" else None,
            "claude_model": alias if alias in tp.CLAUDE_MODELS else None}
    return card, agent_profiles.effective_launch_mode(profile) == "full"


def _free_key(base: str, used: set) -> str:
    key, n = base, 1
    while key in used:
        n += 1
        suffix = f"_{n}"
        key = base[: 24 - len(suffix)] + suffix
    used.add(key)
    return key


def _assemble(rows: dict, templates: dict, now: dict) -> tuple[dict, list, dict]:
    """The new template's three lists (without id or name), the notes, and the place of every item as ``{(kind, key): index}``."""
    cards: list = []
    skills: list = []
    routines: list = []
    notes: list = []
    used = {kind: set() for kind in tp.KINDS}
    seen: set = set()
    new_card_key: dict = {}          # ("now", profile_id) or (template id, key) -> the key in the new template
    order: dict = {}

    def once(token):
        if token in seen:
            raise _bad("同一項不能選兩次。")
        seen.add(token)

    for index, row in enumerate(rows["cards"]):
        if "from" in row:
            tid, item = _ref(row["from"], templates, "cards")
            once(("cards", tid, item["key"]))
            token, card = (tid, item["key"]), copy.deepcopy(item)
            card["key"] = _free_key(item["key"], used["cards"])
        else:
            profile = _by_id(now["cards"], row["profile_id"], "員工")
            once(("cards", "now", profile["id"]))
            token = ("now", profile["id"])
            card, full = _card_of(profile)
            card["key"] = _free_key(f"card_{len(cards) + 1}", used["cards"])
            if full:
                notes.append({"code": "full_mode_saved_safe", "kind": "cards", "index": index, "text": NOTE_FULL_MODE})
        new_card_key[token] = card["key"]
        cards.append({k: card[k] for k in tp.CARD_KEYS})
        order[("card", card["key"])] = ("cards", index)

    for index, row in enumerate(rows["skills"]):
        if "from" in row:
            tid, item = _ref(row["from"], templates, "skills")
            once(("skills", tid, item["key"]))
            skill = {"key": _free_key(item["key"], used["skills"]), "name": item["name"], "text": item["text"]}
        else:
            found = _by_id(now["skills"], row["skill_id"], "技能")
            once(("skills", "now", found["id"]))
            skill = {"key": _free_key(f"skill_{len(skills) + 1}", used["skills"]), "name": found.get("name"), "text": found.get("text")}
        skills.append(skill)
        order[("skill", skill["key"])] = ("skills", index)

    for index, row in enumerate(rows["routines"]):
        if "from" in row:
            tid, item = _ref(row["from"], templates, "routines")
            once(("routines", tid, item["key"]))
            who = new_card_key.get((tid, item["who"])) if item["who"] else None
            routine = {"key": _free_key(item["key"], used["routines"]), "name": item["name"], "text": item["text"], "days": list(item["days"]),
                       "times": list(item["times"]), "who": who}
        else:
            found = _by_id(now["routines"], row["routine_id"], "例行工作")
            once(("routines", "now", found["id"]))
            routine = {"key": _free_key(f"routine_{len(routines) + 1}", used["routines"]), "name": found.get("name"), "text": found.get("text"),
                       "days": list(found.get("days") or []), "times": list(found.get("times") or []),
                       "who": new_card_key.get(("now", found.get("profile_id")))}
        if routine["who"] is None:
            notes.append({"code": "routine_no_assignee", "kind": "routines", "index": index, "text": NOTE_NO_ASSIGNEE})
        routines.append({k: routine[k] for k in tp.ROUTINE_KEYS})
        order[("routine", routine["key"])] = ("routines", index)
    return {"cards": cards, "skills": skills, "routines": routines}, notes, order


def _words_checked(template: dict, order: dict, confirm: bool) -> None:
    """Hold every word of the new template to ``memory_rules.check_text``: a refusal is a 400, a warning needs ``confirm_warning``. The answer
    names the place and the field and never the words."""
    warn: list = []
    items: list = []
    for finding in tp.warnings_of(template):
        kind, index = order[(finding["kind"], finding["key"])]
        if finding["refuse"]:
            raise ApiError(400, "template_refused", f"第 {index + 1} 個{PLACE_WORD[kind]}的{FIELD_WORD[finding['field']]}"
                           f"{REFUSE_SAVE_TEXT[finding['refuse']]}，不能存進團隊範本。",
                           kind=kind, index=index, field=finding["field"], refuse=finding["refuse"])
        warn += [w for w in finding["warn"] if w not in warn]
        items.append({"kind": kind, "index": index, "field": finding["field"], "warn": list(finding["warn"])})
    if warn and not confirm:
        raise ApiError(409, "confirm_warning", SAVE_WARN_TEXT[warn[0]], warn=warn, warn_text=[SAVE_WARN_TEXT[w] for w in warn], items=items)


def _name_checked(name: str, confirm: bool) -> list:
    """The refusal or the warnings of a template's own name (ApiError 400 when refused); the warnings, to be added to the others."""
    got = memory_rules.check_text(name, tp.NAME_MAX, multiline=False)
    if got["refuse"]:
        raise ApiError(400, "template_refused", f"團隊範本的名稱{REFUSE_SAVE_TEXT[got['refuse']]}，不能這樣取名。",
                       kind="template", index=0, field="name", refuse=got["refuse"])
    if got["warn"] and not confirm:
        raise ApiError(409, "confirm_warning", SAVE_WARN_TEXT[got["warn"][0]], warn=list(got["warn"]),
                       warn_text=[SAVE_WARN_TEXT[w] for w in got["warn"]], items=[{"kind": "template", "index": 0, "field": "name", "warn": list(got["warn"])}])
    return got["warn"]


# ---- the person's changes (called from the browser's routes only) ---------------------------------------------------------------

def save_mine(body, *, cards, skills, routines, now: float | None = None) -> dict:
    """Save a copy as a new team template of the person's own. ``body``: ``{name, cards?, skills?, routines?, confirm_warning?}``; each row of
    the three lists is ``{"from": {template, key}}`` (an item of a built-in or an own template) or ``{"profile_id" | "skill_id" | "routine_id"}``
    (what the person has now: ``cards`` are the role cards as stored, ``skills`` the skills as ``skillbook.view`` lists them, ``routines`` the
    routines as ``routines.read_routines`` lists them). ``{"template", "notes"}``, or ApiError: bad_request (400), template_refused (400, with
    ``kind``, ``index``, ``field``, ``refuse``), not_found (404), confirm_warning (409, with ``warn`` and ``items``), template_too_big (409),
    mine_full (409) or templates_unreadable (503)."""
    name, rows, confirm = _check_request(body)
    current, readable, _ = read_mine()
    if not readable:
        raise _unreadable()
    try:
        templates = tp.index(current)
    except ValueError:
        raise _unreadable() from None
    new, notes, order = _assemble(rows, templates, {"cards": list(cards), "skills": list(skills), "routines": list(routines)})
    for kind in tp.KINDS:
        if len(new[kind]) > tp.MAX_PER_TEMPLATE[kind]:
            raise ApiError(409, "template_too_big", f"一個團隊範本最多 {tp.MAX_PER_TEMPLATE[kind]} 個{PLACE_WORD[kind]}，"
                           f"請少選 {len(new[kind]) - tp.MAX_PER_TEMPLATE[kind]} 個。", kind=kind, over=len(new[kind]) - tp.MAX_PER_TEMPLATE[kind])
    template = {"id": "tm-" + "0" * 12, "name": name, "builtin": False, **new}
    bad = tp.template_problem(template, builtin=False)
    if bad:
        raise _bad(bad)
    _name_checked(name, confirm)
    _words_checked(template, order, confirm)
    stamp = time.time() if now is None else now
    try:
        _folder(True)
        with mine_store.locked():
            saved = _read()
            if len(saved) >= tp.MAX_MINE:
                raise ApiError(409, "mine_full", f"你存的團隊範本滿了（最多 {tp.MAX_MINE} 個），請先刪掉幾個。")
            ids = {t["id"] for t in saved} | set(templates_builtin.BUILTIN_IDS)
            template["id"] = "tm-" + secrets.token_hex(6)
            while template["id"] in ids:
                template["id"] = "tm-" + secrets.token_hex(6)
            mine_store.save({"v": SCHEMA, "templates": saved + [template]})
            _log("saved_mine", template["id"], {kind: len(new[kind]) for kind in tp.KINDS}, stamp)
    except (StoreError, OSError):
        raise _unreadable() from None
    return {"template": copy.deepcopy(template), "notes": notes}


def rename_mine(template_id, body, now: float | None = None) -> dict:
    """Change the name of one of the person's own team templates (``{name, confirm_warning?}``). Nothing else of it can be changed: to change
    what is in it, save a new one. ``{"template"}``, or ApiError: bad_request, template_refused (400), not_found (404), confirm_warning (409),
    templates_unreadable (503)."""
    if not isinstance(body, dict) or "name" not in body or set(body) - {"name", "confirm_warning"}:
        raise _bad("只接受 name 與 confirm_warning，而且要有 name。")
    confirm = _confirm_flag(body)
    name = _name_of(body)
    probe = {"id": "tm-" + "0" * 12, "name": name, "builtin": False, "cards": [], "skills": [{"key": "a", "name": "a", "text": "a"}], "routines": []}
    if tp.template_problem(probe, builtin=False):       # the name is the only thing of the probe that can be wrong
        raise _bad(f"團隊範本的名稱要 1 到 {tp.NAME_MAX} 個字、只能一行、頭尾不能有空白。")
    _name_checked(name, confirm)
    try:
        _folder(True)
        with mine_store.locked():
            saved = _read()
            found = next((t for t in saved if t["id"] == template_id), None) if isinstance(template_id, str) else None
            if found is None:
                raise ApiError(404, "not_found", "找不到這個團隊範本。")
            renamed = dict(found, name=name)
            mine_store.save({"v": SCHEMA, "templates": [renamed if t["id"] == template_id else t for t in saved]})
            _log("renamed_mine", template_id, None, now)
    except (StoreError, OSError):
        raise _unreadable() from None
    return {"template": copy.deepcopy(renamed)}


def delete_mine(template_id, body, now: float | None = None) -> dict:
    """Delete one of the person's own team templates. Only the template goes: what was made from it, and what it was made from, stay.
    ``{"deleted": id}``, or ApiError: bad_request (a body that is not empty), not_found (404), templates_unreadable (503)."""
    if body != {}:
        raise _bad("這個動作不需要內容。")
    try:
        _folder(True)
        with mine_store.locked():
            saved = _read()
            if not (isinstance(template_id, str) and any(t["id"] == template_id for t in saved)):
                raise ApiError(404, "not_found", "找不到這個團隊範本。")
            mine_store.save({"v": SCHEMA, "templates": [t for t in saved if t["id"] != template_id]})
            _log("deleted_mine", template_id, None, now)
    except (StoreError, OSError):
        raise _unreadable() from None
    return {"deleted": template_id}
