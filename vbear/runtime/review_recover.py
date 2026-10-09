"""Review jobs a previous daemon left behind (design 5.3, 5.8, v29.9), judged
when the daemon starts. Nothing is ever signalled here.

  prepared        no process was ever started: the review was cut short, so it
                  is invalid (a v29.8 failure), judged without any file.
  running         the recorded processes are provably gone: invalid (the round
                  was interrupted, never run again); the rollout is handled
                  like any other (saved for the record), then the clean-up.
  launching, or a process still alive, or one that cannot be compared:
                  manual_review; the scratch is kept, no new review starts.
  finished / invalid, not yet cleaned (the daemon died in the middle of
                  ending the review): cleaned now, but only when the record
                  is whole (a result.json that agrees with the manifest).
  manual_review / cleaned: left alone.

A job whose flow-side link is missing (the daemon died between writing the
manifest and the link) gets its link written back, from the manifest. A
manifest that cannot be read is reported and left as it is: the flow's
accounting refuses until a person looks (stream_flow.flow_reviews).

Each item of the result is {job_id, pipeline_id, action, failure, why}; the
caller holds the flow for every item with failure True.
"""

from __future__ import annotations

import os
import time

from . import codex_constants as cc
from . import pipeline_store, proctrack, review_finish, review_store, stream_flow


def _item(m: dict | None, name: str, action: str, why: str = "", failure: bool = False) -> dict:
    return {"job_id": name, "pipeline_id": m["pipeline_id"] if m else None, "action": action, "failure": failure,
            "why": why[:300]}


def _repair_link(base, m: dict) -> str | None:
    """None when the flow-side link is there (or was put back); else why not."""
    try:
        with pipeline_store.Pipeline(base, m["task_id"], create=False) as p:
            links = p.review_links()
            if m["round"] not in links:
                p.write_review_link(m["round"], m["job_id"], m["pipeline_id"], m["commit"])
    except (OSError, pipeline_store.StoreRefused) as exc:
        return f"流程的審查紀錄無法核對或補寫（{type(exc).__name__}）"
    return None


def _finish_decided(base, m: dict, constants) -> dict:
    """finished / invalid but not cleaned: the daemon ended in the middle of
    ending the review. finish_review resumes it without judging or saving
    again (Codex 3c R4): the clean-up when the record is whole, result.json
    rebuilt from the saved copies when only that is missing."""
    name = m["job_id"]
    out = review_finish.finish_review(base, m, {"interrupted": True, "manual_review": None},
                                      c=constants.get(m["codex_version"]))
    if out.cleaned:
        return _item(m, name, "cleaned")
    return _item(m, name, "kept", out.problem or "審查紀錄不完整，保留原檔，不清理")


def _recover_active(base, m: dict, rows, constants, now: float) -> dict:
    name = m["job_id"]
    verdict, why = review_store.processes_gone(m, rows)
    if verdict != "gone":
        review_store.retain(base, name, f"daemon 重啟後，{why}")
        return _item(m, name, "manual_review", why, failure=True)
    c = constants.get(m["codex_version"])
    if c is None:
        review_store.retain(base, name, "daemon 重啟後，這個 Codex 版本的常數不存在，無法判斷審查")
        return _item(m, name, "manual_review", "沒有這個 Codex 版本的常數", failure=True)
    run = {"manual_review": None, "interrupted": True, "never_started": m["process"] == "none",
           "exit_code": None, "exit_signal": None, "terminated_for": None, "invalid_reasons": []}
    out = review_finish.finish_review(base, m, run, c=c, now=now)
    why = "；".join(out.reasons[:3]) or (out.problem or "")
    return _item(m, name, out.outcome, why, failure=True) | {"cleaned": out.cleaned}


def recover(base, *, constants=None, rows=None, now: float | None = None) -> list[dict]:
    """Every job under reviews/. ``rows``: a process table (None: look it up;
    an unavailable table means "cannot tell", never "gone")."""
    constants = cc.VERSIONS if constants is None else constants
    now = time.time() if now is None else now
    try:
        names = review_store.list_jobs(base)
    except (review_store.ReviewRefused, OSError) as exc:
        return [_item(None, "", "unreadable", f"reviews/ 無法列出（{type(exc).__name__}）")]
    if rows is None:
        try:
            rows = proctrack.process_table()
        except proctrack.ProcessTableUnavailable:
            rows = None
    out = []
    for name in names:
        if not review_store.JOB_RE.match(name):
            out.append(_item(None, name, "unreadable", "不是審查工作的名稱"))
            continue
        try:
            m = review_store.read_manifest(base, name)
        except (review_store.ReviewRefused, OSError) as exc:
            out.append(_item(None, name, "unreadable", f"manifest 無法讀取（{type(exc).__name__}）"))
            continue
        try:
            problem = _repair_link(base, m)
            if problem:
                out.append(_item(m, name, "link_problem", problem))
            if m["state"] in ("manual_review", "cleaned"):
                continue
            if m["state"] in ("finished", "invalid"):
                out.append(_finish_decided(base, m, constants))
            else:
                out.append(_recover_active(base, m, rows, constants, now))
        except Exception as exc:                  # one job never stops the others, nor the daemon's start
            out.append(_item(m, name, "error", f"恢復時發生未預期的錯誤（{type(exc).__name__}）", failure=True))
            try:
                review_store.retain(base, name, f"恢復時發生未預期的錯誤（{type(exc).__name__}）")
            except Exception:
                pass
    return out
