#!/usr/bin/env python3
"""v0.21.0 real check of the plain navigation (P47): the coordinator's before/after walk of five tasks in a headless Chrome.

A developer check, never part of the product, and **standard library only**. It starts one headless Chrome of its own, drives the
console's page with the Chrome DevTools Protocol over a pipe (``--remote-debugging-pipe``: the commands go in on file descriptor 3 and
come out on 4, each message ended by a NUL byte; **no TCP debugging port is opened**), and walks the same five tasks on two versions
of VBear, one after the other on the same port (``--label before`` on v0.20.0, ``--label after`` on v0.21.0), then compares them
(``--compare``).

The five tasks (what a person who has never seen VBear would try; every sentence and name it types is made up and begins with QA47):

  1  first       from the start-up to the first sentence to the CEO. ``--no-ai`` stops at the box with the opening in it, or at the one
                 action of the prepare page (nothing is sent, no check is run); ``--haiku`` verifies the chat, sends one sentence and waits
                 for the reply.
  2  limit       set the day's limit to US$5 by typing it (v0.20.0 only offers 1, 3 and 10 and the settings page has no such place: the
                 task is recorded as "unable").
  3  routine     add a routine for every morning at 8 (switched on).
  4  card        read a "change a file" card and refuse it. ``--haiku``: the CEO is asked to make a file, the card comes, it is refused.
                 ``--no-ai``: no card can be made without a model, so the task is recorded as "unable" with the reason (the words of the
                 card are checked by tests/frontend/p47_chat.cjs, not here).
  5  blocked     what a person sees when the day's limit has stopped them, and the way to raise it. The limit is set to US$0.01 (only after
                 something was spent, with ``--haiku``) and a sentence is sent to the CEO; ``--no-ai`` instead finds where the day's use and
                 the limit are shown.

How it counts. A **step** is a press, a field filled, or one screen scrolled to find what is wanted (each counts 1). **Stuck** is a step
at which any of these happened: (1) what had to be pressed was not on the first screen (more than a screen of scrolling); (2) the page
(``main``'s text) held a word from the vocabulary table's ``avoid`` lists (``WORDS`` of web/app.js, scope ``all``) or a sentence from
``PLAIN_ERRORS`` (the same file; both read once with ``node`` from this repository's own web/app.js); (3) what had to be pressed is not
on this page and the person had to look on another. **Unable** is recorded apart. Also kept: **how much has to be read** (the characters
of ``main`` that are seen above the thing to press) and, on a phone (390 by 844), how far from the top of the page the chat box is.

The two versions' paths are written down below (``PATHS``), found only by ``data-*`` attributes, ``href`` and ids, never by the words on
the screen.

What it reads and writes. It talks to the console through the same HTTP routes the page uses (GET ``/api/config``, ``/api/meetings/ledger``,
``/api/chats``, ``/api/agent-profiles``, ``/api/routines``; POST ``/api/setup/daily-limit``, ``/api/config``, ``/api/chat-support/verify``
with ``--haiku``, and the deletes of what it made), and the access token only from ``<state>/server.token`` (never printed, never stored).
It writes ``<T>/qa47-<label>.json`` (steps, stuck, unable, counts, pixels, money, the names of screenshot files: no conversation, no
sentence a model wrote) and ``<T>/shots-<label>/*.png`` (``<T>`` is the folder that holds ``<state>``), and uses ``<T>/chrome-<label>`` as
the browser's own profile. It runs on port 7802 only (any other port, 7788 and 7789 first of all, is refused before anything is read or
started), refuses ``~/.vbear`` and anything under it, and a Claude cap above US$0.30. At the end it deletes the employees, chats and
routines it made (only the ones whose ids it saw appear after it began), and puts the day's limit and the per-turn limit back.

The money. ``--no-ai`` spends nothing. ``--haiku`` is the only thing that uses Claude Code (the console runs it, on Haiku): the chat
check of each state folder (kept at US$0.05) and one turn for task 1 and one for task 4, each under a per-turn limit of US$0.03. **The
hard cap is US$0.30 (``--claude-cap``, never more):** before each step that spends, the script adds "this state folder's day in the ledger
+ the other version's day (the ``ledger_end`` of its result file) + the chat check's US$0.05 + the step's own per-turn limit" and does not do
the step, and records a FAIL, when that is over the cap. **An amount that is not known is never counted as zero:** a ledger that cannot be
read at the end of a run is written as ``null`` with a FAIL; a run that finds the other version's start marker but no readable result
(it was lost, or it ended without one) does not spend at all; only a run that finds neither (the first of the pair) counts the other day as 0.

Caps on time: 20 minutes for the whole run, 2 minutes for any one wait, 5 minutes for one Chrome (every command to the browser is refused once
its 5 minutes are over, and no wait goes past what is left of them; the Chrome is closed in every case). A page that has not drawn yet is waited
for up to 30 seconds when a task begins (a new state folder's first screen can stay empty for 20 seconds).

The first task does not assume which screen comes first: it presses 「leave the start-up」 only when that button is on the screen. With
``--no-ai`` it also reads the chat support (GET ``/api/chat-support``): reaching a chat box that cannot be used (the tool is not checked for
chat, held back by an administrator's policy, or the state cannot be read) is a **dead end**: it counts as a stuck step and is written in the
result; reaching the prepare page's one action instead is the right ending.

    python3 tools/qa_p47.py --state "$T/a" --port 7802 --label before --chrome "<path of Chrome>"            # --no-ai is the default
    python3 tools/qa_p47.py --state "$T/b" --port 7802 --label after  --chrome "<path of Chrome>" --haiku
    python3 tools/qa_p47.py --compare "$T/qa47-before.json" "$T/qa47-after.json"

Exit code 0 only when every check passed (a task that is "unable" on v0.20.0 is not a FAIL). ``--compare`` exits 0 only when both runs have no
FAIL, every task that the before run did finished or is unable on the after run too is finished there, and nothing is worse.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_PORTS = (7788, 7789)
DEFAULT_PORT = 7802                          # the one port this script may use
LABELS = ("before", "after")
TASKS = ("first", "limit", "routine", "card", "blocked")
CLAUDE_CAP_MAX = 0.30
CHAT_CHECK_RESERVE = 0.05                    # kept for the Claude chat check of each state folder (it is not counted in the day's limit)
PER_TURN_CLAUDE = 0.03
DAILY_START = 2.00
WALL_CAP_S = 20 * 60
WAIT_CAP_S = 2 * 60
CHROME_CAP_S = 5 * 60
FIRST_LOAD_S = 30.0                          # a task's first screen can stay empty for 20 seconds on a new state folder
DESKTOP = (1440, 900)
PHONE = (390, 844)
SETTLE_S = 0.35
SCROLL_FRACTION = 0.9                        # one scroll is nine tenths of a screen
CHROME_FLAGS = ("--headless=new", "--use-mock-keychain", "--password-store=basic", "--no-first-run", "--no-default-browser-check",
                "--disable-sync", "--remote-debugging-pipe")
SENTENCES = {
    "first": "QA47 虛構：你好，請只回答 QA47 ok",
    "card": "QA47 虛構：請在你的工作資料夾建立 qa47.txt，內容寫 QA47 虛構",
    "blocked": "QA47 虛構：再說一句",
}
ROUTINE_NAME = "QA47 虛構早安"
ROUTINE_TEXT = "QA47 虛構：請整理三行待辦。"


class Check:
    """The lines and the count; nothing here ever holds a secret, a conversation or a model's words."""

    def __init__(self, out=print):
        self.out = out
        self.passed = 0
        self.failed = 0
        self.warned = 0

    def ok(self, name, detail=""):
        self.passed += 1
        self.out(f"ok   {name}" + (f"  ({detail})" if detail else ""))

    def warn(self, name, detail=""):
        self.warned += 1
        self.out(f"warn {name}" + (f"  ({detail})" if detail else ""))

    def fail(self, name, detail=""):
        self.failed += 1
        self.out(f"FAIL {name}" + (f"  ({detail})" if detail else ""))

    def expect(self, cond, name, detail=""):
        (self.ok if cond else self.fail)(name, detail)
        return bool(cond)


class Stop(Exception):
    """A check that the rest cannot go on without."""


# ---- pure helpers (tested by tests/test_qa_p47.py) --------------------------------------------------------------------------------

