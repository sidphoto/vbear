"""P44-4: 「自己動手」 item 5, the countdown that ends in VBear pressing 「繼續」 for a dispatch (ADR 0010 point 6, ADR 0003).

Seams: ``AutoContinue.tick()`` (what the routine runner calls on every pass), ``AutoContinue.waiting_rows()`` (what the line over every
page reads), ``DispatchRunner.resume_dispatch(did, by=...)`` (what it presses), and the records they leave: the dispatch's own (a
``continued`` event by ``vbear``) and ``<state>/routines/auto-continue.jsonl``. The dispatches are real ones over the dispatch tests'
fake daemon; the clock is a hand-moved one (a Monday in Taipei, so the day is never the machine's); nothing waits for real time and no
CLI runs. Every name here is made up."""
from __future__ import annotations

import datetime
import json
import os
import stat
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from tests.group_fixtures import GroupBase
from tests.test_dispatch_runner import RunnerBase
from tests.test_dispatch import old_hands_plan
from vbear import auto_continue, autonomy, config as cfg, dispatch, groups

TAIPEI = ZoneInfo("Asia/Taipei")
HOUR = 3600.0


def at(month, day, hour, minute=0, second=0) -> float:
    return datetime.datetime(2026, month, day, hour, minute, second, tzinfo=TAIPEI).timestamp()


NOON = at(11, 9, 12, 0)
ON = {"autonomy": {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": True}}


class AutoBase(RunnerBase):
    def setUp(self):
        super().setUp()
        self.now[0] = NOON
        self.dispatcher.clock = lambda: self.now[0]
        self.conf = dict(ON)
        self.calls: list = []
        self.resume_error: list = [None]
        self.usage: list = [{"primary_pct": 100, "primary_resets_at": int(NOON), "reached": "primary"}]
        self.auto = auto_continue.AutoContinue(conf=lambda: self.conf, ledger=self.ledger, resume=self.press, usage=lambda did: self.usage[0],
                                               clock=lambda: self.now[0], tz=TAIPEI)

    def press(self, did, pause_seq):
        self.calls.append((did, pause_seq))
        if self.resume_error[0] is not None:
            raise self.resume_error[0]
        return self.drunner.resume_dispatch(did, by="vbear", expect_pause_seq=pause_seq)

    # -- the world ------------------------------------------------------------------------------------------------------

    def new_dispatch(self) -> str:
        did = self.running(old_hands_plan())
        return did

    def stop_at(self, did, reason="daily_limit", until=None):
        """What the runner writes when it pauses a dispatch, at the clock's now (the paused event's own ``at``)."""
        def change(rec):
            rec["state"], rec["pause"] = "paused", {"reason": reason, "until": until}
            self.dispatcher.add_event(rec, "paused", "vbear", reason=reason, **({"until": until} if until is not None else {}))
        self.dispatcher.mutate(did, change)
        return did

    def paused(self, reason="daily_limit", until=NOON + HOUR) -> str:
        return self.stop_at(self.new_dispatch(), reason, until)

    def go(self, ts) -> dict:
        self.now[0] = ts
        return self.auto.tick()

    def state(self, did) -> str:
        return self.rec(did)["state"]

    def log_rows(self) -> list:
        path = cfg.state_dir() / "routines" / "auto-continue.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ItemFiveDecidesTests(AutoBase):
    """Item 5 is read from 「自己動手」 and nowhere else; anything that is not ``True`` is off, and off presses nothing."""

    def test_it_is_off_for_every_way_of_not_being_on(self):
        did = self.paused()
        far = NOON + 3 * HOUR
        for conf in ({}, {"autonomy": {}}, {"autonomy": {"auto_continue": False}}, {"autonomy": {"auto_continue": 1}},
                     {"autonomy": {"auto_continue": "true"}}, {"autonomy": {"auto_continue": None}}, {"autonomy": "yes"}, {"autonomy": [True]},
                     {"autonomy": {"routines": True, "dispatch": True, "create_cards": True}},
                     {"_corrupt": True, "autonomy": {"auto_continue": True}}, None, "x"):
            with self.subTest(conf=conf):
                self.conf = conf
                self.assertEqual(self.go(far), {})
                self.assertEqual((self.calls, self.state(did)), ([], "paused"))

    def test_a_config_that_cannot_be_asked_is_off(self):
        did = self.paused()

        def broken():
            raise OSError("no config")
        self.auto = auto_continue.AutoContinue(conf=broken, ledger=self.ledger, resume=self.press, usage=lambda d: None,
                                               clock=lambda: self.now[0], tz=TAIPEI)
        self.assertEqual(self.go(NOON + 3 * HOUR), {})
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))

    def test_with_it_off_the_time_only_makes_a_row_to_press_by_hand(self):
        did = self.paused()
        self.conf = {}
        self.go(NOON + HOUR + 600)
        self.assertEqual(self.calls, [])
        rows = self.auto.waiting_rows()
        self.assertEqual([(r["kind"], r["dispatch_id"], r["state"]) for r in rows], [("dispatch_resume", did, "ready")])
        self.dispatcher.resume(did)                            # the person's press: a continue by "you", as before
        self.assertEqual([(e["kind"], e["by"]) for e in self.rec(did)["events"][-1:]], [("continued", "you")])
        self.assertEqual(self.log_rows(), [], "the person's press is not item 5")


