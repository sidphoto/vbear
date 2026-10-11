"""Server-side preview records (design 3.1, 9, 10; S2c-1).

A dispatch and a risk acceptance are both approved from a record the server
made, never from what the browser sends back: the user sees a preview, the
server keeps the exact values it showed under a random id, and the approval
carries only that id. The record is one file, ``<state>/previews/<id>.json``
(0600), good for 5 minutes and for one use.

  * ``create`` writes a record (atomic, durable); at most 200 live records,
    each at most 128 KiB; expired ones are removed first.
  * ``consume`` is the approval: under one lock it checks that the record is
    ours, for this kind and flow, not expired, not used; runs the caller's
    check against the *current* facts; and writes ``consumed = true`` before
    it returns. Whatever the check says, the record cannot be used again: a
    preview that failed is void, and the user previews again.
  * A record is exactly its schema: the fields, their types and ranges, and
    the data of its kind. A file that is not exactly that (damaged, another
    owner, a link, a wrong mode) is never used and is removed with the
    expired ones.
  * Time that runs backwards makes a record expired, never newer.

Everything is opened relative to a directory descriptor, without following a
symlink, from the state directory down.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import threading
import time
from pathlib import Path

from . import acceptance, config as cfg, strictjson

PREVIEWS_DIR = "previews"
LOCK_NAME = ".lock"
TTL = 300.0
MAX_PREVIEWS = 200
MAX_BYTES = 128 << 10
MAX_TEXT_BYTES = 64 << 10
CLOCK_SLACK = 60.0                         # a clock set back by more than this voids the record
ID_RE = re.compile(r"^[0-9a-f]{32}\Z")
FILE_RE = re.compile(r"^([0-9a-f]{32})\.json\Z")
TMP_RE = re.compile(r"^\.[0-9a-f]{32}\.tmp\Z")
FLOW_RE = re.compile(r"^flow-[0-9a-f]{12}\Z")
LAUNCH_RE = re.compile(r"^l-[0-9a-f]{16}\Z")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
SHA_RE = re.compile(r"^[0-9a-f]{64}\Z")
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
REQUIRED = frozenset({"v", "preview_id", "kind", "flow_id", "created", "expires", "consumed", "data"})


class PreviewError(Exception):
    """``code``: not_found (404), expired (409), consumed (409), conflict
    (409: a fact changed since the preview), mismatch (409: another flow or
    kind), full (429), invalid (400), unavailable (500: the store itself)."""

    STATUS = {"not_found": 404, "expired": 409, "consumed": 409, "conflict": 409, "mismatch": 409,
              "full": 429, "invalid": 400, "unavailable": 500}

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    @property
    def status(self) -> int:
        return self.STATUS.get(self.code, 500)


# ---- what each kind carries -------------------------------------------------------------------------------

def _acceptance_data_problem(data) -> str | None:
    if not (isinstance(data, dict) and set(data) == {"fields"}):
        return "acceptance 的資料欄位不符"
    problem = acceptance.record_problem(data["fields"])
    return f"接受內容不合法（{problem}）" if problem else None


def _dispatch_data_problem(data) -> str | None:
    if not (isinstance(data, dict) and set(data) == {"launch_id", "dispatch_id", "text", "text_sha256"}):
        return "dispatch 的資料欄位不符"
    if not (isinstance(data["launch_id"], str) and LAUNCH_RE.match(data["launch_id"])):
        return "launch_id 不合法"
    if not (isinstance(data["dispatch_id"], str) and UUID_RE.match(data["dispatch_id"])):
        return "dispatch_id 不合法"
    text = data["text"]
    if not isinstance(text, str):
        return "text 不是字串"
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return "text 含孤立的 surrogate"
    if not 0 < len(raw) <= MAX_TEXT_BYTES:
        return "text 的長度不合法"
    if not (isinstance(data["text_sha256"], str) and SHA_RE.match(data["text_sha256"])
            and hashlib.sha256(raw).hexdigest() == data["text_sha256"]):
        return "text_sha256 與全文不符"
    return None


KINDS = {"acceptance": _acceptance_data_problem, "dispatch": _dispatch_data_problem}


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 1e9 else None


def record_problem(rec, name_id: str | None = None) -> str | None:
    """None when ``rec`` is exactly a preview record (and, when ``name_id``
    is given, the one its file name says)."""
    if not isinstance(rec, dict) or set(rec) != REQUIRED:
        return "欄位不符"
    if rec["v"] != 1 or isinstance(rec["v"], bool):
        return "版本不符"
    if not (isinstance(rec["preview_id"], str) and ID_RE.match(rec["preview_id"])):
        return "preview_id 不合法"
    if name_id is not None and rec["preview_id"] != name_id:
        return "preview_id 與檔名不符"
    if rec["kind"] not in KINDS:
        return "種類不合法"
    if not (isinstance(rec["flow_id"], str) and FLOW_RE.match(rec["flow_id"])):
        return "flow_id 不合法"
    created, expires = _num(rec["created"]), _num(rec["expires"])
    if created is None or expires is None or abs((expires - created) - TTL) > 1e-6:
        return "時間不合法"
    if not isinstance(rec["consumed"], bool):
        return "consumed 不是布林值"
    return KINDS[rec["kind"]](rec["data"])


def new_id() -> str:
    return secrets.token_hex(16)


class PreviewStore:
    """One per state directory. Every public method is safe to call from
    several server threads (and from several server processes, by a file
    lock)."""

    def __init__(self, base=None, clock=time.time):
        self._base = Path(base) if base is not None else None
        self._clock = clock
        self._mutex = threading.Lock()

    # ---- the directory -------------------------------------------------------------------------------

    @property
    def base(self) -> Path:
        return self._base if self._base is not None else cfg.state_dir()

    def _open_dir(self, create: bool) -> int:
        """previews/ under the state directory, by descriptors, nothing
        followed; ours and 0700."""
        try:
            fd = os.open(str(self.base), _DIR)
        except OSError as exc:
            raise PreviewError("unavailable", f"狀態資料夾無法開啟（{exc.strerror or type(exc).__name__}）") from exc
        try:
            try:
                sub = os.open(PREVIEWS_DIR, _DIR, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                old = os.umask(0o077)
                try:
                    os.mkdir(PREVIEWS_DIR, 0o700, dir_fd=fd)
                finally:
                    os.umask(old)
                sub = os.open(PREVIEWS_DIR, _DIR, dir_fd=fd)
            except OSError as exc:
                raise PreviewError("unavailable", f"預覽資料夾無法開啟（{exc.strerror or type(exc).__name__}）") from exc
        finally:
            os.close(fd)
        st = os.fstat(sub)
        if st.st_uid != os.geteuid() or st.st_mode & 0o077:
            os.close(sub)
            raise PreviewError("unavailable", "預覽資料夾不是本人的 0700 資料夾")
        return sub

    @contextlib.contextmanager
    def _locked(self, create: bool = True):
        with self._mutex:
            try:
                dfd = self._open_dir(create)
            except FileNotFoundError:
                yield None
                return
            try:
                try:
                    lock = os.open(LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
                except OSError as exc:
                    raise PreviewError("unavailable", f"預覽鎖無法開啟（{exc.strerror or type(exc).__name__}）") from exc
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    yield dfd
                finally:
                    os.close(lock)                  # closing releases the flock
            finally:
                os.close(dfd)

    # ---- reading and writing one record ----------------------------------------------------------------------

    def _read(self, dfd: int, preview_id: str):
        """(record, None) or (None, why). A file that is not exactly a record
        is reported, not used."""
        try:
            fd, st = strictjson.open_owned(f"{preview_id}.json", dir_fd=dfd, max_bytes=MAX_BYTES)
        except strictjson.ReadRefused as exc:
            return None, ("missing" if exc.missing else f"無法讀取（{exc}）")
        try:
            if stat.S_IMODE(st.st_mode) != 0o600:
                return None, "權限不是 0600"
            raw = strictjson.read_fd(fd, MAX_BYTES)
        except (strictjson.ReadRefused, OSError) as exc:
            return None, f"無法讀取（{type(exc).__name__}）"
        finally:
            os.close(fd)
        parsed = strictjson.loads_object(raw, strictjson.PREVIEW)
        if not parsed.ok:
            return None, f"不是合法的 JSON 物件（{parsed.problem}）"
        problem = record_problem(parsed.value, preview_id)
        return (parsed.value, None) if problem is None else (None, problem)

    def _write(self, dfd: int, rec: dict) -> None:
        raw = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_BYTES:
            raise PreviewError("invalid", f"預覽紀錄超過 {MAX_BYTES >> 10} KiB")
        tmp = f".{rec['preview_id']}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
        except OSError as exc:
            raise PreviewError("unavailable", f"預覽紀錄無法寫入（{exc.strerror or type(exc).__name__}）") from exc
        try:
            try:
                view = memoryview(raw)
                while view:
                    n = os.write(fd, view)
                    if n <= 0:
                        raise OSError(5, "寫入沒有進展")
                    view = view[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, f"{rec['preview_id']}.json", src_dir_fd=dfd, dst_dir_fd=dfd)
            os.fsync(dfd)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=dfd)
            raise PreviewError("unavailable", f"預覽紀錄無法寫入（{exc.strerror or type(exc).__name__}）") from exc

    def _entries(self, dfd: int) -> list[str]:
        try:
            with os.scandir(dfd) as it:
                return sorted(e.name for e in it)
        except OSError as exc:
            raise PreviewError("unavailable", f"預覽資料夾無法列出（{exc.strerror or type(exc).__name__}）") from exc

    def _expired(self, rec: dict, now: float) -> bool:
        return now >= rec["expires"] or now < rec["created"] - CLOCK_SLACK

    def _purge(self, dfd: int, now: float) -> int:
        """Remove expired, damaged and leftover files; the number of live
        records left."""
        live = 0
        for name in self._entries(dfd):
            m = FILE_RE.match(name)
            if m:
                rec, why = self._read(dfd, m.group(1))
                if rec is not None and not self._expired(rec, now):
                    live += 1
                    continue
            elif not TMP_RE.match(name):
                continue                          # not ours: left alone (the lock file, anything else)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=dfd)
        return live

    # ---- the public operations ---------------------------------------------------------------------------------

    def create(self, kind: str, flow_id: str, data: dict) -> dict:
        """A new record. PreviewError("invalid") for a kind, flow or data
        that is not exactly what the kind carries; "full" at 200 live
        records."""
        now = self._clock()
        rec = {"v": 1, "preview_id": new_id(), "kind": kind, "flow_id": flow_id, "created": now,
               "expires": now + TTL, "consumed": False, "data": data}
        problem = record_problem(rec)
        if problem:
            raise PreviewError("invalid", f"預覽內容不合法：{problem}")
        with self._locked() as dfd:
            if self._purge(dfd, now) >= MAX_PREVIEWS:
                raise PreviewError("full", f"未使用的預覽已達 {MAX_PREVIEWS} 筆，請稍後再試")
            self._write(dfd, rec)
        return rec

    def get(self, preview_id: str, *, kind: str | None = None, flow_id: str | None = None) -> dict:
        """The record if it is usable (exists, exactly a record, not
        expired, not consumed, of this kind and flow); else PreviewError.
        Does not consume."""
        rec = self._load_usable(preview_id, kind, flow_id, consume=False)
        return rec

    def consume(self, preview_id: str, *, kind: str, flow_id: str, check=None) -> dict:
        """The approval. Under the lock: the record must be usable; ``check``
        (called with the record) must not raise; and the record is marked
        consumed on disk before it is returned. A ``check`` that raises
        PreviewError (typically "conflict") leaves the record consumed too: a
        preview that no longer matches the facts is void."""
        return self._load_usable(preview_id, kind, flow_id, consume=True, check=check)

    def _load_usable(self, preview_id, kind, flow_id, *, consume: bool, check=None) -> dict:
        if not (isinstance(preview_id, str) and ID_RE.match(preview_id)):
            raise PreviewError("invalid", "preview_id 格式不符")
        now = self._clock()
        with self._locked(create=False) as dfd:
            if dfd is None:
                raise PreviewError("not_found", "找不到這筆預覽（可能已過期），請重新預覽")
            rec, why = self._read(dfd, preview_id)
            if rec is None:
                if why == "missing":
                    raise PreviewError("not_found", "找不到這筆預覽（可能已過期），請重新預覽")
                with contextlib.suppress(OSError):
                    os.unlink(f"{preview_id}.json", dir_fd=dfd)
                raise PreviewError("invalid", f"這筆預覽的紀錄不合法，已作廢（{why}）")
            if self._expired(rec, now):
                with contextlib.suppress(OSError):
                    os.unlink(f"{preview_id}.json", dir_fd=dfd)
                raise PreviewError("expired", "這筆預覽已過期，請重新預覽")
            if rec["consumed"]:
                raise PreviewError("consumed", "這筆預覽已經用過，請重新預覽")
            if rec["kind"] != kind or rec["flow_id"] != flow_id:
                raise PreviewError("mismatch", "這筆預覽不屬於這個流程或這個動作")
            if not consume:
                return rec
            rec = dict(rec, consumed=True)
            self._write(dfd, rec)                  # first: from here the record cannot be used again
            if check is not None:
                check(rec)                         # PreviewError("conflict") and the like: the record stays void
            return rec

    def void(self, preview_id: str) -> None:
        """Remove a record (best effort)."""
        if not (isinstance(preview_id, str) and ID_RE.match(preview_id)):
            return
        with self._locked(create=False) as dfd:
            if dfd is not None:
                with contextlib.suppress(OSError):
                    os.unlink(f"{preview_id}.json", dir_fd=dfd)

    def purge(self) -> int:
        """Remove expired and damaged records; the number of live ones."""
        with self._locked(create=False) as dfd:
            return 0 if dfd is None else self._purge(dfd, self._clock())
