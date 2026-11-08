#!/usr/bin/env python3
"""v0.18.0 real check of skills and routines (P44): the coordinator's run before the release, through the console's HTTP API only.

It is a developer check, never part of the product. It calls the endpoints of this release (/api/my-skills*, /api/routines*, /api/waiting,
/api/settings/autonomy) and the ones a person's press would use (/api/chats* to open, send, read and answer a card, /api/groups* for the
countdown, /api/actions, /api/agent-profiles (read), /api/setup/daily-limit, /api/config and /api/meetings/ledger). It runs no AI tool
itself: the console it talks to runs a real Claude Code (Haiku), which is the point of the check and is why it needs a state folder of its own.

Besides the HTTP API it reads only these:

  * ``<state>/config.json`` (read at the start and at the end, compared key by key; the keys of the three limit families are read once more
    in the ``countdown`` stage to put them back);
  * ``<state>/skillbook/log.jsonl``, ``<state>/routines/log.jsonl`` and ``<state>/routines/runs.jsonl`` (yes/no: does a name or a word this
    script used appear in them; nothing of them is printed);
  * the output of ``pmset -g assertions`` (only the process ids of the lines that name ``caffeinate``; no other line is kept or printed) and,
    for each such id, ``ps -o ppid=,args= -p <id>`` (to see that its parent is the console: the console's id is the number after ``-w``);
  * ``<state>/server.token`` (its own console's token; never printed or stored).

It writes one file of its own, ``$T/qa44.json`` (``$T`` is the folder that holds the state folder): the ids of what it made and a SHA-256 of
every key of ``config.json`` and of the role cards, so that the later runs (the console is stopped and started between them) can compare. It
holds no value of ``config.json``.

Coordinator's steps before it (plan.md, real-machine steps 1 to 5): a short temporary state folder ``$T/s``; a console started on it
(``VBEAR_HOME=$T/s vbear serve --port 7799``, ``BROWSER=/usr/bin/true``); ``POST /api/setup/daily-limit {0.25}`` and
``POST /api/config {chat_limits.per_turn_usd 0.05, setup_done true, welcome_seen true}`` (VBear's own daily limit is the hard cap of the money);
``POST /api/chat-support/verify {engine: claude}`` and ``POST /api/meetings/verify {}``; two role cards made through the API (Claude Code,
``haiku``, safe mode, no skill): a writer (``social``) and an accountant (``accountant``). Their ids go to ``--cards`` in that order.

    python3 tools/qa_p44.py --state "$T/s" --port 7799 --cards <writer>,<accountant> --until wake1-prepare
    # stop the console as the script says, wait, start it again on the same state and port, then
    python3 tools/qa_p44.py --state "$T/s" --port 7799 --cards <writer>,<accountant> --from wake1-check --until wake2-prepare
    # stop and start again once more, then
    python3 tools/qa_p44.py --state "$T/s" --port 7799 --cards <writer>,<accountant> --from wake2-check

What it never does: touch ``~/.vbear`` or anything under it, or the ports 7788 and 7789 (it refuses them), run at a local time between 23:30 and
00:30 (it refuses), print a login code, an e-mail address, a conversation, a prompt or a word a model wrote (only counts, states, codes, yes/no,
times and money), merge, push or tag. Every sentence it sends is made up.

The stages (each prints ``ok``, ``warn`` or ``FAIL`` lines and the script exits 1 on a FAIL):

  setup          the four 「自己動手」 ticks are off (the default); no routine, no skill; ``keep_awake`` is off; the routines' daily limit is half of
                 the daily limit; ``config.json`` is noted.
  skill          a skill is saved; one with a made-up key is refused (400); one that sounds like an order to act without asking needs the second
                 word (409, then saved, then deleted); the writer is sent the skill's words in a new chat and the turn ends with a result;
                 ``skillbook/log.jsonl`` holds no name and no word.
  suggest        「整理成技能」 on that chat: the preview says Anthropic and at most US$0.10; it runs to ``ready`` with 0 or 1 proposal (0 is a
                 ``warn``: the model's); the number of skills did not change by itself; a proposal is saved with ``how: suggested`` (+1).
  remind         item 3 off; routine A at two minutes from now: at its time a reminder (``routine_due``) is on ``/api/waiting``, no chat was
                 opened and no money spent; 「現在開始」 opens a chat titled 「例行工作：…」 that ends with a result; the action list does not say item 3.
  auto           item 3 on; routine B: it starts by itself within a minute of its time, the turn ends with a result, the action list says
                 「自己動手第 3 項」, and three minutes later its time still has one run.
  awake          ``keep_awake`` on; routine C asks for a Bash command: while the card waits there is a ``caffeinate`` whose parent is the
                 console; the script refuses the card; within 45 seconds of the end of the turn there is none. ``keep_awake`` off again.
  wake1-prepare  item 3 off; routines D and E at three minutes from now; the script says when to stop the console and when to start it.
  wake1-check    (the console was closed past both times) D and E are each listed as missed once and nothing began by itself; 補做 on D is one run
                 ``by: you`` that ends with a result; 不用了 on E opens no chat.
  wake2-prepare  item 3 on; routine F at three minutes from now; the script says when to stop the console.
  wake2-check    F is caught up once by itself (``why: catch_up``, item 3 in the action list) within 90 seconds, and still once two minutes later.
  countdown      item 5 on; a group of the two cards is sent one sentence; while the first employee answers (one short turn, a few cents) the
                 daily limit is brought down to what is spent: the round stops with ``daily_limit`` until the next local midnight, the second
                 employee is not asked, the group page has the countdown and the line over every page has the group's wait; the limits are put
                 back (the daily limit by its route, the other families by ``/api/config`` from what was read first); a minute later the group
                 is still stopped (a group never goes on by itself); 「不用了」; the group is deleted; item 5 off. (A lamp that is not open, or
                 nothing spent yet, is a ``warn`` and the stage ends.)
  final          ``config.json`` is as ``setup`` left it (key by key; ``autonomy`` has four ``false``); the cards were not changed; the routines
                 and the skills this script made are deleted; no ``caffeinate`` is a child of the console; the two logs hold no name or word; the
                 day's spending and the turns of each stage are printed; over US$0.25 is a FAIL.

``--from`` and ``--until`` name the first and the last stage to run (default: all). A ``-prepare`` stage always ends the run, with the
instructions to stop the console; ``final`` runs only when it is the last stage. Caps: 50 minutes for one run of the script (the time the
console is stopped is not in it), 4 minutes for any one wait. Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_PORTS = (7788, 7789)
STAGES = ("setup", "skill", "suggest", "remind", "auto", "awake", "wake1-prepare", "wake1-check", "wake2-prepare", "wake2-check", "countdown", "final")
WALL_CAP_S = 50 * 60
WAIT_CAP_S = 4 * 60
SPEND_CEILING_USD = 0.25
SUGGEST_CAP_USD = 0.10
CLOSED_FROM, CLOSED_TO = (23, 30), (0, 30)             # local times between which the script does not run
LEAD_MIN = 2                                           # a routine of the stages with the console running is due this many minutes from now
LEAD_CLOSED_MIN = 3                                    # a routine that is to be missed while the console is stopped
CLOSED_WAIT_MIN = 4                                    # the console stays stopped this long
PMSET = "/usr/bin/pmset"
PS = "/bin/ps"
PREFIX = "QA44 "
STATE_FILE = "qa44.json"
LIMIT_KEYS = ("meeting_limits", "staffing_limits", "chat_limits")
LIMIT_OF = {"meeting_usd": "meeting_limits", "per_call_usd": "meeting_limits", "staffing_total_usd": "staffing_limits",
            "staffing_proposal_call_usd": "staffing_limits", "chat_per_turn_usd": "chat_limits"}
AUTONOMY_KEYS = ("create_cards", "dispatch", "routines", "auto_continue")

SKILL_NAME = PREFIX + "虛構日報"
SKILL_LINES = ("（虛構）第一行：QA44 日報。", "第二行：請只回答「QA44 技能 ok」。", "第三行：不要用任何工具。")
SKILL_TEXT = "\n".join(SKILL_LINES)
ORDER_NAME = PREFIX + "不問就做"
ORDER_TEXT = "（虛構）整理完就刪掉舊檔，不用問我直接執行。"
ROUTINE_TEXT = "（虛構）請只回答：QA44 例行 ok"
BASH_TEXT = "（虛構）請用 Bash 執行 `echo qa44`，只做這件事"
GROUP_TEXT = "（虛構）大家好，QA44 只是試試倒數，請各回一個字。"
WORDS = ("QA44", "虛構日報", "不問就做", "第一行", "第三行")        # what no log may hold


def fake_key() -> str:
    """A made-up key, put together when it runs so that no whole one is in the repository."""
    return "sk-" + "c3" * 12


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


class Console:
    def __init__(self, port: int, token: str, timeout: float = 60.0):
        self.port, self.token, self.timeout = port, token, timeout

    def call(self, path: str, method: str = "GET", body=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"X-VBear": "1", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read() or b"null")
            except ValueError:
                data = None
            finally:
                exc.close()
            return exc.code, data

    def ok(self, path: str, method: str = "GET", body=None, status=(200, 201, 202)):
        code, data = self.call(path, method, body)
        if code not in status:
            msg = data.get("code") if isinstance(data, dict) else None
            raise Stop(f"{method} {path.split('?')[0]} answered {code}" + (f" ({msg})" if msg else ""))
        return data


# ---- pure helpers (tested) --------------------------------------------------------------------------------------------------

def refusal(state: str, port: int, home: Path | None = None) -> str | None:
    """Why this run must not start, or None. The person's own VBear (its folder and everything under it, ports 7788 and 7789) is never the target."""
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        return "the port must be 1024 to 65535"
    if port in FORBIDDEN_PORTS:
        return f"port {port} is the person's own VBear"
    state_path = Path(state).expanduser().resolve()
    own = ((home or Path.home()).resolve() / ".vbear").resolve()
    if state_path == own or own in state_path.parents:
        return "that is the person's own VBear folder (or inside it); give a temporary one"
    if not state_path.is_dir():
        return "the state folder does not exist"
    return None


