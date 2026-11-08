"""P44-2: the routine runner (vbear/routine_runner.py): what happens when a routine's time comes, with a clock a test moves by hand.

Seams: ``RoutineRunner.tick()`` (one pass), the person's buttons the runner carries out (``start_waiting``, ``skip_waiting``,
``start_now``), and the records they all write (``<state>/routines/runs.jsonl``), over the real ``ChatService`` talking to the dispatch
tests' fake runtime daemon. Nothing waits for real time, no CLI runs, nothing leaves the machine."""
from __future__ import annotations

import datetime
import json
import unittest
from decimal import Decimal
from unittest import mock

from tests.routine_fixtures import NY, MONDAY_0759, RoutineBase, at
from vbear import agent_profiles as ap, config as cfg, routines as rt, routine_rules as rr
from vbear.api_error import ApiError


class OnTimeWithItemThreeOffTests(RoutineBase):
    """The default: at the time VBear only reminds. Nothing is sent, nothing costs, until the person presses 「現在開始」."""

    def test_at_the_time_there_is_a_reminder_and_nothing_else(self):
        routine = self.routine()
        self.tick_to(7, 59, 30)
        self.assertEqual(self.states(), [], "before the time: nothing")
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["by"], run["why"], run["slot"], run["routine_id"]),
                         ("waiting", None, "on_time", "2026-11-09T08:00", routine["id"]))
        self.assertEqual(self.sent(), [], "nothing was sent")
        self.assertEqual(self.daemon.closed, [])
        self.assertEqual(self.chat_files(), [], "not even a chat was opened")
        for _ in range(5):
            self.tick_after(15)
        self.assertEqual(self.states(), ["waiting"], "still one reminder, still nothing sent")
        self.assertEqual(self.sent(), [])

    def test_pressing_start_makes_exactly_one_run(self):
        self.routine()
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        started = self.runner.start_waiting(run["run_id"])
        self.assertEqual((started["state"], started["by"]), ("starting", "you"))
        self.tick()
        (run,) = self.runs()
        self.assertEqual((run["state"], run["by"], run["why"], run["turn"]), ("running", "you", "on_time", 1))
        self.assertEqual(len(self.sent()), 1)
        self.assertNotIn("origin", self.sent()[0])
        text = self.sent()[0]["text"]
        self.assertTrue(text.startswith("（這是用的人排定的例行工作"))
        self.assertIn("請整理昨天的銷售。", text)
        self.assertEqual(json.loads(json.loads(text.split("\n")[2])), {"name": "市集日報", "slot": "2026-11-09T08:00"})
        with self.assertRaises(ApiError) as ctx:
            self.runner.start_waiting(run["run_id"])
        self.assertEqual(ctx.exception.status, 409, "pressing it twice does not start it twice")
        self.tick()
        self.assertEqual(len(self.sent()), 1)

    def test_skipping_sends_nothing_and_the_slot_is_used(self):
        self.routine()
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.runner.skip_waiting(run["run_id"])
        self.assertEqual((self.runs()[0]["state"], self.runs()[0]["by"], self.runs()[0]["reason"]), ("skipped", "you", "you"))
        for _ in range(3):
            self.tick_after(60)
        self.assertEqual(self.states(), ["skipped"])
        self.assertEqual(self.sent(), [])

    def test_a_reminder_nobody_pressed_is_put_away_at_the_next_time(self):
        routine = self.routine()
        self.tick_to(8, 0, 10)
        self.tick_to(19, 0, 0)
        self.assertEqual(self.states(), ["waiting"])
        self.go_to(at(2026, 11, 10, 8, 0, 10))                  # Tuesday: the next time has come
        self.tick()
        self.assertEqual(self.states(), ["missed", "waiting"], "Monday's is put away, Tuesday's is the new reminder")
        self.assertEqual(self.runs()[0]["reason"], "unanswered")
        self.assertEqual(self.sent(), [])

    def test_a_reminder_is_put_away_after_twelve_hours_too(self):
        self.routine(days=[0], times=["08:00"])
        self.tick_to(8, 0, 10)
        self.go_to(at(2026, 11, 9, 20, 0, 11))
        self.tick()
        self.assertEqual((self.states(), self.runs()[0]["reason"]), (["missed"], "unanswered"))

    def test_a_reminder_for_a_routine_that_was_switched_off_or_deleted_is_put_away(self):
        first = self.routine()
        second = self.routine(name="另一件", times=["08:00"])
        self.tick_to(8, 0, 10)
        self.assertEqual(self.states(), ["waiting", "waiting"])
        rt.set_enabled(first["id"], False, self.service.cards(), now=self.now[0])
        rt.delete(second["id"])
        self.tick_after(15)
        self.assertEqual(sorted((r["state"], r["reason"]) for r in self.runs()), [("dismissed", "deleted"), ("dismissed", "disabled")])

    def test_a_slot_that_was_missed_while_nobody_looked_is_listed_as_a_wake_up_not_sent(self):
        # P44-3: the interim "recorded and not listed" is now the wake-up's list (tests/test_routine_wake.py has the rules)
        self.routine()
        self.tick_to(7, 59, 0)
        self.go_to(at(2026, 11, 9, 8, 30, 0))                    # the machine was away for half an hour, with VBear running
        self.tick()
        (run,) = self.runs()
        self.assertEqual((run["state"], run["why"], run["reason"]), ("waiting", "catch_up", "asleep_1"))
        self.assertEqual([r["kind"] for r in self.runner.waiting_rows()], ["routine_missed"])
        self.assertEqual(self.sent(), [])

    def test_the_routine_before_it_was_switched_on_has_no_slots(self):
        self.go_to(at(2026, 11, 9, 9, 0, 0))
        self.routine()                                            # switched on at 09:00: the 08:00 of today is not its
        self.tick()
        self.assertEqual(self.runs(), [])

    def test_pressing_start_now_works_out_of_time_and_for_a_switched_off_routine(self):
        routine = self.routine(enabled=False)
        self.go_to(at(2026, 11, 9, 14, 7, 20))
        run = self.runner.start_now(routine["id"])
        self.assertEqual((run["state"], run["by"], run["why"], run["slot"]), ("starting", "you", "now", "2026-11-09T14:07"))
        self.tick()
        self.assertEqual(self.states(), ["running"])
        with self.assertRaises(ApiError) as ctx:
            self.runner.start_now(routine["id"])
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "routine_already"), "the same minute: not twice")
        with self.assertRaises(ApiError) as ctx:
            self.runner.start_now("r-000000000000")
        self.assertEqual(ctx.exception.status, 404)

    def test_the_reminders_the_page_shows(self):
        routine = self.routine()
        self.tick_to(8, 0, 10)
        (row,) = self.runner.waiting_rows()
        self.assertEqual((row["kind"], row["routine_id"], row["name"], row["slot"]), ("routine_due", routine["id"], "市集日報", "2026-11-09T08:00"))
        self.assertEqual(row["run_id"], self.runs()[0]["run_id"])
        self.assertNotIn("text", row, "only a name, a time and a link: no content")
        self.runner.skip_waiting(row["run_id"])
        self.assertEqual(self.runner.waiting_rows(), [])


