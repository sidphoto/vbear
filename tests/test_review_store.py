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
         "exit_code": None, "state": "prepared", "created": time.time(), "process": "none", "outcome": None,
         "workdir": "/Users/me/work"}
    m.update(over)
    return m


def state_manifest(state, **over):
    """A manifest whose state, outcome and process fields agree, for any state."""
    now = time.time()
    leader = {"pid": 4242, "start": f"{int(now)}.000000", "source": "libproc"}
    fields = {
        "prepared": {},
        "launching": {"process": "maybe"},
        "running": {"process": "started", "leader": leader},
        "finished": {"process": "started", "leader": leader, "exit_code": 0, "ended_at": now, "outcome": "valid"},
        "invalid": {"process": "started", "leader": leader, "exit_code": 0, "ended_at": now, "outcome": "invalid",
                    "invalid_reasons": ["rollout 不符"]},
        "manual_review": {"process": "started", "leader": leader, "ended_at": now, "outcome": "manual_review",
                          "retained_at": now, "retained_reason": "程序群組還活著"},
        "cleaned": {"process": "started", "leader": leader, "exit_code": 0, "ended_at": now, "outcome": "valid"},
    }[state]
    return manifest(state=state, **{**fields, **over})


class Base(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbrs-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.base, True)
        os.chmod(self.base, 0o700)


