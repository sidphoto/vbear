"""P41-4: tools/qa_p41.py, the coordinator's real-machine check of group chat, must refuse to run without a state folder of its own,
never aim at the person's VBear (its folder, anything under it, ports 7788 and 7789), print none of what a model wrote or the
access token, pass over a console that behaves, and FAIL over one that does not (B asked when only B was named is the other way
round: A asked when only B was named; a message with no markers; the round going on after the limit; a key added to config.json;
the group's fixed words sent twice; a file written after the card was refused; the group's chats in the chat list; too much spent).
Nothing here starts a console or a model: the console is an in-memory fake that builds the employees' messages with the real
``groups.build_message``, so the check reads the format the server really writes.

Seams: ``qa_p41.main`` (the command line, with a fake console), ``refusal``, ``pick_cards``, ``parse_data``, ``config_problems``,
``card_problems`` and ``work_dir``."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from vbear import groups
from vbear.runtime import chat_store as cs

SPEC = importlib.util.spec_from_file_location("qa_p41", Path(__file__).resolve().parent.parent / "tools" / "qa_p41.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

GID = "g-0123456789ab"
CONSOLE_AT = 50123
TOKEN = "synthetic-token-never-printed"
SECRET = "FAKE-REPLY-WORDS-NEVER-PRINTED"
A, B = "emp-aaaa", "emp-bbbb"
CHAT = {A: "c-" + "a" * 16, B: "c-" + "b" * 16}
NAME = {A: "文案", B: "會計"}


class FakeConsole(qa.Console):
    """A console that holds one group in memory and moves it one step on every read of the group (the real one has its runner and its
    model; the script waits by reading, so a read is the only clock it needs). ``flaws`` are the ways it misbehaves."""

    def __init__(self, state: Path, **flaws):
        super().__init__(CONSOLE_AT, TOKEN)
        self.state, self.flaws = Path(state), flaws
        self.cost = flaws.get("turn_cost", 0.02)
        self.daily, self.spent = 0.45, 0.0
        self.profiles = [{"id": pid, "name": NAME[pid], "position": "social", "enabled": True, "launch_mode": "safe", "equipped_skill_ids": [],
                          "model": {"tool": "claude", "model_id": "haiku"}, "updated_at": 100 + i} for i, pid in enumerate((A, B))]
        self.config = {"setup_done": True, "meeting_limits": {"daily_usd": 0.45, "per_call_usd": 0.2}, "staffing_limits": {"total_usd": 0.45},
                       "chat_limits": {"per_turn_usd": 0.1, "daily_usd": 0.45}}
        self.write_config()
        (self.state / "server.token").write_text(json.dumps({"port": CONSOLE_AT, "token": TOKEN}))
        self.made = False
        self.calls: list[tuple] = []
        self.sent: list[tuple] = []                  # (pid, text, round) in order
        self.items: list[dict] = []
        self.talk: list[dict] = []
        self.heard: dict[str, int] = {}
        self.started: set[str] = set()
        self.records = {CHAT[A]: [], CHAT[B]: []}
        self.cards: dict[str, dict] = {}
        self.round = None
        self.members = [A, B]
        self.n = 0
        self.answered: list[tuple] = []

    # -- files -------------------------------------------------------------------------------------------------------------

    def write_config(self):
        (self.state / "config.json").write_text(json.dumps(self.config))

    def seq(self):
        return len(self.items) + 1

    def add(self, kind, **kw):
        self.items.append({"seq": self.seq(), "at": 1.0 + len(self.items), "kind": kind, **kw})

    # -- the group moves one step on each read -------------------------------------------------------------------------------

    def red(self):
        return self.spent >= self.daily - 1e-9 and not self.flaws.get("ignore_limit")

    def advance(self):
        r = self.round
        if r is None or r["state"] != "running":
            return
        if r["cur"] is None:
            if r["i"] >= len(r["asked"]):
                r["state"], r["how"] = "idle", "done"
                self.add("round_ended", round=r["n"], how="done")
                return
            if self.red():
                r["state"], r["pause"] = "paused", {"reason": "daily_limit", "until": 9.0, "text": "今天的花費到了每天上限 US$0.01，本機明天 0:00 重新計算；還有 1 位沒回答。"}
                self.add("paused", round=r["n"], reason="daily_limit", until=9.0, text=r["pause"]["text"])
                return
            pid = r["asked"][r["i"]]
            self.send(pid, r)
            return
        cur = r["cur"]
        if cur["pid"] in self.cards:
            return                                   # a card waits for the person
        cur["ticks"] += 1
        if cur["ticks"] >= 2:
            self.finish(cur["pid"], r)

    def send(self, pid, r):
        first = pid not in self.started and not self.flaws.get("intro_every_time") or bool(self.flaws.get("intro_every_time"))
        mine = [e for e in self.talk[self.heard.get(pid, 0):] if e["round"] != r["n"] or e["who"] != "用的人"]
        items = [{k: v for k, v in e.items() if k != "round"} for e in mine]
        to_text = "大家" if r["to"] == "all" else "、".join(NAME[x] for x in r["to"])
        members = [{"name": NAME[m], "tool": "Claude Code"} for m in self.members]
        message = groups.build_message(group="QA 群組", members=members, me=NAME[pid], first=first, items=items, said=r["text"], to_text=to_text)
        if self.flaws.get("no_data_sentence"):
            message = message.replace(groups.DATA_HEAD, "")
        if self.flaws.get("no_markers"):
            message = message.replace(groups.MARK_BEGIN, "").replace(groups.MARK_END, "")
        self.heard[pid] = len(self.talk)
        self.started.add(pid)
        self.records[CHAT[pid]].append({"seq": len(self.records[CHAT[pid]]) + 1, "kind": "user_message", "text": message})
        self.sent.append((pid, message, r["n"]))
        r["cur"] = {"pid": pid, "ticks": 0}
        self.spent += self.cost
        if "Bash" in r["text"] and not self.flaws.get("no_card"):
            self.cards[pid] = {"card_id": "k-" + "a" * 16, "token": "t" * 32, "turn": 1, "tool": "Bash", "input": {"command": "echo qa41 > qa41.txt"},
                               "editable": "command", "reason": "x", "expires_in": 290}

    def finish(self, pid, r, reason="result"):
        text = SECRET + " " + NAME[pid]
        self.talk.append({"who": NAME[pid], "text": text, "round": r["n"]})
        self.add("reply", round=r["n"], profile_id=pid, name=NAME[pid], tool="claude", text=text, cost_usd=f"{self.cost:.2f}", partial=reason != "result",
                 chat_id=CHAT[pid], turn=len(self.records[CHAT[pid]]))
        r["cur"] = None
        r["done"].append(pid)
        r["i"] += 1

    # -- the routes --------------------------------------------------------------------------------------------------------

    def view(self, after):
        self.advance()
        r = self.round
        group_state = "idle" if r is None else r["state"]
        asked = []
        if r:
            for pid in r["asked"]:
                asked.append({"profile_id": pid, "state": "skipped" if pid in r["skipped"] else "done" if pid in r["done"]
                              else "answering" if r["cur"] and r["cur"]["pid"] == pid else "waiting"})
        cur = {"profile_id": r["cur"]["pid"], "chat_id": CHAT[r["cur"]["pid"]], "turn": 1} if r and r["cur"] else None
        return {"group": {"id": GID, "name": "QA 群組", "state": group_state, "problem": None},
                "members": [{"profile_id": m, "name": NAME[m], "tool": "claude"} for m in self.members],
                "items": [i for i in self.items if i["seq"] > after], "next_after": len(self.items), "last_seq": len(self.items), "more": False,
                "round": None if r is None else {"n": r["n"], "state": r["state"], "to": r["to"], "how": r.get("how"), "asked": asked, "pause": r.get("pause")},
                "current": cur, "cost": {"per_turn_usd": "0.1", "day_left_usd": "0.3", "lamp": "red" if self.red() else "green", "group_today_usd": "0"},
                "can": {"send": group_state == "idle", "stop": group_state in ("running", "paused"), "continue": group_state == "paused",
                        "drop": group_state == "paused", "edit_members": group_state == "idle", "delete": group_state == "idle"}}

    def say(self, body):
        r = self.round
        if r is not None and r["state"] != "idle":
            return 409, {"code": "round_open"}
        if self.red():
            return 409, {"code": "red"}
        to = body["to"]
        self.n += 1
        asked = list(self.members) if to == "all" or self.flaws.get("extra_ask_on_named") else [m for m in self.members if m in to]
        self.round = {"n": self.n, "to": to, "text": body["text"], "asked": asked, "i": 0, "cur": None, "state": "running", "done": [], "skipped": [], "pause": None}
        self.talk.append({"who": "用的人", "text": body["text"], "round": self.n, **({} if to == "all" else {"to": [NAME[x] for x in to]})})
        self.add("said", round=self.n, text=body["text"], to=to, to_names=None if to == "all" else [NAME[x] for x in to])
        return 202, {"round": self.n}

    def stop(self):
        r = self.round
        if r is None or r["state"] == "idle":
            return 409, {"code": "not_active"}
        if r["cur"]:
            self.finish(r["cur"]["pid"], r, reason="stopped")
        for pid in r["asked"][r["i"]:]:
            r["skipped"].append(pid)
            self.add("skipped", round=r["n"], profile_id=pid, reason="stopped", text="停")
        r["state"], r["how"] = "idle", "stopped"
        self.add("round_ended", round=r["n"], how="stopped")
        return 200, {"round": r["n"], "state": "idle"}

    def call(self, path, method="GET", body=None):
        route = path.split("?")[0]
        after = int(path.split("after=")[1]) if "after=" in path else 0
        self.calls.append((method, route, body))
        if route == "/api/agent-profiles":
            return 200, {"ok": True, "profiles": self.profiles}
        if route == "/api/meetings/ledger":
            return 200, {"spent_usd": f"{self.spent + self.flaws.get('ledger_extra', 0):.2f}", "daily_usd": f"{self.daily}", "lamp": "red" if self.red() else "green"}
        if route == "/api/groups" and method == "POST":
            self.made = True
            folder = self.state / "groups" / GID
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "group.json").write_text(json.dumps({"members": [{"profile_id": m, "chat_id": CHAT[m], "removed_at": None} for m in self.members]}))
            return 200, {"group": {"id": GID}, "notes": []}
        if route == "/api/groups":
            if not self.made:
                return 200, {"groups": []}
            state = "idle" if self.round is None else self.round["state"]
            return 200, {"groups": [{"id": GID, "name": "QA 群組", "state": state, "waiting": bool(self.cards), "members": [{"profile_id": m, "name": NAME[m]} for m in self.members]}]}
        if route == f"/api/groups/{GID}" and method == "GET":
            return (200, self.view(after)) if self.made else (404, {"code": "not_found"})
        if route == f"/api/groups/{GID}/messages":
            return self.say(body)
        if route == f"/api/groups/{GID}/stop":
            return self.stop()
        if route == f"/api/groups/{GID}/continue":
            r = self.round
            if r is None or r["state"] != "paused":
                return 409, {"code": "not_paused"}
            r["state"], r["pause"] = "running", None
            self.add("continued", round=r["n"])
            return 200, {"round": r["n"], "state": "running"}
        if route == f"/api/groups/{GID}" and method == "DELETE":
            self.made = False
            if self.flaws.get("spend_drops"):
                self.spent -= 0.01
            return 200, {"deleted": GID}
        if route == "/api/chats" and method == "GET":
            rows = [{"id": c} for c in CHAT.values()] if self.flaws.get("lists_group_chats") else []
            return 200, {"chats": rows, "cards": []}
        m = [c for c in CHAT.values() if route.startswith(f"/api/chats/{c}")]
        if m:
            cid = m[0]
            pid = next(p for p, c in CHAT.items() if c == cid)
            if not self.made:
                return 404, {"code": "not_found"}
            if route.endswith("/messages"):
                return 409, {"code": "group_member_chat"}
            if route.endswith("/answer"):
                self.answered.append((pid, body.get("decision")))
                self.cards.pop(pid, None)
                if self.flaws.get("writes_file"):
                    folder = qa.work_dir(self.state, pid)
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / qa.FILE_NAME).write_text("x")
                return 200, {"answered": body.get("card_id")}
            recs = [r for r in self.records[cid] if r["seq"] > after]
            live = {"cards": [self.cards[pid]]} if pid in self.cards else None
            return 200, {"records": recs, "live": live, "more": False, "next_after": after}
        if route == "/api/setup/daily-limit":
            self.daily = body["daily_usd"]
            self.config["meeting_limits"]["daily_usd"] = self.daily
            self.config["chat_limits"]["daily_usd"] = self.daily
            self.config["chat_limits"]["per_turn_usd"] = min(self.config["chat_limits"]["per_turn_usd"], self.daily)
            self.write_config()
            return 200, {"ok": True, "changed": []}
        if route == "/api/config":
            self.config.update(body)
            if self.flaws.get("config_extra_key"):
                self.config["mystery"] = 1
            self.write_config()
            self.daily = self.config["meeting_limits"]["daily_usd"]
            return 200, {"ok": True}
        return 404, {"code": "unknown"}


class Harness(unittest.TestCase):
    def run_main(self, *args, fake=None, **flaws):
        tmp = tempfile.TemporaryDirectory(prefix="qa41-")
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name)
        console = fake or FakeConsole(state, **flaws)
        lines = []
        code = qa.main(["--state", str(console.state), "--port", str(CONSOLE_AT), *args], out=lines.append, console_factory=lambda port, token: console, **self.time())
        return code, lines, console

    def time(self):
        """A clock that only moves when the script sleeps, so that a wait that never ends times out at once instead of in 3 minutes."""
        now = [0.0]
        return {"clock": lambda: now[0], "sleep": lambda s: now.__setitem__(0, now[0] + s)}

    def fails(self, lines):
        return [l for l in lines if l.startswith("FAIL")]


class CommandLineTests(unittest.TestCase):
    def test_it_does_not_run_without_a_state_folder(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            qa.main([], out=lambda *_: None)
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("--state", err.getvalue())

    def test_it_refuses_the_ports_of_the_persons_own_vbear(self):
        with tempfile.TemporaryDirectory(prefix="qa41-") as tmp:
            for port in (7788, 7789):
                lines = []
                self.assertEqual(qa.main(["--state", tmp, "--port", str(port)], out=lines.append), 2)
                self.assertTrue(lines[0].startswith("refused"), lines)

    def test_it_refuses_the_persons_own_state_folder_anything_under_it_and_a_missing_one(self):
        with tempfile.TemporaryDirectory(prefix="qa41-") as tmp:
            home = Path(tmp).resolve()
            (home / ".vbear" / "groups").mkdir(parents=True)
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear"), 50001, home=home))
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear" / "groups"), 50001, home=home))
            self.assertIn("does not exist", qa.refusal(str(home / "nope"), 50001, home=home))
            self.assertIsNone(qa.refusal(str(home), 50001, home=home))
            self.assertIn("1024", qa.refusal(str(home), 80, home=home))

    def test_the_default_port_is_7796_and_not_the_persons(self):
        import re
        source = Path(qa.__file__).read_text(encoding="utf-8")
        default = int(re.search(r'"--port", type=int, default=(\d+)', source).group(1))
        self.assertEqual(default, 7796)
        self.assertNotIn(default, qa.FORBIDDEN_PORTS)

    def test_a_group_id_or_two_cards_that_are_not_are_refused_before_any_call(self):
        with tempfile.TemporaryDirectory(prefix="qa41-") as tmp:
            for args in (["--group", "../x"], ["--cards", "emp-a"], ["--cards", "a,b,c"]):
                lines = []
                self.assertEqual(qa.main(["--state", tmp, "--port", str(CONSOLE_AT), *args], out=lines.append, console_factory=lambda *_: self.fail("called")), 2, args)

    def test_a_state_folder_without_a_matching_token_stops_with_a_line_not_a_trace(self):
        with tempfile.TemporaryDirectory(prefix="qa41-") as tmp:
            lines = []
            self.assertEqual(qa.main(["--state", tmp, "--port", str(CONSOLE_AT)], out=lines.append), 1)
            self.assertTrue(any(l.startswith("FAIL stopped") for l in lines), lines)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": 1, "token": "x"}))
            with self.assertRaises(qa.Stop):
                qa.read_token(Path(tmp), CONSOLE_AT)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": CONSOLE_AT, "token": "synthetic"}))
            self.assertEqual(qa.read_token(Path(tmp), CONSOLE_AT), "synthetic")


class PureTests(unittest.TestCase):
    def test_the_work_folder_is_the_one_the_chat_store_names(self):
        self.assertEqual(qa.work_dir(Path("/s"), "emp-aaaa"), Path("/s/chat-work") / cs.work_dir_name("emp-aaaa"))

    def test_the_two_cards_are_the_newest_claude_haiku_ones_that_are_on_and_not_the_ceo(self):
        def card(pid, at, **over):
            return {"id": pid, "enabled": True, "position": "social", "model": {"tool": "claude", "model_id": "haiku"}, "updated_at": at, **over}
        rows = [card("old", 1), card("new", 9), card("mid", 5), card("ceo", 99, position="planner"), card("off", 98, enabled=False),
                card("codex", 97, model={"tool": "codex", "model_id": ""}), card("opus", 96, model={"tool": "claude", "model_id": "opus"})]
        self.assertEqual(qa.pick_cards(rows, None), ["new", "mid"])
        self.assertEqual(qa.pick_cards(rows, ["old", "mid"]), ["old", "mid"])
        for given in (["old", "ghost"], ["old", "off"], ["old", "codex"]):
            with self.assertRaises(qa.Stop):
                qa.pick_cards(rows, given)
        with self.assertRaises(qa.Stop):
            qa.pick_cards(rows[:1], None)

    def test_the_data_is_read_the_way_the_server_writes_it(self):
        message = groups.build_message(group="g", members=[], me="B", first=False, items=[{"who": "文案", "text": "有\"引號\"\n和換行"}],
                                       said="現在說的話", to_text="大家")
        items = qa.parse_data(message)
        self.assertEqual(items, [{"who": "文案", "text": "有\"引號\"\n和換行"}])
        self.assertTrue(qa.says_in(items, "文案", "有\"引號\"\n和換行"))
        self.assertFalse(qa.says_in(items, "會計", "有\"引號\"\n和換行"))
        self.assertFalse(qa.says_in(items, "文案", ""))
        self.assertIsNone(qa.parse_data(message.replace(qa.MARK_END, "")))
        self.assertIsNone(qa.parse_data("沒有標記"))
        self.assertIsNone(qa.parse_data(f"{qa.MARK_BEGIN}\n123\n{qa.MARK_END}"))

    def test_the_config_and_the_card_checks(self):
        self.assertEqual(qa.config_problems({"a": 1, "m": {"d": 1}}, {"a": 1, "m": {"d": 1}}), [])
        self.assertEqual(qa.config_problems({"a": 1}, {"a": 1, "b": 2}), ["b"])
        self.assertEqual(qa.config_problems({"m": {"d": 0.45}}, {"m": {"d": 0.01}}), ["m"])
        self.assertEqual(qa.card_problems({"launch_mode": "safe", "equipped_skill_ids": []}), [])
        self.assertEqual(qa.card_problems({"launch_mode": "full", "equipped_skill_ids": ["s"]}), ["launch_mode", "equipped_skill_ids"])


class WholeRunTests(Harness):
    def test_a_console_that_behaves_passes_every_stage_and_the_group_is_gone_at_the_end(self):
        code, lines, fake = self.run_main()
        self.assertEqual(self.fails(lines), [])
        self.assertEqual(code, 0, lines)
        self.assertTrue(lines[-1].startswith("qa_p41: PASS"), lines[-1])
        for phrase in ("the group's two chats are not in the chat list", "only B's chat got a message", "B's message holds the conversation as one JSON string",
                       "the round paused at the daily limit", "the round ended stopped", "A's work folder has no such file",
                       "the group and its two chats are gone", "config.json is as it was before", "turns by stage"):
            self.assertTrue(any(phrase in l for l in lines), phrase)
        self.assertFalse(fake.made)
        self.assertEqual(fake.answered, [(A, "deny")], "the only card it answered, it refused")
        self.assertEqual(fake.config["meeting_limits"]["daily_usd"], 0.45)

    def test_it_prints_none_of_what_a_model_wrote_nor_the_token(self):
        code, lines, fake = self.run_main()
        text = "\n".join(lines)
        self.assertEqual(code, 0, lines)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("echo qa41", text)
        self.assertNotIn("FAKE", text)

    def test_the_order_of_the_turns_follows_what_the_plan_says(self):
        code, lines, fake = self.run_main()
        self.assertEqual(code, 0, lines)
        self.assertEqual([(p, r) for p, _, r in fake.sent], [(A, 1), (B, 1), (B, 2), (A, 3), (B, 3), (A, 4), (A, 5), (B, 5), (A, 6)])
        self.assertTrue(lines[[i for i, l in enumerate(lines) if "turns by stage" in l][0]].endswith("create 0, round 2, mention 3, card 1, limit 2, stop 1)"), lines[-3])

    def test_until_create_makes_the_group_asks_nothing_and_leaves_it_for_the_next_run(self):
        code, lines, fake = self.run_main("--until", "create")
        self.assertEqual(code, 0, lines)
        self.assertEqual(fake.sent, [])
        self.assertTrue(fake.made)
        self.assertTrue(any(f"--group {GID}" in l for l in lines), lines)
        lines2 = []
        code2 = qa.main(["--state", str(fake.state), "--port", str(CONSOLE_AT), "--group", GID], out=lines2.append, console_factory=lambda port, token: fake, **self.time())
        self.assertEqual((code2, self.fails(lines2)), (0, []), lines2)
        self.assertTrue(any("taken over" in l for l in lines2), lines2)
        self.assertFalse(fake.made)

    def test_a_model_that_did_not_ask_for_the_command_is_a_warning_not_a_failure(self):
        code, lines, fake = self.run_main(no_card=True)
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertTrue(any(l.startswith("warn the model did not ask for the command") for l in lines), lines)
        self.assertEqual(fake.answered, [])


class FailureTests(Harness):
    def assertFailsWith(self, phrase, **flaws):
        code, lines, _ = self.run_main(**flaws)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL") and phrase in l for l in lines), (phrase, lines))
        self.assertTrue(lines[-1].startswith("qa_p41: FAIL"), lines[-1])

    def test_a_asked_when_only_b_was_named(self):
        self.assertFailsWith("only B's chat got a message", extra_ask_on_named=True)

    def test_a_message_with_no_markers(self):
        self.assertFailsWith("B's message holds the conversation as one JSON string", no_markers=True)

    def test_data_with_no_sentence_that_says_it_is_data(self):
        self.assertFailsWith("and says it is data, not an instruction", no_data_sentence=True)

    def test_the_round_going_on_after_the_limit_came_down(self):
        self.assertFailsWith("the round paused at the daily limit", ignore_limit=True)

    def test_a_key_added_to_config_json(self):
        self.assertFailsWith("config.json is as it was before", config_extra_key=True)

    def test_the_groups_fixed_words_sent_every_time(self):
        self.assertFailsWith("has not got the group's fixed words again", intro_every_time=True)

    def test_a_file_written_although_the_card_was_refused(self):
        self.assertFailsWith("A's work folder has no such file", writes_file=True)

    def test_the_groups_chats_in_the_chat_list(self):
        self.assertFailsWith("are not in the chat list", lists_group_chats=True)

    def test_too_much_spent(self):
        self.assertFailsWith("within the allowance", ledger_extra=0.5)

    def test_a_ledger_that_goes_down_when_the_group_is_deleted(self):
        self.assertFailsWith("the ledger did not go down", spend_drops=True)


if __name__ == "__main__":
    unittest.main()
