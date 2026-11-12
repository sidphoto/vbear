"""Chats with a role card whose AI tool is AGY, through the runtime daemon (P46-3, ADR 0012), end to end with a fake ``agy``
(tests/fake_agy_acp.py) that plays the synthetic scripts of tests/fixtures/agy-chat/ (they are not recordings: see
tests/agy_chat_fixtures.py). Synthetic HOME and VBEAR_HOME under /tmp; the daemon listens on its own socket there, never the user's;
nothing reaches a model or the network, and the real agy is never run."""

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

from tests import agy_chat_fixtures as fx
from tests import leftover
from vbear import admin_policy
from vbear.runtime import agent_sessions as a
from vbear.runtime import agy_chat_env as env
from vbear.runtime import agy_chat_protocol as acp
from vbear.runtime import agy_chat_session as acs
from vbear.runtime import chat_store as cs
from vbear.runtime import cli_versions
from vbear.runtime import daemon as d

TIMEOUT = 20.0
WAIT = 20.0
VERSION = "1.5.3"
SESSION = fx.SESSION
USAGE_COST = "0.09"          # 86000 tokens at US$1 a million, up to the cent


class AgyCase(unittest.TestCase):
    policy_ok = True

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbg-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(leftover.assert_clean, self.tmp)            # runs after the daemon is stopped and before the folder goes
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        patched = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patched.start()
        self.addCleanup(patched.stop)
        verified = mock.patch.object(cli_versions, "AGY_CHAT_VERIFIED_VERSIONS", (VERSION,))
        verified.start()
        self.addCleanup(verified.stop)
        if self.policy_ok:
            policy = mock.patch("vbear.runtime.daemon_chat.admin_policy.check_agy",
                                side_effect=lambda version, root="/": admin_policy.PolicyCheck(True))
            policy.start()
            self.addCleanup(policy.stop)
        self.conf_path = self.home / "fake-agy.json"
        self.binary = Path(fx.write_launcher(self.tmp / "agy", self.conf_path))
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

    def configure(self, *scripts, **extra):
        conf = {"version": VERSION, "scripts": [s if isinstance(s, dict) else {"fixture": s} for s in scripts] or [{"fixture": "text"}]}
        conf.update(extra)
        self.conf_path.write_text(json.dumps(conf))

    def cli(self, **over):
        cli = {"binary": str(self.binary), "version": VERSION, "identity": a.binary_identity(str(self.binary))}
        cli.update(over)
        return cli

    def open_chat(self, profile="emp-1"):
        r = self.rpc("chat_open", profile_id=profile, engine="agy-chat")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["engine"], "agy-chat")
        return r["result"]["chat_id"]

    def send(self, chat_id, text="hello", **kw):
        return self.rpc("chat_send", chat_id=chat_id, text=text, cli=kw.pop("cli", None) or self.cli(), model_id=kw.pop("model_id", None), **kw)

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
        return self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision=decision, value=value)

    def fake_log(self):
        path = Path(str(self.conf_path) + ".log.jsonl")
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def stdin(self):
        return [r["line"] for r in self.fake_log() if r["event"] == "stdin"]

    def choices(self):
        """What VBear answered to the agent's requests: (decision, kind of the option chosen)."""
        return [(x["decision"], x["kind"]) for x in self.fake_log() if x["event"] == "choice"]

    def methods(self):
        return [x["method"] for x in self.stdin() if "method" in x]

    def unexpected(self):
        return [x for x in self.fake_log() if x["event"] == "unexpected"]

    def kinds(self, chat_id):
        return [r["kind"] for r in self.events(chat_id)[0]]

    def records(self, chat_id, kind):
        return [r for r in self.events(chat_id)[0] if r["kind"] == kind]

    def raw(self, chat_id):
        return (self.base / "chats" / chat_id / "events.jsonl").read_text()

    def work(self, profile="emp-1"):
        return cs.ensure_work_dir(self.base, profile)

    def assert_nothing_dangerous_was_sent(self):
        text = json.dumps(self.stdin())
        for word in ("allow_always", "reject_always", "bypass", "BypassSandbox"):
            self.assertNotIn(word, text)
        for decision, kind in self.choices():
            self.assertIn((decision, kind), (("allow", "allow_once"), ("deny", "reject_once"), ("cancelled", None)))

    def assert_nothing_of_the_account_kept(self, chat_id):
        reply = json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        for text in (self.raw(chat_id), reply, "\n".join(self.logs)):
            for secret in fx.SENSITIVE + (str(env.chat_home_path(self.base)),):
                self.assertNotIn(secret, text)


