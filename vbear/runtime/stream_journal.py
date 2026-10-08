"""The stream session journal (design 2.5), its state machine, and turn
validity (2.4). The journal records facts only; every conclusion (session
state, dispatch status, whether a turn is valid) is recomputed from them by
the functions here, live in the daemon and on recovery alike.

Record: {"v":1,"seq":N,"t":epoch,"kind":k,"data":{...},"sha256":hex}; seq
from 1, t finite and never more than 2 s before the previous record, sha256
over the canonical form without that field. One write() and fsync per
record; at most 16 MiB per journal, 512 KiB per line.
"""

from __future__ import annotations

import os
import re
import stat
import time
from dataclasses import dataclass, field

from .. import strictjson
from ..numbers import finite_real
from . import stream_protocol as sp

JOURNAL_NAME = "journal.jsonl"
MAX_JOURNAL = strictjson.SESSION_LOG.file_bytes
MAX_LINE = strictjson.SESSION_LOG.unit_bytes
CLOCK_BACK_S = 2.0
EARLIEST = 1577836800.0                   # 2020-01-01

_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
_FLOW = re.compile(r"^flow-[0-9a-f]{12}\Z")
_VERSION = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}\Z")
_ID = re.compile(r"^[\x21-\x7e]{1,256}\Z")          # request/message/tool ids: printable, bounded
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}\Z")

TERMINAL = ("error", "uncertain", "exited")


class JournalCorrupt(Exception):
    pass


# --- data schemas (missing, extra or mistyped fields are corruption) --------------

def _uuid(v):
    return isinstance(v, str) and sp.UUID_RE.match(v) is not None


def _int(v, low, high):
    return isinstance(v, int) and not isinstance(v, bool) and low <= v <= high


def _str(v, limit):
    return isinstance(v, str) and len(v) <= limit


def _money(v):
    if isinstance(v, bool):
        return False
    x = finite_real(v)
    return x is not None and x >= 0


def _assistant_event(e):
    return (isinstance(e, dict) and set(e) == {"request_id", "message_id", "user_message_uuid", "user_message_uuids"}
            and isinstance(e["request_id"], str) and _ID.match(e["request_id"]) is not None
            and isinstance(e["message_id"], str) and _ID.match(e["message_id"]) is not None
            and (e["user_message_uuid"] is None or _uuid(e["user_message_uuid"]))
            and (e["user_message_uuids"] is None or (isinstance(e["user_message_uuids"], list)
                                                     and len(e["user_message_uuids"]) <= 16
                                                     and all(_uuid(x) for x in e["user_message_uuids"]))))


def _tool_call(c):
    return (isinstance(c, dict) and set(c) == {"tool_use_id", "name", "input_sha256", "result_count",
                                               "result_is_error", "result_text_sha256"}
            and isinstance(c["tool_use_id"], str) and _ID.match(c["tool_use_id"]) is not None
            and _str(c["name"], 128) and isinstance(c["input_sha256"], str) and _HEX64.match(c["input_sha256"])
            and _int(c["result_count"], 0, 1)
            and (c["result_is_error"] is None or isinstance(c["result_is_error"], bool))
            and (c["result_text_sha256"] is None or (isinstance(c["result_text_sha256"], str)
                                                     and _HEX64.match(c["result_text_sha256"]) is not None))
            and (c["result_count"] == 0) == (c["result_is_error"] is None) == (c["result_text_sha256"] is None))


def _turn_result(d):
    if set(d) != {"dispatch_id", "subtype", "is_error", "num_turns", "total_cost_usd", "result_index",
                  "user_message_uuids", "assistant_events", "tool_calls", "structured_output", "result_text",
                  "result_too_large"}:
        return False
    return (_uuid(d["dispatch_id"]) and _str(d["subtype"], 64) and isinstance(d["is_error"], bool)
            and _int(d["num_turns"], 0, sp.MAX_NUM_TURNS) and _money(d["total_cost_usd"])
            and _int(d["result_index"], 0, sp.MAX_RESULT_INDEX)
            and d["user_message_uuids"] == [d["dispatch_id"]]
            and isinstance(d["assistant_events"], list) and len(d["assistant_events"]) <= 50_000
            and all(_assistant_event(e) for e in d["assistant_events"])
            and isinstance(d["tool_calls"], list) and len(d["tool_calls"]) <= 50_000
            and all(_tool_call(c) for c in d["tool_calls"])
            and (d["structured_output"] is None or isinstance(d["structured_output"], dict))
            and isinstance(d["result_too_large"], bool)
            and (d["result_text"] is None or (isinstance(d["result_text"], str)
                                              and len(d["result_text"].encode("utf-8")) <= sp.MAX_RESULT_TEXT))
            and not (d["result_too_large"] and d["result_text"] is not None))