def refusal(state: str, port: int, cap: float = CLAUDE_CAP_MAX, label: str = "before", home: Path | None = None,
            chrome: str | None = None) -> str | None:
    """Why this run must not start, or None. The person's own VBear (its folder and everything under it, ports 7788 and 7789) is never
    the target; Claude's cap is at most US$0.30; the label is one of the two; the Chrome is a file that exists."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        return "the port must be 1024 to 65535"
    if port in FORBIDDEN_PORTS:
        return f"port {port} is the person's own VBear"
    if port != DEFAULT_PORT:
        return f"only port {DEFAULT_PORT} may be used (port {port} is kept for something else)"
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not 0 < cap <= CLAUDE_CAP_MAX:
        return f"--claude-cap must be above 0 and at most {CLAUDE_CAP_MAX}"
    if label not in LABELS:
        return "--label must be before or after"
    state_path = Path(state).expanduser().resolve()
    own = ((home or Path.home()).resolve() / ".vbear").resolve()
    if state_path == own or own in state_path.parents:
        return "that is the person's own VBear folder (or inside it); give a temporary one"
    if not state_path.is_dir():
        return "the state folder does not exist"
    if chrome is not None and not Path(chrome).is_file():
        return "--chrome must be the path of a Chrome program that exists"
    return None


def frame(message: dict) -> bytes:
    """One DevTools message on the pipe: JSON ended by a NUL byte."""
    return json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\0"


def unframe(buffer: bytes) -> tuple[list, bytes]:
    """Split what has been read into the whole messages and the rest (a message not yet ended). A part that is not JSON is dropped."""
    parts = buffer.split(b"\0")
    rest = parts.pop()
    out = []
    for raw in parts:
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(msg, dict):
            out.append(msg)
    return out, rest


def chrome_args(chrome: str, profile: str) -> list[str]:
    """The command of the browser: only the flags the rules list, its own profile, and the pipe (never a TCP debugging port)."""
    return [chrome, *CHROME_FLAGS, f"--user-data-dir={profile}", "about:blank"]


def money(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 and n == n and n != float("inf") else None


def claude_spent(ledgers: list, checks: int, reserve: float = CHAT_CHECK_RESERVE) -> float | None:
    """What Claude has cost so far: the day's spending of each state folder (the ledger), plus the reserve for each chat check that has been or
    will be run (it is not counted in the day's limit). None when a ledger could not be read (unknown is no)."""
    total = 0.0
    for value in ledgers:
        n = money(value)
        if n is None:
            return None
        total += n
    return total + reserve * checks


def claude_allowed(spent: float | None, step_cap: float, cap: float) -> bool:
    """Whether a step that spends may start: unknown is no, and so is "spent + this step's own limit" over the cap."""
    return spent is not None and spent + step_cap <= cap + 1e-9


def screens_to_scroll(top: float, height: float, viewport: float) -> int:
    """How many scrolls (each nine tenths of a screen) it takes to see what is to be pressed, whose top edge is ``top`` pixels from the top of
    the page when the page has not been scrolled. It counts as seen when the first 48 pixels of it (all of it if it is lower) are inside the
    screen. 0 when it already is, so "more than one screen away" is a number above 1."""
    if viewport <= 0:
        raise ValueError("viewport must be above 0")
    need = top + min(max(height, 0), 48)
    if need <= viewport:
        return 0
    return int(-(-(need - viewport) // (viewport * SCROLL_FRACTION)))


def count_chars(text: str) -> int:
    """The characters to read: the ones that are not white space."""
    return sum(1 for ch in str(text) if not ch.isspace())


def bad_words(text: str, avoid: list, errors: list) -> list:
    """The words a page said that the vocabulary table says not to say, and the known server sentences it showed as they came.
    ``avoid``: terms (a term made of ASCII letters is matched as a whole word, with its case; any other is searched literally).
    ``errors``: regular expressions (as text) of PLAIN_ERRORS. -> a sorted list of the terms found (an error is named ``error:<n>``)."""
    found = set()
    for term in avoid:
        if not isinstance(term, str) or not term:
            continue
        if re.fullmatch(r"[A-Za-z_ ]+", term):
            if re.search(rf"(?<![A-Za-z_]){re.escape(term)}(?![A-Za-z_])", text):
                found.add(term)
        elif term in text:
            found.add(term)
    for n, source in enumerate(errors):
        try:
            if re.search(source, text):
                found.add(f"error:{n}")
        except re.error:
            continue
    return sorted(found)


def judge_step(obs: dict) -> list:
    """Why a step counts as stuck. ``obs``: ``scrolls`` (screens scrolled to find the target), ``bad`` (the bad words on the page),
    ``elsewhere`` (the target was not on this page and the person had to look on another), ``dead_end`` (the person reached a box that cannot be
    used). -> a list of "scrolled", "words", "elsewhere", "dead_end"."""
    why = []
    if (obs.get("scrolls") or 0) > 1:
        why.append("scrolled")
    if obs.get("bad"):
        why.append("words")
    if obs.get("elsewhere"):
        why.append("elsewhere")
    if obs.get("dead_end"):
        why.append("dead_end")
    return why


def summarize(steps: list, unable: str = "") -> dict:
    """One task's result from its steps (each a dict with ``kind``: press / fill / scroll, ``stuck``: the reasons, ``read``: characters to
    read, ``bad``: the terms). Scrolls that were counted into a press are in ``scrolls`` of that step and are added here."""
    count = 0
    stuck = 0
    read = None
    bad = set()
    for s in steps:
        if s.get("kind") != "dead-end":              # a dead end is not something the person did: it is stuck, and it is not a step
            count += 1 + int(s.get("scrolls") or 0)
        if s.get("stuck"):
            stuck += 1
        if s.get("read") is not None:
            read = (read or 0) + int(s["read"])
        bad.update(s.get("bad") or [])
    return {"steps": count, "stuck": stuck, "unable": unable or None, "read": read, "bad": sorted(bad), "done": not unable}


def slice_const(source: str, name: str) -> str | None:
    """The text of the top-level ``const NAME = ...;`` statement of a JavaScript file: from the line that starts it to the first line that is
    ``};`` or ``];`` at the start of a line. None when it is not there."""
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(f"const {name} =")), None)
    if start is None:
        return None
    for j in range(start, len(lines)):
        if lines[j] in ("};", "];"):
            return "\n".join(lines[start:j + 1])
    return None


NODE_READ = """
%(words)s
%(errors)s
const avoid = [];
for (const w of Object.values(WORDS)) { if (w.scope === "all") for (const t of w.avoid) avoid.push(t); }
console.log(JSON.stringify({ avoid, errors: PLAIN_ERRORS.map((e) => e.re.source) }));
"""


def read_tables(app_js: Path, run=subprocess.run) -> dict:
    """The avoid words (scope ``all``) and the sentences of PLAIN_ERRORS, read once with ``node`` from the repository's own web/app.js
    (only the two tables are cut out and run, not the page). -> {"avoid": [...], "errors": [...]} or {"avoid": [], "errors": [], "why": ...}."""
    empty = {"avoid": [], "errors": []}
    try:
        source = Path(app_js).read_text(encoding="utf-8")
    except OSError:
        return {**empty, "why": "web/app.js could not be read"}
    words, errors = slice_const(source, "WORDS"), slice_const(source, "PLAIN_ERRORS")
    if not words or not errors:
        return {**empty, "why": "the tables WORDS and PLAIN_ERRORS were not found in web/app.js"}
    try:
        done = run(["node", "-e", NODE_READ % {"words": words, "errors": errors}], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        data = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {**empty, "why": "node could not read the tables"}
    if not isinstance(data, dict) or not isinstance(data.get("avoid"), list) or not isinstance(data.get("errors"), list):
        return {**empty, "why": "node answered something unexpected"}
    return {"avoid": [t for t in data["avoid"] if isinstance(t, str)], "errors": [t for t in data["errors"] if isinstance(t, str)]}


def result_ok(data) -> bool:
    """Whether a result file has the shape ``--compare`` and the coordinator rely on: a label, the UI it saw, five tasks each with the numbers and
    whether it was finished, and the count of checks. It holds no sentence of a conversation: a task's ``bad`` is a list of terms from the table
    and ``unable`` is one of our own reasons."""
    if not isinstance(data, dict) or data.get("label") not in LABELS or not isinstance(data.get("tasks"), dict):
        return False
    checks = data.get("checks")
    if not isinstance(checks, dict) or not all(isinstance(checks.get(k), int) and not isinstance(checks.get(k), bool) for k in ("ok", "warn", "fail")):
        return False
    for name in TASKS:
        t = data["tasks"].get(name)
        if not isinstance(t, dict) or not isinstance(t.get("steps"), int) or not isinstance(t.get("stuck"), int) or not isinstance(t.get("done"), bool):
            return False
    return True


COLUMNS = (("steps", "steps"), ("stuck", "stuck"), ("read", "read chars"))


def _cell(task: dict, key: str) -> str:
    if key == "steps" and task.get("unable"):
        return "unable"
    if key == "steps" and not task.get("done"):
        return "failed"
    value = task.get(key)
    return "-" if value is None else str(value)


def _delta(a: dict, b: dict, key: str) -> str:
    x, y = a.get(key), b.get(key)
    if a.get("unable") or b.get("unable") or not a.get("done") or not b.get("done") or not isinstance(x, int) or not isinstance(y, int):
        return "-"
    return f"{y - x:+d}"


def task_state(task: dict) -> str:
    """"ok" (finished), "unable" (this version cannot do it, our own reason is written) or "failed" (it did not finish and nothing says it cannot be done)."""
    if task.get("unable"):
        return "unable"
    if task.get("done") is True and not task.get("error"):
        return "ok"
    return "failed"


def verdict(before: dict, after: dict) -> list:
    """What is wrong with the pair, as short sentences; an empty list is "no worse". A run with a FAIL cannot be judged; an after task that did not
    finish, or that cannot be done where the before one could, is a regression whatever its step count; steps and stuck are compared only for a task
    both versions finished."""
    problems = []
    for label, data in (("before", before), ("after", after)):
        fails = (data.get("checks") or {}).get("fail") or 0
        if fails:
            problems.append(f"{label} run has {fails} FAIL")
    for name in TASKS:
        a, b = before["tasks"][name], after["tasks"][name]
        sa, sb = task_state(a), task_state(b)
        if sb == "failed":
            problems.append(f"{name}: after did not finish")
        elif sb == "unable" and sa == "ok":
            problems.append(f"{name}: after cannot do what before did")
        elif sa == "failed":
            problems.append(f"{name}: before did not finish, so it cannot be compared")
        elif sa == "ok" and sb == "ok" and (b["steps"] > a["steps"] or b["stuck"] > a["stuck"]):
            problems.append(f"{name}: worse")
    return problems


def compare_table(before: dict, after: dict) -> str:
    """The table ``--compare`` prints: for each task, the steps, stuck and read characters of each version and the difference (after minus
    before), the tasks that were unable or failed, and the phone's chat-box distance. Lower is better; 'unable' is shown, not counted as zero."""
    rows = [("task", "steps b", "steps a", "diff", "stuck b", "stuck a", "diff", "read b", "read a", "diff")]
    for name in TASKS:
        a, b = before["tasks"][name], after["tasks"][name]
        rows.append((name, _cell(a, "steps"), _cell(b, "steps"), _delta(a, b, "steps"), _cell(a, "stuck"), _cell(b, "stuck"), _delta(a, b, "stuck"),
                     _cell(a, "read"), _cell(b, "read"), _delta(a, b, "read")))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    for name in TASKS:
        for label, data in (("before", before), ("after", after)):
            why = data["tasks"][name].get("unable")
            if why:
                lines.append(f"{name} ({label}): unable - {why}")
            elif task_state(data["tasks"][name]) == "failed":
                lines.append(f"{name} ({label}): did not finish - {str(data['tasks'][name].get('error') or 'no reason written')[:120]}")
            if data["tasks"][name].get("dead_end"):
                lines.append(f"{name} ({label}): dead end - {data['tasks'][name]['dead_end']}")
    for label, data in (("before", before), ("after", after)):
        px = (data.get("phone") or {}).get("chat_input_px")
        lines.append(f"phone, chat box from the top of the page ({label}): " + ("not measured" if px is None else f"{px} px"))
    worse = verdict(before, after)
    lines.append("every task is no worse than before: " + ("yes" if not worse else "NO - " + "; ".join(worse)))
    return "\n".join(lines)


def compare(path_a: Path, path_b: Path, out=print) -> int:
    """``--compare a.json b.json``: print the table. 2 when a file cannot be read or has the wrong shape; 1 when after is worse or a run failed;
    else 0."""
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


# ---- the browser: Chrome over the DevTools pipe ------------------------------------------------------------------------------------

class Browser:
    """One headless Chrome, driven over ``--remote-debugging-pipe`` (fd 3 in, fd 4 out; no TCP port). Nothing here knows VBear."""

    def __init__(self, chrome: str, profile: Path, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.proc = None
        self.next_id = 0
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.replies: dict = {}
        self.events: list = []
        self.closed = False
        to_chrome_r, to_chrome_w = os.pipe()
        from_chrome_r, from_chrome_w = os.pipe()
        # The child reads fd 3 and writes fd 4. A shell does the two redirections, so that no hook runs between fork and exec; the two
        # pipe ends are moved above 9 first, so that a redirection can never land on an end still wanted.
        r = fcntl.fcntl(to_chrome_r, fcntl.F_DUPFD, 10)
        w = fcntl.fcntl(from_chrome_w, fcntl.F_DUPFD, 10)
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        try:
            self.proc = subprocess.Popen(["/bin/sh", "-c", f'exec "$@" 3<&{r} 4>&{w}', "sh", *chrome_args(chrome, str(profile))],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                                         pass_fds=(r, w))
        finally:
            os.close(r)
            os.close(w)
        self.wfd, self.rfd = to_chrome_w, from_chrome_r
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        buf = b""
        while True:
            try:
                chunk = os.read(self.rfd, 1 << 16)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
            msgs, buf = unframe(buf)
            with self.cond:
                for m in msgs:
                    if "id" in m:
                        self.replies[m["id"]] = m
                    else:
                        self.events.append(m)
                self.cond.notify_all()
        with self.cond:
            self.closed = True
            self.cond.notify_all()

    def left(self) -> float:
        """What is left of this Chrome's 5 minutes."""
        return CHROME_CAP_S - (self.clock() - self.started)

    def allowed_wait(self, wait: float, force: bool = False) -> float:
        """How long one command may wait: never past what is left of the 5 minutes, and never past the 2 minutes of any one wait. Once the 5
        minutes are over nothing is sent any more, except the closing (``force``)."""
        if force:
            return wait
        left = self.left()
        if left <= 0:
            raise Stop("the 5 minutes of this Chrome are over")
        return min(wait, left, WAIT_CAP_S)

    def call(self, method: str, params: dict | None = None, session: str | None = None, wait: float = 30.0, force: bool = False) -> dict:
        wait = self.allowed_wait(wait, force)
        with self.lock:
            self.next_id += 1
            ident = self.next_id
        msg = {"id": ident, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        try:
            os.write(self.wfd, frame(msg))
        except OSError:
            raise Stop("Chrome closed the pipe") from None
        end = self.clock() + wait
        with self.cond:
            while ident not in self.replies:
                if self.closed:
                    raise Stop("Chrome closed the pipe")
                left = end - self.clock()
                if left <= 0:
                    raise Stop(f"Chrome did not answer {method}")
                self.cond.wait(min(left, 0.5))
            reply = self.replies.pop(ident)
        if "error" in reply:
            raise Stop(f"Chrome refused {method}: {str(reply['error'].get('message'))[:120]}")
        return reply.get("result") or {}

    def over(self) -> bool:
        return self.left() <= 0

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            self.call("Browser.close", wait=5, force=True)
        except Stop:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for fd in (self.wfd, self.rfd):
            try:
                os.close(fd)
            except OSError:
                pass
        self.proc = None


# The only scripts run in the page. Each takes its arguments as JSON and answers JSON; they look at attributes, text lengths and
# rectangles, press, or fill a field. None reads a value of a field or any text beyond its length, except ``MAIN_TEXT`` (matched in this
# script against the vocabulary tables and then dropped, never stored).
JS_FIND = """((sel) => {
  const e = document.querySelector(sel);
  if (!e) return { found: false };
  const r = e.getBoundingClientRect();
  const st = getComputedStyle(e);
  const shown = r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  return { found: true, shown, top: r.top, docTop: r.top + window.scrollY, height: r.height,
           disabled: !!e.disabled, vh: window.innerHeight, sy: window.scrollY };
})(%s)"""
JS_CLICK = """((sel) => { const e = document.querySelector(sel); if (!e) return false; e.click(); return true; })(%s)"""
JS_FILL = """((sel, value) => {
  const e = document.querySelector(sel); if (!e) return false;
  const proto = e.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(e, value);
  e.dispatchEvent(new Event("input", { bubbles: true })); e.dispatchEvent(new Event("change", { bubbles: true }));
  return true; })(%s, %s)"""
JS_MAIN_TEXT = """(() => { const m = document.getElementById("main"); return m ? m.innerText : ""; })()"""
JS_SCROLL = """((sel, f) => {
  let e = sel ? document.querySelector(sel) : null;
  const scrollable = (n) => { const s = getComputedStyle(n); return /(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 1; };
  while (e && e !== document.body && e !== document.documentElement) { if (scrollable(e)) break; e = e.parentElement; }
  if (!e || e === document.body || e === document.documentElement) {
    const before = window.scrollY; window.scrollBy(0, Math.round(window.innerHeight * f)); return window.scrollY !== before;
  }
  const before = e.scrollTop; e.scrollBy(0, Math.round(e.clientHeight * f)); return e.scrollTop !== before;
})(%s, %s)"""
JS_INTO_VIEW = """((sel) => { const e = document.querySelector(sel); if (e) e.scrollIntoView({ block: "center" }); return !!e; })(%s)"""
JS_TOP = """(() => { window.scrollTo(0, 0); return true; })()"""
JS_COUNT_ABOVE = """((sel) => {
  const target = document.querySelector(sel), main = document.getElementById("main");
  if (!target || !main) return -1;
  const walk = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  let n = 0, node;
  while ((node = walk.nextNode())) {
    if (target.contains(node) || (target.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)) break;
    const p = node.parentElement; if (!p) continue;
    const r = p.getBoundingClientRect(), st = getComputedStyle(p);
    if (r.width === 0 || r.height === 0 || st.visibility === "hidden" || p.closest("[hidden]")) continue;
    if (p.closest("details:not([open])") && !p.closest("summary")) continue;
    n += node.textContent.replace(/\\s/g, "").length;
  }
  return n; })(%s)"""
JS_BOX_TOP = """((sel) => { const e = document.querySelector(sel); if (!e) return null; return Math.round(e.getBoundingClientRect().top + window.scrollY); })(%s)"""
JS_HAS = """((sel) => !!document.querySelector(sel))(%s)"""
JS_VALUE_OF = """((sel) => { const e = document.querySelector(sel); return e ? String(e.value || "").length : -1; })(%s)"""
JS_ROUTE = """(() => location.hash)()"""
JS_CHECKED = """((sel) => { const e = document.querySelector(sel); return e ? !!e.checked : null; })(%s)"""
JS_AT_BOTTOM = """(() => Math.ceil(window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight - 2)()"""
JS_TEXT_OF = """((sel) => { const e = document.querySelector(sel); return e ? e.innerText : ""; })(%s)"""


class Page:
    """One tab: the calls the walk needs, each running one of the scripts above."""

    def __init__(self, browser: Browser, base: str, sleep=time.sleep):
        self.b, self.base, self.sleep = browser, base, sleep
        target = browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = browser.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        browser.call("Page.enable", session=self.session)
        self.size = DESKTOP

    def ev(self, expression: str):
        res = self.b.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, session=self.session)
        if res.get("exceptionDetails"):
            raise Stop("a script in the page failed")
        return (res.get("result") or {}).get("value")

    def viewport(self, width: int, height: int) -> None:
        self.size = (width, height)
        self.b.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 500},
                    session=self.session)

    def open(self, url: str) -> None:
        self.b.call("Page.navigate", {"url": url}, session=self.session)
        self.settle(1.0)

    def goto(self, hash_: str) -> None:
        """Move to a route by its address (the same as a link would) and wait until the page stops changing."""
        self.ev("(h => { location.hash = h; return true; })(%s)" % json.dumps(hash_))
        self.settle()

    def settle(self, floor: float = SETTLE_S, cap: float = 8.0) -> None:
        end = self.b.clock() + cap
        last, since = None, self.b.clock()
        while self.b.clock() < end:
            self.sleep(0.12)
            now = self.ev(JS_MAIN_TEXT)
            if now == last and self.b.clock() - since >= floor:
                return
            if now != last:
                last, since = now, self.b.clock()

    def find(self, sel: str) -> dict:
        return self.ev(JS_FIND % json.dumps(sel)) or {"found": False}

    def has(self, sel: str) -> bool:
        return bool(self.ev(JS_HAS % json.dumps(sel)))

    def click(self, sel: str) -> bool:
        ok = bool(self.ev(JS_CLICK % json.dumps(sel)))
        self.settle()
        return ok

    def fill(self, sel: str, value: str) -> bool:
        return bool(self.ev(JS_FILL % (json.dumps(sel), json.dumps(value))))

    def scroll(self, sel: str | None = None) -> bool:
        """Scroll one screen (nine tenths) of whatever holds ``sel`` (the page, or the side menu); True when anything moved."""
        moved = bool(self.ev(JS_SCROLL % (json.dumps(sel), json.dumps(SCROLL_FRACTION))))
        self.sleep(0.1)
        return moved

    def into_view(self, sel: str) -> None:
        self.ev(JS_INTO_VIEW % json.dumps(sel))

    def to_top(self) -> None:
        self.ev(JS_TOP)

    def at_bottom(self) -> bool:
        return bool(self.ev(JS_AT_BOTTOM))

    def checked(self, sel: str):
        return self.ev(JS_CHECKED % json.dumps(sel))

    def text_of(self, sel: str) -> str:
        return str(self.ev(JS_TEXT_OF % json.dumps(sel)) or "")

    def main_text(self) -> str:
        return str(self.ev(JS_MAIN_TEXT) or "")

    def read_above(self, sel: str) -> int:
        return int(self.ev(JS_COUNT_ABOVE % json.dumps(sel)))

    def box_top(self, sel: str):
        return self.ev(JS_BOX_TOP % json.dumps(sel))

    def length_of(self, sel: str) -> int:
        return int(self.ev(JS_VALUE_OF % json.dumps(sel)))

    def route(self) -> str:
        return str(self.ev(JS_ROUTE) or "")

    def shot(self, path: Path) -> None:
        data = self.b.call("Page.captureScreenshot", {"format": "png"}, session=self.session, wait=30)["data"]
        Path(path).write_bytes(base64.b64decode(data))


# ---- the console's HTTP routes ------------------------------------------------------------------------------------------------------

class Console:
    def __init__(self, port: int, token: str, timeout: float = 60.0):
        self.port, self.token, self.timeout = port, token, timeout
        self.budget = None            # a function: seconds this call may still use (set only inside a wait; None = the normal limit)

    def call(self, path: str, method: str = "GET", body=None):
        timeout = self.timeout
        if callable(self.budget):
            left = self.budget()
            if left <= 0:
                return 0, None
            timeout = min(timeout, left)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"X-VBear": "1", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        if not callable(self.budget):
            return self._once(req, timeout)
        # Inside a wait the whole call (status line, headers, body, an error's body) is held to what is left, not each socket read: it runs
        # on its own thread over a connection this call holds. When the time is over the connection is shut and closed, which ends the
        # thread's read at once; the thread is then waited for (briefly) so nothing is left reading.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        # The socket is made and registered before it connects, under a lock shared with the cancel below: a cancel either finds it and
        # closes it (its connect, request or read then fails at once), or comes first and the socket is never made. Nothing can connect
        # after the time is over, and an answer with "Connection: close" taking the socket from conn.sock does not hide it.
        lock, held, cancelled = threading.Lock(), [], [False]
        port = self.port

        def connect():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            with lock:
                if cancelled[0]:
                    sock.close()
                    raise OSError("the time left is over")
                held.append(sock)
            sock.connect(("127.0.0.1", port))
            conn.sock = sock
        conn.connect = connect
        box = []

        def shut_all():
            with lock:
                cancelled[0] = True
                socks = list(held)
            for sock in socks:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

        def run():
            try:
                conn.request(req.get_method(), req.selector, body=req.data, headers=dict(req.header_items()))
                resp = conn.getresponse()
                raw = resp.read()
                try:
                    data = json.loads(raw or b"null")
                except ValueError:
                    data = None
                box.append((resp.status, data))
            except Exception:                               # a read cut short by the closing below ends here, whatever it raised
                box.append((0, None))
            finally:
                shut_all()                                  # the worker always lets its socket go, answered or not
                conn.close()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            worker.join(max(0.0, self.budget()))
        finally:
            late = worker.is_alive()
            shut_all()                                      # past the time left (or done): no socket stays open, none can be opened
            conn.close()
            worker.join(1.0)                                # the read was cut: the thread ends at once
            if not worker.is_alive():
                del conn.connect                            # no reference loop keeps the connection alive (only once the worker is gone:
                                                            # a worker still running stays held to the cancel, so it can never reconnect)
        if late or not box or self.budget() <= 0:
            return 0, None
        return box[0]

    @staticmethod
    def _once(req, timeout):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read() or b"null")
            except ValueError:
                data = None
            finally:
                exc.close()
            return exc.code, data
        except (urllib.error.URLError, OSError, ValueError):
            return 0, None

    def ok(self, path: str, method: str = "GET", body=None, status=(200, 201, 202)):
        code, data = self.call(path, method, body)
        if code not in status:
            msg = data.get("code") if isinstance(data, dict) else None
            raise Stop(f"{method} {path.split('?')[0]} answered {code}" + (f" ({msg})" if msg else ""))
        return data


