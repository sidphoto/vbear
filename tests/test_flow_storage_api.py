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
from vbear.runtime import flow_data, quota, review_store, agent_sessions


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

    def test_a_stopped_flows_marker_goes_with_it(self):
        self.flow_with_a_review()
        self.end_executor()
        st, r = self.call(f"/api/flows/{self.fid}/hold", "POST", {})
        self.assertEqual(st, 200, r)
        self.assertTrue(self.dirs()["hold"])
        st, r = self.delete()
        self.assertEqual(st, 200, r)
        self.assertTrue(r["removed"]["hold"])
        self.assertFalse(self.dirs()["hold"])

    def test_a_deletion_that_stopped_half_way_is_finished_by_asking_again(self):
        job = self.flow_with_a_review()
        self.end_executor()
        ldir = self.base / "sessions" / self.launch
        for p in ldir.iterdir():                                  # a crash after the files, before the manifest
            if p.name != "manifest.json":
                p.unlink() if p.is_file() else shutil.rmtree(p)
        st, r = self.delete()
        self.assertEqual(st, 200, r)
        self.assertEqual(self.dirs(), {"sessions": [], "reviews": [], "pipeline": False, "hold": False})
        self.assertEqual(r["removed"]["reviews"], [job])

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

    def test_a_task_directory_that_belongs_to_another_flow_is_not_touched(self):
        self.flow_with_a_review()
        self.end_executor()
        other = flows.create_flow({"task_id": tasks.save_task(None, {"title": "x"})["id"],
                                  "roles": flows.get_flow(self.fid)["roles"]}, lambda t: True)["id"]
        with flows.store.locked():                                 # the other flow now claims this flow's task
            data = flows.store.load()
            data[other]["task_id"] = self.tid
            flows.store.save(data)
        pl = flow_data.plan(self.base, other, self.tid)
        self.assertIsNone(pl.pipeline_dir)
        self.assertIn("另一個流程", pl.pipeline_note)
        self.assertEqual((pl.sessions, pl.reviews), ([], []))


class QuotaHintTests(unittest.TestCase):
    def test_a_full_quota_answer_carries_the_storage_hint(self):
        e = ApiError(409, "quota", "VBear 保存的資料已接近上限（4 GiB），請刪除不再需要的舊流程後再試")
        self.assertTrue(e.extra.get("storage"))
        self.assertNotIn("storage", ApiError(409, "x", "別的原因").extra)


class RemoveUnitTests(unittest.TestCase):
    def test_a_directory_is_emptied_manifest_last_and_special_files_refuse(self):
        import tempfile
        tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbfd-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, tmp, True)
        parent = tmp / "p"
        parent.mkdir(mode=0o700)
        d = parent / "x"
        d.mkdir(mode=0o700)
        (d / "manifest.json").write_text("{}")
        (d / "journal").write_text("a")
        (d / "sub").mkdir(mode=0o700)
        (d / "sub" / "f").write_text("b")
        order = []
        real = os.unlink

        def unlink(name, *a, **kw):
            order.append(name)
            return real(name, *a, **kw)
        pfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with mock.patch.object(flow_data.os, "unlink", unlink):
                self.assertTrue(flow_data._remove_dir(pfd, "x", manifest="manifest.json"))
            self.assertEqual(order[-1], "manifest.json")
            self.assertFalse(d.exists())
            self.assertFalse(flow_data._remove_dir(pfd, "x", manifest="manifest.json"))     # already gone
            d.mkdir(mode=0o700)
            os.mkfifo(d / "pipe")
            with self.assertRaises(flow_data.FlowDataRefused) as cm:
                flow_data._remove_dir(pfd, "x")
            self.assertTrue(d.exists())
            # a wrong identity is refused before anything goes
            os.unlink(d / "pipe")
            (d / "keep").write_text("k")
            with self.assertRaises(flow_data.FlowDataRefused):
                flow_data._remove_dir(pfd, "x", identity={"inode": 1, "uid": os.getuid()})
            self.assertTrue((d / "keep").exists())
        finally:
            os.close(pfd)


if __name__ == "__main__":
    unittest.main()
