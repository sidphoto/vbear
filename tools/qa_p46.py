#!/usr/bin/env python3
"""v0.20.0 real check of the AGY chat (P46): the coordinator's run before the release, through the console's HTTP API only.

It is a developer check, never part of the product. It calls the endpoints a person's presses would use: /api/chat-support (read),
/api/agent-profiles (make and delete its own role cards), /api/chats* (open, send, answer a card, stop, read, delete), /api/memory*,
/api/shared* (never ``reveal``), /api/groups*, /api/routines*, /api/templates*, /api/meetings/ledger, /api/config (only
``chat_limits.per_turn_usd``, put back at the end) and /api/settings/autonomy (read). It runs no program and no AI tool itself: the
console it talks to runs the real AGY (model ``gemini-3.8-flash-high``, on the person's Google plan) and, for two stages, a real Claude
Code (Haiku). That is the point of the check and why it needs a state folder of its own.

Besides the HTTP API it reads only these, in the state folder ``<state>``, and writes one file of its own:

  * ``<state>/config.json``: the bytes (a hash) at the start and at the end; in between only ``chat_limits.per_turn_usd`` may be
    changed and put back;
  * ``<state>/memory/memory.json`` and every file under ``<state>/shared-meta/``: a hash before and after the team template's apply;
  * ``<state>/shared/``: the names of the files (the AGY employee has no shared folder in this release, so none may appear);
  * ``<state>/chats/*/events.jsonl``: only the set of the ``kind`` words (they must all be kinds that v0.19.0 already had);
  * ``$T/qa46.json`` (``$T`` is the folder that holds ``<state>``): the one file it writes (ids it made and money; never a name,
    a word or a secret).

Coordinator's steps before it (plan.md, real-machine steps 1 to 5): a short state folder ``$T/s`` **under the home folder, not
under /tmp** (the check's decoys have to be where AGY's sandbox cannot write); a console started on it (``VBEAR_HOME=$T/s
BROWSER=/usr/bin/true vbear serve --port 7801``); the daily limit US$2.00 and ``chat_limits.per_turn_usd`` 0.25 (``setup_done``,
``welcome_seen``), AGY marked 「我登入好了」; ``POST /api/chat-support/verify`` for ``claude`` and then for ``agy`` (with
``shared: true``), both passed.

    python3 tools/qa_p46.py --state "$T/s" --port 7801 --until group     # without the suggestion, the routine and the templates
    python3 tools/qa_p46.py --state "$T/s" --port 7801                    # every stage, ending with ``final``

What it never does: touch ``~/.vbear`` or anything under it, or the ports 7788 and 7789 (it refuses them), print a login code, an
e-mail address, a conversation, a prompt, a word a model wrote, the name of a skill or the name of a plan (only counts, states,
codes, yes/no, times, tokens and money), merge, push or tag. The access token is read from ``<state>/server.token`` (the file the
console wrote for itself) and is never printed or stored. Every sentence it sends and every name it saves is made up (it begins
with QA46).

**The money.** The AGY turns are estimates (tokens, at US$1 a million) and are paid by the Google plan, not in dollars. **What a
Claude stage may spend is capped at US$0.30** (``--claude-cap``, never more): before each stage that uses Claude, the script works out
"Claude spent = the ledger's day - the AGY estimates of the chats it saw + US$0.05 kept for the Claude chat check" and does not run the
stage, and FAILs, when "Claude spent + that stage's cap" would be over the cap. A Claude stage runs with the per-turn limit at
US$0.05, and the limit goes back afterwards.

The stages (each prints ``ok``, ``warn`` or ``FAIL`` lines and the script exits 1 on a FAIL; ``final`` always runs and deletes what
this script made; a condition is what makes a FAIL):

  setup      AGY is ``ready``, version 1.5.3 and ``verified``; Claude Code's chat is verified; the four 自己動手 ticks are false; the
             hashes of config.json, the memory and the shared folder's files are noted.
  card       an AGY role card 「QA46 虛構 AGY 員工」 (safe) is made; its memory switch is off and so is its shared-folder switch.
  text       one AGY turn ends with ``result``, ``estimate`` true and tokens above 0 (prints the tokens and the estimate).
  command    ``ls -a``: a command card that holds ``ls``; allowed; the turn ends and the tool did not fail.
  file       a file tool writes ``qa46.txt``: a file card; allowed; the turn ends.
  outside    a file tool writes outside the work folder: no card, VBear's own refusal in the record, no file there.
  edit       a file card is answered 「改內容再問」 with ``changed``: the turn ends, the next turn asks again in a new card that holds
             ``changed``; allowed.
  stop       a code word is told, then ``sleep 30`` is allowed and stopped after 2 seconds: the turn ends ``stopped``.
  resume     the next message (a new process, ``session/resume``) is asked the code word: the reply holds it.
  memory     switching it on without the yes is 409 ``memory_confirm`` with ``send_to_google``; with the yes 200; one made-up line
             is saved; a new chat is asked for it and the reply holds it (the system prompt got there); off again, the line deleted.
  shared     this release does not open the shared folder to an AGY employee: switching it on is 400 ``card_tool_unsupported``
             with or without the yes, and the sentence says AGY cannot use it in this version.
  group      (Claude) a group of the AGY employee and a Claude Haiku employee: the notes name Anthropic and Google; both answer one
             made-up line; deleted.
  suggest    (Claude) 整理要記住的事 on the AGY chat: the preview says the chat goes to Anthropic too; the suggestion is only read,
             nothing is saved.
  routine    a routine (switched off) for the AGY employee is made (201) and deleted; it is not run.
  templates  the team template 「學習教練」 of 個人生活助理 with AGY: the preview has 1 employee; the apply makes a card in the safe
             mode with tool ``agy`` and no model; the memory and the shared folder's files are the same bytes; the undo deletes it.
  final      what this script made is deleted; the per-turn limit is as it was; config.json is the same bytes as at ``setup``; the
             kinds of record are all v0.19.0's; the ledger, the AGY estimates and turns and Claude's part are printed; Claude spent
             over the cap is a FAIL.

Caps: 25 minutes for the whole run, 4 minutes for any one wait. Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_PORTS = (7788, 7789)
DEFAULT_PORT = 7801
STAGES = ("setup", "card", "text", "command", "file", "outside", "edit", "stop", "resume", "memory", "shared", "group", "suggest",
          "routine", "templates", "final")
CLAUDE_STAGES = {"group": 0.05, "suggest": 0.10}                       # the most each Claude stage may spend (its own cap)
CLAUDE_CAP_MAX = 0.30
CHAT_CHECK_RESERVE = 0.05                                               # kept for the Claude chat check that is run before this script
WALL_CAP_S = 25 * 60
WAIT_CAP_S = 4 * 60
PER_TURN_CLAUDE = 0.05
PAST_THE_END = 999999999
VERSION = "1.5.3"
OWN_NAME = "QA46 虛構 AGY 員工"
CLAUDE_NAME = "QA46 虛構 Claude 員工"
ASK = "（虛構）請只回答：QA46 ok"
ASK_NO_TOOLS = "（虛構）不要使用任何工具，請只回答：QA46 ok"
ASK_LS = "（虛構）請執行指令 ls -a，然後只回答：QA46 完成"
ASK_FILE = "（虛構）請用檔案工具在工作資料夾建立 qa46.txt，內容寫 QA46，然後只回答：QA46 完成"
ASK_EDIT = "（虛構）請用檔案工具在工作資料夾建立 edit46.txt，內容寫 original，然後只回答：QA46 完成"
ASK_SLEEP = "（虛構）請執行指令 sleep 30，然後只回答：QA46 完成"
ASK_GROUP = "（虛構）大家請各自只回答：QA46 ok"
# the kinds of record a chat had in v0.19.0 (chat_store.KINDS): the AGY chat may not add one
V019_KINDS = frozenset("chat_created user_message turn_started process_started session_ready reply tool_call tool_result card card_decision "
                       "auto_allowed denied turn_ended process_ended anomaly error session_bound usage plan_usage card_edit_sent".split())
WATCHED = ("config.json", "memory/memory.json")
SHARED_SENTENCE = "不能用共用資料夾"
LEARN = {"template": "life", "key": "coach"}


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

def _temp_roots() -> list[Path]:
    roots = [Path("/tmp"), Path("/private/tmp")]
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        roots.append(Path(tmpdir))
    return [r.resolve() for r in roots]


def refusal(state: str, port: int, cap: float = CLAUDE_CAP_MAX, home: Path | None = None) -> str | None:
    """Why this run must not start, or None. The person's own VBear (its folder and everything under it, ports 7788 and 7789) is
    never the target; a state folder under /tmp or $TMPDIR is refused because AGY's sandbox may write there (the check's decoys would
    prove nothing); Claude's cap is at most US$0.30."""
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        return "the port must be 1024 to 65535"
    if port in FORBIDDEN_PORTS:
        return f"port {port} is the person's own VBear"
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not 0 < cap <= CLAUDE_CAP_MAX:
        return f"--claude-cap must be above 0 and at most {CLAUDE_CAP_MAX}"
    state_path = Path(state).expanduser().resolve()
    own = ((home or Path.home()).resolve() / ".vbear").resolve()
    if state_path == own or own in state_path.parents:
        return "that is the person's own VBear folder (or inside it); give a temporary one under the home folder"
    for root in _temp_roots():
        if state_path == root or root in state_path.parents:
            return "the state folder is under /tmp or $TMPDIR, where AGY's sandbox may write; make it under the home folder"
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


