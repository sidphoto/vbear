"""Review jobs a previous daemon left (vbear/runtime/review_recover.py): what
is judged, what is kept for a person, what is cleaned. A process table is
passed in; nothing is signalled and no process is started."""

import json
import os
import shutil
import unittest
from unittest import mock

from tests import review_fixtures as rf
from tests.test_review_finish import C, FID, JOB, TID, Scenario
from tests.test_review_store import state_manifest
from vbear.runtime import codex_constants as cc
from vbear.runtime import pipeline_store as ps
from vbear.runtime import proctrack, review_recover as rr, review_store as rs
from vbear.runtime import stream_flow as sfl

CONSTANTS = {"0.160.0": C}


def row(pid, pgid, start, stat="R"):
    return {"pid": pid, "ppid": 1, "pgid": pgid, "uid": os.getuid(), "stat": stat, "start": start}


class RecoverCase(Scenario):
    def recover(self, rows=()):
        return rr.recover(self.base, constants=CONSTANTS, rows=list(rows) if rows is not None else None)

    def leader(self):
        return self.manifest()["leader"]

    def alive_rows(self):
        lead = self.leader()
        return [row(lead["pid"], lead["pid"], lead["start"])]


class ActiveJobTests(RecoverCase):
    def test_a_running_review_whose_processes_are_gone_is_interrupted_and_invalid(self):
        items = self.recover([])
        self.assertEqual([(i["job_id"], i["action"], i["failure"]) for i in items], [(JOB, "invalid", True)])
        self.assertIn("中斷", items[0]["why"])
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"]), ("cleaned", "invalid"))
        self.assertEqual(rs.failure_id(m), f"{JOB}#invalid")
        self.assertTrue(items[0]["cleaned"])
        self.assertFalse(self.scratch.exists() or self.run_home.exists())
        result = json.loads((self.record() / "result.json").read_text())
        self.assertFalse(result["valid"])
        self.assertTrue((self.record() / "rollout.jsonl").exists())            # the rollout is handled like any other
        self.assertEqual([x["record"] for x in sfl.flow_reviews(self.base, FID, TID)], ["complete"])

    def test_nothing_is_ever_signalled(self):
        with mock.patch("os.kill") as kill, mock.patch("os.killpg") as killpg:
            self.recover([])
            self.recover(self.alive_rows())
        kill.assert_not_called()
        killpg.assert_not_called()

    def test_a_live_process_means_manual_review_and_nothing_is_touched(self):
        items = self.recover(self.alive_rows())
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("manual_review", True)])
        m = self.manifest()
        self.assertEqual((m["state"], m["outcome"]), ("manual_review", "manual_review"))
        self.assertIn("仍有已記錄的程序存活", m["retained_reason"])
        self.assertTrue(self.scratch.exists() and self.run_home.exists())
        self.assertTrue((self.job / "events.jsonl").exists())
        self.assertFalse((self.record() / "result.json").exists())
        self.assertTrue(rs.failure_id(m).startswith(f"{JOB}#manual_review#"))

    def test_an_unreadable_process_table_is_not_gone(self):
        with mock.patch.object(proctrack, "process_table", side_effect=proctrack.ProcessTableUnavailable("x")):
            items = rr.recover(self.base, constants=CONSTANTS)
        self.assertEqual(items[0]["action"], "manual_review")
        self.assertEqual(self.manifest()["outcome"], "manual_review")

    def test_a_launch_that_may_have_started_a_process_is_never_gone(self):
        rs.update_manifest(self.base, JOB, state="launching", process="maybe", leader=None)
        items = self.recover([])
        self.assertEqual(items[0]["action"], "manual_review")
        self.assertIn("pid", items[0]["why"])
        self.assertTrue(self.scratch.exists())

    def test_a_group_member_that_was_never_recorded_counts(self):
        lead = self.leader()
        items = self.recover([row(lead["pid"] + 1, lead["pid"], "1791467099.000000")])
        self.assertEqual(items[0]["action"], "manual_review")
        self.assertIn("未記錄", items[0]["why"])

    def test_a_job_that_never_started_is_invalid_without_noise(self):
        # prepared: no process, no events, no rollout. One clear reason.
        os.unlink(self.job / "events.jsonl")
        os.unlink(self.job / "stderr.log")
        rs.update_manifest(self.base, JOB, state="prepared", process="none", leader=None)
        items = self.recover([])
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("invalid", True)])
        reasons = self.manifest()["invalid_reasons"]
        self.assertIn("尚未啟動", " ".join(reasons))
        self.assertNotIn("events.jsonl", " ".join(reasons))
        self.assertNotIn("rollout", " ".join(reasons))
        self.assertEqual(self.manifest()["state"], "cleaned")
        self.assertFalse(self.scratch.exists())

    def test_the_flow_being_held_is_in_the_reasons_once(self):
        ps.hold(self.base, FID, "stop")
        self.recover([])
        reasons = self.manifest()["invalid_reasons"]
        self.assertEqual(sum(r.startswith("流程在審查期間被停止") for r in reasons), 1)

    def test_an_unknown_codex_version_is_manual_review(self):
        items = rr.recover(self.base, constants={}, rows=[])
        self.assertEqual(items[0]["action"], "manual_review")
        self.assertTrue(self.scratch.exists())

    def test_one_bad_job_does_not_stop_the_others(self):
        second = "r-" + "5" * 16
        rs.create_job_dir(self.base, second)
        (rs.job_dir(self.base, second) / rs.MANIFEST).write_text("{")
        items = self.recover([])
        by = {i["job_id"]: i for i in items}
        self.assertEqual(by[second]["action"], "unreadable")
        self.assertFalse(by[second]["failure"])
        self.assertEqual(by[JOB]["action"], "invalid")

    def test_an_unexpected_error_keeps_the_job_for_a_person(self):
        with mock.patch.object(rr.review_finish, "finish_review", side_effect=RuntimeError("boom")):
            items = self.recover([])
        self.assertEqual((items[0]["action"], items[0]["failure"]), ("error", True))
        self.assertEqual(self.manifest()["outcome"], "manual_review")
        self.assertTrue(self.scratch.exists())


