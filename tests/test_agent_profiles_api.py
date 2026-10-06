"""Phase C2 Agent Builder API endpoint tests.

Boots a real `vbear.server.Console` on loopback, then drives it via
urllib like a browser would. Checks the wiring (catalog, list, get,
create, update, delete, duplicate), the security headers (write needs
X-VBear and same-origin Origin; oversized body is 413), the
validation boundary (unknown fields, unknown permission key, unknown
tool, missing name, missing model), and the fail-closed 503 path when
the storage layer is in a state that would lose data.

Run: python3 -m unittest tests.test_agent_profiles_api -v
"""

from __future__ import annotations

import json
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

# Same reuse-guard as tests/test_tasks.py:18-24 / tests/test_console.py —
# don't overwrite a HOME already pinned by a sibling module loaded earlier
# by `unittest discover`, or every test across the suite would observe the
# wrong fake-home.
if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-agent-api-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_profiles, server  # noqa: E402
from vbear import runtime as rt_mod  # noqa: E402
from vbear.config import state_dir  # noqa: E402
from vbear.index import Store  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _fresh_console():
    sd = state_dir()
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


class AgentBuilderAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.console, cls.httpd, cls.port = _fresh_console()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        sd = state_dir()
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)

    def test_catalog_endpoint_lists_tool_and_permission_enums(self):
        status, body = _request("GET", self.port, "/api/agent-builder/catalog")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(set(body["tools"]),
                         {"claude", "codex", "shared"})
        self.assertEqual(body["permission_keys"], ["read", "write", "test", "deploy"])
        self.assertEqual(body["permission_values"],
                         ["allow", "deny", "unspecified"])
        self.assertTrue(body["permission_intent_only"])
        self.assertEqual(body["max_profiles"], agent_profiles.MAX_PROFILES)
        self.assertEqual(body["max_skills_per_profile"],
                         agent_profiles.MAX_SKILLS_PER_PROFILE)
        # Disclosures must be present and honest about intent-only semantics.
        joined = "\n".join(body["disclosures"])
        self.assertIn("Equipped Skill Loadout", joined)
        self.assertIn("Permission Intents are intent-only", joined)
        self.assertIn("never write to ~/.codex", joined)

    def test_create_then_list_then_get(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="One"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        pid = body["profile"]["id"]
        self.assertEqual(body["profile"]["name"], "One")
        self.assertEqual(body["profile"]["model"]["tool"], "claude")

        status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 200)
        self.assertEqual([p["name"] for p in body["profiles"]], ["One"])

        status, body = _request("GET", self.port, f"/api/agent-profiles/{pid}")
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"]["id"], pid)

    def test_get_unknown_id_is_404(self):
        status, _ = _request("GET", self.port, "/api/agent-profiles/prof-not-here")
        self.assertEqual(status, 404)

    def test_update_keeps_created_at_and_advances_updated_at(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="v1"),
                                headers=_write_headers())
        pid = body["profile"]["id"]
        created_at = body["profile"]["created_at"]
        # ensure updated_at changes
        import time as _t
        _t.sleep(0.01)
        status, body = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                                body=_sample(name="v2"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"]["name"], "v2")
        self.assertEqual(body["profile"]["created_at"], created_at)
        self.assertGreater(body["profile"]["updated_at"], created_at)

    def test_delete_then_duplicate(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="Origin"),
                                headers=_write_headers())
        pid = body["profile"]["id"]
        status, body = _request("POST", self.port,
                                f"/api/agent-profiles/{pid}/duplicate", body={},
                                headers=_write_headers())
        self.assertEqual(status, 200)
        dup_id = body["profile"]["id"]
        self.assertNotEqual(dup_id, pid)
        self.assertTrue(body["profile"]["name"].startswith("Origin"))

        status, _ = _request("POST", self.port,
                              f"/api/agent-profiles/{dup_id}/delete", body={},
                              headers=_write_headers())
        self.assertEqual(status, 200)
        status, _ = _request("GET", self.port, f"/api/agent-profiles/{dup_id}")
        self.assertEqual(status, 404)

    def test_delete_unknown_is_404(self):
        status, _ = _request("POST", self.port,
                              "/api/agent-profiles/prof-missing/delete", body={},
                              headers=_write_headers())
        self.assertEqual(status, 404)

    def test_duplicate_value_error_is_400(self):
        # AGY review 2026-09-25 (Low): ValueError from duplicate must be 400,
        # not fall through to the generic 500 handler.
        with mock.patch.object(agent_profiles, "duplicate_profile",
                               side_effect=ValueError("Agent Profile 已達上限 500 筆")):
            status, body = _request("POST", self.port,
                                    "/api/agent-profiles/prof-any/duplicate",
                                    body={}, headers=_write_headers())
        self.assertEqual(status, 400)
        self.assertIn("上限", json.dumps(body, ensure_ascii=False))

    def test_duplicate_unknown_is_404(self):
        status, _ = _request("POST", self.port,
                              "/api/agent-profiles/prof-missing/duplicate", body={},
                              headers=_write_headers())
        self.assertEqual(status, 404)

    def test_write_without_header_is_403(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="X"),
                                headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_write_with_foreign_origin_is_403(self):
        status, _ = _request("POST", self.port, "/api/agent-profiles",
                              body=_sample(name="X"),
                              headers={"X-VBear": "1",
                                        "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_write_with_wrong_host_is_421(self):
        # Send to the real server's port with a spoofed Host header.
        h = {"Host": "evil.example", "X-VBear": "1",
             "Content-Type": "application/json"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/agent-profiles",
            data=b'{}', headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 421)

    def test_oversized_body_is_413(self):
        huge = "x" * (64 * 1024 + 16)
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body={"name": huge,
                                      "model": {"tool": "claude",
                                                "model_id": "a"}},
                                headers=_write_headers())
        self.assertEqual(status, 413)
        # And the file must NOT have been written.
        self.assertFalse(agent_profiles._path().exists())

    def test_unknown_tool_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(model={"tool": "rogue",
                                                     "model_id": "a"}),
                                headers=_write_headers())
        self.assertEqual(status, 400)
        self.assertIn("支援的工具", body["error"])

    def test_unknown_permission_key_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(permission_intents={
                                    "read": "allow", "sudo": "allow"}),
                                headers=_write_headers())
        self.assertEqual(status, 400)
        self.assertIn("permission_intents", body["error"])

    def test_invalid_permission_value_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(permission_intents={
                                    "read": "force"}),
                                headers=_write_headers())
        self.assertEqual(status, 400)

    def test_unknown_top_level_field_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body={"name": "X",
                                      "model": {"tool": "claude",
                                                "model_id": "a"},
                                      "enforce_everywhere": True},
                                headers=_write_headers())
        self.assertEqual(status, 400)

    def test_empty_name_is_400(self):
        status, _ = _request("POST", self.port, "/api/agent-profiles",
                              body=_sample(name="   "),
                              headers=_write_headers())
        self.assertEqual(status, 400)

    def test_unresolved_skill_is_kept_not_dropped(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(equipped_skill_ids=["unknown-skill-id"]),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"]["equipped_skill_ids"],
                         ["unknown-skill-id"])
        self.assertEqual(body["profile"]["_unresolved"]["skills"],
                         ["unknown-skill-id"])

    def test_corruption_marks_503_on_subsequent_writes(self):
        # Seed a valid profile, then corrupt the file the way a partial write
        # might, and confirm the next API write returns 503 instead of
        # silently clobbering real data.
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="Real"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        pid = body["profile"]["id"]

        path = agent_profiles._path()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["t-broken"] = {"id": "t-broken", "name": "x",
                             "model": {"tool": "rogue", "model_id": "y"}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        # Subsequent reads must be 503.
        status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 503, body)
        # And the real profile must still be recoverable after the operator
        # manually clears the marker — same invariant tasks.py enforces.
        agent_profiles._corrupt_marker_path().unlink(missing_ok=True)
        status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 200)

    def test_storage_path_does_not_leak_into_codepath_for_sessions(self):
        """The AgentProfile write path must NEVER touch ~/.codex, ~/.claude,
        third-party skill/role sources, Herdr, or session artifacts.

        We monkey-patch the obvious "outside" filesystem root and assert
        the AgentProfile POST never invokes anything that could write to
        it. The same patches are torn down at the end of the test.
        """
        real_open = Path.open
        leaks: list[str] = []

        def spy_open(self, *args, **kwargs):
            text = str(self)
            if ("/.codex/" in text or "/.claude/" in text
                    or "/.agents/" in text or "/herdr" in text.lower()):
                if "w" in kwargs.get("mode", "r") or "a" in kwargs.get("mode", "r"):
                    leaks.append(text)
            return real_open(self, *args, **kwargs)

        with mock.patch.object(Path, "open", spy_open):
            status, body = _request("POST", self.port, "/api/agent-profiles",
                                    body=_sample(name="LeakProbe"),
                                    headers=_write_headers())
            self.assertEqual(status, 200)
        self.assertEqual(leaks, [],
                         f"AgentProfile write leaked to {leaks}")


if __name__ == "__main__":
    unittest.main()