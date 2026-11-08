"""P45-4: one walk through the team templates over the real routes of a loopback server, from the list to the last undo.

The person looks at the four built-in team templates, ticks things from two of them, previews (nothing is written), applies with Claude Code
(three employees, three skills, two routines, all of them made the ordinary way: safe mode, no skill card, every routine switched off), talks
to one employee (the chat service of the test writes the record a chat leaves), changes one skill, asks what 復原這次套用 would do (the
employee who was talked to and the skill that was changed stay, and the other employee stays because a routine that stays still goes to
him), presses 「刪掉這些」, saves the employee and the skill as the person's own team template, applies that one and undoes it at once
(nothing was changed or used, so everything it made goes). ``config.json``, the memory and the shared folder's switches are the same bytes
at the end as at the start, no AI, no daemon and no program was asked for anything, and neither the record of the applies nor the log has a
name or a word of what was made.

Seams: the HTTP routes ``/api/templates*``, ``/api/my-skills*``, ``/api/routines*``, ``/api/agent-profiles*`` and the files a person could look
at in the state folder. The chat service is a fake that lists the role cards and writes the one file a chat leaves behind; the daemon, the
meetings' ledger and every program are traps; the status of the AI tools is a fake. Every name here is made up."""

from __future__ import annotations

import json
import unittest

from tests import templates_apply_fixtures as fx
from vbear import agent_profiles as ap

pick = fx.pick


