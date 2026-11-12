"""P47-6 documents: ADR 0013 is final (and ADR 0001's Q4 says where the daily limit is now), the changelog, both READMEs, the security model, the
architecture and the reference say what v0.21.0 changed and what it did not, the words they quote are the page's, the five files of guard rule 15 are
there and each carries its number, and nothing in what P47-6 added names a person or a machine.

Seams: the text of the documents (whitespace flattened), the page's source for the words it uses, and the files of the guard rule."""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# No list of private names is kept in this repository: it is public, and a list of words that must not appear is itself a list of them (even spelled
# in pieces). The checks are generic patterns (an email-like string that is not an example address, a path in a home folder). A person who wants
# to look for private words too puts them, one a line, in a file of their own outside git and names it in VBEAR_DOCS_DENYLIST when they run the tests.
def _local_denylist() -> list[str]:
    path = os.environ.get("VBEAR_DOCS_DENYLIST", "")
    if not path:
        return []
    try:
        return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


PERSONAL = _local_denylist()
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def raw(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


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


def section(text: str, start: str, end: str | None = None) -> str:
    i = text.index(start)
    j = text.index(end, i + len(start)) if end else len(text)
    return text[i:j]


class AdrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adr_raw = raw("docs", "adr", "0013-plain-navigation.md")
        cls.adr = flat(cls.adr_raw)
        cls.first = flat(raw("docs", "adr", "0001-users-who-never-open-a-terminal.md"))

    def test_the_adr_is_final_and_in_the_format_of_the_others(self):
        self.assertTrue(self.adr_raw.startswith("# 0013 "), self.adr_raw[:30])
        self.assertIn("狀態：已決定", self.adr)
        for word in ("草稿", "/Users/", "runs/", "P47-6 定稿"):
            self.assertNotIn(word, self.adr_raw, word)
        for heading in ("## 背景", "## 決定", "## 考慮過的其他選項", "## 後果", "## 守門規則 15", "## 真機驗證"):
            self.assertIn(heading, self.adr_raw, heading)

    def test_it_holds_the_nine_decisions_and_the_reasons_for_each_other_option(self):
        for word in ("選單四項", "進階模式不是權限", "等你決定", "只用一套「公司」說法", "花費收起來，上限照樣把關", "聊天頁只剩對話", "建立 CEO，開始聊」直接進對話",
                     "錯誤白話在畫面做", "預設每天、開著", "AI 仍然不能自己調高上限", "保護範圍", "花費做成選單一項", "把花費上限拿掉或預設不限"):
            self.assertIn(word, self.adr, word)
        for n in range(1, 10):
            self.assertRegex(self.adr_raw, rf"(?m)^{n}\. \*\*", f"decision {n}")

    def test_the_five_rules_of_guard_15_are_named_with_the_file_that_tests_them(self):
        for rule, where in (("15a", "tests/test_autonomy_guard.py"), ("15b", "tests/test_autonomy_guard.py"), ("15c", "tests/frontend/p47_home.cjs"),
                            ("15d", "tests/frontend/p47_settings.cjs"), ("15e", "tests/frontend/p47_chat.cjs")):
            line = next((l for l in self.adr_raw.splitlines() if l.startswith(f"- **{rule} ")), "")
            self.assertTrue(line, rule)
            if rule in ("15c", "15d", "15e"):
                self.assertIn(where, line, rule)
        self.assertIn("`tests/test_autonomy_guard.py`", self.adr)

    def test_it_says_which_boundaries_were_not_touched_and_how_the_walk_is_done(self):
        for word in ("沒有碰啟動邊界", "`vbear/autonomy.py`", "`vbear/first_ceo.py`", "localStorage", "`tools/qa_p47.py`", "US$0.30", "不在測試裡啟動瀏覽器"):
            self.assertIn(word, self.adr, word)

    def test_adr_0001_says_the_daily_limit_is_now_folded_and_where(self):
        q4 = section(self.first, "## 補充：每天花費上限由用的人第一次自己選（Q4）", "## 補充：先不申請 Apple 開發者簽章（Q5）")
        for word in ("v0.21.0 修正（ADR 0013 第 5 點）", "預設收起", "自己填（0.01 到 50）", "用量與上限", "上限本身沒有變弱"):
            self.assertIn(word, q4, word)
        self.assertIn("選 C：開始設定頁問用的人每天最多花 US$1、US$3 或 US$10", q4)             # the decision of its day is kept

    def test_the_adr_holds_nothing_personal(self):
        self.assertEqual(problems(self.adr_raw, "0013"), [])


class GuardRuleTests(unittest.TestCase):
    def test_the_five_files_exist_and_each_carries_the_number_of_its_rule(self):
        guard = raw("tests", "test_autonomy_guard.py")
        for rule in ("15a", "15b", "15c", "15d", "15e"):
            self.assertIn(f"     {rule}  ", guard, f"{rule} in the guard's description")
        self.assertIn("def test_15a_", guard)
        for rule, path in (("15c", ("tests", "frontend", "p47_home.cjs")), ("15d", ("tests", "frontend", "p47_settings.cjs")),
                           ("15e", ("tests", "frontend", "p47_chat.cjs"))):
            text = raw(*path)
            self.assertIn(rule, text, "/".join(path))
            self.assertRegex(text, rf'test\("{rule}:', "/".join(path))
        self.assertRegex(guard, r"15b")
        self.assertTrue(re.search(r"class NothingNewIsAsked", guard))

    def test_rules_one_to_fourteen_are_still_described(self):
        guard = raw("tests", "test_autonomy_guard.py")
        for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11):                    # (the docstring numbers them as the rules came; 10 is in the text of 9)
            self.assertRegex(guard, rf"(?m)^  {n}\. ", f"rule {n}")

    def test_the_rest_of_the_front_end_tests_of_the_release_are_there(self):
        for name in ("p47_nav.cjs", "p47_words.cjs", "p47_home.cjs", "p47_settings.cjs", "p47_chat.cjs"):
            self.assertTrue((ROOT / "tests" / "frontend" / name).is_file(), name)


class ChangelogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = raw("CHANGELOG.md")
        cls.first = flat(section(cls.text, "## v0.21.0", "## v0.20.0"))

    def test_the_release_heading_is_first_and_not_unreleased(self):
        self.assertIn("\n## v0.21.0 — easier to pick up (好上手 1)\n", self.text)                  # (P48-7 put v0.22.0 in front of it)
        self.assertRegex(self.text, r"\A# Changelog\n\n## v0\.\d+\.\d+ — ")
        self.assertLess(self.text.index("## v0.21.0"), self.text.index("## v0.20.0"))
        self.assertNotIn("Unreleased", self.first)

    def test_it_says_what_changed_in_plain_words_and_lists_the_six_tasks(self):
        for word in ("four items", "首頁", "員工", "工作", "設定", "進階模式", "等你決定", "想做什麼？跟 CEO 說", "建立 CEO，開始聊", "用量與上限", "US$0.01 to US$50",
                     "every limit is still checked and enforced exactly as before", "「⋯」", "技術細節", "保護範圍（沙盒）", "every day and on",
                     "P47-1", "P47-2", "P47-3", "P47-4", "P47-5", "P47-6", "Codex"):
            self.assertIn(word, self.first, word)

    def test_it_says_what_did_not_change_and_the_five_rules(self):
        for word in ("What did not change (safety)", "No server route (API), setting, data file, kind of chat event or `localStorage` key was added", "15a", "15b", "15c", "15d", "15e",
                     "Advanced mode is not a permission", "the AI still cannot raise a limit", "Money.", "Known limits."):
            self.assertIn(word, self.first, word)

    def test_it_does_not_overstate_the_money_the_routes_or_the_sweep(self):
        for word in ("There is no amount of money in the new home blocks", "so its cards can still show amounts", "port 7802 only", "for both versions together",
                     "never counted as zero", "the page has two new addresses", "17 normal pages", "not by that sweep"):
            self.assertIn(word, self.first, word)
        self.assertNotIn("There is no amount of money on the home page", self.first)
        self.assertNotIn("refuses the ports 7788 and 7789", self.first)
        adr = flat(raw("docs", "adr", "0013-plain-navigation.md"))
        self.assertIn("新的一般首頁區塊沒有金額", adr)
        self.assertNotIn("首頁沒有金額；", adr)
        self.assertIn("the new home blocks show no amount", flat(raw("docs", "SECURITY-MODEL.md")))

    def test_it_describes_the_real_machine_walk_with_its_caps(self):
        for word in ("tools/qa_p47.py", "--remote-debugging-pipe", "no TCP port", "--no-ai", "--haiku", "US$0.30", "7788", "7789", "tests/test_qa_p47.py", "tests/test_p47_docs.py"):
            self.assertIn(word, self.first, word)

    def test_the_line_for_the_real_mac_is_there_for_the_release_to_fill(self):
        self.assertIn("**On a real Mac:**", self.first)

    def test_it_says_what_going_back_to_v0_20_0_does(self):
        self.assertIn("Going back to v0.20.0", self.first)
        for word in ("Nothing is migrated", "`advanced_mode` is a key v0.20.0 already has", "目前的每天上限是 US$5，不是這三個之一", "19 items", "`#/employees` and `#/work` say 「找不到這個頁面」",
                     "`#/settings?open=limits` is the plain settings page", "待確認"):
            self.assertIn(word, self.first, word)

    def test_the_version_number_is_left_for_the_release(self):
        import vbear
        self.assertRegex(vbear.__version__, r"^0\.\d+\.\d+$")


class SecurityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = flat(raw("docs", "SECURITY-MODEL.md"))
        cls.section = section(cls.model, "## Plain navigation (v0.21)", "## Easy start 2 (v0.22)")   # (P48-7 added a section after it)
        cls.app = raw("web", "app.js")

    def test_the_section_is_the_last_one_and_says_no_boundary_moved(self):
        self.assertEqual(self.model.count("## Plain navigation (v0.21)"), 1)
        self.assertNotIn(" ## ", self.section[len("## Plain navigation (v0.21)"):])
        for word in ("does not move any boundary", "no route, no key of `config.json`, no data file, no kind of chat event", "`localStorage`", "rule 15b",
                     "Advanced mode is a display and not a permission", "(guard rule 15a)", "(guard rule 15c)", "(guard rule 15d)", "(15e)",
                     "The AI still cannot raise a limit", "Residual risks", "Going back to v0.20.0"):
            self.assertIn(word, self.section, word)

    def test_the_sentences_it_quotes_are_the_pages(self):
        for words in ("允許這一次", "改內容再允許", "拒絕", "技術細節", "保護範圍（沙盒）", "用量與上限"):
            self.assertTrue(words in self.app, words)
            self.assertTrue(words in self.section, words)
        # P50-1: the box under 「想做什麼？跟 CEO 說」 became the greeting 「今天想做什麼？」 (the v0.21 section keeps quoting the old words as that version's)
        self.assertTrue("想做什麼？跟 CEO 說" in self.section)
        self.assertTrue("今天想做什麼？" in self.app)
        self.assertTrue("到設定調高" in self.app)

    def test_the_old_words_are_no_longer_quoted_as_the_page_says_them(self):
        for old in ("可能在沙盒外執行", "VBear 依派工送出"):
            self.assertNotIn(old, self.model, old)
        self.assertIn("可能在保護範圍（沙盒）外執行", self.model)
        self.assertIn("VBear 依分配工作送出", self.model)

    def test_the_section_holds_nothing_personal(self):
        self.assertEqual(problems(self.section, "SECURITY-MODEL v0.21"), [])


class ReadmeAndReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = flat(raw("README.md"))
        cls.zh = flat(raw("README.zh-TW.md"))
        cls.ref = flat(raw("docs", "REFERENCE.zh-TW.md"))
        cls.arch = flat(raw("docs", "ARCHITECTURE.md"))
        cls.app = raw("web", "app.js")
        cls.index = raw("web", "index.html")

    def test_both_readmes_describe_the_four_item_menu_and_where_the_limit_is(self):
        for name, text in (("en", self.en), ("zh", self.zh)):
            for word in ("首頁", "員工", "工作", "設定", "進階模式", "用量與上限", "GLOSSARY.md", "指令視窗", "AI 工具的外掛清單", "員工詳細資料"):
                self.assertIn(word, text, (name, word))
        # P50-4 (v0.23): the bar's first item is 新對話 and the three others are a size smaller (the words of the four items are all still in the text above)
        self.assertIn("The bar on the left has 新對話 (back to the box on the home page), 最近 (the employees you talked with lately) and, smaller, 員工, 工作 and 設定", self.en)
        self.assertIn("左邊選單有「新對話」「最近」，以及小一級的「員工」「工作」「設定」", self.zh)

    def test_the_old_menu_sentences_are_gone(self):
        self.assertNotIn("The menu on the left has 冒險者大廳", self.en)
        self.assertNotIn("左邊選單有「冒險者大廳」", self.zh)
        self.assertNotIn("any time from 「開始設定」 in the left menu", self.en)
        self.assertNotIn("之後隨時可以從左邊選單的「開始設定」", self.zh)

    def test_the_start_up_page_and_the_daily_limit_are_said_as_the_page_says_them(self):
        for text in (self.en, self.zh):
            self.assertIn("每天最多花 US$3（預設，可以不用動）", text)
        for part in ("每天最多花 ${", "（預設，可以不用動）", "之後可以在『設定』的『用量與上限』改"):
            self.assertTrue(part in self.app, part)
        self.assertIn("US$0.01 to US$50", self.en)
        self.assertIn("US$0.01 到 US$50", self.zh)

    def test_the_reference_has_rows_for_the_new_pages_and_the_folded_limit(self):
        for word in ("| 首頁（v0.21 起；以前叫冒險者大廳）", "| 員工 | `#/employees`", "| 工作 | `#/work`", "用量與上限", "`#/settings?open=limits`", "進階模式的開關只管顯示",
                     "不改變任何權限", "保護範圍（沙盒）外警告"):
            self.assertIn(word, self.ref, word)
        self.assertTrue('href="#/employees"' in self.index)
        self.assertTrue('href="#/work"' in self.index)

    def test_the_architecture_has_the_section_and_names_things_the_page_has(self):
        self.assertIn("## Plain navigation — `web/index.html`, `web/app.js` (v0.21)", self.arch)
        part = section(self.arch, "## Plain navigation — `web/index.html`, `web/app.js` (v0.21)", "## Easy start 2 — `web/app.js`, `macos/VBear/main.swift`, `vbear/spend_keep.py`, `vbear/first_ceo.py` (v0.22)")
        for name in ("syncAdvancedNav", "NAV_PARENT", "viewHome", "homeWaiting", "homeTeam", "homeToday", "homeAsk", "homeFirstRun", "viewEmployees", "viewWork",
                     "openChatWith", "plainWords", "plainNotice", "limitReachedNotice", "dailyLimitEditor", "chatPrepState", "navPageName", "wireNavMenu"):
            self.assertIn(name, part, name)
            self.assertRegex(self.app, rf"(function|const) {name}\b", f"web/app.js has {name}")
        for rule in ("15a", "15b", "15c", "15d", "15e"):
            self.assertIn(rule, part, rule)
        self.assertEqual(problems(part, "ARCHITECTURE v0.21"), [])

    def test_the_menu_words_the_documents_quote_are_the_pages(self):
        # P50-2: the first item of the menu is 「新對話」 (the page itself, #/, is still called 首頁 in the documents)
        for word in ("新對話", "員工", "工作", "設定", "進階", "指令視窗", "工作台", "流程", "專案資料夾", "AI 工具的外掛清單", "員工詳細資料", "你的 AI 員工"):
            self.assertIn(word, self.index, word)


