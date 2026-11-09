"""P42-5: the changelog, both READMEs, the security model, the ADR, the architecture, the reference and the glossary say what memory is,
who can save it, what it never does, its residual risks and what going back does; the numbers, routes and rules they quote are the
code's; and the words the pages use are the ones quoted.

Seams: the text of the documents (whitespace flattened), the constants and routes of ``vbear/memory.py``,
``vbear/runtime/memory_rules.py`` and ``vbear/server.py`` and the page's source for the words it uses."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from vbear import memory, server
from vbear.runtime import memory_rules as rules

ROOT = Path(__file__).resolve().parent.parent


def flat(text):
    return re.sub(r"\s+", " ", text)


def read(*parts):
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


class MemoryDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        cls.raw = text
        cls.changelog = flat(text[text.index("## v0.17.0"):text.index("## v0.16.0")])
        cls.en = read("README.md")
        cls.zh = read("README.zh-TW.md")
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.section = cls.model[cls.model.index("## Memory (v0.17)"):cls.model.index("## Shared folder (v0.17.1)")]
        cls.arch = read("docs", "ARCHITECTURE.md")
        cls.arch_section = cls.arch[cls.arch.index("## Memory — "):cls.arch.index("## Shared folder — ")]
        cls.ref = read("docs", "REFERENCE.zh-TW.md")
        cls.adr_raw = (ROOT / "docs" / "adr" / "0008-memory.md").read_text(encoding="utf-8")
        cls.adr = flat(cls.adr_raw)
        cls.glossary = read("GLOSSARY.md")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertIn("\n## v0.17.0 — memory\n", self.raw)                      # (v0.17.1 is the first now)
        self.assertLess(self.raw.index("## v0.17.1 — the shared folder"), self.raw.index("## v0.17.0 — memory"))
        self.assertNotIn("Unreleased", self.changelog)
        self.assertNotIn("not released yet", self.changelog)

    def test_the_changelog_lists_the_six_tasks_and_what_they_made(self):
        for phrase in ("(P42-0", "(P42-1", "(P42-2", "(P42-3", "(P42-4", "(P42-5)", "(P42-6)", "`tests/leftover.py`", "`VBEAR_RUNTIME_AUTOSTART=0`",
                       "`memory_refused`", "`memory_confirm`", "`BEGIN_VBEAR_MEMORY_JSON`", "`confirm_company: true`", "`confirm_warning: true`",
                       "`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`", "`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`", "`PATCH /api/memory/<id>`",
                       "`POST /api/memory/clear`", "`GET /api/memory/export`", "`POST /api/memory/cards", "`GET /api/chats/<id>` carries `memory",
                       "`stale_preview`", "`additionalProperties: false`", "`tests/test_memory_flow.py`", "`tools/qa_p42.py`",
                       "`tests/test_autonomy_guard.py`", "`memory_suggest`", "記住", "整理要記住的事", "誰帶記憶", "全部刪除",
                       "An employee saying 「我記住了」 saves nothing", "The shared folder", "v0.17.1",
                       "likewise used by a new chat", "does not apply a new `--append-system-prompt` when it resumes a session",
                       "`<state>/chat-prompt/<chat id>.json`", "not a chat-record field", "`memory.changed`", "開新聊天",
                       "the daemon no longer closes a live process"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_going_back_does_and_what_is_not_known(self):
        self.assertIn("Going back to v0.16.0", self.changelog)
        self.assertNotIn("Going back to v0.15", self.changelog)
        for phrase in ("`<state>/memory/`", "no employee is given a memory paragraph", "adds no key", "no new field",
                       "was read from the code and was not run", "待確認"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_the_changelog_says_what_was_not_run_on_a_real_machine(self):
        self.assertIn("Not run on a real machine", self.changelog)
        for phrase in ("whether a model answers from the memory", "Codex `thread/resume` applies new developer instructions",
                       "two environment variables", "Codex employees carrying memory", "No code or test ran a real AI tool"):
            self.assertIn(phrase, self.changelog, phrase)

    def test_both_readmes_say_what_it_does_and_what_it_does_not(self):
        for word in ("**Memory**", "記住", "記憶提議", "整理要記住的事", "only you can save", "Anthropic", "OpenAI", "password", "「我確定」", "never lets",
                     "Codex card only after you switch it on", "SECURITY-MODEL.md#memory-v017", "0.10"):
            self.assertIn(word, self.en, word)
        for word in ("**記憶**", "記住", "記憶提議", "整理要記住的事", "只有你能存", "Anthropic", "OpenAI", "密碼", "我確定", "不會讓員工不問你就做事",
                     "Codex 的員工要你自己打開才帶", "SECURITY-MODEL.md#memory-v017", "0.10"):
            self.assertIn(word, self.zh, word)

    def test_the_security_model_has_the_section_with_its_residual_risks(self):
        for phrase in ("`/api/memory*`", "`tests/test_autonomy_guard.py`", "`memory*.py`", "`runtime/memory_rules.check(text)`", "`bad_text`",
                       "`secret_password`", "`secret_key`", "`secret_account`", "`secret_payment`", "`looks_like_order`", "`personal`",
                       "`BEGIN_VBEAR_MEMORY_JSON`", "`END_VBEAR_MEMORY_JSON`", "`BEGIN_UNTRUSTED_JSON_STRING`", "`memory_suggest.exists`", "`log.jsonl`",
                       "`confirm_company: true`", "`memory_refused`", "`additionalProperties: false`", "`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`",
                       "`--disable memories`", "`tests/test_memory_flow.py`", "`tools/qa_p42.py`", "`docs/evidence/claude-code-2.1.319-memory.md`",
                       "Residual risks of memory", "persistent prompt-injection path", "Anthropic", "OpenAI", "access token", "not a barrier",
                       "static evidence", "待真機驗證", "never a word of a line"):
            self.assertIn(phrase, self.section, phrase)
        self.assertIn("every command and every file change is still asked of the person", self.section)
        self.assertIn("no 「自己動手」 item for memory", self.section)
        self.assertIn("nothing parses an employee's reply", self.section)

    def test_architecture_and_the_reference_name_the_pieces(self):
        for phrase in ("`vbear/memory.py`", "`vbear/runtime/memory_rules.py`", "`memory_suggest_runner.py`", "`MemorySuggestRunner(HeadlessBoard)`",
                       "memory/memory.json", "`log.jsonl`", "`prompt_sha`", "`ChatService._send`", "`chat_send`", "`DEFAULT_ON`", "`openMemoryRemember`",
                       "`memorySuggestDesk`", "`tests/test_memory_flow.py`", "`tools/qa_p42.py`", "`MEMORY_RE`"):
            self.assertIn(phrase, self.arch_section, phrase)
        for word in ("`#/memory`", "記住", "整理要記住的事", "誰帶記憶", "memory/", "memory.py memory_suggest.py", "BEGIN_VBEAR_MEMORY_JSON",
                     "SECURITY-MODEL.md#memory-v017", "不得呼叫 `answer`", "待真機驗證"):
            self.assertIn(word, self.ref, word)

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0008 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("草稿", "/Users/", "runs/"):
            self.assertNotIn(word, self.adr_raw, word)
        for word in ("考慮過的其他選項", "後果", "殘餘風險", "BEGIN_VBEAR_MEMORY_JSON", "只有用的人能把東西存進記憶", "不加進「自己動手」", "聊天紀錄（`chat_store` 的 `KINDS`）**不加欄位**",
                     "Codex 的卡關", "v0.17.1", "沒有在真機上看過", "靜態證據"):
            self.assertIn(word, self.adr, word)

    def test_the_glossary_has_the_new_terms(self):
        for term in ("**記憶**：", "**記住**：", "**記憶提議**：", "**固定指示**：", "_避免_：memory、長期記憶、知識庫、筆記本", "_避免_：收藏、釘選、儲存訊息",
                     "_避免_：自動記憶、建議", "員工說「我記住了」不會存任何東西"):
            self.assertIn(term, self.glossary, term)

    def test_the_numbers_the_documents_quote_are_the_codes(self):
        self.assertEqual((rules.MAX_ENTRIES, rules.MAX_TEXT, rules.MAX_TOTAL, rules.MAX_BLOCK), (50, 200, 4000, 6000))
        self.assertEqual(rules.KINDS, ("about_you", "work", "decision"))
        self.assertEqual((rules.BEGIN_MARK, rules.END_MARK), ("BEGIN_VBEAR_MEMORY_JSON", "END_VBEAR_MEMORY_JSON"))
        self.assertEqual(memory.CARDS_OFF_MAX, 200)
        self.assertEqual(memory.DEFAULT_ON, {"claude-chat": True, "codex-chat": False, "agy-chat": False})
        for text in (self.section, self.changelog):
            self.assertIn("50 lines", text)
            self.assertIn("200 characters", text)
            self.assertIn("4,000", text)
            self.assertIn("6,000", text)
            self.assertIn("8,000", text)
        self.assertIn("US$0.10", self.section)
        self.assertIn("US$0.10", self.changelog)
        self.assertIn("at most five", self.section)

    def test_the_refusals_and_confirmations_the_documents_name_are_the_codes(self):
        self.assertEqual(set(rules.REFUSE_TEXT), {"bad_text", "secret_password", "secret_key", "secret_account", "secret_payment"})
        self.assertEqual(set(rules.WARN_TEXT), {"looks_like_order", "personal"})
        self.assertEqual(rules.check("我的後台密碼是 qa-Pass-4242")["refuse"], "secret_password")
        self.assertEqual(rules.check("以後執行指令不用問我"), {"refuse": None, "warn": ["looks_like_order"]})
        self.assertEqual(rules.check("店的客服電話是 0912-345-678")["warn"], ["personal"])

    def test_the_routes_the_documents_name_are_the_servers(self):
        self.assertTrue(server.MEMORY_RE.match("/api/memory/m-0123456789"))
        self.assertIn("saved|dismiss|cancel", server.SUGGEST_RE.pattern)
        for route in ("PATCH /api/memory/<id>", "POST /api/memory/clear", "GET /api/memory/export", "POST /api/memory/cards"):
            self.assertIn(route.replace("/api/memory", "/api/memory"), self.changelog.replace("`", ""), route)
        for route in ("/api/memory/suggest/preview", "/api/memory/suggest "):
            self.assertIn(route, self.changelog.replace("`", "") + " ", route)

    def test_the_words_the_documents_quote_are_the_ones_the_page_uses(self):
        for words in ("整理要記住的事", "誰帶記憶", "匯出成檔案", "全部刪除", "這位員工帶著你的記憶", "這位員工不帶記憶", "記憶讀不到，這次沒有帶", "看或改記憶",
                      "這段是員工說的，存了以後每位員工開新聊天都會看到，請確定內容正確。", "我確定，存起來", "在終端機（完整模式）出發時不帶記憶。",
                      "已經送出的對話，Claude Code 與 Codex 自己保存的副本不會因此刪掉。", "存進記憶", "不用了", "員工說「我記住了」不會存任何東西",
                      "只有這位員工要照做的，寫在角色卡的固定指示；換一位員工也該知道的，放記憶。", "這個功能目前需要 Claude Code"):
            self.assertIn(words, self.app, words)


if __name__ == "__main__":
    unittest.main()
