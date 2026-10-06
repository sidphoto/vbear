"""Unit tests for Phase B3 Task Card and Phase B4 Governance Foundation."""

import json
import multiprocessing
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

# Isolated test environment
_OWN_TEMP = False
if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-tasks-test-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
    _OWN_TEMP = True

os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import config as cfg
from vbear import server, tasks


def _mp_save_worker(i):
    """Module-level (picklable) worker for the cross-process lock test
    (H3): save_task() is exercised from a genuinely separate forked OS
    process, not just a thread sharing this process's in-memory lock."""
    from vbear import tasks as _tasks
    t = _tasks.save_task(None, {"title": f"mp task {i}"})
    return t["id"]


class TasksStorageTests(unittest.TestCase):
    def setUp(self):
        cfg.ensure_state_dir()
        tpath = tasks._path()
        if tpath.exists():
            tpath.unlink()

    def test_empty_tasks(self):
        self.assertEqual(tasks.list_tasks(), [])
        self.assertIsNone(tasks.get_task("nonexistent"))

    def test_create_and_get_task(self):
        data = {
            "title": "Fix Terminal Stream Leak",
            "template": "bug_fix",
            "goal": "Ensure all SSE streams abort when view is unmounted",
            "scope": ["web/app.js", "tests/frontend/terminal.cjs"],
            "out_of_scope": ["Herdr Rust backend"],
            "deliverables": ["AbortController cleanup", "node test coverage"],
            "acceptance_criteria": ["Zero orphan processes", "Tests pass"],
            "evidence": ["Node test 10/10 PASS"],
            "steps": [
                {"title": "Add AbortController", "done": True},
                "Run test suite",
            ],
            "artifacts": ["tests/frontend/terminal.cjs"],
            "associated_pane_id": "w1:pA",
        }
        saved = tasks.save_task(None, data)
        self.assertTrue(saved["id"].startswith("task-"))
        self.assertEqual(saved["title"], "Fix Terminal Stream Leak")
        self.assertEqual(saved["template"], "bug_fix")
        self.assertEqual(saved["scope"], ["web/app.js", "tests/frontend/terminal.cjs"])
        self.assertEqual(saved["associated_pane_id"], "w1:pA")
        self.assertEqual(saved["association_mode"], "tracking_only")
        self.assertIn("未注入 Context", saved["association_label"])

        # Steps normalized
        self.assertEqual(len(saved["steps"]), 2)
        self.assertTrue(saved["steps"][0]["done"])
        self.assertFalse(saved["steps"][1]["done"])

        # Fetch by ID
        fetched = tasks.get_task(saved["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], saved["title"])

    def test_strict_validation_and_id_regex(self):
        # Empty title
        with self.assertRaises(ValueError) as ctx:
            tasks.save_task("task-1", {"title": "   "})
        self.assertIn("任務標題", str(ctx.exception))

        # Invalid ID characters (path traversal attempt)
        with self.assertRaises(ValueError) as ctx:
            tasks.save_task("../../bad_id", {"title": "Bad ID"})
        self.assertIn("無效的任務識別碼", str(ctx.exception))

        # NUL byte in ID
        with self.assertRaises(ValueError):
            tasks.save_task("task\x00evil", {"title": "Nul ID"})

    def test_status_provenance_strict_verification(self):
        # No authenticated verifier exists anywhere in this console (H1):
        # provenance["verified"] must always read False, no matter what.
        # provenance["verification_asserted"] is the honestly-named
        # self-report — true only once tests passed and human approved.

        # Case 1: Agent reports completed, but tests are untested and human
        # is pending -> status must NOT assert verification, must be
        # agent_completed.
        task1 = tasks.save_task("t-prov-1", {
            "title": "Feature X",
            "provenance": {
                "agent": "completed",
                "tests": "untested",
                "human": "pending",
            },
        })
        self.assertFalse(task1["provenance"]["verified"], "verified must always be False; there is no authenticated verifier")
        self.assertFalse(task1["provenance"]["verification_asserted"], "Agent claim alone cannot assert verification")
        self.assertEqual(task1["status"], "agent_completed")

        # Case 2: Agent completed and tests passed, but human is pending
        task2 = tasks.save_task("t-prov-2", {
            "title": "Feature Y",
            "provenance": {
                "agent": "completed",
                "tests": "passed",
                "human": "pending",
            },
        })
        self.assertFalse(task2["provenance"]["verified"])
        self.assertFalse(task2["provenance"]["verification_asserted"], "Tests passed without human approval must not assert verification")
        self.assertEqual(task2["status"], "agent_completed")

        # Case 3: Tests passed AND human approved -> verification asserted,
        # but "verified" (the governed claim) still always reads False.
        task3 = tasks.save_task("t-prov-3", {
            "title": "Feature Z",
            "provenance": {
                "agent": "completed",
                "tests": "passed",
                "human": "approved",
            },
        })
        self.assertFalse(task3["provenance"]["verified"], "verified must remain False even when tests passed and human approved — there is still no authenticated verifier")
        self.assertTrue(task3["provenance"]["verification_asserted"])
        self.assertEqual(task3["status"], "verification_asserted")

    def test_tracking_only_immutable(self):
        # Attempting to forge association_mode
        task = tasks.save_task("t-track", {
            "title": "Tracking Test",
            "association_mode": "injected_context",  # Attack / forge attempt
        })
        self.assertEqual(task["association_mode"], "tracking_only", "association_mode must remain tracking_only")

    def test_update_and_delete(self):
        tasks.save_task("t-del", {"title": "To be deleted"})
        self.assertIsNotNone(tasks.get_task("t-del"))
        deleted = tasks.delete_task("t-del")
        self.assertTrue(deleted)
        self.assertIsNone(tasks.get_task("t-del"))

        # Deleting nonexistent returns False
        self.assertFalse(tasks.delete_task("t-del"))

    def test_atomic_file_permissions(self):
        tasks.save_task("t-perm", {"title": "Permissions Check"})
        tpath = tasks._path()
        mode = tpath.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, "tasks.json must be written owner-only (0600)")

    def test_templates_catalog(self):
        tmpls = tasks.get_templates()
        for key in ("bug_fix", "feature", "review", "test", "research", "refactor", "docs", "investigation", "custom"):
            self.assertIn(key, tmpls)
            self.assertIn("title", tmpls[key])
            self.assertIn("goal", tmpls[key])
            self.assertIn("scope", tmpls[key])
            self.assertIn("deliverables", tmpls[key])

    # -- H1: status/verification cannot be forged from raw client input, and
    # "verified" (the governed claim) is never derived, always False --------

    def test_h1_status_verified_cannot_be_forged(self):
        # No tests/human provenance at all, but the client asserts
        # status="verification_asserted" directly: must not be trusted.
        task = tasks.save_task("t-h1-forge", {"title": "Forge attempt", "status": "verification_asserted"})
        self.assertNotEqual(task["status"], "verification_asserted")
        self.assertEqual(task["status"], "draft")
        self.assertFalse(task["provenance"]["verified"])
        self.assertFalse(task["provenance"]["verification_asserted"])

        # Same forgery attempt, layered on top of a task that already has
        # some (insufficient) provenance progress.
        task2 = tasks.save_task("t-h1-forge-2", {
            "title": "Forge attempt 2",
            "provenance": {"agent": "completed", "tests": "failed", "human": "pending"},
            "status": "verification_asserted",
        })
        self.assertNotEqual(task2["status"], "verification_asserted")
        self.assertEqual(task2["status"], "agent_completed")
        self.assertFalse(task2["provenance"]["verified"])
        self.assertFalse(task2["provenance"]["verification_asserted"])

        # The only legitimate path to status=="verification_asserted" is
        # genuinely passing tests + human approval (no status field needed
        # at all) — and even then, "verified" itself still always reads
        # False: there is no authenticated verifier in this system.
        task3 = tasks.save_task("t-h1-legit", {
            "title": "Legit",
            "provenance": {"agent": "completed", "tests": "passed", "human": "approved"},
        })
        self.assertEqual(task3["status"], "verification_asserted")
        self.assertTrue(task3["provenance"]["verification_asserted"])
        self.assertFalse(task3["provenance"]["verified"])

        # Directly forging body["provenance"]["verified"] = True must also
        # never survive normalization — it is never read from the client at
        # all, only ever hardcoded False server-side.
        task4 = tasks.save_task("t-h1-forge-verified-field", {
            "title": "Forge verified field directly",
            "provenance": {"agent": "pending", "tests": "untested", "human": "pending", "verified": True},
        })
        self.assertFalse(task4["provenance"]["verified"], "a client-supplied provenance.verified=True must never be trusted")

    # -- H2: collision-resistant IDs, corrupt-storage quarantine -----------

    def test_h2_generated_ids_do_not_collide_under_volume(self):
        ids = set()
        for i in range(300):
            t = tasks.save_task(None, {"title": f"task {i}"})
            self.assertNotIn(t["id"], ids, "a freshly generated id must never collide with an existing task id")
            ids.add(t["id"])
        self.assertEqual(len(ids), 300)

    def test_h2_corrupt_storage_is_quarantined_not_silently_wiped(self):
        # Seed real data, then corrupt the file the way a crash/partial
        # write/disk issue might.
        tasks.save_task("t-h2-real", {"title": "Important pre-existing data"})
        tpath = tasks._path()
        tpath.write_text("{not valid json!!!", encoding="utf-8")

        with self.assertRaises(tasks.TaskStorageError):
            tasks.list_tasks()
        with self.assertRaises(tasks.TaskStorageError):
            tasks.get_task("t-h2-real")

        # Critically: a save attempted after the corruption must NOT
        # silently start from an empty store and clobber the corrupt file
        # with just the new task, permanently losing "t-h2-real".
        with self.assertRaises(tasks.TaskStorageError):
            tasks.save_task(None, {"title": "New task after corruption"})

        # The corrupt file was moved aside (preserved for recovery), not
        # deleted, and a marker blocks further reads/writes until a human
        # clears it.
        marker = tasks._corrupt_marker_path()
        self.assertTrue(marker.exists())
        quarantine_files = list(tpath.parent.glob("tasks.json.corrupt-*"))
        self.assertEqual(len(quarantine_files), 1)
        self.assertIn("not valid json", quarantine_files[0].read_text(encoding="utf-8"))

        # Explicit recovery: an operator removes the marker (and, in a real
        # recovery, restores or discards the quarantined file) — only then
        # does the store resume normal operation.
        marker.unlink()
        self.assertEqual(tasks.list_tasks(), [])  # fresh empty store, not silently populated
        tasks.save_task("t-after-recovery", {"title": "Works again"})
        self.assertIsNotNone(tasks.get_task("t-after-recovery"))

    def test_h2_non_dict_json_root_is_also_treated_as_corrupt(self):
        tpath = tasks._path()
        cfg.ensure_state_dir()
        tpath.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(tasks.TaskStorageError):
            tasks.list_tasks()
        tasks._corrupt_marker_path().unlink()

    # -- M1: explicit null must clear an association, not fall back --------

    def test_m1_explicit_null_clears_association(self):
        tasks.save_task("t-m1", {"title": "x", "associated_pane_id": "w1:pA", "associated_session_id": "sess-1"})
        t = tasks.get_task("t-m1")
        self.assertEqual(t["associated_pane_id"], "w1:pA")
        self.assertEqual(t["associated_session_id"], "sess-1")

        cleared = tasks.save_task("t-m1", {"associated_pane_id": None, "associated_session_id": None})
        self.assertIsNone(cleared["associated_pane_id"], "explicit null must clear associated_pane_id, not preserve the old value")
        self.assertIsNone(cleared["associated_session_id"])

        # Omitting the key entirely (as opposed to sending null) must still
        # preserve whatever is already there.
        tasks.save_task("t-m1", {"associated_pane_id": "w1:pB"})
        preserved = tasks.save_task("t-m1", {"title": "unrelated update"})
        self.assertEqual(preserved["associated_pane_id"], "w1:pB")

    # -- L3: a non-string / unhashable id must fail cleanly with 400-style -
    # ValueError, not crash with an unhandled TypeError from being used as a
    # dict key before validation gets a chance to reject it.

    def test_l3_non_string_id_raises_value_error_not_type_error(self):
        for bad_id in ([1, 2], {"a": 1}, 123, 1.5, True, (1, 2)):
            with self.assertRaises(ValueError, msg=f"non-string id {bad_id!r} must raise ValueError"):
                tasks.save_task(None, {"id": bad_id, "title": "x"})


class TasksAndGovernanceAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg.ensure_state_dir()
        tpath = tasks._path()
        if tpath.exists():
            tpath.unlink()

        cls.port = 18889
        cls.console = server.Console(cls.port)
        cls.console.auth_token = None  # auth has its own tests (AuthTests)
        cls.handler = server.make_handler(cls.console)
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", cls.port), cls.handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.H = {"Host": f"127.0.0.1:{cls.port}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{cls.port}"}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if _OWN_TEMP:
            shutil.rmtree(FAKE_HOME, ignore_errors=True)

    def req(self, path, method="GET", body=None, headers=None):
        h = dict(headers or self.H)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=5) as res:
                return res.status, json.loads(res.read().decode("utf-8")), res.headers
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"raw": raw}
            return err.code, parsed, err.headers

    def test_tasks_crud_lifecycle(self):
        # 1. List initially empty
        status, data, _ = self.req("/api/tasks")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        initial_count = len(data["tasks"])

        # 2. Create task
        task_payload = {
            "id": "task-api-1",
            "title": "API Test Task",
            "template": "feature",
            "goal": "Verify REST API for task cards",
            "scope": ["vbear/server.py"],
            "deliverables": ["New routes"],
            "acceptance_criteria": ["200 OK"],
            "evidence": ["test_tasks.py"],
            "provenance": {
                "agent": "in_progress",
                "tests": "untested",
                "human": "pending",
            },
        }
        status, data, _ = self.req("/api/tasks", "POST", body=task_payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["task"]["id"], "task-api-1")
        self.assertEqual(data["task"]["status"], "in_progress")

        # 3. Get single task
        status, data, _ = self.req("/api/tasks/task-api-1")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["task"]["title"], "API Test Task")

        # 4. Update task
        update_payload = {
            "title": "API Test Task Updated",
            "provenance": {
                "agent": "completed",
                "tests": "passed",
                "human": "approved",
            },
        }
        status, data, _ = self.req("/api/tasks/task-api-1", "POST", body=update_payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["task"]["title"], "API Test Task Updated")
        self.assertEqual(data["task"]["status"], "verification_asserted")
        self.assertTrue(data["task"]["provenance"]["verification_asserted"])
        self.assertFalse(data["task"]["provenance"]["verified"], "verified must always be False; there is no authenticated verifier")

        # 5. Delete task via POST action: delete
        status, data, _ = self.req("/api/tasks/task-api-1", "POST", body={"action": "delete"})
        self.assertEqual(status, 200)
        self.assertEqual(data["deleted"], "task-api-1")

        # Verify 404 after delete
        status, _, _ = self.req("/api/tasks/task-api-1")
        self.assertEqual(status, 404)

        # 6. Create another and delete via DELETE method
        self.req("/api/tasks", "POST", body={"id": "task-api-2", "title": "DELETE method task"})
        status, data, _ = self.req("/api/tasks/task-api-2", method="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(data["deleted"], "task-api-2")

    def test_delete_maps_storage_errors_to_503(self):
        from vbear import agent_profiles
        for exc in (tasks.TaskStorageError("blocked"),
                    agent_profiles.AgentProfileStorageError("blocked")):
            with mock.patch.object(tasks, "delete_task", side_effect=exc):
                status, _, _ = self.req("/api/tasks/task-x", method="DELETE")
            self.assertEqual(status, 503, type(exc).__name__)

    def test_task_templates_endpoint(self):
        status, data, _ = self.req("/api/task-templates")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("bug_fix", data["templates"])
        self.assertIn("feature", data["templates"])

    def test_governance_foundation_endpoint(self):
        status, data, _ = self.req("/api/governance")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertFalse(data["compiler_active"], "Policy compiler must NOT be active in Phase B")
        self.assertFalse(data["effective_context_enabled"], "Effective context must NOT be enabled in Phase B")
        self.assertIn("唯讀介面骨架展示", data["notice"])

        # Global skeleton checks
        g = data["global"]
        self.assertEqual(g["source_type"], "skeleton_read_only")
        self.assertIn("唯讀骨架", g["status"])
        cat_names = [c["name"] for c in g["categories"]]
        self.assertIn("Security & Secrets", cat_names)
        self.assertIn("Operations & Git", cat_names)
        self.assertIn("Evidence & Verification", cat_names)

        # Project contract checks
        p = data["project"]
        self.assertEqual(p["source_type"], "skeleton_read_only")
        self.assertIn("contract", p)
        self.assertIn("Python 3.13+", p["contract"]["stack"])

    def test_security_protections_on_tasks(self):
        # Missing X-VBear header
        h_no_token = {"Host": f"127.0.0.1:{self.port}"}
        status, _, _ = self.req("/api/tasks", "POST", body={"title": "Attack"}, headers=h_no_token)
        self.assertEqual(status, 403)

        # Hostile / cross-origin Origin
        h_bad_origin = {
            "Host": f"127.0.0.1:{self.port}",
            "X-VBear": "1",
            "Origin": "http://evil.com",
        }
        status, _, _ = self.req("/api/tasks", "POST", body={"title": "Attack"}, headers=h_bad_origin)
        self.assertEqual(status, 403)

    def test_l3_non_string_id_returns_400_over_http(self):
        for bad_id in ([1, 2], {"a": 1}, 123.5):
            status, data, _ = self.req("/api/tasks", "POST", body={"id": bad_id, "title": "x"})
            self.assertEqual(status, 400, f"non-string id {bad_id!r} must be a clean 400, not a 500")

    def test_h1_status_verified_cannot_be_forged_over_http(self):
        status, data, _ = self.req("/api/tasks", "POST", body={"id": "task-http-forge", "title": "x", "status": "verification_asserted"})
        self.assertEqual(status, 200)
        self.assertNotEqual(data["task"]["status"], "verification_asserted")
        self.assertFalse(data["task"]["provenance"]["verification_asserted"])
        self.assertFalse(data["task"]["provenance"]["verified"])

    def test_m1_explicit_null_clears_association_over_http(self):
        self.req("/api/tasks", "POST", body={"id": "task-http-assoc", "title": "x", "associated_pane_id": "w1:pA"})
        status, data, _ = self.req("/api/tasks/task-http-assoc", "POST", body={"associated_pane_id": None})
        self.assertEqual(status, 200)
        self.assertIsNone(data["task"]["associated_pane_id"])

    def test_h2_corrupt_storage_surfaces_as_503_not_500_or_silent_wipe(self):
        self.req("/api/tasks", "POST", body={"id": "task-before-corrupt", "title": "Must survive"})
        tpath = tasks._path()
        tpath.write_text("{broken", encoding="utf-8")
        try:
            status, data, _ = self.req("/api/tasks", "POST", body={"title": "after corrupt"})
            self.assertEqual(status, 503, "a corrupt store must surface as 503, not a bare 500 or a silent success that wiped prior data")
            status2, _, _ = self.req("/api/tasks")
            self.assertEqual(status2, 503)
        finally:
            tasks._corrupt_marker_path().unlink(missing_ok=True)
            for f in tpath.parent.glob("tasks.json.corrupt-*"):
                f.unlink(missing_ok=True)
            if tpath.exists():
                tpath.unlink()


class TasksConcurrencyAndFilesystemSafetyTests(unittest.TestCase):
    """H2: concurrent writers must not corrupt storage or silently lose
    each other's tasks, and every generated id must stay unique under
    concurrent creation."""

    def setUp(self):
        cfg.ensure_state_dir()
        tpath = tasks._path()
        if tpath.exists():
            tpath.unlink()
        marker = tasks._corrupt_marker_path()
        if marker.exists():
            marker.unlink()

    def test_concurrent_creates_all_persist_with_unique_ids(self):
        n_threads = 12
        created_ids = []
        lock = threading.Lock()
        errors = []

        def worker(i):
            try:
                t = tasks.save_task(None, {"title": f"concurrent task {i}"})
                with lock:
                    created_ids.append(t["id"])
            except Exception as exc:  # noqa: BLE001 - captured for the assertion below
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"concurrent save_task calls must not raise: {errors}")
        self.assertEqual(len(created_ids), n_threads)
        self.assertEqual(len(set(created_ids)), n_threads, "every concurrently-created task must get a unique id, none silently overwritten")

        all_tasks = tasks.list_tasks()
        self.assertEqual(len(all_tasks), n_threads, "the storage file must end up containing every concurrently-created task, none lost to a lost-update race")

        # The file itself must still be valid, atomically-written JSON.
        raw = tasks._path().read_text(encoding="utf-8")
        parsed = json.loads(raw)
        self.assertEqual(len(parsed), n_threads)

    def test_concurrent_update_of_the_same_task_never_corrupts_the_file(self):
        tasks.save_task("t-hot", {"title": "shared"})
        errors = []

        def worker(i):
            try:
                tasks.save_task("t-hot", {"provenance": {"agent": "in_progress" if i % 2 else "blocked"}})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        raw = tasks._path().read_text(encoding="utf-8")
        parsed = json.loads(raw)  # must still be well-formed JSON, no interleaved partial writes
        self.assertIn("t-hot", parsed)
        self.assertEqual(parsed["t-hot"]["provenance"]["agent"], tasks.get_task("t-hot")["provenance"]["agent"])


