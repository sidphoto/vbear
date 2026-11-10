"""P40-5: the changelog, both READMEs, the security model, the ADR, the architecture, the reference and the glossary say what the chief
of staff and the dispatch are, what they never do, their residual risks and what going back does; and the words the page uses are
the ones quoted.

Seams: the text of the documents (whitespace flattened) and the page's source for the words it uses."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class ChiefDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.15.0"):text.index("## v0.13.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Chief of staff and dispatch"):cls.model.index("## The start-up page (v0.12)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr_raw = (ROOT / "docs" / "adr" / "0006-chief-of-staff-dispatch.md").read_text(encoding="utf-8")
        cls.adr = flat(cls.adr_raw)
        cls.glossary = read("GLOSSARY.md")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertIn("\n## v0.15.0 — the chief of staff\n", self.raw)         # newer releases are put above it (v0.16.0 is the first now)
        self.assertIn("\n## v0.16.0 — group chat\n", self.raw)                  # (v0.17.0 is the first now)
        self.assertIn("\n## v0.17.0 — memory\n", self.raw)                      # (v0.17.1 is the first now)
        self.assertLess(self.raw.index("## v0.17.1 — the shared folder"), self.raw.index("## v0.17.0 — memory"))
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_five_tasks_and_what_they_made(self):
        for phrase in ("(P40-1)", "(P40-2)", "(P40-3)", "(P40-4)", "(P40-5)", "`empty_plan`", "`GET /api/chief/preview?chat_id=`",
                       "`POST /api/chief`", "/api/dispatch/<id>/confirm", "`GET /api/actions`", "`GET/POST /api/settings/autonomy`", "`origin = {dispatch, step}`",
                       "`step`", "`tools/qa_p40.py`", "`tests/test_autonomy_guard.py`", "`#/dispatch`", "`#/actions`", "自己動手",
                       "確認派工", "你改過", "幕僚長目前需要 Claude Code", "BEGIN_UNTRUSTED_JSON_STRING", "US$0.30",
                       "never answers a permission card", "skips a step"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does_and_to_which_version(self):
        self.assertIn("Going back to v0.13.0", self.changelog)
        self.assertIn("v0.14 was never released", self.changelog)
        self.assertNotIn("Going back to v0.14", self.changelog)
        for phrase in ("`origin`", "damaged", "`spend_unknown`", "`<state>/dispatch/`", "`<state>/chief/`", "`autonomy`", "was not run"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_both_readmes_say_what_it_does_and_what_it_does_not(self):
        for word in ("chief of staff", "請幕僚長安排", "確認派工", "你改過", "never answers", "permission card", "Anthropic", "自己動手",
                     "off by default", "cannot be taken back", "#/actions", "SECURITY-MODEL.md#chief-of-staff-and-dispatch-v015"):
            self.assertIn(word, self.en, word)
        for word in ("幕僚長", "請幕僚長安排", "確認派工", "你改過", "權限卡片", "Anthropic", "自己動手", "預設都不勾", "收不回來", "#/actions",
                     "SECURITY-MODEL.md#chief-of-staff-and-dispatch-v015"):
            self.assertIn(word, self.zh, word)

    def test_the_security_model_has_the_section_with_its_residual_risks(self):
        for phrase in ("`vbear/chief_runner.py`", "`StructuredOutput`", "`additionalProperties: false`", "`empty_plan`", "`tests/test_autonomy_guard.py`",
                       "`/api/native/`", "`/api/settings/autonomy`", "`/api/config`", "`/api/setup/daily-limit`", "`acceptForSession`",
                       "`ChatService.send_for_dispatch`", "`origin = {dispatch, step}`", "no way to answer an allow card", "`BEGIN_UNTRUSTED_JSON_STRING`",
                       "Residual risks", "prompt-injection", "access token", "VBear's own API", "its own chief of staff and dispatch code",
                       "Anthropic", "`#/actions`", "taken back", "tools/qa_p40.py", "cannot be taken back"):
            self.assertIn(phrase, self.section, phrase)
        self.assertIn("every command and every file change", self.section)

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`vbear/chief*.py`", "`ChiefRunner`", "`Dispatcher.from_proposal`", "`DispatchRunner`", "`dispatch-runner.lock`",
                       "`ChatService.send_for_dispatch`", "`dispatch.PAUSE_TEXT`", "/api/settings/autonomy`", "`tools/qa_p40.py`"):
            self.assertIn(phrase, self.arch, phrase)
        for word in ("#/dispatch", "#/actions", "AI 自己做了什麼", "請幕僚長安排", "你改過", "chief/", "dispatch/", "SECURITY-MODEL.md#chief-of-staff-and-dispatch-v015"):
            self.assertIn(word, self.ref, word)

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0006 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(word, self.adr_raw, word)
        for word in ("幕僚長是 VBear 內建的角色", "派工走員工的聊天", "考慮過的其他選項", "後果", "殘餘風險", "存取權杖", "不會重做"):
            self.assertIn(word, self.adr, word)

    def test_the_glossary_has_the_new_terms_and_the_old_ones_say_what_is_now(self):
        for term in ("**分配工作**：", "**提議卡**：", "**AI 自己做了什麼**：", "**幕僚長**：", "**CEO**："):
            self.assertIn(term, self.glossary, term)
        self.assertNotIn("派工做好之前", self.glossary)
        self.assertNotIn("分配工作做好之前", self.glossary)
        self.assertNotIn("現在只會聊天", self.glossary)

    def test_the_words_the_documents_quote_are_the_ones_the_page_uses(self):
        # (P47) the page says 依分配工作; the security model's section quotes the same words (the v0.15.0 changelog entry keeps the words of its day)
        self.assertIn("VBear 依分配工作送出", self.section)
        self.assertNotIn("VBear 依派工送出", self.section)
        for words in ("請幕僚長安排", "確認派工", "不採用", "你改過", "AI 自己做了什麼", "幕僚長目前需要 Claude Code", "VBear 依分配工作送出"):
            self.assertIn(words, self.app, words)


if __name__ == "__main__":
    unittest.main()
