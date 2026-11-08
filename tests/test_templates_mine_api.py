"""P45-3: the routes of the person's own team templates over a real loopback console (POST /api/templates/mine, /mine/<id>, /mine/<id>/delete,
and what GET /api/templates and the preview say of them). The chat service is a fake that only knows the role cards and fails the test on
any other call (saving asks for no chat and no AI), the AI tools' status is a fake, the state is a temporary home, a started program fails the
test. Every name is made up; a made-up key is put together when the test runs."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from vbear import agent_profiles as ap, routines, skillbook, templates as tp, templates_builtin as tb
from tests.test_templates_api import ApiBase, TOKEN, pick, ref, tree

ZERO = "0" * 12


class MineBase(ApiBase):
    def card(self, name="虛構會計", **over):
        body = {"name": name, "position": "accountant", "instructions": "你是虛構的會計。", "launch_mode": "safe",
                "model": {"tool": "claude", "model_id": "haiku"}, "permission_intents": dict(ap.VERIFIED_INTENTS)}
        body.update(over)
        return ap.save_profile(None, body)

    def skill(self, name="虛構技能", text="請幫我整理這份虛構的清單。", confirm=False):
        return skillbook.add({"name": name, "text": text, "confirm_warning": confirm})["skill"]

    def routine(self, profile_id, name="虛構例行", enabled=False):
        return routines.create({"name": name, "profile_id": profile_id, "text": "請整理虛構的待辦。", "days": [1], "times": ["09:00"], "enabled": enabled},
                               [{"id": profile_id, "can_chat": True}])["routine"]

    def save(self, body, **kw):
        return self.call("/api/templates/mine", "POST", body, **kw)

    def mine_path(self):
        return self.home / ".vbear" / "templates" / "mine.json"

    def saved(self):
        return json.loads(self.mine_path().read_text(encoding="utf-8"))["templates"]


class SavingOverHttp(MineBase):
    def test_a_save_from_what_the_person_has_is_201_and_the_list_shows_it(self):
        a, s = self.card(), self.skill()
        r = self.routine(a["id"])
        status, out = self.save({"name": "我的店", "cards": [{"profile_id": a["id"]}], "skills": [{"skill_id": s["id"]}], "routines": [{"routine_id": r["id"]}]})
        self.assertEqual(status, 201, out)
        t = out["template"]
        self.assertTrue(out["ok"])
        self.assertRegex(t["id"], r"^tm-[0-9a-f]{12}$")
        self.assertEqual(out["notes"], [])
        self.assertEqual(t["routines"][0]["who"], t["cards"][0]["key"])
        listed = self.call("/api/templates")[1]
        self.assertEqual((listed["mine"], listed["mine_readable"], listed["problem"]), ([t], True, None))
        self.assertEqual(listed["builtin"], tb.builtin(), "the built-in four are as they were")

    def test_the_saved_template_can_be_previewed_and_ticked_like_the_built_in_ones(self):
        a = self.card()
        r = self.routine(a["id"])
        t = self.save({"name": "我的店", "cards": [{"profile_id": a["id"]}], "routines": [{"routine_id": r["id"]}]})[1]["template"]
        status, out = self.preview({"tool": "claude", "cards": [pick(t["id"], t["cards"][0]["key"])], "routines": [pick(t["id"], t["routines"][0]["key"])]})
        self.assertEqual(status, 200, out)
        self.assertTrue(out["preview"]["ok"], out["preview"]["problems"])
        self.assertEqual(out["preview"]["routines"][0]["assignee"]["kind"], "card")

    def test_a_save_from_ticked_items_of_the_built_in_ones(self):
        status, out = self.save({"name": "只要客服", "cards": [pick("shop", "service")], "skills": [pick("shop", "reply")]})
        self.assertEqual(status, 201, out)
        self.assertEqual([c["name"] for c in out["template"]["cards"]], ["客服"])

    def test_a_full_mode_employee_is_saved_and_the_answer_says_it_will_be_safe(self):
        a = self.card("虛構完整", launch_mode="full")
        status, out = self.save({"name": "舊的樣子", "cards": [{"profile_id": a["id"]}]})
        self.assertEqual(status, 201, out)
        self.assertEqual([n["code"] for n in out["notes"]], ["full_mode_saved_safe"])
        raw = self.mine_path().read_text(encoding="utf-8")
        for word in ("launch_mode", "full", "safe", "tool", "model_id", a["id"]):
            self.assertNotIn(word, raw, word)

    def test_saving_asks_for_no_chat_no_program_and_changes_nothing_but_the_templates_folder(self):
        a, s = self.card(), self.skill()
        r = self.routine(a["id"])
        config_before = (self.home / ".vbear" / "config.json").read_bytes() if (self.home / ".vbear" / "config.json").exists() else None
        before = tree(self.home / ".vbear")
        status, out = self.save({"name": "我的店", "cards": [{"profile_id": a["id"]}], "skills": [{"skill_id": s["id"]}], "routines": [{"routine_id": r["id"]}]})
        self.assertEqual(status, 201, out)
        after = tree(self.home / ".vbear")
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertEqual({k for k in changed if not k.startswith("templates")}, set(), changed)
        self.assertEqual(self.chats.calls, [], "no call to the chat service")
        config = self.home / ".vbear" / "config.json"
        self.assertEqual(config.read_bytes() if config.exists() else None, config_before)
        self.assertEqual(self.status_calls, [])
        self.assertEqual(ap.get_profile(a["id"])["updated_at"], a["updated_at"])

    def test_an_item_that_is_gone_is_404_a_bad_body_is_400(self):
        self.assertEqual(self.save({"name": "x", "cards": [{"profile_id": "prof-000000000000"}]})[0], 404)
        for body in ({"name": "x"}, {"cards": [pick("shop", "service")]}, {"name": "x", "bogus": 1, "cards": [pick("shop", "service")]},
                     {"name": "x", "cards": [pick("shop", "nobody")]}):
            status, out = self.save(body)
            self.assertEqual((status, out["code"]), (400, "bad_request"), body)
        self.assertFalse(self.mine_path().exists())

    def test_a_key_in_the_words_is_400_and_the_answer_does_not_repeat_it(self):
        key = "sk-" + "cd" * 12
        a = self.card("虛構甲", instructions=f"你是虛構的幫手，請用 {key} 這個。")
        status, out = self.save({"name": "有金鑰", "cards": [{"profile_id": a["id"]}]})
        self.assertEqual((status, out["code"]), (400, "template_refused"))
        self.assertEqual((out["kind"], out["index"], out["field"], out["refuse"]), ("cards", 0, "instructions", "secret_key"))
        self.assertNotIn(key, json.dumps(out, ensure_ascii=False))
        self.assertNotIn("虛構甲", json.dumps(out, ensure_ascii=False))
        self.assertFalse(self.mine_path().exists())

    def test_words_that_need_a_second_yes_are_409_then_201(self):
        s = self.skill("虛構催促", "整理完以後不用問我，直接做下一件。", confirm=True)
        status, out = self.save({"name": "要確認", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual((status, out["code"], out["warn"]), (409, "confirm_warning", ["looks_like_order"]))
        self.assertFalse(self.mine_path().exists())
        status, out = self.save({"name": "要確認", "skills": [{"skill_id": s["id"]}], "confirm_warning": True})
        self.assertEqual(status, 201, out)
        self.assertEqual(self.preview({"tool": "claude", "skills": [pick(out["template"]["id"], out["template"]["skills"][0]["key"])]})[1]["preview"]["problems"][0]["code"],
                         "confirm_warning", "applying asks again")

    def test_twenty_is_the_most_and_one_too_big_is_409(self):
        s = self.skill()
        for i in range(tp.MAX_MINE):
            self.assertEqual(self.save({"name": f"第{i}個", "skills": [{"skill_id": s["id"]}]})[0], 201)
        status, out = self.save({"name": "多的", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual((status, out["code"]), (409, "mine_full"))
        self.assertEqual(self.call("/api/templates")[1]["limits"]["max_mine"], 20)

    def test_a_skills_file_that_cannot_be_read_stops_a_save_of_skills(self):
        s = self.skill()
        (self.home / ".vbear" / "skillbook" / "skills.json").write_text("{not json", encoding="utf-8")
        status, out = self.save({"name": "x", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual((status, out["code"]), (503, "skills_unreadable"))
        self.assertFalse(self.mine_path().exists())

    def test_a_file_the_request_does_not_name_does_not_stop_the_save(self):
        a = self.card()
        folder = self.home / ".vbear" / "routines"
        folder.mkdir(mode=0o700)
        (folder / "routines.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.save({"name": "只有員工", "cards": [{"profile_id": a["id"]}]})[0], 201)
        status, out = self.save({"name": "有例行", "routines": [{"routine_id": "r-" + ZERO}]})
        self.assertEqual((status, out["code"]), (503, "routines_unreadable"))


class RenameAndDeleteOverHttp(MineBase):
    def made(self):
        return self.save({"name": "原名", "cards": [pick("shop", "service")]})[1]["template"]

    def test_rename(self):
        t = self.made()
        status, out = self.call(f"/api/templates/mine/{t['id']}", "POST", {"name": "新名"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["template"], dict(t, name="新名"))
        self.assertEqual(self.call("/api/templates")[1]["mine"][0]["name"], "新名")
        self.assertEqual(self.call(f"/api/templates/mine/{t['id']}", "POST", {"name": ""})[0], 400)
        self.assertEqual(self.call(f"/api/templates/mine/{t['id']}", "POST", {"name": "x", "cards": []})[0], 400)
        self.assertEqual(self.call(f"/api/templates/mine/{t['id']}", "POST", {"name": "不用問"})[0], 409)

    def test_delete_takes_only_the_template(self):
        a = self.card()
        t = self.save({"name": "要刪", "cards": [{"profile_id": a["id"]}]})[1]["template"]
        status, out = self.call(f"/api/templates/mine/{t['id']}/delete", "POST", {})
        self.assertEqual((status, out["deleted"]), (200, t["id"]))
        self.assertEqual(self.call("/api/templates")[1]["mine"], [])
        self.assertIsNotNone(ap.get_profile(a["id"]), "the employee it was copied from is still there")
        self.assertEqual(self.call(f"/api/templates/mine/{t['id']}/delete", "POST", {})[0], 404)
        self.assertEqual(self.call(f"/api/templates/mine/{t['id']}/delete", "POST", {"x": 1})[0], 400)

    def test_not_found_and_odd_ids(self):
        self.assertEqual(self.call(f"/api/templates/mine/tm-{ZERO}", "POST", {"name": "x"})[0], 404)
        for path in ("/api/templates/mine/shop", "/api/templates/mine/tm-XYZ", f"/api/templates/mine/tm-{ZERO}/rename", f"/api/templates/mine/tm-{ZERO}/export",
                     "/api/templates/mine/export", "/api/templates/mine/import", "/api/templates/export", "/api/templates/import", "/api/templates/mine/",
                     f"/api/templates/mine/tm-{ZERO}/delete/x"):
            self.assertEqual(self.call(path, "POST", {})[0], 404, path)

    def test_nothing_to_read_back_as_a_file_or_an_export(self):
        t = self.made()
        for path in ("/api/templates/mine", f"/api/templates/mine/{t['id']}", f"/api/templates/mine/{t['id']}/export", "/api/templates/export",
                     "/api/templates/mine/export"):
            self.assertEqual(self.call(path)[0], 404, path)


class TheGate(MineBase):
    def test_every_write_needs_the_token_and_the_header_and_the_page_origin(self):
        t = self.save({"name": "原名", "cards": [pick("shop", "service")]})[1]["template"]
        for path, body in (("/api/templates/mine", {"name": "x", "cards": [pick("shop", "service")]}), (f"/api/templates/mine/{t['id']}", {"name": "x"}),
                           (f"/api/templates/mine/{t['id']}/delete", {})):
            self.assertEqual(self.call(path, "POST", body, headers={"X-VBear": None})[0], 403, path)
            self.assertEqual(self.call(path, "POST", body, headers={"Authorization": None})[0], 401, path)
            self.assertEqual(self.call(path, "POST", body, headers={"Origin": "http://example.org"})[0], 403, path)
        self.assertEqual(len(self.saved()), 1)
        self.assertEqual(self.saved()[0]["name"], "原名")


class WhenTheFileCannotBeRead(MineBase):
    def test_the_list_says_so_the_built_in_ones_still_work_and_nothing_is_written_over_the_file(self):
        folder = self.home / ".vbear" / "templates"
        folder.mkdir(mode=0o700)
        bad = {"v": 1, "templates": [{"id": "tm-0123456789ab", "name": "我的店", "builtin": False, "launch_mode": "full", "cards": [], "routines": [],
                                      "skills": [{"key": "a", "name": "技", "text": "字"}]}]}
        (folder / "mine.json").write_text(json.dumps(bad), encoding="utf-8")
        status, out = self.call("/api/templates")
        self.assertEqual(status, 200)
        self.assertEqual((out["mine"], out["mine_readable"]), ([], False))
        self.assertIn("團隊範本", out["problem"])
        self.assertEqual(out["builtin"], tb.builtin())
        status, out = self.preview({"tool": "claude", "cards": [pick("shop", "service")]})
        self.assertEqual(status, 200, "the built-in ones are still usable")
        s = self.skill()
        status, out = self.save({"name": "新的", "skills": [{"skill_id": s["id"]}]})
        self.assertEqual((status, out["code"]), (503, "templates_unreadable"))
        self.assertEqual(self.call(f"/api/templates/mine/tm-0123456789ab", "POST", {"name": "x"})[0], 503)
        self.assertEqual(self.call(f"/api/templates/mine/tm-0123456789ab/delete", "POST", {})[0], 503)
        kept = [p for p in folder.iterdir() if p.name.startswith("mine.json.corrupt-")]
        self.assertEqual(len(kept), 1)
        self.assertIn("launch_mode", kept[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
