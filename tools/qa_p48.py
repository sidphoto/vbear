#!/usr/bin/env python3
"""v0.22.0 real check of "easy start 2" (P48): the coordinator's before/after walk, v0.21.0 against v0.22.0, in a headless Chrome.

A developer check, never part of the product, **standard library only** (and the sibling ``qa_p47.py``, which this file imports and does not
change: its browser over a pipe, its console calls, its walker, its step counting and its money rules are reused as they are). It starts one
headless Chrome of its own, drives the console's page with the Chrome DevTools Protocol over a pipe (``--remote-debugging-pipe``; **no TCP
debugging port is opened**), walks the tasks below on two versions of VBear one after the other on the same port (``--label before`` on
v0.21.0, ``--label after`` on v0.22.0) and compares them (``--compare``).

Which port, which folders. **Port 7803 only**: any other port (7788 and 7789, the person's own VBear, first of all) is refused before anything
is read or started. The state folder (``--state``) must be a temporary one: ``~/.vbear`` and anything under it are refused. It writes
``<T>/qa48-<label>.json`` (numbers, the names of screenshot files and our own reasons: no conversation, no sentence a model wrote, never the
token) and ``<T>/shots48-<label>/*.png`` (``<T>`` is the folder that holds ``<state>``), uses ``<T>/chrome-<label>`` as the browser's own profile
and ``<T>/started-<label>.txt`` as a marker. The access token is read only from ``<state>/server.token``; it is never printed or stored. Every
name it makes begins with QA48 and is deleted at the end (the employees it made; the day's limit and the per-turn limit are put back).

The tasks (``--tasks a,b,c`` picks some; the default is all, in this order):

  first    the new person's first run: open, the start-up page, choose Claude (v0.21.0 has no picker: the person finds Claude's row; v0.22.0:
           one press of the card's button), the next step, create the CEO, and end at the box with the opening in it or at the one action of
           the prepare page. Counted like qa_p47 (a step is a press, a field filled, or one screen scrolled; stuck is a step with more than
           one screen of scrolling, a word of the vocabulary table's ``avoid`` lists or a known server sentence, or looking on another page);
           also kept for **each page the person lands on**: the seconds from the page being asked for to its first ``h1`` (``h1_s``), and to
           the thing to press being on the screen (``target_s``). The v0.22.0 picker is **one press that v0.21.0 does as a look at Claude's row**,
           so the count is the same by design (ADR 0014); the checklist the pick opens (and whether 「換一家」 is there) is read and written, not counted.
  home     the home page of a person who has an employee (one is made through the API: no model, no cost; ``setup_done`` is set): the seconds
           from the page being asked for to its first ``h1`` and to **no block being in "loading" any more** (``ready_s``), and whether
           「沒有要你決定的事」 ever showed and was then followed by a row (a false empty). v0.21.0 draws the page once all its answers are in
           (the real-machine walk of v0.21.0 saw 12 to 21 seconds of white); v0.22.0 draws its frame first (target: the frame within 2 seconds).
  title    the page's title with nothing waiting: ``VBear`` and nothing else (``--no-ai`` cannot make a chat card, so ``(N) VBear`` is only
           tested by tests/frontend/p48_home.cjs).
  notify   the settings page's 「通知」 switch: it is off by default; pressing it asks the browser (a headless Chrome usually refuses), the
           page says the result in plain words, and **no POST is sent** (a wrapper around ``fetch`` in this script's own tab counts them: method
           and path only, never a body). v0.21.0 has no such switch: recorded as "none".
  logo     the brand mark on the first load: an image that decoded, or the letters 「VB」 the page falls back to; not a broken picture.
  limit    regression: the day's limit set to US$5 by typing it (qa_p47's task 2; the paths of v0.21.0 and v0.22.0 are the same).
  routine  regression: a routine for every morning at 8 (qa_p47's task 3).
  blocked  regression: where the day's use and the limit are shown (qa_p47's task 5; ``--haiku``: what a person sees when the limit has stopped them).

Cold start. The first load is **cold** only when the first task is ``first`` or ``home`` and nothing has asked the console anything before it:
this script reads only ``<state>/server.token`` and starts Chrome; for ``home`` it first makes the employee and sets ``setup_done`` (two small
writes that do not wake the background program or read the AI tools). To get the cold home number, start a fresh console on a fresh state folder
and run ``--tasks home`` alone (the file says ``"cold": true``); ``--tasks first,title,notify,logo,...`` on another fresh one gives the cold start-up
page. A task that is not the first load is a warm one and is written as such.

THE PAGES READ ``/api/chats``, WHICH RUNS THE AI TOOLS' ``--version``. The home page, the start-up page and the chat pages of both versions read
``GET /api/chats``, and the console answers it by running ``claude --version``, ``codex --version`` and ``agy --version`` on this computer (it
adds the usual program folders to the search path, so a changed PATH does not stop it). Nothing is signed in, sent or spent by that, but it is a run
of the person's real AI tools. This script itself does not read ``/api/chats`` (``--no-ai``): it learns the chat of a CEO it made from the address
the page went to, and deletes by id. It does not read ``/api/chat-support`` either (qa_p47 does, to find a chat box that cannot be used; here
reaching the box is only noted). Whether to run it on a computer with real AI tools is the **coordinator's decision at the real-machine
walk**; the tests of this file start no browser and no console, and run nothing.

The money. ``--no-ai`` (the default) spends nothing. ``--haiku`` is off unless asked and **needs the person's yes first** (it spends their
plan): it is the only thing that uses Claude Code (the console runs it, on Haiku): the chat check of each state folder (kept at US$0.05) and one turn
under a per-turn limit of US$0.03. **The hard cap is US$0.30 (``--claude-cap``, never more):** before each step that spends, the script adds this
state folder's day in the ledger, the other version's day (the ``ledger_end`` of its result file), the chat check and the step's own limit, and does
not do the step, and records a FAIL, when that is over the cap; **an amount that is not known is never counted as zero** (qa_p47's rules, used as they
are). An administrator's setting can refuse the chat check on a computer (then Claude cost US$0).

Caps on time: 20 minutes for the whole run, 2 minutes for any one wait, 5 minutes for one Chrome (every command to the browser is refused once its
5 minutes are over; the Chrome is closed in every case), and **90 seconds for a cold first screen**: past that the page is written as slow (``slow``
and no number) and the run goes on; it is not a FAIL.

    python3 tools/qa_p48.py --state "$T/a" --port 7803 --label before --chrome "<path of Chrome>"      # --no-ai is the default
    python3 tools/qa_p48.py --state "$T/b" --port 7803 --label after  --chrome "<path of Chrome>"
    python3 tools/qa_p48.py --compare "$T/qa48-before.json" "$T/qa48-after.json"

Exit code 0 only when every check passed. ``--compare`` exits 0 only when both runs have no FAIL and the after run is no worse (steps, stuck, the
seconds of white and of loading, a false empty, the title, the switch, the logo).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _load_qa47():
    """``qa_p47.py`` of this folder, as it is (imported, not copied). Loaded by path so that the tests, which load this file by path too, find it."""
    found = sys.modules.get("qa_p47")
    if found is not None:
        return found
    spec = importlib.util.spec_from_file_location("qa_p47", Path(__file__).resolve().parent / "qa_p47.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_p47"] = module
    spec.loader.exec_module(module)
    return module


qa47 = _load_qa47()
Check, Stop, Unable, Console, Browser, Walker = qa47.Check, qa47.Stop, qa47.Unable, qa47.Console, qa47.Browser, qa47.Walker

FORBIDDEN_PORTS = qa47.FORBIDDEN_PORTS
DEFAULT_PORT = 7803                          # the one port this script may use
LABELS = qa47.LABELS
TASKS = ("first", "home", "title", "notify", "logo", "limit", "routine", "blocked")
STEP_TASKS = ("first", "limit", "routine", "blocked")
COLD_TASKS = ("first", "home")
CLAUDE_CAP_MAX = qa47.CLAUDE_CAP_MAX
PER_TURN_CLAUDE = qa47.PER_TURN_CLAUDE
WALL_CAP_S = qa47.WALL_CAP_S
COLD_CAP_S = 90.0                            # a cold first screen is waited for this long; past it the page is "slow", which is not a FAIL
ARRIVE_CAP_S = qa47.FIRST_LOAD_S             # a later page is waited for this long before the step is tried
NOISE_S = 0.25                               # a difference of seconds smaller than this is not a difference
SKELETON_TARGET_S = 2.0                      # the home page's frame within 2 seconds on a cold start (the plan's target)
DESKTOP, PHONE = qa47.DESKTOP, qa47.PHONE
TITLE_RE = re.compile(r"(\(\d{1,3}\) )?VBear")
EMPLOYEE_NAME = "QA48 虛構員工"
UI_OF = {"before": "v0.21", "after": "v0.22"}
CHATS_NOTE = ("note: the pages of both versions read /api/chats, which makes the console run the AI tools' --version on this computer; "
              "this script does not read it itself (--no-ai). Running it on a computer with real AI tools is the coordinator's decision.")

DIALOG_OK = qa47.DIALOG_OK
LEAVE = qa47.LEAVE
CEO_GO = qa47.CEO_GO
CHAT_INPUT = qa47.CHAT_INPUT
SEND = qa47.SEND
NOTIFY_SWITCH = '[data-setting="notify"]'
NOTIFY_RESULT = '[data-settings="notify-result"]'
NOTIFY_BLOCK = '[data-settings="notify"]'
NAV_SETTINGS = qa47.NAV_SETTINGS
CLAUDE_ROW = '[data-tool="claude"]'
PICK_CLAUDE = '[data-setup-pick-go="claude"]'
CHECK_LIST = '[data-setup="check-list"]'
CHANGE_PICK = '[data-setup="change-pick"]'
CHECK_CHAT = '[data-setup-check-item="chat"]'
CHECK_ITEMS = '[data-setup-check-item]'
FIRST_END = [CHAT_INPUT, '[data-chat="prep-action"]', '[data-chat="prep-reason"]']
FIRST_TARGET = {"before": CLAUDE_ROW, "after": PICK_CLAUDE}


def _regression_paths() -> dict:
    """The three v0.21.0 tasks that are walked again. The data attributes of these paths are the same in v0.21.0 and v0.22.0 (the plan says so
    and the sources agree), so both labels use qa_p47's v0.21.0 ("after") ones."""
    same = qa47.PATHS["after"]
    return {key: same[key] for key in ("limit", "routine", "blocked_find", "blocked_sent")}