class ItemFiveContinuesTests(AutoBase):
    def test_two_minutes_after_the_time_it_presses_continue_once_as_vbear(self):
        did = self.paused(until=NOON + HOUR)
        self.assertEqual(self.go(NOON + HOUR + 119), {})
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))
        self.assertEqual(self.go(NOON + HOUR + 120), {did: "continued"})
        rec = self.rec(did)
        self.assertEqual((rec["state"], rec["pause"]), ("running", None))
        last = rec["events"][-1]
        self.assertEqual((last["kind"], last["by"]), ("continued", "vbear"))
        self.assertIsNone(dispatch.record_problem(rec), "a record v0.17.1 reads: the same keys, a value of BYS")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.go(NOON + HOUR + 200), {}, "nothing is pressed twice for one pause")
        self.assertEqual(len(self.calls), 1)

    def test_the_dispatch_goes_on_where_the_person_would_have_sent_it(self):
        did = self.paused(until=NOON + HOUR)
        self.go(NOON + HOUR + 120)
        self.assertEqual(self.drunner.tick(), {did: "sent:1"})
        self.assertEqual(len(self.daemon.sent), 1)
        self.assertEqual(self.daemon.sent[0]["origin"], {"dispatch": did, "step": 1})

    def test_the_other_file_records_it_with_ids_times_and_a_code_only(self):
        did = self.paused(until=NOON + HOUR)
        self.go(NOON + HOUR + 120)
        rec = self.rec(did)
        pause_seq = next(e["seq"] for e in rec["events"] if e["kind"] == "paused")
        cont_seq = rec["events"][-1]["seq"]
        rows = self.log_rows()
        self.assertEqual(rows, [{"at": NOON + HOUR + 120, "dispatch_id": did, "event_seq": cont_seq, "pause_seq": pause_seq,
                                 "reason": "daily_limit", "item": 5}])
        path = cfg.state_dir() / "routines" / "auto-continue.jsonl"
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        text = path.read_text(encoding="utf-8")
        for word in ("攤位", "請寫", "手工皂", rec["plan"]["title"]):
            self.assertNotIn(word, text)
        self.assertEqual(self.auto.taken(), {(did, cont_seq)})

    def test_it_never_touches_the_config_or_the_cards(self):
        did = self.paused(until=NOON + HOUR)
        before = self.config_bytes()
        cards = self.profile_ids()
        self.go(NOON + HOUR + 120)
        self.assertEqual(self.config_bytes(), before)
        self.assertEqual(self.profile_ids(), cards)
        self.assertEqual(self.state(did), "running")

    def test_a_plan_limit_with_a_time_the_tool_gave_goes_on_when_the_last_report_is_not_full(self):
        did = self.paused("plan_limit", until=NOON + 3 * HOUR)
        self.usage[0] = {"primary_pct": 100, "primary_resets_at": int(NOON + 3 * HOUR), "secondary_pct": 20, "reached": "primary"}
        self.assertEqual(self.go(NOON + 3 * HOUR + 120), {did: "continued"})


