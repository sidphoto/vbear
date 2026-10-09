"""How a review ends (vbear/runtime/review_finish.py): the decision from the
files left on disk, the saved record, the manifest outcome, the clean-up. No
Codex, no model; a real throwaway git repository supplies a real commit."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import review_fixtures as rf
from tests import stream_fixtures as fx
from tests.test_review_store import state_manifest
from vbear.runtime import pipeline_store as ps
from vbear.runtime import review_finish as rfn
from vbear.runtime import review_store as rs
from vbear.runtime import review_validate as rv
from vbear.runtime import stream_flow as sfl

C = rf.C
JOB = "r-0123456789abcdef"
FID = "flow-0123456789ab"
TID = "task-1"


def git(cwd, *args):
    env = {"PATH": os.environ["PATH"], "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args], cwd=cwd, env=env,
                          check=True, capture_output=True, text=True).stdout.strip()


class Scenario(unittest.TestCase):
    """A review that has ended: the files its process left, ready to be judged."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vbrf-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "state"
        self.base.mkdir(mode=0o700)
        self.work = self.tmp / "work"
        self.work.mkdir()
        git(self.work, "init", "-q")
        git(self.work, "commit", "-q", "--allow-empty", "-m", "base")
        self.base_commit = git(self.work, "rev-parse", "HEAD")
        git(self.work, "commit", "-q", "--allow-empty", "-m", "change")
        self.commit = git(self.work, "rev-parse", "HEAD")
        self.scratch = Path(tempfile.mkdtemp(prefix="sr-", dir="/private/tmp"))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        rf.COMMIT, self._old = self.commit, rf.COMMIT
        self.addCleanup(setattr, rf, "COMMIT", self._old)
        fx.fake_repo(self.scratch / "repo", self.commit)
        self.run_home = self.base / "codex-run-homes" / JOB
        self.run_home.mkdir(parents=True, mode=0o700)
        self.home = self.base / "codex-home"
        self.home.mkdir(mode=0o700)
        self.text = rf.report(commit=self.commit)
        evs, recs, _ = rf.valid_run(text=self.text, scratch=str(self.scratch))
        self.events, self.recs = evs, recs
        rs.create_job_dir(self.base, JOB)
        self.job = rs.job_dir(self.base, JOB)
        (self.job / "stderr.log").write_text("log line\n")
        self.m = state_manifest(
            "running", job_id=JOB, pipeline_id=FID, task_id=TID, round=1, commit=self.commit, workdir=str(self.work),
            scratch={"path": str(self.scratch), "inode": self.scratch.stat().st_ino, "dev": self.scratch.stat().st_dev},
            run_home={"inode": self.run_home.stat().st_ino, "dev": self.run_home.stat().st_dev})
        rs.write_new_manifest(self.base, self.m)
        with ps.Pipeline(self.base, TID, create=True) as p:
            p.write_review_link(1, JOB, FID, self.commit)
        self.write_files()

    def write_files(self, events=None, recs=None):
        (self.job / "events.jsonl").write_bytes(rf.lines(self.events if events is None else events)
                                                 if not isinstance(events, bytes) else events)
        d = self.home / "sessions" / time.strftime("%Y/%m/%d")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"rollout-x-{rf.THREAD}.jsonl").write_bytes(rf.lines(self.recs if recs is None else recs)
                                                         if not isinstance(recs, bytes) else recs)

    def finish(self, **run):
        run = {"manual_review": None, "exit_code": 0, "exit_signal": None, "terminated_for": None,
               "invalid_reasons": [], **run}
        return rfn.finish_review(self.base, rs.read_manifest(self.base, JOB), run, c=C)

    def tearDown_and_setUp(self):
        shutil.rmtree(self.base, ignore_errors=True)
        shutil.rmtree(self.scratch, ignore_errors=True)
        self.setUp()

    def record(self):
        return self.base / "pipelines" / TID / "reviews" / "1"

    def manifest(self):
        return rs.read_manifest(self.base, JOB)


