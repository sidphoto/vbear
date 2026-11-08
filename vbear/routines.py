"""The records of routines (例行工作, P44-2, ADR 0010): what the person made, what they set, and what happened each time.

``<state>/routines/`` (owner only, 0700):

  * ``routines.json`` (``GuardedJsonStore``, 0600): ``{"v": 1, "routines": [...]}``. A routine is ``{id, name, profile_id, text, days,
    times, enabled, enabled_at, created_at, updated_at}`` (see ``routine_rules``); at most 20, at most 10 of them on. A file that cannot
    be read safely is never guessed at: the page says so, nothing runs.
  * ``settings.json`` (0600): ``{"v": 1, "daily_usd": number | null, "keep_awake": bool}``. The daily limit of routines lives here and not
    in ``config.json`` (nothing of routines writes ``config.json``).
  * ``runs.jsonl`` (0600, append only; rolled to ``runs.jsonl.1`` at 2 MiB, both read): one full snapshot of a run for every change, the
    last line of a ``run_id`` is the run. ``{run_id, routine_id, slot, state, by, why, chat_id, turn, cost_usd, reason, started_at, at}``:
    ids, times, states, counts and money, **never** a name or a word of a routine. ``new_run`` is the one place a run is born, and it
    refuses a (routine, slot) that already has one: that is what keeps a slot from being done twice, whatever the clock does.
  * ``log.jsonl`` (0600, append only): what the person did to the routines, with ids only.
  * ``heartbeat.json`` (0600, P44-3): ``{"v": 1, "at": seconds}``, the instant VBear last looked, written by the runner about once a minute.
    It is how a start, or a look after a sleep, tells that VBear was not looking in between; no name and no word of a routine.

Who writes: routines, settings and the two logs are changed by the person's own press in the browser (the ``/api/routines*`` routes of
vbear/server.py carry ``X-VBear``); the functions that do it (``create``, ``edit``, ``set_enabled``, ``delete``, ``set_settings``, ``store``)
are called from there and from nowhere else (tests/test_autonomy_guard.py keeps it so). Runs are written by the runner
(vbear/routine_runner.py) and by the routes that carry the person's decision on a reminder. Nothing here writes ``config.json``, starts a
program, makes or changes a role card, installs a skill, or answers a question of a chat.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
import threading
import time
from decimal import Decimal

from . import config as cfg, routine_rules as rr
from .api_error import ApiError
from .jsonstore import GuardedJsonStore, StoreError
from .runtime import memory_rules

DIR = "routines"
SCHEMA = 1
LOG_MAX = 1 << 20
RUNS_MAX_BYTES = 2 << 20
ROUTINE_RE = re.compile(r"^r-[0-9a-f]{12}\Z")
RUN_RE = re.compile(r"^rr-[0-9a-f]{12}\Z")
CHAT_RE = re.compile(r"^c-[0-9a-f]{16}\Z")
ROUTINE_KEYS = {"id", "name", "profile_id", "text", "days", "times", "enabled", "enabled_at", "created_at", "updated_at"}
STATES = ("waiting", "starting", "running", "done", "skipped", "missed", "dismissed", "failed", "uncertain")
BYS = ("you", "auto3", None)
WHYS = ("on_time", "catch_up", "now")
RUN_KEYS = ("run_id", "routine_id", "slot", "state", "by", "why", "chat_id", "turn", "cost_usd", "reason", "started_at", "at")
CHANGEABLE = ("state", "by", "why", "chat_id", "turn", "cost_usd", "reason")
UNREADABLE = ("例行工作的檔案有問題，VBear 先不碰它：例行工作先不會做事。請檢查狀態資料夾裡的 routines 資料夾"
              "（權限、是不是連結，或有沒有 routines.json.corrupted）。")


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


# ---- the files ---------------------------------------------------------------------------------------------------------------

def _routine_problem(item) -> str | None:
    if not isinstance(item, dict) or set(item) != ROUTINE_KEYS:
        return "fields"
    if not (isinstance(item["id"], str) and ROUTINE_RE.match(item["id"])):
        return "id"
    try:
        rr.validate_fields({k: item[k] for k in rr.FIELDS}, full=True)
    except ValueError:
        return "fields"
    if item["enabled_at"] is not None and not _num(item["enabled_at"]):
        return "enabled_at"
    if not (_num(item["created_at"]) and _num(item["updated_at"])):
        return "time"
    return None


def _problem(key, value) -> str | None:
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "routines":
        if not isinstance(value, list) or len(value) > rr.MAX_ROUTINES:
            return "routines"
        if any(_routine_problem(item) for item in value) or len({item["id"] for item in value}) != len(value):
            return "routines"
        return None
    return "key"


def _settings_problem(key, value) -> str | None:
    if key == "v":
        return None if value == SCHEMA and isinstance(value, int) and not isinstance(value, bool) else "v"
    if key == "daily_usd":
        return None if value is None or (_num(value) and value >= 0.01) else "daily_usd"
    if key == "keep_awake":
        return None if isinstance(value, bool) else "keep_awake"
    return "key"


store = GuardedJsonStore(f"{DIR}/routines.json", "例行工作", _problem)
settings_store = GuardedJsonStore(f"{DIR}/settings.json", "例行工作的設定", _settings_problem)


def _folder(create: bool):
    """The routines folder, owner only, and not a link: Path, or None when it does not exist and ``create`` is false."""
    path = cfg.state_dir() / DIR
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if not create:
            return None
        cfg.ensure_state_dir()
        path.mkdir(mode=cfg.STATE_DIR_MODE, exist_ok=True)
        st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise StoreError("例行工作的資料夾不是這個使用者自己的資料夾（或是連結）")
    if stat.S_IMODE(st.st_mode) != cfg.STATE_DIR_MODE:
        os.chmod(path, cfg.STATE_DIR_MODE)
    return path


def _unreadable(exc: Exception) -> ApiError:
    return ApiError(503, "routines_unreadable", UNREADABLE)


def _log(what: str, routine_id: str | None = None, now: float | None = None, **extra) -> None:
    """One line, only the action and which routine (an id), never a word of one. A full log (1 MiB) becomes ``log.jsonl.1``."""
    folder = _folder(True)
    path = folder / "log.jsonl"
    try:
        if os.lstat(path).st_size >= LOG_MAX:
            os.replace(path, folder / "log.jsonl.1")
    except FileNotFoundError:
        pass
    line = {"at": round(time.time() if now is None else now, 3), "what": what}
    if routine_id is not None:
        line["id"] = routine_id
    line.update(extra)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        os.fchmod(fd, cfg.STATE_FILE_MODE)
        os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


# ---- reading routines and settings ---------------------------------------------------------------------------------------------

def _read() -> list:
    data = store.load()
    return list(data.get("routines", []))


def read_routines() -> tuple[list, str | None]:
    """``(routines, problem)``: the routines in the order they were made; ``problem`` is a sentence when the file cannot be read (then the
    list is empty and nothing may run)."""
    try:
        if _folder(False) is None:
            return [], None
        return _read(), None
    except (StoreError, OSError):
        return [], UNREADABLE


def read_settings() -> tuple[dict, str | None]:
    base = {"daily_usd": None, "keep_awake": False}
    try:
        if _folder(False) is None:
            return base, None
        data = settings_store.load()
    except (StoreError, OSError):
        return base, UNREADABLE
    return {"daily_usd": data.get("daily_usd"), "keep_awake": data.get("keep_awake", False)}, None


# ---- the person's changes (called from the browser's routes only) ---------------------------------------------------------------------

def _card_ok(profile_id: str, cards) -> None:
    card = next((c for c in cards if isinstance(c, dict) and c.get("id") == profile_id), None)
    if card is None or card.get("can_chat") is not True:
        raise ApiError(400, "routine_card", "這位員工現在不能聊天（找不到、已停用，或用的工具還不能聊天），例行工作交給不了他。")


def _fields(body, *, full: bool) -> tuple[dict, bool]:
    try:
        fields = rr.validate_fields(body, full=full)
    except ValueError as exc:
        raise ApiError(400, "bad_request", str(exc)) from None
    return fields, body.get("confirm_warning") is True


def _checked(fields: dict, confirmed: bool) -> None:
    """The name and the text are held to the memory's rules: a refusal is a 400, a warning needs ``confirm_warning``."""
    warn: list = []
    for key in ("name", "text"):
        if key in fields:
            got = rr.check_content(fields[key])
            if got["refuse"]:
                raise ApiError(400, "routine_refused", memory_rules.REFUSE_TEXT.get(got["refuse"], "這段文字現在不能存。"), refuse=got["refuse"])
            warn += [w for w in got["warn"] if w not in warn]
    if warn and not confirmed:
        texts = [memory_rules.WARN_TEXT[w] for w in warn if w in memory_rules.WARN_TEXT]
        raise ApiError(409, "routine_confirm", texts[0] if texts else "請再確認一次。", warn=warn, warn_text=texts)