class ManifestSchemaTests(unittest.TestCase):
    def test_a_good_manifest_has_no_problem(self):
        self.assertIsNone(rs.manifest_problem(manifest(), JOB))
        for state in rs.STATES:
            with self.subTest(state=state):
                self.assertIsNone(rs.manifest_problem(state_manifest(state), JOB))
        self.assertIsNone(rs.manifest_problem(state_manifest(
            "manual_review", invalid_reasons=["a"], thread_id="01a11921-aaaa-bbbb", exit_code=0,
            observed=[[4243, f"{int(time.time())}.000000"]]), JOB))

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
            "workdir relative": {"workdir": "work"}, "workdir with newline": {"workdir": "/a\nb"},
            "workdir not normal": {"workdir": "/a/../b"}, "workdir trailing slash": {"workdir": "/a/"},
            "workdir none": {"workdir": None}, "workdir long": {"workdir": "/" + "x" * 2000},
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
        # the real sequence: launching (a process may exist), then running with the leader recorded
        rs.update_manifest(self.base, JOB, state="launching", process="maybe")
        leader = {"pid": 4242, "start": f"{int(time.time())}.000000", "source": "libproc"}
        m = rs.update_manifest(self.base, JOB, state="running", process="started", leader=leader,
                               thread_id="01a11921-aaaa-bbbb")
        self.assertEqual((m["state"], rs.read_manifest(self.base, JOB)["thread_id"]), ("running", "01a11921-aaaa-bbbb"))
        with self.assertRaises(rs.ReviewRefused):                 # a state the fields do not support
            rs.update_manifest(self.base, JOB, state="finished")

    def test_the_outcome_is_decided_once(self):
        self.make(**state_manifest("running"))
        now = time.time()
        rs.update_manifest(self.base, JOB, state="invalid", outcome="invalid", ended_at=now, exit_code=1,
                           invalid_reasons=["rollout 不符"])
        # it can go on to cleaned, keeping its identity
        m = rs.update_manifest(self.base, JOB, state="cleaned")
        self.assertEqual((m["state"], m["outcome"], rs.failure_id(m)), ("cleaned", "invalid", f"{JOB}#invalid"))
        for change in ({"outcome": "valid"}, {"outcome": "manual_review", "retained_at": now, "retained_reason": "x"},
                       {"outcome": None}, {"state": "running"}, {"invalid_reasons": ["another"]},
                       {"state": "finished"}):
            with self.subTest(change=change), self.assertRaises(rs.ReviewRefused):
                rs.update_manifest(self.base, JOB, **change)
        self.assertEqual(rs.read_manifest(self.base, JOB)["outcome"], "invalid")

    def test_a_manual_review_identity_does_not_move(self):
        self.make(**state_manifest("running"))
        rs.retain(self.base, JOB, "first")
        first = rs.read_manifest(self.base, JOB)
        rs.retain(self.base, JOB, "second")                        # a later look only adds a reason
        second = rs.read_manifest(self.base, JOB)
        self.assertEqual((rs.failure_id(first), second["retained_reason"]), (rs.failure_id(second), "second"))
        self.assertEqual(second["retained_at"], first["retained_at"])
        with self.assertRaises(rs.ReviewRefused):
            rs.update_manifest(self.base, JOB, retained_at=first["retained_at"] + 1)
        done = rs.update_manifest(self.base, JOB, state="cleaned")
        self.assertEqual(rs.failure_id(done), rs.failure_id(first))

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
        self.make(**{k: v for k, v in state_manifest("running").items()})
        rs.retain(self.base, JOB, "why")
        m = rs.read_manifest(self.base, JOB)
        self.assertEqual((m["state"], m["outcome"], m["retained_reason"]), ("manual_review", "manual_review", "why"))
        self.assertIn("ended_at", m)
        # when even that cannot be written, nothing is raised
        with mock.patch.object(rs.agent_sessions, "_write_private", side_effect=OSError(5, "Input/output error")):
            rs.retain(self.base, JOB, "again")

    def test_listing(self):
        self.assertEqual(rs.list_jobs(self.base), [])
        self.make()
        (rs.reviews_root(self.base) / "notes").mkdir()
        self.assertEqual(rs.list_jobs(self.base), ["notes", JOB])         # the caller refuses what is not a job
        with mock.patch.object(rs.os, "listdir", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(rs.ReviewRefused):
                rs.list_jobs(self.base)                                   # never read as "no jobs"

    def test_the_root_is_checked_like_sessions(self):
        # S2b part 1 review P2: a symlink to an empty directory was "no jobs"
        self.make()
        root = rs.reviews_root(self.base)
        empty = self.base / "empty"
        empty.mkdir(mode=0o700)
        moved = self.base / "moved"
        root.rename(moved)
        root.symlink_to(empty)
        with self.assertRaises(rs.ReviewRefused):
            rs.list_jobs(self.base)
        root.unlink()
        moved.rename(root)
        root.chmod(0o755)
        with self.assertRaises(rs.ReviewRefused):
            rs.list_jobs(self.base)
        root.chmod(0o700)
        shutil.rmtree(root)
        root.write_text("a file")
        with self.assertRaises(rs.ReviewRefused):
            rs.list_jobs(self.base)


class FailureIdentityTests(unittest.TestCase):
    def test_identities(self):
        self.assertIsNone(rs.failure_id(state_manifest("finished")))
        self.assertIsNone(rs.failure_id(state_manifest("cleaned")))                 # cleaned after a valid review
        self.assertEqual(rs.failure_id(state_manifest("invalid")), f"{JOB}#invalid")
        # the failure outlives the clean-up: the outcome, not the state, decides (S2b part 1 review P1)
        self.assertEqual(rs.failure_id(state_manifest("cleaned", outcome="invalid", invalid_reasons=["x"])),
                         f"{JOB}#invalid")
        at = 1791467063.473483
        ident = rs.failure_id(state_manifest("manual_review", retained_at=at))
        self.assertEqual(ident, f"{JOB}#manual_review#1791467063.473483")
        self.assertEqual(rs.failure_id(state_manifest("cleaned", outcome="manual_review", retained_at=at,
                                                       retained_reason="x")), ident)
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

    def running(self, pid=500, **over):
        return state_manifest("running", leader=self.leader(pid), **over)

    def test_decisions(self):
        m = self.running()
        self.assertEqual(rs.processes_gone(manifest(), [])[0], "gone")                     # never had a process
        self.assertEqual(rs.processes_gone(manifest(), None)[0], "gone")
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
        seen = self.running(observed=[[600, "1791467070.000000"]])
        self.assertEqual(rs.processes_gone(seen, [self.row(600, 999, start="1791467070.000000")])[0], "alive")
        other = state_manifest("running", leader={"pid": 500, "start": "1791467063.000000",
                                                  "source": "ps" if proctrack.SOURCE == "libproc" else "libproc"})
        self.assertEqual(rs.processes_gone(other, [])[0], "unknown")

    def test_a_launch_that_may_have_started_a_process_is_never_gone(self):
        # the crash window between "launching" and the recorded leader
        launching = state_manifest("launching")
        for rows in ([], None, [self.row(1, 1)]):
            self.assertEqual(rs.processes_gone(launching, rows)[0], "unknown")
        crashed_terminal = state_manifest("invalid", process="maybe", leader=None)
        self.assertEqual(rs.processes_gone(crashed_terminal, [])[0], "unknown")

    def test_a_manifest_whose_process_fields_disagree_is_not_trusted(self):
        # P1: leader null while a process was started, or the reverse, never reads as "gone"
        bad = {
            "started without a leader": state_manifest("running", leader=None),
            "leader without a started process": state_manifest("running", process="none"),
            "running without a process": state_manifest("running", process="none", leader=None),
            "launching with a leader": state_manifest("launching", leader=self.leader(500), process="started"),
            "prepared with a process": manifest(process="maybe"),
            "prepared with a leader": manifest(leader=self.leader(500), process="started"),
            "observed without a process": manifest(observed=[[600, "1791467070.000000"]]),
            "finished without a process": state_manifest("finished", process="none", leader=None),
            "leader but process maybe": state_manifest("invalid", process="maybe"),
        }
        for name, m in bad.items():
            with self.subTest(case=name):
                self.assertIsNotNone(rs.manifest_problem(m, JOB), name)


class StateDependentFieldTests(unittest.TestCase):
    """P2: what each outcome and each final state requires, so a failure's
    identity cannot be made from a missing value and change later."""

    def test_required_fields_per_state_and_outcome(self):
        missing = {
            "manual_review without retained_at": ("manual_review", "retained_at"),
            "manual_review without retained_reason": ("manual_review", "retained_reason"),
            "manual_review without ended_at": ("manual_review", "ended_at"),
            "invalid without invalid_reasons": ("invalid", "invalid_reasons"),
            "invalid without ended_at": ("invalid", "ended_at"),
            "finished without ended_at": ("finished", "ended_at"),
            "finished without exit_code": ("finished", "exit_code"),
            "cleaned without ended_at": ("cleaned", "ended_at"),
            "outcome invalid kept by cleaned, without reasons": ("cleaned", "invalid_reasons"),
        }
        for name, (state, field) in missing.items():
            with self.subTest(case=name):
                m = state_manifest("cleaned", outcome="invalid", invalid_reasons=["x"]) if "outcome invalid" in name \
                    else state_manifest(state)
                m.pop(field)
                if field == "exit_code":
                    m["exit_code"] = None
                self.assertIsNotNone(rs.manifest_problem(m, JOB), name)
        for field, value in (("invalid_reasons", []), ("retained_reason", "")):
            m = state_manifest("invalid" if field == "invalid_reasons" else "manual_review", **{field: value})
            self.assertIsNotNone(rs.manifest_problem(m, JOB), field)

    def test_state_and_outcome_go_together(self):
        bad = {
            "prepared with an outcome": manifest(outcome="valid"),
            "running with an outcome": state_manifest("running", outcome="invalid"),
            "finished invalid": state_manifest("finished", outcome="invalid"),
            "invalid but valid": state_manifest("invalid", outcome="valid"),
            "manual_review but invalid": state_manifest("manual_review", outcome="invalid"),
            "finished without an outcome": state_manifest("finished", outcome=None),
            "cleaned without an outcome": state_manifest("cleaned", outcome=None),
            "an outcome nobody knows": state_manifest("finished", outcome="maybe"),
        }
        for name, m in bad.items():
            with self.subTest(case=name):
                self.assertIsNotNone(rs.manifest_problem(m, JOB), name)


if __name__ == "__main__":
    unittest.main()
