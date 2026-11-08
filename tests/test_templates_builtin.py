"""P45-1: the four built-in team templates (vbear/templates_builtin.py). The words are the plan's, letter for letter
(runs/20261108-p45/plan.md, 「四個內建範本的完整內容」). The plan is the spec; this file does not read it. It holds what the plan says
in plain tables (names, positions, models, who gets which routine, the days and the time) and the SHA-256 of every long text, worked out
from the plan once, so a changed word is found without this file repeating all the words. Nothing here writes a file."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import unittest

from vbear import agent_profiles, model_options, templates_builtin as tb
from vbear.runtime import agent_sessions, memory_rules
from vbear import routine_rules

EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]

# (id, name, [(key, name, position, claude model)], [(key, name)], [(key, name, who, days, times)])
SHAPE = (
    ("shop", "小店",
     [("service", "客服", None, "haiku"), ("copy", "商品文案", "social", "sonnet"), ("accounting", "會計", "accountant", "haiku")],
     [("reply", "回覆客人詢問"), ("product", "寫商品介紹"), ("daybook", "整理一天的帳")],
     [("spend", "整理昨天的花費", "accounting", EVERY_DAY, ["09:00"]), ("promo", "想下週的促銷", "copy", [4], ["10:00"])]),
    ("creator", "自媒體",
     [("topics", "選題", None, "sonnet"), ("writer", "寫稿", "social", "sonnet"), ("editor", "社群編輯", "social", "haiku")],
     [("ideas", "找選題"), ("post", "寫一篇貼文草稿"), ("short", "改成短影音腳本")],
     [("news", "整理新聞選題", "topics", EVERY_DAY, ["08:30"]), ("week", "排下週內容", "editor", [6], ["19:00"])]),
    ("studio", "接案工作室",
     [("assistant", "專案助理", "pm", "haiku"), ("contract", "報價與合約草稿", "legal", "sonnet"), ("accounting", "會計", "accountant", "haiku")],
     [("quote", "寫報價單草稿"), ("minutes", "整理會議紀錄"), ("terms", "列合約要注意的地方")],
     [("todo", "整理本週待辦", "assistant", [0], ["09:00"])]),
    ("life", "個人生活助理",
     [("schedule", "行程助理", "pm", "haiku"), ("coach", "學習教練", None, "sonnet"), ("money", "記帳", "accountant", "haiku")],
     [("plan_week", "排一週行程"), ("study", "做學習計畫"), ("month", "整理這個月的花費")],
     [("today", "排今天的事", "schedule", EVERY_DAY, ["07:30"])]),
)

ABOUT = {
    "shop": "一個人開網路或實體小店：回覆客人、寫商品介紹、記帳。",
    "creator": "經營粉專、IG 或 YouTube 的個人創作者：找題目、寫稿、排社群內容。",
    "studio": "一個人或小團隊接案：追專案進度、寫報價和合約草稿、記帳。",
    "life": "打理自己的生活：排行程、安排學習、記帳。",
}

# first 16 hex digits of the SHA-256 of each text (a card's instructions, a skill's words, a routine's words)
DIGESTS = {
    ("shop", "card", "service"): "adb5f0bfb15a1aa5",
    ("shop", "card", "copy"): "6948ca5ae46a113f",
    ("shop", "card", "accounting"): "f84a98c5c1499c67",
    ("shop", "skill", "reply"): "5cb0704da5654aaa",
    ("shop", "skill", "product"): "ab570c302343ba17",
    ("shop", "skill", "daybook"): "400818ef2f3f5192",
    ("shop", "routine", "spend"): "5a095dac1c63aac3",
    ("shop", "routine", "promo"): "bed6f5476b375acc",
    ("creator", "card", "topics"): "d7b7405a368c24a3",
    ("creator", "card", "writer"): "1b849b36c654309a",
    ("creator", "card", "editor"): "d10b9d4b6ad4e63e",
    ("creator", "skill", "ideas"): "b0ef84442261ab0e",
    ("creator", "skill", "post"): "4e4efffe3a0d5f17",
    ("creator", "skill", "short"): "723fe2387f527a99",
    ("creator", "routine", "news"): "b7ffdf6d1fc7e99e",
    ("creator", "routine", "week"): "d32207ea436ebc23",
    ("studio", "card", "assistant"): "8f91f529859ad053",
    ("studio", "card", "contract"): "9640e21573ade7e7",
    ("studio", "card", "accounting"): "acdf1d3db126c513",
    ("studio", "skill", "quote"): "1775f2d4aa18e58f",
    ("studio", "skill", "minutes"): "a59ffdf08ac0feb4",
    ("studio", "skill", "terms"): "8e2871a7df0368e4",
    ("studio", "routine", "todo"): "1e9b1b0cae6f9d60",
    ("life", "card", "schedule"): "5ae43d48f47f0559",
    ("life", "card", "coach"): "c1f5680570bb0d00",
    ("life", "card", "money"): "af2d943c0b9562e9",
    ("life", "skill", "plan_week"): "1d8ea826771ecef7",
    ("life", "skill", "study"): "0caee87e31591a87",
    ("life", "skill", "month"): "8bc51545e849551f",
    ("life", "routine", "today"): "5a3dc4bebeb52987",
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def texts(template: dict):
    """(kind, key, field, text) for every word a template holds."""
    for c in template["cards"]:
        yield "card", c["key"], "name", c["name"]
        yield "card", c["key"], "instructions", c["instructions"]
    for s in template["skills"]:
        yield "skill", s["key"], "name", s["name"]
        yield "skill", s["key"], "text", s["text"]
    for r in template["routines"]:
        yield "routine", r["key"], "name", r["name"]
        yield "routine", r["key"], "text", r["text"]


class BuiltinContent(unittest.TestCase):
    def setUp(self):
        self.templates = tb.builtin()

    def test_the_four_templates_in_the_order_of_the_plan(self):
        self.assertEqual([t["id"] for t in self.templates], ["shop", "creator", "studio", "life"])
        self.assertEqual(tb.BUILTIN_IDS, ("shop", "creator", "studio", "life"))
        self.assertTrue(all(t["builtin"] is True for t in self.templates))

    def test_names_about_and_the_shape_of_each(self):
        for t, (tid, name, cards, skills, routines) in zip(self.templates, SHAPE):
            self.assertEqual((t["id"], t["name"], t["about"]), (tid, name, ABOUT[tid]))
            self.assertEqual([(c["key"], c["name"], c["position"], c["claude_model"]) for c in t["cards"]], cards, tid)
            self.assertEqual([(s["key"], s["name"]) for s in t["skills"]], skills, tid)
            self.assertEqual([(r["key"], r["name"], r["who"], r["days"], r["times"]) for r in t["routines"]], routines, tid)
            self.assertEqual(set(t), {"id", "name", "about", "builtin", "cards", "skills", "routines"})
            for c in t["cards"]:
                self.assertEqual(set(c), {"key", "name", "position", "instructions", "claude_model"})
            for s in t["skills"]:
                self.assertEqual(set(s), {"key", "name", "text"})
            for r in t["routines"]:
                self.assertEqual(set(r), {"key", "name", "text", "days", "times", "who"})

    def test_all_four_together_are_12_employees_12_skills_and_6_routines(self):
        self.assertEqual((sum(len(t["cards"]) for t in self.templates), sum(len(t["skills"]) for t in self.templates),
                          sum(len(t["routines"]) for t in self.templates)), (12, 12, 6))

    def test_every_long_text_is_the_plans_letter_for_letter(self):
        seen = set()
        for t in self.templates:
            for c in t["cards"]:
                seen.add((t["id"], "card", c["key"]))
                self.assertEqual(digest(c["instructions"]), DIGESTS[(t["id"], "card", c["key"])], f"{t['id']} card {c['key']}")
            for s in t["skills"]:
                seen.add((t["id"], "skill", s["key"]))
                self.assertEqual(digest(s["text"]), DIGESTS[(t["id"], "skill", s["key"])], f"{t['id']} skill {s['key']}")
            for r in t["routines"]:
                seen.add((t["id"], "routine", r["key"]))
                self.assertEqual(digest(r["text"]), DIGESTS[(t["id"], "routine", r["key"])], f"{t['id']} routine {r['key']}")
        self.assertEqual(seen, set(DIGESTS))

    def test_a_few_words_by_eye(self):
        shop = self.templates[0]
        self.assertTrue(shop["cards"][0]["instructions"].startswith("你是這家小店的客服助理，幫店主草擬回覆客人的訊息。"))
        self.assertTrue(shop["skills"][0]["text"].startswith("請幫我回覆下面這則客人的訊息。\n1. 先用一句話說你理解客人在問什麼。"))
        self.assertTrue(shop["skills"][0]["text"].endswith("商品資訊與規定：\n（貼在這裡）"))
        self.assertTrue(shop["routines"][0]["text"].endswith("最後用三句話說昨天有什麼值得注意的地方。"))
        self.assertEqual(self.templates[3]["routines"][0]["text"][:12], "請幫我排今天的事。如果你")

    def test_keys_are_unique_inside_a_template_and_a_kind_and_who_points_at_a_card_of_the_same_template(self):
        for t in self.templates:
            for kind in ("cards", "skills", "routines"):
                keys = [x["key"] for x in t[kind]]
                self.assertEqual(len(keys), len(set(keys)), (t["id"], kind))
                self.assertTrue(all(re.match(r"^[a-z][a-z0-9_]{0,23}\Z", k) for k in keys), keys)
            card_keys = {c["key"] for c in t["cards"]}
            self.assertTrue(all(r["who"] in card_keys for r in t["routines"]), t["id"])

    def test_every_word_passes_the_memory_rules_with_no_refusal_and_no_warning(self):
        for t in self.templates:
            for kind, key, field, text in texts(t):
                limit = {"name": 40, "instructions": 2000, "text": 4000}[field]
                got = memory_rules.check_text(text, limit, multiline=field != "name")
                self.assertEqual(got, {"refuse": None, "warn": []}, f"{t['id']} {kind} {key} {field}")
            self.assertEqual(memory_rules.check_text(t["about"], 120), {"refuse": None, "warn": []}, t["id"])

    def test_standing_instructions_are_fine_for_a_card_and_for_a_command_line(self):
        for t in self.templates:
            for c in t["cards"]:
                self.assertEqual(agent_profiles.clean_instructions(c["instructions"]), c["instructions"], c["key"])
                self.assertIsNone(agent_sessions.append_prompt_problem(c["instructions"]), c["key"])
                self.assertIsNone(agent_sessions.chat_append_prompt_problem(c["instructions"]), c["key"])

    def test_positions_and_models_are_the_ones_the_program_knows(self):
        for t in self.templates:
            for c in t["cards"]:
                self.assertTrue(c["position"] is None or c["position"] in agent_profiles.POSITIONS, c)
                self.assertIn(c["claude_model"], model_options.CLAUDE_ALIASES, c)

    def test_the_routines_are_what_the_routine_rules_take(self):
        for t in self.templates:
            for r in t["routines"]:
                fields = routine_rules.validate_fields(
                    {"name": r["name"], "profile_id": "p-fake", "text": r["text"], "days": r["days"], "times": r["times"], "enabled": False},
                    full=True)
                self.assertEqual((fields["days"], fields["times"]), (r["days"], r["times"]))

    def test_lengths_fit_the_limits_of_a_card_a_skill_and_a_routine(self):
        for t in self.templates:
            self.assertLessEqual(len(t["name"]), 40)
            self.assertLessEqual(len(t["about"]), 120)
            for kind, key, field, text in texts(t):
                self.assertEqual(text, text.strip(), (kind, key, field))
                self.assertLessEqual(len(text), {"name": 40, "instructions": 2000, "text": 4000}[field], (kind, key, field))
                self.assertGreaterEqual(len(text), 1)

    def test_no_emoji_no_address_no_mail_no_phone_and_no_long_number(self):
        for t in self.templates:
            for kind, key, field, text in list(texts(t)) + [("t", t["id"], "about", t["about"]), ("t", t["id"], "name", t["name"])]:
                where = (t["id"], kind, key, field)
                for ch in text:
                    self.assertNotEqual(unicodedata.category(ch), "So", (where, ch))
                    self.assertLess(ord(ch), 0x1F000, (where, ch))
                    self.assertFalse(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") and ch not in "\n", (where, ch))
                self.assertIsNone(re.search(r"https?:|www\.|://|\.com|\.org|\.tw", text, flags=re.I), where)
                self.assertNotIn("@", text, where)
                self.assertIsNone(re.search(r"\d{8,}", text), where)
                self.assertIsNone(re.search(r"\b0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{3,4}\b", text), where)

    def test_the_fill_in_spaces_are_the_plans_two_markers(self):
        words = " ".join(t for tpl in self.templates for _, _, f, t in texts(tpl) if f == "text")
        self.assertIn("（填）", words)
        self.assertIn("（貼在這裡）", words)

    def test_builtin_hands_out_copies(self):
        got = tb.builtin()
        got[0]["cards"][0]["name"] = "被改過"
        got[0]["cards"].append({})
        again = tb.builtin()
        self.assertEqual(again[0]["cards"][0]["name"], "客服")
        self.assertEqual(len(again[0]["cards"]), 3)


if __name__ == "__main__":
    unittest.main()
