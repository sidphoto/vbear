"""The quota ledger for data VBear writes (design 9).

``<state>/pipelines``, ``<state>/sessions`` and ``<state>/reviews`` together
may never pass 4 GiB. The daemon is their only writer. Every writer reserves
its maximum before it starts (a stream session: its journal limit; a
dispatch: one text; a review: its outputs), writes only within that, and on
finishing returns the unused part. A new reservation is granted only when

    used + every outstanding reservation + this one <= 4 GiB.

The ledger lives in the daemon's memory only, so it cannot be lost or
damaged. On every daemon start it is rebuilt conservatively: "used" is a
fresh scan; every writer not proven finished counts at its full maximum,
whatever it already wrote. If the scan or any manifest cannot be read, no
protected write is granted until a later rebuild succeeds.

Scan: by directory fd, symlinks not followed, at most one million entries;
any error, a vanished entry, a symlink or too many entries counts as "over".
"""

from __future__ import annotations

import os
import stat

HARD_LIMIT = 4 << 30
JOURNAL_MAX = 16 << 20            # a stream session's journal (2.5; strictjson.SESSION_LOG.file_bytes)
MANIFEST_MAX = 64 << 10           # a launch manifest, as read (strictjson.MANIFEST.file_bytes)
START_RECORD_MAX = 64 << 10       # pipelines/<task>/started.json, as read (strictjson.MANIFEST.file_bytes)
# What one stream session may add (review B4): its journal; its manifest's
# growth, rewritten through a sibling temp file, so two copies at the peak;
# and the flow's start record when it is the first session.
RESERVE_SESSION = JOURNAL_MAX + 2 * MANIFEST_MAX + START_RECORD_MAX
RESERVE_DISPATCH = 64 << 10       # one dispatch text (3.5)
RESERVE_REVIEW = 96 << 20         # one review's outputs (5.2, 5.4, 5.6)
SCAN_MAX_ENTRIES = 1_000_000
ROOTS = ("pipelines", "sessions", "reviews")
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ScanFailed(Exception):
    pass


def scan(base) -> int:
    """Bytes in the three roots. ScanFailed for anything unexpected."""
    total, seen = 0, 0
    try:
        state = os.open(str(base), _DIR)
    except OSError as exc:
        raise ScanFailed(f"狀態目錄無法開啟（{exc.strerror}）") from exc
    stack: list[int] = []                  # directories opened, not yet listed
    try:
        for root in ROOTS:
            try:
                stack.append(os.open(root, _DIR, dir_fd=state))
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ScanFailed(f"{root} 無法開啟（{exc.strerror}）") from exc
        while stack:
            fd = stack.pop()
            try:
                with os.scandir(fd) as entries:
                    for entry in entries:
                        seen += 1
                        if seen > SCAN_MAX_ENTRIES:
                            raise ScanFailed("項目超過上限")
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(st.st_mode):
                            raise ScanFailed(f"發現符號連結：{entry.name[:64]!r}")
                        if stat.S_ISDIR(st.st_mode):
                            stack.append(os.open(entry.name, _DIR, dir_fd=fd))
                        elif stat.S_ISREG(st.st_mode):
                            total += st.st_size
                        else:
                            raise ScanFailed(f"不是一般檔案或資料夾：{entry.name[:64]!r}")
            except ScanFailed:
                raise
            except OSError as exc:
                raise ScanFailed(f"掃描失敗（{exc.strerror or type(exc).__name__}）") from exc
            finally:
                os.close(fd)
    finally:
        for fd in stack:                   # left over when the scan stopped early
            try:
                os.close(fd)
            except OSError:
                pass
        os.close(state)
    return total


def _amount(value) -> bool:
    """A byte count: an int (never a bool), 0 <= value <= the hard limit."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= HARD_LIMIT


class Ledger:
    def __init__(self, base, limit: int = HARD_LIMIT):
        self.base = base
        self.limit = limit
        self.used: int | None = None              # None: not rebuilt, nothing is granted
        self.reservations: dict[str, int] = {}
        self.problem = "額度尚未核算"
        self.overrun = ""                         # a writer passed its reservation: refuse until rebuilt

    def rebuild(self, outstanding: dict[str, int] | None) -> bool:
        """``outstanding``: writers not proven finished, each at its full
        maximum; None when that could not be established."""
        try:
            if outstanding is None:
                raise ScanFailed("無法判斷哪些寫入者仍在進行")
            if not isinstance(outstanding, dict) or not all(
                    isinstance(k, str) and _amount(v) for k, v in outstanding.items()):
                raise ScanFailed("進行中寫入者的保留額度不合法")
            used = scan(self.base)
        except ScanFailed as exc:
            self.used, self.reservations = None, {}
            self.problem = f"額度無法核算，需要人工檢查（{exc}）"
            return False
        self.used, self.reservations, self.problem, self.overrun = used, dict(outstanding), "", ""
        return True

    def free(self) -> int | None:
        if self.used is None:
            return None
        return self.limit - self.used - sum(self.reservations.values())

    def reserve(self, key: str, amount: int) -> str | None:
        """None when granted, else why not."""
        if self.used is None:
            return self.problem
        if self.overrun:
            return self.overrun
        if not isinstance(key, str) or not _amount(amount):
            return "保留額度必須是非負整數"
        if key in self.reservations:
            return "重複的保留"
        if self.used + sum(self.reservations.values()) + amount > self.limit:
            return (f"VBear 保存的資料已接近上限（{self.limit >> 30} GiB），"
                    "請刪除不再需要的舊流程後再試")
        self.reservations[key] = amount
        return None

    def release(self, key: str, written) -> None:
        """The writer is done: what it actually wrote becomes used, and the
        rest of its reservation is returned. A writer must stay within its
        reservation (design 9); if it did not, or its count is not a byte
        count, the true (or worst-case) amount is counted and nothing more
        is granted until the ledger is rebuilt from a scan."""
        amount = self.reservations.pop(key, None)
        if self.used is None:
            return
        if not _amount(written):
            self.used += amount if amount is not None else 0
            self.overrun = "寫入量無法核對，額度需要重新核算"
            return
        if amount is None:
            self.used += written
            self.overrun = "未保留額度就寫入，額度需要重新核算"
            return
        self.used += written
        if written > amount:
            self.overrun = f"有寫入超過保留額度（{written} > {amount}），額度需要重新核算"
