"""P38-5: the changelog, both READMEs, the security model, the ADR, the evidence file and the glossary say what a Codex chat is,
what it costs, what is not limited and what going back does; and the words the page uses are the ones quoted."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class CodexChatDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.13.0"):text.index("## v0.12.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Chats with a Codex role card"):cls.model.index("## The start-up page (v0.12)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr = read("docs", "adr", "0005-codex-chat-boundary.md")
        cls.evidence = read("docs", "evidence", "codex-0.163.0-chat.md")
        cls.glossary = read("GLOSSARY.md")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_heading_is_the_release_and_not_unreleased(self):
        self.assertIn("\n## v0.13.0 — Codex chat\n", self.raw)            # newer releases are put above it (v0.15.0 is the first now)
        self.assertIn("\n## v0.15.0 — the chief of staff\n", self.raw)         # (v0.16.0 is the first now)
        self.assertTrue(self.raw.startswith("# Changelog\n\n## v0.16.0 — group chat\n"), self.raw[:60])
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_six_tasks(self):
        for phrase in ("(P38-1)", "(P38-2)", "(P38-3)", "(P38-4)", "(P38-5)", "(P38-6)", ".noindex", "`codex-chat`",
                       "`--mode codex-chat`", "`codex-chat-verified.json`", "`card_tool_unsupported`", "`card_tool_changed`",
                       "`card_not_claude`", "`cli_version`", "`claude_code_version`", "`POST /api/chat-support/verify`",
                       "改內容再問", "估計 US$0.02", "不是帳單", "讓聊天用的 Codex 登入", "Reading is not limited",
                       "codex-chat-home/sessions", "`untrusted`", "`turn/steer`", "US$0.30", "`vbear/codex_verify.py`"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does(self):
        self.assertIn("Going back to v0.12.0", self.changelog)
        for phrase in ("`chat.json`", "damaged", "`spend_unknown`", "`session_bound`", "move the chat's folder", "was not run"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_both_readmes_say_what_a_codex_chat_is_and_costs(self):
        for word in ("Codex", "ChatGPT", "not a bill", "改內容再問", "read", "token", "OpenAI"):
            self.assertIn(word, self.en, word)
        for word in ("Codex 聊天", "ChatGPT", "不是帳單", "改內容再問", "不擋讀", "token", "OpenAI", "讓聊天用的 Codex 登入"):
            self.assertIn(word, self.zh, word)
        self.assertNotIn("whose tool is Claude Code and which is on", self.en)

    def test_the_security_model_has_the_section_with_its_four_residual_risks(self):
        for phrase in ("`card_tool_changed`", "`card_tool_unsupported`", "`POST /api/chat-support/verify", "Residual risks",
                       "Reading is not limited by the sandbox", "The cap is checked between reports", "It relies on a retired value",
                       "The interface is experimental", "`untrusted`", "`codex app-server`", "`--mode codex-chat`",
                       "`acceptForSession`", "US$1.00 per million", "not a bill", "`codex-chat-home`", "`sessions`"):
            self.assertIn(phrase, self.section, phrase)
        self.assertNotIn("come later in the same release", self.section)
        self.assertNotIn("card_not_claude", self.model)

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`codex-chat`", "`CodexChatVerifier`", "`card_tool_changed`", "`runtime/codex_chat_session.py`"):
            self.assertIn(phrase, self.arch, phrase)
        for word in ("Codex 聊天", "codex-chat-home", "codex-chat-verified.json", "改內容再問", "每 100 萬 token"):
            self.assertIn(word, self.ref, word)

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0005 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        self.assertNotIn("草稿", self.adr)
        for word in ("app-server", "codex-chat-home", "untrusted", "decline", "workspace-write", "US$1.00", "cli_version",
                     "card_tool_changed", "後果"):
            self.assertIn(word, self.adr, word)
        self.assertNotIn("/Users/", self.adr)
        self.assertNotIn("runs/", self.adr)

    def test_the_evidence_is_not_a_draft_and_keeps_what_is_still_to_confirm(self):
        self.assertNotIn("(draft)", self.evidence)
        self.assertIn("Still to be confirmed with `--mode codex-chat`", self.evidence)
        self.assertIn("`turn/steer`", self.evidence)

    def test_the_glossary_has_the_new_words(self):
        for word in ("聊天用的 Codex 登入", "改內容再問"):
            self.assertIn(word, self.glossary, word)

    def test_the_words_quoted_are_the_pages(self):
        for words in ("改內容再問", "讓聊天用的 Codex 登入", "估計", "ChatGPT 方案", "到開始設定", "驗證聊天", "codex-chat-home"):
            self.assertIn(words, self.app, words)

    def test_the_home_folder_that_is_a_git_repository_is_in_the_security_model_the_adr_and_the_evidence(self):
        for name, text in (("section", self.section), ("adr", self.adr), ("evidence", self.evidence)):
            for phrase in ("project_root_markers", "untrusted", "~"):
                self.assertIn(phrase, text, (name, phrase))
        for phrase in ("home folder that is a git repository", "threadId", "managed configuration", "skills", "`config.toml`",
                       "inline table"):
            self.assertIn(phrase, self.section, phrase)
        for phrase in ("home folder that is a git repository", "threadId", "inline table", "project_root_markers=[]",
                       "managed", "skills"):
            self.assertIn(phrase, self.evidence, phrase)
        for word in ("家目錄", "git", "project_root_markers", "信任", "threadId", "行內表格", "技能"):
            self.assertIn(word, self.adr, word)
        self.assertIn("project_root_markers", self.changelog)

    def test_an_allowed_command_may_run_outside_the_sandbox_is_said_in_every_place(self):
        warning = "允許後，這個指令可能在沙盒外執行：能改到工作資料夾以外的檔案，也能連網。只允許你看得懂、確定沒問題的指令。"
        self.assertIn(warning, self.app)
        for phrase in ("允許後可能在沙盒外執行", "三個選項", "照現在發布", "`never`", "`:root`", "等 Codex 修好", "apply_patch", "連網",
                       "寫整台電腦", "不再問", "`require_escalated`"):
            self.assertIn(phrase, self.adr, phrase)
        self.assertRegex(self.adr, r"7\. \*\*")
        for phrase in ("Residual risks", "(7) *An allowed command can run outside the sandbox.*", "again without the sandbox",
                       "`require_escalated`", "write anywhere", "reach the network", "`:root`", "is only noted", "apply_patch",
                       "outside the sandbox", warning):
            self.assertIn(phrase, self.section, phrase)
        for phrase in ("5b", "orchestrator.rs", "sandbox_override_for_first_attempt", "`require_escalated`", "`:root`",
                       "again without the sandbox", "the permission profile", "`never`", "`on-request`"):
            self.assertIn(phrase, self.evidence, phrase)
        for name, text in (("changelog", self.changelog), ("readme", self.en)):
            for phrase in ("outside the sandbox", "write anywhere", "reach the network"):
                self.assertIn(phrase, text, (name, phrase))
        for phrase in ("沙盒外", "連網", "整台電腦"):
            self.assertIn(phrase, self.zh, phrase)
        self.assertIn("沙盒外", self.ref)
        self.assertIn("is only noted", self.changelog)

    def test_the_old_claim_that_the_sandbox_stops_what_the_person_allowed_is_gone(self):
        old = ("a shell write there that the sandbox must stop", "stops writes outside the work folder and the network, not reads",
               "Codex's sandbox stops writes outside the card's folder and the network",
               "the sandbox stops writes outside the folder and the network, not reads", "Codex 的沙盒擋住資料夾外的寫入",
               "writes only in the card's folder, no network, no `/tmp`)", "排除 `/tmp` 與 `$TMPDIR`，不能連網", "writes only in the work folder, no `/tmp`, no network",
               "which the sandbox must stop", "沙盒擋住允許後")
        for name, text in (("changelog", self.changelog), ("en", self.en), ("zh", self.zh), ("model", self.model), ("adr", self.adr),
                           ("evidence", self.evidence), ("ref", self.ref)):
            for phrase in old:
                self.assertNotIn(phrase, text, (name, phrase))
        self.assertNotIn("sandbox must stop", read("vbear", "codex_chat_check.py"))

    def test_nothing_public_names_a_real_person_or_machine(self):
        for text in (self.raw, self.section, self.adr, self.evidence):
            self.assertNotRegex(text, r"/Users/(?!fake-user)[A-Za-z0-9_.-]+")
            self.assertNotRegex(text, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")


if __name__ == "__main__":
    unittest.main()
