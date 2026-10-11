"""What a flow owns on disk, and removing it (design 9, S2c-5).

A flow's data lives in three places the daemon alone writes:

  <state>/sessions/<launch-id>/      its stream sessions (manifest, journal, settings)
  <state>/reviews/<job-id>/          its review jobs (manifest and the kept outputs)
  <state>/pipelines/<task-id>/       dispatch texts, start/release records and the
                                     flow's copies of its reviews
  <state>/holds/<flow-id>            the stop marker

"Data is kept until the user deletes the flow. Only when no process is running
and nothing is in manual_review; the path and identity are checked before
anything is removed." This module is that rule in one place: ``plan()`` reads
(it is what the console shows and what the daemon re-reads), ``blockers()``
says why a flow cannot go now, ``remove()`` does it.

Everything is attributed through the same strict readers the quota ledger and
the flow's accounting use (stream_flow.flow_sessions / flow_reviews): one
manifest that cannot be read or does not fit its schema, or an entry that is
not shaped like a session or job, refuses the whole plan, because it could be
this flow's data. Nothing is guessed.

Removal never follows a link and never lets a half-removed record look like a
whole one: inside each directory the manifest (the identity record) goes last,
in the pipeline directory the start record goes last, and the directory itself
only after it is empty. A deletion that stops half way is finished by running
it again (it is idempotent); the daemon's ledger is rebuilt from a scan after.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from . import agent_sessions, pipeline_store, review_store

SESSIONS = "sessions"
REVIEWS = "reviews"
PIPELINES = "pipelines"
HOLDS = "holds"
WALK_MAX_ENTRIES = 200_000        # one flow: far above the design's worst case (about 730 MiB of a few hundred files)
WALK_MAX_DEPTH = 8
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class FlowDataRefused(Exception):
    """The plan or the removal cannot be done safely; the message says why
    (user-facing). Nothing was removed unless ``partial`` is True."""

    def __init__(self, message: str, *, partial: bool = False):
        super().__init__(message)
        self.partial = partial


@dataclass
class Plan:
    pipeline_id: str
    task_id: str
    sessions: list[dict] = field(default_factory=list)      # {launch_id, state, bytes}
    reviews: list[dict] = field(default_factory=list)       # {job_id, state, outcome, bytes}
    pipeline_dir: str | None = None                         # the task directory when it is this flow's
    pipeline_bytes: int = 0
    pipeline_note: str = ""                                 # why the task directory is left alone
    held: bool = False
    total_bytes: int = 0


# ---- measuring -----------------------------------------------------------------------------------------

def _walk_bytes(fd: int, budget: list[int], depth: int = 0) -> int:
    """Bytes of the regular files under the directory ``fd``. A link, a special
    file, too deep or too many entries refuses; nothing is skipped quietly."""
    if depth > WALK_MAX_DEPTH:
        raise FlowDataRefused("資料夾層數過深，無法核對")
    total = 0
    with os.scandir(fd) as entries:
        for entry in entries:
            budget[0] -= 1
            if budget[0] < 0:
                raise FlowDataRefused("項目過多，無法核對")
            st = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
            elif stat.S_ISDIR(st.st_mode):
                sub = os.open(entry.name, _DIR, dir_fd=fd)
                try:
                    total += _walk_bytes(sub, budget, depth + 1)
                finally:
                    os.close(sub)
            else:
                raise FlowDataRefused(f"不是一般檔案或資料夾：{entry.name[:64]!r}")
    return total


def dir_bytes(parent_fd: int, name: str) -> int:
    """Bytes under ``parent_fd``/``name``; FlowDataRefused when it cannot be
    measured as a plain tree of ours."""
    try:
        fd = os.open(name, _DIR, dir_fd=parent_fd)
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 無法開啟（{exc.strerror}）") from exc
    try:
        return _walk_bytes(fd, [WALK_MAX_ENTRIES])
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 無法核對（{exc.strerror}）") from exc
    finally:
        os.close(fd)


def _root_fd(state: int, name: str) -> int | None:
    try:
        return os.open(name, _DIR, dir_fd=state)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FlowDataRefused(f"{name}/ 無法開啟（{exc.strerror}）") from exc


# ---- the plan --------------------------------------------------------------------------------------------

def plan(base, pipeline_id: str, task_id: str) -> Plan:
    """What the flow owns. Read-only."""
    if not (isinstance(pipeline_id, str) and pipeline_store.FLOW_RE.match(pipeline_id)):
        raise FlowDataRefused("流程 id 格式不符")
    if not (isinstance(task_id, str) and pipeline_store.TASK_RE.match(task_id)) or task_id in (".", ".."):
        raise FlowDataRefused("任務 id 格式不符")
    out = Plan(pipeline_id, task_id)
    try:
        state = os.open(str(base), _DIR)
    except OSError as exc:
        raise FlowDataRefused(f"狀態目錄無法開啟（{exc.strerror}）") from exc
    try:
        # pipelines/<task>: this flow's only when its start record says so
        try:
            with pipeline_store.Pipeline(base, task_id, create=False) as p:
                rec = p.start_record()
                links = p.review_links()
            foreign = rec is not None and rec["pipeline_id"] != pipeline_id
            owned_links = all(v["pipeline_id"] == pipeline_id for v in links.values())
            if foreign or not owned_links:
                out.pipeline_note = "這個任務的資料夾屬於另一個流程，不會動它"
            else:
                out.pipeline_dir = task_id
        except pipeline_store.StoreRefused as exc:
            if not exc.missing:
                raise FlowDataRefused(f"流程資料夾無法核對（{exc}）") from exc
        except OSError as exc:
            raise FlowDataRefused(f"流程資料夾無法核對（{exc.strerror}）") from exc
        manifests = _flow_sessions(base, pipeline_id)
        jobs = _flow_reviews(base, pipeline_id)
        sroot = _root_fd(state, SESSIONS)
        rroot = _root_fd(state, REVIEWS)
        proot = _root_fd(state, PIPELINES)
        try:
            for m in manifests:
                size = dir_bytes(sroot, m["launch_id"]) if sroot is not None else 0
                out.sessions.append({"launch_id": m["launch_id"], "state": m["state"], "bytes": size})
            for m in jobs:
                size = dir_bytes(rroot, m["job_id"]) if rroot is not None else 0
                out.reviews.append({"job_id": m["job_id"], "state": m["state"], "outcome": m["outcome"],
                                    "bytes": size})
            if out.pipeline_dir and proot is not None:
                out.pipeline_bytes = dir_bytes(proot, out.pipeline_dir)
        finally:
            for fd in (sroot, rroot, proot):
                if fd is not None:
                    os.close(fd)
        out.held = pipeline_store.is_held(base, pipeline_id)
    finally:
        os.close(state)
    out.total_bytes = (sum(s["bytes"] for s in out.sessions) + sum(r["bytes"] for r in out.reviews)
                       + out.pipeline_bytes)
    return out


def _flow_sessions(base, pipeline_id: str) -> list[dict]:
    """The flow's stream sessions from their manifests alone (not the journals:
    a deletion that stopped half way may have taken a journal already, and
    finishing it must still be possible). An entry that is not shaped like a
    launch, or a manifest that cannot be read, refuses: it could be this
    flow's."""
    root = agent_sessions.sessions_root(Path(os.fspath(base)))
    try:
        names = sorted(os.listdir(root))
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise FlowDataRefused(f"sessions/ 無法列出（{exc.strerror}）") from exc
    out = []
    for name in names:
        if not agent_sessions.LAUNCH_RE.match(name):
            raise FlowDataRefused(f"sessions/ 裡有不認得的項目 {name[:64]!r}，無法判斷哪些資料屬於這個流程")
        try:
            m = agent_sessions._read_manifest(root / name, os.getuid())
        except (OSError, agent_sessions.LaunchRefused) as exc:
            raise FlowDataRefused(f"session {name} 的 manifest 無法讀取（{exc}），無法判斷哪些資料屬於這個流程") from exc
        if m.get("engine") == "claude-stream" and m.get("pipeline_id") == pipeline_id:
            if m.get("launch_id") != name:
                raise FlowDataRefused(f"session {name} 的資料夾與 manifest 不符（改名或複製過）")
            out.append(m)
    return out