class ValidReviewTests(Scenario):
    def test_a_valid_review_is_saved_decided_and_cleaned_up(self):
        out = self.finish()
        self.assertEqual((out.outcome, out.reasons, out.verdict, out.base_is_ancestor, out.cleaned),
                         ("valid", [], "PASS", True, True))
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"], m["exit_code"], m["thread_id"]), ("cleaned", "valid", 0, rf.THREAD))
        self.assertIsNone(rs.failure_id(m))
        rec = self.record()
        self.assertEqual(sorted(p.name for p in rec.iterdir()),
                         ["events.jsonl", "job.json", "last.md", "result.json", "rollout.jsonl", "stderr.log"])
        self.assertEqual((rec / "last.md").read_text(), self.text)
        self.assertEqual((rec / "events.jsonl").read_bytes(), rf.lines(self.events))
        self.assertEqual((rec / "stderr.log").read_text(), "log line\n")
        self.assertEqual((rec / "rollout.jsonl").read_bytes(), rf.lines(self.recs))
        for p in rec.iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        result = json.loads((rec / "result.json").read_text())
        self.assertEqual((result["valid"], result["verdict"], result["reasons"], result["rollout"]["copied"]),
                         (True, "PASS", [], True))
        self.assertEqual(result["rollout"]["responses"], 2)
        self.assertFalse(self.scratch.exists())
        self.assertFalse(self.run_home.exists())
        self.assertEqual(sorted(p.name for p in self.job.iterdir()), ["manifest.json"])      # only the manifest stays
        source = self.home / "sessions" / time.strftime("%Y/%m/%d") / f"rollout-x-{rf.THREAD}.jsonl"
        self.assertTrue(source.exists())                                              # the source is never deleted

    def test_a_negative_verdict_is_still_a_valid_review(self):
        for verdict in ("NEEDS WORK", "BLOCKED"):
            with self.subTest(verdict=verdict):
                self.tearDown_and_setUp()
                text = rf.report(commit=self.commit, verdict=verdict)
                evs, recs, _ = rf.valid_run(text=text, scratch=str(self.scratch))
                self.events, self.recs = evs, recs
                self.write_files()
                out = self.finish()
                self.assertEqual((out.outcome, out.verdict), ("valid", verdict))
                self.assertEqual(self.manifest()["outcome"], "valid")


