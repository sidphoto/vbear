"""P48-7: tools/qa_p48.py, the coordinator's before/after walk of v0.21.0 against v0.22.0 in a headless Chrome, must refuse to run against the person's VBear
(its folder, anything under it, ports 7788 and 7789) and on any port but 7803 or with a Claude cap above US$0.30; leave the AI tools' ``--version`` alone
(it never reads /api/chats itself, and says in its text that the pages do); ask the console nothing before the first (cold) load; count steps and the seconds
of white the way its docstring says; call the picker's one press and v0.21.0's look at Claude's row the same single step; judge the title, the notification
switch, the logo, the false empty and the cold frame by what they must be; open no TCP debugging port; use only the standard library (and the sibling
qa_p47.py, imported and not copied); find elements only by data attributes, href, ids and the dialog's classes; print nothing a model wrote and not the token;
and compare two result files into a table.
Nothing here starts Chrome, a console, a model or an AI tool: the browser page is a small in-memory fake and so is the console (the real page is walked by
the coordinator). The page's own clock (the script installed in the page) is run under ``node`` against a tiny stand-in for the page, as qa_p47's tables are.
Everything here is made up.

Seams: ``refusal``, ``parse_tasks``, ``title_ok`` / ``logo_ok`` / ``notify_ok``, ``blank_summary``, ``result_ok``, ``verdict`` / ``compare_table`` / ``compare``,
``observer_source`` (under node), ``read_ui_version`` (a local server of our own), ``Run`` over a fake page and console, and ``main`` (the command line, with
those fakes)."""
from __future__ import annotations

import ast
import contextlib
import http.server
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

SOURCE = Path(__file__).resolve().parent.parent / "tools" / "qa_p48.py"
SPEC = importlib.util.spec_from_file_location("qa_p48", SOURCE)
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)
q47 = qa.qa47

TOKEN = "synthetic-token-never-printed"
MODEL_WORDS = "MODEL-WORDS-never-printed"


# ---- fakes ------------------------------------------------------------------------------------------------------------------------------

class FakeClock:
    """Time that moves only when it is looked at."""

    def __init__(self, step=0.05):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


class FakePage:
    """A page that is a table: route -> {selector: info, "_h1": ms, "_ready": ms}. ``info``: ``top``, ``at`` (the page's own milliseconds at which it first
    showed), ``checked``, ``text``, ``disabled``, ``attrs``, ``count``. A click goes where ``links`` says."""

    def __init__(self, pages, links, opens_at="#/setup", on_click=None, events=None, title="VBear", logo=None):
        self.pages, self.links, self.opens_at, self.on_click = pages, links, opens_at, on_click or {}
        self.where, self.offset, self.log, self.events = "about:blank", 0, [], events if events is not None else []
        self.size = q47.DESKTOP
        self.fresh = False
        self.posts: list = []
        self.the_title = title
        self.the_logo = logo if logo is not None else {"mode": "image", "complete": True, "decoded": True, "tries": 1, "retried": False}
        self.installed = None

    picked = False                  # a tool was picked and the page remembers it: the setup page then has no picker (the test sets this)

    def _el(self, sel):
        if self.picked and self.where == "#/setup" and sel == qa.PICK_CLAUDE:
            return None
        return (self.pages.get(self.where) or {}).get(sel)

    def _note(self, *what):
        self.log.append(what)
        self.events.append(("page", *what))

    def viewport(self, w, h):
        self.size = (w, h)

    def install(self, sels=None):
        self.installed = list(sels or [])
        self._note("install")

    def open(self, url):
        self.fresh = True
        self.where = self.opens_at
        self._note("open", "token" if "#auth=" in url else url)

    def goto(self, hash_):
        self.fresh = True
        self.where, self.offset = hash_, 0
        self._note("goto", hash_)

    def forget_pick(self):
        self._note("forget_pick")
        self.picked = False

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
        self.fresh = True
        self._note("click", sel)
        if sel in self.on_click:
            self.on_click[sel]()
        dest = self.links.get((self.where, sel))
        if dest:
            self.offset = 0
            self.where = dest
        return True

    def fill(self, sel, value):
        self._note("fill", sel)
        return self._el(sel) is not None

    def scroll(self, sel=None):
        return False

    def into_view(self, sel):
        self.offset = 0

    def to_top(self):
        self.offset = 0

    def at_bottom(self):
        return True

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

    def ev(self, expression):
        return False

    def timing(self):
        page = self.pages.get(self.where) or {}
        first = {sel: e.get("at", 100) for sel, e in page.items() if isinstance(e, dict) and not sel.startswith("_") and e.get("shown", True)}
        return {"h1": page.get("_h1"), "ready": page.get("_ready"), "first": first, "falseEmpty": page.get("_false_empty", False), "loadingSeen": True,
                "posts": list(self.posts)}

    def title(self):
        return self.the_title

    def attr(self, sel, name):
        return ((self._el(sel) or {}).get("attrs") or {}).get(name)

    def count(self, sel):
        return int((self._el(sel) or {}).get("count", 1 if self._el(sel) else 0))

    def logo(self):
        return self.the_logo


class FakeConsole(q47.Console):
    def __init__(self, daily=3.0, events=None, token=TOKEN):
        super().__init__(7803, token)
        self.daily, self.per_turn = daily, 0.25
        self.profiles, self.routines, self.log = [], [], []
        self.events = events if events is not None else []
        self.config = {}

    def call(self, path, method="GET", body=None):
        clean = path.split("?")[0]
        self.log.append((method, clean, body))
        self.events.append(("console", method, clean))
        if (method, clean) == ("GET", "/api/meetings/ledger"):
            return 200, {"spent_usd": "0", "daily_usd": str(self.daily)}
        if (method, clean) == ("GET", "/api/config"):
            return 200, {"config": {"chat_limits": {"per_turn_usd": self.per_turn}}}
        if (method, clean) == ("POST", "/api/config"):
            if isinstance(body, dict) and "chat_limits" in body:
                self.per_turn = body["chat_limits"]["per_turn_usd"]
            self.config.update({k: v for k, v in (body or {}).items() if k != "chat_limits"})
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
        if method == "DELETE" and clean.startswith("/api/chats/"):
            return 200, {"ok": True}
        return 404, None


CLAUDE = q47.PATHS  # (the regression paths are qa_p47's)


