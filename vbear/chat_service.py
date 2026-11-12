"""The console's side of chats with role cards (P36-2): what the pages /api/chats* read and ask of the runtime daemon.

The daemon owns the chat processes and is the only writer of a chat's record (vbear/runtime/daemon_chat.py). This
module asks it (``daemon_client.call``), reads the record files where only reading is needed (the list of chats), and
decides the things the console decides:

  * which role cards may chat: an enabled card whose tool is Claude Code, Codex or AGY. The tool decides the chat's engine
    (claude-chat, codex-chat or agy-chat) when the chat is opened, and the engine never changes. Checked when a chat is opened and
    again on every message, because a card can be switched off or changed later (a card whose tool changed to the other
    one cannot go on in the old chat: ``card_tool_changed``); a card of another tool, or a disabled one, is refused with
    the reason, never started;
  * what of the card goes into the chat: only the instructions the person wrote on the card (never the position's
    default text), passed to the daemon, which adds them to Claude Code's system prompt; and (P58, ADR 0020) the card's name and the
    label of its position, cleaned (``identity``), from which the daemon makes the one fixed sentence that tells the employee who it
    is. Both go to the company of the AI tool the employee runs on, with the conversation;
  * which Claude Code, Codex or AGY runs it (the pinned one), and whether that version may chat at all (``support``): the
    version has a chat-mode source list and a pass of the chat check, and no administrator policy is in the way; for
    Codex also the login of its own folder (vbear/runtime/codex_chat_env.py), for AGY its own settings folder and the
    person's hooks (vbear/runtime/agy_chat_env.py; AGY's login is the person's own, found out when a chat starts);
  * what of the person's memory goes into the chat (P42-1): the lines of ``memory.json`` (read only, never written here)
    unless the card has memory switched off or the file cannot be read; the daemon checks every line again;
  * whether the employee may use the shared folder (P43-1, ADR 0009): the person's switch for the card on the shared folder page
    (vbear/shared_folder.py, read only, off for everyone until the person turns it on), sent as ``shared: true`` and otherwise not at
    all; the daemon computes the path and checks the folder again;
  * what each code of the daemon means to a person (``CODE_TEXT``): every refusal the daemon can give has a
    sentence here, so the page never shows a bare code.

Nothing here starts a process or spends money by itself: a message is sent only by ``send``, which a person's press
of the send button reaches.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from pathlib import Path

from . import admin_policy, agent_profiles, ai_tools, board_engine, config as cfg, daemon_client, groups, meetings as mt
from . import memory as memory_store, routines as routines_store, shared_folder
from .api_error import ApiError
from .runtime import agent_sessions, agy_chat_env, chat_engines, chat_protocol as cp, chat_store as cs, cli_versions, codex_chat_env, memory_rules
from .runtime import shared_rules

LIST_MAX = 100                    # chats named in the list, newest first; the rest are counted
EXCERPT = 80                      # characters of the last message shown in the list
EVENTS_PAGE = 200                 # records of one answer
EVENTS_BYTES = 768 << 10          # about this many bytes of records in one answer (at least one record)
RESTART_TRIES = 8                 # a message the daemon asked to be sent again (``restarting``): tried this often,
RESTART_PAUSE = 1.0               # this many seconds apart, before the person is asked to send it again
DELETE_TRIES = 12
DELETE_PAUSE = 0.5
# The AI tools that can chat, and the engine each one's chats run on (fixed when the chat is opened), are the rows of
# runtime/chat_engines.TABLE.
CODEX_MONEY = chat_engines.CODEX_MONEY
POSITION_LABELS = {row["id"]: row["label"] for row in agent_profiles.POSITION_TABLE}
TOOL_LABEL = {**{t.id: t.name for t in ai_tools.REGISTRY if t.id not in ("claude", "codex", "agy", "shared")},
              "claude": "Claude Code", "codex": "Codex", "agy": "Antigravity（AGY）", "shared": "共用（不限工具）"}

# What each code means to a person, and the HTTP status the console answers with. The daemon's own message follows the
# explanation when it adds something (which card, which file). A test reads the codes the daemon, the session, the
# store and the launch code can give from their source files and checks that every one has a line here.
CODE_TEXT: dict[str, tuple[int, str]] = {
    "bad_request": (400, "送出的內容不符規定。"),
    "not_found": (404, "找不到這個聊天。"),
    "no_card": (404, "找不到這張角色卡。"),
    "card_disabled": (409, "這張角色卡已停用，啟用之後才能聊天。"),
    "card_tool_unsupported": (409, "聊天目前只支援工具是 Claude Code、Codex 或 AGY 的角色卡。"),
    "card_tool_changed": (409, "這張角色卡換了 AI 工具，原來的聊天不能再用，請開新的聊天。"),
    "refused": (409, "你按下允許的當下，VBear 又檢查了一次這個動作，發現現在已經不安全，所以拒絕了它（沒有執行）。"),
    "expired": (409, "這張卡片過了 5 分鐘還沒有回覆，已過期，VBear 視為拒絕（沒有執行）。"),
    "gone": (409, "這張卡片已經回覆過、已過期，或這一回合已經結束，不能再回覆。"),
    "bad_token": (403, "卡片的一次性憑證不符，VBear 沒有採用這次回覆。請重新整理後再按。"),
    "restarting": (409, "員工的程序正在換新的（模型、版本或額度不同，或同時聊天的員工太多），VBear 等了一會兒還沒換好。"
                        "你的訊息還沒有送出，請幾秒後再按一次送出。"),
    "spend_unknown": (409, "VBear 無法確認今天已經花了多少（某個聊天或會議的紀錄讀不完整），為了不超出每日上限，現在不送出。"
                           "這是保護，不是你的錯：請檢查 VBear 的狀態資料夾裡的紀錄，修好或移走有問題的檔案後再試。"),
    "damaged": (409, "這個聊天的紀錄有問題（檔案缺少、被改過或沒寫完），VBear 不會再動它：不往裡面寫、不能再送訊息，"
                     "也不能刪除（刪掉的話，已花的錢會從今天的額度裡消失）。請另開一個聊天，並檢查狀態資料夾裡的這個聊天。"),
    "bad_record": (409, "VBear 無法把這件事寫進聊天紀錄，所以沒有做。"),
    "red": (409, "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算。"),
    "budget": (409, "今天剩下的額度不到 US$0.01，不送出。"),
    "busy": (409, "員工還在處理上一則訊息（或這位員工正在另一個聊天裡工作），請等它回覆完，或先按停止。"),
    "limit": (429, "同時聊天的員工或背景程序的工作已經到上限，請稍後再試。"),
    "unsupported_python": (409, "執行 VBear 背景程序的 Python 太舊（沒有 os.waitid），無法安全管理聊天程序，所以不啟動。"
                                "請改用 Python 3.13 或更新的版本（macOS 內建的 /usr/bin/python3 是 3.9，不行）。"),
    "unverified": (409, "這個版本的聊天模式還沒有在這台 Mac 上通過驗證，不會啟動。"),
    "unsupported_version": (409, "VBear 沒有這個版本的聊天模式常數，不會啟動。"),
    "admin_policy": (409, "這台 Mac 上有管理員政策或系統設定，可能蓋過 VBear 的設定，所以不啟動聊天。"),
    "drift": (409, "AI 工具的檔案或設定在檢查之後改變了，VBear 不啟動它。請重新整理後再試。"),
    "invalid_binary": (409, "找不到可以安全啟動的 AI 工具程式（Claude Code、Codex 或 AGY）。"),
    "invalid_model": (409, "這張角色卡的模型名稱不能用在聊天。"),
    "invalid_workdir": (409, "員工的工作資料夾不符規定，不啟動。"),
    "unsafe_path": (409, "聊天用到的資料夾或檔案不是這個使用者擁有的私人檔案（或是連結），VBear 不使用它。"),
    "scratch_path_too_long": (409, "暫存資料夾的路徑太長，Claude Code 會改用共用暫存區，所以不啟動。"),
    "manifest_invalid": (409, "聊天程序的啟動資料不符規定，不啟動。"),
    "unsupported_sandbox": (409, "這台 Mac 的沙盒不能用在聊天，不啟動。"),
    "commit_not_enforceable": (409, "這個設定在這個版本不能確實執行，不啟動。"),
    "not_logged_in": (409, "聊天用的 Codex 還沒有登入（或查不出有沒有登入）。請到「開始設定」按「讓聊天用的 Codex 登入」。"),
    "codex_home": (409, "聊天用的 Codex 資料夾不能用（裡面有不是 VBear 放的設定檔、太大，或路徑不安全），VBear 不使用它。"),
    "agy_home": (409, "聊天用的 AGY 資料夾不能用（裡面有不是 VBear 放的設定、太大，或路徑不安全），VBear 不使用它。"
                      "請到 VBear 的狀態資料夾，把不是 VBear 放的那個項目移走後再試。"),
    "agy_hooks": (409, "你自己的 AGY 設定，或聊天資料夾往上的資料夾裡，有會自動執行的指令（hooks）或外掛。AGY 聊天會載入它們，VBear 管不到，所以不啟動。"
                       "請把括號裡寫的那一項（例如 ~/.agents/hooks.json；~/.agents、~/.agent、~/_agents、~/_agent 裡的 hooks.json、plugins.json 和 plugins 都算）移走後再試，"
                       "或把 VBear 的資料夾（VBEAR_HOME）放到別處；VBear 不會替你動它。"),
    "agy_workdir": (409, "員工的工作資料夾最上層有 AGY 會當成設定或規則來讀的項目（.agents、.agent、_agents、_agent、.gemini、GEMINI.md、AGENTS.md），"
                         "或有指向資料夾以外的連結，VBear 不讓 AGY 在那裡聊天。請把它移走後再試。"),
    "agy_version": (409, "讀不到 AGY 的版本，或 VBear 不能拿這個 AGY 來聊天（程式不安全、版本不在 VBear 認得的清單裡）。"),
    "manual_review": (409, "這個聊天之前的程序還沒確認已經結束，需要人工檢查 VBear 的狀態資料夾，之後才能再送訊息。"),
    "too_many": (409, "聊天已經太多，請先刪掉不用的。"),
    "full": (409, "這個聊天的紀錄已經滿了，請另開一個聊天。"),
    "storage": (503, "VBear 讀寫聊天紀錄時出了問題。"),
    "internal": (500, "VBear 內部出了問題，這則訊息沒有送出。"),
    "unavailable": (503, "VBear 的背景程序現在連不上。"),
    "bad_reply": (502, "背景程序的回應 VBear 看不懂。"),
    "claude_version": (409, "讀不到 Claude Code 的版本，不能聊天。"),
    "codex_version": (409, "讀不到 Codex 的版本，或它印出的版本和預期不同，不能聊天。"),
    "version_changed": (409, "AI 工具的版本在你預覽之後改變了，請重新整理。"),
    "verifying": (409, "聊天模式的驗證正在進行。"),
    "group_member_chat": (409, "這是群組裡的對話，請到群組裡說話。"),
    "memory_refused": (409, "記憶裡有一條現在不能送出，請到記憶頁看看。你的訊息還沒有送出。"),
    "shared_unsafe": (409, "共用資料夾的位置不安全（可能被換成連結或權限被改過），VBear 不會用它。請到共用資料夾頁看說明。你的訊息還沒有送出。"),
    "shared_full": (409, "共用資料夾超過 1 GiB 或 1 萬個檔案。請在 Finder 整理，或把這位員工的共用資料夾關掉。你的訊息還沒有送出。"),
    "shared_unverified": (409, "這個 AI 工具的版本還沒檢查過共用資料夾。按「檢查」（Claude Code 約 US$0.01；Codex 用你的 ChatGPT 方案；AGY 用你的 Google 方案），"
                               "或先把這位員工的共用資料夾關掉。你的訊息還沒有送出。"),
}

VERSION_TTL = 20.0                # seconds a looked-up version of an AI tool is kept for the pages that ask often (P43-2)

# Codes a person reads as "try again in a moment" rather than "something is wrong".
TRANSIENT = frozenset({"restarting", "busy"})


def explain(code: str, detail: str = "") -> str:
    """The sentence for a code, then the daemon's own words when they add something."""
    text = CODE_TEXT[code][1] if code in CODE_TEXT else "VBear 沒有送出這則訊息。"
    detail = (detail or "").strip()
    if detail and detail not in text and code not in ("restarting", "spend_unknown", "damaged", "refused", "expired"):
        text += f"（{detail[:300]}）"
    elif detail and code in ("refused", "spend_unknown", "damaged"):
        text += f"原因：{detail[:300]}"
    if code not in CODE_TEXT:
        text += f"（代碼：{code[:40]}）"
    return text


