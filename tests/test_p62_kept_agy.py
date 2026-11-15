"""P62 (v0.26.0, ADR 0021): the AGY that VBear keeps. The chat check copies the AGY it checks into ``<state>/tools/agy/<version>/agy`` and
checks that very copy; the chat runs the copy only when every condition holds again, the whole file's SHA-256 included.

Synthetic HOME and state under /tmp. The only "agy" is a small script written by this test that prints a version; the real one is never
looked for, run or read. The scripts write nothing next to themselves (a kept folder must hold the one file)."""

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

from tests.test_p46_agy_chat_check import CheckCase, VERSION as CHECK_VERSION
from tests.test_p46_agy_chat_daemon import AgyCase, VERSION as DAEMON_VERSION
from vbear import agy_chat_check as cc, agy_verify, claude_verify, config as cfg
from vbear.api_error import ApiError
from vbear.runtime import agy_chat_env as env, agy_kept as kept, cli_versions


def fake_source(version: str, note: str = "") -> bytes:
    return f"#!{sys.executable}\nprint({version!r})\n# {note}\n".encode()


class KeptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="v62k.", dir="/tmp")))
        self.addCleanup(self._cleanup)
        self.home = self.tmp / "h"
        self.state = self.home / ".vbear"
        self.state.mkdir(parents=True, mode=0o700)
        for patch in (mock.patch.dict(os.environ, {"HOME": str(self.home), "VBEAR_HOME": str(self.state)}),
                      mock.patch.object(env, "CACHE_TTL_S", 0.0),
                      mock.patch("vbear.runtime.daemon.cli_search_path", return_value=str(self.tmp / "no-bin"))):
            patch.start()
            self.addCleanup(patch.stop)
        policy = self.tmp / "policy-root"
        policy.mkdir()
        patch = mock.patch.object(env, "POLICY_ROOT", str(policy))
        patch.start()
        self.addCleanup(patch.stop)
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir(mode=0o700)

    def _cleanup(self):
        for dirpath, dirnames, filenames in os.walk(self.tmp):
            for name in dirnames + filenames:
                full = os.path.join(dirpath, name)
                try:
                    if not os.path.islink(full):
                        os.chmod(full, 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers
    def install_agy(self, version="1.5.8", note="", mode=0o700, folder=None, name="agy"):
        folder = Path(folder) if folder else self.bindir
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / name
        path.write_bytes(fake_source(version, note))
        path.chmod(mode)
        return path

    def write_private(self, path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o600)

    def record_pass(self, version, sha=None, size=None, *, report_sha="same", report_size="same", with_hash=True):
        """The state a chat check that named its file leaves: the report (``agy_sha256``, ``agy_size``), then the record (``sha256``, ``size``)."""
        report = {"mode": "agy-chat", "passed": True, "agy_version": version}
        if report_sha == "same":
            report_sha = sha
        if report_size == "same":
            report_size = size
        if with_hash:
            if report_sha is not None:
                report["agy_sha256"] = report_sha
            if report_size is not None:
                report["agy_size"] = report_size
        self.write_private(self.state / f"agy-report-{version}.json", json.dumps(report))
        path = self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE
        try:
            versions = json.loads(path.read_text())["versions"]
        except (OSError, ValueError, KeyError):
            versions = {}
        entry = {"passed": True, "verified_at": "2026-11-13T10:00:00+0000", "binary": "x",
                 "report": str(self.state / f"agy-report-{version}.json"), "tool": "vbear.boundary_check --mode agy-chat"}
        if with_hash and sha is not None:
            entry["sha256"] = sha
        if with_hash and size is not None:
            entry["size"] = size
        versions[version] = entry
        self.write_private(path, json.dumps({"versions": versions}))

    def keep(self, version, note="", *, source=None):
        """What a passing chat check leaves, made through the real functions: the copy kept and the record naming it. Returns the copy's path."""
        source = source or self.install_agy(version, note, folder=self.tmp / f"src-{version}-{len(note)}")
        staged = kept.stage(self.state, os.path.realpath(source), version)
        self.record_pass(version, staged.sha256, staged.size)
        kept.promote(self.state, staged, version)
        return Path(kept.path_of(self.state, version))

    def names(self):
        return sorted(os.listdir(kept.root(self.state))) if os.path.isdir(kept.root(self.state)) else []

    def tamper(self, path, data=None):
        """Change the file though it is 0500 (what a program of the same user could do), keeping the size unless data is given."""
        path = Path(path)
        old = path.read_bytes()
        path.chmod(0o700)
        path.write_bytes(data if data is not None else old[:-1] + (b"X" if old[-1:] != b"X" else b"Y"))
        path.chmod(0o500)


class StageTests(KeptCase):
    def test_a_copy_is_made_new_private_and_read_only_with_the_hash_of_what_was_written(self):
        src = self.install_agy("1.5.8")
        staged = kept.stage(self.state, os.path.realpath(src), "1.5.8")
        data = src.read_bytes()
        self.assertEqual((staged.sha256, staged.size), (hashlib.sha256(data).hexdigest(), len(data)))
        self.assertTrue(kept.STAGING_RE.match(staged.name))
        self.assertEqual(staged.path, os.path.join(kept.root(self.state), staged.name, "agy"))
        self.assertEqual(Path(staged.path).read_bytes(), data)
        self.assertEqual(stat.S_IMODE(os.stat(staged.path).st_mode), 0o500)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(staged.path)).st_mode), 0o700)
        self.assertEqual(os.listdir(os.path.dirname(staged.path)), ["agy"])
        self.assertEqual(stat.S_IMODE(os.stat(kept.root(self.state)).st_mode), 0o700)
        self.assertEqual(src.read_bytes(), data, "the source is not touched")
        self.assertEqual(stat.S_IMODE(os.stat(src).st_mode), 0o700)

    def test_a_copy_that_prints_another_version_is_not_kept_and_leaves_nothing(self):
        src = self.install_agy("1.5.7")
        with self.assertRaises(env.AgyRefused) as ctx:
            with mock.patch.object(kept.time, "sleep"):
                kept.stage(self.state, os.path.realpath(src), "1.5.8")
        self.assertEqual(ctx.exception.code, "version_unreadable")
        self.assertEqual(self.names(), [])

    def test_a_source_that_others_can_write_or_that_is_a_link_or_not_this_users_is_refused(self):
        src = self.install_agy("1.5.8")
        src.chmod(0o722)
        with self.assertRaises(env.AgyRefused):
            kept.stage(self.state, os.path.realpath(src), "1.5.8")
        src.chmod(0o700)
        link = self.bindir / "agy-link"
        link.symlink_to(src)
        with self.assertRaises(OSError):                       # O_NOFOLLOW: the caller resolves the link first
            kept.stage(self.state, str(link), "1.5.8")
        with mock.patch.object(env, "_uid", return_value=os.getuid() + 1), mock.patch.object(env, "_trusted_owner", return_value=False):
            with self.assertRaises(env.AgyRefused):
                kept.stage(self.state, os.path.realpath(src), "1.5.8")
        self.assertEqual([n for n in self.names() if n.startswith("staging-")], [])

    def test_not_enough_room_or_a_failed_write_leaves_nothing(self):
        src = self.install_agy("1.5.8")
        little = os.statvfs_result((4096, 4096, 10, 1, 1, 10, 1, 1, 0, 255))
        with mock.patch.object(kept.os, "statvfs", return_value=little):
            with self.assertRaises(env.AgyRefused) as ctx:
                kept.stage(self.state, os.path.realpath(src), "1.5.8")
        self.assertIn("磁碟空間不夠", str(ctx.exception))
        self.assertEqual(self.names(), [])
        real_write = os.write

        def full(fd, data):
            raise OSError(28, "No space left on device")
        with mock.patch.object(kept.os, "write", full):
            with self.assertRaises(OSError):
                kept.stage(self.state, os.path.realpath(src), "1.5.8")
        self.assertEqual(self.names(), [])
        self.assertIs(os.write, real_write)

    def test_a_source_that_changes_while_it_is_copied_is_refused(self):
        src = self.install_agy("1.5.8")
        real_read = os.read
        done = []

        def grow(fd, n):
            data = real_read(fd, n)
            if data and not done:
                done.append(1)
                with open(src, "ab") as more:
                    more.write(b"# more\n")
            return data
        with mock.patch.object(kept.os, "read", grow):
            with self.assertRaises(env.AgyRefused):
                kept.stage(self.state, os.path.realpath(src), "1.5.8")
        self.assertEqual(self.names(), [])

    def test_a_program_of_an_unreasonable_size_is_refused(self):
        src = self.install_agy("1.5.8")
        with mock.patch.object(kept, "MAX_BYTES", 10):
            with self.assertRaises(env.AgyRefused):
                kept.stage(self.state, os.path.realpath(src), "1.5.8")
        self.assertEqual(self.names(), [])

    def test_the_folders_must_be_this_users_and_not_links(self):
        src = os.path.realpath(self.install_agy("1.5.8"))
        (self.state / "tools").symlink_to(self.tmp)
        with self.assertRaises(env.AgyRefused):
            kept.stage(self.state, src, "1.5.8")
        (self.state / "tools").unlink()
        (self.state / "tools").mkdir(mode=0o700)
        (self.state / "tools" / "agy").mkdir(mode=0o770)
        os.chmod(self.state / "tools" / "agy", 0o770)
        with self.assertRaises(env.AgyRefused):
            kept.stage(self.state, src, "1.5.8")
        os.chmod(self.state / "tools" / "agy", 0o755)          # readable by others is not private either
        with self.assertRaises(env.AgyRefused):
            kept.stage(self.state, src, "1.5.8")
        os.chmod(self.state / "tools" / "agy", 0o700)
        self.assertTrue(kept.stage(self.state, src, "1.5.8").path)
        os.chmod(self.state / "tools", 0o777)
        with self.assertRaises(env.AgyRefused):
            kept.stage(self.state, src, "1.5.8")

    def test_a_staging_folder_a_day_old_goes_and_a_new_one_or_one_with_something_else_in_it_stays(self):
        src = os.path.realpath(self.install_agy("1.5.8"))
        first = kept.stage(self.state, src, "1.5.8")
        old = os.path.dirname(first.path)
        os.utime(old, (1, 1))
        fresh = Path(kept.root(self.state)) / "staging-0123456789abcdef"
        fresh.mkdir(mode=0o700)
        odd = Path(kept.root(self.state)) / "staging-fedcba9876543210"
        odd.mkdir(mode=0o700)
        (odd / "notes.txt").write_text("not ours")
        os.utime(odd, (1, 1))
        other = Path(kept.root(self.state)) / "notes"
        other.mkdir(mode=0o700)
        os.utime(other, (1, 1))
        second = kept.stage(self.state, src, "1.5.8")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(fresh.exists() and odd.exists() and other.exists())
        kept.discard(self.state, second)
        self.assertFalse(os.path.exists(os.path.dirname(second.path)))

    def test_discard_removes_only_a_staging_folder_and_never_a_kept_copy(self):
        path = self.keep("1.5.8")
        kept.discard(self.state, kept.Staged("1.5.8", str(path), "0" * 64, 1))
        self.assertTrue(path.exists())
        kept.discard(self.state, kept.Staged("staging-0123456789abcdef", "x", "0" * 64, 1))        # not there: nothing happens


