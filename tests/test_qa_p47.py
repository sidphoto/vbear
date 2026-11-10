"""P47-6: tools/qa_p47.py, the coordinator's before/after walk of five tasks in a headless Chrome, must refuse to run against the person's VBear (its folder,
anything under it, ports 7788 and 7789) or with a Claude cap above US$0.30; count steps, stuck steps and the characters to read the way its docstring
says; say "unable" for what a version cannot do and not call it zero; keep Claude's money under the cap (a step that would pass it is not done); open no
TCP debugging port; use only the standard library; find elements only by data attributes, href, ids and the dialog's classes (never by screen words); print
nothing a model wrote and not the access token; and compare two result files into a table.
Nothing here starts Chrome, a console, a model or a program: the browser page is a small in-memory fake and so is the console (the real page is walked by
the coordinator, and the words of the cards by tests/frontend/p47_chat.cjs). Everything here is made up.

Seams: ``refusal``, ``frame`` / ``unframe``, ``chrome_args``, ``screens_to_scroll``, ``bad_words``, ``judge_step``, ``summarize``, ``claude_spent`` /
``claude_allowed``, ``slice_const`` / ``read_tables``, ``compare_table`` / ``compare``, ``Walker`` (over a fake page), ``Run.play`` / ``Run.money_ok``
(over a fake page and console) and ``main`` (the command line, with those fakes)."""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "tools" / "qa_p47.py"
SPEC = importlib.util.spec_from_file_location("qa_p47", SOURCE)
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

TOKEN = "synthetic-token-never-printed"
MODEL_WORDS = "MODEL-WORDS-never-printed"


# ---- fakes ------------------------------------------------------------------------------------------------------------------------------

class FakePage:
    """A page that is a table: route -> {selector: info}. A click on a selector goes where ``links`` says. Scrolling moves everything up by 810."""

    def __init__(self, pages, links, on_click=None, route="#/"):
        self.pages, self.links, self.on_click = pages, links, on_click or {}
        self.where, self.offset, self.log = route, 0, []
        self.size = qa.DESKTOP

    def _el(self, sel):
        return (self.pages.get(self.where) or {}).get(sel)

    def viewport(self, w, h):
        self.size = (w, h)

    def open(self, url):
        self.log.append(("open", "token" if "#auth=" in url else url))

    def goto(self, hash_):
        self.where, self.offset = hash_, 0
        self.log.append(("goto", hash_))

    def route(self):
        return self.where

    def has(self, sel):
        return self._el(sel) is not None

    def find(self, sel):
        e = self._el(sel)
        if e is None:
            return {"found": False}
        top = e.get("top", 100) - self.offset
        return {"found": True, "shown": e.get("shown", True), "top": top, "docTop": e.get("top", 100), "height": e.get("height", 30),
                "disabled": e.get("disabled", False), "vh": self.size[1], "sy": self.offset}

    def click(self, sel):
        self.log.append(("click", sel))
        if sel in self.on_click:
            self.on_click[sel]()
        dest = self.links.get((self.where, sel))
        if dest:
            if dest != self.where:
                self.offset = 0
            self.where = dest
        return True

    def fill(self, sel, value):
        self.log.append(("fill", sel, value))
        return self._el(sel) is not None

    def scroll(self, sel=None):
        room = (self.pages.get(self.where) or {}).get("_height", 900) - self.size[1]
        if self.offset >= room:
            return False
        self.offset = min(room, self.offset + 810)
        self.log.append(("scroll", sel))
        return True

    def into_view(self, sel):
        self.offset = max(0, (self._el(sel) or {}).get("top", 0) - 400)

    def to_top(self):
        self.offset = 0

    def at_bottom(self):
        return self.offset >= (self.pages.get(self.where) or {}).get("_height", 900) - self.size[1]

    def main_text(self):
        return (self.pages.get(self.where) or {}).get("_text", "")

    def read_above(self, sel):
        return (self._el(sel) or {}).get("read", 0)

    def checked(self, sel):
        e = self._el(sel)
        return None if e is None else e.get("checked", False)

    def text_of(self, sel):
        return (self._el(sel) or {}).get("text", "")

    def box_top(self, sel):
        return (self._el(sel) or {}).get("top")

    def settle(self, *a, **k):
        pass

    def shot(self, path):
        Path(path).write_bytes(b"png")


