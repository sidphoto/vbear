"""Chats with a role card through the runtime daemon (P36-1), end to end with a fake Claude Code
(tests/fake_chat_cli.py) that replays the turns recorded with 2.1.318 (tests/chat_fixtures.py). Synthetic HOME and
VBEAR_HOME under /tmp; the daemon listens on its own socket there, never the user's; nothing reaches a model or the
network."""

from __future__ import annotations

import copy
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests import chat_fixtures as cf
from vbear import admin_policy
from vbear.runtime import agent_sessions as a
from vbear.runtime import chat_session as csess
from vbear.runtime import chat_store as cs
from vbear.runtime import cli_versions
from vbear.runtime import daemon as d

REPO = str(Path(__file__).resolve().parent.parent)
TIMEOUT = 20.0
WAIT = 20.0
MODEL = "claude-haiku-5-5"
LAUNCHER = "#!%(py)s -I\nimport runpy, sys\nsys.path.insert(0, %(repo)r)\nrunpy.run_module('tests.fake_chat_cli', run_name='__main__')\n"
SECRETS_OF_INIT = ("fictional.person", "fictional-command", "fictional-model", "Fictional Org", "/USER-DIR-")


def clean(name, index):
    return cf.script(name, index, init=cf.clean_init())


class ChatCase(unittest.TestCase):
    policy_ok = True

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbc-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        v = mock.patch.object(cli_versions, "CHAT_VERIFIED_VERSIONS", (cf.VERSION,))
        v.start()
        self.addCleanup(v.stop)
        if self.policy_ok:
            p = mock.patch("vbear.runtime.daemon_chat.admin_policy.check_claude",
                           side_effect=lambda version, home=None: admin_policy.PolicyCheck(True))
            p.start()
            self.addCleanup(p.stop)
        self.binary = self.tmp / "claude"
        self.binary.write_text(LAUNCHER % {"py": sys.executable, "repo": REPO})
        self.binary.chmod(0o700)
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

    def configure(self, turns, **init):
        (self.home / "fake-chat.json").write_text(json.dumps({"turns": turns, "init": init}))

    def cli(self):
        return {"binary": str(self.binary), "version": cf.VERSION, "identity": a.binary_identity(str(self.binary))}

    def open_chat(self, profile="emp-1"):
        r = self.rpc("chat_open", profile_id=profile)
        self.assertTrue(r["ok"], r)
        return r["result"]["chat_id"]

    def send(self, chat_id, text="hello"):
        return self.rpc("chat_send", chat_id=chat_id, text=text, cli=self.cli(), model_id=MODEL)

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

    def wait_card(self, chat_id):
        def card():
            _, live = self.events(chat_id)
            return live and live["cards"] and live["cards"][0]
        return self.wait(card, "a card")

    def wait_turn(self, chat_id, n):
        def ended():
            recs, _ = self.events(chat_id)
            return next((r for r in recs if r["kind"] == "turn_ended" and r["turn"] == n), None)
        return self.wait(ended, f"the end of turn {n}")

    def wait_gone(self, chat_id):
        self.wait(lambda: chat_id not in self.dm._chats and self.events(chat_id)[1] is None, "the process to end")

    def fake_log(self):
        path = self.home / "fake-chat-log.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def stdin(self):
        return [r["line"] for r in self.fake_log() if r["event"] == "stdin"]

    def answers(self):
        return [x for x in self.stdin() if x.get("type") == "control_response"]

    def kinds(self, chat_id):
        return [r["kind"] for r in self.events(chat_id)[0]]

    def raw(self, chat_id):
        return (self.base / "chats" / chat_id / "events.jsonl").read_text()

    def assert_nothing_of_init_kept(self, chat_id):
        reply = json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        for text in (self.raw(chat_id), reply, "\n".join(self.logs)):
            for secret in SECRETS_OF_INIT:
                self.assertNotIn(secret, text)