def _find(items: list, routine_id):
    found = next((r for r in items if r["id"] == routine_id), None) if isinstance(routine_id, str) else None
    if found is None:
        raise ApiError(404, "not_found", "找不到這件例行工作。")
    return found


def _count_ok(items: list, *, adding: bool = False, enabling: bool = False, current: dict | None = None) -> None:
    if adding and len(items) >= rr.MAX_ROUTINES:
        raise ApiError(409, "routine_full", f"例行工作最多 {rr.MAX_ROUTINES} 件，請先刪掉幾件。")
    if enabling and sum(1 for r in items if r["enabled"] and r is not current) >= rr.MAX_ENABLED:
        raise ApiError(409, "routine_enabled_full", f"同時啟用的例行工作最多 {rr.MAX_ENABLED} 件，請先停用幾件。")


def create(body, cards, now: float | None = None) -> dict:
    """Make one routine: exactly the six fields (``confirm_warning: true`` when the text needs the second yes). ``cards`` are the chat
    service's cards ({id, can_chat, ...}). ``{"routine": ...}``, or ApiError: bad_request, routine_card, routine_refused (400),
    routine_confirm, routine_full, routine_enabled_full (409), routines_unreadable (503)."""
    fields, confirmed = _fields(body, full=True)
    _checked(fields, confirmed)
    _card_ok(fields["profile_id"], cards)
    now = time.time() if now is None else now
    try:
        _folder(True)
        with store.locked():
            items = _read()
            _count_ok(items, adding=True, enabling=fields["enabled"])
            routine = {"id": "r-" + secrets.token_hex(6), **fields, "enabled_at": now if fields["enabled"] else None,
                       "created_at": now, "updated_at": now}
            store.save({"v": SCHEMA, "routines": items + [routine]})
            _log("created", routine["id"], now, enabled=routine["enabled"])
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"routine": routine}