class OnTimeWithItemThreeOnTests(RoutineBase):
    def setUp(self):
        super().setUp()
        self.item3(True)

    def test_it_starts_by_itself_once_and_says_who_decided(self):
        routine = self.routine()
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["by"], run["why"], run["turn"], run["routine_id"]), ("running", "auto3", "on_time", 1, routine["id"]))
        self.assertEqual(len(self.sent()), 1)
        (row,) = self.runner.actions()
        self.assertEqual((row["by"], row["by_text"], row["kind"]), ("auto3", "自己動手第 3 項", "routine_started"))
        self.assertIn("市集日報", row["what"])

    def test_the_run_is_a_new_chat_for_the_routines_employee_with_the_persons_text_and_no_new_field(self):
        self.routine()
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        chat = self.service.get(run["chat_id"])
        self.assertEqual(chat["chat"]["profile_id"], self.writer)
        (said,) = [r for r in chat["records"] if r["kind"] == "user_message"]
        self.assertNotIn("origin", said)
        self.assertTrue(said["text"].endswith("請整理昨天的銷售。"))
        self.assertEqual(rt.chat_titles()[run["chat_id"]], "例行工作：市集日報 11/09 08:00")

    def test_a_turn_that_ends_is_recorded_with_its_cost_and_the_chats_process_is_closed(self):
        self.routine()
        self.tick_to(8, 0, 10)
        chat_id = self.runs()[0]["chat_id"]
        self.tick_after(15)
        self.assertEqual(self.states(), ["running"], "still working: nothing changes")
        self.daemon.finish(chat_id, reply="這是日報。", cost="0.12")
        self.tick()
        (run,) = self.runs()
        self.assertEqual((run["state"], run["cost_usd"], run["reason"]), ("done", "0.12", "result"))
        self.assertEqual(self.daemon.closed, [chat_id])

    def test_a_turn_that_did_not_end_the_normal_way_is_a_failed_run(self):
        self.routine()
        self.tick_to(8, 0, 10)
        chat_id = self.runs()[0]["chat_id"]
        self.daemon.finish(chat_id, reply=None, reason="stopped", cost="0.03", reported=False, is_error=True)
        self.tick()
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"], run["cost_usd"]), ("failed", "stopped", "0.03"))
        self.routine(name="第二件", times=["09:30"])
        self.tick_to(9, 30, 5)
        self.daemon.finish(self.runs()[1]["chat_id"], reply="x", reason="result", is_error=True)
        self.tick()
        self.assertEqual(self.runs()[1]["reason"], "is_error")

    def test_the_same_slot_is_never_done_twice_across_restarts_and_a_clock_set_back(self):
        routine = self.routine()
        self.tick_to(7, 59, 55)
        self.tick_to(8, 0, 10)
        self.assertEqual(len(self.sent()), 1)
        for _ in range(3):                                         # the console is restarted three times
            self.restart()
            self.tick_after(15)
            self.tick_to(8, 0, 20)
        self.assertEqual(len(self.sent()), 1)
        self.go_to(at(2026, 11, 9, 7, 0, 0))                       # the clock is set back an hour
        self.tick()
        self.tick_to(7, 59, 55)
        self.tick_to(8, 0, 10)
        self.tick_after(15)
        self.assertEqual((len(self.runs(routine["id"])), len(self.sent())), (1, 1))

    def test_two_runs_for_the_same_minute_go_one_after_the_other(self):
        self.routine(name="第一件")
        self.routine(name="第二件", profile_id=self.accountant)
        self.tick_to(8, 0, 10)
        self.assertEqual(sorted(self.states()), ["running", "starting"], "one at a time: the other waits its turn")
        self.assertEqual(len(self.sent()), 1)
        first = next(r for r in self.runs() if r["state"] == "running")
        self.tick_after(15)
        self.assertEqual(len(self.sent()), 1)
        self.daemon.finish(first["chat_id"], reply="好", cost="0.05")
        self.tick()
        self.assertEqual(sorted(self.states()), ["done", "running"], "the next one starts in the same pass that closed the first")
        self.assertEqual(len(self.sent()), 2)

    def test_a_routine_whose_employee_can_no_longer_chat_fails_and_sends_nothing(self):
        self.routine()
        ap.save_profile(self.writer, {"name": "文案小編", "position": "social", "model": {"tool": "claude"}, "enabled": False})
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"]), ("failed", "card_disabled"))
        self.assertEqual(self.sent(), [])

    def test_a_routine_switched_off_between_the_reminder_and_the_start_does_not_start(self):
        routine = self.routine()
        self.tick_to(7, 59, 55)
        with mock.patch.object(self.runner, "_drive", return_value={}):
            self.tick_to(8, 0, 10)
        rt.set_enabled(routine["id"], False, self.service.cards(), now=self.now[0])
        self.tick_after(15)
        self.assertEqual(self.states(), ["dismissed"])
        self.assertEqual(self.sent(), [])


