"""``codex app-server``'s JSON-RPC protocol when a person chats with a role card whose AI tool is Codex (P38). Pure: no
I/O, no clock, in the manner of ``chat_protocol`` (Claude Code's).

What VBear writes to the server's stdin (one JSON object per line, no ``jsonrpc`` member): ``initialize`` and
``initialized`` first, then ``thread/start`` (or ``thread/resume`` in a later process), then ``turn/start`` for each
message, and an answer to every request the server makes. What it reads back goes through a ``CodexTracker``, which
answers with facts for the chat's record and for the session to act on.

The facts below are the ones P38-0 recorded with the real 0.163.0 (runs/20261106-p38/plan.md "P38-0 實測事實",
tests/codex_chat_fixtures.py) and the JSON Schema ``codex app-server generate-json-schema`` printed:

  * ``initialize`` is answered with the account-free ``codexHome`` (the folder it really reads, a person's home when
    VBear's own CODEX_HOME is not in force), a ``userAgent`` and the platform; VBear compares ``codexHome`` with the
    folder it gave and keeps none of it. The account comes from notifications: ``account/updated`` (the plan's kind),
    ``account/rateLimits/updated`` (windows of plan use, credits) and ``remoteControl/status/changed`` (host name and
    installation id). Only the window numbers and the reached-limit kind of the rate limits are kept.
  * With ``approvalPolicy: "untrusted"`` every command (``ls -a`` too) and every file change makes a request,
    ``item/commandExecution/requestApproval`` or ``item/fileChange/requestApproval``, and the answer is a
    ``decision``. The file-change request has no content: it names an ``itemId`` whose ``item/started`` carried the
    ``changes``. There is no "answer with a changed input": a person's change is a decline and a ``turn/steer``.
  * ``thread/tokenUsage/updated`` counts the whole thread, a resumed one included, and the first one after a resume
    repeats the last total: a turn's tokens are the total minus the last total VBear knows. There is no money in it.
  * An item that was started may never be completed (a command the sandbox stopped): not a violation.

The chat is kept safe by the sandbox and the permission cards, not by how strict this reader is: a notification of an
unknown kind is recorded as an anomaly (its method and field names, never a value) and not shown; an unknown kind of
server request is answered with a refusal. What does stop a chat (a ``violation``) is evidence that VBear's settings are
not in force, or that something ran that VBear did not allow.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, Decimal

from . import chat_protocol as cp, shared_rules
from . import stream_protocol as sp

MAX_TEXT_BYTES = cp.MAX_TEXT_BYTES              # one user message (UTF-8)
MAX_STDIN_LINE = cp.MAX_STDIN_LINE
MAX_INSTRUCTIONS_BYTES = 32 * 1024              # a role card's own instructions
MAX_CARD_BYTES = 12 << 10                       # one card as the live view shows it (chat_session.CARD_SHOW_MAX)
MAX_OUTPUT_TEXT = 256 * 1024                    # the output of one command, kept for the session to cut and mask
MAX_REPLY_TEXT = 256 * 1024
MAX_ERROR_TEXT = 4000                           # the message of an ``error`` notification, cut (a chat record keeps it behind a plain sentence)
MAX_EVENT_TYPE = sp.MAX_EVENT_TYPE
MAX_TOKENS = 10 ** 12
TOKEN_USD_PER_MTOK = Decimal("1.00")            # VBear's own accounting rule, not a price (ADR 0005; AGY chats use it too, ADR 0012)
MIN_TURN_USD = Decimal("0.01")
JSONRPC_METHOD_NOT_FOUND = -32601

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}\Z")
_METHOD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{0,63}\Z")
_MODEL_RE = cp._MODEL_RE
_EFFORT_RE = re.compile(r"^[a-z]{1,16}\Z")              # the schema allows any non-empty string; the card picks one
_PROTECTED = frozenset({".codex", ".agents", ".git"})   # no file change may touch these, at any depth
DECISIONS = ("accept", "decline", "cancel")             # the only answers ever written (no "for the session")
SANDBOX_POLICY = {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                  "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}

# What each request VBear writes is called when its answer comes back (CodexTracker.expect).
REQUEST_KINDS = frozenset({"initialize", "thread_start", "thread_resume", "mcp_list", "turn_start", "turn_steer",
                           "turn_interrupt", "thread_delete"})


@dataclass(frozen=True)
class CodexConstants:
    version: str
    config: tuple                       # the ``-c key=value`` settings, in the order the argv names them
    disabled_features: tuple            # the ``--disable <feature>`` list
    remote_control_env: tuple           # (name, value): keeps the app-server from enabling remote control
    env_keys: tuple                     # the environment variables the process gets, and no others
    allowed_items: frozenset            # the item kinds a chat may show (anything else stops it)
    known_notifications: frozenset      # the notification methods this version prints
    refused_requests: frozenset         # server requests VBear knows and answers with an error


_RECORDED_NOTIFICATIONS = frozenset({
    "remoteControl/status/changed", "account/updated", "account/rateLimits/updated", "thread/started",
    "thread/status/changed", "thread/settings/updated", "thread/readState/changed", "thread/tokenUsage/updated",
    "thread/deleted", "turn/started", "turn/completed", "turn/diff/updated", "turn/moderationMetadata",
    "item/started", "item/completed", "item/agentMessage/delta", "serverRequest/resolved",
    "mcpServer/startupStatus/updated"})
# Named in the schema, harmless to show nothing for: reasoning and plan text, command and patch output while it runs.
_QUIET_NOTIFICATIONS = frozenset({
    "item/reasoning/summaryTextDelta", "item/reasoning/summaryPartAdded", "item/reasoning/textDelta",
    "item/plan/delta", "turn/plan/updated", "item/commandExecution/outputDelta", "item/fileChange/outputDelta",
    "item/fileChange/patchUpdated", "error"})

VERSIONS = {
    "0.163.0": CodexConstants(
        version="0.163.0",
        config=('cli_auth_credentials_store="file"', 'web_search="disabled"', "check_for_update_on_startup=false",
                "notify=[]", 'history.persistence="none"', "skills.bundled.enabled=false",
                "skills.include_instructions=false", "project_doc_max_bytes=0",
                "sandbox_workspace_write.network_access=false", "sandbox_workspace_write.exclude_slash_tmp=true",
                "sandbox_workspace_write.exclude_tmpdir_env_var=true",
                # The work folder is the project root, so a git repository above it (a person's home folder is
                # one) is not searched for settings, MCP servers or skills (docs/evidence/codex-0.163.0-chat.md).
                "project_root_markers=[]"),
        disabled_features=("apps", "plugins", "remote_plugin", "hooks", "shell_snapshot", "browser_use",
                           "browser_use_external", "computer_use", "image_generation", "memories", "multi_agent",
                           "skill_mcp_dependency_install", "tool_suggest", "view_image", "in_app_browser", "goals",
                           "realtime_conversation", "sleep_tool", "workspace_dependencies", "worktrees"),
        remote_control_env=("CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED", "1"),
        env_keys=("PATH", "USER", "LOGNAME", "LANG", "CODEX_HOME", "HOME",
                  "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"),
        allowed_items=frozenset({"commandExecution", "fileChange", "agentMessage", "userMessage", "reasoning",
                                 "plan"}),
        known_notifications=_RECORDED_NOTIFICATIONS | _QUIET_NOTIFICATIONS,
        refused_requests=frozenset({"item/tool/requestUserInput", "mcpServer/elicitation/request",
                                    "item/permissions/requestApproval", "item/tool/call",
                                    "account/chatgptAuthTokens/refresh", "attestation/generate",
                                    "applyPatchApproval", "execCommandApproval"})),
}

# 0.167.0 (v0.22.1): the same constants. Every command VBear runs prints the same --help as 0.163.0's, `codex features list` still knows
# every feature VBear disables (two of them are now "removed": --disable still passes and no longer changes anything, see the evidence),
# and the app-server protocol schema (`codex app-server generate-json-schema`) adds to 0.163.0's: the requests, the server requests
# and the fields VBear uses are unchanged (docs/evidence/codex-0.167.0-chat.md). No real recording of 0.167.0 was made. A version here is
# a version VBear knows how to start, not a verified one: ``cli_versions.codex_chat_verified_versions`` decides which may chat.
VERSIONS["0.167.0"] = replace(VERSIONS["0.163.0"], version="0.167.0")


def constants_for(version) -> CodexConstants | None:
    return VERSIONS.get(version) if isinstance(version, str) else None


def _toml_path(path, what: str) -> str:
    """``path`` as the JSON string that is also a valid TOML basic string (the quote and the backslash are escaped by json.dumps;
    control characters are refused rather than escaped). ValueError for a path that is not an absolute path of printable
    characters that UTF-8 can hold."""
    if not (isinstance(path, str) and os.path.isabs(path)):
        raise ValueError(f"{what}要是絕對路徑")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        raise ValueError(f"{what}的路徑含有控制字元")
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{what}的路徑無法編碼") from exc
    return json.dumps(path, ensure_ascii=False)


def project_trust_setting(workdir) -> str:
    """The ``-c`` value that sets the work folder's trust to "untrusted" (an inline table: a dotted key would be cut at
    the dots of a path like ``~/.vbear``). Without any trust setting for the folder, a thread/start with a writable
    sandbox makes Codex write "trusted" for the project root, which can be a person's home folder, into its CODEX_HOME.
    ValueError for a path that is not an absolute path of printable characters that UTF-8 can hold: json.dumps gives a
    valid TOML basic string for the quote and the backslash; control characters are refused rather than escaped."""
    return "projects={%s={trust_level=\"untrusted\"}}" % _toml_path(workdir, "工作資料夾")


def shared_root_setting(path) -> str:
    """The ``-c`` value that makes the shared folder (P43-2, ADR 0009) the sandbox's one more writable root: an array of one
    string, written the way the work folder's trust setting is, with the same refusals (ValueError). Codex 0.163.0's own
    sandbox then lets a command write there and nowhere else outside the work folder, and keeps ``.git``, ``.codex`` and
    ``.agents`` read-only (docs/evidence/codex-0.163.0-shared.md)."""
    return "sandbox_workspace_write.writable_roots=[%s]" % _toml_path(path, "共用資料夾")


def roots_of(value) -> list[str]:
    """The writable roots of a chat process as a list: none (off) or the one shared folder. ValueError for anything else, so that a
    process can never be given a root VBear did not compute."""
    if value is None:
        return []
    if not (isinstance(value, (list, tuple)) and len(value) <= 1):
        raise ValueError("可寫的資料夾只能是共用資料夾一個")
    out = []
    for path in value:
        _toml_path(path, "共用資料夾")
        out.append(path)
    return out


def argv_for(consts: CodexConstants, workdir: str, shared: str | None = None) -> list[str]:
    """The arguments after the binary: the stdio app-server, VBear's settings, the work folder's trust setting, the shared
    folder's writable root when the employee has it (P43-2; nothing is added without it, so the list is the one of v0.17.0)
    and the features it turns off. ``workdir`` is the manifest's canonical work folder (ValueError when it cannot be written)."""
    out = ["app-server", "--listen", "stdio://"]
    settings = [*consts.config, project_trust_setting(workdir)]
    if shared is not None:
        settings.append(shared_root_setting(shared))
    for setting in settings:
        out += ["-c", setting]
    for feature in consts.disabled_features:
        out += ["--disable", feature]
    return out


