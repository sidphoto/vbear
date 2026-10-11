"""Keeping and deleting a flow's data (design 9, S2c-5) through the console
and a real runtime daemon, with the synthetic Claude and Codex of the other
flow API tests. No model is called."""

import json
import os
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_flow_review_api import ReviewApiCase
from vbear import flows, tasks
from vbear.api_error import ApiError
from vbear.runtime import agent_sessions, flow_data, pipeline_store, quota, review_store


class StorageCase(ReviewApiCase):
    def storage(self):
        st, r = self.call("/api/flows/storage")
        self.assertEqual(st, 200, r)
        return r

    def mine(self, r=None):
        return next(x for x in (r or self.storage())["flows"] if x["flow_id"] == self.fid)

    def delete(self, body="__self__", fid=None):
        body = {"flow_id": self.fid} if body == "__self__" else body
        return self.call(f"/api/flows/{fid or self.fid}/delete", "POST", body)

    def end_executor(self):
        st, r = self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": self.launch})
        self.assertEqual(st, 200, r)
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["manifest_state"] == "ended", msg="session ended")

    def dirs(self):
        base = self.base
        return {"sessions": sorted(os.listdir(base / "sessions")) if (base / "sessions").exists() else [],
                "reviews": sorted(os.listdir(base / "reviews")) if (base / "reviews").exists() else [],
                "pipeline": (base / "pipelines" / self.tid).exists(),
                "hold": (base / "holds" / self.fid).exists()}

    def flow_with_a_review(self):
        self.start_executor()
        self.commit_work()
        self.turn()
        job, _ = self.run_review()
        return job


class UsageTests(StorageCase):
    def test_a_flow_is_listed_with_its_size_and_why_it_cannot_go_while_a_session_runs(self):
        self.flow_with_a_review()
        r = self.storage()
        self.assertEqual((r["limit_bytes"], r["problem"]), (quota.HARD_LIMIT, ""))
        mine = self.mine(r)
        self.assertEqual((mine["sessions"], mine["reviews"], mine["has_data"]), (1, 1, True))
        self.assertGreater(mine["bytes"], 0)
        self.assertLessEqual(mine["bytes"], r["used_bytes"])
        self.assertFalse(mine["deletable"])
        self.assertTrue(any("仍在執行" in x for x in mine["reasons"]), mine["reasons"])

    def test_after_the_session_ends_it_is_deletable_and_the_sizes_add_up(self):
        self.flow_with_a_review()
        self.end_executor()
        r = self.storage()
        mine = self.mine(r)
        self.assertTrue(mine["deletable"], mine)
        self.assertEqual(mine["reasons"], [])
        self.assertEqual(mine["bytes"], r["used_bytes"])           # this flow is all there is

    def test_a_damaged_manifest_is_listed_with_the_reason_and_no_size(self):
        self.flow_with_a_review()
        self.end_executor()
        (self.base / "sessions" / self.launch / "manifest.json").write_text("{not json")
        mine = self.mine()
        self.assertIsNone(mine["bytes"])
        self.assertFalse(mine["deletable"])
        self.assertTrue(mine["reasons"])

    def test_a_review_waiting_for_a_person_blocks_deletion(self):
        job = self.flow_with_a_review()
        self.end_executor()
        path = self.base / "reviews" / job / "manifest.json"                 # as a daemon that kept it would have
        m = json.loads(path.read_text())
        m.update(state="manual_review", outcome="manual_review", retained_reason="test", retained_at=time.time())
        path.write_text(json.dumps(m))
        mine = self.mine()
        self.assertFalse(mine["deletable"])
        self.assertTrue(any("manual_review" in x for x in mine["reasons"]), mine["reasons"])