SCHEMAS = {
    "session_started": lambda d: (set(d) == {"claude_session_id", "pipeline_id", "cli_version", "argv_sha256",
                                             "budget_usd"}
                                  and _uuid(d["claude_session_id"]) and isinstance(d["pipeline_id"], str)
                                  and _FLOW.match(d["pipeline_id"]) is not None
                                  and isinstance(d["cli_version"], str) and _VERSION.match(d["cli_version"]) is not None
                                  and isinstance(d["argv_sha256"], str) and _HEX64.match(d["argv_sha256"]) is not None
                                  and _money(d["budget_usd"]) and finite_real(d["budget_usd"]) > 0),
    "dispatch_accepted": lambda d: (set(d) == {"dispatch_id", "text_sha256", "length", "approval"}
                                    and _uuid(d["dispatch_id"]) and isinstance(d["text_sha256"], str)
                                    and _HEX64.match(d["text_sha256"]) is not None
                                    and _int(d["length"], 0, sp.MAX_DISPATCH_LINE)
                                    and isinstance(d["approval"], dict) and set(d["approval"]) == {"kind", "id"}
                                    and d["approval"]["kind"] in ("preview", "automation")
                                    and isinstance(d["approval"]["id"], str)
                                    and _APPROVAL_ID.match(d["approval"]["id"]) is not None),
    "dispatch_written": lambda d: set(d) == {"dispatch_id"} and _uuid(d["dispatch_id"]),
    "turn_lifecycle": lambda d: (set(d) == {"dispatch_id", "state"} and _uuid(d["dispatch_id"])
                                 and d["state"] in ("queued", "started", "completed")),
    "turn_init": lambda d: (set(d) == {"dispatch_id", "permissionMode", "tools", "mcp_servers", "model", "cwd",
                                       "claude_code_version", "apiKeySource"}
                            and _uuid(d["dispatch_id"]) and _str(d["permissionMode"], 64)
                            and isinstance(d["tools"], list) and len(d["tools"]) <= 16
                            and all(_str(x, 64) for x in d["tools"]) and d["mcp_servers"] == []
                            and _str(d["model"], 128) and _str(d["cwd"], 4096)
                            and _str(d["claude_code_version"], 32) and _str(d["apiKeySource"], 64)),
    "dispatch_confirmed": lambda d: set(d) == {"dispatch_id"} and _uuid(d["dispatch_id"]),
    "turn_anomaly": lambda d: (set(d) == {"dispatch_id", "reason", "event_type"} and _uuid(d["dispatch_id"])
                               and d["reason"] in sp.ANOMALY_REASONS and _str(d["event_type"], sp.MAX_EVENT_TYPE)),
    "turn_result": _turn_result,
    "dispatch_failed": lambda d: (set(d) == {"dispatch_id", "reason"} and _uuid(d["dispatch_id"])
                                  and d["reason"] in sp.FAILED_REASONS),
    "protocol_error": lambda d: (set(d) == {"reason", "detail"} and d["reason"] in sp.PROTOCOL_REASONS
                                 and _str(d["detail"], 1024)),
    "exited": lambda d: (set(d) == {"returncode", "signal", "stderr_tail"}
                         and (d["returncode"] is None or _int(d["returncode"], 0, 255))
                         and (d["signal"] is None or _int(d["signal"], 1, 31))
                         and _str(d["stderr_tail"], 64 * 1024)),
}


# --- the state machine (pure) -----------------------------------------------------------

@dataclass
class Turn:
    dispatch_id: str
    status: str = "accepted"       # accepted | written | confirmed | ended | failed
    text_sha256: str = ""
    length: int = 0
    approval: dict = field(default_factory=dict)
    lifecycle: list = field(default_factory=list)
    init: dict | None = None
    anomalies: list = field(default_factory=list)
    result: dict | None = None
    failed: str | None = None
    times: dict = field(default_factory=dict)
    identity_problems: list = field(default_factory=list)   # turn_init vs manifest and acceptance


IDENTITY_KEYS = frozenset({"model_id", "workdir", "executor_claude_version", "executor_model"})


