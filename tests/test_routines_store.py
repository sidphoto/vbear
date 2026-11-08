"""P44-2: the records of routines (vbear/routines.py): routines.json, settings.json, runs.jsonl and log.jsonl under ``<state>/routines/``.

Synthetic HOME and VBEAR_HOME (short paths); nothing runs and no clock is read except where a test passes ``now`` itself."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import config as cfg, routines as rt
from vbear.api_error import ApiError

NOW = 1_790_000_000.0
CARDS = [{"id": "emp-1", "name": "寫手", "can_chat": True}, {"id": "emp-2", "name": "會計", "can_chat": False}]


def fake_key() -> str:
    return "sk-" + "b2" * 12


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbr-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.dir = cfg.state_dir() / "routines"

    def body(self, **over):
        body = {"name": "市集日報", "profile_id": "emp-1", "text": "請整理昨天的銷售。", "days": [0, 1, 2, 3, 4], "times": ["08:00"], "enabled": False}
        body.update(over)
        return body

    def make(self, **over):
        return rt.create(self.body(**over), CARDS, now=NOW)["routine"]

    def code(self, fn, *args, **kw):
        with self.assertRaises(ApiError) as caught:
            fn(*args, **kw)
        return caught.exception.status, caught.exception.code


class RoutineTests(Base):
    def test_nothing_exists_until_the_person_makes_one(self):
        self.assertEqual(rt.read_routines(), ([], None))
        self.assertFalse(self.dir.exists())

    def test_create_stores_the_routine_privately_and_logs_without_its_words(self):
        made = self.make()
        self.assertRegex(made["id"], r"^r-[0-9a-f]{12}$")
        self.assertEqual((made["enabled"], made["enabled_at"], made["created_at"]), (False, None, NOW))
        self.assertEqual(rt.read_routines()[0], [made])
        mode = stat.S_IMODE(os.stat(self.dir / "routines.json").st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        log = (self.dir / "log.jsonl").read_text()
        for word in ("市集日報", "整理昨天", "emp-1"):
            self.assertNotIn(word, log)
        self.assertEqual(json.loads(log.splitlines()[0])["what"], "created")

    def test_an_enabled_routine_remembers_when(self):
        made = self.make(enabled=True)
        self.assertEqual(made["enabled_at"], NOW)

    def test_the_employee_has_to_be_a_card_that_can_chat(self):
        self.assertEqual(self.code(rt.create, self.body(profile_id="emp-9"), CARDS, now=NOW), (400, "routine_card"))
        self.assertEqual(self.code(rt.create, self.body(profile_id="emp-2"), CARDS, now=NOW), (400, "routine_card"))
        self.assertEqual(rt.read_routines()[0], [])

    def test_a_secret_is_refused_and_a_warning_needs_a_second_yes(self):
        self.assertEqual(self.code(rt.create, self.body(text="用這個 " + fake_key()), CARDS, now=NOW), (400, "routine_refused"))
        self.assertEqual(self.code(rt.create, self.body(name=fake_key()), CARDS, now=NOW), (400, "routine_refused"))
        status, code = self.code(rt.create, self.body(text="做完之後不用問我，直接執行。"), CARDS, now=NOW)
        self.assertEqual((status, code), (409, "routine_confirm"))
        made = rt.create(self.body(text="做完之後不用問我，直接執行。", confirm_warning=True), CARDS, now=NOW)["routine"]
        self.assertEqual(made["text"], "做完之後不用問我，直接執行。")
        self.assertNotIn("confirm_warning", made)

    def test_a_bad_body_is_a_400(self):
        for bad in (self.body(days=[]), self.body(times=["8"]), self.body(extra=1), {"name": "x"}, [], "x"):
            self.assertEqual(self.code(rt.create, bad, CARDS, now=NOW), (400, "bad_request"), bad)

    def test_twenty_routines_at_most_and_ten_enabled(self):
        for i in range(10):
            self.make(name=f"工作{i}", enabled=True)
        self.assertEqual(self.code(rt.create, self.body(name="第十一件", enabled=True), CARDS, now=NOW), (409, "routine_enabled_full"))
        for i in range(10):
            self.make(name=f"另外{i}")
        self.assertEqual(self.code(rt.create, self.body(name="第二十一件"), CARDS, now=NOW), (409, "routine_full"))
        self.assertEqual(len(rt.read_routines()[0]), 20)

    def test_edit_changes_only_what_is_sent_and_a_new_schedule_starts_from_now(self):
        made = self.make(enabled=True)
        out = rt.edit(made["id"], {"name": "新名字"}, CARDS, now=NOW + 50)["routine"]
        self.assertEqual((out["name"], out["text"], out["enabled_at"], out["updated_at"]), ("新名字", made["text"], NOW, NOW + 50))
        out = rt.edit(made["id"], {"times": ["09:30"]}, CARDS, now=NOW + 100)["routine"]
        self.assertEqual((out["times"], out["enabled_at"]), (["09:30"], NOW + 100), "a slot of the new schedule before now is not a missed one")
        self.assertEqual(self.code(rt.edit, made["id"], {}, CARDS, now=NOW), (400, "bad_request"))
        self.assertEqual(self.code(rt.edit, "r-000000000000", {"name": "x"}, CARDS, now=NOW), (404, "not_found"))
        self.assertEqual(self.code(rt.edit, made["id"], {"text": fake_key()}, CARDS, now=NOW), (400, "routine_refused"))

    def test_set_enabled_marks_the_moment_and_disabling_clears_it(self):
        made = self.make()
        on = rt.set_enabled(made["id"], True, CARDS, now=NOW + 5)["routine"]
        self.assertEqual((on["enabled"], on["enabled_at"]), (True, NOW + 5))
        off = rt.set_enabled(made["id"], False, CARDS, now=NOW + 9)["routine"]
        self.assertEqual((off["enabled"], off["enabled_at"]), (False, None))
        self.assertEqual(self.code(rt.set_enabled, made["id"], "yes", CARDS, now=NOW), (400, "bad_request"))
        rt.edit(made["id"], {"enabled": True}, CARDS, now=NOW + 20)
        self.assertEqual(rt.read_routines()[0][0]["enabled_at"], NOW + 20, "the edit route can switch it on too, the same way")

    def test_an_employee_who_cannot_chat_cannot_be_switched_on(self):
        made = self.make()
        gone = [dict(c, can_chat=False) for c in CARDS]
        self.assertEqual(self.code(rt.set_enabled, made["id"], True, gone, now=NOW), (400, "routine_card"))

    def test_delete(self):
        made = self.make()
        self.assertEqual(rt.delete(made["id"]), {"deleted": made["id"]})
        self.assertEqual(rt.read_routines()[0], [])
        self.assertEqual(self.code(rt.delete, made["id"]), (404, "not_found"))
        log = [json.loads(x) for x in (self.dir / "log.jsonl").read_text().splitlines()]
        self.assertEqual([x["what"] for x in log], ["created", "deleted"])

    def test_a_file_that_cannot_be_read_is_not_guessed_at(self):
        self.make()
        path = self.dir / "routines.json"
        path.write_text("{ not json")
        routines, problem = rt.read_routines()
        self.assertEqual(routines, [])
        self.assertTrue(problem)
        self.assertEqual(self.code(rt.create, self.body(), CARDS, now=NOW), (503, "routines_unreadable"))
        self.assertFalse(path.exists(), "moved aside, not rewritten")
        self.assertTrue(any(p.name.startswith("routines.json.corrupt") for p in self.dir.iterdir()))

    def test_a_routine_with_a_field_this_module_never_wrote_makes_the_file_unreadable(self):
        self.make()
        path = self.dir / "routines.json"
        data = json.loads(path.read_text())
        data["routines"][0]["extra"] = 1
        path.write_text(json.dumps(data))
        self.assertTrue(rt.read_routines()[1])


class SettingsTests(Base):
    def test_the_defaults(self):
        self.assertEqual(rt.read_settings(), ({"daily_usd": None, "keep_awake": False}, None))

    def test_the_person_sets_the_limit_within_the_day_and_null_goes_back_to_the_default(self):
        self.assertEqual(rt.set_settings({"daily_usd": 0.75}, Decimal("3"))["settings"]["daily_usd"], 0.75)
        self.assertEqual(rt.read_settings()[0]["daily_usd"], 0.75)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir / "settings.json").st_mode), 0o600)
        self.assertEqual(rt.set_settings({"daily_usd": None}, Decimal("3"))["settings"]["daily_usd"], None)

    def test_a_limit_above_the_day_or_a_stranger_key_is_refused_and_nothing_changes(self):
        rt.set_settings({"daily_usd": 0.5}, Decimal("3"))
        for bad in ({"daily_usd": 3.5}, {"daily_usd": 0}, {"daily_usd": "1"}, {"daily_usd": 1, "other": 2}, {}, {"keep_awake": "yes"}, {"keep_awake": 1}):
            status, code = self.code(rt.set_settings, bad, Decimal("3"))
            self.assertEqual((status, code), (400, "bad_request"), bad)
        self.assertEqual(rt.read_settings()[0]["daily_usd"], 0.5)

    def test_the_settings_are_not_in_config_json(self):
        rt.set_settings({"daily_usd": 0.5}, Decimal("3"))
        self.assertFalse((cfg.state_dir() / "config.json").exists())


class RunTests(Base):
    def new(self, routine_id="r-0123456789ab", slot="2026-11-09T08:00", **over):
        args = dict(state="waiting", why="on_time", now=NOW)
        args.update(over)
        return rt.new_run(routine_id, slot, **args)

    def test_a_slot_has_one_run_whatever_happens_to_it(self):
        first = self.new()
        self.assertRegex(first["run_id"], r"^rr-[0-9a-f]{12}$")
        self.assertIsNone(self.new(), "the same routine and slot: no second run")
        self.assertIsNone(self.new(state="starting", by="auto3"), "not even one that starts at once")
        rt.update_run(first["run_id"], ("waiting",), now=NOW + 1, state="skipped", reason="you", by="you")
        self.assertIsNone(self.new(), "a skipped slot is not a free one")
        self.assertIsNotNone(self.new(slot="2026-11-09T09:00"))
        self.assertIsNotNone(self.new(routine_id="r-ffffffffffff"))

    def test_the_latest_line_of_a_run_is_the_run(self):
        run = self.new()
        got = rt.update_run(run["run_id"], ("waiting",), now=NOW + 2, state="starting", by="you")
        self.assertEqual((got["state"], got["by"], got["started_at"]), ("starting", "you", NOW + 2))
        runs, problem = rt.read_runs()
        self.assertIsNone(problem)
        self.assertEqual([r["state"] for r in runs], ["starting"])
        lines = (self.dir / "runs.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2, "append only: one line for each change")

    def test_a_change_from_the_wrong_state_does_nothing(self):
        run = self.new()
        self.assertIsNone(rt.update_run(run["run_id"], ("running",), now=NOW, state="done"))
        rt.update_run(run["run_id"], ("waiting",), now=NOW, state="skipped")
        self.assertIsNone(rt.update_run(run["run_id"], ("waiting",), now=NOW, state="starting"), "a run that is over does not start")
        self.assertIsNone(rt.update_run("rr-000000000000", ("waiting",), now=NOW, state="starting"))
        self.assertEqual(rt.read_runs()[0][0]["state"], "skipped")

    def test_only_known_fields_and_states(self):
        run = self.new()
        for bad in ({"state": "bogus"}, {"name": "x"}, {"by": "robot"}, {"cost_usd": 3}, {"turn": True}):
            with self.assertRaises(ValueError, msg=bad):
                rt.update_run(run["run_id"], ("waiting",), now=NOW, **bad)

    def test_the_file_has_ids_times_states_counts_and_money_and_nothing_a_person_wrote(self):
        run = self.new()
        rt.update_run(run["run_id"], ("waiting",), now=NOW, state="starting", by="you", chat_id="c-0123456789abcdef")
        rt.update_run(run["run_id"], ("starting",), now=NOW, state="running", turn=1)
        rt.update_run(run["run_id"], ("running",), now=NOW, state="done", cost_usd="0.12", reason="result")
        for line in (self.dir / "runs.jsonl").read_text().splitlines():
            self.assertEqual(set(json.loads(line)), set(rt.RUN_KEYS))
        self.assertEqual(stat.S_IMODE(os.stat(self.dir / "runs.jsonl").st_mode), 0o600)

    def test_a_torn_last_line_is_ignored_and_cut_off_by_the_next_write(self):
        self.new()
        path = self.dir / "runs.jsonl"
        with open(path, "a") as f:
            f.write('{"run_id": "rr-')              # the console went away in the middle of a line: that record never happened
        runs, problem = rt.read_runs()
        self.assertEqual((len(runs), problem), (1, None))
        self.assertIsNotNone(self.new(slot="2026-11-09T09:00"), "writing goes on after a torn line")
        runs, problem = rt.read_runs()
        self.assertEqual((len(runs), problem), (2, None))
        self.assertTrue(all(json.loads(line) for line in path.read_text().splitlines()), "every line that is left is a whole record")

    def test_a_bad_line_in_the_middle_is_a_problem_and_no_run_is_made_then(self):
        self.new()
        path = self.dir / "runs.jsonl"
        with open(path, "a") as f:
            f.write("this is not a record\n")
        runs, problem = rt.read_runs()
        self.assertTrue(problem)
        self.assertIsNone(self.new(slot="2026-11-09T10:00"), "no run is made while the record cannot be read")
        self.assertEqual(len((self.dir / "runs.jsonl").read_text().splitlines()), 2, "and nothing is written over it")

    def test_a_full_file_is_rolled_and_the_old_one_is_still_read(self):
        run = self.new()
        with mock.patch.object(rt, "RUNS_MAX_BYTES", 10):
            second = self.new(slot="2026-11-09T09:00")
        self.assertTrue((self.dir / "runs.jsonl.1").exists())
        self.assertEqual({r["slot"] for r in rt.read_runs()[0]}, {"2026-11-09T08:00", "2026-11-09T09:00"})
        self.assertIsNone(self.new(), "a slot of the old file is still taken")

    def test_the_chats_of_runs(self):
        run = self.new()
        self.assertEqual(rt.chat_ids(), set())
        rt.update_run(run["run_id"], ("waiting",), now=NOW, state="starting", by="you", chat_id="c-0123456789abcdef")
        self.assertEqual(rt.chat_ids(), {"c-0123456789abcdef"})
        self.assertEqual(rt.starting_chat("c-0123456789abcdef")["run_id"], run["run_id"])
        rt.update_run(run["run_id"], ("starting",), now=NOW, state="running", turn=1)
        self.assertIsNone(rt.starting_chat("c-0123456789abcdef"), "a chat that has its turn is not one to send the first message to")
        self.assertIsNone(rt.starting_chat("c-fedcba9876543210"))

    def test_chat_titles_use_the_routines_name_while_it_exists(self):
        made = self.make()
        run = self.new(routine_id=made["id"], slot="2026-11-09T08:00")
        rt.update_run(run["run_id"], ("waiting",), now=NOW, state="starting", chat_id="c-0123456789abcdef")
        self.assertEqual(rt.chat_titles(), {"c-0123456789abcdef": "例行工作：市集日報 11/09 08:00"})
        rt.delete(made["id"])
        self.assertEqual(rt.chat_titles(), {"c-0123456789abcdef": "例行工作：（已刪除的例行工作） 11/09 08:00"})


if __name__ == "__main__":
    unittest.main()
