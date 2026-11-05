"""Claude Code's stream-json protocol when a person chats with a role card (P36). Pure: no I/O, no clock.

What VBear writes to the CLI's stdin (one JSON object per line): the ``initialize`` control request first, then each
user message, and an answer (``control_response``) to every request the CLI makes. What it reads back goes through a
``ChatTracker``, which answers with facts for the chat's record and for the session to act on.

The facts below are the ones P36-0 recorded with the real 2.1.318 (runs/20261105-p36, tests/chat_fixtures.py):

  * Permission requests reach VBear only with ``--permission-prompts host --permission-prompt-tool stdio`` and the
    ``initialize`` request sent before the first message. The answer to ``initialize`` also carries the account,
    the commands and the models: only ``claude_code_version`` and ``current_permission_mode`` are ever read from it.
  * A request is ``control_request`` / ``can_use_tool`` (tool_name, input, tool_use_id); the answer allows with an
    ``updatedInput`` (what the person changed is what runs) or denies with a message. ``permission_suggestions``
    (such as switching to acceptEdits) are never taken.
  * ``system/init`` comes again with every turn and names the work folder, the tools, the mode and the extra folders
    of the account's own settings; VBear's settings set those to none, and a chat whose init still lists any is
    stopped (only how many is said, never which).
  * ``result.total_cost_usd`` counts the whole session, a resumed process included: a turn's cost is this total
    minus the last one.

The chat is kept safe by the sandbox and the permission cards, not by how strict this reader is: an event of an
unknown kind is recorded as an anomaly (its top-level field names, never a value) and not shown; an unknown kind of
control request is answered with a refusal. What does stop a chat (a ``violation``) is evidence that VBear's
settings are not in force, or that a tool ran that VBear did not allow.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal

from ..numbers import finite_real
from . import stream_protocol as sp

UUID_RE = sp.UUID_RE
MAX_TEXT_BYTES = 32 * 1024            # one user message (UTF-8)
MAX_STDIN_LINE = 1 << 20              # one line VBear writes: a Write's content can be long
MAX_EVENT_TYPE = 64
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}\Z")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}\Z")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,63}\Z")

# The --tools list, in the order the argv names them.
TOOLS = ("Bash", "Read", "Edit", "Write", "Grep", "Glob")
READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
EDITABLE = {"Bash": "command", "Write": "content", "Edit": "new_string"}     # what a person may change first
# Inside the work folder, Claude Code's own project settings: neither Write nor Edit may go there.
PROTECTED = (".claude",)


@dataclass(frozen=True)
class ChatConstants:
    version: str
    tools: frozenset                   # the --tools list, which system/init must report exactly
    permission_mode: str
    known: frozenset                   # the event kinds (kind_of) this version prints
    pinned_env: dict                   # the --settings env block that pins the endpoint (as for the stream executor)
    cost_cumulative: bool              # result.total_cost_usd counts the whole session, resumed processes included


VERSIONS = {
    "2.1.318": ChatConstants(
        version="2.1.318",
        tools=frozenset(TOOLS),
        permission_mode="default",
        known=frozenset({"control_response", "control_request", "system/init", "system/status",
                         "system/thinking_tokens", "system/permission_denied", "stream_event", "assistant", "user",
                         "rate_limit_event", "result"}),
        pinned_env=dict(sp._PINNED_ENV),
        cost_cumulative=True,
    ),
}
STREAM_EVENTS = frozenset({"message_start", "content_block_start", "content_block_delta", "content_block_stop",
                           "message_delta", "message_stop"})
DELTAS = frozenset({"text_delta", "thinking_delta", "signature_delta", "input_json_delta"})


def constants_for(version) -> ChatConstants | None:
    return VERSIONS.get(version) if isinstance(version, str) else None


def kind_of(ev) -> str | None:
    if not isinstance(ev, dict) or not isinstance(ev.get("type"), str):
        return None
    if ev["type"] == "system":
        sub = ev.get("subtype")
        return f"system/{sub}" if isinstance(sub, str) else "system/?"
    return ev["type"]


# ---- what VBear writes ------------------------------------------------------------------------------------------

def _line(obj) -> bytes:
    """One stdin line, newline included; ValueError when it cannot be encoded (a lone surrogate) or would pass
    MAX_STDIN_LINE. Never cut."""
    try:
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise ValueError("內容無法編碼成一行 JSON") from exc
    if len(data) > MAX_STDIN_LINE:
        raise ValueError(f"一行超過 {MAX_STDIN_LINE} bytes")
    return data


def initialize_line(request_id: str) -> bytes:
    return _line({"type": "control_request", "request_id": request_id, "request": {"subtype": "initialize"}})


def user_line(text: str, session_id: str) -> bytes:
    return _line({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                  "session_id": session_id, "parent_tool_use_id": None})


def allow_line(request_id: str, updated_input: dict) -> bytes:
    return _line({"type": "control_response", "response": {
        "subtype": "success", "request_id": request_id,
        "response": {"behavior": "allow", "updatedInput": updated_input}}})


def deny_line(request_id: str, message: str) -> bytes:
    return _line({"type": "control_response", "response": {
        "subtype": "success", "request_id": request_id, "response": {"behavior": "deny", "message": message}}})


def error_line(request_id: str, message: str) -> bytes:
    """The answer to a control request VBear does not take (any subtype but can_use_tool)."""
    return _line({"type": "control_response", "response": {"subtype": "error", "request_id": request_id,
                                                           "error": message}})


# ---- which tool calls VBear answers itself ---------------------------------------------------------------------

@dataclass(frozen=True)
class Judgement:
    action: str                        # "allow": VBear says yes itself; "ask": a card; "deny": VBear says no itself
    reason: str
    editable: str | None = None        # the input field a person may change before allowing


def _resolve(path, work: str) -> str | None:
    """Where a tool's path points: relative to the work folder (the CLI's own folder) when not absolute, with every
    link that exists followed. None when it is not a usable path."""
    if not isinstance(path, str) or not path or "\0" in path or len(path) > 4096:
        return None
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(work, path))


def _inside(path: str | None, work: str) -> bool:
    return isinstance(path, str) and (path == work or path.startswith(work.rstrip(os.sep) + os.sep))


def _pattern_escapes(pattern) -> bool:
    """A Glob/Grep pattern that could reach outside the folder it starts from: absolute, from the home folder, or
    with any ``..`` in it (a brace expansion can make one out of parts)."""
    return not isinstance(pattern, str) or pattern.startswith(("/", "~")) or ".." in pattern


def judge(tool, tool_input, workdir: str) -> Judgement:
    """What VBear does with a permission request (P36 design): Bash, Edit and Write always ask, Edit and Write only
    inside the role card's work folder (elsewhere, or into its ``.claude``, VBear refuses with no way to allow);
    Read, Grep and Glob are allowed by VBear inside the work folder and ask anywhere else; any other tool is
    refused."""
    if not isinstance(tool_input, dict):
        return Judgement("deny", "工具的輸入格式不對")
    work = os.path.realpath(workdir)
    if tool == "Bash":
        if not isinstance(tool_input.get("command"), str):
            return Judgement("deny", "Bash 沒有給要執行的指令")
        return Judgement("ask", "每個指令都要你允許才會執行", EDITABLE["Bash"])
    if tool in ("Write", "Edit"):
        where = _resolve(tool_input.get("file_path"), work)
        if where is None:
            return Judgement("deny", f"{tool} 沒有給檔案路徑")
        if not _inside(where, work) or where == work:
            return Judgement("deny", "只能寫員工自己的工作資料夾裡的檔案，這個路徑在資料夾以外")
        first = os.path.relpath(where, work).split(os.sep)[0]
        if first.casefold() in PROTECTED:
            return Judgement("deny", f"{first} 是 Claude Code 自己的設定資料夾，聊天裡不能寫")
        return Judgement("ask", "寫入員工工作資料夾裡的檔案，要你允許", EDITABLE[tool])
    if tool in READ_TOOLS:
        if tool == "Read":
            paths, patterns = [tool_input.get("file_path")], []
        else:
            paths = [tool_input.get("path") if tool_input.get("path") is not None else work]
            patterns = ([tool_input.get("pattern")] if tool == "Glob" else
                        [tool_input["glob"]] if tool_input.get("glob") is not None else [])
        if all(_inside(_resolve(p, work), work) for p in paths) and not any(_pattern_escapes(p) for p in patterns):
            return Judgement("allow", "在員工自己的工作資料夾裡讀取")
        return Judgement("ask", "要讀員工工作資料夾以外的地方，要你允許")
    return Judgement("deny", "VBear 的聊天不提供這個工具")


def summary(tool, tool_input, limit: int = 2000) -> str:
    """One line for the record: what the call does (a command, a path, a pattern), at most ``limit`` characters."""
    if not isinstance(tool_input, dict):
        return ""
    if tool == "Bash":
        text = tool_input.get("command")
    elif tool in ("Read", "Write", "Edit"):
        text = tool_input.get("file_path")
    elif tool in ("Grep", "Glob"):
        text = " ".join(str(tool_input[k]) for k in ("pattern", "path", "glob") if tool_input.get(k) is not None)
    else:
        text = ""
    return text[:limit] if isinstance(text, str) else ""


def turn_cost(total, last, cap: Decimal) -> tuple[Decimal, bool]:
    """(cost, reported) of a turn from its result's cumulative ``total_cost_usd`` and the last one this session
    reported (None before any): their difference; the turn's cap when there is no usable total or it went back."""
    t = finite_real(total)
    if t is None or t < 0:
        return cap, False
    base = 0.0 if last is None else last
    if t < base:
        return cap, False
    return Decimal(str(t)) - Decimal(str(base)), True


