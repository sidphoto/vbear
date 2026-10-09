"""Stream executor RPCs and loop hooks for the runtime daemon (design 2-3, 6,
7, 9; planner decisions S2a-2 Q1-Q4). Mixed into ``daemon.Daemon``; every
method runs on the daemon's single thread, so a hold and a dispatch are
strictly ordered (design 7).

  open_stream       {launch_id}                         start a prepared stream launch
  dispatch_prepare  {launch_id, pipeline, dispatch_id, text, approval}
  stream_send       {launch_id, pipeline, dispatch_id}
  stream_status     {launch_id}
  stream_close      {launch_id}
  pipeline_hold     {pipeline, reason}
  pipeline_release  {pipeline}

``pipeline`` in the two dispatch RPCs is what design 3.1 checks against the
manifest ("manifest 綁定的流程等於請求的流程").
"""

from __future__ import annotations

import os
import re
import secrets
import selectors
import signal
import subprocess
import time
import uuid

from .. import admin_policy, executor_report, git_head
from . import (agent_sessions, cli_versions, pipeline_store, proctrack, quota, stream_flow, stream_journal,
               stream_protocol as sp, stream_session)

_APPROVAL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}\Z")
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _ok(rid, result) -> dict:
    return {"v": 1, "id": rid, "ok": True, "result": result}


def _err(rid, code: str, message: str) -> dict:
    return {"v": 1, "id": rid, "ok": False, "error": {"code": code, "message": message}}


HELD_RECHECK = 5.0
MAX_HELD_LEADERS = 4      # unproven process groups VBear keeps; at this many, no new session opens


class _SetupFailed(Exception):
    pass