class TextTests(AgyCase):
    def test_a_plain_text_turn_and_how_the_process_was_started(self):
        self.configure("text")
        chat_id = self.open_chat()
        r = self.send(chat_id, "Say hello", instructions="先說結論。")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (1, "new"))
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["reported"], end["total_usd"]), ("result", USAGE_COST, False, None))
        self.assertEqual((end["estimate"], end["tokens"], end["subtype"], end["is_error"]), (True, 86000, "end_turn", False))
        recs = self.events(chat_id)[0]
        kinds = [x["kind"] for x in recs]
        for k in ("user_message", "turn_started", "process_started", "session_ready", "session_bound", "usage", "reply", "turn_ended"):
            self.assertIn(k, kinds)
        self.assertEqual(next(x for x in recs if x["kind"] == "reply")["text"], "Hello, this is a made-up reply.")
        self.assertEqual(next(x for x in recs if x["kind"] == "session_bound")["thread_id"], SESSION)
        self.assertEqual(next(x for x in recs if x["kind"] == "usage")["delta_tokens"], 86000)
        ready = next(x for x in recs if x["kind"] == "session_ready")
        self.assertEqual((ready["cli_version"], ready["permission_mode"], ready["model"]), (VERSION, "request-review", acp.VERSIONS[VERSION].model_id))
        # how it was started
        start = self.starts()[0]
        consts = acp.VERSIONS[VERSION]
        self.assertEqual(start["argv"], acp.argv_for(consts, str(env.chat_home_path(self.base))))
        self.assertEqual(sorted(start["env_keys"]), sorted(consts.env_keys))
        self.assertEqual(start["cwd"], self.work())
        self.assertEqual(start["settings_sha256"], __import__("hashlib").sha256(env.SETTINGS_BYTES).hexdigest())     # written before the process
        self.assertEqual(self.methods()[:4], ["initialize", "session/new", "session/set_model", "session/prompt"])
        new = next(x for x in self.stdin() if x.get("method") == "session/new")
        self.assertEqual(new["params"]["cwd"], self.work())
        self.assertEqual(cs.load(self.base, chat_id)["engine"], "agy-chat")
        self.assertEqual(set(cs.load(self.base, chat_id)), {"v", "id", "profile_id", "created_at", "engine"})
        self.assert_nothing_of_the_account_kept(chat_id)
        self.assert_nothing_dangerous_was_sent()
        self.assertEqual(self.unexpected(), [])

    def test_the_process_is_left_idle_and_the_next_message_goes_to_it(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send(chat_id, "again")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "reused"))
        end = self.wait_turn(chat_id, 2)
        self.assertEqual((end["tokens"], end["cost_usd"]), (86000, USAGE_COST))
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.methods().count("session/prompt"), 2)
        self.assertEqual(self.unexpected(), [])


def permission(**vars):
    return {"fixture": "permission", "vars": vars}


def file_call(rel="note.txt", content="hello\n", kind="edit", old=None):
    """Variables of the ``permission`` script for a file tool that names ``rel`` in the work folder."""
    where = "${WORK}/" + rel
    return {"KIND": kind, "TITLE": "Change a file", "RAW_INPUT": {"Path": where, "Content": content},
            "LOCATIONS": [{"path": where}], "CONTENT": [{"type": "diff", "path": where, "oldText": old, "newText": content}]}