class DstTests(RoutineBase):
    def test_the_skipped_hour_is_done_once_at_the_next_minute_that_exists(self):
        self.item3(True)
        self.go_to(at(2026, 3, 7, 12, 0, 0))
        routine = self.routine(days=[0, 1, 2, 3, 4, 5, 6], times=["02:30"])
        self.go_to(at(2026, 3, 8, 1, 59, 50))                      # the night the clocks go forward: 02:00 becomes 03:00
        self.tick()
        self.go_to(at(2026, 3, 8, 3, 0, 5))
        self.tick()
        self.assertEqual([r["slot"] for r in self.runs()], ["2026-03-08T02:30"])
        self.assertEqual(len(self.sent()), 1)
        self.tick_after(15)
        self.tick_after(600)
        self.assertEqual(len(self.runs()), 1)

    def test_the_repeated_hour_is_done_once(self):
        self.item3(True)
        self.go_to(at(2026, 10, 31, 12, 0, 0))
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], times=["01:30"])
        first = datetime.datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=0).timestamp()
        second = datetime.datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=1).timestamp()
        self.go_to(first - 5)
        self.tick()
        self.go_to(first + 5)
        self.tick()
        self.assertEqual(len(self.runs()), 1)
        self.go_to(second - 5)
        self.tick()
        self.go_to(second + 5)
        self.tick()
        self.assertEqual((len(self.runs()), len(self.sent())), (1, 1), "the second 01:30 of the night is not another slot")


