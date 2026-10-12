"""Claude Code stream-json protocol for the stream executor (design 2.2-2.4,
3.1, 3.3). Pure: no I/O, no clock of its own (times are passed in).

The daemon feeds every stdout event of a stream session to an EventTracker.
The tracker checks the event against the per-version constants (kinds,
required and allowed fields, init values), the attribution equalities and
the order of one dispatch, counts model responses, and answers with journal
facts to append (design 2.5 kinds) and, when the session must stop, why.
It never decides whether a turn is valid: that is recomputed from the
recorded facts by stream_journal.turn_validity, the same way live and on
recovery.

The constants below are written by a developer from observed behaviour
(2.1.292, planner's measurements 2026-10-08) and reviewed; the stream probe
(boundary_check --mode stream) only confirms them, it never learns them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, replace

from ..numbers import finite_real

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
MAX_DISPATCH_LINE = 64 * 1024
MAX_RESULT_TEXT = 256 * 1024
MAX_EVENT_TYPE = 64
# design 2.4: bounds on integers from outside
MAX_ESTIMATED_TOKENS = 10 ** 8
MAX_NUM_TURNS = 10 ** 4
MAX_RESULT_INDEX = 10 ** 6
MAX_VCS_FIELD = 512                         # system/vcs_state_changed: kind, branch, cwd


@dataclass(frozen=True)
class StreamConstants:
    version: str
    tools: frozenset
    permission_mode: str
    api_key_sources: frozenset
    lifecycle_states: tuple
    allowed: dict                      # kind -> frozenset of top-level fields
    structured_success: str
    num_turns_offset: int              # num_turns == responses + offset (with --json-schema)
    pinned_env: dict                   # the --settings env block that pins the endpoint


_PINNED_ENV = {
    # design 2.1: the endpoint and provider are fixed by VBear's --settings,
    # which ranks above user and project settings. Every provider switch the
    # vendor documents is turned off.
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "CLAUDE_CODE_USE_BEDROCK": "0",
    "CLAUDE_CODE_USE_VERTEX": "0",
    "CLAUDE_CODE_USE_FOUNDRY": "0",
    "CLAUDE_CODE_USE_MANTLE": "0",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS": "0",
}

VERSIONS = {
    "2.1.292": StreamConstants(
        version="2.1.292",
        tools=frozenset({"Bash", "StructuredOutput"}),
        permission_mode="acceptEdits",
        api_key_sources=frozenset({"none"}),
        lifecycle_states=("queued", "started", "completed"),
        allowed={
            "command_lifecycle": frozenset({"command_uuid", "session_id", "state", "type", "uuid"}),
            "system/init": frozenset({
                "agents", "analytics_disabled", "apiKeySource", "capabilities", "claude_code_version", "cwd",
                "fast_mode_disabled_reason", "fast_mode_state", "mcp_servers", "messaging_socket_path", "model",
                "output_style", "per_turn_effort_active", "permissionMode", "plugins", "product_feedback_disabled",
                "session_id", "skills", "slash_commands", "subtype", "terminal_slash_commands", "tools", "type",
                "uuid", "view_mode"}),
            "system/thinking_tokens": frozenset({"estimated_tokens", "estimated_tokens_delta", "session_id",
                                                 "subtype", "type", "user_message_uuid", "uuid"}),
            "user/replay": frozenset({"isReplay", "message", "parent_tool_use_id", "session_id", "timestamp",
                                      "type", "uuid"}),
            # tool_result_meta: seen on a Bash result by the stream probe
            # (2026-10-08), absent from the earlier measurement; not read.
            "user/tool_result": frozenset({"message", "parent_tool_use_id", "session_id", "timestamp",
                                           "tool_result_meta", "tool_use_result", "type", "uuid"}),
            "assistant": frozenset({"message", "parent_tool_use_id", "request_id", "session_id",
                                    "thinking_duration_ms", "timestamp", "type", "user_message_uuid",
                                    "user_message_uuids", "uuid", "wire_tool_inputs"}),
            "rate_limit_event": frozenset({"rate_limit_info", "session_id", "type", "uuid"}),
            "result": frozenset({
                "api_error_status", "duration_api_ms", "duration_ms", "errors", "fast_mode_disabled_reason",
                "fast_mode_state", "first_content_frame_ms", "first_request_input_tokens", "is_error",
                "modelUsage", "num_turns", "permission_denials", "queued_turn_count", "request_sent_wall_ms",
                "result", "result_index", "safety_stops", "session_id", "stop_reason", "structured_output",
                "subagent_stats", "subtype", "terminal_reason", "time_to_request_ms", "total_cost_usd", "ttft_ms",
                "ttft_stream_ms", "type", "usage", "user_message_uuid", "user_message_uuids", "uuid"}),
        },
        structured_success="Structured output provided successfully",
        num_turns_offset=1,
        pinned_env=dict(_PINNED_ENV),
    ),
}

# 2.1.296: the 2.1.292 entry plus what the stream probe observed (docs/evidence/claude-code-2.1.296-stream.md, a
# passing run 2026-10-12). One difference: assistant events carry ``thinking_display`` (a new top-level field; not
# read).
#
# And a new event kind (S3 real end-to-end, run 1, 2026-10-12; raw capture by tools/stream_capture.py): a ``system``
# event with subtype ``vcs_state_changed`` comes between a tool's call and its result when the tool changed the
# work directory's repository state (seen after a ``git commit``). Fields: type, subtype, kind, branch, cwd (all
# strings; cwd is the work directory or below it), uuid, session_id. 2.1.292 has no such entry, so there it stays an unknown type and invalidates the turn.
VERSIONS["2.1.296"] = replace(
    VERSIONS["2.1.292"], version="2.1.296",
    allowed={**VERSIONS["2.1.292"].allowed,
             "assistant": VERSIONS["2.1.292"].allowed["assistant"] | {"thinking_display"},
             "system/vcs_state_changed": frozenset({"branch", "cwd", "kind", "session_id", "subtype", "type",
                                                    "uuid"})})

KINDS = ("command_lifecycle", "system/init", "system/thinking_tokens", "system/vcs_state_changed", "user/replay",
         "user/tool_result",
         "assistant", "rate_limit_event", "result")


def constants_for(version) -> StreamConstants | None:
    return VERSIONS.get(version) if isinstance(version, str) else None


# --- helpers shared with the journal ------------------------------------------

def canonical(value) -> bytes:
    """The standard form used for every hash (sort_keys, no spaces)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# --- dispatch text (design 3.3) and line (3.1) --------------------------------