class CommandCardTests(AgyCase):
    def test_a_command_is_a_card_and_allow_runs_it_once(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id, "list the folder")["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["input"], card["editable"]), ("command", {"command": "ls -a", "cwd": "."}, "command"))
        self.assertIn("沙盒", card["reason"])
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("result", USAGE_COST))
        recs = self.events(chat_id)[0]
        self.assertEqual([x["decision"] for x in recs if x["kind"] == "card_decision"], ["allow"])
        call = next(x for x in recs if x["kind"] == "tool_call")
        self.assertEqual((call["tool"], call["summary"], call["tool_use_id"]), ("command", "ls -a", "call-1"))
        result = next(x for x in recs if x["kind"] == "tool_result")
        self.assertEqual((result["tool"], result["is_error"], result["text"], result["source"]), ("command", False, "made-up output", "agy"))
        self.assertEqual(next(x for x in recs if x["kind"] == "reply")["text"], "Done.")
        self.assertEqual(self.choices(), [("allow", "allow_once")])
        self.assert_nothing_dangerous_was_sent()
        self.assert_nothing_of_the_account_kept(chat_id)
        self.assertEqual(self.unexpected(), [])

    def test_deny_refuses_it_once_and_nothing_ran(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)
        recs = self.events(chat_id)[0]
        self.assertEqual([x["decision"] for x in recs if x["kind"] == "card_decision"], ["deny"])
        self.assertEqual([x for x in recs if x["kind"] == "tool_result"], [])
        self.assertEqual(self.choices(), [("deny", "reject_once")])
        self.assertEqual(next(x for x in recs if x["kind"] == "reply")["text"], "Understood, I did not do it.")

    def test_a_card_is_answered_once_with_its_own_token(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token="nope", decision="allow")["error"]["code"], "bad_token")
        self.assertEqual(self.answer(chat_id, card, "maybe")["error"]["code"], "bad_request")
        self.assertEqual(self.answer(chat_id, card, "allow", value="x")["error"]["code"], "bad_request")
        self.assertEqual(self.answer(chat_id, card, "modify", "")["error"]["code"], "bad_request")
        self.assertEqual(self.choices(), [])
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        self.assertEqual(self.answer(chat_id, card, "allow")["error"]["code"], "gone")
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.choices(), [("allow", "allow_once")])

    def test_a_card_that_waits_too_long_is_refused(self):
        self.dm.chat_card_ttl = 0.5
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        self.wait_turn(chat_id, 1)
        self.assertEqual([x["decision"] for x in self.records(chat_id, "card_decision")], ["expired"])
        self.assertEqual(self.choices(), [("deny", "reject_once")])

    def test_a_changed_command_refuses_the_first_and_is_asked_again_as_the_next_message(self):
        self.configure("edit-input")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        first = self.wait_card(chat_id)
        self.assertEqual(first["input"]["command"], "echo one")
        self.assertTrue(self.answer(chat_id, first, "modify", "echo two")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["reason"], "result")
        second = self.wait(lambda: next((c for c in (self.events(chat_id)[1] or {}).get("cards", []) if c["card_id"] != first["card_id"]), None), "the second card")
        self.assertEqual(second["input"]["command"], "echo two")                 # the card is the changed command, asked again
        self.assertTrue(self.answer(chat_id, second, "allow")["ok"])
        self.wait_turn(chat_id, 2)
        recs = self.events(chat_id)[0]
        said = [x for x in recs if x["kind"] == "user_message"]
        self.assertEqual(len(said), 2)
        self.assertIn("echo two", said[1]["text"])
        self.assertEqual([x["turn"] for x in recs if x["kind"] == "turn_started"], [1, 2])
        self.assertEqual([(x["decision"], x["value"]) for x in recs if x["kind"] == "card_decision"], [("modify", "echo two"), ("allow", None)])
        sent = next(x for x in recs if x["kind"] == "card_edit_sent")
        self.assertEqual((sent["card_id"], sent["text"]), (first["card_id"], "echo two"))
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.choices(), [("deny", "reject_once"), ("allow", "allow_once")])
        self.assertEqual(self.unexpected(), [])

    def test_a_changed_text_that_cannot_be_sent_as_a_new_turn_says_so(self):
        # the day's limit is the turn's cap: the recorded turn reaches it, so the day is closed (red) when the next turn is asked for
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {"per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.09}}))
        self.configure("edit-input")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "modify", "echo two")["ok"])
        self.wait_turn(chat_id, 1)
        error = self.wait(lambda: next((x for x in self.records(chat_id, "error")), None), "the error")
        self.assertTrue(error["message"].startswith("改過的內容沒有送出："), error)
        self.assertEqual(len(self.records(chat_id, "user_message")), 1)
        self.assertEqual(self.methods().count("session/prompt"), 1)


