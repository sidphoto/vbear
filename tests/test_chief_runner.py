"""The chief of staff's one proposal, run (P40-1): the preview, the one call on the meetings' engine, the money and the day it
shares with the meetings, the staffing meetings, the chats and the tries, a retry and a restart. No real CLI and no network:
a fake call answers in place of Claude Code, or an owned synthetic script prints what a tool-less one would. The chats are
real files in a synthetic state folder, written by the chat store. Every name and every word of the chat is made up."""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import board_engine as be, chief, chief_runner as cr, meeting_runner as mr
from vbear import meetings as mt, staffing_runner as sr, translations as tr
from vbear.runtime import chat_store as cs, daemon_chat
from tests import leftover

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}
INIT = {"type": "system", "subtype": "init", "tools": ["StructuredOutput"], "mcp_servers": [], "model": "claude-sonnet-5-5"}
FAKE = '''#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ['--version']:
    print('{version} (Claude Code)')
    sys.exit(0)
assert args[args.index('--tools')+1] == ''
assert '--safe-mode' in args and '--strict-mcp-config' in args and '--no-session-persistence' in args and '--verbose' in args
assert '--allowedTools' not in args and '--dangerously-skip-permissions' not in args
assert not list(Path.cwd().iterdir())
schema = json.loads(args[args.index('--json-schema')+1])
prompt = sys.stdin.read()
with open({log!r}, 'a') as fh:
    fh.write(json.dumps({{'model': args[args.index('--model')+1], 'budget': args[args.index('--max-budget-usd')+1],
                         'effort': args[args.index('--effort')+1], 'schema_keys': sorted(schema['properties']),
                         'tools_enum': schema['properties']['new_cards']['items']['properties']['tool']['enum'],
                         'prompt': prompt}}) + chr(10))
{body}
'''


def card(pid, position, tool="claude", *, enabled=True, name=None, model_id="", **extra):
    p = {"id": pid, "name": name or f"虛構{pid}", "profession_role_id": None, "model": {"tool": tool, "model_id": model_id},
         "equipped_skill_ids": [], "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
         "enabled": enabled, "created_at": 1.0, "updated_at": 1.0, "position": position}
    p.update(extra)
    return p


