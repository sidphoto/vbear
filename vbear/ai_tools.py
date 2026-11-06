"""The AI tools VBear knows, written once.

Every other table of tools in the code (the ids a role card may name, their model families, which can be started in
full mode, the flag that carries a model id, the words the page shows) is made from REGISTRY. To add a tool, add one
entry here; tests/test_ai_tools.py shows that this is enough for the Python side, and keeps the few tables web/app.js
repeats (it has no import) equal to this one.

This module imports nothing from the rest of VBear, so the lowest modules (position_guide, flows) can use it.
The functions read REGISTRY when they are called, so a test can add an entry before the other modules are imported.
"""

from __future__ import annotations

import shlex
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
    # safe_launch and safe_mode differ. safe_launch: the safe launch's code accepts the tool at all (agent_launch.launch_blockers
    # does not refuse it for being the wrong tool); it is true for claude and codex. safe_mode: the safe mode can really start the
    # tool in this build, so a new card may default to it and the page may call it a safe mode; it is true for claude only,
    # because Codex's interactive managed launch is refused (codex_interactive_flags_unsupported, ADR 0002). safe_mode implies
    # safe_launch. Nothing about safe_launch's behaviour depends on safe_mode.
    safe_launch: bool
    safe_mode: bool
    full_launch: bool                        # full mode can start it
    model_flag: Optional[str]                # the command-line flag that carries a model id in full mode
    hidden: bool                             # not offered until the person turns it on in the settings
    install_command: str                     # the vendor's own one-line install command ("" until it is recorded)
    login_command: str                       # the vendor's own login command ("" until it is recorded)
    status_command: Optional[tuple]          # the command that tells whether the person is logged in, if there is one
    family_enforced: bool                    # a role's family must equal `family` (flows stored before this keep loading)
    not_launchable_message: str              # why the safe launch refuses it ("" for the default sentence)
    # The start-up page (開始設定): when a tool has more than one way to log in, each is (region id, label, fixed line) and
    # login_command is "". version_pattern matches the first line `--version` prints, group 1 being the version; a tool
    # whose output does not match is not counted as installed. blurb is the one plain sentence the page shows.
    login_regions: tuple = ()
    version_pattern: str = ""
    blurb: str = ""


# The order is the order the camps are offered in, with the generic "shared" camp last.
REGISTRY: tuple[Tool, ...] = (
    Tool("claude", "Claude Code", "Claude Code", "anthropic", "bear", False, True, True, True, "--model", False,
         "curl -fsSL https://claude.ai/install.sh | bash", "claude auth login", ("claude", "auth", "status"), False, "",
         version_pattern=r"^(\d+\.\d+\.\d+) \(Claude Code\)$",
         blurb="Anthropic 做的。要有 Claude 的付費方案（Pro、Max、Team 等）或 Console 帳號，免費的 claude.ai 帳號不能用。"),
    Tool("codex", "Codex CLI", "Codex", "openai", "robot", False, True, False, True, "-m", False,
         "curl -fsSL https://chatgpt.com/codex/install.sh | sh", "codex login", ("codex", "login", "status"), False, "",
         version_pattern=r"^codex-cli (\d+\.\d+\.\d+)",
         blurb="OpenAI 做的。用你的 ChatGPT 帳號登入；哪些方案可以用，官方沒有寫清楚。"),
    # Antigravity: the safe launch never starts it; full mode does (as a terminal, with the person's own settings).
    Tool("agy", "Antigravity（AGY）", "AGY", "google", "fox", False, False, False, True, "--model", False,
         "curl -fsSL https://antigravity.google/cli/install.sh | bash", "agy", None, True,
         "安全模式不會啟動 AGY，要出發請選完整模式",
         version_pattern=r"^(\d+\.\d+\.\d+)$",
         blurb="Google 做的（Antigravity）。用個人 Google 帳號登入；公司帳號要有 Gemini Enterprise 授權。"),
    # Grok Build (xAI) and MiniMax Code: full mode only. The model flag is -m for both; the instructions are pasted. MCODE
    # is hidden: it is offered only while the person has turned on "show MCODE" (config key show_mcode).
    Tool("grok", "Grok", "Grok", "xai", "alien", False, False, False, True, "-m", False,
         "curl -fsSL https://x.ai/cli/install.sh | bash", "grok login", None, True,
         "Grok 目前只能用完整模式，VBear 不用安全模式啟動它，這張卡的安全模式只用來排隊伍與記錄",
         version_pattern=r"^grok (\d+\.\d+\.\d+)",
         blurb="xAI 做的。用 xAI 帳號登入；xAI 公告說 SuperGrok 與 X Premium Plus 的訂閱者可以用。"),
    Tool("mcode", "MCODE", "MCODE", "minimax", "alien", False, False, False, True, "-m", True,
         "curl -fsSL https://filecdn.minimax.chat/public/install.sh | bash", "", None, True,
         "MCODE 目前只能用完整模式，VBear 不用安全模式啟動它，這張卡的安全模式只用來排隊伍與記錄",
         login_regions=(("global", "國際區", "mcode login --region global"), ("cn", "中國區", "mcode login --region cn")),
         version_pattern=r"^(\d+\.\d+\.\d+)$",
         blurb="MiniMax 做的。用 MiniMax 帳號登入，國際區與中國區的帳號是分開的，登入時要選對。"),
    Tool("shared", "共用（skills CLI）", "共用卡", "unknown", None, True, False, False, False, None, False,
         "", "", None, False, "shared 不是可啟動的工具"),
)


