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
import unittest
from pathlib import Path
from unittest import mock

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
        self.policy_root = self.tmp / "policy-root"                  # no administrator policy anywhere unless a test makes one
        self.policy_root.mkdir()
        patch = mock.patch.object(env, "POLICY_ROOT", str(self.policy_root))
        patch.start()
        self.addCleanup(patch.stop)
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir(mode=0o700)
        # Nothing here may find a real agy: the default search path is this empty folder, and the tests that look for the
        # file pass their own folder under self.tmp.
        patch = mock.patch("vbear.runtime.daemon.cli_search_path", return_value=str(self.tmp / "no-bin"))
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
                 "config/Hooks.json"]
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

    def test_what_agy_makes_there_by_itself_is_accepted_and_every_other_name_is_refused_by_name(self):
        self.make_home()
        for name in ("config/projects", "config/config.json", "config/mcp_config.json", "antigravity-cli/conversations",
                     "antigravity-cli/log/x.log"):
            path = self.chat_home / name
            path.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
            path.mkdir() if not name.endswith((".json", ".log")) else path.write_text("{}" if name.endswith(".json") else "x")
        (self.chat_home / "config" / "projects" / "p1").mkdir()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        for where in ("", "config"):
            for kind in ("file", "dir"):
                with self.subTest(where=where, kind=kind):
                    path = self.chat_home / where / "made-up-item"
                    path.write_text("x") if kind == "file" else path.mkdir()
                    why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
                    self.assertIn("made-up-item", why)
                    self.assertNotIn(str(self.tmp), why)
                    path.unlink() if kind == "file" else path.rmdir()
        extra = [self.chat_home / "stranger-a", self.chat_home / "stranger-b"]
        for path in extra:
            path.write_text("x")
        why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
        self.assertIn("stranger-a、stranger-b", why, "all the names are said, so one run shows them all")
        self.assertNotEqual(env.home_state(self.state)[0], "ok")
        for path in extra:
            path.unlink()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_the_projects_folder_is_looked_into_empty_project_folders_pass_and_nothing_else_does(self):
        self.make_home()
        projects = self.chat_home / "config" / "projects"
        projects.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "no project folder at all")
        (projects / "p-0001").mkdir()
        (projects / "p-0002").mkdir()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "project folders with nothing in them")
        bad = {
            "a name nobody knows": "p-0001/notes.txt",
            "a file where a project folder belongs": "stray-file",
            "hooks": "p-0001/hooks.json",
            "hooks in other letters": "p-0001/HOOKS.JSON",
            "rules": "p-0001/rules",
            "a rules file": "p-0001/rules.md",
            "workflows": "p-0002/workflows",
            "global workflows": "p-0002/global_workflows",
            "skills deep down": "p-0001/a/b/skills",
            "settings": "p-0001/settings.json",
            "a gemini file deep down": "p-0001/a/GEMINI.md",
            "an agents file": "p-0002/AGENTS.md",
            "an agent folder": "p-0002/.agents",
            "plugins": "p-0001/plugins",
        }
        for what, name in bad.items():
            for kind in ("file", "dir"):
                if what == "a file where a project folder belongs" and kind == "dir":
                    continue                                  # an empty folder is a project folder
                with self.subTest(what=what, kind=kind):
                    path = projects / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if kind == "file":
                        path.write_text("x")
                    else:
                        path.mkdir(exist_ok=True)
                    why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
                    self.assertIn(Path(name).name.casefold(), why.casefold())
                    self.assertNotIn(str(self.tmp), why, "the sentence does not print a path")
                    self.assertIn("projects/", why)
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
                    for left in sorted(projects.rglob("*"), key=lambda q: -len(q.parts)):
                        if left.name in ("a", "b") and left.is_dir() and not any(left.iterdir()):
                            left.rmdir()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "clean again")

    def test_a_link_in_the_projects_folder_and_a_projects_folder_that_is_a_link_or_a_file_are_refused(self):
        self.make_home()
        projects = self.chat_home / "config" / "projects"
        projects.mkdir(parents=True, exist_ok=True, mode=0o700)
        (projects / "p-0001").symlink_to(self.tmp)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        (projects / "p-0001").unlink()
        (projects / "p-0001").mkdir()
        (projects / "p-0001" / "ln").symlink_to(self.tmp)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        shutil.rmtree(projects)
        projects.symlink_to(self.tmp)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        projects.unlink()
        projects.write_text("a file")
        self.refused(env.check_chat_home, self.state, code="foreign_settings")

    def test_a_projects_folder_that_is_too_deep_or_too_full_is_refused(self):
        self.make_home()
        projects = self.chat_home / "config" / "projects"
        deep = projects / "p-0001" / "d1" / "d2" / "d3" / "d4" / "d5"
        deep.mkdir(parents=True, mode=0o700)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        shutil.rmtree(projects)
        projects.mkdir(mode=0o700)
        for i in range(env.PROJECTS_MAX_ENTRIES + 1):
            (projects / f"p-{i:05d}").mkdir()
        self.refused(env.check_chat_home, self.state, code="foreign_settings")

    def test_the_names_agy_1_5_3_really_made_are_all_accepted_in_their_places(self):
        self.make_home()
        real = {"antigravity-cli": ["annotations", "bin", "brain", "builtin", "cache", "conversation_summaries.db", "conversations",
                                   "crashes", "implicit", "installation_id", "jetbox_summaries_proto.pb", "jetski_state.pbtxt",
                                   "log", "settings.json"],
                "config": [".migrated", "config.json", "mcp_config.json", "projects"]}
        for top, names in real.items():
            for name in names:
                path = self.chat_home / top / name
                path.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
                if name in ("annotations", "bin", "brain", "builtin", "cache", "conversations", "crashes", "implicit", "log", "projects"):
                    path.mkdir(exist_ok=True)
                elif name != "settings.json":
                    path.write_text("{}" if name.endswith(".json") else "x")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_a_name_in_antigravity_cli_that_is_not_on_the_list_is_refused_by_name_and_so_is_a_forbidden_one_at_any_depth(self):
        self.make_home()
        cli = self.chat_home / "antigravity-cli"
        cli.mkdir(exist_ok=True, mode=0o700)
        (cli / "builtin" / "tools").mkdir(parents=True)
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        (cli / "made-up-top").write_text("x")
        self.assertIn("made-up-top", self.refused(env.check_chat_home, self.state, code="foreign_settings"))
        (cli / "made-up-top").unlink()
        for where in ("builtin/skills", "implicit/Workflows", "brain/a/b/c/hooks.json", "cache/rules.md", "bin/GEMINI.md",
                      "conversations/AGENTS.md", "log/plugins", "builtin/tools/settings.json", "implicit/mcp_config.json"):
            for kind in ("file", "dir"):
                with self.subTest(where=where, kind=kind):
                    path = cli / where
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("x") if kind == "file" else path.mkdir(exist_ok=True)
                    why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
                    self.assertIn(Path(where).name.casefold(), why.casefold())
                    self.assertIn("antigravity-cli/", why)
                    self.assertNotIn(str(self.tmp), why)
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "VBear's own settings.json is not what is looked for")

    def test_a_config_folder_that_is_a_link_or_a_file_is_refused(self):
        self.make_home()
        (self.chat_home / "config").symlink_to(self.tmp)
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        (self.chat_home / "config").unlink()
        (self.chat_home / "config").write_text("x")
        self.refused(env.check_chat_home, self.state, code="foreign_settings")

    def test_what_agy_makes_itself_is_fine(self):
        self.make_home()
        for rel in ("config/config.json", "config/.migrated", "antigravity-cli/conversations/c1.db", "antigravity-cli/log/a.log",
                    "antigravity-cli/builtin/some-tool/readme.txt", "antigravity-cli/conversation_summaries.db",
                    "antigravity-cli/jetski_state.pbtxt", "antigravity-cli/installation_id"):
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
        self.write_private(self.chat_home / "antigravity-cli" / "conversation_summaries.db", "x" * 4096)
        self.assertEqual(env.HOME_LIMIT, 512 << 20)
        with mock.patch.object(env, "HOME_LIMIT", 1024):
            self.refused(env.check_chat_home, self.state, code="too_big")
            self.assertEqual(env.check_chat_home(self.state, size=False), self.chat_home)
            self.assertEqual(env.home_state(self.state)[0], "refused")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_a_link_inside_the_folder_cannot_be_counted_so_it_refuses(self):
        self.make_home()
        (self.chat_home / "antigravity-cli").mkdir(mode=0o700)
        (self.chat_home / "antigravity-cli" / "cache").symlink_to(self.tmp)
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
        cases = {"absolute": str(outside), "absolute file": str(outside / "decoy.txt"), "relative": "../../../outside",
                 "dangling": "../../../nothing-at-all", "root": "/"}
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