class RealMachineWalkTests(unittest.TestCase):
    def test_the_script_and_its_test_are_there_and_hold_nothing_personal(self):
        for path in (("tools", "qa_p47.py"), ("tests", "test_qa_p47.py")):
            text = raw(*path)
            self.assertEqual(problems(text, "/".join(path)), [])
        script = raw("tools", "qa_p47.py")
        for word in ("7802", "7788", "7789", "remote-debugging-pipe", "US$0.30", "--no-ai", "--haiku", "--compare"):
            self.assertIn(word, script, word)

    def test_the_documents_name_the_same_caps_as_the_script(self):
        script = raw("tools", "qa_p47.py")
        self.assertIn("CLAUDE_CAP_MAX = 0.30", script)
        self.assertIn("PER_TURN_CLAUDE = 0.03", script)
        self.assertIn("WALL_CAP_S = 20 * 60", script)
        self.assertIn("US$0.30", flat(raw("CHANGELOG.md")))

    def test_no_list_of_private_words_is_kept_in_the_tests_and_the_tests_themselves_are_public(self):
        for name in ("test_p47_docs.py", "test_p46_docs.py", "test_qa_p47.py"):
            text = raw("tests", name)
            self.assertEqual(problems(text, name), [], name)
            self.assertNotRegex(text, r"(?m)^PERSONAL\s*=\s*\[", name)

    def test_a_local_denylist_outside_git_is_read_when_named_and_ignored_otherwise(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "words.txt"
            path.write_text("made-up-word\n\n  another one \n", encoding="utf-8")
            old = os.environ.get("VBEAR_DOCS_DENYLIST")
            os.environ["VBEAR_DOCS_DENYLIST"] = str(path)
            try:
                self.assertEqual(_local_denylist(), ["made-up-word", "another one"])
                os.environ["VBEAR_DOCS_DENYLIST"] = str(Path(d) / "missing.txt")
                self.assertEqual(_local_denylist(), [])
            finally:
                if old is None:
                    os.environ.pop("VBEAR_DOCS_DENYLIST", None)
                else:
                    os.environ["VBEAR_DOCS_DENYLIST"] = old

    def test_the_scan_fires_on_small_made_up_texts(self):
        for text in ("my home is /Users" + "/alice/projects", "mail " + "someone" + "@" + "corp.invalid" + " now", "at /home" + "/bob/x"):
            self.assertTrue(problems(text, "x"), text)
        for text in ("mail a.b@example.com now", "/Users/fake-user/.codex", "plain words"):
            self.assertEqual(problems(text, "x"), [], text)


if __name__ == "__main__":
    unittest.main()
