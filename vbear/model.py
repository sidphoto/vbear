"""Data model for VBear.

Design rule from the product plan (section 6.2 / 9): every user-visible claim
must carry where it came from. A value the scanner derived by reading document
structure is never presented as something the skill author asserted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any

# --- provenance ------------------------------------------------------------

AUTHOR = "author"  # stated by the skill/agent author in the source file
DERIVED = "derived"  # inferred by this scanner from file structure
RUNTIME = "runtime"  # observed from a running runtime session
MISSING = "missing"  # the source does not provide it


@dataclass
class Sourced:
    """A single field plus where it came from."""

    value: Any = None
    origin: str = MISSING
    detail: str = ""

    @staticmethod
    def author(value: Any, detail: str) -> "Sourced":
        return Sourced(value, AUTHOR, detail)

    @staticmethod
    def derived(value: Any, detail: str) -> "Sourced":
        return Sourced(value, DERIVED, detail)

    @staticmethod
    def runtime(value: Any, detail: str) -> "Sourced":
        return Sourced(value, RUNTIME, detail)

    @staticmethod
    def missing(detail: str) -> "Sourced":
        return Sourced(None, MISSING, detail)

    @property
    def present(self) -> bool:
        return self.value not in (None, "", [], {})


# --- activation ------------------------------------------------------------
# "Configured" and "in effect" are different things (plan section 4 and 9).

ACT_ACTIVE = "active"  # in a scope the tool loads, and not switched off
ACT_DISABLED = "disabled"  # installed but explicitly switched off
ACT_SUPERSEDED = "superseded"  # older cached copy; a newer version is installed
ACT_NOT_INSTALLED = "not_installed"  # available in a marketplace, not installed
ACT_ARCHIVED = "archived"  # backup / vendor import / temp; not a load path
ACT_NOT_LOADED = "not_loaded"  # shipped inside a package, but outside its load path
ACT_UNKNOWN = "unknown"  # we could not establish it from any source


def unread_activation(activation: str, reason: str, why: str) -> tuple[str, str]:
    """A skill whose file was not read cannot be called usable.

    The path may be in a load scope, but the console never saw the content
    (too large, or it leads outside its folder), so it cannot say the tool
    will load it cleanly. States that already say "not usable" are kept.
    """
    if activation != ACT_ACTIVE:
        return activation, reason
    return ACT_UNKNOWN, f"未讀取技能檔（{why}），無法確認能否正常載入；位置判讀：{reason}"


@dataclass
class SkillRecord:
    skill_id: str
    name: str
    tool: str  # "claude" | "codex"
    scope: str  # user | project | plugin | marketplace | system | vendor | backup
    activation: str
    activation_reason: str
    path: str
    root: str

    description: Sourced = field(default_factory=Sourced)
    when_to_use: Sourced = field(default_factory=Sourced)
    inputs: Sourced = field(default_factory=Sourced)
    outputs: Sourced = field(default_factory=Sourced)
    dependencies: Sourced = field(default_factory=Sourced)

    frontmatter: dict = field(default_factory=dict)
    headings: list = field(default_factory=list)
    referenced_files: list = field(default_factory=list)
    missing_files: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    origin_package: dict = field(default_factory=dict)
    size_bytes: int = 0
    mtime: float = 0.0
    body_chars: int = 0

    # filled in by the indexer
    duplicate_of: list = field(default_factory=list)

    def to_json(self) -> dict:
        return _dump(self)


@dataclass
class AgentRole:
    """A reusable agent configuration. Not a running session."""

    role_id: str
    name: str
    tool: str  # claude | codex
    kind: str  # "cli" (the tool itself) | "subagent"
    path: str = ""
    description: Sourced = field(default_factory=Sourced)
    capabilities: Sourced = field(default_factory=Sourced)
    suitable_tasks: Sourced = field(default_factory=Sourced)
    limits: Sourced = field(default_factory=Sourced)
    model: Sourced = field(default_factory=Sourced)
    emoji: str = ""
    color: str = ""
    warnings: list = field(default_factory=list)
    skill_link_ids: list = field(default_factory=list)
    skill_link_basis: str = ""

    def to_json(self) -> dict:
        return _dump(self)


@dataclass
class LiveSession:
    """One working terminal observed through the runtime."""

    terminal_id: str
    agent: str
    status: str
    workspace_id: str = ""
    tab_id: str = ""
    pane_id: str = ""
    cwd: str = ""
    title: str = ""
    session_ref: str = ""
    focused: bool = False
    project_id: str = ""

    def to_json(self) -> dict:
        return _dump(self)


@dataclass
class Project:
    project_id: str
    name: str
    path: str
    basis: str  # how we decided this is a project
    git_branch: str = ""
    session_ids: list = field(default_factory=list)
    workspace_ids: list = field(default_factory=list)

    def to_json(self) -> dict:
        return _dump(self)


def _dump(obj) -> dict:
    def factory(pairs):
        out = {}
        for k, v in pairs:
            out[k] = v
        return out

    raw = asdict(obj, dict_factory=factory)
    return raw


def stable_id(*parts: str) -> str:
    joined = "\x00".join(parts)
    return hashlib.sha256(joined.encode("utf-8", "replace")).hexdigest()[:16]
