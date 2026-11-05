"""The AI tools VBear knows, written once.

Every other table of tools in the code (the ids a role card may name, their model families, which can be started in
full mode, the flag that carries a model id, the words the page shows) is made from REGISTRY. To add a tool, add one
entry here; tests/test_ai_tools.py shows that this is enough for the Python side, and keeps the few tables web/app.js
repeats (it has no import) equal to this one.

This module imports nothing from the rest of VBear, so the lowest modules (position_guide, flows) can use it.
The functions read REGISTRY when they are called, so a test can add an entry before the other modules are imported.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

# What a person is told when a card's tool has no safe launch and nothing more specific is written for it.
NOT_LAUNCHABLE_DEFAULT = "此 Agent 工具沒有受管啟動設定"


class Tool(NamedTuple):
    id: str                                  # also the executable's file name (full mode checks that they are equal)
    name: str                                # the long name the card pool and the card back show
    short: str                               # the short tag
    family: str                              # the model family the tool implies, for the team places
    species: Optional[str]                   # the office character of its camp; None when the camp has none
    generic: bool                            # True for the "shared" camp, which is no program and no model
    safe_launch: bool                        # the safe (sandboxed, managed) launch accepts it
    full_launch: bool                        # full mode can start it
    model_flag: Optional[str]                # the command-line flag that carries a model id in full mode
    hidden: bool                             # not offered until the person turns it on in the settings
    install_command: str                     # the vendor's own one-line install command ("" until it is recorded)
    login_command: str                       # the vendor's own login command ("" until it is recorded)
    status_command: Optional[tuple]          # the command that tells whether the person is logged in, if there is one
    family_enforced: bool                    # a role's family must equal `family` (flows stored before this keep loading)
    not_launchable_message: str              # why the safe launch refuses it ("" for the default sentence)


# The order is the order the camps are offered in, with the generic "shared" camp last.
REGISTRY: tuple[Tool, ...] = (
    Tool("claude", "Claude Code", "Claude Code", "anthropic", "bear", False, True, True, "--model", False,
         "", "", ("claude", "auth", "status"), False, ""),
    Tool("codex", "Codex CLI", "Codex", "openai", "robot", False, True, True, "-m", False,
         "", "", ("codex", "login", "status"), False, ""),
    # Antigravity: the safe launch never starts it; full mode does (as a terminal, with the person's own settings).
    Tool("agy", "Antigravity（AGY）", "AGY", "google", "fox", False, False, True, "--model", False,
         "", "", None, True, "VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄"),
    Tool("shared", "共用（skills CLI）", "共用卡", "unknown", None, True, False, False, None, False,
         "", "", None, False, "shared 不是可啟動的工具"),
)


def ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY)


def generic_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.generic)


def family_map() -> dict[str, str]:
    return {t.id: t.family for t in REGISTRY}


def safe_launch_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.safe_launch)


def full_launch_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.full_launch)


def model_flags() -> dict[str, str]:
    return {t.id: t.model_flag for t in REGISTRY if t.full_launch and t.model_flag}


def family_enforced_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.family_enforced)


def not_launchable_messages() -> dict[str, str]:
    """Why the safe launch refuses each tool it does not start."""
    return {t.id: t.not_launchable_message or NOT_LAUNCHABLE_DEFAULT for t in REGISTRY if not t.safe_launch}


def view() -> list[dict]:
    """The list the server hands to the page: names and abilities only, never a command."""
    return [{"id": t.id, "name": t.name, "short": t.short, "family": t.family, "generic": t.generic,
             "safe_launch": t.safe_launch, "full_launch": t.full_launch, "hidden": t.hidden} for t in REGISTRY]
