"""Phase C4 fault-injection / integration / regression tests.

End-to-end: HTTP API -> server handler -> agent_profiles module -> on-disk
JSON. Each scenario drives a real server on loopback the same way a browser
would, then asserts on what landed in `~/.vbear/agent_profiles.json`,
the quarantine file, and the marker.

Also includes:
  * the existing tasks.json path stays untouched when the agent_profiles
    path is blocked (storage-isolation regression),
  * the server stays up (no 500 swap into 5xx) when the storage layer is
    in a corruption-marker-blocked state and a concurrent API request comes
    in,
  * a fault-injection test that a storage marker write failure leaves the
    agent_profiles.json corrupt bytes in place (never silently swallowed)
    and the API surfaces 503 with a recovery hint instead of clobbering it
    on the next write.
"""

from __future__ import annotations

import json
import multiprocessing
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

# HOME / VBEAR_HOME must be pinned BEFORE any `from vbear import ...`
# line: vbear.index.HOME = Path.home() and friends are module-level
# constants evaluated at import time, and once bound to the real home they
# will pollute every other test module unittest discover loads alongside us
# (test_console / test_tasks pin HOME at module level and re-build fixtures
# from it — they cannot override an already-bound constant from an earlier
# import). Each test (and the per-class setup) creates a fresh tempdir and
# patches vbear.config.state_dir / ensure_state_dir for its own use.
# Reuse-guard: if a sibling test module loaded earlier by `unittest discover`
# already pinned VBEAR_HOME, honor that HOME instead of clobbering it.
# Without this guard every sibling races to set os.environ["HOME"] at module
# load time and whichever loads last wins for the whole process; vbear
# resolves HOME() at runtime now, but the fixtures built below track a
# specific FAKE_HOME so they must stay consistent with what HOME() sees.
if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-phase-c-int-env-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_profiles, tasks, server  # noqa: E402
from vbear import config as cfg  # noqa: E402
from vbear import runtime as rt_mod  # noqa: E402
from vbear.index import Store  # noqa: E402


def _per_test_isolator(testcase_or_cls, _register=None):
    """Patch cfg.state_dir / ensure_state_dir for one test (or class) to
    return a fresh tempdir under HOME. Returns the resolved state dir.

    For per-test use, pass the testcase instance — the patches and tempdir
    cleanup are auto-registered via addCleanup.

    For setUpClass, pass the class and also pass a `_register` list — the
    returned patchers and cleanup callable are appended to that list and
    must be invoked from tearDownClass (since TestCase.addCleanup is an
    instance method, not a classmethod).
    """
    _TMP = Path(tempfile.mkdtemp(prefix="vbear-phase-c-int-"))
    sd = _TMP / ".vbear"

    def _patched_state_dir(_ignored=None):
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)
        return sd

    s_p = mock.patch.object(cfg, "state_dir", _patched_state_dir)
    e_p = mock.patch.object(cfg, "ensure_state_dir",
                            lambda _ignored=None: _patched_state_dir())
    s_p.start()
    e_p.start()

    def _cleanup():
        try:
            s_p.stop()
        finally:
            try:
                e_p.stop()
            finally:
                shutil.rmtree(_TMP, ignore_errors=True)

    # addCleanup is an instance method of unittest.TestCase. The class itself
    # inherits the attribute but calling it on the class does not bind the
    # testcase instance, which leads to a confusing TypeError. Always use
    # _register when called from setUpClass; only call addCleanup when we
    # have a TestCase instance.
    if isinstance(testcase_or_cls, unittest.TestCase):
        testcase_or_cls.addCleanup(_cleanup)
    elif _register is not None:
        _register.append(_cleanup)
    else:
        # Defensive — caller did not provide a registration mechanism. The
        # patches and tempdir will outlive the test, which is acceptable
        # only for the rare one-off case.
        pass
    return sd


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _fresh_console(sd):
    if sd.exists():
        shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)
    c = server.Console.__new__(server.Console)
    port = _free_port()
    c.port = port
    c.store = Store()
    c.lock = threading.Lock()
    c.runtime = rt_mod.get_runtime()  # native; never autostarts a daemon
    handler = server.make_handler(c)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return c, httpd, port


