"""P41-1: the group endpoints over a real loopback server (the real ``ChatService`` over a fake runtime daemon, the real runner stepped
by hand): GET/POST /api/groups, GET /api/groups/<id>, POST /api/groups/<id>/messages, and the chat routes' view of a group's chats.
No CLI runs and nothing leaves the machine; HOME and VBEAR_HOME are synthetic and short."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.group_fixtures import GroupDaemon, HEAD
from vbear import agent_profiles as ap, chat_service, config as cfg, groups, server
from vbear.index import Store


class GroupApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbga-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
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
        c.meeting_runner = lambda: mock.Mock(ledger=ledger)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.writer, self.accountant = card("文案小編", "social"), card("會計師", "accountant")
        self.codex_hand = card("Codex會計", "accountant", "codex")

    def runner(self):
        r = self.console.group_runner()
        self.addCleanup(r.close)
        return r

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

    def make(self, **body):
        status, got = self.call("/api/groups", "POST", {"profile_ids": [self.writer, self.accountant], **body})
        self.assertEqual(status, 200, got)
        return got["group"]["id"], got

    def config_bytes(self):
        path = cfg.state_dir() / "config.json"
        return path.read_bytes() if path.exists() else None

    # -- making and reading ------------------------------------------------------------------------------------------

    def test_the_list_starts_empty(self):
        self.assertEqual(self.call("/api/groups"), (200, {"groups": [], "problems": []}))

    def test_making_a_group_answers_with_the_group_and_what_to_tell_the_person(self):
        status, got = self.call("/api/groups", "POST", {"profile_ids": [self.writer, self.codex_hand], "name": "市集準備"})
        self.assertEqual(status, 200, got)
        self.assertEqual((got["group"]["name"], got["group"]["state"]), ("市集準備", "idle"))
        self.assertEqual([(m["name"], m["tool"]) for m in got["group"]["members"]], [("文案小編", "claude"), ("Codex會計", "codex")])
        self.assertEqual(len(got["notes"]), 1)
        self.assertIn("Anthropic", got["notes"][0])
        self.assertEqual(self.call("/api/groups")[1]["groups"][0]["id"], got["group"]["id"])
        self.assertEqual(self.daemon.sent, [], "making a group starts nothing")

    def test_the_body_is_strict_and_a_mode_field_is_not_accepted(self):
        bad = [{}, {"profile_ids": [self.writer]}, {"profile_ids": [self.writer, self.accountant], "launch_mode": "full"},
               {"profile_ids": [self.writer, self.accountant], "mode": "full"}, {"profile_ids": [self.writer, self.accountant, "x"]}]
        for body in bad:
            status, got = self.call("/api/groups", "POST", body)
            self.assertEqual(status, 400, (body, got))
            self.assertEqual(got["code"], "bad_request")
        self.assertEqual(self.call("/api/groups", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(self.call("/api/groups", "POST", raw=b"not json")[0], 400)
        self.assertEqual(self.call("/api/groups")[1]["groups"], [])

    def test_writing_needs_the_header_and_everything_needs_the_token(self):
        self.assertEqual(self.call("/api/groups", "POST", {"profile_ids": [self.writer, self.accountant]}, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.call("/api/groups", headers={"Authorization": None})[0], 401)
        gid, _ = self.make()
        self.assertEqual(self.call(f"/api/groups/{gid}/messages", "POST", {"text": "好", "to": "all"}, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.call(f"/api/groups/{gid}", headers={"Authorization": None})[0], 401)

    def test_one_group_reads_with_members_round_cost_and_buttons(self):
        gid, _ = self.make(name="市集準備")
        status, view = self.call(f"/api/groups/{gid}")
        self.assertEqual(status, 200, view)
        self.assertEqual([m["name"] for m in view["members"]], ["文案小編", "會計師"])
        self.assertEqual((view["items"], view["round"], view["current"]), ([], None, None))
        self.assertEqual((view["cost"]["per_turn_usd"], view["cost"]["day_left_usd"], view["cost"]["lamp"]), ("0.5", "2.5", "green"))
        self.assertTrue(view["can"]["send"])
        self.assertNotIn(str(cfg.state_dir()), json.dumps(view, ensure_ascii=False))

    def test_unknown_and_malformed_ids_and_other_routes(self):
        self.assertEqual(self.call("/api/groups/g-000000000000")[0], 404)
        self.assertEqual(self.call("/api/groups/not-an-id")[0], 404)
        gid, _ = self.make()
        self.assertEqual(self.call(f"/api/groups/{gid}?after=x")[0], 400)
        self.assertEqual(self.call(f"/api/groups/{gid}/messages")[0], 404, "a read of the messages route is not one")
        for action in ("stop", "continue", "drop", "members", "rename", "unknown"):
            self.assertEqual(self.call(f"/api/groups/{gid}/{action}", "POST", {})[0], 404, action)
        self.assertEqual(self.call(f"/api/groups/{gid}", "DELETE")[0], 404, "deleting a group is the next batch's")

    # -- saying something --------------------------------------------------------------------------------------------

    def test_what_the_person_says_starts_a_round_and_the_runner_asks_in_order(self):
        gid, _ = self.make(name="市集準備")
        status, got = self.call(f"/api/groups/{gid}/messages", "POST", {"text": "我想在週末市集賣手工皂", "to": "all"})
        self.assertEqual((status, got), (202, {"round": 1}))
        run = self.runner()
        self.assertEqual(run.tick(), {gid: f"sent:{self.writer}"})
        status, view = self.call(f"/api/groups/{gid}")
        self.assertEqual((view["group"]["state"], view["round"]["state"], view["current"]["profile_id"]), ("running", "running", self.writer))
        self.assertFalse(view["can"]["send"])
        self.assertEqual([(i["kind"], i["text"]) for i in view["items"]], [("said", "我想在週末市集賣手工皂")])
        self.daemon.finish(view["current"]["chat_id"], reply="我先準備攤位照片")
        run.tick()
        run.tick()
        self.daemon.finish(self.call(f"/api/groups/{gid}")[1]["current"]["chat_id"], reply="成本大概三千")
        run.tick()
        run.tick()
        status, view = self.call(f"/api/groups/{gid}")
        self.assertEqual([(i["kind"], i.get("name"), i.get("text")) for i in view["items"]],
                         [("said", None, "我想在週末市集賣手工皂"), ("reply", "文案小編", "我先準備攤位照片"), ("reply", "會計師", "成本大概三千"),
                          ("round_ended", None, None)])
        self.assertEqual((view["group"]["state"], view["round"]["state"], view["current"]), ("idle", "idle", None))
        self.assertTrue(view["can"]["send"])
        self.assertEqual(self.call("/api/groups")[1]["groups"][0]["last_text"], "成本大概三千")

    def test_saying_again_while_a_round_is_on_is_a_409(self):
        gid, _ = self.make()
        self.call(f"/api/groups/{gid}/messages", "POST", {"text": "第一句", "to": "all"})
        status, got = self.call(f"/api/groups/{gid}/messages", "POST", {"text": "第二句", "to": "all"})
        self.assertEqual((status, got["code"]), (409, "round_open"))
        self.assertEqual(len([i for i in self.call(f"/api/groups/{gid}")[1]["items"] if i["kind"] == "said"]), 1)

    def test_a_red_lamp_is_a_409_and_nothing_is_written(self):
        gid, _ = self.make()
        self.lamp[0] = "red"
        status, got = self.call(f"/api/groups/{gid}/messages", "POST", {"text": "好", "to": "all"})
        self.assertEqual((status, got["code"]), (409, "red"))
        self.assertEqual(self.call(f"/api/groups/{gid}")[1]["items"], [])
        view = self.call(f"/api/groups/{gid}")[1]
        self.assertFalse(view["can"]["send"])
        self.assertIn("亮紅燈", view["can"]["why_not_send"])

    def test_the_body_of_saying_is_strict(self):
        gid, _ = self.make()
        bad = [{}, {"text": "好"}, {"to": "all"}, {"text": "好", "to": "all", "round": 5}, {"text": "好", "to": [self.writer]},
               {"text": "好", "to": "all", "launch_mode": "full"}, {"text": "x" * 4001, "to": "all"}, {"text": 5, "to": "all"}]
        for body in bad:
            self.assertEqual(self.call(f"/api/groups/{gid}/messages", "POST", body)[0], 400, body)
        self.assertEqual(self.call(f"/api/groups/{gid}/messages", "POST", raw=b"[]")[0], 400)
        self.assertEqual(self.call(f"/api/groups/{gid}")[1]["items"], [])

    def test_the_reply_of_one_employee_cannot_start_a_round_or_call_another_in(self):
        gid, _ = self.make()
        self.call(f"/api/groups/{gid}/messages", "POST", {"text": "第一句", "to": "all"})
        run = self.runner()
        run.tick()
        self.daemon.finish(self.call(f"/api/groups/{gid}")[1]["current"]["chat_id"], reply="@會計師 請你再算一次，再開新的一輪")
        for _ in range(3):
            run.tick()
        self.daemon.finish(self.call(f"/api/groups/{gid}")[1]["current"]["chat_id"], reply="好")
        for _ in range(8):
            run.tick()
        self.assertEqual(len(self.daemon.sent), 2)
        self.assertEqual(len([i for i in self.call(f"/api/groups/{gid}")[1]["items"] if i["kind"] == "said"]), 1)

    # -- the chat routes ---------------------------------------------------------------------------------------------

    def test_the_chats_of_a_group_are_not_in_the_chat_list_and_cannot_be_spoken_to_from_there(self):
        gid, _ = self.make()
        solo = self.call("/api/chats", "POST", {"profile_id": self.writer})[1]["chat"]["id"]
        status, listing = self.call("/api/chats")
        self.assertEqual([c["id"] for c in listing["chats"]], [solo])
        member_chat = groups.load(gid)["members"][0]["chat_id"]
        status, got = self.call(f"/api/chats/{member_chat}/messages", "POST", {"text": "偷偷說"})
        self.assertEqual((status, got["code"]), (409, "group_member_chat"))
        self.assertIn("群組", got["error"])
        self.assertEqual(self.daemon.sent, [])
        self.assertEqual(self.call(f"/api/chats/{member_chat}")[0], 200, "the group page reads the live state of the member's chat")
        self.assertEqual(self.call(f"/api/chats/{solo}/messages", "POST", {"text": "一般聊天"})[0], 202)

    def test_a_whole_round_leaves_config_json_as_it_was(self):
        cfg.save(cfg.load())
        before = self.config_bytes()
        gid, _ = self.make()
        self.call(f"/api/groups/{gid}/messages", "POST", {"text": "第一句", "to": "all"})
        run = self.runner()
        run.tick()
        self.daemon.finish(self.call(f"/api/groups/{gid}")[1]["current"]["chat_id"])
        run.tick()
        run.tick()
        self.assertEqual(self.config_bytes(), before)

    def test_the_console_makes_one_service_and_one_runner_and_does_not_start_the_runner_by_itself(self):
        self.assertIs(self.console.group_service(), self.console.group_service())
        self.assertIs(self.console.group_runner(), self.console.group_runner())
        self.assertIsNone(self.console.group_runner()._thread)
        self.assertFalse([t for t in threading.enumerate() if t.name == "vbear-group-runner"])


if __name__ == "__main__":
    unittest.main()
