"""Task Card custody ideas adopted from OpenRig: exact-candidate binding
(git_head + tasks.verification_binding), the closure obligation, atomic
handoff with a chain of record, and derived pickup state."""

import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_OWN_TEMP = False
if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-custody-test-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
    _OWN_TEMP = True

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import config as cfg
from vbear import git_head, server, tasks

SHA_A = "a" * 40
SHA_B = "b" * 40


def fake_repo(root: Path, head: str = "ref: refs/heads/main\n", refs: dict | None = None,
              packed: str | None = None) -> Path:
    """A repository made of plain files, the way git lays them out."""
    gitdir = root / ".git"
    (gitdir / "refs" / "heads").mkdir(parents=True)
    (gitdir / "HEAD").write_text(head)
    for name, sha in (refs if refs is not None else {"refs/heads/main": SHA_A}).items():
        path = gitdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sha + "\n")
    if packed is not None:
        (gitdir / "packed-refs").write_text(packed)
    return root


class GitHeadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbear-githead-", dir=str(FAKE_HOME))))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_branch_from_a_loose_ref_and_from_a_subdirectory(self):
        repo = fake_repo(self.tmp / "r")
        (repo / "src" / "deep").mkdir(parents=True)
        for where in (repo, repo / "src" / "deep"):
            head = git_head.read_head(str(where))
            self.assertEqual((head["commit"], head["ref"], head["repo"], head["error"]),
                             (SHA_A, "refs/heads/main", str(repo), None))

    def test_packed_refs_and_detached_head(self):
        repo = fake_repo(self.tmp / "p", refs={},
                         packed=f"# pack-refs with: peeled fully-peeled sorted\n{SHA_B} refs/heads/main\n^{SHA_A}\n")
        self.assertEqual(git_head.read_head(str(repo))["commit"], SHA_B)
        detached = fake_repo(self.tmp / "d", head=SHA_A + "\n")
        self.assertEqual(git_head.read_head(str(detached))["commit"], SHA_A)

    def test_linked_worktree_reads_shared_refs_from_the_common_dir(self):
        main = fake_repo(self.tmp / "main", refs={"refs/heads/main": SHA_A, "refs/heads/feature": SHA_B})
        wtgit = main / ".git" / "worktrees" / "feature"
        wtgit.mkdir(parents=True)
        (wtgit / "HEAD").write_text("ref: refs/heads/feature\n")
        (wtgit / "commondir").write_text("../..\n")
        tree = self.tmp / "feature-tree"
        tree.mkdir()
        (tree / ".git").write_text(f"gitdir: {wtgit}\n")
        head = git_head.read_head(str(tree))
        self.assertEqual((head["commit"], head["ref"]), (SHA_B, "refs/heads/feature"))

    def test_unsafe_or_unreadable_layouts_give_no_commit(self):
        target = self.tmp / "elsewhere"
        target.write_text(SHA_A + "\n")
        cases = {
            "symlinked HEAD": lambda r: ((r / ".git" / "HEAD").unlink(), (r / ".git" / "HEAD").symlink_to(target)),
            "traversing ref": lambda r: (r / ".git" / "HEAD").write_text("ref: refs/heads/../../../elsewhere\n"),
            "reftable": lambda r: (r / ".git" / "reftable").mkdir(),
            "unborn branch": lambda r: (r / ".git" / "refs" / "heads" / "main").unlink(),
            "garbage ref": lambda r: (r / ".git" / "refs" / "heads" / "main").write_text("not a sha\n"),
            "garbage HEAD": lambda r: (r / ".git" / "HEAD").write_text("hello\n"),
        }
        for i, (name, breaker) in enumerate(cases.items()):
            repo = fake_repo(self.tmp / f"bad{i}")
            breaker(repo)
            head = git_head.read_head(str(repo))
            self.assertIsNone(head["commit"], name)
            self.assertTrue(head["error"], name)

    def test_a_fifo_never_blocks_the_read(self):
        # Review finding: open() on a FIFO without O_NONBLOCK waits forever.
        for where in ("HEAD", "refs/heads/main", "packed-refs"):
            repo = fake_repo(self.tmp / f"fifo-{where.replace('/', '-')}",
                             refs={} if where == "packed-refs" else None)
            target = repo / ".git" / where
            if target.exists():
                target.unlink()
            os.mkfifo(target)
            done = {}
            worker = threading.Thread(target=lambda: done.setdefault("head", git_head.read_head(str(repo))),
                                      daemon=True)
            worker.start()
            worker.join(5)
            self.assertFalse(worker.is_alive(), f"read_head blocked on a FIFO {where}")
            self.assertIsNone(done["head"]["commit"], where)
            self.assertIn("不是一般檔案", done["head"]["error"], where)

    def test_symlinked_dot_git_is_not_followed(self):
        real = fake_repo(self.tmp / "real")
        link = self.tmp / "link"
        link.mkdir()
        (link / ".git").symlink_to(real / ".git")
        head = git_head.read_head(str(link))
        self.assertIsNone(head["commit"])
        self.assertIn("符號連結", head["error"])

    def test_outside_any_repository(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        for where in (str(plain), str(FAKE_HOME)):
            head = git_head.read_head(where)
            self.assertEqual((head["commit"], head["repo"]), (None, None), where)
        self.assertIn("絕對路徑", git_head.read_head("relative/path")["error"])
        self.assertIn("不存在", git_head.read_head(str(self.tmp / "missing"))["error"])

    def test_agrees_with_real_git(self):
        git = shutil.which("git", path="/usr/bin:/opt/homebrew/bin:/usr/local/bin")
        if git is None or subprocess.run([git, "--version"], capture_output=True).returncode != 0:
            self.skipTest("git is not available")
        repo = self.tmp / "real-git"
        repo.mkdir()
        env = {"PATH": "/usr/bin:/bin", "HOME": str(FAKE_HOME), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null"}

        def g(*args, cwd=repo):
            return subprocess.run([git, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                                  cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()
        g("init", "-q", "-b", "main")
        g("commit", "-q", "--allow-empty", "-m", "one")
        self.assertEqual(git_head.read_head(str(repo))["commit"], g("rev-parse", "HEAD"))
        g("pack-refs", "--all")
        self.assertEqual(git_head.read_head(str(repo))["commit"], g("rev-parse", "HEAD"))
        g("worktree", "add", "-q", "-b", "side", str(self.tmp / "side-tree"))
        g("commit", "-q", "--allow-empty", "-m", "two", cwd=self.tmp / "side-tree")
        side = git_head.read_head(str(self.tmp / "side-tree"))
        self.assertEqual((side["commit"], side["ref"]),
                         (g("rev-parse", "HEAD", cwd=self.tmp / "side-tree"), "refs/heads/side"))


class _Store(unittest.TestCase):
    def setUp(self):
        cfg.ensure_state_dir()
        for path in (tasks._path(), tasks._corrupt_marker_path()):
            if path.exists():
                path.unlink()
        self.work = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbear-work-", dir=str(FAKE_HOME))))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.heads = {str(self.work): {"commit": SHA_A, "ref": "refs/heads/main", "repo": str(self.work),
                                        "error": None}}
        patcher = mock.patch.object(tasks, "HEAD_READER", side_effect=self.read_head)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_head(self, workdir):
        return dict(self.heads.get(workdir) or {"commit": None, "ref": None, "repo": None,
                                                "error": "工作目錄不在 git 儲存庫內"})

    def move_head(self, sha):
        self.heads[str(self.work)]["commit"] = sha

    def assert_both(self, tid, **prov):
        return tasks.save_task(tid, {"provenance": {"agent": "in_progress", "tests": "passed",
                                                    "human": "approved", **prov}})


class ExactCandidateTests(_Store):
    def test_results_bind_to_the_commit_and_go_stale_when_it_moves(self):
        tasks.save_task("t-bind", {"title": "bind", "workdir": str(self.work)})
        t = self.assert_both("t-bind")
        self.assertEqual(t["provenance"]["tests_candidate"]["commit"], SHA_A)
        self.assertEqual(t["provenance"]["human_candidate"]["commit"], SHA_A)
        self.assertEqual((t["status"], t["verification_binding"]["state"]), ("verification_asserted", "current"))
        self.assertTrue(t["provenance"]["verification_asserted"])

        self.move_head(SHA_B)
        t = tasks.get_task("t-bind")
        self.assertEqual((t["status"], t["verification_binding"]["state"]), ("verification_stale", "stale"))
        self.assertFalse(t["provenance"]["verification_asserted"])
        self.assertIn("aaaaaaaa", t["verification_binding"]["detail"])
        self.assertIn("bbbbbbbb", t["verification_binding"]["detail"])
        self.assertEqual([x["status"] for x in tasks.list_tasks()], ["verification_stale"])
        self.assertFalse(t["provenance"]["verified"])

    def test_keeping_a_result_never_rebinds_it(self):
        tasks.save_task("t-keep", {"title": "keep", "workdir": str(self.work)})
        self.assert_both("t-keep")
        self.move_head(SHA_B)
        # Saving again with the same results keeps the old candidates.
        t = self.assert_both("t-keep")
        self.assertEqual(t["provenance"]["tests_candidate"]["commit"], SHA_A)
        self.assertEqual(t["status"], "verification_stale")
        # Re-testing alone binds the test to B while the approval stays on A.
        tasks.save_task("t-keep", {"provenance": {"agent": "in_progress", "tests": "untested", "human": "approved"}})
        t = self.assert_both("t-keep")
        self.assertEqual(t["verification_binding"]["state"], "mismatch")
        self.assertEqual(t["status"], "verification_stale")
        # Re-approving binds both to B.
        tasks.save_task("t-keep", {"provenance": {"agent": "in_progress", "tests": "passed", "human": "pending"}})
        t = self.assert_both("t-keep")
        self.assertEqual((t["status"], t["verification_binding"]["state"]), ("verification_asserted", "current"))

    def test_client_cannot_supply_the_candidate(self):
        tasks.save_task("t-forge", {"title": "forge", "workdir": str(self.work)})
        forged = {"commit": SHA_B, "ref": "refs/heads/main", "repo": str(self.work), "error": None}
        t = self.assert_both("t-forge", tests_candidate=forged, human_candidate=forged)
        self.assertEqual(t["provenance"]["tests_candidate"]["commit"], SHA_A)
        self.assertEqual(t["provenance"]["human_candidate"]["commit"], SHA_A)

    def test_unbound_and_unreadable(self):
        tasks.save_task("t-none", {"title": "no workdir"})
        t = self.assert_both("t-none")
        self.assertEqual((t["status"], t["verification_binding"]["state"]), ("verification_asserted", "unbound"))

        plain = self.work / "not-a-repo"
        plain.mkdir()
        tasks.save_task("t-plain", {"title": "plain", "workdir": str(plain)})
        t = self.assert_both("t-plain")
        self.assertEqual((t["status"], t["verification_binding"]["state"]), ("verification_asserted", "unbound"))

        broken = self.work / "broken"
        broken.mkdir()
        self.heads[str(broken)] = {"commit": None, "ref": None, "repo": str(broken), "error": "找不到 HEAD"}
        tasks.save_task("t-broken", {"title": "broken", "workdir": str(broken)})
        t = self.assert_both("t-broken")
        self.assertEqual((t["status"], t["verification_binding"]["state"]), ("verification_stale", "unknown"))

    def test_workdir_validation(self):
        for bad in ("relative/dir", str(self.work / "missing"), "/tmp/\x00x", 42):
            with self.assertRaises(ValueError, msg=repr(bad)):
                tasks.save_task(None, {"title": "x", "workdir": bad})
        t = tasks.save_task(None, {"title": "x", "workdir": str(self.work) + "/./"})
        self.assertEqual(t["workdir"], str(self.work))
        self.assertIsNone(tasks.save_task(t["id"], {"workdir": None})["workdir"])

    def test_binding_uses_the_real_reader_by_default(self):
        mock.patch.stopall()
        repo = fake_repo(self.work / "repo")
        tasks.save_task("t-real", {"title": "real", "workdir": str(repo)})
        t = self.assert_both("t-real")
        self.assertEqual(t["verification_binding"]["state"], "current")
        (repo / ".git" / "refs" / "heads" / "main").write_text(SHA_B + "\n")
        self.assertEqual(tasks.get_task("t-real")["status"], "verification_stale")


class ClosureTests(_Store):
    def test_completing_or_blocking_requires_what_follows(self):
        tasks.save_task("t-c", {"title": "c"})
        with self.assertRaisesRegex(ValueError, "結案理由"):
            tasks.save_task("t-c", {"provenance": {"agent": "completed"}})
        with self.assertRaisesRegex(ValueError, "結案理由"):
            tasks.save_task("t-c", {"provenance": {"agent": "blocked"}})
        with self.assertRaisesRegex(ValueError, "結案理由不符"):
            tasks.save_task("t-c", {"provenance": {"agent": "blocked"}, "closure": {"reason": "no_follow_on"}})
        with self.assertRaisesRegex(ValueError, "對象"):
            tasks.save_task("t-c", {"provenance": {"agent": "blocked"}, "closure": {"reason": "blocked_on"}})
        with self.assertRaisesRegex(ValueError, "物件"):
            tasks.save_task("t-c", {"provenance": {"agent": "completed"}, "closure": "no_follow_on"})
        self.assertEqual(tasks.get_task("t-c")["provenance"]["agent"], "pending")  # nothing was saved

        t = tasks.save_task("t-c", {"provenance": {"agent": "blocked"},
                                    "closure": {"reason": "blocked_on", "target": "審查者", "note": "等回覆"}})
        self.assertEqual((t["status"], t["closure"]["reason"], t["closure"]["target"]),
                         ("blocked", "blocked_on", "審查者"))
        first_set_at = t["closure"]["set_at"]
        t = tasks.save_task("t-c", {"title": "renamed"})  # unrelated edits keep the closure
        self.assertEqual((t["closure"]["set_at"], t["closure_missing"]), (first_set_at, False))

    def test_closure_shapes_the_status(self):
        for reason, target, status in (("no_follow_on", None, "agent_completed"),
                                       ("handed_off_to", "下一位", "handed_off"),
                                       ("canceled", None, "closed"), ("denied", None, "closed"),
                                       ("superseded", None, "closed")):
            t = tasks.save_task(None, {"title": reason, "provenance": {"agent": "completed"},
                                       "closure": {"reason": reason, "target": target}})
            self.assertEqual(t["status"], status, reason)

    def test_closure_belongs_only_to_completed_or_blocked(self):
        with self.assertRaisesRegex(ValueError, "只有"):
            tasks.save_task(None, {"title": "x", "provenance": {"agent": "in_progress"},
                                   "closure": {"reason": "no_follow_on"}})
        t = tasks.save_task(None, {"title": "x", "provenance": {"agent": "completed"},
                                   "closure": {"reason": "no_follow_on"}})
        with self.assertRaisesRegex(ValueError, "不能移除"):
            tasks.save_task(t["id"], {"closure": None})
        reopened = tasks.save_task(t["id"], {"provenance": {"agent": "in_progress"}})
        self.assertIsNone(reopened["closure"])

    def test_raw_status_cannot_stand_in_for_completion_or_blocking(self):
        # Review finding: status="agent_completed"/"blocked" used to bypass closure.
        for raw in ("agent_completed", "blocked", "verification_asserted", "handed_off", "closed"):
            t = tasks.save_task(None, {"title": raw, "status": raw})
            self.assertEqual((t["status"], t["provenance"]["agent"], t["closure"], t["closure_missing"]),
                             ("draft", "pending", None, False), raw)
        self.assertEqual(tasks.save_task(None, {"title": "x", "status": "in_progress"})["status"], "in_progress")

    def test_raw_status_cards_from_older_versions_are_flagged_not_silently_downgraded(self):
        # Review R2 finding: such a card used to read "blocked" and now derives
        # to "draft"; legacy_status keeps what it claimed until the agent
        # field is set.
        legacy = {"t-raw": {"id": "t-raw", "title": "raw", "status": "blocked",
                            "provenance": {"agent": "pending", "tests": "untested", "human": "pending"},
                            "created_at": 1.0, "updated_at": 1.0}}
        cfg.write_private(tasks._path(), json.dumps(legacy))
        t = tasks.get_task("t-raw")
        self.assertEqual((t["status"], t["legacy_status"], t["closure_missing"]), ("draft", "blocked", False))
        t = tasks.save_task("t-raw", {"title": "raw, renamed"})
        self.assertEqual((t["status"], t["legacy_status"]), ("draft", "blocked"))
        self.assertEqual(json.loads(tasks._path().read_text())["t-raw"]["legacy_status"], "blocked")
        t = tasks.save_task("t-raw", {"provenance": {"agent": "in_progress"}})
        self.assertEqual((t["status"], t["legacy_status"]), ("in_progress", None))
        self.assertIsNone(tasks.save_task(None, {"title": "new", "status": "blocked"})["legacy_status"])

    def test_records_saved_before_the_rule_still_load_and_are_flagged(self):
        legacy = {"t-old": {"id": "t-old", "title": "old", "status": "agent_completed",
                            "provenance": {"agent": "completed", "tests": "untested", "human": "pending"},
                            "created_at": 1.0, "updated_at": 1.0}}
        cfg.write_private(tasks._path(), json.dumps(legacy))
        t = tasks.get_task("t-old")
        self.assertTrue(t["closure_missing"])
        self.assertEqual(t["status"], "agent_completed")
        t = tasks.save_task("t-old", {"title": "old, renamed"})
        self.assertTrue(t["closure_missing"])


class HandoffTests(_Store):
    def make(self, **extra):
        return tasks.save_task(None, {"title": "原卡", "goal": "做某件事", "scope": ["a.py"],
                                      "acceptance_criteria": ["測試通過"], "workdir": str(self.work),
                                      "steps": [{"title": "一", "done": True}],
                                      "associated_pane_id": "n-000000000001",
                                      "provenance": {"agent": "in_progress"}, **extra})

    def test_handoff_closes_and_creates_in_one_write(self):
        old = self.make()
        moved = tasks.handoff_task(old["id"], {"to": "審查者", "note": "請看 diff"})
        done, nxt = moved["from"], moved["to"]
        self.assertEqual((done["status"], done["closure"]["reason"], done["closure"]["target"],
                          done["closure"]["successor"]), ("handed_off", "handed_off_to", "審查者", nxt["id"]))
        self.assertEqual((nxt["handed_off_from"], nxt["chain_of_record"], nxt["owner"]),
                         (old["id"], [old["id"]], "審查者"))
        self.assertEqual((nxt["goal"], nxt["scope"], nxt["acceptance_criteria"], nxt["workdir"]),
                         ("做某件事", ["a.py"], ["測試通過"], str(self.work)))
        self.assertEqual(nxt["steps"], [{"title": "一", "done": False}])
        self.assertIsNone(nxt["associated_pane_id"])
        self.assertEqual((nxt["provenance"]["agent"], nxt["provenance"]["tests"], nxt["status"]),
                         ("pending", "untested", "draft"))
        stored = json.loads(tasks._path().read_text())
        self.assertEqual(set(stored), {old["id"], nxt["id"]})

        third = tasks.handoff_task(nxt["id"], {"to": "測試者"})["to"]
        self.assertEqual(third["chain_of_record"], [old["id"], nxt["id"]])

    def test_handoff_refusals(self):
        old = self.make()
        with self.assertRaisesRegex(ValueError, "對象"):
            tasks.handoff_task(old["id"], {"to": "  "})
        with self.assertRaises(LookupError):
            tasks.handoff_task("t-missing", {"to": "x"})
        tasks.handoff_task(old["id"], {"to": "x"})
        with self.assertRaisesRegex(ValueError, "已結案"):
            tasks.handoff_task(old["id"], {"to": "y"})

    def test_failed_write_leaves_neither_half(self):
        old = self.make()
        before = tasks._path().read_text()
        with mock.patch.object(cfg, "write_private", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                tasks.handoff_task(old["id"], {"to": "x"})
        self.assertEqual(tasks._path().read_text(), before)
        self.assertEqual(tasks.get_task(old["id"])["provenance"]["agent"], "in_progress")

    def test_chain_fields_cannot_be_set_by_a_client(self):
        t = tasks.save_task(None, {"title": "x", "handed_off_from": "task-forged",
                                   "chain_of_record": ["task-a", "task-b"]})
        self.assertEqual((t["handed_off_from"], t["chain_of_record"]), (None, []))
        nxt = tasks.handoff_task(self.make()["id"], {"to": "x"})["to"]
        kept = tasks.save_task(nxt["id"], {"chain_of_record": [], "handed_off_from": None, "title": "y"})
        self.assertEqual((kept["handed_off_from"], len(kept["chain_of_record"])), (nxt["handed_off_from"], 1))


def live(panes, available=True):
    return {"runtime": {"available": available}, "panes": panes}


class PickupTests(unittest.TestCase):
    def card(self, agent="in_progress", pane="n-000000000001", closure=None):
        return {"provenance": {"agent": agent}, "associated_pane_id": pane, "closure": closure}

    def test_states(self):
        p = {"pane_id": "n-000000000001", "exited": False}
        cases = [
            (self.card(agent="completed"), live([]), "closed"),
            (self.card(agent="blocked", closure={"target": "審查者"}), live([]), "blocked"),
            (self.card(pane=None), live([]), "unclaimed"),
            (self.card(), live([], available=False), "unknown"),
            (self.card(), None, "unknown"),
            (self.card(), live([]), "stalled"),
            (self.card(), live([{**p, "exited": True}]), "stalled"),
            (self.card(), live([{**p, "agent_status": "working"}]), "working"),
            (self.card(), live([{**p, "agent_status": "waiting"}]), "parked"),
            (self.card(), live([{**p, "agent_status": "needs-input"}]), "parked"),
            (self.card(), live([{**p, "agent_status": "unknown"}]), "unknown"),
        ]
        for card, view, want in cases:
            got = tasks.pickup(card, view)
            self.assertEqual(got["state"], want, (card, view))
            self.assertIn(got["state"], tasks.PICKUP_STATES)
            self.assertTrue(got["detail"])
        self.assertIn("審查者", tasks.pickup(self.card(agent="blocked", closure={"target": "審查者"}), None)["detail"])


class CustodyAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg.ensure_state_dir()
        cls.port = 18891
        cls.console = server.Console(cls.port)
        cls.console.auth_token = None  # auth has its own tests (AuthTests)
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", cls.port), server.make_handler(cls.console))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.H = {"Host": f"127.0.0.1:{cls.port}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{cls.port}"}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if _OWN_TEMP:
            shutil.rmtree(FAKE_HOME, ignore_errors=True)

    def setUp(self):
        for path in (tasks._path(), tasks._corrupt_marker_path()):
            if path.exists():
                path.unlink()

    def req(self, path, method="GET", body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=self.H, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read().decode("utf-8"))

    def test_handoff_endpoint_and_pickup_on_every_card(self):
        status, data = self.req("/api/tasks", "POST", {"title": "API 交接", "associated_pane_id": "n-00000000000a"})
        self.assertEqual(status, 200)
        tid = data["task"]["id"]
        # No runtime runs in tests, so an associated card cannot be judged.
        self.assertEqual(data["task"]["pickup"]["state"], "unknown")

        status, data = self.req(f"/api/tasks/{tid}/handoff", "POST", {"to": ""})
        self.assertEqual(status, 400)
        status, data = self.req("/api/tasks/task-nope/handoff", "POST", {"to": "x"})
        self.assertEqual(status, 404)
        status, data = self.req(f"/api/tasks/{tid}/handoff", "POST", {"to": "審查者"})
        self.assertEqual(status, 200)
        self.assertEqual((data["from"]["status"], data["from"]["pickup"]["state"]), ("handed_off", "closed"))
        self.assertEqual((data["to"]["handed_off_from"], data["to"]["pickup"]["state"]), (tid, "unclaimed"))

        status, data = self.req("/api/tasks")
        self.assertEqual(status, 200)
        self.assertTrue(all("pickup" in t and "verification_binding" in t for t in data["tasks"]))
        status, data = self.req(f"/api/tasks/{tid}")
        self.assertEqual(data["task"]["pickup"]["state"], "closed")

    def test_missing_closure_is_a_400(self):
        status, data = self.req("/api/tasks", "POST", {"title": "x", "provenance": {"agent": "completed"}})
        self.assertEqual(status, 400)
        self.assertIn("結案理由", data["error"])
        status, data = self.req("/api/tasks", "POST", {"title": "x", "status": "agent_completed"})
        self.assertEqual((status, data["task"]["status"]), (200, "draft"))


if __name__ == "__main__":
    unittest.main()
