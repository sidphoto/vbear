"""P20: the page's tables for the Antigravity (AGY) camp are the backend's. app.js repeats the tool -> family table
because it has no import; these keep the two equal.

Run: python3 -m unittest tests.test_p20_agy_page -v
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


class FrontEndTableTests(unittest.TestCase):
    SOURCE = (REPO / "web" / "app.js").read_text(encoding="utf-8")

    def js_object(self, name: str) -> dict:
        m = re.search(r"const %s = \{([^}]*)\};" % re.escape(name), self.SOURCE)
        self.assertIsNotNone(m, name)
        return dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", m.group(1)))

    def test_team_tool_family_is_the_backends_table(self):
        self.assertEqual(self.js_object("TEAM_TOOL_FAMILY"), agent_profiles.TOOL_FAMILY)

    def test_the_card_tool_labels_cover_exactly_the_known_tools(self):
        self.assertEqual(set(self.js_object("CARD_TOOL_LABEL")), set(agent_profiles.KNOWN_TOOLS))
        self.assertEqual(set(self.js_object("CARD_TOOL_SHORT")), set(agent_profiles.KNOWN_TOOLS))
        self.assertEqual(list(self.js_object("CARD_TOOL_LABEL")), list(agent_profiles.TOOL_ORDER))

    def test_the_camp_and_the_species_of_agy_are_google_and_the_fox(self):
        self.assertEqual(self.js_object("OFFICE_TOOL_CAMP").get("agy"), "google")
        self.assertEqual(self.js_object("OFFICE_TOOL_SPECIES").get("agy"), "fox")


if __name__ == "__main__":
    unittest.main()