def api_error(code: str, detail: str = "", **extra) -> ApiError:
    status = CODE_TEXT[code][0] if code in CODE_TEXT else 500
    return ApiError(status, code, explain(code, detail), **extra)


def tool_label(tool) -> str:
    return TOOL_LABEL.get(tool, tool if isinstance(tool, str) and tool else "未指定")


def card_gate(profile) -> tuple[bool, str, str]:
    """(can chat, code, reason) for a role card as the person sees it now."""
    if not isinstance(profile, dict):
        return False, "no_card", CODE_TEXT["no_card"][1]
    if profile.get("enabled") is False:
        return False, "card_disabled", "這張角色卡已停用，啟用之後才能聊天。"
    model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
    if chat_engines.by_tool(model.get("tool")) is None:
        return False, "card_tool_unsupported", (
            f"這張角色卡的工具是 {tool_label(model.get('tool'))}，聊天目前支援 Claude Code、Codex 與 AGY。")
    return True, "", ""


def engine_of(profile) -> str | None:
    """The engine a chat with this card runs on, or None when its tool cannot chat."""
    model = profile.get("model") if isinstance(profile, dict) and isinstance(profile.get("model"), dict) else {}
    row = chat_engines.by_tool(model.get("tool"))
    return row.engine if row else None


def _default_claude() -> tuple[str | None, str | None, str]:
    """(binary, version, why not): the Claude Code a chat would run (P40-6: one VBear has chat constants for, on disk;
    else the one on PATH)."""
    from .runtime import native as rt_native
    res = cli_versions.check_cli_version("claude", rt_native._pinned_claude_chat_binary(), cwd=str(Path.home()),
                                         allow_unverified=True)
    if res.compatible and res.observed_version and res.binary_path:
        return res.binary_path, res.observed_version, ""
    return None, None, res.reason


