"""P45-1: the format of a team template, the bodies it makes for the ordinary write functions, and the plan of a selection
(vbear/templates.py). Pure: nothing here writes the state folder, except the one class that hands the bodies to the real write
functions in a temporary home to show they take them."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import agent_profiles as ap, model_options, routine_rules, routines, skillbook, templates as tp, templates_builtin as tb

SHOP, CREATOR, STUDIO, LIFE = tb.builtin()


def ref(template, key):
    return {"template": template, "key": key}


def pick(template, key, **extra):
    return {"from": ref(template, key), **extra}


def mine_template(**over):
    """A made-up saved team template of the person's (the shape P45-3 will store)."""
    base = {"id": "tm-0123456789ab", "name": "我的店", "builtin": False,
            "cards": [{"key": "boss", "name": "店長", "position": None, "instructions": "你是店長的小幫手。", "claude_model": None}],
            "skills": [{"key": "daily", "name": "每日小結", "text": "請幫我寫今天的小結。"}],
            "routines": [{"key": "close", "name": "打烊前提醒", "text": "請提醒我打烊前要做的事。", "days": [0, 1, 2, 3, 4], "times": ["20:00"], "who": "boss"}]}
    base.update(over)
    return base


def templates_by_id(*extra):
    return tp.index(list(extra))


def current(cards=(), skills=0, routine_count=0):
    return {"cards": [dict(c) for c in cards], "skills": skills, "routines": routine_count}


def existing_card(pid="p-old", name="老員工", can_chat=True):
    return {"id": pid, "name": name, "can_chat": can_chat}


def plan(body, cur=None, extra=()):
    return tp.plan(body, templates=templates_by_id(*extra), current=cur or current())


class SameNumbers(unittest.TestCase):
    """The numbers templates.py repeats (it may not import skillbook or routine_rules) are the ones the write functions hold."""

    def test_limits_equal_the_ones_of_the_write_functions(self):
        self.assertEqual(tp.MAX_CARDS, ap.MAX_PROFILES)
        self.assertEqual(tp.MAX_SKILLS, skillbook.MAX_SKILLS)
        self.assertEqual(tp.MAX_ROUTINES, routine_rules.MAX_ROUTINES)
        self.assertEqual(tp.NAME_MAX, skillbook.MAX_NAME)
        self.assertEqual(tp.NAME_MAX, routine_rules.NAME_MAX)
        self.assertEqual(tp.TEXT_MAX, skillbook.MAX_TEXT)
        self.assertEqual(tp.TEXT_MAX, routine_rules.TEXT_MAX)
        self.assertEqual(tp.INSTRUCTIONS_MAX, ap.MAX_INSTRUCTIONS)
        self.assertEqual(tp.MAX_TIMES, routine_rules.MAX_TIMES)
        self.assertEqual(tp.MIN_GAP_MIN, routine_rules.MIN_GAP_MIN)
        self.assertEqual(tp.POSITIONS, ap.POSITIONS)
        self.assertEqual(tp.CLAUDE_MODELS, model_options.CLAUDE_ALIASES)

    def test_the_numbers_of_the_plan(self):
        self.assertEqual((tp.MAX_PER_TEMPLATE, tp.MAX_PER_APPLY), ({"cards": 12, "skills": 24, "routines": 12},) * 2)
        self.assertEqual((tp.MAX_MINE, tp.ABOUT_MAX), (20, 120))

    def test_the_two_warnings_say_what_the_skills_say_in_the_words_of_a_team_template(self):
        self.assertEqual(set(tp.WARN_TEXT), {"looks_like_order", "personal"})
        self.assertTrue(all("團隊範本" in text for text in tp.WARN_TEXT.values()))


