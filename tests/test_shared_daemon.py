"""P43-1 (ADR 0009): the shared folder in a Claude chat, through the runtime daemon with the fake Claude Code (tests/fake_chat_cli.py). The
field ``shared`` of ``chat_send`` is only ever ``true``; the daemon computes the path itself, checks the folder and how full it is, gives
the Bash sandbox one more place to write, tells the employee in the system prompt, and judges every file tool with the folder as a
second root. Every Edit and Write there is a card; a path through a link out, a protected name or a hard-linked file is refused with no
card. A change of the switch makes the idle process give way to a new one. Nothing here starts a real AI tool."""

from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests import test_chat_daemon as tcd
from tests.test_chat_daemon import MODEL, clean
from vbear.runtime import chat_store as cs, cli_versions, memory_rules as mr, shared_rules as sr

V0170_EMPTY_SHA = "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"      # printed by the unchanged v0.17.0 code
MEMORY = [{"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"}]


class SharedCase(tcd.ChatCase):
    def setUp(self):
        super().setUp()
        # P43-2: only a version whose chat check passed with the shared folder may use it; these tests are about the folder, not that gate
        # (tests/test_shared_codex_daemon.py NotCheckedTests and tests/test_shared_verified.py are)
        p = mock.patch.object(cli_versions, "shared_verified", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.shared = sr.shared_path(self.base)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def send_with(self, chat_id, shared="absent", text="hello", **more):
        fields = dict(chat_id=chat_id, text=text, cli=self.cli(), model_id=MODEL, **more)
        if shared != "absent":
            fields["shared"] = shared
        return self.rpc("chat_send", **fields)

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def argv(self, index=-1):
        return self.starts()[index]["argv"]

    def appended(self, index=-1):
        argv = self.argv(index)
        return argv[argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in argv else None

    def allow_write(self, index=-1):
        argv = self.argv(index)
        path = argv[argv.index("--settings") + 1]
        return json.loads(Path(path).read_text())["sandbox"]["filesystem"]["allowWrite"]

    def prompt_sha(self, chat_id):
        return cs.prompt_start(self.base, chat_id)["sha"]

    def file_turn(self, tool, path, **inp):
        """One scripted turn: the recorded Write turn with its permission request rewritten to ``tool`` on ``path``."""
        steps = clean("ask", 2)
        ask = next(s["ask"] for s in steps if "ask" in s)
        ask["request"]["tool_name"] = tool
        ask["request"]["input"] = {"file_path": path, **inp}
        return steps

    def tool_log(self, chat_id):
        return [r for r in self.events(chat_id)[0] if r["kind"] in ("card", "auto_allowed", "denied")]


class FieldTests(SharedCase):
    def test_only_true_is_accepted_and_nothing_starts_for_anything_else(self):
        chat_id = self.open_chat()
        for bad in (False, None, 1, 0, "true", "yes", [], {}, [True], 1.0):
            with self.subTest(bad=repr(bad)):
                r = self.send_with(chat_id, bad)
                self.assertEqual(r["error"]["code"], "bad_request", r)
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertFalse(os.path.lexists(self.shared), "the folder is not made for a message that was refused")

    def test_a_path_cannot_be_sent_along(self):
        chat_id = self.open_chat()
        for field in ("shared_path", "shared_folder", "add_dir", "writable_roots"):
            r = self.send_with(chat_id, True, **{field: str(self.outside)})
            self.assertEqual((r["error"]["code"], "shared" in r["error"]["message"] or field in r["error"]["message"]), ("bad_request", True), r)
        self.assertEqual(self.fake_log(), [])
        self.assertFalse(os.path.lexists(self.shared))

    def test_a_version_that_has_not_passed_the_check_with_the_folder_is_refused_before_anything_is_made(self):
        chat_id = self.open_chat()
        with mock.patch.object(cli_versions, "shared_verified", return_value=False):
            r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], "shared_unverified", r)
        self.assertIn("共用資料夾", r["error"]["message"])
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertFalse(os.path.lexists(self.shared))

    def test_the_checks_own_daemon_may_use_it_for_the_version_it_is_checking(self):
        self.dm.chat_probe_versions = frozenset({self.cli()["version"]})
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        with mock.patch.object(cli_versions, "shared_verified", return_value=False):
            self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)