class FileAndReadTests(AgyCase):
    def finish(self, chat_id):
        self.assertTrue(self.rpc("chat_close", chat_id=chat_id)["ok"])
        self.wait_gone(chat_id)

    def test_a_file_change_is_a_card_with_its_path_and_diff(self):
        self.configure(permission(**file_call()))
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("file_change", "content"))
        self.assertEqual(card["input"], {"changes": [{"path": "note.txt", "kind": "add", "diff": "+hello"}]})
        self.assertIn("要你允許", card["reason"])
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.choices(), [("allow", "allow_once")])
        call = next(x for x in self.records(chat_id, "tool_call"))
        self.assertEqual(call["tool"], "file_change")

    def test_a_file_change_the_person_changed_is_asked_again_with_the_new_content(self):
        self.configure(permission(**file_call()), permission(**file_call(content="changed\n")))
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "modify", "changed\n")["ok"])
        self.wait_turn(chat_id, 1)
        said = self.records(chat_id, "user_message")
        self.assertEqual(len(said), 2)
        self.assertIn("note.txt", said[1]["text"])
        self.assertIn("changed", said[1]["text"])

    def test_files_outside_and_the_names_that_are_settings_are_refused_with_no_card(self):
        cases = [("/etc/hosts", "資料夾以外"), ("${WORK}/.git/config", ".git"), ("${WORK}/sub/AGENTS.md", "AGENTS.md"),
                 ("${WORK}/.agents/skills/x.md", ".agents"), ("${WORK}/.Gemini/settings.json", ".gemini")]
        for index, (path, word) in enumerate(cases):
            with self.subTest(path=path):
                profile = f"emp-{index + 1}"
                self.configure(permission(**{**file_call(), "RAW_INPUT": {"Path": path, "Content": "x"},
                                              "LOCATIONS": [{"path": path}], "CONTENT": []}))
                self.conf_path.with_name(self.conf_path.name + ".state.json").unlink(missing_ok=True)
                chat_id = self.open_chat(profile)
                self.assertTrue(self.send(chat_id)["ok"])
                self.wait_turn(chat_id, 1)
                recs = self.events(chat_id)[0]
                self.assertEqual([x for x in recs if x["kind"] == "card"], [])
                denied = next(x for x in recs if x["kind"] == "denied")
                self.assertEqual((denied["tool"], denied["by"]), ("file_change", "vbear"))
                self.assertIn(word, denied["reason"])
                self.assertEqual(self.choices()[-1], ("deny", "reject_once"))
                self.assertEqual([x for x in recs if x["kind"] == "tool_result"], [])
                self.finish(chat_id)

    def test_a_read_inside_the_work_folder_is_allowed_without_a_card(self):
        self.configure(permission(KIND="read", TITLE="Read a file", RAW_INPUT={"Path": "${WORK}/a.txt"}, LOCATIONS=[{"path": "${WORK}/a.txt"}]))
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        recs = self.events(chat_id)[0]
        self.assertEqual([x for x in recs if x["kind"] == "card"], [])
        auto = next(x for x in recs if x["kind"] == "auto_allowed")
        self.assertEqual(auto["tool"], "read")
        self.assertEqual(self.choices(), [("allow", "allow_once")])

    def test_a_read_outside_is_a_card_that_says_where_the_content_goes(self):
        self.configure(permission(KIND="read", TITLE="Read a file", RAW_INPUT={"Path": "/etc/hosts"}, LOCATIONS=[{"path": "/etc/hosts"}]))
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["input"], card["editable"]), ("read", {"paths": ["/etc/hosts"]}, None))
        self.assertIn("Google", card["reason"])
        self.assertEqual(self.answer(chat_id, card, "modify", "x")["error"]["code"], "bad_request")
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.choices(), [("deny", "reject_once")])

    def test_the_network_is_refused_with_no_card(self):
        self.configure(permission(KIND="fetch", TITLE="Fetch", RAW_INPUT={"Url": "https://example.invalid/x"}, LOCATIONS=[]))
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        recs = self.events(chat_id)[0]
        self.assertEqual([x for x in recs if x["kind"] == "card"], [])
        denied = next(x for x in recs if x["kind"] == "denied")
        self.assertIn("連網", denied["reason"])
        self.assertEqual(self.choices(), [("deny", "reject_once")])

    def test_a_command_outside_the_sandbox_is_refused_with_no_card(self):
        self.configure("bypass")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        first = self.wait_card(chat_id)
        self.assertEqual(first["input"]["command"], "echo x > /made/up/out.txt")
        self.assertTrue(self.answer(chat_id, first, "allow")["ok"])
        self.wait_turn(chat_id, 1)
        recs = self.events(chat_id)[0]
        self.assertEqual(len([x for x in recs if x["kind"] == "card"]), 1)             # only the first
        denied = next(x for x in recs if x["kind"] == "denied")
        self.assertIn("沙盒", denied["reason"])
        self.assertEqual(self.choices(), [("allow", "allow_once"), ("deny", "reject_once")])
        self.assert_nothing_dangerous_was_sent()


