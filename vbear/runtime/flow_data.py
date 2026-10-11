"""What a flow owns on disk, and removing it (design 9, S2c-5).

A flow's data lives in three places the daemon alone writes:

  <state>/sessions/<launch-id>/      its stream sessions (manifest, journal, settings)
  <state>/reviews/<job-id>/          its review jobs (manifest and the kept outputs)
  <state>/pipelines/<task-id>/       dispatch texts, start/release records and the
                                     flow's copies of its reviews (one task, one flow)
  <state>/holds/<flow-id>            the stop marker

"Data is kept until the user deletes the flow, only when no process is running,
nothing is in manual_review and no failure or stop is outstanding; path and
identity are checked before anything is removed."

How a deletion is made safe (the reasoning is also in the commit that
introduced it):

1. **Nothing is guessed.** An item is the flow's only when it is proven:
   a session directory by its manifest (flow id, launch id) *and* the
   directory inode the manifest recorded; a review job by its manifest *and*
   the flow-side record ``pipelines/<task>/reviews/<round>/job.json`` naming
   the same job, commit and flow; the task directory by its start record
   naming the flow (or, for a flow that never started, by holding nothing but
   empty scaffolding and a release record naming it). Anything else refuses
   the whole deletion and says why: a person looks.
2. **Move, then purge.** The proven directories are first *moved* (atomic
   ``rename``, same file system) into ``<state>/deleting/<flow-id>/``, which
   no flow's accounting reads (the quota scan does count it: the bytes are
   on the disk until purged) and is where nothing else looks. From then on
   nothing but the flow's own deletion can see them; no accounting of
   another flow (``flow_sessions``/``flow_reviews`` refuse unknown entries)
   ever meets a half-removed directory. The tomb is then emptied by a
   recursive walk that needs no manifest, so it can be resumed from any
   point. While ``deleting/<flow-id>`` exists the flow counts as stopped
   (``pipeline_store.is_held``): nothing new can be started in it.
3. **Every level is pinned.** Each directory is opened with
   ``O_NOFOLLOW|O_DIRECTORY`` and ``fstat``-checked: owner, the same device as
   the state directory (a mount point is refused before it is entered), and
   the inode seen by the ``lstat`` just before; before ``rmdir`` the name is
   looked at again and must still be that inode (``rmdir`` only removes an
   empty directory anyway).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from . import agent_sessions, pipeline_store, review_store, stream_flow

SESSIONS = "sessions"
REVIEWS = "reviews"
PIPELINES = "pipelines"
HOLDS = "holds"
AUTOMATION = "automation"         # <state>/automation/<flow-id>/plan.txt (S3 v11.1 G2), written by the console
DELETING = pipeline_store.DELETING
WALK_MAX_ENTRIES = 200_000        # one flow: far above the design's worst case (about 730 MiB of a few hundred files)
WALK_MAX_DEPTH = 12
SCAFFOLD_NAMES = ("dispatches", "reviews")
AUTOMATION_FILES = ("plan.txt", ".lock", ".plan.txt.tmp")     # what the console keeps in automation/<flow>/
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class FlowDataRefused(Exception):
    """The plan or the removal cannot be done safely; the message says why
    (user-facing). ``partial`` is True when something was already moved or
    removed (asking again continues)."""

    def __init__(self, message: str, *, partial: bool = False):
        super().__init__(message)
        self.partial = partial


@dataclass
class Plan:
    pipeline_id: str
    task_id: str
    sessions: list[dict] = field(default_factory=list)      # {launch_id, state, bytes, inode}
    reviews: list[dict] = field(default_factory=list)       # {job_id, state, outcome, bytes, inode}
    pipeline_dir: str | None = None                         # the task directory when it is proven this flow's
    pipeline_bytes: int = 0
    pipeline_inode: int | None = None
    automation_inode: int | None = None                     # automation/<flow>/ (plan.txt), when there is one
    automation_bytes: int = 0
    auto: bool = False                                      # the flow is in automatic mode (S3)
    held: bool = False                                      # a stop marker exists (any reason, or unknown)
    deleting: bool = False                                  # a deletion of this flow was begun and not finished
    tomb_bytes: int = 0
    unresolved: list[str] = field(default_factory=list)     # failures the user has not released (not when deleting)
    failure_problem: str = ""                               # why failures could not be told (not when deleting)
    total_bytes: int = 0


# ---- opening and measuring: every level pinned ------------------------------------------------------------

class _Missing(FlowDataRefused):
    """The directory is not there (not an error for a retry)."""


def _open_pinned(parent_fd: int, name: str, root_dev: int, *, inode: int | None = None, private: bool = False) -> int:
    """The directory ``name`` under ``parent_fd``, opened without following a
    link, and checked: ours, on the root's device, the inode expected, and
    (``private``) with no group/other permission bits."""
    try:
        fd = os.open(name, _DIR, dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise _Missing(f"{name[:64]} 不存在") from exc
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 不是一般資料夾（{exc.strerror}），不處理") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
            raise FlowDataRefused(f"{name[:64]} 不是本人的資料夾，不處理")
        if st.st_dev != root_dev:
            raise FlowDataRefused(f"{name[:64]} 在另一個檔案系統（掛載點），不處理")
        if inode is not None and st.st_ino != inode:
            raise FlowDataRefused(f"{name[:64]} 在檢查之後被替換了，不處理")
        if private and stat.S_IMODE(st.st_mode) & 0o077:
            raise FlowDataRefused(f"{name[:64]} 不是私有（0700）資料夾，不處理")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _walk_bytes(fd: int, root_dev: int, budget: list[int], depth: int = 0) -> int:
    """Bytes of the regular files under the directory ``fd``. A link, a special
    file, a mount point, too deep or too many entries refuses."""
    if depth > WALK_MAX_DEPTH:
        raise FlowDataRefused("資料夾層數過深，無法核對")
    total = 0
    for name in os.listdir(fd):
        budget[0] -= 1
        if budget[0] < 0:
            raise FlowDataRefused("項目過多，無法核對")
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISREG(st.st_mode):
            total += st.st_size
        elif stat.S_ISDIR(st.st_mode):
            sub = _open_pinned(fd, name, root_dev, inode=st.st_ino)
            try:
                total += _walk_bytes(sub, root_dev, budget, depth + 1)
            finally:
                os.close(sub)
        else:
            raise FlowDataRefused(f"不是一般檔案或資料夾：{name[:64]!r}")
    return total


def dir_bytes(parent_fd: int, name: str, root_dev: int) -> int:
    """Bytes under ``parent_fd``/``name``; FlowDataRefused when it cannot be
    measured as a plain tree of ours on one device."""
    fd = _open_pinned(parent_fd, name, root_dev)
    try:
        return _walk_bytes(fd, root_dev, [WALK_MAX_ENTRIES])
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 無法核對（{exc.strerror}）") from exc
    finally:
        os.close(fd)


def _root_fd(state: int, name: str, root_dev: int) -> int | None:
    try:
        return _open_pinned(state, name, root_dev)
    except _Missing:
        return None


# ---- the plan --------------------------------------------------------------------------------------------

def plan(base, pipeline_id: str, task_id: str, *, flows=None) -> Plan:
    """What the flow owns, proven. Read-only. ``flows`` (the flows.json
    snapshot) lets it refuse a task that more than one flow names."""
    if not (isinstance(pipeline_id, str) and pipeline_store.FLOW_RE.match(pipeline_id)):
        raise FlowDataRefused("流程 id 格式不符")
    if not (isinstance(task_id, str) and pipeline_store.TASK_RE.match(task_id)) or task_id in (".", ".."):
        raise FlowDataRefused("任務 id 格式不符")
    if flows is not None:
        sharing = sorted(f["id"] for f in flows.values()
                         if isinstance(f, dict) and f.get("task_id") == task_id and f.get("id") != pipeline_id)
        if sharing:
            raise FlowDataRefused(f"另一個流程（{sharing[0]}）也使用這個任務的資料夾，無法判斷哪些資料屬於這個流程")
    out = Plan(pipeline_id, task_id)
    try:
        state = os.open(str(base), _DIR)
    except OSError as exc:
        raise FlowDataRefused(f"狀態目錄無法開啟（{exc.strerror}）") from exc
    try:
        root_dev = os.fstat(state).st_dev
        out.deleting = pipeline_store.deleting_exists(base, pipeline_id)
        links = _pipeline_side(base, pipeline_id, task_id, out)
        manifests = _flow_sessions(base, pipeline_id)
        jobs = _flow_reviews(base, pipeline_id, links)
        sroot = _root_fd(state, SESSIONS, root_dev)
        rroot = _root_fd(state, REVIEWS, root_dev)
        proot = _root_fd(state, PIPELINES, root_dev)
        try:
            for m in manifests:
                if sroot is None:
                    raise FlowDataRefused(f"session {m['launch_id']} 的資料夾不見了")
                ino = _proven_inode(sroot, m["launch_id"], root_dev, m)
                out.sessions.append({"launch_id": m["launch_id"], "state": m["state"], "inode": ino,
                                     "bytes": dir_bytes(sroot, m["launch_id"], root_dev)})
            for m in jobs:
                if rroot is None:
                    raise FlowDataRefused(f"審查 {m['job_id']} 的資料夾不見了")
                fd = _open_pinned(rroot, m["job_id"], root_dev, private=True)
                try:
                    ino = os.fstat(fd).st_ino
                finally:
                    os.close(fd)
                out.reviews.append({"job_id": m["job_id"], "state": m["state"], "outcome": m["outcome"],
                                    "inode": ino, "bytes": dir_bytes(rroot, m["job_id"], root_dev)})
            if out.pipeline_dir and proot is not None:
                fd = _open_pinned(proot, out.pipeline_dir, root_dev, private=True)
                try:
                    out.pipeline_inode = os.fstat(fd).st_ino
                finally:
                    os.close(fd)
                out.pipeline_bytes = dir_bytes(proot, out.pipeline_dir, root_dev)
        finally:
            for fd in (sroot, rroot, proot):
                if fd is not None:
                    os.close(fd)
        _automation_side(state, pipeline_id, root_dev, out)
        out.auto = pipeline_store.mode_info(base, pipeline_id)["mode"] == "auto"
        if out.deleting:
            droot = _root_fd(state, DELETING, root_dev)
            if droot is not None:
                try:
                    out.tomb_bytes = dir_bytes(droot, pipeline_id, root_dev)
                except _Missing:
                    pass
                finally:
                    os.close(droot)
        out.held = pipeline_store.hold_marker_exists(base, pipeline_id)
        if not out.deleting:
            _failures(base, pipeline_id, task_id, out)
    finally:
        os.close(state)
    out.total_bytes = (sum(s["bytes"] for s in out.sessions) + sum(r["bytes"] for r in out.reviews)
                       + out.pipeline_bytes + out.automation_bytes + out.tomb_bytes)
    return out


def _automation_side(state: int, pipeline_id: str, root_dev: int, out: Plan) -> None:
    """automation/<flow>/ holds the approved plan text (plan.txt) and nothing
    else; it is named by the flow id the console wrote it for. Anything else
    in it refuses: it is not something this module wrote."""
    aroot = _root_fd(state, AUTOMATION, root_dev)
    if aroot is None:
        return
    try:
        try:
            fd = _open_pinned(aroot, pipeline_id, root_dev, private=True)
        except _Missing:
            return
        try:
            st = os.fstat(fd)
            names = os.listdir(fd)
            total = 0
            for name in names:
                if name not in AUTOMATION_FILES:
                    raise FlowDataRefused(f"automation/{pipeline_id} 裡有不認得的項目 {name[:48]!r}，不處理")
                fst = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(fst.st_mode):
                    raise FlowDataRefused(f"{name} 不是一般檔案，不處理")
                total += fst.st_size
            out.automation_inode, out.automation_bytes = st.st_ino, total
        finally:
            os.close(fd)
    finally:
        os.close(aroot)


def _proven_inode(sroot: int, name: str, root_dev: int, m: dict) -> int:
    """The session directory's inode, which must be the one its manifest
    recorded (the manifest says which directory it is the record of)."""
    rec = m.get("launch_dir")
    if not (isinstance(rec, dict) and isinstance(rec.get("inode"), int) and not isinstance(rec.get("inode"), bool)):
        raise FlowDataRefused(f"session {name} 的 manifest 沒有資料夾身分，無法證明它屬於這個流程")
    fd = _open_pinned(sroot, name, root_dev, inode=rec["inode"], private=True)
    try:
        st = os.fstat(fd)
    finally:
        os.close(fd)
    if rec.get("uid") != st.st_uid:
        raise FlowDataRefused(f"session {name} 的資料夾身分與 manifest 不符")
    return st.st_ino


def _pipeline_side(base, pipeline_id: str, task_id: str, out: Plan) -> dict:
    """Prove (or refuse) that the task directory is this flow's, and return
    the flow-side review links. A flow's directory is proven by its start
    record naming the flow; nothing else is ever deleted on a guess."""
    try:
        with pipeline_store.Pipeline(base, task_id, create=False) as p:
            rec = p.start_record()
            links = p.review_links()
            if rec is not None and rec["pipeline_id"] != pipeline_id:
                raise FlowDataRefused(f"這個任務的資料夾屬於另一個流程（{rec['pipeline_id']}），不處理")
            if any(v["pipeline_id"] != pipeline_id for v in links.values()):
                raise FlowDataRefused("這個任務的審查紀錄屬於另一個流程，不處理")
            if rec is None:
                _scaffold_only(p, pipeline_id)
            out.pipeline_dir = task_id
            return links
    except pipeline_store.StoreRefused as exc:
        if exc.missing:
            return {}
        raise FlowDataRefused(f"這個任務的資料夾無法核對（{exc}），無法證明它屬於這個流程") from exc
    except OSError as exc:
        raise FlowDataRefused(f"這個任務的資料夾無法核對（{exc.strerror}）") from exc


def _scaffold_only(p, pipeline_id: str) -> None:
    """A flow that never started has no start record. Its directory is then
    deleted only when it holds nothing but empty scaffolding and, at most, a
    release record that names this flow; any file or any record that cannot
    be read or names someone else refuses."""
    for name in os.listdir(p.fd):
        if name == pipeline_store.RELEASED:
            try:
                if p.release_record(pipeline_id) is None:
                    raise FlowDataRefused("流程資料夾沒有開始紀錄，無法證明它屬於這個流程")
            except pipeline_store.StoreRefused as exc:
                raise FlowDataRefused(f"流程資料夾沒有開始紀錄，而且繼續紀錄無法證明歸屬（{exc}）") from exc
        elif name in SCAFFOLD_NAMES:
            sub = os.open(name, _DIR, dir_fd=p.fd)
            try:
                if os.listdir(sub):
                    raise FlowDataRefused(f"流程資料夾沒有開始紀錄，但 {name}/ 裡有資料，無法證明它屬於這個流程")
            finally:
                os.close(sub)
        else:
            raise FlowDataRefused(f"流程資料夾沒有開始紀錄，但有不認得的項目 {name[:64]!r}，無法證明它屬於這個流程")


def _flow_sessions(base, pipeline_id: str) -> list[dict]:
    """The flow's stream sessions from their manifests alone (not the journals).
    An entry that is not shaped like a launch, or a manifest that cannot be
    read, refuses: it could be this flow's."""
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


