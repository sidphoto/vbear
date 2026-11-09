"""P46-6: tools/qa_p46.py, the coordinator's real-machine check of the AGY chat, must refuse to run against the person's VBear (its folder, anything
under it, ports 7788 and 7789), under /tmp or $TMPDIR, or with a Claude cap above US$0.30; print none of what a model wrote and not the access token;
pass over a console that behaves; and FAIL over one that does not (AGY not ready; a new AGY card whose memory is on; a command with no card; a card for a
place outside the work folder; a changed content that is not asked again; a memory that opens without the yes to Google; a shared folder that opens to
an AGY employee; a group notice with no Google; a team template card that is not safe; a kind of record that v0.19.0 did not have; Claude's part over the
cap, which is then not run at all; a conversation that was not resumed).
Nothing here starts a console, a model or a program: the console is a small in-memory fake that answers the routes the script calls (the real routes are
walked over HTTP by tests/test_p46_flow.py). Everything here is made up.

Seams: ``qa_p46.main`` (the command line, with that console), ``refusal``, ``claude_spent``, ``claude_allowed``, ``kinds_in``, ``watched`` and ``differs``."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("qa_p46", Path(__file__).resolve().parent.parent / "tools" / "qa_p46.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

TOKEN = "synthetic-token-never-printed"
MODEL_WORDS = "MODEL-WORDS-never-printed"
CHAT_RE = re.compile(r"^/api/chats/(c-[0-9a-f]{16})(?:/(messages|answer|stop))?(?:\?after=(\d+))?$")
GROUP_RE = re.compile(r"^/api/groups/(g-[0-9a-f]{12})(?:/(messages))?$")


class FakeConsole(qa.Console):
    """The routes the script calls, in memory. ``flaws`` are the ways it misbehaves (a set of names)."""

    def __init__(self, state: Path, flaws=(), **extra):
        super().__init__(7801, TOKEN)
        self.state, self.flaws, self.extra = Path(state), set(flaws), extra
        self.config = {"chat_limits": {"per_turn_usd": 0.25}, "setup_done": True}
        self.write_config()
        self.cards, self.chats, self.groups, self.routines = {}, {}, {}, {}
        self.memory_on, self.memory_entries, self.shared_on = {}, {}, {}
        self.spent_agy, self.spent_claude = 0.0, extra.get("claude_before", 0.0)
        self.applied = {}
        self.log = []
        self.n = 0
        self.limit_log = []

    # -- helpers ---------------------------------------------------------------------------------------------------------------

    def write_config(self):
        (self.state / "config.json").write_text(json.dumps(self.config, sort_keys=True))

    def new_id(self, prefix, width):
        self.n += 1
        return prefix + format(self.n, f"0{width}x")

    def tool_of(self, pid):
        return (self.cards[pid].get("model") or {}).get("tool")

    def engine_of(self, pid):
        return "agy-chat" if self.tool_of(pid) == "agy" else "claude-chat"

    def events(self, chat_id):
        folder = self.state / "chats" / chat_id
        folder.mkdir(parents=True, exist_ok=True)
        kinds = [r["kind"] for r in self.chats[chat_id]["records"]]
        if "extra_kind" in self.flaws:
            kinds.append("made_up_kind")
        (folder / "events.jsonl").write_text("\n".join(json.dumps({"kind": k}) for k in kinds))

    # -- the one entry point ---------------------------------------------------------------------------------------------------

    def call(self, path, method="GET", body=None):
        self.log.append((method, path.split("?")[0]))
        clean = path.split("?")[0]
        body = body if isinstance(body, dict) else {}
        fixed = {("GET", "/api/chat-support"): self.support, ("GET", "/api/settings/autonomy"): lambda: (200, {"autonomy": {k: False for k in ("a", "b", "c", "d")}}),
                 ("GET", "/api/meetings/ledger"): self.ledger, ("GET", "/api/config"): lambda: (200, {"config": json.loads(json.dumps(self.config))}),
                 ("GET", "/api/agent-profiles"): lambda: (200, {"profiles": [dict(c, id=i) for i, c in self.cards.items()]}),
                 ("GET", "/api/memory"): lambda: (200, {"cards": self.card_rows(self.memory_on), "used": {"count": len(self.memory_entries)}}),
                 ("GET", "/api/shared"): lambda: (200, {"cards": self.card_rows(self.shared_on, shared=True)}),
                 ("GET", "/api/chats"): lambda: (200, {"chats": [{"id": c} for c in self.chats]})}
        if (method, clean) in fixed:
            return fixed[(method, clean)]()
        if method == "POST":
            posts = {"/api/config": self.post_config, "/api/agent-profiles": self.make_card, "/api/chats": self.open_chat,
                     "/api/memory/cards": self.memory_card, "/api/memory": self.memory_add, "/api/shared/cards": self.shared_card,
                     "/api/groups": self.make_group, "/api/routines": self.make_routine, "/api/templates/preview": self.template_preview,
                     "/api/templates/apply": self.template_apply, "/api/memory/suggest/preview": self.suggest_preview,
                     "/api/memory/suggest": lambda b: (202, {"id": "s-1"}), "/api/meetings/verify": lambda b: (200, {"ok": True})}
            if clean in posts:
                return posts[clean](body)
        found = CHAT_RE.match(path)
        if found:
            return self.chat_route(found.group(1), found.group(2), method, body, found.group(3))
        found = GROUP_RE.match(path)
        if found:
            return self.group_route(found.group(1), found.group(2), method, body)
        if method == "GET" and clean == "/api/memory/suggest/s-1":
            return 200, {"status": "ready", "items": []}
        if clean.startswith("/api/agent-profiles/") and clean.endswith("/delete"):
            self.cards.pop(clean.split("/")[3], None)
            return 200, {"ok": True}
        if clean.startswith("/api/routines/") and clean.endswith("/delete"):
            self.routines.pop(clean.split("/")[3], None)
            return 200, {"ok": True}
        if clean.startswith("/api/memory/") and method == "DELETE":
            self.memory_entries.pop(clean.split("/")[3], None)
            return 200, {"ok": True}
        if clean.startswith("/api/templates/applies/"):
            return self.template_undo(clean, body)
        return 404, {"error": "not found", "code": "not_found"}

    # -- reads -----------------------------------------------------------------------------------------------------------------

    def support(self):
        if "agy_not_ready" in self.flaws:
            agy = {"state": "unverified", "version": "1.5.3", "verified": False}
        else:
            agy = {"state": "ready", "version": "1.5.3", "verified": True}
        return 200, {"state": "verified", "agy": agy}

    def ledger(self):
        return 200, {"spent_usd": str(round(self.spent_agy + self.spent_claude, 4))}

    def card_rows(self, switches, shared=False):
        rows = []
        for pid in self.cards:
            tool = self.tool_of(pid)
            on = switches.get(pid, tool == "claude" and not shared)
            if "memory_default_on" in self.flaws and not shared and tool == "agy":
                on = True
            rows.append({"profile_id": pid, "tool": tool, "on": on, "company": None if shared else {"agy": "Google"}.get(tool, "Anthropic")})
        return rows

    # -- writes ----------------------------------------------------------------------------------------------------------------

    def post_config(self, body):
        self.config["chat_limits"] = dict(body["chat_limits"])
        self.limit_log.append(body["chat_limits"]["per_turn_usd"])
        if "forget_limit" not in self.flaws or body["chat_limits"]["per_turn_usd"] != 0.25:
            self.write_config()
        return 200, {"ok": True}

    def make_card(self, body):
        pid = "p-" + str(len(self.cards) + 1)
        self.cards[pid] = dict(body)
        return 201, {"profile": {"id": pid}}

    def memory_card(self, body):
        pid = body["profile_id"]
        if body["on"] and self.tool_of(pid) == "agy" and body.get("confirm_company") is not True and "memory_no_yes" not in self.flaws:
            return 409, {"code": "memory_confirm", "warn": ["send_to_openai" if "wrong_company" in self.flaws else "send_to_google"], "error": "x"}
        self.memory_on[pid] = bool(body["on"])
        return 200, {"ok": True, "on": bool(body["on"])}

    def memory_add(self, body):
        eid = "m-" + str(len(self.memory_entries) + 1)
        self.memory_entries[eid] = body["text"]
        return 201, {"entry": {"id": eid}}

    def shared_card(self, body):
        pid = body["profile_id"]
        if "shared_opens" in self.flaws:
            self.shared_on[pid] = True
            return 200, {"ok": True}
        return 400, {"code": "card_tool_unsupported", "error": "AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查。"}

    def make_routine(self, body):
        rid = "r-" + str(len(self.routines) + 1)
        self.routines[rid] = body
        return 201, {"routine": {"id": rid}}

    def suggest_preview(self, body):
        notice = "這是和 AGY 員工的對話，也會送給 Anthropic（Claude Code）整理。"
        if "no_notice" in self.flaws:
            notice = ""
        return 200, {"ok": True, "sends_to": "Anthropic", "cap_usd": "0.10", "preview_id": "pv-1", "notice": notice}

    def template_preview(self, body):
        return 200, {"preview": {"ok": True, "cards": [{"key": "coach"}], "skills": [], "routines": [], "problems": []}}

    def template_apply(self, body):
        pid = "p-" + str(len(self.cards) + 1)
        mode = "full" if "template_full" in self.flaws else "safe"
        self.cards[pid] = {"launch_mode": mode, "model": {"tool": "agy", "model_id": ""}, "equipped_skill_ids": []}
        self.applied["ta-1"] = pid
        if "template_touches_memory" in self.flaws:
            (self.state / "memory").mkdir(exist_ok=True)
            (self.state / "memory" / "memory.json").write_text(json.dumps({"x": len(self.cards)}))
        return 201, {"apply": {"id": "ta-1", "items": [{"kind": "card", "state": "made", "id": pid}]}}

    def template_undo(self, clean, body):
        pid = self.applied["ta-1"]
        if clean.endswith("/undo-preview"):
            return 200, {"delete": [{"id": pid}], "keep": []}
        self.cards.pop(pid, None)
        return 200, {"deleted": [{"id": pid}], "kept": []}

    # -- chats -----------------------------------------------------------------------------------------------------------------

    def open_chat(self, body):
        cid = "c-" + format(len(self.chats) + 1, "016x")
        self.chats[cid] = {"pid": body["profile_id"], "records": [{"kind": "chat_created"}], "cards": [], "turn": 0, "pending": None, "word": None,
                           "closed": False, "memory_word": None}
        self.events(cid)
        return 201, {"chat": {"id": cid}}

    def end(self, chat, reason="result", cost=None):
        agy = self.engine_of(chat["pid"]) == "agy-chat"
        rec = {"kind": "turn_ended", "turn": chat["turn"], "reason": reason}
        if agy:
            rec.update(estimate=True, tokens=86000, cost_usd="0.09")
            self.spent_agy += 0.09
        else:
            rec.update(cost_usd="0.002")
            self.spent_claude += 0.002 + self.extra.get("claude_per_turn", 0.0)
        chat["records"].append(rec)
        chat["pending"] = None

    def start_turn(self, chat):
        chat["turn"] += 1
        chat["records"].append({"kind": "user_message", "turn": chat["turn"], "text": "x"})

    def add_card(self, chat, tool, inp):
        card = {"card_id": f"k-{chat['turn']}-{len(chat['cards'])}", "token": "t", "tool": tool, "input": inp}
        chat["cards"].append(card)
        chat["records"].append({"kind": "card", "turn": chat["turn"], "tool": tool, "input": inp})

    def chat_route(self, cid, action, method, body, after):
        chat = self.chats.get(cid)
        if chat is None:
            return 404, {"code": "not_found"}
        if method == "DELETE":
            del self.chats[cid]
            return 200, {"deleted": cid}
        if action == "messages":
            return self.message(chat, body["text"])
        if action == "answer":
            return self.answered(chat, body)
        if action == "stop":
            if chat["pending"] == "sleep":
                self.end(chat, "stopped")
                chat["closed"] = True
            return 200, {"stopped": True}
        records = [] if after and int(after) >= qa.PAST_THE_END else list(chat["records"])
        self.events(cid)
        return 200, {"records": records, "more": False, "next_after": 0, "live": {"cards": list(chat["cards"])}}

    def message(self, chat, text):
        process = "resume" if chat["closed"] and "no_resume" not in self.flaws else "new"
        chat["closed"] = False
        self.start_turn(chat)
        agy = self.engine_of(chat["pid"]) == "agy-chat"
        outside = str(self.state.parent) in text and "qa46-outside" in text
        if agy and "ls -a" in text and "no_command_card" not in self.flaws:
            self.add_card(chat, "command", {"command": "ls -a", "cwd": "."})
            chat["pending"] = "ls"
        elif agy and "qa46-outside" in text:
            if "outside_card" in self.flaws:
                self.add_card(chat, "file_change", {"changes": [{"path": "qa46-outside.txt", "kind": "add", "diff": "+QA46"}]})
                chat["pending"] = "outside"
            else:
                chat["records"].append({"kind": "denied", "turn": chat["turn"], "by": "vbear", "tool": "file_change"})
                self.end(chat)
        elif agy and "qa46.txt" in text:
            self.add_card(chat, "file_change", {"changes": [{"path": "qa46.txt", "kind": "add", "diff": "+QA46"}]})
            chat["pending"] = "file"
        elif agy and "edit46.txt" in text:
            self.add_card(chat, "file_change", {"changes": [{"path": "edit46.txt", "kind": "add", "diff": "+original"}]})
            chat["pending"] = "edit"
        elif agy and "sleep 30" in text:
            self.add_card(chat, "command", {"command": "sleep 30", "cwd": "."})
            chat["pending"] = "sleep"
        else:
            if "記住代號" in text:
                chat["word"] = re.search(r"QA46-[0-9a-f]+", text).group(0)
            reply = "不知道"
            if "代號是什麼" in text and chat["word"] and "no_resume" not in self.flaws:
                reply = chat["word"]
            if "暗號是什麼" in text:
                memory = [t for t in self.memory_entries.values()]
                if memory and self.memory_on.get(chat["pid"]):
                    reply = memory[0]
            chat["records"].append({"kind": "reply", "turn": chat["turn"], "text": reply + MODEL_WORDS})
            self.end(chat)
        return 202, {"ok": True, "turn": chat["turn"], "process": process}

    def answered(self, chat, body):
        card = next((c for c in chat["cards"] if c["card_id"] == body["card_id"]), None)
        chat["cards"] = [c for c in chat["cards"] if c is not card]
        pending, decision = chat["pending"], body["decision"]
        if pending == "edit" and decision == "modify":
            self.end(chat)
            self.start_turn(chat)
            changed = body.get("value") if "edit_not_asked" not in self.flaws else None
            if changed is not None:
                self.add_card(chat, "file_change", {"changes": [{"path": "edit46.txt", "kind": "add", "diff": "+" + changed}]})
                chat["pending"] = "edit2"
            else:
                self.end(chat)
        elif pending == "sleep":
            pass                                          # allowed: it keeps running until it is stopped
        elif pending in ("ls", "file", "edit2", "outside") and decision == "allow":
            chat["records"].append({"kind": "tool_result", "turn": chat["turn"], "is_error": False})
            self.end(chat)
        else:
            self.end(chat)
        return 200, {"ok": True}

    # -- groups ----------------------------------------------------------------------------------------------------------------

    def make_group(self, body):
        gid = "g-" + format(len(self.groups) + 1, "012x")
        chats = {}
        for pid in body["profile_ids"]:
            chats[pid] = self.open_chat({"profile_id": pid})[1]["chat"]["id"]
        self.groups[gid] = {"ids": body["profile_ids"], "chats": chats, "state": "idle", "items": []}
        tools = {self.tool_of(p) for p in body["profile_ids"]}
        notes = []
        if len(tools) > 1:
            notes = ["群組裡有 Claude Code 和 AGY 的員工，群組裡的對話會同時送給 Anthropic 和 " + ("OpenAI" if "no_google" in self.flaws else "Google") + "。"]
        return 201, {"group": {"id": gid}, "notes": notes}

    def group_route(self, gid, action, method, body):
        group = self.groups.get(gid)
        if group is None:
            return 404, {"code": "not_found"}
        if method == "DELETE":
            for cid in group["chats"].values():
                self.chats.pop(cid, None)
            del self.groups[gid]
            return 200, {"ok": True}
        if action == "messages":
            for pid, cid in group["chats"].items():
                self.message(self.chats[cid], "（虛構）大家請各自只回答：QA46 ok")
                if "one_silent" not in self.flaws or self.tool_of(pid) != "claude":
                    group["items"].append({"kind": "reply", "profile_id": pid})
            return 202, {"ok": True, "round": {"n": 1}}
        last = list(group["chats"].values())[-1]
        return 200, {"group": {"state": group["state"]}, "current": {"chat_id": last}, "items": group["items"]}


class Base(unittest.TestCase):
    def setUp(self):
        # the state folder is under the home folder of the test, which is under /tmp: the refusal for /tmp is switched off with an empty temp-root list
        self.root = Path(tempfile.mkdtemp(prefix="vq46-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = self.root / "s"
        self.state.mkdir()
        (self.state / "server.token").write_text(json.dumps({"port": 7801, "token": TOKEN}))
        self.lines = []
        self.now = [0.0]
        self.other_home = self.root / "somebody-else"
        self.other_home.mkdir()
        old = qa._temp_roots
        qa._temp_roots = lambda: []
        self.addCleanup(setattr, qa, "_temp_roots", old)

    def run_qa(self, *args, flaws=(), state=None, port=7801, **extra):
        self.fake = FakeConsole(self.state, flaws, **extra)
        argv = ["--state", str(state or self.state), "--port", str(port), *args]
        return qa.main(argv, out=self.lines.append, console_factory=lambda p, t: self.fake, clock=lambda: self.now[0],
                       sleep=lambda s: self.now.__setitem__(0, self.now[0] + s), home=self.other_home, rand=lambda n: "ab12cd34"[:n * 2])

    def text(self):
        return "\n".join(self.lines)

    def failed(self, needle):
        return [l for l in self.lines if l.startswith("FAIL") and needle in l]

    def assert_fails(self, code, needle):
        self.assertEqual(code, 1, self.text())
        self.assertTrue(self.failed(needle), f"no FAIL with {needle!r}:\n{self.text()}")


class PassesOverAConsoleThatBehaves(Base):
    def test_every_stage_passes_cleans_up_and_prints_a_summary(self):
        code = self.run_qa()
        self.assertEqual(code, 0, self.text())
        self.assertRegex(self.lines[-1], r"^qa_p46: PASS \(\d+ ok, \d+ warn, 0 FAIL\)$")
        self.assertFalse([l for l in self.lines if l.startswith("FAIL")])
        self.assertEqual((self.fake.cards, self.fake.chats, self.fake.groups, self.fake.routines), ({}, {}, {}, {}), "what the script made is deleted")
        self.assertEqual(self.fake.memory_entries, {})
        self.assertEqual(self.fake.config["chat_limits"]["per_turn_usd"], 0.25, "the per-turn limit is back")
        self.assertIn(0.05, self.fake.limit_log, "a Claude stage ran with the lower limit")
        self.assertIn("AGY estimate", self.text())
        self.assertIn("Claude US$", self.text())

    def test_it_prints_nothing_a_model_wrote_and_not_the_token_and_the_memo_holds_only_ids(self):
        self.run_qa()
        self.assertNotIn(MODEL_WORDS, self.text())
        self.assertNotIn(TOKEN, self.text())
        memo = (self.root / "qa46.json").read_text(encoding="utf-8")
        self.assertNotIn(TOKEN, memo)
        for word in ("QA46 虛構", "暗號", MODEL_WORDS):
            self.assertNotIn(word, memo, word)

    def test_the_agy_estimates_are_counted_and_are_not_claudes_money(self):
        self.run_qa()
        self.assertGreater(self.fake.spent_agy, 0.5)
        self.assertRegex(self.text(), r"Claude US\$0\.0\d+ \(cap US\$0\.30\)")

    def test_it_can_be_stopped_early_and_still_cleans_up(self):
        self.assertEqual(self.run_qa("--until", "command"), 0, self.text())
        self.assertEqual((self.fake.cards, self.fake.chats), ({}, {}))
        self.assertEqual(self.fake.limit_log, [], "no Claude stage, no change of the limit")

    def test_a_stage_can_be_left_out(self):
        self.assertEqual(self.run_qa("--skip", "suggest"), 0, self.text())
        self.assertNotIn(("POST", "/api/memory/suggest/preview"), self.fake.log)

    def test_the_shared_stage_expects_the_refusal_not_the_yes(self):
        self.run_qa()
        self.assertIn(("POST", "/api/shared/cards"), self.fake.log)
        self.assertTrue([l for l in self.lines if l.startswith("ok") and "not open to an AGY employee" in l])


class FailsOverAConsoleThatDoesNot(Base):
    def test_agy_that_is_not_ready_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"agy_not_ready"}), "AGY is ready")

    def test_a_new_agy_card_whose_memory_is_on_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"memory_default_on"}), "switched off (the default)")

    def test_a_command_that_comes_without_a_card_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"no_command_card"}), "command card")

    def test_a_card_for_a_place_outside_the_work_folder_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"outside_card"}), "no file card for a place outside")

    def test_a_changed_content_that_is_not_asked_again_is_a_fail(self):
        code = self.run_qa(flaws={"edit_not_asked"})
        self.assertEqual(code, 1, self.text())
        self.assertTrue([l for l in self.lines if l.startswith("FAIL")], self.text())

    def test_a_memory_that_opens_without_the_yes_to_google_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"memory_no_yes"}), "without the yes is 409")

    def test_a_memory_confirm_that_names_the_wrong_company_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"wrong_company"}), "send_to_google")

    def test_a_shared_folder_that_opens_to_an_agy_employee_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"shared_opens"}), "not open to an AGY employee")

    def test_a_group_notice_without_google_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"no_google"}), "names Anthropic and Google")

    def test_a_group_where_one_does_not_answer_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"one_silent"}), "both the AGY employee and the Claude employee answered")

    def test_a_preview_that_does_not_say_anthropic_too_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"no_notice"}), "goes to Anthropic too")

    def test_a_team_template_card_that_is_full_mode_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"template_full"}), "the new employee is safe")

    def test_a_template_apply_that_touches_the_memory_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"template_touches_memory"}), "same bytes after the apply")

    def test_a_kind_of_record_v0190_did_not_have_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"extra_kind"}), "every kind of record")

    def test_a_conversation_that_was_not_resumed_is_a_fail(self):
        self.assert_fails(self.run_qa(flaws={"no_resume"}), "the reply holds the code word")

    def test_a_per_turn_limit_that_was_not_put_back_is_a_fail(self):
        code = self.run_qa(flaws={"forget_limit"})
        self.assertEqual(code, 1, self.text())

    def test_claude_over_the_cap_is_not_run_and_is_a_fail(self):
        code = self.run_qa(claude_before=0.30)
        self.assert_fails(code, "Claude's part would go over US$0.30")
        self.assertNotIn(("POST", "/api/groups"), self.fake.log, "the group stage did not start")
        self.assertNotIn(("POST", "/api/memory/suggest/preview"), self.fake.log)
        self.assertEqual(self.fake.limit_log, [], "the limit was not lowered for a stage that did not run")

    def test_a_lower_cap_stops_the_second_claude_stage(self):
        code = self.run_qa("--claude-cap", "0.12", claude_before=0.01)
        self.assertEqual(code, 1, self.text())
        self.assertTrue(self.failed("would go over US$0.12"), self.text())

    def test_claude_that_spends_more_than_it_may_is_a_fail_at_the_end(self):
        self.assert_fails(self.run_qa(claude_per_turn=0.2, claude_before=0.0, **{}), "within the cap")


class Refuses(Base):
    def test_port_7788_and_7789(self):
        for port in (7788, 7789):
            self.lines.clear()
            self.assertEqual(self.run_qa(port=port), 2)
            self.assertIn("person's own VBear", self.text())
        self.assertEqual(self.fake.log, [], "nothing was called")

    def test_a_state_folder_that_is_the_persons_own_or_inside_it(self):
        own = self.other_home / ".vbear"
        (own / "x").mkdir(parents=True)
        for state in (own, own / "x"):
            self.lines.clear()
            self.assertEqual(self.run_qa(state=state), 2)
            self.assertIn("own VBear folder", self.text())

    def test_a_state_folder_that_does_not_exist(self):
        self.assertEqual(self.run_qa(state=self.root / "nowhere"), 2)

    def test_a_state_folder_under_a_temporary_folder(self):
        qa._temp_roots = lambda: [Path("/tmp").resolve(), Path("/private/tmp").resolve()]
        self.assertEqual(self.run_qa(), 2)
        self.assertIn("/tmp", self.text())

    def test_a_claude_cap_above_30_cents_or_not_above_zero(self):
        for cap in ("0.5", "0.31", "0", "-1"):
            self.lines.clear()
            self.assertEqual(self.run_qa("--claude-cap", cap), 2, cap)
            self.assertIn("--claude-cap", self.text())

    def test_from_after_until(self):
        self.assertEqual(self.run_qa("--from", "final", "--until", "card"), 2)

    def test_a_start_in_the_middle_without_the_notes(self):
        code = self.run_qa("--from", "command")
        self.assertEqual(code, 1)
        self.assertTrue(self.failed("qa46.json"), self.text())


class PureHelpers(unittest.TestCase):
    def test_the_money_rule(self):
        self.assertAlmostEqual(qa.claude_spent(1.00, 0.90), 0.10 + qa.CHAT_CHECK_RESERVE)
        self.assertEqual(qa.claude_spent(0.10, 0.90), qa.CHAT_CHECK_RESERVE, "the AGY estimate cannot make Claude's part negative")
        self.assertIsNone(qa.claude_spent(None, 0.0))
        self.assertTrue(qa.claude_allowed(0.10, 0.10, 0.30))
        self.assertFalse(qa.claude_allowed(0.21, 0.10, 0.30))
        self.assertFalse(qa.claude_allowed(None, 0.05, 0.30), "unknown is no")

    def test_the_cap_of_the_plan_is_30_cents(self):
        self.assertEqual(qa.CLAUDE_CAP_MAX, 0.30)
        self.assertEqual(qa.DEFAULT_PORT, 7801)
        self.assertEqual(qa.FORBIDDEN_PORTS, (7788, 7789))

    def test_the_kinds_of_v0190_are_the_ones_of_the_chat_store_of_that_release(self):
        from vbear.runtime import chat_store
        self.assertEqual(qa.V019_KINDS, frozenset(chat_store.KINDS), "P46 added no kind of record")

    def test_a_card_text_is_json_of_its_input(self):
        self.assertIn("ls", qa.card_text({"input": {"command": "ls -a"}}))
        self.assertEqual(qa.card_text({"input": object()}), "")


if __name__ == "__main__":
    unittest.main()
