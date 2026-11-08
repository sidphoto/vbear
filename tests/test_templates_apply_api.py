"""P45-2: POST /api/templates/apply over a real loopback console with the real stores of the cards, the skills and the routines in a temporary
home. What an apply makes, what it never touches (full mode, skill cards, switched-on routines, memory, the shared folder, config.json, a
chat, the daemon, the ledger, a program), what it checks before it starts, where it stops, and what the record keeps. Every name and text is
made up."""

from __future__ import annotations

import json
import shutil
import unittest
from unittest import mock

from tests import templates_apply_fixtures as fx
from vbear import agent_profiles as ap, routines, server, skillbook, templates as tp, templates_apply as ta
from vbear.api_error import ApiError

pick = fx.pick
BUILTIN = fx.BUILTIN


class TheBuiltInOnesAreMadeAsTheyAre(fx.ApplyBase):
    def check_everything(self, tool):
        status, out = self.apply(self.everything_of(tool))
        self.assertEqual(status, 201, out)
        self.assertTrue(out["ok"])
        apply = out["apply"]
        self.assertEqual((apply["state"], apply["tool"]), ("done", tool))
        return apply

    def test_everything_of_the_four_with_claude_code(self):
        apply = self.check_everything("claude")
        cards = self.stored_cards()
        self.assertEqual(len(cards), 12)
        wanted = {(c["name"], c["position"], c["claude_model"] or "", c["instructions"]) for t in BUILTIN.values() for c in t["cards"]}
        self.assertEqual(len(wanted), 12)
        for card in cards.values():
            self.assertEqual(card["launch_mode"], "safe", "never full mode")
            self.assertEqual(card["equipped_skill_ids"], [], "never a skill card")
            self.assertEqual(card["permission_intents"], ap.VERIFIED_INTENTS)
            self.assertEqual(card["model"]["tool"], "claude")
            self.assertIn((card["name"], card.get("position"), card["model"]["model_id"], card.get("instructions")), wanted)
            self.assertIsNot(card.get("enabled"), False)
            self.assertIsNone(card.get("profession_role_id"))
        skills = self.stored_skills()
        self.assertEqual(len(skills), 12)
        self.assertEqual({s["name"]: s["text"] for s in skills.values()}, {s["name"]: s["text"] for t in BUILTIN.values() for s in t["skills"]})
        self.assertTrue(all(s["source"] == {"how": "typed"} for s in skills.values()))
        made = self.stored_routines()
        self.assertEqual(len(made), 6)
        self.assertTrue(all(r["enabled"] is False and r["enabled_at"] is None for r in made.values()), "every routine is made switched off")
        self.assertEqual(sorted(r["name"] for r in made.values()), sorted(r["name"] for t in BUILTIN.values() for r in t["routines"]))
        for t in BUILTIN.values():
            for r in t["routines"]:
                got = next(x for x in made.values() if x["name"] == r["name"])
                who = next(c["name"] for c in t["cards"] if c["key"] == r["who"])
                self.assertEqual(cards[got["profile_id"]]["name"], who)
                self.assertEqual((got["days"], got["times"], got["text"]), (r["days"], r["times"], r["text"]))
        self.assertEqual(len(apply["items"]), 30)
        self.assert_watched_unchanged()
        self.assert_no_ai_no_chat_no_ledger()

    def test_everything_of_the_four_with_codex(self):
        self.check_everything("codex")
        for card in self.stored_cards().values():
            self.assertEqual(card["model"], {"tool": "codex", "model_id": ""}, "Codex has its own default model")
            self.assertEqual((card["launch_mode"], card["equipped_skill_ids"]), ("safe", []))
        self.assertTrue(all(r["enabled"] is False for r in self.stored_routines().values()))
        self.assert_watched_unchanged()

    def test_the_new_names_are_the_templates_unless_the_person_gave_others(self):
        body = {"tool": "claude", "cards": [pick("shop", "service", name="小客服"), pick("shop", "copy")]}
        status, out = self.apply(body)
        self.assertEqual(status, 201, out)
        self.assertEqual(sorted(c["name"] for c in self.stored_cards().values()), ["商品文案", "小客服"])

    def test_the_apply_touches_no_other_file_than_the_three_stores_and_its_own_record(self):
        before = set(fx.tree(self.state))
        self.make_small()
        added = {name.split("/")[0] for name in set(fx.tree(self.state)) - before}
        self.assertLessEqual(added, {"agent_profiles.json", "agent_profiles.json.lock", "skillbook", "routines", "templates"}, added)
        self.assertNotIn("chats", added)
        self.assertNotIn("chat-work", added)
        self.assert_watched_unchanged()

    def test_what_the_person_already_has_is_not_changed(self):
        mine = ap.save_profile(None, {"name": "老客服", "model": {"tool": "claude"}})
        old_skill = skillbook.add({"name": "舊技能", "text": "舊做法"})["skill"]
        before = (ap.profile_digest(ap.get_profile_readonly(mine["id"])), dict(old_skill))
        self.make_small()
        self.assertEqual((ap.profile_digest(ap.get_profile_readonly(mine["id"])), self.stored_skills()[old_skill["id"]]), before)

    def test_a_routine_can_go_to_an_employee_the_person_already_has_and_he_is_not_changed(self):
        mine = ap.save_profile(None, {"name": "老會計", "model": {"tool": "claude"}})
        digest = ap.profile_digest(ap.get_profile_readonly(mine["id"]))
        status, out = self.apply({"tool": "claude", "routines": [pick("shop", "spend", to={"profile_id": mine["id"]})]})
        self.assertEqual(status, 201, out)
        (made,) = self.stored_routines().values()
        self.assertEqual((made["profile_id"], made["enabled"]), (mine["id"], False))
        self.assertEqual(ap.profile_digest(ap.get_profile_readonly(mine["id"])), digest)

    def test_it_costs_nothing_and_asks_nobody(self):
        self.make_small("codex")
        self.assert_no_ai_no_chat_no_ledger()
        self.assertEqual(self.status_calls, [], "not even the status of the AI tools is looked at")