SETUP_ACTIONS = ("install", "login", "chat_login")

# The Codex that chats (v0.13, ADR 0005) logs in to its own folder, <state>/codex-chat-home, never to the person's own
# ~/.codex: app-server always reads that folder's settings, so the chat needs another one. The line is fixed here; only the
# folder (which the runtime daemon makes from its own state folder, never from a request) is filled in, shell-quoted.
# The login state is read from the exit code of the status arguments below, nothing else.
CHAT_LOGIN = {"codex": {"line": "CODEX_HOME={home} codex login -c cli_auth_credentials_store=file",
                        "status_args": ("login", "status", "-c", "cli_auth_credentials_store=file")}}


def setup_ids() -> tuple[str, ...]:
    """The tools the start-up page lists: those with a recorded install line, in the order of REGISTRY."""
    return tuple(t.id for t in REGISTRY if t.install_command and not t.generic)


def _plain_folder(path) -> bool:
    return (isinstance(path, str) and path.startswith("/") and "\0" not in path
            and all(c.isprintable() for c in path))


def command_for(tool_id, action, region=None, *, chat_home=None) -> Optional[str]:
    """The one fixed line the start-up page may send to a terminal for (tool, action[, region]); None for anything the
    registry does not hold. The caller never supplies a command: it names a tool and an action, and this looks the line up.
    ``chat_home`` is the folder of the chat login (action "chat_login" only): an absolute path of printable characters
    that the daemon made itself."""
    if not isinstance(tool_id, str) or action not in SETUP_ACTIONS:
        return None
    t = next((x for x in REGISTRY if x.id == tool_id), None)
    if t is None or t.generic:
        return None
    if action == "chat_login":
        spec = CHAT_LOGIN.get(tool_id)
        if spec is None or region is not None or not _plain_folder(chat_home):
            return None
        return spec["line"].format(home=shlex.quote(chat_home))
    if action == "install":
        return (t.install_command or None) if region is None else None
    if t.login_regions:
        hit = next((line for rid, _label, line in t.login_regions if rid == region), None)
        return hit
    if region is not None:
        return None
    return t.login_command or None


def action_known(tool_id, action, region=None) -> bool:
    """Whether (tool, action[, region]) names a line at all (a request is checked with this before any folder is made)."""
    return command_for(tool_id, action, region, chat_home="/x") is not None


