"""The fake ``agy`` of tests/fake_agy_acp.py (P46-1): it must play the synthetic 1.5.3 scripts to what VBear writes, in the order
VBear writes it, so that the daemon tests (P46-3, P46-4) can run a chat without a real AGY. These tests drive it over real pipes
with the lines and the tracker of vbear.runtime.agy_chat_protocol. No real ``agy`` is ever run."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from tests import agy_chat_fixtures as fx
from tests import leftover
from vbear.runtime import agy_chat_protocol as acp

TIMEOUT = 15
CONSTS = acp.VERSIONS["1.5.3"]
SESSION = fx.SESSION


class Chat:
    """A fake agy process and a tracker, driven the way a session drives a real one. The process lives under a temporary folder
    of its own; its VBEAR_HOME is that folder, so that a process a test left behind is found by tests/leftover.py."""

    def __init__(self, case, scripts, *, session_id=None, resumed=False, version="1.5.3", with_settings=False, shared=False):
        self.case = case
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba")))
        case.addCleanup(shutil.rmtree, self.root, True)
        case.addCleanup(leftover.assert_clean, self.root)           # runs after the process is killed, before the folder goes
        self.work = self.root / "work"
        self.gemini = self.root / "agy-chat-home"
        self.shared = self.root / "shared" if shared else None
        for d in (self.work, self.gemini):
            d.mkdir(exist_ok=True)
        if self.shared:
            self.shared.mkdir(exist_ok=True)
        if with_settings:
            (self.gemini / "antigravity-cli").mkdir()
            (self.gemini / "antigravity-cli" / "settings.json").write_bytes(acp.settings_bytes(CONSTS))
        self.config_path = self.root / "fake-agy.json"
        self.config_path.write_text(json.dumps({"version": version, "scripts": scripts}))
        self.binary = fx.write_launcher(self.root / "agy", self.config_path)
        self.log_path = Path(str(self.config_path) + ".log.jsonl")
        self.spawn(session_id=session_id, resumed=resumed)

    def spawn(self, *, session_id=None, resumed=False):
        env = {"PATH": os.environ.get("PATH", ""), "USER": "fake-user", "LOGNAME": "fake-user", "LANG": "C",
               "TMPDIR": str(self.root / "tmp"), "HOME": str(self.root / "home"), "VBEAR_HOME": str(self.root / "state")}
        argv = acp.argv_for(CONSTS, str(self.gemini), shared=str(self.shared) if self.shared else None)
        self.p = subprocess.Popen([self.binary] + argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  cwd=self.work, env=env)
        self.case.addCleanup(self.kill, self.p)
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.t = acp.AgyTracker(CONSTS, workdir=str(self.work), shared=str(self.shared) if self.shared else None,
                                session_id=session_id, resumed=resumed)
        self.facts: list = []
        self.ids = 0

    def _read(self):
        for raw in self.p.stdout:
            self.q.put(json.loads(raw))
        self.q.put(None)

    @staticmethod
    def kill(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        for pipe in (proc.stdin, proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def write(self, line: bytes):
        self.p.stdin.write(line)
        self.p.stdin.flush()

    def call(self, build, kind, *args, **kw) -> int:
        self.ids += 1
        self.t.expect(self.ids, kind)
        self.write(build(self.ids, *args, **kw))
        return self.ids

    def pump(self, kinds, timeout=TIMEOUT):
        """Read and track until a fact of one of ``kinds`` appears; its (kind, data), or the case fails."""
        kinds = {kinds} if isinstance(kinds, str) else set(kinds)
        while True:
            try:
                msg = self.q.get(timeout=timeout)
            except queue.Empty:
                self.case.fail(f"timeout waiting for {kinds}; facts so far {[k for k, _ in self.facts]}")
            if msg is None:
                self.case.fail(f"the process ended while waiting for {kinds}; facts {[k for k, _ in self.facts]}")
            out = self.t.on_message(msg)
            self.facts += out
            for kind, data in out:
                if kind in kinds:
                    return kind, data

    def of(self, kind):
        return [d for k, d in self.facts if k == kind]

    def start(self, system_prompt=None):
        self.call(acp.initialize_line, "initialize")
        self.pump("initialized")
        if self.t.resumed:
            self.call(acp.session_resume_line, "session_resume", self.t.session_id, cwd=str(self.work), system_prompt=system_prompt)
        else:
            self.call(acp.session_new_line, "session_new", cwd=str(self.work), system_prompt=system_prompt)
        ready = self.pump("session_ready")[1]
        self.call(acp.set_model_line, "set_model", self.t.session_id, CONSTS)
        self.pump("model_set")
        return ready

    def send(self, text="hello"):
        self.t.begin_turn()
        self.call(acp.prompt_line, "prompt", self.t.session_id, text)

    def answer(self, request, decision):
        self.t.answered(request["request_id"], decision)
        self.write(acp.answer_line(request["request_id"], request["options"], decision))

    def log(self):
        if not self.log_path.exists():
            return []
        return [json.loads(x) for x in self.log_path.read_text().splitlines()]

    def finish(self):
        self.p.stdin.close()
        return self.p.wait(timeout=TIMEOUT)


class CliTests(unittest.TestCase):
    def run_fake(self, conf, *argv):
        d = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba")))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "c.json").write_text(json.dumps(conf))
        launcher = fx.write_launcher(d / "agy", d / "c.json")
        return subprocess.run([launcher, *argv], capture_output=True, text=True, timeout=TIMEOUT, cwd=d,
                              env={"PATH": os.environ.get("PATH", "")})

    def test_version_prints_the_version_alone_on_one_line(self):
        r = self.run_fake({}, "--version")
        self.assertEqual((r.returncode, r.stdout), (0, "1.5.3\n"))
        r = self.run_fake({"version": "1.6.0"}, "--version")
        self.assertEqual(r.stdout, "1.6.0\n")

    def test_anything_else_is_refused_and_nothing_real_is_run(self):
        for argv in (["-p", "hi"], [], ["login"], ["--help"], ["changelog"], ["acp-ish"]):
            r = self.run_fake({}, *argv)
            self.assertNotEqual(r.returncode, 0, argv)
            self.assertEqual(r.stdout, "")

    def test_the_launcher_is_a_process_the_leftover_check_can_name(self):
        d = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba")))
        self.addCleanup(shutil.rmtree, d, True)
        launcher = fx.write_launcher(d / "agy", d / "c.json")
        text = Path(launcher).read_text()
        self.assertIn("fake_agy_acp.py", text)
        self.assertIn("exec ", text)


class PlayTests(unittest.TestCase):
    def test_a_text_turn_in_a_new_session(self):
        c = Chat(self, [{"fixture": "text"}], with_settings=True)
        ready = c.start(system_prompt="Be brief.")
        self.assertEqual(ready, {"session_id": SESSION, "resumed": False})
        c.send("Reply with a made-up sentence")
        _, done = c.pump("turn_completed")
        self.assertEqual((done["stop_reason"], done["tokens"]), ("end_turn", 86000))
        self.assertEqual(c.of("reply")[-1]["text"], "Hello, this is a made-up reply.")
        text = json.dumps(c.facts, ensure_ascii=False)
        for secret in fx.SENSITIVE + (str(c.root),):
            self.assertNotIn(secret, text, secret)
        self.assertEqual(c.finish(), 0)
        log = c.log()
        start = log[0]
        self.assertEqual(start["event"], "start")
        self.assertEqual(start["argv"], acp.argv_for(CONSTS, str(c.gemini)))
        self.assertEqual(start["cwd"], str(c.work))
        self.assertEqual(sorted(start["env_keys"]), sorted(["PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME", "VBEAR_HOME"]))
        self.assertEqual(start["settings_sha256"], __import__("hashlib").sha256(acp.settings_bytes(CONSTS)).hexdigest())
        self.assertEqual([x["line"]["method"] for x in log if x["event"] == "stdin"],
                         ["initialize", "session/new", "session/set_model", "session/prompt"])
        self.assertEqual(log[-1]["event"], "exit")
        self.assertFalse([x for x in log if x["event"] == "unexpected"])

    def test_it_says_when_the_settings_were_not_there(self):
        c = Chat(self, [{"fixture": "text"}])
        c.start()
        self.assertIsNone(c.log()[0]["settings_sha256"])

    def test_the_shared_folder_is_the_add_dir_argument(self):
        c = Chat(self, [{"fixture": "text"}], shared=True)
        c.start()
        self.assertEqual(c.log()[0]["shared"], str(c.shared))
        self.assertEqual(c.log()[0]["argv"][-2:], ["--add-dir", str(c.shared)])

    def test_a_command_is_asked_about_and_runs_when_allowed(self):
        c = Chat(self, [{"fixture": "permission"}])
        c.start()
        c.send("Run ls -a")
        _, req = c.pump("permission_request")
        self.assertEqual((req["action"], req["command"]), ("ask", "ls -a"))
        c.answer(req, "allow")
        _, done = c.pump("turn_completed")
        self.assertEqual(c.of("tool_result")[0]["exit_code"], 0)
        self.assertEqual(done["open_calls"], 0)
        self.assertEqual([x for x in c.log() if x["event"] == "choice"],
                         [{"event": "choice", "decision": "allow", "option_id": "allow", "kind": "allow_once"}])

    def test_a_command_that_is_refused_does_not_run(self):
        c = Chat(self, [{"fixture": "permission"}])
        c.start()
        c.send("Run ls -a")
        _, req = c.pump("permission_request")
        c.answer(req, "deny")
        c.pump("turn_completed")
        self.assertEqual(c.of("tool_result")[0]["status"], "failed")
        self.assertEqual(c.of("reply")[-1]["text"], "Understood, I did not do it.")

    def test_changing_what_runs_is_a_refusal_and_the_next_message(self):
        c = Chat(self, [{"fixture": "edit-input"}])
        c.start()
        c.send("Run echo one")
        _, first = c.pump("permission_request")
        c.answer(first, "deny")
        c.pump("turn_completed")
        c.send("Please run this instead: echo two")
        _, second = c.pump("permission_request")
        self.assertEqual(second["command"], "echo two")
        c.answer(second, "allow")
        c.pump("turn_completed")
        self.assertEqual(len(c.of("turn_completed")), 2)

    def test_a_wrong_option_in_the_list_is_never_picked_whatever_the_agent_offers(self):
        options = [{"optionId": "yes-always", "name": "Always", "kind": "allow_always"},
                   {"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                   {"optionId": "no-always", "name": "Never", "kind": "reject_always"},
                   {"optionId": "deny", "name": "Deny", "kind": "reject_once"}]
        for decision, expected in (("allow", "allow"), ("deny", "deny")):
            c = Chat(self, [{"fixture": "permission", "vars": {"OPTIONS": options}}])
            c.start()
            c.send("Run ls")
            _, req = c.pump("permission_request")
            c.answer(req, decision)
            c.pump("turn_completed")
            self.assertEqual([x["option_id"] for x in c.log() if x["event"] == "choice"], [expected])

    def test_bypass_sandbox_is_asked_for_and_refused_by_vbear(self):
        c = Chat(self, [{"fixture": "bypass"}])
        c.start()
        c.send("Write the file")
        _, first = c.pump("permission_request")
        c.answer(first, "allow")
        _, second = c.pump("permission_request")
        self.assertEqual((second["action"], second["why"]), ("deny", acp.REASON_BYPASS))
        c.answer(second, "deny")
        c.pump("turn_completed")
        self.assertEqual([x["decision"] for x in c.log() if x["event"] == "choice"], ["allow", "deny"])
        self.assertEqual(c.of("violation"), [])

    def test_a_tool_that_runs_without_asking_is_a_violation(self):
        c = Chat(self, [{"fixture": "no-ask"}])
        c.start()
        c.send("Do it")
        kind, data = c.pump("violation")
        self.assertIn("沒有經過 VBear 的允許", data["message"])

    def test_the_turn_is_stopped_with_cancel_and_the_cancelled_answer(self):
        c = Chat(self, [{"fixture": "cancel"}])
        c.start()
        c.send("Run sleep 60")
        _, req = c.pump("permission_request")
        c.write(acp.cancel_line(c.t.session_id))
        c.answer(req, "cancelled")
        _, done = c.pump("turn_completed")
        self.assertEqual((done["stop_reason"], done["tokens"]), ("cancelled", 86000))
        self.assertEqual([x["decision"] for x in c.log() if x["event"] == "choice"], ["cancelled"])

    def test_a_new_process_resumes_and_the_model_is_set_again(self):
        c = Chat(self, [{"fixture": "text"}, {"fixture": "resume"}])
        c.start()
        c.send("Remember the made-up word")
        c.pump("turn_completed")
        c.p.stdin.close()
        c.p.wait(timeout=TIMEOUT)
        c.spawn(session_id=SESSION, resumed=True)
        ready = c.start()
        self.assertEqual(ready, {"session_id": SESSION, "resumed": True})
        c.send("What was the word?")
        c.pump("turn_completed")
        self.assertEqual(c.of("reply")[-1]["text"], "I remember.")
        starts = [x for x in c.log() if x["event"] == "start"]
        self.assertEqual([s["script"] for s in starts], ["text", "resume"])
        methods = [x["line"]["method"] for x in c.log() if x["event"] == "stdin"]
        self.assertEqual(methods[-4:], ["initialize", "session/resume", "session/set_model", "session/prompt"])
        self.assertEqual(methods.count("session/set_model"), 2)

    def test_a_missing_sign_in_is_the_error_a_session_turns_into_not_logged_in(self):
        c = Chat(self, [{"fixture": "auth-error"}])
        c.call(acp.initialize_line, "initialize")
        c.pump("initialized")
        c.call(acp.session_new_line, "session_new", cwd=str(c.work))
        _, failed = c.pump("request_failed")
        self.assertEqual((failed["kind"], failed["auth_required"]), ("session_new", True))

    def test_what_the_script_does_not_expect_is_logged_and_a_request_is_answered_with_an_error(self):
        c = Chat(self, [{"fixture": "text"}])
        c.call(acp.initialize_line, "initialize")
        c.pump("initialized")
        c.write(acp.cancel_line(SESSION))                       # not part of the script
        c.write(acp.prompt_line(99, SESSION, "too early"))      # a request, not part of the script yet
        msg = c.q.get(timeout=TIMEOUT)
        self.assertEqual(msg["error"]["code"], -32601)
        self.assertEqual(c.finish(), 0)
        unexpected = [x for x in c.log() if x["event"] == "unexpected"]
        self.assertEqual([x["method"] for x in unexpected], ["session/cancel", "session/prompt"])

    def test_a_term_signal_ends_it_and_is_logged(self):
        c = Chat(self, [{"fixture": "text"}])
        c.start()
        c.p.terminate()
        self.assertEqual(c.p.wait(timeout=TIMEOUT), 143)
        self.assertEqual(c.log()[-1]["event"], "sigterm")

    def test_closing_stdin_ends_it_quietly(self):
        c = Chat(self, [{"fixture": "text"}])
        c.start()
        self.assertEqual(c.finish(), 0)
        self.assertEqual([x["event"] for x in c.log()][-2:], ["eof", "exit"])


class PlayerTests(unittest.TestCase):
    """The player in memory: the same script, no process."""

    def test_every_script_loads_and_names_itself_synthetic(self):
        for name in fx.names():
            defaults, rows = fx.load(name)
            self.assertTrue(rows, name)
            self.assertIsInstance(defaults, dict)
            for row in rows:
                self.assertIn(row["dir"], ("in", "out", "answer"), name)

    def test_a_variable_that_does_not_exist_is_an_error_not_a_hole(self):
        with self.assertRaises(KeyError):
            p = fx.Player("text")
            p.vars.pop("USAGE")
            for method in ("initialize", "session/new", "session/set_model", "session/prompt"):
                p.send({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})

    def test_a_script_without_a_header_that_says_synthetic_is_refused(self):
        d = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba")))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "x.jsonl").write_text('{"dir": "in", "method": "initialize"}\n')
        old = fx.DIR
        fx.DIR = d
        self.addCleanup(setattr, fx, "DIR", old)
        with self.assertRaises(ValueError):
            fx.load("x")


if __name__ == "__main__":
    unittest.main()
