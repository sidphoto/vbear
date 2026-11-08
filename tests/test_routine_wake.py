"""P44-3: waking up. The heartbeat, the list of what a sleeping Mac (or a VBear that was closed) missed, and the rules of catching up
(ADR 0010 point 6): one run per routine and only the latest missed time, by itself only with 「自己動手」 item 3 and only for the last
12 hours and three routines per wake-up, otherwise listed for the person. A hand-moved clock in New York; no CLI, no real waiting."""
from __future__ import annotations

import json
import os
import stat
import unittest
from unittest import mock

from tests.routine_fixtures import RoutineBase, at
from tests.test_routines_api import RoutinesApiBase
from vbear import config as cfg, routine_rules as rr, routines as rt
from vbear.api_error import ApiError

MON_0759 = at(2026, 11, 9, 7, 59, 0)


class WakeBase(RoutineBase):
    def sleep_until(self, ts):
        """The Mac sleeps with VBear open: the next time anyone looks, the wall clock has jumped."""
        self.go_to(ts)
        return self.tick()

    def listed(self):
        return [r for r in self.runner.waiting_rows() if r["kind"] == "routine_missed"]

    def beat(self):
        return json.loads((cfg.state_dir() / "routines" / "heartbeat.json").read_text())


class HeartbeatTests(WakeBase):
    def test_the_first_pass_writes_a_private_heartbeat_and_then_one_a_minute(self):
        self.routine()
        self.tick()
        path = cfg.state_dir() / "routines" / "heartbeat.json"
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(self.beat(), {"v": 1, "at": MON_0759})
        for _ in range(3):                                          # 15, 30, 45 seconds: not yet
            self.tick_after(15)
        self.assertEqual(self.beat()["at"], MON_0759)
        self.tick_after(15)                                         # 60 seconds
        self.assertEqual(self.beat()["at"], MON_0759 + 60)
        self.assertEqual(rt.read_heartbeat(), MON_0759 + 60)

    def test_no_file_and_a_file_that_cannot_be_read_are_the_same_no_heartbeat(self):
        self.assertIsNone(rt.read_heartbeat())
        folder = cfg.state_dir() / "routines"
        folder.mkdir(mode=0o700, exist_ok=True)
        for bad in ("not json", "[]", json.dumps({"v": 1}), json.dumps({"v": 1, "at": "x"}), json.dumps({"v": 1, "at": -1}),
                    json.dumps({"v": 2, "at": 5}), json.dumps({"v": 1, "at": True})):
            (folder / "heartbeat.json").write_text(bad)
            self.assertIsNone(rt.read_heartbeat(), bad)

    def test_a_heartbeat_that_is_a_link_is_not_followed(self):
        folder = cfg.state_dir() / "routines"
        folder.mkdir(mode=0o700, exist_ok=True)
        real = folder / "elsewhere.json"
        real.write_text(json.dumps({"v": 1, "at": 5}))
        os.symlink(real, folder / "heartbeat.json")
        self.assertIsNone(rt.read_heartbeat())

    def test_nothing_of_a_routine_is_in_the_heartbeat(self):
        self.routine(name="市集日報")
        self.tick()
        self.assertEqual(set(self.beat()), {"v", "at"})


class NoHeartbeatNoMissedTests(WakeBase):
    def test_a_fresh_upgrade_has_no_heartbeat_and_counts_nothing_as_missed(self):
        self.routine()
        self.go_to(at(2026, 11, 9, 7, 0, 0))
        routine = rt.read_routines()[0][0]
        rt.edit(routine["id"], {"enabled": False}, self.service.cards(), now=self.now[0])
        rt.edit(routine["id"], {"enabled": True}, self.service.cards(), now=self.now[0])
        self.go_to(at(2026, 11, 10, 9, 0, 0))                       # a day later, the first pass of a new console, no heartbeat file
        self.tick()
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.listed(), [])

    def test_a_slot_that_is_still_on_time_when_the_console_starts_is_still_done(self):
        self.routine()
        self.tick_to(8, 0, 40)                                       # no heartbeat, 40 seconds after the time
        self.assertEqual(self.states(), ["waiting"])