def _flow_reviews(base, pipeline_id: str, links: dict) -> list[dict]:
    """The flow's review jobs: a manifest naming the flow *and* the flow-side
    record of its round naming the same job, commit and flow. One record
    alone is not proof."""
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
        if m["pipeline_id"] != pipeline_id:
            continue
        link = links.get(m["round"])
        if (link is None or link["job_id"] != name or link["commit"] != m["commit"]
                or link["pipeline_id"] != pipeline_id):
            raise FlowDataRefused(f"審查 {name} 與流程的審查紀錄對不上，無法證明它屬於這個流程")
        out.append(m)
    return out


def _failures(base, pipeline_id: str, task_id: str, out: Plan) -> None:
    """The failures of the flow that the user has not released (v29.8), by
    identity, recomputed from the journals and manifests."""
    try:
        current = stream_flow.failure_ids(base, pipeline_id, task_id)
    except stream_flow.FlowRefused as exc:
        out.failure_problem = f"無法確認失敗是否都已處理（{exc}）"
        return
    resolved: set = set()
    if out.pipeline_dir:
        try:
            with pipeline_store.Pipeline(base, task_id, create=False) as p:
                rec = p.release_record(pipeline_id)
            resolved = rec["resolved"] if rec else set()
        except (pipeline_store.StoreRefused, OSError) as exc:
            out.failure_problem = f"無法確認失敗是否都已處理（繼續紀錄無法讀取：{exc}）"
            return
    out.unresolved = [i for i in current if i not in resolved]


