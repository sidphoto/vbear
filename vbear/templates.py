"""Team templates (團隊範本, P45-1, ADR 0011): what a template is, how a selection becomes a plan, and the bodies the ordinary write
functions are given. Pure: no file, no clock, no process, no network, and nothing here writes anything.

A team template is a set of ready-made employees (role cards), skills and routines. The person ticks the ones they want, from one
template or from several, looks at the preview, and presses 套用; VBear (the console, in ``server.py``, P45-2) then makes them one by one with the
write functions that the person's own presses use. This module is the part before that: it never calls those functions. It only
makes what they would be given, and says what would happen.

    {id, name, about, builtin,
     cards:    [{key, name, position, instructions, claude_model}],
     skills:   [{key, name, text}],
     routines: [{key, name, text, days, times, who}]}

The four built-in ones are in ``templates_builtin.py``; the person's own (P45-3) are kept by ``templates_mine.py`` and handed in as
dicts of this shape. A template has no way to say a tool, full mode, a skill card, a profession, a permission, whether something is
switched on, memory, the shared folder, a chat or an id: the shape is closed, so such a field makes the whole template unusable. What the
bodies add is fixed here: a card is made in safe mode with no skill card (``card_body``), a routine is made switched off
(``routine_body``), a skill is made as a typed one (``skill_body``).

The numbers of the skills, the routines and the cards are written again here (this module may not import ``skillbook`` or
``routine_rules``); tests/test_templates_plan.py keeps them equal to the originals.
"""

from __future__ import annotations

import copy
import re
import unicodedata

from . import agent_profiles, model_options, templates_builtin
from .runtime import memory_rules

TOOLS = ("claude", "codex")                                  # the two tools that can chat; one is chosen for the whole apply
POSITIONS = agent_profiles.POSITIONS
CLAUDE_MODELS = model_options.CLAUDE_ALIASES
BUILTIN_IDS = templates_builtin.BUILTIN_IDS

NAME_MAX = 40
ABOUT_MAX = 120
TEXT_MAX = 4000                  # a skill's words, a routine's words
INSTRUCTIONS_MAX = 2000          # a card's standing instructions
MAX_CARDS = 500                  # the role cards a person can have
MAX_SKILLS = 100
MAX_ROUTINES = 20
MAX_TIMES = 3
MIN_GAP_MIN = 60
MAX_MINE = 20                    # the person's own team templates
MAX_PER_TEMPLATE = {"cards": 12, "skills": 24, "routines": 12}
MAX_PER_APPLY = {"cards": 12, "skills": 24, "routines": 12}
HEAD_CHARS = 80                  # how much of a card's instructions the preview shows

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}\Z")
MINE_ID_RE = re.compile(r"^tm-[0-9a-f]{12}\Z")
PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)\Z")

KINDS = ("cards", "skills", "routines")
KIND_WORD = {"cards": "員工", "skills": "技能", "routines": "例行工作"}
KIND_ONE = {"cards": "card", "skills": "skill", "routines": "routine"}
ONE_WORD = {"card": "員工", "skill": "技能", "routine": "例行工作"}
CARD_KEYS = ("key", "name", "position", "instructions", "claude_model")
SKILL_KEYS = ("key", "name", "text")
ROUTINE_KEYS = ("key", "name", "text", "days", "times", "who")
TEMPLATE_KEYS = ("id", "name", "builtin", "cards", "skills", "routines")      # + "about", which a saved one may leave out

# What a person who unticks nothing is told when a text of a saved template needs a second yes (the same two as the skills'; the
# words say 團隊範本, because they are shown over a preview).
WARN_TEXT = {
    "looks_like_order": ("這段看起來像在叫員工不問你就做事。團隊範本不會讓員工不問你就做事：員工一律用安全模式，"
                         "每個指令、每個檔案修改照舊都會問你。確定要用嗎？"),
    "personal": "這看起來有電話或地址。團隊範本的字套用後會成為員工的固定指示、技能或例行工作的內容，之後會跟著訊息送給 AI 公司。確定要用嗎？",
}
REFUSE_TEXT = {
    "bad_text": "格式不行（空的、太長、有看不見的字元，或含 VBear 的標記）",
    "secret_password": "有密碼或驗證碼",
    "secret_key": "有像金鑰或登入用代碼的東西",
    "secret_account": "有帳號或 email",
    "secret_payment": "有卡號、身分證字號或銀行帳號",
}
FIELD_WORD = {"name": "名稱", "instructions": "固定指示", "text": "內容"}


