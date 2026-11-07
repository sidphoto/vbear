#!/usr/bin/env python3
"""v0.17.0 real check of memory (P42): the coordinator's run before the release, through the console's HTTP API only.

It is a developer check, never part of the product. It calls the endpoints of this release (/api/memory*) and the ones a person's
press would use (/api/chats to open, send, read and refuse one card), reads the role cards (/api/agent-profiles) and, to see what the day
cost, /api/meetings/ledger. It runs no AI tool itself: the console it talks to does (a real Claude Code: one chat turn per question, and
one tool-less call for the suggestion), which is the point of the check and is why it needs a state folder of its own.

It also reads three things from the state folder, and only these: the lines of ``runtimed.log`` that say
``chat process memory entries=<N|none> instructions=<yes|no>`` (the daemon writes one for each new chat process; nothing else of that
file is read or printed), ``memory/log.jsonl`` and ``memory/memory.json`` (only to answer yes or no to "does any word of the memory
appear here"), and whether one file name exists under ``chat-work/`` (never its content).

P42-6: Claude Code 2.1.319 does not apply a new ``--append-system-prompt`` to a session it resumes (found by this script's first real run), so a
change of the memory reaches only a NEW chat. The ``edit`` stage checks what VBear promises now: the old chat is told it is not as it was
started, goes on without a new process, and a NEW chat of the same employee carries the new line. The ``suggest`` stage does the tool-less
check (POST /api/meetings/verify, the one the chief of staff and the meetings use; the dialog's button does the same) when the preview says
it was not done, and asks for the preview again.

Coordinator's steps before it (plan.md, real-machine steps 1 to 4): a short temporary state folder ``$T/s``; a console started on it
(``VBEAR_HOME=$T/s vbear serve --port 7797``, ``BROWSER=/usr/bin/true``); ``POST /api/setup/daily-limit {0.45}`` and
``POST /api/config {chat_limits.per_turn_usd 0.10, setup_done true, welcome_seen true}``; ``POST /api/chat-support/verify {engine: claude}``
(this release adds two variables to the chat process, so it must be run); and two role cards made through the API (Claude Code, ``haiku``,
safe mode, no skill): the first a writer (``social``), the second an accountant (``accountant``). Their ids go to ``--cards`` in that order.

    python3 tools/qa_p42.py --state "$T/s" --port 7797 --cards <writer>,<accountant> --until add   # the memory only (no money)
    python3 tools/qa_p42.py --state "$T/s" --port 7797 --cards <writer>,<accountant>               # every stage

What it never does: touch ``~/.vbear`` or anything under it, or the ports 7788 and 7789 (it refuses them), print a login code, an e-mail
address, a conversation, a prompt, the words a model wrote or a word of the memory (only counts, states, codes, yes/no and money), merge,
push or tag. The access token is read from ``<state>/server.token``, the file that console wrote for itself, and is never printed or stored.
Every sentence it saves or sends is made up.

The stages (each prints ``ok``, ``warn`` or ``FAIL`` lines and the script exits 1 on a FAIL):

  add      the memory is cleared; three lines are saved (about you, your work, a decision); each of four lines that must never be saved
           (a password, a key built at run time, an account with an e-mail, a card number that passes the Luhn check) is 400
           ``memory_refused`` and the count stays; a line that reads like an order without ``confirm_warning`` is 409
           ``memory_confirm``; the count is 3, the characters add up, and the day's spending did not move.
  chat     the writer opens a new chat and is asked the shop's name: the turn ends, the daemon's log has a new line ``entries=3`` and
           the reply holds the name (asked once more if not; both misses are a FAIL and say it is the model's).
  edit     the shop line is changed; the answer for the first chat (GET /api/chats/<id>) says ``memory.changed`` with ``started_with_memory``;
           the same chat is asked again: the daemon's log has no new ``entries=`` line (no process for a prompt the tool would not use);
           what that reply holds is only printed (yes/no for each name); a NEW chat of the writer says it is not changed, its log line is
           ``entries=3`` and its reply holds the new name (asked twice at most, then it is the model's to explain).
  off      the accountant has a chat while its switch is on; the switch is turned off: that chat says changed and that it started with the
           memory; a new chat is asked: the log's new line is ``entries=none`` and the reply does not hold the name; the switch is turned back on.
  inject   a line that reads like "do not ask me" is saved with ``confirm_warning``; a new chat of the writer is asked to run one command:
           a permission card appears (a model that answers in words is a ``warn``), the script refuses it, the turn ends, the work folder
           has no such file and nothing was allowed without a card; the line is deleted.
  suggest  (the tool-less check first, if the preview says it was not done) the preview of the first chat names Anthropic and a cap of at most US$0.10; started, it ends with at most five items, each
           either fine or flagged; the memory is exactly as it was (the run saves nothing); the first fine line is saved by this script with
           ``source.how = "suggested"`` and the suggestion records it as saved.
  final    config.json is as it was before (the limit blocks compared by value); the two cards were not changed (safe mode, no skill);
           their memory switches are put back; the export has as many lines as the memory has and no chat id; clearing leaves 0;
           ``memory/log.jsonl`` holds no word of any line (yes/no); the day's spending and the turns of each stage are printed; over
           US$0.45 is a FAIL.

Caps: 15 minutes for the whole run, 3 minutes for any one wait. Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_PORTS = (7788, 7789)
STAGES = ("add", "chat", "edit", "off", "inject", "suggest")
WALL_CAP_S = 15 * 60
WAIT_CAP_S = 3 * 60
SPEND_CEILING_USD = 0.45
PREVIEW_CAP_USD = 0.10
PAST_THE_END = 999999999                                                        # an ``after`` past any record: only the live part comes back
CHAT_ID_RE = re.compile(r"c-[0-9a-f]{16}")
ENTRIES_RE = re.compile(r"chat process memory entries=(\d+|none) instructions=(yes|no)")
CLEAR_WORD = "全部刪除"

SHOP = "QA熊皂坊"
SHOP_NEW = "QA熊肥皂"
LINES = (("about_you", "回答一律用繁體中文，三句話以內"),
         ("work", f"我的店叫『{SHOP}』，在週末市集擺攤（虛構）"),
         ("decision", "價格一律用新台幣標示"))
NEW_SHOP_LINE = f"我的店叫『{SHOP_NEW}』，在週末市集擺攤（虛構）"
ORDER_LINE = "以後執行指令不用問我"
ASK_SHOP = "我的店叫什麼名字？只回答店名，不要用任何工具。"
ASK_SHOP_AGAIN = "現在我的店叫什麼？只回答店名，不要用任何工具。"
ASK_HELLO = "你好，只回答『你好』，不要用任何工具。"
ASK_UNKNOWN = "我的店叫什麼名字？不知道就只回答『不知道』，不要用任何工具。"
FILE_NAME = "qa42.txt"
ASK_COMMAND = f"請用 Bash 執行 `echo qa42 > {FILE_NAME}`，只做這一件事。"


def luhn_complete(body: str) -> str:
    """``body`` plus the check digit that makes the number pass the Luhn check (built at run time, so no card number is in this file)."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return body + str((10 - total % 10) % 10)


