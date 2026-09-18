"""Console configuration: which sources to scan, and where state lives.

Scan scope is chosen by the user, never the whole machine (plan section 9).
The console writes only inside its own state directory; skill and agent source
files are opened read-only and never modified.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

APP_NAME = "sid-console"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7788

# Directory names that are storage, not a load path. Skills found under these
# are still listed, but marked archived so they never look active.
ARCHIVE_MARKERS = ("_backups", ".tmp", "archived_sessions", "vendor_imports", "backups")


def state_dir() -> Path:
    override = os.environ.get("SID_CONSOLE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sid-console"


def config_path() -> Path:
    return state_dir() / "config.json"


def index_path() -> Path:
    return state_dir() / "index.json"


@dataclass
class Source:
    source_id: str
    tool: str  # claude | codex | shared
    kind: str  # skills | agents | plugin_cache | marketplace
    scope: str  # user | project | plugin | marketplace | system | vendor | synced
    path: str
    enabled: bool = True
    label: str = ""

    def resolved(self) -> Path:
        return Path(os.path.expanduser(self.path))


def default_sources() -> list[Source]:
    home = "~"
    return [
        Source("claude-user-skills", "claude", "skills", "user", f"{home}/.claude/skills",
               label="Claude Code 使用者技能"),
        Source("claude-plugin-cache", "claude", "plugin_cache", "plugin", f"{home}/.claude/plugins/cache",
               label="Claude Code 外掛快取"),
        Source("claude-marketplaces", "claude", "marketplace", "marketplace",
               f"{home}/.claude/plugins/marketplaces", label="Claude Code 外掛市集"),
        Source("claude-user-agents", "claude", "agents", "user", f"{home}/.claude/agents",
               label="Claude Code 子代理"),
        Source("codex-skills", "codex", "skills", "user", f"{home}/.codex/skills",
               label="Codex CLI 技能"),
        Source("codex-agents", "codex", "agents", "user", f"{home}/.codex/agents",
               label="Codex CLI 代理定義"),
        Source("shared-skills", "shared", "skills", "shared", f"{home}/.agents/skills",
               label="skills CLI 共用技能庫"),
    ]


DEFAULT_CONFIG = {
    "version": 1,
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "language": "zh-TW",
    "advanced_mode": False,
    "herdr_bin": "",
    "project_roots": ["~/projects"],
    "sources": [asdict(s) for s in default_sources()],
}


def load() -> dict:
    path = config_path()
    if not path.exists():
        save(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update(data)
    known = {s["source_id"] for s in merged.get("sources", [])}
    for extra in DEFAULT_CONFIG["sources"]:
        if extra["source_id"] not in known:
            merged["sources"].append(extra)
    return merged


def save(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sources_from(data: dict) -> list[Source]:
    out = []
    for raw in data.get("sources", []):
        try:
            out.append(Source(**raw))
        except TypeError:
            continue
    return out


def is_archive_path(path: str) -> bool:
    parts = Path(path).parts
    return any(marker in parts for marker in ARCHIVE_MARKERS)