# ---- the shape of a template ------------------------------------------------------------------------------------------------------

def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _minutes(value):
    found = TIME_RE.match(value) if isinstance(value, str) else None
    return int(found.group(1)) * 60 + int(found.group(2)) if found else None


def _odd_char(ch: str, allow_lines: bool) -> bool:
    if allow_lines and ch in "\n\t":
        return False
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp")


def _line_problem(value, limit: int) -> bool:
    """True when ``value`` is not a name: text of 1 to ``limit`` characters, trimmed, one line, no control or format character."""
    return not (isinstance(value, str) and 1 <= len(value) <= limit and value == value.strip()
                and not any(_odd_char(ch, False) for ch in value))


def _text_problem(value, limit: int) -> bool:
    """True when ``value`` is not words: 1 to ``limit`` characters, trimmed, lines and tabs allowed, no other control or format character."""
    return not (isinstance(value, str) and 1 <= len(value) <= limit and value == value.strip()
                and not any(_odd_char(ch, True) for ch in value))


def _instructions_problem(value) -> bool:
    if not (isinstance(value, str) and 1 <= len(value) <= INSTRUCTIONS_MAX):
        return True
    try:
        return agent_profiles.clean_instructions(value) != value
    except ValueError:
        return True


def _item_shape(item, keys, kind: str, index: int):
    where = f"第 {index + 1} 個{KIND_WORD[kind]}"
    if not isinstance(item, dict) or set(item) != set(keys):
        return f"{where}只能有這些欄位：" + "、".join(keys)
    if not (isinstance(item["key"], str) and KEY_RE.match(item["key"])):
        return f"{where}的 key 要是小寫英文字母開頭、最多 24 個字的英數字與底線"
    if _line_problem(item["name"], NAME_MAX):
        return f"{where}的名稱要 1 到 {NAME_MAX} 個字、只能一行、頭尾不能有空白"
    return None


def _card_problem(card, index: int):
    bad = _item_shape(card, CARD_KEYS, "cards", index)
    if bad:
        return bad
    where = f"第 {index + 1} 位員工"
    if card["position"] is not None and card["position"] not in POSITIONS:
        return f"{where}的職位不是 VBear 認得的職位"
    if card["instructions"] is not None and _instructions_problem(card["instructions"]):
        return f"{where}的固定指示要 1 到 {INSTRUCTIONS_MAX:,} 個字、頭尾不能有空白、不能有看不見的字元（或是 null）"
    if card["claude_model"] is not None and card["claude_model"] not in CLAUDE_MODELS:
        return f"{where}的模型只能是 " + "、".join(CLAUDE_MODELS) + " 或 null"
    return None


def _skill_problem(skill, index: int):
    bad = _item_shape(skill, SKILL_KEYS, "skills", index)
    if bad:
        return bad
    if _text_problem(skill["text"], TEXT_MAX):
        return f"第 {index + 1} 個技能的內容要 1 到 {TEXT_MAX:,} 個字、頭尾不能有空白、不能有看不見的字元"
    return None


def _routine_problem(routine, index: int, card_keys):
    bad = _item_shape(routine, ROUTINE_KEYS, "routines", index)
    if bad:
        return bad
    where = f"第 {index + 1} 件例行工作"
    if _text_problem(routine["text"], TEXT_MAX):
        return f"{where}的內容要 1 到 {TEXT_MAX:,} 個字、頭尾不能有空白、不能有看不見的字元"
    days = routine["days"]
    if not (isinstance(days, list) and days and all(_is_int(d) and 0 <= d <= 6 for d in days)
            and all(a < b for a, b in zip(days, days[1:]))):
        return f"{where}的 days 要是 0 到 6 的整數（星期一是 0），至少一天，由小到大、不能重複"
    times = routine["times"]
    if not (isinstance(times, list) and 1 <= len(times) <= MAX_TIMES and all(_minutes(t) is not None for t in times)
            and all(a < b for a, b in zip(times, times[1:]))):
        return f"{where}的 times 要是 1 到 {MAX_TIMES} 個 HH:MM，由早到晚、不能重複"
    mins = [_minutes(t) for t in times]
    for i, a in enumerate(mins):
        for b in mins[i + 1:]:
            if min(abs(a - b), 1440 - abs(a - b)) < MIN_GAP_MIN:
                return f"{where}的時間要彼此至少差 {MIN_GAP_MIN} 分鐘"
    if routine["who"] is not None and routine["who"] not in card_keys:
        return f"{where}交給的員工要是這個團隊範本裡的一位（或是 null）"
    return None