def read_token(state: Path, port: int) -> str:
    try:
        data = json.loads((Path(state) / "server.token").read_text())
    except (OSError, ValueError):
        raise Stop("no readable server.token in the state folder: is the console running on it?") from None
    if not isinstance(data, dict) or data.get("port") != port or not isinstance(data.get("token"), str) or not data["token"]:
        raise Stop("server.token is not the one of a console on that port")
    return data["token"]


# ---- the walk ----------------------------------------------------------------------------------------------------------------------

SCROLL_CAP = 40
PATIENCE_S = 4.0


class Walker:
    """Walks one version's path through the page and keeps the count: a step is a press, a field filled, or a screen scrolled to find
    what is wanted; stuck is what ``judge_step`` says. ``page`` is anything with the Page methods (a fake one in the tests)."""

    def __init__(self, page, tables: dict, clock=time.monotonic, sleep=time.sleep):
        self.page, self.tables, self.clock, self.sleep = page, tables, clock, sleep
        self.steps: list = []
        self.route_seen = ""

    # -- a task ----------------------------------------------------------------------------------------------------------------

    def begin(self, hash_: str, load: float = FIRST_LOAD_S) -> None:
        """Start a task at an address (opening it is not a step: it is where the person is). The screen is waited for, up to ``load`` seconds: a
        new state folder's first screen can stay empty for 20 seconds, and nothing is judged before it is drawn."""
        self.steps = []
        self.page.goto(hash_)
        end = self.clock() + load
        while not str(self.page.main_text()).strip() and self.clock() < end:
            self.sleep(0.5)
        self.page.to_top()
        self.route_seen = self.page.route()

    def dead_end(self, why: str) -> dict:
        """The person reached a box that cannot be used: stuck (not a step of theirs)."""
        step = {"kind": "dead-end", "target": why, "scrolls": 0, "read": None, "bad": [], "stuck": judge_step({"dead_end": True}), "why": why}
        self.steps.append(step)
        return step

    def _bad(self) -> list:
        return bad_words(self.page.main_text(), self.tables.get("avoid", []), self.tables.get("errors", []))

    def present(self, sel: str, patience: float = 3.0) -> bool:
        """Whether ``sel`` is on the screen (after a short wait for a page that is still drawing). Nothing is recorded: it is only looking."""
        info = self._wait_for(sel, patience)
        return bool(info.get("found") and info.get("shown"))

    def _arrived(self) -> None:
        now = self.page.route()
        if now != self.route_seen:
            self.route_seen = now
            self.page.to_top()

    def _wait_for(self, sel: str, patience: float, enabled: bool = False) -> dict:
        """The page draws after its answers come: look again for a few seconds before saying a thing is not there (or, if ``enabled``, still off)."""
        end = self.clock() + patience
        info = self.page.find(sel)
        while self.clock() < end and (not (info.get("found") and info.get("shown")) or (enabled and info.get("disabled"))):
            self.sleep(0.3)
            info = self.page.find(sel)
        return info

    def _see(self, sel: str, patience: float = PATIENCE_S, enabled: bool = False):
        """Scroll until the first 48 pixels of ``sel`` are in the screen. -> (info, scrolls) or (None, scrolls) when it is not shown on the page."""
        scrolls = 0
        info = self._wait_for(sel, patience, enabled)
        while info.get("found") and info.get("shown"):
            top, height, vh = info.get("top", 0), info.get("height", 0), info.get("vh", 1)
            if top < 0:
                self.page.into_view(sel)
                scrolls += 1
                info = self.page.find(sel)
                break
            if top + min(max(height, 0), 48) <= vh or scrolls >= SCROLL_CAP:
                break
            if not self.page.scroll(sel):
                break                                                           # nothing moves: it cannot be brought into the screen
            scrolls += 1
            info = self.page.find(sel)
        if not (info.get("found") and info.get("shown")):
            return None, scrolls
        return info, scrolls

    def _record(self, kind: str, sel: str, scrolls: int, bad: list, read, elsewhere: bool = False) -> dict:
        step = {"kind": kind, "target": sel, "scrolls": scrolls, "read": read, "bad": bad,
                "stuck": judge_step({"scrolls": scrolls, "bad": bad, "elsewhere": elsewhere})}
        self.steps.append(step)
        return step

    # -- the moves -------------------------------------------------------------------------------------------------------------

    def press(self, sel: str):
        """Press ``sel``. -> the step, or None when it is not on the page (nothing is recorded; the caller says why)."""
        bad = self._bad()
        info, scrolls = self._see(sel, enabled=True)
        if info is None:
            return None
        if info.get("disabled"):
            return {"disabled": True, "target": sel}
        read = self.page.read_above(sel)
        step = self._record("press", sel, scrolls, bad, read if read >= 0 else None)
        self.page.click(sel)
        self._arrived()
        return step

    def fill(self, sel: str, value: str):
        bad = self._bad()
        info, scrolls = self._see(sel)
        if info is None:
            return None
        read = self.page.read_above(sel)
        step = self._record("fill", sel, scrolls, bad, read if read >= 0 else None)
        if not self.page.fill(sel, value):
            return None
        return step

    def ensure(self, sel: str):
        """A box that has to be ticked: pressed only when it is not (a person who sees it ticked does nothing). -> the step or None."""
        state = self.page.checked(sel)
        if state is None:
            return None
        if state:
            bad = self._bad()
            info, scrolls = self._see(sel)
            return self._record("look", sel, scrolls, bad, None) if info is not None and scrolls else {"kind": "look", "target": sel, "already": True}
        return self.press(sel)

    def look(self, sels):
        """Find the first of ``sels`` that is on the page, scrolling to it; nothing is pressed. -> (the step, the selector found) or (None, None)."""
        bad = self._bad()
        for sel in ([sels] if isinstance(sels, str) else list(sels)):
            info, scrolls = self._see(sel)
            if info is not None:
                read = self.page.read_above(sel)
                return self._record("look", sel, scrolls, bad, read if read >= 0 else None), sel
        return None, None

    def search(self, sel: str):
        """Look for ``sel`` on this page, where the person expects it, by scrolling to the bottom. If it is there it was only a look; if not,
        the person has to look on another page (that is stuck). -> (the step, found)."""
        bad = self._bad()
        info, scrolls = self._see(sel, patience=1.0)
        if info is not None:
            return self._record("look", sel, scrolls, bad, None), True
        scrolls = 0
        while not self.page.at_bottom() and scrolls < SCROLL_CAP:
            if not self.page.scroll():
                break
            scrolls += 1
        return self._record("search", sel, scrolls, bad, None, elsewhere=True), False

    def summary(self, unable: str = "") -> dict:
        return summarize(self.steps, unable)