class FakeConsole(qa.Console):
    def __init__(self, ledger="0", daily=3.0, profiles=None, token=TOKEN):
        super().__init__(7802, token)
        self.ledger_value, self.daily, self.profiles = ledger, daily, list(profiles or [])
        self.per_turn, self.routines, self.log = 0.25, [], []
        self.verified = False

    def call(self, path, method="GET", body=None):
        self.log.append((method, path.split("?")[0], body))
        clean = path.split("?")[0]
        if (method, clean) == ("GET", "/api/meetings/ledger"):
            return 200, {"spent_usd": self.ledger_value, "daily_usd": str(self.daily)}
        if (method, clean) == ("GET", "/api/config"):
            return 200, {"config": {"chat_limits": {"per_turn_usd": self.per_turn}}}
        if (method, clean) == ("POST", "/api/config"):
            if isinstance(body, dict) and "chat_limits" in body:
                self.per_turn = body["chat_limits"]["per_turn_usd"]
            return 200, {"ok": True}
        if (method, clean) == ("POST", "/api/setup/daily-limit"):
            self.daily = body["daily_usd"]
            return 200, {"ok": True, "daily_usd": self.daily, "changed": []}
        if (method, clean) == ("GET", "/api/agent-profiles"):
            return 200, {"profiles": [dict(p) for p in self.profiles]}
        if (method, clean) == ("POST", "/api/agent-profiles"):
            pid = f"prof-{len(self.profiles) + 1:012x}"
            self.profiles.append({"id": pid, "name": body["name"], "model": body["model"]})
            return 200, {"ok": True, "profile": {"id": pid}}
        if clean.startswith("/api/agent-profiles/") and clean.endswith("/delete"):
            self.profiles = [p for p in self.profiles if p["id"] != clean.split("/")[3]]
            return 200, {"ok": True}
        if (method, clean) == ("GET", "/api/routines"):
            return 200, {"routines": [dict(r) for r in self.routines]}
        if clean.startswith("/api/routines/") and clean.endswith("/delete"):
            self.routines = [r for r in self.routines if r["id"] != clean.split("/")[3]]
            return 200, {"ok": True}
        if (method, clean) == ("GET", "/api/chats"):
            return 200, {"chats": []}
        if (method, clean) == ("GET", "/api/chat-support"):
            return 200, {"support": {"state": "verified" if self.verified else "unverified"}}
        if (method, clean) == ("POST", "/api/chat-support/verify"):
            self.verified = True
            return 202, {"ok": True}
        return 404, None


def after_site():
    """The v0.21 page as a table, enough for the paths of the four tasks that need no model."""
    nav = {qa.NAV_SETTINGS: {"top": 200}, '[data-nav="work"]': {"top": 160}, '[data-nav="employees"]': {"top": 120}}
    pages = {
        "#/": {**nav, "_text": "首頁 等你決定"},
        "#/settings": {**nav, qa.LIMITS_SUMMARY: {"top": 1400, "read": 900}, "_height": 2200, "_text": "設定"},
        "#/settings#open": {**nav, qa.LIMITS_SUMMARY: {"top": 1400}, '[data-limit-choice="custom"]': {"top": 1500, "read": 1000},
                            "[data-limit-input]": {"top": 1560}, "[data-limit-save]": {"top": 1600}, '[data-limit-current]': {"top": 1450, "text": "US$3"},
                            "_height": 2200, "_text": "設定 用量與上限"},
        "#/work": {**nav, '[data-work="routines"]': {"top": 250}, "_text": "工作"},
        "#/routines": {**nav, '[data-routine-action="new"]': {"top": 400}, "_text": "定時工作"},
        "#/routines#form": {**nav, '[data-routine-field="name"]': {"top": 200}, '[data-routine-field="text"]': {"top": 300},
                            '[data-routine-field="enabled"]': {"top": 350, "checked": True},
                            **{sel: {"top": 400, "checked": True} for sel in qa.ROUTINE_DAYS},
                            '[data-routine-action="save"]': {"top": 500}, "_text": "新增定時工作"},
    }
    links = {("#/", qa.NAV_SETTINGS): "#/settings", ("#/settings", qa.LIMITS_SUMMARY): "#/settings#open",
             ("#/settings#open", qa.LIMITS_SUMMARY): "#/settings", ("#/settings#open", '[data-limit-choice="custom"]'): "#/settings#open",
             ("#/", '[data-nav="work"]'): "#/work", ("#/work", '[data-work="routines"]'): "#/routines",
             ("#/routines", '[data-routine-action="new"]'): "#/routines#form", ("#/routines#form", '[data-routine-action="save"]'): "#/routines"}
    return pages, links


class FakeClock:
    """Time that moves only when it is looked at, so that waiting for something that is not there takes no real time."""

    def __init__(self, step=0.5):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


def make_state(root: Path, name: str = "b") -> Path:
    state = root / name
    state.mkdir()
    (state / "server.token").write_text(json.dumps({"port": 7802, "token": TOKEN}))
    return state


# ---- the pure helpers -------------------------------------------------------------------------------------------------------------------

