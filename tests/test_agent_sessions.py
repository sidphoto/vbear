"""R3 S2: managed Claude launch state (settings, scratch, manifest, cleanup, recovery).

No Claude, Codex or model is started; binaries are synthetic scripts.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from sidconsole.runtime import agent_sessions as a
from sidconsole.runtime import proctrack


def mode(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


class LaunchStateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="sidr3-", dir="/tmp")))
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.binary = self.tmp / "claude"
        self.binary.write_text(f"#!{sys.executable}\nprint('2.1.286 (Claude Code)')\n", encoding="utf-8")
        self.binary.chmod(0o700)
        self.codex_binary = self.tmp / "codex"
        self.codex_binary.write_text(f"#!{sys.executable}\nprint('codex-cli 0.159.2')\n", encoding="utf-8")
        self.codex_binary.chmod(0o700)
        self.scratches: list[str] = []

    def tearDown(self):
        for p in self.scratches:
            if p.startswith("/private/tmp/sc-"):
                shutil.rmtree(p, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def prepare(self, workdir=None, **kw):
        m = a.prepare_claude_launch(
            self.base, str(workdir or self.work), cli_binary=str(self.binary), cli_version="2.1.286",
            cli_identity=a.binary_identity(str(self.binary)), allowed_root=kw.pop("allowed_root", str(self.tmp)), **kw)
        self.scratches.append(m["scratch"]["path"])
        return m

    def prepare_codex(self, *, read_only=False, commit=True):
        m = a.prepare_codex_launch(
            self.base, str(self.work), cli_binary=str(self.codex_binary), cli_version="0.159.2",
            cli_identity=a.binary_identity(str(self.codex_binary)), allowed_root=str(self.tmp),
            read_only=read_only, commit=commit)
        self.scratches.append(m["scratch"]["path"])
        return m

    def manifest(self, launch_id) -> dict:
        return json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())

    # ---- prepare ----

    def test_prepare_creates_private_layout_and_verified_settings(self):
        m = self.prepare()
        ldir = self.base / "sessions" / m["launch_id"]
        scratch = Path(m["scratch"]["path"])
        self.assertRegex(m["launch_id"], r"^l-[0-9a-f]{16}$")
        self.assertEqual(mode(self.base / "sessions"), 0o700)
        self.assertEqual(mode(ldir), 0o700)
        self.assertEqual(mode(ldir / "settings.json"), 0o600)
        self.assertEqual(mode(ldir / "manifest.json"), 0o600)
        self.assertEqual(scratch.parent, Path("/private/tmp"))
        self.assertTrue(scratch.name.startswith("sc-"))
        self.assertEqual(mode(scratch), 0o700)
        self.assertLessEqual(len(f"{scratch}/claude-{os.getuid()}".encode()), 44)
        settings = json.loads((ldir / "settings.json").read_text())
        sb = settings["sandbox"]
        self.assertEqual(settings, a.claude_settings(str(self.work), str(scratch), os.getuid()))
        self.assertIs(sb["enabled"], True)
        self.assertIs(sb["failIfUnavailable"], True)
        self.assertIs(sb["allowUnsandboxedCommands"], False)
        self.assertEqual(sb["filesystem"]["allowWrite"], [str(self.work), str(scratch)])
        self.assertEqual(sb["network"], {"allowedDomains": [], "strictAllowlist": True})
        self.assertEqual(m["state"], "prepared")
        self.assertIsNone(m["native_session_id"])
        self.assertEqual(m["boundary"]["read"], "not isolated")
        blob = json.dumps(m).lower()
        for word in ("token", "credential", "password", "secret", "keychain"):
            self.assertNotIn(word, blob)

    def test_argv_is_fixed_and_offers_no_edit_tools(self):
        m = self.prepare()
        self.assertEqual(a.claude_argv(m), [
            str(self.binary), "--safe-mode", "--settings", m["settings_path"],
            "--permission-mode", "acceptEdits", "--tools", "Bash",
            "--disallowedTools", "Edit,Write", "--strict-mcp-config"])

    def test_codex_prepare_and_argv_are_pinned_and_workspace_scoped(self):
        m = self.prepare_codex()
        self.assertEqual(m["engine"], "codex")
        self.assertNotIn("commit", m)
        self.assertNotIn("read_only", m)
        self.assertEqual(mode(Path(m["settings_path"])), 0o600)
        settings = json.loads(Path(m["settings_path"]).read_text())
        self.assertEqual(settings, a.codex_settings(str(self.work), m["scratch"]["path"],
                                                    sandbox_mode="workspace-write", commit=True))
        loaded = a.load_validated(self.base, m["launch_id"])
        argv = a.managed_argv(loaded)
        self.assertEqual(argv[:10], [str(self.codex_binary), "--ignore-user-config", "--ignore-rules",
                                     "--ephemeral", "--sandbox", "workspace-write", "--cd",
                                     str(self.work), "--skip-git-repo-check", "-c"])
        self.assertIn("sandbox_workspace_write.exclude_slash_tmp=true", argv)
        self.assertIn("sandbox_workspace_write.exclude_tmpdir_env_var=true", argv)
        self.assertIn("sandbox_workspace_write.network_access=false", argv)
        roots = "sandbox_workspace_write.writable_roots=" + json.dumps(
            [str(self.work), m["scratch"]["path"], str(self.work / ".git")], separators=(",", ":"))
        self.assertIn(roots, argv)
        self.assertNotIn("CODEX_HOME", json.dumps(loaded))

    def test_codex_read_only_settings_have_no_writable_roots(self):
        m = self.prepare_codex(read_only=True, commit=False)
        self.assertEqual(json.loads(Path(m["settings_path"]).read_text()), {"sandbox_mode": "read-only"})
        loaded = a.load_validated(self.base, m["launch_id"])
        argv = a.managed_argv(loaded)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertFalse(any("writable_roots" in arg for arg in argv))

    def test_codex_workspace_write_refuses_commit_false_and_settings_drift(self):
        with self.assertRaises(a.LaunchRefused) as c:
            a.codex_settings(str(self.work), "/private/tmp/sc-test", sandbox_mode="workspace-write", commit=False)
        self.assertEqual(c.exception.code, "commit_not_enforceable")
        m = self.prepare_codex()
        path = Path(m["settings_path"])
        data = json.loads(path.read_text())
        data["sandbox_workspace_write"]["network_access"] = True
        path.write_text(json.dumps(data))
        with self.assertRaises(a.LaunchRefused) as c:
            a.load_validated(self.base, m["launch_id"])
        self.assertEqual(c.exception.code, "drift")

    def test_workdir_rules(self):
        cases = [
            ("relative/path", None),
            (str(self.tmp / "missing"), None),
            (str(self.tmp), None),                       # the allowed root itself
            ("/usr", None),                              # outside the allowed root
            (str(self.tmp), str(self.tmp.parent)),       # would contain the state dir
            (str(self.base), None),                      # the state dir itself
        ]
        for workdir, root in cases:
            with self.subTest(workdir=workdir):
                with self.assertRaises(a.LaunchRefused) as c:
                    a.prepare_claude_launch(self.base, workdir, cli_binary=str(self.binary),
                                            cli_version="2.1.286",
                                            cli_identity=a.binary_identity(str(self.binary)),
                                            allowed_root=root or str(self.tmp))
                self.assertEqual(c.exception.code, "invalid_workdir")
        self.assertFalse((self.base / "sessions").exists() and any((self.base / "sessions").iterdir()))

    def test_workdir_inside_global_cli_config_is_refused(self):
        target = Path.home() / ".claude"
        if not target.is_dir():
            self.skipTest("no ~/.claude here")
        with self.assertRaises(a.LaunchRefused) as c:
            a.prepare_claude_launch(self.base, str(target), cli_binary=str(self.binary),
                                    cli_version="2.1.286",
                                    cli_identity=a.binary_identity(str(self.binary)),
                                    allowed_root=str(Path.home()))
        self.assertEqual(c.exception.code, "invalid_workdir")

    def test_too_long_scratch_path_is_refused_and_leaves_nothing(self):
        before = {p for p in os.listdir("/private/tmp") if p.startswith("sc-")}
        with mock.patch.object(a, "CLAUDE_TMP_PATH_LIMIT", 10):
            with self.assertRaises(a.LaunchRefused) as c:
                self.prepare()
        self.assertEqual(c.exception.code, "scratch_path_too_long")
        self.assertEqual({p for p in os.listdir("/private/tmp") if p.startswith("sc-")}, before)
        self.assertEqual(list((self.base / "sessions").iterdir()), [])

    def test_unresolved_binary_is_refused(self):
        link = self.tmp / "claude-link"
        link.symlink_to(self.binary)
        with self.assertRaises(a.LaunchRefused) as c:
            a.prepare_claude_launch(self.base, str(self.work), cli_binary=str(link), cli_version="2.1.286",
                                    cli_identity=a.binary_identity(str(self.binary)), allowed_root=str(self.tmp))
        self.assertEqual(c.exception.code, "invalid_binary")

    # ---- validation before launch ----

    def test_load_validated_accepts_untouched_launch(self):
        m = self.prepare()
        self.assertEqual(a.load_validated(self.base, m["launch_id"])["launch_id"], m["launch_id"])

    def test_bad_launch_ids_are_refused(self):
        for bad in ["", "l-xyz", "../x", "l-0123456789abcdef/..", None, 7]:
            with self.subTest(bad=bad):
                with self.assertRaises(a.LaunchRefused):
                    a.load_validated(self.base, bad)

    def test_drift_is_refused(self):
        def settings_changed(m):
            p = Path(m["settings_path"])
            data = json.loads(p.read_text())
            data["sandbox"]["filesystem"]["allowWrite"].append("/")
            p.write_text(json.dumps(data))

        def settings_loose_mode(m):
            os.chmod(m["settings_path"], 0o644)

        def scratch_is_symlink(m):
            shutil.rmtree(m["scratch"]["path"])
            os.symlink(str(self.work), m["scratch"]["path"])

        def scratch_loose_mode(m):
            os.chmod(m["scratch"]["path"], 0o755)

        def binary_touched(m):
            self.binary.write_text(self.binary.read_text() + "# changed\n")

        def workdir_gone(m):
            self.work.rmdir()

        def manifest_other_id(m):
            p = self.base / "sessions" / m["launch_id"] / "manifest.json"
            data = json.loads(p.read_text())
            data["launch_id"] = "l-" + "0" * 16
            p.write_text(json.dumps(data))

        def manifest_points_scratch_elsewhere(m):
            p = self.base / "sessions" / m["launch_id"] / "manifest.json"
            data = json.loads(p.read_text())
            data["scratch"]["path"] = str(self.work)
            p.write_text(json.dumps(data))

        for change in [settings_changed, settings_loose_mode, scratch_is_symlink, scratch_loose_mode,
                       binary_touched, workdir_gone, manifest_other_id, manifest_points_scratch_elsewhere]:
            with self.subTest(change=change.__name__):
                self.work.mkdir(exist_ok=True)
                m = self.prepare()
                change(m)
                with self.assertRaises(a.LaunchRefused):
                    a.load_validated(self.base, m["launch_id"])
                p = m["scratch"]["path"]
                if os.path.islink(p):
                    os.unlink(p)

    def test_settings_swapped_for_same_hash_shape_must_match_template(self):
        m = self.prepare()
        p = Path(m["settings_path"])
        data = json.loads(p.read_text())
        data["sandbox"]["allowUnsandboxedCommands"] = True
        p.write_text(json.dumps(data))
        mp = self.base / "sessions" / m["launch_id"] / "manifest.json"
        md = json.loads(mp.read_text())
        md["settings_sha256"] = a._sha256(p)  # an attacker who can also fix up the digest
        mp.write_text(json.dumps(md))
        with self.assertRaises(a.LaunchRefused) as c:
            a.load_validated(self.base, m["launch_id"])
        self.assertEqual(c.exception.code, "drift")

    # ---- cleanup ----

    def test_cleanup_removes_exactly_the_recorded_paths(self):
        m = self.prepare()
        other = self.prepare()
        (Path(m["scratch"]["path"]) / "claude-501").mkdir()
        r = a.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertEqual(r, {"launch_id": m["launch_id"], "cleaned": True})
        self.assertFalse(os.path.exists(m["scratch"]["path"]))
        self.assertFalse((self.base / "sessions" / m["launch_id"]).exists())
        self.assertTrue(os.path.isdir(other["scratch"]["path"]))
        self.assertTrue((self.base / "sessions" / other["launch_id"]).is_dir())
        self.assertTrue(self.work.is_dir())

    def test_cleanup_without_proof_retains_and_marks_manual_review(self):
        m = self.prepare()
        r = a.cleanup_launch(self.base, m["launch_id"], proven_dead=False, reason="仍有程序")
        self.assertFalse(r["cleaned"])
        self.assertTrue(os.path.isdir(m["scratch"]["path"]))
        after = self.manifest(m["launch_id"])
        self.assertEqual(after["state"], "manual_review")
        self.assertEqual(after["retained_reason"], "仍有程序")

    def test_cleanup_refuses_replaced_scratch(self):
        m = self.prepare()
        shutil.rmtree(m["scratch"]["path"])
        os.symlink(str(self.work), m["scratch"]["path"])
        (self.work / "keep.txt").write_text("user data")
        r = a.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertFalse(r["cleaned"])
        self.assertTrue((self.work / "keep.txt").exists())
        self.assertTrue((self.base / "sessions" / m["launch_id"]).is_dir())
        os.unlink(m["scratch"]["path"])

    def test_cleanup_refuses_manifest_pointing_outside_scratch_area(self):
        m = self.prepare()
        victim = self.tmp / "victim"
        victim.mkdir(mode=0o700)
        (victim / "keep.txt").write_text("user data")
        mp = self.base / "sessions" / m["launch_id"] / "manifest.json"
        md = json.loads(mp.read_text())
        md["scratch"] = {"path": str(victim), "inode": os.stat(victim).st_ino, "uid": os.getuid()}
        mp.write_text(json.dumps(md))
        r = a.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
        self.assertFalse(r["cleaned"])
        self.assertTrue((victim / "keep.txt").exists())

    def test_expire_prepared_removes_only_stale_never_started_launches(self):
        fresh = self.prepare()
        stale = self.prepare()
        running = self.prepare()
        a.update_manifest(self.base, stale["launch_id"], created=time.time() - a.PREPARED_TTL - 5)
        a.update_manifest(self.base, running["launch_id"], created=time.time() - a.PREPARED_TTL - 5,
                          state="running", native_session_id="n-000000000000")
        self.assertEqual(a.expire_prepared(self.base), [{"launch_id": stale["launch_id"], "cleaned": True}])
        self.assertFalse(os.path.exists(stale["scratch"]["path"]))
        self.assertTrue(os.path.isdir(fresh["scratch"]["path"]))
        self.assertTrue(os.path.isdir(running["scratch"]["path"]))

    def test_discard_prepared_refuses_a_launch_a_daemon_has_taken(self):
        m = self.prepare()
        a.update_manifest(self.base, m["launch_id"], state="launching")
        self.assertFalse(a.discard_prepared(self.base, m["launch_id"])["cleaned"])
        self.assertTrue(os.path.isdir(m["scratch"]["path"]))

    def test_workdir_rules_are_rechecked_at_validation(self):
        m = self.prepare()
        other = self.tmp / "elsewhere"
        other.mkdir()
        a.update_manifest(self.base, m["launch_id"], allowed_root=str(other))
        with self.assertRaises(a.LaunchRefused):
            a.load_validated(self.base, m["launch_id"])

    # ---- recovery after a daemon restart ----

    def _running(self, pid, start, observed=()):
        m = self.prepare()
        a.update_manifest(self.base, m["launch_id"], state="running", native_session_id="n-000000000000",
                          leader={"pid": pid, "start": start, "source": proctrack.SOURCE}, observed=[list(x) for x in observed])
        return m

    def test_recover_cleans_launch_whose_processes_are_gone(self):
        m = self._running(999999, "Thu Jan  1 00:00:00 1970")
        result = a.recover(self.base)
        self.assertEqual(result, [{"launch_id": m["launch_id"], "cleaned": True}])
        self.assertFalse(os.path.exists(m["scratch"]["path"]))

    def test_recover_retains_when_a_recorded_process_is_alive_and_never_signals(self):
        proc = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
        try:
            row = next(r for r in proctrack.process_table() if r["pid"] == proc.pid)
            m = self._running(999999, "Thu Jan  1 00:00:00 1970", observed=[(proc.pid, row["start"])])
            result = a.recover(self.base)
            self.assertFalse(result[0]["cleaned"])
            self.assertIn(str(proc.pid), result[0]["retained_reason"])
            self.assertIsNone(proc.poll())
            self.assertTrue(os.path.isdir(m["scratch"]["path"]))
            self.assertEqual(self.manifest(m["launch_id"])["state"], "manual_review")
            self.assertEqual(a.recover(self.base), [])  # manual_review is left for a human
        finally:
            proc.kill()
            proc.wait()

    def test_recover_ignores_reused_pid_with_other_start_time(self):
        proc = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
        try:
            m = self._running(proc.pid, "Thu Jan  1 00:00:00 1970")
            self.assertTrue(a.recover(self.base)[0]["cleaned"])
            self.assertIsNone(proc.poll())
            self.assertFalse(os.path.exists(m["scratch"]["path"]))
        finally:
            proc.kill()
            proc.wait()

    def test_recover_skips_fresh_prepared_and_cleans_stale_prepared(self):
        fresh = self.prepare()
        stale = self.prepare()
        a.update_manifest(self.base, stale["launch_id"], created=time.time() - a.PREPARED_TTL - 5)
        result = a.recover(self.base)
        self.assertEqual(result, [{"launch_id": stale["launch_id"], "cleaned": True}])
        self.assertTrue(os.path.isdir(fresh["scratch"]["path"]))

    def test_recover_marks_prepared_launch_with_corrupt_created_field(self):
        m = self.prepare()
        a.update_manifest(self.base, m["launch_id"], created="yesterday")
        result = a.recover(self.base)
        self.assertFalse(result[0]["cleaned"])
        self.assertEqual(self.manifest(m["launch_id"])["state"], "manual_review")
        self.assertTrue(os.path.isdir(m["scratch"]["path"]))

    def test_recover_retains_launch_interrupted_mid_spawn(self):
        m = self.prepare()
        a.update_manifest(self.base, m["launch_id"], state="launching")
        result = a.recover(self.base)
        self.assertFalse(result[0]["cleaned"])
        self.assertTrue(os.path.isdir(m["scratch"]["path"]))

    def test_recover_retains_when_process_table_is_unavailable(self):
        m = self._running(999999, "Thu Jan  1 00:00:00 1970")
        with mock.patch.object(proctrack, "process_table", side_effect=proctrack.ProcessTableUnavailable("x")):
            result = a.recover(self.base)
        self.assertFalse(result[0]["cleaned"])
        self.assertTrue(os.path.isdir(m["scratch"]["path"]))


class TrackerCase(unittest.TestCase):
    def test_tracks_descendant_in_its_own_group_after_reparenting(self):
        code = ("import subprocess,sys,time;"
                "c=subprocess.Popen(['/bin/sleep','30'],start_new_session=True);"
                "print(c.pid,flush=True);time.sleep(30)")
        leader = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                                  start_new_session=True)
        child_pid = int(leader.stdout.readline())
        try:
            t = proctrack.DescendantTracker(leader.pid)
            t.observe()
            rows = proctrack.process_table()
            child = next(r for r in rows if r["pid"] == child_pid)
            self.assertNotEqual(child["pgid"], leader.pid)
            groups, uncertain = t.groups(rows, uid=os.getuid(), exclude_pgid=leader.pid)
            self.assertEqual(groups, [child_pid])
            self.assertEqual(uncertain, [])
            leader.kill()
            leader.wait()
            alive = t.live()
            self.assertEqual([r["pid"] for r in alive], [child_pid])  # orphaned, still known
        finally:
            for pid in (child_pid,):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            if leader.poll() is None:
                leader.kill()
                leader.wait()
            leader.stdout.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and t.live():
            time.sleep(0.05)
        self.assertEqual(t.live(), [])

    def test_reused_root_pid_is_not_followed(self):
        me = os.getuid()
        t = proctrack.DescendantTracker(100)
        first = [{"pid": 100, "ppid": 1, "pgid": 100, "uid": me, "stat": "R", "start": "t1"},
                 {"pid": 101, "ppid": 100, "pgid": 101, "uid": me, "stat": "R", "start": "t2"}]
        t.observe(first)
        self.assertEqual(sorted(p for p, _ in t.identities), [100, 101])
        # The root exited; pid 100 now belongs to an unrelated process with a child.
        reused = [{"pid": 100, "ppid": 1, "pgid": 100, "uid": me, "stat": "R", "start": "t9"},
                  {"pid": 300, "ppid": 100, "pgid": 300, "uid": me, "stat": "R", "start": "t9"}]
        t.observe(reused)
        self.assertEqual(t.live(reused), [])
        self.assertEqual(t.groups(reused, uid=me, exclude_pgid=100), ([], []))

    def test_restored_tracker_follows_root_only_with_matching_start(self):
        me = os.getuid()
        rows = [{"pid": 100, "ppid": 1, "pgid": 100, "uid": me, "stat": "R", "start": "t1"},
                {"pid": 101, "ppid": 100, "pgid": 101, "uid": me, "stat": "R", "start": "t2"}]
        blind = proctrack.DescendantTracker(100, [(50, "gone")])      # restored, no root start known
        blind.observe(rows)
        self.assertEqual(blind.live(rows), [])
        wrong = proctrack.DescendantTracker(100, [(50, "gone")], root_start="other")
        wrong.observe(rows)
        self.assertEqual(wrong.live(rows), [])
        right = proctrack.DescendantTracker(100, [(50, "gone")], root_start="t1")
        right.observe(rows)
        self.assertEqual(sorted(r["pid"] for r in right.live(rows)), [100, 101])

    def test_dead_identities_are_forgotten_and_live_ones_kept(self):
        me = os.getuid()
        t = proctrack.DescendantTracker(100)
        rows = [{"pid": 100, "ppid": 1, "pgid": 100, "uid": me, "stat": "R", "start": "a"}] + [
            {"pid": 200 + i, "ppid": 100, "pgid": 200 + i, "uid": me, "stat": "R", "start": "b"} for i in range(50)]
        t.observe(rows)
        self.assertEqual(len(t.identities), 51)
        t.observe(rows[:2])
        self.assertEqual(sorted(p for p, _ in t.identities), [100, 200])

    def _row(self, pid, ppid, pgid, start="s", uid=None, stat="R"):
        return {"pid": pid, "ppid": ppid, "pgid": pgid, "uid": os.getuid() if uid is None else uid,
                "stat": stat, "start": start}

    def test_member_of_foreign_group_is_uncertain_not_signalable(self):
        t = proctrack.DescendantTracker(100)
        rows = [self._row(100, 1, 100), self._row(200, 100, 300), self._row(300, 1, 300)]
        t.observe(rows)
        groups, uncertain = t.groups(rows, uid=os.getuid(), exclude_pgid=100)
        self.assertEqual(groups, [])
        self.assertEqual([r["pid"] for r in uncertain], [200])

    def test_foreign_uid_is_uncertain(self):
        t = proctrack.DescendantTracker(100)
        rows = [self._row(100, 1, 100), self._row(200, 100, 200, uid=os.getuid() + 1, start="")]
        t.observe(rows)
        groups, uncertain = t.groups(rows, uid=os.getuid(), exclude_pgid=100)
        self.assertEqual(groups, [])
        self.assertEqual([r["pid"] for r in uncertain], [200])

    def test_group_led_by_another_users_process_is_never_signalable(self):
        other = os.getuid() + 1
        t = proctrack.DescendantTracker(100)
        # A setuid child leads its own group; one of our own processes is a member of it.
        rows = [self._row(100, 1, 100), self._row(200, 100, 200, uid=other, start=""),
                self._row(201, 200, 200)]
        t.observe(rows)
        self.assertNotIn(200, t.known_groups)
        groups, uncertain = t.groups(rows, uid=os.getuid(), exclude_pgid=100)
        self.assertEqual(groups, [])
        self.assertEqual(sorted(r["pid"] for r in uncertain), [200, 201])

    def test_orphan_left_in_a_tool_group_is_still_ours(self):
        t = proctrack.DescendantTracker(100)
        t.observe([self._row(100, 1, 100), self._row(200, 100, 200)])       # tool shell, own group
        # The shell exited; a background child it started between two looks remains, re-parented.
        rows = [self._row(100, 1, 100), self._row(201, 1, 200, start="later")]
        t.observe(rows)
        self.assertEqual([r["pid"] for r in t.live(rows)], [100, 201])
        self.assertEqual(t.groups(rows, uid=os.getuid(), exclude_pgid=100), ([200], []))

    def test_emptied_group_id_is_forgotten_before_reuse(self):
        t = proctrack.DescendantTracker(100)
        t.observe([self._row(100, 1, 100), self._row(200, 100, 200)])
        t.observe([self._row(100, 1, 100)])                                   # group 200 is empty now
        rows = [self._row(100, 1, 100), self._row(200, 1, 200, start="other"), self._row(201, 200, 200, start="other")]
        t.observe(rows)                                                        # unrelated reuse of pid 200
        self.assertEqual([r["pid"] for r in t.live(rows)], [100])
        self.assertEqual(t.groups(rows, uid=os.getuid(), exclude_pgid=100), ([], []))

    def test_root_group_is_not_claimed_by_the_tracker(self):
        t = proctrack.DescendantTracker(100)
        rows = [self._row(100, 1, 100), self._row(101, 100, 100), self._row(999, 1, 100, start="x")]
        t.observe(rows)
        self.assertNotIn(100, t.known_groups)
        self.assertEqual(sorted(p for p, _ in t.identities), [100, 101])


if __name__ == "__main__":
    unittest.main()
