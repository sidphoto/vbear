"""P35-2: the security model says how fast a meeting is (the effort and the clock) and what a staffing meeting is."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _flat(text: str) -> str:
    return " ".join(text.split())


class SecurityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = (ROOT / "docs" / "SECURITY-MODEL.md").read_text(encoding="utf-8")

    def section(self, title: str) -> str:
        return _flat(self.model.split(f"## {title}", 1)[1].split("\n## ", 1)[0])

    def test_meetings_says_the_effort_is_low_or_medium_and_how_the_boundary_still_holds(self):
        meetings = self.section("Meetings (tool-less headless speech)")
        for phrase in ("`--effort low`", "`--effort medium`", "`meeting_speed`", "never asks for high effort",
                       "ran without `--effort`", "checks its own init event", "does not know `--effort`"):
            self.assertIn(phrase, meetings)

    def test_meetings_says_a_meeting_runs_on_a_clock_with_three_minutes_kept_for_the_ceo(self):
        meetings = self.section("Meetings (tool-less headless speech)")
        for phrase in ("15 by default, 5 to 30", "three minutes before the end", "`time_up`", "時間到沒發言",
                       "a clock of its own", "not inside `meeting_limits`"):
            self.assertIn(phrase, meetings)


if __name__ == "__main__":
    unittest.main()