class InvalidReviewTests(Scenario):
    def invalid(self, expect=None, **run):
        out = self.finish(**run)
        self.assertEqual(out.outcome, "invalid", out.reasons)
        self.assertTrue(out.reasons)
        if expect:
            self.assertIn(expect, " | ".join(out.reasons))
        m = self.manifest()
        self.assertEqual((m["outcome"], m["state"]), ("invalid", "cleaned"))
        self.assertEqual(rs.failure_id(m), f"{JOB}#invalid")             # survives the clean-up
        result = json.loads((self.record() / "result.json").read_text())
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], out.reasons)
        self.assertTrue((self.record() / "events.jsonl").exists())        # the record is kept even when invalid
        return out

    def test_the_process_ending_badly(self):
        self.invalid("沒有以 0 結束", exit_code=3)
        self.tearDown_and_setUp()
        self.invalid("被訊號結束", exit_code=None, exit_signal=9)
        self.tearDown_and_setUp()
        self.invalid("被 VBear 結束", terminated_for="timeout")
        self.tearDown_and_setUp()
        self.invalid("審查被中斷", interrupted=True, exit_code=None)
        self.tearDown_and_setUp()
        self.invalid("run said so", invalid_reasons=["run said so"])

    def test_events_breaking_a_rule(self):
        for name, events in (
                ("an error event", self.events[:3] + [{"type": "error", "message": "x"}] + self.events[3:]),
                ("no turn.completed", self.events[:-1]),
                ("no final reply", [e for e in self.events if e.get("item", {}).get("type") != C.message_item_type]),
                ("unknown kind", self.events[:2] + [{"type": "surprise"}] + self.events[2:])):
            with self.subTest(case=name):
                self.tearDown_and_setUp()
                self.write_files(events=events)
                self.invalid()
        self.tearDown_and_setUp()
        self.write_files(events=rf.lines(self.events)[:-1])                  # no final newline
        self.invalid("events.jsonl")
        self.tearDown_and_setUp()
        (self.job / "events.jsonl").unlink()                                  # gone
        out = self.finish()
        self.assertEqual(out.outcome, "invalid")

    def test_the_rollout_breaking_a_rule_is_still_kept(self):
        recs = json.loads(json.dumps(self.recs))
        [r for r in recs if r["type"] == "turn_context"][0]["payload"]["sandbox_policy"]["network_access"] = True
        self.write_files(recs=recs)
        out = self.invalid("sandbox_policy")
        self.assertEqual((self.record() / "rollout.jsonl").read_bytes(), rf.lines(recs))   # the only source is kept
        self.assertTrue(json.loads((self.record() / "result.json").read_text())["rollout"]["copied"])

    def test_no_or_two_rollouts(self):
        src = self.home / "sessions" / time.strftime("%Y/%m/%d") / f"rollout-x-{rf.THREAD}.jsonl"
        src.unlink()
        out = self.invalid("rollout")
        self.assertFalse(json.loads((self.record() / "result.json").read_text())["rollout"])
        self.assertFalse((self.record() / "rollout.jsonl").exists())
        self.tearDown_and_setUp()
        src = self.home / "sessions" / time.strftime("%Y/%m/%d") / f"rollout-x-{rf.THREAD}.jsonl"
        (src.parent / f"rollout-y-{rf.THREAD}.jsonl").write_bytes(b"x\n")
        self.invalid("不只一份")

    def test_the_report(self):
        for name, text in (("another commit", rf.report(commit="c" * 40)),
                           ("no verdict", self.text.replace("VERDICT: PASS\n", "")),
                           ("base is not an ancestor", rf.report(commit=self.commit, ancestor="no")),
                           ("control line in a fence", self.text.replace(f"REVIEWED_COMMIT: {self.commit}\n",
                                                                         f"```\nREVIEWED_COMMIT: {self.commit}\n```\n"))):
            with self.subTest(case=name):
                self.tearDown_and_setUp()
                evs, recs, _ = rf.valid_run(text=text, scratch=str(self.scratch))
                self.events, self.recs = evs, recs
                self.write_files()
                out = self.invalid()
                if name == "base is not an ancestor":
                    self.assertIn(rv.BASE_NOT_ANCESTOR, out.reasons)
                    self.assertEqual(out.base_is_ancestor, False)

    def test_the_object_under_review(self):
        # the commit is not in the work directory
        other = "d" * 40
        text = rf.report(commit=other)
        evs, recs, _ = rf.valid_run(text=text, scratch=str(self.scratch))
        self.events, self.recs = evs, recs
        self.write_files()
        m = rs.read_manifest(self.base, JOB)
        rs.update_manifest(self.base, JOB)                                     # manifest unchanged; use a copy of it
        mm = dict(m, commit=other)
        out = rfn.finish_review(self.base, mm, {"manual_review": None, "exit_code": 0, "invalid_reasons": []}, c=C)
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("不存在", " | ".join(out.reasons))

    def test_the_clone_must_be_detached_at_the_reviewed_commit(self):
        for name, head in (("another commit", self.base_commit + "\n"), ("a branch", "ref: refs/heads/main\n"),
                           ("garbage", "nonsense\n")):
            with self.subTest(case=name):
                self.tearDown_and_setUp()
                (self.scratch / "repo" / ".git" / "HEAD").write_text(head)
                self.invalid("detached")
        self.tearDown_and_setUp()
        shutil.rmtree(self.scratch / "repo")
        self.invalid("detached")


class CommitOrderTests(Scenario):
    def test_result_json_is_written_after_the_manifest_holds_the_outcome(self):
        seen = []
        real_update, real_write = rs.update_manifest, rfn._write_new

        def update(base, job_id, **fields):
            if fields.get("outcome"):
                seen.append(("manifest", (self.record() / "result.json").exists()))
            return real_update(base, job_id, **fields)

        def write(dir_fd, name, data, dst):
            if name == "result.json":
                seen.append(("result", self.manifest()["outcome"]))
            return real_write(dir_fd, name, data, dst)
        with mock.patch.object(rs, "update_manifest", update), mock.patch.object(rfn, "_write_new", write):
            out = self.finish()
        self.assertEqual(seen, [("manifest", False), ("result", "valid")])
        self.assertTrue(out.record_complete)
        self.assertEqual([x["record"] for x in sfl.flow_reviews(self.base, FID, TID)], ["complete"])

    def test_a_result_json_that_cannot_be_written_leaves_a_decided_manifest_and_no_marker(self):
        real = rfn._write_new

        def write(dir_fd, name, data, dst):
            if name == "result.json":
                return rfn._Saved(False, "審查紀錄的 result.json 無法寫入（OSError）")
            return real(dir_fd, name, data, dst)
        with mock.patch.object(rfn, "_write_new", write):
            out = self.finish()
        m = self.manifest()
        self.assertEqual((out.outcome, out.record_complete, m["outcome"]), ("valid", False, "valid"))
        self.assertIn("result.json", out.problem)
        self.assertIn("審查紀錄不完整", m["retained_reason"])
        self.assertTrue((self.job / "events.jsonl").exists())                  # the originals are kept
        with self.assertRaises(sfl.FlowRefused) as cm:                          # a valid review without its marker is not believed
            sfl.flow_reviews(self.base, FID, TID)
        self.assertEqual(cm.exception.code, "count_unavailable")


