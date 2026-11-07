"""P43-3 (ADR 0009 point 2): the two places besides the shared folder page where the person can open the folder for employees: the tick on
the new-group dialog (``POST /api/groups`` with ``shared_folder``) and the tick on a dispatch's proposal card
(``POST /api/dispatch/<id>/confirm`` with ``shared_folder``). Both are browser requests (token and ``X-VBear``); both default to off; a
Codex employee needs ``confirm_company``; an automatic dispatch (自己動手 item 2) opens nobody.

Seams: the HTTP routes of a real loopback console over the real ``ChatService`` on a fake runtime daemon, the chief of staff's fake call,
and the files under the synthetic state folder (``shared-meta/settings.json``, ``log.jsonl``, ``pending/``). No CLI runs and nothing leaves
the machine; HOME and VBEAR_HOME are synthetic and short; every name is made up."""

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

from tests.group_fixtures import GroupDaemon, HEAD
from tests.test_dispatch import EVIDENCE, VERSION, old_hands_plan, plan
from vbear import agent_profiles as ap, chat_service, chief_runner as cr, config as cfg, groups, meeting_runner as mr, server, shared_folder
from vbear import staffing_runner as sr_mod
from vbear.index import Store
from vbear.runtime import chat_store as cs, shared_rules as sr


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
        self.answer = plan()
        self.daemon = GroupDaemon()
        self.lamp = ["green"]
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = chat_service.ChatService(self.daemon, claude=lambda: (sys.executable, "2.1.318", ""), codex=lambda: dict(HEAD),
                                           codex_binary=lambda: (sys.executable, "0.163.0"))
        c.chats.restart_pause = 0
        ledger = lambda conf: {"lamp": self.lamp[0], "daily_usd": "3", "spent_usd": "0.5"}
        c.meetings = mr.MeetingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
        c.meetings.ledger = ledger
        c.staffing = sr_mod.StaffingRunner(provider=lambda e: ("unused", VERSION), call=lambda s, k: None)
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
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.ceo, self.writer = card("虛構CEO", "planner"), card("文案小編", "social")
        self.accountant, self.codex_hand = card("會計師", "accountant"), card("Codex會計", "accountant", "codex")
        self.card_fn = card
        self.shared = Path(sr.shared_path(cfg.state_dir()))
        self.meta = cfg.state_dir() / "shared-meta"
        base = cfg.state_dir()
        chat = cs.create(base, self.ceo, now=time.time())
        log = cs.ChatLog(base, chat["id"])
        log.append("user_message", {"turn": 1, "text": "我想在週末市集擺攤"}, now=time.time())
        log.append("reply", {"turn": 1, "text": "好，先問你預算", "truncated": False}, now=time.time())
        log.close()
        self.chat_id = chat["id"]

    def fake(self, spec, cancel):
        return mr.CallResult(copy.deepcopy(self.answer), dict(EVIDENCE), Decimal("0.02"))

    def call(self, path, method="GET", body=None, headers=None, raw=None):
        hdr = {"Authorization": "Bearer synthetic-test-token", "X-VBear": "1",
               "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
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

    def switches(self):
        path = self.meta / "settings.json"
        return json.loads(path.read_text())["cards_on"] if path.exists() else []

    def log(self):
        path = self.meta / "log.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def config_bytes(self):
        path = cfg.state_dir() / "config.json"
        return path.read_bytes() if path.exists() else None


class GroupTickTests(Base):
    def make(self, ids=None, **extra):
        return self.call("/api/groups", "POST", {"profile_ids": ids or [self.writer, self.accountant], **extra})

    def test_without_the_tick_a_group_is_made_as_before_and_nothing_is_opened(self):
        status, got = self.make()
        self.assertEqual(status, 200, got)
        self.assertNotIn("shared", got)
        self.assertFalse(self.meta.exists())
        self.assertFalse(self.shared.exists())

    def test_the_tick_off_is_the_same_as_none(self):
        status, got = self.make(shared_folder=False)
        self.assertEqual(status, 200, got)
        self.assertNotIn("shared", got)
        self.assertFalse(self.meta.exists())

    def test_the_tick_opens_the_folder_for_the_members_and_logs_how(self):
        before = self.config_bytes()
        status, got = self.make(shared_folder=True)
        self.assertEqual(status, 200, got)
        self.assertEqual(got["shared"], {"opened": [self.writer, self.accountant]})
        self.assertEqual(sorted(self.switches()), sorted([self.writer, self.accountant]))
        self.assertEqual([(x["what"], x["how"], x["profile_id"]) for x in self.log()],
                         [("card_on", "group", self.writer), ("card_on", "group", self.accountant)])
        self.assertTrue(self.shared.is_dir())
        self.assertEqual(oct(os.lstat(self.shared).st_mode & 0o777), "0o700")
        self.assertEqual(self.config_bytes(), before, "config.json is untouched")
        self.assertEqual(self.daemon.sent, [], "nothing is started or sent")

    def test_a_member_who_has_it_on_already_is_not_logged_again_and_the_others_are_opened(self):
        self.assertEqual(self.call("/api/shared/cards", "POST", {"profile_id": self.writer, "on": True})[0], 200)
        status, got = self.make(shared_folder=True)
        self.assertEqual((status, got["shared"]["opened"]), (200, [self.accountant]), got)
        self.assertEqual([(x["how"], x["profile_id"]) for x in self.log()], [("page", self.writer), ("group", self.accountant)])

    def test_a_group_of_other_people_leaves_the_rest_as_they_were(self):
        other = self.card_fn("另一位", "pm")
        self.make(shared_folder=True)
        self.assertNotIn(other, self.switches())
        self.assertNotIn(self.ceo, self.switches())

    def test_a_codex_member_needs_the_persons_confirmation_and_nothing_is_made_without_it(self):
        with mock.patch.object(shared_folder, "SUPPORTED_ENGINES", ("claude-chat", "codex-chat")):
            status, got = self.make([self.writer, self.codex_hand], shared_folder=True)
            self.assertEqual((status, got["code"], got.get("warn")), (409, "shared_confirm", ["send_to_openai"]), got)
            self.assertEqual(self.call("/api/groups")[1]["groups"], [], "no group was made")
            self.assertFalse(self.meta.exists(), "no switch was written")
            status, got = self.make([self.writer, self.codex_hand], shared_folder=True, confirm_company=True)
            self.assertEqual((status, sorted(got["shared"]["opened"])), (200, sorted([self.writer, self.codex_hand])), got)

    def test_a_codex_member_who_cannot_use_the_folder_yet_is_refused_before_the_group_is_made(self):
        with mock.patch.object(shared_folder, "SUPPORTED_ENGINES", ("claude-chat",)):
            status, got = self.make([self.writer, self.codex_hand], shared_folder=True, confirm_company=True)
            self.assertEqual((status, got["code"]), (400, "card_tool_unsupported"), got)
            self.assertEqual(self.call("/api/groups")[1]["groups"], [])
            status, got = self.make([self.writer, self.codex_hand])
            self.assertEqual(status, 200, "without the tick a Codex member is as welcome as before")

    def test_a_folder_that_is_not_right_refuses_before_the_group_is_made(self):
        self.shared.mkdir(mode=0o755)
        status, got = self.make(shared_folder=True)
        self.assertEqual((status, got["code"]), (409, "shared_unsafe"), got)
        self.assertEqual(self.call("/api/groups")[1]["groups"], [])
        self.assertEqual(oct(os.lstat(self.shared).st_mode & 0o777), "0o755", "not mended")

    def test_the_ticks_must_be_booleans_and_the_confirmation_goes_with_the_tick(self):
        for extra in ({"shared_folder": "yes"}, {"shared_folder": 1}, {"shared_folder": None}, {"confirm_company": True},
                      {"shared_folder": False, "confirm_company": True}, {"shared_folder": True, "confirm_company": "y"}):
            with self.subTest(extra=extra):
                status, got = self.make(**extra)
                self.assertEqual((status, got["code"]), (400, "bad_request"), got)
        self.assertEqual(self.call("/api/groups")[1]["groups"], [])
        self.assertFalse(self.meta.exists())

    def test_other_unknown_fields_are_still_refused(self):
        status, got = self.make(shared_folder=True, launch_mode="full")
        self.assertEqual((status, got["code"]), (400, "bad_request"))
        self.assertFalse(self.meta.exists())

    def test_the_route_needs_the_browsers_header_and_the_token(self):
        body = {"profile_ids": [self.writer, self.accountant], "shared_folder": True}
        self.assertEqual(self.call("/api/groups", "POST", body, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.call("/api/groups", "POST", body, headers={"Authorization": None})[0], 401)
        self.assertFalse(self.meta.exists())

    def test_a_group_member_who_is_a_card_that_cannot_chat_stops_the_group_as_before(self):
        grok = self.card_fn("Grok員工", "pm", "grok")
        status, got = self.make([self.writer, grok], shared_folder=True)
        self.assertGreaterEqual(status, 400, got)
        self.assertFalse(self.meta.exists())


class DispatchBase(Base):
    def propose(self, answer=None):
        if answer is not None:
            self.answer = answer
        status, preview = self.call(f"/api/chief/preview?chat_id={self.chat_id}")
        self.assertEqual(status, 200, preview)
        status, started = self.call("/api/chief", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, started)
        self.console.chief.wait(10)
        status, got = self.call(f"/api/chief/{started['chief_id']}")
        self.assertIsNotNone(got["dispatch_id"], got)
        return got["dispatch_id"]

    def body_of(self, view, **changes):
        plan_ = view["plan"]
        body = {"proposal_sha": view["proposal_sha"], "title": plan_["title"], "goal": plan_["goal"],
                "new_cards": plan_["new_cards"], "steps": [{"who": s["who"], "text": s["text"]} for s in plan_["steps"]]}
        body.update(changes)
        return body

    def confirm(self, did, **extra):
        view = self.call(f"/api/dispatch/{did}")[1]
        return self.call(f"/api/dispatch/{did}/confirm", "POST", self.body_of(view, **extra))

    def tick(self, did, **extra):
        view = self.call(f"/api/dispatch/{did}")[1]
        return self.call(f"/api/dispatch/{did}/confirm", "POST", {**self.body_of(view), "shared_folder": True, **extra})

    def pending(self, did):
        path = self.meta / "pending" / f"{did}.json"
        return json.loads(path.read_text()) if path.exists() else None


class DispatchTickTests(DispatchBase):
    def test_a_proposal_says_who_has_the_folder_and_who_would_read_what(self):
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        self.assertEqual(view["shared"]["people"], [{"who": "C1", "name": "文案小編", "on": False, "company": "Anthropic", "usable": True}])
        self.assertEqual(self.call("/api/shared/cards", "POST", {"profile_id": self.writer, "on": True})[0], 200)
        view = self.call(f"/api/dispatch/{did}")[1]
        self.assertTrue(view["shared"]["people"][0]["on"])
        self.assertFalse(self.meta.joinpath("pending").exists())

    def test_a_dispatch_that_is_not_waiting_has_no_shared_part(self):
        did = self.propose()
        self.assertEqual(self.confirm(did)[0], 200)
        self.assertNotIn("shared", self.call(f"/api/dispatch/{did}")[1])

    def test_without_the_tick_nobody_is_opened_and_no_file_is_made(self):
        did = self.propose()
        before = self.config_bytes()
        status, out = self.confirm(did)
        self.assertEqual(status, 200, out)
        self.assertNotIn("shared", out)
        self.assertFalse(self.meta.exists())
        self.assertFalse(self.shared.exists())
        self.assertEqual(self.config_bytes(), before)

    def test_the_tick_opens_the_folder_for_the_existing_employee_and_the_one_the_dispatch_makes(self):
        did = self.propose()
        known = set(ap.load_all(None, None, mark_corrupt=False))
        status, out = self.tick(did)
        self.assertEqual(status, 200, out)
        (new_id,) = set(ap.load_all(None, None, mark_corrupt=False)) - known
        self.assertEqual(sorted(self.switches()), sorted([self.writer, new_id]))
        self.assertEqual(out["shared"], {"opened": [self.writer]})
        self.assertEqual({(x["profile_id"], x["how"]) for x in self.log()}, {(self.writer, "dispatch"), (new_id, "dispatch")})
        self.assertEqual(self.pending(did), {"v": 1, "on": False, "confirm_company": False}, "the tick is spent when the confirmation is over")

    def test_an_employee_who_is_on_already_is_left_alone_and_not_logged_again(self):
        did = self.propose(old_hands_plan())
        self.assertEqual(self.call("/api/shared/cards", "POST", {"profile_id": self.writer, "on": True})[0], 200)
        status, out = self.tick(did)
        self.assertEqual((status, out["shared"]), (200, {"opened": []}), out)
        self.assertEqual(len(self.log()), 1)
        self.assertIsNone(self.pending(did), "nobody new: nothing to remember")

    def test_a_refused_confirmation_takes_the_tick_back_and_opens_nobody(self):
        did = self.propose()
        known = set(ap.load_all(None, None, mark_corrupt=False))
        view = self.call(f"/api/dispatch/{did}")[1]
        status, out = self.call(f"/api/dispatch/{did}/confirm", "POST", {**self.body_of(view, proposal_sha="0" * 64), "shared_folder": True})
        self.assertEqual((status, out["code"]), (409, "proposal_changed"), out)
        self.assertEqual(self.switches(), [])
        self.assertEqual(set(ap.load_all(None, None, mark_corrupt=False)), known)
        self.assertEqual(self.call(f"/api/dispatch/{did}")[1]["state"], "proposed")

    def test_a_confirmation_that_fails_after_the_existing_employee_was_opened_closes_him_again(self):
        did = self.propose()
        with mock.patch.object(server.dispatch_mod.Dispatcher, "confirm", side_effect=server.dispatch_mod.DispatchError("card_changed")):
            status, out = self.tick(did)
        self.assertEqual((status, out["code"]), (409, "card_changed"), out)
        self.assertEqual(self.switches(), [])
        self.assertEqual([(x["what"], x["how"]) for x in self.log()], [("card_on", "dispatch"), ("card_off", "dispatch")])

    def test_the_tick_taken_back_later_is_not_carried_over_to_a_later_confirmation(self):
        did = self.propose()
        shared_folder.mark_dispatch(did, True, False)                 # a tick that was written and never carried out
        status, out = self.confirm(did)                               # this time the person did not tick
        self.assertEqual(status, 200, out)
        self.assertEqual(self.switches(), [], "the new employee is not opened by an old tick")
        self.assertEqual(self.pending(did)["on"], False)

    def test_a_codex_new_employee_needs_the_confirmation_and_the_dispatch_is_not_confirmed_without_it(self):
        self.console.chief_tools = lambda: ("claude", "codex")
        self.console.chats = chat_service.ChatService(self.daemon, claude=lambda: (sys.executable, "2.1.318", ""), codex=lambda: dict(HEAD),
                                                      codex_binary=lambda: (sys.executable, "0.163.0"))
        self.console.chief_tools = lambda: ("claude", "codex")
        answer = plan(new_cards=[{"ref": "N1", "name": "會計師", "position": "accountant", "tool": "codex", "model_alias": "", "why": "算價"}])
        did = self.propose(answer)
        with mock.patch.object(shared_folder, "SUPPORTED_ENGINES", ("claude-chat", "codex-chat")):
            status, out = self.tick(did)
            self.assertEqual((status, out["code"], out.get("warn")), (409, "shared_confirm", ["send_to_openai"]), out)
            self.assertEqual(self.call(f"/api/dispatch/{did}")[1]["state"], "proposed")
            self.assertEqual(self.switches(), [])
            known = set(ap.load_all(None, None, mark_corrupt=False))
            status, out = self.tick(did, confirm_company=True)
            self.assertEqual(status, 200, out)
            (new_id,) = set(ap.load_all(None, None, mark_corrupt=False)) - known
            self.assertIn(new_id, self.switches())

    def test_a_new_employee_whose_tool_cannot_use_the_folder_yet_is_refused_before_anything_is_made(self):
        self.console.chief_tools = lambda: ("claude", "codex")
        answer = plan(new_cards=[{"ref": "N1", "name": "會計師", "position": "accountant", "tool": "codex", "model_alias": "", "why": "算價"}])
        did = self.propose(answer)
        known = set(ap.load_all(None, None, mark_corrupt=False))
        with mock.patch.object(shared_folder, "SUPPORTED_ENGINES", ("claude-chat",)):
            status, out = self.tick(did, confirm_company=True)
        self.assertEqual((status, out["code"]), (400, "card_tool_unsupported"), out)
        self.assertEqual(set(ap.load_all(None, None, mark_corrupt=False)), known)
        self.assertEqual(self.call(f"/api/dispatch/{did}")[1]["state"], "proposed")

    def test_the_ticks_must_be_booleans_and_go_together(self):
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        for extra in ({"shared_folder": "yes"}, {"confirm_company": True}, {"shared_folder": True, "confirm_company": 1}):
            with self.subTest(extra=extra):
                status, out = self.call(f"/api/dispatch/{did}/confirm", "POST", {**self.body_of(view), **extra})
                self.assertEqual((status, out["code"]), (400, "bad_request"), out)
        self.assertEqual(self.call(f"/api/dispatch/{did}")[1]["state"], "proposed")
        self.assertFalse(self.meta.exists())

    def test_the_route_needs_the_browsers_header(self):
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        status, _ = self.call(f"/api/dispatch/{did}/confirm", "POST", {**self.body_of(view), "shared_folder": True}, headers={"X-VBear": None})
        self.assertEqual(status, 403)
        self.assertFalse(self.meta.exists())

    def test_a_folder_that_is_not_right_refuses_the_confirmation_and_makes_nobody(self):
        self.shared.mkdir(mode=0o755)
        did = self.propose()
        known = set(ap.load_all(None, None, mark_corrupt=False))
        status, out = self.tick(did)
        self.assertEqual((status, out["code"]), (409, "shared_unsafe"), out)
        self.assertEqual(set(ap.load_all(None, None, mark_corrupt=False)), known)

    def test_a_marker_in_the_shared_folder_decides_nothing(self):
        did = self.propose()
        self.shared.mkdir(mode=0o700)
        pending = self.shared / "pending"
        pending.mkdir()
        (pending / f"{did}.json").write_text(json.dumps({"v": 1, "on": True, "confirm_company": True}))
        (self.shared / "settings.json").write_text(json.dumps({"v": 1, "cards_on": [self.writer]}))
        status, out = self.confirm(did)
        self.assertEqual(status, 200, out)
        self.assertEqual(self.switches(), [])
        self.assertFalse(shared_folder.for_card(self.writer, "claude-chat"))


class TheAutomaticDispatchOpensNobodyTests(DispatchBase):
    """自己動手 items 1 and 2 on: the proposal arrives, the employees are made and the dispatch starts without the person. No file of
    the shared folder switches is written."""

    def test_the_whole_automatic_way_leaves_the_switches_as_they_were(self):
        conf = cfg.load()
        conf["autonomy"] = {"create_cards": True, "dispatch": True}
        cfg.save(conf)
        self.console.store.set_conf(cfg.load())
        self.assertEqual(self.call("/api/shared/cards", "POST", {"profile_id": self.writer, "on": False})[0], 200)
        before = (self.meta / "settings.json").read_bytes()
        log_before = (self.meta / "log.jsonl").read_bytes()
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        self.assertEqual((view["state"], view["started_by"]), ("running", "auto2"), "the dispatch went on by itself")
        self.assertEqual(len(view["created_cards"]), 1, "and made its new employee")
        self.assertEqual((self.meta / "settings.json").read_bytes(), before)
        self.assertEqual((self.meta / "log.jsonl").read_bytes(), log_before)
        self.assertFalse((self.meta / "pending").exists())
        self.assertFalse(self.shared.exists())

    def test_an_old_tick_does_not_open_an_employee_the_automatic_way_makes(self):
        conf = cfg.load()
        conf["autonomy"] = {"create_cards": True, "dispatch": False}
        cfg.save(conf)
        self.console.store.set_conf(cfg.load())
        known = set(ap.load_all(None, None, mark_corrupt=False))
        did = self.propose()
        self.assertEqual(self.switches(), [], "an employee made while the proposal waited is off")
        self.assertEqual(len(set(ap.load_all(None, None, mark_corrupt=False)) - known), 1)
        self.assertIsNone(self.pending(did))


if __name__ == "__main__":
    unittest.main()