CANARY = "CANARY-NOT-A-REAL-SECRET-0000"
FAKE_AGY = r'''#!%(py)s
import os, sys, time
here = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(here, "calls.log"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + " | cwd=" + os.getcwd() + " | env=" + ",".join(sorted(os.environ)) + "\n")
sys.stderr.write(%(canary)r + "\n")
time.sleep(%(sleep)r)
sys.stdout.buffer.write(%(out)r)
sys.exit(%(code)d)
'''


class BinaryCase(TempCase):
    def install_agy(self, version="1.5.3", *, out=None, code=0, sleep=0.0, folder=None, name="agy"):
        folder = Path(folder) if folder else self.bindir
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        out = (version + "\n").encode() if out is None else out
        path.write_text(FAKE_AGY % {"py": sys.executable, "canary": CANARY, "sleep": sleep, "out": out, "code": code})
        path.chmod(0o700)
        return path

    def calls(self, folder=None):
        log = Path(folder or self.bindir) / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def refused(self, fn, *args, code, **kwargs):
        with self.assertRaises(env.AgyRefused) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        self.assertNotIn(str(self.tmp), str(ctx.exception), "no path in the sentence")
        self.assertNotIn(CANARY, str(ctx.exception), "nothing AGY printed in the sentence")
        return ctx.exception

    def locate(self, folder=None):
        return env.locate_binary(str(folder or self.bindir))

    def pin(self, folder=None, **kw):
        return env.pinned_binary(str(folder or self.bindir), **kw)


