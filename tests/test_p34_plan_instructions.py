"""P34-3: the approved plan of automatic mode carries the executor card's instructions.

The block is the first thing in the plan text, names the card it came from, and is part of the text the screen shows,
of its hash and of plan.txt. A flow whose executor has no card, or a card with no instructions, gets the text it always
got, byte for byte. A flow that is already approved reads its own plan.txt and is not touched. No model is started.
"""

from __future__ import annotations

import hashlib
import json
import os

from tests.test_automation_api import AutoApiCase
from vbear import agent_profiles, automation, flows, position_guide


class PlanBlockTests(AutoApiCase):
    TASK = {"title": "T", "goal": "G", "scope": ["a"], "acceptance_criteria": ["c"]}

    def test_without_instructions_the_text_is_what_it_always_was(self):
        plain = "任務：T\n目標：G\n範圍：\n- a\n驗收條件：\n- c"
        self.assertEqual(automation.build_plan_text(self.TASK), plain)
        self.assertEqual(automation.build_plan_text(self.TASK, None), plain)
        self.assertEqual(automation.build_plan_text(self.TASK, {"name": "x", "text": ""}), plain)
        self.assertEqual(automation.build_plan_text(self.TASK, {"name": "x", "text": "  \n "}), plain)

    def test_the_block_comes_first_and_names_the_card(self):
        got = automation.build_plan_text(self.TASK, {"name": "全端工程師", "text": "先寫測試。\n再改程式。"})
        self.assertEqual(got, "職位指示（來自角色卡「全端工程師」）：\n先寫測試。\n再改程式。\n\n"
                              "任務：T\n目標：G\n範圍：\n- a\n驗收條件：\n- c")

    def test_control_characters_are_made_visible_like_the_rest_of_the_text(self):
        got = automation.build_plan_text(self.TASK, {"name": "卡\x01", "text": "指示\x02"})
        self.assertIn("\\u0001", got)
        self.assertIn("\\u0002", got)
        self.assertNotIn("\x01", got)


class PlanApiCase(AutoApiCase):
    def make_card(self, **extra):
        body = {"name": "全端工程師", "model": {"tool": "claude", "model_id": ""},
                "permission_intents": dict(agent_profiles.VERIFIED_INTENTS), "enabled": True, **extra}
        return agent_profiles.save_profile(None, body)

    def put_card(self, profile, *, revision=None):
        roles = json.loads(json.dumps(flows.get_flow(self.fid)["roles"]))
        roles["executor"]["profile_id"] = profile["id"]
        roles["executor"]["profile_snapshot"] = {
            "name": profile["name"], "tool": "claude", "model_id": "",
            "revision": revision or agent_profiles.profile_digest(profile)}
        flows.set_roles(self.fid, {"roles": roles})

    def plain_plan(self):
        return automation.build_plan_text(tasks_get(self.tid))


def tasks_get(tid):
    from vbear import tasks
    return tasks.get_task(tid)