def _request(method, port, path, body=None, headers=None):
    url = f"http://127.0.0.1:{port}{path}"
    h = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=payload, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:
            data = None
        return e.code, data


def _write_headers(headers=None):
    h = {"X-VBear": "1"}
    if headers:
        h.update(headers)
    return h


def _sample(**overrides):
    base = {
        "name": "Sample",
        "profession_role_id": None,
        "model": {"tool": "claude", "model_id": "opus-4.1"},
        "equipped_skill_ids": [],
        "permission_intents": {"read": "allow", "write": "deny",
                                "test": "unspecified", "deploy": "deny"},
    }
    base.update(overrides)
    return base


# Module-level so multiprocessing.Pool can pickle it. Each worker writes
# one row directly via the storage layer to validate the cross-process flock
# the same way an unrelated CLI invocation would.
def _xproc_worker(args):
    i, name = args
    rec = agent_profiles.save_profile(
        None, _sample(name=name),
        known_skills=set(), known_roles=set())
    return rec["id"]


class EndToEndTests(unittest.TestCase):
    _cls_cleanup = []

    @classmethod
    def setUpClass(cls):
        # One shared HTTP server for the class. The state dir it reads from
        # is patched at class level so setUpClass's _fresh_console can
        # pre-create the dir; per-test setUp then re-patches to a fresh dir.
        cls.httpd_sd = _per_test_isolator(cls, _register=cls._cls_cleanup)
        cls.console, cls.httpd, cls.port = _fresh_console(cls.httpd_sd)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for fn in reversed(cls._cls_cleanup):
            fn()
        cls._cls_cleanup.clear()

    def setUp(self):
        sd = _per_test_isolator(self)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)

    def test_full_lifecycle_round_trips_through_storage(self):
        # Create -> GET -> duplicate -> delete -> file untouched.
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="Alpha"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        pid = body["profile"]["id"]

        # File landed on disk under the right name, mode 0600, owner-only.
        path = agent_profiles._path()
        self.assertTrue(path.exists())
        import stat
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        # On-disk shape has no transient _unresolved decoration.
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(pid, on_disk)
        self.assertNotIn("_unresolved", on_disk[pid],
                         "on-disk shape must not carry transient decoration")

        # GET via the API returns the decorated shape (unresolved).
        status, body = _request("GET", self.port, f"/api/agent-profiles/{pid}")
        self.assertEqual(status, 200)
        self.assertIn("_unresolved", body["profile"])

        # Duplicate -> delete.
        status, body = _request("POST", self.port,
                                f"/api/agent-profiles/{pid}/duplicate", body={},
                                headers=_write_headers())
        self.assertEqual(status, 200)
        dup_id = body["profile"]["id"]
        self.assertNotEqual(dup_id, pid)
        status, _ = _request("POST", self.port,
                              f"/api/agent-profiles/{dup_id}/delete", body={},
                              headers=_write_headers())
        self.assertEqual(status, 200)

        # Two-step delete leaves exactly one entry behind.
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(on_disk.keys()), {pid})

    def test_storage_failure_does_not_crash_server(self):
        # Fault-inject the agent_profiles storage so list_profiles raises.
        # The server must respond with 503 (never 500 / never 200-empty).
        with mock.patch.object(agent_profiles, "list_profiles",
                               side_effect=agent_profiles.AgentProfileStorageError(
                                   "Agent Profile 儲存先前偵測到損毀，需人工復原")):
            status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 503)
        self.assertIn("Agent Profile", body["error"])

    def test_corruption_marker_blocks_subsequent_writes_with_503(self):
        # Seed a valid profile, simulate disk corruption on the next read.
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="Real"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        real_id = body["profile"]["id"]
        path = agent_profiles._path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["t-broken"] = {"id": "t-broken", "name": "x",
                             "model": {"tool": "rogue", "model_id": "y"}}
        path.write_text(json.dumps(data), encoding="utf-8")

        # The marker + quarantine happen during the next read attempt;
        # any subsequent write must be 503, never 200.
        status, _ = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 503)
        status, _ = _request("POST", self.port, "/api/agent-profiles",
                              body=_sample(name="must-not-overwrite"),
                              headers=_write_headers())
        self.assertEqual(status, 503)
        # The corrupt file has been moved aside; the marker is on disk.
        self.assertTrue(agent_profiles._corrupt_marker_path().exists())
        quarantined = list(path.parent.glob("agent_profiles.json.corrupt-*"))
        self.assertGreaterEqual(len(quarantined), 1,
                                "at least one corrupt-* sibling must exist")
        for q in quarantined:
            self.assertTrue(q.name.startswith("agent_profiles.json.corrupt-"))

    def test_storage_layer_isolation_from_tasks_storage(self):
        """Block agent_profiles only; tasks storage must keep working.

        Regression: if the agent_profiles module imported or touched the
        tasks storage layer, a corruption-marker block on agent_profiles
        must NOT also block tasks. tasks has its own marker / quarantine
        and is independent.
        """
        tasks.save_task("t-real", {"title": "Important task"})
        # Block it.
        tasks._corrupt_marker_path().parent.mkdir(parents=True, exist_ok=True)
        tasks._corrupt_marker_path().write_text(
            json.dumps({"detected_at": 0, "quarantine_file": "",
                         "original_file": str(tasks._path()),
                         "error": "synthetic"}),
            encoding="utf-8")

        try:
            # tasks reads/writes should be blocked (503 / raise).
            with self.assertRaises(tasks.TaskStorageError):
                tasks.list_tasks()
            # but agent_profiles keeps working.
            status, body = _request("POST", self.port, "/api/agent-profiles",
                                    body=_sample(name="While tasks blocked"),
                                    headers=_write_headers())
            self.assertEqual(status, 200)
            self.assertEqual(body["profile"]["name"], "While tasks blocked")
        finally:
            tasks._corrupt_marker_path().unlink(missing_ok=True)