class LocateTests(BinaryCase):
    def test_the_file_is_found_on_the_given_path_only(self):
        self.refused(self.locate, code="not_installed")
        self.install_agy()
        self.assertEqual(self.locate(), os.path.realpath(self.bindir / "agy"))
        self.refused(env.locate_binary, str(self.tmp / "elsewhere") + os.pathsep + "", code="not_installed")
        self.assertEqual(env.locate_binary(str(self.tmp / "elsewhere") + os.pathsep + str(self.bindir)),
                         os.path.realpath(self.bindir / "agy"), "the path is searched in order")

    def test_the_default_search_path_is_the_daemons(self):
        self.install_agy(folder=self.tmp / "default-bin")
        with mock.patch("vbear.runtime.daemon.cli_search_path", return_value=str(self.tmp / "default-bin")):
            self.assertEqual(env.locate_binary(), os.path.realpath(self.tmp / "default-bin" / "agy"))

    def test_only_a_file_named_agy_that_can_run_counts(self):
        self.install_agy(name="agy-other")
        self.refused(self.locate, code="not_installed")
        (self.bindir / "agy").write_text("#!/bin/sh\n")
        (self.bindir / "agy").chmod(0o600)                                    # not executable
        self.refused(self.locate, code="not_installed")
        (self.bindir / "agy").unlink()
        (self.bindir / "agy").mkdir()
        self.refused(self.locate, code="not_installed")

    def test_a_link_is_followed_to_the_real_file_and_that_is_what_is_returned(self):
        real = self.install_agy(folder=self.tmp / "versions", name="agy-1.5.3")
        (self.bindir / "agy").symlink_to(real)
        self.assertEqual(self.locate(), os.path.realpath(real))

    def test_a_file_that_others_can_change_is_refused(self):
        path = self.install_agy()
        path.chmod(0o722)
        self.refused(self.locate, code="unsafe_binary")
        path.chmod(0o770)
        self.refused(self.locate, code="unsafe_binary")
        path.chmod(0o700)
        self.assertTrue(self.locate())

    def test_a_folder_on_the_way_that_others_can_change_is_refused_wherever_it_is(self):
        deep = self.tmp / "a" / "b"
        self.install_agy(folder=deep)
        for folder in (self.tmp / "a", deep):
            for mode in (0o770, 0o707, 0o777):
                with self.subTest(folder=folder.name, mode=oct(mode)):
                    os.chmod(folder, mode)
                    self.refused(self.locate, deep, code="unsafe_binary")
                    os.chmod(folder, 0o700)
        self.assertTrue(self.locate(deep))
        # the link's own folder is on the way too, as well as the folder of the file it ends at
        real = self.install_agy(folder=self.tmp / "versions")
        (self.bindir / "agy").symlink_to(real)
        os.chmod(self.tmp / "versions", 0o770)
        self.refused(self.locate, code="unsafe_binary")
        os.chmod(self.tmp / "versions", 0o700)

    def test_a_sticky_folder_is_the_only_writable_one_allowed_and_only_when_a_trusted_owner_has_it(self):
        self.install_agy()
        os.chmod(self.tmp, 0o1777)                                            # like /tmp itself
        self.assertTrue(self.locate())
        os.chmod(self.tmp, 0o777)
        self.refused(self.locate, code="unsafe_binary")
        os.chmod(self.tmp, 0o700)

    def test_a_file_or_folder_of_someone_else_is_refused(self):
        self.install_agy()
        real_uid = os.getuid()
        with mock.patch.object(env, "_uid", return_value=real_uid + 1):
            self.refused(self.locate, code="unsafe_binary")
        self.assertTrue(self.locate())

    def test_the_cli_identity_is_the_six_numbers_every_launch_manifest_has(self):
        from vbear.runtime import agent_sessions
        path = self.install_agy()
        real = os.path.realpath(path)
        identity = env.cli_identity(real)
        self.assertEqual(identity, agent_sessions.binary_identity(real))
        self.assertEqual(len(identity), 6)
        self.assertTrue(env.unchanged(real, identity))
        path.write_text(path.read_text() + "# changed\n")
        self.assertFalse(env.unchanged(real, identity), "a changed file is not the one that was checked")
        path.unlink()
        self.assertFalse(env.unchanged(real, identity))
        self.assertFalse(env.unchanged(real, [1, 2, 3]))
        self.assertFalse(env.unchanged(real, None))


