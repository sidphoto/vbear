"""The first CEO (v0.13, P38-8): what the page needs to lead a person who has finished the start-up, and has no role card to
chat with yet, to make one.

``plan(profiles, tool_rows)`` answers three things and makes nothing:

* ``needed``: the person has no card they can chat with (an enabled card on Claude Code, Codex or AGY). A person who has one is
  not shown the step.
* which AI tool the card would use: a ready Claude Code, otherwise a ready Codex, otherwise a ready AGY (P46-5; its chat
  still has to pass the check, which the plan says in ``chat_note``). A tool that is ready only because the person pressed
  「我登入好了」 (Grok, MCODE) cannot chat, so it is never chosen. With none ready the plan says to go back to the start-up
  (``go``), and nothing can be made.
* the words to fill in: the name, the instructions and the opening sentence of the first chat. All three are only a
  starting point the person can change; the opening sentence is put in the chat's box and never sent by anything but the
  person's own press of the send button.

The card is made by the ordinary POST /api/agent-profiles, in safe mode, like any card: a CEO is a plain role card (the
chief of staff, who plans which employees are needed, is a later release). The rows carry no path and no command.
"""

from __future__ import annotations

from . import chat_service

NAME = "CEO"
POSITION = "planner"            # the position that is labelled CEO (agent_profiles.POSITION_TABLE)
LAUNCH_MODE = "safe"            # ADR 0002: a new card starts in safe mode
# The tools in the order they are tried, and what the person is told they are called.
TOOLS = (("claude", "Claude Code"), ("codex", "Codex"), ("agy", "AGY"))
INSTRUCTIONS = (
    "你是我的 CEO（執行長）。我不是工程師，請用一般人聽得懂的話跟我說話，不要用術語。\n"
    "我來找你的時候，通常還不知道要做什麼。請先問我幾個簡單的問題，了解我想做什麼，再幫我把想法整理成一份簡單的計畫："
    "要做哪幾件事、先做哪一件、哪些事需要我決定。\n"
    "凡是要花錢、對外發布、刪除資料或改動檔案的事，先告訴我你打算做什麼，等我說可以再做。"
)
OPENING = "你好，請先問我三個問題，了解我想做什麼。"
SETUP_REASON = "目前沒有已經就緒、而且能聊天的 AI 工具（Claude Code、Codex 或 AGY）。先到「開始設定」把其中一個裝好、登入。"
CODEX_CHAT_NOTE = ("Codex 聊天要用另一份登入：先到「開始設定」按「讓聊天用的 Codex 登入」，登入之後才能和 CEO 聊。"
                   "員工現在還是可以先建立。")
AGY_CHAT_NOTE = ("AGY 要先到聊天頁按「驗證聊天」（會用你的 Google 方案跑十幾則很短的對話），驗證通過之後才能和 CEO 聊。"
                 "員工現在還是可以先建立。")


def _can_chat(profile) -> bool:
    return isinstance(profile, dict) and chat_service.card_gate(profile)[0]


def _not_ready_reason(name: str) -> str:
    return f"你選的 {name} 還沒準備好，回開始設定把它準備好，或換一家。"


def _ready_tool(rows, wanted=None):
    """(tool id, name, row) of the first ready tool that can chat, or None. With ``wanted`` only that tool is looked at: it is
    never swapped for another one (P48-3)."""
    by_id = {r.get("id"): r for r in rows if isinstance(r, dict)}
    for tool_id, name in TOOLS:
        if wanted is not None and tool_id != wanted:
            continue
        row = by_id.get(tool_id)
        if row and row.get("ready") is True:
            return tool_id, name, row
    return None


def needed(profiles) -> bool:
    """True when no card can be chatted with. Asked first, so that a person who has one costs the lobby no look at the tools."""
    return not any(_can_chat(p) for p in profiles if isinstance(p, dict))


def plan(profiles, tool_rows, wanted=None) -> dict:
    """``tool_rows`` are ai_tool_status.report rows; they are only read when the step is needed (pass [] otherwise).

    ``wanted`` (P48-3, ADR 0014): the AI the person picked in the start-up (``claude``, ``codex`` or ``agy``). The card is
    planned on that one or not at all: when it is not ready the plan says so plainly (``reason``) and goes back to the
    start-up, it never picks another tool for the person. Anything else raises ValueError. ``None`` keeps the old order."""
    if wanted is not None and wanted not in dict(TOOLS):
        raise ValueError("tool 必須是 claude、codex 或 agy")
    needed_now = needed(profiles)
    out = {"ok": True, "needed": needed_now, "can_create": False, "go": None, "reason": "", "tool": None, "tool_name": None,
           "name": NAME, "position": POSITION, "launch_mode": LAUNCH_MODE, "instructions": INSTRUCTIONS, "opening": OPENING,
           "chat_ready": None, "chat_note": ""}
    if not needed_now:
        return out
    found = _ready_tool(tool_rows, wanted)
    if found is None:
        out.update(go="setup", reason=SETUP_REASON if wanted is None else _not_ready_reason(dict(TOOLS)[wanted]))
        return out
    tool_id, name, row = found
    out.update(can_create=True, tool=tool_id, tool_name=name)
    if tool_id == "codex":
        login = row.get("chat_login") if isinstance(row.get("chat_login"), dict) else {}
        out["chat_ready"] = login.get("state") == "logged_in"
        if not out["chat_ready"]:
            out["chat_note"] = CODEX_CHAT_NOTE
    elif tool_id == "agy":
        chat = row.get("chat") if isinstance(row.get("chat"), dict) else {}
        out["chat_ready"] = chat.get("verified") is True
        if not out["chat_ready"]:
            out["chat_note"] = AGY_CHAT_NOTE
    return out
