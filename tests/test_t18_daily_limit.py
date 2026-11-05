"""v0.12 task 5: the choice of the daily limit on the start-up page (server side).

Over HTTP against a Console's handler (no daemon, no AI tool: this is config only). One request writes the daily limit and
brings the meeting, call, staffing and chat limits down to it, all or nothing; nothing is ever raised.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.test_chat_api import Http
from vbear import config as cfg, meetings, server, staffing
from vbear.index import Store
from vbear.runtime import chat_store as cs

PATH = "/api/setup/daily-limit"


class DailyLimitCase(Http, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-daily-limit-test-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"),
                                             "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = self.token
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.runtime = mock.Mock(binary=lambda: "unused")
        from http.server import ThreadingHTTPServer
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def choose(self, usd):
        return self.call(PATH, "POST", {"daily_usd": usd})

    def everything_validates(self):
        """Every limit block now in config.json is accepted when written back (the rules of the three limit families)."""
        conf = cfg.load()
        for key in ("meeting_limits", "staffing_limits", "chat_limits"):
            if key in conf:
                status, out = self.call("/api/config", "POST", {key: conf[key]})
                self.assertEqual(status, 200, (key, out))
        eff = {"m": meetings.limits_from(cfg.load()), "s": staffing.limits_from(cfg.load()), "c": cs.limits_from(cfg.load())}
        daily = eff["m"]["daily_usd"]
        self.assertLessEqual(eff["m"]["per_call_usd"], eff["m"]["meeting_usd"])
        self.assertLessEqual(eff["m"]["meeting_usd"], daily)
        self.assertLessEqual(eff["s"]["proposal_call_usd"], eff["s"]["total_usd"])
        self.assertLessEqual(eff["s"]["total_usd"], daily)
        self.assertLessEqual(eff["c"]["per_turn_usd"], daily)
        return eff

    def test_the_page_asks_for_the_day_in_force_and_the_three_choices(self):
        status, out = self.call(PATH)
        self.assertEqual((status, out["daily_usd"], out["choices"]), (200, 3.0, [1, 3, 10]), out)
        self.choose(10)
        self.assertEqual(self.call(PATH)[1]["daily_usd"], 10.0)

    def test_choosing_1_brings_the_other_limits_down_and_every_rule_still_holds(self):
        status, out = self.choose(1)
        self.assertEqual(status, 200, out)
        self.assertEqual(out["daily_usd"], 1.0)
        conf = cfg.load()
        self.assertEqual(conf["meeting_limits"], {"per_call_usd": 0.2, "meeting_usd": 1.0, "daily_usd": 1.0})
        self.assertEqual(conf["staffing_limits"], {"proposal_call_usd": 0.5, "total_usd": 1.0})
        self.assertEqual(self.console.store.conf["meeting_limits"]["daily_usd"], 1.0, "the running console sees it at once")
        changed = {c["limit"]: (c["from"], c["to"]) for c in out["changed"]}
        self.assertEqual(changed, {"meeting_usd": (1.5, 1.0), "staffing_total_usd": (2.0, 1.0)})
        eff = self.everything_validates()
        self.assertEqual(eff["c"]["per_turn_usd"], cs.DEFAULT_PER_TURN)

    def test_a_chat_turn_and_a_call_above_the_new_day_are_brought_down_too(self):
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 4}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"per_call_usd": 0.9, "meeting_usd": 5}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"staffing_limits": {"proposal_call_usd": 0.9, "total_usd": 6}})[0], 200)
        status, out = self.choose(1)
        self.assertEqual(status, 200, out)
        conf = cfg.load()
        self.assertEqual(conf["chat_limits"], {"per_turn_usd": 1.0})
        self.assertEqual(conf["meeting_limits"], {"per_call_usd": 0.9, "meeting_usd": 1.0, "daily_usd": 1.0})
        self.assertEqual(conf["staffing_limits"], {"proposal_call_usd": 0.9, "total_usd": 1.0})
        self.everything_validates()

    def test_a_call_limit_above_the_new_meeting_limit_follows_it_down(self):
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"per_call_usd": 1, "meeting_usd": 5}})[0], 200)
        self.assertEqual(self.choose(1)[0], 200)
        self.assertEqual(cfg.load()["meeting_limits"], {"per_call_usd": 1.0, "meeting_usd": 1.0, "daily_usd": 1.0})
        self.assertEqual(self.choose(3)[0], 200)
        self.everything_validates()

    def test_choosing_10_raises_nothing(self):
        self.assertEqual(self.choose(1)[0], 200)
        before = cfg.load()
        status, out = self.choose(10)
        self.assertEqual(status, 200, out)
        after = cfg.load()
        self.assertEqual(after["meeting_limits"], {**before["meeting_limits"], "daily_usd": 10.0})
        self.assertEqual(after["staffing_limits"], before["staffing_limits"])
        self.assertEqual(after.get("chat_limits"), before.get("chat_limits"))
        self.assertEqual(out["changed"], [])
        self.everything_validates()

    def test_choosing_10_from_the_defaults_leaves_the_defaults(self):
        self.assertEqual(self.choose(10)[0], 200)
        eff = self.everything_validates()
        self.assertEqual(eff["m"]["meeting_usd"], meetings.DEFAULT_LIMITS["meeting_usd"])
        self.assertEqual(eff["m"]["per_call_usd"], meetings.DEFAULT_LIMITS["per_call_usd"])
        self.assertEqual(eff["s"]["total_usd"], staffing.DEFAULT_LIMITS["total_usd"])
        self.assertEqual(eff["c"]["per_turn_usd"], cs.DEFAULT_PER_TURN)

    def test_the_default_3_changes_nothing_that_the_defaults_already_hold(self):
        self.assertEqual(self.choose(3)[0], 200)
        eff = self.everything_validates()
        self.assertEqual(eff["m"]["meeting_usd"], meetings.DEFAULT_LIMITS["meeting_usd"])
        self.assertEqual(eff["s"]["total_usd"], staffing.DEFAULT_LIMITS["total_usd"])

    def test_a_broken_request_is_refused_and_changes_nothing(self):
        self.choose(1)
        before = (Path(cfg.config_path()).read_bytes(), dict(self.console.store.conf))
        for bad in (0, -1, 51, 1000, "3", "1", True, False, None, [], {}, [1], float("nan")):
            with self.subTest(bad=bad):
                self.assertEqual(self.choose(bad)[0], 400)
        for raw in (b'{"daily_usd": NaN}', b'{"daily_usd": Infinity}', b'{"daily_usd": 1e999}', b"[]", b"null", b'"x"', b"{",
                    b"{}", b'{"daily_usd": 3, "meeting_usd": 9}', b'{"daily_usd": 3, "daily_usd2": 1}', b""):
            with self.subTest(raw=raw):
                self.assertEqual(self.call(PATH, "POST", raw=raw)[0], 400)
        self.assertEqual(Path(cfg.config_path()).read_bytes(), before[0])
        self.assertEqual(self.console.store.conf, before[1])

    def test_a_broken_config_file_is_refused_and_not_written_over(self):
        self.choose(1)
        Path(cfg.config_path()).write_text("{ not json", encoding="utf-8")
        self.console.store.set_conf(cfg.load())
        status, out = self.choose(3)
        self.assertEqual(status, 409, out)
        self.assertEqual(Path(cfg.config_path()).read_text(encoding="utf-8"), "{ not json")

    def test_it_is_written_whole_or_not_at_all(self):
        self.choose(10)
        before = Path(cfg.config_path()).read_bytes()
        with self.subTest("a rule of one family refuses"):
            with mock.patch.object(staffing, "validate_limits", side_effect=ValueError("synthetic refusal")):
                status, out = self.choose(1)
            self.assertEqual(status, 400, out)
            self.assertEqual(Path(cfg.config_path()).read_bytes(), before)
        with self.subTest("the write itself fails"):
            with mock.patch.object(cfg, "save", side_effect=OSError("synthetic disk failure")):
                status, _ = self.choose(1)
            self.assertGreaterEqual(status, 400)
            self.assertEqual(Path(cfg.config_path()).read_bytes(), before)
            self.assertEqual(self.console.store.conf["meeting_limits"]["daily_usd"], 10.0)
        self.assertEqual(self.choose(1)[0], 200, "and the same request goes through when nothing is wrong")

    def test_it_needs_the_page_header_like_every_write(self):
        status, _ = self.call(PATH, "POST", {"daily_usd": 1}, headers={"X-VBear": ""})
        self.assertEqual(status, 403)
        self.assertEqual(self.call(PATH)[1]["daily_usd"], 3.0)

    def test_lowering_the_day_in_the_settings_brings_staffing_and_chat_down_the_same_way(self):
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 5}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"staffing_limits": {"total_usd": 8}})[0], 200)
        status, out = self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 3}})
        self.assertEqual(status, 200, out)
        conf = cfg.load()
        self.assertEqual(conf["chat_limits"], {"per_turn_usd": 3.0})
        self.assertEqual(conf["staffing_limits"], {"proposal_call_usd": 0.5, "total_usd": 3.0})
        self.everything_validates()

    def test_lowering_the_day_below_the_meeting_limit_in_the_settings_stays_a_plain_error(self):
        status, out = self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 1}})
        self.assertEqual(status, 400, out)
        self.assertIn("每天", out["error"])
        self.assertNotIn("meeting_limits", cfg.load())

    def test_what_the_same_request_writes_for_other_limits_is_not_brought_down(self):
        # an explicit value in the same request is checked as written, not changed behind the person's back
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})[0], 200)
        status, out = self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 3}, "chat_limits": {"per_turn_usd": 4}})
        self.assertEqual(status, 400, out)
        self.assertEqual(cfg.load()["meeting_limits"]["daily_usd"], 10.0)


if __name__ == "__main__":
    unittest.main()