class FramingTests(unittest.TestCase):
    def test_a_message_is_json_ended_by_a_nul_byte_and_comes_back_whole(self):
        raw = qa.frame({"id": 1, "method": "Page.enable", "params": {}})
        self.assertTrue(raw.endswith(b"\0"))
        self.assertEqual(raw.count(b"\0"), 1)
        msgs, rest = qa.unframe(raw)
        self.assertEqual(msgs, [{"id": 1, "method": "Page.enable", "params": {}}])
        self.assertEqual(rest, b"")

    def test_several_messages_and_a_half_one_are_split_and_the_half_is_kept(self):
        data = qa.frame({"id": 1}) + qa.frame({"id": 2, "result": {"x": "字"}}) + b'{"id": 3, "res'
        msgs, rest = qa.unframe(data)
        self.assertEqual([m["id"] for m in msgs], [1, 2])
        self.assertEqual(msgs[1]["result"]["x"], "字")
        self.assertEqual(rest, b'{"id": 3, "res')
        msgs2, rest2 = qa.unframe(rest + b'ult": {}}\0')
        self.assertEqual(msgs2, [{"id": 3, "result": {}}])
        self.assertEqual(rest2, b"")

    def test_a_part_that_is_not_json_or_not_an_object_is_dropped(self):
        msgs, rest = qa.unframe(b"garbage\0" + qa.frame({"id": 7}) + b"[1,2]\0\xff\xfe\0")
        self.assertEqual(msgs, [{"id": 7}])
        self.assertEqual(rest, b"")

    def test_the_browser_is_started_with_the_pipe_its_own_profile_and_no_tcp_port(self):
        args = qa.chrome_args("/x/Chrome", "/tmp/p")
        self.assertEqual(args[0], "/x/Chrome")
        for flag in ("--headless=new", "--use-mock-keychain", "--password-store=basic", "--no-first-run", "--no-default-browser-check", "--disable-sync",
                     "--remote-debugging-pipe", "--user-data-dir=/tmp/p"):
            self.assertIn(flag, args)
        self.assertFalse([a for a in args if "remote-debugging-port" in a])


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.chrome = self.root / "chrome"
        self.chrome.write_text("x")
        self.state = self.root / "s"
        self.state.mkdir()

    def why(self, **kw):
        args = {"state": str(self.state), "port": 7802, "cap": 0.30, "label": "before", "home": self.root, "chrome": str(self.chrome)}
        args.update(kw)
        return qa.refusal(args["state"], args["port"], args["cap"], args["label"], args["home"], args["chrome"])

    def test_a_good_call_is_not_refused(self):
        self.assertIsNone(self.why())

    def test_the_persons_own_ports_are_refused(self):
        for port in (7788, 7789):
            self.assertIn("own VBear", self.why(port=port))
        for port in (80, 1023, 70000, True):
            self.assertIn("port", self.why(port=port))

    def test_the_persons_own_folder_and_anything_under_it_is_refused(self):
        own = self.root / ".vbear"
        (own / "deep").mkdir(parents=True)
        self.assertIn("own VBear folder", self.why(state=str(own)))
        self.assertIn("own VBear folder", self.why(state=str(own / "deep")))
        link = self.root / "link"
        link.symlink_to(own)
        self.assertIn("own VBear folder", self.why(state=str(link)))

    def test_a_cap_above_thirty_cents_or_not_above_zero_is_refused(self):
        for cap in (0.31, 1, 0, -0.1, True, "0.3"):
            self.assertIn("claude-cap", self.why(cap=cap))
        self.assertIsNone(self.why(cap=0.05))

    def test_the_label_the_state_folder_and_the_chrome_have_to_be_real(self):
        self.assertIn("label", self.why(label="later"))
        self.assertIn("does not exist", self.why(state=str(self.root / "nope")))
        self.assertIn("Chrome", self.why(chrome=str(self.root / "no-chrome")))


class CountingTests(unittest.TestCase):
    def test_a_target_in_the_first_screen_needs_no_scroll_and_each_further_screen_one(self):
        self.assertEqual(qa.screens_to_scroll(100, 40, 900), 0)
        self.assertEqual(qa.screens_to_scroll(850, 40, 900), 0)           # its first 48 pixels end at 898
        self.assertEqual(qa.screens_to_scroll(900, 40, 900), 1)
        self.assertEqual(qa.screens_to_scroll(1700, 40, 900), 2)
        self.assertEqual(qa.screens_to_scroll(2800, 10, 844), 3)          # 2810 - 844 = 1966 over 759.6 per scroll
        self.assertEqual(qa.screens_to_scroll(880, 10, 900), 0)           # a short thing counts by its own height
        with self.assertRaises(ValueError):
            qa.screens_to_scroll(1, 1, 0)

    def test_characters_to_read_are_the_ones_that_are_not_white_space(self):
        self.assertEqual(qa.count_chars("a b\n字 字\t"), 4)
        self.assertEqual(qa.count_chars(""), 0)

    def test_words_of_the_table_are_found_and_a_longer_english_word_is_not(self):
        avoid = ["角色卡", "Edit", "Read", "Agent CLI"]
        self.assertEqual(qa.bad_words("新增一張角色卡", avoid, []), ["角色卡"])
        self.assertEqual(qa.bad_words("修改檔案（Edit）", avoid, []), ["Edit"])
        self.assertEqual(qa.bad_words("Edited the Readme, then Reads", avoid, []), [])
        self.assertEqual(qa.bad_words("Agent CLI 版本檢查", avoid, []), ["Agent CLI"])
        self.assertEqual(qa.bad_words("", avoid, []), [])
        self.assertEqual(qa.bad_words("x", ["", None, 3], []), [])

    def test_a_known_server_sentence_shown_as_it_came_is_found_by_its_pattern(self):
        errors = [r"今天的額度已用完（亮紅燈）", r"VBear runtime 未連線"]
        self.assertEqual(qa.bad_words("今天的額度已用完（亮紅燈），不能再送", [], errors), ["error:0"])
        self.assertEqual(qa.bad_words("a VBear runtime 未連線 b", [], errors), ["error:1"])
        self.assertEqual(qa.bad_words("今天的用量到你設的上限了", [], errors), [])
        self.assertEqual(qa.bad_words("x", [], ["(unclosed"]), [])        # a pattern that does not compile is skipped, not fatal

    def test_a_step_is_stuck_for_more_than_one_screen_of_scrolling_a_bad_word_or_looking_elsewhere(self):
        self.assertEqual(qa.judge_step({"scrolls": 0, "bad": [], "elsewhere": False}), [])
        self.assertEqual(qa.judge_step({"scrolls": 1}), [])
        self.assertEqual(qa.judge_step({"scrolls": 2}), ["scrolled"])
        self.assertEqual(qa.judge_step({"bad": ["派工"]}), ["words"])
        self.assertEqual(qa.judge_step({"elsewhere": True}), ["elsewhere"])
        self.assertEqual(qa.judge_step({"scrolls": 3, "bad": ["x"], "elsewhere": True}), ["scrolled", "words", "elsewhere"])

    def test_a_tasks_numbers_come_from_its_steps(self):
        steps = [{"kind": "press", "scrolls": 0, "stuck": [], "read": 10, "bad": []},
                 {"kind": "fill", "scrolls": 2, "stuck": ["scrolled", "words"], "read": 300, "bad": ["派工"]},
                 {"kind": "look", "scrolls": 1, "stuck": [], "read": None, "bad": []}]
        got = qa.summarize(steps)
        self.assertEqual((got["steps"], got["stuck"], got["read"], got["bad"], got["done"], got["unable"]), (6, 1, 310, ["派工"], True, None))
        gone = qa.summarize(steps[:1], "no field")
        self.assertEqual((gone["steps"], gone["unable"], gone["done"]), (1, "no field", False))
        self.assertEqual(qa.summarize([])["steps"], 0)
        self.assertIsNone(qa.summarize([])["read"])