# ---- the two versions' paths ---------------------------------------------------------------------------------------------------------
#
# Written down by hand and found only by ``data-*`` attributes, ``href`` and the dialog's classes, never by the words on the screen.
# A step: ``kind`` press / fill / ensure / look / search, ``sel`` (a selector, or a list of them for ``look``), ``value`` (fill), ``ai`` (only with
# --haiku: it sends something to Claude), ``then`` (what the script itself does after the step), ``unable`` (what a search that finds nothing means).
# ``optional`` (press): done only when the thing is on the screen once the screen is drawn; if it is not, the person is already past it.
# ``start`` is where the person is when the task begins (not a step). v0.20.0 has no ``data-nav`` for the new pages; its own ids are used.

DIALOG_OK = '.modal-backdrop .modal-actions .btn.primary'
LEAVE = '[data-setup="leave"]'
CEO_GO = '[data-ceo="create"]'
NAV_SETTINGS = '[data-nav="settings"]'
LIMITS_SUMMARY = '[data-settings="limits"] > summary'
ROUTINE_DAYS = [f'[data-routine-day="{i}"]' for i in range(7)]
SEND = '[data-chat="send"]'
CHAT_INPUT = '[data-chat="input"]'

PATHS = {
    "before": {
        "first": {"start": "#/", "steps": [
            {"kind": "press", "sel": LEAVE, "optional": True, "unable": "no AI tool is ready on this computer, so the start button stays off"},
            {"kind": "press", "sel": '[data-ceo="create-invite"] a[href="#/ceo"]'},
            {"kind": "press", "sel": CEO_GO, "then": "ceo_made"},
            {"kind": "look", "sel": [CHAT_INPUT, '[data-chat="verify"]'], "then": "chat_usable"},
            {"kind": "press", "sel": SEND, "ai": True, "then": "first_reply"},
        ]},
        "limit": {"start": "#/", "steps": [
            {"kind": "press", "sel": NAV_SETTINGS},
            {"kind": "search", "sel": '[data-limit-input]'},
            {"kind": "press", "sel": '[data-setup="open"]'},
            {"kind": "search", "sel": '[data-daily-pick="5"]',
             "unable": "v0.20.0 offers only US$1, US$3 and US$10 (on the start-up page); there is no field to type US$5"},
        ]},
        "routine": {"start": "#/", "steps": [
            {"kind": "press", "sel": '[data-nav="routines"]'},
            {"kind": "press", "sel": '[data-routine-action="new"]'},
            {"kind": "fill", "sel": '[data-routine-field="name"]', "value": ROUTINE_NAME},
            {"kind": "fill", "sel": '[data-routine-field="text"]', "value": ROUTINE_TEXT},
            *({"kind": "ensure", "sel": sel} for sel in ROUTINE_DAYS),
            {"kind": "ensure", "sel": '[data-routine-field="enabled"]'},
            {"kind": "press", "sel": '[data-routine-action="save"]', "then": "routine_saved"},
        ]},
        "card": {"start": "chat", "steps": [
            {"kind": "fill", "sel": CHAT_INPUT, "value": SENTENCES["card"], "ai": True},
            {"kind": "press", "sel": SEND, "ai": True, "then": "wait_card"},
            {"kind": "press", "sel": '[data-chat="deny"]', "ai": True, "then": "card_refused"},
        ]},
        "blocked_find": {"start": "#/", "steps": [
            {"kind": "press", "sel": NAV_SETTINGS},
            {"kind": "search", "sel": '[data-limit-input]'},
            {"kind": "press", "sel": '[data-setup="open"]'},
            {"kind": "look", "sel": '[data-setup-slot="daily-limit"]'},
        ]},
        "blocked_sent": {"start": "chat", "steps": [
            {"kind": "fill", "sel": CHAT_INPUT, "value": SENTENCES["blocked"]},
            {"kind": "press", "sel": SEND, "then": "blocked_notice"},
            {"kind": "press", "sel": NAV_SETTINGS},
            {"kind": "search", "sel": '[data-limit-input]'},
            {"kind": "press", "sel": '[data-setup="open"]'},
            {"kind": "look", "sel": '[data-setup-slot="daily-limit"]'},
        ]},
    },
    "after": {
        "first": {"start": "#/", "steps": [
            {"kind": "press", "sel": LEAVE, "optional": True, "unable": "no AI tool is ready on this computer, so the start button stays off"},
            {"kind": "press", "sel": '[data-home-step="2"] a[href="#/ceo"]'},
            {"kind": "press", "sel": CEO_GO, "then": "ceo_made"},
            {"kind": "look", "sel": [CHAT_INPUT, '[data-chat="prep-action"]'], "then": "chat_usable"},
            {"kind": "press", "sel": SEND, "ai": True, "then": "first_reply"},
        ]},
        "limit": {"start": "#/", "steps": [
            {"kind": "press", "sel": NAV_SETTINGS},
            {"kind": "press", "sel": LIMITS_SUMMARY},
            {"kind": "press", "sel": '[data-limit-choice="custom"]'},
            {"kind": "fill", "sel": '[data-limit-input]', "value": "5"},
            {"kind": "press", "sel": '[data-limit-save]', "then": "limit_saved"},
        ]},
        "routine": {"start": "#/", "steps": [
            {"kind": "press", "sel": '[data-nav="work"]'},
            {"kind": "press", "sel": '[data-work="routines"]'},
            {"kind": "press", "sel": '[data-routine-action="new"]'},
            {"kind": "fill", "sel": '[data-routine-field="name"]', "value": ROUTINE_NAME},
            {"kind": "fill", "sel": '[data-routine-field="text"]', "value": ROUTINE_TEXT},
            *({"kind": "ensure", "sel": sel} for sel in ROUTINE_DAYS),
            {"kind": "ensure", "sel": '[data-routine-field="enabled"]'},
            {"kind": "press", "sel": '[data-routine-action="save"]', "then": "routine_saved"},
        ]},
        "card": {"start": "chat", "steps": [
            {"kind": "fill", "sel": CHAT_INPUT, "value": SENTENCES["card"], "ai": True},
            {"kind": "press", "sel": SEND, "ai": True, "then": "wait_card"},
            {"kind": "press", "sel": '[data-chat="deny"]', "ai": True, "then": "card_refused"},
        ]},
        "blocked_find": {"start": "#/", "steps": [
            {"kind": "press", "sel": NAV_SETTINGS},
            {"kind": "press", "sel": LIMITS_SUMMARY},
            {"kind": "look", "sel": '[data-limit-current]'},
        ]},
        "blocked_sent": {"start": "#/", "steps": [
            {"kind": "fill", "sel": '[data-home="ask-input"]', "value": SENTENCES["blocked"]},
            {"kind": "press", "sel": '[data-home="ask-send"]', "then": "blocked_notice"},
            {"kind": "look", "sel": '[data-limit="reached"]'},
            {"kind": "press", "sel": '[data-limit="go"]'},
            {"kind": "look", "sel": '[data-limit-input]'},
        ]},
    },
}


