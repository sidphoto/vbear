#!/usr/bin/env python3
"""v0.15.0 real check of the chief of staff and the dispatch (P40): the coordinator's run before the release, through the
console's HTTP API only.

It is a developer check, never part of the product. It calls the endpoints of this release (/api/chief*, /api/dispatch*,
/api/actions, /api/settings/autonomy) and, to bring the day's limit down and back, /api/setup/daily-limit and /api/config. It
runs no AI tool itself: the console it talks to does (a real Claude Code, one call for the chief of staff and one chat turn per
step), which is the point of the check and is why it needs a state folder of its own.

    python3 tools/qa_p40.py --state "$T/s" --port 7795                    # everything below
    python3 tools/qa_p40.py --state "$T/s" --port 7795 --until preview    # the dialog's numbers only: asks no model
    python3 tools/qa_p40.py --state "$T/s" --port 7795 --until propose    # + the chief of staff's one call (about US$0.03-0.10)
    python3 tools/qa_p40.py --state "$T/s" --port 7795 --until confirm    # + confirm, the daily-limit pause, continue
    python3 tools/qa_p40.py --state "$T/s" --port 7795 --until auto       # + both 「自己動手」 items on, one more proposal, take-back

What it needs: a console started by the coordinator on a temporary state folder (``VBEAR_HOME=<state>``, a short path) on a port
that is not 7788 or 7789, with ``config.json`` holding ``meeting_limits.daily_usd`` (0.45), ``chat_limits.per_turn_usd`` (0.10)
and ``setup_done``; a CEO role card (Claude Code, planner) and a chat with it that already holds the person's sentence and the
CEO's reply (plan.md, real-check steps 1 to 4). ``--chat`` names the chat; without it the newest chat of a CEO card is used.

What it never does: touch ``~/.vbear`` or the ports 7788 and 7789 (it refuses both), print a login code, an e-mail address, a
conversation, a prompt or the words a model wrote (only counts, states, codes and yes/no), merge, push or tag. The access token
is read from ``<state>/server.token``, the file that console wrote for itself.

The stages (each prints ``ok``, ``warn`` or ``FAIL`` lines and the script exits 1 on a FAIL):

  preview   the dialog's numbers: messages, cards, the cap, what is left today; nothing is asked of a model.
  propose   POST /api/chief from that preview, wait for the proposal; it must be valid, have 1 to 4 steps, name only Claude Code
            for a new employee, and its call must have reported no tool but StructuredOutput and no MCP (read from the proposal's
            record in the state folder).
  confirm   change the plan (two steps, the new employee on haiku, each step "用三行回答：…"), confirm, and as soon as step 1 is
            sent bring the daily limit down to US$0.01: step 1 finishes, step 2 must not be sent, the dispatch must pause with
            ``daily_limit`` and say 「明天 0:00」; then the limit and the chat's per-turn limit go back to what they were, 「繼續」
            sends step 2, which must carry step 1's reply as data and be marked in the chat record as the dispatch's.
  auto      tick both 「自己動手」 items, ask again (one more step), the proposal must start by itself and the list must say 「自己動手
            第 1 項」 and 「第 2 項」; take back the new employee (the card is switched off); untick both items.
  final     config.json changed only in the limits and the ticks this script wrote (compared key by key), every employee a dispatch
            made is in safe mode with no skill, and what the day's ledger says was spent.

Caps: 20 minutes for the whole run, 3 minutes for any one wait. Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_PORTS = (7788, 7789)
STAGES = ("preview", "propose", "confirm", "auto")
WALL_CAP_S = 20 * 60
WAIT_CAP_S = 3 * 60
LOW_DAILY_USD = 0.01
OWN_KEYS = {"meeting_limits", "chat_limits", "staffing_limits", "autonomy"}       # the config keys this script writes itself
SPEND_CEILING_USD = 0.47                                                        # US$0.50, less the check of the tool-less boundary


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

    def ok(self, path: str, method: str = "GET", body=None, status=(200, 202)):
        code, data = self.call(path, method, body)
        if code not in status:
            msg = data.get("error") if isinstance(data, dict) else None
            raise Stop(f"{method} {path.split('?')[0]} answered {code}" + (f": {msg}" if msg else ""))
        return data


# ---- pure helpers (tested) --------------------------------------------------------------------------------------------------

def refusal(state: str, port: int, home: Path | None = None) -> str | None:
    """Why this run must not start, or None. The person's own VBear (its folder, ports 7788 and 7789) is never the target."""
    if port in FORBIDDEN_PORTS:
        return f"port {port} is the person's own VBear"
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        return "the port must be 1024 to 65535"
    state_path = Path(state).expanduser().resolve()
    home_dir = (home or Path.home()).resolve()
    if state_path == (home_dir / ".vbear").resolve():
        return "that is the person's own VBear folder; give a temporary one"
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


