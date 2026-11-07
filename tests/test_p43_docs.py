"""P43-5: the changelog, both READMEs, the security model, the ADR, the architecture, the reference and the glossary say what the shared
folder is, who can switch it on, what it never does, its residual risks and what going back does; the numbers they quote are the code's;
and the words the pages use are the ones quoted.

Seams: the text of the documents (whitespace flattened), the constants of ``vbear/runtime/shared_rules.py`` and ``vbear/shared_folder.py``
and the page's source for the words it uses."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from vbear import shared_folder
from vbear.runtime import shared_rules as rules

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class SharedFolderDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.17.1"):text.index("## v0.17.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Shared folder (v0.17.1)"):cls.model.index("## The start-up page (v0.12)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.arch_section = cls.arch[cls.arch.index("## Shared folder — "):cls.arch.index("## Start-up page")]
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr_raw = (ROOT / "docs" / "adr" / "0009-shared-folder.md").read_text(encoding="utf-8")
        cls.adr = flat(cls.adr_raw)
        cls.glossary = read("GLOSSARY.md")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertTrue(self.raw.startswith("# Changelog\n\n## v0.17.1 — the shared folder\n"), self.raw[:60])
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_five_tasks_and_the_merge_decision(self):
        for task in ("P43-1", "P43-2", "P43-3", "P43-4", "P43-5"):
            self.assertIn(task, self.changelog, task)
        for phrase in ("`sharedStartCheck`", "`data-chat=\"shared-check\"`", "only P43-2's note", "Every employee is off until you switch them on",
                       "still a permission card", "`timeout-minutes` is 35", "`tools/qa_p43.py`", "`tests/test_shared_flow.py`",
                       "`docs/evidence/codex-0.163.0-shared.md`", "`shared_unverified`", "`shared_confirm`", "`shared_full`", "`shared_unsafe`"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does_and_what_is_not_known(self):
        self.assertIn("Going back to v0.17.0", self.changelog)
        for phrase in ("`<state>/shared/`", "read from the code and was not run", "no new field", "no new key", "待確認", "Nothing in the folder is deleted"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_codex_was_not_tried_on_a_real_machine(self):
        self.assertIn("Codex employees using the shared folder were NOT tried on a real machine", self.changelog)
        self.assertIn("On a real Mac:** with Claude Code 2.1.319", self.changelog)
        self.assertIn("待真機驗證", self.changelog)

    def test_both_readmes_say_what_it_does_and_what_it_does_not(self):
        for word in ("**Shared folder**", "共用資料夾", "Every employee is off", "Anthropic", "OpenAI", "permission card", "names of the files",
                     "SECURITY-MODEL.md#shared-folder-v0171", "1 GiB", "not on a real machine", "`.command`"):
            self.assertIn(word, self.en, word)
        for word in ("**共用資料夾**", "預設都是關", "Anthropic", "OpenAI", "權限卡片", "檔名", "SECURITY-MODEL.md#shared-folder-v0171", "1 GiB",
                     "沒有在真機上驗證", "`.command`"):
            self.assertIn(word, self.zh, word)
        self.assertNotIn("員工看不到彼此的檔案，只看得到群組裡說過的話。", self.zh)

    def test_the_security_model_has_the_section_with_its_residual_risks(self):
        for phrase in ("`POST /api/shared/cards`", "`confirm_company: true`", "`shared_confirm`", "`shared_unverified`", "`tests/test_autonomy_guard.py`",
                       "`BEGIN_UNTRUSTED_JSON_STRING`", "`<state>/shared-meta/`", "`<state>/shared-meta/changes/<g-… or d-…>.jsonl`", "`tests/test_shared_flow.py`", "`tools/qa_p43.py`",
                       "`docs/evidence/codex-0.163.0-shared.md`", "Residual risks of the shared folder", "Going back to v0.17.0", "prompt-injection path",
                       "crosses companies", "Links and hard links", "outside its sandbox", "`.command`", "only when a process starts", "not verified on a real machine",
                       "待真機驗證"):
            self.assertIn(phrase, self.section, phrase)
        self.assertIn("every command and every file change is still asked of the person", self.section)
        self.assertIn("There is **no 自己動手 item** for it", self.section)
        self.assertIn("one** 「檢查」 button", self.section)

    def test_the_old_group_sentence_no_longer_says_employees_see_none_of_each_others_files_without_the_exception(self):
        self.assertIn("with the shared folder switched on, the next employee is also given the names of files", self.model)

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`vbear/shared_folder.py`", "`vbear/shared_changes.py`", "`vbear/runtime/shared_rules.py`", "`shared_path(state)`", "`folder_problem`",
                       "`write_problem`", "`judge_file_change`", "`sharedCheckNode`", "`data-chat=\"shared-check\"`", "`Console._on_new_employee`",
                       "`tests/test_shared_flow.py`", "`tools/qa_p43.py`", "`settings.json`", "`log.jsonl`", "`pending/<d-…>.json`"):
            self.assertIn(phrase, self.arch_section, phrase)
        for word in ("`#/shared`", "共用資料夾", "shared-meta/", "shared_folder.py shared_changes.py", "runtime/shared_rules.py", "SECURITY-MODEL.md#shared-folder-v0171",
                     "`POST /api/shared/cards`", "預設是關的", "沒有在真機上驗證"):
            self.assertIn(word, self.ref, word)

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0009 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(word, self.adr_raw, word)
        for word in ("考慮過的其他選項", "後果", "殘餘風險", "BEGIN_VBEAR_SHARED_JSON", "使用者拍板", "預設關", "Codex", "沒有在真機上"):
            self.assertIn(word, self.adr, word)

    def test_the_glossary_has_the_new_term_and_the_changed_ones(self):
        for term in ("**共用資料夾**：", "_避免_：shared folder", "群組", "派工"):
            self.assertIn(term, self.glossary, term)
        self.assertIn("共用資料夾", self.glossary[self.glossary.index("**群組**"):self.glossary.index("**共用資料夾**")])

    def test_the_numbers_the_documents_quote_are_the_codes(self):
        self.assertEqual((rules.MAX_BYTES, rules.MAX_ENTRIES, rules.MAX_BLOCK, rules.MAX_NAMES, rules.NAME_MAX), (1 << 30, 10_000, 1000, 50, 200))
        self.assertEqual((rules.BEGIN_MARK, rules.END_MARK), ("BEGIN_VBEAR_SHARED_JSON", "END_VBEAR_SHARED_JSON"))
        self.assertEqual(rules.PROTECTED, (".claude", ".codex", ".agents", ".git"))
        self.assertEqual((shared_folder.CARDS_MAX, shared_folder.FILES_MAX, shared_folder.LOG_MAX), (200, 200, 1 << 20))
        self.assertEqual(shared_folder.COMPANY, {"claude-chat": "Anthropic", "codex-chat": "OpenAI"})
        for text in (self.section, self.changelog):
            self.assertIn("1 GiB", text)
            self.assertIn("10,000", text)
        self.assertIn("1,000 characters", self.section)
        self.assertIn("9,000", self.changelog)
        self.assertIn("at most 50", self.section)
        self.assertIn("4,096 bytes", self.section)

    def test_the_words_the_documents_quote_are_the_ones_the_page_uses(self):
        for words in ("讓這幾位都能用共用資料夾", "替這次派工的員工打開共用資料夾", "在 Finder 打開", "還要檢查一次", "這段時間共用資料夾裡新增或改過",
                      "不要在 Finder 裡直接打開你不認得的檔案", "每位員工預設都是關的"):
            self.assertIn(words, self.app, words)


if __name__ == "__main__":
    unittest.main()