def plan(**changes):
    out = {"summary": "先寫介紹，再算價格", "task": {"title": "週末市集攤位", "goal": "準備賣手工皂的攤位", "deliverables": ["攤位介紹"]},
           "team": [{"who": "C1", "why": "會寫文案"}], "new_cards": [],
           "steps": [{"who": "C1", "text": "請寫一份攤位介紹。"}], "questions": []}
    out.update(changes)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbc-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(os.path.realpath(self.tmp.name))
        self.addCleanup(leftover.assert_clean, self.root)     # no runtimed, no runner's program left under the test's folder
        home = self.root / "h"
        home.mkdir()
        self.base = home / ".vbear"
        self.base.mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(self.base), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.log = self.root / "calls.jsonl"
        self.profiles = {p["id"]: p for p in (
            card("ceo", "planner", name="虛構CEO"), card("copy", "social", name="文案小編"), card("pm", "pm", name="專案經理"),
            card("cx", "executor", tool="codex", name="寫程式的"), card("off", "art", enabled=False, name="停用的"),
            card("agy", "art", tool="agy", name="其他工具"), card("ceo2", "planner", tool="codex", name="第二個CEO"))}
        self.tools = ("claude", "codex")
        self.runners = []
        self.specs = []
        self.chat_id = self.chat("ceo", [("user", "我想在週末市集擺攤賣手工皂"), ("ceo", "好，先問你預算")])

    def chat(self, profile_id, said, engine="claude-chat"):
        chat = cs.create(self.base, profile_id, now=time.time(), engine=engine)
        log = cs.ChatLog(self.base, chat["id"])
        try:
            turn = 1
            for who, text in said:
                if who == "user":
                    turn += 1
                    log.append("user_message", {"turn": turn, "text": text}, now=time.time())
                elif who == "ceo":
                    log.append("reply", {"turn": turn, "text": text, "truncated": False}, now=time.time())
                elif who == "tool":
                    log.append("tool_result", {"turn": turn, "tool_use_id": "t1", "tool": "Bash", "is_error": False, "text": text,
                                               "truncated": False, "source": "stdout"}, now=time.time())
                elif who == "error":
                    log.append("error", {"turn": turn, "message": text}, now=time.time())
        finally:
            log.close()
        return chat["id"]

    def sources(self, **conf):
        return cr.ChiefSources(chat=cr.chat_reader(self.base), profile=self.profiles.get, profiles=lambda: list(self.profiles.values()),
                               tools=lambda: self.tools, conf=conf)

    def board(self, answer=None, **kw):
        def fake(spec, cancel):
            self.specs.append(spec)
            out = answer(spec) if callable(answer) else (answer if answer is not None else plan())
            return mr.CallResult(out, dict(EVIDENCE), Decimal("0.02"))
        kw.setdefault("provider", lambda e: ("x", VERSION))
        kw.setdefault("call", fake)
        runner = cr.ChiefRunner(**kw)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        return runner

    def run_one(self, runner, chat_id=None, note="", **conf):
        src = self.sources(**conf)
        preview = runner.preview(chat_id or self.chat_id, src)
        self.assertTrue(preview["ok"], preview["blockers"])
        rec = runner.start(preview["preview_id"], {"note": note}, src)
        runner.wait(10)
        return chief.load(rec["id"])

    def script(self, body):
        script = self.root / "fake-cli"
        script.write_text(FAKE.format(python=sys.executable, version=VERSION, log=str(self.log), body=body))
        script.chmod(0o700)
        return script

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def write_meeting_spend(self, cost="0.40"):
        """A meeting that cost ``cost`` today, written as the meetings' store keeps one."""
        from tests.test_meetings import finish, opinion, record as meeting_record
        rec = finish(meeting_record(), 1, opinion(), cost)
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)


