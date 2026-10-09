"""Review jobs on disk (design 5.3): ids, the exact manifest, atomic updates,
failure identities, process checks. No Codex, no model."""

import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear.runtime import pipeline_store, proctrack, review_store as rs

JOB = "r-0123456789abcdef"


def manifest(**over):
    m = {"review_manifest_version": 1, "job_id": JOB, "pipeline_id": "flow-0123456789ab", "task_id": "task-1",
         "round": 1, "commit": "a" * 40, "model": "gpt-6-luna", "codex_version": "0.160.0",
         "argv_sha256": "c" * 64, "scratch": {"path": "/private/tmp/sr-abcd1234", "inode": 7, "dev": 9},
         "run_home": {"inode": 8, "dev": 9}, "leader": None, "observed": [], "thread_id": None,
         "exit_code": None, "state": "prepared", "created": time.time()}
    m.update(over)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbrs-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.base, True)
        os.chmod(self.base, 0o700)


class ManifestSchemaTests(unittest.TestCase):
    def test_a_good_manifest_has_no_problem(self):
        self.assertIsNone(rs.manifest_problem(manifest(), JOB))
        self.assertIsNone(rs.manifest_problem(manifest(
            state="manual_review", retained_reason="r", retained_at=time.time(), ended_at=time.time(),
            invalid_reasons=["a"], thread_id="01a11921-aaaa-bbbb", exit_code=0,
            leader={"pid": 4242, "start": f"{int(time.time())}.000000", "source": "libproc"},
            observed=[[4243, f"{int(time.time())}.000000"]])))

    def test_every_field_is_exact(self):
        bad = {
            "version": {"review_manifest_version": 2}, "version bool": {"review_manifest_version": True},
            "job id": {"job_id": "r-xyz"}, "job id newline": {"job_id": JOB + "\n"},
            "other job id": {"job_id": "r-ffffffffffffffff"},
            "pipeline": {"pipeline_id": "flow-x"}, "task": {"task_id": ".."}, "task slash": {"task_id": "a/b"},
            "round 0": {"round": 0}, "round big": {"round": rs.ROUND_MAX + 1}, "round bool": {"round": True},
            "round str": {"round": "1"}, "commit short": {"commit": "a" * 39}, "commit upper": {"commit": "A" * 40},
            "commit newline": {"commit": "a" * 40 + "\n"}, "model": {"model": "../x"}, "model none": {"model": None},
            "version str": {"codex_version": "0.160"}, "argv hash": {"argv_sha256": "c" * 63},
            "scratch not sr-": {"scratch": {"path": "/private/tmp/sc-abcd1234", "inode": 7, "dev": 9}},
            "scratch elsewhere": {"scratch": {"path": "/tmp/sr-abcd1234", "inode": 7, "dev": 9}},
            "scratch nested": {"scratch": {"path": "/private/tmp/x/sr-abcd1234", "inode": 7, "dev": 9}},
            "scratch short": {"scratch": {"path": "/private/tmp/sr-abcd123", "inode": 7, "dev": 9}},
            "scratch extra key": {"scratch": {"path": "/private/tmp/sr-abcd1234", "inode": 7, "dev": 9, "x": 1}},
            "scratch inode neg": {"scratch": {"path": "/private/tmp/sr-abcd1234", "inode": -1, "dev": 9}},
            "run_home missing key": {"run_home": {"inode": 8}},
            "leader empty start": {"leader": {"pid": 4242, "start": "", "source": "ps"}},
            "leader pid 0": {"leader": {"pid": 0, "start": f"{int(time.time())}.000000", "source": "ps"}},
            "leader source": {"leader": {"pid": 4242, "start": f"{int(time.time())}.000000", "source": "x"}},
            "observed junk": {"observed": [[1, ""]]}, "thread short": {"thread_id": "abc"},
            "thread newline": {"thread_id": "01a11921-aaaa-bbbb\n"}, "exit float": {"exit_code": 1.5},
            "exit bool": {"exit_code": False}, "exit huge": {"exit_code": 100000},
            "state": {"state": "done"}, "created old": {"created": 1.0}, "created nan": {"created": float("nan")},
            "created bool": {"created": True}, "retained_reason long": {"retained_reason": "x" * 5000},
            "retained_at bad": {"retained_at": "yesterday"}, "ended_at bad": {"ended_at": -1},
            "reasons not list": {"invalid_reasons": "x"}, "reasons long": {"invalid_reasons": ["x" * 300]},
            "reasons many": {"invalid_reasons": ["x"] * 17}, "extra field": {"note": "x"},
        }
        for name, over in bad.items():
            with self.subTest(case=name):
                self.assertIsNotNone(rs.manifest_problem(manifest(**over), JOB), name)
        m = manifest()
        del m["thread_id"]
        self.assertIsNotNone(rs.manifest_problem(m))
        for not_a_dict in (None, [], "x", 1):
            self.assertIsNotNone(rs.manifest_problem(not_a_dict))