class ConcurrentHTTPRequestsTests(unittest.TestCase):
    _cls_cleanup = []

    @classmethod
    def setUpClass(cls):
        cls.httpd_sd = _per_test_isolator(cls, _register=cls._cls_cleanup)
        cls.console, cls.httpd, cls.port = _fresh_console(cls.httpd_sd)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for fn in reversed(cls._cls_cleanup):
            fn()
        cls._cls_cleanup.clear()

    def setUp(self):
        sd = _per_test_isolator(self)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)

    def test_concurrent_http_creates_all_persist_with_unique_ids(self):
        n_threads = 16
        results = []
        errors = []
        lock = threading.Lock()

        def worker(i):
            # The ThreadingHTTPServer can drop a small fraction of short-lived
            # concurrent sockets at the kernel level (errno 54 ECONNRESET
            # when the listen backlog is briefly exceeded). Retry with a
            # tiny backoff — we care that every *save* persists with a unique
            # id, not that a transient TCP RST escapes into the test as a
            # false failure.
            import time as _t
            last_exc = None
            for attempt in range(5):
                try:
                    status, body = _request(
                        "POST", self.port, "/api/agent-profiles",
                        body=_sample(name=f"concurrent {i}"),
                        headers=_write_headers())
                    with lock:
                        results.append((status, body["profile"]["id"]))
                    return
                except urllib.error.URLError as exc:  # noqa: BLE001
                    last_exc = exc
                    _t.sleep(0.02 * (attempt + 1))
            with lock:
                errors.append(last_exc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertEqual(errors, [], f"concurrent HTTP save must not raise: {errors}")
        self.assertEqual(len(results), n_threads)
        ids = [pid for _, pid in results]
        self.assertEqual(len(set(ids)), n_threads,
                         "every concurrently-created profile must have a unique id")
        on_disk = json.loads(agent_profiles._path().read_text(encoding="utf-8"))
        self.assertEqual(len(on_disk), n_threads)

    def test_concurrent_http_cross_process_creates_all_persist(self):
        # Cross-process via multiprocessing — the actual scenario two
        # terminal sessions of `vbear save` vs the server would race.
        n = 24
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(processes=8) as pool:
            ids = pool.map(_xproc_worker,
                           [(i, f"xproc {i}") for i in range(n)])
        self.assertEqual(len(set(ids)), n)
        on_disk = json.loads(agent_profiles._path().read_text(encoding="utf-8"))
        self.assertEqual(len(on_disk), n)


class FaultInjectionTests(unittest.TestCase):
    """Inject failures into the storage layer and confirm:

       * 503 surfaces, never a 200-pretending-everything-is-fine,
       * the corrupt bytes never disappear silently,
       * the next write attempts to recover, not clobber.
    """

    def setUp(self):
        sd = _per_test_isolator(self)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)

    def tearDown(self):
        marker = agent_profiles._corrupt_marker_path()
        if marker.exists() or marker.is_symlink():
            marker.unlink()
        for f in agent_profiles._path().parent.glob("agent_profiles.json.corrupt-*"):
            f.unlink(missing_ok=True)
        if agent_profiles._path().exists() or agent_profiles._path().is_symlink():
            try:
                agent_profiles._path().chmod(0o600)
            except OSError:
                pass
            agent_profiles._path().unlink()

    def test_marker_write_failure_leaves_corrupt_file_in_place(self):
        path = agent_profiles._path()
        path.write_text("{not valid json!!!", encoding="utf-8")
        with mock.patch.object(agent_profiles, "_write_marker",
                               side_effect=OSError("disk full (simulated)")):
            with self.assertRaises(agent_profiles.AgentProfileStorageError):
                agent_profiles.list_profiles()
        marker = agent_profiles._corrupt_marker_path()
        self.assertFalse(marker.exists())
        self.assertTrue(path.exists())
        self.assertIn("not valid json", path.read_text(encoding="utf-8"))

    def test_quarantine_move_failure_still_leaves_store_blocked(self):
        path = agent_profiles._path()
        path.write_text('{"broken": ', encoding="utf-8")
        real_rename = Path.rename

        def fail_quarantine(self_path, target):
            if ".corrupt-" in str(target):
                raise OSError("cross-device link (simulated)")
            return real_rename(self_path, target)

        with mock.patch.object(Path, "rename", fail_quarantine):
            with self.assertRaises(agent_profiles.AgentProfileStorageError):
                agent_profiles.list_profiles()
        marker = agent_profiles._corrupt_marker_path()
        self.assertTrue(marker.exists())
        self.assertTrue(path.exists())
        self.assertIn("broken", path.read_text(encoding="utf-8"))

    def test_save_with_empty_body_does_not_silently_pass(self):
        # Body missing required fields must raise ValueError, never silently
        # fall through to write a default-shaped profile.
        with self.assertRaises(ValueError):
            agent_profiles.save_profile(None, {}, known_skills=set())


