"""What VBear keeps of a chat with a role card (P36). The daemon is the only writer.

  <state>/chats/<chat_id>/chat.json       0600, written once: {v: 2, id, profile_id, created_at, engine[, claude_session_id]}
                                          (a version 1 file, without ``engine``, is a Claude chat)
  <state>/chats/<chat_id>/events.jsonl    0600, append-only: one event per line, {seq, at, kind, ...}, fsync'd
  <state>/chat-spend/<chat_id>.json       0600: what a deleted chat cost in its last days, for the day's limit
  <state>/chat-prompt/<chat_id>.json      0600: the fingerprint of the system prompt a chat's session was started with
                                          (P42-6; VBear's own state, not a field of the record; gone with the chat)
  <state>/chat-work/<hash of the card>/   0700: the role card's work folder (the CLI's cwd), kept when a chat goes

Every event kind has a fixed set of fields (``KINDS``); a record that does not fit is refused before anything is
written, and a file that does not read back cleanly (a cut last line, a field that does not belong, a sequence that
skips) is reported and never appended to. The text of a message, a reply, a tool's result and a card's input goes
through scan/document.redact before it is written and is cut to a fixed length; the live chat shows what the CLI
printed, the record keeps the masked form.

A turn costs what the CLI reported for it, or, when it reported nothing usable (stopped, timed out, a daemon that
stopped mid-turn), the turn's cap; while it runs it counts at its cap. Those turns are what the day's limit counts,
together with the meetings and the staffing meetings (``spend_kind``, ``day_spent``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from .. import config as cfg, meetings as mt, strictjson
from ..numbers import finite_real
from ..scan.document import redact, redact_value
from . import chat_engines, chat_protocol as cp

CHATS = "chats"
SPEND = "chat-spend"
PROMPT = "chat-prompt"
WORK = "chat-work"
CHAT_JSON = "chat.json"
EVENTS = "events.jsonl"
CHAT_RE = re.compile(r"^c-[0-9a-f]{16}\Z")
CARD_RE = re.compile(r"^k-[0-9a-f]{16}\Z")
DISPATCH_RE = re.compile(r"^d-[0-9a-f]{12}\Z")
MAX_DISPATCH_STEP = 4                  # vbear/chief.py MAX_STEPS: a dispatch has at most this many steps
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")      # agent_profiles.VALID_PROFILE_ID_RE
UUID_RE = cp.UUID_RE

MAX_CHATS = 200
MAX_EVENTS_BYTES = 8 << 20             # one chat's events file
RESERVE_BYTES = 64 << 10               # kept for the records that close a turn or a process
MAX_LINE = 1 << 20
# The chat's engine is set when it is created from its role card's AI tool; the engines are the rows of chat_engines.TABLE.
MAX_USER = cp.MAX_TEXT_BYTES           # a person's message, refused above (the daemon checks first)
MAX_REPLY = 64_000                     # characters of a reply kept
MAX_EXCERPT = 4_000                    # characters of a tool's result, a card's field, a summary kept
MAX_SHORT = 200
SPEND_KEEP = 3 * 86400                 # a deleted chat's turns kept this long for the day's limit
DEFAULT_PER_TURN = Decimal("0.50")
PER_TURN_CAP = Decimal("5")
EVENT_LIMITS = strictjson.Limits(MAX_LINE, 100_000, 16, None)


def usd(value: Decimal) -> str:
    """A cost as stored: exact (never rounded down, unlike meetings.fmt), and only when that would pass the
    field's 40 characters rounded up to 12 decimals."""
    text = format(value.normalize(), "f")
    if len(text) > 40:
        text = format(value.quantize(Decimal("1e-12"), rounding=ROUND_CEILING).normalize(), "f")
    return text


class ChatStoreError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# ---- the fields of each event ------------------------------------------------------------------------------------

