"""P46-2 (ADR 0012): what the AGY chat needs before any process starts: the record of the versions that passed the chat
check, VBear's own settings folder, the checks of the folders AGY would read, the pinned binary and the one answer
"may this Mac chat with AGY". Synthetic HOME and state; the "agy" is a small script that prints a version and nothing
else. No real AGY is looked for, started or read, and the stand-in HOME holds decoys that fail the test when they are read."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import admin_policy
from vbear.runtime import agy_chat_env as env, cli_versions

VERSION = "1.5.3"


class TempCase(unittest.TestCase):
    """A temporary tree under /tmp: ``self.tmp/h`` is the stand-in HOME, ``self.state`` the VBear state folder."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="v46e.", dir="/tmp")))
        self.addCleanup(self._cleanup)
        self.home = self.tmp / "h"
        self.state = self.home / ".vbear"
        self.state.mkdir(parents=True)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "VBEAR_HOME": str(self.state)})
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(env, "CACHE_TTL_S", 0.0)
        patch.start()
        self.addCleanup(patch.stop)

    def _cleanup(self):
        for dirpath, dirnames, filenames in os.walk(self.tmp):
            for name in dirnames + filenames:
                try:
                    full = os.path.join(dirpath, name)
                    if not os.path.islink(full):
                        os.chmod(full, 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_private(self, path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o600)
        return path

    def record_pass(self, version=VERSION, *, shared=False, mode="agy-chat", passed=True, key="agy_version"):
        """The state the chat check leaves: the report, then the record naming it."""
        report = self.write_private(self.state / f"agy-report-{version}.json",
                                    json.dumps({"mode": mode, "passed": passed, key: version,
                                                **({"shared": "passed"} if shared else {})}))
        record_path = self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE
        try:
            versions = json.loads(record_path.read_text())["versions"]
        except (OSError, ValueError, KeyError):
            versions = {}
        versions[version] = {"passed": True, "verified_at": "2026-11-09T10:00:00+0000", "binary": "x",
                             "report": str(report), "tool": "vbear.boundary_check --mode agy-chat"}
        self.write_private(record_path, json.dumps({"versions": versions}))


class VerifiedRecordTests(TempCase):
    def test_nothing_is_verified_until_a_report_backs_it(self):
        self.assertEqual(cli_versions.AGY_CHAT_VERIFIED_VERSIONS, ())
        self.assertEqual(cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE, "agy-chat-verified.json")
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ())
        self.assertEqual(cli_versions.agy_chat_shared_verified_versions(), ())
        self.assertFalse(cli_versions.shared_verified("agy-chat", VERSION))

    def test_a_passed_report_of_the_same_mode_and_version_counts(self):
        self.record_pass()
        self.assertEqual(cli_versions.agy_chat_verified_versions(), (VERSION,))
        self.assertIn(VERSION, cli_versions.local_agy_chat_verified_versions())
        self.assertEqual(cli_versions.agy_chat_shared_verified_versions(), (), "the chat part alone is not the shared part")
        self.assertFalse(cli_versions.shared_verified("agy-chat", VERSION))

    def test_the_shared_part_counts_only_when_the_report_says_it_passed(self):
        self.record_pass(shared=True)
        self.assertEqual(cli_versions.agy_chat_shared_verified_versions(), (VERSION,))
        self.assertTrue(cli_versions.shared_verified("agy-chat", VERSION))
        self.assertFalse(cli_versions.shared_verified("agy-chat", "1.5.4"))
        self.assertFalse(cli_versions.shared_verified("agy-chat", "not a version"))
        self.assertFalse(cli_versions.shared_verified("agy-chat", None))

    def test_a_report_of_another_mode_a_failed_one_or_another_version_does_not_count(self):
        for kwargs in ({"mode": "codex-chat"}, {"mode": "chat"}, {"passed": False}, {"key": "codex_version"}):
            with self.subTest(kwargs=kwargs):
                self.record_pass(**kwargs)
                self.assertEqual(cli_versions.agy_chat_verified_versions(), ())
                (self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).unlink()
        self.record_pass()
        report = self.state / f"agy-report-{VERSION}.json"
        report.write_text(json.dumps({"mode": "agy-chat", "passed": True, "agy_version": "1.5.4"}))
        report.chmod(0o600)
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ())

    def test_a_record_whose_report_is_gone_does_not_count(self):
        self.record_pass()
        (self.state / f"agy-report-{VERSION}.json").unlink()
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ())

    def test_the_other_engines_keep_their_own_records(self):
        self.record_pass(shared=True)
        self.assertEqual(cli_versions.codex_chat_verified_versions(), ())
        self.assertEqual(cli_versions.chat_verified_versions(), ())
        self.assertFalse(cli_versions.shared_verified("codex-chat", VERSION))
        self.assertFalse(cli_versions.shared_verified("claude-chat", VERSION))

    def test_the_unverified_sentences_name_the_tool_the_version_and_the_plan(self):
        text = cli_versions.agy_chat_unverified_text("1.5.3")
        self.assertIn("AGY 1.5.3", text)
        self.assertIn("Google 方案", text)
        self.assertIn("驗證", text)
        self.record_pass("1.5.2")
        text = cli_versions.agy_chat_unverified_text("1.5.3")
        self.assertIn("1.5.2", text)
        shared = cli_versions.shared_unverified_text("agy-chat", "1.5.3")
        self.assertIn("AGY 1.5.3", shared)
        self.assertIn("Google 方案", shared)
        self.assertNotIn("Claude Code", shared)
        self.assertNotIn("ChatGPT", shared)
        self.assertIn("Codex", cli_versions.shared_unverified_text("codex-chat", "0.163.0"))