class TheMoneyTests(RoutineBase):
    def setUp(self):
        super().setUp()
        self.item3(True)

    def test_a_red_lamp_skips_the_run_and_opens_no_chat(self):
        self.routine()
        self.lamp[0] = "red"
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"], run["chat_id"]), ("skipped", "daily_limit", None))
        self.assertEqual((self.sent(), self.chat_files()), ([], []))
        self.lamp[0] = "green"
        self.tick_after(15)
        self.tick_after(15)
        self.assertEqual(self.states(), ["skipped"], "it does not try again: the next time is the next try")

    def test_a_ledger_that_cannot_be_read_skips_too(self):
        self.routine()
        self.ledger_error[0] = RuntimeError("no ledger")
        self.tick_to(8, 0, 10)
        self.assertEqual((self.runs()[0]["state"], self.runs()[0]["reason"]), ("skipped", "spend_unknown"))
        self.assertEqual(self.sent(), [])

    def test_the_chats_own_refusal_for_the_day_skips_it(self):
        self.routine()
        self.daemon.refuse = ["budget"]
        self.tick_to(8, 0, 10)
        self.assertEqual((self.runs()[0]["state"], self.runs()[0]["reason"]), ("skipped", "daily_limit"))

    def test_the_routines_daily_limit_defaults_to_half_the_days_and_stops_new_runs_when_it_is_reached(self):
        self.routine(name="第一件")
        self.routine(name="第二件", times=["08:00"])
        self.tick_to(8, 0, 10)
        first = next(r for r in self.runs() if r["state"] == "running")
        self.daemon.finish(first["chat_id"], reply="好", cost="1.50")          # half of the default day (US$3.00) is gone
        self.tick()
        states = sorted((r["state"], r["reason"]) for r in self.runs())
        self.assertEqual(states, [("done", "result"), ("skipped", "routine_limit")])
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.runner.limits()["routine_usd"], Decimal("1.50"))

    def test_the_persons_setting_is_the_limit_and_it_is_never_above_the_days(self):
        rt.set_settings({"daily_usd": 0.25}, Decimal("3"))
        self.assertEqual(self.runner.limits()["routine_usd"], Decimal("0.25"))
        self.conf = {"meeting_limits": {"daily_usd": 0.2, "meeting_usd": 0.2, "per_call_usd": 0.1}}
        self.assertEqual(self.runner.limits()["routine_usd"], Decimal("0.2"), "the day was lowered below it")

    def test_only_todays_spend_counts(self):
        routine = self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        yesterday = at(2026, 11, 8, 8, 0, 10)
        run = rt.new_run(routine["id"], "2026-11-08T08:00", state="starting", why="on_time", by="auto3", now=yesterday)
        rt.update_run(run["run_id"], ("starting",), now=yesterday, state="done", cost_usd="9.99", reason="result")
        self.assertEqual(self.runner.spent_today(), Decimal("0"))
        self.tick_to(8, 0, 10)
        self.assertEqual(self.states(routine["id"])[-1], "running")

    def test_what_the_page_says_about_money(self):
        self.routine()
        self.tick_to(8, 0, 10)
        self.daemon.finish(self.runs()[0]["chat_id"], reply="好", cost="0.20")
        self.tick()
        got = self.runner.limits()
        self.assertEqual((got["day_usd"], got["routine_usd"], got["routine_spent_usd"]), (Decimal("3.00"), Decimal("1.50"), Decimal("0.20")))
        self.assertEqual(got["lamp"], "green")


