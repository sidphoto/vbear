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
import json
import os
import secrets
import shutil
import stat
import time
from dataclasses import dataclass, field

from .. import git_head, git_objects, strictjson
from . import codex_constants as cc
from . import pipeline_store, review_codex, review_run, review_store, review_validate, stream_flow

EVENTS_NAME, STDERR_NAME = "events.jsonl", "stderr.log"
# what the run itself may write (review_run), so what is read back is bounded the same way (Codex 3c R4 P2)
EVENTS_LIMIT = review_run.EVENTS_CAP
STDERR_LIMIT = review_run.STDERR_CAP
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


SCRATCH_SCAN_MAX = 64                 # entries read from the scratch for the message, never more


def _scratch_names(scratch) -> str:
    """For the message that the review's clone is not where it should be: the NAMES of the directories under the
    scratch, so the next reading says "there is 'toy repo' and no repo". Names only, never content; at most 64
    entries are read (a reviewer may have made many), only directories are listed (a file or a link is not), at
    most five are shown, each cut to 40 characters with control characters shown as ?."""
    shown: list[str] = []
    seen = 0
    more = False
    try:
        with os.scandir(str(scratch)) as it:
            for entry in it:
                seen += 1
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir and not entry.name.startswith("."):
                    shown.append("".join(ch if ch.isprintable() else "?" for ch in entry.name)[:40])
                if seen >= SCRATCH_SCAN_MAX:          # the 64th is the last one read: more may follow
                    more = True
                    break
    except OSError:
        return ""
    shown.sort()
    extra = len(shown) > 5 or more
    shown = shown[:5]
    if not shown and not more:
        return "（暫存區底下沒有任何資料夾）"
    return ("（暫存區底下的資料夾：" + "、".join(f"'{n}'" for n in shown) + ("…以及更多" if extra else "") + "）")


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

