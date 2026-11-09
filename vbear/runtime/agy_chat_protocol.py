"""``agy acp``'s JSON-RPC protocol (ACP v1, one JSON object per line on stdio) when a person chats with a role card whose AI
tool is AGY (P46-1, ADR 0012). Pure: no I/O, no clock, in the manner of ``codex_chat_protocol``.

What VBear writes to the process's stdin: ``initialize``, then ``session/new`` (or ``session/resume`` in a later process),
then ``session/set_model`` (every time, after either), then ``session/prompt`` for each message, ``session/cancel`` to stop a
turn, and an answer to every request the agent makes. What it reads back goes through an ``AgyTracker``, which answers with
facts for the chat's record and for the session to act on.

Where the facts come from (docs/evidence/agy-1.5.3-chat.md, P46's spike of 2026-11-09 on the real 1.5.3):

  * "measured": the method, the option ids and kinds, the ``BypassSandbox`` key, the ``usage`` fields and their arithmetic,
    ``stopReason: "cancelled"``, ``set_model`` answering ``{}``, a command that failed still ending as ``completed`` with its
    exit code in ``rawOutput.exit_code``.
  * "format": the shape of the other fields is ACP v1's public one. The spike's raw messages were not kept, so the fixtures
    (tests/fixtures/agy-chat/) are synthetic, and the first real run of ``boundary_check --mode agy-chat`` confirms every
    "format" field. A message that does not have the shape stops nothing by itself: it is an anomaly (its method and field
    names, never a value), and a thing VBear cannot read as safe is refused.

What does stop a chat (a ``violation`` fact) is evidence that VBear's settings are not in force or that something ran that VBear
did not allow: a tool that ran without VBear having answered "allow once", a read outside the work folder that VBear was not asked
about, a mode other than ``default``, another session's messages, a model that was not set.

VBear answers a permission request with one of two options only, the one of kind ``allow_once`` or the one of kind
``reject_once``; the other kinds of option are known and never chosen (``NEVER_CHOSEN_OPTION_KINDS``).
"""

from __future__ import annotations

import copy
import json
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal

from . import chat_protocol as cp, codex_chat_protocol as ccp
from . import stream_protocol as sp

MAX_TEXT_BYTES = cp.MAX_TEXT_BYTES              # one user message (UTF-8)
MAX_STDIN_LINE = cp.MAX_STDIN_LINE
MAX_INSTRUCTIONS_BYTES = ccp.MAX_INSTRUCTIONS_BYTES
MAX_CARD_BYTES = ccp.MAX_CARD_BYTES             # one card as the live view shows it (chat_session.CARD_SHOW_MAX)
MAX_OUTPUT_TEXT = ccp.MAX_OUTPUT_TEXT           # the output of one command, kept for the session to cut and mask
MAX_REPLY_TEXT = ccp.MAX_REPLY_TEXT
MAX_EVENT_TYPE = sp.MAX_EVENT_TYPE
MAX_TOKENS = ccp.MAX_TOKENS
JSONRPC_METHOD_NOT_FOUND = ccp.JSONRPC_METHOD_NOT_FOUND
MAX_PATH = 4096

# The kinds of permission option VBear knows and never chooses (ADR 0012 decision 2). Nothing else in the package may carry
# these words as a value to send (tests/test_autonomy_guard.py rule 14a).
NEVER_CHOSEN_OPTION_KINDS = frozenset({"allow_always", "reject_always"})
DECISIONS = ("allow", "deny", "cancelled")      # the only answers ever written

# What VBear says itself when it refuses (the sentences the chat shows; they name no path).
REASON_BYPASS = "AGY 要在沙盒外執行指令，聊天不允許"
REASON_NETWORK = "聊天不能連網"
REASON_OPTIONS = "AGY 給的選項 VBear 不認得"

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}\Z")
_METHOD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{0,63}\Z")
_MODEL_RE = cp._MODEL_RE


@dataclass(frozen=True, eq=False)
class AgyConstants:
    """Everything that depends on the version of AGY. A real machine corrects it in one place."""
    version: str
    protocol_version: int
    model_id: str                       # the only model a chat uses; set again after every session/new and session/resume
    argv_template: tuple                # after the binary; "{gemini_dir}" is the chat's own settings folder
    shared_flag: str                    # names the shared folder as one more folder of the work (P43)
    env_keys: tuple                     # the environment variables the process gets, and no others
    settings: dict                      # antigravity-cli/settings.json, written by VBear before every process
    session_updates: frozenset          # the session/update kinds this version prints
    tool_kinds: frozenset               # the tool kinds ACP names
    allow_option_kind: str
    reject_option_kind: str
    usage_fields: tuple
    usage_sum_fields: tuple             # totalTokens is the sum of these (measured)
    home_forbidden: tuple               # paths in the chat's settings folder that VBear never writes and that must not be there
    home_created: tuple                 # the only other paths AGY makes there by itself (seen in a real run); anything else is refused
    workdir_forbidden: tuple            # names at the top of a work folder that AGY would read as settings or rules

    def settings_copy(self) -> dict:
        return copy.deepcopy(self.settings)


VERSIONS = {
    "1.5.3": AgyConstants(
        version="1.5.3",
        protocol_version=1,
        model_id="gemini-3.8-flash-high",
        argv_template=("acp", "--gemini-dir", "{gemini_dir}", "--sandbox", "--disable-telemetry"),
        shared_flag="--add-dir",
        env_keys=("PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME"),
        settings={"toolPermission": "request-review", "allowNonWorkspaceAccess": False, "enableTerminalSandbox": True,
                  "useG1Credits": False, "permissions": {"allow": [], "ask": [], "deny": []}},
        session_updates=frozenset({"agent_message_chunk", "agent_thought_chunk", "tool_call", "tool_call_update",
                                   "available_commands_update", "plan", "current_mode_update", "user_message_chunk",
                                   "config_option_update", "session_info_update"}),
        tool_kinds=frozenset({"read", "edit", "delete", "move", "search", "execute", "think", "fetch", "switch_mode",
                              "other"}),
        allow_option_kind="allow_once",
        reject_option_kind="reject_once",
        usage_fields=("inputTokens", "outputTokens", "cachedReadTokens", "cachedWriteTokens", "thoughtTokens",
                      "totalTokens"),
        usage_sum_fields=("inputTokens", "cachedReadTokens", "outputTokens"),
        home_forbidden=("GEMINI.md", "AGENTS.md", "config/hooks.json", "config/skills", "config/workflows",
                        "config/global_workflows", "config/plugins"),
        # AGY 1.5.3 makes these in a fresh --gemini-dir (the first real run found config/projects among them). Names only are
        # looked at, and a name that is in neither list is a name something else put there.
        home_created=("antigravity-cli", "config", "config/config.json", "config/mcp_config.json", "config/projects"),
        workdir_forbidden=(".agents", ".agent", ".gemini", "GEMINI.md", "AGENTS.md")),
}