def template_problem(template, *, builtin: bool):
    """None when ``template`` is a team template of the closed shape above (``builtin``: one of the four VBear ships, else one the
    person saved), else one sentence on what is wrong. The sentence never holds a word of the template. This checks the shape only; what
    the words say (``memory_rules``) is looked at when they are used (``warnings_of``)."""
    if not isinstance(template, dict):
        return "團隊範本必須是一個物件"
    keys = set(template)
    if not set(TEMPLATE_KEYS) <= keys <= set(TEMPLATE_KEYS) | {"about"}:
        return "團隊範本只能有這些欄位：" + "、".join(TEMPLATE_KEYS) + "，另可有 about"
    if template["builtin"] is not builtin:
        return "團隊範本的 builtin 與它的來源不符"
    tid = template["id"]
    if builtin:
        if tid not in BUILTIN_IDS:
            return "內建團隊範本的 id 不是 VBear 內建的四個之一"
        if "about" not in template:
            return "內建團隊範本要有 about"
    elif not (isinstance(tid, str) and MINE_ID_RE.match(tid)):
        return "團隊範本的 id 格式不符"
    if _line_problem(template["name"], NAME_MAX):
        return f"團隊範本的名稱要 1 到 {NAME_MAX} 個字、只能一行、頭尾不能有空白"
    if "about" in template and not (isinstance(template["about"], str) and len(template["about"]) <= ABOUT_MAX
                                    and not any(_odd_char(ch, False) for ch in template["about"])):
        return f"團隊範本的說明最多 {ABOUT_MAX} 個字、只能一行"
    for kind in KINDS:
        if not isinstance(template[kind], list):
            return f"團隊範本的 {kind} 必須是陣列"
        if len(template[kind]) > MAX_PER_TEMPLATE[kind]:
            return f"一個團隊範本最多 {MAX_PER_TEMPLATE[kind]} 個{KIND_WORD[kind]}"
        keys_seen = [x.get("key") for x in template[kind] if isinstance(x, dict)]
        if len(keys_seen) != len(set(map(str, keys_seen))):
            return f"同一個團隊範本裡的{KIND_WORD[kind]}，key 不能重複"
    if not (template["cards"] or template["skills"] or template["routines"]):
        return "團隊範本至少要有一項"
    for i, card in enumerate(template["cards"]):
        bad = _card_problem(card, i)
        if bad:
            return bad
    for i, skill in enumerate(template["skills"]):
        bad = _skill_problem(skill, i)
        if bad:
            return bad
    card_keys = {c["key"] for c in template["cards"]}
    for i, routine in enumerate(template["routines"]):
        bad = _routine_problem(routine, i, card_keys)
        if bad:
            return bad
    return None


def warnings_of(template, picked=None):
    """What ``memory_rules.check_text`` says of the words of a template (or of the ``picked`` items of it, a set of (kind, key) with the kind
    one of "card", "skill", "routine"): a list of {kind, key, field, refuse, warn}, one for each word that is refused or needs a second yes.
    The built-in four have none (tests/test_templates_builtin.py)."""
    found = []

    def look(kind, item, field, text, limit, multiline):
        if text is None or (picked is not None and (kind, item["key"]) not in picked):
            return
        got = memory_rules.check_text(text, limit, multiline=multiline)
        if got["refuse"] or got["warn"]:
            found.append({"kind": kind, "key": item["key"], "field": field, "refuse": got["refuse"], "warn": list(got["warn"])})

    for c in template["cards"]:
        look("card", c, "name", c["name"], NAME_MAX, False)
        look("card", c, "instructions", c["instructions"], INSTRUCTIONS_MAX, True)
    for s in template["skills"]:
        look("skill", s, "name", s["name"], NAME_MAX, False)
        look("skill", s, "text", s["text"], TEXT_MAX, True)
    for r in template["routines"]:
        look("routine", r, "name", r["name"], NAME_MAX, False)
        look("routine", r, "text", r["text"], TEXT_MAX, True)
    return found