class StoreTests(Base):
    def make(self, **over):
        rs.create_job_dir(self.base, JOB)
        rs.write_new_manifest(self.base, manifest(**over))

    def test_write_read_update_roundtrip(self):
        self.make()
        self.assertEqual(rs.read_manifest(self.base, JOB)["state"], "prepared")
        mode = os.stat(rs.job_dir(self.base, JOB) / rs.MANIFEST).st_mode
        self.assertEqual(stat.S_IMODE(mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(rs.job_dir(self.base, JOB)).st_mode), 0o700)
        m = rs.update_manifest(self.base, JOB, state="running", thread_id="01a11921-aaaa-bbbb")
        self.assertEqual((m["state"], rs.read_manifest(self.base, JOB)["thread_id"]), ("running", "01a11921-aaaa-bbbb"))

    def test_nothing_invalid_is_written(self):
        self.make()
        before = (rs.job_dir(self.base, JOB) / rs.MANIFEST).read_bytes()
        with self.assertRaises(rs.ReviewRefused):
            rs.update_manifest(self.base, JOB, state="nonsense")
        with self.assertRaises(rs.ReviewRefused):
            rs.update_manifest(self.base, JOB, surprise=1)
        self.assertEqual((rs.job_dir(self.base, JOB) / rs.MANIFEST).read_bytes(), before)
        with self.assertRaises(rs.ReviewRefused):
            rs.write_new_manifest(self.base, manifest(round=0))
        with self.assertRaises(FileExistsError):
            rs.create_job_dir(self.base, JOB)

    def test_a_damaged_job_is_refused_not_trusted(self):
        self.make()
        path = rs.job_dir(self.base, JOB) / rs.MANIFEST
        cases = {
            "not json": lambda: path.write_text("{"),
            "extra field": lambda: path.write_text(json.dumps(manifest(note="x"))),
            "another job's": lambda: path.write_text(json.dumps(manifest(job_id="r-ffffffffffffffff"))),
            "duplicate key": lambda: path.write_text(json.dumps(manifest())[:-1] + ', "round": 2}'),
            "NaN": lambda: path.write_text(json.dumps(manifest()).replace('"round": 1', '"round": NaN')),
            "missing": lambda: path.unlink(),
            "a symlink": lambda: (path.unlink(), path.symlink_to(self.base / "elsewhere")),
            "a directory": lambda: (path.unlink(), path.mkdir()),
        }
        good = json.dumps(manifest())
        for name, damage in cases.items():
            with self.subTest(case=name):
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
                path.write_text(good)
                path.chmod(0o600)
                damage()
                if path.exists() and not path.is_dir() and not path.is_symlink():
                    path.chmod(0o600)
                with self.assertRaises(rs.ReviewRefused):
                    rs.read_manifest(self.base, JOB)

    def test_the_job_directory_itself_must_be_ours_and_private(self):
        self.make()
        ldir = rs.job_dir(self.base, JOB)
        ldir.chmod(0o755)
        with self.assertRaises(rs.ReviewRefused):
            rs.read_manifest(self.base, JOB)
        ldir.chmod(0o700)
        moved = self.base / "elsewhere"
        ldir.rename(moved)
        ldir.symlink_to(moved)
        with self.assertRaises(rs.ReviewRefused):
            rs.read_manifest(self.base, JOB)

    def test_bad_ids_are_refused(self):
        for bad in ("r-xyz", "../x", None, JOB + "\n", "l-0123456789abcdef"):
            with self.subTest(job=bad):
                with self.assertRaises(rs.ReviewRefused):
                    rs.job_dir(self.base, bad)
                with self.assertRaises(rs.ReviewRefused):
                    rs.run_home(self.base, bad)

    def test_retain_keeps_the_job_for_a_person(self):
        self.make(state="running")
        rs.retain(self.base, JOB, "why")
        m = rs.read_manifest(self.base, JOB)
        self.assertEqual((m["state"], m["retained_reason"]), ("manual_review", "why"))
        # when even that cannot be written, nothing is raised
        with mock.patch.object(rs.agent_sessions, "_write_private", side_effect=OSError(5, "Input/output error")):
            rs.retain(self.base, JOB, "again")

    def test_listing(self):
        self.assertEqual(rs.list_jobs(self.base), [])
        self.make()
        (rs.reviews_root(self.base) / "notes").mkdir()
        self.assertEqual(rs.list_jobs(self.base), ["notes", JOB])         # the caller refuses what is not a job
        with mock.patch.object(rs.os, "listdir", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(PermissionError):
                rs.list_jobs(self.base)                                   # never read as "no jobs"


class FailureIdentityTests(unittest.TestCase):
    def test_identities(self):
        self.assertIsNone(rs.failure_id(manifest(state="finished")))
        self.assertIsNone(rs.failure_id(manifest(state="cleaned")))
        self.assertEqual(rs.failure_id(manifest(state="invalid")), f"{JOB}#invalid")
        at = 1791467063.473483
        ident = rs.failure_id(manifest(state="manual_review", retained_at=at))
        self.assertEqual(ident, f"{JOB}#manual_review#1791467063.473483")
        for i in (f"{JOB}#invalid", ident, "l-0123456789abcdef#3"):
            self.assertIsNotNone(pipeline_store.FAILURE_ID_RE.match(i), i)
        for i in (f"{JOB}#valid", f"{JOB}#0", f"{JOB}#invalid\n", "r-xyz#invalid", f"{JOB}#manual_review#x",
                  f"{JOB}#3"):
            self.assertIsNone(pipeline_store.FAILURE_ID_RE.match(i), i)


class ProcessCheckTests(unittest.TestCase):
    def leader(self, pid, start="1791467063.000000"):
        return {"pid": pid, "start": start, "source": proctrack.SOURCE}

    def row(self, pid, pgid, start="1791467063.000000", stat="R"):
        return {"pid": pid, "ppid": 1, "pgid": pgid, "uid": os.getuid(), "stat": stat, "start": start}

    def test_decisions(self):
        m = manifest(leader=self.leader(500))
        self.assertEqual(rs.processes_gone(manifest(), [])[0], "gone")                     # never had a process
        self.assertEqual(rs.processes_gone(m, [self.row(1, 1)])[0], "gone")
        self.assertEqual(rs.processes_gone(m, None)[0], "unknown")
        self.assertEqual(rs.processes_gone(m, [self.row(500, 500)])[0], "alive")           # the recorded leader
        # a reused pid that is not in the old group is no one of ours; one that
        # leads a group named after the old leader cannot be told apart from a
        # member, so it counts (the same conservative rule as stream recovery)
        self.assertEqual(rs.processes_gone(m, [self.row(500, 999, start="1791467099.000000")])[0], "gone")
        self.assertEqual(rs.processes_gone(m, [self.row(500, 500, start="1791467099.000000")])[0], "alive")
        self.assertEqual(rs.processes_gone(m, [self.row(777, 500)])[0], "alive")           # an unrecorded member
        self.assertEqual(rs.processes_gone(m, [self.row(777, 500, stat="Z")])[0], "gone")  # only a zombie
        seen = manifest(leader=self.leader(500), observed=[[600, "1791467070.000000"]])
        self.assertEqual(rs.processes_gone(seen, [self.row(600, 999, start="1791467070.000000")])[0], "alive")
        other = manifest(leader={"pid": 500, "start": "1791467063.000000",
                                 "source": "ps" if proctrack.SOURCE == "libproc" else "libproc"})
        self.assertEqual(rs.processes_gone(other, [])[0], "unknown")


if __name__ == "__main__":
    unittest.main()
