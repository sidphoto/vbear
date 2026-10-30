"""The engine under the meetings (P35-0): HeadlessBoard runs the turns, the money and the recovery; a kind of board (the
meeting) gives it the schema, the checks, the prompts, the most one call may cost and where its records live."""
import inspect
import time
import unittest
from decimal import Decimal

from tests.test_meeting_runner import DECISION, OPINION, VERSION, Base
from tests.test_meetings import finish, opinion, record
from vbear import board_engine as be, meeting_runner as mr, meetings as mt

EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


class ShapeTests(unittest.TestCase):
    def test_the_meeting_runner_is_a_headless_board_with_the_meetings_hooks(self):
        self.assertTrue(issubclass(mr.MeetingRunner, be.HeadlessBoard))
        self.assertEqual(mr.MeetingRunner.final_kind, "decision")
        self.assertIs(mr.MeetingRunner.store_cls, mt.MeetingStore)
        runner = mr.MeetingRunner.__new__(mr.MeetingRunner)
        self.assertIs(runner.schema("decision"), mt.DECISION_SCHEMA)
        self.assertIs(runner.schema("opinion"), mt.OPINION_SCHEMA)
        rec = record(limits={**mt.DEFAULT_LIMITS, "per_call_usd": Decimal("0.3")})
        self.assertEqual([runner.per_call(rec, t) for t in rec["turns"]], [Decimal("0.3")] * 3)

    def test_a_board_that_does_not_give_its_hooks_cannot_run_a_turn(self):
        board = be.HeadlessBoard.__new__(be.HeadlessBoard)
        for hook, args in (("schema", ("x",)), ("validate", ("x", {}, {}, None)), ("prompt", ("x", {}, {}, None)),
                           ("per_call", ({}, {})), ("total_limit", ({},)), ("ids", ()), ("load", ("x",)), ("view", ({},)),
                           ("remove", ("x",)), ("decided", ({},))):
            with self.subTest(hook=hook), self.assertRaises(NotImplementedError):
                getattr(board, hook)(*args)

    def test_the_engine_knows_no_meeting_rule_and_executes_nothing(self):
        source = inspect.getsource(be)
        for word in ("meeting_rules", "evaluate(", "major", "approved", "os.system", "shell=True", "task_save", "save_task",
                     "append_event", "create_flow"):
            self.assertNotIn(word, source, word)

    def test_the_names_the_meetings_used_from_the_runner_are_still_there(self):
        for name in ("Sources", "CallSpec", "CallResult", "CallFailed", "default_call", "meeting_argv", "model_for", "participant",
                     "CHECK_ERRORS", "WORKER"):
            self.assertIs(getattr(mr, name), getattr(be, name), name)


class PerCallOfTests(unittest.TestCase):
    def test_spent_and_daily_spent_charge_each_turn_what_its_own_kind_may_cost(self):
        now = time.time()
        rec = finish(record(), 1, opinion(), cost="0.01")
        rec["turns"][1].update(state="running", attempts=1, started_at=now)
        rec["turns"][2].update(state="running", attempts=1, started_at=now)
        seen = []

        def of(meeting, turn):
            seen.append((meeting is rec, turn["seq"]))
            return Decimal("0.5") if turn["kind"] == "decision" else Decimal("0.2")
        self.assertEqual(mt.spent(rec), Decimal("0.41"))  # the default: the meeting's per-call limit for every turn
        self.assertEqual(mt.spent(rec, per_call_of=of), Decimal("0.71"))
        self.assertEqual(seen, [(True, 1), (True, 2), (True, 3)])
        self.assertEqual(mt.daily_spent([rec], now), Decimal("0.41"))
        self.assertEqual(mt.daily_spent([rec], now, per_call_of=of), Decimal("0.71"))
        self.assertEqual(mt.daily_spent([rec], now + 36 * 3600, per_call_of=of), Decimal(0))


class DecisionCostsMore(mr.MeetingRunner):
    """A board whose last turn may cost more than a speaker's, as a staffing proposal will."""

    def per_call(self, rec, turn):
        return Decimal("0.5") if turn["kind"] == "decision" else super().per_call(rec, turn)


