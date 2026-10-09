"""Daemon-side storage for stream executors: per-flow files (3.5, 7, planner
Q1), the quota ledger (9), the flow context (planner Q1/Q3/Q4) and the
claude-stream launch (2.1). Every flows.json, .claude.json and key is
synthetic; nothing reads the user's real files."""

import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import stream_fixtures as fx
from vbear import acceptance as acc
from vbear import flows, login_identity, tasks
from vbear.runtime import agent_sessions as a
from vbear.runtime import cli_versions
from vbear.runtime import pipeline_store as ps
from vbear.runtime import quota, stream_flow, stream_journal, stream_protocol as sp

NAN, INF = float("nan"), float("inf")


LID = "l-0123456789abcdef"


class StateDir(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbss-")))
        self.base.chmod(0o700)
        self.addCleanup(shutil.rmtree, self.base, True)
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base)})
        p.start()
        self.addCleanup(p.stop)


class PipelineStoreTests(StateDir):
    def test_text_write_zero_progress_fails_and_cleans_partial(self):
        d = fx.new_uuid()
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            with mock.patch.object(ps.os, "write", side_effect=[0, 0, 0, OSError(5, "stop test loop")]) as write:
                with self.assertRaises(OSError):
                    p.write_text(d, b"hello")
            write.assert_called_once()
            dispatches = self.base / "pipelines" / "task-1" / "dispatches"
            self.assertEqual(os.listdir(dispatches), [])

    def test_text_write_order_and_no_overwrite(self):
        d = fx.new_uuid()
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            p.write_text(d, b"hello")
            self.assertEqual(p.read_text(d), b"hello")
            self.assertEqual(p.text_names(), [d])
            with self.assertRaises(FileExistsError):
                p.write_text(d, b"other")
            self.assertEqual(p.read_text(d), b"hello")
        path = self.base / "pipelines" / "task-1" / "dispatches" / f"{d}.txt"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(sorted(os.listdir(path.parent)), [f"{d}.txt"])      # no partial left

    def test_partials_are_removed_on_recovery(self):
        d = fx.new_uuid()
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            (self.base / "pipelines" / "task-1" / "dispatches" / f".{d}.partial").write_bytes(b"half")
            self.assertEqual(p.text_names(), [])
            self.assertEqual(p.remove_partials(), [d])
            self.assertEqual(os.listdir(self.base / "pipelines" / "task-1" / "dispatches"), [])

    def test_refusals(self):
        for task in ("..", ".", "a/b", "task\n", "", None, "x" * 65):
            with self.subTest(task=task), self.assertRaises(ps.StoreRefused):
                ps.Pipeline(self.base, task, create=True)
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            for bad in ("x", fx.new_uuid().upper(), fx.new_uuid() + "\n", None):
                with self.subTest(dispatch=bad), self.assertRaises(ps.StoreRefused):
                    p.write_text(bad, b"x")
            with self.assertRaises(ps.StoreRefused):
                p.write_text(fx.new_uuid(), b"x" * (sp.MAX_DISPATCH_LINE + 1))
            (self.base / "pipelines" / "task-1" / "dispatches" / "stray").write_text("x")
            with self.assertRaises(ps.StoreRefused):
                p.text_names()                                   # counts must be exact
        shutil.rmtree(self.base / "pipelines" / "task-1")
        os.mkdir(self.base / "pipelines" / "real", 0o700)
        os.symlink(self.base / "pipelines" / "real", self.base / "pipelines" / "task-2")
        with self.assertRaises(ps.StoreRefused):
            ps.Pipeline(self.base, "task-2", create=True)       # a symlinked flow directory
        os.chmod(self.base / "pipelines" / "real", 0o755)
        os.mkdir(self.base / "pipelines" / "task-3", 0o755)
        with self.assertRaises(ps.StoreRefused):
            ps.Pipeline(self.base, "task-3", create=True)       # not private

    def test_symlinked_text_is_refused(self):
        d = fx.new_uuid()
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            target = self.base / "elsewhere.txt"
            target.write_bytes(b"x")
            os.symlink(target, self.base / "pipelines" / "task-1" / "dispatches" / f"{d}.txt")
            with self.assertRaises(ps.StoreRefused):
                p.read_text(d)
            with self.assertRaises(ps.StoreRefused):
                p.text_names()

    def test_started_record(self):
        fid = "flow-0123456789ab"
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            self.assertIsNone(p.started_at(fid))
            t = p.record_start(fid, time.time(), launch_id=LID, base_commit=fx.BASE_COMMIT)
            self.assertEqual(p.started_at(fid), t)
            self.assertEqual(p.start_record(), {"pipeline_id": fid, "launch_id": LID, "base_commit": fx.BASE_COMMIT,
                                                "started_at": t})
            self.assertEqual(p.record_start(fid, time.time() + 100, launch_id=LID, base_commit=fx.BASE_COMMIT), t)   # first start is kept
            for bad_id in ("l-xyz", LID + "\n", None):
                with self.assertRaises(ps.StoreRefused):
                    p.record_start(fid, time.time(), launch_id=bad_id, base_commit=fx.BASE_COMMIT)
            for bad_base in ("xyz", fx.BASE_COMMIT + "\n", fx.BASE_COMMIT[:39], None, "B" * 40):
                with self.assertRaises(ps.StoreRefused):
                    p.record_start(fid, time.time(), launch_id=LID, base_commit=bad_base)
            self.assertEqual(p.start_record()["base_commit"], fx.BASE_COMMIT)
        path = self.base / "pipelines" / "task-1" / "started.json"
        good = {"v": 2, "pipeline_id": fid, "launch_id": LID, "base_commit": fx.BASE_COMMIT}
        bad = [{**good, "pipeline_id": "flow-ffffffffffff", "started_at": t}, dict(good),
               {**good, "v": 1, "started_at": t}, {**good, "v": True, "started_at": t},
               {**good, "started_at": 1.0}, {**good, "started_at": time.time() + 10 * 86400},
               {**good, "started_at": True}, {**good, "started_at": "1"}, {**good, "started_at": t, "x": 1},
               {"v": 2, "pipeline_id": fid, "launch_id": LID, "started_at": t},    # no base_commit
               {"v": 1, "pipeline_id": fid, "launch_id": LID, "started_at": t},    # the v1 record (v29.7/8)
               {**good, "base_commit": "xyz", "started_at": t}, {**good, "base_commit": None, "started_at": t},
               {**good, "base_commit": fx.BASE_COMMIT.upper(), "started_at": t},
               {"v": 1, "pipeline_id": fid, "started_at": t},                      # no launch id (pre-v29.7)
               {**good, "launch_id": "l-xyz", "started_at": t}, {**good, "launch_id": None, "started_at": t}]
        for value in bad + ["NaN", "Infinity"]:
            with self.subTest(value=repr(value)[:60]):
                raw = json.dumps(value).encode() if isinstance(value, dict) else \
                    f'{{"v": 2, "pipeline_id": "{fid}", "launch_id": "{LID}", "base_commit": "{fx.BASE_COMMIT}", '\
                    f'"started_at": {value}}}'.encode()
                path.chmod(0o600)
                path.write_bytes(raw)
                with ps.Pipeline(self.base, "task-1", create=False) as p, self.assertRaises(ps.StoreRefused):
                    p.started_at(fid)

    def test_directory_sync_failure_is_reported(self):
        real = os.fsync

        def dir_fsync_fails(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "Input/output error")
            return real(fd)
        fid = "flow-0123456789ab"
        ps.hold(self.base, fid, "prior")
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            with mock.patch("vbear.runtime.pipeline_store.os.fsync", dir_fsync_fails):
                with self.assertRaises(ps.StoreRefused):
                    p.write_text(fx.new_uuid(), b"text")
                with self.assertRaises(ps.StoreRefused):
                    p.record_start(fid, time.time(), launch_id=LID, base_commit=fx.BASE_COMMIT)
                with self.assertRaises(ps.StoreRefused):
                    ps.hold(self.base, fid, "stop")
                warnings = []
                self.assertTrue(ps.release(self.base, fid, warnings=warnings))
                self.assertEqual(warnings, ["hold_removal_not_durable"])
            # outside the injection everything works again
            d = fx.new_uuid()
            p.write_text(d, b"ok")
            self.assertEqual(p.read_text(d), b"ok")

    def test_failed_hold_release_reports_warning_after_durable_release_record(self):
        fid = "flow-0123456789ab"
        ps.hold(self.base, fid, "stop")
        warnings = []
        with mock.patch.object(ps, "_fsync_dir", side_effect=ps.StoreRefused("sync failed")):
            self.assertTrue(ps.release(self.base, fid, warnings=warnings))
        self.assertEqual(warnings, ["hold_removal_not_durable"])
        self.assertFalse(ps.is_held(self.base, fid))

    def test_release_does_not_recreate_hold_after_directory_sync_failure(self):
        fid = "flow-0123456789ab"
        ps.hold(self.base, fid, "stop")
        warnings = []
        with mock.patch.object(ps, "_fsync_dir", side_effect=ps.StoreRefused("sync failed")), \
                mock.patch.object(ps, "hold", side_effect=OSError(28, "disk full")) as restore:
            self.assertTrue(ps.release(self.base, fid, warnings=warnings))
        restore.assert_not_called()
        self.assertEqual(warnings, ["hold_removal_not_durable"])
        self.assertFalse(ps.is_held(self.base, fid))

    def test_release_crash_replay_prefers_reappearing_hold(self):
        fid = "flow-0123456789ab"
        ps.hold(self.base, fid, "stop")
        warnings = []
        with mock.patch.object(ps, "_fsync_dir", side_effect=ps.StoreRefused("sync failed")):
            self.assertTrue(ps.release(self.base, fid, warnings=warnings))
        # Model a crash in which the unsynced unlink is lost. The marker is
        # visible again, so a restarted daemon still stops the flow.
        ps.hold(self.base, fid, "stop")
        self.assertTrue(ps.is_held(self.base, fid))

    def test_journal_creation_syncs_directory_and_fails_closed(self):
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            with mock.patch.object(stream_journal.os, "fsync", side_effect=OSError(5, "sync failed")):
                with self.assertRaises(OSError):
                    stream_journal.JournalWriter(p.fd)
            self.assertFalse((self.base / "pipelines" / "task-1" / "journal.jsonl").exists())

    def test_review_links(self):
        # the flow's own record of each review job (S2b part 1 review P2)
        fid, job = "flow-0123456789ab", "r-0123456789abcdef"
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            self.assertEqual(p.review_links(), {})
            p.write_review_link(1, job, fid, "a" * 40)
            p.write_review_link(7, "r-0123456789abcdee", fid, "b" * 64)
            self.assertEqual(p.review_links()[1], {"job_id": job, "pipeline_id": fid, "commit": "a" * 40})
            self.assertEqual(sorted(p.review_links()), [1, 7])
            with self.assertRaises(FileExistsError):                      # exclusive: a round has one record
                p.write_review_link(1, "r-0123456789abcdee", fid, "a" * 40)
            self.assertEqual(p.review_links()[1]["job_id"], job)
            for bad in ((0, job, fid, "a" * 40), (ps.ROUND_MAX + 1, job, fid, "a" * 40), (True, job, fid, "a" * 40),
                        (2, "r-xyz", fid, "a" * 40), (2, job, "flow-x", "a" * 40), (2, job, fid, "xyz"),
                        (2, job + "\n", fid, "a" * 40)):
                with self.subTest(bad=bad), self.assertRaises(ps.StoreRefused):
                    p.write_review_link(*bad)
            real = os.write

            def half_then_fail(fd, data):
                if not hasattr(half_then_fail, "n"):
                    half_then_fail.n = 1
                    return real(fd, bytes(data)[:5])
                raise OSError(28, "No space left on device")
            with mock.patch.object(ps.os, "write", half_then_fail), self.assertRaises(OSError):
                p.write_review_link(9, job, fid, "a" * 40)
            self.assertEqual(sorted(p.review_links()), [1, 7])               # no half record, no empty round either
            self.assertEqual(sorted(n.name for n in (self.base / "pipelines" / "task-1" / "reviews").iterdir()),
                             ["1", "7"])
        for name in (".", "0", "01", "1001", "x"):
            d = self.base / "pipelines" / "task-1" / "reviews" / name
            if name in (".",):
                continue
            d.mkdir(mode=0o700, exist_ok=True)
            with self.subTest(entry=name), ps.Pipeline(self.base, "task-1", create=False) as p, \
                    self.assertRaises(ps.StoreRefused):
                p.review_links()
            d.rmdir()

    def test_remove_start_only_undoes_the_record_just_written(self):
        fid = "flow-0123456789ab"
        with ps.Pipeline(self.base, "task-abc", create=True) as p:
            t = p.record_start(fid, time.time(), launch_id=LID, base_commit=fx.BASE_COMMIT)
            with self.assertRaises(ps.StoreRefused):
                p.remove_start(fid, t - 1)                                  # not the one written
            with self.assertRaises(ps.StoreRefused):
                p.remove_start(fid, t, launch_id="l-ffffffffffffffff")       # another launch's
            with self.assertRaises(ps.StoreRefused):
                p.remove_start("flow-ffffffffffff", t)                      # another flow's
            self.assertEqual(p.started_at(fid), t)
            p.remove_start(fid, t)
            self.assertIsNone(p.started_at(fid))

    def test_release_record_holds_failure_identities(self):
        # Review round 6 #1: identities, accumulated, at most RESOLVED_MAX.
        fid = "flow-0123456789ab"
        ids = [f"{LID}#3", f"{LID}#manual_review#1791467063.473483"]
        with ps.Pipeline(self.base, "task-1", create=True) as p:
            self.assertIsNone(p.release_record(fid))
            p.record_release(fid, time.time(), ids)
            self.assertEqual(p.release_record(fid)["resolved"], set(ids))
            with self.assertRaises(ps.StoreRefused):
                p.record_release(fid, time.time(), [f"{LID}#{n}" for n in range(1, ps.RESOLVED_MAX + 2)])
            for bad in ([f"{LID}#0"], ["l-xyz#3"], [f"{LID}#3\n"], [f"{LID}#manual_review#x"]):
                with self.subTest(bad=bad), self.assertRaises(ps.StoreRefused):
                    p.record_release(fid, time.time(), bad)
            self.assertEqual(p.release_record(fid)["resolved"], set(ids))      # unchanged by the refusals
        path = self.base / "pipelines" / "task-1" / "released.json"
        for value in ({"v": 1, "pipeline_id": fid, "released_at": time.time()},           # the time-only format
                      {"v": 2, "pipeline_id": fid, "released_at": time.time(), "resolved": ids + ids[:1]},
                      {"v": 2, "pipeline_id": fid, "released_at": time.time(), "resolved": "x"}):
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                path.chmod(0o600)
                with ps.Pipeline(self.base, "task-1", create=False) as p, self.assertRaises(ps.StoreRefused):
                    p.release_record(fid)

    def test_writes_are_complete_or_fail(self):
        # Review round 7 B-1: short writes are continued; a failure leaves
        # neither a half record nor a temp file, and the old record stays.
        fid = "flow-0123456789ab"
        real = os.write

        def halves(fd, data):
            data = bytes(data)
            return real(fd, data[:max(1, len(data) // 2)])
        with mock.patch.object(ps.os, "write", halves), mock.patch.object(a.os, "write", halves):
            with ps.Pipeline(self.base, "task-1", create=True) as p:
                t = p.record_start(fid, time.time(), launch_id=LID, base_commit=fx.BASE_COMMIT)
                p.record_release(fid, time.time(), [f"{LID}#3"])
                self.assertEqual(p.started_at(fid), t)
                self.assertEqual(p.release_record(fid)["resolved"], {f"{LID}#3"})
            ps.hold(self.base, fid, "stop")
            self.assertTrue(ps.is_held(self.base, fid))
            a._write_private(self.base / "x.json", json.dumps({"k": "v" * 100}))
        self.assertEqual(json.loads((self.base / "x.json").read_text()), {"k": "v" * 100})
        calls = []

        def half_then_fail(fd, data):
            calls.append(fd)
            if len(calls) % 2 == 1:
                return real(fd, bytes(data)[:len(data) // 2])
            raise OSError(28, "No space left on device")
        with mock.patch.object(ps.os, "write", half_then_fail), mock.patch.object(a.os, "write", half_then_fail):
            with ps.Pipeline(self.base, "task-2", create=True) as p:
                with self.assertRaises(OSError):
                    p.record_start(fid, time.time(), launch_id=LID, base_commit=fx.BASE_COMMIT)
                self.assertIsNone(p.start_record())                           # no half record
            with ps.Pipeline(self.base, "task-1", create=False) as p:
                with self.assertRaises(OSError):
                    p.record_release(fid, time.time(), [f"{LID}#4"])
                self.assertEqual(p.release_record(fid)["resolved"], {f"{LID}#3"})   # the old one stays
            ps.release(self.base, fid)
            with self.assertRaises(OSError):
                ps.hold(self.base, fid, "stop")
            self.assertFalse(ps.is_held(self.base, fid))
            with self.assertRaises(OSError):
                a._write_private(self.base / "y.json", json.dumps({"k": "v" * 100}))
            self.assertFalse((self.base / "y.json").exists())
        leftovers = [p.name for p in self.base.rglob("*") if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_private_replace_syncs_parent_directory(self):
        path = self.base / "replace.json"
        a._write_private(path, '{"old": true}')
        real_fsync = os.fsync

        def fail_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "directory sync failed")
            return real_fsync(fd)

        with mock.patch.object(a.os, "fsync", fail_directory_sync):
            with self.assertRaises(OSError):
                a._write_private(path, '{"new": true}', replace=True)
        self.assertEqual(path.read_text(), '{"new": true}')

    def test_holds(self):
        fid = "flow-0123456789ab"
        self.assertFalse(ps.is_held(self.base, fid))
        ps.hold(self.base, fid, "使用者按了停止\x1b[31m")
        self.assertTrue(ps.is_held(self.base, fid))
        data = json.loads((self.base / "holds" / fid).read_text())
        self.assertNotIn("\x1b", data["reason"])
        self.assertTrue(ps.release(self.base, fid))
        self.assertFalse(ps.is_held(self.base, fid))
        self.assertFalse(ps.release(self.base, fid))
        for bad in ("flow-x", "../x", None, fid + "\n"):
            self.assertTrue(ps.is_held(self.base, bad))            # cannot rule it out: held
            with self.assertRaises(ps.StoreRefused):
                ps.hold(self.base, bad, "x")
        (self.base / "holds").chmod(0o000)
        self.assertTrue(ps.is_held(self.base, fid))                 # unreadable: held
        (self.base / "holds").chmod(0o700)
        # R4 audit: a state directory that is missing or not a directory is
        # not "no holds".
        self.assertTrue(ps.is_held(self.base / "no-such-state", fid))
        (self.base / "a-file").write_text("x")
        self.assertTrue(ps.is_held(self.base / "a-file", fid))


class QuotaTests(StateDir):
    def test_scan_and_reservations(self):
        (self.base / "sessions" / "l-x").mkdir(parents=True)
        (self.base / "sessions" / "l-x" / "f").write_bytes(b"x" * 1000)
        (self.base / "pipelines").mkdir()
        (self.base / "pipelines" / "g").write_bytes(b"y" * 24)
        (self.base / "other").write_bytes(b"z" * 10_000)                    # not a protected root
        self.assertEqual(quota.scan(self.base), 1024)
        led = quota.Ledger(self.base, limit=5000)
        self.assertIsNotNone(led.reserve("a", 1))                           # not rebuilt yet
        self.assertTrue(led.rebuild({"old": 2000}))
        self.assertIsNone(led.reserve("a", 1900))
        self.assertIsNotNone(led.reserve("b", 100))                          # 1024 + 2000 + 1900 + 100 > 5000
        self.assertIsNotNone(led.reserve("a", 1))                            # same key twice
        led.release("a", 50)
        self.assertEqual(led.used, 1074)
        self.assertIsNone(led.reserve("b", 1900))

    def test_amounts_must_be_byte_counts(self):
        # Codex S2a-2 p1 #2
        led = quota.Ledger(self.base, limit=100)
        for bad in ({"x": -1}, {"x": True}, {"x": 1.5}, {"x": "5"}, {"x": quota.HARD_LIMIT + 1}, {1: 5}, ["x"]):
            with self.subTest(outstanding=bad):
                self.assertFalse(led.rebuild(bad))
        self.assertTrue(led.rebuild({}))
        for bad in (-1, True, False, 1.5, "1", None, quota.HARD_LIMIT + 1):
            with self.subTest(amount=bad):
                self.assertIsNotNone(led.reserve("k", bad))
        self.assertEqual(led.free(), 100)

    def test_an_overrun_is_counted_in_full_and_stops_further_grants(self):
        led = quota.Ledger(self.base, limit=1000)
        self.assertTrue(led.rebuild({}))
        self.assertIsNone(led.reserve("w", 1))
        led.release("w", 100)                         # wrote more than it reserved
        self.assertEqual(led.used, 100)
        self.assertIn("超過", led.reserve("next", 1))
        self.assertTrue(led.rebuild({}))              # a fresh scan clears it
        self.assertIsNone(led.reserve("next", 1))
        led.release("next", True)                      # not a byte count: worst case, then refuse
        self.assertEqual(led.used, 1)
        self.assertIsNotNone(led.reserve("again", 1))
        self.assertTrue(led.rebuild({}))
        led.release("never-reserved", 5)
        self.assertIsNotNone(led.reserve("again", 1))

    def test_anything_unexpected_refuses(self):
        (self.base / "sessions").mkdir()
        os.symlink("/etc", self.base / "sessions" / "link")
        led = quota.Ledger(self.base)
        self.assertFalse(led.rebuild({}))
        self.assertIn("人工", led.problem)
        self.assertIsNotNone(led.reserve("a", 1))
        (self.base / "sessions" / "link").unlink()
        os.mkfifo(self.base / "sessions" / "fifo")
        self.assertFalse(led.rebuild({}))
        (self.base / "sessions" / "fifo").unlink()
        self.assertFalse(led.rebuild(None))                                  # writers unknown
        with mock.patch.object(quota, "SCAN_MAX_ENTRIES", 0):
            (self.base / "sessions" / "f").write_text("x")
            self.assertFalse(led.rebuild({}))
        self.assertTrue(led.rebuild({}))


def claude_json(path: Path, account="11111111-2222-3333-4444-555555555555",
                org="66666666-7777-8888-9999-000000000000"):
    path.write_text(json.dumps({"oauthAccount": {"accountUuid": account, "organizationUuid": org}}))
    return path


class FlowContextTests(StateDir):
    def setUp(self):
        super().setUp()
        self.tid = tasks.save_task(None, {"title": "t"})["id"]
        roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
                 "reviewers": [{"name": "c", "family": "openai"}]}
        self.fid = flows.create_flow({"task_id": self.tid, "roles": roles}, lambda t: True)["id"]
        self.key = login_identity.create_login_key(self.base, valid_acceptances=0)
        self.cj = claude_json(self.base / "claude.json")
        self.fp = login_identity.claude_login_fingerprint(self.cj, self.key).hmac

    def launch(self, **fields) -> Path:
        """A real claude-stream manifest for this flow (prepare_stream_launch),
        then ``fields`` set as the daemon would."""
        work = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbss-fw-")))
        self.addCleanup(shutil.rmtree, work, True)
        # Not in the state directory: writing a private file there tightens
        # every entry to 0600 (config.ensure_state_dir), executables included.
        binary = work / "claude"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o700)
        m = a.prepare_stream_launch(self.base, str(work), cli_binary=str(binary), cli_version="2.1.292",
                                    cli_identity=a.binary_identity(str(binary)), model_id=fx.MODEL,
                                    pipeline_id=self.fid, task_id=self.tid, allowed_root=str(work.parent))
        self.addCleanup(shutil.rmtree, m["scratch"]["path"], True)
        if fields:
            a.update_manifest(self.base, m["launch_id"], **fields)
        return Path(m["launch_dir"]["path"])

    def accept(self, **over):
        fields = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
                  "executor_claude_version": "2.1.292", "executor_model": fx.MODEL,
                  "executor_login_fingerprint": self.fp, "login_fingerprint": "b" * 64,
                  "login_key_id": self.key.key_id, "limits": dict(acc.DEFAULT_LIMITS)}
        fields.update(over)
        with flows.store.locked():
            data = flows.store.load()
            ev = data[self.fid]["events"]
            ev.append({"seq": len(ev) + 1, "at": time.time(), "kind": "risk_acknowledged", "source": "console",
                       "note": "", **fields})
            flows.store.save(data)

    def test_needs_a_valid_acceptance(self):
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.load(self.base, self.fid)
        self.assertEqual(cm.exception.code, "no_acceptance")
        self.accept()
        ctx = stream_flow.load(self.base, self.fid)
        self.assertEqual((ctx.task_id, ctx.limits), (self.tid, acc.DEFAULT_LIMITS))
        stream_flow.check_executor(ctx, cli_version="2.1.292", model_id=fx.MODEL, claude_json=str(self.cj))

    def test_latest_acceptance_wins_and_executor_must_match(self):
        self.accept(limits={**acc.DEFAULT_LIMITS, "max_dispatches": 3})
        self.accept(limits={**acc.DEFAULT_LIMITS, "max_dispatches": 4})
        ctx = stream_flow.load(self.base, self.fid)
        self.assertEqual(ctx.limits["max_dispatches"], 4)
        for kw in ({"cli_version": "2.1.291", "model_id": fx.MODEL},
                   {"cli_version": "2.1.292", "model_id": "claude-other-1"}):
            with self.subTest(kw=kw), self.assertRaises(stream_flow.FlowRefused):
                stream_flow.check_executor(ctx, claude_json=str(self.cj), **kw)
        claude_json(self.cj, account="99999999-2222-3333-4444-555555555555")      # another account
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_executor(ctx, cli_version="2.1.292", model_id=fx.MODEL, claude_json=str(self.cj))
        self.assertEqual(cm.exception.code, "reaccept")
        self.cj.unlink()
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_executor(ctx, cli_version="2.1.292", model_id=fx.MODEL, claude_json=str(self.cj))
        self.assertEqual(cm.exception.code, "no_login")

    def test_key_lost_voids_the_acceptance(self):
        self.accept()
        (self.base / login_identity.KEY_NAME).unlink()
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.load(self.base, self.fid)
        self.assertEqual(cm.exception.code, "no_acceptance")
        login_identity.create_login_key(self.base, valid_acceptances=0)
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.load(self.base, self.fid)

    def test_flows_json_is_read_strictly_and_never_repaired(self):
        self.accept()
        path = self.base / "flows.json"
        good = path.read_bytes()
        for raw in (good[:-5], good.replace(b'"note": ""', b'"note": NaN', 1), b"[]",
                    good.replace(b'"seq": 1,', b'"seq": 1, "seq": 1,', 1)):
            with self.subTest(raw=raw[:40]):
                path.write_bytes(raw)
                with self.assertRaises(stream_flow.FlowRefused) as cm:
                    stream_flow.load(self.base, self.fid)
                self.assertEqual(cm.exception.code, "flow_unavailable")
                self.assertFalse((self.base / "flows.json.corrupted").exists())   # read-only: no quarantine
                self.assertEqual(path.read_bytes(), raw)

    def test_sessions_root_must_be_sound(self):
        # Codex S2a-2 p1 R2 #1
        root = self.base / "sessions"
        self.assertEqual(stream_flow.flow_sessions(self.base, self.fid, started=False), [])
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.flow_sessions(self.base, self.fid, started=True)          # started, nothing left
        root.write_text("not a directory")
        for started in (False, True):
            with self.subTest(case="file", started=started), self.assertRaises(stream_flow.FlowRefused):
                stream_flow.flow_sessions(self.base, self.fid, started=started)
        root.unlink()
        real = self.base / "elsewhere"
        real.mkdir(mode=0o700)
        root.symlink_to(real)
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.flow_sessions(self.base, self.fid, started=False)
        root.unlink()
        root.mkdir(mode=0o700)
        root.chmod(0o000)
        try:
            with self.assertRaises(stream_flow.FlowRefused):
                stream_flow.flow_sessions(self.base, self.fid, started=False)
        finally:
            root.chmod(0o700)
        # a started flow whose sessions are gone: through load()
        self.accept()
        with ps.Pipeline(self.base, self.tid, create=True) as p:
            p.record_start(self.fid, time.time(), launch_id=LID, base_commit=fx.BASE_COMMIT)
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.load(self.base, self.fid)
        self.assertEqual(cm.exception.code, "count_unavailable")

    def test_limits(self):
        self.accept(limits={**acc.DEFAULT_LIMITS, "max_dispatches": 2, "max_elapsed_h": 1,
                            "executor_total_max_responses": 10, "executor_budget_usd": 5.0})
        ctx = stream_flow.load(self.base, self.fid)
        now = time.time()
        stream_flow.check_limits(ctx, now=now, counting_dispatch=True)
        ctx.totals.accepted = {fx.new_uuid()}
        stream_flow.check_limits(ctx, now=now, counting_dispatch=True)
        ctx.totals.pending_or_orphan_texts = [fx.new_uuid()]                  # counts against the limit too
        self.assertEqual(ctx.totals.dispatches, 2)
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.check_limits(ctx, now=now, counting_dispatch=True)
        stream_flow.check_limits(ctx, now=now, counting_dispatch=False)      # stream_send does not count
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False, live_responses=10)
        ctx.started_at = now - 3601
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False)
        ctx.started_at, ctx.totals.spent_usd = now, 4.987
        self.assertEqual(stream_flow.remaining_budget(ctx), 0.01)
        ctx.totals.spent_usd = 5.0
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.remaining_budget(ctx)

    def test_elapsed_limit_fails_on_clock_rollback_and_exact_boundary(self):
        self.accept(limits={**acc.DEFAULT_LIMITS, "max_elapsed_h": 1})
        ctx = stream_flow.load(self.base, self.fid)
        now = time.time()
        ctx.started_at = now + 1
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False)
        self.assertEqual(cm.exception.code, "count_unavailable")

        ctx.started_at = now - 3600
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_limits(ctx, now=now, counting_dispatch=False)
        self.assertEqual(cm.exception.code, "limit")

    def test_elapsed_limit_rejects_nonfinite_clock(self):
        self.accept(limits={**acc.DEFAULT_LIMITS, "max_elapsed_h": 1})
        ctx = stream_flow.load(self.base, self.fid)
        ctx.started_at = time.time()
        for now in (float("nan"), float("inf"), True):
            with self.subTest(now=now), self.assertRaises(stream_flow.FlowRefused):
                stream_flow.check_limits(ctx, now=now, counting_dispatch=False)

    def flow_with_one_session(self, cost=0.25):
        """A started flow with one session whose journal accepted one
        dispatch, its saved text, and one orphan text (3.5)."""
        self.accept()
        root = self.launch(state="ended", claude_session_id=fx.new_uuid(), budget_usd=20.0)
        from tests.test_stream_protocol import Harness
        h = Harness()
        h.records[0] = stream_journal.encode(1, time.time(), "session_started",
                                             {"claude_session_id": h.sid, "pipeline_id": self.fid,
                                              "cli_version": "2.1.292", "argv_sha256": "a" * 64,
                                              "budget_usd": 20.0})
        d = h.run_turn(cost=cost)
        (root / "journal.jsonl").write_bytes(b"".join(h.records))
        (root / "journal.jsonl").chmod(0o600)
        with ps.Pipeline(self.base, self.tid, create=True) as p:
            p.write_text(d, "please do the work".encode())            # the text Harness.dispatch accepted
            p.write_text(fx.new_uuid(), b"orphan")                      # saved, never accepted
            p.record_start(self.fid, time.time(), launch_id=root.name, base_commit=fx.BASE_COMMIT)
        return root, d

    def test_totals_come_from_journals_and_texts(self):
        root, d = self.flow_with_one_session()
        ctx = stream_flow.load(self.base, self.fid)
        # R5 #2: accepted and saved-but-unaccepted texts are listed apart;
        # the limit counts both (more conservative than design 3.5).
        self.assertEqual(ctx.totals.accepted, {d})
        self.assertEqual(len(ctx.totals.pending_or_orphan_texts), 1)
        self.assertNotIn(d, ctx.totals.pending_or_orphan_texts)
        self.assertEqual((ctx.totals.dispatches, ctx.totals.responses), (2, 1))
        self.assertAlmostEqual(ctx.totals.spent_usd, 0.25)
        good = (root / "journal.jsonl").read_bytes()
        (root / "journal.jsonl").write_bytes(good[:-3])                     # damaged: counts unknown
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.load(self.base, self.fid)
        self.assertEqual(cm.exception.code, "count_unavailable")

    def test_nothing_is_read_as_zero_on_an_error(self):
        # Codex S2a-2 p1 R4: every way the flow's own files can go wrong refuses.
        cases = {}

        def flow_dir_deleted():
            shutil.rmtree(self.base / "pipelines" / self.tid)
        cases["flow directory deleted (Codex repro)"] = flow_dir_deleted

        def accepted_text_missing():
            (self.base / "pipelines" / self.tid / "dispatches" / f"{self.d}.txt").unlink()
        cases["accepted text missing"] = accepted_text_missing

        def accepted_text_changed():
            (self.base / "pipelines" / self.tid / "dispatches" / f"{self.d}.txt").write_bytes(b"changed!!")
        cases["accepted text changed"] = accepted_text_changed

        def start_record_missing():
            (self.base / "pipelines" / self.tid / "started.json").unlink()
        cases["start record missing"] = start_record_missing

        def start_record_is_a_directory():
            (self.base / "pipelines" / self.tid / "started.json").unlink()
            (self.base / "pipelines" / self.tid / "started.json").mkdir()
        cases["start record is a directory"] = start_record_is_a_directory

        def start_record_is_a_symlink():
            target = self.base / "start-elsewhere.json"
            (self.base / "pipelines" / self.tid / "started.json").rename(target)
            (self.base / "pipelines" / self.tid / "started.json").symlink_to(target)
        cases["start record is a symlink"] = start_record_is_a_symlink

        def dispatches_dir_missing():
            shutil.rmtree(self.base / "pipelines" / self.tid / "dispatches")
        cases["dispatches directory missing"] = dispatches_dir_missing

        def pipelines_root_is_a_file():
            shutil.rmtree(self.base / "pipelines")
            (self.base / "pipelines").write_text("x")
        cases["pipelines root is a file"] = pipelines_root_is_a_file

        def sessions_root_gone():
            shutil.rmtree(self.base / "sessions")
        cases["sessions gone after the start"] = sessions_root_gone

        for name, damage in cases.items():
            with self.subTest(case=name):
                for p in ("pipelines", "sessions"):
                    target = self.base / p
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.exists():
                        shutil.rmtree(target)
                with flows.store.locked():
                    data = flows.store.load()
                    data[self.fid]["events"] = []
                    flows.store.save(data)
                _, self.d = self.flow_with_one_session()
                stream_flow.load(self.base, self.fid)                    # sound before the damage
                damage()
                with self.assertRaises(stream_flow.FlowRefused) as cm:
                    stream_flow.load(self.base, self.fid)
                self.assertEqual(cm.exception.code, "count_unavailable")

    # ---- v29.7: what the next session's accounting counts for an unfinished dispatch

    def session_ending(self, end):
        """A second session of the flow: one dispatch written and confirmed,
        then ``end``; its text is saved like dispatch_prepare does."""
        from tests.test_stream_protocol import Harness, CWD
        root = self.launch(state="ended", claude_session_id=fx.new_uuid(), budget_usd=7.5)
        h = Harness()
        h.records.clear()
        h.seq, h.js = 0, stream_journal.JournalState()
        h.record("session_started", {"claude_session_id": h.sid, "pipeline_id": self.fid, "cli_version": "2.1.292",
                                     "argv_sha256": "a" * 64, "budget_usd": 7.5})
        d, text = h.dispatch()
        h.feed(fx.turn(h.sid, d, text, cwd=CWD, prefix="u")[:5])
        end(h, d)
        (root / "journal.jsonl").write_bytes(b"".join(h.records))
        (root / "journal.jsonl").chmod(0o600)
        with ps.Pipeline(self.base, self.tid, create=False) as p:
            p.write_text(d, text.encode())
        return d

    def test_the_next_session_counts_the_worst_case(self):
        endings = {
            "no_progress": lambda h, d: h.record("dispatch_failed", {"dispatch_id": d, "reason": "no_progress"}),
            "turn_timeout": lambda h, d: h.record("dispatch_failed", {"dispatch_id": d, "reason": "turn_timeout"}),
            "response_cap": lambda h, d: h.record("dispatch_failed", {"dispatch_id": d, "reason": "response_cap"}),
            "process_exited": lambda h, d: (h.record("dispatch_failed", {"dispatch_id": d, "reason": "process_exited"}),
                                            h.record("exited", {"returncode": 1, "signal": None, "stderr_tail": ""})),
            "protocol_error": lambda h, d: h.record("protocol_error", {"reason": "bad_json", "detail": ""}),
            "daemon died, recovered": lambda h, d: h.record("recovered", {"process": "gone"}),
            "daemon died, not yet recovered": lambda h, d: None,
        }
        from tests.test_stream_protocol import TURN_CAP
        for name, end in endings.items():
            with self.subTest(ending=name):
                for p in ("pipelines", "sessions"):
                    shutil.rmtree(self.base / p, ignore_errors=True)
                with flows.store.locked():
                    data = flows.store.load()
                    data[self.fid]["events"] = []
                    flows.store.save(data)
                self.flow_with_one_session(cost=0.25)                    # 1 response, USD 0.25
                d = self.session_ending(end)
                ctx = stream_flow.load(self.base, self.fid)
                self.assertEqual(ctx.totals.responses, 1 + TURN_CAP)
                self.assertAlmostEqual(ctx.totals.spent_usd, 0.25 + 7.5)  # the second session's whole budget
                self.assertEqual([x["unfinished"] for x in ctx.totals.sessions if x["unfinished"]], [[d]])

    def test_start_record_recovery(self):
        # v29.7 / review B3: a start record whose launch never ran is removed
        # exactly; anything else is kept.
        def start_for(launch_id):
            with ps.Pipeline(self.base, self.tid, create=True) as p:
                p.record_start(self.fid, time.time(), launch_id=launch_id, base_commit=fx.BASE_COMMIT)

        def has_start():
            return (self.base / "pipelines" / self.tid / "started.json").exists()
        prepared = self.launch()                                              # never opened
        start_for(prepared.name)
        out = stream_flow.recover_start_records(self.base)
        self.assertEqual(out, [{"task": self.tid, "pipeline_id": self.fid, "removed": prepared.name}])
        self.assertFalse(has_start())
        start_for("l-00000000000000ee")                                        # a launch that is gone
        stream_flow.recover_start_records(self.base)
        self.assertFalse(has_start())
        kept = {
            "launching": lambda: a.update_manifest(self.base, prepared.name, state="launching"),
            "has a journal": lambda: (prepared / "journal.jsonl").write_bytes(b""),
            "another launch of the flow has a journal": lambda: (
                self.launch(state="ended") / "journal.jsonl").write_bytes(b""),
            "an unknown entry in sessions/": lambda: (self.base / "sessions" / "notes").write_text("x"),
        }
        for name, make in kept.items():
            with self.subTest(case=name):
                shutil.rmtree(self.base / "sessions")
                prepared = self.launch()
                start_for(prepared.name)
                make()
                out = stream_flow.recover_start_records(self.base)
                self.assertTrue(has_start())
                (self.base / "pipelines" / self.tid / "started.json").unlink()

    # ---- review jobs in the flow's accounting (design 5.3, v29.8.1, v29.9)

    def review(self, n: int, state="finished", link=True, **over):
        """A review job of this flow with a manifest whose fields agree, and
        (link) the flow's own record of it."""
        from vbear.runtime import review_store as rs
        from tests.test_review_store import state_manifest
        job = f"r-{n:016x}"
        rs.create_job_dir(self.base, job)
        fields = {"job_id": job, "pipeline_id": self.fid, "task_id": self.tid, "round": n, **over}
        m = state_manifest(state, **fields)
        rs.write_new_manifest(self.base, m)
        if link:
            with ps.Pipeline(self.base, self.tid, create=True) as p:
                p.write_review_link(n, job, self.fid, m["commit"])
        return job

    def test_reviews_are_counted_and_limited(self):
        self.accept(limits={**acc.DEFAULT_LIMITS, "max_reviews": 2})
        self.review(1, state="finished")
        self.review(2, state="cleaned")
        self.review(3, state="finished", pipeline_id="flow-ffffffffffff", link=False)   # another flow's: not ours
        ctx = stream_flow.load(self.base, self.fid)
        self.assertEqual([x["round"] for x in ctx.totals.reviews], [1, 2])
        stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False)               # not counting a review
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False, counting_review=True)
        self.assertIn("審查次數", str(cm.exception))

    def test_a_failed_review_holds_the_flow_until_it_is_released_by_identity(self):
        self.accept()
        job = self.review(1, state="invalid", invalid_reasons=["rollout 不符"])
        ctx = stream_flow.load(self.base, self.fid)
        self.assertIn(job, stream_flow.unresolved_failure(ctx))
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False)
        self.assertEqual(cm.exception.code, "failed")
        self.assertEqual(stream_flow.failure_ids(self.base, self.fid, self.tid), [f"{job}#invalid"])
        with ps.Pipeline(self.base, self.tid, create=True) as p:
            p.record_release(self.fid, time.time(), [f"{job}#invalid"])
        ctx = stream_flow.load(self.base, self.fid)
        self.assertIsNone(stream_flow.unresolved_failure(ctx))
        later = self.review(2, state="manual_review", retained_reason="group alive", retained_at=1791467063.473483)
        ctx = stream_flow.load(self.base, self.fid)                       # a new failure is not resolved
        self.assertIn(later, stream_flow.unresolved_failure(ctx))
        self.assertEqual(stream_flow.failure_ids(self.base, self.fid, self.tid),
                         [f"{job}#invalid", f"{later}#manual_review#1791467063.473483"])
        with ps.Pipeline(self.base, self.tid, create=True) as p:
            p.record_release(self.fid, time.time(), stream_flow.failure_ids(self.base, self.fid, self.tid))
        self.assertIsNone(stream_flow.unresolved_failure(stream_flow.load(self.base, self.fid)))

    def test_a_failure_survives_the_clean_up(self):
        # S2b part 1 review P1: cleaned must not make the failure vanish
        from vbear.runtime import review_store as rs
        self.accept()
        job = self.review(1, state="invalid", invalid_reasons=["rollout 不符"])
        self.assertIsNotNone(stream_flow.unresolved_failure(stream_flow.load(self.base, self.fid)))
        rs.update_manifest(self.base, job, state="cleaned")
        ctx = stream_flow.load(self.base, self.fid)
        self.assertIn(job, stream_flow.unresolved_failure(ctx))             # still held
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=False)
        self.assertEqual(cm.exception.code, "failed")
        self.assertEqual(stream_flow.failure_ids(self.base, self.fid, self.tid), [f"{job}#invalid"])
        with ps.Pipeline(self.base, self.tid, create=True) as p:
            p.record_release(self.fid, time.time(), [f"{job}#invalid"])     # only the user's "continue" lets it go
        self.assertIsNone(stream_flow.unresolved_failure(stream_flow.load(self.base, self.fid)))
        # the same for a review kept for a person and cleaned up later
        other = self.review(2, state="cleaned", outcome="manual_review", retained_at=1791467063.473483,
                            retained_reason="x")
        self.assertIn(other, stream_flow.unresolved_failure(stream_flow.load(self.base, self.fid)))

    def test_a_review_that_cannot_be_read_refuses_the_count(self):
        from vbear.runtime import review_store as rs
        self.accept()
        job = self.review(1, state="finished")
        stream_flow.load(self.base, self.fid)
        cases = {
            "an entry that is not a job": lambda: (rs.reviews_root(self.base) / "notes").mkdir(),
            "a manifest that is not json": lambda: (rs.job_dir(self.base, job) / rs.MANIFEST).write_text("{"),
            "a manifest with an extra field": lambda: (rs.job_dir(self.base, job) / rs.MANIFEST).write_text(
                json.dumps({**rs.read_manifest(self.base, job), "x": 1})),
            "a job directory renamed": lambda: rs.job_dir(self.base, job).rename(rs.reviews_root(self.base) / "r-ffffffffffffffff"),
            "a missing manifest": lambda: (rs.job_dir(self.base, job) / rs.MANIFEST).unlink(),
        }
        for name, damage in cases.items():
            with self.subTest(case=name):
                shutil.rmtree(rs.reviews_root(self.base))
                shutil.rmtree(self.base / "pipelines" / self.tid / "reviews", ignore_errors=True)
                job = self.review(1, state="finished")
                damage()
                with self.assertRaises(stream_flow.FlowRefused) as cm:
                    stream_flow.load(self.base, self.fid)
                self.assertEqual(cm.exception.code, "count_unavailable")
                with self.assertRaises(stream_flow.FlowRefused):
                    stream_flow.failure_ids(self.base, self.fid, self.tid)

    def test_the_two_sides_of_a_review_must_agree(self):
        # S2b part 1 review P2: neither a replaced reviews/ nor a deleted job
        # can make the flow's reviews and failures count as zero
        from vbear.runtime import review_store as rs
        self.accept()
        links = self.base / "pipelines" / self.tid / "reviews"

        def reset():
            shutil.rmtree(rs.reviews_root(self.base), ignore_errors=True)
            shutil.rmtree(links, ignore_errors=True)
            if rs.reviews_root(self.base).is_symlink():
                rs.reviews_root(self.base).unlink()
        cases = {}

        def a_job_without_its_record():
            self.review(1, state="invalid", link=False)
        cases["a job without the flow's record"] = a_job_without_its_record

        def a_record_without_its_job():
            job = self.review(1, state="invalid")
            shutil.rmtree(rs.job_dir(self.base, job))
        cases["a record whose job directory was deleted"] = a_record_without_its_job

        def a_replaced_root():
            self.review(1, state="invalid")
            empty = self.base / "empty-root"
            empty.mkdir(mode=0o700)
            shutil.rmtree(rs.reviews_root(self.base))
            rs.reviews_root(self.base).symlink_to(empty)
        cases["reviews/ replaced by a link to an empty directory"] = a_replaced_root

        def a_vanished_root():
            self.review(1, state="invalid")
            shutil.rmtree(rs.reviews_root(self.base))
        cases["reviews/ gone"] = a_vanished_root

        def another_commit():
            job = self.review(1, state="invalid")
            (links / "1" / "job.json").write_text(json.dumps(
                {"v": 1, "job_id": job, "pipeline_id": self.fid, "round": 1, "commit": "b" * 40}))
        cases["a record naming another commit"] = another_commit

        def another_job():
            self.review(1, state="invalid")
            (links / "1" / "job.json").write_text(json.dumps(
                {"v": 1, "job_id": "r-ffffffffffffffff", "pipeline_id": self.fid, "round": 1, "commit": "a" * 40}))
        cases["a record naming another job"] = another_job

        def another_flow():
            job = self.review(1, state="invalid")
            (links / "1" / "job.json").write_text(json.dumps(
                {"v": 1, "job_id": job, "pipeline_id": "flow-ffffffffffff", "round": 1, "commit": "a" * 40}))
        cases["a record naming another flow"] = another_flow

        def a_bad_record():
            self.review(1, state="invalid")
            (links / "1" / "job.json").write_text("{")
        cases["an unreadable record"] = a_bad_record

        def a_wrong_round_in_the_record():
            job = self.review(1, state="invalid")
            (links / "1" / "job.json").write_text(json.dumps(
                {"v": 1, "job_id": job, "pipeline_id": self.fid, "round": 2, "commit": "a" * 40}))
        cases["a record of another round"] = a_wrong_round_in_the_record

        def junk_in_the_records():
            self.review(1, state="invalid")
            (links / "notes").mkdir()
        cases["an unknown entry among the records"] = junk_in_the_records

        def a_round_without_a_record():
            self.review(1, state="invalid")
            (links / "2").mkdir(mode=0o700)
        cases["a round directory without job.json"] = a_round_without_a_record

        def two_jobs_one_round():
            self.review(1, state="invalid")
            from tests.test_review_store import state_manifest
            rs.create_job_dir(self.base, "r-00000000000000aa")
            rs.write_new_manifest(self.base, state_manifest("invalid", job_id="r-00000000000000aa",
                                                            pipeline_id=self.fid, task_id=self.tid, round=1))
        cases["two jobs in one round"] = two_jobs_one_round
        for name, make in cases.items():
            with self.subTest(case=name):
                reset()
                make()
                with self.assertRaises(stream_flow.FlowRefused) as cm:
                    stream_flow.load(self.base, self.fid)
                self.assertEqual(cm.exception.code, "count_unavailable")
                with self.assertRaises(stream_flow.FlowRefused):
                    stream_flow.failure_ids(self.base, self.fid, self.tid)
        reset()
        self.review(1, state="invalid")                                   # and the intact pair is believed
        self.assertEqual(len(stream_flow.load(self.base, self.fid).totals.reviews), 1)

    def test_spend_that_is_not_finite_refuses(self):
        self.accept()
        ctx = stream_flow.load(self.base, self.fid)
        for spent in (float("inf"), float("nan"), 1e308 * 10):
            ctx.totals.spent_usd = spent
            with self.subTest(spent=spent), self.assertRaises(stream_flow.FlowRefused):
                stream_flow.remaining_budget(ctx)                         # never OverflowError
            with self.subTest(spent=spent, path="check_limits"), self.assertRaises(stream_flow.FlowRefused):
                stream_flow.check_limits(ctx, now=time.time(), counting_dispatch=True)
        # many finite costs summed past the float range
        root, d = self.flow_with_one_session()
        real_read = stream_flow._journal_state

        def huge(base, launch_id):
            res = real_read(base, launch_id)
            res.state.cost = 1.7e308
            if launch_id != root.name:    # the copy: the same dispatch twice would refuse first
                res.state.order, res.state.turns = [], {}
            return res
        second = self.launch(state="ended", claude_session_id=fx.new_uuid(), budget_usd=20.0)
        (second / "journal.jsonl").write_bytes((root / "journal.jsonl").read_bytes())
        (second / "journal.jsonl").chmod(0o600)
        with mock.patch.object(stream_flow, "_journal_state", huge):
            with self.assertRaises(stream_flow.FlowRefused) as cm:
                stream_flow.load(self.base, self.fid)
        self.assertIn("有限", str(cm.exception))

    # ---- R5 #1: nothing under sessions/ is skipped unless it provably is not this flow's

    def edit_manifest(self, ldir: Path, change):
        m = json.loads((ldir / "manifest.json").read_text())
        change(m)
        (ldir / "manifest.json").write_text(json.dumps(m))
        (ldir / "manifest.json").chmod(0o600)

    def terminal_launch(self, engine: str) -> Path:
        """A real claude or codex terminal launch, as prepare_* writes it."""
        work = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbss-tl-")))
        self.addCleanup(shutil.rmtree, work, True)
        binary = work / engine
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o700)
        prepare = a.prepare_claude_launch if engine == "claude" else a.prepare_codex_launch
        m = prepare(self.base, str(work), cli_binary=str(binary), cli_version="2.1.292",
                    cli_identity=a.binary_identity(str(binary)), allowed_root=str(work.parent))
        self.addCleanup(shutil.rmtree, m["scratch"]["path"], True)
        return Path(m["launch_dir"]["path"])

    def assert_refused(self, why: str):
        with self.assertRaises(stream_flow.FlowRefused) as cm:
            stream_flow.load(self.base, self.fid)
        self.assertEqual(cm.exception.code, "count_unavailable")
        self.assertIn(why, str(cm.exception))

    def test_terminal_and_other_flow_launches_are_skipped(self):
        root, d = self.flow_with_one_session()
        claude, codex = self.terminal_launch("claude"), self.terminal_launch("codex")
        a.update_manifest(self.base, claude.name, state="running", native_session_id="n-0123456789ab",
                          unverified_acknowledged=True, unverified_acknowledged_at=time.time(),
                          leader={"pid": 4242, "start": f"{int(time.time())}.000000", "source": "libproc"},
                          observed=[[4243, f"{int(time.time())}.000000"]])
        a._retain(self.base, codex.name, "test")
        other = self.launch(state="ended", claude_session_id=fx.new_uuid(), budget_usd=1.0)
        self.edit_manifest(other, lambda m: m.update(pipeline_id="flow-ffffffffffff"))   # another flow
        (other / "journal.jsonl").write_bytes(b"not this flow's")
        ctx = stream_flow.load(self.base, self.fid)
        self.assertEqual([x["launch_id"] for x in ctx.totals.sessions], [root.name])
        self.assertEqual(ctx.totals.accepted, {d})

    def test_an_entry_that_is_not_a_launch_refuses(self):
        self.flow_with_one_session()
        for name, make in ((".DS_Store", "file"), ("notes", "dir"), ("l-xyz", "dir"), ("l-0123", "file")):
            with self.subTest(name=name):
                target = self.base / "sessions" / name
                target.mkdir() if make == "dir" else target.write_text("x")
                self.assert_refused("不認得的項目")
                shutil.rmtree(target) if make == "dir" else target.unlink()
        stream_flow.load(self.base, self.fid)

    def test_a_renamed_or_copied_launch_refuses(self):
        # Codex R5 repro: renaming the flow's launch folder hid its usage.
        root, _ = self.flow_with_one_session()
        sessions = self.base / "sessions"
        root.rename(sessions / "l-renamed")                                  # not a launch name
        self.assert_refused("不認得的項目")
        (sessions / "l-renamed").rename(sessions / "l-00000000000000aa")      # a launch name, not its own
        self.assert_refused("與 manifest 不符")
        (sessions / "l-00000000000000aa").rename(root)
        stream_flow.load(self.base, self.fid)
        shutil.copytree(root, sessions / "l-00000000000000bb")               # a copy: same manifest
        self.assert_refused("與 manifest 不符")

    def test_an_unreadable_or_unknown_manifest_refuses(self):
        root, _ = self.flow_with_one_session()
        good = (root / "manifest.json").read_bytes()
        cases = {
            "missing": lambda: (root / "manifest.json").unlink(),
            "not json": lambda: (root / "manifest.json").write_text("{"),
            "unknown engine": lambda: self.edit_manifest(root, lambda m: m.update(engine="gemini")),
            "no engine": lambda: self.edit_manifest(root, lambda m: m.pop("engine")),
        }
        for name, damage in cases.items():
            with self.subTest(case=name):
                damage()
                with self.assertRaises(stream_flow.FlowRefused) as cm:
                    stream_flow.load(self.base, self.fid)
                self.assertEqual(cm.exception.code, "count_unavailable")
                (root / "manifest.json").write_bytes(good)
                (root / "manifest.json").chmod(0o600)

    def test_a_stream_launch_relabelled_as_terminal_refuses(self):
        # Codex R5 repro: changing a stream manifest's engine hid its usage.
        root, _ = self.flow_with_one_session()
        self.edit_manifest(root, lambda m: m.update(engine="claude"))
        self.assert_refused("欄位不符")                                       # still has the stream fields

        def as_terminal(m):                                                  # a clean claude manifest, but
            for k in ("pipeline_id", "task_id", "claude_session_id", "budget_usd", "ended_at"):
                m.pop(k, None)
            m.update(engine="claude", state="manual_review")
        self.edit_manifest(root, as_terminal)
        self.assertIsNone(a.managed_manifest_problem(json.loads((root / "manifest.json").read_text())))
        self.assert_refused("帶有流程欄位或串流日誌")                          # ... its journal is still there

    def test_a_terminal_manifest_must_be_exact(self):
        self.flow_with_one_session()
        cases = {
            "names a flow": (lambda m: m.update(pipeline_id=self.fid), "欄位不符"),
            "extra field": (lambda m: m.update(note="x"), "欄位不符"),
            "missing field": (lambda m: m.pop("observed"), "欄位不符"),
            "bad state": (lambda m: m.update(state="ended"), "state 不合法"),
            "bad leader": (lambda m: m.update(leader={"pid": 1, "start": "", "source": "ps"}), "leader 不合法"),
            "bad version": (lambda m: m.update(cli_version="2.1.292\n"), "cli_version 不合法"),
            "bool verified as string": (lambda m: m.update(cli_verified="true"), "cli_verified 不合法"),
        }
        for engine in ("claude", "codex"):
            for name, (change, why) in cases.items():
                if engine == "codex" and name == "bool verified as string":
                    continue
                with self.subTest(engine=engine, case=name):
                    ldir = self.terminal_launch(engine)
                    stream_flow.load(self.base, self.fid)
                    self.edit_manifest(ldir, change)
                    self.assert_refused(why)
                    shutil.rmtree(ldir)
        ldir = self.terminal_launch("codex")
        self.edit_manifest(ldir, lambda m: m.update(cli_verified=True))       # a claude-only field
        self.assert_refused("欄位不符")
        shutil.rmtree(ldir)
        ldir = self.terminal_launch("claude")
        (ldir / "journal.jsonl").write_bytes(b"")                              # a journal beside it
        self.assert_refused("帶有流程欄位或串流日誌")

    def test_cleanup_never_reads_an_error_or_a_dangling_link_as_absent(self):
        # R5 audit (agent_sessions.cleanup_launch, a deleting path).
        ldir = self.launch(state="running")
        (ldir / "journal.jsonl").symlink_to(self.base / "nowhere")            # Path.exists() says False
        out = a.cleanup_launch(self.base, ldir.name, proven_dead=True)
        self.assertEqual(out.get("kept"), "journal")
        self.assertTrue(ldir.is_dir())                                       # not deleted with its record
        ldir = self.launch(state="running")
        scratch = json.loads((ldir / "manifest.json").read_text())["scratch"]["path"]
        real = os.lstat

        def lstat(path, *args, **kw):
            if str(path) == scratch:
                raise PermissionError(13, "Permission denied")
            return real(path, *args, **kw)
        with mock.patch("vbear.runtime.agent_sessions.os.lstat", lstat):
            out = a.cleanup_launch(self.base, ldir.name, proven_dead=True)
        self.assertFalse(out["cleaned"])                                      # not "cleaned" with the scratch left
        self.assertTrue(os.path.isdir(scratch))
        self.assertEqual(json.loads((ldir / "manifest.json").read_text())["state"], "manual_review")

    def test_one_dispatch_in_two_journals_refuses(self):
        root, _ = self.flow_with_one_session()
        second = self.launch(state="ended", claude_session_id=fx.new_uuid(), budget_usd=20.0)
        (second / "journal.jsonl").write_bytes((root / "journal.jsonl").read_bytes())
        (second / "journal.jsonl").chmod(0o600)
        self.assert_refused("被兩個 session 接受過")

    def test_a_journal_that_cannot_be_checked_refuses(self):
        # R4 audit: Path.exists() (Python 3.14) reads EACCES as "absent", which
        # for a never-started launch would skip it silently.
        self.accept()
        root = self.launch(state="prepared")
        (root / "journal.jsonl").write_bytes(b"")
        real = os.lstat

        def lstat(path, *args, **kw):
            if str(path).endswith("/journal.jsonl"):
                raise PermissionError(13, "Permission denied")
            return real(path, *args, **kw)
        with mock.patch("vbear.runtime.stream_flow.os.lstat", lstat):
            with self.assertRaises(stream_flow.FlowRefused) as cm:
                stream_flow.flow_sessions(self.base, self.fid, started=False)
        self.assertEqual(cm.exception.code, "count_unavailable")
        self.assertIn("無法檢查", str(cm.exception))

    def test_a_started_launch_without_journal_refuses(self):
        # Codex S2a-2 p1 #3: never skipped, whatever its state.
        self.accept()
        launch = self.launch()
        leader = {"pid": 4242, "start": f"{int(time.time())}.000000", "source": "libproc"}
        for state, extra, refused in (("prepared", {}, False),
                                      ("prepared", {"native_session_id": "n-0123456789ab"}, True),
                                      ("prepared", {"leader": leader}, True),
                                      ("launching", {}, True), ("running", {}, True), ("ended", {}, True),
                                      ("manual_review", {}, True)):
            with self.subTest(state=state, extra=extra):
                a.update_manifest(self.base, launch.name, **{"state": state, "native_session_id": None,
                                                             "leader": None, **extra})
                if refused:
                    with self.assertRaises(stream_flow.FlowRefused) as cm:
                        stream_flow.flow_sessions(self.base, self.fid, started=False)
                    self.assertEqual(cm.exception.code, "count_unavailable")
                else:
                    self.assertEqual(stream_flow.flow_sessions(self.base, self.fid, started=False), [])