_BIDI = frozenset(chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C))


def sanitize(text) -> str:
    """Rewrite C0/C1/DEL, bidi controls and other format characters as a
    visible ``\\uXXXX``; keep printable characters, ``\\n`` and ``\\t``. A
    lone surrogate is refused (ValueError), never replaced; no
    normalisation."""
    if not isinstance(text, str):
        raise ValueError("文字必須是字串")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("文字含有不合法的 Unicode（孤立 surrogate）") from exc
    out = []
    for ch in text:
        if ch in "\n\t":
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat == "Cc" or ch in _BIDI or cat == "Cf":
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)
    return "".join(out)


def dispatch_line(text: str, claude_session_id: str, dispatch_id: str) -> bytes:
    """The one stdin line for a dispatch, newline included; ValueError when
    it would pass 64 KiB (never truncated)."""
    if not (isinstance(dispatch_id, str) and UUID_RE.match(dispatch_id)):
        raise ValueError("dispatch_id 必須是小寫 UUID")
    if not (isinstance(claude_session_id, str) and UUID_RE.match(claude_session_id)):
        raise ValueError("claude_session_id 格式不符")
    obj = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]},
           "parent_tool_use_id": None, "session_id": claude_session_id, "uuid": dispatch_id}
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(line) > MAX_DISPATCH_LINE:
        raise ValueError(f"派工組成的一行超過 {MAX_DISPATCH_LINE} bytes")
    return line


# --- event checks --------------------------------------------------------------

def kind_of(event: dict) -> str | None:
    t = event.get("type")
    if t == "system":
        sub = event.get("subtype")
        return f"system/{sub}" if sub in ("init", "thinking_tokens", "vcs_state_changed") else None
    if t == "user":
        return "user/replay" if "isReplay" in event else "user/tool_result"
    if t in ("command_lifecycle", "assistant", "rate_limit_event", "result"):
        return t
    return None