class WhatItLeavesAloneTests(AutoBase):
    def test_a_pause_without_a_time_is_never_pressed(self):
        did = self.paused("plan_limit", until=None)
        self.assertEqual(self.go(NOON + 30 * HOUR), {})
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))
        self.assertEqual([r["state"] for r in self.auto.waiting_rows()], ["unknown"])

    def test_the_pauses_that_need_a_look_are_never_pressed_whatever_the_time(self):
        for reason in ("uncertain", "interrupted", "runner_error", "turn_error", "turn_stopped", "turn_timeout", "turn_is_error",
                       "busy", "limit", "restarting", "create_failed", "spend_unknown", "damaged", "chat_unreadable"):
            with self.subTest(reason=reason):
                did = self.paused(reason, until=NOON + 10)
                self.assertEqual(self.go(NOON + HOUR), {})
                self.assertEqual((self.calls, self.state(did)), ([], "paused"))
                self.dispatcher.stop(did)

    def test_a_dispatch_that_is_running_stopped_or_done_is_left_alone(self):
        running = self.new_dispatch()
        stopped = self.stop_at(self.new_dispatch(), until=NOON + 10)
        self.dispatcher.stop(stopped)
        self.go(NOON + HOUR)
        self.assertEqual((self.calls, self.state(running), self.state(stopped)), ([], "running", "stopped"))

    def test_a_step_that_may_or_may_not_have_gone_is_not_sent_again_by_vbear(self):
        did = self.paused(until=NOON + 10)

        def change(rec):
            rec["steps"][0]["state"], rec["steps"][0]["chat_id"] = "sending", self.chat_id
        self.dispatcher.mutate(did, change)
        self.assertEqual(self.go(NOON + HOUR), {})
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))
        with self.assertRaises(dispatch.DispatchError) as ctx:
            self.drunner.resume_dispatch(did, by="vbear")
        self.assertEqual(ctx.exception.code, "needs_look")
        self.assertEqual(self.state(did), "paused")

    def test_a_row_that_is_not_ready_or_not_a_dispatch_is_not_pressed_for_a_group(self):
        """A group whose round is paused for the day only counts down: nothing here writes its log or calls its runner."""
        # (the group half is in GroupOnlyCountsDownTests; here: one more dispatch that is paused and not yet due stays paused)
        did = self.paused(until=NOON + 5 * HOUR)
        self.assertEqual(self.go(NOON + 2 * HOUR), {})
        self.assertEqual(self.state(did), "paused")


class StillCannotGoOnTests(AutoBase):
    def test_a_red_lamp_waits_and_the_next_pass_after_it_turns_goes_on(self):
        did = self.paused(until=NOON + HOUR)
        self.lamp[0] = "red"
        self.assertEqual(self.go(NOON + HOUR + 300), {})
        self.assertEqual(self.calls, [])
        self.lamp[0] = "green"
        self.assertEqual(self.go(NOON + HOUR + 330), {did: "continued"})

    def test_a_ledger_that_cannot_be_read_or_says_something_else_waits(self):
        did = self.paused(until=NOON + HOUR)
        self.ledger_error[0] = OSError("no ledger")
        self.assertEqual(self.go(NOON + HOUR + 300), {})
        self.ledger_error[0] = None
        self.lamp[0] = "purple"
        self.assertEqual(self.go(NOON + HOUR + 330), {})
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))
        self.lamp[0] = "yellow"
        self.assertEqual(self.go(NOON + HOUR + 360), {did: "continued"}, "yellow is not red")

    def test_a_plan_that_is_still_full_waits_and_one_that_cannot_be_read_waits(self):
        did = self.paused("plan_limit", until=NOON + HOUR)
        future = int(NOON + 9 * HOUR)
        self.usage[0] = {"primary_pct": 100, "primary_resets_at": future, "reached": "primary"}
        self.assertEqual(self.go(NOON + HOUR + 300), {})
        self.usage[0] = {"primary_pct": 100, "primary_resets_at": None, "reached": "primary"}
        self.assertEqual(self.go(NOON + HOUR + 330), {}, "full with no time to be usable again is still full")
        self.usage[0] = None
        self.assertEqual(self.go(NOON + HOUR + 360), {}, "no report to look at is not a reason to go on")
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))
        self.usage[0] = {"primary_pct": 12, "primary_resets_at": future, "reached": None}
        self.assertEqual(self.go(NOON + HOUR + 390), {did: "continued"})

    def test_a_usage_that_raises_waits(self):
        did = self.paused("plan_limit", until=NOON + HOUR)

        def raising(_did):
            raise OSError("chat unreadable")
        self.auto = auto_continue.AutoContinue(conf=lambda: self.conf, ledger=self.ledger, resume=self.press, usage=raising,
                                               clock=lambda: self.now[0], tz=TAIPEI)
        self.assertEqual(self.go(NOON + HOUR + 300), {})
        self.assertEqual(self.state(did), "paused")

    def test_the_daily_limit_does_not_ask_the_plan(self):
        did = self.paused("daily_limit", until=NOON + HOUR)
        self.usage[0] = None
        self.assertEqual(self.go(NOON + HOUR + 120), {did: "continued"})

    def test_a_time_that_went_by_12_hours_ago_or_more_is_only_listed(self):
        did = self.paused(until=NOON + HOUR)
        self.assertEqual(self.go(NOON + HOUR + 12 * HOUR + 1), {})
        self.assertEqual((self.calls, self.state(did)), ([], "paused"))
        self.assertEqual([r["state"] for r in self.auto.waiting_rows()], ["ready"])

    def test_12_hours_exactly_still_goes_on(self):
        did = self.paused(until=NOON + HOUR)
        self.assertEqual(self.go(NOON + HOUR + 12 * HOUR), {did: "continued"})


