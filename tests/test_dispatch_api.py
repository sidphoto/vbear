"""P40-3: the dispatch endpoints over a real loopback server, with the chief of staff's fake call: no CLI runs, nothing leaves the
machine. A proposal is asked for through /api/chief, becomes a dispatch through the runner's hook, and is confirmed, dismissed,
withdrawn and deleted through /api/dispatch*; 「AI 自己做了什麼」 is /api/actions."""
import copy
import json
import os
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

from tests.test_dispatch import EVIDENCE, VERSION, old_hands_plan, plan
from vbear import agent_profiles as ap, chief, chief_runner as cr, config as cfg, meeting_runner as mr, server, staffing_runner as sr
from vbear import tasks
from vbear.index import Store
from vbear.runtime import chat_store as cs


class DispatchApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbda-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.answer = plan()
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
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

    def propose(self, answer=None):
        """Ask the chief of staff through the API; the dispatch id the proposal got."""
        if answer is not None:
            self.answer = answer
        status, preview = self.call(f"/api/chief/preview?chat_id={self.chat_id}")
        self.assertEqual(status, 200, preview)
        status, started = self.call("/api/chief", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, started)
        self.console.chief.wait(10)
        status, got = self.call(f"/api/chief/{started['chief_id']}")
        self.assertEqual(status, 200, got)
        self.assertIsNotNone(got["dispatch_id"], got)
        return got["dispatch_id"]

    def body_of(self, view, **changes):
        plan_ = view["plan"]
        body = {"proposal_sha": view["proposal_sha"], "title": plan_["title"], "goal": plan_["goal"],
                "new_cards": plan_["new_cards"], "steps": [{"who": s["who"], "text": s["text"]} for s in plan_["steps"]]}
        body.update(changes)
        return body

    def config_bytes(self):
        path = cfg.state_dir() / "config.json"
        return path.read_bytes() if path.exists() else None

    # -- reading ---------------------------------------------------------------------------------------------------

    def test_a_proposal_shows_up_as_a_dispatch_with_its_card_data(self):
        self.assertEqual(self.call("/api/dispatch"), (200, {"dispatch": []}))
        did = self.propose()
        status, rows = self.call("/api/dispatch")
        self.assertEqual((status, [(r["id"], r["state"], r["title"]) for r in rows["dispatch"]]), (200, [(did, "proposed", "週末市集攤位")]))
        status, view = self.call(f"/api/dispatch/{did}")
        self.assertEqual(status, 200, view)
        self.assertEqual((view["state"], view["cost"]["steps"], view["cost"]["per_turn_usd"], view["cost"]["max_usd"]),
                         ("proposed", 2, "0.5", "1"))
        self.assertEqual(view["cost"]["day_left_usd"], "2.98", "the day's money, less the chief of staff's US$0.02")
        self.assertEqual([t["kind"] for t in view["team"]], ["existing", "new"])
        text = json.dumps(view, ensure_ascii=False)
        for word in ("預算", self.ceo):
            self.assertNotIn(word, text)

    def test_what_is_not_a_dispatch_is_not_found(self):
        self.assertEqual(self.call("/api/dispatch/d-ffffffffffff")[0], 404)
        self.assertEqual(self.call("/api/dispatch/nope")[0], 404)
        self.assertEqual(self.call("/api/dispatch/d-ffffffffffff/confirm", "POST", {})[0], 404)
        self.assertEqual(self.call("/api/dispatch/d-ffffffffffff/explode", "POST", {})[0], 404)

    def test_a_post_needs_the_browsers_header(self):
        did = self.propose()
        status, out = self.call(f"/api/dispatch/{did}/dismiss", "POST", {}, headers={"X-VBear": None})
        self.assertEqual(status, 403)
        self.assertEqual(self.call(f"/api/dispatch/{did}")[1]["state"], "proposed")

    # -- confirming --------------------------------------------------------------------------------------------------

    def test_confirming_through_the_api_makes_what_the_plan_says_and_lists_it(self):
        did = self.propose()
        before_config = self.config_bytes()
        before = set(ap.load_all(None, None, mark_corrupt=False))
        view = self.call(f"/api/dispatch/{did}")[1]
        status, out = self.call(f"/api/dispatch/{did}/confirm", "POST", self.body_of(view))
        self.assertEqual(status, 200, out)
        self.assertEqual((out["state"], out["started_by"], out["started_by_text"]), ("running", "you", "你確認的"))
        (new_id,) = set(ap.load_all(None, None, mark_corrupt=False)) - before
        self.assertEqual([c["profile_id"] for c in out["created_cards"]], [new_id])
        self.assertEqual(out["can"]["withdraw"], [new_id])
        self.assertEqual((out["can"]["stop"], out["can"]["confirm"]), (True, False))
        self.assertEqual(tasks.get_task(out["task_id"])["title"], "週末市集攤位")
        self.assertEqual(self.config_bytes(), before_config, "config.json is untouched")
        status, acts = self.call("/api/actions")
        self.assertEqual(status, 200)
        self.assertEqual([(a["kind"], a["by"]) for a in reversed(acts["actions"])],
                         [("proposed", "vbear"), ("confirmed", "you"), ("card_intent", "you"), ("card_created", "you"),
                          ("task_intent", "you"), ("task_created", "you")])
        self.assertEqual(acts["actions"][0].keys(), {"at", "dispatch_id", "seq", "kind", "what", "by", "by_text", "can_stop", "can_withdraw"})

    def test_a_refused_confirmation_answers_400_or_409_and_changes_nothing(self):
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        before = set(ap.load_all(None, None, mark_corrupt=False))
        cases = [
            ({**self.body_of(view), "daily_usd": 9}, 400),
            ({**self.body_of(view), "launch_mode": "full"}, 400),
            (self.body_of(view, steps=[{"who": "C9", "text": "x"}]), 400),
            (self.body_of(view, new_cards=[{**view["plan"]["new_cards"][0], "position": "planner"}]), 400),
            (self.body_of(view, new_cards=[{**view["plan"]["new_cards"][0], "tool": "codex"}]), 400),
            (self.body_of(view, title="題" * 81), 400),
            (self.body_of(view, steps=[{"who": "C1", "text": "字" * 1501}]), 400),
            (self.body_of(view, steps=[{"who": "C1", "text": str(i)} for i in range(5)]), 400),
            (self.body_of(view, proposal_sha="0" * 64), 409),
            ({}, 400),
        ]
        for body, status in cases:
            with self.subTest(body=json.dumps(body, ensure_ascii=False)[:80]):
                got, out = self.call(f"/api/dispatch/{did}/confirm", "POST", body)
                self.assertEqual(got, status, out)
                self.assertIn("error", out)
        for raw in (b"[1]", b"not json", b'"x"'):
            self.assertEqual(self.call(f"/api/dispatch/{did}/confirm", "POST", raw=raw)[0], 400)
        self.assertEqual(set(ap.load_all(None, None, mark_corrupt=False)), before)
        self.assertEqual((tasks.list_tasks(), self.call(f"/api/dispatch/{did}")[1]["state"]), ([], "proposed"))

    def test_a_dispatch_is_confirmed_once(self):
        did = self.propose()
        body = self.body_of(self.call(f"/api/dispatch/{did}")[1])
        self.assertEqual(self.call(f"/api/dispatch/{did}/confirm", "POST", body)[0], 200)
        status, out = self.call(f"/api/dispatch/{did}/confirm", "POST", body)
        self.assertEqual((status, out["code"]), (409, "not_proposed"))

    # -- the rest ---------------------------------------------------------------------------------------------------

    def test_dismiss_then_delete_leaves_nothing_but_what_the_person_has(self):
        did = self.propose()
        status, out = self.call(f"/api/dispatch/{did}/dismiss", "POST", {})
        self.assertEqual((status, out["state"]), (200, "dismissed"))
        self.assertEqual(self.call(f"/api/dispatch/{did}/dismiss", "POST", {})[0], 409)
        self.assertEqual(self.call(f"/api/dispatch/{did}/dismiss", "POST", {"x": 1})[0], 400)
        status, out = self.call(f"/api/dispatch/{did}/delete", "POST", {})
        self.assertEqual((status, out), (200, {"ok": True, "deleted": did}))
        self.assertEqual((self.call(f"/api/dispatch/{did}")[0], self.call("/api/dispatch")[1], chief.record_ids()), (404, {"dispatch": []}, []))

    def test_withdraw_card_and_stop_and_continue_over_http(self):
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        out = self.call(f"/api/dispatch/{did}/confirm", "POST", self.body_of(view))[1]
        pid = out["created_cards"][0]["profile_id"]
        self.assertTrue(out["can"]["stop"])
        status, got = self.call(f"/api/dispatch/{did}/continue", "POST", {})
        self.assertEqual((status, got["code"]), (409, "not_paused"), "it is running: nothing to continue")
        self.assertEqual(self.call(f"/api/dispatch/{did}/delete", "POST", {})[1]["code"], "not_deletable")
        self.assertEqual(self.call(f"/api/dispatch/{did}/withdraw-card", "POST", {"profile_id": self.writer})[0], 400)
        status, out = self.call(f"/api/dispatch/{did}/withdraw-card", "POST", {"profile_id": pid})
        self.assertEqual(status, 200, out)
        self.assertIs(ap.get_profile_readonly(pid)["enabled"], False)
        self.assertEqual(out["can"]["withdraw"], [])
        self.assertEqual(self.call(f"/api/dispatch/{did}/withdraw-card", "POST", {"profile_id": pid})[1]["code"], "already_withdrawn")
        status, got = self.call(f"/api/dispatch/{did}/stop", "POST", {})
        self.assertEqual((status, got["state"], got["events"][-1]["kind"], got["events"][-1]["by"]), (200, "stopped", "stopped", "you"))
        status, got = self.call(f"/api/dispatch/{did}/stop", "POST", {})
        self.assertEqual((status, got["code"]), (409, "not_active"))
        self.assertEqual(self.call(f"/api/dispatch/{did}/stop", "POST", {"x": 1})[0], 400)
        self.assertEqual(self.call("/api/dispatch/d-ffffffffffff/stop", "POST", {})[0], 404)
        self.assertEqual(self.call(f"/api/dispatch/{did}/delete", "POST", {})[0], 200, "a stopped dispatch can be deleted")

    def test_continue_over_http_lets_a_paused_dispatch_go_on(self):
        did = self.propose()
        self.call(f"/api/dispatch/{did}/confirm", "POST", self.body_of(self.call(f"/api/dispatch/{did}")[1]))
        self.console.dispatcher().control.d.mutate(did, lambda r: r.update(state="paused", pause={"reason": "daily_limit", "until": time.time() + 3600}))
        got = self.call(f"/api/dispatch/{did}")[1]
        self.assertEqual((got["state"], got["pause"]["reason"]), ("paused", "daily_limit"))
        self.assertIn("明天 0:00", got["pause"]["text"])
        self.assertIn("第 1 步", got["pause"]["text"])
        status, got = self.call(f"/api/dispatch/{did}/continue", "POST", {})
        self.assertEqual((status, got["state"], got["pause"]), (200, "running", None))
        self.assertEqual(got["events"][-1]["kind"], "continued")

    def test_the_console_has_one_dispatch_runner_that_is_not_started_by_building_it(self):
        runner = self.console.dispatch_runner()
        self.assertIs(runner, self.console.dispatch_runner())
        self.assertIs(self.console.dispatcher().control, runner)
        self.assertIsNone(runner._thread)

    def test_withdraw_card_is_refused_while_the_chat_has_a_turn_running(self):
        did = self.propose()
        out = self.call(f"/api/dispatch/{did}/confirm", "POST", self.body_of(self.call(f"/api/dispatch/{did}")[1]))[1]
        pid = out["created_cards"][0]["profile_id"]
        self.console.dispatcher()._mutate(did, lambda r: r["steps"][1].update(chat_id="c-0123456789abcdef", state="running", turn=1))
        status, got = self.call(f"/api/dispatch/{did}/withdraw-card", "POST", {"profile_id": pid})
        self.assertEqual((status, got["code"]), (409, "turn_running"))
        self.assertIs(ap.get_profile_readonly(pid)["enabled"], True)

    def test_with_both_ticks_a_whole_dispatch_goes_by_itself_and_config_json_only_holds_the_ticks(self):
        status, out = self.call("/api/settings/autonomy", "POST", {"create_cards": True, "dispatch": True})
        self.assertEqual(status, 200, out)
        after_ticks = self.config_bytes()
        did = self.propose()
        status, view = self.call(f"/api/dispatch/{did}")
        self.assertEqual((view["state"], view["started_by"], view["started_by_text"]), ("running", "auto2", "自己動手第 2 項"))
        self.assertEqual(len(view["created_cards"]), 1)
        self.assertEqual(self.config_bytes(), after_ticks, "the dispatch wrote nothing into config.json")
        status, acts = self.call("/api/actions")
        self.assertEqual({a["by"] for a in acts["actions"]}, {"vbear", "auto1", "auto2"})

    def test_a_console_that_stopped_in_the_middle_pauses_what_it_left_when_the_dispatcher_is_built(self):
        did = self.propose()
        view = self.call(f"/api/dispatch/{did}")[1]
        disp = self.console.dispatcher()

        class Killed(BaseException):
            pass
        with mock.patch.object(ap, "save_profile", side_effect=Killed()):
            with self.assertRaises(Killed):
                disp.confirm(did, self.body_of(view))
        del self.console.__dict__["_dispatcher"]                 # a new console: the dispatcher is built again
        self.assertEqual(self.call(f"/api/dispatch/{did}")[1]["pause"]["reason"], "uncertain")


