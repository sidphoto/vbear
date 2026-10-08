"""Identifier patterns end with \\Z, not $ (S2a-1 finding, fixed in S2a-2).

In Python ``$`` also matches just before a trailing newline, so
``re.match(r"^l-[0-9a-f]{16}$", "l-0123456789abcdef\\n")`` succeeds. These
patterns guard values that name files and directories, select sessions or
authenticate; each must refuse a trailing newline (and any other trailing
whitespace), at the pattern and where it is used."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import agent_profiles, flows, git_head, git_objects, server, tasks
from vbear.runtime import agent_sessions, cli_versions, daemon, native

GOOD = {
    "tasks.VALID_ID_RE": (tasks.VALID_ID_RE, "task-0123abcd"),
    "agent_profiles.VALID_PROFILE_ID_RE": (agent_profiles.VALID_PROFILE_ID_RE, "prof-0123abcd"),
    "agent_sessions.LAUNCH_RE": (agent_sessions.LAUNCH_RE, "l-0123456789abcdef"),
    "agent_sessions.MODEL_ID_RE": (agent_sessions.MODEL_ID_RE, "claude-haiku-4-5-20251001"),
    "daemon.SESSION_RE": (daemon.SESSION_RE, "n-0123456789ab"),
    "native.SESSION_RE": (native.SESSION_RE, "n-0123456789ab"),
    "server._TOKEN_RE": (server._TOKEN_RE, "A" * 43),
    "cli_versions._VERSION_RE": (cli_versions._VERSION_RE, "2.1.292"),
    "git_head.SHA_RE": (git_head.SHA_RE, "a" * 40),
    "git_head.REF_RE": (git_head.REF_RE, "refs/heads/main"),
    "git_objects.SHA_RE": (git_objects.SHA_RE, "a" * 64),
    "flows.COMMIT_RE": (flows.COMMIT_RE, "a" * 40),
    "flows.FLOW_ID_RE": (flows.FLOW_ID_RE, "flow-0123456789ab"),
    "flows.SESSION_RE": (flows.SESSION_RE, "n-0123456789ab"),
}


class PatternTests(unittest.TestCase):
    def test_trailing_newline_and_whitespace_are_refused(self):
        for name, (pattern, good) in GOOD.items():
            with self.subTest(pattern=name):
                self.assertTrue(pattern.match(good), "the sample itself must be valid")
                for tail in ("\n", "\r\n", "\n\n", " ", "\t", "\x00"):
                    self.assertIsNone(pattern.match(good + tail), repr(tail))
                self.assertIsNone(pattern.match("\n" + good))


class UseSiteTests(unittest.TestCase):
    def test_launch_directory(self):
        base = Path(tempfile.mkdtemp(prefix="vbre-"))
        self.addCleanup(lambda: os.rmdir(base))
        self.assertTrue(str(agent_sessions.launch_dir(base, "l-0123456789abcdef")).endswith("l-0123456789abcdef"))
        with self.assertRaises(agent_sessions.LaunchRefused):
            agent_sessions.launch_dir(base, "l-0123456789abcdef\n")

    def test_task_id(self):
        home = tempfile.mkdtemp(prefix="vbre-st-")
        with mock.patch.dict(os.environ, {"VBEAR_HOME": home}):
            with self.assertRaises(ValueError):
                tasks.save_task("task-abc\n", {"title": "t"})
            self.assertIsNone(tasks.get_task("task-abc\n"))

    def test_handed_token(self):
        good = "A" * 43
        for value, expected in ((good, good), (good + "\n", None)):
            with mock.patch.dict(os.environ, {server.HANDED_TOKEN_ENV: value}):
                self.assertEqual(server.take_handed_token(), expected)

    def test_native_target(self):
        rt = native.NativeRuntime(Path(tempfile.gettempdir()))
        self.assertTrue(rt.validate_target("n-0123456789ab"))
        self.assertFalse(rt.validate_target("n-0123456789ab\n"))


if __name__ == "__main__":
    unittest.main()
