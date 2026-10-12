"""How a review ends (vbear/runtime/review_finish.py): the decision from the
files left on disk, the saved record, the manifest outcome, the clean-up. No
Codex, no model; a real throwaway git repository supplies a real commit."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
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
        # the review's tokens, from the rollout's usage chain (the fixture's two responses), in the record
        a, b = rf._usage(0), rf._usage(1)
        self.assertEqual(result["usage"], {"complete": True, "counts": {f: a[f] + b[f] for f in a}})
        self.assertIsNone(result["usage_problem"])
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
        result = json.loads((self.record() / "result.json").read_text())
        self.assertFalse(result["rollout"])
        self.assertEqual((result["usage"], result["usage_problem"]), (None, "no_rollout"))   # not had, never 0
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
        rs.update_manifest(self.base, JOB, commit=other)                       # the job names a commit the work dir lacks
        out = self.finish()
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

    def test_the_message_names_what_is_under_the_scratch_instead_of_repo(self):
        # S3 real end-to-end run 5: the reviewer cloned into "toy repo", not "repo". The strictness stays; the
        # reason says what was found (names only).
        shutil.rmtree(self.scratch / "repo")
        (self.scratch / "toy repo").mkdir()
        (self.scratch / "toy repo" / "SECRET-FILE-CONTENT.txt").write_text("not a name that is shown")
        out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        reason = next(r for r in out.reasons if "detached" in r)
        self.assertIn("'toy repo'", reason)
        self.assertNotIn("SECRET-FILE-CONTENT", reason)
        self.assertLessEqual(len(reason), 256)

    def test_the_names_listing_reads_a_bounded_number_of_entries_and_lists_directories_only(self):
        from vbear.runtime import review_finish as rfin
        shutil.rmtree(self.scratch / "repo")
        for i in range(200):
            (self.scratch / f"d{i:03d}").mkdir()
        entered = []
        real = os.scandir

        class Counting:
            def __init__(self, it):
                self.it = it

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self.it.__exit__(*exc)

            def __iter__(self):
                for e in self.it:
                    entered.append(e.name)
                    yield e
        with mock.patch.object(rfin.os, "scandir", lambda p: Counting(real(p))):
            text = rfin._scratch_names(self.scratch)
        self.assertEqual(len(entered), rfin.SCRATCH_SCAN_MAX)               # it stopped reading
        self.assertIn("…以及更多", text)
        self.assertLessEqual(len(text), 200)
        # files and links are not listed, and a control character is shown as ?
        shutil.rmtree(self.scratch)
        self.scratch.mkdir()
        (self.scratch / "a file").write_text("x")
        (self.scratch / "a link").symlink_to(self.scratch)
        (self.scratch / "real\x1bdir").mkdir()
        text = rfin._scratch_names(self.scratch)
        self.assertIn("'real?dir'", text)
        self.assertNotIn("a file", text)
        self.assertNotIn("a link", text)
        self.assertNotIn("\x1b", text)


class AtomicMarkerTests(Scenario):
    def write_marker(self, data=b'{"v":1}'):
        with ps.Pipeline(self.base, TID, create=False) as p:
            fd = p.review_dir_fd(1)
        try:
            return rfn._write_new(fd, "result.json", data, str(self.record()))
        finally:
            os.close(fd)

    def test_a_partial_write_is_never_visible_at_the_formal_name(self):
        seen = []
        real_write = os.write
        with ps.Pipeline(self.base, TID, create=False) as p:
            fd = p.review_dir_fd(1)
            try:
                def partial_write(dst, data):
                    n = real_write(dst, data[:1])
                    seen.append((self.record() / "result.json").exists())
                    return n
                with mock.patch.object(os, "write", partial_write):
                    saved = rfn._write_new(fd, "result.json", b'{"v":1}', str(self.record()))
                self.assertTrue(saved.ok)
                self.assertTrue(seen)
                self.assertFalse(any(seen), "a partial result.json was visible to readers")
                self.assertEqual(p.review_result(1), {"v": 1})
            finally:
                os.close(fd)

    def test_after_file_sync_the_reader_still_sees_no_marker(self):
        seen = []
        real_sync = os.fsync
        with ps.Pipeline(self.base, TID, create=False) as p:
            fd = p.review_dir_fd(1)
            try:
                def synced(dst):
                    real_sync(dst)
                    if dst != fd:
                        seen.append(p.review_result(1))
                with mock.patch.object(os, "fsync", synced):
                    saved = rfn._write_new(fd, "result.json", b'{"v":1}', str(self.record()))
                self.assertTrue(saved.ok)
                self.assertEqual(seen, [None])
                self.assertEqual(p.review_result(1), {"v": 1})
            finally:
                os.close(fd)

    def test_publication_is_exclusive_and_the_reader_ignores_the_temp_name(self):
        real_link, real_open = os.link, os.open
        seen, opens = [], []

        def opened(name, flags, *a, **kw):
            if str(name).startswith(".result.json."):
                opens.append((flags, a[0]))
            return real_open(name, flags, *a, **kw)

        def publish(src, dst, **kw):
            tmp = self.record() / src
            seen.append((tmp.read_bytes(), tmp.stat().st_mode & 0o777))
            with ps.Pipeline(self.base, TID, create=False) as p:
                seen.append(p.review_result(1))
            self.assertEqual(self.manifest()["outcome"], "valid")
            real_link(src, dst, **kw)
            with ps.Pipeline(self.base, TID, create=False) as p:
                seen.append(p.review_result(1)["valid"])
            self.assertEqual(kw["src_dir_fd"], kw["dst_dir_fd"])
            self.assertFalse(kw["follow_symlinks"])

        with mock.patch.object(os, "link", publish), mock.patch.object(os, "open", opened):
            out = self.finish()
        self.assertTrue(out.record_complete)
        self.assertEqual(seen[0][1], 0o600)
        self.assertEqual(seen[1:], [None, True])
        flags, mode = opens[0]
        self.assertEqual(flags & (os.O_EXCL | os.O_NOFOLLOW | os.O_CREAT),
                         os.O_EXCL | os.O_NOFOLLOW | os.O_CREAT)
        self.assertEqual(mode, 0o600)
        self.assertEqual(list(self.record().glob(".result.json.*.tmp")), [])
        self.assertEqual([x["record"] for x in sfl.flow_reviews(self.base, FID, TID)], ["complete"])

    def test_existing_marker_and_racing_destination_are_never_overwritten(self):
        marker = self.record() / "result.json"
        marker.write_bytes(b"earlier marker")
        before = marker.stat().st_ino
        self.assertFalse(self.write_marker().ok)
        self.assertEqual((marker.read_bytes(), marker.stat().st_ino), (b"earlier marker", before))
        marker.unlink()
        real_link = os.link

        def competing_writer(src, dst, **kw):
            marker.write_bytes(b"concurrent marker")
            return real_link(src, dst, **kw)

        with mock.patch.object(os, "link", competing_writer):
            self.assertFalse(self.write_marker().ok)
        self.assertEqual(marker.read_bytes(), b"concurrent marker")
        self.assertEqual(list(self.record().glob(".result.json.*.tmp")), [])

    def test_an_existing_symlink_is_never_followed_or_replaced(self):
        target = self.tmp / "target"
        target.write_bytes(b"original")
        marker = self.record() / "result.json"
        marker.symlink_to(target)
        self.assertFalse(self.write_marker().ok)
        self.assertTrue(marker.is_symlink())
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(list(self.record().glob(".result.json.*.tmp")), [])

    def test_write_file_sync_link_unlink_and_directory_sync_failures_roll_back(self):
        real_write, real_sync, real_unlink = os.write, os.fsync, os.unlink
        for step in ("write", "zero_write", "file_sync", "link", "unlink", "directory_sync"):
            with self.subTest(step=step):
                calls = []

                def write(fd, data):
                    if step == "zero_write":
                        return 0
                    if calls:
                        raise OSError(5, "injected write error")
                    calls.append(fd)
                    return real_write(fd, data[:1])

                def sync(fd):
                    is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
                    if (step == "directory_sync") == is_dir:
                        raise OSError(5, "injected sync error")
                    return real_sync(fd)

                def unlink(name, **kw):
                    if not calls:
                        calls.append(name)
                        raise OSError(5, "injected unlink error")
                    return real_unlink(name, **kw)

                if step in ("write", "zero_write"):
                    patch = mock.patch.object(os, "write", write)
                elif step in ("file_sync", "directory_sync"):
                    patch = mock.patch.object(os, "fsync", sync)
                elif step == "unlink":
                    patch = mock.patch.object(os, "unlink", unlink)
                else:
                    patch = mock.patch.object(os, "link", side_effect=OSError(5, "injected link error"))
                with patch:
                    saved = self.write_marker()
                self.assertFalse(saved.ok)
                self.assertIsNone(saved.leftover)
                self.assertFalse((self.record() / "result.json").exists())
                self.assertEqual(list(self.record().glob(".result.json.*.tmp")), [])

    def test_temp_creation_failure_does_not_remove_an_existing_temp_file(self):
        tmp = self.record() / (".result.json." + "a" * 32 + ".tmp")
        tmp.write_bytes(b"previous failed write")
        with mock.patch.object(rfn.secrets, "token_hex", return_value="a" * 32):
            saved = self.write_marker()
        self.assertFalse(saved.ok)
        self.assertEqual(tmp.read_bytes(), b"previous failed write")
        self.assertFalse((self.record() / "result.json").exists())

    def test_unremovable_temp_is_reported_with_its_actual_size(self):
        with mock.patch.object(os, "link", side_effect=OSError(5, "injected link error")), \
                mock.patch.object(os, "unlink", side_effect=OSError(13, "injected cleanup error")):
            saved = self.write_marker()
        self.assertFalse(saved.ok)
        tmp, = self.record().glob(".result.json.*.tmp")
        self.assertEqual((saved.leftover, saved.leftover_bytes), (str(tmp), tmp.stat().st_size))
        self.assertIn(str(tmp), saved.reason)
        self.assertFalse((self.record() / "result.json").exists())

    def test_unremovable_public_and_temp_names_are_both_reported(self):
        with mock.patch.object(os, "unlink", side_effect=OSError(13, "injected cleanup error")):
            saved = self.write_marker()
        tmp, = self.record().glob(".result.json.*.tmp")
        marker = self.record() / "result.json"
        self.assertFalse(saved.ok)
        self.assertEqual(saved.leftover, str(marker))
        self.assertEqual(saved.leftover_bytes, marker.stat().st_size + tmp.stat().st_size)
        self.assertIn(str(marker), saved.reason)
        self.assertIn(str(tmp), saved.reason)

    def test_a_marker_leftover_retains_the_job_and_the_decided_outcome(self):
        real_unlink = os.unlink

        def unlink(name, **kw):
            if str(name).startswith(".result.json."):
                raise OSError(13, "injected cleanup error")
            return real_unlink(name, **kw)

        with mock.patch.object(os, "unlink", unlink):
            out = self.finish()
        self.assertEqual(out.outcome, "valid")
        self.assertFalse(out.cleaned or out.record_complete)
        self.assertTrue(out.leftover.endswith(".tmp"))
        self.assertTrue(self.scratch.exists() and self.run_home.exists())
        self.assertIn(out.leftover, self.manifest()["retained_reason"])


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

    def test_a_reader_in_the_window_waits_for_the_marker_when_it_asked_to(self):
        # the daemon's own order leaves a moment with the outcome in the manifest and no (or a torn) result.json;
        # the console's screens read in that moment (load verification: 2 of 10 runs failed with 409)
        real = rfn._write_new
        got = {}

        def reader(settle, key):
            def run():
                try:
                    with sfl.settling(settle):
                        got[key] = [x["record"] for x in sfl.flow_reviews(self.base, FID, TID)]
                except sfl.FlowRefused as exc:
                    got[key] = exc.code
            t = threading.Thread(target=run)
            t.start()
            return t

        def write(dir_fd, name, data, dst):
            if name != "result.json":
                return real(dir_fd, name, data, dst)
            self.assertEqual(self.manifest()["outcome"], "valid")           # the window: decided, no marker yet
            waits, nows = reader(5.0, "waits"), reader(0.0, "nows")
            nows.join(10)
            self.assertEqual(got["nows"], "count_unavailable")              # the daemon's own reading is unchanged
            time.sleep(0.3)
            self.assertNotIn("waits", got)                                   # still waiting, not refused
            out = real(dir_fd, name, data, dst)
            waits.join(10)
            return out
        with mock.patch.object(rfn, "_write_new", write):
            out = self.finish()
        self.assertTrue(out.record_complete)
        self.assertEqual(got["waits"], ["complete"])

    def test_the_wait_is_bounded_and_a_cleaned_job_never_waits(self):
        real = rfn._write_new
        timing = {}

        def write(dir_fd, name, data, dst):
            if name != "result.json":
                return real(dir_fd, name, data, dst)
            t0 = time.monotonic()                                            # a window that never closes
            with sfl.settling(0.4):
                with self.assertRaises(sfl.FlowRefused) as cm:
                    sfl.flow_reviews(self.base, FID, TID)
            timing["open"] = time.monotonic() - t0
            self.assertEqual(cm.exception.code, "count_unavailable")
            return rfn._Saved(False, "審查紀錄的 result.json 無法寫入（OSError）")
        with mock.patch.object(rfn, "_write_new", write):
            self.finish()
        self.assertGreaterEqual(timing["open"], 0.35)
        self.assertLess(timing["open"], 5.0)
        self.assertEqual(self.manifest()["state"], "cleaned")
        t0 = time.monotonic()                                                # decided, cleaned, no marker: damage
        with sfl.settling(3.0):
            with self.assertRaises(sfl.FlowRefused) as cm:
                sfl.flow_reviews(self.base, FID, TID)
        self.assertEqual(cm.exception.code, "count_unavailable")
        self.assertLess(time.monotonic() - t0, 1.0)

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


class ResumeTests(Scenario):
    """Codex 3c R4 P1: finish_review looks at the manifest before it opens
    anything for writing. A job decided before is never judged or saved
    again, so EEXIST is not on the normal path and an outcome is not
    rewritten."""

    def no_judging(self):
        """Judging, saving the process's files or looking at the clone again
        fails the test. Reading the record's own saved copies is allowed (it
        is how result.json is rebuilt), and so is writing result.json."""
        def boom(*a, **kw):
            raise AssertionError("the job was judged or saved again")
        real = rfn._write_new

        def only_the_marker(dir_fd, name, data, dst):
            assert name == "result.json", f"{name} was written again"
            return real(dir_fd, name, data, dst)
        return (mock.patch.object(rfn, "judge_events", boom), mock.patch.object(rv, "open_rollout", boom),
                mock.patch.object(rv, "validate_rollout", boom), mock.patch.object(rv, "copy_rollout", boom),
                mock.patch.object(rfn.git_objects, "commit_exists", boom), mock.patch.object(rfn.git_head, "read_head", boom),
                mock.patch.object(rfn, "_write_new", only_the_marker))

    def finish_without_result_json(self):
        real = rfn._write_new

        def write(dir_fd, name, data, dst):
            if name == "result.json":
                return rfn._Saved(False, "審查紀錄的 result.json 無法寫入（OSError）")
            return real(dir_fd, name, data, dst)
        with mock.patch.object(rfn, "_write_new", write):
            out = self.finish()
        self.assertEqual((out.outcome, out.record_complete), ("valid", False))
        self.assertFalse((self.record() / "result.json").exists())
        return out

    def snapshot(self):
        return {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in self.record().iterdir()}

    def second_call(self, **run):
        patches = self.no_judging()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return rfn.finish_review(self.base, rs.read_manifest(self.base, JOB), {"interrupted": True, **run}, c=C)

    def test_a_job_decided_and_recorded_is_a_no_op(self):
        first = self.finish()
        self.assertEqual((first.outcome, first.record_complete, first.cleaned), ("valid", True, True))
        before, manifest = self.snapshot(), self.manifest()
        again = self.second_call()
        self.assertEqual((again.outcome, again.record_complete, again.cleaned), ("valid", True, True))
        self.assertEqual(self.snapshot(), before)                                  # no file touched
        self.assertEqual(self.manifest(), manifest)                                # the outcome is not rewritten
        self.assertEqual(again.result["valid"], True)

    def test_a_decided_invalid_job_is_a_no_op_too(self):
        self.finish(exit_code=3)
        before, manifest = self.snapshot(), self.manifest()
        again = self.second_call()
        self.assertEqual((again.outcome, again.record_complete), ("invalid", True))
        self.assertEqual((self.snapshot(), self.manifest()), (before, manifest))
        self.assertTrue(again.reasons)

    def test_saved_copies_and_outcome_but_no_result_json_gets_only_the_marker(self):
        first = self.finish_without_result_json()
        self.assertIn("result.json", first.problem)
        before = self.snapshot()
        manifest_before = self.manifest()
        self.assertEqual(manifest_before["outcome"], "valid")
        again = self.second_call()                                                 # judge/save functions fail the test if used
        self.assertEqual((again.outcome, again.record_complete, again.cleaned), ("valid", True, True))
        after = self.snapshot()
        self.assertEqual({k: v for k, v in after.items() if k != "result.json"}, before)   # copies untouched (same inode, mtime)
        result = json.loads(after["result.json"][2])
        self.assertEqual((result["valid"], result["verdict"], result["rebuilt"], result["job_id"]),
                         (True, "PASS", True, JOB))
        self.assertEqual((result["usage"], result["usage_problem"]), (None, "rebuilt"))      # not re-read, not 0
        self.assertEqual(self.manifest()["outcome"], "valid")
        self.assertEqual(self.manifest()["state"], "cleaned")
        self.assertEqual([x["record"] for x in sfl.flow_reviews(self.base, FID, TID)], ["complete"])
        self.assertFalse(self.scratch.exists())

    def test_an_invalid_job_gets_its_marker_back_with_the_recorded_reasons(self):
        real = rfn._write_new

        def write(dir_fd, name, data, dst):
            return (rfn._Saved(False, "x") if name == "result.json" else real(dir_fd, name, data, dst))
        with mock.patch.object(rfn, "_write_new", write):
            self.finish(exit_code=3)
        again = self.second_call()
        self.assertEqual((again.outcome, again.record_complete), ("invalid", True))
        result = json.loads((self.record() / "result.json").read_text())
        self.assertEqual((result["valid"], result["reasons"]), (False, self.manifest()["invalid_reasons"]))

    def test_unreadable_copies_leave_the_outcome_as_it_is(self):
        self.finish_without_result_json()
        os.unlink(self.record() / "events.jsonl")                                   # a saved copy is gone
        again = self.second_call()
        self.assertEqual((again.outcome, again.record_complete), ("valid", False))   # not upgraded, not downgraded
        self.assertIn("events.jsonl", again.problem)
        self.assertFalse((self.record() / "result.json").exists())
        self.assertEqual(self.manifest()["outcome"], "valid")
        self.assertIn("無法補寫", self.manifest()["retained_reason"])
        self.assertTrue((self.job / "events.jsonl").exists())                       # the job's own originals are kept

    def test_a_last_md_that_contradicts_a_valid_outcome_is_not_trusted(self):
        self.finish_without_result_json()
        (self.record() / "last.md").write_text("no control lines at all\n")
        again = self.second_call()
        self.assertFalse(again.record_complete)
        self.assertIn("last.md", again.problem)
        self.assertFalse((self.record() / "result.json").exists())

    def test_a_marker_that_disagrees_is_left_alone(self):
        self.finish()
        (self.record() / "result.json").write_text(json.dumps({"v": 1, "job_id": JOB, "round": 1,
                                                               "commit": self.commit, "valid": False}))
        before = self.snapshot()
        again = self.second_call()
        self.assertFalse(again.record_complete)
        self.assertIn("不一致", again.problem)
        self.assertEqual(self.snapshot(), before)

    def test_a_manual_review_job_is_left_alone(self):
        self.finish(manual_review="group still alive")
        manifest = self.manifest()
        again = self.second_call()
        self.assertEqual(again.outcome, "manual_review")
        self.assertIn("group still alive", again.reasons[0])
        self.assertEqual(self.manifest(), manifest)
        self.assertTrue(self.scratch.exists())

    def test_an_unreadable_manifest_writes_nothing(self):
        (self.job / "manifest.json").write_text("{")
        out = rfn.finish_review(self.base, state_manifest("running", job_id=JOB), {"exit_code": 0}, c=C)
        self.assertEqual(out.outcome, "manual_review")
        self.assertFalse((self.record() / "last.md").exists())


class StderrLimitTests(Scenario):
    """Codex 3c R4 P2: stderr.log is bounded by its own 1 MiB, not events' 8 MiB."""

    def test_stderr_larger_than_its_cap_is_refused_and_not_saved(self):
        (self.job / "stderr.log").write_bytes(b"x" * ((1 << 20) + 1))
        out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("stderr.log", " | ".join(out.reasons))
        self.assertFalse((self.record() / "stderr.log").exists())
        self.assertTrue((self.job / "stderr.log").exists())                         # kept for a person

    def test_stderr_of_exactly_its_cap_is_read(self):
        (self.job / "stderr.log").write_bytes(b"x" * (1 << 20))
        out = self.finish()
        self.assertEqual(out.outcome, "valid")
        self.assertEqual((self.record() / "stderr.log").stat().st_size, 1 << 20)

    def test_the_limits_are_the_runs_own(self):
        from vbear.runtime import review_run
        self.assertEqual((rfn.EVENTS_LIMIT, rfn.STDERR_LIMIT), (review_run.EVENTS_CAP, review_run.STDERR_CAP))
        self.assertLess(rfn.STDERR_LIMIT, rfn.EVENTS_LIMIT)