def edit(routine_id, body, cards, now: float | None = None) -> dict:
    """Change some of the six fields. A new schedule (days or times) or switching on starts counting from now: slots before this moment
    are not missed ones."""
    fields, confirmed = _fields(body, full=False)
    _checked(fields, confirmed)
    if "profile_id" in fields:
        _card_ok(fields["profile_id"], cards)
    now = time.time() if now is None else now
    try:
        _folder(True)
        with store.locked():
            items = _read()
            found = _find(items, routine_id)
            enabled = fields.get("enabled", found["enabled"])
            if enabled and "profile_id" not in fields:
                _card_ok(found["profile_id"], cards)
            if enabled and not found["enabled"]:
                _count_ok(items, enabling=True, current=found)
            changed = dict(found, **fields, updated_at=max(now, found["created_at"]))
            if not enabled:
                changed["enabled_at"] = None
            elif not found["enabled"] or "days" in fields or "times" in fields:
                changed["enabled_at"] = now
            store.save({"v": SCHEMA, "routines": [changed if r is found else r for r in items]})
            _log("edited", changed["id"], now, fields=sorted(fields))
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"routine": changed}


def set_enabled(routine_id, enabled, cards, now: float | None = None) -> dict:
    if not isinstance(enabled, bool):
        raise ApiError(400, "bad_request", "enabled 必須是 true 或 false。")
    out = edit(routine_id, {"enabled": enabled}, cards, now)
    return out


def delete(routine_id) -> dict:
    """Remove a routine. The chats it opened stay (they are the person's); reminders waiting for it are put away by the runner."""
    try:
        _folder(True)
        with store.locked():
            items = _read()
            found = _find(items, routine_id)
            store.save({"v": SCHEMA, "routines": [r for r in items if r is not found]})
            _log("deleted", found["id"])
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"deleted": routine_id}


def set_settings(body, daily_limit) -> dict:
    """The routines' settings the person may change here: ``daily_usd`` (a number from one cent to the day's limit ``daily_limit``, a
    Decimal; null: back to the default) and ``keep_awake`` (true or false: whether the Mac is kept from sleeping while employees work,
    P44-3). At least one of them, nothing else; the one not sent stays as it is."""
    if not isinstance(body, dict) or not body or set(body) - {"daily_usd", "keep_awake"}:
        raise ApiError(400, "bad_request", "只接受 daily_usd 與 keep_awake，至少一個。")
    if "keep_awake" in body and not isinstance(body["keep_awake"], bool):
        raise ApiError(400, "bad_request", "keep_awake 必須是 true 或 false。")
    value = body.get("daily_usd")
    if value is not None:
        try:
            value = rr.check_daily_usd(value, Decimal(daily_limit))
        except ValueError as exc:
            raise ApiError(400, "bad_request", str(exc)) from None
    try:
        _folder(True)
        with settings_store.locked():
            data = settings_store.load()
            merged = {"v": SCHEMA, "daily_usd": value if "daily_usd" in body else data.get("daily_usd"),
                      "keep_awake": body["keep_awake"] if "keep_awake" in body else data.get("keep_awake", False)}
            settings_store.save(merged)
            _log("settings", None, None)
    except (StoreError, OSError) as exc:
        raise _unreadable(exc) from None
    return {"settings": {"daily_usd": merged["daily_usd"], "keep_awake": merged["keep_awake"]}}