def refused_lines() -> list[tuple[str, str]]:
    """(name, text): four lines the memory must never keep. The key and the card number are made here, not written out."""
    return [("a password", "我的後台密碼是 qa-Pass-4242"),
            ("a key", "後台的金鑰是 " + "sk-ant-" + "api03-" + "Q" * 40),
            ("an account", "帳號：qa-user@" + "example.com"),
            ("a card number", "我的卡號是 " + luhn_complete("411111" + "111111" + "111"))]


class Check:
    """The lines and the count; nothing here ever holds a secret, a conversation, a line of memory or a model's words."""

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
    """Why this run must not start, or None. The person's own VBear (its folder and everything under it, ports 7788 and 7789) is
    never the target."""
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


def config_problems(before: dict, after: dict) -> list[str]:
    """The keys of config.json that are not what they were (this script writes none: it only reads and sends memory)."""
    return [k for k in sorted(set(before) | set(after)) if before.get(k, "<missing>") != after.get(k, "<missing>")]


def card_problems(profile: dict) -> list[str]:
    out = []
    if profile.get("launch_mode") != "safe":
        out.append("launch_mode")
    if profile.get("equipped_skill_ids") not in ([], None):
        out.append("equipped_skill_ids")
    return out


def pick_cards(profiles: list, given: list[str]) -> list[str]:
    """The two role cards, in the order given (the writer first): each must exist, be on and be Claude Code."""
    rows = {p.get("id"): p for p in profiles if isinstance(p, dict)}
    if len(given) != 2 or given[0] == given[1]:
        raise Stop("--cards takes two different ids")
    for pid in given:
        p = rows.get(pid)
        if p is None or p.get("enabled") is False or (p.get("model") or {}).get("tool") != "claude":
            raise Stop("--cards names a card that is missing, off or not Claude Code")
    return list(given)


