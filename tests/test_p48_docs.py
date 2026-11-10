"""P48-7 documents: ADR 0014 is final (and ADR 0001's Q1-4 says what changed), the changelog, both READMEs, the security model, the architecture,
the reference and the glossary say what v0.22.0 changed and what it did not, the words they quote are the page's, the files of guard rule 16 are
there and each carries its number, the version is 0.22.0, and nothing P48-7 added names a person or a machine.

Seams: the text of the documents (whitespace flattened), the page's source for the words it uses, and the files of the guard rule."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_p47_docs import flat, problems, raw, section

ROOT = Path(__file__).resolve().parent.parent


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("docs", "adr", "0014-pick-one-ai-first.md")
        cls.adr = flat(cls.raw)
        cls.first = flat(raw("docs", "adr", "0001-users-who-never-open-a-terminal.md"))

    def test_it_is_final_and_has_the_sections_of_the_others(self):
        self.assertTrue(self.raw.startswith("# 0014 "))
        self.assertIn("狀態：已決定", self.adr)
        for heading in ("## 背景", "## 決定", "## 沒有改的", "## 考慮過的其他選項", "## 後果", "## 守門規則 16", "## 真機驗證"):
            self.assertIn(heading, self.raw, heading)
        for left_over in ("草稿", "/Users/", "runs/", "定稿）"):
            self.assertNotIn(left_over, self.raw, left_over)
        for n in range(1, 14):
            self.assertRegex(self.raw, rf"(?m)^{n}\. \*\*", f"decision {n}")

    def test_it_says_the_decisions_in_the_words_of_the_page(self):
        for word in ("先選一家你要用的 AI", "之後支援", "其他 AI 工具（之後隨時可以加）", "選這個", "換一家", "試一下，並做聊天安全檢查", "確認，開始", "下一步：建立 CEO",
                     "`vbear-setup-pick`", "`vbear-notify`", "`GET /api/first-ceo?tool=<id>`", "載入中…", "`spend-keep/`", "不預選、不標「建議」", "不跨版本沿用",
                     "`tools/qa_p48.py`", "US$0.30", "Not tried on a real machine", "`GET /api/chats`", "`--version`", "協調者", "5 到 10 秒", "不在測試裡啟動瀏覽器"):
            self.assertIn(word, self.adr, word)

    def test_it_says_what_it_did_not_touch(self):
        for word in ("啟動邊界沒有碰", "`agent_launch.py`", "`cli_versions.py`", "`admin_policy.py`", "不新增 API 路徑、設定鍵或聊天事件種類", "回到 v0.21.0", "聊天本來就把花費留在 `chat-spend/`"):
            self.assertIn(word, self.adr, word)

    def test_the_seven_rules_of_guard_16_are_named_with_the_file_that_tests_them(self):
        where = {"16a": "tests/frontend/p48_setup.cjs", "16b": "tests/frontend/p48_setup.cjs", "16c": "tests/frontend/p48_home.cjs", "16d": "tests/frontend/p48_home.cjs",
                 "16e": "tests/frontend/p48_notify.cjs", "16f": "tests/test_autonomy_guard.py", "16g": "tests/frontend/p48_chat.cjs"}
        for rule, path in where.items():
            line = next((l for l in self.raw.splitlines() if l.startswith(f"- **{rule} ")), "")
            self.assertTrue(line, rule)
            self.assertIn(path, line, rule)
        e = next(l for l in self.raw.splitlines() if l.startswith("- **16e "))
        self.assertIn("macos/test_waiting_bridge.sh", e)
        self.assertIn("tests/test_p48_notify_static.py", e)

    def test_adr_0001_says_what_changed(self):
        q14 = section(self.first, "## 補充：開始設定列哪些 AI 工具（Q1-4）", "## 補充：只有 Codex 或 AGY 的人（Q1-5）")
        for word in ("v0.22.0 修正（ADR 0014）", "先選一家", "之後支援", "其他 AI 工具", "不預選、不標建議"):
            self.assertIn(word, q14, word)
        self.assertIn("選 B：Claude Code、Codex、AGY 三個並列", q14)                    # the decision of its day is kept

    def test_the_adr_holds_nothing_personal(self):
        self.assertEqual(problems(self.raw, "0014"), [])


class GuardRuleTests(unittest.TestCase):
    def test_the_files_exist_and_each_carries_the_number_of_its_rule(self):
        guard = raw("tests", "test_autonomy_guard.py")
        for rule in "abcdefg":
            self.assertIn(f"     16{rule}  ", guard, f"16{rule} in the guard's description")
        for rule, path in (("16a", ("tests", "frontend", "p48_setup.cjs")), ("16b", ("tests", "frontend", "p48_setup.cjs")), ("16c", ("tests", "frontend", "p48_home.cjs")),
                           ("16d", ("tests", "frontend", "p48_home.cjs")), ("16e", ("tests", "frontend", "p48_notify.cjs")), ("16e", ("tests", "test_p48_notify_static.py")),
                           ("16g", ("tests", "frontend", "p48_chat.cjs")), ("16f", ("tests", "test_p48_spend_keep.py"))):
            self.assertIn(rule, raw(*path), "/".join(path))
        for rule in ("16a", "16b", "16c", "16d", "16g"):
            text = raw("tests", "frontend", {"16a": "p48_setup.cjs", "16b": "p48_setup.cjs", "16c": "p48_home.cjs", "16d": "p48_home.cjs", "16g": "p48_chat.cjs"}[rule])
            self.assertRegex(text, rf'test\("{rule}[: ]', rule)
        self.assertTrue((ROOT / "macos" / "test_waiting_bridge.sh").is_file())
        self.assertRegex(guard, r"class DeletingNeverLowersTheDay")
        self.assertIn("def test_16f_", guard)
        self.assertRegex(guard, r"class Guard16FilesAreThere")

    def test_rules_one_to_fifteen_are_still_described(self):
        guard = raw("tests", "test_autonomy_guard.py")
        for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15):
            self.assertRegex(guard, rf"(?m)^  {n}\. ", f"rule {n}")
        for rule in ("15a", "15b", "15c", "15d", "15e"):
            self.assertIn(f"     {rule}  ", guard, rule)

    def test_the_front_end_tests_of_the_release_are_there(self):
        for name in ("p48_setup.cjs", "p48_home.cjs", "p48_chat.cjs", "p48_notify.cjs", "p48_sweep.cjs"):
            self.assertTrue((ROOT / "tests" / "frontend" / name).is_file(), name)


class ChangelogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = raw("CHANGELOG.md")
        cls.first = flat(section(cls.text, "## v0.22.0", "## v0.21.0"))

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertTrue(self.text.startswith("# Changelog\n\n## v0.22.0 — easier to pick up, part 2 (好上手 2)\n"), self.text[:90])
        self.assertLess(self.text.index("## v0.22.0"), self.text.index("## v0.21.0"))
        self.assertNotIn("Unreleased", self.first)

    def test_it_has_the_parts_of_the_last_release(self):
        for word in ("**What you will see.**", "**The tasks.**", "**What did not change (safety).**", "**Money.**", "**Known limits.**", "- **On a real Mac:**",
                     "- **Going back to v0.21.0.**", "**Not tried on a real machine:**"):
            self.assertIn(word, self.first, word)

    def test_it_says_what_the_release_does_in_the_words_of_the_page(self):
        for word in ("先選一家你要用的 AI", "「之後支援」", "「選這個」", "「換一家」", "「檢查能不能用」", "「試一下，並做聊天安全檢查」", "「確認，開始」", "「下一步：建立 CEO」", "「載入中…」", "「讀不到…」",
                     "「通知」", "`vbear-setup-pick`", "`vbear-notify`", "`GET /api/first-ceo?tool=<id>`", "`spend-keep/`", "#86", "`window.webkit.messageHandlers.vbearWaiting`",
                     "at most every 30 seconds", "「計畫整理好了嗎？」", "「請幕僚長安排」", "「先不用」"):
            self.assertIn(word, self.first, word)

    def test_it_says_what_did_not_change_and_the_rules(self):
        for word in ("No server route (API), setting key, kind of chat event or `localStorage` key beyond the two new ones", "`agent_launch.py`", "`cli_versions.py`", "`admin_policy.py`",
                     "once per version on each Mac", "not carried to another version", "rule 16 was added", "16a", "16b", "16c", "16d", "16e", "16f", "16g",
                     "never lowers"):
            self.assertIn(word, self.first, word)
        self.assertIn("The guard rules 1 to 15 are as they were", self.first)

    def test_the_known_limits_are_the_real_ones(self):
        for word in ("`GET /api/chats` makes the console run the three AI tools' `--version`", "2 to 7 seconds", "5 to 10 seconds", "`request_queue_size` was not changed", "2.4 to 10 seconds",
                     "/logo.svg?r=1", "does not clear the stored pick", "revoked in System Settings", "ad-hoc", "33 to 42 minutes", "judge functions"):
            self.assertIn(word, self.first, word)

    def test_the_real_machine_line_is_left_for_the_coordinator_and_what_was_not_tried_is_honest(self):
        line = next(l for l in self.text.splitlines() if l.startswith("- **On a real Mac:**") and "v0.22.0" in l)
        for word in ("TO BE FILLED BY THE COORDINATOR", "administrator setting", "`--haiku` could not run", "permission window", "number on the Dock", "notification really appearing",
                     "after upgrading"):
            self.assertIn(word, line, word)

    def test_going_back_to_v021_is_read_from_the_old_code_and_marks_what_is_not_known(self):
        line = next(l for l in self.text.splitlines() if l.startswith("- **Going back to v0.21.0.**"))
        for word in ("Nothing is migrated", "spend-keep/", "`vbear-setup-pick`", "`vbear-notify`", "one row per tool", "same format", "does not send `?tool=`", "posts nothing", "待確認"):
            self.assertIn(word, line, word)

    def test_the_changelog_holds_nothing_personal(self):
        self.assertEqual(problems(section(self.text, "## v0.22.0", "## v0.21.0"), "CHANGELOG v0.22"), [])


class SecurityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = flat(raw("docs", "SECURITY-MODEL.md"))
        cls.section = section(cls.model, "## Easy start 2 (v0.22)")
        cls.app = raw("web", "app.js")

    def test_the_section_is_the_last_one_and_says_no_boundary_moved(self):
        self.assertEqual(self.model.count("## Easy start 2 (v0.22)"), 1)
        self.assertNotIn(" ## ", self.section[len("## Easy start 2 (v0.22)"):])
        for word in ("does not move any start-up boundary", "`vbear/agent_launch.py`", "`vbear/cli_versions.py`", "`vbear/admin_policy.py`", "No route (API path), no key of `config.json` and no kind of chat event",
                     "`vbear-setup-pick` and `vbear-notify`", "rule 16", "rules 1 to 15 were not loosened", "Residual risks", "Going back to v0.21.0"):
            self.assertIn(word, self.section, word)

    def test_it_describes_each_thing_that_could_have_widened_something(self):
        for word in ("The picker asks and decides nothing", "(guard rule 16b)", "**the plan never swaps in another tool**", "Only 「確認，開始」 sends", "(guard rule 16a)",
                     "not carried to another version and is not kept in the browser", "Home says what it has not read yet", "(16c)", "(16d)", "The notification is local, count-only and off by default",
                     "only that press asks the Mac for permission", "no `URLSession`, `URLRequest` or `Process`", "(16e", "(guard rule 16f)", "fail closed", "409 `running`", "(16g)",
                     "`GET /api/chats` makes the console run the three AI tools' `--version`", "`request_queue_size`", "ad-hoc"):
            self.assertIn(word, self.section, word)

    def test_the_sentences_it_quotes_are_the_pages(self):
        for words in ("試一下，並做聊天安全檢查", "確認，開始", "選這個", "換一家", "載入中", "計畫整理好了嗎？", "詳細資訊", "每件事先問我"):
            self.assertTrue(words in self.app, words)
            self.assertTrue(words in self.section, words)
        for const in ("CHAT_VERIFY_COST_CLAUDE", "CHAT_VERIFY_COST_CODEX", "CHAT_AGY_VERIFY_COST"):
            self.assertIn(const, self.app)
            self.assertIn(const, self.section)

    def test_the_section_holds_nothing_personal(self):
        self.assertEqual(problems(self.section, "SECURITY-MODEL v0.22"), [])


class ReadmeReferenceArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = flat(raw("README.md"))
        cls.zh = flat(raw("README.zh-TW.md"))
        cls.ref = flat(raw("docs", "REFERENCE.zh-TW.md"))
        cls.arch = flat(raw("docs", "ARCHITECTURE.md"))
        cls.app = raw("web", "app.js")

    def test_both_readmes_say_what_v022_is_and_point_to_the_documents(self):
        for text in (self.en, self.zh):
            for word in ("v0.22", "先選一家你要用的 AI", "之後支援", "試一下，並做聊天安全檢查", "載入中…", "CHANGELOG.md", "docs/adr/0014-pick-one-ai-first.md", "Easy start 2 (v0.22)"):
                self.assertIn(word, text, word)
        self.assertIn("Mac notification", self.en)
        self.assertIn("off by default", self.en)
        self.assertIn("Mac 通知開關，預設關", self.zh)
        self.assertEqual(problems(self.en, "README"), [])
        self.assertEqual(problems(self.zh, "README.zh-TW"), [])

    def test_the_reference_has_the_start_up_page_the_home_page_the_settings_and_the_state_folder(self):
        for word in ("`#/setup`", "先選一家你要用的 AI", "「檢查能不能用」清單", "`vbear-setup-pick`", "「下一步：建立 CEO」", "`GET /api/first-ceo?tool=<id>`", "「載入中…」", "`(N) VBear`", "「**通知**」一塊",
                     "`spend-keep/<種類>-<id>.json`", "資料夾 0700、檔案 0600", "保留兩天"):
            self.assertIn(word, self.ref, word)
        self.assertEqual(problems(self.ref, "REFERENCE"), [])

    def test_the_architecture_has_the_section_and_names_things_the_page_and_the_code_have(self):
        marker = "## Easy start 2 — `web/app.js`, `macos/VBear/main.swift`, `vbear/spend_keep.py`, `vbear/first_ceo.py` (v0.22)"
        self.assertIn(marker, self.arch)
        part = section(self.arch, marker, "## Front end — `web/`")
        for name in ("setupPickerNode", "setupCheckNode", "setupPickRead", "setupPickWrite", "setupCheckConfirmLines", "chatPrepState", "homeLoadingLine", "homeWaitingRows", "waitingTitleText",
                     "ceoOpeningChoices", "ceoPlanShaped", "ceoChiefHint", "notifySettings", "notifyIsOn"):
            self.assertIn(name, part, name)
            self.assertRegex(self.app, rf"(function|const) {name}\b", f"web/app.js has {name}")
        for word in ("`vbear-setup-pick`", "`vbear-notify`", "`WAITING_REUSE_MS`", "vbearWaiting", "vbearNotifyAnswer", "spend-keep/", "`first_ceo.plan(..., wanted=None)`", "/api/first-ceo?tool=<id>",
                     "`tools/qa_p48.py`", "`GET /api/chats`", "coordinator's decision", "16a", "16b", "16c", "16d", "16e", "16f", "16g"):
            self.assertIn(word, part, word)
        self.assertEqual(problems(part, "ARCHITECTURE v0.22"), [])
        import vbear.spend_keep as spend_keep
        self.assertEqual(sorted(spend_keep.KINDS), ["chief", "meeting", "memory_suggest", "skill_suggest", "staffing"])
        for kind in spend_keep.KINDS:
            self.assertIn(f"`{kind}`", part, kind)


class GlossaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = raw("GLOSSARY.md")
        cls.text = flat(cls.raw)

    def test_the_new_terms_are_there_each_with_a_definition_and_what_to_avoid(self):
        for term in ("先選一家你要用的 AI", "之後支援", "其他 AI 工具", "檢查能不能用", "試一下，並做聊天安全檢查", "聊天安全檢查", "下一步：建立 CEO", "載入中", "等你按卡片", "讀不完整", "通知",
                     "Dock 上的數字", "開場選項", "詳細資訊", "「計畫整理好了嗎？」提示", "訊息橋", "花費墓碑"):
            m = re.search(rf"(?ms)^\*\*{re.escape(term)}\*\*：\n(.+?)\n_避免_：(.+?)$", self.raw)
            self.assertTrue(m, term)
            self.assertGreater(len(m.group(1)), 20, term)

    def test_the_old_words_are_in_the_avoid_column_and_the_updated_terms_say_the_new_thing(self):
        for word in ("選擇供應商", "即將推出", "推播", "badge", "快捷回覆", "驗證聊天", "回收桶"):
            self.assertIn(word, self.text, word)
        start = section(self.text, "**開始設定**：", "**AI 工具**：")
        self.assertIn("先選一家你要用的 AI", start)
        self.assertIn("下一步：建立 CEO", start)
        waiting = section(self.text, "**等你決定**：", "**用量與上限**：")
        self.assertIn("允許這一次", waiting)
        self.assertNotIn("「驗證聊天」", self.text.split("**聊天用的 AGY 設定資料夾**：")[1].split("**AGY 的保護範圍**")[0])

    def test_the_words_it_says_the_page_uses_are_the_pages(self):
        app = raw("web", "app.js")
        for words in ("先選一家你要用的 AI", "之後支援", "其他 AI 工具（之後隨時可以加）", "檢查能不能用", "試一下，並做聊天安全檢查", "下一步：建立 CEO", "選這個", "換一家", "請幕僚長安排", "先不用",
                      "vbearWaiting", "vbearNotifyAnswer", "vbear-setup-pick"):
            self.assertIn(words, app, words)

    def test_the_glossary_holds_nothing_personal(self):
        self.assertEqual(problems(self.raw, "GLOSSARY"), [])


class VersionAndWalkTests(unittest.TestCase):
    def test_the_version_is_the_release(self):
        import vbear
        self.assertEqual(vbear.__version__, "0.22.0")
        self.assertIn("## v0.22.0", raw("CHANGELOG.md"))

    def test_the_script_and_its_test_are_there_and_hold_nothing_personal(self):
        for path in (("tools", "qa_p48.py"), ("tests", "test_qa_p48.py")):
            self.assertTrue(ROOT.joinpath(*path).is_file(), "/".join(path))
            self.assertEqual(problems(raw(*path), "/".join(path)), [], "/".join(path))
        doc = raw("tools", "qa_p48.py")
        self.assertIn("coordinator", doc)
        self.assertIn("/api/chats", doc)
        self.assertTrue((ROOT / "tools" / "qa_p47.py").is_file())                           # (it is imported, not copied, and not changed)

    def test_the_script_is_not_part_of_the_package_and_no_test_starts_it(self):
        for path in (ROOT / "tests").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.name in ("test_qa_p48.py", "test_qa_p47.py", "test_p48_docs.py", "test_p47_docs.py"):
                continue
            self.assertNotRegex(text, r"subprocess[^\n]*qa_p4[78]", path.name)


if __name__ == "__main__":
    unittest.main()
