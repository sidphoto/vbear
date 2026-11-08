"""P45-4: tools/qa_p45.py, the coordinator's real-machine check of the team templates, must refuse to run without a state folder, never aim at
the person's VBear (its folder, anything under it, ports 7788 and 7789), print none of what a model wrote and not the access token, pass over a
console that behaves, and FAIL over one that does not (a built-in team template missing; a preview that wrote; an employee that is not the safe
mode; a routine that is on; an apply that opened a chat; config.json changed; an employee that is not Haiku, which is then not sent anything;
an undo that deletes the employee who was talked to; a saved employee with a tool; a name in the record or the log; too much spent; a turn that
does not end well; a start in the middle without the notes).
Nothing here starts a console, a model or a program: the cards, the skills, the routines and the team templates are the real ones, served by
the real routes of a loopback server over a temporary home (the same one the tests of the apply use); only the chat, the ledger and the ticks
of 「自己動手」 are small fakes in the test.

Seams: ``qa_p45.main`` (the command line, with that console), ``refusal``, ``card_problems``, ``list_problems``, ``differs``, ``watched``,
``names_in`` and ``counts_of``."""
from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path

from tests import templates_apply_fixtures as fx
from vbear import agent_profiles as ap

SPEC = importlib.util.spec_from_file_location("qa_p45", Path(__file__).resolve().parent.parent / "tools" / "qa_p45.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

TOKEN = "synthetic-token-never-printed"
MODEL_WORDS = "MODEL-WORDS-never-printed"
CHAT_RE = re.compile(r"^/api/chats/(c-[0-9a-f]{16})(?:\?after=(\d+))?$")


class FakeConsole(qa.Console):
    """The console the script talks to: the templates, cards, skills and routines are the real routes of the test's server; the chat, the
    ledger and the ticks are here. ``flaws`` are the ways it misbehaves."""

    def __init__(self, test, port, **flaws):
        super().__init__(port, TOKEN)
        self.t, self.flaws = test, flaws
        self.spent, self.chats, self.messages, self.records = 0.0, {}, 0, {}
        self.ticks = {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": False}
        self.after = []                                   # side effects after a path was answered: (path-prefix, function)

    def hook(self, name, *args):
        fn = self.flaws.get(name)
        return fn(self, *args) if fn else None

    def call(self, path, method="GET", body=None):
        clean = path.split("?")[0]
        if clean == "/api/settings/autonomy":
            return 200, {"ok": True, "autonomy": dict(self.ticks)}
        if clean == "/api/meetings/ledger":
            return 200, {"ok": True, "spent_usd": str(self.flaws.get("spent", self.spent))}
        if clean == "/api/chats":
            if method == "GET":
                return 200, {"ok": True, "chats": [{"id": c} for c in self.chats]}
            return self.open_chat(body)
        found = CHAT_RE.match(path)
        if found or clean.endswith("/messages") or clean.endswith("/answer"):
            return self.chat_call(path, method, body)
        replaced = self.hook("replace", clean, method, body)
        if replaced:
            return replaced
        self.hook("before", clean, method, body)
        status, data = self.t.call(path, method, body)
        out = self.hook("after", clean, method, status, data)
        return out if out else (status, data)

    # -- the chat -------------------------------------------------------------------------------------------------------------

    def open_chat(self, body):
        chat_id = "c-" + format(len(self.chats) + 1, "016x")
        self.chats[chat_id] = body.get("profile_id")
        self.records[chat_id] = []
        if not self.flaws.get("no_record"):
            self.t.put(f"chats/{chat_id}/chat.json", {"id": chat_id, "profile_id": body.get("profile_id")})
        self.hook("opened", chat_id)
        return 201, {"ok": True, "chat": {"id": chat_id}}

    def chat_call(self, path, method, body):
        found = CHAT_RE.match(path)
        if method == "POST" and path.endswith("/messages"):
            chat_id = path.split("/")[3]
            self.messages += 1
            if not self.flaws.get("never_ends"):
                reason = self.flaws.get("reason", "result")
                self.records[chat_id] = [{"kind": "reply", "turn": 1, "text": MODEL_WORDS}, {"kind": "turn_ended", "turn": 1, "reason": reason}]
            self.spent += 0.002
            return 202, {"ok": True, "turn": 1}
        if method == "POST":
            return 200, {"ok": True}
        chat_id, after = found.group(1), int(found.group(2) or 0)
        if after >= qa.PAST_THE_END:
            return 200, {"ok": True, "live": {"cards": []}}
        return 200, {"ok": True, "records": self.records.get(chat_id, []), "more": False, "next_after": 0}


class QaBase(fx.ApplyBase):
    def setUp(self):
        super().setUp()
        self.lines = []
        self.clock_now = [0.0]
        self.other_home = self.home.parent / "somebody-else"
        self.other_home.mkdir()

    def sleeper(self, seconds):
        self.clock_now[0] += seconds

    def run_qa(self, *args, port=None, state=None, home=None, **flaws):
        self.console_fake = FakeConsole(self, self.console.port, **flaws)
        (self.state / "server.token").write_text(json.dumps({"port": self.console.port, "token": TOKEN}))
        argv = ["--state", str(state or self.state), "--port", str(port or self.console.port), *args]
        code = qa.main(argv, out=self.lines.append, console_factory=lambda port_, token: self.console_fake, clock=lambda: self.clock_now[0],
                       sleep=self.sleeper, home=home or self.other_home)
        return code

    def text(self):
        return "\n".join(self.lines)

    def failed(self, needle):
        return [l for l in self.lines if l.startswith("FAIL") and needle in l]

    def assert_fails(self, code, needle):
        self.assertEqual(code, 1, self.text())
        self.assertTrue(self.failed(needle), f"no FAIL with {needle!r}:\n{self.text()}")

    def nothing_left(self):
        self.assertEqual((self.stored_cards(), self.stored_skills(), self.stored_routines()), ({}, {}, {}), "the script deleted what it made")


class PassesOverAConsoleThatBehaves(QaBase):
    def test_every_stage_passes_and_cleans_up(self):
        code = self.run_qa()
        self.assertEqual(code, 0, self.text())
        self.assertRegex(self.lines[-1], r"^qa_p45: PASS \(\d+ ok, 0 warn, 0 FAIL\)$")
        self.assertFalse([l for l in self.lines if l.startswith("FAIL")])
        self.assertEqual(self.console_fake.messages, 1, "one turn, one sentence")
        self.assertEqual(len(self.console_fake.chats), 1)
        self.assertIn("1 turn(s)", self.text())
        self.assertEqual(set(self.stored_cards()), set(), "what the apply and the undo left was deleted at the end")
        self.nothing_left()
        self.assertEqual(self.call("/api/templates")[1]["mine"], [], "its own team template was deleted")
        self.assert_watched_unchanged()
        self.assertEqual(set(self.chats.calls) - {"cards"}, set())

    def test_it_prints_nothing_a_model_wrote_and_not_the_token_and_the_memo_holds_only_ids(self):
        self.run_qa()
        self.assertNotIn(MODEL_WORDS, self.text())
        self.assertNotIn(TOKEN, self.text())
        memo = (self.home / "qa45.json").read_text(encoding="utf-8")
        self.assertNotIn(TOKEN, memo)
        for word in ("客服", "商品文案", "會計", "寫稿", "QA45", "你是這家小店"):
            self.assertNotIn(word, memo, word)
        self.assertIn("ta-", memo)

    def test_it_can_be_run_in_two_parts(self):
        self.assertEqual(self.run_qa("--until", "preview"), 0, self.text())
        self.assertEqual(self.console_fake.messages, 0, "no model before the apply and the chat")
        self.nothing_left()
        self.lines.clear()
        self.assertEqual(self.run_qa("--from", "apply"), 0, self.text())
        self.assertEqual(self.console_fake.messages, 1)
        self.nothing_left()

    def test_a_stage_after_setup_needs_the_notes_of_setup(self):
        code = self.run_qa("--from", "apply")
        self.assertEqual(code, 1, self.text())
        self.assertTrue(self.failed("no qa45.json"), self.text())
        self.assertEqual(self.console_fake.messages, 0)

    def test_a_run_that_stops_before_the_end_still_deletes_what_it_made(self):
        self.assertEqual(self.run_qa("--until", "undo-preview"), 0, self.text())     # the apply and its chat are there, then final deletes them
        self.nothing_left()
        self.assertTrue(any("deleted with the ordinary routes" in l for l in self.lines), "final ran")


class Refuses(QaBase):
    def test_the_persons_own_ports_and_folders_and_what_does_not_exist(self):
        for port in (7788, 7789, 80):
            self.lines.clear()
            self.assertEqual(self.run_qa(port=port), 2, port)
            self.assertTrue(self.lines[0].startswith("refused:"), self.lines)
        self.lines.clear()
        self.assertEqual(self.run_qa(home=self.home), 2, "the state folder is the person's own ~/.vbear")
        self.assertIn("refused:", self.lines[0])
        self.lines.clear()
        inside = self.state / "templates"
        self.assertEqual(self.run_qa(state=inside, home=self.home), 2, "a folder inside it")
        self.lines.clear()
        self.assertEqual(self.run_qa(state=self.home / "nothing-here"), 2)
        self.assertEqual(self.console_fake.messages, 0)

    def test_from_after_until(self):
        self.assertEqual(self.run_qa("--from", "undo", "--until", "preview"), 2)

    def test_the_pure_refusal(self):
        self.assertIsNone(qa.refusal(str(self.state), 50123, self.other_home))
        self.assertIsNotNone(qa.refusal(str(self.state), 7788, self.other_home))
        self.assertIsNotNone(qa.refusal(str(self.state), 7789, self.other_home))
        self.assertIsNotNone(qa.refusal(str(self.state), 50123, self.home))
        self.assertIsNotNone(qa.refusal(str(self.state), 80, self.other_home))


class FailsOverAConsoleThatDoesNot(QaBase):
    def test_a_built_in_team_template_is_missing(self):
        def drop(console, clean, method, status, data):
            if clean == "/api/templates" and method == "GET" and isinstance(data, dict):
                return status, dict(data, builtin=[t for t in data["builtin"] if t["id"] != "life"])
        self.assert_fails(self.run_qa(after=drop), "built-in team templates")

    def test_the_state_is_not_fresh(self):
        self.call("/api/templates/mine", "POST", {"name": "別人存的", "cards": [fx.pick("shop", "service")]})
        self.assert_fails(self.run_qa(), "none of the person's own")

    def test_an_item_is_ticked_on_in_the_settings(self):
        def tick(console, clean, method, body):
            console.ticks["routines"] = True
        self.assert_fails(self.run_qa(before=tick), "ticks are false")

    def test_a_preview_that_wrote(self):
        def write(console, clean, method, body):
            if clean == "/api/templates/preview":
                ap.save_profile(None, {"name": "不該有的", "model": {"tool": "claude"}})
        self.assert_fails(self.run_qa(before=write), "the preview wrote nothing")

    def test_a_preview_with_the_wrong_counts(self):
        def fewer(console, clean, method, status, data):
            if clean == "/api/templates/preview":
                preview = dict(data["preview"], cards=data["preview"]["cards"][:3])
                return status, dict(data, preview=preview)
        self.assert_fails(self.run_qa(after=fewer), "4 employees, 4 skills and 2 routines")

    def test_a_new_employee_that_is_the_full_mode(self):
        state = {"applied": False}

        def full(console, clean, method, status, data):
            if clean == "/api/templates/apply":
                state["applied"] = True
            if clean == "/api/agent-profiles" and method == "GET" and state["applied"]:
                return status, dict(data, profiles=[dict(p, launch_mode="full") for p in data["profiles"]])
        self.assert_fails(self.run_qa(after=full), "4 new employees")

    def test_a_new_employee_with_a_skill_card(self):
        state = {"applied": False}

        def armed(console, clean, method, status, data):
            if clean == "/api/templates/apply":
                state["applied"] = True
            if clean == "/api/agent-profiles" and method == "GET" and state["applied"]:
                return status, dict(data, profiles=[dict(p, equipped_skill_ids=["x"]) for p in data["profiles"]])
        self.assert_fails(self.run_qa(after=armed), "4 new employees")

    def test_a_routine_that_is_on(self):
        state = {"applied": False}

        def on(console, clean, method, status, data):
            if clean == "/api/templates/apply":
                state["applied"] = True
            if clean == "/api/routines" and method == "GET" and state["applied"]:
                return status, dict(data, routines=[dict(r, enabled=True) for r in data["routines"]])
        self.assert_fails(self.run_qa(after=on), "2 new routines, both off")

    def test_a_routine_that_is_on_at_the_end(self):
        from vbear import routines
        mine = ap.save_profile(None, {"name": "別人的員工", "model": {"tool": "claude"}})
        routines.create({"name": "別人的例行", "profile_id": mine["id"], "text": "請整理虛構的待辦。", "days": [1], "times": ["09:00"], "enabled": True},
                        [{"id": mine["id"], "can_chat": True}])
        self.assert_fails(self.run_qa(), "no routine is on")

    def test_an_apply_that_opened_a_chat(self):
        def chat(console, clean, method, status, data):
            if clean == "/api/templates/apply" and status == 201:
                console.open_chat({"profile_id": "p-old"})
        self.assert_fails(self.run_qa(after=chat), "no chat was opened")

    def test_an_apply_that_spent_money(self):
        def spend(console, clean, method, status, data):
            if clean == "/api/templates/apply" and status == 201:
                console.spent += 0.01
        self.assert_fails(self.run_qa(after=spend), "did not move")

    def test_config_json_that_changed_after_the_apply(self):
        def change(console, clean, method, status, data):
            if clean == "/api/templates/apply" and status == 201:
                (console.t.state / "config.json").write_text('{"port": 1}\n')
        self.assert_fails(self.run_qa(after=change), "config.json, the memory and the shared folder")

    def test_the_memory_or_the_shared_folder_that_changed(self):
        def change(console, clean, method, status, data):
            if clean == "/api/templates/apply" and status == 201:
                (console.t.state / "shared-meta" / "state.json").write_text('{"cards_on": ["x"]}\n')
        self.assert_fails(self.run_qa(after=change), "shared folder")

    def test_an_employee_that_is_not_haiku_is_not_sent_anything(self):
        state = {"applied": False}

        def other(console, clean, method, status, data):
            if clean == "/api/templates/apply":
                state["applied"] = True
            if clean == "/api/agent-profiles" and method == "GET" and state["applied"]:
                return status, dict(data, profiles=[dict(p, model=dict(p["model"], model_id="opus")) if p["name"] == "客服" else p for p in data["profiles"]])
        code = self.run_qa(after=other)
        self.assertEqual(self.console_fake.messages, 0, "nothing was sent")
        self.assertEqual(len(self.console_fake.chats), 0)
        self.assertEqual(code, 1, self.text())
        self.assertTrue(self.failed("haiku"), self.text())

    def test_a_turn_that_does_not_end_with_a_result(self):
        self.assert_fails(self.run_qa(reason="error"), "ended with a result")

    def test_a_turn_that_never_ends_stops_the_run_and_final_still_cleans_up(self):
        code = self.run_qa(never_ends=True)
        self.assert_fails(code, "stopped")
        self.assertTrue(self.failed("timed out"), self.text())
        self.nothing_left()
        self.assertTrue(any("deleted with the ordinary routes" in l for l in self.lines), "final ran")

    def test_an_apply_that_is_refused_stops_the_run(self):
        def refuse(console, clean, method, body):
            if clean == "/api/templates/apply":
                return 409, {"ok": False, "code": "template_full"}
        code = self.run_qa(replace=refuse)
        self.assert_fails(code, "stopped")
        self.assertTrue(self.failed("template_full"), self.text())
        self.nothing_left()

    def test_an_apply_that_stopped_in_the_middle_is_deleted_too(self):
        from unittest import mock
        from vbear import server, skillbook
        from vbear.api_error import ApiError
        real, calls = skillbook.add, []

        def second_fails(body):
            calls.append(1)
            if len(calls) == 2:
                raise ApiError(400, "skill_refused", "no")
            return real(body)
        with mock.patch.object(server.skillbook_mod, "add", second_fails):
            code = self.run_qa()
        self.assert_fails(code, "stopped")
        self.assertTrue(self.failed("template_partial"), self.text())
        self.nothing_left()

    def test_an_undo_that_deletes_the_employee_who_was_talked_to(self):
        self.assert_fails(self.run_qa(no_record=True), "kept:")

    def test_an_undo_preview_that_wrote(self):
        def write(console, clean, method, body):
            if clean.endswith("/undo-preview"):
                ap.save_profile(None, {"name": "不該有的", "model": {"tool": "claude"}})
        self.assert_fails(self.run_qa(before=write), "the preview of the undo wrote nothing")

    def test_a_saved_employee_that_has_a_tool(self):
        def tool(console, clean, method, status, data):
            if clean == "/api/templates" and method == "GET" and isinstance(data, dict):
                mine = [dict(t, cards=[dict(c, tool="claude") for c in t["cards"]]) for t in data["mine"]]
                return status, dict(data, mine=mine)
        self.assert_fails(self.run_qa(after=tool), "only key, name, position, instructions and claude_model")

    def test_a_record_that_holds_a_name(self):
        def leak(console, clean, method, status, data):
            if clean == "/api/templates/apply" and status == 201:
                with open(console.t.state / "templates" / "log.jsonl", "a", encoding="utf-8") as out:
                    out.write(json.dumps({"what": "applied", "name": "客服"}, ensure_ascii=False) + "\n")
        self.assert_fails(self.run_qa(after=leak), "hold no name or word")

    def test_too_much_spent(self):
        self.assert_fails(self.run_qa(spent=0.5), "within the allowance")

    def test_something_left_behind(self):
        def keep(console, clean, method, body):
            if clean.endswith("/delete") and clean.startswith("/api/routines/"):
                return 200, {"ok": True}                           # a delete that is answered and does nothing
        self.assert_fails(self.run_qa(replace=keep), "the counts of employees, skills and routines")


class TheHelpers(unittest.TestCase):
    def test_card_problems(self):
        good = {"launch_mode": "safe", "equipped_skill_ids": [], "model": {"tool": "claude", "model_id": "haiku"}}
        self.assertEqual(qa.card_problems(good, "haiku"), [])
        self.assertEqual(qa.card_problems(dict(good, launch_mode="full"), "haiku"), ["launch_mode"])
        self.assertEqual(qa.card_problems(dict(good, equipped_skill_ids=["a"]), "haiku"), ["equipped_skill_ids"])
        self.assertEqual(qa.card_problems(dict(good, model={"tool": "codex", "model_id": ""}), "haiku"), ["tool", "model"])
        self.assertEqual(qa.card_problems(good, None), ["model"])
        self.assertEqual(qa.card_problems(dict(good, model={"tool": "claude", "model_id": ""}), None), [])

    def test_list_problems(self):
        self.assertEqual(qa.list_problems([{"cards": [{"position": "pm"}, {"position": None}], "routines": [{"enabled": False}]}]), [])
        self.assertEqual(qa.list_problems([{"cards": [{"position": "ceo"}]}]), ["position"])
        self.assertEqual(qa.list_problems([{"cards": [{"launch_mode": "safe"}]}]), ["launch_mode"])
        self.assertEqual(qa.list_problems([{"routines": [{"enabled": True}]}]), ["enabled"])

    def test_differs_and_absent_stays_absent(self):
        self.assertEqual(qa.differs({"a": "1", "b": None}, {"a": "1", "b": None}), [])
        self.assertEqual(qa.differs({"a": "1"}, {"a": "2"}), ["a"])
        self.assertEqual(qa.differs({"a": None}, {}), ["a"], "a file that appeared is a difference, also when it was None")

    def test_counts_of(self):
        self.assertEqual(qa.counts_of([{"kind": "card"}, {"kind": "card"}, {"kind": "skill"}]), (2, 1, 0))

    def test_money(self):
        self.assertEqual(qa.money("0.05"), 0.05)
        self.assertIsNone(qa.money("x"))
        self.assertIsNone(qa.money(-1))

    def test_the_things_it_ticks_exist_in_the_built_in_ones(self):
        from vbear import templates_builtin as tb
        built = {t["id"]: t for t in tb.builtin()}
        for kind, pairs in (("cards", qa.CARDS), ("skills", qa.SKILLS), ("routines", qa.ROUTINES)):
            for template, key in pairs:
                self.assertIn(key, [i["key"] for i in built[template][kind]], (template, key))
        self.assertIn("study", [s["key"] for s in built["life"]["skills"]])
        self.assertEqual(built["shop"]["cards"][0]["name"], "客服")
        self.assertEqual(built["shop"]["cards"][0]["claude_model"], "haiku")


class NoFixedPort(unittest.TestCase):
    def test_the_script_names_no_fixed_port_but_the_default_and_the_two_it_refuses(self):
        text = (Path(__file__).resolve().parent.parent / "tools" / "qa_p45.py").read_text(encoding="utf-8")
        ports = set(re.findall(r"\b7[0-9]{3}\b", text))
        self.assertEqual(ports, {"7788", "7789", "7800"})


if __name__ == "__main__":
    unittest.main()
