"""Review jobs on disk (design 5.3, 5.4): ids, the manifest and its strict
schema, and reading and updating it.

A job lives in ``<state>/reviews/<job-id>/``; the only file this module owns
is ``manifest.json``. The manifest is a *separate* schema from the launch
manifest (``review_manifest_version: 1``), with its own loader, so nothing
here relies on the launch loader. Every field has an exact type and range and
there are no extra fields: a manifest that is not exactly that is *invalid*,
and nothing is cleaned up or signalled on its say-so (``read`` reports why and
the caller marks the job for manual review).

Failure identities (design v29.8.1): a review that ended invalid is
``<job>#invalid``; one kept for a person is ``<job>#manual_review#<retained_at
as stored>``. The manifest outlives the job's clean-up, so neither disappears
with it.
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
ROUND_MAX = 1000
STATES = ("prepared", "running", "finished", "invalid", "manual_review", "cleaned")
EARLIEST = 1577836800.0                                   # 2020-01-01

REQUIRED = frozenset({
    "review_manifest_version", "job_id", "pipeline_id", "task_id", "round", "commit", "model", "codex_version",
    "argv_sha256", "scratch", "run_home", "leader", "observed", "thread_id", "exit_code", "state", "created"})
OPTIONAL = frozenset({"retained_reason", "retained_at", "ended_at", "invalid_reasons"})


class ReviewRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
    ]
    for name, ok in checks:
        if not ok:
            return f"{name} 不合法"
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
    m.update(fields)
    problem = manifest_problem(m, job_id)
    if problem:
        raise ReviewRefused("manifest_invalid", f"更新後的 manifest 不符（{problem}）")
    agent_sessions._write_private(job_dir(base, job_id) / MANIFEST,
                                  json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + "\n", replace=True)
    return m


def retain(base, job_id: str, reason: str) -> None:
    """Keep the job for a person. Best effort: when even that cannot be written
    the next recovery finds the job in a state that is not final, and the
    failure identity of a manifest that cannot be read is recomputed from the
    directory itself (stream_flow)."""
    try:
        update_manifest(base, job_id, state="manual_review", retained_reason=str(reason)[:4096],
                        retained_at=time.time())
    except (OSError, ReviewRefused):
        pass


def list_jobs(base) -> list[str]:
    """Every entry under reviews/, job-shaped or not. An unreadable root
    raises (nothing is read as "no jobs" on an error); a root that was never
    created has none."""
    try:
        return sorted(os.listdir(reviews_root(base)))
    except FileNotFoundError:
        return []


def failure_id(m: dict) -> str | None:
    """The v29.8.1 identity of this job's failure, or None when it has none."""
    if m["state"] == "invalid":
        return f"{m['job_id']}#invalid"
    if m["state"] == "manual_review":
        return f"{m['job_id']}#manual_review#{json.dumps(m.get('retained_at'))}"
    return None


def processes_gone(m: dict, rows) -> tuple[str, str]:
    """("gone" | "alive" | "unknown", why) for a job's recorded processes,
    from a process table (None: unavailable). Nothing is signalled. The same
    rule as stream recovery: recorded identities, and live members of the
    leader's group that were never recorded."""
    leader = m["leader"]
    if rows is None:
        return "unknown", "無法取得程序表"
    if leader is None:
        return "gone", ""
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
