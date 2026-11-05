"""A stand-in for Claude Code 2.1.318 in chat mode, for the P36-1 daemon tests. It never calls a model or touches
the network: it answers ``initialize`` with a made-up account, commands and models (which VBear must never keep),
then plays one scripted turn per user message, waiting for VBear's answer to each permission request it prints.

Reads ``$HOME/fake-chat.json``: {"turns": [[step, ...], ...], "init": {"version", "mode", "error"}}. A step is
{"emit": [event, ...]}, {"ask": control_request} (printed, then stdin is read up to VBear's control_response with
that request_id), {"sleep": seconds} or {"exit": code}. In every event "SESSION" becomes the session id of the argv
and "/WORK" the folder it runs in (tests/chat_fixtures.py). The turn counter is kept in ``$HOME/fake-chat-state.json``
so that a resumed process plays the next turn. Everything it is given and does goes to ``$HOME/fake-chat-log.jsonl``.
"""

import json
import os
import signal
import sys
import time

HOME = os.environ["HOME"]
CONF = json.load(open(os.path.join(HOME, "fake-chat.json")))
LOG = os.path.join(HOME, "fake-chat-log.jsonl")
STATE = os.path.join(HOME, "fake-chat-state.json")


def log(**kw):
    with open(LOG, "a") as f:
        f.write(json.dumps(kw) + "\n")


def on_term(*_):
    log(event="sigterm", pid=os.getpid())
    sys.exit(143)


signal.signal(signal.SIGTERM, on_term)
argv = sys.argv[1:]
flag = "--session-id" if "--session-id" in argv else "--resume"
sid = argv[argv.index(flag) + 1]
cwd = os.path.realpath(os.getcwd())
log(event="start", argv=argv, cwd=cwd, pid=os.getpid(),
    env={k: os.environ.get(k) for k in ("HOME", "CLAUDE_CODE_TMPDIR", "DISABLE_AUTOUPDATER")})


def sub(v):
    if isinstance(v, str):
        return v.replace("SESSION", sid).replace("/WORK", cwd)
    if isinstance(v, list):
        return [sub(x) for x in v]
    if isinstance(v, dict):
        return {k: sub(x) for k, x in v.items()}
    return v


def emit(ev):
    sys.stdout.write(json.dumps(sub(ev)) + "\n")
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        log(event="eof")
        sys.exit(0)
    msg = json.loads(line)
    log(event="stdin", line=msg)
    return msg


def next_turn():
    n = json.load(open(STATE))["next"] if os.path.exists(STATE) else 0
    with open(STATE, "w") as f:
        json.dump({"next": n + 1}, f)
    return n


def initialize(msg):
    a = CONF.get("init", {})
    rid = msg["request_id"]
    if a.get("error"):
        emit({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "no"}})
        return
    emit({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": {
        "commands": [{"name": "fictional-command", "description": "made up"}],
        "models": [{"value": "fictional-model", "displayName": "Fictional Model"}],
        "account": {"email": "fictional.person@example.invalid", "organization": "Fictional Org"},
        "claude_code_version": a.get("version", "2.1.318"), "current_permission_mode": a.get("mode", "default")}}})


def run(steps):
    for step in steps:
        if "emit" in step:
            for ev in step["emit"]:
                emit(ev)
        elif "ask" in step:
            emit(step["ask"])
            rid = step["ask"]["request_id"]
            while True:
                msg = read()
                if msg.get("type") == "control_response" and msg.get("response", {}).get("request_id") == rid:
                    break
        elif "sleep" in step:
            time.sleep(step["sleep"])
        elif "exit" in step:
            log(event="exit", code=step["exit"])
            sys.exit(step["exit"])


while True:
    message = read()
    if message.get("type") == "control_request" and message.get("request", {}).get("subtype") == "initialize":
        initialize(message)
    elif message.get("type") == "user":
        index = next_turn()
        turns = CONF.get("turns", [])
        run(turns[index] if index < len(turns) else [])
