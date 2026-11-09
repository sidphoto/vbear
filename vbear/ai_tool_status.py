"""Where each AI tool stands: installed, logged in, ready (the start-up page's data).

One question, answered for every tool the page lists: ``report(conf)``.

* Installed: the tool's file is found on the search path VBear uses for these programs (``runtime.daemon.cli_search_path``)
  and ``--version`` prints a first line the registry's pattern reads. A file that is there but prints something else is
  not counted (fail closed).
* Logged in, for the tools that have a status command (Claude Code, Codex): the command is run and only its exit code is
  looked at, 0 meaning logged in; anything else, including a timeout, means not logged in. Its output goes nowhere: it is
  never captured, stored or served.
* Logged in, for the tools that have none (AGY, Grok, MCODE): the person's "I have logged in" mark. The mark is kept in
  the state folder as the tool id and the time, nothing else.

The page asks every 5 seconds while it is open, and each look runs ``--version`` and the status commands, so a look is
kept for ``CACHE_TTL_S`` (30 seconds) and used again. It is read again at once when the person presses 「重新檢查」
(``force``), changes a mark, opens an install or login terminal or tries a tool (``invalidate``). A kept look is the row
this module made (no output of a command is in it); it is kept in memory only and is for one search path, one tool and one mark.

Codex also carries ``chat_login``: whether the Codex that chats (its own login folder in the state folder, ADR 0005) has a
login, by the exit code of its own status command (0 logged in, anything else not, no answer unknown); a folder that VBear
refuses to use is told in a sentence. That folder is looked at, never created here.

AGY also carries ``chat``: ``{"verified": bool}``, whether the AGY that is installed is a version whose chat check passed on this
Mac (P46-5). It is read from the record of ``agy-chat-verified.json`` and asks AGY nothing.

No tool's own login folder is opened, listed or read here. The commands run with the same plain environment the
terminals get, from the root folder, with no input.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import ai_tools, config as cfg
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import cli_versions, codex_chat_env, daemon

VERSION_TIMEOUT_S = 10.0
STATUS_TIMEOUT_S = 20.0
CACHE_TTL_S = 30.0
VERSION_LINE_MAX = 200          # of the first line of `--version`; a longer line is not a version


def _mark_problem(key, value):
    if key not in ai_tools.setup_ids():
        return "不是開始設定列出的 AI 工具"
    if not (isinstance(value, dict) and set(value) == {"at"} and isinstance(value["at"], float)
            and not isinstance(value["at"], bool)):
        return "只能記錄時間"
    return None


_cache: dict = {}               # (search path, tool id, mark time) -> (time it was read, row)
_cache_lock = threading.Lock()


def invalidate() -> None:
    """Forget every kept look: the next look reads the tools again."""
    with _cache_lock:
        _cache.clear()


store = GuardedJsonStore("setup_marks.json", "AI 工具登入標記", _mark_problem)


def parse_version(tool_id, text) -> Optional[str]:
    """The version in the first line of what ``--version`` printed, by the registry's pattern; None when it does not read."""
    tool = next((t for t in ai_tools.REGISTRY if t.id == tool_id), None)
    if tool is None or not tool.version_pattern or not isinstance(text, str):
        return None
    first = text.strip().splitlines()[0] if text.strip() else ""
    if not first or len(first) > VERSION_LINE_MAX:
        return None
    m = re.match(tool.version_pattern, first)
    return m.group(1) if m else None


def find_binary(tool_id) -> Optional[str]:
    """The tool's file on the search path, as an absolute path under its own name; None when there is none."""
    found = shutil.which(tool_id, path=daemon.cli_search_path())
    if not found or not os.path.isabs(found) or os.path.basename(found) != tool_id:
        return None
    return found


