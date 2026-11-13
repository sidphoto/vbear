"""P59-2 (v0.25.4): the chat list and the start-up page's read of the chat state no longer start the AI tools on every read.

``cli_versions.check_cli_version_for_display`` keeps a reading that found a version for 30 seconds, under a key that carries the
program's file identity, and the launch-side checks (``check_cli_version``, ``assert_cli_version``, ``ensure_binary_unchanged``, the
chat's ``_claude_fields``, the chat check's ``_verify_claude``) never read it. Every program here is a small script in a temporary
folder that writes a line to a log when it is started; the clock is a function the test gives, nobody sleeps.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p59_fakes import Fakes, CLAUDE_VERSION, CODEX_VERSION, AGY_VERSION   # noqa: E402

from vbear import ai_tool_status, chat_service, claude_verify   # noqa: E402
from vbear.runtime import cli_versions as cv   # noqa: E402


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class ProgramCase(unittest.TestCase):
    """One fake ``claude`` that logs each start; ``self.read()`` is one display reading, ``self.starts()`` how many times it was started."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v59d.")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.cwd = self.root / "cwd"
        self.cwd.mkdir()
        self.log = self.root / "log"
        self.flag = self.root / "fail-flag"
        self.binary = self.root / "claude"
        self.write(CLAUDE_VERSION)
        self.clock = Clock()
        cv.invalidate_display_cache()
        self.addCleanup(cv.invalidate_display_cache)
        env = mock.patch.dict(os.environ, {"HOME": str(self.root), "PATH": "/usr/bin:/bin"})
        env.start()
        self.addCleanup(env.stop)

    def write(self, version, *, body=None, replace=False):
        text = (f'#!/bin/sh\necho "$*" >> {self.log}\n'
                f'[ -f {self.flag} ] && {{ echo "garbage"; exit 3; }}\n'
                + (body if body is not None else f'echo "{version} (Claude Code)"\n'))
        target = self.binary
        if replace:                                    # a new file moved over the old one: another inode
            target = self.root / "claude.new"
        target.write_text(text)
        target.chmod(0o700)
        if replace:
            os.replace(target, self.binary)

    def starts(self):
        try:
            return len(self.log.read_text().splitlines())
        except FileNotFoundError:
            return 0

    def read(self, **kw):
        kw.setdefault("allow_unverified", True)
        return cv.check_cli_version_for_display("claude", self.binary, cwd=self.cwd, clock=self.clock, **kw)