def plan_body(view: dict, *, steps: int = 2, prefix: str = "用三行回答：", alias: str = "haiku") -> dict:
    """The confirmation body for a proposal card, changed the way the real check says: at most ``steps`` steps, each text with a
    short instruction in front, a new employee of Claude Code on ``alias``. Only the fields the server takes."""
    plan = view["plan"]
    kept = plan["steps"][:steps]
    used = {s["who"] for s in kept}
    cards = []
    for c in plan["new_cards"]:
        if c["ref"] not in used:
            continue
        cards.append({"ref": c["ref"], "name": c["name"], "position": c["position"], "tool": c["tool"],
                      "model_alias": alias if c["tool"] == "claude" else ""})
    return {"proposal_sha": view["proposal_sha"], "title": plan["title"], "goal": plan["goal"], "new_cards": cards,
            "steps": [{"who": s["who"], "text": (prefix + s["text"])[:1500]} for s in kept]}


def config_problems(before: dict, after: dict, own: set = OWN_KEYS) -> list[str]:
    """The keys of config.json that changed other than the ones this script writes itself."""
    out = []
    for key in sorted(set(before) | set(after)):
        if key in own:
            continue
        if before.get(key, "<missing>") != after.get(key, "<missing>"):
            out.append(key)
    return out


def card_problems(profile: dict) -> list[str]:
    out = []
    if profile.get("launch_mode") != "safe":
        out.append("launch_mode")
    if profile.get("equipped_skill_ids") not in ([], None):
        out.append("equipped_skill_ids")
    return out