class CardTests(ChatCase):
    def test_allow_runs_the_recorded_bash_turn(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        r = self.send(chat_id, "run ls")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["cap_usd"], r["result"]["process"]), (1, "0.5", "new"))
        card = self.wait_card(chat_id)
        recorded = cf.events("ask", 0)
        asked = next(e for e in recorded if e.get("type") == "control_request")["request"]
        self.assertEqual((card["tool"], card["input"], card["editable"]), ("Bash", asked["input"], "command"))
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertTrue(r["ok"], r)
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["cost_usd"], end["reported"], end["reason"]), ("0.00100946", True, "result"))
        self.assertEqual(end["total_usd"], 0.00100946)
        kinds = self.kinds(chat_id)
        for k in ("user_message", "turn_started", "process_started", "session_ready", "card", "card_decision",
                  "tool_call", "tool_result", "reply", "turn_ended"):
            self.assertIn(k, kinds)
        lines = self.stdin()
        self.assertEqual(lines[0]["request"], {"subtype": "initialize"})
        self.assertEqual((lines[1]["type"], lines[1]["message"]["content"][0]["text"]), ("user", "run ls"))
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"], {"behavior": "allow", "updatedInput": asked["input"]})
        start = next(x for x in self.fake_log() if x["event"] == "start")
        chat = cs.load(self.base, chat_id)
        self.assertEqual(start["argv"][start["argv"].index("--session-id") + 1], chat["claude_session_id"])
        self.assertIn("--permission-prompt-tool", start["argv"])
        self.assertTrue(start["env"]["CLAUDE_CODE_TMPDIR"].startswith("/private/tmp/sc-"))
        self.assertEqual(start["cwd"], cs.ensure_work_dir(self.base, "emp-1"))
        self.assert_nothing_of_init_kept(chat_id)

    def test_deny(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="deny")
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"], {"behavior": "deny", "message": csess.DENIED})
        decision = next(x for x in self.events(chat_id)[0] if x["kind"] == "card_decision")
        self.assertEqual(decision["decision"], "deny")

    def test_modify_then_allow_sends_what_the_person_wrote(self):
        self.configure([clean("ask", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        recorded = next(x["line"] for x in cf.turns("ask")[1]["out"] if x["dir"] == "in")
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="modify",
                     value="echo changed-by-user")
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"], recorded["response"]["response"])
        decision = next(x for x in self.events(chat_id)[0] if x["kind"] == "card_decision")
        self.assertEqual((decision["decision"], decision["value"]), ("modify", "echo changed-by-user"))

    def test_a_second_answer_or_a_wrong_token_is_refused(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token="x" * 32, decision="allow")
        self.assertEqual(r["error"]["code"], "bad_token")
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertTrue(r["ok"], r)
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="deny")
        self.assertEqual(r["error"]["code"], "gone")
        self.wait_turn(chat_id, 1)
        self.assertEqual(len(self.answers()), 1)

    def test_an_expired_card_is_refused(self):
        self.dm.chat_card_ttl = 0.5
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.wait(lambda: self.answers(), "the expiry's refusal")
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"], {"behavior": "deny", "message": csess.EXPIRED})
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertEqual(r["error"]["code"], "gone")
        self.wait_turn(chat_id, 1)
        decision = next(x for x in self.events(chat_id)[0] if x["kind"] == "card_decision")
        self.assertEqual(decision["decision"], "expired")

    def test_a_write_outside_the_work_folder_is_refused_without_a_card(self):
        steps = clean("ask", 2)
        ask = next(s for s in steps if "ask" in s)["ask"]
        ask["request"]["input"]["file_path"] = str(self.tmp / "outside" / "note.txt")
        self.configure([steps])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"]["behavior"], "deny")
        self.assertIn("以外", answer["response"]["response"]["message"])
        recs = self.events(chat_id)[0]
        self.assertNotIn("card", [r["kind"] for r in recs])
        denied = next(r for r in recs if r["kind"] == "denied")
        self.assertEqual((denied["tool"], denied["by"]), ("Write", "vbear"))


    def _swap_a_folder_for_a_link_while_the_card_waits(self, index, tool, decision, value=None):
        """The card is asked for /WORK/sub/note.txt while ``sub`` is a folder of the work folder; before the person
        answers, ``sub`` becomes a link to a folder outside it. VBear judges the call again on the answer."""
        steps = clean("ask", index)
        ask = next(s["ask"] for s in steps if "ask" in s and s["ask"]["request"]["tool_name"] == tool)
        ask["request"]["input"]["file_path"] = "/WORK/sub/note.txt"
        self.configure([steps])
        work = Path(cs.ensure_work_dir(self.base, "emp-1"))
        (work / "sub").mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["input"]["file_path"]), (tool, str(work / "sub" / "note.txt")))
        (work / "sub").rmdir()
        (work / "sub").symlink_to(outside, target_is_directory=True)
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision=decision,
                     value=value)
        self.assertEqual(r["error"]["code"], "refused", r)
        self.assertIn("以外", r["error"]["message"])
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertEqual(r["error"]["code"], "gone")
        self.wait_turn(chat_id, 1)
        answers = [x["response"]["response"] for x in self.answers()]
        self.assertEqual(answers[-1]["behavior"], "deny")
        self.assertIn("以外", answers[-1]["message"])
        self.assertFalse([x for x in answers if x["behavior"] == "allow" and "sub" in x["updatedInput"]["file_path"]])
        recs = self.events(chat_id)[0]
        closed = next(x for x in recs if x["kind"] == "card_decision")
        self.assertEqual((closed["card_id"], closed["decision"], closed["value"]), (card["card_id"], "refused", value))
        denied = next(x for x in recs if x["kind"] == "denied")
        self.assertEqual((denied["tool"], denied["by"]), (tool, "vbear"))
        self.assertIn("以外", denied["reason"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_write_whose_folder_became_a_link_outside_is_refused_on_allow(self):
        self._swap_a_folder_for_a_link_while_the_card_waits(2, "Write", "allow")

    def test_an_edit_whose_folder_became_a_link_outside_is_refused_on_modify(self):
        self._swap_a_folder_for_a_link_while_the_card_waits(3, "Edit", "modify", "hello-changed")

    def test_many_cards_of_wide_characters_still_fit_one_events_reply(self):
        steps = clean("ask", 2)
        ask = next(s["ask"] for s in steps if "ask" in s)
        delta = copy.deepcopy(next(e for e in cf.events("ask", 0) if e.get("type") == "stream_event"
                                   and e["event"].get("delta", {}).get("type") == "text_delta"))
        long_reply = "說" * 500 + "\U00020000" * 4000                 # 4-byte characters (CJK Extension B)
        delta["event"]["delta"]["text"] = long_reply
        content = "測" * 1700 + "\U00020000" * 1150                    # about 9.7 KB of UTF-8: under a card's limit
        asks = []
        for i in range(6):
            a = copy.deepcopy(ask)
            a["request_id"] = f"req-many-{i}"
            a["request"]["tool_use_id"] = f"toolu_many_{i}"
            a["request"]["input"] = {"file_path": f"/WORK/n{i}.txt", "content": f"{content}{i}"}
            asks.append(a)
        self.configure([[steps[0], {"emit": [delta] + asks}]])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])

        def settled():
            _, live = self.events(chat_id)
            return live and len(live["cards"]) + len(self.answers()) == 6 and live
        live = self.wait(settled, "every request to be shown or refused")
        reply = self.rpc("chat_events", chat_id=chat_id, after=0)
        self.assertTrue(reply["ok"], reply)
        self.assertLess(len(json.dumps(reply, ensure_ascii=False).encode("utf-8")), d.MAX_LINE)
        self.assertLessEqual(len(json.dumps(live, ensure_ascii=False).encode("utf-8")), csess.LIVE_MAX)
        work = cs.ensure_work_dir(self.base, "emp-1")
        shown = {c["input"]["file_path"]: c["input"] for c in live["cards"]}
        self.assertEqual(len(shown), 3)
        for path, inp in shown.items():                                  # whole, as asked: never cut
            i = int(path[-5])
            self.assertEqual(inp, {"file_path": f"{work}/n{i}.txt", "content": f"{content}{i}"})
        refused = [x["response"]["response"] for x in self.answers()]
        self.assertEqual(len(refused), 3)
        for x in refused:
            self.assertEqual(x["behavior"], "deny")
            self.assertIn("太多", x["message"])
        recs = self.events(chat_id)[0]
        self.assertEqual(len([x for x in recs if x["kind"] == "denied" and x["by"] == "vbear"]), 3)
        self.assertTrue(live["partial_truncated"])
        self.assertTrue(live["partial"] and long_reply.endswith(live["partial"]))
        card = live["cards"][0]
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertTrue(r["ok"], r)