class PreviewTests(Base):
    def test_the_preview_says_what_is_read_and_what_it_may_cost_and_never_the_chat(self):
        runner = self.board()
        preview = runner.preview(self.chat_id, self.sources())
        self.assertTrue(preview["ok"])
        self.assertEqual((preview["messages"], preview["omitted_messages"], preview["cards"], preview["tools"]),
                         (2, 0, 3, ["claude", "codex"]))
        self.assertEqual((preview["cap_usd"], preview["sends_to"]), ("0.3", "Claude Code"))
        self.assertEqual(preview["day_left_usd"], "3")
        text = json.dumps(preview, ensure_ascii=False)
        for word in ("手工皂", "預算", "文案小編", "copy"):
            self.assertNotIn(word, text)
        self.assertEqual(self.specs, [])

    def test_a_codex_ceo_is_told_the_chat_goes_to_claude_code(self):
        chat_id = self.chat("ceo2", [("user", "你好")], engine="codex-chat")
        preview = self.board().preview(chat_id, self.sources())
        self.assertEqual(preview["ceo_tool"], "codex")
        self.assertIn("Claude Code", preview["notice"])

    def test_only_a_chat_with_a_ceo_card_may_ask(self):
        other = self.chat("copy", [("user", "你好")])
        with self.assertRaises(chief.ChiefError) as got:
            self.board().preview(other, self.sources())
        self.assertEqual(got.exception.code, "not_ceo")

    def test_a_disabled_ceo_or_a_missing_chat_or_a_bad_id_is_refused(self):
        self.profiles["ceo"]["enabled"] = False
        with self.assertRaises(chief.ChiefError) as got:
            self.board().preview(self.chat_id, self.sources())
        self.assertEqual(got.exception.code, "card_unavailable")
        for chat_id, code in (("c-0000000000000000", "not_found"), ("../x", "bad_request"), (None, "bad_request")):
            with self.assertRaises(chief.ChiefError) as got:
                self.board().preview(chat_id, self.sources())
            self.assertEqual(got.exception.code, code, chat_id)

    def test_a_chat_that_does_not_read_whole_is_refused(self):
        path = self.base / "chats" / self.chat_id / "events.jsonl"
        lines = path.read_text().splitlines(keepends=True)
        lines[1] = lines[1][:10] + "\n"
        path.write_text("".join(lines))
        with self.assertRaises(chief.ChiefError) as got:
            self.board().preview(self.chat_id, self.sources())
        self.assertEqual(got.exception.code, "storage")

    def test_no_conversation_yet_is_a_blocker(self):
        empty = self.chat("ceo", [])
        preview = self.board().preview(empty, self.sources())
        self.assertFalse(preview["ok"])
        self.assertIsNone(preview["preview_id"])
        self.assertEqual([b["code"] for b in preview["blockers"]], ["no_conversation"])

    def test_no_tool_that_can_chat_is_a_blocker(self):
        self.tools = ()
        preview = self.board().preview(self.chat_id, self.sources())
        self.assertEqual([b["code"] for b in preview["blockers"]], ["no_chat_tool"])

    def test_no_claude_code_and_an_unchecked_one_are_blockers_in_the_persons_words(self):
        def missing(engine):
            raise tr.TranslationError("cli_not_found")

        def unchecked(engine):
            raise tr.TranslationError("boundary_unverified")
        for provider, code, words in ((missing, "cli_not_found", "幕僚長目前需要 Claude Code"), (unchecked, "boundary_unverified", "還沒通過")):
            preview = self.board(provider=provider).preview(self.chat_id, self.sources())
            self.assertFalse(preview["ok"])
            self.assertEqual([b["code"] for b in preview["blockers"]], [code])
            self.assertIn(words, preview["blockers"][0]["message"])
            self.assertIsNone(preview["preview_id"])

    def test_the_cap_is_the_smaller_of_thirty_cents_and_what_the_day_has_left(self):
        self.write_meeting_spend("0.40")
        preview = self.board().preview(self.chat_id, self.sources(meeting_limits={"per_call_usd": 0.2, "meeting_usd": 1, "daily_usd": 0.5}))
        self.assertEqual((preview["cap_usd"], preview["day_left_usd"]), ("0.1", "0.1"))
        self.assertTrue(preview["ok"], preview["blockers"])

    def test_a_red_light_or_less_than_a_cent_left_never_calls(self):
        self.write_meeting_spend("0.50")
        runner = self.board()
        preview = runner.preview(self.chat_id, self.sources(meeting_limits={"per_call_usd": 0.2, "meeting_usd": 1, "daily_usd": 0.5}))
        self.assertFalse(preview["ok"])
        self.assertIsNone(preview["preview_id"])
        self.assertTrue(all(b["code"] == "budget" for b in preview["blockers"]))
        self.assertEqual(preview["day_left_usd"], "0")
        self.assertEqual(self.specs, [])

    def test_a_day_with_only_half_a_cent_left_does_not_call(self):
        self.write_meeting_spend("0.495")
        preview = self.board().preview(self.chat_id, self.sources(meeting_limits={"per_call_usd": 0.2, "meeting_usd": 1, "daily_usd": 0.5}))
        self.assertFalse(preview["ok"])
        self.assertEqual(preview["cap_usd"], "0")

    def test_a_worker_that_is_busy_is_a_blocker(self):
        from vbear import headless_cli
        fd = headless_cli.acquire_worker(be.WORKER, check_blocked=False)
        try:
            preview = self.board().preview(self.chat_id, self.sources())
        finally:
            os.close(fd)
        self.assertEqual([b["code"] for b in preview["blockers"]], ["busy"])

    def test_the_list_is_only_cards_that_can_chat_now_and_the_ceo_is_not_on_it(self):
        self.tools = ("claude",)
        runner = self.board()
        runner.preview(self.chat_id, self.sources())
        rec = self.run_one(runner)
        self.assertEqual([c["name"] for c in rec["sent"]["cards"]], ["專案經理", "文案小編"])
        self.assertEqual(rec["sent"]["tools"], ["claude"])