class FolderCase(TempCase):
    def setUp(self):
        super().setUp()
        self.chat_home = self.state / "agy-chat-home"

    def make_home(self):
        return env.ensure_chat_home(self.state)

    def refused(self, fn, *args, code=None, **kwargs):
        with self.assertRaises(env.AgyRefused) as ctx:
            fn(*args, **kwargs)
        if code:
            self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return str(ctx.exception)


class ChatHomeTests(FolderCase):
    def test_the_folder_is_under_the_state_folder_and_made_0700(self):
        self.assertEqual(env.chat_home_path(self.state), self.chat_home)
        self.assertEqual(env.home_state(self.state), ("missing", ""))
        self.assertEqual(self.make_home(), self.chat_home)
        self.assertEqual(stat.S_IMODE(os.stat(self.chat_home).st_mode), 0o700)
        self.assertEqual(env.home_state(self.state), ("ok", ""))
        self.assertEqual(env.ensure_chat_home(self.state), self.chat_home, "making it again is fine")
        self.assertEqual(os.listdir(self.chat_home), [], "nothing is put in it but by write_settings")

    def test_the_state_folder_may_sit_behind_a_link_but_the_chat_folder_may_not(self):
        real = self.tmp / "real-state"
        real.mkdir()
        link = self.tmp / "state-link"
        link.symlink_to(real)
        self.assertEqual(env.chat_home_path(link), real / "agy-chat-home")
        env.ensure_chat_home(link)
        self.assertTrue((real / "agy-chat-home").is_dir())
        shutil.rmtree(real / "agy-chat-home")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        (real / "agy-chat-home").symlink_to(elsewhere)
        self.refused(env.ensure_chat_home, real, code="unsafe_path")
        self.assertEqual(env.home_state(real)[0], "refused")
        self.assertEqual(os.listdir(elsewhere), [], "nothing was written through the link")

    def test_a_folder_that_is_not_a_plain_0700_one_is_refused_and_never_repaired(self):
        self.make_home()
        os.chmod(self.chat_home, 0o755)
        self.refused(env.check_chat_home, self.state, code="unsafe_path")
        self.refused(env.ensure_chat_home, self.state, code="unsafe_path")
        self.assertEqual(stat.S_IMODE(os.stat(self.chat_home).st_mode), 0o755, "an existing folder is not changed")
        shutil.rmtree(self.chat_home)
        self.chat_home.write_text("a file")
        self.refused(env.ensure_chat_home, self.state, code="unsafe_path")

    def test_a_state_folder_that_is_not_there_is_refused(self):
        self.refused(env.ensure_chat_home, self.tmp / "no-such-state", code="unsafe_path")

    def test_entries_vbear_never_writes_refuse_whatever_kind_of_entry_they_are(self):
        self.make_home()
        names = ["GEMINI.md", "AGENTS.md", "gemini.md", "Agents.MD",
                 "config/hooks.json", "config/skills", "config/workflows", "config/global_workflows", "config/plugins",
                 "config/projects", "config/Hooks.json"]
        for name in names:
            for kind in ("file", "dir", "link"):
                with self.subTest(name=name, kind=kind):
                    path = self.chat_home / name
                    path.parent.mkdir(exist_ok=True, mode=0o700)
                    {"file": lambda: path.write_text("x"), "dir": lambda: path.mkdir(),
                     "link": lambda: path.symlink_to(self.tmp / "nowhere")}[kind]()
                    why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
                    self.assertIn(name.split("/")[-1].lower(), why.lower())
                    self.assertNotIn(str(self.tmp), why, "the sentence does not print a path")
                    if kind == "dir":
                        shutil.rmtree(path)
                    else:
                        path.unlink()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "clean again")

    def test_a_config_folder_that_is_a_link_or_a_file_is_refused(self):
        self.make_home()
        (self.chat_home / "config").symlink_to(self.tmp)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        (self.chat_home / "config").unlink()
        (self.chat_home / "config").write_text("x")
        self.refused(env.check_chat_home, self.state, code="foreign_settings")

    def test_what_agy_makes_itself_is_fine(self):
        self.make_home()
        for rel in ("config/config.json", "antigravity-cli/conversations/c1.db", "antigravity-cli/log/a.log",
                    "antigravity-cli/skills/built-in/x.md"):
            self.write_private(self.chat_home / rel, "{}")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_mcp_config_must_be_missing_or_say_nothing(self):
        self.make_home()
        path = self.chat_home / "config" / "mcp_config.json"
        for text in ("", "  \n", "{}", '{"mcpServers":{}}', '{"mcpServers": {}, "extra": [], "name": "", "none": null}'):
            with self.subTest(text=text):
                self.write_private(path, text)
                self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        for text in ('{"mcpServers":{"x":{"command":"y"}}}', '{"mcpServers":{}, "enabled": false}', '{"a": 0}', "[1]",
                     "not json", '{"mcpServers": {', '"text"', "1"):
            with self.subTest(text=text):
                self.write_private(path, text)
                self.refused(env.check_chat_home, self.state, code="foreign_settings")
        self.write_private(path, "{}" + " " * (env.MCP_CONFIG_MAX))
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        path.unlink()
        path.symlink_to(self.tmp / "nowhere")
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        path.unlink()
        path.mkdir()
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        path.rmdir()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_a_deeply_nested_mcp_config_is_refused_not_a_crash(self):
        self.make_home()
        self.write_private(self.chat_home / "config" / "mcp_config.json", "[" * 5000 + "]" * 5000)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")

    def test_the_size_is_a_threshold_that_refuses_and_can_be_left_out(self):
        self.make_home()
        self.write_private(self.chat_home / "antigravity-cli" / "big.bin", "x" * 4096)
        self.assertEqual(env.HOME_LIMIT, 512 << 20)
        with mock.patch.object(env, "HOME_LIMIT", 1024):
            self.refused(env.check_chat_home, self.state, code="too_big")
            self.assertEqual(env.check_chat_home(self.state, size=False), self.chat_home)
            self.assertEqual(env.home_state(self.state)[0], "refused")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_a_link_inside_the_folder_cannot_be_counted_so_it_refuses(self):
        self.make_home()
        (self.chat_home / "antigravity-cli").mkdir(mode=0o700)
        (self.chat_home / "antigravity-cli" / "l").symlink_to(self.tmp)
        self.refused(env.check_chat_home, self.state, code="too_big")


