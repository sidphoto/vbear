"""An AGY chat process as a managed launch (P46-3): engine "agy-chat" under sessions/, its settings record, argv and
environment (exactly six variables), the engine table's third row, and the one place every version-dependent constant
is written. Synthetic HOME and VBEAR_HOME under /tmp; nothing is started and no real AGY is run."""

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
from vbear.runtime import agy_chat_env as env
from vbear.runtime import agy_chat_protocol as acp
from vbear.runtime import chat_engines as ce
from vbear.runtime import chat_store as cs

VERSION = "1.5.3"


class OneSourceTests(unittest.TestCase):
    """The protocol's version table (P46-1) is the only place the settings, the version list and the folder names are written;
    the environment module (P46-2) reads them from it."""

    def test_the_settings_are_the_tables_own_and_their_bytes_are_the_same(self):
        consts = acp.VERSIONS[env.KNOWN_VERSIONS[-1]]
        self.assertIs(env.SETTINGS, consts.settings)
        self.assertEqual(env.SETTINGS_BYTES, acp.settings_bytes(consts))

    def test_the_known_versions_are_the_tables_keys(self):
        self.assertEqual(env.KNOWN_VERSIONS, tuple(acp.VERSIONS))

    def test_the_forbidden_names_are_the_tables_own(self):
        consts = acp.VERSIONS[env.KNOWN_VERSIONS[-1]]
        self.assertIs(env.WORKDIR_FORBIDDEN, consts.workdir_forbidden)
        top = tuple(n for n in consts.home_forbidden if "/" not in n)
        config = tuple(n.split("/", 1)[1] for n in consts.home_forbidden if n.startswith(env.CONFIG_DIR + "/"))
        self.assertEqual(env.FORBIDDEN_TOP, top)
        self.assertEqual(env.FORBIDDEN_CONFIG, config)
        self.assertEqual(len(top) + len(config), len(consts.home_forbidden))


class EngineRowTests(unittest.TestCase):
    def test_the_third_row_is_agy_and_the_first_two_are_as_they_were(self):
        self.assertEqual([(r.tool, r.engine, r.check_mode) for r in ce.TABLE],
                         [("claude", "claude-chat", "chat"), ("codex", "codex-chat", "codex-chat"), ("agy", "agy-chat", "agy-chat")])
        row = ce.by_tool("agy")
        self.assertIs(row, ce.by_engine("agy-chat"))
        self.assertEqual((row.noun, row.support_key, row.uuid_fields), ("AGY 聊天", "agy", ()))
        self.assertEqual(row.record_fields(), frozenset({"v", "id", "profile_id", "created_at", "engine"}))

    def test_every_hook_the_row_names_is_there(self):
        from vbear import chat_service
        from vbear.runtime import daemon_chat
        row = ce.by_tool("agy")
        self.assertTrue(callable(getattr(daemon_chat.ChatOps, row.daemon_send)))
        self.assertTrue(callable(getattr(asess, row.manifest_problem)))
        self.assertTrue(callable(getattr(asess, row.launch_settings)))
        for name in (row.fields, row.verify):
            self.assertTrue(callable(getattr(chat_service.ChatService, name)), name)
        service = chat_service.ChatService(mock.Mock(), base="/tmp")
        for name in (row.state, row.binary, row.verifier):
            self.assertTrue(hasattr(service, name), name)

    def test_the_money_sentence_says_estimate_not_a_bill_and_whose_plan(self):
        text = ce.AGY_MONEY
        for word in ("Google 方案", "估算", "不是帳單", "每 100 萬 token 計 US$1", "至少 US$0.01", "每回合上限"):
            self.assertIn(word, text)
        self.assertEqual(ce.by_tool("agy").money, text)
        for engineering_word in ("CLI", "stdio", "JSON"):
            self.assertNotIn(engineering_word, text)

    def test_the_chat_store_makes_and_reads_a_chat_of_the_engine(self):
        tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vba-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, tmp, True)
        chat = cs.create(tmp, "emp-1", now=1.0, engine="agy-chat")
        self.assertEqual(set(chat), {"v", "id", "profile_id", "created_at", "engine"})
        self.assertEqual(cs.load(tmp, chat["id"]), chat)


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbag-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.base = self.home / ".vbear"
        self.base.mkdir(mode=0o700)
        patched = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home)})
        patched.start()
        self.addCleanup(patched.stop)
        self.cli = self.tmp / "bin" / "agy"
        self.cli.parent.mkdir()
        self.cli.write_text("#!/bin/sh\nexit 0\n")        # a stand-in: nothing here runs it
        self.cli.chmod(0o755)
        self.work = cs.ensure_work_dir(self.base, "emp-1")
        self.agy_home = self.base / "agy-chat-home"
        self.agy_home.mkdir(mode=0o700)
        self.session = str(uuid.uuid4())

    def prepare(self, **over):
        args = dict(workdir=self.work, cli_binary=str(self.cli), cli_version=VERSION,
                    cli_identity=asess.binary_identity(str(self.cli)), chat_id="c-0123456789abcdef", profile_id="emp-1",
                    resume=False, session_id=None, agy_home=str(self.agy_home))
        args.update(over)
        m = asess.prepare_agy_chat_launch(self.base, **args)
        self.addCleanup(asess.cleanup_launch, self.base, m["launch_id"], proven_dead=True)
        return m