_COMMON_FIRST = [
    {"kind": "press", "sel": LEAVE, "unable": "no AI tool is ready on this computer, so the next-step button stays off"},
    {"kind": "press", "sel": CEO_GO, "then": "ceo_made", "unable": "no CEO can be made (the AI tool is not ready for it)"},
    {"kind": "look", "sel": FIRST_END, "then": "chat_usable"},
    {"kind": "press", "sel": SEND, "ai": True, "then": "first_reply"},
]
PATHS = {
    "before": {
        "first": {"start": "#/", "steps": [{"kind": "look", "sel": CLAUDE_ROW}, *_COMMON_FIRST]},
        **_regression_paths(),
    },
    "after": {
        "first": {"start": "#/", "steps": [{"kind": "press", "sel": PICK_CLAUDE, "then": "picked"}, *_COMMON_FIRST]},
        **_regression_paths(),
    },
}

# What the page is asked to watch for, from the start: the first moment each of these is shown. Data attributes and ids only.
WATCHED = sorted({sel for table in PATHS.values() for spec in table.values() for st in spec["steps"]
                  for sel in ([st["sel"]] if isinstance(st["sel"], str) else st["sel"])} | {NOTIFY_BLOCK, NOTIFY_SWITCH, CHECK_LIST, CHANGE_PICK})


# ---- pure helpers (tested by tests/test_qa_p48.py) ----------------------------------------------------------------------------------

