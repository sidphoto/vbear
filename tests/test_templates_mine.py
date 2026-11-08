"""P45-3: the person's own team templates (vbear/templates_mine.py): ``<state>/templates/mine.json``, saving a copy from what the person has now
or from ticked items of other templates, renaming, deleting. Every test uses a temporary home (HOME and VBEAR_HOME), nothing here starts a
program, and every name and word is made up. The real write functions of the cards, the skills and the routines make the 'now' in the tests."""

from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import agent_profiles as ap, config as cfg, routines, skillbook, templates as tp, templates_builtin as tb, templates_mine as tm
from vbear.api_error import ApiError

SHOP, CREATOR, STUDIO, LIFE = tb.builtin()


def ref(template, key):
    return {"template": template, "key": key}


def pick(template, key):
    return {"from": ref(template, key)}


class Home(unittest.TestCase):
    """A temporary home, and helpers that make cards, skills and routines through the ordinary write functions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbtm-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name)) / "h"
        (self.home / ".vbear").mkdir(parents=True, mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "VBEAR_HOME": str(self.home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        for target in (mock.patch("subprocess.run", side_effect=AssertionError("a program was started")),
                       mock.patch("subprocess.Popen", side_effect=AssertionError("a program was started"))):
            target.start()
            self.addCleanup(target.stop)
        self.state = cfg.state_dir()

    # what the person has
    def card(self, name="虛構會計", **over):
        body = {"name": name, "position": "accountant", "instructions": "你是虛構的會計，只整理數字。", "launch_mode": "safe",
                "model": {"tool": "claude", "model_id": "haiku"}, "permission_intents": dict(ap.VERIFIED_INTENTS)}
        body.update(over)
        return ap.save_profile(None, body)

    def skill(self, name="虛構技能", text="請幫我整理這份虛構的清單。", confirm=False):
        return skillbook.add({"name": name, "text": text, "confirm_warning": confirm})["skill"]

    def loose_skill(self, name, text):
        """A skill the skill book would not take (a key in it): handed to the save as if it were stored, so the save's own check is what is tested."""
        return {"id": "k-" + "0" * 12, "name": name, "text": text, "source": {"how": "typed"}, "created_at": 1.0, "updated_at": 1.0}

    def routine(self, profile_id, name="虛構例行", text="請整理虛構的待辦。", days=(0, 2), times=("09:00",), enabled=False):
        body = {"name": name, "profile_id": profile_id, "text": text, "days": list(days), "times": list(times), "enabled": enabled}
        return routines.create(body, [{"id": profile_id, "can_chat": True}])["routine"]

    def now(self):
        return {"cards": list(ap.load_all(None, None, mark_corrupt=False).values()), "skills": skillbook.view()["skills"],
                "routines": routines.read_routines()[0]}

    def save(self, body, **over):
        now = self.now()
        now.update(over)
        return tm.save_mine(body, **now)

    def mine_file(self):
        return json.loads((self.state / "templates" / "mine.json").read_text(encoding="utf-8"))

    def mine(self):
        return self.mine_file()["templates"]

    def assertApi(self, status, code, fn, *args, **kw):
        with self.assertRaises(ApiError) as caught:
            fn(*args, **kw)
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code), str(caught.exception))
        return caught.exception


class Reading(Home):
    def test_nothing_saved_reads_as_none_and_looking_creates_nothing(self):
        before = sorted(p.name for p in self.state.rglob("*"))
        self.assertEqual(tm.read_mine(), ([], True, None))
        self.assertEqual(sorted(p.name for p in self.state.rglob("*")), before)
        self.assertFalse((self.state / "templates").exists())


