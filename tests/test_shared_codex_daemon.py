"""P43-2 (ADR 0009): the shared folder in a Codex chat, through the runtime daemon with the fake ``codex`` (tests/fake_codex_app_server.py, which
replays the turns recorded with 0.163.0 and answers ``thread/start`` with the writable roots the command line named, unless a test tells it
otherwise). The field ``shared`` of ``chat_send`` is only ever ``true`` and only for a version of Codex whose chat check passed with the
shared folder; the daemon computes the path itself, adds the sandbox's writable root, tells the employee in the developer instructions, and
judges every file change with the folder as a second root. Every change there is a card; a path through a link out, a protected name or a
hard-linked file is refused with no card. An answer that lists any other roots stops the chat before the message. Nothing real is run."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests import test_p38_codex_chat_daemon as base
from tests.test_p38_codex_chat_daemon import THREAD, VERSION
from vbear.runtime import chat_store as cs, cli_versions, codex_chat_protocol as ccp, memory_rules as mr, shared_rules as sr

V0170_EMPTY_SHA = "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"      # printed by the unchanged v0.17.0 code
MEMORY = [{"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"}]


class SharedCodexCase(base.CodexCase):
    checked = True

    def setUp(self):
        super().setUp()
        if self.checked:                      # the version has passed the chat check with the shared folder
            p = mock.patch.object(cli_versions, "shared_verified", side_effect=lambda engine, version: engine == "codex-chat")
            p.start()
            self.addCleanup(p.stop)
        self.shared = sr.shared_path(self.base)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def send_with(self, chat_id, shared="absent", text="hello", **more):
        if shared != "absent":
            more["shared"] = shared
        return self.send(chat_id, text, **more)

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def argv(self, index=-1):
        return self.starts()[index]["argv"]

    def configs(self, index=-1):
        argv = self.argv(index)
        return [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]

    def thread_params(self, method="thread/start"):
        return next(x for x in self.stdin() if x.get("method") == method)["params"]

    def turn_policies(self):
        return [x["params"]["sandboxPolicy"] for x in self.stdin() if x.get("method") == "turn/start"]

    def prompt_sha(self, chat_id):
        return cs.prompt_start(self.base, chat_id)["sha"]

    def file_turn(self, rel_or_abs, kind="add"):
        """A recorded text turn with a file change injected after the answer to ``turn/start``, as the fake prints it."""
        change = {"path": rel_or_abs, "kind": {"type": kind}, "diff": "fictional\n"}
        item = {"id": "inject-fc", "type": "fileChange", "status": "inProgress", "changes": [change]}
        started = {"method": "item/started", "params": {"threadId": THREAD, "turnId": "t-inject", "item": item, "startedAtMs": 1}}
        ask = {"method": "item/fileChange/requestApproval", "id": "inject-req",
               "params": {"threadId": THREAD, "turnId": "t-inject", "itemId": "inject-fc", "startedAtMs": 1, "reason": None,
                          "grantRoot": None}}
        return {"turn": 0, "inject": [started, ask]}

    def tool_log(self, chat_id):
        return [r for r in self.events(chat_id)[0] if r["kind"] in ("card", "auto_allowed", "denied")]


class FieldTests(SharedCodexCase):
    def test_only_true_is_accepted_and_nothing_starts_for_anything_else(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        for bad in (False, None, 1, 0, "true", "yes", [], {}, [True], 1.0):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(self.send_with(chat_id, bad)["error"]["code"], "bad_request")
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertFalse(os.path.lexists(self.shared), "the folder is not made for a message that was refused")

    def test_a_path_cannot_be_sent_along(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        for field in ("shared_path", "writable_roots", "add_dir", "shared_folder"):
            r = self.send_with(chat_id, True, **{field: str(self.outside)})
            self.assertEqual(r["error"]["code"], "bad_request", (field, r))
        self.assertEqual(self.fake_log(), [])
        self.assertFalse(os.path.lexists(self.shared))


class NewProcessTests(SharedCodexCase):
    def test_on_the_sandbox_has_the_root_the_turn_names_it_and_the_employee_is_told(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        r = self.send_with(chat_id, True, instructions="先說結論。", memory=MEMORY)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.wait_turn(chat_id, 1)["reason"], "result")
        consts = ccp.VERSIONS[VERSION]
        self.assertEqual(self.argv(), ccp.argv_for(consts, self.work(), shared=self.shared))
        self.assertEqual(self.configs()[-1], ccp.shared_root_setting(self.shared))
        self.assertEqual(len([c for c in self.configs() if "writable_roots" in c]), 1)
        self.assertNotIn("--add-dir", self.argv())
        self.assertEqual(self.turn_policies(), [dict(ccp.SANDBOX_POLICY, writableRoots=[self.shared])])
        self.assertEqual(self.thread_params()["developerInstructions"], "先說結論。\n\n" + mr.block(MEMORY) + "\n\n" + sr.block(self.shared))
        self.assertEqual(self.thread_params()["sandbox"], "workspace-write")
        self.assertEqual(self.thread_params()["approvalPolicy"], "untrusted")
        self.assertEqual(os.lstat(self.shared).st_mode & 0o7777, 0o700, "made by the daemon, private")
        self.assertEqual(self.starts()[-1]["cwd"], self.work())

    def test_off_nothing_of_it_is_in_the_process_and_the_fingerprint_is_the_one_of_v0_17_0(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.argv(), ccp.argv_for(ccp.VERSIONS[VERSION], self.work()))
        self.assertNotIn("writable_roots", json.dumps(self.starts()))
        self.assertEqual(self.turn_policies(), [ccp.SANDBOX_POLICY])
        self.assertNotIn("developerInstructions", self.thread_params())
        self.assertNotIn(self.shared, json.dumps(self.fake_log()))
        self.assertEqual(self.prompt_sha(chat_id), V0170_EMPTY_SHA)
        self.assertFalse(os.path.lexists(self.shared), "off: the daemon makes no folder")

    def test_off_with_instructions_and_memory_is_as_before_too(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, instructions="先說結論。", memory=MEMORY)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.thread_params()["developerInstructions"], "先說結論。\n\n" + mr.block(MEMORY))
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha("先說結論。", mr.block(MEMORY)))

    def test_on_the_kept_fingerprint_covers_the_paragraph_and_the_record_has_no_new_field(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.prompt_sha(chat_id), mr.prompt_sha(None, None, sr.block(self.shared)))
        started = next(x for x in self.events(chat_id)[0] if x["kind"] == "process_started")
        self.assertEqual(set(started) - {"seq", "at", "kind"}, {"mode", "budget_usd", "instructions", "identity"})      # P58: one yes-or-no field, no word of the name
        raw = self.raw(chat_id) + json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        self.assertNotIn(self.shared, raw)
        self.assertEqual(cs.prompt_start(self.base, chat_id).keys(), {"sha", "memory"})

    def test_the_log_says_on_or_off_and_never_a_path(self):
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id)["error"]["code"], "restarting")
        self.wait_gone(chat_id)
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 2)
        lines = [x for x in self.logs if "chat process shared" in x]
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(lines[0], r"^[^:]+: chat process shared=on$")
        self.assertRegex(lines[1], r"^[^:]+: chat process shared=off$")
        for line in self.logs:
            self.assertNotIn(self.shared, line)

    def test_a_resumed_thread_gets_the_root_too(self):
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id, True)["error"]["code"], "restarting")
        self.wait_gone(chat_id)
        r = self.send_with(chat_id, True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["process"], "resume")
        self.wait_turn(chat_id, 2)
        self.assertEqual(self.configs()[-1], ccp.shared_root_setting(self.shared))
        self.assertEqual(self.turn_policies()[-1]["writableRoots"], [self.shared])


class TheAnswerTests(SharedCodexCase):
    def stopped(self, roots):
        self.configure(start=[0], roots=roots)
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        end = self.wait_turn(chat_id, 1)
        self.assertEqual((end["reason"], end["cost_usd"], end["tokens"]), ("not_sent", "0", None))
        self.wait_gone(chat_id)
        self.assertNotIn("turn/start", self.methods(), "the message was never sent")
        error = next(x for x in self.events(chat_id)[0] if x["kind"] == "error")
        self.assertNotIn(self.shared, error["message"])
        self.assertNotIn("fake-user", self.raw(chat_id))
        self.assertNotIn(self.shared, self.raw(chat_id))

    def test_an_empty_list_stops_the_chat(self):
        self.stopped("empty")

    def test_one_more_root_stops_the_chat_first_or_last(self):
        self.stopped("extra")

    def test_one_more_root_before_ours_stops_the_chat(self):
        self.stopped("extra_first")

    def test_only_another_root_stops_the_chat(self):
        self.stopped(["/Users/fake-user/elsewhere"])

    def test_the_folder_twice_stops_the_chat(self):
        self.stopped([self.shared, self.shared])

    def test_the_exact_list_goes_on(self):
        self.configure(start=[0], roots=[self.shared])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.assertEqual(self.wait_turn(chat_id, 1)["reason"], "result")

    def test_with_it_off_a_root_in_the_answer_stops_the_chat_as_before(self):
        self.configure(start=[0], roots=[self.shared])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.assertEqual(self.wait_turn(chat_id, 1)["reason"], "not_sent")


class FileChangeTests(SharedCodexCase):
    def one(self, path, kind="add"):
        self.configure(start=[self.file_turn(path, kind)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        return chat_id

    def test_a_change_there_is_a_card_that_says_who_can_read_it_and_allow_answers_yes(self):
        chat_id = self.one(f"{self.shared}/price.md")
        card = self.wait_card(chat_id)
        self.assertEqual((card["tool"], card["editable"]), ("file_change", "content"))
        rec = next(r for r in self.events(chat_id)[0] if r["kind"] == "card")
        self.assertIn("共用資料夾", rec["reason"])
        self.assertTrue(self.answer(chat_id, card, "allow")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.decisions(), ["accept"])
        self.assertEqual(list(Path(self.shared).iterdir()), [], "VBear wrote nothing")

    def test_a_relative_path_is_the_work_folders_and_one_that_climbs_into_the_folder_is_judged_there(self):
        chat_id = self.one("../../shared/price.md")
        card = self.wait_card(chat_id)
        self.assertEqual(card["tool"], "file_change")
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)

    def test_nothing_is_allowed_by_vbear_itself(self):
        chat_id = self.one(f"{self.shared}/price.md")
        self.wait_card(chat_id)
        self.assertEqual(self.decisions(), [])
        self.assertEqual([r["kind"] for r in self.tool_log(chat_id)], ["card"])

    def test_refused_with_no_card(self):
        os.mkdir(self.shared, 0o700)
        os.symlink(self.outside, Path(self.shared) / "out")
        (Path(self.shared) / "real.md").write_text("x")
        os.link(Path(self.shared) / "real.md", Path(self.shared) / "twin.md")
        paths = [f"{self.shared}/out/x.md", f"{self.shared}/.git/config", f"{self.shared}/a/b/.claude/x", f"{self.shared}/.codex/x",
                 f"{self.shared}/.Agents/y", f"{self.shared}/twin.md", self.shared, str(self.outside / "z.md")]
        self.configure(start=[self.file_turn(p) for p in paths])
        chat_id = self.open_chat()
        for n, path in enumerate(paths, 1):
            self.assertTrue(self.send_with(chat_id, True, text=f"turn {n}")["ok"], path)
            self.wait_turn(chat_id, n)
        recs = self.tool_log(chat_id)
        self.assertEqual([r["kind"] for r in recs], ["denied"] * len(paths))
        self.assertEqual({r["by"] for r in recs}, {"vbear"})
        self.assertNotIn("card", self.kinds(chat_id))
        self.assertEqual(self.decisions(), ["decline"] * len(paths))
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_with_the_switch_off_the_same_path_is_refused_as_before(self):
        os.mkdir(self.shared, 0o700)
        self.configure(start=[self.file_turn(f"{self.shared}/price.md")])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        [rec] = self.tool_log(chat_id)
        self.assertEqual(rec["kind"], "denied")
        self.assertIn("以外", rec["reason"])

    def test_a_card_answered_after_the_folder_became_a_link_out_is_refused(self):
        os.mkdir(self.shared, 0o700)
        (Path(self.shared) / "sub").mkdir()
        chat_id = self.one(f"{self.shared}/sub/note.md")
        card = self.wait_card(chat_id)
        (Path(self.shared) / "sub").rmdir()
        os.symlink(self.outside, Path(self.shared) / "sub")
        r = self.answer(chat_id, card, "allow")
        self.assertEqual(r["error"]["code"], "refused", r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.decisions(), ["decline"])
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_the_work_folder_is_a_card_as_before(self):
        chat_id = self.one("note.txt")
        card = self.wait_card(chat_id)
        self.assertEqual(card["input"]["changes"][0]["path"], "note.txt")
        rec = next(r for r in self.events(chat_id)[0] if r["kind"] == "card")
        self.assertNotIn("共用資料夾", rec["reason"])
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_command_there_is_a_card_like_any_command(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(card["tool"], "command")
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.decisions(), ["decline"])


class SwitchChangeTests(SharedCodexCase):
    def test_switching_on_gives_a_new_process_with_the_root_and_the_old_idle_one_goes(self):
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], "restarting", r)
        self.assertEqual(self.kinds(chat_id).count("user_message"), 1, "the refused message wrote nothing")
        self.wait_gone(chat_id)
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 2)
        self.assertNotIn("writable_roots", " ".join(self.configs(0)))
        self.assertEqual(self.configs(1)[-1], ccp.shared_root_setting(self.shared))

    def test_switching_off_takes_the_root_away_from_the_next_message_on(self):
        self.configure(start=[0], resume=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id)["error"]["code"], "restarting")
        self.wait_gone(chat_id)
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 2)
        self.assertEqual(self.turn_policies(), [dict(ccp.SANDBOX_POLICY, writableRoots=[self.shared]), ccp.SANDBOX_POLICY])
        self.assertNotIn("writable_roots", " ".join(self.configs(1)))

    def test_the_same_setting_reuses_the_process(self):
        self.configure(start=[0, 0])
        chat_id = self.open_chat()
        self.assertEqual(self.send_with(chat_id, True)["result"]["process"], "new")
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.send_with(chat_id, True)["result"]["process"], "reused")
        self.wait_turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 1)

    def test_a_busy_process_is_left_alone_and_finishes_with_the_sandbox_it_had(self):
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(self.send_with(chat_id, True)["error"]["code"], "busy")
        self.assertTrue(self.answer(chat_id, card, "deny")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.turn_policies(), [ccp.SANDBOX_POLICY])


class FolderChecksTests(SharedCodexCase):
    def refused(self, code):
        self.configure(start=[0])
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
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_chat_with_it_off_is_not_stopped_by_a_full_folder(self):
        os.mkdir(self.shared, 0o700)
        for i in range(4):
            (Path(self.shared) / f"f{i}.md").write_text("x")
        self.configure(start=[0])
        chat_id = self.open_chat()
        with mock.patch.object(sr, "MAX_ENTRIES", 3):
            self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)

    def test_a_path_that_cannot_be_an_argument_is_refused(self):
        with mock.patch.object(sr, "MAX_BLOCK", 10):
            self.refused("shared_unsafe")


class NotCheckedTests(SharedCodexCase):
    checked = False

    def test_a_version_that_has_not_passed_the_check_with_the_folder_is_refused_before_anything_is_made(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], "shared_unverified", r)
        self.assertIn("0.163.0", r["error"]["message"])
        self.assertIn("共用資料夾", r["error"]["message"])
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertFalse(os.path.lexists(self.shared), "no folder was made")

    def test_off_the_same_version_chats_as_always(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.assertEqual(self.wait_turn(chat_id, 1)["reason"], "result")

    def test_the_checks_own_daemon_may_use_it_for_the_version_it_is_checking(self):
        self.dm.codex_chat_probe_versions = frozenset({VERSION})
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)

    def test_an_idle_process_of_a_checked_version_is_not_kept_for_an_unchecked_one(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        r = self.send_with(chat_id, True)
        self.assertEqual(r["error"]["code"], "shared_unverified", r)
        self.assertEqual(len(self.starts()), 1)


class NothingElseChangesTests(SharedCodexCase):
    def test_the_command_card_warning_text_is_the_one_of_v0_17_0(self):
        # ADR 0005 item 7: a command that is allowed may run outside the sandbox. The shared folder changes nothing of it.
        self.configure(start=[1])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_card(chat_id)
        rec = next(r for r in self.events(chat_id)[0] if r["kind"] == "card")
        self.assertEqual(rec["reason"], "每個指令都要你允許才會執行")

    def test_the_safe_fields_of_the_thread_do_not_change(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_with(chat_id, True)["ok"])
        self.wait_turn(chat_id, 1)
        params = self.thread_params()
        self.assertEqual({k: v for k, v in params.items() if k != "developerInstructions"},
                         {"cwd": self.work(), "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "workspace-write",
                          "ephemeral": False, "serviceName": "vbear"})
        turn = next(x for x in self.stdin() if x.get("method") == "turn/start")["params"]
        self.assertEqual(turn["approvalPolicy"], "untrusted")
        self.assertIs(turn["sandboxPolicy"]["networkAccess"], False)
        self.assertIs(turn["sandboxPolicy"]["excludeSlashTmp"], True)
        self.assert_nothing_dangerous_was_sent()


if __name__ == "__main__":
    unittest.main()
