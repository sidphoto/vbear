"""Chats with a role card whose AI tool is Codex, through the runtime daemon (P38-3), end to end with a fake ``codex``
(tests/fake_codex_app_server.py) that replays the turns recorded with 0.163.0 (tests/fixtures/codex-chat/). Synthetic
HOME and VBEAR_HOME under /tmp; the daemon listens on its own socket there, never the user's; nothing reaches a model or
the network, and the real codex is never run."""

from __future__ import annotations

import json
import os
import shutil
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import codex_chat_fixtures as ccf
from vbear import admin_policy
from vbear.runtime import agent_sessions as a
from vbear.runtime import chat_store as cs
from vbear.runtime import cli_versions
from vbear.runtime import codex_chat_protocol as ccp
from vbear.runtime import codex_chat_session as ccs
from vbear.runtime import daemon as d

TIMEOUT = 20.0
WAIT = 20.0
VERSION = "0.163.0"
THREAD = "00000000-0000-4000-8000-0000000000aa"
OTHER_THREAD = "00000000-0000-4000-8000-0000000000bb"


class CodexCase(unittest.TestCase):
    policy_ok = True

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbx-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.chat_home = self.base / "codex-chat-home"
        self.chat_home.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        v = mock.patch.object(cli_versions, "CODEX_CHAT_VERIFIED_VERSIONS", (VERSION,))
        v.start()
        self.addCleanup(v.stop)
        if self.policy_ok:
            p = mock.patch("vbear.runtime.daemon_chat.admin_policy.check_codex",
                           side_effect=lambda version, root="/": admin_policy.PolicyCheck(True))
            p.start()
            self.addCleanup(p.stop)
        self.conf_path = self.home / "fake-codex.json"
        self.binary = Path(ccf.write_launcher(self.tmp / "codex", self.conf_path))
        self.logs: list[str] = []
        self.start_daemon()

    def start_daemon(self):
        self.dm = d.Daemon(self.base, log=self.logs.append)
        self.dm.start()
        self.thread = threading.Thread(target=self.dm.serve_forever, daemon=True)
        self.thread.start()

    def stop_daemon(self):
        procs = [p.proc for p in list(self.dm._chats.values())] + [h["proc"] for h in self.dm._held_leaders]
        self.dm.stop()
        self.thread.join(10)
        self.dm.close()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            for f in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    f.close()
                except OSError:
                    pass

    def tearDown(self):
        self.stop_daemon()
        for rec in self.fake_log():
            if rec["event"] == "start":
                try:
                    os.kill(rec["pid"], signal.SIGKILL)
                except OSError:
                    pass

    # ---- helpers --------------------------------------------------------------------------------------------

    def rpc(self, op, **kw):
        return d.rpc(op, base=self.base, timeout=TIMEOUT, **kw)

    def configure(self, start=None, resume=None, **extra):
        conf = {"version": VERSION, "login_status": 0, "clean": True, "thread_id": THREAD}
        if start is not None:
            conf["start"] = {"fixture": "a", "turns": start}
        if resume is not None:
            conf["resume"] = {"fixture": "b-resume", "turns": resume}
        conf.update(extra)
        self.conf_path.write_text(json.dumps(conf))

    def cli(self, **over):
        cli = {"binary": str(self.binary), "version": VERSION, "identity": a.binary_identity(str(self.binary))}
        cli.update(over)
        return cli

    def open_chat(self, profile="emp-1"):
        r = self.rpc("chat_open", profile_id=profile, engine="codex-chat")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["engine"], "codex-chat")
        return r["result"]["chat_id"]

    def send(self, chat_id, text="hello", model_id=None, **kw):
        return self.rpc("chat_send", chat_id=chat_id, text=text, cli=kw.pop("cli", None) or self.cli(),
                        model_id=model_id, **kw)

    def events(self, chat_id):
        out, after = [], 0
        while True:
            r = self.rpc("chat_events", chat_id=chat_id, after=after)
            self.assertTrue(r["ok"], r)
            out += r["result"]["records"]
            after = r["result"]["next_after"]
            if not r["result"]["more"]:
                return out, r["result"]["live"]

    def wait(self, pred, what, timeout=WAIT):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = pred()
            if got:
                return got
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}; daemon log: {self.logs[-8:]}")

    def wait_card(self, chat_id, count=1):
        def card():
            _, live = self.events(chat_id)
            return live and len(live["cards"]) >= count and live["cards"][count - 1]
        return self.wait(card, "a card")

    def wait_turn(self, chat_id, n):
        def ended():
            recs, _ = self.events(chat_id)
            return next((r for r in recs if r["kind"] == "turn_ended" and r["turn"] == n), None)
        return self.wait(ended, f"the end of turn {n}")

    def wait_gone(self, chat_id):
        self.wait(lambda: chat_id not in self.dm._chats and self.events(chat_id)[1] is None, "the process to end")

    def answer(self, chat_id, card, decision, value=None):
        return self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"],
                        decision=decision, value=value)

    def fake_log(self):
        path = Path(str(self.conf_path) + ".log.jsonl")
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def stdin(self):
        return [r["line"] for r in self.fake_log() if r["event"] == "stdin"]

    def decisions(self):
        """What VBear answered to the server's requests, by decision."""
        return [x["result"]["decision"] for x in self.stdin() if "method" not in x and isinstance(x.get("result"), dict)
                and "decision" in x["result"]]

    def methods(self):
        return [x["method"] for x in self.stdin() if "method" in x]

    def kinds(self, chat_id):
        return [r["kind"] for r in self.events(chat_id)[0]]

    def raw(self, chat_id):
        return (self.base / "chats" / chat_id / "events.jsonl").read_text()

    def work(self, profile="emp-1"):
        return cs.ensure_work_dir(self.base, profile)

    def usage(self, total, thread=THREAD):
        return {"method": "thread/tokenUsage/updated", "params": {"threadId": thread, "turnId": "t-inject", "tokenUsage": {
            "total": {"totalTokens": total}, "last": {"totalTokens": total}, "modelContextWindow": 1}}}

    def assert_nothing_dangerous_was_sent(self):
        text = json.dumps(self.stdin())
        for word in ("acceptForSession", "acceptWithExecpolicyAmendment", "applyNetworkPolicyAmendment", "cancel"):
            self.assertNotIn(word, text)
        for decision in self.decisions():
            self.assertIn(decision, ("accept", "decline"))

    def assert_nothing_of_the_account_kept(self, chat_id):
        reply = json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        for text in (self.raw(chat_id), reply, "\n".join(self.logs)):
            for secret in ccf.SENSITIVE + (str(self.chat_home), "gpt-6.1-sol-user"):
                self.assertNotIn(secret, text)