class WhatWasMissedTests(WakeBase):
    def asleep_three_days(self, **over):
        """A routine at 08:00 every day; VBear last looked Monday 07:59 and the Mac wakes Wednesday 12:00 (Mon, Tue and Wed 08:00 passed)."""
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], **over)
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))

    def test_three_days_asleep_is_one_row_with_the_count_and_the_latest_time_and_nothing_is_sent(self):
        self.asleep_three_days()
        (row,) = self.listed()
        self.assertEqual((row["count"], row["slot"], row["name"]), (3, "2026-11-11T08:00", "市集日報"))
        self.assertEqual(row["due_at"], at(2026, 11, 11, 8, 0, 0))
        self.assertNotIn("text", row)
        self.assertEqual(self.sent(), [])
        self.assertEqual(sorted((r["slot"], r["state"]) for r in self.runs()),
                         [("2026-11-09T08:00", "missed"), ("2026-11-10T08:00", "missed"), ("2026-11-11T08:00", "waiting")])
        self.assertEqual({r["why"] for r in self.runs()}, {"catch_up"})

    def test_the_list_is_the_same_after_another_pass_and_after_a_restart(self):
        self.asleep_three_days()
        for _ in range(3):
            self.restart()
            self.tick_after(15)
        self.assertEqual(len(self.runs()), 3)
        self.assertEqual([r["count"] for r in self.listed()], [3])

    def test_a_console_that_was_closed_is_the_same_as_a_sleeping_mac(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.runner.close()
        self.restart()                                               # a new console, hours later
        self.go_to(at(2026, 11, 10, 9, 30, 0))
        self.tick()
        (row,) = self.listed()
        self.assertEqual((row["count"], row["slot"]), (2, "2026-11-10T08:00"))

    def test_the_times_before_the_routine_was_switched_on_are_not_missed(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], enabled=False)
        self.tick()
        self.go_to(at(2026, 11, 10, 7, 0, 0))
        routine = rt.read_routines()[0][0]
        rt.set_enabled(routine["id"], True, self.service.cards(), now=self.now[0])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        (row,) = self.listed()
        self.assertEqual((row["count"], row["slot"]), (2, "2026-11-11T08:00"), "Monday's and the earlier Tuesday time are before it was on")

    def test_a_routine_that_is_off_misses_nothing(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        routine = rt.read_routines()[0][0]
        rt.set_enabled(routine["id"], False, self.service.cards(), now=self.now[0])
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        self.assertEqual((self.runs(), self.listed()), ([], []))

    def test_only_seven_days_back_are_counted(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 29, 9, 0, 0))                  # twenty days asleep
        (row,) = self.listed()
        self.assertEqual((row["count"], row["slot"]), (7, "2026-11-29T08:00"))
        self.assertEqual(len(self.runs()), 7)

    def test_every_routine_has_its_own_row(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], name="第一件")
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], name="第二件", times=["09:30"])
        self.tick()
        self.sleep_until(at(2026, 11, 10, 12, 0, 0))
        rows = self.listed()
        self.assertEqual([(r["name"], r["count"], r["slot"]) for r in rows],
                         [("第一件", 2, "2026-11-10T08:00"), ("第二件", 2, "2026-11-10T09:30")])

    def test_a_routine_whose_own_time_is_now_does_not_also_catch_up(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 8, 0, 30))                 # woke up 30 seconds after Wednesday's time
        self.assertEqual(self.listed(), [])
        self.assertEqual(sorted((r["slot"], r["state"], r["reason"]) for r in self.runs()),
                         [("2026-11-09T08:00", "missed", "superseded"), ("2026-11-10T08:00", "missed", "superseded"),
                          ("2026-11-11T08:00", "waiting", None)], "the time that is due now is the ordinary reminder")
        self.assertEqual([r["kind"] for r in self.runner.waiting_rows()], ["routine_due"])

    def test_a_clock_set_back_is_not_a_sleep(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 9, 6, 0, 0))
        self.tick_after(15)
        self.assertEqual(self.runs(), [])

    def test_a_short_pause_is_not_a_sleep(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick_to(7, 59, 0)
        self.tick_to(8, 0, 20)                                       # 80 seconds between two looks: the thread was late, not asleep
        self.assertEqual(self.states(), ["waiting"])
        self.assertEqual(self.listed(), [])

    def test_the_gap_that_makes_a_sleep_is_more_than_ninety_seconds(self):
        self.assertEqual(rr.WAKE_GAP_S, 90.0)
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], times=["08:00", "10:00"])
        self.tick_to(7, 59, 0)
        self.tick_to(8, 0, 10)
        self.tick_after(91)                                          # nothing is due in the 91 seconds; the look is a sleep's look
        self.tick_after(3)
        self.tick_to(8, 5, 0)
        self.assertEqual(self.listed(), [], "nothing was missed in those gaps")


