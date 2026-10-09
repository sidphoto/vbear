"""Codex review RPCs and loop hooks for the runtime daemon (design 5, 6, 7, 9;
planner decisions S2b, v29.8, v29.9). Mixed into ``daemon.Daemon``; every
method runs on the daemon's single thread, so a hold and a start are strictly
ordered (design 7).

  review_start   {pipeline, round, commit}   start (or, same round and commit, return) a review job
  review_status  {job_id}
  review_cancel  {job_id}                    end a running review; it is invalid (a failure)

Nothing here judges a review (review_finish does) or runs the process
(review_run does); this module is the order in which things happen, and what
the daemon does around them:

  * before anything is created: the flow, its acceptance and limits, the hold,
    one review at a time, the pinned and verified Codex, no administrator or
    system settings, the dedicated CODEX_HOME and its login (bound to the
    acceptance), no MCP server, and the quota reservation;
  * a job is durable before its process: scratch and run home, the manifest
    (prepared), the flow's link, then "launching" (a process may exist), the
    process, and only then "running" with its leader. A failure at any step
    ends the job as invalid (or manual_review when a process cannot be proven
    gone) and holds the flow: the same v29.8 rule as every other failure;
  * a hold on the flow (or a failure of another part of it) ends its running
    review; a review that ended while the flow was held is invalid.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import selectors
import signal
import subprocess
import tempfile
import time

from .. import admin_policy, login_identity, tasks
from . import (cli_versions, codex_constants as cc, pipeline_store, proctrack, quota, review_codex, review_finish,
               review_recover, review_run, review_store, stream_flow, stream_session)
from .daemon_stream import _err, _ok

SHUTDOWN_GRACE = review_run.TERM_GRACE + review_run.KILL_GRACE + 2.0
VIEW_FIELDS = ("job_id", "pipeline_id", "round", "commit", "model", "codex_version", "state", "outcome", "process",
               "created", "ended_at", "exit_code", "thread_id", "invalid_reasons", "retained_reason")


class _Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ReviewJob:
    def __init__(self, job_id: str, m: dict, c: cc.CodexConstants, run, key: str):
        self.job_id, self.m, self.c, self.run, self.key = job_id, m, c, run, key
        self.pipeline_id, self.task_id = m["pipeline_id"], m["task_id"]
        self.held = False                  # the flow was stopped while this ran
        self.registered: set[str] = set()
        self.dirty_logged = False


class ReviewOps:
    # set up by Daemon.__init__: base, _sel, _reviews, _ledger, _log, _held_leaders, review_admin_root,
    # review_home (the home the pinned Codex lives under; None: the user's), _shutdown_requested

    # ---- RPCs ----------------------------------------------------------------------------------------

    def _op_review_start(self, rid: str, req: dict) -> dict:
        if self._shutdown_requested:
            return _err(rid, "limit", "背景程序正在關閉，不接受新的審查")
        pipeline, round_, commit = req.get("pipeline"), req.get("round"), req.get("commit")
        if not (isinstance(pipeline, str) and review_store.FLOW_RE.match(pipeline)):
            return _err(rid, "bad_request", "流程 id 格式不符")
        if not (isinstance(round_, int) and not isinstance(round_, bool) and 1 <= round_ <= review_store.ROUND_MAX):
            return _err(rid, "bad_request", f"輪次必須是 1 到 {review_store.ROUND_MAX} 的整數")
        if not (isinstance(commit, str) and review_store.COMMIT_RE.match(commit)):
            return _err(rid, "bad_request", "commit 必須是 40 或 64 碼小寫十六進位")
        try:
            ctx = stream_flow.load(self.base, pipeline)
            if pipeline_store.is_held(self.base, pipeline):           # first: a hold refuses a resend too
                raise _Refused("held", "這個流程已停止")
            now = time.time()
            # the acceptance, the limits and any unresolved failure are
            # re-checked on every call, a resend included (v29.8)
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False)
            same_round = [x for x in ctx.totals.reviews if x["round"] == round_]
            if same_round:
                if same_round[0]["commit"] != commit:
                    raise _Refused("conflict", f"輪次 {round_} 已有針對另一個 commit 的審查")
                return _ok(rid, self._review_view(same_round[0]["job_id"], existing=True))
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False, counting_review=True)
            if self._reviews:
                raise _Refused("limit", "已有審查在執行（全域同時最多一個）")
            busy = [x["job_id"] for x in ctx.totals.reviews if x["state"] in ("prepared", "launching", "running")]
            if busy:
                raise _Refused("busy", f"這個流程已有尚未結束的審查（{busy[0]}），一次只能有一個")
            room = self._session_room(rid)
            if room:
                return room
            plan = self._review_preflight(ctx)
            return self._review_spawn(rid, ctx, plan, round_, commit)
        except stream_flow.FlowRefused as exc:
            return _err(rid, "refused", f"{exc.code}: {exc}")
        except _Refused as exc:
            return _err(rid, "limit" if exc.code == "limit" else "refused", f"{exc.code}: {exc}")
        except review_codex.CodexRefused as exc:
            return _err(rid, "refused", f"{exc.code}: {exc}")
        except (review_store.ReviewRefused, pipeline_store.StoreRefused) as exc:
            return _err(rid, "refused", f"{getattr(exc, 'code', 'refused')}: {exc}")
        except OSError as exc:
            return _err(rid, "refused", f"狀態無法驗證：{exc}")

    def _op_review_status(self, rid: str, req: dict) -> dict:
        job_id = req.get("job_id")
        if not (isinstance(job_id, str) and review_store.JOB_RE.match(job_id)):
            return _err(rid, "bad_request", "無效的審查工作 id")
        try:
            return _ok(rid, self._review_view(job_id))
        except (review_store.ReviewRefused, OSError) as exc:
            return _err(rid, "refused", f"審查工作無法讀取（{getattr(exc, 'code', type(exc).__name__)}）")

    def _op_review_cancel(self, rid: str, req: dict) -> dict:
        job = self._reviews.get(req.get("job_id")) if isinstance(req.get("job_id"), str) else None
        if job is None:
            return _err(rid, "refused", "這個審查不在執行")
        job.run.bad("使用者取消了審查")
        job.run.terminate("cancel")
        return _ok(rid, {"job_id": job.job_id, "canceling": True})

    # ---- what a status shows -----------------------------------------------------------------------

    def _review_view(self, job_id: str, existing: bool = False) -> dict:
        m = review_store.read_manifest(self.base, job_id)
        out = {k: m.get(k) for k in VIEW_FIELDS}
        out["existing"] = existing
        job = self._reviews.get(job_id)
        if job is not None:
            r = job.run
            out["live"] = {"responses_seen": r.watch.responses, "elapsed_s": round(time.monotonic() - r.started, 1),
                           "ending": r.terminated_for, "events_bytes": r.events_bytes}
        if m["outcome"] in ("valid", "invalid"):
            try:
                with pipeline_store.Pipeline(self.base, m["task_id"], create=False) as p:
                    res = p.review_result(m["round"])
                state = stream_flow.record_state(m, res)
            except (OSError, pipeline_store.StoreRefused, stream_flow.FlowRefused) as exc:
                res, state = None, f"damaged ({type(exc).__name__})"
            out["record"] = state
            if state == "complete":
                out["result"] = {k: res.get(k) for k in ("valid", "verdict", "base_is_ancestor", "reasons")}
        return out

    # ---- before anything is created ----------------------------------------------------------------

    def _review_preflight(self, ctx):
        """Everything that must hold before a job exists. Raises _Refused or
        CodexRefused; a check that cannot be made is a refusal."""
        acc = ctx.acceptance
        version, model = acc["codex_version"], acc["model"]
        c = cc.VERSIONS.get(version)
        if c is None or version not in cc.VERIFIED_VERSIONS:
            raise _Refused("unverified", f"Codex {version} 還沒有通過驗證，不能啟動審查")
        if model not in c.models:
            raise _Refused("unverified", "審查模型不在這個 Codex 版本已驗證的清單內")
        # the task's work directory is the one the executor ran in (v29.9)
        task = tasks.get_task(ctx.task_id)
        workdir = task.get("workdir") if task else None
        if not (isinstance(workdir, str) and review_store.WORKDIR_RE.match(workdir)
                and os.path.normpath(workdir) == workdir):
            raise _Refused("no_workdir", "任務沒有可用的工作目錄")
        if ctx.started_at is None:
            raise _Refused("no_base", "這個流程還沒有啟動過串流 session，沒有審查範圍的起點")
        sessions = stream_flow.flow_sessions(self.base, ctx.pipeline_id, started=True)
        if not sessions:
            raise _Refused("no_base", "這個流程有開始紀錄，但找不到任何串流 session")
        if any(x.get("canonical_workspace") != workdir for x in sessions):
            raise _Refused("workdir_mismatch", "任務的工作目錄與執行者 session 的工作目錄不同")
        with pipeline_store.Pipeline(self.base, ctx.task_id, create=False) as p:
            start = p.start_record()
        if start is None or start["pipeline_id"] != ctx.pipeline_id:
            raise _Refused("no_base", "流程沒有開始紀錄，讀不到審查範圍的起點")
        policy = admin_policy.check_codex(version, root=self.review_admin_root)
        if not policy.ok:
            raise _Refused("admin_policy", policy.reason())
        binary = review_codex.codex_binary(version, home=self.review_home)
        if review_codex.read_version(binary, cli_versions._run_probe) != version:
            raise _Refused("version_mismatch", f"固定位置的 Codex 不是 {version}")
        home = review_codex.check_codex_home(self.base)
        if review_codex.over_limit(review_codex.tree_size(home), review_codex.HOME_LIMIT):
            raise _Refused("codex_home_full", "專用的 CODEX_HOME 超過 512 MiB（或無法完整計算），請先清理")
        fp = login_identity.codex_login_fingerprint(home, ctx.key)
        if not fp.ok:
            raise _Refused("no_login", f"專用 CODEX_HOME 還沒有登入，或登入無法辨識（{fp.problem}）")
        bind = review_codex.check_binding(acc, version=version, model=model, login_fingerprint=fp.hmac,
                                          key_id=ctx.key.key_id, current_key_id=ctx.key.key_id)
        if not bind.ok:
            raise _Refused("reaccept", bind.reason)
        self._mcp_must_be_empty(c, binary, home)
        return {"c": c, "version": version, "model": model, "binary": binary, "workdir": workdir,
                "base_commit": start["base_commit"], "home": home,
                "timeout_s": float(ctx.limits["review_timeout_min"]) * 60.0,
                "max_responses": int(ctx.limits["review_max_responses"])}

    def _mcp_must_be_empty(self, c, binary: str, home) -> None:
        """`codex mcp list --json` with the review's own settings must print
        an empty array (design 5.2). HOME is a throwaway empty directory."""
        parent = os.path.join(os.path.realpath(self.base), review_codex.RUN_HOMES)
        os.makedirs(parent, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="mcp-", dir=parent) as tmp_home:
            os.chmod(tmp_home, 0o700)
            env = review_codex.build_env(str(home), tmp_home)
            if not review_codex.mcp_list_is_empty(c, binary, env, review_codex.run_argv):
                raise _Refused("mcp", "codex mcp list 沒有回傳空陣列（或無法執行），不啟動審查")

    # ---- creating and starting the job ----------------------------------------------------------------

    def _review_spawn(self, rid: str, ctx, plan: dict, round_: int, commit: str) -> dict:
        c, version, model = plan["c"], plan["version"], plan["model"]
        job_id = "r-" + secrets.token_hex(8)
        key = f"review:{job_id}"
        why = self._reserve(key, quota.RESERVE_REVIEW)
        if why:
            return _err(rid, "refused", f"quota: {why}")
        scratch = run_home = None            # (path, {"inode", "dev"}) of what this call created
        m = None
        events_fd = stderr_fd = -1
        proc = leader_start = run = None
        try:
            prompt = review_codex.prompt_for(c, workdir=plan["workdir"], commit=commit, base=plan["base_commit"])
            spath = tempfile.mkdtemp(prefix=review_store.SCRATCH_PREFIX, dir=review_store.SCRATCH_PARENT)
            st = os.stat(spath)
            scratch = (spath, {"inode": st.st_ino, "dev": st.st_dev})
            hpath = str(review_store.run_home(self.base, job_id))
            os.makedirs(os.path.dirname(hpath), mode=0o700, exist_ok=True)
            os.mkdir(hpath, 0o700)
            st = os.stat(hpath)
            run_home = (hpath, {"inode": st.st_ino, "dev": st.st_dev})
            argv = review_codex.review_argv(c, plan["binary"], model=model, scratch=spath, prompt=prompt)
            env = review_codex.build_env(str(plan["home"]), hpath)
            m = {"review_manifest_version": 1, "job_id": job_id, "pipeline_id": ctx.pipeline_id,
                 "task_id": ctx.task_id, "round": round_, "commit": commit, "model": model, "codex_version": version,
                 "argv_sha256": hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest(),
                 "scratch": {"path": spath, **scratch[1]}, "run_home": dict(run_home[1]), "leader": None,
                 "observed": [], "thread_id": None, "exit_code": None, "state": "prepared", "created": time.time(),
                 "process": "none", "outcome": None, "workdir": plan["workdir"]}
            review_store.create_job_dir(self.base, job_id)
        except Exception as exc:
            self._review_undo_dirs(scratch, run_home)
            self._ledger.release(key, 0)
            return _err(rid, "refused", f"審查工作無法建立：{type(exc).__name__}: {exc}")
        # From here the job is on disk: whatever fails ends it as a decided job.
        try:
            review_store.write_new_manifest(self.base, m)
            with pipeline_store.Pipeline(self.base, ctx.task_id, create=True) as p:
                p.write_review_link(round_, job_id, ctx.pipeline_id, commit)
            m = review_store.update_manifest(self.base, job_id, state="launching", process="maybe")
            jdir = review_store.job_dir(self.base, job_id)
            events_fd = os.open(jdir / review_finish.EVENTS_NAME,
                                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            stderr_fd = os.open(jdir / review_finish.STDERR_NAME,
                                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=spath, env=env, start_new_session=True, close_fds=True)
        except Exception as exc:
            for fd in (events_fd, stderr_fd):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self._review_end_unspawned(job_id, m, c, key, f"審查無法啟動（{type(exc).__name__}: {exc}）"[:300])
            return _err(rid, "internal", f"審查無法啟動：{type(exc).__name__}")
        # A process exists: every step until the job is "running" is undone on failure.
        try:
            leader_start = stream_session.capture_leader(proc.pid)
            if leader_start is None:
                raise _Refused("leader", "無法取得 leader 的開始時間，這個程序無法安全地管理")
            run = review_run.ReviewRun(
                job_id=job_id, c=c, proc=proc, events_fd=events_fd, stderr_fd=stderr_fd, leader_start=leader_start,
                codex_home=plan["home"], scratch=spath, run_home=hpath, timeout_s=plan["timeout_s"],
                max_responses=plan["max_responses"], log=self._log, now=time.monotonic())
            events_fd = stderr_fd = -1                   # the run owns them now
            try:
                run.descendants.observe(proctrack.process_table())
            except proctrack.ProcessTableUnavailable as exc:
                self._log(f"{job_id}: process table unavailable at launch: {exc}")
            m = review_store.update_manifest(
                self.base, job_id, state="running", process="started",
                leader={"pid": proc.pid, "start": leader_start, "source": proctrack.SOURCE},
                observed=run.descendants.export())
            job = ReviewJob(job_id, m, c, run, key)
            self._reviews[job_id] = job
            self._register_review(job, "stdout")
            self._register_review(job, "stderr")
        except Exception as exc:
            self._review_abort_spawned(job_id, m, c, key, proc, leader_start, run, events_fd, stderr_fd,
                                       f"{type(exc).__name__}: {exc}")
            return _err(rid, "internal", f"啟動後初始化失敗：{type(exc).__name__}")
        return _ok(rid, self._review_view(job_id))

    def _review_undo_dirs(self, scratch, run_home) -> None:
        """Before the job had a manifest: remove only what this call created."""
        if scratch is not None:
            review_finish._remove_child(review_store.SCRATCH_PARENT, os.path.basename(scratch[0]), scratch[1])
        if run_home is not None:
            review_finish._remove_child(os.path.dirname(run_home[0]), os.path.basename(run_home[0]), run_home[1])

    def _hold_for_review(self, pipeline_id: str, job_id: str, why: str) -> None:
        self._hold_for_failure(pipeline_id, job_id, why, kind="review")

    def _review_end_unspawned(self, job_id: str, m: dict | None, c, key: str, why: str) -> None:
        """The job is on disk and no process was started: decide it invalid
        with the reason, keep the record, clean up, hold the flow."""
        self._log(f"{job_id}: {why}")
        fin = None
        try:
            fresh = review_store.read_manifest(self.base, job_id)
            fin = review_finish.finish_review(self.base, fresh, {"never_started": why, "manual_review": None,
                                                                  "interrupted": False, "invalid_reasons": []}, c=c)
        except Exception as exc:
            review_store.retain(self.base, job_id, f"{why}；結束時發生錯誤（{type(exc).__name__}）")
            try:
                review_store.read_manifest(self.base, job_id)
            except Exception:
                # not even a manifest: what this call created is still ours to remove, by what it recorded
                try:
                    review_finish.cleanup_job(self.base, m)
                except Exception:
                    pass
        pipeline_id = (m or {}).get("pipeline_id")
        if pipeline_id:
            self._hold_for_review(pipeline_id, job_id, why)
        self._ledger.release(key, self._review_bytes(job_id, m))

    def _review_abort_spawned(self, job_id, m, c, key, proc, leader_start, run, events_fd, stderr_fd, why) -> None:
        """A process was started but the job could not be set up. After the
        identity check its group is killed and proven gone, then the leader is
        reaped; when that cannot be proven nothing is reaped and the job is
        kept for a person."""
        self._log(f"{job_id}: set-up after spawn failed ({why}); ending the process")
        job = self._reviews.pop(job_id, None)
        if job is not None:
            for which in list(job.registered):
                self._unregister_review(job, which)
        problem = stream_session.end_spawned(proc, leader_start, run.descendants if run is not None else None)
        for f in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if f is not None:
                    f.close()
            except OSError:
                pass
        for fd in (events_fd, stderr_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if run is not None:
            run._close_ends()
        pipeline_id = (m or {}).get("pipeline_id")
        if problem is None:
            try:
                fresh = review_store.read_manifest(self.base, job_id)
                review_finish.finish_review(
                    self.base, fresh, {"manual_review": None, "interrupted": False, "terminated_for": "setup_failed",
                                       "exit_code": None, "invalid_reasons": [f"啟動後初始化失敗（{why}）"[:250]]},
                    c=c)
            except Exception as exc:
                review_store.retain(self.base, job_id, f"啟動後初始化失敗（{why}）；結束時發生錯誤（{type(exc).__name__}）")
        else:
            review_store.retain(self.base, job_id, f"啟動後初始化失敗（{why}）；{problem}")
            self._hold_leader(proc, job_id)
        if pipeline_id:
            self._hold_for_review(pipeline_id, job_id, f"啟動後初始化失敗（{why}）"[:200])
        self._ledger.release(key, self._review_bytes(job_id, m))

    def _review_bytes(self, job_id: str, m: dict | None) -> int | None:
        """What the job added to the protected data, measured on disk: its
        directory and its record directory (files only, none of them
        nested). None when it cannot be measured (the ledger then counts the
        whole reservation and grants nothing more until rebuilt)."""
        total = 0
        try:
            paths = [str(review_store.job_dir(self.base, job_id))]
            if m is not None:
                paths.append(os.path.join(os.path.realpath(self.base), "pipelines", m["task_id"], "reviews",
                                          str(m["round"])))
            for path in paths:
                try:
                    with os.scandir(path) as it:
                        for e in it:
                            st = e.stat(follow_symlinks=False)
                            if not (st.st_mode & 0o170000 == 0o100000):
                                return None
                            total += st.st_size
                except FileNotFoundError:
                    pass
        except OSError as exc:
            self._log(f"{job_id}: bytes on disk cannot be measured ({exc})")
            return None
        return total

    # ---- loop hooks -------------------------------------------------------------------------------------

    def _register_review(self, job: ReviewJob, which: str) -> None:
        fd = {"stdout": job.run.stdout, "stderr": job.run.stderr}[which]
        if which in job.registered:
            return
        self._sel.register(fd, selectors.EVENT_READ, ("review", job, which))
        job.registered.add(which)

    def _unregister_review(self, job: ReviewJob, which: str) -> None:
        if which not in job.registered:
            return
        fd = {"stdout": job.run.stdout, "stderr": job.run.stderr}[which]
        try:
            self._sel.unregister(fd)
        except (KeyError, ValueError):
            pass
        job.registered.discard(which)

    def _review_ready(self, job: ReviewJob, which: str, now: float) -> None:
        try:
            (job.run.on_stdout if which == "stdout" else job.run.on_stderr)(now)
        except Exception as exc:
            self._review_crashed(job, exc)

    def _review_tick(self, now: float) -> None:
        for job in list(self._reviews.values()):
            if self._reviews.get(job.job_id) is not job:
                continue
            try:
                job.run.tick(now)
                if job.run.stdout_eof:
                    self._unregister_review(job, "stdout")
                if job.run.stderr_eof:
                    self._unregister_review(job, "stderr")
                self._save_observed(job)
                if job.run.finished:
                    self._finish_review(job)
            except Exception as exc:
                self._review_crashed(job, exc)

    def _save_observed(self, job: ReviewJob) -> None:
        """New descendants go into the manifest so a restart can look for them."""
        run = job.run
        if not run.observed_dirty or run.finished:
            return
        try:
            review_store.update_manifest(self.base, job.job_id, observed=run.descendants.export())
            run.observed_dirty = False
        except (OSError, review_store.ReviewRefused) as exc:
            if not job.dirty_logged:
                job.dirty_logged = True
                self._log(f"{job.job_id}: observed processes cannot be saved yet ({type(exc).__name__})")

    def _review_crashed(self, job: ReviewJob, exc: Exception) -> None:
        """The outer guard of every per-review step: an unexpected exception
        never leaves the loop. The review is given up to manual review
        without a signal, with its leader kept unreaped (design 5.8), the flow
        is held, and it always leaves _reviews so the same exception cannot
        repeat on every pass."""
        why = f"管理審查時發生未預期的錯誤（{type(exc).__name__}）"
        steps = [lambda: self._log(f"{job.job_id}: {why}"),
                 lambda: [self._unregister_review(job, w) for w in list(job.registered)],
                 lambda: job.run._abandon(f"{why}，交人工處理") if not job.run.finished else None,
                 lambda: review_store.retain(self.base, job.job_id, why),
                 lambda: self._hold_for_review(job.pipeline_id, job.job_id, why),
                 lambda: self._hold_leader(job.run.proc, job.job_id) if not job.run.reaped else None]
        for step in steps:
            try:
                step()
            except Exception:
                pass
        try:
            self._ledger.release(job.key, self._review_bytes(job.job_id, job.m))
        except Exception:
            pass
        self._reviews.pop(job.job_id, None)

    def _finish_review(self, job: ReviewJob) -> None:
        for which in list(job.registered):
            self._unregister_review(job, which)
        run = job.run
        out = run.outcome if isinstance(run.outcome, dict) else {"manual_review": "審查結束時沒有留下結果",
                                                                  "leader_held": not run.reaped}
        fin = None
        try:
            m = review_store.read_manifest(self.base, job.job_id)
            fin = review_finish.finish_review(
                self.base, m, {"manual_review": out.get("manual_review"), "exit_code": out.get("exit_code"),
                               "exit_signal": out.get("exit_signal"), "terminated_for": out.get("terminated_for"),
                               "invalid_reasons": out.get("invalid_reasons") or [], "held": job.held,
                               "interrupted": False}, c=job.c)
        except Exception as exc:
            why = f"審查結束後無法判定（{type(exc).__name__}）"
            review_store.retain(self.base, job.job_id, why)
            self._log(f"{job.job_id}: {why}")
        if out.get("leader_held"):
            self._hold_leader(run.proc, job.job_id)
        self._reviews.pop(job.job_id, None)               # before the hold: a hold must not end this job again
        if fin is None:
            self._hold_for_review(job.pipeline_id, job.job_id, "審查結束後無法判定")
        elif fin.outcome != "valid" or not fin.record_complete:
            why = "；".join(fin.reasons[:2]) or fin.problem or "審查沒有通過"
            if fin.outcome == "valid":
                why = f"審查結果有效，但審查紀錄不完整：{fin.problem}"
            self._hold_for_review(job.pipeline_id, job.job_id, why[:200])
        self._log(f"{job.job_id}: review ended: {fin.outcome if fin else 'undecided'}"
                  + (f" ({fin.problem})" if fin and fin.problem else ""))
        self._ledger.release(job.key, self._review_bytes(job.job_id, job.m))

    # ---- hold and shutdown -----------------------------------------------------------------------------

    def _review_hold(self, pipeline_id: str) -> None:
        """The flow was stopped (the RPC, or a failure's hold): its running
        review ends, and what it says is invalid (design 7)."""
        for job in list(self._reviews.values()):
            if job.pipeline_id != pipeline_id or job.run.finished:
                continue
            job.held = True
            try:
                job.run.bad("流程被停止，審查中止")
                job.run.terminate("hold")
            except Exception as exc:
                self._review_crashed(job, exc)

    def _kill_all_reviews(self) -> None:
        """Daemon shutdown: nobody could manage these afterwards."""
        jobs = list(self._reviews.values())
        for job in jobs:
            try:
                job.run.bad("背景程序關閉，審查中止")
                job.run.terminate("daemon_shutdown")
            except Exception as exc:
                self._review_crashed(job, exc)
        jobs = [j for j in jobs if j.job_id in self._reviews]
        deadline = time.monotonic() + SHUTDOWN_GRACE
        while jobs and time.monotonic() < deadline:
            for job in jobs:
                try:
                    for which in ("stdout", "stderr"):
                        if which in job.registered:
                            (job.run.on_stdout if which == "stdout" else job.run.on_stderr)(time.monotonic())
                    job.run.tick(time.monotonic())
                    if job.run.finished:
                        self._finish_review(job)
                except Exception as exc:
                    self._review_crashed(job, exc)
            jobs = [j for j in jobs if not j.run.finished and j.job_id in self._reviews]
            time.sleep(0.05)
        for job in jobs:
            try:
                job.run._killpg(signal.SIGKILL)       # without a proven identity nothing is sent
            except Exception:
                pass
            why = "背景程序關閉時程序未能證明已結束"
            self._log(f"{job.job_id}: still running at shutdown; kept for manual review")
            for step in (lambda: [self._unregister_review(job, w) for w in list(job.registered)],
                         lambda: review_store.retain(self.base, job.job_id, why),
                         lambda: self._hold_for_review(job.pipeline_id, job.job_id, why),
                         lambda: self._hold_leader(job.run.proc, job.job_id)):
                try:
                    step()
                except Exception:
                    pass
            self._reviews.pop(job.job_id, None)

    # ---- at start -------------------------------------------------------------------------------------------

    def _recover_reviews(self) -> None:
        """Jobs a previous daemon left (review_recover). Every failure it
        decided holds its flow; nothing is signalled."""
        try:
            items = review_recover.recover(self.base)
        except Exception as exc:
            self._log(f"review recovery failed: {type(exc).__name__}")
            return
        for item in items:
            self._log(f"review {item['job_id'] or '?'}: {item['action']}" + (f" ({item['why']})" if item["why"] else ""))
            if item["failure"] and item["pipeline_id"]:
                self._hold_for_review(item["pipeline_id"], item["job_id"], item["why"] or item["action"])

    def _review_outstanding(self) -> dict | None:
        """For the quota ledger: every job not yet in a final state, at its
        full reservation. None when that cannot be established."""
        out: dict[str, int] = {}
        try:
            for name in review_store.list_jobs(self.base):
                if not review_store.JOB_RE.match(name):
                    raise review_store.ReviewRefused("manifest_invalid", f"reviews/ 裡有不認得的項目 {name[:64]!r}")
                m = review_store.read_manifest(self.base, name)
                if m["state"] not in review_store.TERMINAL:
                    out[f"review:{name}"] = quota.RESERVE_REVIEW
        except (review_store.ReviewRefused, OSError) as exc:
            self._log(f"quota rebuild: review jobs unreadable: {exc}")
            return None
        return out