class DeleteTests(StorageCase):
    def test_a_running_session_refuses_and_nothing_is_touched(self):
        self.flow_with_a_review()
        before = self.dirs()
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertIn("仍在執行", r["error"])
        self.assertEqual(self.dirs(), before)
        self.assertIsNotNone(flows.get_flow(self.fid))

    def test_the_request_has_to_name_the_flow(self):
        self.flow_with_a_review()
        self.end_executor()
        for body in ({}, {"flow_id": "flow-000000000000"}, {"flow_id": self.fid, "x": 1}, {"flow_id": 5}):
            st, r = self.delete(body)
            self.assertEqual((st, r["code"]), (400, "bad_request"), body)
        self.assertTrue(self.dirs()["sessions"])
        st, r = self.delete(fid="flow-000000000000", body={"flow_id": "flow-000000000000"})
        self.assertEqual(st, 404)

    def test_everything_of_the_flow_goes_the_record_goes_and_the_room_comes_back(self):
        job = self.flow_with_a_review()
        self.end_executor()
        used = self.storage()["used_bytes"]
        self.assertGreater(used, 0)
        st, r = self.delete()
        self.assertEqual(st, 200, r)
        self.assertEqual((r["deleted"], r["bytes"]), (self.fid, used))
        self.assertEqual(r["removed"]["sessions"], [self.launch])
        self.assertEqual(r["removed"]["reviews"], [job])
        self.assertTrue(r["removed"]["pipeline"])
        self.assertEqual(self.dirs(), {"sessions": [], "reviews": [], "pipeline": False, "hold": False})
        with self.assertRaises(KeyError):
            flows.get_flow(self.fid)
        st, _ = self.call(f"/api/flows/{self.fid}")
        self.assertEqual(st, 404)
        self.assertEqual(self.storage()["used_bytes"], 0)
        self.assertEqual(self.storage()["flows"], [])
        self.assertEqual(self.dm._ledger.used, 0)                  # the daemon's ledger was rebuilt from a scan

    def test_a_stopped_flow_is_refused_until_it_is_continued(self):
        self.flow_with_a_review()
        self.end_executor()
        st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
        self.assertEqual(st, 200, r)
        self.assertTrue(self.dirs()["hold"])
        mine = self.mine()
        self.assertFalse(mine["deletable"])
        self.assertTrue(any("已停止" in x for x in mine["reasons"]), mine["reasons"])
        before = self.dirs()
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertIn("請先按「繼續」", r["error"])
        self.assertEqual(self.dirs(), before)                       # nothing moved
        st, r = self.call(f"/api/flows/{self.fid}/continue", "POST", {})
        self.assertEqual(st, 200, r)
        st, r = self.delete()
        self.assertEqual(st, 200, r)
        self.assertFalse(self.dirs()["hold"])

    def test_an_unreleased_failure_is_refused_even_when_nothing_runs(self):
        self.start_executor("exit")                                  # the turn dies without a result
        st, pre = self.call(f"/api/flows/{self.fid}/dispatch-preview", "POST", {"launch_id": self.launch, "text": "x"})
        self.assertEqual(st, 200, pre)
        st, r = self.call(f"/api/flows/{self.fid}/dispatch", "POST", {"preview_id": pre["preview_id"]})
        self.wait_for(lambda: self.executor_status()["hold"]["held"], msg="the failure to hold the flow")
        self.call(f"/api/flows/{self.fid}/executor/close", "POST", {"launch_id": self.launch})
        self.wait_for(lambda: self.executor_status()["sessions"][-1]["manifest_state"] in ("ended", "manual_review"),
                      msg="closed")
        self.assertTrue(self.executor_status()["unresolved_failure"])
        before = self.dirs()
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"), r)
        self.assertTrue("已停止" in r["error"] or "manual_review" in r["error"] or "尚未解除" in r["error"], r["error"])
        self.assertEqual(self.dirs(), before)

    def test_a_process_group_that_is_not_proven_finished_refuses(self):
        self.flow_with_a_review()
        self.end_executor()
        self.dm._held_leaders.append({"proc": None, "pid": 0, "launch_id": self.launch})
        try:
            st, r = self.delete()
        finally:
            self.dm._held_leaders[:] = [h for h in self.dm._held_leaders if h["launch_id"] != self.launch]
        self.assertEqual((st, r["code"]), (409, "refused"), r)               # the daemon's own refusal
        self.assertIn("尚未證明已結束", r["error"])
        self.assertTrue(self.dirs()["sessions"])

    def test_a_session_whose_journal_is_gone_cannot_be_judged_and_is_left_to_a_person(self):
        # an unreadable journal means the flow's failures cannot be told: refused, nothing moved
        self.flow_with_a_review()
        self.end_executor()
        (self.base / "sessions" / self.launch / "journal.jsonl").unlink()
        before = self.dirs()
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertIn("無法確認失敗是否都已處理", r["error"])
        self.assertEqual(self.dirs(), before)

    def test_a_flow_whose_record_removal_fails_is_deleted_by_asking_again(self):
        self.flow_with_a_review()
        self.end_executor()
        with mock.patch.object(flows, "delete_flow", side_effect=OSError("disk")):
            st, r = self.delete()
        self.assertEqual((st, r["code"]), (500, "internal"))
        self.assertIn("再按一次", r["error"])
        self.assertEqual(self.dirs()["sessions"], [])             # the data went
        st, r = self.delete()
        self.assertEqual(st, 200, r)
        with self.assertRaises(KeyError):
            flows.get_flow(self.fid)

    def test_a_link_inside_the_flows_data_is_removed_as_a_link_and_never_followed(self):
        self.flow_with_a_review()
        self.end_executor()
        outside = self.tmp / "outside"
        outside.mkdir()
        keep = outside / "keep.txt"
        keep.write_text("mine")
        os.symlink(outside, self.base / "sessions" / self.launch / "evil")
        st, r = self.delete()
        # a link is something the scan and the plan refuse: the flow is not touched
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertTrue(keep.exists())
        self.assertTrue(self.dirs()["sessions"])

    def test_a_flow_that_never_started_needs_no_daemon_and_other_flows_are_left_alone(self):
        t2 = tasks.save_task(None, {"title": "second"})["id"]
        other = flows.create_flow({"task_id": t2, "roles": flows.get_flow(self.fid)["roles"]}, lambda t: True)["id"]
        self.flow_with_a_review()
        self.end_executor()
        before = self.dirs()
        with mock.patch("vbear.flow_storage.daemon_client.call", side_effect=AssertionError("no daemon call")):
            st, r = self.call(f"/api/flows/{other}/delete", "POST", {"flow_id": other})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["bytes"], 0)
        self.assertIsNone(r["removed"])
        self.assertEqual(self.dirs(), before)
        self.assertIsNotNone(flows.get_flow(self.fid))
        with self.assertRaises(KeyError):
            flows.get_flow(other)

    def test_two_flows_cannot_share_a_task_and_a_shared_one_is_refused(self):
        self.flow_with_a_review()
        self.end_executor()
        with self.assertRaises(ValueError) as cm:                  # creation already says one task, one flow
            flows.create_flow({"task_id": self.tid, "roles": flows.get_flow(self.fid)["roles"]}, lambda t: True)
        self.assertIn("已經有流程", str(cm.exception))
        everyone = {f["id"]: f for f in flows.list_flows()}
        everyone["flow-ffffffffffff"] = {"id": "flow-ffffffffffff", "task_id": self.tid}   # a damaged store
        with self.assertRaises(flow_data.FlowDataRefused) as cm:
            flow_data.plan(self.base, self.fid, self.tid, flows=everyone)
        self.assertIn("也使用這個任務的資料夾", str(cm.exception))

    def test_a_task_directory_without_a_start_record_is_not_guessed_to_be_this_flows(self):
        # Codex S2c-5 review: pipelines/<task> with a data file and no start record was deleted
        shared = self.base / "pipelines" / "shared-task"
        (shared / "dispatches").mkdir(parents=True)
        (shared / "data.txt").write_text("someone else's")
        for d in (shared.parent, shared, shared / "dispatches"):
            os.chmod(d, 0o700)
        with self.assertRaises(flow_data.FlowDataRefused) as cm:
            flow_data.plan(self.base, self.fid, "shared-task")
        self.assertIn("沒有開始紀錄", str(cm.exception))
        self.assertTrue((shared / "data.txt").exists())
        (shared / "data.txt").unlink()                              # only empty scaffolding: nothing to lose
        pl = flow_data.plan(self.base, self.fid, "shared-task")
        self.assertEqual(pl.pipeline_dir, "shared-task")

    def test_a_start_record_naming_another_flow_refuses(self):
        self.flow_with_a_review()
        self.end_executor()
        rec = self.base / "pipelines" / self.tid / "started.json"
        d = json.loads(rec.read_text())
        d["pipeline_id"] = "flow-ffffffffffff"
        rec.write_text(json.dumps(d))
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertTrue(self.dirs()["sessions"])

    def test_a_review_without_the_flows_own_record_of_it_is_not_proven(self):
        job = self.flow_with_a_review()
        self.end_executor()
        link = self.base / "pipelines" / self.tid / "reviews" / "1" / "job.json"
        d = json.loads(link.read_text())
        d["job_id"] = "r-" + "0" * 16                                # the flow's record names a different job
        link.write_text(json.dumps(d))
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertIn("對不上", r["error"])
        self.assertTrue((self.base / "reviews" / job).exists())

    def test_a_session_directory_that_is_not_the_one_its_manifest_recorded_is_not_proven(self):
        self.flow_with_a_review()
        self.end_executor()
        m = self.base / "sessions" / self.launch / "manifest.json"
        d = json.loads(m.read_text())
        d["launch_dir"]["inode"] += 1
        m.write_text(json.dumps(d))
        st, r = self.delete()
        self.assertEqual((st, r["code"]), (409, "not_deletable"))
        self.assertTrue((self.base / "sessions" / self.launch).exists())

    def test_a_deletion_begun_stops_new_work_and_is_finished_by_asking_again(self):
        job = self.flow_with_a_review()
        self.end_executor()
        tomb = self.base / "deleting" / self.fid
        tomb.mkdir(parents=True, mode=0o700)                       # as left by a crash right after it was begun
        os.chmod(tomb.parent, 0o700)
        s = self.executor_status()
        self.assertTrue(s["hold"]["held"])
        self.assertIn("正在刪除", s["hold"]["reason"])
        st, r = self.call(f"/api/flows/{self.fid}/executor", "POST", {})
        self.assertNotEqual(st, 200, r)                            # nothing new starts in a flow being deleted
        st, r = self.call(f"/api/flows/{self.fid}/review", "POST", {})
        self.assertNotEqual(st, 200, r)
        mine = self.mine()
        self.assertTrue(mine["deleting"] and mine["deletable"], mine)
        st, r = self.delete()
        self.assertEqual(st, 200, r)
        self.assertFalse((self.base / "deleting").exists())
        self.assertEqual(self.dirs(), {"sessions": [], "reviews": [], "pipeline": False, "hold": False})