class SameBytesTests(Scenario):
    """Codex 3c review #2: what is judged is what is saved, and a file
    replaced in between is noticed."""

    def swap_after_judging(self, change):
        real = rfn.git_objects.commit_exists

        def later(*a, **kw):                       # runs after events.jsonl was read and judged
            change()
            return real(*a, **kw)
        return mock.patch.object(rfn.git_objects, "commit_exists", later)

    def test_a_replaced_events_file_is_invalid_and_the_record_holds_what_was_judged(self):
        original = (self.job / "events.jsonl").read_bytes()

        def replace():
            (self.job / "events.jsonl.new").write_bytes(b'{"type":"thread.started","thread_id":"x"}\n')
            os.rename(self.job / "events.jsonl.new", self.job / "events.jsonl")
        with self.swap_after_judging(replace):
            out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("被替換或改動", " | ".join(out.reasons))
        self.assertEqual((self.record() / "events.jsonl").read_bytes(), original)   # the judged bytes
        self.assertTrue((self.job / "events.jsonl").exists())                        # the stranger is kept for a person
        self.assertNotEqual(self.manifest()["state"], "valid")

    def test_a_file_changed_in_place_is_noticed(self):
        def append():
            with open(self.job / "events.jsonl", "ab") as f:
                f.write(b"\n")
        with self.swap_after_judging(append):
            out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("events.jsonl", " | ".join(out.reasons))

    def test_stderr_is_treated_the_same_way(self):
        original = (self.job / "stderr.log").read_bytes()

        def replace():
            os.unlink(self.job / "stderr.log")
            (self.job / "stderr.log").write_text("something else\n")
        with self.swap_after_judging(replace):
            out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("stderr.log", " | ".join(out.reasons))
        self.assertEqual((self.record() / "stderr.log").read_bytes(), original)

    def test_the_file_is_read_only_once(self):
        opened = []
        real = rfn.strictjson.open_owned

        def spy(path, **kw):
            opened.append(str(path))
            return real(path, **kw)
        with mock.patch.object(rfn.strictjson, "open_owned", spy):
            self.finish()
        self.assertEqual(sorted(x for x in opened if x in ("events.jsonl", "stderr.log")),
                         ["events.jsonl", "stderr.log"])             # once each, not once to judge and once to save


class HoldTests(Scenario):
    """Codex 3c review #3: a review that ran while its flow was stopped is
    invalid even when the process ended well and every file is fine."""

    def test_a_hold_makes_a_good_review_invalid(self):
        ps.hold(self.base, FID, "user stop")
        out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("被停止", " | ".join(out.reasons))
        self.assertEqual(self.manifest()["outcome"], "invalid")
        self.assertFalse(json.loads((self.record() / "result.json").read_text())["valid"])

    def test_the_daemon_can_say_it_saw_a_hold_that_was_released_since(self):
        out = self.finish(held=True)
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("被停止", " | ".join(out.reasons))

    def test_a_hold_state_that_cannot_be_read_counts_as_held(self):
        with mock.patch.object(ps, "is_held", side_effect=OSError(5, "io")):
            out = self.finish()
        self.assertEqual(out.outcome, "invalid")

    def test_another_flows_hold_does_not_matter(self):
        ps.hold(self.base, "flow-ffffffffffff", "other")
        self.assertEqual(self.finish().outcome, "valid")


