"""One Codex chat process owned by the runtime daemon (P38-3): ``codex app-server`` over stdio, talking with a person for a
role card whose AI tool is Codex. It takes the place of chat_session.ChatProcess for that engine and keeps what is the
same: the daemon's selectors loop calls on_stdout / on_stderr / on_writable when a pipe is ready and tick() on every
pass, the RPC ops call start_turn, answer, stop and close_gracefully, the process is ended as a stream session is
(stream_session.ProcessGroupEnd), and a card is VBear's one-use-token, five-minute, size-limited question to the person.

What is different is the protocol (codex_chat_protocol.CodexTracker reads it):

  * The handshake is initialize, initialized, thread/start (thread/resume in a later process of the chat) and one
    mcpServerStatus/list that must be empty; a person's message is held until all of it passed. A turn whose message was
    never written costs nothing.
  * Every command and every file change makes a request (``approvalPolicy: "untrusted"``). A command is a card with its
    whole text. A file change is judged first (a path outside the work folder, or under .codex, .agents or .git, is
    refused with no card); the rest is a card with each file's path, kind and diff. An allow is one ``accept``: never
    "for the session", never an execpolicy or network amendment (codex_chat_protocol.decision_line cannot write them).
  * Codex has no "allow a changed command". A changed one is a decline and a ``turn/steer`` that tells Codex what to run
    instead; Codex then asks again, with the changed command, in a card of its own. When the steer is refused (the turn is
    over) the changed text is sent as the next message of the chat, in a new turn (``followup``).
  * Codex reports tokens, not money. A turn costs its tokens at VBear's own rate (ccp.estimate_usd), counted as the
    thread's total less what it was when the turn began; every count is compared with the turn's cap and the turn is
    interrupted when it is reached. A turn that is cut off (stopped, timed out, the process ended, a violation) costs its
    cap, or its estimate when that is more; only a turn that never reached Codex costs nothing.
  * Facts go to the chat's events file as for a Claude chat; of initialize's answer and of the account notifications only
    what codex_chat_protocol keeps (never the Codex home, the user agent, the plan, credits, MCP names or the paths of
    instruction files).
"""

from __future__ import annotations

import secrets
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from . import chat_session as chs, chat_store as cs, codex_chat_protocol as ccp
from .chat_session import Card, Turn

TOOL_COMMAND = "command"
TOOL_FILE = "file_change"
INTERRUPT_GRACE = 30.0           # seconds a turn that was interrupted may take to end before the process is ended
REFUSED_REQUEST = "VBear 不接受這種請求"
DECLINED = chs.DENIED
CLIENT_VERSION = "0"             # what initialize names as VBear's own version when the daemon gives none


@dataclass
class CodexTurn(Turn):
    text: str = ""
    turn_id: str | None = None          # Codex's id of the turn, once it said so
    limit_hit: bool = False             # the tokens reached the cap: the turn is being interrupted
    interrupt_sent: bool = False
    interrupt_at: float | None = None


@dataclass
class CodexCard(Card):
    changes: list | None = None         # a file card's changes as Codex gave them, judged again on allow


