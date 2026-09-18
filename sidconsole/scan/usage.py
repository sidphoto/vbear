"""Usage evidence from local session logs.

Answers two questions the plan says must never be guessed:
  - which skills did a session actually use?
  - which model did a session actually run on?

Privacy boundary: only skill identifiers, model names, session ids, working
directories and timestamps are extracted. Prompt text, tool output and file
contents are never stored, returned, or logged.

Evidence strength:
  explicit  - Claude Code recorded a Skill tool call naming the skill
  file_read - Codex ran a tool call that referenced the skill's SKILL.md path;
              that is how Codex loads a skill, but it is weaker than an
              explicit invocation (the file may have been read for another
              reason), so it is labelled as derived.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import config as cfg

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"

_SKILL_PATH = re.compile(r"((?:~|/)[^\s\"'\\]*?/skills/[^\s\"'\\]+?/SKILL\.md)")
_CACHE_VERSION = 2


def _cache_file() -> Path:
    return cfg.state_dir() / "usage-cache.json"


def _load_cache() -> dict:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        if data.get("version") == _CACHE_VERSION:
            return data
    except (OSError, ValueError):
        pass
    return {"version": _CACHE_VERSION, "files": {}}


def _save_cache(cache: dict) -> None:
    cfg.write_private(_cache_file(), json.dumps(cache))


def _new_session(tool: str, file: Path) -> dict:
    return {
        "session_id": "", "tool": tool, "cwd": "", "first_ts": "", "last_ts": "",
        "models": {}, "skills": {}, "log": str(file),
    }


def _touch(session: dict, ts: str) -> None:
    if not ts:
        return
    if not session["first_ts"] or ts < session["first_ts"]:
        session["first_ts"] = ts
    if ts > session["last_ts"]:
        session["last_ts"] = ts


def _add_skill(session: dict, key: str, ts: str, evidence: str) -> None:
    entry = session["skills"].setdefault(key, {"count": 0, "last_ts": "", "evidence": evidence})
    entry["count"] += 1
    if ts and ts > entry["last_ts"]:
        entry["last_ts"] = ts


def parse_claude_log(path: Path) -> dict:
    session = _new_session("claude", path)
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"sessionId"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ts = obj.get("timestamp") or ""
            session["session_id"] = session["session_id"] or obj.get("sessionId") or ""
            if obj.get("cwd") and not session["cwd"]:
                session["cwd"] = obj["cwd"]
            _touch(session, ts)
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if model and not str(model).startswith("<"):
                session["models"][model] = session["models"].get(model, 0) + 1
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (isinstance(part, dict) and part.get("type") == "tool_use"
                        and part.get("name") == "Skill"):
                    skill = (part.get("input") or {}).get("skill")
                    if isinstance(skill, str) and skill:
                        _add_skill(session, "name:" + skill, ts, "explicit")
    return session


def parse_codex_log(path: Path) -> dict:
    session = _new_session("codex", path)
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("{"):
                continue
            kind_hint = line[:80]
            relevant = ("session_meta" in kind_hint or "turn_context" in kind_hint
                        or "SKILL.md" in line)
            if not relevant:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ts = obj.get("timestamp") or ""
            _touch(session, ts)
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            kind = obj.get("type")
            if kind == "session_meta":
                session["session_id"] = payload.get("id") or payload.get("session_id") or ""
                session["cwd"] = payload.get("cwd") or session["cwd"]
            elif kind == "turn_context":
                model = payload.get("model")
                if model:
                    session["models"][model] = session["models"].get(model, 0) + 1
            elif payload.get("type") in ("custom_tool_call", "function_call", "local_shell_call"):
                blob = json.dumps(payload, ensure_ascii=False)
                for raw in set(_SKILL_PATH.findall(blob)):
                    resolved = str(Path(raw.replace("\\/", "/")).expanduser())
                    _add_skill(session, "path:" + resolved, ts, "file_read")
    return session


def collect(days: int = 30) -> dict:
    """Return {"sessions": [...], "problems": [...], "window_days": days}."""
    cutoff = time.time() - days * 86400
    cache = _load_cache()
    files_cache = cache["files"]
    seen: set[str] = set()
    sessions: list[dict] = []
    problems: list[str] = []

    jobs: list[tuple[Path, str]] = []
    if CLAUDE_PROJECTS.is_dir():
        jobs += [(p, "claude") for p in CLAUDE_PROJECTS.glob("*/*.jsonl")]
    else:
        problems.append("找不到 ~/.claude/projects，Claude Code 使用紀錄不可用")
    if CODEX_SESSIONS.is_dir():
        jobs += [(p, "codex") for p in CODEX_SESSIONS.rglob("*.jsonl")]
    else:
        problems.append("找不到 ~/.codex/sessions，Codex 使用紀錄不可用")

    for path, tool in jobs:
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            continue
        key = str(path)
        seen.add(key)
        stamp = [stat.st_mtime, stat.st_size]
        cached = files_cache.get(key)
        if cached and cached.get("stamp") == stamp:
            sessions.append(cached["session"])
            continue
        try:
            session = parse_claude_log(path) if tool == "claude" else parse_codex_log(path)
        except OSError as exc:
            problems.append(f"無法讀取 {path.name}：{exc}")
            continue
        files_cache[key] = {"stamp": stamp, "session": session}
        sessions.append(session)

    for stale in set(files_cache) - seen:
        files_cache.pop(stale, None)
    _save_cache(cache)
    sessions = [s for s in sessions if s["session_id"]]
    return {"sessions": sessions, "problems": problems, "window_days": days}


def for_session_ids(ids: list[str]) -> dict[str, dict]:
    """Parse the logs of specific sessions regardless of the time window.

    Used for sessions herdr reports as running now: they are current work even
    when their log was last written long ago. Files are located by the session
    id in their file name, so nothing outside the two log roots is touched.
    """
    wanted = {i for i in ids if i and all(c.isalnum() or c == "-" for c in i)}
    found: dict[str, dict] = {}
    if not wanted:
        return found
    for sid in wanted:
        for path in CLAUDE_PROJECTS.glob(f"*/{sid}.jsonl"):
            try:
                found[sid] = parse_claude_log(path)
            except OSError:
                pass
            break
    if CODEX_SESSIONS.is_dir() and wanted - found.keys():
        for path in CODEX_SESSIONS.rglob("rollout-*.jsonl"):
            sid = next((s for s in wanted - found.keys() if path.name.endswith(f"{s}.jsonl")), None)
            if sid:
                try:
                    found[sid] = parse_codex_log(path)
                except OSError:
                    pass
    return {k: v for k, v in found.items() if v.get("session_id")}