class Walk(fx.ApplyBase):
    def talk_to(self, profile_id, chat_id="c-0123456789abcdef"):
        """The person chats with an employee: what a chat leaves in the state folder is its record, which names the employee."""
        self.put(f"chats/{chat_id}/chat.json", {"id": chat_id, "profile_id": profile_id})

    def good(self, path, method="GET", body=None, status=(200, 201)):
        code, out = self.call(path, method, body)
        self.assertIn(code, status, (path, code, out))
        return out

    def names_in(self, path):
        raw = (self.state / "templates" / path).read_text(encoding="utf-8")
        words = []
        for t in fx.BUILTIN.values():
            for kind in ("cards", "skills", "routines"):
                for item in t[kind]:
                    words.append(item["name"])
                    words.extend(item[f][:12] for f in ("instructions", "text") if item.get(f))
        return [w for w in words if w in raw]

    def test_from_the_list_to_the_last_undo(self):
        # 1. the list: four built-in team templates, none of the person's own, no apply yet; nothing is on
        listed = self.good("/api/templates")
        self.assertEqual([t["id"] for t in listed["builtin"]], ["shop", "creator", "studio", "life"])
        self.assertEqual((listed["mine"], listed["applies"], listed["problems"]), ([], [], []))
        self.assertEqual(listed["counts"], {"cards": 2, "skills": 0, "routines": 0}, "the two employees the test's chat service already lists")
        for t in listed["builtin"]:
            self.assertTrue(all(r.get("enabled") is not True for r in t["routines"]), "no routine of a team template is on")
            self.assertTrue(all(set(c) == {"key", "name", "position", "instructions", "claude_model"} for c in t["cards"]), "an employee has no tool, mode, switch or id")

        # 2. a mix of two team templates; the preview says what would be made and writes nothing
        body = {"tool": "claude",
                "cards": [pick("shop", "service"), pick("shop", "copy"), pick("shop", "accounting"), pick("creator", "writer")],
                "skills": [pick("shop", "product"), pick("shop", "daybook"), pick("creator", "short")],
                "routines": [pick("shop", "promo"), pick("shop", "spend")]}
        before = fx.tree(self.state)
        status, shown = self.call("/api/templates/preview", "POST", body)
        self.assertEqual(status, 200, shown)
        preview = shown["preview"]
        self.assertTrue(preview["ok"], preview["problems"])
        self.assertEqual((len(preview["cards"]), len(preview["skills"]), len(preview["routines"])), (4, 3, 2))
        self.assertEqual(fx.tree(self.state), before, "the preview wrote nothing")
        self.assertEqual((self.stored_cards(), self.stored_skills(), self.stored_routines()), ({}, {}, {}))

        # 3. the apply: 201, made the ordinary way, switched on nothing, asked nobody
        status, out = self.apply(body)
        self.assertEqual(status, 201, out)
        apply = out["apply"]
        self.assertEqual((apply["state"], apply["tool"]), ("done", "claude"))
        cards, skills, routines = self.stored_cards(), self.stored_skills(), self.stored_routines()
        self.assertEqual((len(cards), len(skills), len(routines)), (4, 3, 2))
        for card in cards.values():
            self.assertEqual((card["launch_mode"], card["equipped_skill_ids"], card["model"]["tool"]), ("safe", [], "claude"))
            self.assertIsNot(card.get("enabled"), False)
        self.assertTrue(all(s["source"] == {"how": "typed"} for s in skills.values()))
        self.assertTrue(all(r["enabled"] is False and r["enabled_at"] is None for r in routines.values()), "every routine was made switched off")
        self.assert_watched_unchanged()
        self.assert_no_ai_no_chat_no_ledger()
        service, copy_, writer = (self.id_named("card", n) for n in ("客服", "商品文案", "寫稿"))
        self.assertEqual(self.id_named("card", "會計") in cards, True)

        # 4. the person talks to the customer service, changes the skill 「寫商品介紹」 and the words of the routine 「想下週的促銷」
        self.talk_to(service)
        skill = self.id_named("skill", "寫商品介紹")
        text = skills[skill]["text"] + "（虛構的修改）"
        self.good(f"/api/my-skills/{skill}", "POST", {"name": skills[skill]["name"], "text": text})
        promo = self.id_named("routine", "想下週的促銷")
        self.good(f"/api/routines/{promo}", "POST", {"text": routines[promo]["text"] + "（虛構的修改）"})

        # 5. what 復原這次套用 would do: nothing is written
        before = fx.tree(self.state)
        status, plan = self.undo_preview(apply["id"])
        self.assertEqual(status, 200, plan)
        kept = {k["id"]: k["why"] for k in plan["keep"]}
        deleted = {d["id"] for d in plan["delete"]}
        self.assertEqual(kept[service], "chatted")
        self.assertEqual(kept[skill], "changed")
        self.assertEqual(kept[promo], "changed")
        self.assertEqual(kept[copy_], "routine_kept", "the routine that stays still goes to him")
        self.assertIn(self.id_named("routine", "整理昨天的花費"), deleted, "this routine was not changed and has no run")
        self.assertIn(self.id_named("card", "會計"), deleted)
        self.assertIn(writer, deleted)
        self.assertEqual({n["code"] for n in plan["notes"]}, {"terminal", "skills"}, "the two fixed reminders: VBear cannot see a terminal, and does not record that a skill was used")
        self.assertEqual(fx.tree(self.state), before, "the preview of the undo wrote nothing")

        # 6. 刪掉這些: only what the preview listed and is still free goes, routines first
        status, done = self.undo(apply["id"], sorted(deleted))
        self.assertEqual(status, 200, done)
        self.assertEqual({d["id"] for d in done["deleted"]}, deleted)
        order = [d["kind"] for d in done["deleted"]]
        self.assertEqual(order, sorted(order, key=("routine", "skill", "card").index), "routines, then skills, then employees")
        self.assertEqual({k["id"] for k in done["kept"]}, set(kept))
        self.assertIn(service, self.stored_cards())
        self.assertIn(copy_, self.stored_cards())
        self.assertIn(skill, self.stored_skills())
        self.assertEqual(self.stored_skills()[skill]["text"], text, "what the person wrote is as it was")
        status, again = self.undo_preview(apply["id"])
        self.assertEqual(again["delete"], [], "nothing more can go")

        # 7. the person's own team template: the customer service and the skill, as they are now
        status, saved = self.call("/api/templates/mine", "POST", {"name": "我的虛構店", "cards": [{"profile_id": service}], "skills": [{"skill_id": skill}]})
        self.assertEqual(status, 201, saved)
        mine = saved["template"]
        self.assertEqual(set(mine["cards"][0]), {"key", "name", "position", "instructions", "claude_model"})
        self.assertEqual(mine["skills"][0]["text"], text)
        self.assertEqual(self.good("/api/templates")["mine"], [mine])
        raw = (self.state / "templates" / "mine.json").read_text(encoding="utf-8")
        for word in ("launch_mode", "safe", "tool", "equipped_skill_ids", "permission_intents", service, skill):
            self.assertNotIn(word, raw, word)

        # 8. apply it (a new employee and a new skill with the same words) and undo it at once: nothing was changed or used, so both go
        status, out = self.apply({"tool": "claude", "cards": [pick(mine["id"], mine["cards"][0]["key"])], "skills": [pick(mine["id"], mine["skills"][0]["key"])]})
        self.assertEqual(status, 201, out)
        again_id = out["apply"]["id"]
        new_cards = set(self.stored_cards()) - {service, copy_}
        self.assertEqual(len(new_cards), 1)
        (new_card,) = new_cards
        self.assertEqual(self.stored_cards()[new_card]["launch_mode"], "safe")
        status, plan = self.undo_preview(again_id)
        self.assertEqual((len(plan["delete"]), plan["keep"]), (2, []))
        status, done = self.undo(again_id, [d["id"] for d in plan["delete"]])
        self.assertEqual((status, len(done["deleted"]), done["kept"]), (200, 2, []))
        self.assertNotIn(new_card, self.stored_cards())
        self.assertIn(service, self.stored_cards(), "the employee the person already had was not touched")

        # 9. the end: the same bytes, no AI, no program, no name or word in the record or the log, every routine off, the applies listed
        self.assert_watched_unchanged()
        self.assert_no_ai_no_chat_no_ledger()
        self.assertTrue(all(r["enabled"] is False for r in self.stored_routines().values()))
        self.assertEqual(self.names_in("applies.json"), [])
        self.assertEqual(self.names_in("log.jsonl"), [])
        self.assertEqual(len(self.applies()), 2)
        what = [json.loads(x)["what"] for x in (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(set(what)), ["applied", "saved_mine", "undo"])

    def test_the_same_walk_with_codex_makes_codex_employees_that_are_just_as_safe(self):
        status, out = self.apply({"tool": "codex", "cards": [pick("life", "schedule")], "skills": [pick("life", "month")], "routines": [pick("life", "today")]})
        self.assertEqual(status, 201, out)
        (card,) = self.stored_cards().values()
        self.assertEqual((card["model"], card["launch_mode"], card["equipped_skill_ids"]), ({"tool": "codex", "model_id": ""}, "safe", []))
        (routine,) = self.stored_routines().values()
        self.assertFalse(routine["enabled"])
        status, plan = self.undo_preview(out["apply"]["id"])
        self.assertEqual(len(plan["delete"]), 3)
        self.undo(out["apply"]["id"], [d["id"] for d in plan["delete"]])
        self.assertEqual((self.stored_cards(), self.stored_skills(), self.stored_routines()), ({}, {}, {}))
        self.assert_watched_unchanged()
        self.assert_no_ai_no_chat_no_ledger()

    def test_there_is_no_route_that_takes_a_team_template_out_of_this_computer(self):
        for path in ("/api/templates/export", "/api/templates/import", "/api/templates/mine/tm-000000000000/export", "/api/templates/upload", "/api/templates/download"):
            for method in ("GET", "POST"):
                status, _ = self.call(path, method, {} if method == "POST" else None)
                self.assertIn(status, (400, 404), (method, path))


if __name__ == "__main__":
    unittest.main()
