"""The chat engine table (P39-1): one row for each AI tool that can chat with a role card.

Everything that used to decide by ``if engine == "codex-chat"`` (which cards may chat, what chat.json holds, which launch
manifest is read, which method sends a message, what the support answer and the chat check say) asks this table. A new
engine, such as Grok's, is one more row here plus the methods the row names; no other place needs a new branch.

This module holds data only and imports nothing of VBear, so the store, the launch code, the daemon and the console can
all read it without a cycle. A hook is the NAME of a method or function on the object that uses it, found with
``getattr`` when it is needed: ``daemon_send`` on the daemon's ChatOps, ``manifest_problem`` and ``launch_settings`` on
runtime.agent_sessions, and ``state``/``binary``/``verifier`` (attributes), ``fields`` and ``verify`` (methods) on the
console's ChatService. Lookups read ``TABLE`` when they are called, so a test can put one more row in.
"""

from __future__ import annotations

from dataclasses import dataclass

_COMMON_FIELDS = frozenset({"v", "id", "profile_id", "created_at", "engine"})
CLAUDE_MONEY = ""          # Claude's money sentence stays in ChatService.support (its top-level answer)
CODEX_MONEY = ("聊天用你自己的 ChatGPT 方案，不另外收費。Codex 不回報金額，VBear 依 token 數估算（每 100 萬 token 計 US$1，至少 US$0.01）"
               "後算進每天上限；這是 VBear 的記帳規則，不是帳單。")


@dataclass(frozen=True)
class ChatEngine:
    engine: str                      # the chat's engine as chat.json and the launch manifest name it
    tool: str                        # the AI tool (ai_tools id) of the role card; also the ``engine`` of a verify request
    noun: str                        # what a launch is called in the sentences about it ("聊天", "Codex 聊天")
    check_mode: str                  # ``python -m vbear.boundary_check --mode <this>``
    uuid_fields: tuple = ()          # chat.json fields beyond the common ones; each is a fresh UUID when the chat is made
    # the daemon (runtime/daemon_chat.py ChatOps)
    daemon_send: str = ""            # method(rid, chat, text, cli, model_id, instructions): a person's message
    # the launch code (runtime/agent_sessions.py)
    manifest_problem: str = ""       # function(manifest) -> why it is not exactly this engine's manifest, or None
    launch_settings: str = ""        # function(manifest, workdir, scratch, uid, base) -> the settings the launch must hold
    # the console (chat_service.ChatService)
    support_key: str | None = None   # key of this engine's block in support(); None: the top-level answer is its own
    state: str = ""                  # attribute: function() -> the engine's state (what support() shows of it)
    binary: str | None = None        # attribute: function() -> (binary, version) or None
    verifier: str | None = None      # attribute: the object whose status() support() shows
    fields: str = ""                 # method(chat_id, text, profile) -> the fields of the daemon's chat_send
    verify: str = ""                 # method(wanted version) -> the answer of a 「驗證聊天」 request
    money: str = ""                  # the sentence about what a chat costs, shown with the support block

    def record_fields(self) -> frozenset:
        return _COMMON_FIELDS | frozenset(self.uuid_fields)


TABLE: tuple[ChatEngine, ...] = (
    ChatEngine(
        engine="claude-chat", tool="claude", noun="聊天", check_mode="chat", uuid_fields=("claude_session_id",),
        daemon_send="_claude_send", manifest_problem="chat_manifest_problem", launch_settings="_claude_chat_settings",
        support_key=None, state="claude", verifier="verifier", fields="_claude_fields", verify="_verify_claude",
        money=CLAUDE_MONEY),
    ChatEngine(
        engine="codex-chat", tool="codex", noun="Codex 聊天", check_mode="codex-chat",
        daemon_send="_codex_send", manifest_problem="codex_chat_manifest_problem", launch_settings="_codex_chat_settings",
        support_key="codex", state="codex", binary="codex_binary", verifier="codex_verifier", fields="_codex_fields",
        verify="_verify_codex", money=CODEX_MONEY),
)


def by_tool(tool) -> ChatEngine | None:
    """The row of an AI tool, or None when that tool cannot chat (anything that is not a known tool id is None)."""
    for row in TABLE:
        if row.tool == tool:
            return row
    return None


def by_engine(engine) -> ChatEngine | None:
    for row in TABLE:
        if row.engine == engine:
            return row
    return None


def engine_ids() -> tuple[str, ...]:
    return tuple(row.engine for row in TABLE)


def is_chat_engine(engine) -> bool:
    return by_engine(engine) is not None


def tools() -> tuple[str, ...]:
    return tuple(row.tool for row in TABLE)
