"""P46-3 (ADR 0009, ADR 0012): the shared folder in an AGY chat, through the runtime daemon with the fake ``agy`` (tests/fake_agy_acp.py, synthetic
scripts). The field ``shared`` of ``chat_send`` is only ever ``true`` and only for a version of AGY whose chat check passed with the shared
folder; the daemon computes the path itself, names it to AGY as one more folder (``--add-dir``), tells the employee in the system prompt,
and judges every file change and read with the folder as a second root. Every change there is a card; a path through a link out, a protected
name or a hard-linked file is refused with no card. The page's switch is P46-5's: here the service is told by an injected switch. Nothing
real is run."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests import agy_chat_fixtures as fx
from tests.test_p46_agy_chat_api import ApiCase
from tests.test_p46_agy_chat_daemon import SESSION, VERSION, AgyCase, file_call, permission
from vbear.runtime import agent_sessions as a
from vbear.runtime import agy_chat_env as env
from vbear.runtime import agy_chat_protocol as acp
from vbear.runtime import chat_store as cs, cli_versions, memory_rules as mr, shared_rules as sr


class SharedAgyCase(AgyCase):
    checked = True

    def setUp(self):
        super().setUp()
        if self.checked:                      # the version has passed the chat check with the shared folder
            p = mock.patch.object(cli_versions, "shared_verified", side_effect=lambda engine, version: engine == "agy-chat")
            p.start()
            self.addCleanup(p.stop)
        self.shared = sr.shared_path(self.base)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def send_with(self, chat_id, shared="absent", text="hello", **more):
        if shared != "absent":
            more["shared"] = shared
        return self.send(chat_id, text, **more)

    def argv(self, index=-1):
        return self.starts()[index]["argv"]

    def session_prompt(self, method="session/new"):
        got = next(x for x in self.stdin() if x.get("method") == method)["params"]
        return got["_meta"]["antigravity"]["systemPrompt"]["append"] if "_meta" in got else None

    def prompt_sha(self, chat_id):
        return cs.prompt_start(self.base, chat_id)["sha"]


class WhatTheProcessGetsTests(SharedAgyCase):
    def test_on_the_folder_is_one_more_folder_named_and_told(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.argv(), acp.argv_for(acp.VERSIONS[VERSION], str(env.chat_home_path(self.base)), shared=self.shared))
        self.assertEqual(self.argv()[-2:], ["--add-dir", self.shared])
        self.assertEqual(os.lstat(self.shared).st_mode & 0o7777, 0o700)
        self.assertEqual(self.starts()[0]["shared"], self.shared)
        self.assertEqual(self.session_prompt(), sr.block(self.shared))
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha(None, None, sr.block(self.shared)))
        self.assertEqual(self.unexpected(), [])

    def test_with_instructions_and_memory_the_paragraphs_come_in_the_order_the_other_engines_use(self):
        memory = [{"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"}]
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True, instructions="先說結論。", memory=memory)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.session_prompt(), mr.combine("先說結論。", mr.block(memory), sr.block(self.shared)))

    def test_off_nothing_of_it_is_there(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertNotIn("--add-dir", self.argv())
        self.assertIsNone(self.starts()[0]["shared"])
        self.assertIsNone(self.session_prompt())
        self.assertFalse(os.path.lexists(self.shared))
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha(None, None))
        [name] = os.listdir(self.base / "sessions") if (self.base / "sessions").exists() and os.listdir(self.base / "sessions") else [None]
        if name:
            self.assertNotIn("shared", a._read_manifest(a.launch_dir(self.base, name), os.getuid()))

    def test_the_record_has_no_new_field_and_no_path(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        started = next(x for x in self.events(chat_id)[0] if x["kind"] == "process_started")
        self.assertEqual(set(started) - {"seq", "at", "kind"}, {"mode", "budget_usd", "instructions", "identity"})      # P58: one yes-or-no field, no word of the name
        raw = self.raw(chat_id) + json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        self.assertNotIn(self.shared, raw)
        self.assertEqual(cs.prompt_start(self.base, chat_id).keys(), {"sha", "memory"})

    def test_the_log_says_on_or_off_and_never_a_path(self):
        self.configure("text", "resume")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id)["error"]["code"], "restarting")       # the folder of a live process is fixed
        self.wait_gone(chat_id)
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 2)
        lines = [x for x in self.logs if "chat process shared" in x]
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(lines[0], r"^[^:]+: chat process shared=on$")
        self.assertRegex(lines[1], r"^[^:]+: chat process shared=off$")
        self.assertNotIn("--add-dir", self.argv())
        self.assertEqual(self.session_prompt("session/resume"), None)

    def test_the_launch_names_the_folder_and_only_that_one(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_card(chat_id)
        [name] = os.listdir(self.base / "sessions")
        m = a._read_manifest(a.launch_dir(self.base, name), os.getuid())
        self.assertEqual(m["shared"], self.shared)
        self.assertIsNone(a.agy_chat_manifest_problem(m))
        self.assertIsNotNone(a.agy_chat_manifest_problem(dict(m, shared=str(self.outside))))


class JudgementTests(SharedAgyCase):
    def finish(self, chat_id):
        self.assertTrue(self.rpc("chat_close", chat_id=chat_id)["ok"])
        self.wait_gone(chat_id)

    def run_call(self, *, kind="edit", rel="n.md", profile="emp-1", decision=None, **vars):
        """One file or read call against ``${SHARED}/rel``; returns (chat id, the records)."""
        self.conf_path.with_name(self.conf_path.name + ".state.json").unlink(missing_ok=True)
        self.configure(permission(**vars))
        chat_id = self.open_chat(profile)
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        if decision:
            self.assertTrue(self.answer(chat_id, self.wait_card(chat_id), decision)["ok"])
        self.wait_turn(chat_id, 1)
        return chat_id, self.events(chat_id)[0]

    def shared_call(self, rel="n.md", **kw):
        where = "${SHARED}/" + rel
        return {"KIND": "edit", "TITLE": "Change a shared file", "RAW_INPUT": {"Path": where, "Content": "x\n"},
                "LOCATIONS": [{"path": where}], "CONTENT": [{"type": "diff", "path": where, "oldText": None, "newText": "x\n"}], **kw}

    def test_a_change_in_the_shared_folder_is_a_card_that_says_who_else_reads_it(self):
        os.makedirs(self.shared, mode=0o700, exist_ok=True)
        chat_id, recs = self.run_call(decision="allow", **self.shared_call())
        card = next(x for x in recs if x["kind"] == "card")
        self.assertEqual(card["tool"], "file_change")
        self.assertIn("共用資料夾", card["reason"])
        self.assertEqual(card["input"]["changes"][0]["path"], os.path.join(self.shared, "n.md"))
        self.assertEqual(self.choices(), [("allow", "allow_once")])

    def test_a_read_in_the_shared_folder_is_allowed_without_a_card(self):
        os.makedirs(self.shared, mode=0o700, exist_ok=True)
        chat_id, recs = self.run_call(KIND="read", TITLE="Read", RAW_INPUT={"Path": "${SHARED}/a.md"}, LOCATIONS=[{"path": "${SHARED}/a.md"}])
        self.assertEqual([x for x in recs if x["kind"] == "card"], [])
        self.assertEqual([x["tool"] for x in recs if x["kind"] == "auto_allowed"], ["read"])

    def test_without_the_folder_the_same_paths_are_outside(self):
        os.makedirs(self.shared, mode=0o700, exist_ok=True)
        call = self.shared_call()                    # the folder is not this process's, so the script cannot name it by ${SHARED}
        for key in ("RAW_INPUT", "LOCATIONS", "CONTENT"):
            call[key] = json.loads(json.dumps(call[key]).replace("${SHARED}", self.shared))
        self.conf_path.write_text(json.dumps({"version": VERSION, "scripts": [permission(**call)]}))
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])             # no shared field: the folder is not this process's
        self.wait_turn(chat_id, 1)
        recs = self.events(chat_id)[0]
        self.assertEqual([x for x in recs if x["kind"] == "card"], [])
        self.assertIn("資料夾以外", next(x for x in recs if x["kind"] == "denied")["reason"])

    def test_the_names_that_are_settings_and_a_hard_link_are_refused_there_too(self):
        os.makedirs(self.shared, mode=0o700, exist_ok=True)
        (Path(self.shared) / "sub").mkdir()
        (Path(self.shared) / "one.md").write_text("fictional")
        os.link(Path(self.shared) / "one.md", self.outside / "two.md")
        cases = [("sub/AGENTS.md", "AGENTS.md"), (".git/config", ".git"), ("one.md", "硬連結")]
        for index, (rel, word) in enumerate(cases):
            with self.subTest(rel=rel):
                chat_id, recs = self.run_call(profile=f"emp-{index + 1}", **self.shared_call(rel))
                self.assertEqual([x for x in recs if x["kind"] == "card"], [])
                self.assertIn(word, next(x for x in recs if x["kind"] == "denied")["reason"])
                self.finish(chat_id)
        self.assertEqual(sorted(os.listdir(self.outside)), ["two.md"])

    def test_the_folder_itself_is_not_a_file(self):
        os.makedirs(self.shared, mode=0o700, exist_ok=True)
        chat_id, recs = self.run_call(**self.shared_call(""))
        self.assertIn("共用資料夾本身", next(x for x in recs if x["kind"] == "denied")["reason"])

    def test_a_folder_that_became_a_link_while_a_card_waited_is_refused_when_allowed(self):
        os.mkdir(self.shared, 0o700)
        os.mkdir(os.path.join(self.shared, "sub"), 0o700)
        self.configure(permission(**self.shared_call("sub/n.md")))
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        card = self.wait_card(chat_id)
        os.rmdir(os.path.join(self.shared, "sub"))
        os.symlink(self.outside, os.path.join(self.shared, "sub"))
        r = self.answer(chat_id, card, "allow")
        self.assertEqual(r["error"]["code"], "refused", r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.choices(), [("deny", "reject_once")])
        self.assertEqual(list(self.outside.iterdir()), [])


class FolderChecksTests(SharedAgyCase):
    def refused(self, code):
        self.configure("text")
        chat_id = self.open_chat()
        r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], code, r)
        self.assertEqual(self.fake_log(), [], "nothing was started")
        self.assertEqual(self.kinds(chat_id), ["chat_created"], "nothing was written to the record")
        self.assertNotIn(self.shared, r["error"]["message"])
        return r

    def test_a_folder_with_other_permissions_is_not_used_and_not_mended(self):
        os.mkdir(self.shared, 0o700)
        os.chmod(self.shared, 0o755)
        self.refused("shared_unsafe")
        self.assertEqual(os.lstat(self.shared).st_mode & 0o7777, 0o755)

    def test_a_link_in_its_place_is_not_used(self):
        os.symlink(self.outside, self.shared)
        self.refused("shared_unsafe")
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_a_sparse_file_over_one_gib_stops_a_new_process_and_costs_nothing(self):
        os.mkdir(self.shared, 0o700)
        big = Path(self.shared) / "sparse.bin"
        with open(big, "wb") as f:
            os.truncate(f.fileno(), (1 << 30) + 1)
        r = self.refused("shared_full")
        self.assertIn("Finder", r["error"]["message"])
        os.truncate(big, 1 << 20)
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_chat_with_it_off_is_not_stopped_by_a_full_folder(self):
        os.mkdir(self.shared, 0o700)
        for i in range(4):
            (Path(self.shared) / f"f{i}.md").write_text("x")
        self.configure("text")
        chat_id = self.open_chat()
        with mock.patch.object(sr, "MAX_ENTRIES", 3):
            self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_path_that_cannot_be_an_argument_is_refused(self):
        with mock.patch.object(sr, "MAX_BLOCK", 10):
            self.refused("shared_unsafe")

    def test_a_shared_folder_that_holds_what_agy_would_read_as_settings_is_not_used(self):
        for name in (".agents", ".gemini", "GEMINI.md", "agents.md"):
            with self.subTest(name=name):
                os.makedirs(self.shared, mode=0o700, exist_ok=True)
                (Path(self.shared) / name).mkdir() if not name.endswith(".md") else (Path(self.shared) / name).write_text("rules")
                self.refused("shared_unsafe")
                if (Path(self.shared) / name).is_dir():
                    (Path(self.shared) / name).rmdir()
                else:
                    (Path(self.shared) / name).unlink()

    def test_a_link_in_the_shared_folder_that_leads_out_is_not_used(self):
        os.makedirs(self.shared, mode=0o700, exist_ok=True)
        os.symlink(self.outside, os.path.join(self.shared, "out"))
        self.refused("shared_unsafe")

    def test_a_switch_that_changed_gives_way_to_a_new_process(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id, True)["error"]["code"], "restarting")


class NotCheckedTests(SharedAgyCase):
    checked = False

    def test_a_version_that_has_not_passed_the_check_with_the_folder_is_refused_before_anything_is_made(self):
        self.configure("text")
        chat_id = self.open_chat()
        r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], "shared_unverified", r)
        self.assertIn("Google 方案", r["error"]["message"])
        self.assertEqual(self.fake_log(), [])
        self.assertFalse(os.path.lexists(self.shared))
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_without_the_folder_the_same_version_chats(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)

    def test_the_version_the_check_itself_is_probing_may_use_the_folder(self):
        self.configure("text")
        chat_id = self.open_chat()
        self.dm.agy_chat_probe_versions = frozenset({VERSION})
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)

    def test_shared_is_only_ever_true(self):
        self.configure("text")
        chat_id = self.open_chat()
        for bad in (False, 1, "yes", None, {}):
            self.assertEqual(self.send_with(chat_id, bad)["error"]["code"], "bad_request", bad)
        self.assertEqual(self.fake_log(), [])


class ThroughTheServiceTests(ApiCase):
    """The console's side: the switch it reads (here injected) becomes ``shared: true``, only for a version that was checked."""

    def setUp(self):
        super().setUp()
        self.checked = True
        p = mock.patch.object(cli_versions, "shared_verified", side_effect=lambda engine, version: self.checked and engine == "agy-chat")
        p.start()
        self.addCleanup(p.stop)
        self.svc._shared = lambda pid, engine: engine == "agy-chat" and pid == self.emp
        self.shared = sr.shared_path(self.base)

    def test_a_switched_on_card_with_a_checked_version_chats_with_the_folder(self):
        self.configure("text")
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        self.assertEqual(self.starts()[0]["argv"][-2:], ["--add-dir", self.shared])

    def test_an_unchecked_version_is_refused_by_the_service_in_words_before_the_daemon_is_asked(self):
        self.checked = False
        self.configure("text")
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "shared_unverified"))
        self.assertIn("AGY", out["error"])
        self.assertIn("Google 方案", out["error"])
        self.assertIn("你的訊息還沒有送出", out["error"])
        self.assertEqual(self.fake_log(), [])

    def test_a_card_that_is_not_switched_on_sends_no_field(self):
        other = self.card("沒打開的員工")
        self.configure("text")
        chat_id = self.open_http(other)
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        self.assertNotIn("--add-dir", self.starts()[0]["argv"])

    def test_the_version_the_page_asks_about_is_the_pinned_one(self):
        self.assertEqual(self.svc.shared_checked(["agy-chat", "codex-chat"]), {"agy-chat": True, "codex-chat": None})
        self.checked = False
        self.svc._versions.clear()
        self.assertEqual(self.svc.shared_checked(["agy-chat"]), {"agy-chat": False})


if __name__ == "__main__":
    unittest.main()