# ---- reading what the CLI prints -----------------------------------------------------------------------------------

def _id(value) -> str:
    return value if isinstance(value, str) and _ID_RE.match(value) else "?"


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x["text"] for x in content
                         if isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str))
    return ""


def _anomaly(label: str, fields) -> tuple[str, dict]:
    return ("anomaly", {"event_type": label[:MAX_EVENT_TYPE], "fields": sp.anomaly_fields(fields)})


class ChatTracker:
    """One chat process. ``on_event`` turns one parsed stdout line into facts, (kind, data) pairs:

      initialized       {claude_code_version, permission_mode}      the answer to initialize was this version's
      session_ready     {claude_code_version, permission_mode, model}   the first system/init, as expected
      permission_request {request_id, tool, input, tool_use_id, description}
      unknown_control   {request_id, subtype}                        to be answered with error_line
      delta             {text}                                       a piece of the reply (shown, not kept)
      reply             {message_id, text}                           a whole text block of the reply
      tool_call         {tool_use_id, tool, input}
      tool_result       {tool_use_id, tool, is_error, text, source}
      denied            {tool, tool_use_id}                          Claude Code refused a call by itself
      result            {total_cost_usd, subtype, is_error, num_turns, denials}
      anomaly           {event_type, fields}
      violation         {message}                                    the session must stop; nothing more is read

    The session tells it which tool calls VBear allowed (``approve``) or refused (``refuse``)."""

    def __init__(self, consts: ChatConstants, *, session_id: str, workdir: str, init_request_id: str):
        self.c = consts
        self.session_id = session_id
        self.workdir = os.path.realpath(workdir)
        self.init_id = init_request_id
        self.initialized = False
        self.ready = False
        self.stopped = False
        self.calls: dict[str, dict] = {}        # tool_use_id -> {"tool", "input"} of this process
        self.approved: set[str] = set()
        self.refused: set[str] = set()          # by VBear, or by Claude Code itself (system/permission_denied)

    def approve(self, tool_use_id) -> None:
        if isinstance(tool_use_id, str):
            self.approved.add(tool_use_id)

    def refuse(self, tool_use_id) -> None:
        if isinstance(tool_use_id, str):
            self.refused.add(tool_use_id)

    def on_event(self, ev) -> list[tuple[str, dict]]:
        if self.stopped:
            return []
        try:
            out = self._on_event(ev)
        except Exception:
            # Strict JSON can still hold shapes no handler expects: an anomaly, never an exception out of the loop.
            out = [_anomaly(kind_of(ev) or "?", ev if isinstance(ev, dict) else ())]
        if any(k == "violation" for k, _ in out):
            self.stopped = True
        return out

    def _violation(self, message: str) -> list[tuple[str, dict]]:
        return [("violation", {"message": message})]

    def _on_event(self, ev) -> list[tuple[str, dict]]:
        kind = kind_of(ev)
        if kind is None or kind not in self.c.known:
            return [_anomaly(kind or "?", ev if isinstance(ev, dict) else ())]
        if "session_id" in ev and ev["session_id"] != self.session_id:
            if kind == "system/init":
                return self._violation("Claude Code 開的不是 VBear 指定的對話")
            return [_anomaly(kind, ["session_id"])]
        handler = getattr(self, "_on_" + kind.replace("/", "_"))
        return handler(ev)

    def _on_control_response(self, ev):
        resp = ev.get("response")
        if not isinstance(resp, dict) or resp.get("request_id") != self.init_id or self.initialized:
            return [_anomaly("control_response", resp if isinstance(resp, dict) else ev)]
        if resp.get("subtype") != "success" or not isinstance(resp.get("response"), dict):
            return self._violation("Claude Code 沒有接受初始化（initialize）")
        body = resp["response"]
        version, mode = body.get("claude_code_version"), body.get("current_permission_mode")
        if version != self.c.version:
            return self._violation(f"初始化回覆的 Claude Code 版本不是 {self.c.version}")
        if mode != self.c.permission_mode:
            return self._violation(f"初始化回覆的權限模式不是 {self.c.permission_mode}")
        self.initialized = True
        return [("initialized", {"claude_code_version": version, "permission_mode": mode})]

    def _on_control_request(self, ev):
        rid, req = ev.get("request_id"), ev.get("request")
        if not (isinstance(rid, str) and REQUEST_ID_RE.match(rid)):
            return [_anomaly("control_request", ev)]
        sub = req.get("subtype") if isinstance(req, dict) else None
        if sub == "can_use_tool":
            tool, inp, tid = req.get("tool_name"), req.get("input"), req.get("tool_use_id")
            if isinstance(tool, str) and isinstance(inp, dict) and (tid is None or isinstance(tid, str)):
                desc = req.get("description")
                return [("permission_request", {"request_id": rid, "tool": tool, "input": inp, "tool_use_id": tid,
                                                "description": desc if isinstance(desc, str) else ""})]
        return [("unknown_control", {"request_id": rid, "subtype": sp.safe_name(sub)})]

    def _on_system_init(self, ev):
        problems = []
        if ev.get("claude_code_version") != self.c.version:
            problems.append("版本")
        if ev.get("permissionMode") != self.c.permission_mode:
            problems.append("權限模式")
        tools = ev.get("tools")
        if not (isinstance(tools, list) and all(isinstance(x, str) for x in tools) and len(tools) == len(set(tools))
                and set(tools) == self.c.tools):
            problems.append("工具")
        cwd = ev.get("cwd")
        if not (isinstance(cwd, str) and (cwd == self.workdir or os.path.realpath(cwd) == self.workdir)):
            problems.append("工作資料夾")
        if "mcp_servers" in ev and ev["mcp_servers"] != []:
            problems.append("MCP 伺服器")
        extra = ev.get("additional_directories")
        if extra is not None and extra != []:
            count = len(extra) if isinstance(extra, list) else "?"
            problems.append(f"額外資料夾（{count} 個，聊天只能有員工自己的工作資料夾）")
        if problems:
            return self._violation("Claude Code 的啟動資訊與 VBear 的設定不符：" + "、".join(problems))
        if self.ready:
            return []
        self.ready = True
        model = ev.get("model")
        return [("session_ready", {"claude_code_version": self.c.version, "permission_mode": self.c.permission_mode,
                                   "model": model if isinstance(model, str) and _MODEL_RE.match(model) else "?"})]

    def _on_system_status(self, ev):
        return []

    def _on_system_thinking_tokens(self, ev):
        return []

    def _on_rate_limit_event(self, ev):
        return []

    def _on_system_permission_denied(self, ev):
        tid = ev.get("tool_use_id")
        self.refuse(tid)
        return [("denied", {"tool": sp.safe_name(ev.get("tool_name")), "tool_use_id": _id(tid)})]

    def _on_stream_event(self, ev):
        inner = ev.get("event")
        etype = inner.get("type") if isinstance(inner, dict) else None
        if etype not in STREAM_EVENTS:
            return [_anomaly(f"stream_event/{sp.safe_name(etype)}", inner if isinstance(inner, dict) else ev)]
        if etype != "content_block_delta":
            return []
        delta = inner.get("delta")
        dtype = delta.get("type") if isinstance(delta, dict) else None
        if dtype not in DELTAS:
            return [_anomaly(f"stream_event/delta/{sp.safe_name(dtype)}", delta if isinstance(delta, dict) else ())]
        if dtype == "text_delta" and isinstance(delta.get("text"), str):
            return [("delta", {"text": delta["text"]})]
        return []                                   # thinking is never shown; signatures and tool input are not text

    def _on_assistant(self, ev):
        msg = ev.get("message")
        if not (isinstance(msg, dict) and isinstance(msg.get("content"), list)):
            return [_anomaly("assistant", ev)]
        mid = _id(msg.get("id"))
        out = []
        for item in msg["content"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                out.append(("reply", {"message_id": mid, "text": item["text"]}))
            elif item.get("type") == "tool_use":
                tid, name, inp = item.get("id"), item.get("name"), item.get("input")
                if not (isinstance(tid, str) and isinstance(name, str) and isinstance(inp, dict)):
                    out.append(_anomaly("assistant/tool_use", item))
                    continue
                if tid in self.calls:
                    continue
                self.calls[tid] = {"tool": name, "input": inp}
                out.append(("tool_call", {"tool_use_id": _id(tid), "tool": sp.safe_name(name), "input": inp}))
        return out

    def _on_user(self, ev):
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return []                               # a text message: what VBear sent; nothing to read
        meta = {}
        for m in ev.get("tool_result_meta") or ():
            if isinstance(m, dict) and isinstance(m.get("id"), str) and isinstance(m.get("permission_decision"), dict):
                meta[m["id"]] = m["permission_decision"]
        out = []
        for item in content:
            if not (isinstance(item, dict) and item.get("type") == "tool_result"):
                continue
            tid = item.get("tool_use_id")
            if not isinstance(tid, str):
                out.append(_anomaly("user/tool_result", item))
                continue
            decision = meta.get(tid, {})
            call = self.calls.get(tid)
            is_error = item.get("is_error") is True
            out.append(("tool_result", {"tool_use_id": _id(tid), "tool": sp.safe_name(call["tool"]) if call else "?",
                                        "is_error": is_error, "text": _result_text(item.get("content")),
                                        "source": sp.safe_name(decision.get("source"))}))
            why = self._unapproved(tid, call, is_error, decision.get("decision"))
            if why:
                out += self._violation(why)
                break
        return out

    def _unapproved(self, tid: str, call, is_error: bool, decision) -> str | None:
        """Why a tool result shows a call that ran without VBear's yes, or None. A result that is an error and that
        Claude Code itself says was not accepted did not run; without that statement an error may have run too."""
        if tid in self.approved or tid in self.refused:
            return None
        if is_error and decision is not None and decision != "accept":
            return None
        if call is None:
            return "Claude Code 回報了一個 VBear 沒看到呼叫的工具結果"
        if call["tool"] in READ_TOOLS and judge(call["tool"], call["input"], self.workdir).action == "allow":
            return None                             # a read inside the work folder, which VBear allows too
        return f"Claude Code 沒有經過 VBear 的允許就執行了 {sp.safe_name(call['tool'])}"

    def _on_result(self, ev):
        cost = finite_real(ev.get("total_cost_usd"))
        turns = ev.get("num_turns")
        denials = ev.get("permission_denials")
        return [("result", {"total_cost_usd": cost if cost is not None and cost >= 0 else None,
                            "subtype": sp.safe_name(ev.get("subtype")), "is_error": ev.get("is_error") is True,
                            "num_turns": turns if isinstance(turns, int) and not isinstance(turns, bool)
                            and 0 <= turns <= sp.MAX_NUM_TURNS else None,
                            "denials": len(denials) if isinstance(denials, list) else 0})]