class NewProcessTests(SharedCase):
    def test_on_the_sandbox_may_write_there_and_the_employee_is_told_and_nothing_else_is_added(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        r = self.send_with(chat_id, True)
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.allow_write()[-1], self.shared)
        self.assertEqual(len(self.allow_write()), 3)
        self.assertEqual(self.appended(), sr.block(self.shared))
        argv = self.argv()
        self.assertNotIn("--add-dir", argv)
        self.assertEqual(argv[argv.index("--permission-prompt-tool") + 1], "stdio")
        self.assertEqual(os.lstat(self.shared).st_mode & 0o7777, 0o700, "made by the daemon, private")
        self.assertEqual(self.starts()[-1]["cwd"], os.path.realpath(cs.ensure_work_dir(self.base, "emp-1")))

    def test_the_paragraph_comes_after_the_cards_instructions_and_the_memory(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        r = self.send_with(chat_id, True, instructions="先說結論。", memory=MEMORY)
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.appended(), "先說結論。\n\n" + mr.block(MEMORY) + "\n\n" + sr.block(self.shared))

    def test_off_nothing_of_it_is_in_the_process_and_the_fingerprint_is_the_one_of_v0_17_0(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(len(self.allow_write()), 2)
        self.assertNotIn(self.shared, json.dumps(self.starts()))
        self.assertIsNone(self.appended())
        self.assertEqual(self.prompt_sha(chat_id), V0170_EMPTY_SHA)
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha(None, None))
        self.assertFalse(os.path.lexists(self.shared), "off: the daemon makes no folder")

    def test_off_with_instructions_and_memory_is_as_before_too(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, instructions="先說結論。", memory=MEMORY)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.appended(), "先說結論。\n\n" + mr.block(MEMORY))
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha("先說結論。", mr.block(MEMORY)))

    def test_on_the_kept_fingerprint_covers_the_paragraph_and_the_record_has_no_new_field(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha(None, None, sr.block(self.shared)))
        self.assertNotEqual(self.prompt_sha(chat_id), V0170_EMPTY_SHA)
        started = next(x for x in self.events(chat_id)[0] if x["kind"] == "process_started")
        self.assertEqual(set(started) - {"seq", "at", "kind"}, {"mode", "budget_usd", "instructions", "identity"})      # P58: one yes-or-no field, no word of the name
        self.assertEqual(cs.prompt_start(self.base, chat_id).keys(), {"sha", "memory"})
        self.assertEqual(set(cs.KINDS["process_started"]), {"mode", "budget_usd", "instructions"})
        self.assertNotIn(self.shared, self.raw(chat_id))
        raw = self.raw(chat_id) + json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        self.assertNotIn("shared", "".join(x["kind"] for x in self.events(chat_id)[0]))
        self.assertNotIn(self.shared, raw)

    def test_a_resumed_process_does_not_rewrite_what_the_session_started_with(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        first = self.prompt_sha(chat_id)
        self.wait_gone(chat_id)
        r = self.send_with(chat_id)                              # now off: the sandbox follows the switch, the words do not
        self.assertEqual(r["result"]["process"], "resume", r)
        self.wait_turn(chat_id, 2)
        self.assertEqual(self.prompt_sha(chat_id), first)
        self.assertEqual(len(self.allow_write()), 2, "off now: the sandbox has no shared folder")
        self.assertEqual(self.starts()[-1]["system_prompt"], sr.block(self.shared), "the session still works with what it started with")

    def test_the_log_says_on_or_off_and_never_a_path(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 2)
        lines = [x for x in self.logs if "chat process shared" in x]
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(lines[0], r"^[^:]+: chat process shared=on$")
        self.assertRegex(lines[1], r"^[^:]+: chat process shared=off$")
        for line in self.logs:
            self.assertNotIn(self.shared, line)


class FolderChecksTests(SharedCase):
    def refused(self, code):
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

    def test_a_link_in_its_place_is_not_used_and_nothing_is_made_through_it(self):
        os.symlink(self.outside, self.shared)
        self.refused("shared_unsafe")
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_a_file_in_its_place_is_not_used(self):
        Path(self.shared).write_text("fictional")
        self.refused("shared_unsafe")
        self.assertEqual(Path(self.shared).read_text(), "fictional")

    def test_too_many_entries_stop_a_new_process(self):
        os.mkdir(self.shared, 0o700)
        for i in range(4):
            (Path(self.shared) / f"f{i}.md").write_text("x")
        with mock.patch.object(sr, "MAX_ENTRIES", 3):
            r = self.refused("shared_full")
        self.assertIn("Finder", r["error"]["message"])

    def test_a_sparse_file_over_one_gib_stops_a_new_process_and_costs_nothing(self):
        os.mkdir(self.shared, 0o700)
        big = Path(self.shared) / "sparse.bin"
        with open(big, "wb") as f:
            os.truncate(f.fileno(), (1 << 30) + 1)
        self.refused("shared_full")
        os.truncate(big, 1 << 20)                                      # tidied in Finder: it goes on
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_chat_with_it_off_is_not_stopped_by_a_full_folder(self):
        os.mkdir(self.shared, 0o700)
        for i in range(4):
            (Path(self.shared) / f"f{i}.md").write_text("x")
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        with mock.patch.object(sr, "MAX_ENTRIES", 3):
            self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)

    def test_how_full_it_is_looked_at_when_a_process_begins_not_while_it_runs(self):
        os.mkdir(self.shared, 0o700)
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        for i in range(4):
            (Path(self.shared) / f"f{i}.md").write_text("x")
        with mock.patch.object(sr, "MAX_ENTRIES", 3):
            r = self.send_with(chat_id, True)
        self.assertEqual(r["result"]["process"], "reused", r)

    def test_a_folder_made_unsafe_while_a_process_runs_stops_the_next_message(self):
        os.mkdir(self.shared, 0o700)
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        os.chmod(self.shared, 0o777)
        self.assertEqual(self.send_with(chat_id, True)["error"]["code"], "shared_unsafe")

    def test_a_path_that_makes_the_paragraph_too_long_is_refused(self):
        with mock.patch.object(sr, "MAX_BLOCK", 10):
            self.refused("shared_unsafe")


