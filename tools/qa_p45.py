#!/usr/bin/env python3
"""v0.19.0 real check of the team templates (P45): the coordinator's run before the release, through the console's HTTP API only.

It is a developer check, never part of the product. It calls the endpoints of this release (/api/templates, /preview, /apply,
/applies/<id>/undo-preview and /undo, /mine) and the ones a person's press would use (/api/chats to open, send and read one chat;
/api/agent-profiles, /api/my-skills and /api/routines to read, to change one skill and one routine and, at the end, to delete what it
made; /api/settings/autonomy and /api/meetings/ledger to read). It runs no program and no AI tool itself: the console it talks to
runs a real Claude Code (Haiku) for the one turn of the ``chat`` stage, which is the point of the check and is why it needs a state
folder of its own.

Besides the HTTP API it reads only these, in the state folder ``<state>`` (``$T/s``) and writes one file of its own:

  * ``<state>/config.json``, ``<state>/memory/memory.json`` and every file under ``<state>/shared-meta/``: the bytes (a hash) at the
    start and at the end, absent stays absent: a team template must not touch them;
  * ``<state>/agent_profiles.json``, ``<state>/skillbook/skills.json`` and ``<state>/routines/routines.json``: a hash, to see that a
    preview and an undo-preview write nothing;
  * the names (not the contents) of the files in ``<state>``, before and after a preview;
  * ``<state>/templates/applies.json`` and ``<state>/templates/log.jsonl``: yes/no, does any name or word this script used appear in
    them (they must hold none);
  * ``$T/qa45.json``: the one file it writes (ids it made, counts and hashes; never a name, a word or a secret).

Coordinator's steps before it (plan.md, real-machine steps 1 to 3): a short temporary state folder ``$T/s``; a console started on it
(``VBEAR_HOME=$T/s BROWSER=/usr/bin/true vbear serve --port 7800``); ``POST /api/setup/daily-limit {0.10}`` and ``POST /api/config
{chat_limits.per_turn_usd 0.05, setup_done true, welcome_seen true}`` (VBear's own daily limit is the hard cap of the money);
``POST /api/chat-support/verify {engine: claude}``. It needs no role card made beforehand: the team templates make the employees.

    python3 tools/qa_p45.py --state "$T/s" --port 7800 --until preview      # no model, no money, nothing written
    python3 tools/qa_p45.py --state "$T/s" --port 7800                      # every stage, ending with ``final``

What it never does: touch ``~/.vbear`` or anything under it, or the ports 7788 and 7789 (it refuses them), print a login code, an e-mail
address, a conversation, a prompt or a word a model wrote (only counts, states, codes, yes/no and money), merge, push or tag. The access
token is read from ``<state>/server.token``, the file that console wrote for itself, and is never printed or stored. Every sentence it
sends and every name it saves is made up (it begins with QA45).

The stages (each prints ``ok``, ``warn`` or ``FAIL`` lines and the script exits 1 on a FAIL; ``final`` always runs, and deletes what
this script made; a condition is what makes a FAIL):

  setup          the four built-in team templates are exactly shop, creator, studio and life; none of the person's own and no apply
                 yet; the four 自己動手 ticks are false; the counts of cards, skills and routines, the hashes of the three files and the
                 bytes of config.json, the memory and the shared folder's files are noted.
  browse         every employee of the list has a position of the eight, or none; nothing in the list has a launch mode and no routine
                 is on.
  preview        ticked: all of 小店 and, of 自媒體, 寫稿 and 改成短影音腳本 (4 employees, 4 skills, 2 routines): the preview says exactly
                 that and has no problem; the three hashes and the names of the files in the state folder are the same after.
  apply          the same ticks with Claude Code: 201; 4 new employees, each ``safe``, no skill card, Claude Code, with the model the
                 template says; 4 new skills with ``how: typed``; 2 new routines, both off; config.json, the memory and the shared
                 folder are the same bytes; the number of chats and the day's spending did not move (an apply uses no AI).
  chat           the employee 客服 must have the model ``haiku`` (else FAIL and nothing is sent); one new chat, one made-up sentence;
                 the turn ends with ``result`` (a card, if one comes, is refused). Prints the state and the cost only.
  change         the skill 寫商品介紹 and the routine 想下週的促銷 get " (QA45 改過)" at the end of their words; the routine stays off.
  undo-preview   kept: 客服 (chatted), the skill and the routine that were changed, and 商品文案 (a routine that stays goes to him);
                 deleted: 會計, 寫稿, the other 3 skills and the routine 整理昨天的花費; the three hashes are the same after.
  undo           the ids of the preview are given back: what is deleted is what the preview said, what is kept has the same reasons;
                 what was deleted is gone and what was kept is still there; asking again, there is nothing more to delete.
  mine           the person's own team template is saved from the existing 客服 and 做學習計畫 of 個人生活助理, named QA45 虛構團隊範本:
                 201; the list shows it; its employee has only key, name, position, instructions and claude_model.
  reapply        that team template, all of it, with Claude Code: 1 employee and 1 skill; undone at once, both are deleted.
  final          the own team template is deleted; what this script left (the kept employees, the skill, the routine) is deleted with
                 the ordinary delete routes; the counts are what ``setup`` noted; config.json, the memory and the shared folder are the
                 same bytes; the ticks are false and no routine is on; applies.json and log.jsonl hold no name or word of the script's;
                 prints the day's spending and the turns (1); over US$0.10 is a FAIL.

Caps: 15 minutes for the whole run, 4 minutes for any one wait. Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_PORTS = (7788, 7789)
STAGES = ("setup", "browse", "preview", "apply", "chat", "change", "undo-preview", "undo", "mine", "reapply", "final")
WALL_CAP_S = 15 * 60
WAIT_CAP_S = 4 * 60
SPEND_CEILING_USD = 0.10
PAST_THE_END = 999999999
BUILTIN = ["shop", "creator", "studio", "life"]
POSITIONS = ("planner", "executor", "social", "art", "pm", "legal", "accountant", "reviewer")
OWN_NAME = "QA45 虛構團隊範本"
CHANGE_TAIL = "（QA45 改過）"
ASK = "（虛構）請只回答：QA45 ok"
MINE_KEYS = ["claude_model", "instructions", "key", "name", "position"]
# the things this script ticks: (template, key)
CARDS = (("shop", "service"), ("shop", "copy"), ("shop", "accounting"), ("creator", "writer"))
SKILLS = (("shop", "reply"), ("shop", "product"), ("shop", "daybook"), ("creator", "short"))
ROUTINES = (("shop", "spend"), ("shop", "promo"))
SERVICE, COPY, ACCOUNTING, WRITER = CARDS
PRODUCT, PROMO, SPEND, STUDY = ("shop", "product"), ("shop", "promo"), ("shop", "spend"), ("life", "study")
WATCHED = ("config.json", "memory/memory.json")
STORES = {"cards": "agent_profiles.json", "skills": "skillbook/skills.json", "routines": "routines/routines.json"}
TRANSIENT = ("routines/heartbeat.json",)


def ref(pair):
    return {"template": pair[0], "key": pair[1]}


def tick(pair, **extra):
    return {"from": ref(pair), **extra}


def body_of(tool="claude"):
    return {"tool": tool, "cards": [tick(p) for p in CARDS], "skills": [tick(p) for p in SKILLS], "routines": [tick(p) for p in ROUTINES]}


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


def digest(path: Path) -> str | None:
    """The hash of a file, or None when there is none (absent has to stay absent)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def watched(state: Path) -> dict:
    """config.json, the memory and every file under shared-meta: a hash for each, None for the two files that are not there."""
    state = Path(state)
    out = {name: digest(state / name) for name in WATCHED}
    meta = state / "shared-meta"
    if meta.is_dir():
        for found in sorted(meta.rglob("*")):
            if found.is_file():
                out["shared-meta/" + found.relative_to(meta).as_posix()] = digest(found)
    return out


