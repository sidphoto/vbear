"""A chat process as a managed launch (P36-1): engine "claude-chat" under sessions/, its settings and argv, the checks
before it starts, and the places that read every launch (flows, cleanup). Synthetic HOME and VBEAR_HOME; nothing is
started."""

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
from vbear.runtime import chat_protocol as cp
from vbear.runtime import chat_store as cs
from vbear.runtime import cli_versions
from vbear.runtime import stream_flow

VERSION = "2.1.318"


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcl-")))
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

    def prepare(self, **over):
        args = dict(workdir=self.work, cli_binary=str(self.cli), cli_version=VERSION,
                    cli_identity=asess.binary_identity(str(self.cli)), model_id="claude-haiku-5-5",
                    chat_id="c-0123456789abcdef", profile_id="emp-1", claude_session_id=self.sid,
                    budget_usd=0.5, resume=False)
        args.update(over)
        m = asess.prepare_chat_launch(self.base, **args)
        self.addCleanup(asess.cleanup_launch, self.base, m["launch_id"], proven_dead=True)
        return m


class PrepareTests(LaunchCase):
    def test_settings_manifest_and_argv(self):
        m = self.prepare()
        self.assertEqual(m["engine"], "claude-chat")
        self.assertIsNone(asess.chat_manifest_problem(m))
        settings = json.loads(Path(m["settings_path"]).read_text())
        uid = os.getuid()
        self.assertEqual(settings, {
            "sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                        "autoAllowBashIfSandboxed": False,
                        "filesystem": {"allowWrite": [self.work, m["scratch"]["path"]],
                                       "denyWrite": [f"/private/tmp/claude-{uid}", f"/tmp/claude-{uid}"]},
                        "network": {"allowedDomains": [], "strictAllowlist": True}},
            "permissions": {"ask": ["Bash"], "additionalDirectories": []},
            "env": dict(cp.VERSIONS[VERSION].pinned_env)})
        self.assertEqual(stat.S_IMODE(os.lstat(m["settings_path"]).st_mode), 0o600)
        self.assertEqual(asess.chat_argv(m), [
            str(self.cli), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
            "--permission-mode", "default", "--safe-mode", "--settings", m["settings_path"], "--setting-sources", "",
            "--strict-mcp-config", "--tools", "Bash,Read,Edit,Write,Grep,Glob", "--max-budget-usd", "0.50", "--model", "claude-haiku-5-5",
            "--session-id", self.sid])
        r = self.prepare(resume=True, budget_usd=0.25)
        self.assertEqual(asess.chat_argv(r)[-6:], ["--max-budget-usd", "0.25", "--model", "claude-haiku-5-5",
                                                    "--resume", self.sid])
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["chat_id"], "c-0123456789abcdef")

    def test_a_cards_own_instructions_are_appended_to_the_system_prompt_and_nothing_else_changes(self):
        plain = self.prepare()
        text = "先說結論。\n不要用表情符號。"
        m = self.prepare(append_prompt=text)
        self.assertIsNone(asess.chat_manifest_problem(m))
        self.assertEqual(m["append_prompt"], text)
        argv = asess.chat_argv(m)
        i = argv.index("--append-system-prompt")
        self.assertEqual(argv[i + 1], text)
        self.assertEqual(argv[i - 2:i], ["--tools", "Bash,Read,Edit,Write,Grep,Glob"])      # after the tools, before the budget
        self.assertEqual(argv[:i] + argv[i + 2:], [a if a != plain["settings_path"] else m["settings_path"]
                                                    for a in asess.chat_argv(plain)])
        self.assertNotIn("--append-system-prompt", asess.chat_argv(plain))
        self.assertNotIn("append_prompt", plain)
        self.assertEqual(asess.load_validated(self.base, m["launch_id"])["append_prompt"], text)
        resumed = asess.chat_argv(self.prepare(append_prompt=text, resume=True))
        self.assertEqual(resumed[-2:], ["--resume", self.sid])
        self.assertEqual(resumed[resumed.index("--append-system-prompt") + 1], text)

    def test_instructions_that_could_not_be_a_cards_are_refused(self):
        for bad in ("", "   \n", 5, ["x"], "a\x00b", "a\x07b", "a\u202eb", "x" * 9001):
            with self.subTest(bad=bad if not isinstance(bad, str) else bad[:12]):
                with self.assertRaises(asess.LaunchRefused):
                    self.prepare(append_prompt=bad)
        self.assertEqual(self.prepare(append_prompt="x" * 2000)["append_prompt"], "x" * 2000)
        self.assertEqual(self.prepare(append_prompt="x" * 8000)["append_prompt"], "x" * 8000, "P42-1: room for the memory paragraph")
        self.assertEqual(self.prepare(append_prompt=None).get("append_prompt"), None)
        m = self.prepare(append_prompt="ok")
        for bad in ("", 5, "a\x00b", "x" * 9001):
            self.assertIsNotNone(asess.chat_manifest_problem(dict(m, append_prompt=bad)), repr(bad)[:20])

    def test_refused_before_anything_is_made(self):
        other = self.tmp / "elsewhere"
        other.mkdir(mode=0o700)
        cases = [dict(workdir=str(other)), dict(workdir=str(self.base)), dict(workdir=str(self.home)),
                 dict(cli_version="2.1.296"), dict(model_id="bad model"), dict(chat_id="../x"),
                 dict(profile_id="../x"), dict(claude_session_id="nope"), dict(budget_usd=0),
                 dict(budget_usd=float("nan")), dict(budget_usd=0.123), dict(resume="yes")]
        for over in cases:
            with self.assertRaises(asess.LaunchRefused, msg=over):
                self.prepare(**over)
        self.assertFalse((self.base / "sessions").exists() and os.listdir(self.base / "sessions"))

    def test_a_terminal_launch_never_runs_a_chat_manifest(self):
        m = self.prepare()
        with self.assertRaises(asess.LaunchRefused):
            asess.managed_argv(m)

    def test_drift_is_refused(self):
        m = self.prepare()
        settings = Path(m["settings_path"])
        data = json.loads(settings.read_text())
        data["permissions"]["additionalDirectories"] = ["/x"]
        os.chmod(settings, 0o600)
        settings.write_text(json.dumps(data))
        with self.assertRaises(asess.LaunchRefused):
            asess.load_validated(self.base, m["launch_id"])

    def test_a_changed_manifest_is_refused(self):
        m = self.prepare()
        for field, value in (("chat_id", "nope"), ("resume", 1), ("budget_usd", -1), ("extra", 1),
                             ("cli_version", "2.1.296")):
            bad = dict(m, **{field: value})
            self.assertIsNotNone(asess.chat_manifest_problem(bad), field)


