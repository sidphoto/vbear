"""The fake ``codex`` of tests/fake_codex_app_server.py (P38-1): it must play the recorded 0.163.0 transcripts to what
VBear writes, in the order VBear writes it, so that the daemon tests (P38-3, P38-4) can run a chat without a real
Codex. These tests drive it over real pipes with the lines and the tracker of vbear.runtime.codex_chat_protocol."""

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

from tests import codex_chat_fixtures as ccf
from vbear.runtime import codex_chat_protocol as ccp

TIMEOUT = 15
CONSTS = ccp.VERSIONS["0.163.0"]


class Chat:
    """A fake codex process and a tracker, driven the way a session drives a real one."""

    def __init__(self, case, config, *, thread_id=None, last_total=None, expect_resume=False, argv=None):
        self.case = case
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbf")))
        case.addCleanup(shutil.rmtree, self.root, True)
        self.work = self.root / "work"
        self.home = self.root / "codex-home"
        self.work.mkdir(exist_ok=True)
        self.home.mkdir(exist_ok=True)
        self.config_path = self.root / "fake-codex.json"
        self.config_path.write_text(json.dumps(config))
        self.binary = ccf.write_launcher(self.root / "codex", self.config_path)
        self.log_path = Path(str(self.config_path) + ".log.jsonl")
        self.spawn(thread_id=thread_id, last_total=last_total, argv=argv)

    def spawn(self, *, thread_id=None, last_total=None, argv=None):
        env = {"PATH": os.environ.get("PATH", ""), "USER": "fake-user", "LOGNAME": "fake-user", "LANG": "C",
               "CODEX_HOME": str(self.home), "HOME": str(self.root / "home"),
               CONSTS.remote_control_env[0]: CONSTS.remote_control_env[1]}
        self.p = subprocess.Popen([self.binary] + (argv or ccp.argv_for(CONSTS)), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=self.work, env=env)
        self.case.addCleanup(self.kill, self.p)
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.t = ccp.CodexTracker(CONSTS, workdir=str(self.work), codex_home=str(self.home), thread_id=thread_id,
                                  resumed=thread_id is not None, last_total=last_total)
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
                if kind == "violation":
                    self.case.fail(f"violation: {data}")
                if kind in kinds:
                    return kind, data

    def of(self, kind):
        return [d for k, d in self.facts if k == kind]

    def start(self, resume_thread=None):
        """initialize, initialized, thread/start or thread/resume, all answered."""
        self.call(ccp.initialize_line, "initialize", "0.13.0")
        self.pump("initialized")
        self.write(ccp.initialized_line())
        if resume_thread:
            self.call(ccp.thread_resume_line, "thread_resume", resume_thread, cwd=str(self.work))
        else:
            self.call(ccp.thread_start_line, "thread_start", cwd=str(self.work))
        return self.pump("session_ready")[1]

    def send(self, text="hello"):
        self.t.begin_turn()
        self.call(ccp.turn_start_line, "turn_start", self.t.thread_id, text)

    def answer(self, request, decision):
        self.write(ccp.decision_line(request["request_id"], decision))
        (self.t.approve if decision == "accept" else self.t.refuse)(request["item_id"])

    def log(self):
        if not self.log_path.exists():
            return []
        return [json.loads(x) for x in self.log_path.read_text().splitlines()]

    def finish(self):
        self.p.stdin.close()
        return self.p.wait(timeout=TIMEOUT)


def config(**kw):
    base = {"start": {"fixture": "a", "turns": [0]}}
    base.update(kw)
    return base