class StreamVerificationRecordTests(StateDir):
    """A version counts as stream-verified only when built in or backed by a
    passing stream report (design 2.2: no "unverified but start")."""

    def record(self, report: dict | None, **over):
        path = self.base / "report.json"
        if report is not None:
            path.write_text(json.dumps(report))
            path.chmod(0o600)
        rec = {"passed": True, "report": str(path), "verified_at": "now", **over}
        (self.base / cli_versions.LOCAL_STREAM_VERIFIED_FILE).write_text(json.dumps({"versions": {"9.9.9": rec}}))
        (self.base / cli_versions.LOCAL_STREAM_VERIFIED_FILE).chmod(0o600)

    def test_record_must_be_backed_by_a_passing_stream_report(self):
        good = {"mode": "stream", "passed": True, "claude_version": "9.9.9"}
        self.record(good)
        self.assertIn("9.9.9", cli_versions.stream_verified_versions())
        for report, over in ((None, {}), ({**good, "mode": "headless"}, {}), ({**good, "passed": False}, {}),
                             ({**good, "claude_version": "9.9.8"}, {}), (good, {"passed": False}),
                             (good, {"passed": "true"})):
            with self.subTest(report=report, over=over):
                if (self.base / "report.json").exists():
                    (self.base / "report.json").unlink()
                self.record(report, **over)
                self.assertNotIn("9.9.9", cli_versions.stream_verified_versions())
        self.assertEqual(cli_versions.STREAM_VERIFIED_VERSIONS, ("2.1.292",))


