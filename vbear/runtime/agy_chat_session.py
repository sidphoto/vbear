"""One AGY chat process owned by the runtime daemon (P46-3, ADR 0012): ``agy acp`` over stdio, talking with a person for a role
card whose AI tool is AGY. It takes the place of chat_session.ChatProcess for that engine and keeps what is the same: the daemon's
selectors loop calls on_stdout / on_stderr / on_writable when a pipe is ready and tick() on every pass, the RPC ops call start_turn,
answer, stop and close_gracefully, the process is ended as a stream session is (stream_session.ProcessGroupEnd), and a card is VBear's
one-use-token, five-minute, size-limited question to the person.

What is different is the protocol (agy_chat_protocol.AgyTracker reads it):

  * The handshake is initialize, session/new (session/resume in a later process of the chat) and session/set_model, which names the one
    model of the version's table (every time, after either); a person's message is held until all of it passed. A turn whose message was
    never written costs nothing.
  * Every command and every file change makes a request (settings ``request-review`` and AGY's sandbox). VBear answers each one with
    "allow once" or "reject once" and nothing else (agy_chat_protocol.answer_line cannot write another choice). It answers itself when it
    refuses (a request to run outside the sandbox, a file outside the work folder or one of the names that are settings, the network, a
    kind of tool it does not open) and when it allows (a read inside the work folder); the rest is a card.
  * A card cannot be answered with other words: the person's changed text refuses the original and, when the turn has ended, is sent as the
    next message of the chat (``followup``); AGY then asks again, in a card of its own.
  * AGY reports tokens at the end of a turn, not money and not during it. A turn costs its tokens at VBear's own rate
    (agy_chat_protocol.estimate_usd), as the turn's own ``totalTokens``; a turn that has no usable count (it was cut off, timed out, the
    process ended, a violation, or the count does not add up) costs its cap. The cap is checked before a turn starts only: one turn may
    cost more than it, and what it cost is recorded as it was.
  * Stopping is ``session/cancel`` and the cancelled answer of every request that waits; the turn ends with AGY's own end (its usage
    counts) or, after STOP_WAIT seconds, at its cap, and the process is closed.
  * Facts go to the chat's events file as for a Claude or Codex chat, with the events they already have and no new kind. Of what AGY prints
    only what agy_chat_protocol keeps (never the plan's name, the sign-in methods, the names of the skills or what the model thought).
"""

from __future__ import annotations

import difflib
import hmac
import secrets
from dataclasses import dataclass
from decimal import Decimal

from . import agy_chat_protocol as acp, chat_session as chs, chat_store as cs
from .chat_session import Card, Turn

TOOL_COMMAND = "command"
TOOL_FILE = "file_change"
TOOL_READ = "read"
TOOL_OTHER = "other"
STOP_WAIT = 10.0                  # seconds AGY may take to end a cancelled turn before its process is ended
REFUSED_REQUEST = "VBear 不接受這種請求"
SHUTDOWN_REASON = "背景程序關閉"    # the reason the daemon gives when it is closing (daemon_chat._kill_all_chats): nothing is waited for then
NOT_LOGGED_IN = "AGY 還沒登入。請到「開始設定」按 AGY 的「登入」，登入後再送一次。"
RESUME_FAILED = "AGY 找不到這段對話，請開新聊天。"
NO_MODEL = "這個 AGY 沒有 {model} 這個模型，聊天不能用。請更新 AGY，或改用其他 AI 工具的員工。"
FAILED_STEP = {"initialize": "AGY 沒有接受開始聊天", "session_new": "AGY 沒有接受開啟新的對話",
               "session_resume": RESUME_FAILED, "set_model": "AGY 沒有接受聊天用的模型設定", "prompt": "AGY 沒有接受這則訊息"}
_CATEGORY_TOOL = {"command": TOOL_COMMAND, "file_change": TOOL_FILE, "read": TOOL_READ}
_TOOL_OF_KIND = {"execute": TOOL_COMMAND, "edit": TOOL_FILE, "delete": TOOL_FILE, "move": TOOL_FILE, "read": TOOL_READ,
                 "search": TOOL_READ}