class CatchUpByItselfTests(WakeBase):
    """Item 3 on: the latest missed time, if it is under 12 hours old, is done by VBear (by: auto3, why: catch_up)."""

    def setUp(self):
        super().setUp()
        self.item3(True)

    def test_under_twelve_hours_it_is_done_once_by_itself(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))                 # Wednesday's time was 4 hours ago, Monday's and Tuesday's before
        started = sorted((r["slot"], r["state"], r["by"]) for r in self.runs() if r["state"] != "missed")
        self.assertEqual(started, [("2026-11-11T08:00", "running", "auto3")])
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(sorted((r["slot"], r["state"]) for r in self.runs() if r["state"] == "missed"),
                         [("2026-11-09T08:00", "missed"), ("2026-11-10T08:00", "missed")], "the older ones are not done too")
        self.assertEqual(self.listed(), [])
        run = next(r for r in self.runs() if r["state"] == "running")
        self.assertEqual((run["why"], run["by"]), ("catch_up", "auto3"))
        self.tick_after(15)
        self.tick_after(600)
        self.assertEqual(len(self.sent()), 1, "never twice")

    def test_it_is_in_the_list_of_what_the_ai_did_with_the_item_that_decided(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        (action,) = self.runner.actions()
        self.assertEqual((action["by_text"], action["what"]), ("自己動手第 3 項", "例行工作「市集日報」補做了一次"))

    def test_the_message_is_the_routines_own_message_for_the_missed_time(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        self.assertIn("2026-11-11T08:00", self.sent()[0]["text"])

    def test_over_twelve_hours_it_is_only_listed(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 7, 0, 0))                  # Tuesday's time was 23 hours ago
        (row,) = self.listed()
        self.assertEqual((row["count"], row["slot"], row["too_old"]), (2, "2026-11-10T08:00", True))
        self.assertEqual(self.sent(), [])
        self.assertNotIn("auto3", {r["by"] for r in self.runs()})

    def test_exactly_twelve_hours_is_too_old(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 10, 20, 0, 0))
        self.assertEqual([r["too_old"] for r in self.listed()], [True])
        self.assertEqual(self.sent(), [])

    def test_five_routines_missed_three_are_done_one_after_the_other_and_two_are_listed(self):
        for i, hh in enumerate(("08:00", "09:00", "10:00", "11:00", "12:00")):
            self.routine(days=[0, 1, 2, 3, 4, 5, 6], name=f"第{i + 1}件", times=[hh])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 15, 0, 0))
        by_name = {r["routine_id"]: r for r in self.runs() if r["state"] != "missed"}
        names = {r["id"]: r["name"] for r in rt.read_routines()[0]}
        # the earliest three Wednesday times are queued by VBear; the other two stay in the list
        self.assertEqual(sorted(names[i] for i, r in by_name.items() if r["by"] == "auto3"), ["第1件", "第2件", "第3件"])
        self.assertEqual(sorted(r["name"] for r in self.listed()), ["第4件", "第5件"])
        self.assertEqual(len(self.sent()), 1, "one at a time")
        for expected in (2, 3):
            running = next(r for r in self.runs() if r["state"] == "running")
            self.daemon.finish(running["chat_id"], reply="好", cost="0.01")
            self.tick()
            self.assertEqual(len(self.sent()), expected)
        running = next(r for r in self.runs() if r["state"] == "running")
        self.daemon.finish(running["chat_id"], reply="好", cost="0.01")
        for _ in range(3):
            self.tick_after(15)
        self.assertEqual(len(self.sent()), 3, "the list is the person's")
        self.assertEqual(sorted(r["name"] for r in self.listed()), ["第4件", "第5件"])

    def test_a_routine_that_was_switched_off_while_the_mac_slept_is_not_done(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        routine = rt.read_routines()[0][0]
        self.go_to(at(2026, 11, 10, 7, 0, 0))
        rt.set_enabled(routine["id"], False, self.service.cards(), now=self.now[0])
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        self.assertEqual((self.sent(), self.listed()), ([], []))

    def test_the_day_limit_reached_makes_it_skipped_with_the_reason_and_it_is_not_tried_again(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.lamp[0] = "red"
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        run = next(r for r in self.runs() if r["slot"] == "2026-11-11T08:00")
        self.assertEqual((run["state"], run["reason"]), ("skipped", "daily_limit"))
        self.lamp[0] = "green"
        for _ in range(4):
            self.tick_after(15)
        self.assertEqual((self.sent(), run["state"]), ([], "skipped"))
        self.assertEqual(self.listed(), [])

    def test_the_routines_own_limit_reached_is_the_same(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        rt.set_settings({"daily_usd": 0.01}, 3)
        self.tick()
        wednesday = at(2026, 11, 11, 9, 0, 0)
        done = rt.new_run(rt.read_routines()[0][0]["id"], "2026-11-11T07:00", state="starting", why="now", by="you", now=wednesday)
        rt.update_run(done["run_id"], ("starting",), now=wednesday, state="done", cost_usd="0.50")
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        run = next(r for r in self.runs() if r["slot"] == "2026-11-11T08:00")
        self.assertEqual((run["state"], run["reason"]), ("skipped", "routine_limit"))
        self.assertEqual(self.sent(), [])


class CatchUpByThePersonTests(WakeBase):
    def asleep(self):
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))

    def test_item_3_off_only_lists_and_the_press_starts_one_run_by_you(self):
        self.asleep()
        routine = rt.read_routines()[0][0]
        self.assertEqual((self.sent(), len(self.listed())), ([], 1))
        got = self.runner.catch_up(routine["id"])
        self.assertEqual((got["state"], got["by"], got["why"], got["slot"]), ("starting", "you", "catch_up", "2026-11-11T08:00"))
        self.tick()
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.listed(), [])
        self.assertEqual(sorted(r["state"] for r in self.runs()), ["missed", "missed", "running"])
        with self.assertRaises(ApiError) as ctx:
            self.runner.catch_up(routine["id"])
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "routine_gone"))
        self.tick_after(15)
        self.assertEqual(len(self.sent()), 1)

    def test_the_person_can_catch_up_what_is_over_twelve_hours_old(self):
        self.item3(True)
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 7, 0, 0))
        routine = rt.read_routines()[0][0]
        self.assertEqual(self.sent(), [])
        self.runner.catch_up(routine["id"])
        self.tick()
        self.assertEqual(len(self.sent()), 1)

    def test_not_needed_closes_the_row_and_sends_nothing(self):
        self.asleep()
        routine = rt.read_routines()[0][0]
        got = self.runner.dismiss_missed(routine["id"])
        self.assertEqual((got["state"], got["by"], got["reason"]), ("dismissed", "you", "you"))
        self.assertEqual(self.listed(), [])
        self.tick_after(15)
        self.assertEqual((self.sent(), self.listed()), ([], []))
        with self.assertRaises(ApiError) as ctx:
            self.runner.dismiss_missed(routine["id"])
        self.assertEqual(ctx.exception.status, 409)

    def test_a_routine_that_is_not_there_is_404(self):
        for call in (self.runner.catch_up, self.runner.dismiss_missed):
            with self.assertRaises(ApiError) as ctx:
                call("r-000000000000")
            self.assertEqual(ctx.exception.status, 404)

    def test_the_row_is_put_away_when_the_routines_next_time_comes_whether_or_not_it_was_done(self):
        self.asleep()
        self.tick_to(7, 59, 30, day=(2026, 11, 12))                  # Thursday just before its time: the row is still there
        self.assertEqual(len(self.listed()), 1)
        self.tick_to(8, 0, 10, day=(2026, 11, 12))                   # Thursday's time has come, and it has its own reminder
        self.assertEqual(self.listed(), [])
        old = [r for r in self.runs() if r["slot"] == "2026-11-11T08:00"][0]
        self.assertEqual((old["state"], old["reason"]), ("missed", "unanswered"))
        self.assertEqual([r["kind"] for r in self.runner.waiting_rows()], ["routine_due"])

    def test_the_row_is_put_away_after_twenty_four_hours(self):
        self.routine(days=[0], times=["08:00"])                      # weekly: the next time is far away
        self.tick()
        self.sleep_until(at(2026, 11, 9, 20, 0, 0))                  # 12 hours after: too old to do by itself, listed
        (row,) = self.listed()
        self.assertTrue(row["too_old"])
        self.go_to(at(2026, 11, 10, 19, 59, 0))
        self.tick()
        self.assertEqual(len(self.listed()), 1, "just under 24 hours after it was listed")
        self.go_to(at(2026, 11, 10, 20, 0, 1))
        self.tick()
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.runs()[0]["state"], "missed")

    def test_a_row_of_a_routine_that_was_deleted_is_put_away(self):
        self.asleep()
        rt.delete(rt.read_routines()[0][0]["id"])
        self.tick_after(15)
        self.assertEqual(self.listed(), [])
        self.assertIn("dismissed", self.states())