class ProtocolTests(ChatCase):
    def test_an_unknown_event_is_noted_by_its_field_names_only(self):
        steps = [{"emit": [{"type": "brand_new_kind", "secret_field": "value-not-to-keep"}]}] + clean("ask", 4)
        self.configure([steps])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        anomaly = next(r for r in self.events(chat_id)[0] if r["kind"] == "anomaly")
        self.assertEqual((anomaly["event_type"], anomaly["fields"]), ("brand_new_kind", ["secret_field", "type"]))
        self.assertNotIn("value-not-to-keep", self.raw(chat_id))
        self.assertIn("reply", self.kinds(chat_id))

    def test_an_unknown_control_request_is_answered_with_a_refusal(self):
        ask = {"type": "control_request", "request_id": "req-hook-1",
               "request": {"subtype": "hook_callback", "callback_id": "made-up"}}
        self.configure([[{"ask": ask}] + clean("ask", 4)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        [answer] = self.answers()
        self.assertEqual(answer["response"], {"subtype": "error", "request_id": "req-hook-1",
                                              "error": csess.UNKNOWN_CONTROL})
        anomaly = next(r for r in self.events(chat_id)[0] if r["kind"] == "anomaly")
        self.assertEqual(anomaly["event_type"], "control_request/hook_callback")

    def test_extra_folders_in_init_stop_the_chat(self):
        self.configure([cf.script("ask", 4)])                 # as recorded: the account's own extra folders
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["reported"]), ("violation", "0.5", False))
        error = next(r for r in self.events(chat_id)[0] if r["kind"] == "error")
        self.assertIn("額外資料夾（2 個", error["message"])
        self.wait_gone(chat_id)
        self.assert_nothing_of_init_kept(chat_id)

    def test_a_tool_that_ran_without_vbears_yes_stops_the_chat(self):
        self.configure([clean("text", 1)])                    # recorded without the stdio prompt tool
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "violation")
        error = next(r for r in self.events(chat_id)[0] if r["kind"] == "error")
        self.assertIn("Bash", error["message"])
        self.wait_gone(chat_id)

    def test_an_initialize_answer_of_another_version_stops_before_the_message(self):
        self.configure([clean("ask", 4)], version="2.1.999")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("not_sent", "0"))
        self.wait_gone(chat_id)
        self.assertFalse([x for x in self.stdin() if x.get("type") == "user"])