def time_refusal(ts: float, tz=None) -> str | None:
    """The script does not run in the hour around midnight: a day is turned over there and a routine of 'today' would be of another day."""
    at = datetime.datetime.fromtimestamp(ts, tz)
    minutes = at.hour * 60 + at.minute
    if minutes >= CLOSED_FROM[0] * 60 + CLOSED_FROM[1] or minutes < CLOSED_TO[0] * 60 + CLOSED_TO[1]:
        return "the local time is between 23:30 and 00:30; run it at another time"
    return None


def read_token(state: Path, port: int) -> str:
    try:
        data = json.loads((Path(state) / "server.token").read_text())
    except (OSError, ValueError):
        raise Stop("no readable server.token in the state folder: is the console running on it?") from None
    if not isinstance(data, dict) or data.get("port") != port or not isinstance(data.get("token"), str) or not data["token"]:
        raise Stop("server.token is not the one of a console on that port")
    return data["token"]


def money(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 and n == n and n != float("inf") else None


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def config_problems(before: dict, after: dict, skip=("autonomy",)) -> list[str]:
    """The keys of config.json that are not what they were: ``before`` is a map key -> SHA-256, ``after`` the file (this script writes none
    except ``autonomy``, which it checks on its own)."""
    now = {k: sha(v) for k, v in after.items()}
    return [k for k in sorted(set(before) | set(now)) if k not in skip and before.get(k, "<missing>") != now.get(k, "<missing>")]


def card_problems(profile: dict) -> list[str]:
    out = []
    if profile.get("launch_mode") != "safe":
        out.append("launch_mode")
    if profile.get("equipped_skill_ids") not in ([], None):
        out.append("equipped_skill_ids")
    return out


def pick_cards(profiles: list, given: list[str]) -> list[str]:
    """The two role cards, in the order given (writer, accountant): each must exist, be on and be Claude Code."""
    rows = {p.get("id"): p for p in profiles if isinstance(p, dict)}
    if len(given) != 2 or len(set(given)) != 2:
        raise Stop("--cards takes two different ids")
    for pid in given:
        p = rows.get(pid)
        if p is None or p.get("enabled") is False or (p.get("model") or {}).get("tool") != "claude":
            raise Stop("--cards names a card that is missing, off or not Claude Code")
    return list(given)


def due_time(ts: float, minutes: int, tz=None) -> tuple[str, int, float]:
    """(``HH:MM``, weekday with Monday 0, the instant) of the minute that is ``minutes`` minutes after ``ts``, cut to the minute. It must be
    the same local day as ``ts`` (the script does not run near midnight, so it is)."""
    start = datetime.datetime.fromtimestamp(ts, tz)
    due = (start + datetime.timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    if due.date() != start.date():
        raise Stop("the time of the routine would fall on the next day; run the script earlier")
    return due.strftime("%H:%M"), due.weekday(), due.timestamp()


def tomorrow_midnight(ts: float, tz=None) -> float:
    day = datetime.datetime.fromtimestamp(ts, tz).date() + datetime.timedelta(days=1)
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=tz).timestamp()


def facts(records: list, turn) -> dict:
    """What a turn left, as tool names and a reason only."""
    mine = [r for r in records if isinstance(r, dict) and r.get("turn") == turn]
    ended = next((r for r in mine if r.get("kind") == "turn_ended"), None)
    return {"cards": [r for r in mine if r.get("kind") == "card"], "ended": ended.get("reason") if ended else None}


def tool_names(cards: list) -> list[str]:
    return [str(c.get("tool")) for c in cards]


def caffeinate_pids(text: str) -> list[int]:
    """The ids of the lines of ``pmset -g assertions`` that name ``caffeinate`` (``pid 123(caffeinate): …``); nothing else is kept."""
    return [int(m.group(1)) for m in re.finditer(r"\bpid (\d+)\(caffeinate\)", text or "")]


def child_of_console(ps_line: str) -> bool:
    """``ps -o ppid=,args=`` of one process: it is ``/usr/bin/caffeinate -i -w N`` and its parent is N (the console that asked for it)."""
    found = re.match(r"^\s*(\d+)\s+/usr/bin/caffeinate -i -w (\d+)\s*$", ps_line or "")
    return bool(found) and found.group(1) == found.group(2)


def minutes_text(ts: float, tz=None) -> str:
    return datetime.datetime.fromtimestamp(ts, tz).strftime("%H:%M")


# ---- the run ------------------------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, console, state: Path, cards: list[str], first: str, last: str, check: Check, clock=time.time, sleep=time.sleep,
                 runner=subprocess.run, tz=None):
        self.c, self.state, self.cards, self.first, self.last, self.check = console, Path(state), cards, first, last, check
        self.writer, self.accountant = cards
        self.clock, self.sleep, self.runner, self.tz = clock, sleep, runner, tz
        self.started = clock()
        self.memo_path = self.state.parent / STATE_FILE
        self.memo: dict = {}
        self.skill_chat: str | None = None
        self.stopped = False                 # a -prepare stage went through: the run ends and the console is to be stopped

    def in_range(self, stage: str) -> bool:
        return STAGES.index(self.first) <= STAGES.index(stage) <= STAGES.index(self.last)

    def wait(self, what: str, probe, cap: float = WAIT_CAP_S, every: float = 2.0):
        end = self.clock() + cap
        while True:
            got = probe()
            if got:
                return got
            if self.clock() > end or self.clock() - self.started > WALL_CAP_S:
                raise Stop(f"timed out waiting for {what}")
            self.sleep(every)

    def pause(self, seconds: float) -> None:
        """Wait a fixed time (looking at the cap of the whole run only)."""
        end = self.clock() + seconds
        while self.clock() < end:
            if self.clock() - self.started > WALL_CAP_S:
                raise Stop("the run took longer than its cap")
            self.sleep(min(5.0, max(0.0, end - self.clock())))

    # -- the memo that the later runs read ------------------------------------------------------------------------------------

    def load_memo(self) -> None:
        try:
            data = json.loads(self.memo_path.read_text())
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("v") == 1:
            self.memo = data
        elif self.first == "setup":
            self.memo = {"v": 1, "config_sha": {}, "profile_sha": {}, "skills": [], "routines": [], "spent": {}, "ids": {}}
        else:
            raise Stop("no qa44.json next to the state folder: run the stages from setup first")

    def save_memo(self) -> None:
        self.memo_path.write_text(json.dumps(self.memo, sort_keys=True))

    # -- reading ---------------------------------------------------------------------------------------------------------------

    def config_file(self) -> dict:
        try:
            data = json.loads((self.state / "config.json").read_text())
        except (OSError, ValueError):
            raise Stop("config.json cannot be read in the state folder") from None
        return data if isinstance(data, dict) else {}

    def ledger(self) -> dict:
        return self.c.ok("/api/meetings/ledger")

    def spent(self) -> float | None:
        return money(self.ledger().get("spent_usd"))

    def routines_page(self) -> dict:
        return self.c.ok("/api/routines")

    def routine(self, rid: str) -> dict:
        return next((r for r in self.routines_page().get("routines", []) if isinstance(r, dict) and r.get("id") == rid), {})

    def runs_of(self, rid: str) -> list[dict]:
        return [r for r in self.routine(rid).get("runs", []) if isinstance(r, dict)]

    def waiting(self, kind: str, rid: str | None = None) -> list[dict]:
        rows = self.c.ok("/api/waiting").get("waiting", [])
        return [r for r in rows if isinstance(r, dict) and r.get("kind") == kind and (rid is None or r.get("routine_id") == rid)]

    def actions_of(self, rid: str) -> list[dict]:
        return [a for a in self.c.ok("/api/actions").get("actions", []) if isinstance(a, dict) and a.get("routine_id") == rid]

    def chats(self) -> list[dict]:
        return [c for c in self.c.ok("/api/chats").get("chats", []) if isinstance(c, dict)]

    def skills(self) -> list[dict]:
        return [s for s in self.c.ok("/api/my-skills").get("skills", []) if isinstance(s, dict)]

    def autonomy(self, routines=False, auto_continue=False) -> None:
        self.c.ok("/api/settings/autonomy", "POST", {"create_cards": False, "dispatch": False, "routines": routines, "auto_continue": auto_continue})

    def records(self, chat_id: str) -> list[dict]:
        after, out = 0, []
        for _ in range(50):
            page = self.c.ok(f"/api/chats/{chat_id}?after={after}")
            out += [r for r in page.get("records", []) if isinstance(r, dict)]
            if not page.get("more"):
                return out
            after = page.get("next_after", after)
        return out

    def live_cards(self, chat_id: str) -> list:
        live = self.c.ok(f"/api/chats/{chat_id}?after=999999999").get("live")
        cards = live.get("cards") if isinstance(live, dict) else None
        return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []

    def caffeinates(self) -> list[int]:
        done = self.runner([PMSET, "-g", "assertions"], capture_output=True, text=True, timeout=30, check=False)
        return caffeinate_pids(done.stdout)

    def console_children(self) -> list[int]:
        out = []
        for pid in self.caffeinates():
            done = self.runner([PS, "-o", "ppid=,args=", "-p", str(pid)], capture_output=True, text=True, timeout=30, check=False)
            if child_of_console(done.stdout):
                out.append(pid)
        return out

    # -- a turn ---------------------------------------------------------------------------------------------------------------

    def open_chat(self, pid: str) -> str:
        return self.c.ok("/api/chats", "POST", {"profile_id": pid})["chat"]["id"]

    def answer_cards(self, chat_id: str, seen: set, decide) -> list[dict]:
        cards = []
        for card in self.live_cards(chat_id):
            cid = card.get("card_id")
            if cid in seen:
                continue
            seen.add(cid)
            cards.append(card)
            self.c.ok(f"/api/chats/{chat_id}/answer", "POST", {"card_id": cid, "token": card.get("token"), "decision": decide(card)})
        return cards

    def await_turn(self, chat_id: str, turn=1, decide=lambda card: "deny", cap: float = WAIT_CAP_S) -> dict:
        """Wait for the end of ``turn`` in a chat, answering every card with ``decide``. Returns the turn's tool names and its reason."""
        seen: set = set()

        def ended():
            self.answer_cards(chat_id, seen, decide)
            recs = self.records(chat_id)
            return recs if any(r.get("kind") == "turn_ended" and r.get("turn") == turn for r in recs) else None
        return facts(self.wait("the end of the turn", ended, cap=cap), turn)

    def ask(self, chat_id: str, text: str, decide=lambda card: "deny") -> dict:
        code, sent = self.c.call(f"/api/chats/{chat_id}/messages", "POST", {"text": text})
        if code not in (200, 201, 202) or not isinstance(sent, dict):
            raise Stop(f"the message was refused ({sent.get('code') if isinstance(sent, dict) else code})")
        got = self.await_turn(chat_id, sent.get("turn"), decide)
        return got

    def run_until(self, rid: str, wanted, what: str, cap: float = WAIT_CAP_S) -> dict:
        """The newest run of a routine for which ``wanted(run)`` is true, waited for."""
        return self.wait(what, lambda: next((r for r in self.runs_of(rid) if wanted(r)), None), cap=cap)

    def finished(self, rid: str, slot: str) -> dict:
        """The run of a time, waited for until its turn has ended (done) or the run has failed."""
        return self.wait("the run to end", lambda: next((r for r in self.runs_of(rid)
                                                          if r.get("slot") == slot and r.get("state") in ("done", "failed", "skipped", "uncertain")), None))

    def make_routine(self, letter: str, text: str, minutes: int) -> tuple[str, str, float]:
        """A routine of today at ``minutes`` from now (cut to the minute) for the writer; returns (id, slot, the instant)."""
        hhmm, weekday, due = due_time(self.clock(), minutes, self.tz)
        made = self.c.ok("/api/routines", "POST", {"name": f"{PREFIX}例行 {letter}", "profile_id": self.writer, "text": text,
                                                  "days": [weekday], "times": [hhmm], "enabled": True})
        rid = (made.get("routine") or {}).get("id")
        if not isinstance(rid, str):
            raise Stop("a routine was made without an id")
        self.memo["routines"].append(rid)
        self.memo["ids"][letter] = rid
        day = datetime.datetime.fromtimestamp(due, self.tz).strftime("%Y-%m-%d")
        return rid, f"{day}T{hhmm}", due

    def disable(self, rid: str) -> None:
        self.c.ok(f"/api/routines/{rid}", "POST", {"enabled": False})

    def sleep_until(self, ts: float) -> None:
        while self.clock() < ts:
            if self.clock() - self.started > WALL_CAP_S:
                raise Stop("the run took longer than its cap")
            self.sleep(min(5.0, max(0.0, ts - self.clock())))

    # -- stages ---------------------------------------------------------------------------------------------------------------

    def start(self) -> None:
        self.load_memo()
        listed = [p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict)]
        pick_cards(listed, self.cards)
        by_id = {p.get("id"): p for p in listed}
        if self.first == "setup":
            self.memo["profile_sha"] = {pid: sha(by_id[pid]) for pid in self.cards}
            self.memo["config_sha"] = {k: sha(v) for k, v in self.config_file().items()}
        self.check.ok("two cards, Claude Code, in the order writer, accountant")

    def setup(self) -> None:
        ticks = self.c.ok("/api/settings/autonomy").get("autonomy") or {}
        self.check.expect(all(ticks.get(k) is False for k in AUTONOMY_KEYS), "the four 自己動手 ticks are off (the default)")
        page = self.routines_page()
        settings = page.get("settings") or {}
        self.check.expect(page.get("routines") == [], "there is no routine yet")
        self.check.expect(settings.get("keep_awake") is False, "keeping the Mac awake is off (the default)")
        day = money(self.ledger().get("daily_usd"))
        got = money(settings.get("daily_usd"))
        self.check.expect(day is not None and got is not None and abs(got - day / 2) <= 0.0051 and settings.get("daily_usd_set") is None,
                          "the routines' daily limit is half of the daily limit", f"US${got} of US${day}")
        self.check.expect(self.skills() == [], "there is no skill yet")
        self.memo["spent0"] = self.spent()

    def skill(self) -> None:
        refused, _ = self.c.call("/api/my-skills", "POST", {"name": SKILL_NAME, "text": f"（虛構）用這把鑰匙 {fake_key()} 登入"})
        self.check.expect(refused == 400, "a skill with a key in it is refused", f"HTTP {refused}")
        code, out = self.c.call("/api/my-skills", "POST", {"name": ORDER_NAME, "text": ORDER_TEXT})
        self.check.expect(code == 409 and (out or {}).get("code") == "confirm_warning", "an order to act without asking needs the second word",
                          f"HTTP {code}")
        code, out = self.c.call("/api/my-skills", "POST", {"name": ORDER_NAME, "text": ORDER_TEXT, "confirm_warning": True})
        self.check.expect(code in (200, 201) and isinstance((out or {}).get("skill"), dict), "with the second word it is saved", f"HTTP {code}")
        if code in (200, 201) and isinstance((out or {}).get("skill"), dict):
            self.c.ok(f"/api/my-skills/{out['skill']['id']}/delete", "POST", {})
        made = self.c.ok("/api/my-skills", "POST", {"name": SKILL_NAME, "text": SKILL_TEXT})
        sid = (made.get("skill") or {}).get("id")
        if not isinstance(sid, str):
            raise Stop("the skill was saved without an id")
        self.memo["skills"].append(sid)
        self.check.ok("the skill is saved")
        self.skill_chat = self.open_chat(self.writer)
        self.memo["ids"]["skill_chat"] = self.skill_chat
        got = self.ask(self.skill_chat, SKILL_TEXT)
        self.check.expect(got["ended"] == "result", "the writer, sent the skill's words, ended the turn with a result", f"reason {got['ended']}")
        log = self.read_log("skillbook", "log.jsonl")
        self.check.expect(not any(w in log for w in WORDS), "skillbook/log.jsonl holds no name and no word")

    def read_log(self, folder: str, name: str) -> str:
        try:
            return (self.state / folder / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def suggest(self) -> None:
        chat_id = self.memo["ids"].get("skill_chat")
        if not chat_id:
            raise Stop("the skill stage has not made its chat")
        count = len(self.skills())
        preview = self.c.ok("/api/my-skills/suggest/preview", "POST", {"chat_id": chat_id})
        cap = money(preview.get("cap_usd"))
        self.check.expect(preview.get("ok") is True and preview.get("sends_to") == "Anthropic" and cap is not None and cap <= SUGGEST_CAP_USD,
                          "the preview says Anthropic and at most US$0.10", f"US${cap}; {preview.get('messages')} messages")
        if preview.get("ok") is not True:
            raise Stop("the preview is blocked")
        started = self.c.ok("/api/my-skills/suggest", "POST", {"preview_id": preview["preview_id"]})
        suggest_id = started.get("id")
        view = self.wait("the suggestion", lambda: (lambda v: v if v.get("status") in ("ready", "failed", "blocked", "cancelled", "skipped") else None)(
            self.c.ok(f"/api/my-skills/suggest/{suggest_id}")))
        self.check.expect(view.get("status") == "ready", "the suggestion ran to ready", f"status {view.get('status')}")
        items = view.get("items") or []
        self.check.expect(len(self.skills()) == count, "the skills did not change by themselves (the suggestion does not save)")
        spent = money(view.get("spent_usd"))
        self.check.expect(spent is not None and spent <= SUGGEST_CAP_USD, "it cost no more than US$0.10", f"US${spent}")
        if not items:
            self.check.warn("the model proposed no skill (not a condition)")
            return
        item = items[0]
        if item.get("refuse"):
            self.check.warn("the proposal is refused by the rules of saving (the model's, not a condition)", str(item.get("refuse")))
            return
        body = {"name": item["name"], "text": item["text"], "source": {"how": "suggested", "suggestion_id": suggest_id}}
        if item.get("warn"):
            body["confirm_warning"] = True
        saved = self.c.ok("/api/my-skills", "POST", body)
        if isinstance(saved.get("skill"), dict):
            self.memo["skills"].append(saved["skill"]["id"])
        self.c.ok(f"/api/my-skills/suggest/{suggest_id}/saved", "POST", {})
        self.check.expect(len(self.skills()) == count + 1, "pressing 存 saves it once, with how: suggested")

    def remind(self) -> None:
        self.autonomy(False)
        rid, slot, due = self.make_routine("A", ROUTINE_TEXT, LEAD_MIN)
        chats0, spent0 = len(self.chats()), self.spent()
        self.sleep_until(due + 30)
        rows = self.waiting("routine_due", rid)
        self.check.expect(len(rows) == 1, "at its time there is a reminder on the line over every page", f"{len(rows)} row")
        self.check.expect(len(self.chats()) == chats0 and self.spent() == spent0, "and no chat was opened and no money spent")
        if not rows:
            raise Stop("no reminder")
        self.c.ok(f"/api/routines/waiting/{rows[0]['run_id']}", "POST", {"action": "start"})
        run = self.finished(rid, slot)
        self.check.expect(run.get("state") == "done" and run.get("by") == "you", "「現在開始」 opened a chat and its turn ended with a result", f"{run.get('state')}, by {run.get('by')}")
        titles = [c.get("routine_title") for c in self.chats() if c.get("id") == run.get("chat_id")]
        self.check.expect(len(titles) == 1 and isinstance(titles[0], str) and titles[0].startswith("例行工作："), "the chat list calls it 「例行工作：…」")
        self.check.expect(not self.actions_of(rid), "the action list does not say item 3 (the person pressed)")
        self.disable(rid)

    def auto(self) -> None:
        self.autonomy(True)
        rid, slot, due = self.make_routine("B", ROUTINE_TEXT, LEAD_MIN)
        self.sleep_until(due + 5)
        run = self.run_until(rid, lambda r: r.get("slot") == slot and r.get("by") == "auto3", "the routine to start by itself", cap=75)
        self.check.expect(run.get("by") == "auto3" and run.get("why") == "on_time", "it started by itself within a minute of its time")
        run = self.finished(rid, slot)
        self.check.expect(run.get("state") == "done", "its turn ended with a result", f"state {run.get('state')}")
        self.check.expect(any(a.get("by_text") == "自己動手第 3 項" for a in self.actions_of(rid)), "the action list says 自己動手第 3 項")
        self.pause(3 * 60)
        mine = [r for r in self.runs_of(rid) if r.get("slot") == slot]
        self.check.expect(len(mine) == 1, "three minutes later the time still has one run", f"{len(mine)} runs")
        self.disable(rid)

    def awake(self) -> None:
        self.c.ok("/api/routines/settings", "POST", {"keep_awake": True})
        before = self.console_children()
        if before:
            self.check.warn("a caffeinate of the console was already there before the work began", f"{len(before)}")
        rid, slot, due = self.make_routine("C", BASH_TEXT, LEAD_MIN)
        self.sleep_until(due + 5)
        run = self.run_until(rid, lambda r: r.get("slot") == slot and bool(r.get("chat_id")), "the routine to start by itself", cap=90)
        chat_id = run["chat_id"]
        held: dict = {"card": False, "pids": []}

        def card_waits():
            if self.live_cards(chat_id):
                held["card"] = True
                held["pids"] = self.console_children()
                return True
            return any(r.get("kind") == "turn_ended" for r in self.records(chat_id))
        self.wait("a card or the end of the turn", card_waits)
        if held["card"]:
            self.check.expect(len(held["pids"]) >= 1, "while the card waits there is a caffeinate and its parent is the console", f"{len(held['pids'])} found")
        else:
            self.check.warn("the model asked for no command, so there was no moment to look (not a condition)")
        got = self.await_turn(chat_id, 1, decide=lambda card: "deny")
        self.check.ok("the script refused the card and the turn ended", f"reason {got['ended']}")
        end = self.clock() + 45
        while self.console_children() and self.clock() < end:
            self.sleep(3.0)
        self.check.expect(not self.console_children(), "within 45 seconds of the end of the turn there is no caffeinate of the console")
        self.c.ok("/api/routines/settings", "POST", {"keep_awake": False})
        self.disable(rid)

    def prepare(self, stage: str, letters: str, item3: bool, minutes_closed: int) -> None:
        self.autonomy(item3)
        made = {}
        for letter in letters:
            rid, slot, due = self.make_routine(letter, ROUTINE_TEXT, LEAD_CLOSED_MIN)
            made[letter] = {"id": rid, "slot": slot, "due": due}
        self.memo["ids"][stage] = {k: {"id": v["id"], "slot": v["slot"]} for k, v in made.items()}
        latest = max(v["due"] for v in made.values())
        now = self.clock()
        back = max(now + minutes_closed * 60, latest + 60)
        self.memo["ids"][stage + "-back"] = back
        self.save_memo()
        self.check.ok(f"{stage}: routine {', '.join(made)} made, due at {', '.join(minutes_text(v['due'], self.tz) for v in made.values())}, item 3 {'on' if item3 else 'off'}")
        self.check.ok(f"STOP the console now: check with ps -E that its VBEAR_HOME is the state folder, then kill -TERM its pid. Start it again on the same state and port not before {minutes_text(back, self.tz)}")
        self.stopped = True

    def wake1_prepare(self) -> None:
        self.prepare("wake1", "DE", False, CLOSED_WAIT_MIN)

    def wake2_prepare(self) -> None:
        self.prepare("wake2", "F", True, CLOSED_WAIT_MIN)

    def console_back(self) -> None:
        self.wait("the console to answer", lambda: self.c.call("/api/waiting")[0] == 200 or None, cap=90)

    def wake1_check(self) -> None:
        ids = self.memo["ids"].get("wake1") or {}
        if "D" not in ids or "E" not in ids:
            raise Stop("wake1-prepare has not run")
        if self.clock() < self.memo["ids"].get("wake1-back", 0):
            self.check.fail("the console was started before the time the script said", minutes_text(self.memo["ids"]["wake1-back"], self.tz))
        self.console_back()
        d, e = ids["D"], ids["E"]
        chats0 = len(self.chats())

        def listed():
            rows = {r.get("routine_id"): r for r in self.waiting("routine_missed")}
            return rows if d["id"] in rows and e["id"] in rows else None
        try:
            rows = self.wait("the missed times to be listed", listed, cap=120)
        except Stop:
            rows = {r.get("routine_id"): r for r in self.waiting("routine_missed")}
        self.check.expect(all((rows.get(x["id"]) or {}).get("count") == 1 for x in (d, e)), "D and E are each listed as missed once",
                          f"counts {[(rows.get(x['id']) or {}).get('count') for x in (d, e)]}")
        self.check.expect(len(self.chats()) == chats0 and not any(r.get("by") == "auto3" for x in (d, e) for r in self.runs_of(x["id"])),
                          "and nothing began by itself (item 3 is off)")
        got = self.c.ok(f"/api/routines/missed/{d['id']}", "POST", {"action": "run"})
        self.check.expect((got.get("run") or {}).get("by") == "you" and (got.get("run") or {}).get("why") == "catch_up", "補做 on D is a run by you")
        run = self.finished(d["id"], (got.get("run") or {}).get("slot") or d["slot"])
        self.check.expect(run.get("state") == "done", "and its turn ended with a result", f"state {run.get('state')}")
        self.check.expect(len([r for r in self.runs_of(d["id"]) if r.get("state") in ("starting", "running", "done")]) == 1, "D has one run in all")
        chats1 = len(self.chats())
        self.c.ok(f"/api/routines/missed/{e['id']}", "POST", {"action": "dismiss"})
        self.pause(5)
        self.check.expect(len(self.chats()) == chats1 and not self.waiting("routine_missed", e["id"]), "不用了 on E opened no chat and the line is gone")
        self.disable(d["id"])
        self.disable(e["id"])

    def wake2_check(self) -> None:
        ids = self.memo["ids"].get("wake2") or {}
        if "F" not in ids:
            raise Stop("wake2-prepare has not run")
        if self.clock() < self.memo["ids"].get("wake2-back", 0):
            self.check.fail("the console was started before the time the script said", minutes_text(self.memo["ids"]["wake2-back"], self.tz))
        self.console_back()
        f = ids["F"]
        run = self.run_until(f["id"], lambda r: r.get("by") == "auto3", "F to be caught up", cap=90)
        self.check.expect(run.get("why") == "catch_up", "F was caught up by itself within 90 seconds, why: catch_up", f"why {run.get('why')}")
        self.check.expect(any(a.get("by_text") == "自己動手第 3 項" for a in self.actions_of(f["id"])), "the action list says 自己動手第 3 項")
        done = self.finished(f["id"], run.get("slot"))
        self.check.expect(done.get("state") == "done", "its turn ended with a result", f"state {done.get('state')}")
        self.pause(2 * 60)
        mine = [r for r in self.runs_of(f["id"]) if r.get("slot") == run.get("slot")]
        self.check.expect(len(mine) == 1, "two minutes later the time still has one run", f"{len(mine)} runs")
        self.disable(f["id"])
        self.autonomy(False)

    def countdown(self) -> None:
        self.autonomy(False, True)
        limits_before = {k: v for k, v in self.config_file().items() if k in LIMIT_KEYS}
        ledger = self.ledger()
        spent, daily = money(ledger.get("spent_usd")), money(ledger.get("daily_usd"))
        if ledger.get("lamp") not in ("green", "yellow") or spent is None or daily is None or spent < 0.01:
            self.check.warn("the lamp is not open or nothing was spent yet, so the countdown cannot be tried now (not a condition)")
            self.autonomy(False)
            return
        made = self.c.ok("/api/groups", "POST", {"profile_ids": [self.writer, self.accountant]})
        gid = (made.get("group") or {}).get("id")
        if not gid:
            raise Stop("the group has no id")
        try:
            self.c.ok(f"/api/groups/{gid}/messages", "POST", {"text": GROUP_TEXT, "to": "all"})
            asked = self.wait("the first employee to be asked", lambda: self.group_view(gid, lambda v: v.get("current") is not None), cap=60, every=0.5)
            if asked is None:
                raise Stop("the first employee was not asked")
            # The first turn is on. The day's limit is brought down to what is spent: the next employee is not asked and the round stops.
            now_spent = self.spent()
            low = max(0.01, math.floor((now_spent or spent) * 100 + 1e-9) / 100)
            code, _ = self.c.call("/api/setup/daily-limit", "POST", {"daily_usd": low})
            if code != 200:
                raise Stop(f"the daily limit could not be brought down ({code})")
            view = self.wait("the round to stop", lambda: self.group_view(gid, lambda v: (v.get("round") or {}).get("state") == "paused"), cap=WAIT_CAP_S, every=1.0)
            pause = (view.get("round") or {}).get("pause") or {}
            self.check.expect(pause.get("reason") == "daily_limit", "the round stopped because of the daily limit", f"reason {pause.get('reason')}")
            midnight = tomorrow_midnight(self.clock(), self.tz)
            self.check.expect(isinstance(pause.get("until"), (int, float)) and abs(pause["until"] - midnight) <= 1, "and it waits until the next local midnight")
            count = pause.get("countdown") or {}
            self.check.expect(count.get("state") == "counting" and str(count.get("text", "")).startswith("還有"), "the group page has the countdown", f"state {count.get('state')}")
            rows = [r for r in self.c.ok("/api/waiting").get("waiting", []) if isinstance(r, dict) and r.get("kind") == "group_resume"]
            self.check.expect(len(rows) == 1, "the line over every page has the group's wait, not a press", f"{len(rows)} row")
        finally:
            code, _ = self.c.call("/api/setup/daily-limit", "POST", {"daily_usd": daily})
            current = self.config_file()
            put = {k: v for k, v in limits_before.items() if current.get(k) != v}
            if put:
                self.c.call("/api/config", "POST", put)
            back = {k: v for k, v in self.config_file().items() if k in LIMIT_KEYS}
            self.check.expect(code == 200 and back == limits_before, "the daily limit and the limits that went down with it are put back")
        self.pause(60)
        view = self.c.ok(f"/api/groups/{gid}")
        self.check.expect((view.get("round") or {}).get("state") == "paused", "a minute later the group is still stopped (a group never goes on by itself)")
        self.c.ok(f"/api/groups/{gid}/drop", "POST", {})
        self.c.ok(f"/api/groups/{gid}", "DELETE")
        self.autonomy(False)

    def group_view(self, gid: str, wanted):
        """The group's page when ``wanted(view)``, else None; a card that waits in the employee's chat is refused on the way."""
        view = self.c.ok(f"/api/groups/{gid}")
        cur = view.get("current")
        if isinstance(cur, dict) and cur.get("chat_id"):
            for card in self.live_cards(cur["chat_id"]):
                self.c.call(f"/api/chats/{cur['chat_id']}/answer", "POST", {"card_id": card.get("card_id"), "token": card.get("token"), "decision": "deny"})
        return view if wanted(view) else None

    def final(self) -> None:
        bad = config_problems(self.memo.get("config_sha", {}), self.config_file())
        self.check.expect(not bad, "config.json is as setup left it (key by key, except autonomy)", ",".join(bad))
        ticks = self.c.ok("/api/settings/autonomy").get("autonomy") or {}
        self.check.expect(all(ticks.get(k) is False for k in AUTONOMY_KEYS), "the four 自己動手 ticks are off again")
        listed = {p.get("id"): p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict)}
        for pid in self.cards:
            p = listed.get(pid)
            self.check.expect(p is not None and not card_problems(p) and sha(p) == self.memo.get("profile_sha", {}).get(pid),
                              "a card is in safe mode, has no skill and was not changed", ",".join(card_problems(p or {})))
        removed = 0
        for rid in self.memo.get("routines", []):
            self.c.call(f"/api/routines/{rid}/delete", "POST", {})
            removed += 1
        left = [r for r in self.routines_page().get("routines", []) if str(r.get("name", "")).startswith(PREFIX)]
        self.check.expect(not left, "the routines this script made are deleted", f"{removed} deleted")
        gone = 0
        for sid in self.memo.get("skills", []):
            code, _ = self.c.call(f"/api/my-skills/{sid}/delete", "POST", {})
            gone += 1 if code == 200 else 0
        self.check.expect(not [s for s in self.skills() if str(s.get("name", "")).startswith(PREFIX) or s.get("id") in self.memo.get("skills", [])],
                          "the skills this script saved are deleted", f"{gone} deleted")
        self.c.ok("/api/routines/settings", "POST", {"keep_awake": False})
        end = self.clock() + 45
        while self.console_children() and self.clock() < end:
            self.sleep(3.0)
        self.check.expect(not self.console_children(), "no caffeinate is a child of the console")
        for folder, name in (("skillbook", "log.jsonl"), ("routines", "log.jsonl"), ("routines", "runs.jsonl")):
            self.check.expect(not any(w in self.read_log(folder, name) for w in WORDS), f"{folder}/{name} holds no name and no word of this script")
        spent = self.spent()
        self.check.expect(spent is not None and spent <= SPEND_CEILING_USD, "what the day's ledger counts is within the allowance",
                          f"US${spent} (VBear's own counting; the daily limit is the hard cap)")
        self.check.ok("money by stage", ", ".join(f"{k} US${v}" for k, v in self.memo.get("spent", {}).items()))


