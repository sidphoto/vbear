"""P41-4: the changelog, both READMEs, the security model, the ADR, the architecture, the reference and the glossary say what a group
is, what it never does, its residual risks and what going back does; the numbers and routes they quote are the code's; and the words
the page uses are the ones quoted.

Seams: the text of the documents (whitespace flattened), the constants and routes of ``vbear/groups.py`` and ``vbear/server.py`` and
the page's source for the words it uses."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from vbear import groups, server

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class GroupDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.16.0"):text.index("## v0.15.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Group chats (v0.16)"):cls.model.index("## The start-up page (v0.12)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.arch_section = cls.arch[cls.arch.index("## Group chats"):cls.arch.index("## Start-up page")]
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr_raw = (ROOT / "docs" / "adr" / "0007-group-chat.md").read_text(encoding="utf-8")
        cls.adr = flat(cls.adr_raw)
        cls.glossary = read("GLOSSARY.md")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertTrue(self.raw.startswith("# Changelog\n\n## v0.16.0 — group chat\n"), self.raw[:60])
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_four_tasks_and_what_they_made(self):
        for phrase in ("(P41-1", "(P41-2", "(P41-3", "(P41-4)", "`ChatService.send_for_group`", "`group_member_chat`", "`round_open`",
                       "`POST /api/groups/<id>/messages`", "`POST /api/groups/<id>/members {add, remove}`", "`DELETE /api/groups/<id>`",
                       "`POST …/stop|continue|drop`", "`daily_limit`", "`plan_limit`", "`uncertain`", "`group-runner.lock`", "`<state>/groups/",
                       "BEGIN_UNTRUSTED_JSON_STRING", "never answers a permission card", "`tools/qa_p41.py`", "`tests/test_group_flow.py`",
                       "`tests/test_autonomy_guard.py`", "`#/chat/group/<id>`", "點名", "開新群組", "大家", "明天 0:00", "不用了", "停止", "繼續",
                       "`vbear/runtime/` is the same as in v0.15.0", "the path at the top"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does_and_what_is_not_known(self):
        self.assertIn("Going back to v0.15.0", self.changelog)
        self.assertNotIn("Going back to v0.14", self.changelog)
        for phrase in ("ordinary chat", "no new field", "`<state>/groups/`", "`group-runner.lock`", "adds no key", "Do not go back while a round is on",
                       "was read from the code and was not run", "待確認"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_was_not_run_on_a_real_machine(self):
        self.assertIn("Not run on a real machine", self.changelog)
        for phrase in ("between the markers", "Codex employee", "whether 停止", "No code or test ran a real AI tool"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_both_readmes_say_what_it_does_and_what_it_does_not(self):
        for word in ("**Group**", "group", "點名", "開新群組", "Anthropic", "OpenAI", "data", "never calls another", "permission card", "停止",
                     "daily limit", "no 「allow all」", "SECURITY-MODEL.md#group-chats-v016"):
            self.assertIn(word, self.en, word)
        for word in ("**群組**", "點名", "開新群組", "Anthropic", "OpenAI", "資料", "不會讓別的員工回答", "權限卡片", "停止", "每天上限", "沒有「全部允許」",
                     "SECURITY-MODEL.md#group-chats-v016"):
            self.assertIn(word, self.zh, word)

    def test_the_security_model_has_the_section_with_its_residual_risks(self):
        for phrase in ("`ChatService.send_for_group`", "`POST /api/groups/<id>/messages", "`group-runner.lock`", "`BEGIN_UNTRUSTED_JSON_STRING`",
                       "`END_UNTRUSTED_JSON_STRING`", "`vbear/group*.py`", "`tests/test_autonomy_guard.py`", "may not call `answer`", "`acceptForSession`",
                       "`group_member_chat`", "Residual risks of group chats", "prompt-injection", "Anthropic", "OpenAI", "access token", "VBear's API",
                       "outside the sandbox", "`tests/test_group_flow.py`", "`tools/qa_p41.py`", "`group.json`", "`log.jsonl`", "0:00 local time tomorrow",
                       "`vbear/runtime/` is not touched", "待真機驗證"):
            self.assertIn(phrase, self.section, phrase)
        self.assertIn("every command and every file change asked of the person", self.section)
        self.assertIn("no \"allow all\"", self.section)

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`vbear/groups.py`", "`vbear/group_runner.py`", "`GroupRunner`", "`group-runner.lock`", "`ChatService.send_for_group`", "`Groups.say`",
                       "`groups.PAUSE_TEXT`", "`groups.SKIP_TEXT`", "`ChatService.delete_for_group`", "`tools/qa_p41.py`", "`tests/test_group_flow.py`",
                       "`log.jsonl`", "`group.json`"):
            self.assertIn(phrase, self.arch_section, phrase)
        for word in ("`#/chat/group/<id>`", "開新群組", "點名", "大家", "groups/g-", "group-runner.lock", "groups.py group_runner.py", "BEGIN_UNTRUSTED_JSON_STRING",
                     "SECURITY-MODEL.md#group-chats-v016", "不得呼叫 `answer`"):
            self.assertIn(word, self.ref, word)

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0007 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(word, self.adr_raw, word)
        for word in ("群組是聊天的一種", "每位成員在群組裡有一個自己的聊天", "考慮過的其他選項", "後果", "殘餘風險", "BEGIN_UNTRUSTED_JSON_STRING", "存取權杖",
                     "聊天紀錄不加新欄位", "還沒有在真機上看過"):
            self.assertIn(word, self.adr, word)

    def test_the_glossary_has_the_new_terms(self):
        for term in ("**群組**：", "**點名**：", "_避免_：群聊、聊天室、room、多人會議", "_避免_：tag、mention、標記", "「會議」", "「派工」"):
            self.assertIn(term, self.glossary, term)

    def test_the_numbers_the_documents_quote_are_the_codes(self):
        self.assertEqual((groups.MIN_MEMBERS, groups.MAX_MEMBERS, groups.NAME_MAX, groups.MAX_GROUPS), (2, 3, 40, 200))
        self.assertEqual((groups.ITEM_MAX, groups.DATA_MAX, groups.MESSAGE_MAX), (6 * 1024, 12 * 1024, 30 * 1024))
        self.assertEqual((groups.MAX_FILE, groups.MAX_LOG), (64 * 1024, 8 << 20))
        for text in (self.section, self.changelog, self.arch_section):
            self.assertIn("6 KiB", text)
            self.assertIn("12 KiB", text)
            self.assertIn("30 KiB", text)
        self.assertIn("64 KiB", self.section)
        self.assertIn("8 MiB", self.section)
        self.assertIn("two or three", self.section)

    def test_the_routes_the_documents_name_are_the_servers(self):
        route = server.GROUP_RE.pattern
        for action in ("messages", "stop", "continue", "drop", "members", "rename"):
            self.assertIn(action, route, action)
        for action in ("messages", "members", "rename", "stop", "continue", "drop"):
            self.assertIn(action, self.arch_section, action)

    def test_the_words_the_documents_quote_are_the_ones_the_page_uses(self):
        for words in ("開新群組", "建立（不花錢）", "繼續（請剩下的人回答）", "不用了", "停止", "加人／移除", "這句會請", "對大家說", "這是群組", "回到群組",
                      "會刪掉群組和群組裡每位員工的對話紀錄", "Codex 自己保存的對話副本不會被刪", "員工看不到彼此的檔案", "同時送給 Anthropic 和 OpenAI"):
            self.assertIn(words, self.app, words)


if __name__ == "__main__":
    unittest.main()
