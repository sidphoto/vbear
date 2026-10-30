"""Which skill a card of each camp can take, in Python (P35-1): the same answers as web/app.js skillCompatible and the
wizard's default list (skillPickPlan), held to one table (tests/skill_fit_cases.json) that tests/frontend/skill_fit.cjs
holds the page to."""
import json
import unittest
from pathlib import Path

from vbear import skill_fit

CASES = json.loads((Path(__file__).resolve().parent / "skill_fit_cases.json").read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    def test_the_states_never_listed_are_the_pages(self):
        self.assertEqual(sorted(skill_fit.NEVER_LISTED), CASES["never_listed"])

    def test_every_camp_takes_exactly_the_skills_the_page_lets_it_take(self):
        for tool in CASES["tools"]:
            got = sorted(s["skill_id"] for s in CASES["skills"] if skill_fit.skill_compatible(s, tool))
            self.assertEqual(got, CASES["expect"][tool]["compatible"], tool)

    def test_every_camp_lists_exactly_what_the_wizard_lists(self):
        for tool in CASES["tools"]:
            got = sorted(s["skill_id"] for s in skill_fit.pick_listed(CASES["skills"], tool))
            self.assertEqual(got, CASES["expect"][tool]["listed"], tool)


class RowTests(unittest.TestCase):
    def test_the_rules_in_words(self):
        claude, shared, agy = {"tool": "claude"}, {"tool": "shared"}, {"tool": "agy"}
        self.assertTrue(skill_fit.skill_compatible(claude, "claude"))
        self.assertFalse(skill_fit.skill_compatible(claude, "codex"))
        self.assertTrue(skill_fit.skill_compatible(shared, "codex"))
        self.assertFalse(skill_fit.skill_compatible(shared, "agy"))  # the shared store is AGY's only when its config lists it
        self.assertTrue(skill_fit.skill_compatible({"tool": "shared", "read_by": ["agy"]}, "agy"))
        self.assertTrue(skill_fit.skill_compatible(agy, "agy"))
        self.assertFalse(skill_fit.skill_compatible(claude, "shared"))
        for nothing in (None, {}, [], "claude", {"tool": None}):
            self.assertFalse(skill_fit.skill_compatible(nothing, "claude"), nothing)
            self.assertFalse(skill_fit.skill_usable(nothing, "agy"), nothing)

    def test_a_tools_own_skill_counts_only_when_active_and_another_only_when_not_dead(self):
        self.assertTrue(skill_fit.skill_usable({"tool": "claude", "activation": "active"}, "claude"))
        self.assertFalse(skill_fit.skill_usable({"tool": "claude", "activation": "unknown"}, "claude"))
        self.assertTrue(skill_fit.skill_usable({"tool": "shared", "activation": "unknown"}, "claude"))
        self.assertFalse(skill_fit.skill_usable({"tool": "shared", "activation": "archived"}, "claude"))
        self.assertTrue(skill_fit.skill_usable({"tool": "agy", "activation": "unknown"}, "agy"))
        self.assertFalse(skill_fit.skill_usable({"tool": "codex", "activation": "active"}, "claude"))  # not compatible

    def test_the_tools_a_skill_fits(self):
        self.assertEqual(skill_fit.fits({"tool": "shared", "activation": "unknown"}), ["claude", "codex", "shared"])
        self.assertEqual(skill_fit.fits({"tool": "shared", "activation": "unknown", "read_by": ["agy"]}), ["claude", "codex", "agy", "shared"])
        self.assertEqual(skill_fit.fits({"tool": "codex", "activation": "active"}), ["codex"])
        self.assertEqual(skill_fit.fits({"tool": "codex", "activation": "disabled"}), [])


if __name__ == "__main__":
    unittest.main()