class LifecycleTests(ChatCase):
    def test_a_turn_over_its_time_is_stopped_at_its_cap(self):
        self.dm.chat_turn_timeout = 1.0
        init = next(e for e in cf.events("ask", 4) if e.get("subtype") == "init")
        self.configure([[{"emit": [dict(init, additional_directories=[])]}, {"sleep": 600}]])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["reported"]), ("error", "0.5", False))
        self.wait_gone(chat_id)
        self.assertIn("process_ended", self.kinds(chat_id))
        self.assertIn("sigterm", [x["event"] for x in self.fake_log()])

    def test_stop_ends_the_turn_at_its_cap(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("stopped", "0.5"))
        self.wait_gone(chat_id)

    def test_after_an_idle_close_the_next_message_resumes_the_session(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("ask", 0), clean("ask", 4)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertIn("eof", [x["event"] for x in self.fake_log()])          # closed by its stdin, not a signal
        r = self.send(chat_id, "what file did you create?")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "resume"))
        end = self.wait_turn(chat_id, 2)
        self.assertEqual((end["cost_usd"], end["reported"]),
                         (str(Decimal("0.0026256499999999998") - Decimal("0.00100946")), True))
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        chat = cs.load(self.base, chat_id)
        self.assertEqual(starts[1]["argv"][-2:], ["--resume", chat["claude_session_id"]])
        second = [x["line"] for x in self.fake_log()[self.fake_log().index(starts[1]):] if x["event"] == "stdin"]
        self.assertEqual(second[0]["request"], {"subtype": "initialize"})

    def test_the_next_message_reuses_the_process_within_what_it_may_still_spend(self):
        self.configure([clean("ask", 0), clean("ask", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.wait_turn(chat_id, 1)
        r = self.send(chat_id, "echo something")
        self.assertTrue(r["ok"], r)
        # the process may still spend 0.50 - 0.00100946 under its --max-budget-usd: that is this turn's cap
        self.assertEqual((r["result"]["turn"], r["result"]["process"], r["result"]["cap_usd"]),
                         (2, "reused", "0.49899054"))
        card = self.wait_card(chat_id)
        self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="modify",
                 value="echo changed-by-user")
        end = self.wait_turn(chat_id, 2)
        self.assertEqual(end["cost_usd"], str(Decimal("0.00145344") - Decimal("0.00100946")))
        self.assertEqual(len([x for x in self.fake_log() if x["event"] == "start"]), 1)

    def test_a_process_that_could_spend_more_than_the_turn_may_is_not_reused(self):
        self.configure([clean("ask", 4), clean("ask", 4)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        (self.base / "config.json").write_text(json.dumps({"chat_limits": {"per_turn_usd": 0.1}}))
        r = self.send(chat_id)
        self.assertEqual(r["error"]["code"], "restarting")
        self.wait_gone(chat_id)
        r = self.send(chat_id)
        self.assertEqual((r["result"]["process"], r["result"]["cap_usd"]), ("resume", "0.1"))
        self.wait_turn(chat_id, 2)

    def test_one_process_per_role_card(self):
        self.configure([clean("ask", 4), clean("ask", 4)])
        first, second = self.open_chat(), self.open_chat()
        self.assertTrue(self.send(first)["ok"])
        self.wait_turn(first, 1)
        r = self.send(second)
        self.assertEqual(r["error"]["code"], "restarting")
        self.wait_gone(first)
        self.assertTrue(self.send(second)["ok"])
        self.wait_turn(second, 1)

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


class MoneyAndDeleteTests(ChatCase):
    def spend(self, chat_id, cost):
        log = cs.ChatLog(self.base, chat_id)
        try:
            log.append("user_message", {"turn": 1, "text": "hi"}, now=time.time())
            log.append("turn_started", {"turn": 1, "cap_usd": "0.5"}, now=time.time())
            log.append("turn_ended", {"turn": 1, "cost_usd": cost, "reported": True, "total_usd": float(cost),
                                      "reason": "result", "subtype": "success", "is_error": False}, now=time.time())
        finally:
            log.close()

    def test_no_new_message_on_a_red_lamp(self):
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {
            "per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.01}}))
        self.configure([clean("ask", 4)])
        chat_id = self.open_chat()
        self.spend(chat_id, "0.02")
        r = self.send(chat_id)
        self.assertEqual(r["error"]["code"], "red")
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id).count("user_message"), 1)

    def _the_day_stays_closed_when(self, damage, *, deleted=False):
        """Another chat spent past the day's limit (red); once its record no longer reads whole, the day is unknown,
        never less: still nothing is sent."""
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {
            "per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.01}}))
        self.configure([clean("ask", 4)])
        other = self.open_chat("emp-2")
        self.spend(other, "0.02")
        if deleted:
            self.assertTrue(self.rpc("chat_delete", chat_id=other)["ok"])
        chat_id = self.open_chat()
        self.assertEqual(self.send(chat_id)["error"]["code"], "red")
        damage(other)
        r = self.send(chat_id)
        self.assertEqual(r["error"]["code"], "spend_unknown", r)
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id).count("user_message"), 0)
        return other

    def test_a_chat_damaged_in_the_middle_does_not_give_the_day_back(self):
        def damage(other):
            path = self.base / "chats" / other / "events.jsonl"
            lines = path.read_text().splitlines(keepends=True)
            lines[1] = lines[1][: len(lines[1]) // 2] + "\n"               # the spending lines after it stay
            path.write_text("".join(lines))
        other = self._the_day_stays_closed_when(damage)
        self.assertEqual(self.rpc("chat_delete", chat_id=other)["error"]["code"], "damaged")
        self.assertTrue((self.base / "chats" / other / "events.jsonl").exists())

    def test_a_chat_missing_its_events_does_not_give_the_day_back(self):
        self._the_day_stays_closed_when(lambda other: (self.base / "chats" / other / "events.jsonl").unlink())

    def test_a_deleted_chats_damaged_spend_record_does_not_give_the_day_back(self):
        def damage(other):
            path = self.base / "chat-spend" / f"{other}.json"
            path.write_text(path.read_text()[:-20])
        self._the_day_stays_closed_when(damage, deleted=True)

    def test_a_turn_may_cost_at_most_what_is_left_of_the_day(self):
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {
            "per_call_usd": 0.2, "meeting_usd": 1, "daily_usd": 1}}))
        other = self.open_chat("emp-2")
        self.spend(other, "0.8")
        self.configure([clean("ask", 4)])
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.assertEqual(r["result"]["cap_usd"], "0.2")
        start = self.wait(lambda: next((x for x in self.fake_log() if x["event"] == "start"), None), "the start")
        self.assertEqual(start["argv"][start["argv"].index("--max-budget-usd") + 1], "0.20")
        self.wait_turn(chat_id, 1)

    def test_deleting_a_chat(self):
        self.configure([clean("ask", 4)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(self.rpc("chat_delete", chat_id=chat_id)["error"]["code"], "busy")
        self.assertTrue(self.rpc("chat_close", chat_id=chat_id)["result"]["closed"])
        self.wait_gone(chat_id)
        r = self.rpc("chat_delete", chat_id=chat_id)
        self.assertTrue(r["ok"], r)
        self.assertFalse((self.base / "chats" / chat_id).exists())
        self.assertEqual(self.rpc("chat_events", chat_id=chat_id, after=0)["error"]["code"], "not_found")
        self.assertEqual(cs.day_spent(self.base, time.time()), Decimal(end["cost_usd"]))
        self.assertTrue(os.path.isdir(cs.ensure_work_dir(self.base, "emp-1")))      # the card's folder stays


class GateTests(ChatCase):
    def test_an_unverified_version_starts_nothing(self):
        with mock.patch.object(cli_versions, "CHAT_VERIFIED_VERSIONS", ()):
            chat_id = self.open_chat()
            r = self.send(chat_id)
        self.assertEqual(r["error"]["code"], "unverified")
        self.assertEqual(self.fake_log(), [])
        self.assertFalse(os.listdir(self.base / "sessions") if (self.base / "sessions").exists() else [])

    def test_a_changed_cli_is_refused(self):
        chat_id = self.open_chat()
        cli = dict(self.cli(), identity=[0, 0, 0, 0, 0, 0])
        r = self.rpc("chat_send", chat_id=chat_id, text="hi", cli=cli, model_id=MODEL)
        self.assertEqual(r["error"]["code"], "drift")


class AdminPolicyTests(ChatCase):
    policy_ok = False

    def test_without_a_policy_list_for_the_version_nothing_starts(self):
        """2.1.318 has no administrator-policy source list yet (admin_policy.CLAUDE_SOURCES): refused, fail closed."""
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.assertEqual(r["error"]["code"], "admin_policy")
        self.assertEqual(self.fake_log(), [])


if __name__ == "__main__":
    unittest.main()
