"""Does a commit exist in a repository? Answered from the object files alone.

``commit_exists(workdir, sha)`` returns True, False, or None ("cannot tell").
It backs principle 8 (design 5.7): an executor's reported ``head``, the
commit a review is started for, and the merge gate all need to know that the
commit really is in the repository.

Rules, in short (the design is the reference):
  * Read-only, standard library only, never runs git (a repository's config
    can make git execute programs; see git_head).
  * Every path is opened one directory at a time from ``/`` with
    O_NOFOLLOW, including the search for the repository, the ``gitdir:``
    of a worktree and its ``commondir``. A symlink anywhere gives None. An
    agent that swaps directories meanwhile can only make VBear read other
    content inside the repository, which the hash check then rejects.
  * True only when the object's full content was obtained, its type is
    commit, and the hash of ``commit <size>\\0<content>`` (SHA-1 for 40 hex
    digits, SHA-256 for 64) equals the requested sha. For an object from a
    pack, the pack and its index must also pass their checksums.
  * Every idx passes its own checksum before it is searched, so "not found"
    is never read off a damaged index.
  * The object exists with a matching hash but is not a commit: False. Not
    found locally and no alternates: False. Not found but alternates exist,
    or anything malformed, over a limit, too slow or symlinked: None.

None always means "not verified": callers treat it as a failed check.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
import time
import zlib

# --- limits (design 5.7) ---
MAX_PARENTS = 64
MAX_SMALL_FILE = 4096              # a .git file, commondir
LOOSE_MAX_COMPRESSED = 2 << 20
OBJECT_MAX = 1 << 20               # any object, intermediate or result, and delta data
TOTAL_INFLATE_MAX = 16 << 20       # all inflating in one check
OBJECT_MAX_COMPRESSED = 2 << 20    # compressed input read for one pack entry
INFLATE_CHUNK = 64 << 10
DELTA_MAX_DEPTH = 50
DEADLINE_S = 2.0
PACK_DIR_MAX_ENTRIES = 10_000
IDX_MAX_FILES = 1_000
IDX_MAX_OBJECTS = 50_000_000
IDX_MAX_BYTES = 2 << 30
PACK_MAX_BYTES = 64 << 30
CHECKSUM_PACK_MAX = 512 << 20      # larger packs are not verified: None
CHECKSUM_CHUNK = 1 << 20
CHECKSUM_DEADLINE_S = 10.0

# \Z, not $: $ also matches before a trailing newline.
SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_IDX_NAME = re.compile(r"^pack-(?:[0-9a-f]{40}|[0-9a-f]{64})\.idx\Z")
_TYPES = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}
_OFS_DELTA, _REF_DELTA = 6, 7
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class _Undecidable(Exception):
    pass


# Verified (idx, pack) pairs, keyed by both files' identity. ctime moves on
# any content or attribute change and cannot be set back by a user, so an
# in-place edit misses the cache.
_checksum_cache: set[tuple] = set()
_cache_lock = threading.Lock()


def _identity(st: os.stat_result) -> tuple:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class _Check:
    """One call: open descriptors, the deadline and the inflate budget."""

    def __init__(self, algo: str):
        self.algo = algo
        self.hashlen = hashlib.new(algo).digest_size
        self.deadline = time.monotonic() + DEADLINE_S
        self.checksum_deadline: float | None = None   # starts at the first verification
        self.inflated = 0
        self.fds: list[int] = []

    def tick(self):
        if time.monotonic() > self.deadline:
            raise _Undecidable("逾時")

    def keep(self, fd: int) -> int:
        self.fds.append(fd)
        return fd

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds.clear()

    # opening, never through a symlink

    def open_dir(self, name: str, dir_fd: int | None) -> int:
        self.tick()
        try:
            return self.keep(os.open(name, _DIR, dir_fd=dir_fd))
        except OSError as exc:
            raise _Undecidable(f"無法開啟目錄（{exc.strerror}）") from exc

    def open_dir_if_exists(self, name: str, dir_fd: int) -> int | None:
        self.tick()
        try:
            return self.keep(os.open(name, _DIR, dir_fd=dir_fd))
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _Undecidable(f"無法開啟目錄（{exc.strerror}）") from exc

    def open_file_if_exists(self, name: str, dir_fd: int) -> tuple[int, os.stat_result] | None:
        self.tick()
        try:
            fd = self.keep(os.open(name, _FILE, dir_fd=dir_fd))
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _Undecidable(f"無法開啟檔案（{exc.strerror}）") from exc
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise _Undecidable("不是一般檔案")
        return fd, st

    def open_path(self, path: str) -> list[tuple[str, int]]:
        """Each directory from ``/`` down to the work directory, as (path,
        fd). ``.`` and ``..`` are refused rather than collapsed: collapsing
        them as text would skip a component that might be a symlink."""
        if not isinstance(path, str) or "\0" in path or not path.startswith("/"):
            raise _Undecidable("路徑必須是絕對路徑")
        chain = [("/", self.open_dir("/", None))]
        current = "/"
        for part in path.split("/"):
            if not part:
                continue
            if part in (".", ".."):
                raise _Undecidable("路徑格式不符")
            current = os.path.join(current, part)
            chain.append((current, self.open_dir(part, chain[-1][1])))
        return chain

    def open_pointer(self, target: str, base_fd: int) -> int:
        """A ``gitdir:`` or ``commondir`` target: absolute from ``/``,
        relative from ``base_fd``. Every component, ``..`` included, is
        opened in turn without following a symlink, so the result is the
        directory the kernel would reach, or None when that needs a
        symlink."""
        if not target or "\0" in target:
            raise _Undecidable("路徑格式不符")
        fd = self.open_dir("/", None) if target.startswith("/") else base_fd
        for part in target.split("/"):
            if part in ("", "."):
                continue
            fd = self.open_dir(part, fd)
        return fd

    def pread(self, fd: int, n: int, pos: int) -> bytes:
        self.tick()
        try:
            data = os.pread(fd, n, pos)
        except OSError as exc:
            raise _Undecidable(f"讀取失敗（{exc.strerror}）") from exc
        if len(data) != n:
            raise _Undecidable("檔案被截斷")
        return data

    def read_upto(self, fd: int, limit: int) -> bytes:
        """The whole file from the current position; more than ``limit``
        bytes is refused (read in a loop: a read may return less)."""
        parts, total = [], 0
        while True:
            self.tick()
            chunk = os.read(fd, min(INFLATE_CHUNK, limit + 1 - total))
            if not chunk:
                return b"".join(parts)
            total += len(chunk)
            if total > limit:
                raise _Undecidable("檔案過大")
            parts.append(chunk)

    def read_small(self, fd: int) -> str:
        data = self.read_upto(fd, MAX_SMALL_FILE)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _Undecidable("不是 UTF-8 文字") from exc

    def inflate(self, fd: int, pos: int, end: int, size: int) -> bytes:
        """Inflate one zlib stream starting at ``pos`` (reading no further
        than ``end``) that must produce exactly ``size`` bytes and end."""
        if size > OBJECT_MAX:
            raise _Undecidable("物件過大")
        d = zlib.decompressobj()
        out = bytearray()
        read = 0
        while not d.eof:
            self.tick()
            if d.unconsumed_tail:
                chunk = d.unconsumed_tail
            else:
                n = min(INFLATE_CHUNK, end - pos, OBJECT_MAX_COMPRESSED - read)
                if n <= 0:
                    raise _Undecidable("壓縮資料超過上限或超出範圍")
                chunk = os.pread(fd, n, pos)
                if not chunk:
                    raise _Undecidable("檔案被截斷")
                pos += len(chunk)
                read += len(chunk)
            try:
                piece = d.decompress(chunk, size + 1 - len(out))
            except zlib.error as exc:
                raise _Undecidable("壓縮資料損壞") from exc
            out += piece
            self.inflated += len(piece)
            if len(out) > size:
                raise _Undecidable("解壓後大小與宣告不符")
            if self.inflated > TOTAL_INFLATE_MAX:
                raise _Undecidable("解壓總量超過上限")
        if len(out) != size:
            raise _Undecidable("解壓後大小與宣告不符")
        return bytes(out)

    def matches(self, kind: str, data: bytes, sha: str) -> bool:
        h = hashlib.new(self.algo)
        h.update(f"{kind} {len(data)}\0".encode())
        h.update(data)
        return h.hexdigest() == sha


# --- finding the object store -------------------------------------------------

def _objects_dir(chk: _Check, workdir: str) -> int:
    chain = chk.open_path(workdir)
    home = os.path.realpath(os.path.expanduser("~"))
    for depth, (path, fd) in enumerate(reversed(chain)):
        if depth >= MAX_PARENTS or path == home or path == "/":
            raise _Undecidable("不在 git 儲存庫內")
        chk.tick()
        try:
            entry = chk.keep(os.open(".git", _FILE, dir_fd=fd))
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _Undecidable(f"無法開啟 .git（{exc.strerror}）") from exc
        st = os.fstat(entry)
        if stat.S_ISDIR(st.st_mode):
            gitdir = entry
        elif stat.S_ISREG(st.st_mode):
            text = chk.read_small(entry).strip()
            if not text.startswith("gitdir:"):
                raise _Undecidable(".git 檔案格式不符")
            gitdir = chk.open_pointer(text[len("gitdir:"):].strip(), fd)
        else:
            raise _Undecidable(".git 不是資料夾或檔案")
        common = gitdir
        found = chk.open_file_if_exists("commondir", gitdir)
        if found is not None:
            common = chk.open_pointer(chk.read_small(found[0]).strip(), gitdir)
        return chk.open_dir("objects", common)
    raise _Undecidable("不在 git 儲存庫內")


# --- loose objects -------------------------------------------------------------

def _loose(chk: _Check, objects: int, sha: str) -> bool | None:
    """True/False when the loose object is there and genuine; None when
    there is no loose object (look in packs next)."""
    sub = chk.open_dir_if_exists(sha[:2], objects)
    if sub is None:
        return None
    found = chk.open_file_if_exists(sha[2:], sub)
    if found is None:
        return None
    fd, st = found
    if st.st_size > LOOSE_MAX_COMPRESSED:
        raise _Undecidable("loose 物件過大")
    data = chk.read_upto(fd, LOOSE_MAX_COMPRESSED)
    d = zlib.decompressobj()
    try:
        raw = d.decompress(data, OBJECT_MAX + 64 + 1)
    except zlib.error as exc:
        raise _Undecidable("loose 物件損壞") from exc
    chk.inflated += len(raw)
    if not d.eof or d.unused_data or len(raw) > OBJECT_MAX + 64:
        raise _Undecidable("loose 物件損壞或過大")
    header, sep, body = raw.partition(b"\0")
    kind, _, size = header.partition(b" ")
    if not sep or kind.decode("ascii", "replace") not in _TYPES.values() or not size.isdigit():
        raise _Undecidable("loose 物件標頭不符")
    if int(size) != len(body) or len(body) > OBJECT_MAX:
        raise _Undecidable("loose 物件大小不符")
    kind_s = kind.decode()
    if not chk.matches(kind_s, body, sha):
        raise _Undecidable("loose 物件的雜湊不符")
    return kind_s == "commit"


# --- packs ---------------------------------------------------------------------

def _varint_size(chk: _Check, fd: int, pos: int) -> tuple[int, int, int]:
    """Pack entry header: (type, size, position after the header)."""
    b = chk.pread(fd, 1, pos)[0]
    pos += 1
    kind, size, shift = (b >> 4) & 7, b & 15, 4
    while b & 0x80:
        if shift > 60:
            raise _Undecidable("pack 物件標頭過長")
        b = chk.pread(fd, 1, pos)[0]
        pos += 1
        size |= (b & 0x7F) << shift
        shift += 7
    return kind, size, pos


def _delta_varint(data: bytes, i: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        if i >= len(data) or shift > 63:
            raise _Undecidable("delta 格式不符")
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, i


def _apply_delta(base: bytes, delta: bytes) -> bytes:
    src_size, i = _delta_varint(delta, 0)
    dst_size, i = _delta_varint(delta, i)
    if src_size != len(base):
        raise _Undecidable("delta 的 base 大小不符")
    if dst_size > OBJECT_MAX:
        raise _Undecidable("delta 結果過大")
    out = bytearray()
    while i < len(delta):
        op = delta[i]
        i += 1
        if op & 0x80:
            offset = size = 0
            for bit, shift in ((0x01, 0), (0x02, 8), (0x04, 16), (0x08, 24)):
                if op & bit:
                    if i >= len(delta):
                        raise _Undecidable("delta 格式不符")
                    offset |= delta[i] << shift
                    i += 1
            for bit, shift in ((0x10, 0), (0x20, 8), (0x40, 16)):
                if op & bit:
                    if i >= len(delta):
                        raise _Undecidable("delta 格式不符")
                    size |= delta[i] << shift
                    i += 1
            if size == 0:
                size = 0x10000
            if offset + size > len(base):
                raise _Undecidable("delta 複製範圍超出 base")
            out += base[offset:offset + size]
        elif op:
            if i + op > len(delta):
                raise _Undecidable("delta 格式不符")
            out += delta[i:i + op]
            i += op
        else:
            raise _Undecidable("delta 指令無效")
        if len(out) > dst_size:
            raise _Undecidable("delta 結果大小不符")
    if len(out) != dst_size:
        raise _Undecidable("delta 結果大小不符")
    return bytes(out)


class _Pack:
    def __init__(self, chk: _Check, pack_dir: int, idx_name: str):
        self.chk = chk
        h = chk.hashlen
        found = chk.open_file_if_exists(idx_name, pack_dir)
        if found is None:
            raise _Undecidable("idx 消失")
        self.idx, self.idx_st = found
        size = self.idx_st.st_size
        if size > IDX_MAX_BYTES:
            raise _Undecidable("idx 過大")
        head = chk.pread(self.idx, 8 + 1024, 0)
        if head[:4] != b"\xfftOc" or int.from_bytes(head[4:8], "big") != 2:
            raise _Undecidable("idx 不是 v2 格式")
        fanout = [int.from_bytes(head[8 + 4 * k:12 + 4 * k], "big") for k in range(256)]
        if any(fanout[k] > fanout[k + 1] for k in range(255)):
            raise _Undecidable("idx 的 fanout 不是遞增")
        n = fanout[255]
        if n > IDX_MAX_OBJECTS:
            raise _Undecidable("idx 物件數超過上限")
        base = 8 + 1024 + n * (h + 8) + 2 * h
        extra = size - base
        if extra < 0 or extra % 8 or extra > 8 * n:
            raise _Undecidable("idx 大小不符")
        self.fanout, self.n, self.large = fanout, n, extra // 8
        pack = chk.open_file_if_exists(idx_name[:-len(".idx")] + ".pack", pack_dir)
        if pack is None:
            raise _Undecidable("找不到對應的 pack")
        self.pack, self.pack_st = pack
        if self.pack_st.st_size > PACK_MAX_BYTES:
            raise _Undecidable("pack 過大")
        self.end = self.pack_st.st_size - h          # entries end before the trailer
        if self.end < 12:
            raise _Undecidable("pack 過小")
        ph = chk.pread(self.pack, 12, 0)
        if ph[:4] != b"PACK" or int.from_bytes(ph[4:8], "big") not in (2, 3) \
                or int.from_bytes(ph[8:12], "big") != n:
            raise _Undecidable("pack 標頭不符")

    def find(self, want: bytes) -> int | None:
        """The pack offset of ``want``, or None when this idx lacks it."""
        h, n = self.chk.hashlen, self.n
        lo = self.fanout[want[0] - 1] if want[0] else 0
        hi = self.fanout[want[0]]
        while lo < hi:
            mid = (lo + hi) // 2
            name = self.chk.pread(self.idx, h, 1032 + mid * h)
            if name == want:
                break
            if name < want:
                lo = mid + 1
            else:
                hi = mid
        else:
            return None
        raw = int.from_bytes(self.chk.pread(self.idx, 4, 1032 + n * (h + 4) + mid * 4), "big")
        if raw & 0x80000000:
            k = raw & 0x7FFFFFFF
            if k >= self.large:
                raise _Undecidable("idx 的大 offset 超出範圍")
            offset = int.from_bytes(self.chk.pread(self.idx, 8, 1032 + n * (h + 8) + k * 8), "big")
        else:
            offset = raw
        if not 12 <= offset < self.end:
            raise _Undecidable("idx 的 offset 超出範圍")
        return offset

    def read(self, offset: int) -> tuple[str, bytes]:
        """The object at ``offset``, following delta bases."""
        chain: list[bytes] = []
        seen = 0
        while True:
            if seen > DELTA_MAX_DEPTH:
                raise _Undecidable("delta 深度超過上限")
            kind, size, pos = _varint_size(self.chk, self.pack, offset)
            if kind in _TYPES:
                data = self.chk.inflate(self.pack, pos, self.end, size)
                break
            if kind == _OFS_DELTA:
                b = self.chk.pread(self.pack, 1, pos)[0]
                pos += 1
                rel = b & 0x7F
                while b & 0x80:
                    if rel > PACK_MAX_BYTES:
                        raise _Undecidable("delta offset 格式不符")
                    b = self.chk.pread(self.pack, 1, pos)[0]
                    pos += 1
                    rel = ((rel + 1) << 7) | (b & 0x7F)
                base_offset = offset - rel
                if not 12 <= base_offset < offset:
                    raise _Undecidable("delta base 的 offset 超出範圍")
            elif kind == _REF_DELTA:
                ref = self.chk.pread(self.pack, self.chk.hashlen, pos)
                pos += self.chk.hashlen
                base_offset = self.find(ref)
                if base_offset is None:
                    raise _Undecidable("delta base 不在同一個 pack")
            else:
                raise _Undecidable("pack 物件型別不符")
            chain.append(self.chk.inflate(self.pack, pos, self.end, size))
            offset = base_offset
            seen += 1
        kind_s = _TYPES[kind]
        for delta in reversed(chain):
            self.chk.tick()
            data = _apply_delta(data, delta)
        return kind_s, data

    def unchanged(self):
        if (_identity(os.fstat(self.idx)) != _identity(self.idx_st)
                or _identity(os.fstat(self.pack)) != _identity(self.pack_st)):
            raise _Undecidable("pack 或 idx 在讀取期間改變")

    def _cached(self, key: tuple) -> bool:
        self.unchanged()
        with _cache_lock:
            return key in _checksum_cache

    def _remember(self, key: tuple):
        self.unchanged()
        with _cache_lock:
            if len(_checksum_cache) > 4096:
                _checksum_cache.clear()
            _checksum_cache.add(key)

    def _deadline(self) -> float:
        if self.chk.checksum_deadline is None:
            self.chk.checksum_deadline = time.monotonic() + CHECKSUM_DEADLINE_S
        return self.chk.checksum_deadline

    def verify_idx(self):
        """The idx's own checksum, before it is searched: an idx that fails
        it can neither show an object present nor show it absent."""
        key = ("idx", self.chk.algo, _identity(self.idx_st))
        if self._cached(key):
            return
        h = self.chk.hashlen
        size = self.idx_st.st_size
        if self._digest(self.idx, size - h, self._deadline()) != self.chk.pread(self.idx, h, size - h):
            raise _Undecidable("idx 校驗和不符")
        self._remember(key)

    def verify_pack(self):
        """For the pair the object came from: the pack checksum the idx
        records and the pack's own trailer, recomputed. Cached by both
        files' identity."""
        key = ("pack", self.chk.algo, _identity(self.idx_st), _identity(self.pack_st))
        if self._cached(key):
            return
        if self.pack_st.st_size > CHECKSUM_PACK_MAX:
            raise _Undecidable("pack 超過可驗證的大小")
        h = self.chk.hashlen
        recorded = self.chk.pread(self.idx, h, self.idx_st.st_size - 2 * h)
        trailer = self.chk.pread(self.pack, h, self.end)
        if trailer != recorded:
            raise _Undecidable("idx 記錄的 pack 校驗和不符")
        if self._digest(self.pack, self.end, self._deadline()) != trailer:
            raise _Undecidable("pack 校驗和不符")
        self._remember(key)

    def _digest(self, fd: int, length: int, deadline: float) -> bytes:
        h = hashlib.new(self.chk.algo)
        pos = 0
        while pos < length:
            if time.monotonic() > deadline:
                raise _Undecidable("校驗和驗證逾時")
            n = min(CHECKSUM_CHUNK, length - pos)
            chunk = os.pread(fd, n, pos)
            if len(chunk) != n:
                raise _Undecidable("檔案被截斷")
            h.update(chunk)
            pos += n
        return h.digest()