# ---- the templates ----------------------------------------------------------------------------------------------------------------

def catalog(mine=()):
    """{"builtin": [the four], "mine": [the person's own]}, as copies a caller may keep. ``mine`` is what ``templates_mine`` read (P45-3);
    until then there is none."""
    return {"builtin": templates_builtin.builtin(), "mine": [copy.deepcopy(t) for t in mine]}


def index(mine=()):
    """{id: template} of the built-in four and the person's own. ValueError when one is not a team template, or when two share an id."""
    out = {}
    for template in templates_builtin.builtin():
        out[template["id"]] = template
    for template in mine:
        bad = template_problem(template, builtin=False)
        if bad:
            raise ValueError(bad)
        if template["id"] in out:
            raise ValueError("兩個團隊範本用了同一個 id")
        out[template["id"]] = copy.deepcopy(template)
    return out


# ---- the AI tools -----------------------------------------------------------------------------------------------------------------

def _tool_state(tool: str, row):
    name = {"claude": "Claude Code", "codex": "Codex"}[tool]
    if not isinstance(row, dict):
        return {"ready": False, "why": f"開始設定頁沒有列出 {name}，讀不到它的狀態。"}
    if row.get("state") == "not_installed" or row.get("installed") is False:
        return {"ready": False, "why": f"這台電腦找不到 {name}。"}
    if row.get("ready") is not True:
        return {"ready": False, "why": f"{name} 還沒登入。"}
    if tool == "codex":
        chat = row.get("chat_login")
        if not (isinstance(chat, dict) and chat.get("state") == "logged_in"):
            return {"ready": False, "why": "聊天用的 Codex 登入還沒完成，Codex 的員工要先到開始設定頁登入才能聊天。"}
    return {"ready": True, "why": ""}


def tools_view(rows):
    """{"claude": {ready, why}, "codex": {ready, why}, "default": "claude" | "codex"} from the rows of the start-up page
    (``ai_tool_status.report``): the same source, read and not asked again. Codex counts as ready only when the Codex that chats (its own login) is
    logged in. The default is Claude Code unless it is not ready and Codex is."""
    by_id = {r.get("id"): r for r in rows if isinstance(r, dict)} if isinstance(rows, (list, tuple)) else {}
    claude, codex = _tool_state("claude", by_id.get("claude")), _tool_state("codex", by_id.get("codex"))
    return {"claude": claude, "codex": codex, "default": "codex" if (not claude["ready"] and codex["ready"]) else "claude"}


# ---- the bodies for the ordinary write functions ------------------------------------------------------------------------------------

def card_body(card, tool, name=None):
    """What ``POST /api/agent-profiles`` is given for one employee of a template: always safe mode, never a skill card, no profession, the
    permission records of the starter deck, the model of the template for Claude Code and Codex's own for Codex. No ``enabled`` key (a new card
    is switched on)."""
    if tool not in TOOLS:
        raise ValueError("tool 只能是 claude 或 codex")
    model_id = card["claude_model"] if tool == "claude" and card["claude_model"] else ""
    return {
        "name": card["name"] if name is None else name,
        "position": card["position"],
        "instructions": card["instructions"],
        "launch_mode": "safe",
        "model": {"tool": tool, "model_id": model_id},
        "equipped_skill_ids": [],
        "permission_intents": dict(agent_profiles.VERIFIED_INTENTS),
        "profession_role_id": None,
    }


def skill_body(skill):
    """What ``skillbook.add`` is given: a name and the words. No source, so it is kept as a typed one (the file's closed list of sources
    has no new value)."""
    return {"name": skill["name"], "text": skill["text"]}