class CrashMatrixTests(StorageCase):
    """Every point where a deletion can stop (design 9; Codex S2c-5 review):
    before and after each rename, unlink, rmdir and mkdir it performs. At each
    one: nothing another flow's accounting reads is damaged, and asking again
    finishes the deletion. The data is a real flow's (session, review, task
    directory) copied aside, so no daemon is needed for each of the runs."""

    def copy_state(self, name):
        dst = self.tmp / name
        dst.mkdir(mode=0o700)
        for sub in ("sessions", "reviews", "pipelines", "holds"):
            if (self.base / sub).exists():
                shutil.copytree(self.base / sub, dst / sub, symlinks=True)
        for m in (dst / "sessions").glob("l-*/manifest.json"):          # the copy's directories are new inodes
            d = json.loads(m.read_text())
            d["launch_dir"] = {**d["launch_dir"], "path": str(m.parent), "inode": m.parent.stat().st_ino}
            m.write_text(json.dumps(d))
        return dst

    def others_ok(self, base):
        from vbear.runtime import stream_flow
        stream_flow.flow_sessions(base, "flow-ffffffffffff", started=False)      # unknown entries would refuse
        stream_flow.flow_reviews(base, "flow-ffffffffffff", "some-other-task")
        quota.scan(base)
        for n in os.listdir(base / "sessions") if (base / "sessions").exists() else []:
            self.assertRegex(n, r"^l-[0-9a-f]{16}\Z")
        for n in os.listdir(base / "reviews") if (base / "reviews").exists() else []:
            self.assertRegex(n, r"^r-[0-9a-f]{16}\Z")

    def gone(self, base):
        return {"sessions": os.listdir(base / "sessions") if (base / "sessions").exists() else [],
                "reviews": os.listdir(base / "reviews") if (base / "reviews").exists() else [],
                "pipeline": (base / "pipelines" / self.tid).exists(),
                "tomb": bool(os.listdir(base / "deleting" / self.fid)) if (base / "deleting" / self.fid).exists() else False}

    def disk_bytes(self, base):
        """Every regular file under the four data roots, summed independently of quota.scan."""
        total = 0
        for root in ("sessions", "reviews", "pipelines", "deleting"):
            for dirpath, _dirs, files in os.walk(base / root):
                total += sum(os.lstat(os.path.join(dirpath, f)).st_size for f in files)
        return total

    def test_the_quota_scan_counts_what_waits_in_the_deletion_area(self):
        self.flow_with_a_review()
        self.end_executor()
        base = self.copy_state("half")
        before = quota.scan(base)
        self.assertEqual(before, self.disk_bytes(base))
        pl = flow_data.plan(base, self.fid, self.tid)
        real_purge = flow_data._purge

        def stop_before_purge(*a, **kw):                      # everything moved, nothing purged yet
            raise flow_data.FlowDataRefused("stopped here")
        with mock.patch.object(flow_data, "_purge", stop_before_purge):
            with self.assertRaises(flow_data.FlowDataRefused):
                flow_data.remove(base, pl)
        self.assertEqual(os.listdir(base / "sessions"), [])
        self.assertTrue((base / "deleting" / self.fid / "sessions").exists())
        self.assertEqual(quota.scan(base), before)            # the room is still taken, not given away
        self.assertEqual(quota.scan(base), self.disk_bytes(base))
        ledger = quota.Ledger(base)
        self.assertTrue(ledger.rebuild({}))
        self.assertEqual(ledger.used, before)
        flow_data.remove(base, flow_data.plan(base, self.fid, self.tid))
        self.assertEqual(quota.scan(base), 0)

    def test_every_stopping_point_is_finished_by_asking_again(self):
        self.flow_with_a_review()
        self.end_executor()
        names = ("rename", "unlink", "rmdir", "mkdir")
        # how many such operations a whole deletion makes
        probe = self.copy_state("probe")
        calls = []
        real = {n: getattr(os, n) for n in names}

        def counting(n):
            def f(*a, **kw):
                calls.append(n)
                return real[n](*a, **kw)
            return f
        pl = flow_data.plan(probe, self.fid, self.tid)
        self.assertEqual(flow_data.blockers(pl), [])
        with mock.patch.multiple(flow_data.os, **{n: counting(n) for n in names}):
            flow_data.remove(probe, pl)
        total = len(calls)
        self.assertGreater(total, 10)
        self.assertEqual(self.gone(probe), {"sessions": [], "reviews": [], "pipeline": False, "tomb": False})
        shutil.rmtree(probe)
        # the stop is "before the k-th operation"; k = total + 1 is the whole run
        for k in range(0, total):
            with self.subTest(stop_before_operation=k + 1, of=total):
                base = self.copy_state(f"k{k}")
                pl = flow_data.plan(base, self.fid, self.tid)
                counter = {"n": 0}

                def crashing(name):
                    def f(*a, **kw):
                        if counter["n"] >= k:
                            raise OSError(5, "simulated crash")
                        counter["n"] += 1
                        return real[name](*a, **kw)
                    return f
                with mock.patch.multiple(flow_data.os, **{n: crashing(n) for n in names}):
                    with self.assertRaises((flow_data.FlowDataRefused, OSError)):
                        flow_data.remove(base, pl)
                # after the stop: what other flows read is intact; a begun deletion counts as stopped
                self.others_ok(base)
                self.assertEqual(quota.scan(base), self.disk_bytes(base))   # the deletion area is counted
                if (base / "deleting" / self.fid).exists():
                    self.assertTrue(pipeline_store.is_held(base, self.fid))
                    self.assertTrue(pipeline_store.hold_info(base, self.fid)["held"])
                # asking again: re-planned from what is left, no manifest of a removed item needed
                pl2 = flow_data.plan(base, self.fid, self.tid)
                self.assertEqual(flow_data.blockers(pl2), [], k)
                flow_data.remove(base, pl2)
                self.assertEqual(self.gone(base), {"sessions": [], "reviews": [], "pipeline": False, "tomb": False})
                self.others_ok(base)
                # the marker stays until the console says the record is gone: nothing new can start meanwhile
                self.assertTrue(pipeline_store.is_held(base, self.fid))
                self.assertTrue(flow_data.finish(base, self.fid))
                self.assertFalse(pipeline_store.is_held(base, self.fid))
                self.assertFalse((base / "deleting").exists())
                shutil.rmtree(base)