class PreviewTests(PlanApiCase):
    def test_a_flow_whose_executor_has_no_card_is_byte_for_byte_as_before(self):
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        self.assertEqual(pre["plan_text"], self.plain_plan())
        self.assertTrue(pre["plan_text"].startswith("任務："))
        self.assertIsNone(pre["instructions"])

    def test_a_card_with_neither_text_nor_position_adds_nothing(self):
        self.put_card(self.make_card())
        st, pre = self.preview()
        self.assertEqual(pre["plan_text"], self.plain_plan())
        self.assertFalse(pre["instructions"]["included"])
        self.assertEqual(pre["instructions"]["source"], "none")
        self.assertIn("沒有", pre["instructions"]["reason"])

    def test_the_position_default_is_carried_with_the_name_of_the_card(self):
        card = self.make_card(position="executor")
        self.put_card(card)
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        text = position_guide.GUIDE["executor"]["prompt"]
        self.assertTrue(pre["plan_text"].startswith("職位指示（來自角色卡「全端工程師」）：\n" + text + "\n\n任務："), pre["plan_text"])
        self.assertTrue(pre["plan_text"].endswith(self.plain_plan()))
        raw = pre["plan_text"].encode()
        self.assertEqual((pre["plan_sha256"], pre["plan_bytes"]), (hashlib.sha256(raw).hexdigest(), len(raw)))
        ins = pre["instructions"]
        self.assertEqual((ins["included"], ins["profile_id"], ins["name"], ins["source"], ins["position"], ins["length"]),
                         (True, card["id"], "全端工程師", "default", "executor", len(text)))
        self.assertFalse(ins["changed_since_placed"])

    def test_the_cards_own_text_wins_over_the_default(self):
        self.put_card(self.make_card(position="executor", instructions="只改 add.py。"))
        st, pre = self.preview()
        self.assertIn("職位指示（來自角色卡「全端工程師」）：\n只改 add.py。\n\n任務：", pre["plan_text"])
        self.assertNotIn(position_guide.GUIDE["executor"]["prompt"], pre["plan_text"])
        self.assertEqual(pre["instructions"]["source"], "custom")

    def test_a_card_that_changed_since_it_was_placed_is_used_as_it_is_now_and_says_so(self):
        card = self.make_card(position="executor", instructions="舊的")
        self.put_card(card)
        agent_profiles.save_profile(card["id"], {"instructions": "新的"})
        st, pre = self.preview()
        self.assertIn("\n新的\n\n任務：", pre["plan_text"])
        self.assertTrue(pre["instructions"]["changed_since_placed"])

    def test_a_card_that_is_gone_or_a_store_that_cannot_be_read_adds_nothing_and_says_why(self):
        card = self.make_card(position="executor")
        self.put_card(card)
        agent_profiles.delete_profile(card["id"])
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        self.assertEqual(pre["plan_text"], self.plain_plan())
        self.assertFalse(pre["instructions"]["included"])
        self.assertIn("找不到", pre["instructions"]["reason"])
        card = self.make_card(position="executor")
        self.put_card(card)
        agent_profiles._path().write_text("{ not json")
        os.chmod(agent_profiles._path(), 0o600)
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        self.assertEqual(pre["plan_text"], self.plain_plan())
        self.assertFalse(pre["instructions"]["included"])
        self.assertIn("無法讀取", pre["instructions"]["reason"])

    def test_the_longest_instructions_still_fit_the_plan(self):
        self.put_card(self.make_card(instructions="字" * 2000))
        st, pre = self.preview()
        self.assertEqual(st, 200, pre)
        self.assertLess(pre["plan_bytes"], 32 << 10)


class ConfirmTests(PlanApiCase):
    def test_the_plan_file_and_the_acceptance_hold_exactly_the_text_with_the_block(self):
        self.put_card(self.make_card(position="executor", instructions="只改 add.py。"))
        pre, r = self.enable()
        flow = flows.get_flow(self.fid)
        ev = next(e for e in reversed(flow["events"]) if e["kind"] == "risk_acknowledged")
        self.assertEqual((ev["plan_sha256"], ev["plan_bytes"]), (pre["plan_sha256"], pre["plan_bytes"]))
        plan = self.base / "automation" / self.fid / "plan.txt"
        self.assertEqual(plan.read_text(), pre["plan_text"])
        self.assertTrue(plan.read_text().startswith("職位指示（來自角色卡「全端工程師」）：\n只改 add.py。"))
        self.assertEqual(automation.read_plan(self.base, self.fid, sha256=pre["plan_sha256"], size=pre["plan_bytes"]),
                         pre["plan_text"])

    def test_an_approved_flow_keeps_its_plan_when_the_card_is_edited_or_removed_afterwards(self):
        card = self.make_card(position="executor", instructions="核准時的指示")
        self.put_card(card)
        pre, _ = self.enable()
        agent_profiles.save_profile(card["id"], {"instructions": "核准之後才改"})
        agent_profiles.delete_profile(card["id"])
        plan = self.base / "automation" / self.fid / "plan.txt"
        self.assertEqual(plan.read_text(), pre["plan_text"])
        self.assertIn("核准時的指示", plan.read_text())
        self.assertEqual(automation.read_plan(self.base, self.fid, sha256=pre["plan_sha256"], size=pre["plan_bytes"]),
                         pre["plan_text"])
        self.assertEqual(self.mode()["mode"], "auto")

    def test_a_flow_approved_before_cards_had_instructions_runs_as_it_did(self):
        pre, _ = self.enable()                      # no card on the executor: the text it always was
        self.assertEqual(pre["plan_text"], self.plain_plan())
        card = self.make_card(position="executor")
        self.put_card(card)
        plan = self.base / "automation" / self.fid / "plan.txt"
        self.assertEqual(plan.read_text(), self.plain_plan())
        self.assertEqual(self.mode()["mode"], "auto")


if __name__ == "__main__":
    import unittest
    unittest.main()
