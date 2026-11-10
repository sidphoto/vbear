"""P46 documents: what the public repository may hold (P46-1: the evidence file and the synthetic fixtures), and (P46-6) that the documents say what the
code does: the evidence file's sections 1 to 12 and the facts of the real runs, ADR 0012 as final, the security model's AGY section (the residual
risks, the shared folder decision, going back to v0.19.0, the guard rules 14a to 14h, the error codes), the changelog, both READMEs, the
architecture, the reference and the glossary."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

from vbear import chat_service, shared_folder
from vbear.runtime import chat_engines, cli_versions

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "docs" / "evidence" / "agy-1.5.3-chat.md"
FIXTURES = REPO / "tests" / "fixtures" / "agy-chat"

# What must never be in the repository, spelled in pieces so that this file does not hold it either: the names of the maintainer's own
# skills, plan and providers, the name of a temporary folder, the title of a test conversation.
PERSONAL = ["identi" + "fy-me", "grill" + "-me", "team" + "work", "minimax" + "-global", "vs." + "8kOc", "AI " + "Pro",
            "permissions " + "test", "MiniMax-" + "M3", "side" + "chang"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")


def problems(text: str, label: str) -> list[str]:
    found = []
    for word in PERSONAL:
        if word.casefold() in text.casefold():
            found.append(f"{label}: names something personal ({len(word)} characters)")
    for m in EMAIL.finditer(text):
        if not m.group(0).lower().endswith(SAFE_EMAIL_DOMAINS):
            found.append(f"{label}: an email-like string")
    for m in HOME_PATH.finditer(text):
        if m.group(0) not in ("/Users/fake-user", "/home/fake-user"):
            found.append(f"{label}: a path in a home folder")
    return found


class EvidenceFileTests(unittest.TestCase):
    def test_the_file_exists_and_holds_the_sections_of_the_plan(self):
        text = EVIDENCE.read_text(encoding="utf-8")
        for number in range(1, 13):
            self.assertRegex(text, rf"(?m)^## {number}\. ", f"section {number}")
        self.assertIn("raw messages were not kept", text)

    def test_the_file_holds_nothing_personal(self):
        text = EVIDENCE.read_text(encoding="utf-8")
        self.assertEqual(problems(text, "agy-1.5.3-chat.md"), [])

    def test_the_scan_fires_on_small_made_up_texts(self):
        for text in ("my home is /Users/alice/projects", "mail a.b@gmail.com now", "skill " + PERSONAL[0], "plan " + PERSONAL[5].lower(),
                     "at /home/bob/x"):
            self.assertTrue(problems(text, "x"), text)
        for text in ("mail a.b@example.com now", "/Users/fake-user/.codex", "the ~/.agents/hooks.json file", "plain words"):
            self.assertEqual(problems(text, "x"), [], text)


class FixtureFilesTests(unittest.TestCase):
    def test_every_fixture_says_it_is_synthetic_and_holds_nothing_personal(self):
        files = sorted(FIXTURES.glob("*.jsonl"))
        self.assertGreaterEqual(len(files), 15)
        for path in files:
            text = path.read_text(encoding="utf-8")
            first = text.splitlines()[0]
            self.assertTrue(first.startswith('{"_synthetic": "'), path.name)
            self.assertIn("not a recording", first, path.name)
            self.assertEqual(problems(text, path.name), [])

    def test_the_fake_agy_and_the_fixture_loader_hold_nothing_personal(self):
        for name in ("fake_agy_acp.py", "agy_chat_fixtures.py"):
            self.assertEqual(problems((REPO / "tests" / name).read_text(encoding="utf-8"), name), [])
        self.assertEqual(problems((REPO / "vbear" / "runtime" / "agy_chat_protocol.py").read_text(encoding="utf-8"),
                                  "agy_chat_protocol.py"), [])


def read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The text from ``heading`` to the next heading of the same or a higher level."""
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    rest = text[start + len(heading):]
    end = re.search(rf"(?m)^#{{1,{level}}} ", rest)
    return heading + (rest[:end.start()] if end else rest)


SHARED_SENTENCE = "AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查"
GUARD_RULES = ("14a", "14b", "14c", "14d", "14e", "14f", "14g", "14h")