def refusal(state: str, port: int, cap: float = CLAUDE_CAP_MAX, label: str = "before", home: Path | None = None, chrome: str | None = None) -> str | None:
    """Why this run must not start, or None. Port 7803 only (7788 and 7789 are the person's own VBear); the rest (the state folder is not the
    person's own ``~/.vbear`` or under it and exists, a Claude cap of at most US$0.30, the label, the Chrome) is qa_p47's own rule, used as it is."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        return "the port must be 1024 to 65535"
    if port in FORBIDDEN_PORTS:
        return f"port {port} is the person's own VBear"
    if port != DEFAULT_PORT:
        return f"only port {DEFAULT_PORT} may be used (port {port} is kept for something else)"
    return qa47.refusal(state, qa47.DEFAULT_PORT, cap, label, home, chrome)


def parse_tasks(text) -> tuple | str:
    """``--tasks``: a comma list of task names, each once, in the order of TASKS. -> the tuple, or a sentence saying what is wrong."""
    if text is None or str(text).strip() == "":
        return TASKS
    names = [n.strip() for n in str(text).split(",")]
    unknown = [n for n in names if n not in TASKS]
    if unknown:
        return f"unknown task: {', '.join(unknown)} (the tasks are {', '.join(TASKS)})"
    if len(set(names)) != len(names):
        return "a task is named twice"
    return tuple(t for t in TASKS if t in names)


def title_ok(title) -> bool:
    """The page's title is ``VBear`` or ``(N) VBear``, with digits only: no name, no sentence."""
    return isinstance(title, str) and TITLE_RE.fullmatch(title) is not None


def logo_ok(obs) -> bool:
    """The brand mark is the letters the page falls back to, or an image that has loaded and decoded: not a broken picture."""
    if not isinstance(obs, dict):
        return False
    if obs.get("mode") == "text":
        return True
    return obs.get("mode") == "image" and obs.get("complete") is True and obs.get("decoded") is True


def notify_ok(obs) -> bool:
    """The switch is there, off until pressed, and pressing it sent no POST."""
    return isinstance(obs, dict) and obs.get("present") is True and obs.get("default_off") is True and obs.get("posts") == 0


