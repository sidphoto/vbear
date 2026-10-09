"""How a Codex review ends (design 5.3, 5.5, 5.6, 5.7): once the process group
is proven empty, decide whether the review is valid, save its record, record
the outcome in the manifest, and clean up.

Everything is judged from the files on disk (events.jsonl in the job
directory, the rollout in CODEX_HOME, the clone in the scratch), never from
what a running process object remembers, so the live path and the recovery
after a daemon restart are the same code. The caller passes only what the
process itself can tell (how it ended).

The outcome is decided once and written once (review_store: the outcome of a
manifest never changes):

  valid          every rule of 5.5 and 5.6 holds. A NEEDS WORK or BLOCKED
                 verdict is still a valid review: it is the reviewer's
                 answer, not a failure of the review.
  invalid        any rule does not hold (or the daemon restarted, or the
                 flow was held). A v29.8 failure.
  manual_review  the process group was not proven gone, a partial file could
                 not be removed, or the decision itself could not be
                 written. Nothing is cleaned up; a v29.8 failure.

The record (pipelines/<task>/reviews/<round>/) gets the report, the event and
stderr files, the rollout copy and result.json, each written exclusively and
durably, result.json last. The rollout *source* is never deleted.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import stat
import time
from dataclasses import dataclass, field

from .. import git_head, git_objects, strictjson
from . import codex_constants as cc
from . import pipeline_store, review_codex, review_store, review_validate

EVENTS_NAME, STDERR_NAME = "events.jsonl", "stderr.log"
SCRATCH_PARENT = review_store.SCRATCH_PARENT
MAX_REASON = 256
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass
class Finish:
    outcome: str                         # valid | invalid | manual_review
    reasons: list = field(default_factory=list)
    verdict: str | None = None
    base_is_ancestor: bool | None = None
    cleaned: bool = False
    leftover: str | None = None          # a partial file that could not be removed (the job is kept)
    leftover_bytes: int = 0
    problem: str | None = None           # why the clean-up stopped or the manifest could not be written
    result: dict | None = None
    record_complete: bool = False        # result.json (the commit marker) was written after the outcome


def _short(reasons) -> list[str]:
    out: list[str] = []
    for r in reasons:
        r = str(r)[:MAX_REASON]
        if r and r not in out:
            out.append(r)
    return out[:16]


class _Dir:
    def __init__(self, path):
        self.path, self.fd = path, None

    def __enter__(self) -> int:
        self.fd = os.open(str(self.path), _DIR)
        return self.fd

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)


# ---- reading what the process left ------------------------------------------------------------------

@dataclass
class _Blob:
    """A job file read once, from one descriptor: the bytes that are judged
    are the bytes that are saved, and the identity it had when read is kept
    so that a replacement in between is noticed (Codex S2b part 3c review #2)."""
    data: bytes
    dev: int
    ino: int
    size: int
    sha256: str


def _read_blob(job_fd: int, name: str, limit: int) -> _Blob:
    fd, _ = strictjson.open_owned(name, dir_fd=job_fd, max_bytes=limit)
    try:
        st = os.fstat(fd)
        data = strictjson.read_fd(fd, limit)
    finally:
        os.close(fd)
    return _Blob(data, st.st_dev, st.st_ino, len(data), hashlib.sha256(data).hexdigest())


def _unchanged(job_fd: int, name: str, blob: _Blob) -> bool:
    """Whether ``name`` is still exactly what was read: a regular file (not a
    link) with the same device, inode and size, and the same SHA-256 of its
    bytes (a same-size rewrite in place keeps the first three; Codex 3c R2).
    Anything else, and any error, is "no"."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=job_fd)
    except OSError:
        return False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino, st.st_size) != (blob.dev, blob.ino, blob.size):
            return False
        h, left = hashlib.sha256(), blob.size + 1             # one byte more than expected: a longer file shows
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
        return left == 1 and h.hexdigest() == blob.sha256
    except OSError:
        return False
    finally:
        os.close(fd)


def judge_events(data: bytes, c: cc.CodexConstants):
    """The bytes of events.jsonl through the same tracker the live run used.
    (tracker, EventsResult or None, reasons)."""
    tracker = review_validate.EventsTracker(c)
    reasons: list[str] = []
    try:
        for line in strictjson.iter_data_lines(data, strictjson.CODEX_EVENTS):
            tracker.feed(line)
    except strictjson.LineError as exc:
        reasons.append(f"events.jsonl 不符：{exc}")
    except review_validate.ReviewInvalid as exc:
        reasons += exc.reasons
    if reasons:
        return tracker, None, reasons
    try:
        return tracker, tracker.finish(), []
    except review_validate.ReviewInvalid as exc:
        return tracker, None, list(exc.reasons)


# ---- the record -------------------------------------------------------------------------------------------

@dataclass
class _Saved:
    ok: bool
    reason: str | None = None
    leftover: str | None = None
    leftover_bytes: int = 0


def _write_new(dir_fd: int, name: str, data: bytes, dst_path: str) -> _Saved:
    """A file created exclusively, written whole, synced (file and directory).
    A failure removes it; if that fails too the leftover is reported."""
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                     dir_fd=dir_fd)
    except OSError as exc:
        return _Saved(False, f"審查紀錄的 {name} 無法建立（{exc.strerror or type(exc).__name__}）")
    written = 0
    try:
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                if n <= 0:
                    raise OSError(5, "寫入沒有進展")
                written += n
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(dir_fd)
        return _Saved(True)
    except Exception as exc:
        out = _Saved(False, f"審查紀錄的 {name} 無法寫入（{type(exc).__name__}）")
        try:
            os.unlink(name, dir_fd=dir_fd)
        except Exception:
            out.leftover = f"{dst_path.rstrip('/')}/{name}"
            out.leftover_bytes = written
        return out


# ---- clean-up -----------------------------------------------------------------------------------------------

def _remove_child(parent_path, name: str, ident: dict) -> str | None:
    """Remove the directory ``name`` under ``parent_path``, only if it is the
    one the manifest recorded (a directory, not a symlink, same inode and
    device). None when it is gone afterwards (or was never there)."""
    try:
        pfd = os.open(str(parent_path), _DIR)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{name} 的上層資料夾無法開啟（{exc.strerror}）"
    try:
        try:
            st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(st.st_mode) or (st.st_ino, st.st_dev) != (ident["inode"], ident["dev"]):
            return f"{name} 不是紀錄中的那個資料夾（身分不符），不刪除"
        try:
            shutil.rmtree(name, dir_fd=pfd)
        except OSError as exc:
            return f"{name} 無法刪除（{exc.strerror or type(exc).__name__}）"
        try:
            os.stat(name, dir_fd=pfd, follow_symlinks=False)
            return f"{name} 刪除後仍然存在"
        except FileNotFoundError:
            return None
    finally:
        os.close(pfd)


def cleanup_job(base, m: dict, *, keep_job_files: bool = False) -> str | None:
    """Delete exactly what the manifest recorded: the scratch (only a direct
    child of /private/tmp named sr-…, same inode and device), the job's run
    home, and, unless ``keep_job_files``, events.jsonl and stderr.log in the
    job directory. Never a glob. None when everything is gone, else the
    first problem (the job is then kept for a person)."""
    problems = []
    scratch = m["scratch"]
    name = os.path.basename(scratch["path"])
    if not review_store.SCRATCH_RE.match(name) or os.path.dirname(scratch["path"]) != SCRATCH_PARENT:
        return "暫存區的位置與核准樣式不符，不刪除"
    p = _remove_child(SCRATCH_PARENT, name, scratch)
    if p:
        problems.append(p)
    p = _remove_child(os.path.dirname(review_store.run_home(base, m["job_id"])), m["job_id"], m["run_home"])
    if p:
        problems.append(p)
    if not keep_job_files:
        try:
            with _Dir(review_store.job_dir(base, m["job_id"])) as jfd:
                for fname in (EVENTS_NAME, STDERR_NAME):
                    try:
                        os.unlink(fname, dir_fd=jfd)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            problems.append(f"審查工作資料夾的檔案無法刪除（{exc.strerror or type(exc).__name__}）")
    return "；".join(problems) if problems else None


# ---- the decision ---------------------------------------------------------------------------------------------

def finish_review(base, m: dict, run: dict, *, c: cc.CodexConstants, now: float | None = None) -> Finish:
    """Decide, save, record, clean up. ``run``: how the process ended —
    manual_review (str | None: the group was not proven gone), interrupted
    (bool: a daemon restart or a stop cut it short), exit_code, exit_signal,
    terminated_for, invalid_reasons (what the run itself saw)."""
    now = time.time() if now is None else now
    job_id = m["job_id"]
    if run.get("manual_review"):
        review_store.retain(base, job_id, run["manual_review"])
        return Finish("manual_review", [str(run["manual_review"])[:MAX_REASON]])
    reasons: list[str] = []
    # condition 1 (5.5): exit 0, and not ended by VBear
    if run.get("interrupted"):
        reasons.append("審查被中斷（daemon 重啟，或流程被停止）")
    if run.get("terminated_for"):
        reasons.append(f"審查被 VBear 結束（{run['terminated_for']}）")
    elif run.get("exit_signal") is not None:
        reasons.append("Codex 被訊號結束")
    elif not run.get("interrupted") and run.get("exit_code") != 0:
        reasons.append("Codex 沒有以 0 結束")
    reasons += list(run.get("invalid_reasons") or [])
    # A review that ran while its flow was stopped is invalid (design 7, v29.9),
    # even if the process ended well and every file is fine. The daemon says
    # so when it saw the hold; the hold file is read here as well (recovery
    # has no one to ask), and not being able to tell counts as held
    # (Codex S2b part 3c review #3).
    try:
        held = bool(run.get("held")) or pipeline_store.is_held(base, m["pipeline_id"])
    except Exception:
        held = True
    if held:
        reasons.append("流程在審查期間被停止，或無法確認沒有被停止，審查無效")
    leftover = None
    leftover_bytes = 0
    saved_all = True
    record_path = ""
    verdict = ancestor = None
    rollout_info = None
    thread = None
    result: dict = {}
    jdir = review_store.job_dir(base, job_id)
    record_fd = None
    try:
        with pipeline_store.Pipeline(base, m["task_id"], create=False) as p:
            try:
                record_fd = p.review_dir_fd(m["round"])
                record_path = f"pipelines/{m['task_id']}/reviews/{m['round']}"
            except (OSError, pipeline_store.StoreRefused) as exc:
                reasons.append(f"審查紀錄資料夾無法開啟（{type(exc).__name__}）")
                saved_all = False
    except (OSError, pipeline_store.StoreRefused) as exc:
        reasons.append(f"流程資料夾無法開啟（{type(exc).__name__}）")
        saved_all = False
    try:
        with _Dir(jdir) as job_fd:
            blobs: dict[str, _Blob] = {}
            for fname in (EVENTS_NAME, STDERR_NAME):
                try:
                    blobs[fname] = _read_blob(job_fd, fname, strictjson.CODEX_EVENTS.file_bytes)
                except (strictjson.ReadRefused, OSError) as exc:
                    reasons.append(f"{fname} 無法讀取（{type(exc).__name__}），不能判定或保存到審查紀錄")
                    saved_all = False
            if EVENTS_NAME in blobs:
                tracker, events, ev_reasons = judge_events(blobs[EVENTS_NAME].data, c)
            else:
                tracker, events, ev_reasons = review_validate.EventsTracker(c), None, []
            reasons += ev_reasons
            thread = tracker.thread_id
            # the rollout (5.6) and its copy
            rfd = None
            if thread:
                dates = [datetime.datetime.fromtimestamp(m["created"]), datetime.datetime.fromtimestamp(now)]
                try:
                    rfd, st, rel = review_validate.open_rollout(review_codex.codex_home_path(base), c, thread, dates)
                except review_validate.ReviewInvalid as exc:
                    reasons += exc.reasons
            else:
                reasons.append("沒有 thread_id，找不到 rollout")
            if rfd is not None:
                try:
                    v = review_validate.validate_rollout(
                        rfd, c, thread_id=thread, scratch=m["scratch"]["path"], model=m["model"],
                        events_usage=events.usage if events else {}, last_message=events.last_message if events else "")
                    reasons += v.reasons
                    rollout_info = {"sha256": v.sha256, "size": v.size, "source": rel, "source_dev": st.st_dev,
                                    "source_inode": st.st_ino, "copied": False, "responses": v.responses}
                    if v.complete and record_fd is not None:
                        cr = review_validate.copy_rollout(rfd, record_fd, "rollout.jsonl", expect_sha256=v.sha256,
                                                          src_before=st, dst_path=record_path)
                        if cr.ok:
                            rollout_info["copied"] = True
                        else:
                            reasons += cr.reasons
                            saved_all = False
                            if cr.leftover:
                                leftover, leftover_bytes = cr.leftover, cr.leftover_bytes
                    elif not v.complete:
                        saved_all = False
                finally:
                    os.close(rfd)
            # the report (5.5 item 3)
            if events is not None:
                rep = review_validate.check_report(events.last_message, m["commit"])
                verdict, ancestor = rep.verdict, rep.base_is_ancestor
                reasons += rep.problems
            # the object under review (5.7)
            if git_objects.commit_exists(m["workdir"], m["commit"]) is not True:
                reasons.append("被審 commit 不存在於任務工作目錄，或無法核對")
            head = git_head.read_head(os.path.join(m["scratch"]["path"], "repo"))
            if head.get("commit") != m["commit"] or head.get("ref") is not None:
                reasons.append("審查暫存區的 repo 不是 detached 在被審 commit")
            # save the record; result.json last
            if record_fd is not None:
                files = []
                if events is not None and review_validate._text(events.last_message, review_validate.REPORT_MAX):
                    files.append(("last.md", events.last_message.encode("utf-8")))
                for name in (EVENTS_NAME, STDERR_NAME):
                    if name in blobs:
                        files.append((name, blobs[name].data))
                for name, data in files:
                    saved = _write_new(record_fd, name, data, record_path)
                    if not saved.ok:
                        saved_all = False
                        reasons.append(saved.reason)
                        if saved.leftover:
                            leftover, leftover_bytes = leftover or saved.leftover, leftover_bytes + saved.leftover_bytes
            for fname, blob in blobs.items():
                if not _unchanged(job_fd, fname, blob):
                    reasons.append(f"{fname} 在判定與保存之間被替換或改動")
                    saved_all = False                                  # the job's files are kept for a person
    except OSError as exc:
        reasons.append(f"審查工作資料夾無法開啟（{exc.strerror or type(exc).__name__}）")
        saved_all = False
    except BaseException:
        if record_fd is not None:
            os.close(record_fd)
        raise
    reasons = _short(reasons)
    valid = not reasons and not leftover
    result = {"v": 1, "job_id": job_id, "round": m["round"], "commit": m["commit"], "valid": valid,
              "verdict": verdict, "base_is_ancestor": ancestor, "reasons": reasons, "thread_id": thread,
              "exit_code": run.get("exit_code"), "exit_signal": run.get("exit_signal"),
              "terminated_for": run.get("terminated_for"), "rollout": rollout_info,
              "finished_at": now}
    out = Finish("valid" if valid else "invalid", reasons, verdict, ancestor,
                 leftover=leftover, leftover_bytes=leftover_bytes, result=result)
    try:
        return _decide(base, m, run, out, result, thread, record_fd, record_path, saved_all, now)
    finally:
        if record_fd is not None:
            os.close(record_fd)


def _decide(base, m, run, out: Finish, result: dict, thread, record_fd, record_path: str, saved_all: bool,
            now: float) -> Finish:
    """The order that makes result.json a commit marker (Codex S2b part 3c
    review #1): the record's files are saved already; the outcome goes into
    the manifest; only then result.json. A manifest that cannot be written
    leaves no result.json, so no record claims an outcome the manifest does
    not hold."""
    job_id = m["job_id"]
    valid = out.outcome == "valid"
    left_note = f"已保存的檔案留在 {record_path}，沒有 result.json" if record_path else "沒有可用的審查紀錄資料夾"
    # a partial file that cannot be removed keeps the whole job for a person
    if out.leftover:
        out.outcome = "manual_review"
        out.reasons = _short(out.reasons + [f"不完整的檔案無法移除：{out.leftover}"])
        review_store.retain(base, job_id, f"不完整的檔案無法移除：{out.leftover}；{left_note}")
        return out
    try:
        fields = {"state": "finished" if valid else "invalid", "outcome": "valid" if valid else "invalid",
                  "ended_at": now, "exit_code": run.get("exit_code") if isinstance(run.get("exit_code"), int) else None}
        if thread:
            fields["thread_id"] = thread
        if not valid:
            fields["invalid_reasons"] = out.reasons
        elif fields["exit_code"] != 0:
            raise review_store.ReviewRefused("manifest_invalid", "valid 的審查必須以 0 結束")
        m = review_store.update_manifest(base, job_id, **fields)
    except (OSError, review_store.ReviewRefused) as exc:
        out.outcome = "manual_review"
        out.problem = f"審查結果無法寫入 manifest（{type(exc).__name__}）"
        out.reasons = _short(out.reasons + [out.problem])
        review_store.retain(base, job_id, f"{out.problem}；{left_note}")
        return out
    # the outcome is on disk: now the marker that says the record is whole
    if record_fd is not None:
        saved = _write_new(record_fd, "result.json", json.dumps(result, ensure_ascii=False, sort_keys=True).encode(),
                           record_path)
        if saved.ok:
            out.record_complete = True
        else:
            saved_all = False
            out.problem = saved.reason
            out.leftover, out.leftover_bytes = saved.leftover, saved.leftover_bytes
            review_store.retain(base, job_id, f"{saved.reason}；審查紀錄不完整")
    else:
        saved_all = False
        out.problem = "沒有審查紀錄資料夾，無法寫入 result.json"
        review_store.retain(base, job_id, out.problem)
    # clean up, but only what is safe: the group is proven gone here
    problem = cleanup_job(base, m, keep_job_files=not saved_all)
    if problem:
        out.problem = "；".join(x for x in (out.problem, problem) if x)
        review_store.retain(base, job_id, out.problem)         # only a reason: the outcome is decided
        return out
    try:
        review_store.update_manifest(base, job_id, state="cleaned")
        out.cleaned = True
    except (OSError, review_store.ReviewRefused) as exc:
        out.problem = f"manifest 無法改成 cleaned（{type(exc).__name__}）"
    return out
