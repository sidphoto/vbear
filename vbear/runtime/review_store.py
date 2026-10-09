"""Review jobs on disk (design 5.3, 5.4): ids, the manifest and its strict
schema, and reading and updating it.

A job lives in ``<state>/reviews/<job-id>/``; the only file this module owns
is ``manifest.json``. The manifest is a *separate* schema from the launch
manifest (``review_manifest_version: 1``), with its own loader, so nothing
here relies on the launch loader. Every field has an exact type and range and
there are no extra fields: a manifest that is not exactly that is *invalid*,
and nothing is cleaned up or signalled on its say-so (``read`` reports why and
the caller marks the job for manual review).

Failure identities (design v29.8.1): a review whose *outcome* is invalid is
``<job>#invalid``; one kept for a person is ``<job>#manual_review#<retained_at
as stored>``. The outcome is decided once, after the review's processes are
dealt with, and never changes; the state may go on to ``cleaned`` without
touching it, so a failure does not disappear with the clean-up.

Process fields are tied to the state (Codex S2b part 1 review P1): ``process``
says whether a process was never started ("none"), may have been
("maybe": the manifest says launching, the pid is not recorded yet) or was
("started": the leader's identity is recorded). A manifest whose state and
process fields do not agree is not trusted.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path

from .. import strictjson
from ..numbers import finite_real
from . import agent_sessions, proctrack

REVIEWS_DIR = "reviews"
MANIFEST = "manifest.json"
MANIFEST_VERSION = 1
JOB_RE = re.compile(r"^r-[0-9a-f]{16}\Z")
SCRATCH_RE = re.compile(r"^sr-[a-z0-9_]{8}\Z")
SCRATCH_PARENT = "/private/tmp"
SCRATCH_PREFIX = "sr-"
FLOW_RE = re.compile(r"^flow-[0-9a-f]{12}\Z")
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
THREAD_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\-]{7,63}\Z")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}\Z")
VERSION_RE = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}\Z")
HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
WORKDIR_RE = re.compile(r"^/[^\x00-\x1f\x7f]{0,1023}\Z")      # the task's work directory: no control characters
ROUND_MAX = 1000
STATES = ("prepared", "launching", "running", "finished", "invalid", "manual_review", "cleaned")
TERMINAL = ("finished", "invalid", "manual_review", "cleaned")
OUTCOMES = ("valid", "invalid", "manual_review")
PROCESS = ("none", "maybe", "started")
EARLIEST = 1577836800.0                                   # 2020-01-01

REQUIRED = frozenset({
    "review_manifest_version", "job_id", "pipeline_id", "task_id", "round", "commit", "model", "codex_version",
    "argv_sha256", "scratch", "run_home", "leader", "observed", "thread_id", "exit_code", "state", "created",
    "process", "outcome", "workdir"})
OPTIONAL = frozenset({"retained_reason", "retained_at", "ended_at", "invalid_reasons"})
# which state each outcome goes with, and which outcome each terminal state may carry
STATE_OUTCOMES = {"prepared": (None,), "launching": (None,), "running": (None,), "finished": ("valid",),
                  "invalid": ("invalid",), "manual_review": ("manual_review",),
                  "cleaned": OUTCOMES}
STATE_PROCESS = {"prepared": ("none",), "launching": ("maybe",), "running": ("started",),
                 "finished": ("started",), "invalid": PROCESS, "manual_review": PROCESS, "cleaned": PROCESS}


class ReviewRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def open_dir_chain(path) -> int:
    """A descriptor on the directory ``path``, opened from "/" one component
    at a time with O_NOFOLLOW, so a symlink anywhere on the way (not only at
    the end) is refused, and nothing is resolved first (Codex S2b part 3
    review #4). ``path`` must be absolute with no "." or ".." component.
    OSError for a symlink (ELOOP), a non-directory or anything missing;
    ValueError for a path of the wrong shape. The caller closes the fd."""
    text = os.fspath(path)
    if not isinstance(text, str) or not text.startswith("/") or "\0" in text:
        raise ValueError("路徑必須是絕對路徑")
    parts = [p for p in text.split("/")[1:] if p != ""]
    if any(p in (".", "..") for p in parts):
        raise ValueError("路徑不能含 . 或 ..")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for name in parts:
            nxt = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def reviews_root(base) -> Path:
    return Path(os.path.realpath(base)) / REVIEWS_DIR


def job_dir(base, job_id: str) -> Path:
    if not (isinstance(job_id, str) and JOB_RE.match(job_id)):
        raise ReviewRefused("bad_request", "無效的審查工作 id")
    return reviews_root(base) / job_id


def run_home(base, job_id: str) -> Path:
    if not (isinstance(job_id, str) and JOB_RE.match(job_id)):
        raise ReviewRefused("bad_request", "無效的審查工作 id")
    return Path(os.path.realpath(base)) / "codex-run-homes" / job_id


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _epoch_ok(value) -> bool:
    x = finite_real(value)
    return x is not None and EARLIEST <= x <= time.time() + 86400


def _ident_ok(v) -> bool:
    return (isinstance(v, dict) and set(v) == {"inode", "dev"} and _int_in(v["inode"], 0, 2 ** 63)
            and _int_in(v["dev"], 0, 2 ** 63))


def _scratch_ok(v) -> bool:
    return (isinstance(v, dict) and set(v) == {"path", "inode", "dev"} and isinstance(v["path"], str)
            and os.path.dirname(v["path"]) == SCRATCH_PARENT
            and SCRATCH_RE.match(os.path.basename(v["path"])) is not None
            and _int_in(v["inode"], 0, 2 ** 63) and _int_in(v["dev"], 0, 2 ** 63))


def manifest_problem(m, job_id: str | None = None) -> str | None:
    """None when ``m`` is exactly a review manifest (design 5.3: every field
    an exact type and range, no other fields), else which field is wrong."""
    if not isinstance(m, dict):
        return "不是物件"
    keys = set(m)
    if not REQUIRED <= keys or keys - REQUIRED - OPTIONAL:
        return "欄位不符"
    leader = m["leader"]
    checks = [
        ("review_manifest_version", m["review_manifest_version"] == MANIFEST_VERSION
                                    and not isinstance(m["review_manifest_version"], bool)),
        ("job_id", isinstance(m["job_id"], str) and JOB_RE.match(m["job_id"]) is not None
                   and (job_id is None or m["job_id"] == job_id)),
        ("pipeline_id", isinstance(m["pipeline_id"], str) and FLOW_RE.match(m["pipeline_id"]) is not None),
        ("task_id", isinstance(m["task_id"], str) and TASK_RE.match(m["task_id"]) is not None
                    and m["task_id"] not in (".", "..")),
        ("round", _int_in(m["round"], 1, ROUND_MAX)),
        ("commit", isinstance(m["commit"], str) and COMMIT_RE.match(m["commit"]) is not None),
        ("model", isinstance(m["model"], str) and MODEL_RE.match(m["model"]) is not None),
        ("codex_version", isinstance(m["codex_version"], str) and VERSION_RE.match(m["codex_version"]) is not None),
        ("argv_sha256", isinstance(m["argv_sha256"], str) and HEX64.match(m["argv_sha256"]) is not None),
        ("scratch", _scratch_ok(m["scratch"])),
        ("run_home", _ident_ok(m["run_home"])),
        ("leader", leader is None or (isinstance(leader, dict) and set(leader) == {"pid", "start", "source"}
                                      and _int_in(leader["pid"], 1, 99999)
                                      and isinstance(leader["start"], str) and agent_sessions._start_ok(leader["start"])
                                      and leader["source"] in ("libproc", "ps"))),
        ("observed", agent_sessions._observed_ok(m["observed"])),
        ("thread_id", m["thread_id"] is None or (isinstance(m["thread_id"], str)
                                                 and THREAD_RE.match(m["thread_id"]) is not None)),
        ("exit_code", m["exit_code"] is None or _int_in(m["exit_code"], -64, 255)),
        ("state", m["state"] in STATES),
        ("created", _epoch_ok(m["created"])),
        ("retained_reason", "retained_reason" not in m
                            or (isinstance(m["retained_reason"], str) and len(m["retained_reason"]) <= 4096)),
        ("retained_at", "retained_at" not in m or _epoch_ok(m["retained_at"])),
        ("ended_at", "ended_at" not in m or _epoch_ok(m["ended_at"])),
        ("invalid_reasons", "invalid_reasons" not in m
                            or (isinstance(m["invalid_reasons"], list) and len(m["invalid_reasons"]) <= 16
                                and all(isinstance(x, str) and len(x) <= 256 for x in m["invalid_reasons"]))),
        ("workdir", isinstance(m["workdir"], str) and WORKDIR_RE.match(m["workdir"]) is not None
                    and os.path.normpath(m["workdir"]) == m["workdir"]),
        ("process", m["process"] in PROCESS),
        ("outcome", m["outcome"] is None or m["outcome"] in OUTCOMES),
    ]
    for name, ok in checks:
        if not ok:
            return f"{name} 不合法"
    return _consistency_problem(m)


def _consistency_problem(m: dict) -> str | None:
    """The fields that must agree with each other (review P1, P2): state with
    outcome and process; process with leader and observed; the fields an
    outcome or a final state requires. Nothing is cleaned up or signalled
    from a manifest that fails any of these."""
    state, outcome, process = m["state"], m["outcome"], m["process"]
    if outcome not in STATE_OUTCOMES[state]:
        return "state 與 outcome 不相容"
    if process not in STATE_PROCESS[state]:
        return "state 與 process 不相容"
    if (process == "started") != (m["leader"] is not None):
        return "process 與 leader 不相容（啟動過程序就必須有 leader）"
    if m["observed"] and process != "started":
        return "沒有啟動過程序卻有已觀察到的後代"
    if state in TERMINAL and "ended_at" not in m:
        return "終態缺少 ended_at"
    if state == "finished" and m["exit_code"] is None:
        return "finished 缺少 exit_code"
    if outcome == "invalid" and not m.get("invalid_reasons"):
        return "invalid 缺少 invalid_reasons"
    if outcome == "manual_review" and ("retained_at" not in m or not m.get("retained_reason")):
        return "manual_review 缺少 retained_at 或 retained_reason"
    return None


def read_manifest(base, job_id: str) -> dict:
    """The job's manifest, exactly validated. ReviewRefused otherwise (the
    caller then keeps the job for a person; it never cleans up from a
    manifest it could not trust)."""
    ldir = job_dir(base, job_id)
    uid = os.getuid()
    try:
        st = os.lstat(ldir)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or st.st_mode & 0o077:
            raise ReviewRefused("unsafe_path", "審查工作資料夾不是本人的 0700 一般資料夾")
        parsed = strictjson.load_owned_object(ldir / MANIFEST, strictjson.MANIFEST)
    except OSError as exc:
        raise ReviewRefused("unsafe_path", f"審查工作無法開啟（{exc.strerror}）") from exc
    if not parsed.ok:
        raise ReviewRefused("manifest_invalid", f"manifest 無法讀取（{parsed.problem}）")
    problem = manifest_problem(parsed.value, job_id)
    if problem:
        raise ReviewRefused("manifest_invalid", f"manifest 不符（{problem}）")
    return parsed.value


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_job_dir(base, job_id: str) -> Path:
    """The job directory (0700), exclusive; the reviews root is created if
    needed. The caller writes the first manifest into it."""
    root = reviews_root(base)
    old = os.umask(0o077)
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
        agent_sessions._owned_dir(root, os.getuid())
        ldir = job_dir(base, job_id)
        os.mkdir(ldir, 0o700)                       # fails if it exists
        _fsync_dir(root)
    finally:
        os.umask(old)
    return ldir


def write_new_manifest(base, m: dict) -> None:
    """The first manifest of a job: validated before it is written, created
    exclusively, durable (file and directory)."""
    problem = manifest_problem(m)
    if problem:
        raise ReviewRefused("manifest_invalid", f"要寫入的 manifest 不符（{problem}）")
    ldir = job_dir(base, m["job_id"])
    agent_sessions._write_private(ldir / MANIFEST, json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    _fsync_dir(ldir)


def update_manifest(base, job_id: str, **fields) -> dict:
    """Read, change, validate, replace: a change that would make the manifest
    invalid is refused before anything is written."""
    m = read_manifest(base, job_id)
    old = dict(m)
    m.update(fields)
    problem = manifest_problem(m, job_id)
    if problem:
        raise ReviewRefused("manifest_invalid", f"更新後的 manifest 不符（{problem}）")
    if old["outcome"] is not None:
        # decided once (v29.8.1): what the failure identity is made of cannot change
        same = (m["outcome"] == old["outcome"] and m.get("retained_at") == old.get("retained_at")
                and m.get("invalid_reasons") == old.get("invalid_reasons") and m["job_id"] == old["job_id"])
        if not same or (old["state"] in TERMINAL and m["state"] not in ("cleaned", old["state"])):
            raise ReviewRefused("manifest_invalid", "審查結果已決定，不能再改")
    agent_sessions._write_private(job_dir(base, job_id) / MANIFEST,
                                  json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + "\n", replace=True)
    return m


def retain(base, job_id: str, reason: str) -> None:
    """Keep the job for a person. Best effort: when even that cannot be written
    the next recovery finds the job in a state that is not final, and the
    failure identity of a manifest that cannot be read is recomputed from the
    directory itself (stream_flow)."""
    try:
        m = read_manifest(base, job_id)
        now = time.time()
        if m["outcome"] is None:
            update_manifest(base, job_id, state="manual_review", outcome="manual_review",
                            retained_reason=str(reason)[:4096] or "交人工處理", retained_at=now, ended_at=now)
        else:
            # already decided (its identity cannot change): only say why a person should look
            update_manifest(base, job_id, retained_reason=str(reason)[:4096])
    except (OSError, ReviewRefused):
        pass


def list_jobs(base) -> list[str]:
    """Every entry under reviews/, job-shaped or not. The root is checked as
    sessions/ is (Codex S2b part 1 review P2): a private plain directory of
    ours, not a symlink. A root that does not exist has no jobs, which is
    believed only together with the flow side (flow_links): a flow with a
    review record whose job is gone is refused by the caller. Anything else
    raises; nothing is read as "no jobs" on an error."""
    root = reviews_root(base)
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        return []
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ReviewRefused("unsafe_path", "reviews/ 不是本人的 0700 一般資料夾")
    try:
        return sorted(os.listdir(root))
    except OSError as exc:
        raise ReviewRefused("unsafe_path", f"reviews/ 無法列出（{exc.strerror}）") from exc


def failure_id(m: dict) -> str | None:
    """The v29.8.1 identity of this job's failure, or None when it has none."""
    if m["outcome"] == "invalid":
        return f"{m['job_id']}#invalid"
    if m["outcome"] == "manual_review":
        return f"{m['job_id']}#manual_review#{json.dumps(m['retained_at'])}"
    return None


