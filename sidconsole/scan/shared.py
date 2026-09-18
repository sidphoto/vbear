"""~/.agents/skills: the store used by the `skills` CLI (vercel-labs/skills).

It records each skill's upstream in .skill-lock.json. Whether an agent tool
loads this directory directly is not established by any local config, so these
records are marked unknown; the tools load their own copies.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config as cfg
from ..model import ACT_UNKNOWN, SkillRecord
from . import claude


def _lock(root: Path) -> dict:
    try:
        data = json.loads((root.parent / ".skill-lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    skills = data.get("skills")
    return skills if isinstance(skills, dict) else {}


def scan_skills(source: cfg.Source, facts: dict) -> list[SkillRecord]:
    root = source.resolved()
    lock = _lock(root)
    records = claude.scan_skills(source, facts)
    for rec in records:
        rec.scope = "shared"
        rec.activation = ACT_UNKNOWN
        rec.activation_reason = ("skills CLI 的安裝庫；本機設定未顯示任何工具直接載入此目錄，"
                                 "各工具通常載入自己目錄中的副本")
        entry = lock.get(Path(rec.path).parent.name) or lock.get(rec.name)
        if isinstance(entry, dict):
            rec.origin_package = {
                "upstream": entry.get("source", ""),
                "upstream_url": entry.get("sourceUrl", ""),
                "installed_at": entry.get("installedAt", ""),
                "updated_at": entry.get("updatedAt", ""),
                "evidence": "~/.agents/.skill-lock.json",
            }
        else:
            rec.warnings.append("此技能不在 .skill-lock.json 中，上游來源未知")
    return records