def _default_agy_binary():
    """(binary, version) of the AGY that may chat, or None (not installed, not a version VBear knows, not verified...)."""
    try:
        pinned = agy_chat_env.pinned_binary()
    except agy_chat_env.AgyRefused:
        return None
    return pinned.binary, pinned.version


def unsupported_text(version: str) -> str:
    """The one wording for "VBear has no chat constants for this Claude Code": which versions it has, and what to do."""
    listed = "、".join(sorted(cp.VERSIONS, key=cli_versions._version_key))
    return (f"VBear 沒有 Claude Code {version} 的聊天模式常數，所以不能聊天。VBear 目前能聊天的版本：{listed}。"
            f"處理方式：安裝其中一個版本（放在 Claude Code 自己的版本資料夾裡，VBear 就會自動選用），或等 VBear 更新。")


def _excerpt(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EXCERPT else one[:EXCERPT - 1] + "…"


def summarize(chat: dict, events: cs.Events) -> dict:
    """The line of the chat list, from the chat's record alone: nothing here asks the daemon."""
    out = {"id": chat["id"], "profile_id": chat["profile_id"], "engine": chat.get("engine"),
           "created_at": chat["created_at"], "last_at": chat["created_at"],
           "last_kind": None, "last_text": "", "turns": 0, "spent_usd": "0", "open": False, "waiting": False,
           "problem": events.problem or None}
    if events.problem:
        return out
    state = cs.derive(events.records)
    spent = sum((t.cost if t.cost is not None else t.cap for t in state.turns), Decimal(0))
    decided = {r["card_id"] for r in events.records if r["kind"] == "card_decision"}
    asked = [r for r in events.records if r["kind"] == "card" and r["card_id"] not in decided]
    out.update(turns=len(state.turns), spent_usd=cs.usd(spent), open=state.open_turn is not None,
               waiting=state.open_turn is not None and any(r["turn"] == state.open_turn.turn for r in asked))
    for rec in reversed(events.records):
        if rec["kind"] in ("user_message", "reply"):
            out.update(last_at=rec["at"], last_kind="user" if rec["kind"] == "user_message" else "reply",
                       last_text=_excerpt(rec["text"]))
            break
    return out


class ChatService:
    """``runtime``: anything with ``_rpc(op, timeout, **fields)`` (the console's NativeRuntime). ``claude``: a function
    returning (binary, version, why not); the pinned Claude Code by default. ``codex``: a function returning the Codex chat
    state (codex_chat_env.status of the state folder by default); ``codex_binary``: a function returning (binary, version) of
    the pinned Codex, or None. ``agy`` and ``agy_binary`` are the same two questions for AGY (agy_chat_env.status of the state
    folder; (binary, version) of the pinned AGY, or None). ``verifier``: claude_verify.ChatVerifier; ``codex_verifier``:
    codex_verify.CodexChatVerifier; ``agy_verifier``: the AGY chat check's (P46-4).
    ``ledger``: a function returning the day's ledger (the meetings' runner, whose day the chats share)."""

    def __init__(self, runtime, *, claude=None, codex=None, codex_binary=None, verifier=None, codex_verifier=None,
                 ledger=None, profile=None, profiles=None, base=None, memory=None, shared=None, shared_verified=None,
                 agy=None, agy_binary=None, agy_verifier=None):
        self.runtime = runtime
        self.claude = claude or _default_claude
        self.codex = codex or (lambda: codex_chat_env.status(self.base))
        self.codex_binary = codex_binary or (lambda: codex_chat_env.pinned_binary())
        self.verifier = verifier
        self.codex_verifier = codex_verifier
        self.agy = agy or (lambda: agy_chat_env.status(self.base))
        self.agy_binary = agy_binary or _default_agy_binary
        self.agy_verifier = agy_verifier
        self.ledger = ledger
        self._profile = profile or (lambda pid: agent_profiles.get_profile_readonly(pid))
        self._profiles = profiles or (lambda: list(agent_profiles.load_all(None, None, mark_corrupt=False).values()))
        self._base = base
        self._memory = memory or memory_store.for_card          # a function: (role card id, engine) -> memory.ChatMemory (reads only)
        self._shared = shared or shared_folder.for_card         # a function: (role card id, engine) -> bool, the shared folder's switch (reads only)
        self._shared_verified = shared_verified or (lambda engine, version: cli_versions.shared_verified(engine, version))    # (engine, version) -> bool: passed the chat check with the folder
        self._versions: dict = {}                      # engine -> (when, version or None): the AI tool's version, looked up once in a while
        self.version_ttl = VERSION_TTL
        self.restart_tries, self.restart_pause = RESTART_TRIES, RESTART_PAUSE
        self.delete_tries, self.delete_pause = DELETE_TRIES, DELETE_PAUSE

    # ---- plumbing -----------------------------------------------------------------------------------------------

    @property
    def base(self) -> Path:
        return Path(self._base) if self._base is not None else cfg.state_dir()

    def _call(self, op: str, *, timeout: float = 10.0, **fields) -> dict:
        try:
            return daemon_client.call(self.runtime, op, timeout=timeout, **fields)
        except daemon_client.DaemonError as exc:
            raise api_error(exc.code, str(exc)) from exc

    def _card(self, profile_id) -> dict:
        """The role card a chat is with, when it may chat; ApiError (with the reason) when it may not."""
        try:
            profile = self._profile(profile_id)
        except agent_profiles.AgentProfileStorageError:
            raise ApiError(503, "storage", "角色資料無法讀取，請到角色頁處理（損毀的檔案不會在這裡被搬移）。") from None
        ok, code, reason = card_gate(profile)
        if not ok:
            raise ApiError(CODE_TEXT[code][0], code, reason)
        return profile

    def _chat(self, chat_id) -> dict:
        try:
            return cs.load(self.base, chat_id)
        except cs.ChatStoreError as exc:
            raise api_error(exc.code, exc.message) from None

    @staticmethod
    def _instructions(profile) -> str | None:
        """The card's own instructions, or None: never the position's default text (the most careful reading of
        「帶角色卡的指示」: only words the person wrote on this card go to the model)."""
        got = agent_profiles.instructions_of(profile)
        text = got["text"] if got["source"] == "custom" else None
        return text if isinstance(text, str) and agent_sessions.append_prompt_problem(text) is None else None

    @staticmethod
    def _identity(profile) -> dict | None:
        """``{"name", "position"}`` of the card as the employee is to be told (memory_rules.identity_parts: the name cleaned to one line and
        64 characters, the position's label from the table, never a custom word), or None when the name has nothing usable left. The
        daemon builds the sentence; this is only the two words."""
        if not isinstance(profile, dict):
            return None
        pos = agent_profiles.position_of(profile)
        return memory_rules.identity_parts(profile.get("name"), POSITION_LABELS.get(pos))

    # ---- support: may this Claude Code chat at all ----------------------------------------------------------------

    def support(self) -> dict:
        """What the page says before anyone types: the detected version, whether it has been verified for chats, and
        why not otherwise. Starts nothing. ``codex`` is the same question for the Codex that chats (P38-2: its own
        login folder, its pinned and verified version, the administrator policy); the other keys are Claude Code's."""
        binary, version, why = self.claude()
        out = {"engine": "claude-chat", "detected": version, "verified": [], "state": "unknown", "message": "", "policy": None,
               "verify": self.verifier.status() if self.verifier else None,
               "money": "聊天用你自己的 Claude 登入，會用掉你的 Claude 額度；金額是 Claude Code 回報的估值。"}
        for row in chat_engines.TABLE:
            if row.support_key is not None:
                out[row.support_key] = self._engine_support(row)
        out["verified"] = sorted(cli_versions.chat_verified_versions(), key=cli_versions._version_key)
        if version is None:
            out["message"] = f"讀不到 Claude Code 的版本（{why or '原因不明'}），無法確認聊天模式是否已通過驗證。"
            return out
        if cp.constants_for(version) is None:
            out.update(state="unsupported", message=unsupported_text(version))
            return out
        policy = admin_policy.check_claude(version, home=os.path.expanduser("~"))
        out["policy"] = {"ok": policy.ok, "found": policy.found, "problems": policy.problems,
                         "reason": policy.reason()}
        if not policy.ok:
            out.update(state="policy", message=policy.reason())
            return out
        if version not in cli_versions.chat_verified_versions():
            out.update(state="unverified", message=cli_versions.chat_unverified_text(version))
            return out
        out.update(state="verified")
        return out

    def _engine_support(self, row) -> dict:
        """The block of ``support()`` for an engine other than Claude Code's: its own state, its money sentence and the
        status of its verifier (the names of the three come from the engine's row)."""
        verifier = getattr(self, row.verifier, None)
        return dict(getattr(self, row.state)(), engine=row.engine, money=row.money,
                    verify=verifier.status() if verifier else None)

    def verify_start(self, body) -> dict:
        """「驗證聊天」: one real session with the pinned Claude Code (a few small model calls with the person's own
        login), or with ``{"engine": "codex"}`` the Codex chat check (about fourteen short calls on the person's own
        ChatGPT plan). Refused when the check could not pass anyway (no constants, an administrator policy). The
        ``engine`` is an AI tool of the engine table; its row names the method that answers."""
        if (not isinstance(body, dict) or set(body) - {"version", "engine", "shared"}
                or chat_engines.by_tool(body.get("engine", "claude")) is None or not isinstance(body.get("shared", False), bool)):
            raise ApiError(400, "bad_request", "只接受 version、engine（claude、codex 或 agy），和 shared（true 或 false）。")
        verify = getattr(self, chat_engines.by_tool(body.get("engine", "claude")).verify)
        return verify(body.get("version"), **({"shared": True} if body.get("shared") else {}))      # without shared the call is the one it was

    def _verify_claude(self, wanted, shared: bool = False) -> dict:
        if self.verifier is None:
            raise ApiError(503, "unavailable", "這個主控台沒有驗證功能。")
        binary, version, why = self.claude()
        if version is None:
            raise api_error("claude_version", why)
        if wanted is not None and wanted != version:
            raise ApiError(409, "version_changed", f"目前的 Claude Code 是 {version}，不是 {wanted}；請重新整理後再驗證。")
        if cp.constants_for(version) is None:
            raise ApiError(CODE_TEXT["unsupported_version"][0], "unsupported_version", unsupported_text(version))
        policy = admin_policy.check_claude(version, home=os.path.expanduser("~"))
        if not policy.ok:
            raise ApiError(409, "admin_policy", policy.reason())
        if version in cli_versions.chat_verified_versions() and (not shared or cli_versions.shared_verified("claude-chat", version)):
            return {"already_verified": True, "version": version, "status": self.verifier.status()}
        return {"status": self.verifier.start(binary, version)}

    # What a state of Codex that is not ready is refused with (the word of codex_chat_env.status, and its own sentence).
    CODEX_REFUSAL = {"not_installed": "invalid_binary", "unverified": "unverified", "policy": "admin_policy",
                     "folder": "codex_home", "version_unreadable": "codex_version", "not_logged_in": "not_logged_in"}

    def _codex_refusal(self, state: dict) -> ApiError:
        code = self.CODEX_REFUSAL.get(state.get("state"), "invalid_binary")
        why = state.get("why") if isinstance(state.get("why"), str) else ""
        return ApiError(CODE_TEXT[code][0], code, why.strip() or CODE_TEXT[code][1])

    def _verify_codex(self, wanted, shared: bool = False) -> dict:
        """``shared`` (P43-2): the person asks for the check because the version lacks the part made with the shared folder, so a
        version that passed the chat check before is checked again unless it has passed with the folder too."""
        if self.codex_verifier is None:
            raise ApiError(503, "unavailable", "這個主控台沒有驗證功能。")
        state = self.codex()
        version = state.get("version")
        if state.get("verified") is True and isinstance(version, str):
            if not shared or cli_versions.shared_verified("codex-chat", version):
                return {"already_verified": True, "version": version, "status": self.codex_verifier.status()}
            if state.get("state") != "ready":
                raise self._codex_refusal(state)
        elif state.get("state") != "unverified" or not isinstance(version, str):
            raise self._codex_refusal(state)
        if wanted is not None and wanted != version:
            raise ApiError(409, "version_changed", f"目前的 Codex 是 {version}，不是 {wanted}；請重新整理後再驗證。")
        policy = admin_policy.check_codex(version)
        if not policy.ok:
            raise ApiError(409, "admin_policy", policy.reason())
        return {"status": self.codex_verifier.start("", version)}

    # What a state of AGY that is not ready is refused with (the word of agy_chat_env.status, and its own sentence).
    AGY_REFUSAL = {"not_installed": "invalid_binary", "unsupported": "agy_version", "unverified": "unverified",
                   "policy": "admin_policy", "hooks": "agy_hooks", "folder": "agy_home", "version_unreadable": "agy_version"}

    def _agy_refusal(self, state: dict) -> ApiError:
        code = self.AGY_REFUSAL.get(state.get("state"), "invalid_binary")
        why = state.get("why") if isinstance(state.get("why"), str) else ""
        return ApiError(CODE_TEXT[code][0], code, why.strip() or CODE_TEXT[code][1])

    def _verify_agy(self, wanted, shared: bool = False) -> dict:
        """The AGY chat check (about fourteen short calls on the person's own Google plan), asked for by the page: refused when it
        could not pass anyway (no AGY, a version VBear has no constants for, an administrator policy, hooks, an unusable folder).
        A version that passed before is not checked again unless ``shared`` asks for the part made with the shared folder."""
        if self.agy_verifier is None:
            raise ApiError(503, "unavailable", "這個主控台沒有驗證功能。")
        state = self.agy()
        version = state.get("version")
        if state.get("verified") is True and isinstance(version, str):
            if not shared or cli_versions.shared_verified("agy-chat", version):
                return {"already_verified": True, "version": version, "status": self.agy_verifier.status()}
            if state.get("state") != "ready":
                raise self._agy_refusal(state)
        elif state.get("state") != "unverified" or not isinstance(version, str):
            raise self._agy_refusal(state)
        if wanted is not None and wanted != version:
            raise ApiError(409, "version_changed", f"目前的 AGY 是 {version}，不是 {wanted}；請重新整理後再驗證。")
        policy = admin_policy.check_agy(version)
        if not policy.ok:
            raise ApiError(409, "admin_policy", policy.reason())
        return {"status": self.agy_verifier.start("", version)}

    # ---- the list and one chat ----------------------------------------------------------------------------------

    def cards(self) -> list[dict]:
        out = []
        try:
            profiles = self._profiles()
        except agent_profiles.AgentProfileStorageError:
            raise ApiError(503, "storage", "角色資料無法讀取，請到角色頁處理（損毀的檔案不會在這裡被搬移）。") from None
        for p in profiles:
            ok, code, reason = card_gate(p)
            model = p.get("model") if isinstance(p.get("model"), dict) else {}
            out.append({"id": p.get("id"), "name": p.get("name"), "position": agent_profiles.position_of(p),
                        "tool": model.get("tool"), "engine": engine_of(p), "enabled": p.get("enabled") is not False,
                        "can_chat": ok, "code": code or None, "reason": reason or None,
                        "instructions": self._instructions(p) is not None})
        return out

    def list(self, conf) -> dict:
        base = self.base
        chats, problems = [], []
        try:
            ids = cs.list_ids(base)
        except cs.ChatStoreError as exc:
            ids = []
            problems.append(exc.message)
        rows = []
        in_groups = groups.member_chat_ids()          # a chat a group opened is shown in the group, not here
        for chat_id in ids:
            if chat_id in in_groups:
                continue
            try:
                chat = cs.load(base, chat_id)
            except cs.ChatStoreError as exc:
                rows.append({"id": chat_id, "profile_id": None, "engine": None, "created_at": 0, "last_at": 0, "last_kind": None,
                             "last_text": "", "turns": 0, "spent_usd": "0", "open": False, "waiting": False,
                             "problem": exc.message})
                continue
            try:
                events = cs.read_events(base, chat_id)
            except cs.ChatStoreError as exc:
                events = cs.Events([], problem=exc.message)
            rows.append(summarize(chat, events))
        rows.sort(key=lambda r: r["last_at"] or r["created_at"], reverse=True)
        chats, more = rows[:LIST_MAX], max(0, len(rows) - LIST_MAX)
        limits = {"per_turn_usd": cs.usd(cs.limits_from(conf)["per_turn_usd"]),
                  "daily_usd": cs.usd(mt.limits_from(conf)["daily_usd"])}
        ledger, ledger_error = None, None
        if self.ledger is not None:
            try:
                ledger = self.ledger()
            except mt.MeetingError as exc:
                ledger_error = str(exc)
            except Exception as exc:                     # the page says it does not know; it is never an error page
                ledger_error = f"讀不到今天的花費（{type(exc).__name__}）"
        return {"chats": chats, "more": more, "cards": self.cards(), "support": self.support(), "limits": limits,
                "ledger": ledger, "ledger_error": ledger_error, "problems": problems,
                "scratch": "每位員工有自己的工作資料夾；員工能寫的地方只有那裡和暫存區。"}

    def get(self, chat_id, after: int = 0) -> dict:
        """The record after ``after`` and what is happening now. The daemon's answer when it can be reached; else the
        record read from its files alone (no live part), said so."""
        chat = self._chat(chat_id)
        runtime = {"available": True, "message": ""}
        try:
            r = self._call("chat_events", chat_id=chat_id, after=after)
            records, live = r["records"], r["live"]
            out = {"next_after": r["next_after"], "last_seq": r["last_seq"], "more": r["more"], "problem": r["problem"]}
        except ApiError as exc:
            if exc.code != "unavailable":
                raise
            runtime = {"available": False, "message": str(exc)}
            try:
                ev = cs.read_events(self.base, chat_id, after=after, limit=EVENTS_PAGE)
            except cs.ChatStoreError as err:
                raise api_error(err.code, err.message) from None
            records, live, size = [], None, 0
            for rec in ev.records:
                n = len(repr(rec))
                if records and size + n > EVENTS_BYTES:
                    break
                records.append(rec)
                size += n
            nxt = records[-1]["seq"] if records else after
            out = {"next_after": nxt, "last_seq": ev.last_seq, "more": nxt < ev.last_seq, "problem": ev.problem}
        card = None
        try:
            profile = self._profile(chat["profile_id"])
        except agent_profiles.AgentProfileStorageError:
            profile = None
        if profile is not None:
            ok, code, reason = card_gate(profile)
            model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
            card = {"id": profile.get("id"), "name": profile.get("name"), "position": agent_profiles.position_of(profile),
                    "tool": model.get("tool"), "engine": engine_of(profile), "enabled": profile.get("enabled") is not False,
                    "can_chat": ok, "code": code or None, "reason": reason or None}
        given = self._memory(chat["profile_id"], engine_of(profile) or chat.get("engine") or "claude-chat")
        taken = given.readable and given.on           # now, not what an earlier process was given: a count, never a line
        changed, had = self._prompt_changed(chat["id"], profile, given)
        shared = self._shared_view(chat["profile_id"], engine_of(profile) or chat.get("engine") or "claude-chat")
        return {"chat": {"id": chat["id"], "profile_id": chat["profile_id"], "created_at": chat["created_at"],
                         "engine": chat.get("engine")},
                "card": card, "records": records, "live": live, "runtime": runtime, "group": groups.group_of_chat(chat_id),
                "memory": {"on": taken, "count": len(given.entries) if taken else 0, "readable": given.readable,
                           "changed": changed, "started_with_memory": had}, "shared": shared, **out}

    def _shared_view(self, profile_id, engine) -> dict:
        """What the chat page is told about the shared folder: whether this employee's switch is on, whether the folder can be used
        now and, when it cannot, the code of the reason. Looks at the folder's kind and permissions only, never at what is in it."""
        on = bool(self._shared(profile_id, engine))
        code = shared_rules.folder_problem(shared_rules.shared_path(self.base), str(self.base), str(Path.home())) if on else None
        if on and code is None and self._shared_checked(engine) is False:
            code = "shared_unverified"                 # the version has not passed the chat check with the folder (P43-2)
        return {"on": on, "usable": on and code is None, "code": code}

    def _tool_version(self, engine) -> str | None:
        """The version of the AI tool a chat of ``engine`` would run, or None when it cannot be read. Kept for VERSION_TTL seconds:
        the chat page and the shared folder page ask often, and Claude Code's version is read by running it."""
        now = time.monotonic()
        kept = self._versions.get(engine)
        if kept is not None and now - kept[0] < self.version_ttl:
            return kept[1]
        try:
            if engine == "claude-chat":
                version = self.claude()[1]
            else:
                getter = {"codex-chat": self.codex_binary, "agy-chat": self.agy_binary}.get(engine)
                pinned = getter() if getter else None
                version = pinned[1] if pinned else None
        except Exception:                              # a page that only wants to say "unchecked" is not broken by an unreadable tool
            version = None
        version = version if isinstance(version, str) else None
        self._versions[engine] = (now, version)
        return version

    def _shared_checked(self, engine) -> bool | None:
        """Whether the AI tool of ``engine`` passed the chat check with the shared folder: True or False, None when its version cannot be read."""
        version = self._tool_version(engine)
        return None if version is None else bool(self._shared_verified(engine, version))

    def shared_checked(self, engines) -> dict:
        """{engine: True | False | None} for the engines named (the ones that have the shared folder; the server names them): what the
        shared folder page shows beside each employee. The chat service only reads the shared switches, so it does not know the list."""
        return {engine: self._shared_checked(engine) for engine in engines}
    def _prompt_changed(self, chat_id, profile, given) -> tuple[bool, bool | None]:
        """(whether the memory or the card's instructions now are not what this chat's session was started with, whether it was
        started with the memory paragraph). Claude Code 2.1.319 keeps the system prompt a session was started with, so a chat goes
        on with the old one (P42-6); the page says so and offers a new chat. (False, None) when the start is not known (a chat from
        before v0.17.0, a file that does not read) or the card is gone. Compares fingerprints; reads no word of the memory aloud."""
        start = cs.prompt_start(self.base, chat_id)
        if start is None or profile is None:
            return False, None
        block = memory_rules.block(given.entries) if given.readable and given.on else None
        # P58: the employee's name counts only for a session that was told it (the file says so). A session started before the upgrade, or
        # without a usable name, was fingerprinted without the paragraph, so it is compared without it and is not "changed" for it.
        named = None
        if start.get("identity") is True:
            parts, engine = self._identity(profile), engine_of(profile)
            named = memory_rules.identity_block(parts, engine) if parts is not None and engine is not None else None
        return (start["sha"] != memory_rules.prompt_sha(self._instructions(profile), block, self._shared_block(profile), named),
                start["memory"])

    def _shared_block(self, profile) -> str | None:
        """The shared folder's paragraph a new session of this card would be started with now, or None (the switch is off, or this
        AI tool does not have the folder). With None the fingerprint is the one v0.17.0 made."""
        engine = engine_of(profile)
        if not self._shared(profile.get("id"), engine):
            return None
        try:
            return shared_rules.block(shared_rules.shared_path(self.base))
        except ValueError:
            return None

    # ---- what a person does ---------------------------------------------------------------------------------------

    def create(self, body) -> dict:
        if not isinstance(body, dict) or set(body) != {"profile_id"} or not isinstance(body["profile_id"], str):
            raise ApiError(400, "bad_request", "只需要 profile_id。")
        profile = self._card(body["profile_id"])
        r = self._call("chat_open", profile_id=body["profile_id"], engine=engine_of(profile))
        return {"chat": {"id": r["chat_id"], "profile_id": r["profile_id"], "created_at": r["created_at"],
                         "engine": r.get("engine", engine_of(profile))}}

    def send(self, chat_id, body) -> dict:
        """A person's message (the browser's route): exactly ``text``, never an ``origin``."""
        if not isinstance(body, dict) or set(body) != {"text"} or not isinstance(body["text"], str):
            raise ApiError(400, "bad_request", "只需要 text。")
        if isinstance(chat_id, str) and chat_id in groups.member_chat_ids():
            raise api_error("group_member_chat")
        return self._send(chat_id, body["text"], None)

    def send_for_group(self, chat_id, text) -> dict:
        """A message VBear sends for a group (P41-1): the same send as a person's, so every limit, every question about a command or
        a file and the day's money apply as they do there. The record gets no new field. Only to a chat a group opened. Not
        reachable from the browser's routes: only the group runner calls it."""
        if not isinstance(text, str):
            raise ApiError(400, "bad_request", "訊息必須是文字。")
        if not isinstance(chat_id, str) or chat_id not in groups.member_chat_ids():
            raise ApiError(400, "bad_request", "這不是群組用的聊天。")
        return self._send(chat_id, text, None)

    def send_for_routine(self, chat_id, text) -> dict:
        """The first message of a routine's run (P44-2): the same send as a person's, so every limit, every question about a command or a
        file and the day's money apply as they do there. Only into the chat a run is in the middle of opening (its record says
        ``starting`` with this chat, and no turn yet); the record gets no new field. Not reachable from the browser's routes: only the
        routine runner calls it. Once the run has its turn the chat is an ordinary one, and the person goes on in it with ``send``."""
        if not isinstance(text, str):
            raise ApiError(400, "bad_request", "訊息必須是文字。")
        if routines_store.starting_chat(chat_id) is None:
            raise ApiError(400, "bad_request", "這不是例行工作正在開的聊天。")
        return self._send(chat_id, text, None)

    def send_for_dispatch(self, chat_id, text, origin) -> dict:
        """A message VBear sends for a dispatch step (P40-3): the same send as a person's, so every limit, every question
        about a command or a file and the day's money apply as they do there; the record says which dispatch and step it was
        sent for. Not reachable from the browser's routes: only the dispatch code calls it."""
        if not isinstance(text, str):
            raise ApiError(400, "bad_request", "訊息必須是文字。")
        if not cs.origin_ok(origin):
            raise ApiError(400, "bad_request", "origin 格式不符。")
        return self._send(chat_id, text, dict(origin))

    def _send(self, chat_id, text, origin) -> dict:
        if not text.strip():
            raise ApiError(400, "bad_request", "訊息不能是空的。")
        chat = self._chat(chat_id)
        profile = self._card(chat["profile_id"])
        engine = engine_of(profile)
        if chat.get("engine", "claude-chat") != engine:
            raise api_error("card_tool_changed")
        fields = getattr(self, chat_engines.by_engine(engine).fields)(chat_id, text, profile)
        instructions = self._instructions(profile)
        if instructions is not None:
            fields["instructions"] = instructions
        given = self._memory(chat["profile_id"], engine)
        if given.readable and given.on:               # a card with memory off, or a file that cannot be read: not a word is sent
            fields["memory"] = given.entries
        identity = self._identity(profile)                 # the employee's name and position; nothing usable: the field is left out
        if identity is not None:
            fields["identity"] = identity
        if self._shared(chat["profile_id"], engine):          # off (the default), unreadable settings, an AI tool without it: the field is left out
            if not self._shared_verified(engine, fields["cli"]["version"]):      # the daemon asks again; this is the sentence for a person
                raise ApiError(CODE_TEXT["shared_unverified"][0], "shared_unverified",
                               cli_versions.shared_unverified_text(engine, str(fields["cli"]["version"])[:32]) + "你的訊息還沒有送出。",
                               engine=engine)
            fields["shared"] = True
        if origin is not None:
            fields["origin"] = origin
        for attempt in range(self.restart_tries):
            try:
                result = self._call("chat_send", timeout=30.0, **fields)
            except ApiError as exc:
                # The daemon asked for a new process and refused this message before it wrote anything: asking again
                # shortly cannot send it twice.
                if exc.code == "restarting" and attempt + 1 < self.restart_tries:
                    time.sleep(self.restart_pause)
                    continue
                raise
            return {"turn": result["turn"], "cap_usd": result["cap_usd"], "process": result["process"]}
        raise api_error("restarting")                     # not reached

    def _claude_fields(self, chat_id, text, profile) -> dict:
        binary, version, why = self.claude()
        if binary is None:
            raise api_error("claude_version", why)
        try:
            identity = agent_sessions.binary_identity(binary)
        except OSError:
            raise api_error("drift", "Claude Code 檔案已消失或不可執行") from None
        return {"chat_id": chat_id, "text": text, "cli": {"binary": binary, "version": version, "identity": identity},
                "model_id": board_engine.model_for(profile, agent_profiles.position_of(profile))}

    def _codex_fields(self, chat_id, text, profile) -> dict:
        """What the daemon is told for a Codex chat. The service says why Codex cannot chat before it asks (the daemon
        checks all of it again): the state of ``support`` that is not ready is the refusal, in its own words."""
        state = self.codex()
        if state.get("state") != "ready":
            raise self._codex_refusal(state)
        pinned = self.codex_binary()
        if not pinned:
            raise api_error("invalid_binary", "找不到用官方安裝指令裝的 Codex")
        binary, version = pinned
        try:
            identity = agent_sessions.binary_identity(binary)
        except OSError:
            raise api_error("drift", "Codex 檔案已消失或不可執行") from None
        model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
        own = model.get("model_id")
        return {"chat_id": chat_id, "text": text, "engine": "codex-chat",
                "cli": {"binary": binary, "version": version, "identity": identity},
                "model_id": own if isinstance(own, str) and agent_sessions.MODEL_ID_RE.match(own) else None}

    def _agy_fields(self, chat_id, text, profile) -> dict:
        """What the daemon is told for an AGY chat. The service says why AGY cannot chat before it asks (the daemon checks all of it
        again): the state of ``support`` that is not ready is the refusal, in its own words. AGY has one model, so none is named."""
        state = self.agy()
        if state.get("state") != "ready":
            raise self._agy_refusal(state)
        pinned = self.agy_binary()
        if not pinned:
            raise api_error("invalid_binary", "找不到可以安全啟動的 AGY")
        binary, version = pinned
        try:
            identity = agent_sessions.binary_identity(binary)
        except OSError:
            raise api_error("drift", "AGY 檔案已消失或不可執行") from None
        return {"chat_id": chat_id, "text": text, "engine": "agy-chat",
                "cli": {"binary": binary, "version": version, "identity": identity}, "model_id": None}

    def answer(self, chat_id, body) -> dict:
        keys = {"card_id", "token", "decision"}
        if (not isinstance(body, dict) or not keys <= set(body) or set(body) - keys - {"value"}
                or not all(isinstance(body[k], str) for k in keys)
                or ("value" in body and body["value"] is not None and not isinstance(body["value"], str))):
            raise ApiError(400, "bad_request", "只接受 card_id、token、decision，改內容時再加 value。")
        self._chat(chat_id)
        fields = {k: body[k] for k in keys}
        fields["value"] = body.get("value")
        self._call("chat_answer", chat_id=chat_id, **fields)
        return {"answered": body["card_id"]}

    def stop(self, chat_id, body) -> dict:
        if body != {}:
            raise ApiError(400, "bad_request", "停止不需要內容。")
        self._chat(chat_id)
        return {"stopped": self._call("chat_stop", chat_id=chat_id)["stopped"]}

    def close(self, chat_id) -> dict:
        """Ask the daemon to end the chat's idle process (a turn must be stopped or have ended first: ``busy`` otherwise).
        Used by the dispatch runner when a step is done, so that the place of the employee's process is free; the record stays."""
        self._chat(chat_id)
        return {"closed": self._call("chat_close", chat_id=chat_id)["closed"]}

    def chat_engine(self, chat_id) -> str | None:
        """The engine a chat was opened for (None when the chat cannot be read): a group asks it when someone comes back."""
        try:
            return self._chat(chat_id).get("engine", "claude-chat")
        except ApiError:
            return None

    def delete(self, chat_id) -> dict:
        """Removes a chat (the browser's route). A chat a group opened is not removed from here: it goes with its group."""
        if isinstance(chat_id, str) and chat_id in groups.member_chat_ids():
            raise api_error("group_member_chat")
        return self.delete_for_group(chat_id)

    def delete_for_group(self, chat_id) -> dict:
        """Removes a chat for the groups code (a group is deleted with its chats; a group that could not be made takes back the chats
        it opened). Not reachable from the browser's routes. A live process is first asked to close (idle only: a turn must be stopped first); the
        daemon refuses the removal while the process still exists, so this asks a few times."""
        self._chat(chat_id)
        for attempt in range(self.delete_tries):
            try:
                self._call("chat_delete", chat_id=chat_id)
                return {"deleted": chat_id}
            except ApiError as exc:
                if exc.code != "busy" or attempt + 1 == self.delete_tries:
                    raise
            try:
                self._call("chat_close", chat_id=chat_id)
            except ApiError as exc:
                if exc.code == "busy":
                    raise ApiError(409, "busy", "員工還在回覆。請先按停止，等這一回合結束再刪除。") from None
                raise
            time.sleep(self.delete_pause)
        raise api_error("busy")                           # not reached
