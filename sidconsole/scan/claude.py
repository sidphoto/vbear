"""Claude Code source adapter: skills, plugin activation state, subagents."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config as cfg
from ..model import (
    ACT_ACTIVE, ACT_ARCHIVED, ACT_DISABLED, ACT_NOT_INSTALLED, ACT_NOT_LOADED,
    ACT_SUPERSEDED, ACT_UNKNOWN, AgentRole, SkillRecord, Sourced, stable_id,
    unread_activation,
)
from . import document, walk

def CLAUDE_HOME() -> Path:
    """Per-call Claude Code home directory.

    Resolved on every call so tests which mutate ``os.environ['HOME']`` after
    import see the new fake-home. Equivalent to ``Path.home() / '.claude'``
    in production.
    """
    return Path.home() / ".claude"


# --- activation evidence ---------------------------------------------------

def load_activation_facts() -> dict:
    """Read the two files Claude Code uses to decide what is actually loaded.

    installed_plugins.json -> which cached copy is the installed one
    settings.json enabledPlugins -> whether the user switched it off
    Both are read-only inputs; absence is reported, never assumed.
    """
    facts = {"installed": {}, "enabled": {}, "problems": []}

    installed_path = CLAUDE_HOME() / "plugins" / "installed_plugins.json"
    if installed_path.exists():
        try:
            data = json.loads(installed_path.read_text(encoding="utf-8"))
            for key, entries in (data.get("plugins") or {}).items():
                for entry in entries or []:
                    path = entry.get("installPath")
                    if path:
                        facts["installed"][str(Path(path))] = {
                            "plugin": key,
                            "version": entry.get("version", ""),
                            "commit": entry.get("gitCommitSha", ""),
                            "scope": entry.get("scope", ""),
                            "installed_at": entry.get("installedAt", ""),
                        }
        except (OSError, ValueError) as exc:
            facts["problems"].append(f"無法解析 installed_plugins.json：{exc}")
    else:
        facts["problems"].append("找不到 installed_plugins.json，外掛安裝狀態未知")

    settings_path = CLAUDE_HOME() / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            facts["enabled"] = dict(data.get("enabledPlugins") or {})
        except (OSError, ValueError) as exc:
            facts["problems"].append(f"無法解析 settings.json：{exc}")
    else:
        facts["problems"].append("找不到 settings.json，外掛啟用狀態未知")

    return facts


def _plugin_key_from_cache_path(path: Path) -> tuple[str, str, str]:
    """~/.claude/plugins/cache/<owner>/<plugin>/<version>/... -> key, version, dir."""
    parts = path.parts
    try:
        i = len(parts) - 1 - parts[::-1].index("cache")
    except ValueError:
        return "", "", ""
    if len(parts) < i + 4:
        return "", "", ""
    owner, plugin, version = parts[i + 1], parts[i + 2], parts[i + 3]
    install_dir = str(Path(*parts[: i + 4]))
    return f"{plugin}@{owner}", version, install_dir


def plugin_manifest(install_dir: str) -> dict:
    path = Path(install_dir) / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _declared_paths(manifest: dict, field: str, default: str) -> list[str]:
    value = manifest.get(field)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return [default]


def in_plugin_skill_load_path(skill_md: Path, install_dir: str) -> bool:
    """Plugin skills load from <dir>/<name>/SKILL.md, exactly one level deep,
    under each skills path the manifest declares (default ./skills)."""
    manifest = plugin_manifest(install_dir)
    for rel in _declared_paths(manifest, "skills", "./skills"):
        base = (Path(install_dir) / rel).resolve()
        if skill_md.parent.parent.resolve() == base:
            return True
    return False


def classify(path: Path, source: cfg.Source, facts: dict) -> tuple[str, str, str, dict]:
    """Return (scope, activation, reason, origin_package)."""
    text_path = str(path)

    if cfg.is_archive_path(text_path):
        return source.scope, ACT_ARCHIVED, "位於備份或暫存目錄，不是載入路徑", {}

    if source.kind == "skills":
        if "/synced/" in text_path.replace("\\", "/"):
            return "synced", ACT_ACTIVE, "使用者技能目錄（雲端同步），Claude Code 會載入", {}
        return "user", ACT_ACTIVE, "使用者技能目錄，Claude Code 會載入", {}

    if source.kind == "plugin_cache":
        key, version, install_dir = _plugin_key_from_cache_path(path)
        if not key:
            return "plugin", ACT_UNKNOWN, "無法從路徑判讀外掛身分", {}
        record = facts["installed"].get(install_dir)
        pkg = {"plugin": key, "version": version}
        if record is None:
            newer = sorted(
                (v["version"], k) for k, v in facts["installed"].items() if v["plugin"] == key
            )
            if newer:
                pkg["installed_version"] = newer[-1][0]
                return ("plugin", ACT_SUPERSEDED,
                        f"此為 {version} 的舊快取；目前安裝的是 {newer[-1][0]}", pkg)
            return "plugin", ACT_UNKNOWN, "installed_plugins.json 沒有對應這份快取", pkg
        pkg.update({"commit": record["commit"], "installed_at": record["installed_at"]})
        if not in_plugin_skill_load_path(path, install_dir):
            return ("plugin", ACT_NOT_LOADED,
                    "隨外掛附帶，但不在外掛的技能載入路徑（例如作者開發用或 upstream 副本）", pkg)
        enabled = facts["enabled"].get(key)
        if enabled is True:
            return "plugin", ACT_ACTIVE, f"外掛 {key} 已安裝且在 settings.json 中啟用", pkg
        if enabled is False:
            return ("plugin", ACT_DISABLED,
                    f"外掛 {key} 已安裝，但在 settings.json 中設為停用", pkg)
        return ("plugin", ACT_UNKNOWN,
                f"外掛 {key} 已安裝，settings.json 未記錄啟用狀態", pkg)

    if source.kind == "marketplace":
        return ("marketplace", ACT_NOT_INSTALLED,
                "市集來源副本；實際載入的是 plugins/cache 內的安裝版本", {})

    return source.scope, ACT_UNKNOWN, "未知來源類型", {}


# --- skills ----------------------------------------------------------------

def scan_skills(source: cfg.Source, facts: dict) -> list[SkillRecord]:
    root = source.resolved()
    records: list[SkillRecord] = []
    for path in walk.find_files(root, "SKILL.md"):
        try:
            records.append(_build_skill(path, root, source, facts))
        except Exception as exc:  # one hostile file must not stop the scan
            records.append(failed_record(source.tool, path, root, exc))
    return records


def failed_record(tool: str, path: Path, root: Path, exc: Exception) -> SkillRecord:
    """Placeholder for a SKILL.md that could not be processed. Carries only the
    path and the error type, never file content."""
    return SkillRecord(
        skill_id=stable_id(tool, str(path)),
        name=path.parent.name,
        tool=tool,
        scope="unknown",
        activation=ACT_UNKNOWN,
        activation_reason="解析時發生錯誤，無法判斷",
        path=str(path),
        root=str(root),
        warnings=[f"無法解析此技能（{type(exc).__name__}），已略過內容"],
    )


def _build_skill(path: Path, root: Path, source: cfg.Source, facts: dict) -> SkillRecord:
    raw = document.read_skill_file(path, root)
    skill_dir = path.parent
    scope, activation, reason, pkg = classify(path, source, facts)

    if "skipped" in raw:  # outside the source root or too large: no content
        activation, reason = unread_activation(activation, reason, raw["skipped"])
        return SkillRecord(
            skill_id=stable_id(source.tool, str(path)),
            name=skill_dir.name,
            tool=source.tool,
            scope=scope,
            activation=activation,
            activation_reason=reason,
            path=str(path),
            root=str(root),
            warnings=[raw["skipped"]],
            origin_package=pkg,
        )

    if "error" in raw:
        return SkillRecord(
            skill_id=stable_id(source.tool, str(path)),
            name=skill_dir.name,
            tool=source.tool,
            scope=scope,
            activation=ACT_UNKNOWN,
            activation_reason=reason,
            path=str(path),
            root=str(root),
            warnings=[raw["error"]],
        )

    meta = raw["frontmatter"]
    body = raw["body"]
    warnings = list(raw["warnings"])

    name = str(meta.get("name") or skill_dir.name).strip()
    if meta.get("name") and str(meta["name"]).strip() != skill_dir.name:
        warnings.append(
            f'front matter 名稱「{meta["name"]}」與資料夾名稱「{skill_dir.name}」不同'
        )

    sections = document.extract_sections(body)
    refs, missing = document.referenced_files(body, skill_dir)

    description = (
        Sourced.author(document.redact(str(meta["description"])), "SKILL.md front matter: description")
        if meta.get("description")
        else Sourced.missing("front matter 未提供 description")
    )
    if not meta.get("description"):
        warnings.append("front matter 缺少 description，工具無法判斷何時該使用這個技能")

    deps = sections.get("dependencies") or Sourced.missing("文件未說明相依需求")
    if meta.get("allowed-tools"):
        deps = Sourced.author(
            document.redact(_as_text(meta["allowed-tools"])), "SKILL.md front matter: allowed-tools"
        )

    try:
        stat = path.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        size, mtime = 0, 0.0

    return SkillRecord(
        skill_id=stable_id(source.tool, str(path)),
        name=name,
        tool=source.tool,
        scope=scope,
        activation=activation,
        activation_reason=reason,
        path=str(path),
        root=str(root),
        description=description,
        when_to_use=sections.get("when_to_use") or Sourced.missing("文件未標示使用時機章節"),
        inputs=sections.get("inputs") or Sourced.missing("文件未標示輸入章節"),
        outputs=sections.get("outputs") or Sourced.missing("文件未標示產出章節"),
        dependencies=deps,
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


def _as_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def _safe_meta(meta: dict) -> dict:
    """Front matter for display and the index. A secret-named key (api_key,
    apiKey, access_token, password, ...) loses its whole value, at any depth;
    other text still goes through the pattern redaction."""
    out = {}
    for key, value in meta.items():
        clean = document.redact_value(key, value)
        if isinstance(clean, (str, int, float, bool)) or clean is None:
            out[key] = clean
        else:
            out[key] = document.redact(_as_text(clean))
    return out


# --- subagents -------------------------------------------------------------

def scan_agents(source: cfg.Source) -> list[AgentRole]:
    root = source.resolved()
    roles: list[AgentRole] = []
    for path in walk.find_by_suffix(root, ".md", max_depth=2):
        try:
            raw = document.read_skill_file(path, root)
        except Exception:  # hostile file: skip it, keep scanning
            continue
        if "error" in raw or "skipped" in raw:
            continue
        meta = raw["frontmatter"]
        name = str(meta.get("name") or path.stem)
        desc = meta.get("description")
        roles.append(
            AgentRole(
                role_id=stable_id("claude-role", str(path)),
                name=name,
                tool="claude",
                kind="subagent",
                path=str(path),
                description=(
                    Sourced.author(document.redact(str(desc)), f"{path.name} front matter: description")
                    if desc else Sourced.missing("front matter 未提供 description")
                ),
                model=(
                    Sourced.author(str(meta["model"]), f"{path.name} front matter: model")
                    if meta.get("model") else Sourced.missing("未指定模型，沿用主 Agent 設定")
                ),
                emoji=str(meta.get("emoji") or ""),
                color=str(meta.get("color") or ""),
                warnings=[document.redact(w) for w in raw["warnings"]],
                skill_link_basis="claude-subagent",
            )
        )
    return roles


def scan_plugin_agents(facts: dict) -> list[AgentRole]:
    """Agents that installed plugins declare in plugin.json. Only the installed
    copy counts; enable state comes from settings.json."""
    roles: list[AgentRole] = []
    for install_dir, record in facts["installed"].items():
        manifest = plugin_manifest(install_dir)
        declared = manifest.get("agents")
        if isinstance(declared, str):
            declared = [declared]
        if not isinstance(declared, list):
            continue
        key = record["plugin"]
        enabled = facts["enabled"].get(key)
        prefix = key.split("@", 1)[0]
        for rel in declared:
            if not isinstance(rel, str):
                continue
            path = (Path(install_dir) / rel).resolve()
            try:
                # the manifest path must stay inside the plugin's install dir
                raw = document.read_skill_file(path, Path(install_dir))
            except Exception:
                continue
            if "error" in raw or "skipped" in raw:
                continue
            meta = raw["frontmatter"]
            desc = meta.get("description")
            warnings = [document.redact(w) for w in raw["warnings"]]
            if enabled is False:
                warnings.append(f"外掛 {key} 在 settings.json 中停用，此角色目前不可用")
            elif enabled is None:
                warnings.append(f"外掛 {key} 的啟用狀態未記錄")
            roles.append(AgentRole(
                role_id=stable_id("claude-plugin-role", str(path)),
                name=f"{prefix}:{meta.get('name') or path.stem}",
                tool="claude",
                kind="subagent",
                path=str(path),
                description=(
                    Sourced.author(document.redact(str(desc)), f"{path.name} front matter: description")
                    if desc else Sourced.missing("front matter 未提供 description")
                ),
                model=(
                    Sourced.author(str(meta["model"]), f"{path.name} front matter: model")
                    if meta.get("model") else Sourced.missing("未指定模型，沿用主 Agent 設定")
                ),
                emoji=str(meta.get("emoji") or ""),
                color=str(meta.get("color") or ""),
                warnings=warnings,
                skill_link_basis="claude-subagent",
            ))
    return roles
