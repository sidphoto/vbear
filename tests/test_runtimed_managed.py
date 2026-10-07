"""R3 S2: managed Claude sessions in the runtime daemon (``open_managed``).

A synthetic stand-in plays the CLI: like Claude Code's Bash tool it starts a
child in its own process group. No Claude, Codex or model is started.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear.runtime import agent_sessions as a
from vbear.runtime import cli_versions
from vbear.runtime import daemon as d
from vbear.runtime.native import NativeRuntime, NativeRuntimeError

CLOSE_TIMEOUT = 15.0

FAKE_CLI = r'''#!%(py)s
import json, os, signal, subprocess, sys, time
if "--version" in sys.argv:
    print("%(version)s (Claude Code)")
    raise SystemExit(0)
mode = open("fake-mode").read().strip() if os.path.exists("fake-mode") else "tool"
tool = ""
if mode == "tool":
    tool = "import time; time.sleep(600)"
elif mode == "stubborn":
    # Signals are ignored before the marker is written, so the test can wait for it.
    tool = ("import signal,time; [signal.signal(s, signal.SIG_IGN) for s in (signal.SIGHUP, signal.SIGTERM)]; "
            "open('stubborn-ready','w').close(); time.sleep(600)")
pid = None
if mode == "orphan":
    # A command that leaves a background process behind and returns.
    pid = subprocess.Popen(["/bin/sh", "-c", "sleep 600 & echo $! > orphan.pid; sleep 2"],
                           start_new_session=True).pid
if tool:
    # Like Claude Code's Bash tool: the command runs in its own process group.
    pid = subprocess.Popen([sys.executable, "-c", tool], start_new_session=True).pid
with open("fake-launch.json", "w") as f:
    json.dump({"argv": sys.argv, "cwd": os.getcwd(), "tool_pid": pid, "pid": os.getpid(),
               "tmpdir_env": os.environ.get("CLAUDE_CODE_TMPDIR"),
               "autoupdater_env": os.environ.get("DISABLE_AUTOUPDATER"),
               "env_names": sorted(os.environ)}, f)
time.sleep(600)
'''

FAKE_CODEX_CLI = r'''#!%(py)s
import json, os, subprocess, sys, time
if "--version" in sys.argv:
    print("codex-cli 0.159.2")
    raise SystemExit(0)
mode = open("fake-mode").read().strip() if os.path.exists("fake-mode") else "tool"
pid = None
if mode == "tool":
    pid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True).pid
with open("fake-launch.json", "w") as f:
    json.dump({"argv": sys.argv, "cwd": os.getcwd(), "tool_pid": pid, "pid": os.getpid(),
               "home": os.environ.get("HOME"), "user": os.environ.get("USER"),
               "logname": os.environ.get("LOGNAME"), "codex_home": os.environ.get("CODEX_HOME"),
               "tmpdir": os.environ.get("TMPDIR"), "env_names": sorted(os.environ)}, f)
time.sleep(600)
'''


def gone(pid: int) -> bool:
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return r.returncode != 0 or not r.stdout.strip() or "Z" in r.stdout


class ManagedCase(unittest.TestCase):
    version = "2.1.286"

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="sidr3d-", dir="/tmp")))
        self.base = self.tmp / "st"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.binary = self.tmp / "claude"
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": self.version}, encoding="utf-8")
        self.binary.chmod(0o700)
        self.scratches: list[str] = []
        self.pids: list[int] = []
        self.logs: list[str] = []
        self.dm = d.Daemon(self.base, log=self.logs.append)
        self.dm.start()
        self.thread = threading.Thread(target=self.dm.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        for pid in self.pids:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        for p in self.scratches:
            if p.startswith("/private/tmp/sc-") and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rpc(self, op, **kw):
        return d.rpc(op, base=self.base, timeout=CLOSE_TIMEOUT, **kw)

    def prepare(self, mode="tool"):
        (self.work / "fake-mode").write_text(mode)
        launch = self.work / "fake-launch.json"
        if launch.exists():
            launch.unlink()
        m = a.prepare_claude_launch(self.base, str(self.work), cli_binary=str(self.binary),
                                    cli_version=self.version,
                                    cli_identity=a.binary_identity(str(self.binary)),
                                    allowed_root=str(self.tmp))
        self.scratches.append(m["scratch"]["path"])
        return m

    def wait_for(self, pred, timeout=8.0, msg="condition"):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = pred()
            if value:
                return value
            time.sleep(0.03)
        self.fail(f"timed out waiting for {msg}")

    def launched(self) -> dict:
        path = self.work / "fake-launch.json"

        def read():
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                return None
        info = self.wait_for(read, msg="fake CLI start")
        for key in ("pid", "tool_pid"):
            if info.get(key):
                self.pids.append(info[key])
        return info

    def open_managed(self, m, **kw):
        r = self.rpc("open_managed", launch_id=m["launch_id"], **kw)
        self.assertTrue(r["ok"], r)
        return r["result"]

    def manifest(self, m) -> dict:
        return json.loads((self.base / "sessions" / m["launch_id"] / "manifest.json").read_text())

    # ---- launch ----

    def test_daemon_builds_argv_env_and_cwd_itself(self):
        m = self.prepare()
        info = self.open_managed(m)
        self.assertEqual(info["managed"], m["launch_id"])
        self.assertEqual(info["argv"], a.claude_argv(m))
        seen = self.launched()
        self.assertEqual(seen["argv"], a.claude_argv(m))
        self.assertEqual(seen["cwd"], str(self.work))
        self.assertEqual(seen["tmpdir_env"], m["scratch"]["path"])
        self.assertEqual(seen["autoupdater_env"], "1")  # never touch the global CLI install
        self.assertFalse([n for n in seen["env_names"] if n.startswith(("ORCA_", "HERDR_"))])
        self.assertEqual(seen["pid"], info["pid"])  # trampoline exec'd in place
        after = self.wait_for(lambda: (lambda x: x if seen["tool_pid"] in [p for p, _ in x["observed"]] else None)(
            self.manifest(m)), msg="tool pid recorded in manifest")
        self.assertEqual(after["state"], "running")
        self.assertEqual(after["native_session_id"], info["session_id"])
        self.assertEqual(after["leader"]["pid"], info["pid"])
        self.rpc("close", session_id=info["session_id"])

    def test_caller_cannot_pass_argv_env_or_cwd(self):
        m = self.prepare()
        for extra in ({"argv": ["/bin/sh"]}, {"env": {"PATH": "/x"}}, {"cwd": "/"}):
            with self.subTest(extra=list(extra)):
                r = self.rpc("open_managed", launch_id=m["launch_id"], **extra)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "bad_request")
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])
        self.assertEqual(self.manifest(m)["state"], "prepared")

    def test_plain_open_still_refuses_the_tmpdir_variable(self):
        r = self.rpc("open", argv=["/bin/sh", "-c", "true"], cwd=str(self.tmp),
                     env={"CLAUDE_CODE_TMPDIR": "/tmp/x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "bad_request")

    def test_launch_id_is_single_use(self):
        m = self.prepare()
        info = self.open_managed(m)
        self.launched()
        r = self.rpc("open_managed", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "refused")
        self.assertEqual(len(self.rpc("list")["result"]["sessions"]), 1)
        self.rpc("close", session_id=info["session_id"])

    def test_bad_or_unknown_launch_id_is_refused(self):
        for bad in ["l-" + "0" * 16, "../../etc", "", 5]:
            with self.subTest(bad=bad):
                r = self.rpc("open_managed", launch_id=bad)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "refused")
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    def test_tampered_settings_refuse_launch_and_start_nothing(self):
        m = self.prepare()
        p = Path(m["settings_path"])
        data = json.loads(p.read_text())
        data["sandbox"]["enabled"] = False
        p.write_text(json.dumps(data))
        r = self.rpc("open_managed", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "refused")
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])
        self.assertFalse((self.work / "fake-launch.json").exists())

    def test_changed_binary_refuses_launch(self):
        m = self.prepare()
        self.binary.write_text(self.binary.read_text() + "# changed\n")
        r = self.rpc("open_managed", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn("drift", r["error"]["message"])
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    # ---- close and cleanup ----

    def test_close_kills_tool_in_other_process_group_and_cleans_exactly(self):
        m = self.prepare()
        info = self.open_managed(m)
        seen = self.launched()
        tool_pgid = os.getpgid(seen["tool_pid"])
        self.assertNotEqual(tool_pgid, info["pgid"])  # the reason descendant tracking exists
        self.wait_for(lambda: seen["tool_pid"] in [p for p, _ in self.manifest(m)["observed"]],
                      msg="tool observed")
        r = self.rpc("close", session_id=info["session_id"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["managed"], {"launch_id": m["launch_id"], "cleaned": True})
        self.assertTrue(gone(seen["tool_pid"]))
        self.assertTrue(gone(info["pid"]))
        self.assertFalse(os.path.exists(m["scratch"]["path"]))
        self.assertFalse((self.base / "sessions" / m["launch_id"]).exists())
        self.assertTrue((self.work / "fake-launch.json").exists())  # the work directory is untouched

    def test_stubborn_tool_is_killed_then_cleaned(self):
        m = self.prepare("stubborn")
        info = self.open_managed(m)
        seen = self.launched()
        self.wait_for(lambda: (self.work / "stubborn-ready").exists(), msg="tool ignores HUP/TERM")
        self.wait_for(lambda: seen["tool_pid"] in [p for p, _ in self.manifest(m)["observed"]],
                      msg="tool observed")
        r = self.rpc("close", session_id=info["session_id"])
        self.assertTrue(r["result"]["forced"])
        self.assertTrue(gone(seen["tool_pid"]))
        self.assertTrue(r["result"]["managed"]["cleaned"])
        self.assertFalse(os.path.exists(m["scratch"]["path"]))

    def test_background_process_left_by_a_finished_command_is_killed_and_cleaned(self):
        m = self.prepare("orphan")
        info = self.open_managed(m)
        seen = self.launched()
        orphan = int(self.wait_for(lambda: (self.work / "orphan.pid").read_text().strip()
                                   if (self.work / "orphan.pid").exists() else None, msg="orphan pid"))
        self.pids.append(orphan)
        self.wait_for(lambda: gone(seen["tool_pid"]), msg="tool shell exit")   # the shell is gone ...
        self.assertFalse(gone(orphan))                                           # ... its child is not
        r = self.rpc("close", session_id=info["session_id"])
        self.assertTrue(r["result"]["managed"]["cleaned"], r)
        self.assertTrue(gone(orphan))
        self.assertFalse(os.path.exists(m["scratch"]["path"]))

    def test_unprovable_death_retains_state_for_manual_review(self):
        m = self.prepare("none")
        info = self.open_managed(m)
        self.launched()
        with mock.patch.object(d.proctrack, "process_table",
                               side_effect=d.proctrack.ProcessTableUnavailable("no ps")):
            r = self.rpc("close", session_id=info["session_id"])
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["result"]["managed"]["cleaned"])
        self.assertTrue(os.path.isdir(m["scratch"]["path"]))
        self.assertEqual(self.manifest(m)["state"], "manual_review")

    def test_transient_table_failure_does_not_block_a_later_proven_cleanup(self):
        m = self.prepare()
        info = self.open_managed(m)
        seen = self.launched()
        sess = self.dm._sessions[info["session_id"]]
        with mock.patch.object(d.proctrack, "process_table",
                               side_effect=d.proctrack.ProcessTableUnavailable("no table")):
            self.wait_for(lambda: sess.missed_looks >= 1, msg="a failed look")
            self.assertTrue(sess.unproven)
        self.wait_for(lambda: seen["tool_pid"] in [p for p, _ in self.manifest(m)["observed"]],
                      msg="tool observed once the table is back")
        r = self.rpc("close", session_id=info["session_id"])
        self.assertTrue(r["result"]["managed"]["cleaned"], r)   # decided on a fresh, complete look
        self.assertTrue(gone(seen["tool_pid"]))
        self.assertTrue(any("unreadable" in line for line in self.logs))

    def test_daemon_shutdown_kills_and_cleans_managed_sessions(self):
        m = self.prepare()
        info = self.open_managed(m)
        seen = self.launched()
        self.wait_for(lambda: seen["tool_pid"] in [p for p, _ in self.manifest(m)["observed"]],
                      msg="tool observed")
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        self.assertTrue(gone(seen["tool_pid"]))
        self.assertTrue(gone(info["pid"]))
        self.assertFalse(os.path.exists(m["scratch"]["path"]))
        self.assertFalse((self.base / "sessions" / m["launch_id"]).exists())

    def test_running_daemon_expires_abandoned_prepared_launches(self):
        with mock.patch.object(d, "PREPARED_SWEEP", 0.2):
            self.dm._next_prepared_sweep = 0.0
            stale = self.prepare("none")
            a.update_manifest(self.base, stale["launch_id"], created=time.time() - a.PREPARED_TTL - 5)
            fresh = self.prepare("none")
            self.wait_for(lambda: not (self.base / "sessions" / stale["launch_id"]).exists(),
                          msg="stale prepared launch removed")
        self.assertFalse(os.path.exists(stale["scratch"]["path"]))
        self.assertTrue(os.path.isdir(fresh["scratch"]["path"]))
        self.assertTrue(any("expired: removed" in line for line in self.logs))

    def test_plain_sessions_are_unmanaged_and_untracked(self):
        r = self.rpc("open", argv=["/bin/sh", "-c", "sleep 30"], cwd=str(self.tmp))
        info = r["result"]
        self.assertIsNone(info["managed"])
        self.assertIsNone(self.dm._sessions[info["session_id"]].tracker)
        closed = self.rpc("close", session_id=info["session_id"])
        self.assertNotIn("managed", closed["result"])

    # ---- NativeRuntime entry ----

    def runtime(self) -> NativeRuntime:
        return NativeRuntime(self.base, autostart=False)

    def test_runtime_entry_launches_managed_session(self):
        (self.work / "fake-mode").write_text("tool")
        with mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(self.binary)):
            result = self.runtime().create_managed_claude_session(
                {"cwd": str(self.work), "cols": 100, "rows": 30}, allowed_root=str(self.tmp))
        self.scratches.append(self.wait_for(
            lambda: json.loads((self.base / "sessions" / result["launch_id"] / "manifest.json").read_text()),
            msg="manifest")["scratch"]["path"])
        self.assertEqual(result["state"], "profile_managed")
        self.assertEqual(result["boundary"]["read"], "not isolated")
        self.assertEqual(result["session"]["managed"], result["launch_id"])
        self.assertEqual((result["session"]["cols"], result["session"]["rows"]), (100, 30))
        self.launched()
        self.rpc("close", session_id=result["session"]["session_id"])

    def test_runtime_entry_launches_codex_through_shared_lifecycle(self):
        codex = self.tmp / "codex"
        codex.write_text(FAKE_CODEX_CLI % {"py": sys.executable}, encoding="utf-8")
        codex.chmod(0o700)
        (self.work / "fake-mode").write_text("tool")
        with mock.patch("vbear.runtime.native._pinned_codex_binary", return_value=str(codex)), \
                mock.patch("vbear.runtime.cli_versions.CODEX_INTERACTIVE_FLAGS_SUPPORTED", True):
            result = self.runtime().create_managed_codex_session(
                {"cwd": str(self.work), "cols": 100, "rows": 30, "commit": True},
                allowed_root=str(self.tmp))
        manifest = self.wait_for(
            lambda: json.loads((self.base / "sessions" / result["launch_id"] / "manifest.json").read_text()),
            msg="Codex manifest")
        self.scratches.append(manifest["scratch"]["path"])
        self.assertEqual(result["state"], "profile_managed")
        self.assertEqual(result["session"]["managed"], result["launch_id"])
        self.assertEqual(manifest["engine"], "codex")
        seen = self.launched()
        self.assertIn("--ignore-user-config", seen["argv"])
        self.assertIn("--ignore-rules", seen["argv"])
        self.assertIn("--ephemeral", seen["argv"])
        self.assertIn("--sandbox", seen["argv"])
        self.assertIn("sandbox_workspace_write.network_access=false", seen["argv"])
        self.assertEqual(seen["cwd"], str(self.work))
        self.assertEqual(seen["home"], str(Path.home()))
        self.assertEqual(seen["user"], os.environ.get("USER") or os.environ.get("LOGNAME"))
        self.assertEqual(seen["logname"], seen["user"])
        self.assertIsNone(seen["codex_home"], "use the existing default auth location; do not fake CODEX_HOME")
        self.assertIsNone(seen["tmpdir"], "do not make shared /tmp writable via TMPDIR")
        self.assertFalse([n for n in seen["env_names"] if n.startswith(("ORCA_", "HERDR_"))])
        closed = self.rpc("close", session_id=result["session"]["session_id"])
        self.assertTrue(closed["result"]["managed"]["cleaned"], closed)
        self.assertFalse(os.path.exists(manifest["scratch"]["path"]))

    def test_runtime_entry_refuses_other_cli_version_and_leaves_nothing(self):
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.287"}, encoding="utf-8")
        with mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(self.binary)):
            with self.assertRaises(cli_versions.VersionAssertionError) as c:
                self.runtime().create_managed_claude_session({"cwd": str(self.work)}, allowed_root=str(self.tmp))
        self.assertEqual(c.exception.code, "version_mismatch")
        # An unverified version is prepared (to learn it is unverified), then removed:
        # the direct path never starts one without a user-acknowledged preview.
        sessions = self.base / "sessions"
        self.assertEqual(sorted(sessions.iterdir()) if sessions.exists() else [], [])
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    def test_prepared_unverified_launch_needs_the_acknowledgement_at_the_last_step(self):
        """prepare + launch_prepared_agent directly (no preview) cannot start an
        unverified version unless the caller passes the acknowledgement."""
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.287"}, encoding="utf-8")
        with mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(self.binary)):
            rt = self.runtime()
            prepared = rt.prepare_managed_claude_launch({"cwd": str(self.work)}, allowed_root=str(self.tmp))
            self.assertIs(prepared["manifest"]["cli_verified"], False)
            self.assertNotIn("enforced", json.dumps(prepared["manifest"]["boundary"]))
            self.scratches.append(prepared["manifest"]["scratch"]["path"])
            with self.assertRaises(cli_versions.VersionAssertionError) as c:
                rt.launch_prepared_agent(prepared)
            self.assertEqual(c.exception.code, "unverified_not_acknowledged")
        sessions = self.base / "sessions"
        self.assertEqual(sorted(sessions.iterdir()) if sessions.exists() else [], [])  # prepared state removed
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    def test_daemon_refuses_unverified_without_a_recorded_acknowledgement(self):
        """Tampering with the in-memory manifest or calling the daemon directly does
        not help: the daemon decides from the version itself and its own state dir."""
        self.binary.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.287"}, encoding="utf-8")
        with mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(self.binary)):
            rt = self.runtime()
            # 1. Caller flips the in-memory flag to look verified.
            prepared = rt.prepare_managed_claude_launch({"cwd": str(self.work)}, allowed_root=str(self.tmp))
            self.scratches.append(prepared["manifest"]["scratch"]["path"])
            prepared["manifest"]["cli_verified"] = True
            with self.assertRaises(NativeRuntimeError) as c:
                rt.launch_prepared_agent(prepared)
            self.assertIn("unverified_not_acknowledged", str(c.exception))
            # 2. Caller goes straight to the daemon's open_managed.
            prepared = rt.prepare_managed_claude_launch({"cwd": str(self.work)}, allowed_root=str(self.tmp))
            self.scratches.append(prepared["manifest"]["scratch"]["path"])
            r = self.rpc("open_managed", launch_id=prepared["manifest"]["launch_id"])
            self.assertFalse(r["ok"])
            self.assertIn("unverified_not_acknowledged", r["error"]["message"])
        self.assertEqual(self.rpc("list")["result"]["sessions"], [])

    def test_runtime_entry_rejects_extra_spec_fields(self):
        for extra in ({"argv": ["x"]}, {"env": {}}, {"settings": "x"}):
            with self.subTest(extra=list(extra)):
                with self.assertRaises(NativeRuntimeError):
                    self.runtime().create_managed_claude_session({"cwd": str(self.work), **extra})

    def test_runtime_entry_cleans_prepared_state_when_daemon_refuses(self):
        rt = self.runtime()
        with mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(self.binary)), \
                mock.patch.object(rt, "_rpc", return_value={"ok": False, "error": {"message": "refused"}}):
            with self.assertRaises(NativeRuntimeError):
                rt.create_managed_claude_session({"cwd": str(self.work)}, allowed_root=str(self.tmp))
        self.assertEqual(list((self.base / "sessions").iterdir()), [])


class RecoveryAtStartCase(unittest.TestCase):
    def test_new_daemon_cleans_dead_launch_and_retains_live_one(self):
        tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="sidr3r-", dir="/tmp")))
        base, work = tmp / "st", tmp / "work"
        base.mkdir(mode=0o700)
        work.mkdir()
        binary = tmp / "claude"
        binary.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        binary.chmod(0o700)
        live = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
        scratches = []
        try:
            def launch(pid, start):
                m = a.prepare_claude_launch(base, str(work), cli_binary=str(binary), cli_version="2.1.286",
                                            cli_identity=a.binary_identity(str(binary)), allowed_root=str(tmp))
                scratches.append(m["scratch"]["path"])
                a.update_manifest(base, m["launch_id"], state="running", native_session_id="n-000000000000",
                                  leader={"pid": pid, "start": start, "source": d.proctrack.SOURCE}, observed=[])
                return m
            row = next(r for r in d.proctrack.process_table() if r["pid"] == live.pid)
            dead = launch(999999, "Thu Jan  1 00:00:00 1970")
            alive = launch(live.pid, row["start"])
            logs = []
            dm = d.Daemon(base, log=logs.append)
            dm.start()
            dm.close()
            self.assertFalse(os.path.exists(dead["scratch"]["path"]))
            self.assertTrue(os.path.isdir(alive["scratch"]["path"]))
            self.assertIsNone(live.poll())  # recovery never signals
            self.assertTrue(any("cleaned" in m for m in logs))
            self.assertTrue(any("retained" in m for m in logs))
        finally:
            live.kill()
            live.wait()
            for p in scratches:
                shutil.rmtree(p, ignore_errors=True)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
