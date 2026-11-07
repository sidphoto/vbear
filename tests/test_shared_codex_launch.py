"""P43-2 (ADR 0009): a Codex chat process with the shared folder as a managed launch. The settings, the manifest and the argument list name the
folder (the one VBear computes, nothing else) as the sandbox's one more writable root; the launch checks it again when it is loaded. With
the folder off the manifest, the settings file and the argument list are the ones v0.17.0 made. Nothing is started."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear.runtime import agent_sessions as asess, chat_store as cs, codex_chat_protocol as ccp, shared_rules as sr

VERSION = "0.163.0"


class CodexLaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vsx-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.base = self.home / ".vbear"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.cli = self.tmp / "bin" / "codex"
        self.cli.parent.mkdir()
        self.cli.write_text("#!/bin/sh\nexit 0\n")
        self.cli.chmod(0o755)
        self.work = cs.ensure_work_dir(self.base, "emp-1")
        self.chat_home = self.base / "codex-chat-home"
        self.chat_home.mkdir(mode=0o700)
        self.shared = sr.shared_path(self.base)
        self.assertIsNone(sr.ensure_folder(str(self.base), str(self.home)))

    def prepare(self, **over):
        args = dict(workdir=self.work, cli_binary=str(self.cli), cli_version=VERSION,
                    cli_identity=asess.binary_identity(str(self.cli)), model_id=None,
                    chat_id="c-0123456789abcdef", profile_id="emp-1", resume=False, thread_id=None,
                    codex_home=str(self.chat_home))
        args.update(over)
        m = asess.prepare_codex_chat_launch(self.base, **args)
        self.addCleanup(asess.cleanup_launch, self.base, m["launch_id"], proven_dead=True)
        return m

    def settings_of(self, m):
        return json.loads(Path(m["settings_path"]).read_text())

    def configs(self, m):
        argv = asess.codex_chat_argv(m)
        return [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]


class OffTests(CodexLaunchCase):
    def test_off_the_manifest_the_settings_and_the_argument_list_are_what_v0_17_0_made(self):
        m = self.prepare()
        self.assertNotIn("shared", m)
        settings = self.settings_of(m)
        self.assertEqual(settings["sandbox"]["writableRoots"], [])
        self.assertNotIn("shared", settings)
        self.assertEqual(asess.codex_chat_settings(VERSION, os.path.realpath(self.work)), settings)
        self.assertEqual(asess.codex_chat_argv(m), [str(self.cli), *ccp.argv_for(ccp.VERSIONS[VERSION], os.path.realpath(self.work))])
        self.assertNotIn("writable_roots", " ".join(asess.codex_chat_argv(m)))


class OnTests(CodexLaunchCase):
    def test_on_the_settings_the_manifest_and_the_argv_name_the_folder_once_and_nothing_else_changes(self):
        off, on = self.prepare(), self.prepare(shared=self.shared)
        self.assertEqual(on["shared"], self.shared)
        a, b = self.settings_of(off), self.settings_of(on)
        self.assertEqual(b["sandbox"]["writableRoots"], [self.shared])
        self.assertEqual(b["shared"], self.shared)
        b["sandbox"]["writableRoots"] = []
        del b["shared"]
        self.assertEqual(b, a, "only the root differs")
        self.assertEqual(self.configs(on)[:-1], self.configs(off))
        self.assertEqual(self.configs(on)[-1], ccp.shared_root_setting(self.shared))
        self.assertNotIn("--add-dir", asess.codex_chat_argv(on))
        self.assertEqual(sum(self.shared in x for x in asess.codex_chat_argv(on)), 1)
        self.assertEqual(b["approval_policy"], "untrusted")
        self.assertEqual(b["approvals_reviewer"], "user")
        self.assertIs(b["sandbox"]["networkAccess"], False)

    def test_a_launch_that_was_prepared_loads_again_and_the_manifest_is_valid(self):
        m = self.prepare(shared=self.shared)
        self.assertIsNone(asess.codex_chat_manifest_problem(m))
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["shared"], self.shared)

    def test_a_resumed_chat_takes_it_too(self):
        thread = "00000000-0000-4000-8000-000000000003"
        m = self.prepare(shared=self.shared, resume=True, thread_id=thread)
        self.assertEqual(self.configs(m)[-1], ccp.shared_root_setting(self.shared))


class TheOnePathTests(CodexLaunchCase):
    def test_only_the_path_vbear_computes_is_accepted(self):
        other = self.base / "elsewhere"
        other.mkdir(mode=0o700)
        for bad in (str(other), str(self.home), str(self.base), self.shared + "/", self.shared + "/sub", "shared", "", 5, True, [self.shared]):
            with self.subTest(bad=repr(bad)[:50]), self.assertRaises(asess.LaunchRefused):
                self.prepare(shared=bad)
        sessions = self.base / "sessions"
        self.assertEqual(list(sessions.iterdir()) if sessions.exists() else [], [], "nothing is left behind")

    def test_an_unsafe_folder_is_refused_at_prepare_and_at_load(self):
        m = self.prepare(shared=self.shared)
        os.chmod(self.shared, 0o755)
        with self.assertRaises(asess.LaunchRefused) as cm:
            asess.load_validated(self.base, m["launch_id"])
        self.assertEqual(cm.exception.code, "unsafe_path")
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(shared=self.shared)

    def test_a_folder_swapped_for_a_link_is_refused_at_load(self):
        m = self.prepare(shared=self.shared)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        os.rmdir(self.shared)
        os.symlink(elsewhere, self.shared)
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])

    def test_a_manifest_edited_to_name_another_folder_or_to_drop_it_is_refused(self):
        m = self.prepare(shared=self.shared)
        path = Path(m["launch_dir"]["path"]) / "manifest.json"
        good = json.loads(path.read_text())
        for edit in ({"shared": str(self.tmp)}, {"shared": 7}, {"shared": None}):
            path.write_text(json.dumps(dict(good, **edit)))
            with self.subTest(edit=edit), self.assertRaises(asess.LaunchRefused):
                asess.load_validated(self.base, m["launch_id"])
        path.write_text(json.dumps({k: v for k, v in good.items() if k != "shared"}))
        with self.assertRaises(asess.LaunchRefused) as cm:
            asess.load_validated(self.base, m["launch_id"])
        self.assertEqual(cm.exception.code, "drift", "the settings still name the root: not what a launch without it holds")

    def test_settings_edited_to_add_a_root_or_to_drop_it_are_refused(self):
        m = self.prepare(shared=self.shared)
        path = Path(m["settings_path"])
        good = json.loads(path.read_text())
        for name, edit in {"another root": lambda d: d["sandbox"].update(writableRoots=[self.shared, str(self.tmp)]),
                           "no root": lambda d: d["sandbox"].update(writableRoots=[]),
                           "other root": lambda d: d["sandbox"].update(writableRoots=[str(self.tmp)]),
                           "no shared key": lambda d: d.pop("shared")}.items():
            data = json.loads(json.dumps(good))
            edit(data)
            path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
            with self.subTest(name=name), self.assertRaises(asess.LaunchRefused):
                asess.load_validated(self.base, m["launch_id"])

    def test_a_launch_without_it_loads_and_a_settings_file_with_a_root_added_is_refused(self):
        m = self.prepare()
        asess.load_validated(self.base, m["launch_id"])
        path = Path(m["settings_path"])
        data = json.loads(path.read_text())
        data["sandbox"]["writableRoots"] = [self.shared]
        path.write_text(json.dumps(data))
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])


if __name__ == "__main__":
    unittest.main()