class ItemThreeAloneDecidesTests(WakeBase):
    """Guard rule 10 over the wake: catching up by itself reads item 3 and nothing else."""

    def test_when_it_is_not_true_a_wake_up_only_lists(self):
        cases = [{}, {"autonomy": {}}, {"autonomy": {"routines": False}}, {"autonomy": {"routines": "true"}}, {"autonomy": {"routines": 1}},
                 {"autonomy": {"auto_continue": True}}, {"autonomy": "routines"}, {"_corrupt": True, "autonomy": {"routines": True}}]
        for conf in cases:
            with self.subTest(conf=conf):
                self.conf = conf
                spy = mock.Mock(wraps=self.service.send_for_routine)
                self.service.send_for_routine = spy
                for p in cfg.state_dir().glob("routines"):
                    import shutil
                    shutil.rmtree(p)
                self.go_to(MON_0759)
                self.restart()
                self.routine(days=[0, 1, 2, 3, 4, 5, 6])
                self.tick()
                self.sleep_until(at(2026, 11, 11, 12, 0, 0))
                self.assertEqual(spy.call_count, 0)
                self.assertEqual(len(self.listed()), 1)
                self.assertNotIn("auto3", {r["by"] for r in self.runs()})

    def test_a_config_that_raises_is_off_here_too(self):
        self.runner.conf = mock.Mock(side_effect=RuntimeError("no config"))
        self.routine(days=[0, 1, 2, 3, 4, 5, 6])
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        self.assertEqual((self.sent(), len(self.listed())), ([], 1))


