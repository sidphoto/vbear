"""The meeting runner (P34-4). No real CLI: an owned synthetic script prints the stream-json a tool-less Claude Code would."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests.test_meetings import SHA, decision, finish, opinion, person, record
from vbear import agent_profiles as ap, config as cfg, meeting_runner as mr, meetings as mt, translations as tr
from vbear.jsonstore import StoreError

VERSION = "2.1.296"
FAKE = '''#!{python}
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
if args == ['--version']:
    print('{version} (Claude Code)')
    sys.exit(0)
assert args[args.index('--tools')+1] == ''
assert '--safe-mode' in args and '--strict-mcp-config' in args and '--no-session-persistence' in args and '--verbose' in args
assert args[args.index('--mcp-config')+1] == '{{"mcpServers":{{}}}}'
assert args[args.index('--output-format')+1] == 'stream-json'
assert '--input-format' not in args and '--allowedTools' not in args and '--dangerously-skip-permissions' not in args
schema = json.loads(args[args.index('--json-schema')+1])
assert not list(Path.cwd().iterdir())
assert set(os.environ) <= {{'PATH','HOME','USER','LOGNAME','LANG','TMPDIR','LC_CTYPE','__CF_USER_TEXT_ENCODING'}}
prompt = sys.stdin.read()
model = args[args.index('--model')+1]
budget = args[args.index('--max-budget-usd')+1]
with open({log!r}, 'a') as fh:
    fh.write(json.dumps({{'model': model, 'budget': budget, 'prompt': prompt, 'schema_keys': sorted(schema['properties'])}}) + chr(10))
kind = 'decision' if 'decision' in schema['properties'] else 'opinion'
{body}
'''
INIT = {"type": "system", "subtype": "init", "tools": ["StructuredOutput"], "mcp_servers": [], "model": "claude-sonnet-5-5"}
OPINION = {"stance": "支持", "summary": "可以做", "points": ["一"], "risks": [], "needs_chairman": False}
DECISION = {"decision": "照做", "rationale": "沒問題", "dissent_addressed": [], "actions": [{"type": "寫草稿", "text": "寫"}],
            "escalate": False, "escalate_reason": "", "follow_up_topics": []}


def good_body(cost=0.01, init=INIT, extra=""):
    return (f"print(json.dumps({init!r}))\n{extra}"
            f"out = {DECISION!r} if kind == 'decision' else {OPINION!r}\n"
            f"print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': out, 'total_cost_usd': {cost}}}))")


def profile(pid, position, tool="claude", model_id="", enabled=True, **extra):
    p = {"id": pid, "name": pid.upper(), "profession_role_id": None, "model": {"tool": tool, "model_id": model_id},
         "equipped_skill_ids": [], "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
         "enabled": enabled, "created_at": 1.0, "updated_at": 1.0, "position": position}
    p.update(extra)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-meeting-runner-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        home = self.root / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.log = self.root / "calls.jsonl"
        self.profiles = {p["id"]: p for p in (
            profile("ceo", "planner", model_id="claude-opus-5-5"), profile("pm", "pm"), profile("legal", "legal"),
            profile("acct", "accountant"), profile("eng", "executor", tool="codex", model_id="gpt-6-luna"))}
        self.task = {"id": "t-1", "title": "改按鈕", "goal": "讓它變大", "workdir": str(self.root / "project"), "status": "draft"}
        (self.root / "project").mkdir()
        self.runners = []

    def fake(self, body=None, name="fake-cli"):
        script = self.root / name
        script.write_text(FAKE.format(python=sys.executable, version=VERSION, log=str(self.log), body=body or good_body()))
        script.chmod(0o700)
        return script

    def runner(self, body=None, **kw):
        script = self.fake(body)
        r = mr.MeetingRunner(provider=lambda engine: (str(script), VERSION), **kw)
        self.runners.append(r)
        self.addCleanup(r.wait, 5)
        return r

    def sources(self, **conf):
        return mr.Sources(profile=self.profiles.get, task=lambda tid: self.task if tid == "t-1" else None,
                          flows=lambda tid: [], conf=conf)

    def body(self, **kw):
        body = {"topic": "要不要改按鈕", "chair_profile_id": "ceo", "speaker_profile_ids": ["pm", "legal"]}
        body.update(kw)
        return body

    def failing_runner(self, fail_kind="opinion", times=1, **kw):
        """A runner whose opinion calls fail ``times`` times (then work); decisions always work."""
        state = {"n": 0}

        self.prompts = []

        def call(spec, cancel):
            self.prompts.append(spec.prompt)
            if spec.kind == fail_kind and state["n"] < times:
                state["n"] += 1
                raise mr.CallFailed("cli_failed", {"cli_version": VERSION, "model_reported": None, "tools_reported": None,
                                                   "mcp_servers_reported": None, "exit_code": 1, "duration_ms": 3}, None)
            return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION,
                                 {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"],
                                  "mcp_servers_reported": [], "exit_code": 0, "duration_ms": 1}, Decimal("0.01"))
        runner = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=call, **kw)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        return runner

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_meeting(self, runner=None, body=None, **conf):
        runner = runner or self.runner()
        src = self.sources(**conf)
        preview = runner.preview(body or self.body(), src)
        self.assertTrue(preview["startable"], preview["blockers"])
        view = runner.start(preview["preview_id"], src)
        runner.wait(10)
        return runner, mt.view(mt.load(view["id"]))


class PositionTests(Base):
    def test_who_may_sit_is_decided_by_position_enabled_and_one_card_per_position(self):
        runner = self.runner()
        src = self.sources()
        self.profiles["ceo2"] = profile("ceo2", "planner")
        self.profiles["pm2"] = profile("pm2", "pm")
        self.profiles["off"] = profile("off", "social", enabled=False)
        self.profiles["gate"] = profile("gate", "reviewer", tool="codex")
        self.profiles["none"] = profile("none", None)
        self.profiles["old"] = profile("old", "records")  # retired: reads as PM
        for change in ({"chair_profile_id": "pm"}, {"chair_profile_id": "nobody"}, {"speaker_profile_ids": []},
                       {"speaker_profile_ids": ["pm", "pm"]}, {"speaker_profile_ids": ["pm", "pm2"]}, {"speaker_profile_ids": ["off"]},
                       {"speaker_profile_ids": ["gate"]}, {"speaker_profile_ids": ["none"]}, {"speaker_profile_ids": ["ceo"]},
                       {"speaker_profile_ids": ["a1", "a2", "a3", "a4", "a5", "a6", "a7"]}, {"speaker_profile_ids": "pm"},
                       {"speaker_profile_ids": [1]}, {"chair_profile_id": 5}):
            with self.subTest(change=change), self.assertRaises(mt.MeetingError) as cm:
                runner.preview(self.body(**change), src)
            self.assertEqual(cm.exception.code, "bad_request")
        self.profiles["ceo"]["enabled"] = False
        with self.assertRaises(mt.MeetingError):
            runner.preview(self.body(), src)
        self.profiles["ceo"]["enabled"] = True
        self.assertTrue(runner.preview(self.body(speaker_profile_ids=["old"]), src)["startable"])

    def test_a_codex_card_speaks_through_claude_and_is_marked_as_proxy(self):
        runner = self.runner()
        preview = runner.preview(self.body(speaker_profile_ids=["eng", "pm"]), self.sources())
        eng = next(p for p in preview["participants"] if p["profile_id"] == "eng")
        self.assertEqual((eng["tool"], eng["proxy"], eng["model"]), ("codex", True, "sonnet"))
        self.assertNotIn("gpt-6-luna", json.dumps(preview))
        ceo = preview["chair"]
        self.assertEqual((ceo["proxy"], ceo["model"]), (False, "claude-opus-5-5"))

    def test_a_claude_card_without_a_usable_model_uses_the_positions_alias(self):
        self.profiles["pm"]["model"]["model_id"] = "--bad model"
        preview = self.runner().preview(self.body(), self.sources())
        self.assertEqual(next(p for p in preview["participants"] if p["profile_id"] == "pm")["model"], "haiku")


class PreviewTests(Base):
    def test_the_preview_shows_every_text_that_would_be_sent_and_where(self):
        self.profiles["pm"]["instructions"] = "我自己寫的 PM 指示"
        preview = self.runner().preview(self.body(context="補充", task_id="t-1", flags=["spend"]), self.sources())
        pm = next(p for p in preview["participants"] if p["profile_id"] == "pm")
        self.assertEqual(pm["instructions"], "我自己寫的 PM 指示")
        self.assertTrue(pm["prompt"].startswith("我自己寫的 PM 指示"))
        self.assertIn("改按鈕", pm["prompt"])
        self.assertNotIn(str(self.root / "project"), json.dumps(preview, ensure_ascii=False))
        self.assertEqual(len(pm["prompt_sha256"]), 64)
        self.assertIn("Anthropic", preview["disclosure"])
        self.assertIn("估值", preview["cost_note"])
        self.assertEqual((preview["calls"], preview["reserve_usd"]), (3, "0.6"))
        self.assertEqual(preview["cli"], {"version": VERSION, "verified": True})
        self.assertEqual(preview["chair"]["dynamic"], True)
        self.assertFalse((cfg.state_dir() / "meetings").exists())  # a preview writes nothing

    def test_a_card_without_its_own_instructions_uses_the_positions_default(self):
        preview = self.runner().preview(self.body(), self.sources())
        legal = next(p for p in preview["participants"] if p["profile_id"] == "legal")
        self.assertIn("法務經理", legal["instructions"])
        self.assertEqual(legal["instructions"], ap.instructions_of(self.profiles["legal"])["text"])

    def test_the_pm_gets_a_progress_summary_and_the_accountant_the_spend_slot(self):
        self.profiles["acct"]["position"] = "accountant"
        preview = self.runner().preview(self.body(speaker_profile_ids=["pm", "acct"], task_id="t-1"), self.sources())
        by = {p["profile_id"]: p for p in preview["participants"]}
        self.assertIn("進度", by["pm"]["prompt"])
        self.assertIn("沒有流程紀錄", by["pm"]["prompt"])
        self.assertTrue(by["acct"]["dynamic"])
        self.assertFalse(by["pm"]["dynamic"])

    def test_it_is_not_startable_until_the_version_has_passed_the_no_tool_check(self):
        def refuse(engine):
            raise tr.TranslationError("boundary_unverified")
        preview = mr.MeetingRunner(provider=refuse).preview(self.body(), self.sources())
        self.assertFalse(preview["startable"])
        self.assertIsNone(preview["preview_id"])
        self.assertEqual(preview["blockers"][0]["code"], "boundary_unverified")
        self.assertIn("檢查", preview["blockers"][0]["message"])

    def test_the_reserve_must_fit_the_meeting_and_what_is_left_of_today(self):
        runner = self.runner()
        too_big = runner.preview(self.body(speaker_profile_ids=["pm", "legal", "acct"]), self.sources(meeting_limits={"per_call_usd": 0.5, "meeting_usd": 1.5, "daily_usd": 3}))
        self.assertIn("budget", [b["code"] for b in too_big["blockers"]])  # 4 calls x 0.5 = 2.0 > 1.5
        spent = record("m-111111111111")
        for seq in (1, 2, 3):
            finish(spent, seq, opinion() if seq < 3 else decision(), cost="1.2")
        store = mt.MeetingStore(spent["id"])
        with store.locked():
            store.save(spent)
        today = runner.preview(self.body(), self.sources())  # 3.6 spent of 3.00: red
        self.assertIn("budget", [b["code"] for b in today["blockers"]])
        self.assertEqual(today["today"]["lamp"], "red")
        yellow = runner.preview(self.body(), self.sources(meeting_limits={"per_call_usd": 0.2, "meeting_usd": 1.5, "daily_usd": 4.2}))
        self.assertEqual(yellow["today"]["lamp"], "yellow")  # 3.6 of 4.2 is 85%: allowed, 0.6 reserve still fits
        self.assertTrue(yellow["startable"])

    def test_unknown_or_malformed_fields_are_refused(self):
        runner, src = self.runner(), self.sources()
        for bad in ({"extra": 1}, {"topic": ""}, {"topic": 5}, {"topic": "x" * 501}, {"context": "x" * 4001}, {"flags": ["nope"]},
                    {"task_id": "missing"}, {"task_id": 5}, {"flags": "spend"}, {"context": True}):
            with self.subTest(bad=bad), self.assertRaises(mt.MeetingError) as cm:
                runner.preview(self.body(**bad), src)
            self.assertIn(cm.exception.code, ("bad_request", "not_found"))
        for body in (None, [], "x"):
            with self.assertRaises(mt.MeetingError):
                runner.preview(body, src)

    def test_a_preview_is_used_once_and_expires_after_five_minutes(self):
        clock = [1000.0]
        runner = self.runner(clock=lambda: clock[0])
        src = self.sources()
        first = runner.preview(self.body(), src)
        runner.start(first["preview_id"], src)
        runner.wait(10)
        with self.assertRaises(mt.MeetingError) as cm:
            runner.start(first["preview_id"], src)
        self.assertEqual(cm.exception.code, "preview_expired")
        second = runner.preview(self.body(), src)
        clock[0] += 301
        with self.assertRaises(mt.MeetingError) as cm:
            runner.start(second["preview_id"], src)
        self.assertEqual(cm.exception.code, "preview_expired")
        for bad in ("pv-nothing", None, 5, "../x"):
            with self.assertRaises(mt.MeetingError):
                runner.start(bad, src)

    def test_a_card_that_changed_after_the_preview_makes_it_stale(self):
        runner, src = self.runner(), self.sources()
        preview = runner.preview(self.body(), src)
        self.profiles["pm"]["instructions"] = "改了"
        with self.assertRaises(mt.MeetingError) as cm:
            runner.start(preview["preview_id"], src)
        self.assertEqual(cm.exception.code, "stale_preview")

    def test_a_different_cli_version_than_the_one_previewed_is_refused(self):
        script = self.fake()
        versions = iter([VERSION, "2.1.301"])
        runner = mr.MeetingRunner(provider=lambda engine: (str(script), next(versions)))
        src = self.sources()
        preview = runner.preview(self.body(), src)
        with self.assertRaises(mt.MeetingError) as cm:
            runner.start(preview["preview_id"], src)
        self.assertEqual(cm.exception.code, "stale_preview")


class RunTests(Base):
    def test_every_speaker_answers_alone_then_the_ceo_decides_with_evidence(self):
        runner, m = self.run_meeting(body=self.body(task_id="t-1", context="補充"))
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "done", "done"])
        self.assertEqual([t["kind"] for t in m["turns"]], ["opinion", "opinion", "decision"])
        for t in m["turns"]:
            self.assertEqual(t["attempts"], 1)
            self.assertEqual(len(t["prompt_sha256"]), 64)
            ev = t["evidence"]
            self.assertEqual((ev["cli_version"], ev["tools_reported"], ev["mcp_servers_reported"], ev["exit_code"], ev["cost_source"]),
                             (VERSION, ["StructuredOutput"], [], 0, "cli"))
            self.assertEqual((ev["model_reported"], ev["cost_usd"]), ("claude-sonnet-5-5", "0.01"))
        self.assertEqual(m["spent_usd"], "0.03")
        self.assertEqual(m["status"], "decided")
        self.assertEqual(m["chairman"]["state"], "not_needed")
        calls = self.calls()
        self.assertEqual([("actions" in c["schema_keys"]) for c in calls], [False, False, True])
        self.assertEqual([c["model"] for c in calls], ["haiku", "sonnet", "claude-opus-5-5"])
        self.assertEqual({c["budget"] for c in calls}, {"0.2"})
        # speakers never see each other; the CEO sees them all
        self.assertTrue(all("各職位的發言" not in c["prompt"] for c in calls[:2]))
        self.assertIn("各職位的發言", calls[2]["prompt"])
        self.assertIn("可以做", calls[2]["prompt"])
        self.assertTrue(all(str(self.root / "project") not in c["prompt"] for c in calls))

    def test_the_prompt_hash_of_a_speaker_is_the_one_in_the_preview(self):
        runner = self.runner()
        src = self.sources()
        preview = runner.preview(self.body(), src)
        runner.start(preview["preview_id"], src)
        runner.wait(10)
        m = mt.load(mt.meeting_ids()[0])
        shown = {p["profile_id"]: p["prompt_sha256"] for p in preview["participants"]}
        done = {t["profile_id"]: t["prompt_sha256"] for t in m["turns"]}
        self.assertEqual({k: done[k] for k in shown}, shown)

    def test_nothing_is_written_to_the_project_the_flows_or_the_tasks(self):
        before = sorted(p.name for p in (self.root / "project").iterdir())
        self.run_meeting(body=self.body(task_id="t-1"))
        self.assertEqual(sorted(p.name for p in (self.root / "project").iterdir()), before)
        names = {p.name for p in cfg.state_dir().iterdir()}
        self.assertNotIn("flows.json", names)
        self.assertNotIn("tasks.json", names)
        self.assertTrue({"meetings", "meeting-worker.lock"} <= names)
        meeting_file = next((cfg.state_dir() / "meetings").glob("m-*.json"))
        self.assertEqual(oct(meeting_file.stat().st_mode & 0o777), "0o600")

    def test_a_flag_the_chairman_ticked_holds_the_meeting_for_the_chairman(self):
        _, m = self.run_meeting(body=self.body(flags=["spend"]))
        self.assertEqual((m["status"], m["major"], m["chairman"]["state"]), ("waiting_chairman", True, "pending"))
        self.assertEqual([r["id"] for r in m["rules"]], ["R1"])
        self.assertTrue(mt.load(m["id"])["major_at_decision"])

    def test_the_cli_reports_its_cost_and_a_missing_cost_is_the_worst_case(self):
        body = ("print(json.dumps(%r))\nout = %r if kind == 'decision' else %r\n"
                "print(json.dumps({'type': 'result', 'is_error': False, 'structured_output': out}))" % (INIT, DECISION, OPINION))
        _, m = self.run_meeting(self.runner(body))
        self.assertEqual([t["state"] for t in m["turns"]], ["done"] * 3)
        for t in m["turns"]:
            self.assertEqual((t["evidence"]["cost_usd"], t["evidence"]["cost_source"]), ("0.2", "worst_case"))
        self.assertEqual(m["spent_usd"], "0.6")

    def test_the_accountant_is_told_what_the_meeting_has_cost_so_far(self):
        self.profiles["acct"]["position"] = "accountant"
        self.run_meeting(body=self.body(speaker_profile_ids=["pm", "acct"]))
        prompt = self.calls()[1]["prompt"]
        self.assertIn("會議花費", prompt)
        self.assertIn("0.01", prompt)

    def test_a_proxy_turn_runs_the_same_way_and_the_record_says_so(self):
        _, m = self.run_meeting(body=self.body(speaker_profile_ids=["eng"]))
        self.assertTrue(next(p for p in m["participants"] if p["profile_id"] == "eng")["proxy"])
        self.assertEqual(self.calls()[0]["model"], "sonnet")

    def test_only_one_meeting_runs_at_a_time(self):
        gate = threading.Event()

        def call(spec, cancel):
            gate.wait(5)
            return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION, {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [], "exit_code": 0, "duration_ms": 1}, Decimal("0.01"))
        runner = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=call)
        src = self.sources()
        first = runner.preview(self.body(), src)
        second = runner.preview(self.body(), src)
        runner.start(first["preview_id"], src)
        self.assertTrue(runner.preview(self.body(), src)["blockers"][0]["code"] == "busy")
        with self.assertRaises(mt.MeetingError) as cm:
            runner.start(second["preview_id"], src)
        self.assertEqual(cm.exception.code, "busy")
        gate.set()
        runner.wait(10)


class FailureTests(Base):
    def test_a_failed_speaker_is_recorded_at_the_worst_case_and_the_meeting_goes_to_the_chairman(self):
        _, m = self.run_meeting(self.failing_runner())
        self.assertEqual([t["state"] for t in m["turns"]], ["failed", "done", "done"])
        failed = m["turns"][0]
        self.assertEqual((failed["error_code"], failed["attempts"], failed["output"]), ("cli_failed", 1, None))
        self.assertEqual((failed["evidence"]["cost_usd"], failed["evidence"]["cost_source"]), ("0.2", "worst_case"))
        self.assertEqual((m["status"], m["major"], m["retryable"]), ("waiting_chairman", True, [1]))
        self.assertIn("R7", [r["id"] for r in m["rules"]])
        ceo_prompt = self.prompts[-1]  # the CEO is told who did not speak, and is not given an invented opinion
        self.assertIn("沒有發言（發言失敗）", ceo_prompt)

    def test_a_retry_is_previewed_costed_and_confirmed_and_reruns_the_decision(self):
        runner = self.failing_runner(times=1)
        _, m = self.run_meeting(runner)
        src = self.sources()
        preview = runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual((preview["startable"], preview["calls"], preview["reserve_usd"]), (True, 2, "0.4"))
        self.assertIn("你是專案經理", preview["prompt"])
        runner.retry(preview["preview_id"], src)
        runner.wait(10)
        m = mt.view(mt.load(m["id"]))
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "done", "done"])
        self.assertEqual([t["attempts"] for t in m["turns"]], [2, 1, 2])
        self.assertEqual(m["turns"][0]["evidence"]["cost_usd"], "0.21")  # the worst case of the failure + the retry
        self.assertEqual(m["turns"][2]["evidence"]["cost_usd"], "0.02")
        # the first decision was made with a speaker missing (R7), and a verdict stored at a decision only goes up: the
        # meeting stays with the chairman although nothing is wrong now
        self.assertEqual((m["rules"], m["major"], m["status"]), ([], True, "waiting_chairman"))

    def test_two_retries_at_most_then_the_turn_is_blocked(self):
        runner = self.failing_runner(times=99)
        _, m = self.run_meeting(runner)
        src = self.sources()
        for expected in ("failed", "blocked"):
            preview = runner.retry_preview(m["id"], {"seq": 1}, src)
            runner.retry(preview["preview_id"], src)
            runner.wait(10)
            m = mt.view(mt.load(m["id"]))
            self.assertEqual(m["turns"][0]["state"], expected)
        self.assertEqual(m["turns"][0]["attempts"], 3)
        self.assertNotIn(1, m["retryable"])
        with self.assertRaises(mt.MeetingError) as cm:
            runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual(cm.exception.code, "not_retryable")
        self.assertIn("R7", [r["id"] for r in m["rules"]])

    def test_a_done_turn_cannot_be_retried_and_a_final_chairman_closes_retries(self):
        runner = self.failing_runner()
        _, m = self.run_meeting(runner)
        src = self.sources()
        with self.assertRaises(mt.MeetingError) as cm:
            runner.retry_preview(m["id"], {"seq": 2}, src)
        self.assertEqual(cm.exception.code, "not_retryable")
        for bad in ({}, {"seq": "1"}, {"seq": True}, {"seq": 99}, {"seq": 1, "x": 1}):
            with self.subTest(bad=bad), self.assertRaises(mt.MeetingError):
                runner.retry_preview(m["id"], bad, src)
        runner.chairman(m["id"], {"decision": "reject"})
        with self.assertRaises(mt.MeetingError) as cm:
            runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual(cm.exception.code, "already_decided")

    def test_a_retry_is_refused_when_the_card_or_the_task_changed_since(self):
        runner = self.failing_runner()
        _, m = self.run_meeting(runner, body=self.body(task_id="t-1"))
        src = self.sources()
        self.task["goal"] = "別的目標"
        with self.assertRaises(mt.MeetingError) as cm:
            runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual(cm.exception.code, "changed")
        self.task["goal"] = "讓它變大"
        self.profiles["pm"]["instructions"] = "改了"
        with self.assertRaises(mt.MeetingError) as cm:
            runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual(cm.exception.code, "changed")

    def test_a_failed_decision_is_retried_on_its_own(self):
        runner = self.failing_runner("decision")
        _, m = self.run_meeting(runner)
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "done", "failed"])
        self.assertEqual(m["status"], "incomplete")
        src = self.sources()
        preview = runner.retry_preview(m["id"], {"seq": 3}, src)
        self.assertEqual(preview["calls"], 1)
        runner.retry(preview["preview_id"], src)
        runner.wait(10)
        self.assertEqual(mt.view(mt.load(m["id"]))["status"], "decided")

    def test_no_opinion_at_all_means_the_ceo_is_not_asked(self):
        _, m = self.run_meeting(self.failing_runner(times=99), body=self.body(speaker_profile_ids=["pm"]))
        self.assertEqual([t["state"] for t in m["turns"]], ["failed", "skipped"])
        self.assertEqual(m["turns"][1]["error_code"], "no_opinions")

    def test_a_retry_that_would_not_fit_the_limits_is_not_startable(self):
        runner = self.failing_runner()
        _, m = self.run_meeting(runner)
        rec = mt.load(m["id"])
        rec["limits"]["meeting_usd"] = "0.3"  # 0.22 spent so far: 0.08 is left and a retry reserves 0.4
        store = mt.MeetingStore(m["id"])
        with store.locked():
            store.save(rec)
        preview = runner.retry_preview(m["id"], {"seq": 1}, self.sources())
        self.assertFalse(preview["startable"])
        self.assertEqual(preview["blockers"][0]["code"], "budget")
        self.assertIsNone(preview["preview_id"])


class BudgetAndBoundaryTests(Base):
    def test_calls_that_cost_less_than_the_reserve_all_fit(self):
        runner = self.runner(good_body(cost=0.45))
        src = self.sources(meeting_limits={"per_call_usd": 0.5, "meeting_usd": 1.5, "daily_usd": 9})
        preview = runner.preview(self.body(), src)
        self.assertTrue(preview["startable"])  # 1.5 reserved = exactly the limit
        runner.start(preview["preview_id"], src)
        runner.wait(10)
        m = mt.view(mt.load(mt.meeting_ids()[0]))
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "done", "done"])  # 0.45 x 3 = 1.35 <= 1.5: all fit
        self.assertEqual(m["spent_usd"], "1.35")

    def test_a_turn_that_would_pass_the_limit_is_skipped_with_the_budget_code(self):
        runner = self.runner(good_body(cost=0.9))
        src = self.sources(meeting_limits={"per_call_usd": 0.5, "meeting_usd": 1.5, "daily_usd": 9})
        preview = runner.preview(self.body(), src)
        runner.start(preview["preview_id"], src)
        runner.wait(10)
        m = mt.view(mt.load(mt.meeting_ids()[0]))
        # 0.9 after the first call; 0.9 + 0.5 per-call reserve = 1.4 fits, 1.8 + 0.5 does not
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "done", "skipped"])
        self.assertEqual(m["turns"][2]["error_code"], "budget")
        self.assertIn("R7", [r["id"] for r in m["rules"]])

    def test_an_init_with_a_tool_stops_the_call_at_once_revokes_the_version_and_adopts_nothing(self):
        store = tr.BoundaryStore()
        with store.locked():
            store.save({VERSION: time.time(), "2.1.200": time.time()})
        bad = dict(INIT, tools=["StructuredOutput", "Bash"])
        started = time.monotonic()
        runner = self.runner("print(json.dumps(%r), flush=True)\ntime.sleep(30)" % (bad,))
        _, m = self.run_meeting(runner)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(m["turns"][0]["state"], "failed")
        self.assertEqual(m["turns"][0]["error_code"], "tools_not_clean")
        self.assertIsNone(m["turns"][0]["output"])
        self.assertEqual([t["state"] for t in m["turns"][1:]], ["skipped", "skipped"])
        self.assertEqual({t["error_code"] for t in m["turns"][1:]}, {"boundary_revoked"})
        self.assertNotIn(VERSION, store.load())
        self.assertIn("2.1.200", store.load())
        self.assertEqual(len(self.calls()), 1)

    def test_an_mcp_server_a_tool_use_or_a_second_init_is_not_clean_either(self):
        cases = {
            "mcp": "print(json.dumps(%r))" % (dict(INIT, mcp_servers=[{"name": "x"}]),),
            "no tools key": "print(json.dumps(%r))" % ({k: v for k, v in INIT.items() if k != "tools"},),
            "tool use": (good_body(extra="print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {}}]}}))\n")),
            "two inits": "print(json.dumps(%r))\nprint(json.dumps(%r))" % (INIT, INIT),
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                self.log.unlink(missing_ok=True)
                for p in (cfg.state_dir() / "meetings").glob("*"):
                    p.unlink()
                runner, m = self.run_meeting(self.runner(body))
                self.assertEqual(m["turns"][0]["state"], "failed", name)
                self.assertIn(m["turns"][0]["error_code"], ("tools_not_clean", "invalid_output"))
                self.assertIsNone(m["turns"][0]["output"])

    def test_an_assistant_event_that_only_calls_the_structured_output_is_fine(self):
        ok = "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'StructuredOutput', 'input': {}}]}}))\n"
        _, m = self.run_meeting(self.runner(good_body(extra=ok)))
        self.assertEqual(m["turns"][0]["state"], "done")

    def test_a_result_that_is_an_error_or_missing_or_of_the_wrong_shape_is_a_failure(self):
        for name, tail in {
            "is_error": "print(json.dumps({'type': 'result', 'is_error': True, 'total_cost_usd': 0.02}))",
            "no result": "pass",
            "no structured output": "print(json.dumps({'type': 'result', 'is_error': False, 'total_cost_usd': 0.02}))",
            "wrong schema": "print(json.dumps({'type': 'result', 'is_error': False, 'structured_output': {'a': 1}, 'total_cost_usd': 0.02}))",
            "text not json": "print('not json')",
            "negative cost": "print(json.dumps({'type': 'result', 'is_error': False, 'structured_output': %r, 'total_cost_usd': -1}))" % (OPINION,),
        }.items():
            with self.subTest(name=name):
                for p in (cfg.state_dir() / "meetings").glob("*"):
                    p.unlink()
                runner, m = self.run_meeting(self.runner("print(json.dumps(%r))\n%s" % (INIT, tail)), body=self.body(speaker_profile_ids=["pm"]))
                self.assertEqual(m["turns"][0]["state"], "failed", name)
                self.assertIsNone(m["turns"][0]["output"])
                self.assertIn(m["turns"][0]["error_code"], ("invalid_output", "cli_error"))

    def test_a_simplified_answer_is_refused_and_not_kept(self):
        bad = dict(OPINION, summary="这个可以")
        body = "print(json.dumps(%r))\nprint(json.dumps({'type': 'result', 'is_error': False, 'structured_output': %r, 'total_cost_usd': 0.01}))" % (INIT, bad)
        _, m = self.run_meeting(self.runner(body), body=self.body(speaker_profile_ids=["pm"]))
        self.assertEqual((m["turns"][0]["state"], m["turns"][0]["error_code"]), ("failed", "not_traditional"))
        self.assertEqual(m["turns"][0]["evidence"]["cost_source"], "cli")

    def test_an_unconfirmed_process_group_blocks_later_meetings(self):
        runner = self.runner()
        src = self.sources()
        preview = runner.preview(self.body(), src)
        with mock.patch("vbear.headless_cli.group_exists", return_value=True), mock.patch("vbear.headless_cli.time.sleep"):
            runner.start(preview["preview_id"], src)
            runner.wait(30)
        m = mt.view(mt.load(mt.meeting_ids()[0]))
        self.assertEqual(m["turns"][0]["error_code"], "process_unconfirmed")
        self.assertTrue((cfg.state_dir() / "meeting-worker.blocked").exists())
        self.assertEqual([t["state"] for t in m["turns"][1:]], ["skipped", "skipped"])
        blocked = runner.preview(self.body(), src)
        self.assertEqual(blocked["blockers"][0]["code"], "process_unconfirmed")


class CancelRecoverChairmanTests(Base):
    def test_cancel_ends_the_running_call_and_cancels_the_rest(self):
        runner = self.runner("print(json.dumps(%r), flush=True)\ntime.sleep(30)" % (INIT,))
        src = self.sources()
        view = runner.start(runner.preview(self.body(), src)["preview_id"], src)
        for _ in range(100):
            if self.log.exists():
                break
            time.sleep(0.05)
        started = time.monotonic()
        runner.cancel(view["id"])
        runner.wait(10)
        self.assertLess(time.monotonic() - started, 8)
        m = mt.view(mt.load(view["id"]))
        self.assertEqual([t["state"] for t in m["turns"]], ["cancelled"] * 3)
        self.assertEqual(m["status"], "cancelled")
        self.assertEqual(m["turns"][0]["evidence"]["cost_source"], "worst_case")
        with self.assertRaises(mt.MeetingError) as cm:
            runner.cancel(view["id"])
        self.assertEqual(cm.exception.code, "not_running")

    def test_after_a_restart_a_running_turn_is_interrupted_at_the_worst_case_and_nothing_resumes(self):
        rec = record("m-0123456789ab")
        finish(rec, 1, opinion())
        rec["turns"][1].update(state="running", attempts=1, started_at=time.time())
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)
        runner = self.runner()
        m = mt.view(mt.load(rec["id"]))
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "interrupted", "interrupted"])
        self.assertEqual(m["turns"][1]["evidence"]["cost_source"], "worst_case")
        self.assertEqual(m["turns"][1]["evidence"]["cost_usd"], "0.2")
        self.assertIsNone(m["turns"][2]["evidence"])  # it never started: no cost
        self.assertEqual(m["retryable"], [2, 3])
        self.assertIn("R7", [r["id"] for r in m["rules"]])
        time.sleep(0.3)
        self.assertEqual(self.calls(), [])  # nothing ran again

    def test_a_turn_interrupted_with_no_attempts_left_is_blocked(self):
        rec = record("m-0123456789ab")
        rec["turns"][0].update(state="running", attempts=3, started_at=time.time())
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)
        self.runner()
        self.assertEqual(mt.load(rec["id"])["turns"][0]["state"], "blocked")

    def test_a_second_process_does_not_interrupt_a_meeting_another_one_is_running(self):
        rec = record("m-0123456789ab")
        rec["turns"][0].update(state="running", attempts=1, started_at=time.time())
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)
        from vbear import headless_cli
        fd = headless_cli.acquire_worker("meeting-worker")  # the other process holds the worker lock
        try:
            self.runner()
            self.assertEqual(mt.load(rec["id"])["turns"][0]["state"], "running")
        finally:
            os.close(fd)

    def finished(self, runner, **kw):
        body = self.body(**kw)
        return self.run_meeting(runner, body=body)[1]

    def test_the_chairman_approves_only_a_decided_major_meeting_and_the_note_is_marked_unverified(self):
        runner = self.runner()
        m = self.finished(runner, flags=["publish"])
        out = runner.chairman(m["id"], {"decision": "approve", "note": "照辦"})
        self.assertEqual((out["status"], out["chairman"]["state"], out["chairman"]["note"]), ("approved", "approved", "照辦"))
        self.assertEqual(out["chairman"]["label"], "主控台記錄（未驗證身分）")
        self.assertIsNotNone(mt.load(m["id"])["chairman"]["at"])
        with self.assertRaises(mt.MeetingError) as cm:
            runner.chairman(m["id"], {"decision": "reject"})
        self.assertEqual(cm.exception.code, "already_decided")

    def test_a_meeting_that_is_not_major_needs_no_approval_but_can_be_vetoed(self):
        runner = self.runner()
        m = self.finished(runner)
        with self.assertRaises(mt.MeetingError) as cm:
            runner.chairman(m["id"], {"decision": "approve"})
        self.assertEqual(cm.exception.code, "not_needed")
        self.assertEqual(runner.chairman(m["id"], {"decision": "reject", "note": "不要"})["status"], "rejected")

    def test_an_unfinished_meeting_cannot_be_approved(self):
        runner = self.failing_runner("decision")
        _, m = self.run_meeting(runner)
        with self.assertRaises(mt.MeetingError) as cm:
            runner.chairman(m["id"], {"decision": "approve"})
        self.assertEqual(cm.exception.code, "not_decided")

    def test_chairman_input_is_validated_and_a_running_meeting_is_left_alone(self):
        runner = self.runner()
        m = self.finished(runner, flags=["publish"])
        for bad in ({}, {"decision": "maybe"}, {"decision": 1}, {"decision": "approve", "note": 5}, {"decision": "approve", "x": 1},
                    {"decision": "approve", "note": "x" * 501}, {"decision": "approve", "note": "a\x00"}):
            with self.subTest(bad=bad), self.assertRaises(mt.MeetingError):
                runner.chairman(m["id"], bad)
        self.assertEqual(mt.load(m["id"])["chairman"]["state"], "pending")

    def test_a_decision_is_only_a_record_nothing_in_the_runner_executes_it(self):
        import inspect
        source = inspect.getsource(mr)
        for word in ("os.system", "shell=True", "task_save", "save_task", "append_event", "create_flow"):
            self.assertNotIn(word, source)

    def test_list_get_ledger_and_delete(self):
        runner = self.runner()
        m = self.finished(runner)
        listing = runner.list()
        self.assertEqual([x["id"] for x in listing["meetings"]], [m["id"]])
        self.assertEqual(set(listing["meetings"][0]) >= {"id", "topic", "status", "major", "chairman_state", "spent_usd", "created_at"}, True)
        self.assertNotIn("turns", listing["meetings"][0])
        self.assertEqual(runner.get(m["id"])["id"], m["id"])
        ledger = runner.ledger({})
        self.assertEqual((ledger["spent_usd"], ledger["daily_usd"], ledger["lamp"], ledger["running"]), ("0.03", "3", "green", None))
        runner.delete(m["id"])
        self.assertEqual(runner.list()["meetings"], [])
        with self.assertRaises(mt.MeetingError):
            runner.get(m["id"])

    def test_a_damaged_meeting_is_listed_as_blocked_and_the_others_still_show(self):
        runner = self.runner()
        m = self.finished(runner)
        bad = mt.MeetingStore("m-ffffffffffff")
        bad.path().write_text("{broken")
        for _ in range(2):  # the first read quarantines the file; the meeting stays in the list as blocked
            listing = runner.list()["meetings"]
            self.assertEqual({x["id"]: x.get("blocked", False) for x in listing}, {m["id"]: False, "m-ffffffffffff": True})
        with self.assertRaises(mt.MeetingError) as cm:
            runner.delete("m-ffffffffffff")
        self.assertEqual(cm.exception.code, "storage")

    def test_the_meeting_count_is_capped(self):
        runner = self.runner()
        with mock.patch.object(mt, "MAX_MEETINGS", 1):
            self.finished(runner)
            src = self.sources()
            with self.assertRaises(mt.MeetingError) as cm:
                runner.start(runner.preview(self.body(), src)["preview_id"], src)
            self.assertEqual(cm.exception.code, "too_many")

    def test_a_running_meeting_cannot_be_deleted(self):
        runner = self.runner("print(json.dumps(%r), flush=True)\ntime.sleep(30)" % (INIT,))
        src = self.sources()
        view = runner.start(runner.preview(self.body(), src)["preview_id"], src)
        with self.assertRaises(mt.MeetingError) as cm:
            runner.delete(view["id"])
        self.assertEqual(cm.exception.code, "running")
        runner.cancel(view["id"])
        runner.wait(10)


class ProductionProviderTests(Base):
    def test_the_real_provider_needs_a_passed_no_tool_check_for_the_exact_version(self):
        script = self.fake()
        with mock.patch.object(tr.shutil, "which", return_value=str(script)):
            runner = mr.MeetingRunner()
            preview = runner.preview(self.body(), self.sources())
            self.assertEqual(preview["blockers"][0]["code"], "boundary_unverified")
            self.assertFalse(preview["startable"])
            self.assertEqual(preview["cli"]["verified"], False)
            store = tr.BoundaryStore()
            with store.locked():
                store.save({VERSION: time.time()})
            preview = runner.preview(self.body(), self.sources())
            self.assertTrue(preview["startable"], preview["blockers"])
            runner.start(preview["preview_id"], self.sources())
            runner.wait(10)
            self.assertEqual(mt.view(mt.load(mt.meeting_ids()[0]))["status"], "decided")

    def test_the_meeting_argv_differs_from_the_translation_argv_in_three_values_only(self):
        a = tr.translation_argv("claude", "bin", "/x", mt.OPINION_SCHEMA)
        b = mr.meeting_argv("bin", "sonnet", mt.OPINION_SCHEMA, Decimal("0.2"))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(diff, [("claude-haiku-5-5", "sonnet"), ("json", "stream-json"), ("0.05", "0.2")])
        self.assertEqual(b[len(a):], ["--verbose"])


if __name__ == "__main__":
    unittest.main()