class HookTests(Base):
    def call(self, costs):
        self.specs = []

        def call(spec, cancel):
            self.specs.append(spec)
            return mr.CallResult(OPINION if spec.kind == "opinion" else DECISION, dict(EVIDENCE), costs.get(spec.kind))
        return call

    def board(self, costs):
        runner = DecisionCostsMore(provider=lambda e: ("x", VERSION), call=self.call(costs))
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        return runner

    def test_each_call_is_capped_and_counted_at_its_own_turns_limit(self):
        _, m = self.run_meeting(self.board({"opinion": Decimal("0.01")}))  # the decision reports no cost
        self.assertEqual([(s.kind, s.per_call) for s in self.specs],
                         [("opinion", Decimal("0.2")), ("opinion", Decimal("0.2")), ("decision", Decimal("0.5"))])
        self.assertEqual((m["turns"][2]["evidence"]["cost_usd"], m["turns"][2]["evidence"]["cost_source"]), ("0.5", "worst_case"))

    def test_the_check_before_a_call_uses_that_turns_limit(self):
        # 0.06 x 2 spent of 0.6 leaves 0.48: a speaker's 0.2 would fit, the decision's 0.5 does not
        _, m = self.run_meeting(self.board({"opinion": Decimal("0.06"), "decision": Decimal("0.01")}),
                                meeting_limits={"per_call_usd": 0.2, "meeting_usd": 0.6, "daily_usd": 3})
        self.assertEqual([t["state"] for t in m["turns"]], ["done", "done", "skipped"])
        self.assertEqual(m["turns"][2]["error_code"], "budget")
        self.assertEqual(len(self.specs), 2)

    def test_a_turn_interrupted_by_a_restart_costs_its_own_turns_limit(self):
        rec = finish(record("m-0123456789ab"), 1, opinion())
        finish(rec, 2, opinion())
        rec["turns"][2].update(state="running", attempts=1, started_at=time.time())
        store = mt.MeetingStore(rec["id"])
        with store.locked():
            store.save(rec)
        runner = self.board({})
        turn = mt.load(rec["id"])["turns"][2]
        self.assertEqual((turn["state"], turn["evidence"]["cost_usd"], turn["evidence"]["cost_source"]), ("interrupted", "0.5", "worst_case"))
        self.assertEqual(runner.room(mt.load(rec["id"])), Decimal("1.5") - Decimal("0.52"))

    def test_the_day_is_counted_over_the_records_the_board_spends_from(self):
        runner, m = self.run_meeting(self.failing_runner())
        bad = mt.MeetingStore("m-ffffffffffff")
        bad.path().write_text("{broken")
        self.assertEqual([r["id"] for r in runner.spend_records()], [m["id"]])  # a damaged one adds nothing
        self.assertEqual(runner.ledger({})["spent_usd"], "0.22")

    def test_the_reserve_and_the_room_are_given_to_the_check(self):
        runner = self.runner()
        limits = mt.limits_from({})
        blockers, today = runner._blockers(Decimal("0.7"), Decimal("0.5"), limits)
        self.assertEqual([b["code"] for b in blockers], ["budget"])
        self.assertEqual(blockers[0]["message"], "預留 0.7 美元超過這場會議剩下的額度 0.5")
        self.assertEqual(today, {"spent_usd": "0", "daily_usd": "3", "lamp": "green"})
        self.assertEqual(runner._blockers(Decimal("0.5"), Decimal("0.5"), limits)[0], [])
        self.assertIn("額度 0", runner._blockers(Decimal("0.1"), Decimal("-0.2"), limits)[0][0]["message"])
        message = runner._blockers(Decimal("2.9"), Decimal("9"), {**limits, "daily_usd": Decimal("2.5")})[0][0]["message"]
        self.assertEqual(message, "今天已花 0 美元，加上預留 2.9 會超過每日上限 2.5")

    def test_a_retry_is_planned_from_the_boards_last_kind(self):
        runner = self.failing_runner("decision")
        _, m = self.run_meeting(runner)
        rec, turn, again = runner._retry_plan(m["id"], 3, self.sources())
        self.assertEqual((turn["kind"], again), ("decision", False))
        runner = self.failing_runner()
        _, m = self.run_meeting(runner)
        rec, turn, again = runner._retry_plan(m["id"], 1, self.sources())
        self.assertEqual((turn["kind"], again), ("opinion", True))
        self.assertFalse(runner.decided(rec))
        runner.chairman(m["id"], {"decision": "reject"})
        self.assertTrue(runner.decided(mt.load(m["id"])))


if __name__ == "__main__":
    unittest.main()
