"""Staffing meetings (P35-1): the pure part of asking the CEO to staff a task card, after the staff have spoken.

A staffing meeting is held like a meeting, by headless calls with no tools (the runner comes later, on board_engine):
each suggested speaker says once, alone, which abilities the task needs, which card fits which place, which skills to
insert and what is missing; then the CEO writes a staffing proposal from what they said. Nothing here runs a program,
and nothing here, or in a proposal, creates a card, inserts a skill or puts anyone on a team: every step is a person's.

What this module holds:

  * the list both kinds of turn are given (build_inputs): the role cards and the skills a card can use, each under an
    alias (C1..C40, S1..S120) given once, so that no real id leaves the console and a model can only point at what is
    on the list. A speaker gets a short view of it (speaker_view), the CEO the whole of it (full_view);
  * who VBear suggests to speak, by a fixed table (SUGGEST_SPEAKERS), with the reason for each;
  * what a speaker and the CEO may write (STAFF_OPINION_SCHEMA, PROPOSAL_SCHEMA) and how it is checked, in three levels:
    what is not the schema voids the whole answer (mt.OutputError, the turn fails and may be retried); what points at
    nothing on the list or cannot fit is taken out and said (a note); what is allowed but needs the person's eye is
    kept and flagged, and a flagged item is not ticked in advance. A legal manager's risk without a source is kept with
    the sentence that says so; it is shown, and no rule of the meetings (R1-R8) is run on any of it.

Disabled cards are on the list, marked: a disabled card cannot speak, but the CEO may propose it, and enabling it is
one more step of the person's.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from . import agent_profiles as ap, categories as cats, meeting_rules as rules, meetings as mt, model_options, position_guide
from . import skill_fit
from .board_engine import SPEAKER_POSITIONS
from .runtime import agent_sessions, cli_versions

MAX_CARDS, MAX_SKILLS, MAX_SPEAKER_SKILLS = 40, 120, 40
LIST_MAX = 40 * 1024  # the CEO's list of cards and skills, as JSON
NAME_MAX, MODEL_MAX, HEAD_MAX, LINE_MAX = 80, 200, 120, 60
CATEGORY_IDS = tuple(c["id"] for c in cats.CATEGORIES)
CATEGORY_LABELS = {c["id"]: c["label"] for c in cats.CATEGORIES}
POSITION_LABELS = {row["id"]: row["label"] for row in ap.POSITION_TABLE}
TASK_TEXT_FIELDS = ("title", "goal", "scope", "deliverables")


# ---- the task ------------------------------------------------------------------------------------------------------

def _words(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(v for v in value if isinstance(v, str))
    return ""


def task_text(task) -> str:
    """The words of a task card VBear reads for its categories and its amounts: the title, the goal, the scope and the
    deliverables. Not what is out of scope (a template's says 「未授權變更」), not the folder."""
    if not isinstance(task, dict):
        return ""
    return "\n".join(_words(task.get(k)) for k in TASK_TEXT_FIELDS)


def task_categories(task) -> list[dict]:
    """The categories of a task card by the skills' keyword table ({id, label, keyword}), derived, not claimed."""
    if not isinstance(task, dict):
        return []
    return cats.categorize(_words(task.get("title")), "\n".join(_words(task.get(k)) for k in TASK_TEXT_FIELDS[1:]), "")


# ---- the cards and the skills --------------------------------------------------------------------------------------

def can_start(profile) -> str:
    """Whether VBear can start this card: "full" (in full mode), "safe" (in safe mode, on a version that passes the
    check), or "no" (VBear does not start this tool in this mode; the card is a record for the team)."""
    tool = (profile.get("model") or {}).get("tool") if isinstance(profile, dict) else None
    if ap.effective_launch_mode(profile) == "full":
        return "full" if tool in agent_sessions.FULL_ENGINES else "no"
    if tool == "claude" or (tool == "codex" and cli_versions.CODEX_INTERACTIVE_FLAGS_SUPPORTED):
        return "safe"
    return "no"


def _suggested_categories(position) -> list[str]:
    return list(position_guide.GUIDE[position]["skill_categories"]) if position in position_guide.GUIDE else []


def _updated(profile: dict) -> float:
    value = profile.get("updated_at")
    return float(value) if type(value) in (int, float) else 0.0


def _card(profile: dict) -> dict:
    model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
    tool = model.get("tool") if isinstance(model.get("tool"), str) else ""
    model_id = model.get("model_id")
    instructions = ap.instructions_of(profile)
    equipped = profile.get("equipped_skill_ids")
    return {"profile_id": profile["id"], "revision": ap.profile_digest(profile),
            "name": str(profile.get("name") or "")[:NAME_MAX], "position": ap.position_of(profile), "tool": tool,
            "family": ap.family_of_tool(tool), "model_id": model_id[:MODEL_MAX] if isinstance(model_id, str) else "",
            "launch_mode": ap.effective_launch_mode(profile), "can_start": can_start(profile),
            "enabled": profile.get("enabled") is not False,
            "equipped_ids": [s for s in equipped if isinstance(s, str)] if isinstance(equipped, list) else [],
            "instructions": {"source": instructions["source"], "head": (instructions["text"] or "")[:HEAD_MAX]}}


def _skill(skill: dict, summaries: dict) -> dict:
    summary = summaries.get(skill.get("skill_id"))
    excerpt = skill.get("excerpt") if isinstance(skill.get("excerpt"), str) else ""
    found = skill.get("categories") if isinstance(skill.get("categories"), list) else []
    return {"skill_id": skill["skill_id"], "name": str(skill.get("name") or "")[:NAME_MAX],
            "invoke_name": str(skill.get("invoke_name") or "")[:NAME_MAX],
            "categories": [c for c in CATEGORY_IDS if c in found], "fits": skill_fit.fits(skill),
            "line": (summary if isinstance(summary, str) and summary.strip() else excerpt).strip()[:LINE_MAX],
            "line_source": "中文摘要" if isinstance(summary, str) and summary.strip() else "原文"}


def _equip(card: dict, aliases: dict[str, str]) -> dict:
    """The card with the skills it carries that are on the list, by their aliases, and how many others it carries."""
    equipped = [aliases[s] for s in card["equipped_ids"] if s in aliases]
    return {**card, "equipped": equipped, "equipped_unlisted": len(card["equipped_ids"]) - len(equipped)}


def _card_out(card: dict) -> dict:
    """A card as the CEO is given it: its alias, never its id or revision."""
    return {"alias": card["alias"], "name": card["name"], "position": card["position"], "tool": card["tool"],
            "family": card["family"], "model_id": card["model_id"], "launch_mode": card["launch_mode"],
            "can_start": card["can_start"], "enabled": card["enabled"], "equipped": list(card["equipped"]),
            "equipped_unlisted": card["equipped_unlisted"], "instructions": dict(card["instructions"])}


def _skill_out(skill: dict) -> dict:
    return {k: skill[k] for k in ("alias", "name", "invoke_name", "categories", "fits", "line", "line_source")}


def _size(cards: list[dict], skills: list[dict]) -> int:
    aliases = {s["skill_id"]: s["alias"] for s in skills}
    view = {"cards": [_card_out(_equip(c, aliases)) for c in cards], "skills": [_skill_out(s) for s in skills]}
    return len(json.dumps(view, ensure_ascii=False).encode())


def _largest(count: int, fits) -> int:
    """The largest n in 0..count with fits(n), for a fits that holds up to some n and not after it (-1 when none)."""
    low, high = -1, count
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return low


def build_inputs(task, profiles, skills, *, summaries: dict | None = None) -> dict:
    """The one list a staffing meeting is given, in a fixed order (so the same cards, skills and task card give the same
    list, the same aliases and the same sha, in whatever order they come):

      cards   at most MAX_CARDS: the enabled ones first, then those whose position's suggested skill categories meet the
              task's categories most, then by name and id;
      skills  at most MAX_SKILLS of those a card of some camp can use (skill_fit.pick_listed, one per name of one tool):
              first those whose categories meet the task's or those suggested to the listed cards' positions, then the
              ones a listed card carries, then by name and id. A skill's line is the fresh Chinese summary when one is
              given (``summaries``, by skill id), else its author's own text, marked as such;

    and, for the whole of it, at most LIST_MAX bytes: skills go first from the end, then cards. What is left out is
    counted. The record keeps the real ids under the aliases (sent_of); a model is shown the aliases only."""
    summaries = summaries if isinstance(summaries, dict) else {}
    found = task_categories(task)
    wanted = {c["id"] for c in found}
    cards = [_card(p) for p in profiles if isinstance(p, dict) and isinstance(p.get("id"), str)]
    cards.sort(key=lambda c: (not c["enabled"], -len(wanted & set(_suggested_categories(c["position"]))), c["name"].casefold(),
                              c["profile_id"]))
    omitted_cards = max(len(cards) - MAX_CARDS, 0)
    cards = cards[:MAX_CARDS]

    picked: dict[str, dict] = {}
    for tool in ap.TOOL_ORDER:
        for s in skill_fit.pick_listed(skills, tool):
            if isinstance(s.get("skill_id"), str):
                picked.setdefault(s["skill_id"], s)
    near = wanted.union(*(_suggested_categories(c["position"]) for c in cards))
    equipped = {s for c in cards for s in c["equipped_ids"]}
    listed = [_skill(s, summaries) for s in picked.values()]
    listed.sort(key=lambda s: (0 if near & set(s["categories"]) else 1 if s["skill_id"] in equipped else 2,
                               s["name"].casefold(), s["skill_id"]))
    omitted_skills = max(len(listed) - MAX_SKILLS, 0)
    listed = listed[:MAX_SKILLS]
    for i, card in enumerate(cards):
        card["alias"] = f"C{i + 1}"
    for i, s in enumerate(listed):
        s["alias"] = f"S{i + 1}"

    keep = _largest(len(listed), lambda n: _size(cards, listed[:n]) <= LIST_MAX)
    if keep < 0:
        keep = 0
        kept_cards = max(_largest(len(cards), lambda n: _size(cards[:n], []) <= LIST_MAX), 0)
        omitted_cards += len(cards) - kept_cards
        cards = cards[:kept_cards]
    omitted_skills += len(listed) - keep
    listed = listed[:keep]
    aliases = {s["skill_id"]: s["alias"] for s in listed}
    cards = [_equip(c, aliases) for c in cards]

    task_part = {k: v for k, v in (mt.task_context(task) or {}).items() if k != "status"}
    inputs = {"categories": [c["id"] for c in found], "category_hits": found, "cards": cards, "skills": listed,
              "omitted": {"cards": omitted_cards, "skills": omitted_skills}}
    raw = json.dumps({"task": task_part, **inputs}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    inputs["inputs_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    return inputs


def full_view(inputs: dict) -> dict:
    """The list as the CEO is given it."""
    return {"cards": [_card_out(c) for c in inputs["cards"]], "skills": [_skill_out(s) for s in inputs["skills"]]}


def speaker_view(inputs: dict, position: str) -> dict:
    """The short list a speaker is given: every listed card without its instructions or its skills (only how many it
    carries; the accountant also sees each card's model), and only the listed skills whose categories meet the speaker's
    position's suggested ones or the task's, at most MAX_SPEAKER_SKILLS, without their lines. Every alias is the full
    list's."""
    keys = ("alias", "name", "position", "tool", "family", "enabled", "launch_mode", "can_start")
    cards = []
    for card in inputs["cards"]:
        out = {k: card[k] for k in keys}
        out["equipped_count"] = len(card["equipped_ids"])
        if position == "accountant":
            out["model_id"] = card["model_id"]
        cards.append(out)
    near = set(_suggested_categories(position)) | set(inputs["categories"])
    skills = [{k: s[k] for k in ("alias", "name", "categories", "fits")} for s in inputs["skills"] if near & set(s["categories"])]
    return {"cards": cards, "skills": skills[:MAX_SPEAKER_SKILLS]}


def sent_of(inputs: dict) -> dict:
    """What a record keeps of the list: under each alias the real id (and a card's revision and whether it was enabled),
    what was left out, and the sha of the whole."""
    return {"cards": [{"alias": c["alias"], "profile_id": c["profile_id"], "revision": c["revision"], "enabled": c["enabled"]}
                      for c in inputs["cards"]],
            "skills": [{"alias": s["alias"], "skill_id": s["skill_id"]} for s in inputs["skills"]],
            "omitted": dict(inputs["omitted"]), "inputs_sha256": inputs["inputs_sha256"]}


# ---- who VBear suggests to speak -----------------------------------------------------------------------------------

# A fixed table, read in this order; nothing here asks a model. `categories` are the task's categories that call the
# position; the legal manager's words of the plan (個資、授權、合約、著作權) are keywords of the "legal" category itself.
SUGGEST_SPEAKERS: tuple[dict[str, Any], ...] = (
    {"position": "pm", "categories": (), "always": True},
    {"position": "executor", "categories": ("frontend", "backend", "quality", "security", "ai"), "when_uncategorized": True},
    {"position": "legal", "categories": ("legal",)},
    {"position": "accountant", "categories": ("finance",), "amount": True},
    {"position": "social", "categories": ("writing", "media")},
    {"position": "art", "categories": ("design", "media")},
)


def _why(rule: dict, found: list[dict], amount: bool) -> str | None:
    label = POSITION_LABELS[rule["position"]]
    if rule.get("always"):
        return f"有 {label} 卡，負責講進度與分工"
    hits = [c for c in found if c["id"] in rule["categories"]]
    if hits:
        named = "、".join(f"「{c['label']}」（提到「{c['keyword']}」）" for c in hits)
        return f"任務分類有{named}，所以找{label}"
    if rule.get("amount") and amount:
        return f"任務文字出現金額，所以找{label}"
    if rule.get("when_uncategorized") and not found:
        return f"任務沒有分出任何分類，先找{label}"
    return None


def suggest_speakers(task, profiles) -> list[dict]:
    """[{profile_id, position, why}]: who VBear ticks for a staffing meeting on this task card, one enabled card per
    position (the one updated last, then the smaller id), in SUGGEST_SPEAKERS's order. A person may change all of it."""
    found = task_categories(task)
    amount = rules.has_amount(task_text(task))
    out = []
    for rule in SUGGEST_SPEAKERS:
        why = _why(rule, found, amount)
        if why is None:
            continue
        cards = [p for p in profiles if isinstance(p, dict) and isinstance(p.get("id"), str) and p.get("enabled") is not False
                 and ap.position_of(p) == rule["position"]]
        if not cards:
            continue
        card = min(cards, key=lambda p: (-_updated(p), p["id"]))
        out.append({"profile_id": card["id"], "position": rule["position"], "why": why})
    return out


# ---- what a speaker and the CEO may write --------------------------------------------------------------------------

SLOTS = ("planner", "executor", "reviewer1", "reviewer2")
SLOT_LABELS = {"planner": "規劃位", "executor": "執行位", "reviewer1": "審查位", "reviewer2": "第二位審查"}
OPINION_SLOTS = SLOTS + ("staff",)
STAFF_POSITIONS = ("pm", "legal", "accountant", "social", "art", "executor")
PICKS, STAFF_PICKS = ("existing", "new", "empty"), ("existing", "new")
GAP_CATEGORIES = CATEGORY_IDS + ("other",)
NEW_CARD_ALIASES = model_options.CLAUDE_ALIASES + ("",)
ALIAS_MAX, FOR_MAX, WORD_MAX = 8, 16, 20
NEW_REF_RE = re.compile(r"^N[1-3]\Z")
SHOWN_REF_RE = re.compile(r"^[CSN][1-9][0-9]{0,2}\Z")
# The positions a place suits (web/app.js TEAM_SLOTS fit). Whether a reviewer is of another camp than the executor is
# the review check's, not this table's.
SLOT_FIT = {"planner": ("planner", "pm"), "executor": ("executor", "social", "art"), "reviewer1": ("reviewer", "executor"),
            "reviewer2": ("reviewer", "executor"), "staff": SPEAKER_POSITIONS}

_S = {"type": "string"}


def _enum(values) -> dict:
    return {"type": "string", "enum": list(values)}


def _array(items: dict) -> dict:
    return {"type": "array", "items": items}


_RISK = mt._obj({"level": _enum(mt.LEVELS), "text": _S, "source": _S})
_PICKED_SKILL = mt._obj({"skill": _S, "why": _S})
STAFF_OPINION_SCHEMA = mt._obj({
    "summary": _S,
    "needs": _array(mt._obj({"what": _S, "position": _enum(ap.POSITIONS)})),
    "recommend": _array(mt._obj({"card": _S, "position": _enum(ap.POSITIONS), "slot": _enum(OPINION_SLOTS), "why": _S})),
    "skills": _array(mt._obj({"skill": _S, "for": _S, "why": _S})),
    "skill_gaps": _array(mt._obj({"need": _S, "category": _enum(GAP_CATEGORIES), "search_words": _array(_S)})),
    "risks": _array(_RISK)})
PROPOSAL_SCHEMA = mt._obj({
    "summary": _S,
    "team": _array(mt._obj({"slot": _enum(SLOTS), "pick": _enum(PICKS), "card": _S, "new_ref": _S, "reason": _S,
                            "skills": _array(_PICKED_SKILL)})),
    "staff": _array(mt._obj({"position": _enum(STAFF_POSITIONS), "pick": _enum(STAFF_PICKS), "card": _S, "new_ref": _S,
                             "reason": _S, "skills": _array(_PICKED_SKILL)})),
    "new_cards": _array(mt._obj({"ref": _S, "position": _enum(ap.POSITIONS), "tool": _enum(ap.TOOL_ORDER),
                                 "model_alias": _enum(NEW_CARD_ALIASES), "name": _S, "reason": _S, "skills": _array(_PICKED_SKILL)})),
    "skill_gaps": _array(mt._obj({"for": _S, "need": _S, "category": _enum(GAP_CATEGORIES), "search_words": _array(_S), "why": _S})),
    "risks": _array(_S),
    "questions_for_chairman": _array(_S),
    "opinions_used": _array(mt._obj({"from": _S, "point": _S, "adopted": {"type": "boolean"}, "why": _S}))})

# What VBear says of an item it kept but did not tick in advance; the codes are the record's, the words the page's.
FLAGS = {
    "disabled": "這張卡停用中，要先啟用",
    "cannot_start": "VBear 不能幫這張卡出發（安全模式下的 Codex、AGY，或共用卡）",
    "slot_fit": "這張卡的職位和這個位置不太合",
    "same_card": "同一張卡不能審查自己",
    "reviewer_family_unknown": "審查位的陣營是「共用」或不明，審查結果不算數",
    "executor_family_unknown": "執行位的陣營是「共用」或不明，審查結果不算數",
    "same_family": "審查位和執行位同一陣營，審查結果不算數",
    "already_equipped": "這張卡已經插著這張技能",
}
# What VBear took out or changed, and the places still empty. {ref} is an alias, a place or a position, never free text.
NOTES = {
    "unknown_card": "提到清單上沒有的角色卡{ref}，已拿掉",
    "unknown_skill": "提到清單上沒有的技能{ref}，已拿掉",
    "unknown_new_ref": "提到沒有寫出來的新卡{ref}，已拿掉",
    "unknown_for": "技能或缺口指向的{ref}不是清單上的卡、新卡或位置，已拿掉",
    "unknown_speaker": "說採納或沒採納{ref}的意見，但這個職位沒有成功發言，已拿掉",
    "bad_ref": "新卡的代號{ref}不是 N1 到 N3，已拿掉",
    "duplicate_ref": "新卡的代號{ref}重複，只留第一筆",
    "duplicate_slot": "{ref}寫了兩次，只留第一筆",
    "duplicate_position": "幕僚{ref}寫了兩次，只留第一筆",
    "duplicate_card": "同一張卡{ref}出現在兩個地方，只留第一筆",
    "duplicate_skill": "同一張技能{ref}寫了兩次，只留第一筆",
    "pick_mismatch": "{ref}的人選寫法前後不一致（現有的卡、新卡或空著），已拿掉",
    "incompatible_skill": "技能{ref}和這張卡的工具不相容，已拿掉",
    "too_many_skills": "技能{ref}插上後會超過 200 張，已拿掉",
    "bad_search_word": "搜尋關鍵字含網址或控制字元，已拿掉",
    "model_alias_cleared": "新卡{ref}不是 Claude Code 的卡，模型別名已清空",
    "missing": "還差：{ref}",
}


def _ref(value) -> str:
    """How a note names what it is about: an alias, a place or a position; anything else a model wrote is not repeated."""
    if not isinstance(value, str):
        return ""
    if SHOWN_REF_RE.match(value):
        return f"「{value}」"
    label = SLOT_LABELS.get(value) or POSITION_LABELS.get(value)
    return f"「{label}」" if label else ""


class _Notes(list):
    def add(self, code: str, ref="") -> None:
        self.append({"code": code, "text": NOTES[code].format(ref=_ref(ref))})


def _shape(value, keys: set) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise mt.OutputError()
    return value


def _items(value, count: int) -> list:
    if not isinstance(value, list) or len(value) > count:
        raise mt.OutputError()
    return value


def _one_of(value, allowed) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise mt.OutputError()
    return value


def _code(value, limit: int = ALIAS_MAX) -> str:
    """An alias, a ref or a place as a model wrote it (it may be empty): only its type and length are the schema's."""
    if not isinstance(value, str) or len(value) > limit:
        raise mt.OutputError()
    return value


def _bad_word(word: str) -> bool:
    return "://" in word or "www." in word.lower() or any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in word)


def _index(inputs: dict) -> tuple[dict, dict]:
    return {c["alias"]: c for c in inputs["cards"]}, {s["alias"]: s for s in inputs["skills"]}


def _card_flags(card: dict) -> list[str]:
    return (["disabled"] if not card["enabled"] else []) + (["cannot_start"] if card["can_start"] == "no" else [])


def validate_opinion(value, position: str | None, inputs: dict) -> dict:
    """{kept, notes}: a speaker's answer as it is kept, or mt.OutputError. Every alias must be on the list (a skill's
    ``for`` may also be a position); a skill must fit the card it is for."""
    v = _shape(value, {"summary", "needs", "recommend", "skills", "skill_gaps", "risks"})
    cards, skills = _index(inputs)
    notes = _Notes()
    needs = []
    for raw in _items(v["needs"], 5):
        raw = _shape(raw, {"what", "position"})
        needs.append({"what": mt._text(raw["what"], 120), "position": _one_of(raw["position"], ap.POSITIONS)})
    recommend = []
    for raw in _items(v["recommend"], 4):
        raw = _shape(raw, {"card", "position", "slot", "why"})
        item = {"card": _code(raw["card"]), "position": _one_of(raw["position"], ap.POSITIONS),
                "slot": _one_of(raw["slot"], OPINION_SLOTS), "why": mt._text(raw["why"], 200), "flags": []}
        if item["card"]:
            card = cards.get(item["card"])
            if card is None:
                notes.add("unknown_card", item["card"])
                continue
            item["flags"] = _card_flags(card) + (["slot_fit"] if card["position"] not in SLOT_FIT[item["slot"]] else [])
        recommend.append(item)
    picked = []
    for raw in _items(v["skills"], 6):
        raw = _shape(raw, {"skill", "for", "why"})
        item = {"skill": _code(raw["skill"]), "for": _code(raw["for"], FOR_MAX), "why": mt._text(raw["why"], 120), "flags": []}
        skill = skills.get(item["skill"])
        if skill is None:
            notes.add("unknown_skill", item["skill"])
            continue
        if item["for"] in cards:
            card = cards[item["for"]]
            if card["tool"] not in skill["fits"]:
                notes.add("incompatible_skill", item["skill"])
                continue
            item["flags"] = ["already_equipped"] if item["skill"] in card["equipped"] else []
        elif item["for"] not in ap.POSITIONS:
            notes.add("unknown_for", item["for"])
            continue
        picked.append(item)
    gaps = []
    for raw in _items(v["skill_gaps"], 3):
        raw = _shape(raw, {"need", "category", "search_words"})
        gaps.append({"need": mt._text(raw["need"], 100), "category": _one_of(raw["category"], GAP_CATEGORIES),
                     "search_words": _kept_words([mt._text(w, WORD_MAX) for w in _items(raw["search_words"], 3)], notes)})
    risks = []
    for raw in _items(v["risks"], 5):
        raw = _shape(raw, {"level", "text", "source"})
        source = mt._text(raw["source"], 200, empty=True).strip()
        if position == "legal" and not source:
            source = rules.NO_SOURCE
        risks.append({"level": _one_of(raw["level"], mt.LEVELS), "text": mt._text(raw["text"], 200), "source": source})
    kept = {"summary": mt._text(v["summary"], 120), "needs": needs, "recommend": recommend, "skills": picked,
            "skill_gaps": gaps, "risks": risks}
    return {"kept": kept, "notes": list(notes)}


def _parse_picked(value) -> list[dict]:
    out = []
    for raw in _items(value, 8):
        raw = _shape(raw, {"skill", "why"})
        out.append({"skill": _code(raw["skill"]), "why": mt._text(raw["why"], 120)})
    return out


def _picked_skills(picked: list[dict], tool: str, equipped: list[str], carried: int, skills: dict, notes: _Notes) -> list[dict]:
    """The skills proposed for one card: on the list, fitting the card's tool, once each, and not more than a card may
    carry once inserted (one already on the card is flagged, and adds nothing)."""
    out, seen, adding = [], set(), 0
    for item in picked:
        skill = skills.get(item["skill"])
        if skill is None:
            notes.add("unknown_skill", item["skill"])
        elif tool not in skill["fits"]:
            notes.add("incompatible_skill", item["skill"])
        elif item["skill"] in seen:
            notes.add("duplicate_skill", item["skill"])
        elif item["skill"] in equipped:
            seen.add(item["skill"])
            out.append({**item, "flags": ["already_equipped"]})
        elif carried + adding >= ap.MAX_SKILLS_PER_PROFILE:
            notes.add("too_many_skills", item["skill"])
        else:
            seen.add(item["skill"])
            adding += 1
            out.append({**item, "flags": []})
    return out


def _seat(raw: dict, cards: dict, new_cards: dict, notes: _Notes, where: str):
    """(key, who) of a place or a staff entry, who being the listed card or the new card; (None, None) for an empty place;
    False when the entry is taken out."""
    card, ref, pick = raw["card"], raw["new_ref"], raw["pick"]
    if pick == "empty":
        if card or ref or raw["skills"]:
            notes.add("pick_mismatch", where)
            return False
        return None, None
    if pick == "existing":
        if not card or ref:
            notes.add("pick_mismatch", where)
            return False
        if card not in cards:
            notes.add("unknown_card", card)
            return False
        return card, cards[card]
    if not ref or card:
        notes.add("pick_mismatch", where)
        return False
    if ref not in new_cards:
        notes.add("unknown_new_ref", ref)
        return False
    return ref, new_cards[ref]


def _family(who: dict) -> str:
    return who["family"] if "family" in who else ap.family_of_tool(who["tool"])


def _review_flag(review: dict, executor: dict | None) -> str | None:
    """Why a review place will not count, as web/app.js slotProblem and flows._independent judge it; None when it will."""
    if executor is not None and executor["key"] is not None and executor["key"] == review["key"]:
        return "same_card"
    rf = _family(review["who"])
    if rf in ("unknown", "other"):
        return "reviewer_family_unknown"
    if executor is None or executor["key"] is None:
        return None
    ef = _family(executor["who"])
    if ef in ("unknown", "other"):
        return "executor_family_unknown"
    return "same_family" if ef == rf else None


def _parse_proposal(value) -> dict:
    """The proposal read whole against its schema (every entry, the ones about to be taken out too), or mt.OutputError."""
    keys = {"summary", "team", "staff", "new_cards", "skill_gaps", "risks", "questions_for_chairman", "opinions_used"}
    v = _shape(value, keys)
    out: dict[str, Any] = {"summary": mt._text(v["summary"], 300), "risks": mt._texts(v["risks"], 5, 200),
                           "questions_for_chairman": mt._texts(v["questions_for_chairman"], 3, 150)}
    out["new_cards"] = []
    for raw in _items(v["new_cards"], 3):
        raw = _shape(raw, {"ref", "position", "tool", "model_alias", "name", "reason", "skills"})
        out["new_cards"].append({"ref": _code(raw["ref"]), "position": _one_of(raw["position"], ap.POSITIONS),
                                 "tool": _one_of(raw["tool"], ap.TOOL_ORDER), "model_alias": _one_of(raw["model_alias"], NEW_CARD_ALIASES),
                                 "name": mt._text(raw["name"], 40), "reason": mt._text(raw["reason"], 300),
                                 "skills": _parse_picked(raw["skills"])})
    for name, count, place, picks in (("team", 4, "slot", PICKS), ("staff", 4, "position", STAFF_PICKS)):
        out[name] = []
        for raw in _items(v[name], count):
            raw = _shape(raw, {place, "pick", "card", "new_ref", "reason", "skills"})
            out[name].append({place: _one_of(raw[place], SLOTS if name == "team" else STAFF_POSITIONS), "pick": _one_of(raw["pick"], picks),
                              "card": _code(raw["card"]), "new_ref": _code(raw["new_ref"]), "reason": mt._text(raw["reason"], 300),
                              "skills": _parse_picked(raw["skills"])})
    out["skill_gaps"] = []
    for raw in _items(v["skill_gaps"], 6):
        raw = _shape(raw, {"for", "need", "category", "search_words", "why"})
        out["skill_gaps"].append({"for": _code(raw["for"], FOR_MAX), "need": mt._text(raw["need"], 100),
                                  "category": _one_of(raw["category"], GAP_CATEGORIES),
                                  "search_words": [mt._text(w, WORD_MAX) for w in _items(raw["search_words"], 3)],
                                  "why": mt._text(raw["why"], 200)})
    out["opinions_used"] = []
    for raw in _items(v["opinions_used"], 12):
        raw = _shape(raw, {"from", "point", "adopted", "why"})
        if type(raw["adopted"]) is not bool:
            raise mt.OutputError()
        out["opinions_used"].append({"from": _code(raw["from"], FOR_MAX), "point": mt._text(raw["point"], 120),
                                     "adopted": raw["adopted"], "why": mt._text(raw["why"], 200)})
    return out


def _kept_words(words: list[str], notes: _Notes) -> list[str]:
    for word in words:
        if _bad_word(word):
            notes.add("bad_search_word")
    return [w for w in words if not _bad_word(w)]


def validate_proposal(value, inputs: dict, spoke) -> dict:
    """{kept, notes}: the CEO's proposal as it is kept, or mt.OutputError. ``spoke`` is the set of positions whose opinion
    was kept: an opinion said to be used must come from one of them. New cards are read first (a place may name one),
    then the four places, the staff, the gaps and the opinions used, each in the order written."""
    p = _parse_proposal(value)
    cards, skills = _index(inputs)
    notes = _Notes()

    new_cards: dict[str, dict] = {}
    for item in p["new_cards"]:
        if not NEW_REF_RE.match(item["ref"]):
            notes.add("bad_ref", item["ref"])
            continue
        if item["ref"] in new_cards:
            notes.add("duplicate_ref", item["ref"])
            continue
        if item["tool"] != "claude" and item["model_alias"]:
            item["model_alias"] = ""
            notes.add("model_alias_cleared", item["ref"])
        item["skills"] = _picked_skills(item["skills"], item["tool"], [], 0, skills, notes)
        new_cards[item["ref"]] = item

    used: dict[str, str] = {}
    seats: dict[str, dict] = {}
    team = []
    for item in p["team"]:
        if item["slot"] in seats:
            notes.add("duplicate_slot", item["slot"])
            continue
        seat = _seat(item, cards, new_cards, notes, item["slot"])
        if seat is False:
            continue
        key, who = seat
        if key is not None and key in used and {used[key], item["slot"]} not in ({"executor", "reviewer1"}, {"executor", "reviewer2"}):
            notes.add("duplicate_card", key)
            continue
        if key is not None:
            used.setdefault(key, item["slot"])
        listed = cards.get(key) if key is not None else None
        item["skills"] = _picked_skills(item["skills"], who["tool"] if who else "", listed["equipped"] if listed else [],
                                        len(listed["equipped_ids"]) if listed else 0, skills, notes)
        item["flags"] = (_card_flags(listed) if listed else []) + (
            ["slot_fit"] if who is not None and who["position"] not in SLOT_FIT[item["slot"]] else [])
        seats[item["slot"]] = {"key": key, "who": who, "item": item}
        team.append(item)
    executor = seats.get("executor")
    for slot in ("reviewer1", "reviewer2"):
        review = seats.get(slot)
        if review is not None and review["key"] is not None:
            flag = _review_flag(review, executor)
            if flag:
                review["item"]["flags"].append(flag)

    staff, positions = [], set()
    for item in p["staff"]:
        if item["position"] in positions:
            notes.add("duplicate_position", item["position"])
            continue
        seat = _seat(item, cards, new_cards, notes, item["position"])
        if seat is False:
            continue
        key, who = seat
        if key in used:
            notes.add("duplicate_card", key)
            continue
        used[key] = "staff"
        positions.add(item["position"])
        listed = cards.get(key)
        item["skills"] = _picked_skills(item["skills"], who["tool"], listed["equipped"] if listed else [],
                                        len(listed["equipped_ids"]) if listed else 0, skills, notes)
        item["flags"] = (_card_flags(listed) if listed else []) + (["slot_fit"] if who["position"] != item["position"] else [])
        staff.append(item)

    gaps = []
    for item in p["skill_gaps"]:
        if item["for"] not in cards and item["for"] not in new_cards and item["for"] not in SLOTS:
            notes.add("unknown_for", item["for"])
            continue
        gaps.append({**item, "search_words": _kept_words(item["search_words"], notes)})

    used_opinions = []
    for item in p["opinions_used"]:
        if item["from"] not in spoke:
            notes.add("unknown_speaker", item["from"])
            continue
        used_opinions.append(item)

    kept = {"summary": p["summary"], "team": team, "staff": staff, "new_cards": list(new_cards.values()), "skill_gaps": gaps,
            "risks": p["risks"], "questions_for_chairman": p["questions_for_chairman"], "opinions_used": used_opinions}
    missing = [SLOT_LABELS[s] for s in ("planner", "executor", "reviewer1") if seats.get(s) is None or seats[s]["key"] is None]
    if missing:
        notes.append({"code": "missing", "text": NOTES["missing"].format(ref="、".join(missing))})
    return {"kept": kept, "notes": list(notes)}
