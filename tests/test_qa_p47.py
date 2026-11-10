"""P47-6: tools/qa_p47.py, the coordinator's before/after walk of five tasks in a headless Chrome, must refuse to run against the person's VBear (its folder,
anything under it, ports 7788 and 7789) or with a Claude cap above US$0.30; count steps, stuck steps and the characters to read the way its docstring
says; say "unable" for what a version cannot do and not call it zero; keep Claude's money under the cap (a step that would pass it is not done); open no
TCP debugging port; use only the standard library; find elements only by data attributes, href, ids and the dialog's classes (never by screen words); print
nothing a model wrote and not the access token; and compare two result files into a table.
Nothing here starts Chrome, a console, a model or a program: the browser page is a small in-memory fake and so is the console (the real page is walked by
the coordinator, and the words of the cards by tests/frontend/p47_chat.cjs). Everything here is made up.

Seams: ``refusal``, ``frame`` / ``unframe``, ``chrome_args``, ``screens_to_scroll``, ``bad_words``, ``judge_step``, ``summarize``, ``claude_spent`` /
``claude_allowed``, ``slice_const`` / ``read_tables``, ``compare_table`` / ``compare``, ``Walker`` (over a fake page), ``Run.play`` / ``Run.money_ok``
(over a fake page and console), ``Browser.allowed_wait`` / ``Browser.close`` (over a fake clock; no Chrome is started) and ``main`` (the command line, with those fakes)."""
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
import threading
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
        self.support_state = None                    # a word to answer instead (None: verified or not by ``verified``); "unreadable": no answer
        self.created_chat = None

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
            if self.support_state == "unreadable":
                return 0, None
            return 200, {"support": {"state": self.support_state or ("verified" if self.verified else "unverified")}}
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

    def test_only_port_7802_may_be_used_every_other_port_is_refused_even_the_ones_kept_for_other_checks(self):
        self.assertIsNone(self.why(port=7802))
        for port in (7795, 7796, 7797, 7798, 7799, 7800, 7801, 7803, 8000, 65535, 1024):
            self.assertIn("only port 7802", self.why(port=port), port)

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
        return {"label": label, "mode": "no-ai", "ui": "x", "tasks": tasks, "phone": {"chat_input_px": px}, "money": {"ledger_end": 0.0}, "shots": [],
                "checks": {"ok": 10, "warn": 0, "fail": 0}}

    def compared(self, before, after):
        tmp = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "a.json").write_text(json.dumps(before))
        (tmp / "b.json").write_text(json.dumps(after))
        lines = []
        code = qa.compare(tmp / "a.json", tmp / "b.json", lines.append)
        return code, lines[-1]

    def test_an_after_task_that_did_not_finish_is_a_failure_even_with_fewer_steps(self):
        after = self.result("after", 4)
        after["tasks"]["first"] = {"steps": 0, "stuck": 0, "unable": None, "read": 0, "bad": [], "done": False, "error": "synthetic stop"}
        after["checks"]["fail"] = 1
        code, last = self.compared(self.result("before", 8, 2), after)
        self.assertEqual(code, 1)
        self.assertIn("NO", last)
        self.assertIn("first: after did not finish", last)
        self.assertNotIn("yes", last)

    def test_an_after_task_that_cannot_be_done_where_before_did_it_is_a_regression(self):
        after = self.result("after", 4, unable="a button went missing")
        code, last = self.compared(self.result("before", 8), after)
        self.assertEqual(code, 1)
        self.assertIn("limit: after cannot do what before did", last)

    def test_a_task_the_before_run_could_not_do_is_not_a_regression_when_after_does_it(self):
        code, last = self.compared(self.result("before", 9, unable="no field"), self.result("after", 9))
        self.assertEqual(code, 0, last)
        self.assertTrue(last.endswith("yes"))

    def test_a_run_with_a_fail_cannot_be_judged_and_a_task_the_before_run_did_not_finish_cannot_be_compared(self):
        bad = self.result("before", 4)
        bad["checks"]["fail"] = 2
        code, last = self.compared(bad, self.result("after", 4))
        self.assertEqual(code, 1)
        self.assertIn("before run has 2 FAIL", last)
        stopped = self.result("before", 4)
        stopped["tasks"]["routine"] = {"steps": 1, "stuck": 0, "unable": None, "read": 1, "bad": [], "done": False, "error": "stopped"}
        code, last = self.compared(stopped, self.result("after", 4))
        self.assertEqual(code, 1)
        self.assertIn("routine: before did not finish", last)

    def test_the_table_says_failed_and_dead_end_where_they_happened(self):
        after = self.result("after", 4)
        after["tasks"]["first"]["dead_end"] = "the chat box was reached, but the chat cannot be used (state policy)"
        after["tasks"]["card"] = {"steps": 0, "stuck": 0, "unable": None, "read": 0, "bad": [], "done": False, "error": "synthetic stop"}
        table = qa.compare_table(self.result("before", 4), after)
        self.assertIn("first (after): dead end - the chat box was reached", table)
        self.assertIn("card (after): did not finish - synthetic stop", table)
        self.assertRegex(table, r"(?m)^card\s+4\s+failed\s+-")

    def test_a_result_file_without_the_count_of_checks_or_a_done_flag_is_not_a_result(self):
        good = self.result("after", 4)
        self.assertTrue(qa.result_ok(good))
        no_checks = dict(good)
        del no_checks["checks"]
        self.assertFalse(qa.result_ok(no_checks))
        no_done = self.result("after", 4)
        del no_done["tasks"]["card"]["done"]
        self.assertFalse(qa.result_ok(no_done))

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