class WriteTests(SharedCase):
    def run_turn(self, steps, shared=True):
        self.configure([steps])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, shared)["ok"])
        return chat_id

    def test_a_write_there_is_a_card_that_says_who_can_read_it_and_allow_answers_yes(self):
        os.mkdir(self.shared, 0o700)
        chat_id = self.run_turn(self.file_turn("Write", f"{self.shared}/price.md", content="fictional"))
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("Write", "content"))
        self.assertEqual(card["input"]["file_path"], f"{self.shared}/price.md")
        rec = next(r for r in self.events(chat_id)[0] if r["kind"] == "card")
        self.assertIn("共用資料夾", rec["reason"])
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        [answer] = self.answers()
        self.assertEqual(answer["response"]["response"]["behavior"], "allow")
        self.assertEqual(answer["response"]["response"]["updatedInput"]["file_path"], f"{self.shared}/price.md")

    def test_an_edit_there_is_a_card_too_and_the_person_can_change_what_is_written(self):
        os.mkdir(self.shared, 0o700)
        chat_id = self.run_turn(self.file_turn("Edit", f"{self.shared}/a/b.md", old_string="a", new_string="b"))
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("Edit", "new_string"))
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="modify", value="c")
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.answers()[0]["response"]["response"]["updatedInput"]["new_string"], "c")

    def test_nothing_is_written_by_vbear_and_nothing_is_allowed_by_vbear_itself(self):
        os.mkdir(self.shared, 0o700)
        chat_id = self.run_turn(self.file_turn("Write", f"{self.shared}/price.md", content="fictional"))
        self.wait_card(chat_id)
        self.assertEqual(list(Path(self.shared).iterdir()), [])
        self.assertEqual([r["kind"] for r in self.tool_log(chat_id)], ["card"])
        self.assertEqual(self.answers(), [])

    def test_refused_with_no_card(self):
        os.mkdir(self.shared, 0o700)
        os.symlink(self.outside, Path(self.shared) / "out")
        (Path(self.shared) / "real.md").write_text("x")
        os.link(Path(self.shared) / "real.md", Path(self.shared) / "twin.md")
        (self.outside / "o.md").write_text("fictional")
        os.link(self.outside / "o.md", Path(self.shared) / "from-outside.md")
        paths = [f"{self.shared}/out/x.md", f"{self.shared}/out", f"{self.shared}/.git/config", f"{self.shared}/a/b/.claude/settings.json",
                 f"{self.shared}/.codex/x", f"{self.shared}/.Agents/y", f"{self.shared}/twin.md", f"{self.shared}/from-outside.md",
                 self.shared, str(self.outside / "z.md"), f"{self.shared}/../outside/z.md"]
        self.configure([self.file_turn("Write", p, content="x") for p in paths])
        chat_id = self.open_chat()
        for n, path in enumerate(paths, 1):
            r = self.send_with(chat_id, True, text=f"turn {n}")
            self.assertTrue(r["ok"], (path, r))
            self.wait_turn(chat_id, n)
        recs = self.tool_log(chat_id)
        self.assertEqual([r["kind"] for r in recs], ["denied"] * len(paths))
        self.assertEqual({r["by"] for r in recs}, {"vbear"})
        self.assertNotIn("card", self.kinds(chat_id))
        self.assertEqual([x["response"]["response"]["behavior"] for x in self.answers()], ["deny"] * len(paths))
        self.assertEqual(list(self.outside.iterdir()), [self.outside / "o.md"])

    def test_with_the_switch_off_the_same_write_is_refused_as_before(self):
        os.mkdir(self.shared, 0o700)
        chat_id = self.run_turn(self.file_turn("Write", f"{self.shared}/price.md", content="x"), shared="absent")
        self.wait_turn(chat_id, 1)
        recs = self.tool_log(chat_id)
        self.assertEqual([r["kind"] for r in recs], ["denied"])
        self.assertIn("以外", recs[0]["reason"])

    def test_a_card_answered_after_the_folder_became_a_link_out_is_refused(self):
        os.mkdir(self.shared, 0o700)
        (Path(self.shared) / "sub").mkdir()
        chat_id = self.run_turn(self.file_turn("Write", f"{self.shared}/sub/note.md", content="x"))
        card = self.wait_card(chat_id)
        (Path(self.shared) / "sub").rmdir()
        os.symlink(self.outside, Path(self.shared) / "sub")
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="allow")
        self.assertEqual(r["error"]["code"], "refused", r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.answers()[-1]["response"]["response"]["behavior"], "deny")
        self.assertEqual(list(self.outside.iterdir()), [])


