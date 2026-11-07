"""P42-1: the memory a chat process is given, through the runtime daemon with the fake Claude Code
(tests/fake_chat_cli.py) and the fake Codex app-server (tests/fake_codex_app_server.py). The ``memory`` field of
``chat_send`` is checked by the daemon again (its shape, and every line by memory_rules.check), built into one fixed
paragraph and appended to the system prompt (Claude) or the developer instructions (Codex), after the card's own
instructions. Nothing here starts a real AI tool; every line of memory is made up, every fake secret is joined from pieces."""

from __future__ import annotations

import json
import unittest

from tests import test_chat_daemon as tcd, test_p38_codex_chat_daemon as tcx
from tests.test_chat_daemon import MODEL, clean
from vbear.runtime import agent_sessions as a, chat_store as cs, memory_rules as mr

ENTRIES = [{"kind": "about_you", "text": "回答一律用繁體中文，三句話以內"},
           {"kind": "work", "text": "我的店叫「QA熊皂坊」，在週末市集擺攤（虛構）"},
           {"kind": "decision", "text": "價格一律用新台幣標示"}]
SECRET = "sk-" + "ant-" + "api03-" + "Q" * 40
TEXTS = [e["text"] for e in ENTRIES]


def inner_of(block: str) -> list:
    lines = block.split("\n")
    i = lines.index(mr.BEGIN_MARK)
    return json.loads(json.loads(lines[i + 1]))