class CodexChatProcess(chs.ChatProcess):
    def __init__(self, *, instructions: str | None, thread_id: str | None, last_tokens: int | None, followup=None,
                 client_version: str = CLIENT_VERSION, **kw):
        self._instructions = instructions
        self._resume_thread = thread_id
        self._start_tokens = last_tokens
        self.followup_hook = followup            # (process, text) -> why not, or None: sends a changed text as a new turn
        self.client_version = client_version
        super().__init__(last_total=None, **kw)
        self.rpc_no = 0
        self.thread_id = thread_id
        self.shown_model = ""
        self.steers: deque[str] = deque()        # the texts of steers asked and not answered yet
        self.followup_text: str | None = None
        self.last_plan: tuple | None = None

    def _new_tracker(self):
        return ccp.CodexTracker(ccp.constants_for(self.cli_version), workdir=self.cwd,
                                codex_home=self.manifest["codex_home"], thread_id=self._resume_thread,
                                resumed=self._resume_thread is not None, last_total=self._start_tokens)

    def _read_facts(self, value) -> list:
        return self.tracker.on_message(value)

    def _rpc(self) -> int:
        self.rpc_no += 1
        return self.rpc_no

    # ---- what the daemon asks ----------------------------------------------------------------------------------

    def headroom(self) -> Decimal:
        return Decimal(0)                        # Codex has no budget of its own; every turn has its cap

    def info(self) -> dict:
        out = super().info()
        out.update(engine="codex-chat", activity_evidence={"codex_chat": {"state": self.live_state()}})
        return out

    def live_view(self, now: float) -> dict:
        view = super().live_view(now)
        view["model"] = self.shown_model or (self.model_id or "")
        return view

    def send_initialize(self) -> None:
        rid = self._rpc()
        self.tracker.expect(rid, "initialize")
        self._queue(ccp.initialize_line(rid, self.client_version))

    def start_turn(self, n: int, cap: Decimal, text: str, now: float) -> None:
        """The turn is on record (user_message, turn_started) before this. Its message is written now, or once the
        handshake has passed."""
        self.turn = CodexTurn(n, cap, now, text=text)
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
            line = ccp.turn_start_line(rid, self.tracker.thread_id, t.text)
        except ValueError as exc:
            self._record("error", {"turn": t.n, "message": f"這則訊息無法送給 Codex（{exc}）"})
            self._end_turn("not_sent", now=t.started)
            return
        t.written = True
        self.tracker.begin_turn()
        self.tracker.expect(rid, "turn_start")
        self._queue(line)

    def answer(self, card_id, token, decision, value, now: float) -> tuple[str | None, str]:
        """(None, "") when the card was answered; else (error code, message). A card is answered once: a second
        answer, an expired card or one of an ended turn is gone. A changed text declines the card and steers."""
        import hmac
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
        if decision == "allow" and card.tool == TOOL_FILE:
            # What is allowed is judged again now: a folder of its path may have become a link out of the work folder
            # while the card waited. Codex still writes later, so this narrows the race and does not close it.
            again = ccp.judge_file_change(card.changes, self.cwd)
            if again.action != "ask":
                self._refuse_on_answer(card, decision, value, again.reason, now)
                return "refused", f"卡片出現之後情況變了，VBear 已拒絕：{again.reason}"
        steer = None
        if decision == "modify":
            steer = _steer_text(card, value)
        del self.cards[card_id]
        if decision == "allow":
            self.tracker.approve(card.tool_use_id)
        else:
            self.tracker.refuse(card.tool_use_id)
        self._queue(ccp.decision_line(card.request_id, "accept" if decision == "allow" else "decline"))
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": decision,
                                       "value": value if decision == "modify" else None})
        if steer is not None:
            self._steer(card, steer, now)
        self.last_activity = now
        return None, ""

    def _steer(self, card: Card, text: str, now: float) -> None:
        t = self.turn
        if t is None or t.turn_id is None:
            self.followup_text = text                 # nothing to steer: said as the next message instead
            return
        rid = self._rpc()
        try:
            line = ccp.turn_steer_line(rid, self.tracker.thread_id, t.turn_id, text)
        except ValueError:
            self.followup_text = text
            return
        self.tracker.expect(rid, "turn_steer")
        self.steers.append(text)
        self._queue(line)
        self._record("card_edit_sent", {"card_id": card.card_id, "text": text})

    def _expire(self, card: Card) -> None:
        del self.cards[card.card_id]
        self.tracker.refuse(card.tool_use_id)
        self._queue(ccp.decision_line(card.request_id, "decline"))
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "expired", "value": None})

    def _refuse_on_answer(self, card: Card, decision: str, value, reason: str, now: float) -> None:
        del self.cards[card.card_id]
        self.tracker.refuse(card.tool_use_id)
        self._queue(ccp.decision_line(card.request_id, "decline"))
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "refused",
                                       "value": value if decision == "modify" else None})
        self._record("denied", {"turn": card.turn, "tool_use_id": card.tool_use_id, "tool": card.tool,
                                "summary": _summary(card.tool, card.input),
                                "reason": f"回覆時再檢查一次：{reason}"[:cs.MAX_SHORT], "by": "vbear"})
        self.last_activity = now

    def _cancel_cards(self) -> None:
        for card in list(self.cards.values()):
            del self.cards[card.card_id]
            self.tracker.refuse(card.tool_use_id)
            self._queue(ccp.decision_line(card.request_id, "decline"))
            self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "cancelled",
                                           "value": None})

    def stop(self, reason: str, now: float) -> None:
        """A person stopped the turn, the daemon is closing, or the chat must end: the turn costs its cap. A turn that
        reached Codex is interrupted first, then the process is asked to end by closing its stdin (it is signalled only
        when it has not ended after the grace); anything else ends the process now."""
        t = self.turn
        if t is not None and t.written and not self.finished and self.phase is None and self.stdin_open:
            self._send_interrupt(now)
            self._end_turn("stopped", now=now)
            self.on_writable(now)                       # the interrupt and the refusals leave before stdin closes
            self.close_gracefully(reason, now)
            return
        super().stop(reason, now)

    def delete_thread(self) -> bool:
        """Ask Codex to delete this chat's thread (``thread/delete``). No chat does this: the version check
        (codex_chat_check) deletes the thread it made, from the loop's own thread. False when there is no thread, no turn
        may be open and the process must be idle."""
        if self.thread_id is None or not self.idle or self.turn is not None or not self.stdin_open:
            return False
        rid = self._rpc()
        try:
            line = ccp.thread_delete_line(rid, self.thread_id)
        except ValueError:
            return False
        self.tracker.expect(rid, "thread_delete")
        self._queue(line)
        return True

    def _send_interrupt(self, now: float) -> None:
        t = self.turn
        if t is None or t.interrupt_sent or not t.written or t.turn_id is None:
            return
        rid = self._rpc()
        try:
            line = ccp.turn_interrupt_line(rid, self.tracker.thread_id, t.turn_id)
        except ValueError:
            return
        t.interrupt_sent, t.interrupt_at = True, now
        self.tracker.expect(rid, "turn_interrupt")
        self._queue(line)

    # ---- facts ------------------------------------------------------------------------------------------------

    def _on_fact(self, kind: str, data: dict, now: float) -> None:
        n = self._turn_no()
        if kind == "initialized":
            self._open_thread(now)
        elif kind == "session_ready":
            self._on_ready(data)
        elif kind == "mcp_checked":
            if self.state == "starting":
                self.state = "idle"
                if self.turn is not None:
                    self._write_turn()
        elif kind in ("turn_accepted", "turn_started"):
            if self.turn is not None and self.turn.written:
                self.turn.turn_id = data["turn_id"]
                if self.turn.limit_hit:
                    self._send_interrupt(now)
        elif kind == "approval_request":
            self._on_approval(data, now)
        elif kind == "request_resolved":
            self._on_resolved(data)
        elif kind == "unknown_request":
            self._queue(ccp.error_line(data["request_id"], REFUSED_REQUEST))
            self._record("anomaly", {"event_type": f"server_request/{data['method']}"[:cs.MAX_SHORT], "fields": []})
        elif kind == "delta":
            self.partial = (self.partial + data["text"])[-chs.PARTIAL_MAX:]
        elif kind == "anomaly":
            self._record("anomaly", data)
        elif kind == "violation":
            self._record("error", {"turn": n or None, "message": data["message"]})
            if self.turn is not None:
                self._end_turn("violation", now=now)
            self.terminate("聊天違反 VBear 的設定，已停止")
        elif kind == "request_failed":
            self._on_failed(data, now)
        elif kind == "steer_accepted":
            if self.steers:
                self.steers.popleft()
        elif kind == "turn_completed":
            self._on_completed(data, now)
        elif kind == "usage":
            self._on_usage(data, now)
        elif kind == "plan_usage":
            self._on_plan(data)
        elif n < 1 and kind in ("reply", "command_done", "file_change_done"):
            self._record("anomaly", {"event_type": f"outside_turn/{kind}", "fields": []})
        elif kind == "reply":
            self.partial = ""
            self._record("reply", {"turn": n, "text": data["text"], "truncated": False})
        elif kind == "command_done":
            self._on_done(n, data, TOOL_COMMAND, data.get("exit_code"), data.get("output") or "")
        elif kind == "file_change_done":
            self._on_done(n, data, TOOL_FILE, None, "")
        # remote_control, item_started, steer, interrupt and delete answers, turn_error, thread_deleted: nothing to keep

    def _open_thread(self, now: float) -> None:
        self._queue(ccp.initialized_line())
        rid = self._rpc()
        try:
            if self._resume_thread is not None:
                line = ccp.thread_resume_line(rid, self._resume_thread, cwd=self.cwd, model=self.model_id,
                                              developer_instructions=self._instructions)
                self.tracker.expect(rid, "thread_resume")
            else:
                line = ccp.thread_start_line(rid, cwd=self.cwd, model=self.model_id,
                                             developer_instructions=self._instructions)
                self.tracker.expect(rid, "thread_start")
        except ValueError as exc:
            self._fail(f"無法開啟 Codex 的對話（{exc}）", now)
            return
        self._queue(line)

    def _on_ready(self, data: dict) -> None:
        self.thread_id = data["thread_id"]
        if data["model"] != "?":
            self.shown_model = data["model"]
        self._record("session_ready", {"cli_version": self.cli_version, "permission_mode": "untrusted",
                                       "model": data["model"]})
        if not data["resumed"]:
            self._record("session_bound", {"thread_id": data["thread_id"]})
        rid = self._rpc()
        self.tracker.expect(rid, "mcp_list")
        self._queue(ccp.mcp_status_list_line(rid, self.thread_id))

    def _on_failed(self, data: dict, now: float) -> None:
        kind = data["kind"]
        if kind == "turn_steer":
            if self.steers:
                self.followup_text = self.steers.popleft()
            if self.turn is None:
                self._run_followup(now)
        elif kind == "turn_start":
            self._record("error", {"turn": self._turn_no() or None, "message": "Codex 沒有接受這則訊息"})
            if self.turn is not None:
                self._end_turn("not_sent", now=now)
        elif kind in ("turn_interrupt", "thread_delete"):
            return
        else:
            what = {"initialize": "初始化", "thread_start": "開啟對話", "thread_resume": "接續之前的對話",
                    "mcp_list": "確認沒有 MCP 伺服器"}.get(kind, kind)
            self._fail(f"Codex 沒有接受{what}", now)

    def _on_approval(self, data: dict, now: float) -> None:
        rid, iid = data["request_id"], data["item_id"]
        tool = TOOL_COMMAND if data["kind"] == "command" else TOOL_FILE
        n = self._turn_no() or 1
        inp = _card_input(data, self.cwd)
        action, reason = data["action"], data["why"]
        t = self.turn
        if t is None:
            action, reason = "deny", "這個請求不在任何一回合裡"
        elif t.limit_hit:
            action, reason = "deny", "這回合已到花費上限，正在中斷"
        summary = _summary(tool, inp)
        self._record("tool_call", {"turn": n, "tool_use_id": iid or "?", "tool": tool, "summary": summary})
        card = None
        if action == "ask":
            card = CodexCard(card_id="k-" + secrets.token_hex(8), token=secrets.token_urlsafe(24), request_id=rid,
                             tool=tool, input=inp, tool_use_id=iid, reason=reason, turn=n,
                             editable="command" if tool == TOOL_COMMAND else "content", expires=now + self.card_ttl,
                             changes=data.get("changes") if tool == TOOL_FILE else None)
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
            self._record("card", {"turn": n, "card_id": card.card_id, "tool": tool, "input": inp,
                                  "editable": card.editable, "state": "asked", "reason": reason})
            return
        self.tracker.refuse(iid)
        self._queue(ccp.decision_line(rid, "decline"))
        self._record("denied", {"turn": n, "tool_use_id": iid or "?", "tool": tool, "summary": summary,
                                "reason": reason[:cs.MAX_SHORT], "by": "vbear"})

    def _on_resolved(self, data: dict) -> None:
        """Codex closed a request that is still a card (it ended the turn): the card goes, nothing is answered."""
        for card in list(self.cards.values()):
            if card.request_id == data["request_id"]:
                del self.cards[card.card_id]
                self.tracker.refuse(card.tool_use_id)
                self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "cancelled",
                                               "value": None})

    def _on_done(self, n: int, data: dict, tool: str, exit_code, output: str) -> None:
        if data["status"] == "declined":
            return                                       # the card's own record says so
        failed = data["status"] != "completed" or (exit_code is not None and exit_code != 0)
        self._record("tool_result", {"turn": n, "tool_use_id": data["item_id"], "tool": tool, "is_error": failed,
                                     "text": output, "truncated": False, "source": "codex"})

    def _on_usage(self, data: dict, now: float) -> None:
        n = self._turn_no()
        if n >= 1:
            self._record("usage", {"turn": n, "total_tokens": data["total_tokens"],
                                   "delta_tokens": data["delta_tokens"]})
        t = self.turn
        tokens = self.tracker.turn_tokens
        if t is None or not t.written or t.limit_hit or tokens is None:
            return
        try:
            spent = ccp.estimate_usd(tokens)
        except ValueError:
            return
        if spent >= t.cap:
            t.limit_hit = True
            self._cancel_cards()
            self._send_interrupt(now)

    def _on_plan(self, data: dict) -> None:
        n = self._turn_no()
        key = tuple(data[k] for k in ("primary_pct", "primary_window_min", "primary_resets_at", "secondary_pct",
                                      "secondary_window_min", "secondary_resets_at", "reached"))
        if n < 1 or key == self.last_plan:
            return
        self.last_plan = key
        self._record("plan_usage", {"turn": n, **data})

    def _on_completed(self, data: dict, now: float) -> None:
        t = self.turn
        if t is None:
            self._record("anomaly", {"event_type": "turn_completed/outside_turn", "fields": []})
            return
        if t.turn_id is not None and data["turn_id"] not in (None, t.turn_id):
            self._record("anomaly", {"event_type": "turn_completed/other_turn", "fields": []})
            return
        status = data["status"]
        self._end_turn("limit" if t.limit_hit else "result", now=now, status=status,
                       is_error=status != "completed" or data["error"])
        if self.followup_text is not None:
            self._run_followup(now)

    def _run_followup(self, now: float) -> None:
        """The text of a changed card whose steer Codex refused goes as the next message, a new turn."""
        text, self.followup_text = self.followup_text, None
        if text is None:
            return
        why = "聊天已經在結束了" if (self.phase is not None or self.finished or self.state == "closing") \
            else "沒有辦法送出" if self.followup_hook is None else self.followup_hook(self, text)
        if why:
            self._record("error", {"turn": None, "message": f"改過的內容沒有送出：{why}"[:cs.MAX_EXCERPT]})

    # ---- a turn's end -----------------------------------------------------------------------------------------

    def _end_turn(self, reason: str, *, now: float, status=None, is_error=False) -> None:
        """"result" and "limit" come from Codex's own end of the turn and cost its tokens (the cap when there is no usable
        count); the rest cut the turn off and cost its cap, or its estimate when that is more; a turn never written costs
        nothing."""
        t = self.turn
        if t is None:
            return
        tokens = self.tracker.turn_tokens if t.written else None
        estimate = False
        if not t.written:
            cost, reason = Decimal(0), "not_sent"
        else:
            try:
                spent = ccp.estimate_usd(tokens)
            except ValueError:
                spent, tokens = None, None
            if reason in ("result", "limit"):
                cost, estimate = (spent, True) if spent is not None else (t.cap, False)
            else:
                cost, estimate = (spent, True) if spent is not None and spent > t.cap else (t.cap, False)
        self.turn = None
        self.spent += cost
        self.partial = ""
        self._record("turn_ended", {"turn": t.n, "cost_usd": cs.usd(cost), "reported": False, "total_usd": None,
                                    "reason": reason,
                                    "subtype": status if isinstance(status, str) and status != "?" else None,
                                    "is_error": bool(is_error) or reason not in ("result",),
                                    "estimate": estimate, "tokens": tokens})
        self._cancel_cards()
        self.last_activity = now

    def _timers(self, now: float) -> None:
        super()._timers(now)
        t = self.turn
        if (not self.finished and self.phase is None and t is not None and t.interrupt_at is not None
                and now - t.interrupt_at > INTERRUPT_GRACE):
            self._fail("Codex 沒有在中斷之後結束這回合", now)


