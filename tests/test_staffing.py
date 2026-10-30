"""Staffing meetings, the pure part (P35-1): what the speakers and the CEO are given, who VBear suggests, what a model may
write, the prompts, the record and what is read from it. No CLI runs here."""
import copy
import inspect
import json
import os
import random
import stat
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import board_engine as be, categories, meeting_rules as rules, meetings as mt, position_guide, staffing as st
from vbear.jsonstore import StoreError

SHA = "b" * 64


def profile(pid, position, tool="claude", *, enabled=True, updated=1.0, skills=(), name=None, model_id="", **extra):
    p = {"id": pid, "name": name or pid.upper(), "profession_role_id": None, "model": {"tool": tool, "model_id": model_id},
         "equipped_skill_ids": list(skills), "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
         "enabled": enabled, "created_at": 1.0, "updated_at": updated, "_unresolved": {"profession": False, "skills": []}}
    if position:
        p["position"] = position
    p.update(extra)
    return p


def skill(sid, name=None, tool="claude", activation="active", cats=(), excerpt="", **extra):
    s = {"skill_id": sid, "name": name or sid, "invoke_name": name or sid, "tool": tool, "read_by": [], "scope": "user",
         "activation": activation, "mtime": 1, "excerpt": excerpt, "categories": list(cats)}
    s.update(extra)
    return s


def task(title="官網改版", goal="把網站首頁改成新的版型", scope=("前端頁面",), deliverables=("新的首頁",), **extra):
    t = {"title": title, "goal": goal, "scope": list(scope), "out_of_scope": [], "deliverables": list(deliverables),
         "acceptance_criteria": [], "evidence": [], "status": "todo", "folder": "/Users/someone/secret-project"}
    t.update(extra)
    return t


def team():
    return [profile("ceo", "planner", model_id="opus"), profile("eng", "executor", skills=["s-front", "s-gone"]),
            profile("rev", "reviewer", tool="codex"), profile("law", "legal"), profile("off", "art", tool="agy", enabled=False)]


def library():
    return [skill("s-front", "網站前端", cats=["frontend"], excerpt="Build a website front end"),
            skill("s-test", "測試檢查", tool="shared", activation="unknown", cats=["quality"]),
            skill("s-law", "授權檢查", cats=["legal"]),
            skill("s-codex", "codex-review", tool="codex", cats=["quality"]),
            skill("s-dead", "舊版", activation="superseded", cats=["frontend"]),
            skill("s-novel", "小說寫作", cats=["writing"])]


