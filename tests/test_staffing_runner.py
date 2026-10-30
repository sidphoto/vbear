"""Running a staffing meeting (P35-2): the speakers VBear suggests speak one after another, then the CEO writes a staffing
proposal; the money, the clock, the worker shared with the meetings, a retry, a restart and the chairman's record. No
real CLI: an owned synthetic script prints what a tool-less Claude Code would, or a fake call answers in its place."""
import hashlib
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

from vbear import agent_profiles as ap, board_engine as be, config as cfg, meeting_runner as mr, meetings as mt
from vbear import staffing as st, staffing_runner as sr, translations as tr

VERSION = "2.1.296"
INIT = {"type": "system", "subtype": "init", "tools": ["StructuredOutput"], "mcp_servers": [], "model": "claude-sonnet-5-5"}
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}
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
assert not list(Path.cwd().iterdir())
assert set(os.environ) <= {{'PATH','HOME','USER','LOGNAME','LANG','TMPDIR','LC_CTYPE','__CF_USER_TEXT_ENCODING'}}
schema = json.loads(args[args.index('--json-schema')+1])
kind = 'proposal' if 'opinions_used' in schema['properties'] else 'opinion'
prompt = sys.stdin.read()
with open({log!r}, 'a') as fh:
    fh.write(json.dumps({{'kind': kind, 'model': args[args.index('--model')+1], 'budget': args[args.index('--max-budget-usd')+1],
                         'effort': args[args.index('--effort')+1], 'schema_keys': sorted(schema['properties']),
                         'prompt': prompt}}) + chr(10))
{body}
'''


def card(pid, position, tool="claude", *, enabled=True, model_id="", updated=1.0, instructions=None, name=None):
    p = {"id": pid, "name": name or f"虛構{pid.upper()}", "profession_role_id": None, "model": {"tool": tool, "model_id": model_id},
         "equipped_skill_ids": [], "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
         "enabled": enabled, "created_at": 1.0, "updated_at": updated, "position": position}
    if instructions is not None:
        p["instructions"] = instructions
    return p


def skill(sid, name, tool="claude", activation="active", cats=()):
    return {"skill_id": sid, "name": name, "invoke_name": name, "tool": tool, "read_by": [], "scope": "user",
            "activation": activation, "mtime": 1, "excerpt": f"{name}（虛構）", "categories": list(cats)}


def opinion(eng="", gap="授權", level="中"):
    return {"summary": "需要會做前端的人", "needs": [{"what": "網站前端", "position": "executor"}],
            "recommend": [{"card": eng, "position": "executor", "slot": "executor", "why": "會做前端"}] if eng else [],
            "skills": [], "skill_gaps": [{"need": "圖片授權檢查", "category": "legal", "search_words": [gap]}],
            "risks": [{"level": level, "text": "圖片授權不明", "source": ""}]}


def place(slot, alias):
    return {"slot": slot, "pick": "existing", "card": alias, "new_ref": "", "reason": "合適", "skills": []}


def proposal(a, used=("legal",)):
    return {"summary": "全端工程師做，Codex 審查", "team": [place("planner", a["ceo"]), place("executor", a["eng"]), place("reviewer1", a["rev"])],
            "staff": [], "new_cards": [], "skill_gaps": [], "risks": [], "questions_for_chairman": [],
            "opinions_used": [{"from": p, "point": "先查授權", "adopted": True, "why": "範圍有圖片"} for p in used]}


def long_opinion():
    w = "長"
    return {"summary": w * 120, "needs": [{"what": w * 120, "position": "executor"}] * 5,
            "recommend": [{"card": "", "position": "executor", "slot": "staff", "why": w * 200}] * 4, "skills": [],
            "skill_gaps": [{"need": w * 100, "category": "other", "search_words": [w * 20] * 3}] * 3,
            "risks": [{"level": "低", "text": w * 200, "source": w * 200}] * 5}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-staffing-runner-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        home = self.root / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.log = self.root / "calls.jsonl"
        self.profiles = {p["id"]: p for p in (
            card("ceo", "planner", model_id="claude-opus-5-5"), card("pm", "pm"), card("law", "legal"), card("acct", "accountant"),
            card("eng", "executor"), card("rev", "reviewer", tool="codex"), card("off", "art", tool="agy", enabled=False))}
        self.task = {"id": "t-1", "title": "官網改版（虛構）", "goal": "把首頁改成新版型，並確認圖片授權", "scope": ["前端頁面"],
                     "deliverables": ["新的首頁"], "status": "todo", "folder": "/Users/someone/secret-project"}
        self.skills = [skill("s-front", "網站前端", cats=["frontend"]), skill("s-law", "授權檢查", cats=["legal"]),
                       skill("s-codex", "codex-review", tool="codex", cats=["quality"])]
        self.summaries = {}
        self.runners = []

    def aliases(self):
        inputs = st.build_inputs(self.task, list(self.profiles.values()), self.skills, summaries=self.summaries)
        return {c["profile_id"]: c["alias"] for c in inputs["cards"]}

    def sources(self, **conf):
        return sr.StaffingSources(profile=self.profiles.get, task=lambda tid: self.task if tid == "t-1" else None,
                                  flows=lambda tid: [], profiles=lambda: list(self.profiles.values()), skills=lambda: list(self.skills),
                                  summaries=lambda: dict(self.summaries), conf=conf)

    def body(self, **kw):
        body = {"task_id": "t-1", "chair_profile_id": "ceo", "speaker_profile_ids": ["pm", "law"]}
        body.update(kw)
        return body

    def answer(self, spec):
        a = self.aliases()
        return proposal(a) if spec.kind == "proposal" else opinion(a["eng"])

    def board(self, call=None, **kw):
        self.specs = []

        def fake(spec, cancel):
            self.specs.append(spec)
            return mr.CallResult(self.answer(spec), dict(EVIDENCE), Decimal("0.01"))
        runner = sr.StaffingRunner(provider=lambda e: ("x", VERSION), call=call or fake, **kw)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        return runner

    def script(self, body):
        script = self.root / "fake-cli"
        script.write_text(FAKE.format(python=sys.executable, version=VERSION, log=str(self.log), body=body))
        script.chmod(0o700)
        return script

    def cli_board(self, body):
        script = self.script(body)
        runner = sr.StaffingRunner(provider=lambda e: (str(script), VERSION))
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        return runner

    def good_body(self, cost=0.01):
        a = self.aliases()
        return (f"print(json.dumps({INIT!r}))\n"
                f"out = {proposal(a)!r} if kind == 'proposal' else {opinion(a['eng'])!r}\n"
                f"print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': out, 'total_cost_usd': {cost}}}))")

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_board(self, runner, body=None, **conf):
        src = self.sources(**conf)
        preview = runner.preview(body or self.body(), src)
        self.assertTrue(preview["startable"], preview["blockers"])
        view = runner.start(preview["preview_id"], src)
        runner.wait(10)
        return st.view(st.load(view["id"]))


class RunTests(Base):
    def test_the_speakers_speak_in_order_alone_then_the_ceo_proposes_through_the_cli(self):
        m = self.run_board(self.cli_board(self.good_body()), self.body(speaker_profile_ids=["pm", "law", "acct"]))
        calls = self.calls()
        self.assertEqual([c["kind"] for c in calls], ["opinion", "opinion", "opinion", "proposal"])
        self.assertEqual([(c["budget"], c["effort"]) for c in calls], [("0.2", "low")] * 3 + [("0.5", "medium")])
        self.assertEqual([c["model"] for c in calls],
                         [be.model_for(self.profiles[p], self.profiles[p]["position"]) for p in ("pm", "law", "acct")] + ["claude-opus-5-5"])
        self.assertEqual(calls[0]["schema_keys"], sorted(st.STAFF_OPINION_SCHEMA["properties"]))
        self.assertEqual(calls[-1]["schema_keys"], sorted(st.PROPOSAL_SCHEMA["properties"]))
        for c in calls[:3]:  # a speaker never sees another speaker
            self.assertNotIn("需要會做前端的人", c["prompt"])
        self.assertEqual(calls[-1]["prompt"].count("需要會做前端的人"), 3)
        self.assertEqual([t["state"] for t in m["turns"]], ["done"] * 4)
        self.assertEqual(m["status"], "ready")
        self.assertEqual(m["spent_usd"], "0.04")
        self.assertEqual(m["turns"][-1]["output"]["kept"]["opinions_used"][0]["from"], "legal")
        self.assertEqual([t["prompt_sha256"] for t in m["turns"]], [hashlib.sha256(c["prompt"].encode()).hexdigest() for c in calls])
        self.assertTrue(m["high_risk"] is False)

    def test_what_is_sent_names_cards_and_skills_by_alias_and_never_the_folder_or_an_id(self):
        self.run_board(self.cli_board(self.good_body()))
        for c in self.calls():
            for secret in ("secret-project", "/Users/someone", "s-front", "s-law", "s-codex"):
                self.assertNotIn(secret, c["prompt"])
            for pid in ("ceo", "law", "acct", "eng", "rev", "off"):  # the data is a JSON string inside the text
                self.assertNotIn(f'\\"{pid}\\"', c["prompt"])
            self.assertIn("C1", c["prompt"])
            self.assertIn("BEGIN_UNTRUSTED_JSON_STRING", c["prompt"])

    def test_the_ceo_is_told_who_did_not_speak_and_an_opinion_used_must_come_from_one_who_did(self):
        def call(spec, cancel):
            self.specs.append(spec)
            if spec.kind == "opinion" and len(self.specs) == 2:  # the legal manager fails
                raise mr.CallFailed("cli_failed", dict(EVIDENCE, exit_code=1), None)
            return mr.CallResult(self.answer(spec), dict(EVIDENCE), Decimal("0.01"))
        runner = self.board()
        runner.call = call
        m = self.run_board(runner)
        self.assertIn("沒有發言（發言失敗）", self.specs[-1].prompt)
        kept = m["turns"][-1]["output"]
        self.assertEqual(kept["kept"]["opinions_used"], [])
        self.assertIn("unknown_speaker", [n["code"] for n in kept["notes"]])

    def test_a_high_risk_is_shown_to_the_chairman_and_holds_nothing(self):
        def call(spec, cancel):
            out = proposal(self.aliases()) if spec.kind == "proposal" else opinion(level="高")
            return mr.CallResult(out, dict(EVIDENCE), Decimal("0.01"))
        m = self.run_board(self.board(call))
        self.assertTrue(m["high_risk"])
        self.assertEqual(m["status"], "ready")

    def test_a_disabled_card_is_on_the_list_but_cannot_speak(self):
        runner = self.board()
        with self.assertRaises(mt.MeetingError) as caught:
            runner.preview(self.body(speaker_profile_ids=["pm", "off"]), self.sources())
        self.assertEqual(caught.exception.code, "bad_request")
        m = self.run_board(runner)
        aliases = self.aliases()
        listed = {c["profile_id"]: c["enabled"] for c in m["sent"]["cards"]}
        self.assertIs(listed["off"], False)
        self.assertIn(aliases["off"], self.specs[-1].prompt)

    def test_nothing_but_the_staffing_folder_is_written(self):
        state = cfg.state_dir()

        def files():
            return {str(p.relative_to(state)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in state.rglob("*") if p.is_file()} if state.exists() else {}
        before = files()
        m = self.run_board(self.board())
        runner = self.runners[-1]
        runner.chairman(m["id"], {"decision": "adopt", "note": "照這樣組隊（虛構）"})
        after = files()
        changed = {k for k in after if before.get(k) != after[k]}
        self.assertTrue(changed)
        self.assertEqual({k for k in changed if not k.startswith("staffing/")}, {"meeting-worker.lock"})
        self.assertEqual((state / "meeting-worker.lock").read_bytes(), b"")
        self.assertFalse((state / "meetings").exists())


class SuggestAndPreviewTests(Base):
    def test_suggest_reads_the_task_and_the_cards_and_runs_nothing(self):
        runner = sr.StaffingRunner(provider=mock.Mock(side_effect=AssertionError("no CLI")), call=mock.Mock(side_effect=AssertionError))
        self.runners.append(runner)
        out = runner.suggest("t-1", self.sources())
        self.assertEqual([(s["profile_id"], s["position"]) for s in out["suggested"]], [("pm", "pm"), ("eng", "executor"), ("law", "legal")])
        self.assertTrue(all(s["why"] and s["name"] for s in out["suggested"]))
        self.assertIn("legal", [c["id"] for c in out["categories"]])
        self.assertEqual(out["chairs"], [{"profile_id": "ceo", "name": "虛構CEO"}])
        for bad in ("t-404", "../x", 3, None):
            with self.subTest(bad=bad), self.assertRaises(mt.MeetingError) as caught:
                runner.suggest(bad, self.sources())
            self.assertIn(caught.exception.code, ("bad_request", "not_found"))

    def test_the_preview_shows_every_text_the_reserve_the_suggestions_and_the_speed(self):
        runner = self.board()
        preview = runner.preview(self.body(note="先看授權（虛構）"), self.sources())
        self.assertTrue(preview["startable"])
        self.assertEqual([p["profile_id"] for p in preview["participants"]], ["pm", "law"])
        self.assertTrue(all(p["prompt"] and len(p["prompt_sha256"]) == 64 and p["effort"] == "low" for p in preview["participants"]))
        self.assertEqual((preview["chair"]["profile_id"], preview["chair"]["effort"], preview["chair"]["dynamic"]), ("ceo", "medium", True))
        self.assertIn("先看授權（虛構）", preview["participants"][0]["prompt"])
        self.assertEqual((preview["calls"], preview["reserve_usd"]), (3, "0.9"))
        self.assertEqual(preview["reserve"], {"speakers": 2, "per_call_usd": "0.2", "proposal_call_usd": "0.5"})
        self.assertEqual(preview["limits"], {"per_call_usd": "0.2", "proposal_call_usd": "0.5", "total_usd": "2", "daily_usd": "3"})
        self.assertEqual([(s["profile_id"], s["chosen"]) for s in preview["suggested"]], [("pm", True), ("eng", False), ("law", True)])
        self.assertEqual(preview["list"]["cards"], 7)
        self.assertEqual(preview["speed"]["max_minutes"], 15)
        self.assertNotIn("secret-project", json.dumps(preview, ensure_ascii=False))
        self.assertIn("Anthropic", preview["disclosure"])
        self.assertIn("估值", preview["cost_note"])

    def test_the_request_is_strict(self):
        runner = self.board()
        for bad in ({"chair_profile_id": "ceo", "speaker_profile_ids": ["pm"]},
                    self.body(extra=1), self.body(task_id="../x"), self.body(task_id=3), self.body(note=3), self.body(note="x" * 501),
                    self.body(note="a\u0000b"), self.body(chair_profile_id="pm"), self.body(speaker_profile_ids=[]),
                    self.body(speaker_profile_ids=["pm", "pm"]), self.body(speaker_profile_ids=["rev"]), "x", None):
            with self.subTest(bad=bad), self.assertRaises(mt.MeetingError) as caught:
                runner.preview(bad, self.sources())
            self.assertEqual(caught.exception.code, "bad_request")
        with self.assertRaises(mt.MeetingError) as caught:
            runner.preview(self.body(task_id="t-404"), self.sources())
        self.assertEqual(caught.exception.code, "not_found")

    def test_a_task_card_too_long_for_the_text_is_refused_at_the_preview_and_never_cut(self):
        self.task["goal"] = "長" * 9000
        with self.assertRaises(mt.MeetingError) as caught:
            self.board().preview(self.body(), self.sources())
        self.assertEqual(caught.exception.code, "bad_request")
        self.assertIn("超過大小限制", str(caught.exception))
        self.assertEqual(st.record_ids(), [])

    def test_a_preview_is_used_once_and_the_ids_of_a_meeting_preview_do_not_start_one(self):
        runner = self.board()
        src = self.sources()
        preview = runner.preview(self.body(), src)
        runner.start(preview["preview_id"], src)
        runner.wait(10)
        for pid in (preview["preview_id"], "pv-0000000000000000", None):
            with self.subTest(pid=pid), self.assertRaises(mt.MeetingError) as caught:
                runner.start(pid, src)
            self.assertEqual(caught.exception.code, "preview_expired")

    def test_a_change_after_the_preview_makes_it_stale(self):
        changes = {
            "a speaker's card": lambda: self.profiles["pm"].update(instructions="改過的指示（虛構）"),
            "a card on the list": lambda: self.profiles["rev"].update(name="改名的審查（虛構）"),
            "a new skill": lambda: self.skills.append(skill("s-new", "新技能", cats=["frontend"])),
            "a fresh summary": lambda: self.summaries.update({"s-front": "做網站前端（虛構）"}),
            "the task card": lambda: self.task.update(goal="改成別的目標"),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.setUp()
                runner = self.board()
                src = self.sources()
                preview = runner.preview(self.body(), src)
                change()
                with self.assertRaises(mt.MeetingError) as caught:
                    runner.start(preview["preview_id"], src)
                self.assertEqual(caught.exception.code, "stale_preview")
                self.assertEqual(st.record_ids(), [])

    def test_the_task_status_or_the_accountants_spend_does_not_make_it_stale(self):
        runner = self.board()
        src = self.sources()
        preview = runner.preview(self.body(speaker_profile_ids=["acct", "law"]), src)
        self.assertTrue(preview["participants"][0]["dynamic"])
        self.task["status"] = "in_progress"
        view = runner.start(preview["preview_id"], src)
        runner.wait(10)
        self.assertEqual(st.view(st.load(view["id"]))["status"], "ready")

    def test_a_different_cli_version_than_the_one_previewed_is_refused(self):
        versions = iter([VERSION, "2.1.297"])
        runner = self.board()
        runner.provider = lambda e: ("x", next(versions))
        src = self.sources()
        preview = runner.preview(self.body(), src)
        with self.assertRaises(mt.MeetingError) as caught:
            runner.start(preview["preview_id"], src)
        self.assertEqual(caught.exception.code, "stale_preview")

    def test_the_record_count_is_capped(self):
        runner = self.board()
        folder = st.folder()
        folder.mkdir(parents=True)
        for n in range(st.MAX_RECORDS):
            (folder / f"s-{n:012x}.json.corrupted").write_text("x")
        with self.assertRaises(mt.MeetingError) as caught:
            runner.preview(self.body(), self.sources())
        self.assertEqual(caught.exception.code, "too_many")


class ChairPromptFitTests(Base):
    def big(self):
        self.profiles = {}
        for n in range(40):
            self.profiles[f"c{n:02d}"] = card(f"c{n:02d}", "executor", name="卡" * 80, instructions="指" * 120, updated=float(n))
        self.profiles.update({p["id"]: p for p in (
            card("ceo", "planner", instructions="主" * ap.MAX_INSTRUCTIONS, updated=99.0), card("pm", "pm", updated=99.0),
            card("law", "legal", updated=99.0), card("acct", "accountant", updated=99.0), card("soc", "social", updated=99.0),
            card("art", "art", updated=99.0), card("eng", "executor", updated=99.0))})
        self.skills = [skill(f"s-{n:03d}", f"{n:03d}" + "技" * 77, cats=["frontend", "legal", "quality"]) for n in range(150)]
        self.summaries = {s["skill_id"]: "摘" * 60 for s in self.skills}
        return self.body(speaker_profile_ids=["pm", "soc", "eng", "art", "law", "acct"])

    def test_the_list_is_shortened_at_the_preview_so_that_the_ceos_text_fits_whatever_the_speakers_write(self):
        body = self.big()
        full = st.build_inputs(self.task, list(self.profiles.values()), self.skills, summaries=self.summaries)
        worst = [{"職位": "x", "名稱": "卡" * 80, "代發言": False, "發言": st.chair_opinion({**long_opinion(), "flags": []})}] * 6
        with self.assertRaises(mt.MeetingError):  # the whole list would not fit with six long answers
            st.build_prompt("proposal", instructions="主" * ap.MAX_INSTRUCTIONS, position="planner", task=self.task, note="",
                            inputs=full, opinions=worst)

        def call(spec, cancel):
            self.specs.append(spec)
            out = proposal({"ceo": "", "eng": "", "rev": ""}, used=()) if spec.kind == "proposal" else long_opinion()
            if spec.kind == "proposal":
                out["team"] = []
            return mr.CallResult(out, dict(EVIDENCE), Decimal("0.01"))
        runner = self.board()
        runner.call = call
        src = self.sources()
        preview = runner.preview(body, src)
        self.assertTrue(preview["startable"], preview["blockers"])
        self.assertLess(preview["list"]["list_max"], st.LIST_MAX)
        self.assertGreater(preview["list"]["omitted"]["skills"], 30)
        view = runner.start(preview["preview_id"], src)
        runner.wait(10)
        m = st.view(st.load(view["id"]))
        self.assertEqual([t["state"] for t in m["turns"]], ["done"] * 7)
        self.assertLessEqual(len(self.specs[-1].prompt.encode()), st.CHAIR_PROMPT_MAX)
        self.assertTrue(all(len(s.prompt.encode()) <= st.SPEAKER_PROMPT_MAX for s in self.specs[:-1]))


class MoneyTests(Base):
    def test_the_reserve_must_fit_the_records_limit_and_what_is_left_of_today(self):
        runner = self.board()
        tight = runner.preview(self.body(), self.sources(staffing_limits={"total_usd": 0.8}))
        self.assertFalse(tight["startable"])
        self.assertEqual([b["code"] for b in tight["blockers"]], ["budget"])
        self.assertIn("預留 0.9 美元超過這份組隊提案剩下的額度 0.8", tight["blockers"][0]["message"])
        self.assertIsNone(tight["preview_id"])
        # a meeting spent 2.5 of today's 3: 0.9 does not fit what is left
        rec = mt.new_record("m-0123456789ab", topic="虛構會議", context="", flags=[], task_id=None,
                            chair=be.participant(self.profiles["ceo"], "planner"), speakers=[be.participant(self.profiles["pm"], "pm")],
                            limits=mt.DEFAULT_LIMITS, now=time.time())
        rec["turns"][0].update(state="done", attempts=1, started_at=time.time(), ended_at=time.time(), prompt_sha256="b" * 64,
                               output={"stance": "支持", "summary": "好", "points": [], "risks": [], "needs_chairman": False},
                               evidence=dict(EVIDENCE, cost_usd="2.5", cost_source="cli"))
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)
        day = runner.preview(self.body(), self.sources())
        self.assertEqual([b["code"] for b in day["blockers"]], ["budget"])
        self.assertEqual(day["today"]["spent_usd"], "2.5")
        self.assertIn("會超過每日上限 3", day["blockers"][0]["message"])

    def test_limits_that_change_after_the_preview_are_checked_again_at_start(self):
        runner = self.board()
        preview = runner.preview(self.body(), self.sources())
        with self.assertRaises(mt.MeetingError) as caught:
            runner.start(preview["preview_id"], self.sources(staffing_limits={"total_usd": 0.6, "proposal_call_usd": 0.5}))
        self.assertEqual(caught.exception.code, "budget")

    def test_each_call_is_checked_again_and_one_that_would_pass_the_limit_is_skipped(self):
        costs = iter([Decimal("0.6"), Decimal("0.1")])

        def call(spec, cancel):
            self.specs.append(spec)
            return mr.CallResult(self.answer(spec), dict(EVIDENCE), next(costs))
        # 1.0 for the record: 0.6 + 0.1 spent leaves 0.3, the CEO's 0.5 does not fit
        m = self.run_board(self.board(call), staffing_limits={"total_usd": 1.0})
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]], [("done", None), ("done", None), ("skipped", "budget")])
        self.assertEqual(len(self.specs), 2)
        self.assertEqual(m["status"], "incomplete")

    def test_a_call_that_reports_no_cost_is_counted_at_its_own_kinds_limit(self):
        def call(spec, cancel):
            return mr.CallResult(self.answer(spec), dict(EVIDENCE), None)
        m = self.run_board(self.board(call))
        self.assertEqual([(t["evidence"]["cost_usd"], t["evidence"]["cost_source"]) for t in m["turns"]],
                         [("0.2", "worst_case"), ("0.2", "worst_case"), ("0.5", "worst_case")])
        self.assertEqual(m["spent_usd"], "0.9")

    def test_the_day_counts_meetings_and_staffing_meetings_together_for_both(self):
        m = self.run_board(self.board())
        meetings = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=lambda s, c: None)
        self.runners.append(meetings)
        ledger = meetings.ledger({})
        self.assertEqual((ledger["spent_usd"], ledger["includes"]), ("0.03", ["meetings", "staffing"]))
        self.assertEqual([r["id"] for r in meetings.spend_records()], [m["id"]])
        self.assertEqual(self.runners[0]._day(), Decimal("0.03"))

    def test_the_staffing_limits_are_read_with_defaults_and_caps_and_written_by_their_rule(self):
        self.assertEqual(st.limits_from({}), {"per_call_usd": Decimal("0.20"), "proposal_call_usd": Decimal("0.50"),
                                              "total_usd": Decimal("2.00"), "daily_usd": Decimal("3.00")})
        got = st.limits_from({"staffing_limits": {"proposal_call_usd": 0.8, "total_usd": 5}, "meeting_limits": {"per_call_usd": 0.3}})
        self.assertEqual((got["proposal_call_usd"], got["total_usd"], got["per_call_usd"]), (Decimal("0.8"), Decimal("5"), Decimal("0.3")))
        for bad in (0, -1, 1.5, True, "0.5", None, float("nan")):
            with self.subTest(bad=bad):
                self.assertEqual(st.limits_from({"staffing_limits": {"proposal_call_usd": bad}})["proposal_call_usd"], Decimal("0.50"))
        self.assertEqual(st.limits_from({"staffing_limits": {"total_usd": 11}})["total_usd"], Decimal("2.00"))
        current = st.limits_from({})
        self.assertEqual(st.validate_limits({"total_usd": 2.5}, current), {"proposal_call_usd": 0.5, "total_usd": 2.5})
        for bad in ({"total_usd": 0.4}, {"proposal_call_usd": 1.2}, {"total_usd": 3.5}, {"total_usd": "2"}, {"total_usd": True},
                    {"per_call_usd": 0.2}, {"daily_usd": 3}, {"x": 1}, "2", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                st.validate_limits(bad, current)
        self.assertEqual(st.validate_limits({"total_usd": 9}, current, daily=Decimal("9")), {"proposal_call_usd": 0.5, "total_usd": 9.0})


class SharedWorkerTests(Base):
    def meeting_sources(self):
        return mr.Sources(profile=self.profiles.get, task=lambda tid: None, flows=lambda tid: [], conf={})

    def test_a_staffing_meeting_and_a_meeting_never_run_at_the_same_time(self):
        entered, release = threading.Event(), threading.Event()

        def hold(spec, cancel):
            entered.set()
            while not release.wait(0.02):
                if cancel.is_set():
                    raise mr.CallFailed("cancelled", None, None)
            return mr.CallResult({"stance": "支持", "summary": "好", "points": [], "risks": [], "needs_chairman": False}
                                 if spec.kind == "opinion" else
                                 {"decision": "好", "rationale": "好", "dissent_addressed": [], "actions": [], "escalate": False,
                                  "escalate_reason": "", "follow_up_topics": []}, dict(EVIDENCE), Decimal("0.01"))
        meetings = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=hold)
        self.runners.append(meetings)
        self.addCleanup(meetings.wait, 5)
        self.addCleanup(release.set)
        staffing = self.board()
        src = self.sources()
        early = staffing.preview(self.body(), src)
        msrc = self.meeting_sources()
        meetings.start(meetings.preview({"topic": "虛構議題", "chair_profile_id": "ceo", "speaker_profile_ids": ["pm"]}, msrc)["preview_id"], msrc)
        entered.wait(10)
        late = staffing.preview(self.body(), src)
        self.assertEqual([b["code"] for b in late["blockers"]], ["busy"])
        self.assertIn("組隊會議", late["blockers"][0]["message"])
        with self.assertRaises(mt.MeetingError) as caught:
            staffing.start(early["preview_id"], src)
        self.assertEqual(caught.exception.code, "busy")
        self.assertEqual(st.record_ids(), [])
        release.set()
        meetings.wait(10)
        # and the other way: while a staffing meeting runs, a meeting is busy
        entered.clear()
        release.clear()
        staffing.call = hold
        staffing.start(staffing.preview(self.body(), src)["preview_id"], src)
        entered.wait(10)
        blocked = meetings.preview({"topic": "虛構議題", "chair_profile_id": "ceo", "speaker_profile_ids": ["pm"]}, msrc)
        self.assertEqual([b["code"] for b in blocked["blockers"]], ["busy"])
        release.set()


class FailureTests(Base):
    def failing(self, kinds=("opinion",), times=1, code="cli_failed"):
        state = {"n": 0}

        def call(spec, cancel):
            self.specs.append(spec)
            if spec.kind in kinds and state["n"] < times:
                state["n"] += 1
                raise mr.CallFailed(code, dict(EVIDENCE, exit_code=1), None)
            return mr.CallResult(self.answer(spec), dict(EVIDENCE), Decimal("0.01"))
        return self.board(call)

    def test_an_init_with_a_tool_stops_at_once_revokes_the_version_and_skips_the_rest(self):
        store = tr.BoundaryStore()
        with store.locked():
            store.save({VERSION: time.time(), "2.1.200": time.time()})
        bad = dict(INIT, tools=["StructuredOutput", "Bash"])
        started = time.monotonic()
        m = self.run_board(self.cli_board("print(json.dumps(%r), flush=True)\ntime.sleep(30)" % (bad,)))
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]],
                         [("failed", "tools_not_clean"), ("skipped", "boundary_revoked"), ("skipped", "boundary_revoked")])
        self.assertIsNone(m["turns"][0]["output"])
        self.assertNotIn(VERSION, store.load())
        self.assertIn("2.1.200", store.load())
        self.assertEqual(len(self.calls()), 1)

    def test_no_opinion_at_all_means_the_ceo_is_not_asked(self):
        runner = self.failing(times=9)
        m = self.run_board(runner)
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]],
                         [("failed", "cli_failed"), ("failed", "cli_failed"), ("skipped", "no_opinions")])
        self.assertEqual([s.kind for s in self.specs], ["opinion", "opinion"])
        self.assertEqual((m["status"], m["retryable"]), ("incomplete", [1, 2]))

    def test_retrying_a_speaker_asks_the_ceo_again_and_a_third_failure_is_blocked(self):
        runner = self.failing(times=1)
        m = self.run_board(runner)
        self.assertEqual(m["retryable"], [1])
        src = self.sources()
        preview = runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual((preview["startable"], preview["calls"], preview["reserve_usd"], preview["proposal_again"]), (True, 2, "0.7", True))
        self.assertEqual(preview["participant"]["effort"], "low")
        runner.retry(preview["preview_id"], src, m["id"])
        runner.wait(10)
        m = st.view(st.load(m["id"]))
        self.assertEqual([(t["state"], t["attempts"]) for t in m["turns"]], [("done", 2), ("done", 1), ("done", 2)])
        self.assertEqual([s.kind for s in self.specs], ["opinion", "opinion", "proposal", "opinion", "proposal"])
        # a speaker that keeps failing: two retries, then blocked
        runner = self.failing(times=9)
        m = self.run_board(runner, self.body(speaker_profile_ids=["pm"]))
        for _ in range(2):
            preview = runner.retry_preview(m["id"], {"seq": 1}, src)
            runner.retry(preview["preview_id"], src, m["id"])
            runner.wait(10)
        m = st.view(st.load(m["id"]))
        self.assertEqual((m["turns"][0]["state"], m["turns"][0]["attempts"]), ("blocked", 3))
        with self.assertRaises(mt.MeetingError) as caught:
            runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual(caught.exception.code, "not_retryable")

    def test_a_failed_proposal_is_retried_on_its_own(self):
        runner = self.failing(kinds=("proposal",))
        m = self.run_board(runner)
        self.assertEqual(m["retryable"], [3])
        src = self.sources()
        preview = runner.retry_preview(m["id"], {"seq": 3}, src)
        self.assertEqual((preview["calls"], preview["reserve_usd"], preview["proposal_again"], preview["participant"]["effort"]),
                         (1, "0.5", False, "medium"))
        self.assertIn("需要會做前端的人", preview["prompt"])
        runner.retry(preview["preview_id"], src, m["id"])
        runner.wait(10)
        self.assertEqual(st.view(st.load(m["id"]))["status"], "ready")

    def test_a_retry_is_refused_when_the_list_changed_since(self):
        runner = self.failing(kinds=("proposal",))
        m = self.run_board(runner)
        self.skills.append(skill("s-new", "新技能", cats=["frontend"]))
        with self.assertRaises(mt.MeetingError) as caught:
            runner.retry_preview(m["id"], {"seq": 3}, self.sources())
        self.assertEqual(caught.exception.code, "changed")

    def test_after_a_restart_each_running_turn_is_interrupted_at_its_own_worst_case(self):
        runner = self.board()
        m = self.run_board(runner)

        def running(r):
            r["turns"][2].update(state="running", attempts=1, started_at=time.time(), evidence=None, output=None)
        runner._update(m["id"], running)
        restarted = sr.StaffingRunner(provider=lambda e: ("x", VERSION), call=lambda s, c: None)
        self.runners.append(restarted)
        turn = st.load(m["id"])["turns"][2]
        self.assertEqual((turn["state"], turn["error_code"], turn["evidence"]["cost_usd"], turn["evidence"]["cost_source"]),
                         ("interrupted", "restart", "0.5", "worst_case"))
        self.assertEqual(st.view(st.load(m["id"]))["retryable"], [3])

    def test_cancel_ends_the_running_call_and_cancels_the_rest(self):
        entered = threading.Event()

        def call(spec, cancel):
            entered.set()
            while not cancel.wait(0.02):
                pass
            raise mr.CallFailed("cancelled", None, None)
        runner = self.board(call)
        src = self.sources()
        view = runner.start(runner.preview(self.body(), src)["preview_id"], src)
        entered.wait(10)
        self.assertIn("clock", runner.get(view["id"]))
        with self.assertRaises(mt.MeetingError) as caught:
            runner.delete(view["id"])
        self.assertEqual(caught.exception.code, "running")
        runner.cancel(view["id"])
        runner.wait(10)
        m = st.view(st.load(view["id"]))
        self.assertEqual([t["state"] for t in m["turns"]], ["cancelled"] * 3)
        with self.assertRaises(mt.MeetingError) as caught:
            runner.cancel(view["id"])
        self.assertEqual(caught.exception.code, "not_running")

    def test_a_staffing_meeting_runs_on_the_meeting_clock_with_the_ceos_three_minutes(self):
        now = [1_893_456_000.0]

        def call(spec, cancel):
            self.specs.append(spec)
            now[0] += 100
            return mr.CallResult(self.answer(spec), dict(EVIDENCE), Decimal("0.01"))
        runner = self.board(call, clock=lambda: now[0])
        m = self.run_board(runner, self.body(speaker_profile_ids=["pm", "law", "acct"]), meeting_speed={"max_minutes": 5})
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]],
                         [("done", None), ("skipped", "time_up"), ("skipped", "time_up"), ("done", None)])
        self.assertEqual([(s.kind, s.timeout) for s in self.specs], [("opinion", 120.0), ("proposal", 180.0)])
        self.assertEqual(self.specs[-1].prompt.count("沒有發言（時間到）"), 2)


class ChairmanTests(Base):
    def test_the_chairman_records_adopt_or_dismiss_and_that_is_all(self):
        runner = self.board()
        m = self.run_board(runner)
        for bad in ({"decision": "approve"}, {"decision": "adopt", "adopted": {}}, {"decision": "adopt", "note": 3}, {}, None,
                    {"decision": "adopt", "note": "x" * 501}):
            with self.subTest(bad=bad), self.assertRaises(mt.MeetingError) as caught:
                runner.chairman(m["id"], bad)
            self.assertEqual(caught.exception.code, "bad_request")
        out = runner.chairman(m["id"], {"decision": "adopt", "note": "照這樣組隊（虛構）"})
        self.assertEqual((out["status"], out["chairman"]["state"], out["chairman"]["note"], out["chairman"]["adopted"]),
                         ("adopted", "adopted", "照這樣組隊（虛構）", None))
        self.assertEqual(out["chairman"]["label"], "主控台記錄（未驗證身分）")
        with self.assertRaises(mt.MeetingError) as caught:
            runner.chairman(m["id"], {"decision": "dismiss"})
        self.assertEqual(caught.exception.code, "already_decided")
        with self.assertRaises(mt.MeetingError) as caught:
            runner.retry_preview(m["id"], {"seq": 1}, self.sources())
        self.assertEqual(caught.exception.code, "already_decided")

    def test_a_proposal_that_is_not_there_cannot_be_adopted_but_can_be_dismissed(self):
        def call(spec, cancel):
            raise mr.CallFailed("cli_failed", dict(EVIDENCE), None)
        runner = self.board(call)
        m = self.run_board(runner)
        with self.assertRaises(mt.MeetingError) as caught:
            runner.chairman(m["id"], {"decision": "adopt"})
        self.assertEqual(caught.exception.code, "not_decided")
        self.assertIn("CEO 還沒有提案", str(caught.exception))
        self.assertEqual(runner.chairman(m["id"], {"decision": "dismiss"})["status"], "dismissed")


class ReadTests(Base):
    def test_list_get_and_delete(self):
        runner = self.board()
        m = self.run_board(runner)
        listing = runner.list()
        self.assertEqual([(x["id"], x["task_id"], x["status"], x["spent_usd"], x["participants"]) for x in listing["staffing"]],
                         [(m["id"], "t-1", "ready", "0.03", 3)])
        self.assertEqual(runner.list("t-2")["staffing"], [])
        got = runner.get(m["id"], self.sources())
        self.assertEqual(got["changed_cards"], [])
        self.assertNotIn("clock", got)
        eng = self.aliases()["eng"]
        self.profiles["eng"]["name"] = "改過的卡（虛構）"
        self.assertEqual(runner.get(m["id"], self.sources())["changed_cards"], [eng])
        self.assertIsNone(runner.get(m["id"])["changed_cards"])
        runner.delete(m["id"])
        with self.assertRaises(mt.MeetingError) as caught:
            runner.get(m["id"])
        self.assertEqual(caught.exception.code, "not_found")

    def test_a_damaged_record_is_listed_as_blocked_and_the_others_still_show(self):
        runner = self.board()
        m = self.run_board(runner)
        bad = st.folder() / "s-ffffffffffff.json"
        bad.write_text("{broken")
        listing = runner.list()["staffing"]
        self.assertEqual([(x["id"], x.get("blocked", False)) for x in listing], [(m["id"], False), ("s-ffffffffffff", True)])


if __name__ == "__main__":
    unittest.main()