class PinnedTests(BinaryCase):
    def setUp(self):
        super().setUp()
        self.record_pass()

    def test_a_known_verified_version_is_pinned_with_its_identity(self):
        path = self.install_agy()
        pinned = self.pin()
        self.assertEqual((pinned.binary, pinned.version), (os.path.realpath(path), "1.5.3"))
        self.assertEqual(pinned.identity, env.cli_identity(pinned.binary))
        self.assertEqual(self.calls(), ["--version | cwd=/ | env=" + self.calls()[0].split("env=")[1]],
                         "one run, with exactly --version, from the root folder")

    def test_the_version_is_read_from_a_run_with_a_safe_environment(self):
        self.install_agy()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x", "ANTIGRAVITY_PERM_GRANTS": "x", "GOOGLE_API_KEY": "x",
                                          "OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "x"}):
            self.pin()
        keys = set(self.calls()[0].split("env=")[1].split(","))
        for bad in ("GEMINI_API_KEY", "ANTIGRAVITY_PERM_GRANTS", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertNotIn(bad, keys)
        self.assertLessEqual(keys, {"HOME", "USER", "LOGNAME", "PATH", "TERM", "LANG", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"})

    def test_anything_but_exactly_one_version_line_is_unreadable(self):
        cases = [b"agy 1.5.3\n", b"v1.5.3\n", b"1.5.3 (build 7)\n", b"1.5.3\n1.5.3\n", b"1.5.3\n\n", b"\n1.5.3\n", b" 1.5.3\n",
                 b"1.5\n", b"1.5.3.1\n", b"", b"\n", b"\xff\xfe\n", b"1.5.3\x00\n", b"x" * 100000]
        for out in cases:
            with self.subTest(out=out[:30]):
                self.install_agy(out=out)
                self.refused(self.pin, code="version_unreadable")
        self.install_agy(out=b"1.5.3")                                        # no final newline is fine: it is still one line
        self.assertEqual(self.pin().version, "1.5.3")

    def test_a_program_that_fails_or_does_not_finish_is_unreadable(self):
        self.install_agy(code=1)
        self.refused(self.pin, code="version_unreadable")
        self.install_agy(sleep=5.0)
        with mock.patch.object(env, "STATUS_TIMEOUT_S", 0.5):
            self.refused(self.pin, code="version_unreadable")

    def test_a_version_not_in_the_table_is_unsupported_and_the_sentence_lists_what_is(self):
        for version in ("1.5.4", "1.5.2", "2.0.0", "0.0.1"):
            with self.subTest(version=version):
                self.install_agy(version)
                exc = self.refused(self.pin, code="unsupported")
                self.assertEqual(exc.version, version)
                self.assertIn(version, str(exc))
                self.assertIn("1.5.3", str(exc))

    def test_a_known_version_that_never_passed_the_check_is_unverified(self):
        self.install_agy()
        (self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).unlink()
        exc = self.refused(self.pin, code="unverified")
        self.assertEqual(exc.version, "1.5.3")
        self.assertIn("驗證", str(exc))
        self.assertIn("Google 方案", str(exc))
        self.record_pass("1.5.2")                                             # another version passed: still not this one
        self.refused(self.pin, code="unverified")
        self.assertEqual(self.pin(verified=("1.5.3",)).version, "1.5.3", "the verified list can be given")

    def test_a_new_version_is_checked_again_at_the_next_pin(self):
        path = self.install_agy()
        self.assertEqual(self.pin().version, "1.5.3")
        self.install_agy("1.5.4")                                             # AGY updated itself
        self.refused(self.pin, code="unsupported")
        self.assertEqual(path.read_text().count("1.5.4"), 1)

    def test_the_known_versions_are_the_ones_the_plan_names(self):
        self.assertEqual(env.KNOWN_VERSIONS, ("1.5.3",))
        with mock.patch.object(env, "KNOWN_VERSIONS", ("1.5.3", "1.5.4")):
            self.install_agy("1.5.4")
            self.record_pass("1.5.4")
            self.assertEqual(self.pin().version, "1.5.4")


class StatusTests(BinaryCase):
    KEYS = {"state", "installed", "version", "verified", "shared_verified", "admin_policy_ok", "hooks_ok", "why",
            "verified_versions"}

    def status(self, **kw):
        kw.setdefault("search_path", str(self.bindir))
        return env.status(self.state, **kw)

    def ready(self):
        self.install_agy()
        self.record_pass()

    def assert_state(self, state, *, why=True, **fields):
        out = self.status()
        self.assertEqual(out["state"], state, out)
        self.assertEqual(set(out), self.KEYS)
        self.assertEqual(bool(out["why"]), why, out)
        for k, v in fields.items():
            self.assertEqual(out[k], v, (k, out))
        text = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(str(self.tmp), text, "no path in the answer")
        self.assertNotIn(CANARY, text, "nothing AGY printed in the answer")
        return out

    def test_not_installed(self):
        out = self.assert_state("not_installed", installed=False, version=None, verified=False)
        self.assertIn("開始設定", out["why"])

    def test_ready(self):
        self.ready()
        self.assert_state("ready", why=False, installed=True, version="1.5.3", verified=True, admin_policy_ok=True,
                          hooks_ok=True, shared_verified=False, verified_versions=["1.5.3"])
        self.assertFalse((self.state / "agy-chat-home").exists(), "a look makes nothing")
        self.record_pass(shared=True)
        self.assert_state("ready", why=False, shared_verified=True)

    def test_a_file_that_is_not_safe_or_prints_the_wrong_thing_is_version_unreadable(self):
        path = self.install_agy(out=b"agy 1.5.3\n")
        self.assert_state("version_unreadable", installed=True, verified=False)
        self.install_agy()
        path.chmod(0o722)
        self.assert_state("version_unreadable", installed=True)

    def test_unsupported_and_unverified(self):
        self.install_agy("1.5.4")
        self.record_pass()
        out = self.assert_state("unsupported", installed=True, version="1.5.4", verified=False)
        self.assertIn("1.5.3", out["why"])
        self.install_agy()
        (self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).unlink()
        out = self.assert_state("unverified", installed=True, version="1.5.3", verified=False, verified_versions=[])
        self.assertIn("驗證", out["why"])

    def test_policy_hooks_and_folder_in_that_order(self):
        self.ready()
        (self.state / "agy-chat-home").mkdir(mode=0o700)
        (self.state / "agy-chat-home" / "AGENTS.md").write_text("x")
        self.write_private(self.home / ".agents" / "hooks.json", "{}")
        (self.policy_root / "etc" / "antigravity").mkdir(parents=True)
        out = self.assert_state("policy", admin_policy_ok=False, hooks_ok=None, verified=True)
        self.assertIn("管理員", out["why"])
        shutil.rmtree(self.policy_root / "etc")
        out = self.assert_state("hooks", admin_policy_ok=True, hooks_ok=False)
        self.assertIn("hooks.json", out["why"])
        (self.home / ".agents" / "hooks.json").unlink()
        out = self.assert_state("folder", hooks_ok=True)
        self.assertIn("AGENTS.md", out["why"])
        (self.state / "agy-chat-home" / "AGENTS.md").unlink()
        self.assert_state("ready", why=False)

    def test_a_hooks_file_that_cannot_be_told_is_hooks_too(self):
        self.ready()
        (self.home / ".agents").write_text("a file")
        out = self.assert_state("hooks", hooks_ok=False)
        self.assertIn("無法確認", out["why"])

    def test_the_policy_root_can_be_given(self):
        self.ready()
        other = self.tmp / "other-root"
        (other / "etc" / "antigravity").mkdir(parents=True)
        out = env.status(self.state, search_path=str(self.bindir), root=str(other))
        self.assertEqual(out["state"], "policy")
        self.assertEqual(env.POLICY_ROOT, str(self.policy_root))

    def test_the_answer_is_cached_for_a_few_seconds_and_can_be_forced_or_dropped(self):
        self.ready()
        with mock.patch.object(env, "CACHE_TTL_S", 30.0):
            self.assertEqual(self.status()["state"], "ready")
            self.assertEqual(len(self.calls()), 1)
            (self.home / ".agents").mkdir()
            (self.home / ".agents" / "hooks.json").write_text("{}")
            self.assertEqual(self.status()["state"], "ready", "from the cache")
            self.assertEqual(len(self.calls()), 1)
            self.assertEqual(self.status(force=True)["state"], "hooks")
            self.assertEqual(len(self.calls()), 2)
            (self.home / ".agents" / "hooks.json").unlink()
            env.invalidate()
            self.assertEqual(self.status()["state"], "ready")
            first = self.status()
            first["verified_versions"].append("9.9.9")
            self.assertEqual(self.status()["verified_versions"], ["1.5.3"], "a copy is returned, not the cached list")

    def test_no_real_agy_is_run_or_read_when_nothing_is_given(self):
        # self.tmp/no-bin does not exist: the default search path finds nothing
        out = env.status(self.state)
        self.assertEqual(out["state"], "not_installed")


if __name__ == "__main__":
    unittest.main()