class SettingsTests(FolderCase):
    EXPECTED = {"toolPermission": "request-review", "allowNonWorkspaceAccess": False, "enableTerminalSandbox": True,
                "useG1Credits": False, "permissions": {"allow": [], "ask": [], "deny": []}}

    @property
    def settings_path(self):
        return self.chat_home / "antigravity-cli" / "settings.json"

    def test_the_content_is_the_five_keys_of_the_design_and_nothing_else(self):
        self.assertEqual(env.SETTINGS, self.EXPECTED)
        self.assertEqual(json.loads(env.SETTINGS_BYTES), self.EXPECTED)
        self.assertEqual(env.SETTINGS_BYTES, env.SETTINGS_BYTES.strip() + b"\n")

    def test_it_is_written_before_a_process_starts_0600_in_a_0700_folder(self):
        self.make_home()
        self.assertEqual(env.write_settings(self.state), self.settings_path)
        self.assertEqual(self.settings_path.read_bytes(), env.SETTINGS_BYTES)
        self.assertEqual(stat.S_IMODE(os.stat(self.settings_path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.settings_path.parent).st_mode), 0o700)
        self.assertEqual(sorted(os.listdir(self.settings_path.parent)), ["settings.json"], "no temporary file is left")
        self.assertTrue(env.settings_intact(self.state))

    def test_it_makes_the_folder_when_it_is_not_there_yet(self):
        env.write_settings(self.state)
        self.assertEqual(self.settings_path.read_bytes(), env.SETTINGS_BYTES)

    def test_someone_elses_change_is_written_over_at_the_next_start(self):
        self.make_home()
        env.write_settings(self.state)
        for tamper in (b'{"toolPermission":"auto"}', b"", env.SETTINGS_BYTES + b" ", b"\xff\xfe"):
            with self.subTest(tamper=tamper):
                self.settings_path.write_bytes(tamper)
                os.chmod(self.settings_path, 0o644)
                self.assertFalse(env.settings_intact(self.state))
                env.write_settings(self.state)
                self.assertEqual(self.settings_path.read_bytes(), env.SETTINGS_BYTES)
                self.assertEqual(stat.S_IMODE(os.stat(self.settings_path).st_mode), 0o600)
                self.assertTrue(env.settings_intact(self.state))

    def test_it_never_follows_a_link_in_place_of_the_file(self):
        self.make_home()
        env.write_settings(self.state)
        target = self.write_private(self.tmp / "target.json", "untouched")
        self.settings_path.unlink()
        self.settings_path.symlink_to(target)
        self.assertFalse(env.settings_intact(self.state), "a link is not the file VBear wrote")
        env.write_settings(self.state)
        self.assertEqual(target.read_text(), "untouched", "the link's target is not written")
        self.assertFalse(self.settings_path.is_symlink())
        self.assertEqual(self.settings_path.read_bytes(), env.SETTINGS_BYTES)

    def test_a_link_or_a_file_in_place_of_antigravity_cli_refuses(self):
        self.make_home()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        (self.chat_home / "antigravity-cli").symlink_to(elsewhere)
        self.refused(env.write_settings, self.state, code="unsafe_path")
        self.assertEqual(os.listdir(elsewhere), [])
        (self.chat_home / "antigravity-cli").unlink()
        (self.chat_home / "antigravity-cli").write_text("x")
        self.refused(env.write_settings, self.state, code="unsafe_path")

    def test_a_folder_in_place_of_the_file_refuses_and_leaves_nothing_behind(self):
        self.make_home()
        (self.chat_home / "antigravity-cli" / "settings.json").mkdir(parents=True, mode=0o700)
        self.refused(env.write_settings, self.state, code="unsafe_path")
        self.assertEqual(os.listdir(self.settings_path.parent), ["settings.json"])
        self.assertFalse(env.settings_intact(self.state))

    def test_it_refuses_when_the_chat_folder_itself_is_not_usable(self):
        self.make_home()
        (self.chat_home / "GEMINI.md").write_text("x")
        self.refused(env.write_settings, self.state, code="foreign_settings")
        self.assertFalse((self.chat_home / "antigravity-cli").exists(), "nothing is made in a folder that is refused")

    def test_a_link_in_place_of_the_file_does_not_keep_the_folder_from_being_repaired(self):
        self.make_home()
        env.write_settings(self.state)
        self.settings_path.unlink()
        self.settings_path.symlink_to(self.tmp / "nowhere")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "the size count lets this one link through")
        env.write_settings(self.state)
        self.assertTrue(env.settings_intact(self.state))

    def test_a_missing_file_is_not_intact(self):
        self.make_home()
        self.assertFalse(env.settings_intact(self.state))
        self.assertFalse(env.settings_intact(self.tmp / "no-such-state"))

    def test_a_file_that_is_too_big_is_not_intact_without_reading_it_all(self):
        self.make_home()
        env.write_settings(self.state)
        self.settings_path.write_bytes(env.SETTINGS_BYTES + b" " * (1 << 20))
        self.assertFalse(env.settings_intact(self.state))