class UnprovenAndFailureTests(Scenario):
    def test_a_group_not_proven_gone_keeps_everything(self):
        out = self.finish(manual_review="程序群組在 SIGKILL 後仍有程序存活")
        self.assertEqual(out.outcome, "manual_review")
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"]), ("manual_review", "manual_review"))
        self.assertIn("SIGKILL", m["retained_reason"])
        self.assertTrue(rs.failure_id(m).startswith(f"{JOB}#manual_review#"))
        self.assertTrue(self.scratch.exists() and self.run_home.exists())
        self.assertTrue((self.job / "events.jsonl").exists())
        self.assertFalse(self.record().joinpath("result.json").exists())     # nothing was judged or saved

    def test_a_partial_that_cannot_be_removed_means_manual_review(self):
        bad = rv.CopyResult(False, None, ["rollout 的不完整複本無法移除（PermissionError），交人工處理"],
                            leftover="pipelines/task-1/reviews/1/rollout.jsonl", leftover_bytes=77)
        with mock.patch.object(rv, "copy_rollout", return_value=bad):
            out = self.finish()
        self.assertEqual((out.outcome, out.leftover, out.leftover_bytes),
                         ("manual_review", "pipelines/task-1/reviews/1/rollout.jsonl", 77))
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"]), ("manual_review", "manual_review"))
        self.assertTrue(self.scratch.exists())                                # nothing cleaned up

    def test_a_decision_that_cannot_be_written_is_manual_review(self):
        real = rs.update_manifest

        def update(base, job_id, **fields):
            if fields.get("outcome") == "valid":
                raise OSError(5, "Input/output error")
            return real(base, job_id, **fields)
        with mock.patch.object(rs, "update_manifest", update):
            out = self.finish()
        self.assertEqual(out.outcome, "manual_review")
        self.assertIn("無法寫入 manifest", out.problem)
        self.assertTrue(self.scratch.exists())
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"]), ("manual_review", "manual_review"))
        # Codex 3c review #1: result.json is written after the outcome, so
        # without the outcome there is none; the saved files stay and are named
        self.assertFalse((self.record() / "result.json").exists())
        self.assertTrue((self.record() / "last.md").exists() and (self.record() / "events.jsonl").exists())
        self.assertIn("沒有 result.json", m["retained_reason"])
        self.assertFalse(out.record_complete)
        self.assertTrue(rs.failure_id(m))                                   # the flow is blocked by it
        self.assertEqual([x["record"] for x in sfl.flow_reviews(self.base, FID, TID)], ["none"])

    def test_a_record_that_cannot_be_saved_keeps_the_originals(self):
        shutil.rmtree(self.record())
        out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("審查紀錄", " | ".join(out.reasons))
        self.assertTrue((self.job / "events.jsonl").exists())                 # the only copy is not deleted
        self.assertTrue((self.job / "stderr.log").exists())
        self.assertEqual(self.manifest()["outcome"], "invalid")

    def test_a_write_that_fails_in_the_record_is_not_left_half_done(self):
        real = os.write
        calls = []

        def failing(fd, data):
            calls.append(1)
            if len(calls) == 3:
                raise OSError(28, "No space left on device")
            return real(fd, data)
        with mock.patch.object(rfn.os, "write", failing):
            out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("無法寫入", " | ".join(out.reasons))
        names = sorted(p.name for p in self.record().iterdir())
        self.assertIn("result.json", names)                                    # the result still says what happened
        self.assertTrue((self.job / "events.jsonl").exists())

    def test_the_clean_up_only_removes_what_the_manifest_recorded(self):
        # the scratch was replaced by another directory (other inode): not deleted
        stranger = Path(tempfile.mkdtemp(prefix="sr-", dir="/private/tmp"))
        self.addCleanup(shutil.rmtree, stranger, True)
        marker = stranger / "keep-me"
        marker.write_text("x")
        shutil.rmtree(self.scratch)
        os.rename(stranger, self.scratch)
        out = self.finish()
        self.assertTrue(marker.exists() or (self.scratch / "keep-me").exists())
        self.assertIn("身分不符", out.problem)
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"]), ("invalid", "invalid"))     # decided; not cleaned
        self.assertIn("身分不符", m["retained_reason"])
        self.assertTrue(rs.failure_id(m))

    def test_a_symlinked_scratch_is_not_followed(self):
        target = self.tmp / "precious"
        target.mkdir()
        (target / "f").write_text("x")
        shutil.rmtree(self.scratch)
        os.symlink(target, self.scratch)
        out = self.finish()
        self.assertTrue((target / "f").exists())
        self.assertTrue(out.problem)
        self.scratch.unlink()

    def test_cleaning_up_twice_is_fine(self):
        self.finish()
        m = self.manifest()
        self.assertIsNone(rfn.cleanup_job(self.base, m))                       # already gone: nothing to do

    def test_a_run_home_replaced_by_a_link_is_not_followed(self):
        target = self.tmp / "other"
        target.mkdir()
        (target / "f").write_text("x")
        shutil.rmtree(self.run_home)
        os.symlink(target, self.run_home)
        out = self.finish()
        self.assertTrue((target / "f").exists())
        self.assertTrue(out.problem)


if __name__ == "__main__":
    unittest.main()
