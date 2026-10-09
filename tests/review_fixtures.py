"""A valid fake Codex review run built from the version's constants table
(vbear.runtime.codex_constants), so tests break one rule at a time. Nothing
here starts Codex or calls a model. When the real probe corrects the table,
this follows."""

import copy
import json
import os
import tempfile

from vbear.runtime import codex_constants as cc

C = cc.VERSIONS["0.160.0"]
THREAD = "01a11921-aaaa-4bbb-8ccc-0123456789ab"
TURN = "turn-0001"
MODEL = "gpt-6-luna"
COMMIT = "a" * 40
SCRATCH = "/private/tmp/sr-abcd1234"


def report(commit=COMMIT, verdict="PASS", ancestor="yes", extra=""):
    return (f"Review of the change.\n{extra}\nREVIEWED_COMMIT: {commit}\nBASE_IS_ANCESTOR: {ancestor}\n"
            f"No defects found.\nVERDICT: {verdict}\n")


def _usage(i):
    return {"input_tokens": 1000 + i, "cached_input_tokens": 100, "cache_write_input_tokens": 0,
            "output_tokens": 50 + i, "reasoning_output_tokens": 10, "total_tokens": 1000 + i + 50 + i}


def _add(a, b):
    return {k: a[k] + b[k] for k in a}


def rollout_records(c=C, *, thread=THREAD, turn=TURN, scratch=SCRATCH, model=MODEL, last_message=None,
                    responses=2):
    last_message = report() if last_message is None else last_message
    recs = [
        ("session_meta", {"id": thread, "cwd": scratch, "cli_version": c.version, "originator": c.session_originator,
                          "source": c.session_source, "model_provider": c.model_provider, "extra": "ignored"}),
        ("world_state", {"apps_instructions": False, "plugins_instructions": False, "host_skills": [],
                         "multi_agent_mode": c.multi_agent_disabled, "agents_md": None}),
        ("event_msg", {"type": "task_started", "turn_id": turn, "started_at": 1791467000}),
        ("turn_context", {"cwd": scratch, "approval_policy": c.approval_policy, "model": model, "turn_id": turn,
                          "sandbox_policy": {"type": c.sandbox_type, "network_access": False,
                                             "exclude_slash_tmp": True, "exclude_tmpdir_env_var": True},
                          "permission_profile": {"network": c.network_restricted},
                          "file_system_sandbox_policy": {"x": 1}, "workspace_roots": [scratch]}),
        ("response_item", {"type": "message", "role": "user", "content": []}),
    ]
    turn_total = {f: 0 for f in c.usage_fields}
    thread_total = {f: 0 for f in c.usage_fields}
    for i in range(responses):
        usage = _usage(i)
        turn_total, thread_total = _add(turn_total, usage), _add(thread_total, usage)
        recs.append(("response_item", {"type": "reasoning", "summary": []}))
        recs.append(("response_item", {"type": "custom_tool_call", c.tool_name_key: "exec", "input": "ls"}))
        recs.append(("response_item", {"type": "custom_tool_call_output", "output": "ok"}))
        recs.append(("token_usage_record", {"usage": usage, "turn_token_usage": dict(turn_total),
                                            "thread_token_usage": dict(thread_total), "turn_id": turn}))
    recs.append(("response_item", {"type": "message", "role": "assistant", "content": []}))
    recs.append(("event_msg", {"type": "task_complete", "turn_id": turn, "last_agent_message": last_message,
                               "started_at": 1791467000, "completed_at": 1791467010, "duration_ms": 10000}))
    out = []
    for n, (typ, payload) in enumerate(recs):
        out.append({"ordinal": n, "timestamp": "2026-10-09T00:00:00Z", "type": typ, "payload": payload})
    return out, dict(turn_total)


def events(c=C, *, thread=THREAD, text=None, usage=None):
    text = report() if text is None else text
    return [
        {"type": "thread.started", "thread_id": thread},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "item_1", "type": "command_execution"}},
        {"type": "item.completed", "item": {"id": "item_1", "type": "command_execution"}},
        {"type": "item.completed", "item": {"id": "item_2", "type": c.message_item_type, c.message_text_key: text}},
        {"type": "turn.completed", "usage": usage},
    ]


def valid_run(c=C, **kw):
    """(events, rollout records, report text), all consistent."""
    text = kw.pop("text", None) or report()
    recs, turn_usage = rollout_records(c, last_message=text, **kw)
    evs = events(c, thread=kw.get("thread", THREAD), text=text,
                 usage={f: turn_usage[f] for f in c.events_usage_fields})
    return evs, recs, text


def lines(objs) -> bytes:
    return b"".join(json.dumps(o).encode("utf-8") + b"\n" for o in objs)


def rollout_fd(objs_or_bytes):
    """A read-only descriptor on a temporary file holding the rollout."""
    data = objs_or_bytes if isinstance(objs_or_bytes, bytes) else lines(objs_or_bytes)
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(data)
    f.close()
    fd = os.open(f.name, os.O_RDONLY)
    os.unlink(f.name)
    return fd


def clone(objs):
    return copy.deepcopy(objs)