class DecoyTests(FolderCase):
    """The person's own AGY folders are never read: a decoy that cannot be opened is in the stand-in HOME, and every call
    here still works (they only name things; none opens a file of the person's)."""

    def test_nothing_here_reads_the_stand_in_home(self):
        decoys = [self.home / ".gemini" / "antigravity-cli" / "settings.json", self.home / ".gemini" / "GEMINI.md",
                  self.home / ".agents" / "skills" / "decoy-skill" / "SKILL.md", self.home / ".agents" / "skills.json"]
        for d in decoys:
            self.write_private(d, "decoy")
            d.chmod(0o000)
        before = {d: (d.stat().st_mtime_ns, d.stat().st_mode) for d in decoys}
        opened = []
        real_open = os.open

        def watch(path, *args, **kwargs):
            if ".gemini" in os.fspath(path) or ".agents" in os.fspath(path):
                opened.append(os.fspath(path))
            return real_open(path, *args, **kwargs)

        with mock.patch("os.open", watch):
            env.ensure_chat_home(self.state)
            env.write_settings(self.state)
            env.check_chat_home(self.state)
            env.home_state(self.state)
            self.assertEqual(env.home_hooks_state(self.home)[0], "absent")
        self.assertEqual(opened, [])
        self.assertEqual({d: (d.stat().st_mtime_ns, d.stat().st_mode) for d in decoys}, before)