def number(value) -> float | None:
    """A number of seconds as it is written in a result; anything else (a missing one, a word) is not a number."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value >= 0 else None


def blank_summary(pages: list) -> dict:
    """The seconds of white of one task from its pages (each ``{"page", "h1_s", "target_s", "slow"}``): the longest wait for a thing to press,
    the sum of those waits, and how many pages were slow (waited for past the cap)."""
    waits = [number(p.get("target_s")) for p in pages if isinstance(p, dict)]
    known = [w for w in waits if w is not None]
    return {"blank_max_s": round(max(known), 2) if known else None, "blank_total_s": round(sum(known), 2) if known else None,
            "slow_pages": sum(1 for p in pages if isinstance(p, dict) and p.get("slow"))}


def result_ok(data) -> bool:
    """Whether a result file has the shape ``--compare`` relies on: a label, at least one known task each with its numbers and whether it was
    finished, and the count of checks. Nothing in it is a sentence of a conversation."""
    if not isinstance(data, dict) or data.get("label") not in LABELS or not isinstance(data.get("tasks"), dict) or not data["tasks"]:
        return False
    checks = data.get("checks")
    if not isinstance(checks, dict) or not all(isinstance(checks.get(k), int) and not isinstance(checks.get(k), bool) for k in ("ok", "warn", "fail")):
        return False
    for name, t in data["tasks"].items():
        if name not in TASKS or not isinstance(t, dict) or not isinstance(t.get("steps"), int) or not isinstance(t.get("stuck"), int) \
                or not isinstance(t.get("done"), bool):
            return False
    return True


def _later(before, after) -> bool:
    """Whether ``after`` seconds are more than ``before`` by more than the noise. Not measured after (slow) is later than anything measured; not
    measured before cannot be compared."""
    b, a = number(before), number(after)
    if b is None:
        return False
    return a is None or a > b + NOISE_S


def verdict(before: dict, after: dict) -> list:
    """What is wrong with the pair, as short sentences; an empty list is "no worse". A run with a FAIL cannot be judged. The tasks with steps are
    judged like qa_p47's (an after task that did not finish, or cannot be done where before did it, is a regression; steps and stuck only for a
    task both finished). The seconds, the false empty, the title, the switch and the logo of the after run are judged by what they must be."""
    problems = []
    for label, data in (("before", before), ("after", after)):
        fails = (data.get("checks") or {}).get("fail") or 0
        if fails:
            problems.append(f"{label} run has {fails} FAIL")
    for name in STEP_TASKS:
        a, b = before["tasks"].get(name), after["tasks"].get(name)
        if a is None or b is None:
            continue
        sa, sb = qa47.task_state(a), qa47.task_state(b)
        if sb == "failed":
            problems.append(f"{name}: after did not finish")
        elif sb == "unable" and sa == "ok":
            problems.append(f"{name}: after cannot do what before did")
        elif sa == "failed":
            problems.append(f"{name}: before did not finish, so it cannot be compared")
        elif sa == "ok" and sb == "ok" and (b["steps"] > a["steps"] or b["stuck"] > a["stuck"]):
            problems.append(f"{name}: worse")
    a, b = before["tasks"].get("first"), after["tasks"].get("first")
    if a and b and qa47.task_state(a) == "ok" and qa47.task_state(b) == "ok" and _later(a.get("blank_max_s"), b.get("blank_max_s")):
        problems.append("first: a page stays white longer than before")
    a, b = before["tasks"].get("home"), after["tasks"].get("home")
    if b:
        if b.get("false_empty"):
            problems.append("home: after said nothing waits and then showed rows (a false empty)")
        if a and (_later(a.get("h1_s"), b.get("h1_s")) or _later(a.get("ready_s"), b.get("ready_s"))):
            problems.append("home: after is slower than before")
        if b.get("cold") and (number(b.get("h1_s")) is None or number(b.get("h1_s")) > SKELETON_TARGET_S):
            problems.append(f"home: the frame did not show within {SKELETON_TARGET_S:g} seconds on a cold start")
    b = after["tasks"].get("title")
    if b and not b.get("ok"):
        problems.append("title: after is not 'VBear' with nothing waiting")
    b = after["tasks"].get("notify")
    if b and not b.get("ok"):
        problems.append("notify: after has no switch, or it is on by default, or pressing it sent a POST")
    b = after["tasks"].get("logo")
    if b and not b.get("ok"):
        problems.append("logo: after shows a broken picture")
    return problems


def _secs(task: dict, key: str) -> str:
    if task.get("slow") and number(task.get(key)) is None:
        return f">{COLD_CAP_S:g}"
    value = number(task.get(key))
    return "-" if value is None else f"{value:.2f}"


def _cell(task: dict, key: str) -> str:
    return qa47._cell(task, key)


def compare_table(before: dict, after: dict) -> str:
    """The text ``--compare`` prints: the steps table (first, limit, routine, blocked), the seconds of white (first, home), the checks of the title,
    the switch and the logo, and the last line: every task is no worse than before, yes or NO with the reasons."""
    rows = [("task", "steps b", "steps a", "diff", "stuck b", "stuck a", "diff", "read b", "read a", "diff")]
    for name in STEP_TASKS:
        a, b = before["tasks"].get(name), after["tasks"].get(name)
        if a is None or b is None:
            continue
        rows.append((name, _cell(a, "steps"), _cell(b, "steps"), qa47._delta(a, b, "steps"), _cell(a, "stuck"), _cell(b, "stuck"), qa47._delta(a, b, "stuck"),
                     _cell(a, "read"), _cell(b, "read"), qa47._delta(a, b, "read")))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    secs = [("seconds", "before", "after")]
    for name, key, what in (("first", "blank_max_s", "first: longest wait for a thing to press"), ("first", "blank_total_s", "first: all waits added"),
                            ("first", "total_s", "first: the whole walk"), ("home", "h1_s", "home: first heading"), ("home", "ready_s", "home: nothing loading")):
        a, b = before["tasks"].get(name), after["tasks"].get(name)
        if a is not None or b is not None:
            secs.append((what, _secs(a or {}, key) if a else "not run", _secs(b or {}, key) if b else "not run"))
    if len(secs) > 1:
        w = [max(len(r[i]) for r in secs) for i in range(3)]
        lines.append("")
        lines += ["  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in secs]
    for name in STEP_TASKS:
        for label, data in (("before", before), ("after", after)):
            t = data["tasks"].get(name)
            if not t:
                continue
            if t.get("unable"):
                lines.append(f"{name} ({label}): unable - {t['unable']}")
            elif qa47.task_state(t) == "failed":
                lines.append(f"{name} ({label}): did not finish - {str(t.get('error') or 'no reason written')[:120]}")
            if t.get("dead_end"):
                lines.append(f"{name} ({label}): dead end - {t['dead_end']}")
    for label, data in (("before", before), ("after", after)):
        t = data["tasks"].get("home")
        if t:
            lines.append(f"home ({label}): {'cold' if t.get('cold') else 'warm'} start; a false empty: {'yes' if t.get('false_empty') else 'no'}")
    t = after["tasks"].get("home")
    if t and t.get("cold"):
        h1 = number(t.get("h1_s"))
        lines.append(f"home frame within {SKELETON_TARGET_S:g} s on a cold start (target): " + ("yes" if h1 is not None and h1 <= SKELETON_TARGET_S else "NO"))
    for name in ("title", "notify", "logo"):
        for label, data in (("before", before), ("after", after)):
            t = data["tasks"].get(name)
            if not t:
                continue
            if name == "title":
                lines.append(f"title ({label}): {t.get('title')!r}, {'ok' if t.get('ok') else 'not ok'}")
            elif name == "notify":
                lines.append(f"notify ({label}): " + ("none in this version" if not t.get("present") else
                             f"switch off by default: {'yes' if t.get('default_off') else 'NO'}, POSTs sent: {t.get('posts')}, answer in plain words: "
                             f"{'yes' if t.get('answered') else 'not within the wait'}"))
            else:
                lines.append(f"logo ({label}): {t.get('mode')}, {'ok' if t.get('ok') else 'BROKEN'}")
    for label, data in (("before", before), ("after", after)):
        px = (data.get("phone") or {}).get("first_action_px")
        lines.append(f"phone, the first thing to press on the start-up page from the top ({label}): " + ("not measured" if px is None else f"{px} px"))
    worse = verdict(before, after)
    lines.append("every task is no worse than before: " + ("yes" if not worse else "NO - " + "; ".join(worse)))
    return "\n".join(lines)


def compare(path_a: Path, path_b: Path, out=print) -> int:
    """``--compare a.json b.json``: print the table. 2 when a file cannot be read or has the wrong shape; 1 when after is worse or a run failed; else 0."""
    loaded = []
    for p in (path_a, path_b):
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out(f"refused: {Path(p).name} cannot be read")
            return 2
        if not result_ok(data):
            out(f"refused: {Path(p).name} is not a result of this script")
            return 2
        loaded.append(data)
    before, after = loaded
    if before["label"] != "before" or after["label"] != "after":
        out("refused: give the before file first and the after file second")
        return 2
    table = compare_table(before, after)
    out(table)
    return 0 if table.splitlines()[-1].endswith("yes") else 1


def read_ui_version(port: int, timeout: float = 10.0) -> str | None:
    """"v0.21" or "v0.22" from the ``Server: VBear/x.y.z`` header of the console's front page (a static file: no token, nothing is run), or None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as resp:
            header = resp.headers.get("Server") or ""
    except (urllib.error.URLError, OSError, ValueError):
        return None
    m = re.search(r"VBear/(\d+)\.(\d+)", header)
    return f"v{m.group(1)}.{m.group(2)}" if m else None


# ---- the page: Chrome over the pipe, plus the clock of the page itself ------------------------------------------------------------------