class ViolationTests(AgyCase):
    def violation(self, script, **vars):
        self.configure({"fixture": script, "vars": vars})
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.assertTrue(r["ok"], r)
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"], end["tokens"]), ("violation", r["result"]["cap_usd"], False, None))
        self.wait_gone(chat_id)
        recs = self.events(chat_id)[0]
        self.assertTrue(any(x["kind"] == "error" for x in recs))
        self.assertEqual(recs[-1]["kind"], "process_ended")
        return chat_id, recs

    def test_something_that_ran_without_asking_stops_the_chat(self):
        _, recs = self.violation("no-ask")
        error = next(x for x in recs if x["kind"] == "error")
        self.assertIn("沒有經過 VBear 的允許", error["message"])

    def test_a_mode_that_was_switched_stops_the_chat(self):
        _, recs = self.violation("mode-switch")
        error = next(x for x in recs if x["kind"] == "error")
        self.assertIn("模式", error["message"])
        self.assertEqual(set(self.methods()) - {"initialize", "session/new", "session/set_model", "session/prompt", "session/cancel"}, set())

    def test_a_request_of_another_session_stops_the_chat(self):
        self.violation("permission", REQ_SESSION=fx.OTHER_SESSION)

    def test_the_settings_file_changed_during_the_turn_stops_the_chat(self):
        self.configure("permission")
        chat_id = self.open_chat()
        r = self.send(chat_id)
        card = self.wait_card(chat_id)
        path = env.chat_home_path(self.base) / "antigravity-cli" / "settings.json"
        self.assertEqual(path.read_bytes(), env.SETTINGS_BYTES)
        path.write_text(json.dumps(dict(env.SETTINGS, toolPermission="auto")))
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"]), ("violation", r["result"]["cap_usd"], False))
        self.wait_gone(chat_id)
        error = next(x for x in self.records(chat_id, "error"))
        self.assertIn("設定檔", error["message"])
        # the next process writes it again
        self.assertEqual(self.starts()[0]["settings_sha256"], __import__("hashlib").sha256(env.SETTINGS_BYTES).hexdigest())


class ProblemsAtStartTests(AgyCase):
    def test_not_signed_in_is_said_in_words_and_costs_nothing(self):
        self.configure("auth-error")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("not_sent", "0"))
        error = next(x for x in self.records(chat_id, "error"))
        self.assertEqual(error["message"], acs.NOT_LOGGED_IN)
        self.assertNotIn("CLI", error["message"])
        self.wait_gone(chat_id)
        self.assertNotIn("session/prompt", self.methods())

    def test_a_model_that_is_not_there_is_said_in_words_and_costs_nothing(self):
        self.configure({"fixture": "text", "vars": {"MODELS": {"currentModelId": "x", "availableModels": [{"modelId": "gemini-4-argon-medium", "name": "A"}]}}})
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("not_sent", "0"))
        error = next(x for x in self.records(chat_id, "error"))
        self.assertIn(acp.VERSIONS[VERSION].model_id, error["message"])
        self.assertNotIn("session/prompt", self.methods())

    def test_a_session_id_that_is_not_one_stops_the_chat(self):
        self.configure({"fixture": "text", "vars": {"SESSION_NEW": "not-a-uuid"}})
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual(end["cost_usd"], "0")
        self.assertNotIn("session/prompt", self.methods())


