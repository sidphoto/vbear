"""P34-3: a card set to full mode really departs.

The server builds the command line (a list, never a shell); the daemon opens the terminal and sets no sandbox, no
settings file, no tool list and no scratch. Claude Code gets the card's instructions as one `--append-system-prompt`
argument; Codex and AGY do not (their instructions are the paste button's). A safe card still departs as before.

A synthetic stand-in plays each CLI. No Claude, Codex, AGY or model is started.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import test_p34_instructions_api as base
from tests.test_agent_launch_api import GOOD
from tests.test_runtimed_managed import FAKE_CLI
from vbear import activity, agent_launch, agent_profiles, position_guide
from vbear.runtime import agent_sessions as a
from vbear.runtime import daemon as d
from vbear.runtime import native

# One stand-in for all three tools: it records how it was started and waits.
FAKE_ANY = r'''#!%(py)s
import json, os, sys, time
with open("fake-launch.json", "w") as f:
    json.dump({"argv": sys.argv, "cwd": os.getcwd(), "pid": os.getpid(), "env_names": sorted(os.environ),
               "tmpdir_env": os.environ.get("CLAUDE_CODE_TMPDIR"),
               "autoupdater_env": os.environ.get("DISABLE_AUTOUPDATER")}, f)
time.sleep(600)
'''

SANDBOX_FLAGS = ("--safe-mode", "--settings", "--tools", "--disallowedTools", "--permission-mode",
                 "--strict-mcp-config", "--sandbox", "--ignore-user-config", "--ephemeral", "--dangerously-skip-permissions")


class FullArgvTests(unittest.TestCase):
    def test_each_tool_gets_its_own_short_command(self):
        self.assertEqual(a.full_argv("claude", "/x/claude", None, None), ["/x/claude"])
        self.assertEqual(a.full_argv("claude", "/x/claude", "opus", "你是工程師"),
                         ["/x/claude", "--model", "opus", "--append-system-prompt", "你是工程師"])
        self.assertEqual(a.full_argv("codex", "/x/codex", "gpt-x", None), ["/x/codex", "-m", "gpt-x"])
        self.assertEqual(a.full_argv("agy", "/x/agy", "gemini-x", None), ["/x/agy", "--model", "gemini-x"])

    def test_only_claude_carries_the_instructions(self):
        for engine in ("codex", "agy"):
            with self.subTest(engine=engine):
                argv = a.full_argv(engine, f"/x/{engine}", None, "不會被帶上")
                self.assertEqual(argv, [f"/x/{engine}"])
                self.assertNotIn("不會被帶上", " ".join(argv))

    def test_nothing_of_the_safe_launch_is_in_it(self):
        for engine in a.FULL_ENGINES:
            argv = a.full_argv(engine, f"/x/{engine}", "m1", "指示")
            for flag in SANDBOX_FLAGS:
                self.assertNotIn(flag, argv, (engine, flag))

    def test_an_instruction_is_one_argument_that_never_starts_with_a_dash(self):
        argv = a.full_argv("claude", "/x/claude", None, "--dangerously-skip-permissions 然後做事")
        self.assertEqual(len(argv), 3)
        self.assertEqual(argv[1], "--append-system-prompt")
        self.assertFalse(argv[2].startswith("-"))
        self.assertTrue(argv[2].startswith(a.FULL_INSTRUCTION_LEAD))
        self.assertIn("--dangerously-skip-permissions 然後做事", argv[2])
        self.assertEqual(a.full_argv("claude", "/x/claude", None, "- 一\n- 二")[2], a.FULL_INSTRUCTION_LEAD + "- 一\n- 二")

    def test_an_instruction_is_cleaned_and_limited(self):
        self.assertEqual(a.full_instruction_arg("  第一行\r\n第二行\t完\x00\x07‮   "), "第一行\n第二行\t完")
        self.assertIsNone(a.full_instruction_arg("   \n\x00 "))
        self.assertIsNone(a.full_instruction_arg(None))
        self.assertIsNone(a.full_instruction_arg(7))
        long_text = "字" * 5000
        self.assertEqual(len(a.full_instruction_arg(long_text)), a.FULL_INSTRUCTION_MAX)
        # the lead never pushes it over the limit the daemon holds an argument to
        self.assertLessEqual(len(a.full_instruction_arg("-" + "字" * 5000)), a.FULL_INSTRUCTION_MAX + len(a.FULL_INSTRUCTION_LEAD))
        argv = a.full_argv("claude", "/x/claude", None, "x" * 5000)
        self.assertTrue(all(isinstance(x, str) and "\0" not in x and len(x) <= 4096 for x in argv))

    def test_a_bad_model_or_engine_or_binary_is_refused(self):
        for model in ("--x", "a b", "a;b", "x" * 80, 5, "-m"):
            with self.subTest(model=model), self.assertRaises(a.LaunchRefused):
                a.full_argv("claude", "/x/claude", model, None)
        with self.assertRaises(a.LaunchRefused):
            a.full_argv("shared", "/x/shared", None, None)
        for binary in ("claude", "", None, "/x/other", "/x/claude\0"):
            with self.subTest(binary=binary), self.assertRaises(a.LaunchRefused):
                a.full_argv("claude", binary, None, None)

    def test_the_daemons_check_accepts_what_is_built_and_nothing_else(self):
        for engine, model, text in (("claude", "opus", "指示"), ("claude", None, None), ("codex", "m", None),
                                    ("agy", None, None), ("agy", "g", "x")):
            argv = a.full_argv(engine, f"/x/{engine}", model, text)
            self.assertIsNone(a.full_argv_problem(engine, argv), argv)
        bad = [["/x/claude", "--dangerously-skip-permissions"], ["/x/claude", "--model", "--x"],
               ["/x/claude", "--append-system-prompt", "-x"], ["/x/claude", "--append-system-prompt", "a", "b"],
               ["/x/claude", "--append-system-prompt"], ["/x/other"], ["/x/claude", "-p", "hi"],
               ["claude"], [], "x", ["/x/claude", 5]]
        for argv in bad:
            with self.subTest(argv=argv):
                self.assertIsNotNone(a.full_argv_problem("claude", argv))
        self.assertIsNotNone(a.full_argv_problem("codex", ["/x/codex", "--model", "m"]))
        self.assertIsNotNone(a.full_argv_problem("codex", ["/x/codex", "--append-system-prompt", "x"]))
        self.assertIsNotNone(a.full_argv_problem("shared", ["/x/shared"]))


class DaemonOpenFullTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="sidp343-", dir="/tmp")))
        self.base = self.tmp / "st"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        for name in a.FULL_ENGINES:
            b = self.bindir / name
            b.write_text(FAKE_ANY % {"py": sys.executable}, encoding="utf-8")
            b.chmod(0o700)
        self.dm = d.Daemon(self.base, log=lambda m: None)
        self.dm.start()
        self.thread = threading.Thread(target=self.dm.serve_forever, daemon=True)
        self.thread.start()
        self.pids: list[int] = []

    def tearDown(self):
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        for pid in self.pids:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rpc(self, op, **kw):
        return d.rpc(op, base=self.base, timeout=15.0, **kw)

    def launched(self):
        path = self.work / "fake-launch.json"
        end = time.monotonic() + 8
        while time.monotonic() < end:
            try:
                info = json.loads(path.read_text())
                self.pids.append(info["pid"])
                return info
            except (OSError, ValueError):
                time.sleep(0.03)
        self.fail("the stand-in never started")

    def test_it_opens_a_plain_terminal_marked_full_with_no_launch_state(self):
        argv = a.full_argv("claude", str(self.bindir / "claude"), "opus", "指示")
        r = self.rpc("open_full", engine="claude", argv=argv, cwd=str(self.work), cols=100, rows=30)
        self.assertTrue(r["ok"], r)
        info = r["result"]
        self.assertEqual((info["engine"], info["launch_mode"], info["managed"], info["kind"]), ("claude", "full", None, None))
        self.assertEqual(info["argv"], argv)
        seen = self.launched()
        self.assertEqual(seen["argv"], argv)
        self.assertEqual(seen["cwd"], str(self.work))
        self.assertIsNone(seen["tmpdir_env"])
        self.assertIsNone(seen["autoupdater_env"])
        self.assertFalse((self.base / "sessions").exists() and list((self.base / "sessions").iterdir()))
        listed = self.rpc("list")["result"]["sessions"]
        self.assertEqual([(s["engine"], s["launch_mode"]) for s in listed], [("claude", "full")])
        self.assertIsNone(listed[0]["activity_evidence"])
        self.rpc("close", session_id=info["session_id"])

    def test_the_other_tools_open_too(self):
        for engine in ("codex", "agy"):
            with self.subTest(engine=engine):
                argv = a.full_argv(engine, str(self.bindir / engine), None, None)
                r = self.rpc("open_full", engine=engine, argv=argv, cwd=str(self.work))
                self.assertTrue(r["ok"], r)
                self.assertEqual((r["result"]["engine"], r["result"]["launch_mode"]), (engine, "full"))
                self.rpc("close", session_id=r["result"]["session_id"])

    def test_it_refuses_what_is_not_the_shape_built_by_full_argv(self):
        good = a.full_argv("claude", str(self.bindir / "claude"), None, None)
        cases = [
            {"engine": "claude", "argv": good + ["--dangerously-skip-permissions"], "cwd": str(self.work)},
            {"engine": "shared", "argv": good, "cwd": str(self.work)},
            {"engine": "claude", "argv": ["/bin/sh", "-c", "true"], "cwd": str(self.work)},
            {"engine": "claude", "argv": good, "cwd": "relative"},
            {"engine": "claude", "argv": good, "cwd": str(self.tmp / "missing")},
            {"engine": "claude", "argv": good, "cwd": str(self.work), "cols": 0},
            {"engine": "claude", "argv": [str(self.tmp / "nope" / "claude")], "cwd": str(self.work)},
        ]
        for case in cases:
            with self.subTest(case=case):
                r = self.rpc("open_full", **case)
                self.assertFalse(r["ok"], r)
        extra = self.rpc("open_full", engine="claude", argv=good, cwd=str(self.work), env={"PATH": "/x"})
        self.assertFalse(extra["ok"])
        self.assertEqual(extra["error"]["code"], "bad_request")
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])


class StatusTests(unittest.TestCase):
    def test_a_full_terminal_is_an_agent_whose_state_is_unknown_and_says_why(self):
        for engine in ("claude", "codex", "agy"):
            info = {"engine": engine, "launch_mode": "full", "managed": None, "exited": False, "closing": False,
                    "cli_version": None, "activity_evidence": None}
            got = activity.arbitrate(info, 1000.0)
            with self.subTest(engine=engine):
                self.assertEqual((got["activity"], got["display"]), ("unknown", "unknown"))
                self.assertIn("完整模式", got["reason"])
                self.assertEqual(got["evidence"], [])
        self.assertEqual(native._agent_engine({"engine": "agy", "launch_mode": "full"}), "agy")
        self.assertIsNone(native._agent_engine({"engine": None, "argv": ["/x/agy"]}))

    def test_an_exited_full_terminal_still_reads_exited(self):
        got = activity.arbitrate({"engine": "claude", "launch_mode": "full", "exited": True}, 1000.0)
        self.assertEqual(got["session"], "exited")


class FullApiCase(base.P342ApiCase):
    """The pass and the launch over HTTP, with a stand-in for each tool found on the search path."""

    def setUp(self):
        super().setUp()
        self.bindir = self.tmp / "fullbin"
        self.bindir.mkdir()
        self.found: dict[str, str] = {}
        for name in a.FULL_ENGINES:
            b = self.bindir / name
            b.write_text(FAKE_ANY % {"py": sys.executable}, encoding="utf-8")
            b.chmod(0o700)
            self.found[name] = str(b)
        self.resolver = mock.patch("vbear.runtime.native._full_cli_path", side_effect=lambda engine: self.found.get(engine))
        self.resolver.start()
        self.pids: list[int] = []

    def tearDown(self):
        self.resolver.stop()
        for pid in self.pids:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        super().tearDown()

    def save_full(self, tool="claude", **extra):
        body = {"name": "f-" + os.urandom(3).hex(), "model": {"tool": tool, "model_id": ""},
                "permission_intents": GOOD, "enabled": True, "launch_mode": "full", **extra}
        st, r = self.req("POST", "/api/agent-profiles", body)
        self.assertEqual(st, 200, r)
        return r["profile"]["id"]

    def full_preview(self, pid, **kw):
        body = {"profile_id": pid, "workdir": str(self.work), **kw}
        return self.req("POST", "/api/native/agent-previews", body)

    def confirm(self, pv, **kw):
        body = {"preview_id": pv["preview_id"], "expected_settings_digest": pv["settings_digest"], "user_confirmed": True, **kw}
        return self.req("POST", "/api/native/agent-launches", body)

    def seen(self):
        path = self.work / "fake-launch.json"
        end = time.monotonic() + 8
        while time.monotonic() < end:
            try:
                info = json.loads(path.read_text())
                self.pids.append(info["pid"])
                return info
            except (OSError, ValueError):
                time.sleep(0.03)
        self.fail("the stand-in never started")

    def fresh(self):
        p = self.work / "fake-launch.json"
        if p.exists():
            p.unlink()


class FullPassTests(FullApiCase):
    def test_a_claude_card_in_full_mode_is_launchable_and_the_pass_says_what_it_will_run(self):
        pid = self.save_full(position="executor")
        st, r = self.full_preview(pid)
        self.assertEqual(st, 200, r)
        pv = r["preview"]
        self.assertTrue(pv["launchable"], pv["reasons"])
        self.assertEqual(pv["reasons"], [])
        self.assertTrue(pv["preview_id"].startswith("p-"))
        self.assertEqual((pv["launch_mode"], pv["position"]), ("full", "executor"))
        self.assertEqual(pv["cli"]["binary"], self.found["claude"])
        self.assertIsNone(pv["canonical_paths"]["scratch"])
        self.assertEqual(pv["canonical_paths"]["workdir"], str(self.work))
        self.assertEqual(pv["derived_labels"], {})
        self.assertEqual(pv["armor_groups"], [])
        self.assertEqual({b["kind"] for b in pv["boundaries"]["items"]}, {"reminder"})
        self.assertIn("沒有限制", pv["mode_note"])
        text = position_guide.GUIDE["executor"]["prompt"]
        self.assertEqual(pv["instructions"]["delivery"], "argv")
        self.assertEqual(pv["instructions"]["source"], "default")
        self.assertEqual(pv["instructions"]["text"], text)
        self.assertEqual(pv["command"], [self.found["claude"], "--append-system-prompt", f"<職位指示，共 {len(text)} 字>"])
        self.assertTrue(pv["settings_digest"])
        # nothing was prepared: no launch state, no scratch
        self.assertFalse((self.home / "sessions").exists() and list((self.home / "sessions").iterdir()))
        self.assertEqual(self.sessions(), [])

    def test_the_commit_and_network_inputs_do_not_apply(self):
        pid = self.save_full(position="executor")
        for kw in ({}, {"commit": False}, {"commit": True}):
            st, r = self.full_preview(pid, **kw)
            self.assertTrue(r["preview"]["launchable"], (kw, r["preview"]["reasons"]))
        self.assertFalse(r["preview"]["launch_inputs"]["applies"])

    def test_the_intents_of_the_safe_launch_do_not_stop_a_full_one_but_a_deny_is_called_out(self):
        pid = self.save_full(permission_intents={"read": "unspecified", "write": "deny", "test": "unspecified", "deploy": "deny"})
        st, r = self.full_preview(pid)
        pv = r["preview"]
        self.assertTrue(pv["launchable"], pv["reasons"])
        joined = " ".join(pv["notes"])
        self.assertIn("編輯寫入", joined)
        self.assertIn("部署上線", joined)
        self.assertNotIn("讀取檔案", joined)
        # the usual card (read, write and test allowed, deploy denied) has one such record too, and it is called out
        st, r = self.full_preview(self.save_full(position="executor"))
        self.assertEqual(len(r["preview"]["notes"]), 1)
        self.assertIn("部署上線", r["preview"]["notes"][0])
        st, r = self.full_preview(self.save_full(permission_intents={"read": "allow", "write": "allow", "test": "allow", "deploy": "allow"}))
        self.assertEqual(r["preview"]["notes"], [])

    def test_a_card_with_no_instructions_carries_none(self):
        pid = self.save_full()
        st, r = self.full_preview(pid)
        pv = r["preview"]
        self.assertEqual(pv["instructions"]["delivery"], "none")
        self.assertEqual(pv["command"], [self.found["claude"]])

    def test_codex_and_agy_are_launchable_in_full_mode_and_say_the_instructions_are_pasted(self):
        for tool in ("codex", "agy"):
            with self.subTest(tool=tool):
                pid = self.save_full(tool=tool, position="legal")
                st, r = self.full_preview(pid)
                pv = r["preview"]
                self.assertTrue(pv["launchable"], pv["reasons"])
                self.assertEqual(pv["instructions"]["delivery"], "paste")
                self.assertEqual(pv["command"], [self.found[tool]])
                self.assertEqual({b["kind"] for b in pv["boundaries"]["items"]}, {"reminder"})

    def test_a_shared_card_and_a_disabled_card_are_still_refused(self):
        st, r = self.full_preview(self.save_full(tool="shared"))
        self.assertEqual([x["code"] for x in r["preview"]["reasons"]], ["tool_not_launchable"])
        self.assertIsNone(r["preview"]["preview_id"])
        st, r = self.full_preview(self.save_full(enabled=False))
        self.assertEqual([x["code"] for x in r["preview"]["reasons"]], ["profile_disabled"])

    def test_a_tool_that_is_not_installed_is_said_not_guessed(self):
        self.found.pop("agy")
        st, r = self.full_preview(self.save_full(tool="agy"))
        pv = r["preview"]
        self.assertFalse(pv["launchable"])
        self.assertEqual([x["code"] for x in pv["reasons"]], ["cli_not_found"])
        self.assertIn("agy", pv["reasons"][0]["message"])
        self.assertIsNone(pv["preview_id"])

    def test_the_model_of_the_card_is_in_the_command(self):
        pid = self.save_full(model={"tool": "claude", "model_id": "opus"})
        st, r = self.full_preview(pid)
        self.assertEqual(r["preview"]["command"][1:3], ["--model", "opus"])

    def test_a_safe_card_is_prepared_as_before(self):
        pid = self.save(position="executor", launch_mode="safe")
        st, r = self.preview(pid)
        pv = r["preview"]
        self.assertTrue(pv["launchable"])
        self.assertIsNotNone(pv["canonical_paths"]["scratch"])
        self.assertTrue(pv["derived_labels"])
        self.assertNotIn("command", pv)

    def test_an_old_card_without_a_mode_is_a_safe_one(self):
        pid = self.save(position="executor")
        st, r = self.preview(pid)
        self.assertEqual(r["preview"]["launch_mode"], "safe")
        self.assertIsNotNone(r["preview"]["canonical_paths"]["scratch"])


class FullLaunchTests(FullApiCase):
    def test_claude_departs_with_its_instructions_in_one_argument_and_no_sandbox(self):
        text = "第一行\n- 第二行"
        pid = self.save_full(position="executor", instructions=text, model={"tool": "claude", "model_id": "sonnet"})
        pv = self.full_preview(pid)[1]["preview"]
        self.fresh()
        st, r = self.confirm(pv)
        self.assertEqual(st, 200, r)
        session = r["launch"]["session"]
        self.assertEqual((session["engine"], session["launch_mode"], session["managed"]), ("claude", "full", None))
        seen = self.seen()
        self.assertEqual(seen["argv"], [self.found["claude"], "--model", "sonnet", "--append-system-prompt", text])
        for flag in SANDBOX_FLAGS:
            self.assertNotIn(flag, seen["argv"])
        self.assertEqual(seen["cwd"], str(self.work))
        self.assertIsNone(seen["tmpdir_env"])
        self.assertIsNone(seen["autoupdater_env"])
        self.assertEqual(r["launch"]["state"], "full_mode")
        self.assertFalse((self.home / "sessions").exists() and list((self.home / "sessions").iterdir()))
        self.assertEqual([s["session_id"] for s in self.sessions()], [session["session_id"]])

    def test_the_default_instructions_of_the_position_are_what_is_carried_when_there_is_no_text(self):
        pid = self.save_full(position="legal")
        pv = self.full_preview(pid)[1]["preview"]
        self.fresh()
        self.assertEqual(self.confirm(pv)[0], 200)
        argv = self.seen()["argv"]
        self.assertEqual(argv[-2:], ["--append-system-prompt", position_guide.GUIDE["legal"]["prompt"]])

    def test_an_instruction_that_starts_with_a_dash_is_led_by_a_sentence(self):
        pid = self.save_full(instructions="--dangerously-skip-permissions")
        pv = self.full_preview(pid)[1]["preview"]
        self.fresh()
        self.assertEqual(self.confirm(pv)[0], 200)
        argv = self.seen()["argv"]
        self.assertEqual(argv[1], "--append-system-prompt")
        self.assertTrue(argv[2].startswith(a.FULL_INSTRUCTION_LEAD))
        self.assertEqual(len(argv), 3)

    def test_codex_and_agy_depart_with_their_own_short_command(self):
        for tool, flag in (("codex", "-m"), ("agy", "--model")):
            with self.subTest(tool=tool):
                pid = self.save_full(tool=tool, position="art", model={"tool": tool, "model_id": "m-1"})
                pv = self.full_preview(pid)[1]["preview"]
                self.fresh()
                st, r = self.confirm(pv)
                self.assertEqual(st, 200, r)
                self.assertEqual(self.seen()["argv"], [self.found[tool], flag, "m-1"])
                self.assertEqual(r["launch"]["session"]["engine"], tool)
                self.dm_rpc("close", session_id=r["launch"]["session"]["session_id"])

    def test_the_person_must_confirm(self):
        pv = self.full_preview(self.save_full(position="executor"))[1]["preview"]
        for body in ({"preview_id": pv["preview_id"], "expected_settings_digest": pv["settings_digest"]},
                     {"preview_id": pv["preview_id"], "expected_settings_digest": pv["settings_digest"], "user_confirmed": False},
                     {"preview_id": pv["preview_id"], "expected_settings_digest": pv["settings_digest"], "user_confirmed": "yes"}):
            st, r = self.req("POST", "/api/native/agent-launches", body)
            self.assertEqual(st, 400, r)
        self.assertEqual(self.sessions(), [])

    def test_a_preview_is_used_once(self):
        pv = self.full_preview(self.save_full(position="executor"))[1]["preview"]
        self.assertEqual(self.confirm(pv)[0], 200)
        st, r = self.confirm(pv)
        self.assertIn(st, (404, 409))
        self.assertEqual(len(self.sessions()), 1)

    def test_a_changed_digest_a_changed_card_or_a_changed_program_needs_a_new_preview(self):
        pid = self.save_full(position="executor")
        pv = self.full_preview(pid)[1]["preview"]
        st, r = self.req("POST", "/api/native/agent-launches",
                         {"preview_id": pv["preview_id"], "expected_settings_digest": "0" * 64, "user_confirmed": True})
        self.assertEqual((st, r["code"]), (409, "settings_drift"))
        pv = self.full_preview(pid)[1]["preview"]
        st, r = self.req("POST", f"/api/agent-profiles/{pid}", {"instructions": "改過了"})
        self.assertEqual(st, 200, r)
        st, r = self.confirm(pv)
        self.assertEqual((st, r["code"]), (409, "profile_drift"))
        pv = self.full_preview(pid)[1]["preview"]
        Path(self.found["claude"]).write_text(FAKE_ANY % {"py": sys.executable} + "# changed\n")
        st, r = self.confirm(pv)
        self.assertEqual((st, r["code"]), (409, "cli_drift"))
        self.assertEqual(self.sessions(), [])

    def test_the_digest_follows_the_exact_command(self):
        pid = self.save_full(position="executor")
        first = self.full_preview(pid)[1]["preview"]
        second = self.full_preview(pid)[1]["preview"]
        self.assertEqual(first["settings_digest"], second["settings_digest"])
        self.req("POST", f"/api/agent-profiles/{pid}", {"instructions": "另一份指示"})
        third = self.full_preview(pid)[1]["preview"]
        self.assertNotEqual(first["settings_digest"], third["settings_digest"])

    def test_a_folder_outside_the_allowed_root_is_refused_as_before(self):
        st, r = self.full_preview(self.save_full(), workdir="/")
        self.assertEqual(st, 400, r)

    def test_the_new_terminal_is_listed_as_an_agent_with_an_unknown_state(self):
        pv = self.full_preview(self.save_full(position="executor"))[1]["preview"]
        r = self.confirm(pv)[1]
        sid = r["launch"]["session"]["session_id"]
        agents = self.console.runtime.list_sessions()["agents"]
        mine = [x for x in agents if x["terminal_id"] == sid]
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]["agent"], mine[0]["agent_status"]), ("claude", "unknown"))
        self.assertIn("完整模式", mine[0]["activity"]["reason"])


class CatalogAndLoadoutTests(FullApiCase):
    def test_the_catalog_says_full_mode_can_depart(self):
        st, cat = self.req("GET", "/api/agent-builder/catalog")
        self.assertIs(cat["full_mode_launchable"], True)
        self.assertIs(agent_launch.FULL_MODE_LAUNCHABLE, True)

    def test_the_loadout_of_a_full_card_has_no_blocker_and_no_armor_and_says_where_the_instructions_go(self):
        for tool, delivery in (("claude", True), ("codex", False), ("agy", False)):
            with self.subTest(tool=tool):
                pid = self.save_full(tool=tool, position="executor")
                st, ld = self.req("GET", f"/api/agent-profiles/{pid}/loadout")
                self.assertEqual(st, 200)
                self.assertEqual(ld["blockers"], [])
                self.assertFalse(ld["armor"]["applicable"])
                self.assertIs(ld["instructions"]["automatic"], delivery)
                self.assertIn("--append-system-prompt" if delivery else "貼上職位指示", ld["instructions"]["where"])

    def test_the_loadout_of_a_safe_card_still_says_the_instructions_are_not_carried(self):
        pid = self.save(position="executor", launch_mode="safe")
        st, ld = self.req("GET", f"/api/agent-profiles/{pid}/loadout")
        self.assertFalse(ld["instructions"]["automatic"])
        self.assertIn("不會自動", ld["instructions"]["where"])

    def test_the_boundary_lines_of_a_full_card_stay_reminders_and_name_no_shield(self):
        pid = self.save_full(position="social")
        st, ld = self.req("GET", f"/api/agent-profiles/{pid}/loadout")
        self.assertEqual({b["kind"] for b in ld["boundaries"]["items"]}, {"reminder"})


if __name__ == "__main__":
    unittest.main()