# ---- what VBear writes ------------------------------------------------------------------------------------------

_line = cp._line


def _rid(value):
    """A JSON-RPC request id: an integer (not a bool) or a plain string; ValueError otherwise."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and _ID_RE.match(value):
        return value
    raise ValueError("request id 的格式不對")


def _thread_id(value) -> str:
    if not (isinstance(value, str) and sp.UUID_RE.match(value)):
        raise ValueError("thread id 的格式不對")
    return value


def _text(value, limit: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("訊息是空的")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("內容無法編碼成一行 JSON") from exc
    if size > limit:
        raise ValueError(f"內容超過 {limit} bytes")
    return value


def _thread_settings(cwd, model, developer_instructions) -> dict:
    if not (isinstance(cwd, str) and os.path.isabs(cwd) and "\0" not in cwd):
        raise ValueError("工作資料夾要是絕對路徑")
    params = {"cwd": cwd, "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "workspace-write"}
    if model is not None:
        if not (isinstance(model, str) and _MODEL_RE.match(model)):
            raise ValueError("模型名稱的格式不對")
        params["model"] = model
    if developer_instructions is not None:
        params["developerInstructions"] = _text(developer_instructions, MAX_INSTRUCTIONS_BYTES)
    return params


def initialize_line(request_id, version: str) -> bytes:
    return _line({"method": "initialize", "id": _rid(request_id), "params": {
        "clientInfo": {"name": "vbear", "title": "VBear", "version": str(version)[:32]},
        "capabilities": {"experimentalApi": False}}})


def initialized_line() -> bytes:
    return _line({"method": "initialized"})


def thread_start_line(request_id, *, cwd: str, model: str | None = None,
                      developer_instructions: str | None = None) -> bytes:
    params = _thread_settings(cwd, model, developer_instructions)
    params.update(ephemeral=False, serviceName="vbear")
    return _line({"method": "thread/start", "id": _rid(request_id), "params": params})


def thread_resume_line(request_id, thread_id: str, *, cwd: str, model: str | None = None,
                       developer_instructions: str | None = None) -> bytes:
    params = {"threadId": _thread_id(thread_id)}
    params.update(_thread_settings(cwd, model, developer_instructions))
    params["excludeTurns"] = True
    return _line({"method": "thread/resume", "id": _rid(request_id), "params": params})


def turn_start_line(request_id, thread_id: str, text: str, *, effort: str | None = None,
                    writable_roots=None) -> bytes:
    """``writable_roots`` (P43-2) is the shared folder in a list, or None: the sandbox of the turn names it, or names none."""
    params = {"threadId": _thread_id(thread_id), "input": [{"type": "text", "text": _text(text)}],
              "approvalPolicy": "untrusted", "sandboxPolicy": dict(SANDBOX_POLICY, writableRoots=roots_of(writable_roots))}
    if effort is not None:
        if not (isinstance(effort, str) and _EFFORT_RE.match(effort)):
            raise ValueError("effort 的值不對")
        params["effort"] = effort
    return _line({"method": "turn/start", "id": _rid(request_id), "params": params})


def turn_steer_line(request_id, thread_id: str, expected_turn_id: str, text: str) -> bytes:
    if not (isinstance(expected_turn_id, str) and _ID_RE.match(expected_turn_id)):
        raise ValueError("turn id 的格式不對")
    return _line({"method": "turn/steer", "id": _rid(request_id), "params": {
        "threadId": _thread_id(thread_id), "expectedTurnId": expected_turn_id,
        "input": [{"type": "text", "text": _text(text)}]}})


def turn_interrupt_line(request_id, thread_id: str, turn_id: str) -> bytes:
    if not (isinstance(turn_id, str) and _ID_RE.match(turn_id)):
        raise ValueError("turn id 的格式不對")
    return _line({"method": "turn/interrupt", "id": _rid(request_id),
                  "params": {"threadId": _thread_id(thread_id), "turnId": turn_id}})


def mcp_status_list_line(request_id, thread_id: str) -> bytes:
    """Asks for the MCP servers of the thread. With a ``threadId`` Codex answers for what that thread loaded; without
    one it answers for what the process loaded at its start, before the project's trust was known, and an empty list
    there proves nothing (docs/evidence/codex-0.163.0-chat.md)."""
    return _line({"method": "mcpServerStatus/list", "id": _rid(request_id),
                  "params": {"detail": None, "threadId": _thread_id(thread_id)}})


def thread_delete_line(request_id, thread_id: str) -> bytes:
    return _line({"method": "thread/delete", "id": _rid(request_id), "params": {"threadId": _thread_id(thread_id)}})


def decision_line(request_id, decision: str) -> bytes:
    """The answer to an approval request, to the server's request id as it came. Only accept, decline and cancel can
    be written: never "for the session", never an execpolicy or network-policy amendment."""
    if not (isinstance(decision, str) and decision in DECISIONS):
        raise ValueError("只能回 accept、decline 或 cancel")
    return _line({"id": _rid(request_id), "result": {"decision": decision}})


def error_line(request_id, message: str, code: int = JSONRPC_METHOD_NOT_FOUND) -> bytes:
    """The answer to a server request VBear does not take (anything but the two approval requests)."""
    if not (isinstance(code, int) and not isinstance(code, bool)):
        raise ValueError("錯誤碼要是整數")
    return _line({"id": _rid(request_id), "error": {"code": code, "message": str(message)[:500]}})


# ---- what VBear answers itself ----------------------------------------------------------------------------------

Judgement = cp.Judgement


def estimate_usd(tokens) -> Decimal:
    """What a turn is counted as in the day's limit: ``tokens`` / 1,000,000 x US$1.00 rounded up to the cent, at least
    US$0.01. ValueError when there is no usable count (the session then counts the turn's cap instead)."""
    if isinstance(tokens, bool) or not isinstance(tokens, int) or not 0 <= tokens <= MAX_TOKENS:
        raise ValueError("沒有可用的 token 數")
    usd = (Decimal(tokens) * TOKEN_USD_PER_MTOK / Decimal(1_000_000)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return max(usd, MIN_TURN_USD)


def _change_paths(change) -> list | None:
    """The paths one ``fileChange`` change names (its own and a move's target), or None when it is not in the shape
    0.163.0 prints: {path, kind: {type: add|delete|update[, move_path]}, diff}."""
    if not isinstance(change, dict):
        return None
    path, kind, diff = change.get("path"), change.get("kind"), change.get("diff")
    if not (isinstance(path, str) and path and isinstance(kind, dict) and isinstance(diff, str)):
        return None
    if kind.get("type") not in ("add", "delete", "update"):
        return None
    paths = [path]
    if kind.get("type") == "update" and kind.get("move_path") is not None:
        if not (isinstance(kind["move_path"], str) and kind["move_path"]):
            return None
        paths.append(kind["move_path"])
    return paths


def judge_file_change(changes, workdir: str, max_bytes: int = MAX_CARD_BYTES, shared: str | None = None) -> Judgement:
    """What VBear does with a file-change request (P38 design): every path, links followed, must be inside the role
    card's work folder and under none of Codex's own ``.codex``, ``.agents`` or ``.git`` (at any depth); the card must
    fit ``max_bytes``. Anything else, or a shape it does not know, is refused with no way to allow; the rest is asked.

    ``shared`` (P43-2, ADR 0009) is the shared folder of an employee the person switched it on for, or None. It is a second
    root: a path that is in it after the links are followed is asked about (a card that says other employees can read it) unless
    ``shared_rules.write_problem`` refuses it (a protected name at any depth, a file with another hard link, the folder itself):
    then there is no card. A path in neither root is refused as before."""
    if not isinstance(changes, list) or not changes:
        return Judgement("deny", "看不到這次要修改的內容")
    work = os.path.realpath(workdir)
    root = os.path.realpath(shared) if isinstance(shared, str) and os.path.isabs(shared) else None
    size = 0
    in_shared = False
    for change in changes:
        paths = _change_paths(change)
        if paths is None:
            return Judgement("deny", "檔案修改的格式不認得")
        size += sum(len(p.encode("utf-8", "replace")) for p in paths) + len(change["diff"].encode("utf-8", "replace"))
        for path in paths:
            where = cp._resolve(path, work)
            if where is None:
                return Judgement("deny", "檔案路徑的格式不對")
            if root is not None and cp._inside(where, root) and not cp._inside(where, work):
                problem = shared_rules.write_problem(where, root)
                if problem:
                    return Judgement("deny", problem)
                in_shared = True
                continue
            if not cp._inside(where, work) or where == work:
                return Judgement("deny", "只能改員工自己的工作資料夾裡的檔案，這個路徑在資料夾以外"
                                 if root is None else "只能改員工自己的工作資料夾或共用資料夾裡的檔案，這個路徑在資料夾以外")
            for part in os.path.relpath(where, work).split(os.sep):
                if part.casefold() in _PROTECTED:
                    return Judgement("deny", f"{part} 是 Codex 或版本控制自己的資料夾，聊天裡不能改")
    if size > max_bytes:
        return Judgement("deny", "這次修改的內容太大，一張卡放不下")
    if in_shared:
        return Judgement("ask", "修改共用資料夾裡的檔案，其他打開共用資料夾的員工都讀得到，要你允許")
    return Judgement("ask", "修改員工工作資料夾裡的檔案，要你允許")


# ---- reading what the server prints -----------------------------------------------------------------------------

def _anomaly(label, fields) -> tuple[str, dict]:
    label = label if isinstance(label, str) and _METHOD_RE.match(label) else "?"
    return ("anomaly", {"event_type": label[:MAX_EVENT_TYPE],
                        "fields": sp.anomaly_fields(fields if isinstance(fields, (dict, list, tuple, set)) else ())})


def _is_int(value, low: int = 0, high: int = MAX_TOKENS) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _item_id(value) -> str | None:
    return value if isinstance(value, str) and _ID_RE.match(value) else None


def _request_id(value):
    return value if (isinstance(value, int) and not isinstance(value, bool)) or \
        (isinstance(value, str) and _ID_RE.match(value)) else None


def _text_or_none(value, limit: int):
    return value[:limit] if isinstance(value, str) else None


def _window(win, prefix: str) -> dict:
    ok = isinstance(win, dict)
    pct = win.get("usedPercent") if ok else None
    mins = win.get("windowDurationMins") if ok else None
    reset = win.get("resetsAt") if ok else None
    return {f"{prefix}_pct": pct if _is_int(pct, 0, 10_000) else None,
            f"{prefix}_window_min": mins if _is_int(mins, 0, 10 ** 7) else None,
            f"{prefix}_resets_at": reset if _is_int(reset, 0, 10 ** 12) else None}


_REACHED = frozenset({"rate_limit_reached", "workspace_owner_credits_depleted", "workspace_member_credits_depleted",
                      "workspace_owner_usage_limit_reached", "workspace_member_usage_limit_reached"})
_TURN_STATUS = frozenset({"completed", "interrupted", "failed", "inProgress"})
_ITEM_STATUS = frozenset({"inProgress", "completed", "failed", "declined"})


def _sandbox_is_ours(sandbox, roots=()) -> bool:
    """Whether the sandbox Codex reports is, field for field, the one VBear asked for (SANDBOX_POLICY): the same five
    fields and no others (0.163.0 prints exactly these for ``workspaceWrite``), the same types, the same values. A
    missing field, an extra one (such as ``readOnlyAccess``) or ``1`` for ``True`` is not it. ``roots`` are the writable
    roots VBear asked for (none, or the shared folder, P43-2): the answer must list exactly those, in that order."""
    if not isinstance(sandbox, dict) or set(sandbox) != set(SANDBOX_POLICY):
        return False
    for key, want in SANDBOX_POLICY.items():
        got = sandbox[key]
        if key == "writableRoots":
            want = list(roots)
        if isinstance(want, bool):
            if got is not want:
                return False
        elif isinstance(want, list):
            if not (isinstance(got, list) and got == want and all(isinstance(x, str) for x in got)):
                return False
        elif not (isinstance(got, str) and got == want):
            return False
    return True


class CodexTracker:
    """One ``codex app-server`` process and its one thread. ``on_message`` turns one parsed stdout line into facts,
    (kind, data) pairs:

      initialized       {}                                      initialize was answered, with the folder VBear gave
      remote_control    {disabled: True}
      session_ready     {thread_id, model, resumed}             the thread's answer is what VBear asked for
      mcp_checked       {count: 0}                              the MCP list is empty
      turn_accepted     {turn_id}                               the answer to turn/start
      steer_accepted    {turn_id}                               the answer to turn/steer
      interrupt_accepted {}
      delete_accepted   {}
      request_failed    {kind, code}                            an error answer to a request VBear wrote
      turn_started      {turn_id}
      item_started      {item_id, item_type, phase}             agentMessage, commandExecution, fileChange only
      delta             {item_id, text}                         a piece of the reply (shown, not kept)
      reply             {item_id, phase, text}                  a whole message of the reply
      approval_request  {request_id, kind, item_id, action, why, codex_reason, ...}
                        kind "command": command, cwd, actions; kind "file_change": changes
                        action "ask" (a card) or "deny" (VBear says no itself: decision_line(.., "decline"))
      request_resolved  {request_id}
      command_done      {item_id, status, exit_code, output}
      file_change_done  {item_id, status}
      usage             {total_tokens, delta_tokens, baseline}  delta_tokens None when the total went back
      plan_usage        {primary_pct, primary_window_min, primary_resets_at, secondary_*, reached}
      turn_completed    {turn_id, status, error, tokens, open_items}   tokens None when a count was unusable
      turn_error        {will_retry, message}                   message: the words of the notification's ``error.message`` (else ``message``), cut to
                                                                MAX_ERROR_TEXT, "" when there are none; nothing else of the notification is read
      thread_deleted    {thread_id}
      unknown_request   {request_id, method, refused}           to be answered with error_line
      anomaly           {event_type, fields}
      violation         {message}                               the session must stop; nothing more is read

    The session says which requests it wrote (``expect``), where a turn begins (``begin_turn``) and which items it
    allowed (``approve``) or refused (``refuse``). Nothing from ``initialize``, the account notifications, the MCP
    servers or ``instructionSources`` is ever put in a fact: only that they were as expected, or how many."""

    def __init__(self, consts: CodexConstants, *, workdir: str, codex_home: str, thread_id: str | None = None,
                 resumed: bool = False, last_total: int | None = None, writable_roots=None):
        self.c = consts
        self.workdir = os.path.realpath(workdir)
        self.writable_roots = roots_of(writable_roots)       # the shared folder (P43-2) or none: what the thread's answer must list
        self.codex_home = os.path.realpath(codex_home)
        self.thread_id = _thread_id(thread_id) if thread_id is not None else None
        self.resumed = resumed
        self.total_tokens: int | None = last_total if _is_int(last_total) else None
        self.pending: dict = {}                 # request id -> kind (REQUEST_KINDS)
        self.stopped = False
        self.ready = False
        self.turn_id: str | None = None
        self.items: dict[str, dict] = {}        # this turn's items: {"type", "done", "changes", "asked"}
        self.approved: set[str] = set()
        self.refused: set[str] = set()
        self.requests: dict = {}                # approval request id -> item id, until serverRequest/resolved
        self._baseline: dict | None = None      # cwd, approval policy, reviewer, sandbox of the thread's answer
        self._started_id: str | None = None     # a thread/started that came before the thread's answer
        self._turn_delta = 0
        self._turn_unknown = False

    # -- what the session tells it

    def expect(self, request_id, kind: str) -> None:
        if kind not in REQUEST_KINDS:
            raise ValueError("不認得的請求種類")
        self.pending[_rid(request_id)] = kind

    def begin_turn(self) -> None:
        self._turn_delta, self._turn_unknown = 0, False

    @property
    def turn_tokens(self) -> int | None:
        """The tokens this turn used so far: None when a count was unusable (the session counts the turn's cap)."""
        return None if self._turn_unknown else self._turn_delta

    def approve(self, item_id) -> None:
        if isinstance(item_id, str):
            self.approved.add(item_id)

    def refuse(self, item_id) -> None:
        if isinstance(item_id, str):
            self.refused.add(item_id)

    # -- reading

    def on_message(self, msg) -> list[tuple[str, dict]]:
        if self.stopped:
            return []
        try:
            out = self._on_message(msg)
        except Exception:
            # Strict JSON can still hold shapes no handler expects: an anomaly, never an exception out of the loop.
            label = msg.get("method") if isinstance(msg, dict) else None
            out = [_anomaly(label, msg if isinstance(msg, dict) else ())]
        if any(k == "violation" for k, _ in out):
            self.stopped = True
        return out

    @staticmethod
    def _violation(message: str) -> list[tuple[str, dict]]:
        return [("violation", {"message": message})]

    def _on_message(self, msg):
        if not isinstance(msg, dict):
            return [_anomaly("?", ())]
        method = msg.get("method")
        if isinstance(method, str):
            params = msg.get("params")
            params = params if isinstance(params, dict) else {}
            if "id" in msg:
                return self._on_server_request(msg["id"], method, params)
            return self._on_notification(method, params)
        if "id" in msg and ("result" in msg or "error" in msg):
            return self._on_response(msg)
        return [_anomaly("?", msg)]

    # -- answers to what VBear wrote

    def _on_response(self, msg):
        rid = msg["id"]
        kind = self.pending.pop(rid, None) if _request_id(rid) is not None else None
        if kind is None:
            return [_anomaly("response", msg)]
        if "error" in msg:
            err = msg["error"]
            code = err.get("code") if isinstance(err, dict) else None
            return [("request_failed", {"kind": kind, "code": code if _is_int(code, -10 ** 9, 10 ** 9) else None})]
        result = msg.get("result")
        return getattr(self, "_answer_" + kind)(result if isinstance(result, dict) else None)

    def _answer_initialize(self, result):
        home = result.get("codexHome") if result else None
        if not isinstance(home, str) or not home or os.path.realpath(home) != self.codex_home:
            return self._violation("Codex 讀的不是 VBear 給它的資料夾")
        return [("initialized", {})]

    def _settings_problems(self, policy, reviewer, sandbox, cwd) -> list[str]:
        problems = []
        if policy != "untrusted":
            problems.append("核准方式不是每個指令都問")
        if reviewer != "user":
            problems.append("核准的人不是你")
        if not _sandbox_is_ours(sandbox, self.writable_roots):
            problems.append("沙盒不是只能寫工作資料夾" + ("和共用資料夾" if self.writable_roots else "") + "、不能連網")
        if not (isinstance(cwd, str) and cwd and os.path.realpath(cwd) == self.workdir):
            problems.append("工作資料夾")
        return problems

    def _thread_answer(self, kind: str, result):
        thread = result.get("thread") if result else None
        tid = thread.get("id") if isinstance(thread, dict) else None
        if not (isinstance(tid, str) and sp.UUID_RE.match(tid)):
            return self._violation("Codex 回覆的對話資料格式不對")
        if self.thread_id is not None and (tid != self.thread_id or kind == "thread_start"):
            return self._violation("Codex 開的不是 VBear 指定的對話")
        if self._started_id is not None and self._started_id != tid:
            return self._violation("Codex 通知的對話和它回覆的不是同一個")
        problems = self._settings_problems(result.get("approvalPolicy"), result.get("approvalsReviewer"),
                                           result.get("sandbox"), result.get("cwd"))
        sources = result.get("instructionSources")
        if not (isinstance(sources, list) and not sources):
            problems.append(f"載入了指示檔（{len(sources) if isinstance(sources, list) else '?'} 個，聊天不能有）")
        if problems:
            return self._violation("Codex 的啟動資訊與 VBear 的設定不符：" + "、".join(problems))
        self.thread_id = tid
        self.ready = True
        self._baseline = {k: result.get(src) for k, src in (("cwd", "cwd"), ("approvalPolicy", "approvalPolicy"),
                          ("approvalsReviewer", "approvalsReviewer"), ("sandboxPolicy", "sandbox"),
                          ("activePermissionProfile", "activePermissionProfile"))}
        model = result.get("model")
        return [("session_ready", {"thread_id": tid, "resumed": kind == "thread_resume",
                                   "model": model if isinstance(model, str) and _MODEL_RE.match(model) else "?"})]

    def _answer_thread_start(self, result):
        return self._thread_answer("thread_start", result)

    def _answer_thread_resume(self, result):
        return self._thread_answer("thread_resume", result)

    def _answer_mcp_list(self, result):
        data = result.get("data") if result else None
        if not isinstance(data, list):
            return self._violation("Codex 回覆的 MCP 清單格式不對")
        if data:
            return self._violation(f"Codex 載入了 MCP 伺服器（{len(data)} 個，聊天不能有）")
        return [("mcp_checked", {"count": 0})]

    def _answer_turn_start(self, result):
        turn = result.get("turn") if result else None
        tid = _item_id(turn.get("id")) if isinstance(turn, dict) else None
        if tid is None:
            return [_anomaly("turn/start", result or ())]
        self.turn_id = tid
        return [("turn_accepted", {"turn_id": tid})]

    def _answer_turn_steer(self, result):
        tid = _item_id(result.get("turnId")) if result else None
        return [("steer_accepted", {"turn_id": tid})] if tid else [_anomaly("turn/steer", result or ())]

    def _answer_turn_interrupt(self, result):
        return [("interrupt_accepted", {})]

    def _answer_thread_delete(self, result):
        return [("delete_accepted", {})]

    # -- notifications

    def _other_thread(self, params) -> bool:
        tid = params.get("threadId")
        return self.thread_id is not None and isinstance(tid, str) and tid != self.thread_id

    def _on_notification(self, method: str, params: dict):
        if method not in self.c.known_notifications:
            return [_anomaly(method, params)]
        if method != "thread/started" and self._other_thread(params):
            return self._violation("Codex 回報了別的對話的事件")
        handler = getattr(self, "_n_" + method.replace("/", "_"), None)
        return handler(params) if handler else []

    def _n_remoteControl_status_changed(self, params):
        if params.get("status") != "disabled":
            return self._violation("Codex 的遠端控制沒有關閉")
        return [("remote_control", {"disabled": True})]

    def _n_mcpServer_startupStatus_updated(self, params):
        return self._violation("Codex 啟動了 MCP 伺服器（聊天不能有）")

    def _n_thread_started(self, params):
        thread = params.get("thread")
        tid = thread.get("id") if isinstance(thread, dict) else None
        if not (isinstance(tid, str) and sp.UUID_RE.match(tid)):
            return [_anomaly("thread/started", params)]
        if self.thread_id is not None and tid != self.thread_id:
            return self._violation("Codex 開了別的對話")
        if self.thread_id is None:
            self._started_id = tid
        return []

    def _n_thread_settings_updated(self, params):
        settings = params.get("threadSettings")
        if not isinstance(settings, dict):
            return [_anomaly("thread/settings/updated", params)]
        problems = []
        if "approvalPolicy" in settings and settings["approvalPolicy"] != "untrusted":
            problems.append("核准方式")
        if "approvalsReviewer" in settings and settings["approvalsReviewer"] != "user":
            problems.append("核准的人")
        if "sandboxPolicy" in settings and self._settings_problems(
                "untrusted", "user", settings["sandboxPolicy"], self.workdir):
            problems.append("沙盒")
        if "cwd" in settings and not (isinstance(settings["cwd"], str)
                                      and os.path.realpath(settings["cwd"]) == self.workdir):
            problems.append("工作資料夾")
        for key, was in (self._baseline or {}).items():
            if key in settings and key not in ("cwd",) and settings[key] != was:
                problems.append(key)
        if problems:
            return self._violation("Codex 的設定被改了：" + "、".join(sorted(set(problems))))
        return []

    def _n_item_agentMessage_delta(self, params):
        text, iid = params.get("delta"), _item_id(params.get("itemId"))
        if not isinstance(text, str) or iid is None:
            return [_anomaly("item/agentMessage/delta", params)]
        return [("delta", {"item_id": iid, "text": text})]

    def _n_item_fileChange_patchUpdated(self, params):
        iid, changes = _item_id(params.get("itemId")), params.get("changes")
        if iid in self.items and self.items[iid]["type"] == "fileChange" and isinstance(changes, list):
            self.items[iid]["changes"] = changes
        return []

    def _n_serverRequest_resolved(self, params):
        rid = _request_id(params.get("requestId"))
        if rid is None:
            return [_anomaly("serverRequest/resolved", params)]
        self.requests.pop(rid, None)
        return [("request_resolved", {"request_id": rid})]

    def _n_thread_deleted(self, params):
        tid = params.get("threadId")
        return [("thread_deleted", {"thread_id": tid})] if isinstance(tid, str) and sp.UUID_RE.match(tid) else \
            [_anomaly("thread/deleted", params)]

    def _n_error(self, params):
        # The schema's ErrorNotification is {error: {message, codexErrorInfo, additionalDetails}, willRetry, threadId, turnId}; 0.167.0 was seen to say
        # "The '<model>' model is not supported when using Codex with a ChatGPT account." in error.message. A top-level ``message`` is read too, as a
        # guess for a shape no sample shows. Only that text is taken (cut); codexErrorInfo and additionalDetails are never read.
        err = params.get("error")
        message = err.get("message") if isinstance(err, dict) else None
        if not isinstance(message, str):
            message = params.get("message")
        return [("turn_error", {"will_retry": params.get("willRetry") is True,
                                "message": message[:MAX_ERROR_TEXT] if isinstance(message, str) else ""})]

    def _n_account_rateLimits_updated(self, params):
        limits = params.get("rateLimits")
        if not isinstance(limits, dict):
            return [_anomaly("account/rateLimits/updated", params)]
        reached = limits.get("rateLimitReachedType")
        data = {}
        data.update(_window(limits.get("primary"), "primary"))
        data.update(_window(limits.get("secondary"), "secondary"))
        data["reached"] = None if reached is None else reached if reached in _REACHED else "?"
        return [("plan_usage", data)]

    def _n_thread_tokenUsage_updated(self, params):
        usage = params.get("tokenUsage")
        total = usage.get("total") if isinstance(usage, dict) else None
        count = total.get("totalTokens") if isinstance(total, dict) else None
        if not _is_int(count):
            return [_anomaly("thread/tokenUsage/updated", params)]
        baseline = False
        if self.total_tokens is None:
            if self.resumed:
                # A resumed thread repeats its last total first and VBear has no record of it: a starting line.
                self.total_tokens, baseline = count, True
            else:
                self.total_tokens = 0                 # a new thread starts at nothing
        delta = count - self.total_tokens
        if delta < 0:
            delta = None                              # the total went back: nothing to trust
            self._turn_unknown = True
        else:
            self._turn_delta += delta
        self.total_tokens = count
        return [("usage", {"total_tokens": count, "delta_tokens": 0 if baseline else delta, "baseline": baseline})]

    def _n_turn_started(self, params):
        turn = params.get("turn")
        tid = _item_id(turn.get("id")) if isinstance(turn, dict) else None
        if tid is None:
            return [_anomaly("turn/started", params)]
        self.turn_id = tid
        return [("turn_started", {"turn_id": tid})]

    def _n_turn_completed(self, params):
        turn = params.get("turn")
        if not isinstance(turn, dict):
            return [_anomaly("turn/completed", params)]
        status = turn.get("status")
        open_items = sum(1 for i in self.items.values() if not i["done"])
        self.items.clear()
        return [("turn_completed", {"turn_id": _item_id(turn.get("id")), "status": status if status in _TURN_STATUS
                                    else "?", "error": turn.get("error") is not None, "tokens": self.turn_tokens,
                                    "open_items": open_items})]

    # -- items

    def _item(self, params):
        item = params.get("item")
        iid = _item_id(item.get("id")) if isinstance(item, dict) else None
        typ = item.get("type") if isinstance(item, dict) else None
        return (item, iid, typ) if iid is not None and isinstance(typ, str) else (None, None, None)

    def _forbidden_item(self, typ) -> list | None:
        if typ in self.c.allowed_items:
            return None
        return self._violation(f"Codex 用了 VBear 沒開放的功能：{sp.safe_name(typ)}")

    def _n_item_started(self, params):
        item, iid, typ = self._item(params)
        if iid is None:
            return [_anomaly("item/started", params)]
        bad = self._forbidden_item(typ)
        if bad:
            return bad
        changes = item.get("changes") if typ == "fileChange" and isinstance(item.get("changes"), list) else None
        self.items[iid] = {"type": typ, "done": False, "changes": changes, "asked": None}
        if typ not in ("agentMessage", "commandExecution", "fileChange"):
            return []
        return [("item_started", {"item_id": iid, "item_type": typ,
                                  "phase": sp.safe_name(item.get("phase")) if typ == "agentMessage" else None})]

    def _n_item_completed(self, params):
        item, iid, typ = self._item(params)
        if iid is None:
            return [_anomaly("item/completed", params)]
        bad = self._forbidden_item(typ)
        if bad:
            return bad
        rec = self.items.setdefault(iid, {"type": typ, "done": False, "changes": None, "asked": None})
        rec["done"] = True
        status = item.get("status")
        if typ == "agentMessage":
            text = _text_or_none(item.get("text"), MAX_REPLY_TEXT)
            if text is None:
                return [_anomaly("item/completed", item)]
            return [("reply", {"item_id": iid, "phase": sp.safe_name(item.get("phase")), "text": text})]
        if typ not in ("commandExecution", "fileChange"):
            return []
        # A command or a file change that finished without VBear's yes is what the chat must not have.
        if iid not in self.approved and status not in ("declined", "failed"):
            return self._violation(f"Codex 沒有經過 VBear 的允許就完成了{'指令' if typ == 'commandExecution' else '檔案修改'}")
        if typ == "fileChange":
            return self._file_change_done(iid, rec, item, status)
        code = item.get("exitCode")
        return [("command_done", {"item_id": iid, "status": status if status in _ITEM_STATUS else "?",
                                  "exit_code": code if _is_int(code, -10 ** 6, 10 ** 6) else None,
                                  "output": _text_or_none(item.get("aggregatedOutput"), MAX_OUTPUT_TEXT)})]

    def _file_change_done(self, iid, rec, item, status):
        changes = item.get("changes")
        if status == "completed" and rec["asked"] is not None and isinstance(changes, list) \
                and _change_keys(changes) != rec["asked"]:
            return self._violation("Codex 完成的檔案修改和允許時看到的不同")
        return [("file_change_done", {"item_id": iid, "status": status if status in _ITEM_STATUS else "?"})]

    # -- requests from the server

    def _on_server_request(self, rid, method: str, params: dict):
        rid = _request_id(rid)
        if rid is None:
            return [_anomaly(method, params)]
        if self._other_thread(params):
            return self._violation("Codex 回報了別的對話的請求")
        if method == "item/commandExecution/requestApproval":
            return self._command_request(rid, params)
        if method == "item/fileChange/requestApproval":
            return self._file_request(rid, params)
        return [("unknown_request", {"request_id": rid, "method": method if _METHOD_RE.match(method) else "?",
                                     "refused": method in self.c.refused_requests})]

    def _ask(self, rid, iid, data: dict, action: str, why: str):
        data.update(request_id=rid, item_id=iid, action=action, why=why)
        if iid is not None:
            self.requests[rid] = iid
        return [("approval_request", data)]

    def _command_request(self, rid, params):
        iid = _item_id(params.get("itemId"))
        command, kind, net = params.get("command"), params.get("kind", "command"), params.get("networkApprovalContext")
        raw = params.get("commandActions")
        actions = [{"type": sp.safe_name(a.get("type")), "command": _text_or_none(a.get("command"), 4096)}
                   for a in raw[:20] if isinstance(a, dict)] if isinstance(raw, list) else []
        cwd = params.get("cwd")
        data = {"kind": "command", "command": _text_or_none(command, MAX_OUTPUT_TEXT),
                "cwd": cwd if isinstance(cwd, str) else None, "actions": actions,
                "codex_reason": _text_or_none(params.get("reason"), 2000)}
        if kind != "command":
            return self._ask(rid, iid, data, "deny", "這不是要執行指令，而是要把輸入送進已在跑的終端機，聊天不提供")
        if net is not None:
            return self._ask(rid, iid, data, "deny", "這個指令要連網，聊天不能連網")
        if iid is None or not isinstance(command, str) or not command:
            return self._ask(rid, iid, data, "deny", "請求沒有給要執行的指令")
        return self._ask(rid, iid, data, "ask", "每個指令都要你允許才會執行")

    def _file_request(self, rid, params):
        iid = _item_id(params.get("itemId"))
        rec = self.items.get(iid) if iid is not None else None
        changes = rec["changes"] if rec and rec["type"] == "fileChange" else None
        data = {"kind": "file_change", "codex_reason": _text_or_none(params.get("reason"), 2000),
                "changes": [dict(c) for c in changes if isinstance(c, dict)] if isinstance(changes, list) else []}
        if iid is None:
            return self._ask(rid, iid, data, "deny", "請求沒有指出是哪一項修改")
        if params.get("grantRoot") is not None:
            return self._ask(rid, iid, data, "deny", "這個請求要整個資料夾的寫入權限，聊天不給")
        verdict = judge_file_change(changes, self.workdir, shared=self.writable_roots[0] if self.writable_roots else None)
        if verdict.action == "ask" and rec is not None:
            rec["asked"] = _change_keys(changes)
        return self._ask(rid, iid, data, verdict.action, verdict.reason)


def _change_keys(changes) -> frozenset:
    """Which paths a list of file changes touches and how: what an approval must still match when it completes."""
    keys = set()
    for c in changes:
        if isinstance(c, dict) and isinstance(c.get("kind"), dict):
            keys.add((c.get("path"), c["kind"].get("type"), c["kind"].get("move_path")))
        else:
            keys.add(("?", "?", "?"))
    return frozenset(keys)
