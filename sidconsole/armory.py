"""Read-only Armory projections for Phase D1.

This module deliberately derives every display claim from the existing skill
index, profile store and runtime-use observations.  It never persists an index:
Profile -> equipped_skill_ids remains the sole source of truth.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .model import ACT_ACTIVE, ACT_DISABLED, ACT_NOT_INSTALLED, ACT_SUPERSEDED

_INSTALLED = frozenset({ACT_ACTIVE, ACT_DISABLED, ACT_SUPERSEDED})


def equipped_index(skills: list[dict], profiles: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Return known-skill reverse references plus unresolved profile refs.

    Disabled profiles remain visible: they still express a stored user intent,
    but are labelled disabled rather than being silently omitted.
    """
    known = {s.get("skill_id") for s in skills}
    resolved: dict[str, list[dict]] = defaultdict(list)
    unresolved: list[dict] = []
    for profile in profiles:
        ref = {"id": profile.get("id", ""), "name": profile.get("name", ""),
               "enabled": bool(profile.get("enabled", True))}
        for skill_id in profile.get("equipped_skill_ids", []):
            if skill_id in known:
                resolved[skill_id].append(ref)
            else:
                unresolved.append({"skill_id": skill_id, "profile": ref})
    return dict(resolved), unresolved


def project(skills: list[dict], profiles: list[dict], usage_for_skill) -> dict:
    """Make the Armory response without changing any scanned SkillRecord."""
    by_skill, unresolved = equipped_index(skills, profiles)
    rows = []
    for skill in skills:
        skill_id = skill["skill_id"]
        activation = skill.get("activation", "unknown")
        usage = usage_for_skill(skill_id)
        rows.append({
            "skill_id": skill_id,
            "name": skill.get("name", ""),
            "invoke_name": skill.get("invoke_name", ""),
            "tool": skill.get("tool", ""),
            "scope": skill.get("scope", ""),
            "activation": activation,
            "states": {
                "available": activation == ACT_NOT_INSTALLED,
                "installed": activation in _INSTALLED,
                "equipped": by_skill.get(skill_id, []),
                # No observed use is unknown, not a claim that it was not loaded.
                "loaded": {"observed": bool(usage), "evidence": usage},
            },
            "sources": {
                "available": "掃描（marketplace 副本）",
                "installed": "掃描",
                "equipped": "主控台 Profile（使用者意圖）",
                "loaded": "RUNTIME 觀察" if usage else "未知（沒有執行觀察）",
            },
        })
    return {"skills": rows, "unresolved_equipped": unresolved}
