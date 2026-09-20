"""Read a SKILL.md into structured, attributable pieces.

Nothing here invents content. Section text is copied from the document and
labelled DERIVED, meaning "this scanner found it under a heading that looks
like X", which is weaker than the author explicitly declaring the field.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..model import Sourced
from . import frontmatter

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.MULTILINE)
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_TICKED = re.compile(r"`([^`\n]{2,120})`")
MAX_FILE_BYTES = 256 * 1024  # same cap as the server's raw-file view
REDACTED = "[已遮蔽的機密值]"

# Credential detection (plan section 9). Three layers, all applied to every
# piece of text the console shows or stores: whole private-key blocks, bare
# token shapes that are recognisable without a key name, and "name: value" /
# "name=value" pairs whose name looks like a secret (quotes allowed, value up
# to the end of the line).
_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_BARE_TOKENS = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-ant-[A-Za-z0-9_-]{16,}"            # Anthropic
    r"|sk-[A-Za-z0-9_-]{20,}"               # OpenAI-style; length gate spares "sk-learn"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"          # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"                    # AWS access key id
    r"|xox[abprse]-[A-Za-z0-9-]{10,}"       # Slack
    r")"
)
# "Bearer <token>" outside a key/value line; the digit requirement keeps prose
# such as "bearer authentication" readable.
_BEARER = re.compile(r"(?i)\b(bearer\s+)(?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{8,}")
_KV_NAME = re.compile(
    r"(?<![A-Za-z0-9_$-])([\"']?)([A-Za-z_$][A-Za-z0-9_.$-]{0,79})\1\s*(?::(?!//)|=)\s*(?=\S)"
)
_NAME_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
# Name parts that mark a secret on their own, in any text.
_STRONG_PARTS = {
    "token", "tokens", "secret", "secrets", "password", "passwords", "passwd", "pwd",
    "credential", "credentials", "authorization", "bearer", "apikey", "passphrase",
}
# Front matter keys are short identifiers, so a lone "key", "auth" or "private"
# is treated as a secret there; in prose those words are too common.
_KEY_PARTS = _STRONG_PARTS | {"key", "keys", "auth", "private", "privatekey", "cookie"}


# Name parts that make the field describe a secret instead of holding one:
# a count or limit (max_tokens), where it lives (token_file, api_key_env) or
# what it is called (secret_name). Their values are numbers, paths and names.
_ABOUT_PARTS = {
    "max", "min", "count", "counts", "num", "number", "limit", "limits", "length", "len",
    "size", "budget", "usage", "used", "remaining", "total", "ttl", "expiry", "expires",
    "file", "files", "path", "paths", "dir", "env", "var", "name", "names", "url", "header",
    "type", "kind", "format", "field", "rotation",
}
# Database and data-structure keys, not credentials.
# "sub" is deliberately absent: a sub_key is a real derived or subscription key.
_STRUCT_KEY_PREFIXES = ("primary", "foreign", "sort", "partition", "composite", "unique",
                        "cache", "map", "dict", "hot", "short")


def secret_key_name(name: str, strict: bool = True) -> bool:
    """True when a field name (api_key, apiKey, ACCESS_TOKEN, ...) names a secret.

    strict=True is for structured keys (front matter); strict=False is for
    "name: value" found inside free text, where a bare "key:" is usually prose.
    Names that only describe a secret (max_tokens, token_file, primary_key)
    are not secrets themselves.
    """
    parts = [p.lower() for p in _NAME_PART.findall(name)]
    if not parts or _describes_only(parts) or _structure_key(parts):
        return False
    return _names_secret(parts, strict)


def _describes_only(parts: list[str]) -> bool:
    return bool(_ABOUT_PARTS & set(parts))


def _structure_key(parts: list[str]) -> bool:
    return parts[-1] in ("key", "keys") and len(parts) > 1 and parts[-2] in _STRUCT_KEY_PREFIXES


# Values that cannot be a credential: counts, paths, URLs without a query,
# ENV_VAR names and booleans. A describing name keeps only these visible.
# A path must actually look like one (a separator), and a URL must carry no
# user:password@ part; otherwise a random secret starting with "." or "/", or
# a credential embedded in an endpoint, would pass as harmless.
_HARMLESS_VALUE = re.compile(
    r"\s*(?:[\"'`]?)(?:-?\d+(?:\.\d+)?[kKmM]?|true|false|null|none|"
    r"(?:\.{1,2}/|~/|/[^/\s?#]+/)[^\s?#]*|https?://[^@\s?#]+|[A-Z][A-Z0-9_]{2,})"
    r"(?:[\"'`]?)\s*[,;]?\s*"
)


def secret_value_for(name: str, value: str, strict: bool = True) -> bool:
    """Whether `value`, stored under `name`, must be hidden.

    Secret names always hide their value. A name that only describes a secret
    (max_tokens, token_file, api_key_env) keeps its value visible only while
    that value is harmless; "secret_file: hunter2" is still hidden.
    """
    parts = [p.lower() for p in _NAME_PART.findall(name)]
    if not parts or _structure_key(parts):
        return False
    if not _describes_only(parts):
        return _names_secret(parts, strict)
    if not _names_secret(parts, strict):
        return False
    return not _HARMLESS_VALUE.fullmatch(value)


def _names_secret(parts: list[str], strict: bool) -> bool:
    if (_KEY_PARTS if strict else _STRONG_PARTS) & set(parts):
        return True
    joined = "".join(parts)
    if joined.endswith(("apikey", "accesskey", "privatekey", "secretkey", "signingkey",
                        "clientsecret", "authtoken")):
        return True
    return not strict and "key" in parts and len(parts) > 1

# Heading keyword -> field. Checked in order; first match wins per field.
_SECTION_KEYS = {
    "when_to_use": (
        "when to use", "when should", "use this when", "usage", "use cases",
        "triggers", "activation", "適用", "使用時機", "何時使用", "觸發",
    ),
    "inputs": (
        "input", "inputs", "arguments", "parameters", "prerequisite",
        "requirements", "you need", "輸入", "參數", "前置", "需要準備",
    ),
    "outputs": (
        "output", "outputs", "deliverable", "result", "produces", "returns",
        "輸出", "產出", "交付", "結果",
    ),
    "dependencies": (
        "dependencies", "dependency", "requires", "installation", "setup",
        "tools required", "相依", "依賴", "安裝", "需求工具",
    ),
}

_MAX_SECTION_CHARS = 1200


def redact(text: str) -> str:
    """Never surface anything shaped like a credential (plan section 9)."""
    if not text:
        return text
    text = _PEM_BLOCK.sub(REDACTED, text)
    text = _BARE_TOKENS.sub(REDACTED, text)
    lines = text.split("\n")
    block_indent = None  # inside "secret_name: |" block scalar: hide its lines
    for i, line in enumerate(lines):
        if block_indent is not None:
            if not line.strip() or len(line) - len(line.lstrip()) > block_indent:
                if line.strip():
                    lines[i] = line[: len(line) - len(line.lstrip())] + REDACTED
                continue
            block_indent = None
        for match in _KV_NAME.finditer(line):
            value = line[match.end():]
            if secret_value_for(match.group(2), value, strict=False):
                lines[i] = line[: match.end()] + REDACTED
                if value.strip() in ("|", "|-", "|+", ">", ">-", ">+"):
                    block_indent = len(line) - len(line.lstrip())
                break
        else:
            lines[i] = _BEARER.sub(lambda m: m.group(1) + REDACTED, line)
    return "\n".join(lines)


def redact_value(key, value):
    """Redact a parsed front-matter value; secret-named keys lose the whole value."""
    if isinstance(key, str) and secret_value_for(
            key, value if isinstance(value, str) else json.dumps(value, default=str)):
        return REDACTED
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(None, v) for v in value]
    return value


def headings_of(body: str) -> list[dict]:
    out = []
    for match in _HEADING.finditer(body):
        out.append({"level": len(match.group(1)), "text": match.group(2).strip()})
    return out


def public_headings(body: str, limit: int = 60) -> list[dict]:
    """Headings for display and the index, with credentials masked."""
    return [{"level": h["level"], "text": redact(h["text"])} for h in headings_of(body)[:limit]]


def section_text(body: str, heading_text: str) -> str:
    """Return the body under one heading, up to the next heading of <= level."""
    matches = list(_HEADING.finditer(body))
    for i, match in enumerate(matches):
        if match.group(2).strip() != heading_text:
            continue
        level = len(match.group(1))
        start = match.end()
        end = len(body)
        for later in matches[i + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return body[start:end].strip()
    return ""


def extract_sections(body: str) -> dict[str, Sourced]:
    found: dict[str, Sourced] = {}
    heads = headings_of(body)
    for field, keywords in _SECTION_KEYS.items():
        for head in heads:
            low = head["text"].lower()
            if not any(k in low for k in keywords):
                continue
            text = section_text(body, head["text"])
            if not text:
                continue
            clipped = text[:_MAX_SECTION_CHARS]
            if len(text) > _MAX_SECTION_CHARS:
                clipped += "…"
            found[field] = Sourced.derived(
                redact(clipped), f'SKILL.md 章節「{head["text"]}」'
            )
            break
    return found


def referenced_files(body: str, skill_dir: Path) -> tuple[list[dict], list[str]]:
    """Find in-package file references and check whether they resolve.

    Three outcomes, because "the file is not there" and "this path is not part
    of the package" are different claims:
      present    - the file exists inside the skill directory
      missing    - it names a package subdirectory that exists, but the file
                   does not: a real structural gap
      unresolved - it does not exist and does not point at a package
                   subdirectory, so it is probably illustrative, not a
                   dependency. Shown, but not reported as a defect.
    Only relative, non-URL paths are considered; the console never fetches
    external links.
    """
    candidates: set[str] = set()
    candidates.update(_MD_LINK.findall(body))
    for raw in _TICKED.findall(body):
        if "/" in raw and not raw.startswith(("http", "-", "$")) and " " not in raw:
            candidates.add(raw)

    results: list[dict] = []
    missing: list[str] = []
    for raw in sorted(candidates):
        ref = raw.split("#", 1)[0].strip()
        if not ref or ref.startswith(("http://", "https://", "mailto:", "//", "#")):
            continue
        if ref.startswith("/") or ref.startswith("~"):
            continue
        if any(ch in ref for ch in "{}<>*?"):
            continue  # templated placeholder, not a concrete file
        parts = Path(ref).parts
        if not parts or ".." in parts:
            continue
        if not re.search(r"\.[A-Za-z0-9]{1,8}$", ref):
            continue
        target = skill_dir / ref
        if target.exists():
            results.append({"ref": ref, "status": "present"})
            continue
        anchored = len(parts) > 1 and (skill_dir / parts[0]).is_dir()
        status = "missing" if anchored else "unresolved"
        results.append({"ref": ref, "status": status})
        if status == "missing":
            missing.append(ref)
    return results, missing


def contained_file(path: Path, root: Path) -> Path | None:
    """The real path of `path` when it resolves inside `root`, else None.

    Both sides are resolved, so a source root that is itself reached through
    a symlink still works; a SKILL.md symlinked to a file outside the source
    root does not.
    """
    try:
        real = path.resolve(strict=True)
        base = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return real if real.is_relative_to(base) and real.is_file() else None


def read_skill_file(path: Path, root: Path | None = None) -> dict:
    """Read one SKILL.md. Returns raw pieces; callers build the record.

    With `root`, the file must resolve inside it. A file that escapes the root
    or exceeds MAX_FILE_BYTES is not read at all: the result carries only a
    "skipped" message, so nothing from it can reach the index.
    """
    if root is not None:
        real = contained_file(path, root)
        if real is None:
            return {"skipped": "SKILL.md 指向來源目錄之外（符號連結），基於安全未讀取內容"}
        path = real
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return {"skipped": f"檔案超過 {MAX_FILE_BYTES // 1024}KB，未解析內容"}
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"無法讀取檔案：{exc}"}
    fm_text, body = frontmatter.split(text)
    meta, warnings = frontmatter.parse(fm_text)
    if not fm_text.strip():
        warnings.append("缺少 front matter（沒有 --- 區塊）")
    return {
        "frontmatter": meta,
        "body": body,
        "warnings": warnings,
        "raw": text,
    }
