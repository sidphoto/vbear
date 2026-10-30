"""Which skill a role card can take, in Python (P35-1): the rules web/app.js has applied on the card wizard since P22/P24,
so that a staffing proposal is checked by the server the same way the page checks a card.

  skill_compatible  a skill of the card's own tool, or a shared one; an AGY card takes what AGY reads (its own skills and
                    the ones the scan marked read_by agy), and a shared card only shared skills (skillCompatible);
  skill_usable      compatible, and not dead: a Claude Code or Codex card counts its own tool's skill only when it is
                    active, anything else unless the index calls it old, uninstalled, disabled, not loaded or archived;
  pick_listed       the usable ones with one skill per name of one tool: the active one, then the newest, then the
                    smaller skill_id (the wizard's default list, skillPickPlan, without its order).

tests/skill_fit_cases.json holds the answers; tests/test_skill_fit.py holds this module to it and
tests/frontend/skill_fit.cjs holds the page. Inserting a skill on a card is a record: nothing here loads one.
"""
from __future__ import annotations

import math

from .agent_profiles import TOOL_ORDER

NEVER_LISTED = frozenset({"superseded", "not_installed", "disabled", "not_loaded", "archived"})


def skill_read_by_agy(skill) -> bool:
    if not isinstance(skill, dict):
        return False
    read_by = skill.get("read_by")
    return skill.get("tool") == "agy" or (isinstance(read_by, list) and "agy" in read_by)


def skill_compatible(skill, tool) -> bool:
    if not isinstance(skill, dict):
        return False
    source = skill.get("tool")
    if tool == "agy":
        return skill_read_by_agy(skill) and isinstance(source, str) and source != ""
    if source == "shared":
        return True
    return isinstance(source, str) and source == tool


def skill_usable(skill, tool) -> bool:
    if not skill_compatible(skill, tool):
        return False
    activation = skill.get("activation")
    if tool in ("claude", "codex") and skill.get("tool") == tool:
        return activation == "active"
    return activation not in NEVER_LISTED


def fits(skill) -> list[str]:
    """The tools of the cards that can use this skill, in the camps' order."""
    return [tool for tool in TOOL_ORDER if skill_usable(skill, tool)]


def _mtime(skill: dict) -> float:
    value = skill.get("mtime")
    return value if type(value) in (int, float) and math.isfinite(value) else 0


def pick_listed(skills, tool) -> list[dict]:
    """The skills a card of this tool is offered: usable, one per name of one tool."""
    groups: dict[tuple, list[dict]] = {}
    for skill in skills if isinstance(skills, list) else []:
        if isinstance(skill, dict) and skill_usable(skill, tool):
            name = skill.get("invoke_name") or skill.get("name") or skill.get("skill_id")
            groups.setdefault((str(skill.get("tool")), str(name)), []).append(skill)
    return [min(members, key=lambda s: (s.get("activation") != "active", -_mtime(s), str(s.get("skill_id"))))
            for members in groups.values()]