class TheRecordOfAnApply(fx.ApplyBase):
    def test_every_item_is_recorded_with_its_id_its_template_and_a_fingerprint_of_what_was_made(self):
        apply = self.make_small()
        self.assertRegex(apply["id"], r"^ta-[0-9a-f]{12}$")
        kinds = [i["kind"] for i in apply["items"]]
        self.assertEqual(kinds, ["card", "card", "skill", "skill", "routine", "routine"], "the employees first, then the skills, then the routines")
        self.assertTrue(all("fp" not in i for i in apply["items"]), "no fingerprint goes to the screen")
        record = ta.read_applies()[0]
        self.assertEqual(record["id"], apply["id"])
        cards, skills, made = self.stored_cards(), self.stored_skills(), self.stored_routines()
        for item in record["items"]:
            self.assertEqual(item["state"], "made")
            self.assertEqual(item["from"]["template"], "shop")
            if item["kind"] == "card":
                self.assertEqual(item["fp"], ta.fingerprint("card", ap.get_profile_readonly(item["id"])))
                self.assertIn(item["id"], cards)
            elif item["kind"] == "skill":
                self.assertEqual(item["fp"], ta.fingerprint("skill", skills[item["id"]]))
            else:
                self.assertEqual(item["fp"], ta.fingerprint("routine", made[item["id"]]))

    def test_the_file_and_the_log_have_no_name_and_no_word_of_what_was_made(self):
        self.apply(self.everything_of("claude"))
        raw = (self.state / "templates" / "applies.json").read_text(encoding="utf-8") + (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8")
        for t in BUILTIN.values():
            for kind in ("cards", "skills", "routines"):
                for item in t[kind]:
                    self.assertNotIn(item["name"], raw)
                    for field in ("instructions", "text"):
                        if item.get(field):
                            self.assertNotIn(item[field][:12], raw)
        data = json.loads((self.state / "templates" / "applies.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"v", "applies"})
        lines = [json.loads(x) for x in (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(l["what"], l["counts"]) for l in lines], [("applied", {"cards": 12, "skills": 12, "routines": 6})])

    def test_the_list_shows_the_applies_newest_first_with_the_names_as_they_are_now(self):
        first = self.make_small()
        second = self.apply({"tool": "codex", "skills": [pick("shop", "reply")]})[1]["apply"]
        rows = self.applies()
        self.assertEqual([r["id"] for r in rows], [second["id"], first["id"]])
        row = rows[1]
        self.assertEqual((row["state"], row["tool"], row["undone_at"]), ("done", "claude", None))
        self.assertEqual(row["counts"], {"cards": 2, "skills": 2, "routines": 2})
        self.assertEqual(row["left"], {"cards": 2, "skills": 2, "routines": 2})
        self.assertEqual(sorted(i["name"] for i in row["items"] if i["kind"] == "card"), ["商品文案", "會計"])
        card = next(i for i in row["items"] if i["kind"] == "card")
        ap.save_profile(card["id"], {"name": "改了名字的人"})
        self.assertIn("改了名字的人", [i["name"] for i in self.applies()[1]["items"]], "a name is read from the person's own file each time")
        ap.delete_profile(card["id"])
        self.assertIsNone(next(i for i in self.applies()[1]["items"] if i["id"] == card["id"])["name"])

    def test_the_list_says_when_the_record_cannot_be_read_and_still_shows_the_templates(self):
        self.make_small()
        (self.state / "templates" / "applies.json").write_text("{not json", encoding="utf-8")
        status, out = self.call("/api/templates")
        self.assertEqual(status, 200)
        self.assertEqual(len(out["builtin"]), 4)
        self.assertEqual(out["applies"], [])
        self.assertIn(ta.UNREADABLE, out["problems"])


class TheCheckBeforeAnythingIsMade(fx.ApplyBase):
    def test_over_the_limit_of_skills_nothing_is_made_and_the_numbers_are_said(self):
        for i in range(97):
            skillbook.add({"name": f"技能{i}", "text": f"做法{i}"})
        body = {"tool": "claude", "cards": [pick("shop", "service")],
                "skills": [pick("shop", "reply"), pick("shop", "product"), pick("shop", "daybook"), pick("creator", "ideas"), pick("creator", "post")]}
        status, out = self.apply(body)
        self.assertEqual((status, out["code"]), (409, "template_full"), out)
        self.assertIn("技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個", out["error"])
        self.assertEqual((len(self.stored_cards()), len(self.stored_skills()), len(self.stored_routines())), (0, 97, 0))
        self.assertFalse((self.state / "templates").exists())

    def test_over_the_limit_of_routines_nothing_is_made(self):
        for i in range(19):
            routines.create({"name": f"例行{i}", "profile_id": "p-old", "text": f"做{i}", "days": [0], "times": ["09:00"], "enabled": False}, self.chats.cards())
        status, out = self.apply({"tool": "claude", "cards": [pick("shop", "service")], "routines": [pick("shop", "spend", to={"card": ref_("shop", "service")}), pick("shop", "promo", to={"card": ref_("shop", "service")})]})
        self.assertEqual((status, out["code"]), (409, "template_full"), out)
        self.assertEqual((len(self.stored_cards()), len(self.stored_routines())), (0, 19))

    def test_a_file_that_cannot_be_read_is_a_503_and_nothing_is_made(self):
        for name, folder, code in (("skills", "skillbook", "skills_unreadable"), ("routines", "routines", "routines_unreadable")):
            with self.subTest(name):
                path = self.state / folder
                path.mkdir(mode=0o700)
                (path / f"{name}.json").write_text("{not json", encoding="utf-8")
                status, out = self.apply(self.small_pick())
                self.assertEqual((status, out["code"]), (503, code), out)
                self.assertEqual(self.stored_cards(), {})
                self.assertFalse((self.state / "templates").exists())
                shutil.rmtree(path)

    def test_a_card_file_that_cannot_be_read_is_a_503_and_nothing_is_made(self):
        def broken():
            raise ap.AgentProfileStorageError("x")
        self.chats.cards = broken
        status, out = self.apply(self.small_pick())
        self.assertEqual(status, 503, out)
        self.assertEqual((self.stored_skills(), self.stored_routines()), ({}, {}))
        self.assertFalse((self.state / "templates").exists())

    def test_a_record_that_cannot_be_read_stops_the_apply_before_it_starts(self):
        folder = self.state / "templates"
        folder.mkdir(mode=0o700)
        (folder / "applies.json").write_text("{not json", encoding="utf-8")
        status, out = self.apply(self.small_pick())
        self.assertEqual((status, out["code"]), (503, "applies_unreadable"), out)
        self.assertEqual((self.stored_cards(), self.stored_skills(), self.stored_routines()), ({}, {}, {}))

    def test_what_the_person_can_fix_is_a_400_and_nothing_is_made(self):
        cases = (
            ({"tool": "claude", "cards": [pick("shop", "service", name="   ")]}, "bad_request"),
            ({"tool": "claude", "cards": [pick("shop", "service", name="x" * 41)]}, "bad_request"),
            ({"tool": "claude", "routines": [pick("shop", "spend")]}, "bad_request"),
            ({"tool": "claude", "routines": [pick("shop", "spend", to={"profile_id": "p-off"})]}, "bad_request"),
        )
        for body, code in cases:
            status, out = self.apply(body)
            self.assertEqual((status, out["code"]), (400, code), body)
            self.assertTrue(out["error"])
        self.nothing_made()

    def test_a_bad_request_is_a_400_with_the_same_rules_as_the_preview(self):
        for body in ({}, {"tool": "agy", "cards": [pick("shop", "service")]}, {"tool": "claude", "cards": [pick("nope", "service")]},
                     {"tool": "claude", "cards": [pick("shop", "service"), pick("shop", "service")]}, {"tool": "claude", "extra": 1},
                     {"tool": "claude", "cards": [pick("shop", "service")], "launch_mode": "full"},
                     {"tool": "claude", "cards": [pick("shop", "service", launch_mode="full")]},
                     {"tool": "claude", "skills": [pick("shop", "reply", enabled=True)]},
                     {"tool": "claude", "routines": [pick("shop", "spend", enabled=True, to={"profile_id": "p-old"})]},
                     {"tool": "claude", "cards": [pick("shop", "service")] * 13}):
            status, out = self.apply(body)
            self.assertEqual((status, out["code"]), (400, "bad_request"), body)
        self.assertEqual(self.call("/api/templates/apply", "POST", raw=b"[1, 2]")[0], 400)
        self.assertEqual(self.call("/api/templates/apply", "POST", raw=b"not json")[0], 400)
        self.nothing_made()

    def test_the_marker_and_the_token_are_needed_and_the_route_is_a_post(self):
        body = self.small_pick()
        self.assertEqual(self.apply(body, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.apply(body, headers={"Authorization": None})[0], 401)
        self.assertEqual(self.apply(body, headers={"Origin": "http://evil.example.com"})[0], 403)
        self.assertEqual(self.call("/api/templates/apply")[0], 404)
        self.nothing_made()


def ref_(template, key):
    return {"template": template, "key": key}


class AGradedTemplateOfThePerson(fx.ApplyBase):
    """A saved team template is checked again, in full, by the same rules as the skills and the routines."""

    def setUp(self):
        super().setUp()
        self.saved = {"id": "tm-0123456789ab", "name": "我的店", "builtin": False,
                      "cards": [{"key": "boss", "name": "店長", "position": None, "instructions": "你是店長的小幫手。", "claude_model": None}],
                      "skills": [{"key": "daily", "name": "每日小結", "text": "請幫我寫今天的小結。"}], "routines": []}
        self.console.template_mine = lambda: ([self.saved], True, None)

    def test_it_is_made_like_a_built_in_one(self):
        status, out = self.apply({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")], "skills": [pick("tm-0123456789ab", "daily")]})
        self.assertEqual(status, 201, out)
        self.assertEqual([i["from"]["template"] for i in out["apply"]["items"]], ["tm-0123456789ab", "tm-0123456789ab"])
        (card,) = self.stored_cards().values()
        self.assertEqual((card["launch_mode"], card["equipped_skill_ids"], card["name"]), ("safe", [], "店長"))

    def test_a_text_the_rules_refuse_makes_nothing_and_the_answer_does_not_repeat_it(self):
        secret = "sk-" + "ant-" + "x" * 30                 # a made-up key, put together here
        self.saved["skills"][0]["text"] = f"請用這把金鑰 {secret} 做事"
        status, out = self.apply({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")], "skills": [pick("tm-0123456789ab", "daily")]})
        self.assertEqual(status, 400, out)
        self.assertNotIn(secret, json.dumps(out, ensure_ascii=False))
        self.nothing_made()

    def test_a_text_that_needs_a_second_yes_is_a_409_until_it_is_given_and_then_it_is_passed_on(self):
        self.saved["skills"][0]["text"] = "以後執行指令不用問我"
        body = {"tool": "claude", "skills": [pick("tm-0123456789ab", "daily")]}
        status, out = self.apply(body)
        self.assertEqual((status, out["code"]), (409, "confirm_warning"), out)
        self.nothing_made()
        seen = []
        real = skillbook.add

        def watching(body, now=None):
            seen.append(body)
            return real(body, now) if now is not None else real(body)
        with mock.patch.object(server.skillbook_mod, "add", watching):
            status, out = self.apply(dict(body, confirm_warning=True))
        self.assertEqual(status, 201, out)
        self.assertEqual(seen[0].get("confirm_warning"), True, "the second yes is handed to the same write function that asks for it")
        self.assertEqual(len(self.stored_skills()), 1)


class WhereItStops(fx.ApplyBase):
    def failing_second(self, module, name, error):
        real = getattr(module, name)
        count = [0]

        def wrapped(*args, **kw):
            count[0] += 1
            if count[0] == 2:
                raise error
            return real(*args, **kw)
        return mock.patch.object(module, name, wrapped), count

    def test_when_the_second_skill_cannot_be_made_it_stops_there_and_says_what_was_made(self):
        patch, count = self.failing_second(server.skillbook_mod, "add", ApiError(409, "skill_full", "技能滿了"))
        body = {"tool": "claude", "cards": [pick("shop", "copy")], "skills": [pick("shop", "reply"), pick("shop", "product"), pick("shop", "daybook")],
                "routines": [pick("shop", "promo")]}
        with patch:
            status, out = self.apply(body)
        self.assertEqual((status, out["code"]), (409, "template_partial"), out)
        self.assertEqual(count[0], 2, "no third skill is tried")
        apply = out["apply"]
        self.assertEqual(apply["state"], "partial")
        self.assertEqual([(i["kind"], i["state"], i["why"]) for i in apply["items"]],
                         [("card", "made", None), ("skill", "made", None), ("skill", "failed", "skill_full")], "the routine after it was not tried")
        self.assertEqual((len(self.stored_cards()), len(self.stored_skills()), len(self.stored_routines())), (1, 1, 0))
        self.assertIn("建到一半停下了", out["error"])
        row = self.applies()[0]
        self.assertEqual((row["state"], row["left"]), ("partial", {"cards": 1, "skills": 1, "routines": 0}))

    def test_when_a_routine_cannot_be_made_the_employees_and_skills_stay_made_and_recorded(self):
        patch, _ = self.failing_second(server.routines_mod, "create", ApiError(400, "routine_card", "不能聊天"))
        body = {"tool": "claude", "cards": [pick("shop", "copy"), pick("shop", "accounting")], "routines": [pick("shop", "promo"), pick("shop", "spend")]}
        with patch:
            status, out = self.apply(body)
        self.assertEqual((status, out["code"]), (409, "template_partial"), out)
        self.assertEqual([(i["kind"], i["state"]) for i in out["apply"]["items"]], [("card", "made"), ("card", "made"), ("routine", "made"), ("routine", "failed")])
        self.assertEqual((len(self.stored_cards()), len(self.stored_routines())), (2, 1))

    def test_when_an_employee_cannot_be_made_nothing_after_him_is_tried(self):
        patch, count = self.failing_second(server.agent_profiles, "save_profile", ValueError("角色卡已達上限"))
        with patch:
            status, out = self.apply(self.small_pick())
        self.assertEqual((status, out["code"]), (409, "template_partial"), out)
        self.assertEqual(len(self.stored_cards()), 1)
        self.assertEqual((self.stored_skills(), self.stored_routines()), ({}, {}))
        self.assertEqual([(i["kind"], i["state"]) for i in out["apply"]["items"]], [("card", "made"), ("card", "failed")])

    def test_the_answer_and_the_record_of_a_failure_say_a_code_and_never_the_words_of_the_error(self):
        patch, _ = self.failing_second(server.skillbook_mod, "add", ApiError(400, "skill_refused", "含有 客戶機密名單 的字"))
        with patch:
            self.apply({"tool": "claude", "skills": [pick("shop", "reply"), pick("shop", "product")]})
        raw = (self.state / "templates" / "applies.json").read_text(encoding="utf-8") + (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("客戶機密名單", raw)
        self.assertIn("skill_refused", raw)

    def test_a_console_that_stops_in_the_middle_leaves_a_record_that_the_next_start_closes(self):
        real = ap.save_profile
        count = [0]

        def crash_after_second(*args, **kw):
            count[0] += 1
            made = real(*args, **kw)
            if count[0] == 2:
                raise fx.Crash()
            return made
        with mock.patch.object(ap, "save_profile", crash_after_second):
            self.apply_crash(self.small_pick())
        row = ta.read_applies()[0]
        self.assertEqual(row["state"], "applying")
        self.assertEqual([(i["kind"], i["state"]) for i in row["items"]], [("card", "made"), ("card", "intent")])
        self.assertEqual(len(self.stored_cards()), 2, "the second card was really made before the stop")
        self.assertEqual(self.console.recover_template_applies(), 1)
        row = ta.read_applies()[0]
        self.assertEqual(row["state"], "interrupted")
        second = row["items"][1]
        self.assertEqual((second["state"], second["fp"]), ("made", ta.fingerprint("card", ap.get_profile_readonly(second["id"]))))
        self.assertEqual(self.console.recover_template_applies(), 0, "closed once")

    def test_a_skill_that_may_or_may_not_have_been_made_is_unknown_and_an_undo_never_deletes_it(self):
        real = skillbook.add

        def made_then_crash(body, now=None):
            real(body)
            raise fx.Crash()
        with mock.patch.object(server.skillbook_mod, "add", made_then_crash):
            self.apply_crash({"tool": "claude", "cards": [pick("shop", "copy")], "skills": [pick("shop", "reply")]})
        self.console.recover_template_applies()
        row = ta.read_applies()[0]
        self.assertEqual([(i["kind"], i["state"], i["id"]) for i in row["items"]][1:], [("skill", "unknown", None)])
        status, pv = self.undo_preview(row["id"])
        self.assertEqual(status, 200, pv)
        self.assertEqual([d["kind"] for d in pv["delete"]], ["card"])
        self.assertEqual(pv["unsure"], 1)
        self.assertIn(ta.INTERRUPTED_NOTE, [n["text"] for n in pv["notes"]])
        status, out = self.undo(row["id"], [d["id"] for d in pv["delete"]])
        self.assertEqual(status, 200, out)
        self.assertEqual((len(self.stored_cards()), len(self.stored_skills())), (0, 1), "the skill that may be the person's own stays")


class TheNextApply(fx.ApplyBase):
    def test_the_same_pick_again_makes_another_set_and_both_are_recorded(self):
        first, second = self.make_small(), self.make_small()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.stored_cards()), 4)
        self.assertEqual({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}, set())
        self.assertEqual(len(ta.read_applies()), 2)


if __name__ == "__main__":
    unittest.main()
