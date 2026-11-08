"""P45-2: 復原這次套用 over a real loopback console with the real stores. First the preview (nothing is written), then the press (the server
works the list out again and deletes only what is in the person's list and can still be deleted), one test for every rule of the undo, in the
order routines, skills, employees. Every name and text here is made up."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tests import templates_apply_fixtures as fx
from vbear import agent_profiles as ap, routines, server, skillbook, templates_apply as ta
from vbear.api_error import ApiError

pick = fx.pick


class Undo(fx.ApplyBase):
    def setUp(self):
        super().setUp()
        self.apply_row = self.make_small()
        self.aid = self.apply_row["id"]
        self.copy = self.id_named("card", "商品文案")
        self.books = self.id_named("card", "會計")
        self.product = self.id_named("skill", "寫商品介紹")
        self.daybook = self.id_named("skill", "整理一天的帳")
        self.promo = self.id_named("routine", "想下週的促銷")
        self.spend = self.id_named("routine", "整理昨天的花費")
        self.everything = {self.copy, self.books, self.product, self.daybook, self.promo, self.spend}

    def preview(self):
        status, out = self.undo_preview(self.aid)
        self.assertEqual(status, 200, out)
        return out

    def deletes(self, out):
        return {d["id"] for d in out["delete"]}

    def keeps(self, out):
        return {k["id"]: k["why"] for k in out["keep"]}

    def remaining(self):
        return set(self.stored_cards()) | set(self.stored_skills()) | set(self.stored_routines())

    def chat_of(self, profile_id, chat_id="c-0123456789abcdef"):
        return self.put(f"chats/{chat_id}/chat.json", {"id": chat_id, "profile_id": profile_id})


class ThePreview(Undo):
    def test_what_nobody_changed_or_used_is_listed_to_be_deleted_with_names_and_nothing_is_written(self):
        before = fx.tree(self.state)
        out = self.preview()
        self.assertEqual(fx.tree(self.state), before, "the preview writes nothing")
        self.assertEqual(self.deletes(out), self.everything)
        self.assertEqual((out["keep"], out["gone"], out["unsure"]), ([], [], 0))
        self.assertEqual({d["name"] for d in out["delete"]}, {"商品文案", "會計", "寫商品介紹", "整理一天的帳", "想下週的促銷", "整理昨天的花費"})
        self.assertEqual([d["kind"] for d in out["delete"]], ["routine", "routine", "skill", "skill", "card", "card"], "routines, then skills, then employees")
        texts = [n["text"] for n in out["notes"]]
        self.assertIn(ta.TERMINAL_NOTE, texts, "VBear cannot see a terminal: the person is told, so that he decides")
        self.assertIn(ta.SKILL_NOTE, texts)
        self.assertEqual(texts.count(ta.INTERRUPTED_NOTE), 0)
        self.assert_no_ai_no_chat_no_ledger()
        self.assert_watched_unchanged()

    def test_the_terminal_note_is_only_there_when_an_employee_is_to_be_deleted(self):
        self.chat_of(self.copy)
        self.chat_of(self.books, "c-1123456789abcdef")
        out = self.preview()
        self.assertNotIn("card", {d["kind"] for d in out["delete"]})
        self.assertNotIn(ta.TERMINAL_NOTE, [n["text"] for n in out["notes"]])

    def test_the_words_of_a_reason_are_the_screens_and_each_kept_one_has_a_name(self):
        self.chat_of(self.copy)
        out = self.preview()
        (kept,) = [k for k in out["keep"] if k["id"] == self.copy]
        self.assertEqual((kept["why"], kept["text"], kept["name"]), ("chatted", ta.KEPT_TEXT[("card", "chatted")], "商品文案"))

    def test_an_unknown_apply_is_a_404_and_a_bad_path_too(self):
        self.assertEqual(self.undo_preview("ta-0123456789ab")[0], 404)
        self.assertEqual(self.call("/api/templates/applies/not-an-id/undo-preview", "POST", {})[0], 404)
        self.assertEqual(self.call(f"/api/templates/applies/{self.aid}/export", "POST", {})[0], 404)
        self.assertEqual(self.call(f"/api/templates/applies/{self.aid}/undo-preview")[0], 404, "a POST")

    def test_a_body_with_something_in_it_is_a_400(self):
        self.assertEqual(self.undo_preview(self.aid, {"delete": [self.copy]})[0], 400)
        self.assertEqual(self.call(f"/api/templates/applies/{self.aid}/undo-preview", "POST", raw=b"[1]")[0], 400)

    def test_the_marker_and_the_token_are_needed(self):
        self.assertEqual(self.undo_preview(self.aid, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.undo_preview(self.aid, headers={"Authorization": None})[0], 401)
        self.assertEqual(self.undo(self.aid, [self.copy], headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.remaining() >= self.everything, True)

    def test_an_apply_that_is_still_being_made_cannot_be_undone(self):
        pending = ta.begin_apply("claude")
        self.assertEqual(self.undo_preview(pending)[0], 409)
        self.assertEqual(self.undo(pending, [self.copy])[0], 409)


class TheRules(Undo):
    # -- employees ------------------------------------------------------------------------------------------------------

    def test_an_employee_whose_card_was_changed_stays(self):
        for change in ({"name": "改過的名字"}, {"enabled": False}, {"instructions": "我自己寫的指示"}, {"model": {"tool": "claude", "model_id": "opus"}}):
            with self.subTest(change):
                apply = self.make_small()
                card = self.ids_of(apply, "card")[0]
                ap.save_profile(card, change)
                status, out = self.undo_preview(apply["id"])
                self.assertEqual(status, 200, out)
                kept = next(k for k in out["keep"] if k["id"] == card)
                self.assertEqual((kept["why"], kept["text"]), ("changed", "你改過他的卡"))
                self.assertNotIn(card, self.deletes(out))

    def test_a_card_that_was_saved_again_with_nothing_changed_counts_as_changed(self):
        card = ap.get_profile_readonly(self.copy)
        ap.save_profile(self.copy, {"name": card["name"]})
        self.assertEqual(self.keeps(self.preview())[self.copy], "changed", "the time of the save is in the card")

    def test_a_chat_of_his_keeps_him(self):
        self.chat_of(self.copy)
        out = self.preview()
        self.assertEqual(self.keeps(out)[self.copy], "chatted")
        self.assertIn(self.books, self.deletes(out), "the other one is not kept by it")

    def test_his_work_folder_keeps_him(self):
        from vbear.runtime import chat_store
        os.makedirs(self.state / "chat-work" / chat_store.work_dir_name(self.copy))
        self.assertEqual(self.keeps(self.preview())[self.copy], "chatted")

    def test_a_group_a_dispatch_a_meeting_a_team_meeting_a_terminal_a_flow_or_a_task_keeps_him(self):
        places = ("groups/g-0123456789ab.json", "dispatch/d-0123456789ab.json", "chief/c.json", "meetings/m.json", "staffing/s.json",
                  "sessions/l-0123456789abcdef/manifest.json", "flows.json", "tasks.json")
        for relative in places:
            with self.subTest(relative):
                path = self.put(relative, {"somebody": self.copy})
                self.assertEqual(self.keeps(self.preview())[self.copy], "in_use")
                path.unlink()
        self.assertIn(self.copy, self.deletes(self.preview()))

    def test_a_switch_of_the_memory_or_the_shared_folder_that_was_ever_written_keeps_him(self):
        self.put("memory/memory.json", {"v": 1, "lines": [], "cards_off": [self.copy], "cards_on": []})
        self.assertEqual(self.keeps(self.preview())[self.copy], "switches")
        self.put("memory/memory.json", self.watched["memory/memory.json"].decode())
        self.put("shared-meta/state.json", {"cards_on": [self.books]})
        out = self.preview()
        self.assertEqual(self.keeps(out)[self.books], "switches")
        self.assertIn(self.copy, self.deletes(out))

    def test_a_routine_that_stays_keeps_the_employee_it_is_given_to_and_says_so(self):
        routines.edit(self.promo, {"text": "我自己改的內容"}, self.chats.cards())
        out = self.preview()
        self.assertEqual(self.keeps(out)[self.promo], "changed")
        self.assertEqual(self.keeps(out)[self.copy], "routine_kept")
        self.assertEqual(self.deletes(out), {self.books, self.daybook, self.product, self.spend})

    def test_a_routine_of_the_person_given_to_him_keeps_him_too(self):
        routines.create({"name": "我自己的例行工作", "profile_id": self.books, "text": "做事", "days": [0], "times": ["09:00"], "enabled": False}, self.chats.cards())
        self.assertEqual(self.keeps(self.preview())[self.books], "routine_kept")

    def test_what_cannot_be_read_keeps_him(self):
        target = self.state.parent / "elsewhere"
        target.mkdir()
        os.symlink(target, self.state / "groups")
        out = self.preview()
        self.assertEqual(self.keeps(out)[self.copy], "unreadable")
        self.assertEqual(self.keeps(out)[self.books], "unreadable")
        self.assertEqual(ta.KEPT_TEXT[("card", "unreadable")], "讀不到紀錄，先留著")
        self.assertEqual(self.deletes(out), {self.product, self.daybook, self.promo, self.spend}, "what does not depend on it is still listed")

    def test_the_cards_file_that_cannot_be_read_keeps_every_employee(self):
        (self.state / "agent_profiles.json").write_text("{not json", encoding="utf-8")
        out = self.preview()
        self.assertEqual({k["why"] for k in out["keep"] if k["kind"] == "card"}, {"unreadable"})

    # -- routines -------------------------------------------------------------------------------------------------------

    def test_a_routine_that_was_changed_or_switched_on_stays(self):
        routines.edit(self.spend, {"text": "我改過的內容"}, self.chats.cards())
        routines.edit(self.promo, {"enabled": True}, self.chats.cards())
        out = self.preview()
        self.assertEqual((self.keeps(out)[self.spend], self.keeps(out)[self.promo]), ("changed", "changed"))
        self.assertEqual(out["keep"][0]["text"], ta.KEPT_TEXT[("routine", "changed")])

    def test_a_routine_that_switched_on_and_off_again_counts_as_changed(self):
        routines.edit(self.spend, {"enabled": True}, self.chats.cards())
        routines.edit(self.spend, {"enabled": False}, self.chats.cards())
        self.assertEqual(self.keeps(self.preview())[self.spend], "changed")

    def test_any_run_a_reminder_or_a_miss_of_a_routine_keeps_it(self):
        for state in ("waiting", "missed", "skipped", "done", "dismissed"):
            with self.subTest(state):
                run = routines.new_run(self.spend, f"2026-11-09T09:0{len(state) % 9}", state=state, why="on_time", by=None)
                self.assertIsNotNone(run)
                out = self.preview()
                self.assertEqual(self.keeps(out)[self.spend], "ran")
                self.assertIn(self.promo, self.deletes(out))
                (self.state / "routines" / "runs.jsonl").unlink()

    def test_runs_that_cannot_be_read_keep_every_routine(self):
        (self.state / "routines" / "runs.jsonl").write_text("{not json\n", encoding="utf-8")
        out = self.preview()
        self.assertEqual({k["why"] for k in out["keep"] if k["kind"] == "routine"}, {"unreadable"})

    def test_the_routines_file_that_cannot_be_read_keeps_the_routines_and_the_employees(self):
        (self.state / "routines" / "routines.json").write_text("{not json", encoding="utf-8")
        out = self.preview()
        self.assertEqual({k["id"] for k in out["keep"]}, {self.promo, self.spend, self.copy, self.books})
        self.assertEqual(self.deletes(out), {self.product, self.daybook})

    # -- skills ---------------------------------------------------------------------------------------------------------

    def test_a_skill_that_was_changed_stays_and_nothing_else_is_said_of_it(self):
        skillbook.edit(self.product, {"text": "我改過的做法"})
        out = self.preview()
        self.assertEqual(self.keeps(out), {self.product: "changed"})
        self.assertEqual(out["keep"][0]["text"], "你改過")

    def test_the_skills_file_that_cannot_be_read_keeps_the_skills(self):
        (self.state / "skillbook" / "skills.json").write_text("{not json", encoding="utf-8")
        out = self.preview()
        self.assertEqual({k["why"] for k in out["keep"] if k["kind"] == "skill"}, {"unreadable"})

    # -- gone -----------------------------------------------------------------------------------------------------------

    def test_what_the_person_already_deleted_is_said_to_be_gone_and_not_asked_for(self):
        skillbook.delete(self.product)
        routines.delete(self.spend)
        ap.delete_profile(self.books)
        out = self.preview()
        self.assertEqual({g["id"] for g in out["gone"]}, {self.product, self.spend, self.books})
        self.assertEqual(self.deletes(out), {self.daybook, self.promo, self.copy})
        self.assertEqual(self.keeps(out), {})


class ThePress(Undo):
    def test_it_deletes_what_the_list_says_with_the_functions_of_the_deletes_in_the_order_routines_skills_employees(self):
        order = []
        for module, name, label in ((routines, "delete", "routine"), (skillbook, "delete", "skill"), (ap, "delete_profile", "card")):
            real = getattr(module, name)

            def wrap(*a, _real=real, _label=label, **k):
                order.append(_label)
                return _real(*a, **k)
            patcher = mock.patch.object(module, name, wrap)
            patcher.start()
            self.addCleanup(patcher.stop)
        pv = self.preview()
        status, out = self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual(status, 200, out)
        self.assertEqual(order, ["routine", "routine", "skill", "skill", "card", "card"])
        self.assertEqual({d["id"] for d in out["deleted"]}, self.everything)
        self.assertEqual((out["kept"], out["gone"]), ([], []))
        self.assertEqual((self.stored_cards(), self.stored_skills(), self.stored_routines()), ({}, {}, {}))
        row = ta.read_applies()[0]
        self.assertEqual({i["state"] for i in row["items"]}, {"deleted"})
        self.assertIsNotNone(row["undone_at"])
        self.assert_no_ai_no_chat_no_ledger()
        self.assert_watched_unchanged()

    def test_the_press_after_the_press_has_nothing_to_delete(self):
        pv = self.preview()
        self.undo(self.aid, [d["id"] for d in pv["delete"]])
        again = self.preview()
        self.assertEqual((again["delete"], again["keep"], again["gone"]), ([], [], []))
        status, out = self.undo(self.aid, [])
        self.assertEqual((status, out["deleted"]), (200, []))

    def test_only_what_is_in_the_list_is_deleted(self):
        status, out = self.undo(self.aid, [self.product])
        self.assertEqual(status, 200, out)
        self.assertEqual([d["id"] for d in out["deleted"]], [self.product])
        self.assertEqual(self.remaining(), self.everything - {self.product})

    def test_an_id_that_is_not_of_this_apply_is_a_400_and_nothing_is_deleted(self):
        other = skillbook.add({"name": "我自己的技能", "text": "我的做法"})["skill"]["id"]
        for bad in ([self.copy, other], [self.copy, "prof-zzzzzzzzzzzz"], [self.copy, "../x"], [self.copy, 5]):
            status, out = self.call(f"/api/templates/applies/{self.aid}/undo", "POST", {"delete": bad})
            self.assertEqual((status, out["code"]), (400, "bad_request"), bad)
        self.assertEqual(self.remaining(), self.everything | {other})

    def test_a_body_of_another_shape_is_a_400(self):
        for body in ({}, {"delete": "x"}, {"delete": [self.copy, self.copy]}, {"delete": [], "extra": 1}, {"delete": {self.copy: 1}}):
            status, out = self.call(f"/api/templates/applies/{self.aid}/undo", "POST", body)
            self.assertEqual((status, out["code"]), (400, "bad_request"), body)
        self.assertEqual(self.call(f"/api/templates/applies/{self.aid}/undo", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(self.remaining(), self.everything)

    def test_an_employee_who_chatted_after_the_preview_is_not_deleted(self):
        pv = self.preview()
        self.assertIn(self.copy, self.deletes(pv))
        self.chat_of(self.copy)
        status, out = self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual(status, 200, out)
        self.assertEqual({k["id"]: k["why"] for k in out["kept"]}, {self.copy: "chatted"})
        self.assertIn(self.copy, self.stored_cards())
        self.assertNotIn(self.books, self.stored_cards())
        self.assertEqual(out["kept"][0]["name"], "商品文案")

    def test_a_skill_or_a_routine_changed_after_the_preview_is_not_deleted(self):
        pv = self.preview()
        skillbook.edit(self.daybook, {"text": "之後才改的"})
        routines.edit(self.spend, {"enabled": True}, self.chats.cards())
        status, out = self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual({k["id"]: k["why"] for k in out["kept"]}, {self.daybook: "changed", self.spend: "changed", self.books: "routine_kept"})
        self.assertEqual(self.remaining(), {self.daybook, self.spend, self.books})

    def test_what_is_gone_by_the_time_of_the_press_is_not_an_error(self):
        pv = self.preview()
        skillbook.delete(self.product)
        status, out = self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual(status, 200, out)
        self.assertEqual([g["id"] for g in out["gone"]], [self.product])
        self.assertEqual(self.remaining(), set())

    def test_a_second_press_deals_with_what_is_left_by_the_same_rules(self):
        path = self.chat_of(self.copy)
        pv = self.preview()
        self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual(self.remaining(), {self.copy})
        again = self.preview()
        self.assertEqual((again["delete"], [(k["id"], k["why"]) for k in again["keep"]]), ([], [(self.copy, "chatted")]))
        path.unlink()
        os.rmdir(path.parent)
        last = self.preview()
        self.assertEqual(self.deletes(last), {self.copy})
        status, out = self.undo(self.aid, [self.copy])
        self.assertEqual((status, [d["id"] for d in out["deleted"]]), (200, [self.copy]))
        self.assertEqual(self.remaining(), set())

    def test_if_a_delete_fails_it_stops_there_and_what_was_deleted_is_recorded(self):
        pv = self.preview()
        with mock.patch.object(server.skillbook_mod, "delete", side_effect=ApiError(503, "skills_unreadable", "x")):
            status, out = self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual((status, out["code"]), (503, "skills_unreadable"), out)
        self.assertEqual(self.remaining(), {self.product, self.daybook, self.copy, self.books}, "the routines went, nothing after the failing one was tried")
        row = ta.read_applies()[0]
        self.assertEqual({i["id"] for i in row["items"] if i["state"] == "deleted"}, {self.promo, self.spend})
        pv = self.preview()
        status, out = self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual(status, 200, out)
        self.assertEqual(self.remaining(), set())

    def test_it_never_touches_a_chat_a_group_the_memory_or_the_configuration(self):
        group = self.put("groups/g-0123456789ab.json", {"members": ["prof-zzzzzzzzzzzz"]})
        chat = self.put("chats/c-0123456789abcdef/chat.json", {"profile_id": "prof-zzzzzzzzzzzz"})
        snapshot = (group.read_bytes(), chat.read_bytes())
        pv = self.preview()
        self.undo(self.aid, [d["id"] for d in pv["delete"]])
        self.assertEqual((group.read_bytes(), chat.read_bytes()), snapshot)
        self.assert_watched_unchanged()
        self.assert_no_ai_no_chat_no_ledger()

    def test_the_record_and_the_log_still_have_no_name_after_an_undo(self):
        pv = self.preview()
        self.undo(self.aid, [d["id"] for d in pv["delete"]])
        raw = (self.state / "templates" / "applies.json").read_text(encoding="utf-8") + (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8")
        for word in ("商品文案", "會計", "寫商品介紹", "整理一天的帳", "想下週的促銷", "整理昨天的花費", "你是這家小店"):
            self.assertNotIn(word, raw)
        lines = [json.loads(x) for x in (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([l["what"] for l in lines], ["applied", "undo"])
        self.assertEqual(lines[1]["counts"], {"cards": 2, "skills": 2, "routines": 2})

    def test_an_apply_older_than_the_last_fifty_is_not_found_and_its_things_are_left(self):
        for _ in range(50):
            ta.end_apply(ta.begin_apply("claude"), "done")
        self.assertEqual(self.undo_preview(self.aid)[0], 404)
        self.assertEqual(self.remaining(), self.everything, "what it made is left where it is")

    def test_the_list_says_what_can_still_be_undone(self):
        row = self.applies()[0]
        self.assertEqual(row["left"], {"cards": 2, "skills": 2, "routines": 2})
        pv = self.preview()
        self.undo(self.aid, [d["id"] for d in pv["delete"]])
        row = self.applies()[0]
        self.assertEqual((row["left"], row["counts"]), ({"cards": 0, "skills": 0, "routines": 0}, {"cards": 2, "skills": 2, "routines": 2}))
        self.assertIsNotNone(row["undone_at"])


class TheTerminalLeavesNoCardIdBehind(unittest.TestCase):
    """What P45-2 was asked to find out: a card that the person started in a terminal (safe mode, the only one the team templates make) leaves
    no id of the card under ``<state>/sessions/``, so VBear cannot see that an employee was used there, and the undo preview says so (the note
    ``terminal`` of ``templates_apply.TERMINAL_NOTE``). If a later version starts to record the card in the launch, these tests fail, and the note
    can go."""

    def test_the_launch_that_makes_the_manifest_is_given_no_card(self):
        import inspect
        from vbear.runtime import agent_sessions
        for fn in (agent_sessions.prepare_claude_launch, agent_sessions.prepare_codex_launch):
            names = list(inspect.signature(fn).parameters)
            self.assertEqual([n for n in names if "profile" in n or "card" in n or "employee" in n], [], fn.__name__)

    def test_the_spec_the_console_hands_the_runtime_has_no_card_in_it(self):
        import ast
        from pathlib import Path
        source = (Path(server.__file__).parent / "agent_launch.py").read_text(encoding="utf-8")
        specs = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "cwd" for k in n.keys)]
        self.assertTrue(specs, "the spec is there to be read")
        for node in specs:
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            self.assertFalse(keys & {"profile_id", "profile", "card_id"}, keys)

    def test_a_manifest_of_a_launch_is_a_closed_list_of_keys_without_a_card(self):
        import re
        from pathlib import Path
        from vbear.runtime import agent_sessions
        source = Path(agent_sessions.__file__).read_text(encoding="utf-8")
        start = source.index("def _prepare_claude(")
        body = source[start:source.index("\ndef ", start + 10)]
        keys = set(re.findall(r'^\s{12}"([a-z_]+)":', body, re.M))
        self.assertIn("launch_id", keys)
        self.assertFalse(keys & {"profile_id", "profile", "card_id", "profile_digest"}, "a card's id is only ever in what the chat launches add as extra")


if __name__ == "__main__":
    unittest.main()