def digest(path: Path) -> str | None:
    """The hash of a file, or None when there is none (absent has to stay absent)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def watched(state: Path) -> dict:
    """config.json, the memory and every file under shared-meta: a hash for each, None for a file that is not there."""
    state = Path(state)
    out = {name: digest(state / name) for name in WATCHED}
    meta = state / "shared-meta"
    if meta.is_dir():
        for found in sorted(meta.rglob("*")):
            if found.is_file():
                out["shared-meta/" + found.relative_to(meta).as_posix()] = digest(found)
    return out


def differs(before: dict, after: dict) -> list:
    return [k for k in sorted(set(before) | set(after)) if before.get(k, "<missing>") != after.get(k, "<missing>")]


def kinds_in(state: Path) -> set:
    """The set of ``kind`` words in every ``chats/*/events.jsonl`` (only the words; a line that cannot be read is the word ``?``)."""
    found = set()
    for path in sorted((Path(state) / "chats").glob("*/events.jsonl")):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            found.add("?")
            continue
        for line in lines:
            try:
                kind = json.loads(line).get("kind")
            except (ValueError, AttributeError):
                kind = None
            found.add(kind if isinstance(kind, str) else "?")
    return found


def claude_spent(ledger: float | None, agy_estimates: float, reserve: float = CHAT_CHECK_RESERVE) -> float | None:
    """What Claude has cost so far: the ledger's day, less the AGY estimates (which are not money), plus the reserve for the chat check."""
    if ledger is None:
        return None
    return max(0.0, ledger - agy_estimates) + reserve