class LimitsTests(AutoBase):
    def cycle(self, did, start, until_after=HOUR, reason="daily_limit"):
        """Pause at ``start`` until ``start + until_after``; the pass two minutes after the time."""
        self.now[0] = start
        self.stop_at(did, reason, start + until_after)
        return self.go(start + until_after + 120)

    def test_a_failed_press_is_not_tried_again_for_the_same_pause(self):
        did = self.paused(until=NOON + HOUR)
        self.resume_error[0] = dispatch.DispatchError("chat_unreadable")
        self.assertEqual(self.go(NOON + HOUR + 120), {did: "failed"})
        for extra in (150, 400, 900):
            self.assertEqual(self.go(NOON + HOUR + extra), {})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.state(did), "paused")
        self.assertEqual(self.log_rows(), [], "nothing was pressed, so nothing is recorded as pressed")
        self.assertEqual([r["state"] for r in self.auto.waiting_rows()], ["ready"], "the person is still asked")

    def test_a_press_that_the_person_made_first_is_not_pressed_again(self):
        did = self.paused(until=NOON + HOUR)
        self.now[0] = NOON + HOUR + 60
        self.dispatcher.resume(did)
        self.assertEqual(self.go(NOON + HOUR + 120), {})
        self.assertEqual(self.calls, [])

    def test_each_dispatch_is_continued_by_itself_three_times_at_most(self):
        did = self.new_dispatch()
        start = NOON
        for n in range(3):
            self.assertEqual(self.cycle(did, start), {did: "continued"}, n)
            start += HOUR + 120 + 700            # the next pause comes more than 10 minutes after the press
        self.assertEqual(self.cycle(did, start), {}, "the fourth time only asks")
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.state(did), "paused")
        self.assertEqual([r["state"] for r in self.auto.waiting_rows()], ["ready"])
        self.assertEqual(len([r for r in self.log_rows() if r["dispatch_id"] == did]), 3)

    def test_the_count_of_a_dispatch_is_also_read_from_its_own_record(self):
        """A log that cannot be written must not make the limit forget: the ``continued`` events of the record count too."""
        folder = cfg.state_dir() / "routines"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        (folder / "auto-continue.jsonl").mkdir()                  # a directory where the file should be: every append fails
        did = self.new_dispatch()
        start = NOON
        for n in range(3):
            self.assertEqual(self.cycle(did, start), {did: "continued"}, n)
            start += HOUR + 120 + 700
        self.assertEqual(self.cycle(did, start), {})
        self.assertEqual(len(self.calls), 3)

    def test_five_a_day_in_all_and_the_count_starts_again_on_the_next_day(self):
        due = [self.paused(until=at(11, 9, 13, 0)) for _ in range(6)]
        late = self.paused(until=at(11, 9, 23, 0))
        got = self.go(at(11, 9, 13, 2))
        self.assertEqual(len(got), 5, "five go on, the sixth (due at the same time) does not")
        self.assertEqual(len(self.calls), 5)
        left = [d for d in due if self.state(d) == "paused"]
        self.assertEqual(len(left), 1)
        self.assertEqual(self.go(at(11, 9, 23, 2)), {}, "the day's five are used up (23:02 of the same local day)")
        self.assertEqual(self.state(late), "paused")
        self.assertEqual([r["state"] for r in self.auto.waiting_rows()].count("ready"), 2)
        got = self.go(at(11, 10, 0, 30))
        self.assertEqual(sorted(got), sorted(left + [late]), "a new local day, five more")

    def test_a_pause_again_within_10_minutes_for_the_same_reason_is_only_asked(self):
        did = self.new_dispatch()
        self.assertEqual(self.cycle(did, NOON), {did: "continued"})
        pressed_at = NOON + HOUR + 120
        self.now[0] = pressed_at + 600                           # paused again exactly 10 minutes after the press
        self.stop_at(did, "daily_limit", pressed_at + 600 + HOUR)
        self.assertEqual(self.go(pressed_at + 600 + HOUR + 120), {})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([r["state"] for r in self.auto.waiting_rows()], ["ready"])

    def test_a_pause_after_more_than_10_minutes_or_for_another_reason_may_go_on(self):
        did = self.new_dispatch()
        self.assertEqual(self.cycle(did, NOON), {did: "continued"})
        pressed_at = NOON + HOUR + 120
        self.now[0] = pressed_at + 601
        self.stop_at(did, "daily_limit", pressed_at + 601 + HOUR)
        self.assertEqual(self.go(pressed_at + 601 + HOUR + 120), {did: "continued"}, "601 seconds is not within 10 minutes")
        again = pressed_at + 601 + HOUR + 120
        self.now[0] = again + 60
        self.stop_at(did, "plan_limit", again + 60 + HOUR)
        self.usage[0] = {"primary_pct": 100, "primary_resets_at": int(again + 60 + HOUR), "reached": "primary"}
        self.assertEqual(self.go(again + 60 + HOUR + 120), {did: "continued"}, "another reason, soon after")