class LinkAndDecidedTests(RecoverCase):
    def test_a_missing_flow_link_is_written_back(self):
        shutil.rmtree(self.base / "pipelines" / TID / "reviews")
        with self.assertRaises(sfl.FlowRefused):                       # the two sides disagree
            sfl.flow_reviews(self.base, FID, TID)
        self.recover(self.alive_rows())                                # any state
        self.assertEqual([x["job_id"] for x in sfl.flow_reviews(self.base, FID, TID)], [JOB])

    def decided_but_not_cleaned(self, outcome_valid=True):
        """The daemon decided and saved, then died before the clean-up."""
        with mock.patch.object(rr.review_finish, "cleanup_job", return_value="the daemon died here"):
            out = self.finish()
        self.assertEqual(out.outcome, "valid" if outcome_valid else "invalid")
        self.assertNotEqual(self.manifest()["state"], "cleaned")
        self.assertTrue(self.scratch.exists())

    def test_a_decided_job_is_cleaned_when_its_record_is_whole(self):
        self.decided_but_not_cleaned()
        items = self.recover([])
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("cleaned", False)])
        self.assertEqual(self.manifest()["state"], "cleaned")
        self.assertFalse(self.scratch.exists() or self.run_home.exists())
        self.assertEqual(sorted(p.name for p in self.job.iterdir()), ["manifest.json"])

    def test_a_decided_invalid_job_is_reported_as_a_failure_so_its_flow_is_held_again(self):
        # Codex 3d B4
        real = rr.review_finish.cleanup_job
        with mock.patch.object(rr.review_finish, "cleanup_job", return_value="died here"):
            self.finish(exit_code=3)
        self.assertNotEqual(self.manifest()["state"], "cleaned")
        items = self.recover([])
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("cleaned", True)])
        self.assertTrue(items[0]["why"])
        # a valid one is not a failure
        self.tearDown_and_setUp()
        with mock.patch.object(rr.review_finish, "cleanup_job", return_value="died here"):
            self.finish()
        self.assertEqual([(i["action"], i["failure"]) for i in self.recover([])], [("cleaned", False)])

    def test_a_decided_job_without_a_marker_gets_it_back_from_the_saved_copies(self):
        self.decided_but_not_cleaned()
        os.unlink(self.record() / "result.json")
        items = self.recover([])
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("cleaned", False)])
        result = json.loads((self.record() / "result.json").read_text())
        self.assertEqual((result["valid"], result["verdict"], result["rebuilt"]), (True, "PASS", True))
        self.assertEqual([x["record"] for x in sfl.flow_reviews(self.base, FID, TID)], ["complete"])
        self.assertEqual(self.manifest()["state"], "cleaned")

    def test_a_decided_job_whose_saved_copies_are_gone_is_kept_as_it_is(self):
        self.decided_but_not_cleaned()
        os.unlink(self.record() / "result.json")
        os.unlink(self.record() / "last.md")
        items = self.recover([])
        self.assertEqual([i["action"] for i in items], ["kept"])
        m = self.manifest()
        self.assertEqual(m["outcome"], "valid")                                    # neither upgraded nor downgraded
        self.assertIn("無法補寫", m["retained_reason"])
        self.assertTrue(self.scratch.exists())
        self.assertFalse((self.record() / "result.json").exists())

    def test_a_damaged_marker_is_kept(self):
        self.decided_but_not_cleaned()
        (self.record() / "result.json").write_text("{")
        items = self.recover([])
        self.assertEqual([i["action"] for i in items], ["kept"])
        self.assertTrue(self.scratch.exists())

    def test_a_manual_review_and_a_cleaned_job_are_left_alone(self):
        self.recover(self.alive_rows())                                # now manual_review
        before = self.manifest()
        self.assertEqual(self.recover([]), [])
        self.assertEqual(self.manifest(), before)