# Installed before any script of the page runs (Page.addScriptToEvaluateOnNewDocument): the page's own clock (performance.now() counts from the
# navigation) says when the first heading of ``main`` came, when nothing in it was "loading" any more, and when each watched thing was first
# shown, so that no polling of ours is part of the number. It looks at attributes and rectangles, never reads text, and counts the writes
# (method and path only) the page sends with ``fetch``.
JS_OBSERVER = r"""(function (sels) {
  if (window.__q) return;
  var q = window.__q = { t0: 0, base: null, h1: null, ready: null, first: {}, loadingSeen: false, noneSeen: false, falseEmpty: false, posts: [] };
  var shown = function (e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  var seen = function () {
    var now = performance.now() - q.t0, m = document.getElementById("main");
    if (m) {
      var h = m.querySelector("h1");
      if (q.h1 === null && h && h !== q.base) q.h1 = now;
      var waiting = m.querySelector('[data-home-loading],[data-home="loading-note"],[data-setup="loading"]');
      if (waiting) q.loadingSeen = true;
      if (q.h1 !== null && !waiting && q.ready === null) q.ready = now;
    }
    if (document.querySelector('[data-home="waiting-none"]')) q.noneSeen = true;
    if (q.noneSeen && document.querySelector('[data-home-row]')) q.falseEmpty = true;
    for (var i = 0; i < sels.length; i++) {
      if (!(sels[i] in q.first)) { var e = document.querySelector(sels[i]); if (e && shown(e)) q.first[sels[i]] = now; }
    }
  };
  var pending = false;
  var kick = function () { if (pending) return; pending = true; setTimeout(function () { pending = false; try { seen(); } catch (e) {} }, 0); };
  q.mark = function () {
    q.t0 = performance.now(); var m = document.getElementById("main"); q.base = m ? m.querySelector("h1") : null;
    q.h1 = null; q.ready = null; q.first = {}; q.loadingSeen = false; q.noneSeen = false; q.falseEmpty = false;
    try { seen(); } catch (e) {}
  };
  q.snapshot = function () { return { h1: q.h1, ready: q.ready, first: q.first, loadingSeen: q.loadingSeen, falseEmpty: q.falseEmpty, posts: q.posts.slice() }; };
  var f = window.fetch;
  if (typeof f === "function") {
    window.fetch = function (input, init) {
      try {
        var m = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
        if (m !== "GET" && m !== "HEAD") {
          var p = typeof input === "string" ? input : ((input && input.url) || "");
          try { p = new URL(p, location.href).pathname; } catch (e) {}
          q.posts.push(m + " " + p);
        }
      } catch (e) {}
      return f.apply(this, arguments);
    };
  }
  new MutationObserver(kick).observe(document, { childList: true, subtree: true, attributes: true, characterData: true });
  setInterval(kick, 50);
})(%s);"""
JS_MARK = """(() => { if (window.__q) window.__q.mark(); return true; })()"""
JS_SNAPSHOT = """(() => window.__q ? window.__q.snapshot() : null)()"""
JS_TITLE = """(() => document.title)()"""
JS_ATTR = """((sel, name) => { const e = document.querySelector(sel); return e ? e.getAttribute(name) : null; })(%s, %s)"""
JS_COUNT = """((sel) => document.querySelectorAll(sel).length)(%s)"""
JS_LOGO = """(async () => {
  const mark = document.querySelector(".brand-mark");
  if (!mark) return { mode: "none" };
  if (mark.getAttribute("data-brand") === "text") return { mode: "text" };
  const img = mark.querySelector("img");
  if (!img) return { mode: "none" };
  let decoded = false;
  try { await img.decode(); decoded = true; } catch (e) { decoded = false; }
  const tries = performance.getEntriesByType("resource").filter((r) => r.name.indexOf("/logo.svg") >= 0).length;
  return { mode: "image", complete: !!img.complete, decoded, tries, retried: (img.getAttribute("src") || "").indexOf("r=1") >= 0 };
})()"""


def observer_source(sels) -> str:
    return JS_OBSERVER % json.dumps(list(sels))


class Page(qa47.Page):
    """qa_p47's page plus the clock of the page itself. ``fresh`` says a new page was asked for (a load, an address, a press) and its arrival has not
    been written down yet."""

    def __init__(self, browser, base: str, sleep=time.sleep):
        super().__init__(browser, base, sleep)
        self.fresh = False

    def install(self, sels=WATCHED) -> None:
        self.b.call("Page.addScriptToEvaluateOnNewDocument", {"source": observer_source(sels)}, session=self.session)

    def mark(self) -> None:
        self.ev(JS_MARK)
        self.fresh = True

    def open(self, url: str) -> None:
        self.fresh = True                                # a load: the page's own clock starts at the navigation
        super().open(url)

    def goto(self, hash_: str) -> None:
        self.mark()
        super().goto(hash_)

    def click(self, sel: str) -> bool:
        self.mark()
        return super().click(sel)

    def timing(self) -> dict:
        return self.ev(JS_SNAPSHOT) or {}

    def title(self) -> str:
        return str(self.ev(JS_TITLE) or "")

    def attr(self, sel: str, name: str):
        return self.ev(JS_ATTR % (json.dumps(sel), json.dumps(name)))

    def count(self, sel: str) -> int:
        return int(self.ev(JS_COUNT % json.dumps(sel)) or 0)

    def logo(self) -> dict:
        return self.ev(JS_LOGO) or {"mode": "none"}


# ---- the run ---------------------------------------------------------------------------------------------------------------------------

def page_head(route: str) -> str:
    return qa47.page_head(route)