class ReadTests(SharedCase):
    def test_a_read_there_is_allowed_by_vbear_itself(self):
        os.mkdir(self.shared, 0o700)
        self.configure([self.file_turn("Read", f"{self.shared}/price.md")])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual([r["kind"] for r in self.tool_log(chat_id)], ["auto_allowed"])
        self.assertEqual(self.answers()[0]["response"]["response"]["behavior"], "allow")

    def test_a_link_out_of_the_folder_makes_a_read_there_a_card(self):
        os.mkdir(self.shared, 0o700)
        os.symlink(self.outside, Path(self.shared) / "out")
        self.configure([self.file_turn("Read", f"{self.shared}/price.md")])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(card["tool"], "Read")
        self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="deny")
        self.wait_turn(chat_id, 1)

    def test_with_the_switch_off_a_read_there_is_a_card_as_before(self):
        os.mkdir(self.shared, 0o700)
        self.configure([self.file_turn("Read", f"{self.shared}/price.md")])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(card["tool"], "Read")
        self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="deny")
        self.wait_turn(chat_id, 1)


class SwitchChangeTests(SharedCase):
    def test_switching_on_gives_a_new_process_with_the_sandbox_and_the_old_idle_one_goes(self):
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], "restarting", r)
        self.assertEqual(self.kinds(chat_id).count("user_message"), 1, "the refused message wrote nothing")
        self.wait_gone(chat_id)
        r = self.send_with(chat_id, True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["process"], "resume")
        self.wait_turn(chat_id, 2)
        self.assertEqual(self.allow_write()[-1], self.shared)

    def test_switching_off_takes_the_sandbox_away_from_the_next_message_on(self):
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.allow_write()[-1], self.shared, "the first process had it")
        self.assertEqual(self.send_with(chat_id)["error"]["code"], "restarting")
        self.wait_gone(chat_id)
        r = self.send_with(chat_id)
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 2)
        self.assertEqual(len(self.allow_write()), 2, "the second has not")

    def test_the_same_setting_reuses_the_process(self):
        os.mkdir(self.shared, 0o700)
        self.configure([clean("text", 0), clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertEqual(self.send_with(chat_id, True)["result"]["process"], "new")
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id, True)["result"]["process"], "reused")
        self.wait_turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 1)

    def test_a_busy_process_is_left_alone_and_finishes_with_the_sandbox_it_had(self):
        steps = clean("text", 0)
        self.configure([[{"sleep": 1.5}] + steps])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.assertEqual(self.send_with(chat_id, True)["error"]["code"], "busy")
        self.wait_turn(chat_id, 1)
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(len(self.allow_write()), 2)


class NothingElseChangesTests(SharedCase):
    def test_the_argv_with_it_off_is_what_v0_17_0_made(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, instructions="先說結論。")["ok"])
        self.wait_turn(chat_id, 1)
        argv = self.argv()
        for must in ("--safe-mode", "--strict-mcp-config", "--permission-prompt-tool", "--include-partial-messages", "--setting-sources",
                     "--tools", "--append-system-prompt", "--max-budget-usd", "--model", "--session-id"):
            self.assertIn(must, argv)
        self.assertNotIn("--add-dir", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Bash,Read,Edit,Write,Grep,Glob")

    def test_a_full_mode_launch_still_has_two_thousand(self):
        from vbear.runtime import agent_sessions as a
        self.assertEqual(a.MAX_APPEND_PROMPT, 2000)
        self.assertIsNotNone(a.append_prompt_problem("x" * 2001))


if __name__ == "__main__":
    unittest.main()