class RefusalAndRecoveryTests(RoutineBase):
    def setUp(self):
        super().setUp()
        self.item3(True)

    def test_an_employee_who_is_busy_is_asked_again_every_thirty_seconds_for_twelve_minutes_and_then_skipped(self):
        self.routine()
        self.daemon.refuse = ["busy"] * 100
        self.tick_to(8, 0, 10)
        self.assertEqual(self.states(), ["starting"])
        self.assertEqual(len(self.daemon.refuse), 99)
        self.tick_after(10)
        self.assertEqual(len(self.daemon.refuse), 99, "not asked again before the 30 seconds")
        for _ in range(23):                                         # up to 11 minutes 50 seconds after the first try
            self.tick_after(30)
            self.assertEqual(self.states(), ["starting"])
        self.assertEqual(len(self.daemon.refuse), 99 - 23)
        self.tick_after(30)
        self.tick_after(30)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"]), ("skipped", "busy"))
        self.assertEqual(self.sent(), [])

    def test_a_busy_employee_who_becomes_free_gets_the_message_in_the_chat_that_was_opened(self):
        self.routine()
        self.daemon.refuse = ["busy"]
        self.tick_to(8, 0, 10)
        self.tick_after(30)
        (run,) = self.runs()
        self.assertEqual(run["state"], "running")
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(len(self.chat_files()), 1, "one chat: the retry did not open another")

    def test_a_room_that_is_full_is_the_same(self):
        self.routine()
        self.daemon.refuse = ["limit", "restarting"]
        self.tick_to(8, 0, 10)
        self.tick_after(30)
        self.tick_after(30)
        self.assertEqual(self.states(), ["running"])

    def test_another_refusal_is_a_failed_run_with_its_code(self):
        self.routine()
        self.daemon.refuse = ["memory_refused"]
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"]), ("failed", "memory_refused"))

    def test_a_console_that_went_away_after_the_send_finds_the_message_and_records_it_without_sending_again(self):
        self.routine()
        self.daemon.after_write = lambda chat_id: (_ for _ in ()).throw(KeyboardInterrupt())      # the console dies as the daemon answers
        with self.assertRaises(KeyboardInterrupt):
            self.tick_to(8, 0, 10)
        self.daemon.after_write = None
        (run,) = self.runs()
        self.assertEqual((run["state"], run["turn"]), ("starting", None), "the record says an intent and no result")
        self.assertEqual(len(self.sent()), 1)
        self.restart()
        self.tick_after(15)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["turn"]), ("running", 1))
        self.assertEqual(len(self.sent()), 1, "found, not sent again")

    def test_a_console_that_went_away_before_the_send_does_not_send_again_either(self):
        self.routine()
        real = self.service.send_for_routine
        self.service.send_for_routine = mock.Mock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.tick_to(8, 0, 10)
        self.service.send_for_routine = real
        self.restart()
        self.tick_after(15)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"]), ("uncertain", "not_found"))
        self.assertEqual(self.sent(), [])
        self.tick_after(15)
        self.tick_after(300)
        self.assertEqual((self.states(), self.sent()), (["uncertain"], []), "an uncertain run is never sent by itself")

    def test_an_answer_that_never_came_looks_in_the_chat_first(self):
        self.routine(name="第一件")
        self.daemon.refuse = []
        real = self.daemon._rpc

        def flaky(op, timeout=10.0, **f):
            result = real(op, timeout, **f)
            if op == "chat_send":
                raise OSError("the answer never came")
            return result
        self.daemon._rpc = flaky
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["turn"]), ("running", 1), "the message is in the chat, so it is recorded")
        self.assertEqual(len(self.sent()), 1)

    def test_an_answer_that_never_came_and_no_message_is_uncertain(self):
        self.routine()
        real = self.daemon._rpc

        def dead_before_writing(op, timeout=10.0, **f):
            if op == "chat_send":
                raise OSError("no socket")
            return real(op, timeout, **f)
        self.daemon._rpc = dead_before_writing
        self.tick_to(8, 0, 10)
        (run,) = self.runs()
        self.assertEqual((run["state"], run["reason"]), ("uncertain", "not_found"))
        self.assertEqual(self.sent(), [])

    def test_a_running_run_is_waited_for_again_after_a_restart(self):
        self.routine()
        self.tick_to(8, 0, 10)
        chat_id = self.runs()[0]["chat_id"]
        self.restart()
        self.tick_after(15)
        self.assertEqual(self.states(), ["running"])
        self.daemon.finish(chat_id, reply="好", cost="0.07")
        self.restart()
        self.tick_after(15)
        self.assertEqual((self.runs()[0]["state"], self.runs()[0]["cost_usd"]), ("done", "0.07"))
        self.assertEqual(len(self.sent()), 1)

    def test_a_chat_that_cannot_be_read_for_a_long_time_is_a_failed_run_with_the_code(self):
        self.routine()
        self.tick_to(8, 0, 10)
        with mock.patch.object(self.service, "get", side_effect=ApiError(409, "damaged", "x")):
            for _ in range(rr_misses()):
                self.tick_after(15)
        self.assertEqual((self.runs()[0]["state"], self.runs()[0]["reason"]), ("failed", "damaged"))

    def test_a_routines_file_that_cannot_be_read_stops_everything_and_nothing_is_written_over_it(self):
        self.routine()
        (cfg.state_dir() / "routines" / "routines.json").write_text("{ no")
        self.tick_to(8, 0, 10)
        self.tick_after(15)
        self.assertEqual((self.runs(), self.sent()), ([], []))
        self.assertTrue(self.runner.last_error)

    def test_a_runs_file_that_cannot_be_read_makes_no_new_run(self):
        self.routine()
        self.tick_to(7, 59, 55)
        with open(cfg.state_dir() / "routines" / "runs.jsonl", "a") as f:
            f.write("not a record\n")
        self.tick_to(8, 0, 10)
        self.assertEqual(self.sent(), [])
        self.assertTrue(self.runner.last_error)


