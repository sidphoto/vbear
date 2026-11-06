"""A Codex chat process as a managed launch (P38-3): engine "codex-chat" under sessions/, its settings, argv and
environment (exactly seven variables), the checks before it starts, and the places that read every launch (flows,
cleanup, a terminal). Synthetic HOME and VBEAR_HOME; nothing is started."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from vbear.runtime import agent_sessions as asess
from vbear.runtime import chat_store as cs
from vbear.runtime import codex_chat_protocol as ccp
from vbear.runtime import stream_flow

VERSION = "0.163.0"


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcx-", dir="/tmp")))
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
        self.thread = str(uuid.uuid4())

    def prepare(self, **over):
        args = dict(workdir=self.work, cli_binary=str(self.cli), cli_version=VERSION,
                    cli_identity=asess.binary_identity(str(self.cli)), model_id=None,
                    chat_id="c-0123456789abcdef", profile_id="emp-1", resume=False, thread_id=None,
                    codex_home=str(self.chat_home))
        args.update(over)
        m = asess.prepare_codex_chat_launch(self.base, **args)
        self.addCleanup(asess.cleanup_launch, self.base, m["launch_id"], proven_dead=True)
        return m


class PrepareTests(LaunchCase):
    def test_settings_manifest_and_argv(self):
        m = self.prepare()
        self.assertEqual(m["engine"], "codex-chat")
        self.assertIsNone(asess.codex_chat_manifest_problem(m))
        consts = ccp.VERSIONS[VERSION]
        settings = json.loads(Path(m["settings_path"]).read_text())
        self.assertEqual(settings, {"engine": "codex-chat", "approval_policy": "untrusted", "approvals_reviewer": "user",
                                    "sandbox": ccp.SANDBOX_POLICY, "config": list(consts.config),
                                    "project_trust": {self.work: "untrusted"},
                                    "disabled_features": list(consts.disabled_features)})
        self.assertIn("project_root_markers=[]", settings["config"])
        self.assertEqual(stat.S_IMODE(os.lstat(m["settings_path"]).st_mode), 0o600)
        argv = asess.codex_chat_argv(m)
        self.assertEqual(argv, [str(self.cli), "app-server", "--listen", "stdio://",
                                *[x for s in consts.config for x in ("-c", s)],
                                "-c", 'projects={%s={trust_level="untrusted"}}' % json.dumps(self.work),
                                *[x for f in consts.disabled_features for x in ("--disable", f)]])
        self.assertEqual(argv[1:], ccp.argv_for(consts, self.work))
        self.assertNotIn("--strict-config", argv)
        for danger in ("--sandbox", "--yolo", "--dangerously-bypass-approvals-and-sandbox", "--full-auto",
                       "--ask-for-approval", "--remote"):
            self.assertNotIn(danger, argv)
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["chat_id"], "c-0123456789abcdef")
        self.assertEqual(m["codex_home"], str(self.chat_home))

    def test_the_trust_setting_names_the_work_folder_with_its_dot_inside_one_key(self):
        import tomllib
        m = self.prepare()
        self.assertIn("/.vbear/", self.work)                    # the state folder is ~/.vbear: a dot inside the path
        argv = asess.codex_chat_argv(m)
        value = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"][-1]
        self.assertEqual(tomllib.loads(value), {"projects": {self.work: {"trust_level": "untrusted"}}})

    def test_a_work_folder_whose_path_cannot_be_written_safely_is_refused_to_start(self):
        m = self.prepare()
        bad = dict(m, canonical_workspace=m["canonical_workspace"] + "\nprojects")
        self.assertIsNotNone(asess.codex_chat_manifest_problem(bad))
        with self.assertRaises(asess.LaunchRefused):
            asess.codex_chat_argv(bad)
        with self.assertRaises(asess.LaunchRefused):
            asess.codex_chat_settings(VERSION, "/x/a\nb")

    def test_settings_without_the_trust_entry_or_for_another_folder_are_refused(self):
        for mutate in (lambda d: d.pop("project_trust"),
                       lambda d: d.update(project_trust={"/elsewhere": "untrusted"}),
                       lambda d: d.update(project_trust={self.work: "trusted"}),
                       lambda d: d.update(config=[c for c in d["config"] if c != "project_root_markers=[]"])):
            m = self.prepare()
            settings = Path(m["settings_path"])
            data = json.loads(settings.read_text())
            mutate(data)
            os.chmod(settings, 0o600)
            settings.write_text(json.dumps(data))
            asess.update_manifest(self.base, m["launch_id"], settings_sha256=asess._sha256(settings))
            with self.assertRaises(asess.LaunchRefused):
                asess.load_validated(self.base, m["launch_id"])

    def test_a_resumed_launch_names_its_thread(self):
        m = self.prepare(resume=True, thread_id=self.thread, model_id="gpt-6.1-sol")
        self.assertIsNone(asess.codex_chat_manifest_problem(m))
        self.assertEqual((m["resume"], m["thread_id"], m["model_id"]), (True, self.thread, "gpt-6.1-sol"))
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(resume=True, thread_id=None)
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(resume=False, thread_id=self.thread)

    def test_the_environment_is_exactly_seven_variables(self):
        m = self.prepare()
        env = asess.codex_chat_env(m, {"PATH": "/usr/bin:/bin", "USER": "someone", "LOGNAME": "someone", "LANG": "C",
                                       "TERM": "xterm", "OPENAI_API_KEY": "must-not-pass", "HOME": "/real/home"})
        self.assertEqual(set(env), {"PATH", "USER", "LOGNAME", "LANG", "CODEX_HOME", "HOME",
                                    "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"})
        self.assertEqual(env["CODEX_HOME"], str(self.chat_home))
        self.assertEqual(env["CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"], "1")
        self.assertEqual(env["HOME"], os.path.join(m["scratch"]["path"], "home"))
        self.assertEqual(os.listdir(env["HOME"]), [])
        self.assertEqual(stat.S_IMODE(os.lstat(env["HOME"]).st_mode), 0o700)
        self.assertEqual(env["PATH"], "/usr/bin:/bin")
        with self.assertRaises(asess.LaunchRefused):
            asess.codex_chat_env(m, {"PATH": "/usr/bin", "USER": "someone", "LOGNAME": "someone"})   # no LANG

    def test_refused_before_anything_is_made(self):
        other = self.tmp / "elsewhere"
        other.mkdir(mode=0o700)
        cases = [dict(workdir=str(other)), dict(workdir=str(self.base)), dict(workdir=str(self.home)),
                 dict(cli_version="0.1.0"), dict(model_id="bad model"), dict(chat_id="../x"),
                 dict(profile_id="../x"), dict(resume="yes"), dict(thread_id="nope", resume=True),
                 dict(codex_home=str(self.home / ".codex")), dict(codex_home="relative"),
                 dict(codex_home=str(self.base / "codex-home"))]
        for over in cases:
            with self.assertRaises(asess.LaunchRefused, msg=over):
                self.prepare(**over)
        self.assertFalse((self.base / "sessions").exists() and os.listdir(self.base / "sessions"))

    def test_a_terminal_launch_never_runs_a_codex_chat_manifest(self):
        with self.assertRaises(asess.LaunchRefused):
            asess.managed_argv(self.prepare())

    def test_drift_is_refused(self):
        m = self.prepare()
        settings = Path(m["settings_path"])
        data = json.loads(settings.read_text())
        data["approval_policy"] = "never"
        os.chmod(settings, 0o600)
        settings.write_text(json.dumps(data))
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])

    def test_the_chat_folder_moving_is_refused(self):
        m = self.prepare()
        asess.update_manifest(self.base, m["launch_id"], codex_home=str(self.home / ".codex"))
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])

    def test_a_changed_manifest_is_refused(self):
        m = self.prepare()
        for field, value in (("chat_id", "nope"), ("resume", 1), ("thread_id", "x"), ("extra", 1),
                             ("cli_version", "0.1.0"), ("codex_home", "relative"), ("engine", "codex"),
                             ("boundary", {"write": "anything"})):
            bad = dict(m, **{field: value})
            self.assertIsNotNone(asess.codex_chat_manifest_problem(bad), field)


class EveryLaunchReaderTests(LaunchCase):
    def test_flows_skip_a_codex_chat_launch(self):
        self.prepare()
        self.assertEqual(stream_flow.flow_sessions(self.base, "flow-0123456789ab", started=False), [])

    def test_cleanup_removes_it_with_its_home(self):
        m = self.prepare()
        asess.codex_chat_env(m, {"PATH": "/usr/bin", "USER": "u", "LOGNAME": "u", "LANG": "C"})
        res = asess.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertTrue(res["cleaned"], res)
        self.assertFalse(os.path.lexists(m["launch_dir"]["path"]))
        self.assertFalse(os.path.lexists(m["scratch"]["path"]))


if __name__ == "__main__":
    unittest.main()