class TextTests(CodexCase):
    def test_a_plain_text_turn_and_how_the_process_was_started(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        r = self.send(chat_id, "Reply with exactly the single word: pineapple", instructions="先說結論。")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["cap_usd"], r["result"]["process"]), (1, "0.5", "new"))
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["reported"], end["total_usd"]),
                         ("result", "0.02", False, None))
        self.assertEqual((end["estimate"], end["tokens"], end["subtype"], end["is_error"]), (True, 18104, "completed", False))
        recs = self.events(chat_id)[0]
        kinds = [x["kind"] for x in recs]
        for k in ("user_message", "turn_started", "process_started", "session_ready", "session_bound", "usage",
                  "reply", "turn_ended"):
            self.assertIn(k, kinds)
        self.assertEqual(next(x for x in recs if x["kind"] == "reply")["text"], "pineapple")
        self.assertEqual(next(x for x in recs if x["kind"] == "session_bound")["thread_id"], THREAD)
        self.assertEqual(next(x for x in recs if x["kind"] == "usage")["delta_tokens"], 18104)
        plan = next(x for x in recs if x["kind"] == "plan_usage")
        self.assertEqual((plan["primary_window_min"], plan["secondary_window_min"]), (300, 10080))
        # how it was started
        start = next(x for x in self.fake_log() if x["event"] == "start")
        consts = ccp.VERSIONS[VERSION]
        self.assertEqual(start["argv"], ccp.argv_for(consts))
        self.assertEqual(sorted(start["env_keys"]), sorted(consts.env_keys))
        self.assertEqual(start["cwd"], self.work())
        self.assertEqual(start["codex_home"], str(self.chat_home))
        lines = self.stdin()
        self.assertEqual([x["method"] for x in lines if "method" in x][:4],
                         ["initialize", "initialized", "thread/start", "mcpServerStatus/list"])
        self.assertEqual(lines[0]["params"]["capabilities"], {"experimentalApi": False})
        begin = next(x for x in lines if x.get("method") == "thread/start")
        self.assertEqual(begin["params"], {
            "cwd": self.work(), "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "workspace-write",
            "developerInstructions": "先說結論。", "ephemeral": False, "serviceName": "vbear"})
        turn = next(x for x in lines if x.get("method") == "turn/start")
        self.assertEqual(turn["params"]["input"], [{"type": "text", "text": "Reply with exactly the single word: pineapple"}])
        self.assertEqual(turn["params"]["approvalPolicy"], "untrusted")
        self.assertEqual(turn["params"]["sandboxPolicy"], ccp.SANDBOX_POLICY)
        self.assertEqual(cs.load(self.base, chat_id)["engine"], "codex-chat")
        self.assertNotIn("claude_session_id", cs.load(self.base, chat_id))
        self.assert_nothing_of_the_account_kept(chat_id)
        self.assert_nothing_dangerous_was_sent()

    def test_the_process_is_left_idle_and_the_next_message_goes_to_it(self):
        self.configure(start=[0, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send(chat_id, "again")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "reused"))
        end = self.wait_turn(chat_id, 2)
        self.assertEqual(end["tokens"], 18104)
        self.assertEqual(len([x for x in self.fake_log() if x["event"] == "start"]), 1)
        self.assertEqual(self.methods().count("thread/start"), 1)
        self.assertEqual(self.methods().count("turn/start"), 2)

    def test_the_engine_a_message_names_must_be_the_chats(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        r = self.send(chat_id, engine="claude-chat")
        self.assertEqual(r["error"]["code"], "bad_request")
        claude = self.rpc("chat_open", profile_id="emp-2")
        self.assertEqual(claude["result"]["engine"], "claude-chat")
        r = self.send(claude["result"]["chat_id"], engine="codex-chat")
        self.assertEqual(r["error"]["code"], "bad_request")
        r = self.send(claude["result"]["chat_id"])           # no model: a Claude chat needs one
        self.assertEqual(r["error"]["code"], "bad_request")
        self.assertEqual(self.fake_log(), [])


class CardTests(CodexCase):
    def test_a_command_is_asked_even_when_it_only_reads_and_allow_runs_it(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id, "run ls")["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("command", "command"))
        self.assertEqual(card["input"]["command"], "/bin/zsh -lc 'ls -a'")
        self.assertEqual(card["input"]["cwd"], ".")
        self.assertEqual(card["input"]["actions"], [{"type": "listFiles", "command": "ls -a"}])
        self.assertEqual(self.answer(chat_id, card, "allow")["ok"], True)
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["tokens"]), ("result", "0.04", 36426))
        self.assertEqual(self.decisions(), ["accept"])
        recs = self.events(chat_id)[0]
        self.assertEqual([x["decision"] for x in recs if x["kind"] == "card_decision"], ["allow"])
        done = next(x for x in recs if x["kind"] == "tool_result")
        self.assertEqual((done["tool"], done["is_error"], done["source"]), ("command", False, "codex"))
        call = next(x for x in recs if x["kind"] == "tool_call")
        self.assertEqual((call["tool"], call["summary"]), ("command", "/bin/zsh -lc 'ls -a'"))
        self.assert_nothing_dangerous_was_sent()

    def test_deny_declines_and_nothing_runs(self):
        self.configure(start=[3])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(card["input"]["command"], "/bin/zsh -lc 'rm shell.txt'")
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        self.assertEqual(self.decisions(), ["decline"])
        recs = self.events(chat_id)[0]
        self.assertEqual([x["decision"] for x in recs if x["kind"] == "card_decision"], ["deny"])
        self.assertNotIn("tool_result", [x["kind"] for x in recs])            # a declined command ran nothing

    def test_a_changed_command_is_a_decline_and_a_steer_and_codex_asks_again(self):
        self.configure(start=[2])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        first = self.wait_card(chat_id)
        self.assertEqual(first["input"]["command"], "/bin/zsh -lc 'echo original > shell.txt'")
        r = self.answer(chat_id, first, "modify", "echo changed-by-user > shell.txt")
        self.assertTrue(r["ok"], r)
        second = self.wait(lambda: next((c for c in (self.events(chat_id)[1] or {"cards": []})["cards"]
                                         if c["card_id"] != first["card_id"]), None), "the second card")
        self.assertEqual(second["input"]["command"], "/bin/zsh -lc 'echo changed-by-user > shell.txt'")
        self.assertNotEqual(second["card_id"], first["card_id"])
        lines = self.stdin()
        steer = next(x for x in lines if x.get("method") == "turn/steer")
        text = steer["params"]["input"][0]["text"]
        self.assertTrue(text.endswith("echo changed-by-user > shell.txt"), text)
        self.assertEqual(steer["params"]["threadId"], THREAD)
        turn_id = next(x for x in self.events(chat_id)[0] if x["kind"] == "card")             # the turn is the first
        self.assertEqual(turn_id["turn"], 1)
        self.assertEqual(self.decisions(), ["decline"])                         # the first card was declined, once
        self.assertTrue(self.answer(chat_id, second, "allow")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["tokens"]), ("result", "0.06", 55308))
        self.assertEqual(self.decisions(), ["decline", "accept"])
        recs = self.events(chat_id)[0]
        self.assertEqual([(x["decision"], x["value"]) for x in recs if x["kind"] == "card_decision"],
                         [("modify", "echo changed-by-user > shell.txt"), ("allow", None)])
        sent = next(x for x in recs if x["kind"] == "card_edit_sent")
        self.assertEqual((sent["card_id"], sent["text"]), (first["card_id"], text))
        self.assertEqual(len([x for x in recs if x["kind"] == "card"]), 2)
        self.assert_nothing_dangerous_was_sent()

    def test_a_steer_that_codex_refuses_becomes_the_next_message(self):
        # the recorded turn ends right after the decline (nothing to steer): the changed text is a new turn
        self.configure(start=[3, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "modify", "echo changed-by-user > shell.txt")["ok"])
        end = self.wait_turn(chat_id, 2)
        self.assertEqual(end["reason"], "result")
        recs = self.events(chat_id)[0]
        said = [x for x in recs if x["kind"] == "user_message"]
        self.assertEqual(len(said), 2)
        self.assertTrue(said[1]["text"].endswith("echo changed-by-user > shell.txt"))
        self.assertEqual([x["turn"] for x in recs if x["kind"] == "turn_started"], [1, 2])
        turns = [x for x in self.stdin() if x.get("method") == "turn/start"]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[1]["params"]["input"][0]["text"], said[1]["text"])
        self.assertEqual(len([x for x in self.fake_log() if x["event"] == "start"]), 1)

    def test_a_changed_text_that_cannot_be_sent_as_a_new_turn_says_so(self):
        # the day's limit is the turn's cap (US$0.04): the recorded turn reaches it, so the day is closed (red) when the
        # steer's refusal asks for a new turn
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {
            "per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.04}}))
        self.configure(start=[3, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "modify", "echo changed-by-user > shell.txt")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("limit", "0.04"))
        error = self.wait(lambda: next((x for x in self.events(chat_id)[0] if x["kind"] == "error"), None), "the error")
        self.assertTrue(error["message"].startswith("改過的內容沒有送出："), error)
        recs = self.events(chat_id)[0]
        self.assertEqual(len([x for x in recs if x["kind"] == "user_message"]), 1)
        self.assertEqual(self.methods().count("turn/start"), 1)

    def test_a_file_change_is_a_card_with_its_path_and_diff(self):
        self.configure(start=[4])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("file_change", "content"))
        self.assertEqual(card["input"]["changes"], [{"path": "note.txt", "kind": "add", "diff": "hello from codex\n"}])
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        self.assertEqual(self.decisions(), ["accept"])
        done = next(x for x in self.events(chat_id)[0] if x["kind"] == "tool_result")
        self.assertEqual((done["tool"], done["is_error"]), ("file_change", True))        # the recorded patch failed
        self.assert_nothing_dangerous_was_sent()

    def test_a_file_outside_the_work_folder_is_refused_without_a_card(self):
        self.configure(start=[5])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        self.assertEqual(self.decisions(), ["decline"])
        recs = self.events(chat_id)[0]
        self.assertNotIn("card", [x["kind"] for x in recs])
        denied = next(x for x in recs if x["kind"] == "denied")
        self.assertEqual((denied["tool"], denied["by"]), ("file_change", "vbear"))
        self.assertIn("以外", denied["reason"])

    def test_a_path_under_dot_codex_is_refused_without_a_card(self):
        work = self.work()
        change = {"path": f"{work}/.codex/config.toml", "kind": {"type": "add"}, "diff": "x\n"}
        item = {"id": "inject-fc", "type": "fileChange", "status": "inProgress", "changes": [change]}
        started = {"method": "item/started", "params": {"threadId": THREAD, "turnId": "t-inject", "item": item,
                                                         "startedAtMs": 1}}
        ask = {"method": "item/fileChange/requestApproval", "id": "inject-req",
               "params": {"threadId": THREAD, "turnId": "t-inject", "itemId": "inject-fc", "startedAtMs": 1,
                          "reason": None, "grantRoot": None}}
        self.configure(start=[{"turn": 0, "inject": [started, ask]}])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        self.assertEqual(self.decisions(), ["decline"])
        recs = self.events(chat_id)[0]
        self.assertNotIn("card", [x["kind"] for x in recs])
        denied = next(x for x in recs if x["kind"] == "denied")
        self.assertIn(".codex", denied["reason"])

    def test_an_item_that_never_completes_is_not_a_violation(self):
        self.configure(start=[6, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        for count in (1, 2):
            card = self.wait(lambda: next((c for c in (self.events(chat_id)[1] or {"cards": []})["cards"]), None),
                             f"card {count}")
            self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
            self.wait(lambda: len([x for x in self.events(chat_id)[0] if x["kind"] == "card_decision"]) == count, "it")
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        self.assertIn(chat_id, self.dm._chats)
        self.assertTrue(self.send(chat_id)["ok"])                       # still a live, usable process
        self.wait_turn(chat_id, 2)

    def test_an_unknown_server_request_is_answered_with_an_error_and_the_chat_goes_on(self):
        ask = {"method": "item/tool/requestUserInput", "id": "inject-ui",
               "params": {"threadId": THREAD, "turnId": "t-inject", "itemId": "x", "questions": []}}
        self.configure(start=[{"turn": 0, "inject": [ask]}])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        answer = next(x for x in self.stdin() if x.get("id") == "inject-ui")
        self.assertEqual(answer["error"]["code"], -32601)
        anomaly = next(x for x in self.events(chat_id)[0] if x["kind"] == "anomaly")
        self.assertEqual(anomaly["event_type"], "server_request/item/tool/requestUserInput")
        self.assertIn(chat_id, self.dm._chats)

    def test_a_second_answer_a_wrong_token_and_an_expired_card_are_refused(self):
        self.configure(start=[1])
        self.dm.chat_card_ttl = 1.0
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token="x" * 32, decision="allow")
        self.assertEqual(r["error"]["code"], "bad_token")
        self.wait(lambda: self.decisions(), "the expiry's decline")
        self.assertEqual(self.decisions(), ["decline"])
        r = self.answer(chat_id, card, "allow")
        self.assertEqual(r["error"]["code"], "gone")
        self.wait_turn(chat_id, 1)
        self.assertEqual([x["decision"] for x in self.events(chat_id)[0] if x["kind"] == "card_decision"], ["expired"])
        self.assertEqual(self.decisions(), ["decline"])

    def test_an_answer_twice_is_gone_and_only_one_decision_is_written(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        self.assertEqual(self.answer(chat_id, card, "deny")["error"]["code"], "gone")
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.decisions(), ["accept"])

    def test_the_wrong_kind_of_answer_is_refused(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        for decision, value in (("maybe", None), ("allow", "x"), ("modify", None), ("modify", "  "), ("modify", 5),
                                ("modify", "x" * 5000)):
            r = self.answer(chat_id, card, decision, value)
            self.assertEqual(r["error"]["code"], "bad_request", (decision, value))
        self.assertEqual(self.decisions(), [])
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)


class ViolationTests(CodexCase):
    def violation(self, inject, word, turn=0):
        self.configure(start=[{"turn": turn, "inject": inject, "hold": True}])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["reported"]), ("violation", "0.5", False))
        error = next(x for x in self.events(chat_id)[0] if x["kind"] == "error")
        self.assertIn(word, error["message"])
        self.wait_gone(chat_id)
        return chat_id

    def test_one_more_mcp_server_stops_the_chat(self):
        note = {"method": "mcpServer/startupStatus/updated",
                "params": {"name": "fake-mcp-name", "status": "starting", "error": None, "threadId": THREAD}}
        chat_id = self.violation([note], "MCP")
        self.assertNotIn("fake-mcp-name", self.raw(chat_id))
        self.assertNotIn("fake-mcp-name", "\n".join(self.logs))

    def test_another_thread_stops_the_chat(self):
        self.violation([{"method": "thread/started", "params": {"thread": {"id": OTHER_THREAD}}}], "別的對話")

    def test_a_command_completed_without_vbears_yes_stops_the_chat(self):
        item = {"id": "inject-cmd", "type": "commandExecution", "status": "completed", "command": "ls", "exitCode": 0,
                "aggregatedOutput": "x"}
        done = {"method": "item/completed", "params": {"threadId": THREAD, "turnId": "t-inject", "item": item}}
        self.violation([done], "沒有經過 VBear 的允許")

    def test_a_kind_of_item_that_is_not_offered_stops_the_chat(self):
        item = {"id": "inject-web", "type": "webSearch", "query": "x"}
        started = {"method": "item/started", "params": {"threadId": THREAD, "turnId": "t-inject", "item": item}}
        self.violation([started], "webSearch")

    def test_the_persons_own_settings_in_the_answer_stop_the_chat_before_the_message(self):
        self.configure(start=[0], clean=False)           # the recording as made: their AGENTS.md, five MCP servers
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["tokens"]), ("not_sent", "0", None))
        self.wait_gone(chat_id)
        self.assertNotIn("turn/start", self.methods())
        self.assert_nothing_of_the_account_kept(chat_id)