_CHANGE_KIND = {"add": "add", "modify": "update", "delete": "delete"}       # what a file card says (the words of a Codex card)


@dataclass
class AgyTurn(Turn):
    text: str = ""
    cancelling: bool = False          # a person (or the daemon) stopped it: session/cancel was written
    cancel_at: float | None = None


@dataclass
class AgyCard(Card):
    options: list | None = None       # the options of the request, as the tracker kept them (id and kind)
    paths: list | None = None         # the places the request names, judged again on allow
    content: str | None = None        # what a file card writes (for its size and its second judgement)
    category: str = TOOL_COMMAND


class AgyChatProcess(chs.ChatProcess):
    TOOL = "AGY"

    def __init__(self, *, instructions: str | None, session_id: str | None, settings_ok=None, followup=None,
                 stop_wait: float = STOP_WAIT, **kw):
        self._instructions = instructions
        self._resume_session = session_id
        self.settings_ok = settings_ok            # () -> bool: whether VBear's settings file is still byte for byte its own
        self.followup_hook = followup             # (process, text) -> why not, or None: sends a changed text as a new turn
        self.stop_wait = stop_wait
        self._first_deadline = kw["init_deadline"]           # initialize: this long; the session after it: twice as long
        kw["init_deadline"] = 2 * kw["init_deadline"]
        super().__init__(last_total=None, **kw)
        self.consts = acp.constants_for(self.cli_version)
        self.rpc_no = 0
        self.session_id = session_id
        self.initialized = False
        self.commands = 0                         # how many commands AGY listed (never their names)
        self.followup_text: str | None = None
        self.followup_card: str | None = None
        self.followup_value: str | None = None
        self.stop_text = ""
        self.call_tool: dict = {}                 # call id -> the tool name of the record
        self.refused_calls: set = set()           # calls VBear refused: their (failed) end is already on record as a refusal

    def _new_tracker(self):
        return acp.AgyTracker(acp.constants_for(self.cli_version), workdir=self.cwd, shared=self.shared,
                              session_id=self._resume_session, resumed=self._resume_session is not None)

    def _read_facts(self, value) -> list:
        return self.tracker.on_message(value)

    def _rpc(self) -> int:
        self.rpc_no += 1
        return self.rpc_no

    # ---- what the daemon asks ----------------------------------------------------------------------------------

    def headroom(self) -> Decimal:
        return Decimal(0)                         # AGY has no budget of its own; every turn has its cap

    def info(self) -> dict:
        out = super().info()
        out.update(engine="agy-chat", activity_evidence={"agy_chat": {"state": self.live_state()}})
        return out

    def live_view(self, now: float) -> dict:
        view = super().live_view(now)
        view["model"] = self.consts.model_id
        return view

    def send_initialize(self) -> None:
        rid = self._rpc()
        self.tracker.expect(rid, "initialize")
        self._queue(acp.initialize_line(rid))

    def start_turn(self, n: int, cap: Decimal, text: str, now: float) -> None:
        """The turn is on record (user_message, turn_started) before this. Its message is written now, or once the handshake has
        passed."""
        self.turn = AgyTurn(n, cap, now, text=text)
        self.next_turn = n + 1
        self.last_turn = n
        self.partial = ""
        self.last_activity = now
        if self.state == "idle":
            self._write_turn()

    def _write_turn(self) -> None:
        t = self.turn
        if t is None or t.written:
            return
        rid = self._rpc()
        try:
            line = acp.prompt_line(rid, self.tracker.session_id, t.text)
        except ValueError as exc:
            self._record("error", {"turn": t.n, "message": f"這則訊息無法送給 AGY（{exc}）"})
            self._end_turn("not_sent", now=t.started)
            return
        t.written = True
        self.tracker.begin_turn()
        self.tracker.expect(rid, "prompt")
        self._queue(line)

    # ---- a card -----------------------------------------------------------------------------------------------

    def _answer_request(self, request_id, options, decision: str) -> bool:
        """Tell the tracker, then queue the answer: one of "allow" (the one allow-once option), "deny" (the one reject-once option) or
        "cancelled". False when no answer could be given (the tracker does not know the request, or the options are not ones VBear
        understands), in which case nothing was queued."""
        try:
            line = acp.answer_line(request_id, options, decision, self.consts)
            self.tracker.answered(request_id, decision)
        except ValueError:
            return False
        self._queue(line)
        return True

    def answer(self, card_id, token, decision, value, now: float) -> tuple[str | None, str]:
        """(None, "") when the card was answered; else (error code, message). A card is answered once: a second answer, an expired card
        or one of an ended turn is gone. A changed text refuses the card and is sent as the next message when the turn has ended."""
        card = self.cards.get(card_id) if isinstance(card_id, str) else None
        if card is None:
            return "gone", "這張卡片已經回覆過、已過期或不存在"
        if now >= card.expires:
            self._expire(card)
            return "expired", "這張卡片已過期，VBear 已視為拒絕"
        if not (isinstance(token, str) and hmac.compare_digest(token.encode("utf-8", "replace"),
                                                                card.token.encode("ascii"))):
            return "bad_token", "卡片的 token 不符"
        if decision not in ("allow", "deny", "modify"):
            return "bad_request", "decision 必須是 allow、deny 或 modify"
        if decision != "modify" and value is not None:
            return "bad_request", "只有「改內容再問」可以帶 value"
        if decision == "modify":
            if card.editable is None:
                return "bad_request", "這張卡片沒有可以改的內容"
            if not isinstance(value, str) or not value.strip():
                return "bad_request", "改過的內容必須是文字"
            if len(value) > cs.MAX_EXCERPT:
                return "bad_request", f"改過的內容不能超過 {cs.MAX_EXCERPT} 個字"
        if decision == "allow":
            again = self._judge_again(card)
            if again is not None:
                self._refuse_on_answer(card, decision, value, again, now)
                return "refused", f"卡片出現之後情況變了，VBear 已拒絕：{again}"
        sent = "allow" if decision == "allow" else "deny"
        if not self._answer_request(card.request_id, card.options, sent):
            self._drop_card(card)
            return "gone", "這張卡片的請求已經結束，不能再回覆"
        del self.cards[card_id]
        if decision == "deny" or decision == "modify":
            self.refused_calls.add(card.tool_use_id)
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": decision,
                                       "value": value if decision == "modify" else None})
        if decision == "modify":
            self.followup_text, self.followup_card, self.followup_value = _followup_text(card, value), card.card_id, value
        self.last_activity = now
        return None, ""

    def _judge_again(self, card: AgyCard) -> str | None:
        """Why what is about to be allowed is not allowed any more, or None. A folder of a path may have become a link out of the work
        folder while the card waited. AGY still acts later, so this narrows the race and does not close it."""
        if card.category == TOOL_FILE:
            again = acp.judge_file_change(card.paths, card.content, self.cwd, shared=self.shared)
            return again.reason if again.action != "ask" else None
        if card.category == TOOL_READ:
            again = acp.judge_read(card.paths, self.cwd, shared=self.shared)
            return again.reason if again.action == "deny" else None
        return None

    def _drop_card(self, card: Card) -> None:
        self.cards.pop(card.card_id, None)

    def _expire(self, card: AgyCard) -> None:
        del self.cards[card.card_id]
        self.refused_calls.add(card.tool_use_id)
        self._answer_request(card.request_id, card.options, "deny")
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "expired", "value": None})

    def _refuse_on_answer(self, card: AgyCard, decision: str, value, reason: str, now: float) -> None:
        del self.cards[card.card_id]
        self.refused_calls.add(card.tool_use_id)
        self._answer_request(card.request_id, card.options, "deny")
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "refused",
                                       "value": value if decision == "modify" else None})
        self._record("denied", {"turn": card.turn, "tool_use_id": card.tool_use_id, "tool": card.tool,
                                "summary": _summary(card.tool, card.input),
                                "reason": f"回覆時再檢查一次：{reason}"[:cs.MAX_SHORT], "by": "vbear"})
        self.last_activity = now

    def _cancel_cards(self) -> None:
        """The cards of a turn that is over (or is being stopped): each is answered as cancelled when AGY still waits for it."""
        waiting = set(self.tracker.open_requests())
        for card in list(self.cards.values()):
            del self.cards[card.card_id]
            self.refused_calls.add(card.tool_use_id)
            if card.request_id in waiting:
                self._answer_request(card.request_id, card.options, "cancelled")
            self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "cancelled",
                                           "value": None})

    # ---- stopping ---------------------------------------------------------------------------------------------

    def stop(self, reason: str, now: float) -> None:
        """A person stopped the turn, the daemon is closing, or the chat must end. A turn that reached AGY is cancelled first
        (``session/cancel``, and every request that waits answered as cancelled): it ends with AGY's own end, whose usage counts, or at
        its cap after STOP_WAIT seconds, and the process is then closed. When the daemon is closing nothing is waited for."""
        t = self.turn
        if (t is not None and t.written and not t.cancelling and not self.finished and self.phase is None and self.stdin_open
                and self.tracker.session_id is not None and not self.tracker.stopped):
            self._cancel_turn(reason, now)
            if reason != SHUTDOWN_REASON:
                return
            self.on_writable(now)
        super().stop(reason, now)

    def _cancel_turn(self, reason: str, now: float) -> None:
        t = self.turn
        t.cancelling, t.cancel_at = True, now
        self.stop_text = reason
        self._queue(acp.cancel_line(self.tracker.session_id))
        self._cancel_cards()

    # ---- facts ------------------------------------------------------------------------------------------------

    def _on_fact(self, kind: str, data: dict, now: float) -> None:
        n = self._turn_no()
        if kind == "initialized":
            self.initialized = True
            self._open_session(now)
        elif kind == "session_ready":
            self._on_ready(data)
        elif kind == "model_set":
            if self.state == "starting":
                self.state = "idle"
                if self.turn is not None:
                    self._write_turn()
        elif kind == "invalid_model":
            self._fail(NO_MODEL.format(model=self.consts.model_id), now)
        elif kind == "request_failed":
            self._on_failed(data, now)
        elif kind == "commands":
            self.commands = data["count"]
        elif kind == "delta":
            self.partial = (self.partial + data["text"])[-chs.PARTIAL_MAX:]
        elif kind == "anomaly":
            self._record("anomaly", data)
        elif kind == "unknown_request":
            self._queue(acp.error_line(data["request_id"], REFUSED_REQUEST))
        elif kind == "violation":
            self._on_violation(data, n, now)
        elif kind == "permission_request":
            self._on_permission(data, now)
        elif kind == "turn_completed":
            self._on_completed(data, now)
        elif n < 1 and kind in ("reply", "tool_call", "tool_result"):
            self._record("anomaly", {"event_type": f"outside_turn/{kind}", "fields": []})
        elif kind == "reply":
            self.partial = ""
            self._record("reply", {"turn": n, "text": data["text"], "truncated": False})
        elif kind == "tool_call":
            tool = _TOOL_OF_KIND.get(data["tool_kind"], TOOL_OTHER)
            self.call_tool[data["call_id"]] = tool
            self._record("tool_call", {"turn": n, "tool_use_id": data["call_id"], "tool": tool, "summary": data["summary"]})
        elif kind == "tool_result":
            self._on_result(n, data)
        # model_set before a turn, the thoughts and the plan: nothing to keep

    def _open_session(self, now: float) -> None:
        rid = self._rpc()
        try:
            if self._resume_session is not None:
                line = acp.session_resume_line(rid, self._resume_session, cwd=self.cwd, system_prompt=self._instructions)
                self.tracker.expect(rid, "session_resume")
            else:
                line = acp.session_new_line(rid, cwd=self.cwd, system_prompt=self._instructions)
                self.tracker.expect(rid, "session_new")
        except ValueError as exc:
            self._fail(f"無法開啟 AGY 的對話（{exc}）", now)
            return
        self._queue(line)

    def _on_ready(self, data: dict) -> None:
        self.session_id = data["session_id"]
        self._record("session_ready", {"cli_version": self.cli_version, "permission_mode": self.consts.settings["toolPermission"],
                                       "model": self.consts.model_id})
        if not data["resumed"]:
            self._record("session_bound", {"thread_id": data["session_id"]})
        rid = self._rpc()
        self.tracker.expect(rid, "set_model")
        self._queue(acp.set_model_line(rid, self.session_id, self.consts))

    def _on_failed(self, data: dict, now: float) -> None:
        self._fail(NOT_LOGGED_IN if data["auth_required"] else FAILED_STEP.get(data["kind"], "AGY 沒有接受 VBear 的要求"), now)

    def _on_violation(self, data: dict, n: int, now: float) -> None:
        """Evidence that VBear's settings are not in force, or that something ran that VBear did not allow: the turn is cancelled and
        the process ended at once, and the turn costs its cap. A request that was part of it is answered with an error first."""
        self._record("anomaly", {"event_type": "violation", "fields": []})
        self._record("error", {"turn": n or None, "message": data["message"]})
        t = self.turn
        if self.stdin_open and not self.finished and self.tracker.session_id is not None and t is not None and t.written:
            self._queue(acp.cancel_line(self.tracker.session_id))
        if isinstance(data.get("request_id"), (int, str)) and not isinstance(data.get("request_id"), bool):
            self._queue(acp.error_line(data["request_id"], REFUSED_REQUEST))
        if self.turn is not None:
            self._end_turn("violation", now=now)
        self.on_writable(now)                         # what was answered leaves before the signal
        self.terminate("聊天違反 VBear 的設定，已停止")

    def _on_permission(self, data: dict, now: float) -> None:
        rid, cid = data["request_id"], data["call_id"]
        tool = _CATEGORY_TOOL.get(data["kind"], TOOL_OTHER)
        n = self._turn_no() or 1
        inp = _card_input(data, self.cwd, tool)
        action, reason = data["action"], data["why"]
        t = self.turn
        if t is None:
            action, reason = "deny", "這個請求不在任何一回合裡"
        elif t.cancelling:
            action, reason = "deny", "這回合正在停止"
        summary = _summary(tool, inp)
        card = None
        if action == "ask":
            card = AgyCard(card_id="k-" + secrets.token_hex(8), token=secrets.token_urlsafe(24), request_id=rid, tool=tool,
                           input=inp, tool_use_id=cid, reason=reason[:cs.MAX_SHORT], turn=n,
                           editable={TOOL_COMMAND: "command", TOOL_FILE: "content"}.get(tool), expires=now + self.card_ttl,
                           options=data["options"], paths=data.get("paths"), content=data.get("content"), category=tool)
            try:
                card.shown = chs._size(chs._card_view(card, now))
            except (ValueError, TypeError, UnicodeEncodeError, RecursionError):
                card.shown = chs.CARD_SHOW_MAX + 1
            if card.shown > chs.CARD_SHOW_MAX:
                action, reason = "deny", "內容太長，無法完整顯示給你確認，VBear 直接拒絕"
            elif len(self.cards) >= chs.MAX_CARDS:
                action, reason = "deny", "等你回覆的卡片太多，VBear 直接拒絕"
            elif sum(c.shown for c in self.cards.values()) + card.shown > chs.CARDS_SHOW_TOTAL:
                action, reason = "deny", "等你回覆的卡片內容加起來太多，無法一起完整顯示，VBear 直接拒絕；請先回覆前面的卡片"
        if action == "ask":
            self.cards[card.card_id] = card
            self._record("card", {"turn": n, "card_id": card.card_id, "tool": tool, "input": inp, "editable": card.editable,
                                  "state": "asked", "reason": card.reason})
            return
        if action == "allow" and self._answer_request(rid, data["options"], "allow"):
            self._record("auto_allowed", {"turn": n, "tool_use_id": cid, "tool": tool, "summary": summary,
                                          "reason": reason[:cs.MAX_SHORT]})
            return
        if action == "allow":
            reason = "AGY 給的選項 VBear 不認得"
        self.refused_calls.add(cid)
        self._answer_request(rid, data["options"], "deny")
        self._record("denied", {"turn": n, "tool_use_id": cid or "?", "tool": tool, "summary": summary,
                                "reason": reason[:cs.MAX_SHORT], "by": "vbear"})

    def _on_result(self, n: int, data: dict) -> None:
        if data["call_id"] in self.refused_calls:
            return                                    # the refusal is on record already (a card's own decision, or "denied")
        code = data.get("exit_code")
        failed = data["status"] != "completed" or (code is not None and code != 0)
        self._record("tool_result", {"turn": n, "tool_use_id": data["call_id"],
                                     "tool": self.call_tool.get(data["call_id"], TOOL_OTHER), "is_error": failed,
                                     "text": data.get("output") or "", "truncated": False, "source": "agy"})

    def _on_completed(self, data: dict, now: float) -> None:
        t = self.turn
        if t is None:
            self._record("anomaly", {"event_type": "turn_completed/outside_turn", "fields": []})
            return
        if self.settings_ok is not None and not self.settings_ok():
            self._on_violation({"message": "AGY 的設定檔在這一回合裡被改了，不是 VBear 寫的那一份", "request_id": None}, self._turn_no(), now)
            return
        tokens, problem = data["tokens"], data["usage_problem"]
        if tokens is not None:
            self._record("usage", {"turn": t.n, "total_tokens": tokens, "delta_tokens": tokens})
        elif problem:
            self._record("anomaly", {"event_type": f"usage/{problem}", "fields": []})
        stopping = t.cancelling
        stop_reason = data["stop_reason"]
        self._end_turn("stopped" if stopping else "result", now=now, status=stop_reason, tokens=tokens,
                       is_error=stopping or stop_reason != "end_turn")
        if stopping:
            self.close_gracefully(self.stop_text or "你按了停止", now)
        elif self.followup_text is not None:
            self._run_followup(now)

    def _run_followup(self, now: float) -> None:
        """The text of a changed card goes as the next message, a new turn (and only then is it said to have been sent)."""
        text, card_id, value = self.followup_text, self.followup_card, self.followup_value
        self.followup_text = self.followup_card = self.followup_value = None
        if text is None:
            return
        why = "聊天已經在結束了" if (self.phase is not None or self.finished or self.state == "closing") \
            else "沒有辦法送出" if self.followup_hook is None else self.followup_hook(self, text)
        if why:
            self._record("error", {"turn": None, "message": f"改過的內容沒有送出：{why}"[:cs.MAX_EXCERPT]})
        else:
            self._record("card_edit_sent", {"card_id": card_id, "text": value})

    # ---- a turn's end -----------------------------------------------------------------------------------------

    def _end_turn(self, reason: str, *, now: float, status=None, is_error=False, tokens=None) -> None:
        """"result" and "stopped" that AGY itself ended cost their tokens (``tokens``: the turn's own ``totalTokens``, whole and adding
        up) at VBear's rate, as they were, even when that is more than the cap; every other end (the process ended, a timeout, a
        violation, an error, a stop AGY did not answer) and a count that is not usable cost the cap; a turn never written costs nothing."""
        t = self.turn
        if t is None:
            return
        estimate = False
        if not t.written:
            cost, reason, tokens = Decimal(0), "not_sent", None
        else:
            spent = None
            if tokens is not None:
                try:
                    spent = acp.estimate_usd(tokens)
                except ValueError:
                    tokens = None
            if spent is not None and reason in ("result", "stopped"):
                cost, estimate = spent, True
            else:
                cost, tokens = t.cap, None
        self.turn = None
        self.spent += cost
        self.partial = ""
        if self.followup_text is not None and reason != "result":
            self.followup_text = self.followup_card = self.followup_value = None
            self._record("error", {"turn": None, "message": "改過的內容沒有送出：這一回合沒有正常結束"})
        self._record("turn_ended", {"turn": t.n, "cost_usd": cs.usd(cost), "reported": False, "total_usd": None,
                                    "reason": reason,
                                    "subtype": status if isinstance(status, str) and status != "?" else None,
                                    "is_error": bool(is_error) or reason != "result", "estimate": estimate, "tokens": tokens})
        self._cancel_cards()
        self.last_activity = now

    def _timers(self, now: float) -> None:
        if (not self.finished and self.phase is None and self.state == "starting" and not self.initialized
                and now - self.spawned > self._first_deadline):
            self._fail("AGY 沒有回應初始化，聊天沒有開成", now)
            return
        super()._timers(now)
        t = self.turn
        if (not self.finished and self.phase is None and t is not None and t.cancelling and t.cancel_at is not None
                and now - t.cancel_at > self.stop_wait):
            self._end_turn("stopped", now=now)
            self.terminate(self.stop_text or "你按了停止")

    def _record_exit(self, now: float) -> None:
        super()._record_exit(now)
        if self.settings_ok is not None and not self.settings_ok():
            self._record("anomaly", {"event_type": "violation", "fields": []})
            self._record("error", {"turn": None, "message": "AGY 的設定檔被改了，不是 VBear 寫的那一份（下次開程序時 VBear 會重寫）"})


