"""What flows keep on disk, and deleting a flow (design 9, S2c-5).

The data (sessions, reviews, the flow's directory, its stop marker) is the
daemon's: it alone writes it, so it alone removes it (RPC ``flow_delete``,
which re-checks everything this module checked for the screen). This module
is the console's side: the sizes and the reasons shown to the person, and
the one thing the daemon cannot do, removing the flow's own record from
flows.json after the data is gone.

Nothing is deleted without the request naming the flow it is for; the screen
asks twice. A flow that never started has no data and needs no daemon.
"""

from __future__ import annotations

import os
import re

from . import config as cfg, flows
from .api_error import ApiError
from .daemon_client import DaemonError
from .flow_executor import FlowExecutor, _daemon
from . import daemon_client
from .runtime import flow_data, quota

DELETE_TIMEOUT_S = 120.0       # a flow may hold several hundred MiB


class FlowStorage:
    def __init__(self, executor: FlowExecutor):
        self.executor = executor

    # ---- the way out of a deletion that stopped after the record went -----------------------------------------

    def finish_orphans(self) -> list[str]:
        """Deletion markers (<state>/deleting/<flow>) of flows whose record is already gone: the daemon is asked to
        remove them (flow_delete_done), once and best-effort, whenever the list is read, a delete names such a flow,
        or the console starts. A marker that is not empty is left for a person (the daemon says so)."""
        base = cfg.state_dir()
        try:
            names = os.listdir(base / "deleting")
        except OSError:
            return []
        known = {f["id"] for f in flows.list_flows()}
        done = []
        for name in names:
            if name in known or not re.match(r"^flow-[0-9a-f]{12}\Z", name):
                continue
            try:
                daemon_client.call(self.executor.runtime, "flow_delete_done", timeout=10.0, pipeline=name)
                done.append(name)
            except DaemonError:
                pass
        return done

    # ---- what is kept ---------------------------------------------------------------------------------------

    def usage(self) -> dict:
        """The quota and, per flow, what it keeps and whether it can go now.
        Read-only. A flow whose data cannot be attributed is listed with the
        reason and no size, never skipped."""
        base = cfg.state_dir()
        self.finish_orphans()
        try:
            used, problem = quota.scan(base), ""
        except quota.ScanFailed as exc:
            used, problem = None, f"額度無法核算，需要人工檢查（{exc}）"
        items = []
        everyone = {f["id"]: f for f in flows.list_flows()}
        for flow in everyone.values():
            item = {"flow_id": flow["id"], "task_id": flow["task_id"], "created_at": flow.get("created_at"),
                    "bytes": None, "sessions": 0, "reviews": 0, "has_data": False, "held": False,
                    "deleting": False, "deletable": False, "reasons": []}
            try:
                pl = flow_data.plan(base, flow["id"], flow["task_id"], flows=everyone)
            except flow_data.FlowDataRefused as exc:
                item["reasons"] = [str(exc)]
                items.append(item)
                continue
            why = flow_data.blockers(pl)
            item.update({"bytes": pl.total_bytes, "sessions": len(pl.sessions), "reviews": len(pl.reviews),
                         "has_data": bool(pl.sessions or pl.reviews or pl.pipeline_dir or pl.held or pl.deleting),
                         "held": pl.held, "deleting": pl.deleting, "deletable": not why, "reasons": why})
            items.append(item)
        items.sort(key=lambda x: (-(x["bytes"] or 0), x["flow_id"]))
        return {"limit_bytes": quota.HARD_LIMIT, "used_bytes": used, "problem": problem, "flows": items,
                "note": "只有沒有程序在執行、也沒有等待人工處理（manual_review）的流程才能刪除。"}

    # ---- deleting a flow ---------------------------------------------------------------------------------------

    def delete(self, flow_id: str, body) -> dict:
        ex = self.executor
        try:
            flow = ex._flow(flow_id)
        except ApiError as exc:
            # The record is already gone. If its deletion marker is still there, finishing it IS the deletion
            # (the way out of a deletion that stopped between the record and the marker).
            if exc.code == "no_flow" and isinstance(body, dict) and body == {"flow_id": flow_id} \
                    and (cfg.state_dir() / "deleting" / flow_id).exists():
                try:
                    daemon_client.call(ex.runtime, "flow_delete_done", timeout=30.0, pipeline=flow_id)
                except DaemonError as exc2:
                    raise _daemon(exc2) from exc2
                return {"deleted": flow_id, "bytes": 0, "removed": None, "marker_finished": True}
            raise
        if not isinstance(body, dict) or set(body) != {"flow_id"} or body.get("flow_id") != flow_id:
            raise ApiError(400, "bad_request", "刪除必須指名這個流程：{\"flow_id\": \"<流程 id>\"}")
        base = cfg.state_dir()
        with ex._lock(flow_id):
            try:
                pl = flow_data.plan(base, flow_id, flow["task_id"], flows={f["id"]: f for f in flows.list_flows()})
            except flow_data.FlowDataRefused as exc:
                raise ApiError(409, "not_deletable", f"不能刪除：{exc}") from exc
            why = flow_data.blockers(pl)
            if why:
                raise ApiError(409, "not_deletable", "不能刪除：" + "；".join(why[:6]), reasons=why)
            removed = None
            if (pl.sessions or pl.reviews or pl.pipeline_dir or pl.held or pl.deleting or pl.auto
                    or pl.automation_inode is not None):
                try:
                    res = daemon_client.call(ex.runtime, "flow_delete", timeout=DELETE_TIMEOUT_S, pipeline=flow_id)
                except DaemonError as exc:
                    raise _daemon(exc) from exc
                removed = res.get("removed")
            try:
                flows.delete_flow(flow_id)
            except KeyError:
                pass                                           # already gone: the answer is the same
            except Exception as exc:
                raise ApiError(500, "internal",
                               f"流程的資料已刪除，但流程紀錄無法移除（{type(exc).__name__}）；再按一次即可完成") from exc
            if removed is not None or pl.deleting:
                # the record is gone: the deletion marker (which kept anything new out until now) may go. A
                # failure here leaves an empty marker the daemon sweeps at its next start; nothing depends on it.
                try:
                    daemon_client.call(ex.runtime, "flow_delete_done", timeout=30.0, pipeline=flow_id)
                except DaemonError:
                    pass
        return {"deleted": flow_id, "bytes": pl.total_bytes, "removed": removed}