def rr_misses() -> int:
    from vbear import routine_runner
    return routine_runner.READ_MISSES


class ItemThreeAloneDecidesTests(RoutineBase):
    """Guard rule 10: the runner starts by itself only when config.json holds exactly ``True`` for item 3."""

    def run_a_day(self, conf):
        self.conf = conf
        spy = mock.Mock(wraps=self.service.send_for_routine)
        self.service.send_for_routine = spy
        self.routine()
        self.routine(name="第二件", times=["12:00"])
        for ts in (at(2026, 11, 9, 7, 59, 50), at(2026, 11, 9, 8, 0, 10), at(2026, 11, 9, 8, 0, 25), at(2026, 11, 9, 8, 30, 0),
                   at(2026, 11, 9, 11, 59, 55), at(2026, 11, 9, 12, 0, 5), at(2026, 11, 9, 23, 0, 0), at(2026, 11, 10, 8, 0, 5)):
            self.go_to(ts)
            self.tick()
        return spy

    def test_when_it_is_not_true_it_only_ever_reminds_or_puts_away(self):
        cases = [{}, {"autonomy": {}}, {"autonomy": {"create_cards": True, "dispatch": True}},
                 {"autonomy": {"routines": False}}, {"autonomy": {"routines": "true"}}, {"autonomy": {"routines": 1}},
                 {"autonomy": {"routines": None}}, {"autonomy": {"routines": [True]}}, {"autonomy": "routines"},
                 {"autonomy": {"auto_continue": True}},
                 {"_corrupt": True, "autonomy": {"routines": True}}]
        for conf in cases:
            with self.subTest(conf=conf):
                self.tearDown_runs()
                spy = self.run_a_day(conf)
                self.assertEqual(spy.call_count, 0, conf)
                self.assertEqual(self.sent(), [])
                self.assertTrue(set(self.states()) <= {"waiting", "missed"}, self.states())
                self.assertNotIn("auto3", {r["by"] for r in self.runs()})

    def test_a_config_that_raises_is_off(self):
        self.runner.conf = mock.Mock(side_effect=RuntimeError("no config"))
        self.routine()
        self.go_to(at(2026, 11, 9, 8, 0, 10))
        self.runner.tick()
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.states(), ["waiting"])

    def test_when_it_is_true_the_same_day_starts_by_itself(self):
        spy = self.run_a_day({"autonomy": {"routines": True}})
        self.assertEqual(spy.call_count, 1, "one at a time: the second routine waits for the first to end")
        self.assertIn("auto3", {r["by"] for r in self.runs()})

    def tearDown_runs(self):
        """A fresh state folder for the next case of a loop."""
        import shutil
        folder = cfg.state_dir() / "routines"
        if folder.exists():
            shutil.rmtree(folder)
        self.daemon.sent.clear()
        self.now[0] = MONDAY_0759
        self.restart()


