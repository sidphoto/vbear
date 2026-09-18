"""Read a SKILL.md into structured, attributable pieces.

Nothing here invents content. Section text is copied from the document and
labelled DERIVED, meaning "this scanner found it under a heading that looks
like X", which is weaker than the author explicitly declaring the field.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Sourced
from . import frontmatter

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.MULTILINE)
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_TICKED = re.compile(r"`([^`\n]{2,120})`")
_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|credential|authorization)\s*[:=]\s*\S+"
)

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
    return _SECRETISH.sub("[已遮蔽的機密值]", text)


def headings_of(body: str) -> list[dict]:
    out = []
    for match in _HEADING.finditer(body):
        out.append({"level": len(match.group(1)), "text": match.group(2).strip()})
    return out


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


def read_skill_file(path: Path) -> dict:
    """Read one SKILL.md. Returns raw pieces; callers build the record."""
    try:
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