def site(label):
    """The pages the first walk, the settings and the limit / routine tasks need, with the page's own milliseconds."""
    nav = {qa.NAV_SETTINGS: {"top": 200, "at": 80}, '[data-nav="work"]': {"top": 160, "at": 80}}
    pages = {
        "#/": {**nav, "_text": "首頁", "_h1": 120, "_ready": 300},
        "#/settings": {**nav, q47.LIMITS_SUMMARY: {"top": 300}, "_text": "設定", "_h1": 100, "_ready": 100},
        "#/settings#open": {**nav, q47.LIMITS_SUMMARY: {"top": 300}, '[data-limit-choice="custom"]': {"top": 400}, "[data-limit-input]": {"top": 450},
                            "[data-limit-save]": {"top": 500}, "[data-limit-current]": {"top": 360, "text": "US$3"}, "_text": "設定 用量與上限"},
        "#/work": {**nav, '[data-work="routines"]': {"top": 250}, "_text": "工作"},
        "#/routines": {**nav, '[data-routine-action="new"]': {"top": 400}, "_text": "定時工作"},
        "#/routines#form": {**nav, '[data-routine-field="name"]': {"top": 200}, '[data-routine-field="text"]': {"top": 300},
                            '[data-routine-field="enabled"]': {"top": 350, "checked": True}, **{sel: {"top": 400, "checked": True} for sel in q47.ROUTINE_DAYS},
                            '[data-routine-action="save"]': {"top": 500}, "_text": "新增定時工作"},
        "#/ceo": {qa.CEO_GO: {"top": 300, "at": 140}, "_text": "建立你的 CEO", "_h1": 90, "_ready": 90},
        "#/chat?profile=prof-1": {'[data-chat="prep-action"]': {"top": 300, "at": 200}, "_text": "先把聊天準備好", "_h1": 90, "_ready": 90},
        "#/setup#next": {qa.LEAVE: {"top": 500, "at": 60}, "_text": "開始設定", "_h1": 60, "_ready": 60},
    }
    if label == "after":
        pages["#/settings"].update({qa.NOTIFY_BLOCK: {"top": 700, "at": 90}, qa.NOTIFY_SWITCH: {"top": 720, "at": 90, "checked": False},
                                    qa.NOTIFY_RESULT: {"top": 760, "text": ""}})
    if label == "before":
        pages["#/setup"] = {qa.CLAUDE_ROW: {"top": 300, "at": 12000}, qa.LEAVE: {"top": 500, "at": 12000}, "_text": "開始設定", "_h1": 11900, "_ready": 11900}
        links = {("#/setup", qa.LEAVE): "#/ceo"}
    else:
        pages["#/setup"] = {qa.PICK_CLAUDE: {"top": 300, "at": 450}, "_text": "開始設定", "_h1": 180, "_ready": 450}
        pages["#/setup#picked"] = {qa.CHECK_LIST: {"top": 400}, qa.CHANGE_PICK: {"top": 380}, qa.CHECK_CHAT: {"top": 420, "attrs": {"data-result": "fail"}},
                                   qa.CHECK_ITEMS: {"top": 430, "count": 4}, qa.LEAVE: {"top": 500, "at": 20}, "_text": "你選了：Anthropic Claude"}
        links = {("#/setup", qa.PICK_CLAUDE): "#/setup#picked", ("#/setup#picked", qa.LEAVE): "#/ceo"}
        # v0.25: the home page of a person with no employee does the first run itself: the pick opens the checklist in place, and its button makes the CEO
        pages["#/"][qa.PICK_CLAUDE] = {"top": 300, "at": 450}
        pages["#/#picked"] = {**nav, qa.CHECK_LIST: {"top": 400}, qa.CHANGE_PICK: {"top": 380}, qa.CHECK_CHAT: {"top": 420, "attrs": {"data-result": "fail"}},
                              qa.CHECK_ITEMS: {"top": 430, "count": 4}, q47.HOME_CEO_GO: {"top": 500, "at": 20}, "_text": "你選了：Anthropic Claude"}
        links.update({("#/", qa.PICK_CLAUDE): "#/#picked", ("#/#picked", q47.HOME_CEO_GO): "#/chat?profile=prof-1"})
    links.update({("#/ceo", qa.CEO_GO): "#/chat?profile=prof-1", ("#/", qa.NAV_SETTINGS): "#/settings", ("#/settings", q47.LIMITS_SUMMARY): "#/settings#open", ("#/", '[data-nav="work"]'): "#/work",
                  ("#/work", '[data-work="routines"]'): "#/routines", ("#/routines", '[data-routine-action="new"]'): "#/routines#form",
                  ("#/routines#form", '[data-routine-action="save"]'): "#/routines",
                  ("#/settings#open", q47.LIMITS_SUMMARY): "#/settings", ("#/settings#open", '[data-limit-choice="custom"]'): "#/settings#open"})
    return pages, links


def make_state(root: Path, name: str = "b", port: int = 7803) -> Path:
    state = root / name
    state.mkdir()
    (state / "server.token").write_text(json.dumps({"port": port, "token": TOKEN}))
    return state


def task(steps=4, stuck=0, done=True, **extra):
    return {"steps": steps, "stuck": stuck, "unable": None, "read": 100, "bad": [], "done": done, **extra}


def run_file(label="before", **over):
    """A result file the way a run writes it (every task, made-up numbers)."""
    tasks = {
        "first": task(4, 0, blank_max_s=12.0, blank_total_s=12.5, total_s=20.0),
        "home": task(0, 0, h1_s=12.0, ready_s=12.0, false_empty=False, cold=True),
        "title": task(0, 0, title="VBear", ok=True),
        "notify": task(0, 0, present=False, ok=True),
        "logo": task(0, 0, mode="image", ok=True),
        "limit": task(7, 0), "routine": task(6, 0), "blocked": task(3, 0),
    }
    if label == "after":
        tasks["first"].update(blank_max_s=0.45, blank_total_s=0.9, total_s=15.0)
        tasks["home"].update(h1_s=0.2, ready_s=0.6)
        tasks["notify"] = task(1, 0, present=True, default_off=True, posts=0, answered=True, ok=True)
    tasks.update(over.pop("tasks", {}))
    return {"label": label, "mode": "no-ai", "ui": qa.UI_OF[label], "tasks": tasks, "phone": {"first_action_px": 380},
            "money": {"ledger_end": 0.0, "claude_cap": 0.3, "chat_check_reserve": 0.0}, "checks": {"ok": 10, "warn": 0, "fail": 0}, **over}


# ---- the pure helpers -------------------------------------------------------------------------------------------------------------------

class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="q48"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = make_state(self.root)
        self.chrome = self.root / "chrome"
        self.chrome.write_text("x")

    def refuse(self, **kw):
        args = {"state": str(self.state), "port": 7803, "cap": 0.30, "label": "after", "home": self.root, "chrome": str(self.chrome)}
        args.update(kw)
        return qa.refusal(args.pop("state"), args.pop("port"), **args)

    def test_a_good_call_is_not_refused(self):
        self.assertIsNone(self.refuse())

    def test_the_persons_own_ports_are_refused_and_so_is_every_port_but_7803(self):
        for port in (7788, 7789):
            self.assertIn("own VBear", self.refuse(port=port))
        for port in (7795, 7800, 7802, 8080, 1024):
            self.assertIn("only port 7803", self.refuse(port=port), port)
        for port in (0, 80, 70000, True, "7803", None):
            self.assertIsNotNone(self.refuse(port=port), port)

    def test_the_persons_own_folder_and_anything_under_it_is_refused(self):
        own = self.root / ".vbear"
        (own / "deep").mkdir(parents=True)
        for path in (own, own / "deep"):
            self.assertIn("own VBear folder", self.refuse(state=str(path)))
        self.assertIsNotNone(self.refuse(state=str(self.root / "missing")))

    def test_a_cap_above_thirty_cents_or_not_above_zero_is_refused_and_the_label_and_chrome_have_to_be_real(self):
        for cap in (0.31, 1, 0, -1, True):
            self.assertIsNotNone(self.refuse(cap=cap), cap)
        self.assertIsNone(self.refuse(cap=0.05))
        self.assertIsNotNone(self.refuse(label="middle"))
        self.assertIsNotNone(self.refuse(chrome=str(self.root / "no-chrome")))

    def test_the_constants_are_the_rule(self):
        self.assertEqual(qa.DEFAULT_PORT, 7803)
        self.assertEqual(qa.FORBIDDEN_PORTS, (7788, 7789))
        self.assertEqual(qa.CLAUDE_CAP_MAX, 0.30)
        self.assertEqual(qa.COLD_CAP_S, 90.0)


class TaskListTests(unittest.TestCase):
    def test_no_list_means_all_in_order_and_a_list_is_put_in_that_order(self):
        self.assertEqual(qa.parse_tasks(None), qa.TASKS)
        self.assertEqual(qa.parse_tasks(""), qa.TASKS)
        self.assertEqual(qa.parse_tasks("logo, home"), ("home", "logo"))

    def test_an_unknown_name_or_a_name_twice_is_said(self):
        self.assertIn("unknown task: cards", qa.parse_tasks("home,cards"))
        self.assertIn("twice", qa.parse_tasks("home,home"))

    def test_the_tasks_are_the_plans_five_and_the_three_of_the_last_version(self):
        self.assertEqual(qa.TASKS, ("first", "home", "title", "notify", "logo", "limit", "routine", "blocked"))
        self.assertEqual(qa.COLD_TASKS, ("first", "home"))