class PromoteTests(KeptCase):
    def test_a_staged_copy_becomes_the_copy_of_its_version(self):
        path = self.keep("1.5.8")
        self.assertEqual(str(path), os.path.join(kept.root(self.state), "1.5.8", "agy"))
        self.assertEqual(self.names(), ["1.5.8"])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o500)
        self.assertEqual(kept.choose(self.state).version, "1.5.8")

    def test_a_version_the_table_does_not_have_has_no_place(self):
        src = os.path.realpath(self.install_agy("1.5.8"))
        staged = kept.stage(self.state, src, "1.5.8")
        for bad in ("9.9.9", "1.5", "../1.5.8", "1.5.8/x", "", None):
            with self.subTest(version=bad):
                with self.assertRaises(env.AgyRefused):
                    kept.promote(self.state, staged, bad)
                with self.assertRaises(env.AgyRefused):
                    kept.path_of(self.state, bad)
        self.assertEqual(self.names(), [staged.name])

    def test_a_staged_copy_changed_before_it_is_kept_is_not_kept(self):
        staged = kept.stage(self.state, os.path.realpath(self.install_agy("1.5.8")), "1.5.8")
        self.tamper(staged.path)
        with self.assertRaises(env.AgyRefused):
            kept.promote(self.state, staged, "1.5.8")
        self.assertNotIn("1.5.8", self.names())

    def test_a_copy_of_the_same_version_is_replaced(self):
        self.keep("1.5.8", "one")
        path = self.keep("1.5.8", "two")
        self.assertEqual(self.names(), ["1.5.8"])
        self.assertIn(b"two", path.read_bytes())

    def test_a_folder_of_that_version_that_is_not_ours_to_remove_stops_the_keep(self):
        self.keep("1.5.8", "one")
        mine = Path(kept.root(self.state)) / "1.5.8"
        (mine / "extra.txt").write_text("something else")
        staged = kept.stage(self.state, os.path.realpath(self.install_agy("1.5.8", "two", folder=self.tmp / "s2")), "1.5.8")
        with self.assertRaises(env.AgyRefused):
            kept.promote(self.state, staged, "1.5.8")
        self.assertTrue((mine / "extra.txt").exists(), "nothing of it was removed")

    def test_two_copies_are_kept_in_all_and_the_oldest_goes(self):
        for version in ("1.5.3", "1.5.6", "1.5.7"):
            self.keep(version)
        self.assertEqual(self.names(), ["1.5.6", "1.5.7"])
        self.keep("1.5.8")
        self.assertEqual(self.names(), ["1.5.7", "1.5.8"])

    def test_a_copy_of_an_older_version_is_never_the_one_removed_by_its_own_keep(self):
        self.keep("1.5.7")
        self.keep("1.5.8")
        self.keep("1.5.6")                      # the person went back to an older AGY and checked it
        self.assertEqual(self.names(), ["1.5.6", "1.5.8"], "the new one and the newest other")

    def test_prune_removes_only_a_version_folder_of_this_user_that_holds_the_one_file(self):
        for version in ("1.5.3", "1.5.6"):
            self.keep(version)
        root = Path(kept.root(self.state))
        (root / "1.5.3" / "other").write_text("x")             # not only agy: left alone
        (root / "notes").mkdir(mode=0o700)                     # not a version: not looked at
        (root / "1.5.4").symlink_to(self.tmp)                  # a link named like a version: not followed, not removed
        self.keep("1.5.7")
        self.keep("1.5.8")
        left = self.names()
        self.assertIn("1.5.3", left)
        self.assertIn("notes", left)
        self.assertTrue((root / "1.5.4").is_symlink())
        self.assertTrue(self.tmp.exists())
        self.assertNotIn("1.5.6", left)
        self.assertEqual({"1.5.7", "1.5.8"} <= set(left), True)