class InputTests(unittest.TestCase):
    def test_every_card_and_usable_skill_gets_an_alias_and_no_real_id_is_shown(self):
        inputs = st.build_inputs(task(), team(), library())
        self.assertEqual([c["alias"] for c in inputs["cards"]], ["C1", "C2", "C3", "C4", "C5"])
        self.assertEqual(sorted(s["skill_id"] for s in inputs["skills"]), ["s-codex", "s-front", "s-law", "s-novel", "s-test"])
        self.assertEqual([s["alias"] for s in inputs["skills"]], ["S1", "S2", "S3", "S4", "S5"])
        self.assertEqual(inputs["omitted"], {"cards": 0, "skills": 0})
        shown = json.dumps(st.full_view(inputs), ensure_ascii=False)
        for secret in ("s-front", "s-gone", '"eng"', SHA[:10], "/Users/someone", "secret-project", "profile_id", "skill_id", "revision"):
            self.assertNotIn(secret, shown)
        self.assertIn("網站前端", shown)

    def test_enabled_cards_come_first_then_the_ones_that_fit_the_task(self):
        cards = [profile("z-off", "executor", enabled=False), profile("b-law", "legal"), profile("a-eng", "executor"),
                 profile("c-pm", "pm"), profile("d-none", None)]
        inputs = st.build_inputs(task(), cards, [])
        # the task is a website: an executor's suggested skill categories meet its categories, a legal manager's do not
        self.assertEqual([c["profile_id"] for c in inputs["cards"]], ["a-eng", "b-law", "c-pm", "d-none", "z-off"])
        off = inputs["cards"][-1]
        self.assertEqual((off["enabled"], off["position"]), (False, "executor"))
        self.assertIsNone(inputs["cards"][3]["position"])

    def test_a_card_says_what_it_is_and_what_it_carries(self):
        cards = team()
        cards[1]["instructions"] = "你" * 300
        cards[1]["launch_mode"] = "full"
        inputs = st.build_inputs(task(), cards, library())
        eng = next(c for c in inputs["cards"] if c["profile_id"] == "eng")
        front = next(s["alias"] for s in inputs["skills"] if s["skill_id"] == "s-front")
        self.assertEqual(eng["equipped"], [front])
        self.assertEqual(eng["equipped_unlisted"], 1)  # s-gone is not in the list
        self.assertEqual(eng["instructions"], {"source": "custom", "head": "你" * 120})
        self.assertEqual((eng["tool"], eng["family"], eng["launch_mode"], eng["can_start"]), ("claude", "anthropic", "full", "full"))
        self.assertEqual(len(eng["revision"]), 64)
        ceo = next(c for c in inputs["cards"] if c["profile_id"] == "ceo")
        self.assertEqual((ceo["model_id"], ceo["instructions"]["source"]), ("opus", "default"))
        self.assertEqual(ceo["instructions"]["head"], position_guide.GUIDE["planner"]["prompt"][:120])
        rev = next(c for c in inputs["cards"] if c["profile_id"] == "rev")
        self.assertEqual((rev["family"], rev["can_start"]), ("openai", "no"))  # Codex in safe mode: VBear does not start it
        off = next(c for c in inputs["cards"] if c["profile_id"] == "off")
        self.assertEqual((off["family"], off["can_start"], off["enabled"]), ("google", "no", False))

    def test_whether_vbear_can_start_a_card_follows_its_tool_and_launch_mode(self):
        rows = [("claude", None, "safe"), ("claude", "full", "full"), ("codex", None, "no"), ("codex", "full", "full"),
                ("agy", None, "no"), ("agy", "full", "full"), ("shared", None, "no"), ("shared", "full", "no")]
        for tool, mode, want in rows:
            p = profile("x", "executor", tool=tool, **({"launch_mode": mode} if mode else {}))
            self.assertEqual(st.can_start(p), want, (tool, mode))

    def test_a_skill_says_which_camps_can_use_it_and_one_line_of_what_it_is(self):
        lib = library()
        lib[0]["excerpt"] = "x" * 100
        inputs = st.build_inputs(task(), team(), lib, summaries={"s-test": "檢查測試有沒有寫好"})
        by = {s["skill_id"]: s for s in inputs["skills"]}
        self.assertEqual(by["s-front"]["fits"], ["claude"])
        self.assertEqual(by["s-test"]["fits"], ["claude", "codex", "shared"])
        self.assertEqual((by["s-front"]["line"], by["s-front"]["line_source"]), ("x" * 60, "原文"))
        self.assertEqual((by["s-test"]["line"], by["s-test"]["line_source"]), ("檢查測試有沒有寫好", "中文摘要"))
        self.assertEqual(by["s-law"]["categories"], ["legal"])

    def test_one_skill_of_a_name_and_none_that_no_camp_can_use(self):
        lib = [skill("s-old", "same", activation="unknown", mtime=9), skill("s-new", "same", mtime=1),
               skill("s-off", "off", activation="disabled"), skill("s-weird", "weird", tool="")]
        inputs = st.build_inputs(task(), team(), lib)
        self.assertEqual([s["skill_id"] for s in inputs["skills"]], ["s-new"])

    def test_skills_that_meet_the_task_or_the_positions_come_first_then_the_equipped_then_by_name(self):
        lib = [skill("s-z", "zeta"), skill("s-eq", "omega"), skill("s-web", "web", cats=["frontend"]),
               skill("s-auto", "auto", cats=["automation"]), skill("s-a", "alpha")]
        cards = [profile("ceo", "planner", skills=["s-eq"])]
        inputs = st.build_inputs(task(), cards, lib)
        # web meets the task (frontend); auto meets the CEO's suggested categories; omega is on a card; then by name
        self.assertEqual([s["skill_id"] for s in inputs["skills"]], ["s-auto", "s-web", "s-eq", "s-a", "s-z"])

    def test_at_most_forty_cards_and_a_hundred_and_twenty_skills_and_the_rest_is_counted(self):
        cards = [profile(f"p{i:02d}", "executor") for i in range(45)]
        lib = [skill(f"s{i:03d}") for i in range(130)]
        inputs = st.build_inputs(task(), cards, lib)
        self.assertEqual((len(inputs["cards"]), len(inputs["skills"])), (40, 120))
        self.assertEqual(inputs["omitted"], {"cards": 5, "skills": 10})
        self.assertEqual((inputs["cards"][-1]["alias"], inputs["skills"][-1]["alias"]), ("C40", "S120"))

    def test_the_list_stays_within_its_size_skills_go_before_cards(self):
        lib = [skill(f"s{i:03d}", f"{i:03d}" + "技能" * 30, excerpt="說明" * 40) for i in range(120)]
        inputs = st.build_inputs(task(), [profile(f"p{i:02d}", "executor", name="名" * 80) for i in range(40)], lib)
        size = len(json.dumps(st.full_view(inputs), ensure_ascii=False).encode())
        self.assertLessEqual(size, st.LIST_MAX)
        self.assertEqual(len(inputs["cards"]), 40)
        self.assertGreater(inputs["omitted"]["skills"], 0)
        self.assertEqual(len(inputs["skills"]) + inputs["omitted"]["skills"], 120)
        self.assertEqual([s["alias"] for s in inputs["skills"]], [f"S{i + 1}" for i in range(len(inputs["skills"]))])
        # with the cards alone too large, every skill goes and then the last cards
        big = [profile(f"p{i:02d}", "executor", name="名" * 80, instructions="長" * 2000, model_id="m" * 200,
                       skills=[f"s{j:03d}" for j in range(120)]) for i in range(40)]
        inputs = st.build_inputs(task(), big, lib)
        self.assertLessEqual(len(json.dumps(st.full_view(inputs), ensure_ascii=False).encode()), st.LIST_MAX)
        self.assertEqual((inputs["skills"], inputs["omitted"]["skills"]), ([], 120))
        self.assertGreater(inputs["omitted"]["cards"], 0)
        self.assertEqual(len(inputs["cards"]) + inputs["omitted"]["cards"], 40)

    def test_a_smaller_list_can_be_asked_for(self):
        lib = [skill(f"s{i:03d}", f"{i:03d}" + "技能" * 30) for i in range(120)]
        inputs = st.build_inputs(task(), team(), lib, list_max=8 * 1024)
        self.assertLessEqual(len(json.dumps(st.full_view(inputs), ensure_ascii=False).encode()), 8 * 1024)
        self.assertEqual(len(inputs["skills"]) + inputs["omitted"]["skills"], 120)
        self.assertGreater(inputs["omitted"]["skills"], 0)
        for bad in (0, -1, 1023, st.LIST_MAX + 1, 1.5, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                st.build_inputs(task(), team(), lib, list_max=bad)

    def test_the_same_inputs_in_any_order_give_the_same_sha_and_a_change_gives_another(self):
        a = st.build_inputs(task(), team(), library())
        cards, lib = team(), library()
        random.Random(7).shuffle(cards)
        random.Random(8).shuffle(lib)
        b = st.build_inputs(task(), cards, lib)
        self.assertEqual(a["inputs_sha256"], b["inputs_sha256"])
        self.assertEqual(a, b)
        changed = team()
        changed[1]["name"] = "改名了"
        self.assertNotEqual(st.build_inputs(task(), changed, library())["inputs_sha256"], a["inputs_sha256"])
        self.assertNotEqual(st.build_inputs(task(goal="換一個目標"), team(), library())["inputs_sha256"], a["inputs_sha256"])
        moved = task()
        moved["status"] = "in_progress"  # the status moves with the work, as for a meeting's inputs
        self.assertEqual(st.build_inputs(moved, team(), library())["inputs_sha256"], a["inputs_sha256"])

    def test_the_sent_part_of_the_record_holds_only_aliases_ids_revisions_and_counts(self):
        inputs = st.build_inputs(task(), team(), library())
        sent = st.sent_of(inputs)
        self.assertEqual(set(sent), {"cards", "skills", "omitted", "inputs_sha256"})
        self.assertEqual(set(sent["cards"][0]), {"alias", "profile_id", "revision", "enabled"})
        self.assertEqual(set(sent["skills"][0]), {"alias", "skill_id"})


class SpeakerViewTests(unittest.TestCase):
    def test_a_speaker_gets_the_short_list_its_aliases_a_subset_of_the_full_one(self):
        lib = library() + [skill(f"s-q{i:02d}", f"q{i:02d}", cats=["quality"]) for i in range(50)]
        inputs = st.build_inputs(task(), team(), lib)
        full_cards = {c["alias"] for c in inputs["cards"]}
        full_skills = {s["alias"] for s in inputs["skills"]}
        for position in st.SPEAKER_POSITIONS:
            view = st.speaker_view(inputs, position)
            self.assertLessEqual({c["alias"] for c in view["cards"]}, full_cards)
            self.assertLessEqual({s["alias"] for s in view["skills"]}, full_skills)
            self.assertLessEqual(len(view["skills"]), st.MAX_SPEAKER_SKILLS)
        legal = st.speaker_view(inputs, "legal")
        names = {s["name"] for s in legal["skills"]}
        self.assertIn("授權檢查", names)  # legal is a legal manager's own category
        self.assertIn("網站前端", names)  # frontend is the task's
        self.assertNotIn("小說寫作", names)  # writing is neither
        self.assertEqual(len(st.speaker_view(inputs, "executor")["skills"]), st.MAX_SPEAKER_SKILLS)

    def test_a_short_card_carries_no_instructions_and_no_skill_detail(self):
        inputs = st.build_inputs(task(), team(), library())
        card = next(c for c in st.speaker_view(inputs, "pm")["cards"] if c["name"] == "ENG")
        self.assertEqual(set(card), {"alias", "name", "position", "tool", "family", "enabled", "launch_mode", "can_start", "equipped_count"})
        self.assertEqual(card["equipped_count"], 2)
        skill_entry = st.speaker_view(inputs, "pm")["skills"][0]
        self.assertEqual(set(skill_entry), {"alias", "name", "categories", "fits"})

    def test_the_accountant_also_sees_each_cards_model(self):
        inputs = st.build_inputs(task(), team(), library())
        ceo = next(c for c in st.speaker_view(inputs, "accountant")["cards"] if c["name"] == "CEO")
        self.assertEqual(ceo["model_id"], "opus")
        self.assertNotIn("model_id", st.speaker_view(inputs, "legal")["cards"][0])


class SuggestTests(unittest.TestCase):
    def suggest(self, t, cards=None):
        cards = cards if cards is not None else [profile(p, p) for p in ("pm", "executor", "legal", "accountant", "social", "art")]
        return {s["position"]: s for s in st.suggest_speakers(t, cards)}

    def test_the_pm_is_suggested_whenever_there_is_a_pm_card(self):
        got = self.suggest(task(title="寫一篇小說", goal="寫第一章", scope=(), deliverables=()))
        self.assertIn("pm", got)
        self.assertIn("進度", got["pm"]["why"])
        self.assertNotIn("pm", self.suggest(task(), [profile("eng", "executor")]))

    def test_the_engineer_is_suggested_for_each_technical_category_or_when_there_is_none(self):
        for text, cat in (("改網站", "frontend"), ("部署到伺服器", "backend"), ("補測試", "quality"), ("資安檢查", "security"),
                          ("做一個 AI 代理", "ai")):
            got = self.suggest(task(title=text, goal="", scope=(), deliverables=()))
            self.assertIn("executor", got, text)
            label = next(c["label"] for c in categories.CATEGORIES if c["id"] == cat)
            self.assertIn(label, got["executor"]["why"])
        none = self.suggest(task(title="整理一下", goal="", scope=(), deliverables=()))
        self.assertIn("executor", none)
        self.assertIn("沒有分出", none["executor"]["why"])
        self.assertNotIn("executor", self.suggest(task(title="寫文案", goal="", scope=(), deliverables=())))

    def test_the_legal_manager_is_suggested_for_the_legal_category_and_its_words(self):
        for word in ("個資", "授權", "合約", "著作權"):
            legal = next(c for c in categories.CATEGORIES if c["id"] == "legal")
            self.assertIn(word, legal["match"])  # the plan's words are this category's own keywords
            got = self.suggest(task(title=f"檢查{word}", goal="", scope=(), deliverables=()))
            self.assertIn("legal", got, word)
            self.assertIn(word, got["legal"]["why"])
        self.assertNotIn("legal", self.suggest(task()))
        # the words outside title, goal, scope and deliverables are not read (a template's out-of-scope says 未授權)
        self.assertNotIn("legal", self.suggest(task(out_of_scope=["未授權變更之架構"])))

    def test_the_accountant_is_suggested_for_the_finance_category_or_an_amount(self):
        self.assertIn("accountant", self.suggest(task(title="做預算", goal="", scope=(), deliverables=())))
        for text in ("報價 NT$30,000", "大約三萬元", "US$300 以內"):
            got = self.suggest(task(title="外包", goal=text, scope=(), deliverables=()))
            self.assertIn("accountant", got, text)
            self.assertIn("金額", got["accountant"]["why"])
        self.assertNotIn("accountant", self.suggest(task(goal="測試 100% 通過")))
        self.assertTrue(rules.has_amount("US$300"))
        self.assertFalse(rules.has_amount("測試 100% 通過"))

    def test_social_for_writing_or_media_and_art_for_design_or_media(self):
        got = self.suggest(task(title="寫文案", goal="", scope=(), deliverables=()))
        self.assertIn("social", got)
        self.assertNotIn("art", got)
        got = self.suggest(task(title="品牌設計", goal="", scope=(), deliverables=()))
        self.assertIn("art", got)
        self.assertNotIn("social", got)
        got = self.suggest(task(title="剪一支影片", goal="", scope=(), deliverables=()))
        self.assertIn("social", got)
        self.assertIn("art", got)

    def test_one_enabled_card_per_position_the_one_updated_last(self):
        cards = [profile("old", "executor", updated=5.0), profile("new", "executor", updated=9.0),
                 profile("newest-off", "executor", updated=20.0, enabled=False), profile("tie-b", "pm", updated=3.0),
                 profile("tie-a", "pm", updated=3.0), profile("ceo", "planner"), profile("gate", "reviewer", tool="codex")]
        got = st.suggest_speakers(task(), cards)
        self.assertEqual([(s["position"], s["profile_id"]) for s in got], [("pm", "tie-a"), ("executor", "new")])
        self.assertTrue(all(set(s) == {"profile_id", "position", "why"} and s["why"] for s in got))

    def test_the_order_is_the_tables_and_at_most_one_per_speaking_position(self):
        got = st.suggest_speakers(task(title="剪影片、設計品牌、寫文案、做預算、檢查授權、改網站", goal="", scope=(), deliverables=()),
                                  [profile(p, p) for p in ("art", "social", "accountant", "legal", "executor", "pm")])
        self.assertEqual([s["position"] for s in got], ["pm", "executor", "legal", "accountant", "social", "art"])
        self.assertEqual([r["position"] for r in st.SUGGEST_SPEAKERS], ["pm", "executor", "legal", "accountant", "social", "art"])
        self.assertLessEqual(len(got), 6)

    def test_no_task_still_suggests_the_pm_and_the_engineer(self):
        got = st.suggest_speakers(None, [profile("pm", "pm"), profile("eng", "executor"), profile("law", "legal")])
        self.assertEqual([s["position"] for s in got], ["pm", "executor"])


if __name__ == "__main__":
    unittest.main()


def aliases(inputs):
    """{profile id or skill id: alias} of a list."""
    return {**{c["profile_id"]: c["alias"] for c in inputs["cards"]}, **{s["skill_id"]: s["alias"] for s in inputs["skills"]}}


def staff_opinion(**kw):
    out = {"summary": "需要會寫前端的人", "needs": [{"what": "網站前端", "position": "executor"}],
           "recommend": [], "skills": [], "skill_gaps": [], "risks": []}
    out.update(kw)
    return out


def proposal(**kw):
    out = {"summary": "用全端工程師做，Codex 審查", "team": [], "staff": [], "new_cards": [], "skill_gaps": [], "risks": [],
           "questions_for_chairman": [], "opinions_used": []}
    out.update(kw)
    return out


def seat(slot, card="", pick="existing", new_ref="", skills=(), reason="理由"):
    return {"slot": slot, "pick": pick, "card": card, "new_ref": new_ref, "reason": reason, "skills": list(skills)}


def codes(result):
    return [n["code"] for n in result["notes"]]


class OpinionValidationTests(unittest.TestCase):
    def setUp(self):
        self.inputs = st.build_inputs(task(), team(), library())
        self.a = aliases(self.inputs)

    def test_a_good_opinion_is_kept_redacted_with_aliases_and_no_notes(self):
        a = self.a
        out = st.validate_opinion(staff_opinion(
            summary="金鑰 sk-ant-api03-" + "A" * 40 + " 不要寫",
            recommend=[{"card": a["eng"], "position": "executor", "slot": "executor", "why": "會寫前端"},
                       {"card": "", "position": "legal", "slot": "staff", "why": "需要法務但不一定要這張"}],
            skills=[{"skill": a["s-test"], "for": a["eng"], "why": "要會測試"}, {"skill": a["s-law"], "for": "legal", "why": "授權"}],
            skill_gaps=[{"need": "圖片授權檢查", "category": "legal", "search_words": ["授權", "license"]}],
            risks=[{"level": "中", "text": "圖片授權", "source": ""}]), "executor", self.inputs)
        kept = out["kept"]
        self.assertEqual(out["notes"], [])
        self.assertNotIn("sk-ant-api03", kept["summary"])
        self.assertEqual([r["card"] for r in kept["recommend"]], [a["eng"], ""])
        self.assertEqual([r["flags"] for r in kept["recommend"]], [[], []])
        self.assertEqual([(s["skill"], s["for"], s["flags"]) for s in kept["skills"]],
                         [(a["s-test"], a["eng"], []), (a["s-law"], "legal", [])])
        self.assertEqual(kept["skill_gaps"][0]["search_words"], ["授權", "license"])
        self.assertEqual(kept["risks"], [{"level": "中", "text": "圖片授權", "source": ""}])  # only the legal manager's is filled in

    def test_an_opinion_that_is_not_the_schema_is_void(self):
        good = staff_opinion()
        rec = {"card": "", "position": "executor", "slot": "executor", "why": "x"}
        bads = [None, [], {}, {**good, "extra": 1}, {k: v for k, v in good.items() if k != "risks"},
                staff_opinion(summary=""), staff_opinion(summary="x" * 121), staff_opinion(summary=1),
                staff_opinion(needs=[{"what": "x", "position": "ceo"}]), staff_opinion(needs=[{"what": "x", "position": "pm"}] * 6),
                staff_opinion(needs=[{"what": "x" * 121, "position": "pm"}]), staff_opinion(needs="x"),
                staff_opinion(recommend=[rec] * 5), staff_opinion(recommend=[{**rec, "slot": "boss"}]),
                staff_opinion(recommend=[{**rec, "position": "planner2"}]), staff_opinion(recommend=[{**rec, "why": "x" * 201}]),
                staff_opinion(recommend=[{**rec, "card": 3}]), staff_opinion(recommend=[{**rec, "card": "C" * 9}]),
                staff_opinion(recommend=[{k: v for k, v in rec.items() if k != "why"}]),
                staff_opinion(skills=[{"skill": "S1", "for": "pm", "why": "x"}] * 7),
                staff_opinion(skills=[{"skill": "S1", "for": "pm", "why": "x" * 121}]),
                staff_opinion(skills=[{"skill": "S1", "for": "x" * 17, "why": "x"}]),
                staff_opinion(skill_gaps=[{"need": "x", "category": "cooking", "search_words": []}]),
                staff_opinion(skill_gaps=[{"need": "x", "category": "other", "search_words": ["a", "b", "c", "d"]}]),
                staff_opinion(skill_gaps=[{"need": "x", "category": "other", "search_words": ["x" * 21]}]),
                staff_opinion(skill_gaps=[{"need": "x", "category": "other", "search_words": [""]}]),
                staff_opinion(skill_gaps=[{"need": "x", "category": "other", "search_words": []}] * 4),
                staff_opinion(risks=[{"level": "極高", "text": "x", "source": ""}]),
                staff_opinion(risks=[{"level": "高", "text": "x", "source": "x" * 201}]),
                staff_opinion(risks=[{"level": "低", "text": "x", "source": ""}] * 6)]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(mt.OutputError) as caught:
                st.validate_opinion(bad, "executor", self.inputs)
            self.assertEqual(caught.exception.code, "invalid_output")
        with self.assertRaises(mt.OutputError) as caught:
            st.validate_opinion(staff_opinion(summary="这个可以"), "executor", self.inputs)
        self.assertEqual(caught.exception.code, "not_traditional")

    def test_what_is_not_on_the_list_or_does_not_fit_is_taken_out_and_said(self):
        a = self.a
        out = st.validate_opinion(staff_opinion(
            recommend=[{"card": "C99", "position": "executor", "slot": "executor", "why": "x"},
                       {"card": "<b>", "position": "executor", "slot": "executor", "why": "x"}],
            skills=[{"skill": "S99", "for": a["eng"], "why": "x"}, {"skill": a["s-test"], "for": "C99", "why": "x"},
                    {"skill": a["s-test"], "for": "boss", "why": "x"}, {"skill": a["s-codex"], "for": a["eng"], "why": "x"},
                    {"skill": a["s-codex"], "for": a["rev"], "why": "x"}],
            skill_gaps=[{"need": "x", "category": "other", "search_words": ["https://evil.example", "www.x", "好字"]},
                        {"need": "y", "category": "other", "search_words": ["a\x07b"]}]),
            "executor", self.inputs)
        kept = out["kept"]
        self.assertEqual(kept["recommend"], [])
        self.assertEqual([(s["skill"], s["for"]) for s in kept["skills"]], [(a["s-codex"], a["rev"])])
        self.assertEqual([g["search_words"] for g in kept["skill_gaps"]], [["好字"], []])
        self.assertEqual(codes(out), ["unknown_card", "unknown_card", "unknown_skill", "unknown_for", "unknown_for",
                                      "incompatible_skill", "bad_search_word", "bad_search_word", "bad_search_word"])
        self.assertIn("C99", out["notes"][0]["text"])
        self.assertNotIn("<b>", out["notes"][1]["text"])  # what is not an alias is not repeated
        self.assertTrue(all(set(n) == {"code", "text"} for n in out["notes"]))

    def test_what_is_kept_but_needs_a_look_is_flagged(self):
        a = self.a
        out = st.validate_opinion(staff_opinion(
            recommend=[{"card": a["off"], "position": "art", "slot": "executor", "why": "x"},
                       {"card": a["law"], "position": "legal", "slot": "executor", "why": "x"},
                       {"card": a["rev"], "position": "reviewer", "slot": "reviewer1", "why": "x"},
                       {"card": a["law"], "position": "legal", "slot": "staff", "why": "x"}],
            skills=[{"skill": a["s-front"], "for": a["eng"], "why": "x"}]), "pm", self.inputs)
        kept = out["kept"]
        self.assertEqual([r["flags"] for r in kept["recommend"]],
                         [["disabled", "cannot_start"], ["slot_fit"], ["cannot_start"], []])
        self.assertEqual(kept["skills"][0]["flags"], ["already_equipped"])
        self.assertEqual(out["notes"], [])

    def test_a_legal_risk_without_a_source_says_there_is_none(self):
        out = st.validate_opinion(staff_opinion(risks=[{"level": "高", "text": "授權", "source": "  "},
                                                       {"level": "低", "text": "x", "source": "著作權法第 3 條"}]), "legal", self.inputs)
        self.assertEqual([r["source"] for r in out["kept"]["risks"]], [rules.NO_SOURCE, "著作權法第 3 條"])


class ProposalValidationTests(unittest.TestCase):
    def setUp(self):
        cards = team() + [profile("share", "executor", tool="shared"), profile("eng2", "executor", name="ENG2"),
                          profile("pm1", "pm"), profile("full", "executor", skills=[f"x{i}" for i in range(199)])]
        self.inputs = st.build_inputs(task(), cards, library())
        self.a = aliases(self.inputs)

    def check(self, value, spoke=("executor", "legal")):
        return st.validate_proposal(value, self.inputs, set(spoke))

    def test_a_good_proposal_is_kept_with_aliases_and_nothing_to_say(self):
        a = self.a
        out = self.check(proposal(
            team=[seat("planner", a["ceo"]), seat("executor", a["eng"], skills=[{"skill": a["s-test"], "why": "測試"}]),
                  seat("reviewer1", a["rev"]), seat("reviewer2", pick="empty", card="")],
            staff=[{"position": "legal", "pick": "existing", "card": a["law"], "new_ref": "", "reason": "看授權", "skills": []}],
            new_cards=[{"ref": "N1", "position": "accountant", "tool": "claude", "model_alias": "haiku", "name": "會計",
                        "reason": "算成本", "skills": [{"skill": a["s-test"], "why": "x"}]}],
            skill_gaps=[{"for": "executor", "need": "圖片授權", "category": "legal", "search_words": ["授權"], "why": "沒有"},
                        {"for": "N1", "need": "發票", "category": "finance", "search_words": [], "why": "沒有"}],
            risks=["範圍可能變大"], questions_for_chairman=["要不要加第二位審查？"],
            opinions_used=[{"from": "executor", "point": "要會測試", "adopted": True, "why": "同意"},
                           {"from": "legal", "point": "加第二位審查", "adopted": False, "why": "範圍小"}]))
        self.assertEqual(out["notes"], [])
        kept = out["kept"]
        self.assertEqual([(t["slot"], t["card"], t["flags"]) for t in kept["team"]],
                         [("planner", a["ceo"], []), ("executor", a["eng"], []), ("reviewer1", a["rev"], ["cannot_start"]),
                          ("reviewer2", "", [])])
        self.assertEqual(kept["team"][1]["skills"], [{"skill": a["s-test"], "why": "測試", "flags": []}])
        self.assertEqual(kept["staff"][0]["flags"], [])
        self.assertEqual(kept["new_cards"][0]["model_alias"], "haiku")
        self.assertEqual([o["adopted"] for o in kept["opinions_used"]], [True, False])

    def test_a_proposal_that_is_not_the_schema_is_void(self):
        a = self.a
        good = proposal()
        card = {"ref": "N1", "position": "pm", "tool": "claude", "model_alias": "", "name": "x", "reason": "x", "skills": []}
        bads = [None, {**good, "extra": 1}, {k: v for k, v in good.items() if k != "opinions_used"}, proposal(summary="x" * 301),
                proposal(team=[seat("planner", a["ceo"])] * 5), proposal(team=[seat("boss", a["ceo"])]),
                proposal(team=[seat("planner", a["ceo"], pick="maybe")]), proposal(team=[seat("planner", a["ceo"], reason="x" * 301)]),
                proposal(team=[seat("planner", a["ceo"], skills=[{"skill": "S1", "why": "x"}] * 9)]),
                proposal(staff=[{"position": "planner", "pick": "existing", "card": "C1", "new_ref": "", "reason": "x", "skills": []}]),
                proposal(staff=[{"position": "pm", "pick": "empty", "card": "", "new_ref": "", "reason": "x", "skills": []}]),
                proposal(new_cards=[card] * 4), proposal(new_cards=[{**card, "tool": "gemini"}]),
                proposal(new_cards=[{**card, "model_alias": "gpt"}]), proposal(new_cards=[{**card, "name": "x" * 41}]),
                proposal(new_cards=[{**card, "position": "boss"}]),
                proposal(skill_gaps=[{"for": "executor", "need": "x", "category": "other", "search_words": [], "why": "x"}] * 7),
                proposal(risks=["x" * 201]), proposal(questions_for_chairman=["x"] * 4),
                proposal(opinions_used=[{"from": "pm", "point": "x", "adopted": "yes", "why": "x"}]),
                proposal(opinions_used=[{"from": "pm", "point": "x", "adopted": True, "why": "x"}] * 13)]
        # an entry that would be taken out is still read whole first: a bad shape anywhere voids the answer
        bad_skill = [{"skill": "S1"}]
        bads += [proposal(team=[seat("planner", a["ceo"]), seat("planner", a["ceo"], skills=bad_skill)]),
                 proposal(team=[seat("planner", "C99", skills=bad_skill)]),
                 proposal(new_cards=[{**card, "ref": "N9", "skills": bad_skill}]),
                 proposal(staff=[{"position": "pm", "pick": "existing", "card": "C99", "new_ref": "", "reason": "x", "skills": bad_skill}]),
                 proposal(skill_gaps=[{"for": "nowhere", "need": "x", "category": "other", "search_words": [1], "why": "x"}]),
                 proposal(opinions_used=[{"from": "nobody", "point": "x" * 121, "adopted": True, "why": "x"}])]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(mt.OutputError):
                self.check(bad)

    def test_new_cards_that_cannot_be_are_taken_out_or_corrected(self):
        a = self.a
        card = {"ref": "N1", "position": "executor", "tool": "codex", "model_alias": "", "name": "新卡", "reason": "x", "skills": []}
        out = self.check(proposal(new_cards=[
            {**card, "model_alias": "opus", "skills": [{"skill": a["s-front"], "why": "x"}, {"skill": a["s-codex"], "why": "x"}]},
            {**card, "name": "重複"}, {**card, "ref": "N7"}]))
        kept = out["kept"]["new_cards"]
        self.assertEqual([(c["ref"], c["model_alias"], [s["skill"] for s in c["skills"]]) for c in kept], [("N1", "", [a["s-codex"]])])
        self.assertEqual(codes(out), ["model_alias_cleared", "incompatible_skill", "duplicate_ref", "bad_ref", "missing"])

    def test_places_that_clash_or_point_nowhere_are_taken_out_and_said(self):
        a = self.a
        out = self.check(proposal(
            team=[seat("planner", a["ceo"]), seat("planner", a["pm1"]), seat("executor", a["eng"]), seat("reviewer1", "C99")],
            staff=[{"position": "legal", "pick": "existing", "card": a["law"], "new_ref": "", "reason": "x", "skills": []},
                   {"position": "legal", "pick": "existing", "card": a["law"], "new_ref": "", "reason": "x", "skills": []},
                   {"position": "pm", "pick": "existing", "card": a["eng"], "new_ref": "", "reason": "x", "skills": []},
                   {"position": "social", "pick": "existing", "card": "", "new_ref": "", "reason": "x", "skills": []}]))
        kept = out["kept"]
        self.assertEqual([(t["slot"], t["card"]) for t in kept["team"]], [("planner", a["ceo"]), ("executor", a["eng"])])
        self.assertEqual([s["card"] for s in kept["staff"]], [a["law"]])
        self.assertEqual(codes(out), ["duplicate_slot", "unknown_card", "duplicate_position", "duplicate_card", "pick_mismatch",
                                      "missing"])
        self.assertEqual(out["notes"][0]["text"], "「規劃位」寫了兩次，只留第一筆")
        self.assertEqual(out["notes"][-1]["text"], "還差：審查位")
        # a new card nobody wrote, and the CEO's own card in a review place (not the executor's: that one is flagged)
        out = self.check(proposal(team=[seat("planner", a["ceo"]), seat("executor", a["eng"]), seat("reviewer2", pick="new", new_ref="N2"),
                                        seat("reviewer1", a["ceo"])]))
        self.assertEqual([t["slot"] for t in out["kept"]["team"]], ["planner", "executor"])
        self.assertEqual(codes(out), ["unknown_new_ref", "duplicate_card", "missing"])

    def test_the_review_places_are_judged_like_the_team_board_judges_them(self):
        a = self.a
        rows = [(a["eng"], a["eng2"], ["same_family"]), (a["eng"], a["share"], ["cannot_start", "reviewer_family_unknown"]),
                (a["share"], a["rev"], ["cannot_start", "executor_family_unknown"]), (a["eng"], a["eng"], ["same_card"])]
        for executor, reviewer, want in rows:
            out = self.check(proposal(team=[seat("planner", a["ceo"]), seat("executor", executor), seat("reviewer1", reviewer)]))
            review = out["kept"]["team"][2]
            self.assertEqual([f for f in review["flags"] if f != "slot_fit"], want, (executor, reviewer))
        # a new card's camp is its tool's
        out = self.check(proposal(team=[seat("planner", a["ceo"]), seat("executor", a["eng"]), seat("reviewer1", pick="new", new_ref="N1")],
                                  new_cards=[{"ref": "N1", "position": "reviewer", "tool": "claude", "model_alias": "", "name": "x",
                                              "reason": "x", "skills": []}]))
        self.assertEqual(out["kept"]["team"][2]["flags"], ["same_family"])

    def test_a_card_in_a_place_its_position_does_not_suit_is_flagged(self):
        a = self.a
        out = self.check(proposal(
            team=[seat("planner", a["pm1"]), seat("executor", a["law"]), seat("reviewer1", a["rev"]), seat("reviewer2", a["eng2"])],
            staff=[{"position": "accountant", "pick": "existing", "card": a["eng"], "new_ref": "", "reason": "x", "skills": []}]))
        flags = [t["flags"] for t in out["kept"]["team"]]
        self.assertEqual(flags, [[], ["slot_fit"], ["cannot_start"], ["same_family"]])  # an engineer of another camp may review
        self.assertEqual(out["kept"]["staff"][0]["flags"], ["slot_fit"])
        out = self.check(proposal(team=[seat("planner", a["eng"]), seat("executor", a["off"]), seat("reviewer1", a["rev"])]))
        self.assertEqual([t["flags"] for t in out["kept"]["team"]], [["slot_fit"], ["disabled", "cannot_start"], ["cannot_start"]])

    def test_skills_are_checked_against_the_list_the_card_and_the_most_a_card_can_carry(self):
        a = self.a
        out = self.check(proposal(team=[
            seat("planner", a["ceo"]),
            seat("executor", a["eng"], skills=[{"skill": a["s-front"], "why": "x"}, {"skill": "S99", "why": "x"},
                                                {"skill": a["s-codex"], "why": "x"}, {"skill": a["s-test"], "why": "x"},
                                                {"skill": a["s-test"], "why": "again"}]),
            seat("reviewer1", a["full"], skills=[{"skill": a["s-test"], "why": "x"}, {"skill": a["s-law"], "why": "x"}])]))
        executor, reviewer = out["kept"]["team"][1], out["kept"]["team"][2]
        self.assertEqual([(s["skill"], s["flags"]) for s in executor["skills"]], [(a["s-front"], ["already_equipped"]), (a["s-test"], [])])
        self.assertEqual([s["skill"] for s in reviewer["skills"]], [a["s-test"]])  # 199 + 1 is the most
        self.assertEqual(codes(out), ["unknown_skill", "incompatible_skill", "duplicate_skill", "too_many_skills"])

    def test_gaps_point_at_a_card_a_new_card_or_a_place_and_carry_no_address(self):
        a = self.a
        gap = {"need": "x", "category": "other", "search_words": [], "why": "x"}
        out = self.check(proposal(skill_gaps=[{**gap, "for": a["eng"]}, {**gap, "for": "N1"}, {**gap, "for": "reviewer2"},
                                              {**gap, "for": "C99"}, {**gap, "for": "boss", "search_words": ["ok", "http://x"]}]))
        self.assertEqual([g["for"] for g in out["kept"]["skill_gaps"]], [a["eng"], "reviewer2"])
        self.assertEqual(codes(out), ["unknown_for", "unknown_for", "unknown_for", "missing"])

    def test_an_opinion_is_used_only_from_a_position_that_spoke(self):
        out = self.check(proposal(opinions_used=[{"from": "executor", "point": "x", "adopted": True, "why": "x"},
                                                 {"from": "accountant", "point": "x", "adopted": False, "why": "x"},
                                                 {"from": "<script>", "point": "x", "adopted": False, "why": "x"}]),
                         spoke=("executor",))
        self.assertEqual([o["from"] for o in out["kept"]["opinions_used"]], ["executor"])
        self.assertEqual(codes(out)[:2], ["unknown_speaker", "unknown_speaker"])
        self.assertNotIn("<script>", json.dumps(out["notes"], ensure_ascii=False))

    def test_the_places_still_empty_are_named(self):
        out = self.check(proposal())
        self.assertEqual(out["notes"], [{"code": "missing", "text": "還差：規劃位、執行位、審查位"}])


def big_opinion(inputs):
    """An opinion as long as the schema allows, all of it on the list."""
    a = [c["alias"] for c in inputs["cards"]]
    s = [x["alias"] for x in inputs["skills"]]
    return {"summary": "摘" * 120, "needs": [{"what": "需" * 120, "position": "executor"}] * 5,
            "recommend": [{"card": a[0], "position": "executor", "slot": "executor", "why": "因" * 200}] * 4,
            "skills": [{"skill": s[0], "for": "executor", "why": "技" * 120}] * 6,
            "skill_gaps": [{"need": "缺" * 100, "category": "other", "search_words": ["字" * 20] * 3}] * 3,
            "risks": [{"level": "高", "text": "險" * 200, "source": "源" * 200}] * 5}


def turns_of(rec_turns):
    return {"turns": rec_turns}


class PromptTests(unittest.TestCase):
    def setUp(self):
        cards = team()
        cards[1]["id"] = "real-profile-id-123"
        cards[1]["name"] = "工程師 sk-ant-api03-" + "A" * 40
        lib = library()
        lib[0]["skill_id"] = "skill-id-xyz"
        cards[1]["equipped_skill_ids"] = ["skill-id-xyz"]
        self.inputs = st.build_inputs(task(), cards, lib)

    def prompt(self, kind="opinion", position="executor", **kw):
        args = dict(instructions="我自己寫的指示", position=position, task=task(), note="董事長補充：預算有限", inputs=self.inputs)
        args.update(kw)
        return st.build_prompt(kind, **args)

    def test_a_speakers_prompt_is_the_cards_words_the_rules_then_the_short_list_as_untrusted_data(self):
        text = self.prompt()
        self.assertTrue(text.startswith("我自己寫的指示\n\n"))
        self.assertLess(text.index("不能使用任何工具"), text.index("BEGIN_UNTRUSTED_JSON_STRING"))
        self.assertIn("summary（120 字內）", text)
        data = json.loads(json.loads(text.split("BEGIN_UNTRUSTED_JSON_STRING\n", 1)[1].split("\nEND_UNTRUSTED_JSON_STRING", 1)[0]))
        self.assertEqual(set(data), {"任務卡", "任務分類", "董事長的補充說明", "角色卡", "技能", "沒有列出"})
        self.assertEqual(data["任務分類"], ["frontend"])
        self.assertEqual(data["角色卡"], mt._clean_data(st.speaker_view(self.inputs, "executor")["cards"]))  # redacted
        self.assertNotIn("folder", data["任務卡"])
        self.assertTrue(text.endswith("END_UNTRUSTED_JSON_STRING\n"))

    def test_no_path_no_real_id_no_secret_is_sent(self):
        for text in (self.prompt(), self.prompt("proposal", "planner", opinions=[])):
            for secret in ("real-profile-id-123", "skill-id-xyz", "/Users/someone", "secret-project", "sk-ant-api03",
                           self.inputs["cards"][0]["revision"], "profile_id", "skill_id"):
                self.assertNotIn(secret, text)
            self.assertIn("工程師", text)

    def test_each_speaker_gets_its_own_rules_and_data(self):
        self.assertIn(mt.POSITION_RULES["legal"], self.prompt(position="legal"))
        self.assertNotIn(mt.POSITION_RULES["legal"], self.prompt(position="pm"))
        pm = self.prompt(position="pm", progress="任務卡「官網改版」的狀態：todo。")
        self.assertIn("進度", pm)
        self.assertIn(mt.POSITION_RULES["pm"], pm)
        acct = self.prompt(position="accountant", spend="0.4")
        self.assertIn("會議花費", acct)
        self.assertIn("model_id", acct)
        self.assertNotIn("model_id", self.prompt(position="legal"))
        self.assertIn("法務經理", self.prompt(position="legal"))  # the speaker is told who it speaks as

    def test_the_ceo_gets_the_whole_list_and_what_each_speaker_said_by_aliases(self):
        a = aliases(self.inputs)
        opinions = [{"職位": "全端工程師", "名稱": "ENG", "代發言": False,
                     "發言": {"summary": "推薦", "recommend": [{"card": a["real-profile-id-123"]}]}},
                    {"職位": "法務經理", "名稱": "LAW", "代發言": False, "狀態": "沒有發言（發言失敗）"}]
        text = self.prompt("proposal", "planner", opinions=opinions)
        data = json.loads(json.loads(text.split("BEGIN_UNTRUSTED_JSON_STRING\n", 1)[1].split("\nEND_UNTRUSTED_JSON_STRING", 1)[0]))
        self.assertEqual(data["角色卡"], mt._clean_data(st.full_view(self.inputs)["cards"]))
        self.assertEqual(data["技能"], st.full_view(self.inputs)["skills"])
        self.assertEqual(data["各職位的發言"][1]["狀態"], "沒有發言（發言失敗）")
        self.assertIn("opinions_used", text)
        self.assertIn("不會被執行", text)
        self.assertNotIn(mt.POSITION_RULES["legal"], text)

    def test_the_same_inputs_give_the_same_prompt(self):
        cards, lib = team(), library()
        random.Random(3).shuffle(cards)
        random.Random(4).shuffle(lib)
        again = st.build_inputs(task(), cards, lib)
        first = st.build_inputs(task(), team(), library())
        for kind, position in (("opinion", "executor"), ("opinion", "legal"), ("proposal", "planner")):
            self.assertEqual(self.prompt(kind, position, inputs=first, opinions=[]), self.prompt(kind, position, inputs=again, opinions=[]))

    def test_a_speakers_prompt_stays_within_24_kib_by_showing_less_and_saying_so(self):
        cards = [profile(f"p{i:02d}", "executor", name="名" * 80) for i in range(40)]
        lib = [skill(f"s{i:03d}", f"{i:03d}" + "技" * 70, cats=["frontend"]) for i in range(120)]
        inputs = st.build_inputs(task(), cards, lib)
        text = self.prompt(inputs=inputs, instructions="指" * 2000)
        self.assertLessEqual(len(text.encode()), st.SPEAKER_PROMPT_MAX)
        data = json.loads(json.loads(text.split("BEGIN_UNTRUSTED_JSON_STRING\n", 1)[1].split("\nEND_UNTRUSTED_JSON_STRING", 1)[0]))
        shown = len(data["技能"])
        self.assertLess(shown, st.MAX_SPEAKER_SKILLS)
        self.assertEqual(data["沒有列出"]["技能"], len(inputs["skills"]) + inputs["omitted"]["skills"] - shown)
        self.assertEqual([s["alias"] for s in data["技能"]], [s["alias"] for s in st.speaker_view(inputs, "executor")["skills"][:shown]])
        # a task card too long for any list is refused, not cut
        with self.assertRaises(mt.MeetingError) as caught:
            self.prompt(task=task(goal="長" * 9000))
        self.assertEqual(caught.exception.code, "bad_request")
        self.assertIn("大小", str(caught.exception))

    def test_the_ceos_prompt_fits_the_whole_list_and_six_long_opinions(self):
        cards = [profile(f"p{i:02d}", "executor", name="名" * 80, instructions="長" * 2000) for i in range(40)]
        lib = [skill(f"s{i:03d}", f"{i:03d}" + "技" * 70, excerpt="說" * 60) for i in range(120)]
        inputs = st.build_inputs(task(), cards, lib)
        said = st.chair_opinion(st.validate_opinion(big_opinion(inputs), "executor", inputs)["kept"])
        self.assertLessEqual(len(json.dumps(said, ensure_ascii=False).encode()), st.OPINION_FOR_CHAIR_MAX)
        opinions = [{"職位": "全端工程師", "名稱": "名" * 80, "代發言": True, "發言": said}] * 6
        text = self.prompt("proposal", "planner", inputs=inputs, opinions=opinions,
                           instructions=position_guide.GUIDE["planner"]["prompt"])
        self.assertLessEqual(len(text.encode()), st.CHAIR_PROMPT_MAX)
        with self.assertRaises(mt.MeetingError):
            self.prompt("proposal", "planner", inputs=inputs, opinions=opinions, task=task(goal="長" * 5000), instructions="指" * 2000)

    def test_an_opinion_too_long_for_the_ceo_is_cut_from_its_least_needed_lists_and_says_so(self):
        kept = st.validate_opinion(big_opinion(self.inputs), "executor", self.inputs)["kept"]
        said = st.chair_opinion(kept)
        self.assertLessEqual(len(json.dumps(said, ensure_ascii=False).encode()), st.OPINION_FOR_CHAIR_MAX)
        self.assertEqual(said["summary"], kept["summary"])
        self.assertIn("VBear", said["截短"])
        self.assertEqual(len(kept["recommend"]), 4)  # the kept record is not changed
        cut = sum(len(kept[k]) - len(said[k]) for k in ("needs", "recommend", "skills", "skill_gaps", "risks"))
        self.assertIn(str(cut), said["截短"])
        self.assertEqual(said["needs"], [])  # the needs go first, the recommendations last
        small = st.validate_opinion(staff_opinion(), "executor", self.inputs)["kept"]
        self.assertEqual(st.chair_opinion(small), small)


class OpinionsForChairTests(unittest.TestCase):
    def test_both_kinds_of_board_say_who_spoke_and_who_did_not_in_the_same_words(self):
        from vbear import board_engine as be, meeting_runner as mr
        people = {"a": {"position": "legal", "name": "法務", "proxy": False}, "b": {"position": "pm", "name": "PM", "proxy": True},
                  "c": {"position": "planner", "name": "CEO", "proxy": False}}
        turns = [{"profile_id": "a", "kind": "opinion", "state": "done", "output": {"kept": {"summary": "x"}, "notes": []}},
                 {"profile_id": "b", "kind": "opinion", "state": "failed", "output": None},
                 {"profile_id": "c", "kind": "proposal", "state": "queued", "output": None}]
        got = be.opinions_for_chair({"turns": turns}, people.__getitem__, lambda t: t["output"]["kept"])
        self.assertEqual(got, [{"職位": "法務經理", "名稱": "法務", "代發言": False, "發言": {"summary": "x"}},
                               {"職位": "PM", "名稱": "PM", "代發言": True, "狀態": "沒有發言（發言失敗）"}])
        self.assertIs(mr.STATE_LABELS, be.STATE_LABELS)
        self.assertIn("opinions_for_chair(", inspect.getsource(mr._opinions_for_chair))
        self.assertIn("opinions_for_chair(", inspect.getsource(st.chair_opinions))


def person(pid, position, tool="claude"):
    return {"profile_id": pid, "name": pid.upper(), "position": position, "tool": tool, "model_used": "sonnet", "revision": SHA,
            "proxy": tool != "claude"}


def staffing_record(sid="s-0123456789ab", **kw):
    inputs = st.build_inputs(task(), team(), library())
    args = dict(task_id="t-1", note="", chair=person("ceo", "planner"), speakers=[person("eng", "executor"), person("law", "legal")],
                suggested=[{"profile_id": "eng", "why": "任務分類有「網站與前端」"}], sent=st.sent_of(inputs),
                limits=st.DEFAULT_LIMITS, now=time.time())
    args.update(kw)
    return st.new_record(sid, **args)


def evidence(cost="0.01", source="cli"):
    return {"cli_version": "2.1.296", "model_reported": "claude-sonnet-5-5", "tools_reported": ["StructuredOutput"],
            "mcp_servers_reported": [], "exit_code": 0, "duration_ms": 12, "cost_usd": cost, "cost_source": source}


def done(rec, seq, kept=None, cost="0.01", when=None):
    when = when or time.time()
    rec["turns"][seq - 1].update(state="done", attempts=1, started_at=when, ended_at=when, prompt_sha256=SHA,
                                 output={"kept": kept or {"summary": "好"}, "notes": []}, evidence=evidence(cost))
    return rec


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-staffing-test-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)

    def save(self, rec):
        store = st.StaffingStore(rec["id"])
        with store.locked():
            store.save(rec)
        return rec


