"""Bounded directory walking. Only inside user-chosen source roots."""

from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {".trash", ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea"}
MAX_DEPTH = 8


def find_files(root: Path, filename: str, max_depth: int = MAX_DEPTH) -> list[Path]:
    """Depth-limited search for `filename` under root, skipping noise dirs."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink() and entry.is_dir():
                    continue  # do not follow directory symlinks
                if entry.is_dir():
                    if entry.name in SKIP_DIRS or depth >= max_depth:
                        continue
                    stack.append((entry, depth + 1))
                elif entry.name == filename:
                    found.append(entry)
            except OSError:
                continue
    return sorted(found)


def find_by_suffix(root: Path, suffix: str, max_depth: int = 2) -> list[Path]:
    found: list[Path] = []
    if not root.is_dir():
        return found
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name in SKIP_DIRS or depth >= max_depth:
                        continue
                    stack.append((entry, depth + 1))
                elif entry.suffix == suffix:
                    found.append(entry)
            except OSError:
                continue
    return sorted(found)
