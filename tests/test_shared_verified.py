"""P43-2 (ADR 0009): which versions of an AI tool have passed the chat check WITH the shared folder. A version counts only when this Mac's
record names a report that passed the chat check and says ``shared: passed`` in its own words; a report from before v0.17.1 has no such
word and counts for nothing here, whatever it says of the chat check. Synthetic HOME and state folder; no AI tool is run."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import config as cfg
from vbear.runtime import cli_versions


class StateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vsv-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "h" / ".vbear"
        self.state.mkdir(parents=True, mode=0o700)
        env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "h"), "VBEAR_HOME": str(self.state), "VBEAR_RUNTIME_AUTOSTART": "0"})
        env.start()
        self.addCleanup(env.stop)

    def record(self, engine, version, **report):
        mode, key, file_name = (("chat", "claude_version", cli_versions.LOCAL_CHAT_VERIFIED_FILE) if engine == "claude-chat"
                                else ("codex-chat", "codex_version", cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE))
        body = {"mode": mode, "passed": True, key: version}
        body.update(report)
        out = self.tmp / f"{engine}-report.json"
        out.write_text(json.dumps(body))
        out.chmod(0o600)
        cfg.write_private(self.state / file_name, json.dumps({"versions": {
            version: {"passed": True, "verified_at": "2026-11-07T00:00:00+0000", "report": str(out)}}}))


class SharedVerifiedTests(StateCase):
    def test_nothing_is_built_in(self):
        self.assertEqual(cli_versions.chat_shared_verified_versions(), ())
        self.assertEqual(cli_versions.codex_chat_shared_verified_versions(), ())
        self.assertFalse(cli_versions.shared_verified("claude-chat", "2.1.319"))

    def test_a_report_that_says_shared_passed_counts_for_its_own_tool_only(self):
        self.record("claude-chat", "2.1.319", shared="passed")
        self.assertEqual(cli_versions.chat_shared_verified_versions(), ("2.1.319",))
        self.assertTrue(cli_versions.shared_verified("claude-chat", "2.1.319"))
        self.assertFalse(cli_versions.shared_verified("codex-chat", "2.1.319"))
        self.assertEqual(cli_versions.codex_chat_shared_verified_versions(), ())
        self.record("codex-chat", "0.163.0", shared="passed")
        self.assertTrue(cli_versions.shared_verified("codex-chat", "0.163.0"))
        self.assertFalse(cli_versions.shared_verified("claude-chat", "0.163.0"))

    def test_a_report_from_before_this_check_failed_or_odd_words_do_not_count(self):
        for what in ({}, {"shared": "failed"}, {"shared": True}, {"shared": "PASSED"}, {"shared": None}, {"shared": ["passed"]}):
            for engine, version in (("claude-chat", "2.1.319"), ("codex-chat", "0.163.0")):
                with self.subTest(what=what, engine=engine):
                    self.record(engine, version, **what)
                    self.assertFalse(cli_versions.shared_verified(engine, version))
                    # the chat check itself still counts: only the shared folder is unchecked
                    base = cli_versions.chat_verified_versions() if engine == "claude-chat" else cli_versions.codex_chat_verified_versions()
                    self.assertEqual(base, (version,))

    def test_a_shared_pass_of_a_report_that_failed_the_chat_check_counts_for_nothing(self):
        self.record("claude-chat", "2.1.319", shared="passed", passed=False)
        self.assertFalse(cli_versions.shared_verified("claude-chat", "2.1.319"))
        self.record("claude-chat", "2.1.319", shared="passed", mode="stream")
        self.assertFalse(cli_versions.shared_verified("claude-chat", "2.1.319"))

    def test_a_missing_report_a_bad_version_or_a_bad_input_do_not_count(self):
        self.record("claude-chat", "2.1.319", shared="passed")
        (self.tmp / "claude-chat-report.json").unlink()
        self.assertFalse(cli_versions.shared_verified("claude-chat", "2.1.319"))
        for bad in (None, 5, "", "latest", ["2.1.319"]):
            self.assertFalse(cli_versions.shared_verified("claude-chat", bad))
        self.assertFalse(cli_versions.shared_verified("claude", "2.1.319"), "an engine name, not a tool name")
        self.assertFalse(cli_versions.shared_verified(None, "2.1.319"))

    def test_the_text_says_what_to_do_for_each_tool(self):
        claude = cli_versions.shared_unverified_text("claude-chat", "2.1.319")
        codex = cli_versions.shared_unverified_text("codex-chat", "0.163.0")
        self.assertIn("2.1.319", claude)
        self.assertIn("共用資料夾", claude)
        self.assertIn("ChatGPT", codex)
        self.assertIn("0.163.0", codex)
        self.record("claude-chat", "2.1.318", shared="passed")
        self.assertIn("2.1.318", cli_versions.shared_unverified_text("claude-chat", "2.1.319"))


if __name__ == "__main__":
    unittest.main()
