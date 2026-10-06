"""Task Card storage, validation, and lifecycle management (Phase B3).

Tasks are stored in ~/.vbear/tasks.json (or $VBEAR_HOME/tasks.json).
All writes are atomic and secure (permissions 0600, directory 0700), guarded
by a cross-process lock so a CLI scan and the server can never race each
other's read-modify-write (see _cross_process_lock).

Status Provenance explicitly separates three self-reported fields, all
recorded via this same unauthenticated local API (see provenance["source"]
below — this app has no login, so nothing here cryptographically attributes
a field to a human rather than a script or another agent hitting the API):
  1. Agent-reported completion ("agent": "pending" | "in_progress" | "completed" | "blocked")
  2. Automated test verification ("tests": "untested" | "passed" | "failed")
  3. Approval asserted through this console's UI/API ("human": "pending" | "approved" | "rejected")

There is no authenticated verifier anywhere in this system — "tests" and
"human" above are both just fields someone (or some script) set through this
same unauthenticated local UI/API, exactly like "agent" is. This console
therefore never derives or displays a governed "Verified" claim:
  - provenance["verified"] is always False. It is not computed from
    tests/human and can never become True — there is nothing in this system
    that could make such a claim true, so the field simply always reads
    "not verified" (kept, not removed, for tools that only check truthiness).
  - provenance["verification_asserted"] is True only when tests == "passed"
    and human == "approved". This is an honestly-named *assertion*, not a
    verification: it says "this console's own UI/API was told both of those
    things", nothing more. status can become "verification_asserted" the
    same way, and the client can never set status="verification_asserted"
    directly — see CLIENT_ASSERTABLE_STATUSES.

Task-to-session association is strictly tracking-only:
  - association_mode is always "tracking_only"
  - Never implies or generates context injection
  - Applying a changed Task Card as Effective Context requires a new session
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import config as cfg

MAX_TASKS = 1000
MAX_TEXT_SHORT = 200
MAX_TEXT_LONG = 5000
MAX_ITEM_TEXT = 500
MAX_ITEMS = 50
MAX_STEPS = 50
MAX_ARTIFACTS = 50

VALID_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")

# Statuses the client may assert directly via body["status"] when it doesn't
# correspond to agent/tests/human provenance state. "verification_asserted"
# is deliberately excluded: it must only ever be derived from provenance (see
# _validate_and_normalize below), never accepted as a raw client-asserted
# string, or a client could forge a verification-looking status without
# passing tests or human approval.
CLIENT_ASSERTABLE_STATUSES = ("draft", "in_progress", "blocked", "agent_completed")


class TaskStorageError(RuntimeError):
    """Raised when tasks.json is corrupted and needs manual recovery.

    Reads and writes are blocked (this is raised from load_all(), which every
    other function goes through) until the corrupt file's quarantine copy has
    been inspected and the marker below removed by a human.
    """

TEMPLATES = {
    "bug_fix": {
        "title": "Bug 修復任務",
        "goal": "修復特定錯誤或異常行為",
        "scope": ["需修復之檔案"],
        "out_of_scope": ["未授權變更之架構或外部模組"],
        "deliverables": ["修正程式碼", "單元測試案例", "回歸驗證結果"],
        "acceptance_criteria": ["測試 100% 通過", "無回歸錯誤"],
        "evidence": ["測試通過日誌"],
    },
    "feature": {
        "title": "功能實作任務",
        "goal": "實作指定規格之新功能",
        "scope": ["新功能相關檔案"],
        "out_of_scope": ["非本次範圍之額外功能"],
        "deliverables": ["功能實作", "完整測試套件", "文件更新"],
        "acceptance_criteria": ["符合需求規格", "測試覆蓋達標"],
        "evidence": ["實測截圖或日誌", "測試報告"],
    },
    "review": {
        "title": "獨立審查任務",
        "goal": "進行缺陷優先之獨立審查與安全性檢查",
        "scope": ["待審查之變更檔案與測試"],
        "out_of_scope": ["直接撰寫程式碼變更"],
        "deliverables": ["審查報告 (Findings & Verdict)"],
        "acceptance_criteria": ["標註阻斷與非阻斷項目", "確認安全邊界符合規範"],
        "evidence": ["靜態檢查日誌", "差異比對紀錄"],
    },
    "test": {
        "title": "測試補充任務",
        "goal": "補齊單元測試與邊界測試案例",
        "scope": ["測試檔案與測試環境配置"],
        "out_of_scope": ["修改產品主程式碼邏輯"],
        "deliverables": ["新增之測試套件", "測試執行報告"],
        "acceptance_criteria": ["覆蓋關鍵邊界案例", "無 flaky 測試"],
        "evidence": ["測試覆蓋率報告", "測試通過輸出"],
    },
    "research": {
        "title": "技術調研任務",
        "goal": "評估架構方案與技術可行性",
        "scope": ["調研相關之技術規格與範例"],
        "out_of_scope": ["正式環境修改"],
        "deliverables": ["調研評估報告", "可行性矩陣"],
        "acceptance_criteria": ["具備客觀實測依據", "包含安全性分析"],
        "evidence": ["實驗測試數據", "技術規格引用"],
    },
    "refactor": {
        "title": "模組重構任務",
        "goal": "優化程式結構並維持對外契約不變",
        "scope": ["目標重構模組"],
        "out_of_scope": ["破壞性 API 變更"],
        "deliverables": ["重構後程式碼", "回歸測試套件"],
        "acceptance_criteria": ["既有測試完全通過", "對外行為維持一致"],
        "evidence": ["重構前後測試對比日誌"],
    },
    "docs": {
        "title": "技術文件撰寫",
        "goal": "更新產品使用手冊與架構規範說明",
        "scope": ["文件檔案 (README / PRD / docs)"],
        "out_of_scope": ["程式碼邏輯修改"],
        "deliverables": ["更新後之 Markdown 文件"],
        "acceptance_criteria": ["路徑與指令經實測驗證", "無過期或誤導描述"],
        "evidence": ["文件連結查核", "指令實測截圖"],
    },
    "investigation": {
        "title": "問題排查任務",
        "goal": "排查系統異常之根本原因 (RCA)",
        "scope": ["日誌檔案與懷疑問題模組"],
        "out_of_scope": ["未經確認之熱修復"],
        "deliverables": ["根本原因分析報告 (RCA)", "再現步驟與修復建議"],
        "acceptance_criteria": ["再現路徑明確", "根本原因有日誌佐證"],
        "evidence": ["錯誤日誌摘錄", "重現環境資訊"],
    },
    "custom": {
        "title": "自訂任務",
        "goal": "",
        "scope": [],
        "out_of_scope": [],
        "deliverables": [],
        "acceptance_criteria": [],
        "evidence": [],
    },
}

_lock = threading.Lock()

_VALID_AGENT_STATUSES = ("pending", "in_progress", "completed", "blocked")
_VALID_TEST_STATUSES = ("untested", "passed", "failed")
_VALID_HUMAN_STATUSES = ("pending", "approved", "rejected")


def _path() -> Path:
    return cfg.state_dir() / "tasks.json"


def _lock_path() -> Path:
    return cfg.state_dir() / "tasks.json.lock"


def _corrupt_marker_path() -> Path:
    return cfg.state_dir() / "tasks.json.corrupted"


def _fsync_dir(directory: Path) -> None:
    """fsync a *directory* so a rename into it survives a power loss.

    os.replace()/rename() is atomic with respect to concurrent readers, but
    on its own that only guarantees no one ever observes a half-installed
    file — it says nothing about the name surviving a crash. Without this,
    there is a window in which the corrupt store has already been moved
    aside but its marker's directory entry was never persisted, so a crash
    leaves a quarantined file with no marker to block the next writer.
    """
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_marker(
    marker: Path, quarantine_path: Path, original_path: Path, exc: Exception
) -> None:
    """Install the corruption marker: contents are fsync'd to a temp file
    and installed with an atomic rename, so the marker is never observable
    half-written. The containing directory is then fsync'd as a best-effort
    durability step, so an ordinary power cut cannot lose the marker's
    directory entry the way the atomic rename alone would not have
    prevented.

    Raises OSError if the marker could not be *installed*; callers must not
    swallow that (see _mark_corrupt). A failure of the trailing directory
    fsync alone is deliberately not raised — see the comment at that call.
    """
    payload = json.dumps(
        {
            "detected_at": time.time(),
            "quarantine_file": str(quarantine_path),
            "original_file": str(original_path),
            "error": str(exc),
        },
        ensure_ascii=False,
        indent=2,
    )
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

    # Deliberately a separate step, outside the block above: by this point
    # the marker is installed, so a failure here is a durability caveat and
    # not a failed write. Letting it propagate would send _mark_corrupt into
    # its "marker could not be written, nothing was moved" branch and tell
    # the operator no marker exists — while the marker is in fact on disk
    # and already blocking every read and write. The residual risk is
    # bounded: the caller only moves the corrupt file *after* this returns,
    # so a crash that drops the unsynced directory entry leaves the corrupt
    # file exactly where it was and the next load_all() simply re-detects
    # the same corruption and redoes this. Fail-closed either way.
    try:
        _fsync_dir(marker.parent)
    except OSError:
        pass


def _mark_corrupt(path: Path, marker: Path, exc: Exception) -> Path:
    """Quarantine `path` and durably write the marker that blocks all
    further reads and writes until a human clears it. Shared by every way
    the store can be found corrupt: unparseable JSON, a non-object root, or
    JSON that parses fine but holds an entry this module itself could never
    have written (see _entry_schema_problem).

    Fail-closed ordering: **the marker is installed before the corrupt file
    is moved**, never after. The dangerous state this whole routine exists
    to avoid is "no tasks.json and no marker", which is byte-for-byte
    indistinguishable from a normal fresh empty store and would let the very
    next save_task() overwrite real data with an empty file. Marker-first
    makes that state unreachable rather than merely unlikely:

      * marker write fails  -> nothing has moved; `path` still holds the
        corrupt bytes and the next load_all() retries this whole sequence.
      * marker write succeeds, move fails -> the marker is already on disk,
        so every subsequent read and write is blocked regardless; the
        corrupt bytes simply stay at their original path.

    An earlier revision moved first and rolled the move back if the marker
    write failed, but a rollback can itself fail — and that failure landed
    in exactly the unrecoverable state above. There is no rollback path here
    to fail. Every failure that changes what the operator must do is
    re-raised as TaskStorageError naming the file's actual on-disk location;
    the only exceptions are the two best-effort directory fsyncs, which are
    durability hardening and cannot make the reported location wrong.
    """
    quarantine_path = path.with_name(f"{path.name}.corrupt-{int(time.time())}")

    try:
        _write_marker(marker, quarantine_path, path, exc)
    except OSError as marker_exc:
        raise TaskStorageError(
            f"任務儲存損毀復原失敗：無法寫入復原標記 {marker}（{marker_exc}）。"
            f"損毀檔案未搬移、原封保留於 {path}，下次讀取會重新嘗試隔離；"
            "請人工檢查檔案系統（磁碟空間與權限）後重試"
        ) from marker_exc

    try:
        path.rename(quarantine_path)
    except OSError as move_exc:
        # The marker is already durably on disk, so the store is blocked and
        # no writer can clobber anything; the corrupt bytes just stay where
        # they are. Record the true location in the marker if we can, and
        # report it either way — nothing is silently discarded.
        remark = ""
        try:
            _write_marker(marker, path, path, exc)
        except OSError as remark_exc:
            remark = f"；另外無法更新標記內的實際位置（{remark_exc}）"
        raise TaskStorageError(
            f"任務儲存檔案損毀，且無法搬移至 {quarantine_path}（{move_exc}）。"
            f"損毀檔案原地保留於 {path}，復原標記 {marker} 已寫入，"
            f"讀寫已封鎖至人工復原為止{remark}"
        ) from move_exc

    # Deliberately *not* inside the try above. The rename has already
    # succeeded, so the corrupt file is at `quarantine_path` and the marker
    # written earlier already names it. Sharing a try with the rename would
    # let a directory-fsync failure fall into the move-failure branch, which
    # rewrites the marker to claim the file is still at `path` and reports
    # that location to the operator — a lie once the move went through.
    # A failure here only means the rename's durability is unconfirmed: the
    # on-disk state is already correct and blocked, and a crash that reverts
    # the unsynced rename puts the corrupt file back at `path` while the
    # marker (which also records `original_file`) keeps the store blocked.
    try:
        _fsync_dir(path.parent)
    except OSError:
        pass

    return quarantine_path


def _entry_schema_problem(key: Any, value: Any) -> str | None:
    """None if `value` is a plausible stored task record for `key`;
    otherwise a short reason it isn't. Deliberately conservative — this only
    rejects shapes load_all() could never have produced itself (wrong id,
    missing title, an out-of-enum provenance value, ...), so a schema this
    module later extends with new optional fields doesn't start failing
    closed on its own previously-valid data.
    """
    if not isinstance(key, str) or not VALID_ID_RE.match(key):
        return "鍵值不是有效的任務識別碼"
    if not isinstance(value, dict):
        return "值不是物件"
    if value.get("id") != key:
        return "id 欄位與鍵值不一致"
    if not isinstance(value.get("title"), str) or not value["title"]:
        return "title 缺失或非字串"
    prov = value.get("provenance")
    if prov is not None:
        if not isinstance(prov, dict):
            return "provenance 不是物件"
        if prov.get("agent") not in _VALID_AGENT_STATUSES:
            return "provenance.agent 不合法"
        if prov.get("tests") not in _VALID_TEST_STATUSES:
            return "provenance.tests 不合法"
        if prov.get("human") not in _VALID_HUMAN_STATUSES:
            return "provenance.human 不合法"
    for ts_field in ("created_at", "updated_at"):
        if ts_field in value and not isinstance(value[ts_field], (int, float)):
            return f"{ts_field} 非數值"
    return None


def _read_raw(path: Path) -> str | None:
    """Read tasks.json's exact bytes, or None if it simply doesn't exist yet
    (a normal, fresh empty store).

    Fails closed (raises OSError) for everything else — permission errors,
    the path being a directory, a symlink where a regular file must be, an
    unexpected hard link, or any other filesystem surprise (M2) — instead of
    the old behaviour of silently treating an unreadable-but-present file as
    an empty store, which let a subsequent save_task() overwrite real data
    it never actually managed to read.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"tasks.json 不是一般檔案 (mode={oct(st.st_mode)})")
        if st.st_nlink > 1:
            raise OSError(f"tasks.json 有多個硬連結 (nlink={st.st_nlink})，拒絕讀取")
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1  # fdopen now owns the descriptor; do not close it twice
            return fh.read()
    finally:
        if fd != -1:
            os.close(fd)