class EveryLaunchReaderTests(LaunchCase):
    def test_flows_skip_a_chat_launch(self):
        self.prepare()
        self.assertEqual(stream_flow.flow_sessions(self.base, "flow-0123456789ab", started=False), [])

    def test_cleanup_removes_it(self):
        m = self.prepare()
        res = asess.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertTrue(res["cleaned"], res)
        self.assertFalse(os.path.lexists(m["launch_dir"]["path"]))
        self.assertFalse(os.path.lexists(m["scratch"]["path"]))


class VerifiedTests(LaunchCase):
    def test_no_version_is_chat_verified_without_a_local_report(self):
        self.assertEqual(cli_versions.CHAT_VERIFIED_VERSIONS, ())
        self.assertEqual(cli_versions.chat_verified_versions(), ())
        report = self.base / "chat-report.json"
        report.write_text(json.dumps({"mode": "chat", "passed": True, "claude_version": VERSION}))
        report.chmod(0o600)
        rec = self.base / cli_versions.LOCAL_CHAT_VERIFIED_FILE
        rec.write_text(json.dumps({"versions": {VERSION: {"passed": True, "report": str(report),
                                                          "verified_at": "2026-11-05T00:00:00Z"}}}))
        rec.chmod(0o600)
        self.assertEqual(cli_versions.chat_verified_versions(), (VERSION,))
        report.write_text(json.dumps({"mode": "stream", "passed": True, "claude_version": VERSION}))
        self.assertEqual(cli_versions.chat_verified_versions(), ())
        self.assertIn(VERSION, cli_versions.chat_unverified_text(VERSION))


if __name__ == "__main__":
    unittest.main()
