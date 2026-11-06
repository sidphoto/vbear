"""The console's side of chats with role cards (P36-2): what the pages /api/chats* read and ask of the runtime daemon.

The daemon owns the chat processes and is the only writer of a chat's record (vbear/runtime/daemon_chat.py). This
module asks it (``daemon_client.call``), reads the record files where only reading is needed (the list of chats), and
decides the things the console decides:

  * which role cards may chat: an enabled card whose tool is Claude Code. Checked when a chat is opened and again on
    every message, because a card can be switched off or changed later; a card of another tool, or a disabled one, is
    refused with the reason, never started;
  * what of the card goes into the chat: only the instructions the person wrote on the card (never the position's
    default text), passed to the daemon, which adds them to Claude Code's system prompt;
  * which Claude Code runs it (the pinned one), and whether that version may chat at all (``support``): the version
    has a chat-mode source list and a pass of the chat check, and no administrator policy is in the way;
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

from . import admin_policy, agent_profiles, ai_tools, board_engine, config as cfg, daemon_client, meetings as mt
from .api_error import ApiError
from .runtime import agent_sessions, chat_protocol as cp, chat_store as cs, cli_versions, codex_chat_env

LIST_MAX = 100                    # chats named in the list, newest first; the rest are counted
EXCERPT = 80                      # characters of the last message shown in the list
EVENTS_PAGE = 200                 # records of one answer
EVENTS_BYTES = 768 << 10          # about this many bytes of records in one answer (at least one record)
RESTART_TRIES = 8                 # a message the daemon asked to be sent again (``restarting``): tried this often,
RESTART_PAUSE = 1.0               # this many seconds apart, before the person is asked to send it again
DELETE_TRIES = 12
DELETE_PAUSE = 0.5
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
    "card_not_claude": (409, "聊天目前只支援工具是 Claude Code 的角色卡。"),
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
    "unverified": (409, "這個 Claude Code 版本的聊天模式還沒有在這台 Mac 上通過驗證，不會啟動。"),
    "unsupported_version": (409, "VBear 沒有這個 Claude Code 版本的聊天模式常數，不會啟動。"),
    "admin_policy": (409, "這台 Mac 上有管理員政策或系統設定，可能蓋過 VBear 的設定，所以不啟動聊天。"),
    "drift": (409, "Claude Code 的檔案或設定在檢查之後改變了，VBear 不啟動它。請重新整理後再試。"),
    "invalid_binary": (409, "找不到可以安全啟動的 Claude Code。"),
    "invalid_model": (409, "這張角色卡的模型名稱不能用在聊天。"),
    "invalid_workdir": (409, "員工的工作資料夾不符規定，不啟動。"),
    "unsafe_path": (409, "聊天用到的資料夾或檔案不是這個使用者擁有的私人檔案（或是連結），VBear 不使用它。"),
    "scratch_path_too_long": (409, "暫存資料夾的路徑太長，Claude Code 會改用共用暫存區，所以不啟動。"),
    "manifest_invalid": (409, "聊天程序的啟動資料不符規定，不啟動。"),
    "unsupported_sandbox": (409, "這台 Mac 的沙盒不能用在聊天，不啟動。"),
    "commit_not_enforceable": (409, "這個設定在這個版本不能確實執行，不啟動。"),
    "not_logged_in": (409, "聊天用的 Codex 還沒有登入（或查不出有沒有登入）。請到「開始設定」按「讓聊天用的 Codex 登入」。"),
    "codex_home": (409, "聊天用的 Codex 資料夾不能用（裡面有不是 VBear 放的設定檔、太大，或路徑不安全），VBear 不使用它。"),
    "manual_review": (409, "這個聊天之前的程序還沒確認已經結束，需要人工檢查 VBear 的狀態資料夾，之後才能再送訊息。"),
    "too_many": (409, "聊天已經太多，請先刪掉不用的。"),
    "full": (409, "這個聊天的紀錄已經滿了，請另開一個聊天。"),
    "storage": (503, "VBear 讀寫聊天紀錄時出了問題。"),
    "internal": (500, "VBear 內部出了問題，這則訊息沒有送出。"),
    "unavailable": (503, "VBear 的背景程序現在連不上。"),
    "bad_reply": (502, "背景程序的回應 VBear 看不懂。"),
    "claude_version": (409, "讀不到 Claude Code 的版本，不能聊天。"),
    "version_changed": (409, "Claude Code 的版本在你預覽之後改變了，請重新整理。"),
    "verifying": (409, "聊天模式的驗證正在進行。"),
}

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
    if model.get("tool") != "claude":
        return False, "card_not_claude", f"這張角色卡的工具是 {tool_label(model.get('tool'))}，聊天目前只支援 Claude Code。"
    return True, "", ""


def _default_claude() -> tuple[str | None, str | None, str]:
    """(binary, version, why not): the pinned Claude Code that would run."""
    from .runtime import native as rt_native
    res = cli_versions.check_cli_version("claude", rt_native._pinned_claude_binary(), cwd=str(Path.home()),
                                         allow_unverified=True)
    if res.compatible and res.observed_version and res.binary_path:
        return res.binary_path, res.observed_version, ""
    return None, None, res.reason


def _excerpt(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EXCERPT else one[:EXCERPT - 1] + "…"


def summarize(chat: dict, events: cs.Events) -> dict:
    """The line of the chat list, from the chat's record alone: nothing here asks the daemon."""
    out = {"id": chat["id"], "profile_id": chat["profile_id"], "created_at": chat["created_at"], "last_at": chat["created_at"],
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
    state (codex_chat_env.status of the state folder by default). ``verifier``: claude_verify.ChatVerifier.
    ``ledger``: a function returning the day's ledger (the meetings' runner, whose day the chats share)."""

    def __init__(self, runtime, *, claude=None, codex=None, verifier=None, ledger=None, profile=None, profiles=None, base=None):
        self.runtime = runtime
        self.claude = claude or _default_claude
        self.codex = codex or (lambda: codex_chat_env.status(self.base))
        self.verifier = verifier
        self.ledger = ledger
        self._profile = profile or (lambda pid: agent_profiles.get_profile_readonly(pid))
        self._profiles = profiles or (lambda: list(agent_profiles.load_all(None, None, mark_corrupt=False).values()))
        self._base = base
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

    # ---- support: may this Claude Code chat at all ----------------------------------------------------------------

    def support(self) -> dict:
        """What the page says before anyone types: the detected version, whether it has been verified for chats, and
        why not otherwise. Starts nothing. ``codex`` is the same question for the Codex that chats (P38-2: its own
        login folder, its pinned and verified version, the administrator policy); the other keys are Claude Code's."""
        binary, version, why = self.claude()
        out = {"detected": version, "verified": [], "state": "unknown", "message": "", "policy": None,
               "verify": self.verifier.status() if self.verifier else None, "codex": self.codex(),
               "money": "聊天用你自己的 Claude 登入，會用掉你的 Claude 額度；金額是 Claude Code 回報的估值。"}
        out["verified"] = sorted(cli_versions.chat_verified_versions(), key=cli_versions._version_key)
        if version is None:
            out["message"] = f"讀不到 Claude Code 的版本（{why or '原因不明'}），無法確認聊天模式是否已通過驗證。"
            return out
        if cp.constants_for(version) is None:
            out.update(state="unsupported", message=f"VBear 沒有 Claude Code {version} 的聊天模式常數，所以不能聊天。"
                                                  "處理方式：等 VBear 更新。")
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

    def verify_start(self, body) -> dict:
        """「驗證聊天」: one real session with the pinned Claude Code (a few small model calls with the person's own
        login). Refused when the check could not pass anyway (no constants, an administrator policy)."""
        if not isinstance(body, dict) or set(body) - {"version"}:
            raise ApiError(400, "bad_request", "只接受 version。")
        if self.verifier is None:
            raise ApiError(503, "unavailable", "這個主控台沒有驗證功能。")
        binary, version, why = self.claude()
        if version is None:
            raise api_error("claude_version", why)
        wanted = body.get("version")
        if wanted is not None and wanted != version:
            raise ApiError(409, "version_changed", f"目前的 Claude Code 是 {version}，不是 {wanted}；請重新整理後再驗證。")
        if cp.constants_for(version) is None:
            raise api_error("unsupported_version", f"Claude Code {version}")
        policy = admin_policy.check_claude(version, home=os.path.expanduser("~"))
        if not policy.ok:
            raise ApiError(409, "admin_policy", policy.reason())
        if version in cli_versions.chat_verified_versions():
            return {"already_verified": True, "version": version, "status": self.verifier.status()}
        return {"status": self.verifier.start(binary, version)}

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
                        "tool": model.get("tool"), "enabled": p.get("enabled") is not False, "can_chat": ok,
                        "code": code or None, "reason": reason or None,
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
        for chat_id in ids:
            try:
                chat = cs.load(base, chat_id)
            except cs.ChatStoreError as exc:
                rows.append({"id": chat_id, "profile_id": None, "created_at": 0, "last_at": 0, "last_kind": None,
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
                    "tool": model.get("tool"), "enabled": profile.get("enabled") is not False, "can_chat": ok,
                    "code": code or None, "reason": reason or None}
        return {"chat": {"id": chat["id"], "profile_id": chat["profile_id"], "created_at": chat["created_at"]},
                "card": card, "records": records, "live": live, "runtime": runtime, **out}

    # ---- what a person does ---------------------------------------------------------------------------------------

    def create(self, body) -> dict:
        if not isinstance(body, dict) or set(body) != {"profile_id"} or not isinstance(body["profile_id"], str):
            raise ApiError(400, "bad_request", "只需要 profile_id。")
        self._card(body["profile_id"])
        r = self._call("chat_open", profile_id=body["profile_id"])
        return {"chat": {"id": r["chat_id"], "profile_id": r["profile_id"], "created_at": r["created_at"]}}

    def send(self, chat_id, body) -> dict:
        if not isinstance(body, dict) or set(body) != {"text"} or not isinstance(body["text"], str):
            raise ApiError(400, "bad_request", "只需要 text。")
        text = body["text"]
        if not text.strip():
            raise ApiError(400, "bad_request", "訊息不能是空的。")
        chat = self._chat(chat_id)
        profile = self._card(chat["profile_id"])
        binary, version, why = self.claude()
        if binary is None:
            raise api_error("claude_version", why)
        try:
            identity = agent_sessions.binary_identity(binary)
        except OSError:
            raise api_error("drift", "Claude Code 檔案已消失或不可執行") from None
        fields = {"chat_id": chat_id, "text": text, "cli": {"binary": binary, "version": version, "identity": identity},
                  "model_id": board_engine.model_for(profile, agent_profiles.position_of(profile))}
        instructions = self._instructions(profile)
        if instructions is not None:
            fields["instructions"] = instructions
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

    def delete(self, chat_id) -> dict:
        """Removes a chat. A live process is first asked to close (idle only: a turn must be stopped first); the
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
