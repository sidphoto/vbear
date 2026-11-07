"""P43-1 (ADR 0009): the shared folder page's routes (/api/shared, /api/shared/cards, /api/shared/reveal) over a real loopback
console. The switches live in ``<state>/shared-meta/settings.json`` (never in the shared folder an employee can write), all
start off, and only a browser request that carries ``X-VBear`` and the token turns one on. Finder is never opened: the console's
``reveal_command`` is a fake that records the argv. Every name, file and card is made up."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import test_chat_api as tca
from vbear import config as cfg, server, shared_folder
from vbear.runtime import shared_rules as sr


class SharedCase(tca.ApiCase):
    def setUp(self):
        super().setUp()
        self.opened: list = []
        self.console.reveal_command = self.opened.append
        self.shared = Path(sr.shared_path(cfg.state_dir()))
        self.meta = cfg.state_dir() / "shared-meta"

    def cards(self):
        status, out = self.call("/api/shared")
        self.assertEqual(status, 200, out)
        return {c["profile_id"]: c for c in out["cards"]}

    def switch(self, pid, on=True, **extra):
        return self.call("/api/shared/cards", "POST", {"profile_id": pid, "on": on, **extra})

    def log(self):
        path = self.meta / "log.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


class ViewTests(SharedCase):
    def test_a_fresh_page_has_every_switch_off_and_makes_nothing(self):
        codex = self.card("Codex 員工", "codex")
        grok = self.card("Grok 員工", "grok")
        status, out = self.call("/api/shared")
        self.assertEqual(status, 200, out)
        self.assertTrue(out["ok"])
        self.assertEqual((out["exists"], out["problem"], out["readable"], out["links"], out["files"]), (False, None, True, 0, []))
        self.assertEqual(out["used"], {"bytes": 0, "entries": 0, "max_bytes": 1 << 30, "max_entries": 10_000, "over": False})
        self.assertTrue(out["where_text"].endswith("/shared"))
        self.assertFalse(self.shared.exists(), "looking makes no folder")
        self.assertFalse(self.meta.exists(), "looking makes no record")
        by = {c["profile_id"]: c for c in out["cards"]}
        self.assertEqual({k: by[self.emp][k] for k in ("company", "can_chat", "on", "verified")}, {"company": "Anthropic", "can_chat": True, "on": False, "verified": None})
        self.assertEqual((by[codex]["company"], by[codex]["can_chat"], by[codex]["on"]), ("OpenAI", True, False))
        self.assertEqual((by[grok]["company"], by[grok]["can_chat"], by[grok]["on"]), (None, False, False))
        self.assertEqual(by[self.emp]["name"], "虛構員工")
        self.assertEqual(by[self.emp]["tool"], "claude")

    def test_the_place_is_written_with_the_home_as_a_tilde(self):
        out = self.call("/api/shared")[1]
        home = os.path.realpath(self.home)
        state = os.path.realpath(cfg.state_dir())
        want = "~" + state[len(home):] + "/shared" if state.startswith(home + os.sep) else state + "/shared"
        self.assertEqual(out["where_text"], want)
        self.assertNotIn(home, out["where_text"] if state.startswith(home + os.sep) else "")

    def test_a_switch_is_shown_after_it_is_turned_on(self):
        self.assertEqual(self.switch(self.emp)[0], 200)
        self.assertTrue(self.cards()[self.emp]["on"])
        self.assertEqual(self.switch(self.emp, False)[0], 200)
        self.assertFalse(self.cards()[self.emp]["on"])

    def test_files_are_listed_newest_first_with_links_marked_and_no_content_read(self):
        self.assertEqual(self.switch(self.emp)[0], 200)
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "huge.bin").write_bytes(b"x" * 100_000)
        (self.shared / "old.md").write_text("fictional old")
        (self.shared / "sub").mkdir()
        (self.shared / "sub" / "<script>alert(1)<!--.md").write_text("fictional")
        locked = self.shared / "unreadable.txt"
        locked.write_text("fictional words that must stay unread")
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o600)
        os.symlink(outside / "huge.bin", self.shared / "link-to-file")
        os.symlink(outside, self.shared / "link-to-folder")
        base = time.time() - 1000
        for i, name in enumerate(("old.md", "sub/<script>alert(1)<!--.md", "unreadable.txt")):
            os.utime(self.shared / name, (base + i * 10, base + i * 10), follow_symlinks=False)
        out = self.call("/api/shared")[1]                       # a file nobody can read is listed all the same: it is not opened
        names = [f["name"] for f in out["files"]]
        self.assertEqual(set(names), {"old.md", "sub/<script>alert(1)<!--.md", "unreadable.txt", "link-to-file", "link-to-folder"})
        self.assertNotIn("sub", names, "a folder is not a file")
        by = {f["name"]: f for f in out["files"]}
        self.assertTrue(by["link-to-file"]["link"] and by["link-to-folder"]["link"])
        self.assertFalse(by["old.md"]["link"])
        self.assertEqual(by["old.md"]["size"], len("fictional old"))
        self.assertLess(by["link-to-file"]["size"], 1000, "the size of the link, not of what it points at")
        files = [f for f in out["files"] if not f["link"]]
        self.assertEqual([f["name"] for f in files], ["unreadable.txt", "sub/<script>alert(1)<!--.md", "old.md"], "newest first")
        self.assertEqual(out["links"], 2)
        self.assertEqual(out["used"]["entries"], 6)
        self.assertLess(out["used"]["bytes"], 1000, "a link's target is not counted")
        self.assertEqual(set(by["old.md"]), {"name", "size", "mtime", "link"})

    def test_at_most_two_hundred_files_are_listed_and_all_are_counted(self):
        for i in range(205):
            (self.shared if self.shared.exists() else self._make()).joinpath(f"f{i:03d}.md").write_text("x")
        out = self.call("/api/shared")[1]
        self.assertEqual((len(out["files"]), out["used"]["entries"]), (200, 205))

    def _make(self):
        self.shared.mkdir(mode=0o700)
        return self.shared

    def test_over_the_limit_is_said(self):
        self._make()
        for i in range(6):
            (self.shared / f"f{i}").write_text("x")
        with mock.patch.object(sr, "MAX_ENTRIES", 5):
            out = self.call("/api/shared")[1]
        self.assertTrue(out["used"]["over"])
        self.assertEqual(out["used"]["max_entries"], 5)

    def test_a_folder_that_is_not_right_is_named_and_not_read(self):
        self._make()
        (self.shared / "a.md").write_text("x")
        os.chmod(self.shared, 0o755)
        out = self.call("/api/shared")[1]
        self.assertEqual((out["problem"], out["files"], out["exists"]), ("shared_unsafe", [], True))
        self.assertEqual(out["used"]["entries"], 0)

    def test_a_link_in_place_of_the_folder_is_named_and_not_followed(self):
        target = self.tmp / "target"
        target.mkdir(mode=0o700)
        (target / "a.md").write_text("x")
        os.symlink(target, self.shared)
        out = self.call("/api/shared")[1]
        self.assertEqual((out["problem"], out["files"]), ("shared_unsafe", []))

    def test_a_file_that_cannot_be_read_is_said_and_every_card_is_off(self):
        self.assertEqual(self.switch(self.emp)[0], 200)
        (self.meta / "settings.json").write_text("{broken")
        out = self.call("/api/shared")[1]
        self.assertEqual(out["readable"], False)
        self.assertFalse(any(c["on"] for c in out["cards"]))
        status, bad = self.switch(self.emp)
        self.assertEqual((status, bad["code"]), (503, "shared_unreadable"))
        self.assertFalse((self.meta / "settings.json").exists(), "moved aside by the store, not overwritten")

    def test_a_settings_file_in_the_shared_folder_decides_nothing(self):
        self._make()
        (self.shared / "settings.json").write_text(json.dumps({"v": 1, "cards_on": [self.emp]}))
        (self.shared / "shared-meta").mkdir()
        (self.shared / "shared-meta" / "settings.json").write_text(json.dumps({"v": 1, "cards_on": [self.emp]}))
        self.assertFalse(self.cards()[self.emp]["on"])
        self.assertFalse(shared_folder.for_card(self.emp, "claude-chat"))


class SwitchTests(SharedCase):
    def test_turning_one_on_makes_the_folder_private_and_records_it(self):
        status, out = self.switch(self.emp)
        self.assertEqual((status, out["ok"], out["profile_id"], out["on"]), (200, True, self.emp, True))
        self.assertEqual(stat.S_IMODE(os.lstat(self.shared).st_mode), 0o700)
        self.assertEqual(os.lstat(self.shared).st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(os.lstat(self.meta).st_mode), 0o700)
        for name in ("settings.json", "log.jsonl"):
            self.assertEqual(stat.S_IMODE(os.lstat(self.meta / name).st_mode), 0o600, name)
        self.assertEqual(json.loads((self.meta / "settings.json").read_text()), {"v": 1, "cards_on": [self.emp]})
        log = self.log()
        self.assertEqual([(x["what"], x["profile_id"], x["how"]) for x in log], [("card_on", self.emp, "page")])
        self.assertIsInstance(log[0]["at"], float)

    def test_turning_it_off_keeps_every_file(self):
        self.switch(self.emp)
        (self.shared / "keep.md").write_text("fictional")
        status, _ = self.switch(self.emp, False)
        self.assertEqual(status, 200)
        self.assertEqual((self.shared / "keep.md").read_text(), "fictional")
        self.assertEqual(json.loads((self.meta / "settings.json").read_text()), {"v": 1, "cards_on": []})
        self.assertEqual([x["what"] for x in self.log()], ["card_on", "card_off"])

    def test_twice_is_one_entry(self):
        self.switch(self.emp)
        self.switch(self.emp)
        self.assertEqual(json.loads((self.meta / "settings.json").read_text())["cards_on"], [self.emp])

    def test_the_default_is_off_for_everyone_so_off_is_not_kept_as_a_state(self):
        self.switch(self.emp, False)
        self.assertEqual(json.loads((self.meta / "settings.json").read_text())["cards_on"], [])

    def test_a_codex_card_is_refused_for_now(self):
        codex = self.card("Codex 員工", "codex")
        for body in ({"on": True}, {"on": False}, {"on": True, "confirm_company": True}):
            status, out = self.call("/api/shared/cards", "POST", {"profile_id": codex, **body})
            self.assertEqual((status, out["code"]), (400, "card_tool_unsupported"), body)
        self.assertFalse(self.meta.exists(), "nothing was written")
        self.assertFalse(self.shared.exists())

    def test_a_card_whose_tool_cannot_chat_and_one_that_is_not_there(self):
        grok = self.card("Grok 員工", "grok")
        self.assertEqual(self.switch(grok)[0], 400)
        self.assertEqual(self.switch("emp-nobody")[0], 404)
        self.assertFalse(self.meta.exists())

    def test_the_body_is_closed(self):
        bad = ({}, {"profile_id": self.emp}, {"on": True}, {"profile_id": self.emp, "on": "yes"}, {"profile_id": self.emp, "on": 1},
               {"profile_id": 5, "on": True}, {"profile_id": "../x", "on": True}, {"profile_id": self.emp, "on": True, "path": "/etc"},
               {"profile_id": self.emp, "on": True, "confirm_company": "yes"}, {"profile_id": self.emp, "on": True, "how": "group"}, [], "x")
        for body in bad:
            with self.subTest(body=str(body)[:50]):
                self.assertEqual(self.call("/api/shared/cards", "POST", body)[0], 400)
        self.assertEqual(self.call("/api/shared/cards", "POST", raw=b"{nope")[0], 400)
        self.assertFalse(self.meta.exists())
        self.assertFalse(self.shared.exists())

    def test_it_needs_the_page_header_and_the_token(self):
        self.assertEqual(self.call("/api/shared/cards", "POST", {"profile_id": self.emp, "on": True}, headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call("/api/shared/cards", "POST", {"profile_id": self.emp, "on": True}, headers={"Authorization": "Bearer nope"})[0], 401)
        self.assertEqual(self.call("/api/shared", headers={"Authorization": "Bearer nope"})[0], 401)
        self.assertEqual(self.call("/api/shared/reveal", "POST", {}, headers={"X-VBear": "0"})[0], 403)
        self.assertFalse(self.cards()[self.emp]["on"])
        self.assertEqual(self.opened, [])

    def test_other_paths_and_methods_are_not_found(self):
        for path, method in (("/api/shared/cards", "GET"), ("/api/shared/x", "GET"), ("/api/shared/reveal", "GET"), ("/api/shared", "POST"),
                             ("/api/shared/cards/x", "POST"), ("/api/shared/files", "GET"), ("/api/shared", "DELETE"), ("/api/shared/cards", "DELETE")):
            with self.subTest(path=path, method=method):
                self.assertIn(self.call(path, method, {} if method in ("POST", "DELETE") else None)[0], (404, 405))

    def test_a_folder_that_is_not_right_is_not_mended_and_the_switch_is_not_turned_on(self):
        self._make_bad()
        status, out = self.switch(self.emp)
        self.assertEqual((status, out["code"]), (409, "shared_unsafe"))
        self.assertEqual(stat.S_IMODE(os.lstat(self.shared).st_mode), 0o755, "not mended")
        self.assertFalse(self.cards()[self.emp]["on"])
        self.assertEqual(self.switch(self.emp, False)[0], 200, "turning off always works")

    def _make_bad(self):
        self.shared.mkdir(mode=0o700)
        os.chmod(self.shared, 0o755)

    def test_the_records_hold_no_file_name_and_the_page_never_writes_a_file_name_anywhere(self):
        self.switch(self.emp)
        (self.shared / "秘密價目表-fictional.md").write_text("fictional")
        self.call("/api/shared")
        self.call("/api/shared/reveal", "POST", {})
        self.switch(self.emp, False)
        for path in self.meta.rglob("*"):
            if path.is_file():
                self.assertNotIn("價目表", path.read_text(), path.name)

    def test_the_limit_on_how_many_cards(self):
        with mock.patch.object(shared_folder, "CARDS_MAX", 1):
            other = self.card("第二位員工")
            self.assertEqual(self.switch(self.emp)[0], 200)
            status, out = self.switch(other)
            self.assertEqual((status, out["code"]), (409, "shared_settings_full"))
            self.assertEqual(self.switch(self.emp, False)[0], 200)
            self.assertEqual(self.switch(other)[0], 200)


class RevealTests(SharedCase):
    def test_finder_is_asked_to_open_the_one_folder_with_a_fixed_command(self):
        status, out = self.call("/api/shared/reveal", "POST", {})
        self.assertEqual((status, out), (200, {"ok": True, "revealed": True}))
        self.assertEqual(self.opened, [["/usr/bin/open", str(self.shared)]])
        self.assertTrue(self.shared.is_dir(), "made when it was not there")
        self.assertEqual(stat.S_IMODE(os.lstat(self.shared).st_mode), 0o700)
        self.assertEqual([x["what"] for x in self.log()], ["revealed"])
        self.assertEqual(self.log()[0]["how"], "page")
        self.assertNotIn("profile_id", self.log()[0])

    def test_the_command_is_not_a_shell_and_nothing_of_the_request_is_in_it(self):
        self.call("/api/shared/reveal", "POST", {})
        argv = self.opened[0]
        self.assertEqual(len(argv), 2)
        self.assertEqual(argv[0], "/usr/bin/open")
        self.assertEqual(argv[1], sr.shared_path(cfg.state_dir()))

    def test_a_body_with_anything_in_it_is_refused(self):
        for body in ({"path": "/etc"}, {"x": 1}, [], "x"):
            with self.subTest(body=str(body)):
                self.assertEqual(self.call("/api/shared/reveal", "POST", body)[0], 400)
        self.assertEqual(self.call("/api/shared/reveal", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(self.call("/api/shared/reveal", "POST", raw=b"{nope")[0], 400)
        self.assertEqual(self.opened, [])

    def test_a_folder_that_is_not_right_is_not_opened(self):
        self.shared.mkdir(mode=0o700)
        os.chmod(self.shared, 0o777)
        status, out = self.call("/api/shared/reveal", "POST", {})
        self.assertEqual((status, out["code"]), (409, "shared_unsafe"))
        self.assertEqual(self.opened, [])

    def test_only_a_mac_can_open_finder(self):
        with mock.patch.object(shared_folder, "IS_MAC", False):
            status, out = self.call("/api/shared/reveal", "POST", {})
        self.assertEqual((status, out["code"]), (400, "not_mac"))
        self.assertIn("Mac", out["error"])
        self.assertEqual(self.opened, [])

    def test_a_console_nobody_wired_a_command_into_opens_nothing(self):
        """The console of every test is built like this one: the way to open Finder is wired by ``serve()`` alone, so a test that
        forgot to fake it opens nothing, whatever the machine is."""
        self.console.reveal_command = None
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("started a program")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("started a program")), \
                mock.patch.object(os, "system", side_effect=AssertionError("started a program")):
            status, out = self.call("/api/shared/reveal", "POST", {})
        self.assertEqual((status, out["code"]), (503, "reveal_unavailable"))

    def test_the_console_as_the_tests_build_it_has_no_command(self):
        other = server.Console(self.httpd.server_address[1])
        self.assertIsNone(other.reveal_command)

    def test_a_command_that_fails_is_said_without_the_path(self):
        def boom(argv):
            raise subprocess.TimeoutExpired(argv, 10)
        self.console.reveal_command = boom
        status, out = self.call("/api/shared/reveal", "POST", {})
        self.assertEqual((status, out["code"]), (502, "reveal_failed"))
        self.assertNotIn(str(self.tmp), json.dumps(out))
        self.assertEqual(self.log(), [], "nothing is recorded as done")

    def test_the_real_command_is_the_fixed_argv_with_a_timeout_and_no_shell(self):
        calls = []
        with mock.patch.object(server.subprocess, "run", side_effect=lambda *a, **k: calls.append((a, k))):
            server._open_in_finder(["/usr/bin/open", "/some/where"])
        (args, kwargs), = calls
        self.assertEqual(args, (["/usr/bin/open", "/some/where"],))
        self.assertEqual(kwargs.get("timeout"), 10)
        self.assertIs(kwargs.get("check"), True)
        self.assertFalse(kwargs.get("shell", False))

    def test_only_serve_wires_the_real_command(self):
        source = Path(server.__file__).read_text(encoding="utf-8")
        wired = [line.strip() for line in source.splitlines() if "reveal_command" in line and "=" in line and "self." not in line]
        self.assertTrue(any(line.startswith("console.reveal_command = _open_in_finder") for line in wired), wired)
        self.assertEqual(len([x for x in source.splitlines() if "_open_in_finder" in x and "def " not in x and "console.reveal_command =" in x]), 1)


if __name__ == "__main__":
    unittest.main()