class WhatTheWakeNeverDoesTests(WakeBase):
    def test_no_config_no_card_and_no_record_with_a_name_or_a_word(self):
        self.item3(True)
        self.routine(days=[0, 1, 2, 3, 4, 5, 6], name="獨一無二的名稱", text="獨一無二的內容")
        self.tick()
        self.sleep_until(at(2026, 11, 11, 12, 0, 0))
        folder = cfg.state_dir() / "routines"
        for name in ("runs.jsonl", "heartbeat.json", "log.jsonl"):
            path = folder / name
            if path.exists():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("獨一無二", text, name)
        self.assertFalse((cfg.state_dir() / "config.json").exists())


class ApiTests(RoutinesApiBase):
    """The routes: the list the pages read, the person's 補做 and 不用了, and the setting of keeping the Mac awake."""

    def asleep(self, item3=False):
        if item3:
            self.set_item3(True)
        made = self.make(days=[0, 1, 2, 3, 4, 5, 6])
        self.go(7, 59, 0)
        self.now[0] = at(2026, 11, 11, 12, 0, 0)
        self.runner.tick()
        return made

    def test_the_waiting_line_and_the_page_list_the_missed_times_with_a_count_and_no_content(self):
        made = self.asleep()
        status, out = self.call("/api/waiting")
        self.assertEqual(status, 200)
        (row,) = out["waiting"]
        self.assertEqual((row["kind"], row["routine_id"], row["name"], row["count"], row["slot"], row["too_old"]),
                         ("routine_missed", made["id"], "市集日報", 3, "2026-11-11T08:00", False))
        self.assertNotIn("text", row)
        self.assertEqual(self.call("/api/routines")[1]["waiting"], out["waiting"])

    def test_catch_up_is_one_run_by_you_and_a_second_press_is_409(self):
        made = self.asleep()
        status, out = self.call(f"/api/routines/missed/{made['id']}", "POST", {"action": "run"})
        self.assertEqual((status, out["run"]["state"], out["run"]["by"], out["run"]["why"]), (200, "starting", "you", "catch_up"))
        self.runner.tick()
        self.assertEqual(len(self.daemon.sent), 1)
        status, out = self.call(f"/api/routines/missed/{made['id']}", "POST", {"action": "run"})
        self.assertEqual((status, out["code"]), (409, "routine_gone"))
        self.assertEqual(self.call("/api/waiting")[1]["waiting"], [])

    def test_not_needed_sends_nothing(self):
        made = self.asleep()
        status, out = self.call(f"/api/routines/missed/{made['id']}", "POST", {"action": "dismiss"})
        self.assertEqual((status, out["run"]["state"]), (200, "dismissed"))
        self.runner.tick()
        self.assertEqual(self.daemon.sent, [])

    def test_a_bad_request_is_a_400_and_a_stranger_is_a_404(self):
        made = self.asleep()
        for body in ({}, {"action": "start"}, {"action": "run", "x": 1}, {"action": 1}, [], {"action": None}):
            self.assertEqual(self.call(f"/api/routines/missed/{made['id']}", "POST", body)[0], 400, body)
        self.assertEqual(self.call("/api/routines/missed/r-000000000000", "POST", {"action": "run"})[0], 404)
        self.assertEqual(self.call("/api/routines/missed/nope", "POST", {"action": "run"})[0], 404)
        self.assertEqual(len(self.call("/api/waiting")[1]["waiting"]), 1, "nothing was changed")
        self.assertEqual(self.daemon.sent, [])

    def test_the_routes_need_the_browsers_header_and_a_get_is_not_one(self):
        made = self.asleep()
        status, _ = self.call(f"/api/routines/missed/{made['id']}", "POST", {"action": "run"}, headers={"X-VBear": None})
        self.assertEqual(status, 403)
        self.assertEqual(self.call(f"/api/routines/missed/{made['id']}")[0], 404)
        self.assertEqual(len(self.call("/api/waiting")[1]["waiting"]), 1)

    def test_by_itself_with_item_3_the_list_is_empty_and_the_page_says_who_decided(self):
        self.asleep(item3=True)
        self.assertEqual(self.call("/api/waiting")[1]["waiting"], [])
        (action,) = [a for a in self.call("/api/actions")[1]["actions"] if a["kind"] == "routine_started"]
        self.assertEqual((action["by_text"], action["what"]), ("自己動手第 3 項", "例行工作「市集日報」補做了一次"))

    def test_the_setting_is_taken_beside_the_limit_and_never_written_to_the_config(self):
        path = cfg.state_dir() / "config.json"
        before = path.read_bytes() if path.exists() else None
        status, out = self.call("/api/routines/settings", "POST", {"keep_awake": True})
        self.assertEqual((status, out["settings"]), (200, {"daily_usd": None, "keep_awake": True}))
        self.assertTrue(self.call("/api/routines")[1]["settings"]["keep_awake"])
        self.assertEqual(self.call("/api/routines/settings", "POST", {"daily_usd": 0.75})[0], 200)
        self.assertTrue(self.call("/api/routines")[1]["settings"]["keep_awake"], "the limit's save left it alone")
        self.assertEqual(self.call("/api/routines/settings", "POST", {"keep_awake": "yes"})[0], 400)
        self.assertEqual(self.call("/api/routines/settings", "POST", {"keep_awake": False})[0], 200)
        self.assertEqual(path.read_bytes() if path.exists() else None, before)


if __name__ == "__main__":
    unittest.main()