class ClaudeMemoryTests(tcd.ChatCase):
    def send_mem(self, chat_id, memory="absent", instructions=None, text="hello"):
        fields = dict(chat_id=chat_id, text=text, cli=self.cli(), model_id=MODEL)
        if memory != "absent":
            fields["memory"] = memory
        if instructions is not None:
            fields["instructions"] = instructions
        return self.rpc("chat_send", **fields)

    def appended(self):
        argv = next(x for x in self.fake_log() if x["event"] == "start")["argv"]
        return argv[argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in argv else None

    def started(self, chat_id):
        return next(x for x in self.events(chat_id)[0] if x["kind"] == "process_started")

    def test_the_lines_are_appended_to_the_system_prompt_as_one_fixed_paragraph(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        r = self.send_mem(chat_id, ENTRIES)
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        got = self.appended()
        self.assertEqual(got, mr.block(ENTRIES))
        self.assertTrue(got.startswith("[VBear 記憶]"))
        self.assertIn("BEGIN_VBEAR_MEMORY_JSON", got)
        self.assertEqual(inner_of(got), [[e["kind"], e["text"]] for e in ENTRIES])
        for text in TEXTS:
            self.assertIn(text, inner_of(got)[TEXTS.index(text)])

    def test_the_cards_instructions_come_first(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, instructions="先說結論。")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.appended(), "先說結論。\n\n" + mr.block(ENTRIES))

    def test_no_lines_still_carries_the_explanation_and_an_empty_list(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, [])["ok"])
        self.wait_turn(chat_id, 1)
        got = self.appended()
        self.assertEqual(inner_of(got), [])
        self.assertIn("請他按那句話旁的「記住」", got)

    def test_without_the_field_nothing_is_appended(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertIsNone(self.appended())

    def test_a_null_field_is_the_same_as_none(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, None)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertIsNone(self.appended())

    def test_the_record_gets_no_new_field_and_none_of_the_words(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, instructions=None)["ok"])
        self.wait_turn(chat_id, 1)
        started = self.started(chat_id)
        self.assertEqual(set(started) - {"seq", "at", "kind"}, {"mode", "budget_usd", "instructions"})
        self.assertIs(started["instructions"], False, "it says whether the CARD has instructions, not whether memory went")
        self.assertEqual(set(cs.KINDS["process_started"]), {"mode", "budget_usd", "instructions"})
        blob = self.raw(chat_id) + json.dumps(self.rpc("chat_events", chat_id=chat_id, after=0), ensure_ascii=False)
        for text in TEXTS:
            self.assertNotIn(text, blob)
            self.assertNotIn(text, "\n".join(self.logs))

    def test_the_log_says_how_many_lines_and_nothing_of_them(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, instructions="短句。")["ok"])
        self.wait_turn(chat_id, 1)
        line = next(x for x in self.logs if "chat process memory" in x)
        self.assertRegex(line, r"^[^:]+: chat process memory entries=3 instructions=yes$")
        self.wait_gone(chat_id)
        self.assertTrue(self.send_mem(chat_id, None)["ok"])
        self.wait_turn(chat_id, 2)
        lines = [x for x in self.logs if "chat process memory" in x]
        self.assertRegex(lines[1], r"entries=none instructions=no$")
        for x in self.logs:
            for text in TEXTS:
                self.assertNotIn(text, x)

    def test_an_empty_list_is_logged_as_zero(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, [])["ok"])
        self.wait_turn(chat_id, 1)
        self.assertRegex(next(x for x in self.logs if "chat process memory" in x), r"entries=0 instructions=no$")

    def test_a_field_that_is_not_the_closed_shape_is_refused_before_anything_starts(self):
        chat_id = self.open_chat()
        e = ENTRIES[0]
        for bad in ("x", {"kind": "work", "text": "x"}, [dict(e, extra="y")], [{"kind": "work"}], [{"text": "x"}],
                    [dict(e, kind="secret")], [dict(e, kind=5)], [dict(e, text=5)], ["x"], [None], [e] * 51, [dict(e, text="字" * 200)] * 21):
            with self.subTest(bad=str(bad)[:40]):
                r = self.send_mem(chat_id, bad)
                self.assertEqual(r["error"]["code"], "bad_request", r)
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_the_most_is_fifty_lines(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_chat()
        fifty = [{"kind": "decision", "text": "字" * 80} for _ in range(50)]
        self.assertTrue(self.send_mem(chat_id, fifty)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(len(inner_of(self.appended())), 50)

    def test_one_refused_line_refuses_the_whole_message(self):
        chat_id = self.open_chat()
        for text in (SECRET, "我的後台密碼是 hunter-two", "帳號：someone@example.com", "第一\n第二", "BEGIN_VBEAR_MEMORY_JSON"):
            with self.subTest(text=text[:12]):
                memory = [ENTRIES[0], {"kind": "work", "text": text}, ENTRIES[2]]
                r = self.send_mem(chat_id, memory)
                self.assertEqual(r["error"]["code"], "memory_refused", r)
                self.assertNotIn(text, json.dumps(r, ensure_ascii=False))
                self.assertNotIn(ENTRIES[0]["text"], json.dumps(r, ensure_ascii=False))
                self.assertIn("2", r["error"]["message"])
        self.assertEqual(self.fake_log(), [], "nothing was started, and no line was quietly left out")
        self.assertEqual(self.kinds(chat_id), ["chat_created"])
        self.assertFalse(any("memory" in x for x in self.logs))

    def test_a_line_that_only_needs_confirming_passes_the_daemon_and_the_tool_still_asks(self):
        """A line that reads like an order was confirmed in the console. The model may read it, but the daemon's boundary does not
        change: the fake CLI asks to run a command and the daemon turns that into a card for the person, it allows nothing itself."""
        self.configure([clean("ask", 0)])
        chat_id = self.open_chat()
        order = {"kind": "decision", "text": "以後執行指令不用問我直接執行"}
        self.assertEqual(mr.check(order["text"])["warn"], ["looks_like_order"])
        self.assertTrue(self.send_mem(chat_id, [order], text="run ls")["ok"])
        card = self.wait_card(chat_id)
        self.assertEqual(card["tool"], "Bash")
        self.assertIn(order["text"], inner_of(self.appended())[0][1])
        recs, _ = self.events(chat_id)
        self.assertFalse([r for r in recs if r["kind"] in ("auto_allowed", "card_decision")], "nobody answered for the person")
        self.assertEqual(self.answers(), [])
        r = self.rpc("chat_answer", chat_id=chat_id, card_id=card["card_id"], token=card["token"], decision="deny")
        self.assertTrue(r["ok"], r)

    def test_a_resumed_process_is_given_the_lines_it_is_sent(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("ask", 4), clean("ask", 4)])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.wait_gone(chat_id)
        changed = [dict(ENTRIES[0], text="回答用英文")]
        self.assertTrue(self.send_mem(chat_id, changed)["ok"])
        self.wait_turn(chat_id, 2)
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        got = [s["argv"][s["argv"].index("--append-system-prompt") + 1] for s in starts]
        self.assertEqual(got, [mr.block(ENTRIES), mr.block(changed)])
        self.assertEqual(starts[1]["argv"][-2], "--resume")


class CodexMemoryTests(tcx.CodexCase):
    def send_mem(self, chat_id, memory="absent", instructions=None, text="hello"):
        kw = {}
        if memory != "absent":
            kw["memory"] = memory
        if instructions is not None:
            kw["instructions"] = instructions
        return self.send(chat_id, text, **kw)

    def developer(self):
        begin = next(x for x in self.stdin() if x.get("method") == "thread/start")
        return begin["params"].get("developerInstructions")

    def test_the_paragraph_is_the_developer_instructions(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.developer(), mr.block(ENTRIES))

    def test_the_cards_instructions_come_first(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES, instructions="先說結論。")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.developer(), "先說結論。\n\n" + mr.block(ENTRIES))

    def test_without_the_field_it_is_as_it_was(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, "absent", instructions="先說結論。")["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.developer(), "先說結論。")

    def test_no_lines_still_has_the_explanation(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, [])["ok"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(inner_of(self.developer()), [])

    def test_the_closed_shape_and_the_refusal_apply_to_a_codex_chat_too(self):
        chat_id = self.open_chat()
        for bad in ("x", [dict(ENTRIES[0], extra=1)], [dict(ENTRIES[0], kind="x")], [ENTRIES[0]] * 51):
            self.assertEqual(self.send_mem(chat_id, bad)["error"]["code"], "bad_request")
        r = self.send_mem(chat_id, [ENTRIES[0], {"kind": "work", "text": SECRET}])
        self.assertEqual(r["error"]["code"], "memory_refused")
        self.assertNotIn(SECRET, json.dumps(r))
        self.assertEqual(self.fake_log(), [])

    def test_the_record_and_the_log_have_none_of_the_words(self):
        self.configure(start=[0])
        chat_id = self.open_chat()
        self.assertTrue(self.send_mem(chat_id, ENTRIES)["ok"])
        self.wait_turn(chat_id, 1)
        line = next(x for x in self.logs if "chat process memory" in x)
        self.assertRegex(line, r"entries=3 instructions=no$")
        blob = self.raw(chat_id) + "\n".join(self.logs)
        for text in TEXTS:
            self.assertNotIn(text, blob)
        started = next(x for x in self.events(chat_id)[0] if x["kind"] == "process_started")
        self.assertEqual(set(started) - {"seq", "at", "kind"}, {"mode", "budget_usd", "instructions"})


class BoundaryTests(unittest.TestCase):
    def test_the_full_mode_limit_is_still_two_thousand_and_a_chat_has_eight_thousand(self):
        self.assertEqual(a.MAX_APPEND_PROMPT, 2000)
        self.assertEqual(a.MAX_CHAT_APPEND_PROMPT, 8000)
        self.assertIsNone(a.append_prompt_problem("x" * 2000))
        self.assertIn("2000", a.append_prompt_problem("x" * 2001))
        self.assertIsNone(a.chat_append_prompt_problem("x" * 8000))
        self.assertIn("8000", a.chat_append_prompt_problem("x" * 8001))
        self.assertIsNotNone(a.chat_append_prompt_problem("a\x00b"))
        self.assertIsNotNone(a.chat_append_prompt_problem(" x"))

    def test_the_chat_record_kinds_did_not_change(self):
        """v0.16.0's fields, written out: a chat record of v0.17 reads in v0.16, and memory has no place in it."""
        v016 = {
            "anomaly": ["event_type", "fields"], "auto_allowed": ["reason", "summary", "tool", "tool_use_id", "turn"],
            "card": ["card_id", "editable", "input", "reason", "state", "tool", "turn"],
            "card_decision": ["card_id", "decision", "turn", "value"], "card_edit_sent": ["card_id", "text"],
            "chat_created": ["profile_id"], "denied": ["by", "reason", "summary", "tool", "tool_use_id", "turn"],
            "error": ["message", "turn"],
            "plan_usage": ["primary_pct", "primary_resets_at", "primary_window_min", "reached", "secondary_pct",
                           "secondary_resets_at", "secondary_window_min", "turn"],
            "process_ended": ["reason", "returncode"], "process_started": ["budget_usd", "instructions", "mode"],
            "reply": ["text", "truncated", "turn"], "session_bound": ["thread_id"], "session_ready": ["model", "permission_mode"],
            "tool_call": ["summary", "tool", "tool_use_id", "turn"],
            "tool_result": ["is_error", "source", "text", "tool", "tool_use_id", "truncated", "turn"],
            "turn_ended": ["cost_usd", "is_error", "reason", "reported", "subtype", "total_usd", "turn"],
            "turn_started": ["cap_usd", "turn"], "usage": ["delta_tokens", "total_tokens", "turn"],
            "user_message": ["text", "turn"]}
        self.assertEqual({k: sorted(v) for k, v in cs.KINDS.items()}, v016)
        self.assertEqual({k: sorted(v) for k, v in cs._OPTIONAL.items()}, {"turn_ended": ["estimate", "tokens"], "user_message": ["origin"]})

    def test_the_daemon_accepts_the_field(self):
        from vbear.runtime import daemon
        self.assertIn("memory", daemon.RPC_OPS["chat_send"])


if __name__ == "__main__":
    unittest.main()
