"""Strict, bounded JSON and file reading for data VBear did not write itself.

Design 2.3 「所有 JSON 的共同規則」 applies to every JSON source the
coordinator reads (Claude and Codex events, rollouts, auth.json,
~/.claude.json, logs, manifests, preview records):

  * Before ``json.loads`` sees anything, one linear pass over the raw bytes
    counts, outside strings, ``{`` ``[`` ``,`` ``:`` (the unit's total nodes)
    and the nesting depth, and checks the unit's byte size. Only input within
    all three limits is parsed, so the parser cannot be driven into deep
    recursion or huge allocations.
  * Parsing is strict: valid UTF-8, no duplicate keys, no NaN/Infinity, and no
    number that only parses to a non-finite float (``1e400``).
  * Every exception from decoding, scanning or parsing (RecursionError and
    MemoryError included) becomes a failed result; none escapes.
  * Files are read through one descriptor: O_NOFOLLOW (and O_NONBLOCK, so a
    FIFO cannot block the open), then ``fstat`` must show a regular file owned
    by this user within the size limit, then the content is read in chunks
    and reading stops as soon as it would pass the limit.
  * Multi-line sources are parsed a line at a time; each line is a parse unit
    with its own limits, so memory is bounded by the line limit.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from dataclasses import dataclass
from typing import Any, Iterator

KiB = 1 << 10
MiB = 1 << 20

READ_CHUNK = 64 * KiB


@dataclass(frozen=True)
class Limits:
    unit_bytes: int            # one parse unit (a line, or the whole file)
    unit_nodes: int            # { [ , : outside strings, summed over the unit
    depth: int                 # nesting depth of [ and {
    file_bytes: int | None     # the whole file; None when bounded elsewhere


# The table in design 2.3.
CLAUDE_STDOUT = Limits(1 * MiB, 200_000, 64, None)        # bounded by log and turn limits
CODEX_EVENTS = Limits(1 * MiB, 200_000, 64, 8 * MiB)
ROLLOUT = Limits(4 * MiB, 500_000, 64, 64 * MiB)
SESSION_LOG = Limits(512 * KiB, 100_000, 32, 16 * MiB)
MANIFEST = Limits(64 * KiB, 10_000, 16, 64 * KiB)         # review and launch manifests
AUTH_JSON = Limits(64 * KiB, 1_000, 8, 64 * KiB)
CLAUDE_JSON = Limits(16 * MiB, 2_000_000, 64, 16 * MiB)   # ~/.claude.json
PREVIEW = Limits(128 * KiB, 10_000, 16, 128 * KiB)         # dispatch and acceptance previews


@dataclass(frozen=True)
class Parsed:
    ok: bool
    value: Any = None
    problem: str = ""


class ReadRefused(Exception):
    """A file that cannot be read under the rules; ``missing`` tells
    "does not exist" apart from every other refusal."""

    def __init__(self, reason: str, *, missing: bool = False):
        super().__init__(reason)
        self.missing = missing


# --- the pre-parse scan -------------------------------------------------------

# Only the bytes that matter to the scan: quote, backslash and the four
# structural bytes. Each is visited once (an escaped byte is skipped by
# position), so the scan is linear even for hostile input such as a long run
# of escaped quotes that never closes.
_SPECIAL = re.compile(rb'["\\\[\]{},:]')


def scan(raw: bytes, limits: Limits) -> str | None:
    """None when ``raw`` is within the unit's byte, node and depth limits,
    otherwise why not. Strings are skipped, so brackets inside them do not
    count. For malformed input the counts still bound what ``json.loads``
    could build before it reports the error."""
    if not isinstance(raw, (bytes, bytearray)):
        return "不是位元組資料"
    if len(raw) > limits.unit_bytes:
        return f"超過 {limits.unit_bytes} bytes"
    nodes = depth = 0
    in_string = False
    skip_to = -1
    for m in _SPECIAL.finditer(raw):
        i = m.start()
        if i < skip_to:                    # the byte after a backslash
            continue
        c = raw[i]
        if in_string:
            if c == 0x5C:                  # \ escapes the next byte
                skip_to = i + 2
            elif c == 0x22:
                in_string = False
            continue
        if c == 0x22:
            in_string = True
        elif c in (0x5B, 0x7B):            # [ {
            depth += 1
            nodes += 1
            if depth > limits.depth:
                return f"巢狀深度超過 {limits.depth}"
        elif c in (0x5D, 0x7D):            # ] }
            depth -= 1
        elif c in (0x2C, 0x3A):            # , :
            nodes += 1
        if nodes > limits.unit_nodes:
            return f"節點數超過 {limits.unit_nodes}"
    return None


# --- strict parsing -----------------------------------------------------------

class _Reject(ValueError):
    pass


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _Reject(f"重複的 key：{key[:40]!r}")
        out[key] = value
    return out


def _constant(name):
    raise _Reject(f"不接受 {name}")


def _float(text):
    value = float(text)
    if not math.isfinite(value):
        raise _Reject("數字超出有限範圍")
    return value


def loads(raw: bytes, limits: Limits) -> Parsed:
    """Scan, decode and parse one unit. Never raises."""
    try:
        problem = scan(raw, limits)
        if problem:
            return Parsed(False, problem=problem)
        text = bytes(raw).decode("utf-8")          # strict: invalid UTF-8 raises
        return Parsed(True, json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant,
                                       parse_float=_float))
    except _Reject as exc:
        return Parsed(False, problem=str(exc))
    except UnicodeDecodeError:
        return Parsed(False, problem="不是合法的 UTF-8")
    except RecursionError:
        return Parsed(False, problem="巢狀過深")
    except MemoryError:
        return Parsed(False, problem="記憶體不足")
    except Exception as exc:  # json.JSONDecodeError, ValueError (huge ints), anything else
        return Parsed(False, problem=f"JSON 格式錯誤（{type(exc).__name__}）")


def loads_object(raw: bytes, limits: Limits) -> Parsed:
    """``loads``, and the root must be an object."""
    parsed = loads(raw, limits)
    if parsed.ok and not isinstance(parsed.value, dict):
        return Parsed(False, problem="根節點不是物件")
    return parsed


# --- reading files through one descriptor -------------------------------------

def open_owned(path, *, dir_fd: int | None = None, max_bytes: int) -> tuple[int, os.stat_result]:
    """Open a regular file owned by this user, at most ``max_bytes`` long,
    without following a symlink at the last component. Returns the open fd
    (the caller closes it) and its fstat."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError as exc:
        raise ReadRefused("檔案不存在", missing=True) from exc
    except OSError as exc:
        raise ReadRefused(f"無法開啟（{exc.strerror or type(exc).__name__}）") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReadRefused("不是一般檔案")
        if st.st_uid != os.geteuid():
            raise ReadRefused("不是目前的使用者擁有")
        if st.st_size > max_bytes:
            raise ReadRefused(f"超過 {max_bytes} bytes")
    except BaseException:
        os.close(fd)
        raise
    return fd, st