class RowsTests(AutoBase):
    def test_a_dispatch_row_counts_down_then_is_ready_and_has_a_name_and_a_time_only(self):
        did = self.paused(until=NOON + 2 * HOUR + 5 * 60)
        self.now[0] = NOON
        rows = self.auto.waiting_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual({k: row[k] for k in ("kind", "dispatch_id", "name", "state", "until", "reason")},
                         {"kind": "dispatch_resume", "dispatch_id": did, "name": self.rec(did)["plan"]["title"], "state": "counting",
                          "until": NOON + 2 * HOUR + 5 * 60, "reason": "daily_limit"})
        self.assertTrue(row["text"].startswith("還有 2 小時 5 分可以繼續（"), row["text"])
        self.assertEqual(set(row), {"kind", "dispatch_id", "name", "state", "until", "reason", "text"})
        self.now[0] = NOON + 3 * HOUR
        self.assertEqual(self.auto.waiting_rows()[0]["state"], "ready")

    def test_other_reasons_and_other_states_have_no_row_and_nothing_makes_a_row_when_item_5_is_off_or_on(self):
        self.paused("uncertain", until=None)
        self.new_dispatch()
        for conf in ({}, dict(ON)):
            self.conf = conf
            self.assertEqual(self.auto.waiting_rows(), [])


