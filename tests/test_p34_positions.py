"""P34-1: the suggested positions of a role card are the seven positions of a one-person company plus VBear's own
review gate, in the order the screen shows them. The table lives in vbear/agent_profiles.py (POSITION_TABLE); app.js
repeats it because a card has to be drawn without the catalog, and these tests keep the two equal. A position is a
label: nothing here may carry a permission. The ids of v0.9.0 that no longer exist are in RETIRED_POSITIONS.

Run: python3 -m unittest tests.test_p34_positions -v
"""

from __future__ import annotations

import hashlib
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_profiles, model_options  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
IDS = ["planner", "executor", "social", "art", "pm", "legal", "accountant", "reviewer"]
# names of a private team never go into a public repository (the screens say generic job titles); the names
# themselves are kept out of this file too, so the test compares the first 16 hex of the sha256 of each lower-cased word
PRIVATE_WORD_HASHES = frozenset((
    "2b7847b7b705781d",
    "3608e4bd0e693177",
    "598f7a741a1e3a05",
    "71b41d6dd48dc58e",
    "78193ef266c1e3c2",
    "7c82602500857aa6",
    "8cd0001a4c013ab3",
    "a925617886e8799c",
    "b769a6983b42d565",
    "fe14010b4fe83303",
))


class PositionTableTests(unittest.TestCase):
    def test_eight_rows_in_the_order_the_screen_shows_them(self):
        self.assertEqual([r["id"] for r in agent_profiles.POSITION_TABLE], IDS)
        self.assertEqual(list(agent_profiles.POSITIONS), IDS)

    def test_the_three_old_ids_keep_their_meaning_under_the_new_names(self):
        # a card saved before P34 carries planner / executor / reviewer in the browser; those ids stay, the words change
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertEqual([rows[i]["label"] for i in ("planner", "executor", "reviewer")], ["CEO", "全端工程師", "獨立審查"])
        self.assertEqual([rows[i]["glyph"] for i in ("planner", "executor", "reviewer")], ["長", "工", "審"])
        self.assertEqual([rows[i]["slot"] for i in ("planner", "executor", "reviewer")], ["planner", "executor", "reviewer"])

    def test_seven_positions_and_the_review_gate_which_is_not_one_of_them(self):
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertEqual([i for i in IDS if rows[i]["tier"] == "team"], ["planner", "executor", "social", "art"])
        self.assertEqual([i for i in IDS if rows[i]["tier"] == "staff"], ["pm", "legal", "accountant"])
        # the independent review is VBear's own gate (its own tier), so it is not counted among the seven positions
        self.assertEqual([i for i in IDS if rows[i]["tier"] == "gate"], ["reviewer"])
        self.assertEqual(len([r for r in agent_profiles.POSITION_TABLE if r["tier"] in ("team", "staff")]), 7)

    def test_the_task_card_place_each_position_suits(self):
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertEqual({i: rows[i]["slot"] for i in IDS}, {
            "planner": "planner", "executor": "executor", "social": "executor", "art": "executor",
            "pm": "planner", "legal": None, "accountant": None, "reviewer": "reviewer"})

    def test_every_row_has_exactly_the_fields_and_words(self):
        for r in agent_profiles.POSITION_TABLE:
            self.assertEqual(list(r), ["id", "label", "glyph", "tier", "slot", "duty", "reminder", "suggested_tool",
                                       "suggested_model_alias"], r["id"])
            self.assertEqual(len(r["glyph"]), 1, r["id"])
            self.assertTrue(r["label"].strip() and r["duty"].strip() and r["reminder"].strip(), r["id"])
        self.assertEqual(len({r["glyph"] for r in agent_profiles.POSITION_TABLE}), 8, "one character each")
        self.assertEqual(len({r["label"] for r in agent_profiles.POSITION_TABLE}), 8)

    def test_the_suggested_tool_and_model_are_only_suggestions_from_known_lists(self):
        for r in agent_profiles.POSITION_TABLE:
            self.assertIn(r["suggested_tool"], agent_profiles.KNOWN_TOOLS - {"shared"}, r["id"])
            alias = r["suggested_model_alias"]
            if r["suggested_tool"] == "claude":
                self.assertIn(alias, model_options.CLAUDE_ALIASES, r["id"])
            else:
                self.assertIsNone(alias, r["id"])
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertEqual(rows["art"]["suggested_tool"], "agy")      # VBear does not launch it: the screens say so
        self.assertEqual(rows["reviewer"]["suggested_tool"], "codex")

    def test_the_words_say_what_each_position_does_and_claim_no_enforcement(self):
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertIn("只回報", rows["reviewer"]["reminder"])
        self.assertIn("不重寫", rows["reviewer"]["reminder"])
        self.assertIn("草稿", rows["social"]["reminder"])
        self.assertIn("查無出處", rows["legal"]["reminder"])
        self.assertIn("程式", rows["accountant"]["reminder"])
        self.assertIn("董事長", rows["planner"]["duty"])
        # the reminders are words to put in the task card's goal; no row claims VBear enforces them
        for r in agent_profiles.POSITION_TABLE:
            self.assertNotRegex(r["reminder"] + r["duty"], r"(已限制|已擋住|保證|強制)", r["id"])

    def test_no_row_carries_a_permission_and_no_private_name_is_in_the_words(self):
        for r in agent_profiles.POSITION_TABLE:
            self.assertFalse({"permission_intents", "intents"} & set(r), r["id"])
            words = re.findall(r"[A-Za-z]+", " ".join(str(v) for v in r.values()))
            for w in words:
                self.assertNotIn(hashlib.sha256(w.lower().encode()).hexdigest()[:16], PRIVATE_WORD_HASHES, r["id"])

    def test_the_starter_deck_stays_the_three_cards_and_the_executor_is_named_by_its_position(self):
        self.assertEqual([c["position"] for c in agent_profiles.STARTER_DECK], ["planner", "executor", "reviewer"])
        self.assertEqual([c["name"] for c in agent_profiles.STARTER_DECK], ["CEO", "全端工程師", "審查員"])

    def test_every_position_gets_the_one_verified_combination(self):
        # a position is a label: the starter deck is the only place intents are suggested, and all three cards take
        # VERIFIED_INTENTS, which is also what a card with no position gets (agent_launch is a whitelist on it)
        self.assertEqual(agent_profiles.VERIFIED_INTENTS, {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"})
        for card in agent_profiles.STARTER_DECK:
            self.assertEqual(card["permission_intents"], agent_profiles.VERIFIED_INTENTS, card["key"])


class RetiredPositionTests(unittest.TestCase):
    """The ids that only the unreleased v0.9.0 wrote, kept readable: where each is shown, and that none is accepted."""

    def test_the_table_of_retired_ids(self):
        self.assertEqual(agent_profiles.RETIRED_POSITIONS, {
            "qa": {"label": "品質驗證", "to": "reviewer"},
            "product": {"label": "產品", "to": "pm"},
            "records": {"label": "紀錄", "to": "pm"},
            "design": {"label": "設計", "to": "art"},
            "research": {"label": "研究", "to": None},
            "business": {"label": "商業", "to": None},
        })

    def test_a_retired_id_maps_to_a_listed_position_or_to_none_and_is_never_listed(self):
        for old, row in agent_profiles.RETIRED_POSITIONS.items():
            self.assertNotIn(old, agent_profiles.POSITIONS, old)
            self.assertTrue(row["to"] is None or row["to"] in agent_profiles.POSITIONS, old)
            self.assertTrue(row["label"].strip(), old)

    def test_the_old_ids_of_v089_are_not_retired(self):
        for kept in ("planner", "executor", "reviewer"):
            self.assertNotIn(kept, agent_profiles.RETIRED_POSITIONS)
            self.assertIn(kept, agent_profiles.POSITIONS)


class FrontEndPositionTableTests(unittest.TestCase):
    SOURCE = (REPO / "web" / "app.js").read_text(encoding="utf-8")

    def page_rows(self) -> list[dict]:
        m = re.search(r"const CARD_POSITION_TABLE = \[(.*?)\n\];", self.SOURCE, re.S)
        self.assertIsNotNone(m, "app.js has no CARD_POSITION_TABLE")
        rows = []
        for r in re.finditer(r"\{\s*id:\s*\"(\w+)\",\s*label:\s*\"([^\"]*)\",\s*glyph:\s*\"([^\"]*)\",\s*tier:\s*\"(\w+)\",\s*"
                             r"slot:\s*(null|\"\w+\"),\s*duty:\s*\"([^\"]*)\",\s*reminder:\s*\"([^\"]*)\",\s*"
                             r"suggested_tool:\s*\"(\w+)\",\s*suggested_model_alias:\s*(null|\"\w+\")\s*\}", m.group(1)):
            rows.append({"id": r.group(1), "label": r.group(2), "glyph": r.group(3), "tier": r.group(4),
                         "slot": None if r.group(5) == "null" else r.group(5).strip('"'),
                         "duty": r.group(6), "reminder": r.group(7), "suggested_tool": r.group(8),
                         "suggested_model_alias": None if r.group(9) == "null" else r.group(9).strip('"')})
        return rows

    def test_the_page_table_is_the_backends(self):
        self.assertEqual(self.page_rows(), [dict(r) for r in agent_profiles.POSITION_TABLE])

    def test_the_page_retired_table_is_the_backends(self):
        m = re.search(r"const CARD_RETIRED_POSITIONS = \{(.*?)\n\};", self.SOURCE, re.S)
        self.assertIsNotNone(m, "app.js has no CARD_RETIRED_POSITIONS")
        rows = {}
        for r in re.finditer(r"(\w+):\s*\{\s*label:\s*\"([^\"]*)\",\s*to:\s*(null|\"\w+\")\s*\}", m.group(1)):
            rows[r.group(1)] = {"label": r.group(2), "to": None if r.group(3) == "null" else r.group(3).strip('"')}
        self.assertEqual(rows, agent_profiles.RETIRED_POSITIONS)

    def test_the_page_draws_its_constants_from_that_table(self):
        # one source in the page too: the labels and the badges are made from the table, not typed a second time
        self.assertIn("const CARD_POSITION_LABEL = Object.fromEntries(CARD_POSITION_TABLE.map(", self.SOURCE)
        self.assertIn("const CARD_POSITIONS = CARD_POSITION_TABLE.map(", self.SOURCE)
        m = re.search(r"const CARD_POSITION_BADGES = \{(.*?)\n\};", self.SOURCE, re.S)
        self.assertIsNotNone(m)
        self.assertIn("CARD_POSITION_TABLE.map(", m.group(1))
        self.assertNotIn("glyph: \"長\"", m.group(1), "no glyph is typed a second time")


if __name__ == "__main__":
    unittest.main()