# ---- runs -----------------------------------------------------------------------------------------------------------------------

_runs_thread_lock = threading.RLock()


@contextlib.contextmanager
def _runs_locked(timeout: float = 10.0):
    with _runs_thread_lock:
        folder = _folder(True)
        fd = os.open(folder / "runs.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise StoreError("例行工作的紀錄鎖定逾時")
                    time.sleep(0.02)
            yield folder
        finally:
            os.close(fd)


def _run_problem(rec) -> str | None:
    if not isinstance(rec, dict) or set(rec) != set(RUN_KEYS):
        return "fields"
    if not (isinstance(rec["run_id"], str) and RUN_RE.match(rec["run_id"])
            and isinstance(rec["routine_id"], str) and ROUTINE_RE.match(rec["routine_id"])):
        return "id"
    if not (isinstance(rec["slot"], str) and rr.SLOT_RE.match(rec["slot"])):
        return "slot"
    if rec["state"] not in STATES or rec["by"] not in BYS or rec["why"] not in WHYS:
        return "state"
    if rec["chat_id"] is not None and not (isinstance(rec["chat_id"], str) and CHAT_RE.match(rec["chat_id"])):
        return "chat_id"
    if rec["turn"] is not None and not (isinstance(rec["turn"], int) and not isinstance(rec["turn"], bool) and rec["turn"] >= 1):
        return "turn"
    if rec["cost_usd"] is not None:
        try:
            if not (isinstance(rec["cost_usd"], str) and len(rec["cost_usd"]) <= 40 and Decimal(rec["cost_usd"]) >= 0):
                return "cost_usd"
        except ArithmeticError:
            return "cost_usd"
    if rec["reason"] is not None and not (isinstance(rec["reason"], str) and re.fullmatch(r"[a-z_0-9]{1,64}", rec["reason"])):
        return "reason"
    if rec["started_at"] is not None and not _num(rec["started_at"]):
        return "started_at"
    if not _num(rec["at"]):
        return "at"
    return None


def _read_file(path) -> list:
    """The records of one file, each a dict, in order; a last line that has no newline is a write that never finished and is not one.
    ValueError for a line that is not a record."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "rb") as fh:
        raw = fh.read()
    if raw and not raw.endswith(b"\n"):
        raw = raw[:raw.rfind(b"\n") + 1]
    out = []
    for line in raw.decode("utf-8", errors="strict").split("\n"):
        if not line:
            continue
        rec = json.loads(line)
        if _run_problem(rec):
            raise ValueError("record")
        out.append(rec)
    return out


def _all_records(folder) -> list:
    return _read_file(folder / "runs.jsonl.1") + _read_file(folder / "runs.jsonl")


def _fold(records: list) -> list:
    latest: dict = {}
    for rec in records:
        latest[rec["run_id"]] = rec            # a dict keeps the place of the first line of a run
    return list(latest.values())


def read_runs() -> tuple[list, str | None]:
    """``(runs, problem)``: every run as its last line says, in the order they began; ``problem`` when a record cannot be read (then the
    runner makes no new run: it could not tell whether a slot was done)."""
    try:
        folder = _folder(False)
        if folder is None:
            return [], None
        return _fold(_all_records(folder)), None
    except (StoreError, OSError, ValueError):
        return [], UNREADABLE


def _append(folder, rec: dict) -> None:
    path = folder / "runs.jsonl"
    try:
        if os.lstat(path).st_size >= RUNS_MAX_BYTES:
            os.replace(path, folder / "runs.jsonl.1")
    except FileNotFoundError:
        pass
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        os.fchmod(fd, cfg.STATE_FILE_MODE)
        size = os.fstat(fd).st_size
        if size:                                            # an unfinished last line was never a record: cut it off
            data = os.pread(fd, size, 0)
            if not data.endswith(b"\n"):
                os.ftruncate(fd, data.rfind(b"\n") + 1)
        os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def record_run(rec: dict) -> dict:
    """Append one snapshot of a run (checked). The caller holds the runs lock (``new_run`` and ``update_run`` do)."""
    if _run_problem(rec):
        raise ValueError("a run record of another shape")
    _append(_folder(True), rec)
    return rec


# ---- the heartbeat (P44-3) ----------------------------------------------------------------------------------------------------------

HEARTBEAT = "heartbeat.json"


def write_heartbeat(now: float) -> None:
    """``heartbeat.json`` (0600) = ``{"v": 1, "at": <the instant VBear last looked>}``, replaced whole. It holds nothing else: it is how a
    later start tells that VBear was not looking in between. Written by the runner."""
    folder = _folder(True)
    tmp = folder / (HEARTBEAT + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, cfg.STATE_FILE_MODE)
    try:
        os.fchmod(fd, cfg.STATE_FILE_MODE)
        os.write(fd, json.dumps({"v": SCHEMA, "at": round(float(now), 3)}).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, folder / HEARTBEAT)


def read_heartbeat() -> float | None:
    """The instant of the last heartbeat, or None: no file (a fresh upgrade), a link, or anything that is not exactly what was written.
    None means nothing is counted as missed."""
    try:
        folder = _folder(False)
        if folder is None:
            return None
        fd = os.open(folder / HEARTBEAT, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            data = json.loads(fh.read(4096).decode("utf-8"))
    except (OSError, ValueError, StoreError):
        return None
    if not isinstance(data, dict) or set(data) != {"v", "at"} or data["v"] != SCHEMA or isinstance(data["v"], bool):
        return None
    return float(data["at"]) if _num(data["at"]) else None


def new_run(routine_id: str, slot: str, *, state: str, why: str, by: str | None = None, reason: str | None = None,
            now: float | None = None) -> dict | None:
    """Begin a run of a slot, or None when the slot already has one (any state) or the records cannot be read. A run that begins as
    ``starting`` is counted as started now."""
    now = time.time() if now is None else now
    try:
        with _runs_locked() as folder:
            records = _all_records(folder)
            if any(r["routine_id"] == routine_id and r["slot"] == slot for r in records):
                return None
            rec = {"run_id": "rr-" + secrets.token_hex(6), "routine_id": routine_id, "slot": slot, "state": state, "by": by, "why": why,
                   "chat_id": None, "turn": None, "cost_usd": None, "reason": reason,
                   "started_at": now if state == "starting" else None, "at": now}
            return record_run(rec)
    except (StoreError, OSError, ValueError):
        return None


def update_run(run_id: str, expect, *, now: float | None = None, **changes) -> dict | None:
    """Change a run that is in one of the states ``expect``: the new snapshot, or None when it is not (it was decided meanwhile, or is
    not there). ValueError for a field or state that does not exist."""
    if set(changes) - set(CHANGEABLE):
        raise ValueError("a field of a run that is not changed here")
    now = time.time() if now is None else now
    try:
        with _runs_locked() as folder:
            try:
                current = next((r for r in _fold(_all_records(folder)) if r["run_id"] == run_id), None)
            except ValueError:
                return None                                 # the record cannot be read: nothing is changed on top of it
            if current is None or current["state"] not in expect:
                return None
            rec = dict(current, **changes, at=now)
            if rec["state"] == "starting" and rec["started_at"] is None:
                rec["started_at"] = now
            return record_run(rec)
    except (StoreError, OSError):
        return None


def chat_ids() -> set:
    """The chats the runs opened (a chat of a run is the person's, once it is there; this is for the list and for the service's check)."""
    return {r["chat_id"] for r in read_runs()[0] if r["chat_id"]}


def starting_chat(chat_id) -> dict | None:
    """The run that is sending the first message into this chat (state ``starting`` with this chat), or None. ``send_for_routine``
    sends into no other chat."""
    if not isinstance(chat_id, str):
        return None
    return next((r for r in read_runs()[0] if r["state"] == "starting" and r["chat_id"] == chat_id), None)


def chat_titles() -> dict:
    """``{chat id: title}`` for the chats of runs: 「例行工作：名稱 MM/DD HH:MM」, the name read from routines.json while the routine is
    there. The chat's record has no field for it: the console puts the title on the list."""
    names = {r["id"]: r["name"] for r in read_routines()[0]}
    return {r["chat_id"]: rr.chat_title(names.get(r["routine_id"]), r["slot"]) for r in read_runs()[0] if r["chat_id"]}