class RecordTests(unittest.TestCase):
    def test_a_new_record_queues_every_speaker_then_the_ceo_and_waits_for_the_chairman(self):
        rec = staffing_record()
        self.assertIsNone(st.record_problem(rec))
        self.assertEqual(rec["kind"], "staffing")
        self.assertEqual([(t["kind"], t["profile_id"], t["state"]) for t in rec["turns"]],
                         [("opinion", "eng", "queued"), ("opinion", "law", "queued"), ("proposal", "ceo", "queued")])
        self.assertEqual(set(rec["turns"][0]), mt._TURN_KEYS)
        self.assertEqual(rec["limits"], {"per_call_usd": "0.2", "proposal_call_usd": "0.5", "total_usd": "2"})
        self.assertEqual(rec["chairman"], {"state": "pending", "at": None, "note": "", "adopted": None})
        self.assertEqual(rec["participants"][-1]["profile_id"], "ceo")
        self.assertEqual(set(rec["sent"]), {"cards", "skills", "omitted", "inputs_sha256"})

    def test_only_a_record_this_module_could_have_written_is_one(self):
        good = staffing_record()

        def broken(change):
            rec = copy.deepcopy(good)
            change(rec)
            return rec
        bads = [
            [], {**good, "extra": 1}, {k: v for k, v in good.items() if k != "suggested"},
            broken(lambda r: r.update(kind="meeting")), broken(lambda r: r.update(id="m-0123456789ab")),
            broken(lambda r: r.update(task_id="")), broken(lambda r: r.update(task_id="bad id/..")),
            broken(lambda r: r.update(note="x" * 501)), broken(lambda r: r.update(created_at=-1)),
            broken(lambda r: r.update(participants=r["participants"][-1:])),
            broken(lambda r: r["participants"][0].update(proxy="no")), broken(lambda r: r["participants"][0].update(revision="x")),
            broken(lambda r: r.update(suggested=[{"profile_id": "eng"}])), broken(lambda r: r.update(suggested=[{"profile_id": "eng", "why": 1}])),
            broken(lambda r: r.update(suggested=[{"profile_id": "eng", "why": "x"}] * 7)),
            broken(lambda r: r["sent"].update(cards=[{"alias": "X1", "profile_id": "eng", "revision": SHA, "enabled": True}])),
            broken(lambda r: r["sent"].update(cards=[{"alias": "C1", "profile_id": "eng", "revision": SHA, "enabled": "yes"}])),
            broken(lambda r: r["sent"].update(cards=[{"alias": "C2", "profile_id": "eng", "revision": SHA, "enabled": True}])),
            broken(lambda r: r["sent"].update(skills=[{"alias": "S1", "skill_id": 5}])),
            broken(lambda r: r["sent"].update(omitted={"cards": -1, "skills": 0})), broken(lambda r: r["sent"].update(inputs_sha256="x")),
            broken(lambda r: r["limits"].pop("total_usd")), broken(lambda r: r["limits"].update(total_usd="NaN")),
            broken(lambda r: r["turns"][0].update(kind="decision")), broken(lambda r: r["turns"].reverse()),
            broken(lambda r: r["turns"][0].update(profile_id="nobody")), broken(lambda r: r["turns"][0].update(attempts=4)),
            broken(lambda r: r["turns"][0].update(output={"kept": {}})), broken(lambda r: r["turns"][0].update(output={"kept": [], "notes": []})),
            broken(lambda r: r["turns"][0].update(output={"kept": {}, "notes": [{"code": "made_up", "text": "x"}]})),
            broken(lambda r: r["turns"][0].update(evidence={"cost_usd": "1"})),
            broken(lambda r: r["chairman"].update(state="approved")), broken(lambda r: r["chairman"].update(adopted={"team": {}})),
            broken(lambda r: r["chairman"].pop("adopted")), broken(lambda r: r["chairman"].update(note="x" * 501)),
        ]
        for bad in bads:
            with self.subTest(bad=str(bad)[:120]):
                self.assertIsNotNone(st.record_problem(bad))
        ok = done(copy.deepcopy(good), 1, cost="0.02")
        ok["turns"][0]["output"]["notes"] = [{"code": "unknown_card", "text": "提到清單上沒有的角色卡「C99」，已拿掉"}]
        self.assertIsNone(st.record_problem(ok))