class WhatTheRunnerNeverDoesTests(RoutineBase):
    def test_a_whole_day_with_everything_ticked_writes_no_config_and_changes_no_card(self):
        before = {p: ap.get_profile_readonly(p) for p in (self.writer, self.accountant)}
        routines_before = None
        self.item3(True)
        self.conf["autonomy"]["dispatch"] = True
        self.routine()
        routines_before = (cfg.state_dir() / "routines" / "routines.json").read_bytes()
        for ts in (at(2026, 11, 9, 7, 59, 50), at(2026, 11, 9, 8, 0, 10), at(2026, 11, 9, 8, 1, 0)):
            self.go_to(ts)
            self.tick()
        self.daemon.finish(self.runs()[0]["chat_id"], reply="好", cost="0.01")
        self.tick()
        self.assertFalse((cfg.state_dir() / "config.json").exists(), "the runner never writes config.json")
        self.assertEqual({p: ap.get_profile_readonly(p) for p in before}, before, "no role card was made or changed")
        self.assertEqual((cfg.state_dir() / "routines" / "routines.json").read_bytes(), routines_before)
        self.assertEqual(self.daemon.stopped, [])

    def test_a_card_in_the_chat_is_never_answered_by_the_runner(self):
        self.item3(True)
        self.routine()
        self.tick_to(8, 0, 10)
        chat_id = self.runs()[0]["chat_id"]
        self.service.answer = mock.Mock()
        self.service.stop = mock.Mock()
        for _ in range(60):                                          # an hour of nobody answering a card
            self.tick_after(60)
        self.service.answer.assert_not_called()
        self.assertEqual(self.states(), ["running"], "the runner waits: the chat's own 5 minutes and 10 minutes end the turn")
        self.assertTrue(chat_id)


class TheLoopTests(RoutineBase):
    def test_the_runner_takes_the_lock_once_and_gives_it_back(self):
        from vbear import routine_runner as rrun
        other = rrun.RoutineRunner(chats=lambda: self.service, ledger=self.ledger, conf=lambda: self.conf, clock=lambda: self.now[0], tz=self.TZ)
        self.addCleanup(other.close)
        self.assertTrue(self.runner.start())
        self.assertFalse(other.start())
        self.assertIn("routine-runner.lock", other.last_error)
        self.runner.close()
        self.assertTrue(other.start())
        other.close()


if __name__ == "__main__":
    unittest.main()
