"""Console configuration: which sources to scan, and where state lives.

Scan scope is chosen by the user, never the whole machine (plan section 9).
The console writes only inside its own state directory; skill and agent source
files are opened read-only and never modified.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path

APP_NAME = "vbear"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7788

# Directory names that are storage, not a load path. Skills found under these
# are still listed, but marked archived so they never look active.
ARCHIVE_MARKERS = ("_backups", ".tmp", "archived_sessions", "vendor_imports", "backups")


LEGACY_STATE_NAME = ".sid-console"  # name before the VBear rename (v0.1.0)


def state_dir() -> Path:
    override = os.environ.get("VBEAR_HOME") or os.environ.get("SID_CONSOLE_HOME")
    if override:
        return Path(override).expanduser()
    current = Path.home() / ".vbear"
    legacy = Path.home() / LEGACY_STATE_NAME
    # Until the legacy directory can be moved safely, keep using it in place.
    if not current.exists() and legacy.is_dir():
        return legacy
    return current


def _legacy_port(legacy: Path) -> int:
    """The port the old console was configured for (default when unknown)."""
    try:
        port = json.loads((legacy / "config.json").read_text()).get("port")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_PORT
    return port if isinstance(port, int) and 0 < port < 65536 else DEFAULT_PORT


def migrate_legacy_state_dir(port_in_use=None) -> str:
    """Move ~/.sid-console to ~/.vbear once, only when nothing is using it.

    Returns "none" (nothing to do), "moved", or "kept:<reason>" when the
    legacy directory stays in use for now. Never merges or overwrites."""
    if os.environ.get("VBEAR_HOME") or os.environ.get("SID_CONSOLE_HOME"):
        return "none"
    current = Path.home() / ".vbear"
    legacy = Path.home() / LEGACY_STATE_NAME
    if not legacy.is_dir() or legacy.is_symlink():
        return "none"
    if current.exists():
        return "conflict"  # both exist: never merge; the caller tells the user
    if port_in_use is not None and port_in_use(_legacy_port(legacy)):
        return "kept:console_running"
    sessions = legacy / "sessions"
    # Launch manifests hold absolute paths into this directory.
    if sessions.is_dir() and any(sessions.iterdir()):
        return "kept:managed_launches_pending"
    lock = legacy / "runtimed.lock"
    fd = None
    try:
        if lock.exists():
            import fcntl
            fd = os.open(lock, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return "kept:runtime_running"
        os.rename(legacy, current)
        return "moved"
    except OSError:
        return "kept:rename_failed"
    finally:
        if fd is not None:
            os.close(fd)  # releases the flock; the lock file moved with the directory


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


def write_private(path: Path, text: str) -> os.stat_result:
    """Atomically replace `path` with an owner-only (0600) file.

    The temporary name is unique (mkstemp), so a CLI scan and a server rescan
    writing the same file at once cannot clobber each other's half-written
    temp file; the last complete write wins.

    Returns the stat of the file this call installed, taken from its own
    descriptor, so a caller can tell it apart from a later replacement.
    """
    ensure_state_dir()
    path.parent.mkdir(parents=True, exist_ok=True, mode=STATE_DIR_MODE)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            written = os.fstat(out.fileno())
        os.chmod(tmp, STATE_FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return written


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
    "runtime_kind": "native",  # the only runtime since the Herdr bridge was removed
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
    except (OSError, ValueError, RecursionError):  # deep nesting is corrupt too
        return True


def _holds(path: Path, raw: bytes) -> bool:
    """Whether `path` is a regular file, not a symlink, with exactly `raw`."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            return (stat.S_ISREG(st.st_mode) and st.st_size == len(raw)
                    and fh.read(len(raw) + 1) == raw)
    except OSError:
        return False


def _backup_corrupt(raw: bytes) -> str:
    """Keep a corrupt config's exact bytes in config.json.bak.

    The copy is written owner-only to a temporary file and hard-linked into
    place. link() never replaces or follows an existing entry, not even a
    dangling symlink, so an older backup survives and a backup is either
    complete or absent. Returns what is now true:
      created   config.json.bak is this call's copy
      existing  config.json.bak already held exactly these bytes
      conflict  something else is there, and it was left alone
      failed    no copy could be made
    """
    bak = config_path().with_suffix(".json.bak")
    try:
        fd, tmp = tempfile.mkstemp(dir=bak.parent, prefix=bak.name + ".", suffix=".tmp")
    except OSError:
        return "failed"
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
        os.chmod(tmp, STATE_FILE_MODE)
        os.link(tmp, bak)
        return "created"
    except FileExistsError:
        return "existing" if _holds(bak, raw) else "conflict"
    except OSError:
        return "failed"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


_BACKUP_NOTES = {
    "created": "原檔未修改，內容已備份至 config.json.bak",
    "existing": "原檔未修改，內容已備份至 config.json.bak（先前建立，內容相同）",
    "conflict": "原檔未修改；config.json.bak 已存在但不是目前內容，未覆寫，本次內容沒有另外備份",
    "failed": "原檔未修改，但無法建立備份",
    "unreadable": "無法讀取原檔，沒有建立備份；原檔未被修改",
}


def corrupt_message() -> str:
    """Why a corrupt config is not saved over. It says the file is backed up
    only when config.json.bak holds exactly the file's current bytes."""
    try:
        raw = config_path().read_bytes()
    except OSError:
        outcome = "unreadable"
    else:
        outcome = _backup_corrupt(raw)
    return f"設定檔已損毀，拒絕自動覆寫；{_BACKUP_NOTES[outcome]}，請修復後重試"


def corrupt_fallback() -> dict:
    """What the console runs with while config.json cannot be read.

    The user's choices are unknown, so nothing is assumed: every source is
    off and no project root is scanned. Falling back to the defaults would
    silently widen the scan past what the user had chosen.
    """
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for src in merged["sources"]:
        src["enabled"] = False
    merged["project_roots"] = []
    merged["_corrupt"] = True
    return merged


def load() -> dict:
    path = config_path()
    if not path.exists():
        save(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    raw = None
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("設定檔內容非物件")
    except (OSError, ValueError, RecursionError):
        if raw is not None:
            _backup_corrupt(raw)
        return corrupt_fallback()
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update(data)
    known = {s["source_id"] for s in merged.get("sources", [])}
    for extra in DEFAULT_CONFIG["sources"]:
        if extra["source_id"] not in known:
            merged["sources"].append(extra)
    if _migrate_from_herdr(merged):
        try:
            save(merged)
        except (OSError, ValueError):
            pass  # still run as native this time; the migration is retried on the next load
    return merged


def _migrate_from_herdr(conf: dict) -> bool:
    """A config written while Herdr was supported becomes native once. The
    time is kept so the UI can tell the user once (until acknowledged)."""
    changed = False
    if conf.get("runtime_kind") != "native":
        conf["runtime_kind"] = "native"
        conf.setdefault("herdr_migrated_at", time.time())
        changed = True
    if "herdr_bin" in conf:
        del conf["herdr_bin"]
        changed = True
    return changed


def save(data: dict, force: bool = False) -> None:
    if not force and is_corrupt():
        raise ValueError(corrupt_message())
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
