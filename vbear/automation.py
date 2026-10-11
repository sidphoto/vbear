"""Turning automatic mode on and off from the console (S3 design 2, 9; v11.1).

``preview`` gathers the same facts as a risk acceptance, builds the plan text
from the task card, and stores both in one server-held preview record
(kind "automation"; one use, five minutes). ``confirm`` takes only its id:

  1. the facts are looked at again (a changed account, version, key or text
     voids the preview) and the flow is still manual, running, with a task;
  2. the preview is consumed;
  3. plan.txt is written (<state>/automation/<flow>/, 0600, atomic) with
     exactly the text the screen showed;
  4. the acceptance is recorded: the nine S2 fields plus auto_text_version,
     automation_scope, plan_sha256 and plan_bytes, in ONE event, which is the
     plan approval and the risk acceptance (v11.1 G1);
  5. the daemon is asked for ``pipeline_mode_set auto`` with the approval id
     ``auto-<seq of that event>``; it re-verifies everything;
  6. the console records ``automation_mode``.

A failure between the steps leaves nothing that runs: without step 5 the
flow is manual, and plan.txt of an older approval is replaced only by a whole
new one. Switching back (``disable``) works only on a stopped flow, as the
daemon requires.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import stat
import time
from pathlib import Path

from . import acceptance, config as cfg, flows, login_identity, previews, risk_acceptance, risk_text, tasks
from .api_error import ApiError
from .flow_executor import FlowExecutor
from .runtime import codex_constants, pipeline_store
from .runtime import stream_protocol as sp

AUTO_DEFAULT_LIMITS = {**acceptance.DEFAULT_LIMITS, "max_elapsed_h": 4}      # S3 design 4: 4 hours prefilled
PLAN_FILE = "plan.txt"
LOCK_FILE = ".lock"
LOCK_WAIT_S = 15.0
FIXED_RULES = ("連續失敗 1 次就停止（不能調整）",)
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


# ---- the plan text and its file --------------------------------------------------------------------------

def build_plan_text(task: dict) -> str:
    """The plan, from the task card: title, goal, scope, out of scope,
    deliverables, acceptance criteria, evidence. Control characters are made
    visible (the same sanitising a dispatch gets) so the file holds exactly
    what could be sent."""
    def lines(name: str, items) -> list[str]:
        if not isinstance(items, list) or not items:
            return []
        return [f"{name}：", *[f"- {str(x)}" for x in items if isinstance(x, (str, int, float)) and str(x).strip()]]

    parts = [f"任務：{task.get('title', '')}"]
    goal = task.get("goal")
    if isinstance(goal, str) and goal.strip():
        parts.append(f"目標：{goal.strip()}")
    for name, key in (("範圍", "scope"), ("不在範圍", "out_of_scope"), ("交付物", "deliverables"),
                      ("驗收條件", "acceptance_criteria"), ("證據", "evidence")):
        parts += lines(name, task.get(key))
    try:
        return sp.sanitize("\n".join(parts))
    except ValueError as exc:
        raise ApiError(409, "bad_plan", f"任務卡的內容無法形成計畫：{exc}") from exc


def _plan_dir(state, flow_id: str, *, create: bool) -> int:
    """A descriptor on <state>/automation/<flow>/ (private, ours)."""
    sfd = os.open(str(state), _DIR)
    try:
        for name, mode in (("automation", 0o700), (flow_id, 0o700)):
            if create:
                try:
                    os.mkdir(name, mode, dir_fd=sfd)
                except FileExistsError:
                    pass
            nfd = os.open(name, _DIR, dir_fd=sfd)
            os.close(sfd)
            sfd = nfd
            st = os.fstat(sfd)
            if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise ApiError(500, "plan_dir", f"{name} 不是目前使用者私有的資料夾")
        return sfd
    except BaseException:
        os.close(sfd)
        raise


def _lock_is_current(state, flow_id: str, fd: int) -> bool:
    """After flock: the file we hold is still the one at the path (a deletion
    may have moved its directory away while we waited, and then we hold a lock
    on a file nobody else will ever look at)."""
    try:
        dfd = _plan_dir(state, flow_id, create=False)
    except OSError:
        return False
    try:
        try:
            now = os.stat(LOCK_FILE, dir_fd=dfd, follow_symlinks=False)
        except OSError:
            return False
        mine = os.fstat(fd)
        return (now.st_dev, now.st_ino) == (mine.st_dev, mine.st_ino)
    finally:
        os.close(dfd)


HELD, BUSY, UNAVAILABLE = "held", "busy", "unavailable"


@contextlib.contextmanager
def try_plan_lock(state, flow_id: str):
    """The same lock taken without waiting. Yields (HELD, ""): we hold it, and
    what is read under it is what no approval can be changing; (BUSY, ""):
    an approval holds it (only EWOULDBLOCK/EAGAIN mean this); (UNAVAILABLE,
    why): there is no lock file or directory, it cannot be opened, or it is
    not a plain file of ours. Only BUSY is ever waited for."""
    try:
        dfd = _plan_dir(state, flow_id, create=False)
    except FileNotFoundError:
        yield UNAVAILABLE, "核准用的資料夾不存在"
        return
    except (OSError, ApiError) as exc:
        yield UNAVAILABLE, f"核准用的資料夾無法開啟（{getattr(exc, 'strerror', None) or exc}）"
        return
    try:
        try:
            fd = os.open(LOCK_FILE, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        except OSError as exc:
            fd = None
            why = f"核准用的鎖檔無法開啟（{exc.strerror}）"
    finally:
        os.close(dfd)
    if fd is None:
        yield UNAVAILABLE, why
        return
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
            yield UNAVAILABLE, "核准用的鎖檔不是本人的一般檔案"
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            import errno
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                yield BUSY, ""
            else:
                yield UNAVAILABLE, f"核准用的鎖無法取得（{exc.strerror}）"
            return
        if not _lock_is_current(state, flow_id, fd):
            yield UNAVAILABLE, "核准用的鎖檔已被替換或搬走"
            return
        yield HELD, ""
    finally:
        os.close(fd)


@contextlib.contextmanager
def plan_lock(state, flow_id: str):
    """The cross-process lock of this flow's approval (v11.1 / S3-2 review): the
    plan file, the acceptance event and the daemon's mode switch of one
    approval are done as one unit, so two consoles confirming two previews
    cannot interleave and leave a plan that is not the one the mode is bound
    to. flock on automation/<flow>/.lock."""
    # nothing is created for a flow that is going away: look first, then create, then (below) look again under the lock
    if pipeline_store.deleting_exists(state, flow_id):
        raise ApiError(409, "deleting", "這個流程正在刪除，不能開啟自動執行")
    try:
        flows.get_flow(flow_id)
    except KeyError:
        raise ApiError(404, "no_flow", "找不到這個流程") from None
    existed = (Path(str(state)) / "automation" / flow_id).exists()
    dfd = _plan_dir(state, flow_id, create=True)
    try:
        fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
    finally:
        os.close(dfd)

    def forget_what_we_made():
        """Refused after we had created the directory and the lock file (the flow was deleted meanwhile): remove
        them again, but only what this call made and only while nothing else is in the directory."""
        if existed:
            return
        try:
            d = _plan_dir(state, flow_id, create=False)
        except (OSError, ApiError):
            return
        try:
            if os.listdir(d) == [LOCK_FILE]:
                os.unlink(LOCK_FILE, dir_fd=d)
                os.close(d)
                d = -1
                parent = os.open(str(Path(str(state)) / "automation"), _DIR)
                try:
                    os.rmdir(flow_id, dir_fd=parent)
                finally:
                    os.close(parent)
        except OSError:
            pass
        finally:
            if d >= 0:
                os.close(d)
    try:
        end = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise ApiError(409, "busy", "另一個主控台正在核准這個流程的自動執行，請稍後再試") from None
                time.sleep(0.05)
        # The standard flock discipline: what we hold must still be what the path names, and the flow must still
        # exist and not be on its way out (a deletion that took the directory while we waited).
        if not _lock_is_current(state, flow_id, fd):
            raise ApiError(409, "deleting", "這個流程的資料夾已被搬走或正在刪除，不能開啟自動執行")
        if pipeline_store.deleting_exists(state, flow_id):
            forget_what_we_made()
            raise ApiError(409, "deleting", "這個流程正在刪除，不能開啟自動執行")
        try:
            flows.get_flow(flow_id)
        except KeyError:
            forget_what_we_made()
            raise ApiError(404, "no_flow", "找不到這個流程") from None
        yield
    finally:
        os.close(fd)                                   # closing releases the flock


def stage_plan(state, flow_id: str, text: str) -> None:
    """The new plan in a temp file (fsynced), not yet the plan: publish_plan
    renames it into place once the acceptance that names it is recorded."""
    data = text.encode("utf-8")
    dfd = _plan_dir(state, flow_id, create=True)
    try:
        tmp = f".{PLAN_FILE}.tmp"
        try:
            os.unlink(tmp, dir_fd=dfd)
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def publish_plan(state, flow_id: str) -> None:
    dfd = _plan_dir(state, flow_id, create=False)
    try:
        os.replace(f".{PLAN_FILE}.tmp", PLAN_FILE, src_dir_fd=dfd, dst_dir_fd=dfd)
        os.fsync(dfd)
    finally:
        os.close(dfd)


def discard_staged_plan(state, flow_id: str) -> None:
    try:
        dfd = _plan_dir(state, flow_id, create=False)
    except OSError:
        return
    try:
        try:
            os.unlink(f".{PLAN_FILE}.tmp", dir_fd=dfd)
        except FileNotFoundError:
            pass
    finally:
        os.close(dfd)


def write_plan(state, flow_id: str, text: str) -> None:
    """plan.txt, whole or not at all (stage + publish)."""
    stage_plan(state, flow_id, text)
    publish_plan(state, flow_id)


def events_needed(limits: dict) -> int:
    """How many events one approved run can write at most: per dispatch an
    intent, a sent and a report; per review an intent, a started, a result and
    maybe an aborted; the acceptance and the mode; some stops (each of which
    the user has to end). With the caps (40 dispatches, 10 reviews) that is
    40*3 + 10*4 + 2 + 20 = 182; flows allow 500."""
    return limits["max_dispatches"] * 3 + limits["max_reviews"] * 4 + 2 + 20

def read_plan(state, flow_id: str, *, sha256: str, size: int) -> str:
    """The approved plan text; ApiError (409) when the file is missing, not a
    plain file of ours, not the size or hash the acceptance recorded."""
    try:
        dfd = _plan_dir(state, flow_id, create=False)
    except FileNotFoundError:
        raise ApiError(409, "plan_missing", "找不到核准時保存的計畫文字（plan.txt）") from None
    except OSError as exc:
        raise ApiError(409, "plan_missing", f"計畫文字無法讀取（{exc.strerror}）") from exc
    try:
        try:
            fd = os.open(PLAN_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        except OSError as exc:
            raise ApiError(409, "plan_missing", f"找不到核准時保存的計畫文字（{exc.strerror}）") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_size > acceptance.PLAN_MAX_BYTES:
                raise ApiError(409, "plan_changed", "plan.txt 不是核准時寫入的一般檔案")
            data = b""
            while len(data) <= acceptance.PLAN_MAX_BYTES:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(fd)
    finally:
        os.close(dfd)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise ApiError(409, "plan_changed", "plan.txt 與核准時記錄的雜湊不符，計畫文字已被改動")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(409, "plan_changed", "plan.txt 不是合法的 UTF-8") from exc


# ---- the service -----------------------------------------------------------------------------------------

class FlowAutomation:
    def __init__(self, executor: FlowExecutor, store: previews.PreviewStore, host=None):
        self.executor = executor
        self.store = store
        self.host = host

    # -- read model -------------------------------------------------------------------------------------

    def status(self, flow_id: str) -> dict:
        """The flow's mode, and when it is auto what it was approved with."""
        flow = self.executor._flow(flow_id)
        base = cfg.state_dir()
        info = pipeline_store.mode_info(base, flow_id)
        out = {"flow_id": flow_id, "mode": info["mode"], "approval_id": info["approval_id"],
               "problem": info["problem"], "since": info["at"], "approval": None, "step": None}
        if info["mode"] == "auto":
            from . import runner as runner_mod                    # (runner imports this module)
            hold = pipeline_store.hold_info(base, flow_id)
            out["step"] = {**runner_mod.describe(flow.get("events") or []), "held": hold["held"],
                           "hold_reason": hold["reason"]}
        seq = acceptance.approval_seq(info["approval_id"]) if info["approval_id"] else None
        events = flow.get("events") or []
        if seq is not None and 1 <= seq <= len(events):
            ev = events[seq - 1]
            if acceptance.is_auto_event(ev):
                out["approval"] = {"seq": seq, "at": ev.get("at"), "auto_text_version": ev.get("auto_text_version"),
                                   "plan_sha256": ev.get("plan_sha256"), "plan_bytes": ev.get("plan_bytes"),
                                   "limits": ev.get("limits")}
        return out

    # -- preview and confirm ------------------------------------------------------------------------------

    def _preconditions(self, flow: dict) -> dict:
        """The task card, when this flow may be offered automatic mode now."""
        if pipeline_store.mode_info(cfg.state_dir(), flow["id"])["mode"] != "manual":
            raise ApiError(409, "already_auto", "這個流程已經是自動執行模式")
        hold = pipeline_store.hold_info(cfg.state_dir(), flow["id"])
        if hold["held"]:
            raise ApiError(409, "held", f"這個流程已停止（{hold['reason']}），要先按「繼續」")
        try:
            task = tasks.get_task(flow["task_id"])
        except tasks.TaskStorageError as exc:
            raise ApiError(409, "no_task", f"任務卡無法讀取（{exc}）") from exc
        if task is None:
            raise ApiError(409, "no_task", "找不到這個流程的任務卡")
        return task

    def preview(self, flow_id: str, body) -> dict:
        host = self.host or risk_acceptance.DEFAULT_HOST
        if body is None:
            body = {}
        if not isinstance(body, dict) or set(body) - risk_acceptance.PREVIEW_KEYS:
            raise ApiError(400, "bad_request", "只接受 executor_model、review_model、limits")
        with self.executor._lock(flow_id):
            flow = self.executor._flow(flow_id)
            risk_acceptance._check_families(flow)
            task = self._preconditions(flow)
            plan = build_plan_text(task)
            raw = plan.encode("utf-8")
            if not 0 < len(raw) <= acceptance.PLAN_MAX_BYTES:
                raise ApiError(409, "bad_plan", f"計畫文字必須是 1 到 {acceptance.PLAN_MAX_BYTES} bytes（目前 {len(raw)}）")
            state = cfg.state_dir()
            key = risk_acceptance._key(state)
            over = body.get("limits")
            limits = dict(AUTO_DEFAULT_LIMITS)
            if over is not None:
                if not isinstance(over, dict):
                    raise ApiError(400, "bad_limits", "limits 必須是物件")
                unknown = set(over) - set(acceptance.LIMITS)
                if unknown:
                    raise ApiError(400, "bad_limits", "不認得的上限欄位：" + "、".join(sorted(map(str, unknown))))
                limits.update(over)
            problem = acceptance.limits_problem(limits)
            if problem:
                raise ApiError(400, "bad_limits", f"上限不合法（{problem}）")
            room = flows.MAX_EVENTS - len(flow["events"])
            if room < events_needed(limits):
                raise ApiError(409, "no_event_room",
                               f"這個流程的事件紀錄剩 {room} 筆，這組上限最多可能寫 {events_needed(limits)} 筆，"
                               "不足以安全地自動執行（調低派工則數或審查次數，或改用手動）")
            values = risk_acceptance._gather(host, state, key,
                                             body.get("executor_model", risk_acceptance.DEFAULT_EXECUTOR_MODEL),
                                             body.get("review_model", risk_acceptance.DEFAULT_REVIEW_MODEL))
            fields = {**values, "limits": limits, "auto_text_version": acceptance.AUTO_RISK_TEXT_VERSION,
                      "automation_scope": list(acceptance.AUTO_SCOPE),
                      "plan_sha256": hashlib.sha256(raw).hexdigest(), "plan_bytes": len(raw)}
            problem = acceptance.record_problem(fields)
            if problem:
                raise ApiError(500, "internal", f"接受內容不合法（{problem}）")
            try:
                rec = self.store.create("automation", flow_id, {"fields": fields, "plan_text": plan})
            except previews.PreviewError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
        shown = risk_acceptance._display({k: fields[k] for k in acceptance.FIELDS})
        return {"preview_id": rec["preview_id"], "expires_at": rec["expires"], "ttl_s": previews.TTL,
                "plan_text": plan, "plan_sha256": fields["plan_sha256"], "plan_bytes": fields["plan_bytes"],
                "risk_text": {"zh": risk_text.render("zh"), "en": risk_text.render("en")},
                "auto_text": {"zh": risk_text.render_auto("zh"), "en": risk_text.render_auto("en")},
                "fixed_rules": list(FIXED_RULES), "values": shown,
                "suggested_executor_models": list(risk_acceptance.SUGGESTED_EXECUTOR_MODELS),
                "review_models": sorted(codex_constants.VERSIONS[fields["codex_version"]].models)}

    def confirm(self, flow_id: str, body) -> dict:
        host = self.host or risk_acceptance.DEFAULT_HOST
        if not isinstance(body, dict) or set(body) != {"preview_id"}:
            raise ApiError(400, "bad_request", "只接受 preview_id；計畫與接受的值一律取自預覽紀錄")
        with self.executor._lock(flow_id):
            flow = self.executor._flow(flow_id)
            state = cfg.state_dir()

            def check(rec: dict) -> None:
                stored = rec["data"]["fields"]
                try:
                    risk_acceptance._check_families(self.executor._flow(flow_id))
                    self._preconditions(self.executor._flow(flow_id))
                    key = login_identity.load_login_key(state)
                    now = risk_acceptance._gather(host, state, key, stored["executor_model"], stored["model"])
                except (ApiError, login_identity.KeyUnavailable) as exc:
                    raise previews.PreviewError("conflict", f"預覽之後的情況已改變（{exc}），請重新預覽") from exc
                changed = [name for name in now if now[name] != stored[name]]
                if changed:
                    raise previews.PreviewError("conflict", "預覽之後下列內容已改變，請重新預覽：" + "、".join(sorted(changed)))
                problem = acceptance.record_problem(stored)
                if problem or not acceptance.AUTO_FIELDS <= set(stored):
                    raise previews.PreviewError("invalid", f"預覽內容不合法（{problem or '沒有自動執行的欄位'}）")

            try:
                rec = self.store.consume(body["preview_id"], kind="automation", flow_id=flow_id, check=check)
            except previews.PreviewError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            fields, plan = rec["data"]["fields"], rec["data"]["plan_text"]
            # One unit across processes: the plan file, the acceptance that names its hash, and the daemon's
            # mode switch (which reads the file again). Two consoles cannot interleave their approvals.
            with plan_lock(state, flow_id):
                # a deletion that began while the preview was open (it asked for this lock first and did not get
                # it, or began just before): nothing is written into a flow that is going away
                if pipeline_store.deleting_exists(state, flow_id):
                    raise ApiError(409, "deleting", "這個流程正在刪除，不能開啟自動執行")
                try:
                    stage_plan(state, flow_id, plan)
                except OSError as exc:
                    raise ApiError(500, "plan_write", f"計畫文字無法保存（{exc.strerror}）") from exc
                try:
                    flows.append_risk_acknowledged(flow_id, fields)
                except ValueError as exc:
                    discard_staged_plan(state, flow_id)
                    raise ApiError(409, "event_write", f"接受無法記錄：{exc}") from exc
                except KeyError:
                    discard_staged_plan(state, flow_id)
                    raise ApiError(404, "no_flow", "找不到這個流程") from None
                try:
                    publish_plan(state, flow_id)
                except OSError as exc:
                    raise ApiError(500, "plan_write", f"計畫文字無法保存（{exc.strerror}）；沒有開啟自動執行") from exc
                events = flows.get_flow(flow_id)["events"]
                seq = events[-1]["seq"]
                approval = {"kind": "automation", "id": acceptance.approval_id(events[-1])}
                self.executor._call("pipeline_mode_set", pipeline=flow_id, mode="auto", approval=approval)
                try:
                    flows.append_automation_event(flow_id, "automation_mode", {"mode": "auto", "approval_seq": seq})
                except Exception as exc:                  # any failure: on but not on the record is never a success
                    held = True
                    try:
                        self.executor._call("pipeline_hold", pipeline=flow_id,
                                            reason=f"自動執行的開啟無法記錄（{type(exc).__name__}）")
                    except Exception:
                        held = False
                    if held:
                        raise ApiError(500, "event_write", f"自動執行已開啟但無法寫入事件紀錄（{exc}），流程已停止，"
                                       "請切回手動後處理") from exc
                    raise ApiError(500, "event_write_not_stopped",
                                   f"自動執行已開啟但無法寫入事件紀錄（{exc}），而且無法要求停止：流程可能仍在自動模式，"
                                   "請立刻按「停止流程」") from exc
            return {"mode": "auto", "approval_id": approval["id"], "approval_seq": seq,
                    "plan_sha256": fields["plan_sha256"], "plan_bytes": fields["plan_bytes"]}

    # -- switching back -------------------------------------------------------------------------------------

    def disable(self, flow_id: str, body) -> dict:
        if body not in (None, {}):
            raise ApiError(400, "bad_request", "不接受任何欄位")
        with self.executor._lock(flow_id):
            self.executor._flow(flow_id)
            self.executor._call("pipeline_mode_set", pipeline=flow_id, mode="manual", approval=None)
            result = {"mode": "manual", "event_written": True}
            try:
                flows.append_automation_event(flow_id, "automation_mode", {"mode": "manual", "approval_seq": None})
            except Exception as exc:
                result.update(event_written=False, event_problem=f"模式已切回手動，但事件無法記錄（{exc}）")
            return result
