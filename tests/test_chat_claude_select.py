"""P40-6: which Claude Code a chat runs. Before, a chat took the same pick as a terminal launch (the newest boundary-verified
version on disk, else whatever ``claude`` is on PATH), so a Mac whose only chat-ready Claude Code was not on PATH, or whose
PATH one was newer than VBear's constants, could not chat at all. Now a chat also considers the versions on disk that VBear has
chat constants for.

Seams: ``native._pinned_claude_chat_binary`` (a temporary HOME with fake version files; no process is started),
``chat_service._default_claude`` (what it hands the version check) and ``ChatService.support()`` (the words for the person)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import chat_service
from vbear.runtime import chat_protocol as cp, native


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cs-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.versions = self.home / ".local/share/claude/versions"
        self.versions.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def on_disk(self, *names, kind="file"):
        for n in names:
            if kind == "file":
                (self.versions / n).write_text("#!/bin/sh\n")
            else:
                (self.versions / n).mkdir()

    def verified(self, *versions):
        patch = mock.patch.object(native._cli_versions, "chat_verified_versions", return_value=tuple(versions))
        patch.start()
        self.addCleanup(patch.stop)

    def pick(self):
        return native._pinned_claude_chat_binary()

    def test_the_newest_version_with_chat_constants_on_disk_is_picked(self):
        self.verified()
        self.on_disk("2.1.318", "2.1.319")
        self.assertEqual(self.pick(), str(self.versions / "2.1.319"))

    def test_a_version_that_passed_the_chat_check_is_preferred_to_a_newer_one_that_did_not(self):
        self.verified("2.1.318")
        self.on_disk("2.1.318", "2.1.319")
        self.assertEqual(self.pick(), str(self.versions / "2.1.318"))
        self.verified("2.1.318", "2.1.319")
        self.assertEqual(self.pick(), str(self.versions / "2.1.319"))

    def test_a_version_without_constants_or_not_a_file_is_never_picked(self):
        self.verified("2.1.400")                  # verified in some record, but VBear has no constants for it
        self.on_disk("2.1.296", "2.1.400", "2.1.320")        # launch-verified, unknown, unknown
        self.on_disk("2.1.319", kind="dir")                  # a folder is not a program
        self.assertIsNone(self.pick())

    def test_nothing_on_disk_leaves_the_choice_to_path(self):
        self.verified()
        self.assertIsNone(self.pick())

    def test_the_launch_pick_is_not_changed(self):
        """A terminal launch still takes only boundary-verified versions: the chat's constants say nothing about those."""
        self.on_disk("2.1.318", "2.1.319")
        with mock.patch.object(native._cli_versions, "verified_versions", return_value=("2.1.296",)):
            self.assertIsNone(native._pinned_claude_binary())
        self.on_disk("2.1.296")
        with mock.patch.object(native._cli_versions, "verified_versions", return_value=("2.1.296",)):
            self.assertEqual(native._pinned_claude_binary(), str(self.versions / "2.1.296"))


class DefaultClaudeTests(unittest.TestCase):
    def test_the_chat_asks_the_version_check_about_the_chat_pick(self):
        seen = []

        def check(engine, binary, **kw):
            seen.append((engine, binary, kw.get("allow_unverified")))
            return mock.Mock(compatible=True, observed_version="2.1.319", binary_path="/x/claude", reason="")
        with mock.patch.object(native, "_pinned_claude_chat_binary", return_value="/x/versions/2.1.319"), \
                mock.patch.object(chat_service.cli_versions, "check_cli_version", check):
            self.assertEqual(chat_service._default_claude(), ("/x/claude", "2.1.319", ""))
        self.assertEqual(seen, [("claude", "/x/versions/2.1.319", True)])


class SupportWordsTests(unittest.TestCase):
    def support(self, version, verified=()):
        svc = chat_service.ChatService(mock.Mock(), claude=lambda: ("/x/claude", version, ""), base=tempfile.gettempdir())
        with mock.patch.object(chat_service.cli_versions, "CHAT_VERIFIED_VERSIONS", tuple(verified)), \
                mock.patch.object(chat_service.cli_versions, "local_chat_verified_versions", return_value={}), \
                mock.patch.object(chat_service.admin_policy, "check_claude", return_value=mock.Mock(ok=True, found=[], problems=[], reason=lambda: "")):
            return svc.support()

    def test_a_path_version_with_constants_can_be_verified(self):
        got = self.support("2.1.319")
        self.assertEqual((got["state"], got["detected"]), ("unverified", "2.1.319"))
        self.assertEqual(self.support("2.1.319", verified=("2.1.319",))["state"], "verified")

    def test_a_version_without_constants_is_told_in_plain_words_which_ones_work(self):
        got = self.support("2.1.399")
        self.assertEqual(got["state"], "unsupported")
        for part in ("2.1.399", *sorted(cp.VERSIONS)):
            self.assertIn(part, got["message"])
        self.assertIn("安裝", got["message"])
        self.assertIn("等 VBear 更新", got["message"])


if __name__ == "__main__":
    unittest.main()