class TheFormat(unittest.TestCase):
    def problem(self, template, builtin=False):
        return tp.template_problem(template, builtin=builtin)

    def test_the_four_built_in_templates_and_a_saved_one_are_fine(self):
        for t in tb.builtin():
            self.assertIsNone(self.problem(t, builtin=True), t["id"])
        self.assertIsNone(self.problem(mine_template()))

    def test_a_saved_template_may_have_no_about_and_a_built_in_must_have_one(self):
        self.assertIsNone(self.problem(mine_template()))
        gone = tb.builtin()[0]
        del gone["about"]
        self.assertIsNotNone(self.problem(gone, builtin=True))

    def test_the_shape_is_closed(self):
        extra = mine_template()
        extra["color"] = "red"
        self.assertIsNotNone(self.problem(extra))
        for field in ("launch_mode", "equipped_skill_ids", "profession_role_id", "permission_intents", "tool", "enabled", "id", "model", "memory"):
            card = mine_template()
            card["cards"][0][field] = "x"
            self.assertIsNotNone(self.problem(card), field)
        skill = mine_template()
        skill["skills"][0]["source"] = {"how": "typed"}
        self.assertIsNotNone(self.problem(skill))
        routine = mine_template()
        routine["routines"][0]["enabled"] = False
        self.assertIsNotNone(self.problem(routine))
        for field in ("cards", "skills", "routines", "name", "builtin", "id"):
            lacking = mine_template()
            del lacking[field]
            self.assertIsNotNone(self.problem(lacking), field)

    def test_the_id_and_the_builtin_flag_belong_together(self):
        self.assertIsNotNone(self.problem(mine_template(id="shop")))
        self.assertIsNotNone(self.problem(mine_template(id="tm-xyz")))
        self.assertIsNotNone(self.problem(mine_template(builtin=True)))
        bad = tb.builtin()[0]
        bad["id"] = "tm-0123456789ab"
        self.assertIsNotNone(self.problem(bad, builtin=True))
        self.assertIsNotNone(self.problem(tb.builtin()[0], builtin=False))

    def test_names_keys_and_texts(self):
        for name in ("", " ", "x" * 41, "兩\n行", 5, None):
            self.assertIsNotNone(self.problem(mine_template(name=name)), repr(name))
        self.assertIsNone(self.problem(mine_template(name="x" * 40)))
        for key in ("", "A", "1a", "a-b", "a" * 25, "a b", 3):
            card = mine_template()
            card["cards"][0]["key"] = key
            card["routines"][0]["who"] = None
            self.assertIsNotNone(self.problem(card), repr(key))
        dup = mine_template()
        dup["skills"].append(dict(dup["skills"][0]))
        self.assertIsNotNone(self.problem(dup))
        same_key_other_kind = mine_template()
        same_key_other_kind["skills"][0]["key"] = "boss"
        self.assertIsNone(self.problem(same_key_other_kind), "keys only have to differ inside one kind")
        text = mine_template()
        text["skills"][0]["text"] = " 頭尾有空白 "
        self.assertIsNotNone(self.problem(text))
        text["skills"][0]["text"] = "x" * 4001
        self.assertIsNotNone(self.problem(text))
        text["skills"][0]["text"] = "第一行\n第二行\t縮排"
        self.assertIsNone(self.problem(text))
        text["skills"][0]["text"] = "控制\x07字元"
        self.assertIsNotNone(self.problem(text))
        about = mine_template(about="x" * 121)
        self.assertIsNotNone(self.problem(about))

    def test_a_card(self):
        for field, value in (("position", "boss"), ("position", 3), ("claude_model", "gpt"), ("claude_model", "claude-opus-4"),
                             ("instructions", ""), ("instructions", "x" * 2001), ("instructions", " x"), ("instructions", 5), ("name", "")):
            t = mine_template()
            t["cards"][0][field] = value
            self.assertIsNotNone(self.problem(t), (field, value))
        for field, value in (("position", "accountant"), ("position", None), ("claude_model", "fable"), ("instructions", None)):
            t = mine_template()
            t["cards"][0][field] = value
            self.assertIsNone(self.problem(t), (field, value))

    def test_a_routine(self):
        def with_(**over):
            t = mine_template()
            t["routines"][0].update(over)
            return self.problem(t)
        self.assertIsNone(with_(days=[6], times=["07:00", "13:00", "19:00"]))
        for over in ({"days": []}, {"days": [7]}, {"days": [1, 1]}, {"days": [2, 1]}, {"days": [True]}, {"days": "1"},
                     {"times": []}, {"times": ["8:00"]}, {"times": ["24:00"]}, {"times": ["08:00", "08:30"]},
                     {"times": ["00:00", "23:30"]}, {"times": ["09:00", "09:00"]}, {"times": ["09:00", "11:00", "13:00", "15:00"]},
                     {"who": "nobody"}, {"who": 4}, {"text": ""}):
            self.assertIsNotNone(with_(**over), over)
        self.assertIsNone(with_(who=None))

    def test_how_many_a_template_may_hold(self):
        many = mine_template()
        many["cards"] = [{"key": f"c{i}", "name": f"員工{i}", "position": None, "instructions": None, "claude_model": None} for i in range(13)]
        many["routines"] = []
        self.assertIsNotNone(self.problem(many))
        many["cards"] = many["cards"][:12]
        self.assertIsNone(self.problem(many))
        many["skills"] = [{"key": f"s{i}", "name": f"技能{i}", "text": "做法"} for i in range(25)]
        self.assertIsNotNone(self.problem(many))
        many["skills"] = many["skills"][:24]
        many["routines"] = [{"key": f"r{i}", "name": f"工作{i}", "text": "做法", "days": [0], "times": ["09:00"], "who": None} for i in range(13)]
        self.assertIsNotNone(self.problem(many))
        empty = mine_template(cards=[], skills=[], routines=[])
        self.assertIsNotNone(self.problem(empty), "a template holds at least one thing")

    def test_what_is_not_a_template(self):
        for thing in (None, [], "x", 3):
            self.assertIsNotNone(self.problem(thing))

    def test_the_problem_says_nothing_of_the_words(self):
        t = mine_template()
        t["skills"][0]["text"] = "秘密字句ZZ" + "x" * 4001
        self.assertNotIn("秘密字句ZZ", self.problem(t))


