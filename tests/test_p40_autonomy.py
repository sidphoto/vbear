"""P40-2: the settings of 「自己動手」 (ADR 0003): the table, the reading of config.json, the check of a request, and the two
routes. Over HTTP against a Console's handler (config only: no daemon, no AI tool)."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.test_chat_api import Http
from vbear import autonomy, config as cfg, server
from vbear.index import Store

PATH = "/api/settings/autonomy"

# the wording of plan.md (P40), word for word
TITLE_1 = "幕僚長可以自己建新員工"
EFFECT_1 = "幕僚長提議要新員工時，VBear 不等你確認就建好（一律安全模式），你可以在「AI 自己做了什麼」撤回。"
TITLE_2 = "幕僚長可以自己派工給員工"
EFFECT_2 = ("幕僚長的提議一到就開始派工，不再停在提議卡；員工照舊每個指令都問你。提議要新員工（而第 1 項沒勾）、VBear 拿掉了東西、"
            "或幕僚長有問題要問你時，還是會停下來等你。")
OFF4 = {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": False}
LATER = "不必每次問、倒數後自動接續這兩項會在之後的版本加入。"


class TableTests(unittest.TestCase):
    def test_the_five_items_of_adr_0003_and_only_three_work_in_this_version(self):
        # P44-2 made item 3 work and gave the block its two new booleans; item 5 (P44-4) is in the block but not yet in the table
        self.assertEqual([i["id"] for i in autonomy.ITEMS], [1, 2, 3, 4, 5])
        self.assertEqual([i["id"] for i in autonomy.ITEMS if i["active"]], [1, 2, 3])
        self.assertEqual([i["key"] for i in autonomy.ITEMS if i["active"]], ["create_cards", "dispatch", "routines"])
        self.assertEqual(autonomy.KEYS, ("create_cards", "dispatch", "routines", "auto_continue"))
        for item in autonomy.ITEMS:
            self.assertEqual(item["adr"], "0003")
            self.assertTrue(item["title"] and item["effect"])
        self.assertTrue(all(i["key"] is None for i in autonomy.ITEMS if not i["active"]))

    def test_the_words_are_the_plans(self):
        first, second = autonomy.ITEMS[0], autonomy.ITEMS[1]
        self.assertEqual((first["title"], first["effect"]), (TITLE_1, EFFECT_1))
        self.assertEqual((second["title"], second["effect"]), (TITLE_2, EFFECT_2))
        self.assertEqual(autonomy.LATER_NOTE, LATER)

    def test_the_three_things_never_allowed_are_listed(self):
        self.assertEqual(len(autonomy.NEVER), 3)
        joined = "".join(autonomy.NEVER)
        for word in ("每天", "完整模式", "技能"):
            self.assertIn(word, joined)


class ChiefTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("vbear.chief"), "vbear/chief.py is not in this tree yet")
    def test_the_cost_the_page_names_is_the_chiefs_own_limit(self):
        from vbear import chief
        self.assertEqual(autonomy.CHIEF_CALL_USD, float(chief.CHIEF_CALL_USD))


class ReadTests(unittest.TestCase):
    OFF = {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": False}

    def test_the_default_is_both_off(self):
        self.assertEqual(autonomy.read({}), self.OFF)
        self.assertEqual(autonomy.read(cfg.DEFAULT_CONFIG), self.OFF)

    def test_only_true_is_true_and_what_cannot_be_read_is_false(self):
        self.assertEqual(autonomy.read({"autonomy": {"create_cards": True, "dispatch": False}}),
                         {"create_cards": True, "dispatch": False, "routines": False, "auto_continue": False})
        for bad in (None, "yes", 1, [], [True], {"create_cards": 1, "dispatch": "true"}, {"create_cards": None},
                    {"dispatch": [True]}, {"unknown": True}):
            self.assertEqual(autonomy.read({"autonomy": bad}), self.OFF, bad)
        # one item that cannot be read does not turn the other off, and never turns anything on
        self.assertEqual(autonomy.read({"autonomy": {"create_cards": "x", "dispatch": True}}),
                         {"create_cards": False, "dispatch": True, "routines": False, "auto_continue": False})
        self.assertEqual(autonomy.read("not a dict"), self.OFF)
        self.assertEqual(autonomy.read(None), self.OFF)

    def test_a_config_flagged_corrupt_is_off(self):
        self.assertEqual(autonomy.read({"_corrupt": True, "autonomy": {"create_cards": True, "dispatch": True}}), self.OFF)

    def test_read_does_not_change_what_it_is_given(self):
        conf = {"autonomy": {"create_cards": True}}
        autonomy.read(conf)
        self.assertEqual(conf, {"autonomy": {"create_cards": True}})


class ValidateTests(unittest.TestCase):
    def test_exactly_the_four_booleans(self):
        body = {"create_cards": True, "dispatch": False, "routines": True, "auto_continue": False}
        self.assertEqual(autonomy.validate(body), body)

    def test_anything_else_is_refused(self):
        four = {"create_cards": True, "dispatch": True, "routines": True, "auto_continue": True}
        for bad in (None, [], "x", {}, {"create_cards": True}, {"dispatch": True},
                    {"create_cards": True, "dispatch": True},                       # the two keys of v0.17.1: one short of four
                    {**four, "daily_usd": 9}, {**four, "routine": True},
                    {k: v for k, v in four.items() if k != "routines"}, {k: v for k, v in four.items() if k != "auto_continue"},
                    {**four, "create_cards": 1, "dispatch": 0}, {**four, "create_cards": "true"},
                    {**four, "routines": None}, {**four, "auto_continue": 1}):
            with self.assertRaises(ValueError, msg=bad):
                autonomy.validate(bad)


class SettingsRoutes(Http, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vb-auto-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "h"
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
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def raw_conf(self) -> dict:
        return json.loads(cfg.config_path().read_text(encoding="utf-8"))

    def bytes_of_conf(self) -> bytes:
        return cfg.config_path().read_bytes()

    def test_the_default_is_both_off_and_the_page_gets_the_table(self):
        status, out = self.call(PATH)
        self.assertEqual(status, 200, out)
        self.assertEqual(out["autonomy"], OFF4)
        self.assertEqual([i["id"] for i in out["items"]], [1, 2, 3, 4, 5])
        self.assertEqual([i["id"] for i in out["items"] if i["active"]], [1, 2, 3])
        self.assertEqual(out["later_note"], LATER)
        self.assertEqual(len(out["never"]), 3)
        self.assertIn("per_turn_usd", out["limits"])
        self.assertIn("daily_usd", out["limits"])

    def test_the_read_needs_the_token(self):
        status, _ = self.call(PATH, headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)

    def test_a_config_that_cannot_be_read_gives_off_in_the_api(self):
        conf = self.raw_conf()
        conf["autonomy"] = "garbage"
        cfg.config_path().write_text(json.dumps(conf), encoding="utf-8")
        self.console.store.set_conf(cfg.load())
        status, out = self.call(PATH)
        self.assertEqual((status, out["autonomy"]), (200, OFF4))

    def test_post_writes_the_four_booleans_and_only_them(self):
        before = self.raw_conf()
        on = {**OFF4, "create_cards": True}
        status, out = self.call(PATH, "POST", on)
        self.assertEqual(status, 200, out)
        self.assertEqual(out["autonomy"], on)
        after = self.raw_conf()
        self.assertEqual(after["autonomy"], on)
        self.assertEqual({k: v for k, v in after.items() if k != "autonomy"}, {k: v for k, v in before.items() if k != "autonomy"})
        self.assertEqual(self.call(PATH)[1]["autonomy"], on)
        # and back off
        self.assertEqual(self.call(PATH, "POST", OFF4)[0], 200)
        self.assertEqual(self.raw_conf()["autonomy"], OFF4)

    def test_post_without_the_header_is_refused_and_nothing_is_written(self):
        before = self.bytes_of_conf()
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}{PATH}", method="POST",
                                     data=json.dumps({**OFF4, "routines": True}).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=15)
        with caught.exception:
            self.assertEqual(caught.exception.code, 403)  # the Console's gate for every write, before any route
        self.assertEqual(self.bytes_of_conf(), before)

    def test_post_with_a_bad_body_is_400_and_nothing_is_written(self):
        before = self.bytes_of_conf()
        for body in ({"create_cards": True}, {"dispatch": True}, {}, {"create_cards": True, "dispatch": True},
                     {**OFF4, "daily_usd": 9}, {**OFF4, "launch_mode": "full"},
                     {**OFF4, "create_cards": 1, "dispatch": 0}, {**OFF4, "create_cards": "true"},
                     {**OFF4, "create_cards": None, "dispatch": True}, {"create_cards": True, "dispatch": True, "routines": True}):
            status, out = self.call(PATH, "POST", body)
            self.assertEqual(status, 400, (body, out))
            self.assertIn("error", out)
        for raw in (b"[]", b"not json", b'"x"'):
            self.assertEqual(self.call(PATH, "POST", raw=raw)[0], 400, raw)
        self.assertEqual(self.bytes_of_conf(), before)

    def test_the_config_route_cannot_write_it(self):
        before = self.bytes_of_conf()
        for body in ({"autonomy": {"create_cards": True, "dispatch": True}}, {"autonomy": True}, {"autonomy": None},
                     {"advanced_mode": True, "autonomy": {"create_cards": True, "dispatch": True}}):
            status, out = self.call("/api/config", "POST", body)
            self.assertEqual(status, 400, (body, out))
        self.assertEqual(self.bytes_of_conf(), before)
        self.assertNotIn("autonomy", server.CONFIG_WRITABLE)

    def test_the_config_route_leaves_the_setting_as_it_was(self):
        both = {**OFF4, "create_cards": True, "dispatch": True}
        self.call(PATH, "POST", both)
        status, out = self.call("/api/config", "POST", {"advanced_mode": True})
        self.assertEqual(status, 200, out)
        self.assertEqual(self.raw_conf()["autonomy"], both)
        self.assertEqual(out["config"]["autonomy"], both)

    def test_the_other_settings_routes_do_not_touch_it(self):
        one = {**OFF4, "create_cards": True}
        self.call(PATH, "POST", one)
        self.assertEqual(self.call("/api/setup/daily-limit", "POST", {"daily_usd": 1})[0], 200)
        self.assertEqual(self.raw_conf()["autonomy"], one)

    def test_a_config_that_cannot_be_read_blocks_the_write(self):
        cfg.config_path().write_text("[1, 2]", encoding="utf-8")
        status, out = self.call(PATH, "POST", {**OFF4, "create_cards": True, "dispatch": True})
        self.assertEqual(status, 409, out)
        self.assertEqual(cfg.config_path().read_text(encoding="utf-8"), "[1, 2]")
        self.assertEqual(self.call(PATH)[1]["autonomy"], OFF4)


if __name__ == "__main__":
    unittest.main()
