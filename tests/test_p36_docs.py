"""P36-2: the changelog, both READMEs, SECURITY and the reference say what a chat is, what it costs, whose instructions go
in, and what is not verified; and every refusal the runtime can give has a sentence in the console."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat((ROOT.joinpath(*parts)).read_text(encoding="utf-8"))


class ChatDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.changelog = flat(text[text.index("## v0.11.0"):text.index("## v0.10.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.security = read("SECURITY.md")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_changelog_covers_the_chat(self):
        for phrase in ("`#/chat`", "`#/chat/<id>`", "允許這一次", "改內容再允許", "`--append-system-prompt`",
                       "default text of the card's position is never sent", "not checked on a real machine",
                       "`chat_limits.per_turn_usd`", "`meeting_limits.daily_usd` covers all three",
                       "`python3 -m vbear.boundary_check --mode chat`", "`claude-chat-verified.json`",
                       "`~/.claude/policy-limits.json`", "chats stay shut", "`spend_unknown`", "`damaged`",
                       "無法確認花費", "`X-VBear`", "Going back to v0.10.0", "does not know chats"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_and_the_model_say_why_no_settings_are_read_and_which_python(self):
        for phrase in ('`--setting-sources ""`', "extra folders", "`unsupported_python`", "`os.waitid`", "3.13"):
            self.assertIn(phrase, self.changelog, phrase)
        for phrase in ('--setting-sources ""', "`project,local`", "`.claude/`", "`unsupported_python`", "`os.waitid`",
                       "second layer"):
            self.assertIn(phrase, self.model, phrase)
        self.assertIn('--setting-sources ""', self.arch)

    def test_the_changelog_heading_is_the_release(self):
        self.assertTrue(self.changelog.startswith("## v0.11.0 — chatting with role cards"), self.changelog[:80])
        self.assertNotIn("not released yet", self.changelog)

    def test_the_readmes_say_what_a_chat_costs_and_asks(self):
        for text, words in ((self.en, ("chat_limits.per_turn_usd", "allow once", "allow-every-time", "--append-system-prompt",
                                       "Anthropic")),
                            (self.zh, ("chat_limits.per_turn_usd", "允許這一次", "以後都允許", "--append-system-prompt", "Anthropic"))):
            for word in words:
                self.assertIn(word, text, word)

    def test_the_security_model_says_what_is_not_verified(self):
        for phrase in ("## Chats with a role card", "`card_disabled`", "`card_tool_unsupported`", "`--system-prompt-snapshot`",
                       "has been checked on a real machine", "`policy-limits.json`", "`claude-chat-verified.json`",
                       "`X-VBear`"):
            self.assertIn(phrase, self.model, phrase)
        self.assertNotIn("in progress", self.model[self.model.index("## Chats with a role card"):][:400])

    def test_security_and_the_reference_name_the_chat(self):
        self.assertIn("Chats with a role card", self.security)
        for word in ("聊天", "`chat_limits`", "claude-chat-verified.json", "policy-limits.json", "chats-with-a-role-card"):
            self.assertIn(word, self.ref, word)
        self.assertIn("ChatVerifier", self.arch)

    def test_the_words_quoted_are_the_pages(self):
        for words in ("允許這一次", "改內容再允許", "驗證聊天", "開始聊天", "無法確認花費"):
            self.assertIn(words, self.app, words)

    def test_every_code_the_runtime_can_give_has_a_sentence(self):
        from vbear import chat_service
        for code in ("refused", "expired", "restarting", "spend_unknown", "damaged", "card_disabled", "card_tool_unsupported"):
            self.assertIn(code, chat_service.CODE_TEXT, code)
            self.assertTrue(chat_service.CODE_TEXT[code][1].strip())


if __name__ == "__main__":
    unittest.main()