class RecordTests(KeptCase):
    SHA = "a" * 64

    def test_a_record_counts_only_when_it_and_its_report_name_the_same_file(self):
        self.record_pass("1.5.8", self.SHA, 100)
        self.assertEqual(cli_versions.local_agy_chat_kept_records(self.state), {"1.5.8": {"sha256": self.SHA, "size": 100}})
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.8",), "the plain list is as it was")
        bad = {
            "no hash in the record": dict(sha=None, size=100),
            "no size in the record": dict(sha=self.SHA, size=None),
            "no hash in the report": dict(sha=self.SHA, size=100, report_sha=None),
            "another hash in the report": dict(sha=self.SHA, size=100, report_sha="b" * 64),
            "another size in the report": dict(sha=self.SHA, size=100, report_size=101),
            "a report that names none": dict(sha=self.SHA, size=100, with_hash=False),
            "upper case": dict(sha="A" * 64, size=100),
            "a short hash": dict(sha="a" * 63, size=100),
            "a size that is a bool": dict(sha=self.SHA, size=True),
            "a size of zero": dict(sha=self.SHA, size=0),
            "a size that is text": dict(sha=self.SHA, size="100"),
        }
        for why, kw in bad.items():
            with self.subTest(why):
                self.record_pass("1.5.8", **kw)
                self.assertEqual(cli_versions.local_agy_chat_kept_records(self.state), {}, why)
                self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.8",), "still passed as a version")

    def test_an_old_record_without_a_file_named_is_a_version_and_nothing_more(self):
        self.record_pass("1.5.7", with_hash=False)
        self.assertEqual(cli_versions.agy_chat_verified_versions(), ("1.5.7",))
        self.assertEqual(cli_versions.local_agy_chat_kept_records(self.state), {})

    def test_the_state_folder_can_be_given_and_the_configured_one_is_the_default(self):
        self.record_pass("1.5.8", self.SHA, 100)
        other = self.tmp / "other-state"
        other.mkdir(mode=0o700)
        self.assertEqual(cli_versions.local_agy_chat_kept_records(other), {})
        self.assertEqual(set(cli_versions.local_agy_chat_kept_records()), {"1.5.8"})