# ---- what a card shows ----------------------------------------------------------------------------------------

def _relative(path, cwd: str):
    """A path as the card shows it: relative to the work folder when it is inside it, else as given."""
    if not isinstance(path, str):
        return path
    if path == cwd:
        return "."
    prefix = cwd.rstrip("/") + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def _diff_text(old, new) -> str:
    """The diff of a file card: the lines added and removed, in the unified form without its header; a new file is all added lines."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    if old is None:
        return "\n".join("+" + line for line in new_lines)
    rows = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    return "\n".join(rows[2:])


def _changes(data: dict, cwd: str) -> list[dict]:
    paths, op = data.get("paths") or [], data.get("operation")
    if op == "move" and len(paths) >= 2:
        return [{"path": _relative(paths[0], cwd), "kind": "update", "move_to": _relative(paths[1], cwd), "diff": ""}]
    kind = _CHANGE_KIND.get(op, "update")
    out = []
    for path in paths:
        mine = [d for d in data.get("diffs") or [] if d["path"] == path]
        if mine:
            text = "\n".join(_diff_text(d["old_text"], d["new_text"]) for d in mine)
        elif op == "delete":
            text = ""
        elif len(paths) == 1 and isinstance(data.get("content"), str):
            text = _diff_text(None, data["content"])
        else:
            text = ""
        out.append({"path": _relative(path, cwd), "kind": kind, "diff": text})
    return out


def _card_input(data: dict, cwd: str, tool: str) -> dict:
    """What a card holds: a command with its folder (AGY does not say which one, so it is the work folder); the files with a diff each
    (the shape of a Codex card); or the places a read wants. Only fields VBear reads out of the request, never AGY's own wording."""
    if tool == TOOL_COMMAND:
        return {"command": data.get("command") or "", "cwd": "."}
    if tool == TOOL_FILE:
        return {"changes": _changes(data, cwd)}
    return {"paths": [_relative(p, cwd) for p in data.get("paths") or []]}


def _summary(tool: str, inp: dict) -> str:
    if tool == TOOL_COMMAND:
        return str(inp.get("command", ""))[:cs.MAX_EXCERPT]
    if tool == TOOL_FILE:
        changes = inp.get("changes") if isinstance(inp.get("changes"), list) else []
        names = ", ".join(f"{c.get('kind')} {c.get('path')}" for c in changes if isinstance(c, dict))
        return f"{len(changes)} 個檔案：{names}"[:cs.MAX_EXCERPT]
    paths = inp.get("paths") if isinstance(inp.get("paths"), list) else []
    return ", ".join(str(p) for p in paths)[:cs.MAX_EXCERPT]


def _followup_text(card: Card, value: str) -> str:
    """The next message when a person changed what a card asked for (in the person's own language: it is shown in the chat)."""
    if card.tool == TOOL_COMMAND:
        return "請改成執行下面這個指令：" + value
    paths = "、".join(str(c.get("path")) for c in card.input.get("changes", []) if isinstance(c, dict))
    return f"請把 {paths} 寫成下面的內容：{value}"