def routine_body(routine, profile_id):
    """What ``routines.create`` is given: the six fields, switched off."""
    return {"name": routine["name"], "profile_id": profile_id, "text": routine["text"], "days": list(routine["days"]),
            "times": list(routine["times"]), "enabled": False}


# ---- the plan of a selection ------------------------------------------------------------------------------------------------------

def _plain_name(value):
    """The trimmed name, or None when it is not a name a card can have (empty, over 40, more than one line)."""
    text = value.strip()
    return None if _line_problem(text, NAME_MAX) else text


def _same(name) -> str:
    return unicodedata.normalize("NFKC", str(name or "")).strip().lower()


def _ref(value, templates, kind: str, what: str):
    """(ref, template, item) for ``{"template": id, "key": key}``; ValueError when it is not exactly that or names nothing."""
    if not (isinstance(value, dict) and set(value) == {"template", "key"} and isinstance(value["template"], str)
            and isinstance(value["key"], str)):
        raise ValueError(f"{what}的 from 要是 {{template, key}}")
    template = templates.get(value["template"])
    if template is None:
        raise ValueError("找不到這個團隊範本")
    bad = template_problem(template, builtin=template.get("builtin") is True) if isinstance(template, dict) else "x"
    if bad:
        raise ValueError(bad)
    item = next((x for x in template[kind] if x["key"] == value["key"]), None)
    if item is None:
        raise ValueError(f"這個團隊範本裡沒有這個{KIND_WORD[kind]}")
    return {"template": value["template"], "key": value["key"]}, template, item


def _request(body, templates):
    """The request, checked and with every ``from`` resolved. ValueError (zh) for anything that is not exactly the shape of the plan's API."""
    if not isinstance(body, dict):
        raise ValueError("請求內容必須是一個 JSON 物件")
    allowed = {"tool", "cards", "skills", "routines", "confirm_warning"}
    if set(body) - allowed:
        raise ValueError("只接受 " + "、".join(sorted(allowed)))
    if body.get("tool") not in TOOLS:
        raise ValueError("tool 只能是 claude 或 codex")
    confirm = body.get("confirm_warning", False)
    if not isinstance(confirm, bool):
        raise ValueError("confirm_warning 必須是 true 或 false")
    picked = {}
    for kind in KINDS:
        rows = body.get(kind, [])
        if not isinstance(rows, list):
            raise ValueError(f"{kind} 必須是陣列")
        if len(rows) > MAX_PER_APPLY[kind]:
            raise ValueError(f"一次最多套用 {MAX_PER_APPLY[kind]} 個{KIND_WORD[kind]}")
        picked[kind] = rows
    if not any(picked.values()):
        raise ValueError("至少要勾一項")
    out = {"tool": body["tool"], "confirm": confirm, "cards": [], "skills": [], "routines": []}
    seen = set()
    for kind in KINDS:
        allowed_keys = {"cards": {"from", "name"}, "skills": {"from"}, "routines": {"from", "to"}}[kind]
        for row in picked[kind]:
            if not isinstance(row, dict) or "from" not in row or set(row) - allowed_keys:
                raise ValueError(f"每個{KIND_WORD[kind]}只接受 " + "、".join(sorted(allowed_keys)))
            ref, template, item = _ref(row["from"], templates, kind, KIND_WORD[kind])
            if (kind, ref["template"], ref["key"]) in seen:
                raise ValueError(f"同一個{KIND_WORD[kind]}不能勾兩次")
            seen.add((kind, ref["template"], ref["key"]))
            entry = {"from": ref, "template": template, "item": item}
            if kind == "cards" and "name" in row:
                if not isinstance(row["name"], str):
                    raise ValueError("name 必須是文字")
                entry["name"] = row["name"]
            if kind == "routines" and "to" in row:
                entry["to"] = row["to"]
            out[kind].append(entry)
    ticked = {(e["from"]["template"], e["from"]["key"]) for e in out["cards"]}
    for entry in out["routines"]:
        if "to" not in entry:
            continue
        to = entry["to"]
        if not (isinstance(to, dict) and len(to) == 1 and set(to) <= {"card", "profile_id"}):
            raise ValueError("to 要是 {card: {template, key}} 或 {profile_id}")
        if "card" in to:
            ref, _, _ = _ref(to["card"], templates, "cards", "員工")
            if (ref["template"], ref["key"]) not in ticked:
                raise ValueError("例行工作只能交給這次勾的員工，或你現在能聊天的員工")
            entry["to"] = {"card": ref}
        elif not (isinstance(to["profile_id"], str) and PROFILE_RE.match(to["profile_id"])):
            raise ValueError("profile_id 必須是員工的識別碼")
    return out