# ---- the run ------------------------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, console: Console, state: Path, chat: str | None, until: str, check: Check, clock=time.monotonic, sleep=time.sleep):
        self.c, self.state, self.chat, self.until, self.check = console, Path(state), chat, until, check
        self.clock, self.sleep = clock, sleep
        self.started = clock()
        self.made: list[str] = []          # profile ids of employees a dispatch made
        self.dispatches: list[str] = []

    def reached(self, stage: str) -> bool:
        return STAGES.index(stage) <= STAGES.index(self.until)

    def wait(self, what: str, probe, cap: float = WAIT_CAP_S, every: float = 2.0):
        end = self.clock() + cap
        while True:
            got = probe()
            if got:
                return got
            if self.clock() > end or self.clock() - self.started > WALL_CAP_S:
                raise Stop(f"timed out waiting for {what}")
            self.sleep(every)

    def config_file(self) -> dict:
        try:
            data = json.loads((self.state / "config.json").read_text())
        except (OSError, ValueError):
            raise Stop("config.json cannot be read in the state folder") from None
        return data if isinstance(data, dict) else {}

    def find_chat(self) -> str:
        if self.chat:
            return self.chat
        data = self.c.ok("/api/chats")
        cards = {c.get("id"): c for c in data.get("cards", []) if isinstance(c, dict)}
        rows = [r for r in data.get("chats", []) if isinstance(r, dict) and cards.get(r.get("profile_id"), {}).get("position") == "planner"]
        rows.sort(key=lambda r: r.get("last_at") or r.get("created_at") or 0, reverse=True)
        if not rows:
            raise Stop("no chat of a CEO card found; create it first (real-check step 4) or give --chat")
        return rows[0]["id"]

    # -- stages ------------------------------------------------------------------------------------------------------------

    def preview(self, chat: str) -> dict:
        pv = self.c.ok(f"/api/chief/preview?chat_id={chat}")
        self.check.expect(pv.get("ok") is True and isinstance(pv.get("preview_id"), str), "the preview is startable",
                          ",".join(b.get("code", "?") for b in pv.get("blockers", []) if isinstance(b, dict)))
        self.check.expect(pv.get("sends_to") == "Claude Code", "it says where the conversation goes", str(pv.get("sends_to")))
        cap, left = money(pv.get("cap_usd")), money(pv.get("day_left_usd"))
        self.check.expect(cap is not None and left is not None and cap <= 0.30 + 1e-9, "the most it costs and what is left today are numbers",
                          f"cap US${cap}, left US${left}, {pv.get('messages')} messages, {pv.get('cards')} employees")
        self.check.expect(isinstance(pv.get("messages"), int) and pv["messages"] >= 1, "it reads at least one message")
        if pv.get("ok") is not True:
            raise Stop("the preview cannot start")
        return pv

    def propose(self, pv: dict, note: str | None) -> tuple[str, dict]:
        body = {"preview_id": pv["preview_id"]}
        if note:
            body["note"] = note
        started = self.c.ok("/api/chief", "POST", body)
        cid = started["chief_id"]

        def done():
            v = self.c.ok(f"/api/chief/{cid}")
            return v if v.get("status") != "running" else None
        view = self.wait("the chief of staff", done)
        self.check.expect(view.get("status") == "ready", "the chief of staff's proposal is ready", f"status {view.get('status')}, code {view.get('error_code')}")
        spent = money(view.get("spent_usd"))
        self.check.ok("what the chief of staff cost", f"US${spent} ({view.get('cost_source')})")
        if view.get("status") != "ready":
            raise Stop("no proposal")
        self.check.expect(isinstance(view.get("dispatch_id"), str), "the proposal became a dispatch")
        evidence = self.chief_evidence(cid)
        if evidence is not None:
            self.check.expect(evidence.get("tools_reported") == ["StructuredOutput"] and evidence.get("mcp_servers_reported") == [],
                              "the call reported only StructuredOutput and no MCP", f"{evidence.get('tools_reported')}")
        else:
            self.check.warn("the call's init event could not be read from the record")
        did = view["dispatch_id"]
        self.dispatches.append(did)
        dv = self.c.ok(f"/api/dispatch/{did}")
        steps = dv["plan"]["steps"]
        self.check.expect(1 <= len(steps) <= 4 or bool(dv.get("questions")), "1 to 4 steps (or only questions)", f"{len(steps)} steps, {len(dv.get('questions', []))} questions, {len(dv.get('notes', []))} notes")
        self.check.expect(all(c["tool"] == "claude" for c in dv["plan"]["new_cards"]), "a new employee is of Claude Code only", ",".join(c["tool"] for c in dv["plan"]["new_cards"]) or "no new employee")
        self.check.expect(all(0 < len(s["text"]) <= 1500 for s in steps), "every step has words to send, 1500 characters at most")
        self.check.expect(dv["cost"]["max_usd"] is not None, "the proposal card can say the most it costs", f"US${dv['cost']['max_usd']} of US${dv['cost']['day_left_usd']} left")
        return cid, dv

    def chief_evidence(self, cid: str) -> dict | None:
        try:
            rec = json.loads((self.state / "chief" / f"{cid}.json").read_text())
            return rec["turns"][0]["evidence"]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return None

    def confirm_and_pause(self, dv: dict) -> str:
        did = dv["id"]
        if len(dv["plan"]["steps"]) < 2:
            raise Stop("the proposal has fewer than 2 steps, so the pause between two steps cannot be shown; ask again")
        before = self.config_file()
        daily0 = money((before.get("meeting_limits") or {}).get("daily_usd"))
        per0 = money((before.get("chat_limits") or {}).get("per_turn_usd"))
        if daily0 is None or per0 is None:
            raise Stop("config.json lacks meeting_limits.daily_usd or chat_limits.per_turn_usd (real-check step 2)")
        lamp = self.c.ok("/api/meetings/ledger").get("lamp")
        if lamp == "red":
            raise Stop("the day's lamp is red already")
        body = plan_body(dv, steps=2)
        confirmed = self.c.ok(f"/api/dispatch/{did}/confirm", "POST", body)
        self.check.expect(confirmed.get("state") == "running" and confirmed.get("started_by") == "you" and confirmed.get("edited") is True,
                          "confirmed: running, by you, marked as edited", f"{confirmed.get('state')}/{confirmed.get('started_by')}")
        self.made += [m["profile_id"] for m in confirmed.get("created_cards", [])]
        first = self.wait("step 1 to be sent", lambda: next((s for s in self.c.ok(f"/api/dispatch/{did}")["steps"] if s["seq"] == 1 and s["state"] in ("running", "ended")), None), cap=90, every=0.5)
        low = self.c.ok("/api/setup/daily-limit", "POST", {"daily_usd": LOW_DAILY_USD})
        self.check.expect(low.get("ok") is True, f"the daily limit is US${LOW_DAILY_USD} after step 1 was sent", f"chat per-turn limit brought down: {any(c.get('limit') == 'chat_per_turn_usd' for c in low.get('changed', []))}")
        paused = self.wait("the dispatch to pause", lambda: (lambda v: v if v["state"] in ("paused", "done", "stopped") else None)(self.c.ok(f"/api/dispatch/{did}")), cap=WAIT_CAP_S, every=2.0)
        self.check.expect(paused["state"] == "paused" and (paused.get("pause") or {}).get("reason") == "daily_limit", "the dispatch paused at the daily limit",
                          f"{paused['state']}/{(paused.get('pause') or {}).get('reason')}")
        self.check.expect("明天 0:00" in ((paused.get("pause") or {}).get("text") or ""), "the pause says when the day starts again")
        s1, s2 = paused["steps"][0], paused["steps"][1]
        self.check.expect(s1["state"] == "ended" and s1["ended_reason"] == "result", "step 1 finished", f"{s1['state']}/{s1['ended_reason']}")
        self.check.expect(s2["state"] == "pending" and s2["chat_id"] is None, "step 2 was not sent")
        self.check.expect(paused["can"]["continue"] is True, "the dispatch can be continued by the person")
        # back to what it was: the day first, then the chat's per-turn limit that coming down took with it
        self.c.ok("/api/setup/daily-limit", "POST", {"daily_usd": daily0})
        self.c.ok("/api/config", "POST", {"chat_limits": {"per_turn_usd": per0}})
        cont = self.c.ok(f"/api/dispatch/{did}/continue", "POST", {})
        self.check.expect(cont.get("state") == "running", "continue: running again")
        done = self.wait("the dispatch to finish", lambda: (lambda v: v if v["state"] in ("done", "paused", "stopped") else None)(self.c.ok(f"/api/dispatch/{did}")), cap=WAIT_CAP_S, every=2.0)
        self.check.expect(done["state"] == "done", "the dispatch is done", done["state"] + (f"/{(done.get('pause') or {}).get('reason')}" if done.get("pause") else ""))
        self.check_handoff(done, first)
        return did

    def user_message(self, chat_id: str) -> dict | None:
        after = 0
        for _ in range(20):
            page = self.c.ok(f"/api/chats/{chat_id}?after={after}")
            for r in page.get("records", []):
                if isinstance(r, dict) and r.get("kind") == "user_message":
                    return r
            if not page.get("more"):
                return None
            after = page.get("next_after", after)
        return None

    def reply_of(self, chat_id: str) -> str:
        after, last = 0, ""
        for _ in range(20):
            page = self.c.ok(f"/api/chats/{chat_id}?after={after}")
            for r in page.get("records", []):
                if isinstance(r, dict) and r.get("kind") == "reply" and isinstance(r.get("text"), str):
                    last = r["text"]
            if not page.get("more"):
                break
            after = page.get("next_after", after)
        return last

    def check_handoff(self, done: dict, first: dict) -> None:
        if len(done["steps"]) < 2 or not done["steps"][1].get("chat_id"):
            self.check.fail("step 2 has a chat")
            return
        message = self.user_message(done["steps"][1]["chat_id"])
        if message is None:
            self.check.fail("step 2's chat has the message sent")
            return
        self.check.expect(message.get("origin") == {"dispatch": done["id"], "step": 2}, "step 2's message is marked as the dispatch's in the chat record")
        text = message.get("text") or ""
        reply = self.reply_of(done["steps"][0]["chat_id"])
        probe = reply.strip()[:40]
        self.check.expect(bool(probe) and probe in text, "step 2 carries step 1's reply", "found" if probe and probe in text else "not found")
        self.check.expect("BEGIN_UNTRUSTED" in text and "資料" in text, "and marks it as data, not as an instruction")
        self.check.expect(text.startswith((done["plan"]["steps"][1]["text"])[:20]), "and begins with the words of the plan")

    def auto_stage(self, chat: str) -> None:
        self.c.ok("/api/settings/autonomy", "POST", {"create_cards": True, "dispatch": True})
        try:
            pv = self.c.ok(f"/api/chief/preview?chat_id={chat}")
            if pv.get("ok") is not True:
                raise Stop("the second preview cannot start")
            self.check.ok("the second preview", f"cap US${pv.get('cap_usd')}")
            _, dv = self.propose(pv, "再請一位員工把清單翻成英文，一步就好")
            if dv["state"] == "proposed" and (dv.get("notes") or dv.get("questions")):
                self.check.warn("the proposal had notes or questions, so 「自己動手」 item 2 correctly did not start it", f"{len(dv.get('notes', []))} notes, {len(dv.get('questions', []))} questions")
                return
            self.check.expect(dv["started_by"] == "auto2" and dv["state"] in ("running", "done"), "the proposal started by itself (自己動手第 2 項)", f"{dv['state']}/{dv['started_by']}")
            self.made += [m["profile_id"] for m in dv.get("created_cards", [])]
            rows = self.c.ok("/api/actions")["actions"]
            mine = [r for r in rows if r["dispatch_id"] == dv["id"]]
            if dv["plan"]["new_cards"]:
                self.check.expect(any(r["kind"] == "card_created" and r["by"] == "auto1" and r["by_text"] == "自己動手第 1 項" for r in mine), "the list says 自己動手第 1 項 for the new employee")
            self.check.expect(any(r["kind"] in ("confirmed", "step_intent") and r["by"] == "auto2" and r["by_text"] == "自己動手第 2 項" for r in mine), "the list says 自己動手第 2 項 for the start")
            fin = self.wait("the second dispatch to finish", lambda: (lambda v: v if v["state"] in ("done", "paused", "stopped") else None)(self.c.ok(f"/api/dispatch/{dv['id']}")), cap=WAIT_CAP_S, every=2.0)
            self.check.expect(fin["state"] == "done", "the second dispatch is done", fin["state"])
            for m in fin.get("created_cards", []):
                if m["profile_id"] not in self.made:
                    self.made.append(m["profile_id"])
                if m.get("withdrawn") or m["profile_id"] not in fin["can"]["withdraw"]:
                    continue
                self.c.ok(f"/api/dispatch/{dv['id']}/withdraw-card", "POST", {"profile_id": m["profile_id"]})
                profile = next((p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if p.get("id") == m["profile_id"]), None)
                self.check.expect(profile is not None and profile.get("enabled") is False, "taking the new employee back switched the card off, did not delete it")
        finally:
            self.c.ok("/api/settings/autonomy", "POST", {"create_cards": False, "dispatch": False})
            self.check.ok("both 「自己動手」 items are off again")

    def final(self, before: dict) -> None:
        after = self.config_file()
        bad = config_problems(before, after)
        self.check.expect(not bad, "config.json changed only in the limits and the ticks this script wrote", ",".join(bad))
        self.check.expect((after.get("autonomy") or {}) in ({}, {"create_cards": False, "dispatch": False}), "and both ticks are off")
        profiles = {p.get("id"): p for p in self.c.ok("/api/agent-profiles").get("profiles", []) if isinstance(p, dict)}
        for pid in self.made:
            p = profiles.get(pid)
            if p is None:
                self.check.fail("an employee a dispatch made can be read", "missing")
                continue
            self.check.expect(not card_problems(p), "an employee a dispatch made is in safe mode with no skill", ",".join(card_problems(p)))
        ledger = self.c.ok("/api/meetings/ledger")
        spent = money(ledger.get("spent_usd"))
        self.check.expect(spent is not None and spent <= SPEND_CEILING_USD, "what the day's ledger counts is within the allowance",
                          f"US${spent} (VBear's own counting; the daily limit is the hard cap)")