class TasksCrossProcessLockTests(unittest.TestCase):
    """M2/H3: save_task() must serialize across separate OS processes, not
    just threads sharing this process's in-memory lock — the old
    threading.Lock-only implementation could not see a second `vbear`
    invocation (e.g. a CLI scan running alongside the server) racing the
    same read-modify-write and silently discarding the loser's write."""

    def setUp(self):
        cfg.ensure_state_dir()
        tpath = tasks._path()
        if tpath.exists():
            tpath.unlink()
        marker = tasks._corrupt_marker_path()
        if marker.exists():
            marker.unlink()
        lockp = tasks._lock_path()
        if lockp.exists():
            lockp.unlink()

    def test_concurrent_creates_across_separate_processes_are_not_lost(self):
        n = 24
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(processes=8) as pool:
            ids = pool.map(_mp_save_worker, range(n))

        self.assertEqual(len(ids), n)
        self.assertEqual(
            len(set(ids)), n,
            "every concurrently-created task across separate processes must get a unique id, none silently overwritten"
        )

        all_tasks = tasks.list_tasks()
        self.assertEqual(
            len(all_tasks), n,
            "the storage file must end up containing every task created by every process, none lost to a cross-process lost-update race"
        )

        raw = tasks._path().read_text(encoding="utf-8")
        parsed = json.loads(raw)
        self.assertEqual(len(parsed), n)


