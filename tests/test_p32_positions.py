"""P32-2: the suggested positions of a role card are the one-person-company division of work, nine of them in two
tiers. The table lives in vbear/agent_profiles.py (POSITION_TABLE); app.js repeats it because a card has to be drawn
without the catalog, and these tests keep the two equal. A position is a label: nothing here may carry a permission.

Run: python3 -m unittest tests.test_p32_positions -v
"""

from __future__ import annotations

import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_profiles  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
IDS = ["planner", "executor", "qa", "reviewer", "product", "research", "business", "design", "records"]
# names of a private team never go into a public repository (the screens say generic job titles)
PRIVATE_WORDS = ("Orion", "Forge", "Aegis", "Sentinel", "Atlas", "Mercury", "Scout", "Ledger", "Herdr", "JAOS")


class PositionTableTests(unittest.TestCase):
    def test_nine_positions_in_the_order_the_screen_shows_them(self):
        self.assertEqual([r["id"] for r in agent_profiles.POSITION_TABLE], IDS)
        self.assertEqual(list(agent_profiles.POSITIONS), IDS)

    def test_the_three_old_ids_keep_their_meaning(self):
        # a card saved before P32 carries planner / executor / reviewer in the browser; those ids must stay
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertEqual([rows[i]["label"] for i in ("planner", "executor", "reviewer")], ["規劃", "執行", "獨立審查"])
        self.assertEqual([rows[i]["glyph"] for i in ("planner", "executor", "reviewer")], ["規", "執", "審"])

    def test_two_tiers_and_the_task_card_place_each_position_belongs_to(self):
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertEqual([i for i in IDS if rows[i]["tier"] == "team"], ["planner", "executor", "qa", "reviewer"])
        self.assertEqual([i for i in IDS if rows[i]["tier"] == "staff"],
                         ["product", "research", "business", "design", "records"])
        # qa and the independent review both fit the review places; the staff take no place on a task card
        self.assertEqual({i: rows[i]["slot"] for i in IDS}, {
            "planner": "planner", "executor": "executor", "qa": "reviewer", "reviewer": "reviewer",
            "product": None, "research": None, "business": None, "design": None, "records": None})

    def test_every_row_has_exactly_the_fields_and_words(self):
        for r in agent_profiles.POSITION_TABLE:
            self.assertEqual(list(r), ["id", "label", "glyph", "tier", "slot", "duty", "reminder"], r["id"])
            self.assertEqual(len(r["glyph"]), 1, r["id"])
            self.assertTrue(r["label"].strip() and r["duty"].strip() and r["reminder"].strip(), r["id"])
        self.assertEqual(len({r["glyph"] for r in agent_profiles.POSITION_TABLE}), 9, "one character each")
        self.assertEqual(len({r["label"] for r in agent_profiles.POSITION_TABLE}), 9)

    def test_the_reminders_that_a_position_is_a_division_of_work_not_a_limit(self):
        rows = {r["id"]: r for r in agent_profiles.POSITION_TABLE}
        self.assertIn("只回報", rows["qa"]["reminder"])
        self.assertIn("沒實際跑過不算通過", rows["qa"]["reminder"])
        self.assertIn("不重寫", rows["reviewer"]["reminder"])
        # the reminders are words to put in the task card's goal; no row claims VBear enforces them
        for r in agent_profiles.POSITION_TABLE:
            self.assertNotRegex(r["reminder"] + r["duty"], r"(已限制|已擋住|保證|強制)", r["id"])

    def test_no_row_carries_a_permission_and_no_private_name_is_in_the_words(self):
        for r in agent_profiles.POSITION_TABLE:
            self.assertFalse({"permission_intents", "intents"} & set(r), r["id"])
            for w in PRIVATE_WORDS:
                self.assertNotIn(w, " ".join(str(v) for v in r.values()), r["id"])

    def test_the_starter_deck_stays_the_three_cards_of_the_task_card(self):
        self.assertEqual([c["position"] for c in agent_profiles.STARTER_DECK], ["planner", "executor", "reviewer"])


class FrontEndPositionTableTests(unittest.TestCase):
    SOURCE = (REPO / "web" / "app.js").read_text(encoding="utf-8")

    def page_rows(self) -> list[dict]:
        m = re.search(r"const CARD_POSITION_TABLE = \[(.*?)\n\];", self.SOURCE, re.S)
        self.assertIsNotNone(m, "app.js has no CARD_POSITION_TABLE")
        rows = []
        for r in re.finditer(r"\{\s*id:\s*\"(\w+)\",\s*label:\s*\"([^\"]*)\",\s*glyph:\s*\"([^\"]*)\",\s*tier:\s*\"(\w+)\",\s*"
                             r"slot:\s*(null|\"\w+\"),\s*duty:\s*\"([^\"]*)\",\s*reminder:\s*\"([^\"]*)\"\s*\}", m.group(1)):
            rows.append({"id": r.group(1), "label": r.group(2), "glyph": r.group(3), "tier": r.group(4),
                         "slot": None if r.group(5) == "null" else r.group(5).strip('"'),
                         "duty": r.group(6), "reminder": r.group(7)})
        return rows

    def test_the_page_table_is_the_backends(self):
        self.assertEqual(self.page_rows(), [dict(r) for r in agent_profiles.POSITION_TABLE])

    def test_the_page_draws_its_constants_from_that_table(self):
        # one source in the page too: the labels and the badges are made from the table, not typed a second time
        self.assertIn("const CARD_POSITION_LABEL = Object.fromEntries(CARD_POSITION_TABLE.map(", self.SOURCE)
        self.assertIn("const CARD_POSITIONS = CARD_POSITION_TABLE.map(", self.SOURCE)
        m = re.search(r"const CARD_POSITION_BADGES = \{(.*?)\n\};", self.SOURCE, re.S)
        self.assertIsNotNone(m)
        self.assertIn("CARD_POSITION_TABLE.map(", m.group(1))
        self.assertNotIn("glyph: \"規\"", m.group(1), "no glyph is typed a second time")


if __name__ == "__main__":
    unittest.main()