def processes_gone(m: dict, rows) -> tuple[str, str]:
    """("gone" | "alive" | "unknown", why) for a job's recorded processes,
    from a process table (None: unavailable). Nothing is signalled. The same
    rule as stream recovery: recorded identities, and live members of the
    leader's group that were never recorded."""
    leader, process = m["leader"], m["process"]
    if process == "none":
        return "gone", ""                           # no process was ever started (the schema ties this to leader None)
    if process == "maybe" or leader is None:
        return "unknown", "啟動程序前後當機，無法得知 pid"
    if rows is None:
        return "unknown", "無法取得程序表"
    if leader["source"] != proctrack.SOURCE:
        return "unknown", "程序身分紀錄的來源與目前不同，無法比對"
    identities = list(m["observed"]) + [[leader["pid"], leader["start"]]]
    alive = proctrack.DescendantTracker(leader["pid"], identities).live(rows)
    if alive:
        return "alive", "仍有已記錄的程序存活：" + ", ".join(str(r["pid"]) for r in alive[:8])
    members = [r for r in rows if r["pgid"] == leader["pid"] and "Z" not in r["stat"]]
    if members:
        return "alive", "程序群組裡仍有未記錄的程序存活：" + ", ".join(str(r["pid"]) for r in members[:8])
    return "gone", ""
