"""A stand-in for ``codex`` 0.163.0 for the version check (vbear/codex_chat_check.py), which needs a Codex that does
what each message asks (tests/fake_codex_app_server.py only replays recordings and touches no file). It plays the
handshake of the recordings (tests/fixtures/codex-chat/) and then answers each ``turn/start`` by the step named in the
message, ``[vbear-check:<step>]``, the way a well-behaved Codex would, with real effects in the work folder:

  stream     numbers 1 to 40; remembers the code word of the message
  ask        ``ls -a`` is asked (item/commandExecution/requestApproval); allowed it runs. Then ``rm deny-target.txt`` is
             asked; declined it does not run
  edit       ``echo original > edit-probe.txt`` is asked; a decline and a ``turn/steer`` follow; the changed command in
             the steer is asked again in the same turn and, allowed, runs
  patch      a fileChange (add patch-probe.txt) is asked; allowed it is written
  outside    a fileChange outside the work folder (VBear declines it itself), then a shell command that writes there
             (allowed, the sandbox stops it: item/started only, as recorded)
  interrupt  streams a reply that does not end until ``turn/interrupt``
  memory     answers the code word
  (none)     "ok"

Configuration is the JSON file of tests/fake_codex_app_server.py (``start`` and ``resume`` name the recordings for the
handshake) with ``flags`` for the ways a Codex can go wrong:

  ls_unasked        ``ls -a`` runs without a request
  steer_rejected    ``turn/steer`` is answered with an error
  edit_ignored      after the steer the original command is asked again
  deny_ignored      the declined ``rm`` runs anyway
  outside_escapes   the sandbox does not stop the write outside
  forgets           the code word is not remembered after a resume
  tokens_back       the thread's token total goes back after a resume
  interrupt_rejected ``turn/interrupt`` is answered with an error
  ignore_eof        stdin closing does not end the process (it waits for SIGTERM)
  delete_fails      ``thread/delete`` is answered with an error
  late_exit         the process takes ``exit_delay`` seconds to end after stdin closes
  rollout           a file is made under CODEX_HOME/sessions for the thread, and removed by ``thread/delete``
  ignores_trust     ``thread/start`` writes a trust entry into CODEX_HOME/config.toml even when the work folder has
                    its own trust setting in the arguments

Like 0.163.0 it also writes that entry (``[projects."<work folder>"] trust_level = "trusted"``) when the arguments carry
no ``-c projects={...}`` for the work folder: a chat that was started without the setting is caught by the check.

Every model call costs ``call_tokens`` (default 18000) of the thread's running total, which is kept across processes.
Everything it is given goes to ``<config>.log.jsonl`` (tests/fake_codex_app_server.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

from tests import codex_chat_fixtures as ccf
from tests.fake_codex_app_server import Eof, Fake, main as base_main

TURN_ID = "00000000-0000-4000-8000-0000000000{:02d}"


class Probe(Fake):
    def __init__(self, conf, path):
        super().__init__(conf, path)
        self.flags = conf.get("flags") or {}
        self.call_tokens = int(conf.get("call_tokens", 18000))
        self.thread = None
        self.turn_id = None
        self.turn_no = 0
        self.next_req = 100
        self.item_no = 0

    # -- small writers

    def notify(self, method, params):
        self.write({"method": method, "params": params})

    def item_id(self):
        self.item_no += 1
        return f"fake-item-{os.getpid()}-{self.item_no}"

    def item(self, _kind, method, item):
        self.notify(method, {"threadId": self.thread, "turnId": self.turn_id, "item": item})

    def say(self, text, phase="final_answer"):
        iid = self.item_id()
        base = {"type": "agentMessage", "id": iid, "phase": phase, "memoryCitation": None, "delivery": None,
                "questions": None}
        self.item("agentMessage", "item/started", dict(base, text=""))
        for i in range(0, len(text), 3):
            self.notify("item/agentMessage/delta", {"threadId": self.thread, "turnId": self.turn_id, "itemId": iid,
                                                      "delta": text[i:i + 3]})
        self.item("agentMessage", "item/completed", dict(base, text=text))

    def model_call(self):
        state = self.state()
        run = state.get("tokens") or {"totalTokens": 0}
        if self.flags.get("tokens_back") and self.mode == "resume" and not state.get("went_back"):
            run = {"totalTokens": 0}
            state["went_back"] = True
        run["totalTokens"] = run.get("totalTokens", 0) + self.call_tokens
        state["tokens"] = run
        self.save(state)
        self.tokens = run
        usage = {"totalTokens": run["totalTokens"], "inputTokens": run["totalTokens"], "cachedInputTokens": 0,
                 "cacheWriteInputTokens": 0, "outputTokens": 0, "reasoningOutputTokens": 0}
        self.notify("thread/tokenUsage/updated", {"threadId": self.thread, "turnId": self.turn_id, "tokenUsage": {
            "total": usage, "last": dict(usage, totalTokens=self.call_tokens), "modelContextWindow": 100000}})
        self.notify("account/rateLimits/updated", {"rateLimits": {
            "limitId": "fake-limit", "limitName": None, "primary": {"usedPercent": 6, "windowDurationMins": 300,
                                                                      "resetsAt": 1793943244},
            "secondary": {"usedPercent": 27, "windowDurationMins": 10080, "resetsAt": 1794454231},
            "credits": {"hasCredits": False, "unlimited": False, "balance": "0"}, "planType": "fake_plan",
            "rateLimitReachedType": None}})

    def request(self, method, params):
        """A server request; returns the decision VBear answered."""
        rid = self.next_req
        self.next_req += 1
        self.write({"method": method, "id": rid, "params": dict(params, threadId=self.thread, turnId=self.turn_id)})
        msg = self.wait_for(lambda m: m.get("id") == rid and "method" not in m)
        self.notify("serverRequest/resolved", {"threadId": self.thread, "requestId": rid})
        result = msg.get("result") if isinstance(msg.get("result"), dict) else {}
        return result.get("decision")

    def wait_for(self, pred):
        while True:
            msg = self.read()
            if isinstance(msg, dict) and pred(msg):
                return msg
            self.unexpected(msg)

    # -- commands and files

    def command(self, shell, kind="listFiles", unasked=False, runs=True):
        """A command item. Returns "accept"/"decline". Run for real when accepted (``runs``)."""
        iid = self.item_id()
        cmd = f"/bin/zsh -lc '{shell}'"
        cwd = os.path.realpath(os.getcwd())
        base = {"type": "commandExecution", "id": iid, "pluginId": None, "scriptPath": None, "command": cmd,
                "cwd": cwd, "processId": None, "source": "agent", "commandActions": [
                    {"type": kind, "command": shell, "path": None}], "aggregatedOutput": None, "exitCode": None,
                "durationMs": None}
        self.item("commandExecution", "item/started", dict(base, status="inProgress"))
        decision = "accept" if unasked else self.request("item/commandExecution/requestApproval", {
            "kind": "command", "itemId": iid, "startedAtMs": 1, "environmentId": "local", "command": cmd, "cwd": cwd,
            "commandActions": base["commandActions"]})
        if decision != "accept":
            self.item("commandExecution", "item/completed", dict(base, status="declined"))
            return decision
        if not runs:
            return decision                       # the sandbox stopped it: no item/completed, as recorded
        done = subprocess.run(["/bin/sh", "-c", shell], cwd=cwd, capture_output=True, text=True, timeout=20)
        self.item("commandExecution", "item/completed", dict(base, status="completed", exitCode=done.returncode,
                                                             aggregatedOutput=done.stdout, processId="1"))
        return decision

    def file_change(self, path, text):
        iid = self.item_id()
        changes = [{"path": path, "kind": {"type": "add"}, "diff": text}]
        base = {"type": "fileChange", "id": iid, "changes": changes}
        self.item("fileChange", "item/started", dict(base, status="inProgress"))
        decision = self.request("item/fileChange/requestApproval", {"itemId": iid, "startedAtMs": 1, "reason": None,
                                                                    "grantRoot": None})
        if decision != "accept":
            self.item("fileChange", "item/completed", dict(base, status="declined"))
            return decision
        with open(path, "w") as f:
            f.write(text)
        self.item("fileChange", "item/completed", dict(base, status="completed"))
        return decision

    # -- the steps

    def step_stream(self, text):
        word = re.search(r"code word for this conversation is (\S+?)\.", text)
        state = self.state()
        state["code_word"] = word.group(1) if word else None
        self.save(state)
        self.model_call()
        self.say(" ".join(str(i) for i in range(1, 41)))

    def step_ask(self, text):
        self.say("I will run ls and rm.", phase="commentary")
        self.command("ls -a", unasked=bool(self.flags.get("ls_unasked")))
        self.model_call()
        decision = self.command("rm deny-target.txt", kind="unknown")
        if decision == "decline" and self.flags.get("deny_ignored"):
            subprocess.run(["/bin/rm", "-f", "deny-target.txt"], cwd=os.getcwd())
        self.model_call()
        self.say("The rm was refused.")
        self.model_call()

    def step_edit(self, text):
        self.say("I will write the file.", phase="commentary")
        decision = self.command("echo original > edit-probe.txt", kind="unknown")
        if decision == "decline":
            msg = self.wait_for(lambda m: m.get("method") == "turn/steer")
            if self.flags.get("steer_rejected"):
                self.write({"id": msg["id"], "error": {"code": -32600, "message": "no active turn to steer"}})
                self.model_call()
                self.say("Understood, I stop.")
                self.model_call()
                return
            self.respond(msg["id"], {"turnId": self.turn_id})
            asked = msg["params"]["input"][0]["text"]
            changed = asked.split("this shell command instead: ", 1)[-1]
            if self.flags.get("edit_ignored"):
                changed = "echo original > edit-probe.txt"
            self.model_call()
            self.command(changed, kind="unknown")
        self.model_call()
        self.say("Done.")
        self.model_call()

    def step_patch(self, text):
        self.say("I will use apply_patch.", phase="commentary")
        self.file_change(os.path.join(os.path.realpath(os.getcwd()), "patch-probe.txt"), "patched-by-codex\n")
        self.model_call()
        self.say("Done.")
        self.model_call()

    def step_outside(self, text):
        folder = re.search(r"(/\S+/outside)/outside-probe\.txt", text).group(1)
        self.say("I will write outside.", phase="commentary")
        if self.file_change(os.path.join(folder, "outside-probe.txt"), "outside\n") == "decline":
            self.model_call()
            shell = f"echo outside > {folder}/outside-shell.txt"
            escapes = bool(self.flags.get("outside_escapes"))
            self.command(shell, kind="unknown", runs=escapes)
            self.model_call()
        self.say("It was refused.")
        self.model_call()

    def step_interrupt(self, text):
        iid = self.item_id()
        base = {"type": "agentMessage", "id": iid, "phase": "final_answer", "memoryCitation": None, "delivery": None,
                "questions": None}
        self.item("agentMessage", "item/started", dict(base, text=""))
        self.notify("item/agentMessage/delta", {"threadId": self.thread, "turnId": self.turn_id, "itemId": iid,
                                                  "delta": "1\n2\n3\n"})
        while True:
            msg = self.wait_for(lambda m: m.get("method") == "turn/interrupt")
            if self.flags.get("interrupt_rejected"):
                self.write({"id": msg["id"], "error": {"code": -32600, "message": "cannot interrupt"}})
                self.model_call()
                return
            self.respond(msg["id"], {})
            self.interrupted = True
            return

    def step_memory(self, text):
        word = self.state().get("code_word")
        self.model_call()
        self.say("I do not know." if self.flags.get("forgets") else (word or "I do not know."))

    def step_free(self, text):
        if text.startswith("I changed the command"):          # VBear's fallback for a refused steer: left running until stopped
            return self.step_interrupt(text)
        self.model_call()
        self.say("ok")

    # -- the turn

    def scripted_turn(self, msg):
        params = msg["params"]
        self.thread = params["threadId"]
        self.turn_no += 1
        self.turn_id = TURN_ID.format(self.turn_no + 10)
        text = params["input"][0]["text"]
        found = re.match(r"\[vbear-check:(\w+)\]", text)
        step = found.group(1) if found else "free"
        turn = {"id": self.turn_id, "rootTurnId": self.turn_id, "items": [], "itemsView": "notLoaded",
                "status": "inProgress", "error": None}
        self.respond(msg["id"], {"turn": turn})
        self.notify("turn/started", {"threadId": self.thread, "turn": turn})
        self.interrupted = False
        self.in_turn = True
        try:
            getattr(self, "step_" + step, self.step_free)(text)
        finally:
            self.in_turn = False
        status = "interrupted" if self.interrupted else "completed"
        self.notify("turn/completed", {"threadId": self.thread, "turn": dict(turn, status=status)})

    # -- the process

    def idle(self, msg):
        method = msg.get("method") if isinstance(msg, dict) else None
        if method == "turn/start" and self.parsed is not None:
            return self.scripted_turn(msg)
        if method == "thread/delete" and "id" in msg and self.flags.get("delete_fails"):
            return self.respond_error(msg["id"], -32600, "cannot delete")
        super().idle(msg)
        if method == "thread/start":
            self.maybe_write_trust()
        if method in ("thread/start", "thread/resume") and self.flags.get("rollout"):
            self.rollout(msg["params"].get("threadId") or self.conf.get("thread_id"), make=True)
        if method == "thread/delete" and "id" in msg and self.flags.get("rollout"):
            self.rollout(msg["params"].get("threadId"), make=False)

    def maybe_write_trust(self):
        home = os.environ.get("CODEX_HOME")
        cwd = os.path.realpath(os.getcwd())
        given = any(a.startswith("projects={") and json.dumps(cwd, ensure_ascii=False) in a for a in sys.argv[1:])
        if home and (self.flags.get("ignores_trust") or not given):
            with open(os.path.join(home, "config.toml"), "w") as f:
                f.write(f'[projects.{json.dumps(cwd, ensure_ascii=False)}]\ntrust_level = "trusted"\n')

    def rollout(self, thread_id, make):
        home = os.environ.get("CODEX_HOME")
        if not (home and thread_id):
            return
        path = os.path.join(home, "sessions", f"rollout-{thread_id}.jsonl")
        if make:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{}\n")
        else:
            try:
                os.unlink(path)
            except OSError:
                pass

def main(argv) -> int:
    path = os.environ.get("FAKE_CODEX_CONFIG") or os.path.join(os.environ.get("HOME", ""), "fake-codex.json")
    try:
        with open(path) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = {}
    if argv[:1] != ["app-server"]:
        return base_main(argv)
    import signal
    fake = Probe(conf, path)
    signal.signal(signal.SIGTERM, lambda *_: (fake.log(event="sigterm", pid=os.getpid()), sys.exit(143)))
    flags = fake.flags
    code = fake.serve()
    if flags.get("ignore_eof"):
        time.sleep(3600)
    if flags.get("late_exit"):
        time.sleep(float(conf.get("exit_delay", 1)))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