def claude_allowed(spent: float | None, stage_cap: float, cap: float) -> bool:
    """Whether a Claude stage may start: unknown is no, and so is "spent + this stage's cap" over the cap."""
    return spent is not None and spent + stage_cap <= cap + 1e-9


def turn_facts(records: list, turn) -> dict:
    """What a turn left, without a word of the model's: the cards asked, what VBear refused itself, what a tool returned, how it ended."""
    mine = [r for r in records if isinstance(r, dict) and r.get("turn") == turn]
    return {"cards": [r for r in mine if r.get("kind") == "card"],
            "refused": [r for r in mine if r.get("kind") == "denied" and r.get("by") == "vbear"],
            "results": [r for r in mine if r.get("kind") == "tool_result"],
            "reply": " ".join(str(r.get("text") or "") for r in mine if r.get("kind") == "reply"),
            "end": next((r for r in mine if r.get("kind") == "turn_ended"), None)}


def card_text(card: dict) -> str:
    """Everything a card asks for, as one string (to look for a made-up word in it); never printed."""
    try:
        return json.dumps(card.get("input"), ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


# ---- the run ------------------------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, console, state: Path, until: str, start: str, skip: set, claude_cap: float, check: Check,
                 clock=time.monotonic, sleep=time.sleep, rand=secrets.token_hex):
        self.c, self.state, self.until, self.first, self.skip, self.cap, self.check = console, Path(state), until, start, skip, claude_cap, check
        self.clock, self.sleep, self.rand = clock, sleep, rand
        self.started = clock()
        self.memo_path = self.state.parent / "qa46.json"
        self.memo: dict = {}
        self.ready = False

    # -- the memo: ids and money, never a name or a word ------------------------------------------------------------------------

    def save(self) -> None:
        self.memo_path.write_text(json.dumps(self.memo, sort_keys=True))

    def load(self) -> None:
        try:
            self.memo = json.loads(self.memo_path.read_text())
        except (OSError, ValueError):
            raise Stop("no qa46.json next to the state folder: start from the stage setup") from None
        if not isinstance(self.memo, dict) or "base" not in self.memo:
            raise Stop("qa46.json is not one of this script's")

    def made(self, kind: str, ident) -> None:
        got = self.memo.setdefault("made", {})
        if isinstance(ident, str) and ident and ident not in got.setdefault(kind, []):
            got[kind].append(ident)

    def reached(self, stage: str) -> bool:
        return STAGES.index(self.first) <= STAGES.index(stage) <= STAGES.index(self.until) and stage not in self.skip

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

    def ledger(self) -> float | None:
        return money(self.c.ok("/api/meetings/ledger").get("spent_usd"))

    def cards(self) -> dict:
        return {p["id"]: p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict) and "id" in p}

    def ticks(self) -> dict:
        return self.c.ok("/api/settings/autonomy").get("autonomy") or {}

    def records(self, chat_id: str) -> list:
        after, out = 0, []
        for _ in range(50):
            page = self.c.ok(f"/api/chats/{chat_id}?after={after}")
            out += [r for r in page.get("records", []) if isinstance(r, dict)]
            if not page.get("more"):
                return out
            after = page.get("next_after", after)
        return out

    def live_cards(self, chat_id: str) -> list:
        live = self.c.ok(f"/api/chats/{chat_id}?after={PAST_THE_END}").get("live")
        cards = live.get("cards") if isinstance(live, dict) else None
        return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []

    def switch(self, page: str, pid: str):
        card = next((c for c in self.c.ok(page).get("cards", []) if isinstance(c, dict) and c.get("profile_id") == pid), None)
        return None if card is None else card

    # -- money -----------------------------------------------------------------------------------------------------------------

    def agy_total(self) -> float:
        return float(self.memo.get("agy_estimate", 0.0))

    def count_agy(self, chat_ids) -> None:
        """Add the estimate of every AGY turn of these chats that was not counted yet (a turn's end that says ``estimate``)."""
        counted = self.memo.setdefault("counted", [])
        for chat_id in chat_ids:
            for rec in self.records(chat_id):
                if rec.get("kind") == "turn_ended" and rec.get("estimate") is True:
                    key = f"{chat_id}:{rec.get('turn')}"
                    if key not in counted:
                        counted.append(key)
                        self.memo["agy_estimate"] = self.agy_total() + (money(rec.get("cost_usd")) or 0.0)
                        self.memo["agy_turns"] = self.memo.get("agy_turns", 0) + 1
                        self.memo["agy_tokens"] = self.memo.get("agy_tokens", 0) + (rec.get("tokens") if isinstance(rec.get("tokens"), int) else 0)

    def claude_part(self) -> float | None:
        return claude_spent(self.ledger(), self.agy_total())

    def set_per_turn(self, value) -> None:
        self.c.ok("/api/config", "POST", {"chat_limits": {"per_turn_usd": value}})

    def restore_per_turn(self) -> None:
        if isinstance(self.memo.get("base", {}).get("per_turn"), (int, float)):
            self.set_per_turn(self.memo["base"]["per_turn"])

    def claude_stage(self, stage: str):
        """True when the stage may use Claude (its cap fits under the total cap); sets the per-turn limit down for it."""
        spent = self.claude_part()
        if not claude_allowed(spent, CLAUDE_STAGES[stage], self.cap):
            self.check.fail(f"Claude's part would go over US${self.cap:.2f}: the stage {stage} is not run",
                            f"spent US${spent if spent is None else round(spent, 4)} + the stage's US${CLAUDE_STAGES[stage]:.2f}")
            return False
        self.set_per_turn(PER_TURN_CLAUDE)
        return True

    # -- one question to an employee -------------------------------------------------------------------------------------------

    def open_chat(self, pid: str) -> str:
        chat = self.c.ok("/api/chats", "POST", {"profile_id": pid})["chat"]["id"]
        self.made("chats", chat)
        self.save()
        return chat

    def answer(self, chat_id: str, card: dict, decision, value=None) -> None:
        body = {"card_id": card.get("card_id"), "token": card.get("token"), "decision": decision}
        if value is not None:
            body["value"] = value
        self.c.ok(f"/api/chats/{chat_id}/answer", "POST", body)

    def ask(self, chat_id: str, text: str, decide=lambda card: "deny", cap: float = WAIT_CAP_S) -> dict:
        """Send ``text``; answer every card with ``decide`` (a decision word, or ``("modify", text)``); wait for the end of the turn.
        Returns ``refused`` with the status when the message was not taken, else the turn's facts and ``process``."""
        code, sent = self.c.call(f"/api/chats/{chat_id}/messages", "POST", {"text": text})
        if code not in (200, 201, 202) or not isinstance(sent, dict):
            return {"refused": True, "status": code, "code": sent.get("code") if isinstance(sent, dict) else None}
        turn, seen = sent.get("turn"), set()
        self.memo["turns"] = self.memo.get("turns", 0) + 1

        def ended():
            for card in self.live_cards(chat_id):
                cid = card.get("card_id")
                if cid in seen:
                    continue
                seen.add(cid)
                got = decide(card)
                if isinstance(got, tuple):
                    self.answer(chat_id, card, got[0], got[1])
                else:
                    self.answer(chat_id, card, got)
            recs = self.records(chat_id)
            return recs if any(r.get("kind") == "turn_ended" and r.get("turn") == turn for r in recs) else None
        recs = self.wait("the end of the turn", ended, cap=cap)
        self.count_agy([chat_id])
        facts = turn_facts(recs, turn)
        facts.update(refused_message=False, process=sent.get("process"), turn=turn, seen=seen)
        return facts

    def tokens_of(self, end: dict | None):
        return end.get("tokens") if isinstance(end, dict) and isinstance(end.get("tokens"), int) else None

    # -- stages ----------------------------------------------------------------------------------------------------------------

    def start(self) -> None:
        if self.first == "setup":
            self.memo = {}
        else:
            self.load()
        self.ready = True

    def setup(self) -> None:
        support = self.c.ok("/api/chat-support")
        agy = support.get("agy") if isinstance(support.get("agy"), dict) else {}
        self.check.expect(agy.get("state") == "ready" and agy.get("version") == VERSION and agy.get("verified") is True,
                          "AGY is ready, 1.5.3 and verified for chat", f"state {agy.get('state')}, version {agy.get('version')}, verified {agy.get('verified')}")
        self.check.expect(support.get("state") == "verified", "Claude Code's chat is verified", f"state {support.get('state')}")
        ticks = self.ticks()
        self.check.expect(len(ticks) == 4 and all(v is False for v in ticks.values()), "the four 自己動手 ticks are false", f"{len(ticks)} ticks")
        conf = (self.c.ok("/api/config").get("config") or {})
        per_turn = (conf.get("chat_limits") or {}).get("per_turn_usd") if isinstance(conf.get("chat_limits"), dict) else None
        base = {"watched": watched(self.state), "per_turn": per_turn, "ledger": self.ledger()}
        self.memo = {"base": base, "made": {}, "turns": 0, "agy_estimate": 0.0, "agy_turns": 0, "agy_tokens": 0, "counted": []}
        self.check.ok("noted: the hashes of config.json, the memory and the shared folder's files; the per-turn limit", f"limit {per_turn}")

    def card(self) -> None:
        made = self.c.ok("/api/agent-profiles", "POST", {"name": OWN_NAME, "position": "pm", "launch_mode": "safe", "model": {"tool": "agy"}})
        pid = (made.get("profile") or {}).get("id")
        if not isinstance(pid, str):
            raise Stop("the AGY role card was made without an id")
        self.memo["agy"] = pid
        self.made("cards", pid)
        self.save()
        memory = self.switch("/api/memory", pid)
        shared = self.switch("/api/shared", pid)
        self.check.expect(memory is not None and memory.get("on") is False and shared is not None and shared.get("on") is False,
                          "the new AGY employee has the memory and the shared folder switched off (the default)")

    def employee(self) -> str:
        pid = self.memo.get("agy")
        if not isinstance(pid, str):
            raise Stop("no AGY employee in qa46.json: run the stage card")
        return pid

    def chat(self) -> str:
        chat = self.memo.get("chat")
        if not isinstance(chat, str):
            chat = self.open_chat(self.employee())
            self.memo["chat"] = chat
            self.save()
        return chat

    def text(self) -> None:
        facts = self.ask(self.chat(), ASK)
        if facts.get("refused"):
            raise Stop(f"the first message was refused ({facts.get('code')})")
        end = facts["end"] or {}
        tokens = self.tokens_of(end)
        self.check.expect(end.get("reason") == "result" and end.get("estimate") is True and isinstance(tokens, int) and tokens > 0,
                          "an AGY turn ended with a result, as an estimate, with tokens", f"reason {end.get('reason')}, {tokens} tokens, US${end.get('cost_usd')}")

    def command(self) -> None:
        facts = self.ask(self.chat(), ASK_LS, decide=lambda card: "allow")
        cmd = [c for c in facts["cards"] if c.get("tool") == "command" and "ls" in card_text(c)]
        failed = [r for r in facts["results"] if r.get("is_error") is True]
        self.check.expect(bool(cmd), "ls -a came as a command card that holds the command", f"{len(facts['cards'])} cards")
        self.check.expect((facts["end"] or {}).get("reason") == "result" and not failed, "it was allowed, the turn ended and the tool did not fail",
                          f"{len(failed)} failed")

    def file(self) -> None:
        facts = self.ask(self.chat(), ASK_FILE, decide=lambda card: "allow")
        files = [c for c in facts["cards"] if c.get("tool") == "file_change" and "qa46.txt" in card_text(c)]
        self.check.expect(bool(files), "a file change came as a file card with the path", f"{len(facts['cards'])} cards")
        self.check.expect((facts["end"] or {}).get("reason") == "result", "it was allowed and the turn ended")

    def outside(self) -> None:
        target = self.state.parent / "qa46-outside.txt"
        facts = self.ask(self.chat(), f"（虛構）請用檔案工具把檔案 {target} 寫成內容 QA46，然後只回答：QA46 完成", decide=lambda card: "deny")
        files = [c for c in facts["cards"] if c.get("tool") == "file_change"]
        self.check.expect(not files, "no file card for a place outside the work folder", f"{len(files)} cards")
        self.check.expect(len(facts["refused"]) >= 1, "VBear refused it itself (denied by vbear in the record)", f"{len(facts['refused'])} refusals")
        self.check.expect(not os.path.lexists(target), "the file is not there")

    def edit(self) -> None:
        chat = self.chat()
        first_seen = []

        def decide(card):
            first_seen.append(card)
            return ("modify", "changed")
        facts = self.ask(chat, ASK_EDIT, decide=decide)
        self.check.expect(any(c.get("tool") == "file_change" for c in facts["cards"]), "the first file card came", f"{len(facts['cards'])} cards")
        old = {c.get("card_id") for c in first_seen}

        def again():
            return next((c for c in self.live_cards(chat) if c.get("card_id") not in old), None)
        second = self.wait("the second card", again)
        self.check.expect(second.get("tool") == "file_change" and "changed" in card_text(second),
                          "the next turn asked again in a new card that holds the changed content")
        self.answer(chat, second, "allow")
        end = self.wait("the end of the second turn", lambda: next(
            (r for r in self.records(chat) if r.get("kind") == "turn_ended" and r.get("turn") == facts["turn"] + 1), None))
        self.count_agy([chat])
        self.check.expect(end.get("reason") == "result", "the second turn ended with a result")

    def stop(self) -> None:
        chat = self.chat()
        word = "QA46-" + self.rand(4)
        self.memo["word"] = word
        self.save()
        told = self.ask(chat, f"（虛構）請記住代號 {word}。不要使用任何工具，只回答：QA46 ok")
        self.check.expect((told["end"] or {}).get("reason") == "result", "the code word was told in a turn that ended with a result")
        code, sent = self.c.call(f"/api/chats/{chat}/messages", "POST", {"text": ASK_SLEEP})
        if code not in (200, 201, 202) or not isinstance(sent, dict):
            raise Stop(f"the message for the stop was refused ({sent.get('code') if isinstance(sent, dict) else code})")
        turn, asked = sent.get("turn"), set()
        self.memo["turns"] = self.memo.get("turns", 0) + 1

        def card():
            return next((c for c in self.live_cards(chat) if "sleep" in card_text(c)), None)
        got = self.wait("the command card of sleep 30", card)
        asked.add(got.get("card_id"))
        self.answer(chat, got, "allow")
        self.sleep(2.0)
        self.c.ok(f"/api/chats/{chat}/stop", "POST", {})
        end = self.wait("the end of the stopped turn", lambda: next(
            (r for r in self.records(chat) if r.get("kind") == "turn_ended" and r.get("turn") == turn), None), cap=60)
        self.count_agy([chat])
        self.check.expect(end.get("reason") == "stopped", "the turn ended because it was stopped", f"reason {end.get('reason')}")

    def resume(self) -> None:
        word = self.memo.get("word")
        if not isinstance(word, str):
            raise Stop("no code word in qa46.json: run the stage stop")
        facts = self.ask(self.chat(), "（虛構）我剛才告訴你的代號是什麼？不要使用任何工具，只回答代號。")
        if facts.get("refused"):
            raise Stop(f"the question was refused ({facts.get('code')})")
        self.check.expect(word in facts["reply"], "the reply holds the code word (the conversation was resumed)", f"process {facts.get('process')}")
        if facts.get("process") != "resume":
            self.check.warn("the message did not start a resumed process", f"process {facts.get('process')}")

    def memory(self) -> None:
        pid = self.employee()
        code, data = self.c.call("/api/memory/cards", "POST", {"profile_id": pid, "on": True})
        warn = data.get("warn") if isinstance(data, dict) else None
        self.check.expect(code == 409 and isinstance(data, dict) and data.get("code") == "memory_confirm" and isinstance(warn, list) and "send_to_google" in warn,
                          "switching the memory on without the yes is 409 memory_confirm with send_to_google", f"{code}")
        self.c.ok("/api/memory/cards", "POST", {"profile_id": pid, "on": True, "confirm_company": True})
        self.memo["memory_on"] = True
        self.save()
        word = "QA46M-" + self.rand(4)
        saved = self.c.ok("/api/memory", "POST", {"kind": "work", "text": f"QA46 的暗號是 {word}（虛構）"}, status=(200, 201))
        entry = (saved.get("entry") or {}).get("id")
        self.made("memory", entry)
        self.save()
        chat = self.open_chat(pid)
        facts = self.ask(chat, "（虛構）QA46 的暗號是什麼？不要使用任何工具，只回答暗號。")
        if facts.get("refused"):
            raise Stop(f"the question was refused ({facts.get('code')})")
        self.check.expect(word in facts["reply"], "a new chat is asked for the line and the reply holds it (the memory reached the system prompt)")
        self.c.ok("/api/memory/cards", "POST", {"profile_id": pid, "on": False})
        self.memo["memory_on"] = False
        if isinstance(entry, str):
            self.c.call(f"/api/memory/{entry}", "DELETE")
        card = self.switch("/api/memory", pid)
        self.check.expect(card is not None and card.get("on") is False, "the memory is switched off again and the line is deleted")

    def shared(self) -> None:
        pid = self.employee()
        for body in ({"profile_id": pid, "on": True}, {"profile_id": pid, "on": True, "confirm_company": True}):
            code, data = self.c.call("/api/shared/cards", "POST", body)
            said = str((data or {}).get("error") or "") if isinstance(data, dict) else ""
            self.check.expect(code == 400 and isinstance(data, dict) and data.get("code") == "card_tool_unsupported" and SHARED_SENTENCE in said,
                              "the shared folder is not open to an AGY employee: 400 card_tool_unsupported, and the sentence says so",
                              f"{code}, yes to Google: {body.get('confirm_company') is True}")
        card = self.switch("/api/shared", pid)
        self.check.expect(card is not None and card.get("on") is False and card.get("company") is None, "the page still shows it off, with no company to send to")
        shared_dir = self.state / "shared"
        names = sorted(p.name for p in shared_dir.iterdir()) if shared_dir.is_dir() else []
        self.check.expect(not names, "nothing of AGY's is in the shared folder", f"{len(names)} files")

    def claude_card(self) -> str:
        pid = self.memo.get("claude")
        if isinstance(pid, str):
            return pid
        made = self.c.ok("/api/agent-profiles", "POST", {"name": CLAUDE_NAME, "position": "pm", "launch_mode": "safe",
                                                          "model": {"tool": "claude", "model_id": "haiku"}})
        pid = (made.get("profile") or {}).get("id")
        if not isinstance(pid, str):
            raise Stop("the Claude role card was made without an id")
        self.memo["claude"] = pid
        self.made("cards", pid)
        self.save()
        return pid

    def group(self) -> None:
        if not self.claude_stage("group"):
            return
        claude = self.claude_card()
        mine = self.employee()
        model = (self.cards().get(claude, {}).get("model") or {}).get("model_id")
        if model != "haiku":
            self.check.fail("the Claude employee has the model haiku (nothing is sent otherwise)", f"model {model!r}")
            return
        made = self.c.ok("/api/groups", "POST", {"profile_ids": [mine, claude], "name": "QA46 群組"})
        gid = (made.get("group") or {}).get("id")
        if not isinstance(gid, str):
            raise Stop("the group has no id")
        self.made("groups", gid)
        self.save()
        notes = " ".join(str(n) for n in made.get("notes", []))
        self.check.expect("Anthropic" in notes and "Google" in notes, "the notice of a group of the two names Anthropic and Google")
        self.c.ok(f"/api/groups/{gid}/messages", "POST", {"text": ASK_GROUP, "to": "all"})
        self.memo["turns"] = self.memo.get("turns", 0) + 2
        answered, chats = set(), set()

        def idle():
            view = self.c.ok(f"/api/groups/{gid}")
            current = view.get("current")
            if isinstance(current, dict) and isinstance(current.get("chat_id"), str):
                chats.add(current["chat_id"])
                for card in self.live_cards(current["chat_id"]):
                    if card.get("card_id") not in answered:
                        answered.add(card.get("card_id"))
                        self.answer(current["chat_id"], card, "deny")
            replies = [i for i in view.get("items", []) if isinstance(i, dict) and i.get("kind") == "reply"]
            return view if (view.get("group") or {}).get("state") == "idle" and replies else None
        view = self.wait("the group's round to end", idle)
        self.count_agy(chats)
        who = {i.get("profile_id") for i in view.get("items", []) if isinstance(i, dict) and i.get("kind") == "reply"}
        self.check.expect({mine, claude} <= who, "both the AGY employee and the Claude employee answered", f"{len(who)} answered")
        self.c.ok(f"/api/groups/{gid}", "DELETE")
        self.memo["made"]["groups"].remove(gid)
        self.restore_per_turn()

    def suggest(self) -> None:
        chat = self.memo.get("chat")
        if not isinstance(chat, str):
            raise Stop("the suggestion needs the AGY chat of the stage text")
        if not self.claude_stage("suggest"):
            return
        before = (self.c.ok("/api/memory").get("used") or {}).get("count")
        pv = self.c.ok("/api/memory/suggest/preview", "POST", {"chat_id": chat})
        if pv.get("ok") is not True and any(isinstance(b, dict) and b.get("code") == "boundary_unverified" for b in pv.get("blockers", [])):
            self.check.ok("the tool-less check was not done; doing it now (as the dialog's button does)")
            self.c.ok("/api/meetings/verify", "POST", {})
            pv = self.c.ok("/api/memory/suggest/preview", "POST", {"chat_id": chat})
        notice = str(pv.get("notice") or "")
        cap = money(pv.get("cap_usd"))
        self.check.expect(pv.get("ok") is True and pv.get("sends_to") == "Anthropic" and "AGY 員工的對話" in notice and "Anthropic" in notice,
                          "the preview says an AGY chat goes to Anthropic too", f"cap US${cap}")
        if pv.get("ok") is not True or cap is None or cap > CLAUDE_STAGES["suggest"] + 1e-9:
            self.check.fail("the preview's cap is within the stage's US$0.10", f"cap {cap}")
            self.restore_per_turn()
            return
        started = self.c.ok("/api/memory/suggest", "POST", {"preview_id": pv.get("preview_id")})
        sid = started["id"]
        view = self.wait("the suggestion to end", lambda: (lambda v: v if v.get("status") != "running" else None)(self.c.ok(f"/api/memory/suggest/{sid}")))
        if view.get("status") == "ready":
            self.check.ok("the suggestion came back", f"{len(view.get('items', []))} items")
        else:
            self.check.warn("the suggestion did not end ready (the model's, not a condition)", f"{view.get('status')}/{view.get('error_code')}")
        after = (self.c.ok("/api/memory").get("used") or {}).get("count")
        self.check.expect(after == before, "the run saved nothing: the memory is as it was", f"{after} lines")
        self.c.call(f"/api/memory/suggest/{sid}", "DELETE")
        self.restore_per_turn()

    def routine(self) -> None:
        pid = self.employee()
        code, data = self.c.call("/api/routines", "POST", {"name": "QA46 虛構例行工作", "profile_id": pid, "text": "（虛構）請整理三行待辦。",
                                                           "days": [1], "times": ["09:00"], "enabled": False})
        rid = ((data or {}).get("routine") or {}).get("id") if isinstance(data, dict) else None
        self.check.expect(code == 201 and isinstance(rid, str), "a routine for the AGY employee is made (switched off)", f"{code}")
        if isinstance(rid, str):
            self.made("routines", rid)
            self.save()
            self.c.call(f"/api/routines/{rid}/delete", "POST", {})
            self.memo["made"]["routines"].remove(rid)

    def templates(self) -> None:
        body = {"tool": "agy", "cards": [{"from": LEARN}], "skills": [], "routines": []}
        got = self.c.ok("/api/templates/preview", "POST", body)
        plan = got.get("preview") or {}
        self.check.expect(plan.get("ok") is True and len(plan.get("cards", [])) == 1 and plan.get("problems") == [], "the preview has 1 employee and no problem",
                          f"{len(plan.get('cards', []))} employees")
        before = watched(self.state)
        code, data = self.c.call("/api/templates/apply", "POST", body)
        apply = (data.get("apply") if isinstance(data, dict) else None) or {}
        items = [i for i in apply.get("items", []) if isinstance(i, dict) and i.get("state") == "made" and i.get("kind") == "card"]
        for item in items:
            self.made("cards", item.get("id"))
        self.save()
        self.check.expect(code == 201 and len(items) == 1, "the apply made 1 employee", f"{code}")
        if len(items) != 1:
            return
        card = self.cards().get(items[0].get("id"), {})
        model = card.get("model") if isinstance(card.get("model"), dict) else {}
        self.check.expect(card.get("launch_mode") == "safe" and model.get("tool") == "agy" and (model.get("model_id") or "") == "" and card.get("equipped_skill_ids") in ([], None),
                          "the new employee is safe, tool agy, no model, no skill card")
        moved = differs(before, watched(self.state))
        self.check.expect(not moved, "the memory and the shared folder's files are the same bytes after the apply", f"{len(moved)} differ")
        apply_id = apply.get("id")
        plan = self.c.ok(f"/api/templates/applies/{apply_id}/undo-preview", "POST", {})
        ids = [d.get("id") for d in plan.get("delete", [])]
        done = self.c.ok(f"/api/templates/applies/{apply_id}/undo", "POST", {"delete": ids})
        self.check.expect(len(done.get("deleted", [])) == 1 and items[0].get("id") not in self.cards(), "the undo deleted it at once")

    def final(self) -> None:
        if "base" not in self.memo:
            raise Stop("setup did not finish, so there is nothing to compare with")
        base, got = self.memo["base"], self.memo.get("made", {})
        # the memory line and the switch, in case a stage stopped in the middle
        if self.memo.get("memory_on") and isinstance(self.memo.get("agy"), str):
            self.c.call("/api/memory/cards", "POST", {"profile_id": self.memo["agy"], "on": False})
        for ident in got.get("memory", []):
            self.c.call(f"/api/memory/{ident}", "DELETE")
        for ident in got.get("groups", []):
            self.c.call(f"/api/groups/{ident}", "DELETE")
        for ident in got.get("routines", []):
            self.c.call(f"/api/routines/{ident}/delete", "POST", {})
        self.count_agy([c for c in got.get("chats", [])])
        for chat in got.get("chats", []):
            self.c.call(f"/api/chats/{chat}", "DELETE")
        for ident in got.get("cards", []):
            self.c.call(f"/api/agent-profiles/{ident}/delete", "POST", {})
        self.check.ok("what this script made is deleted with the ordinary routes",
                      f"{len(got.get('cards', []))} employees, {len(got.get('chats', []))} chats, {len(got.get('groups', []))} groups left to delete")
        conf = (self.c.ok("/api/config").get("config") or {})
        per_turn = (conf.get("chat_limits") or {}).get("per_turn_usd") if isinstance(conf.get("chat_limits"), dict) else None
        if per_turn != base.get("per_turn"):
            self.restore_per_turn()
        conf = (self.c.ok("/api/config").get("config") or {})
        per_turn = (conf.get("chat_limits") or {}).get("per_turn_usd") if isinstance(conf.get("chat_limits"), dict) else None
        self.check.expect(per_turn == base.get("per_turn"), "the per-turn limit is what setup noted", f"{per_turn}")
        now = watched(self.state)
        self.check.expect(now.get("config.json") == base["watched"].get("config.json"), "config.json is the same bytes as at setup")
        ticks = self.ticks()
        self.check.expect(len(ticks) == 4 and all(v is False for v in ticks.values()), "the four 自己動手 ticks are false")
        kinds = kinds_in(self.state)
        extra = sorted(kinds - V019_KINDS)
        self.check.expect(not extra, "every kind of record in the chats is one v0.19.0 already had", f"{len(kinds)} kinds, {len(extra)} new")
        ledger = self.ledger()
        claude = claude_spent(ledger, self.agy_total(), 0.0)
        self.check.ok("the day's ledger, the AGY estimates and turns, and Claude's part (by VBear's own counting)",
                      f"ledger US${ledger}; AGY estimate US${round(self.agy_total(), 4)} over {self.memo.get('agy_turns', 0)} turns, {self.memo.get('agy_tokens', 0)} tokens; "
                      f"Claude US${None if claude is None else round(claude, 4)} (cap US${self.cap:.2f}); {self.memo.get('turns', 0)} messages sent")
        self.check.expect(claude is not None and claude + CHAT_CHECK_RESERVE <= self.cap + 1e-9,
                          "Claude's part (with the chat check's US$0.05) is within the cap")


