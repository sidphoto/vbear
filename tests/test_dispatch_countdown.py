"""P44-4: the countdown a paused dispatch or group shows (ADR 0010 point 6): when the day's money or the plan is usable again, in words.

Seam: ``countdown.words(reason, until, now, tz)``, a pure function; the clocks and the zone are given, nothing here waits."""
from __future__ import annotations

import datetime
import unittest
from zoneinfo import ZoneInfo

from tests.group_fixtures import GroupBase
from tests.test_dispatch_runner import RunnerBase
from vbear import countdown, dispatch, groups

TAIPEI = ZoneInfo("Asia/Taipei")


def at(month, day, hour, minute, second=0):
    return datetime.datetime(2026, month, day, hour, minute, second, tzinfo=TAIPEI).timestamp()


class WordsTests(unittest.TestCase):
    def test_a_known_time_in_the_future_counts_down_in_hours_and_minutes(self):
        got = countdown.words("daily_limit", at(11, 9, 0, 0), at(11, 8, 21, 55), TAIPEI)
        self.assertEqual(got, {"state": "counting", "until": at(11, 9, 0, 0), "text": "還有 2 小時 5 分可以繼續（11/09 00:00）"})

    def test_the_minutes_are_rounded_up_so_the_line_never_says_zero_before_the_time(self):
        got = countdown.words("daily_limit", at(11, 9, 0, 0), at(11, 8, 21, 55, 30), TAIPEI)
        self.assertEqual(got["text"], "還有 2 小時 5 分可以繼續（11/09 00:00）")
        got = countdown.words("plan_limit", at(11, 9, 0, 0), at(11, 8, 23, 59, 59), TAIPEI)
        self.assertEqual(got["text"], "還有 1 分可以繼續（11/09 00:00）")

    def test_whole_hours_and_under_an_hour(self):
        self.assertEqual(countdown.words("daily_limit", at(11, 9, 0, 0), at(11, 8, 23, 0), TAIPEI)["text"],
                         "還有 1 小時可以繼續（11/09 00:00）")
        self.assertEqual(countdown.words("plan_limit", at(11, 9, 0, 0), at(11, 8, 23, 30), TAIPEI)["text"],
                         "還有 30 分可以繼續（11/09 00:00）")

    def test_at_or_after_the_time_it_says_it_can_go_on(self):
        for now in (at(11, 9, 0, 0), at(11, 9, 3, 0), at(11, 12, 0, 0)):
            got = countdown.words("daily_limit", at(11, 9, 0, 0), now, TAIPEI)
            self.assertEqual((got["state"], got["text"]), ("ready", "可以繼續了（11/09 00:00 恢復）"), now)

    def test_a_time_the_ai_tool_did_not_give_is_said_so_and_has_no_countdown(self):
        got = countdown.words("plan_limit", None, at(11, 8, 12, 0), TAIPEI)
        self.assertEqual(got, {"state": "unknown", "until": None, "text": "AI 工具沒說什麼時候恢復"})

    def test_only_the_two_limits_count_down(self):
        for reason in ("uncertain", "interrupted", "runner_error", "turn_error", "turn_stopped", "busy", "limit", "spend_unknown",
                       "violation", "damaged", None, 5):
            self.assertIsNone(countdown.words(reason, at(11, 9, 0, 0), at(11, 8, 12, 0), TAIPEI), reason)

    def test_a_time_that_is_not_a_time_is_unknown(self):
        for bad in (True, "x", float("nan"), -5, 0):
            self.assertEqual(countdown.words("daily_limit", bad, at(11, 8, 12, 0), TAIPEI)["state"], "unknown", bad)

    def test_the_zone_is_the_one_given_so_the_text_does_not_depend_on_the_machine(self):
        until = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
        now = until - 3600
        self.assertIn("（11/08 20:00）", countdown.words("daily_limit", until, now, TAIPEI)["text"])
        self.assertIn("（11/08 07:00）", countdown.words("daily_limit", until, now, ZoneInfo("America/New_York"))["text"])


class DispatchViewTests(RunnerBase):
    """A paused dispatch's page gets the countdown beside the sentence; ``PAUSE_TEXT`` and the record are as they were."""

    def pause(self, reason, until):
        did = self.running()

        def change(rec):
            rec["state"], rec["pause"] = "paused", {"reason": reason, "until": until}
            self.dispatcher.add_event(rec, "paused", "vbear", reason=reason, **({"until": until} if until is not None else {}))
        self.dispatcher.mutate(did, change)
        return did

    def test_a_pause_for_the_day_counts_down_to_its_time(self):
        until = self.now[0] + 2 * 3600 + 5 * 60
        self.dispatcher.clock = lambda: self.now[0]
        did = self.pause("daily_limit", until)
        pause = self.dispatcher.get(did)["pause"]
        self.assertEqual((pause["reason"], pause["until"]), ("daily_limit", until))
        self.assertEqual(pause["countdown"]["state"], "counting")
        self.assertTrue(pause["countdown"]["text"].startswith("還有 2 小時 5 分可以繼續（"), pause["countdown"])
        self.assertIn("明天 0:00", pause["text"], "the sentence is the one it was")

    def test_a_plan_limit_without_a_time_says_the_tool_did_not_say(self):
        did = self.pause("plan_limit", None)
        pause = self.dispatcher.get(did)["pause"]
        self.assertEqual(pause["countdown"], {"state": "unknown", "until": None, "text": "AI 工具沒說什麼時候恢復"})

    def test_a_pause_that_needs_a_look_has_no_countdown(self):
        for reason in ("uncertain", "interrupted", "runner_error", "turn_error", "busy"):
            did = self.pause(reason, None)
            self.assertIsNone(self.dispatcher.get(did)["pause"]["countdown"], reason)
            self.dispatcher.stop(did)

    def test_a_dispatch_that_is_not_paused_has_no_pause_and_the_record_has_no_new_field(self):
        did = self.running()
        self.assertIsNone(self.dispatcher.get(did)["pause"])
        self.assertEqual(set(self.rec(did)["pause"] or {}), set())
        did = self.pause("daily_limit", self.now[0] + 60)
        self.assertEqual(set(self.rec(did)["pause"]), {"reason", "until"})
        self.assertEqual(set(self.rec(did)["events"][-1]) - {"seq", "at", "kind", "by"}, {"reason", "until"})


class GroupViewTests(GroupBase):
    def paused(self, until):
        gid = self.make_group()["group"]["id"]
        self.groups.say(gid, {"text": "大家好", "to": "all"})
        with groups.log_tx(gid) as tx:
            tx.append("paused", round=1, reason="daily_limit", until=until)
        return gid

    def test_a_round_paused_for_the_day_counts_down_and_the_sentence_is_the_same(self):
        until = self.now[0] + 7200
        gid = self.paused(until)
        pause = self.groups.get(gid)["round"]["pause"]
        self.assertEqual(pause["countdown"]["state"], "counting")
        self.assertTrue(pause["countdown"]["text"].startswith("還有 2 小時可以繼續（"), pause["countdown"])
        self.assertIn("明天 0:00", pause["text"])

    def test_after_the_time_it_says_it_can_go_on_and_nothing_goes_on_by_itself(self):
        until = self.now[0] + 60
        gid = self.paused(until)
        self.now[0] = until + 3600
        view = self.groups.get(gid)
        self.assertEqual(view["round"]["pause"]["countdown"]["state"], "ready")
        self.assertEqual(self.runner.tick(), {}, "the group runner does not press 繼續")
        self.assertEqual(self.groups.get(gid)["round"]["state"], "paused")


if __name__ == "__main__":
    unittest.main()