class SlowPage(FakePage):
    """A page whose screen stays empty for ``blank`` looks, as a new state folder's first screen does."""

    def __init__(self, *a, blank=0, **k):
        super().__init__(*a, **k)
        self.blank, self.looks = blank, 0

    def main_text(self):
        self.looks += 1
        return "" if self.looks <= self.blank else super().main_text()


class FirstLoadTests(unittest.TestCase):
    def test_a_task_waits_for_the_screen_to_be_drawn_up_to_thirty_seconds_before_it_looks(self):
        page = SlowPage({"#/": {"[a]": {"top": 100}, "_text": "首頁"}}, {}, blank=25)      # 25 looks of 0.5 s each on the fake clock: about 25 seconds
        w = qa.Walker(page, {"avoid": [], "errors": []}, sleep=lambda s: None, clock=FakeClock())
        w.begin("#/")
        self.assertGreater(page.looks, 25)
        self.assertEqual(w.press("[a]")["scrolls"], 0)
        self.assertEqual(qa.FIRST_LOAD_S, 30.0)

    def test_a_screen_that_never_draws_does_not_hold_the_walk_for_ever_and_nothing_is_judged_on_it(self):
        clock = FakeClock()
        page = SlowPage({"#/": {"_text": "首頁"}}, {}, blank=10 ** 9)
        w = qa.Walker(page, {"avoid": [], "errors": []}, sleep=lambda s: None, clock=clock)
        w.begin("#/")
        self.assertLess(clock.now, 45)
        self.assertEqual(w.steps, [])

    def test_a_dead_end_is_stuck_and_is_not_a_step_of_the_person(self):
        page = FakePage({"#/": {"[a]": {"top": 100}, "_text": "x"}}, {})
        w = qa.Walker(page, {"avoid": [], "errors": []}, sleep=lambda s: None, clock=FakeClock())
        w.begin("#/")
        w.press("[a]")
        w.dead_end("the box cannot be used")
        done = w.summary()
        self.assertEqual((done["steps"], done["stuck"]), (1, 1))
        self.assertEqual(qa.judge_step({"dead_end": True}), ["dead_end"])

    def test_present_looks_without_recording_a_step(self):
        page = FakePage({"#/": {"[a]": {"top": 100}, "_text": "x"}}, {})
        w = qa.Walker(page, {"avoid": [], "errors": []}, sleep=lambda s: None, clock=FakeClock())
        w.begin("#/")
        self.assertTrue(w.present("[a]"))
        self.assertFalse(w.present("[nope]", 1.0))
        self.assertEqual(w.steps, [])


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
        run.other, run.other_state = {"mode": "haiku", "money": {"ledger_end": 0.05}}, "known"
        self.assertAlmostEqual(0.10 + 0.05 + 0.05 + 0.05, qa.claude_spent([0.10, 0.05], 2))
        self.assertTrue(run.money_ok(0.03))                                  # 0.25 + 0.03 is under 0.30
        run.other = {"mode": "haiku", "money": {"ledger_end": 0.10}}
        self.assertFalse(run.money_ok(0.03))                                 # 0.30 + 0.03 is over it
        run.cap = 0.05
        run.other, run.other_state = None, "none"
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

    # -- the first task does not assume which screen comes first, and a chat box that cannot be used is a dead end ------------------------

    def first_site(self, leave=False, ending="input"):
        pages = {"#/": {"_text": "首頁", '[data-home-step="2"] a[href="#/ceo"]': {"top": 300}},
                 "#/ceo": {qa.CEO_GO: {"top": 400}, "_text": "建立 CEO"},
                 "#/chat/c1": {"_text": "chat", **({qa.CHAT_INPUT: {"top": 300}} if ending == "input" else {'[data-chat="prep-action"]': {"top": 300}})}}
        if leave:
            pages["#/"][qa.LEAVE] = {"top": 200}
            pages["#/start"] = {'[data-home-step="2"] a[href="#/ceo"]': {"top": 300}, "_text": "開始設定"}
        links = {("#/", '[data-home-step="2"] a[href="#/ceo"]'): "#/ceo", ("#/ceo", qa.CEO_GO): "#/chat/c1"}
        if leave:
            links[("#/", qa.LEAVE)] = "#/"
        return pages, links

    def first_run(self, support=None, **site):
        pages, links = self.first_site(**site)
        console = FakeConsole()
        console.support_state = support
        page = FakePage(pages, links, on_click={qa.CEO_GO: lambda: console.profiles.append({"id": "prof-000000000001", "name": "CEO", "model": {"tool": "claude"}})})
        run, page, console = self.run_for(page=page, console=console)
        run.orig = {"daily": 3.0, "per_turn": 0.25, "profiles": set(), "routines": set()}
        return run, page, console

    def test_a_real_machine_that_opens_on_the_home_page_is_not_unable_for_lack_of_the_start_up_button(self):
        run, page, console = self.first_run(support="verified")
        run.play("first")
        task = run.tasks["first"]
        self.assertIsNone(task["unable"])
        self.assertEqual(task["steps"], 3)                           # the link to the CEO, the create button, the look at the box
        self.assertNotIn(("click", qa.LEAVE), page.log)

    def test_when_the_start_up_button_is_on_the_screen_it_is_pressed_first(self):
        run, page, console = self.first_run(support="verified", leave=True)
        run.play("first")
        self.assertIn(("click", qa.LEAVE), page.log)
        self.assertEqual(run.tasks["first"]["steps"], 4)

    def test_without_a_model_a_chat_box_that_cannot_be_used_is_a_dead_end_counted_as_stuck_and_written_in_the_task(self):
        for support, words in (("unverified", "state unverified"), ("policy", "state policy"), ("unreadable", "could not be read")):
            run, page, console = self.first_run(support=support)
            run.task_first()
            task = run.tasks["first"]
            self.assertGreaterEqual(task["stuck"], 1, support)
            self.assertIn(words, task["dead_end"], support)
            self.assertEqual(task["steps"], 3, "a dead end is not one more step")
            self.assertTrue([line for line in self.lines if line.startswith("warn") and "cannot be used" in line])
            self.lines.clear()

    def test_a_chat_box_that_can_be_used_or_the_prepare_pages_one_action_is_not_a_dead_end(self):
        run, page, console = self.first_run(support="verified")
        run.task_first()
        self.assertNotIn("dead_end", run.tasks["first"])
        self.assertEqual(run.tasks["first"]["stuck"], 0)
        run, page, console = self.first_run(support="policy", ending="prep")
        run.task_first()
        self.assertNotIn("dead_end", run.tasks["first"])
        self.assertEqual(run.tasks["first"]["stuck"], 0)

    # -- money that is not known is never zero ---------------------------------------------------------------------------------------

    def test_what_the_other_version_spent_is_zero_only_for_the_first_of_the_pair(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.10"))
        run.read_other()
        self.assertEqual(run.other_state, "none")
        self.assertTrue(run.money_ok(0.03))
        (self.root / "started-before.txt").write_text("started\n")             # the other version began, and left no result
        run.read_other()
        self.assertEqual(run.other_state, "unknown")
        self.assertFalse(run.money_ok(0.0), "it spends nothing when it does not know what the other spent")
        self.assertTrue([line for line in self.lines if line.startswith("warn")])

    def test_a_result_of_the_other_version_without_a_readable_amount_is_unknown_not_zero(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.01"))
        good = {"label": "before", "mode": "haiku", "ui": "x", "phone": {}, "shots": [], "checks": {"ok": 1, "warn": 0, "fail": 0},
                "tasks": {n: {"steps": 1, "stuck": 0, "unable": None, "read": 1, "bad": [], "done": True} for n in qa.TASKS}}
        for amount, state in ((0.04, "known"), (None, "unknown"), ("x", "unknown"), (-1, "unknown")):
            (self.root / "qa47-before.json").write_text(json.dumps({**good, "money": {"ledger_end": amount}}))
            run.read_other()
            self.assertEqual(run.other_state, state, amount)
        (self.root / "qa47-before.json").write_text("not json")
        (self.root / "started-before.txt").write_text("started\n")
        run.read_other()
        self.assertEqual(run.other_state, "unknown")
        (self.root / "qa47-before.json").write_text(json.dumps({**good, "money": {"ledger_end": 0.0}, "label": "after"}))
        run.read_other()
        self.assertEqual(run.other_state, "unknown", "a file that is not the other version's")

    def test_a_result_file_that_is_there_but_cannot_be_read_is_unknown_even_without_a_start_marker(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.01"))
        path = self.root / "qa47-before.json"
        for what, make in (("not json", lambda: path.write_text("{not json")), ("empty", lambda: path.write_text("")),
                           ("null", lambda: path.write_text("null")), ("a list", lambda: path.write_text("[]")),
                           ("a folder", lambda: path.mkdir())):
            if path.is_dir():
                path.rmdir()
            elif path.exists():
                path.unlink()
            make()
            self.assertFalse((self.root / "started-before.txt").exists())
            run.read_other()
            self.assertEqual(run.other_state, "unknown", what)
            self.assertIsNone(run.other_ledger(), what)
            self.assertFalse(run.money_ok(0.0), f"{what}: no step that spends Claude's money")
        if path.is_dir():
            path.rmdir()
        run.read_other()
        self.assertEqual(run.other_state, "none", "no file at all and no marker is the first of the pair")
        self.assertTrue(run.money_ok(0.03))

    def test_a_start_marker_that_cannot_be_written_refuses_every_step_that_spends(self):
        run, page, console = self.run_for(haiku=True, console=FakeConsole(ledger="0.00"))
        run.read_other()
        self.assertTrue(run.money_ok(0.03), "the first of the pair spends when the marker is kept")
        (self.root / "started-after.txt").mkdir()                    # a folder where the marker has to be: the write fails
        run.mark_started()
        self.assertFalse(run.money_ok(0.03), "no evidence of the start is kept: the next run could not know this one began")
        self.assertTrue([line for line in self.lines if line.startswith("warn") and "marker" in line])

    def test_a_ledger_that_cannot_be_read_at_the_end_is_null_with_a_fail_and_the_next_run_then_spends_nothing(self):
        class Gone(FakeConsole):
            def call(self, path, method="GET", body=None):
                return (0, None) if path == "/api/meetings/ledger" else super().call(path, method, body)
        run, page, console = self.run_for(label="before", haiku=True, console=Gone())
        for name in qa.TASKS:
            run.tasks[name] = {"steps": 1, "stuck": 0, "unable": None, "read": 1, "bad": [], "done": True}
        result = run.result()
        self.assertIsNone(result["money"]["ledger_end"])
        self.assertEqual(result["checks"]["fail"], 1)
        self.assertTrue([line for line in self.lines if line.startswith("FAIL") and "ledger" in line])
        (self.root / "qa47-before.json").write_text(json.dumps(result))
        later, page2, console2 = self.run_for(label="after", haiku=True, console=FakeConsole(ledger="0.00"))
        later.read_other()
        self.assertEqual(later.other_state, "unknown")
        self.assertFalse(later.money_ok(0.03))

    # -- clean-up deletes only what this run made ----------------------------------------------------------------------------------------

    def test_a_routine_that_was_there_before_the_run_is_not_deleted_even_if_it_has_the_runs_prefix(self):
        run, page, console = self.run_for()
        console.routines = [{"id": "r-before", "name": "QA47 虛構早安", "enabled": True}, {"id": "r-mine", "name": "QA47 虛構早安", "enabled": True},
                            {"id": "r-other", "name": "別的工作", "enabled": True}]
        run.orig["routines"] = {"r-before"}
        run.made["routines"] = ["r-mine"]
        run.cleanup()
        self.assertEqual(sorted(r["id"] for r in console.routines), ["r-before", "r-other"])
        deletes = [c for c in console.log if c[1].startswith("/api/routines/") and c[1].endswith("/delete")]
        self.assertEqual([c[1] for c in deletes], ["/api/routines/r-mine/delete"])

    def test_the_routine_the_run_saved_is_found_among_the_new_ones_only(self):
        run, page, console = self.run_for()
        console.routines = [{"id": "r-before", "name": "QA47 虛構早安", "enabled": False, "days": [1], "times": ["07:00"]}]
        run.orig["routines"] = {"r-before"}
        console.routines.append({"id": "r-new", "name": "QA47 虛構早安", "enabled": True, "days": list(range(7)), "times": ["08:00"]})
        run.then_routine_saved()
        self.assertEqual(run.made["routines"], ["r-new"])
        self.assertTrue([line for line in self.lines if line.startswith("ok") and "08:00" in line])

    # -- a wait is never longer than two minutes -----------------------------------------------------------------------------------------

    def test_a_wait_that_asks_for_more_than_two_minutes_gives_up_at_two_minutes(self):
        run, page, console = self.run_for()
        clock = FakeClock(step=1.0)
        run.clock = clock
        with self.assertRaises(qa.Stop):
            run.wait("something that never comes", lambda: False, cap=10 ** 6, every=1.0)
        self.assertLess(clock.now, qa.WAIT_CAP_S + 30)

    def test_a_wait_by_api_polling_stops_when_the_five_minutes_of_the_chrome_are_over(self):
        # No Chrome is started: a Browser object built without its program, on a clock that moves by hand. The probes are API calls, so no
        # Chrome command is there to find out that the 5 minutes are over.
        b = qa.Browser.__new__(qa.Browser)
        b.now, b.started, b.proc, b.sent = 0.0, 0.0, None, []
        b.clock = lambda: b.now
        run, page, console = self.run_for()
        page.b = b
        run.clock = lambda: b.now
        probes, sleeps = [], []

        def probe():
            probes.append(b.now)
            b.now += 1.0
            return False

        def sleep(sec):
            sleeps.append(sec)
            b.now += sec
        run.sleep = sleep
        run.started = b.now
        b.now = qa.CHROME_CAP_S - 2.0                           # the Chrome has two seconds left
        with self.assertRaises(qa.Stop):
            run.wait("something that never comes", probe, cap=qa.WAIT_CAP_S, every=5.0)
        self.assertLessEqual(max(probes), qa.CHROME_CAP_S, "no probe after the 5 minutes")
        self.assertLessEqual(b.now, qa.CHROME_CAP_S + 1.0)
        for before, sec in zip(probes, sleeps):
            self.assertLessEqual(before + 1.0 + sec, qa.CHROME_CAP_S + 1e-9, "no sleep goes past what is left of the 5 minutes")

    def test_a_wait_that_begins_after_the_five_minutes_probes_nothing(self):
        b = qa.Browser.__new__(qa.Browser)
        b.now, b.started, b.proc = qa.CHROME_CAP_S + 10.0, 0.0, None
        b.clock = lambda: b.now
        run, page, console = self.run_for()
        page.b = b
        run.clock = lambda: b.now
        run.started = b.now
        probes = []
        with self.assertRaises(qa.Stop):
            run.wait("anything", lambda: probes.append(1) or True)
        self.assertEqual(probes, [])

    @staticmethod
    def fake_connection(seen, read):
        """A stand-in for http.client.HTTPConnection, the connection a call inside a wait holds (so that it can close it when time is over)."""
        class Reply:
            status = 200

            def read(inner, n=-1):
                return read()

        class Conn:
            sock = None

            def __init__(inner, host, port, timeout=None):
                seen.append(timeout)

            def connect(inner):
                pass

            def request(inner, *a, **k):                   # no network: the call's own connect (set on it) is not reached
                pass

            def getresponse(inner):
                return Reply()

            def close(inner):
                pass
        return Conn

    def test_the_http_call_of_a_wait_never_waits_longer_than_what_is_left_and_is_back_to_normal_after_it(self):
        import unittest.mock as mock
        b = qa.Browser.__new__(qa.Browser)
        b.now, b.started, b.proc = qa.CHROME_CAP_S - 7.0, 0.0, None
        b.clock = lambda: b.now
        console = qa.Console(qa.DEFAULT_PORT, "t")                         # the real class: only the network underneath is replaced
        seen, plain = [], []

        class Reply:
            status = 200

            def __enter__(inner):
                return inner

            def __exit__(inner, *a):
                return False

            def read(inner, n=-1):
                return b"{}"

        def fake_urlopen(req, timeout=None):
            plain.append(timeout)
            return Reply()
        run, page, _ = self.run_for(console=console)
        page.b = b
        run.clock = lambda: b.now
        run.started = b.now
        with mock.patch.object(qa.http.client, "HTTPConnection", self.fake_connection(seen, lambda: b"{}")), \
                mock.patch.object(qa.urllib.request, "urlopen", fake_urlopen):
            run.wait("an answer", lambda: console.call("/api/x")[0] == 200)
            self.assertLessEqual(seen[-1], 7.0, "inside a wait the call is held to what is left")
            console.call("/api/x")
            self.assertEqual(plain[-1], console.timeout, "outside a wait (the clean-up) it is the normal limit")

    def test_an_answer_that_trickles_in_past_the_five_minutes_is_not_taken(self):
        # R3: each read is quick, but together they go past what is left; the answer must not be taken as a success.
        import unittest.mock as mock
        b = qa.Browser.__new__(qa.Browser)
        b.now, b.started, b.proc = qa.CHROME_CAP_S - 1.0, 0.0, None
        b.clock = lambda: b.now
        console = qa.Console(qa.DEFAULT_PORT, "t")

        def slow_body():
            b.now += 2.0                                    # the whole body comes, but only after what was left
            return b'{"ready": true}'
        run, page, _ = self.run_for(console=console)
        page.b = b
        run.clock = lambda: b.now
        run.started = b.now
        run.sleep = lambda sec: None
        with mock.patch.object(qa.http.client, "HTTPConnection", self.fake_connection([], slow_body)):
            with self.assertRaises(qa.Stop):
                run.wait("an answer", lambda: (console.call("/api/x")[1] or {}).get("ready"))

    def test_a_real_http_answer_that_trickles_is_given_up_when_the_time_left_is_over(self):
        # R4/R5: a real call against a little local server (a random loopback port, not VBear) that sends its status line and headers, or an
        # error's body, a byte at a time and would go on long after: each byte is quicker than the socket timeout, the whole is not. The call
        # must end near the time left, and its connection must be closed so that nothing is left reading.
        import socket
        import time as _time
        replies = {
            "headers": b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Long: " + b"a" * 400 + b"\r\nContent-Length: 15\r\n\r\n" + b'{"ready": true}',
            "error": b"HTTP/1.1 409 Conflict\r\nContent-Type: application/json\r\nContent-Length: 400\r\n\r\n" + b" " * 400,
            # R6: the console's own way (HTTP/1.0, "Connection: close"): the answer takes the socket from the connection
            "close 200": b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: 400\r\n\r\n" + b" " * 400,
            "close 409": b"HTTP/1.0 409 Conflict\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: 400\r\n\r\n" + b" " * 400,
        }
        for name, raw in replies.items():
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            srv.settimeout(5.0)
            port = srv.getsockname()[1]
            slow_from = 0 if name == "headers" else raw.index(b"\r\n\r\n") + 4
            # the server goes on sending long after the time left (400 bytes at 0.01 s: 4 s), unless the reader closes its end
            gone = threading.Event()

            def serve():
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                try:
                    conn.recv(65536)
                    for i, byte in enumerate(raw):
                        conn.sendall(bytes([byte]))
                        if i >= slow_from:
                            _time.sleep(0.01)
                except OSError:
                    gone.set()                              # the reader closed its end: the server stops sending
                finally:
                    conn.close()
            t = threading.Thread(target=serve, daemon=True)
            before = threading.active_count()
            t.start()
            try:
                console = qa.Console(port, "t", timeout=5.0)
                end = _time.monotonic() + 0.2
                console.budget = lambda: end - _time.monotonic()
                began = _time.monotonic()
                code, data = console.call("/api/x")
                took = _time.monotonic() - began
                self.assertEqual((code, data), (0, None), name)
                self.assertLess(took, 1.5, f"{name}: the call ended near the time left ({took:.3f} s)")
                t.join(3.0)
                self.assertFalse(t.is_alive(), f"{name}: the server saw the connection closed and stopped")
                self.assertTrue(gone.is_set(), f"{name}: it was the reader that closed it, before the answer was done")
                self.assertLessEqual(threading.active_count(), before, f"{name}: no thread of the call is left reading")
            finally:
                srv.close()
                t.join(3.0)

    def test_a_connect_that_finishes_after_the_time_left_sends_nothing_and_leaves_no_socket_open(self):
        # R7: the deadline can fall while the connection is being made; the socket must still be closed and no request may go out.
        import socket
        import time as _time
        import unittest.mock as mock
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.settimeout(3.0)
        port = srv.getsockname()[1]
        got = []

        def serve():
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                conn.settimeout(1.0)
                got.append(conn.recv(65536))
            except OSError:
                pass
            finally:
                conn.close()
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        made = []
        real = socket.socket

        class SlowConnect(real):
            def connect(inner, addr):
                made.append(inner)
                _time.sleep(0.3)                            # the deadline (0.1 s) falls while the connection is being made
                return super().connect(addr)
        try:
            console = qa.Console(port, "t", timeout=5.0)
            end = _time.monotonic() + 0.1
            console.budget = lambda: end - _time.monotonic()
            with mock.patch.object(qa.socket, "socket", SlowConnect):
                began = _time.monotonic()
                code, data = console.call("/api/x")
                took = _time.monotonic() - began
            self.assertEqual((code, data), (0, None))
            self.assertLess(took, 1.5)
            self.assertTrue(made, "the socket was made")
            self.assertTrue(all(sock.fileno() == -1 for sock in made), "every socket of the call is closed when it returns")
            t.join(2.0)
            self.assertFalse(any(g for g in got), "no request went out after the time left")
        finally:
            srv.close()
            t.join(3.0)

    def test_a_probe_that_answers_after_the_deadline_is_not_taken(self):
        b = qa.Browser.__new__(qa.Browser)
        b.now, b.started, b.proc = qa.CHROME_CAP_S - 1.0, 0.0, None
        b.clock = lambda: b.now
        run, page, console = self.run_for()
        page.b = b
        run.clock = lambda: b.now
        run.started = b.now

        def late():
            b.now += 5.0                                    # the answer comes, but only after the 5 minutes
            return True
        with self.assertRaises(qa.Stop):
            run.wait("a late answer", late)

    def test_the_chat_check_does_not_ask_for_more_than_one_wait(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("WAIT_CAP_S * 2", source)
        self.assertNotRegex(source, r"cap=WAIT_CAP_S\s*\*")

    def test_an_address_is_written_down_without_an_id(self):
        self.assertEqual(qa.page_head("#/chat/c-0123456789abcdef"), "#/chat")
        self.assertEqual(qa.page_head("#/chat?profile=prof-1"), "#/chat")
        self.assertEqual(qa.page_head("#/settings?open=limits"), "#/settings")
        self.assertEqual(qa.page_head("#/"), "#/")
        self.assertEqual(qa.page_head(""), "#/")


class BrowserDeadlineTests(unittest.TestCase):
    """The 5 minutes of one Chrome, over a clock that is moved by hand (no Chrome is started: the object is built without its program)."""

    def browser(self):
        b = qa.Browser.__new__(qa.Browser)
        b.now = 0.0
        b.clock = lambda: b.now
        b.started = 0.0
        b.sent = []
        b.proc = None
        return b

    def test_no_wait_goes_past_what_is_left_of_the_five_minutes_or_past_two_minutes(self):
        b = self.browser()
        self.assertEqual(b.allowed_wait(30), 30)
        self.assertEqual(b.allowed_wait(600), qa.WAIT_CAP_S)              # no single wait is longer than 2 minutes
        b.now = qa.CHROME_CAP_S - 10
        self.assertEqual(b.allowed_wait(600), 10)                          # nor than what is left
        self.assertFalse(b.over())

    def test_after_five_minutes_no_command_is_sent_any_more(self):
        b = self.browser()
        b.now = qa.CHROME_CAP_S + 1
        self.assertTrue(b.over())
        with self.assertRaises(qa.Stop) as ctx:
            b.call("Runtime.evaluate", {"expression": "1"})
        self.assertIn("5 minutes", str(ctx.exception))

    def test_closing_still_goes_through_after_the_deadline_and_the_program_is_ended(self):
        b = self.browser()
        b.now = qa.CHROME_CAP_S + 60
        sent = []
        b.call = lambda method, params=None, session=None, wait=30.0, force=False: sent.append((method, wait, force)) or {}

        class Proc:
            ended = []

            def wait(self, timeout=None):
                self.ended.append("wait")

            def terminate(self):
                self.ended.append("terminate")

            def kill(self):
                self.ended.append("kill")
        b.proc, b.wfd, b.rfd = Proc(), -1, -1
        b.close()
        self.assertEqual(sent, [("Browser.close", 5, True)])
        self.assertIn("wait", Proc.ended)
        self.assertIsNone(b.proc)

    def test_the_run_closes_its_chrome_when_the_walk_stops_because_of_the_deadline(self):
        root = Path(tempfile.mkdtemp(prefix="q47"))
        self.addCleanup(shutil.rmtree, root, True)
        chrome = root / "chrome"
        chrome.write_text("x")
        state = make_state(root)
        closed = []

        class Late:
            def __init__(inner, chrome_path, profile):
                inner.profile = profile

            def close(inner):
                closed.append("closed")

        class Dead:
            def __getattr__(inner, name):
                def fail(*a, **k):
                    raise qa.Stop("the 5 minutes of this Chrome are over")
                return fail
        app = root / "app.js"
        app.write_text("const WORDS = {\n};\nconst PLAIN_ERRORS = [\n];\n", encoding="utf-8")
        lines = []
        code = qa.main(["--state", str(state), "--label", "after", "--chrome", str(chrome)], out=lines.append, console_factory=lambda port, token: FakeConsole(),
                       browser_factory=Late, page_factory=lambda b, base: Dead(), sleep=lambda s: None, clock=FakeClock(), home=root, app_js=app)
        self.assertEqual(code, 1)
        self.assertEqual(closed, ["closed"])


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

    def test_every_port_but_7802_is_refused_before_the_token_is_read_or_chrome_is_started(self):
        for port in ("7795", "7801", "7803", "8080"):
            self.lines.clear()
            self.assertEqual(self.go("--port", port), 2, port)
            self.assertIn("only port 7802", self.lines[0], port)
        (self.state / "server.token").unlink()                      # a token that cannot be read would be a different message, if it got that far
        self.lines.clear()
        self.assertEqual(self.go("--port", "7795"), 2)
        self.assertIn("only port 7802", self.lines[0])
        self.assertEqual(self.closed, [])
        self.assertEqual(self.page.log, [])

    def test_a_run_leaves_a_start_marker_that_is_not_a_result_file(self):
        self.go()
        self.assertTrue((self.root / "started-after.txt").is_file())
        self.assertFalse(str(self.root / "started-after.txt").endswith(".json"))

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