def main(argv=None, out=print, console_factory=Console, clock=time.monotonic, sleep=time.sleep, home: Path | None = None,
         rand=secrets.token_hex) -> int:
    ap = argparse.ArgumentParser(description="v0.20.0 real check of the AGY chat (see the file's docstring)")
    ap.add_argument("--state", required=True, help="the temporary state folder of the console (VBEAR_HOME), under the home folder")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="the console's port (never 7788 or 7789)")
    ap.add_argument("--from", dest="first", choices=STAGES, default=STAGES[0], help="the first stage to run (after setup it needs qa46.json)")
    ap.add_argument("--until", choices=STAGES, default=STAGES[-1], help="the last stage to run")
    ap.add_argument("--skip", action="append", choices=STAGES[:-1], default=[], help="a stage to leave out (for example suggest)")
    ap.add_argument("--claude-cap", type=float, default=CLAUDE_CAP_MAX, help="the most Claude's part may cost (at most 0.30)")
    args = ap.parse_args(argv)
    why = refusal(args.state, args.port, args.claude_cap, home)
    if why:
        out(f"refused: {why}")
        return 2
    if STAGES.index(args.first) > STAGES.index(args.until):
        out("refused: --from is after --until")
        return 2
    check = Check(out)
    run = None
    try:
        state = Path(args.state).expanduser().resolve()
        console = console_factory(args.port, read_token(state, args.port))
        run = Run(console, state, args.until, args.first, set(args.skip), args.claude_cap, check, clock=clock, sleep=sleep, rand=rand)
        run.start()
        for stage in STAGES[:-1]:
            if run.reached(stage):
                getattr(run, stage)()
                run.save()
    except Stop as exc:
        check.fail("stopped", str(exc))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        check.fail("unexpected", f"{type(exc).__name__}: {str(exc)[:120]}")
    finally:
        if run is not None and run.ready:
            try:
                run.final()
                run.save()
            except Stop as exc:
                check.fail("final stopped", str(exc))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
                check.fail("final unexpected", f"{type(exc).__name__}: {str(exc)[:120]}")
    out(f"qa_p46: {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