class LimitTests(CodexCase):
    def test_a_turn_over_its_time_is_stopped_at_its_cap(self):
        self.dm.chat_turn_timeout = 1.0
        self.configure(start=[{"turn": 0, "inject": [], "hold": True}])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["reported"], end["estimate"]), ("error", "0.5", False, False))
        self.wait_gone(chat_id)
        self.assertIn("process_ended", self.kinds(chat_id))
        self.assertIn("sigterm", [x["event"] for x in self.fake_log()])

    def test_tokens_that_reach_the_cap_interrupt_the_turn_and_the_estimate_is_kept(self):
        (self.base / "config.json").write_text(json.dumps({"chat_limits": {"per_turn_usd": 0.01}}))
        self.configure(start=[{"turn": 0, "inject": [self.usage(20000)], "hold": True}])
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.assertEqual(r["result"]["cap_usd"], "0.01")
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"], end["tokens"], end["is_error"]),
                         ("limit", "0.02", True, 20000, True))
        self.assertEqual(self.methods().count("turn/interrupt"), 1)
        self.assertIn(chat_id, self.dm._chats)              # the process goes on: only the turn was cut
        self.assertTrue(self.wait(lambda: self.dm._chats[chat_id].idle, "idle"))

    def test_a_turn_that_ends_by_itself_after_the_cap_is_still_counted_by_its_tokens(self):
        (self.base / "config.json").write_text(json.dumps({"chat_limits": {"per_turn_usd": 0.01}}))
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)                      # the tokens are counted after the command ran
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["tokens"], end["estimate"]), ("limit", "0.04", 36426, True))
        self.assertEqual(self.methods().count("turn/interrupt"), 1)

    def test_a_day_with_less_than_a_cent_left_sends_nothing(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        other = cs.create(self.base, "emp-2", now=time.time(), engine="codex-chat")
        log = cs.ChatLog(self.base, other["id"])
        try:
            log.append("user_message", {"turn": 1, "text": "hi"}, now=time.time())
            log.append("turn_started", {"turn": 1, "cap_usd": "0.5"}, now=time.time())
            log.append("turn_ended", {"turn": 1, "cost_usd": "2.999", "reported": False, "total_usd": None,
                                      "reason": "result", "subtype": "completed", "is_error": False, "estimate": True,
                                      "tokens": 5}, now=time.time())
        finally:
            log.close()
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {
            "per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 3}}))
        r = self.send(chat_id)
        self.assertEqual(r["error"]["code"], "budget", r)
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {
            "per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.01}}))
        self.assertEqual(self.send(chat_id)["error"]["code"], "red")
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id).count("user_message"), 0)

    def test_stop_interrupts_and_ends_the_turn_at_its_cap(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("stopped", "0.5"))
        self.wait_gone(chat_id)
        self.assertEqual(self.methods().count("turn/interrupt"), 1)
        self.assertEqual(self.decisions(), ["decline"])         # the waiting card was declined
        self.assertEqual([x["decision"] for x in self.events(chat_id)[0] if x["kind"] == "card_decision"], ["cancelled"])


class LifecycleTests(CodexCase):
    def test_after_an_idle_close_the_next_message_resumes_the_thread_and_counts_only_its_own_tokens(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertIn("eof", [x["event"] for x in self.fake_log()])           # closed by its stdin, not a signal
        r = self.send(chat_id, "what word?")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "resume"))
        end = self.wait_turn(chat_id, 2)
        # the resumed thread repeats the total it had (18104) first: not this turn's; the turn used 19612
        self.assertEqual((end["tokens"], end["cost_usd"], end["reason"]), (19612, "0.02", "result"))
        self.assertEqual(self.methods().count("thread/start"), 1)
        resume = next(x for x in self.stdin() if x.get("method") == "thread/resume")
        self.assertEqual(resume["params"]["threadId"], THREAD)
        self.assertEqual(resume["params"]["cwd"], self.work())
        self.assertEqual(resume["params"]["approvalPolicy"], "untrusted")
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        self.assertEqual(len(starts), 2)
        recs = self.events(chat_id)[0]
        self.assertEqual([x["mode"] for x in recs if x["kind"] == "process_started"], ["new", "resume"])
        self.assertEqual(len([x for x in recs if x["kind"] == "session_bound"]), 1)
        totals = [x["total_tokens"] for x in recs if x["kind"] == "usage"]
        self.assertEqual(totals, [18104, 18104, 37716])
        deltas = [x["delta_tokens"] for x in recs if x["kind"] == "usage"]
        self.assertEqual(deltas, [18104, 0, 19612])
        self.assert_nothing_of_the_account_kept(chat_id)

    def test_a_resume_without_a_recorded_total_is_counted_from_its_first_report(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        path = self.base / "chats" / chat_id / "events.jsonl"
        lines = [x for x in path.read_text().splitlines(keepends=True) if '"kind":"usage"' not in x]
        # keep the sequence whole: renumber
        out = []
        for i, line in enumerate(lines, 1):
            rec = json.loads(line)
            rec["seq"] = i
            out.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        path.write_text("".join(out))
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 2)
        self.assertEqual(end["tokens"], 19612)

    def test_one_process_per_role_card(self):
        self.configure(start=[0, 0])
        first, second = self.open_chat(), self.open_chat()
        self.assertTrue(self.send(first)["ok"])
        self.wait_turn(first, 1)
        r = self.send(second)
        self.assertEqual(r["error"]["code"], "restarting")
        self.wait_gone(first)
        self.assertTrue(self.send(second)["ok"])
        self.wait_turn(second, 1)

    def test_a_busy_role_card_cannot_have_a_second_chat(self):
        self.configure(start=[1])
        first, second = self.open_chat(), self.open_chat()
        self.assertTrue(self.send(first)["ok"])
        self.wait_card(first)
        self.assertEqual(self.send(second)["error"]["code"], "busy")
        self.assertEqual(self.send(first)["error"]["code"], "busy")

    def test_a_daemon_restart_closes_an_open_turn_at_its_cap(self):
        chat_id = self.open_chat()
        log = cs.ChatLog(self.base, chat_id)
        log.append("user_message", {"turn": 1, "text": "hi"}, now=time.time())
        log.append("turn_started", {"turn": 1, "cap_usd": "0.3"}, now=time.time())
        log.close()
        self.stop_daemon()
        self.start_daemon()
        end = next(r for r in self.events(chat_id)[0] if r["kind"] == "turn_ended")
        self.assertEqual((end["reason"], end["cost_usd"]), ("daemon_restart", "0.3"))

    def test_deleting_a_chat_keeps_its_folder_and_its_cost(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertTrue(self.rpc("chat_delete", chat_id=chat_id)["ok"])
        self.assertTrue(Path(self.work()).is_dir())
        self.assertTrue(list((self.base / "chat-spend").iterdir()))


class BeforeAnythingStartsTests(CodexCase):
    def refused(self, code, **cli):
        self.configure(start=[0])
        chat_id = self.open_chat()
        r = self.send(chat_id, cli=self.cli(**cli) if cli else None)
        self.assertEqual(r["error"]["code"], code, r)
        self.assertEqual([x for x in self.fake_log() if x["event"] == "start"], [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertEqual(os.listdir(self.base / "sessions") if (self.base / "sessions").exists() else [], [])
        return chat_id

    def test_a_version_that_is_not_verified(self):
        with mock.patch.object(cli_versions, "CODEX_CHAT_VERIFIED_VERSIONS", ()):
            self.refused("unverified")

    def test_a_version_without_constants(self):
        self.refused("unsupported_version", version="0.1.0")

    def test_a_chat_login_that_is_not_there(self):
        self.configure(start=[0], login_status=1)
        chat_id = self.open_chat()
        self.assertEqual(self.send(chat_id)["error"]["code"], "not_logged_in")
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        shutil.rmtree(self.chat_home)
        self.assertEqual(self.send(chat_id)["error"]["code"], "not_logged_in")

    def test_a_chat_folder_with_a_config_toml(self):
        (self.chat_home / "config.toml").write_text("approval_policy = 'never'\n")
        self.refused("codex_home")

    def test_a_chat_folder_that_is_open_to_others(self):
        os.chmod(self.chat_home, 0o755)
        self.refused("codex_home")

    def test_a_dot_codex_in_the_work_folder(self):
        os.mkdir(os.path.join(self.work(), ".codex"))
        self.refused("invalid_workdir")

    def test_a_binary_that_changed_since_it_was_checked(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        identity = a.binary_identity(str(self.binary))
        r = self.send(chat_id, cli=self.cli(identity=[identity[0] + 1] + identity[1:]))
        self.assertEqual(r["error"]["code"], "drift")

    def test_the_administrator_policy(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        bad = admin_policy.PolicyCheck(False, found=["/etc/codex"], problems=["found"])
        with mock.patch("vbear.runtime.daemon_chat.admin_policy.check_codex", return_value=bad):
            self.assertEqual(self.send(chat_id)["error"]["code"], "admin_policy")
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_the_input_is_checked(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        for kw in (dict(text="  "), dict(model_id="bad model"), dict(instructions="x" * 2001),
                   dict(cli={"binary": str(self.binary)})):
            r = self.send(chat_id, **kw) if "text" not in kw else self.send(chat_id, kw["text"])
            self.assertEqual(r["error"]["code"], "bad_request", kw)
        self.assertEqual(self.fake_log(), [])


class WhatIsNotKeptTests(CodexCase):
    def test_a_whole_chat_keeps_nothing_of_the_account_the_folder_or_the_servers(self):
        self.configure(start=[0, 1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertTrue(self.send(chat_id, "ls")["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        self.wait_turn(chat_id, 2)
        self.assert_nothing_of_the_account_kept(chat_id)
        live = json.dumps(self.events(chat_id)[1])
        for secret in ccf.SENSITIVE:
            self.assertNotIn(secret, live)
        listing = json.dumps(self.rpc("list"))
        for secret in ccf.SENSITIVE + (str(self.chat_home),):
            self.assertNotIn(secret, listing)
        info = next(s for s in self.rpc("list")["result"]["sessions"] if s.get("engine") == "codex-chat")
        self.assertEqual(info["activity_evidence"], {"codex_chat": {"state": "idle"}})

    def test_the_manifest_of_a_launch_in_progress_is_a_codex_chat_one(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        [name] = os.listdir(self.base / "sessions")
        m = a._read_manifest(a.launch_dir(self.base, name), os.getuid())
        self.assertEqual((m["engine"], m["state"], m["chat_id"]), ("codex-chat", "running", chat_id))
        self.assertIsNone(a.codex_chat_manifest_problem(m))
        self.assertIsInstance(self.dm._chats[chat_id], ccs.CodexChatProcess)


if __name__ == "__main__":
    unittest.main()
