"""Per-flow files the daemon writes (it is their only writer, design 9).

  <state>/pipelines/<task-id>/dispatches/<dispatch-id>.txt   dispatch texts (3.5)
  <state>/pipelines/<task-id>/started.json                   first stream start (planner Q1)
  <state>/holds/<flow-id>                                    a stopped flow (7)

Every path component is a validated identifier (design 2.4 path rule) and
every directory is opened from the state directory by fd with O_NOFOLLOW,
so the result is always below the expected parent.

Dispatch text, write order (3.5): exclusive ``.<id>.partial``, write, fsync,
link to the final name (link refuses an existing name: never overwritten),
unlink the partial, fsync the directory. Only after that does the caller
write ``dispatch_accepted`` to the journal.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time

from .. import strictjson
from ..numbers import finite_real
from . import stream_protocol as sp

PIPELINES = "pipelines"
DISPATCHES = "dispatches"
HOLDS = "holds"
STARTED = "started.json"
RELEASED = "released.json"                 # v29.8: the flow's last pipeline_release
RESOLVED_MAX = 4096                        # failure identities one flow may have released
# "<launch>#<seq>" (a journal record) or "<launch>#manual_review#<retained_at as stored>"
FAILURE_ID_RE = re.compile(r"^(?:l-[0-9a-f]{16}#(?:[1-9][0-9]{0,8}|manual_review#[0-9eE.+\-]{1,40})"
                           r"|r-[0-9a-f]{16}#(?:invalid|manual_review#[0-9eE.+\-]{1,40}))\Z")
RELEASE_FILE_MAX = 256 << 10
RELEASE_LIMITS = strictjson.Limits(RELEASE_FILE_MAX, RESOLVED_MAX + 64, 8, None)
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
FLOW_RE = re.compile(r"^flow-[0-9a-f]{12}\Z")
LAUNCH_RE = re.compile(r"^l-[0-9a-f]{16}\Z")              # agent_sessions.LAUNCH_RE
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
TEXT_NAME = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.txt\Z")
PARTIAL_NAME = re.compile(r"^\.([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.partial\Z")
MAX_TEXT = sp.MAX_DISPATCH_LINE
MAX_DIR_ENTRIES = 10_000
EARLIEST = 1577836800.0                    # 2020-01-01
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class StoreRefused(Exception):
    """``missing`` is True only when the flow's directory itself does not
    exist (never decided from the message text)."""

    def __init__(self, message: str, *, missing: bool = False):
        super().__init__(message)
        self.missing = missing


def _open_dir(name: str, parent: int, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(name, _DIR, dir_fd=parent)
    st = os.fstat(fd)
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
        os.close(fd)
        raise StoreRefused(f"{name} 不是目前使用者私有的資料夾")
    return fd


def _write_all(fd: int, data: bytes) -> None:
    """Every byte or an error (review round 7: a short write is never taken
    for a complete one). A write that makes no progress is an error."""
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0:
            raise OSError(5, "寫入沒有進展")
        view = view[n:]


def _fsync_dir(fd: int):
    """Make a rename/link/unlink in this directory durable. A failure is
    reported, never swallowed (Codex S2a-2 p1 #5): the caller treats the
    write as failed, so e.g. a start record that might vanish after a crash
    cannot quietly move the flow's elapsed-time origin."""
    try:
        os.fsync(fd)
    except OSError as exc:
        raise StoreRefused(f"資料夾無法同步到磁碟（{exc.strerror or type(exc).__name__}）") from exc


class Pipeline:
    """One flow's directory, opened by fd. Use as a context manager."""

    def __init__(self, base, task_id: str, *, create: bool):
        if not (isinstance(task_id, str) and TASK_RE.match(task_id)) or task_id in (".", ".."):
            raise StoreRefused("任務 id 格式不符")
        self.task_id = task_id
        self._fds: list[int] = []
        step = "state"
        try:
            state = self._keep(os.open(str(base), _DIR))
            step = "flow"                     # pipelines/ or pipelines/<task>: the flow's own directory
            root = self._keep(_open_dir(PIPELINES, state, create=create))
            self.fd = self._keep(_open_dir(task_id, root, create=create))
            step = "dispatches"               # created with the flow directory: missing means damaged
            self.dispatches = self._keep(_open_dir(DISPATCHES, self.fd, create=create))
        except FileNotFoundError as exc:
            self.close()
            if step == "flow":
                raise StoreRefused("流程資料夾不存在", missing=True) from exc
            raise StoreRefused(f"流程資料夾不完整（{step} 不見了）") from exc
        except OSError as exc:
            self.close()
            raise StoreRefused(f"無法開啟流程資料夾（{exc.strerror}）") from exc
        except BaseException:
            self.close()
            raise

    def _keep(self, fd: int) -> int:
        self._fds.append(fd)
        return fd

    def close(self):
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # dispatch texts -------------------------------------------------------------

    def text_names(self) -> list[str]:
        """Dispatch ids that have a final text file. More than the limit, or
        anything unexpected, refuses (counts must be exact)."""
        ids = []
        with os.scandir(self.dispatches) as it:
            for n, entry in enumerate(it):
                if n >= MAX_DIR_ENTRIES:
                    raise StoreRefused("派工資料夾項目過多")
                m = TEXT_NAME.match(entry.name)
                if m:
                    if not entry.is_file(follow_symlinks=False):
                        raise StoreRefused(f"{entry.name} 不是一般檔案")
                    ids.append(m.group(1))
                elif not PARTIAL_NAME.match(entry.name):
                    raise StoreRefused(f"派工資料夾裡有不認得的項目：{entry.name[:64]!r}")
        return sorted(ids)

    def remove_partials(self) -> list[str]:
        """Crash recovery (3.5): a ``.partial`` was never accepted; delete it."""
        removed = []
        with os.scandir(self.dispatches) as it:
            names = [e.name for e in it if PARTIAL_NAME.match(e.name)]
        for name in names:
            os.unlink(name, dir_fd=self.dispatches)
            removed.append(PARTIAL_NAME.match(name).group(1))
        if removed:
            _fsync_dir(self.dispatches)
        return removed

    def write_text(self, dispatch_id: str, data: bytes) -> None:
        """Exclusive, fsynced, never overwrites. FileExistsError when a final
        file for this id is already there (the caller then compares it)."""
        if not (isinstance(dispatch_id, str) and sp.UUID_RE.match(dispatch_id)):
            raise StoreRefused("dispatch_id 格式不符")
        if not isinstance(data, bytes) or len(data) > MAX_TEXT:
            raise StoreRefused("派工全文超過上限")
        final, partial = f"{dispatch_id}.txt", f".{dispatch_id}.partial"
        try:
            os.stat(final, dir_fd=self.dispatches, follow_symlinks=False)
            raise FileExistsError(final)
        except FileNotFoundError:
            pass
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                     dir_fd=self.dispatches)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(5, "寫入沒有進展")
                view = view[written:]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(partial, dir_fd=self.dispatches)
            raise
        os.close(fd)
        try:
            os.link(partial, final, src_dir_fd=self.dispatches, dst_dir_fd=self.dispatches,
                    follow_symlinks=False)
        finally:
            os.unlink(partial, dir_fd=self.dispatches)
        _fsync_dir(self.dispatches)

    def text_bytes(self, dispatch_id: str) -> int:
        """Bytes on disk for this dispatch's text: the final file and a
        .partial, each counted, as the quota scan counts them (review B-1)."""
        if not (isinstance(dispatch_id, str) and sp.UUID_RE.match(dispatch_id)):
            raise StoreRefused("dispatch_id 格式不符")
        total = 0
        for name in (f"{dispatch_id}.txt", f".{dispatch_id}.partial"):
            try:
                total += os.stat(name, dir_fd=self.dispatches, follow_symlinks=False).st_size
            except FileNotFoundError:
                pass
        return total

    def read_text(self, dispatch_id: str) -> bytes:
        if not (isinstance(dispatch_id, str) and sp.UUID_RE.match(dispatch_id)):
            raise StoreRefused("dispatch_id 格式不符")
        try:
            return strictjson.read_owned(f"{dispatch_id}.txt", dir_fd=self.dispatches, max_bytes=MAX_TEXT)
        except strictjson.ReadRefused as exc:
            raise StoreRefused(f"派工全文無法讀取（{exc}）") from exc

    # the flow's first stream start (planner decision S2a-2 Q1) -------------------

    def start_record(self) -> dict | None:
        """The flow's start record {"pipeline_id", "launch_id", "started_at"}
        (v29.7: the launch whose open wrote it), None when there is none yet;
        StoreRefused when it cannot be trusted (then the caller refuses)."""
        try:
            fd, _ = strictjson.open_owned(STARTED, dir_fd=self.fd, max_bytes=strictjson.MANIFEST.file_bytes)
        except strictjson.ReadRefused as exc:
            if exc.missing:                   # the read's own flag, not its message
                return None
            raise StoreRefused(f"流程開始時間無法讀取（{exc}）") from exc
        try:
            raw = strictjson.read_fd(fd, strictjson.MANIFEST.file_bytes)
        except strictjson.ReadRefused as exc:
            raise StoreRefused(f"流程開始時間無法讀取（{exc}）") from exc
        finally:
            os.close(fd)
        parsed = strictjson.loads_object(raw, strictjson.MANIFEST)
        if not parsed.ok:
            raise StoreRefused(f"流程開始時間無法讀取（{parsed.problem}）")
        d = parsed.value
        t = finite_real(d.get("started_at")) if not isinstance(d.get("started_at"), bool) else None
        # v2 (design v29.9): base_commit, the work directory's HEAD when the
        # flow first started, is what a review's range begins at. The v1
        # record (no base_commit) is refused.
        if (set(d) != {"v", "pipeline_id", "launch_id", "base_commit", "started_at"} or d.get("v") != 2
                or isinstance(d.get("v"), bool) or not isinstance(d.get("pipeline_id"), str)
                or not FLOW_RE.match(d["pipeline_id"]) or not isinstance(d.get("launch_id"), str)
                or not LAUNCH_RE.match(d["launch_id"]) or not isinstance(d.get("base_commit"), str)
                or not COMMIT_RE.match(d["base_commit"]) or t is None or not EARLIEST <= t <= time.time() + 86400):
            raise StoreRefused("流程開始時間的紀錄不符")
        return {"pipeline_id": d["pipeline_id"], "launch_id": d["launch_id"], "base_commit": d["base_commit"],
                "started_at": t}

    def started_at(self, pipeline_id: str) -> float | None:
        """None when no stream session has started yet; StoreRefused when the
        record cannot be trusted or names another flow."""
        rec = self.start_record()
        if rec is None:
            return None
        if rec["pipeline_id"] != pipeline_id:
            raise StoreRefused("流程開始時間的紀錄不符")
        return rec["started_at"]

    def record_start(self, pipeline_id: str, now: float, *, launch_id: str, base_commit: str) -> float:
        """Write the first start once; an existing record is kept."""
        if not (isinstance(launch_id, str) and LAUNCH_RE.match(launch_id)):
            raise StoreRefused("launch id 格式不符")
        if not (isinstance(base_commit, str) and COMMIT_RE.match(base_commit)):
            raise StoreRefused("base_commit 格式不符")
        existing = self.started_at(pipeline_id)
        if existing is not None:
            return existing
        data = json.dumps({"v": 2, "pipeline_id": pipeline_id, "launch_id": launch_id,
                           "base_commit": base_commit, "started_at": now}).encode()
        fd = os.open(STARTED, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                     dir_fd=self.fd)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(STARTED, dir_fd=self.fd)     # just created by us: never leave a half record
            raise
        os.close(fd)
        _fsync_dir(self.fd)
        return now

    def start_record_bytes(self) -> int:
        try:
            return os.stat(STARTED, dir_fd=self.fd, follow_symlinks=False).st_size
        except FileNotFoundError:
            return 0

    # the flow's last release (design v29.8) ------------------------------------------

    def release_record(self, pipeline_id: str) -> dict | None:
        """The flow's last "continue" (pipeline_release): {"released_at",
        "resolved"} where resolved is the set of failure identities the user
        has released (review round 6: identities, never times, decide). None
        when never released; StoreRefused when it cannot be trusted."""
        try:
            fd, _ = strictjson.open_owned(RELEASED, dir_fd=self.fd, max_bytes=RELEASE_FILE_MAX)
        except strictjson.ReadRefused as exc:
            if exc.missing:
                return None
            raise StoreRefused(f"流程繼續紀錄無法讀取（{exc}）") from exc
        try:
            raw = strictjson.read_fd(fd, RELEASE_FILE_MAX)
        except strictjson.ReadRefused as exc:
            raise StoreRefused(f"流程繼續紀錄無法讀取（{exc}）") from exc
        finally:
            os.close(fd)
        parsed = strictjson.loads_object(raw, RELEASE_LIMITS)
        if not parsed.ok:
            raise StoreRefused(f"流程繼續紀錄無法讀取（{parsed.problem}）")
        d = parsed.value
        t = finite_real(d.get("released_at")) if not isinstance(d.get("released_at"), bool) else None
        resolved = d.get("resolved")
        if (set(d) != {"v", "pipeline_id", "released_at", "resolved"} or d.get("v") != 2
                or isinstance(d.get("v"), bool) or d.get("pipeline_id") != pipeline_id
                or t is None or not EARLIEST <= t <= time.time() + 86400
                or not isinstance(resolved, list) or len(resolved) > RESOLVED_MAX
                or not all(isinstance(x, str) and FAILURE_ID_RE.match(x) for x in resolved)
                or len(set(resolved)) != len(resolved)):
            raise StoreRefused("流程繼續紀錄不符")
        return {"released_at": t, "resolved": set(resolved)}

    def record_release(self, pipeline_id: str, now: float, resolved) -> None:
        """Replace the release record atomically (temp file, fsync, rename,
        directory sync); a failure raises, so a release is never assumed.
        More than RESOLVED_MAX identities refuses (a person looks first)."""
        if not (isinstance(pipeline_id, str) and FLOW_RE.match(pipeline_id)):
            raise StoreRefused("流程 id 格式不符")
        resolved = sorted(set(resolved))
        if len(resolved) > RESOLVED_MAX:
            raise StoreRefused(f"已解除的失敗超過 {RESOLVED_MAX} 筆，需要人工處理")
        if not all(isinstance(x, str) and FAILURE_ID_RE.match(x) for x in resolved):
            raise StoreRefused("失敗的身分格式不符")
        tmp = f".{RELEASED}.tmp"
        try:
            os.unlink(tmp, dir_fd=self.fd)                     # left by a crash: never trusted
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                     dir_fd=self.fd)
        try:
            data = json.dumps({"v": 2, "pipeline_id": pipeline_id, "released_at": now, "resolved": resolved})
            _write_all(fd, data.encode())
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(tmp, dir_fd=self.fd)         # the old record stays as it was
            raise
        os.close(fd)
        os.replace(tmp, RELEASED, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        _fsync_dir(self.fd)

    def release_record_bytes(self) -> int:
        total = 0
        for name in (RELEASED, f".{RELEASED}.tmp"):
            try:
                total += os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_size
            except FileNotFoundError:
                pass
        return total

    def remove_start(self, pipeline_id: str, expected: float, *, launch_id: str | None = None) -> None:
        """Undo a start record no session ever started from: the open that
        wrote it failed before any journal existed (or, v29.7, recovery
        proved it). Refuses unless the record is exactly that one (flow,
        time and, when given, launch)."""
        rec = self.start_record()
        if (rec is None or rec["pipeline_id"] != pipeline_id or rec["started_at"] != expected
                or (launch_id is not None and rec["launch_id"] != launch_id)):
            raise StoreRefused("流程開始時間的紀錄不是這次寫入的，不能移除")
        os.unlink(STARTED, dir_fd=self.fd)
        _fsync_dir(self.fd)


# holds (design 7) -------------------------------------------------------------------

def _holds_dir(base, *, create: bool) -> tuple[int, int]:
    state = os.open(str(base), _DIR)
    try:
        return state, _open_dir(HOLDS, state, create=create)
    except BaseException:
        os.close(state)
        raise


def is_held(base, pipeline_id: str) -> bool:
    """True when the flow is stopped, or when that cannot be ruled out.
    Only a missing ``holds/`` (inside a state directory that opened) or a
    missing hold file means "not held"."""
    if not (isinstance(pipeline_id, str) and FLOW_RE.match(pipeline_id)):
        return True
    try:
        state = os.open(str(base), _DIR)
    except OSError:
        return True                       # no state directory: nothing can be ruled out
    try:
        holds = _open_dir(HOLDS, state, create=False)
    except FileNotFoundError:
        os.close(state)
        return False
    except (OSError, StoreRefused):
        os.close(state)
        return True
    try:
        os.stat(pipeline_id, dir_fd=holds, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True
    finally:
        os.close(holds)
        os.close(state)


def hold(base, pipeline_id: str, reason: str) -> None:
    if not (isinstance(pipeline_id, str) and FLOW_RE.match(pipeline_id)):
        raise StoreRefused("流程 id 格式不符")
    if not isinstance(reason, str):
        raise StoreRefused("停止原因必須是字串")
    reason = sp.sanitize(reason)[:256]
    state, holds = _holds_dir(base, create=True)
    try:
        tmp = f".{pipeline_id}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=holds)
        try:
            _write_all(fd, json.dumps({"v": 1, "reason": reason, "at": time.time()}, ensure_ascii=False).encode())
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(tmp, dir_fd=holds)
            raise
        os.close(fd)
        os.replace(tmp, pipeline_id, src_dir_fd=holds, dst_dir_fd=holds)
        _fsync_dir(holds)
    finally:
        os.close(holds)
        os.close(state)


def release(base, pipeline_id: str, *, warnings: list[str] | None = None) -> bool:
    if not (isinstance(pipeline_id, str) and FLOW_RE.match(pipeline_id)):
        raise StoreRefused("流程 id 格式不符")
    try:
        state, holds = _holds_dir(base, create=False)
    except FileNotFoundError:
        return False
    try:
        try:
            os.unlink(pipeline_id, dir_fd=holds)
        except FileNotFoundError:
            return False
        try:
            _fsync_dir(holds)
        except StoreRefused:
            # released.json was durably written first, so the user's continue
            # action has taken effect. Do not recreate the hold: a crash may
            # make the unlink disappear and restore the marker, which safely
            # stops the flow until the user presses continue again.
            if warnings is not None:
                warnings.append("hold_removal_not_durable")
            return True
        return True
    finally:
        os.close(holds)
        os.close(state)