class CliTests(unittest.TestCase):
    def run_fake(self, conf, *argv):
        d = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbf")))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "c.json").write_text(json.dumps(conf))
        launcher = ccf.write_launcher(d / "codex", d / "c.json")
        return subprocess.run([launcher, *argv], capture_output=True, text=True, timeout=TIMEOUT, cwd=d,
                              env={"PATH": os.environ.get("PATH", "")})

    def test_version_prints_the_line_the_real_one_prints(self):
        r = self.run_fake({}, "--version")
        self.assertEqual((r.returncode, r.stdout), (0, "codex-cli 0.163.0\n"))
        r = self.run_fake({"version": "0.170.1"}, "--version")
        self.assertEqual(r.stdout, "codex-cli 0.170.1\n")

    def test_login_status_is_the_exit_code(self):
        self.assertEqual(self.run_fake({}, "login", "status", "-c", 'cli_auth_credentials_store="file"').returncode, 0)
        r = self.run_fake({"login_status": 1}, "login", "status", "-c", 'cli_auth_credentials_store="file"')
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("@", r.stdout + r.stderr)

    def test_anything_else_is_refused_and_nothing_real_is_run(self):
        self.assertNotEqual(self.run_fake({}, "exec", "hi").returncode, 0)
        self.assertNotEqual(self.run_fake({}).returncode, 0)