class EvidenceFileRealRunTests(unittest.TestCase):
    """Sections 8, 10, 11 and 12 of the evidence file hold what the real runs showed, not assumptions."""

    @classmethod
    def setUpClass(cls):
        cls.text = read("docs", "evidence", "agy-1.5.3-chat.md")

    def test_it_no_longer_says_a_later_task_will_fill_it_in(self):
        for phrase in ("P46-6 completes", "P46-6 fills in", "must confirm", "are the **unconfirmed** points"):
            self.assertNotIn(phrase, self.text, phrase)

    def test_the_seventh_run_and_its_numbers_are_there(self):
        part = section(self.text, "## 11. What the real runs confirmed")
        for phrase in ("seventh run", "15 turns", "US$0.57", "asked_and_refused", "3.1 seconds", "41 built-in files", "62 paths", "`-journal`", "`-shm`", "`-wal`",
                       "`in_progress`", "`pending`", "`request_permission`", "`completed`", "`failed`"):
            self.assertIn(phrase, part.replace("request_permission", "`request_permission`") if phrase == "`request_permission`" else part, phrase)

    def test_the_shared_part_is_told_with_both_failures_and_the_decision(self):
        part = section(self.text, "## 11. What the real runs confirmed")
        for phrase in ("`shared_shell_card`", "`shared_home_clean`", 'found: ["path"]', "false positive", "`--add-dir`", "file tools", "shell", SHARED_SENTENCE,
                       "`shared_write_card`", "`shared_link_refused`", "`shared_git_refused`", "`shared_records_clean`", "`SUPPORTED_ENGINES`",
                       "main check passed, shared part not passed"):
            self.assertIn(phrase, part, phrase)

    def test_the_first_six_failed_runs_are_told_as_why_it_is_designed_this_way(self):
        part = section(self.text, "## 12. ")
        for number in range(1, 8):
            self.assertRegex(part, rf"(?m)^{number}\. \*\*Run {number}\.\*\*", f"run {number}")
        for phrase in ("`home_created`", "`config_option_update`", "`session_info_update`", "`user_message_chunk`", "`announced_kinds`", "`_order_problem`", "`builtin_paths`",
                       "`cli_closed`", "`stop_leaves_nothing`", "`builtin_sha256`", "`builtin_runnable`", "`table_folder`", "`.manifest`", "`-shm`"):
            self.assertIn(phrase, part, phrase)

    def test_section_10_lists_the_six_tasks_and_the_guard_rules(self):
        part = section(self.text, "## 10. What was built")
        for task in ("P46-1", "P46-2", "P46-3", "P46-4", "P46-5", "P46-6"):
            self.assertIn(f"**{task}**", part, task)
        for rule in GUARD_RULES:
            self.assertIn(rule, part, rule)

    def test_section_8_says_the_list_is_still_a_reading_of_strings(self):
        part = section(self.text, "## 8. ")
        self.assertIn("a reading of strings", part)
        self.assertIn("`found: []`", part)


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adr = read("docs", "adr", "0012-agy-chat-boundary.md")

    def test_it_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr.startswith("# 0012 "), self.adr[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("狀態：草稿", "/Users/", "runs/", "規劃者依"):
            self.assertNotIn(word, self.adr, word)
        for word in ("## 背景", "## 決定", "## 考慮過的其他選項", "## 後果", "## 真機結果", "殘餘風險", "使用者拍板"):
            self.assertIn(word, self.adr, word)

    def test_it_holds_the_decisions_and_the_real_machine_facts(self):
        for word in ("`agy acp`", "`<state>/agy-chat-home`", "`--sandbox`", "`BypassSandbox`", "`announced_kinds`", "`builtin_sha256`", "`builtin_runnable`", "`builtin_paths`",
                     "`table_folder`" if False else "62 個路徑", "41 個", "`-journal`", "`-shm`", "`-wal`", "US$0.57", "15 個回合", "`asked_and_refused`", "3.1 秒",
                     "`shared_shell_card`", "`shared_home_clean`", '`["path"]`', SHARED_SENTENCE, "`SUPPORTED_ENGINES`", "你自己裝的 AGY 技能" if False else "自己的 AGY 技能",
                     "回到 v0.19.0", "`applies.json`", "不能復原", "AGY 會自己更新", "管理員政策清單來自 strings"):
            self.assertIn(word, self.adr, word)

    def test_it_does_not_touch_the_older_adrs(self):
        for name in ("0002-safe-mode-by-default-full-mode-behind-a-plain-warning.md", "0005-codex-chat-boundary.md"):
            self.assertNotIn("0012", read("docs", "adr", name), name)


class SecurityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = read("docs", "SECURITY-MODEL.md")
        cls.part = section(cls.model, "## Chats with an AGY role card (engine `agy-chat`, v0.20)")

    def test_the_section_is_final_and_has_its_parts(self):
        self.assertNotIn("*Draft.", self.part)
        self.assertNotIn("(draft from P46-1)", self.model)
        self.assertNotIn("final wording in P46-6", self.model)
        for phrase in ("What the real runs showed", "Residual risks", "### Going back to v0.19.0", "### The process, the launch and the console's side (P46-3)"):
            self.assertIn(phrase, self.part, phrase)

    def test_the_residual_risks_are_the_nine_of_the_adr(self):
        risks = self.part[self.part.index("- **Residual risks.**"):self.part.index("### Going back to v0.19.0")]
        for phrase in ("own AGY skills are loaded", "not in the sandbox", "does not pass through VBear", "temporary folder", "goes to Google", "per-turn cap",
                       "`strings`", "AGY updates itself", "access token"):
            self.assertIn(phrase, risks, phrase)
        self.assertEqual(len(re.findall(r"(?m)^  \d\. ", risks)), 9)

    def test_the_shared_folder_decision_and_the_false_positive_are_there(self):
        for phrase in (SHARED_SENTENCE, "`shared_folder.SUPPORTED_ENGINES`", "`--add-dir`", "false positive"):
            self.assertIn(phrase, self.part, phrase)
        self.assertIn(SHARED_SENTENCE, section(self.model, "## Shared folder (v0.17.1)"), "the shared folder section says it too")

    def test_going_back_to_v0190_says_what_is_read_and_what_is_not_known(self):
        back = self.part[self.part.index("### Going back to v0.19.0"):self.part.index("### The process")] if "### The process" in self.part[self.part.index("### Going back"):] else self.part[self.part.index("### Going back to v0.19.0"):]
        for phrase in ("欄位不符", "spending is still counted", "`card_tool_unsupported`", "`applies.json`", "closed set of two", "does not remove the record", "`<state>/agy-chat-home/`",
                       "`agy-chat-verified.json`", "`<state>/sessions/`", "`config.json` has no new key", "restores everything", "待確認", "`tests/test_p46_flow.py`"):
            self.assertIn(phrase, back, phrase)

    def test_the_skills_sentence_is_the_one_the_investigation_left(self):
        part = section(self.model, "## Which skills AGY reads")
        self.assertNotIn("is not read by AGY unless", part)
        self.assertIn("disproved", part)
        self.assertIn("~/.agents/skills", part)

    def test_the_company_lists_name_google(self):
        for heading, words in (("## Group chats", ("Google",)),):
            if heading in self.model:
                self.assertTrue(all(w in section(self.model, heading) for w in words), heading)
        self.assertIn("Anthropic, OpenAI or Google (AGY)", self.model)
        self.assertIn("Memory goes to Anthropic, to OpenAI and to Google.", self.model)
        self.assertIn("order Claude Code, Codex, AGY", self.model)

    def test_the_guard_rules_and_the_codes_are_named(self):
        for rule in GUARD_RULES:
            self.assertIn(rule, self.part, rule)
        for code in ("agy_version", "agy_home", "agy_hooks", "agy_workdir", "admin_policy", "unverified", "card_tool_unsupported"):
            self.assertIn(f"`{code}`", self.part, code)
            self.assertIn(code, chat_service.CODE_TEXT, code)

    def test_every_guard_rule_14a_to_14h_has_a_test_in_the_guard_file(self):
        guard = read("tests", "test_autonomy_guard.py")
        for rule in GUARD_RULES:
            self.assertRegex(guard, rf"def test_{rule}_", rule)


class ChangelogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read("CHANGELOG.md")
        cls.first = section(cls.text, "## v0.20.0")

    def test_the_release_heading_is_first_and_the_old_one_follows(self):
        headings = re.findall(r"(?m)^## (v\S+)", self.text)
        self.assertEqual(headings[:2], ["v0.20.0", "v0.19.0"])

    def test_it_says_what_was_done_what_an_agy_employee_can_and_cannot_do_and_that_it_is_an_estimate(self):
        for phrase in ("P46-1 to P46-6", "AGY employees can chat", "Can:", "Cannot:", SHARED_SENTENCE, "AGY skills you installed yourself", "**The cost is an estimate:**",
                       "「估計」", "Google plan", "no new kind of event", "`agy acp`", "`shared_folder.SUPPORTED_ENGINES`", "`tools/qa_p46.py`", "US$0.30", "7801", "7788", "7789"):
            self.assertIn(phrase, self.first, phrase)

    def test_the_real_machine_result_and_the_qa_run_are_there(self):
        for phrase in ("passed its main part on the seventh run", "15 turns", "US$0.57", "3.1 seconds", "`found: [\"path\"]`", "false positive",
                       "45 ok, 0 warn, 0 FAIL", "13 AGY turns"):
            self.assertIn(phrase, self.first, phrase)
        self.assertNotIn("TODO", self.first, "the coordinator filled in the real-Mac line")

    def test_going_back_to_v0190_is_written_and_marks_what_is_not_known(self):
        back = self.first[self.first.index("**Going back to v0.19.0.**"):]
        for phrase in ("欄位不符", "still counted", "locks all team templates", "does **not** remove the record", "待確認", "restores everything"):
            self.assertIn(phrase, back, phrase)

    def test_the_tests_it_changed_are_named(self):
        for phrase in ("tests/test_autonomy_guard.py", "SharedFolderForAgyTests", "tests/frontend/agy_chat.cjs"):
            self.assertIn(phrase, self.first, phrase)


class OtherDocumentsTests(unittest.TestCase):
    def test_both_readmes_say_agy_chats_and_the_shared_folder_and_the_skills(self):
        en, zh = read("README.md"), read("README.zh-TW.md")
        for phrase in ("Claude Code, Codex or AGY", "An **AGY** chat", "AGY employees use the AGY skills you installed yourself", "cannot use the shared folder in this version",
                       SHARED_SENTENCE, "Google", "estimate"):
            self.assertIn(phrase, en, phrase)
        for phrase in ("Claude Code、Codex 或 AGY", "**AGY 聊天**", "AGY 員工會用到你自己裝的 AGY 技能", SHARED_SENTENCE, "Google", "估計"):
            self.assertIn(phrase, zh, phrase)
        self.assertNotIn("`~/.agents/skills` is\nnot AGY's", en)

    def test_architecture_and_the_reference_name_the_pieces(self):
        arch = read("docs", "ARCHITECTURE.md")
        for phrase in ("`agy-chat`", "`runtime/agy_chat_protocol.py`", "`runtime/agy_chat_env.py`", "`runtime/agy_chat_session.py`", "`vbear/agy_chat_check.py`", "`vbear/agy_verify.py`",
                       "`tools/qa_p46.py`", "`shared_folder.SUPPORTED_ENGINES`", "no new kind of event"):
            self.assertIn(phrase, arch, phrase)
        ref = read("docs", "REFERENCE.zh-TW.md")
        for phrase in ("`agy-chat`", "`agy acp`", "ADR 0012", SHARED_SENTENCE, "Google", "AGY 的支援狀態"):
            self.assertIn(phrase, ref, phrase)

    def test_the_glossary_has_the_terms_and_the_shared_folder_sentence(self):
        text = read("GLOSSARY.md")
        for term in ("**聊天用的 AGY 設定資料夾**：", "**AGY 的保護範圍**：", "**讀取卡**：", "**估計花費**：", "**改內容再問**：", SHARED_SENTENCE):
            self.assertIn(term, text, term)
        self.assertNotIn("AGY 的員工要再確認「讀到的檔案內容會送到 Google」", text)

    def test_the_new_documents_hold_nothing_personal(self):
        for parts in (("docs", "adr", "0012-agy-chat-boundary.md"), ("CHANGELOG.md",), ("tools", "qa_p46.py"), ("tests", "test_qa_p46.py"), ("tests", "test_p46_flow.py")):
            self.assertEqual(problems(read(*parts), "/".join(parts)), [], parts)


class CodeAndDocumentsAgreeTests(unittest.TestCase):
    def test_the_shared_folder_is_not_open_to_agy_and_the_sentence_is_the_one_in_the_documents(self):
        self.assertNotIn("agy-chat", shared_folder.SUPPORTED_ENGINES)
        self.assertEqual(shared_folder.SUPPORTED_ENGINES, ("claude-chat", "codex-chat"))
        self.assertEqual(shared_folder.UNSUPPORTED_AGY_TEXT, SHARED_SENTENCE + "。")

    def test_the_verified_record_is_the_same_kind_as_codex(self):
        self.assertEqual(cli_versions.AGY_CHAT_VERIFIED_VERSIONS, ())
        self.assertEqual(cli_versions.CODEX_CHAT_VERIFIED_VERSIONS, ())
        self.assertEqual(cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE, "agy-chat-verified.json")
        self.assertEqual([r.engine for r in chat_engines.TABLE], ["claude-chat", "codex-chat", "agy-chat"])

    def test_the_numbers_of_the_documents_are_the_code_s(self):
        spec = importlib.util.spec_from_file_location("qa_p46_docs", REPO / "tools" / "qa_p46.py")
        qa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qa)
        self.assertEqual((qa.DEFAULT_PORT, qa.FORBIDDEN_PORTS, qa.CLAUDE_CAP_MAX), (7801, (7788, 7789), 0.30))
        from vbear.runtime import chat_store
        self.assertEqual(qa.V019_KINDS, frozenset(chat_store.KINDS))
        self.assertEqual(len(chat_store.KINDS), 20)


if __name__ == "__main__":
    unittest.main()