class RunTests(Base):
    def test_one_call_with_the_models_and_limits_vbear_chose(self):
        runner = self.board()
        rec = self.run_one(runner, note="預算兩千元")
        self.assertEqual(len(self.specs), 1)
        spec = self.specs[0]
        self.assertEqual((spec.kind, spec.model, spec.effort, spec.per_call, spec.timeout), ("plan", "sonnet", "low", Decimal("0.3"), 120.0))
        self.assertEqual(spec.schema["properties"]["new_cards"]["items"]["properties"]["tool"]["enum"], ["claude", "codex"])
        turn = rec["turns"][0]
        self.assertEqual((turn["state"], turn["attempts"], turn["evidence"]["cost_usd"]), ("done", 1, "0.02"))
        self.assertEqual(turn["prompt_sha256"], hashlib.sha256(spec.prompt.encode()).hexdigest())
        self.assertEqual(chief.view(rec)["status"], "ready")
        self.assertEqual(rec["outcome"]["state"], "ready")
        self.assertIsNone(rec["outcome"]["dispatch_id"])
        self.assertIsNone(runner.job)

    def test_only_what_was_said_is_sent_and_no_id_instruction_or_tool_output(self):
        chat_id = self.chat("ceo", [("user", "我想擺攤"), ("tool", "TOOL-OUTPUT-XYZ"), ("error", "ERROR-TEXT-XYZ"), ("ceo", "先問預算")])
        self.profiles["copy"]["instructions"] = "SECRET-INSTRUCTION-XYZ"
        self.run_one(self.board(), chat_id)
        prompt = self.specs[0].prompt
        for word in ("我想擺攤", "先問預算", "文案小編", "C1"):
            self.assertIn(word, prompt)
        for word in ("TOOL-OUTPUT-XYZ", "ERROR-TEXT-XYZ", "SECRET-INSTRUCTION-XYZ", "copy", "pm\"", "ceo", "/Users/", "profile_id"):
            self.assertNotIn(word, prompt)

    def test_twenty_messages_and_twelve_kib_are_the_most_that_is_read(self):
        said = [("user", f"第{i:02d}句") for i in range(25)]
        self.run_one(self.board(), self.chat("ceo", said))
        prompt = self.specs[0].prompt
        self.assertIn("第24句", prompt)
        self.assertIn("第05句", prompt)
        self.assertNotIn("第04句", prompt)
        big = [("ceo", ("字" * 1000) + str(i)) for i in range(6)]
        self.specs.clear()
        self.run_one(self.board(), self.chat("ceo", big))
        prompt = self.specs[0].prompt
        self.assertIn("2", prompt)
        self.assertNotIn("字" * 1000 + "1", prompt)
        self.assertIn("字" * 1000 + "5", prompt)

    def test_a_secret_in_a_message_or_a_card_name_is_masked(self):
        self.profiles["copy"]["name"] = "小編 sk-ant-api03-" + "C" * 40
        self.run_one(self.board(), self.chat("ceo", [("user", "我的金鑰 sk-ant-api03-" + "D" * 40)]))
        self.assertNotIn("sk-ant-api03-" + "C" * 20, self.specs[0].prompt)
        self.assertNotIn("sk-ant-api03-" + "D" * 20, self.specs[0].prompt)

    def test_the_record_keeps_no_word_of_the_chat_and_only_the_hash_of_the_prompt(self):
        rec = self.run_one(self.board(), note="一句補充")
        raw = (chief.folder() / f"{rec['id']}.json").read_text()
        for word in ("我想在週末市集擺攤", "好，先問你預算"):
            self.assertNotIn(word, raw)
        self.assertEqual(rec["read"]["count"], 2)
        self.assertEqual(oct(os.stat(chief.folder() / f"{rec['id']}.json").st_mode & 0o777), "0o600")
        self.assertNotIn(self.specs[0].prompt, raw)

    def test_the_proposal_hook_is_told_when_it_is_ready(self):
        seen = []
        runner = self.board(on_proposal=lambda cid: seen.append(cid))
        rec = self.run_one(runner)
        self.assertEqual(seen, [rec["id"]])

    def test_a_hook_that_fails_does_not_lose_the_proposal(self):
        def boom(cid):
            raise RuntimeError("synthetic")
        rec = self.run_one(self.board(on_proposal=boom))
        self.assertEqual(chief.view(rec)["status"], "ready")
        self.assertIsNone(self.runners[-1].job)

    def test_a_proposal_with_only_questions_is_ready(self):
        rec = self.run_one(self.board(plan(team=[], steps=[], questions=["你想賣幾種香味？"], task={"title": "", "goal": "", "deliverables": []})))
        v = chief.view(rec)
        self.assertEqual((v["status"], v["plan"]["steps"], v["plan"]["questions"]), ("ready", [], ["你想賣幾種香味？"]))

    def test_things_taken_out_are_said(self):
        out = plan(team=[{"who": "C1", "why": "a"}, {"who": "C9", "why": "b"}],
                   steps=[{"who": "C1", "text": "做甲"}, {"who": "C9", "text": "做乙"}])
        v = chief.view(self.run_one(self.board(out)))
        self.assertEqual([n["code"] for n in v["notes"]], ["unknown_card", "step_unknown"])
        self.assertEqual([s["name"] for s in v["plan"]["steps"]], ["寫程式的"])

    def test_an_answer_with_a_field_too_many_or_too_few_fails_and_may_be_tried_again(self):
        answers = [dict(plan(), daily_usd=5), {k: v for k, v in plan().items() if k != "questions"}, plan()]
        runner = self.board(lambda spec: answers.pop(0))
        src = self.sources()
        preview = runner.preview(self.chat_id, src)
        rec = runner.start(preview["preview_id"], {}, src)
        runner.wait(10)
        rec = chief.load(rec["id"])
        turn = rec["turns"][0]
        self.assertEqual((turn["state"], turn["error_code"], turn["attempts"]), ("failed", "invalid_output", 1))
        self.assertEqual(chief.view(rec)["retryable"], [1])
        self.assertEqual(chief.view(rec)["status"], "failed")
        runner.retry(rec["id"], src)
        runner.wait(10)
        turn = chief.load(rec["id"])["turns"][0]
        self.assertEqual((turn["state"], turn["error_code"], turn["attempts"]), ("failed", "invalid_output", 2))
        runner.retry(rec["id"], src)
        runner.wait(10)
        rec = chief.load(rec["id"])
        self.assertEqual((rec["turns"][0]["state"], rec["turns"][0]["attempts"]), ("done", 3))
        self.assertEqual(rec["turns"][0]["evidence"]["cost_usd"], "0.06")
        self.assertEqual(chief.view(rec)["spent_usd"], "0.06")

    def test_everything_taken_out_fails_the_call(self):
        out = plan(team=[{"who": "C9", "why": "a"}], steps=[{"who": "C9", "text": "做"}])
        rec = self.run_one(self.board(out))
        self.assertEqual((rec["turns"][0]["state"], rec["turns"][0]["error_code"]), ("failed", "empty_plan"))

    def test_the_third_failure_blocks_and_a_fourth_is_refused(self):
        runner = self.board(lambda spec: {"nonsense": True})
        src = self.sources()
        preview = runner.preview(self.chat_id, src)
        rec = runner.start(preview["preview_id"], {}, src)
        runner.wait(10)
        for _ in range(2):
            runner.retry(rec["id"], src)
            runner.wait(10)
        turn = chief.load(rec["id"])["turns"][0]
        self.assertEqual((turn["state"], turn["attempts"]), ("blocked", 3))
        with self.assertRaises(chief.ChiefError) as got:
            runner.retry(rec["id"], src)
        self.assertEqual(got.exception.code, "not_retryable")

    def test_a_retry_is_refused_when_the_chat_or_the_list_changed(self):
        answers = [{"x": 1}, plan()]
        runner = self.board(lambda spec: answers.pop(0))
        src = self.sources()
        rec = runner.start(runner.preview(self.chat_id, src)["preview_id"], {}, src)
        runner.wait(10)
        log = cs.ChatLog(self.base, self.chat_id)
        log.append("user_message", {"turn": 9, "text": "又想到一件事"}, now=time.time())
        log.close()
        with self.assertRaises(chief.ChiefError) as got:
            runner.retry(rec["id"], src)
        self.assertEqual(got.exception.code, "changed")
        self.assertEqual(len(self.specs), 1)

    def test_a_done_proposal_cannot_be_retried_and_a_running_one_cannot_either(self):
        runner = self.board()
        rec = self.run_one(runner)
        with self.assertRaises(chief.ChiefError) as got:
            runner.retry(rec["id"], self.sources())
        self.assertEqual(got.exception.code, "not_retryable")

    def test_a_dispatch_made_from_it_closes_it(self):
        answers = [{"x": 1}]
        runner = self.board(lambda spec: answers.pop(0))
        src = self.sources()
        rec = runner.start(runner.preview(self.chat_id, src)["preview_id"], {}, src)
        runner.wait(10)
        runner._update(rec["id"], lambda r: r["outcome"].update(state="ready", dispatch_id="d-0123456789ab"))
        with self.assertRaises(chief.ChiefError) as got:
            runner.retry(rec["id"], src)
        self.assertEqual(got.exception.code, "already_decided")

    def test_a_stopped_call_is_cancelled(self):
        import threading
        gate = threading.Event()

        def slow(spec, cancel):
            gate.wait(5)
            raise be.CallFailed("cancelled", dict(EVIDENCE), None)
        runner = self.board(call=slow)
        src = self.sources()
        rec = runner.start(runner.preview(self.chat_id, src)["preview_id"], {}, src)
        for _ in range(100):
            if chief.load(rec["id"])["turns"][0]["state"] == "running":
                break
            time.sleep(0.02)
        self.assertEqual(runner.cancel(rec["id"])["status"], "running")
        gate.set()
        runner.wait(10)
        self.assertEqual(chief.load(rec["id"])["turns"][0]["state"], "cancelled")
        with self.assertRaises(chief.ChiefError) as got:
            runner.cancel(rec["id"])
        self.assertEqual(got.exception.code, "not_running")

    def test_a_note_too_long_or_with_control_characters_is_refused(self):
        runner = self.board()
        src = self.sources()
        for note in ("字" * 201, "a\x00b", 5):
            preview = runner.preview(self.chat_id, src)
            with self.assertRaises(chief.ChiefError) as got:
                runner.start(preview["preview_id"], {"note": note}, src)
            self.assertEqual(got.exception.code, "bad_request", note)

    def test_a_preview_is_used_once_and_goes_stale_when_the_chat_changes(self):
        runner = self.board()
        src = self.sources()
        preview = runner.preview(self.chat_id, src)
        runner.start(preview["preview_id"], {}, src)
        runner.wait(10)
        with self.assertRaises(chief.ChiefError) as got:
            runner.start(preview["preview_id"], {}, src)
        self.assertEqual(got.exception.code, "preview_expired")
        preview = runner.preview(self.chat_id, src)
        log = cs.ChatLog(self.base, self.chat_id)
        log.append("user_message", {"turn": 9, "text": "又想到一件事"}, now=time.time())
        log.close()
        with self.assertRaises(chief.ChiefError) as got:
            runner.start(preview["preview_id"], {}, src)
        self.assertEqual(got.exception.code, "stale_preview")
        preview = runner.preview(self.chat_id, src)
        self.profiles["copy"]["name"] = "改了名字"
        with self.assertRaises(chief.ChiefError) as got:
            runner.start(preview["preview_id"], {}, src)
        self.assertEqual(got.exception.code, "stale_preview")
        self.assertEqual(len(chief.record_ids()), 1)

    def test_the_call_is_not_made_when_the_day_ran_out_between_preview_and_start(self):
        runner = self.board()
        src = self.sources(meeting_limits={"per_call_usd": 0.2, "meeting_usd": 1, "daily_usd": 0.5})
        preview = runner.preview(self.chat_id, src)
        self.write_meeting_spend("0.50")
        with self.assertRaises(chief.ChiefError) as got:
            runner.start(preview["preview_id"], {}, src)
        self.assertEqual(got.exception.code, "budget")
        self.assertEqual(self.specs, [])

    def test_a_restart_interrupts_what_was_running_and_charges_its_worst_case(self):
        runner = self.board()
        cards, omitted = chief.candidates(list(self.profiles.values()), self.tools)
        rec = chief.new_record(chief.new_id(), chat_id=self.chat_id, ceo_profile_id="ceo", note="",
                               read={"count": 1, "omitted": 0, "bytes": 3, "sha256": "a" * 64},
                               sent=chief.sent_of(cards, omitted, self.tools, "b" * 64),
                               limits={"per_call_usd": Decimal("0.3"), "total_usd": Decimal("0.9")}, now=time.time())
        rec["turns"][0].update(state="running", attempts=1, started_at=time.time())
        store = chief.ChiefStore(rec["id"])
        with store.locked():
            store.save(rec)
        again = cr.ChiefRunner(provider=lambda e: ("x", VERSION), call=lambda s, c: None)
        turn = chief.load(rec["id"])["turns"][0]
        self.assertEqual((turn["state"], turn["error_code"], turn["evidence"]["cost_usd"], turn["evidence"]["cost_source"]),
                         ("interrupted", "restart", "0.3", "worst_case"))
        self.assertEqual(chief.view(chief.load(rec["id"]))["retryable"], [1])


