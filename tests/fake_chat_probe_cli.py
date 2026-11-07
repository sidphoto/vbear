"""A stand-in for Claude Code 2.1.318 in chat mode for the chat check (vbear/chat_check.py), for tests only. Unlike
tests/fake_chat_cli.py, which replays recorded turns, this one decides what to do from the words of each message, as
the check's prompts are written: ``[vbear-check:stream|modify|deny|error|memory|budget]``. It never calls a model or
touches the network, and what it prints has the shapes recorded with 2.1.318 (tests/fixtures/chat).

Reads ``$HOME/fake-probe.json``; every key is optional and the default is a well-behaved Claude Code:
  version               what it says it is (2.1.318)
  cost                  what each turn adds to the total (0.0015)
  cumulative            false: the total starts again in a resumed process
  remember              false: a resumed session has forgotten the code word
  stream                false: no text_delta events, the reply comes whole
  instructions_honored  false: ignores --append-system-prompt
  bash_asks             false: runs Bash without asking (breaks the rule that every Bash is asked)
  deny_ignored          true: runs a Bash command even when VBear said no
  error_reply_fatal     true: exits when VBear answers a permission request with a control error
  sandbox               "open": a write outside the work folder and the scratch folder succeeds
  tmp_error             true: ends a Bash result with the shared-tmp error recorded in P36-0 fact 9
  extra_dirs            list: reported as additional_directories in system/init
  user_extra_dirs       list: the extra folders of the person's own Claude settings, reported in system/init unless
                        the argv has ``--setting-sources ""`` (what the real 2.1.318 does: --settings cannot remove them)
  budget_counts_previous  true: --max-budget-usd counts what earlier processes of the session spent
  init_error            true: answers initialize with an error
  shared_sandbox        "closed": a Bash write into the shared folder (a further place --settings lets the sandbox write) is
                        blocked as if the CLI had ignored the setting (P43-2)
  shared_no_attempt     true: does not try the Write the shared step asks for (the model said no)
The shared-folder steps are tagged ``[vbear-check:shared_write|shared_bash|shared_link]`` and name the path to use: a Write asks
VBear, and writes the file only when VBear says yes; a Bash ``echo ok > <path>`` asks, and writes only inside the places the sandbox
of ``--settings`` names.
Everything it is given and does goes to ``$HOME/fake-probe-log.jsonl``; the session's totals are kept in
``$HOME/fake-probe-state.json``."""

import json
import os
import re
import shlex
import signal
import sys
import time

HOME = os.environ["HOME"]
CONF = json.load(open(os.path.join(HOME, "fake-probe.json")))
LOG = os.path.join(HOME, "fake-probe-log.jsonl")
STATE = os.path.join(HOME, "fake-probe-state.json")
VERSION = CONF.get("version", "2.1.318")
argv = sys.argv[1:]

if "--version" in argv:
    print(f"{VERSION} (Claude Code)")
    sys.exit(0)


def log(**kw):
    with open(LOG, "a") as f:
        f.write(json.dumps(kw) + "\n")


def on_term(*_):
    log(event="sigterm", pid=os.getpid())
    sys.exit(143)


signal.signal(signal.SIGTERM, on_term)
flag = "--session-id" if "--session-id" in argv else "--resume"
SID = argv[argv.index(flag) + 1]
CWD = os.path.realpath(os.getcwd())
SCRATCH = os.path.realpath(os.environ.get("CLAUDE_CODE_TMPDIR", CWD))
BUDGET = float(argv[argv.index("--max-budget-usd") + 1])
APPENDED = "--append-system-prompt" in argv
NO_USER_SETTINGS = "--setting-sources" in argv and argv[argv.index("--setting-sources") + 1] == ""
RESUMED = flag == "--resume"
log(event="start", argv=argv, cwd=CWD, pid=os.getpid())
TOOLS = ["Bash", "Edit", "Glob", "Grep", "Read", "Write"]
state = json.load(open(STATE)) if os.path.exists(STATE) else {"total": 0.0, "code": None}
proc_total = 0.0               # what this process added; the total shown when "cumulative" is false
started = False


def save():
    with open(STATE, "w") as f:
        json.dump(state, f)


def emit(ev):
    sys.stdout.write(json.dumps({**ev, "session_id": SID}) + "\n")
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        log(event="eof")
        sys.exit(0)
    msg = json.loads(line)
    log(event="stdin", line=msg)
    return msg