def _packed(chk: _Check, objects: int, sha: str) -> bool | None:
    """True/False when a pack holds the object; None when none does."""
    pack_dir = chk.open_dir_if_exists("pack", objects)
    if pack_dir is None:
        return None
    names = []
    seen = 0
    with os.scandir(pack_dir) as entries:
        for entry in entries:
            chk.tick()
            seen += 1
            if seen > PACK_DIR_MAX_ENTRIES:
                raise _Undecidable("pack 目錄項目過多")
            if _IDX_NAME.match(entry.name):
                names.append(entry.name)
    if len(names) > IDX_MAX_FILES:
        raise _Undecidable("idx 檔案過多")
    want = bytes.fromhex(sha)
    for name in sorted(names):
        pack = _Pack(chk, pack_dir, name)
        pack.verify_idx()
        offset = pack.find(want)
        if offset is None:
            continue
        kind, data = pack.read(offset)
        pack.unchanged()
        if not chk.matches(kind, data, sha):
            raise _Undecidable("pack 物件的雜湊不符")
        pack.verify_pack()
        return kind == "commit"
    return None


def _has_alternates(chk: _Check, objects: int) -> bool:
    info = chk.open_dir_if_exists("info", objects)
    if info is None:
        return False
    try:
        os.stat("alternates", dir_fd=info, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _Undecidable(f"無法檢查 alternates（{exc.strerror}）") from exc
    return True


def commit_exists(workdir, sha) -> bool | None:
    """True, False or None; see the module docstring. Never raises."""
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        return None
    chk = _Check("sha1" if len(sha) == 40 else "sha256")
    try:
        objects = _objects_dir(chk, workdir)
        found = _loose(chk, objects, sha)
        if found is None:
            found = _packed(chk, objects, sha)
        if found is None:
            return None if _has_alternates(chk, objects) else False
        return found
    except _Undecidable:
        return None
    except Exception:  # a–d: whatever the files hold, never an exception
        return None
    finally:
        chk.close()