class DisplayCacheTests(ProgramCase):
    def test_two_reads_within_thirty_seconds_start_the_program_once(self):
        first = self.read()
        self.clock.now += 29.9
        second = self.read()
        self.assertEqual(self.starts(), 1)
        self.assertEqual((first.observed_version, second.observed_version), (CLAUDE_VERSION, CLAUDE_VERSION))
        self.assertTrue(first.compatible and second.compatible)

    def test_after_thirty_seconds_it_is_read_again(self):
        self.read()
        self.clock.now += cv.DISPLAY_CACHE_TTL_S
        self.read()
        self.assertEqual(self.starts(), 2)

    def test_the_ttl_is_the_one_of_the_start_up_page(self):
        self.assertEqual(cv.DISPLAY_CACHE_TTL_S, ai_tool_status.CACHE_TTL_S)
        self.assertEqual(cv.DISPLAY_CACHE_TTL_S, 30.0)

    def test_a_clock_that_went_backwards_does_not_keep_a_reading(self):
        self.read()
        self.clock.now -= 5
        self.read()
        self.assertEqual(self.starts(), 2)

    def test_a_program_rewritten_in_place_is_read_again_at_once(self):
        self.assertEqual(self.read().observed_version, CLAUDE_VERSION)
        self.write("2.1.319")
        self.clock.now += 1
        got = self.read()
        self.assertEqual(self.starts(), 2)
        self.assertEqual(got.observed_version, "2.1.319")

    def test_a_program_replaced_by_another_file_is_read_again_at_once(self):
        """What an automatic update does: a new file moved over the old name (another inode, the same words)."""
        self.read()
        before = os.stat(self.binary).st_ino
        self.write(CLAUDE_VERSION, replace=True)
        self.assertNotEqual(os.stat(self.binary).st_ino, before)
        self.read()
        self.assertEqual(self.starts(), 2)

    def test_only_the_mode_changing_is_read_again(self):
        self.read()
        os.chmod(self.binary, 0o500)
        self.read()
        self.assertEqual(self.starts(), 2)

    def test_a_reading_that_failed_is_never_kept(self):
        self.flag.write_text("x")
        self.assertFalse(self.read().compatible)
        self.assertFalse(self.read().compatible)
        self.assertEqual(self.starts(), 2)
        self.flag.unlink()
        self.assertTrue(self.read().compatible)
        self.assertEqual(self.starts(), 3)
        self.assertTrue(self.read().compatible)
        self.assertEqual(self.starts(), 3)

    def test_a_reading_with_too_much_output_or_no_version_is_never_kept(self):
        for body in ('python3 -c "print(\'x\' * 9000)"\n', 'echo "not a version"\n'):
            with self.subTest(body=body):
                self.write(CLAUDE_VERSION, body=body)
                before = self.starts()
                self.assertFalse(self.read().compatible)
                self.assertFalse(self.read().compatible)
                self.assertEqual(self.starts(), before + 2)

    def test_a_version_nobody_verified_is_kept_as_the_answer_it_is(self):
        """Without ``allow_unverified`` an unknown version is "blocked" but its version was read: that reading is kept, with its own key."""
        first = self.read(allow_unverified=False)
        self.assertFalse(first.compatible)
        self.assertEqual(first.error_code, "version_mismatch")
        self.read(allow_unverified=False)
        self.assertEqual(self.starts(), 1)
        self.read(allow_unverified=True)              # another key: the same program asked another question
        self.assertEqual(self.starts(), 2)

    def test_the_versions_the_engine_recognizes_are_part_of_the_key(self):
        self.read(allow_unverified=False)
        with mock.patch.object(cv, "verified_versions", return_value=(CLAUDE_VERSION,)):
            got = self.read(allow_unverified=False)
        self.assertEqual(self.starts(), 2)
        self.assertTrue(got.compatible)

    def test_the_folder_is_part_of_the_key(self):
        other = self.root / "other"
        other.mkdir()
        self.read()
        cv.check_cli_version_for_display("claude", self.binary, cwd=other, clock=self.clock, allow_unverified=True)
        self.assertEqual(self.starts(), 2)

    def test_invalidate_makes_the_next_read_start_the_program(self):
        self.read()
        cv.invalidate_display_cache()
        self.read()
        self.assertEqual(self.starts(), 2)

    def test_the_start_up_pages_invalidate_and_recheck_forget_it_too(self):
        self.read()
        ai_tool_status.invalidate()
        self.read()
        self.assertEqual(self.starts(), 2)
        # 「重新檢查」: report(force=True). No tool is looked at: nothing is listed, so nothing is started.
        with mock.patch.object(ai_tool_status.ai_tools, "visible_ids", return_value=[]):
            self.assertEqual(ai_tool_status.report({}, marks={}, force=True), [])
        self.read()
        self.assertEqual(self.starts(), 3)
        with mock.patch.object(ai_tool_status.ai_tools, "visible_ids", return_value=[]):
            ai_tool_status.report({}, marks={}, force=False)
        self.read()
        self.assertEqual(self.starts(), 3)

    def test_a_finished_chat_check_forgets_it(self):
        self.read()
        verifier = claude_verify.ChatVerifier()
        verifier._finish("failed", "x")
        self.read()
        self.assertEqual(self.starts(), 2)
        old = claude_verify.ClaudeVerifier()
        old._finish("failed", "x")
        self.read()
        self.assertEqual(self.starts(), 3)

    def test_few_readings_are_kept(self):
        folders = []
        for i in range(cv.DISPLAY_CACHE_MAX + 6):
            folder = self.root / f"f{i}"
            folder.mkdir()
            folders.append(folder)
            cv.check_cli_version_for_display("claude", self.binary, cwd=folder, clock=self.clock, allow_unverified=True)
        self.assertLessEqual(len(cv._display_cache), cv.DISPLAY_CACHE_MAX)
        self.clock.now += 100
        cv.check_cli_version_for_display("claude", self.binary, cwd=self.cwd, clock=self.clock, allow_unverified=True)
        self.assertEqual(len(cv._display_cache), 1)       # the old ones went with the first new reading

    def test_what_cannot_be_keyed_is_read_every_time_and_says_why(self):
        missing = self.root / "nope"
        for _ in range(2):
            got = cv.check_cli_version_for_display("claude", missing, cwd=self.cwd, clock=self.clock)
            self.assertEqual(got.error_code, "binary_not_found")
        got = cv.check_cli_version_for_display("nothing", self.binary, cwd=self.cwd, clock=self.clock)
        self.assertEqual(got.error_code, "unsupported_engine")
        self.assertEqual(self.starts(), 0)
        self.assertEqual(cv._display_cache, {})


class LaunchSideNeverReadsTheCacheTests(ProgramCase):
    def test_the_checks_that_start_things_start_the_program_even_when_a_reading_is_kept(self):
        self.read()
        self.assertEqual(self.starts(), 1)
        cv.check_cli_version("claude", self.binary, cwd=self.cwd, allow_unverified=True)
        self.assertEqual(self.starts(), 2)
        got = cv.assert_cli_version("claude", self.binary, cwd=self.cwd, allow_unverified=True)
        self.assertEqual(self.starts(), 3)
        cv.assert_agent_version  # (the alias for assert_cli_version: not a separate road)
        cv.ensure_binary_unchanged(got)                    # a launch result still carries the file identity
        self.read()
        self.assertEqual(self.starts(), 3)                 # and the display still has its reading

    def test_a_display_result_cannot_stand_in_for_a_launch_check(self):
        shown = self.read()
        self.assertTrue(shown.compatible)
        with self.assertRaises(cv.VersionAssertionError) as raised:
            cv.ensure_binary_unchanged(shown)
        self.assertEqual(raised.exception.code, "version_assertion_missing")
        hit = self.read()                                  # also the one that came from the memory
        with self.assertRaises(cv.VersionAssertionError):
            cv.ensure_binary_unchanged(hit)


