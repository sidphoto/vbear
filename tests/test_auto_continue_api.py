"""P44-4: what the console shows and wires for the countdown and item 5: the line over every page (/api/waiting), 「AI 自己做了什麼」
(/api/actions), the dispatch page's countdown (/api/dispatch/<id>), and the routine runner the console builds (it carries item 5's module,
whose press is the dispatch runner's ``resume_dispatch(did, by="vbear")``). Over a real loopback server and the dispatch tests' fake daemon;
the clock is a hand-moved one; no CLI runs and nothing leaves the machine."""
from __future__ import annotations

import json
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.test_auto_continue import AutoBase, HOUR, NOON, ON, TAIPEI, at
from vbear import auto_continue, config as cfg, routine_runner as rrun, server
from vbear.index import Store

TOKEN = "synthetic-test-token"


class ApiBase(AutoBase):
    def setUp(self):
        super().setUp()
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = TOKEN
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = self.service
        c._dispatcher = self.dispatcher
        c._dispatch_runner = self.drunner
        c.meeting_runner = lambda: types.SimpleNamespace(ledger=lambda conf: self.ledger())
        self.rrunner = rrun.RoutineRunner(chats=lambda: self.service, ledger=self.ledger, conf=lambda: c.store.conf,
                                         clock=lambda: self.now[0], tz=TAIPEI, auto_continue=self.auto)
        self.addCleanup(self.rrunner.close)
        c._routine_runner = self.rrunner
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, method="GET", body=None):
        hdr = {"Authorization": f"Bearer {TOKEN}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}",
               "Content-Type": "application/json"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")


class WaitingLineTests(ApiBase):
    def test_a_paused_dispatch_is_a_row_with_a_name_a_time_and_words_only(self):
        did = self.paused(until=NOON + 2 * HOUR)
        status, out = self.call("/api/waiting")
        self.assertEqual(status, 200, out)
        rows = [r for r in out["waiting"] if r["kind"] == "dispatch_resume"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["dispatch_id"], rows[0]["name"], rows[0]["state"]), (did, self.rec(did)["plan"]["title"], "counting"))
        self.assertTrue(rows[0]["text"].startswith("還有 2 小時可以繼續（"), rows[0]["text"])
        self.assertEqual(set(rows[0]), {"kind", "dispatch_id", "name", "reason", "state", "until", "text"})

    def test_the_routines_own_rows_and_these_come_together_and_an_empty_line_is_an_empty_list(self):
        self.assertEqual(self.call("/api/waiting"), (200, {"ok": True, "waiting": []}))
        self.paused(until=NOON + HOUR)
        status, out = self.call("/api/waiting")
        self.assertEqual([r["kind"] for r in out["waiting"]], ["dispatch_resume"])

    def test_reading_the_line_presses_nothing_and_writes_nothing(self):
        did = self.paused(until=NOON - 10 * HOUR)
        bytes_before = self.config_bytes()
        self.call("/api/waiting")
        self.assertEqual((self.calls, self.state(did), self.config_bytes()), ([], "paused", bytes_before))


class ActionsTests(ApiBase):
    def test_a_press_of_item_5_is_listed_as_item_5_and_the_persons_own_press_is_not(self):
        auto_did = self.paused(until=NOON + HOUR)
        by_hand = self.paused(until=NOON + HOUR)
        self.now[0] = NOON + HOUR + 120
        self.dispatcher.resume(by_hand)
        self.auto.tick()
        self.assertEqual(self.state(auto_did), "running")
        status, out = self.call("/api/actions")
        self.assertEqual(status, 200, out)
        rows = {r["dispatch_id"]: r for r in out["actions"] if r["kind"] == "continued"}
        self.assertEqual((rows[auto_did]["by"], rows[auto_did]["by_text"]), ("auto5", "自己動手第 5 項"))
        self.assertIn("自己按了「繼續」", rows[auto_did]["what"])
        self.assertEqual((rows[by_hand]["by"], rows[by_hand]["by_text"]), ("you", "你按的"))

    def test_the_dispatch_page_shows_the_countdown_beside_the_sentence(self):
        did = self.paused(until=NOON + 90 * 60)
        status, out = self.call(f"/api/dispatch/{did}")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["pause"]["countdown"]["state"], "counting")
        self.assertTrue(out["pause"]["countdown"]["text"].startswith("還有 1 小時 30 分可以繼續（"), out["pause"]["countdown"])


class TheConsoleWiresItTests(ApiBase):
    def test_the_routine_runner_the_console_builds_carries_item_5_and_its_press_is_the_dispatch_runners_as_vbear(self):
        c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = self.service
        c._dispatcher = self.dispatcher
        c._dispatch_runner = self.drunner
        c.meeting_runner = lambda: types.SimpleNamespace(ledger=lambda conf: self.ledger())
        runner = c.routine_runner()
        self.addCleanup(runner.close)
        self.assertIsInstance(runner.auto_continue, auto_continue.AutoContinue)
        did = self.paused(until=NOON + HOUR)
        seq = next(e["seq"] for e in self.rec(did)["events"] if e["kind"] == "paused")
        runner.auto_continue.resume(did, seq)
        last = self.rec(did)["events"][-1]
        self.assertEqual((last["kind"], last["by"], self.state(did)), ("continued", "vbear", "running"))

    def test_item_5_in_the_console_looks_at_the_consoles_config(self):
        c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = self.service
        c.meeting_runner = lambda: types.SimpleNamespace(ledger=lambda conf: self.ledger())
        runner = c.routine_runner()
        self.addCleanup(runner.close)
        self.assertFalse(runner.auto_continue._on(), "the default config has it off")
        c.store.set_conf({**cfg.load(), "autonomy": dict(ON["autonomy"])})
        self.assertTrue(runner.auto_continue._on())


if __name__ == "__main__":
    unittest.main()
