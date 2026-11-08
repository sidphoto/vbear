"""P45-4: the changelog, both READMEs, the security model, the ADR, the architecture, the reference and the glossary say what a team template
is, who can apply and save one, what an apply never opens, what 復原這次套用 deletes and keeps and what it cannot see, what was and was not tried
on a real machine, the residual risks and what going back does; the numbers they quote are the code's; and the words the pages use are the ones
quoted.

Seams: the text of the documents (whitespace flattened), the constants of ``vbear/templates.py``, ``vbear/templates_apply.py`` and
``vbear/templates_builtin.py``, the guard test's list of modules and the page's source for the words it uses."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from vbear import templates as tp, templates_apply as ta, templates_builtin as tb

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class TeamTemplatesDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.19.0"):text.index("## v0.18.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Team templates (v0.19)"):cls.model.index("## The start-up page (v0.12)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.arch_section = cls.arch[cls.arch.index("## Team templates — "):cls.arch.index("## Start-up page")]
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr_raw = (ROOT / "docs" / "adr" / "0011-team-templates.md").read_text(encoding="utf-8")
        cls.adr = flat(cls.adr_raw)
        cls.glossary_raw = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
        cls.glossary = flat(cls.glossary_raw)
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    # -- the changelog ---------------------------------------------------------------------------------------------------------

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertTrue(self.raw.startswith("# Changelog\n\n## v0.19.0 — team templates\n"), self.raw[:70])
        self.assertLess(self.raw.index("## v0.19.0 — team templates"), self.raw.index("## v0.18.0 — skills and routines"))
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_four_tasks_and_the_pieces(self):
        for task in ("P45-1", "P45-2", "P45-3", "P45-4"):
            self.assertIn(task, self.changelog, task)
        for phrase in ("`vbear/templates.py`", "`vbear/templates_builtin.py`", "`vbear/templates_apply.py`", "`vbear/templates_mine.py`", "`/api/templates`", "`_save_card`",
                       "`<state>/templates/`", "`applies.json`", "`mine.json`", "`log.jsonl`", "`tools/qa_p45.py`", "`tests/test_templates_flow.py`", "`tests/test_qa_p45.py`",
                       "`tests/test_p45_docs.py`", "`docs/adr/0011-team-templates.md`", "`skillbook.add`", "`routines.create`", "rules 13a to 13c", "rule 13d", "rule 13e", "`vbear/runtime/`"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_an_apply_opens_and_what_it_never_does(self):
        for phrase in ("never full mode", "switched off", "uses no AI and costs US$0", "one AI tool", "no exception to rule 13b", "only keeps the record",
                       "does not touch `config.json`", "memory", "shared folder"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_the_undo_cannot_see(self):
        for phrase in ("VBear cannot see whether you used an employee of a team template in a terminal", "so the preview of 復原這次套用 always has one more line",
                       "you decide before you press 「刪掉這些」", "VBear does not record that a skill was used", "looks only at whether it was changed"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_saving_your_own_does_with_a_full_mode_employee(self):
        for phrase in ("a full-mode employee can be saved", "without a launch mode", "an apply is always the safe mode"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does_and_what_is_not_known(self):
        self.assertIn("Going back to v0.18.0", self.changelog)
        for phrase in ("read from the code and was not run", "no new field", "待確認", "Nothing is deleted", "`<state>/templates/`", "cannot be undone from v0.18.0"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_was_not_tried_on_a_real_machine(self):
        for phrase in ("On a real Mac:**", "待確認", "Codex employees were NOT tried on a real machine", "really running at their time was NOT tried",
                       "待真機驗證"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_names_the_flaky_test_and_its_cause(self):
        for phrase in ("`test_two_at_once_are_refused`", "link count", "0"):
            self.assertIn(phrase, self.changelog, phrase)

    # -- the readmes -----------------------------------------------------------------------------------------------------------

    def test_both_readmes_say_what_it_does_and_what_it_does_not(self):
        for word in ("**Team templates**", "團隊範本", "復原這次套用", "SECURITY-MODEL.md#team-templates-v019", "safe mode", "switched off", "one AI tool",
                     "uses no AI", "this computer", "terminal", "VBear cannot see", "not tried on a real machine"):
            self.assertIn(word, self.en, word)
        for word in ("**團隊範本**", "復原這次套用", "SECURITY-MODEL.md#team-templates-v019", "安全模式", "關著", "同一個 AI 工具", "不用 AI", "這台電腦",
                     "終端機", "VBear 看不出來", "沒有在真機上驗證"):
            self.assertIn(word, self.zh, word)
        for text in (self.en, self.zh):
            self.assertNotIn("模板", text)

    # -- the security model ----------------------------------------------------------------------------------------------------

    def test_the_security_model_has_the_section_with_its_residual_risks(self):
        for phrase in ("`POST /api/templates/apply`", "`POST /api/templates/preview`", "undo-preview", "`X-VBear`", "`confirm_warning`", "`tests/test_autonomy_guard.py`",
                       "`<state>/templates/applies.json`", "`<state>/templates/mine.json`", "`<state>/templates/log.jsonl`", "`profile_digest`", "`card_mentions`",
                       "`_save_card`", "`skillbook.add`", "`routines.create`", "`routines.delete`", "`skillbook.delete`", "`agent_profiles.delete_profile`",
                       "launch_mode", "equipped_skill_ids", "`VERIFIED_INTENTS`", "`tests/test_templates_flow.py`", "`tools/qa_p45.py`",
                       "Residual risks of team templates", "Going back to v0.18.0", "A known limit of the undo", "`TERMINAL_NOTE`",
                       "待真機驗證", "not verified on a real machine", "待確認"):
            self.assertIn(phrase, self.section, phrase)
        for sentence in ("ule 13b has no exception for `templates_apply`", "every write is in `vbear/server.py`", "`templates_apply.py` only keeps the record",
                         "`vbear/runtime/` is not changed at all", "every command and every file change is still asked of the person",
                         "There is **no 自己動手 item**", "VBear cannot see whether the person used an employee in a terminal",
                         "a full-mode employee is saved without a launch mode", "the preview of the undo always has the line"):
            self.assertIn(sentence, self.section, sentence)

    def test_the_security_model_names_every_rule_of_the_guard(self):
        for rule in ("13a", "13b", "13c", "13d", "13e"):
            self.assertIn(rule, self.section, rule)

    def test_the_other_sections_of_the_security_model_are_still_where_the_older_tests_look(self):
        order = [self.model.index(h) for h in ("## Skills and routines (v0.18)", "## Team templates (v0.19)", "## The start-up page (v0.12)")]
        self.assertEqual(order, sorted(order))

    # -- the architecture and the reference ------------------------------------------------------------------------------------

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`vbear/templates.py`", "`vbear/templates_builtin.py`", "`vbear/templates_apply.py`", "`vbear/templates_mine.py`", "`plan(", "`card_body`", "`skill_body`", "`routine_body`",
                       "`_save_card`", "`TEMPLATE_WRITE_LOCK`", "`recover()`", "`undo_plan(", "`card_mentions(", "`fingerprint(", "`viewTemplates`", "`openTemplatesPreview`",
                       "`tests/test_templates_flow.py`", "`tools/qa_p45.py`", "`tests/test_qa_p45.py`", "`GET /api/templates`", "`POST /api/templates/mine`"):
            self.assertIn(phrase, self.arch_section, phrase)
        for word in ("`#/templates`", "團隊範本", "復原這次套用", "templates/", "templates.py", "templates_apply.py", "templates_mine.py", "templates_builtin.py",
                     "SECURITY-MODEL.md#team-templates-v019", "`POST /api/templates/apply`", "安全模式", "關著", "沒有在真機上驗證", "VBear 看不出來"):
            self.assertIn(word, self.ref, word)

    # -- the ADR and the glossary ----------------------------------------------------------------------------------------------

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0011 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("狀態：草稿", "/Users/", "runs/", "P45-4 定稿"):
            self.assertNotIn(word, self.adr_raw, word)
        for word in ("考慮過的其他選項", "後果", "殘餘風險", "使用者拍板", "沒有在真機上驗證", "VBear 看不出來", "守門規則 13b", "沒有為", "完整模式的員工",
                     "不帶啟動模式", "套用一律是安全模式"):
            self.assertIn(word, self.adr, word)

    def test_the_glossary_has_the_new_terms(self):
        for term in ("**團隊範本**：", "**復原這次套用**：", "_避免_：團隊範本、範本（單獨用時）、巨集"):
            self.assertIn(term, self.glossary, term)
        part = self.glossary_raw[self.glossary_raw.index("**復原這次套用**"):]
        part = part[:part.index("\n_避免_")]
        for word in ("終端機", "VBear 看不出來", "技能沒有", "改過"):
            self.assertIn(word, part, word)

    # -- the numbers and the words ---------------------------------------------------------------------------------------------

    def test_the_numbers_the_documents_quote_are_the_codes(self):
        self.assertEqual(tp.MAX_PER_APPLY, {"cards": 12, "skills": 24, "routines": 12})
        self.assertEqual(tp.MAX_PER_TEMPLATE, {"cards": 12, "skills": 24, "routines": 12})
        self.assertEqual((tp.MAX_MINE, tp.MAX_CARDS, tp.MAX_SKILLS, tp.MAX_ROUTINES, tp.NAME_MAX), (20, 500, 100, 20, 40))
        self.assertEqual((ta.MAX_APPLIES, ta.MENTION_FILE_MAX, ta.MENTION_FILES_MAX), (50, 4 << 20, 20000))
        self.assertEqual(tb.BUILTIN_IDS, ("shop", "creator", "studio", "life"))
        built = tb.builtin()
        self.assertEqual([sum(len(t[k]) for t in built) for k in ("cards", "skills", "routines")], [12, 12, 6])
        for text in (self.section, self.changelog):
            for number in ("12 employees", "24 skills", "20 of your own", "50 applies", "4 MiB", "20,000 files"):
                self.assertIn(number, text, number)
        for number in ("500", "100 skills", "20 routines"):
            self.assertIn(number, self.section, number)

    def test_the_four_built_in_ones_are_named_as_the_page_names_them(self):
        for name in ("小店", "自媒體", "接案工作室", "個人生活助理"):
            self.assertIn(name, self.en, name)
            self.assertIn(name, self.zh, name)
            self.assertIn(name, self.adr, name)
            self.assertIn(name, [t["name"] for t in tb.builtin()])

    def test_the_words_the_documents_quote_are_the_ones_the_page_uses(self):
        for words in ("預覽並套用", "復原這次套用", "刪掉這些", "存成團隊範本", "你現在的", "用團隊範本開始", "團隊範本只存在這台電腦，不會上傳，也不能匯出。",
                      "undo-notes", "data-tpl-preview"):
            self.assertIn(words, self.app, words)            # (the two fixed reminders of the undo come from the server's ``notes``, below)
        self.assertEqual(ta.TERMINAL_NOTE, "如果你在終端機用過這些員工，VBear 看不出來；確定再刪。")
        self.assertEqual(ta.SKILL_NOTE, "VBear 不記錄技能有沒有被用過，只看有沒有改過。")
        for text in (self.zh, self.ref, self.adr):
            self.assertNotIn("還原", text)
        # 「範本」 alone is not a word of the pages: it is always 團隊範本 (or the older 角色範本 and 任務範本)
        new_zh = self.zh[self.zh.index("**從現成的一組開始：團隊範本。**"):self.zh.index("**全部留在你的 Mac 上。**")]
        new_ref = self.ref[self.ref.index("| 團隊範本 | `#/templates`"):self.ref.index("| 派工 | `#/dispatch`")] + self.ref[self.ref.index("團隊範本（v0.19.0，ADR 0011）"):self.ref.index("- 組隊會議：")]
        for label, text in (("zh", new_zh), ("ref", new_ref), ("adr", self.adr)):
            for found in re.finditer(r".?.?範本", text):
                self.assertTrue(found.group(0).endswith(("團隊範本", "角色範本", "任務範本")), (label, found.group(0)))


if __name__ == "__main__":
    unittest.main()