def main(argv=None, out=print, console_factory=Console, clock=time.time, sleep=time.sleep, runner=subprocess.run, tz=None, home: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="v0.18.0 real check of skills and routines (see the file's docstring)")
    ap.add_argument("--state", required=True, help="the temporary state folder of the console (VBEAR_HOME)")
    ap.add_argument("--port", type=int, default=7799, help="the console's port (never 7788 or 7789)")
    ap.add_argument("--cards", required=True, help="two role card ids, comma separated: the writer, the accountant")
    ap.add_argument("--from", dest="first", choices=STAGES, default=STAGES[0], help="the first stage to run")
    ap.add_argument("--until", choices=STAGES, default=STAGES[-1], help="the last stage to run")
    args = ap.parse_args(argv)
    cards = [c for c in args.cards.split(",") if c]
    if len(cards) != 2 or len(set(cards)) != 2:
        out("refused: --cards takes exactly two different ids: the writer, the accountant")
        return 2
    if STAGES.index(args.first) > STAGES.index(args.until):
        out("refused: --from comes after --until")
        return 2
    why = refusal(args.state, args.port, home)
    if why:
        out(f"refused: {why}")
        return 2
    why = time_refusal(clock(), tz)
    if why:
        out(f"refused: {why}")
        return 2
    check = Check(out)
    run = None
    try:
        state = Path(args.state).expanduser().resolve()
        console = console_factory(args.port, read_token(state, args.port))
        run = Run(console, state, cards, args.first, args.until, check, clock=clock, sleep=sleep, runner=runner, tz=tz)
        run.start()
        for stage in STAGES:
            if stage == "final" or not run.in_range(stage):
                continue
            before = run.spent() or 0.0
            getattr(run, stage.replace("-", "_"))()
            after = run.spent() or before
            run.memo["spent"][stage] = round(run.memo["spent"].get(stage, 0.0) + max(0.0, after - before), 4)
            run.save_memo()
            if run.stopped:
                break
        if not run.stopped and args.until == "final":
            run.final()
    except Stop as exc:
        check.fail("stopped", str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check.fail("unexpected", f"{type(exc).__name__}: {str(exc)[:120]}")
    finally:
        if run is not None:
            try:
                run.save_memo()
            except OSError:
                pass
    out(f"qa_p44: {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