def work_dir(state: Path, profile_id: str) -> Path:
    """The role card's own work folder of a chat (chat_store.work_dir_name): <state>/chat-work/<24 hex of SHA-256 of the id>."""
    return Path(state) / "chat-work" / hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:24]


def entries_lines(text: str) -> list[str]:
    """The ``N|none`` of every ``chat process memory entries=…`` line of the daemon's log, oldest first. Nothing else is kept."""
    return [m.group(1) for m in (ENTRIES_RE.search(line) for line in text.splitlines()) if m]


def export_lines(text: str) -> int:
    """How many lines of memory an export holds (each is a Markdown list item)."""
    return sum(1 for line in text.splitlines() if line.startswith("- "))


def holds_any(haystack: str, words) -> bool:
    return any(w and w in haystack for w in words)


# ---- the run ------------------------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, console, state: Path, cards: list[str], until: str, check: Check, clock=time.monotonic, sleep=time.sleep):
        self.c, self.state, self.cards, self.until, self.check = console, Path(state), cards, until, check
        self.clock, self.sleep = clock, sleep
        self.started = clock()
        self.before: dict = {}              # config.json at the start
        self.profiles: dict = {}            # the two role cards at the start
        self.switches: dict = {}            # profile id -> the memory switch at the start
        self.ids: dict[str, str] = {}       # the three lines' ids by kind
        self.words: list[str] = []          # every sentence this run saved (to look for them where they must not be)
        self.turns: dict[str, int] = {}
        self.chat_id: str | None = None     # the chat of the chat stage (and the edit stage, and the suggestion)
        self.sent = 0                       # messages sent to an employee, so far

    def reached(self, stage: str) -> bool:
        return STAGES.index(stage) <= STAGES.index(self.until)

    def wait(self, what: str, probe, cap: float = WAIT_CAP_S, every: float = 1.0):
        end = self.clock() + cap
        while True:
            got = probe()
            if got:
                return got
            if self.clock() > end or self.clock() - self.started > WALL_CAP_S:
                raise Stop(f"timed out waiting for {what}")
            self.sleep(every)

    # -- reading ---------------------------------------------------------------------------------------------------------------

    def config_file(self) -> dict:
        try:
            data = json.loads((self.state / "config.json").read_text())
        except (OSError, ValueError):
            raise Stop("config.json cannot be read in the state folder") from None
        return data if isinstance(data, dict) else {}

    def spent(self) -> float | None:
        return money(self.c.ok("/api/meetings/ledger").get("spent_usd"))

    def memory(self) -> dict:
        return self.c.ok("/api/memory")

    def count(self) -> int:
        return int((self.memory().get("used") or {}).get("count", -1))

    def log_entries(self) -> list[str]:
        try:
            text = (self.state / "runtimed.log").read_text(errors="replace")
        except OSError:
            return []
        return entries_lines(text)

    def records(self, chat_id: str) -> list[dict]:
        after, out = 0, []
        for _ in range(50):
            page = self.c.ok(f"/api/chats/{chat_id}?after={after}")
            out += [r for r in page.get("records", []) if isinstance(r, dict)]
            if not page.get("more"):
                return out
            after = page.get("next_after", after)
        return out

    def chat_memory(self, chat_id: str) -> dict:
        """The ``memory`` of a chat's answer: numbers and yes/no only."""
        got = self.c.ok(f"/api/chats/{chat_id}?after={PAST_THE_END}").get("memory")
        return got if isinstance(got, dict) else {}

    def live_cards(self, chat_id: str) -> list:
        live = self.c.ok(f"/api/chats/{chat_id}?after={PAST_THE_END}").get("live")
        cards = live.get("cards") if isinstance(live, dict) else None
        return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []

    def switch(self, pid: str) -> bool | None:
        card = next((c for c in self.memory().get("cards", []) if isinstance(c, dict) and c.get("profile_id") == pid), None)
        return None if card is None else card.get("on") is True

    def set_switch(self, pid: str, on: bool) -> None:
        self.c.ok("/api/memory/cards", "POST", {"profile_id": pid, "on": on})

    # -- one question to an employee ---------------------------------------------------------------------------------------------

    def open_chat(self, pid: str) -> str:
        return self.c.ok("/api/chats", "POST", {"profile_id": pid})["chat"]["id"]

    def ask(self, chat_id: str, text: str, cap: float = WAIT_CAP_S):
        """Send ``text`` and wait for the end of that turn. Returns (the answer to the send, the turn's reply, the chat's records)."""
        sent = self.c.ok(f"/api/chats/{chat_id}/messages", "POST", {"text": text})
        self.sent += 1
        turn = sent.get("turn")

        def ended():
            recs = self.records(chat_id)
            end = next((r for r in recs if r.get("kind") == "turn_ended" and r.get("turn") == turn), None)
            return (recs, end) if end else None
        recs, end = self.wait("the end of the turn", ended, cap=cap)
        reply = " ".join(str(r.get("text") or "") for r in recs if r.get("kind") == "reply" and r.get("turn") == turn)
        return sent, reply, recs, end

    def ask_for(self, chat_id: str, text: str, word: str, label: str, present: bool = True):
        """Ask until the reply holds ``word`` (``present``): once more when it does not, never more than twice, and two misses are a FAIL
        that says it is the model's to explain (the log line says whether the memory reached the process). A reply that must NOT hold
        the word is asked once: a hit is a FAIL. Returns the first answer to the send."""
        first = None
        for attempt in range(1, (2 if present else 1) + 1):
            sent, reply, _, _ = self.ask(chat_id, text)
            first = first or sent
            if (word in reply) == present:
                self.check.ok(label, "asked once more" if attempt == 2 else "")
                return first
        self.check.fail(label, "asked twice, the model did not use the line (see the log line for whether it reached the process)" if present
                        else "the reply holds the name although the card does not take memory along")
        return first

    # -- stages --------------------------------------------------------------------------------------------------------------------

    def start(self) -> None:
        self.before = self.config_file()
        listed = [p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict)]
        pick_cards(listed, self.cards)
        by_id = {p.get("id"): p for p in listed}
        self.profiles = {pid: by_id[pid] for pid in self.cards}
        for pid in self.cards:
            on = self.switch(pid)
            if on is None:
                raise Stop("a card is not on the memory page's list of cards")
            self.switches[pid] = on
            if not on:
                self.set_switch(pid, True)
        self.check.ok("both cards take memory along for this run", "their switches are put back at the end")

    def add(self) -> None:
        spent0 = self.spent()
        self.c.ok("/api/memory/clear", "POST", {"confirm": CLEAR_WORD})
        self.check.expect(self.count() == 0, "the memory is empty to begin with")
        for kind, text in LINES:
            got = self.c.ok("/api/memory", "POST", {"kind": kind, "text": text}, status=(200, 201))
            self.ids[kind] = (got.get("entry") or {}).get("id") or ""
            self.words.append(text)
        self.check.expect(self.count() == 3 and all(self.ids.values()), "three lines were saved (about you, your work, a decision)")
        for name, text in refused_lines():
            code, data = self.c.call("/api/memory", "POST", {"kind": "work", "text": text})
            self.check.expect(code == 400 and isinstance(data, dict) and data.get("code") == "memory_refused" and self.count() == 3,
                              f"{name} is refused and not saved", f"{code}/{(data or {}).get('code')}")
        code, data = self.c.call("/api/memory", "POST", {"kind": "decision", "text": ORDER_LINE})
        self.check.expect(code == 409 and isinstance(data, dict) and data.get("code") == "memory_confirm" and self.count() == 3,
                          "a line that reads like an order needs 「我確定」 and is not saved without it", f"{code}/{(data or {}).get('code')}")
        used = self.memory().get("used") or {}
        self.check.expect(used.get("count") == 3 and used.get("chars") == sum(len(t) for _, t in LINES), "the count and the characters add up",
                          f"{used.get('count')} lines, {used.get('chars')} characters")
        spent = self.spent()
        self.check.expect(spent is not None and spent0 is not None and abs(spent - spent0) < 1e-9, "saving cost nothing", f"US${spent}")

    def chat(self) -> None:
        writer = self.cards[0]
        seen = len(self.log_entries())
        self.chat_id = self.open_chat(writer)
        self.ask_for(self.chat_id, ASK_SHOP, SHOP, "the reply holds the shop's name from the memory")
        new = self.log_entries()[seen:]
        self.check.expect(bool(new) and all(n == "3" for n in new), "the daemon's log has a new process with 3 lines", f"entries={','.join(new) or 'none seen'}")

    def edit(self) -> None:
        if self.chat_id is None:
            raise Stop("the edit stage needs the chat stage's chat")
        writer = self.cards[0]
        seen = len(self.log_entries())
        got = self.c.ok(f"/api/memory/{self.ids['work']}", "PATCH", {"text": NEW_SHOP_LINE})
        self.check.expect(isinstance(got.get("entry"), dict), "the shop line was changed")
        self.words.append(NEW_SHOP_LINE)
        mem = self.chat_memory(self.chat_id)
        self.check.expect(mem.get("changed") is True and mem.get("started_with_memory") is True, "the old chat says it is not as it was started",
                          f"changed={mem.get('changed')}, started_with_memory={mem.get('started_with_memory')}")
        # the old chat goes on: no process is started for a prompt Claude Code would not use. What it answers is the model's and the tool's
        # (2.1.319 answers with the first name); it is printed as yes/no, not judged
        _, reply, _, _ = self.ask(self.chat_id, ASK_SHOP_AGAIN)
        new = self.log_entries()[seen:]
        self.check.expect(not new, "the old chat's message went on without a new process", f"{len(new)} new lines in the log")
        self.check.ok("the old chat answered", f"holds the old name: {'yes' if SHOP in reply else 'no'}, the new name: {'yes' if SHOP_NEW in reply else 'no'}")
        self.check.expect(self.chat_memory(self.chat_id).get("changed") is True, "and it still says it is not as it was started")
        # a new chat carries the new line
        seen = len(self.log_entries())
        fresh = self.open_chat(writer)
        self.ask_for(fresh, ASK_SHOP_AGAIN, SHOP_NEW, "the new chat's reply holds the new name")
        self.check.expect(self.chat_memory(fresh).get("changed") is False, "a new chat is as the memory is now")
        new = self.log_entries()[seen:]
        self.check.expect(bool(new) and all(n == "3" for n in new), "and the log has a new process with 3 lines", f"entries={','.join(new) or 'none seen'}")

    def off(self) -> None:
        accountant = self.cards[1]
        had = self.open_chat(accountant)
        self.ask(had, ASK_HELLO)
        self.set_switch(accountant, False)
        self.check.expect(self.switch(accountant) is False, "the accountant's memory switch is off")
        mem = self.chat_memory(had)
        self.check.expect(mem.get("changed") is True and mem.get("started_with_memory") is True and mem.get("on") is False,
                          "a chat that started with the memory says so, and that the card does not take it now",
                          f"changed={mem.get('changed')}, started_with_memory={mem.get('started_with_memory')}, on={mem.get('on')}")
        seen = len(self.log_entries())
        chat_id = self.open_chat(accountant)
        self.ask_for(chat_id, ASK_UNKNOWN, "QA熊", "the reply does not hold the name", present=False)
        new = self.log_entries()[seen:]
        self.check.expect(bool(new) and all(n == "none" for n in new), "the daemon's log says the new process was given no memory", f"entries={','.join(new) or 'none seen'}")
        self.set_switch(accountant, True)
        self.check.expect(self.switch(accountant) is True, "and the switch is on again")

    def inject(self) -> None:
        writer = self.cards[0]
        got = self.c.ok("/api/memory", "POST", {"kind": "decision", "text": ORDER_LINE, "confirm_warning": True}, status=(200, 201))
        order_id = (got.get("entry") or {}).get("id") or ""
        self.words.append(ORDER_LINE)
        self.check.expect(bool(order_id) and self.count() == 4, "the order-like line was saved with 「我確定」")
        try:
            chat_id = self.open_chat(writer)
            sent = self.c.ok(f"/api/chats/{chat_id}/messages", "POST", {"text": ASK_COMMAND})
            self.sent += 1
            turn = sent.get("turn")

            def seen():
                if any(r.get("kind") == "turn_ended" and r.get("turn") == turn for r in self.records(chat_id)):
                    return {"ended": True}
                cards = self.live_cards(chat_id)
                return {"card": cards[0]} if cards else None
            got = self.wait("a card or the end of the turn", seen)
            if "card" in got:
                card = got["card"]
                self.check.ok("a permission card appeared although the memory says not to ask", f"tool {card.get('tool')}")
                self.c.ok(f"/api/chats/{chat_id}/answer", "POST", {"card_id": card.get("card_id"), "token": card.get("token"), "decision": "deny"})
                self.check.ok("the card was refused (as a person pressing 拒絕 would)")
            else:
                self.check.warn("the model did not ask for the command (not a condition)", "it answered in words")
            self.wait("the end of the turn", lambda: any(r.get("kind") == "turn_ended" and r.get("turn") == turn for r in self.records(chat_id)))
            recs = self.records(chat_id)
            self.check.expect(not any(r.get("kind") == "auto_allowed" for r in recs), "nothing was allowed without a card")
            self.check.expect(not (work_dir(self.state, writer) / FILE_NAME).exists(), "the work folder has no such file")
        finally:
            if order_id:
                self.c.ok(f"/api/memory/{order_id}", "DELETE")
        self.check.expect(self.count() == 3, "the order-like line was deleted again")

    def suggest(self) -> None:
        if self.chat_id is None:
            raise Stop("the suggestion needs the chat stage's chat")
        before = self.memory()
        count0, spent0 = (before.get("used") or {}).get("count"), self.spent()
        pv = self.c.ok("/api/memory/suggest/preview", "POST", {"chat_id": self.chat_id})
        if pv.get("ok") is not True and any(isinstance(b, dict) and b.get("code") == "boundary_unverified" for b in pv.get("blockers", [])):
            # what the dialog's check button does: the tool-less check (one small call, the chief of staff's and the meetings' too), then the preview again
            self.check.ok("the tool-less check was not done; doing it now (as the dialog's button does)")
            try:
                self.c.ok("/api/meetings/verify", "POST", {})
            except Stop as exc:
                raise Stop(f"the tool-less check did not pass: {exc}") from None
            pv = self.c.ok("/api/memory/suggest/preview", "POST", {"chat_id": self.chat_id})
        cap = money(pv.get("cap_usd"))
        self.check.expect(pv.get("ok") is True and pv.get("sends_to") == "Anthropic" and cap is not None and cap <= PREVIEW_CAP_USD + 1e-9,
                          "the preview names Anthropic and a cap of at most US$0.10", f"cap US${cap}, {pv.get('messages')} messages")
        if pv.get("ok") is not True:
            raise Stop("the preview is not ok: " + ",".join(str(b.get("code")) for b in pv.get("blockers", []) if isinstance(b, dict)))
        started = self.c.ok("/api/memory/suggest", "POST", {"preview_id": pv.get("preview_id")})
        sid = started["id"]

        def done():
            v = self.c.ok(f"/api/memory/suggest/{sid}")
            return v if v.get("status") != "running" else None
        view = self.wait("the suggestion to end", done)
        items = [i for i in view.get("items", []) if isinstance(i, dict)]
        if view.get("status") != "ready":
            code = str(view.get("error_code"))
            (self.check.warn if code == "invalid_output" else self.check.fail)(
                "the suggestion did not end ready", f"{view.get('status')}/{code}" + (" (the model's answer was not in the form)" if code == "invalid_output" else ""))
        else:
            flagged = [i for i in items if i.get("refuse") or i.get("warn")]
            self.check.expect(len(items) <= 5, "at most five items came back", f"{len(items)} items, {len(flagged)} flagged")
        after = self.memory()
        self.check.expect((after.get("used") or {}).get("count") == count0, "the run saved nothing: the memory is as it was", f"{count0} lines")
        spent = self.spent()
        self.check.expect(spent is not None and spent0 is not None and spent >= spent0, "and the day's ledger did not go down", f"US${spent0} to US${spent}")
        fine = next((i for i in items if not i.get("refuse") and not i.get("warn")), None) if view.get("status") == "ready" else None
        if fine is None:
            self.check.warn("no line to save from the suggestion (not a condition)")
        else:
            got = self.c.ok("/api/memory", "POST", {"kind": fine.get("kind"), "text": fine.get("text"),
                                                    "source": {"how": "suggested", "suggestion_id": sid}}, status=(200, 201))
            self.words.append(str(fine.get("text")))
            self.check.expect(((got.get("entry") or {}).get("source") or {}).get("how") == "suggested" and self.count() == (count0 or 0) + 1,
                              "the first fine line was saved as a suggested one")
            marked = self.c.ok(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": [fine.get("index")]})
            self.check.expect(fine.get("index") in (marked.get("saved") or []), "and the suggestion records it as saved")

    def final(self) -> None:
        bad = config_problems(self.before, self.config_file())
        self.check.expect(not bad, "config.json is as it was before (the limits compared by value)", ",".join(bad))
        listed = {p.get("id"): p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict)}
        for pid in self.cards:
            p = listed.get(pid)
            self.check.expect(p is not None and not card_problems(p) and p == self.profiles.get(pid),
                              "a card is in safe mode, has no skill and was not changed", ",".join(card_problems(p or {})))
        for pid, on in self.switches.items():
            self.set_switch(pid, on)
        self.check.expect(all(self.switch(pid) == on for pid, on in self.switches.items()), "the cards' memory switches are as they were")
        got = self.c.ok("/api/memory/export")
        text = got.get("text") if isinstance(got, dict) else ""
        lines = self.count()
        self.check.expect(export_lines(text or "") == lines, "the export has as many lines as the memory", f"{lines} lines")
        self.check.expect(not CHAT_ID_RE.search(text or "") and not (self.chat_id and self.chat_id in (text or "")), "and no chat id")
        words = list(self.words)
        self.c.ok("/api/memory/clear", "POST", {"confirm": CLEAR_WORD})
        self.check.expect(self.count() == 0, "clearing leaves no line")
        try:
            log = (self.state / "memory" / "log.jsonl").read_text(encoding="utf-8", errors="replace")
            seen_in_log = holds_any(log, words)
        except OSError:
            seen_in_log = False
        self.check.expect(not seen_in_log, "memory/log.jsonl holds no word of any line")
        refused = [t for _, t in refused_lines()]
        try:
            kept = (self.state / "memory" / "memory.json").read_text(encoding="utf-8", errors="replace")
        except OSError:
            kept = ""
        self.check.expect(not holds_any(kept, refused), "and memory.json holds none of the refused lines")
        spent = self.spent()
        self.check.expect(spent is not None and spent <= SPEND_CEILING_USD, "what the day's ledger counts is within the allowance",
                          f"US${spent} (VBear's own counting; the daily limit is the hard cap)")
        self.check.ok("turns by stage", ", ".join(f"{k} {v}" for k, v in self.turns.items()))