@contextlib.contextmanager
def _cross_process_lock(timeout: float = 10.0):
    """Exclusive lock spanning the full read-modify-write critical section
    of save_task()/delete_task(), enforced at the OS level via flock().

    Unlike the in-process `_lock` above, this also serializes a *second OS
    process* (e.g. a `vbear` CLI invocation running alongside the
    server) writing the same ~/.vbear/tasks.json, closing a lost-
    update race threading.Lock alone cannot see (H3): two separate processes
    could each load_all() the same version, each compute their own update,
    and the second write_private() call would silently discard whatever the
    first one just wrote.

    flock() is associated with the *open file description*, not the
    process, so it also correctly blocks concurrent threads within this
    same process (each acquire opens its own fd) — this lock is therefore
    sufficient on its own for save_task()/delete_task(); it does not also
    take `_lock`.
    """
    cfg.ensure_state_dir()
    fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, cfg.STATE_FILE_MODE)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TaskStorageError(
                        "任務儲存鎖定逾時（可能有其他程序正在寫入），請稍後再試"
                    )
                time.sleep(0.02)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def load_all() -> dict[str, dict[str, Any]]:
    """Load all task cards from the storage file.

    Raises TaskStorageError (never silently returns {} or drops an entry) if
    the storage file exists but cannot be safely read, is corrupt, holds an
    entry that doesn't match this module's own schema, or a prior corruption
    has not yet been recovered from. A missing file is a normal empty/fresh
    state, not corruption.
    """
    marker = _corrupt_marker_path()
    if marker.exists():
        raise TaskStorageError(
            f"任務儲存先前偵測到損毀，需人工復原後才能繼續讀寫任務卡。詳見 {marker}"
        )

    path = _path()
    try:
        raw = _read_raw(path)
    except OSError as exc:
        # Not "missing" — something is actually wrong (permissions, a
        # symlink, a directory in the way...). Fail closed instead of
        # silently starting from an empty store: a save_task() right after
        # this must never be allowed to overwrite data we simply failed to
        # read (M2).
        raise TaskStorageError(
            f"無法安全讀取任務儲存檔案 {path}：{exc}；為避免資料遺失，讀寫已暫停，"
            "請人工檢查檔案系統（權限、是否為符號連結或硬連結）後重試"
        ) from exc
    if raw is None:
        return {}

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("tasks.json 根節點必須為物件")
    except (ValueError, RecursionError) as exc:
        quarantine_path = _mark_corrupt(path, marker, exc)
        raise TaskStorageError(
            f"任務儲存檔案損毀，已隔離至 {quarantine_path}，請人工復原後刪除 {marker} 以恢復讀寫"
        ) from exc

    tasks: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        problem = _entry_schema_problem(k, v)
        if problem is not None:
            # A malformed entry used to be silently dropped here, which
            # meant the very next save_task() would write the file back out
            # *without* it — permanent, silent data loss for whatever other
            # task shared the file. Fail closed instead, the same way
            # unparseable JSON already does (H2 / M2).
            exc = ValueError(f"任務項目 {k!r} 結構不符：{problem}")
            quarantine_path = _mark_corrupt(path, marker, exc)
            raise TaskStorageError(
                f"任務儲存檔案含有不符結構的項目（{k!r}：{problem}），已隔離至 "
                f"{quarantine_path}，請人工復原後刪除 {marker} 以恢復讀寫"
            ) from exc
        tasks[k] = v
    return tasks