def _read_once(job_fd: int, name: str, limit: int) -> bytes:
    """A job file, opened once and read whole into memory (at most ``limit``
    bytes). Everything after this - judging it and saving it into the record -
    uses these bytes and never opens the name again, so there is no gap
    between "what was judged" and "what was saved" for anyone to use
    (Codex S2b part 3c R3: the earlier re-open to compare had a gap of its
    own)."""
    fd, _ = strictjson.open_owned(name, dir_fd=job_fd, max_bytes=limit)
    try:
        return strictjson.read_fd(fd, limit)
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
    result.json is published atomically. A failure removes what this call
    created; if that fails too the leftover is reported."""
    if name == "result.json":
        return _write_marker(dir_fd, name, data, dst_path)
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


def _write_marker(dir_fd: int, name: str, data: bytes, dst_path: str) -> _Saved:
    """Publish complete bytes without replacing an existing marker. link()
    checks destination absence atomically, unlike a check followed by rename.
    Both names are relative to the same pinned directory descriptor. Old
    temporary files are never reused or trusted; recovery rebuilds from the
    saved copies and quota counts every remaining file."""
    tmp = f".{name}.{secrets.token_hex(16)}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                     dir_fd=dir_fd)
    except OSError as exc:
        return _Saved(False, f"審查紀錄的 {name} 暫存檔無法建立（{exc.strerror or type(exc).__name__}）")
    written, linked = 0, False
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
        os.link(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
        linked = True
        os.unlink(tmp, dir_fd=dir_fd)
        os.fsync(dir_fd)
        return _Saved(True)
    except Exception as exc:
        out = _Saved(False, f"審查紀錄的 {name} 無法寫入（{type(exc).__name__}）")
        # Only remove the public name if this call created it. In particular,
        # EEXIST must leave the earlier marker untouched.
        for entry in ([name, tmp] if linked else [tmp]):
            try:
                os.unlink(entry, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            except Exception:
                path = f"{dst_path.rstrip('/')}/{entry}"
                try:
                    size = os.stat(entry, dir_fd=dir_fd, follow_symlinks=False).st_size
                except OSError:
                    size = written
                if out.leftover is None:
                    out.leftover = path
                out.leftover_bytes += size
                out.reason += f"；不完整的檔案無法移除：{path}（{size} bytes）"
        try:
            os.fsync(dir_fd)
        except OSError:
            out.reason += "；移除後資料夾無法同步，需人工確認"
        return out


# ---- clean-up -----------------------------------------------------------------------------------------------

def _remove_child(parent_path, name: str, ident: dict) -> str | None:
    """Remove the directory ``name`` under ``parent_path``, only if it is the
    one the manifest recorded (a directory, not a symlink, same inode and
    device). None when it is gone afterwards (or was never there).

    The identity is checked, then the directory is renamed to a private name
    and checked again before anything is deleted: what is removed is what was
    verified at the private name, which nobody else is looking for, not
    whatever the public name points at by then (the same idea as the
    ".partial" names elsewhere). A directory that turns out not to be ours
    is renamed back. A leftover from an earlier attempt that died after the
    rename is recognised by the same identity and finished."""
    private = f".{name}.deleting"
    try:
        pfd = os.open(str(parent_path), _DIR)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{name} 的上層資料夾無法開啟（{exc.strerror}）"

    def is_ours(n: str) -> bool | None:
        """True / False, or None when there is no such entry."""
        try:
            st = os.stat(n, dir_fd=pfd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return stat.S_ISDIR(st.st_mode) and (st.st_ino, st.st_dev) == (ident["inode"], ident["dev"])

    def remove(n: str) -> str | None:
        try:
            shutil.rmtree(n, dir_fd=pfd)
        except OSError as exc:
            return f"{name} 無法刪除（{exc.strerror or type(exc).__name__}）"
        if is_ours(n) is not None:
            return f"{name} 刪除後仍然存在"
        return None

    try:
        left = is_ours(private)
        if left is False:
            return f"{private} 不是紀錄中的那個資料夾（身分不符），不刪除"
        if left:                                           # an earlier attempt died after the rename
            problem = remove(private)
            if problem:
                return problem
        ours = is_ours(name)
        if ours is None:
            return None
        if not ours:
            return f"{name} 不是紀錄中的那個資料夾（身分不符），不刪除"
        try:
            os.rename(name, private, src_dir_fd=pfd, dst_dir_fd=pfd)
        except OSError as exc:
            return f"{name} 無法改成私有名稱以便刪除（{exc.strerror or type(exc).__name__}）"
        if not is_ours(private):                           # the public name was swapped before the rename
            try:
                os.rename(private, name, src_dir_fd=pfd, dst_dir_fd=pfd)
            except OSError:
                pass
            return f"{name} 在驗證與刪除之間被換成別的東西（身分不符），已放回，不刪除"
        return remove(private)
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
    # Before anything is opened for writing (Codex 3c R4 P1): a job that was
    # decided already is never judged or saved again. The manifest says
    # which of the three situations this call is in.
    try:
        current = review_store.read_manifest(base, job_id)
    except (OSError, review_store.ReviewRefused) as exc:
        problem = f"審查工作的 manifest 無法讀取（{type(exc).__name__}），不判定也不寫入"
        return Finish("manual_review", [problem], problem=problem)
    if current["outcome"] is not None:
        return _resume_decided(base, current, now)
    m = current
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
    before_files = list(reasons)
    # A review that ran while its flow was stopped is invalid (design 7, v29.9),
    # even if the process ended well and every file is fine. The daemon says
    # so when it saw the hold; the hold file is read here as well (recovery
    # has no one to ask), and not being able to tell counts as held
    # (Codex S2b part 3c review #3).
    try:
        held = bool(run.get("held")) or pipeline_store.is_held(base, m["pipeline_id"])
    except Exception:
        held = True
    held_reason = "流程在審查期間被停止，或無法確認沒有被停止，審查無效" if held else None
    if held_reason:
        reasons.append(held_reason)
    leftover = None
    leftover_bytes = 0
    saved_all = True
    record_path = ""
    verdict = ancestor = None
    rollout_info = None
    usage, usage_problem = None, "no_rollout"        # review_validate.RolloutResult: None is "not had", never 0
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
            blobs: dict[str, bytes] = {}
            for fname, limit in ((EVENTS_NAME, EVENTS_LIMIT), (STDERR_NAME, STDERR_LIMIT)):
                try:
                    blobs[fname] = _read_once(job_fd, fname, limit)
                except (strictjson.ReadRefused, OSError) as exc:
                    reasons.append(f"{fname} 無法讀取（{type(exc).__name__}），不能判定或保存到審查紀錄")
                    saved_all = False
            if EVENTS_NAME in blobs:
                tracker, events, ev_reasons = judge_events(blobs[EVENTS_NAME], c)
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
                    usage, usage_problem = v.usage, v.usage_problem
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
                reasons.append("審查暫存區的 repo 不是 detached 在被審 commit" + _scratch_names(m["scratch"]["path"]))
            # save the record; result.json last
            if record_fd is not None:
                files = []
                if events is not None and review_validate._text(events.last_message, review_validate.REPORT_MAX):
                    files.append(("last.md", events.last_message.encode("utf-8")))
                for name in (EVENTS_NAME, STDERR_NAME):
                    if name in blobs:
                        files.append((name, blobs[name]))
                for name, data in files:
                    saved = _write_new(record_fd, name, data, record_path)
                    if not saved.ok:
                        saved_all = False
                        reasons.append(saved.reason)
                        if saved.leftover:
                            leftover, leftover_bytes = leftover or saved.leftover, leftover_bytes + saved.leftover_bytes
    except OSError as exc:
        reasons.append(f"審查工作資料夾無法開啟（{exc.strerror or type(exc).__name__}）")
        saved_all = False
    except BaseException:
        if record_fd is not None:
            os.close(record_fd)
        raise
    if run.get("never_started"):
        # Recovery of a job that never got a process: there is nothing to
        # read, so the missing files and rollout are not reasons of their own
        note = run["never_started"] if isinstance(run["never_started"], str) else "daemon 重啟時審查尚未啟動，沒有程序也沒有輸出"
        reasons = before_files + ([held_reason] if held_reason else []) + [note]
        saved_all = record_fd is not None
    reasons = _short(reasons)
    valid = not reasons and not leftover
    result = {"v": 1, "job_id": job_id, "round": m["round"], "commit": m["commit"], "valid": valid,
              "verdict": verdict, "base_is_ancestor": ancestor, "reasons": reasons, "thread_id": thread,
              "exit_code": run.get("exit_code"), "exit_signal": run.get("exit_signal"),
              "terminated_for": run.get("terminated_for"), "rollout": rollout_info,
              "usage": usage, "usage_problem": usage_problem,
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
            if saved.leftover:
                return out                         # retain the job for a person
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


# ---- a job that was decided before (a restart in the middle of finishing) -----------------------------------

def _resume_cleanup(base, m: dict, fin: Finish) -> None:
    """The record is whole: remove what the manifest recorded, then say so."""
    if m["state"] == "cleaned":
        fin.cleaned = True
        return
    problem = cleanup_job(base, m)
    if problem:
        fin.problem = "；".join(x for x in (fin.problem, problem) if x)
        review_store.retain(base, m["job_id"], fin.problem)
        return
    try:
        review_store.update_manifest(base, m["job_id"], state="cleaned")
        fin.cleaned = True
    except (OSError, review_store.ReviewRefused) as exc:
        fin.problem = f"manifest 無法改成 cleaned（{type(exc).__name__}）"


def _rebuild_result(base, m: dict, now: float):
    """result.json from the outcome in the manifest and the copies already in
    the record (never from the files Codex left, which may be gone). (result
    dict or None, problem or None, leftover). A copy that cannot be read, or
    one that contradicts the outcome, is a problem: nothing is guessed."""
    valid = m["outcome"] == "valid"
    with pipeline_store.Pipeline(base, m["task_id"], create=False) as p:
        rfd = p.review_dir_fd(m["round"])
    try:
        copies: dict[str, bytes | None] = {}
        for name, limit in (("last.md", review_validate.REPORT_MAX), (EVENTS_NAME, EVENTS_LIMIT),
                            (STDERR_NAME, STDERR_LIMIT)):
            try:
                copies[name] = _read_once(rfd, name, limit)
            except (strictjson.ReadRefused, OSError) as exc:
                copies[name] = None
                if valid or not (isinstance(exc, strictjson.ReadRefused) and exc.missing):
                    return None, f"審查紀錄裡已保存的 {name} 讀不到或損壞（{type(exc).__name__}）", None
        rollout = None
        try:
            fd, st = strictjson.open_owned("rollout.jsonl", dir_fd=rfd, max_bytes=review_validate.ROLLOUT_MAX)
            os.close(fd)
            rollout = {"copied": True, "size": st.st_size}
        except (strictjson.ReadRefused, OSError) as exc:
            if valid or not (isinstance(exc, strictjson.ReadRefused) and exc.missing):
                return None, f"審查紀錄裡已保存的 rollout.jsonl 讀不到或損壞（{type(exc).__name__}）", None
        verdict = ancestor = None
        if copies["last.md"] is not None:
            try:
                text = copies["last.md"].decode("utf-8")
            except UnicodeDecodeError:
                return None, "審查紀錄裡已保存的 last.md 不是合法的 UTF-8", None
            rep = review_validate.check_report(text, m["commit"])
            verdict, ancestor = rep.verdict, rep.base_is_ancestor
            if valid and rep.problems:
                return None, "已保存的 last.md 與 valid 的結果不符：" + "；".join(rep.problems[:2]), None
        reasons = [] if valid else list(m.get("invalid_reasons") or [])
        result = {"v": 1, "job_id": m["job_id"], "round": m["round"], "commit": m["commit"], "valid": valid,
                  "verdict": verdict, "base_is_ancestor": ancestor, "reasons": reasons, "thread_id": m["thread_id"],
                  "exit_code": m["exit_code"], "exit_signal": None, "terminated_for": None, "rollout": rollout,
                  "usage": None, "usage_problem": "rebuilt",
                  "finished_at": m.get("ended_at", now), "rebuilt": True}
        record_path = f"pipelines/{m['task_id']}/reviews/{m['round']}"
        saved = _write_new(rfd, "result.json", json.dumps(result, ensure_ascii=False, sort_keys=True).encode(),
                           record_path)
        if not saved.ok:
            return None, saved.reason, saved
        return result, None, None
    finally:
        os.close(rfd)


def _resume_decided(base, m: dict, now: float) -> Finish:
    """finish_review for a job whose outcome is already in the manifest. The
    decision, the saved files and the outcome are never touched again:
      * manual_review: nothing to do (a person looks);
      * the record is whole (result.json agrees): only the clean-up is
        finished, when it was not;
      * the record is not whole (no result.json): the saved copies are read
        back and result.json is written from them and the outcome; when that
        cannot be done the outcome stays as it is and the reason is kept."""
    job_id, outcome = m["job_id"], m["outcome"]
    fin = Finish(outcome, list(m.get("invalid_reasons") or []))
    if outcome == "manual_review":
        fin.reasons = [str(m.get("retained_reason") or "")[:MAX_REASON]]
        return fin
    try:
        with pipeline_store.Pipeline(base, m["task_id"], create=False) as p:
            res = p.review_result(m["round"])
    except (OSError, pipeline_store.StoreRefused) as exc:
        fin.problem = f"審查紀錄的 result.json 無法讀取（{type(exc).__name__}）"
        review_store.retain(base, job_id, fin.problem)
        return fin
    if res is not None:
        try:
            stream_flow.record_state(m, res)
        except stream_flow.FlowRefused as exc:
            fin.problem = f"審查紀錄的 result.json 與 manifest 不一致（{exc}）"
            review_store.retain(base, job_id, fin.problem)
            return fin
        fin.record_complete = True
        fin.result = res
        _resume_cleanup(base, m, fin)
        return fin
    try:
        result, problem, saved = _rebuild_result(base, m, now)
    except (OSError, pipeline_store.StoreRefused) as exc:
        result, problem, saved = None, f"審查紀錄無法開啟（{type(exc).__name__}）", None
    if result is None:
        fin.problem = f"審查紀錄不完整，且無法補寫 result.json：{problem}"
        if saved is not None and saved.leftover:
            fin.leftover, fin.leftover_bytes = saved.leftover, saved.leftover_bytes
        review_store.retain(base, job_id, fin.problem)
        return fin
    fin.record_complete, fin.result = True, result
    _resume_cleanup(base, m, fin)
    return fin