class StatusTests(unittest.TestCase):
    def test_the_status_is_derived_from_the_turns_and_the_chairman(self):
        rec = staffing_record()
        self.assertEqual(st.view(rec)["status"], "running")
        done(rec, 1)
        done(rec, 2)
        rec["turns"][2].update(state="skipped", error_code="no_opinions")
        self.assertEqual(st.view(rec)["status"], "incomplete")
        done(rec, 3)
        self.assertEqual(st.view(rec)["status"], "ready")
        rec["chairman"].update(state="adopted", at=time.time())
        self.assertEqual(st.view(rec)["status"], "adopted")
        rec["chairman"]["state"] = "dismissed"
        self.assertEqual(st.view(rec)["status"], "dismissed")
        failed = staffing_record()
        failed["turns"][0].update(state="failed", attempts=1, error_code="cli_error")
        failed["turns"][1].update(state="cancelled")
        failed["turns"][2].update(state="cancelled")
        self.assertEqual(st.view(failed)["status"], "incomplete")
        self.assertEqual(st.view(failed)["retryable"], [1])

    def test_the_view_counts_each_turn_at_its_own_limit_and_names_the_chairman_as_unverified(self):
        rec = done(staffing_record(), 1, cost="0.05")
        rec["turns"][1].update(state="running", attempts=1, started_at=time.time())
        rec["turns"][2].update(state="running", attempts=1, started_at=time.time())
        v = st.view(rec)
        self.assertEqual(v["spent_usd"], "0.75")  # 0.05 reported, a running speaker 0.2, a running CEO 0.5
        self.assertEqual(v["chairman"]["label"], mt.CHAIRMAN_NOTE)
        self.assertNotIn("major", v)
        self.assertNotIn("rules", v)

    def test_a_high_risk_reminds_the_chairman_and_holds_nothing(self):
        rec = done(staffing_record(), 1, kept={"summary": "x", "risks": [{"level": "高", "text": "授權", "source": "x"}]})
        self.assertTrue(st.view(rec)["high_risk"])
        self.assertFalse(st.view(done(staffing_record(), 1))["high_risk"])

    def test_the_cards_changed_since_the_list_was_made_are_named(self):
        inputs = st.build_inputs(task(), team(), library())
        rec = staffing_record(sent=st.sent_of(inputs))
        cards = {p["id"]: p for p in team()}
        self.assertIsNone(st.view(rec)["changed_cards"])  # not asked: unknown, not "none"
        self.assertEqual(st.view(rec, cards.get)["changed_cards"], [])
        cards["eng"] = {**cards["eng"], "name": "改了"}
        del cards["law"]
        a = aliases(inputs)
        self.assertEqual(st.view(rec, cards.get)["changed_cards"], sorted([a["eng"], a["law"]], key=lambda x: int(x[1:])))

    def test_per_call_of_is_the_turns_own_limit_for_the_meetings_money_functions(self):
        rec = staffing_record(limits={"per_call_usd": Decimal("0.2"), "proposal_call_usd": Decimal("0.7"), "total_usd": Decimal("2")})
        self.assertEqual([st.per_call_of(rec, t) for t in rec["turns"]], [Decimal("0.2"), Decimal("0.2"), Decimal("0.7")])
        now = time.time()
        rec["turns"][2].update(state="running", attempts=1, started_at=now)
        # turn_cost keeps its (turn, per_call) form: spent and daily_spent ask per_call_of for each turn and hand it over
        self.assertEqual(mt.turn_cost(rec["turns"][2], st.per_call_of(rec, rec["turns"][2])), Decimal("0.7"))
        self.assertEqual(st.spent(rec), Decimal("0.7"))
        self.assertEqual(mt.daily_spent([rec], now, st.per_call_of), Decimal("0.7"))
        self.assertEqual(mt.spent(rec), Decimal("0.2"))  # the meeting's own rule would count the CEO's turn at 0.2: wrong here