class JudgeTests(unittest.TestCase):
    def test_a_title_is_the_word_or_a_number_and_the_word(self):
        for t in ("VBear", "(1) VBear", "(12) VBear", "(999) VBear"):
            self.assertTrue(qa.title_ok(t), t)
        for t in ("(1000) VBear", "(x) VBear", "VBear - 阿明", "(1) VBear 阿明想動手", "", None, 3, "vbear"):
            self.assertFalse(qa.title_ok(t), t)

    def test_a_logo_is_letters_or_a_picture_that_decoded(self):
        self.assertTrue(qa.logo_ok({"mode": "text"}))
        self.assertTrue(qa.logo_ok({"mode": "image", "complete": True, "decoded": True}))
        for obs in ({"mode": "image", "complete": True, "decoded": False}, {"mode": "image", "complete": False, "decoded": True}, {"mode": "none"}, {}, None,
                    {"mode": "image", "complete": True}):
            self.assertFalse(qa.logo_ok(obs), obs)

    def test_the_switch_is_there_off_by_default_and_sent_nothing(self):
        good = {"present": True, "default_off": True, "posts": 0}
        self.assertTrue(qa.notify_ok(good))
        for bad in ({**good, "present": False}, {**good, "default_off": False}, {**good, "posts": 1}, {**good, "posts": None}, {}, None):
            self.assertFalse(qa.notify_ok(bad), bad)

    def test_a_number_of_seconds_is_a_number_not_a_word_a_bool_or_a_minus(self):
        self.assertEqual(qa.number(0), 0.0)
        self.assertEqual(qa.number(1.5), 1.5)
        for v in (None, "1", True, -1, float("nan")):
            self.assertIsNone(qa.number(v), v)

    def test_the_white_of_a_task_is_its_longest_wait_the_sum_and_how_many_pages_were_slow(self):
        got = qa.blank_summary([{"target_s": 0.5}, {"target_s": 12.0}, {"target_s": None, "slow": True}, {"target_s": 0.25}])
        self.assertEqual(got, {"blank_max_s": 12.0, "blank_total_s": 12.75, "slow_pages": 1})
        self.assertEqual(qa.blank_summary([]), {"blank_max_s": None, "blank_total_s": None, "slow_pages": 0})


class ResultAndCompareTests(unittest.TestCase):
    def test_a_result_needs_a_label_known_tasks_with_their_numbers_and_the_count_of_checks(self):
        self.assertTrue(qa.result_ok(run_file("before")))
        data = run_file("after")
        data["tasks"]["first"].pop("done")
        self.assertFalse(qa.result_ok(data))
        data = run_file("after")
        data["tasks"]["photos"] = task()
        self.assertFalse(qa.result_ok(data))
        data = run_file("after")
        data["checks"].pop("fail")
        self.assertFalse(qa.result_ok(data))
        self.assertFalse(qa.result_ok({**run_file("after"), "tasks": {}}))
        self.assertTrue(qa.result_ok({**run_file("after"), "tasks": {"home": task(0, 0, h1_s=1.0)}}))      # a run of some tasks only is a result too

    def test_a_pair_with_the_first_flow_as_good_and_the_home_page_faster_is_no_worse(self):
        self.assertEqual(qa.verdict(run_file("before"), run_file("after")), [])

    def test_the_picker_is_the_same_number_of_steps_but_one_more_is_a_regression(self):
        after = run_file("after", tasks={"first": task(5, 0, blank_max_s=0.45, blank_total_s=0.9, total_s=15.0)})
        self.assertIn("first: worse", qa.verdict(run_file("before"), after))
        after = run_file("after", tasks={"first": task(4, 1, blank_max_s=0.45, blank_total_s=0.9, total_s=15.0)})
        self.assertIn("first: worse", qa.verdict(run_file("before"), after))

    def test_a_page_that_stays_white_longer_or_a_home_page_slower_is_named_and_noise_is_not(self):
        after = run_file("after", tasks={"first": task(4, 0, blank_max_s=13.0, blank_total_s=13.0, total_s=20.0)})
        self.assertIn("first: a page stays white longer than before", qa.verdict(run_file("before"), after))
        after = run_file("after")
        after["tasks"]["home"].update(h1_s=12.1, ready_s=12.1, cold=False)
        self.assertEqual(qa.verdict(run_file("before"), after), [])                        # 0.1 s over is inside the noise
        after["tasks"]["home"].update(h1_s=14.0, ready_s=14.0)
        self.assertIn("home: after is slower than before", qa.verdict(run_file("before"), after))
        after["tasks"]["home"].update(h1_s=None, ready_s=None, slow=True)
        self.assertIn("home: after is slower than before", qa.verdict(run_file("before"), after))
        before = run_file("before")
        before["tasks"]["home"].update(h1_s=None, ready_s=None, slow=True)
        self.assertEqual([p for p in qa.verdict(before, run_file("after")) if p.startswith("home: after is slower")], [])

    def test_a_false_empty_in_the_after_run_and_a_cold_frame_over_two_seconds_are_named(self):
        after = run_file("after")
        after["tasks"]["home"]["false_empty"] = True
        self.assertIn("home: after said nothing waits and then showed rows (a false empty)", qa.verdict(run_file("before"), after))
        after = run_file("after")
        after["tasks"]["home"].update(h1_s=2.5, ready_s=2.6, cold=True)
        self.assertTrue([p for p in qa.verdict(run_file("before"), after) if "within 2 seconds" in p])
        after["tasks"]["home"]["cold"] = False                                             # a warm load has no such target
        self.assertEqual([p for p in qa.verdict(run_file("before"), after) if "within 2 seconds" in p], [])
        after["tasks"]["home"].update(cold=True, h1_s=None, slow=True)
        self.assertTrue([p for p in qa.verdict(run_file("before"), after) if "within 2 seconds" in p])

    def test_the_title_the_switch_and_the_logo_of_the_after_run_are_judged_by_what_they_must_be(self):
        for name, bad, text in (("title", {"ok": False, "title": "x"}, "title"), ("notify", {"present": True, "default_off": False, "posts": 0, "ok": False}, "notify"),
                                ("logo", {"mode": "none", "ok": False}, "logo")):
            after = run_file("after", tasks={name: task(0, 0, **bad)})
            self.assertTrue([p for p in qa.verdict(run_file("before"), after) if p.startswith(text)], name)
        before = run_file("before", tasks={"logo": task(0, 0, mode="none", ok=False)})      # a broken logo in v0.21.0 is not the after run's fault
        self.assertEqual(qa.verdict(before, run_file("after")), [])

    def test_a_run_with_a_fail_and_an_after_task_that_did_not_finish_are_regressions(self):
        after = run_file("after")
        after["checks"]["fail"] = 2
        self.assertIn("after run has 2 FAIL", qa.verdict(run_file("before"), after))
        after = run_file("after", tasks={"limit": task(7, 0, done=False, error="stopped")})
        self.assertIn("limit: after did not finish", qa.verdict(run_file("before"), after))
        after = run_file("after", tasks={"routine": {**task(0, 0, done=False), "unable": "x"}})
        self.assertIn("routine: after cannot do what before did", qa.verdict(run_file("before"), after))

    def test_a_task_only_one_run_has_is_not_judged(self):
        before = run_file("before")
        before["tasks"].pop("limit")
        self.assertEqual(qa.verdict(before, run_file("after")), [])

    def test_the_table_has_the_rows_the_seconds_the_checks_and_the_last_line(self):
        text = qa.compare_table(run_file("before"), run_file("after"))
        for word in ("first", "limit", "routine", "blocked", "steps b", "first: longest wait for a thing to press", "home: first heading", "home: nothing loading", "12.00", "0.45",
                     "cold start; a false empty: no", "frame within 2 s on a cold start (target): yes", "title (after): 'VBear', ok", "notify (before): none in this version",
                     "notify (after): switch off by default: yes, POSTs sent: 0", "logo (after): image, ok", "380 px", "every task is no worse than before: yes"):
            self.assertIn(word, text, word)

    def test_a_slow_page_is_written_as_over_the_cap_and_never_as_zero(self):
        before = run_file("before")
        before["tasks"]["home"].update(h1_s=None, ready_s=None, slow=True)
        text = qa.compare_table(before, run_file("after"))
        self.assertIn(">90", text)
        self.assertIsNone(re.search(r"home: (first heading|nothing loading)\s+0\.00", text))

    def test_the_table_says_where_a_task_was_unable_failed_or_ended_in_a_dead_end(self):
        after = run_file("after", tasks={"first": {**task(2, 1, dead_end="the chat box cannot be used"), "unable": "no AI tool is ready"},
                                        "limit": task(7, 0, done=False, error="stopped here")})
        text = qa.compare_table(run_file("before"), after)
        self.assertIn("first (after): unable - no AI tool is ready", text)
        self.assertIn("limit (after): did not finish - stopped here", text)
        self.assertIn("first (after): dead end - the chat box cannot be used", text)

    def test_compare_prints_the_table_and_the_exit_code_follows_the_last_line(self):
        root = Path(tempfile.mkdtemp(prefix="q48"))
        self.addCleanup(shutil.rmtree, root, True)
        before, after = root / "b.json", root / "a.json"
        before.write_text(json.dumps(run_file("before")))
        after.write_text(json.dumps(run_file("after")))
        lines = []
        self.assertEqual(qa.compare(before, after, lines.append), 0)
        self.assertTrue(lines[-1].endswith("yes"))
        worse = run_file("after", tasks={"limit": task(9, 0)})
        after.write_text(json.dumps(worse))
        lines.clear()
        self.assertEqual(qa.compare(before, after, lines.append), 1)
        self.assertIn("limit: worse", lines[-1])

    def test_files_that_are_missing_in_the_wrong_order_or_the_wrong_shape_are_refused(self):
        root = Path(tempfile.mkdtemp(prefix="q48"))
        self.addCleanup(shutil.rmtree, root, True)
        good_b, good_a = root / "b.json", root / "a.json"
        good_b.write_text(json.dumps(run_file("before")))
        good_a.write_text(json.dumps(run_file("after")))
        for a, b in ((root / "no.json", good_a), (good_b, root / "no.json"), (good_a, good_b)):
            lines = []
            self.assertEqual(qa.compare(a, b, lines.append), 2)
            self.assertTrue(lines[0].startswith("refused:"))
        (root / "p47.json").write_text(json.dumps({"label": "before", "tasks": {"first": task(), "card": task()}, "checks": {"ok": 1, "warn": 0, "fail": 0}}))
        lines = []
        self.assertEqual(qa.compare(root / "p47.json", good_a, lines.append), 2)                 # a result of qa_p47 (it has a "card" task) is not one of this script's


