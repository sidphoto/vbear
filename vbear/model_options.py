"""The model names the card wizard offers in its drop-down (P31).

Nothing here runs a program or opens a connection. Two sources, both already on this computer:

  * Claude Code: the aliases below, and the full names the usage scan has already seen in Claude's own session logs
    (passed in; this module reads no log).
  * Codex: ``~/.codex/models_cache.json``, the list Codex caches for itself. Only ``slug``, ``display_name``,
    ``visibility`` and ``priority`` of each model are looked at; nothing else in the file is kept or sent on.

Agy and shared cards get no list: VBear does not start Antigravity and reads nothing under ``~/.gemini`` for this.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import strictjson

# The aliases `claude --help` documents for --model: "Provide an alias for the latest model (e.g. 'fable', 'opus', or
# 'sonnet') or a model's full name". An alias always points at the newest version, so it needs no list to stay current.
# `haiku` is the fourth model family Claude Code takes the same way. If Claude Code changes its aliases, change this.
CLAUDE_ALIASES = ("fable", "opus", "sonnet", "haiku")

CODEX_CACHE = (".codex", "models_cache.json")
MAX_CODEX_BYTES = 1 << 20                  # the whole file
MAX_CODEX_SCANNED = 500                    # models looked at
MAX_CODEX_OPTIONS = 50                     # models offered
MAX_OBSERVED = 20                          # names from the usage scan, per tool
MAX_LABEL = 80
MAX_VALUE = 100
CODEX_LIMITS = strictjson.Limits(MAX_CODEX_BYTES, 50_000, 8, MAX_CODEX_BYTES)

# letters, digits and . - _ : / only, and it starts with a letter or digit (never an option-looking "-x")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ‪-‮⁦-⁩]")


def _safe_name(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_VALUE and _SAFE_NAME.match(value) is not None


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _label(display, slug: str) -> str:
    if isinstance(display, str):
        text = display.strip()
        if 0 < len(text) <= MAX_LABEL and not _CONTROL.search(text):
            return text
    return slug


def _cache_path(home: Path) -> tuple[Path | None, str]:
    """The cache file's path, or why there is none. The folder may be a link only when it stays inside the home folder;
    the file itself is never a link (strictjson opens it with O_NOFOLLOW)."""
    folder = home / CODEX_CACHE[0]
    try:
        real_home = home.resolve(strict=True)
        real_folder = folder.resolve(strict=True)
    except OSError:
        return None, "這台電腦沒有 Codex 的模型快取"
    if not real_folder.is_dir():
        return None, "這台電腦沒有 Codex 的模型快取"
    if real_folder != real_home and real_home not in real_folder.parents:
        return None, "Codex 的資料夾連到家目錄之外，沒有讀取"
    return real_folder / CODEX_CACHE[1], ""


def codex_models(home: Path) -> tuple[list[dict], str]:
    """(options, problem): the models Codex lists for itself, in its own order, or an empty list and a one-line reason."""
    path, problem = _cache_path(Path(home))
    if path is None:
        return [], problem
    try:
        raw = strictjson.read_owned(path, max_bytes=MAX_CODEX_BYTES)
    except strictjson.ReadRefused as exc:
        if exc.missing:
            return [], "這台電腦沒有 Codex 的模型快取"
        return [], f"讀不到 Codex 的模型快取（{exc}）"
    except Exception:  # noqa: BLE001 - the drop-down must still open
        return [], "讀不到 Codex 的模型快取"
    parsed = strictjson.loads_object(raw, CODEX_LIMITS)
    if not parsed.ok:
        return [], f"Codex 的模型快取格式不對（{parsed.problem}）"
    models = parsed.value.get("models")
    if not isinstance(models, list):
        return [], "Codex 的模型快取格式不對（沒有 models 清單）"
    rows: list[tuple[float, int, dict]] = []
    seen: set[str] = set()
    for index, item in enumerate(models[:MAX_CODEX_SCANNED]):
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        slug = item.get("slug")
        if not _safe_name(slug) or slug in seen:
            continue
        seen.add(slug)
        priority = item.get("priority")
        try:
            rank = float(priority) if _number(priority) and priority == priority else float("inf")
        except OverflowError:                # an integer with hundreds of digits
            rank = float("inf")
        rows.append((rank, index, {"value": slug, "label": _label(item.get("display_name"), slug)}))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows[:MAX_CODEX_OPTIONS]], ""


def _observed(sessions, tool: str, accept, skip: set[str]) -> list[dict]:
    """The model names the usage scan saw for ``tool``, most used first (then most recently used), at most MAX_OBSERVED."""
    counts: dict[str, int] = {}
    last: dict[str, str] = {}
    for sess in sessions if isinstance(sessions, list) else []:
        if not isinstance(sess, dict) or sess.get("tool") != tool or not isinstance(sess.get("models"), dict):
            continue
        stamp = sess.get("last_ts") if isinstance(sess.get("last_ts"), str) else ""
        for name, count in sess["models"].items():
            if not accept(name) or name in skip or not _number(count) or count <= 0:
                continue
            counts[name] = counts.get(name, 0) + int(count)
            if stamp > last.get(name, ""):
                last[name] = stamp
    order = sorted(counts)                                           # name, then newest use, then use count: each sort is stable
    order.sort(key=lambda n: last.get(n, ""), reverse=True)
    order.sort(key=lambda n: -counts[n])
    return [{"value": n, "label": n} for n in order[:MAX_OBSERVED]]


def build(home: Path, sessions) -> dict:
    """The ``model_options`` the catalog carries: per tool, ``latest`` (aliases), ``listed`` (the tool's own list),
    ``observed`` (names this computer's usage showed) and ``problem`` (why ``listed`` is empty, or "")."""
    claude_observed = _observed(sessions, "claude", lambda n: _safe_name(n) and n.startswith("claude-"), set())
    listed, problem = codex_models(home)
    codex_observed = _observed(sessions, "codex", _safe_name, {o["value"] for o in listed})
    return {
        "claude": {"latest": [{"value": a, "label": a} for a in CLAUDE_ALIASES], "listed": [],
                   "observed": claude_observed, "problem": ""},
        "codex": {"latest": [], "listed": listed, "observed": codex_observed, "problem": problem},
    }