class StoreTests(Isolated):
    def test_one_record_one_private_file_in_its_own_folder(self):
        rec = self.save(staffing_record())
        path = st.StaffingStore(rec["id"]).path()
        self.assertEqual(path.parent.name, "staffing")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(st.load(rec["id"]), rec)
        self.assertEqual(st.record_ids(), [rec["id"]])
        self.assertFalse((Path(os.environ["VBEAR_HOME"]) / "meetings").exists())
        st.delete(rec["id"])
        self.assertEqual(st.record_ids(), [])
        with self.assertRaises(st.StaffingError) as caught:
            st.load(rec["id"])
        self.assertEqual(caught.exception.code, "not_found")
        self.assertIsInstance(caught.exception, mt.MeetingError)

    def test_what_is_not_a_record_is_refused_on_the_way_in(self):
        rec = staffing_record()
        rec["kind"] = "meeting"
        with self.assertRaises(StoreError):
            self.save(rec)
        huge = staffing_record()
        done(huge, 1, kept={"summary": "x" * 300_000})
        with self.assertRaises(StoreError):
            self.save(huge)
        for bad in ("m-0123456789ab", "s-XYZ", "../s-0123456789ab", None):
            with self.subTest(bad=bad), self.assertRaises(st.StaffingError):
                st.StaffingStore(bad)

    def test_a_damaged_record_blocks_only_itself(self):
        good = self.save(staffing_record("s-aaaaaaaaaaaa"))
        bad = self.save(staffing_record("s-bbbbbbbbbbbb"))
        st.StaffingStore(bad["id"]).path().write_text("{broken")
        with self.assertRaises(st.StaffingError) as caught:
            st.load(bad["id"])
        self.assertEqual(caught.exception.code, "storage")
        self.assertTrue(st.StaffingStore(bad["id"]).marker_path().exists())
        self.assertEqual(st.load(good["id"]), good)
        self.assertEqual(st.record_ids(), [good["id"], bad["id"]])  # still listed, blocked
        with self.assertRaises(st.StaffingError):
            st.delete(bad["id"])
        st.delete(good["id"])
        # a meeting's record put in the staffing folder is not a staffing record
        meeting = json.loads(json.dumps(staffing_record("s-cccccccccccc")))
        meeting["kind"] = "meeting"
        path = st.StaffingStore("s-cccccccccccc").path()
        path.write_text(json.dumps(meeting))
        path.chmod(0o600)
        with self.assertRaises(st.StaffingError):
            st.load("s-cccccccccccc")
        self.assertTrue(st.StaffingStore("s-cccccccccccc").marker_path().exists())
        # a file whose id is not its name is refused too
        other = json.loads(json.dumps(staffing_record("s-dddddddddddd")))
        path = st.StaffingStore("s-eeeeeeeeeeee").path()
        path.write_text(json.dumps(other))
        path.chmod(0o600)
        with self.assertRaises(st.StaffingError):
            st.load("s-eeeeeeeeeeee")

    def test_names_that_are_not_records_are_ignored(self):
        folder = st.folder()
        folder.mkdir(parents=True)
        for name in ("s-0123456789ab.json.lock", "notes.txt", "m-0123456789ab.json", "s-ABC.json"):
            (folder / name).write_text("x")
        self.assertEqual(st.record_ids(), [])


