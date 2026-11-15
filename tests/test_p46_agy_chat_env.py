"""P46-2 (ADR 0012): what the AGY chat needs before any process starts: the record of the versions that passed the chat
check, VBear's own settings folder, the checks of the folders AGY would read, the pinned binary and the one answer
"may this Mac chat with AGY". Synthetic HOME and state; the "agy" is a small script that prints a version and nothing
else. No real AGY is looked for, started or read, and the stand-in HOME holds decoys that fail the test when they are read."""

from __future__ import annotations

import hashlib
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
            "an underscore agents folder": "p-0002/_agents",
            "an underscore agent folder deep down": "p-0001/a/_AGENT",
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
                                   "log", "persistent_terminals", "settings.json"],
                "config": [".migrated", "config.json", "mcp_config.json", "projects"]}
        for top, names in real.items():
            for name in names:
                path = self.chat_home / top / name
                path.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
                if name in ("annotations", "bin", "brain", "builtin", "cache", "conversations", "crashes", "implicit", "log", "projects",
                            "persistent_terminals"):
                    path.mkdir(exist_ok=True)
                elif name != "settings.json":
                    path.write_text("{}" if name.endswith(".json") else "x")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_the_sqlite_side_files_next_to_the_summaries_db_are_fine_on_the_second_start_and_nothing_like_them_is(self):
        self.make_home()
        cli = self.chat_home / "antigravity-cli"
        self.write_private(cli / "conversation_summaries.db", "x")
        for side in ("-shm", "-wal", "-journal"):                    # left by the first process (the sixth real run saw -shm and -wal)
            self.write_private(cli / ("conversation_summaries.db" + side), "x")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "a second start in the same folder")
        for letters in ("conversation_summaries.db-WAL", "Conversation_Summaries.db-wal", "CONVERSATION_SUMMARIES.DB-SHM"):
            with self.assertRaises(env.AgyRefused, msg=letters):        # (a disk that folds letters would not show the difference)
                env._refuse_strangers([letters], env.CREATED_CLI, exact=True)
        for stranger in ("conversation_summaries.db-wal2",
                         "conversation_summaries.db-shm.bak", "other.db-wal", "conversation_summaries-wal", "jetski_state.pbtxt-wal"):
            with self.subTest(stranger=stranger):
                self.write_private(cli / stranger, "x")
                self.assertIn(stranger, self.refused(env.check_chat_home, self.state, code="foreign_settings"))
                (cli / stranger).unlink()
        for elsewhere in (self.chat_home / "conversation_summaries.db-wal", self.chat_home / "config" / "conversation_summaries.db-wal"):
            with self.subTest(elsewhere=str(elsewhere.relative_to(self.chat_home))):
                self.write_private(elsewhere, "x")
                self.refused(env.check_chat_home, self.state, code="foreign_settings")
                elsewhere.unlink()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_a_name_in_antigravity_cli_that_is_not_on_the_list_is_refused_by_name_and_so_is_a_forbidden_one_at_any_depth(self):
        self.make_home()
        cli = self.chat_home / "antigravity-cli"
        cli.mkdir(exist_ok=True, mode=0o700)
        (cli / "builtin").mkdir(parents=True)
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        (cli / "made-up-top").write_text("x")
        self.assertIn("made-up-top", self.refused(env.check_chat_home, self.state, code="foreign_settings"))
        (cli / "made-up-top").unlink()
        for where in ("implicit/Workflows", "brain/a/b/c/hooks.json", "cache/rules.md", "bin/GEMINI.md",
                      "conversations/AGENTS.md", "log/plugins", "implicit/mcp_config.json"):
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

    def hashed(self, text="x", only=None):
        """Patch the table's pinned hashes with the hash of ``text`` for every built-in file that counts as executable (or ``only``)."""
        paths = only if only is not None else [p for p in env.builtin_table().paths if env.builtin_executable_like(p)]
        self.pin_hashes({p: hashlib.sha256(text.encode()).hexdigest() for p in paths})

    def pin_hashes(self, hashes, versions=None):
        """Replace the pinned hashes of the built-in tables (of ``versions``, else of every known version) with ``hashes``: path -> hex."""
        tables = {v: (t._replace(sha=dict(hashes)) if versions is None or v in versions else t) for v, t in env.BUILTIN_TABLES.items()}
        patch = mock.patch.dict(env.BUILTIN_TABLES, tables)
        patch.start()
        self.addCleanup(patch.stop)

    def make_builtin(self, *paths):
        base = self.chat_home / "antigravity-cli" / "builtin"
        for rel in paths:
            path = base / rel
            if any(other.startswith(rel + "/") for other in env.builtin_table().paths):          # a folder: something is below it
                path.mkdir(parents=True, exist_ok=True)
            else:
                self.write_private(path, "x")
        return base

    def test_the_built_in_content_of_agy_passes_only_by_the_exact_paths_of_the_table(self):          # (R1: every known version's table, not only the newest)
        for version in env.BUILTIN_TABLES:
            with self.subTest(version=version):
                shutil.rmtree(self.chat_home, ignore_errors=True)
                self._the_built_in_content_of_agy_passes_only_by_the_exact_paths_of_the_table(version)

    def _the_built_in_content_of_agy_passes_only_by_the_exact_paths_of_the_table(self, version):
        env.ensure_chat_home(self.state, version=version)
        self.assertEqual(len(env.builtin_table(version).paths), {"1.5.3": 62, "1.5.6": 62, "1.5.7": 64, "1.5.8": 64}[version],          # (1.5.7: one more skill, the folder and its SKILL.md; 1.5.8: the same paths)
                         "every path of the real AGY 1.5.3 (the fourth real run) and of the folders a real 1.5.7 wrote, one by one")
        for name in (".checksum", ".manifest", "keep.txt", "plugins/swarm/plugin.json", "plugins/swarm/sidecars/swarm_board/main.mjs",
                     "skills/agy-customizations/docs/skills.md", "skills/agy-customizations/docs/rules.md", "skills/native_swarm/logo.svg"):
            self.assertIn(name, env.builtin_table(version).paths)
        self.assertEqual(sum(1 for p in env.builtin_table(version).paths if p.startswith("skills/") and p.count("/") == 1),
                         {"1.5.3": 13, "1.5.6": 13, "1.5.7": 14, "1.5.8": 14}[version], "13 skill folders (14 in 1.5.7 and 1.5.8)")
        self.assertFalse(any(set(p) & set("*?[") for p in env.builtin_table(version).paths), "no pattern, only names")
        self.hashed()
        for rel in sorted(env.builtin_table(version).paths):                  # all of the table, though named skills, plugins, hooks and rules
            self.make_builtin(rel)
        self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)
        base = self.chat_home / "antigravity-cli" / "builtin"
        for rel in ("skills/made-up-skill", "skills/agy-customizations/hooks", "skills/agy-customizations/docs/mcp_config.json",
                    "plugins/made-up", "hooks.json", "made-up.txt",
                    "skills/agy-customizations/docs/skills.md.bak"):
            for kind in ("file", "dir"):
                with self.subTest(rel=rel, kind=kind):
                    path = base / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("x") if kind == "file" else path.mkdir(exist_ok=True)
                    why = self.refused(env.check_chat_home, self.state, version=version, code="foreign_settings")
                    self.assertIn("antigravity-cli/builtin/" + rel, why)
                    self.assertNotIn(str(self.tmp), why)
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
        self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)

    def test_a_built_in_file_that_can_run_is_refused_until_its_hash_is_pinned_whatever_its_name(self):          # (R1: every known version's table, not only the newest)
        for version in env.BUILTIN_TABLES:
            with self.subTest(version=version):
                shutil.rmtree(self.chat_home, ignore_errors=True)
                self._a_built_in_file_that_can_run_is_refused_until_its_hash_is_pinned_whatever_its_name(version)

    def _a_built_in_file_that_can_run_is_refused_until_its_hash_is_pinned_whatever_its_name(self, version):
        env.ensure_chat_home(self.state, version=version)
        self.pin_hashes({})                                           # (the case of a file nobody pinned: the tables have them all now)
        runnable = [p for p in env.builtin_table(version).paths if env.builtin_executable_like(p)]
        self.assertIn("plugins/swarm/plugin.json", runnable)
        self.assertIn("plugins/swarm/sidecars/swarm_board/main.mjs", runnable)
        self.assertIn("plugins/swarm/sidecars/swarm_board/narrator_bootstrap.js", runnable)
        self.assertIn("plugins/swarm/sidecars/swarm_board/sidecar.json", runnable)
        self.assertIn("plugins/swarm/sidecars/swarm_board/package.json", runnable)
        self.assertNotIn("skills/agy-customizations/docs/skills.md", runnable)
        for rel in ("a.js", "a.mjs", "a.cjs", "a.sh", "a.py", "A.JS", "plugin.json", "sidecar.json", "package.json"):
            self.assertTrue(env.builtin_executable_like(rel), rel)
        for rel in runnable:
            with self.subTest(rel=rel):
                self.make_builtin(rel)
                why = self.refused(env.check_chat_home, self.state, version=version, code="foreign_settings")
                self.assertIn("antigravity-cli/builtin/" + rel, why)
                shutil.rmtree(self.chat_home / "antigravity-cli" / "builtin")
        self.make_builtin("skills/agy-customizations/docs/skills.md", "keep.txt", ".manifest")
        self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home, "documents pass by their exact names")

    def test_the_table_pins_every_built_in_file_and_no_folder_with_a_real_sha256(self):
        for version, table in env.BUILTIN_TABLES.items():
            with self.subTest(version=version):
                files = {p for p in table.paths if p not in table.dirs}
                count = {"1.5.3": 41, "1.5.6": 41, "1.5.7": 42, "1.5.8": 42}[version]          # (1.5.7 has one more skill; 1.5.8 the same files)
                self.assertEqual(len(files), count)
                self.assertEqual(set(table.sha), files, "every file of the real AGY (the fifth real run of 1.5.3; the folders a real 1.5.6 and a real 1.5.7 wrote), not only the ones that run")
                for rel, digest in table.sha.items():
                    self.assertRegex(digest, r"^[0-9a-f]{64}$", rel)
                self.assertEqual(len(set(table.sha.values())), count - 1, "the two logo.svg files share a hash, and nothing else does")
                self.assertEqual(table.sha["keep.txt"], hashlib.sha256(b"").hexdigest(), "keep.txt is empty")

    def test_with_the_real_table_a_file_of_any_kind_with_other_bytes_is_refused_by_its_path(self):          # (R1: every known version's table, not only the newest)
        for version in env.BUILTIN_TABLES:
            with self.subTest(version=version):
                shutil.rmtree(self.chat_home, ignore_errors=True)
                self._with_the_real_table_a_file_of_any_kind_with_other_bytes_is_refused_by_its_path(version)

    def _with_the_real_table_a_file_of_any_kind_with_other_bytes_is_refused_by_its_path(self, version):
        env.ensure_chat_home(self.state, version=version)
        for rel in sorted(p for p in env.builtin_table(version).paths if p not in env.builtin_table(version).dirs):
            with self.subTest(rel=rel):
                base = self.make_builtin(rel)
                (base / rel).write_text("other bytes")
                self.assertIn("antigravity-cli/builtin/" + rel, self.refused(env.check_chat_home, self.state, version=version, code="foreign_settings"))
                shutil.rmtree(base)

    def test_with_the_real_table_the_right_bytes_pass(self):          # (R1: every known version's table, not only the newest)
        for version in env.BUILTIN_TABLES:
            with self.subTest(version=version):
                shutil.rmtree(self.chat_home, ignore_errors=True)
                self._with_the_real_table_the_right_bytes_pass(version)

    def _with_the_real_table_the_right_bytes_pass(self, version):
        env.ensure_chat_home(self.state, version=version)
        base = self.make_builtin("keep.txt")                          # the one file whose bytes are known: it is empty
        (base / "keep.txt").write_bytes(b"")
        self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)

    def test_a_pinned_hash_must_match_and_a_file_that_can_run_passes_only_with_the_right_one(self):
        self.make_home()
        rel = "plugins/swarm/sidecars/swarm_board/main.mjs"
        self.hashed("made-up", only=[rel])
        path = self.make_builtin(rel) / rel
        path.write_text("made-up")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        path.write_text("made-up!")                                  # changed by one byte
        self.assertIn(rel, self.refused(env.check_chat_home, self.state, code="foreign_settings"))
        path.write_text("")
        self.refused(env.check_chat_home, self.state, code="foreign_settings")
        path.unlink()
        path.mkdir()                                                  # a folder where the pinned file belongs
        self.refused(env.check_chat_home, self.state, code="foreign_settings")

    # ---- P56-1: the built-in table is read for the AGY version that is about to start, and a hash any known version pins is let through
    def two_versions(self, old="old", new="new"):
        """Two made-up tables with the real paths: 1.5.3 pins the hash of ``old`` and 1.5.6 the hash of ``new`` for every file that can run
        (the real hashes cannot be made from here, and the path table is the point)."""
        paths = [p for p in env.builtin_table().paths if env.builtin_executable_like(p)]
        tables = {"1.5.3": env.BUILTIN_TABLES["1.5.3"]._replace(sha={p: hashlib.sha256(old.encode()).hexdigest() for p in paths}),
                  "1.5.6": env.BUILTIN_TABLES["1.5.6"]._replace(sha={p: hashlib.sha256(new.encode()).hexdigest() for p in paths})}
        patch = mock.patch.dict(env.BUILTIN_TABLES, tables)
        patch.start()
        self.addCleanup(patch.stop)
        return paths

    def test_a_folder_an_older_known_agy_wrote_still_passes_when_a_newer_one_is_about_to_start_and_the_other_way_round(self):
        self.make_home()
        paths = self.two_versions()
        base = self.make_builtin(*paths)
        for rel in paths:
            (base / rel).write_text("old")                              # what 1.5.3 wrote
        for version in ("1.5.3", "1.5.6", None):
            with self.subTest(version=version):
                self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)
        self.assertEqual(env.home_state(self.state, version="1.5.6"), ("ok", ""))
        for rel in paths:
            (base / rel).write_text("new")                              # what 1.5.6 wrote
        for version in ("1.5.3", "1.5.6"):
            with self.subTest(version=version):
                self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)
        (base / paths[0]).write_text("old")                             # some of each (AGY rewrote only part of the folder)
        self.assertEqual(env.check_chat_home(self.state, version="1.5.6"), self.chat_home)

    def test_a_hash_that_no_known_version_pins_is_refused_for_every_version_and_named(self):
        self.make_home()
        paths = self.two_versions()
        base = self.make_builtin(*paths)
        for rel in paths:
            (base / rel).write_text("old")
        victim = "plugins/swarm/sidecars/swarm_board/main.mjs"
        (base / victim).write_text("something else")
        for version in ("1.5.3", "1.5.6"):
            with self.subTest(version=version):
                self.assertIn("antigravity-cli/builtin/" + victim, self.refused(env.check_chat_home, self.state, code="foreign_settings",
                                                                               version=version))
        (base / victim).write_text("")
        self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.6")

    def test_a_file_that_can_run_with_no_hash_in_any_table_is_refused_whatever_version_wrote_it(self):
        """The old version's hash is no free pass: only the hash of a file of AGY's, in some table, at that very path."""
        self.make_home()
        paths = self.two_versions()
        victim = "plugins/swarm/sidecars/swarm_board/hive.js"
        tables = {v: t._replace(sha={p: h for p, h in t.sha.items() if p != victim}) for v, t in env.BUILTIN_TABLES.items()}
        patch = mock.patch.dict(env.BUILTIN_TABLES, tables)
        patch.start()
        self.addCleanup(patch.stop)
        base = self.make_builtin(victim)
        for text in ("old", "new", "anything"):
            (base / victim).write_text(text)
            self.assertIn(victim, self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.6"))
        # and a hash another version pins at ANOTHER path does not pass at this one
        other = "plugins/swarm/sidecars/swarm_board/main.mjs"
        tables = {v: t._replace(sha={**t.sha, victim: hashlib.sha256(b"belongs-to-main").hexdigest(),
                                     other: hashlib.sha256(b"belongs-to-main").hexdigest()}) for v, t in env.BUILTIN_TABLES.items()}
        with mock.patch.dict(env.BUILTIN_TABLES, tables):
            (base / victim).write_text("old")
            self.assertIn(victim, self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.6"))

    def test_the_path_table_is_the_one_of_the_version_about_to_start_and_matches_exactly(self):
        self.make_home()
        keep = "skills/native_swarm/logo.svg"
        tables = {v: t._replace(sha={}) for v, t in env.BUILTIN_TABLES.items()}
        tables["1.5.6"] = tables["1.5.6"]._replace(paths=frozenset(p for p in tables["1.5.6"].paths if p != keep))
        patch = mock.patch.dict(env.BUILTIN_TABLES, tables)
        patch.start()
        self.addCleanup(patch.stop)
        self.make_builtin(keep)
        self.assertIn(keep, self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.6"),
                      "a path only the older table has is not let in for the newer version")
        self.assertEqual(env.check_chat_home(self.state, version="1.5.3"), self.chat_home)

    # ---- v0.25.5: AGY 1.5.7's path table is its own (one skill more), and a start reads the table of the version that is about to start
    NEW_SKILL = "skills/mcp-app-development"
    NEW_SKILL_FILE = "skills/mcp-app-development/SKILL.md"

    def test_the_real_path_tables_of_1_5_6_and_1_5_7_differ_by_exactly_the_new_skill(self):
        old, new = env.BUILTIN_TABLES["1.5.6"], env.BUILTIN_TABLES["1.5.7"]
        self.assertEqual(new.paths - old.paths, {self.NEW_SKILL, self.NEW_SKILL_FILE})
        self.assertEqual(old.paths - new.paths, frozenset())
        self.assertEqual(new.dirs - old.dirs, {self.NEW_SKILL})
        self.assertEqual(env.BUILTIN_TABLES["1.5.3"].paths, old.paths, "1.5.6's table is still 1.5.3's, untouched")
        self.assertEqual(env.builtin_table().version, "1.5.8", "no version means the newest known one")          # (v0.25.6: 1.5.8)
        self.assertEqual(env.KNOWN_VERSIONS, ("1.5.3", "1.5.6", "1.5.7", "1.5.8"))

    def test_a_folder_with_the_new_skill_passes_for_1_5_7_and_is_refused_for_1_5_6_and_1_5_3(self):
        """The path table is the one of the version about to start: the new skill is on 1.5.7's table only, so it is a stranger to the others (named in the sentence)."""
        self.make_home()
        self.pin_hashes({})                                            # (no pinned hash: the point is the path; the new file is a document)
        self.make_builtin(self.NEW_SKILL_FILE)
        self.assertTrue((self.chat_home / "antigravity-cli" / "builtin" / self.NEW_SKILL / "SKILL.md").is_file())
        self.assertEqual(env.check_chat_home(self.state, version="1.5.7"), self.chat_home)
        self.assertEqual(env.check_chat_home(self.state), self.chat_home, "the newest version is 1.5.8, which has the same paths as 1.5.7")
        self.assertEqual(env.home_state(self.state, version="1.5.7"), ("ok", ""))
        for version in ("1.5.6", "1.5.3"):
            with self.subTest(version=version):
                why = self.refused(env.check_chat_home, self.state, code="foreign_settings", version=version)
                self.assertIn("antigravity-cli/builtin/" + self.NEW_SKILL, why)
                self.assertNotIn(str(self.tmp), why)
                self.assertEqual(env.home_state(self.state, version=version)[0], "refused")

    def test_a_folder_1_5_6_wrote_passes_for_1_5_7_a_path_the_table_has_and_the_folder_lacks_is_not_a_fault(self):
        self.make_home()
        self.pin_hashes({})
        self.make_builtin("keep.txt", "skills/automation/SKILL.md")      # what 1.5.6 wrote: no new skill
        for version in ("1.5.3", "1.5.6", "1.5.7", None):
            with self.subTest(version=version):
                self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)

    def test_the_new_skills_file_passes_only_with_the_hash_1_5_7_pins_and_a_stranger_beside_it_is_refused(self):
        self.make_home()
        base = self.make_builtin(self.NEW_SKILL_FILE)
        target = base / self.NEW_SKILL_FILE
        self.assertEqual(env.pinned_hashes(self.NEW_SKILL_FILE), frozenset({env.BUILTIN_TABLES[v].sha[self.NEW_SKILL_FILE] for v in ("1.5.7", "1.5.8")}),
                         "only 1.5.7 and 1.5.8 pin it (two values: 1.5.8 changed the file), so only their bytes pass")
        target.write_text("other bytes")
        self.assertIn("antigravity-cli/builtin/" + self.NEW_SKILL_FILE, self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.7"))
        target.write_bytes(b"")
        self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.7")
        target.unlink()
        self.pin_hashes({})
        self.write_private(base / self.NEW_SKILL / "extra.md", "x")     # a name beside it that no table has
        self.assertIn("extra.md", self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.7"))

    def test_the_hash_of_a_file_that_only_1_5_7_changed_passes_for_every_known_version_at_that_path_and_no_other(self):
        """ADR 0018: the hashes are shared among the known versions at one path (so a folder an older AGY wrote is not refused after AGY updated itself), the paths are not."""
        old, new = env.BUILTIN_TABLES["1.5.6"], env.BUILTIN_TABLES["1.5.7"]
        rel = "plugins/swarm/sidecars/swarm_board/hive.js"
        self.assertNotEqual(old.sha[rel], new.sha[rel])
        self.assertEqual(env.pinned_hashes(rel), frozenset({env.BUILTIN_TABLES["1.5.3"].sha[rel], old.sha[rel], new.sha[rel]}))
        self.assertNotIn(new.sha[rel], env.pinned_hashes("plugins/swarm/sidecars/swarm_board/main.mjs"), "a hash of another path is no pass")
        self.assertEqual(env.pinned_hashes("skills/mcp-app-development/SKILL.md") & env.pinned_hashes("keep.txt"), frozenset())

    # ---- v0.25.6: AGY 1.5.8 has 1.5.7's paths (nothing added, nothing gone) and two files with new bytes; the table is still the one of the version about to start
    def test_the_real_path_tables_of_1_5_7_and_1_5_8_are_the_same_and_1_5_6s_still_lacks_the_skill(self):
        old, new = env.BUILTIN_TABLES["1.5.7"], env.BUILTIN_TABLES["1.5.8"]
        self.assertEqual(new.paths, old.paths)
        self.assertEqual(new.dirs, old.dirs)
        self.assertEqual(len(new.paths), 64)
        self.assertEqual(set(new.sha), set(old.sha))
        self.assertEqual(sorted(p for p in new.sha if new.sha[p] != old.sha[p]), [".checksum", self.NEW_SKILL_FILE])
        self.assertEqual(env.BUILTIN_TABLES["1.5.6"].paths, env.BUILTIN_TABLES["1.5.3"].paths, "1.5.6's table is untouched")
        self.assertNotIn(self.NEW_SKILL_FILE, env.BUILTIN_TABLES["1.5.6"].paths)

    def test_a_folder_with_the_skill_passes_for_1_5_8_and_still_is_refused_for_1_5_6_and_1_5_3(self):
        self.make_home()
        self.pin_hashes({})
        self.make_builtin(self.NEW_SKILL_FILE, "keep.txt")
        for version in ("1.5.7", "1.5.8", None):
            with self.subTest(version=version):
                self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)
        for version in ("1.5.6", "1.5.3"):
            with self.subTest(version=version):
                self.assertIn("antigravity-cli/builtin/" + self.NEW_SKILL, self.refused(env.check_chat_home, self.state, code="foreign_settings", version=version))

    def test_a_path_that_1_5_8_does_not_have_is_refused_for_it_even_though_the_hash_table_is_shared(self):
        self.make_home()
        self.pin_hashes({})
        base = self.make_builtin("keep.txt")
        self.write_private(base / "skills" / "mcp-app-development" / "extra.md", "x")          # a name no table has
        self.assertIn("extra.md", self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.8"))
        shutil.rmtree(base / "skills" / "mcp-app-development")
        self.write_private(base / "skills" / "a-skill-of-1.5.9" / "SKILL.md", "x")
        self.assertIn("a-skill-of-1.5.9", self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.8"))

    def test_the_two_changed_files_of_1_5_8_pass_with_either_value_at_their_own_path_and_nowhere_else(self):
        """ADR 0018: the hashes are shared among the known versions at one path. A folder 1.5.7 wrote stays fine after AGY updated itself to 1.5.8, and the reverse."""
        old, new = env.BUILTIN_TABLES["1.5.7"], env.BUILTIN_TABLES["1.5.8"]
        for rel in (".checksum", self.NEW_SKILL_FILE):
            with self.subTest(rel=rel):
                self.assertNotEqual(old.sha[rel], new.sha[rel])
                self.assertTrue(env.pinned_hashes(rel) >= {old.sha[rel], new.sha[rel]})
                self.assertNotIn(new.sha[rel], env.pinned_hashes("keep.txt"))
                self.assertNotIn(new.sha[rel], env.pinned_hashes("skills/automation/SKILL.md"), "a hash of another path is no pass")
        self.assertEqual(env.pinned_hashes("plugins/swarm/sidecars/swarm_board/hive.js") & {new.sha[".checksum"]}, frozenset())
        for rel in sorted(p for p in new.sha if p not in (".checksum", self.NEW_SKILL_FILE)):
            self.assertEqual(new.sha[rel], old.sha[rel], rel)

    def test_a_version_without_a_table_checks_nothing_and_makes_nothing(self):
        for version in ("1.5.5", "1.5.4", "9.9.9", "", 5, ["1.5.3"]):
            with self.subTest(version=version):
                self.refused(env.builtin_table, version, code="unsupported")
                self.refused(env.check_chat_home, self.state, code="unsupported", version=version)
                self.refused(env.ensure_chat_home, self.state, code="unsupported", version=version)
                self.assertEqual(env.home_state(self.state, version=version)[0] in ("missing", "refused"), True)
        self.assertFalse(self.chat_home.exists(), "no folder was made for a version without a table")
        self.assertEqual(env.builtin_table().version, env.NEWEST_VERSION, "no version means the newest known one")
        self.assertEqual(env.NEWEST_VERSION, "1.5.8")

    def test_the_real_tables_of_both_versions_let_the_empty_file_pass_and_refuse_other_bytes_by_path(self):
        self.make_home()
        for version, table in env.BUILTIN_TABLES.items():
            for rel in sorted(p for p in table.paths if p not in table.dirs):
                with self.subTest(version=version, rel=rel):
                    base = self.make_builtin(rel)
                    if rel == "keep.txt":
                        (base / rel).write_bytes(b"")
                        self.assertEqual(env.check_chat_home(self.state, version=version), self.chat_home)
                    (base / rel).write_text("other bytes")
                    self.assertIn("antigravity-cli/builtin/" + rel,
                                  self.refused(env.check_chat_home, self.state, code="foreign_settings", version=version))
                    shutil.rmtree(base)

    def test_the_real_tables_of_the_two_versions_differ_in_the_hashes_of_exactly_fifteen_files_and_any_of_them_passes(self):
        old, new, newest = env.BUILTIN_TABLES["1.5.3"], env.BUILTIN_TABLES["1.5.6"], env.BUILTIN_TABLES["1.5.7"]
        self.assertEqual(old.paths, new.paths)
        differ = sorted(p for p in old.sha if old.sha[p] != new.sha[p])
        self.assertEqual(len(differ), 15)
        for rel in differ:
            self.assertEqual(env.pinned_hashes(rel), frozenset({old.sha[rel], new.sha[rel], newest.sha[rel], env.BUILTIN_TABLES["1.5.8"].sha[rel]}), rel)          # (1.5.7 pins its own value, or 1.5.6's again; 1.5.8 pins 1.5.7's, or its own for the one file it changed)
        self.assertTrue(env.pinned_hashes(differ[0]) >= {old.sha[differ[0]], new.sha[differ[0]]})
        self.assertEqual(env.pinned_hashes("keep.txt"), frozenset({hashlib.sha256(b"").hexdigest()}))
        self.assertEqual(env.pinned_hashes("not/a/file"), frozenset())

    def test_the_hash_of_an_older_version_does_not_make_a_stranger_in_the_folder_pass(self):
        self.make_home()
        self.pin_hashes({})
        base = self.make_builtin("keep.txt")
        (base / "keep.txt").write_bytes(b"")
        self.assertEqual(env.check_chat_home(self.state, version="1.5.6"), self.chat_home)
        (base / "skills" / "made-up-skill").mkdir(parents=True)
        self.assertIn("made-up-skill", self.refused(env.check_chat_home, self.state, code="foreign_settings", version="1.5.6"))

    def test_a_file_with_a_pinned_hash_is_looked_at_by_what_is_in_it_not_by_a_link(self):
        self.make_home()
        rel = "plugins/swarm/plugin.json"
        self.hashed("made-up", only=[rel])
        base = self.make_builtin(rel)
        real = self.tmp / "real.json"
        real.write_text("made-up")
        (base / rel).unlink()
        (base / rel).symlink_to(real)                                 # the same bytes, behind a link
        with self.assertRaises(env.AgyRefused):
            env.check_chat_home(self.state)

    def test_a_folder_that_is_spelled_with_other_letters_than_the_table_is_never_the_table_s(self):
        self.make_home()
        cli = self.chat_home / "antigravity-cli"
        for spelling in ("Builtin", "BUILTIN", "Persistent_Terminals", "PERSISTENT_TERMINALS"):
            with self.subTest(spelling=spelling):
                (cli / spelling / "skills").mkdir(parents=True)
                (cli / spelling / "skills" / "Hooks.md").write_text("x")
                why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
                self.assertIn(spelling, why)
                self.assertNotIn(str(self.tmp), why)
                shutil.rmtree(cli / spelling)
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_a_name_inside_the_built_in_folder_with_other_letters_is_refused(self):
        self.make_home()
        self.hashed()
        self.make_builtin("skills/agy-customizations/docs/skills.md")
        base = self.chat_home / "antigravity-cli" / "builtin"
        (base / "skills" / "Native_Swarm").mkdir()                      # not a spelling of the table
        self.assertIn("Native_Swarm", self.refused(env.check_chat_home, self.state, code="foreign_settings"))

    def test_the_one_function_that_names_a_folder_of_the_table_is_exact_and_says_when_only_the_letters_differ(self):
        self.assertEqual(env.table_folder("builtin/skills"), "builtin")
        self.assertEqual(env.table_folder("persistent_terminals"), "persistent_terminals")
        self.assertIsNone(env.table_folder("cache/x"))
        self.assertEqual(env.table_folder("Builtin/skills"), env.LETTERS_DIFFER)
        self.assertEqual(env.table_folder("PERSISTENT_TERMINALS/t"), env.LETTERS_DIFFER)

    def test_fewer_built_in_names_than_the_table_is_fine_and_a_link_there_is_refused(self):
        self.make_home()
        self.make_builtin("skills")
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        (self.chat_home / "antigravity-cli" / "builtin" / "plugins").symlink_to(self.tmp)
        self.assertIn("builtin/plugins", self.refused(env.check_chat_home, self.state, code="foreign_settings"))

    def test_the_table_exemption_is_only_inside_builtin(self):
        self.make_home()
        cli = self.chat_home / "antigravity-cli"
        for where in ("skills", "plugins", "cache/skills/agy-customizations", "implicit/plugins", "brain/x/skills"):
            with self.subTest(where=where):
                (cli / where).mkdir(parents=True, exist_ok=True)
                self.refused(env.check_chat_home, self.state, code="foreign_settings")
                shutil.rmtree(cli / where.split("/")[0])
                (cli / where.split("/")[0]).mkdir() if "/" in where else None
                if "/" in where:
                    (cli / where.split("/")[0]).rmdir()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)

    def test_persistent_terminals_is_made_by_agy_and_only_empty_passes(self):
        self.make_home()
        cli = self.chat_home / "antigravity-cli"
        (cli / "persistent_terminals").mkdir(parents=True, exist_ok=True)
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        for where, kind in (("t-1", "file"), ("t-1", "dir"), ("hooks.json", "file"), ("a/b/rules", "dir")):
            with self.subTest(where=where, kind=kind):
                path = cli / "persistent_terminals" / where
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x") if kind == "file" else path.mkdir(exist_ok=True)
                why = self.refused(env.check_chat_home, self.state, code="foreign_settings")
                self.assertIn("antigravity-cli/persistent_terminals/", why)
                self.assertNotIn(str(self.tmp), why)
                shutil.rmtree(cli / "persistent_terminals")
                (cli / "persistent_terminals").mkdir()
        self.assertEqual(env.check_chat_home(self.state), self.chat_home)
        shutil.rmtree(cli / "persistent_terminals")
        (cli / "persistent_terminals").symlink_to(self.tmp)
        with self.assertRaises(env.AgyRefused):                  # a link is never let in (it is refused whichever check sees it first)
            env.check_chat_home(self.state)

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
                    "antigravity-cli/conversation_summaries.db",
                    "antigravity-cli/jetski_state.pbtxt", "antigravity-cli/installation_id"):
            self.write_private(self.chat_home / rel, "{}")
        self.write_private(self.chat_home / "antigravity-cli" / "builtin" / "keep.txt", "")      # (a built-in file: its bytes are pinned)
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

    def test_only_the_named_places_are_looked_at_and_nothing_is_listed_or_opened(self):          # (P56-2: it was "only that one name", ~/.agents/hooks.json)
        calls = []
        real = os.lstat

        def watch(path, *a, **k):
            calls.append(os.fspath(path))
            return real(path, *a, **k)

        with mock.patch("os.lstat", watch), mock.patch("os.scandir", side_effect=AssertionError("listed")), \
                mock.patch("builtins.open", side_effect=AssertionError("opened")):
            env.home_hooks_state(self.home)
        self.assertEqual(calls, [str(self.home / root / item) for root in (".agents", ".agent", "_agents", "_agent")
                                 for item in ("hooks.json", "plugins.json", "plugins")])

    def test_the_hooks_and_plugins_of_every_customization_root_in_the_home_folder_refuse(self):
        """P56-2: AGY's own guide (the same in 1.5.3 and 1.5.6) reads ``hooks.json``, ``plugins.json`` and ``plugins/`` (a plugin may carry
        hooks and an MCP server it starts) from ``.agents``, ``.agent``, ``_agents`` and ``_agent``; any of the twelve stops the chat."""
        for root in (".agents", ".agent", "_agents", "_agent"):
            for item in ("hooks.json", "plugins.json", "plugins"):
                for kind in ("file", "dir", "link"):
                    with self.subTest(root=root, item=item, kind=kind):
                        path = self.home / root / item
                        path.parent.mkdir(exist_ok=True)
                        {"file": lambda: path.write_text("{}"), "dir": lambda: path.mkdir(),
                         "link": lambda: path.symlink_to(self.tmp / "nowhere")}[kind]()
                        state, why = env.home_hooks_state(self.home)
                        self.assertEqual(state, "present")
                        self.assertIn(f"~/{root}/{item}", why)
                        self.assertIn("hooks", why)
                        self.assertNotIn(str(self.home), why)
                        path.rmdir() if kind == "dir" else path.unlink()
                path.parent.rmdir()
        self.assertEqual(env.home_hooks_state(self.home), ("absent", ""))

    def test_the_other_things_the_person_keeps_in_those_folders_are_not_hooks(self):
        for root in (".agents", ".agent", "_agents", "_agent"):
            for name in ("skills", "skills.json", "rules", "workflows", "agents", "teamwork"):
                (self.home / root).mkdir(exist_ok=True)
                (self.home / root / name).write_text("x")
        (self.home / "agents").mkdir()
        (self.home / "agents" / "hooks.json").write_text("{}")                   # a folder that only looks like the root
        self.assertEqual(env.home_hooks_state(self.home), ("absent", ""))

    def test_a_failure_to_tell_in_the_other_roots_refuses_too(self):
        for root in (".agent", "_agents", "_agent"):
            with self.subTest(root=root):
                path = self.home / root
                path.mkdir()
                path.chmod(0o000)
                state, why = env.home_hooks_state(self.home)
                path.chmod(0o700)
                self.assertEqual(state, "unreadable")
                self.assertIn("無法確認", why)
                path.rmdir()
        (self.home / "_agent").write_text("a file where the folder should be")
        self.assertEqual(env.home_hooks_state(self.home)[0], "unreadable")


class AncestorHooksTests(TempCase):
    """R1 (P1 of the security review): AGY looks for its customization roots from the folder it starts in up to the repository root, so a
    ``_agent/hooks.json`` in a folder above VBear's state folder (``VBEAR_HOME=$HOME/project/.vbear``) is loaded by a chat. Every folder
    above the work folder, up to ``/``, is looked at (by name only) for the twelve places of the home check."""

    PLACES = tuple(f"{root}/{item}" for root in (".agents", ".agent", "_agents", "_agent") for item in ("hooks.json", "plugins.json", "plugins"))

    def setUp(self):
        super().setUp()
        self.project = self.home / "project"
        self.nested = self.project / ".vbear"
        self.work = self.nested / "chat-work" / ("a" * 24)

    def put(self, folder, place, kind="file"):
        path = Path(folder) / place
        path.parent.mkdir(parents=True, exist_ok=True)
        {"file": lambda: path.write_text("{}"), "dir": lambda: path.mkdir(),
         "link": lambda: path.symlink_to(self.tmp / "nowhere")}[kind]()
        return path

    def test_nothing_above_the_work_folder_passes(self):
        self.assertEqual(env.ancestor_hooks_state(self.work), ("absent", ""))
        self.work.mkdir(parents=True)
        (self.project / "_agent").mkdir()
        self.write_private(self.project / "_agent" / "skills.json", "{}")               # the person's skills are text AGY loads anyway
        self.write_private(self.project / ".agents" / "rules" / "a.md", "x")
        self.assertEqual(env.ancestor_hooks_state(self.work), ("absent", ""))

    def test_the_four_roots_and_the_three_names_in_a_project_above_a_nested_state_folder_refuse(self):
        for place in self.PLACES:
            for kind in ("file", "dir", "link"):
                with self.subTest(place=place, kind=kind):
                    path = self.put(self.project, place, kind)
                    state, why = env.ancestor_hooks_state(self.work)
                    self.assertEqual(state, "present")
                    self.assertIn(f"~/project/{place}", why, "the folder and the name, with the home written as ~")
                    self.assertNotIn(str(self.home), why)
                    self.assertIn("VBEAR_HOME", why, "and what the person can do")
                    path.rmdir() if kind == "dir" else path.unlink()
                    path.parent.rmdir()
        self.assertEqual(env.ancestor_hooks_state(self.work), ("absent", ""))

    def test_every_folder_up_to_the_root_is_looked_at_not_only_the_home_and_the_project(self):
        seen = []
        original = os.lstat

        def watch(path, *a, **k):
            seen.append(os.fspath(path))
            return original(path, *a, **k)
        with mock.patch("os.lstat", watch):
            env.ancestor_hooks_state(self.work)
        folders = [self.work.parent, self.nested, self.project, self.tmp, self.tmp.parent, Path("/")]
        for folder in folders:
            for place in self.PLACES:
                if folder != self.home:
                    self.assertIn(os.path.join(os.fspath(folder), place), seen, (str(folder), place))
        places = [p for p in seen if p.endswith(tuple("/" + place for place in self.PLACES))]          # (realpath looks at folders too)
        self.assertFalse([p for p in places if p.startswith(os.fspath(self.work) + "/")], "nothing inside the work folder itself")
        self.assertEqual(len(places), len(set(places)), "no place is looked at twice")

    def test_the_home_folder_is_left_to_the_home_check_and_not_counted_twice(self):
        self.put(self.home, ".agents/hooks.json")
        self.assertEqual(env.home_hooks_state(self.home)[0], "present")
        self.assertEqual(env.ancestor_hooks_state(self.work, self.home), ("absent", ""))
        seen = []
        original = os.lstat
        with mock.patch("os.lstat", lambda path, *a, **k: (seen.append(os.fspath(path)), original(path, *a, **k))[1]):
            env.ancestor_hooks_state(self.work, self.home)
        self.assertFalse([p for p in seen if p.startswith(str(self.home) + "/.agent") or p.startswith(str(self.home) + "/_agent")], seen)

    def test_a_folder_outside_the_home_is_named_with_its_whole_path(self):
        outside = self.tmp / "work-disk" / "project"
        self.put(outside, "_agents/plugins", "dir")
        state, why = env.ancestor_hooks_state(outside / ".vbear" / "chat-work" / ("b" * 24))
        self.assertEqual(state, "present")
        self.assertIn(str(outside / "_agents" / "plugins"), why)

    def test_a_link_in_the_way_is_followed_to_the_real_folders_and_the_lexical_ones_too(self):
        self.put(self.project, "_agent/hooks.json")
        self.nested.mkdir(parents=True)
        link = self.tmp / "via-link"
        link.symlink_to(self.project)
        state, why = env.ancestor_hooks_state(link / ".vbear" / "chat-work" / ("c" * 24))
        self.assertEqual(state, "present", "AGY's own folder is the real one")
        self.assertIn("_agent/hooks.json", why)
        (self.project / "_agent" / "hooks.json").unlink()
        lexical = self.tmp / "lexical"
        self.put(lexical, "_agents/plugins.json")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (lexical / "door").symlink_to(elsewhere)
        state, why = env.ancestor_hooks_state(lexical / "door" / "x")
        self.assertEqual(state, "present", "and the folders above the path as it is written")
        self.assertIn("lexical/_agents/plugins.json", why)

    def test_a_folder_that_cannot_be_looked_at_refuses_and_a_file_where_a_root_would_be_does_not(self):
        self.work.mkdir(parents=True)
        self.project.chmod(0o000)
        try:
            state, why = env.ancestor_hooks_state(self.work)
        finally:
            self.project.chmod(0o700)
        self.assertEqual(state, "unreadable")
        self.assertIn("無法確認", why)
        self.assertIn("~/project", why)
        (self.project / "_agent").write_text("a file where a folder would be: no root, so no hooks")
        self.assertEqual(env.ancestor_hooks_state(self.work), ("absent", ""))
        with mock.patch("os.lstat", side_effect=OSError(5, "Input/output error")):
            self.assertEqual(env.ancestor_hooks_state(self.work)[0], "unreadable")

    def test_nothing_is_opened_or_listed(self):
        self.put(self.project, "_agents/hooks.json")
        with mock.patch("builtins.open", side_effect=AssertionError("opened")), mock.patch("os.scandir", side_effect=AssertionError("listed")):
            self.assertEqual(env.ancestor_hooks_state(self.work)[0], "present")
            with self.assertRaises(env.AgyRefused) as ctx:
                env.check_ancestors(self.work)
        self.assertEqual(ctx.exception.code, "agy_hooks")
        self.assertIn("~/project/_agents/hooks.json", str(ctx.exception))

    def test_the_name_of_the_chats_work_folders_is_the_stores(self):
        from vbear.runtime import chat_store
        self.assertEqual(env.CHAT_WORK_NAME, chat_store.WORK)
        self.assertEqual(Path(chat_store.ensure_work_dir(self.state, "emp-1")).parent, self.state / env.CHAT_WORK_NAME)

    def test_check_ancestors_passes_when_there_is_nothing(self):
        self.assertEqual(env.check_ancestors(self.work), self.work)

    def test_the_folder_itself_is_left_to_check_workdir_unless_asked(self):
        self.work.mkdir(parents=True)
        self.put(self.work, "_agent/hooks.json")
        self.assertEqual(env.ancestor_hooks_state(self.work), ("absent", ""))
        self.assertEqual(env.ancestor_hooks_state(self.work, include_self=True)[0], "present")


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

    def test_the_seven_names_at_the_top_refuse_whatever_they_are_and_however_they_are_cased(self):          # (P56-2: five names, then seven)
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
        self.assertEqual(tuple(env.WORKDIR_FORBIDDEN), (".agents", ".agent", "_agents", "_agent", ".gemini", "GEMINI.md", "AGENTS.md"))

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
        for version in ("1.5.4", "1.5.5", "1.5.2", "2.0.0", "0.0.1"):
            with self.subTest(version=version):
                self.install_agy(version)
                exc = self.refused(self.pin, code="unsupported")
                self.assertEqual(exc.version, version)
                self.assertIn(version, str(exc))
                self.assertIn("1.5.3、1.5.6、1.5.7、1.5.8。", str(exc), "the sentence lists the known versions in order")

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
        self.assertEqual(env.KNOWN_VERSIONS, ("1.5.3", "1.5.6", "1.5.7", "1.5.8"))
        with mock.patch.object(env, "KNOWN_VERSIONS", ("1.5.3", "1.5.4")):
            self.install_agy("1.5.4")
            self.record_pass("1.5.4")
            self.assertEqual(self.pin().version, "1.5.4")

    def test_1_5_6_is_pinned_only_with_a_record_of_its_own_and_1_5_3s_does_not_count_for_it(self):
        """P56-1: ``agy-chat-verified.json`` is kept per version (and each record names a report of that very version)."""
        path = self.install_agy("1.5.6")
        self.refused(self.pin, code="unverified")                              # setUp recorded a pass for 1.5.3 only
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3",))
        exc = self.refused(self.pin, code="unverified")
        self.assertEqual(exc.version, "1.5.6")
        self.assertIn("1.5.3", str(exc), "the sentence says which version did pass")
        # a record whose report is the 1.5.3 report does not make 1.5.6 pass either
        record_path = self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE
        versions = json.loads(record_path.read_text())["versions"]
        versions["1.5.6"] = dict(versions["1.5.3"])
        self.write_private(record_path, json.dumps({"versions": versions}))
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3",))
        self.refused(self.pin, code="unverified")
        self.record_pass("1.5.6")
        pinned = self.pin()
        self.assertEqual((pinned.binary, pinned.version), (os.path.realpath(path), "1.5.6"))
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6"))

    def test_1_5_7_is_pinned_only_with_a_record_of_its_own_and_neither_1_5_3s_nor_1_5_6s_counts_for_it(self):
        """v0.25.5: the same lock again. A pass of 1.5.6 (or of 1.5.3) does not make 1.5.7 pass, a record copied from another version does not either, and a
        report that names another version does not either."""
        path = self.install_agy("1.5.7")
        self.record_pass("1.5.6")
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6"))
        exc = self.refused(self.pin, code="unverified")
        self.assertEqual(exc.version, "1.5.7")
        self.assertIn("1.5.6", str(exc), "the sentence says which versions did pass")
        record_path = self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE
        versions = json.loads(record_path.read_text())["versions"]
        versions["1.5.7"] = dict(versions["1.5.6"])                              # a record that points at the 1.5.6 report
        self.write_private(record_path, json.dumps({"versions": versions}))
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6"))
        self.refused(self.pin, code="unverified")
        self.record_pass("1.5.7")
        pinned = self.pin()
        self.assertEqual((pinned.binary, pinned.version), (os.path.realpath(path), "1.5.7"))
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6", "1.5.7"))
        self.assertIn("1.5.7", cli_versions.AGY_CHAT_VERIFIED_VERSIONS + tuple(cli_versions.local_agy_chat_verified_versions()))
        self.assertNotIn("1.5.7", cli_versions.AGY_CHAT_VERIFIED_VERSIONS, "nothing is built in: only a pass on this Mac counts")

    def test_1_5_8_is_pinned_only_with_a_record_of_its_own_and_none_of_the_older_versions_counts_for_it(self):
        """v0.25.6: the same lock again. A pass of 1.5.7 (or of 1.5.6, or of 1.5.3) does not make 1.5.8 pass, a record copied from another version does not
        either, and a report that names another version does not either."""
        path = self.install_agy("1.5.8")
        self.record_pass("1.5.7")
        self.record_pass("1.5.6")
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6", "1.5.7"))
        exc = self.refused(self.pin, code="unverified")
        self.assertEqual(exc.version, "1.5.8")
        self.assertIn("1.5.7", str(exc), "the sentence says which versions did pass")
        record_path = self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE
        versions = json.loads(record_path.read_text())["versions"]
        versions["1.5.8"] = dict(versions["1.5.7"])                              # a record that points at the 1.5.7 report
        self.write_private(record_path, json.dumps({"versions": versions}))
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6", "1.5.7"))
        self.refused(self.pin, code="unverified")
        self.record_pass("1.5.8")
        pinned = self.pin()
        self.assertEqual((pinned.binary, pinned.version), (os.path.realpath(path), "1.5.8"))
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.3", "1.5.6", "1.5.7", "1.5.8"))
        self.assertNotIn("1.5.8", cli_versions.AGY_CHAT_VERIFIED_VERSIONS, "nothing is built in: only a pass on this Mac counts")
        self.install_agy("1.5.7")                                                 # the old version is still its own record
        self.assertEqual(self.pin().version, "1.5.7")
        self.install_agy("1.5.9")                                                 # AGY updated itself again: not known
        self.refused(self.pin, code="unsupported")


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

    def test_the_folder_is_looked_at_with_the_table_of_the_version_that_is_installed(self):
        """P56-1: the status asks about the AGY it found (``agy --version``), so a path only another version's table has is refused for it."""
        keep = "skills/native_swarm/logo.svg"
        tables = {v: t._replace(sha={}) for v, t in env.BUILTIN_TABLES.items()}
        tables["1.5.6"] = tables["1.5.6"]._replace(paths=frozenset(p for p in tables["1.5.6"].paths if p != keep))
        patch = mock.patch.dict(env.BUILTIN_TABLES, tables)
        patch.start()
        self.addCleanup(patch.stop)
        home = self.state / "agy-chat-home"
        for path in (home / "antigravity-cli" / "builtin" / "skills" / "native_swarm",):
            path.mkdir(parents=True, mode=0o700)
        (home / "antigravity-cli" / "builtin" / keep).write_text("x")
        os.chmod(home, 0o700)
        self.record_pass("1.5.3")
        self.record_pass("1.5.6")
        self.install_agy("1.5.3")
        self.assert_state("ready", why=False, version="1.5.3", verified_versions=["1.5.3", "1.5.6"])
        self.install_agy("1.5.6")
        out = self.assert_state("folder", version="1.5.6")
        self.assertIn(keep, out["why"])

    def test_1_5_6_is_held_back_by_the_application_support_folder_and_1_5_3_is_not(self):
        """P56-2: the strings of 1.5.6 name /Library/Application Support/Antigravity, so for 1.5.6 it is an administrator source."""
        self.install_agy("1.5.6")
        self.record_pass("1.5.6")
        self.assert_state("ready", why=False, version="1.5.6", admin_policy_ok=True)
        (self.policy_root / "Library" / "Application Support" / "Antigravity").mkdir(parents=True)
        out = self.assert_state("policy", version="1.5.6", admin_policy_ok=False, hooks_ok=None)
        self.assertIn("管理員", out["why"])
        self.install_agy("1.5.3")
        self.record_pass("1.5.3")
        self.assert_state("ready", why=False, version="1.5.3", admin_policy_ok=True)

    def test_hooks_above_the_state_folder_are_hooks_too(self):          # R1
        """The state folder is ``home/.vbear``: the folders above it (``home`` is the HOME check's, ``tmp`` and up are the new look)
        and the folder the work folders live in. The status says so before a chat is tried."""
        self.ready()
        self.assert_state("ready", why=False, hooks_ok=True)
        for where, place in ((self.tmp, "_agent/hooks.json"), (self.state / "chat-work", "_agents/plugins")):
            with self.subTest(where=str(where), place=place):
                path = where / place
                path.parent.mkdir(parents=True, exist_ok=True)
                path.mkdir() if place.endswith("plugins") else path.write_text("{}")
                out = self.status()          # (not assert_state: this sentence names the folder it found, which is not under the home)
                self.assertEqual((out["state"], out["hooks_ok"]), ("hooks", False), out)
                self.assertIn(place, out["why"])
                self.assertNotIn(str(self.home), out["why"])
                self.assertEqual(set(out), self.KEYS)
                path.rmdir() if place.endswith("plugins") else path.unlink()
                path.parent.rmdir()
        self.assert_state("ready", why=False, hooks_ok=True)

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