def _run(argv, timeout, want_output):
    """Run one command from the root folder with the plain environment and no input. -> (exit code or None, first output).
    The code is None when it could not be started or did not finish in time. Output is read only when asked for."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if want_output else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout, cwd="/", env=daemon.build_env(),
                              start_new_session=True, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, ""
    text = done.stdout[:4096].decode("utf-8", "replace") if want_output and done.stdout else ""
    return done.returncode, text


def read_marks() -> dict:
    """{tool id: time} of the tools the person said they logged in to. A store that cannot be read safely raises StoreError."""
    return {k: v["at"] for k, v in store.load().items()}


def set_mark(tool_id, done: bool) -> Optional[float]:
    """Record or remove the "I have logged in" mark of a tool that has no status command. -> the time, or None when removed."""
    with store.locked():
        data = store.load()
        if done:
            data[tool_id] = {"at": float(time.time())}
        else:
            data.pop(tool_id, None)
        store.save(data)
    invalidate()
    return data[tool_id]["at"] if done else None


def _chat_login(binary) -> dict:
    """{"state": "logged_in" | "not_logged_in" | "unknown" | "folder_problem", "problem": sentence}. A folder that is not
    there yet is "not_logged_in"; one that VBear would not use (a link, open to others, someone else's settings, too big)
    is "folder_problem" with the reason, and the status command is not run for it."""
    base = cfg.state_dir()
    folder, why = codex_chat_env.home_state(base)
    if folder == "refused":
        return {"state": "folder_problem", "problem": why}
    if folder == "missing":
        return {"state": "not_logged_in", "problem": ""}
    return {"state": codex_chat_env.login_state(binary, codex_chat_env.chat_home_path(base)), "problem": ""}


def _inspect(tool: ai_tools.Tool, marked_at: Optional[float]) -> dict:
    row = {"id": tool.id, "name": tool.name, "short": tool.short, "blurb": tool.blurb, "hidden": tool.hidden,
           "installed": False, "version": None, "install_problem": "not_found",
           "login_by": "status" if tool.status_command else "mark", "login": "unknown", "can_mark": not tool.status_command,
           "marked_at": None, "state": "not_installed", "ready": False,
           "login_regions": [{"id": rid, "label": label} for rid, label, _line in tool.login_regions]}
    if tool.id in ai_tools.CHAT_LOGIN:
        row["chat_login"] = {"state": "unknown", "problem": ""}
    if tool.id == "agy":
        row["chat"] = {"verified": False}       # P46-5: whether this AGY passed the chat check, read from the record only
    if not tool.status_command:
        row["login"] = "marked" if marked_at is not None else "not_marked"
        row["marked_at"] = marked_at
    binary = find_binary(tool.id)
    if binary is None:
        return row
    code, out = _run([binary, "--version"], VERSION_TIMEOUT_S, True)
    version = parse_version(tool.id, out) if code == 0 else None
    if version is None:
        row["install_problem"] = "version_unreadable"
        return row
    row.update(installed=True, version=version, install_problem="")
    if tool.id in ai_tools.CHAT_LOGIN:
        row["chat_login"] = _chat_login(binary)
    if tool.id == "agy":
        row["chat"] = {"verified": version in cli_versions.agy_chat_verified_versions()}
    if tool.status_command:
        code, _ = _run([binary, *tool.status_command[1:]], STATUS_TIMEOUT_S, False)
        row["login"] = "unknown" if code is None else "logged_in" if code == 0 else "not_logged_in"
        logged_in = row["login"] == "logged_in"
    else:
        logged_in = marked_at is not None
    row["state"] = "ready" if logged_in else "not_logged_in"
    row["ready"] = logged_in
    return row


def report(conf, marks: Optional[dict] = None, *, force: bool = False) -> list[dict]:
    """One row per tool the start-up page lists (a hidden tool only while it is switched on), in the registry's order.
    ``marks`` is {tool id: time}; None reads the state folder. ``force`` reads the tools again whatever was kept. The rows
    carry no command and no path."""
    marks = read_marks() if marks is None else marks
    shown = set(ai_tools.visible_ids(conf))
    tools = [t for t in ai_tools.REGISTRY if t.id in ai_tools.setup_ids() and t.id in shown]
    if not tools:
        return []
    where, now = daemon.cli_search_path(), time.monotonic()
    keys = {t.id: (where, t.id, marks.get(t.id)) for t in tools}
    with _cache_lock:
        kept = {} if force or CACHE_TTL_S <= 0 else {
            t.id: _cache[keys[t.id]][1] for t in tools if keys[t.id] in _cache and now - _cache[keys[t.id]][0] < CACHE_TTL_S}
    stale = [t for t in tools if t.id not in kept]
    if stale:
        with ThreadPoolExecutor(max_workers=len(stale)) as pool:
            fresh = dict(zip((t.id for t in stale), pool.map(lambda t: _inspect(t, marks.get(t.id)), stale)))
        with _cache_lock:
            if CACHE_TTL_S > 0:
                for tid, row in fresh.items():
                    _cache[keys[tid]] = (now, row)
                for key in [k for k, v in _cache.items() if now - v[0] >= CACHE_TTL_S]:
                    del _cache[key]
        kept.update(fresh)
    return [dict(kept[t.id]) for t in tools]


__all__ = ["report", "invalidate", "set_mark", "read_marks", "parse_version", "find_binary", "StoreError"]