class MoneyTests(unittest.TestCase):
    def test_what_claude_has_cost_is_both_ledgers_plus_five_cents_for_each_chat_check(self):
        self.assertAlmostEqual(qa.claude_spent(["0.02", "0.01"], 2), 0.13)
        self.assertAlmostEqual(qa.claude_spent([0, 0], 0), 0.0)
        self.assertIsNone(qa.claude_spent(["0.02", None], 1))
        self.assertIsNone(qa.claude_spent(["x"], 1))
        self.assertIsNone(qa.claude_spent([-1], 1))

    def test_a_step_that_would_pass_the_cap_is_not_allowed_and_unknown_is_no(self):
        self.assertTrue(qa.claude_allowed(0.10, 0.03, 0.30))
        self.assertTrue(qa.claude_allowed(0.27, 0.03, 0.30))               # exactly the cap is allowed
        self.assertFalse(qa.claude_allowed(0.28, 0.03, 0.30))
        self.assertFalse(qa.claude_allowed(None, 0.0, 0.30))

    def test_the_cap_constants_are_the_rule(self):
        self.assertEqual(qa.CLAUDE_CAP_MAX, 0.30)
        self.assertEqual(qa.PER_TURN_CLAUDE, 0.03)
        self.assertEqual(qa.CHAT_CHECK_RESERVE, 0.05)
        self.assertEqual(qa.DEFAULT_PORT, 7802)
        self.assertEqual(qa.FORBIDDEN_PORTS, (7788, 7789))


class TablesTests(unittest.TestCase):
    SOURCE = "\n".join(["// head", "const WORDS = {",
                        '  a: { use: "員工", avoid: ["角色卡"], scope: "all" },',
                        '  b: { use: "x", avoid: ["終端機"], scope: "title" },',
                        '  c: { use: "y", avoid: ["Edit"], scope: "all" },',
                        "};", "const OTHER = 1;", "const PLAIN_ERRORS = [", "  { re: /額度用完/ },", "  { re: /Errno 2/ },", "];", "// tail"])

    def test_a_const_statement_is_cut_out_by_its_first_and_closing_line(self):
        got = qa.slice_const(self.SOURCE, "WORDS")
        self.assertTrue(got.startswith("const WORDS = {") and got.endswith("};"))
        self.assertNotIn("OTHER", got)
        self.assertIsNone(qa.slice_const(self.SOURCE, "NOPE"))
        self.assertIsNone(qa.slice_const("const WORDS = {\nnever closed", "WORDS"))

    def test_the_tables_are_read_by_node_from_the_two_statements_only(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        tmp = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, tmp, True)
        app = tmp / "app.js"
        app.write_text(self.SOURCE + "\nthrow new Error('the rest of the file must not run');\n", encoding="utf-8")
        got = qa.read_tables(app)
        self.assertEqual(got, {"avoid": ["角色卡", "Edit"], "errors": ["額度用完", "Errno 2"]})

    def test_a_file_without_the_tables_or_a_node_that_fails_gives_no_words_and_says_why(self):
        tmp = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, tmp, True)
        app = tmp / "app.js"
        app.write_text("const x = 1;\n", encoding="utf-8")
        got = qa.read_tables(app)
        self.assertEqual((got["avoid"], got["errors"]), ([], []))
        self.assertIn("not found", got["why"])
        self.assertIn("could not be read", qa.read_tables(tmp / "missing.js")["why"])
        app.write_text(self.SOURCE, encoding="utf-8")

        def broken(*a, **k):
            raise subprocess.TimeoutExpired("node", 30)
        self.assertIn("node", qa.read_tables(app, run=broken)["why"])

        class Done:
            stdout = "not json"
        self.assertIn("node", qa.read_tables(app, run=lambda *a, **k: Done())["why"])

    def test_the_real_tables_of_the_page_are_found_in_the_real_file(self):
        app = SOURCE.parent.parent / "web" / "app.js"
        text = app.read_text(encoding="utf-8")
        for name in ("WORDS", "PLAIN_ERRORS"):
            self.assertIsNotNone(qa.slice_const(text, name), name)