class Run(qa47.Run):
    def __init__(self, console, page, walker, state: Path, label: str, haiku: bool, cap: float, check: Check, out_dir: Path,
                 tasks=TASKS, version_reader=read_ui_version, clock=time.monotonic, sleep=time.sleep):
        super().__init__(console, page, walker, state, label, haiku, cap, check, out_dir, clock, sleep)
        self.todo = tuple(tasks)
        self.version_reader = version_reader
        self.shot_dir = self.out_dir / f"shots48-{label}"
        self.cold = None                      # the task whose first load was the cold one (None: nothing was cold)
        self.first_load = {}
        self.carry: list = []                 # the pages of the cold first load, kept for the task that begins with it
        self.pages: list = []
        self.home_employee = False
        self.logo_first = None
        self.checklist: dict = {}
        self.cold_home: dict = {}
        self.cold_began = None
        self.first_seconds = None

    # -- the start -------------------------------------------------------------------------------------------------------------------

    def url(self) -> str:
        return f"http://127.0.0.1:{self.c.port}/#auth={self.c.token}"

    def prepare_home(self) -> None:
        """An employee through the API (no model, no cost) and the start-up marked done: what a person who has finished setting up has. Two small
        writes; neither wakes the background program nor reads the AI tools."""
        if self.home_employee:
            return
        code, data = self.c.call("/api/agent-profiles", "POST", {"name": EMPLOYEE_NAME, "position": "executor", "instructions": "QA48 虛構",
                                                                 "launch_mode": "safe", "model": {"tool": "claude", "model_id": "haiku"}})
        pid = (((data or {}).get("profile") or {}).get("id")) if code in (200, 201) and isinstance(data, dict) else None
        if not isinstance(pid, str):
            raise Stop("an employee for the home page could not be made: is the console running on that state folder?")
        self.made["profiles"].append(pid)
        self.home_employee = True
        self.c.ok("/api/config", "POST", {"setup_done": True, "welcome_seen": True})

    @staticmethod
    def _sec(ms):
        """Milliseconds of the page's clock as seconds (3 places), or None when there is no number."""
        n = number(ms)
        return None if n is None else round(n / 1000.0, 3)

    def note_arrival(self, sels, cap: float = ARRIVE_CAP_S) -> None:
        """When a new page has been asked for: wait (up to ``cap``) for the thing the next step needs, and write down the page's own seconds to
        its first heading and to that thing. Nothing is written for a step that stays on the same page."""
        if not getattr(self.page, "fresh", False):
            return
        self.page.fresh = False
        sels = [sels] if isinstance(sels, str) else list(sels)
        end = self.clock() + cap
        while True:
            t = self.page.timing()
            first = t.get("first") or {}
            seen = [first[s] for s in sels if s in first]
            if seen or self.clock() >= end or self.over():
                break
            self.sleep(0.1)
        entry = {"page": page_head(self.page.route()), "h1_s": self._sec(t.get("h1")), "ready_s": self._sec(t.get("ready"))}
        if seen:
            entry["target_s"] = self._sec(min(seen))
        else:
            entry["target_s"], entry["slow"] = None, True
        self.pages.append(entry)

    def home_load(self, cap: float) -> dict:
        """After a full load of the home page: wait (up to ``cap``) until nothing in it is loading, and read the page's own seconds."""
        end = self.clock() + cap
        while True:
            t = self.page.timing()
            if t.get("ready") is not None or self.clock() >= end or self.over():
                break
            self.sleep(0.1)
        out = {"h1_s": self._sec(t.get("h1")), "ready_s": self._sec(t.get("ready")), "false_empty": bool(t.get("falseEmpty")),
               "loading_seen": bool(t.get("loadingSeen"))}
        if out["h1_s"] is None or out["ready_s"] is None:
            out["slow"] = True
        return out

    def start(self) -> None:
        first = self.todo[0]
        self.page.viewport(*DESKTOP)
        self.page.install()
        if first == "home":
            self.prepare_home()                                   # two writes, before the first load: neither wakes anything
        if first in COLD_TASKS:
            self.cold = first
            self.cold_began = self.clock()
            self.page.open(self.url())
            if first == "first":
                self.note_arrival(FIRST_TARGET[self.label], COLD_CAP_S)
                self.carry = list(self.pages)
                self.first_load = {"cold": True, "task": "first", **(self.pages[-1] if self.pages else {})}
            else:
                self.cold_home = self.home_load(COLD_CAP_S)
                self.first_load = {"cold": True, "task": "home", **self.cold_home}
            self.logo_first = self.page.logo()
            self.shot("0-first-load")
        else:
            self.page.open(self.url())
            self.page.settle(1.0)
            self.logo_first = self.page.logo()
            self.first_load = {"cold": False}
        self.page.settle()
        # from here on the console may be asked (the first load is over)
        ledger = self.c.call("/api/meetings/ledger")
        if ledger[0] != 200 or not isinstance(ledger[1], dict):
            raise Stop("the ledger cannot be read: is the console running on that state folder?")
        conf = self.c.ok("/api/config").get("config") or {}
        limits = conf.get("chat_limits") if isinstance(conf.get("chat_limits"), dict) else {}
        self.orig = {"daily": qa47.money(ledger[1].get("daily_usd")), "per_turn": limits.get("per_turn_usd"),
                     "profiles": {p.get("id") for p in self.profiles()},
                     "routines": {r.get("id") for r in (self.c.ok("/api/routines").get("routines") or []) if isinstance(r, dict)}}
        self.ui = self.version_reader(self.c.port) or "?"
        if not self.check.expect(self.ui == UI_OF[self.label], f"the page is the {UI_OF[self.label]} one that --label {self.label} means", f"saw {self.ui}"):
            raise Stop("the label does not match the version the console serves")
        self.c.ok("/api/setup/daily-limit", "POST", {"daily_usd": qa47.DAILY_START})
        self.c.ok("/api/config", "POST", {"chat_limits": {"per_turn_usd": PER_TURN_CLAUDE}, "welcome_seen": True})
        self.check.ok("the day's limit is US$2.00 and the per-turn limit US$0.03 (put back at the end)")
        self.check.ok("the first load was " + ("cold: nothing asked the console before it" if self.cold else "warm: it was not the first task"))
        self.read_other()
        self.mark_started()
        if self.haiku:
            self.verify_chat()

    def read_other(self) -> None:
        """What the other version spent (qa_p47's rule, with this script's file names): its result is read and has to hold a readable amount of
        money; without one, its start marker says whether it ever began (then the amount is unknown), and if it did not this is the first of the pair."""
        other = self.other_label()
        path = self.out_dir / f"qa48-{other}.json"
        if not os.path.lexists(path):
            self.other, self.other_state = None, ("unknown" if (self.out_dir / f"started-{other}.txt").exists() else "none")
        else:
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = None
            if data is None:
                self.other, self.other_state = None, "unknown"
            else:
                self.other = data
                self.other_state = "known" if result_ok(data) and data.get("label") == other and qa47.money((data.get("money") or {}).get("ledger_end")) is not None else "unknown"
        if self.other_state == "unknown":
            self.check.warn(f"what the {other} run spent is not known, so no step that spends Claude's money will be done")

    # -- the tasks -----------------------------------------------------------------------------------------------------------------

    def run_all(self) -> None:
        for n, name in enumerate(self.todo, 1):
            if self.over():
                self.check.fail("the 20 minutes of the whole run are over", name)
                self.tasks[name] = {**qa47.summarize([], "the time cap of the run"), "error": "time cap"}
                continue
            self.w.steps = []
            self.pages = list(self.carry) if name == "first" else []
            began = self.clock()
            try:
                getattr(self, f"task_{name}")()
            except Unable as exc:
                self.tasks[name] = {**qa47.summarize(self.w.steps, str(exc))}
                self.check.ok(f"task {n} {name}: unable here", str(exc))
            except Stop as exc:
                self.tasks[name] = {**qa47.summarize(self.w.steps), "done": False, "error": str(exc)[:160]}
                self.check.fail(f"task {n} {name}: stopped", str(exc)[:160])
            else:
                t = self.tasks[name]
                self.check.ok(f"task {n} {name}", f"{t['steps']} steps, {t['stuck']} stuck")
            if isinstance(self.tasks.get(name), dict):
                self.tasks[name]["end_page"] = page_head(self.page.route())
                if name in STEP_TASKS:
                    self.tasks[name].update(blank_summary(self.pages))
                    self.tasks[name]["pages"] = list(self.pages)
                if name == "first":
                    self.tasks[name].update(self.checklist)
                    self.tasks[name]["total_s"] = self.first_seconds
                    if self.dead_end:
                        self.tasks[name]["dead_end"] = self.dead_end
            self.shot(f"{n}-{name}")

    def play(self, key: str, name: str | None = None, begin: bool = True) -> None:
        spec = PATHS[self.label][key]
        start = spec["start"]
        if start == "chat":
            if not self.chat:
                self.find_chat()
            if not self.chat:
                raise Unable("there is no conversation with a CEO to start from (it needs a model: --haiku)")
            start = f"#/chat/{self.chat}"
        if begin:
            self.w.begin(start)
        else:
            self.w.steps = []
            self.w.route_seen = self.page.route()
            self.page.to_top()
        unable = ""
        for st in spec["steps"]:
            if st.get("ai") and not self.haiku:
                break
            if self.over():
                raise Stop("the time cap of the run")
            if st.get("ai") and not self.money_ok(PER_TURN_CLAUDE):
                self.check.fail("the Claude cap would be passed by this step: not done", st.get("sel", ""))
                raise Unable("the Claude cap would have been passed")
            kind, sel = st["kind"], st["sel"]
            if st.get("optional") and not self.w.present(sel):
                continue
            self.note_arrival(sel)
            if kind == "press":
                got = self.w.press(sel)
                if got is None:
                    raise Unable(st.get("unable") or f"{sel} is not on the page")
                if got.get("disabled"):
                    raise Unable(st.get("unable") or f"{sel} is switched off")
            elif kind == "fill":
                if self.w.fill(sel, st["value"]) is None:
                    raise Unable(f"{sel} is not on the page")
            elif kind == "ensure":
                if self.w.ensure(sel) is None:
                    raise Unable(f"{sel} is not on the page")
            elif kind == "look":
                got, found = self.w.look(sel)
                self.last_look = found
                if got is None:
                    raise Unable(f"{sel if isinstance(sel, str) else ' / '.join(sel)} is not on the page")
            elif kind == "search":
                got, found = self.w.search(sel)
                if not found and st.get("unable"):
                    raise Unable(st["unable"])
            if st.get("then"):
                getattr(self, f"then_{st['then']}")()
        self.tasks[name or key] = self.w.summary(unable)

    def task_first(self) -> None:
        began = self.cold_began if self.cold == "first" and self.cold_began is not None else self.clock()
        try:
            self.play("first", begin=self.cold != "first")
        except Unable:
            self.c.call("/api/config", "POST", {"setup_done": True})           # nothing can be done without a ready tool: the other tasks begin at the home page
            raise
        finally:
            self.first_seconds = round(self.clock() - began, 2)

    def then_picked(self) -> None:
        """v0.22.0: the checklist the pick opened. Written down (the number of items, whether 「換一家」 is there, what the chat item says), not counted."""
        self.page.settle()
        have = self.w.present(CHECK_LIST, 3.0)
        self.checklist = {"checklist": bool(have), "check_items": self.page.count(CHECK_ITEMS) if have else 0,
                          "change_pick": self.w.present(CHANGE_PICK, 1.0), "chat_item": self.page.attr(CHECK_CHAT, "data-result")}
        self.check.expect(have, "the pick opened the checklist", f"{self.checklist['check_items']} items")

    def then_ceo_made(self) -> None:
        """The CEO the page made. Without a model the chat's id is read from the address the page went to (a chat that exists is deleted by id at the
        end); ``/api/chats`` is not read (the console would run the AI tools' --version for it)."""
        if self.haiku:
            return super().then_ceo_made()
        pid = self.wait("the CEO card", self.new_profile, cap=15, every=0.5)
        self.ceo = pid
        self.made["profiles"].append(pid)
        self.page.settle()
        m = re.fullmatch(r"#/chat/(c-[0-9a-f]+)", str(self.page.route()).split("?")[0])
        if m:
            self.chat = m.group(1)
            self.made["chats"].append(self.chat)

    def then_chat_usable(self) -> None:
        """qa_p47 asks the console for the chat support here (the console runs the AI tools' --version for it). Without a model this script does not:
        the pages of v0.21.0 and v0.22.0 open a chat only when it can be used, so reaching the box is written as a note, not read from the console."""
        self.dead_end = None
        if self.haiku or self.last_look != CHAT_INPUT:
            return
        self.check.warn("task 1 ends in the chat box; whether the chat can be used is not read from the console (it would run the AI tools' --version)")

    def task_home(self) -> None:
        if self.cold == "home":
            m = dict(self.cold_home)
            m["cold"] = True
        else:
            self.prepare_home()
            self.page.open(self.url())
            m = {**self.home_load(COLD_CAP_S), "cold": False}
        self.tasks["home"] = {**qa47.summarize([]), **m}
        self.check.expect(m.get("h1_s") is not None, "the home page drew its first heading", "slow" if m.get("slow") else f"{m.get('h1_s')} s")
        self.check.expect(not m.get("false_empty"), "the home page never said nothing waits and then showed a row")

    def task_title(self) -> None:
        self.page.goto("#/")
        self.page.settle()
        title = self.page.title()
        ok = title == "VBear"
        self.tasks["title"] = {**qa47.summarize([]), "title": title if title_ok(title) else "(not of the form VBear or (N) VBear)", "ok": ok}
        self.check.expect(ok, "the title is VBear with nothing waiting", title if title_ok(title) else "other")

    def task_notify(self) -> None:
        self.page.goto("#/settings")
        self.page.settle()
        if not self.w.present(NOTIFY_BLOCK, 4.0):
            self.tasks["notify"] = {**qa47.summarize([]), "present": False, "ok": True, "note": "none in this version"}
            self.check.ok("no notification switch in this version", self.ui)
            return
        self.w.steps = []
        default_off = self.page.checked(NOTIFY_SWITCH) is False
        before = len(self.page.timing().get("posts") or [])
        self.w.press(NOTIFY_SWITCH)
        answered, end = "", self.clock() + 8.0
        while self.clock() < end:                                   # the answer of a headless Chrome comes at once or not at all
            answered = self.page.text_of(NOTIFY_RESULT).strip()
            if answered and not self.page.ev("(() => { const e = document.querySelector(%s); return !!(e && e.disabled); })()" % json.dumps(NOTIFY_SWITCH)):
                break
            self.sleep(0.3)
        posts = len(self.page.timing().get("posts") or []) - before
        if self.page.checked(NOTIFY_SWITCH):
            self.page.click(NOTIFY_SWITCH)                          # left as it was found
        self.tasks["notify"] = {**self.w.summary(), "present": True, "default_off": default_off, "posts": posts, "answered": bool(answered),
                                "answer_chars": len(answered)}
        self.tasks["notify"]["ok"] = notify_ok(self.tasks["notify"])
        self.check.expect(default_off, "the notification switch is off by default")
        self.check.expect(posts == 0, "pressing the switch sent no POST", f"{posts}")

    def task_logo(self) -> None:
        obs = self.logo_first if isinstance(self.logo_first, dict) else self.page.logo()
        ok = logo_ok(obs)
        self.tasks["logo"] = {**qa47.summarize([]), "mode": obs.get("mode"), "ok": ok, "tries": obs.get("tries"), "retried": obs.get("retried")}
        self.check.expect(ok, "the brand mark on the first load is a picture that loaded, or the letters it falls back to", str(obs.get("mode")))

    # the three regression tasks are qa_p47's own methods (``self.play`` reads this file's paths)

    def phone_walk(self) -> None:
        self.page.viewport(*PHONE)
        try:
            self.page.goto("#/setup")
            self.page.settle()
            top = self.page.box_top(FIRST_TARGET[self.label])
            self.phone["first_action_px"] = top if isinstance(top, int) else None
            self.shot("phone-setup")
            self.page.goto("#/")
            self.shot("phone-home")
            self.phone["size"] = f"{PHONE[0]}x{PHONE[1]}"
        finally:
            self.page.viewport(*DESKTOP)

    def cleanup(self) -> None:
        """Delete what this run made and put the two limits back. The chats are deleted by the ids the run saw (``/api/chats`` is not read)."""
        def drop(path, method="POST", body=None):
            code, _ = self.c.call(path, method, body)
            return code in (200, 201, 202, 204, 404)
        code, data = self.c.call("/api/routines")
        for r in ((data or {}).get("routines") or []) if code == 200 and isinstance(data, dict) else []:
            if isinstance(r, dict) and r.get("id") in self.made["routines"] and r.get("id") not in self.orig.get("routines", set()):
                drop(f"/api/routines/{r.get('id')}/delete", "POST", {})
        for cid in self.made["chats"]:
            drop(f"/api/chats/{cid}", "DELETE")
        for pid in self.made["profiles"]:
            drop(f"/api/agent-profiles/{pid}/delete", "POST", {})
        if self.orig.get("daily") is not None:
            self.c.call("/api/setup/daily-limit", "POST", {"daily_usd": self.orig["daily"]})
        if self.orig.get("per_turn") is not None:
            self.c.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": self.orig["per_turn"]}})

    def result(self) -> dict:
        data = super().result()
        data.update({"tool": "qa_p48", "cold": self.cold, "first_load": self.first_load, "tasks_run": list(self.todo)})
        return data