# ---- what a card shows ----------------------------------------------------------------------------------------

def _relative(path, cwd: str):
    """A path as the card shows it: relative to the work folder when it is inside it, else as given."""
    if not isinstance(path, str):
        return path
    if path == cwd:
        return "."
    prefix = cwd.rstrip("/") + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def _card_input(data: dict, cwd: str) -> dict:
    if data["kind"] == "command":
        inp = {"command": data.get("command") or "", "cwd": _relative(data.get("cwd"), cwd),
               "actions": [{"type": a["type"], "command": a["command"]} for a in data.get("actions") or []]}
    else:
        inp = {"changes": []}
        for c in data.get("changes") or []:
            kind = c.get("kind") if isinstance(c.get("kind"), dict) else {}
            row = {"path": _relative(c.get("path"), cwd), "kind": kind.get("type"), "diff": c.get("diff")}
            if kind.get("move_path") is not None:
                row["move_to"] = _relative(kind["move_path"], cwd)
            inp["changes"].append(row)
    if data.get("codex_reason"):
        inp["codex_reason"] = data["codex_reason"]
    return inp


def _summary(tool: str, inp: dict) -> str:
    if tool == TOOL_COMMAND:
        return str(inp.get("command", ""))[:cs.MAX_EXCERPT]
    changes = inp.get("changes") if isinstance(inp.get("changes"), list) else []
    names = ", ".join(f"{c.get('kind')} {c.get('path')}" for c in changes if isinstance(c, dict))
    return f"{len(changes)} 個檔案：{names}"[:cs.MAX_EXCERPT]


def _steer_text(card: Card, value: str) -> str:
    """What Codex is told when a person changed what a card asked for (in English: Codex's own working language)."""
    if card.tool == TOOL_COMMAND:
        return ("I changed the command. Do not run the previous one. Run exactly this shell command instead: "
                + value)
    paths = ", ".join(str(c.get("path")) for c in card.input.get("changes", []) if isinstance(c, dict))
    return (f"I changed my mind about the file change you proposed ({paths}). Do not make it. Make this change "
            f"instead, as a new file change: {value}")
