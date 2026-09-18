"""Minimal YAML-subset parser for SKILL.md / agent .md front matter.

The console ships with zero third-party dependencies, so this covers the subset
that skill front matter actually uses: scalars, quoted scalars, nested maps,
block and inline sequences, and block scalars. Anything it cannot parse is
reported as a warning instead of being guessed at or silently dropped.
"""

from __future__ import annotations

import re

_DELIM = re.compile(r"^---\s*$")
_KEY = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.\-$]+)\s*:(?P<rest>.*)$")
_ITEM = re.compile(r"^(?P<indent>\s*)-\s?(?P<rest>.*)$")


def split(text: str) -> tuple[str, str]:
    """Return (front_matter_text, body). Empty front matter when absent."""
    lines = text.split("\n")
    if not lines or not _DELIM.match(lines[0]):
        return "", text
    for i in range(1, len(lines)):
        if _DELIM.match(lines[i]):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return "", text


def parse(text: str) -> tuple[dict, list[str]]:
    """Parse a front-matter block. Returns (mapping, warnings)."""
    warnings: list[str] = []
    lines = text.split("\n") if text else []
    value, _ = _parse_block(lines, 0, 0, warnings)
    if not isinstance(value, dict):
        if value not in (None, {}, []):
            warnings.append("front matter is not a key/value mapping")
        return {}, warnings
    return value, warnings


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _parse_block(lines, start: int, indent: int, warnings) -> tuple:
    """Parse one block at the given indent. Returns (value, next_index)."""
    mapping: dict = {}
    sequence: list = []
    i = start
    while i < len(lines):
        line = lines[i]
        if _is_blank(line):
            i += 1
            continue
        cur = _indent_of(line)
        if cur < indent:
            break

        item = _ITEM.match(line)
        if item and cur == indent:
            rest = item.group("rest").strip()
            if rest:
                inner = _KEY.match(item.group("rest"))
                if inner:
                    # "- key: value" starts a mapping inside the sequence item
                    offset = len(item.group(0)) - len(item.group("rest"))
                    sub_lines = [" " * offset + item.group("rest")] + lines[i + 1 :]
                    value, consumed = _parse_block(sub_lines, 0, offset, warnings)
                    sequence.append(value)
                    i += consumed
                    continue
                sequence.append(_scalar(rest))
            else:
                value, consumed = _parse_block(lines, i + 1, indent + 1, warnings)
                sequence.append(value)
                i = consumed
                continue
            i += 1
            continue

        key = _KEY.match(line)
        if key and cur == indent:
            name = key.group("key")
            rest = key.group("rest").strip()
            if rest in ("|", "|-", ">", ">-", "|+", ">+"):
                block, i = _block_scalar(lines, i + 1, indent, fold=rest[0] == ">")
                mapping[name] = block
                continue
            if rest == "":
                nxt = _peek(lines, i + 1)
                if nxt is not None and _indent_of(nxt) > indent:
                    value, i = _parse_block(lines, i + 1, _indent_of(nxt), warnings)
                    mapping[name] = value
                    continue
                mapping[name] = None
                i += 1
                continue
            mapping[name] = _scalar(rest)
            i += 1
            continue

        warnings.append(f"unparsed front-matter line: {line.strip()[:120]}")
        i += 1

    if sequence and mapping:
        warnings.append("front-matter block mixes list items and keys")
    if sequence:
        return sequence, i
    return mapping, i


def _peek(lines, i):
    while i < len(lines):
        if not _is_blank(lines[i]):
            return lines[i]
        i += 1
    return None


def _block_scalar(lines, start: int, parent_indent: int, fold: bool) -> tuple[str, int]:
    collected: list[str] = []
    i = start
    body_indent = None
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            collected.append("")
            i += 1
            continue
        cur = _indent_of(line)
        if cur <= parent_indent:
            break
        if body_indent is None:
            body_indent = cur
        collected.append(line[body_indent:])
        i += 1
    while collected and not collected[-1]:
        collected.pop()
    joined = " ".join(x.strip() for x in collected if x.strip()) if fold else "\n".join(collected)
    return joined, i


def _scalar(raw: str):
    text = raw.strip()
    if not text:
        return ""
    # strip a trailing comment only when it is clearly not part of a quoted value
    if text[0] not in "\"'" and " #" in text:
        text = text.split(" #", 1)[0].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in _split_inline(inner)]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        out = {}
        for part in _split_inline(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip()] = _scalar(v)
        return out
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _split_inline(inner: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote = None
    depth = 0
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts
