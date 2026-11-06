"""P40-3: 「自己動手」 on a proposal as it arrives (the four combinations of ADR 0006 point 4), what a person may do with a dispatch
(dismiss, withdraw an employee, delete) and 「AI 自己做了什麼」. Same seams as tests/test_dispatch.py; no CLI runs."""
from __future__ import annotations

import json
import unittest
from decimal import Decimal

from tests.test_dispatch import Base, old_hands_plan, plan
from vbear import agent_profiles as ap, chief, config as cfg, dispatch, tasks


def with_note(answer: dict) -> dict:
    """A proposal that has a note: one step points at a card that is not on the list, so VBear takes it out and says so."""
    answer["steps"] = answer["steps"] + [{"who": "C7", "text": "不存在的員工"}]
    return answer


class TheFourCombinations(Base):
    def made_cards(self, did):
        return dispatch.load(did)["made"]

    def test_neither_ticked_the_proposal_waits_for_the_person(self):
        self.autonomy_on(False, False)
        before = self.profile_ids()
        did = self.propose()
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["made"], rec["task_id"]), ("proposed", {}, None))
        self.assertEqual(self.events(did), [("proposed", "vbear")])
        self.assertEqual((self.profile_ids(), tasks.list_tasks()), (before, []))

    def test_only_item_1_makes_the_new_employees_and_still_waits_for_the_person(self):
        self.autonomy_on(True, False)
        did = self.propose()
        rec = dispatch.load(did)
        self.assertEqual(rec["state"], "proposed")
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("card_intent", "auto1"), ("card_created", "auto1")])
        (new_id,) = rec["made"].values()
        card = ap.get_profile_readonly(new_id)
        self.assertEqual((card["launch_mode"], card["equipped_skill_ids"]), ("safe", []))
        self.assertIsNone(rec["task_id"])
        # the person confirms: the employee that is there is used, not made a second time
        before = self.profile_ids()
        self.dispatcher.confirm(did, self.body_of(did))
        self.assertEqual(self.profile_ids(), before)
        rec = dispatch.load(did)
        self.assertEqual(rec["steps"][1]["profile_id"], new_id)
        self.assertEqual([k for k, _ in self.events(did)].count("card_created"), 1)
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("card_intent", "auto1"), ("card_created", "auto1"),
                                             ("confirmed", "you"), ("task_intent", "you"), ("task_created", "you")])

    def test_item_1_alone_with_nobody_new_makes_nothing(self):
        self.autonomy_on(True, False)
        did = self.propose(old_hands_plan())
        self.assertEqual((self.events(did), dispatch.load(did)["made"]), ([("proposed", "vbear")], {}))

    def test_only_item_2_starts_a_proposal_that_needs_nobody_new(self):
        self.autonomy_on(False, True)
        before = self.profile_ids()
        did = self.propose(old_hands_plan())
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["started_by"]), ("running", "auto2"))
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("confirmed", "auto2"), ("task_intent", "auto2"), ("task_created", "auto2")])
        self.assertEqual(self.profile_ids(), before)
        self.assertIsNotNone(tasks.get_task(rec["task_id"]))

    def test_only_item_2_does_not_start_a_proposal_that_needs_a_new_employee(self):
        self.autonomy_on(False, True)
        did = self.propose()
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["made"], rec["task_id"]), ("proposed", {}, None))

    def test_both_ticked_make_the_employees_then_start(self):
        self.autonomy_on(True, True)
        did = self.propose()
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["started_by"]), ("running", "auto2"))
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("card_intent", "auto1"), ("card_created", "auto1"), ("confirmed", "auto2"),
                                             ("task_intent", "auto2"), ("task_created", "auto2")])
        (new_id,) = rec["made"].values()
        self.assertEqual(rec["steps"][1]["profile_id"], new_id)
        self.assertEqual(rec["events"][3]["edited"], False)

    def test_a_note_keeps_item_2_from_starting_but_item_1_still_makes_the_employees(self):
        self.autonomy_on(True, True)
        did = self.propose(with_note(plan()))
        rec = dispatch.load(did)
        self.assertTrue(rec["notes"])
        self.assertEqual(rec["state"], "proposed")
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("card_intent", "auto1"), ("card_created", "auto1")])
        self.assertIsNone(rec["task_id"])

    def test_a_note_keeps_item_2_alone_from_starting(self):
        self.autonomy_on(False, True)
        did = self.propose(with_note(old_hands_plan()))
        self.assertEqual((dispatch.load(did)["state"], self.events(did)), ("proposed", [("proposed", "vbear")]))

    def test_a_question_keeps_item_2_from_starting(self):
        self.autonomy_on(True, True)
        did = self.propose(old_hands_plan(questions=["要賣多少錢？"]))
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["questions"], rec["task_id"]), ("proposed", ["要賣多少錢？"], None))

    def test_a_proposal_with_only_questions_never_starts(self):
        self.autonomy_on(True, True)
        did = self.propose(plan(steps=[], team=[], new_cards=[], questions=["預算多少？"]))
        self.assertEqual((dispatch.load(did)["state"], self.events(did)), ("proposed", [("proposed", "vbear")]))

    def test_a_card_that_cannot_be_made_pauses_instead_of_starting(self):
        from unittest import mock
        self.autonomy_on(True, True)
        with mock.patch.object(ap, "save_profile", side_effect=ValueError("角色卡已達上限 500 筆")):
            did = self.propose()
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["pause"]["reason"], rec["task_id"]), ("paused", "create_failed", None))

    def test_a_config_that_is_not_readable_as_ticks_means_neither(self):
        conf_path = cfg.state_dir() / "config.json"
        conf_path.write_text(json.dumps({"autonomy": {"create_cards": "yes", "dispatch": 1}}))
        conf_path.chmod(0o600)
        did = self.propose(old_hands_plan())
        self.assertEqual(dispatch.load(did)["state"], "proposed")

    def test_config_json_is_not_touched_by_a_whole_dispatch_with_both_ticked(self):
        self.autonomy_on(True, True)
        before = self.config_bytes()
        did = self.propose()
        self.assertEqual(dispatch.load(did)["state"], "running")
        for pid in list(dispatch.load(did)["made"].values()):
            self.dispatcher.withdraw_card(did, {"profile_id": pid})
        self.assertEqual(self.config_bytes(), before)
        self.assertNotEqual(before, None)


class WhatAPersonMayDo(Base):
    def test_dismissing_ends_the_proposal_and_makes_nothing(self):
        did = self.propose()
        before = (self.profile_ids(), tasks.list_tasks())
        view = self.dispatcher.dismiss(did)
        self.assertEqual(view["state"], "dismissed")
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("dismissed", "you")])
        self.assertEqual((self.profile_ids(), tasks.list_tasks()), before)
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.dismiss(did)
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "not_proposed"))
        with self.assertRaises(dispatch.DispatchError):
            self.dispatcher.confirm(did, self.body_of(did))

    def test_a_running_dispatch_cannot_be_dismissed(self):
        did = self.propose(old_hands_plan())
        self.dispatcher.confirm(did, self.body_of(did))
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.dismiss(did)
        self.assertEqual(cm.exception.code, "not_proposed")

    def confirmed(self):
        did = self.propose()
        self.dispatcher.confirm(did, self.body_of(did))
        (pid,) = dispatch.load(did)["made"].values()
        return did, pid

    def test_withdrawing_switches_the_employee_off_and_keeps_it(self):
        did, pid = self.confirmed()
        view = self.dispatcher.withdraw_card(did, {"profile_id": pid})
        card = ap.get_profile_readonly(pid)
        self.assertIs(card["enabled"], False)
        self.assertEqual((card["name"], card["launch_mode"], card["equipped_skill_ids"]), ("會計師", "safe", []), "only switched off")
        self.assertEqual(self.events(did)[-1], ("card_withdrawn", "you"))
        self.assertEqual([(c["profile_id"], c["withdrawn"]) for c in view["created_cards"]], [(pid, True)])
        self.assertEqual(view["can"]["withdraw"], [])
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.withdraw_card(did, {"profile_id": pid})
        self.assertEqual(cm.exception.code, "already_withdrawn")

    def test_withdrawing_is_refused_for_an_employee_this_dispatch_did_not_make(self):
        did, pid = self.confirmed()
        for other in (self.writer, self.ceo, "prof-000000000000", 5, None):
            with self.assertRaises(dispatch.DispatchError) as cm:
                self.dispatcher.withdraw_card(did, {"profile_id": other})
            self.assertEqual(cm.exception.status, 400, other)
        self.assertIs(ap.get_profile_readonly(self.writer)["enabled"], True)
        with self.assertRaises(dispatch.DispatchError):
            self.dispatcher.withdraw_card(did, {"profile_id": pid, "x": 1})

    def test_withdrawing_is_refused_while_a_turn_of_that_employee_is_running(self):
        did, pid = self.confirmed()
        chat_id = "c-0123456789abcdef"

        def sent(rec):
            step = rec["steps"][1]
            step["chat_id"], step["state"], step["turn"] = chat_id, "running", 1
        self.dispatcher._mutate(did, sent)
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.withdraw_card(did, {"profile_id": pid})
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "turn_running"))
        self.assertIs(ap.get_profile_readonly(pid)["enabled"], True)

    def test_withdrawing_is_refused_when_the_chat_is_busy_or_cannot_be_asked(self):
        did, pid = self.confirmed()
        chat_id = "c-0123456789abcdef"

        def sent(rec):
            step = rec["steps"][1]
            step["chat_id"], step["state"], step["turn"] = chat_id, "ended", 1
        self.dispatcher._mutate(did, sent)
        self.busy_chats.add(chat_id)
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.withdraw_card(did, {"profile_id": pid})
        self.assertEqual(cm.exception.code, "turn_running")
        self.busy_chats.clear()
        self.dispatcher.busy = lambda c: (_ for _ in ()).throw(RuntimeError("daemon gone"))
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.withdraw_card(did, {"profile_id": pid})
        self.assertEqual(cm.exception.code, "turn_running", "a turn that cannot be ruled out is a turn")
        self.dispatcher.busy = lambda c: False
        self.dispatcher.withdraw_card(did, {"profile_id": pid})
        self.assertIs(ap.get_profile_readonly(pid)["enabled"], False)

    def test_deleting_a_proposed_dispatch_removes_it_and_its_proposal_only(self):
        did = self.propose()
        chief_id = dispatch.load(did)["chief_id"]
        before = (self.profile_ids(), tasks.list_tasks())
        self.dispatcher.delete(did)
        self.assertEqual((dispatch.record_ids(), chief.record_ids()), ([], []))
        self.assertEqual((self.profile_ids(), tasks.list_tasks()), before)
        self.assertNotIn(chief_id, chief.record_ids())

    def test_deleting_keeps_what_a_confirmed_dispatch_made(self):
        did, pid = self.confirmed()
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.delete(did)                              # running
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "not_deletable"))
        self.dispatcher._mutate(did, lambda r: r.update(state="stopped"))
        task_id = dispatch.load(did)["task_id"]
        self.dispatcher.delete(did)
        self.assertEqual(dispatch.record_ids(), [])
        self.assertIsNotNone(ap.get_profile_readonly(pid))
        self.assertIsNotNone(tasks.get_task(task_id))

    def test_a_dispatch_paused_before_anything_was_sent_can_be_deleted(self):
        did, pid = self.confirmed()
        self.dispatcher._pause(did, "uncertain")
        self.assertTrue(self.dispatcher.get(did)["can"]["delete"])
        self.dispatcher._mutate(did, lambda r: r["steps"][0].update(state="ended"))
        self.assertFalse(self.dispatcher.get(did)["can"]["delete"])

    def test_stop_and_continue_say_there_is_no_runner_yet(self):
        did, pid = self.confirmed()
        for call in (self.dispatcher.stop, self.dispatcher.resume):
            with self.assertRaises(dispatch.DispatchError) as cm:
                call(did)
            self.assertEqual((cm.exception.status, cm.exception.code), (409, "no_runner"))
            self.assertIn("runner", str(cm.exception))
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.stop("d-ffffffffffff")
        self.assertEqual(cm.exception.status, 404)

    def test_the_list_says_each_dispatch_in_a_row(self):
        a = self.propose()
        b = self.propose(old_hands_plan())
        rows = self.dispatcher.list()["dispatch"]
        self.assertEqual({r["id"] for r in rows}, {a, b})
        row = next(r for r in rows if r["id"] == a)
        self.assertEqual((row["state"], row["title"], row["steps"]), ("proposed", "週末市集攤位", 2))


