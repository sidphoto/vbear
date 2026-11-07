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

    def replaced(self, chat_id, turn, **second):
        """The first message started a process with ENTRIES and 'old'; the second one, with ``second``, must be told to wait for a
        new process, and the third (after the old one is gone) is the new process, resumed, for turn ``turn``."""
        r = self.send_mem(chat_id, **second)
        self.assertEqual(r["error"]["code"], "restarting", r)
        self.assertIn("記憶或固定指示", r["error"]["message"])
        self.wait_gone(chat_id)
        r = self.send_mem(chat_id, **second)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (turn, "resume"))
        self.wait_turn(chat_id, turn)

    def test_nothing_changed_the_process_is_reused(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_mem(chat_id, ENTRIES, "old")
        self.assertEqual((r["result"]["turn"], r["result"]["process"]), (2, "reused"))
        self.wait_turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 1)

    def test_a_changed_line_means_a_new_process_that_carries_the_new_one(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2, memory=OTHER, instructions="old")
        self.assertEqual([self.appended(0), self.appended(1)], ["old\n\n" + mr.block(ENTRIES), "old\n\n" + mr.block(OTHER)])
        self.assertEqual(self.starts()[1]["argv"][-2], "--resume")

    def test_changed_instructions_of_the_card_mean_a_new_process_too(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2, memory=ENTRIES, instructions="new")
        self.assertEqual(self.appended(1), "new\n\n" + mr.block(ENTRIES))

    def test_instructions_without_any_memory_follow_the_same_rule(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, instructions="old")["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2, instructions="new")
        self.assertEqual([self.appended(0), self.appended(1)], ["old", "new"])

    def test_a_card_just_switched_off_does_not_keep_its_old_process_with_the_old_memory(self):
        """The service sends no ``memory`` field for a switched-off card: the live process that still carries the lines is replaced."""
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2)
        self.assertEqual(self.appended(0), mr.block(ENTRIES))
        self.assertIsNone(self.appended(1), "not a word of it, not even the explanation")
        self.assertNotIn(ENTRIES[1]["text"], json.dumps(self.starts()[1], ensure_ascii=False))

    def test_a_card_just_switched_on_gets_a_new_process_with_the_lines(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2, memory=ENTRIES)
        self.assertEqual((self.appended(0), self.appended(1)), (None, mr.block(ENTRIES)))

    def test_an_empty_list_and_no_field_are_not_the_same_prompt(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, [])["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2)

    def test_the_log_and_the_record_say_how_many_and_never_what(self):
        self.configure([clean("text", 0), clean("text", 1)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        self.replaced(chat_id, 2, memory=OTHER, instructions="old")
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

    def test_a_changed_line_or_changed_instructions_mean_a_new_process(self):
        self.configure(start=[0], resume=[0, 0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, "old")["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_mem(chat_id, OTHER, "old")
        self.assertEqual(r["error"]["code"], "restarting", r)
        self.assertIn("記憶或固定指示", r["error"]["message"])
        self.wait_gone(chat_id)
        r = self.send_mem(chat_id, OTHER, "old")
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 2)
        r = self.send_mem(chat_id, OTHER, "new")
        self.assertEqual(r["error"]["code"], "restarting", r)
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id, OTHER, "new")["ok"])
        self.wait_turn(chat_id, 3)
        self.assertEqual(self.developers(), ["old\n\n" + mr.block(ENTRIES), "old\n\n" + mr.block(OTHER), "new\n\n" + mr.block(OTHER)])

    def test_a_card_switched_off_replaces_the_process_that_has_the_lines(self):
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_mem(chat_id)["error"]["code"], "restarting")
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id)["ok"])
        self.wait_turn(chat_id, 2)
        self.assertEqual(self.developers(), [mr.block(ENTRIES), None])

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
