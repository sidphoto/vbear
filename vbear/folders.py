"""Read-only look at a folder the user is about to turn into a task card.

`inspect_folder` answers: does it exist, is it a git repository (and which
branch / commit, read straight from the repository files by `git_head`), how
many project skills the already-loaded skill index attributes to it, which
terminals the last live view has inside it, and which unfinished task cards
already point at it.

It writes nothing, starts no process (not even git) and never walks the file
tree: a fixed number of stats plus the few small files `git_head` reads. A
location that must never be a project (credentials, tool state, the home
directory itself) is refused before anything about it is looked at, and the
refusal says the same thing whether or not the location exists.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import config as cfg
from . import git_head

# Under the home directory; the home directory itself is refused as well.
SENSITIVE_HOME_DIRS = (".ssh", ".gnupg", ".aws", ".config", ".vbear", ".claude", ".codex", ".gemini", "Library")
REFUSED = "這個位置不能當成專案"
OUTSIDE_HOME = "這個位置不能當成專案（VBear 只能管理家目錄內的資料夾）"
MAX_PATH_CHARS = 1024
MAX_LISTED = 20        # terminals / task cards named in one answer
MAX_RECENT_FOLDERS = 10
TERMINAL_TITLE_CHARS = 80
# What closes a task card (see tasks._derive): a closure with one of these reasons on a completed card.
_CLOSED_REASONS = ("superseded", "canceled", "denied", "handed_off_to")


class FolderError(Exception):
    """A request that cannot be answered; `status` is the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def clean_path_text(raw) -> str:
    """The path text of a request: a non-empty absolute path, no NUL, not a file:// link."""
    if not isinstance(raw, str) or not raw.strip():
        raise FolderError(400, "請提供資料夾的絕對路徑")
    text = raw.strip()
    if len(text) > MAX_PATH_CHARS or "\x00" in text:
        raise FolderError(400, "路徑格式不正確")
    if text.lower().startswith("file://"):
        raise FolderError(400, "請填資料夾路徑（例如 /Users/you/project），不是 file:// 連結")
    if not os.path.isabs(text):
        raise FolderError(400, "路徑必須是絕對路徑")
    return os.path.normpath(text)


def _fold(path: Path) -> tuple[str, ...]:
    # Case-folded parts: the default macOS volume does not tell ~/.SSH from ~/.ssh.
    return tuple(part.casefold() for part in path.parts)


def _inside(path: Path, base: Path) -> bool:
    p, b = _fold(path), _fold(base)
    return len(p) >= len(b) and p[:len(b)] == b


def refused_locations(homes: list[Path]) -> list[Path]:
    """Every location a folder may not be, or be under: the fixed list below each home
    directory (also by where each really points), and the state directory."""
    out: list[Path] = []
    for home in homes:
        for name in SENSITIVE_HOME_DIRS:
            literal = home / name
            out.append(literal)
            try:
                out.append(Path(os.path.realpath(literal)))
            except OSError:
                pass
    state = cfg.state_dir()
    out.append(state)
    try:
        out.append(Path(os.path.realpath(state)))
    except OSError:
        pass
    return out


def resolve_allowed(raw, home: Path, root: Path | None = None) -> Path:
    """The real path of `raw`, or FolderError (400 for a malformed request, 403 for
    a place that may not be a project). Symlinks are followed first, so a link that
    points into a refused location is refused too.

    `root` is the range a folder must be inside (the console's managed root); it is the
    home directory in every real run, and `home` then is the same place."""
    text = clean_path_text(raw)
    home_real = Path(os.path.realpath(home))
    root_real = Path(os.path.realpath(root)) if root is not None else home_real
    try:
        real = Path(os.path.realpath(text))
    except (OSError, ValueError):
        raise FolderError(400, "路徑格式不正確") from None
    homes = [home_real] if _fold(home_real) == _fold(root_real) else [home_real, root_real]
    if any(_fold(real) == _fold(h) for h in homes):
        raise FolderError(403, REFUSED)
    if not _inside(real, root_real):
        raise FolderError(403, OUTSIDE_HOME)
    for blocked in refused_locations(homes):
        if _inside(real, blocked):
            raise FolderError(403, REFUSED)
    return real


def _within(cwd, bases: tuple[str, ...]) -> bool:
    if not isinstance(cwd, str) or not cwd:
        return False
    norm = os.path.normpath(cwd)
    return any(norm == b or norm.startswith(b.rstrip("/") + "/") for b in bases)