class PrepareTests(LaunchCase):
    def test_settings_record_manifest_and_argv(self):
        m = self.prepare()
        self.assertEqual(m["engine"], "agy-chat")
        self.assertIsNone(asess.agy_chat_manifest_problem(m))
        self.assertIsNone(asess.chat_engine_manifest_problem(m))
        consts = acp.VERSIONS[VERSION]
        record = json.loads(Path(m["settings_path"]).read_text())
        self.assertEqual(record, {"engine": "agy-chat", "settings": consts.settings, "model": consts.model_id,
                                  "sandbox": True, "argv": acp.argv_for(consts, str(self.agy_home))})
        self.assertEqual(stat.S_IMODE(os.lstat(m["settings_path"]).st_mode), 0o600)
        self.assertEqual(m["model_id"], consts.model_id)
        argv = asess.agy_chat_argv(m)
        self.assertEqual(argv, [str(self.cli), "acp", "--gemini-dir", str(self.agy_home), "--sandbox", "--disable-telemetry"])
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["chat_id"], "c-0123456789abcdef")
        self.assertEqual(m["agy_home"], str(self.agy_home))

    def test_the_shared_folder_is_one_more_folder_and_only_that_one(self):
        from vbear.runtime import shared_rules
        shared = shared_rules.shared_path(self.base)
        os.mkdir(shared, 0o700)
        m = self.prepare(shared=shared)
        self.assertIsNone(asess.agy_chat_manifest_problem(m))
        self.assertEqual(asess.agy_chat_argv(m)[-2:], ["--add-dir", shared])
        self.assertEqual(json.loads(Path(m["settings_path"]).read_text())["shared"], shared)
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["shared"], shared)
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(shared=str(self.home))
        plain = self.prepare()
        self.assertNotIn("--add-dir", asess.agy_chat_argv(plain))
        self.assertNotIn("shared", plain)

    def test_the_argv_never_names_a_switch_that_lets_a_request_through_or_changes_the_login(self):
        argv = asess.agy_chat_argv(self.prepare())
        for danger in ("--dangerously-skip-permissions", "--login", "--app-data-dir", "--process-per-session",
                       "--include-default-customizations", "--yolo", "--mode", "--settings"):
            self.assertNotIn(danger, argv)

    def test_a_resumed_launch_names_its_session(self):
        m = self.prepare(resume=True, session_id=self.session)
        self.assertIsNone(asess.agy_chat_manifest_problem(m))
        self.assertEqual((m["resume"], m["session_id"]), (True, self.session))
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(resume=True, session_id=None)
        with self.assertRaises(asess.LaunchRefused):
            self.prepare(resume=False, session_id=self.session)

    def test_the_environment_is_exactly_six_variables_and_the_home_is_the_persons_own(self):
        m = self.prepare()
        source = {"PATH": "/usr/bin:/bin", "USER": "someone", "LOGNAME": "someone", "LANG": "C", "TMPDIR": "/var/tmp/x",
                  "HOME": "/real/home", "TERM": "xterm", "ANTIGRAVITY_PERM_GRANTS": "must-not-pass",
                  "GEMINI_API_KEY": "must-not-pass", "GOOGLE_API_KEY": "must-not-pass", "GOOGLE_APPLICATION_CREDENTIALS": "x",
                  "OPENAI_API_KEY": "must-not-pass"}
        got = asess.agy_chat_env(m, source)
        self.assertEqual(set(got), {"PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME"})
        self.assertEqual(set(got), set(acp.VERSIONS[VERSION].env_keys))
        self.assertEqual(got, {k: source[k] for k in got})
        self.assertEqual(got["HOME"], "/real/home")                   # AGY's login follows HOME: not an empty folder
        for key in ("TMPDIR", "LANG", "PATH", "USER", "LOGNAME", "HOME"):
            lacking = {k: v for k, v in source.items() if k != key}
            with self.assertRaises(asess.LaunchRefused, msg=key):
                asess.agy_chat_env(m, lacking)
            with self.assertRaises(asess.LaunchRefused, msg=key):
                asess.agy_chat_env(m, dict(source, **{key: ""}))
        with self.assertRaises(asess.LaunchRefused):
            asess.agy_chat_env(m, dict(source, HOME="relative"))

    def test_refused_before_anything_is_made(self):
        other = self.tmp / "elsewhere"
        other.mkdir(mode=0o700)
        cases = [dict(workdir=str(other)), dict(workdir=str(self.base)), dict(workdir=str(self.home)),
                 dict(cli_version="0.1.0"), dict(chat_id="../x"), dict(profile_id="../x"), dict(resume="yes"),
                 dict(session_id="nope", resume=True), dict(agy_home=str(self.home / ".gemini")), dict(agy_home="relative"),
                 dict(agy_home=str(self.base / "codex-chat-home")), dict(cli_binary="agy"),
                 dict(cli_binary=str(self.cli.parent / ".." / "bin" / "agy"))]
        for over in cases:
            with self.assertRaises(asess.LaunchRefused, msg=over):
                self.prepare(**over)
        self.assertFalse((self.base / "sessions").exists() and os.listdir(self.base / "sessions"))

    def test_a_terminal_launch_never_runs_an_agy_chat_manifest(self):
        with self.assertRaises(asess.LaunchRefused) as ctx:
            asess.managed_argv(self.prepare())
        self.assertEqual(ctx.exception.code, "manifest_invalid")
        self.assertIn("AGY 聊天", str(ctx.exception))
        self.assertTrue(asess.is_known_engine("agy-chat"))

    def test_drift_is_refused(self):
        for mutate in (lambda d: d["settings"].update(toolPermission="auto"), lambda d: d.update(sandbox=False),
                       lambda d: d["argv"].remove("--sandbox"), lambda d: d.update(model="gemini-4-argon-medium")):
            m = self.prepare()
            settings = Path(m["settings_path"])
            data = json.loads(settings.read_text())
            mutate(data)
            os.chmod(settings, 0o600)
            settings.write_text(json.dumps(data))
            asess.update_manifest(self.base, m["launch_id"], settings_sha256=asess._sha256(settings))
            with self.assertRaises(asess.LaunchRefused) as ctx:
                asess.load_validated(self.base, m["launch_id"])
            self.assertEqual(ctx.exception.code, "drift")

    def test_the_chat_folder_moving_is_refused(self):
        m = self.prepare()
        asess.update_manifest(self.base, m["launch_id"], agy_home=str(self.home / ".gemini"))
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])

    def test_a_changed_manifest_is_refused(self):
        m = self.prepare()
        for field, value in (("chat_id", "nope"), ("resume", 1), ("session_id", "x"), ("extra", 1), ("cli_version", "0.1.0"),
                             ("agy_home", "relative"), ("engine", "agy"), ("boundary", {"write": "anything"}),
                             ("model_id", "gemini-4-argon-medium"), ("shared", "/elsewhere"), ("native_session_id", "n-0123456789ab")):
            bad = dict(m, **{field: value})
            self.assertIsNotNone(asess.agy_chat_manifest_problem(bad), field)
        self.assertIsNotNone(asess.agy_chat_manifest_problem(dict(m, codex_home="/x")))
        self.assertIsNotNone(asess.agy_chat_manifest_problem("not a dict"))

    def test_the_boundary_sentences_say_what_is_and_is_not_kept_in(self):
        boundary = self.prepare()["boundary"]
        self.assertEqual(set(boundary), {"write", "read", "network", "settings"})
        self.assertIn("sandbox", boundary["write"])
        self.assertIn("not isolated", boundary["read"])


class EveryLaunchReaderTests(LaunchCase):
    def test_flows_skip_an_agy_chat_launch(self):
        from vbear.runtime import stream_flow
        self.prepare()
        self.assertEqual(stream_flow.flow_sessions(self.base, "flow-0123456789ab", started=False), [])

    def test_cleanup_removes_it_and_leaves_the_chat_folder(self):
        m = self.prepare()
        res = asess.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertTrue(res["cleaned"], res)
        self.assertFalse(os.path.lexists(m["launch_dir"]["path"]))
        self.assertFalse(os.path.lexists(m["scratch"]["path"]))
        self.assertTrue(self.agy_home.is_dir())


if __name__ == "__main__":
    unittest.main()