class TheCatalog(unittest.TestCase):
    def test_catalog_has_the_four_built_in_and_the_saved_ones_as_copies(self):
        got = tp.catalog([mine_template()])
        self.assertEqual([t["id"] for t in got["builtin"]], ["shop", "creator", "studio", "life"])
        self.assertEqual([t["id"] for t in got["mine"]], ["tm-0123456789ab"])
        got["builtin"][0]["cards"][0]["name"] = "改了"
        self.assertEqual(tp.catalog()["builtin"][0]["cards"][0]["name"], "客服")
        self.assertEqual(tp.catalog()["mine"], [])

    def test_index_by_id_and_a_saved_template_cannot_take_a_built_in_id(self):
        got = tp.index([mine_template()])
        self.assertEqual(sorted(got), sorted(["shop", "creator", "studio", "life", "tm-0123456789ab"]))
        with self.assertRaises(ValueError):
            tp.index([mine_template(id="shop")])
        with self.assertRaises(ValueError):
            tp.index([mine_template(), mine_template()])


class TheBodies(unittest.TestCase):
    def test_a_card_for_each_tool(self):
        card = SHOP["cards"][1]
        claude = tp.card_body(card, "claude")
        self.assertEqual(claude, {"name": "商品文案", "position": "social", "instructions": card["instructions"], "launch_mode": "safe",
                                  "model": {"tool": "claude", "model_id": "sonnet"}, "equipped_skill_ids": [],
                                  "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
                                  "profession_role_id": None})
        codex = tp.card_body(card, "codex")
        self.assertEqual(codex["model"], {"tool": "codex", "model_id": ""})
        self.assertEqual({k: v for k, v in codex.items() if k != "model"}, {k: v for k, v in claude.items() if k != "model"})

    def test_a_card_is_always_safe_without_a_skill_card_and_without_an_enabled_key(self):
        for t in tb.builtin():
            for c in t["cards"]:
                for tool in ("claude", "codex"):
                    body = tp.card_body(c, tool)
                    self.assertEqual(body["launch_mode"], "safe")
                    self.assertEqual(body["equipped_skill_ids"], [])
                    self.assertNotIn("enabled", body)
                    self.assertEqual(set(body), {"name", "position", "instructions", "launch_mode", "model", "equipped_skill_ids",
                                                 "permission_intents", "profession_role_id"})
        self.assertIsNot(tp.card_body(SHOP["cards"][0], "claude")["permission_intents"], tp.card_body(SHOP["cards"][0], "claude")["permission_intents"])

    def test_a_name_the_person_changed_and_a_card_with_no_model_or_words(self):
        card = {"key": "x", "name": "原名", "position": None, "instructions": None, "claude_model": None}
        body = tp.card_body(card, "claude", "新名")
        self.assertEqual((body["name"], body["model"], body["instructions"], body["position"]), ("新名", {"tool": "claude", "model_id": ""}, None, None))

    def test_only_two_tools(self):
        with self.assertRaises(ValueError):
            tp.card_body(SHOP["cards"][0], "agy")

    def test_a_skill_is_a_name_and_words_and_nothing_else(self):
        self.assertEqual(tp.skill_body(SHOP["skills"][2]), {"name": "整理一天的帳", "text": SHOP["skills"][2]["text"]})

    def test_a_routine_is_six_fields_and_always_off(self):
        body = tp.routine_body(SHOP["routines"][1], "prof-abc")
        self.assertEqual(body, {"name": "想下週的促銷", "profile_id": "prof-abc", "text": SHOP["routines"][1]["text"], "days": [4], "times": ["10:00"],
                                "enabled": False})
        self.assertIs(body["enabled"], False)
        for t in tb.builtin():
            for r in t["routines"]:
                self.assertIs(tp.routine_body(r, "prof-abc")["enabled"], False)
                routine_rules.validate_fields(tp.routine_body(r, "prof-abc"), full=True)

    def test_the_bodies_are_copies(self):
        body = tp.routine_body(SHOP["routines"][0], "prof-abc")
        body["days"].append(9)
        self.assertEqual(SHOP["routines"][0]["days"], [0, 1, 2, 3, 4, 5, 6])