class QuotaHintTests(unittest.TestCase):
    def test_a_full_quota_answer_carries_the_storage_hint(self):
        e = ApiError(409, "quota", "VBear 保存的資料已接近上限（4 GiB），請刪除不再需要的舊流程後再試")
        self.assertTrue(e.extra.get("storage"))
        self.assertNotIn("storage", ApiError(409, "x", "別的原因").extra)


class PurgeUnitTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbfd-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.parent = self.tmp / "p"
        self.parent.mkdir(mode=0o700)
        self.pfd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.pfd)
        self.dev = os.fstat(self.pfd).st_dev

    def tree(self):
        d = self.parent / "x"
        d.mkdir(mode=0o700)
        (d / "manifest.json").write_text("{}")
        (d / "sub").mkdir(mode=0o700)
        (d / "sub" / "f").write_text("b")
        return d

    def test_a_tree_is_purged_and_a_missing_one_is_not_an_error(self):
        d = self.tree()
        self.assertTrue(flow_data._purge(self.pfd, "x", self.dev, [100]))
        self.assertFalse(d.exists())
        self.assertFalse(flow_data._purge(self.pfd, "x", self.dev, [100]))

    def test_a_link_is_removed_as_a_link_never_followed(self):
        d = self.tree()
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "keep").write_text("k")
        os.symlink(outside, d / "evil")
        flow_data._purge(self.pfd, "x", self.dev, [100])
        self.assertTrue((outside / "keep").exists())
        self.assertFalse(d.exists())

    def test_a_special_file_refuses_and_nothing_else_is_assumed(self):
        d = self.tree()
        os.mkfifo(d / "pipe")
        with self.assertRaises(flow_data.FlowDataRefused):
            flow_data._purge(self.pfd, "x", self.dev, [100])
        self.assertTrue(d.exists())

    def test_another_device_is_refused_before_it_is_entered(self):
        d = self.tree()
        with self.assertRaises(flow_data.FlowDataRefused) as cm:
            flow_data._purge(self.pfd, "x", self.dev + 1, [100])        # as if x were a mount point
        self.assertIn("掛載點", str(cm.exception))
        self.assertTrue((d / "sub" / "f").exists())

    def test_a_directory_replaced_between_looking_and_opening_is_refused(self):
        d = self.tree()
        real = os.open
        swapped = []

        def open_(path, flags, *a, **kw):
            if path == "x" and not swapped:                              # the swap happens after the lstat, before the open
                swapped.append(1)
                shutil.rmtree(d)
                d.mkdir(mode=0o700)
                (d / "other").write_text("new")
            return real(path, flags, *a, **kw)
        with mock.patch.object(flow_data.os, "open", open_):
            with self.assertRaises(flow_data.FlowDataRefused) as cm:
                flow_data._purge(self.pfd, "x", self.dev, [100])
        self.assertIn("被替換", str(cm.exception))
        self.assertTrue((d / "other").exists())

    def test_a_directory_replaced_after_it_was_emptied_is_not_removed(self):
        d = self.tree()
        real_stat = os.stat
        seen = []

        def stat_(path, *a, **kw):
            r = real_stat(path, *a, **kw)
            if path == "x" and kw.get("dir_fd") == self.pfd:
                seen.append(1)
                if len(seen) == 2:                                         # the look just before the rmdir
                    return os.stat_result((r.st_mode, r.st_ino + 1, r.st_dev, r.st_nlink, r.st_uid, r.st_gid,
                                           r.st_size, 0, 0, 0))
            return r
        with mock.patch.object(flow_data.os, "stat", stat_):
            with self.assertRaises(flow_data.FlowDataRefused) as cm:
                flow_data._purge(self.pfd, "x", self.dev, [100])
        self.assertIn("被替換", str(cm.exception))
        self.assertTrue(d.exists())

    def test_a_move_checks_the_inode_it_planned_with(self):
        d = self.tree()
        dst = self.tmp / "dst"
        dst.mkdir(mode=0o700)
        dfd = os.open(dst, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, dfd)
        with self.assertRaises(flow_data.FlowDataRefused):
            flow_data._move(self.pfd, "x", dfd, "x", self.dev, d.stat().st_ino + 1)
        self.assertTrue(d.exists())
        self.assertFalse((dst / "x").exists())
        self.assertTrue(flow_data._move(self.pfd, "x", dfd, "x", self.dev, d.stat().st_ino))
        self.assertTrue((dst / "x" / "sub" / "f").exists())
        self.assertFalse(flow_data._move(self.pfd, "x", dfd, "x", self.dev, 1))        # already gone: not an error


if __name__ == "__main__":
    unittest.main()