class VerifierKeepsTests(KeptCase):
    """The chat check's verifier (vbear/agy_verify.py) with a stand-in for the child process that does what the real child does: hash the file
    it was given, write the report and the record."""

    def setUp(self):
        super().setUp()
        self.path_patch = mock.patch("vbear.runtime.daemon.cli_search_path", return_value=str(self.bindir))
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.runs = []

    def child(self, *, rc=0, tell=None, write_record=True, sha=None):
        def run(argv, **kw):
            self.runs.append(argv)
            copy = argv[argv.index("--agy") + 1]
            file_sha, size = kept.hash_file(copy)
            out = Path(argv[argv.index("--out") + 1])
            version = tell or env.read_version(copy)
            report = {"mode": "agy-chat", "passed": rc == 0, "agy_version": version, "agy_sha256": sha or file_sha, "agy_size": size,
                      "shared": "passed", "shared_steps": {"a": {"pass": True}}}
            self.write_private(out, json.dumps(report))
            if rc == 0 and write_record:
                self.record_pass(version, sha or file_sha, size)
                versions = json.loads((self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).read_text())["versions"]
                versions[version]["report"] = str(out)
                self.write_private(self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE, json.dumps({"versions": versions}))
            return mock.Mock(returncode=rc, stdout="", stderr="")
        return run

    def verify(self, version="1.5.8", **kw):
        verifier = agy_verify.AgyChatVerifier()
        with mock.patch.object(claude_verify.subprocess, "run", self.child(**kw)):
            verifier._run("", version)
        return verifier.status()

    def test_the_check_runs_the_copy_and_a_pass_keeps_that_very_file(self):
        self.install_agy("1.5.8")
        status = self.verify()
        self.assertEqual((status["running"], status["result"]), (False, "passed"), status)
        self.assertIn("保存", status["message"])
        argv = self.runs[0]
        copy = argv[argv.index("--agy") + 1]
        self.assertTrue(copy.startswith(kept.root(self.state) + "/staging-"))
        self.assertIn("--shared", argv)
        self.assertEqual(self.names(), ["1.5.8"], "the staging folder was renamed, nothing is left")
        kept_path = kept.path_of(self.state, "1.5.8")
        self.assertEqual(Path(kept_path).read_bytes(), (self.bindir / "agy").read_bytes())
        self.assertEqual(kept.choose(self.state).binary, kept_path)

    def test_a_check_that_fails_keeps_nothing_and_leaves_nothing(self):
        self.install_agy("1.5.8")
        status = self.verify(rc=1)
        self.assertEqual(status["result"], "failed")
        self.assertEqual(self.names(), [])

    def test_a_pass_whose_record_names_another_file_is_not_kept(self):
        self.install_agy("1.5.8")
        status = self.verify(sha="c" * 64)
        self.assertEqual(status["result"], "error", status)
        self.assertIn("SHA-256", status["message"])
        self.assertEqual(self.names(), [])

    def test_a_pass_whose_record_names_no_file_is_not_kept(self):
        self.install_agy("1.5.8")
        verifier = agy_verify.AgyChatVerifier()

        def run(argv, **kw):                                     # an old-style child: version only
            out = Path(argv[argv.index("--out") + 1])
            self.write_private(out, json.dumps({"mode": "agy-chat", "passed": True, "agy_version": "1.5.8"}))
            self.record_pass("1.5.8", with_hash=False)
            versions = json.loads((self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).read_text())["versions"]
            versions["1.5.8"]["report"] = str(out)
            self.write_private(self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE, json.dumps({"versions": versions}))
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(claude_verify.subprocess, "run", run):
            verifier._run("", "1.5.8")
        self.assertEqual(verifier.status()["result"], "error")
        self.assertEqual(self.names(), [])

    def test_an_agy_that_changed_version_before_the_copy_is_not_copied(self):
        self.install_agy("1.5.9")
        status = self.verify("1.5.8")
        self.assertEqual(status["result"], "error")
        self.assertIn("1.5.9", status["message"])
        self.assertEqual(self.runs, [], "no check was started")
        self.assertEqual(self.names(), [])

    def test_no_agy_or_an_unsafe_one_starts_no_check(self):
        status = self.verify()
        self.assertEqual(status["result"], "error")
        self.assertEqual(self.runs, [])
        self.install_agy("1.5.8").chmod(0o722)
        status = self.verify()
        self.assertEqual(status["result"], "error")
        self.assertEqual(self.runs, [])

    def test_no_room_starts_no_check_and_says_so(self):
        self.install_agy("1.5.8")
        little = os.statvfs_result((4096, 4096, 10, 1, 1, 10, 1, 1, 0, 255))
        with mock.patch.object(kept.os, "statvfs", return_value=little):
            status = self.verify()
        self.assertEqual(status["result"], "error")
        self.assertIn("磁碟空間不夠", status["message"])
        self.assertEqual(self.runs, [])
        self.assertEqual(self.names(), [])

    def test_the_older_copies_beyond_two_go_and_the_message_says_which(self):
        self.keep("1.5.6")
        self.keep("1.5.7")
        self.install_agy("1.5.8")
        status = self.verify()
        self.assertEqual(status["result"], "passed", status)
        self.assertIn("1.5.6", status["message"])
        self.assertEqual(self.names(), ["1.5.7", "1.5.8"])

    def test_claude_and_codex_checks_keep_nothing_and_say_nothing_more(self):
        self.assertEqual(claude_verify.ChatVerifier()._keep("x", "1"), (None, ""))