def init_event():
    emit({"type": "system", "subtype": "init", "cwd": CWD, "tools": TOOLS, "model": "claude-haiku-5-5",
          "permissionMode": "default", "claude_code_version": VERSION, "mcp_servers": [],
          "additional_directories": CONF.get("extra_dirs", []) + ([] if NO_USER_SETTINGS else CONF.get("user_extra_dirs", []))})


def text_reply(text, *, stream=True):
    mid = "msg_fake" + str(int(time.time() * 1000))
    emit({"type": "stream_event", "event": {"type": "message_start", "message": {"id": mid, "role": "assistant"}}})
    emit({"type": "stream_event", "event": {"type": "content_block_start", "index": 0,
                                            "content_block": {"type": "text", "text": ""}}})
    if stream and CONF.get("stream", True):
        words = text.split(" ")
        for i, w in enumerate(words):
            emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {
                "type": "text_delta", "text": w + (" " if i + 1 < len(words) else "")}}})
            time.sleep(0.03)
    emit({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
    emit({"type": "stream_event", "event": {"type": "message_stop"}})
    emit({"type": "assistant", "message": {"id": mid, "type": "message", "role": "assistant",
                                           "content": [{"type": "text", "text": text}]}})


def result(subtype="success", is_error=False, add=True):
    global proc_total
    if add:
        state["total"] += CONF.get("cost", 0.0015)
        proc_total += CONF.get("cost", 0.0015)
    save()
    shown = state["total"] if CONF.get("cumulative", True) else proc_total
    emit({"type": "result", "subtype": subtype, "is_error": is_error, "num_turns": 1, "total_cost_usd": shown,
          "permission_denials": []})


def sandbox_roots():
    """The places ``--settings`` lets the sandbox write: the work folder, the scratch folder and, with the shared folder on, it."""
    roots = [CWD, SCRATCH]
    if "--settings" in argv:
        try:
            allow = json.load(open(argv[argv.index("--settings") + 1]))["sandbox"]["filesystem"]["allowWrite"]
        except (OSError, ValueError, KeyError):
            allow = []
        roots += [os.path.realpath(x) for x in allow if os.path.realpath(x) not in roots]
    if CONF.get("shared_sandbox") == "closed":
        roots = roots[:2]
    return roots


def run_bash(command):
    """A tiny shell: echo and touch, with a sandbox that only lets touch write in the work and scratch folders."""
    out, err, code = [], [], 0
    for part in command.split(";"):
        words = shlex.split(part)
        if not words:
            continue
        if words[0] == "echo" and len(words) >= 3 and words[-2] == ">":
            target = os.path.realpath(os.path.join(CWD, words[-1]))
            if any(target == root or target.startswith(root + os.sep) for root in sandbox_roots()):
                with open(target, "w") as f:
                    f.write(" ".join(words[1:-2]) + "\n")
                code = 0
            else:
                err.append(f"{words[-1]}: Operation not permitted")
                code = 1
        elif words[0] == "echo":
            out.append(" ".join(words[1:]))
            code = 0
        elif words[0] == "touch":
            target = os.path.realpath(os.path.join(CWD, words[1]))
            inside = any(target == root or target.startswith(root + os.sep) for root in (CWD, SCRATCH))
            if inside or CONF.get("sandbox") == "open":
                open(target, "a").close()
                code = 0
            else:
                err.append(f"touch: {words[1]}: Operation not permitted")
                code = 1
        else:
            err.append(f"{words[0]}: command not found")
            code = 127
    if CONF.get("tmp_error"):
        err.append("operation not permitted: /tmp/claude-501/cwd-ab12cd")
        code = 1
    return "\n".join(out + err), code != 0


def tool_turn(command, tid):
    emit({"type": "assistant", "message": {"id": "msg_fakecall" + tid, "type": "message", "role": "assistant",
                                           "content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                        "input": {"command": command, "description": "check"}}]}})
    if CONF.get("bash_asks", True):
        rid = "00000000-0000-4000-8000-" + tid[-12:].rjust(12, "0")
        emit({"type": "control_request", "request_id": rid, "request": {
            "subtype": "can_use_tool", "tool_name": "Bash", "display_name": "Bash",
            "input": {"command": command, "description": "check"}, "description": "check", "tool_use_id": tid}})
        while True:
            msg = read()
            if msg.get("type") == "control_response" and msg.get("response", {}).get("request_id") == rid:
                break
        resp = msg["response"]
        if resp.get("subtype") == "error":
            if CONF.get("error_reply_fatal"):
                log(event="exit", code=1)
                sys.exit(1)
            return tool_result(tid, "The permission request was not accepted: " + str(resp.get("error")), True,
                               "user_reject", "reject")
        body = resp.get("response", {})
        if body.get("behavior") == "allow":
            text, failed = run_bash(body["updatedInput"]["command"])
            return tool_result(tid, text, failed, "user_temporary", "accept")
        if CONF.get("deny_ignored"):
            run_bash(command)
        return tool_result(tid, "The user doesn't want to proceed: " + str(body.get("message")), True, "user_reject",
                           "reject")
    text, failed = run_bash(command)
    return tool_result(tid, text, failed, "config", "accept")


def tool_result(tid, text, is_error, source, decision):
    emit({"type": "user", "message": {"role": "user", "content": [{
        "tool_use_id": tid, "type": "tool_result", "content": text, "is_error": is_error}]},
        "tool_result_meta": [{"id": tid, "permission_decision": {"decision": decision, "source": source}}]})
    return text


def shared_turn(tag, text, tid):
    """The shared-folder steps: the path to use is the one word of the message that begins with a slash."""
    path = next((w for w in text.replace(">", " ").split() if w.startswith("/")), "")
    if tag == "shared_bash":
        shown = tool_turn(f"echo ok > {path}", tid)
        return text_reply("The tool said: " + shown.replace("\n", " "), stream=False)
    if CONF.get("shared_no_attempt"):
        return text_reply("I will not do that.", stream=False)
    emit({"type": "assistant", "message": {"id": "msg_fakecall" + tid, "type": "message", "role": "assistant",
                                           "content": [{"type": "tool_use", "id": tid, "name": "Write",
                                                        "input": {"file_path": path, "content": "ok"}}]}})
    rid = "00000000-0000-4000-8000-" + tid[-12:].rjust(12, "0")
    emit({"type": "control_request", "request_id": rid, "request": {
        "subtype": "can_use_tool", "tool_name": "Write", "display_name": "Write",
        "input": {"file_path": path, "content": "ok"}, "description": "check", "tool_use_id": tid}})
    while True:
        msg = read()
        if msg.get("type") == "control_response" and msg.get("response", {}).get("request_id") == rid:
            break
    body = msg["response"].get("response", {})
    if body.get("behavior") == "allow":
        with open(body["updatedInput"]["file_path"], "w") as f:
            f.write("ok\n")
        tool_result(tid, "File created", False, "user_temporary", "accept")
        return text_reply("Done.", stream=False)
    tool_result(tid, "The user doesn't want to proceed: " + str(body.get("message")), True, "user_reject", "reject")
    text_reply("The tool was refused.", stream=False)


def turn(text):
    global started
    tag = re.search(r"\[vbear-check:(\w+)\]", text)
    tag = tag.group(1) if tag else "text"
    if not started:
        started = True
        init_event()
    if tag == "budget" and CONF.get("budget_counts_previous") and state["total"] >= BUDGET:
        return result("error_max_budget_usd", True, add=False)
    if tag == "stream":
        found = re.search(r"code word[^.]*? is ([A-Z]+-\d+)", text)
        if found:
            state["code"] = found.group(1)
        lead = "PINEAPPLE " if CONF.get("instructions_honored", True) and APPENDED else ""
        text_reply(lead + ", ".join(str(i) for i in range(1, 41)))
    elif tag == "memory":
        code = state["code"] if CONF.get("remember", True) else None
        text_reply(code or "I do not know")
    elif tag in ("shared_write", "shared_bash", "shared_link"):
        shared_turn(tag, text, "toolu_" + tag + "0001")
    elif tag in ("modify", "deny", "error"):
        command = {"modify": "echo original", "deny": "touch denied-probe.txt", "error": "touch error-probe.txt"}[tag]
        shown = tool_turn(command, "toolu_" + tag + "0001")
        text_reply("The tool said: " + shown.replace("\n", " "), stream=False)
    else:
        text_reply("OK")
    result()


while True:
    message = read()
    if message.get("type") == "control_request" and message.get("request", {}).get("subtype") == "initialize":
        rid = message["request_id"]
        if CONF.get("init_error"):
            emit({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "no"}})
            continue
        emit({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": {
            "commands": [{"name": "fictional-command", "description": "made up"}],
            "models": [{"value": "fictional-model", "displayName": "Fictional Model"}],
            "account": {"email": "fictional.person@example.invalid", "organization": "Fictional Org"},
            "claude_code_version": VERSION, "current_permission_mode": "default"}}})
    elif message.get("type") == "user":
        turn(message["message"]["content"][0]["text"])