class GroupOnlyCountsDownTests(GroupBase):
    def test_a_group_paused_for_the_day_has_a_row_and_nothing_is_pressed(self):
        gid = self.make_group(name="市集準備")["group"]["id"]
        self.groups.say(gid, {"text": "大家好", "to": "all"})
        until = self.now[0] + 2 * HOUR
        with groups.log_tx(gid) as tx:
            tx.append("paused", round=1, reason="daily_limit", until=until)
        auto = auto_continue.AutoContinue(conf=lambda: dict(ON), ledger=self.ledger, resume=lambda *a: self.fail("a group is not pressed"),
                                          usage=lambda d: None, clock=lambda: self.now[0], tz=TAIPEI)
        rows = auto.waiting_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0][k] for k in ("kind", "group_id", "name", "state", "until")},
                         {"kind": "group_resume", "group_id": gid, "name": "市集準備", "state": "counting", "until": until})
        self.assertTrue(rows[0]["text"].startswith("還有 2 小時可以繼續（"), rows[0]["text"])
        self.now[0] = until + 6 * HOUR
        self.assertEqual(auto.tick(), {}, "the time is up and item 5 is on: a group still waits for the person")
        self.assertEqual(self.groups.get(gid)["round"]["state"], "paused")
        self.assertEqual(self.runner.tick(), {})
        self.assertEqual(auto.waiting_rows()[0]["state"], "ready")

    def test_a_skipped_employee_or_another_reason_makes_no_group_row(self):
        gid = self.make_group()["group"]["id"]
        self.groups.say(gid, {"text": "大家好", "to": "all"})
        with groups.log_tx(gid) as tx:
            tx.append("paused", round=1, reason="uncertain", until=None)
        auto = auto_continue.AutoContinue(conf=lambda: dict(ON), ledger=self.ledger, resume=lambda *a: None, usage=lambda d: None,
                                          clock=lambda: self.now[0], tz=TAIPEI)
        self.assertEqual(auto.waiting_rows(), [])


class ResumeDispatchTests(AutoBase):
    def test_by_is_you_or_vbear_and_nothing_else(self):
        did = self.paused(until=NOON + 10)
        for bad in ("auto5", "auto1", "", None, 5, "VBear"):
            with self.assertRaises(dispatch.DispatchError, msg=repr(bad)):
                self.drunner.resume_dispatch(did, by=bad)
        self.assertEqual(self.state(did), "paused")
        self.drunner.resume_dispatch(did)
        self.assertEqual(self.rec(did)["events"][-1]["by"], "you", "the default is the person")

    def test_it_can_name_the_pause_it_means_and_a_newer_pause_is_not_that_one(self):
        did = self.paused(until=NOON + 10)
        old = next(e["seq"] for e in self.rec(did)["events"] if e["kind"] == "paused")
        self.drunner.resume_dispatch(did)
        self.stop_at(did, "daily_limit", NOON + HOUR)
        with self.assertRaises(dispatch.DispatchError) as ctx:
            self.drunner.resume_dispatch(did, by="vbear", expect_pause_seq=old)
        self.assertEqual(ctx.exception.code, "not_paused")
        self.assertEqual(self.state(did), "paused")


class TheRoutineRunnerCallsItTests(unittest.TestCase):
    """One line in the routine runner's pass: ``auto_continue.tick()`` after the routines' own work, whatever happens there."""

    def setUp(self):
        from tests.routine_fixtures import RoutineBase
        self.base = type("B", (RoutineBase,), {"runTest": lambda s: None})()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)

    def runner(self, auto):
        from vbear import routine_runner as rrun
        r = rrun.RoutineRunner(chats=lambda: self.base.service, ledger=self.base.ledger, conf=lambda: self.base.conf,
                               clock=lambda: self.base.now[0], tz=self.base.TZ, auto_continue=auto)
        self.addCleanup(r.close)
        return r

    def test_every_pass_calls_it_once_and_the_routines_result_is_unchanged(self):
        calls = []

        class Spy:
            def tick(self_inner):
                calls.append(1)
                return {"d-1": "continued"}
        runner = self.runner(Spy())
        self.assertEqual(runner.tick(), {})
        runner.tick()
        self.assertEqual(len(calls), 2)

    def test_a_failure_in_it_does_not_stop_the_pass_or_the_thread(self):
        class Bad:
            def tick(self_inner):
                raise RuntimeError("boom")
        runner = self.runner(Bad())
        self.base.item3(True)
        self.assertEqual(runner.tick(), {})
        self.assertIsNotNone(runner.last_error)
        self.assertNotIn("boom", runner.last_error, "the log has codes, not messages")

    def test_without_it_the_pass_is_as_it_was(self):
        self.assertEqual(self.runner(None).tick(), {})


if __name__ == "__main__":
    unittest.main()