def stores(state: Path) -> dict:
    return {kind: digest(Path(state) / name) for kind, name in STORES.items()}


def names_in(state: Path) -> list:
    """The names of the files in the state folder (not their contents), without the ones that change by themselves."""
    state = Path(state)
    found = sorted(p.relative_to(state).as_posix() for p in state.rglob("*") if p.is_file())
    return [n for n in found if n not in TRANSIENT and not n.endswith((".tmp", ".lock"))]


def differs(before: dict, after: dict) -> list:
    return [k for k in sorted(set(before) | set(after)) if before.get(k, "<missing>") != after.get(k, "<missing>")]


def walk(value):
    """Every dict inside a JSON value."""
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


def list_problems(builtin: list) -> list[str]:
    """What is wrong with the built-in team templates as listed: a position outside the eight, a launch mode, a routine that is on."""
    out = []
    for item in walk(builtin):
        if "position" in item and item["position"] is not None and item["position"] not in POSITIONS:
            out.append("position")
        if "launch_mode" in item:
            out.append("launch_mode")
        if item.get("enabled") is True:
            out.append("enabled")
    return sorted(set(out))


def card_problems(card: dict, model: str | None) -> list[str]:
    """What is wrong with an employee an apply made: not the safe mode, a skill card, not Claude Code, or not the template's model."""
    out = []
    if card.get("launch_mode") != "safe":
        out.append("launch_mode")
    if card.get("equipped_skill_ids") not in ([], None):
        out.append("equipped_skill_ids")
    shown = card.get("model") if isinstance(card.get("model"), dict) else {}
    if shown.get("tool") != "claude":
        out.append("tool")
    if (shown.get("model_id") or "") != (model or ""):
        out.append("model")
    return out