class HooksTests(TempCase):
    def test_no_file_no_refusal(self):
        self.assertEqual(env.home_hooks_state(self.home), ("absent", ""))
        (self.home / ".agents" / "skills").mkdir(parents=True)                # the person's skills are not hooks
        (self.home / ".agents" / "skills.json").write_text("{}")
        (self.home / ".gemini").mkdir()
        self.assertEqual(env.home_hooks_state(self.home)[0], "absent")
        self.assertEqual(env.home_hooks_state()[0], "absent", "the default is HOME")

    def test_anything_with_that_name_refuses_without_being_opened(self):
        kinds = {"file": lambda p: p.write_text("{}"), "empty": lambda p: p.write_text(""),
                 "dir": lambda p: p.mkdir(), "link": lambda p: p.symlink_to(self.tmp / "nowhere"),
                 "unreadable": lambda p: (p.write_text("{}"), p.chmod(0o000))}
        for kind, make in kinds.items():
            with self.subTest(kind=kind):
                hooks = self.home / ".agents" / "hooks.json"
                hooks.parent.mkdir(exist_ok=True)
                make(hooks)
                with mock.patch("builtins.open", side_effect=AssertionError("opened")):
                    state, why = env.home_hooks_state(self.home)
                self.assertEqual(state, "present")
                self.assertIn("hooks", why)
                self.assertIn("~/.agents/hooks.json", why)
                self.assertNotIn(str(self.home), why)
                if kind == "dir":
                    hooks.rmdir()
                else:
                    hooks.unlink()

    def test_a_failure_to_tell_refuses_too(self):
        agents = self.home / ".agents"
        agents.mkdir()
        agents.chmod(0o000)
        state, why = env.home_hooks_state(self.home)
        agents.chmod(0o700)
        self.assertEqual(state, "unreadable")
        self.assertIn("無法確認", why)
        agents.rmdir()
        agents.write_text("a file where the folder should be")                 # ENOTDIR is not "not there" either
        self.assertEqual(env.home_hooks_state(self.home)[0], "unreadable")
        with mock.patch("os.lstat", side_effect=OSError(5, "Input/output error")):
            self.assertEqual(env.home_hooks_state(self.home)[0], "unreadable")

    def test_only_that_one_name_is_looked_at(self):
        calls = []
        real = os.lstat

        def watch(path, *a, **k):
            calls.append(os.fspath(path))
            return real(path, *a, **k)

        with mock.patch("os.lstat", watch), mock.patch("os.scandir", side_effect=AssertionError("listed")):
            env.home_hooks_state(self.home)
        self.assertEqual(calls, [str(self.home / ".agents" / "hooks.json")])


