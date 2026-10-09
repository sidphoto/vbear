"""Codex review jobs in the runtime daemon (design 5, 6, 7, 9; planner
decisions S2b, v29.8, v29.9).

A synthetic stand-in plays Codex 0.160.0: it prints its version, answers
`mcp list`, and for `exec` writes a clone HEAD, an events stream and a rollout
built from tests/review_fixtures.py (every condition of 5.5 and 5.6 breakable
one at a time). The pinned install lives under a temporary HOME; the
administrator-settings root is a temporary directory. No Codex, no model, no
network. The executor side is the synthetic Claude of test_runtimed_stream.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests import review_fixtures as rf
from tests.test_runtimed_stream import REPO, StreamCase, TIMEOUT
from vbear import acceptance as acc
from vbear import flows, login_identity, tasks
from vbear.runtime import codex_constants as cc
from vbear.runtime import daemon_review, pipeline_store, quota, review_codex, review_store, stream_flow

FAKE_CODEX = r'''#!%(py)s
import json, os, re, signal, subprocess, sys, time
sys.path.insert(0, %(repo)r)
here = os.path.dirname(os.path.abspath(__file__))
def _term(*_):
    open(os.path.join(here, "got-sigterm"), "w").close()
    sys.exit(143)
signal.signal(signal.SIGTERM, _term)
mode = open(os.path.join(here, "fake-mode")).read().strip() if os.path.exists(os.path.join(here, "fake-mode")) else "ok"
argv = sys.argv[1:]
with open(os.path.join(here, "calls.log"), "a") as f:
    # (macOS adds __CF_USER_TEXT_ENCODING to a Python process by itself; it is not from the daemon)
    f.write(json.dumps({"argv": argv, "env": sorted(k for k in os.environ if k != "__CF_USER_TEXT_ENCODING"), "home": os.environ.get("HOME"),
                        "codex_home": os.environ.get("CODEX_HOME"), "cwd": os.getcwd(), "pid": os.getpid(),
                        "pgid": os.getpgrp()}) + "\n")
if argv == ["--version"]:
    print("codex-cli 0.160.0" if mode != "wrong_version" else "codex-cli 0.159.2")
    sys.exit(0)
if "mcp" in argv:
    print('[{"name": "x"}]' if mode == "mcp_nonempty" else "[]")
    sys.exit(0)
from tests import review_fixtures as rf
scratch = argv[argv.index("-C") + 1]
model = argv[argv.index("-m") + 1]
prompt = argv[-1]
commit = re.search(r"REVIEWED_COMMIT: ([0-9a-f]{40,64})", prompt).group(1)
os.makedirs(os.path.join(scratch, "repo", ".git"), exist_ok=True)
with open(os.path.join(scratch, "repo", ".git", "HEAD"), "w") as f:
    f.write(commit + "\n")
verdict = {"needs_work": "NEEDS WORK", "blocked": "BLOCKED"}.get(mode, "PASS")
text = rf.report(commit=commit, verdict=verdict)
if mode == "no_verdict":
    text = text.replace("VERDICT: PASS\n", "")
if mode == "wrong_commit":
    text = rf.report(commit="d" * 40)
evs, recs, _ = rf.valid_run(text=text, scratch=scratch, model=model, thread=rf.THREAD)
codex_home = os.environ["CODEX_HOME"]
d = os.path.join(codex_home, "sessions", time.strftime("%%Y/%%m/%%d"))
os.makedirs(d, exist_ok=True)
with open(os.path.join(d, "rollout-x-%%s.jsonl" %% rf.THREAD), "wb") as f:
    f.write(rf.lines(recs))
def emit(events):
    for e in events:
        sys.stdout.write(json.dumps(e) + "\n")
    sys.stdout.flush()
if mode == "hang":
    emit(evs[:2]); open(os.path.join(here, "hang-ready"), "w").close(); time.sleep(600)
if mode == "stderr_flood":
    sys.stderr.write("x" * 1048576 * 2); sys.stderr.flush()
emit(evs)
sys.exit(3 if mode == "exit3" else 0)
'''


class ReviewCase(StreamCase):
    def setUp(self):
        super().setUp()
        machine = platform.machine().lower()
        arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
        bindir = self.home / ".codex/packages/standalone/releases" / f"0.160.0-{arch}-apple-darwin" / "bin"
        bindir.mkdir(parents=True)
        self.codex = bindir / "codex"
        self.codex.write_text(FAKE_CODEX % {"py": sys.executable, "repo": REPO})
        self.codex.chmod(0o700)
        self.fake_dir = bindir
        v = mock.patch.object(cc, "VERIFIED_VERSIONS", ("0.160.0",))
        v.start()
        self.addCleanup(v.stop)
        self.dm.review_admin_root = str(self.root)
        self.dm.review_home = str(self.home)
        # the dedicated CODEX_HOME with a login, and an acceptance that binds to it
        self.codex_home = self.base / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        (self.codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt",
                                                               "tokens": {"account_id": "acct-0001"}}))
        os.chmod(self.codex_home / "auth.json", 0o600)
        self.accept()
        # the task's work directory is a real repository with two commits
        shutil.rmtree(self.work / ".git")
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        self.base_commit = self.commit = self.git("rev-parse", "HEAD")      # the executor starts here (v29.9 base_commit)
        tasks.save_task(self.tid, {"title": "t", "workdir": str(self.work)})

    def git(self, *args):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.work), "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args], cwd=self.work,
                              env=env, check=True, capture_output=True, text=True).stdout.strip()

    def accept(self, **limits):
        fp = "b" * 64
        if (self.base / "codex-home" / "auth.json").exists():
            fp = login_identity.codex_login_fingerprint(self.base / "codex-home", self.key).hmac
        claude_fp = login_identity.claude_login_fingerprint(self.home / ".claude.json", self.key).hmac
        fields = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
                  "executor_claude_version": "2.1.292", "executor_model": rf.fx.MODEL if hasattr(rf, "fx") else "",
                  "executor_login_fingerprint": claude_fp, "login_fingerprint": fp,
                  "login_key_id": self.key.key_id, "limits": {**acc.DEFAULT_LIMITS, **(self.limits or {}), **limits}}
        from tests import stream_fixtures as fx
        fields["executor_model"] = fx.MODEL
        with flows.store.locked():
            data = flows.store.load()
            ev = data[self.fid]["events"]
            ev.append({"seq": len(ev) + 1, "at": time.time(), "kind": "risk_acknowledged", "source": "console",
                       "note": "", **fields})
            flows.store.save(data)

    # ---- helpers ----

    def fake_mode(self, mode):
        (self.fake_dir / "fake-mode").write_text(mode)

    def calls(self):
        try:
            return [json.loads(x) for x in (self.fake_dir / "calls.log").read_text().splitlines()]
        except OSError:
            return []

    def exec_calls(self):
        return [c for c in self.calls() if c["argv"] and c["argv"][0] == "exec"]

    def executor_done(self):
        """An executor session ran for this flow and ended: the flow has its
        start record (with the base commit) and a session in its accounting."""
        launch_id, _ = self.open()
        r = self.rpc("stream_close", launch_id=launch_id)
        self.assertTrue(r.get("ok"), r)
        self.wait_for(lambda: self.manifest(launch_id)["state"] == "ended", msg="the executor session to end")
        self.git("commit", "-q", "--allow-empty", "-m", "change")            # the executor's work: what is reviewed
        self.commit = self.git("rev-parse", "HEAD")
        return launch_id

    def crash_daemon(self):
        """As the stream version: nothing is cleaned up, signalled or reaped;
        the review process lives on in its own group."""
        for job in self.dm._reviews.values():
            for f in (job.run.proc.stdin, job.run.proc.stdout, job.run.proc.stderr):
                try:
                    if f is not None:
                        f.close()
                except OSError:
                    pass
            for fd in (job.run.events_fd, job.run.stderr_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.dm._reviews.clear()
        super().crash_daemon()

    def start_review(self, round_=1, commit=None):
        return self.rpc("review_start", pipeline=self.fid, round=round_, commit=commit or self.commit)

    def review_status(self, job_id):
        r = self.rpc("review_status", job_id=job_id)
        self.assertTrue(r.get("ok"), r)
        return r["result"]

    def wait_state(self, job_id, *states, timeout=TIMEOUT):
        return self.wait_for(lambda: (s := self.review_status(job_id))["state"] in states and s,
                             timeout=timeout, msg=f"review {job_id} to reach {states}")

    def record_dir(self, round_=1):
        return self.base / "pipelines" / self.tid / "reviews" / str(round_)

    def held(self):
        return pipeline_store.is_held(self.base, self.fid)

    def run_review(self, mode="ok", round_=1):
        self.fake_mode(mode)
        r = self.start_review(round_)
        self.assertTrue(r.get("ok"), r)
        return r["result"]["job_id"]


class HappyPathTests(ReviewCase):
    def test_a_valid_review_end_to_end(self):
        self.executor_done()
        job = self.run_review("ok")
        end = self.wait_state(job, "cleaned")
        self.assertEqual((end["outcome"], end["process"], end["exit_code"]), ("valid", "started", 0))
        self.assertEqual(end["record"], "complete")
        self.assertEqual((end["result"]["valid"], end["result"]["verdict"], end["result"]["base_is_ancestor"]),
                         (True, "PASS", True))
        rec = self.record_dir()
        self.assertEqual(sorted(p.name for p in rec.iterdir()),
                         ["events.jsonl", "job.json", "last.md", "result.json", "rollout.jsonl", "stderr.log"])
        # nothing is left: the scratch, the run home, the job's own files
        m = review_store.read_manifest(self.base, job)
        self.assertFalse(os.path.exists(m["scratch"]["path"]))
        self.assertFalse((self.base / "codex-run-homes" / job).exists())
        self.assertEqual(sorted(p.name for p in review_store.job_dir(self.base, job).iterdir()), ["manifest.json"])
        self.assertFalse(self.held())
        self.assertEqual(self.dm._reviews, {})
        self.assertEqual(self.dm._ledger.reservations.get(f"review:{job}"), None)
        self.assertEqual(stream_flow.failure_ids(self.base, self.fid, self.tid), [])

    def test_the_process_is_started_as_designed(self):
        self.executor_done()
        job = self.run_review("ok")
        self.wait_state(job, "cleaned")
        [call] = self.exec_calls()
        m = review_store.read_manifest(self.base, job)
        expected = review_codex.review_argv(
            cc.VERSIONS["0.160.0"], str(self.codex), model="gpt-6-luna", scratch=m["scratch"]["path"],
            prompt=review_codex.prompt_for(cc.VERSIONS["0.160.0"], workdir=str(self.work), commit=self.commit,
                                           base=self.base_commit))
        self.assertEqual([str(self.codex)] + call["argv"], expected)                  # the whole argv, in order
        self.assertEqual(call["env"], sorted(review_codex.ENV_KEYS))                  # exactly six variables
        self.assertEqual(call["codex_home"], str(self.codex_home))
        self.assertEqual(call["home"], str(self.base / "codex-run-homes" / job))
        self.assertEqual(call["cwd"], m["scratch"]["path"])
        self.assertEqual(call["pgid"], call["pid"])                                    # its own process group
        self.assertEqual(m["argv_sha256"].__len__(), 64)
        # `codex --version` and `codex mcp list --json` ran first, with the same settings
        mcp = [c for c in self.calls() if "mcp" in c["argv"]]
        self.assertEqual(len(mcp), 1)
        self.assertEqual(mcp[0]["argv"][-3:], ["mcp", "list", "--json"])
        self.assertEqual(mcp[0]["codex_home"], str(self.codex_home))

    def test_a_negative_verdict_is_a_valid_review_and_does_not_stop_the_flow(self):
        self.executor_done()
        for round_, mode, verdict in ((1, "needs_work", "NEEDS WORK"), (2, "blocked", "BLOCKED")):
            job = self.run_review(mode, round_)
            end = self.wait_state(job, "cleaned")
            self.assertEqual((end["outcome"], end["result"]["verdict"]), ("valid", verdict))
            self.assertFalse(self.held())

    def test_a_resend_returns_the_same_job_and_another_commit_is_refused(self):
        self.executor_done()
        first = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="the review to hang")
        again = self.start_review()
        self.assertTrue(again["ok"], again)
        self.assertEqual((again["result"]["job_id"], again["result"]["existing"]), (first, True))
        other = self.start_review(commit=self.base_commit)
        self.assertFalse(other["ok"])
        self.assertIn("另一個 commit", other["error"]["message"])
        self.assertEqual(len(self.exec_calls()), 1)                                   # one process, not two
        self.rpc("review_cancel", job_id=first)
        self.wait_state(first, "cleaned")
        r = self.start_review()                                                        # a resend after the end still names it
        self.assertFalse(r["ok"])                                                      # but the flow is held by the cancel (v29.8)


class RefusalTests(ReviewCase):
    def refused(self, fragment, **kw):
        r = self.start_review(**kw)
        self.assertFalse(r["ok"], r)
        self.assertIn(fragment, r["error"]["message"])
        self.assertEqual(self.exec_calls(), [])                                        # no review process was started
        self.assertEqual(os.listdir(review_store.reviews_root(self.base)) if review_store.reviews_root(self.base).exists() else [], [])
        return r

    def test_bad_requests(self):
        for kw in ({"pipeline": "x"}, {"round": 0}, {"round": 1001}, {"round": True}, {"round": "1"},
                   {"commit": "A" * 40}, {"commit": "a" * 39}, {"commit": 5}):
            with self.subTest(kw=kw):
                req = {"pipeline": self.fid, "round": 1, "commit": self.commit, **kw}
                r = self.rpc("review_start", **req)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "bad_request")
        self.assertFalse(self.rpc("review_status", job_id="nope")["ok"])
        self.assertFalse(self.rpc("review_status", job_id="r-" + "0" * 16)["ok"])
        self.assertFalse(self.rpc("review_cancel", job_id="r-" + "0" * 16)["ok"])

    def test_a_flow_without_an_executor_start_has_no_base(self):
        self.refused("no_base")

    def test_the_hold_comes_first(self):
        self.executor_done()
        pipeline_store.hold(self.base, self.fid, "user stop")
        self.refused("held")

    def test_no_acceptance_for_this_codex(self):
        self.executor_done()
        for key, value, fragment in (("codex_version", "0.161.0", "還沒有通過驗證"), ("model", "gpt-other", "已驗證的清單")):
            with self.subTest(key=key):
                with flows.store.locked():
                    data = flows.store.load()
                    ev = data[self.fid]["events"]
                    last = dict(ev[-1])
                    last["seq"] = len(ev) + 1
                    last[key] = value
                    ev.append(last)
                    flows.store.save(data)
                self.refused(fragment)
                self.accept()

    def test_an_unverified_codex_cannot_start(self):
        self.executor_done()
        with mock.patch.object(cc, "VERIFIED_VERSIONS", ()):
            self.refused("還沒有通過驗證")

    def test_administrator_settings_refuse(self):
        self.executor_done()
        (self.root / "etc/codex").mkdir(parents=True)
        (self.root / "etc/codex/managed_config.toml").write_text("x")
        self.refused("admin_policy")

    def test_the_binary_must_be_the_pinned_one(self):
        self.executor_done()
        self.fake_mode("wrong_version")
        self.refused("version_mismatch")
        self.codex.unlink()
        self.refused("no_binary")

    def test_mcp_servers_refuse(self):
        self.executor_done()
        self.fake_mode("mcp_nonempty")
        self.refused("mcp")

    def test_the_codex_home_and_its_login(self):
        self.executor_done()
        os.chmod(self.codex_home, 0o755)
        self.refused("unsafe_path")
        os.chmod(self.codex_home, 0o700)
        (self.codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt",
                                                               "tokens": {"account_id": "acct-OTHER"}}))
        self.refused("reaccept")                                                        # another account than the accepted one
        os.unlink(self.codex_home / "auth.json")
        self.refused("no_login")
        shutil.rmtree(self.codex_home)
        self.refused("unsafe_path")

    def test_the_run_homes_root_must_be_ours_and_private(self):
        self.executor_done()
        root = self.base / "codex-run-homes"
        root.mkdir(mode=0o755)
        os.chmod(root, 0o755)
        r = self.start_review()
        self.assertFalse(r["ok"])
        self.assertIn("unsafe_path", r["error"]["message"])
        self.assertEqual(self.exec_calls(), [])
        root.rmdir()
        link_target = self.tmp / "elsewhere"
        link_target.mkdir(mode=0o700)
        os.symlink(link_target, root)
        self.assertFalse(self.start_review()["ok"])
        self.assertEqual(os.listdir(link_target), [])                                   # nothing was put through the link
        os.unlink(root)

    def test_the_work_directory_must_be_the_executors(self):
        self.executor_done()
        other = self.tmp / "other"
        other.mkdir()
        tasks.save_task(self.tid, {"title": "t", "workdir": str(other)})
        self.refused("workdir_mismatch")
        tasks.save_task(self.tid, {"title": "t", "workdir": None})
        self.refused("no_workdir")

    def test_one_review_at_a_time_and_a_limit_on_how_many(self):
        self.accept(max_reviews=1)
        self.executor_done()
        job = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="hang")
        r = self.start_review(round_=2)
        self.assertFalse(r["ok"])
        self.assertTrue("審查次數" in r["error"]["message"] or "全域" in r["error"]["message"], r)
        self.rpc("review_cancel", job_id=job)
        self.wait_state(job, "cleaned")

    def test_the_review_count_limit(self):
        self.accept(max_reviews=1)
        self.executor_done()
        job = self.run_review("ok")
        self.wait_state(job, "cleaned")
        r = self.start_review(round_=2)
        self.assertFalse(r["ok"])
        self.assertIn("審查次數", r["error"]["message"])

    def test_the_quota_refuses_when_there_is_no_room(self):
        self.executor_done()
        self.dm._ledger.limit = 1 << 20
        r = self.start_review()
        self.assertFalse(r["ok"])
        self.assertIn("quota", r["error"]["message"])
        self.assertEqual(self.dm._ledger.reservations, {})
        self.assertEqual(self.exec_calls(), [])


class FailureTests(ReviewCase):
    def failed(self, mode, fragment):
        self.executor_done()
        job = self.run_review(mode)
        end = self.wait_state(job, "cleaned", "manual_review")
        self.assertEqual(end["outcome"], "invalid", end)
        self.assertIn(fragment, " ".join(end["invalid_reasons"]))
        self.assertTrue(self.held())                                                    # v29.8: any failure stops the flow
        self.assertIn(f"{job}#invalid", stream_flow.failure_ids(self.base, self.fid, self.tid))
        for op, kw in (("review_start", {"pipeline": self.fid, "round": 2, "commit": self.commit}),
                       ("open_stream", {"launch_id": "l-" + "0" * 16})):
            r = self.rpc(op, **kw)
            self.assertFalse(r["ok"])
        return job, end

    def test_a_non_zero_exit_is_invalid_and_stops_the_flow(self):
        job, end = self.failed("exit3", "沒有以 0 結束")
        self.assertEqual(end["state"], "cleaned")
        self.assertEqual(end["result"]["valid"], False)
        self.assertTrue(self.record_dir().joinpath("events.jsonl").exists())            # the record is kept

    def test_report_rules_are_enforced(self):
        self.failed("no_verdict", "VERDICT")

    def test_the_wrong_commit_in_the_report(self):
        self.failed("wrong_commit", "REVIEWED_COMMIT")

    def test_the_user_can_continue_after_a_failed_review(self):
        job, _ = self.failed("exit3", "沒有以 0 結束")
        r = self.rpc("pipeline_release", pipeline=self.fid)
        self.assertTrue(r["ok"], r)
        self.fake_mode("ok")
        r = self.start_review(round_=2)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.wait_state(r["result"]["job_id"], "cleaned")["outcome"], "valid")

    def test_a_stderr_flood_ends_the_review(self):
        self.failed("stderr_flood", "stderr 超過")

    def test_a_spawn_that_fails_is_invalid_and_leaves_nothing(self):
        self.executor_done()
        self.fake_mode("ok")
        real = subprocess.Popen

        def popen(argv, *a, **kw):                          # only the review's own process fails to start
            if len(argv) > 1 and argv[1] == "exec":
                raise OSError(2, "No such file")
            return real(argv, *a, **kw)
        with mock.patch.object(subprocess, "Popen", popen):
            r = self.start_review()
        self.assertFalse(r["ok"])
        [job] = os.listdir(review_store.reviews_root(self.base))
        end = self.review_status(job)
        self.assertEqual((end["state"], end["outcome"]), ("cleaned", "invalid"))
        self.assertFalse(os.path.exists(review_store.read_manifest(self.base, job)["scratch"]["path"]))
        self.assertTrue(self.held())
        self.assertEqual(self.dm._ledger.reservations, {})

    def test_a_job_that_cannot_be_created_leaves_nothing(self):
        self.executor_done()
        with mock.patch.object(daemon_review.review_store, "create_job_dir", side_effect=OSError(28, "No space")):
            r = self.start_review()
        self.assertFalse(r["ok"])
        self.assertFalse(self.held())                                                  # nothing happened that a person must look at
        self.assertEqual(self.dm._ledger.reservations, {})
        self.assertEqual([p for p in os.listdir("/private/tmp") if p.startswith("sr-")
                          and (Path("/private/tmp") / p).stat().st_mtime > time.time() - 120 and False], [])


class HoldAndCancelTests(ReviewCase):
    def hanging(self):
        self.executor_done()
        job = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="the review to hang")
        return job, self.exec_calls()[0]["pid"]

    def test_a_hold_ends_the_running_review_and_it_is_invalid(self):
        job, pid = self.hanging()
        r = self.rpc("pipeline_hold", pipeline=self.fid, reason="user stop")
        self.assertTrue(r["ok"], r)
        end = self.wait_state(job, "cleaned", "manual_review")
        self.assertEqual(end["outcome"], "invalid")
        self.assertIn("流程被停止", " ".join(end["invalid_reasons"]))
        self.assertTrue((self.fake_dir / "got-sigterm").exists())                      # ended by SIGTERM to its group
        self.assertRaises(OSError, os.kill, pid, 0)                                    # gone and reaped
        self.assertEqual(self.dm._reviews, {})
        self.assertEqual(self.dm._held_leaders, [])

    def test_a_cancel_is_invalid_and_stops_the_flow(self):
        job, pid = self.hanging()
        r = self.rpc("review_cancel", job_id=job)
        self.assertEqual(r["result"], {"job_id": job, "canceling": True})
        end = self.wait_state(job, "cleaned", "manual_review")
        self.assertEqual(end["outcome"], "invalid")
        self.assertIn("取消", " ".join(end["invalid_reasons"]))
        self.assertTrue(self.held())

    def test_a_failure_elsewhere_in_the_flow_ends_the_review_too(self):
        job, pid = self.hanging()
        self.dm._hold_for_failure(self.fid, "l-" + "1" * 16, "an executor failure")
        end = self.wait_state(job, "cleaned", "manual_review")
        self.assertEqual(end["outcome"], "invalid")

    def test_another_flows_hold_does_not_touch_it(self):
        job, pid = self.hanging()
        self.dm._review_hold("flow-ffffffffffff")
        time.sleep(0.5)
        self.assertEqual(self.review_status(job)["state"], "running")
        self.rpc("review_cancel", job_id=job)
        self.wait_state(job, "cleaned")

    def test_the_review_timeout(self):
        self.executor_done()
        real = self.dm._review_preflight

        def short(ctx):
            plan = real(ctx)
            plan["timeout_s"] = 1.0
            return plan
        self.dm._review_preflight = short
        job = self.run_review("hang")
        end = self.wait_state(job, "cleaned", "manual_review", timeout=30)
        self.assertEqual(end["outcome"], "invalid")
        self.assertIn("逾時", " ".join(end["invalid_reasons"]))
        self.assertTrue(self.held())


class ShutdownAndRecoveryTests(ReviewCase):
    def test_shutdown_ends_a_running_review_and_records_it(self):
        self.executor_done()
        job = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="hang")
        pid = self.exec_calls()[0]["pid"]
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        self.assertRaises(OSError, os.kill, pid, 0)
        m = review_store.read_manifest(self.base, job)
        self.assertEqual((m["state"], m["outcome"]), ("cleaned", "invalid"))
        self.assertIn("關閉", " ".join(m["invalid_reasons"]))
        self.assertTrue(self.held())
        self.restart_daemon()                                                           # the next start finds nothing to do

    def test_a_crashed_daemon_with_a_live_review_leaves_it_for_a_person(self):
        self.executor_done()
        job = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="hang")
        pid = self.exec_calls()[0]["pid"]
        self.pids.append(pid)
        self.crash_daemon()
        self.restart_daemon()
        end = self.review_status(job)
        self.assertEqual((end["state"], end["outcome"]), ("manual_review", "manual_review"))
        os.kill(pid, 0)                                                                 # never signalled
        self.assertTrue(os.path.exists(review_store.read_manifest(self.base, job)["scratch"]["path"]))
        self.assertTrue(self.held())
        self.assertFalse(self.start_review(round_=2)["ok"])

    def test_a_crashed_daemon_whose_review_is_gone_is_invalid_and_cleaned(self):
        self.executor_done()
        job = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="hang")
        pid = self.exec_calls()[0]["pid"]
        self.crash_daemon()
        os.kill(pid, 9)
        self.wait_for(lambda: not self._alive(pid), msg="the review process to be gone")
        self.restart_daemon()
        end = self.review_status(job)
        self.assertEqual((end["state"], end["outcome"]), ("cleaned", "invalid"))
        self.assertIn("中斷", " ".join(end["invalid_reasons"]))
        self.assertTrue(self.held())
        self.assertFalse(os.path.exists(review_store.read_manifest(self.base, job)["scratch"]["path"]))
        self.assertEqual(self.record_dir().joinpath("result.json").exists(), True)

    @staticmethod
    def _alive(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:
            st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        except OSError:
            return True
        return bool(st) and "Z" not in st

    def test_the_ledger_counts_unfinished_jobs_at_their_full_reservation(self):
        self.executor_done()
        job = self.run_review("hang")
        self.wait_for(lambda: (self.fake_dir / "hang-ready").exists(), msg="hang")
        self.dm._rebuild_ledger()
        self.assertEqual(self.dm._ledger.reservations.get(f"review:{job}"), quota.RESERVE_REVIEW)
        self.rpc("review_cancel", job_id=job)
        self.wait_state(job, "cleaned")
        self.dm._rebuild_ledger()
        self.assertNotIn(f"review:{job}", self.dm._ledger.reservations)

    def test_an_unreadable_review_job_means_no_quota_is_granted(self):
        self.executor_done()
        root = review_store.reviews_root(self.base)
        root.mkdir(mode=0o700, exist_ok=True)
        (root / "notes").mkdir()
        self.assertFalse(self.dm._rebuild_ledger())
        r = self.start_review()
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