class LifecycleTests(AgyCase):
    def test_after_an_idle_close_the_next_message_resumes_the_session_and_sets_the_model_again(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure("text", "resume")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertIn("eof", [x["event"] for x in self.fake_log()])           # closed by its stdin, not a signal
        r = self.send(chat_id, "do you remember?")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "resume"))
        end = self.wait_turn(chat_id, 2)
        self.assertEqual((end["tokens"], end["cost_usd"], end["reason"]), (86000, USAGE_COST, "result"))
        methods = self.methods()
        self.assertEqual(methods.count("session/new"), 1)
        resume = next(x for x in self.stdin() if x.get("method") == "session/resume")
        self.assertEqual((resume["params"]["sessionId"], resume["params"]["cwd"]), (SESSION, self.work()))
        self.assertEqual(methods.count("session/set_model"), 2)                 # set again after the resume
        second = methods[methods.index("session/resume"):]
        self.assertEqual(second, ["session/resume", "session/set_model", "session/prompt"])
        recs = self.events(chat_id)[0]
        self.assertEqual([x["mode"] for x in recs if x["kind"] == "process_started"], ["new", "resume"])
        self.assertEqual(len([x for x in recs if x["kind"] == "session_bound"]), 1)
        self.assertEqual(len([x for x in recs if x["kind"] == "session_ready"]), 2)
        self.assertEqual([x["text"] for x in recs if x["kind"] == "reply"][-1], "I remember.")
        self.assertEqual(self.unexpected(), [])
        self.assert_nothing_of_the_account_kept(chat_id)

    def test_a_session_that_cannot_be_found_stops_and_says_so(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure("text", "resume-missing")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertTrue(self.send(chat_id)["ok"])
        end = self.wait_turn(chat_id, 2)
        self.assertEqual((end["reason"], end["cost_usd"]), ("not_sent", "0"))
        error = self.records(chat_id, "error")[-1]
        self.assertEqual(error["message"], acs.RESUME_FAILED)
        self.assertEqual(self.methods().count("session/prompt"), 1)

    def test_one_process_per_role_card(self):
        self.configure("text", "text")
        first, second = self.open_chat(), self.open_chat()
        self.assertTrue(self.send(first)["ok"])
        self.wait_turn(first, 1)
        self.assertEqual(self.send(second)["error"]["code"], "restarting")
        self.wait_gone(first)
        self.assertTrue(self.send(second)["ok"])
        self.wait_turn(second, 1)

    def test_a_busy_role_card_cannot_have_a_second_chat(self):
        self.configure("permission")
        first, second = self.open_chat(), self.open_chat()
        self.assertTrue(self.send(first)["ok"])
        self.wait_card(first)
        self.assertEqual(self.send(second)["error"]["code"], "busy")
        self.assertEqual(self.send(first)["error"]["code"], "busy")

    def test_the_three_places_are_shared_with_the_other_engines(self):
        self.configure("permission", "permission", "permission")
        chats = [self.open_chat(f"emp-{i}") for i in (1, 2, 3, 4)]
        for chat_id in chats[:3]:
            self.assertTrue(self.send(chat_id)["ok"])
            self.wait_card(chat_id)
        self.assertEqual(self.send(chats[3])["error"]["code"], "limit")
        self.assertEqual(len(self.starts()), 3)

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


class StopAndMoneyTests(AgyCase):
    def test_stop_cancels_the_turn_and_the_usage_it_reports_is_what_it_costs(self):
        self.configure("cancel")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"], end["tokens"], end["is_error"]), ("stopped", USAGE_COST, True, 86000, True))
        self.wait_gone(chat_id)
        self.assertEqual(self.methods().count("session/cancel"), 1)
        self.assertEqual(self.choices(), [("cancelled", None)])                # the waiting request was answered as cancelled
        self.assertEqual([x["decision"] for x in self.records(chat_id, "card_decision")], ["cancelled"])
        self.assertEqual(self.unexpected(), [])

    def test_stop_while_the_agent_is_only_thinking(self):
        self.configure("cancel-idle")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait(lambda: "session/prompt" in self.methods(), "the message to arrive")
        time.sleep(0.2)
        self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"]), ("stopped", USAGE_COST))
        self.wait_gone(chat_id)

    def test_a_cancelled_turn_that_is_never_ended_by_the_agent_costs_its_cap_and_the_process_is_ended(self):
        self.configure("unfinished")
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.wait_card(chat_id)
        self.dm._chats[chat_id].stop_wait = 0.3
        self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"], end["tokens"]), ("stopped", r["result"]["cap_usd"], False, None))
        self.wait_gone(chat_id)
        self.assertIn("sigterm", [x["event"] for x in self.fake_log()])          # the group was ended: it did not close by itself

    def test_the_daemon_closing_does_not_wait_for_the_agent(self):
        self.configure("unfinished")
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.wait_card(chat_id)
        started = time.monotonic()
        self.stop_daemon()
        self.assertLess(time.monotonic() - started, 15)
        self.start_daemon()
        end = next(x for x in self.events(chat_id)[0] if x["kind"] == "turn_ended")
        self.assertEqual(end["cost_usd"], r["result"]["cap_usd"])
        self.assertNotEqual(end["estimate"], True)

    def test_a_turn_that_takes_too_long_costs_its_cap(self):
        self.dm.chat_turn_timeout = 0.5
        self.configure("unfinished")
        chat_id = self.open_chat()
        r = self.send(chat_id)
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"]), ("error", r["result"]["cap_usd"], False))
        self.wait_gone(chat_id)

    def test_a_usage_that_does_not_add_up_costs_the_cap(self):
        bad = {"inputTokens": 60000, "outputTokens": 2000, "cachedReadTokens": 24000, "cachedWriteTokens": 0, "thoughtTokens": 1500, "totalTokens": 99999}
        self.configure({"fixture": "text", "vars": {"USAGE": bad}})
        chat_id = self.open_chat()
        r = self.send(chat_id)
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"], end["tokens"]), ("result", r["result"]["cap_usd"], False, None))
        anomaly = next(x for x in self.records(chat_id, "anomaly"))
        self.assertEqual(anomaly["event_type"], "usage/mismatch")
        self.assertEqual(self.records(chat_id, "usage"), [])

    def test_a_turn_may_cost_more_than_its_cap_and_is_recorded_as_it_was(self):
        (self.base / "config.json").write_text(json.dumps({"chat_limits": {"per_turn_usd": 0.01}}))
        self.configure("text")
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.assertEqual(r["result"]["cap_usd"], "0.01")
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["estimate"], end["tokens"]), ("result", USAGE_COST, True, 86000))

    def test_a_day_with_less_than_a_cent_left_sends_nothing(self):
        self.configure("text")
        chat_id = self.open_chat()
        other = cs.create(self.base, "emp-2", now=time.time(), engine="agy-chat")
        log = cs.ChatLog(self.base, other["id"])
        try:
            log.append("user_message", {"turn": 1, "text": "hi"}, now=time.time())
            log.append("turn_started", {"turn": 1, "cap_usd": "0.5"}, now=time.time())
            log.append("turn_ended", {"turn": 1, "cost_usd": "2.999", "reported": False, "total_usd": None, "reason": "result",
                                      "subtype": "end_turn", "is_error": False, "estimate": True, "tokens": 5}, now=time.time())
        finally:
            log.close()
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {"per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 3}}))
        self.assertEqual(self.send(chat_id)["error"]["code"], "budget")
        (self.base / "config.json").write_text(json.dumps({"meeting_limits": {"per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": 0.01}}))
        self.assertEqual(self.send(chat_id)["error"]["code"], "red")
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id).count("user_message"), 0)


