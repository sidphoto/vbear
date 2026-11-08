"""P44-6: tools/qa_p44.py, the coordinator's real-machine check of skills and routines, must refuse to run without a state folder and two
cards, never aim at the person's VBear (its folder, anything under it, ports 7788 and 7789), never run in the hour around midnight, print
none of what a model wrote, no name or word of what it made, and not the access token, pass over a console that behaves, and FAIL over one
that does not (a skill with a key that is saved; a suggestion over its cap or one that saves by itself; a reminder that opens a chat; a time
that starts twice; a caffeinate that is not there while a card waits or that stays; a missed time that is caught up with item 3 off; a group
that goes on by itself; a key added to config.json; a name in a log; too much spent).
Nothing here starts a console, a model or ``caffeinate``: the console is an in-memory world over a real temporary state folder, the clock is
a hand-moved one (a Monday noon in Taipei) that ``sleep`` moves, and ``pmset`` and ``ps`` are answered by a function.

Seams: ``qa_p44.main`` (the command line, with a fake console, clock, sleep and command runner), ``refusal``, ``time_refusal``,
``pick_cards``, ``config_problems``, ``card_problems``, ``caffeinate_pids``, ``child_of_console``, ``due_time`` and ``tomorrow_midnight``."""
import contextlib
import datetime
import importlib.util
import io
import json
import re
import tempfile
import types
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

SPEC = importlib.util.spec_from_file_location("qa_p44", Path(__file__).resolve().parent.parent / "tools" / "qa_p44.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

TAIPEI = ZoneInfo("Asia/Taipei")
PORT = 50144
TOKEN = "synthetic-token-never-printed"
W, A = "emp-writer", "emp-account"
MODEL_WORDS = "MODEL-WORDS-never-printed"
CONSOLE_PID = 9001
CHAT_RE = re.compile(r"^/api/chats/(c-[0-9a-f]{16})(/messages|/answer)?$")
GROUP_RE = re.compile(r"^/api/groups/(g-[0-9a-f]{12})(/messages|/drop|/stop)?$")


def at(hour, minute, day=9):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=TAIPEI).timestamp()