# ---- the run ---------------------------------------------------------------------------------------------------------------------------

class Unable(Exception):
    """A task cannot be done in this version (or here); the reason is our own sentence, never the page's."""


def page_head(route: str) -> str:
    """The first part of an address (``#/chat/c-1234`` -> ``#/chat``, ``#/chat?profile=x`` -> ``#/chat``): no id is ever written down."""
    head = re.split(r"[?]", str(route))[0]
    parts = [x for x in head.split("/") if x]
    return "#/" + (parts[1] if len(parts) > 1 else "")


class Run:
    def __init__(self, console, page, walker, state: Path, label: str, haiku: bool, cap: float, check: Check, out_dir: Path,
                 clock=time.monotonic, sleep=time.sleep):
        self.c, self.page, self.w, self.state, self.label = console, page, walker, Path(state), label
        self.haiku, self.cap, self.check, self.out_dir = haiku, cap, check, Path(out_dir)
        self.clock, self.sleep, self.started = clock, sleep, clock()
        self.made = {"profiles": [], "chats": [], "routines": []}
        self.orig: dict = {}
        self.tasks: dict = {}
        self.shots: list = []
        self.phone: dict = {"chat_input_px": None}
        self.ui = "?"
        self.ceo = None
        self.chat = None
        self.notice = {}
        self.spent_calls = 0
        self.other = None
        self.marker_kept = None                      # None until the start marker is tried; False when it could not be written (nothing is spent then)
        self.other_state = "none"                    # "none" (the first of the pair), "known" (its result was read) or "unknown" (it began and left no usable result)
        self.last_look = None
        self.dead_end = None
        self.shot_dir = self.out_dir / f"shots-{label}"

    # -- small helpers ---------------------------------------------------------------------------------------------------------

    def over(self) -> bool:
        return self.clock() - self.started > WALL_CAP_S

    def chrome_left(self) -> float | None:
        """What is left of the Chrome's 5 minutes (None when there is no Chrome to ask, as in a test of the walk alone)."""
        left = getattr(getattr(self.page, "b", None), "left", None)
        return left() if callable(left) else None

    def wait(self, what: str, probe, cap: float = WAIT_CAP_S, every: float = 1.0):
        """Poll ``probe`` until it answers. The wait is never longer than 2 minutes, nor than what is left of the whole run or of the Chrome's 5
        minutes: that is looked at before every probe and before every sleep, and the probe's own HTTP call (through ``Console.budget``) and
        every sleep are held to what is left. A wait that begins after the deadline probes nothing."""
        end = self.clock() + min(cap, WAIT_CAP_S)           # no single wait is longer than 2 minutes, whatever asks for more

        def room() -> float:                                # seconds this wait may still use; <= 0 means: stop
            left = end - self.clock()
            chrome = self.chrome_left()
            return left if chrome is None else min(left, chrome)

        before = getattr(self.c, "budget", None)
        self.c.budget = lambda: max(0.0, room())
        try:
            while True:
                if self.over() or (self.chrome_left() is not None and self.chrome_left() <= 0):
                    raise Stop(f"timed out waiting for {what}")
                got = probe()
                if got:
                    if room() <= 0 or self.over():          # an answer that came in after the deadline is not taken
                        raise Stop(f"timed out waiting for {what}")
                    return got
                left = room()
                if left <= 0 or self.over():
                    raise Stop(f"timed out waiting for {what}")
                self.sleep(min(every, left))
        finally:
            self.c.budget = before

    def ledger(self) -> float | None:
        code, data = self.c.call("/api/meetings/ledger")
        return money(data.get("spent_usd")) if code == 200 and isinstance(data, dict) else None

    def shot(self, name: str) -> None:
        try:
            self.shot_dir.mkdir(parents=True, exist_ok=True)
            self.page.shot(self.shot_dir / f"{name}.png")
            self.shots.append(f"{name}.png")
        except (Stop, OSError):
            self.check.warn("a screenshot could not be taken", name)

    def profiles(self) -> list:
        code, data = self.c.call("/api/agent-profiles")
        return [p for p in (data or {}).get("profiles", []) if isinstance(p, dict)] if code == 200 and isinstance(data, dict) else []

    def other_ledger(self) -> float | None:
        """The other version's day, in dollars: 0 only for the first of the pair; None (unknown, which is never a yes) when the other version began
        and its result is missing, broken, or has no readable amount."""
        if self.other_state == "none":
            return 0.0
        other = self.other if isinstance(self.other, dict) else {}
        return money((other.get("money") or {}).get("ledger_end")) if self.other_state == "known" else None

    def money_ok(self, step_cap: float, checks: int | None = None) -> bool:
        """The cap before a step that spends: the day's ledger of this folder, the other folder's day (from its result file), the chat checks
        (kept at US$0.05 each) and this step's own limit."""
        if self.marker_kept is False:
            return False
        other = self.other if isinstance(self.other, dict) else {}
        ledgers = [self.ledger(), self.other_ledger()]
        others_checks = 1 if other and other.get("mode") == "haiku" else 0
        spent = claude_spent(ledgers, (1 if checks is None else checks) + others_checks)
        return claude_allowed(spent, step_cap, self.cap)

    # -- the start --------------------------------------------------------------------------------------------------------------

    def start(self) -> None:
        if (self.ledger() is None):
            raise Stop("the ledger cannot be read: is the console running on that state folder?")
        conf = self.c.ok("/api/config").get("config") or {}
        ledger = self.c.ok("/api/meetings/ledger")
        limits = conf.get("chat_limits") if isinstance(conf.get("chat_limits"), dict) else {}
        self.orig = {"daily": money(ledger.get("daily_usd")), "per_turn": limits.get("per_turn_usd"),
                     "profiles": {p.get("id") for p in self.profiles()},
                     "routines": {r.get("id") for r in (self.c.ok("/api/routines").get("routines") or []) if isinstance(r, dict)}}
        self.page.viewport(*DESKTOP)
        self.page.open(f"http://127.0.0.1:{self.c.port}/#auth={self.c.token}")
        self.sleep(1.5)
        self.page.goto("#/")
        self.ui = "v0.21" if self.page.has('[data-nav="employees"]') else "v0.20"
        want = "v0.21" if self.label == "after" else "v0.20"
        if not self.check.expect(self.ui == want, f"the page is the {want} one that --label {self.label} means", f"saw {self.ui}"):
            raise Stop("the label does not match the version the console serves")
        self.c.ok("/api/setup/daily-limit", "POST", {"daily_usd": DAILY_START})
        self.c.ok("/api/config", "POST", {"chat_limits": {"per_turn_usd": PER_TURN_CLAUDE}, "welcome_seen": True})
        self.check.ok("the day's limit is US$2.00 and the per-turn limit US$0.03 (put back at the end)")
        self.read_other()
        self.mark_started()
        if self.haiku:
            self.verify_chat()

    def other_label(self) -> str:
        return "after" if self.label == "before" else "before"

    def read_other(self) -> None:
        """Find out what the other version spent. Its result file is read (and has to hold a readable amount of money); without one, its start
        marker says whether it ever began: if it did, the amount is unknown, and if it did not, this is the first of the pair."""
        other = self.other_label()
        path = self.out_dir / f"qa47-{other}.json"
        if not os.path.lexists(path):
            # no result file at all: the marker tells whether the other version ever began
            if (self.out_dir / f"started-{other}.txt").exists():
                self.other, self.other_state = None, "unknown"
            else:
                self.other, self.other_state = None, "none"
        else:
            # a file that is there but cannot be read, parsed or checked is never "the first of the pair": what it spent is unknown
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = None
            if data is None:
                self.other, self.other_state = None, "unknown"
            else:
                self.other = data
                self.other_state = "known" if result_ok(data) and data.get("label") == other and money((data.get("money") or {}).get("ledger_end")) is not None else "unknown"
        if self.other_state == "unknown":
            self.check.warn(f"what the {other} run spent is not known, so no step that spends Claude's money will be done")

    def mark_started(self) -> None:
        """The marker that tells the other version this one began. When it cannot be kept, the next run could take this one for never started and
        count its day as zero, so this run spends nothing."""
        try:
            (self.out_dir / f"started-{self.label}.txt").write_text("started\n", encoding="utf-8")
            self.marker_kept = True
        except OSError:
            self.marker_kept = False
            self.check.warn("the start marker could not be written, so no step that spends Claude's money will be done")

    def verify_chat(self) -> None:
        """The chat check of Claude Code (the person's own login; about US$0.01 to 0.05, not counted in the day's limit): reserved first."""
        if not self.money_ok(CHAT_CHECK_RESERVE, checks=0):
            self.check.fail("the Claude cap would be passed by the chat check: not run")
            raise Stop("over the Claude cap")
        code, data = self.c.call("/api/chat-support")
        if code == 200 and ((data or {}).get("support") or {}).get("state") == "verified":
            self.check.ok("Claude Code's chat is already verified in this state folder")
            return
        self.c.ok("/api/chat-support/verify", "POST", {"engine": "claude"})
        self.wait("the chat check", lambda: (lambda d: ((d or {}).get("support") or {}).get("state") == "verified")(self.c.call("/api/chat-support")[1]),
                  cap=WAIT_CAP_S, every=3.0)
        self.check.ok("Claude Code's chat check passed")

    # -- the tasks ---------------------------------------------------------------------------------------------------------------

    def run_all(self) -> None:
        for n, name in enumerate(TASKS, 1):
            if self.over():
                self.check.fail("the 20 minutes of the whole run are over", name)
                self.tasks[name] = {**summarize([], "the time cap of the run"), "error": "time cap"}
                continue
            self.w.steps = []
            try:
                getattr(self, f"task_{name}")()
            except Unable as exc:
                self.tasks[name] = summarize(self.w.steps, str(exc))
                self.check.ok(f"task {n} {name}: unable here", str(exc))
            except Stop as exc:
                self.tasks[name] = {**summarize(self.w.steps), "done": False, "error": str(exc)[:160]}
                self.check.fail(f"task {n} {name}: stopped", str(exc)[:160])
            else:
                t = self.tasks[name]
                self.check.ok(f"task {n} {name}", f"{t['steps']} steps, {t['stuck']} stuck, {t['read']} characters to read")
            if isinstance(self.tasks.get(name), dict):
                self.tasks[name]["end_page"] = page_head(self.page.route())
            self.shot(f"{n}-{name}")

    def play(self, key: str, name: str | None = None) -> None:
        spec = PATHS[self.label][key]
        start = spec["start"]
        if start == "chat":
            if not self.chat:
                self.find_chat()
            if not self.chat:
                raise Unable("there is no conversation with a CEO to start from (it needs a model: --haiku)")
            start = f"#/chat/{self.chat}"
        self.w.begin(start)
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
                continue                                   # the screen is already past this one
            if kind == "press":
                got = self.w.press(sel)
                if got is None:
                    raise Unable(f"{sel} is not on the page")
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
        try:
            self.play("first")
            if self.dead_end and isinstance(self.tasks.get("first"), dict):
                self.tasks["first"]["dead_end"] = self.dead_end
        except Unable as exc:
            # nothing can be done without a ready AI tool: the console is told the start-up is over so the other tasks begin at the home page
            self.c.call("/api/config", "POST", {"setup_done": True})
            raise exc

    def task_limit(self) -> None:
        self.play("limit")

    def task_routine(self) -> None:
        if not self.profiles():
            made = self.c.call("/api/agent-profiles", "POST", {"name": "QA47 虛構員工", "position": "executor", "instructions": "QA47 虛構",
                                                               "launch_mode": "safe", "model": {"tool": "claude", "model_id": "haiku"}})
            pid = (((made[1] or {}).get("profile") or {}).get("id")) if made[0] == 200 and isinstance(made[1], dict) else None
            if not isinstance(pid, str):
                raise Unable("an employee for the routine could not be made")
            self.made["profiles"].append(pid)
        self.play("routine")

    def task_card(self) -> None:
        if not self.haiku:
            raise Unable("a permission card needs a model to ask for one (--haiku); its words are checked by tests/frontend/p47_chat.cjs")
        self.play("card")

    def task_blocked(self) -> None:
        if self.haiku and self.chat and (self.ledger() or 0.0) >= 0.01:
            self.c.ok("/api/setup/daily-limit", "POST", {"daily_usd": 0.01})
            self.play("blocked_sent", "blocked")
        else:
            self.play("blocked_find", "blocked")
            self.notice["variant"] = "find"
        t = self.tasks["blocked"]
        if self.notice.get("text"):
            t["notice"] = self.notice["text"][:240]

    # -- what the script itself does after a step ----------------------------------------------------------------------------------

    def new_profile(self) -> str | None:
        found = [p for p in self.profiles() if p.get("id") not in self.orig["profiles"] and p.get("id") not in self.made["profiles"]]
        return found[-1].get("id") if found else None

    def then_ceo_made(self) -> None:
        pid = self.wait("the CEO card", self.new_profile, cap=15, every=0.5)
        self.ceo = pid
        self.made["profiles"].append(pid)
        if self.haiku:
            # the card is made by the page with the tool's default model; Haiku is the cheap one, so the script sets it before anything is sent
            card = next(p for p in self.profiles() if p.get("id") == pid)
            body = {k: v for k, v in card.items() if k not in ("id", "_unresolved", "created_at", "revision", "updated_at")}
            body["model"] = {"tool": (card.get("model") or {}).get("tool", "claude"), "model_id": "haiku"}
            self.c.ok(f"/api/agent-profiles/{pid}", "POST", body)
        self.sleep(1.0)
        self.page.settle()
        code, data = self.c.call("/api/chats")
        mine = [c for c in (data or {}).get("chats", []) if isinstance(c, dict) and c.get("profile_id") == pid] if code == 200 and isinstance(data, dict) else []
        if mine:
            self.chat = mine[0].get("id")
            self.made["chats"].append(self.chat)

    def chat_state(self):
        """What GET /api/chat-support says of Claude Code's chat: its state word, or None when it cannot be read."""
        code, data = self.c.call("/api/chat-support")
        support = (data or {}).get("support") if code == 200 and isinstance(data, dict) else None
        state = support.get("state") if isinstance(support, dict) else None
        return state if isinstance(state, str) else None

    def then_chat_usable(self) -> None:
        """Without a model the walk ends at the chat box or at the prepare page's one action. A chat box that cannot be used (the tool is not
        checked for chat, an administrator's policy holds it back, or the state cannot be read) is a dead end, whatever the box looks like."""
        self.dead_end = None
        if self.haiku or self.last_look != CHAT_INPUT:
            return
        state = self.chat_state()
        if state == "verified":
            return
        self.dead_end = f"the chat box was reached, but the chat cannot be used ({'the state could not be read' if state is None else 'state ' + state})"
        self.w.dead_end(self.dead_end)
        self.check.warn("task 1 ends in a chat box that cannot be used", self.dead_end)

    def then_first_reply(self) -> None:
        chat = self.chat or self.find_chat()
        if not chat:
            raise Stop("no conversation with the CEO was opened")
        self.wait("the end of the first turn", lambda: self.turn_ended(chat))

    def find_chat(self):
        if not self.ceo:
            return None
        code, data = self.c.call("/api/chats")
        mine = [c for c in (data or {}).get("chats", []) if isinstance(c, dict) and c.get("profile_id") == self.ceo] if code == 200 and isinstance(data, dict) else []
        if mine:
            self.chat = mine[0].get("id")
            if self.chat not in self.made["chats"]:
                self.made["chats"].append(self.chat)
        return self.chat

    def records(self, chat: str) -> list:
        code, data = self.c.call(f"/api/chats/{chat}?after=0")
        return [r for r in (data or {}).get("records", []) if isinstance(r, dict)] if code == 200 and isinstance(data, dict) else []

    def turn_ended(self, chat: str, count: int = 1) -> bool:
        return sum(1 for r in self.records(chat) if r.get("kind") == "turn_ended") >= count

    def then_wait_card(self) -> None:
        chat = self.chat or self.find_chat()
        if not chat:
            raise Stop("no conversation with the CEO was opened")
        self.wait("the permission card", lambda: any(r.get("kind") == "card" for r in self.records(chat)))
        self.page.settle()

    def then_card_refused(self) -> None:
        chat = self.chat
        self.wait("the refusal to be recorded", lambda: any(r.get("kind") == "card_decision" for r in self.records(chat)), cap=30)
        self.wait("the end of the turn", lambda: self.turn_ended(chat, 2), cap=WAIT_CAP_S)

    def then_limit_saved(self) -> None:
        self.page.settle()
        got = self.c.call("/api/meetings/ledger")
        value = money(got[1].get("daily_usd")) if got[0] == 200 and isinstance(got[1], dict) else None
        self.check.expect(value == 5.0, "the day's limit is now US$5", f"{value}")

    def then_routine_saved(self) -> None:
        self.page.settle()
        code, data = self.c.call("/api/routines")
        mine = [r for r in (data or {}).get("routines", []) if isinstance(r, dict) and str(r.get("name", "")).startswith("QA47")] if code == 200 and isinstance(data, dict) else []
        mine = [r for r in mine if r.get("id") not in self.orig.get("routines", set())]       # one that was there before the run began is not this run's
        for r in mine:
            if r.get("id") not in self.made["routines"]:
                self.made["routines"].append(r.get("id"))
        r = mine[0] if mine else {}
        self.check.expect(bool(mine), "the routine was saved")
        self.check.expect(r.get("enabled") is True and sorted(r.get("days") or []) == list(range(7)) and r.get("times") == ["08:00"],
                          "it is switched on, every day, at 08:00", f"enabled {r.get('enabled')}, {len(r.get('days') or [])} days, times {r.get('times')}")

    def then_blocked_notice(self) -> None:
        self.page.settle()
        self.sleep(1.0)
        for sel in ('[data-limit="reached"]', '[data-chat="limit-box"]', '[data-chat="send-note"]', '[data-home="ask-result"]'):
            text = self.page.text_of(sel).strip()
            if text:
                self.notice["text"] = " ".join(text.split())
                break
        self.notice.setdefault("variant", "sent")

    # -- the phone and the end -----------------------------------------------------------------------------------------------------

    def phone_walk(self) -> None:
        self.page.viewport(*PHONE)
        try:
            self.page.goto("#/")
            self.shot("phone-home")
            if self.chat:
                self.page.goto(f"#/chat/{self.chat}")
                top = self.page.box_top(CHAT_INPUT)
                self.phone["chat_input_px"] = top if isinstance(top, int) else None
                self.shot("phone-chat")
            self.phone["size"] = f"{PHONE[0]}x{PHONE[1]}"
        finally:
            self.page.viewport(*DESKTOP)

    def cleanup(self) -> None:
        """Delete what this run made and put the two limits back."""
        def drop(path, method="POST", body=None):
            code, _ = self.c.call(path, method, body)
            return code in (200, 201, 202, 204, 404)
        code, data = self.c.call("/api/routines")
        for r in ((data or {}).get("routines") or []) if code == 200 and isinstance(data, dict) else []:
            if isinstance(r, dict) and r.get("id") in self.made["routines"] and r.get("id") not in self.orig.get("routines", set()):
                drop(f"/api/routines/{r.get('id')}/delete", "POST", {})
        code, data = self.c.call("/api/chats")
        for c in ((data or {}).get("chats") or []) if code == 200 and isinstance(data, dict) else []:
            if isinstance(c, dict) and (c.get("id") in self.made["chats"] or c.get("profile_id") in self.made["profiles"]):
                drop(f"/api/chats/{c.get('id')}", "DELETE")
        for pid in self.made["profiles"]:
            drop(f"/api/agent-profiles/{pid}/delete", "POST", {})
        if self.orig.get("daily") is not None:
            self.c.call("/api/setup/daily-limit", "POST", {"daily_usd": self.orig["daily"]})
        if self.orig.get("per_turn") is not None:
            self.c.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": self.orig["per_turn"]}})

    def final(self) -> None:
        left = [p for p in self.profiles() if p.get("id") not in self.orig.get("profiles", set())]
        self.check.expect(not left, "every employee this run made is deleted", f"{len(left)} left")
        code, data = self.c.call("/api/meetings/ledger")
        daily = money(data.get("daily_usd")) if code == 200 and isinstance(data, dict) else None
        self.check.expect(daily == self.orig.get("daily"), "the day's limit is what it was", f"{daily}")

    def result(self) -> dict:
        ledger_end = self.ledger()
        if ledger_end is None:                       # not known is not zero: it stays null, is a FAIL, and the other version then spends nothing
            self.check.fail("the day's ledger could not be read at the end, so the amount spent is not known")
        return {"label": self.label, "mode": "haiku" if self.haiku else "no-ai", "ui": self.ui, "tasks": self.tasks, "phone": self.phone,
                "money": {"ledger_end": ledger_end, "claude_cap": self.cap, "chat_check_reserve": CHAT_CHECK_RESERVE if self.haiku else 0.0},
                "shots": self.shots, "checks": {"ok": self.check.passed, "warn": self.check.warned, "fail": self.check.failed}}