def _flow_reviews(base, pipeline_id: str) -> list[dict]:
    try:
        names = review_store.list_jobs(base)
    except (review_store.ReviewRefused, OSError) as exc:
        raise FlowDataRefused(f"reviews/ 無法核對（{exc}）") from exc
    out = []
    for name in names:
        if not review_store.JOB_RE.match(name):
            raise FlowDataRefused(f"reviews/ 裡有不認得的項目 {name[:64]!r}，無法判斷哪些資料屬於這個流程")
        try:
            m = review_store.read_manifest(base, name)
        except (review_store.ReviewRefused, OSError) as exc:
            raise FlowDataRefused(f"審查 {name} 的 manifest 無法讀取（{exc}），無法判斷哪些資料屬於這個流程") from exc
        if m["pipeline_id"] == pipeline_id:
            out.append(m)
    return out


def blockers(pl: Plan, *, live_launches=(), live_jobs=()) -> list[str]:
    """Why this flow cannot be deleted now; empty when it can."""
    why: list[str] = []
    for s in pl.sessions:
        if s["launch_id"] in live_launches or s["state"] in ("launching", "running"):
            why.append(f"串流 session {s['launch_id']} 仍在執行")
        elif s["state"] == "manual_review":
            why.append(f"串流 session {s['launch_id']} 需要人工處理（manual_review）")
        elif s["state"] not in ("ended", "prepared"):
            why.append(f"串流 session {s['launch_id']} 的狀態不明（{s['state']}）")
    for r in pl.reviews:
        if r["job_id"] in live_jobs or r["state"] in ("prepared", "launching", "running"):
            why.append(f"審查 {r['job_id']} 仍在進行")
        elif r["state"] == "manual_review" or r["outcome"] == "manual_review":
            why.append(f"審查 {r['job_id']} 需要人工處理（manual_review）")
        elif r["state"] != "cleaned":
            why.append(f"審查 {r['job_id']} 尚未清理完成（{r['state']}）")
    return why