class ThroughTheCli(Base):
    def test_the_call_is_the_tool_less_call_of_the_meetings_with_the_chiefs_format(self):
        body = (f"print(json.dumps({INIT!r}))\n"
                f"print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': {plan()!r}, "
                f"'total_cost_usd': 0.03}}))")
        script = self.script(body)
        runner = cr.ChiefRunner(provider=lambda e: (str(script), VERSION))
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        rec = self.run_one(runner)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["model"], calls[0]["budget"], calls[0]["effort"]), ("sonnet", "0.3", "low"))
        self.assertEqual(calls[0]["schema_keys"], sorted(chief.PLAN_SCHEMA["properties"]))
        self.assertEqual(calls[0]["tools_enum"], ["claude", "codex"])
        self.assertEqual((rec["turns"][0]["state"], rec["turns"][0]["evidence"]["cost_usd"]), ("done", "0.03"))

    def test_a_call_that_reports_a_tool_is_killed_and_the_check_is_revoked(self):
        bad = dict(INIT, tools=["StructuredOutput", "Bash"])
        script = self.script(f"print(json.dumps({bad!r}))")
        runner = cr.ChiefRunner(provider=lambda e: (str(script), VERSION))
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        with mock.patch.object(be.HeadlessBoard, "_revoke") as revoke:
            rec = self.run_one(runner)
        self.assertEqual((rec["turns"][0]["state"], rec["turns"][0]["error_code"]), ("failed", "tools_not_clean"))
        revoke.assert_called_once_with(VERSION)