class ActionsTests(Base):
    def test_every_event_is_listed_with_who_decided_newest_first(self):
        self.autonomy_on(True, True)
        auto = self.propose()
        self.autonomy_on(False, False)
        mine = self.propose()
        self.dispatcher.confirm(mine, self.body_of(mine))
        (pid,) = dispatch.load(mine)["made"].values()
        self.dispatcher.withdraw_card(mine, {"profile_id": pid})
        got = self.dispatcher.actions()
        rows = got["actions"]
        self.assertEqual(got["unreadable"], 0)
        ats = [r["at"] for r in rows]
        self.assertEqual(ats, sorted(ats, reverse=True))
        pairs = lambda did: [(r["kind"], r["by"]) for r in reversed(rows) if r["dispatch_id"] == did]
        self.assertEqual(pairs(auto), [("proposed", "vbear"), ("card_intent", "auto1"), ("card_created", "auto1"), ("confirmed", "auto2"),
                                       ("task_intent", "auto2"), ("task_created", "auto2")])
        self.assertEqual(pairs(mine), [("proposed", "vbear"), ("confirmed", "you"), ("card_intent", "you"), ("card_created", "you"),
                                       ("task_intent", "you"), ("task_created", "you"), ("card_withdrawn", "you")])
        by_text = {r["by"]: r["by_text"] for r in rows}
        self.assertEqual(by_text, {"vbear": "VBear", "auto1": "自己動手第 1 項", "auto2": "自己動手第 2 項", "you": "你確認的"})

    def test_the_words_name_the_employee_and_can_stop_and_can_withdraw_say_what_is_possible(self):
        did = self.propose()
        self.dispatcher.confirm(did, self.body_of(did))
        rows = {r["kind"]: r for r in self.dispatcher.actions()["actions"] if r["dispatch_id"] == did}
        self.assertIn("會計師", rows["card_created"]["what"])
        self.assertTrue(rows["card_created"]["can_withdraw"])
        self.assertTrue(rows["confirmed"]["can_stop"], "it is running")
        self.assertFalse(rows["proposed"]["can_stop"] or rows["proposed"]["can_withdraw"])
        (pid,) = dispatch.load(did)["made"].values()
        self.dispatcher.withdraw_card(did, {"profile_id": pid})
        rows = {r["kind"]: r for r in self.dispatcher.actions()["actions"]}
        self.assertFalse(rows["card_created"]["can_withdraw"], "already withdrawn")
        self.assertIn("撤回", rows["card_withdrawn"]["what"])
        self.assertIn("停用", rows["card_withdrawn"]["what"])
        text = json.dumps(self.dispatcher.actions(), ensure_ascii=False)
        for word in ("預算", "先問你", self.ceo):
            self.assertNotIn(word, text, "nothing of the conversation")

    def test_an_intent_with_no_result_is_said_as_unsure(self):
        did = self.propose()

        class Killed(BaseException):
            pass
        from unittest import mock
        with mock.patch.object(ap, "save_profile", side_effect=Killed()):
            with self.assertRaises(Killed):
                self.dispatcher.confirm(did, self.body_of(did))
        self.dispatcher.recover_all()
        what = [r["what"] for r in self.dispatcher.actions()["actions"] if r["kind"] == "card_intent"]
        self.assertEqual(len(what), 1)
        self.assertIn("不確定", what[0])
        self.assertTrue(any(r["kind"] == "paused" and "員工頁" in r["what"] for r in self.dispatcher.actions()["actions"]))

    def test_the_most_listed_is_the_limit_and_a_damaged_record_is_counted_not_guessed(self):
        self.propose()
        self.propose(old_hands_plan())
        self.assertEqual(len(self.dispatcher.actions(limit=1)["actions"]), 1)
        bad = dispatch.folder() / "d-aaaaaaaaaaaa.json"
        bad.write_text("not json")
        bad.chmod(0o600)
        got = self.dispatcher.actions()
        self.assertEqual(got["unreadable"], 1)
        self.assertEqual(len(got["actions"]), 2)
        self.assertEqual(self.dispatcher.list()["dispatch"][-1]["blocked"], True)

    def test_a_dispatch_that_is_not_ours_in_the_folder_blocks_only_itself(self):
        did = self.propose()
        bad = dispatch.folder() / "d-bbbbbbbbbbbb.json"
        bad.write_text(json.dumps({"id": "d-bbbbbbbbbbbb"}))
        bad.chmod(0o600)
        with self.assertRaises(dispatch.DispatchError) as cm:
            dispatch.load("d-bbbbbbbbbbbb")
        self.assertEqual(cm.exception.code, "storage")
        self.assertEqual(self.dispatcher.get(did)["state"], "proposed")


class PauseWords(unittest.TestCase):
    def test_each_reason_has_words_and_an_unknown_time_is_said_unknown(self):
        self.assertEqual(dispatch.pause_text("daily_limit", limit="3", n=2),
                         "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；到時候按「繼續」接著做第 2 步。")
        self.assertIn("US$未知", dispatch.pause_text("daily_limit"))
        self.assertEqual(dispatch.pause_text("plan_limit", tool="Codex", when="三小時後恢復"), "Codex 的方案用量到了上限，三小時後恢復。")
        self.assertIn("恢復時間未知", dispatch.pause_text("plan_limit"))
        for reason in ("busy", "limit", "restarting", "uncertain", "interrupted", "create_failed"):
            self.assertTrue(dispatch.PAUSE_TEXT[reason])
        self.assertIn("員工頁", dispatch.pause_text("uncertain"))
        self.assertIn("weird_code", dispatch.pause_text("weird_code"))
        self.assertIn("沒有這個代碼的說明", dispatch.pause_text("weird_code"))


if __name__ == "__main__":
    unittest.main()