class SavingWhatThePersonHas(Home):
    def test_an_employee_is_saved_as_a_name_a_position_the_persons_own_words_and_the_claude_alias_only(self):
        a = self.card("虛構會計")
        out = self.save({"name": "我的店", "cards": [{"profile_id": a["id"]}]})
        t = out["template"]
        self.assertRegex(t["id"], r"^tm-[0-9a-f]{12}$")
        self.assertEqual((t["name"], t["builtin"]), ("我的店", False))
        self.assertEqual(len(t["cards"]), 1)
        self.assertEqual(t["cards"][0], {"key": t["cards"][0]["key"], "name": "虛構會計", "position": "accountant",
                                         "instructions": "你是虛構的會計，只整理數字。", "claude_model": "haiku"})
        self.assertEqual(set(t["cards"][0]), set(tp.CARD_KEYS))
        self.assertIsNone(tp.template_problem(t, builtin=False))
        self.assertEqual(self.mine(), [t], "what was answered is what was kept")

    def test_nothing_of_the_card_but_those_five_things_reaches_the_file(self):
        a = self.card("虛構甲", launch_mode="full", model={"tool": "claude", "model_id": "opus"}, enabled=False)
        self.save({"name": "只有字", "cards": [{"profile_id": a["id"]}]})
        raw = (self.state / "templates" / "mine.json").read_text(encoding="utf-8")
        for word in ("launch_mode", "equipped_skill_ids", "permission_intents", "profession_role_id", "enabled", "tool", "model_id", "memory",
                     "shared", "chat", "created_at", "updated_at", a["id"], "prof-"):
            self.assertNotIn(word, raw, word)

    def test_a_full_mode_card_is_saved_without_a_mode_and_the_answer_says_it_will_be_safe(self):
        a = self.card("虛構完整", launch_mode="full")
        out = self.save({"name": "從舊模式來的", "cards": [{"profile_id": a["id"]}]})
        self.assertEqual(set(out["template"]["cards"][0]), set(tp.CARD_KEYS))
        notes = [n for n in out["notes"] if n["code"] == "full_mode_saved_safe"]
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["kind"], notes[0]["index"]), ("cards", 0))
        self.assertIn("安全模式", notes[0]["text"])
        self.assertNotIn("虛構完整", json.dumps(out["notes"], ensure_ascii=False), "a note holds no name")

    def test_a_card_saved_from_full_mode_is_made_safe_when_applied(self):
        a = self.card("虛構完整", launch_mode="full")
        t = self.save({"name": "從舊模式來的", "cards": [{"profile_id": a["id"]}]})["template"]
        planned = tp.plan({"tool": "claude", "cards": [pick(t["id"], t["cards"][0]["key"])]}, templates=tp.index([t]),
                          current={"cards": [], "skills": 0, "routines": 0})
        self.assertEqual(planned["cards"][0]["body"]["launch_mode"], "safe")
        self.assertEqual(planned["cards"][0]["body"]["equipped_skill_ids"], [])

    def test_a_card_that_uses_the_position_text_carries_no_instructions(self):
        a = self.card("虛構預設", instructions=None)
        t = self.save({"name": "預設字", "cards": [{"profile_id": a["id"]}]})["template"]
        self.assertIsNone(t["cards"][0]["instructions"])

    def test_a_full_model_name_or_another_tools_model_is_not_carried(self):
        a = self.card("虛構全名", model={"tool": "claude", "model_id": "claude-opus-4-1"})
        b = self.card("虛構另一家", model={"tool": "codex", "model_id": "gpt-5-codex"})
        c = self.card("虛構沒指定", model={"tool": "claude", "model_id": ""})
        t = self.save({"name": "模型", "cards": [{"profile_id": a["id"]}, {"profile_id": b["id"]}, {"profile_id": c["id"]}]})["template"]
        self.assertEqual([x["claude_model"] for x in t["cards"]], [None, None, None])

    def test_a_position_this_build_does_not_list_is_not_carried(self):
        a = self.card("虛構無職", position=None)
        t = self.save({"name": "無職位", "cards": [{"profile_id": a["id"]}]})["template"]
        self.assertIsNone(t["cards"][0]["position"])

    def test_a_skill_is_a_name_and_the_words_with_no_source_and_no_id(self):
        s = self.skill()
        t = self.save({"name": "技能而已", "skills": [{"skill_id": s["id"]}]})["template"]
        self.assertEqual(t["skills"], [{"key": t["skills"][0]["key"], "name": "虛構技能", "text": "請幫我整理這份虛構的清單。"}])
        raw = (self.state / "templates" / "mine.json").read_text(encoding="utf-8")
        self.assertNotIn("source", raw)
        self.assertNotIn(s["id"], raw)

    def test_a_routine_goes_to_the_card_saved_with_it_and_comes_out_switched_off(self):
        a = self.card("虛構會計")
        r = self.routine(a["id"], enabled=True)
        t = self.save({"name": "一組", "cards": [{"profile_id": a["id"]}], "routines": [{"routine_id": r["id"]}]})["template"]
        self.assertEqual(t["routines"][0], {"key": t["routines"][0]["key"], "name": "虛構例行", "text": "請整理虛構的待辦。", "days": [0, 2],
                                            "times": ["09:00"], "who": t["cards"][0]["key"]})
        self.assertNotIn("enabled", t["routines"][0])
        planned = tp.plan({"tool": "claude", "cards": [pick(t["id"], t["cards"][0]["key"])], "routines": [pick(t["id"], t["routines"][0]["key"])]},
                          templates=tp.index([t]), current={"cards": [], "skills": 0, "routines": 0})
        self.assertTrue(planned["ok"], planned["problems"])
        self.assertIs(tp.routine_body(planned["routines"][0]["routine"], "p-new")["enabled"], False)

    def test_a_routine_whose_employee_was_not_saved_has_nobody_and_the_answer_says_to_choose(self):
        a = self.card("虛構會計")
        r = self.routine(a["id"])
        out = self.save({"name": "沒有人", "routines": [{"routine_id": r["id"]}]})
        self.assertIsNone(out["template"]["routines"][0]["who"])
        self.assertIn("routine_no_assignee", [n["code"] for n in out["notes"]])
        planned = tp.plan({"tool": "claude", "routines": [pick(out["template"]["id"], out["template"]["routines"][0]["key"])]},
                          templates=tp.index([out["template"]]), current={"cards": [], "skills": 0, "routines": 0})
        self.assertIn("no_assignee", [p["code"] for p in planned["problems"]])

    def test_it_is_a_copy_of_this_moment(self):
        s = self.skill()
        t = self.save({"name": "複本", "skills": [{"skill_id": s["id"]}]})["template"]
        skillbook.edit(s["id"], {"text": "改過之後的虛構字"})
        self.assertEqual(self.mine()[0]["skills"][0]["text"], "請幫我整理這份虛構的清單。")
        self.assertEqual(tm.read_mine()[0][0]["id"], t["id"])

    def test_saving_changes_none_of_the_things_it_copied(self):
        a = self.card("虛構會計")
        s = self.skill()
        r = self.routine(a["id"])
        before = (self.now()["cards"], self.now()["skills"], self.now()["routines"])
        self.save({"name": "不動原本的", "cards": [{"profile_id": a["id"]}], "skills": [{"skill_id": s["id"]}], "routines": [{"routine_id": r["id"]}]})
        self.assertEqual((self.now()["cards"], self.now()["skills"], self.now()["routines"]), before)

    def test_the_file_is_private_in_a_private_folder_and_has_the_closed_shape(self):
        s = self.skill()
        self.save({"name": "私人", "skills": [{"skill_id": s["id"]}]})
        folder, path = self.state / "templates", self.state / "templates" / "mine.json"
        self.assertEqual(stat.S_IMODE(os.lstat(folder).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)
        data = self.mine_file()
        self.assertEqual(set(data), {"v", "templates"})
        self.assertEqual(data["v"], 1)
        self.assertEqual(set(data["templates"][0]), {"id", "name", "builtin", "cards", "skills", "routines"})

    def test_the_log_has_ids_and_counts_and_no_word(self):
        a = self.card("虛構會計")
        s = self.skill("虛構技能甲")
        t = self.save({"name": "日誌", "cards": [{"profile_id": a["id"]}], "skills": [{"skill_id": s["id"]}]})["template"]
        tm.rename_mine(t["id"], {"name": "日誌改名"})
        tm.delete_mine(t["id"], {})
        lines = [json.loads(x) for x in (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["what"] for x in lines], ["saved_mine", "renamed_mine", "deleted_mine"])
        self.assertEqual(lines[0]["counts"], {"cards": 1, "skills": 1, "routines": 0})
        self.assertTrue(all(set(x) <= {"at", "what", "id", "counts"} and x["id"] == t["id"] for x in lines))
        raw = (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8")
        for word in ("虛構", "日誌", a["id"]):
            self.assertNotIn(word, raw)
        self.assertEqual(stat.S_IMODE(os.lstat(self.state / "templates" / "log.jsonl").st_mode), 0o600)

    def test_a_full_log_becomes_log_jsonl_1_and_a_new_one_starts(self):
        folder = self.state / "templates"
        folder.mkdir(mode=0o700)
        (folder / "log.jsonl").write_text("x" * tm.LOG_MAX, encoding="utf-8")
        s = self.skill()
        t = self.save({"name": "換檔", "skills": [{"skill_id": s["id"]}]})["template"]
        self.assertEqual((folder / "log.jsonl.1").stat().st_size, tm.LOG_MAX)
        lines = (folder / "log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["id"] for x in lines], [t["id"]])

    def test_a_card_name_over_forty_characters_is_a_400_that_asks_for_a_shorter_one(self):
        a = self.card("長" * 41)
        err = self.assertApi(400, "bad_request", self.save, {"name": "太長", "cards": [{"profile_id": a["id"]}]})
        self.assertNotIn("長長", str(err))
        self.assertFalse((self.state / "templates" / "mine.json").exists())

    def test_instructions_over_the_template_limit_cannot_be_saved(self):
        a = self.card("虛構長指示", instructions="字" * ap.MAX_INSTRUCTIONS)
        self.save({"name": "剛好", "cards": [{"profile_id": a["id"]}]})          # the same limit: it fits
        self.assertEqual(tp.INSTRUCTIONS_MAX, ap.MAX_INSTRUCTIONS)

    def test_something_the_person_no_longer_has_is_a_404_and_nothing_is_saved(self):
        self.assertApi(404, "not_found", self.save, {"name": "不見了", "cards": [{"profile_id": "prof-000000000000"}]})
        self.assertApi(404, "not_found", self.save, {"name": "不見了", "skills": [{"skill_id": "k-000000000000"}]})
        self.assertApi(404, "not_found", self.save, {"name": "不見了", "routines": [{"routine_id": "r-000000000000"}]})
        self.assertFalse((self.state / "templates" / "mine.json").exists())


class SavingTickedItems(Home):
    def test_ticked_items_of_the_built_in_ones_are_copied_whole(self):
        out = self.save({"name": "我的店", "cards": [pick("shop", "service"), pick("shop", "accounting")], "skills": [pick("shop", "reply")],
                         "routines": [pick("shop", "spend")]})
        t = out["template"]
        src = {c["key"]: c for c in SHOP["cards"]}
        self.assertEqual([(c["name"], c["position"], c["instructions"], c["claude_model"]) for c in t["cards"]],
                         [(src[k]["name"], src[k]["position"], src[k]["instructions"], src[k]["claude_model"]) for k in ("service", "accounting")])
        self.assertEqual(t["skills"][0]["text"], next(s for s in SHOP["skills"] if s["key"] == "reply")["text"])
        spend = next(r for r in SHOP["routines"] if r["key"] == "spend")
        self.assertEqual((t["routines"][0]["days"], t["routines"][0]["times"], t["routines"][0]["text"]), (spend["days"], spend["times"], spend["text"]))
        accounting = next(c for c in t["cards"] if c["name"] == "會計")
        self.assertEqual(t["routines"][0]["who"], accounting["key"], "the employee it was for was ticked too")
        self.assertIsNone(tp.template_problem(t, builtin=False))

    def test_a_routine_ticked_without_its_employee_has_nobody(self):
        t = self.save({"name": "少一位", "routines": [pick("shop", "spend")]})["template"]
        self.assertIsNone(t["routines"][0]["who"])

    def test_two_templates_with_the_same_key_both_come_through_with_different_keys(self):
        t = self.save({"name": "兩個會計", "cards": [pick("shop", "accounting"), pick("studio", "accounting")]})["template"]
        keys = [c["key"] for c in t["cards"]]
        self.assertEqual(len(set(keys)), 2)
        self.assertIsNone(tp.template_problem(t, builtin=False))

    def test_routines_of_two_templates_go_to_their_own_employee(self):
        t = self.save({"name": "兩家", "cards": [pick("shop", "accounting"), pick("studio", "assistant")],
                       "routines": [pick("shop", "spend"), pick("studio", "todo")]})["template"]
        by_key = {c["key"]: c["name"] for c in t["cards"]}
        self.assertEqual([by_key[r["who"]] for r in t["routines"]], ["會計", "專案助理"])

    def test_a_template_of_the_persons_own_can_be_ticked_from_too(self):
        first = self.save({"name": "第一個", "skills": [pick("shop", "product")]})["template"]
        second = self.save({"name": "第二個", "skills": [pick(first["id"], first["skills"][0]["key"])], "cards": [pick("life", "schedule")]})["template"]
        self.assertEqual(second["skills"][0]["text"], first["skills"][0]["text"])
        self.assertEqual(len(tm.read_mine()[0]), 2)

    def test_ticked_items_and_what_the_person_has_can_be_mixed(self):
        a = self.card("虛構會計")
        s = self.skill()
        t = self.save({"name": "混合", "cards": [pick("shop", "service"), {"profile_id": a["id"]}], "skills": [{"skill_id": s["id"]}, pick("shop", "reply")]})["template"]
        self.assertEqual([c["name"] for c in t["cards"]], ["客服", "虛構會計"])
        self.assertEqual([x["name"] for x in t["skills"]], ["虛構技能", "回覆客人詢問"])
        self.assertEqual(len({c["key"] for c in t["cards"]}), 2)

    def test_the_saved_one_is_applied_by_the_same_plan_as_the_built_in_ones(self):
        t = self.save({"name": "我的店", "cards": [pick("shop", "service"), pick("shop", "accounting")], "routines": [pick("shop", "spend")]})["template"]
        mine = tm.read_mine()[0]
        planned = tp.plan({"tool": "codex", "cards": [pick(t["id"], c["key"]) for c in t["cards"]], "routines": [pick(t["id"], t["routines"][0]["key"])]},
                          templates=tp.index(mine), current={"cards": [], "skills": 0, "routines": 0})
        self.assertTrue(planned["ok"], planned["problems"])
        self.assertEqual({c["body"]["launch_mode"] for c in planned["cards"]}, {"safe"})


class WhatIsRefused(Home):
    def fake_key(self):
        return "sk-" + "ab" * 12

    def test_a_key_in_the_instructions_of_a_card_is_a_400_that_does_not_repeat_it_and_nothing_is_saved(self):
        key = self.fake_key()
        a = self.card("虛構甲", instructions=f"你是虛構的幫手，用 {key} 這個。")
        err = self.assertApi(400, "template_refused", self.save, {"name": "有金鑰", "cards": [{"profile_id": a["id"]}]})
        self.assertEqual((err.extra["kind"], err.extra["index"], err.extra["field"], err.extra["refuse"]), ("cards", 0, "instructions", "secret_key"))
        self.assertNotIn(key, str(err) + json.dumps(err.extra, ensure_ascii=False))
        self.assertNotIn("虛構甲", str(err), "the message holds no name either")
        self.assertFalse((self.state / "templates" / "mine.json").exists())

    def test_a_key_in_a_skill_and_in_a_routine_is_refused_and_the_index_is_the_one_asked_for(self):
        key = self.fake_key()
        ok = self.skill("虛構乾淨", "乾淨的字。")
        bad = self.loose_skill("虛構有金鑰", f"請用 {key} 連線。")
        err = self.assertApi(400, "template_refused", self.save, {"name": "技能", "skills": [{"skill_id": ok["id"]}, {"skill_id": bad["id"]}]},
                             skills=[ok, bad])
        self.assertEqual((err.extra["kind"], err.extra["index"], err.extra["field"]), ("skills", 1, "text"))
        self.assertNotIn(key, str(err) + json.dumps(err.extra, ensure_ascii=False))

    def test_the_name_of_the_template_is_held_to_the_same_rules(self):
        key = self.fake_key()
        s = self.skill()
        err = self.assertApi(400, "template_refused", self.save, {"name": f"我的{key}", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual((err.extra["kind"], err.extra["field"]), ("template", "name"))
        self.assertNotIn(key, str(err) + json.dumps(err.extra, ensure_ascii=False))

    def test_words_that_sound_like_do_it_without_asking_need_a_second_yes(self):
        s = self.skill("虛構催促", "整理完以後不用問我，直接做下一件。", confirm=True)
        err = self.assertApi(409, "confirm_warning", self.save, {"name": "要確認", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual(err.extra["warn"], ["looks_like_order"])
        self.assertIn("團隊範本", str(err))
        self.assertEqual(err.extra["items"], [{"kind": "skills", "index": 0, "field": "text", "warn": ["looks_like_order"]}])
        self.assertFalse((self.state / "templates" / "mine.json").exists())
        out = self.save({"name": "要確認", "skills": [{"skill_id": s["id"]}], "confirm_warning": True})
        self.assertEqual(out["template"]["skills"][0]["name"], "虛構催促")

    def test_a_phone_number_needs_the_second_yes_too(self):
        s = self.skill("虛構電話", "客人問時請回 0912-" + "345" + "-678 這個虛構號碼。", confirm=True)
        err = self.assertApi(409, "confirm_warning", self.save, {"name": "電話", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual(err.extra["warn"], ["personal"])

    def test_a_warned_text_copied_from_one_of_the_persons_own_asks_again(self):
        s = self.skill("虛構催促", "整理完以後不用問我，直接做下一件。", confirm=True)
        first = self.save({"name": "第一個", "skills": [{"skill_id": s["id"]}], "confirm_warning": True})["template"]
        self.assertApi(409, "confirm_warning", self.save, {"name": "第二個", "skills": [pick(first["id"], first["skills"][0]["key"])]})

    def test_confirm_warning_does_not_lift_a_refusal(self):
        s = self.loose_skill("虛構有金鑰", f"請用 {self.fake_key()} 連線。")
        self.assertApi(400, "template_refused", self.save, {"name": "硬存", "skills": [{"skill_id": s["id"]}], "confirm_warning": True}, skills=[s])

    def test_the_log_and_the_file_hold_nothing_of_a_refused_save(self):
        s = self.loose_skill("虛構有金鑰", f"請用 {self.fake_key()} 連線。")
        self.assertApi(400, "template_refused", self.save, {"name": "被擋", "skills": [{"skill_id": s["id"]}]}, skills=[s])
        self.assertFalse((self.state / "templates").exists(), "a refused save leaves no trace")


class TheLimits(Home):
    def test_at_least_one_item_and_a_name(self):
        self.assertApi(400, "bad_request", self.save, {"name": "空的"})
        self.assertApi(400, "bad_request", self.save, {"name": "空的", "cards": [], "skills": [], "routines": []})
        s = self.skill()
        self.assertApi(400, "bad_request", self.save, {"skills": [{"skill_id": s["id"]}]})
        self.assertApi(400, "bad_request", self.save, {"name": "", "skills": [{"skill_id": s["id"]}]})
        self.assertApi(400, "bad_request", self.save, {"name": "字" * 41, "skills": [{"skill_id": s["id"]}]})
        self.assertApi(400, "bad_request", self.save, {"name": "兩\n行", "skills": [{"skill_id": s["id"]}]})
        self.assertApi(400, "bad_request", self.save, {"name": 5, "skills": [{"skill_id": s["id"]}]})

    def test_the_body_is_strict(self):
        s = self.skill()
        for body in ({"name": "x", "skills": [{"skill_id": s["id"]}], "extra": 1},
                     {"name": "x", "skills": [{"skill_id": s["id"], "text": "改"}]},
                     {"name": "x", "skills": [{"skill_id": s["id"], "from": ref("shop", "reply")}]},
                     {"name": "x", "skills": [{"profile_id": s["id"]}]},
                     {"name": "x", "skills": {"skill_id": s["id"]}},
                     {"name": "x", "skills": ["k-000000000000"]},
                     {"name": "x", "cards": [{"from": {"template": "shop", "key": "service", "more": 1}}]},
                     {"name": "x", "cards": [{"from": ref("shop", "nobody")}]},
                     {"name": "x", "cards": [{"from": ref("tm-000000000000", "a")}]},
                     {"name": "x", "skills": [{"skill_id": s["id"]}], "confirm_warning": "yes"},
                     {"name": "x", "tool": "claude", "skills": [{"skill_id": s["id"]}]}):
            self.assertApi(400, "bad_request", self.save, body)
        for not_a_dict in (None, [], "x", 5):
            self.assertApi(400, "bad_request", self.save, not_a_dict)

    def test_the_same_thing_twice_is_a_400(self):
        a, s = self.card("虛構甲"), self.skill()
        self.assertApi(400, "bad_request", self.save, {"name": "x", "cards": [{"profile_id": a["id"]}, {"profile_id": a["id"]}]})
        self.assertApi(400, "bad_request", self.save, {"name": "x", "skills": [{"skill_id": s["id"]}, {"skill_id": s["id"]}]})
        self.assertApi(400, "bad_request", self.save, {"name": "x", "skills": [pick("shop", "reply"), pick("shop", "reply")]})

    def test_one_template_holds_at_most_12_employees_24_skills_and_12_routines(self):
        cards = [self.card(f"虛構{i}") for i in range(13)]
        self.assertApi(409, "template_too_big", self.save, {"name": "太多人", "cards": [{"profile_id": c["id"]} for c in cards]})
        self.save({"name": "剛好", "cards": [{"profile_id": c["id"]} for c in cards[:12]]})
        skills = [self.skill(f"虛構技能{i}") for i in range(25)]
        self.assertApi(409, "template_too_big", self.save, {"name": "太多技能", "skills": [{"skill_id": s["id"]} for s in skills]})
        self.save({"name": "剛好技能", "skills": [{"skill_id": s["id"]} for s in skills[:24]]})
        rs = [self.routine(cards[0]["id"], name=f"虛構例行{i}", times=(f"{8 + i % 10:02d}:00",), days=(i % 7,)) for i in range(13)]
        self.assertApi(409, "template_too_big", self.save, {"name": "太多例行", "routines": [{"routine_id": r["id"]} for r in rs]})
        self.save({"name": "剛好例行", "routines": [{"routine_id": r["id"]} for r in rs[:12]]})

    def test_at_most_twenty_of_the_persons_own(self):
        s = self.skill()
        for i in range(tp.MAX_MINE):
            self.save({"name": f"第{i}個", "skills": [{"skill_id": s["id"]}]})
        err = self.assertApi(409, "mine_full", self.save, {"name": "第二十一個", "skills": [{"skill_id": s["id"]}]})
        self.assertIn("20", str(err))
        self.assertEqual(len(self.mine()), 20)
        # deleting one makes room
        tm.delete_mine(self.mine()[0]["id"], {})
        self.save({"name": "補上", "skills": [{"skill_id": s["id"]}]})

    def test_the_full_message_is_the_same_whatever_is_saved(self):
        s = self.skill()
        for i in range(tp.MAX_MINE):
            self.save({"name": f"第{i}個", "skills": [{"skill_id": s["id"]}]})
        self.assertApi(409, "mine_full", self.save, {"name": "x", "skills": [{"skill_id": s["id"]}]})


class RenamingAndDeleting(Home):
    def made(self, name="原名"):
        s = self.skill()
        return self.save({"name": name, "skills": [{"skill_id": s["id"]}]})["template"]

    def test_rename_changes_only_the_name(self):
        t = self.made()
        out = tm.rename_mine(t["id"], {"name": "新名字"})
        self.assertEqual(out["template"], dict(t, name="新名字"))
        self.assertEqual(self.mine(), [dict(t, name="新名字")])

    def test_rename_is_strict_and_held_to_the_rules(self):
        t = self.made()
        for body in ({}, {"name": ""}, {"name": "字" * 41}, {"name": "a\nb"}, {"name": 1}, {"name": "x", "cards": []}, {"name": "x", "skills": [], "text": "y"}):
            self.assertApi(400, "bad_request", tm.rename_mine, t["id"], body)
        self.assertApi(400, "template_refused", tm.rename_mine, t["id"], {"name": "我的sk-" + "ab" * 12})
        self.assertApi(409, "confirm_warning", tm.rename_mine, t["id"], {"name": "不用問"})
        tm.rename_mine(t["id"], {"name": "不用問", "confirm_warning": True})
        self.assertEqual(self.mine()[0]["name"], "不用問")

    def test_rename_and_delete_of_one_that_is_not_there_are_404(self):
        self.made()
        self.assertApi(404, "not_found", tm.rename_mine, "tm-000000000000", {"name": "x"})
        self.assertApi(404, "not_found", tm.delete_mine, "tm-000000000000", {})
        self.assertApi(404, "not_found", tm.rename_mine, "shop", {"name": "x"})
        self.assertApi(404, "not_found", tm.delete_mine, "shop", {})

    def test_delete_removes_only_the_template_and_nothing_it_was_made_from_or_made(self):
        a = self.card("虛構會計")
        s = self.skill()
        t = self.save({"name": "要刪的", "cards": [{"profile_id": a["id"]}], "skills": [{"skill_id": s["id"]}]})["template"]
        keep = self.made("留下的")
        before = (self.now()["cards"], self.now()["skills"])
        self.assertEqual(tm.delete_mine(t["id"], {}), {"deleted": t["id"]})
        self.assertEqual([x["id"] for x in self.mine()], [keep["id"]])
        self.assertEqual((self.now()["cards"], self.now()["skills"]), before)

    def test_delete_takes_an_empty_body_only(self):
        t = self.made()
        self.assertApi(400, "bad_request", tm.delete_mine, t["id"], {"x": 1})
        self.assertEqual(len(self.mine()), 1)


class WhenTheFileCannotBeRead(Home):
    def write_raw(self, text):
        folder = self.state / "templates"
        folder.mkdir(mode=0o700, exist_ok=True)
        (folder / "mine.json").write_text(text, encoding="utf-8")

    def good(self):
        return {"id": "tm-0123456789ab", "name": "我的店", "builtin": False, "cards": [], "routines": [],
                "skills": [{"key": "daily", "name": "每日小結", "text": "請幫我寫今天的小結。"}]}

    def unreadable(self, text):
        self.write_raw(text)
        templates, readable, problem = tm.read_mine()
        self.assertEqual((templates, readable), ([], False))
        self.assertIsInstance(problem, str)
        self.assertNotIn("每日小結", problem)
        return problem

    def test_one_more_field_makes_the_whole_file_unreadable_and_nothing_is_written_over_it(self):
        extra = dict(self.good(), launch_mode="full")
        self.unreadable(json.dumps({"v": 1, "templates": [extra]}))
        s = self.skill()
        self.assertApi(503, "templates_unreadable", self.save, {"name": "新的", "skills": [{"skill_id": s["id"]}]})
        self.assertApi(503, "templates_unreadable", tm.rename_mine, "tm-0123456789ab", {"name": "x"})
        self.assertApi(503, "templates_unreadable", tm.delete_mine, "tm-0123456789ab", {})
        kept = [p for p in (self.state / "templates").iterdir() if p.name.startswith("mine.json.corrupt-")]
        self.assertEqual(len(kept), 1, "the unreadable file is kept where it was moved")
        self.assertIn("launch_mode", kept[0].read_text(encoding="utf-8"))

    def test_a_card_with_a_tool_or_a_skill_with_a_source_is_unreadable_too(self):
        card = {"key": "boss", "name": "店長", "position": None, "instructions": None, "claude_model": None}
        for template in (dict(self.good(), cards=[dict(card, tool="claude")]),
                         dict(self.good(), skills=[{"key": "a", "name": "技", "text": "字", "source": {"how": "typed"}}]),
                         dict(self.good(), routines=[{"key": "r", "name": "例", "text": "字", "days": [0], "times": ["09:00"], "who": None, "enabled": True}]),
                         dict(self.good(), cards=[dict(card, equipped_skill_ids=[])])):
            self.tearDown_state()
            self.unreadable(json.dumps({"v": 1, "templates": [template]}))

    def tearDown_state(self):
        import shutil
        shutil.rmtree(self.state / "templates", ignore_errors=True)

    def test_other_ways_to_be_unreadable(self):
        good = self.good()
        for text in ("not json", "[]", json.dumps({"v": 2, "templates": []}), json.dumps({"templates": [], "v": 1, "extra": 1}), json.dumps({"v": 1, "templates": [good], "extra": 1}),
                     json.dumps({"v": 1, "templates": [good, good]}),
                     json.dumps({"v": 1, "templates": [dict(good, id="shop")]}),
                     json.dumps({"v": 1, "templates": [dict(good, builtin=True)]}),
                     json.dumps({"v": 1, "templates": [dict(good, id=f"tm-{i:012x}") for i in range(tp.MAX_MINE + 1)]})):
            self.tearDown_state()
            self.unreadable(text)

    def test_a_good_file_with_the_optional_about_is_readable(self):
        self.write_raw(json.dumps({"v": 1, "templates": [dict(self.good(), about="說明")]}))
        templates, readable, problem = tm.read_mine()
        self.assertEqual((len(templates), readable, problem), (1, True, None))

    def test_a_link_in_place_of_the_file_is_unreadable_and_not_followed(self):
        folder = self.state / "templates"
        folder.mkdir(mode=0o700)
        target = Path(self.tmp.name) / "elsewhere.json"
        target.write_text(json.dumps({"v": 1, "templates": [self.good()]}), encoding="utf-8")
        os.symlink(target, folder / "mine.json")
        self.assertFalse(tm.read_mine()[1])

    def test_a_link_in_place_of_the_folder_is_unreadable(self):
        target = Path(self.tmp.name) / "folder"
        target.mkdir()
        os.symlink(target, self.state / "templates")
        self.assertFalse(tm.read_mine()[1])
        s = self.skill()
        self.assertApi(503, "templates_unreadable", self.save, {"name": "新的", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual(list(target.iterdir()), [], "nothing was written through the link")


class OnlyOnThisComputer(unittest.TestCase):
    def test_the_module_has_no_way_to_export_import_or_send(self):
        source = Path(tm.__file__).read_text(encoding="utf-8")
        for word in ("urllib", "http", "socket", "export", "import_mine", "upload", "download", "requests"):
            self.assertNotRegex(source, rf"(?m)^\s*(?:import|from)\s+{word}\b", word)
        public = {n for n in dir(tm) if not n.startswith("_")}
        self.assertFalse({n for n in public if re.search(r"export|import_|upload|download|send", n)}, public)


if __name__ == "__main__":
    unittest.main()