def identity_from(manifest: dict, accepted: dict | None) -> dict | None:
    """The executor identity a session's turns must show (design 5.9, 10):
    the manifest's model and work directory, the accepted version and
    model. None when any part is unknown."""
    if not isinstance(manifest, dict) or not isinstance(accepted, dict):
        return None
    ident = {"model_id": manifest.get("model_id"), "workdir": manifest.get("canonical_workspace"),
             "executor_claude_version": accepted.get("executor_claude_version"),
             "executor_model": accepted.get("executor_model")}
    return ident if all(isinstance(v, str) and v for v in ident.values()) else None


class JournalState:
    """Fed one record at a time, in order. Raises JournalCorrupt on an
    impossible order or a contradiction between records.

    ``identity`` (identity_from): what every turn_init must show. A turn
    whose init differs is invalid and closes the session; without an
    identity no turn can be judged valid (Codex S2a-2 p1 R2 #2)."""

    def __init__(self, consts_for=sp.constants_for, identity: dict | None = None):
        self._consts_for = consts_for
        self.identity = identity if isinstance(identity, dict) and set(identity) == IDENTITY_KEYS else None
        self.seq = 0
        self.last_t: float | None = None
        self.started: dict | None = None
        self.state = "new"
        self.turns: dict[str, Turn] = {}
        self.order: list[str] = []
        self.pending: str | None = None          # accepted, not yet written
        self.current: str | None = None          # written, not yet ended
        self.result_index = -1
        self.cost = 0.0
        self.request_ids: set[str] = set()
        self.message_ids: set[str] = set()
        self.responses = 0
        self.num_turns = 0
        self.closed_reasons: list[str] = []     # why no further dispatch is accepted
        self.exit: dict | None = None
        self.protocol_errors: list[dict] = []

    def _bad(self, why):
        raise JournalCorrupt(why)

    def apply(self, kind: str, data: dict, t: float):
        handler = getattr(self, "_" + kind, None)
        if handler is None:
            self._bad(f"未知的紀錄種類 {kind}")
        if kind != "session_started" and self.started is None:
            self._bad("第一筆不是 session_started")
        handler(data, t)

    def _turn(self, data, *, current=True) -> Turn:
        d = data["dispatch_id"]
        if current and d != self.current:
            self._bad("紀錄不屬於進行中的派工")
        return self.turns[d]

    def _session_started(self, d, t):
        if self.started is not None:
            self._bad("重複的 session_started")
        if self._consts_for(d["cli_version"]) is None:
            self._bad("不支援的 Claude Code 版本")
        self.started = d
        self.state = "idle"

    def _dispatch_accepted(self, d, t):
        if self.state != "idle" or self.pending is not None or self.closed_reasons:
            self._bad("不可能接受派工的狀態")
        if d["dispatch_id"] in self.turns:
            self._bad("重複的 dispatch_id")
        self.turns[d["dispatch_id"]] = Turn(d["dispatch_id"], text_sha256=d["text_sha256"], length=d["length"],
                                            approval=dict(d["approval"]), times={"accepted": t})
        self.order.append(d["dispatch_id"])
        self.pending = d["dispatch_id"]

    def _dispatch_written(self, d, t):
        if self.state != "idle" or d["dispatch_id"] != self.pending:
            self._bad("沒有 prepare 就寫出")
        turn = self.turns[d["dispatch_id"]]
        turn.status, turn.times["written"] = "written", t
        self.pending, self.current, self.state = None, d["dispatch_id"], "sent"

    def _turn_lifecycle(self, d, t):
        turn = self._turn(d)
        expected = {"queued": ([], "sent"), "started": (["queued"], "sent"), "completed": (["queued", "started"], "finishing")}
        before, state = expected[d["state"]]
        if turn.lifecycle != before or self.state != state or (d["state"] == "started" and turn.init is not None):
            self._bad("lifecycle 順序不可能")
        turn.lifecycle.append(d["state"])
        if d["state"] == "completed":
            turn.status, turn.times["ended"] = "ended", t
            self.current, self.state = None, "idle"
            self._close_if_needed(turn)

    def _turn_init(self, d, t):
        turn = self._turn(d)
        if turn.lifecycle != ["queued", "started"] or turn.init is not None or self.state != "sent":
            self._bad("init 順序不可能")
        c = self._consts_for(self.started["cli_version"])
        if (set(d["tools"]) != c.tools or len(d["tools"]) != len(set(d["tools"]))
                or d["permissionMode"] != c.permission_mode or d["claude_code_version"] != c.version
                or d["apiKeySource"] not in c.api_key_sources):
            self._bad("turn_init 不符合常數")
        first = next((self.turns[x].init for x in self.order if self.turns[x].init is not None), None)
        if first is not None and (d["model"] != first["model"] or d["cwd"] != first["cwd"]):
            self._bad("turn_init 的 model 或 cwd 與第一輪不同")
        if self.identity is not None:
            ident = self.identity
            if d["model"] != ident["model_id"] or d["model"] != ident["executor_model"]:
                turn.identity_problems.append("init 的模型不是這次啟動與接受時的模型")
            if d["cwd"] != ident["workdir"]:
                turn.identity_problems.append("init 的工作目錄不是這個任務的工作目錄")
            if (d["claude_code_version"] != ident["executor_claude_version"]
                    or d["claude_code_version"] != self.started["cli_version"]):
                turn.identity_problems.append("init 的 Claude Code 版本不是接受時的版本")
        turn.init = dict(d)

    def _dispatch_confirmed(self, d, t):
        turn = self._turn(d)
        if turn.init is None or self.state != "sent" or turn.status != "written":
            self._bad("沒有 init 就確認送達")
        turn.status, turn.times["confirmed"] = "confirmed", t
        self.state = "running"

    def _turn_anomaly(self, d, t):
        turn = self._turn(d)
        if self.state not in ("sent", "running", "finishing"):
            self._bad("anomaly 不在一輪之內")
        turn.anomalies.append({"reason": d["reason"], "event_type": d["event_type"]})

    def _turn_result(self, d, t):
        turn = self._turn(d)
        if self.state != "running" or turn.status != "confirmed" or turn.result is not None:
            self._bad("result 順序不可能")
        if d["result_index"] != self.result_index + 1:
            self._bad("result_index 不連續")
        cost = finite_real(d["total_cost_usd"])
        if cost < self.cost:
            self._bad("total_cost_usd 變小")
        # Facts must agree with each other (design 2.5), under the same rules
        # the EventTracker applies live (design 2.4 response identity): a
        # request_id maps to one message.id and back, and once the events
        # move on to a new request_id an earlier one never returns (A, B, A
        # is refused here as it is live).
        pairs = {}
        current = None
        seen_order: set[str] = set()
        for e in d["assistant_events"]:
            if pairs.setdefault(e["request_id"], e["message_id"]) != e["message_id"]:
                self._bad("同一個 request_id 對到兩個 message_id")
            if e["request_id"] != current:
                if current is not None and e["request_id"] in seen_order:
                    self._bad("回應順序交錯：切換後又回到先前的 request_id")
                seen_order.add(e["request_id"])
                current = e["request_id"]
        if len(set(pairs.values())) != len(pairs):
            self._bad("同一個 message_id 對到兩個 request_id")
        ids = [c["tool_use_id"] for c in d["tool_calls"]]
        if len(ids) != len(set(ids)):
            self._bad("tool_use_id 重複")
        if set(pairs) & self.request_ids or set(pairs.values()) & self.message_ids:
            self._bad("request_id 或 message_id 在 session 內重複使用")
        self.request_ids |= set(pairs)
        self.message_ids |= set(pairs.values())
        self.responses += len(pairs)
        self.num_turns += d["num_turns"]
        self.result_index, self.cost = d["result_index"], cost
        turn.result = dict(d)
        self.state = "finishing"

    def _dispatch_failed(self, d, t):
        turn = self.turns.get(d["dispatch_id"])
        if turn is None or d["dispatch_id"] not in (self.current, self.pending) or turn.failed is not None:
            self._bad("失敗紀錄不屬於進行中的派工")
        turn.failed, turn.status, turn.times["failed"] = d["reason"], "failed", t
        if d["dispatch_id"] == self.pending:
            self.pending = None
        else:
            self.current = None
        self.state = {"partial_write": "error", "not_confirmed": "error", "no_progress": "uncertain",
                      "turn_timeout": "uncertain", "no_completed": "uncertain", "response_cap": "error",
                      "process_exited": "exited"}[d["reason"]]
        self.closed_reasons.append(f"派工失敗（{d['reason']}）")

    def _protocol_error(self, d, t):
        if self.state == "exited":
            self._bad("程序結束後的協定錯誤")
        self.protocol_errors.append(dict(d))
        for x in (self.current, self.pending):
            if x is not None and self.turns[x].failed is None:
                self.turns[x].status, self.turns[x].failed = "failed", "protocol_error"
        self.current = self.pending = None
        self.state = "error"
        self.closed_reasons.append(f"協定錯誤（{d['reason']}）")

    def _exited(self, d, t):
        if self.exit is not None:
            self._bad("重複的 exited")
        self.exit = dict(d)
        for x in (self.current, self.pending):
            if x is not None and self.turns[x].failed is None:
                self.turns[x].status, self.turns[x].failed = "failed", "process_exited"
        self.current = self.pending = None
        self.state = "exited"
        self.closed_reasons.append("程序已結束")

    def _close_if_needed(self, turn: Turn):
        """After a completed turn: the reasons design 2.4 gives for taking no
        further dispatch on this session (recomputed from facts)."""
        c = self._consts_for(self.started["cli_version"])
        why = closing_reasons(turn, c)
        if why:
            self.closed_reasons.append("；".join(why))

    # the record path, used by readers and by the daemon after each write

    def apply_record(self, rec: dict):
        if not isinstance(rec, dict) or set(rec) != {"v", "seq", "t", "kind", "data", "sha256"}:
            self._bad("紀錄格式不符")
        if rec["v"] != 1 or isinstance(rec["v"], bool):
            self._bad("版本不符")
        if not _int(rec["seq"], self.seq + 1, self.seq + 1):
            self._bad("seq 不連續")
        t = finite_real(rec["t"]) if not isinstance(rec["t"], bool) else None
        if t is None or not EARLIEST <= t <= time.time() + 86400:
            self._bad("時間不合法")
        if self.last_t is not None and t < self.last_t - CLOCK_BACK_S:
            self._bad("時間倒退超過 2 秒")
        body = {k: rec[k] for k in ("v", "seq", "t", "kind", "data")}
        if rec["sha256"] != sp.sha256_hex(sp.canonical(body)):
            self._bad("sha256 不符")
        schema = SCHEMAS.get(rec["kind"])
        if schema is None or not isinstance(rec["data"], dict) or not schema(rec["data"]):
            self._bad(f"{rec['kind']} 的內容不符")
        self.apply(rec["kind"], rec["data"], t)
        self.seq, self.last_t = rec["seq"], t

    def dispatch_count(self) -> int:
        return len(self.turns)