class TheRealWriteFunctionsTakeTheBodies(unittest.TestCase):
    """Every body of the four built-in templates, for both tools, goes through the ordinary write functions of a temporary home."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbtp-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        (home / ".vbear").mkdir(parents=True, mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_cards_skills_and_routines(self):
        for tool in ("claude", "codex"):
            cards = {}
            for t in tb.builtin():
                for c in t["cards"]:
                    saved = ap.save_profile(None, tp.card_body(c, tool))
                    self.assertEqual((saved["launch_mode"], saved["equipped_skill_ids"], saved["model"]["tool"]), ("safe", [], tool))
                    self.assertIsNot(saved.get("enabled"), False, "a new card is not switched off")
                    cards[(t["id"], c["key"])] = saved["id"]
            self.assertEqual(len(cards), 12)
            for t in tb.builtin():
                for s in t["skills"]:
                    got = skillbook.add(tp.skill_body(s))["skill"]
                    self.assertEqual(got["source"], {"how": "typed"})
                for r in t["routines"]:
                    got = routines.create(tp.routine_body(r, cards[(t["id"], r["who"])]),
                                          [{"id": i, "can_chat": True} for i in cards.values()])["routine"]
                    self.assertIs(got["enabled"], False)
                    self.assertIsNone(got["enabled_at"])
            for pid in cards.values():
                ap.delete_profile(pid)


class TheTools(unittest.TestCase):
    def row(self, tid, ready, state="ready", chat=None):
        row = {"id": tid, "ready": ready, "state": state, "installed": state != "not_installed", "login": "logged_in" if ready else "not_logged_in"}
        if chat is not None:
            row["chat_login"] = {"state": chat, "problem": ""}
        return row

    def test_claude_is_the_default_when_it_is_ready_or_when_nothing_is(self):
        both = tp.tools_view([self.row("claude", True), self.row("codex", True, chat="logged_in")])
        self.assertEqual((both["claude"]["ready"], both["codex"]["ready"], both["default"]), (True, True, "claude"))
        only_claude = tp.tools_view([self.row("claude", True), self.row("codex", False, "not_logged_in", chat="not_logged_in")])
        self.assertEqual((only_claude["default"], only_claude["codex"]["ready"]), ("claude", False))
        none = tp.tools_view([self.row("claude", False, "not_installed"), self.row("codex", False, "not_installed")])
        self.assertEqual((none["default"], none["claude"]["ready"], none["codex"]["ready"]), ("claude", False, False))
        self.assertTrue(none["claude"]["why"] and none["codex"]["why"])

    def test_codex_is_the_default_only_when_claude_is_not_ready_and_the_codex_that_chats_is_logged_in(self):
        got = tp.tools_view([self.row("claude", False, "not_logged_in"), self.row("codex", True, chat="logged_in")])
        self.assertEqual((got["default"], got["codex"]["ready"]), ("codex", True))
        for chat in ("not_logged_in", "unknown", "folder_problem"):
            got = tp.tools_view([self.row("claude", False, "not_logged_in"), self.row("codex", True, chat=chat)])
            self.assertEqual((got["default"], got["codex"]["ready"]), ("claude", False), chat)
            self.assertTrue(got["codex"]["why"])

    def test_a_tool_the_page_does_not_list_is_not_ready(self):
        got = tp.tools_view([])
        self.assertEqual((got["claude"]["ready"], got["codex"]["ready"], got["default"]), (False, False, "claude"))

    def test_the_rows_are_only_read(self):
        rows = [self.row("claude", True), self.row("codex", False, "not_logged_in", chat="not_logged_in")]
        before = copy.deepcopy(rows)
        tp.tools_view(rows)
        self.assertEqual(rows, before)


class ThePlan(unittest.TestCase):
    def test_routines_whose_employees_were_not_ticked_have_no_one(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "service"), pick("creator", "writer")],
                    "skills": [pick("shop", "reply"), pick("creator", "short")],
                    "routines": [pick("shop", "promo"), pick("creator", "week")]})
        # promo goes to "copy" and week to "editor"; neither was ticked
        self.assertEqual([p["code"] for p in got["problems"]], ["no_assignee", "no_assignee"])
        self.assertEqual([p["from"] for p in got["problems"]], [ref("shop", "promo"), ref("creator", "week")])
        self.assertFalse(got["ok"])

    def test_a_good_mix(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "copy"), pick("creator", "editor"), pick("studio", "accounting")],
                    "skills": [pick("shop", "product"), pick("creator", "ideas")],
                    "routines": [pick("shop", "promo"), pick("creator", "week"), pick("shop", "spend", to={"card": ref("studio", "accounting")})]})
        self.assertEqual(got["problems"], [])
        self.assertTrue(got["ok"])
        self.assertEqual(got["tool"], "claude")
        self.assertEqual([c["from"] for c in got["cards"]], [ref("shop", "copy"), ref("creator", "editor"), ref("studio", "accounting")])
        self.assertEqual([c["name"] for c in got["cards"]], ["商品文案", "社群編輯", "會計"])
        self.assertEqual([r["assignee"]["name"] for r in got["routines"]], ["商品文案", "社群編輯", "會計"])
        self.assertEqual([r["assignee"]["kind"] for r in got["routines"]], ["card", "card", "card"])
        self.assertEqual(got["cards"][0]["body"], tp.card_body(SHOP["cards"][1], "claude"))
        self.assertEqual(got["skills"][1]["body"], tp.skill_body(CREATOR["skills"][0]))
        self.assertEqual(got["routines"][0]["routine"], SHOP["routines"][1])
        self.assertEqual(got["after"]["cards"], {"now": 0, "add": 3, "after": 3, "max": 500})
        self.assertEqual(got["after"]["skills"], {"now": 0, "add": 2, "after": 2, "max": 100})
        self.assertEqual(got["after"]["routines"], {"now": 0, "add": 3, "after": 3, "max": 20})

    def test_the_default_assignee_is_the_one_the_template_names_when_he_is_ticked(self):
        got = plan({"tool": "codex", "cards": [pick("shop", "accounting")], "routines": [pick("shop", "spend")]})
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["routines"][0]["assignee"], {"kind": "card", "card": ref("shop", "accounting"), "profile_id": None, "name": "會計"})
        self.assertEqual(got["cards"][0]["body"]["model"], {"tool": "codex", "model_id": ""})
        self.assertEqual(got["cards"][0]["model_id"], "")

    def test_a_routine_whose_employee_is_not_ticked_has_no_one(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "service")], "routines": [pick("shop", "spend")]})
        self.assertEqual([p["code"] for p in got["problems"]], ["no_assignee"])
        self.assertEqual(got["routines"][0]["assignee"], {"kind": None, "card": None, "profile_id": None, "name": None})
        self.assertFalse(got["ok"])
        self.assertEqual(got["choices"]["cards"], [{"template": "shop", "key": "service", "name": "客服"}])

    def test_a_routine_for_an_employee_the_person_already_has(self):
        cur = current([existing_card()])
        body = {"tool": "claude", "routines": [pick("shop", "spend", to={"profile_id": "p-old"})]}
        got = plan(body, cur)
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["routines"][0]["assignee"], {"kind": "existing", "card": None, "profile_id": "p-old", "name": "老員工"})
        self.assertEqual(got["after"]["cards"]["add"], 0)
        self.assertEqual(got["choices"]["existing"], [{"profile_id": "p-old", "name": "老員工"}])

    def test_an_employee_who_cannot_chat_or_is_not_there_is_a_problem(self):
        cur = current([existing_card("p-off", "停用員工", can_chat=False)])
        for pid in ("p-off", "p-ghost"):
            got = plan({"tool": "claude", "routines": [pick("shop", "spend", to={"profile_id": pid})]}, cur)
            self.assertEqual([p["code"] for p in got["problems"]], ["assignee_cannot_chat"], pid)
        self.assertEqual(plan({"tool": "claude", "routines": [pick("shop", "spend")]}, cur)["choices"]["existing"], [])

    def test_the_person_may_choose_another_ticked_employee(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "service"), pick("shop", "accounting")],
                    "routines": [pick("shop", "spend", to={"card": ref("shop", "service")})]})
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["routines"][0]["assignee"]["card"], ref("shop", "service"))

    def test_a_malformed_request_is_a_value_error(self):
        good = {"tool": "claude", "cards": [pick("shop", "service")]}
        for bad in (None, [], "x", {}, {"cards": [pick("shop", "service")]}, {"tool": "agy", "cards": [pick("shop", "service")]},
                    {**good, "extra": 1}, {**good, "confirm_warning": "yes"}, {**good, "cards": "x"}, {**good, "cards": [None]},
                    {**good, "cards": [{"from": ref("shop", "service"), "color": 1}]}, {**good, "cards": [{"from": {"template": "shop"}}]},
                    {**good, "cards": [{"from": {**ref("shop", "service"), "x": 1}}]}, {**good, "cards": [pick("nope", "service")]},
                    {**good, "cards": [pick("shop", "nope")]}, {**good, "cards": [pick("shop", "reply")]},
                    {**good, "cards": [pick("shop", "service"), pick("shop", "service")]},
                    {**good, "cards": [pick("shop", "service", name=5)]}, {**good, "skills": [pick("shop", "reply", name="x")]},
                    {"tool": "claude", "cards": []}, {"tool": "claude"},
                    {**good, "routines": [pick("shop", "spend", to={"card": ref("shop", "service"), "profile_id": "p-old"})]},
                    {**good, "routines": [pick("shop", "spend", to={})]}, {**good, "routines": [pick("shop", "spend", to={"card": ref("shop", "copy")})]},
                    {**good, "routines": [pick("shop", "spend", to={"profile_id": 7})]}, {**good, "routines": [pick("shop", "spend", to="x")]},
                    {**good, "routines": [pick("shop", "spend"), pick("shop", "spend")]}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                plan(bad)

    def test_the_same_item_cannot_be_ticked_twice_but_the_same_name_from_two_templates_can(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "accounting"), pick("studio", "accounting")]})
        self.assertEqual(got["problems"], [])
        self.assertEqual([c["same_in_batch"] for c in got["cards"]], [True, True])
        self.assertEqual([n["code"] for n in got["notes"]], ["same_name_batch"])
        self.assertEqual(got["notes"][0]["name"], "會計")
        self.assertEqual(got["notes"][0]["count"], 2)

    def test_the_same_name_as_a_card_the_person_has(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "accounting"), pick("shop", "copy")]}, current([existing_card("p-1", " 會計 ")]))
        self.assertEqual([c["same_existing"] for c in got["cards"]], [True, False])
        self.assertEqual([n["code"] for n in got["notes"]], ["same_name_existing"])
        self.assertEqual(got["problems"], [])

    def test_one_apply_holds_at_most_12_employees_24_skills_and_12_routines(self):
        every_card = [pick(t["id"], c["key"]) for t in tb.builtin() for c in t["cards"]]
        every_skill = [pick(t["id"], s["key"]) for t in tb.builtin() for s in t["skills"]]
        every_routine = [pick(t["id"], r["key"]) for t in tb.builtin() for r in t["routines"]]
        full = plan({"tool": "claude", "cards": every_card, "skills": every_skill, "routines": every_routine})
        self.assertEqual(full["problems"], [])
        self.assertEqual((len(full["cards"]), len(full["skills"]), len(full["routines"])), (12, 12, 6), "all four, every box ticked")
        big = mine_template()
        big["cards"] = [{"key": f"c{i}", "name": f"員工{i}", "position": None, "instructions": None, "claude_model": None} for i in range(12)]
        big["skills"] = [{"key": f"s{i}", "name": f"技能{i}", "text": "做法"} for i in range(12)]
        big["routines"] = [{"key": f"r{i}", "name": f"工作{i}", "text": "做法", "days": [0], "times": ["09:00"], "who": "c0"} for i in range(12)]
        big2 = copy.deepcopy(big)
        big2["id"] = "tm-aaaaaaaaaaaa"
        cards13 = every_card + [pick("tm-0123456789ab", "c0")]
        with self.assertRaises(ValueError):
            plan({"tool": "claude", "cards": cards13}, extra=(big,))
        skills25 = every_skill + [pick("tm-0123456789ab", f"s{i}") for i in range(12)] + [pick("tm-aaaaaaaaaaaa", "s0")]
        with self.assertRaises(ValueError):
            plan({"tool": "claude", "skills": skills25}, extra=(big, big2))
        routines13 = every_routine + [pick("tm-0123456789ab", f"r{i}") for i in range(7)]
        with self.assertRaises(ValueError):
            plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "c0")], "routines": routines13}, extra=(big,))

    def test_over_the_limits_after_the_apply_is_a_problem_that_says_by_how_much(self):
        cur = current([existing_card(f"p-{i}", f"員工{i}") for i in range(499)], skills=97, routine_count=19)
        body = {"tool": "claude", "cards": [pick("shop", "service"), pick("shop", "copy"), pick("shop", "accounting")],
                "skills": [pick("shop", "reply"), pick("shop", "product"), pick("shop", "daybook"), pick("creator", "ideas"), pick("creator", "post")],
                "routines": [pick("shop", "spend"), pick("shop", "promo"), pick("creator", "news")]}
        body["routines"][0]["to"] = {"card": ref("shop", "accounting")}
        body["routines"][1]["to"] = {"card": ref("shop", "copy")}
        body["routines"][2]["to"] = {"card": ref("shop", "service")}
        got = plan(body, cur)
        full = {p["kind"]: p for p in got["problems"] if p["code"] == "template_full"}
        self.assertEqual(set(full), {"cards", "skills", "routines"})
        self.assertEqual((full["cards"]["over"], full["skills"]["over"], full["routines"]["over"]), (2, 2, 2))
        self.assertIn("技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個", full["skills"]["text"])
        self.assertIn("角色卡會超過 500 張：你現在有 499 張，這次要加 3 張，請少勾 2 張", full["cards"]["text"])
        self.assertIn("例行工作會超過 20 件：你現在有 19 件，這次要加 3 件，請少勾 2 件", full["routines"]["text"])
        self.assertFalse(got["ok"])
        # exactly at the limit is fine
        cur = current([existing_card(f"p-{i}", f"員工{i}") for i in range(497)], skills=95, routine_count=17)
        self.assertEqual(plan(body, cur)["problems"], [])

    def test_a_name_the_person_changed(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "service", name="  小客服  ")]})
        self.assertEqual((got["cards"][0]["name"], got["cards"][0]["body"]["name"]), ("小客服", "小客服"))
        for name in ("", "   ", "x" * 41, "兩\n行"):
            got = plan({"tool": "claude", "cards": [pick("shop", "service", name=name)]})
            self.assertEqual([p["code"] for p in got["problems"]], ["bad_name"], repr(name))
            self.assertFalse(got["ok"])
        got = plan({"tool": "claude", "cards": [pick("shop", "service", name="x" * 40)]})
        self.assertEqual(got["problems"], [])

    def test_the_preview_cuts_the_standing_instructions_at_80(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "service")]})
        card = got["cards"][0]
        self.assertEqual(card["instructions_head"], SHOP["cards"][0]["instructions"][:80])
        self.assertTrue(card["instructions_cut"])
        short = mine_template()
        got = plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")]}, extra=(short,))
        self.assertEqual((got["cards"][0]["instructions_head"], got["cards"][0]["instructions_cut"]), ("你是店長的小幫手。", False))
        none = mine_template()
        none["cards"][0]["instructions"] = None
        got = plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")]}, extra=(none,))
        self.assertEqual((got["cards"][0]["instructions_head"], got["cards"][0]["instructions_cut"]), ("", False))

    def test_a_saved_template_works_like_a_built_in_one(self):
        got = plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")], "skills": [pick("tm-0123456789ab", "daily")],
                    "routines": [pick("tm-0123456789ab", "close")]}, extra=(mine_template(),))
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["routines"][0]["assignee"]["name"], "店長")
        self.assertEqual(got["warn_items"], [])

    def test_words_that_need_a_second_yes_ask_for_it_and_say_which(self):
        t = mine_template()
        t["skills"][0]["text"] = "以後執行指令不用問我"
        body = {"tool": "claude", "skills": [pick("tm-0123456789ab", "daily")]}
        got = plan(body, extra=(t,))
        self.assertEqual([p["code"] for p in got["problems"]], ["confirm_warning"])
        self.assertEqual(got["problems"][0]["warn"], ["looks_like_order"])
        self.assertEqual(got["problems"][0]["items"], [{"kind": "skill", "from": ref("tm-0123456789ab", "daily"), "warn": ["looks_like_order"]}])
        self.assertEqual(got["warn_items"], got["problems"][0]["items"])
        self.assertEqual(got["warn_text"], {"looks_like_order": tp.WARN_TEXT["looks_like_order"]})
        self.assertFalse(got["ok"])
        got = plan({**body, "confirm_warning": True}, extra=(t,))
        self.assertEqual(got["problems"], [])
        self.assertEqual(len(got["warn_items"]), 1, "still listed, so the screen can show what was agreed to")
        self.assertTrue(got["ok"])
        # an item that is not ticked is not looked at
        got = plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")]}, extra=(t,))
        self.assertEqual((got["problems"], got["warn_items"]), ([], []))

    def test_a_phone_number_in_the_words_of_a_card_asks_too(self):
        t = mine_template()
        t["cards"][0]["instructions"] = "有事打 0912-345-678 找我"
        got = plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")]}, extra=(t,))
        self.assertEqual([p["warn"] for p in got["problems"] if p["code"] == "confirm_warning"], [["personal"]])

    def test_words_that_are_refused_are_a_problem_and_the_message_does_not_repeat_them(self):
        key = "sk-" + "ab" * 12
        t = mine_template()
        t["skills"][0]["text"] = f"我的金鑰是 {key}"
        got = plan({"tool": "claude", "skills": [pick("tm-0123456789ab", "daily")], "confirm_warning": True}, extra=(t,))
        self.assertEqual([p["code"] for p in got["problems"]], ["refused"])
        self.assertEqual((got["problems"][0]["kind"], got["problems"][0]["from"], got["problems"][0]["refuse"]),
                         ("skill", ref("tm-0123456789ab", "daily"), "secret_key"))
        self.assertNotIn(key, repr(got["problems"]))
        self.assertFalse(got["ok"])

    def test_the_built_in_words_never_ask_for_a_second_yes(self):
        every = {"tool": "codex", "cards": [pick(t["id"], c["key"]) for t in tb.builtin() for c in t["cards"]],
                 "skills": [pick(t["id"], s["key"]) for t in tb.builtin() for s in t["skills"]],
                 "routines": [pick(t["id"], r["key"]) for t in tb.builtin() for r in t["routines"]]}
        got = plan(every)
        self.assertEqual((got["problems"], got["warn_items"], got["warn_text"]), ([], [], {}))

    def test_planning_changes_nothing_it_was_given(self):
        templates = templates_by_id(mine_template())
        cur = current([existing_card()], skills=3, routine_count=1)
        before = (copy.deepcopy(templates), copy.deepcopy(cur))
        body = {"tool": "claude", "cards": [pick("shop", "service", name="新")], "routines": [pick("shop", "spend", to={"profile_id": "p-old"})]}
        keep = copy.deepcopy(body)
        tp.plan(body, templates=templates, current=cur)
        self.assertEqual((templates, cur), before)
        self.assertEqual(body, keep)

    def test_public_view_has_no_bodies(self):
        got = plan({"tool": "claude", "cards": [pick("shop", "service")], "skills": [pick("shop", "reply")], "routines": [pick("shop", "spend")]})
        shown = tp.public(got)
        self.assertTrue(all("body" not in c for c in shown["cards"]))
        self.assertTrue(all("body" not in s for s in shown["skills"]))
        self.assertTrue(all("routine" not in r for r in shown["routines"]))
        self.assertIn("body", got["cards"][0], "the plan itself keeps them for the apply")
        self.assertEqual(set(shown), set(got))

    def test_a_template_with_a_stray_field_cannot_be_planned(self):
        bad = mine_template()
        bad["cards"][0]["launch_mode"] = "full"
        with self.assertRaises(ValueError):
            tp.plan({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")]}, templates={**templates_by_id(), "tm-0123456789ab": bad}, current=current())


if __name__ == "__main__":
    unittest.main()
