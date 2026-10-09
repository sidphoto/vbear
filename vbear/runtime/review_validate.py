"""When a Codex review is valid (design 5.5, 5.6, v29.9): the stdout events,
the report, and the rollout, all against the version's constants
(codex_constants). Pure functions over bytes and file descriptors; nothing is
written, nothing is signalled, no process is started.

A review is valid only if every rule holds; ``ReviewInvalid`` carries the
reasons, which are fixed texts that name fields and never echo a value from
the input (a value may be anything, including a lone surrogate or a secret).
Fields VBear does not read may be present and are ignored; every field it
does read has an exact type and range. Any exception while looking at the
input is itself a reason, never an exception out of here.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field

from .. import strictjson
from . import codex_constants as cc
from . import review_store

REPORT_MAX = 256 << 10
ROLLOUT_MAX = 64 << 20
MAX_REASONS = 16
VERDICTS = ("PASS", "NEEDS WORK", "BLOCKED")
BASE_NOT_ANCESTOR = "審查範圍不可信：base 不是被審 commit 的祖先"
READ_CHUNK = 1 << 20


class ReviewInvalid(Exception):
    def __init__(self, reasons, code: str | None = None):
        reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("；".join(reasons[:3]))
        self.reasons = reasons[:MAX_REASONS]
        self.code = code                     # e.g. "not_found": the rollout is not there (yet)


def _int(v, low=0, high=cc.TOKEN_MAX) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and low <= v <= high


def _text(v, limit: int) -> bool:
    """A string that is valid UTF-8 (no lone surrogate) and at most ``limit`` bytes."""
    if not isinstance(v, str):
        return False
    try:
        return len(v.encode("utf-8")) <= limit
    except Exception:
        return False


# ---- stdout events (5.5 item 2) -------------------------------------------------------------

@dataclass
class EventsResult:
    thread_id: str
    last_message: str
    usage: dict
    events: int


class EventsTracker:
    """Fed the lines of ``codex exec --json`` in order. ``feed`` raises
    ReviewInvalid at the first event that breaks a rule; ``finish`` checks
    that the stream is complete."""

    def __init__(self, c: cc.CodexConstants):
        self.c = c
        self.events = 0
        self.thread_id: str | None = None
        self.turn_started = False
        self.turn_completed = False
        self.last_message: str | None = None
        self.usage: dict | None = None

    def feed(self, line: bytes) -> None:
        try:
            self._feed(line)
        except ReviewInvalid:
            raise
        except Exception as exc:
            raise ReviewInvalid(f"事件無法檢查（{type(exc).__name__}）") from exc

    def _feed(self, line: bytes) -> None:
        c = self.c
        parsed = strictjson.loads_object(line, strictjson.CODEX_EVENTS)
        if not parsed.ok:
            raise ReviewInvalid("事件不是嚴格的 JSON 物件")
        ev = parsed.value
        self.events += 1
        kind = ev.get("type")
        if not isinstance(kind, str) or kind not in c.event_kinds:
            raise ReviewInvalid("出現未知的事件種類")
        if kind in c.failure_events:
            raise ReviewInvalid("Codex 回報失敗事件")
        if self.turn_completed:
            raise ReviewInvalid("turn.completed 之後還有事件")
        if self.events == 1:
            if kind != "thread.started":
                raise ReviewInvalid("第一個事件不是 thread.started")
            tid = ev.get("thread_id")
            if not (isinstance(tid, str) and review_store.THREAD_RE.match(tid)):
                raise ReviewInvalid("thread_id 不合法")
            self.thread_id = tid
            return
        if kind == "thread.started":
            raise ReviewInvalid("thread.started 出現不只一次")
        if kind == "turn.started":
            if self.turn_started:
                raise ReviewInvalid("turn.started 出現不只一次")
            self.turn_started = True
            return
        if not self.turn_started:
            raise ReviewInvalid("事件出現在 turn.started 之前")
        if kind in ("item.started", "item.completed"):
            item = ev.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ReviewInvalid("item 的格式不符")
            if kind == "item.completed" and item["type"] == c.message_item_type:
                text = item.get(c.message_text_key)
                if not _text(text, REPORT_MAX):
                    raise ReviewInvalid("最後一則回覆不是合法的 UTF-8 或超過 256 KiB")
                self.last_message = text
            return
        # turn.completed
        usage = ev.get("usage")
        if not isinstance(usage, dict) or not all(_int(usage.get(f)) for f in c.events_usage_fields):
            raise ReviewInvalid("turn.completed 的 usage 不合法")
        self.usage = {f: usage[f] for f in c.events_usage_fields}
        self.turn_completed = True

    def finish(self) -> EventsResult:
        if self.thread_id is None:
            raise ReviewInvalid("沒有 thread.started")
        if not self.turn_started or not self.turn_completed:
            raise ReviewInvalid("事件不完整：缺少 turn.started 或 turn.completed")
        if self.last_message is None:
            raise ReviewInvalid("事件裡沒有最後一則回覆")
        return EventsResult(self.thread_id, self.last_message, dict(self.usage), self.events)


# ---- the report, last.md (5.5 item 3) -----------------------------------------------------------

@dataclass
class ReportResult:
    verdict: str | None
    base_is_ancestor: bool | None
    problems: list = field(default_factory=list)


CONTROL_KEYS = ("REVIEWED_COMMIT", "BASE_IS_ANCESTOR", "VERDICT")
CONTROL_LINE_IN_FENCE = "控制欄位出現在 code fence 裡面"
CONTROL_LINE_WRAPPED = "控制欄位被引用、清單、加粗或行內 code 包起來，不是獨立的一行"
UNCLOSED_FENCE = "code fence 沒有關閉"
UNCLOSED_CONSTRUCT = "報告最後三行之前，還有沒關閉的 code fence"
HTML_NOT_ALLOWED = "報告在 code fence 以外使用了 HTML（標籤、註解或 <script> 之類），審查報告只能用 Markdown"
CONTROL_LINE_ELSEWHERE = "控制欄位的前綴出現在報告最後三行以外的地方"
TAIL_FORMAT = "報告最後三個非空行不是依序剛好 REVIEWED_COMMIT、BASE_IS_ANCESTOR、VERDICT"
_ANY_CONTROL = re.compile(r"(?:" + "|".join(CONTROL_KEYS) + r")[*_`\s]*:")
_TAIL_VERDICTS = "|".join(re.escape(v) for v in VERDICTS)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)\Z")
# anything that starts HTML: < and then a letter, / ! or ? (comments, tags, <script>, <?xml ...)
_HTML = re.compile(r"<[A-Za-z/!?]")
# a line that is, or is dressed up as, a control line: any run of quote,
# list, heading, bold, italic or code markers (or numbering) in front of
# the key, then the colon
_CONTROL_LIKE = re.compile(r"^[\s>*+\-`_#~\d.)(\[\]]*(?:" + "|".join(CONTROL_KEYS) + r")[*_`\s]*:")


def _fence_line(ln: str, closing_of: tuple[str, int] | None = None):
    """A code fence line as CommonMark reads it: at most three spaces of
    indentation (four make an indented code block, which is not a fence), at
    least three ` or ~. An opening backtick fence has no backtick in its info
    string. A closing fence is the same character, at least as long, and
    nothing after it but spaces or tabs. Returns (char, length) or None."""
    m = _FENCE.match(ln)
    if not m:
        return None
    ch, n, rest = m.group(1)[0], len(m.group(1)), m.group(2)
    if closing_of is None:
        return None if (ch == "`" and "`" in rest) else (ch, n)
    if ch == closing_of[0] and n >= closing_of[1] and not rest.strip(" \t"):
        return ch, n
    return None


def _split_fences(lines: list[str]) -> tuple[list[str], list[str], bool]:
    """(lines outside any code fence, lines inside one, a fence is left
    open). The fence lines themselves are neither."""
    outside, inside = [], []
    opener: tuple[str, int] | None = None
    for ln in lines:
        if opener is None:
            opener = _fence_line(ln)
            if opener is None:
                outside.append(ln)
        elif _fence_line(ln, opener):
            opener = None
        else:
            inside.append(ln)
    return outside, inside, opener is not None


def _fold(ln: str) -> str:
    """The line as a person would read the letters: NFKC (Roman numerals,
    full-width letters and other compatibility forms become plain ones), the
    invisible formatting characters dropped, upper case. Only for finding
    something dressed up as a control line; the three real lines are
    compared as the original ASCII."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", ln) if unicodedata.category(ch) != "Cf").upper()


def check_report(text, commit: str) -> ReportResult:
    """The report's form. Everything a person relies on is on its own exact
    line, outside any code fence: REVIEWED_COMMIT (the reviewed commit),
    BASE_IS_ANCESTOR (v29.9: the reviewer's own statement that the flow's base
    commit is an ancestor; VBear has not verified it), and VERDICT as the last
    non-empty line. A control line inside a fence, or one quoted, listed,
    bolded or put in inline code, is a problem of its own (Codex S2b part 2
    review R2 #2), not something that is skipped."""
    out = ReportResult(None, None)
    if not _text(text, REPORT_MAX):
        out.problems.append("報告不是合法的 UTF-8 或超過 256 KiB")
        return out
    lines = text.split("\n")
    outside, inside, open_fence = _split_fences(lines)
    if open_fence:
        out.problems.append(UNCLOSED_FENCE)
    if any(_CONTROL_LIKE.match(_fold(ln)) for ln in inside):
        out.problems.append(CONTROL_LINE_IN_FENCE)
    exact = tuple(f"{k}:" for k in CONTROL_KEYS)
    if any(_CONTROL_LIKE.match(_fold(ln)) and not ln.startswith(exact) for ln in outside):
        out.problems.append(CONTROL_LINE_WRAPPED)
    # Codex S2b part 2 R4: no HTML outside a code fence, however it is
    # written (a comment, an unclosed <script>/<style>/<textarea>, a tag):
    # such text can hide the lines around it. Markdown is enough for a review.
    if any(_HTML.search(ln) for ln in outside):
        out.problems.append(HTML_NOT_ALLOWED)

    def only(prefix: str) -> list[str]:
        return [ln for ln in outside if ln.startswith(prefix)]

    got = only("REVIEWED_COMMIT:")
    if got != [f"REVIEWED_COMMIT: {commit}"]:
        out.problems.append("REVIEWED_COMMIT 不是剛好一行，或不等於被審 commit")
    anc = only("BASE_IS_ANCESTOR:")
    if len(anc) == 1 and anc[0] in ("BASE_IS_ANCESTOR: yes", "BASE_IS_ANCESTOR: no"):
        out.base_is_ancestor = anc[0].endswith("yes")
        if not out.base_is_ancestor:
            # v29.9: the range cannot be trusted, so the review is not usable
            # (not a basis for the merge gate). A problem, so "no problems"
            # always means the report can be taken as it is.
            out.problems.append(BASE_NOT_ANCESTOR)
    else:
        out.problems.append("BASE_IS_ANCESTOR 不是剛好一行 yes 或 no")
    verdicts = only("VERDICT:")
    nonempty = [ln for ln in lines if ln.strip()]
    if (len(verdicts) == 1 and verdicts[0] in tuple(f"VERDICT: {v}" for v in VERDICTS)
            and nonempty and nonempty[-1] == verdicts[0]):
        out.verdict = verdicts[0][len("VERDICT: "):]
    else:
        out.problems.append("VERDICT 不是剛好一行，或不是最後一個非空行")
    # The whitelist rule (planner, after the HTML-comment bypass): the last
    # three non-empty lines are exactly the three control lines in order;
    # everything before them is closed; no control key appears anywhere else.
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    tail_ok = False
    if len(idx) >= 3:
        a, b, c3 = idx[-3:]
        patterns = (re.compile(r"REVIEWED_COMMIT: ([0-9a-f]{40}|[0-9a-f]{64})"), re.compile(r"BASE_IS_ANCESTOR: (yes|no)"),
                    re.compile(r"VERDICT: (" + _TAIL_VERDICTS + ")"))
        tail_ok = (all(lines[i].isascii() and p.fullmatch(lines[i]) for i, p in zip((a, b, c3), patterns))
                   and lines[a] == f"REVIEWED_COMMIT: {commit}")
        if tail_ok:
            if _split_fences(lines[:a])[2]:
                out.problems.append(UNCLOSED_CONSTRUCT)
            for i, ln in enumerate(lines):
                if i not in (a, b, c3) and _ANY_CONTROL.search(_fold(ln)):
                    out.problems.append(CONTROL_LINE_ELSEWHERE)
                    break
    if not tail_ok:
        out.problems.append(TAIL_FORMAT)
        if any(_ANY_CONTROL.search(_fold(ln)) for ln in lines[:max(0, (idx[-3] if len(idx) >= 3 else 0))]):
            out.problems.append(CONTROL_LINE_ELSEWHERE)
    out.problems = list(dict.fromkeys(out.problems))
    return out


# ---- finding and copying the rollout (5.6 item 1, "rollout 的去向") ----------------------------------

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _stat_key(st) -> tuple:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def open_rollout(codex_home, c: cc.CodexConstants, thread_id: str, dates) -> tuple[int, os.stat_result, str]:
    """See _open_rollout. Nothing but ReviewInvalid comes out of here: a
    wrong argument type or any other exception is a reason that names only
    the exception's type (Codex S2b part 2 review R2 #3)."""
    try:
        return _open_rollout(codex_home, c, thread_id, dates)
    except ReviewInvalid:
        raise
    except Exception as exc:
        raise ReviewInvalid(f"rollout 找不到或無法安全開啟（{type(exc).__name__}）") from exc


def _open_rollout(codex_home, c: cc.CodexConstants, thread_id: str, dates) -> tuple[int, os.stat_result, str]:
    """The rollout of ``thread_id``: exactly one file named
    ``<prefix>…-<thread_id>.jsonl`` under CODEX_HOME/<rollout_dir>/<date
    parts> for the given dates (start and end of the review), opened through
    directory descriptors, nothing followed through a symlink, then checked
    as a plain file owned by this user and at most 64 MiB. Returns (fd, fstat,
    relative path); the caller closes the fd. ReviewInvalid for none or more
    than one, or anything wrong with it: the file is then left alone."""
    if not (isinstance(thread_id, str) and review_store.THREAD_RE.match(thread_id)):
        raise ReviewInvalid("thread_id 不合法，找不到 rollout")
    suffix = f"-{thread_id}.jsonl"
    uid = os.geteuid()
    found: list[tuple[str, int]] = []
    seen_dirs = set()
    try:
        root = review_store.open_dir_chain(codex_home)       # from "/", no symlink anywhere on the way
    except (OSError, ValueError) as exc:
        raise ReviewInvalid(f"CODEX_HOME 無法安全開啟（{type(exc).__name__}）") from exc
    try:
        for when in dates:
            parts = [c.rollout_dir, *(when.strftime(p) for p in c.rollout_date_parts)]
            rel = "/".join(parts)
            if rel in seen_dirs:
                continue
            seen_dirs.add(rel)
            fds = []
            try:
                cur = root
                missing = False
                for name in parts:
                    try:
                        cur = os.open(name, _DIR_FLAGS, dir_fd=cur)
                    except FileNotFoundError:
                        missing = True
                        break
                    except OSError as exc:        # a symlink or anything else on the way: not followed
                        raise ReviewInvalid(f"rollout 的資料夾無法安全開啟（{exc.strerror}）") from exc
                    fds.append(cur)
                if missing:
                    continue
                try:
                    names = os.listdir(cur)
                except OSError as exc:
                    raise ReviewInvalid(f"rollout 資料夾無法列出（{exc.strerror}）") from exc
                found += [(f"{rel}/{n}", n) for n in names if n.startswith(c.rollout_prefix) and n.endswith(suffix)]
            finally:
                for f in fds:
                    os.close(f)
        if len(found) != 1:
            raise ReviewInvalid("找不到 rollout" if not found else "找到不只一份 rollout",
                                code="not_found" if not found else "multiple")
        relpath = found[0][0]
        fds = []
        try:
            cur = root
            for name in relpath.split("/")[:-1]:
                try:
                    cur = os.open(name, _DIR_FLAGS, dir_fd=cur)
                except OSError as exc:
                    raise ReviewInvalid(f"rollout 的資料夾無法安全開啟（{exc.strerror}）") from exc
                fds.append(cur)
            try:
                fd = os.open(relpath.split("/")[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=cur)
            except OSError as exc:
                raise ReviewInvalid(f"rollout 無法開啟（{exc.strerror}）") from exc
        finally:
            for f in fds:
                os.close(f)
        try:
            st = os.fstat(fd)
            import stat as _stat
            if not _stat.S_ISREG(st.st_mode) or st.st_uid != uid:
                raise ReviewInvalid("rollout 不是本人擁有的一般檔案")
            if st.st_size > ROLLOUT_MAX:
                raise ReviewInvalid("rollout 超過 64 MiB")
        except BaseException:
            os.close(fd)
            raise
        return fd, st, relpath
    finally:
        os.close(root)


@dataclass
class CopyResult:
    ok: bool
    info: dict | None = None
    reasons: list = field(default_factory=list)
    leftover: str | None = None          # a partial copy that could not be removed: where it is
    leftover_bytes: int = 0              # its size, for the quota (0 when there is none)


def copy_rollout(src_fd: int, dst_dir_fd: int, name: str, *, expect_sha256: str, src_before,
                 dst_path: str = "") -> CopyResult:
    """See _copy_rollout. Nothing is raised, whatever the arguments are
    (S2b part 2 review R2 #3): an exception of any kind is a reason that names
    only its type."""
    try:
        return _copy_rollout(src_fd, dst_dir_fd, name, expect_sha256=expect_sha256, src_before=src_before,
                             dst_path=dst_path)
    except Exception as exc:
        return CopyResult(False, None, [f"rollout 複製失敗（{type(exc).__name__}）"])


def _copy_rollout(src_fd: int, dst_dir_fd: int, name: str, *, expect_sha256: str, src_before,
                  dst_path: str = "") -> CopyResult:
    """Copy the verified rollout (from the same descriptor, rewound) into a
    file created exclusively in the review record directory (O_EXCL |
    O_NOFOLLOW, 0600), hashing the copy. The two hashes must be equal and the
    source's (dev, inode, size, mtime, ctime) must not have changed; else the
    copy is removed and the review is invalid. The source is never deleted
    (the name could be swapped between matching and deleting).

    Nothing is raised (Codex S2b part 2 review #2): every failure is a reason
    in the result. If the failed copy cannot be removed, ``leftover`` says
    where it is (``dst_path``/``name``) and ``leftover_bytes`` how big, so the
    caller can keep the job for a person and count the bytes."""
    res = CopyResult(False)
    digest = hashlib.sha256()
    try:
        out_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                         dir_fd=dst_dir_fd)
    except OSError as exc:                  # nothing of ours exists: the name was taken or cannot be made
        res.reasons.append(f"rollout 複本無法建立（{exc.strerror or type(exc).__name__}）")
        return res
    created_size = 0
    try:
        try:
            os.lseek(src_fd, 0, os.SEEK_SET)
            size = 0
            while True:
                chunk = os.read(src_fd, READ_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > ROLLOUT_MAX:
                    raise ReviewInvalid("rollout 超過 64 MiB")
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    n = os.write(out_fd, view)
                    if n <= 0:
                        raise OSError(5, "寫入沒有進展")
                    created_size += n
                    view = view[n:]
            os.fsync(out_fd)
            after = os.fstat(src_fd)
            if digest.hexdigest() != expect_sha256:
                raise ReviewInvalid("rollout 複製時的雜湊與核對時不同")
            if _stat_key(after) != _stat_key(src_before):
                raise ReviewInvalid("rollout 在核對與複製之間被改動")
            os.fsync(dst_dir_fd)                 # the new name is durable too; a failure removes the copy
            res.ok = True
            res.info = {"sha256": digest.hexdigest(), "size": size, "source_dev": after.st_dev,
                        "source_inode": after.st_ino}
        except ReviewInvalid as exc:
            res.reasons += exc.reasons
        except Exception as exc:
            res.reasons.append(f"rollout 複製失敗（{type(exc).__name__}）")
    finally:
        try:
            os.close(out_fd)
        except OSError:
            pass
        if not res.ok:
            try:
                os.unlink(name, dir_fd=dst_dir_fd)
            except Exception as exc:
                res.leftover = f"{dst_path.rstrip('/')}/{name}" if dst_path else name
                res.leftover_bytes = created_size
                res.reasons.append(f"rollout 的不完整複本無法移除（{type(exc).__name__}），交人工處理")
    return res


# ---- the rollout (5.6) ----------------------------------------------------------------------------

@dataclass
class RolloutResult:
    sha256: str
    size: int
    responses: int
    turn_id: str | None
    reasons: list
    complete: bool = True        # sha256 and size cover the whole file (always, unless it is over the limit)


class _Counting:
    """A sha256 that also counts the bytes it was given."""

    def __init__(self):
        self.h = hashlib.sha256()
        self.size = 0

    def update(self, chunk: bytes) -> None:
        self.h.update(chunk)
        self.size += len(chunk)


def _drain(fd: int, digest: _Counting) -> bool:
    """Read the rest of the file into the hash. True when the whole file was
    read; False when it is over the limit or cannot be read (the hash then
    stops short and the result says so)."""
    while True:
        try:
            chunk = os.read(fd, READ_CHUNK)
        except OSError:
            return False
        if not chunk:
            return True
        digest.update(chunk)
        if digest.size > ROLLOUT_MAX:
            return False


def _lines(fd: int, limits: strictjson.Limits, digest):
    """Each line of the file (without its newline), the whole file hashed as
    it is read; LineError for a line or a file over its limit, a read error,
    or a last line without a newline."""
    buf = bytearray()
    total = 0
    while True:
        try:
            chunk = os.read(fd, READ_CHUNK)
        except OSError as exc:
            raise strictjson.LineError(f"讀取失敗（{exc.strerror or type(exc).__name__}）") from exc
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        if total > min(limits.file_bytes, ROLLOUT_MAX):
            raise strictjson.LineError("檔案超過上限")
        buf += chunk
        while True:
            cut = buf.find(b"\n")
            if cut < 0:
                break
            if cut > limits.unit_bytes:
                raise strictjson.LineError("有一行超過上限")
            line = bytes(buf[:cut])
            del buf[:cut + 1]
            yield line
        if len(buf) > limits.unit_bytes:
            raise strictjson.LineError("有一行超過上限")
    if buf:
        raise strictjson.LineError("最後一行沒有以換行結尾")


def validate_rollout(fd: int, c: cc.CodexConstants, *, thread_id: str, scratch: str, model: str,
                     events_usage: dict, last_message: str) -> RolloutResult:
    """The rollout read through one already verified descriptor (the caller
    opened it O_NOFOLLOW and checked owner, type and size). ``RolloutResult
    .reasons`` is empty only when every rule of design 5.6 holds."""
    digest = _Counting()
    reasons: list[str] = []
    v = _Walk(c, thread_id, scratch, model, events_usage, last_message, reasons)
    try:
        for raw in _lines(fd, strictjson.ROLLOUT, digest):
            parsed = strictjson.loads_object(raw, strictjson.ROLLOUT)
            if not parsed.ok:
                reasons.append("有一行不是嚴格的 JSON 物件")
                break
            try:
                v.record(parsed.value)
            except Exception as exc:                  # a record that cannot even be looked at
                reasons.append(f"有一筆紀錄無法檢查（{type(exc).__name__}）")
                break
            if len(reasons) >= MAX_REASONS:
                break
    except strictjson.LineError as exc:
        reasons.append(f"rollout 檔案不符：{exc}")
    if not reasons:
        try:
            v.finish()
        except Exception as exc:
            reasons.append(f"rollout 無法檢查（{type(exc).__name__}）")
    # The hash always stands for the whole file, even when the checks stopped
    # at the first bad record: an invalid review still keeps its only source
    # (design 5.6), and copy_rollout compares against this (Codex S2b part 2
    # review #1).
    complete = _drain(fd, digest) and digest.size <= ROLLOUT_MAX
    if not complete:
        reasons.append("rollout 讀不完整或超過 64 MiB，雜湊不涵蓋整個檔案")
    return RolloutResult(digest.h.hexdigest(), digest.size, v.token_records, v.turn_id,
                         list(dict.fromkeys(reasons))[:MAX_REASONS], complete)


class _Walk:
    def __init__(self, c, thread_id, scratch, model, events_usage, last_message, reasons):
        self.c, self.thread_id, self.scratch, self.model = c, thread_id, scratch, model
        self.events_usage, self.last_message, self.reasons = events_usage, last_message, reasons
        self.ordinal = 0
        self.session_meta = 0
        self.world_state = 0
        self.turn_contexts = 0
        self.task_started: dict | None = None
        self.task_complete: dict | None = None
        self.turn_id: str | None = None
        self.token_records = 0
        self.model_items = 0
        self.prev_turn = {f: 0 for f in c.usage_fields}
        self.prev_thread = {f: 0 for f in c.usage_fields}
        self.last_turn_usage: dict | None = None
        self.after_complete = False

    def bad(self, why: str) -> None:
        self.reasons.append(why)

    def record(self, rec: dict) -> None:
        c = self.c
        if self.after_complete:
            self.bad("task_complete 不是最後一筆")
            self.after_complete = False
        if not _int(rec.get("ordinal"), 0, 10 ** 9) or rec["ordinal"] != self.ordinal:
            self.bad("ordinal 不是從 0 開始逐筆加 1 的整數")
        first = self.ordinal == 0
        self.ordinal += 1
        typ, payload = rec.get("type"), rec.get("payload")
        if not isinstance(typ, str) or not isinstance(payload, dict):
            self.bad("有一筆紀錄缺少 type 或 payload")
            return
        sub = None
        if (typ, None) not in c.rollout_kinds:
            sub = payload.get("type")
            if not isinstance(sub, str):
                self.bad("有一筆紀錄的種類不在常數內")
                return
        kind = (typ, sub)
        if kind not in c.rollout_kinds:
            self.bad("有一筆紀錄的種類不在常數內")
            return
        if first and typ != "session_meta":
            self.bad("第一筆不是 session_meta")
        if kind in c.model_message_kinds and (kind != ("response_item", "message")
                                              or payload.get("role") == "assistant"):
            self.model_items += 1                    # something the model produced
        handler = getattr(self, "_" + (sub if sub else typ), None)
        if handler is not None:
            handler(payload)
        if kind == c.tool_call_kind:
            if payload.get(c.tool_name_key) not in c.tools:
                self.bad("出現不在允許清單內的工具呼叫")

    # ---- the records VBear reads
    def _session_meta(self, p):
        c = self.c
        self.session_meta += 1
        if self.session_meta > 1:
            self.bad("session_meta 不只一筆")
            return
        if p.get("id") != self.thread_id:
            self.bad("session_meta.id 不等於 thread_id")
        if p.get("cwd") != self.scratch:
            self.bad("session_meta.cwd 不是審查暫存區")
        if p.get("cli_version") != c.version:
            self.bad("session_meta.cli_version 不是已驗證的版本")
        if p.get("originator") != c.session_originator or p.get("source") != c.session_source:
            self.bad("session_meta 的 originator 或 source 不符")
        if p.get("model_provider") != c.model_provider:
            self.bad("session_meta.model_provider 不是 openai")

    def _world_state(self, p):
        c = self.c
        self.world_state += 1
        if p.get("apps_instructions") is not False or p.get("plugins_instructions") is not False:
            self.bad("world_state 的 apps 或 plugins 指示不是 false")
        if p.get("host_skills") not in ([], {}, None) or "host_skills" not in p:
            self.bad("world_state.host_skills 有內容或缺少")
        if "multi_agent_mode" not in p or p["multi_agent_mode"] != c.multi_agent_disabled:
            self.bad("world_state.multi_agent_mode 缺少或不是停用值")

    def _turn_context(self, p):
        c = self.c
        if self.world_state == 0:
            self.bad("world_state 沒有出現在第一個 turn_context 之前")
        self.turn_contexts += 1
        sp_ = p.get("sandbox_policy")
        if not (isinstance(sp_, dict) and sp_.get("type") == c.sandbox_type and sp_.get("network_access") is False
                and sp_.get("exclude_slash_tmp") is True and sp_.get("exclude_tmpdir_env_var") is True
                and sp_.get("writable_roots") in (None, [])):
            self.bad("turn_context 的 sandbox_policy 不是受限的值")
        pp = p.get("permission_profile")
        if not (isinstance(pp, dict) and "network" in pp and pp["network"] == c.network_restricted):
            self.bad("turn_context 的 permission_profile.network 不是受限值")
        if p.get("approval_policy") != c.approval_policy:
            self.bad("turn_context.approval_policy 不是 never")
        if p.get("cwd") != self.scratch:
            self.bad("turn_context.cwd 不是審查暫存區")
        if p.get("model") != self.model or p.get("model") not in c.models:
            self.bad("turn_context.model 不是要求的模型，或不在清單內")
        tid = p.get("turn_id")
        if not isinstance(tid, str) or not tid or (self.turn_id is not None and tid != self.turn_id):
            self.bad("turn_context.turn_id 與 task_started 不同")
        elif self.turn_id is None:
            self.turn_id = tid

    def _task_started(self, p):
        if self.task_started is not None:
            self.bad("task_started 不只一筆")
            return
        self.task_started = p
        tid = p.get("turn_id")
        if not isinstance(tid, str) or not tid or not _int(p.get("started_at"), 0, 2 ** 53):
            self.bad("task_started 的 turn_id 或 started_at 不合法")
            return
        if self.turn_id is not None and tid != self.turn_id:
            self.bad("task_started.turn_id 與 turn_context 不同")
        self.turn_id = self.turn_id or tid

    def _task_complete(self, p):
        if self.task_complete is not None:
            self.bad("task_complete 不只一筆")
            return
        self.task_complete = p
        self.after_complete = True
        if not _int(p.get("completed_at"), 0, 2 ** 53):
            self.bad("task_complete.completed_at 不合法")
        elif self.task_started and _int(self.task_started.get("started_at"), 0, 2 ** 53) \
                and p["completed_at"] < self.task_started["started_at"]:
            self.bad("completed_at 早於 started_at")
        if p.get("turn_id") != (self.task_started or {}).get("turn_id"):
            self.bad("task_complete.turn_id 與 task_started 不同")
        if not isinstance(p.get("last_agent_message"), str) or p["last_agent_message"] != self.last_message:
            self.bad("task_complete.last_agent_message 與事件流的最後一則回覆不同")

    def _usage_obj(self, obj, what: str):
        c = self.c
        if not (isinstance(obj, dict) and all(_int(obj.get(f)) for f in c.usage_fields)):
            self.bad(f"token_usage_record 的 {what} 不合法")
            return None
        return {f: obj[f] for f in c.usage_fields}

    def _token_usage_record(self, p):
        self.token_records += 1
        usage = self._usage_obj(p.get("usage"), "usage")
        turn = self._usage_obj(p.get("turn_token_usage"), "turn_token_usage")
        thread = self._usage_obj(p.get("thread_token_usage"), "thread_token_usage")
        if p.get("turn_id") != self.turn_id or self.turn_id is None:
            self.bad("token_usage_record.turn_id 不是這次審查的 turn_id")
        if usage is None or turn is None or thread is None:
            return
        if usage["input_tokens"] <= 0 or usage["total_tokens"] <= 0:
            self.bad("token_usage_record 的 usage 輸入或總數為 0")
        if any(usage[f] > usage["input_tokens"] for f in self.c.cache_fields):
            self.bad("token_usage_record 的 usage 有快取欄位超過輸入")
        for f in self.c.usage_fields:
            if turn[f] != self.prev_turn[f] + usage[f] or thread[f] != self.prev_thread[f] + usage[f]:
                self.bad("用量的累計鏈對不上（中間可能有缺漏）")
                break
        self.prev_turn, self.prev_thread, self.last_turn_usage = turn, thread, turn

    def finish(self):
        if self.session_meta != 1:
            self.bad("沒有剛好一筆 session_meta")
        if self.task_started is None or self.task_complete is None:
            self.bad("缺少 task_started 或 task_complete")
        if self.turn_contexts < 1:
            self.bad("沒有 turn_context")
        if self.world_state < 1:
            self.bad("沒有 world_state")
        if self.token_records < 1:
            self.bad("沒有 token_usage_record")
        if self.model_items < 1:
            self.bad("沒有模型產生的 response_item")
        if self.last_turn_usage is not None:
            if any(self.last_turn_usage.get(f) != self.events_usage.get(f) for f in self.c.events_usage_fields):
                self.bad("最後一筆用量的 turn_token_usage 不等於 turn.completed.usage")