# --- validity (design 2.4 「有效回合」), recomputed from facts --------------------------

def closing_reasons(turn: Turn, consts) -> list[str]:
    why = list(turn.identity_problems)
    if turn.anomalies:
        why.append("出現未知種類或多餘欄位")
    r = turn.result
    if r is not None:
        if any(call["name"] not in consts.tools for call in r["tool_calls"]):
            why.append("呼叫了允許清單以外的工具")
        responses = len({e["request_id"] for e in r["assistant_events"]})
        if r["num_turns"] != responses + consts.num_turns_offset:
            why.append("num_turns 與回應數不一致")
    return why


def turn_validity(js: JournalState, dispatch_id: str, report_problem=None) -> tuple[bool, list[str]]:
    """(valid, reasons) for one dispatch, from the journal's facts only.
    ``report_problem(structured_output, dispatch_id)`` is design 4's schema
    check (executor_report.problem); checks against files come later."""
    turn = js.turns.get(dispatch_id)
    if turn is None:
        return False, ["沒有這則派工"]
    reasons = []
    c = js._consts_for(js.started["cli_version"]) if js.started else None
    if js.identity is None:
        reasons.append("無法核對執行者身分（缺少 manifest 或接受時的資料）")
    elif turn.init is None:
        reasons.append("沒有 init，無法核對執行者身分")
    if turn.failed is not None or turn.status != "ended" or turn.lifecycle != ["queued", "started", "completed"]:
        reasons.append("這一輪沒有完整走完")
    r = turn.result
    if r is None:
        return False, reasons + ["沒有 result"]
    reasons += closing_reasons(turn, c)
    if r["subtype"] != "success" or r["is_error"]:
        reasons.append(f"result 不是成功（{r['subtype']}）")
    events = r["assistant_events"]
    responses = len({e["request_id"] for e in events})
    if responses < 1:
        reasons.append("沒有模型回應")
    for i, e in enumerate(events):
        first = i == 0
        if first and not (e["user_message_uuid"] == dispatch_id and e["user_message_uuids"] == [dispatch_id]):
            reasons.append("第一個 assistant 事件的歸屬不符")
        if not first and not (e["user_message_uuid"] is None and e["user_message_uuids"] is None):
            reasons.append("之後的 assistant 事件帶了派工欄位")
    calls = r["tool_calls"]
    if any(call["result_count"] != 1 for call in calls):
        reasons.append("有工具呼叫沒有結果")
    structured = [call for call in calls if call["name"] == "StructuredOutput"]
    if not structured:
        reasons.append("沒有 StructuredOutput 呼叫")
    else:
        last = structured[-1]
        if last["result_is_error"] is not False or last["result_text_sha256"] != sp.sha256_hex(c.structured_success):
            reasons.append("StructuredOutput 沒有成功")
        so = r["structured_output"]
        if so is None or last["input_sha256"] != sp.sha256_hex(sp.canonical(so)):
            reasons.append("structured_output 與 StructuredOutput 的輸入不同")
        elif report_problem is not None:
            problem = report_problem(so, dispatch_id)
            if problem:
                reasons.append(f"回報格式不符（{problem}）")
    reasons = list(dict.fromkeys(reasons))
    return not reasons, reasons