class StreamLaunchTests(StateDir):
    def setUp(self):
        super().setUp()
        self.work = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbss-work-")))    # never in the real home
        self.addCleanup(shutil.rmtree, self.work, True)
        self.binary = self.base / "claude"
        self.binary.write_text("#!/bin/sh\n")
        self.binary.chmod(0o700)
        self.scratches = []
        self.addCleanup(lambda: [shutil.rmtree(p, True) for p in self.scratches])

    def prepare(self, **kw):
        args = dict(cli_binary=str(self.binary), cli_version="2.1.292", cli_identity=a.binary_identity(str(self.binary)),
                    model_id=fx.MODEL, pipeline_id="flow-0123456789ab", task_id="task-1",
                    allowed_root=str(self.work.parent))
        args.update(kw)
        m = a.prepare_stream_launch(self.base, str(self.work), **args)
        self.scratches.append(m["scratch"]["path"])
        return m

    def test_settings_pin_the_endpoint_and_argv_is_exact(self):
        m = self.prepare()
        settings = json.loads(Path(m["settings_path"]).read_text())
        self.assertEqual(settings["env"], sp.VERSIONS["2.1.292"].pinned_env)
        self.assertEqual(settings["sandbox"], a.claude_settings(str(self.work), m["scratch"]["path"], os.getuid())["sandbox"])
        v = a.load_validated(self.base, m["launch_id"])
        self.assertEqual(v["engine"], "claude-stream")
        with self.assertRaises(a.LaunchRefused):
            a.managed_argv(v)                                   # no session id or budget yet
        sid = fx.new_uuid()
        a.update_manifest(self.base, m["launch_id"], claude_session_id=sid, budget_usd=19.97)
        argv = a.managed_argv(a.load_validated(self.base, m["launch_id"]))
        self.assertEqual(argv[:10], [str(self.binary), "-p", "--input-format", "stream-json", "--output-format",
                                     "stream-json", "--verbose", "--replay-user-messages", "--permission-prompts",
                                     "none"])
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "19.97")
        self.assertEqual(argv[argv.index("--session-id") + 1], sid)
        self.assertEqual(argv[argv.index("--model") + 1], fx.MODEL)
        for flag in ("--safe-mode", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Bash")
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "Edit,Write")
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1])["additionalProperties"], False)

    def test_bad_inputs(self):
        for kw in ({"model_id": "haiku"}, {"model_id": None}, {"pipeline_id": "flow-x"}, {"task_id": ".."},
                   {"task_id": "a/b"}, {"cli_version": "2.1.291"}, {"pipeline_id": "flow-0123456789ab\n"}):
            with self.subTest(kw=kw), self.assertRaises(a.LaunchRefused):
                self.prepare(**kw)

    def test_manifest_drift_is_refused(self):
        m = self.prepare()
        path = Path(m["launch_dir"]["path"]) / "manifest.json"
        good = json.loads(path.read_text())
        for change in ({"pipeline_id": "flow-x"}, {"task_id": ".."}, {"model_id": "haiku"},
                       {"claude_session_id": "x"}, {"budget_usd": NAN}, {"budget_usd": 0}, {"budget_usd": 101},
                       {"budget_usd": True}, {"budget_usd": 1.005}, {"cli_version": "2.1.291"}):
            with self.subTest(change=change):
                text = json.dumps({**good, **change}) if not (isinstance(change.get("budget_usd"), float)
                                                              and change["budget_usd"] != change["budget_usd"]) \
                    else json.dumps({**good, **change}, allow_nan=True)
                path.write_text(text)
                with self.assertRaises(a.LaunchRefused):
                    a.managed_argv(a.load_validated(self.base, m["launch_id"]))
        path.write_text(json.dumps(good))
        settings = Path(m["settings_path"])
        s = json.loads(settings.read_text())
        s["env"]["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
        settings.write_text(json.dumps(s))
        with self.assertRaises(a.LaunchRefused):
            a.load_validated(self.base, m["launch_id"])

    def test_manifests_are_read_strictly(self):
        # Codex S2a-2 p1 #4: every engine's manifest goes through strictjson.
        for engine_prepare in ("stream", "claude"):
            with self.subTest(engine=engine_prepare):
                if engine_prepare == "stream":
                    m = self.prepare()
                else:
                    m = a.prepare_claude_launch(self.base, str(self.work), cli_binary=str(self.binary),
                                                cli_version="2.1.292",
                                                cli_identity=a.binary_identity(str(self.binary)),
                                                allowed_root=str(self.work.parent))
                    self.scratches.append(m["scratch"]["path"])
                path = Path(m["launch_dir"]["path"]) / "manifest.json"
                good = path.read_text()
                bad = {
                    "duplicate key": good.replace('"state": "prepared"', '"state": "prepared", "state": "running"'),
                    "NaN": good.replace('"created": ', '"created": NaN, "x_": ', 1),
                    "over 64 KiB": good[:-2] + ', "pad": "' + "x" * (64 << 10) + '"}\n',
                    "not an object": "[]",
                }
                for name, text in bad.items():
                    with self.subTest(case=name):
                        path.write_text(text)
                        with self.assertRaises(a.LaunchRefused):
                            a.load_validated(self.base, m["launch_id"])
                path.unlink()
                elsewhere = self.base / "elsewhere.json"
                elsewhere.write_text(good)
                path.symlink_to(elsewhere)
                with self.assertRaises(a.LaunchRefused):
                    a.load_validated(self.base, m["launch_id"])
                path.unlink()
                path.write_text(good)
                path.chmod(0o600)
                a.load_validated(self.base, m["launch_id"])

    def test_stream_manifest_schema(self):
        m = self.prepare()
        path = Path(m["launch_dir"]["path"]) / "manifest.json"
        good = json.loads(path.read_text())
        now = time.time()
        cases = [
            {"extra": 1}, {"state": "running2"}, {"cli_verified": False}, {"cli_identity": [1, 2]},
            {"native_session_id": "n-x"}, {"settings_sha256": "x"}, {"created": 1.0}, {"created": True},
            {"leader": {"pid": 0, "start": f"{int(now)}.000000", "source": "libproc"}},
            {"leader": {"pid": 100000, "start": f"{int(now)}.000000", "source": "libproc"}},
            {"leader": {"pid": True, "start": f"{int(now)}.000000", "source": "libproc"}},
            {"leader": {"pid": 5, "start": "1.000000", "source": "libproc"}},                   # before 2020
            {"leader": {"pid": 5, "start": f"{int(now) + 10 * 86400}.000000", "source": "libproc"}},
            {"leader": {"pid": 5, "start": "", "source": "libproc"}},
            {"leader": {"pid": 5, "start": f"{int(now)}.000000", "source": "other"}},
            {"observed": [[5, "x"]]}, {"observed": [[5, f"{int(now)}.000000"]] * 4097},
            {"observed": [[0, f"{int(now)}.000000"]]},
            {"observed": [[5, ""]]},                                              # no start time: unidentifiable
            {"observed": [[5, "1.000000"]]}, {"observed": [[5, f"{int(now) + 10 * 86400}.000000"]]},
            {"observed": [[5, "Wed Oct  8 12:00:00 2019"]]}, {"observed": [[5, None]]},
            {"retained_at": float("inf")}, {"retained_reason": 5},
        ]
        for change in cases:
            with self.subTest(change=repr(change)[:60]):
                bad = {**good, **change}
                path.write_text(json.dumps(bad, allow_nan=True))
                with self.assertRaises(a.LaunchRefused):
                    a._read_manifest(Path(m["launch_dir"]["path"]), os.getuid())
        ok = {**good, "state": "running", "native_session_id": "n-0123456789ab",
              "leader": {"pid": 5, "start": f"{int(now)}.000000", "source": "libproc"},
              "observed": [[6, f"{int(now)}.000000"], [7, "Wed Oct  8 12:00:00 2026"]], "retained_reason": "x",
              "ended_at": now}
        path.write_text(json.dumps(ok))
        self.assertEqual(a._read_manifest(Path(m["launch_dir"]["path"]), os.getuid())["state"], "running")

    def test_cleanup_keeps_the_journal(self):
        m = self.prepare()
        ldir = Path(m["launch_dir"]["path"])
        (ldir / "journal.jsonl").write_text("")
        out = a.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertEqual(out.get("kept"), "journal")
        self.assertTrue((ldir / "journal.jsonl").exists())
        self.assertFalse(Path(m["scratch"]["path"]).exists())
        self.assertEqual(json.loads((ldir / "manifest.json").read_text())["state"], "ended")
        m2 = self.prepare()                                    # never started: nothing to keep
        a.cleanup_launch(self.base, m2["launch_id"], proven_dead=True)
        self.assertFalse(Path(m2["launch_dir"]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
