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
            ("Security Auditor", "reviewer"), ("Code Reviewer", "reviewer"), ("Test Engineer", "reviewer"),
            ("Reality Checker", "reviewer"), ("Performance Benchmarker", "reviewer"),
            ("Legal Counsel", "legal"), ("Compliance Officer", "legal"), ("Privacy Lawyer", "legal"),
            ("Accountant", "accountant"), ("Budget Analyst", "accountant"), ("Finance Controller", "accountant"),
            ("Social Media Manager", "social"), ("TikTok Strategist", "social"), ("Community Manager", "social"),
            ("SEO Specialist", "social"),
            ("Art Director", "art"), ("UI Designer", "art"), ("Visual Storyteller", "art"), ("Whimsy Injector", "art"),
            ("Project Manager", "pm"), ("Product Manager", "pm"), ("Sprint Prioritizer", "pm"),
            ("Feedback Synthesizer", "pm"), ("Archivist", "pm"), ("Meeting Scribe", "pm"),
            ("Studio Producer", "planner"), ("Project Shepherd", "planner"), ("Agents Orchestrator", "planner"),
            ("Chief Executive", "planner"),
            ("Frontend Developer", "executor"), ("Backend Architect", "executor"), ("Rapid Prototyper", "executor"),
            ("DevOps Automator", "executor"), ("Technical Writer", "executor"),
        ]:
            self.assertEqual(dept(name), expected, name)

    def test_the_answer_says_which_keyword_matched_and_that_it_is_a_guess(self):
        found = role_departments.department("Legal Counsel", None)
        self.assertEqual(found, {"id": "legal", "keyword": "legal", "origin": "derived"})
        self.assertEqual(role_departments.department("Archivist", None),
                         {"id": "pm", "keyword": "archiv", "origin": "derived"})

    def test_every_answer_is_one_of_the_eight_positions_or_nothing(self):
        for name in ("Trend Researcher", "Brand Guardian", "Zebra", "Ledger Keeper", "", "vercel:ai-architect"):
            found = role_departments.department(name, None)
            self.assertTrue(found is None or found["id"] in POSITION_IDS, name)

    def test_no_retired_position_is_ever_the_answer(self):
        for name in ("Trend Researcher", "Brand Guardian", "Quality Tester", "Product Designer", "Records Manager",
                     "Market Analyst", "Sales Lead"):
            found = role_departments.department(name, None)
            self.assertTrue(found is None or found["id"] not in agent_profiles.RETIRED_POSITIONS, name)

    def test_names_that_look_like_a_keyword_but_are_not_are_not_taken_for_it(self):
        # a short word has to be a whole word, so these do not become ui, test, art or law
        self.assertEqual(dept("Mobile App Builder"), "executor")
        self.assertEqual(dept("Latest News Writer"), "executor")
        self.assertNotEqual(dept("Latest News Writer"), "reviewer")
        self.assertEqual(dept("Smart Planner"), "planner")
        self.assertNotEqual(dept("Smart Planner"), "art")
        self.assertIsNone(dept("Guidance Counselor"))     # "guidance" holds "ui" and "dance"; "counselor" is not "counsel"
        self.assertIsNone(dept("Contest Judge"))          # "contest" holds "test"
        self.assertIsNone(dept("Partner"))                # "partner" holds "art"
        self.assertIsNone(dept("Lawn Mower"))             # "lawn" holds "law"
        self.assertIsNone(dept("Taxonomy Keeper"))        # "taxonomy" holds "tax"
        self.assertIsNone(dept("Pmo Helper"))             # "pmo" holds "pm"
        self.assertNotEqual(dept("Smart Contract Developer"), "legal")

    def test_camel_case_and_punctuation_split_into_words(self):
        self.assertEqual(dept("LegalCounsel"), "legal")
        self.assertEqual(dept("vercel:ai-architect"), "executor")
        self.assertEqual(dept("security_auditor"), "reviewer")
        self.assertEqual(dept("QA-lead"), "reviewer")

    def test_the_priority_order_is_reviewer_legal_accountant_social_art_pm_planner_executor(self):
        self.assertEqual(role_departments.PRIORITY,
                         ["reviewer", "legal", "accountant", "social", "art", "pm", "planner", "executor"])
        self.assertEqual(dept("Security Engineer"), "reviewer")          # reviewer before executor
        self.assertEqual(dept("Compliance Auditor"), "reviewer")         # reviewer before legal
        self.assertEqual(dept("Legal Finance Advisor"), "legal")         # legal before accountant
        self.assertEqual(dept("Financial Social Planner"), "accountant") # accountant before social
        self.assertEqual(dept("Social Media Manager"), "social")         # social before pm and planner
        self.assertEqual(dept("Social Designer"), "social")              # social before art
        self.assertEqual(dept("Art Director"), "art")                    # art before planner ("director")
        self.assertEqual(dept("Product Designer"), "art")                # art before pm
        self.assertEqual(dept("Design Archivist"), "art")                # art before pm
        self.assertEqual(dept("Project Manager"), "pm")                  # pm before planner ("manager")
        self.assertEqual(dept("Records Manager"), "pm")
        self.assertEqual(dept("Lead Developer"), "planner")              # planner before executor

    def test_chinese_names_match_by_the_characters(self):
        for name, expected in [("資安稽核", "reviewer"), ("品質驗證員", "reviewer"), ("法務專員", "legal"),
                               ("合規顧問", "legal"), ("會計師", "accountant"), ("財務分析", "accountant"),
                               ("社群小編", "social"), ("視覺設計師", "art"), ("藝術總監", "art"),
                               ("產品經理", "pm"), ("會議秘書", "pm"), ("專案統籌", "planner"),
                               ("前端工程師", "executor")]:
            self.assertEqual(dept(name), expected, name)


class DepartmentByDescriptionTests(unittest.TestCase):
    def test_the_name_wins_over_the_description(self):
        self.assertEqual(dept("Legal Counsel", "Reviews pull requests and audits code."), "legal")

    def test_with_no_word_in_the_name_the_first_sentence_of_the_description_decides(self):
        self.assertEqual(dept("Zebra", "Keeps the books and prepares the budget. Also writes code."), "accountant")
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
