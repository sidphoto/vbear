"""Console configuration: which sources to scan, and where state lives.

Scan scope is chosen by the user, never the whole machine (plan section 9).
The console writes only inside its own state directory; skill and agent source
files are opened read-only and never modified.
"""

from __future__ import annotations

import json
import os
import tempfile
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


STATE_DIR_MODE = 0o700
STATE_FILE_MODE = 0o600


def ensure_state_dir() -> Path:
    """Create the state directory owner-only and tighten what is already there.

    The index and usage cache list local paths, project names and session ids,
    so neither the directory nor its files are readable by other accounts.
    """
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True, mode=STATE_DIR_MODE)
    os.chmod(path, STATE_DIR_MODE)
    try:
        entries = list(path.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            if entry.is_file() and not entry.is_symlink():
                os.chmod(entry, STATE_FILE_MODE)
        except OSError:
            continue
    return path


def write_private(path: Path, text: str) -> None:
    """Atomically replace `path` with an owner-only (0600) file.

    The temporary name is unique (mkstemp), so a CLI scan and a server rescan
    writing the same file at once cannot clobber each other's half-written
    temp file; the last complete write wins.
    """
    ensure_state_dir()
    path.parent.mkdir(parents=True, exist_ok=True, mode=STATE_DIR_MODE)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.chmod(tmp, STATE_FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def open_private_log(path: Path):
    """Append handle for server.log, created 0600 (and tightened if it exists)."""
    ensure_state_dir()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, STATE_FILE_MODE)
    os.fchmod(fd, STATE_FILE_MODE)
    return os.fdopen(fd, "ab")


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


def is_corrupt() -> bool:
    path = config_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return not isinstance(data, dict)
    except (OSError, ValueError):
        return True


def load() -> dict:
    path = config_path()
    if not path.exists():
        save(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("設定檔內容非物件")
    except (OSError, ValueError):
        bak = path.with_suffix(".json.bak")
        try:
            if not bak.exists() and "raw" in locals():
                bak.write_text(raw, encoding="utf-8")
        except OSError:
            pass
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged["_corrupt"] = True
        return merged
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update(data)
    known = {s["source_id"] for s in merged.get("sources", [])}
    for extra in DEFAULT_CONFIG["sources"]:
        if extra["source_id"] not in known:
            merged["sources"].append(extra)
    return merged


def save(data: dict, force: bool = False) -> None:
    if not force and is_corrupt():
        raise ValueError("設定檔已損毀，拒絕自動覆寫；原檔已備份至 config.json.bak，請修復後重試")
    cleaned = {k: v for k, v in data.items() if not k.startswith("_")}
    write_private(config_path(), json.dumps(cleaned, ensure_ascii=False, indent=2))


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