class VersionReaderTests(unittest.TestCase):
    def serve(self, banner):
        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = banner
            sys_version = ""

            def do_GET(inner):
                inner.send_response(200)
                inner.send_header("Content-Type", "text/html")
                inner.send_header("Content-Length", "2")
                inner.end_headers()
                inner.wfile.write(b"ok")

            def log_message(inner, *a):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(5)
        self.addCleanup(stop)
        return server.server_address[1]

    def test_the_page_version_is_read_from_the_servers_banner(self):
        self.assertEqual(qa.read_ui_version(self.serve("VBear/0.21.0")), "v0.21")
        self.assertEqual(qa.read_ui_version(self.serve("VBear/0.22.0")), "v0.22")
        self.assertIsNone(qa.read_ui_version(self.serve("Other/1.0")))

    def test_a_port_nobody_listens_on_is_none(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        port = server.server_address[1]
        server.server_close()
        self.assertIsNone(qa.read_ui_version(port, timeout=2))


# ---- the clock of the page itself, under node, against a tiny stand-in for the page ----------------------------------------------------------

NODE_STAND_IN = r"""
const fs = require("fs");
const source = fs.readFileSync(0, "utf8");
let now = 0, main = true, h1 = null, loading = false, none = false, rows = false;
const timers = [], els = {}, shown = { getBoundingClientRect: () => ({ width: 10, height: 10 }) };
const doc = {
  getElementById: (id) => (id === "main" && main ? { querySelector: (s) => (s === "h1" ? h1 : (loading && s.indexOf("data-home-loading") >= 0 ? shown : null)) } : null),
  querySelector: (s) => (s === '[data-home="waiting-none"]' ? (none ? shown : null) : s === "[data-home-row]" ? (rows ? shown : null) : (els[s] || null)),
};
const win = {}; win.fetch = function () { return "fetched"; };
let observed = null;
function MO(cb) { this.observe = () => { observed = cb; }; }
const run = new Function("window", "document", "performance", "setTimeout", "setInterval", "MutationObserver", "URL", "location", source);
run(win, doc, { now: () => now }, (f) => { timers.push(f); }, () => 0, MO, URL, { href: "http://127.0.0.1:7803/" });
const q = win.__q;
const flush = () => { observed(); while (timers.length) timers.shift()(); };
const snap = (name, out) => out.push([name, JSON.parse(JSON.stringify(q.snapshot()))]);
const out = [];
now = 100; flush(); snap("empty", out);
h1 = {}; loading = true; els["[data-a]"] = shown; now = 300; flush(); snap("frame", out);
loading = false; now = 500; flush(); snap("ready", out);
win.fetch("/api/x?y=1", { method: "POST" }); win.fetch("/api/z"); win.fetch("/api/w", { method: "delete" }); win.fetch({ url: "/api/u", method: "PUT" });
snap("posts", out);
const old = h1; now = 1000; q.mark(); snap("marked", out);
h1 = {}; els["[data-b]"] = shown; now = 1200; flush(); snap("again", out);
none = true; flush(); rows = true; flush(); snap("false empty", out);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed")
class PageClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", NODE_STAND_IN], input=qa.observer_source(["[data-a]", "[data-b]", "[data-c]"]), capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-800:])
        cls.snaps = dict(json.loads(done.stdout))

    def test_nothing_is_timed_before_a_heading_is_in_main(self):
        s = self.snaps["empty"]
        self.assertIsNone(s["h1"])
        self.assertIsNone(s["ready"])
        self.assertEqual(s["first"], {})

    def test_the_first_heading_the_first_time_a_watched_thing_is_shown_and_nothing_loading_are_each_timed_once(self):
        self.assertEqual(self.snaps["frame"]["h1"], 300)
        self.assertEqual(self.snaps["frame"]["first"], {"[data-a]": 300})
        self.assertIsNone(self.snaps["frame"]["ready"])                     # a block is still loading
        self.assertTrue(self.snaps["frame"]["loadingSeen"])
        self.assertEqual(self.snaps["ready"]["ready"], 500)
        self.assertEqual(self.snaps["ready"]["h1"], 300)
        self.assertEqual(self.snaps["ready"]["first"], {"[data-a]": 300})

    def test_a_write_is_counted_by_method_and_path_only_and_a_read_is_not(self):
        self.assertEqual(self.snaps["posts"]["posts"], ["POST /api/x", "DELETE /api/w", "PUT /api/u"])

    def test_a_new_page_starts_the_clock_again_and_the_old_heading_does_not_count(self):
        self.assertIsNone(self.snaps["marked"]["h1"])
        self.assertEqual(self.snaps["marked"]["first"], {"[data-a]": 0})   # a thing already there is shown at once (0)
        self.assertEqual(self.snaps["again"]["h1"], 200)
        self.assertEqual(self.snaps["again"]["first"]["[data-b]"], 200)

    def test_nothing_waits_followed_by_a_row_is_a_false_empty(self):
        self.assertFalse(self.snaps["again"]["falseEmpty"])
        self.assertTrue(self.snaps["false empty"]["falseEmpty"])

    def test_the_source_reads_no_text_and_sends_no_value(self):
        text = qa.observer_source(["[data-a]"])
        for word in ("innerText", "textContent", "innerHTML", ".value", "body"):
            self.assertNotIn(word, text, word)


# ---- the run, over a fake page and console -----------------------------------------------------------------------------------------------

class RunTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="q48"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = make_state(self.root)
        self.events: list = []

    def build(self, label="after", tasks=qa.TASKS, **page_kw):
        pages, links = site(label)
        console = FakeConsole(events=self.events)
        ceo = lambda: console.profiles.append({"id": "prof-ceo", "name": "CEO", "model": {"tool": "claude"}})
        clicks = {qa.CEO_GO: ceo, q47.HOME_CEO_GO: ceo,
                  "[data-limit-save]": lambda: setattr(console, "daily", 5.0),
                  '[data-routine-action="save"]': lambda: console.routines.append({"id": "r-1", "name": "QA47 虛構早安", "enabled": True, "days": list(range(7)),
                                                                                   "times": ["08:00"]})}
        page_kw.setdefault("opens_at", "#/" if label == "after" else "#/setup")       # (v0.25: a fresh install opens on the home page, which does the first run itself)
        page = FakePage(pages, links, on_click=clicks, events=self.events, **page_kw)
        check = q47.Check(lambda line: None)
        walker = q47.Walker(page, {"avoid": ["派工"], "errors": []}, FakeClock(), lambda s: None)
        run = qa.Run(console, page, walker, self.state, label, False, 0.30, check, self.root, tasks, lambda port: qa.UI_OF[label], FakeClock(), lambda s: None)
        return run, page, console, check

    def walk(self, **kw):
        run, page, console, check = self.build(**kw)
        run.start()
        run.run_all()
        return run, page, console, check

    # the first, cold load

    def test_nothing_asks_the_console_before_the_first_cold_load_of_the_first_task(self):
        run, page, console, check = self.walk(tasks=("first",))
        order = [e for e in self.events]
        opened = next(i for i, e in enumerate(order) if e[:2] == ("page", "open"))
        self.assertEqual([e for e in order[:opened] if e[0] == "console"], [])
        self.assertEqual(run.cold, "first")
        self.assertTrue(run.first_load["cold"])
        self.assertGreater(len([e for e in order[opened:] if e[0] == "console"]), 0)

    def test_for_the_home_page_the_employee_and_the_done_mark_are_two_writes_made_before_the_cold_load_and_nothing_is_read(self):
        run, page, console, check = self.walk(tasks=("home",))
        order = self.events
        opened = next(i for i, e in enumerate(order) if e[:2] == ("page", "open"))
        before = [e for e in order[:opened] if e[0] == "console"]
        self.assertEqual(before, [("console", "POST", "/api/agent-profiles"), ("console", "POST", "/api/config")])
        self.assertTrue(console.config.get("setup_done"))
        self.assertEqual(run.cold, "home")
        self.assertTrue(run.tasks["home"]["cold"])

    def test_a_walk_that_does_not_begin_with_a_cold_task_is_written_as_warm(self):
        run, page, console, check = self.walk(tasks=("title", "logo"))
        self.assertIsNone(run.cold)
        self.assertEqual(run.first_load, {"cold": False})
        self.assertEqual(run.result()["cold"], None)

    # the first task

    def test_the_first_walk_is_four_steps_before_and_three_after_the_picker_press_being_the_look_at_claudes_row(self):
        # (v0.25: the home page makes the CEO itself, so the walk after has no separate 次一步 press: it is never more steps than before, which is what compare() reads)
        for label, steps, kinds in (("before", 4, ["look", "press", "press", "look"]), ("after", 3, ["press", "press", "look"])):
            self.events.clear()
            run, page, console, check = self.walk(label=label, tasks=("first",))
            t = run.tasks["first"]
            self.assertEqual((t["steps"], t["stuck"], t["done"]), (steps, 0, True), label)
            self.assertEqual([s["kind"] for s in run.w.steps], kinds, label)
            self.assertEqual(run.w.steps[0]["target"], qa.FIRST_TARGET[label])

    def test_each_page_the_person_lands_on_is_timed_to_its_first_thing_to_press_in_seconds(self):
        run, page, console, check = self.walk(label="before", tasks=("first",))
        pages = run.tasks["first"]["pages"]
        self.assertEqual([p["page"] for p in pages], ["#/setup", "#/ceo", "#/chat"])
        self.assertEqual(pages[0]["target_s"], 12.0)
        self.assertEqual(pages[0]["h1_s"], 11.9)
        self.assertEqual(run.tasks["first"]["blank_max_s"], 12.0)
        run, page, console, check = self.walk(label="after", tasks=("first",))
        self.assertEqual(run.tasks["first"]["pages"][0]["target_s"], 0.45)
        self.assertEqual(run.tasks["first"]["blank_max_s"], 0.45)
        self.assertEqual(run.first_load["target_s"], 0.45)

    def test_a_step_that_does_not_change_the_page_adds_no_wait(self):
        run, page, console, check = self.walk(label="after", tasks=("limit",))
        self.assertEqual(run.tasks["limit"]["steps"], 5)
        self.assertEqual(len(run.tasks["limit"]["pages"]), 4)             # the fill of the field and the press of 儲存 are on the page the person is already on

    def test_the_checklist_the_pick_opens_is_written_down_and_not_counted(self):
        run, page, console, check = self.walk(label="after", tasks=("first",))
        t = run.tasks["first"]
        self.assertEqual((t["checklist"], t["check_items"], t["change_pick"], t["chat_item"]), (True, 4, True, "fail"))
        self.assertEqual(t["steps"], 3)                 # (v0.25: 4 before the home page made the CEO itself)

    def test_a_page_that_never_draws_is_slow_and_has_no_number_and_the_run_goes_on(self):
        pages, links = site("before")
        pages["#/setup"] = {"_text": "", "_h1": None, "_ready": None}
        run, page, console, check = self.build(label="before", tasks=("first",))
        page.pages, page.links = pages, links
        run.start()
        run.run_all()
        self.assertTrue(run.first_load.get("slow"))
        self.assertIsNone(run.first_load["target_s"])
        self.assertTrue(run.tasks["first"]["unable"])                      # nothing to press: unable, with our own sentence (not a FAIL)
        self.assertEqual(check.failed, 0)
        self.assertEqual(run.tasks["first"]["slow_pages"], 1)

    def test_when_no_tool_is_ready_the_task_is_unable_and_the_start_up_is_marked_done_for_the_others(self):
        pages, links = site("after")
        pages["#/#picked"][q47.HOME_CEO_GO] = {"top": 500, "disabled": True}      # (v0.25: the button that makes the CEO is on the home page)
        run, page, console, check = self.build(label="after", tasks=("first",))
        page.pages, page.links = pages, links
        run.start()
        run.run_all()
        self.assertIn("no CEO can be made", run.tasks["first"]["unable"])
        self.assertTrue(console.config.get("setup_done"))
        self.assertEqual(check.failed, 0)

    def test_the_chat_a_ceo_page_opened_is_found_in_the_address_and_deleted_by_id_without_reading_the_chat_list(self):
        pages, links = site("after")
        links[("#/#picked", q47.HOME_CEO_GO)] = "#/chat/c-0123456789ab"
        pages["#/chat/c-0123456789ab"] = {qa.CHAT_INPUT: {"top": 300, "at": 100}, "_text": "和 CEO 的對話", "_h1": 50, "_ready": 50}
        run, page, console, check = self.build(label="after", tasks=("first",))
        page.pages, page.links = pages, links
        run.start()
        run.run_all()
        run.cleanup()
        self.assertEqual(run.chat, "c-0123456789ab")
        self.assertIn(("DELETE", "/api/chats/c-0123456789ab", None), console.log)
        self.assertNotIn("/api/chats", [c[1] for c in console.log])
        self.assertNotIn("/api/chat-support", [c[1] for c in console.log])         # reaching the box is noted, the console is not asked whether it can be used
        self.assertIsNone(run.dead_end)

    # the other tasks

    def test_the_home_page_is_timed_by_the_pages_own_clock_and_a_false_empty_is_written(self):
        pages, links = site("after")
        pages["#/setup"].update({"_h1": 180, "_ready": 900, "_false_empty": True})
        run, page, console, check = self.build(label="after", tasks=("home",))
        page.pages, page.links, page.opens_at = pages, links, "#/setup"
        run.start()
        run.run_all()
        t = run.tasks["home"]
        self.assertEqual((t["h1_s"], t["ready_s"], t["false_empty"], t["cold"]), (0.18, 0.9, True, True))
        self.assertEqual(check.failed, 1)                                  # a false empty is a FAIL of the walk (and the verdict names it too)

    def test_the_home_load_that_is_not_the_first_is_warm_and_makes_the_employee_once(self):
        run, page, console, check = self.walk(label="after", tasks=("title", "home"))
        self.assertFalse(run.tasks["home"]["cold"])
        self.assertEqual(sum(1 for c in console.log if c[:2] == ("POST", "/api/agent-profiles")), 1)

    def test_the_title_is_judged_with_nothing_waiting(self):
        run, page, console, check = self.walk(tasks=("title",))
        self.assertTrue(run.tasks["title"]["ok"])
        run, page, console, check = self.walk(tasks=("title",), title="(1) VBear")
        self.assertFalse(run.tasks["title"]["ok"])                        # nothing waits in a run with no model: a number would be a lie
        self.assertEqual(check.failed, 1)
        run, page, console, check = self.walk(tasks=("title",), title="VBear 阿明想動手")
        self.assertFalse(run.tasks["title"]["ok"])
        self.assertNotIn("阿明", json.dumps(run.tasks["title"], ensure_ascii=False))

    def test_the_notification_switch_is_pressed_once_it_is_off_before_and_no_post_is_sent(self):
        run, page, console, check = self.walk(label="after", tasks=("notify",))
        t = run.tasks["notify"]
        self.assertEqual((t["present"], t["default_off"], t["posts"], t["ok"], t["steps"]), (True, True, 0, True, 1))
        self.assertIn(("click", qa.NOTIFY_SWITCH), [e[:2] for e in page.log])

    def test_a_post_sent_by_pressing_the_switch_is_a_fail(self):
        pages, links = site("after")
        run, page, console, check = self.build(label="after", tasks=("notify",))
        page.on_click[qa.NOTIFY_SWITCH] = lambda: page.posts.append("POST /api/config")
        run.start()
        run.run_all()
        self.assertEqual(run.tasks["notify"]["posts"], 1)
        self.assertFalse(run.tasks["notify"]["ok"])
        self.assertEqual(check.failed, 1)

    def test_a_switch_that_is_on_before_it_is_pressed_is_not_the_default(self):
        pages, links = site("after")
        pages["#/settings"][qa.NOTIFY_SWITCH]["checked"] = True
        run, page, console, check = self.build(label="after", tasks=("notify",))
        page.pages = pages
        run.start()
        run.run_all()
        self.assertFalse(run.tasks["notify"]["default_off"])
        self.assertFalse(run.tasks["notify"]["ok"])

    def test_a_version_without_the_switch_says_none_and_is_not_a_fail(self):
        run, page, console, check = self.walk(label="before", tasks=("notify",))
        self.assertEqual((run.tasks["notify"]["present"], run.tasks["notify"]["ok"]), (False, True))
        self.assertEqual(check.failed, 0)

    def test_the_logo_is_the_one_seen_on_the_first_load(self):
        run, page, console, check = self.walk(tasks=("logo",))
        self.assertTrue(run.tasks["logo"]["ok"])
        run, page, console, check = self.walk(tasks=("logo",), logo={"mode": "image", "complete": True, "decoded": False})
        self.assertFalse(run.tasks["logo"]["ok"])
        self.assertEqual(check.failed, 1)
        run, page, console, check = self.walk(tasks=("logo",), logo={"mode": "text"})
        self.assertTrue(run.tasks["logo"]["ok"])

    def test_the_three_tasks_of_the_last_version_use_its_paths_in_both_versions(self):
        for label in ("before", "after"):
            run, page, console, check = self.walk(label=label, tasks=("limit",))
            self.assertEqual((run.tasks["limit"]["steps"], run.tasks["limit"]["done"]), (5, True), label)

    def test_without_a_model_nothing_asks_the_ai_tools_through_the_console(self):
        run, page, console, check = self.walk(tasks=qa.TASKS)
        paths = [c[1] for c in console.log]
        for forbidden in ("/api/chats", "/api/chat-support", "/api/chat-support/verify"):
            self.assertNotIn(forbidden, paths, forbidden)
        self.assertFalse([c for c in console.log if c[0] == "POST" and "verify" in c[1]])

    def test_the_label_that_does_not_match_the_served_page_stops_the_run(self):
        run, page, console, check = self.build(label="before", tasks=("title",))
        run.version_reader = lambda port: "v0.22"
        with self.assertRaises(q47.Stop):
            run.start()
        self.assertEqual(check.failed, 1)

    def test_the_other_versions_money_is_read_from_its_own_file_names(self):
        run, page, console, check = self.build(label="after", tasks=("title",))
        run.read_other()
        self.assertEqual(run.other_state, "none")
        (self.root / "started-before.txt").write_text("started\n")
        run.read_other()
        self.assertEqual(run.other_state, "unknown")
        (self.root / "qa48-before.json").write_text(json.dumps(run_file("before")))
        run.read_other()
        self.assertEqual(run.other_state, "known")
        (self.root / "qa48-before.json").write_text("{not json")
        run.read_other()
        self.assertEqual(run.other_state, "unknown")
        (self.root / "qa47-before.json").write_text(json.dumps(run_file("before")))              # the old script's file is not this one's
        (self.root / "qa48-before.json").unlink()
        run.read_other()
        self.assertEqual(run.other_state, "unknown")                                                # (the marker is still there)

    def test_the_phone_walk_reads_where_the_first_thing_to_press_is_and_goes_back_to_the_desktop(self):
        run, page, console, check = self.walk(label="after", tasks=("title",))
        page.pages["#/setup"] = {qa.PICK_CLAUDE: {"top": 380, "at": 50}, "_text": "開始設定"}
        page.links[("#/", qa.NAV_SETTINGS)] = "#/settings"
        run.phone_walk()
        self.assertEqual(run.phone["first_action_px"], 380)
        self.assertEqual(page.size, q47.DESKTOP)

    def test_the_phone_walk_forgets_the_pick_of_the_walk_before_it_and_loads_the_page_for_real_before_looking_for_the_picker(self):
        """P59-3: after the first task pressed 「選這個」 the setup page has no picker, so the phone walk used to find nothing."""
        run, page, console, check = self.walk(label="after", tasks=("title",))
        page.pages["#/setup"] = {qa.PICK_CLAUDE: {"top": 380, "at": 50}, "_text": "開始設定"}
        page.picked = True
        self.events.clear()
        run.phone_walk()
        self.assertEqual(run.phone["first_action_px"], 380)
        mine = [e[1:] for e in self.events if e[0] == "page" and e[1] in ("forget_pick", "open", "goto")]
        self.assertEqual(mine[:3], [("forget_pick",), ("open", "token"), ("goto", "#/setup")])

    def test_without_forgetting_the_pick_the_phone_walk_would_find_nothing(self):
        """The fake page is faithful to the bug: a remembered pick hides the picker, so the old walk read None."""
        run, page, console, check = self.walk(label="after", tasks=("title",))
        page.pages["#/setup"] = {qa.PICK_CLAUDE: {"top": 380, "at": 50}, "_text": "開始設定"}
        page.picked = True
        page.goto("#/setup")
        self.assertIsNone(page.box_top(qa.PICK_CLAUDE))

    def test_the_home_task_after_other_tasks_loads_the_page_for_real(self):
        """P59-3: with a task before it the tab is already on the console, so ``open`` has to be a load (see the real Page below), not a change after the #."""
        run, page, console, check = self.walk(label="after", tasks=("title", "home"))
        opens = [e for e in self.events if e[:2] == ("page", "open")]
        self.assertEqual(len(opens), 2)                             # the start's load, then the home page's own
        self.assertFalse(run.tasks["home"]["cold"])
        self.assertIsNotNone(run.tasks["home"]["h1_s"])


class FakeBrowser:
    """What ``Page`` talks to: it writes down each command and answers just enough for a page to settle. No Chrome is started."""

    def __init__(self):
        self.calls: list = []
        self.now = 0.0

    def clock(self):
        self.now += 0.5
        return self.now

    def call(self, method, params=None, session=None, wait=None):
        self.calls.append((method, params or {}))
        if method == "Target.createTarget":
            return {"targetId": "t-1"}
        if method == "Target.attachToTarget":
            return {"sessionId": "s-1"}
        if method == "Runtime.evaluate":
            return {"result": {"value": "same"}}
        return {}


class RealPageTests(unittest.TestCase):
    """P59-3, the real ``Page`` over a browser that only writes things down."""

    def make(self):
        browser = FakeBrowser()
        return qa.Page(browser, "http://127.0.0.1:7803", lambda s: None), browser

    def test_a_load_goes_through_a_blank_page_so_a_change_after_the_hash_is_a_real_load(self):
        page, browser = self.make()
        url = "http://127.0.0.1:7803/#auth=synthetic"
        page.open(url)
        navigated = [p["url"] for m, p in browser.calls if m == "Page.navigate"]
        self.assertEqual(navigated, ["about:blank", url])
        self.assertTrue(page.fresh)
        browser.calls.clear()
        page.open(url)                                              # the same address again, and again: still a blank page first
        self.assertEqual([p["url"] for m, p in browser.calls if m == "Page.navigate"], ["about:blank", url])

    def test_goto_is_still_a_change_of_the_hash_only(self):
        page, browser = self.make()
        page.goto("#/settings")
        self.assertEqual([p["url"] for m, p in browser.calls if m == "Page.navigate"], [])

    def test_forgetting_the_pick_removes_that_one_key_and_reads_nothing(self):
        page, browser = self.make()
        browser.calls.clear()
        page.forget_pick()
        expressions = [p["expression"] for m, p in browser.calls if m == "Runtime.evaluate"]
        self.assertEqual(len(expressions), 1)
        self.assertIn("localStorage.removeItem", expressions[0])
        self.assertIn(json.dumps("vbear-setup-pick"), expressions[0])
        self.assertNotIn("getItem", expressions[0])
        self.assertNotIn("clear()", expressions[0])
        self.assertEqual(qa.SETUP_PICK_KEY, "vbear-setup-pick")


# ---- the command line ------------------------------------------------------------------------------------------------------------------

class MainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="q48"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.chrome = self.root / "chrome"
        self.chrome.write_text("x")
        self.state = make_state(self.root)
        self.lines: list = []
        self.closed: list = []
        self.events: list = []
        self.console = FakeConsole(events=self.events)
        self.pages, self.links = site("after")
        self.page = FakePage(self.pages, self.links, opens_at="#/", events=self.events, on_click={
            qa.CEO_GO: lambda: self.console.profiles.append({"id": "prof-ceo", "name": "CEO", "model": {"tool": "claude"}}),
            q47.HOME_CEO_GO: lambda: self.console.profiles.append({"id": "prof-ceo", "name": "CEO", "model": {"tool": "claude"}}),
            "[data-limit-save]": lambda: setattr(self.console, "daily", 5.0),
            '[data-routine-action="save"]': lambda: self.console.routines.append(
                {"id": "r-1", "name": "QA47 虛構早安", "enabled": True, "days": list(range(7)), "times": ["08:00"]})})

    def go(self, *extra, label="after", ui="v0.22"):
        outer = self

        class Browser:
            def __init__(inner, chrome, profile):
                inner.profile = profile

            def close(inner):
                outer.closed.append(str(inner.profile))
        app = self.root / "app.js"
        app.write_text("const WORDS = {\n  a: { avoid: [\"派工\"], scope: \"all\" },\n};\nconst PLAIN_ERRORS = [\n  { re: /額度用完/ },\n];\n", encoding="utf-8")
        return qa.main(["--state", str(self.state), "--label", label, "--chrome", str(self.chrome), *extra], out=self.lines.append,
                       console_factory=lambda port, token: self.console, browser_factory=Browser, page_factory=lambda b, base: self.page,
                       sleep=lambda s: None, clock=FakeClock(), home=self.root, app_js=app, version_reader=lambda port: ui)

    def test_ports_of_the_persons_own_vbear_and_every_port_but_7803_and_a_cap_over_thirty_cents_are_refused_before_anything_starts(self):
        for extra in (("--port", "7788"), ("--port", "7789"), ("--port", "7802"), ("--port", "7795"), ("--claude-cap", "0.31")):
            self.lines.clear()
            self.assertEqual(self.go(*extra), 2, extra)
            self.assertTrue(self.lines[0].startswith("refused:"), extra)
        self.assertEqual(self.closed, [])
        self.assertEqual(self.page.log, [])
        self.assertEqual(self.events, [])

    def test_the_persons_own_state_folder_is_refused(self):
        own = self.root / ".vbear"
        own.mkdir()
        self.state = own
        self.assertEqual(self.go(), 2)
        self.assertIn("own VBear folder", self.lines[0])

    def test_a_bad_task_list_is_refused_before_anything_starts(self):
        self.assertEqual(self.go("--tasks", "home,photos"), 2)
        self.assertIn("unknown task", self.lines[0])
        self.assertEqual(self.page.log, [])

    def test_the_state_label_and_chrome_are_needed_haiku_and_no_ai_do_not_go_together_and_compare_needs_two_files(self):
        self.assertEqual(qa.main([], out=self.lines.append), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                qa.main(["--haiku", "--no-ai"], out=self.lines.append)
            with self.assertRaises(SystemExit):
                qa.main(["--compare", "only-one.json"], out=self.lines.append)

    def test_a_walk_with_no_model_passes_writes_a_result_that_compare_accepts_and_cleans_up(self):
        self.assertEqual(self.go(), 0, "\n".join(self.lines))
        data = json.loads((self.root / "qa48-after.json").read_text(encoding="utf-8"))
        self.assertTrue(qa.result_ok(data))
        self.assertEqual((data["label"], data["mode"], data["ui"], data["tool"]), ("after", "no-ai", "v0.22", "qa_p48"))
        self.assertEqual(data["tasks_run"], list(qa.TASKS))
        self.assertEqual(data["cold"], "first")
        self.assertEqual(data["tasks"]["first"]["steps"], 3)             # (v0.25: 4 before the home page made the CEO itself)
        self.assertEqual(data["tasks"]["notify"]["posts"], 0)
        self.assertEqual(data["money"]["claude_cap"], 0.30)
        self.assertEqual(self.console.profiles, [])                      # the employees it made are deleted
        self.assertEqual(self.console.daily, 3.0)                        # the limits are put back
        self.assertEqual(self.console.per_turn, 0.25)
        self.assertEqual(self.closed, [str(self.state.resolve().parent / "chrome-after")])
        self.assertTrue(self.lines[-1].startswith("qa_p48 (after, no-ai): PASS"), self.lines[-3:])

    def test_the_text_says_at_the_start_that_the_pages_read_the_chat_list_and_that_it_is_the_coordinators_call(self):
        self.go()
        self.assertIn("/api/chats", self.lines[0])
        self.assertIn("--version", self.lines[0])
        self.assertIn("coordinator", self.lines[0])
        self.assertIn("this script does not read it itself", self.lines[0])

    def test_nothing_a_model_wrote_and_not_the_token_is_printed_or_stored(self):
        self.pages["#/setup"]["_text"] = MODEL_WORDS
        self.assertEqual(self.go(), 0)
        blob = "\n".join(self.lines) + (self.root / "qa48-after.json").read_text(encoding="utf-8")
        self.assertNotIn(MODEL_WORDS, blob)
        self.assertNotIn(TOKEN, blob)

    def test_a_label_that_does_not_match_the_served_page_stops_the_run_with_a_fail_and_leaves_no_result(self):
        self.assertEqual(self.go(label="before"), 1)
        self.assertTrue([line for line in self.lines if line.startswith("FAIL")])
        self.assertFalse((self.root / "qa48-before.json").exists())
        self.assertEqual(self.console.profiles, [])

    def test_a_run_of_some_tasks_writes_only_those_and_a_start_marker_that_is_not_a_result_file(self):
        self.assertEqual(self.go("--tasks", "title,logo"), 0, "\n".join(self.lines))
        data = json.loads((self.root / "qa48-after.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(data["tasks"]), ["logo", "title"])
        self.assertTrue((self.root / "started-after.txt").is_file())
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.startswith("qa48")), ["qa48-after.json"])
        self.assertTrue((self.root / "shots48-after").is_dir())

    def test_haiku_is_off_by_default_and_never_posts_a_chat_check_when_it_is_not_asked_for(self):
        self.go()
        self.assertFalse([c for c in self.console.log if "chat-support" in c[1]])


# ---- the file itself -------------------------------------------------------------------------------------------------------------------

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def test_only_the_standard_library_is_imported_and_the_last_versions_script_is_imported_not_copied(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add((node.module or "").split(".")[0])
        stdlib = set(__import__("sys").stdlib_module_names)
        self.assertEqual(sorted(n for n in names if n not in stdlib), [])
        self.assertNotIn("vbear", names)
        self.assertTrue(str(q47.__file__).endswith("qa_p47.py"))
        self.assertIs(qa.Walker, q47.Walker)
        self.assertIs(qa.Browser, q47.Browser)
        self.assertIs(qa.Console, q47.Console)
        self.assertTrue(issubclass(qa.Run, q47.Run))
        self.assertTrue(issubclass(qa.Page, q47.Page))

    def test_no_tcp_debugging_port_and_nothing_in_the_persons_home_but_the_refusal(self):
        self.assertNotIn("remote-debugging-port", self.text.replace("no TCP debugging port", ""))
        self.assertNotIn("Path.home", self.text)
        self.assertEqual(len(re.findall(r"\.vbear", self.text.replace("~/.vbear", ""))), 0)
        for forbidden in ("os.system", "shell=True", "innerHTML", "/Applications/VBear", "pkill", "killall", "subprocess", "claude --version", "Popen"):
            self.assertNotIn(forbidden, self.text.replace("claude --version``, ``codex --version`` and ``agy --version", ""), forbidden)

    def test_the_only_routes_it_calls_are_the_ones_it_needs_and_the_chat_list_is_not_one_of_them(self):
        """Every string of the file that is a route: none is /api/chats or /api/chat-support (the pages read the chat list, the console then runs the
        AI tools' --version; this script does not ask for it). A chat is deleted by the id the page's address showed."""
        routes = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/api/") and len(node.value) < 60:
                routes.add(node.value.split("?")[0])
            elif isinstance(node, ast.JoinedStr):
                head = node.values[0] if node.values else None
                if isinstance(head, ast.Constant) and isinstance(head.value, str) and head.value.startswith("/api/"):
                    routes.add(head.value)
        self.assertEqual(sorted(routes), ["/api/agent-profiles", "/api/agent-profiles/", "/api/chats/", "/api/config", "/api/meetings/ledger", "/api/routines",
                                          "/api/routines/", "/api/setup/daily-limit"])
        self.assertNotIn("/api/chats", routes)
        self.assertNotIn("/api/chat-support", routes)

    def test_every_task_has_a_path_where_it_has_steps_in_both_versions(self):
        for label in qa.LABELS:
            for name in ("first", "limit", "routine", "blocked_find", "blocked_sent"):
                self.assertIn(name, qa.PATHS[label], f"{label} {name}")
                self.assertGreater(len(qa.PATHS[label][name]["steps"]), 0)
        self.assertEqual(qa.PATHS["before"]["limit"], q47.PATHS["after"]["limit"])
        self.assertEqual(qa.PATHS["after"]["routine"], q47.PATHS["after"]["routine"])

    def test_every_selector_is_a_data_attribute_an_href_an_id_or_the_dialog_class_and_no_screen_word(self):
        sels = list(qa.WATCHED)
        for label in qa.LABELS:
            for spec in qa.PATHS[label].values():
                for st in spec["steps"]:
                    sels += [st["sel"]] if isinstance(st["sel"], str) else list(st["sel"])
        for name in ("NOTIFY_SWITCH", "NOTIFY_RESULT", "NOTIFY_BLOCK", "CLAUDE_ROW", "PICK_CLAUDE", "CHECK_LIST", "CHANGE_PICK", "CHECK_CHAT", "CHECK_ITEMS"):
            sels.append(getattr(qa, name))
        self.assertGreater(len(sels), 40)
        for sel in sels:
            self.assertFalse(re.search(r"[^\x00-\x7f]", sel), sel)
            self.assertNotIn(":contains", sel)
            self.assertTrue(re.search(r"\[data-[a-z-]+|\[href|#[a-z]|\.modal", sel), sel)

    def test_the_sentences_it_types_and_the_names_it_saves_are_made_up_and_begin_with_qa48_or_qa47(self):
        self.assertTrue(qa.EMPLOYEE_NAME.startswith("QA48"))
        for label in qa.LABELS:
            for spec in qa.PATHS[label].values():
                for st in spec["steps"]:
                    if st["kind"] == "fill" and "value" in st:
                        self.assertTrue(st["value"].startswith("QA4") or st["value"].isdigit(), st["value"])

    def test_only_the_step_that_sends_something_is_marked_for_a_model(self):
        for label in qa.LABELS:
            for key, spec in qa.PATHS[label].items():
                for st in spec["steps"]:
                    if st.get("ai"):
                        self.assertEqual(key, "first", f"{label} {key}")

    def test_the_docstring_states_the_port_the_money_the_caps_the_chat_list_and_how_to_run_it(self):
        doc = qa.__doc__
        for needle in ("7803", "7788", "7789", "US$0.30", "--no-ai", "--haiku", "--compare", "--tasks", "20 minutes", "2 minutes", "5 minutes", "90 seconds",
                       "remote-debugging-pipe", "standard library only", "cold", "/api/chats", "--version", "coordinator", "never counted as zero", "QA48",
                       "needs the person's yes first", "ADR 0014", "qa48-<label>.json", "~/.vbear"):
            self.assertIn(needle, doc, needle)

    def test_the_caps_in_the_text_are_the_ones_in_the_code(self):
        self.assertEqual(qa.CLAUDE_CAP_MAX, q47.CLAUDE_CAP_MAX)
        self.assertEqual(q47.CLAUDE_CAP_MAX, 0.30)
        self.assertEqual(qa.WALL_CAP_S, 20 * 60)
        self.assertEqual(qa.SKELETON_TARGET_S, 2.0)


if __name__ == "__main__":
    unittest.main()