def read_fd(fd: int, max_bytes: int) -> bytes:
    """Everything from the current position, in chunks; refuses as soon as
    more than ``max_bytes`` would have been read (the file may grow after
    ``fstat``)."""
    parts, total = [], 0
    while True:
        try:
            chunk = os.read(fd, min(READ_CHUNK, max_bytes + 1 - total))
        except OSError as exc:
            raise ReadRefused(f"讀取失敗（{exc.strerror or type(exc).__name__}）") from exc
        if not chunk:
            return b"".join(parts)
        total += len(chunk)
        if total > max_bytes:
            raise ReadRefused(f"超過 {max_bytes} bytes")
        parts.append(chunk)


def read_owned(path, *, dir_fd: int | None = None, max_bytes: int) -> bytes:
    fd, _ = open_owned(path, dir_fd=dir_fd, max_bytes=max_bytes)
    try:
        return read_fd(fd, max_bytes)
    finally:
        os.close(fd)


def load_owned_object(path, limits: Limits, *, dir_fd: int | None = None) -> Parsed:
    """A whole-file JSON object under ``limits``. Never raises; a missing
    file is a failed result whose problem says so."""
    try:
        raw = read_owned(path, dir_fd=dir_fd, max_bytes=min(limits.file_bytes or limits.unit_bytes,
                                                            limits.unit_bytes))
    except ReadRefused as exc:
        return Parsed(False, problem=str(exc))
    except Exception as exc:
        return Parsed(False, problem=f"無法讀取（{type(exc).__name__}）")
    return loads_object(raw, limits)


# --- multi-line sources ---------------------------------------------------------

class LineError(Exception):
    """The file as a whole breaks the rules: a line over the unit limit, the
    file over its limit, a read error, or a last line without a newline."""


def iter_lines(fd: int, limits: Limits) -> Iterator[bytes]:
    """Each complete line (without its ``\\n``), read in chunks. Raises
    LineError when a line passes ``unit_bytes``, the file passes
    ``file_bytes``, or the data does not end with a newline. Memory is
    bounded by one line plus one chunk."""
    buf = bytearray()
    total = 0
    while True:
        try:
            chunk = os.read(fd, READ_CHUNK)
        except OSError as exc:
            raise LineError(f"讀取失敗（{exc.strerror or type(exc).__name__}）") from exc
        if not chunk:
            break
        total += len(chunk)
        if limits.file_bytes is not None and total > limits.file_bytes:
            raise LineError(f"檔案超過 {limits.file_bytes} bytes")
        buf += chunk
        while True:
            cut = buf.find(b"\n")
            if cut < 0:
                break
            if cut > limits.unit_bytes:
                raise LineError(f"有一行超過 {limits.unit_bytes} bytes")
            line = bytes(buf[:cut])
            del buf[:cut + 1]
            yield line
        if len(buf) > limits.unit_bytes:
            raise LineError(f"有一行超過 {limits.unit_bytes} bytes")
    if buf:
        raise LineError("最後一行沒有以換行結尾")


def iter_data_lines(data: bytes, limits: Limits) -> Iterator[bytes]:
    """``iter_lines`` for bytes that were read once already (so that what is
    judged and what is saved are the same bytes). Same errors."""
    if limits.file_bytes is not None and len(data) > limits.file_bytes:
        raise LineError(f"檔案超過 {limits.file_bytes} bytes")
    pos = 0
    while pos < len(data):
        cut = data.find(b"\n", pos)
        if cut < 0:
            if len(data) - pos > limits.unit_bytes:
                raise LineError(f"有一行超過 {limits.unit_bytes} bytes")
            raise LineError("最後一行沒有以換行結尾")
        if cut - pos > limits.unit_bytes:
            raise LineError(f"有一行超過 {limits.unit_bytes} bytes")
        yield data[pos:cut]
        pos = cut + 1


def iter_json_lines(fd: int, limits: Limits) -> Iterator[Parsed]:
    """``loads_object`` for each line. A whole-file problem (LineError) ends
    the iteration with one failed result after the lines before it."""
    try:
        for line in iter_lines(fd, limits):
            yield loads_object(line, limits)
    except LineError as exc:
        yield Parsed(False, problem=str(exc))
    except Exception as exc:
        yield Parsed(False, problem=f"讀取失敗（{type(exc).__name__}）")