def main(argv=None, out=print, console_factory=Console, browser_factory=Browser, page_factory=Page, clock=time.monotonic, sleep=time.sleep,
         home: Path | None = None, app_js: Path | None = None, version_reader=read_ui_version) -> int:
    ap = argparse.ArgumentParser(description="v0.22.0 real check of easy start 2 (see the file's docstring)")
    ap.add_argument("--state", help="the temporary state folder of the console (VBEAR_HOME)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="the console's port (7803 only)")
    ap.add_argument("--label", choices=LABELS, help="which version this console serves: before (v0.21.0) or after (v0.22.0)")
    ap.add_argument("--chrome", help="the path of the Chrome program")
    ap.add_argument("--tasks", help="a comma list of tasks (default all): " + ", ".join(TASKS))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--no-ai", action="store_true", help="spend nothing (the default)")
    mode.add_argument("--haiku", action="store_true", help="also use Claude Code on Haiku (off unless asked; the person's yes first; hard cap US$0.30)")
    ap.add_argument("--claude-cap", type=float, default=CLAUDE_CAP_MAX, help="the most Claude's part may cost (at most 0.30)")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE_JSON", "AFTER_JSON"), help="print the table of two result files")
    args = ap.parse_args(argv)
    if args.compare:
        return compare(Path(args.compare[0]), Path(args.compare[1]), out)
    if not (args.state and args.label and args.chrome):
        out("refused: --state, --label and --chrome are needed")
        return 2
    why = refusal(args.state, args.port, args.claude_cap, args.label, home, args.chrome)
    if why:
        out(f"refused: {why}")
        return 2
    todo = parse_tasks(args.tasks)
    if isinstance(todo, str):
        out(f"refused: {todo}")
        return 2
    state = Path(args.state).expanduser().resolve()
    work = state.parent
    check = Check(out)
    out(CHATS_NOTE)
    tables = qa47.read_tables(app_js or Path(__file__).resolve().parent.parent / "web" / "app.js")
    if tables.get("why"):
        check.warn("the vocabulary tables were not read, so no word is judged", tables["why"])
    browser = run = None
    try:
        console = console_factory(args.port, qa47.read_token(state, args.port))
        browser = browser_factory(args.chrome, work / f"chrome-{args.label}")
        page = page_factory(browser, f"http://127.0.0.1:{args.port}")
        run = Run(console, page, Walker(page, tables, clock, sleep), state, args.label, bool(args.haiku), args.claude_cap, check, work, todo,
                  version_reader, clock, sleep)
        run.start()
        run.run_all()
        run.phone_walk()
    except Stop as exc:
        check.fail("stopped", str(exc)[:160])
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, StopIteration) as exc:
        check.fail("unexpected", f"{type(exc).__name__}: {str(exc)[:120]}")
    finally:
        if run is not None:
            try:
                run.cleanup()
                run.final()
            except (Stop, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                check.fail("cleanup", f"{type(exc).__name__}: {str(exc)[:120]}")
        if browser is not None:
            browser.close()
    if run is not None and len(run.tasks) == len(todo):
        try:
            (work / f"qa48-{args.label}.json").write_text(json.dumps(run.result(), ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            check.fail("the result file could not be written", str(exc)[:80])
    out(f"qa_p48 ({args.label}, {'haiku' if args.haiku else 'no-ai'}): {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
