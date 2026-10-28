"""P32-4: which position a role template (a profession) probably fits, worked out from its name and the first sentence
of its author's description by a small visible keyword table. A guess, never an author's claim: it always says
origin=derived and the keyword that matched.

Run: python3 -m unittest tests.test_role_departments -v
"""

from __future__ import annotations

import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_profiles, role_departments  # noqa: E402

POSITION_IDS = [r["id"] for r in agent_profiles.POSITION_TABLE]


def dept(name, description=None):
    found = role_departments.department(name, description)
    return found["id"] if found else None


class DepartmentByNameTests(unittest.TestCase):
    def test_a_name_with_a_clear_word_lands_in_that_position(self):
        for name, expected in [
            ("Trend Researcher", "research"), ("Security Auditor", "reviewer"), ("Code Reviewer", "reviewer"),
            ("Test Engineer", "qa"), ("Reality Checker", "qa"), ("Performance Benchmarker", "qa"),
            ("Product Manager", "product"), ("Sprint Prioritizer", "product"), ("Feedback Synthesizer", "product"),
            ("Brand Guardian", "business"), ("TikTok Strategist", "business"), ("App Store Optimizer", "business"),
            ("UI Designer", "design"), ("UX Researcher", "research"), ("Visual Storyteller", "design"),
            ("Whimsy Injector", "design"), ("Archivist", "records"), ("Meeting Scribe", "records"),
            ("Studio Producer", "planner"), ("Project Shepherd", "planner"), ("Agents Orchestrator", "planner"),
            ("Frontend Developer", "executor"), ("Backend Architect", "executor"), ("Rapid Prototyper", "executor"),
            ("DevOps Automator", "executor"), ("Technical Writer", "executor"),
        ]:
            self.assertEqual(dept(name), expected, name)

    def test_the_answer_says_which_keyword_matched_and_that_it_is_a_guess(self):
        found = role_departments.department("Trend Researcher", None)
        self.assertEqual(found, {"id": "research", "keyword": "researcher", "origin": "derived"})
        self.assertEqual(role_departments.department("Archivist", None)["keyword"], "archiv")

    def test_every_answer_is_one_of_the_nine_positions_or_nothing(self):
        for name in ("Trend Researcher", "Brand Guardian", "Zebra", "Ledger Keeper", "", "vercel:ai-architect"):
            found = role_departments.department(name, None)
            self.assertTrue(found is None or found["id"] in POSITION_IDS, name)

    def test_names_that_look_like_a_keyword_but_are_not_are_not_taken_for_it(self):
        # a short word has to be a whole word, so these do not become ui, test or art
        self.assertEqual(dept("Mobile App Builder"), "executor")
        self.assertEqual(dept("Latest News Writer"), "executor")
        self.assertNotEqual(dept("Latest News Writer"), "qa")
        self.assertEqual(dept("Smart Planner"), "planner")
        self.assertNotEqual(dept("Smart Planner"), "design")
        self.assertIsNone(dept("Guidance Counselor"))     # "guidance" holds "ui" and "dance" but is neither
        self.assertIsNone(dept("Contest Judge"))          # "contest" holds "test"
        self.assertIsNone(dept("Partner"))                # "partner" holds "art"

    def test_camel_case_and_punctuation_split_into_words(self):
        self.assertEqual(dept("TrendResearcher"), "research")
        self.assertEqual(dept("vercel:ai-architect"), "executor")
        self.assertEqual(dept("security_auditor"), "reviewer")
        self.assertEqual(dept("QA-lead"), "qa")

    def test_the_priority_order_is_reviewer_qa_research_product_business_design_records_planner_executor(self):
        self.assertEqual(dept("Security Engineer"), "reviewer")          # reviewer before executor
        self.assertEqual(dept("Test Planner"), "qa")                     # qa before planner
        self.assertEqual(dept("Research Engineer"), "research")          # research before executor
        self.assertEqual(dept("Product Designer"), "product")            # product before design
        self.assertEqual(dept("Brand Designer"), "business")             # business before design
        self.assertEqual(dept("Design Archivist"), "design")             # design before records
        self.assertEqual(dept("Records Manager"), "records")             # records before planner
        self.assertEqual(dept("Lead Developer"), "planner")              # planner before executor

    def test_chinese_names_match_by_the_characters(self):
        for name, expected in [("趨勢研究員", "research"), ("資安稽核", "reviewer"), ("品質驗證員", "qa"),
                               ("產品經理", "product"), ("品牌守護者", "business"), ("視覺設計師", "design"),
                               ("會議秘書", "records"), ("專案統籌", "planner"), ("前端工程師", "executor")]:
            self.assertEqual(dept(name), expected, name)


class DepartmentByDescriptionTests(unittest.TestCase):
    def test_the_name_wins_over_the_description(self):
        self.assertEqual(dept("Trend Researcher", "Reviews pull requests and audits code."), "research")

    def test_with_no_word_in_the_name_the_first_sentence_of_the_description_decides(self):
        self.assertEqual(dept("Zebra", "Finds and analyzes new market trends. Also writes code."), "research")
        self.assertEqual(dept("Zebra", "Audits the code for security problems."), "reviewer")

    def test_only_the_first_sentence_and_the_first_200_characters_count(self):
        self.assertIsNone(dept("Zebra", "A friendly helper. Audits the code for security problems."))
        self.assertIsNone(dept("Zebra", ("x " * 120) + "audits the code"))
        self.assertEqual(dept("Zebra", "Audits the code" + " ok" * 10), "reviewer")

    def test_a_description_that_is_not_text_gives_nothing(self):
        for value in (None, "", "   ", 5, ["audit"], {"value": "audit"}):
            self.assertIsNone(dept("Zebra", value), repr(value))

    def test_a_name_that_is_not_text_gives_nothing(self):
        for value in (None, 5, [], {}):
            self.assertIsNone(role_departments.department(value, None), repr(value))
        self.assertIsNone(dept("", ""))


if __name__ == "__main__":
    unittest.main()
