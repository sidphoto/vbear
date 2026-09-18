"""User annotations: friendly names, tags and notes (plan section 8.2).

Stored only in the console's own state directory; skill files are never
touched. Keyed by "<tool>:<invoke_name>" so a note survives a plugin upgrade
(new version, new path) while same-named skills from different tools stay
separate, as the plan requires.
"""

from __future__ import annotations

import json
import threading
import time

from . import config as cfg

MAX_ALIASES = 5
MAX_TAGS = 12
MAX_TEXT = 60
MAX_NOTE = 2000
_lock = threading.Lock()


def key_for(skill: dict) -> str:
    return f"{skill['tool']}:{skill.get('invoke_name') or skill['name']}"


def _path():
    return cfg.state_dir() / "annotations.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _clean_list(value, limit: int) -> list[str]:
    if isinstance(value, str):
        value = value.replace("，", ",").replace("、", ",").split(",")
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = " ".join(str(item).split())[:MAX_TEXT]
        if text and text not in out:
            out.append(text)
    return out[:limit]


def save(key: str, body: dict) -> dict:
    """Validate and store one annotation. Empty annotation removes the entry."""
    if not isinstance(key, str) or not key or len(key) > 200 or ":" not in key:
        raise ValueError("無效的技能識別")
    entry = {
        "aliases": _clean_list(body.get("aliases"), MAX_ALIASES),
        "tags": _clean_list(body.get("tags"), MAX_TAGS),
        "note": str(body.get("note") or "").strip()[:MAX_NOTE],
    }
    with _lock:
        data = load()
        if not any(entry.values()):
            data.pop(key, None)
            result = {}
        else:
            entry["updated_at"] = time.time()
            data[key] = entry
            result = entry
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    return result