class BeforeAnythingStartsTests(AgyCase):
    def refused(self, code, **cli):
        self.configure("text")
        chat_id = self.open_chat()
        r = self.send(chat_id, cli=self.cli(**cli) if cli else None)
        self.assertEqual(r["error"]["code"], code, r)
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertEqual(os.listdir(self.base / "sessions") if (self.base / "sessions").exists() else [], [])
        return chat_id

    def test_a_version_that_is_not_verified(self):
        with mock.patch.object(cli_versions, "AGY_CHAT_VERIFIED_VERSIONS", ()):
            self.refused("unverified")

    def test_a_version_the_daemon_is_probing_may_start(self):
        self.configure("text")
        chat_id = self.open_chat()
        with mock.patch.object(cli_versions, "AGY_CHAT_VERIFIED_VERSIONS", ()):
            self.dm.agy_chat_probe_versions = frozenset({VERSION})
            self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_version_without_constants(self):
        self.refused("unsupported_version", version="0.1.0")

    def test_the_person_has_hooks(self):
        hooks = self.home / ".agents" / "hooks.json"
        hooks.parent.mkdir()
        hooks.write_text("{}")
        before = (hooks.stat().st_mtime_ns, hooks.read_bytes())
        self.refused("agy_hooks")
        self.assertEqual((hooks.stat().st_mtime_ns, hooks.read_bytes()), before)

    def test_hooks_or_plugins_in_a_folder_above_the_state_folder_refuse_the_start(self):          # R1: AGY looks up from where it starts
        """The state folder is ``tmp/st`` here, so ``tmp`` is a folder above the chat's work folder, as ``$HOME/project`` is for a
        ``VBEAR_HOME=$HOME/project/.vbear``. Nothing is started, moved or deleted."""
        self.configure("text")
        for root, item, kind in (("_agent", "hooks.json", "file"), ("_agents", "plugins", "dir"), (".agent", "plugins.json", "file"),
                                 (".agents", "hooks.json", "file")):
            with self.subTest(root=root, item=item):
                path = self.tmp / root / item
                path.parent.mkdir()
                path.mkdir() if kind == "dir" else path.write_text("{}")
                before = path.stat().st_mtime_ns
                chat_id = self.open_chat()
                r = self.send(chat_id)
                self.assertEqual(r["error"]["code"], "agy_hooks", r)
                self.assertIn(f"{root}/{item}", r["error"]["message"], "it says which one")
                self.assertEqual(self.starts(), [])
                self.assertEqual(self.kinds(chat_id), ["chat_created"])
                self.assertEqual(path.stat().st_mtime_ns, before)
                path.rmdir() if kind == "dir" else path.unlink()
                path.parent.rmdir()
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"], "and a start with nothing above goes on as before")
        self.wait_turn(chat_id, 1)

    def test_the_person_has_a_plugin_in_another_customization_root(self):          # P56-2
        plugins = self.home / "_agents" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "p").mkdir()
        before = plugins.stat().st_mtime_ns
        self.refused("agy_hooks")
        self.assertEqual(plugins.stat().st_mtime_ns, before)
        self.assertEqual(sorted(os.listdir(plugins)), ["p"], "nothing was moved or deleted")

    def test_a_chat_folder_with_something_that_is_not_ours(self):
        home = env.chat_home_path(self.base)
        home.mkdir(mode=0o700)
        (home / "GEMINI.md").write_text("rules")
        self.refused("agy_home")

    def test_a_chat_folder_that_is_open_to_others(self):
        home = env.chat_home_path(self.base)
        home.mkdir(mode=0o700)
        os.chmod(home, 0o755)
        self.refused("agy_home")

    def test_an_underscore_agents_in_the_work_folder(self):          # P56-2
        os.mkdir(os.path.join(self.work(), "_agents"))
        self.refused("agy_workdir")

    def test_a_dot_agents_in_the_work_folder(self):
        os.mkdir(os.path.join(self.work(), ".agents"))
        self.refused("agy_workdir")

    def test_a_binary_that_changed_since_it_was_checked(self):
        self.configure("text")
        chat_id = self.open_chat()
        identity = a.binary_identity(str(self.binary))
        self.assertEqual(self.send(chat_id, cli=self.cli(identity=[identity[0] + 1] + identity[1:]))["error"]["code"], "drift")

    def test_the_administrator_policy(self):
        self.configure("text")
        chat_id = self.open_chat()
        bad = admin_policy.PolicyCheck(False, found=["/etc/antigravity"], problems=["found"])
        with mock.patch("vbear.runtime.daemon_chat.admin_policy.check_agy", return_value=bad):
            self.assertEqual(self.send(chat_id)["error"]["code"], "admin_policy")
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_the_input_is_checked(self):
        self.configure("text")
        chat_id = self.open_chat()
        for kw in (dict(model_id="gemini-4-argon-medium"), dict(model_id="bad model"), dict(instructions="x" * 2001),
                   dict(cli={"binary": str(self.binary)})):
            self.assertEqual(self.send(chat_id, **kw)["error"]["code"], "bad_request", kw)
        self.assertEqual(self.send(chat_id, "  ")["error"]["code"], "bad_request")
        self.assertEqual(self.fake_log(), [])