class ChatServiceTests(unittest.TestCase):
    def test_reading_the_chat_list_again_does_not_start_the_tools_again(self):
        with Fakes() as f:
            f.assert_private()
            svc = chat_service.ChatService(None, base=f.state, profiles=lambda: [], profile=lambda pid: None)
            read = []
            for _ in range(3):
                before = f.counts()
                out = svc.list({})
                after = f.counts()
                read.append({k: after[k] - before[k] for k in after})
            self.assertEqual(out["support"]["state"], "verified")
            self.assertEqual(out["support"]["detected"], CLAUDE_VERSION)
            self.assertEqual(out["support"]["agy"]["version"], AGY_VERSION)
            self.assertEqual(out["support"]["codex"]["version"], CODEX_VERSION)
            self.assertEqual(read[0], {"claude": 1, "codex": 1, "agy": 1})
            self.assertEqual(read[1], {"claude": 0, "codex": 0, "agy": 0})
            self.assertEqual(read[2], {"claude": 0, "codex": 0, "agy": 0})

    def test_a_claude_that_was_updated_shows_at_the_next_read(self):
        with Fakes() as f:
            svc = chat_service.ChatService(None, base=f.state, profiles=lambda: [], profile=lambda pid: None)
            self.assertEqual(svc.support()["detected"], CLAUDE_VERSION)
            text = f.claude.read_text().replace(CLAUDE_VERSION, "2.1.319")
            f.claude.write_text(text)
            self.assertEqual(svc.support()["detected"], "2.1.319")
            self.assertEqual(len(f.calls("claude")), 2)

    def test_starting_a_chat_reads_claude_again_whatever_the_display_kept(self):
        with Fakes() as f:
            svc = chat_service.ChatService(None, base=f.state, profiles=lambda: [], profile=lambda pid: None)
            svc.support()
            svc.support()
            self.assertEqual(len(f.calls("claude")), 1)
            fields = svc._claude_fields("chat-1", "hello", {"model": {"tool": "claude"}})
            self.assertEqual(len(f.calls("claude")), 2)
            self.assertEqual(fields["cli"]["version"], CLAUDE_VERSION)
            svc._claude_fields("chat-1", "hello", {"model": {"tool": "claude"}})
            self.assertEqual(len(f.calls("claude")), 3)

    def test_the_chat_check_reads_claude_again_whatever_the_display_kept(self):
        class Verifier:
            def __init__(self):
                self.started = []

            def status(self):
                return {"running": False}

            def start(self, binary, version):
                self.started.append((binary, version))
                return {"running": True}

        with Fakes() as f:
            verifier = Verifier()
            svc = chat_service.ChatService(None, base=f.state, profiles=lambda: [], profile=lambda pid: None, verifier=verifier)
            svc.support()
            self.assertEqual(len(f.calls("claude")), 1)
            with mock.patch.object(chat_service.cli_versions, "chat_verified_versions", return_value=()):
                svc._verify_claude(None)
            self.assertEqual(len(f.calls("claude")), 2)
            self.assertEqual(verifier.started, [(str(f.claude), CLAUDE_VERSION)])

    def test_a_claude_function_that_was_given_or_replaced_is_used_for_showing_too(self):
        """A test (or a caller) that gives ``claude``, or replaces ``svc.claude`` afterwards, is never bypassed by the default kept reading."""
        calls = []

        def claude():
            calls.append("claude")
            return "/x/claude", CLAUDE_VERSION, ""
        given = chat_service.ChatService(None, claude=claude, base=tempfile.gettempdir())
        self.assertEqual(given.claude_display(), ("/x/claude", CLAUDE_VERSION, ""))
        replaced = chat_service.ChatService(None, base=tempfile.gettempdir())
        replaced.claude = lambda: ("/y/claude", "2.1.319", "")
        with mock.patch.object(chat_service, "_default_claude_for_display", side_effect=AssertionError("the default ran")):
            self.assertEqual(replaced.claude_display(), ("/y/claude", "2.1.319", ""))
        self.assertEqual(calls, ["claude"])
        own = chat_service.ChatService(None, claude=claude, claude_display=lambda: (None, None, "shown"), base=tempfile.gettempdir())
        self.assertEqual(own.claude_display(), (None, None, "shown"))
        self.assertEqual(own.claude()[1], CLAUDE_VERSION)

    def test_the_default_service_shows_with_the_kept_reading_and_starts_with_the_fresh_one(self):
        svc = chat_service.ChatService(None, base=tempfile.gettempdir())
        self.assertIs(svc.claude, chat_service._default_claude)
        with mock.patch.object(chat_service, "_default_claude_for_display", return_value=("/k/claude", "2.1.319", "")) as shown:
            self.assertEqual(svc.claude_display(), ("/k/claude", "2.1.319", ""))
        shown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
