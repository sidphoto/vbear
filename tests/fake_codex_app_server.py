"""A stand-in for ``codex`` 0.163.0, for the P38 daemon tests. It never calls a model, reads a login or touches the
network: ``codex --version`` prints ``codex-cli <version>``, ``codex login status`` exits with the code in the
configuration, and ``codex app-server ...`` plays back a recorded transcript (tests/fixtures/codex-chat/, see
tests/codex_chat_fixtures.py) to what VBear writes, waiting for each line the recording has VBear write before it prints
the next part.

Configuration: the JSON file named by $FAKE_CODEX_CONFIG (else $HOME/fake-codex.json; tests/codex_chat_fixtures.py
``write_launcher`` makes an executable that sets it, since a chat process is given a fixed environment):

  {"version": "0.163.0",                 what --version prints
   "login_status": 0,                    the exit code of ``login status``
   "clean": true,                        false plays the recording as made: a person's AGENTS.md, five MCP servers,
                                         a sandbox with network access (the chat must be stopped)
   "thread_id": null,                    for thread/start: the thread id to print instead of the recorded one
   "start":  {"fixture": "a", "turns": [0, 1, ...]},
   "resume": {"fixture": "b-resume", "turns": [0, 1]}}

``start`` is used when VBear writes ``thread/start``, ``resume`` when it writes ``thread/resume``. ``turns`` names the
recorded turns to play, one for each ``turn/start``, in order (default: all of them); an entry is a number or
{"turn": n, "inject": [message, ...], "hold": true}, the messages printed right after the answer to ``turn/start`` (a
server request among them is waited for until VBear answers it); ``hold`` then stops the turn there, printing nothing
more until VBear writes ``turn/interrupt`` (which ends it as interrupted) or closes stdin. The turn counter is kept in ``<config>.state.json`` so that a
process that resumes the thread goes on with the next turn. Everything it is given and does goes to
``<config>.log.jsonl``.

What a recorded turn holds is what branches: the turn that declines a command and goes on with ``turn/steer`` is
the "change what runs" path (decline, steer, a new request in the same turn). The answer to a request VBear gives
decides the item's status: another decision than the recorded one rewrites the ``item/completed`` that follows (allowed:
completed, exit code 0, no output; declined or cancelled: declined). That rewrite is the fake's own, not a recording.
A ``turn/interrupt`` while a turn waits ends it with ``turn/completed`` of status ``interrupted``. The ids, the thread
id, the work folder and the Codex home in the recording are replaced with the real ones. A request the script does
not expect is answered with a JSON-RPC error and logged as ``unexpected``.
"""

from __future__ import annotations

import copy
import json
import os
import signal
import sys

from tests import codex_chat_fixtures as ccf

# Variables macOS or the interpreter add to any process; the log names the others, which are the ones the parent gave.
_OS_ADDED = frozenset({"__CF_USER_TEXT_ENCODING", "LC_CTYPE", "PWD", "SHLVL", "_"})
ERR_NOT_FOUND = -32601
ERR_INVALID = -32600
ERR_NO_TURN = -32000


class Eof(Exception):
    pass


class Abort(Exception):
    """The turn being played was interrupted."""


def _replace(value, old: str, new: str):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _replace(v, old, new) for k, v in value.items()}
    return value