class PlayTests(unittest.TestCase):
    def test_a_text_turn_in_a_new_thread(self):
        c = Chat(self, config())
        ready = c.start()
        self.assertEqual(ready["model"], "gpt-6.1-terra")
        self.assertEqual(ready["thread_id"], "00000000-0000-4000-8000-000000000003")
        c.send("Reply with exactly the single word: pineapple")
        _, done = c.pump("turn_completed")
        self.assertEqual((done["status"], done["tokens"]), ("completed", 18104))
        self.assertEqual([d["text"] for d in c.of("delta")], ["pine", "apple"])
        self.assertEqual(c.of("reply")[-1]["text"], "pineapple")
        text = json.dumps(c.facts, ensure_ascii=False)
        for secret in ccf.SENSITIVE + (str(c.home),):
            self.assertNotIn(secret, text, secret)
        self.assertEqual(c.finish(), 0)
        log = c.log()
        self.assertEqual(log[0]["event"], "start")
        self.assertEqual(log[0]["argv"], ccp.argv_for(CONSTS))
        self.assertEqual(log[0]["cwd"], str(c.work))
        self.assertEqual(sorted(log[0]["env_keys"]), sorted(["PATH", "USER", "LOGNAME", "LANG", "CODEX_HOME", "HOME",
                                                              CONSTS.remote_control_env[0]]))
        self.assertEqual(log[-1]["event"], "exit")

    def test_the_folder_and_the_codex_home_it_prints_are_the_real_ones(self):
        c = Chat(self, config())
        c.call(ccp.initialize_line, "initialize", "0.13.0")
        c.pump("initialized")                           # codexHome equals the folder the tracker was given
        c.write(ccp.initialized_line())
        c.call(ccp.thread_start_line, "thread_start", cwd=str(c.work))
        c.pump("session_ready")                         # its cwd equals the work folder
        sent = [x for x in c.log() if x["event"] == "stdin"]
        self.assertEqual([x["line"].get("method") for x in sent], ["initialize", "initialized", "thread/start"])

    def test_a_command_is_asked_about_and_runs_when_allowed(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [1]}))
        c.start()
        c.send("Run `ls -a`")
        _, req = c.pump("approval_request")
        self.assertEqual((req["kind"], req["action"], req["command"]), ("command", "ask", "/bin/zsh -lc 'ls -a'"))
        self.assertEqual(req["cwd"], str(c.work))
        c.answer(req, "accept")
        _, cmd = c.pump("command_done")
        self.assertEqual((cmd["status"], cmd["exit_code"]), ("completed", 0))
        _, done = c.pump("turn_completed")
        self.assertEqual(done["tokens"], 36426)

    def test_declining_what_was_recorded_as_allowed_declines_it(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [1]}))
        c.start()
        c.send("Run `ls -a`")
        _, req = c.pump("approval_request")
        c.answer(req, "decline")
        _, cmd = c.pump("command_done")
        self.assertEqual((cmd["status"], cmd["exit_code"], cmd["output"]), ("declined", None, None))
        c.pump("turn_completed")

    def test_allowing_what_was_recorded_as_declined_runs_it(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [3]}))
        c.start()
        c.send("Run exactly this shell command: rm shell.txt")
        _, req = c.pump("approval_request")
        c.answer(req, "accept")
        _, cmd = c.pump("command_done")
        self.assertEqual(cmd["status"], "completed")
        c.pump("turn_completed")

    def test_a_change_of_content_is_a_decline_a_steer_and_a_new_request(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [2]}))
        c.start()
        c.send("Run exactly this shell command: echo original > shell.txt")
        _, first = c.pump("approval_request")
        self.assertEqual(first["command"], "/bin/zsh -lc 'echo original > shell.txt'")
        c.answer(first, "decline")
        turn = c.of("turn_accepted")[0]["turn_id"]
        c.call(ccp.turn_steer_line, "turn_steer", c.t.thread_id, turn, "Run exactly this instead: echo changed")
        c.pump("steer_accepted")
        _, second = c.pump("approval_request")
        self.assertEqual(second["command"], "/bin/zsh -lc 'echo changed-by-user > shell.txt'")
        self.assertNotEqual((first["request_id"], first["item_id"]), (second["request_id"], second["item_id"]))
        c.answer(second, "accept")
        c.pump("turn_completed")
        self.assertEqual([x["status"] for x in c.of("command_done")], ["declined", "completed"])
        steers = [x["line"] for x in c.log() if x["event"] == "stdin" and x["line"].get("method") == "turn/steer"]
        self.assertEqual(len(steers), 1)
        self.assertEqual(steers[0]["params"]["input"][0]["text"], "Run exactly this instead: echo changed")

    def test_a_steer_after_the_turn_is_over_is_an_error_answer(self):
        c = Chat(self, config())
        c.start()
        c.send()
        c.pump("turn_completed")
        c.call(ccp.turn_steer_line, "turn_steer", c.t.thread_id, "turn-gone", "late")
        _, failed = c.pump("request_failed")
        self.assertEqual(failed["kind"], "turn_steer")
        self.assertIsInstance(failed["code"], int)

    def test_a_file_change_inside_the_work_folder_is_asked_about_with_its_diff(self):
        c = Chat(self, config(start={"fixture": "c-legacy-sandbox", "turns": [0]}))
        c.start()
        c.send("Create note2.txt")
        _, req = c.pump("approval_request")
        self.assertEqual((req["kind"], req["action"]), ("file_change", "ask"))
        self.assertEqual(req["changes"], [{"path": str(c.work / "note2.txt"), "kind": {"type": "add"},
                                           "diff": "hello\n"}])
        c.answer(req, "accept")
        self.assertEqual(c.pump("file_change_done")[1]["status"], "completed")
        c.pump("turn_completed")

    def test_a_file_change_outside_is_judged_a_denial_and_declined(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [5]}))
        c.start()
        c.send("Create a file outside")
        _, req = c.pump("approval_request")
        self.assertEqual((req["kind"], req["action"]), ("file_change", "deny"))
        c.answer(req, "decline")
        self.assertEqual(c.pump("file_change_done")[1]["status"], "declined")
        c.pump("turn_completed")

    def test_commands_the_sandbox_stopped_have_no_completion(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [6]}))
        c.start()
        c.send("Write and read outside")
        for _ in range(2):
            _, req = c.pump("approval_request")
            c.answer(req, "accept")
        _, done = c.pump("turn_completed")
        self.assertEqual(done["open_items"], 2)
        self.assertEqual(c.of("command_done"), [])

    def test_turns_are_played_in_the_order_configured_one_per_message(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [0, 1]}))
        c.start()
        c.send("one")
        self.assertEqual(c.pump("turn_completed")[1]["tokens"], 18104)
        c.send("two")
        _, req = c.pump("approval_request")
        c.answer(req, "accept")
        self.assertEqual(c.pump("turn_completed")[1]["tokens"], 36426)
        c.send("three")                                                # nothing recorded for it
        _, failed = c.pump("request_failed")
        self.assertEqual(failed["kind"], "turn_start")

    def test_a_new_process_resumes_the_thread_and_goes_on_with_the_next_recorded_turn(self):
        conf = config(start={"fixture": "a", "turns": [0]}, resume={"fixture": "b-resume", "turns": [0, 1]})
        c = Chat(self, conf)
        c.start()
        c.send("remember pineapple")
        c.pump("turn_completed")
        total = c.t.total_tokens
        thread = c.t.thread_id
        c.finish()
        c.spawn(thread_id=thread, last_total=total)                    # the second process, same configuration
        ready = c.start(resume_thread=thread)
        self.assertEqual((ready["thread_id"], ready["resumed"]), (thread, True))
        c.send("what word?")
        _, done = c.pump("turn_completed")
        self.assertEqual(done["tokens"], 19612)
        self.assertEqual(c.of("usage")[0]["delta_tokens"], 0)         # the repeated total adds nothing
        c.send("make a file")
        _, req = c.pump("approval_request")
        self.assertEqual(req["kind"], "file_change")
        self.assertEqual(req["changes"][0]["path"], str(c.work / "note.txt"))

    def test_the_thread_is_deleted_when_asked(self):
        conf = config(resume={"fixture": "b-resume", "turns": [0]})
        c = Chat(self, conf, thread_id="00000000-0000-4000-8000-000000000007")
        c.start(resume_thread="00000000-0000-4000-8000-000000000007")
        c.call(ccp.thread_delete_line, "thread_delete", c.t.thread_id)
        c.pump("delete_accepted")
        self.assertEqual(c.pump("thread_deleted")[1]["thread_id"], "00000000-0000-4000-8000-000000000007")

    def test_the_mcp_list_is_empty_when_clean_and_not_when_not(self):
        c = Chat(self, config())
        c.start()
        c.call(lambda i: ccp.mcp_status_list_line(i), "mcp_list")
        self.assertEqual(c.pump("mcp_checked")[1], {"count": 0})

    def test_a_person_s_own_setup_can_be_played_back_and_is_stopped(self):
        c = Chat(self, config(clean=False))
        c.call(ccp.initialize_line, "initialize", "0.13.0")
        c.pump("initialized")
        c.write(ccp.initialized_line())
        c.call(ccp.thread_start_line, "thread_start", cwd=str(c.work))
        while True:
            msg = c.q.get(timeout=TIMEOUT)
            out = c.t.on_message(msg)
            if any(k == "violation" for k, _ in out):
                break
        self.assertTrue(c.t.stopped)

    def test_an_unknown_server_request_gets_an_error_answer_and_the_process_goes_on(self):
        unknown = {"method": "item/tool/requestUserInput", "id": 900, "params": {"questions": []}}
        conf = config(start={"fixture": "a", "turns": [{"turn": 0, "inject": [unknown]}]})
        c = Chat(self, conf)
        c.start()
        c.send()
        _, req = c.pump("unknown_request")
        self.assertEqual((req["method"], req["refused"]), ("item/tool/requestUserInput", True))
        c.write(ccp.error_line(req["request_id"], "VBear 不接受這種請求"))
        c.pump("turn_completed")
        answers = [x["line"] for x in c.log() if x["event"] == "stdin" and "error" in x["line"]]
        self.assertEqual(answers, [{"id": req["request_id"], "error": {"code": -32601, "message": "VBear 不接受這種請求"}}])

    def test_an_interrupt_ends_the_turn_while_a_request_waits(self):
        c = Chat(self, config(start={"fixture": "a", "turns": [1]}))
        c.start()
        c.send("Run `ls -a`")
        c.pump("approval_request")
        turn = c.of("turn_accepted")[0]["turn_id"]
        c.call(ccp.turn_interrupt_line, "turn_interrupt", c.t.thread_id, turn)
        c.pump("interrupt_accepted")
        _, done = c.pump("turn_completed")
        self.assertEqual(done["status"], "interrupted")

    def test_a_request_the_script_does_not_expect_gets_an_error_and_is_logged(self):
        c = Chat(self, config())
        c.start()
        c.ids += 1
        c.write(json.dumps({"method": "model/list", "id": 4242, "params": {}}).encode() + b"\n")
        msg = c.q.get(timeout=TIMEOUT)
        while msg.get("id") != 4242:
            msg = c.q.get(timeout=TIMEOUT)
        self.assertEqual((msg["id"], msg["error"]["code"]), (4242, -32601))
        self.assertTrue(any(x["event"] == "unexpected" for x in c.log()))

    def test_closing_stdin_ends_the_process_with_zero(self):
        c = Chat(self, config())
        c.start()
        self.assertEqual(c.finish(), 0)
        self.assertEqual(c.log()[-1], {"event": "exit", "code": 0})


if __name__ == "__main__":
    unittest.main()