class CompareTests(unittest.TestCase):
    def result(self, label, steps, stuck=0, unable=None, read=100, px=None):
        tasks = {name: {"steps": steps, "stuck": stuck, "unable": None, "read": read, "bad": [], "done": True} for name in qa.TASKS}
        if unable:
            tasks["limit"] = {"steps": 3, "stuck": 1, "unable": unable, "read": 50, "bad": [], "done": False}
        return {"label": label, "mode": "no-ai", "ui": "x", "tasks": tasks, "phone": {"chat_input_px": px}, "money": {"ledger_end": 0.0}, "shots": []}

    def test_the_table_has_a_row_for_each_task_with_both_versions_and_the_differences(self):
        before, after = self.result("before", 8, 2, "no field", px=1700), self.result("after", 5, 0, px=300)
        table = qa.compare_table(before, after)
        for name in qa.TASKS:
            self.assertRegex(table, rf"(?m)^{name}\b")
        self.assertRegex(table, r"(?m)^routine\s+8\s+5\s+-3\s+2\s+0\s+-2\s+100\s+100\s+\+0")
        self.assertRegex(table, r"(?m)^limit\s+unable\s+5\s+-\s")
        self.assertIn("limit (before): unable - no field", table)
        self.assertIn("(before): 1700 px", table)
        self.assertIn("(after): 300 px", table)
        self.assertTrue(table.endswith("yes"))

    def test_an_unable_task_is_shown_as_unable_and_not_as_zero_steps(self):
        table = qa.compare_table(self.result("before", 4, unable="x"), self.result("after", 4))
        self.assertNotRegex(table, r"(?m)^limit\s+0\b")

    def test_a_task_that_got_worse_is_named_and_makes_the_exit_code_one(self):
        tmp = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, tmp, True)
        a, b = tmp / "a.json", tmp / "b.json"
        a.write_text(json.dumps(self.result("before", 4)))
        worse = self.result("after", 4)
        worse["tasks"]["routine"]["steps"] = 9
        b.write_text(json.dumps(worse))
        lines = []
        self.assertEqual(qa.compare(a, b, lines.append), 1)
        self.assertIn("NO - routine", lines[-1])
        b.write_text(json.dumps(self.result("after", 4)))
        lines.clear()
        self.assertEqual(qa.compare(a, b, lines.append), 0)

    def test_files_that_are_missing_in_the_wrong_order_or_the_wrong_shape_are_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, tmp, True)
        a, b = tmp / "a.json", tmp / "b.json"
        a.write_text(json.dumps(self.result("before", 4)))
        b.write_text(json.dumps(self.result("after", 4)))
        lines = []
        self.assertEqual(qa.compare(a, tmp / "none.json", lines.append), 2)
        self.assertEqual(qa.compare(b, a, lines.append), 2)
        self.assertIn("before file first", lines[-1])
        b.write_text(json.dumps({"label": "after", "tasks": {"first": {}}}))
        self.assertEqual(qa.compare(a, b, lines.append), 2)
        b.write_text("not json")
        self.assertEqual(qa.compare(a, b, lines.append), 2)
        self.assertFalse(qa.result_ok(None))
        self.assertFalse(qa.result_ok({"label": "later", "tasks": {}}))


# ---- the walk, over a fake page ------------------------------------------------------------------------------------------------------