class Fake:
    def __init__(self, conf: dict, conf_path: str):
        self.conf = conf
        self.log_path = conf_path + ".log.jsonl"
        self.state_path = conf_path + ".state.json"
        self.clean = conf.get("clean", True)
        self.cache: dict = {}
        self.mode: str | None = None
        self.parsed = None
        self.idmap: dict = {}            # an id VBear wrote in the recording -> the id it really wrote
        self.srv: dict = {}              # a server request id in the recording -> the one printed
        self.next_srv = 0
        self.item_of: dict = {}          # a server request id in the recording -> the item it names (recorded id)
        self.flips: dict = {}            # recorded item id -> VBear's decision, when it differs from the recording
        self.subs: list = []
        self.rows: list = []             # the turn being played
        self.tokens: dict | None = None  # the thread's running token counts, kept in the state file across processes
        self.in_turn = False
        home = os.environ.get("CODEX_HOME")
        if home:
            self.subs.append((ccf.CODEX_HOME, home))

    # -- plumbing

    def log(self, **kw):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(kw) + "\n")

    def fx(self, name: str):
        if name not in self.cache:
            self.cache[name] = ccf.parse(name)
        return self.cache[name]

    def spec(self, mode: str) -> dict:
        return self.conf.get(mode) or {}

    def write(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def respond(self, rid, result):
        self.write({"id": rid, "result": result})

    def respond_error(self, rid, code, message):
        self.write({"id": rid, "error": {"code": code, "message": message}})

    def read(self):
        while True:
            raw = sys.stdin.readline()
            if not raw:
                self.log(event="eof")
                raise Eof
            try:
                msg = json.loads(raw)
            except ValueError:
                self.log(event="bad_line", length=len(raw))
                continue
            self.log(event="stdin", line=msg)
            return msg

    def unexpected(self, msg):
        self.log(event="unexpected", method=msg.get("method") if isinstance(msg, dict) else None)
        if isinstance(msg, dict) and "method" in msg and "id" in msg:
            self.respond_error(msg["id"], ERR_NOT_FOUND, "not part of the recorded script")

    def wait(self, pred):
        """Read until a line satisfies ``pred``; others are answered as unexpected. A turn/interrupt ends the turn
        being played."""
        while True:
            msg = self.read()
            if isinstance(msg, dict) and msg.get("method") == "turn/interrupt" and self.rows:
                self.interrupt(msg)
                raise Abort
            if isinstance(msg, dict) and pred(msg):
                return msg
            self.unexpected(msg)

    # -- printing recorded rows

    def emit(self, line):
        ln = ccf.clean(line) if self.clean else copy.deepcopy(line)
        if ln is None:
            return
        if ccf.is_request(ln):                                     # a server request: a fresh id
            rid = self.srv_id(ln["id"])
            params = ln.get("params") if isinstance(ln.get("params"), dict) else {}
            self.item_of[ln["id"]] = params.get("itemId")
            ln["id"] = rid
        elif ccf.is_response(ln):
            ln["id"] = self.idmap.get(ln["id"], ln["id"])
        elif ln.get("method") == "serverRequest/resolved" and isinstance(ln.get("params"), dict):
            ln["params"]["requestId"] = self.srv_id(ln["params"].get("requestId"))
        elif ln.get("method") == "item/completed":
            self.flip(ln)
        elif ln.get("method") == "thread/tokenUsage/updated":
            self.count(ln)
        for old, new in self.subs:
            ln = _replace(ln, old, new)
        self.write(ln)

    def count(self, ln):
        """The recording counts the whole thread, but only some of its turns are played here, in any order: the
        total printed is this process's running sum of the recorded per-call counts, kept across processes. The
        count repeated after a resume is the running sum so far (the recorded one when there is none)."""
        usage = ln["params"]["tokenUsage"]
        if self.tokens is None:
            self.tokens = self.state().get("tokens")
        if self.in_turn:
            run = self.tokens or {k: 0 for k in usage["last"]}
            for key, value in usage["last"].items():
                if isinstance(value, int):
                    run[key] = run.get(key, 0) + value
            self.tokens = run
        elif self.tokens is None:
            self.tokens = dict(usage["total"])
        usage["total"] = dict(self.tokens)
        state = self.state()
        state["tokens"] = self.tokens
        self.save(state)

    def save(self, state):
        with open(self.state_path, "w") as f:
            json.dump(state, f)

    def srv_id(self, recorded):
        if recorded not in self.srv:
            self.srv[recorded] = self.next_srv
            self.next_srv += 1
        return self.srv[recorded]

    def flip(self, ln):
        item = ln["params"].get("item") if isinstance(ln.get("params"), dict) else None
        decision = self.flips.get(item.get("id")) if isinstance(item, dict) else None
        if decision is None:
            return
        if decision == "accept":
            item.update(status="completed", exitCode=0 if item.get("type") == "commandExecution" else None)
            if item.get("type") == "commandExecution":
                item["aggregatedOutput"] = ""
        else:
            item.update(status="declined")
            if item.get("type") == "commandExecution":
                item.update(exitCode=None, aggregatedOutput=None, processId=None, durationMs=None)

    def group(self, g, msg):
        self.idmap[g.request["id"]] = msg["id"]
        for row in g.pre:
            self.emit(row[1])
        self.emit(g.response)
        for row in g.post:
            self.emit(row[1])

    # -- the script

    def state(self) -> dict:
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def expect(self, line):
        """VBear's part of the recording: wait for it, and learn from it."""
        if ccf.is_request(line):                                   # turn/steer
            msg = self.wait(lambda m: m.get("method") == line["method"])
            self.idmap[line["id"]] = msg["id"]
        elif ccf.is_response(line):                                # an answer to a server request
            want = self.srv_id(line["id"])
            msg = self.wait(lambda m: m.get("id") == want and "method" not in m)
            result = msg.get("result") if isinstance(msg.get("result"), dict) else {}
            actual, recorded = result.get("decision"), line.get("result", {}).get("decision")
            item = self.item_of.get(line["id"])
            if item is not None and (actual == "accept") != (recorded == "accept"):
                self.flips[item] = "accept" if actual == "accept" else "decline"
        else:
            self.wait(lambda m: m.get("method") == line.get("method"))

    def interrupt(self, msg):
        self.respond(msg["id"], {})
        for d, ln in reversed(self.rows):
            if d == "out" and isinstance(ln, dict) and ln.get("method") == "turn/completed":
                done = copy.deepcopy(ln)
                done["params"]["turn"]["status"] = "interrupted"
                self.emit(done)
                break

    def play_turn(self, msg):
        spec = self.spec(self.mode)
        entries = spec.get("turns")
        if entries is None:
            entries = list(range(len(self.parsed.turns)))
        state = self.state()
        index = state.get(self.mode + "_next", 0)
        if index >= len(entries):
            self.log(event="no_turn_left", index=index)
            self.respond_error(msg["id"], ERR_NO_TURN, "no recorded turn left")
            return
        state[self.mode + "_next"] = index + 1
        self.save(state)
        entry = entries[index]
        number, inject = (entry, []) if isinstance(entry, int) else (entry["turn"], entry.get("inject", []))
        hold = isinstance(entry, dict) and entry.get("hold") is True
        self.rows = self.parsed.turns[number]
        start_id = self.rows[0][1]["id"]
        self.idmap[start_id] = msg["id"]
        self.in_turn = True
        try:
            for d, ln in self.rows[1:]:
                if d == "out":
                    self.emit(ln)
                    if ccf.is_response(ln) and ln["id"] == start_id:
                        for extra in inject:
                            self.inject(extra)
                        if hold:
                            self.wait(lambda m: False)
                else:
                    self.expect(ln)
        except Abort:
            pass
        finally:
            self.rows = []
            self.in_turn = False

    def inject(self, extra):
        self.write(extra)
        if isinstance(extra, dict) and "method" in extra and "id" in extra:
            self.wait(lambda m: m.get("id") == extra["id"] and "method" not in m)

    def serve(self):
        self.log(event="start", argv=sys.argv[1:], cwd=os.path.realpath(os.getcwd()), pid=os.getpid(),
                 env_keys=sorted(k for k in os.environ if k not in _OS_ADDED and not k.startswith("FAKE_CODEX")),
                 codex_home=os.environ.get("CODEX_HOME"))
        try:
            while True:
                self.idle(self.read())
        except Eof:
            self.log(event="exit", code=0)
            return 0

    def idle(self, msg):
        method = msg.get("method") if isinstance(msg, dict) else None
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if method == "initialize":
            name = (self.spec("start") or self.spec("resume")).get("fixture", "a")
            self.group(self.fx(name).handshake["initialize"], msg)
        elif method == "initialized":
            pass
        elif method in ("thread/start", "thread/resume"):
            self.mode = "start" if method == "thread/start" else "resume"
            spec = self.spec(self.mode)
            if not spec:
                return self.respond_error(msg["id"], ERR_NOT_FOUND, f"no recorded {method}")
            self.parsed = self.fx(spec.get("fixture", "a" if self.mode == "start" else "b-resume"))
            g = self.parsed.handshake.get(method)
            if g is None:
                return self.respond_error(msg["id"], ERR_NOT_FOUND, f"{method} is not in this recording")
            self.subs = [s for s in self.subs if s[0] != ccf.WORK]
            self.subs.append((ccf.WORK, params.get("cwd") or ccf.WORK))
            recorded = g.response["result"]["thread"]["id"]
            wanted = params.get("threadId") if self.mode == "resume" else self.conf.get("thread_id")
            if wanted:
                self.subs.append((recorded, wanted))
            self.group(g, msg)
        elif method == "mcpServerStatus/list":
            g = self.parsed.handshake.get(method) if self.parsed else None
            if g is None:
                self.respond(msg["id"], {"data": []})
            else:
                self.group(g, msg)
        elif method == "turn/start" and self.parsed is not None:
            self.play_turn(msg)
        elif method == "thread/delete" and "id" in msg:
            self.delete(msg, params)
        elif method == "turn/steer" and "id" in msg:
            self.respond_error(msg["id"], ERR_INVALID, "no active turn to steer")
        elif method == "turn/interrupt" and "id" in msg:
            self.respond(msg["id"], {})
        else:
            self.unexpected(msg)

    def delete(self, msg, params):
        if self.parsed is not None and self.parsed.delete:
            self.idmap[self.parsed.delete[0][1]["id"]] = msg["id"]
            for d, ln in self.parsed.delete[1:]:
                if d == "out":
                    self.emit(ln)
        else:
            self.respond(msg["id"], {})
            self.write({"method": "thread/deleted", "params": {"threadId": params.get("threadId")}})


def main(argv) -> int:
    path = os.environ.get("FAKE_CODEX_CONFIG") or os.path.join(os.environ.get("HOME", ""), "fake-codex.json")
    try:
        with open(path) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = {}
    fake = Fake(conf, path)
    signal.signal(signal.SIGTERM, lambda *_: (fake.log(event="sigterm", pid=os.getpid()), sys.exit(143)))
    if argv[:1] == ["--version"]:
        print(f"codex-cli {conf.get('version', ccf.VERSION)}")
        return 0
    if argv[:2] == ["login", "status"]:
        code = int(conf.get("login_status", 0))
        print("Logged in using ChatGPT" if code == 0 else "Not logged in", file=sys.stdout if code == 0 else sys.stderr)
        return code
    if argv[:1] == ["app-server"]:
        return fake.serve()
    print("fake codex: only --version, login status and app-server are played", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
