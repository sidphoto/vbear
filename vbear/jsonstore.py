"""A small owner-only JSON store that fails closed, for state VBear writes.

The rules are the ones tasks.py established for tasks.json, kept here so new
stores (flows.json) get them without copying: 0600 atomic writes
(``cfg.write_private``), one cross-process ``flock`` around every
read-modify-write, and no silent recovery. A file that cannot be read safely
(not a regular file, a symlink, a second hard link), does not parse, or holds
an entry the owning module could never have written puts the store into a
blocked state: a marker is installed *before* the bad file is moved aside,
and every later read and write refuses until a person removes the marker.
The store never returns "empty" for data it failed to read.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from . import config as cfg


class StoreError(RuntimeError):
    """The store cannot be used safely right now; the message says why and
    where the files are."""


class GuardedJsonStore:
    def __init__(self, filename: str, label: str,
                 entry_problem: Callable[[Any, Any], str | None]):
        self.filename = filename
        self.label = label                      # how messages name the store, e.g. 「流程儲存」
        self.entry_problem = entry_problem      # None, or why a stored (key, value) is not ours

    # paths --------------------------------------------------------------

    def path(self) -> Path:
        return cfg.state_dir() / self.filename

    def lock_path(self) -> Path:
        return cfg.state_dir() / f"{self.filename}.lock"

    def marker_path(self) -> Path:
        return cfg.state_dir() / f"{self.filename}.corrupted"

    # reading ------------------------------------------------------------

    def _read_raw(self) -> str | None:
        """The file's text, None if it does not exist; OSError for anything
        else (not a regular file, a symlink, more than one hard link)."""
        path = self.path()
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise OSError(f"{self.filename} 不是一般檔案 (mode={oct(st.st_mode)})")
            if st.st_nlink > 1:
                raise OSError(f"{self.filename} 有多個硬連結 (nlink={st.st_nlink})，拒絕讀取")
            with os.fdopen(fd, "r", encoding="utf-8") as fh:
                fd = -1
                return fh.read()
        finally:
            if fd != -1:
                os.close(fd)

    def load(self) -> dict[str, Any]:
        """All entries, or StoreError. A missing file is an empty store."""
        marker = self.marker_path()
        if marker.exists():
            raise StoreError(f"{self.label}先前偵測到損毀，需人工復原後才能繼續讀寫。詳見 {marker}")
        path = self.path()
        try:
            raw = self._read_raw()
        except (OSError, UnicodeDecodeError) as exc:
            raise StoreError(f"無法安全讀取 {path}：{exc}；為避免資料遺失，讀寫已暫停，"
                             "請人工檢查檔案（權限、是否為符號連結或硬連結）後重試") from exc
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(f"{self.filename} 根節點必須為物件")
        except (ValueError, RecursionError) as exc:
            where = self._quarantine(exc)
            raise StoreError(f"{self.label}檔案損毀，已隔離至 {where}，請人工復原後刪除 {marker} 以恢復讀寫") from exc
        for key, value in data.items():
            problem = self.entry_problem(key, value)
            if problem is not None:
                exc = ValueError(f"項目 {key!r} 結構不符：{problem}")
                where = self._quarantine(exc)
                raise StoreError(f"{self.label}檔案含有不符結構的項目（{key!r}：{problem}），已隔離至 {where}，"
                                 f"請人工復原後刪除 {marker} 以恢復讀寫") from exc
        return data

    # writing ------------------------------------------------------------

    @contextlib.contextmanager
    def locked(self, timeout: float = 10.0):
        """Exclusive lock for one read-modify-write, across threads and processes."""
        cfg.ensure_state_dir()
        fd = os.open(self.lock_path(), os.O_CREAT | os.O_RDWR, cfg.STATE_FILE_MODE)
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise StoreError(f"{self.label}鎖定逾時（可能有其他程序正在寫入），請稍後再試")
                    time.sleep(0.02)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)

    def save(self, data: dict[str, Any]) -> None:
        """Write all entries atomically (0600). Call inside ``locked()``,
        after ``load()``; every entry must pass ``entry_problem``."""
        for key, value in data.items():
            problem = self.entry_problem(key, value)
            if problem is not None:
                raise StoreError(f"拒絕寫入不符結構的項目（{key!r}：{problem}）")
        cfg.write_private(self.path(), json.dumps(data, ensure_ascii=False, indent=2))

    # quarantine ---------------------------------------------------------

    def _quarantine(self, exc: Exception) -> Path:
        """Marker first, then move the bad file; see tasks._mark_corrupt for
        why this order makes "no file and no marker" unreachable."""
        path, marker = self.path(), self.marker_path()
        quarantine = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            self._write_marker(quarantine, exc)
        except OSError as marker_exc:
            raise StoreError(f"{self.label}損毀復原失敗：無法寫入復原標記 {marker}（{marker_exc}）。"
                             f"損毀檔案原封保留於 {path}") from marker_exc
        try:
            path.rename(quarantine)
        except OSError as move_exc:
            try:
                self._write_marker(path, exc)
            except OSError:
                pass
            raise StoreError(f"{self.label}檔案損毀，且無法搬移至 {quarantine}（{move_exc}）。"
                             f"損毀檔案原地保留於 {path}，復原標記 {marker} 已寫入，讀寫已封鎖") from move_exc
        _fsync_dir(path.parent)
        return quarantine

    def _write_marker(self, quarantine: Path, exc: Exception) -> None:
        marker = self.marker_path()
        payload = json.dumps({"detected_at": time.time(), "quarantine_file": str(quarantine),
                              "original_file": str(self.path()), "error": str(exc)},
                             ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=marker.parent, prefix=marker.name + ".", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(tmp, cfg.STATE_FILE_MODE)
            os.replace(tmp, marker)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        _fsync_dir(marker.parent)


def _fsync_dir(directory: Path) -> None:
    """Best-effort durability for a rename; never raises."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
