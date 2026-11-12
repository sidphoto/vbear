"""P43-1 (ADR 0009): the shared folder from the person's side of a chat, through the console, the chat service, a real runtime daemon and
the fake Claude Code. The switch on the shared folder page decides what each new message asks of the daemon; a card that is off (or whose
settings cannot be read, or whose AI tool cannot use the folder yet) sends nothing. The chat page's fingerprint compare knows the folder.
Every name, card and file is made up."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests import test_chat_api as tca
from tests.chat_fixtures import without_identity
from tests.test_chat_daemon import clean
from vbear import chat_service, config as cfg
from vbear.runtime import chat_store as cs, cli_versions, memory_rules as mr, shared_rules as sr

# printed by the unchanged v0.17.0 code for a Claude card with memory on and no lines (the explanation and an empty list), no card instructions
V0170_SHA = "ae3d0c1d1e94a1527fb26b296e17da327dac31a8af4ac45976d995fbc0166c33"


class ChatSharedCase(tca.ApiCase):
    def setUp(self):
        super().setUp()
        # P43-2: the gate for a version that has not passed the chat check with the folder has its own tests (tests/test_shared_codex_chat.py)
        p = mock.patch.object(cli_versions, "shared_verified", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.svc.restart_tries = 200
        self.shared = sr.shared_path(cfg.state_dir())

    def switch(self, pid, on=True):
        status, out = self.call("/api/shared/cards", "POST", {"profile_id": pid, "on": on})
        self.assertEqual(status, 200, out)

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def appended(self, index=-1):
        argv = self.starts()[index]["argv"]
        return without_identity(argv[argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in argv else None)      # P58: the name's sentence is tests/test_p58_identity.py's

    def allow_write(self):
        argv = self.starts()[-1]["argv"]
        return json.loads(Path(argv[argv.index("--settings") + 1]).read_text())["sandbox"]["filesystem"]["allowWrite"]

    def talk(self, chat_id, n, text="你好"):
        status, out = self.say(chat_id, text)
        self.assertEqual(status, 202, out)
        self.wait_http_turn(chat_id, n)
        return out


class FromTheSwitchTests(ChatSharedCase):
    def test_a_card_that_is_on_gets_the_folder_in_its_new_chat(self):
        self.switch(self.emp)
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.assertEqual(self.allow_write()[-1], self.shared)
        self.assertEqual(self.appended(), mr.combine(None, mr.block([]), sr.block(self.shared)), "memory first, then the folder")

    def test_every_card_starts_off_and_gets_not_a_word(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.assertEqual(len(self.allow_write()), 2)
        self.assertEqual(self.appended(), mr.block([]), "only the memory's explanation, as in v0.17.0")
        self.assertNotIn(self.shared, json.dumps(self.fake_log(), ensure_ascii=False))
        self.assertFalse(os.path.lexists(self.shared))

    def test_the_switch_of_one_card_is_not_the_switch_of_another(self):
        other = self.card("第二位員工")
        self.switch(self.emp)
        self.configure([clean("text", 0), clean("text", 0)])
        self.talk(self.open_http(other), 1)
        self.assertEqual(self.appended(), mr.block([]))
        self.assertEqual(len(self.allow_write()), 2)

    def test_a_message_through_the_group_and_dispatch_doors_follows_the_same_switch(self):
        self.switch(self.emp)
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.assertTrue(self.svc.send_for_dispatch(chat_id, "接力的一句話", {"dispatch": "d-0123456789ab", "step": 1})["turn"])
        self.wait_http_turn(chat_id, 1)
        self.assertEqual(self.allow_write()[-1], self.shared)

    def test_the_settings_file_that_cannot_be_read_means_off_and_the_chat_goes_on(self):
        self.switch(self.emp)
        (cfg.state_dir() / "shared-meta" / "settings.json").write_text("{broken")
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.assertEqual(len(self.allow_write()), 2)
        self.assertEqual(self.appended(), mr.block([]))

    def test_a_card_of_an_ai_tool_the_folder_is_not_open_to_is_not_sent_it_even_if_the_file_says_so(self):
        grok = self.card("Grok 員工", "grok")
        meta = cfg.state_dir() / "shared-meta"
        meta.mkdir(mode=0o700)
        (meta / "settings.json").write_text(json.dumps({"v": 1, "cards_on": [grok]}))
        self.assertFalse(self.svc._shared(grok, "grok-chat"))
        self.assertFalse(self.svc._shared(grok, None))
        self.assertFalse(self.svc._shared(self.emp, "claude-chat"), "a card nobody switched on")

    def test_a_card_that_is_switched_off_later_gets_a_new_process_without_the_sandbox(self):
        self.switch(self.emp)
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.switch(self.emp, False)
        self.talk(chat_id, 2)
        self.assertEqual(len(self.starts()), 2)
        self.assertEqual(len(self.allow_write()), 2)

    def test_a_card_that_is_switched_on_later_gets_the_sandbox_from_the_next_message_but_is_not_told(self):
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.switch(self.emp)
        self.talk(chat_id, 2)
        self.assertEqual(len(self.starts()), 2)
        self.assertEqual(self.allow_write()[-1], self.shared, "the sandbox follows the switch")
        self.assertEqual(without_identity(self.starts()[-1]["system_prompt"]), mr.block([]), "what it knows follows the start of the chat (P42-6)")

    def test_a_folder_that_is_not_right_stops_the_message_with_words_for_a_person(self):
        self.switch(self.emp)
        os.chmod(self.shared, 0o755)
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_unsafe"))
        self.assertIn("共用資料夾", out["error"])
        self.assertNotIn(self.shared, json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.fake_log(), [])

    def test_a_folder_that_is_full_stops_the_message_with_words_for_a_person(self):
        self.switch(self.emp)
        for i in range(4):
            (Path(self.shared) / f"f{i}.md").write_text("x")
        chat_id = self.open_http()
        with mock.patch.object(sr, "MAX_ENTRIES", 3):
            status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_full"))
        self.assertIn("Finder", out["error"])
        self.assertEqual(self.fake_log(), [])


class WordsTests(unittest.TestCase):
    def test_every_code_the_daemon_can_give_for_the_folder_has_words_for_a_person(self):
        for code in ("shared_unsafe", "shared_full", "shared_unverified"):
            status, text = chat_service.CODE_TEXT[code]
            self.assertEqual(status, 409)
            self.assertIn("共用資料夾", text)
        self.assertIn("Finder", chat_service.CODE_TEXT["shared_full"][1])
        self.assertIn("1 GiB", chat_service.CODE_TEXT["shared_full"][1])
        self.assertIn("檢查", chat_service.CODE_TEXT["shared_unverified"][1])


class ThePageOfAChatTests(ChatSharedCase):
    def shared_of(self, chat_id):
        return self.view(chat_id)["shared"]

    def memory_of(self, chat_id):
        return self.view(chat_id)["memory"]

    def test_the_chat_says_whether_the_folder_is_on_and_usable(self):
        chat_id = self.open_http()
        self.assertEqual(self.shared_of(chat_id), {"on": False, "usable": False, "code": None})
        self.switch(self.emp)
        self.assertEqual(self.shared_of(chat_id), {"on": True, "usable": True, "code": None})
        os.chmod(self.shared, 0o755)
        self.assertEqual(self.shared_of(chat_id), {"on": True, "usable": False, "code": "shared_unsafe"})

    def test_a_chat_started_with_it_off_is_not_changed_and_has_the_fingerprint_of_v0_17_0(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        # P58: the console now tells the employee its name, so the fingerprint is v0.17.0's value plus the identity paragraph; without that paragraph it is still v0.17.0's value
        self.assertEqual(mr.prompt_sha(None, mr.block([])), V0170_SHA)
        self.assertEqual(cs.prompt_start(cfg.state_dir(), chat_id)["sha"],
                         mr.prompt_sha(None, mr.block([]), None, mr.identity_block({"name": "虛構員工", "position": "PM"}, "claude-chat")))
        self.assertFalse(self.memory_of(chat_id)["changed"])
        self.assertIs(self.memory_of(chat_id)["started_with_memory"], True)

    def test_a_chat_started_with_it_on_is_not_changed_while_it_stays_on(self):
        self.switch(self.emp)
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.talk(chat_id, 1)
        self.assertEqual(cs.prompt_start(cfg.state_dir(), chat_id)["sha"],
                         mr.prompt_sha(None, mr.block([]), sr.block(self.shared), mr.identity_block({"name": "虛構員工", "position": "PM"}, "claude-chat")))      # P58: plus the identity paragraph
        self.assertFalse(self.memory_of(chat_id)["changed"])

    def test_switching_it_on_or_off_after_the_start_shows_the_chat_as_changed(self):
        self.configure([clean("text", 0), clean("text", 0)])
        off_chat = self.open_http()
        self.talk(off_chat, 1)
        self.assertFalse(self.memory_of(off_chat)["changed"])
        self.switch(self.emp)
        self.assertTrue(self.memory_of(off_chat)["changed"], "it works with the folder now but was not told of it")
        self.switch(self.emp, False)
        self.assertFalse(self.memory_of(off_chat)["changed"])
        self.switch(self.emp)
        on_chat = self.open_http()
        self.talk(on_chat, 1)
        self.assertFalse(self.memory_of(on_chat)["changed"])
        self.switch(self.emp, False)
        self.assertTrue(self.memory_of(on_chat)["changed"], "it was told of a folder it can no longer write")


if __name__ == "__main__":
    unittest.main()