def _is_int(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


class ProtocolError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail[:1024]


# protocol_error reasons (journal enum)
PROTOCOL_REASONS = ("session_mismatch", "bad_uuid", "duplicate_uuid", "missing_field", "init_mismatch",
                    "out_of_order", "attribution", "response_ids", "tool_result_unknown", "duplicate_tool_use",
                    "event_while_idle", "event_while_writing", "bad_json", "stdout_limit", "event_limit",
                    "turn_event_limit", "stderr_limit", "journal_full", "dispatch_reuse", "dispatch_file",
                    "pipe_read_error",       # review round 6 #3: a read error is not an EOF
                    "spawn_failed",          # review round 7: the session could not start (a v29.8 failure)
                    "internal_error")        # an unexpected exception while managing the session
FAILED_REASONS = ("partial_write", "not_confirmed", "no_progress", "turn_timeout", "no_completed",
                  "response_cap", "process_exited")
ANOMALY_REASONS = ("unknown_type", "extra_fields")


@dataclass
class TurnFacts:
    """What a turn_result records (design 2.5)."""
    dispatch_id: str
    text: str
    assistant_events: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    responses: int = 0
    events: int = 0


def _validate_utf8_tree(value) -> None:
    """Reject escaped lone surrogates anywhere in an event, including keys."""
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_utf8_tree(key)
            _validate_utf8_tree(item)
    elif isinstance(value, list):
        for item in value:
            _validate_utf8_tree(item)


def _within(path: str, root: str) -> bool:
    """``path`` is ``root`` or below it, by whole path components, both made absolute and normal first (no file
    system is read: a link is not followed, a ``..`` is resolved textually, so ``/work/../etc`` is ``/etc``).
    ``/work2`` is not below ``/work``."""
    if not (isinstance(path, str) and isinstance(root, str) and os.path.isabs(path) and os.path.isabs(root)):
        return False
    path, root = os.path.normpath(path), os.path.normpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


class EventTracker:
    """Per stream session. ``on_event`` returns the journal facts the event
    produces, as (kind, data) pairs, and raises ProtocolError for a protocol
    error (the daemon records it and stops the session from dispatching)."""

    def __init__(self, consts: StreamConstants, claude_session_id: str, workdir: str, model: str | None,
                 executor_version: str | None = None):
        self.c = consts
        self.session_id = claude_session_id
        self.workdir = workdir
        self.expected_model = model                 # the manifest's model, which the acceptance names
        self.executor_version = executor_version    # the accepted Claude Code version
        self.uuids: set[str] = set()
        self.request_ids: set[str] = set()
        self.message_ids: set[str] = set()
        self.result_index = -1
        self.last_cost = 0.0
        self.first_model: str | None = None
        self.phase = "idle"            # idle | sent:queued | sent:started | sent:init | running | finishing
        self.turn: TurnFacts | None = None
        self.current_response: tuple[str, str] | None = None
        self.total_responses = 0

    # the daemon tells the tracker about its own steps

    def begin(self, dispatch_id: str, text: str):
        if self.phase != "idle":
            raise ProtocolError("out_of_order", "begin while a turn is in progress")
        self.turn = TurnFacts(dispatch_id, text)
        self.phase = "sent:queued"
        self.current_response = None

    def reset_after_failure(self):
        self.phase = "closed"

    # events

    def on_event(self, ev) -> list[tuple[str, dict]]:
        if not isinstance(ev, dict):
            raise ProtocolError("bad_json", "event is not an object")
        try:
            _validate_utf8_tree(ev)
        except Exception as exc:
            raise ProtocolError("bad_json", "event contains invalid Unicode") from exc
        if self.phase == "idle":
            raise ProtocolError("event_while_idle", str(ev.get("type"))[:64])
        if self.phase == "closed":
            return []
        if ev.get("session_id") != self.session_id:
            raise ProtocolError("session_mismatch")
        uid = ev.get("uuid")
        if not (isinstance(uid, str) and UUID_RE.match(uid)):
            raise ProtocolError("bad_uuid")
        if uid in self.uuids:
            raise ProtocolError("duplicate_uuid")
        self.uuids.add(uid)
        t = self.turn
        t.events += 1
        kind = kind_of(ev)
        if kind is not None and kind not in self.c.allowed:     # a kind this version's constants do not know
            kind = None
        out: list[tuple[str, dict]] = []
        if kind is None:
            label = f"{ev.get('type')}/{ev.get('subtype')}" if ev.get("type") == "system" else str(ev.get("type"))
            return [("turn_anomaly", {"dispatch_id": t.dispatch_id, "reason": "unknown_type",
                                      "event_type": label[:MAX_EVENT_TYPE]})]
        try:
            extra = set(ev) - self.c.allowed[kind]
            if extra:
                out.append(("turn_anomaly", {"dispatch_id": t.dispatch_id, "reason": "extra_fields",
                                             "event_type": kind[:MAX_EVENT_TYPE]}))
            handler = getattr(self, "_on_" + kind.replace("/", "_"))
            out += handler(ev, t)
        except ProtocolError:
            raise
        except Exception as exc:
            # Strict JSON can still decode escaped lone surrogates. Any
            # schema/hash/encoding exception while interpreting such input
            # is a protocol failure, never an exception out of the daemon
            # selector loop (design 2.3).
            raise ProtocolError("bad_json", f"event could not be validated ({type(exc).__name__})") from exc
        return out

    def _need(self, ok: bool, what: str):
        if not ok:
            raise ProtocolError("missing_field", what)

    def _on_command_lifecycle(self, ev, t):
        self._need(isinstance(ev.get("command_uuid"), str) and UUID_RE.match(ev["command_uuid"]) is not None,
                   "command_uuid")
        state = ev.get("state")
        self._need(state in self.c.lifecycle_states, "state")
        if ev["command_uuid"] != t.dispatch_id:
            raise ProtocolError("attribution", "command_uuid")
        order = {"queued": "sent:queued", "started": "sent:started", "completed": "finishing"}
        if self.phase != order[state]:
            raise ProtocolError("out_of_order", f"lifecycle {state} in {self.phase}")
        self.phase = {"queued": "sent:started", "started": "sent:init", "completed": "idle"}[state]
        if state == "completed":
            self.turn = None
        return [("turn_lifecycle", {"dispatch_id": t.dispatch_id, "state": state})]

    def _on_system_init(self, ev, t):
        if self.phase != "sent:init":
            raise ProtocolError("out_of_order", f"init in {self.phase}")
        tools, mcp = ev.get("tools"), ev.get("mcp_servers")
        model, cwd = ev.get("model"), ev.get("cwd")
        self._need(isinstance(tools, list) and all(isinstance(x, str) for x in tools), "tools")
        self._need(isinstance(mcp, list), "mcp_servers")
        for name in ("permissionMode", "claude_code_version", "apiKeySource", "model", "cwd"):
            self._need(isinstance(ev.get(name), str), name)
        if (len(tools) != len(set(tools)) or set(tools) != self.c.tools or mcp != []
                or ev["permissionMode"] != self.c.permission_mode
                or ev["claude_code_version"] != self.c.version
                or ev["apiKeySource"] not in self.c.api_key_sources or cwd != self.workdir):
            raise ProtocolError("init_mismatch")
        if self.first_model is None:
            self.first_model = model
        if model != self.first_model or (self.expected_model is not None and model != self.expected_model):
            raise ProtocolError("init_mismatch", "model")
        if self.executor_version is not None and ev["claude_code_version"] != self.executor_version:
            raise ProtocolError("init_mismatch", "accepted version")
        self.phase = "sent:replay"
        return [("turn_init", {"dispatch_id": t.dispatch_id, "permissionMode": ev["permissionMode"],
                               "tools": list(tools), "mcp_servers": [], "model": model, "cwd": cwd,
                               "claude_code_version": ev["claude_code_version"],
                               "apiKeySource": ev["apiKeySource"]})]

    def _on_system_thinking_tokens(self, ev, t):
        self._need(_is_int(ev.get("estimated_tokens"), 0, MAX_ESTIMATED_TOKENS), "estimated_tokens")
        if ev.get("user_message_uuid") != t.dispatch_id:
            raise ProtocolError("attribution", "thinking_tokens")
        if self.phase not in ("sent:replay", "running"):
            raise ProtocolError("out_of_order", f"thinking_tokens in {self.phase}")
        return []

    def _on_system_vcs_state_changed(self, ev, t):
        """Claude Code 2.1.296: the repository state of the work directory changed (after a tool call). Not a model
        response, not an anomaly, and no journal fact (the kinds of design 2.5 are closed): the shape and the place
        in the turn are checked, and nothing is read from it."""
        if self.phase != "running":
            raise ProtocolError("out_of_order", f"vcs_state_changed in {self.phase}")
        for name in ("kind", "branch", "cwd"):
            self._need(isinstance(ev.get(name), str) and len(ev[name]) <= MAX_VCS_FIELD, name)
        if not _within(ev["cwd"], self.workdir):
            raise ProtocolError("attribution", "vcs_state_changed cwd")
        return []

    def _on_user_replay(self, ev, t):
        if self.phase != "sent:replay":
            raise ProtocolError("out_of_order", f"replay in {self.phase}")
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        ok = (ev.get("isReplay") is True and isinstance(msg, dict) and msg.get("role") == "user"
              and isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
              and content[0].get("type") == "text" and isinstance(content[0].get("text"), str)
              and ev.get("parent_tool_use_id", "absent") is None)
        self._need(ok, "replay")
        if ev["uuid"] != t.dispatch_id or content[0]["text"] != t.text:
            raise ProtocolError("attribution", "replay")
        self.phase = "running"
        return [("dispatch_confirmed", {"dispatch_id": t.dispatch_id})]

    def _on_assistant(self, ev, t):
        if self.phase != "running":
            raise ProtocolError("out_of_order", f"assistant in {self.phase}")
        msg = ev.get("message")
        self._need(isinstance(msg, dict) and isinstance(msg.get("id"), str) and isinstance(msg.get("content"), list),
                   "message")
        self._need(isinstance(ev.get("request_id"), str), "request_id")
        self._need(ev.get("parent_tool_use_id", "absent") is None, "parent_tool_use_id")
        first = not t.assistant_events
        # Design v29.6: the first assistant event of a turn carries both
        # fields, equal to the dispatch. Later ones carry them as null or, as
        # 2.1.292 does (stream probe 2026-10-08), not at all: absent reads as
        # null and is journaled as null. Any non-null value on a later event,
        # even the dispatch id, breaks attribution: a protocol error, so the
        # turn is invalid and the session takes no further dispatch.
        if first:
            self._need("user_message_uuid" in ev and "user_message_uuids" in ev, "user_message_uuid(s)")
        umu, umus = ev.get("user_message_uuid"), ev.get("user_message_uuids")
        if first and not (umu == t.dispatch_id and umus == [t.dispatch_id]):
            raise ProtocolError("attribution", "first assistant")
        if not first and not (umu is None and umus is None):
            raise ProtocolError("attribution", "later assistant")
        rid, mid = ev["request_id"], msg["id"]
        if self.current_response is not None and rid == self.current_response[0]:
            if mid != self.current_response[1]:
                raise ProtocolError("response_ids", "one request_id, two message ids")
        else:
            if rid in self.request_ids or mid in self.message_ids:
                raise ProtocolError("response_ids", "a response id came back or was reused")
            self.request_ids.add(rid)
            self.message_ids.add(mid)
            self.current_response = (rid, mid)
            t.responses += 1
            self.total_responses += 1
        t.assistant_events.append({"request_id": rid, "message_id": mid, "user_message_uuid": umu,
                                   "user_message_uuids": list(umus) if isinstance(umus, list) else None})
        known = {c["tool_use_id"] for c in t.tool_calls}
        for item in msg["content"]:
            if not (isinstance(item, dict) and item.get("type") == "tool_use"):
                continue
            self._need(isinstance(item.get("id"), str) and isinstance(item.get("name"), str)
                       and isinstance(item.get("input"), dict), "tool_use")
            if item["id"] in known:
                raise ProtocolError("duplicate_tool_use")
            known.add(item["id"])
            t.tool_calls.append({"tool_use_id": item["id"], "name": item["name"],
                                 "input_sha256": sha256_hex(canonical(item["input"])), "result_count": 0,
                                 "result_is_error": None, "result_text_sha256": None})
        return []

    def _on_user_tool_result(self, ev, t):
        if self.phase != "running":
            raise ProtocolError("out_of_order", f"tool result in {self.phase}")
        msg = ev.get("message")
        self._need(isinstance(msg, dict) and msg.get("role") == "user" and isinstance(msg.get("content"), list),
                   "message")
        self._need(ev.get("parent_tool_use_id", "absent") is None, "parent_tool_use_id")
        out = []
        calls = {c["tool_use_id"]: c for c in t.tool_calls}
        for item in msg["content"]:
            shape_ok = (isinstance(item, dict) and set(item) <= {"type", "tool_use_id", "content", "is_error"}
                        and item.get("type") == "tool_result" and isinstance(item.get("tool_use_id"), str)
                        and isinstance(item.get("content"), str)
                        and isinstance(item.get("is_error", False), bool))
            if not shape_ok:
                # design 2.4: content not a string, is_error not a boolean or
                # another field -> this turn is invalid. The journal's anomaly
                # reasons are fixed by design 2.5 (unknown_type, extra_fields),
                # so the item is recorded as extra_fields with event_type
                # "user/tool_result": a wrong type or a missing field reads as
                # "fields other than allowed". The effect is the design's (turn
                # invalid, no further dispatch); only the label is coarser.
                out.append(("turn_anomaly", {"dispatch_id": t.dispatch_id, "reason": "extra_fields",
                                             "event_type": "user/tool_result"}))
                continue
            call = calls.get(item["tool_use_id"])
            if call is None:
                raise ProtocolError("tool_result_unknown")
            if call["result_count"]:
                raise ProtocolError("tool_result_unknown", "second result for one tool_use")
            call["result_count"] = 1
            call["result_is_error"] = item.get("is_error", False)
            call["result_text_sha256"] = sha256_hex(item["content"])
        return out

    def _on_rate_limit_event(self, ev, t):
        self._need(isinstance(ev.get("rate_limit_info"), dict), "rate_limit_info")
        if self.phase != "running":
            raise ProtocolError("out_of_order", f"rate_limit_event in {self.phase}")
        return []

    def _on_result(self, ev, t):
        if self.phase != "running":
            raise ProtocolError("out_of_order", f"result in {self.phase}")
        self._need(isinstance(ev.get("subtype"), str), "subtype")
        self._need(isinstance(ev.get("is_error"), bool), "is_error")
        self._need(_is_int(ev.get("num_turns"), 0, MAX_NUM_TURNS), "num_turns")
        self._need(_is_int(ev.get("result_index"), 0, MAX_RESULT_INDEX), "result_index")
        cost = finite_real(ev.get("total_cost_usd")) if not isinstance(ev.get("total_cost_usd"), bool) else None
        self._need(cost is not None and cost >= 0, "total_cost_usd")
        self._need(ev.get("queued_turn_count") == 0 and not isinstance(ev.get("queued_turn_count"), bool),
                   "queued_turn_count")
        structured = ev.get("structured_output")
        self._need("structured_output" not in ev or isinstance(structured, dict), "structured_output")
        text = ev.get("result")
        self._need(isinstance(text, str), "result")
        try:
            encoded_text = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ProtocolError("missing_field", "result is not valid Unicode") from exc
        if ev.get("user_message_uuid") != t.dispatch_id or ev.get("user_message_uuids") != [t.dispatch_id]:
            raise ProtocolError("attribution", "result")
        if ev["result_index"] != self.result_index + 1:
            raise ProtocolError("out_of_order", "result_index")
        if cost < self.last_cost:
            raise ProtocolError("out_of_order", "total_cost_usd decreased")
        self.result_index, self.last_cost = ev["result_index"], cost
        data = {"dispatch_id": t.dispatch_id, "subtype": ev["subtype"], "is_error": ev["is_error"],
                "num_turns": ev["num_turns"], "total_cost_usd": cost, "result_index": ev["result_index"],
                "user_message_uuids": [t.dispatch_id], "assistant_events": t.assistant_events,
                "tool_calls": t.tool_calls, "structured_output": structured if isinstance(structured, dict) else None}
        # Design 2.5, turn_result: result_text is a string up to 256 KiB "or
        # null with result_too_large=true". That is a recorded fact, not an
        # error: the report comes from structured_output (design 4), never
        # from this text, so an oversized text does not make the turn invalid
        # (planner ruling on S2a-2 part 2 review A1; the 512 KiB journal line
        # limit, review difference 3, is a different rule).
        fits = len(encoded_text) <= MAX_RESULT_TEXT
        data["result_text"] = text if fits else None
        data["result_too_large"] = isinstance(text, str) and not fits
        self.phase = "finishing"
        return [("turn_result", data)]