class StaffingBoard(be.HeadlessBoard):
    """The engine with a staffing record's hooks (the runner itself is the next batch): enough to see the engine plan a
    retry from the CEO's turn and charge a turn a restart left at that turn's own limit."""
    final_kind = "proposal"
    store_cls = st.StaffingStore
    room_name = "這份組隊提案"

    def ids(self):
        return st.record_ids()

    def load(self, rid):
        return st.load(rid)

    def view(self, rec):
        return st.view(rec)

    def remove(self, rid):
        st.delete(rid)

    def per_call(self, rec, turn):
        return st.per_call_of(rec, turn)

    def total_limit(self, rec):
        return mt.money(rec["limits"]["total_usd"])

    def decided(self, rec):
        return rec["chairman"]["state"] in ("adopted", "dismissed")


class EngineTests(Isolated):
    def board(self):
        return StaffingBoard(provider=lambda e: ("x", "2.1.296"), call=lambda spec, cancel: None)

    def test_a_restart_charges_each_running_turn_its_own_limit_and_resumes_nothing(self):
        rec = staffing_record()
        rec["turns"][0].update(state="running", attempts=1, started_at=time.time())
        self.save(rec)
        other = staffing_record("s-ffffffffffff")
        done(other, 1)
        done(other, 2)
        other["turns"][2].update(state="running", attempts=1, started_at=time.time())
        self.save(other)
        board = self.board()
        first, second = st.load(rec["id"]), st.load(other["id"])
        self.assertEqual([(t["state"], (t["evidence"] or {}).get("cost_usd")) for t in first["turns"]],
                         [("interrupted", "0.2"), ("interrupted", None), ("interrupted", None)])
        self.assertEqual((second["turns"][2]["state"], second["turns"][2]["evidence"]["cost_usd"],
                          second["turns"][2]["evidence"]["cost_source"]), ("interrupted", "0.5", "worst_case"))
        self.assertEqual(board.room(second), Decimal("2") - Decimal("0.52"))

    def test_a_retry_is_planned_from_the_ceos_turn(self):
        rec = done(staffing_record(), 1)
        done(rec, 2)
        rec["turns"][2].update(state="failed", attempts=1, error_code="invalid_output", ended_at=time.time())
        self.save(rec)
        board = self.board()
        _, turn, again = board._retry_plan(rec["id"], 3, None)
        self.assertEqual((turn["kind"], again), ("proposal", False))
        speaker = staffing_record("s-ffffffffffff")
        speaker["turns"][0].update(state="failed", attempts=1, error_code="cli_error", ended_at=time.time())
        done(speaker, 2)
        done(speaker, 3)
        self.save(speaker)
        _, turn, again = board._retry_plan(speaker["id"], 1, None)
        self.assertEqual((turn["kind"], again), ("opinion", True))  # the CEO is asked again after a speaker's retry

        def adopt(r):
            r["chairman"].update(state="adopted", at=time.time())
        board._update(speaker["id"], adopt)
        with self.assertRaises(mt.MeetingError) as caught:
            board._retry_plan(speaker["id"], 1, None)
        self.assertEqual(caught.exception.code, "already_decided")

    def test_the_day_counts_staffing_turns_and_skips_a_damaged_record(self):
        rec = self.save(done(staffing_record(), 1, cost="0.03"))
        bad = self.save(staffing_record("s-ffffffffffff"))
        st.StaffingStore(bad["id"]).path().write_text("{broken")
        board = self.board()
        self.assertEqual([r["id"] for r in board.spend_records()], [rec["id"]])
        self.assertEqual(board._day(), Decimal("0.03"))
