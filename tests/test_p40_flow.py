"""P40-5: the whole way through the console's HTTP API, in the order the pages go: the preview, the chief of staff's call (a fake
one), the proposal card, the confirmation (with a change of the person's), the steps sent through the chat service to a fake
runtime daemon until the dispatch is done, and 「AI 自己做了什麼」; then the same with a pause at the daily limit, the person's
stop, taking back an employee, and with both 「自己動手」 items ticked.

Seams: the console's HTTP routes (/api/chief*, /api/dispatch*, /api/actions, /api/settings/autonomy) over a real loopback server;
what the chief of staff says is a fake call and what an employee does is the fake daemon of tests/test_dispatch_runner.py (chats
are real records in the state folder). No CLI runs and nothing leaves the machine; HOME and VBEAR_HOME are synthetic and short."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.test_dispatch import EVIDENCE, VERSION
from tests.test_dispatch_runner import FakeDaemon, HEAD, three_steps
from vbear import agent_profiles as ap, chat_service, chief_runner as cr, config as cfg, dispatch_runner as dr, meeting_runner as mr
from vbear import server, staffing_runner as sr, tasks
from vbear.index import Store
from vbear.runtime import chat_store as cs

TOKEN = "synthetic-test-token"


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbf-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.answer = three_steps()
        self.lamp = ["green"]
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = TOKEN
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.meetings = mr.MeetingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.staffing = sr.StaffingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.chief = cr.ChiefRunner(provider=lambda e: ("unused", VERSION), call=self.fake, on_proposal=c._on_proposal)
        c.chief_tools = lambda: ("claude",)
        c._chat_busy = lambda chat_id: False
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.chief.wait, 5)
        card = lambda name, position: ap.save_profile(None, {"name": name, "position": position, "model": {"tool": "claude"}})["id"]
        self.ceo, self.writer = card("虛構CEO", "planner"), card("文案小編", "social")
        base = cfg.state_dir()
        chat = cs.create(base, self.ceo, now=time.time())
        log = cs.ChatLog(base, chat["id"])
        log.append("user_message", {"turn": 1, "text": "我想在週末市集擺攤賣手工皂，預算三千"}, now=time.time())
        log.append("reply", {"turn": 1, "text": "好，先問你預算", "truncated": False}, now=time.time())
        log.close()
        self.chat_id = chat["id"]
        # the steps go through the real chat service to a fake runtime daemon; the runner is ticked by hand
        self.daemon = FakeDaemon()
        self.service = chat_service.ChatService(self.daemon, claude=lambda: (sys.executable, "2.1.318", ""),
                                                codex=lambda: dict(HEAD), codex_binary=lambda: (sys.executable, "0.163.0"))
        self.service.restart_pause = 0
        self.drunner = dr.DispatchRunner(c.dispatcher(), chats=lambda: self.service,
                                         ledger=lambda: {"lamp": self.lamp[0], "daily_usd": "3", "spent_usd": "0.5"})
        c.dispatcher().control = self.drunner
        self.addCleanup(self.drunner.close)

    def fake(self, spec, cancel):
        return mr.CallResult(copy.deepcopy(self.answer), dict(EVIDENCE), Decimal("0.02"))

    def call(self, path, method="GET", body=None, headers=None):
        hdr = {"Authorization": f"Bearer {TOKEN}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        hdr.update(headers or {})
        hdr = {k: v for k, v in hdr.items() if v is not None}
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, method=method, headers=hdr,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def ok(self, path, method="GET", body=None, status=200):
        got, out = self.call(path, method, body)
        self.assertEqual(got, status, out)
        return out

    def config_bytes(self):
        path = cfg.state_dir() / "config.json"
        return path.read_bytes() if path.exists() else None

    def ask(self):
        """The page's way: a preview, then the call from it; the dispatch the proposal became."""
        preview = self.ok(f"/api/chief/preview?chat_id={self.chat_id}")
        self.assertTrue(preview["ok"], preview)
        started = self.ok("/api/chief", "POST", {"preview_id": preview["preview_id"], "note": "週末就要"}, 202)
        self.console.chief.wait(10)
        chief_view = self.ok(f"/api/chief/{started['chief_id']}")
        self.assertEqual(chief_view["status"], "ready", chief_view)
        return preview, chief_view, chief_view["dispatch_id"]

    def tick_until(self, did, want, limit=40):
        """Tick the runner, ending each open turn the way an employee would, until the dispatch is in the state wanted."""
        for _ in range(limit):
            view = self.ok(f"/api/dispatch/{did}")
            if view["state"] == want:
                return view
            for s in view["steps"]:
                if s["state"] == "running" and self.daemon._turn_of(s["chat_id"]).open_turn is not None:
                    self.daemon.finish(s["chat_id"], reply=f"第 {s['seq']} 步做好了", cost="0.04")
            self.drunner.tick()
        self.fail("the dispatch did not reach " + want)

    # ------------------------------------------------------------------------------------------------------------

    def test_the_whole_way_preview_proposal_confirmation_steps_and_the_list(self):
        config_before = self.config_bytes()
        cards_before = set(ap.load_all(None, None, mark_corrupt=False))
        preview, chief_view, did = self.ask()
        # the preview is what the dialog shows: counts and money, never a word of the conversation
        self.assertEqual((preview["messages"], preview["cards"], preview["cap_usd"], preview["sends_to"]), (2, 1, "0.3", "Claude Code"))
        self.assertNotIn("預算", json.dumps(preview, ensure_ascii=False))
        # the proposal card
        view = self.ok(f"/api/dispatch/{did}")
        self.assertEqual((view["state"], view["cost"]["steps"], view["can"]["confirm"], view["tools"]), ("proposed", 3, True, ["claude"]))
        self.assertEqual(set(ap.load_all(None, None, mark_corrupt=False)), cards_before, "nothing is made before the person confirms")
        self.assertEqual(self.ok("/api/actions")["actions"][0]["kind"], "proposed")
        # the person changes a word and confirms
        body = {"proposal_sha": view["proposal_sha"], "title": view["plan"]["title"], "goal": view["plan"]["goal"], "new_cards": view["plan"]["new_cards"],
                "steps": [{"who": s["who"], "text": s["text"]} for s in view["plan"]["steps"]]}
        body["steps"][1]["text"] = "請用三行回答：成本與定價。"
        confirmed = self.ok(f"/api/dispatch/{did}/confirm", "POST", body)
        self.assertEqual((confirmed["state"], confirmed["started_by"], confirmed["edited"]), ("running", "you", True))
        made = confirmed["created_cards"]
        self.assertEqual(len(made), 1)
        card = ap.get_profile_readonly(made[0]["profile_id"])
        self.assertEqual((card["launch_mode"], card["equipped_skill_ids"], card["enabled"]), ("safe", [], True))
        task = tasks.get_task(confirmed["task_id"])
        self.assertEqual((task["title"], task["goal"]), (view["plan"]["title"], view["plan"]["goal"]))
        # the runner sends the steps in order; the second carries the first's reply as data
        done = self.tick_until(did, "done")
        self.assertEqual([s["state"] for s in done["steps"]], ["ended"] * 3)
        self.assertEqual([s["origin"]["step"] for s in self.daemon.sent], [1, 2, 3])
        self.assertEqual(self.daemon.sent[1]["text"].splitlines()[0], "請用三行回答：成本與定價。")
        self.assertIn("第 1 步做好了", self.daemon.sent[1]["text"])
        # the list: every thing done, who decided, the sent messages say they cannot be taken back
        rows = self.ok("/api/actions")["actions"]
        kinds = {r["kind"] for r in rows}
        self.assertTrue({"proposed", "confirmed", "card_created", "task_created", "step_sent", "step_ended", "done"} <= kinds, kinds)
        self.assertEqual({r["by"] for r in rows if r["kind"] in ("confirmed", "step_sent")}, {"you"})
        self.assertTrue(all("收不回來" in r["what"] for r in rows if r["kind"] == "step_sent"))
        created = next(r for r in rows if r["kind"] == "card_created")
        self.assertEqual((created["profile_id"], created["can_withdraw"]), (made[0]["profile_id"], True))
        self.assertEqual(self.config_bytes(), config_before, "the whole run did not touch the settings")
        for text in (json.dumps(rows, ensure_ascii=False), json.dumps(done, ensure_ascii=False)):
            self.assertNotIn("預算", text, "nothing of the conversation with the CEO is in what the pages are given")

    def test_the_daily_limit_pauses_the_dispatch_in_words_and_continue_goes_on(self):
        _, _, did = self.ask()
        view = self.ok(f"/api/dispatch/{did}")
        self.ok(f"/api/dispatch/{did}/confirm", "POST", {"proposal_sha": view["proposal_sha"], "title": view["plan"]["title"], "goal": view["plan"]["goal"],
                                                            "new_cards": view["plan"]["new_cards"], "steps": [{"who": s["who"], "text": s["text"]} for s in view["plan"]["steps"]]})
        self.tick_until(did, "running")
        self.drunner.tick()
        first = self.ok(f"/api/dispatch/{did}")["steps"][0]
        self.daemon.finish(first["chat_id"], reply="第 1 步做好了", cost="0.04")
        self.drunner.tick()
        self.lamp[0] = "red"
        self.drunner.tick()
        paused = self.ok(f"/api/dispatch/{did}")
        self.assertEqual((paused["state"], paused["pause"]["reason"]), ("paused", "daily_limit"))
        self.assertIn("每天上限", paused["pause"]["text"])
        self.assertIn("明天 0:00", paused["pause"]["text"])
        self.assertTrue(paused["can"]["continue"] and paused["can"]["stop"])
        sent_before = len(self.daemon.sent)
        self.lamp[0] = "green"
        self.assertEqual(self.ok(f"/api/dispatch/{did}/continue", "POST", {})["state"], "running")
        done = self.tick_until(did, "done")
        self.assertEqual(done["state"], "done")
        self.assertGreater(len(self.daemon.sent), sent_before)
        self.assertIn("paused", {r["kind"] for r in self.ok("/api/actions")["actions"]})

    def test_stop_ends_the_turn_and_sends_nothing_more_then_the_new_employee_is_taken_back(self):
        _, _, did = self.ask()
        view = self.ok(f"/api/dispatch/{did}")
        self.ok(f"/api/dispatch/{did}/confirm", "POST", {"proposal_sha": view["proposal_sha"], "title": view["plan"]["title"], "goal": view["plan"]["goal"],
                                                            "new_cards": view["plan"]["new_cards"], "steps": [{"who": s["who"], "text": s["text"]} for s in view["plan"]["steps"]]})
        self.drunner.tick()
        stopped = self.ok(f"/api/dispatch/{did}/stop", "POST", {})
        self.assertEqual(stopped["state"], "stopped")
        sent = len(self.daemon.sent)
        for _ in range(3):
            self.drunner.tick()
        self.assertEqual(len(self.daemon.sent), sent, "nothing more is sent")
        self.assertTrue(self.daemon.stopped, "the turn that was running was stopped")
        view = self.ok(f"/api/dispatch/{did}")
        made = view["created_cards"][0]
        self.assertIn(made["profile_id"], view["can"]["withdraw"])
        out = self.ok(f"/api/dispatch/{did}/withdraw-card", "POST", {"profile_id": made["profile_id"]})
        self.assertTrue(out["created_cards"][0]["withdrawn"])
        self.assertFalse(ap.get_profile_readonly(made["profile_id"])["enabled"], "switched off, not deleted")
        rows = self.ok("/api/actions")["actions"]
        self.assertFalse(next(r for r in rows if r["kind"] == "card_created")["can_withdraw"])
        self.assertIn("card_withdrawn", {r["kind"] for r in rows})

    def test_not_adopting_makes_nothing_and_leaves_the_chiefs_cost(self):
        _, chief_view, did = self.ask()
        cards = set(ap.load_all(None, None, mark_corrupt=False))
        self.assertEqual(self.ok(f"/api/dispatch/{did}/dismiss", "POST", {})["state"], "dismissed")
        self.assertEqual(set(ap.load_all(None, None, mark_corrupt=False)), cards)
        self.assertEqual(self.daemon.sent, [])
        self.assertEqual(self.ok(f"/api/chief/{chief_view['id']}")["spent_usd"], "0.02")
        ledger = self.ok("/api/meetings/ledger")
        self.assertEqual(ledger["spent_usd"], "0.02", "the chief of staff's call is in the day")
        self.assertIn("chief", ledger["includes"])

    def test_with_both_ticks_on_the_proposal_starts_by_itself_and_the_list_says_which_item_and_the_settings_are_what_the_person_wrote(self):
        self.ok("/api/settings/autonomy", "POST", {"create_cards": True, "dispatch": True})
        config_after_ticks = self.config_bytes()
        _, _, did = self.ask()
        view = self.ok(f"/api/dispatch/{did}")
        self.assertEqual((view["state"], view["started_by"], view["started_by_text"]), ("running", "auto2", "自己動手第 2 項"))
        done = self.tick_until(did, "done")
        self.assertEqual(done["state"], "done")
        rows = self.ok("/api/actions")["actions"]
        self.assertEqual(next(r for r in rows if r["kind"] == "card_created")["by_text"], "自己動手第 1 項")
        self.assertEqual({r["by"] for r in rows if r["kind"] == "step_sent"}, {"auto2"})
        made = done["created_cards"][0]
        self.assertEqual(ap.get_profile_readonly(made["profile_id"])["launch_mode"], "safe")
        self.assertEqual(self.config_bytes(), config_after_ticks, "the ticks were the person's; the run changed nothing else")

    def test_the_pages_the_proposal_needs_are_served_and_the_page_has_what_the_flow_uses(self):
        for path in ("/api/chief/preview?chat_id=" + self.chat_id, "/api/chief", "/api/dispatch", "/api/actions", "/api/settings/autonomy", "/api/meetings/ledger"):
            self.assertEqual(self.call(path)[0], 200, path)
        app = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
        for route in ("/api/chief/preview", "/api/chief", "/api/dispatch/", "/api/actions", "/api/meetings/ledger", "/api/meetings/verify"):
            self.assertIn(route, app, route)


if __name__ == "__main__":
    unittest.main()