def _turn(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 1_000_000


def _short(v):
    return isinstance(v, str) and 0 < len(v) <= MAX_SHORT


def _short_or_none(v):
    return v is None or _short(v)


def _money_text(v):
    return isinstance(v, str) and mt.money(v) is not None


def _bool(v):
    return isinstance(v, bool)


def _text(limit):
    return lambda v: isinstance(v, str) and len(v) <= limit


def _total(v):
    return v is None or (finite_real(v) is not None and v >= 0)


def _one_of(*values):
    return lambda v: v in values


def _fields(v):
    return isinstance(v, list) and len(v) <= 64 and all(isinstance(x, str) and len(x) <= 64 for x in v)


def _input(v):
    return isinstance(v, dict) and len(v) <= 64 and all(isinstance(k, str) and len(k) <= 64 for k in v)


def _returncode(v):
    return v is None or (isinstance(v, int) and not isinstance(v, bool) and -255 <= v <= 255)


def origin_ok(v) -> bool:
    """The origin of a message VBear sent for a dispatch (P40-3): exactly the dispatch's id and the number of the step."""
    return (isinstance(v, dict) and set(v) == {"dispatch", "step"} and isinstance(v["dispatch"], str)
            and bool(DISPATCH_RE.match(v["dispatch"])) and type(v["step"]) is int and 1 <= v["step"] <= MAX_DISPATCH_STEP)


def _turn_or_none(v):
    return v is None or _turn(v)


_REASONS = ("result", "stopped", "timeout", "process_exit", "violation", "daemon_restart", "error", "not_sent",
            "limit")


def _int_in(low: int, high: int):
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and low <= v <= high


def _int_or_none(low: int, high: int):
    return lambda v: v is None or (isinstance(v, int) and not isinstance(v, bool) and low <= v <= high)


MAX_TOKENS = 10 ** 12

# kind -> {field: check}; ``_MASK`` names the text fields that are masked and cut, ``_ESSENTIAL`` the kinds that may
# use the reserve at the end of a full file (so that a turn can always be closed at its cost).
KINDS = {
    "chat_created": {"profile_id": lambda v: isinstance(v, str) and bool(PROFILE_ID_RE.match(v))},
    "user_message": {"turn": _turn, "text": lambda v: isinstance(v, str) and 0 < len(v.encode("utf-8", "surrogatepass")) <= MAX_USER},
    "turn_started": {"turn": _turn, "cap_usd": _money_text},
    "process_started": {"mode": _one_of("new", "resume"), "budget_usd": _money_text, "instructions": _bool},
    # the CLI's version is ``claude_code_version`` in a Claude chat and in the records of before v0.13.0, and ``cli_version``
    # in a Codex chat (exactly one of the two; see _ALTERNATIVES)
    "session_ready": {"permission_mode": _short, "model": _short},
    "reply": {"turn": _turn, "text": _text(MAX_REPLY), "truncated": _bool},
    "tool_call": {"turn": _turn, "tool_use_id": _short, "tool": _short, "summary": _text(MAX_EXCERPT)},
    "tool_result": {"turn": _turn, "tool_use_id": _short, "tool": _short, "is_error": _bool,
                    "text": _text(MAX_EXCERPT), "truncated": _bool, "source": _short},
    "card": {"turn": _turn, "card_id": lambda v: isinstance(v, str) and bool(CARD_RE.match(v)), "tool": _short,
             "input": _input, "editable": _short_or_none, "state": _one_of("asked"), "reason": _text(MAX_SHORT)},
    "card_decision": {"turn": _turn, "card_id": lambda v: isinstance(v, str) and bool(CARD_RE.match(v)),
                      "decision": _one_of("allow", "deny", "modify", "expired", "cancelled", "refused"),
                      "value": lambda v: v is None or (isinstance(v, str) and len(v) <= MAX_EXCERPT)},
    "auto_allowed": {"turn": _turn, "tool_use_id": _short_or_none, "tool": _short, "summary": _text(MAX_EXCERPT),
                     "reason": _text(MAX_SHORT)},
    "denied": {"turn": _turn, "tool_use_id": _short_or_none, "tool": _short, "summary": _text(MAX_EXCERPT),
               "reason": _text(MAX_SHORT), "by": _one_of("vbear", "cli")},
    "turn_ended": {"turn": _turn, "cost_usd": _money_text, "reported": _bool, "total_usd": _total,
                   "reason": _one_of(*_REASONS), "subtype": _short_or_none, "is_error": _bool},
    "process_ended": {"reason": _short, "returncode": _returncode},
    "anomaly": {"event_type": _short, "fields": _fields},
    "error": {"turn": _turn_or_none, "message": _text(MAX_EXCERPT)},
    # a Codex chat (P38): the thread VBear resumes, the tokens counted so far in it, the plan's use as Codex reports it
    # (the numbers only), and the words VBear sent in place of a card the person changed
    "session_bound": {"thread_id": lambda v: isinstance(v, str) and bool(UUID_RE.match(v))},
    "usage": {"turn": _turn, "total_tokens": _int_in(0, MAX_TOKENS), "delta_tokens": _int_or_none(0, MAX_TOKENS)},
    "plan_usage": {"turn": _turn, "primary_pct": _int_or_none(0, 10_000), "primary_window_min": _int_or_none(0, 10 ** 7),
                   "primary_resets_at": _int_or_none(0, 10 ** 12), "secondary_pct": _int_or_none(0, 10_000),
                   "secondary_window_min": _int_or_none(0, 10 ** 7), "secondary_resets_at": _int_or_none(0, 10 ** 12),
                   "reached": _short_or_none},
    "card_edit_sent": {"card_id": lambda v: isinstance(v, str) and bool(CARD_RE.match(v)), "text": _text(MAX_EXCERPT)},
}
# Fields a kind may have besides its own, all or none of them (a Claude turn's end has neither): what a Codex chat's
# turn end says about its cost, which Codex gives as tokens and VBear turns into money.
_OPTIONAL = {"turn_ended": {"estimate": _bool, "tokens": _int_or_none(0, MAX_TOKENS)},
             # whether the new process was told the employee's name and position (P58, ADR 0020); a record of before has none
             "process_started": {"identity": _bool},
             # a message VBear sent for a dispatch (P40-3) says which; one the person typed has none, and a record of before has none
             "user_message": {"origin": origin_ok}}
# Fields of which a kind has exactly one: the version of the CLI that started the session.
_ALTERNATIVES = {"session_ready": {"claude_code_version": _short, "cli_version": _short}}
_MASK = {"user_message": {"text": None}, "reply": {"text": MAX_REPLY}, "tool_result": {"text": MAX_EXCERPT},
         "tool_call": {"summary": MAX_EXCERPT}, "card": {"reason": MAX_SHORT},
         "auto_allowed": {"summary": MAX_EXCERPT, "reason": MAX_SHORT},
         "denied": {"summary": MAX_EXCERPT, "reason": MAX_SHORT}, "card_decision": {"value": MAX_EXCERPT},
         "error": {"message": MAX_EXCERPT}, "card_edit_sent": {"text": MAX_EXCERPT}}
_ESSENTIAL = frozenset({"turn_ended", "process_ended", "card_decision", "error"})


def _masked(kind: str, data: dict) -> dict:
    """``data`` with its text fields masked and cut (setting ``truncated`` where the kind has it)."""
    out = dict(data)
    for name, limit in _MASK.get(kind, {}).items():
        value = out.get(name)
        if not isinstance(value, str):
            continue
        value = redact(value)
        if limit is not None and len(value) > limit:
            value = value[:limit]
            if "truncated" in KINDS[kind]:
                out["truncated"] = True
        out[name] = value
    if kind == "card" and isinstance(out.get("input"), dict):
        # automated security review finding 2: masked by key name and value at every level (redact_value), then
        # every string cut, so a nested structure keeps no secret and no unbounded text
        out["input"] = _cut_value({k: redact_value(k, v) for k, v in out["input"].items()}, 1)
    return out


CARD_DEPTH = 8                         # levels of a card's input kept; what lies deeper is not stored
CARD_ITEMS = 64                        # keys of a mapping, items of a list kept at each level
_TOO_DEEP = "[太深，未保存]"


def _cut_value(value, depth: int):
    """A stored copy of a tool's input: strings cut to MAX_EXCERPT, at most CARD_ITEMS entries per level and
    CARD_DEPTH levels, a number that is not finite as None; anything else JSON cannot hold as its text."""
    if isinstance(value, str):
        return value[:MAX_EXCERPT]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if finite_real(value) is not None else None
    if depth > CARD_DEPTH:
        return _TOO_DEEP
    if isinstance(value, dict):
        return {str(k)[:64]: _cut_value(v, depth + 1) for k, v in list(value.items())[:CARD_ITEMS]}
    if isinstance(value, (list, tuple)):
        return [_cut_value(v, depth + 1) for v in list(value)[:CARD_ITEMS]]
    return str(value)[:MAX_EXCERPT]


def record_problem(rec) -> str | None:
    """Why one stored event does not fit (None when it does)."""
    if not isinstance(rec, dict):
        return "不是物件"
    kind = rec.get("kind")
    spec = KINDS.get(kind) if isinstance(kind, str) else None
    if spec is None:
        return "未知的事件種類"
    seq, at = rec.get("seq"), rec.get("at")
    if not (isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1):
        return "seq 不對"
    if finite_real(at) is None or at < 0:
        return "時間不對"
    optional = _OPTIONAL.get(kind, {})
    either = _ALTERNATIVES.get(kind, {})
    present = set(rec) - {"seq", "at", "kind"}
    if either and len(present & set(either)) != 1:
        return f"{kind} 的欄位不符"
    if (not set(spec) <= present or present - set(spec) - set(optional) - set(either)
            or (present & set(optional)) not in (set(), set(optional))):
        return f"{kind} 的欄位不符"
    for name, check in {**spec, **optional, **either}.items():
        if name in rec and not check(rec[name]):
            return f"{kind}.{name} 不符"
    return None


# ---- paths -------------------------------------------------------------------------------------------------------

def _uid() -> int:
    return os.getuid()


def _check_id(chat_id) -> str:
    if not isinstance(chat_id, str) or not CHAT_RE.match(chat_id):
        raise ChatStoreError("bad_request", "chat_id 不符格式")
    return chat_id


def _private_dir(path: Path, *, create: bool) -> Path:
    """``path`` as a folder of ours, 0700, that is not a link (created when asked and missing)."""
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ChatStoreError("storage", f"無法建立資料夾：{path.name}（{exc.strerror}）") from None
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise ChatStoreError("not_found", "找不到這個聊天") from None
    except OSError as exc:
        raise ChatStoreError("storage", f"無法讀取資料夾：{path.name}（{exc.strerror}）") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != _uid() or st.st_mode & 0o077:
        raise ChatStoreError("unsafe_path", f"不是本人擁有的 0700 一般資料夾：{path.name}")
    return path


def _root(base) -> Path:
    base = Path(base)
    if not base.is_dir():
        raise ChatStoreError("storage", "找不到 VBear 的資料夾")
    return base


def chats_dir(base, *, create: bool = False) -> Path:
    return _private_dir(_root(base) / CHATS, create=create)


def chat_dir(base, chat_id) -> Path:
    return _private_dir(chats_dir(base) / _check_id(chat_id), create=False)


def _open_file(directory: Path, name: str, flags: int) -> int:
    """A 0600 regular file of ours in ``directory``, opened without following a link."""
    try:
        fd = os.open(directory / name, flags | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise ChatStoreError("damaged", f"聊天紀錄缺少 {name}") from None
    except OSError as exc:
        raise ChatStoreError("unsafe_path", f"無法開啟 {name}（{exc.strerror}）") from None
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != _uid() or st.st_mode & 0o077:
        os.close(fd)
        raise ChatStoreError("unsafe_path", f"{name} 不是本人擁有的 0600 一般檔案")
    return fd


def _create_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _write_all(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(path)
        raise
    os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0:
            raise OSError(5, "寫入沒有進展")
        view = view[n:]


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _encode(rec: dict) -> bytes:
    try:
        return json.dumps(rec, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    except (UnicodeEncodeError, ValueError, TypeError):
        raise ChatStoreError("bad_record", "內容無法存成 JSON（含有無法編碼的字元）") from None


# ---- a chat --------------------------------------------------------------------------------------------------------

_CHAT_FIELDS_V1 = {"v", "id", "profile_id", "created_at", "claude_session_id"}


def _chat_problem(rec, chat_id: str) -> str | None:
    """Why chat.json does not fit (None when it does). Version 2 names the engine and its fields follow from it; version
    1 (before Codex chats) has no engine and is a Claude chat."""
    if not isinstance(rec, dict):
        return "欄位不符"
    if rec.get("v") == 1 and not isinstance(rec.get("v"), bool):
        if set(rec) != _CHAT_FIELDS_V1:
            return "欄位不符"
    elif rec.get("v") == 2 and not isinstance(rec.get("v"), bool):
        row = chat_engines.by_engine(rec.get("engine"))
        if row is None or set(rec) != row.record_fields():
            return "欄位不符"
    else:
        return "版本或編號不符"
    if rec["id"] != chat_id:
        return "版本或編號不符"
    if not (isinstance(rec["profile_id"], str) and PROFILE_ID_RE.match(rec["profile_id"])):
        return "員工編號不符"
    if finite_real(rec["created_at"]) is None:
        return "建立時間不符"
    for name in ("claude_session_id",) if rec["v"] == 1 else chat_engines.by_engine(rec["engine"]).uuid_fields:
        if not (isinstance(rec[name], str) and UUID_RE.match(rec[name])):
            return "對話編號不符"
    return None


def list_ids(base) -> list[str]:
    try:
        root = chats_dir(base)
    except ChatStoreError as exc:
        if exc.code == "not_found":
            return []
        raise
    try:
        names = os.listdir(root)
    except OSError as exc:
        raise ChatStoreError("storage", f"無法列出聊天（{exc.strerror}）") from None
    return sorted(n for n in names if CHAT_RE.match(n))


def create(base, profile_id, *, now: float, engine: str = "claude-chat") -> dict:
    """A new chat with ``profile_id``: its folder, chat.json and the first event. No process is started. ``engine``
    follows from the role card's AI tool and never changes."""
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.match(profile_id):
        raise ChatStoreError("bad_request", "profile_id 不符格式")
    row = chat_engines.by_engine(engine)
    if row is None:
        raise ChatStoreError("bad_request", "聊天的引擎不符")
    root = chats_dir(base, create=True)
    if len(list_ids(base)) >= MAX_CHATS:
        raise ChatStoreError("too_many", f"聊天最多 {MAX_CHATS} 個，請先刪掉不用的")
    chat_id = "c-" + secrets.token_hex(8)
    rec = {"v": 2, "id": chat_id, "profile_id": profile_id, "created_at": now, "engine": engine}
    for name in row.uuid_fields:
        rec[name] = str(uuid.uuid4())
    d = root / chat_id
    try:
        os.mkdir(d, 0o700)
        _create_file(d / CHAT_JSON, _encode(rec))
        first = {"seq": 1, "at": now, "kind": "chat_created", "profile_id": profile_id}
        _create_file(d / EVENTS, _encode(first))
        _fsync_dir(d)
        _fsync_dir(root)
    except FileExistsError:
        raise ChatStoreError("storage", "聊天編號重複，請再試一次") from None
    except OSError as exc:
        raise ChatStoreError("storage", f"無法建立聊天紀錄（{exc.strerror}）") from None
    return rec


def load(base, chat_id) -> dict:
    d = chat_dir(base, chat_id)
    fd = _open_file(d, CHAT_JSON, os.O_RDONLY)
    try:
        raw = strictjson.read_fd(fd, strictjson.MANIFEST.unit_bytes)
    except Exception:
        raise ChatStoreError("damaged", "聊天紀錄讀不出來") from None
    finally:
        os.close(fd)
    parsed = strictjson.loads_object(raw, strictjson.MANIFEST)
    problem = "不是正確的 JSON" if not parsed.ok else _chat_problem(parsed.value, chat_id)
    if problem:
        raise ChatStoreError("damaged", f"聊天紀錄不符結構（{problem}）")
    if parsed.value["v"] == 1:
        return {**parsed.value, "engine": "claude-chat"}
    return parsed.value


@dataclass
class Events:
    records: list
    problem: str = ""                  # why the file stops reading cleanly here ("" when it does not)
    last_seq: int = 0                  # of the last good record in the file
    size: int = 0


def _read_fd(fd: int, after: int = 0, limit: int | None = None) -> Events:
    out = Events([])
    expect = 1
    for parsed in strictjson.iter_json_lines(fd, EVENT_LIMITS):
        if not parsed.ok:
            out.problem = parsed.problem or "有一行不是正確的 JSON"
            break
        rec = parsed.value
        problem = record_problem(rec)
        if problem is None and rec["seq"] != expect:
            problem = "seq 不連續"
        if problem is None and expect == 1 and rec["kind"] != "chat_created":
            problem = "第一筆不是 chat_created"
        if problem:
            out.problem = f"第 {expect} 筆：{problem}"
            break
        expect += 1
        out.last_seq = rec["seq"]
        if rec["seq"] > after and (limit is None or len(out.records) < limit):
            out.records.append(rec)
    if not out.problem and out.last_seq == 0:
        out.problem = "沒有任何事件"
    out.size = os.fstat(fd).st_size
    return out


def read_events(base, chat_id, after: int = 0, limit: int | None = None) -> Events:
    """The events with seq > ``after`` (at most ``limit``), up to the first that does not read cleanly."""
    fd = _open_file(chat_dir(base, chat_id), EVENTS, os.O_RDONLY)
    try:
        return _read_fd(fd, after, limit)
    finally:
        os.close(fd)


class ChatLog:
    """The events file of one chat, open for appending. Refused when it does not read back cleanly."""

    def __init__(self, base, chat_id):
        self.chat_id = _check_id(chat_id)
        self.fd = _open_file(chat_dir(base, chat_id), EVENTS, os.O_RDWR | os.O_APPEND)
        try:
            ev = _read_fd(self.fd)
        except BaseException:
            os.close(self.fd)
            raise
        if ev.problem:
            os.close(self.fd)
            self.fd = -1
            raise ChatStoreError("damaged", f"聊天紀錄有問題，不能再寫入（{ev.problem}）")
        self.seq = ev.last_seq
        self.size = ev.size

    def room(self) -> int:
        """Bytes left before the file is full for anything but the records that close a turn."""
        return MAX_EVENTS_BYTES - RESERVE_BYTES - self.size

    def append(self, kind: str, data: dict, *, now: float) -> dict:
        if self.fd < 0:
            raise ChatStoreError("storage", "聊天紀錄已關閉")
        if kind not in KINDS:
            raise ChatStoreError("bad_record", f"未知的事件種類：{kind}")
        if kind == "user_message" and not KINDS[kind]["text"](data.get("text")):
            raise ChatStoreError("bad_record", "訊息是空的或太長")
        rec = {"seq": self.seq + 1, "at": now, "kind": kind, **_masked(kind, data)}
        problem = record_problem(rec)
        if problem:
            raise ChatStoreError("bad_record", f"拒絕寫入不符結構的聊天事件（{problem}）")
        line = _encode(rec)
        too_big = strictjson.scan(line[:-1], EVENT_LIMITS)
        if too_big:                                     # what is written must read back (depth, nodes, bytes)
            raise ChatStoreError("bad_record", f"聊天事件太大或太深，不能保存（{too_big}）")
        limit = MAX_EVENTS_BYTES if kind in _ESSENTIAL else MAX_EVENTS_BYTES - min(RESERVE_BYTES, MAX_EVENTS_BYTES // 4)
        if self.size + len(line) > limit:
            raise ChatStoreError("full", "這個聊天的紀錄已經滿了，請開新的聊天")
        try:
            _write_all(self.fd, line)
            os.fsync(self.fd)
        except OSError as exc:
            raise ChatStoreError("storage", f"無法寫入聊天紀錄（{exc.strerror}）") from None
        self.seq += 1
        self.size += len(line)
        return rec

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


# ---- what the events say ------------------------------------------------------------------------------------------

@dataclass
class Turn:
    turn: int
    cap: Decimal
    started_at: float
    cost: Decimal | None = None        # None while the turn is open
    ended_at: float | None = None
    reported: bool = False


@dataclass
class ChatState:
    turns: list = field(default_factory=list)
    last_total: float | None = None    # the last usable cumulative total the CLI reported for this session
    session_ready: bool = False        # a process of this session has started once (later ones resume)
    thread_id: str | None = None       # a Codex chat's thread (session_bound), which a later process resumes
    last_tokens: int | None = None     # a Codex chat's last token total of its thread (usage)
    process_open: bool = False         # a process_started without its process_ended
    last_seq: int = 0

    @property
    def next_turn(self) -> int:
        return (self.turns[-1].turn + 1) if self.turns else 1

    @property
    def open_turn(self) -> Turn | None:
        return next((t for t in self.turns if t.cost is None), None)


def derive(records) -> ChatState:
    st = ChatState()
    by_turn = {}
    for rec in records:
        kind = rec["kind"]
        st.last_seq = rec["seq"]
        if kind == "turn_started":
            t = Turn(rec["turn"], mt.money(rec["cap_usd"]), rec["at"])
            by_turn[t.turn] = t
            st.turns.append(t)
        elif kind == "turn_ended" and rec["turn"] in by_turn:
            t = by_turn[rec["turn"]]
            t.cost, t.ended_at, t.reported = mt.money(rec["cost_usd"]), rec["at"], rec["reported"]
            if rec["total_usd"] is not None:     # the base of the next turn, also after a total that went back
                st.last_total = float(rec["total_usd"])
        elif kind == "session_ready":
            st.session_ready = True
        elif kind == "session_bound":
            st.thread_id = rec["thread_id"]
        elif kind == "usage":
            st.last_tokens = rec["total_tokens"]
        elif kind == "process_started":
            st.process_open = True
        elif kind == "process_ended":
            st.process_open = False
    return st


def recover(base, *, now: float) -> list[str]:
    """After the daemon starts: close every turn and process a stopped daemon left open, each turn at its cap (the
    CLI's own report of it is lost). Returns the chats it changed; a chat that does not read cleanly is left as it
    is (and refuses new messages)."""
    changed = []
    for chat_id in list_ids(base):
        try:
            log = ChatLog(base, chat_id)
        except ChatStoreError:
            continue
        try:
            st = derive(read_events(base, chat_id).records)
            t = st.open_turn
            if t is None and not st.process_open:
                continue
            if t is not None:
                log.append("turn_ended", {"turn": t.turn, "cost_usd": usd(t.cap), "reported": False,
                                          "total_usd": None, "reason": "daemon_restart", "subtype": None,
                                          "is_error": True}, now=now)
            if st.process_open:
                log.append("process_ended", {"reason": "daemon_restart", "returncode": None}, now=now)
            changed.append(chat_id)
        except ChatStoreError:
            continue
        finally:
            log.close()
    return changed


# ---- deleting a chat ---------------------------------------------------------------------------------------------

def spend_dir(base, *, create: bool = False) -> Path:
    return _private_dir(_root(base) / SPEND, create=create)


def _spend_turns(st: ChatState) -> list[dict]:
    """The turns in the shape meetings.daily_spent counts (a running turn at its cap)."""
    out = []
    for t in st.turns:
        if t.cost is None:
            out.append({"state": "running", "started_at": t.started_at, "ended_at": None,
                        "evidence": {"cost_usd": "0"}, "cap_usd": usd(t.cap)})
        else:
            out.append({"state": "done", "started_at": t.started_at, "ended_at": t.ended_at,
                        "evidence": {"cost_usd": usd(t.cost)}, "cap_usd": usd(t.cap)})
    return out


def delete(base, chat_id, *, now: float) -> None:
    """Remove a chat's record; what its recent turns cost stays in chat-spend/ until it no longer counts toward any
    day's limit. Refused while a turn is open. The role card's work folder is kept."""
    d = chat_dir(base, chat_id)
    ev = read_events(base, chat_id)
    if ev.problem:              # what it spent cannot be kept whole: it stays, and the day stays unknown
        raise ChatStoreError("damaged", f"這個聊天的紀錄讀不完整（{ev.problem}），刪掉會讓花費無法核算；"
                                        "請人工檢查狀態目錄")
    st = derive(ev.records)
    if st.open_turn is not None or st.process_open:
        raise ChatStoreError("busy", "這個聊天還在進行，請先停止")
    names = set(os.listdir(d))
    if names - {CHAT_JSON, EVENTS}:
        raise ChatStoreError("damaged", "聊天資料夾裡有不認得的檔案，請人工檢查後再刪")
    keep = [t for t in _spend_turns(st) if (t["ended_at"] or t["started_at"]) >= now - SPEND_KEEP]
    if keep:
        sd = spend_dir(base, create=True)
        tomb = {"v": 1, "id": chat_id, "deleted_at": now, "turns": keep}
        try:
            _create_file(sd / f"{chat_id}.json", _encode(tomb))
            _fsync_dir(sd)
        except FileExistsError:
            raise ChatStoreError("storage", "這個聊天已經刪過") from None
        except OSError as exc:
            raise ChatStoreError("storage", f"無法保存刪除聊天的花費（{exc.strerror}）") from None
    try:
        for name in (EVENTS, CHAT_JSON):
            if name in names:
                os.unlink(d / name)
        os.rmdir(d)
        _fsync_dir(d.parent)
    except OSError as exc:
        raise ChatStoreError("storage", f"無法刪除聊天紀錄（{exc.strerror}）") from None
    _drop_prompt_start(base, chat_id)
    _prune_spend(base, now)


def _prune_spend(base, now: float) -> None:
    try:
        sd = spend_dir(base)
        names = os.listdir(sd)
    except (ChatStoreError, OSError):
        return
    for name in names:
        chat_id = name[:-5] if name.endswith(".json") else ""
        if not CHAT_RE.match(chat_id):
            continue
        try:
            rec = _load_spend(base, chat_id)
        except ChatStoreError:
            continue
        if all((t["ended_at"] or t["started_at"]) < now - SPEND_KEEP for t in rec["turns"]):
            try:
                os.unlink(sd / name)
            except OSError:
                pass


def _spend_problem(rec, chat_id: str) -> str | None:
    if not isinstance(rec, dict) or set(rec) != {"v", "id", "deleted_at", "turns"} or rec["v"] != 1 \
            or rec["id"] != chat_id or not isinstance(rec["turns"], list) or len(rec["turns"]) > 100_000:
        return "結構不符"
    for t in rec["turns"]:
        if not (isinstance(t, dict) and set(t) == {"state", "started_at", "ended_at", "evidence", "cap_usd"}
                and t["state"] in ("running", "done") and finite_real(t["started_at"]) is not None
                and (t["ended_at"] is None or finite_real(t["ended_at"]) is not None)
                and isinstance(t["evidence"], dict) and _money_text(t["evidence"].get("cost_usd"))
                and _money_text(t["cap_usd"])):
            return "回合不符"
    return None


def _load_spend(base, chat_id: str) -> dict:
    sd = spend_dir(base)
    fd = _open_file(sd, f"{chat_id}.json", os.O_RDONLY)
    try:
        raw = strictjson.read_fd(fd, 32 << 20)
    except Exception:
        raise ChatStoreError("damaged", "刪除聊天的花費紀錄讀不出來") from None
    finally:
        os.close(fd)
    parsed = strictjson.loads_object(raw, strictjson.Limits(32 << 20, 2_000_000, 8, 32 << 20))
    if not parsed.ok or _spend_problem(parsed.value, chat_id):
        raise ChatStoreError("damaged", "刪除聊天的花費紀錄不符結構")
    return parsed.value


# ---- what a chat's session was started with (P42-6) -----------------------------------------------------------------

SHA_RE = re.compile(r"^[0-9a-f]{64}\Z")


def set_prompt_start(base, chat_id, sha: str, with_memory: bool, with_identity: bool = False) -> None:
    """Keep the fingerprint (memory_rules.prompt_sha) of the system prompt a chat's NEW session was started with, and whether it
    carried the memory paragraph. Claude Code 2.1.319 keeps that prompt for the whole session (a ``--resume`` does not apply a new
    one), so the page compares it with the current memory and instructions to say when they differ. Never a word of either.
    ``with_identity`` (P58, ADR 0020): the session was also told the employee's name. Only then is the file given an ``identity`` key;
    a file without it is the one of before the upgrade (or of a session that was not told), and the page then leaves the name out of
    the compare."""
    _check_id(chat_id)
    if not (isinstance(sha, str) and SHA_RE.match(sha)) or not isinstance(with_memory, bool) or not isinstance(with_identity, bool):
        raise ChatStoreError("bad_request", "指紋格式不符")
    d = _private_dir(_root(base) / PROMPT, create=True)
    tmp = f".{chat_id}.{secrets.token_hex(4)}.tmp"
    try:
        _create_file(d / tmp, _encode({"v": 1, "sha": sha, "memory": with_memory, **({"identity": True} if with_identity else {})}))
        os.replace(d / tmp, d / f"{chat_id}.json")
        _fsync_dir(d)
    except OSError as exc:
        try:
            os.unlink(d / tmp)
        except OSError:
            pass
        raise ChatStoreError("storage", f"無法保存聊天開始時的指紋（{exc.strerror}）") from None


def prompt_start(base, chat_id) -> dict | None:
    """``{"sha", "memory"}`` (and ``"identity": True`` when the session was told the employee's name) as ``set_prompt_start`` kept it,
    or None when there is none or it does not read cleanly (a chat from before v0.17.0, a file of someone else's, a damaged one): the
    page then says nothing about it."""
    try:
        _check_id(chat_id)
        fd = _open_file(_private_dir(_root(base) / PROMPT, create=False), f"{chat_id}.json", os.O_RDONLY)
    except ChatStoreError:
        return None
    try:
        raw = strictjson.read_fd(fd, 4096)
    except Exception:
        return None
    finally:
        os.close(fd)
    parsed = strictjson.loads_object(raw, strictjson.Limits(4096, 100, 4, 4096))
    rec = parsed.value if parsed.ok else None
    if not (isinstance(rec, dict) and set(rec) in ({"v", "sha", "memory"}, {"v", "sha", "memory", "identity"}) and rec["v"] == 1
            and isinstance(rec["memory"], bool) and isinstance(rec["sha"], str) and SHA_RE.match(rec["sha"])
            and rec.get("identity", True) is True):
        return None
    return {"sha": rec["sha"], "memory": rec["memory"], **({"identity": True} if "identity" in rec else {})}


def _drop_prompt_start(base, chat_id) -> None:
    try:
        os.unlink(Path(base) / PROMPT / f"{chat_id}.json")
    except OSError:
        pass


def _spend_ids(base) -> list[str]:
    try:
        names = os.listdir(spend_dir(base))
    except ChatStoreError as exc:
        if exc.code == "not_found":
            return []
        raise
    except OSError as exc:
        raise ChatStoreError("storage", f"無法列出刪除聊天的花費（{exc.strerror}）") from None
    return sorted(n[:-5] for n in names if n.endswith(".json") and CHAT_RE.match(n[:-5]))


# ---- the day's spending ------------------------------------------------------------------------------------------

def limits_from(conf) -> dict[str, Decimal]:
    """``chat_limits.per_turn_usd`` from config when it is a number above zero and at most PER_TURN_CAP, else the
    default."""
    stored = conf.get("chat_limits") if isinstance(conf, dict) else None
    value = stored.get("per_turn_usd") if isinstance(stored, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = mt.money(value)
        if amount is not None and Decimal("0.01") <= amount <= PER_TURN_CAP:
            return {"per_turn_usd": amount}
    return {"per_turn_usd": DEFAULT_PER_TURN}


def validate_limits(body, current: dict[str, Decimal], daily: Decimal) -> dict[str, float]:
    """The new ``chat_limits`` of config.json from a request, or ValueError. ``daily`` is the meetings' daily limit in
    force (``chat_limits`` has none of its own: the day is shared); a turn may not be allowed to cost more than it."""
    if not isinstance(body, dict) or not body or set(body) - {"per_turn_usd"}:
        raise ValueError("chat_limits 只能含 per_turn_usd")
    raw = body["per_turn_usd"]
    value = None if isinstance(raw, str) else mt.money(raw)
    if value is None or not Decimal("0.01") <= value <= PER_TURN_CAP:
        raise ValueError(f"per_turn_usd 必須是 0.01 到 {PER_TURN_CAP} 之間的數字")
    if value > daily:
        raise ValueError("上限必須是：每次聊天 ≤ 每天")
    return {"per_turn_usd": float(value)}


def _unknown(chat_id: str, why: str) -> ChatStoreError:
    return ChatStoreError(mt.SPEND_UNKNOWN, f"聊天 {chat_id} 的花費紀錄讀不完整（{why}），無法確認今天已經花了多少")


def _written_before_the_day_of(now: float, *paths: Path) -> bool:
    """Whether everything in these files and folders was written before the local date of ``now``, by their times
    (the later of mtime and ctime: a file's ctime cannot be set back): then none of it can count toward that day."""
    latest = None
    for path in paths:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError:
            return False
        latest = max(latest or 0.0, st.st_mtime, st.st_ctime)
    return latest is not None and mt.local_day(latest) < mt.local_day(now)


def spend_record(base, chat_id, now: float) -> dict:
    """A chat, or what a deleted one left, as a record meetings.daily_spent can count: {"turns": [...]}, each turn
    counted at its cap while it runs. A record that does not read whole (damaged, cut short, missing its events or
    unsafe) raises ChatStoreError("spend_unknown"): what it spent is unknown, never less. Only a record whose files
    were all written before the local date of ``now`` counts nothing that day instead, since none of it can be of
    that day. A deleted chat whose spend record is gone (pruned) counts nothing."""
    folder = Path(base) / CHATS / chat_id
    try:
        ev = read_events(base, chat_id)
    except ChatStoreError as exc:
        if exc.code == "not_found":                 # no such chat: deleted, so what it left counts
            return _spent_by_deleted(base, chat_id, now)
        why = exc.message
    else:
        if not ev.problem:
            return {"turns": _spend_turns(derive(ev.records))}
        why = ev.problem
    if os.path.lexists(Path(base) / SPEND / f"{chat_id}.json"):
        # being deleted: delete() keeps what a chat that reads whole spent before it removes the chat's files
        return _spent_by_deleted(base, chat_id, now)
    if _written_before_the_day_of(now, folder, folder / EVENTS):
        return {"turns": []}
    raise _unknown(chat_id, why)


def _spent_by_deleted(base, chat_id: str, now: float) -> dict:
    path = Path(base) / SPEND / f"{chat_id}.json"
    try:
        return {"turns": _load_spend(base, chat_id)["turns"]}
    except ChatStoreError as exc:
        if not os.path.lexists(path):
            return {"turns": []}                    # pruned, or nothing of the chat was kept
        if _written_before_the_day_of(now, path):
            return {"turns": []}
        raise _unknown(chat_id, exc.message) from None


def turn_cap(record: dict, turn: dict) -> Decimal:
    return mt.money(turn.get("cap_usd")) or Decimal(0)


def spend_ids(base) -> list[str]:
    if not os.path.lexists(base):
        return []                                   # no state folder yet: no chat
    return sorted(set(list_ids(base)) | set(_spend_ids(base)))


def day_spent(base, now: float) -> Decimal:
    """What the chats' turns of today (the local date of ``now``) cost, the deleted chats' included. Raises
    ChatStoreError("spend_unknown") when that cannot be established in full: never a smaller sum."""
    try:
        records = [spend_record(base, chat_id, now) for chat_id in spend_ids(base)]
    except ChatStoreError as exc:
        if exc.code == mt.SPEND_UNKNOWN:
            raise
        raise ChatStoreError(mt.SPEND_UNKNOWN, f"聊天的花費讀不出來（{exc.message}），無法確認今天已經花了多少") from None
    return mt.daily_spent(records, now, turn_cap)


def spend_kind(clock=time.time):
    """(ids, load, per_call) for board_engine.spend_kinds: the chats count toward the same day's limit as the
    meetings and the staffing meetings. Reads <state> as the console sees it. What cannot be established raises
    MeetingError("spend_unknown"), which the board engine passes on (it does not skip it as a damaged meeting):
    the day is then unknown, and nothing new that costs money starts."""

    def ids():
        try:
            return spend_ids(cfg.state_dir())
        except ChatStoreError as exc:
            raise mt.MeetingError(mt.SPEND_UNKNOWN, f"聊天的花費讀不出來（{exc.message}）") from None

    def load(chat_id):
        try:
            return spend_record(cfg.state_dir(), chat_id, clock())
        except ChatStoreError as exc:
            raise mt.MeetingError(mt.SPEND_UNKNOWN, exc.message) from None

    return ids, load, turn_cap


# ---- the role card's work folder ---------------------------------------------------------------------------------

def work_dir_name(profile_id: str) -> str:
    """A role card's folder name: a hash, so that ids that differ only in case (one folder on a case-blind file
    system) stay apart."""
    return hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:24]


def ensure_work_dir(base, profile_id) -> str:
    """The role card's own work folder, created 0700 when missing, as a path with no link in it."""
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.match(profile_id):
        raise ChatStoreError("bad_request", "profile_id 不符格式")
    root = Path(os.path.realpath(_root(base)))
    parent = _private_dir(root / WORK, create=True)
    path = _private_dir(parent / work_dir_name(profile_id), create=True)
    if os.path.realpath(path) != str(path):
        raise ChatStoreError("unsafe_path", "工作資料夾的路徑含連結")
    return str(path)