if __name__ == "__main__":
    unittest.main()


class ServeStartsTheDispatchRunnerTests(unittest.TestCase):
    """``serve()`` starts the dispatch runner's thread next to the automation runner, and ends it with the console."""

    def test_the_thread_is_there_while_the_console_serves_and_gone_after(self):
        import signal
        tmp = tempfile.TemporaryDirectory(prefix="vbds-")
        self.addCleanup(tmp.cleanup)
        home = Path(os.path.realpath(tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        env = {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0", "BROWSER": "/usr/bin/true"}
        seen = {}

        class FakeHttpd:
            def __init__(self, *a, **k):
                pass

            def serve_forever(self):
                seen["threads"] = sorted(t.name for t in threading.enumerate() if t.name.endswith("runner"))
                raise KeyboardInterrupt

            def server_close(self):
                pass
        with mock.patch.dict(os.environ, env), mock.patch.object(server, "ThreadingHTTPServer", FakeHttpd), \
                mock.patch.object(signal, "signal"), mock.patch.object(server, "write_access_files"), \
                mock.patch.object(server, "remove_access_files"), mock.patch.object(Store, "static", return_value=None):
            with mock.patch("vbear.server.rt.get_runtime", return_value=mock.Mock(close_all=lambda: None)):
                server.serve(port=7799)
        self.assertIn("vbear-dispatch-runner", seen["threads"])
        self.assertEqual([t.name for t in threading.enumerate() if t.name in ("vbear-dispatch-runner", "vbear-runner")], [])
