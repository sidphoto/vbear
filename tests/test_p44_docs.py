"""P44-6: the changelog, both READMEs, the security model, the ADR, the architecture, the reference and the glossary say what a skill and a
routine are, who can make them, what runs on its own and what never does, what it costs, what is known not to be counted, what was and was not
tried on a real machine, the residual risks and what going back does; the numbers they quote are the code's; and the words the pages use are the
ones quoted.

Seams: the text of the documents (whitespace flattened), the constants of ``vbear/skillbook.py``, ``vbear/routine_rules.py``,
``vbear/auto_continue.py``, ``vbear/keep_awake.py`` and ``vbear/autonomy.py`` and the page's source for the words it uses."""
from __future__ import annotations

import re
import unittest
from decimal import Decimal
from pathlib import Path

from vbear import auto_continue, autonomy, keep_awake, routine_rules as rr, skillbook

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class SkillsAndRoutinesDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.18.0"):text.index("## v0.17.1")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Skills and routines (v0.18)"):cls.model.index("## Team templates (v0.19)")]
        cls.chief = cls.model[cls.model.index("## Chief of staff and dispatch (v0.15)"):cls.model.index("## Group chats (v0.16)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.arch_section = cls.arch[cls.arch.index("## Skills and routines — "):cls.arch.index("## Team templates — ")]
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr_raw = (ROOT / "docs" / "adr" / "0010-skills-and-routines.md").read_text(encoding="utf-8")
        cls.adr = flat(cls.adr_raw)
        cls.glossary_raw = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
        cls.glossary = flat(cls.glossary_raw)
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    # -- the changelog ---------------------------------------------------------------------------------------------------------

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertIn("\n## v0.18.0 — skills and routines\n", self.raw)                      # (v0.19.0 is the first now)
        self.assertLess(self.raw.index("## v0.19.0 — team templates"), self.raw.index("## v0.18.0 — skills and routines"))
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_six_tasks_and_the_pieces(self):
        for task in ("P44-1", "P44-2", "P44-3", "P44-4", "P44-5", "P44-6"):
            self.assertIn(task, self.changelog, task)
        for phrase in ("`memory_rules.check_text`", "`ChatService.send_for_routine`", "`vbear/keep_awake.py`", "`vbear/auto_continue.py`", "`tools/qa_p44.py`",
                       "`tests/test_skills_routines_flow.py`", "`tests/test_qa_p44.py`", "`/api/my-skills`", "`/api/routines`", "`/api/waiting`",
                       "`test_one_memory_from_the_first_line_to_clearing_it`", "item 3", "item 5", "`docs/adr/0010-skills-and-routines.md`"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_is_not_counted_and_what_is_not_known(self):
        for phrase in ("`_chat_day_spent`", "does not include", "at most US$0.10", "skill_suggest"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does_and_what_is_not_known(self):
        self.assertIn("Going back to v0.17.1", self.changelog)
        for phrase in ("`<state>/skillbook/`", "`<state>/routines/`", "read from the code and was not run", "no new field", "待確認", "`routine-runner.lock`",
                       "Nothing is deleted", "`continued` by `vbear`", "ordinary one-to-one chats"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_was_not_tried_on_a_real_machine(self):
        for phrase in ("Codex employees were NOT tried on a real machine", "a Mac that really sleeps was NOT tried", "the automatic continuation after midnight was NOT tried",
                       "`caffeinate` really holding off sleep was NOT tried", "On a real Mac:**", "待真機驗證"):
            self.assertIn(phrase, self.changelog, phrase)

    # -- the readmes -----------------------------------------------------------------------------------------------------------

    def test_both_readmes_say_what_it_does_and_what_it_does_not(self):
        for word in ("**Skills and routines**", "技能", "例行工作", "SECURITY-MODEL.md#skills-and-routines-v018", "Anthropic", "half of the daily limit",
                     "Mac to be awake", "5 minutes", "twelve hours", "keep the Mac awake", "item 3", "item 5", "not on a real machine"):
            self.assertIn(word, self.en, word)
        for word in ("**技能與例行工作**", "SECURITY-MODEL.md#skills-and-routines-v018", "Anthropic", "每天上限的一半", "Mac 要醒著", "5 分鐘", "12 小時",
                     "讓 Mac 保持清醒", "第 3 項", "第 5 項", "沒有在真機上驗證"):
            self.assertIn(word, self.zh, word)

    # -- the security model ----------------------------------------------------------------------------------------------------

    def test_the_security_model_has_the_section_with_its_residual_risks(self):
        for phrase in ("`POST /api/my-skills`", "`POST /api/routines`", "`POST /api/settings/autonomy`", "`X-VBear`", "`confirm_warning`", "`tests/test_autonomy_guard.py`",
                       "`BEGIN_UNTRUSTED_JSON_STRING`", "`send_for_routine`", "`<state>/routines/runs.jsonl`", "`<state>/routines/auto-continue.jsonl`", "`<state>/skillbook/skills.json`",
                       "`tests/test_skills_routines_flow.py`", "`tools/qa_p44.py`", "Residual risks of skills and routines", "Going back to v0.17.1",
                       "prompt-injection path", "`memory_rules.check_text`", "`prompt_sha`", "`/usr/bin/caffeinate`", "A known gap", "`_chat_day_spent`",
                       "待真機驗證", "not verified on a real machine"):
            self.assertIn(phrase, self.section, phrase)
        for sentence in ("every command and every file change is still asked of the person", "no card is answered", "There is **no 自己動手 item** for making a routine",
                         "`routine*.py`, `skillbook*.py` and `auto_continue.py`", "`vbear/runtime/` gains one function"):
            self.assertIn(sentence, self.section, sentence)

    def test_the_waking_up_part_is_inside_the_section_and_the_chief_of_staff_part_knows_the_countdown(self):
        self.assertIn("### Waking up and keeping the Mac awake", self.section)
        self.assertNotIn("the rest of that section is written with the release", self.model)
        self.assertNotIn("does not count down and does not continue anything by itself in this version", self.chief)
        for phrase in ("countdown", "自己動手 item 5", "resume_dispatch(", "Skills and routines (v0.18)"):
            self.assertIn(phrase, self.chief, phrase)

    # -- the architecture and the reference ------------------------------------------------------------------------------------

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`vbear/skillbook.py`", "`vbear/skillbook_suggest.py`", "`vbear/routine_rules.py`", "`vbear/routines.py`", "`vbear/routine_runner.py`",
                       "`vbear/auto_continue.py`", "`vbear/countdown.py`", "`vbear/keep_awake.py`", "slots_between", "send_for_routine", "`heartbeat.json`",
                       "Console.keep_awake_command", "`DispatchRunner.resume_dispatch(did, by=\"vbear\"", "`openSkillSave`", "`openSkillPicker`", "`viewRoutines`", "`tests/test_skills_routines_flow.py`",
                       "`tools/qa_p44.py`", "routine-runner.lock", "`skill_suggest`"):
            self.assertIn(phrase, self.arch_section, phrase)
        for word in ("`#/my-skills`", "`#/routines`", "技能", "例行工作", "skillbook/", "routines/", "skillbook.py", "routine_runner.py", "keep_awake.py",
                     "SECURITY-MODEL.md#skills-and-routines-v018", "`POST /api/routines`", "預設是關的", "沒有在真機上驗證"):
            self.assertIn(word, self.ref, word)

    # -- the ADR and the glossary ----------------------------------------------------------------------------------------------

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0010 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("草稿", "/Users/", "runs/", "P44-6 定稿"):
            self.assertNotIn(word, self.adr_raw, word)
        for word in ("考慮過的其他選項", "後果", "殘餘風險", "使用者拍板", "每天上限的一半", "預設都不勾", "沒有在真機上驗證", "已知缺口", "_chat_day_spent"):
            self.assertIn(word, self.adr, word)

    def test_the_glossary_has_the_new_terms_and_the_changed_ones(self):
        for term in ("**技能**：", "**整理成技能**：", "**例行工作**：", "**醒來補做**：", "**倒數接續**：", "**讓 Mac 保持清醒**：", "_避免_：排程、cron、routine、定時任務"):
            self.assertIn(term, self.glossary, term)
        self.assertNotIn("草稿，P44-6 定稿", self.glossary)
        self.assertNotIn("依排定時間重複交給員工去做的一件工作。 _避免_", self.glossary)
        for name in ("**派工**", "**AI 自己做了什麼**", "**群組**", "**自己動手**"):
            part = self.glossary_raw[self.glossary_raw.index(name):]
            part = part[:part.index("\n\n")]
            self.assertTrue(any(w in part for w in ("倒數", "例行工作", "用技能", "第 3")), name)

    # -- the numbers and the words ---------------------------------------------------------------------------------------------

    def test_the_numbers_the_documents_quote_are_the_codes(self):
        self.assertEqual((skillbook.MAX_SKILLS, skillbook.MAX_NAME, skillbook.MAX_TEXT), (100, 40, 4000))
        self.assertEqual((rr.NAME_MAX, rr.TEXT_MAX, rr.MAX_ROUTINES, rr.MAX_ENABLED, rr.MAX_TIMES, rr.MIN_GAP_MIN), (40, 4000, 20, 10, 3, 60))
        self.assertEqual(rr.ROUTINE_DAILY_FRACTION, Decimal("0.5"))
        self.assertEqual((rr.WAKE_GAP_S, rr.LOOK_BACK_S, rr.CATCH_UP_AUTO_S, rr.CATCH_UP_AUTO_MAX, rr.CATCH_UP_LISTED_S, rr.BEAT_S),
                         (90.0, 7 * 86400.0, 12 * 3600.0, 3, 24 * 3600.0, 60.0))
        self.assertEqual((rr.ON_TIME_S, rr.WAITING_FOR_S, rr.BUSY_RETRY_S, rr.BUSY_FOR_S), (120.0, 12 * 3600.0, 30.0, 720.0))
        self.assertEqual((auto_continue.GRACE_S, auto_continue.STALE_S, auto_continue.PER_DISPATCH, auto_continue.PER_DAY, auto_continue.REPEAT_S),
                         (120.0, 12 * 3600.0, 3, 5, 600.0))
        self.assertEqual(keep_awake.GRACE_S, 30.0)
        self.assertEqual(autonomy.KEYS, ("create_cards", "dispatch", "routines", "auto_continue"))
        self.assertTrue(keep_awake.argv()[:3] == ["/usr/bin/caffeinate", "-i", "-w"] and len(keep_awake.argv()) == 4)
        for text in (self.section, self.changelog):
            for number in ("4,000", "100 skills", "20 routines", "ten", "12 hours", "24 hours", "90 seconds", "seven days", "US$0.10"):
                self.assertIn(number, text, number)
        self.assertIn("three routines", self.section)
        self.assertIn("5 minutes", self.section)

    def test_the_words_the_documents_quote_are_the_ones_the_page_uses(self):
        for words in ("現在開始", "這次跳過", "補做", "不用了", "用技能", "存成技能", "整理成技能", "從技能帶入", "讓 Mac 保持清醒", "有工作在跑時不讓 Mac 睡著",
                      "VBear 的視窗要開著、Mac 要醒著，例行工作才會做", "沒有打開「自己動手」第 3 項"):
            self.assertIn(words, self.app, words)
        for words in ("這段是員工寫的，存成技能後，你用它時會變成你對員工說的話", "之後改技能，不會改這個例行工作"):
            self.assertIn(words, self.app, words)
        self.assertIn("這段是員工寫的，存成技能後，你用它時會變成你對員工說的話", self.adr_raw)


if __name__ == "__main__":
    unittest.main()
