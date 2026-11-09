"""A stand-in for ``agy`` 1.5.3 for the version check (vbear/agy_chat_check.py, P46-4), which needs an AGY that does what each
message asks (tests/fake_agy_acp.py only replays synthetic scripts and touches no file). It speaks the handshake of
tests/fixtures/agy-chat/ (synthetic, not recordings) and answers each ``session/prompt`` by the step named in the message,
``[vbear-check:<step>]``, the way a well-behaved AGY would, with real effects in the folders it is given. Its sandbox is simulated:
a shell command may write only the work folder (``cwd``), the shared folder (``--add-dir``) and ``$TMPDIR``, and may not read or
reach the net. Nothing real is run, nothing reaches a model or the network.

  stream, resume, resume_ask   text only (resume: remembers the code word of the session, which is kept in the --gemini-dir folder)
  settings, read_inside        a read of a file in the work folder: asked when the settings file says "strict", else not asked
  ask, deny                    ``ls -a`` / ``rm deny-target.txt`` as a command that asks
  edit                         the file tool writes ``edit.txt``; after a refusal the next message ("請把 .. 寫成下面的內容：X") is
                               written as X
  outside_edit                 the file tool writes a file outside the work folder (it asks; written only if allowed)
  outside_shell, bypass, network, tmp_write, link_read, stop   the commands of the messages, run in the simulated sandbox
  shared_write, shared_shell, shared_link, shared_git          the shared folder part

The configuration is the JSON file named by $FAKE_AGY_CONFIG (``write_launcher`` makes an executable that sets it): ``version``,
``time_scale`` (what a ``sleep`` of the message takes: seconds x this), ``tokens`` (the usage of a turn: ``first``, ``next``) and
``flags``, the ways an AGY can go wrong:

  no_system_prompt     the system prompt is not applied
  session_id_not_uuid  session/new answers a session id that is not a UUID
  strict_ignored       the settings file is not read: a read in the work folder is never asked
  ls_unasked           ``ls -a`` runs without a request
  edit_ignored         after the change the original content is written again
  deny_ignored         the refused ``rm`` runs anyway
  outside_escapes      the sandbox does not hold: a shell write/read outside works
  outside_edit_escapes the refused file write outside is done anyway
  network_works        ``curl`` works
  link_read_asks       a read through the link asks first (else it is read without a request)
  link_leaks           the reply says the decoy's code word without any tool call
  cancel_keeps_running the command goes on after session/cancel (and the process group's end)
  forgets              the code word is not remembered after a resume
  home_item            the --gemini-dir folder gets a hooks file when the process that answered resume_ask ends
  auth_error           session/new is answered with "Authentication required"
  add_dir_ignored      --add-dir does not make the shared folder writable for a command
  only_shared          outside_edit_escapes works only when the shared folder is on
  settings_changed     the settings file is rewritten at the end of the first turn
  bad_usage            totalTokens is one more than the sum
  email_in_reply       the first reply holds an email-looking text
  skill_in_reply       the first reply names a skill (the sentinel of the test)

Everything it is given and does goes to ``<config>.log.jsonl`` (arguments, working folder, names of the environment, every line
it read).
"""

from __future__ import annotations

import json
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

VERSION = "1.5.3"
MODEL = "gemini-3.8-flash-high"
MODELS = {"currentModelId": "gemini-4-argon-medium", "availableModels": [{"modelId": "gemini-4-argon-medium", "name": "Made-up model A"},
                                                                       {"modelId": MODEL, "name": "Made-up model B"}]}