class FailureFlagTests(RecoverCase):
    """Codex 3d B-R2: every report that says the flow's record of a job is
    incomplete or cannot be trusted is a failure, so the daemon holds the flow."""

    def test_a_link_that_cannot_be_written_back_is_a_failure_for_any_state(self):
        for state in ("manual_review", "invalid", "cleaned", "running"):
            with self.subTest(state=state):
                self.tearDown_and_setUp()
                if state == "manual_review":
                    self.recover(self.alive_rows())                     # the reviewer's job: already manual_review
                elif state == "invalid":
                    self.finish(exit_code=3)
                elif state == "cleaned":
                    self.finish()
                shutil.rmtree(self.base / "pipelines" / TID / "reviews")
                with mock.patch.object(ps.Pipeline, "write_review_link", side_effect=OSError(5, "io")):
                    items = self.recover(self.alive_rows())
                problems = [i for i in items if i["action"] == "link_problem"]
                self.assertEqual(len(problems), 1, items)
                self.assertTrue(problems[0]["failure"], problems)
                self.assertEqual(problems[0]["pipeline_id"], FID)

    def test_the_second_recovery_still_holds_when_the_first_one_could_not_write_the_hold(self):
        # the reviewer's injection: manual_review already decided, link missing, link write fails
        self.recover(self.alive_rows())
        shutil.rmtree(self.base / "pipelines" / TID / "reviews")
        with mock.patch.object(ps.Pipeline, "write_review_link", side_effect=OSError(5, "io")):
            first = self.recover(self.alive_rows())
            second = self.recover(self.alive_rows())
        for items in (first, second):
            self.assertEqual([(i["action"], i["failure"]) for i in items], [("link_problem", True)])

    def test_a_decided_job_whose_record_is_not_whole_is_a_failure_even_when_valid(self):
        real = rr.review_finish.cleanup_job
        with mock.patch.object(rr.review_finish, "cleanup_job", return_value="died here"):
            self.finish()                                             # valid, whole record, only the clean-up missing
        (self.record() / "result.json").write_text("{")               # now the marker is damaged
        items = self.recover([])
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("kept", True)])

    def test_a_valid_job_with_a_whole_record_that_only_needs_cleaning_is_not_a_failure(self):
        with mock.patch.object(rr.review_finish, "cleanup_job", return_value="died here"):
            self.finish()
        with mock.patch.object(rr.review_finish, "cleanup_job", return_value="still cannot delete"):
            items = self.recover([])
        self.assertEqual([(i["action"], i["failure"]) for i in items], [("kept", False)])

    def test_the_documented_table_names_every_action_the_module_can_report(self):
        import re
        actions = set(re.findall(r'_item\([^,]+,[^,]+, "(\w+)"', open(rr.__file__).read()))
        actions |= {"invalid", "manual_review"}                       # reported from finish_review's outcome
        for action in sorted(actions):
            self.assertIn(action, rr.__doc__, f"{action} is not in the table of the module docstring")
        self.assertIn("link_problem     True", rr.__doc__)
        self.assertIn("unreadable       False", rr.__doc__)


class UnreadableRootTests(RecoverCase):
    def test_an_unreadable_manifest_blocks_every_flows_accounting_instead(self):
        # there is no flow to hold, so the accounting itself refuses for all of them
        second = "r-" + "5" * 16
        rs.create_job_dir(self.base, second)
        (rs.job_dir(self.base, second) / rs.MANIFEST).write_text("{")
        items = self.recover([])
        self.assertFalse([i for i in items if i["action"] == "unreadable"][0]["failure"])
        for pipeline, task in ((FID, TID), ("flow-ffffffffffff", "task-other")):
            with self.assertRaises(sfl.FlowRefused) as cm:
                sfl.flow_reviews(self.base, pipeline, task)
            self.assertEqual(cm.exception.code, "count_unavailable")

    def test_an_unreadable_reviews_root_is_reported(self):
        os.chmod(rs.reviews_root(self.base), 0o755)
        items = self.recover([])
        self.assertEqual([i["action"] for i in items], ["unreadable"])


if __name__ == "__main__":
    unittest.main()
