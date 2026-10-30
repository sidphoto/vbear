"""How fast a meeting is (P35-2, the chairman's decision 8): every call thinks at low or medium effort only, and a
meeting runs at most ``max_minutes`` from its start, the last three of them kept for the CEO. No real CLI: an owned
synthetic script prints what a tool-less Claude Code would, and says which --effort it was given."""
import json
import os
import sys
import threading
import time
import unittest
from decimal import Decimal
from unittest import mock

from tests.test_meeting_runner import DECISION, FAKE, INIT, OPINION, VERSION, Base, good_body
from vbear import board_engine as be, config as cfg, meeting_runner as mr, meetings as mt, translations as tr

# the meeting tests' fake CLI, which also writes down the --effort it was given and refuses any other than low or medium
EFFORT_LOG = '''
effort = args[args.index('--effort')+1] if '--effort' in args else None
assert effort in ('low', 'medium'), effort
assert args.count('--effort') == 1
with open({log!r} + '.effort', 'a') as fh:
    fh.write(json.dumps({{'kind': kind, 'effort': effort, 'argv_tail': args[-3:]}}) + chr(10))
'''
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


class SpeedBase(Base):
    def fake(self, body=None, name="fake-cli"):
        script = self.root / name
        text = FAKE.format(python=sys.executable, version=VERSION, log=str(self.log), body=body or good_body())
        marker = "kind = 'decision' if 'decision' in schema['properties'] else 'opinion'\n"
        text = text.replace(marker, marker + EFFORT_LOG.format(log=str(self.log)))
        script.write_text(text)
        script.chmod(0o700)
        return script

    def efforts(self):
        path = self.log.with_name(self.log.name + ".effort")
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class ArgvTests(unittest.TestCase):
    def test_the_meeting_argv_ends_with_the_effort_and_takes_only_low_or_medium(self):
        a = tr.translation_argv("claude", "bin", "/x", mt.OPINION_SCHEMA)
        for effort in ("low", "medium"):
            b = be.meeting_argv("bin", "sonnet", mt.OPINION_SCHEMA, Decimal("0.2"), effort)
            self.assertEqual([(x, y) for x, y in zip(a, b) if x != y],
                             [("claude-haiku-5-5", "sonnet"), ("json", "stream-json"), ("0.05", "0.2")])
            self.assertEqual(b[len(a):], ["--verbose", "--effort", effort])
        for bad in ("high", "xhigh", "max", "", "LOW", None, 1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                be.meeting_argv("bin", "sonnet", mt.OPINION_SCHEMA, Decimal("0.2"), bad)


class SpeedConfigTests(unittest.TestCase):
    def test_the_defaults_are_low_for_speakers_medium_for_the_ceo_and_fifteen_minutes(self):
        self.assertEqual(mt.DEFAULT_SPEED, {"speaker_effort": "low", "chair_effort": "medium", "max_minutes": 15})
        self.assertEqual(mt.EFFORTS, ("low", "medium"))
        self.assertEqual(mt.speed_from({}), mt.DEFAULT_SPEED)
        self.assertEqual(mt.speed_from({"meeting_speed": {"speaker_effort": "medium", "chair_effort": "low", "max_minutes": 30}}),
                         {"speaker_effort": "medium", "chair_effort": "low", "max_minutes": 30})

    def test_a_stored_value_that_cannot_be_used_falls_back_to_its_default_alone(self):
        for bad in ("high", "max", "", None, 3, ["low"]):
            with self.subTest(bad=bad):
                got = mt.speed_from({"meeting_speed": {"speaker_effort": bad, "chair_effort": "low"}})
                self.assertEqual(got, {"speaker_effort": "low", "chair_effort": "low", "max_minutes": 15})
        for bad in (4, 31, 15.0, True, "15", None, -1):
            with self.subTest(bad=bad):
                self.assertEqual(mt.speed_from({"meeting_speed": {"max_minutes": bad}})["max_minutes"], 15)
        self.assertEqual(mt.speed_from({"meeting_speed": "fast"}), mt.DEFAULT_SPEED)

    def test_a_write_takes_low_or_medium_and_five_to_thirty_minutes_and_nothing_else(self):
        current = mt.speed_from({})
        self.assertEqual(mt.validate_speed({"chair_effort": "low"}, current),
                         {"speaker_effort": "low", "chair_effort": "low", "max_minutes": 15})
        self.assertEqual(mt.validate_speed({"max_minutes": 5}, current)["max_minutes"], 5)
        self.assertEqual(mt.validate_speed({"max_minutes": 30}, current)["max_minutes"], 30)
        for bad in ({"speaker_effort": "high"}, {"chair_effort": "max"}, {"chair_effort": "xhigh"}, {"speaker_effort": ""},
                    {"speaker_effort": None}, {"max_minutes": 4}, {"max_minutes": 31}, {"max_minutes": 15.5}, {"max_minutes": 15.0},
                    {"max_minutes": True}, {"max_minutes": "15"}, {"speed": "fast"}, "fast", None, []):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mt.validate_speed(bad, current)

    def test_the_preview_words_say_low_or_medium_and_why_there_is_no_high(self):
        shown = mt.speed_view(mt.DEFAULT_SPEED)
        self.assertEqual((shown["speaker_effort"], shown["chair_effort"], shown["max_minutes"], shown["chair_reserve_minutes"]),
                         ("low", "medium", 15, 3))
        self.assertIn("思考強度：低／中（會議為了快，不提供高）", shown["note"])
        self.assertIn("15 分鐘", shown["note"])
        self.assertEqual(shown["labels"], {"speaker_effort": "低", "chair_effort": "中"})


class EffortTests(SpeedBase):
    def test_speakers_think_at_low_and_the_ceo_at_medium_by_default(self):
        _, m = self.run_meeting()
        self.assertEqual([t["state"] for t in m["turns"]], ["done"] * 3)
        self.assertEqual([(e["kind"], e["effort"], e["argv_tail"]) for e in self.efforts()],
                         [("opinion", "low", ["--verbose", "--effort", "low"]), ("opinion", "low", ["--verbose", "--effort", "low"]),
                          ("decision", "medium", ["--verbose", "--effort", "medium"])])

    def test_the_effort_set_in_the_config_is_the_one_sent(self):
        _, m = self.run_meeting(meeting_speed={"speaker_effort": "medium", "chair_effort": "low"})
        self.assertEqual([e["effort"] for e in self.efforts()], ["medium", "medium", "low"])

    def test_the_preview_shows_each_persons_effort_and_the_time_limit(self):
        runner = self.runner()
        preview = runner.preview(self.body(), self.sources(meeting_speed={"max_minutes": 20}))
        self.assertEqual([p["effort"] for p in preview["participants"]], ["low", "low"])
        self.assertEqual(preview["chair"]["effort"], "medium")
        self.assertEqual((preview["speed"]["max_minutes"], preview["speed"]["chair_reserve_minutes"]), (20, 3))
        self.assertIn("20 分鐘", preview["speed"]["note"])

    def test_what_the_preview_showed_is_what_is_sent_even_if_the_config_changes_before_start(self):
        runner = self.runner()
        preview = runner.preview(self.body(), self.sources())
        runner.start(preview["preview_id"], self.sources(meeting_speed={"speaker_effort": "medium", "chair_effort": "low"}))
        runner.wait(10)
        self.assertEqual([e["effort"] for e in self.efforts()], ["low", "low", "medium"])

    def test_a_retry_shows_and_sends_the_effort_of_its_own_preview(self):
        runner = self.failing_runner()
        self.specs = []
        call = runner.call

        def keep(spec, cancel):
            self.specs.append((spec.kind, spec.effort))
            return call(spec, cancel)
        runner.call = keep
        _, m = self.run_meeting(runner)
        src = self.sources(meeting_speed={"speaker_effort": "medium"})
        preview = runner.retry_preview(m["id"], {"seq": 1}, src)
        self.assertEqual((preview["participant"]["effort"], preview["speed"]["speaker_effort"]), ("medium", "medium"))
        runner.retry(preview["preview_id"], src, m["id"])
        runner.wait(10)
        self.assertEqual(self.specs[-2:], [("opinion", "medium"), ("decision", "medium")])


class BoundaryTests(SpeedBase):
    def test_the_check_of_every_init_still_holds_with_the_effort_and_revokes_the_pass(self):
        store = tr.BoundaryStore()
        with store.locked():
            store.save({VERSION: time.time()})
        bad = dict(INIT, tools=["StructuredOutput", "Bash"])
        _, m = self.run_meeting(self.runner("print(json.dumps(%r), flush=True)\ntime.sleep(30)" % (bad,)))
        self.assertEqual((m["turns"][0]["state"], m["turns"][0]["error_code"]), ("failed", "tools_not_clean"))
        self.assertEqual(self.efforts()[0]["effort"], "low")  # the call that was stopped had the effort
        self.assertNotIn(VERSION, store.load())

    def test_the_versions_pass_is_still_found_and_kept_by_the_real_provider(self):
        script = self.fake()
        store = tr.BoundaryStore()
        with store.locked():
            store.save({VERSION: time.time()})
        with mock.patch.object(tr.shutil, "which", return_value=str(script)):
            runner = mr.MeetingRunner()
            preview = runner.preview(self.body(), self.sources())
            self.assertTrue(preview["startable"], preview["blockers"])
            runner.start(preview["preview_id"], self.sources())
            runner.wait(10)
        self.assertEqual(mt.view(mt.load(mt.meeting_ids()[0]))["status"], "decided")
        self.assertEqual([e["effort"] for e in self.efforts()], ["low", "low", "medium"])
        self.assertIn(VERSION, store.load())

    def test_a_cli_that_does_not_know_the_effort_fails_the_turn_and_keeps_the_pass(self):
        store = tr.BoundaryStore()
        with store.locked():
            store.save({VERSION: time.time()})
        refuse = "import sys\nsys.stderr.write('error: unknown option --effort')\nsys.exit(1)"
        _, m = self.run_meeting(self.runner(refuse))
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]],
                         [("failed", "cli_failed"), ("failed", "cli_failed"), ("skipped", "no_opinions")])
        self.assertEqual(m["turns"][0]["evidence"]["cost_source"], "worst_case")  # nothing reported: counted at the most
        self.assertIn(VERSION, store.load())