def _branch(ref) -> str | None:
    prefix = "refs/heads/"
    return ref[len(prefix):] if isinstance(ref, str) and ref.startswith(prefix) else None


def _terminals(live, bases: tuple[str, ...]) -> dict:
    """Terminals in the last live view whose working directory is this folder or below it.
    Only what the live view lists (Claude Code / Codex terminals) and only by directory: nothing
    here says which role card, if any, a terminal came from."""
    if not isinstance(live, dict) or not isinstance(live.get("sessions"), list):
        return {"known": False, "count": 0, "items": []}
    hits = [s for s in live["sessions"] if isinstance(s, dict) and _within(s.get("cwd"), bases)]
    items = [{"terminal_id": str(s.get("terminal_id") or ""), "tool": str(s.get("tool") or ""),
              "status": str(s.get("status") or "unknown"),
              "title": str(s.get("title") or "")[:TERMINAL_TITLE_CHARS]} for s in hits[:MAX_LISTED]]
    return {"known": True, "count": len(hits), "items": items}


def _skill_count(static, roots: set[str]) -> int | None:
    """Project skills of this folder from the index already in memory; None when none is loaded."""
    if not isinstance(static, dict) or not isinstance(static.get("skills"), list):
        return None
    return sum(1 for s in static["skills"]
               if isinstance(s, dict) and isinstance(s.get("origin_package"), dict)
               and s["origin_package"].get("project_path") in roots)


def _is_open(task: dict) -> bool:
    closure = task.get("closure")
    agent = (task.get("provenance") or {}).get("agent")
    return not (isinstance(closure, dict) and closure.get("reason") in _CLOSED_REASONS and agent == "completed")


def _open_tasks(rows, bases: tuple[str, ...]) -> dict:
    if rows is None:
        return {"known": False, "items": []}
    items = []
    for task in rows.values() if isinstance(rows, dict) else rows:
        if not isinstance(task, dict) or not isinstance(task.get("workdir"), str):
            continue
        if os.path.normpath(task["workdir"]) in bases and _is_open(task):
            items.append({"id": str(task.get("id") or ""), "title": str(task.get("title") or "")[:200]})
    return {"known": True, "items": items[:MAX_LISTED], "count": len(items)}


def inspect_folder(raw, *, home: Path, root: Path | None = None, live=None, static=None, task_rows=None,
                   read_head=git_head.read_head) -> dict:
    """The summary for GET /api/folders/inspect (see the module docstring)."""
    real = resolve_allowed(raw, home, root)
    asked = clean_path_text(raw)
    bases = tuple(dict.fromkeys((str(real), asked)))
    out = {"ok": True, "path": str(real), "name": real.name, "exists": False, "is_dir": False}
    try:
        st = os.stat(real)
    except OSError:
        return out
    out["exists"] = True
    out["is_dir"] = stat.S_ISDIR(st.st_mode)
    if not out["is_dir"]:
        return out
    head = read_head(str(real))
    repo = head.get("repo")
    commit = head.get("commit")
    out["git"] = {"is_repo": repo is not None, "root": repo, "branch": _branch(head.get("ref")),
                  "commit": commit, "short": commit[:8] if isinstance(commit, str) else None,
                  "error": head.get("error") if repo is not None else None}
    roots = {str(real)} | ({os.path.normpath(repo)} if repo else set())
    out["project_skill_count"] = _skill_count(static, roots)
    out["terminals"] = _terminals(live, bases)
    out["tasks"] = _open_tasks(task_rows, bases)
    return out


def clean_recent_folders(value) -> list[str]:
    """The `recent_folders` setting: at most MAX_RECENT_FOLDERS absolute path strings."""
    if not isinstance(value, list) or len(value) > MAX_RECENT_FOLDERS:
        raise ValueError(f"recent_folders 必須是最多 {MAX_RECENT_FOLDERS} 個路徑的清單")
    out: list[str] = []
    for raw in value:
        if (not isinstance(raw, str) or not raw or len(raw) > MAX_PATH_CHARS or "\x00" in raw
                or not os.path.isabs(raw)):
            raise ValueError("recent_folders 只能包含絕對路徑字串")
        if raw not in out:
            out.append(raw)
    return out


def remembered(current, path: str) -> list[str]:
    """`current` with `path` moved to the front, capped."""
    keep = [p for p in current if isinstance(p, str) and p != path]
    return ([path] + keep)[:MAX_RECENT_FOLDERS]