# ---- removing ------------------------------------------------------------------------------------------

def _empty(fd: int, *, keep: str | None, last: tuple[str, ...] = (), depth: int = 0,
           budget: list[int] | None = None) -> None:
    """Remove everything under the directory ``fd`` except the name ``keep``;
    names in ``last`` go after everything else. Links are removed as links,
    never followed; a special file refuses."""
    budget = budget if budget is not None else [WALK_MAX_ENTRIES]
    if depth > WALK_MAX_DEPTH:
        raise FlowDataRefused("資料夾層數過深，無法刪除")
    names = os.listdir(fd)
    budget[0] -= len(names)
    if budget[0] < 0:
        raise FlowDataRefused("項目過多，無法刪除")
    ordered = ([n for n in names if n != keep and n not in last]
               + [n for n in last if n in names and n != keep])
    for name in ordered:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            sub = os.open(name, _DIR, dir_fd=fd)
            try:
                _empty(sub, keep=None, depth=depth + 1, budget=budget)
            finally:
                os.close(sub)
            os.rmdir(name, dir_fd=fd)
        elif stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
            os.unlink(name, dir_fd=fd)
        else:
            raise FlowDataRefused(f"不是一般檔案或資料夾，不刪除：{name[:64]!r}")


def _remove_dir(parent_fd: int, name: str, *, identity: dict | None = None, manifest: str | None = None,
                last: tuple[str, ...] = ()) -> bool:
    """Remove the directory ``name`` under ``parent_fd``: opened without
    following a link, ours, private, and (when given) the very inode the
    manifest recorded. ``manifest`` (and ``last``) are removed after
    everything else. True when something was removed; False when it was
    already gone."""
    try:
        fd = os.open(name, _DIR, dir_fd=parent_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 不是一般資料夾（{exc.strerror}），不刪除") from exc
    try:
        st = os.fstat(fd)
        if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise FlowDataRefused(f"{name[:64]} 不是本人的私有資料夾，不刪除")
        if identity is not None and (identity.get("inode") != st.st_ino or identity.get("uid") != st.st_uid):
            raise FlowDataRefused(f"{name[:64]} 的資料夾身分與 manifest 不符，不刪除")
        try:
            _empty(fd, keep=manifest, last=last)
            if manifest is not None:
                try:
                    os.unlink(manifest, dir_fd=fd)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise FlowDataRefused(f"{name[:64]} 刪除到一半失敗（{exc.strerror}）", partial=True) from exc
    finally:
        os.close(fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 刪除後仍存在（{exc.strerror}）", partial=True) from exc
    return True


def remove(base, pl: Plan) -> dict:
    """Delete what ``pl`` lists. The caller has checked blockers() and that
    no process of the flow is alive. Raises FlowDataRefused (``partial`` when
    something was already removed; run again to finish)."""
    removed = {"sessions": [], "reviews": [], "pipeline": False, "hold": False}
    try:
        return _remove(base, pl, removed)
    except FlowDataRefused as exc:
        if removed["sessions"] or removed["reviews"] or removed["pipeline"] or removed["hold"]:
            exc.partial = True
        raise


def _remove(base, pl: Plan, removed: dict) -> dict:
    uid = os.getuid()
    try:
        state = os.open(str(base), _DIR)
    except OSError as exc:
        raise FlowDataRefused(f"狀態目錄無法開啟（{exc.strerror}）") from exc
    try:
        # a launch that was prepared and never run still has its scratch: the
        # launch's own discard removes both, exactly what the manifest records
        for s in pl.sessions:
            if s["state"] == "prepared":
                res = agent_sessions.discard_prepared(Path(os.fspath(base)), s["launch_id"])
                if not res.get("cleaned"):
                    raise FlowDataRefused(f"未啟動的 session {s['launch_id']} 無法移除（{res.get('retained_reason', '')}）",
                                          partial=bool(removed["sessions"]))
                removed["sessions"].append(s["launch_id"])
        sroot = _root_fd(state, SESSIONS)
        rroot = _root_fd(state, REVIEWS)
        proot = _root_fd(state, PIPELINES)
        try:
            for s in pl.sessions:
                if s["state"] == "prepared" or sroot is None:
                    continue
                ldir = agent_sessions.launch_dir(Path(os.fspath(base)), s["launch_id"])
                try:
                    m = agent_sessions._read_manifest(ldir, uid)
                except FileNotFoundError:
                    m = None                                      # the manifest goes last: a finished removal
                except (OSError, agent_sessions.LaunchRefused) as exc:
                    raise FlowDataRefused(f"session {s['launch_id']} 的 manifest 無法讀取（{exc}）",
                                          partial=bool(removed["sessions"])) from exc
                ident = None
                if m is not None:
                    if m.get("pipeline_id") != pl.pipeline_id or m.get("launch_id") != s["launch_id"]:
                        raise FlowDataRefused(f"session {s['launch_id']} 不屬於這個流程，不刪除")
                    scratch = Path(m["scratch"]["path"])
                    if os.path.lexists(scratch):
                        raise FlowDataRefused(f"session {s['launch_id']} 的暫存區還在，不刪除")
                    rec = m.get("launch_dir")
                    ident = {"inode": rec.get("inode"), "uid": rec.get("uid")} if isinstance(rec, dict) else None
                    if ident is None:
                        raise FlowDataRefused(f"session {s['launch_id']} 的 manifest 沒有資料夾身分，不刪除")
                if _remove_dir(sroot, s["launch_id"], identity=ident, manifest=agent_sessions.MANIFEST):
                    removed["sessions"].append(s["launch_id"])
            for r in pl.reviews:
                if rroot is None:
                    break
                try:
                    m = review_store.read_manifest(base, r["job_id"])
                except review_store.ReviewRefused as exc:
                    if os.path.lexists(review_store.job_dir(base, r["job_id"])):
                        raise FlowDataRefused(f"審查 {r['job_id']} 的 manifest 無法讀取（{exc}）",
                                              partial=bool(removed["sessions"] or removed["reviews"])) from exc
                    continue
                if m["pipeline_id"] != pl.pipeline_id or m["job_id"] != r["job_id"]:
                    raise FlowDataRefused(f"審查 {r['job_id']} 不屬於這個流程，不刪除")
                if m["state"] != "cleaned":
                    raise FlowDataRefused(f"審查 {r['job_id']} 尚未清理完成，不刪除")
                if _remove_dir(rroot, r["job_id"], manifest=review_store.MANIFEST):
                    removed["reviews"].append(r["job_id"])
            if pl.pipeline_dir and proot is not None:
                if _remove_dir(proot, pl.pipeline_dir, last=(pipeline_store.STARTED,)):
                    removed["pipeline"] = True
        finally:
            for fd in (sroot, rroot, proot):
                if fd is not None:
                    os.close(fd)
        try:
            removed["hold"] = _remove_hold(state, pl.pipeline_id)
        except OSError as exc:
            raise FlowDataRefused(f"停止紀錄無法移除（{exc.strerror}）", partial=True) from exc
    finally:
        os.close(state)
    return removed


def _remove_hold(state: int, pipeline_id: str) -> bool:
    holds = _root_fd(state, HOLDS)
    if holds is None:
        return False
    try:
        try:
            st = os.stat(pipeline_id, dir_fd=holds, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
            raise FlowDataRefused("停止紀錄不是一般檔案，不刪除")
        os.unlink(pipeline_id, dir_fd=holds)
        return True
    finally:
        os.close(holds)