def _gone(now: int, add: int, limit: int) -> int:
    return max(0, now + add - limit)


def plan(body, *, templates, current):
    """The plan of a selection: what would be made, for whom, and what stops it. ``body`` is the request of ``POST /api/templates/preview`` and of
    ``/apply`` (the same), ``templates`` is ``index(...)``, ``current`` is
    ``{"cards": [{id, name, can_chat}], "skills": number, "routines": number}``: what the person has now. ValueError (zh) when the request
    is not well-formed (an unknown template, the same item twice, more than one apply holds); everything else the person can still fix is
    a problem in the answer, which is {tool, cards, skills, routines, warn_text, choices, after, notes, warn_items, problems, ok}. Each card has ``body``
    and each routine has ``routine`` (the template's own routine, to be given ``routine_body`` once its employee has an id): ``public`` drops
    them for the screen. Nothing given is changed."""
    req = _request(body, templates)
    tool = req["tool"]
    existing = [c for c in current["cards"] if isinstance(c, dict)]
    problems = []

    cards = []
    for entry in req["cards"]:
        item = entry["item"]
        asked = entry.get("name", item["name"])
        name = _plain_name(asked)
        if name is None:
            problems.append({"code": "bad_name", "text": "員工的名字要 1 到 40 個字、只能一行。", "from": entry["from"]})
            name = asked.strip()
        instr = item["instructions"]
        cards.append({"from": entry["from"], "name": name, "default_name": item["name"], "position": item["position"],
                      "claude_model": item["claude_model"], "model_id": item["claude_model"] if tool == "claude" and item["claude_model"] else "",
                      "instructions_head": instr[:HEAD_CHARS] if instr else "", "instructions_cut": bool(instr) and len(instr) > HEAD_CHARS,
                      "same_in_batch": False, "same_existing": False,
                      "body": card_body(item, tool, name)})
    by_name = {}
    for c in cards:
        by_name.setdefault(_same(c["name"]), []).append(c)
    notes = []
    for group in by_name.values():
        if len(group) > 1 and _same(group[0]["name"]):
            for c in group:
                c["same_in_batch"] = True
            notes.append({"code": "same_name_batch", "name": group[0]["name"], "count": len(group),
                          "text": f"這次有 {len(group)} 位叫「{group[0]['name']}」，只是提醒。"})
    for c in cards:
        match = next((e for e in existing if _same(e.get("name")) == _same(c["name"]) and _same(c["name"])), None)
        if match is not None:
            c["same_existing"] = True
            notes.append({"code": "same_name_existing", "name": c["name"], "text": f"你已經有一位叫「{c['name']}」，只是提醒。"})

    skills = [{"from": e["from"], "name": e["item"]["name"], "body": skill_body(e["item"])} for e in req["skills"]]

    ticked = {(c["from"]["template"], c["from"]["key"]): c for c in cards}
    chatters = [{"profile_id": e["id"], "name": e.get("name")} for e in existing if e.get("can_chat") is True and isinstance(e.get("id"), str)]
    routines = []
    for entry in req["routines"]:
        item, tid = entry["item"], entry["from"]["template"]
        assignee = {"kind": None, "card": None, "profile_id": None, "name": None}
        to = entry.get("to")
        if to is None:
            who = item["who"]
            card = ticked.get((tid, who)) if who else None
            if card is not None:
                assignee = {"kind": "card", "card": dict(card["from"]), "profile_id": None, "name": card["name"]}
            else:
                problems.append({"code": "no_assignee", "from": entry["from"], "text": f"例行工作「{item['name']}」還沒有交給任何員工，請在預覽裡選一位。"})
        elif "card" in to:
            card = ticked[(to["card"]["template"], to["card"]["key"])]
            assignee = {"kind": "card", "card": dict(card["from"]), "profile_id": None, "name": card["name"]}
        else:
            found = next((e for e in existing if e.get("id") == to["profile_id"]), None)
            if found is not None and found.get("can_chat") is True:
                assignee = {"kind": "existing", "card": None, "profile_id": to["profile_id"], "name": found.get("name")}
            else:
                problems.append({"code": "assignee_cannot_chat", "from": entry["from"],
                                 "text": f"例行工作「{item['name']}」交給的員工現在不能聊天（找不到，或已停用），請換一位。"})
        routines.append({"from": entry["from"], "name": item["name"], "days": list(item["days"]), "times": list(item["times"]),
                         "assignee": assignee, "routine": copy.deepcopy(item)})

    now = {"cards": len(existing), "skills": int(current["skills"]), "routines": int(current["routines"])}
    add = {"cards": len(cards), "skills": len(skills), "routines": len(routines)}
    limit = {"cards": MAX_CARDS, "skills": MAX_SKILLS, "routines": MAX_ROUTINES}
    unit = {"cards": ("角色卡", "張"), "skills": ("技能", "個"), "routines": ("例行工作", "件")}
    after = {}
    for kind in KINDS:
        after[kind] = {"now": now[kind], "add": add[kind], "after": now[kind] + add[kind], "max": limit[kind]}
        over = _gone(now[kind], add[kind], limit[kind])
        if over:
            word, counter = unit[kind]
            problems.append({"code": "template_full", "kind": kind, "over": over,
                             "text": (f"{word}會超過 {limit[kind]} {counter}：你現在有 {now[kind]} {counter}，"
                                      f"這次要加 {add[kind]} {counter}，請少勾 {over} {counter}。")})

    warn_items = []
    seen_templates = {}
    for entries in (req["cards"], req["skills"], req["routines"]):
        for e in entries:
            seen_templates.setdefault(e["from"]["template"], e["template"])
    for tid, template in seen_templates.items():
        wanted = {(KIND_ONE[k], e["from"]["key"]) for k in KINDS for e in req[k] if e["from"]["template"] == tid}
        for finding in warnings_of(template, wanted):
            ref = {"template": tid, "key": finding["key"]}
            if finding["refuse"]:
                problems.append({"code": "refused", "kind": finding["kind"], "from": ref, "field": finding["field"], "refuse": finding["refuse"],
                                 "text": f"{ONE_WORD[finding['kind']]}的{FIELD_WORD[finding['field']]}"
                                         f"{REFUSE_TEXT[finding['refuse']]}，不能用團隊範本建立。"})
            if finding["warn"]:
                row = next((w for w in warn_items if w["kind"] == finding["kind"] and w["from"] == ref), None)
                if row is None:
                    warn_items.append({"kind": finding["kind"], "from": ref, "warn": list(finding["warn"])})
                else:
                    row["warn"] += [w for w in finding["warn"] if w not in row["warn"]]
    if warn_items and not req["confirm"]:
        codes = []
        for w in warn_items:
            codes += [c for c in w["warn"] if c not in codes]
        problems.append({"code": "confirm_warning", "warn": codes, "items": copy.deepcopy(warn_items), "text": WARN_TEXT[codes[0]],
                         "warn_text": [WARN_TEXT[c] for c in codes]})

    warn_codes = []
    for w in warn_items:
        warn_codes += [c for c in w["warn"] if c not in warn_codes]
    return {"tool": tool, "cards": cards, "skills": skills, "routines": routines, "warn_text": {c: WARN_TEXT[c] for c in warn_codes},
            "choices": {"cards": [{"template": c["from"]["template"], "key": c["from"]["key"], "name": c["name"]} for c in cards],
                        "existing": chatters},
            "after": after, "notes": notes, "warn_items": warn_items, "problems": problems, "ok": not problems}


def public(planned):
    """The plan as the screen is sent it: no body of a card or a skill, no routine to give to ``routine_body``."""
    shown = copy.deepcopy(planned)
    for c in shown["cards"]:
        c.pop("body", None)
    for s in shown["skills"]:
        s.pop("body", None)
    for r in shown["routines"]:
        r.pop("routine", None)
    return shown