class SharedDayTests(Base):
    def done_proposal(self, cost="0.07"):
        rec = self.run_one(self.board())
        def charge(r):
            r["turns"][0]["evidence"] = {**r["turns"][0]["evidence"], "cost_usd": cost, "cost_source": "cli"}
        self.runners[0]._update(rec["id"], charge)
        return rec["id"]

    def test_the_meetings_the_staffing_meetings_and_the_chiefs_own_board_count_the_proposals(self):
        self.done_proposal("0.07")
        meetings = mr.MeetingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        staffing = sr.StaffingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        chief_board = self.board()
        for runner in (meetings, staffing, chief_board):
            self.assertEqual(runner._day(), Decimal("0.07"), runner)
        ledger = meetings.ledger({})
        self.assertEqual(ledger["spent_usd"], "0.07")
        self.assertEqual(ledger["includes"], ["meetings", "staffing", "chats", "setup_try", "chief"])

    def test_the_chat_daemon_counts_them_too(self):
        self.done_proposal("0.07")

        class Fake:
            base = str(self.base)
        self.assertEqual(daemon_chat.ChatOps._chat_day_spent(Fake(), time.time()), Decimal("0.07"))

    def test_a_proposal_running_counts_at_its_cap(self):
        rec = self.run_one(self.board())
        self.runners[0]._update(rec["id"], lambda r: r["turns"][0].update(state="running", evidence=None, output=None))
        self.assertEqual(mr.MeetingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)._day(), Decimal("0.3"))

    def test_a_proposal_that_cannot_be_read_makes_the_day_unknown_everywhere(self):
        self.done_proposal()
        (chief.folder() / f"{chief.record_ids()[0]}.json").write_text("not json")
        meetings = mr.MeetingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        staffing = sr.StaffingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        for runner in (meetings, staffing, self.board()):
            with self.assertRaises(mt.MeetingError) as got:
                runner._day()
            self.assertEqual(got.exception.code, "spend_unknown", runner)
        with self.assertRaises(mt.MeetingError) as got:
            meetings.ledger({})
        self.assertEqual(got.exception.code, "spend_unknown")

        class Fake:
            base = str(self.base)
        with self.assertRaises(ValueError):
            daemon_chat.ChatOps._chat_day_spent(Fake(), time.time())
        with self.assertRaises(mt.MeetingError) as got:
            self.board().preview(self.chat_id, self.sources())
        self.assertEqual(got.exception.code, "spend_unknown")

    def test_a_folder_that_cannot_be_listed_makes_the_day_unknown(self):
        self.done_proposal()
        os.chmod(chief.folder(), 0)
        self.addCleanup(os.chmod, chief.folder(), 0o700)
        with self.assertRaises(mt.MeetingError) as got:
            mr.MeetingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)._day()
        self.assertEqual(got.exception.code, "spend_unknown")

    def test_a_meeting_and_a_proposal_never_run_together(self):
        gate = __import__("threading").Event()

        def slow(spec, cancel):
            gate.wait(5)
            return mr.CallResult(plan(), dict(EVIDENCE), Decimal("0.01"))
        runner = self.board(call=slow)
        src = self.sources()
        rec = runner.start(runner.preview(self.chat_id, src)["preview_id"], {}, src)
        meetings = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=lambda s, c: None)
        self.assertEqual([b["code"] for b in meetings._blockers(Decimal("0.1"), Decimal("1"), mt.limits_from({}))[0]], ["busy"])
        gate.set()
        runner.wait(10)
        self.assertEqual(chief.load(rec["id"])["turns"][0]["state"], "done")


class EngineTests(unittest.TestCase):
    def test_a_board_of_one_turn_is_asked_with_no_other_turn_and_the_others_still_need_an_answer(self):
        self.assertFalse(cr.ChiefRunner.final_needs_answers)
        self.assertTrue(be.HeadlessBoard.final_needs_answers)
        self.assertTrue(mr.MeetingRunner.final_needs_answers)
        self.assertTrue(sr.StaffingRunner.final_needs_answers)


class ChatToolsTests(unittest.TestCase):
    def test_a_tool_can_chat_when_its_own_support_says_it_is_ready(self):
        support = {"state": "verified", "codex": {"state": "ready"}}
        self.assertEqual(cr.usable_tools(support), ("claude", "codex"))
        self.assertEqual(cr.usable_tools({"state": "unverified", "codex": {"state": "ready"}}), ("codex",))
        self.assertEqual(cr.usable_tools({"state": "verified", "codex": {"state": "not_logged_in"}}), ("claude",))
        self.assertEqual(cr.usable_tools({"state": "unknown", "codex": {}}), ())
        self.assertEqual(cr.usable_tools({}), ())


if __name__ == "__main__":
    unittest.main()