class Clock:
    def __init__(self, start=1_893_456_000.0):
        self.now = start

    def __call__(self):
        return self.now


class TimeTests(Base):
    def timed(self, durations, max_minutes=5, speakers=("pm", "legal", "acct")):
        """Run a meeting whose calls take ``durations`` seconds each (by a fake clock); a call that takes longer than its
        timeout ends at the timeout, as headless_cli ends it."""
        clock, self.specs, durations = Clock(), [], list(durations)

        def call(spec, cancel):
            took = durations.pop(0)
            self.specs.append((spec.kind, spec.timeout, spec.prompt))
            clock.now += min(took, spec.timeout)
            if took > spec.timeout:
                raise mr.CallFailed("timeout", dict(EVIDENCE, exit_code=None, duration_ms=None), None)
            return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION, dict(EVIDENCE), Decimal("0.01"))
        runner = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=call, clock=clock)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        self.clock = clock
        _, m = self.run_meeting(runner, self.body(speaker_profile_ids=list(speakers)),
                                meeting_speed={"max_minutes": max_minutes})
        return runner, m

    def test_speakers_stop_three_minutes_before_the_end_and_the_ceo_keeps_that_time(self):
        # 5 minutes: the speakers until 120 s. The first takes 50 s; the second has 70 s left and runs over; the third
        # has none. The CEO has the last 180 s.
        _, m = self.timed([50, 100, 30])
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]],
                         [("done", None), ("failed", "time_up"), ("skipped", "time_up"), ("done", None)])
        self.assertEqual([(kind, timeout) for kind, timeout, _ in self.specs], [("opinion", 120.0), ("opinion", 70.0), ("decision", 120.0)])
        stopped = m["turns"][1]["evidence"]
        self.assertEqual((stopped["cost_usd"], stopped["cost_source"]), ("0.2", "worst_case"))
        self.assertEqual(m["turns"][2]["evidence"], None)
        chair_prompt = self.specs[-1][2]
        self.assertEqual(chair_prompt.count("沒有發言（時間到）"), 2)
        self.assertEqual(self.clock.now, 1_893_456_000.0 + 120 + 30)

    def test_a_speaker_with_less_than_a_minute_left_does_not_start(self):
        _, m = self.timed([65, 30, 30])  # the second would have 55 s
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "skipped", "skipped", "done"])
        self.assertEqual(len(self.specs), 2)

    def test_a_call_that_ends_by_its_own_timeout_is_a_timeout_not_the_meetings_clock(self):
        _, m = self.timed([500, 30, 30, 30], max_minutes=30)
        self.assertEqual((m["turns"][0]["state"], m["turns"][0]["error_code"]), ("failed", "timeout"))
        self.assertEqual([t["state"] for t in m["turns"][1:]], ["done", "done", "done"])

    def test_past_the_end_nothing_starts_and_the_ceo_can_be_asked_again_on_a_new_clock(self):
        clock, steps = Clock(), [("ok", 400), ("ok", 10)]
        self.specs = []

        def call(spec, cancel):
            self.specs.append(spec.kind)
            clock.now += steps.pop(0)[1]  # a call that overran: the clock is past the end when it returns
            return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION, dict(EVIDENCE), Decimal("0.01"))
        runner = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=call, clock=clock)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        _, m = self.run_meeting(runner, self.body(speaker_profile_ids=["pm", "legal"]), meeting_speed={"max_minutes": 5})
        self.assertEqual([(t["state"], t["error_code"], t["attempts"]) for t in m["turns"]],
                         [("done", None, 1), ("skipped", "time_up", 0), ("failed", "time_up", 0)])
        self.assertEqual(self.specs, ["opinion"])
        self.assertEqual(m["retryable"], [3])
        src = self.sources(meeting_speed={"max_minutes": 5})
        preview = runner.retry_preview(m["id"], {"seq": 3}, src)
        self.assertTrue(preview["startable"], preview["blockers"])
        runner.retry(preview["preview_id"], src, m["id"])
        runner.wait(10)
        m = mt.view(mt.load(m["id"]))
        self.assertEqual((m["turns"][2]["state"], m["turns"][2]["attempts"]), ("done", 1))
        self.assertEqual(self.specs, ["opinion", "decision"])

    def test_the_running_meeting_shows_its_clock_and_a_finished_one_does_not(self):
        clock = Clock()
        entered, release = threading.Event(), threading.Event()

        def call(spec, cancel):
            entered.set()
            release.wait(10)
            return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION, dict(EVIDENCE), Decimal("0.01"))
        runner = mr.MeetingRunner(provider=lambda e: ("x", VERSION), call=call, clock=clock)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        self.addCleanup(release.set)
        src = self.sources(meeting_speed={"max_minutes": 10})
        view = runner.start(runner.preview(self.body(), src)["preview_id"], src)
        entered.wait(10)
        clock.now += 61
        shown = runner.get(view["id"])["clock"]
        start = 1_893_456_000.0
        self.assertEqual(shown, {"started_at": start, "deadline_at": start + 600, "speakers_until": start + 420,
                                 "max_minutes": 10, "remaining_s": 539.0})
        release.set()
        runner.wait(10)
        self.assertNotIn("clock", runner.get(view["id"]))


class ConfigApiTests(unittest.TestCase):
    def test_the_config_takes_meeting_speed_and_refuses_what_is_not_low_or_medium(self):
        from tests.test_meetings_api import MeetingApiTests
        case = MeetingApiTests("test_the_whole_way_preview_start_read_decide_delete")
        case.setUp()
        try:
            status, out = case.call("/api/config", "POST", {"meeting_speed": {"chair_effort": "low", "max_minutes": 10}})
            self.assertEqual(status, 200, out)
            self.assertEqual(cfg.load()["meeting_speed"], {"speaker_effort": "low", "chair_effort": "low", "max_minutes": 10})
            for bad in ({"chair_effort": "high"}, {"max_minutes": 60}, {"max_minutes": 15.0}, {"x": 1}, "fast"):
                with self.subTest(bad=bad):
                    self.assertEqual(case.call("/api/config", "POST", {"meeting_speed": bad})[0], 400)
            self.assertEqual(cfg.load()["meeting_speed"]["chair_effort"], "low")
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