def blockers(pl: Plan, *, live_launches=(), live_jobs=(), held_leaders=()) -> list[str]:
    """Why this flow cannot be deleted now; empty when it can."""
    why: list[str] = []
    for s in pl.sessions:
        if s["launch_id"] in live_launches or s["state"] in ("launching", "running"):
            why.append(f"串流 session {s['launch_id']} 仍在執行")
        elif s["launch_id"] in held_leaders:
            why.append(f"串流 session {s['launch_id']} 的程序群組尚未證明已結束（需要人工處理）")
        elif s["state"] == "manual_review":
            why.append(f"串流 session {s['launch_id']} 需要人工處理（manual_review）")
        elif s["state"] not in ("ended", "prepared"):
            why.append(f"串流 session {s['launch_id']} 的狀態不明（{s['state']}）")
    for r in pl.reviews:
        if r["job_id"] in live_jobs or r["state"] in ("prepared", "launching", "running"):
            why.append(f"審查 {r['job_id']} 仍在進行")
        elif r["job_id"] in held_leaders:
            why.append(f"審查 {r['job_id']} 的程序群組尚未證明已結束（需要人工處理）")
        elif r["state"] == "manual_review" or r["outcome"] == "manual_review":
            why.append(f"審查 {r['job_id']} 需要人工處理（manual_review）")
        elif r["state"] != "cleaned":
            why.append(f"審查 {r['job_id']} 尚未清理完成（{r['state']}）")
    if not pl.deleting:                       # a deletion already begun is finished, not re-decided
        if pl.auto:
            why.append("流程在自動執行模式，請先停止流程並切回手動")
        if pl.held:
            why.append("流程已停止（含失敗後的停止），請先按「繼續」，或處理失敗後再刪除")
        if pl.failure_problem:
            why.append(pl.failure_problem)
        if pl.unresolved:
            why.append(f"還有 {len(pl.unresolved)} 個尚未解除的失敗（{pl.unresolved[0]}），請先處理並按「繼續」")
    return why