class WorkdirTests(TempCase):
    def setUp(self):
        super().setUp()
        self.work = self.tmp / "work"
        self.work.mkdir(mode=0o700)

    def refused(self, *args, code="agy_workdir", **kwargs):
        with self.assertRaises(env.AgyRefused) as ctx:
            env.check_workdir(self.work, *args, **kwargs)
        self.assertEqual(ctx.exception.code, code)
        self.assertNotIn(str(self.tmp), str(ctx.exception), "no path in the sentence")
        return str(ctx.exception)

    def test_an_ordinary_folder_is_fine(self):
        self.assertEqual(env.check_workdir(self.work), self.work)
        self.write_private(self.work / "notes.md", "hello")
        self.write_private(self.work / "sub" / "deep" / "a.txt", "x")
        (self.work / "sub" / "inner-link").symlink_to("deep")                  # a link that stays inside is fine
        (self.work / "sub" / "up").symlink_to("..")
        (self.work / "same").symlink_to(".")
        (self.work / "dangling-inside").symlink_to("nothing-here")
        self.write_private(self.work / "docs" / "agents.md.txt", "x")        # only the exact names count
        self.write_private(self.work / "docs" / "GEMINI.md", "x")             # below the top level they are not read as rules
        self.assertEqual(env.check_workdir(self.work), self.work)

    def test_the_five_names_at_the_top_refuse_whatever_they_are_and_however_they_are_cased(self):
        for name in env.WORKDIR_FORBIDDEN:
            for variant in (name, name.swapcase(), name.lower()):
                for kind in ("file", "dir", "link"):
                    with self.subTest(name=variant, kind=kind):
                        path = self.work / variant
                        {"file": lambda: path.write_text("x"), "dir": lambda: path.mkdir(),
                         "link": lambda: path.symlink_to("elsewhere")}[kind]()
                        why = self.refused()
                        self.assertIn(name, why, "the sentence names the entry")
                        self.assertIn("移走", why)
                        if kind == "dir":
                            path.rmdir()
                        else:
                            path.unlink()
        self.assertEqual(env.check_workdir(self.work), self.work)
        self.assertEqual(tuple(env.WORKDIR_FORBIDDEN), (".agents", ".agent", ".gemini", "GEMINI.md", "AGENTS.md"))

    def test_a_link_to_the_outside_refuses_at_any_depth(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        self.write_private(outside / "decoy.txt", "decoy")
        cases = {"absolute": str(outside), "absolute file": str(outside / "decoy.txt"), "relative": "../outside",
                 "dangling": "../nothing-at-all", "root": "/"}
        for label, target in cases.items():
            with self.subTest(label=label):
                link = self.work / "a" / "b" / "link"
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target)
                why = self.refused()
                self.assertIn("外面", why)
                link.unlink()
        # a chain: a link inside that points to another link that goes out
        (self.work / "hop").symlink_to(self.work / "a" / "b" / "out")
        (self.work / "a" / "b" / "out").symlink_to("../../../outside")
        self.refused()
        (self.work / "hop").unlink()
        (self.work / "a" / "b" / "out").unlink()
        self.assertEqual(env.check_workdir(self.work), self.work)

    def test_the_work_folder_itself_may_not_be_a_link(self):
        link = self.tmp / "work-link"
        link.symlink_to(self.work)
        with self.assertRaises(env.AgyRefused) as ctx:
            env.check_workdir(link)
        self.assertEqual(ctx.exception.code, "agy_workdir")

    def test_a_folder_that_is_not_there_yet_is_fine_and_a_file_is_not(self):
        self.assertEqual(env.check_workdir(self.tmp / "not-yet"), self.tmp / "not-yet")
        self.write_private(self.tmp / "afile", "x")
        with self.assertRaises(env.AgyRefused):
            env.check_workdir(self.tmp / "afile")

    def test_too_many_entries_or_an_unreadable_folder_refuse(self):
        for i in range(6):
            (self.work / f"f{i}").write_text("x")
        with mock.patch.object(env, "WORKDIR_SCAN_MAX", 5):
            self.assertIn("太多", self.refused())
        self.assertEqual(env.check_workdir(self.work), self.work)
        (self.work / "locked").mkdir()
        (self.work / "locked").chmod(0o000)
        self.assertIn("無法", self.refused())

    def test_the_code_and_the_noun_can_be_given_for_the_shared_folder(self):
        (self.work / ".gemini").mkdir()
        with self.assertRaises(env.AgyRefused) as ctx:
            env.check_workdir(self.work, code="shared_unsafe", label="共用資料夾")
        self.assertEqual(ctx.exception.code, "shared_unsafe")
        self.assertIn("共用資料夾", str(ctx.exception))
        self.assertNotIn("工作資料夾", str(ctx.exception))

    def test_the_scan_never_reads_a_file(self):
        self.write_private(self.work / "secret.txt", "decoy")
        (self.work / "secret.txt").chmod(0o000)
        self.assertEqual(env.check_workdir(self.work), self.work)


if __name__ == "__main__":
    unittest.main()