def list_tasks() -> list[dict[str, Any]]:
    """Return all tasks sorted by updated_at descending."""
    with _lock:
        tasks = list(load_all().values())
    tasks.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
    return tasks


def get_task(task_id: str) -> dict[str, Any] | None:
    if not isinstance(task_id, str) or not task_id:
        return None
    with _lock:
        return load_all().get(task_id)


def _clean_str(value: Any, max_len: int = MAX_TEXT_SHORT, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if "\x00" in text:
        text = text.replace("\x00", "")
    return text[:max_len]


def _clean_str_list(value: Any, max_items: int = MAX_ITEMS, max_len: int = MAX_ITEM_TEXT) -> list[str]:
    if isinstance(value, str):
        value = [part.strip() for part in value.replace("\r\n", "\n").split("\n") if part.strip()]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = _clean_str(item, max_len=max_len)
        if text and text not in out:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _clean_steps(value: Any, max_steps: int = MAX_STEPS) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str):
            text = _clean_str(item, max_len=MAX_ITEM_TEXT)
            if text:
                out.append({"title": text, "done": False})
        elif isinstance(item, dict):
            title = _clean_str(item.get("title") or item.get("text"), max_len=MAX_ITEM_TEXT)
            if title:
                out.append({"title": title, "done": bool(item.get("done"))})
        if len(out) >= max_steps:
            break
    return out