def main(argv=None, out=print, console_factory=Console, browser_factory=Browser, page_factory=Page, clock=time.monotonic, sleep=time.sleep,
         home: Path | None = None, app_js: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="v0.21.0 real check of the plain navigation (see the file's docstring)")
    ap.add_argument("--state", help="the temporary state folder of the console (VBEAR_HOME)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="the console's port (never 7788 or 7789)")
    ap.add_argument("--label", choices=LABELS, help="which version this console serves: before (v0.20.0) or after (v0.21.0)")
    ap.add_argument("--chrome", help="the path of the Chrome program")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--no-ai", action="store_true", help="spend nothing (the default)")
    mode.add_argument("--haiku", action="store_true", help="also use Claude Code on Haiku (hard cap US$0.30)")
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
    state = Path(args.state).expanduser().resolve()
    work = state.parent
    check = Check(out)
    tables = read_tables(app_js or Path(__file__).resolve().parent.parent / "web" / "app.js")
    if tables.get("why"):
        check.warn("the vocabulary tables were not read, so no word is judged", tables["why"])
    browser = run = None
    try:
        console = console_factory(args.port, read_token(state, args.port))
        browser = browser_factory(args.chrome, work / f"chrome-{args.label}")
        page = page_factory(browser, f"http://127.0.0.1:{args.port}")
        run = Run(console, page, Walker(page, tables, clock, sleep), state, args.label, bool(args.haiku), args.claude_cap, check, work, clock, sleep)
        run.start()
        run.run_all()
        run.phone_walk()
    except Stop as exc:
        check.fail("stopped", str(exc))
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
    if run is not None and len(run.tasks) == len(TASKS):
        try:
            (work / f"qa47-{args.label}.json").write_text(json.dumps(run.result(), ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            check.fail("the result file could not be written", str(exc)[:80])
    out(f"qa_p47 ({args.label}, {'haiku' if args.haiku else 'no-ai'}): {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
