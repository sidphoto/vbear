"""One chat process owned by the runtime daemon (P36): Claude Code in stream-json mode, asking on stdin about each
tool call it does not allow by itself (a read in its own folder it may allow alone: VBear sees that one only by its
result and stops the chat when it would not have allowed it), talking with a person for a role card. The daemon's
selectors loop calls on_stdout / on_stderr / on_writable when a pipe is ready and tick() on every pass; the RPC ops
call start_turn, answer, stop and close_gracefully.

  * The first line written is the ``initialize`` request; a person's message is held until its answer passes
    (chat_protocol.ChatTracker), so a turn whose message was never written costs nothing.
  * Every permission request is judged (chat_protocol.judge): VBear answers it itself, or it becomes a card that
    only the RPC holding its one-use token can answer, once, before it expires; an expired card is refused, by the
    answer itself as by the timer. An allow (or a changed input) is judged again when it is given: a call that
    became one VBear refuses (a folder of its path is now a link out of the work folder) is refused then.
  * The cards waiting together fit one chat_events reply whole: each at most CARD_SHOW_MAX, all of them at most
    CARDS_SHOW_TOTAL, as they are shown; one that does not fit is refused, never shown cut.
  * A turn ends with its result (it costs what the CLI's cumulative total says it added), or is cut off (stopped,
    timed out, the process ended, a violation): then it costs its cap. Only a turn that never reached the CLI
    costs nothing.
  * Facts go to the chat's events file (chat_store.ChatLog). A violation, an unwritable record, a stalled write or
    a turn over its time stops the process; it is ended as a stream session is (stream_session.ProcessGroupEnd).
  * stderr is read and dropped; nothing of it is kept.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from .. import meetings as mt
from .. import strictjson
from . import chat_protocol as cp, chat_store as cs, proctrack
from .stream_session import DRAIN_AFTER_EXIT, LINE_MAX, OBSERVE_EVERY, ProcessGroupEnd

READ_CHUNK = 64 << 10
READ_BUDGET = 16
STDOUT_MAX = 256 << 20
STDERR_MAX = 64 << 20
EVENTS_MAX = 200_000
WRITE_DEADLINE = 10.0
PARTIAL_MAX = 64_000          # characters of the reply being written that are kept for the live view
CARD_SHOW_MAX = 12 << 10      # one card as the live view shows it (UTF-8 JSON); a larger one is refused
CARDS_SHOW_TOTAL = 30 << 10   # the cards waiting at once, as shown; one that would pass it is refused
MAX_CARDS = 8                 # cards waiting at once; more are refused
LIVE_MAX = 40 << 10           # the whole live view; the reply being written is cut (from its start) to fit
PARTIAL_CHARS = 4000          # at most this much of the reply being written is shown
EXPIRED = "這張權限卡片已過期，VBear 視為拒絕"
DENIED = "使用者拒絕了這個操作"
CANCELLED = "這回合已結束，VBear 視為拒絕"
UNKNOWN_CONTROL = "VBear 不接受這種控制請求"


@dataclass
class Turn:
    n: int
    cap: Decimal
    started: float                 # monotonic
    line: bytes = b""
    written: bool = False          # queued to the CLI's stdin: from then it may cost up to its cap


@dataclass
class Card:
    card_id: str
    token: str
    request_id: str
    tool: str
    input: dict
    tool_use_id: str | None
    editable: str | None
    reason: str
    turn: int
    expires: float                 # monotonic
    asked_at: float = field(default_factory=time.time)
    shown: int = 0                 # bytes of the card in the live view, at most


class ChatProcess(ProcessGroupEnd):
    def __init__(self, *, sid: str, chat_id: str, profile_id: str, manifest: dict, proc, log: cs.ChatLog,
                 last_total: float | None, next_turn: int, now: float, leader_start: str | None, logger,
                 watch, unwatch, card_ttl: float, init_deadline: float, turn_timeout: float, idle_timeout: float,
                 close_grace: float, close_below: Decimal, prompt_sha: str | None = None):
        self.sid = sid
        self.prompt_sha = prompt_sha            # memory_rules.prompt_sha of the system prompt it was started with
        self.chat_id = chat_id
        self.profile_id = profile_id
        self.manifest = manifest
        self.launch_id = manifest["launch_id"]
        self.cli_version = manifest["cli_version"]
        self.model_id = manifest["model_id"]
        self.session_id = manifest.get("claude_session_id")
        self.cwd = manifest["canonical_workspace"]
        self.budget = mt.money(manifest.get("budget_usd")) or Decimal(0)
        self.proc = proc
        self.pid = self.pgid = proc.pid
        self.leader_start = leader_start
        self.stdin = proc.stdin.fileno()
        self.stdout = proc.stdout.fileno()
        self.stderr = proc.stderr.fileno()
        for fd in (self.stdin, self.stdout, self.stderr):
            os.set_blocking(fd, False)
        self.log = log
        self._log = logger
        self._watch, self._unwatch = watch, unwatch
        self.card_ttl, self.init_deadline, self.turn_timeout = card_ttl, init_deadline, turn_timeout
        self.idle_timeout, self.close_grace, self.close_below = idle_timeout, close_grace, close_below
        self.init_id = "init-" + secrets.token_hex(6)
        self.tracker = self._new_tracker()
        self.started = time.time()
        self.spawned = now
        self.state = "starting"                  # starting | idle | closing
        self.turn: Turn | None = None
        self.last_turn = next_turn - 1
        self.next_turn = next_turn
        self.cards: dict[str, Card] = {}
        self.partial = ""
        self.last_total = last_total
        self.spent = Decimal(0)
        self.last_activity = now
        self.closing_since: float | None = None
        self.buf = bytearray()
        self.stdout_total = self.stderr_total = self.events_total = 0
        self.stdout_eof = self.stderr_eof = False
        self.stdin_open = True
        self.out: deque[bytes] = deque()
        self.wbuf = memoryview(b"")
        self.write_since: float | None = None
        self.broken = ""                          # why the record cannot be written any more
        # ProcessGroupEnd
        self.writing = None
        self.exit_info = None
        self.exit_seen = 0.0
        self.exit_recorded = False
        self.phase: str | None = None
        self.phase_deadline = 0.0
        self.escape_deadline: float | None = None
        self.escape_next = 0.0
        self.close_reason = ""
        self.finished = False
        self.reaped = False
        self.outcome: dict | None = None
        self.descendants = proctrack.DescendantTracker(self.pid)
        self.next_observe = now
        self.registered: set[str] = set()

    def _new_tracker(self):
        """What reads the CLI's output (a Codex chat reads another protocol: codex_chat_session)."""
        return cp.ChatTracker(cp.constants_for(self.cli_version), session_id=self.session_id, workdir=self.cwd,
                              init_request_id=self.init_id)

    def _read_facts(self, value) -> list:
        return self.tracker.on_event(value)

    # ---- what the daemon asks ----------------------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        """Whether the loop should look again soon (a turn, a write, an end in progress)."""
        return bool(self.turn or self.out or self.wbuf or self.phase or self.exit_info or self.state == "closing")

    @property
    def idle(self) -> bool:
        return (self.state == "idle" and self.turn is None and not self.cards and self.phase is None
                and self.exit_info is None)

    @property
    def wants_write(self) -> bool:
        return self.stdin_open and not self.finished and bool(self.wbuf or self.out)

    def headroom(self) -> Decimal:
        """What this process may still spend under its --max-budget-usd, as VBear counts it."""
        return self.budget - self.spent - (self.turn.cap if self.turn else Decimal(0))

    def info(self) -> dict:
        return {"session_id": self.sid, "pid": self.pid, "pgid": self.pgid, "argv": [], "cwd": self.cwd,
                "cols": 0, "rows": 0, "started": self.started, "exited": self.exit_info is not None,
                "exit_code": self._returncode(), "closing": self.phase is not None or self.state == "closing",
                "output_bytes": self.stdout_total, "attachments": 0, "control_attachment": None,
                "managed": self.launch_id, "engine": "claude-chat", "kind": None, "cli_version": self.cli_version,
                "activity_evidence": {"claude_chat": {"state": self.live_state()}}}

    def live_state(self) -> str:
        if self.finished or self.exit_info is not None or self.phase is not None:
            return "ending"
        if self.state == "closing":
            return "closing"
        if self.state == "starting":
            return "starting"
        if self.cards:
            return "waiting_for_you"
        return "working" if self.turn else "idle"

    def live_view(self, now: float) -> dict:
        """What a person sees now: every waiting card whole (they fit LIVE_MAX by CARDS_SHOW_TOTAL) and the end of
        the reply being written, as much of it as fits what is left."""
        view = {"state": self.live_state(), "turn": self.turn.n if self.turn else None, "partial": "",
                "partial_truncated": False, "model": self.model_id,
                "cards": [_card_view(c, now) for c in sorted(self.cards.values(), key=lambda c: c.asked_at)]}
        text = self.partial.encode("utf-8", "replace").decode("utf-8")     # a lone surrogate is shown as "?"
        tail = _tail_within(text[-PARTIAL_CHARS:], LIVE_MAX - _size(view))
        view["partial"], view["partial_truncated"] = tail, len(tail) < len(text)
        return view

    def send_initialize(self) -> None:
        self._queue(cp.initialize_line(self.init_id))

    def start_turn(self, n: int, cap: Decimal, line: bytes, now: float) -> None:
        """The turn is on record (user_message, turn_started) before this. Its message is written now, or once the
        initialize answer has passed."""
        self.turn = Turn(n, cap, now, line)
        self.next_turn = n + 1
        self.last_turn = n
        self.partial = ""
        self.last_activity = now
        if self.state == "idle":
            self._write_turn()

    def answer(self, card_id, token, decision, value, now: float) -> tuple[str | None, str]:
        """(None, "") when the card was answered; else (error code, message). A card is answered once: a second
        answer, an expired card or one of an ended turn is gone."""
        card = self.cards.get(card_id) if isinstance(card_id, str) else None
        if card is None:
            return "gone", "這張卡片已經回覆過、已過期或不存在"
        if now >= card.expires:                  # whether or not the timer has run yet
            self._expire(card)
            return "expired", "這張卡片已過期，VBear 已視為拒絕"
        if not (isinstance(token, str) and hmac.compare_digest(token.encode("utf-8", "replace"),
                                                                card.token.encode("ascii"))):
            return "bad_token", "卡片的 token 不符"
        if decision not in ("allow", "deny", "modify"):
            return "bad_request", "decision 必須是 allow、deny 或 modify"
        if decision != "modify" and value is not None:
            return "bad_request", "只有「改內容再允許」可以帶 value"
        sent = card.input
        if decision == "modify":
            if card.editable is None:
                return "bad_request", f"{card.tool} 沒有可以改的內容"
            if not isinstance(value, str) or (card.tool == "Bash" and not value.strip()):
                return "bad_request", "改過的內容必須是文字"
            sent = {**card.input, card.editable: value}
        if decision != "deny":
            # What is allowed is judged again now, as it will be sent: a folder of its path may have become a link
            # out of the work folder while the card waited. The CLI still writes later, so this narrows the race
            # and does not close it.
            again = cp.judge(card.tool, sent, self.cwd)
            if again.action == "deny":
                self._refuse_on_answer(card, decision, value, sent, again.reason, now)
                return "refused", f"卡片出現之後情況變了，VBear 已拒絕：{again.reason}"
        try:
            line = cp.deny_line(card.request_id, DENIED) if decision == "deny" else cp.allow_line(card.request_id, sent)
        except ValueError as exc:
            return "bad_request", f"無法送出這個回覆（{exc}）"
        del self.cards[card_id]
        if decision == "deny":
            self.tracker.refuse(card.tool_use_id)
        else:
            self.tracker.approve(card.tool_use_id)
        self._queue(line)
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": decision,
                                       "value": value if decision == "modify" else None})
        self.last_activity = now
        return None, ""

    def _expire(self, card: Card) -> None:
        del self.cards[card.card_id]
        self.tracker.refuse(card.tool_use_id)
        self._queue(cp.deny_line(card.request_id, EXPIRED))
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "expired",
                                       "value": None})

    def _refuse_on_answer(self, card: Card, decision: str, value, sent: dict, reason: str, now: float) -> None:
        del self.cards[card.card_id]
        self.tracker.refuse(card.tool_use_id)
        self._queue(cp.deny_line(card.request_id, reason))
        self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "refused",
                                       "value": value if decision == "modify" else None})
        self._record("denied", {"turn": card.turn, "tool_use_id": card.tool_use_id, "tool": card.tool,
                                "summary": cp.summary(card.tool, sent),
                                "reason": f"回覆時再檢查一次：{reason}"[:cs.MAX_SHORT], "by": "vbear"})
        self.last_activity = now

    def stop(self, reason: str, now: float) -> None:
        """A person stopped the turn, the daemon is closing, or the chat must end: the turn costs its cap."""
        if self.turn is not None:
            self._end_turn("stopped", now=now)
        self.terminate(reason)

    def close_gracefully(self, reason: str, now: float) -> None:
        """End an idle process by closing its stdin; it is signalled only if it has not ended after the grace."""
        if self.state == "closing" or self.finished:
            return
        self.state = "closing"
        self.close_reason = reason
        self.closing_since = now
        self._close_stdin()

    # ---- pipes ------------------------------------------------------------------------------------------------

    def _queue(self, line: bytes) -> None:
        if not self.stdin_open or self.finished:
            return
        self.out.append(line)
        if self.write_since is None:
            self.write_since = time.monotonic()
        self._watch(self, "stdin")

    def _close_stdin(self) -> None:
        if not self.stdin_open:
            return
        self._unwatch(self, "stdin")
        self.stdin_open = False
        self.out.clear()
        self.wbuf = memoryview(b"")
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def on_writable(self, now: float) -> bool:
        """Write what the pipe takes; True when nothing is left to write."""
        while self.stdin_open and not self.finished:
            if not self.wbuf:
                if not self.out:
                    self.write_since = None
                    return True
                self.wbuf = memoryview(self.out.popleft())
            try:
                n = os.write(self.stdin, self.wbuf)
            except BlockingIOError:
                return False
            except OSError:
                self._fail("無法寫入 Claude Code 的輸入", now)
                return True
            self.wbuf = self.wbuf[n:]
            self.write_since = now
        return True

    def on_stdout(self, now: float) -> None:
        for _ in range(READ_BUDGET):
            if self.finished:
                return
            try:
                chunk = os.read(self.stdout, READ_CHUNK)
            except BlockingIOError:
                return
            except InterruptedError:
                continue
            except OSError:
                self.stdout_eof = True
                self._fail("讀取 Claude Code 的輸出時發生錯誤", now)
                return
            if not chunk:
                self.stdout_eof = True
                return
            self.stdout_total += len(chunk)
            if self.stdout_total > STDOUT_MAX:
                self._fail("Claude Code 的輸出超過上限", now)
                return
            self.buf += chunk
            while not self.finished:
                cut = self.buf.find(b"\n")
                if cut < 0:
                    break
                line = bytes(self.buf[:cut])
                del self.buf[:cut + 1]
                self._on_line(line, now)
            if len(self.buf) > LINE_MAX:
                self.buf.clear()
                self._record("anomaly", {"event_type": "line_too_long", "fields": []})

    def on_stderr(self, now: float) -> None:
        for _ in range(READ_BUDGET):
            if self.finished:
                return
            try:
                chunk = os.read(self.stderr, READ_CHUNK)
            except BlockingIOError:
                return
            except InterruptedError:
                continue
            except OSError:
                self.stderr_eof = True
                return
            if not chunk:
                self.stderr_eof = True
                return
            self.stderr_total += len(chunk)       # read and dropped: nothing of it is kept
            if self.stderr_total > STDERR_MAX:
                self._fail("Claude Code 的錯誤輸出超過上限", now)
                return

    def _on_line(self, line: bytes, now: float) -> None:
        if not line.strip() or self.tracker.stopped:
            return
        self.events_total += 1
        if self.events_total > EVENTS_MAX:
            self._fail("Claude Code 的事件數超過上限", now)
            return
        parsed = strictjson.loads(line, strictjson.CLAUDE_STDOUT)
        if not parsed.ok:
            self._record("anomaly", {"event_type": "bad_json", "fields": []})
            return
        self.last_activity = now
        for kind, data in self._read_facts(parsed.value):
            try:
                self._on_fact(kind, data, now)
            except Exception as exc:              # never out of the loop: the chat ends instead
                self._fail(f"處理 Claude Code 的事件時發生錯誤（{type(exc).__name__}）", now)
                return
            if self.finished or self.phase is not None:
                return

    # ---- facts ------------------------------------------------------------------------------------------------

    def _turn_no(self) -> int:
        return self.turn.n if self.turn else self.last_turn

    def _on_fact(self, kind: str, data: dict, now: float) -> None:
        n = self._turn_no()
        if kind == "initialized":
            if self.state == "starting":
                self.state = "idle"
                if self.turn is not None:
                    self._write_turn()
        elif kind == "session_ready":
            self._record("session_ready", data)
        elif kind == "permission_request":
            self._on_permission(data, now)
        elif kind == "unknown_control":
            self._queue(cp.error_line(data["request_id"], UNKNOWN_CONTROL))
            self._record("anomaly", {"event_type": f"control_request/{data['subtype']}"[:cs.MAX_SHORT],
                                     "fields": []})
        elif kind == "delta":
            self.partial = (self.partial + data["text"])[-PARTIAL_MAX:]
        elif kind == "anomaly":
            self._record("anomaly", data)
        elif kind == "violation":
            self._record("error", {"turn": n or None, "message": data["message"]})
            if self.turn is not None:
                self._end_turn("violation", now=now)
            self.terminate("聊天違反 VBear 的設定，已停止")
        elif n < 1:
            self._record("anomaly", {"event_type": f"outside_turn/{kind}", "fields": []})
        elif kind == "reply":
            self.partial = ""
            self._record("reply", {"turn": n, "text": data["text"], "truncated": False})
        elif kind == "tool_call":
            self._record("tool_call", {"turn": n, "tool_use_id": data["tool_use_id"], "tool": data["tool"],
                                       "summary": cp.summary(data["tool"], data["input"])})
        elif kind == "tool_result":
            self._record("tool_result", {"turn": n, "tool_use_id": data["tool_use_id"], "tool": data["tool"],
                                         "is_error": data["is_error"], "text": data["text"], "truncated": False,
                                         "source": data["source"]})
        elif kind == "denied":
            self._record("denied", {"turn": n, "tool_use_id": data["tool_use_id"], "tool": data["tool"],
                                    "summary": "", "reason": "Claude Code 自己拒絕了這個操作", "by": "cli"})
        elif kind == "result":
            if self.turn is None:
                self._record("anomaly", {"event_type": "result/outside_turn", "fields": []})
            else:
                self._end_turn("result", now=now, total=data["total_cost_usd"], subtype=data["subtype"],
                               is_error=data["is_error"])

    def _on_permission(self, data: dict, now: float) -> None:
        rid, tool, inp, tid = data["request_id"], data["tool"], data["input"], data["tool_use_id"]
        name = tool if isinstance(tool, str) and 0 < len(tool) <= 64 else "?"
        if self.turn is None:
            j = cp.Judgement("deny", "這個請求不在任何一回合裡")
        else:
            j = cp.judge(tool, inp, self.cwd)
        card = None
        if j.action == "ask":
            card = Card(card_id="k-" + secrets.token_hex(8), token=secrets.token_urlsafe(24), request_id=rid,
                        tool=name, input=inp, tool_use_id=tid, editable=j.editable, reason=j.reason,
                        turn=self._turn_no() or 1, expires=now + self.card_ttl)
            try:
                card.shown = _size(_card_view(card, now))   # expires_in only gets shorter from here
            except (ValueError, TypeError, UnicodeEncodeError, RecursionError):
                card.shown = CARD_SHOW_MAX + 1
            if card.shown > CARD_SHOW_MAX:
                j = cp.Judgement("deny", "內容太長，無法完整顯示給你確認，VBear 直接拒絕")
            elif len(self.cards) >= MAX_CARDS:
                j = cp.Judgement("deny", "等你回覆的卡片太多，VBear 直接拒絕")
            elif sum(c.shown for c in self.cards.values()) + card.shown > CARDS_SHOW_TOTAL:
                j = cp.Judgement("deny", "等你回覆的卡片內容加起來太多，無法一起完整顯示，VBear 直接拒絕；"
                                         "請先回覆前面的卡片")
        n = self._turn_no() or 1
        summary = cp.summary(tool, inp)
        if j.action == "allow":
            self.tracker.approve(tid)
            self._queue(cp.allow_line(rid, inp))
            self._record("auto_allowed", {"turn": n, "tool_use_id": tid, "tool": name, "summary": summary,
                                          "reason": j.reason})
        elif j.action == "deny":
            self.tracker.refuse(tid)
            self._queue(cp.deny_line(rid, j.reason))
            self._record("denied", {"turn": n, "tool_use_id": tid, "tool": name, "summary": summary,
                                    "reason": j.reason, "by": "vbear"})
        else:
            self.cards[card.card_id] = card
            self._record("card", {"turn": n, "card_id": card.card_id, "tool": name, "input": inp,
                                  "editable": j.editable, "state": "asked", "reason": j.reason})

    def _write_turn(self) -> None:
        t = self.turn
        if t is None or t.written:
            return
        t.written = True
        self._queue(t.line)

    def _end_turn(self, reason: str, *, now: float, total=None, subtype=None, is_error=False) -> None:
        t = self.turn
        if t is None:
            return
        if reason == "result":
            cost, reported = cp.turn_cost(total, self.last_total, t.cap)
        elif not t.written:
            cost, reported, reason = Decimal(0), False, "not_sent"
        else:
            cost, reported = t.cap, False
        if total is not None:
            self.last_total = total             # the next turn's base, even when this one went back
        self.turn = None
        self.spent += cost
        self.partial = ""
        self._record("turn_ended", {"turn": t.n, "cost_usd": cs.usd(cost), "reported": reported,
                                    "total_usd": total, "reason": reason,
                                    "subtype": subtype if isinstance(subtype, str) and subtype != "?" else None,
                                    "is_error": bool(is_error) or reason != "result"})
        self._cancel_cards()
        self.last_activity = now
        if (reason == "result" and self.phase is None and self.state == "idle"
                and self.budget - self.spent < self.close_below):
            self.close_gracefully("這個程序剩下的額度不夠下一回合", now)

    def _cancel_cards(self) -> None:
        for card in list(self.cards.values()):
            del self.cards[card.card_id]
            self.tracker.refuse(card.tool_use_id)
            self._queue(cp.deny_line(card.request_id, CANCELLED))
            self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "cancelled",
                                           "value": None})

    def _record(self, kind: str, data: dict) -> bool:
        if self.broken or self.log.fd < 0:
            return False
        try:
            self.log.append(kind, data, now=time.time())
            return True
        except cs.ChatStoreError as exc:
            if exc.code == "bad_record" and kind not in ("turn_ended", "process_ended"):
                # one event that does not fit the record (a field out of shape): noted, the chat goes on
                try:
                    self.log.append("anomaly", {"event_type": f"unrecorded/{kind}", "fields": []}, now=time.time())
                    return False
                except cs.ChatStoreError:
                    pass
            self.broken = f"{exc.code}: {exc.message}"[:200]
            self._log(f"{self.sid}: chat record not written ({self.broken}); ending the process")
            self.terminate("聊天紀錄無法寫入")
            return False

    def _fail(self, why: str, now: float) -> None:
        self._record("error", {"turn": self._turn_no() or None, "message": why})
        if self.turn is not None:
            self._end_turn("error", now=now)
        self.terminate(why)

    # ---- timers, exit -----------------------------------------------------------------------------------------

    def tick(self, now: float) -> None:
        if self.finished:
            return
        if now >= self.next_observe:
            self.next_observe = now + OBSERVE_EVERY
            try:
                self.descendants.observe()
            except proctrack.ProcessTableUnavailable:
                pass
        if self.phase is None and self.exit_info is None:
            self._timers(now)
        if self.finished:
            return
        self._poll_exit(now)
        if self.exit_info is not None and not self.exit_recorded:
            if (self.stdout_eof and self.stderr_eof) or now - self.exit_seen > DRAIN_AFTER_EXIT:
                self._record_exit(now)
        self._advance_termination(now)

    def _timers(self, now: float) -> None:
        if self.write_since is not None and (self.wbuf or self.out) and now - self.write_since > WRITE_DEADLINE:
            self._fail("寫入 Claude Code 的輸入逾時", now)
            return
        if self.state == "starting" and now - self.spawned > self.init_deadline:
            self._fail("Claude Code 沒有回應初始化（initialize）", now)
            return
        t = self.turn
        if t is not None and t.written and now - t.started > self.turn_timeout:
            self._fail(f"這回合超過時限（{int(self.turn_timeout // 60) or 1} 分鐘），已停止", now)
            return
        for card in sorted(self.cards.values(), key=lambda c: c.expires):
            if now >= card.expires:
                self._expire(card)
        if self.idle and now - self.last_activity > self.idle_timeout:
            self.close_gracefully("閒置太久，自動關閉", now)
        if self.state == "closing" and self.closing_since is not None and now - self.closing_since > self.close_grace:
            self.terminate(self.close_reason or "關閉")

    def _record_exit(self, now: float) -> None:
        self.exit_recorded = True
        if self.turn is not None:
            self._end_turn("process_exit", now=now)
        self._cancel_cards()
        self._close_stdin()
        info = self.exit_info
        code = info.si_status if info.si_code == os.CLD_EXITED else None
        self._record("process_ended", {"reason": (self.close_reason or "Claude Code 已結束")[:cs.MAX_SHORT],
                                       "returncode": code if code is not None and 0 <= code <= 255 else None})

    # ---- ProcessGroupEnd ------------------------------------------------------------------------------------------

    def _close_record(self) -> None:
        """The chat's record is closed with the process. Given up before its exit was seen (manual review): the
        open turn costs its cap and the record says the process was handed to a person."""
        self.stdin_open = False                   # the pipes are closed already: nothing more is queued
        self.out.clear()
        if not self.exit_recorded:
            self.exit_recorded = True
            now = time.monotonic()
            if self.turn is not None:
                self.turn.written = True
                self._end_turn("error", now=now)
            self.cards.clear()
            self._record("process_ended", {"reason": f"交人工處理：{self.close_reason or '無法確認程序已結束'}"
                                                     [:cs.MAX_SHORT], "returncode": None})
        self.log.close()

    def _outcome_extra(self) -> dict:
        return {"chat_id": self.chat_id}


def _size(value) -> int:
    """Bytes of a value in a daemon reply (UTF-8 JSON, as daemon.py writes it)."""
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _card_view(c: Card, now: float) -> dict:
    return {"card_id": c.card_id, "token": c.token, "turn": c.turn, "tool": c.tool, "input": c.input,
            "editable": c.editable, "reason": c.reason, "expires_in": max(0.0, round(c.expires - now, 1))}


def _tail_within(text: str, room: int) -> str:
    """The longest end of ``text`` whose JSON string adds at most ``room`` bytes to an empty one."""
    if _size(text) - 2 <= room:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if _size(text[mid:]) - 2 <= room:
            hi = mid
        else:
            lo = mid + 1
    return text[lo:]
