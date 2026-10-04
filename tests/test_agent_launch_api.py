"""R3 S0: preview and confirmation for Profile-managed Claude launches (HTTP API).

A synthetic stand-in plays the CLI. No Claude, Codex or model is started.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from unittest import mock

from sidconsole import agent_launch
from tests.test_runtimed_managed import FAKE_CLI, FAKE_CODEX_CLI
from tests.test_runtimed_s3 import ServerCase

LABELS = ("Read", "Write", "Test", "Commit", "Deploy", "Network", "Filesystem")
META = ("level", "note", "source_version", "settings_digest", "path_scope", "evidence_refs",
        "bypass", "unknown_reason")
GOOD = {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"}


class PreviewApiCase(ServerCase):
    kind = "native"

    def setUp(self):
        super().setUp()
        self.tmp = Path(os.path.realpath(self.tmp))
        self.work = self.tmp / "work"
        self.work.mkdir()
        (self.work / "fake-mode").write_text("none")
        self.binary = self.tmp / "claude"
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.286"}, encoding="utf-8")
        self.binary.chmod(0o700)
        self.pin = mock.patch("sidconsole.runtime.native._pinned_claude_binary", return_value=str(self.binary))
        self.pin.start()
        self.codex_binary = self.tmp / "codex"
        self.codex_binary.write_text(FAKE_CODEX_CLI % {"py": sys.executable}, encoding="utf-8")
        self.codex_binary.chmod(0o700)
        self.codex_pin = mock.patch("sidconsole.runtime.native._pinned_codex_binary",
                                    return_value=str(self.codex_binary))
        self.codex_pin.start()
        self.console.managed_root = self.tmp
        self.scratches: list[str] = []

    def tearDown(self):
        self.codex_pin.stop()
        self.pin.stop()
        super().tearDown()
        for p in self.scratches:
            if p.startswith("/private/tmp/sc-"):
                shutil.rmtree(p, ignore_errors=True)

    def profile(self, intents=None, tool="claude", **extra) -> str:
        body = {"name": "p-" + os.urandom(3).hex(), "model": {"tool": tool, "model_id": ""},
                "permission_intents": intents or GOOD, "enabled": True, **extra}
        st, r = self.req("POST", "/api/agent-profiles", body)
        self.assertEqual(st, 200, r)
        return r["profile"]["id"]

    def preview(self, profile_id=None, **kw):
        body = {"profile_id": profile_id or self.profile(), "workdir": str(self.work), "commit": True}
        body.update(kw)
        st, r = self.req("POST", "/api/native/agent-previews", body)
        if st == 200 and r["preview"]["canonical_paths"]["scratch"]:
            self.scratches.append(r["preview"]["canonical_paths"]["scratch"])
        return st, r

    def launch(self, preview, **kw):
        body = {"preview_id": preview["preview_id"], "expected_settings_digest": preview["settings_digest"],
                "user_confirmed": True}
        body.update(kw)
        return self.req("POST", "/api/native/agent-launches", body)

    def sessions(self):
        return self.dm_rpc("list")["result"]["sessions"]

    def dm_rpc(self, op, **kw):
        from sidconsole.runtime import daemon as d
        return d.rpc(op, base=self.home, timeout=15.0, **kw)

    def launch_dirs(self):
        root = self.home / "sessions"
        return sorted(os.listdir(root)) if root.is_dir() else []

    # ---- preview ----

    def test_preview_reports_what_will_apply_and_starts_nothing(self):
        st, r = self.preview()
        self.assertEqual(st, 200, r)
        p = r["preview"]
        self.assertTrue(p["launchable"])
        self.assertEqual(p["reasons"], [])
        self.assertRegex(p["preview_id"], r"^p-[0-9a-f]{32}$")
        self.assertEqual(p["cli"], {"binary": str(self.binary), "version": "2.1.286"})
        self.assertEqual(p["canonical_paths"]["workdir"], str(self.work))
        self.assertRegex(p["settings_digest"], r"^[0-9a-f]{64}$")
        self.assertGreater(p["expires_at"], time.time())
        self.assertEqual(tuple(p["derived_labels"]), LABELS)
        for name, label in p["derived_labels"].items():
            self.assertEqual(tuple(label), META, name)
            self.assertTrue(label["bypass"], name)
            self.assertNotEqual(label["bypass"], "無")
        labels = p["derived_labels"]
        self.assertEqual(labels["Read"]["level"], agent_launch.INTENT)
        self.assertEqual(labels["Commit"]["level"], agent_launch.UNRESTRICTED)
        self.assertEqual(labels["Deploy"]["level"], agent_launch.NOT_GRANTED)
        self.assertEqual(labels["Write"]["level"], agent_launch.PARTIAL)
        self.assertEqual(labels["Filesystem"]["path_scope"], [str(self.work), p["canonical_paths"]["scratch"]])
        if agent_launch.NETWORK_EVIDENCE:
            self.assertEqual(labels["Network"]["evidence_refs"], [agent_launch.NETWORK_EVIDENCE])
        else:  # no evidence, so it must not claim enforcement
            self.assertEqual(labels["Network"]["level"], agent_launch.UNKNOWN)
            self.assertNotEqual(labels["Network"]["unknown_reason"], "none")
        self.assertEqual(self.sessions(), [])
        blob = json.dumps(r).lower()
        for word in ("token", "credential", "password", "secret", "keychain"):
            self.assertNotIn(word, blob)

    def test_codex_preview_confirm_and_close_use_the_shared_managed_lifecycle(self):
        with mock.patch.object(agent_launch.cli_versions, "CODEX_INTERACTIVE_FLAGS_SUPPORTED", True), \
                mock.patch.object(agent_launch, "_codex_evidence_reference",
                                   return_value=".local/r3-finish-20261003/codex-acceptance.json"):
            pid = self.profile(tool="codex")
            st, r = self.preview(pid)
            self.assertEqual(st, 200, r)
            p = r["preview"]
            self.assertTrue(p["launchable"], p["reasons"])
            self.assertEqual(p["cli"], {"binary": str(self.codex_binary), "version": "0.159.2"})
            self.assertTrue(p["derived_labels"]["Write"]["bypass"].find("!") >= 0)
            self.assertEqual(p["derived_labels"]["Network"]["evidence_refs"],
                             [".local/r3-finish-20261003/codex-acceptance.json"])
            self.assertEqual(self.sessions(), [])
            st, launched = self.launch(p)
            self.assertEqual(st, 200, launched)
            session = launched["launch"]["session"]["session_id"]
            launch_file = self.work / "fake-launch.json"
            deadline = time.monotonic() + 5
            seen = None
            while time.monotonic() < deadline and seen is None:
                try:
                    seen = json.loads(launch_file.read_text())
                except (OSError, ValueError):
                    time.sleep(0.03)
            self.assertIsNotNone(seen, "Codex fake CLI did not start")
            self.assertIn("--ephemeral", seen["argv"])
            self.assertIsNone(seen["codex_home"])
            st, closed = self.req("POST", f"/api/native/sessions/{session}/close", {})
            self.assertEqual(st, 200, closed)
            self.assertTrue(closed["managed"]["cleaned"], closed)
            self.assertFalse(os.path.exists(p["canonical_paths"]["scratch"]))

    def test_codex_without_os_evidence_is_fail_closed(self):
        with mock.patch.object(agent_launch.cli_versions, "CODEX_INTERACTIVE_FLAGS_SUPPORTED", False), \
                mock.patch.object(agent_launch, "_codex_evidence_reference", return_value=None):
            st, r = self.preview(self.profile(tool="codex"))
        self.assertEqual(st, 200, r)
        self.assertFalse(r["preview"]["launchable"])
        self.assertIn("codex_interactive_flags_unsupported", [x["code"] for x in r["preview"]["reasons"]])
        self.assertIn("codex_evidence_missing", [x["code"] for x in r["preview"]["reasons"]])
        self.assertEqual(r["preview"]["derived_labels"]["Network"]["level"], agent_launch.UNKNOWN)
        self.assertEqual(self.sessions(), [])

    def test_profiles_the_verified_setup_cannot_honour_are_not_launchable(self):
        cases = [
            ({"intents": {k: "unspecified" for k in GOOD}}, {}, "intent_unspecified"),
            ({"intents": dict(GOOD, write="deny")}, {}, "readonly_unverified"),
            ({"intents": dict(GOOD, deploy="allow")}, {}, "deploy_not_available"),
            ({"intents": dict(GOOD, read="deny")}, {}, "read_deny_unenforceable"),
            ({"intents": dict(GOOD, test="deny")}, {}, "test_deny_unenforceable"),
            ({"tool": "shared"}, {}, "tool_not_launchable"),
            ({}, {"commit": False}, "commit_not_enforceable"),
            ({}, {"network": {"enabled": True, "approved_domains": ["example.com"]}}, "network_not_available"),
            ({"enabled": False}, {}, "profile_disabled"),
        ]
        for prof, inputs, code in cases:
            with self.subTest(code=code, prof=prof):
                kw = dict(prof)
                pid = self.profile(kw.pop("intents", None), **kw)
                st, r = self.preview(pid, **inputs)
                self.assertEqual(st, 200, r)
                p = r["preview"]
                self.assertFalse(p["launchable"])
                self.assertIsNone(p["preview_id"])
                self.assertIn(code, [x["code"] for x in p["reasons"]])
                for label in p["derived_labels"].values():   # nothing prepared: nothing claimed
                    self.assertEqual(label["level"], agent_launch.UNKNOWN)
        self.assertEqual(self.launch_dirs(), [])
        self.assertEqual(self.sessions(), [])

    def test_wrong_cli_version_is_not_launchable(self):
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.287"}, encoding="utf-8")
        st, r = self.preview()
        self.assertEqual(st, 200, r)
        self.assertFalse(r["preview"]["launchable"])
        self.assertIn("cli_version_mismatch", [x["code"] for x in r["preview"]["reasons"]])
        self.assertEqual(self.launch_dirs(), [])

    def test_preview_rejects_raw_launch_fields_and_bad_targets(self):
        pid = self.profile()
        for extra in ({"argv": ["/bin/sh"]}, {"env": {"A": "b"}}, {"settings": {}}, {"credentials": "x"}):
            with self.subTest(extra=list(extra)):
                st, _ = self.preview(pid, **extra)
                self.assertEqual(st, 400)
        self.assertEqual(self.preview(pid, workdir="/usr")[0], 400)           # outside the allowed root
        self.assertEqual(self.preview(pid, workdir="relative")[0], 400)
        self.assertEqual(self.preview("prof-does-not-exist")[0], 404)
        self.assertEqual(self.preview(pid, tool="shared")[0], 400)
        self.assertEqual(self.preview(pid, tool="codex")[0], 400)            # does not match the Profile
        self.assertEqual(self.launch_dirs(), [])

    # ---- confirm ----

    def test_confirm_launches_once_and_replay_is_refused(self):
        p = self.preview()[1]["preview"]
        st, r = self.launch(p, cols=100, rows=30)
        self.assertEqual(st, 200, r)
        launch = r["launch"]
        self.assertEqual(launch["state"], "profile_managed")
        self.assertEqual(launch["session"]["managed"], launch["launch_id"])
        self.assertEqual((launch["session"]["cols"], launch["session"]["rows"]), (100, 30))
        st2, r2 = self.launch(p)
        self.assertIn(st2, (404, 409), r2)
        self.assertEqual(len(self.sessions()), 1)
        closed = self.dm_rpc("close", session_id=launch["session"]["session_id"])
        self.assertTrue(closed["result"]["managed"]["cleaned"])
        self.assertEqual(self.launch_dirs(), [])

    def test_http_close_reports_the_managed_cleanup(self):
        p = self.preview()[1]["preview"]
        sid = self.launch(p)[1]["launch"]["session"]["session_id"]
        st, r = self.req("POST", f"/api/native/sessions/{sid}/close", {})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["closed"], sid)
        self.assertTrue(r["managed"]["cleaned"], r)
        self.assertEqual(self.launch_dirs(), [])
        self.assertFalse(os.path.exists(p["canonical_paths"]["scratch"]))

    def test_http_close_of_a_plain_session_has_no_managed_field(self):
        st, r = self.req("POST", "/api/native/sessions", {"argv": ["/bin/sh", "-c", "sleep 30"],
                                                           "cwd": str(Path.home())})
        st, r = self.req("POST", f"/api/native/sessions/{r['session']['session_id']}/close", {})
        self.assertEqual(st, 200, r)
        self.assertNotIn("managed", r)

    def test_two_simultaneous_confirms_start_exactly_one_session(self):
        p = self.preview()[1]["preview"]
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.launch(p))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(sorted(st for st, _ in results).count(200), 1, results)
        self.assertEqual(len(self.sessions()), 1)
        self.dm_rpc("close", session_id=self.sessions()[0]["session_id"])

    def test_confirmation_is_required_and_does_not_burn_the_preview(self):
        p = self.preview()[1]["preview"]
        for bad in (False, "yes", None, 1):
            self.assertEqual(self.launch(p, user_confirmed=bad)[0], 400)
        self.assertEqual(self.sessions(), [])
        st, r = self.launch(p)
        self.assertEqual(st, 200, r)
        self.dm_rpc("close", session_id=r["launch"]["session"]["session_id"])

    def test_wrong_settings_digest_needs_a_new_preview(self):
        p = self.preview()[1]["preview"]
        st, r = self.launch(p, expected_settings_digest="0" * 64)
        self.assertEqual((st, r["code"]), (409, "settings_drift"))
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.launch_dirs(), [])                      # the prepared state is removed
        self.assertFalse(os.path.exists(p["canonical_paths"]["scratch"]))
        self.assertIn(self.launch(p)[0], (404, 409))                  # and the preview is gone

    def test_profile_changed_after_preview_needs_a_new_preview(self):
        pid = self.profile()
        p = self.preview(pid)[1]["preview"]
        st, r = self.req("POST", f"/api/agent-profiles/{pid}",
                         {"name": "renamed", "model": {"tool": "claude", "model_id": ""},
                          "permission_intents": GOOD, "enabled": True})
        self.assertEqual(st, 200, r)
        st, r = self.launch(p)
        self.assertEqual((st, r["code"]), (409, "profile_drift"))
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.launch_dirs(), [])

    def test_settings_or_cli_changed_after_preview_is_refused_by_revalidation(self):
        for change in ("settings", "cli"):
            with self.subTest(change=change):
                p = self.preview()[1]["preview"]
                if change == "settings":
                    ldir = self.home / "sessions" / self.launch_dirs()[0]
                    data = json.loads((ldir / "settings.json").read_text())
                    data["sandbox"]["enabled"] = False
                    (ldir / "settings.json").write_text(json.dumps(data))
                else:
                    self.binary.write_text(self.binary.read_text() + "# changed\n")
                st, r = self.launch(p)
                self.assertEqual(st, 409, r)
                self.assertEqual(self.sessions(), [])
                self.assertFalse((self.work / "fake-launch.json").exists())
                shutil.rmtree(self.home / "sessions", ignore_errors=True)

    def test_expired_preview_is_refused_and_its_state_removed(self):
        self.console.previews()._ttl = 0.2
        p = self.preview()[1]["preview"]
        time.sleep(0.4)
        st, r = self.launch(p)
        self.assertEqual((st, r["code"]), (410, "preview_expired"))
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.launch_dirs(), [])
        self.assertFalse(os.path.exists(p["canonical_paths"]["scratch"]))

    def test_new_preview_sweeps_expired_ones(self):
        self.console.previews()._ttl = 0.2
        old = self.preview()[1]["preview"]
        time.sleep(0.4)
        self.console.previews()._ttl = 300
        self.preview()
        self.assertEqual(len(self.launch_dirs()), 1)
        self.assertFalse(os.path.exists(old["canonical_paths"]["scratch"]))

    def test_daemon_offline_answers_503_and_leaves_no_state(self):
        p = self.preview()[1]["preview"]
        self.dm.stop()
        self.dthread.join(5)
        self.dm.close()
        self.dm = None
        st, r = self.launch(p)
        self.assertEqual((st, r["code"]), (503, "runtime_unavailable"), r)
        self.assertEqual(self.launch_dirs(), [])
        self.assertFalse(os.path.exists(p["canonical_paths"]["scratch"]))
        self.assertEqual(self.console.previews()._previews, {})

    def test_unexpected_intent_value_is_refused_by_the_whitelist(self):
        profile = {"id": "x", "enabled": True, "model": {"tool": "claude"},
                   "permission_intents": {"read": "allow", "write": "allow", "test": "restricted", "deploy": "deny"}}
        codes = [b["code"] for b in agent_launch.launch_blockers(
            profile, True, {"enabled": False, "approved_domains": []})]
        self.assertEqual(codes, ["intents_not_supported"])
        good = dict(profile, permission_intents=dict(agent_launch.VERIFIED_INTENTS))
        self.assertEqual(agent_launch.launch_blockers(good, True, {"enabled": False, "approved_domains": []}), [])

    def test_launch_rejects_raw_fields_and_unknown_preview(self):
        p = self.preview()[1]["preview"]
        self.assertEqual(self.launch(p, argv=["/bin/sh"])[0], 400)
        self.assertEqual(self.launch(p, env={"A": "b"})[0], 400)
        self.assertEqual(self.launch({"preview_id": "p-" + "0" * 32, "settings_digest": "x"})[0], 404)
        self.assertEqual(self.sessions(), [])

    def test_raw_session_api_is_unchanged_and_unmanaged(self):
        st, r = self.req("POST", "/api/native/sessions", {"argv": ["/bin/sh", "-c", "sleep 30"],
                                                           "cwd": str(Path.home())})
        self.assertEqual(st, 200, r)
        self.assertIsNone(r["session"]["managed"])
        self.dm_rpc("close", session_id=r["session"]["session_id"])


if __name__ == "__main__":
    import unittest
    unittest.main()
