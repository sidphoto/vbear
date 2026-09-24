"""Codex CLI source adapter: skills, per-skill enable state, agent profiles."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .. import config as cfg
from ..model import (
    ACT_ACTIVE, ACT_ARCHIVED, ACT_DISABLED, ACT_UNKNOWN,
    AgentRole, SkillRecord, Sourced, stable_id, unread_activation,
)
from . import document, frontmatter, walk

def CODEX_HOME() -> Path:
    """Per-call Codex CLI home directory.

    Resolved on every call so tests which mutate ``os.environ['HOME']`` after
    import see the new fake-home. Equivalent to ``Path.home() / '.codex'``
    in production.
    """
    return Path.home() / ".codex"

# Labelled blocks inside developer_instructions ("Capabilities:" etc.). These
# are authored, explicitly labelled fields, so they count as AUTHOR evidence.
_BLOCK = re.compile(r"^(?P<label>[A-Z][A-Za-z ]{2,40}):\s*$", re.MULTILINE)
_BLOCK_FIELDS = {
    "capabilities": "capabilities",
    "suitable tasks": "suitable_tasks",
    "limits": "limits",
    "required output": "required_output",
}


def load_config_facts() -> dict:
    """Read only the non-secret keys the console needs from config.toml."""
    facts = {"skill_enabled": {}, "default_model": None, "default_effort": None, "problems": []}
    path = CODEX_HOME() / "config.toml"
    if not path.exists():
        facts["problems"].append("找不到 ~/.codex/config.toml，Codex 技能啟用狀態未知")
        return facts
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        facts["problems"].append(f"無法解析 config.toml：{exc}")
        return facts
    for entry in (data.get("skills") or {}).get("config") or []:
        if isinstance(entry, dict) and entry.get("path"):
            facts["skill_enabled"][str(Path(entry["path"]).expanduser())] = bool(entry.get("enabled", True))
    facts["default_model"] = data.get("model")
    facts["default_effort"] = data.get("model_reasoning_effort")
    return facts


def classify(path: Path, source: cfg.Source, facts: dict) -> tuple[str, str, str]:
    text = str(path)
    if cfg.is_archive_path(text):
        return source.scope, ACT_ARCHIVED, "位於備份或暫存目錄，不是載入路徑"
    scope = "system" if "/.system/" in text.replace("\\", "/") else source.scope
    explicit = facts["skill_enabled"].get(text)
    if explicit is False:
        return scope, ACT_DISABLED, "config.toml 的 skills.config 將此技能設為停用"
    if explicit is True:
        return scope, ACT_ACTIVE, "config.toml 的 skills.config 明確啟用"
    if scope == "system":
        return scope, ACT_ACTIVE, "Codex 內建系統技能目錄"
    return scope, ACT_ACTIVE, "位於 Codex 技能目錄，未被 config.toml 停用"


def scan_skills(source: cfg.Source, facts: dict) -> list[SkillRecord]:
    root = source.resolved()
    out: list[SkillRecord] = []
    for path in walk.find_files(root, "SKILL.md"):
        try:
            out.append(_build_skill(path, root, source, facts))
        except Exception as exc:  # one hostile file must not stop the scan
            from .claude import failed_record
            out.append(failed_record("codex", path, root, exc))
    return out


def _build_skill(path: Path, root: Path, source: cfg.Source, facts: dict) -> SkillRecord:
    scope, activation, reason = classify(path, source, facts)
    raw = document.read_skill_file(path, root)
    skill_dir = path.parent
    if "skipped" in raw:  # outside the source root or too large: no content
        activation, reason = unread_activation(activation, reason, raw["skipped"])
        return SkillRecord(
            skill_id=stable_id("codex", str(path)), name=skill_dir.name, tool="codex",
            scope=scope, activation=activation, activation_reason=reason,
            path=str(path), root=str(root), warnings=[raw["skipped"]],
        )
    if "error" in raw:
        return SkillRecord(
            skill_id=stable_id("codex", str(path)), name=skill_dir.name, tool="codex",
            scope=scope, activation=ACT_UNKNOWN, activation_reason=reason,
            path=str(path), root=str(root), warnings=[raw["error"]],
        )
    meta, body = raw["frontmatter"], raw["body"]
    warnings = list(raw["warnings"])
    name = str(meta.get("name") or skill_dir.name).strip()
    if meta.get("name") and str(meta["name"]).strip() != skill_dir.name:
        warnings.append(f'front matter 名稱「{meta["name"]}」與資料夾名稱「{skill_dir.name}」不同')
    if not meta.get("description"):
        warnings.append("front matter 缺少 description，工具無法判斷何時該使用這個技能")
    sections = document.extract_sections(body)
    refs, missing = document.referenced_files(body, skill_dir)
    try:
        stat = path.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        size, mtime = 0, 0.0

    rel = str(skill_dir.relative_to(root)) if skill_dir.is_relative_to(root) else skill_dir.name
    category = rel.split("/", 1)[0] if "/" in rel else ""
    pkg = {"category": category} if category and not category.startswith(".") else {}

    from .claude import _safe_meta  # shared sanitiser

    return SkillRecord(
        skill_id=stable_id("codex", str(path)),
        name=name,
        tool="codex",
        scope=scope,
        activation=activation,
        activation_reason=reason,
        path=str(path),
        root=str(root),
        description=(
            Sourced.author(document.redact(str(meta["description"])), "SKILL.md front matter: description")
            if meta.get("description") else Sourced.missing("front matter 未提供 description")
        ),
        when_to_use=sections.get("when_to_use") or Sourced.missing("文件未標示使用時機章節"),
        inputs=sections.get("inputs") or Sourced.missing("文件未標示輸入章節"),
        outputs=sections.get("outputs") or Sourced.missing("文件未標示產出章節"),
        dependencies=sections.get("dependencies") or Sourced.missing("文件未說明相依需求"),
        frontmatter=_safe_meta(meta),
        headings=document.public_headings(body),
        referenced_files=refs,
        missing_files=missing,
        warnings=[document.redact(w) for w in warnings],
        origin_package=pkg,
        size_bytes=size,
        mtime=mtime,
        body_chars=len(body),
    )


# --- agent profiles --------------------------------------------------------

def _labelled_blocks(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    matches = list(_BLOCK.finditer(text))
    for i, match in enumerate(matches):
        label = match.group("label").strip().lower()
        field = _BLOCK_FIELDS.get(label)
        if not field:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[match.end():end].strip()
        if chunk:
            found[field] = chunk
    return found


def _load_profiles_registry() -> dict:
    path = CODEX_HOME() / "agents" / "registry" / "PROFILES.yaml"
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > document.MAX_FILE_BYTES:
            return {}
        data, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}
    profiles = data.get("profiles") if isinstance(data, dict) else None
    return profiles if isinstance(profiles, dict) else {}


def scan_agents(source: cfg.Source, facts: dict) -> list[AgentRole]:
    root = source.resolved()
    registry = _load_profiles_registry()
    roles: list[AgentRole] = []
    if not root.is_dir():
        return roles
    for path in sorted(root.glob("*.toml")):
        warnings: list[str] = []
        real = document.contained_file(path, root)
        try:
            if real is None:
                raise ValueError("檔案指向代理目錄之外（符號連結），未讀取")
            if real.stat().st_size > document.MAX_FILE_BYTES:
                raise ValueError(f"檔案超過 {document.MAX_FILE_BYTES // 1024}KB，未解析")
            data = tomllib.loads(real.read_text(encoding="utf-8"))
        except Exception as exc:  # includes RecursionError from hostile nesting
            roles.append(AgentRole(
                role_id=stable_id("codex-role", str(path)), name=path.stem, tool="codex",
                kind="subagent", path=str(path),
                warnings=[f"無法解析：{document.redact(str(exc))[:200] or type(exc).__name__}"],
            ))
            continue
        instructions = str(data.get("developer_instructions") or "")
        blocks = _labelled_blocks(instructions)
        reg = registry.get(path.stem) if isinstance(registry.get(path.stem), dict) else {}

        def pick(field: str, reg_key: str) -> Sourced:
            if field in blocks:
                return Sourced.author(document.redact(blocks[field]),
                                      f"{path.name} developer_instructions「{field}」區塊")
            value = reg.get(reg_key) if reg else None
            if value:
                text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                return Sourced.author(document.redact(text), f"agents/registry/PROFILES.yaml: {path.stem}.{reg_key}")
            return Sourced.missing(f"{path.name} 未描述 {field}")

        model = data.get("model")
        if model:
            model_src = Sourced.author(str(model), f"{path.name}: model")
        elif facts.get("default_model"):
            model_src = Sourced.derived(
                str(facts["default_model"]),
                "Profile 未指定模型；此為 config.toml 的預設模型，實際執行時可能不同",
            )
        else:
            model_src = Sourced.missing("未指定模型")

        desc = data.get("description")
        roles.append(AgentRole(
            role_id=stable_id("codex-role", str(path)),
            name=str(data.get("name") or path.stem),
            tool="codex",
            kind="subagent",
            path=str(path),
            description=(Sourced.author(document.redact(str(desc)), f"{path.name}: description")
                         if desc else Sourced.missing("未提供 description")),
            capabilities=pick("capabilities", "capabilities"),
            suitable_tasks=pick("suitable_tasks", "suitable_tasks"),
            limits=pick("limits", "limits"),
            model=model_src,
            warnings=warnings,
            skill_link_basis="codex-profile",
        ))
    return roles
