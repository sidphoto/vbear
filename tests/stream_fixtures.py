"""Synthetic Claude Code 2.1.292 stream-json turns, in the order measured on
2026-10-08 (design 0): lifecycle(queued) -> lifecycle(started) -> init ->
thinking_tokens* -> replay -> body -> result -> lifecycle(completed).
Used by the protocol/journal tests and by the fake claude program."""

import uuid

VERSION = "2.1.292"
MODEL = "claude-haiku-4-5-20251001"
SUCCESS = "Structured output provided successfully"


def new_uuid() -> str:
    return str(uuid.uuid4())


def report(d, head="0" * 40, **over):
    r = {"v": 1, "dispatch_id": d, "status": "done", "head": head,
         "tests": {"command": "python3 -m unittest", "result": "passed", "summary": "ok"}, "notes": "done"}
    r.update(over)
    return r


def init_event(sid, cwd, **over):
    e = {"type": "system", "subtype": "init", "cwd": cwd, "session_id": sid, "tools": ["Bash", "StructuredOutput"],
         "mcp_servers": [], "model": MODEL, "permissionMode": "acceptEdits", "slash_commands": [],
         "terminal_slash_commands": [], "apiKeySource": "none", "claude_code_version": VERSION,
         "output_style": "default", "agents": [], "skills": [], "plugins": [], "capabilities": [],
         "analytics_disabled": False, "product_feedback_disabled": False, "uuid": new_uuid(),
         "messaging_socket_path": "/private/tmp/sc-x/cc-socks/1.sock", "fast_mode_state": "off",
         "fast_mode_disabled_reason": None, "per_turn_effort_active": False, "view_mode": "default"}
    e.update(over)
    return e


def turn(sid, d, text, *, cwd, result_index=0, cost=0.01, prefix="a", rep=None, responses=None,
         num_turns=None, subtype="success", is_error=False, extra_tool=None, structured_result=SUCCESS,
         structured_is_error=None, structured_output="same", model=MODEL, version=VERSION):
    """One complete turn. ``responses``: list of response specs, each a list
    of content items for that response's assistant events; by default one
    thinking event and one StructuredOutput call in a single response."""
    rep = rep if rep is not None else report(d)
    so_item = {"type": "tool_use", "id": f"toolu_{prefix}_so", "name": "StructuredOutput", "input": rep}
    responses = responses if responses is not None else [[{"type": "thinking", "thinking": "..."}, so_item]]
    ev = [
        {"type": "command_lifecycle", "command_uuid": d, "state": "queued", "uuid": new_uuid(), "session_id": sid},
        {"type": "command_lifecycle", "command_uuid": d, "state": "started", "uuid": new_uuid(), "session_id": sid},
        init_event(sid, cwd, model=model, claude_code_version=version),
        {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 0, "estimated_tokens_delta": 0,
         "user_message_uuid": d, "uuid": new_uuid(), "session_id": sid},
        {"type": "user", "isReplay": True, "message": {"role": "user", "content": [{"type": "text", "text": text}]},
         "parent_tool_use_id": None, "session_id": sid, "uuid": d, "timestamp": "2026-10-08T00:00:00Z"},
    ]
    first = True
    tool_ids = []
    for n, items in enumerate(responses, 1):
        rid, mid = f"req_{prefix}_{n}", f"msg_{prefix}_{n}"
        for item in items:
            ev.append({"type": "assistant", "message": {"id": mid, "content": [item]}, "request_id": rid,
                       "parent_tool_use_id": None, "user_message_uuid": d if first else None,
                       "user_message_uuids": [d] if first else None, "session_id": sid, "uuid": new_uuid(),
                       "timestamp": "2026-10-08T00:00:01Z"})
            first = False
            if item.get("type") == "tool_use":
                tool_ids.append((item["id"], item["name"]))
        results = []
        for tid, name in tool_ids:
            if name == "StructuredOutput":
                r = {"type": "tool_result", "tool_use_id": tid, "content": structured_result}
                if structured_is_error is not None:
                    r["is_error"] = structured_is_error
            else:
                r = {"type": "tool_result", "tool_use_id": tid, "content": "ok", "is_error": False}
            results.append(r)
        if results:
            ev.append({"type": "user", "message": {"role": "user", "content": results}, "parent_tool_use_id": None,
                       "session_id": sid, "uuid": new_uuid(), "timestamp": "2026-10-08T00:00:02Z",
                       "tool_use_result": "x"})
        tool_ids = []
    if extra_tool:
        ev.append(extra_tool)
    ev.append({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}, "session_id": sid,
               "uuid": new_uuid()})
    result = {"type": "result", "subtype": subtype, "is_error": is_error,
              "num_turns": num_turns if num_turns is not None else len(responses) + 1,
              "total_cost_usd": cost, "result_index": result_index, "queued_turn_count": 0,
              "user_message_uuid": d, "user_message_uuids": [d], "session_id": sid, "uuid": new_uuid(),
              "result": "finished", "stop_reason": "tool_use", "terminal_reason": "completed",
              "permission_denials": []}
    if structured_output == "same":
        result["structured_output"] = rep
    elif structured_output is not None:
        result["structured_output"] = structured_output
    ev.append(result)
    ev.append({"type": "command_lifecycle", "command_uuid": d, "state": "completed", "uuid": new_uuid(),
               "session_id": sid})
    return ev


BASE_COMMIT = "b" * 40


def fake_repo(path, commit: str = BASE_COMMIT):
    """A work directory whose HEAD git_head can read from files: a detached
    ``.git/HEAD``. No git is run and no object exists (git_head reads refs only)."""
    from pathlib import Path
    git = Path(path) / ".git"
    git.mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text(commit + "\n")
    return commit