class ChooseTests(KeptCase):
    """The bad samples: a copy that fails any one condition is never chosen, and the refusal is the one there was without copies."""

    def setUp(self):
        super().setUp()
        self.path = self.keep("1.5.7")
        self.install_agy("1.5.9", folder=self.bindir)             # AGY updated itself to a version VBear does not know

    def pin(self, **kw):
        return env.pinned_binary(str(self.bindir), base=self.state, **kw)

    def refused(self, code):
        with self.assertRaises(env.AgyRefused) as ctx:
            self.pin()
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        self.assertNotIn(str(self.tmp), str(ctx.exception))

    def test_the_good_copy_is_chosen_with_its_identity_and_hash(self):
        got = kept.choose(self.state)
        self.assertEqual((got.binary, got.version), (str(self.path), "1.5.7"))
        self.assertEqual(got.identity, env.cli_identity(str(self.path)))
        self.assertEqual(got.sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_a_changed_file_is_not_chosen_even_when_it_has_the_same_size_mode_and_version_text(self):
        self.tamper(self.path)
        self.assertEqual(len(self.path.read_bytes()), json.loads((self.state / "agy-report-1.5.7.json").read_text())["agy_size"])
        self.assertIsNone(kept.choose(self.state))
        self.refused("unsupported")

    def test_a_changed_size_is_not_chosen(self):
        self.tamper(self.path, self.path.read_bytes() + b"# more\n")
        self.assertIsNone(kept.choose(self.state))

    def test_a_version_the_table_does_not_know_is_not_chosen(self):
        (self.state / "agy-report-9.9.9.json").write_text("{}")
        os.rename(Path(kept.root(self.state)) / "1.5.7", Path(kept.root(self.state)) / "9.9.9")
        self.record_pass("9.9.9", *self._rec())
        self.assertIsNone(kept.choose(self.state))
        self.refused("unsupported")

    def _rec(self):
        data = self.path.read_bytes() if self.path.exists() else (Path(kept.root(self.state)) / "9.9.9" / "agy").read_bytes()
        return hashlib.sha256(data).hexdigest(), len(data)

    def test_a_copy_that_is_a_link_is_not_chosen(self):
        real = self.tmp / "elsewhere-agy"
        real.write_bytes(self.path.read_bytes())
        real.chmod(0o500)
        self.path.chmod(0o700)
        self.path.unlink()
        self.path.symlink_to(real)
        self.assertIsNone(kept.choose(self.state))
        self.refused("unsupported")

    def test_a_folder_that_is_a_link_is_not_chosen(self):
        folder = Path(kept.root(self.state)) / "1.5.7"
        moved = self.tmp / "moved"
        os.rename(folder, moved)
        folder.symlink_to(moved)
        self.assertIsNone(kept.choose(self.state))

    def test_a_file_or_folder_with_the_wrong_permissions_is_not_chosen(self):
        folder = self.path.parent
        for mode in (0o520, 0o550, 0o504, 0o700, 0o600, 0o400, 0o555):
            with self.subTest(file=oct(mode)):
                self.path.chmod(mode)
                self.assertIsNone(kept.choose(self.state))
        self.path.chmod(0o500)
        self.assertIsNotNone(kept.choose(self.state))
        for mode in (0o770, 0o750, 0o705, 0o755, 0o777):
            with self.subTest(folder=oct(mode)):
                folder.chmod(mode)
                self.assertIsNone(kept.choose(self.state))
        folder.chmod(0o700)
        self.assertIsNotNone(kept.choose(self.state))
        root = Path(kept.root(self.state))
        root.chmod(0o770)
        self.assertIsNone(kept.choose(self.state))
        root.chmod(0o700)
        (self.state / "tools").chmod(0o777)
        self.assertIsNone(kept.choose(self.state))
        (self.state / "tools").chmod(0o700)
        self.assertIsNotNone(kept.choose(self.state))

    def test_a_folder_of_someone_else_is_not_chosen(self):
        with mock.patch.object(kept.os, "getuid", return_value=os.getuid() + 1):
            self.assertIsNone(kept.choose(self.state))

    def test_a_copy_with_a_second_name_is_not_chosen(self):
        os.link(self.path, self.tmp / "another-name")
        self.assertIsNone(kept.choose(self.state))
        os.unlink(self.tmp / "another-name")
        self.assertIsNotNone(kept.choose(self.state))

    def test_a_folder_that_holds_anything_besides_the_one_file_is_not_chosen(self):
        for name in ("agy.1.old", "calls.log", ".hidden"):
            with self.subTest(name=name):
                extra = self.path.parent / name
                extra.write_text("x")
                self.assertIsNone(kept.choose(self.state))
                extra.unlink()
        self.assertIsNotNone(kept.choose(self.state))

    def test_a_copy_that_prints_another_version_is_not_chosen(self):
        self.tamper(self.path, fake_source("1.5.6", "same size, other version"))
        sha, size = hashlib.sha256(self.path.read_bytes()).hexdigest(), len(self.path.read_bytes())
        self.record_pass("1.5.7", sha, size)                      # even a record that names this file
        self.assertIsNone(kept.choose(self.state))

    def test_a_record_without_the_file_or_with_a_report_that_disagrees_is_not_used(self):
        data = self.path.read_bytes()
        sha, size = hashlib.sha256(data).hexdigest(), len(data)
        for why, kw in {"no hash": dict(sha=None, size=size), "report has another hash": dict(sha=sha, size=size, report_sha="d" * 64),
                        "report has another size": dict(sha=sha, size=size, report_size=size + 1),
                        "report names none": dict(sha=sha, size=size, with_hash=False), "record has another hash": dict(sha="e" * 64, size=size)}.items():
            with self.subTest(why):
                self.record_pass("1.5.7", **kw)
                self.assertIsNone(kept.choose(self.state))
                self.refused("unsupported")
        self.record_pass("1.5.7", sha, size)
        self.assertIsNotNone(kept.choose(self.state))

    def test_a_copy_with_no_pass_record_at_all_is_not_chosen(self):
        (self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).unlink()
        self.assertIsNone(kept.choose(self.state))
        self.refused("unsupported")

    def test_when_the_newest_copy_fails_the_next_older_one_is_used(self):
        newest = self.keep("1.5.8")
        self.assertEqual(kept.choose(self.state).version, "1.5.8")
        self.tamper(newest)
        self.assertEqual(kept.choose(self.state).version, "1.5.7")
        self.tamper(self.path)
        self.assertIsNone(kept.choose(self.state))

    def test_the_copy_is_looked_at_whole_every_time(self):
        calls = []
        real = kept._hash_fd

        def counting(fd):
            calls.append(1)
            return real(fd)
        with mock.patch.object(kept, "_hash_fd", counting):
            kept.choose(self.state)
            kept.choose(self.state)
        self.assertEqual(len(calls), 2)


class PinnedKeptTests(KeptCase):
    def setUp(self):
        super().setUp()
        self.path = self.keep("1.5.7")

    def pin(self, base="default", **kw):
        return env.pinned_binary(str(self.bindir), base=self.state if base == "default" else base, **kw)

    def refused(self, code, **kw):
        with self.assertRaises(env.AgyRefused) as ctx:
            self.pin(**kw)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception

    def test_an_agy_that_can_chat_is_used_and_the_copies_are_not_even_looked_at(self):
        installed = self.install_agy("1.5.8")
        self.record_pass("1.5.8", with_hash=False)
        with mock.patch.object(kept, "choose", side_effect=AssertionError("looked")):
            got = self.pin()
        self.assertEqual((got.binary, got.version, got.kept, got.installed), (os.path.realpath(installed), "1.5.8", False, None))

    def test_a_version_vbear_does_not_know_is_replaced_by_the_kept_copy(self):
        self.install_agy("1.5.9")
        got = self.pin()
        self.assertEqual((got.binary, got.version, got.kept, got.installed), (str(self.path), "1.5.7", True, "1.5.9"))
        self.assertEqual(got.identity, env.cli_identity(str(self.path)))

    def test_a_known_version_that_never_passed_is_replaced_too(self):
        self.install_agy("1.5.8")
        got = self.pin()
        self.assertEqual((got.version, got.kept, got.installed), ("1.5.7", True, "1.5.8"))

    def test_without_a_state_folder_nothing_is_kept(self):
        self.install_agy("1.5.9")
        exc = self.refused("unsupported", base=None)
        self.assertEqual(exc.version, "1.5.9")
        self.install_agy("1.5.8")
        self.refused("unverified", base=None)

    def test_no_agy_an_unsafe_one_or_one_without_a_readable_version_is_never_replaced(self):
        self.refused("not_installed")
        agy = self.install_agy("1.5.9")
        agy.chmod(0o722)
        self.refused("unsafe_binary")
        agy.chmod(0o700)
        agy.write_text(f"#!{sys.executable}\nprint('agy 1.5.9')\n")
        self.refused("version_unreadable")
        self.install_agy("1.5.9")
        self.assertEqual(self.pin().kept, True, "and with a good AGY on the path the copy is used")

    def test_the_newest_good_copy_is_the_one(self):
        self.keep("1.5.6")
        self.keep("1.5.8")
        self.install_agy("1.5.9")
        self.assertEqual(self.pin().version, "1.5.8")

    def test_a_bad_copy_leaves_the_original_refusal(self):
        self.install_agy("1.5.9")
        self.tamper(self.path)
        exc = self.refused("unsupported")
        self.assertEqual(exc.version, "1.5.9")
        self.assertIn("1.5.9", str(exc))


class StatusKeptTests(KeptCase):
    KEYS = {"state", "installed", "version", "verified", "shared_verified", "admin_policy_ok", "hooks_ok", "why", "verified_versions"}

    def status(self, **kw):
        return env.status(self.state, search_path=str(self.bindir), **kw)

    def test_ready_on_the_kept_version_with_the_installed_one_named(self):
        self.keep("1.5.7")
        self.install_agy("1.5.9")
        out = self.status()
        self.assertEqual((out["state"], out["version"], out["verified"], out["why"]), ("ready", "1.5.7", True, ""), out)
        self.assertEqual(out["kept"], {"using": "1.5.7", "installed": "1.5.9", "installed_state": "unsupported"})
        self.assertEqual(set(out), self.KEYS | {"kept"})
        self.assertNotIn(str(self.tmp), json.dumps(out), "no path in the answer")
        self.install_agy("1.5.8")
        self.assertEqual(self.status()["kept"], {"using": "1.5.7", "installed": "1.5.8", "installed_state": "unverified"})

    def test_there_is_no_kept_when_the_installed_one_chats_or_there_is_no_copy(self):
        self.install_agy("1.5.8")
        self.record_pass("1.5.8", with_hash=False)
        out = self.status()
        self.assertEqual((out["state"], out["version"]), ("ready", "1.5.8"))
        self.assertEqual(set(out), self.KEYS)
        self.install_agy("1.5.9")
        out = self.status()
        self.assertEqual((out["state"], out["version"], out["kept"] if "kept" in out else None), ("unsupported", "1.5.9", None))

    def test_the_other_states_still_come_first_for_the_version_that_runs(self):
        self.keep("1.5.7")
        self.install_agy("1.5.9")
        self.write_private(self.home / ".agents" / "hooks.json", "{}")
        self.assertEqual(self.status()["state"], "hooks")
        (self.home / ".agents" / "hooks.json").unlink()
        (self.state / "agy-chat-home").mkdir(mode=0o700)
        (self.state / "agy-chat-home" / "AGENTS.md").write_text("x")
        self.assertEqual(self.status()["state"], "folder")

    def test_a_caller_cannot_change_the_cached_answer(self):
        self.keep("1.5.7")
        self.install_agy("1.5.9")
        with mock.patch.object(env, "CACHE_TTL_S", 30.0):
            first = self.status()
            first["kept"]["using"] = "9.9.9"
            self.assertEqual(self.status()["kept"]["using"], "1.5.7")

    def test_tampered_copy_means_the_plain_refusal(self):
        path = self.keep("1.5.7")
        self.install_agy("1.5.9")
        self.tamper(path)
        out = self.status()
        self.assertEqual((out["state"], out["version"]), ("unsupported", "1.5.9"))
        self.assertNotIn("kept", out)


class LaunchCheckTests(KeptCase):
    """The daemon's look before it starts a file under the kept folder."""

    def setUp(self):
        super().setUp()
        self.path = self.keep("1.5.7")
        self.identity = env.cli_identity(str(self.path))

    def check(self, version="1.5.7", binary=None, identity="same"):
        return kept.check_for_launch(self.state, version, binary or str(self.path), self.identity if identity == "same" else identity)

    def test_the_good_copy_passes_and_a_file_elsewhere_is_not_its_business(self):
        self.assertTrue(self.check())
        self.assertFalse(self.check(binary=str(self.install_agy("1.5.8"))))
        self.assertFalse(kept.is_kept_path(self.state, str(self.tmp / "tools" / "agy" / "1.5.7" / "agy")))
        self.assertFalse(kept.is_kept_path(self.state, kept.root(self.state)), "the folder itself is not a file in it")

    def test_every_way_it_can_be_wrong_is_refused(self):
        with self.assertRaises(env.AgyRefused) as ctx:
            self.check(version="1.5.6")                     # no record for that version
        self.assertEqual(ctx.exception.code, "unverified")
        self.keep("1.5.8")
        with self.assertRaises(env.AgyRefused):
            self.check(version="1.5.8")                     # the path of 1.5.7 with the version 1.5.8
        with self.assertRaises(env.AgyRefused) as ctx:
            self.check(identity=[1, 2, 3, 4, 5, 6])
        self.assertEqual(ctx.exception.code, "drift")
        with self.assertRaises(env.AgyRefused):
            self.check(identity=None)
        with self.assertRaises(env.AgyRefused):
            self.check(binary=str(self.path) + "/../1.5.7/agy")
        self.tamper(self.path)
        with self.assertRaises(env.AgyRefused):
            self.check(identity=env.cli_identity(str(self.path)))
        (Path(kept.root(self.state)) / "1.5.7" / "other").write_text("x")
        with self.assertRaises(env.AgyRefused):
            self.check()

    def test_a_version_check_is_not_run_by_the_daemon(self):
        with mock.patch.object(env, "read_version", side_effect=AssertionError("ran")):
            self.assertTrue(self.check())


class ServiceKeptTests(KeptCase):
    """ChatService: the AGY it hands to the daemon is the kept copy, and the check it starts is for the installed version."""

    def setUp(self):
        super().setUp()
        from vbear import chat_service
        self.chat_service = chat_service

    def service(self, state, verifier=None):
        svc = self.chat_service.ChatService(None, agy=lambda: state, agy_verifier=verifier, base=self.state)
        return svc

    def test_the_binary_the_service_names_is_the_kept_copy(self):
        path = self.keep("1.5.7")
        self.install_agy("1.5.9")
        svc = self.chat_service.ChatService(None, base=self.state)
        with mock.patch("vbear.runtime.daemon.cli_search_path", return_value=str(self.bindir)):
            self.assertEqual(svc.agy_binary(), (str(path), "1.5.7"))
        self.assertIsNone(self.chat_service._default_agy_binary())

    def test_the_check_started_from_a_kept_state_is_for_the_installed_known_version(self):
        started = []

        class Stub:
            def start(self, binary, version):
                started.append((binary, version))
                return {"running": True}

            def status(self):
                return {"running": False}
        kept_state = {"state": "ready", "version": "1.5.7", "verified": True, "kept": {"using": "1.5.7", "installed": "1.5.8", "installed_state": "unverified"}}
        svc = self.service(kept_state, Stub())
        out = svc._verify_agy(None)
        self.assertEqual(started, [("", "1.5.8")])
        self.assertNotIn("already_verified", out)
        with self.assertRaises(ApiError) as ctx:
            svc._verify_agy("1.5.9")
        self.assertEqual(ctx.exception.code, "version_changed")

    def test_an_installed_version_vbear_does_not_know_has_nothing_to_check(self):
        class Stub:
            def start(self, binary, version):
                raise AssertionError("started")
        kept_state = {"state": "ready", "version": "1.5.7", "verified": True, "kept": {"using": "1.5.7", "installed": "1.5.9", "installed_state": "unsupported"}}
        with self.assertRaises(ApiError) as ctx:
            self.service(kept_state, Stub())._verify_agy(None)
        self.assertEqual(ctx.exception.code, "agy_version")
        self.assertIn("1.5.9", str(ctx.exception))


class DaemonKeptTests(AgyCase):
    """The daemon itself (a real one on its own socket, with the fake AGY of tests/fake_agy_acp.py as the kept copy): it looks at a file under
    the kept folder again, the whole file's SHA-256 included, whatever the console says about it."""

    def keep_the_fake(self):
        staged = kept.stage(self.base, os.path.realpath(self.binary), DAEMON_VERSION)
        report = self.base / "agy-report.json"
        report.write_text(json.dumps({"mode": "agy-chat", "passed": True, "agy_version": DAEMON_VERSION, "agy_sha256": staged.sha256,
                                      "agy_size": staged.size}))
        report.chmod(0o600)
        record = self.base / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE
        record.write_text(json.dumps({"versions": {DAEMON_VERSION: {
            "passed": True, "verified_at": "2026-11-13T10:00:00+0000", "report": str(report), "sha256": staged.sha256, "size": staged.size}}}))
        record.chmod(0o600)
        kept.promote(self.base, staged, DAEMON_VERSION)
        return kept.path_of(self.base, DAEMON_VERSION)

    def kept_cli(self, path):
        return self.cli(binary=path, identity=env.cli_identity(path))

    def test_a_chat_runs_the_kept_copy(self):
        self.configure("text")
        path = self.keep_the_fake()
        chat_id = self.open_chat()
        r = self.send(chat_id, cli=self.kept_cli(path))
        self.assertTrue(r["ok"], r)
        self.wait_turn(chat_id, 1)
        self.assertEqual(len(self.starts()), 1)

    def test_a_copy_that_was_changed_is_not_started_though_the_console_names_its_new_identity(self):
        self.configure("text")
        path = self.keep_the_fake()
        os.chmod(path, 0o700)
        with open(path, "ab") as more:
            more.write(b"# changed\n")
        os.chmod(path, 0o500)
        chat_id = self.open_chat()
        r = self.send(chat_id, cli=self.kept_cli(path))
        self.assertEqual(r["error"]["code"], "invalid_binary", r)
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_a_copy_with_no_record_of_its_file_is_not_started(self):
        self.configure("text")
        path = self.keep_the_fake()
        (self.base / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).unlink()
        chat_id = self.open_chat()
        r = self.send(chat_id, cli=self.kept_cli(path))
        self.assertEqual(r["error"]["code"], "unverified", r)
        self.assertEqual(self.starts(), [])

    def test_a_file_elsewhere_keeps_the_checks_it_always_had(self):
        self.configure("text")
        chat_id = self.open_chat()
        r = self.send(chat_id)
        self.assertTrue(r["ok"], r)


class CheckNamesTheFileTests(CheckCase):
    """The chat check (a whole run against the fake AGY of tests/fake_agy_acp_check.py) says which file it checked."""

    def test_the_report_and_the_record_carry_the_hash_and_size_of_the_file_that_was_checked(self):
        code, report = self.check()
        self.assertEqual(code, 0, report.get("error"))
        data = self.binary.read_bytes()
        self.assertEqual((report["agy_sha256"], report["agy_size"]), (hashlib.sha256(data).hexdigest(), len(data)))
        record = json.loads((self.state / cli_versions.LOCAL_AGY_CHAT_VERIFIED_FILE).read_text())["versions"][CHECK_VERSION]
        self.assertEqual((record["sha256"], record["size"]), (report["agy_sha256"], report["agy_size"]))
        self.assertEqual(cli_versions.local_agy_chat_kept_records(self.state), {CHECK_VERSION: {"sha256": record["sha256"], "size": record["size"]}})

    def test_a_file_that_is_not_the_same_after_the_run_is_not_a_pass(self):
        real = cc._run

        def swap(binary, *a, **kw):
            code = real(binary, *a, **kw)
            with open(binary, "ab") as more:
                more.write(b"\n# changed during the run\n")
            return code
        with mock.patch.object(cc, "_run", swap):
            code, report = self.check()
        self.assertNotEqual(code, 0)
        self.assertFalse(report["passed"])
        self.assertIn("不一樣", report["error"])
        self.assertEqual(self.verified(), (), "nothing is recorded")

    def test_the_agy_it_is_given_is_held_to_the_checks_of_the_one_found_on_the_search_path(self):
        import contextlib
        import io
        self.binary.chmod(0o722)
        buf = io.StringIO()
        with mock.patch.object(cc, "run", return_value=0) as run, contextlib.redirect_stdout(buf):
            code = cc.main(str(self.binary), str(self.out / "r.json"))
        self.assertEqual(code, 2)
        run.assert_not_called()
        self.assertIn("不使用它", buf.getvalue())
        self.binary.chmod(0o700)
        with mock.patch.object(cc, "run", return_value=0) as run, contextlib.redirect_stdout(buf):
            self.assertEqual(cc.main(str(self.binary), str(self.out / "r.json")), 0)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
