"""P43-1 (ADR 0009): a Claude chat process with the shared folder as a managed launch. The settings give the Bash sandbox one more place to
write (``allowWrite``) and nothing else changes: no ``--add-dir``, ``additionalDirectories`` stays empty, Bash still asks and is not
allowed by the sandbox alone. The manifest names the folder (the one VBear computes, nothing else), the launch checks it again when it
is loaded, and a chat's added system prompt may be 9,000 characters (full mode keeps 2,000). Nothing is started."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from vbear.runtime import agent_sessions as asess, chat_protocol as cp, chat_store as cs, shared_rules as sr

VERSION = "2.1.318"


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vsl-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.base = self.home / ".vbear"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.cli = self.tmp / "bin" / "claude"
        self.cli.parent.mkdir()
        self.cli.write_text("#!/bin/sh\nexit 0\n")
        self.cli.chmod(0o755)
        self.work = cs.ensure_work_dir(self.base, "emp-1")
        self.sid = str(uuid.uuid4())
        self.shared = sr.shared_path(self.base)
        self.assertIsNone(sr.ensure_folder(str(self.base), str(self.home)))

    def prepare(self, **over):
        args = dict(workdir=self.work, cli_binary=str(self.cli), cli_version=VERSION,
                    cli_identity=asess.binary_identity(str(self.cli)), model_id="claude-haiku-5-5",
                    chat_id="c-0123456789abcdef", profile_id="emp-1", claude_session_id=self.sid,
                    budget_usd=0.5, resume=False)
        args.update(over)
        m = asess.prepare_chat_launch(self.base, **args)
        self.addCleanup(asess.cleanup_launch, self.base, m["launch_id"], proven_dead=True)
        return m


class SettingsTests(LaunchCase):
    def test_off_the_manifest_and_settings_are_what_v0_17_0_made(self):
        m = self.prepare()
        self.assertNotIn("shared", m)
        settings = json.loads(Path(m["settings_path"]).read_text())
        self.assertEqual(settings["sandbox"]["filesystem"]["allowWrite"], [self.work, m["scratch"]["path"]])
        self.assertEqual(asess.chat_settings(self.work, m["scratch"]["path"], os.getuid(), VERSION), settings)

    def test_on_the_sandbox_may_write_the_shared_folder_too_and_nothing_else_changes(self):
        off = self.prepare()
        on = self.prepare(shared=self.shared)
        self.assertEqual(on["shared"], self.shared)
        a = json.loads(Path(off["settings_path"]).read_text())
        b = json.loads(Path(on["settings_path"]).read_text())
        self.assertEqual(b["sandbox"]["filesystem"]["allowWrite"], [self.work, on["scratch"]["path"], self.shared])
        b["sandbox"]["filesystem"]["allowWrite"] = [self.work, off["scratch"]["path"]]
        deny = b["sandbox"]["filesystem"]["denyWrite"]
        self.assertEqual(deny[len(a["sandbox"]["filesystem"]["denyWrite"]):],
                         [str(Path(self.shared) / n) for n in (".claude", ".codex", ".agents", ".git")],
                         "an allowed Bash may not write the four folders at the top of the shared folder")
        b["sandbox"]["filesystem"]["denyWrite"] = a["sandbox"]["filesystem"]["denyWrite"]
        self.assertEqual(b, a, "only allowWrite and denyWrite differ")
        self.assertEqual(b["permissions"], {"ask": ["Bash"], "additionalDirectories": []})
        self.assertIs(b["sandbox"]["autoAllowBashIfSandboxed"], False)
        self.assertIs(b["sandbox"]["allowUnsandboxedCommands"], False)
        self.assertEqual(b["sandbox"]["network"], {"allowedDomains": [], "strictAllowlist": True})

    def test_the_argv_has_no_add_dir_and_is_otherwise_the_same(self):
        off, on = self.prepare(), self.prepare(shared=self.shared)
        argv_off, argv_on = asess.chat_argv(off), asess.chat_argv(on)
        self.assertNotIn("--add-dir", argv_on)
        self.assertNotIn(self.shared, " ".join(argv_on))
        strip = lambda argv, m: [x.replace(m["settings_path"], "S") for x in argv]
        self.assertEqual(strip(argv_on, on), strip(argv_off, off))
        self.assertIn("--permission-prompt-tool", argv_on)
        self.assertEqual(argv_on[argv_on.index("--permission-prompt-tool") + 1], "stdio")

    def test_a_launch_that_was_prepared_loads_again(self):
        m = self.prepare(shared=self.shared)
        self.assertIsNone(asess.chat_manifest_problem(m))
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["shared"], self.shared)


class TheOnePathTests(LaunchCase):
    def test_only_the_path_vbear_computes_is_accepted(self):
        other = self.base / "elsewhere"
        other.mkdir(mode=0o700)
        for bad in (str(other), str(self.home), str(self.base), self.shared + "/", self.shared + "/sub", "shared", "", 5, True, [self.shared]):
            with self.subTest(bad=repr(bad)[:50]):
                with self.assertRaises(asess.LaunchRefused):
                    self.prepare(shared=bad)
        self.assertEqual(list((self.base / "sessions").iterdir()) if (self.base / "sessions").exists() else [], [], "nothing is left behind")

    def test_an_unsafe_folder_is_refused_at_prepare_and_at_load(self):
        m = self.prepare(shared=self.shared)
        os.chmod(self.shared, 0o755)
        with self.assertRaises(asess.LaunchRefused) as cm:
            asess.load_validated(self.base, m["launch_id"])
        self.assertEqual(cm.exception.code, "unsafe_path")
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(shared=self.shared)

    def test_a_folder_swapped_for_a_link_is_refused(self):
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
        gone = {k: v for k, v in good.items() if k != "shared"}
        path.write_text(json.dumps(gone))
        with self.assertRaises(asess.LaunchRefused) as cm:
            asess.load_validated(self.base, m["launch_id"])
        self.assertEqual(cm.exception.code, "drift", "the settings still let the sandbox write there: not what a launch without it holds")

    def test_settings_edited_to_add_a_place_are_refused(self):
        m = self.prepare(shared=self.shared)
        path = Path(m["settings_path"])
        data = json.loads(path.read_text())
        data["sandbox"]["filesystem"]["allowWrite"].append(str(self.tmp))
        path.write_text(json.dumps(data))
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])

    def test_a_terminal_launch_never_takes_one(self):
        with self.assertRaises(TypeError):
            asess.prepare_claude_launch(self.base, str(self.home), cli_binary=str(self.cli), cli_version=VERSION,
                                        cli_identity=asess.binary_identity(str(self.cli)), shared=self.shared)


class PromptRoomTests(LaunchCase):
    def test_a_chat_may_append_nine_thousand_characters_and_full_mode_two_thousand(self):
        self.assertEqual((asess.MAX_CHAT_APPEND_PROMPT, asess.MAX_APPEND_PROMPT), (9000, 2000))
        m = self.prepare(append_prompt="字" * 9000)
        self.assertEqual(len(asess.chat_argv(m)[asess.chat_argv(m).index("--append-system-prompt") + 1]), 9000)
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(append_prompt="字" * 9001)
        self.assertIsNone(asess.append_prompt_problem("字" * 2000))
        self.assertIsNotNone(asess.append_prompt_problem("字" * 2001), "full mode's room is unchanged")


if __name__ == "__main__":
    unittest.main()