class WalkerTests(unittest.TestCase):
    def walker(self, pages, links, tables=None, on_click=None):
        page = FakePage(pages, links, on_click)
        return qa.Walker(page, tables or {"avoid": ["派工"], "errors": []}, sleep=lambda s: None, clock=FakeClock()), page

    def test_a_press_in_the_first_screen_is_one_step_with_no_scroll_and_it_clicks(self):
        w, page = self.walker({"#/": {"[a]": {"top": 100, "read": 40}, "_text": "plain"}}, {("#/", "[a]"): "#/next"})
        w.begin("#/")
        step = w.press("[a]")
        self.assertEqual((step["scrolls"], step["read"], step["stuck"], step["bad"]), (0, 40, [], []))
        self.assertEqual(page.route(), "#/next")
        self.assertEqual(w.summary()["steps"], 1)

    def test_a_press_below_the_fold_counts_each_screen_scrolled_and_is_stuck_after_two(self):
        w, page = self.walker({"#/": {"[a]": {"top": 2000}, "_height": 3000, "_text": "plain"}}, {})
        w.begin("#/")
        step = w.press("[a]")
        self.assertEqual(step["scrolls"], 2)
        self.assertEqual(step["stuck"], ["scrolled"])
        self.assertEqual(w.summary()["steps"], 3)

    def test_a_page_with_a_word_to_avoid_makes_the_step_stuck_and_names_the_word(self):
        w, page = self.walker({"#/": {"[a]": {"top": 100}, "_text": "請派工給員工"}}, {})
        w.begin("#/")
        step = w.press("[a]")
        self.assertEqual((step["stuck"], step["bad"]), (["words"], ["派工"]))

    def test_a_thing_that_is_not_on_the_page_is_not_pressed_and_is_not_recorded(self):
        w, page = self.walker({"#/": {"_text": ""}}, {})
        w.begin("#/")
        self.assertIsNone(w.press("[a]"))
        self.assertIsNone(w.fill("[a]", "x"))
        self.assertEqual(w.steps, [])
        self.assertNotIn(("click", "[a]"), page.log)

    def test_a_switched_off_button_is_reported_as_such_and_not_clicked(self):
        w, page = self.walker({"#/": {"[a]": {"top": 100, "disabled": True}}}, {})
        w.begin("#/")
        self.assertEqual(w.press("[a]"), {"disabled": True, "target": "[a]"})
        self.assertNotIn(("click", "[a]"), page.log)

    def test_a_search_that_finds_nothing_scrolls_the_whole_page_and_counts_as_looking_elsewhere(self):
        w, page = self.walker({"#/": {"_height": 2400, "_text": "plain"}}, {})
        w.begin("#/")
        step, found = w.search("[nope]")
        self.assertFalse(found)
        self.assertEqual(step["kind"], "search")
        self.assertEqual(step["scrolls"], 2)
        self.assertIn("elsewhere", step["stuck"])

    def test_a_search_that_does_find_it_is_only_a_look(self):
        w, page = self.walker({"#/": {"[a]": {"top": 100}, "_text": "plain"}}, {})
        w.begin("#/")
        step, found = w.search("[a]")
        self.assertTrue(found)
        self.assertEqual((step["kind"], step["stuck"]), ("look", []))

    def test_a_look_takes_the_first_of_several_and_presses_nothing(self):
        w, page = self.walker({"#/": {"[b]": {"top": 100, "read": 7}, "_text": "plain"}}, {})
        w.begin("#/")
        step, sel = w.look(["[a]", "[b]"])
        self.assertEqual((sel, step["read"]), ("[b]", 7))
        self.assertFalse([e for e in page.log if e[0] == "click"])
        self.assertEqual(w.look(["[x]"], ), (None, None))

    def test_a_box_already_ticked_costs_no_press_and_one_not_ticked_costs_one(self):
        pages = {"#/": {"[on]": {"top": 100, "checked": True}, "[off]": {"top": 120, "checked": False}, "_text": "plain"}}
        w, page = self.walker(pages, {})
        w.begin("#/")
        w.ensure("[on]")
        self.assertEqual(w.summary()["steps"], 0)
        w.ensure("[off]")
        self.assertEqual(w.summary()["steps"], 1)
        self.assertIn(("click", "[off]"), page.log)
        self.assertNotIn(("click", "[on]"), page.log)
        self.assertIsNone(w.ensure("[missing]"))

    def test_after_a_press_that_changes_the_route_the_next_page_starts_at_the_top(self):
        pages = {"#/": {"[a]": {"top": 1500}, "_height": 3000, "_text": "x"}, "#/next": {"[b]": {"top": 100}, "_text": "y"}}
        w, page = self.walker(pages, {("#/", "[a]"): "#/next"})
        w.begin("#/")
        w.press("[a]")
        self.assertEqual(page.offset, 0)
        self.assertEqual(w.press("[b]")["scrolls"], 0)

    def test_a_target_scrolled_past_above_the_screen_is_brought_back_with_one_scroll(self):
        w, page = self.walker({"#/": {"[a]": {"top": 100}, "_text": "x"}}, {})
        w.begin("#/")
        page.offset = 600
        self.assertEqual(w.press("[a]")["scrolls"], 1)


# ---- the run, over a fake page and console -------------------------------------------------------------------------------------------

class RunTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = make_state(self.root)
        self.lines = []

    def run_for(self, label="after", haiku=False, console=None, page=None, cap=0.30):
        pages, links = after_site()
        page = page or FakePage(pages, links)
        console = console or FakeConsole()
        check = qa.Check(self.lines.append)
        walker = qa.Walker(page, {"avoid": [], "errors": []}, clock=FakeClock(), sleep=lambda s: None)
        run = qa.Run(console, page, walker, self.state, label, haiku, cap, check, self.root, clock=FakeClock(), sleep=lambda s: None)
        run.orig = {"daily": 3.0, "per_turn": 0.25, "profiles": set(), "routines": set()}
        return run, page, console

    def test_a_press_that_is_not_on_the_page_makes_the_task_unable_with_our_own_sentence(self):
        run, page, console = self.run_for()
        run.w.begin("#/")
        pages, links = after_site()
        del page.pages["#/"][qa.NAV_SETTINGS]
        with self.assertRaises(qa.Unable) as ctx:
            run.play("limit")
        self.assertIn(qa.NAV_SETTINGS, str(ctx.exception))

    def test_without_a_model_the_steps_that_send_something_are_not_played(self):
        run, page, console = self.run_for(haiku=False)
        page.pages["#/chat/c1"] = {qa.CHAT_INPUT: {"top": 100}, qa.SEND: {"top": 140}, "_text": "chat"}
        run.chat = "c1"
        run.play("card")
        self.assertEqual(run.tasks["card"]["steps"], 0)
        self.assertFalse([e for e in page.log if e[0] in ("fill", "click")])
        self.assertFalse([c for c in console.log if c[1] == "/api/chat-support/verify"])

    def test_a_card_task_without_a_model_is_unable_and_says_why(self):
        run, page, console = self.run_for(haiku=False)
        with self.assertRaises(qa.Unable) as ctx:
            run.task_card()
        self.assertIn("--haiku", str(ctx.exception))

    def test_a_task_that_starts_in_a_chat_has_nowhere_to_start_when_there_is_none(self):
        run, page, console = self.run_for(haiku=True)
        run.chat = None
        with self.assertRaises(qa.Unable):
            run.play("card")

    def test_the_money_check_adds_both_ledgers_and_the_chat_checks_and_the_steps_own_limit(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.10"))
        run.other = {"mode": "haiku", "money": {"ledger_end": 0.05}}
        self.assertAlmostEqual(0.10 + 0.05 + 0.05 + 0.05, qa.claude_spent([0.10, 0.05], 2))
        self.assertTrue(run.money_ok(0.03))                                  # 0.25 + 0.03 is under 0.30
        run.other = {"mode": "haiku", "money": {"ledger_end": 0.10}}
        self.assertFalse(run.money_ok(0.03))                                 # 0.30 + 0.03 is over it
        run.cap = 0.05
        run.other = None
        self.assertFalse(run.money_ok(0.03))

    def test_a_ledger_that_cannot_be_read_is_never_a_yes(self):
        class Silent(FakeConsole):
            def call(self, path, method="GET", body=None):
                return (0, None) if path == "/api/meetings/ledger" else super().call(path, method, body)
        run, page, console = self.run_for(haiku=True, console=Silent())
        self.assertFalse(run.money_ok(0.0))

    def test_a_step_that_spends_is_not_done_when_it_would_pass_the_cap_and_a_FAIL_is_printed(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.30"))
        run.chat = "c1"
        page.pages["#/chat/c1"] = {qa.CHAT_INPUT: {"top": 100}, qa.SEND: {"top": 140}, "_text": "chat"}
        with self.assertRaises(qa.Unable):
            run.play("card")
        self.assertTrue([line for line in self.lines if line.startswith("FAIL")])
        self.assertFalse([e for e in page.log if e[0] in ("fill", "click")])

    def test_the_chat_check_is_not_run_when_it_would_pass_the_cap(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.28"))
        with self.assertRaises(qa.Stop):
            run.verify_chat()
        self.assertFalse([c for c in console.log if c[1] == "/api/chat-support/verify"])

    def test_the_chat_check_runs_once_when_the_money_allows_it(self):
        run, page, console = self.run_for(haiku=True)
        run.verify_chat()
        self.assertEqual([c for c in console.log if c[1] == "/api/chat-support/verify"], [("POST", "/api/chat-support/verify", {"engine": "claude"})])

    def test_an_address_is_written_down_without_an_id(self):
        self.assertEqual(qa.page_head("#/chat/c-0123456789abcdef"), "#/chat")
        self.assertEqual(qa.page_head("#/chat?profile=prof-1"), "#/chat")
        self.assertEqual(qa.page_head("#/settings?open=limits"), "#/settings")
        self.assertEqual(qa.page_head("#/"), "#/")
        self.assertEqual(qa.page_head(""), "#/")


class MainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.chrome = self.root / "chrome"
        self.chrome.write_text("x")
        self.state = make_state(self.root)
        self.lines = []
        self.pages, self.links = after_site()
        self.page = FakePage(self.pages, self.links, on_click={'[data-routine-action="save"]': self.saved, "[data-limit-save]": self.limit_saved})
        self.console = FakeConsole()
        self.closed = []

    def limit_saved(self):
        self.console.daily = 5.0

    def saved(self):
        self.console.routines.append({"id": "r-1", "name": "QA47 虛構早安", "enabled": True, "days": list(range(7)), "times": ["08:00"]})

    def go(self, *extra, label="after", console=None):
        class Browser:
            def __init__(inner, chrome, profile):
                inner.profile = profile

            def close(inner):
                self.closed.append(str(inner.profile))
        app = self.root / "app.js"
        app.write_text("const WORDS = {\n  a: { avoid: [\"派工\"], scope: \"all\" },\n};\nconst PLAIN_ERRORS = [\n  { re: /額度用完/ },\n];\n", encoding="utf-8")
        return qa.main(["--state", str(self.state), "--label", label, "--chrome", str(self.chrome), *extra], out=self.lines.append,
                       console_factory=lambda port, token: console or self.console, browser_factory=Browser, page_factory=lambda b, base: self.page,
                       sleep=lambda s: None, clock=FakeClock(), home=self.root, app_js=app)

    def test_ports_of_the_persons_own_vbear_and_a_cap_over_thirty_cents_are_refused_before_anything_starts(self):
        for extra in (("--port", "7788"), ("--port", "7789"), ("--claude-cap", "0.31")):
            self.lines.clear()
            self.assertEqual(self.go(*extra), 2, extra)
            self.assertTrue(self.lines[0].startswith("refused:"), extra)
        self.assertEqual(self.closed, [])
        self.assertEqual(self.page.log, [])

    def test_the_persons_own_state_folder_is_refused(self):
        own = self.root / ".vbear"
        own.mkdir()
        self.state = own
        self.assertEqual(self.go(), 2)
        self.assertIn("own VBear folder", self.lines[0])

    def test_the_state_label_and_chrome_are_needed_and_compare_needs_two_files(self):
        self.assertEqual(qa.main([], out=self.lines.append), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                qa.main(["--haiku", "--no-ai"], out=self.lines.append)
            with self.assertRaises(SystemExit):
                qa.main(["--compare", "only-one.json"], out=self.lines.append)

    def test_a_walk_with_no_model_passes_writes_a_result_that_compare_accepts_and_cleans_up(self):
        self.assertEqual(self.go(), 0, "\n".join(self.lines))
        out = self.root / "qa47-after.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(qa.result_ok(data))
        self.assertEqual((data["label"], data["mode"], data["ui"]), ("after", "no-ai", "v0.21"))
        self.assertEqual(data["tasks"]["limit"]["steps"], 7)             # nav, scroll, summary, scroll, choice, fill, save (1400 and 1500 are below the fold)
        self.assertEqual(data["tasks"]["routine"]["steps"], 6)           # two presses, one nav, two fills, the save; the ticked boxes cost nothing
        self.assertTrue(data["tasks"]["first"]["unable"])
        self.assertTrue(data["tasks"]["card"]["unable"])
        self.assertEqual(data["money"]["claude_cap"], 0.30)
        self.assertFalse([c for c in self.console.log if c[1] == "/api/chat-support/verify"])
        self.assertEqual(self.console.profiles, [])                      # the employee it made for the routine is deleted
        self.assertEqual(self.console.routines, [])
        self.assertEqual(self.console.daily, 3.0)                        # the limits are put back
        self.assertEqual(self.console.per_turn, 0.25)
        self.assertEqual(self.closed, [str(self.state.resolve().parent / "chrome-after")])
        self.assertTrue(self.lines[-1].startswith("qa_p47 (after, no-ai): PASS"))

    def test_nothing_a_model_wrote_and_not_the_token_is_printed_or_stored(self):
        self.pages["#/"]["_text"] = MODEL_WORDS
        self.assertEqual(self.go(), 0)
        blob = "\n".join(self.lines) + (self.root / "qa47-after.json").read_text(encoding="utf-8")
        self.assertNotIn(MODEL_WORDS, blob)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(("open", TOKEN), self.page.log)

    def test_a_label_that_does_not_match_the_served_page_stops_the_run_with_a_fail(self):
        self.assertEqual(self.go(label="before"), 1)
        self.assertTrue([line for line in self.lines if line.startswith("FAIL")])
        self.assertFalse((self.root / "qa47-before.json").exists())

    def test_the_result_file_is_written_inside_the_folder_that_holds_the_state_and_nowhere_else(self):
        self.go()
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.startswith("qa47")), ["qa47-after.json"])
        self.assertTrue((self.root / "shots-after").is_dir())


# ---- the file itself -------------------------------------------------------------------------------------------------------------------

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def test_only_the_standard_library_is_imported(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add((node.module or "").split(".")[0])
        stdlib = set(__import__("sys").stdlib_module_names)
        self.assertEqual(sorted(n for n in names if n not in stdlib), [])
        self.assertNotIn("vbear", names)

    def test_no_tcp_debugging_port_and_nothing_in_the_persons_home_but_the_refusal(self):
        self.assertNotIn("remote-debugging-port", self.text.replace("no TCP debugging port", ""))
        self.assertEqual(len(re.findall(r"\.vbear", self.text.replace("~/.vbear", ""))), 1)       # only the refusal builds the persons folder
        for forbidden in ("os.system", "shell=True", "innerHTML", "/Applications/VBear", "pkill", "killall"):
            self.assertNotIn(forbidden, self.text, forbidden)

    def test_every_task_has_a_path_in_both_versions_and_a_blocked_one_for_each_way_of_doing_it(self):
        for label in qa.LABELS:
            paths = qa.PATHS[label]
            for name in ("first", "limit", "routine", "card", "blocked_find", "blocked_sent"):
                self.assertIn(name, paths, f"{label} {name}")
                self.assertGreater(len(paths[name]["steps"]), 0)

    def test_every_selector_is_a_data_attribute_an_href_an_id_or_the_dialog_class_and_no_screen_word(self):
        sels = []
        for label in qa.LABELS:
            for spec in qa.PATHS[label].values():
                for st in spec["steps"]:
                    sels += [st["sel"]] if isinstance(st["sel"], str) else list(st["sel"])
        self.assertGreater(len(sels), 40)
        for sel in sels:
            self.assertFalse(re.search(r"[^\x00-\x7f]", sel), sel)
            self.assertNotIn(":contains", sel)
            self.assertTrue(re.search(r"\[data-[a-z-]+|\[href|#[a-z]|\.modal", sel), sel)

    def test_the_sentences_it_types_and_the_names_it_saves_are_made_up_and_begin_with_qa47(self):
        for text in list(qa.SENTENCES.values()) + [qa.ROUTINE_NAME, qa.ROUTINE_TEXT]:
            self.assertTrue(text.startswith("QA47"), text)
        for label in qa.LABELS:
            for spec in qa.PATHS[label].values():
                for st in spec["steps"]:
                    if st["kind"] == "fill" and "value" in st:
                        self.assertTrue(st["value"].startswith("QA47") or st["value"].isdigit(), st["value"])

    def test_only_the_steps_that_send_something_are_marked_for_a_model(self):
        for label in qa.LABELS:
            for key, spec in qa.PATHS[label].items():
                for st in spec["steps"]:
                    if st.get("ai"):
                        self.assertIn(key, ("first", "card"), f"{label} {key}")

    def test_the_docstring_states_the_money_the_ports_and_the_caps(self):
        doc = qa.__doc__
        for needle in ("7788", "7789", "US$0.30", "--no-ai", "--haiku", "--compare", "20 minutes", "2 minutes", "5 minutes", "remote-debugging-pipe",
                       "standard library only", "unable"):
            self.assertIn(needle, doc, needle)


if __name__ == "__main__":
    unittest.main()
