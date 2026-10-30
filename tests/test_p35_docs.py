"""P35-2: the security model says how fast a meeting is (the effort and the clock) and what a staffing meeting is.
P35-4: the CHANGELOG's v0.10.0, both READMEs and the reference say what a staffing meeting is, how it is adopted, and what
going back to v0.9.0 does; every phrase of the page they quote is one the page has."""

from __future__ import annotations

import re
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

    def test_staffing_meetings_have_a_section_of_their_own(self):
        staffing = self.section("Staffing meetings (組隊會議)")
        for phrase in (
                # who speaks, and in which order
                "VBear suggests", "a fixed table", "each speaker says once, alone", "then the CEO writes a staffing proposal",
                "the CEO is not asked", "A disabled card cannot speak", "may be proposed",
                # what is sent
                "never its id", "`C1`", "never its folder", "fresh Chinese summary", "`BEGIN/END_UNTRUSTED_JSON_STRING`",
                "whatever the speakers write", "`too_large`",
                # the call, the worker and the money
                "the meetings' call", "`--effort`", "`meeting-worker.lock`", "`meeting-worker.blocked`", "never at the same time",
                "`meeting_limits.per_call_usd`", "`staffing_limits.proposal_call_usd`", "`staffing_limits.total_usd`",
                "the same day as the meetings", '`includes: ["meetings", "staffing"]`', "worst case",
                # what it is not
                "No rule of the meetings (R1–R8)", "creates no card, inserts no skill", "主控台記錄（未驗證身分）",
                "`<state>/staffing/s-<12 hex>.json`", "`/api/staffing/suggest?task_id=`", "`DELETE /api/staffing/<id>`"):
            self.assertIn(phrase, staffing)


    def test_staffing_meetings_say_how_an_adoption_is_made(self):
        staffing = self.section("Staffing meetings (組隊會議)")
        for phrase in ("**Adopting.**", "an endpoint VBear already had", "this page's memory", "flows.json",
                       "建立隊伍", "this browser"):
            self.assertIn(phrase, staffing)


class ChangelogV010Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.section = text[text.index("## v0.10.0"):text.index("## v0.9.0")]
        cls.flat = _flat(cls.section)
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_one_release_with_a_summary_first(self):
        heading = self.section.split("\n", 1)[0]
        self.assertIn("staffing meetings", heading)
        self.assertFalse(self.section.split("\n\n")[1].startswith("- "), "a summary comes before the list")

    def test_it_covers_the_staffing_meeting_its_money_and_the_draft(self):
        for phrase in ("組隊會議", "請 CEO 組隊", "`#/staffing?task=`", "固定規則，不是 AI 判斷", "開始組隊會議", "`C1`", "「找不到」",
                       "`staffing/`", "`staffing_limits.proposal_call_usd`", "`staffing_limits.total_usd`", "`meeting_limits.daily_usd` covers both",
                       "never run at the same time", "R1–R8", "改成你要的樣子（草稿）", "a row you tick yourself stays ticked",
                       "kept in this browser only"):
            self.assertIn(phrase, self.flat)

    def test_it_covers_the_adoption_in_its_order(self):
        for phrase in ("照草稿採用", "啟用", "建新卡", "插技能", "帶到隊伍", "帶去開會", "記下", "nothing is saved until 建立",
                       "插上技能只是紀錄，不會安裝或下載", "`flows.json`", "建立隊伍", "儲存隊伍", "記下：採用", "記下：不採用",
                       "主控台記錄（未驗證身分）", "can only be dismissed"):
            self.assertIn(phrase, self.flat)

    def test_it_covers_the_speed_the_office_and_the_board(self):
        for phrase in ("`meeting_speed`", "low effort", "medium", "15 minutes", "時間到沒發言", "會議室", "董事長桌", "組隊提案待你看",
                       "去看提案", "「輪到你」", "讀不到組隊會議", "`board_engine.py`", "`skill_fit.py`"):
            self.assertIn(phrase, self.flat)

    def test_going_back_to_v090_is_said_once_with_the_ledger(self):
        self.assertEqual(self.section.count("**Going back to v0.9.0.**"), 1)
        back = _flat(self.section[self.section.index("**Going back to v0.9.0.**"):])
        for fact in ("`staffing/`", "`staffing_limits`", "`meeting_speed`", "`--effort`", "without the clock", "代碼：time_up",
                     "daily ledger does not count what the staffing meetings spent", "`meeting_limits.daily_usd`",
                     "`meeting-worker.lock`", "this browser"):
            self.assertIn(fact, back)

    def test_the_page_words_it_quotes_are_the_pages(self):
        for words in ("請 CEO 組隊", "固定規則，不是 AI 判斷", "開始組隊會議", "改成你要的樣子（草稿）", "照草稿採用", "建立隊伍", "儲存隊伍",
                      "記下：採用", "記下：不採用", "主控台記錄（未驗證身分）", "時間到沒發言", "組隊提案待你看", "去看提案", "讀不到組隊會議"):
            self.assertIn(words, self.app, words)
        self.assertIn("插上技能只是紀錄，不會安裝或下載", self.app)


class ReadmeStaffingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = _flat((ROOT / "README.md").read_text(encoding="utf-8"))
        cls.zh = _flat((ROOT / "README.zh-TW.md").read_text(encoding="utf-8"))

    def test_the_english_readme_has_the_staffing_meeting(self):
        for phrase in ("| **Staffing meeting** |", "`#/staffing`", "請 CEO 組隊", "照草稿採用", "組隊提案待你看", "去看提案",
                       "**Let the CEO staff a task card, and adopt it step by step.**", "建立隊伍", "only records it",
                       "A staffing meeting is sent and paid for the same way", "15 minutes by default"):
            self.assertIn(phrase, self.en)

    def test_the_chinese_readme_has_the_staffing_meeting(self):
        for phrase in ("| **組隊會議** |", "`#/staffing`", "請 CEO 組隊", "照草稿採用", "組隊提案待你看", "去看提案",
                       "**請 CEO 幫任務卡組隊，再一步一步採用。**", "建立隊伍", "只是紀錄", "組隊會議也一樣送出、一樣花錢",
                       "一場預設最多 15 分鐘"):
            self.assertIn(phrase, self.zh)

    def test_both_show_the_adoption_list(self):
        for text in (self.en, self.zh):
            self.assertIn('src="docs/images/staffing-adopt.png"', text)


class ReferenceStaffingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = (ROOT / "docs" / "REFERENCE.zh-TW.md").read_text(encoding="utf-8")

    def test_the_pages_the_state_and_the_modules(self):
        self.assertTrue(re.search(r"^\| 組隊會議 \|", self.ref, re.M), "a row of its own in the pages table")
        for phrase in ("照草稿採用", "組隊提案待你看", "`staffing/`", "`s-<12 位十六進位>.json`", "`staffing_limits`", "`meeting_speed`",
                       "board_engine.py", "staffing.py", "staffing_runner.py", "skill_fit.py",
                       "SECURITY-MODEL.md#staffing-meetings-組隊會議", "v0.10.0"):
            self.assertIn(phrase, self.ref)



if __name__ == "__main__":
    unittest.main()