class SameBytesTests(Scenario):
    """Codex 3c R1 #2 and R3: events.jsonl and stderr.log are opened once and
    read whole into memory; the judgement and the saved record both use those
    bytes, and the names are never opened again. Whatever happens to the
    files after they were read cannot make the record differ from what was
    judged, and there is no second look at the path to race."""

    def after_judging(self, change):
        real = rfn.git_objects.commit_exists

        def later(*a, **kw):                       # runs after both files were read and events.jsonl judged
            change()
            return real(*a, **kw)
        return mock.patch.object(rfn.git_objects, "commit_exists", later)

    def test_the_files_are_opened_for_reading_only_once(self):
        reads = []
        real_open = os.open

        def spy(path, flags, *a, **kw):
            if (str(path) in ("events.jsonl", "stderr.log") and "dir_fd" in kw
                    and not flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR)):
                reads.append(str(path))
            return real_open(path, flags, *a, **kw)
        with mock.patch.object(os, "open", spy):
            out = self.finish()
        self.assertEqual(out.outcome, "valid")
        self.assertEqual(sorted(reads), ["events.jsonl", "stderr.log"])        # once each, from judging to saving

    def test_a_change_after_reading_cannot_change_the_record(self):
        originals = {n: (self.job / n).read_bytes() for n in ("events.jsonl", "stderr.log")}

        def change():
            (self.job / "events.jsonl.new").write_bytes(b'{"type":"thread.started","thread_id":"x"}\n')
            os.rename(self.job / "events.jsonl.new", self.job / "events.jsonl")            # replaced
            with open(self.job / "stderr.log", "ab") as f:                                  # appended to
                f.write(b"more\n")
        with self.after_judging(change):
            out = self.finish()
        self.assertEqual(out.outcome, "valid")                                    # the bytes that were judged are valid
        for name, data in originals.items():
            self.assertEqual((self.record() / name).read_bytes(), data)           # and those are what the record holds

    def test_a_same_size_rewrite_after_reading_cannot_change_the_record(self):
        original = (self.job / "events.jsonl").read_bytes()

        def rewrite():
            with open(self.job / "events.jsonl", "r+b") as f:
                f.write(b"X" + original[1:])
        with self.after_judging(rewrite):
            out = self.finish()
        self.assertEqual(out.outcome, "valid")
        self.assertEqual((self.record() / "events.jsonl").read_bytes(), original)

    def test_a_file_that_is_not_a_plain_file_is_not_read(self):
        os.unlink(self.job / "stderr.log")
        os.symlink("/etc/hosts", self.job / "stderr.log")
        out = self.finish()
        self.assertEqual(out.outcome, "invalid")
        self.assertIn("stderr.log", " | ".join(out.reasons))
        self.assertFalse((self.record() / "stderr.log").exists())


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

    def test_a_directory_swapped_in_before_the_rename_is_put_back_not_deleted(self):
        # the identity check and the delete are separated by a rename to a
        # private name, which is checked again
        stranger = Path(tempfile.mkdtemp(prefix="sr-", dir="/private/tmp"))
        self.addCleanup(shutil.rmtree, stranger, True)
        (stranger / "keep-me").write_text("x")
        real = os.rename
        swapped = []

        def rename(src, dst, *a, **kw):
            if not swapped and str(src) == self.scratch.name:
                swapped.append(1)
                shutil.rmtree(self.scratch)                  # after the check, before the rename
                real(stranger, self.scratch)
            return real(src, dst, *a, **kw)
        with mock.patch.object(rfn.os, "rename", rename):
            out = self.finish()
        self.assertTrue((self.scratch / "keep-me").exists())                 # put back, not deleted
        self.assertFalse(Path("/private/tmp", f".{self.scratch.name}.deleting").exists())
        self.assertIn("被換成別的東西", out.problem)
        self.assertEqual(self.manifest()["outcome"], "valid")                # decided; not cleaned
        self.assertNotEqual(self.manifest()["state"], "cleaned")

    def test_nothing_is_left_under_the_private_name(self):
        self.finish()
        self.assertFalse(Path("/private/tmp", f".{self.scratch.name}.deleting").exists())
        self.assertFalse((self.base / "codex-run-homes" / f".{JOB}.deleting").exists())

    def test_an_earlier_attempt_that_died_after_the_rename_is_finished(self):
        private = Path("/private/tmp") / f".{self.scratch.name}.deleting"
        os.rename(self.scratch, private)                                      # as if the daemon died right here
        (private / "leftover").write_text("x")
        # the manifest identity is the renamed directory's: it is the same inode
        self.assertEqual(rfn.cleanup_job(self.base, self.manifest()), None)
        self.assertFalse(private.exists())

    def test_a_private_name_that_is_not_ours_is_not_touched(self):
        private = Path("/private/tmp") / f".{self.scratch.name}.deleting"
        private.mkdir()
        self.addCleanup(shutil.rmtree, private, True)
        (private / "keep-me").write_text("x")
        problem = rfn.cleanup_job(self.base, self.manifest())
        self.assertIn("身分不符", problem)
        self.assertTrue((private / "keep-me").exists())
        self.assertTrue(self.scratch.exists())

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