class StreamOps:
    # set up by Daemon.__init__: base, _sel, _sessions, _streams, _ledger, _log, max_sessions

    # ---- quota ---------------------------------------------------------------------

    def _rebuild_ledger(self) -> bool:
        """Design 9: used = a fresh scan; every stream launch not proven
        ended counts at its full journal reservation."""
        outstanding: dict[str, int] | None = {}
        root = agent_sessions.sessions_root(self.base)
        try:
            try:
                names = sorted(os.listdir(root))
            except FileNotFoundError:
                names = []                # never created: no launch at all (not Path.is_dir(), which reads errors as False)
            for name in names:
                if not agent_sessions.LAUNCH_RE.match(name):
                    raise agent_sessions.LaunchRefused(
                        "manifest_invalid", f"sessions/ 裡有不認得的項目 {name[:64]!r}")
                m = agent_sessions._read_manifest(agent_sessions.launch_dir(self.base, name), os.getuid())
                if m.get("engine") == "claude-stream" and m.get("state") not in ("prepared", "ended"):
                    outstanding["session:" + name] = quota.RESERVE_SESSION
        except (OSError, agent_sessions.LaunchRefused) as exc:
            self._log(f"quota rebuild: manifests unreadable: {exc}")
            outstanding = None
        ok = self._ledger.rebuild(outstanding)
        if not ok:
            self._log(f"quota rebuild failed: {self._ledger.problem}")
        return ok

    def _reserve(self, key: str, amount: int) -> str | None:
        if self._ledger.used is None:
            self._rebuild_ledger()
        return self._ledger.reserve(key, amount)

    # ---- open --------------------------------------------------------------------------

    def _op_open_stream(self, rid: str, req: dict) -> dict:
        from .daemon import build_env  # here: daemon imports this module
        if self._shutdown_requested:
            return _err(rid, "limit", "背景程序正在關閉，不接受新的 session")
        refused = self._session_room(rid)
        if refused:
            return refused
        launch_id = req.get("launch_id")
        key = f"session:{launch_id}"
        reserved = launching = False
        started_here = None                   # the start record, when this open wrote it
        start_mine = False                    # this open may have written a start record (review B-2)
        manifest_before = start_bytes = 0     # for what this session adds to the quota (B4)
        m = None
        try:
            m = agent_sessions.load_validated(self.base, launch_id)
            if m["engine"] != "claude-stream" or m.get("state") != "prepared" or m.get("native_session_id"):
                raise agent_sessions.LaunchRefused("consumed", "此 launch 不是待啟動的串流 launch")
            version = m["cli_version"]
            if version not in cli_versions.stream_verified_versions():
                raise agent_sessions.LaunchRefused("unverified", f"Claude Code {version} 的串流模式尚未通過驗證")
            env = build_env()
            env["CLAUDE_CODE_TMPDIR"] = m["scratch"]["path"]
            env["DISABLE_AUTOUPDATER"] = "1"
            home = env.get("HOME", "")
            policy = admin_policy.check_claude(version, home=home)
            if not policy.ok:
                raise agent_sessions.LaunchRefused("admin_policy", policy.reason())
            ctx = stream_flow.load(self.base, m["pipeline_id"])
            if ctx.task_id != m["task_id"]:
                raise agent_sessions.LaunchRefused("manifest_invalid", "launch 的任務與流程不符")
            # Part 2 review A-1 (design principle 3: one flow, one managed
            # executor): at most one stream session of a flow is not ended.
            # Each would start from the same snapshot of the flow's responses.
            # The manifest decides; manual_review is not ended (a person
            # resolves it first). A prepared launch never had a process.
            busy = sorted({x.launch_id for x in self._streams.values() if x.pipeline_id == m["pipeline_id"]}
                          | {x["launch_id"] for x in ctx.totals.sessions if x["manifest_state"] != "ended"})
            if busy:
                raise agent_sessions.LaunchRefused(
                    "busy", f"這個流程已有尚未結束的串流 session（{', '.join(busy[:4])}），一次只能有一個")
            # v29.8: one failure stops the flow until the user presses
            # "continue"; recomputed from the journals, not only the hold.
            failed = stream_flow.unresolved_failure(ctx)
            if failed:
                raise agent_sessions.LaunchRefused(
                    "failed", f"流程在上次「繼續」之後有失敗（{failed}），需要使用者先按「繼續」")
            if pipeline_store.is_held(self.base, m["pipeline_id"]):
                raise agent_sessions.LaunchRefused("held", "這個流程已停止")
            stream_flow.check_executor(ctx, cli_version=version, model_id=m["model_id"],
                                       claude_json=os.path.join(home, ".claude.json"))
            now = time.time()
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False)
            budget = stream_flow.remaining_budget(ctx)
            why = self._reserve(key, quota.RESERVE_SESSION)
            if why:
                raise agent_sessions.LaunchRefused("quota", why)
            reserved = True
            # The flow's first start (planner Q1) is recorded before anything
            # else changes: if it fails the launch is still "prepared"; if the
            # daemon dies right after, the clock has started a little early.
            # Never a journal (or a process) without a start record.
            manifest_before = self._manifest_bytes(m)
            with pipeline_store.Pipeline(self.base, m["task_id"], create=True) as p:
                if p.started_at(m["pipeline_id"]) is None:
                    start_mine = True             # from here a start record on disk may be this open's
                    # v29.9: where a review's range begins. Read from the files
                    # (git_head, never git); without it the flow cannot start.
                    head = git_head.read_head(m["canonical_workspace"])
                    if not (isinstance(head.get("commit"), str) and pipeline_store.COMMIT_RE.match(head["commit"])):
                        raise agent_sessions.LaunchRefused(
                            "no_base", f"讀不到工作目錄的 HEAD（{head.get('error')}），無法記錄審查範圍的起點")
                    started_here = p.record_start(m["pipeline_id"], now, launch_id=launch_id,
                                                  base_commit=head["commit"])
                    start_bytes = p.start_record_bytes()
            agent_sessions.update_manifest(self.base, launch_id, state="launching",
                                           claude_session_id=str(uuid.uuid4()), budget_usd=budget)
            launching = True
            m = agent_sessions.load_validated(self.base, launch_id)
            argv = agent_sessions.managed_argv(m)
        except (agent_sessions.LaunchRefused, stream_flow.FlowRefused, pipeline_store.StoreRefused, OSError) as exc:
            if launching:
                # Marked launching, but no journal and no process yet: do not
                # leave it so (the flow's totals would refuse until recovery).
                agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)
            left = self._undo_start(m, start_mine)
            if reserved:
                self._ledger.release(key, self._session_bytes(m, manifest_before, left) if m is not None else 0)
            if isinstance(exc, OSError):
                return _err(rid, "refused", f"launch 狀態無法驗證：{exc}")
            code = getattr(exc, "code", "refused")
            return _err(rid, "refused", f"{code}: {exc}")
        # The journal exists (with session_started) before the process does:
        # a launch without one never had a process (stream_flow relies on it).
        try:
            ldir = os.open(m["launch_dir"]["path"], _DIR)
            try:
                writer = stream_journal.JournalWriter(ldir, identity=stream_journal.identity_from(m, ctx.acceptance))
            finally:
                os.close(ldir)
        except (OSError, stream_journal.JournalCorrupt) as exc:
            # No process was started: clean up what this launch left.
            agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)
            left = self._undo_start(m, start_mine)
            self._ledger.release(key, self._session_bytes(m, manifest_before, left))
            return _err(rid, "internal", f"日誌無法建立：{exc}")
        try:
            writer.append("session_started", {
                "claude_session_id": m["claude_session_id"], "pipeline_id": m["pipeline_id"],
                "cli_version": m["cli_version"], "argv_sha256": sp.sha256_hex(sp.canonical(argv)),
                "budget_usd": m["budget_usd"]})
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=m["canonical_workspace"], env=env, start_new_session=True, close_fds=True)
        except (OSError, stream_journal.JournalCorrupt) as exc:
            self._record_spawn_failure(writer, exc)
            try:
                writer.append("exited", {"returncode": None, "signal": None, "stderr_tail": f"無法啟動：{exc}"[:500]})
            except (OSError, stream_journal.JournalCorrupt):
                pass
            writer.close()
            self._hold_for_failure(m["pipeline_id"], launch_id, f"無法啟動（{exc}）"[:200])
            if writer.state.started is not None and writer.state.exit is not None:
                agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)
            else:
                # The journal could not be written whole: a damaged journal is
                # for a person (v29.7), never "ended".
                agent_sessions._retain(self.base, launch_id, f"日誌無法寫入，無法啟動（{exc}）")
            self._ledger.release(key, self._session_bytes(m, manifest_before, start_bytes))
            return _err(rid, "internal", f"無法啟動：{exc}")
        # From here a process exists: every step until the session is set up
        # and on record is undone on failure (review B2), and nothing is ever
        # signalled without the leader's identity (B6), captured first.
        s = leader_start = None
        try:
            leader_start = stream_session.capture_leader(proc.pid)
            if leader_start is None:
                raise _SetupFailed("無法取得 leader 的開始時間，這個程序無法安全地管理")
            sid = "n-" + secrets.token_hex(6)
            while sid in self._sessions or any(x.sid == sid for x in self._streams.values()):
                sid = "n-" + secrets.token_hex(6)
            tracker = sp.EventTracker(sp.constants_for(m["cli_version"]), m["claude_session_id"],
                                      m["canonical_workspace"], m["model_id"],
                                      executor_version=ctx.acceptance["executor_claude_version"])
            s = stream_session.StreamSession(sid=sid, launch_id=launch_id, manifest=m, proc=proc, writer=writer,
                                             tracker=tracker, prior_responses=ctx.totals.responses, log=self._log,
                                             now=time.monotonic(), leader_start=leader_start)
            s.quota_base = (manifest_before, start_bytes)
            self._streams[launch_id] = s
            self._register_stream(s, "stdout")
            self._register_stream(s, "stderr")
            try:
                s.descendants.observe(proctrack.process_table())
            except proctrack.ProcessTableUnavailable as exc:
                self._log(f"{sid}: process table unavailable at launch: {exc}")
            agent_sessions.update_manifest(self.base, launch_id, state="running", native_session_id=sid,
                                           leader={"pid": proc.pid, "start": leader_start,
                                                   "source": proctrack.SOURCE},
                                           observed=s.descendants.export())
        except Exception as exc:
            return self._abort_spawned(rid, key, m, proc, writer, s, leader_start, manifest_before, start_bytes,
                                       f"{type(exc).__name__}: {exc}")
        return _ok(rid, {"session_id": sid, "launch_id": launch_id, "claude_session_id": m["claude_session_id"],
                         "budget_usd": m["budget_usd"], "state": s.state})

    def _abort_spawned(self, rid, key, m, proc, writer, s, leader_start, manifest_before, start_bytes, why) -> dict:
        """Review B2: the process started but its session could not be set
        up. Unwatch it, kill its group after the identity check, prove it
        gone, record the exit, close our ends; clean up, or keep the launch
        for manual review when nothing could be proven."""
        launch_id = m["launch_id"]
        self._log(f"{launch_id}: set-up after spawn failed ({why}); ending the process")
        if s is not None:
            for which in list(s.registered):
                self._unregister_stream(s, which)
        problem = stream_session.end_spawned(proc, leader_start, s.descendants if s is not None else None)
        self._record_spawn_failure(writer, why)
        self._hold_for_failure(m["pipeline_id"], launch_id, f"啟動後初始化失敗（{why}）"[:200])
        if writer.state.exit is None:
            try:
                writer.append("exited", {"returncode": None, "signal": None,
                                         "stderr_tail": f"啟動後初始化失敗：{why}"[:500]})
            except (OSError, stream_journal.JournalCorrupt):
                pass
        for f in (proc.stdin, proc.stdout, proc.stderr):
            try:
                f.close()
            except OSError:
                pass
        writer.close()
        if problem is None:
            agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)
        else:
            agent_sessions._retain(self.base, launch_id, f"啟動後初始化失敗（{why}）；{problem}")
            self._hold_leader(proc, launch_id)                 # not proven: never reaped here
        self._ledger.release(key, self._session_bytes(m, manifest_before, start_bytes))
        self._streams.pop(launch_id, None)
        return _err(rid, "internal", f"啟動後初始化失敗：{why}")

    def _text_added(self, task_id: str, d: str, before: int) -> int | None:
        try:
            with pipeline_store.Pipeline(self.base, task_id, create=False) as p:
                return max(0, p.text_bytes(d) - before)
        except (OSError, pipeline_store.StoreRefused) as exc:
            self._log(f"dispatch {d}: bytes on disk cannot be measured ({exc})")
            return None

    @staticmethod
    def _record_spawn_failure(writer, exc) -> None:
        """Review round 7: a session that could not start ended in error, a
        v29.8 failure with its own (launch, seq) identity, recorded before
        "exited" whenever the journal has session_started."""
        if writer.state.started is None or writer.state.exit is not None:
            return
        errno = getattr(exc, "errno", None)
        detail = (f"errno {errno}: " if errno is not None else "") + str(exc)
        try:
            writer.append("protocol_error", {"reason": "spawn_failed", "detail": detail[:1024]})
        except (OSError, stream_journal.JournalCorrupt):
            pass                          # the launch is then kept for review: also a failure

    @staticmethod
    def _manifest_bytes(m: dict) -> int:
        """The manifest and its sibling temp file (a failed atomic rewrite
        leaves manifest.json.tmp behind; the quota scan counts it: review B-2)."""
        total = 0
        for name in (agent_sessions.MANIFEST, agent_sessions.MANIFEST + ".tmp"):
            try:
                total += os.lstat(os.path.join(m["launch_dir"]["path"], name)).st_size
            except FileNotFoundError:
                pass
        return total

    def _session_bytes(self, m: dict, manifest_before: int, start_bytes: int | None) -> int | None:
        """What one stream session added to the protected data (review B4),
        as measured on disk (review B-1: never the writer's own count, which
        misses a short write or a failed fsync): its journal, its
        manifest's growth and the start record it wrote. None when it
        cannot be measured: the ledger then counts the whole reservation and
        grants nothing more until rebuilt."""
        try:
            try:
                journal = os.lstat(os.path.join(m["launch_dir"]["path"], agent_sessions.JOURNAL)).st_size
            except FileNotFoundError:
                journal = 0
            grown = max(0, self._manifest_bytes(m) - manifest_before)
        except OSError as exc:
            self._log(f"{m.get('launch_id')}: bytes on disk cannot be measured ({exc})")
            return None
        if start_bytes is None:
            return None
        return journal + grown + start_bytes

    def _undo_start(self, m: dict | None, start_mine: bool) -> int | None:
        """A failed first open leaves no start record behind: otherwise the
        flow would have a start but no session journal, which refuses every
        later count (stream_flow). Only before any journal was written.
        Review B-2: record_start can fail after its file landed (an fsync),
        so what is on disk decides, not whether record_start returned: a
        record naming this launch is removed exactly. Returns the bytes this
        open leaves in the start record, None when they cannot be measured."""
        if not start_mine or m is None:
            return 0
        try:
            with pipeline_store.Pipeline(self.base, m["task_id"], create=False) as p:
                try:
                    rec = p.start_record()
                    if rec is not None and rec["launch_id"] == m["launch_id"]:
                        p.remove_start(m["pipeline_id"], rec["started_at"], launch_id=m["launch_id"])
                except pipeline_store.StoreRefused as exc:
                    self._log(f"cannot undo the flow's start record: {exc}")
                return p.start_record_bytes()
        except (OSError, pipeline_store.StoreRefused) as exc:
            self._log(f"the flow's start record cannot be measured: {exc}")
            return None

    # ---- dispatch ----------------------------------------------------------------------

    def _stream_for(self, req: dict):
        launch_id = req.get("launch_id")
        if not (isinstance(launch_id, str) and agent_sessions.LAUNCH_RE.match(launch_id)):
            return None, "無效的 launch id"
        s = self._streams.get(launch_id)
        if s is None:
            return None, "這個串流 session 不在執行"
        if req.get("pipeline") != s.pipeline_id:
            return None, "請求的流程與 session 綁定的流程不同"
        d = req.get("dispatch_id")
        if not (isinstance(d, str) and sp.UUID_RE.match(d)):
            return None, "dispatch_id 必須是小寫 UUID"
        return s, None

    def _op_dispatch_prepare(self, rid: str, req: dict) -> dict:
        s, why = self._stream_for(req)
        if why:
            return _err(rid, "refused", why)
        d, text, approval = req["dispatch_id"], req.get("text"), req.get("approval")
        if not (isinstance(approval, dict) and set(approval) == {"kind", "id"}
                and approval["kind"] in ("preview", "automation")
                and isinstance(approval["id"], str) and _APPROVAL_ID.match(approval["id"])):
            return _err(rid, "bad_request", "approval 格式不符")
        try:
            if sp.sanitize(text) != text:
                return _err(rid, "bad_request", "文字必須是清洗後、與預覽相同的版本")
        except ValueError as exc:
            return _err(rid, "bad_request", str(exc))
        data = text.encode("utf-8")
        sha = sp.sha256_hex(data)
        existing = s.js.turns.get(d)
        if pipeline_store.is_held(self.base, s.pipeline_id):
            # Design 7 / v29.1: after a hold every dispatch RPC is refused,
            # an idempotent repeat included (part 2 review A-3); the status
            # is attached for the runner, which reads it with stream_status.
            return self._held(rid, s, d)
        if existing is not None:
            if existing.text_sha256 == sha and existing.length == len(data):
                refused = self._revalidate(rid, s, d)
                if refused:
                    return refused
                return _ok(rid, {"dispatch_id": d, "status": "writing" if s.writing == d else existing.status})
            return _err(rid, "refused", "這個 dispatch_id 已用於不同的內容")
        why = s.accepts_dispatch()
        if why:
            return _err(rid, "refused", why)
        if s.js.pending is not None:
            return _err(rid, "refused", "已有一則準備好但還沒送出的派工")
        try:
            ctx = stream_flow.load(self.base, s.pipeline_id)
            # A saved text without an acceptance already counts against the
            # limit (planner ruling R5 #2); sending the same id again completes
            # that dispatch (3.5) and adds none.
            stream_flow.check_limits(ctx, now=time.time(),
                                     counting_dispatch=d not in ctx.totals.pending_or_orphan_texts)
            if d in ctx.totals.accepted:
                return _err(rid, "refused", "這個 dispatch_id 已在流程中使用過")
            sp.dispatch_line(text, s.claude_session_id, d)
        except stream_flow.FlowRefused as exc:
            return _err(rid, "refused", f"{exc.code}: {exc}")
        except ValueError as exc:
            return _err(rid, "refused", str(exc))
        key = f"dispatch:{d}"
        why = self._reserve(key, quota.RESERVE_DISPATCH)
        if why:
            return _err(rid, "refused", why)
        written, before = 0, None
        try:
            with pipeline_store.Pipeline(self.base, s.task_id, create=True) as p:
                p.remove_partials()      # 3.5: a .partial was never accepted; a crash left it
                before = p.text_bytes(d)
                try:
                    p.write_text(d, data)
                    written = len(data)
                except FileExistsError:
                    # 3.5 recovery: the text was saved, the journal record was not.
                    saved = p.read_text(d)
                    if saved != data:
                        return _err(rid, "refused", "已有這則派工的全文，但內容不同（孤兒檔，交人工處理）")
        except (OSError, pipeline_store.StoreRefused) as exc:
            if before is not None:
                # Review B-1: a failed write may still have left the final
                # file (unlink of .partial or the directory sync failed) or a
                # .partial: count what is on disk; unknown -> the reservation,
                # and the ledger is marked over until rebuilt.
                written = self._text_added(s.task_id, d, before)
            return _err(rid, "refused", f"派工全文無法保存：{exc}")
        finally:
            self._ledger.release(key, written)
        if not s.record("dispatch_accepted", {"dispatch_id": d, "text_sha256": sha, "length": len(data),
                                              "approval": dict(approval)}):
            return _err(rid, "internal", "日誌無法寫入")
        return _ok(rid, {"dispatch_id": d, "status": "accepted"})

    def _op_stream_send(self, rid: str, req: dict) -> dict:
        s, why = self._stream_for(req)
        if why:
            return _err(rid, "refused", why)
        d = req["dispatch_id"]
        if pipeline_store.is_held(self.base, s.pipeline_id):
            return self._held(rid, s, d)                  # before any idempotent answer (A-3)
        turn = s.js.turns.get(d)
        if s.writing == d or (turn is not None and turn.status != "accepted"):
            refused = self._revalidate(rid, s, d)
            if refused:
                return refused
        if s.writing == d:
            return _ok(rid, {"dispatch_id": d, "status": "writing"})
        if turn is None:
            return _err(rid, "refused", "這則派工還沒有 prepare")
        if turn.status != "accepted":
            return _ok(rid, {"dispatch_id": d, "status": turn.status})         # idempotent (v29.2)
        why = s.accepts_dispatch()
        if why:
            return _err(rid, "refused", why)
        # This dispatch's own text first: a changed text stops the session
        # (3.5), before the flow's totals (which cross-check every text and
        # would only refuse this one request).
        try:
            with pipeline_store.Pipeline(self.base, s.task_id, create=False) as p:
                data = p.read_text(d)
            if sp.sha256_hex(data) != turn.text_sha256 or len(data) != turn.length:
                raise pipeline_store.StoreRefused("保存的全文與 prepare 時不同")
            text = data.decode("utf-8")
            line = sp.dispatch_line(text, s.claude_session_id, d)
        except (OSError, UnicodeDecodeError, ValueError, pipeline_store.StoreRefused) as exc:
            s.protocol_error("dispatch_file", str(exc))
            return _err(rid, "refused", f"保存的派工全文無法核對（{exc}），session 停止接受派工")
        try:
            ctx = stream_flow.load(self.base, s.pipeline_id)
            stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False)
        except stream_flow.FlowRefused as exc:
            return _err(rid, "refused", f"{exc.code}: {exc}")
        lim = ctx.limits
        if not s.start_write(d, text, line, time.monotonic(), turn_cap=lim["executor_turn_max_responses"],
                             total_cap=lim["executor_total_max_responses"],
                             turn_timeout=lim["executor_turn_timeout_min"] * 60.0):
            return _err(rid, "internal", "日誌無法寫入，這則派工沒有送出")
        self._register_stream(s, "stdin")
        return _ok(rid, {"dispatch_id": d, "status": "writing"})

    # ---- status, close, holds --------------------------------------------------------------

    def _op_stream_status(self, rid: str, req: dict) -> dict:
        launch_id = req.get("launch_id")
        if not (isinstance(launch_id, str) and agent_sessions.LAUNCH_RE.match(launch_id)):
            return _err(rid, "bad_request", "無效的 launch id")
        s = self._streams.get(launch_id)
        manifest_state = None
        write_failed = ""
        if s is not None and not s.journal_broken:
            js, state, problem = s.js, s.state, ""
        elif s is not None:
            # Part 2 review A-2: a failed append leaves the in-memory state
            # ahead of the disk, so it is not shown; the journal is read
            # back from the disk with this session's identity instead.
            write_failed = s.journal_broken
            try:
                fd = os.open(str(agent_sessions.launch_dir(self.base, launch_id)), _DIR)
                try:
                    res = stream_journal.read(fd, s.writer.state.identity)
                finally:
                    os.close(fd)
            except (OSError, agent_sessions.LaunchRefused) as exc:
                return _err(rid, "refused", f"無法讀取：{exc}")
            js, state, problem = res.state, s.state, res.problem
        else:
            try:
                m = agent_sessions._read_manifest(agent_sessions.launch_dir(self.base, launch_id), os.getuid())
                manifest_state = m.get("state")
                if m.get("engine") != "claude-stream":
                    return _err(rid, "refused", "不是串流 launch")
                fd = os.open(str(agent_sessions.launch_dir(self.base, launch_id)), _DIR)
                try:
                    res = stream_journal.read(fd, self._identity_for(m))
                finally:
                    os.close(fd)
            except (OSError, agent_sessions.LaunchRefused) as exc:
                return _err(rid, "refused", f"無法讀取：{exc}")
            js, state, problem = res.state, res.state.state, res.problem
        workdir = (s.cwd if s is not None else (m.get("canonical_workspace") if manifest_state else None))
        dispatches = []
        for d in js.order:
            t = js.turns[d]
            status = "writing" if s is not None and s.writing == d else t.status
            valid, reasons = (stream_journal.turn_validity(js, d, executor_report.problem)
                              if t.status == "ended" and not problem else (None, []))
            entry = {"dispatch_id": d, "status": status, "failed": t.failed, "times": dict(t.times),
                     "valid": valid, "reasons": reasons}
            if valid:
                # design 4: the executor's own words and VBear's file checks, apart
                report = t.result["structured_output"]
                entry["report"] = report
                entry["file_checks"] = (executor_report.verify(report, workdir) if isinstance(workdir, str)
                                        else ["不知道任務工作目錄"])
            dispatches.append(entry)
        return _ok(rid, {"launch_id": launch_id, "live": s is not None, "state": state,
                         "manifest_state": manifest_state, "journal_problem": problem,
                         "journal_write_failed": write_failed,
                         "dispatches": dispatches, "total_cost_usd": js.cost, "responses": js.responses,
                         # v29.7: what the flow's limits count; an unfinished
                         # dispatch has no result, so its cost is unknown and
                         # counted at the worst case
                         "counted_responses": js.counted_responses, "counted_cost_usd": js.counted_cost,
                         "unfinished": js.unfinished(), "recovered": js.recovered,
                         "num_turns": js.num_turns, "closed_reasons": list(js.closed_reasons), "exit": js.exit})

    def _revalidate(self, rid: str, s, d) -> dict | None:
        """Before an idempotent answer, the same checks as a new request:
        the flow's acceptance and its limits (part 2 review round 4 #3).
        Nothing is sent or created either way; a refusal carries the status."""
        try:
            ctx = stream_flow.load(self.base, s.pipeline_id)
            stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False)
        except stream_flow.FlowRefused as exc:
            r = _err(rid, "refused", f"{exc.code}: {exc}")
            r["error"]["dispatch_status"] = self._status_of(s, d)
            return r
        return None

    @staticmethod
    def _status_of(s, d):
        turn = s.js.turns.get(d) if isinstance(d, str) else None
        return "writing" if s.writing == d else (turn.status if turn is not None else None)

    def _held(self, rid: str, s, d) -> dict:
        turn = s.js.turns.get(d) if isinstance(d, str) else None
        status = "writing" if s.writing == d else (turn.status if turn is not None else None)
        r = _err(rid, "refused", "這個流程已停止")
        r["error"]["dispatch_status"] = status
        return r

    def _identity_for(self, m: dict) -> dict | None:
        """The identity an ended session's turns are judged against: its
        manifest and the flow's acceptance valid now. None (so no turn is
        valid) when either cannot be read."""
        from .. import acceptance, flows, login_identity
        try:
            flow = flows.read_only_snapshot(self.base).get(m.get("pipeline_id"))
            key = login_identity.load_login_key(self.base)
        except Exception:
            return None
        accepted = acceptance.latest_valid(flow, key.key_id) if flow else None
        return stream_journal.identity_from(m, accepted)

    def _op_stream_close(self, rid: str, req: dict) -> dict:
        s = self._streams.get(req.get("launch_id")) if isinstance(req.get("launch_id"), str) else None
        if s is None:
            return _err(rid, "refused", "這個串流 session 不在執行")
        s.terminate("使用者關閉")
        return _ok(rid, {"launch_id": s.launch_id, "closing": True})

    def _op_pipeline_hold(self, rid: str, req: dict) -> dict:
        reason = req.get("reason")
        if not isinstance(reason, str):
            return _err(rid, "bad_request", "停止原因必須是字串")
        try:
            pipeline_store.hold(self.base, req.get("pipeline"), reason)
        except (OSError, ValueError, pipeline_store.StoreRefused) as exc:
            return _err(rid, "refused", f"無法停止：{exc}")
        # Review jobs of the flow end here once they exist (S2b); a running
        # executor turn is not affected (design 7).
        return _ok(rid, {"pipeline": req["pipeline"], "held": True})

    def _op_pipeline_release(self, rid: str, req: dict) -> dict:
        """The user's "continue" (design 7, v29.8): the time is recorded in
        the daemon's own record first (open_stream compares failures with
        it), then the hold goes. A failed session must be closed before."""
        from .. import flows
        pipeline = req.get("pipeline")
        open_failed = [x.launch_id for x in self._streams.values()
                       if x.pipeline_id == pipeline and x.js.failures]
        if open_failed:
            return _err(rid, "refused", f"請先關閉失敗的 session（{', '.join(open_failed)}），再按「繼續」")
        try:
            flow = flows.read_only_snapshot(self.base).get(pipeline) if isinstance(pipeline, str) else None
        except Exception as exc:
            return _err(rid, "refused", f"無法讀取流程（{exc}）")
        if flow is None:
            return _err(rid, "refused", "找不到這個流程")
        try:
            current = stream_flow.failure_ids(self.base, pipeline, flow["task_id"])      # by identity
        except stream_flow.FlowRefused as exc:
            return _err(rid, "refused", f"無法核對流程的失敗（{exc}），不能繼續")
        key = f"release:{pipeline}"
        why = self._reserve(key, pipeline_store.RELEASE_FILE_MAX * 2)   # the record and its temp file
        if why:
            return _err(rid, "refused", why)
        before, written = None, 0
        release_warnings = []
        try:
            with pipeline_store.Pipeline(self.base, flow["task_id"], create=True) as p:
                before = p.release_record_bytes()
                previous = p.release_record(pipeline)
                resolved = set(current) | (previous["resolved"] if previous else set())
                try:
                    p.record_release(pipeline, time.time(), resolved)
                finally:
                    try:
                        written = max(0, p.release_record_bytes() - before)
                    except OSError:
                        written = None                       # unknown: the reservation, ledger over
            released = pipeline_store.release(self.base, pipeline, warnings=release_warnings)
        except (OSError, pipeline_store.StoreRefused) as exc:
            if before is None:
                written = 0
            return _err(rid, "refused", f"無法繼續：{exc}")
        finally:
            self._ledger.release(key, written)
        result = {"pipeline": pipeline, "held": False, "released": released}
        if release_warnings:
            result["warning"] = release_warnings[0]
        return _ok(rid, result)

    # ---- loop hooks ---------------------------------------------------------------------------

    def _register_stream(self, s, which: str) -> None:
        fd = {"stdin": s.stdin, "stdout": s.stdout, "stderr": s.stderr}[which]
        if which in s.registered:
            return
        events = selectors.EVENT_WRITE if which == "stdin" else selectors.EVENT_READ
        self._sel.register(fd, events, ("stream", s, which))
        s.registered.add(which)

    def _unregister_stream(self, s, which: str) -> None:
        if which not in s.registered:
            return
        fd = {"stdin": s.stdin, "stdout": s.stdout, "stderr": s.stderr}[which]
        try:
            self._sel.unregister(fd)
        except (KeyError, ValueError):
            pass
        s.registered.discard(which)

    def _stream_ready(self, s, which: str, now: float) -> None:
        try:
            if which == "stdout":
                s.on_stdout(now)
            elif which == "stderr":
                s.on_stderr(now)
            elif s.on_writable(now):
                self._unregister_stream(s, "stdin")
        except Exception as exc:
            self._stream_crashed(s, exc)

    def _session_room(self, rid: str) -> dict | None:
        """Review round 4 #1: a held leader is a process group VBear still
        answers for, so it counts toward the session limit; with too many,
        nothing new opens until a person has looked."""
        held = len(self._held_leaders)
        if held >= MAX_HELD_LEADERS:
            return _err(rid, "limit", f"有 {held} 個無法證明已結束的程序群組，需要人工處理後才能開啟新的 session")
        if len(self._sessions) + len(self._streams) + held >= self.max_sessions:
            return _err(rid, "limit", f"已達 session 上限（{self.max_sessions}，含 {held} 個待確認的程序群組）")
        return None

    def _hold_leader(self, proc, launch_id: str) -> None:
        """Keep the Popen object of a leader that may not be reaped (a
        dropped one would be reaped by the subprocess module)."""
        self._held_leaders.append({"proc": proc, "pid": proc.pid, "launch_id": launch_id})
        self._log(f"{launch_id}: leader {proc.pid} kept unreaped until its group is proven empty")

    def _recheck_held(self, now: float) -> None:
        """Reap a held leader once it has exited and its group is proven
        empty; until then (and at daemon exit) it stays as it is."""
        if not self._held_leaders or now < self._held_next:
            return
        self._held_next = now + HELD_RECHECK
        try:
            rows = proctrack.process_table()
        except proctrack.ProcessTableUnavailable:
            return
        for h in list(self._held_leaders):
            pid = h["pid"]
            if not stream_session.leader_exited(pid):
                continue
            if any(r["pgid"] == pid and "Z" not in r["stat"] for r in rows):
                continue
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            self._held_leaders.remove(h)
            self._log(f"{h['launch_id']}: group of leader {pid} proven empty, leader reaped")

    def _hold_for_failure(self, pipeline_id: str, launch_id: str, why: str) -> None:
        """v29.8: any failure holds the flow (reason "failure"). If the hold
        cannot be written, open_stream still refuses: it recomputes the
        failures from the journals."""
        try:
            pipeline_store.hold(self.base, pipeline_id, f"failure: session {launch_id}: {why}")
            self._log(f"{launch_id}: flow {pipeline_id} held after a failure: {why}")
        except Exception as exc:          # e.g. ValueError from sanitize: never out of the event loop
            try:
                self._log(f"{launch_id}: cannot hold flow {pipeline_id} after a failure ({type(exc).__name__})")
            except Exception:
                pass

    def _check_failure(self, s) -> None:
        if not getattr(s, "failure_held", False) and s.js.failures:
            s.failure_held = True
            self._hold_for_failure(s.pipeline_id, s.launch_id, s.js.failures[-1][0])

    def _stream_tick(self, now: float) -> None:
        try:
            self._recheck_held(now)
        except Exception as exc:
            self._log(f"held leader recheck failed: {type(exc).__name__}")
        for s in list(self._streams.values()):
            if self._streams.get(s.launch_id) is not s:
                continue                          # given up earlier in this pass
            try:
                s.tick(now)
                self._check_failure(s)
                if s.writing is None:
                    self._unregister_stream(s, "stdin")
                if s.stdout_eof:
                    self._unregister_stream(s, "stdout")
                if s.stderr_eof:
                    self._unregister_stream(s, "stderr")
                if s.finished:
                    self._finish_stream(s)
            except Exception as exc:
                self._stream_crashed(s, exc)

    def _stream_crashed(self, s, exc: Exception) -> None:
        """The outer guard of every per-session step in the event loop (tick,
        pipe I/O, end-of-session clean-up; Claude review finding 4): an
        unexpected exception never leaves the loop. The session is in error
        (a protocol_error "internal_error" when the journal still takes one,
        so the failure has its (launch, seq) identity), the flow is held, and
        the session is given up to manual review without a signal and with
        its leader kept unreaped (design 5.8). It always leaves _streams, so
        the same exception cannot repeat on every pass."""
        why = f"管理 session 時發生未預期的錯誤（{type(exc).__name__}）"
        for step in (lambda: self._log(f"{s.launch_id}: {why}"),
                     lambda: s.protocol_error("internal_error", type(exc).__name__),
                     lambda: setattr(s, "failure_held", True),
                     lambda: self._hold_for_failure(s.pipeline_id, s.launch_id, why),
                     lambda: s._abandon(f"{why}，交人工處理") if not s.finished else None):
            try:
                step()
            except Exception:
                pass
        try:
            self._finish_stream(s)
        except Exception:
            # The usual clean-up failed too: do the minimum by hand.
            for step in (lambda: [self._unregister_stream(s, w) for w in list(s.registered)],
                         lambda: agent_sessions._retain(self.base, s.launch_id, why),
                         # not a leader the normal clean-up already reaped
                         lambda: self._hold_leader(s.proc, s.launch_id)
                         if not s.reaped and (not isinstance(s.outcome, dict)
                                              or s.outcome.get("leader_held", True)) else None):
                try:
                    step()
                except Exception:
                    pass
            self._streams.pop(s.launch_id, None)

    def _finish_stream(self, s) -> None:
        for which in list(s.registered):
            self._unregister_stream(s, which)
        # The manifest is final and the quota released before the session
        # leaves _streams: a session no longer tracked here is never left
        # "running" on disk (a crash in between is recovered like any other).
        # A finished session always has an outcome; if not, nothing proves
        # it ended cleanly, so it is kept for a person, not cleaned up.
        outcome = s.outcome if isinstance(s.outcome, dict) else {"manual_review": "session 結束時沒有留下結果",
                                                                                  "leader_held": not s.reaped}
        if s.journal_broken and not outcome.get("manual_review"):
            # The journal stops mid-session: what it shows is not how the
            # session ended. Keep everything for a person to look at.
            outcome["manual_review"] = f"日誌無法寫入，session 已結束（{s.journal_broken[:200]}）"
        if outcome.get("manual_review"):
            agent_sessions._retain(self.base, s.launch_id, outcome["manual_review"])
            self._log(f"{s.sid}: retained for manual review: {outcome['manual_review']}")
        else:
            result = agent_sessions.cleanup_launch(self.base, s.launch_id, proven_dead=True)
            self._log(f"{s.sid}: stream session ended ({'cleaned' if result.get('cleaned') else result})")
        if outcome.get("leader_held"):
            self._hold_leader(s.proc, s.launch_id)
        self._check_failure(s)
        if not getattr(s, "failure_held", False) and (outcome.get("manual_review") or s.js.unfinished()):
            s.failure_held = True
            self._hold_for_failure(s.pipeline_id, s.launch_id,
                                   outcome.get("manual_review") or "回合沒有結果，以最壞情況計入")
        manifest_before, start_bytes = getattr(s, "quota_base", (0, 0))
        self._ledger.release(f"session:{s.launch_id}",
                             self._session_bytes(s.manifest, manifest_before, start_bytes))
        self._streams.pop(s.launch_id, None)

    def _kill_all_streams(self) -> None:
        """Daemon shutdown: nobody could manage these afterwards."""
        streams = list(self._streams.values())
        for s in streams:
            try:
                s.terminate("背景程序關閉")
            except Exception as exc:
                self._stream_crashed(s, exc)
        streams = [s for s in streams if s.launch_id in self._streams]
        deadline = time.monotonic() + stream_session.TERM_GRACE + stream_session.KILL_GRACE + 2.0
        while streams and time.monotonic() < deadline:
            for s in streams:
                try:
                    for which in ("stdout", "stderr"):
                        if which in s.registered:
                            getattr(s, "on_" + which)(time.monotonic())
                    s.tick(time.monotonic())
                    if s.finished:
                        self._finish_stream(s)
                except Exception as exc:
                    self._stream_crashed(s, exc)          # leaves _streams, kept for review
            streams = [s for s in streams if not s.finished and s.launch_id in self._streams]
            time.sleep(0.05)
        for s in streams:
            try:
                s._killpg(signal.SIGKILL)
            except Exception:
                pass                              # no proven identity: nothing is sent; kept for review below
            self._log(f"{s.sid}: still running at shutdown; launch kept for manual review")
            try:
                agent_sessions._retain(self.base, s.launch_id, "背景程序關閉時程序未能證明已結束")
            except Exception:
                pass
            try:
                s.failure_held = True
                self._hold_for_failure(s.pipeline_id, s.launch_id, "背景程序關閉時程序未能證明已結束")
            except Exception as exc:
                self._log(f"{s.launch_id}: failed to hold flow during shutdown ({type(exc).__name__})")
            self._hold_leader(s.proc, s.launch_id)       # keep Popen alive; its destructor may reap the leader
            self._streams.pop(s.launch_id, None)