# ---- removing: move, then purge --------------------------------------------------------------------------

def _mkdir_private(parent_fd: int, name: str, root_dev: int) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise FlowDataRefused(f"{name} 無法建立（{exc.strerror}）") from exc
    return _open_pinned(parent_fd, name, root_dev, private=True)


def _fsync(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        pass


def _move(src_parent: int, name: str, dst_parent: int, dst_name: str, root_dev: int, inode) -> bool:
    """Atomically move the directory ``name`` into the tomb as ``dst_name``.
    True when moved, False when it was not there (already moved). The inode
    seen when planning must still be the directory's, before and after."""
    try:
        os.stat(name, dir_fd=src_parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not isinstance(inode, int) or isinstance(inode, bool):
        raise FlowDataRefused(f"{name[:64]} 沒有計畫時的身分，不處理")
    fd = _open_pinned(src_parent, name, root_dev, inode=inode, private=True)
    os.close(fd)
    try:
        os.stat(dst_name, dir_fd=dst_parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FlowDataRefused(f"{dst_name[:64]} 在刪除區裡已經有同名的項目，不處理")
    try:
        os.rename(name, dst_name, src_dir_fd=src_parent, dst_dir_fd=dst_parent)
    except OSError as exc:
        raise FlowDataRefused(f"{name[:64]} 無法移到刪除區（{exc.strerror}）") from exc
    st = os.stat(dst_name, dir_fd=dst_parent, follow_symlinks=False)
    if st.st_ino != inode or st.st_dev != root_dev:
        try:
            os.rename(dst_name, name, src_dir_fd=dst_parent, dst_dir_fd=src_parent)
        except OSError:
            pass
        raise FlowDataRefused(f"{name[:64]} 在移動時被替換了，不處理")
    return True


def _purge(parent_fd: int, name: str, root_dev: int, budget: list[int], depth: int = 0) -> bool:
    """Remove ``name`` under ``parent_fd`` and everything in it. No manifest is
    read: this works from any point. Every directory is opened pinned; a
    link is removed as a link; a special file or a mount point refuses."""
    if depth > WALK_MAX_DEPTH:
        raise FlowDataRefused("資料夾層數過深，不刪除")
    try:
        st0 = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    budget[0] -= 1
    if budget[0] < 0:
        raise FlowDataRefused("項目過多，不刪除")
    if stat.S_ISREG(st0.st_mode) or stat.S_ISLNK(st0.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return True
    if not stat.S_ISDIR(st0.st_mode):
        raise FlowDataRefused(f"不是一般檔案或資料夾，不刪除：{name[:64]!r}")
    fd = _open_pinned(parent_fd, name, root_dev, inode=st0.st_ino)
    try:
        for child in os.listdir(fd):
            _purge(fd, child, root_dev, budget, depth + 1)
    finally:
        os.close(fd)
    st1 = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if st1.st_ino != st0.st_ino or st1.st_dev != st0.st_dev:
        raise FlowDataRefused(f"{name[:64]} 在清空之後被替換了，不刪除")
    os.rmdir(name, dir_fd=parent_fd)
    return True


def remove(base, pl: Plan) -> dict:
    """Delete what ``pl`` lists: move every proven directory into the flow's
    tomb, then purge the tomb. The caller has checked blockers() and that no
    process of the flow is alive. Raises FlowDataRefused (``partial`` when
    something was already moved or removed; asking again continues)."""
    removed = {"sessions": [], "reviews": [], "pipeline": False, "hold": False, "purged": False}

    def began() -> bool:
        return bool(removed["sessions"] or removed["reviews"] or removed["pipeline"] or removed["purged"]
                    or pl.deleting)
    try:
        return _remove(base, pl, removed)
    except FlowDataRefused as exc:
        exc.partial = exc.partial or began()
        raise
    except OSError as exc:
        raise FlowDataRefused(f"刪除失敗（{exc.strerror or type(exc).__name__}）", partial=began()) from exc


def _approval_lock(state: int, flow_id: str, root_dev: int) -> int | None:
    """The console's approval lock of this flow (automation/<flow>/.lock),
    taken without waiting: a flow whose automatic mode is being turned on is
    not deleted under it. None when there is no such file."""
    import fcntl
    aroot = _root_fd(state, AUTOMATION, root_dev)
    if aroot is None:
        return None
    try:
        try:
            dfd = _open_pinned(aroot, flow_id, root_dev, private=True)
        except _Missing:
            return None
        try:
            try:
                fd = os.open(".lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise FlowDataRefused(f"核准用的鎖檔無法開啟（{exc.strerror}），不刪除") from exc
        finally:
            os.close(dfd)
    finally:
        os.close(aroot)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise FlowDataRefused("正在開啟自動執行（核准進行中），不刪除；請稍後再試") from None
    return fd


def _remove(base, pl: Plan, removed: dict) -> dict:
    try:
        state = os.open(str(base), _DIR)
    except OSError as exc:
        raise FlowDataRefused(f"狀態目錄無法開啟（{exc.strerror}）") from exc
    open_fds = [state]
    try:
        root_dev = os.fstat(state).st_dev
        lock = _approval_lock(state, pl.pipeline_id, root_dev)       # before anything is moved
        if lock is not None:
            open_fds.append(lock)
        # A launch that was prepared and never run still has its scratch outside
        # the state directory: the launch's own discard removes both.
        for s in pl.sessions:
            if s["state"] == "prepared":
                res = agent_sessions.discard_prepared(Path(os.fspath(base)), s["launch_id"])
                if not res.get("cleaned"):
                    raise FlowDataRefused(f"未啟動的 session {s['launch_id']} 無法移除（{res.get('retained_reason', '')}）")
                removed["sessions"].append(s["launch_id"])
        # the tomb: from here on the flow counts as stopped (is_held) and a retry finishes it
        deleting = _mkdir_private(state, DELETING, root_dev)
        open_fds.append(deleting)
        tomb = _mkdir_private(deleting, pl.pipeline_id, root_dev)
        open_fds.append(tomb)
        _fsync(state)
        _fsync(deleting)
        for sub, items, key, idname in (("sessions", pl.sessions, "sessions", "launch_id"),
                                        ("reviews", pl.reviews, "reviews", "job_id")):
            live = [x for x in items if not (key == "sessions" and x["state"] == "prepared")]
            if not live:
                continue
            src = _root_fd(state, sub, root_dev)
            if src is None:
                continue
            open_fds.append(src)
            dst = _mkdir_private(tomb, sub, root_dev)
            open_fds.append(dst)
            for x in live:
                if _move(src, x[idname], dst, x[idname], root_dev, x["inode"]):
                    removed[key].append(x[idname])
        if pl.automation_inode is not None:
            src = _root_fd(state, AUTOMATION, root_dev)
            if src is not None:
                open_fds.append(src)
                _move(src, pl.pipeline_id, tomb, "automation", root_dev, pl.automation_inode)
        if pl.pipeline_dir:
            src = _root_fd(state, PIPELINES, root_dev)
            if src is not None:
                open_fds.append(src)
                if _move(src, pl.pipeline_dir, tomb, "pipeline", root_dev, pl.pipeline_inode):
                    removed["pipeline"] = True
        _fsync(tomb)
        # purge: no manifest is needed from here. The tomb itself STAYS (empty) until finish(): it is the visible
        # "this flow is being deleted" that stops anyone creating something new for it, and it goes only after
        # the console has removed the flow's own record (S3-2 review, deletion vs a not-yet-locked approval).
        budget = [WALK_MAX_ENTRIES]
        for child in os.listdir(tomb):
            if _purge(tomb, child, root_dev, budget):
                removed["purged"] = True
        _fsync(tomb)
        _fsync(deleting)
        if pl.held or pl.deleting:
            removed["hold"] = _remove_hold(state, pl.pipeline_id, root_dev)
        try:                                                    # a mode record has no meaning once the flow is gone
            pipeline_store.mode_remove(base, pl.pipeline_id)
        except pipeline_store.StoreRefused:
            pass
    finally:
        for fd in open_fds:
            try:
                os.close(fd)
            except OSError:
                pass
    return removed


def finish(base, pipeline_id: str) -> bool:
    """The last step of a deletion: the (empty) deletion marker goes. The
    caller has removed the flow's record. False when there is no marker;
    FlowDataRefused when it still holds something (then the deletion is not
    done)."""
    try:
        state = os.open(str(base), _DIR)
    except OSError as exc:
        raise FlowDataRefused(f"狀態目錄無法開啟（{exc.strerror}）") from exc
    try:
        deleting = _root_fd(state, DELETING, os.fstat(state).st_dev)
        if deleting is None:
            return False
        try:
            try:
                os.rmdir(pipeline_id, dir_fd=deleting)
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise FlowDataRefused(f"刪除標記裡還有東西（{exc.strerror}），刪除還沒完成") from exc
            _fsync(deleting)
        finally:
            os.close(deleting)
        try:
            os.rmdir(DELETING, dir_fd=state)                     # an empty deleting/ is not kept
        except OSError:
            pass
        return True
    finally:
        os.close(state)


def sweep_orphans(base, known_flow_ids) -> list[str]:
    """Empty deletion markers of flows that no longer exist (the console
    died between removing the record and asking for finish): removed."""
    out = []
    try:
        names = os.listdir(os.path.join(str(base), DELETING))
    except OSError:
        return out
    for name in names:
        if pipeline_store.FLOW_RE.match(name) and name not in known_flow_ids:
            try:
                if finish(base, name):
                    out.append(name)
            except FlowDataRefused:
                pass
    return out


def _remove_hold(state: int, pipeline_id: str, root_dev: int) -> bool:
    """The stop marker of a flow whose deletion is under way (a flow that was
    stopped by the user is refused before this)."""
    holds = _root_fd(state, HOLDS, root_dev)
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