class WhatIsNotKeptTests(AgyCase):
    def test_a_whole_chat_keeps_nothing_of_the_account_the_folder_or_the_skills(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id, "ls")["ok"])
        card = self.wait_card(chat_id)
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        self.wait_turn(chat_id, 1)
        self.assert_nothing_of_the_account_kept(chat_id)
        live = json.dumps(self.events(chat_id)[1])
        for secret in fx.SENSITIVE:
            self.assertNotIn(secret, live)
        listing = json.dumps(self.rpc("list"))
        for secret in fx.SENSITIVE + (str(env.chat_home_path(self.base)),):
            self.assertNotIn(secret, listing)

    def test_the_manifest_of_a_launch_in_progress_is_an_agy_chat_one(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        [name] = os.listdir(self.base / "sessions")
        m = a._read_manifest(a.launch_dir(self.base, name), os.getuid())
        self.assertEqual((m["engine"], m["state"], m["chat_id"]), ("agy-chat", "running", chat_id))
        self.assertIsNone(a.agy_chat_manifest_problem(m))
        self.assertIsInstance(self.dm._chats[chat_id], acs.AgyChatProcess)
        info = next(s for s in self.rpc("list")["result"]["sessions"] if s.get("engine") == "agy-chat")
        self.assertEqual(info["activity_evidence"], {"agy_chat": {"state": "waiting_for_you"}})

    def test_a_leftover_launch_is_cleaned_when_the_chat_ends(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.rpc("chat_close", chat_id=chat_id)
        self.wait_gone(chat_id)
        self.wait(lambda: os.listdir(self.base / "sessions") == [], "the launch to be cleaned")


class TerminalTests(unittest.TestCase):
    def test_an_agy_card_in_a_terminal_is_still_full_mode_only(self):
        from vbear import ai_tools
        tool = next(t for t in ai_tools.REGISTRY if t.id == "agy")
        self.assertFalse(tool.safe_launch)
        self.assertFalse(tool.safe_mode)
        self.assertTrue(tool.full_launch)
        self.assertIn("完整模式", tool.not_launchable_message)


if __name__ == "__main__":
    unittest.main()