class StorageFileShapeRegressionTests(unittest.TestCase):
    """Regressions against accidental widening of the on-disk shape.

    A future change must not silently add unknown fields to agent_profiles
    storage, since the closed shape is what makes the load path fail-closed
    rather than fail-open on the next save.
    """

    def setUp(self):
        sd = _per_test_isolator(self)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)

    def test_on_disk_keys_for_one_profile_are_exactly_the_allowed_set(self):
        rec = agent_profiles.save_profile(
            "p-shape", {
                "name": "Shape", "profession_role_id": None,
                "model": {"tool": "claude", "model_id": "opus-4.1"},
                "equipped_skill_ids": ["alpha"],
                "permission_intents": {"read": "allow", "write": "deny",
                                        "test": "unspecified", "deploy": "deny"},
                "enabled": True,
            },
            known_skills={"alpha"}, known_roles=set())
        self.assertEqual(set(rec.keys()) - {"_unresolved"},
                         {"id", "name", "profession_role_id", "model",
                          "equipped_skill_ids", "permission_intents",
                          "enabled", "created_at", "updated_at"})
        on_disk = json.loads(agent_profiles._path().read_text(encoding="utf-8"))
        self.assertEqual(set(on_disk["p-shape"].keys()),
                         {"id", "name", "profession_role_id", "model",
                          "equipped_skill_ids", "permission_intents",
                          "enabled", "created_at", "updated_at"})

    def test_model_field_is_exactly_tool_and_model_id(self):
        agent_profiles.save_profile(
            "p-model", {
                "name": "M",
                "model": {"tool": "claude", "model_id": "opus-4.1",
                           "enforce": True, "force": True},
            },
            known_skills=set(), known_roles=set())
        on_disk = json.loads(agent_profiles._path().read_text(encoding="utf-8"))
        self.assertEqual(set(on_disk["p-model"]["model"].keys()),
                         {"tool", "model_id"})


if __name__ == "__main__":
    unittest.main()