def _validate_and_normalize(
    task_id: str | None,
    body: dict[str, Any],
    existing: dict[str, Any] | None = None,
    existing_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    raw_id = task_id if task_id is not None else body.get("id")
    if raw_id is not None:
        if not isinstance(raw_id, str) or "\x00" in raw_id or not VALID_ID_RE.match(raw_id):
            raise ValueError("無效的任務識別碼 (必須為 1-64 字元 ASCII 字母、數字、底線或連字號)")
        tid = raw_id
    else:
        # Collision-resistant: a random suffix, not a timestamp modulo that
        # repeats every ~16.7 minutes and can silently overwrite an
        # unrelated task with the same generated id (H2).
        for _ in range(8):
            tid = f"task-{secrets.token_hex(6)}"
            if tid not in existing_ids:
                break
        else:
            raise ValueError("無法產生唯一的任務識別碼，請稍後再試")

    title = _clean_str(body.get("title") or (existing.get("title") if existing else ""), MAX_TEXT_SHORT)
    if not title:
        raise ValueError("任務標題不得為空")

    template = _clean_str(body.get("template") or (existing.get("template") if existing else "custom"), 32)
    if template not in TEMPLATES:
        template = "custom"

    goal = _clean_str(body.get("goal") if "goal" in body else (existing.get("goal") if existing else ""), MAX_TEXT_LONG)
    scope = _clean_str_list(body.get("scope") if "scope" in body else (existing.get("scope") if existing else []))
    out_of_scope = _clean_str_list(body.get("out_of_scope") if "out_of_scope" in body else (existing.get("out_of_scope") if existing else []))
    deliverables = _clean_str_list(body.get("deliverables") if "deliverables" in body else (existing.get("deliverables") if existing else []))
    acceptance_criteria = _clean_str_list(body.get("acceptance_criteria") if "acceptance_criteria" in body else (existing.get("acceptance_criteria") if existing else []))
    evidence = _clean_str_list(body.get("evidence") if "evidence" in body else (existing.get("evidence") if existing else []))

    steps = _clean_steps(body.get("steps") if "steps" in body else (existing.get("steps") if existing else []))
    artifacts = _clean_str_list(body.get("artifacts") if "artifacts" in body else (existing.get("artifacts") if existing else []))

    now = time.time()

    # Status Provenance: agent, tests, human
    prov_raw = body.get("provenance")
    if not isinstance(prov_raw, dict):
        prov_raw = (existing.get("provenance") if existing else {}) or {}
    existing_prov = (existing.get("provenance") if existing else {}) or {}

    agent_status = _clean_str(prov_raw.get("agent", existing_prov.get("agent", "pending")), 32)
    if agent_status not in _VALID_AGENT_STATUSES:
        agent_status = "pending"

    test_status = _clean_str(prov_raw.get("tests", existing_prov.get("tests", "untested")), 32)
    if test_status not in _VALID_TEST_STATUSES:
        test_status = "untested"

    human_status = _clean_str(prov_raw.get("human", existing_prov.get("human", "pending")), 32)
    if human_status not in _VALID_HUMAN_STATUSES:
        human_status = "pending"

    def _field_set_at(field: str, new_value: str) -> float:
        # Truthful provenance (L5): record when each field's value last
        # actually changed, not just when the task happened to be saved —
        # otherwise "set_at" would just restate updated_at and imply a
        # precision this system cannot back up.
        if existing_prov.get(field) == new_value and isinstance(existing_prov.get(f"{field}_set_at"), (int, float)):
            return existing_prov[f"{field}_set_at"]
        return now

    agent_set_at = _field_set_at("agent", agent_status)
    tests_set_at = _field_set_at("tests", test_status)
    human_set_at = _field_set_at("human", human_status)

    # verification_asserted strictly requires tests passed AND human
    # approved. It is an honest name for what this is: an assertion made
    # through this same unauthenticated console UI/API, never a governed or
    # cryptographically verified fact (H1 / L5).
    verification_asserted = (test_status == "passed" and human_status == "approved")

    # overall status
    raw_status = _clean_str(body.get("status") or (existing.get("status") if existing else ""), 32)
    if verification_asserted:
        derived_status = "verification_asserted"
    elif agent_status == "completed":
        derived_status = "agent_completed"  # agent claimed done, but tests/human pending
    elif agent_status == "in_progress":
        derived_status = "in_progress"
    elif agent_status == "blocked":
        derived_status = "blocked"
    elif raw_status in CLIENT_ASSERTABLE_STATUSES:
        derived_status = raw_status
    else:
        derived_status = "draft"

    provenance = {
        "agent": agent_status,
        "agent_set_at": agent_set_at,
        "tests": test_status,
        "tests_set_at": tests_set_at,
        "human": human_status,
        "human_set_at": human_set_at,
        # No authenticated verifier exists anywhere in this system, so this
        # console never claims a governed "Verified" state — this field
        # always reads False (H1). See verification_asserted for the
        # honestly-named self-reported assertion.
        "verified": False,
        "verification_asserted": verification_asserted,
        "notes": _clean_str(prov_raw.get("notes") or existing_prov.get("notes", ""), 1000),
        # Truthful labeling (L5): "human" here means "asserted through this
        # local, single-operator console UI/API" — this app has no
        # authentication, so it cannot and does not claim to verify that a
        # human (rather than a script or another agent) actually set it.
        "source": "unauthenticated_console_ui",
    }

    # Session tracking association: strictly tracking only! A key that is
    # present but explicitly null (or "") must clear the association, not
    # fall back to the existing value (M1) — so presence in `body` decides
    # whether to use the client's value at all, and the client's value
    # (including None) decides the result from there.
    if "associated_pane_id" in body:
        associated_pane = _clean_str(body.get("associated_pane_id"), 64) or None
    else:
        associated_pane = (existing.get("associated_pane_id") if existing else None)

    if "associated_session_id" in body:
        associated_session = _clean_str(body.get("associated_session_id"), 64) or None
    else:
        associated_session = (existing.get("associated_session_id") if existing else None)

    created_at = existing.get("created_at", now) if existing else now

    return {
        "id": tid,
        "title": title,
        "template": template,
        "goal": goal,
        "scope": scope,
        "out_of_scope": out_of_scope,
        "deliverables": deliverables,
        "acceptance_criteria": acceptance_criteria,
        "evidence": evidence,
        "steps": steps,
        "artifacts": artifacts,
        "status": derived_status,
        "provenance": provenance,
        "associated_pane_id": associated_pane,
        "associated_session_id": associated_session,
        "association_mode": "tracking_only",
        "association_label": "僅追蹤關聯 (Tracking Only) · 未注入 Context",
        "created_at": created_at,
        "updated_at": now,
    }


def save_task(task_id: str | None, body: dict[str, Any]) -> dict[str, Any]:
    """Save or update a task atomically, holding the cross-process lock for
    the entire read-modify-write so no other thread's or process's write
    can be silently lost in between (H2 / H3)."""
    with _cross_process_lock():
        all_tasks = load_all()
        target_id = task_id or body.get("id")
        # A non-string id (e.g. a list or dict slipped in via the JSON body)
        # must fail validation cleanly (400), not crash: `all_tasks.get()`
        # below would raise TypeError for an unhashable target_id before
        # _validate_and_normalize ever gets a chance to reject it (L3).
        if target_id is not None and not isinstance(target_id, str):
            raise ValueError("無效的任務識別碼 (必須為 1-64 字元 ASCII 字母、數字、底線或連字號)")
        existing = all_tasks.get(target_id) if target_id else None

        if not existing and len(all_tasks) >= MAX_TASKS:
            raise ValueError(f"任務卡已達上限 {MAX_TASKS} 筆")

        normalized = _validate_and_normalize(
            target_id, body, existing, existing_ids=frozenset(all_tasks.keys())
        )
        all_tasks[normalized["id"]] = normalized

        data_str = json.dumps(all_tasks, ensure_ascii=False, indent=2)
        cfg.write_private(_path(), data_str)
        return normalized


def delete_task(task_id: str) -> bool:
    """Delete a task by ID, holding the cross-process lock for the entire
    read-modify-write (H2 / H3)."""
    if not isinstance(task_id, str) or not task_id:
        return False
    with _cross_process_lock():
        all_tasks = load_all()
        if task_id not in all_tasks:
            return False
        del all_tasks[task_id]
        data_str = json.dumps(all_tasks, ensure_ascii=False, indent=2)
        cfg.write_private(_path(), data_str)
        return True


def get_templates() -> dict[str, Any]:
    """Return all available predefined templates."""
    return TEMPLATES
