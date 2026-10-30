"""Staffing meetings (P35-1): the pure part of asking the CEO to staff a task card, after the staff have spoken.

A staffing meeting is held like a meeting, by headless calls with no tools (the runner comes later, on board_engine):
each suggested speaker says once, alone, which abilities the task needs, which card fits which place, which skills to
insert and what is missing; then the CEO writes a staffing proposal from what they said. Nothing here runs a program,
and nothing here, or in a proposal, creates a card, inserts a skill or puts anyone on a team: every step is a person's.

What this module holds:

  * the list both kinds of turn are given (build_inputs): the role cards and the skills a card can use, each under an
    alias (C1..C40, S1..S120) given once, so that no real id leaves the console and a model can only point at what is
    on the list. A speaker gets a short view of it (speaker_view), the CEO the whole of it (full_view);
  * who VBear suggests to speak, by a fixed table (SUGGEST_SPEAKERS), with the reason for each.

Disabled cards are on the list, marked: a disabled card cannot speak, but the CEO may propose it, and enabling it is
one more step of the person's.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import agent_profiles as ap, categories as cats, meeting_rules as rules, meetings as mt, position_guide, skill_fit
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