def chat_login_status_args(tool_id) -> Optional[tuple]:
    """The arguments after the program name that tell whether the chat login exists (only the exit code is read)."""
    spec = CHAT_LOGIN.get(tool_id) if isinstance(tool_id, str) else None
    return spec["status_args"] if spec else None


def ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY)


def generic_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.generic)


def family_map() -> dict[str, str]:
    return {t.id: t.family for t in REGISTRY}


def safe_launch_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.safe_launch)


def safe_mode_ids() -> tuple[str, ...]:
    """The tools whose safe mode can really start today (see Tool.safe_mode)."""
    return tuple(t.id for t in REGISTRY if t.safe_mode)


def full_launch_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.full_launch)


def model_flags() -> dict[str, str]:
    return {t.id: t.model_flag for t in REGISTRY if t.full_launch and t.model_flag}


def family_enforced_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.family_enforced)


def full_only_ids() -> tuple[str, ...]:
    """The tools full mode can start and the safe mode cannot start today (the card says "only full mode" for these):
    claude is the only tool with a safe mode (Tool.safe_mode), so Codex is among them although its safe_launch is True."""
    return tuple(t.id for t in REGISTRY if t.full_launch and not t.safe_mode)


def hidden_ids() -> tuple[str, ...]:
    return tuple(t.id for t in REGISTRY if t.hidden)


def show_key(tool_id) -> Optional[str]:
    """The server config key that switches a hidden tool on ("show_" + its id), or None for a tool that is not hidden."""
    return "show_" + tool_id if tool_id in hidden_ids() else None


def hidden_off(conf) -> tuple[str, ...]:
    """The hidden tools the person has not switched on. Only a real true switches one on."""
    conf = conf if isinstance(conf, dict) else {}
    return tuple(i for i in hidden_ids() if conf.get(show_key(i)) is not True)


def visible_ids(conf) -> tuple[str, ...]:
    """The tools a new card may name and the menus list: all, less the hidden ones that are switched off. A card that
    already names a hidden tool stays (ids() still has it); it is just not offered."""
    off = hidden_off(conf)
    return tuple(i for i in ids() if i not in off)


def hidden_message(tool_id) -> str:
    """Why a hidden tool that is switched off cannot be chosen or started."""
    t = next((x for x in REGISTRY if x.id == tool_id), None)
    name = t.name if t else str(tool_id)
    return (f"{name} 目前是隱藏的：到設定打開「顯示 {name}」後，才能選它或用它出發。"
            "已經建立的卡不會被刪除，只是先不能用。")


def hidden_blocker(tool_id) -> dict:
    """The launch blocker of a card whose tool is hidden and switched off, in the shape the launch code uses."""
    return {"code": "tool_hidden", "message": hidden_message(tool_id)}


def not_launchable_messages() -> dict[str, str]:
    """Why the safe launch refuses each tool it does not start."""
    return {t.id: t.not_launchable_message or NOT_LAUNCHABLE_DEFAULT for t in REGISTRY if not t.safe_launch}


def view(show_hidden: bool = False) -> list[dict]:
    """The list the server hands to the page: names and abilities only, never a command. A hidden tool is left out
    unless ``show_hidden`` (the caller says which ones the person switched on, with ``view_for``)."""
    return [_row(t) for t in REGISTRY if show_hidden or not t.hidden]


def _row(t: Tool) -> dict:
    return {"id": t.id, "name": t.name, "short": t.short, "family": t.family, "generic": t.generic,
            "safe_launch": t.safe_launch, "safe_mode": t.safe_mode, "full_launch": t.full_launch, "hidden": t.hidden,
            "not_launchable_message": "" if t.safe_launch else (t.not_launchable_message or NOT_LAUNCHABLE_DEFAULT)}


def view_for(conf) -> tuple[list[dict], list[dict]]:
    """(the tools to offer, the hidden tools that are switched off), both as ``view`` rows. The second list is what the
    page needs to word a card that already names one of them."""
    off = hidden_off(conf)
    return ([_row(t) for t in REGISTRY if t.id not in off], [_row(t) for t in REGISTRY if t.id in off])