MODES = {"currentModeId": "default", "availableModes": [{"id": "default", "name": "Default"}, {"id": "plan", "name": "Plan"}]}
OPTIONS = [{"optionId": "allow", "name": "Allow once", "kind": "allow_once"}, {"optionId": "deny", "name": "Deny", "kind": "reject_once"}]
INIT = {"protocolVersion": 1, "agentCapabilities": {"loadSession": True, "promptCapabilities": {}, "mcpCapabilities": {},
                                                    "sessionCapabilities": {"resume": {}, "close": {}, "load": {}, "list": {},
                                                                            "additionalDirectories": {}}},
        "authMethods": [{"id": "fake-auth-1", "name": "Made-up sign-in"}], "_meta": {"antigravity": {"tier": "fake-tier-alpha"}}}
SKILLS = ["fake-skill-alpha", "fake-skill-beta", "fake-builtin"]
EXACT = re.compile(r"exactly(?: this shell command)?: (.+?) -- ", re.S)


class Eof(Exception):
    pass


class Reader:
    """Lines from stdin with a timeout (select on the descriptor, never the buffered file object)."""

    def __init__(self):
        self.buf = b""
        self.fd = sys.stdin.fileno()
        self.eof = False

    def line(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while b"\n" not in self.buf:
            if self.eof:
                raise Eof
            left = None if end is None else max(0.0, end - time.monotonic())
            ready, _, _ = select.select([self.fd], [], [], left)
            if not ready:
                return None
            chunk = os.read(self.fd, 65536)
            if not chunk:
                self.eof = True
                raise Eof
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\n", 1)
        return json.loads(raw)


class Agent:
    def __init__(self, conf: dict, conf_path: str, argv: list):
        self.conf, self.flags = conf, conf.get("flags") or {}
        self.log_path = conf_path + ".log.jsonl"
        self.state_path = conf_path + ".state.json"
        self.argv = argv
        self.reader = Reader()
        self.cwd = os.path.realpath(os.getcwd())
        self.gemini = self.option("--gemini-dir")
        self.shared = self.option("--add-dir")
        self.tmpdir = os.environ.get("TMPDIR") or "/tmp"
        self.sys_word = None
        self.session = None
        self.turns = 0
        self.cancelled = False
        self.next_id = 100
        self.call_no = 0
        self.scale = float(conf.get("time_scale", 1.0))
        self.last_step = None

    # -- plumbing

    def option(self, name):
        return self.argv[self.argv.index(name) + 1] if name in self.argv[:-1] else None

    def log(self, **kw):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(kw) + "\n")

    def write(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def update(self, **update):
        self.write({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": self.session, "update": update}})

    def recv(self, timeout=None):
        msg = self.reader.line(timeout)
        if msg is not None:
            self.log(event="stdin", line=msg)
            if msg.get("method") == "session/cancel":
                self.cancelled = True
        return msg

    def state(self):
        try:
            return json.loads(Path(self.state_path).read_text())
        except (OSError, ValueError):
            return {}

    def sessions_dir(self):
        d = Path(self.gemini or self.cwd) / "antigravity-cli" / "conversations"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def settings_mode(self):
        try:
            return json.loads((Path(self.gemini) / "antigravity-cli" / "settings.json").read_text()).get("toolPermission")
        except (OSError, ValueError, TypeError):
            return None

    # -- the protocol

    def serve(self):
        self.log(event="start", argv=self.argv, cwd=self.cwd, pid=os.getpid(),
                 env_keys=sorted(k for k in os.environ if not k.startswith("FAKE_AGY") and k not in ("__CF_USER_TEXT_ENCODING",
                                                                                                    "LC_CTYPE", "PWD", "SHLVL", "_")))
        try:
            while True:
                msg = self.recv()
                if msg is not None:
                    self.dispatch(msg)
        except Eof:
            pass
        if self.flags.get("home_item") and self.gemini and self.last_step == "resume_ask":
            (Path(self.gemini) / "config").mkdir(parents=True, exist_ok=True)
            (Path(self.gemini) / "config" / "hooks.json").write_text("{}")
        self.log(event="exit", code=0)
        return 0

    def dispatch(self, msg):
        method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if method == "initialize":
            self.write({"jsonrpc": "2.0", "id": rid, "result": INIT})
        elif method in ("session/new", "session/resume"):
            self.open_session(rid, method, params)
        elif method == "session/set_model":
            self.write({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/prompt":
            self.turn(rid, params)
        elif method is None and rid is not None:
            pass                                    # a late answer to a request of the turn that was cancelled
        elif rid is not None:
            self.write({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no"}})

    def open_session(self, rid, method, params):
        if self.flags.get("auth_error"):
            self.write({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "Authentication required"}})
            return
        sys_prompt = (((params.get("_meta") or {}).get("antigravity") or {}).get("systemPrompt") or {}).get("append")
        found = re.search(r"reply with the word (\S+?)\.", sys_prompt or "")
        self.sys_word = None if self.flags.get("no_system_prompt") else (found.group(1) if found else None)
        base = Path(self.gemini or self.cwd)
        (base / "config").mkdir(parents=True, exist_ok=True)
        (base / "config" / "config.json").write_text('{"plugins": ["swarm"]}')
        (base / "config" / "mcp_config.json").write_text("{}")
        if method == "session/new":
            self.session = "not-a-uuid" if self.flags.get("session_id_not_uuid") else str(uuid.uuid4())
            self.sessions_dir()
            result = {"sessionId": self.session, "models": MODELS, "modes": MODES, "configOptions": [{"id": "model"}],
                      "_meta": {"antigravity": {"tier": "fake-tier-alpha"}}}
        else:
            self.session = params.get("sessionId")
            result = {"models": MODELS, "modes": MODES, "configOptions": []}
        self.write({"jsonrpc": "2.0", "id": rid, "result": result})
        self.update(sessionUpdate="available_commands_update", availableCommands=[{"name": n, "description": "made-up"} for n in SKILLS])

    # -- one request of the agent, and what comes of the answer

    def permission(self, kind, title, raw, locations=None, content=None, ask=True):
        """(call id, "allow" | "deny" | "cancelled" | "silent")"""
        self.call_no += 1
        cid = f"call-{os.getpid()}-{self.call_no}"
        call = {"toolCallId": cid, "title": title, "kind": kind, "status": "pending", "rawInput": raw,
                "locations": locations or [], "content": content or []}
        self.update(sessionUpdate="tool_call", **{k: v for k, v in call.items()})
        if not ask:
            return cid, "silent"
        self.next_id += 1
        req = self.next_id
        self.write({"jsonrpc": "2.0", "id": req, "method": "session/request_permission",
                    "params": {"sessionId": self.session, "toolCall": call, "options": OPTIONS}})
        while True:
            msg = self.recv()
            if self.cancelled:
                return cid, "cancelled"
            if msg is not None and msg.get("id") == req and "method" not in msg:
                outcome = (msg.get("result") or {}).get("outcome") or {}
                if outcome.get("outcome") == "selected":
                    option = next((o for o in OPTIONS if o["optionId"] == outcome.get("optionId")), None)
                    return cid, {"allow_once": "allow", "reject_once": "deny"}.get(option["kind"] if option else None, "deny")
                return cid, "cancelled"
            if msg is not None and "method" in msg and msg.get("id") is not None:
                self.write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no"}})

    def finish_call(self, cid, ok, code=0, output=""):
        self.update(sessionUpdate="tool_call_update", toolCallId=cid, status="in_progress")
        self.update(sessionUpdate="tool_call_update", toolCallId=cid, status="completed" if ok else "failed",
                    rawOutput={"exit_code": code}, content=[{"type": "content", "content": {"type": "text", "text": output}}])

    # -- the simulated shell

    def roots(self):
        shared = self.shared and not self.flags.get("add_dir_ignored") and os.path.realpath(self.shared)
        return [r for r in (self.cwd, shared, os.path.realpath(self.tmpdir)) if r]

    def inside(self, path):
        real = os.path.realpath(path)
        return any(real == r or real.startswith(r + "/") for r in self.roots())

    def shell(self, command, ask=True, bypass=False):
        """(decision, exit code, output): the command in the simulated sandbox."""
        raw = {"CommandLine": command}
        if bypass:
            raw["BypassSandbox"] = True
        cid, decision = self.permission("execute", "Run a command", raw, ask=ask and not (self.flags.get("ls_unasked") and command == "ls -a"))
        if decision in ("deny", "cancelled"):
            if decision == "deny":
                self.update(sessionUpdate="tool_call_update", toolCallId=cid, status="failed")
                if self.flags.get("deny_ignored") and command.startswith("rm "):
                    self.run(command, bypass)
            return decision, None, ""
        code, out = self.run(command, bypass)
        self.finish_call(cid, True, code, out)
        return decision, code, out

    def run(self, command, bypass=False):
        free = bypass or self.flags.get("outside_escapes")
        cmd = command.strip()
        if cmd == "ls -a":
            return 0, "\n".join([".", ".."] + sorted(os.listdir(self.cwd)))
        m = re.fullmatch(r"rm (\S+)", cmd)
        if m:
            target = os.path.join(self.cwd, m.group(1))
            if not (free or self.inside(target)):
                return 1, "operation not permitted"
            try:
                os.unlink(target)
                return 0, ""
            except OSError as exc:
                return 1, str(exc)
        m = re.fullmatch(r"echo (\S+) > (.+)", cmd)
        if m:
            target = os.path.expandvars(shlex.split(m.group(2))[0]).replace("$TMPDIR", self.tmpdir)
            target = os.path.join(self.cwd, target)
            if not (free or self.inside(os.path.dirname(target))):
                return 1, "operation not permitted"
            Path(target).write_text(m.group(1) + "\n")
            return 0, ""
        m = re.fullmatch(r"cat (\S+)", cmd)
        if m:
            target = os.path.join(self.cwd, m.group(1))
            if not (free or self.inside(target)):
                return 1, "operation not permitted"
            try:
                return 0, Path(target).read_text()
            except OSError as exc:
                return 1, str(exc)
        if cmd.startswith("curl "):
            m = re.search(r"-o (\S+)", cmd)
            if self.flags.get("network_works") and m:
                Path(os.path.join(self.cwd, m.group(1))).write_text("data\n")
                return 0, "data"
            return 6, "could not resolve host"
        m = re.fullmatch(r"ln -s (\S+) (\S+)", cmd)
        if m:
            link = os.path.join(self.cwd, m.group(2))
            if not self.inside(os.path.dirname(link)):
                return 1, "operation not permitted"
            os.symlink(m.group(1), link)
            return 0, ""
        m = re.fullmatch(r"touch (\S+)", cmd)
        if m:
            Path(os.path.join(self.cwd, m.group(1))).touch()
            return 0, ""
        return 127, "command not found"

    def long_command(self, command):
        """``sleep N && touch F``: asked, then runs for N x scale seconds; a cancel ends it (unless the flag)."""
        m = re.fullmatch(r"sleep (\d+) && touch (\S+)", command)
        cid, decision = self.permission("execute", "Run a command", {"CommandLine": command})
        if decision != "allow":
            return decision
        self.update(sessionUpdate="tool_call_update", toolCallId=cid, status="in_progress")
        seconds = int(m.group(1)) * self.scale
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.cancelled:
                if self.flags.get("cancel_keeps_running"):
                    subprocess.Popen(["sh", "-c", f"sleep {max(0.1, end - time.monotonic()):.2f}; touch {shlex.quote(m.group(2))}"],
                                     cwd=self.cwd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                return "cancelled"
            self.recv(0.05)
        Path(os.path.join(self.cwd, m.group(2))).touch()
        self.finish_call(cid, True, 0, "")
        return "allow"

    # -- the file tool (not in the sandbox)

    def write_file(self, path, content, ask=True):
        where = path if os.path.isabs(path) else os.path.join(self.cwd, path)
        old = Path(where).read_text() if os.path.isfile(where) else None
        raw = {"Path": where, "Content": content}
        cid, decision = self.permission("edit", "Change a file", raw, [{"path": where}],
                                        [{"type": "diff", "path": where, "oldText": old, "newText": content}], ask=ask)
        escapes = self.flags.get("outside_edit_escapes") and (self.shared or not self.flags.get("only_shared"))
        if decision == "allow" or (decision == "deny" and escapes):
            os.makedirs(os.path.dirname(where), exist_ok=True)
            Path(where).write_text(content)
            if decision == "allow":
                self.finish_call(cid, True, 0, "")
            return decision
        if decision == "deny":
            self.update(sessionUpdate="tool_call_update", toolCallId=cid, status="failed")
        return decision

    def read_file(self, path, ask):
        where = path if os.path.isabs(path) else os.path.join(self.cwd, path)
        cid, decision = self.permission("read", "Read a file", {"Path": where}, [{"path": where}], ask=ask)
        if decision in ("allow", "silent"):
            try:
                text = Path(where).read_text()
            except OSError:
                text = ""
            self.finish_call(cid, True, 0, text)
            return decision, text
        if decision == "deny":
            self.update(sessionUpdate="tool_call_update", toolCallId=cid, status="failed")
        return decision, ""

    # -- a turn

    def say(self, text):
        self.update(sessionUpdate="agent_message_chunk", content={"type": "text", "text": text})

    def usage(self):
        tokens = self.conf.get("tokens") or {}
        fresh = tokens.get("first", 60000) if self.turns == 0 and not self.state().get("warm") else tokens.get("next", 6000)
        cached = 20000
        out = 1200
        total = fresh + cached + out + (1 if self.flags.get("bad_usage") else 0)
        return {"inputTokens": fresh, "outputTokens": out, "cachedReadTokens": cached, "cachedWriteTokens": 0,
                "thoughtTokens": 500, "totalTokens": total}

    def turn(self, rid, params):
        self.cancelled = False
        text = "".join(p.get("text", "") for p in params.get("prompt") or [] if isinstance(p, dict))
        step = (re.match(r"\[vbear-check:(\w+)\]", text) or [None, None])[1]
        self.last_step = step or self.last_step
        change = re.match(r"請把 (\S+) 寫成下面的內容：(.*)", text, re.S)
        self.update(sessionUpdate="agent_thought_chunk", content={"type": "text", "text": "(made-up thought)"})
        reply = self.act(step, text, change)
        if self.flags.get("settings_changed") and self.turns == 0 and self.gemini:
            (Path(self.gemini) / "antigravity-cli" / "settings.json").write_text("{}")
        prefix = f"{self.sys_word} " if self.sys_word else ""
        if self.cancelled:
            self.write({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled", "usage": self.usage()}})
        else:
            if self.flags.get("email_in_reply") and self.turns == 0:
                reply += " (write to person@example.org)"
            if self.flags.get("skill_in_reply") and self.turns == 0:
                reply += " (skill fake-skill-alpha)"
            self.say(prefix + reply)
            self.write({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn", "usage": self.usage()}})
        self.turns += 1
        Path(self.state_path).write_text(json.dumps({"warm": True}))

    def act(self, step, text, change):
        if change:
            written = change.group(2)
            if self.flags.get("edit_ignored"):
                written = "original"
            decision = self.write_file(change.group(1), written)
            return "Done." if decision == "allow" else "Refused."
        if step == "stream":
            return ",".join(str(i) for i in range(1, 41))
        if step in ("settings", "read_inside"):
            name = re.search(r"read the file (\S+) in", text).group(1)
            strict = self.settings_mode() == "strict" and not self.flags.get("strict_ignored")
            decision, content = self.read_file(name, ask=strict)
            return "I read it." if decision in ("allow", "silent") else "I could not read it."
        if step == "ask":
            return self.simple_commands(text)
        if step == "deny":
            return self.simple_commands(text)
        if step == "edit":
            decision = self.write_file("edit.txt", "original")
            return "Done." if decision == "allow" else "Refused."
        if step == "outside_edit":
            path = re.search(r"create the file (\S+) containing", text).group(1)
            decision = self.write_file(path, "outside")
            return "Done." if decision == "allow" else "Refused."
        if step in ("outside_shell", "network", "tmp_write", "shared_shell"):
            return self.simple_commands(text)
        if step == "bypass":
            command = EXACT.search(text).group(1)
            decision, code, _out = self.shell(command)
            if decision == "allow" and code not in (0, None):
                self.shell(command, bypass=True)
            return "Done."
        if step == "link_read":
            command = EXACT.search(text).group(1)
            decision, _code, _out = self.shell(command)
            if decision != "allow":
                return "Refused."
            if self.flags.get("link_leaks"):
                return "It says " + Path(re.match(r"ln -s (\S+)", command).group(1)).read_text().strip()
            decision, content = self.read_file("link.txt", ask=bool(self.flags.get("link_read_asks")))
            if decision in ("allow", "silent"):
                self.say("It says " + content.strip())
            return "Done."
        if step == "stop":
            command = EXACT.search(text).group(1)
            self.long_command(command)
            return "Stopped." if self.cancelled else "Done."
        if step == "resume":
            word = re.search(r"code word: (\S+)\.", text).group(1)
            (self.sessions_dir() / f"{self.session}.json").write_text(json.dumps({"word": word}))
            return "OK"
        if step == "resume_ask":
            try:
                word = json.loads((self.sessions_dir() / f"{self.session}.json").read_text())["word"]
            except (OSError, ValueError, KeyError):
                word = "unknown"
            return "I do not know." if self.flags.get("forgets") else word
        if step in ("shared_write", "shared_git"):
            path = re.search(r"create the file (\S+) containing", text).group(1)
            decision = self.write_file(path, "shared-ok")
            return "Done." if decision == "allow" else "Refused."
        if step == "shared_link":
            path = re.search(r"create the file (\S+) containing", text).group(1)
            decision = self.write_file(path, "link-ok")
            return "Done." if decision == "allow" else "Refused."
        return "ok"

    def simple_commands(self, text):
        for found in EXACT.finditer(text):
            decision, _code, _out = self.shell(found.group(1))
            if decision != "allow":
                break
        return "Done."


def write_launcher(path, config_path) -> str:
    """An executable named by ``path`` that runs this file with ``config_path`` as its configuration (a chat process is given a fixed
    environment, so the configuration cannot be found through HOME). It replaces itself with the Python process (``exec``), so that
    the process list shows tests/fake_agy_acp_check.py: a process a test left behind can be found by that name."""
    import shlex as _shlex
    body = (f"#!/bin/sh\nFAKE_AGY_CONFIG={_shlex.quote(str(config_path))} exec {_shlex.quote(sys.executable)} -I "
            f"{_shlex.quote(str(Path(__file__).resolve()))} \"$@\"\n")
    Path(path).write_text(body, encoding="utf-8")
    os.chmod(path, 0o755)
    return str(path)


def main(argv) -> int:
    path = os.environ.get("FAKE_AGY_CONFIG") or os.path.join(os.environ.get("HOME", ""), "fake-agy.json")
    try:
        conf = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        conf = {}
    if argv[:1] == ["--version"]:
        print(conf.get("version", VERSION))
        return 0
    if argv[:1] != ["acp"]:
        print("fake agy: only --version and acp are played", file=sys.stderr)
        return 2
    agent = Agent(conf, path, argv)
    signal.signal(signal.SIGTERM, lambda *_: (agent.log(event="sigterm", pid=os.getpid()), sys.exit(143)))
    return agent.serve()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
