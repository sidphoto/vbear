"""P44-2: the routine endpoints over a real loopback server: the person's presses (make, change, switch on and off, delete, start now,
answer a reminder, set the daily limit) and the reads the pages use (/api/routines, /api/waiting, /api/actions, the chat list's titles).
The chat service is the real one over the dispatch tests' fake daemon; the clock is a hand-moved one; no CLI runs and nothing leaves the machine."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.routine_fixtures import HEAD, NY, MONDAY_0759, at
from tests.test_dispatch_runner import FakeDaemon
from vbear import agent_profiles as ap, chat_service, config as cfg, routine_runner as rrun, routines as rt, server
from vbear.index import Store

TOKEN = "synthetic-test-token"


def fake_key() -> str:
    return "sk-" + "c3" * 12


class RoutinesApiBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbra-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        card = lambda name, position, tool="claude", **kw: ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}, **kw})["id"]
        self.writer, self.accountant = card("文案小編", "social"), card("會計師", "accountant")
        self.off = card("停用員工", "social", enabled=False)
        self.now = [MONDAY_0759]
        # The routine store stamps created_at/enabled_at with the wall clock; tie only time.time to the test clock so these
        # tests do not depend on today's date (monotonic and sleep stay real).
        import time as real_time
        import types as _types
        from unittest import mock as _mock
        from vbear import routines as _routines
        _clock = _types.SimpleNamespace(time=lambda: self.now[0], monotonic=real_time.monotonic, sleep=real_time.sleep)
        _patch = _mock.patch.object(_routines, "time", _clock)
        _patch.start()
        self.addCleanup(_patch.stop)
        self.daemon = FakeDaemon(clock=lambda: self.now[0])
        self.service = chat_service.ChatService(self.daemon, claude=lambda: (sys.executable, "2.1.318", ""), codex=lambda: dict(HEAD),
                                                codex_binary=lambda: (sys.executable, "0.163.0"))
        self.service.restart_pause = 0
        self.lamp = ["green"]
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = TOKEN
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = self.service
        c.meeting_runner = lambda: types.SimpleNamespace(ledger=lambda conf: {"lamp": self.lamp[0], "daily_usd": "3", "spent_usd": "0.50"})
        self.runner = rrun.RoutineRunner(chats=lambda: self.service, ledger=lambda: c.meeting_runner().ledger(None),
                                         conf=lambda: c.store.conf, clock=lambda: self.now[0], tz=NY)
        self.addCleanup(self.runner.close)
        c._routine_runner = self.runner
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, method="GET", body=None, headers=None, raw=None):
        hdr = {"Authorization": f"Bearer {TOKEN}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}",
               "Content-Type": "application/json"}
        hdr.update(headers or {})
        hdr = {k: v for k, v in hdr.items() if v is not None}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def body(self, **over):
        body = {"name": "市集日報", "profile_id": self.writer, "text": "請整理昨天的銷售。", "days": [0, 1, 2, 3, 4], "times": ["08:00"], "enabled": True}
        body.update(over)
        return body

    def make(self, **over) -> dict:
        status, out = self.call("/api/routines", "POST", self.body(**over))
        self.assertEqual(status, 201, out)
        return out["routine"]

    def set_item3(self, on=True):
        status, out = self.call("/api/settings/autonomy", "POST",
                                {"create_cards": False, "dispatch": False, "routines": on, "auto_continue": False})
        self.assertEqual(status, 200, out)

    def go(self, h, m, s=0):
        self.now[0] = at(2026, 11, 9, h, m, s)
        return self.runner.tick()


class WriteTests(RoutinesApiBase):
    def test_make_change_switch_and_delete(self):
        made = self.make(enabled=False)
        self.assertRegex(made["id"], r"^r-[0-9a-f]{12}$")
        self.assertEqual((made["enabled"], made["enabled_at"]), (False, None))
        status, out = self.call(f"/api/routines/{made['id']}", "POST", {"name": "新名字", "times": ["09:00", "13:00"]})
        self.assertEqual((status, out["routine"]["name"], out["routine"]["times"]), (200, "新名字", ["09:00", "13:00"]))
        status, out = self.call(f"/api/routines/{made['id']}", "POST", {"enabled": True})
        self.assertEqual((status, out["routine"]["enabled"]), (200, True))
        self.assertIsNotNone(out["routine"]["enabled_at"])
        status, out = self.call(f"/api/routines/{made['id']}/delete", "POST", {})
        self.assertEqual((status, out["deleted"]), (200, made["id"]))
        self.assertEqual(self.call("/api/routines")[1]["routines"], [])

    def test_a_bad_request_is_a_400_with_a_code_and_changes_nothing(self):
        for body in (self.body(days=[]), self.body(times=["8:00"]), self.body(extra=1), {"name": "x"}, self.body(profile_id="nope"),
                     self.body(profile_id=self.off), self.body(name="")):
            status, out = self.call("/api/routines", "POST", body)
            self.assertEqual(status, 400, (body, out))
            self.assertIn("error", out)
        for raw in (b"[]", b"not json", b'"x"'):
            self.assertEqual(self.call("/api/routines", "POST", raw=raw)[0], 400, raw)
        self.assertEqual(rt.read_routines()[0], [])

    def test_a_secret_is_a_400_and_an_order_to_skip_asking_needs_the_second_yes(self):
        status, out = self.call("/api/routines", "POST", self.body(text="用 " + fake_key()))
        self.assertEqual((status, out["code"]), (400, "routine_refused"))
        status, out = self.call("/api/routines", "POST", self.body(text="做完不用問我，直接執行。"))
        self.assertEqual((status, out["code"]), (409, "routine_confirm"))
        self.assertTrue(out["warn_text"])
        status, out = self.call("/api/routines", "POST", self.body(text="做完不用問我，直接執行。", confirm_warning=True))
        self.assertEqual(status, 201, out)

    def test_actions_that_need_no_body_refuse_one(self):
        made = self.make()
        self.assertEqual(self.call(f"/api/routines/{made['id']}/delete", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call(f"/api/routines/{made['id']}/start", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call("/api/routines/r-000000000000/delete", "POST", {})[0], 404)
        self.assertEqual(self.call("/api/routines/not-an-id", "POST", {"name": "x"})[0], 404)

    def test_every_write_needs_the_header(self):
        for path in ("/api/routines", "/api/routines/settings", "/api/routines/r-000000000000", "/api/routines/waiting/rr-000000000000"):
            status, _ = self.call(path, "POST", {}, headers={"X-VBear": None})
            self.assertEqual(status, 403, path)
        self.assertEqual(rt.read_routines()[0], [])

    def test_the_reads_need_the_token(self):
        for path in ("/api/routines", "/api/waiting"):
            self.assertEqual(self.call(path, headers={"Authorization": "Bearer wrong"})[0], 401, path)

    def test_the_employee_must_be_able_to_chat(self):
        status, out = self.call("/api/routines", "POST", self.body(profile_id=self.off))
        self.assertEqual((status, out["code"]), (400, "routine_card"))

    def test_nothing_here_writes_config_json(self):
        before = cfg.config_path().read_bytes() if cfg.config_path().exists() else None
        made = self.make()
        self.call(f"/api/routines/{made['id']}", "POST", {"name": "x"})
        self.call("/api/routines/settings", "POST", {"daily_usd": 1})
        self.call(f"/api/routines/{made['id']}/start", "POST", {})
        self.call(f"/api/routines/{made['id']}/delete", "POST", {})
        self.assertEqual(cfg.config_path().read_bytes() if cfg.config_path().exists() else None, before)


class ReadTests(RoutinesApiBase):
    def test_the_page_gets_the_routine_its_next_time_the_money_and_the_settings(self):
        made = self.make()
        status, out = self.call("/api/routines")
        self.assertEqual(status, 200, out)
        (row,) = out["routines"]
        self.assertEqual((row["id"], row["name"], row["profile_name"], row["can_chat"]), (made["id"], "市集日報", "文案小編", True))
        self.assertEqual(row["next"]["slot"], "2026-11-09T08:00")
        self.assertEqual(row["per_run_usd"], "0.50")
        self.assertEqual(row["runs"], [])
        self.assertEqual(out["settings"], {"daily_usd": "1.50", "daily_usd_set": None, "default_usd": "1.50", "keep_awake": False, "problem": None})
        self.assertEqual(out["today"]["routine_limit_usd"], "1.50")
        self.assertEqual((out["today"]["day_usd"], out["today"]["day_left_usd"], out["today"]["routine_spent_usd"]), ("3.00", "2.50", "0.00"))
        self.assertEqual(out["autonomy"], {"routines": False})
        self.assertEqual((out["readable"], out["waiting"]), (True, []))

    def test_a_routine_that_is_off_has_no_next_time(self):
        self.make(enabled=False)
        self.assertIsNone(self.call("/api/routines")[1]["routines"][0]["next"])

    def test_the_last_ten_runs_come_newest_first_with_who_decided(self):
        made = self.make(days=[0, 1, 2, 3, 4, 5, 6], times=["08:00", "13:00", "18:00"])
        for day in range(9, 13):
            for h in (8, 13, 18):
                self.now[0] = at(2026, 11, day, h, 0, 10)
                self.runner.tick()
        runs = self.call("/api/routines")[1]["routines"][0]["runs"]
        self.assertEqual(len(runs), 10)
        self.assertEqual(runs[0]["slot"], "2026-11-12T18:00")
        self.assertEqual({r["state"] for r in runs}, {"waiting", "missed"})

    def test_a_file_that_cannot_be_read_is_said_and_not_guessed(self):
        self.make()
        (cfg.state_dir() / "routines" / "routines.json").write_text("{ no")
        status, out = self.call("/api/routines")
        self.assertEqual((status, out["readable"], out["routines"]), (200, False, []))
        self.assertTrue(out["problem"])
        self.assertEqual(self.call("/api/routines", "POST", self.body())[1]["code"], "routines_unreadable")


class ReminderTests(RoutinesApiBase):
    def test_a_reminder_is_listed_without_its_content_and_pressing_start_runs_it_once(self):
        made = self.make()
        self.go(7, 59, 30)
        self.go(8, 0, 10)
        status, out = self.call("/api/waiting")
        self.assertEqual(status, 200)
        (row,) = out["waiting"]
        self.assertEqual((row["kind"], row["name"], row["routine_id"], row["slot"]), ("routine_due", "市集日報", made["id"], "2026-11-09T08:00"))
        self.assertNotIn("請整理", json.dumps(out, ensure_ascii=False), "the line over every page names the routine and nothing of what it says")
        self.assertEqual(self.daemon.sent, [])
        status, out = self.call(f"/api/routines/waiting/{row['run_id']}", "POST", {"action": "start"})
        self.assertEqual((status, out["run"]["state"], out["run"]["by"]), (200, "starting", "you"))
        self.assertEqual(self.call(f"/api/routines/waiting/{row['run_id']}", "POST", {"action": "start"})[0], 409)
        self.runner.tick()
        self.assertEqual(len(self.daemon.sent), 1)
        self.assertEqual(self.call("/api/waiting")[1]["waiting"], [])
        listed = self.call("/api/routines")[1]["routines"][0]["runs"]
        self.assertEqual((listed[0]["state"], listed[0]["by_text"]), ("running", "你按的"))

    def test_skip_and_a_bad_action(self):
        self.make()
        self.go(8, 0, 10)
        (row,) = self.call("/api/waiting")[1]["waiting"]
        for body in ({"action": "run"}, {}, {"action": "skip", "x": 1}, {"action": 5}):
            self.assertEqual(self.call(f"/api/routines/waiting/{row['run_id']}", "POST", body)[0], 400, body)
        self.assertEqual(self.call(f"/api/routines/waiting/{row['run_id']}", "POST", {"action": "skip"})[1]["run"]["state"], "skipped")
        self.assertEqual(self.daemon.sent, [])

    def test_start_now_is_accepted_and_the_second_press_of_the_minute_is_a_409(self):
        made = self.make(enabled=False)
        self.now[0] = at(2026, 11, 9, 14, 7, 20)
        status, out = self.call(f"/api/routines/{made['id']}/start", "POST", {})
        self.assertEqual((status, out["run"]["why"], out["run"]["by"]), (202, "now", "you"))
        self.assertEqual(self.call(f"/api/routines/{made['id']}/start", "POST", {})[0], 409)


class ItemThreeThroughTheRoutesTests(RoutinesApiBase):
    def test_ticking_the_item_in_the_settings_is_what_makes_a_routine_start_by_itself(self):
        self.make()
        self.go(7, 59, 55)
        self.go(8, 0, 10)
        self.assertEqual(self.daemon.sent, [])
        self.now[0] = at(2026, 11, 10, 7, 59, 0)
        self.runner.tick()
        self.set_item3(True)
        self.go_next_day(8, 0, 10)
        self.assertEqual(len(self.daemon.sent), 1)
        rows = self.call("/api/actions")[1]["actions"]
        (mine,) = [r for r in rows if r["kind"] == "routine_started"]
        self.assertEqual((mine["by"], mine["by_text"], mine["dispatch_id"], mine["can_stop"]), ("auto3", "自己動手第 3 項", None, False))
        self.assertIn("市集日報", mine["what"])
        self.assertTrue(mine["chat_id"])

    def go_next_day(self, h, m, s):
        self.now[0] = at(2026, 11, 10, h, m, s)
        return self.runner.tick()

    def test_a_routine_chat_is_listed_with_its_title_and_the_person_can_go_on_in_it(self):
        self.set_item3(True)
        self.make()
        self.go(7, 59, 55)
        self.go(8, 0, 10)
        (run,) = rt.read_runs()[0]
        chats = self.call("/api/chats")[1]["chats"]
        (mine,) = [c for c in chats if c["id"] == run["chat_id"]]
        self.assertEqual(mine["routine_title"], "例行工作：市集日報 11/09 08:00")
        self.assertEqual(self.call(f"/api/chats/{run['chat_id']}")[1]["routine_title"], "例行工作：市集日報 11/09 08:00")
        self.daemon.finish(run["chat_id"], reply="好了")
        self.runner.tick()
        status, out = self.call(f"/api/chats/{run['chat_id']}/messages", "POST", {"text": "再補一句"})
        self.assertEqual(status, 202, out)

    def test_there_is_no_route_that_sends_for_a_routine(self):
        self.set_item3(True)
        self.make()
        self.go(7, 59, 55)
        self.go(8, 0, 10)
        self.assertEqual(len(self.daemon.sent), 1)
        for path in ("/api/routines/send", "/api/routines/r-000000000000/send"):
            self.assertEqual(self.call(path, "POST", {"text": "x"})[0], 404, path)


class SettingsTests(RoutinesApiBase):
    def test_the_limit_is_set_within_the_day_and_null_goes_back(self):
        status, out = self.call("/api/routines/settings", "POST", {"daily_usd": 0.75})
        self.assertEqual((status, out["settings"]["daily_usd"]), (200, 0.75))
        self.assertEqual(self.call("/api/routines")[1]["settings"]["daily_usd"], "0.75")
        self.assertEqual(self.call("/api/routines/settings", "POST", {"daily_usd": None})[0], 200)
        self.assertEqual(self.call("/api/routines")[1]["settings"]["daily_usd"], "1.50")

    def test_above_the_days_limit_or_another_key_is_a_400(self):
        for body in ({"daily_usd": 3.5}, {"daily_usd": 0}, {"daily_usd": "1"}, {"keep_awake": "yes"}, {"keep_awake": 1}, {"daily_usd": 1, "x": 1}, {}):
            self.assertEqual(self.call("/api/routines/settings", "POST", body)[0], 400, body)
        self.assertFalse((cfg.state_dir() / "routines" / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