# --- writing and reading --------------------------------------------------------------------

def encode(seq: int, t: float, kind: str, data: dict) -> bytes:
    body = {"v": 1, "seq": seq, "t": t, "kind": kind, "data": data}
    rec = dict(body, sha256=sp.sha256_hex(sp.canonical(body)))
    return sp.canonical(rec) + b"\n"


class JournalWriter:
    """Appends to a journal this daemon created (O_EXCL), one write() and
    fsync per record, never past MAX_JOURNAL. The JournalState it keeps is
    fed every record it writes, so the live state and a reader's agree."""

    def __init__(self, dir_fd: int, *, identity: dict | None = None, now=time.time):
        self.fd = os.open(JOURNAL_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_NOFOLLOW
                          | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        self.size = 0
        self.state = JournalState(identity=identity)
        self._now = now

    def append(self, kind: str, data: dict) -> dict:
        if self.state.exit is not None and kind != "exited":
            raise JournalCorrupt("程序結束後不再寫入")
        t = self._now()
        if self.state.last_t is not None and t < self.state.last_t:
            t = self.state.last_t                    # never step back in the file
        line = encode(self.state.seq + 1, t, kind, data)
        if len(line) > MAX_LINE:
            raise JournalCorrupt("紀錄超過單行上限")
        if self.size + len(line) > MAX_JOURNAL:
            raise JournalCorrupt("日誌已達上限")
        rec = strictjson.loads(line[:-1], strictjson.SESSION_LOG)
        if not rec.ok:
            raise JournalCorrupt(f"紀錄無法重讀（{rec.problem}）")
        self.state.apply_record(rec.value)          # validate before it reaches the disk
        written = os.write(self.fd, line)
        if written != len(line):
            raise JournalCorrupt("寫入不完整")
        os.fsync(self.fd)
        self.size += len(line)
        return rec.value

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


@dataclass
class ReadResult:
    state: JournalState
    problem: str = ""              # "" when the whole journal is sound
    truncated_tail: bool = False   # the last line is incomplete


def read(dir_fd: int, identity: dict | None = None) -> ReadResult:
    """Rebuild a session from its journal. Any problem is fail closed: the
    caller shows the session and takes no action on it. Without
    ``identity`` the counts are usable but no turn is judged valid."""
    js = JournalState(identity=identity)
    try:
        fd, st = strictjson.open_owned(JOURNAL_NAME, dir_fd=dir_fd, max_bytes=MAX_JOURNAL)
    except strictjson.ReadRefused as exc:
        return ReadResult(js, f"無法讀取日誌（{exc}）")
    try:
        for parsed in strictjson.iter_json_lines(fd, strictjson.SESSION_LOG):
            if not parsed.ok:
                if "換行" in parsed.problem:
                    return ReadResult(js, "日誌末筆不完整", truncated_tail=True)
                return ReadResult(js, f"日誌損壞（{parsed.problem}）")
            try:
                js.apply_record(parsed.value)
            except JournalCorrupt as exc:
                return ReadResult(js, f"日誌損壞（{exc}）")
            except Exception as exc:
                return ReadResult(js, f"日誌損壞（{type(exc).__name__}）")
    finally:
        os.close(fd)
    if js.started is None:
        return ReadResult(js, "日誌是空的")
    return ReadResult(js)