class TasksFailClosedTests(unittest.TestCase):
    """H2/M2: a non-missing read failure, or an on-disk entry that doesn't
    match this module's own schema, must never be silently treated as an
    empty store or silently dropped — either would let the very next
    save_task() silently overwrite real data it never actually read."""

    def setUp(self):
        cfg.ensure_state_dir()
        tpath = tasks._path()
        if tpath.exists() or tpath.is_symlink():
            tpath.unlink()
        marker = tasks._corrupt_marker_path()
        if marker.exists():
            marker.unlink()

    def tearDown(self):
        tpath = tasks._path()
        if tpath.exists() or tpath.is_symlink():
            try:
                tpath.chmod(0o600)
            except OSError:
                pass
            tpath.unlink()
        marker = tasks._corrupt_marker_path()
        if marker.exists():
            marker.unlink()
        for f in tpath.parent.glob("tasks.json.corrupt-*"):
            f.unlink(missing_ok=True)
        elsewhere = tpath.parent / "elsewhere.json"
        if elsewhere.exists():
            elsewhere.unlink()

    def test_malformed_entry_fails_closed_and_is_quarantined_not_dropped(self):
        tasks.save_task("t-real", {"title": "Important pre-existing data"})
        tpath = tasks._path()
        data = json.loads(tpath.read_text(encoding="utf-8"))
        # Inject a structurally invalid entry the way disk corruption or a
        # bad manual edit might: right shape at the top level (a dict
        # keyed by task id), wrong shape inside.
        data["t-broken"] = {
            "id": "t-broken", "title": "ok title",
            "provenance": {"agent": "not-a-real-status", "tests": "untested", "human": "pending"},
        }
        tpath.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaises(tasks.TaskStorageError):
            tasks.list_tasks()
        with self.assertRaises(tasks.TaskStorageError):
            tasks.get_task("t-real")
        # Critically: a save attempted after this must NOT silently start
        # from an empty store and clobber the file with just the new task,
        # permanently losing "t-real" the way silently dropping "t-broken"
        # from load_all()'s result used to risk.
        with self.assertRaises(tasks.TaskStorageError):
            tasks.save_task(None, {"title": "must not get through"})

        marker = tasks._corrupt_marker_path()
        self.assertTrue(marker.exists())
        quarantine_files = list(tpath.parent.glob("tasks.json.corrupt-*"))
        self.assertEqual(len(quarantine_files), 1)
        self.assertIn(
            "t-real", quarantine_files[0].read_text(encoding="utf-8"),
            "the quarantined file must preserve the original data, never delete it"
        )

        # Explicit human recovery clears the block.
        marker.unlink()
        self.assertEqual(tasks.list_tasks(), [])  # fresh empty store, not silently populated
        tasks.save_task("t-after-recovery", {"title": "Works again"})
        self.assertIsNotNone(tasks.get_task("t-after-recovery"))

    def test_marker_write_failure_leaves_corrupt_file_in_place_and_never_swallows(self):
        # Corrupt the store the way a crash/partial write might.
        tpath = tasks._path()
        cfg.ensure_state_dir()
        tpath.write_text("{not valid json!!!", encoding="utf-8")

        # Force the marker write itself to fail (e.g. disk full/permission
        # error). The marker is written *before* the quarantine move, so a
        # marker failure must leave the corrupt file entirely untouched —
        # never "moved away with no marker", which is byte-for-byte
        # indistinguishable from a normal empty store and would let the very
        # next save_task() overwrite the lost data. The error must surface,
        # never be swallowed.
        with mock.patch.object(tasks, "_write_marker", side_effect=OSError("disk full (simulated)")):
            with self.assertRaises(tasks.TaskStorageError):
                tasks.list_tasks()

        marker = tasks._corrupt_marker_path()
        self.assertFalse(marker.exists(), "a failed marker write must not leave a marker behind")
        self.assertTrue(tpath.exists(), "the corrupt source must stay at its original path, not go missing")
        self.assertIn("not valid json", tpath.read_text(encoding="utf-8"))
        self.assertEqual(
            list(tpath.parent.glob("tasks.json.corrupt-*")), [],
            "nothing may be moved aside until the marker that blocks writes is durably on disk",
        )

        # And the store must still be blocked meanwhile: a save attempted
        # while the marker could not be written must not start from an empty
        # store and clobber the corrupt (but recoverable) bytes.
        with self.assertRaises(tasks.TaskStorageError):
            with mock.patch.object(tasks, "_write_marker", side_effect=OSError("disk full (simulated)")):
                tasks.save_task(None, {"title": "must not get through"})
        self.assertIn("not valid json", tpath.read_text(encoding="utf-8"))

        # Retrying now that the marker write works again must still detect
        # the same corruption and complete the quarantine — proving the
        # failed attempt left the store in a state that can still recover.
        with self.assertRaises(tasks.TaskStorageError):
            tasks.list_tasks()
        self.assertTrue(marker.exists())
        quarantine_files = list(tpath.parent.glob("tasks.json.corrupt-*"))
        self.assertEqual(len(quarantine_files), 1)

    def test_quarantine_move_failure_still_leaves_the_store_blocked(self):
        """The mirror case: the marker lands but the move afterwards fails.

        Because the marker is installed first, this is the benign ordering —
        the corrupt bytes simply stay at their original path and every
        subsequent read and write is blocked by the marker that is already
        on disk. What must never happen is the store quietly reverting to
        "looks like a fresh empty store".
        """
        tpath = tasks._path()
        cfg.ensure_state_dir()
        tpath.write_text('{"broken": ', encoding="utf-8")

        real_rename = Path.rename

        def fail_quarantine_move(self, target):
            if ".corrupt-" in str(target):
                raise OSError("cross-device link (simulated)")
            return real_rename(self, target)

        with mock.patch.object(Path, "rename", fail_quarantine_move):
            with self.assertRaises(tasks.TaskStorageError):
                tasks.list_tasks()

        marker = tasks._corrupt_marker_path()
        self.assertTrue(marker.exists(), "the marker must be durable before the move is attempted")
        self.assertTrue(tpath.exists(), "a failed move must leave the corrupt bytes where they are")
        self.assertIn("broken", tpath.read_text(encoding="utf-8"))

        # Blocked for reads and writes alike until a human clears the marker.
        with self.assertRaises(tasks.TaskStorageError):
            tasks.list_tasks()
        with self.assertRaises(tasks.TaskStorageError):
            tasks.save_task(None, {"title": "must not get through"})
        self.assertIn("broken", tpath.read_text(encoding="utf-8"))

        # The marker names where the file actually is, so recovery is possible.
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(recorded["quarantine_file"], str(tpath))

    def test_directory_fsync_failure_is_not_mistaken_for_a_failed_move(self):
        """A durability-hardening fsync must never be reported as a failure
        of the operation it follows.

        The directory fsyncs exist so a power cut cannot lose the marker's
        or the quarantine's directory entry. If one of them shared a `try`
        with the rename it follows, an fsync error would be caught by the
        move-failure handler, which rewrites the marker to claim the corrupt
        file is still at its original path and tells the operator to look
        there — while the rename has in fact already succeeded and the file
        is at the quarantine path. That is a false recovery location, so
        each fsync is a separate best-effort step.
        """
        tpath = tasks._path()
        cfg.ensure_state_dir()
        tpath.write_text("[not an object]", encoding="utf-8")

        with mock.patch.object(tasks, "_fsync_dir", side_effect=OSError("fsync refused (simulated)")):
            with self.assertRaises(tasks.TaskStorageError) as ctx:
                tasks.list_tasks()

        message = str(ctx.exception)
        self.assertNotIn("無法搬移", message, "a directory fsync failure must not be reported as a failed move")
        self.assertNotIn("無法寫入復原標記", message, "a directory fsync failure must not be reported as a failed marker write")

        # The quarantine actually happened, and the marker points at where
        # the file really is — not at its original path.
        marker = tasks._corrupt_marker_path()
        self.assertTrue(marker.exists())
        self.assertFalse(tpath.exists(), "the corrupt file really was moved aside")
        quarantine_files = list(tpath.parent.glob("tasks.json.corrupt-*"))
        self.assertEqual(len(quarantine_files), 1)

        recorded = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(
            recorded["quarantine_file"], str(quarantine_files[0]),
            "the marker must name the quarantine path the file was actually moved to"
        )
        self.assertNotEqual(
            recorded["quarantine_file"], str(tpath),
            "the marker must not claim the file is still at its original path after a successful move"
        )

        # And the store stays blocked regardless.
        with self.assertRaises(tasks.TaskStorageError):
            tasks.save_task(None, {"title": "must not get through"})

    def test_read_fails_closed_on_a_symlink_not_silently_empty(self):
        tpath = tasks._path()
        real_target = tpath.parent / "elsewhere.json"
        real_target.write_text(
            json.dumps({"t-elsewhere": {"id": "t-elsewhere", "title": "x"}}), encoding="utf-8"
        )
        tpath.symlink_to(real_target)

        with self.assertRaises(tasks.TaskStorageError):
            tasks.list_tasks()
        # Must fail closed, not silently treat the unreadable-through path
        # as an empty store and write a fresh file over/through the symlink.
        with self.assertRaises(tasks.TaskStorageError):
            tasks.save_task(None, {"title": "must not silently succeed through a symlink"})

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root bypasses file permission checks")
    def test_read_fails_closed_on_permission_denied_not_silently_empty(self):
        tasks.save_task("t-before-perm", {"title": "must survive"})
        tpath = tasks._path()
        tpath.chmod(0o000)
        try:
            # list_tasks()/get_task() go through load_all() directly, with
            # no side effect that could change the file's permissions —
            # this is the clean fail-closed check.
            with self.assertRaises(tasks.TaskStorageError):
                tasks.list_tasks()
            with self.assertRaises(tasks.TaskStorageError):
                tasks.get_task("t-before-perm")
            # save_task() is NOT re-checked with this exact 0o000 vector:
            # it goes through _cross_process_lock() first, which calls
            # cfg.ensure_state_dir() — an existing, intentional security
            # behavior (config.py's own "tighten what is already there")
            # that legitimately chmods every plain file in the state
            # directory back to 0600 before load_all() ever runs, so an
            # owner-unreadable file self-heals before save_task() can even
            # attempt to read it. That's correct self-healing, not a bug;
            # the symlink test below exercises the fail-closed save_task()
            # path instead, since ensure_state_dir() deliberately skips
            # symlinks.
        finally:
            tpath.chmod(0o600)

        # Once readable again, the original data must still be intact.
        self.assertIsNotNone(tasks.get_task("t-before-perm"))


if __name__ == "__main__":
    unittest.main()