def constants_for(version) -> AgyConstants | None:
    return VERSIONS.get(version) if isinstance(version, str) else None


def settings_bytes(consts: AgyConstants) -> bytes:
    """The bytes of ``antigravity-cli/settings.json`` as VBear writes it before every process, and as it compares it after a
    turn and after the process: one fixed encoding of ``consts.settings``."""
    return (json.dumps(consts.settings, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def _path(value, what: str) -> str:
    """``value`` as an absolute path of printable characters that UTF-8 can hold, short enough for a command line (ValueError)."""
    if not (isinstance(value, str) and value and os.path.isabs(value) and len(value) <= MAX_PATH):
        raise ValueError(f"{what}要是絕對路徑")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError(f"{what}的路徑含有控制字元")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{what}的路徑無法編碼") from exc
    return value


def argv_for(consts: AgyConstants, gemini_dir: str, shared: str | None = None) -> list[str]:
    """The arguments after the binary, from the table and nothing else: the stdio server, the chat's own settings folder, the
    sandbox, no telemetry; and the shared folder as one more folder when the employee has it (P43; without it the list is the same
    as without the feature). ValueError for a folder that cannot be one argument."""
    out = [part.format(gemini_dir=_path(gemini_dir, "聊天用的 AGY 設定資料夾")) if "{" in part else part
           for part in consts.argv_template]
    if shared is not None:
        out += [consts.shared_flag, _path(shared, "共用資料夾")]
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


def _session_id(value) -> str:
    if not (isinstance(value, str) and sp.UUID_RE.match(value)):
        raise ValueError("session id 的格式不對")
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


def _rpc(**members) -> dict:
    return {"jsonrpc": "2.0", **members}


def initialize_line(request_id) -> bytes:
    return _line(_rpc(id=_rid(request_id), method="initialize", params={
        "protocolVersion": 1,
        "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}))


def _session_params(cwd, system_prompt) -> dict:
    params = {"cwd": _path(cwd, "工作資料夾"), "mcpServers": []}
    if system_prompt is not None:
        params["_meta"] = {"antigravity": {"systemPrompt": {"append": _text(system_prompt, MAX_INSTRUCTIONS_BYTES)}}}
    return params


def session_new_line(request_id, *, cwd: str, system_prompt: str | None = None) -> bytes:
    return _line(_rpc(id=_rid(request_id), method="session/new", params=_session_params(cwd, system_prompt)))


def session_resume_line(request_id, session_id: str, *, cwd: str, system_prompt: str | None = None) -> bytes:
    params = {"sessionId": _session_id(session_id)}
    params.update(_session_params(cwd, system_prompt))
    return _line(_rpc(id=_rid(request_id), method="session/resume", params=params))


def set_model_line(request_id, session_id: str, consts: AgyConstants) -> bytes:
    """The model of the table, and no other: a chat uses one model (ADR 0012), set again for every new or resumed session."""
    return _line(_rpc(id=_rid(request_id), method="session/set_model",
                      params={"sessionId": _session_id(session_id), "modelId": consts.model_id}))


def prompt_line(request_id, session_id: str, text: str) -> bytes:
    return _line(_rpc(id=_rid(request_id), method="session/prompt", params={
        "sessionId": _session_id(session_id), "prompt": [{"type": "text", "text": _text(text)}]}))


def cancel_line(session_id: str) -> bytes:
    """``session/cancel`` is a notification: it has no id and is not answered with a result."""
    return _line(_rpc(method="session/cancel", params={"sessionId": _session_id(session_id)}))


def _option_id(value) -> str:
    if not (isinstance(value, str) and _ID_RE.match(value)):
        raise ValueError("選項的 id 格式不對")
    return value


def _options_of(options, consts: AgyConstants) -> dict[str, list]:
    """The option ids of the two kinds VBear may choose, from the agent's list: {kind: [optionId, ...]}. Other kinds, and
    entries that are not an object with a string kind, are left out."""
    found: dict[str, list] = {consts.allow_option_kind: [], consts.reject_option_kind: []}
    if isinstance(options, (list, tuple)):
        for option in options:
            if isinstance(option, dict) and option.get("kind") in found:
                found[option["kind"]].append(option.get("optionId"))
    return found


def options_ok(options, consts: AgyConstants) -> bool:
    """Whether the agent's options hold exactly one of kind allow-once and exactly one of kind reject-once, with plain ids
    (others may be there; they are never chosen). Anything else is not an option list VBear understands."""
    found = _options_of(options, consts)
    try:
        return all(len(ids) == 1 and _option_id(ids[0]) for ids in found.values())
    except ValueError:
        return False


def answer_line(request_id, options, decision: str, consts: AgyConstants | None = None) -> bytes:
    """The answer to a ``session/request_permission``, to the agent's request id as it came. ``decision`` is "allow" (the one
    option of kind allow-once), "deny" (the one of kind reject-once) or "cancelled" (the cancelled outcome). Never an option of any
    other kind: not "allow always", not "reject always", whatever the order of the list. "allow" needs exactly one option of each of
    the two kinds (ValueError otherwise: VBear does not answer yes to a list it does not understand); "deny" without exactly one
    reject-once option is answered as cancelled."""
    consts = consts or VERSIONS["1.5.3"]
    if not (isinstance(decision, str) and decision in DECISIONS):
        raise ValueError("只能回 allow、deny 或 cancelled")
    rid = _rid(request_id)
    found = _options_of(options, consts)
    if decision == "allow":
        if not options_ok(options, consts):
            raise ValueError("選項裡沒有剛好一個允許一次、一個拒絕一次，不能回允許")
        outcome = {"outcome": "selected", "optionId": found[consts.allow_option_kind][0]}
    elif decision == "deny" and len(found[consts.reject_option_kind]) == 1:
        outcome = {"outcome": "selected", "optionId": _option_id(found[consts.reject_option_kind][0])}
    else:
        outcome = {"outcome": "cancelled"}
    return _line(_rpc(id=rid, result={"outcome": outcome}))


def error_line(request_id, message: str, code: int = JSONRPC_METHOD_NOT_FOUND) -> bytes:
    """The answer to an agent request VBear does not take (anything but ``session/request_permission``)."""
    if not (isinstance(code, int) and not isinstance(code, bool)):
        raise ValueError("錯誤碼要是整數")
    return _line(_rpc(id=_rid(request_id), error={"code": code, "message": str(message)[:500]}))


# ---- what a turn costs ---------------------------------------------------------------------------------------------------

def estimate_usd(tokens) -> Decimal:
    """What a turn is counted as in the day's limit: the very rule of a Codex turn (``codex_chat_protocol.estimate_usd``):
    ``tokens`` / 1,000,000 x US$1.00 rounded up to the cent, at least US$0.01. ValueError when there is no usable count (the
    session then counts the turn's cap instead)."""
    return ccp.estimate_usd(tokens)


# ---- what VBear answers itself -------------------------------------------------------------------------------------------

Judgement = cp.Judgement

# No file change may touch these: a folder of that name at any depth (any case: a Mac's filesystem does not tell "A" from "a"),
# or a file of one of those names. They are the settings and rules AGY, the other tools and git read for themselves.
PROTECTED_DIRS = frozenset({".git", ".agents", ".agent", ".gemini", ".codex", ".claude"})
PROTECTED_FILES = frozenset({"gemini.md", "agents.md"})


def _protected_part(rel: str) -> str | None:
    """The first part of a relative path that is one of the protected names (as the list spells it), or None."""
    for part in rel.split(os.sep):
        folded = part.casefold()
        if folded in PROTECTED_DIRS or folded in PROTECTED_FILES:
            return folded if folded in PROTECTED_DIRS else {"gemini.md": "GEMINI.md", "agents.md": "AGENTS.md"}[folded]
    return None


def _hard_linked(where: str) -> bool:
    try:
        st = os.lstat(where)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_nlink > 1


def judge_file_change(paths, content, workdir: str, shared: str | None = None, max_bytes: int = MAX_CARD_BYTES) -> Judgement:
    """What VBear does with a request to edit, delete or move files (ADR 0012; AGY's file tools are not in its sandbox): every
    path, absolute and with its links followed, must be inside the role card's work folder (but not the folder itself), under none
    of ``.git``, ``.agents``, ``.agent``, ``.gemini``, ``.codex`` or ``.claude`` and not a file named GEMINI.md or AGENTS.md at any
    depth, and not an existing file with another hard link; the card (paths and ``content``, in bytes) must fit ``max_bytes``.
    Anything else is refused with no way to allow; the rest is asked.

    ``shared`` (P43, ADR 0009) is the shared folder of an employee the person switched it on for, or None: a second root with the
    same rules (and its own sentence on the card)."""
    if not isinstance(paths, (list, tuple)) or not paths:
        return Judgement("deny", "看不到這次要修改的檔案")
    if content is not None and not isinstance(content, str):
        return Judgement("deny", "看不到這次要修改的內容")
    work = os.path.realpath(workdir)
    root = os.path.realpath(shared) if isinstance(shared, str) and os.path.isabs(shared) else None
    size = len(content.encode("utf-8", "replace")) if content is not None else 0
    in_shared = False
    for path in paths:
        if not (isinstance(path, str) and os.path.isabs(path)):
            return Judgement("deny", "檔案路徑要是絕對路徑")
        where = cp._resolve(path, work)
        if where is None:
            return Judgement("deny", "檔案路徑的格式不對")
        size += len(path.encode("utf-8", "replace"))
        if root is not None and cp._inside(where, root) and not cp._inside(where, work):
            if where == root:
                return Judgement("deny", "這是共用資料夾本身，不是裡面的檔案")
            name = _protected_part(os.path.relpath(where, root))
            if name:
                return Judgement("deny", f"{name} 是 AI 工具或版本控制自己的設定檔或資料夾，聊天裡不能改")
            if _hard_linked(where):
                return Judgement("deny", "這個檔案有其他的硬連結（它同時是別處的檔案），為了不改到別處，不能改")
            in_shared = True
            continue
        if not cp._inside(where, work) or where == work:
            return Judgement("deny", "只能改員工自己的工作資料夾裡的檔案，這個路徑在資料夾以外"
                             if root is None else "只能改員工自己的工作資料夾或共用資料夾裡的檔案，這個路徑在資料夾以外")
        name = _protected_part(os.path.relpath(where, work))
        if name:
            return Judgement("deny", f"{name} 是 AI 工具或版本控制自己的設定檔或資料夾，聊天裡不能改")
        if _hard_linked(where):
            return Judgement("deny", "這個檔案有其他的硬連結（它同時是別處的檔案），為了不改到別處，不能改")
    if size > max_bytes:
        return Judgement("deny", "這次修改的內容太大，一張卡放不下")
    if in_shared:
        return Judgement("ask", "修改共用資料夾裡的檔案，其他打開共用資料夾的員工都讀得到，要你允許")
    return Judgement("ask", "修改員工工作資料夾裡的檔案，要你允許")


def judge_read(paths, workdir: str, shared: str | None = None) -> Judgement:
    """What VBear does with a request to read files: every path (relative ones are the work folder's), links followed, inside
    the work folder or the shared folder the employee has → VBear says yes itself; any path outside → a card that says the
    content goes to Google; no path, or one that is not usable as a path → refused."""
    if not isinstance(paths, (list, tuple)) or not paths:
        return Judgement("deny", "看不到要讀的檔案")
    work = os.path.realpath(workdir)
    root = os.path.realpath(shared) if isinstance(shared, str) and os.path.isabs(shared) else None
    outside = False
    for path in paths:
        where = cp._resolve(path, work)
        if where is None:
            return Judgement("deny", "檔案路徑的格式不對")
        if not (cp._inside(where, work) or (root is not None and cp._inside(where, root))):
            outside = True
    if outside:
        return Judgement("ask", "員工想讀工作資料夾外的檔案，讀到的內容會送到 Google")
    return Judgement("allow", "讀員工自己的工作資料夾（或共用資料夾）裡的檔案，VBear 自己允許")


# ---- reading what the agent prints ---------------------------------------------------------------------------------------

def _anomaly(label, fields) -> tuple[str, dict]:
    label = label if isinstance(label, str) and _METHOD_RE.match(label) else "?"
    return ("anomaly", {"event_type": label[:MAX_EVENT_TYPE],
                        "fields": sp.anomaly_fields(fields if isinstance(fields, (dict, list, tuple, set)) else ())})


def _is_int(value, low: int = 0, high: int = MAX_TOKENS) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _request_id(value):
    return value if (isinstance(value, int) and not isinstance(value, bool)) or \
        (isinstance(value, str) and _ID_RE.match(value)) else None


def _id_or_none(value):
    return value if isinstance(value, str) and _ID_RE.match(value) else None


def _text_or_none(value, limit: int):
    return value[:limit] if isinstance(value, str) else None


def _str_paths(items, key: str | None = None) -> list[str]:
    """The non-empty strings of ``items``, or of the ``key`` member of its objects."""
    out = []
    for item in items if isinstance(items, list) else []:
        value = item.get(key) if key and isinstance(item, dict) else item if not key else None
        if isinstance(value, str) and value:
            out.append(value)
    return out


_PATH_KEY_WORDS = ("path", "dest", "target", "source", "src", "dst", "file", "folder", "dir")
_PATTERN_KEY_WORDS = ("pattern", "glob", "include", "exclude")
# What a file call's raw input may hold besides places (compared in lower case): anything else is a possible place.
_NOT_A_PLACE = frozenset({"content", "contents", "text", "newtext", "oldtext", "description", "explanation", "reason", "summary",
                          "comment", "title", "overwrite", "bypasssandbox"})
_FILE_KINDS = ("edit", "delete", "move")


def _is_pattern_key(key) -> bool:
    return isinstance(key, str) and any(w in key.casefold() for w in _PATTERN_KEY_WORDS)


def _is_place_key(key, kind) -> bool:
    """Whether a member of a raw input may name a place. A file call (edit, delete, move) fails closed: every member that is not on
    the short list of ones that only describe or hold content is a possible place. For the other tools a member counts when its
    name says it holds a place (path, destination, target, source, file, folder...), unless it is named like a pattern."""
    if not isinstance(key, str):
        return False
    folded = key.casefold()
    if key == "Path":
        return True
    if kind in _FILE_KINDS:
        return folded not in _NOT_A_PLACE
    return any(w in folded for w in _PATH_KEY_WORDS) and not any(w in folded for w in ("content", "text")) and not _is_pattern_key(key)


def _raw_paths(raw, kind=None) -> list[str]:
    """Every place the raw input of a tool call names, without repeats: ``Path`` first, then the other members that may hold a place
    (see ``_is_place_key``) in the order of their names. A value is a string or a list of strings."""
    if not isinstance(raw, dict):
        return []
    out = []
    keys = sorted((k for k in raw if isinstance(k, str) and k != "Path"), key=str.casefold)
    for key in (["Path"] if "Path" in raw else []) + keys:
        if not _is_place_key(key, kind):
            continue
        value = raw[key]
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and item and item not in out:
                out.append(item)
    return out


def _pattern_names_a_path(raw, kind) -> bool:
    """Whether a read or a search holds, in a member that is not read as a place (a pattern, a query, a member named like a pattern
    even if its name also says path), a string that is more than a bare name: ``/``, ``..`` or ``~``. VBear's own yes covers a bare
    name only."""
    if not isinstance(raw, dict):
        return False
    return any(not _is_place_key(key, kind) and not all(not cp._pattern_names_a_path(t) for t in _strings_of(value))
               for key, value in raw.items())


def _unreadable_member(raw, kind) -> bool:
    """Whether a file call holds a member that is not on the short list and whose value is neither a string, a list of strings nor a
    plain scalar: it might hold a place VBear cannot read, so the call is refused."""
    if kind not in _FILE_KINDS:
        return False
    for key, value in raw.items():
        if not isinstance(key, str):
            return True
        if key.casefold() in _NOT_A_PLACE:
            continue
        if isinstance(value, dict) or (isinstance(value, list) and not all(isinstance(i, str) for i in value)):
            return True
    return False


def _paths_of(raw, locations, kind=None) -> list[str]:
    """Every path a tool call names, in the order of the raw input first and the locations after, without repeats."""
    out = _raw_paths(raw, kind)
    for path in _str_paths(locations, "path"):
        if path not in out:
            out.append(path)
    return out


def _diffs_of(content) -> list[dict]:
    out = []
    for block in content[:20] if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "diff" and isinstance(block.get("path"), str):
            out.append({"path": block["path"][:MAX_PATH], "old_text": _text_or_none(block.get("oldText"), MAX_OUTPUT_TEXT),
                        "new_text": _text_or_none(block.get("newText"), MAX_OUTPUT_TEXT)})
    return out


def _output_of(content) -> str | None:
    texts = []
    for block in content if isinstance(content, list) else []:
        inner = block.get("content") if isinstance(block, dict) and block.get("type") == "content" else None
        if isinstance(inner, dict) and inner.get("type") == "text" and isinstance(inner.get("text"), str):
            texts.append(inner["text"])
    return "\n".join(texts)[:MAX_OUTPUT_TEXT] if texts else None


def _clean_options(options) -> list[dict]:
    """The options as VBear keeps them for the answer: id and kind of each, nothing else (a name is the agent's wording)."""
    out = []
    for option in options[:16] if isinstance(options, list) else []:
        if isinstance(option, dict) and isinstance(option.get("kind"), str) and len(option["kind"]) <= 32 \
                and isinstance(option.get("optionId"), str) and len(option["optionId"]) <= 128:
            out.append({"optionId": option["optionId"], "kind": option["kind"]})
    return out


def _file_content(raw, diffs) -> str | None:
    """The text a file card has to hold, for its size: the raw input's content or the diff's texts, whichever is larger."""
    given = raw.get("Content") if isinstance(raw.get("Content"), str) else None
    shown = "".join((d["old_text"] or "") + (d["new_text"] or "") for d in diffs) if diffs else None
    if given is None or (shown is not None and len(shown.encode("utf-8", "replace")) > len(given.encode("utf-8", "replace"))):
        return shown
    return given


# Members of a tool call's raw input that only describe it: a change in them after a yes is not a different call.
_DESCRIBING = frozenset({"description", "explanation", "reason", "summary", "comment", "title"})


def _strings_of(value):
    """Every string in a value of JSON, nested ones included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_of(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings_of(item)


_STOP_REASONS = frozenset({"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"})
_RUNNING_FREE = (None, "pending", "failed")           # a call in one of these statuses has not run (or did not)
_CATEGORY = {"execute": "command", "edit": "file_change", "delete": "file_change", "move": "file_change", "read": "read",
             "search": "read"}


class AgyTracker:
    """One ``agy acp`` process and its one session. ``on_message`` turns one parsed stdout line into facts, (kind, data) pairs:

      initialized       {load_session}                          initialize was answered with what VBear needs
      session_ready     {session_id, resumed}                   session/new or session/resume was answered as VBear asked
      model_set         {model}                                 session/set_model answered ``{}``: the session may be prompted
      invalid_model     {}                                      the agent's model list lacks the model of the table
      request_failed    {kind, code, auth_required}             an error answer to a request VBear wrote (no message kept)
      commands          {count}                                 available_commands_update: how many, never their names
      delta             {text}                                  a piece of the reply (shown, not kept)
      reply             {text}                                  the reply so far, whole (before a tool call and at the end of a turn)
      tool_call         {call_id, tool_kind, title, status, summary}      a tool call seen for the first time
      tool_result       {call_id, status, exit_code, output}    a tool call that completed or failed
      permission_request {request_id, call_id, tool_kind, kind, action, why, options, title, bypass, ...}
                        kind "command": command; kind "file_change": paths, operation, content, diffs; kind "read": paths;
                        action "ask" (a card), "allow" (VBear says yes itself: a read inside the work folder) or "deny" (VBear
                        says no itself, no card). The session answers every one with ``answer_line`` and tells the tracker (``answered``).
      turn_completed    {stop_reason, tokens, usage_problem, open_calls}   tokens None when the usage was unusable
      unknown_request   {request_id, method, refused}           to be answered with ``error_line``
      anomaly           {event_type, fields}                    names only, never a value
      violation         {message, request_id}                   the session must stop; nothing more is read; a request_id is
                                                                 to be answered with ``error_line``

    The session says which requests it wrote (``expect``), where a turn begins (``begin_turn``) and what it answered to each request
    of the agent (``answered``). Nothing from ``initialize``, the plan's name, the sign-in methods, the thoughts or the commands'
    names is ever put in a fact: only that they were as expected, or how many."""

    def __init__(self, consts: AgyConstants, *, workdir: str, shared: str | None = None, session_id: str | None = None,
                 resumed: bool = False):
        self.c = consts
        self.workdir = os.path.realpath(workdir)
        self.shared = os.path.realpath(shared) if isinstance(shared, str) and os.path.isabs(shared) else None
        self.session_id = _session_id(session_id) if session_id is not None else None
        self.resumed = bool(resumed)
        if self.resumed and self.session_id is None:
            raise ValueError("續接要有 session id")
        self.pending: dict = {}                 # request id -> kind
        self.requests: dict = {}                # the agent's request id -> {"call_id", "action", "options"}, until answered
        self.calls: dict = {}                   # this turn's tool calls by id
        self.stopped = False
        self.ready = False                      # the model is set: the session may be prompted
        self.thoughts = 0                       # agent_thought_chunk seen (counted, never kept)
        self._early: str | None = None          # a session id seen before the answer to session/new
        self._reply: list[str] = []

    # -- what the session tells it

    _KINDS = frozenset({"initialize", "session_new", "session_resume", "set_model", "prompt"})

    def expect(self, request_id, kind: str) -> None:
        if kind not in self._KINDS:
            raise ValueError("不認得的請求種類")
        if kind == "session_new" and self.resumed:
            raise ValueError("這個程序要續接對話，不能開新的")
        if kind == "session_resume" and not self.resumed:
            raise ValueError("沒有要續接的對話")
        if kind == "set_model" and self.session_id is None:
            raise ValueError("還沒有對話，不能設模型")
        if kind == "prompt" and not self.ready:
            raise ValueError("模型還沒設好，不能送訊息")
        self.pending[_rid(request_id)] = kind

    def begin_turn(self) -> None:
        self._reply = []

    def answered(self, request_id, decision: str) -> None:
        """The session answered the agent's request ``request_id`` with ``decision`` ("allow", "deny" or "cancelled"). An "allow" is
        what lets the call run without being a violation; it cannot be given to a request VBear refused itself."""
        if not (isinstance(decision, str) and decision in DECISIONS):
            raise ValueError("只能回 allow、deny 或 cancelled")
        rec = self.requests.get(request_id) if _request_id(request_id) is not None else None
        if rec is None:
            raise ValueError("沒有這個還沒回答的請求")
        if decision == "allow" and rec["action"] not in ("ask", "allow"):
            raise ValueError("VBear 已經拒絕的請求不能回允許")
        del self.requests[request_id]
        call = self.calls.get(rec["call_id"])
        if call is not None:
            call["approved"] = decision == "allow"

    def open_requests(self) -> list:
        """The agent's requests that have no answer yet (the session answers them as cancelled when it stops a turn)."""
        return list(self.requests)

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
    def _violation(message: str, request_id=None) -> list[tuple[str, dict]]:
        return [("violation", {"message": message, "request_id": request_id})]

    def _on_message(self, msg):
        if not isinstance(msg, dict):
            return [_anomaly("?", ())]
        method = msg.get("method")
        if isinstance(method, str):
            params = msg.get("params")
            params = params if isinstance(params, dict) else {}
            if "id" in msg:
                return self._on_request(msg["id"], method, params)
            return self._on_notification(method, params, msg)
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
            text = err.get("message") if isinstance(err, dict) else None
            auth = isinstance(text, str) and "authentication required" in text[:500].casefold()
            return [("request_failed", {"kind": kind, "code": code if _is_int(code, -10 ** 9, 10 ** 9) else None,
                                        "auth_required": auth})]
        result = msg.get("result")
        return getattr(self, "_answer_" + kind)(result if isinstance(result, dict) else None)

    def _answer_initialize(self, result):
        if not result or result.get("protocolVersion") != self.c.protocol_version \
                or isinstance(result.get("protocolVersion"), bool):
            return self._violation("AGY 說的通訊版本不是 VBear 認得的版本")
        caps = result.get("agentCapabilities")
        sessions = caps.get("sessionCapabilities") if isinstance(caps, dict) else None
        if not (isinstance(sessions, dict) and "resume" in sessions):
            return self._violation("這個 AGY 不能續接對話，聊天不能用")
        return [("initialized", {"load_session": caps.get("loadSession") is True})]

    def _has_model(self, models) -> bool:
        available = models.get("availableModels") if isinstance(models, dict) else None
        return isinstance(available, list) and any(isinstance(m, dict) and m.get("modelId") == self.c.model_id
                                                   for m in available)

    def _session_answer(self, kind: str, result):
        resumed = kind == "session_resume"
        result = result or {}
        sid = result.get("sessionId")
        if resumed:
            if sid is not None and sid != self.session_id:
                return self._violation("AGY 續接的不是 VBear 指定的對話")
            sid = self.session_id
        else:
            if not (isinstance(sid, str) and sp.UUID_RE.match(sid)):
                return self._violation("AGY 回覆的對話代號格式不對")
            if self._early is not None and self._early != sid:
                return self._violation("AGY 通知的對話和它回覆的不是同一個")
        if "modes" in result or not resumed:
            modes = result.get("modes")
            if not (isinstance(modes, dict) and modes.get("currentModeId") == "default"):
                return self._violation("AGY 的模式不是 default（每次都問）")
        if ("models" in result or not resumed) and not self._has_model(result.get("models")):
            return [("invalid_model", {})]
        self.session_id = sid
        return [("session_ready", {"session_id": sid, "resumed": resumed})]

    def _answer_session_new(self, result):
        return self._session_answer("session_new", result)

    def _answer_session_resume(self, result):
        return self._session_answer("session_resume", result)

    def _answer_set_model(self, result):
        if result != {}:
            return self._violation("AGY 沒有照 VBear 的要求設定模型")
        self.ready = True
        return [("model_set", {"model": self.c.model_id})]

    def _usage(self, usage) -> tuple[int | None, str | None]:
        """(the turn's tokens, None) when ``usage`` has every field it must, all whole numbers in range, and ``totalTokens`` is the sum
        of the three that make it (measured); else (None, why): "missing", "invalid" or "mismatch"."""
        if not isinstance(usage, dict) or "totalTokens" not in usage or any(k not in usage for k in self.c.usage_sum_fields):
            return None, "missing"
        if any(k in usage and not _is_int(usage[k]) for k in self.c.usage_fields):
            return None, "invalid"
        if sum(usage[k] for k in self.c.usage_sum_fields) != usage["totalTokens"]:
            return None, "mismatch"
        return usage["totalTokens"], None

    def _answer_prompt(self, result):
        result = result or {}
        out = self._flush_reply()
        reason = result.get("stopReason")
        tokens, problem = self._usage(result.get("usage"))
        open_calls = sum(1 for c in self.calls.values() if not c["done"])
        self.calls.clear()
        self.requests.clear()
        out.append(("turn_completed", {"stop_reason": reason if reason in _STOP_REASONS else "?", "tokens": tokens,
                                       "usage_problem": problem, "open_calls": open_calls}))
        return out

    def _flush_reply(self) -> list:
        if not self._reply:
            return []
        text = "".join(self._reply)[:MAX_REPLY_TEXT]
        self._reply = []
        return [("reply", {"text": text})]

    # -- notifications

    def _same_session(self, sid) -> bool | None:
        """True when ``sid`` is this chat's session, False when it is another, None when it is not a session id at all."""
        if not isinstance(sid, str):
            return None
        if self.session_id is not None:
            return sid == self.session_id
        if self._early is None:
            self._early = sid
        return sid == self._early

    def _on_notification(self, method: str, params: dict, msg: dict):
        if method != "session/update":
            return [_anomaly(method, params)]
        mine = self._same_session(params.get("sessionId"))
        if mine is False:
            return self._violation("AGY 回報了別的對話的事件")
        update = params.get("update")
        kind = update.get("sessionUpdate") if isinstance(update, dict) else None
        if mine is None or not isinstance(kind, str):
            return [_anomaly("session/update", params)]
        if kind not in self.c.session_updates:
            return [_anomaly(kind, update)]
        return getattr(self, "_u_" + kind)(update)

    def _u_agent_message_chunk(self, update):
        content = update.get("content")
        text = content.get("text") if isinstance(content, dict) and content.get("type") == "text" else None
        if not isinstance(text, str):
            return [_anomaly("agent_message_chunk", update)]
        text = text[:MAX_REPLY_TEXT]
        self._reply.append(text)
        return [("delta", {"text": text})]

    def _u_agent_thought_chunk(self, update):
        self.thoughts += 1
        return []

    def _u_available_commands_update(self, update):
        commands = update.get("availableCommands")
        if not isinstance(commands, list):
            return [_anomaly("available_commands_update", update)]
        return [("commands", {"count": len(commands)})]

    def _u_plan(self, update):
        return []

    def _u_user_message_chunk(self, update):
        return []                                         # the echo of VBear's own message: nothing in it is kept

    def _u_config_option_update(self, update):
        return []                                         # AGY telling the options it has (model, mode): nothing in it is kept

    def _u_session_info_update(self, update):
        return []                                         # AGY telling about the session (a title...): nothing in it is kept

    def _u_current_mode_update(self, update):
        if update.get("currentModeId") != "default":
            return self._violation("AGY 把模式換成了 default 以外的模式")
        return []

    def _u_tool_call(self, update):
        return self._tool_update(update, "tool_call")

    def _u_tool_call_update(self, update):
        return self._tool_update(update, "tool_call_update")

    # -- tool calls

    def _merge(self, data: dict):
        """Folds what a notification or a request says about a tool call into the call's record: (call id, record, new). The id
        is None when the call has none VBear can follow."""
        cid = _id_or_none(data.get("toolCallId"))
        if cid is None:
            return None, None, False
        new = cid not in self.calls
        rec = self.calls.setdefault(cid, {"kind": None, "status": None, "raw": {}, "paths": [], "locations": [], "content": [],
                                          "title": "", "done": False, "approved": False, "asked": None})
        if isinstance(data.get("kind"), str):
            rec["kind"] = data["kind"]
        if isinstance(data.get("status"), str):
            rec["status"] = data["status"]
        if isinstance(data.get("title"), str):
            rec["title"] = data["title"][:500]
        if isinstance(data.get("rawInput"), dict):
            rec["raw"] = data["rawInput"]
        if isinstance(data.get("locations"), list):
            rec["locations"] = data["locations"]
        if isinstance(data.get("content"), list):
            rec["content"] = data["content"]
        rec["paths"] = _paths_of(rec["raw"], rec["locations"], rec["kind"])
        return cid, rec, new

    def _summary(self, rec) -> str:
        raw = rec["raw"]
        if rec["kind"] == "execute" and isinstance(raw.get("CommandLine"), str):
            return raw["CommandLine"][:2000]
        if rec["paths"]:
            return rec["paths"][0][:2000]
        return rec["title"][:2000]

    def _tool_fact(self, cid, rec) -> tuple[str, dict]:
        kind = rec["kind"]
        return ("tool_call", {"call_id": cid, "tool_kind": kind if kind in self.c.tool_kinds else "?", "title": rec["title"],
                              "status": rec["status"] if rec["status"] in (None, "pending", "in_progress", "completed", "failed")
                              else "?", "summary": self._summary(rec)})

    @staticmethod
    def _signature(rec):
        """What a yes was given to: everything the raw input says but a short list of fields that only describe (so a field added or
        changed after the yes is a different call), and the paths."""
        raw = {k: v for k, v in rec["raw"].items() if not (isinstance(k, str) and k.casefold() in _DESCRIBING)}
        return (rec["kind"], json.dumps(raw, sort_keys=True, default=repr), tuple(rec["paths"]))

    @staticmethod
    def _bypasses(raw) -> bool:
        return any(isinstance(k, str) and k.casefold() == "bypasssandbox" and v is not False for k, v in raw.items())

    def _search_problem(self, rec) -> str | None:
        """Why a search that ran without a request is a violation, or None (the way a Claude chat lets a Glob or a Grep pass): every
        string that is not a place is a bare name (no ``/``, ``..`` or ``~``), every place it names (a member named like a path, and
        the locations) is an absolute path with no ``~``, ``{``, ``*``, ``?`` or ``[`` and is inside the folders, and the work folder
        has no link to the outside. A member named like a pattern is always a pattern, never a place."""
        if _pattern_names_a_path(rec["raw"], "search"):
            return "AGY 沒有問就搜尋，而搜尋的內容帶有路徑（/、.. 或 ~），可能讀到工作資料夾以外"
        for place in rec["paths"]:
            if not os.path.isabs(place) or any(c in place for c in "~{*?["):
                return "AGY 沒有問就搜尋，而搜尋的地方不是一個明確的絕對路徑，可能在工作資料夾以外"
        if cp._outward_link(self.workdir):
            return "AGY 沒有問就搜尋，而工作資料夾裡有指向外面的連結"
        if rec["paths"] and judge_read(rec["paths"], self.workdir, self.shared).action != "allow":
            return "AGY 沒有經過 VBear 的允許就搜尋了工作資料夾以外的地方"
        return None

    def _running_problem(self, rec) -> str | None:
        """Why a call that is running (or that was allowed and changed) is a violation, or None. A read needs no yes of VBear's when it
        stays in the work folder (and the shared folder the employee has); so does a search that passes ``_search_problem``; anything else
        needs the "allow once" VBear answered, and what runs must be what was allowed."""
        if rec["approved"]:
            if self._bypasses(rec["raw"]):
                return "AGY 在你允許之後要求在沙盒外執行"
            if rec["asked"] is not None and self._signature(rec) != rec["asked"]:
                return "AGY 做的和你允許時看到的不同"
        if rec["status"] in _RUNNING_FREE or rec["approved"]:
            return None
        kind = rec["kind"]
        if kind == "search":
            return self._search_problem(rec)
        if kind == "read":
            if _pattern_names_a_path(rec["raw"], "read"):
                return "AGY 沒有問就讀檔，而讀的內容帶有路徑（/、.. 或 ~），可能讀到工作資料夾以外"
            if not rec["paths"]:
                return "AGY 沒有問就讀檔，而且看不出讀的是哪個檔案"
            if judge_read(rec["paths"], self.workdir, self.shared).action == "allow":
                return None
            return "AGY 沒有經過 VBear 的允許就讀了工作資料夾以外的檔案"
        what = "執行了指令" if kind == "execute" else "修改了檔案" if kind in ("edit", "delete", "move") else \
            "連了網" if kind == "fetch" else "用了工具"
        return f"AGY 沒有經過 VBear 的允許就{what}"

    def _tool_update(self, update: dict, label: str):
        cid, rec, new = self._merge(update)
        if cid is None:
            return [_anomaly(label, update)]
        out = self._flush_reply() if new else []
        if new:
            out.append(self._tool_fact(cid, rec))
        problem = self._running_problem(rec)
        if problem:
            return self._violation(problem)
        if rec["status"] in ("completed", "failed") and not rec["done"]:
            rec["done"] = True
            raw_out = update.get("rawOutput")
            code = raw_out.get("exit_code") if isinstance(raw_out, dict) else None
            out.append(("tool_result", {"call_id": cid, "status": rec["status"],
                                        "exit_code": code if _is_int(code, -10 ** 6, 10 ** 6) else None,
                                        "output": _output_of(update.get("content"))}))
        return out

    # -- requests from the agent

    def _on_request(self, rid, method: str, params: dict):
        rid = _request_id(rid)
        if rid is None:
            return [_anomaly(method, params)]
        if method == "session/request_permission":
            return self._on_permission(rid, params)
        return [("unknown_request", {"request_id": rid, "method": method if _METHOD_RE.match(method) else "?",
                                     "refused": True}),
                _anomaly(method, ())]

    def _decide(self, rec, raw: dict, options) -> tuple[str, str, dict]:
        """(action, why, the extra fields of the fact) for a permission request, in the order of the design: BypassSandbox, the net,
        a list of options VBear does not understand, then by the kind of tool."""
        kind = rec["kind"]
        category = _CATEGORY.get(kind, "other")
        extra: dict = {"kind": category}
        bypass = any(isinstance(k, str) and k.casefold() == "bypasssandbox" and v is not False for k, v in raw.items())
        extra["bypass"] = bypass
        if category == "command":
            command = raw.get("CommandLine")
            extra["command"] = _text_or_none(command, MAX_OUTPUT_TEXT)
        elif category == "file_change":
            diffs = _diffs_of(rec["content"])
            extra.update(paths=[], operation=None, content=_text_or_none(raw.get("Content"), MAX_OUTPUT_TEXT), diffs=diffs)
        elif category == "read":
            extra["paths"] = rec["paths"][:20]
        if bypass:
            return "deny", REASON_BYPASS, extra
        if kind == "fetch" or any(isinstance(k, str) and k.casefold() in ("url", "urls", "uri") for k in raw):
            return "deny", REASON_NETWORK, extra
        if not options_ok(options, self.c):
            return "deny", REASON_OPTIONS, extra
        if category == "command":
            command = raw.get("CommandLine")
            if not (isinstance(command, str) and command.strip()) or "\0" in command:
                return "deny", "請求沒有給要執行的指令", extra
            if len(command.encode("utf-8", "replace")) > MAX_CARD_BYTES:
                return "deny", "這個指令太長，一張卡放不下", extra
            return "ask", "每個指令都要你允許才會執行（在 AGY 的沙盒裡）", extra
        if category == "file_change":
            return self._decide_file(rec, raw, extra)
        if category == "read":
            verdict = judge_read(rec["paths"], self.workdir, self.shared)
            if verdict.action == "allow" and _pattern_names_a_path(raw, kind):
                return "ask", "搜尋或讀取的內容帶有路徑（/、.. 或 ~），可能讀到資料夾以外，要你允許", extra
            if verdict.action == "allow" and kind == "search" and cp._outward_link(self.workdir):
                return "ask", "員工的工作資料夾裡有指向資料夾以外的連結，搜尋可能讀到外面的檔案，要你允許", extra
            return verdict.action, verdict.reason, extra
        return "deny", "VBear 不開放這種工具", extra

    def _decide_file(self, rec, raw: dict, extra: dict):
        diffs = extra["diffs"]
        raw_path = raw.get("Path")
        paths = _raw_paths(raw, rec["kind"])            # every place the call names: a move names two
        if _unreadable_member(raw, rec["kind"]):
            return "deny", "請求裡有 VBear 讀不懂的欄位，可能是檔案路徑，不能允許", extra
        located = _str_paths(rec["locations"], "path")
        if not (isinstance(raw_path, str) and raw_path):
            return "deny", "看不到這次要修改的檔案路徑", extra
        extra["paths"] = paths
        if not located or len(located) != len(rec["locations"]):
            return "deny", "看不到這次要修改的檔案路徑", extra
        if raw_path not in located or not set(located) <= set(paths) or any(d["path"] not in paths for d in diffs):
            return "deny", "請求裡幾個地方寫的檔案路徑不一致", extra
        kind = rec["kind"]
        if kind == "move" and len(paths) < 2:
            return "deny", "看不到要把檔案移到哪裡，不能允許", extra
        if kind == "edit":
            if diffs:
                extra["operation"] = "add" if diffs[0]["old_text"] is None else "modify"
            else:
                extra["operation"] = "modify" if os.path.lexists(raw_path) else "add"
        else:
            extra["operation"] = {"delete": "delete", "move": "move"}[kind]
        verdict = judge_file_change(paths, _file_content(raw, diffs), self.workdir, self.shared)
        return verdict.action, verdict.reason, extra

    def _on_permission(self, rid, params: dict):
        if self._same_session(params.get("sessionId")) is not True or self.session_id is None:
            return self._violation("AGY 的請求不是這個對話的", request_id=rid)
        tool = params.get("toolCall")
        options = params.get("options")
        shown = _clean_options(options)
        base = {"request_id": rid, "call_id": None, "tool_kind": "?", "kind": "other", "title": "", "options": shown,
                "bypass": False}
        if not isinstance(tool, dict):
            return [("permission_request", {**base, "action": "deny", "why": "請求沒有指出是哪一個工具呼叫"})]
        out = []
        cid, rec, new = self._merge(tool)
        if cid is None:
            return [("permission_request", {**base, "action": "deny", "why": "請求沒有指出是哪一個工具呼叫"})]
        if new:
            out += self._flush_reply()
            out.append(self._tool_fact(cid, rec))
        rec["approved"] = False                         # an older yes does not cover what this request asks
        raw = rec["raw"]                                # a request carries only what changed: the rest was said by the tool call
        action, why, extra = self._decide(rec, raw, options)
        kind = rec["kind"]
        data = {**base, "call_id": cid, "tool_kind": kind if kind in self.c.tool_kinds else "?", "title": rec["title"],
                "action": action, "why": why, **extra}
        if extra["kind"] == "other" and why == "VBear 不開放這種工具":
            out.append(_anomaly(kind if isinstance(kind, str) else "?", raw))
        rec["asked"] = self._signature(rec) if action in ("ask", "allow") else None
        self.requests[rid] = {"call_id": cid, "action": action, "options": shown}
        out.append(("permission_request", data))
        return out
