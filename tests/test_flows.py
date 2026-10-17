"""Flows board (stage 1): storage, derivation, family rule, commit binding,
API and malformed input. No model calls; repositories are fake .git dirs."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import flows, tasks
from vbear.jsonstore import StoreError

C1, C2, C3 = "a" * 40, "b" * 40, "c" * 64
NAN, INF = float("nan"), float("inf")


def fake_repo(root: Path, commit: str) -> Path:
    (root / ".git" / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "refs" / "heads" / "main").write_text(commit + "\n")
    return root


def roles(workdir=None, executor_family="anthropic", reviewer_families=("openai",)):
    ex = {"name": "執行者", "family": executor_family}
    if workdir:
        ex["workdir"] = str(workdir)
    return {"planner": {"name": "規劃者", "family": "anthropic"}, "executor": ex,
            "reviewers": [{"name": f"審查{i}", "family": f} for i, f in enumerate(reviewer_families)]}


class FlowCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "st"
        self.home.mkdir()
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.repo = fake_repo(self.root / "repo", C1)

    def task(self, title="任務"):
        return tasks.save_task(None, {"title": title})["id"]

    def flow(self, **kw):
        return flows.create_flow({"task_id": self.task(), "roles": roles(**kw)},
                                 lambda t: tasks.get_task(t) is not None)["id"]

    def add(self, fid, kind, **fields):
        return flows.append_event(fid, {"kind": kind, **fields})

    def derive(self, fid):
        return flows.derive(flows.get_flow(fid), flows.head_reader)


class StorageTests(FlowCase):
    def test_file_is_private_and_round_trips(self):
        fid = self.flow(workdir=self.repo)
        path = self.home / "flows.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(flows.get_flow(fid)["roles"]["executor"]["workdir"], str(self.repo))

    def corrupt_and_expect_block(self, content):
        self.flow()
        (self.home / "flows.json").write_text(content)
        with self.assertRaises(StoreError):
            flows.list_flows()
        self.assertTrue((self.home / "flows.json.corrupted").exists())
        with self.assertRaises(StoreError):     # blocked until a person clears the marker
            flows.list_flows()
        with self.assertRaises(StoreError):
            self.flow()
        self.assertTrue(list(self.home.glob("flows.json.corrupt-*")))   # bad bytes kept aside

    def test_unparseable_file_blocks_reads_and_writes(self):
        self.corrupt_and_expect_block("{not json")

    def test_entry_this_module_never_writes_blocks(self):
        self.corrupt_and_expect_block(json.dumps({"flow-000000000000": {"id": "flow-000000000000"}}))

    def test_event_with_bad_time_or_order_blocks(self):
        fid = self.flow()
        self.add(fid, "note")
        self.add(fid, "note")
        data = json.loads((self.home / "flows.json").read_text())
        for first, second in ((NAN, None), ("1", None), (10 ** 400, None), (-5.0, None), (0, None),
                              (1e12, None), (2e9, 1e9), (None, None), (True, None)):
            with self.subTest(first=type(first).__name__, second=second):
                broken = json.loads(json.dumps(data))
                broken[fid]["events"][0]["at"] = first
                if second is not None:
                    broken[fid]["events"][1]["at"] = second
                self.assertIsNotNone(flows._entry_problem(fid, broken[fid]))

    def test_symlink_or_hard_link_is_refused(self):
        self.flow()
        real = self.home / "flows.json"
        other = self.root / "elsewhere.json"
        os.link(real, other)
        with self.assertRaises(StoreError):
            flows.list_flows()

    def test_concurrent_writers_lose_nothing(self):
        fid = self.flow()
        errors = []

        def write(n):
            try:
                for _ in range(n):
                    self.add(fid, "note", note="x")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
        threads = [threading.Thread(target=write, args=(10,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        events = flows.get_flow(fid)["events"]
        self.assertEqual([e["seq"] for e in events], list(range(1, 41)))


class DerivationTests(FlowCase):
    def test_phases_follow_the_events(self):
        fid = self.flow(workdir=self.repo)
        expect = []
        self.assertEqual(self.derive(fid)["phase"]["key"], "planning")
        for kind, fields, phase in (
                ("plan_submitted", {}, "awaiting_approval"),
                ("plan_approved", {}, "implementing"),
                ("executor_report", {"commit": C1}, "in_review"),
                ("review_result", {"reviewer": 0, "verdict": "NEEDS_WORK", "commit": C1}, "needs_fix"),
                ("executor_report", {"commit": C1}, "in_review"),
                ("review_result", {"reviewer": 0, "verdict": "PASS", "commit": C1}, "awaiting_merge"),
                ("merge_done", {}, "awaiting_push"),
                ("push_done", {}, "done")):
            self.add(fid, kind, **fields)
            d = self.derive(fid)
            expect.append(d["phase"]["key"])
            self.assertEqual(d["phase"]["key"], phase, kind)
        d = self.derive(fid)
        self.assertEqual(len(d["rounds"]), 2)
        self.assertEqual(d["warnings"], [])

    def test_attention_is_only_for_the_users_gates(self):
        fid = self.flow(workdir=self.repo)
        self.assertFalse(self.derive(fid)["attention"])
        self.add(fid, "plan_submitted")
        self.assertTrue(self.derive(fid)["attention"])
        self.add(fid, "plan_approved")
        self.assertFalse(self.derive(fid)["attention"])

    def test_same_or_unknown_family_review_never_passes(self):
        for ex, rv in (("anthropic", "anthropic"), ("anthropic", "unknown"), ("anthropic", "other"),
                       ("unknown", "openai"), ("other", "openai")):
            with self.subTest(executor=ex, reviewer=rv):
                fid = self.flow(workdir=self.repo, executor_family=ex, reviewer_families=(rv,))
                self.add(fid, "executor_report", commit=C1)
                self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
                d = self.derive(fid)
                self.assertEqual(d["phase"]["key"], "in_review")
                self.assertFalse(d["rounds"][0]["reviews"][0]["counts_as_pass"])
                self.assertTrue(d["rounds"][0]["reviews"][0]["why"])

    def test_roles_changed_later_do_not_turn_an_old_review_into_a_pass(self):
        fid = self.flow(workdir=self.repo, reviewer_families=("anthropic",))
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        flows.set_roles(fid, {"roles": roles(workdir=self.repo, reviewer_families=("openai",))})
        d = self.derive(fid)
        self.assertNotEqual(d["phase"]["key"], "awaiting_merge")
        self.assertEqual(flows.get_flow(fid)["events"][-1]["kind"], "roles_changed")

    def test_a_pass_goes_stale_when_head_moves(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.assertEqual(self.derive(fid)["binding"]["state"], "current")
        fake_repo(self.repo, C2)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["binding"]["state"]), ("review_stale", "stale"))
        self.assertIn("已過期", d["phase"]["reason"])

    def test_a_pass_without_a_readable_head_is_unverified(self):
        fid = self.flow()                                       # no workdir
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.assertEqual(self.derive(fid)["phase"]["key"], "review_unverified")
        fid2 = self.flow(workdir=self.root)                     # not a repository
        self.add(fid2, "executor_report", commit=C1)
        self.add(fid2, "review_result", reviewer=0, verdict="PASS", commit=C1)
        d = self.derive(fid2)
        self.assertEqual(d["phase"]["key"], "review_unverified")
        self.assertTrue(d["attention"])

    def test_a_review_of_an_older_commit_is_not_this_rounds_result(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C2)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C2)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "in_review")
        self.assertEqual(len(d["stray_reviews"]), 1)

    def passed_merged_pushed(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.add(fid, "merge_done")
        self.add(fid, "push_done")
        self.assertEqual(self.derive(fid)["phase"]["key"], "done")
        return fid

    def test_a_late_pass_of_the_merged_commit_does_not_reopen_the_flow(self):
        # Codex S1 #3: report, PASS, merge, push, then another PASS of the same commit.
        fid = self.passed_merged_pushed()
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "done")
        late = d["rounds"][-1]["reviews"][-1]
        self.assertFalse(late["counts_as_pass"])
        self.assertIn("合併後", late["why"])
        self.assertEqual(d["warnings"], [])

    def test_a_late_pass_between_merge_and_push_does_not_go_back_to_awaiting_merge(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.add(fid, "merge_done")
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.assertEqual(self.derive(fid)["phase"]["key"], "awaiting_push")

    def test_a_late_objection_keeps_the_phase_and_is_flagged(self):
        fid = self.passed_merged_pushed()
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "done")
        self.assertEqual(len(d["warnings"]), 1)
        self.assertIn("NEEDS_WORK", d["warnings"][0])

    def test_reporting_the_merged_commit_again_does_not_open_a_round(self):
        fid = self.passed_merged_pushed()
        self.add(fid, "executor_report", commit=C1)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], len(d["rounds"])), ("done", 1))
        self.assertEqual(len(d["warnings"]), 1)

    def test_a_new_commit_after_push_opens_a_new_round(self):
        fid = self.passed_merged_pushed()
        fake_repo(self.repo, C2)
        self.add(fid, "executor_report", commit=C2)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"]), ("in_review", 2))
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C2)
        self.assertEqual(self.derive(fid)["phase"]["key"], "awaiting_merge")

    def test_re_reporting_the_same_commit_before_merge_still_opens_a_round(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)
        self.add(fid, "executor_report", commit=C1)
        self.assertEqual(self.derive(fid)["phase"]["round"], 2)

    def test_merge_without_a_valid_pass_is_flagged(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "merge_done")
        self.add(fid, "push_done")
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "done")
        self.assertEqual(len(d["warnings"]), 1)


DISPATCH = "11111111-2222-4333-8444-555555555555"
JOB1, JOB2 = "r-" + "1" * 16, "r-" + "2" * 16


class AutomaticPhaseTests(FlowCase):
    """The phase also reads the automatic mode's own events (S3 alignment item 8): a flow that only the runner
    moves does not stay at 「計畫中」. Derivation only: nothing is written, the merge gate is not touched."""

    def auto(self, fid, kind, **fields):
        return flows.append_automation_event(fid, kind, fields)

    def turn_on(self, fid):
        self.add(fid, "note", note="approval stands in here")
        self.auto(fid, "automation_mode", mode="auto", approval_seq=1)

    def report(self, fid, commit, dispatch=None):
        dispatch = dispatch or "11111111-2222-4333-8444-%012x" % (len(flows.get_flow(fid)["events"]) + 1)
        self.auto(fid, "auto_dispatch_intent", dispatch_id=dispatch, text_sha256="a" * 64, length=10)
        self.auto(fid, "auto_dispatch_sent", dispatch_id=dispatch)
        self.auto(fid, "auto_report", dispatch_id=dispatch, commit=commit, status="done", tests_result="passed")

    def review(self, fid, round_, commit, verdict, job=JOB1):
        self.auto(fid, "auto_review_intent", round=round_, commit=commit)
        self.auto(fid, "auto_review_started", round=round_, job_id=job)
        self.auto(fid, "auto_review_result", round=round_, job_id=job, commit=commit, verdict=verdict, valid=True)

    def key(self, fid):
        return self.derive(fid)["phase"]["key"]

    def test_a_flow_only_the_runner_moves_has_the_right_phase_at_every_step(self):
        fid = self.flow(workdir=self.repo)
        self.assertEqual(self.key(fid), "planning")
        self.turn_on(fid)                                           # the plan was approved with the switch
        self.assertEqual(self.key(fid), "implementing")
        self.auto(fid, "auto_dispatch_intent", dispatch_id=DISPATCH, text_sha256="a" * 64, length=10)
        self.assertEqual(self.key(fid), "implementing")            # an intent is not a fact
        self.auto(fid, "auto_dispatch_sent", dispatch_id=DISPATCH)
        self.assertEqual(self.key(fid), "implementing")
        self.auto(fid, "auto_report", dispatch_id=DISPATCH, commit=C1, status="done", tests_result="passed")
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"], d["phase"]["label"]), ("in_review", 1, "審查第 1 輪"))
        self.auto(fid, "auto_review_intent", round=1, commit=C1)
        self.auto(fid, "auto_review_started", round=1, job_id=JOB1)
        self.assertEqual(self.key(fid), "in_review")
        self.auto(fid, "auto_review_result", round=1, job_id=JOB1, commit=C1, verdict="NEEDS WORK", valid=True)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "needs_fix")
        self.assertEqual([(r["verdict"], r["counts_as_pass"]) for r in d["rounds"][0]["reviews"]],
                         [("NEEDS_WORK", False)])
        # the forwarded comments and the executor's fix
        fake_repo(self.repo, C2)
        self.auto(fid, "auto_dispatch_intent", dispatch_id=DISPATCH.replace("5", "6"), text_sha256="b" * 64, length=11)
        self.auto(fid, "auto_dispatch_sent", dispatch_id=DISPATCH.replace("5", "6"))
        self.assertEqual(self.key(fid), "needs_fix")
        self.auto(fid, "auto_report", dispatch_id=DISPATCH.replace("5", "6"), commit=C2, status="done",
                  tests_result="passed")
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"]), ("in_review", 2))
        self.review(fid, 2, C2, "PASS", JOB2)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["binding"]["state"], d["attention"]), ("awaiting_merge", "current", True))
        self.auto(fid, "auto_stopped", reason_code="awaiting_merge", detail="審查通過，各項核對成立")
        self.assertEqual(self.key(fid), "awaiting_merge")           # a stop is not a phase of its own
        d = self.derive(fid)
        self.assertEqual([len(r["reviews"]) for r in d["rounds"]], [1, 1])
        self.assertEqual(d["warnings"], [])
        self.assertEqual(d["stray_reviews"], [])
        self.assertEqual(d["rounds"][1]["reviews"][0]["family"], "openai")

    def test_manual_and_automatic_records_of_the_same_facts_are_not_counted_twice(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.add(fid, "plan_approved")                              # by hand as well
        self.add(fid, "executor_report", commit=C1)                # recorded by hand ...
        self.report(fid, C1)                                        # ... and by the runner: one round
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], len(d["rounds"])), ("in_review", 1))
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)
        self.review(fid, 1, C1, "NEEDS WORK")                       # the same verdict twice: one review
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], len(d["rounds"][0]["reviews"])), ("needs_fix", 1))
        # the other order: the runner first, the hand after
        fake_repo(self.repo, C2)
        self.report(fid, C2)
        self.add(fid, "executor_report", commit=C2)
        self.review(fid, 2, C2, "PASS", JOB2)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C2)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"]), ("awaiting_merge", 2))
        self.assertEqual([len(r["reviews"]) for r in d["rounds"]], [1, 1])
        self.assertEqual(d["warnings"], [])

    def test_the_last_thing_that_happened_wins_whichever_source_wrote_it(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "PASS")
        self.assertEqual(self.key(fid), "awaiting_merge")
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)     # a person objects after
        self.assertEqual(self.key(fid), "needs_fix")
        self.add(fid, "executor_report", commit=C1)                 # the executor reports it again: a new round
        self.assertEqual((self.key(fid), self.derive(fid)["phase"]["round"]), ("in_review", 2))
        self.review(fid, 2, C1, "PASS", JOB2)
        self.assertEqual(self.key(fid), "awaiting_merge")

    def test_a_report_of_the_same_commit_after_a_review_is_a_new_round_whoever_made_the_first(self):
        # the reviewer's sequence: the runner's report and PASS, then the executor reports the commit again
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "PASS")
        self.assertEqual(self.key(fid), "awaiting_merge")
        self.add(fid, "executor_report", commit=C1)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"], d["attention"]), ("in_review", 2, False))
        self.assertEqual([len(r["reviews"]) for r in d["rounds"]], [1, 0])
        # and by hand first, then the runner: the same
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.report(fid, C1)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"]), ("in_review", 2))

    def test_a_person_mirroring_the_automatic_records_before_the_review_adds_no_round_and_no_review(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.add(fid, "executor_report", commit=C1)                 # mirrored before any review of it
        self.review(fid, 1, C1, "NEEDS WORK")
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)    # the same verdict
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], len(d["rounds"]), len(d["rounds"][0]["reviews"])), ("needs_fix", 1, 1))
        self.assertEqual((d["warnings"], d["stray_reviews"]), ([], []))

    def test_a_manual_review_by_the_same_family_does_not_hide_the_automatic_one(self):
        fid = self.flow(workdir=self.repo, reviewer_families=("anthropic",))      # same family as the executor
        self.turn_on(fid)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)     # does not count
        self.assertEqual(self.key(fid), "in_review")
        self.review(fid, 1, C1, "PASS")                              # the runner's reviewer is another family
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "awaiting_merge")
        self.assertEqual([r["counts_as_pass"] for r in d["rounds"][0]["reviews"]], [False, True])

    def test_an_automatic_review_by_the_executors_own_family_or_an_unknown_one_never_passes(self):
        for family in ("openai", "unknown", "other"):
            with self.subTest(executor=family):
                fid = self.flow(workdir=self.repo, executor_family=family)
                self.turn_on(fid)
                self.report(fid, C1)
                self.review(fid, 1, C1, "PASS")
                d = self.derive(fid)
                self.assertEqual(d["phase"]["key"], "in_review")
                self.assertFalse(d["rounds"][0]["reviews"][0]["counts_as_pass"])
                self.assertIn("不算", d["phase"]["reason"])

    def test_roles_changed_after_an_automatic_review_make_its_family_unknown(self):
        fid = self.flow(workdir=self.repo, executor_family="anthropic")
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "PASS")
        self.assertEqual(self.key(fid), "awaiting_merge")
        flows.set_roles(fid, {"roles": roles(workdir=self.repo, executor_family="anthropic")})
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "in_review")           # judged against roles that are not kept
        self.assertFalse(d["rounds"][0]["reviews"][0]["counts_as_pass"])

    def test_events_that_are_not_phase_facts_move_nothing(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "note", note="x")
        self.auto(fid, "auto_review_intent", round=1, commit=C1)
        self.auto(fid, "auto_review_started", round=1, job_id=JOB1)
        self.auto(fid, "auto_review_aborted", round=1, job_id=JOB1, commit=C1)
        self.auto(fid, "auto_stopped", reason_code="turn_failed", detail="x")
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["rounds"], d["stray_reviews"]), ("planning", [], []))
        # a review that is not valid is not a verdict
        self.auto(fid, "auto_review_result", round=1, job_id=JOB1, commit=C1, verdict="PASS", valid=False)
        self.assertEqual(self.key(fid), "planning")
        # switching back to manual is not an approval either
        self.auto(fid, "automation_mode", mode="manual", approval_seq=None)
        self.assertEqual(self.key(fid), "planning")

    def test_the_tasks_directory_stands_in_when_the_role_names_none(self):
        # automatic mode compares HEAD with the task's directory; a caller in that mode passes it in
        fid = self.flow()                                                # the executor role has no workdir
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "PASS")
        flow = flows.get_flow(fid)
        d = flows.derive(flow, flows.head_reader)
        self.assertEqual(d["phase"]["key"], "review_unverified")        # without it: as before
        self.assertNotIn("source", d["binding"])
        d = flows.derive(flow, flows.head_reader, str(self.repo))
        self.assertEqual((d["phase"]["key"], d["binding"]["state"]), ("awaiting_merge", "current"))
        self.assertEqual(d["binding"]["source"], "task_workdir")
        self.assertIn("以任務工作目錄核對", d["phase"]["reason"])
        self.assertIn("以任務工作目錄核對", d["binding"]["detail"])
        self.assertTrue(d["attention"])
        fake_repo(self.repo, C2)                                         # HEAD moved on
        d = flows.derive(flow, flows.head_reader, str(self.repo))
        self.assertEqual((d["phase"]["key"], d["binding"]["state"]), ("review_stale", "stale"))
        self.assertIn("以任務工作目錄核對", d["phase"]["reason"])
        # a directory that cannot be read keeps it unverified, and says which directory it was
        d = flows.derive(flow, flows.head_reader, str(self.root))
        self.assertEqual((d["phase"]["key"], d["binding"]["state"]), ("review_unverified", "unverified"))
        self.assertIn("以任務工作目錄核對", d["phase"]["reason"])
        self.assertIsNone(d["binding"]["head"])

    def test_a_directory_on_the_role_is_never_replaced_by_the_tasks(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "PASS")
        other = fake_repo(self.root / "other", C2)
        d = flows.derive(flows.get_flow(fid), flows.head_reader, str(other))
        self.assertEqual((d["phase"]["key"], d["binding"]["state"]), ("awaiting_merge", "current"))
        self.assertNotIn("source", d["binding"])
        self.assertNotIn("任務工作目錄", d["phase"]["reason"])

    def test_a_replayed_automatic_result_is_not_hung_on_a_later_round(self):
        # the reviewer's sequence: two reports of one commit, then round 1's PASS (same job) again
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "NEEDS WORK")                     # job 1: NEEDS WORK
        self.report(fid, C1)                                       # reported again (round 2)
        self.assertEqual(self.derive(fid)["phase"]["round"], 2)
        self.auto(fid, "auto_review_result", round=1, job_id=JOB1, commit=C1, verdict="PASS", valid=True)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["attention"]), ("in_review", False))
        self.assertEqual([len(r["reviews"]) for r in d["rounds"]], [1, 0])
        self.assertTrue(any("重複" in w for w in d["warnings"]), d["warnings"])

    def test_a_result_whose_round_or_job_is_not_the_timelines_is_not_counted(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.auto(fid, "auto_review_intent", round=1, commit=C1)
        self.auto(fid, "auto_review_started", round=1, job_id=JOB1)
        # the result names round 2 for job 1; a job nobody started; a commit the intent did not name
        for fields in ({"round": 2, "job_id": JOB1, "commit": C1}, {"round": 1, "job_id": JOB2, "commit": C1},
                       {"round": 1, "job_id": JOB1, "commit": C2}):
            self.auto(fid, "auto_review_result", verdict="PASS", valid=True, **fields)
            d = self.derive(fid)
            self.assertEqual((d["phase"]["key"], d["attention"], d["rounds"][0]["reviews"]), ("in_review", False, []))
        self.assertEqual(len(self.derive(fid)["warnings"]), 3)
        # the right one is still counted afterwards
        self.auto(fid, "auto_review_result", round=1, job_id=JOB1, commit=C1, verdict="PASS", valid=True)
        self.assertEqual(self.key(fid), "awaiting_merge")

    def test_a_result_of_a_job_started_in_an_earlier_report_round_is_not_this_rounds(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.auto(fid, "auto_review_intent", round=1, commit=C1)
        self.auto(fid, "auto_review_started", round=1, job_id=JOB1)
        self.add(fid, "executor_report", commit=C1)                # a person re-reports the same commit: round 2
        self.assertEqual(self.derive(fid)["phase"]["round"], 1)    # one source each: the same fact, no new round
        fake_repo(self.repo, C2)
        self.add(fid, "executor_report", commit=C2)
        self.add(fid, "executor_report", commit=C2)               # (same source again: round 3)
        self.assertEqual(self.derive(fid)["phase"]["round"], 3)
        self.auto(fid, "auto_review_result", round=1, job_id=JOB1, commit=C1, verdict="PASS", valid=True)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "in_review")
        self.assertTrue(any("先前的回報輪次" in w or "不符" in w for w in d["warnings"]), d["warnings"])

    def test_a_dispatch_is_counted_once(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.auto(fid, "auto_dispatch_sent", dispatch_id=DISPATCH)
        self.auto(fid, "auto_dispatch_sent", dispatch_id=DISPATCH)
        self.auto(fid, "auto_report", dispatch_id=DISPATCH, commit=C1, status="done", tests_result="passed")
        fake_repo(self.repo, C2)
        self.auto(fid, "auto_report", dispatch_id=DISPATCH, commit=C2, status="done", tests_result="passed")
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], len(d["rounds"]), d["rounds"][0]["commit"]), ("in_review", 1, C1))
        self.assertEqual(len(d["warnings"]), 2, d["warnings"])

    def test_deriving_writes_nothing(self):
        fid = self.flow(workdir=self.repo)
        self.turn_on(fid)
        self.report(fid, C1)
        self.review(fid, 1, C1, "NEEDS WORK")
        path = flows.store.path()
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.derive(fid)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)


class InputTests(FlowCase):
    def test_one_flow_per_task_and_task_must_exist(self):
        tid = self.task()
        ok = lambda t: tasks.get_task(t) is not None  # noqa: E731
        flows.create_flow({"task_id": tid, "roles": roles()}, ok)
        with self.assertRaises(ValueError):
            flows.create_flow({"task_id": tid, "roles": roles()}, ok)
        with self.assertRaises(ValueError):
            flows.create_flow({"task_id": "no-such-task", "roles": roles()}, ok)

    def test_strict_fields_per_kind(self):
        fid = self.flow()
        bad = [
            {"kind": "launch_agent"},                                       # not a kind
            {"kind": "roles_changed", "roles": roles()},                    # server-only kind
            {"kind": "note", "commit": C1},                                 # field not for this kind
            {"kind": "note", "at": 1.0},                                    # time is the server's
            {"kind": "note", "source": "vbear"},                            # source is the server's
            {"kind": "executor_report", "commit": "abc1234"},               # short commit
            {"kind": "executor_report", "commit": C1.upper()},
            {"kind": "review_result", "reviewer": 0, "verdict": "LGTM", "commit": C1},
            {"kind": "review_result", "reviewer": 5, "verdict": "PASS", "commit": C1},
            {"kind": "review_result", "reviewer": True, "verdict": "PASS", "commit": C1},
            {"kind": "note", "note": "x" * 2001},
            {"kind": "executor_report", "commit": C1 + "\n"},          # $ would have let this through
            {"kind": "review_result", "reviewer": 0, "verdict": "PASS", "commit": C1 + "\n"},
        ]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                with self.assertRaises(ValueError):
                    flows.append_event(fid, body)
        self.assertEqual(flows.get_flow(fid)["events"], [])
        with self.assertRaises(KeyError):
            flows.append_event("flow-ffffffffffff", {"kind": "note"})

    def test_the_view_says_whether_a_reviewer_is_independent_of_the_executor(self):
        # the rule a recorded PASS is judged by, said before any review exists
        cases = (("anthropic", ("openai", "google"), [True, True]),
                 ("anthropic", ("anthropic", "unknown"), [False, False]),
                 ("other", ("openai",), [False]))
        for executor_family, reviewers, expected in cases:
            with self.subTest(executor=executor_family, reviewers=reviewers):
                fid = self.flow(executor_family=executor_family, reviewer_families=reviewers)
                view = flows.view(flows.get_flow(fid), heads=flows.head_reader, task_title=lambda t: "t",
                                  live=None, now=0)
                got = [r["independent_of_executor"] for r in view["roles"]["reviewers"]]
                self.assertEqual([g["counted"] for g in got], expected)
                for g in got:
                    self.assertEqual(bool(g["why"]), not g["counted"])        # a refusal always says why

    def test_role_validation(self):
        tid = self.task()
        ok = lambda t: True  # noqa: E731
        bad_roles = [
            {**roles(), "extra": {}},
            {**roles(), "reviewers": []},
            {**roles(), "reviewers": [{"name": "x", "family": "openai"}] * 5},
            {**roles(), "planner": {"name": "", "family": "anthropic"}},
            {**roles(), "planner": {"name": "p", "family": "gpt"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "session_id": "n-zz"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "session_id": "n-0123456789ab\n"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "workdir": "relative"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "workdir": str(self.root / "missing")}},
            {**roles(), "planner": {"name": "p", "family": "anthropic", "workdir": "/tmp"}},   # only executor has one
        ]
        for r in bad_roles:
            with self.subTest(roles=str(r)[:70]):
                with self.assertRaises(ValueError):
                    flows.create_flow({"task_id": tid, "roles": r}, ok)


class MalformedInputTests(FlowCase):
    """Fixed review checks a-d for every entry: no exception, never a pass."""
    BAD = [None, True, False, "1", "", NAN, INF, -INF, 10 ** 10000, -1, [], {}, [1], {"a": 1}]

    def test_api_bodies(self):
        fid = self.flow()
        for v in self.BAD:
            for body in ({"kind": v}, {"kind": "note", "note": v}, {"kind": "executor_report", "commit": v},
                         {"kind": "review_result", "reviewer": v, "verdict": "PASS", "commit": C1},
                         {"kind": "review_result", "reviewer": 0, "verdict": v, "commit": C1}):
                if "note" in body and isinstance(v, str):
                    continue  # any string up to the limit is a valid note
                try:
                    flows.append_event(fid, body)
                except ValueError:
                    pass
                else:
                    self.fail(f"accepted {str(body)[:60]}")
            for entry in (lambda: flows.append_event(fid, v), lambda: flows.set_roles(fid, v),
                          lambda: flows.set_roles(fid, {"roles": v}),
                          lambda: flows.create_flow(v, lambda t: True),
                          lambda: flows.create_flow({"task_id": v, "roles": roles()}, lambda t: False)):
                with self.assertRaises((ValueError, KeyError)):
                    entry()
            with self.assertRaises(KeyError):
                flows.get_flow(v if isinstance(v, str) else "x")

    def test_stored_values(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        good = flows.get_flow(fid)
        self.assertIsNone(flows._entry_problem(fid, good))
        paths = [("created_at",), ("task_id",), ("roles",), ("events",), ("events", 0, "at"), ("events", 0, "seq"),
                 ("events", 0, "kind"), ("events", 0, "source"), ("events", 0, "note"), ("events", 0, "commit"),
                 ("roles", "executor", "family"), ("roles", "executor", "workdir"), ("roles", "reviewers"),
                 ("roles", "planner", "model"), ("roles", "executor", "session_id")]
        valid = {("events", 0, "note"): lambda v: isinstance(v, str),          # any string is a note
                 ("events",): lambda v: v == [],                                 # no events is valid
                 ("task_id",): lambda v: v == "1",                               # "1" is a valid task id
                 ("roles", "planner", "model"): lambda v: v == "1"}              # and a valid model name
        for path in paths:
            for v in self.BAD:
                if valid.get(path, lambda v: False)(v):
                    continue
                broken = json.loads(json.dumps(good))
                target = broken
                for k in path[:-1]:
                    target = target[k]
                target[path[-1]] = v if not (isinstance(v, int) and not isinstance(v, bool) and v > 10 ** 100) else 10 ** 400
                with self.subTest(path=path, v=type(v).__name__):
                    self.assertIsNotNone(flows._entry_problem(fid, broken))

    def test_derive_with_unreadable_or_odd_heads(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        flow = flows.get_flow(fid)
        for head in ({}, {"commit": None, "error": "x"}, {"commit": 5}, {"commit": C1.upper()}, {"commit": "a" * 39},
                     None):
            with self.subTest(head=head):
                d = flows.derive(flow, lambda wd, h=head: h)
                self.assertNotEqual(d["phase"]["key"], "awaiting_merge")

    def test_events_time_never_goes_back_even_if_the_clock_does(self):
        fid = self.flow()
        self.add(fid, "note")
        first = flows.get_flow(fid)["events"][0]["at"]
        with mock.patch("vbear.flows.time.time", return_value=first - 1000):
            self.add(fid, "note")
        events = flows.get_flow(fid)["events"]
        self.assertGreaterEqual(events[1]["at"], events[0]["at"])
        with mock.patch("vbear.flows.time.time", return_value=NAN):
            with self.assertRaises(StoreError):
                self.add(fid, "note")


class LiveCachedTests(FlowCase):
    """Flows decorate themselves with live state from the cache only: a live
    build calls the runtime, which may start its daemon (Codex S1 #1)."""

    def test_never_builds_and_never_waits(self):
        from vbear.index import Store
        store = Store(runtime=mock.Mock())
        with mock.patch.object(store, "_build_live") as build:
            self.assertIsNone(store.live_cached())
            built = {"sessions": [], "panes": []}
            with store._live_cond:
                store._live, store._live_at = built, 0.0      # stale on purpose
            self.assertIs(store.live_cached(), built)
            build.assert_not_called()
        store.runtime.assert_not_called()
        self.assertEqual(store.runtime.method_calls, [])


SID = "n-0123456789ab"


def live_view(age, status="working", available=True, now=1_800_000_000.0, **extra):
    return {"generated_at": now - age, "runtime": {"available": available},
            "sessions": [{"terminal_id": SID, "status": status, "activity": {"reason": "標題顯示工作中"}}],
            "panes": [{"pane_id": SID}], **extra}


class LiveFreshnessTests(unittest.TestCase):
    """Codex S1 r2: a cached live view is never shown as the current state
    unless it is fresh; its time gets checks a-d like any other."""
    NOW = 1_800_000_000.0

    def ex(self, live, now=...):
        return flows.executor_live(SID, live, self.NOW if now is ... else now)

    def test_fresh_view_shows_the_state_and_its_age(self):
        r = self.ex(live_view(3))
        self.assertEqual((r["state"], r["label"], r["freshness"]["state"], r["freshness"]["age_s"]),
                         ("working", "工作中", "fresh", 3))

    def test_stale_view_is_not_shown_as_current(self):
        r = self.ex(live_view(flows.LIVE_STALE_S + 1))
        self.assertEqual((r["state"], r["label"]), ("stale", "即時狀態已過期"))
        self.assertIn("當時是「工作中」", r["reason"])
        self.assertEqual(self.ex(live_view(flows.LIVE_STALE_S))["state"], "working")   # the limit itself is fresh

    def test_staleness_is_judged_on_the_exact_age(self):
        # Codex S1 r3 #1: truncating first let 30.1-30.9 s pass as fresh.
        for age, state in ((29.9, "fresh"), (30.0, "fresh"), (30.1, "stale"), (30.9, "stale"), (31.0, "stale")):
            with self.subTest(age=age):
                fr = flows.live_freshness(live_view(age, now=self.NOW), self.NOW)
                self.assertEqual(fr["state"], state)
                self.assertEqual(fr["age_s"], int(age))                 # shown in whole seconds
                self.assertEqual(self.ex(live_view(age))["state"], "working" if state == "fresh" else "stale")

    def test_no_view_yet(self):
        self.assertEqual(self.ex(None)["label"], "即時狀態未載入")

    def test_unbound_executor_needs_no_view(self):
        self.assertEqual(flows.executor_live(None, None, self.NOW)["state"], "unbound")

    def test_bad_generated_at_is_never_current(self):
        for bad in (NAN, INF, -INF, 10 ** 400, True, False, "1800000000", None, -1, 0, 1e12, [], {}):
            with self.subTest(bad=repr(bad)[:20]):
                r = self.ex({**live_view(0), "generated_at": bad})
                self.assertEqual(r["freshness"]["state"], "invalid")
                self.assertEqual(r["label"], "即時狀態時間不明")

    def test_bad_now_is_never_current(self):
        for bad in (NAN, INF, None, True):
            with self.subTest(bad=bad):
                self.assertEqual(self.ex(live_view(0), now=bad)["freshness"]["state"], "invalid")

    def test_future_time_beyond_the_skew_allowance_is_invalid(self):
        from vbear.activity import CLOCK_SKEW_S
        self.assertEqual(self.ex(live_view(-(CLOCK_SKEW_S + 1)))["freshness"]["state"], "invalid")
        within = self.ex(live_view(-1))          # a clock a second behind reads as age 0
        self.assertEqual((within["freshness"]["state"], within["freshness"]["age_s"]), ("fresh", 0))

    def test_runtime_down_is_not_a_missing_session(self):
        r = self.ex(live_view(1, available=False))
        self.assertEqual((r["state"], r["label"]), ("unknown", "runtime 未連線"))

    def test_runtime_state_not_proven_is_unknown_not_down(self):
        # Codex S1 r3 #2: only an explicit False shows 「runtime 未連線」.
        for runtime in ({}, {"available": None}, {"available": 1}, {"available": "false"}, {"available": 0},
                        None, "up", [True]):
            with self.subTest(runtime=runtime):
                r = self.ex({**live_view(1), "runtime": runtime})
                self.assertEqual((r["state"], r["label"]), ("unknown", "runtime 狀態不明"))
        view = live_view(1)
        del view["runtime"]
        self.assertEqual(self.ex(view)["label"], "runtime 狀態不明")

    def test_an_executor_with_no_terminal_says_so_in_screen_words(self):
        r = flows.executor_live("", live_view(1), self.NOW)
        self.assertEqual((r["state"], r["label"]), ("unbound", "尚未綁定終端"))
        self.assertNotIn("session", r["label"] + r["reason"])
        gone = self.ex({**live_view(1), "sessions": [], "panes": []})
        self.assertNotIn("session", gone["label"] + gone["reason"])

    def test_other_session_states(self):
        self.assertEqual(self.ex({**live_view(1), "sessions": []})["label"], "狀態未知")          # a plain shell pane
        self.assertEqual(self.ex({**live_view(1), "sessions": [], "panes": []})["label"], "找不到這個終端")
        self.assertEqual(self.ex(live_view(1, status="needs-input"))["label"], "需要你處理")

    def test_malformed_view_parts_are_tolerated(self):
        for extra in ({"sessions": "x"}, {"sessions": [1, None]}, {"panes": {"a": 1}}, {"runtime": "up"},
                      {"sessions": [{"terminal_id": SID, "status": "rm -rf"}]},
                      {"sessions": [{"terminal_id": SID, "status": "working", "activity": {"reason": 5}}]}):
            with self.subTest(extra=extra):
                r = self.ex(live_view(1, **extra))
                self.assertIn(r["label"], {"狀態未知", "找不到這個終端", "runtime 狀態不明", "工作中"})
                self.assertIsInstance(r["reason"], str)


class FlowApiTests(unittest.TestCase):
    """The HTTP surface: needs the access token, rejects bad input, adds no
    execution capability (only GET /api/flows[/id] and three POST routes)."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from vbear.server import Console, make_handler
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"VBEAR_HOME": cls.tmp.name, "VBEAR_RUNTIME_AUTOSTART": "0"})
        cls.env.start()
        # Like the other server tests: no scan sources, no usage scan, so the
        # live view built in the background stays small and never reads HOME.
        from vbear import config as cfg
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for src in conf["sources"]:
            src["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        cls.port = cls.httpd.server_address[1]
        cls.console = Console(cls.port)
        cls.token = cls.console.auth_token
        cls.httpd.RequestHandlerClass = make_handler(cls.console)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.env.stop()
        cls.tmp.cleanup()

    def call(self, path, method="GET", body=None, token=True):
        import urllib.error
        import urllib.request
        h = {"X-VBear": "1", "Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {self.token}"
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"null")
            e.close()
            return e.code, data

    def test_flow_routes_never_build_the_live_view(self):
        tid = tasks.save_task(None, {"title": "不觸發即時建置"})["id"]
        with mock.patch.object(self.console.store, "_build_live") as build, \
                mock.patch.object(self.console.store, "live", side_effect=AssertionError("live() called")):
            st, r = self.call("/api/flows", "POST", {"task_id": tid, "roles": roles()})
            self.assertEqual(st, 200, r)
            fid = r["flow"]["id"]
            self.assertEqual(self.call(f"/api/flows/{fid}/events", "POST", {"kind": "note"})[0], 200)
            self.assertEqual(self.call(f"/api/flows/{fid}/roles", "POST", {"roles": roles()})[0], 200)
            self.assertEqual(self.call(f"/api/flows/{fid}")[0], 200)
            self.assertEqual(self.call("/api/flows")[0], 200)
            build.assert_not_called()

    def test_the_api_marks_a_stale_live_view(self):
        tid = tasks.save_task(None, {"title": "過期即時狀態"})["id"]
        r = roles()
        r["executor"]["session_id"] = SID
        fid = self.call("/api/flows", "POST", {"task_id": tid, "roles": r})[1]["flow"]["id"]
        store = self.console.store
        self.addCleanup(setattr, store, "_live", store._live)
        store._live = live_view(flows.LIVE_STALE_S + 60, now=time.time())
        ex = self.call(f"/api/flows/{fid}")[1]["flow"]["executor_live"]
        self.assertEqual((ex["state"], ex["freshness"]["state"]), ("stale", "stale"))
        store._live = live_view(2, now=time.time())
        ex = self.call(f"/api/flows/{fid}")[1]["flow"]["executor_live"]
        self.assertEqual((ex["state"], ex["freshness"]["state"]), ("working", "fresh"))

    def test_token_required(self):
        self.assertEqual(self.call("/api/flows", token=False)[0], 401)
        self.assertEqual(self.call("/api/flows", "POST", {"task_id": "x", "roles": {}}, token=False)[0], 401)

    def test_create_record_and_read(self):
        tid = tasks.save_task(None, {"title": "API 任務"})["id"]   # the tasks API is not under test here
        st, r = self.call("/api/flows", "POST", {"task_id": tid, "roles": roles()})
        self.assertEqual(st, 200, r)
        fid = r["flow"]["id"]
        self.assertEqual(r["flow"]["phase"]["key"], "planning")
        st, r = self.call(f"/api/flows/{fid}/events", "POST", {"kind": "plan_submitted", "note": "請核准"})
        self.assertEqual((st, r["flow"]["phase"]["key"]), (200, "awaiting_approval"))
        self.assertEqual(r["flow"]["events"][0]["source_label"], flows.MANUAL_LABEL)
        st, r = self.call("/api/flows")
        self.assertEqual(st, 200)
        self.assertTrue(r["flows"][0]["attention"])
        self.assertEqual({f["key"] for f in r["families"]}, set(flows.FAMILIES))
        st, r = self.call(f"/api/flows/{fid}/events", "POST", {"kind": "run_tests"})
        self.assertEqual(st, 400)
        self.assertEqual(self.call(f"/api/flows/{fid}/launch", "POST", {})[0], 404)   # no such capability
        self.assertEqual(self.call("/api/flows/flow-ffffffffffff")[0], 404)
        self.assertEqual(self.call("/api/flows/../tasks")[0], 404)


if __name__ == "__main__":
    unittest.main()