def counts_of(items: list) -> tuple:
    return tuple(sum(1 for i in items if i.get("kind") == k) for k in ("card", "skill", "routine"))


def secrets_in(text: str, words: list) -> bool:
    return any(w and w in text for w in words)


# ---- the run ------------------------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, console, state: Path, until: str, start: str, check: Check, templates: list, clock=time.monotonic, sleep=time.sleep):
        self.c, self.state, self.until, self.first, self.check = console, Path(state), until, start, check
        self.clock, self.sleep = clock, sleep
        self.started = clock()
        self.memo_path = self.state.parent / "qa45.json"
        self.memo: dict = {}
        self.templates = templates               # the built-in team templates, whole (to know the words that must not be in a record)
        self.sent = 0
        self.ready = False

    # -- the memo: ids, counts and hashes, never a name or a word -----------------------------------------------------------------

    def save(self) -> None:
        self.memo_path.write_text(json.dumps(self.memo, sort_keys=True))

    def load(self) -> None:
        try:
            self.memo = json.loads(self.memo_path.read_text())
        except (OSError, ValueError):
            raise Stop("no qa45.json next to the state folder: start from the stage setup") from None
        if not isinstance(self.memo, dict) or "base" not in self.memo:
            raise Stop("qa45.json is not one of this script's")

    def made(self, kind: str, ident: str) -> None:
        got = self.memo.setdefault("made", {"cards": [], "skills": [], "routines": [], "mine": []})
        if ident and ident not in got[kind]:
            got[kind].append(ident)

    def reached(self, stage: str) -> bool:
        return STAGES.index(self.first) <= STAGES.index(stage) <= STAGES.index(self.until)

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

    def listing(self) -> dict:
        return self.c.ok("/api/templates")

    def cards(self) -> dict:
        return {p["id"]: p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict) and "id" in p}

    def skills(self) -> dict:
        return {s["id"]: s for s in self.c.ok("/api/my-skills").get("skills", []) if isinstance(s, dict) and "id" in s}

    def routines(self) -> dict:
        return {r["id"]: r for r in self.c.ok("/api/routines").get("routines", []) if isinstance(r, dict) and "id" in r}

    def counts(self) -> dict:
        return {"cards": len(self.cards()), "skills": len(self.skills()), "routines": len(self.routines())}

    def chats(self) -> int:
        return len(self.c.ok("/api/chats").get("chats", []))

    def spent(self) -> float | None:
        return money(self.c.ok("/api/meetings/ledger").get("spent_usd"))

    def ticks(self) -> dict:
        return self.c.ok("/api/settings/autonomy").get("autonomy") or {}

    def record_text(self) -> str:
        out = ""
        for name in ("applies.json", "log.jsonl"):
            try:
                out += (self.state / "templates" / name).read_text(errors="replace")
            except OSError:
                pass
        return out

    def own_words(self) -> list:
        """The names and the first words of every text of the four team templates, and the script's own marks."""
        words = ["QA45", OWN_NAME]
        for t in self.templates:
            for kind in ("cards", "skills", "routines"):
                for item in t.get(kind, []):
                    words.append(item.get("name"))
                    for field in ("instructions", "text"):
                        if isinstance(item.get(field), str):
                            words.append(item[field][:12])
        return [w for w in words if isinstance(w, str) and len(w) >= 2]

    def made_by(self, apply: dict) -> dict:
        """kind -> {"template/key": id} of what an apply made."""
        out: dict = {"card": {}, "skill": {}, "routine": {}}
        for item in apply.get("items", []):
            if item.get("state") == "made" and item.get("kind") in out and isinstance(item.get("from"), dict):
                out[item["kind"]][f"{item['from'].get('template')}/{item['from'].get('key')}"] = item.get("id")
        return out

    def apply(self, body: dict) -> dict:
        """Apply, and write down every id that was made even when the apply stopped in the middle (409 ``template_partial`` says what it made)."""
        code, got = self.c.call("/api/templates/apply", "POST", body)
        apply = (got.get("apply") if isinstance(got, dict) else None) or {}
        for item in apply.get("items", []):
            if item.get("state") == "made" and item.get("id"):
                self.made({"card": "cards", "skill": "skills", "routine": "routines"}[item["kind"]], item["id"])
        if code != 201:
            raise Stop(f"POST /api/templates/apply answered {code}" + (f" ({got.get('code')})" if isinstance(got, dict) and got.get("code") else ""))
        return apply

    def undo_plan(self, apply_id: str) -> dict:
        return self.c.ok(f"/api/templates/applies/{apply_id}/undo-preview", "POST", {})

    # -- stages --------------------------------------------------------------------------------------------------------------------

    def start(self) -> None:
        if self.first == "setup":
            self.memo = {}
        else:
            self.load()
        self.ready = True

    def setup(self) -> None:
        listed = self.listing()
        ids = [t.get("id") for t in listed.get("builtin", [])]
        self.check.expect(ids == BUILTIN, "the built-in team templates are shop, creator, studio and life", f"{len(ids)} listed")
        self.check.expect(listed.get("mine") == [] and listed.get("applies") == [] and listed.get("mine_readable") is True and listed.get("problems") == [],
                          "none of the person's own, no apply yet, nothing unreadable")
        ticks = self.ticks()
        self.check.expect(len(ticks) == 4 and all(v is False for v in ticks.values()), "the four 自己動手 ticks are false", f"{len(ticks)} ticks")
        base = {"counts": self.counts(), "stores": stores(self.state), "watched": watched(self.state), "spent": self.spent(), "chats": self.chats()}
        self.memo = {"base": base, "made": {"cards": [], "skills": [], "routines": [], "mine": []}, "turns": 0}
        self.check.ok("noted: counts, hashes and bytes", f"{base['counts']['cards']} cards, {base['counts']['skills']} skills, {base['counts']['routines']} routines")

    def browse(self) -> None:
        builtin = self.listing().get("builtin", [])
        bad = list_problems(builtin)
        self.check.expect(not bad, "every position is one of the eight or none; no launch mode; no routine is on", ",".join(bad))

    def preview(self) -> None:
        before_stores, before_names = stores(self.state), names_in(self.state)
        got = self.c.ok("/api/templates/preview", "POST", body_of())
        plan = got.get("preview") or {}
        sizes = (len(plan.get("cards", [])), len(plan.get("skills", [])), len(plan.get("routines", [])))
        self.check.expect(sizes == (4, 4, 2), "the preview is 4 employees, 4 skills and 2 routines", str(sizes))
        self.check.expect(plan.get("ok") is True and plan.get("problems") == [], "the preview has no problem", f"{len(plan.get('problems') or [])} problems")
        self.check.expect(stores(self.state) == before_stores and names_in(self.state) == before_names,
                          "the preview wrote nothing (the three hashes and the names of the files are the same)")

    def apply_stage(self) -> None:
        base = self.memo["base"]
        spent0, chats0 = self.spent(), self.chats()
        before = self.counts()
        apply = self.apply(body_of())
        self.memo["apply1"] = {"id": apply.get("id"), "made": self.made_by(apply)}
        made = self.memo["apply1"]["made"]
        self.check.expect(apply.get("state") == "done" and apply.get("tool") == "claude" and counts_of(apply.get("items", [])) == (4, 4, 2), "the apply is 201 and done with Claude Code",
                          str(counts_of(apply.get("items", []))))
        by_key = {t["id"]: t for t in self.templates}
        cards = self.cards()
        wrong = []
        for pair in CARDS:
            pid = made["card"].get("/".join(pair))
            template = next((c for c in by_key.get(pair[0], {}).get("cards", []) if c.get("key") == pair[1]), {})
            wrong += card_problems(cards.get(pid, {}), template.get("claude_model")) if pid in cards else ["missing"]
        self.check.expect(not wrong, "4 new employees: safe mode, no skill card, Claude Code, the template's model", ",".join(sorted(set(wrong))))
        skills = self.skills()
        typed = all((skills.get(i) or {}).get("source", {}).get("how") == "typed" for i in made["skill"].values())
        self.check.expect(len(made["skill"]) == 4 and typed, "4 new skills, each how: typed")
        routines = self.routines()
        off = all((routines.get(i) or {}).get("enabled") is False for i in made["routine"].values())
        self.check.expect(len(made["routine"]) == 2 and off, "2 new routines, both off")
        after = self.counts()
        self.check.expect(after == {"cards": before["cards"] + 4, "skills": before["skills"] + 4, "routines": before["routines"] + 2}, "the counts went up by 4, 4 and 2", str(after))
        moved = differs(base["watched"], watched(self.state))
        self.check.expect(not moved, "config.json, the memory and the shared folder are the same bytes", f"{len(moved)} differ")
        spent1 = self.spent()
        self.check.expect(self.chats() == chats0 and spent0 is not None and spent1 == spent0, "no chat was opened and the day's spending did not move (an apply uses no AI)",
                          f"US${spent1}")

    def chat(self) -> None:
        made = self.memo["apply1"]["made"]
        pid = made["card"].get("/".join(SERVICE))
        card = self.cards().get(pid, {})
        model = (card.get("model") or {}).get("model_id")
        if model != "haiku":
            self.check.fail("the employee 客服 has the model haiku (nothing is sent otherwise)", f"model {model!r}")
            return
        self.check.ok("the employee 客服 has the model haiku")
        spent0 = self.spent()
        chat = self.c.ok("/api/chats", "POST", {"profile_id": pid})["chat"]["id"]
        self.memo["chat"] = chat
        self.save()
        code, sent = self.c.call(f"/api/chats/{chat}/messages", "POST", {"text": ASK})
        if code not in (200, 201, 202) or not isinstance(sent, dict):
            raise Stop(f"the message was refused ({sent.get('code') if isinstance(sent, dict) else code})")
        self.sent += 1
        self.memo["turns"] = self.memo.get("turns", 0) + 1
        turn, seen = sent.get("turn"), set()

        def ended():
            live = self.c.ok(f"/api/chats/{chat}?after={PAST_THE_END}").get("live")
            for c in (live.get("cards") if isinstance(live, dict) else None) or []:
                if isinstance(c, dict) and c.get("card_id") not in seen:
                    seen.add(c.get("card_id"))
                    self.c.ok(f"/api/chats/{chat}/answer", "POST", {"card_id": c.get("card_id"), "token": c.get("token"), "decision": "deny"})
            after, recs = 0, []
            for _ in range(50):
                page = self.c.ok(f"/api/chats/{chat}?after={after}")
                recs += [r for r in page.get("records", []) if isinstance(r, dict)]
                if not page.get("more"):
                    break
                after = page.get("next_after", after)
            return next((r for r in recs if r.get("kind") == "turn_ended" and r.get("turn") == turn), None)
        end = self.wait("the end of the turn", ended)
        self.check.expect(end.get("reason") == "result", "the turn ended with a result", f"reason {end.get('reason')}, {len(seen)} cards refused")
        spent1 = self.spent()
        self.check.ok("what the turn cost", f"US${None if spent1 is None or spent0 is None else round(spent1 - spent0, 4)}")

    def change(self) -> None:
        made = self.memo["apply1"]["made"]
        sid, rid = made["skill"].get("/".join(PRODUCT)), made["routine"].get("/".join(PROMO))
        skill, routine = self.skills().get(sid), self.routines().get(rid)
        if not skill or not routine:
            raise Stop("the skill or the routine that the apply made is not there")
        self.c.ok(f"/api/my-skills/{sid}", "POST", {"name": skill["name"], "text": skill["text"] + CHANGE_TAIL})
        self.c.ok(f"/api/routines/{rid}", "POST", {"text": routine["text"] + CHANGE_TAIL})
        self.check.expect(self.routines().get(rid, {}).get("enabled") is False, "a skill and a routine were changed; the routine is still off")

    def undo_preview(self) -> None:
        apply1 = self.memo["apply1"]
        made = apply1["made"]
        before = stores(self.state)
        plan = self.undo_plan(apply1["id"])
        keep = {k.get("id"): k.get("why") for k in plan.get("keep", [])}
        delete = [d.get("id") for d in plan.get("delete", [])]
        want_keep = {made["card"].get("/".join(SERVICE)): "chatted", made["skill"].get("/".join(PRODUCT)): "changed", made["routine"].get("/".join(PROMO)): "changed",
                     made["card"].get("/".join(COPY)): "routine_kept"}
        want_delete = {made["card"].get("/".join(ACCOUNTING)), made["card"].get("/".join(WRITER)), made["routine"].get("/".join(SPEND))}
        want_delete |= {v for k, v in made["skill"].items() if k != "/".join(PRODUCT)}
        self.check.expect(keep == want_keep, "kept: the employee talked to (chatted), the changed skill and routine, and the employee a kept routine goes to", f"{len(keep)} kept")
        self.check.expect(set(delete) == want_delete and len(delete) == len(want_delete), "deleted: 會計, 寫稿, the other 3 skills and the routine not changed", f"{len(delete)} to delete")
        self.check.expect(stores(self.state) == before, "the preview of the undo wrote nothing")
        self.memo["undo"] = {"delete": sorted(i for i in delete if i), "keep": keep}

    def undo(self) -> None:
        apply1, plan = self.memo["apply1"], self.memo["undo"]
        done = self.c.ok(f"/api/templates/applies/{apply1['id']}/undo", "POST", {"delete": plan["delete"]})
        deleted = sorted(d.get("id") for d in done.get("deleted", []))
        kept = {k.get("id"): k.get("why") for k in done.get("kept", [])}
        self.check.expect(deleted == plan["delete"] and kept == plan["keep"], "what was deleted and what was kept are what the preview said",
                          f"{len(deleted)} deleted, {len(kept)} kept")
        cards, skills, routines = self.cards(), self.skills(), self.routines()
        there = set(cards) | set(skills) | set(routines)
        self.check.expect(not (set(plan["delete"]) & there) and set(plan["keep"]) <= there, "the deleted ones are gone and the kept ones are still there")
        again = self.undo_plan(apply1["id"])
        self.check.expect(again.get("delete") == [], "asked again, there is nothing more to delete", f"{len(again.get('delete', []))} left")

    def mine(self) -> None:
        made = self.memo["apply1"]["made"]
        pid = made["card"].get("/".join(SERVICE))
        got = self.c.ok("/api/templates/mine", "POST", {"name": OWN_NAME, "cards": [{"profile_id": pid}], "skills": [tick(STUDY)]}, status=(201,))
        template = got.get("template") or {}
        tid = template.get("id")
        if isinstance(tid, str):
            self.memo["mine"] = tid
            self.made("mine", tid)
        listed = next((t for t in self.listing().get("mine", []) if t.get("id") == tid), None)
        self.check.expect(listed is not None, "the person's own team template is listed", "201")
        keys = sorted((listed or {}).get("cards", [{}])[0].keys()) if (listed or {}).get("cards") else None
        self.check.expect(keys == MINE_KEYS, "its employee has only key, name, position, instructions and claude_model", str(keys))

    def reapply(self) -> None:
        tid = self.memo.get("mine")
        template = next((t for t in self.listing().get("mine", []) if t.get("id") == tid), None)
        if not template:
            raise Stop("the person's own team template is not there")
        body = {"tool": "claude", "cards": [tick((tid, c["key"])) for c in template["cards"]], "skills": [tick((tid, s["key"])) for s in template["skills"]],
                "routines": [tick((tid, r["key"])) for r in template["routines"]]}
        apply = self.apply(body)
        self.memo["apply2"] = apply.get("id")
        self.check.expect(counts_of(apply.get("items", [])) == (1, 1, 0), "that team template made 1 employee and 1 skill", str(counts_of(apply.get("items", []))))
        plan = self.undo_plan(apply["id"])
        ids = [d.get("id") for d in plan.get("delete", [])]
        done = self.c.ok(f"/api/templates/applies/{apply['id']}/undo", "POST", {"delete": ids})
        self.check.expect(len(plan.get("delete", [])) == 2 and plan.get("keep") == [] and len(done.get("deleted", [])) == 2 and done.get("kept") == [],
                          "undone at once, both are deleted and nothing is kept", f"{len(done.get('deleted', []))} deleted")

    def final(self) -> None:
        if "base" not in self.memo:
            raise Stop("setup did not finish, so there is nothing to compare with")
        base = self.memo["base"]
        got = self.memo.get("made", {})
        for tid in got.get("mine", []):
            self.c.call(f"/api/templates/mine/{tid}/delete", "POST", {})
        for path, ids in (("/api/routines/{}/delete", got.get("routines", [])), ("/api/my-skills/{}/delete", got.get("skills", [])),
                          ("/api/agent-profiles/{}/delete", got.get("cards", []))):
            for ident in ids:
                self.c.call(path.format(ident), "POST", {})                      # 404 for what the undo already deleted
        self.check.ok("what this script made is deleted with the ordinary routes", f"{len(got.get('cards', []))} employees, {len(got.get('skills', []))} skills, {len(got.get('routines', []))} routines made in all")
        after = self.counts()
        self.check.expect(after == base["counts"], "the counts of employees, skills and routines are what setup noted", str(after))
        moved = differs(base["watched"], watched(self.state))
        self.check.expect(not moved, "config.json, the memory and the shared folder are the same bytes as at the start", f"{len(moved)} differ")
        ticks = self.ticks()
        self.check.expect(len(ticks) == 4 and all(v is False for v in ticks.values()), "the four 自己動手 ticks are false")
        self.check.expect(not any(r.get("enabled") is True for r in self.routines().values()), "no routine is on")
        self.check.expect(not secrets_in(self.record_text(), self.own_words()), "applies.json and log.jsonl hold no name or word of the script's or of the team templates")
        self.check.expect(self.listing().get("mine") == [], "the script's own team template is gone")
        spent, turns = self.spent(), self.memo.get("turns", 0)
        self.check.expect(spent is not None and spent <= SPEND_CEILING_USD, "the day's spending is within the allowance",
                          f"US${spent} by VBear's own counting; {turns} turn(s)")


def main(argv=None, out=print, console_factory=Console, clock=time.monotonic, sleep=time.sleep, home: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="v0.19.0 real check of the team templates (see the file's docstring)")
    ap.add_argument("--state", required=True, help="the temporary state folder of the console (VBEAR_HOME)")
    ap.add_argument("--port", type=int, default=7800, help="the console's port (never 7788 or 7789)")
    ap.add_argument("--from", dest="first", choices=STAGES, default=STAGES[0], help="the first stage to run (after setup it needs qa45.json)")
    ap.add_argument("--until", choices=STAGES, default=STAGES[-1], help="the last stage to run")
    args = ap.parse_args(argv)
    why = refusal(args.state, args.port, home)
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
        listed = console.ok("/api/templates")
        run = Run(console, state, args.until, args.first, check, listed.get("builtin") or [], clock=clock, sleep=sleep)
        run.start()
        for stage in STAGES[:-1]:
            if run.reached(stage):
                getattr(run, stage.replace("-", "_") + ("_stage" if stage == "apply" else ""))()
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
    out(f"qa_p45: {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