def main(argv=None, out=print, console_factory=Console, clock=time.monotonic, sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description="v0.15.0 real check of the chief of staff and the dispatch (see the file's docstring)")
    ap.add_argument("--state", required=True, help="the temporary state folder of the console (VBEAR_HOME)")
    ap.add_argument("--port", type=int, default=7795, help="the console's port (never 7788 or 7789)")
    ap.add_argument("--chat", default=None, help="the CEO chat's id (default: the newest chat of a CEO card)")
    ap.add_argument("--until", choices=STAGES, default="auto", help="the last stage to run")
    args = ap.parse_args(argv)
    why = refusal(args.state, args.port)
    if why:
        out(f"refused: {why}")
        return 2
    check = Check(out)
    try:
        state = Path(args.state).expanduser().resolve()
        console = console_factory(args.port, read_token(state, args.port))
        run = Run(console, state, args.chat, args.until, check, clock=clock, sleep=sleep)
        before = run.config_file()
        chat = run.find_chat()
        pv = run.preview(chat)
        if run.reached("propose"):
            _, dv = run.propose(pv, None)
            if run.reached("confirm"):
                run.confirm_and_pause(dv)
                if run.reached("auto"):
                    run.auto_stage(chat)
                run.final(before)
            else:
                out("stopped after the proposal: it is left waiting on its card, nothing was confirmed")
    except Stop as exc:
        check.fail("stopped", str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check.fail("unexpected", f"{type(exc).__name__}: {str(exc)[:120]}")
    out(f"qa_p40: {'PASS' if not check.failed else 'FAIL'} ({check.passed} ok, {check.warned} warn, {check.failed} FAIL)")
    return 0 if not check.failed else 1


if __name__ == "__main__":
    sys.exit(main())