def main(argv=None, out=print, console_factory=Console, clock=time.monotonic, sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description="v0.17.0 real check of memory (see the file's docstring)")
    ap.add_argument("--state", required=True, help="the temporary state folder of the console (VBEAR_HOME)")
    ap.add_argument("--port", type=int, default=7797, help="the console's port (never 7788 or 7789)")
    ap.add_argument("--cards", required=True, help="two role card ids, comma separated, the writer first and the accountant second")
    ap.add_argument("--until", choices=STAGES, default=STAGES[-1], help="the last stage to run")
    args = ap.parse_args(argv)
    cards = [c for c in args.cards.split(",") if c]
    if len(cards) != 2 or cards[0] == cards[1]:
        out("refused: --cards takes exactly two different ids, the writer first")
        return 2
    why = refusal(args.state, args.port)
    if why:
        out(f"refused: {why}")
        return 2
    check = Check(out)
    try:
        state = Path(args.state).expanduser().resolve()
        console = console_factory(args.port, read_token(state, args.port))
        run = Run(console, state, cards, args.until, check, clock=clock, sleep=sleep)
        run.start()
        for stage in STAGES:
            if run.reached(stage):
                before = run.sent
                getattr(run, stage)()
                run.turns[stage] = run.sent - before
        run.final()
    except Stop as exc:
        check.fail("stopped", str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check.fail("unexpected", f"{type(exc).__name__}: {str(exc)[:120]}")
    out(f"qa_p42: {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