class World:
    """A console in memory over a real temporary state folder. ``flaws`` are the ways it misbehaves."""

    def __init__(self, state: Path, start: float, **flaws):
        self.state, self.flaws, self.now = Path(state).resolve(), flaws, [start]
        (self.state / "server.token").write_text(json.dumps({"port": PORT, "token": TOKEN}))
        self.config = {"setup_done": True, "meeting_limits": {"per_call_usd": 0.05, "meeting_usd": 0.25, "daily_usd": 0.25},
                       "staffing_limits": {"proposal_call_usd": 0.1, "total_usd": 0.25}, "chat_limits": {"per_turn_usd": 0.05}}
        self.write_config()
        self.profiles = [{"id": pid, "name": name, "position": pos, "enabled": True, "launch_mode": "safe", "equipped_skill_ids": [],
                          "model": {"tool": "claude", "model_id": "haiku"}} for pid, name, pos in ((W, "寫手", "social"), (A, "會計", "accountant"))]
        self.open = True
        self.spent = 0.0
        self.autonomy = {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": False}
        self.settings = {"daily_usd": None, "keep_awake": False}
        self.routines, self.skills, self.chats, self.groups, self.sugg = {}, {}, {}, {}, {}
        self.n = 0
        self.grace_end = 0.0
        self.calls = []
        self.last_beat = start

    # -- files ---------------------------------------------------------------------------------------------------------------

    def write_config(self):
        (self.state / "config.json").write_text(json.dumps(self.config))

    def log(self, folder, name, row):
        (self.state / folder).mkdir(exist_ok=True)
        with (self.state / folder / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def ident(self, prefix, size):
        self.n += 1
        return f"{prefix}{self.n:0{size}x}"

    # -- the clock -----------------------------------------------------------------------------------------------------------

    def sleep(self, seconds):
        self.now[0] += seconds
        self.tick()

    def clock(self):
        return self.now[0]

    def tick(self):
        if not self.open:
            return
        self.last_beat = self.now[0]
        self.routine_tick(missed=False)
        self.group_tick()

    def close(self, seconds):
        self.open = False
        self.now[0] += seconds

    def reopen(self):
        self.open = True
        self.routine_tick(missed=True)
        self.last_beat = self.now[0]

    # -- chats ---------------------------------------------------------------------------------------------------------------

    def new_chat(self, pid, title=None):
        cid = self.ident("c-", 16)
        self.chats[cid] = {"pid": pid, "records": [], "turn": 0, "pending": None, "title": title}
        return cid

    def rec(self, chat, kind, **kw):
        chat["records"].append({"seq": len(chat["records"]) + 1, "kind": kind, **kw})

    def finish(self, chat):
        self.rec(chat, "reply", turn=chat["turn"], text=MODEL_WORDS)
        self.rec(chat, "turn_ended", turn=chat["turn"], reason="result")
        chat["pending"] = None
        self.grace_end = float("inf") if self.flaws.get("caffeinate_stays") else self.now[0] + 30

    def send(self, chat, text):
        chat["turn"] += 1
        self.rec(chat, "user_message", turn=chat["turn"], text=text)
        self.spent += 0.01
        if "Bash" in text:
            cid = self.ident("k-", 16)
            self.rec(chat, "card", turn=chat["turn"], card_id=cid, tool="Bash", input={"command": "echo qa44"}, state="asked")
            chat["pending"] = {"card_id": cid, "token": "t" * 32, "tool": "Bash"}
        else:
            self.finish(chat)
        return chat["turn"]

    def caffeine_alive(self):
        if self.flaws.get("no_caffeinate") or not self.settings["keep_awake"]:
            return False
        return any(c["pending"] for c in self.chats.values()) or self.now[0] < self.grace_end

    def runner(self, argv, **kw):
        out = ""
        if argv[0] == qa.PMSET:
            out = "Assertion status system-wide:\n   pid 123(powerd): [0x1] 00:01:00 NoIdleSleepAssertion named: x\n"
            if self.caffeine_alive():
                out += "   pid 4242(caffeinate): [0x2] 00:00:05 PreventUserIdleSystemSleep named: caffeinate command-line tool\n"
        elif argv[0] == qa.PS:
            out = f" {CONSOLE_PID} /usr/bin/caffeinate -i -w {CONSOLE_PID}\n"
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)

    # -- routines ------------------------------------------------------------------------------------------------------------

    def run_row(self, routine, slot, by, why, state, reason=None):
        row = {"run_id": self.ident("rr-", 12), "routine_id": routine["id"], "slot": slot, "state": state, "by": by, "why": why,
               "chat_id": None, "reason": reason}
        routine["runs"].append(row)
        return row

    def start_run(self, routine, row, by):
        cid = self.new_chat(routine["profile_id"], "例行工作：" + routine["name"])
        chat = self.chats[cid]
        row.update(by=by, state="starting", chat_id=cid)
        turn = self.send(chat, "（固定的一行）" + routine["text"])
        row["state"] = "done" if not chat["pending"] else "running"
        if self.flaws.get("auto_twice") and by == "auto3" and not routine.get("twice"):
            routine["twice"] = True
            self.run_row(routine, row["slot"], "auto3", "on_time", "done")
        return turn

    def slots(self, routine):
        today = datetime.datetime.fromtimestamp(self.now[0], TAIPEI).date()
        for back in range(0, 3):
            day = today - datetime.timedelta(days=back)
            if day.weekday() not in routine["days"]:
                continue
            for hhmm in routine["times"]:
                h, m = map(int, hhmm.split(":"))
                due = datetime.datetime.combine(day, datetime.time(h, m), tzinfo=TAIPEI).timestamp()
                yield f"{day.isoformat()}T{hhmm}", due

    def routine_tick(self, missed):
        for routine in self.routines.values():
            if not routine["enabled"]:
                continue
            for slot, due in sorted(self.slots(routine), key=lambda x: x[1]):
                if due > self.now[0] or due <= routine["created"] or any(r["slot"] == slot for r in routine["runs"]):
                    continue
                auto = self.autonomy["routines"] or self.flaws.get("reminder_opens_chat")
                if missed:
                    if auto or self.flaws.get("wake_auto_off"):
                        self.start_run(routine, self.run_row(routine, slot, "auto3", "catch_up", "starting"), "auto3")
                    else:
                        self.run_row(routine, slot, "you", "catch_up", "waiting", "asleep:1")
                elif auto:
                    self.start_run(routine, self.run_row(routine, slot, "auto3", "on_time", "starting"), "auto3")
                else:
                    self.run_row(routine, slot, "you", "on_time", "waiting")

    def waiting_rows(self):
        rows = []
        for routine in self.routines.values():
            for run in routine["runs"]:
                if run["state"] == "waiting":
                    row = {"run_id": run["run_id"], "routine_id": routine["id"], "name": routine["name"], "slot": run["slot"], "due_at": 1.0}
                    rows.append({"kind": "routine_missed" if run["why"] == "catch_up" else "routine_due", **row,
                                 **({"count": 1, "too_old": False} if run["why"] == "catch_up" else {})})
        for gid, g in self.groups.items():
            if g["pause"]:
                rows.append({"kind": "group_resume", "group_id": gid, "name": "g", "state": "counting", "until": g["pause"]["until"], "text": "x"})
        return rows

    # -- groups --------------------------------------------------------------------------------------------------------------

    def lamp(self):
        shown = self.spent + (0.5 if self.flaws.get("over_spend") else 0.0)
        return "red" if shown >= self.config["meeting_limits"]["daily_usd"] else "green"

    def group_tick(self):
        for g in self.groups.values():
            if g["round"] != "running":
                if g["pause"] and self.flaws.get("group_goes_on") and self.now[0] > g["pause"]["since"] + 20:
                    g["pause"], g["round"] = None, "idle"
                continue
            g["ticks"] += 1
            if g["ticks"] >= 2:
                self.spent += 0.02
                g["current"] = None
                if self.lamp() == "red":
                    until = datetime.datetime.combine(datetime.datetime.fromtimestamp(self.now[0], TAIPEI).date() + datetime.timedelta(days=1),
                                                      datetime.time.min, tzinfo=TAIPEI).timestamp()
                    g["round"], g["pause"] = "paused", {"reason": "daily_limit", "until": until, "since": self.now[0]}
                else:
                    g["round"] = "idle"

    def group_view(self, gid):
        g = self.groups[gid]
        pause = None
        if g["pause"]:
            left = max(1, int((g["pause"]["until"] - self.now[0]) // 60))
            pause = {"reason": g["pause"]["reason"], "until": g["pause"]["until"],
                     "countdown": {"state": "counting", "until": g["pause"]["until"], "text": f"還有 {left // 60} 小時可以繼續"}}
        return {"group": {"id": gid, "state": "idle"}, "round": {"n": 1, "state": g["round"], "pause": pause, "asked": []}, "current": g["current"]}

    # -- the routes ----------------------------------------------------------------------------------------------------------

    def route(self, path, method="GET", body=None):
        if not self.open:
            raise ConnectionRefusedError("the console is closed")
        route = path.split("?")[0]
        after = int(path.split("after=")[1]) if "after=" in path else 0
        self.calls.append((method, route, body))
        if route == "/api/agent-profiles":
            return 200, {"ok": True, "profiles": self.profiles}
        if route == "/api/meetings/ledger":
            extra = 0.5 if self.flaws.get("over_spend") else 0.0
            return 200, {"spent_usd": f"{self.spent + extra:.2f}", "daily_usd": f"{self.config['meeting_limits']['daily_usd']:.2f}", "lamp": self.lamp()}
        if route == "/api/settings/autonomy":
            if method == "POST":
                self.autonomy = dict(body)
                self.config["autonomy"] = dict(body)
                if self.flaws.get("config_extra_key"):
                    self.config["mystery"] = 1
                self.write_config()
            return 200, {"ok": True, "autonomy": self.autonomy}
        if route == "/api/setup/daily-limit":
            self.config["meeting_limits"] = {**self.config["meeting_limits"], "daily_usd": body["daily_usd"],
                                             "meeting_usd": min(self.config["meeting_limits"]["meeting_usd"], body["daily_usd"])}
            self.config["chat_limits"] = {"per_turn_usd": min(self.config["chat_limits"]["per_turn_usd"], body["daily_usd"])}
            self.write_config()
            return 200, {"ok": True}
        if route == "/api/config" and method == "POST":
            self.config.update(body)
            self.write_config()
            return 200, {"ok": True}
        if route == "/api/waiting":
            return 200, {"waiting": self.waiting_rows()}
        if route == "/api/actions":
            rows = [{"routine_id": r["routine_id"], "by": "auto3", "by_text": "自己動手第 3 項"} for rt in self.routines.values() for r in rt["runs"]
                    if r["by"] == "auto3"]
            return 200, {"actions": rows}
        if route.startswith("/api/routines"):
            return self.routes_routines(route, method, body)
        if route.startswith("/api/my-skills"):
            return self.routes_skills(route, method, body)
        if route == "/api/chats" and method == "GET":
            return 200, {"chats": [{"id": k, **({"routine_title": v["title"]} if v["title"] else {})} for k, v in self.chats.items()]}
        if route == "/api/chats" and method == "POST":
            return 201, {"ok": True, "chat": {"id": self.new_chat(body["profile_id"])}}
        found = CHAT_RE.match(route)
        if found:
            chat = self.chats[found.group(1)]
            if found.group(2) == "/messages":
                return 202, {"ok": True, "turn": self.send(chat, body["text"])}
            if found.group(2) == "/answer":
                if chat["pending"]:
                    self.finish(chat)
                return 200, {"ok": True}
            recs = [r for r in chat["records"] if r["seq"] > after]
            live = {"cards": [chat["pending"]]} if chat["pending"] else None
            return 200, {"records": recs, "live": live, "more": False, "next_after": len(chat["records"])}
        if route == "/api/groups" and method == "POST":
            gid = "g-" + f"{len(self.groups) + 1:012x}"
            self.groups[gid] = {"round": "idle", "pause": None, "current": None, "ticks": 0, "chat": self.new_chat(body["profile_ids"][0])}
            return 200, {"group": {"id": gid}}
        found = GROUP_RE.match(route)
        if found:
            gid, g = found.group(1), self.groups.get(found.group(1))
            if found.group(2) == "/messages":
                g.update(round="running", ticks=0, current={"profile_id": W, "chat_id": g["chat"], "turn": 1})
                return 202, {"round": 1}
            if found.group(2) == "/drop":
                g.update(round="idle", pause=None)
                return 200, {"ok": True}
            if method == "DELETE":
                self.groups.pop(gid)
                return 200, {"ok": True}
            return 200, self.group_view(gid)
        return 404, {"code": "unknown"}

    def routes_routines(self, route, method, body):
        if route == "/api/routines" and method == "GET":
            rows = [{**r, "runs": [{**x, "by_text": {"you": "你按的", "auto3": "自己動手第 3 項"}[x["by"]]} for x in reversed(r["runs"])]}
                    for r in self.routines.values()]
            return 200, {"routines": rows, "settings": {"daily_usd": "0.12", "daily_usd_set": self.settings["daily_usd"],
                                                        "keep_awake": self.settings["keep_awake"]}}
        if route == "/api/routines" and method == "POST":
            rid = self.ident("r-", 12)
            self.routines[rid] = {"id": rid, **body, "runs": [], "created": self.now[0]}
            return 201, {"ok": True, "routine": {"id": rid}}
        if route == "/api/routines/settings":
            self.settings.update(body)
            return 200, {"settings": self.settings}
        found = re.match(r"^/api/routines/waiting/(rr-[0-9a-f]{12})$", route)
        if found:
            for routine in self.routines.values():
                for run in routine["runs"]:
                    if run["run_id"] == found.group(1):
                        self.start_run(routine, run, "you") if body["action"] == "start" else run.update(state="skipped")
                        return 200, {"run": run}
        found = re.match(r"^/api/routines/missed/(r-[0-9a-f]{12})$", route)
        if found:
            routine = self.routines[found.group(1)]
            run = next((r for r in routine["runs"] if r["state"] == "waiting"), None)
            if run is None:
                return 409, {"code": "nothing_missed"}
            if body["action"] == "run":
                self.start_run(routine, run, "you")
            else:
                run["state"] = "dismissed"
            return 200, {"run": run}
        found = re.match(r"^/api/routines/(r-[0-9a-f]{12})(/delete)?$", route)
        if found and found.group(2):
            self.routines.pop(found.group(1), None)
            return 200, {"ok": True}
        if found:
            self.routines[found.group(1)].update(body)
            return 200, {"ok": True}
        return 404, {"code": "unknown"}

    def routes_skills(self, route, method, body):
        if route == "/api/my-skills" and method == "GET":
            return 200, {"skills": list(self.skills.values())}
        if route == "/api/my-skills" and method == "POST":
            text = body["text"]
            if re.search(r"sk-[0-9a-f]{20,}", text) and not self.flaws.get("key_accepted"):
                return 400, {"code": "skill_refused"}
            if "不用問我" in text and not body.get("confirm_warning"):
                return 409, {"code": "confirm_warning"}
            sid = self.ident("k-", 12)
            self.skills[sid] = {"id": sid, "name": body["name"], "text": text, "source": body.get("source", {"how": "typed"})}
            self.log("skillbook", "log.jsonl", {"action": "add", "id": sid, **({"name": body["name"]} if self.flaws.get("log_has_words") else {})})
            return 201, {"ok": True, "skill": self.skills[sid]}
        if route == "/api/my-skills/suggest/preview":
            cap = "0.50" if self.flaws.get("suggest_over_cap") else "0.10"
            return 200, {"ok": True, "preview_id": "kp-1", "messages": 2, "cap_usd": cap, "sends_to": "Anthropic"}
        if route == "/api/my-skills/suggest" and method == "POST":
            self.spent += 0.03
            items = [] if self.flaws.get("suggest_empty") else [{"name": "QA44 提案", "text": "（虛構）提案的內容", "refuse": None, "warn": []}]
            self.sugg["ks-000000000001"] = {"id": "ks-000000000001", "status": "ready", "items": items, "spent_usd": "0.03"}
            if self.flaws.get("suggest_autosaves"):
                self.routes_skills("/api/my-skills", "POST", {"name": "自動", "text": "x"})
            return 202, {"id": "ks-000000000001"}
        found = re.match(r"^/api/my-skills/suggest/(ks-[0-9a-f]{12})(/saved)?$", route)
        if found:
            return 200, self.sugg[found.group(1)]
        found = re.match(r"^/api/my-skills/(k-[0-9a-f]{12})/delete$", route)
        if found:
            self.skills.pop(found.group(1), None)
            self.log("skillbook", "log.jsonl", {"action": "delete", "id": found.group(1)})
            return 200, {"ok": True}
        return 404, {"code": "unknown"}


class FakeConsole(qa.Console):
    def __init__(self, world):
        super().__init__(PORT, TOKEN)
        self.world = world

    def call(self, path, method="GET", body=None):
        return self.world.route(path, method, body)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="q44")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.state = self.base / "s"
        self.state.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()

    def world(self, start=None, **flaws):
        self.w = World(self.state, at(12, 0) if start is None else start, **flaws)
        return self.w

    def run_main(self, *args, world=None, cards=(W, A), start=None):
        w = world or self.w
        out = io.StringIO()
        argv = ["--state", str(self.state), "--port", str(PORT), "--cards", ",".join(cards), *args]
        with contextlib.redirect_stdout(out):
            code = qa.main(argv, out=lambda s: print(s), console_factory=lambda port, token: FakeConsole(w), clock=w.clock, sleep=w.sleep,
                           runner=w.runner, tz=TAIPEI, home=self.home)
        return code, out.getvalue()

    def whole(self, world=None):
        """A whole run in the three parts the coordinator runs (the console is closed and opened between them)."""
        w = world or self.w
        code1, out1 = self.run_main("--until", "wake1-prepare")
        w.close(6 * 60)
        w.reopen()
        code2, out2 = self.run_main("--from", "wake1-check", "--until", "wake2-prepare")
        w.close(6 * 60)
        w.reopen()
        code3, out3 = self.run_main("--from", "wake2-check")
        return (code1, code2, code3), out1 + out2 + out3


class Refusals(Base):
    def test_it_refuses_the_port_the_folder_the_time_and_the_cards(self):
        w = self.world()
        for port in (7788, 7789):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = qa.main(["--state", str(self.state), "--port", str(port), "--cards", f"{W},{A}"], out=print, home=self.home,
                               console_factory=lambda p, t: FakeConsole(w), clock=w.clock, sleep=w.sleep, runner=w.runner, tz=TAIPEI)
            self.assertEqual(code, 2, port)
            self.assertIn("refused", out.getvalue())
        own = self.home / ".vbear" / "x"
        own.mkdir(parents=True)
        for folder in (self.home / ".vbear", own):
            self.assertIn("own VBear", qa.refusal(str(folder), PORT, self.home))
        self.assertIn("does not exist", qa.refusal(str(self.base / "nope"), PORT, self.home))
        self.assertIsNone(qa.refusal(str(self.state), PORT, self.home))
        self.assertEqual(self.run_main(cards=(W,))[0], 2)
        self.assertEqual(self.run_main(cards=(W, W))[0], 2)
        self.assertEqual(self.run_main("--from", "final", "--until", "setup")[0], 2)
        for hour, minute in ((23, 30), (23, 59), (0, 0), (0, 29)):
            self.assertIn("between 23:30 and 00:30", qa.time_refusal(at(hour, minute), TAIPEI) or "", (hour, minute))
        self.assertIsNone(qa.time_refusal(at(0, 30), TAIPEI))
        self.assertIsNone(qa.time_refusal(at(23, 29), TAIPEI))
        w.now[0] = at(23, 45)
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertEqual(w.calls, [], "nothing was asked of the console at that hour")

    def test_the_helpers(self):
        self.assertEqual(qa.caffeinate_pids("pid 123(powerd): x\n  pid 4242(caffeinate): y\npid 7(caffeinate): z"), [4242, 7])
        self.assertTrue(qa.child_of_console(" 9001 /usr/bin/caffeinate -i -w 9001\n"))
        self.assertFalse(qa.child_of_console(" 1 /usr/bin/caffeinate -i -w 9001\n"))
        self.assertFalse(qa.child_of_console(" 9001 /usr/bin/caffeinate -d -w 9001\n"))
        self.assertEqual(qa.config_problems({"a": qa.sha(1), "b": qa.sha(2)}, {"a": 1, "b": 3, "autonomy": {}, "c": 1}), ["b", "c"])
        self.assertEqual(qa.card_problems({"launch_mode": "auto", "equipped_skill_ids": ["x"]}), ["launch_mode", "equipped_skill_ids"])
        self.assertEqual(qa.due_time(at(12, 0), 2, TAIPEI)[:2], ("12:02", 0))
        with self.assertRaises(qa.Stop):
            qa.due_time(at(23, 0), 90, TAIPEI)
        self.assertEqual(qa.tomorrow_midnight(at(12, 0), TAIPEI), at(0, 0, 10))
        profiles = [{"id": W, "model": {"tool": "claude"}}, {"id": A, "model": {"tool": "codex"}}]
        with self.assertRaises(qa.Stop):
            qa.pick_cards(profiles, [W, A])
        with self.assertRaises(qa.Stop):
            qa.pick_cards(profiles, [W, "emp-nope"])


class Behaves(Base):
    def test_a_console_that_behaves_passes_every_stage_and_the_output_holds_no_secret(self):
        w = self.world()
        codes, out = self.whole()
        self.assertEqual(codes, (0, 0, 0), out)
        self.assertEqual([x for x in out.splitlines() if x.startswith("FAIL")], [])
        self.assertIn("qa_p44: PASS", out)
        for stage_line in ("the four 自己動手 ticks are off", "the skill is saved", "pressing 存 saves it once", "「現在開始」 opened a chat",
                           "自己動手第 3 項", "while the card waits there is a caffeinate", "D and E are each listed as missed once",
                           "F was caught up by itself", "the round stopped because of the daily limit", "the group page has the countdown",
                           "no caffeinate is a child of the console", "money by stage"):
            self.assertIn(stage_line, out)
        for secret in (TOKEN, MODEL_WORDS, "第二行", "sk-", "虛構日報", "QA44 技能"):
            self.assertNotIn(secret, out)
        self.assertEqual(w.skills, {}, "the skills it made are deleted")
        self.assertEqual(w.routines, {}, "the routines it made are deleted")
        self.assertEqual(w.groups, {})
        self.assertEqual(w.config["autonomy"], {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": False})
        self.assertFalse(w.settings["keep_awake"])
        self.assertEqual(w.config["meeting_limits"]["daily_usd"], 0.25, "the daily limit is put back")
        self.assertEqual(w.config["chat_limits"], {"per_turn_usd": 0.05})
        self.assertEqual(w.config["meeting_limits"]["meeting_usd"], 0.25)
        memo = json.loads((self.base / qa.STATE_FILE).read_text())
        self.assertNotIn(TOKEN, json.dumps(memo))
        self.assertNotIn("虛構", json.dumps(memo, ensure_ascii=False))
        for call in w.calls:
            self.assertFalse(call[1].startswith("/api/shared"), call)

    def test_the_stages_can_be_run_one_by_one_and_a_prepare_stage_ends_the_run(self):
        w = self.world()
        code, out = self.run_main("--until", "suggest")
        self.assertEqual(code, 0, out)
        self.assertIn("qa_p44: PASS", out)
        self.assertEqual(len(w.skills), 2, "the skill and the suggestion are saved until final")
        code, out = self.run_main("--from", "remind", "--until", "wake1-prepare")
        self.assertEqual(code, 0, out)
        self.assertIn("STOP the console now", out)
        self.assertNotIn("wake1-check", out)
        self.assertEqual(len(w.routines), 5, "A, B, C, D and E")
        code, out = self.run_main("--from", "wake2-check")
        self.assertEqual(code, 1, "the stages in between were not run")
        self.assertIn("wake2-prepare has not run", out)

    def test_a_run_that_starts_in_the_middle_needs_the_memo(self):
        self.world()
        code, out = self.run_main("--from", "skill")
        self.assertEqual(code, 1)
        self.assertIn("run the stages from setup first", out)

    def test_a_console_that_is_closed_is_a_fail_and_not_a_traceback(self):
        w = self.world()
        w.open = False
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertNotIn("Traceback", out)


class Misbehaves(Base):
    def fails(self, expected, **flaws):
        self.world(**flaws)
        codes, out = self.whole()
        self.assertNotEqual(codes, (0, 0, 0), flaws)
        self.assertTrue(any(expected in line for line in out.splitlines() if line.startswith("FAIL")), (flaws, out))
        return out

    def test_a_key_that_is_saved(self):
        self.fails("a skill with a key in it is refused", key_accepted=True)

    def test_a_suggestion_over_its_cap(self):
        self.fails("the preview says Anthropic and at most US$0.10", suggest_over_cap=True)

    def test_a_suggestion_that_saves_by_itself(self):
        self.fails("the skills did not change by themselves", suggest_autosaves=True)

    def test_a_reminder_that_opens_a_chat(self):
        self.fails("no chat was opened", reminder_opens_chat=True)

    def test_a_time_that_starts_twice(self):
        self.fails("the time still has one run", auto_twice=True)

    def test_no_caffeinate_while_a_card_waits(self):
        self.fails("while the card waits there is a caffeinate", no_caffeinate=True)

    def test_a_caffeinate_that_stays(self):
        self.fails("no caffeinate of the console", caffeinate_stays=True)

    def test_a_group_that_goes_on_by_itself(self):
        self.fails("a group never goes on by itself", group_goes_on=True)

    def test_a_key_added_to_config_json(self):
        self.fails("config.json is as setup left it", config_extra_key=True)

    def test_a_name_in_a_log(self):
        self.fails("holds no name", log_has_words=True)

    def test_too_much_spent(self):
        self.fails("within the allowance", over_spend=True)

    def test_a_missed_time_that_is_caught_up_with_item_3_off(self):
        self.fails("and nothing began by itself", wake_auto_off=True)


if __name__ == "__main__":
    unittest.main()
