"""P42-2: when a chat's live process is given the memory and the card's instructions again, and when it is replaced; the two
environment variables of a Claude Code chat; the settings that keep the tools' own memory off. Through the runtime daemon with the
fake Claude Code (tests/fake_chat_cli.py) and the fake Codex app-server (tests/fake_codex_app_server.py). Nothing here starts a real
AI tool; every line of memory is made up."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests import test_chat_daemon as tcd, test_p38_codex_chat_daemon as tcx
from tests.test_chat_daemon import MODEL, clean
from tests.test_memory_daemon import ENTRIES
from vbear.runtime import chat_store as cs, memory_rules as mr

OTHER = [{"kind": "work", "text": "我的店改叫「QA熊肥皂」（虛構）"}]
REPO = Path(__file__).resolve().parents[1]


class PromptShaTests(unittest.TestCase):
    def test_the_same_prompt_is_the_same_and_a_different_one_is_not(self):
        sha = mr.prompt_sha
        block = mr.block(ENTRIES)
        self.assertEqual(sha("a", block), sha("a", block))
        self.assertEqual(sha(None, None), sha("", ""), "no instructions and empty instructions are one prompt")
        self.assertEqual(len(sha("a", None)), 64)
        distinct = {sha(None, None), sha("a", None), sha("b", None), sha(None, block), sha("a", block), sha("a", mr.block(OTHER)),
                    sha(None, mr.block([]))}
        self.assertEqual(len(distinct), 7)
        self.assertNotEqual(sha("ab", None), sha("a", "b"), "text cannot move from the card's side to the paragraph's")

    def test_nothing_of_the_words_is_in_it(self):
        self.assertNotIn("QA熊", mr.prompt_sha("QA熊皂坊", mr.block(ENTRIES)))


class ClaudeReuseTests(tcd.ChatCase):
    def send_mem(self, chat_id, memory="absent", instructions=None):
        fields = dict(chat_id=chat_id, text="hello", cli=self.cli(), model_id=MODEL)
        if memory != "absent":
            fields["memory"] = memory
        if instructions is not None:
            fields["instructions"] = instructions
        return self.rpc("chat_send", **fields)

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def appended(self, index):
        argv = self.starts()[index]["argv"]
        return argv[argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in argv else None

    def system_prompts(self):
        return [x["system_prompt"] for x in self.starts()]

    def kept(self, chat_id, turn, **second):
        """P42-6: the first message started a process with ENTRIES and 'old'. Claude Code 2.1.319 does not apply a new
        ``--append-system-prompt`` to a session it resumes (found on a real machine), so a message with other memory or other
        instructions goes to the SAME live process: no ``restarting``, no new process (it would only cost more)."""
        r = self.send_mem(chat_id, **second)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (turn, "reused"))
        self.wait_turn(chat_id, turn)
        self.assertEqual(len(self.starts()), 1, "no new process was started for a prompt it would not use")

    def test_nothing_changed_the_process_is_reused(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_mem(chat_id, ENTRIES, "old")
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "reused"))
        self.wait_turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 1)

    def test_a_changed_line_does_not_start_a_new_process(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        self.kept(chat_id, 2, memory=OTHER, instructions="old")
        self.assertEqual(self.system_prompts(), ["old\n\n" + mr.block(ENTRIES)])

    def test_changed_instructions_of_the_card_do_not_start_a_new_process_either(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        self.kept(chat_id, 2, memory=ENTRIES, instructions="new")
        self.assertEqual(self.system_prompts(), ["old\n\n" + mr.block(ENTRIES)])

    def test_instructions_without_any_memory_follow_the_same_rule(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, instructions="old")["ok"])
        self.wait_turn(chat_id, 1)
        self.kept(chat_id, 2, instructions="new")
        self.assertEqual(self.system_prompts(), ["old"])

    def test_a_card_just_switched_off_keeps_its_process_and_what_was_already_sent_cannot_be_taken_back(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.kept(chat_id, 2)
        self.assertEqual(self.system_prompts(), [mr.block(ENTRIES)])

    def test_a_card_just_switched_on_keeps_its_process_too(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.kept(chat_id, 2, memory=ENTRIES)
        self.assertEqual(self.system_prompts(), [None])

    def test_an_empty_list_and_no_field_do_not_start_a_new_process_either(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, [])["ok"])
        self.wait_turn(chat_id, 1)
        self.kept(chat_id, 2)

    def test_a_resumed_process_is_sent_the_new_prompt_but_the_session_keeps_the_old_one(self):
        """The fake Claude Code does as the real 2.1.319 does: the session keeps the system prompt it was started with. The new
        paragraph is on the resumed process's command line (a future version may use it) and is not what the process works
        with; a NEW chat (a new session) works with the new one. The page tells the person (P42-6)."""
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 1), clean("text", 2)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id, OTHER)["ok"])
        self.wait_turn(chat_id, 2)
        starts = self.starts()
        self.assertEqual(starts[1]["argv"][-2], "--resume")
        self.assertEqual(self.appended(1), mr.block(OTHER), "what VBear sends is the current memory")
        self.assertEqual(self.system_prompts(), [mr.block(ENTRIES), mr.block(ENTRIES)], "what the resumed session works with is the first")
        self.wait_gone(chat_id)
        other_chat = self.open_chat("emp-2")
        self.assertTrue(self.send_mem(other_chat, OTHER)["ok"])
        self.wait_turn(other_chat, 1)
        self.assertEqual(self.system_prompts()[-1], mr.block(OTHER), "a new chat gets the new memory")

    def test_the_log_and_the_record_say_how_many_and_never_what(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id, OTHER, "old")["ok"])
        self.wait_turn(chat_id, 2)
        lines = [x for x in self.logs if "chat process memory" in x]
        self.assertEqual([re.search(r"entries=(\S+) instructions=(\S+)$", x).groups() for x in lines], [("3", "yes"), ("1", "yes")])
        blob = self.raw(chat_id) + "\n".join(self.logs)
        for text in [e["text"] for e in ENTRIES + OTHER]:
            self.assertNotIn(text, blob)
        self.assertEqual(set(cs.KINDS["process_started"]), {"mode", "budget_usd", "instructions"})

    def test_a_process_that_is_busy_is_not_replaced_under_the_turn(self):
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_card(chat_id)
        self.assertEqual(self.send_mem(chat_id, OTHER)["error"]["code"], "busy")
        self.assertEqual(len(self.starts()), 1)


    def started_with(self, chat_id):
        return cs.prompt_start(self.base, chat_id)

    def test_what_a_new_session_was_started_with_is_kept_in_a_file_of_its_own_and_never_changed_by_later_messages(self):
        """P42-6: the page needs to know what the chat's session started with, to say when the memory or the instructions are not
        what the chat works with. The fingerprint is VBear's own state (chat-prompt/<chat id>.json), not a field of the record."""
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 1), clean("text", 2)])
        chat_id = self.open_chat()
        self.assertIsNone(self.started_with(chat_id), "nothing before the first message")
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        first = self.started_with(chat_id)
        self.assertEqual(first, {"sha": mr.prompt_sha("old", mr.block(ENTRIES)), "memory": True})
        self.kept(chat_id, 2, memory=OTHER, instructions="new")
        self.assertEqual(self.started_with(chat_id), first, "a live process keeps what it was started with")
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id, OTHER, "new")["ok"])
        self.wait_turn(chat_id, 3)
        self.assertEqual(self.started_with(chat_id), first, "a resumed session keeps the prompt it was started with, so does this")
        path = self.base / "chat-prompt" / f"{chat_id}.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for text in [e["text"] for e in ENTRIES + OTHER]:
            self.assertNotIn(text, path.read_text())
            self.assertNotIn(text, "\n".join(self.logs))
        self.assertEqual(set(cs.KINDS["process_started"]), {"mode", "budget_usd", "instructions"}, "the record has no new field")

    def test_a_chat_started_without_memory_says_so(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.started_with(chat_id), {"sha": mr.prompt_sha(None, None), "memory": False})

    def test_deleting_the_chat_deletes_the_fingerprint_and_an_unreadable_one_is_no_fingerprint(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        path = self.base / "chat-prompt" / f"{chat_id}.json"
        self.assertTrue(path.exists())
        path.write_text("{nope")
        path.chmod(0o600)
        self.assertIsNone(self.started_with(chat_id))
        path.write_text('{"v":1,"sha":"x","memory":true}')
        self.assertIsNone(self.started_with(chat_id), "a sha that is not 64 hex digits")
        path.write_text(json.dumps({"v": 1, "sha": "a" * 64, "memory": True}))
        self.assertEqual(self.started_with(chat_id), {"sha": "a" * 64, "memory": True})
        r = self.rpc("chat_delete", chat_id=chat_id)
        self.assertTrue(r["ok"], r)
        self.assertFalse(path.exists())
        self.assertIsNone(self.started_with(chat_id))


class ClaudeEnvironmentTests(tcd.ChatCase):
    def started(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        return next(x for x in self.fake_log() if x["event"] == "start")

    def test_the_two_variables_are_in_the_chat_process_and_the_tools_own_memory_stays_off(self):
        start = self.started()
        self.assertEqual(start["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")
        self.assertEqual(start["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
        argv = start["argv"]
        self.assertIn("--safe-mode", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--permission-prompt-tool") + 1], "stdio")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "default")

    def test_the_variables_are_set_in_the_chat_process_only(self):
        """Terminals (full mode), meetings and the version checks of other kinds get a plain environment: the names are in the chat
        launch of daemon_chat and in no other module."""
        names = ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS")
        owners = sorted(str(p.relative_to(REPO)) for p in (REPO / "vbear").rglob("*.py") if any(n in p.read_text() for n in names))
        self.assertEqual(owners, ["vbear/runtime/daemon_chat.py"])
        from vbear.runtime import daemon
        env = daemon.build_env()
        for name in names:
            self.assertNotIn(name, env)


class CodexReuseTests(tcx.CodexCase):
    def send_mem(self, chat_id, memory="absent", instructions=None):
        kw = {}
        if memory != "absent":
            kw["memory"] = memory
        if instructions is not None:
            kw["instructions"] = instructions
        return self.send(chat_id, "hello", **kw)

    def developers(self):
        return [x["params"].get("developerInstructions") for x in self.stdin() if x.get("method") in ("thread/start", "thread/resume")]

    def test_nothing_changed_the_process_is_reused(self):
        self.configure(start=[0, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_mem(chat_id, ENTRIES, "old")
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "reused"))
        self.wait_turn(chat_id, 2)
        self.assertEqual(len([x for x in self.fake_log() if x["event"] == "start"]), 1)

    def test_a_changed_line_or_changed_instructions_do_not_start_a_new_process(self):
        """P42-6: whether Codex's ``thread/resume`` applies new developer instructions is not verified, so (as for Claude Code)
        a message with other memory goes to the live process and no process is started for it."""
        self.configure(start=[0, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        for n, (memory, instructions) in enumerate(((OTHER, "old"), (OTHER, "new")), 2):
            r = self.send_mem(chat_id, memory, instructions)
            self.assertTrue(r["ok"], r)
            self.assertEqual((r["result"]["turn"], r["result"]["process"]), (n, "reused"))
            self.wait_turn(chat_id, n)
        self.assertEqual(len([x for x in self.fake_log() if x["event"] == "start"]), 1)
        self.assertEqual(self.developers(), ["old\n\n" + mr.block(ENTRIES)])

    def test_a_card_switched_off_keeps_the_process_that_has_the_lines(self):
        self.configure(start=[0, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_mem(chat_id)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "reused"))
        self.wait_turn(chat_id, 2)
        self.assertEqual(self.developers(), [mr.block(ENTRIES)])

    def test_what_a_new_thread_was_started_with_is_kept_and_a_resumed_one_does_not_change_it(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        first = cs.prompt_start(self.base, chat_id)
        self.assertEqual(first, {"sha": mr.prompt_sha("old", mr.block(ENTRIES)), "memory": True})
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id, OTHER, "new")["ok"])
        self.wait_turn(chat_id, 2)
        self.assertEqual(cs.prompt_start(self.base, chat_id), first)

    def test_the_codex_settings_that_keep_its_own_memory_off(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        argv = next(x for x in self.fake_log() if x["event"] == "start")["argv"]
        self.assertIn(["--disable", "memories"], [argv[i:i + 2] for i in range(len(argv) - 1)])
        settings = [argv[i + 1] for i, x in enumerate(argv) if x == "-c"]
        self.assertIn("project_doc_max_bytes=0", settings)
        self.assertIn('history.persistence="none"', settings)
        self.assertIn("skills.include_instructions=false", settings)
        developer = next(x for x in self.stdin() if x.get("method") == "thread/start")["params"]
        self.assertEqual(developer["approvalPolicy"], "untrusted")


if __name__ == "__main__":
    unittest.main()
