"""Stream executor sessions in the runtime daemon (design 2-3, 5.8, 6, 7, 9;
planner decisions S2a-2 Q1-Q4).

A synthetic stand-in plays Claude Code 2.1.292 in stream-json mode: it reads
one dispatch line from stdin and answers with a turn in the measured event
order (tests/stream_fixtures.py). No Claude, Codex or model is started. The
flows.json, key and .claude.json are synthetic; the admin-policy check runs
against a temporary root, never the real /Library or /etc.
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

from tests import stream_fixtures as fx
from vbear import acceptance as acc
from vbear import admin_policy, flows, login_identity, tasks
from vbear.runtime import pipeline_store
from vbear.runtime import agent_sessions as a
from vbear.runtime import cli_versions
from vbear.runtime import daemon as d
from vbear.runtime import stream_protocol as sp
from vbear.runtime import stream_session

REPO = str(Path(__file__).resolve().parent.parent)
TIMEOUT = 20.0
STARTUP_TIMEOUT = 60.0
HEAVY_TIMEOUT = 180.0        # the 12 000-event turn: CPU work that grows with a busy Mac

FAKE_STREAM_CLI = r'''#!%(py)s
import json, os, signal, subprocess, sys, time
sys.path.insert(0, %(repo)r)
def _term(*_):
    open("got-sigterm", "w").close()                  # evidence that a signal arrived
    sys.exit(143)
signal.signal(signal.SIGTERM, _term)
from tests import stream_fixtures as fx
argv = sys.argv
sid = argv[argv.index("--session-id") + 1]
model = argv[argv.index("--model") + 1]
with open("fake-launch.json", "w") as f:
    json.dump({"argv": argv, "cwd": os.getcwd(), "pid": os.getpid(), "pgid": os.getpgrp(),
               "env": sorted(os.environ), "home": os.environ.get("HOME"),
               "tmpdir": os.environ.get("CLAUDE_CODE_TMPDIR")}, f)
index, cost = 0, 0.0
def emit(events):
    for e in events:
        sys.stdout.write(json.dumps(e) + "\n")
    sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    d = msg["uuid"]
    text = msg["message"]["content"][0]["text"]
    mode = open("fake-mode").read().strip() if os.path.exists("fake-mode") else "ok"
    if mode == "exit":
        sys.exit(3)
    if mode == "silent":
        continue
    if mode == "child_then_exit":
        # Stays in our group and ignores SIGTERM, so the group outlives the
        # leader until SIGKILL: a stable window to look at the leader.
        subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                          "open('child-started','w').close(); time.sleep(600)"])
        while not os.path.exists("child-started"):
            time.sleep(0.01)
        sys.exit(0)
    if mode == "escape_then_exit":
        # Like a Bash tool command that starts its own session; the CLI keeps
        # running a while, as Claude Code does while its tool runs.
        p = subprocess.Popen(["sleep", "600"], start_new_session=True)
        open("escaped.pid", "w").write(str(p.pid))
        time.sleep(3)
        sys.exit(0)
    if mode == "bad_json":
        sys.stdout.write("{not json\n"); sys.stdout.flush()
        continue
    if mode == "stderr_flood":
        sys.stderr.write("x" * 4096 * 64); sys.stderr.flush()
    cost += 0.01
    events = fx.turn(sid, d, text, cwd=os.getcwd(), result_index=index, cost=cost, prefix="r%%d" %% index,
                     model=model)
    if mode == "many_responses":
        rep = fx.report(d)
        responses = [[{"type": "thinking", "thinking": "."}] for _ in range(5)]
        responses.append([{"type": "tool_use", "id": "so%%d" %% index, "name": "StructuredOutput", "input": rep}])
        events = fx.turn(sid, d, text, cwd=os.getcwd(), result_index=index, cost=cost, prefix="r%%d" %% index,
                         model=model, responses=responses, rep=rep)
    if mode == "no_completed":
        events = events[:-1]
    if mode == "is_error":
        events = fx.turn(sid, d, text, cwd=os.getcwd(), result_index=index, cost=cost, prefix="r%%d" %% index,
                         model=model, subtype="error_during_execution", is_error=True)
    if mode == "huge_turn":
        # One response split into very many assistant events: the turn's
        # facts no longer fit one journal line (512 KiB / 100 000 nodes).
        rep = fx.report(d)
        many = [{"type": "thinking", "thinking": "."}] * 12000
        events = fx.turn(sid, d, text, cwd=os.getcwd(), result_index=index, cost=cost, prefix="r%%d" %% index,
                         model=model, responses=[many + [{"type": "tool_use", "id": "so%%d" %% index,
                                                          "name": "StructuredOutput", "input": rep}]], rep=rep)
    if mode == "surrogate_so":
        # A complete, otherwise valid turn; only the result's structured
        # output (a copy: the fixture shares it with the tool input) carries
        # a lone surrogate, which strict JSON still decodes.
        events[-2]["structured_output"] = dict(events[-2]["structured_output"], notes="\ud800")
    if mode == "hang":
        # Confirmed, then the model never answers: a turn in flight.
        emit(events[:5]); open("hang-ready", "w").close(); time.sleep(600)
    if mode == "slow":
        emit(events[:5]); time.sleep(1.5); emit(events[5:])
    else:
        emit(events)
    index += 1
'''

FAKE_PTY_CLI = r'''#!%(py)s
import json, os, sys, time
with open("fake-launch.json", "w") as f:
    json.dump({"pid": os.getpid()}, f)
time.sleep(600)
'''


class StreamCase(unittest.TestCase):
    limits = None

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbs-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.root = self.tmp / "root"                         # the admin-policy root, never the real /
        self.root.mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()
        fx.fake_repo(self.work)                               # HEAD readable from files (v29.9 base_commit)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        real_check = admin_policy.check_claude
        p = mock.patch("vbear.runtime.daemon_stream.admin_policy.check_claude",
                       side_effect=lambda version, home=None: real_check(version, root=str(self.root), home=home))
        p.start()
        self.addCleanup(p.stop)
        v = mock.patch.object(cli_versions, "STREAM_VERIFIED_VERSIONS", ("2.1.292",))
        v.start()
        self.addCleanup(v.stop)
        self.binary = self.tmp / "claude"
        self.binary.write_text(FAKE_STREAM_CLI % {"py": sys.executable, "repo": REPO})
        self.binary.chmod(0o700)
        (self.home / ".claude.json").write_text(json.dumps({"oauthAccount": {
            "accountUuid": "11111111-2222-3333-4444-555555555555",
            "organizationUuid": "66666666-7777-8888-9999-000000000000"}}))
        self.tid = tasks.save_task(None, {"title": "t"})["id"]
        roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
                 "reviewers": [{"name": "c", "family": "openai"}]}
        self.fid = flows.create_flow({"task_id": self.tid, "roles": roles}, lambda t: True)["id"]
        self.key = login_identity.create_login_key(self.base, valid_acceptances=0)
        self.accept()
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

    def accept(self, **limits):
        fp = login_identity.claude_login_fingerprint(self.home / ".claude.json", self.key).hmac
        fields = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
                  "executor_claude_version": "2.1.292", "executor_model": fx.MODEL,
                  "executor_login_fingerprint": fp, "login_fingerprint": "b" * 64, "login_key_id": self.key.key_id,
                  "limits": {**acc.DEFAULT_LIMITS, **(self.limits or {}), **limits}}
        with flows.store.locked():
            data = flows.store.load()
            ev = data[self.fid]["events"]
            ev.append({"seq": len(ev) + 1, "at": time.time(), "kind": "risk_acknowledged", "source": "console",
                       "note": "", **fields})
            flows.store.save(data)

    def rpc(self, op, **kw):
        return d.rpc(op, base=self.base, timeout=TIMEOUT, **kw)

    def raw_rpc(self, op, **kw):
        """Like rpc, but JSON with \\u escapes (a lone surrogate can travel this way)."""
        import socket
        req = {"v": 1, "id": "raw", "op": op, **kw}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(TIMEOUT)
            c.connect(str(d.socket_path(self.base)))
            c.sendall(json.dumps(req).encode("ascii") + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = c.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.split(b"\n")[0])

    def prepare(self, mode="ok"):
        (self.work / "fake-mode").write_text(mode)
        m = a.prepare_stream_launch(self.base, str(self.work), cli_binary=str(self.binary), cli_version="2.1.292",
                                    cli_identity=a.binary_identity(str(self.binary)), model_id=fx.MODEL,
                                    pipeline_id=self.fid, task_id=self.tid, allowed_root=str(self.tmp))
        self.scratches.append(m["scratch"]["path"])
        return m

    def open(self, mode="ok"):
        m = self.prepare(mode)
        r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r.get("ok"), r)
        info = self.launched()
        self.pids.append(info["pid"])
        return m["launch_id"], r["result"]

    def launched(self):
        # A Python start under heavy load (the planner's churn plus a full
        # suite) took over 20 s once; this only waits for the fake to exist.
        return self.wait_for(lambda: self._read(self.work / "fake-launch.json"), timeout=STARTUP_TIMEOUT,
                             msg="fake CLI start")

    @staticmethod
    def _read(path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def wait_for(self, pred, timeout=TIMEOUT, msg="condition"):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = pred()
            if value:
                return value
            time.sleep(0.03)
        self.fail(f"timed out waiting for {msg}; logs: {self.logs[-5:]}")

    def dispatch(self, launch_id, text="請完成工作", d=None):
        d = d or fx.new_uuid()
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d, text=text,
                     approval={"kind": "preview", "id": "pv-" + d[:8]})
        self.assertTrue(r.get("ok"), r)
        r = self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=d)
        self.assertTrue(r.get("ok"), r)
        return d

    def crash_daemon(self):
        """The daemon dies as if killed: its loop stops and the kernel closes
        its descriptors; nothing is cleaned up, signalled or reaped. The CLI
        lives on in its own session."""
        self.dm.stop()
        self.thread.join(5)
        for s in list(self.dm._streams.values()):
            for f in (s.proc.stdin, s.proc.stdout, s.proc.stderr):
                try:
                    f.close()
                except OSError:
                    pass
            s.writer.close()
        self.dm._streams.clear()
        self.dm.close()                           # listener and lock only: nothing is left to kill

    def restart_daemon(self):
        self.dm = d.Daemon(self.base, log=self.logs.append)
        self.dm.start()                           # recovery runs here
        self.thread = threading.Thread(target=self.dm.serve_forever, daemon=True)
        self.thread.start()

    def manifest(self, launch_id):
        return json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())

    def journal(self, launch_id):
        from vbear.runtime import stream_journal
        fd = os.open(self.base / "sessions" / launch_id, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return stream_journal.read(fd)
        finally:
            os.close(fd)

    def status(self, launch_id):
        r = self.rpc("stream_status", launch_id=launch_id)
        self.assertTrue(r.get("ok"), r)
        return r["result"]

    def turn_status(self, launch_id, d):
        st = self.status(launch_id)
        return next((x for x in st["dispatches"] if x["dispatch_id"] == d), None)


class HappyPathTests(StreamCase):
    def test_two_valid_turns_then_close(self):
        launch_id, info = self.open()
        launch = self.launched()
        self.assertEqual(launch["cwd"], str(self.work))
        self.assertNotIn("ANTHROPIC_BASE_URL", launch["env"])                 # the endpoint is in --settings
        settings = json.loads(Path(launch["argv"][launch["argv"].index("--settings") + 1]).read_text())
        self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://api.anthropic.com")
        self.assertEqual(launch["argv"][launch["argv"].index("--session-id") + 1], info["claude_session_id"])
        d1 = self.dispatch(launch_id)
        t = self.wait_for(lambda: (x := self.turn_status(launch_id, d1)) and x["status"] == "ended" and x,
                          msg="first turn")
        self.assertEqual((t["valid"], t["reasons"]), (True, []))
        # design 4: the executor's words and VBear's file checks, apart. The
        # fake reports head 000..., and this work dir is no repository.
        self.assertEqual(t["report"]["dispatch_id"], d1)
        self.assertTrue(t["file_checks"])
        d2 = self.dispatch(launch_id, text="第二則")
        t = self.wait_for(lambda: (x := self.turn_status(launch_id, d2)) and x["status"] == "ended" and x,
                          msg="second turn")
        self.assertTrue(t["valid"])
        st = self.status(launch_id)
        self.assertEqual((st["state"], st["responses"], st["live"]), ("idle", 2, True))
        # resending either RPC is safe
        again = self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=d2)
        self.assertEqual(again["result"]["status"], "ended")
        again = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d2, text="第二則",
                         approval={"kind": "preview", "id": "pv-x"})
        self.assertEqual(again["result"]["status"], "ended")
        other = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d2, text="改了",
                         approval={"kind": "preview", "id": "pv-x"})
        self.assertFalse(other["ok"])
        texts = sorted(os.listdir(self.base / "pipelines" / self.tid / "dispatches"))
        self.assertEqual(texts, sorted([f"{d1}.txt", f"{d2}.txt"]))
        self.assertTrue((self.base / "pipelines" / self.tid / "started.json").exists())
        # close: the journal stays, the scratch goes
        self.assertTrue(self.rpc("stream_close", launch_id=launch_id)["ok"])
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="session finished")
        m = json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())
        self.assertEqual(m["state"], "ended")
        self.assertTrue((self.base / "sessions" / launch_id / "journal.jsonl").exists())
        st = self.status(launch_id)
        self.assertEqual((st["live"], st["state"], st["journal_problem"]), (False, "exited", ""))
        self.assertTrue(st["dispatches"][0]["valid"])

    def test_listing_and_activity(self):
        launch_id, info = self.open()
        listed = self.rpc("list")["result"]["sessions"]
        mine = next(s for s in listed if s["managed"] == launch_id)
        self.assertEqual((mine["engine"], mine["activity_evidence"]["claude_stream"]["state"]),
                         ("claude-stream", "idle"))
        from vbear import activity
        self.assertEqual(activity.arbitrate(mine)["activity"], "waiting")


class RefusalTests(StreamCase):
    def test_unexpected_non_stream_rpc_exception_returns_error_without_stopping_daemon(self):
        with mock.patch.object(self.dm, "_op_open", side_effect=ValueError("synthetic RPC failure")):
            r = self.rpc("open")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "internal")
        self.assertIsNotNone(self.dm._sel)

    def test_an_attach_failing_after_conversion_frees_its_slot(self):
        # Claude review finding 1: the error reaches the client and no dead
        # Attachment keeps a slot.
        import socket
        sid = self.rpc("open", argv=["/bin/sh", "-c", "sleep 30"], cwd=str(self.work))["result"]["session_id"]
        self.pids.append(self.dm._sessions[sid].pid)
        with mock.patch.object(self.dm, "_full_line", side_effect=RuntimeError("synthetic attach failure")):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                c.settimeout(TIMEOUT)
                c.connect(str(d.socket_path(self.base)))
                c.sendall(json.dumps({"v": 1, "id": "a1", "op": "attach", "session_id": sid,
                                      "mode": "control"}).encode() + b"\n")
                response = json.loads(c.recv(65536).split(b"\n", 1)[0])
        self.assertFalse(response["ok"])
        self.assertEqual((response["id"], response["error"]["code"]), ("a1", "internal"))
        # at once: before this fix the stale one went only after the 10 s
        # no-write-progress watchdog
        self.wait_for(lambda: not self.dm._attachments, timeout=2.0, msg="no attachment left")
        self.assertEqual(self.dm._sessions[sid].attachments, [])
        self.assertIsNone(self.dm._sessions[sid].control)
        self.assertTrue(self.rpc("hello")["ok"])
        self.rpc("close", session_id=sid)

    def test_invalid_rpc_id_cannot_escape_response_encoding(self):
        import socket
        req = {"v": 1, "id": "\ud800", "op": "hello"}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(TIMEOUT)
            c.connect(str(d.socket_path(self.base)))
            c.sendall(json.dumps(req).encode("ascii") + b"\n")
            response = json.loads(c.recv(65536).split(b"\n", 1)[0])
        self.assertFalse(response["ok"])
        self.assertIsNone(response["id"])
        self.assertEqual(response["error"]["code"], "internal")
        self.assertIsNotNone(self.dm._sel)

    def test_an_unknown_or_malformed_launch_is_refused_not_an_internal_error(self):
        for launch_id in ("l-0000000000000000", "l-xyz", None):
            with self.subTest(launch_id=launch_id):
                r = self.rpc("open_stream", launch_id=launch_id)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "refused", r)

    def test_open_refusals(self):
        cases = []

        def held():
            self.assertTrue(self.rpc("pipeline_hold", pipeline=self.fid, reason="stop")["ok"])
            yield
            self.rpc("pipeline_release", pipeline=self.fid)

        def no_acceptance():
            (self.base / login_identity.KEY_NAME).unlink()
            yield
            self.key = login_identity.create_login_key(self.base, valid_acceptances=0)
            self.accept()

        def other_account():
            original = (self.home / ".claude.json").read_text()
            (self.home / ".claude.json").write_text(original.replace("1111", "9999"))
            yield
            (self.home / ".claude.json").write_text(original)

        def admin_source():
            p = self.root / "Library" / "Application Support" / "ClaudeCode"
            p.mkdir(parents=True)
            yield
            shutil.rmtree(self.root / "Library")

        def remote_cache():
            (self.home / ".claude").mkdir()
            (self.home / ".claude" / "remote-settings.json").write_text("{}")
            yield
            shutil.rmtree(self.home / ".claude")

        def unverified():
            with mock.patch.object(cli_versions, "STREAM_VERIFIED_VERSIONS", ()):
                yield

        for name, ctx in (("held", held), ("no acceptance", no_acceptance), ("other account", other_account),
                          ("admin source", admin_source), ("server-managed cache", remote_cache),
                          ("unverified version", unverified)):
            with self.subTest(case=name):
                gen = ctx()
                next(gen)
                try:
                    m = self.prepare()
                    r = self.rpc("open_stream", launch_id=m["launch_id"])
                    self.assertFalse(r.get("ok"), r)
                finally:
                    next(gen, None)
        self.assertEqual(self.dm._streams, {})

    def test_dispatch_refusals(self):
        launch_id, _ = self.open()
        good = dict(launch_id=launch_id, pipeline=self.fid, approval={"kind": "preview", "id": "pv1"}, text="hi")
        cases = [
            {"pipeline": "flow-ffffffffffff"},
            {"dispatch_id": "not-a-uuid"},
            {"dispatch_id": fx.new_uuid().upper()},
            {"approval": {"kind": "other", "id": "x"}},
            {"approval": {"kind": "preview"}},
            {"text": "has\x1b escape"},                                 # not the sanitised preview text
            {"text": "x" * sp.MAX_DISPATCH_LINE},
            {"launch_id": "l-ffffffffffffffff"},
        ]
        for change in cases:
            with self.subTest(change=repr(change)[:50]):
                r = self.rpc("dispatch_prepare", **{"dispatch_id": fx.new_uuid(), **good, **change})
                self.assertFalse(r.get("ok"), r)
        r = self.raw_rpc("dispatch_prepare", **{**good, "dispatch_id": fx.new_uuid(), "text": "\ud800"})
        self.assertFalse(r["ok"])                                         # a lone surrogate is refused
        self.assertIn("surrogate", r["error"]["message"])
        r = self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=fx.new_uuid())
        self.assertFalse(r["ok"])                                         # never prepared
        # at most one prepared, unsent dispatch
        d1 = fx.new_uuid()
        self.assertTrue(self.rpc("dispatch_prepare", dispatch_id=d1, **good)["ok"])
        self.assertFalse(self.rpc("dispatch_prepare", dispatch_id=fx.new_uuid(), **good)["ok"])
        # a hold stops the send; release lets it through
        self.rpc("pipeline_hold", pipeline=self.fid, reason="stop")
        self.assertFalse(self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1)["ok"])
        self.rpc("pipeline_release", pipeline=self.fid)
        self.assertTrue(self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1)["ok"])

    def test_a_partial_left_by_a_crash_is_removed(self):
        launch_id, _ = self.open()
        ddir = self.base / "pipelines" / self.tid / "dispatches"
        ddir.mkdir(parents=True, exist_ok=True)
        stale = fx.new_uuid()
        (ddir / f".{stale}.partial").write_text("half")
        self.dispatch(launch_id)
        self.assertFalse((ddir / f".{stale}.partial").exists())

    def test_saved_text_is_checked_before_sending(self):
        launch_id, _ = self.open()
        d1 = fx.new_uuid()
        self.assertTrue(self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1,
                                 text="original", approval={"kind": "preview", "id": "p"})["ok"])
        path = self.base / "pipelines" / self.tid / "dispatches" / f"{d1}.txt"
        path.write_text("tampered")
        r = self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1)
        self.assertFalse(r["ok"])
        self.assertEqual(self.status(launch_id)["state"], "error")

    def test_a_pending_text_counts_and_its_id_completes_it(self):
        # Planner ruling R5 #2: a saved text without an acceptance counts
        # against the limit; the same id sent again completes it (3.5).
        self.accept(max_dispatches=1)
        launch_id, _ = self.open()
        d1 = fx.new_uuid()
        with pipeline_store.Pipeline(self.base, self.tid, create=True) as p:
            p.write_text(d1, "left by a crash".encode())
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=fx.new_uuid(),
                     text="another", approval={"kind": "preview", "id": "p"})
        self.assertFalse(r["ok"])
        self.assertIn("派工則數", r["error"]["message"])
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1,
                     text="left by a crash", approval={"kind": "preview", "id": "p"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["status"], "accepted")

    def test_an_invalid_turn_stops_dispatching(self):
        # Part 2 review A-1: the result says error, the lifecycle completes;
        # the turn is invalid, so the session takes nothing more (design 6).
        launch_id, _ = self.open("is_error")
        d1 = self.dispatch(launch_id)
        t = self.wait_for(lambda: (x := self.turn_status(launch_id, d1)) and x["status"] == "ended" and x,
                          msg="turn ended")
        self.assertFalse(t["valid"])
        self.assertEqual(self.status(launch_id)["state"], "idle")
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=fx.new_uuid(),
                     text="下一則", approval={"kind": "preview", "id": "p"})
        self.assertFalse(r["ok"])
        self.assertIn("已停止", r["error"]["message"])                  # v29.8: held after the failure
        self.assertTrue(self.status(launch_id)["closed_reasons"])        # and the session itself is closed

    def test_dispatch_limit_counts_prepares(self):
        self.accept(max_dispatches=1)
        launch_id, _ = self.open()
        d1 = self.dispatch(launch_id)
        self.wait_for(lambda: (x := self.turn_status(launch_id, d1)) and x["status"] == "ended", msg="turn ended")
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=fx.new_uuid(),
                     text="two", approval={"kind": "preview", "id": "p"})
        self.assertFalse(r["ok"])
        self.assertIn("派工則數", r["error"]["message"])


class FailureTests(StreamCase):
    def run_mode(self, mode, expect_state, expect_failed=None, **patches):
        stack = [mock.patch.object(stream_session, k, v) for k, v in patches.items()]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)
        launch_id, _ = self.open(mode)
        dd = self.dispatch(launch_id)
        st = self.wait_for(lambda: (s := self.status(launch_id)) and s["state"] in expect_state and s,
                           msg=f"state {expect_state}")
        if expect_failed:
            t = next(x for x in st["dispatches"] if x["dispatch_id"] == dd)
            self.assertEqual(t["failed"], expect_failed)
        return launch_id, dd

    def test_process_exit_mid_turn(self):
        launch_id, _ = self.run_mode("exit", ("exited",), "process_exited")
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="cleanup")
        self.assertEqual(self.status(launch_id)["exit"]["returncode"], 3)

    def test_a_live_failure_counts_the_worst_case_for_the_next_open(self):
        # v29.7: no result, so the cost is unknown: the session's budget.
        launch_id, dd = self.run_mode("silent", ("error",), "not_confirmed", CONFIRM_DEADLINE=0.5)
        budget = self.manifest(launch_id)["budget_usd"]
        st = self.status(launch_id)
        self.assertEqual((st["unfinished"], st["counted_cost_usd"]), ([dd], budget))
        self.assertEqual(st["counted_responses"], acc.DEFAULT_LIMITS["executor_turn_max_responses"])
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="ended")
        nxt = self.prepare()["launch_id"]
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])
        self.assertIn("繼續", r["error"]["message"])                    # v29.8: the failure holds the flow
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])
        self.assertIn("額度", r["error"]["message"])                    # and the worst case used the budget

    def test_a_pipe_read_error_is_not_an_eof(self):
        # Review round 6 #3.
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        real = os.read

        def read(fd, n):
            if fd == s.stdout:
                raise OSError(5, "Input/output error")
            return real(fd, n)
        with mock.patch.object(stream_session.os, "read", read):
            self.dispatch(launch_id)
            self.wait_for(lambda: s.js.protocol_errors, msg="read error recorded")
        self.assertEqual(s.js.protocol_errors[0]["reason"], "pipe_read_error")
        self.assertIn("errno 5", s.js.protocol_errors[0]["detail"])
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="session ended")
        self.assertIn("pipe_read_error", json.loads((self.base / "holds" / self.fid).read_text())["reason"])

    def test_not_confirmed(self):
        self.run_mode("silent", ("error",), "not_confirmed", CONFIRM_DEADLINE=0.5)

    def test_no_completed(self):
        self.run_mode("no_completed", ("uncertain",), "no_completed", FINISH_DEADLINE=0.5)

    def test_no_progress(self):
        self.run_mode("slow", ("uncertain",), "no_progress", NO_PROGRESS=0.5)

    def test_bad_json_is_a_protocol_error(self):
        launch_id, dd = self.run_mode("bad_json", ("error",))
        self.assertIn("協定錯誤", " ".join(self.status(launch_id)["closed_reasons"]))

    def test_response_cap_ends_the_session(self):
        self.limits = {"executor_turn_max_responses": 3}
        self.accept()
        launch_id, dd = self.run_mode("many_responses", ("error", "exited"), "response_cap")
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="session ended")

    def test_stderr_over_limit(self):
        self.run_mode("stderr_flood", ("error", "exited"), STDERR_MAX=1024)

    def test_turn_event_limit(self):
        self.run_mode("ok", ("error", "exited"), TURN_EVENTS_MAX=3)


class PreparedFilesQuotaTests(StreamCase):
    """S2c: the console prepares a launch (manifest and settings) outside any
    reservation; opening it counts those files as used."""

    def test_opening_a_prepared_launch_counts_its_files(self):
        m = self.prepare()
        folder = Path(m["launch_dir"]["path"])
        files = sorted(p.name for p in folder.iterdir())
        self.assertEqual(files, ["manifest.json", "settings.json"])
        size = sum(p.stat().st_size for p in folder.iterdir())
        before = self.dm._ledger.used
        r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])
        self.assertEqual(self.dm._ledger.used - before, size)                       # exactly what was on disk
        self.assertIn(f"session:{m['launch_id']}", self.dm._ledger.reservations)    # and the reservation as before

    def test_a_folder_that_cannot_be_measured_grants_nothing_more(self):
        from vbear.runtime import daemon_stream
        m = self.prepare()
        with mock.patch.object(daemon_stream.StreamOps, "_prepared_bytes", return_value=None):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])
        self.assertIn("額度需要重新核算", self.dm._ledger.overrun)
        m2 = a.prepare_stream_launch(self.base, str(self.work), cli_binary=str(self.binary), cli_version="2.1.292",
                                     cli_identity=a.binary_identity(str(self.binary)), model_id=fx.MODEL,
                                     pipeline_id=self.fid, task_id=self.tid, allowed_root=str(self.tmp))
        self.scratches.append(m2["scratch"]["path"])
        self.rpc("stream_close", launch_id=m["launch_id"])
        self.wait_for(lambda: self.manifest(m["launch_id"])["state"] == "ended", msg="first session to end")
        r = self.rpc("open_stream", launch_id=m2["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn("額度", r["error"]["message"])


class ReviewDifferenceTests(StreamCase):
    """The two S2a-2 part-1 review differences that only the daemon can show."""

    def test_turn_too_big_for_the_journal_ends_in_error_and_review(self):
        # Difference 3: turn_result past the journal's line/node limit.
        launch_id, _ = self.open("huge_turn")
        self.dispatch(launch_id)
        # The daemon has to take in 12 000 events one by one (past the journal's
        # 100 000-node limit takes about that many; each costs 1-1.5 ms of
        # parsing and validation), so this is 13-18 s of work on an idle Mac and
        # more on a busy one: a bound for the work, not for one step of it.
        self.wait_for(lambda: (s := self.dm._streams.get(launch_id)) is None or s.state == "error",
                      timeout=HEAVY_TIMEOUT, msg="error state")
        self.wait_for(lambda: launch_id not in self.dm._streams, timeout=HEAVY_TIMEOUT, msg="session ended")
        m = json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())
        self.assertEqual(m["state"], "manual_review")
        self.assertIn("日誌無法寫入", m["retained_reason"])

    def test_a_session_without_an_outcome_is_kept_for_review(self):
        # R4 audit: nothing proves such a session ended cleanly.
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        real = s._finish

        def finish(**kw):
            real(**kw)
            s.outcome = None
        s._finish = finish
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="session ended")
        m = json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())
        self.assertEqual(m["state"], "manual_review")
        self.assertIn("沒有留下結果", m["retained_reason"])

    def test_pipeline_field_must_match_the_manifest(self):
        # Difference 4: both dispatch RPCs carry the flow and it must match.
        launch_id, _ = self.open()
        d1 = fx.new_uuid()
        bad = "flow-ffffffffffff"
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=bad, dispatch_id=d1, text="t",
                     approval={"kind": "preview", "id": "p"})
        self.assertFalse(r["ok"])
        self.assertIn("流程", r["error"]["message"])
        self.assertTrue(self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1,
                                 text="t", approval={"kind": "preview", "id": "p"})["ok"])
        for pipeline in (bad, None, 5, self.fid + "\n"):
            with self.subTest(pipeline=pipeline):
                r = self.rpc("stream_send", launch_id=launch_id, pipeline=pipeline, dispatch_id=d1)
                self.assertFalse(r["ok"])
        r = self.rpc("stream_send", launch_id=launch_id, dispatch_id=d1)
        self.assertFalse(r["ok"])                                    # the field is required
        self.assertTrue(self.rpc("stream_send", launch_id=launch_id, pipeline=self.fid, dispatch_id=d1)["ok"])


class JournalOrderTests(StreamCase):
    """Planner, S2a-2 R2: the journal (with session_started) exists before
    the process is spawned, so a launch without a journal never had one;
    and a journal write failure puts the session in error."""

    def test_journal_is_written_before_the_process_starts(self):
        import vbear.runtime.daemon_stream as ds
        real = ds.subprocess.Popen
        seen = {}

        def spy(argv, **kw):
            launch = Path(kw["cwd"])
            ldirs = [p for p in (self.base / "sessions").iterdir() if (p / "journal.jsonl").exists()]
            seen["journals"] = [json.loads(l)["kind"] for p in ldirs for l in (p / "journal.jsonl").read_text().splitlines()]
            seen["state"] = [json.loads((p / "manifest.json").read_text())["state"] for p in ldirs]
            return real(argv, **kw)
        with mock.patch.object(ds.subprocess, "Popen", spy):
            launch_id, _ = self.open()
        self.assertEqual(seen["journals"], ["session_started"])
        self.assertEqual(seen["state"], ["launching"])

    def test_a_journal_that_cannot_be_started_is_kept_for_review(self):
        import vbear.runtime.daemon_stream as ds
        m = self.prepare()
        with mock.patch.object(ds.stream_journal.JournalWriter, "append",
                               side_effect=OSError(28, "No space left on device")), \
                mock.patch.object(ds.subprocess, "Popen") as popen:
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        popen.assert_not_called()
        man = self.manifest(m["launch_id"])
        self.assertEqual(man["state"], "manual_review")                   # not "ended"
        self.assertIn("日誌無法寫入", man["retained_reason"])
        self.assertNotIn(f"session:{m['launch_id']}", self.dm._ledger.reservations)

    def test_unexpected_record_exception_errors_session_and_holds_flow(self):
        import vbear.runtime.daemon_stream as ds
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        real_append = s.writer.append

        def fail_result(kind, data):
            if kind == "turn_result":
                raise ValueError("synthetic serializer failure")
            return real_append(kind, data)

        with mock.patch.object(s.writer, "append", side_effect=fail_result):
            self.dispatch(launch_id)
            self.wait_for(lambda: s.state == "error", msg="session error")
            self.wait_for(lambda: launch_id not in self.dm._streams, msg="failed stream finalized")
        self.assertTrue(self.dm._sel is not None)                 # daemon loop resources remain alive
        self.assertTrue(ds.pipeline_store.is_held(self.base, self.fid))
        self.assertEqual(self.manifest(launch_id)["state"], "manual_review")

    def test_nested_surrogate_event_is_contained_and_holds_flow(self):
        # The original review finding, end to end: before ae56eb7 this turn
        # passed the tracker and its journal record ended the daemon loop
        # (UnicodeEncodeError from canonical()).
        import vbear.runtime.daemon_stream as ds
        launch_id, _ = self.open("surrogate_so")
        d1 = self.dispatch(launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams or self.dm._streams[launch_id].state == "error",
                      msg="session in error")
        self.assertTrue(self.thread.is_alive(), "the daemon loop ended")
        self.assertTrue(self.rpc("hello")["ok"])
        self.wait_for(lambda: ds.pipeline_store.is_held(self.base, self.fid), msg="held")
        t = self.turn_status(launch_id, d1)
        self.assertNotIn("report", t)
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="closed")

    def test_at_spawn_the_flow_counts_this_launch(self):
        # The prepared exception (a launch without a journal never had a
        # process): at the moment of spawn the start record and the journal
        # exist, and the flow's totals include this launch.
        import vbear.runtime.daemon_stream as ds
        from vbear.runtime import stream_flow
        real = ds.subprocess.Popen
        seen = {}

        def spy(argv, **kw):
            ctx = stream_flow.load(self.base, self.fid)
            seen["sessions"] = [x["launch_id"] for x in ctx.totals.sessions]
            seen["started"] = ctx.started_at is not None
            return real(argv, **kw)
        m = self.prepare()
        with mock.patch.object(ds.subprocess, "Popen", spy):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(seen, {"sessions": [m["launch_id"]], "started": True})

    def test_the_first_start_records_the_work_directorys_head(self):
        # v29.9: the origin of a review's range, read from files, never git.
        self.open()
        rec = json.loads((self.base / "pipelines" / self.tid / "started.json").read_text())
        self.assertEqual((rec["v"], rec["base_commit"]), (2, fx.BASE_COMMIT))

    def test_an_unreadable_head_refuses_the_first_start(self):
        for name, damage in (("no repository", lambda: shutil.rmtree(self.work / ".git")),
                             ("HEAD is not a commit", lambda: (self.work / ".git" / "HEAD").write_text("nonsense\n")),
                             ("HEAD is a dangling ref",
                              lambda: (self.work / ".git" / "HEAD").write_text("ref: refs/heads/none\n"))):
            with self.subTest(case=name):
                fx.fake_repo(self.work)
                damage()
                m = self.prepare()
                r = self.rpc("open_stream", launch_id=m["launch_id"])
                self.assertFalse(r["ok"])
                self.assertIn("HEAD", r["error"]["message"])
                self.assertFalse((self.base / "pipelines" / self.tid / "started.json").exists())
                self.assertEqual(self.manifest(m["launch_id"])["state"], "prepared")
                shutil.rmtree(self.base / "sessions" / m["launch_id"], ignore_errors=True)

    def test_a_failed_start_record_leaves_the_launch_prepared(self):
        import vbear.runtime.daemon_stream as ds
        m = self.prepare()
        with mock.patch.object(ds.pipeline_store.Pipeline, "record_start",
                               side_effect=pipeline_store.StoreRefused("disk")), \
                mock.patch.object(ds.subprocess, "Popen") as popen:
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        popen.assert_not_called()
        ldir = self.base / "sessions" / m["launch_id"]
        self.assertEqual(json.loads((ldir / "manifest.json").read_text())["state"], "prepared")
        self.assertFalse(os.path.lexists(ldir / "journal.jsonl"))
        self.assertNotIn(f"session:{m['launch_id']}", self.dm._ledger.reservations)

    def test_a_failure_after_launching_does_not_strand_the_launch(self):
        import vbear.runtime.daemon_stream as ds
        for where in ("load_validated", "journal"):
            with self.subTest(where=where):
                m = self.prepare()
                calls = {"n": 0}
                real_load = ds.agent_sessions.load_validated

                def load(base, launch_id):
                    calls["n"] += 1
                    if calls["n"] == 2:               # the re-check after "launching"
                        raise ds.agent_sessions.LaunchRefused("drift", "test")
                    return real_load(base, launch_id)
                patches = ([mock.patch.object(ds.agent_sessions, "load_validated", load)] if where == "load_validated"
                           else [mock.patch.object(ds.stream_journal, "JournalWriter",
                                                   side_effect=OSError(28, "No space left on device"))])
                with patches[0], mock.patch.object(ds.subprocess, "Popen") as popen:
                    r = self.rpc("open_stream", launch_id=m["launch_id"])
                self.assertFalse(r["ok"])
                popen.assert_not_called()
                self.assertFalse((self.base / "sessions" / m["launch_id"]).exists())   # never ran: removed
                self.assertNotIn(f"session:{m['launch_id']}", self.dm._ledger.reservations)
                self.assertFalse((self.base / "pipelines" / self.tid / "started.json").exists())  # not started
        launch_id, _ = self.open()                                            # the flow is not stuck
        self.assertTrue((self.base / "pipelines" / self.tid / "started.json").exists())

    def test_spawn_failure_leaves_a_complete_journal(self):
        import vbear.runtime.daemon_stream as ds
        m = self.prepare()
        with mock.patch.object(ds.subprocess, "Popen", side_effect=OSError(8, "Exec format error")):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        ldir = self.base / "sessions" / m["launch_id"]
        kinds = [json.loads(l)["kind"] for l in (ldir / "journal.jsonl").read_text().splitlines()]
        self.assertEqual(kinds, ["session_started", "protocol_error", "exited"])   # spawn_failed (round 7)
        self.assertEqual(json.loads((ldir / "manifest.json").read_text())["state"], "ended")
        self.assertNotIn(f"session:{m['launch_id']}", self.dm._ledger.reservations)

    def test_a_journal_write_failure_is_an_error(self):
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        real_append = s.writer.append

        def failing(kind, data):
            if kind == "dispatch_confirmed":
                raise OSError(28, "No space left on device")
            return real_append(kind, data)
        s.writer.append = failing
        self.dispatch(launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams or self.dm._streams[launch_id].state == "error",
                      msg="error")
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="ended")
        m = json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())
        self.assertEqual(m["state"], "manual_review")
        self.assertIn("日誌無法寫入", m["retained_reason"])


class ProcessTests(StreamCase):
    def test_shutdown_timeout_keeps_the_unproven_leader_owned(self):
        import vbear.runtime.daemon_stream as ds
        launch_id, _ = self.open("hang")
        s = self.dm._streams[launch_id]
        proc = s.proc
        s.terminate = mock.Mock()
        s.tick = mock.Mock()
        s._killpg = mock.Mock()
        with mock.patch.object(ds.time, "monotonic", side_effect=(0.0, 10.0)):
            self.dm._kill_all_streams()
        self.assertNotIn(launch_id, self.dm._streams)
        self.assertTrue(any(h["proc"] is proc and h["launch_id"] == launch_id
                            for h in self.dm._held_leaders))
        self.assertTrue(pipeline_store.is_held(self.base, self.fid))

    def test_shutdown_continues_when_failure_hold_write_raises(self):
        import vbear.runtime.daemon_stream as ds
        launch_id, _ = self.open("hang")
        s = self.dm._streams[launch_id]
        proc = s.proc
        s.terminate = mock.Mock()
        s.tick = mock.Mock()
        s._killpg = mock.Mock()
        with mock.patch.object(ds.time, "monotonic", side_effect=(0.0, 10.0)), \
                mock.patch.object(self.dm, "_hold_for_failure", side_effect=ValueError("synthetic hold failure")):
            self.dm._kill_all_streams()
        self.assertNotIn(launch_id, self.dm._streams)
        self.assertTrue(any(h["proc"] is proc and h["launch_id"] == launch_id
                            for h in self.dm._held_leaders))

    def test_leader_is_not_reaped_while_its_group_lives(self):
        """Design 5.8: the exit is seen with waitid(WNOWAIT); the leader stays
        a zombie (its PID and group id cannot be reused) until the rest of
        the group is gone, then it is reaped."""
        stack = [mock.patch.object(stream_session, "TERM_GRACE", 3.0)]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)
        launch_id, _ = self.open("child_then_exit")
        leader = self.launched()["pid"]
        self.dispatch(launch_id)
        self.wait_for(lambda: (self.work / "child-started").exists(), msg="child")
        s = self.wait_for(lambda: (x := self.dm._streams.get(launch_id)) and x.exit_recorded and x, msg="exit seen")
        stat = subprocess.run(["ps", "-o", "stat=", "-p", str(leader)], capture_output=True, text=True).stdout.strip()
        self.assertIn("Z", stat, "the exited leader must still be an unreaped zombie")
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="group cleaned")
        stat = subprocess.run(["ps", "-o", "stat=", "-p", str(leader)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(stat, "", "reaped after cleanup")
        self.assertEqual(json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())["state"],
                         "ended")

    def test_escaped_descendant_means_manual_review(self):
        launch_id, _ = self.open("escape_then_exit")
        self.dispatch(launch_id)
        pid = int(self.wait_for(lambda: (self.work / "escaped.pid").exists()
                                and (self.work / "escaped.pid").read_text(), msg="escaped child"))
        self.pids.append(pid)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="session finished")
        m = json.loads((self.base / "sessions" / launch_id / "manifest.json").read_text())
        self.assertEqual(m["state"], "manual_review")
        os.kill(pid, 0)                                   # not chased: still alive

    def test_the_manifest_is_final_before_the_session_leaves_tracking(self):
        # The planner's flaky run: a session gone from _streams while its
        # manifest still said "running". The manifest is written first now.
        launch_id, _ = self.open()
        seen = {}
        manifest = self.manifest

        class Watch(dict):
            def pop(inner, key, *default):
                if key == launch_id:
                    seen["state"] = manifest(launch_id)["state"]
                return dict.pop(inner, key, *default)
        self.dm._streams = Watch(self.dm._streams)
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="ended")
        self.assertEqual(seen["state"], "ended")

    def unproven_group(self, group_members):
        """Review B-1: the leader exits, but the group cannot be proven
        empty; the leader must not be reaped until it is."""
        import vbear.runtime.daemon_stream as ds
        launch_id, _ = self.open()
        pid = self.launched()["pid"]
        reaped = []
        real_waitpid = os.waitpid

        def waitpid(p, opts):
            reaped.append(p)
            return real_waitpid(p, opts)
        with mock.patch.object(stream_session.StreamSession, "_group_members", group_members), \
                mock.patch.object(stream_session, "KILL_GIVE_UP", 0.2), \
                mock.patch.object(stream_session, "TABLE_GIVE_UP", 0.2), \
                mock.patch.object(stream_session, "TERM_GRACE", 0.2), \
                mock.patch.object(stream_session, "KILL_GRACE", 0.2), \
                mock.patch.object(ds, "HELD_RECHECK", 3600.0), \
                mock.patch.object(stream_session.os, "waitpid", waitpid):
            self.rpc("stream_close", launch_id=launch_id)
            self.wait_for(lambda: launch_id not in self.dm._streams, msg="given up")
            self.assertNotIn(pid, reaped)
        m = self.manifest(launch_id)
        self.assertEqual(m["state"], "manual_review")
        self.assertTrue(stream_session.leader_exited(pid))                   # a zombie, still our child
        self.assertIn(pid, [h["pid"] for h in self.dm._held_leaders])
        # later the group is proven empty: only then is the leader reaped
        self.dm._held_next = 0.0
        self.wait_for(lambda: pid not in [h["pid"] for h in self.dm._held_leaders], msg="reaped later")
        self.assertFalse(stream_session.leader_exited(pid))                  # gone: reaped
        return m

    def test_members_alive_after_sigkill_keep_the_leader_unreaped(self):
        fake = {"pid": 2, "ppid": 1, "pgid": 0, "uid": os.getuid(), "stat": "R", "start": "1.000000"}

        def members(s):
            return [dict(fake, pgid=s.pgid)], []
        m = self.unproven_group(members)
        self.assertIn("SIGKILL 後仍有程序存活", m["retained_reason"])

    def test_no_process_table_keeps_the_leader_unreaped(self):
        m = self.unproven_group(lambda s: (None, None))
        self.assertIn("無法取得程序表", m["retained_reason"])

    def test_existing_managed_sessions_are_unchanged(self):
        """A PTY-managed Claude launch next to a stream session behaves as
        before: opened by open_managed, closed by close, cleaned up."""
        launch_id, _ = self.open()
        pty_bin = self.tmp / "claude-pty"
        pty_bin.write_text(FAKE_PTY_CLI % {"py": sys.executable})
        pty_bin.chmod(0o700)
        pty_work = self.tmp / "pty-work"
        pty_work.mkdir()
        m = a.prepare_claude_launch(self.base, str(pty_work), cli_binary=str(pty_bin), cli_version="2.1.292",
                                    cli_identity=a.binary_identity(str(pty_bin)), allowed_root=str(self.tmp))
        self.scratches.append(m["scratch"]["path"])
        r = self.rpc("open_managed", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        sid = r["result"]["session_id"]
        self.assertTrue(self.rpc("close", session_id=sid)["ok"])
        self.assertFalse(Path(m["launch_dir"]["path"]).exists())          # removed, as before
        self.assertEqual(self.status(launch_id)["state"], "idle")         # the stream session is untouched


class RecoveryTests(StreamCase):
    """Design v29.7 (part 2 review B1, B3): what a restarted daemon finds."""

    def mid_turn_crash(self):
        launch_id, _ = self.open("hang")
        pid = self.launched()["pid"]
        d1 = self.dispatch(launch_id)
        self.wait_for(lambda: (self.work / "hang-ready").exists(), msg="turn in flight")
        self.wait_for(lambda: self.dm._streams[launch_id].js.state == "running", msg="confirmed")
        budget = self.manifest(launch_id)["budget_usd"]
        self.crash_daemon()
        return launch_id, pid, d1, budget

    def assert_worst_case(self, launch_id, d1, budget, process):
        res = self.journal(launch_id)
        self.assertEqual(res.problem, "")
        self.assertEqual(res.state.recovered, {"process": process})
        self.assertEqual(res.state.turns[d1].failed, "daemon_restart")
        from vbear.runtime import stream_flow
        ctx = stream_flow.load(self.base, self.fid)
        self.assertEqual(ctx.totals.responses, acc.DEFAULT_LIMITS["executor_turn_max_responses"])
        self.assertAlmostEqual(ctx.totals.spent_usd, budget)

    def test_daemon_killed_mid_turn_cli_still_running(self):
        launch_id, pid, d1, budget = self.mid_turn_crash()
        self.restart_daemon()
        self.assert_worst_case(launch_id, d1, budget, "alive")
        m = self.manifest(launch_id)
        self.assertEqual(m["state"], "manual_review")
        self.assertIn("仍有已記錄的程序存活", m["retained_reason"])
        os.kill(pid, 0)                                          # recovery never signals

    def test_daemon_killed_mid_turn_cli_gone(self):
        launch_id, pid, d1, budget = self.mid_turn_crash()
        os.kill(pid, 9)
        self.wait_for(lambda: stream_session.leader_exited(pid), msg="CLI gone")
        self.restart_daemon()
        self.assert_worst_case(launch_id, d1, budget, "gone")
        self.assertEqual(self.manifest(launch_id)["state"], "ended")
        # held by the failure (v29.8); after "continue", the worst case has
        # used up the budget, so the next open is still refused
        nxt = self.prepare()["launch_id"]
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])
        self.assertIn("繼續", r["error"]["message"])
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])
        self.assertIn("額度", r["error"]["message"])

    def on_disk_session(self, records):
        """A stream launch as a dead daemon left it: manifest running with a
        leader that is gone, and a journal with ``records`` after the start."""
        from vbear.runtime import stream_journal
        gone = subprocess.Popen(["/usr/bin/true"])
        gone.wait()
        leader_pid = gone.pid                     # exited; with this start time it can match no process
        m = self.prepare()
        launch_id, sid = m["launch_id"], fx.new_uuid()
        a.update_manifest(self.base, launch_id, state="running", claude_session_id=sid, budget_usd=3.25,
                          native_session_id="n-0123456789ab",
                          leader={"pid": leader_pid, "start": f"{int(time.time()) - 60}.000000",
                                  "source": stream_session.proctrack.SOURCE})
        fd = os.open(self.base / "sessions" / launch_id, os.O_RDONLY | os.O_DIRECTORY)
        try:
            w = stream_journal.JournalWriter(fd)
        finally:
            os.close(fd)
        w.append("session_started", {"claude_session_id": sid, "pipeline_id": self.fid, "cli_version": "2.1.292",
                                     "argv_sha256": "a" * 64, "budget_usd": 3.25})
        for kind, data in records:
            w.append(kind, data)
        w.close()
        with pipeline_store.Pipeline(self.base, self.tid, create=True) as p:
            p.record_start(self.fid, time.time(), launch_id=launch_id, base_commit=fx.BASE_COMMIT)
        return launch_id

    def test_crash_between_writing_and_written(self):
        d1, text = fx.new_uuid(), "請完成工作"
        launch_id = self.on_disk_session([
            ("dispatch_accepted", {"dispatch_id": d1, "text_sha256": sp.sha256_hex(text.encode()),
                                   "length": len(text.encode()), "approval": {"kind": "preview", "id": "p"}}),
            ("dispatch_writing", {"dispatch_id": d1, "turn_cap": 17})])
        with pipeline_store.Pipeline(self.base, self.tid, create=False) as p:
            p.write_text(d1, text.encode())
        self.crash_daemon()
        self.restart_daemon()
        res = self.journal(launch_id)
        self.assertEqual((res.state.recovered, res.state.turns[d1].failed), ({"process": "gone"}, "daemon_restart"))
        self.assertEqual(self.manifest(launch_id)["state"], "ended")
        from vbear.runtime import stream_flow
        ctx = stream_flow.load(self.base, self.fid)
        self.assertEqual((ctx.totals.responses, ctx.totals.spent_usd), (17, 3.25))

    def test_an_unrecorded_group_member_keeps_the_launch(self):
        # Review round 5 B-1: the leader is gone, but its group still has a
        # process the manifest never recorded.
        launch_id = self.on_disk_session([])
        leader = self.manifest(launch_id)["leader"]["pid"]
        real = stream_session.proctrack.process_table

        def table():
            return real() + [{"pid": 99990, "ppid": 1, "pgid": leader, "uid": os.getuid(), "stat": "R",
                              "start": f"{int(time.time())}.000000"}]
        self.crash_daemon()
        with mock.patch.object(a.proctrack, "process_table", table):
            self.restart_daemon()
        m = self.manifest(launch_id)
        self.assertEqual(m["state"], "manual_review")                        # not cleaned up
        self.assertIn("未記錄的程序", m["retained_reason"])
        self.assertEqual(self.journal(launch_id).state.recovered, {"process": "alive"})

    def test_an_unknown_recovery_stays_a_failure_after_cleanup(self):
        # Review round 6 #2: the first recovery could not hold the flow nor
        # write the manifest; a later one cleans up; the failure remains.
        from vbear.runtime import pipeline_store as ps
        launch_id = self.on_disk_session([])
        self.crash_daemon()
        with mock.patch.object(a.proctrack, "process_table",
                               side_effect=a.proctrack.ProcessTableUnavailable("test")), \
                mock.patch.object(ps, "hold", side_effect=OSError(5, "Input/output error")), \
                mock.patch.object(a, "update_manifest", side_effect=OSError(5, "Input/output error")):
            self.restart_daemon()
        self.assertEqual(self.journal(launch_id).state.recovered, {"process": "unknown"})
        self.assertEqual(self.manifest(launch_id)["state"], "running")          # nothing else was written
        self.assertFalse((self.base / "holds" / self.fid).exists())
        self.crash_daemon()
        self.restart_daemon()                                                   # now provably gone: cleaned
        self.assertEqual(self.manifest(launch_id)["state"], "ended")
        (self.base / "holds" / self.fid).unlink(missing_ok=True)
        r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn("狀態不明", r["error"]["message"])

    def test_a_damaged_journal_is_kept_for_review(self):
        launch_id = self.on_disk_session([])
        path = self.base / "sessions" / launch_id / "journal.jsonl"
        damaged = path.read_bytes()[:-5] + b"xxxx\n"
        path.write_bytes(damaged)
        self.crash_daemon()
        self.restart_daemon()
        m = self.manifest(launch_id)
        self.assertEqual(m["state"], "manual_review")                       # not ended
        self.assertIn("日誌無法使用", m["retained_reason"])
        self.assertEqual(path.read_bytes(), damaged)                         # nothing written
        from vbear.runtime import stream_flow
        with self.assertRaises(stream_flow.FlowRefused):
            stream_flow.load(self.base, self.fid)

    def test_crash_right_after_the_start_record(self):
        # B3: the open died after record_start, before anything else changed.
        m = self.prepare()
        with pipeline_store.Pipeline(self.base, self.tid, create=True) as p:
            p.record_start(self.fid, time.time(), launch_id=m["launch_id"], base_commit=fx.BASE_COMMIT)
        from vbear.runtime import stream_flow
        with self.assertRaises(stream_flow.FlowRefused):                     # stuck until recovery
            stream_flow.load(self.base, self.fid)
        self.crash_daemon()
        self.restart_daemon()
        self.assertFalse((self.base / "pipelines" / self.tid / "started.json").exists())
        r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])

    def test_crash_after_launching_before_the_journal(self):
        m = self.prepare()
        with pipeline_store.Pipeline(self.base, self.tid, create=True) as p:
            p.record_start(self.fid, time.time(), launch_id=m["launch_id"], base_commit=fx.BASE_COMMIT)
        a.update_manifest(self.base, m["launch_id"], state="launching", claude_session_id=fx.new_uuid(),
                          budget_usd=5.0)
        self.crash_daemon()
        self.restart_daemon()
        self.assertFalse((self.base / "sessions" / m["launch_id"]).exists())     # never ran: removed
        self.assertFalse((self.base / "pipelines" / self.tid / "started.json").exists())
        self.open()                                                           # the flow opens again


class SetupFailureTests(StreamCase):
    """Part 2 review B2: a failure after Popen leaves no unmanaged process."""

    def stream_keys(self):
        return [k for k in self.dm._sel.get_map().values() if isinstance(k.data, tuple) and k.data[0] == "stream"]

    def spawned(self):
        """Records the pid at Popen: the group may be killed before the fake
        CLI has written anything."""
        import vbear.runtime.daemon_stream as ds
        real, pids = ds.subprocess.Popen, []

        def spy(*args, **kw):
            proc = real(*args, **kw)
            pids.append(proc.pid)
            return proc
        return mock.patch.object(ds.subprocess, "Popen", spy), pids

    def check_ended(self, m, r, pids):
        self.assertFalse(r["ok"])
        self.assertIn("啟動後初始化失敗", r["error"]["message"])
        pid, = pids
        self.pids.append(pid)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)                                   # killed and reaped
        ldir = self.base / "sessions" / m["launch_id"]
        kinds = [json.loads(x)["kind"] for x in (ldir / "journal.jsonl").read_text().splitlines()]
        self.assertEqual(kinds, ["session_started", "protocol_error", "exited"])   # spawn_failed (round 7)
        self.assertEqual(self.manifest(m["launch_id"])["state"], "ended")
        self.assertNotIn(m["launch_id"], self.dm._streams)
        self.assertNotIn(f"session:{m['launch_id']}", self.dm._ledger.reservations)
        self.assertEqual(self.stream_keys(), [])

    def test_set_blocking_fails(self):
        m = self.prepare()
        spy, pids = self.spawned()
        with spy, mock.patch("vbear.runtime.stream_session.os.set_blocking", side_effect=OSError(9, "Bad file")):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.check_ended(m, r, pids)

    def test_selector_registration_fails_half_way(self):
        m = self.prepare()
        real = self.dm._register_stream

        def register(s, which):
            if which == "stderr":                            # stdout is already registered
                raise OSError(24, "Too many open files")
            return real(s, which)
        spy, pids = self.spawned()
        with spy, mock.patch.object(self.dm, "_register_stream", side_effect=register):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.check_ended(m, r, pids)

    def test_no_leader_identity_means_no_signal(self):
        m = self.prepare()
        with mock.patch.object(stream_session, "capture_leader", return_value=None):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        pid = self.launched()["pid"]
        self.pids.append(pid)
        man = self.manifest(m["launch_id"])
        self.assertEqual(man["state"], "manual_review")
        self.assertIn("不送訊號", man["retained_reason"])


class SignalIdentityTests(StreamCase):
    """Part 2 review B6: before any signal, the leader is checked (design 2.3)."""

    def test_leader_start_is_recorded_at_launch(self):
        launch_id, _ = self.open()
        pid = self.launched()["pid"]
        row = next(r for r in stream_session.proctrack.process_table() if r["pid"] == pid)
        self.assertEqual(self.manifest(launch_id)["leader"]["start"], row["start"])
        self.assertEqual(self.dm._streams[launch_id].leader_start, row["start"])

    def refused(self, why, break_identity):
        launch_id, _ = self.open()
        pid = self.launched()["pid"]
        s = self.dm._streams[launch_id]
        with break_identity(s):
            self.rpc("stream_close", launch_id=launch_id)
            self.wait_for(lambda: launch_id not in self.dm._streams, msg="given up")
        m = self.manifest(launch_id)
        self.assertEqual(m["state"], "manual_review")
        self.assertIn("不送訊號", m["retained_reason"])
        self.assertIn(why, m["retained_reason"])
        return pid

    def test_a_different_start_time_sends_nothing(self):
        import contextlib

        @contextlib.contextmanager
        def other_start(s):
            s.leader_start = "1600000000.000000"
            yield
        self.refused("開始時間", other_start)
        time.sleep(0.5)
        self.assertFalse((self.work / "got-sigterm").exists())   # never signalled

    def test_no_process_table_sends_nothing(self):
        def unavailable(s):
            return mock.patch.object(stream_session.proctrack, "process_table",
                                     side_effect=stream_session.proctrack.ProcessTableUnavailable("test"))
        self.refused("無法取得程序表", unavailable)
        time.sleep(0.5)
        self.assertFalse((self.work / "got-sigterm").exists())

    def test_an_exited_leader_is_checked_as_our_unreaped_child(self):
        launch_id, _ = self.open("child_then_exit")
        pid = self.launched()["pid"]
        self.dispatch(launch_id)
        self.wait_for(lambda: stream_session.leader_exited(pid), msg="leader exited")
        self.assertIsNone(stream_session.leader_check(pid, pid, self.dm._streams[launch_id].leader_start))
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="group killed")
        self.assertEqual(self.manifest(launch_id)["state"], "ended")


class FlowConcurrencyTests(StreamCase):
    """Part 2 review A-1: one flow, at most one stream session not ended."""

    def test_a_second_session_of_the_flow_is_refused(self):
        first, _ = self.open()
        second = self.prepare()["launch_id"]
        r = self.rpc("open_stream", launch_id=second)
        self.assertFalse(r["ok"])
        self.assertIn("尚未結束的串流 session", r["error"]["message"])
        self.assertIn(first, r["error"]["message"])
        self.assertEqual(self.manifest(second)["state"], "prepared")      # untouched, can open later
        self.rpc("stream_close", launch_id=first)
        self.wait_for(lambda: first not in self.dm._streams, msg="first ended")
        self.assertEqual(self.manifest(first)["state"], "ended")
        r = self.rpc("open_stream", launch_id=second)
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])

    def test_manual_review_blocks_until_a_person_resolves_it(self):
        first, _ = self.open()
        a._retain(self.base, first, "test")                               # as after an escaped child
        self.dm._streams.pop(first)
        r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn(first, r["error"]["message"])


class JournalFailureStatusTests(StreamCase):
    """Part 2 review A-2: after a failed append the state in memory is not
    what the disk holds; status must not report from it."""

    def test_a_completed_that_never_reached_the_disk_is_not_valid(self):
        from vbear.runtime import stream_journal
        real_write = os.write

        def write(fd, data):
            if b'"kind":"turn_lifecycle"' in bytes(data) and b'"state":"completed"' in bytes(data):
                raise OSError(28, "No space left on device")
            return real_write(fd, data)
        launch_id, _ = self.open()
        with mock.patch.object(stream_session.StreamSession, "terminate"), \
                mock.patch.object(stream_journal.os, "write", write):
            d1 = self.dispatch(launch_id)
            self.wait_for(lambda: self.dm._streams[launch_id].journal_broken, msg="append failed")
            s = self.dm._streams[launch_id]
            self.assertEqual(s.js.turns[d1].status, "ended")              # memory ran ahead of the disk
            st = self.status(launch_id)
        self.assertTrue(st["live"])
        self.assertIn("No space left", st["journal_write_failed"])
        t = next(x for x in st["dispatches"] if x["dispatch_id"] == d1)
        self.assertNotEqual(t["status"], "ended")
        self.assertFalse(t["valid"])
        self.assertNotIn("report", t)
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="ended")
        t = next(x for x in self.status(launch_id)["dispatches"] if x["dispatch_id"] == d1)
        self.assertNotIn("report", t)


class HoldTests(StreamCase):
    """Part 2 review A-3 / design v29.1: after a hold every dispatch RPC is
    refused, an idempotent repeat included; the status rides along."""

    def test_pipeline_hold_requires_a_string_reason(self):
        for kwargs in ({"pipeline": self.fid}, {"pipeline": self.fid, "reason": None},
                       {"pipeline": self.fid, "reason": 1}):
            with self.subTest(kwargs=kwargs):
                r = self.rpc("pipeline_hold", **kwargs)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "bad_request")
                self.assertFalse((self.base / "holds" / self.fid).exists())

    def test_idempotent_repeats_recheck_the_acceptance(self):
        # Review round 4 #3: a repeat is answered only when a new request
        # would pass the acceptance and limits; nothing is sent either way.
        launch_id, _ = self.open()
        d1 = self.dispatch(launch_id)
        self.wait_for(lambda: (x := self.turn_status(launch_id, d1)) and x["status"] == "ended", msg="turn ended")
        d2 = fx.new_uuid()
        prep = dict(dispatch_id=d2, text="二", approval={"kind": "preview", "id": "p2"})
        self.assertTrue(self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, **prep)["ok"])
        (self.base / login_identity.KEY_NAME).unlink()                     # the key changes: no valid acceptance
        self.key = login_identity.create_login_key(self.base, valid_acceptances=0)
        for op, kw, status in (("dispatch_prepare", prep, "accepted"), ("stream_send", dict(dispatch_id=d1), "ended")):
            with self.subTest(op=op):
                r = self.rpc(op, launch_id=launch_id, pipeline=self.fid, **kw)
                self.assertFalse(r["ok"])
                self.assertIn("no_acceptance", r["error"]["message"])
                self.assertEqual(r["error"]["dispatch_status"], status)
        self.assertEqual(self.turn_status(launch_id, d2)["status"], "accepted")   # nothing was sent

    def test_idempotent_repeats_are_refused_after_a_hold(self):
        launch_id, _ = self.open()
        d1 = self.dispatch(launch_id)
        self.wait_for(lambda: (x := self.turn_status(launch_id, d1)) and x["status"] == "ended", msg="turn ended")
        d2 = fx.new_uuid()
        r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d2, text="二",
                     approval={"kind": "preview", "id": "p2"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.rpc("pipeline_hold", pipeline=self.fid, reason="stop")["ok"])
        cases = [("dispatch_prepare", dict(dispatch_id=d2, text="二", approval={"kind": "preview", "id": "p2"}),
                  "accepted"),
                 ("stream_send", dict(dispatch_id=d1), "ended"),
                 ("stream_send", dict(dispatch_id=d2), "accepted")]
        for op, kw, status in cases:
            with self.subTest(op=op, status=status):
                r = self.rpc(op, launch_id=launch_id, pipeline=self.fid, **kw)
                self.assertFalse(r["ok"])
                self.assertIn("已停止", r["error"]["message"])
                self.assertEqual(r["error"]["dispatch_status"], status)
        self.assertEqual(self.turn_status(launch_id, d2)["status"], "accepted")   # nothing was sent


class FailureHoldTests(StreamCase):
    """Design v29.8: one failure stops the flow until the user's "continue"."""

    def fresh_flow(self):
        self.tid = tasks.save_task(None, {"title": "t"})["id"]
        roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
                 "reviewers": [{"name": "c", "family": "openai"}]}
        self.fid = flows.create_flow({"task_id": self.tid, "roles": roles}, lambda t: True)["id"]
        self.accept()

    def hold_reason(self):
        path = self.base / "holds" / self.fid
        return json.loads(path.read_text())["reason"] if path.exists() else None

    def fail_once(self, mode, **patches):
        stack = [mock.patch.object(stream_session, k, v) for k, v in patches.items()]
        for p in stack:
            p.start()
        try:
            launch_id, _ = self.open(mode)
            self.dispatch(launch_id)
            self.wait_for(lambda: (self.hold_reason() or "").startswith("failure"), msg=f"held after {mode}")
            self.rpc("stream_close", launch_id=launch_id)
            self.wait_for(lambda: launch_id not in self.dm._streams, msg="closed")
        finally:
            for p in stack:
                p.stop()
        return launch_id

    def test_every_failure_holds_the_flow(self):
        cases = {"dispatch failed (not confirmed)": ("silent", {"CONFIRM_DEADLINE": 0.5}),
                 "invalid turn": ("is_error", {}),
                 "protocol error": ("bad_json", {}),
                 "ended for manual review": ("escape_then_exit", {})}
        for name, (mode, patches) in cases.items():
            with self.subTest(failure=name):
                self.fresh_flow()                 # a worst case uses up a flow's budget: one flow per case
                launch_id = self.fail_once(mode, **patches)
                self.assertIn(launch_id, self.hold_reason())
                if mode == "escape_then_exit":
                    self.pids.append(int((self.work / "escaped.pid").read_text()))
                self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
                if mode == "escape_then_exit":           # a person resolves the kept launch
                    shutil.rmtree(self.base / "sessions" / launch_id)

    def test_release_order_and_a_lost_hold_file(self):
        launch_id, _ = self.open("is_error")
        self.dispatch(launch_id)
        self.wait_for(lambda: (self.hold_reason() or "").startswith("failure"), msg="held")
        r = self.rpc("pipeline_release", pipeline=self.fid)
        self.assertFalse(r["ok"])                                          # close the failed session first
        self.assertIn("先關閉", r["error"]["message"])
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="closed")
        nxt = self.prepare()["launch_id"]
        (self.base / "holds" / self.fid).unlink()                           # the hold file is lost
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])                                          # recomputed from the journals
        self.assertIn("繼續", r["error"]["message"])
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        released = json.loads((self.base / "pipelines" / self.tid / "released.json").read_text())
        self.assertEqual(released["pipeline_id"], self.fid)
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])
        # a second failure, after the release, holds the flow again
        (self.work / "fake-mode").write_text("is_error")
        self.dispatch(nxt)
        self.wait_for(lambda: nxt in (self.hold_reason() or ""), msg="held again")
        self.rpc("stream_close", launch_id=nxt)
        self.wait_for(lambda: nxt not in self.dm._streams, msg="closed")
        r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn(nxt, r["error"]["message"])

    def test_ending_in_manual_review_alone_holds_the_flow(self):
        # No failure fact: the session is given up at close (no signal could
        # be sent), so it ends in manual review; that alone holds the flow.
        launch_id, _ = self.open()
        self.dm._streams[launch_id].leader_start = "1600000000.000000"
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="given up")
        self.assertEqual(self.manifest(launch_id)["state"], "manual_review")
        self.assertIn(launch_id, self.hold_reason())
        self.assertIn("不送訊號", self.hold_reason())

    def test_release_reports_durable_continue_with_hold_removal_warning(self):
        import vbear.runtime.daemon_stream as ds
        self.fail_once("is_error")
        real_sync = ds.pipeline_store._fsync_dir
        calls = []

        def fail_hold_directory_sync(fd):
            calls.append(fd)
            if len(calls) == 2:  # released.json sync succeeds; unlink sync fails
                raise ds.pipeline_store.StoreRefused("sync failed")
            return real_sync(fd)

        with mock.patch.object(ds.pipeline_store, "_fsync_dir", fail_hold_directory_sync):
            r = self.rpc("pipeline_release", pipeline=self.fid)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["warning"], "hold_removal_not_durable")
        self.assertFalse(ds.pipeline_store.is_held(self.base, self.fid))
        self.assertGreaterEqual(len(calls), 2)
        nxt = self.prepare()["launch_id"]
        ds.pipeline_store.hold(self.base, self.fid, "reappeared after crash")
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])
        self.assertIn("已停止", r["error"]["message"])
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])

    def released_then_fail_again(self, clock):
        """One failure, closed and released; a second session fails with its
        journal clock set by ``clock(released_at)``; the hold file is lost."""
        import vbear.runtime.daemon_stream as ds
        first = self.fail_once("is_error")
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        released = json.loads((self.base / "pipelines" / self.tid / "released.json").read_text())
        self.assertTrue(any(x.startswith(first + "#") for x in released["resolved"]))
        nxt, _ = self.open("ok")
        self.dm._streams[nxt].writer._now = lambda: clock(released["released_at"])
        (self.work / "fake-mode").write_text("is_error")
        self.dispatch(nxt)
        self.wait_for(lambda: nxt in (self.hold_reason() or ""), msg="held again")
        self.rpc("stream_close", launch_id=nxt)
        self.wait_for(lambda: nxt not in self.dm._streams, msg="closed")
        (self.base / "holds" / self.fid).unlink()
        r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn(nxt, r["error"]["message"])

    def test_a_clock_that_went_back_cannot_release_a_new_failure(self):
        # Review round 6 #1: identities decide, not times.
        self.released_then_fail_again(lambda released_at: released_at - 3600)

    def test_a_failure_stamped_with_the_release_time_is_not_released(self):
        self.released_then_fail_again(lambda released_at: released_at)

    def test_a_failed_spawn_is_a_failure(self):
        # Review round 7 A-1: a CLI that cannot start must not be retried
        # without the user's "continue".
        import vbear.runtime.daemon_stream as ds
        m = self.prepare()
        with mock.patch.object(ds.subprocess, "Popen", side_effect=OSError(8, "Exec format error")):
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        res = self.journal(m["launch_id"])
        self.assertEqual(res.state.protocol_errors[0]["reason"], "spawn_failed")
        self.assertIn("errno 8", res.state.protocol_errors[0]["detail"])
        self.assertIn(m["launch_id"], self.hold_reason())
        nxt = self.prepare()["launch_id"]
        (self.base / "holds" / self.fid).unlink()                           # even without the hold file
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertFalse(r["ok"])
        self.assertIn("繼續", r["error"]["message"])
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        r = self.rpc("open_stream", launch_id=nxt)
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])

    def test_a_short_write_never_releases(self):
        # Review round 7 B-1.
        from vbear.runtime import pipeline_store as ps
        self.fail_once("is_error")
        self.assertTrue(self.rpc("pipeline_release", pipeline=self.fid)["ok"])
        record = self.base / "pipelines" / self.tid / "released.json"
        before = record.read_bytes()
        nxt, _ = self.open("is_error")
        self.dispatch(nxt)
        self.wait_for(lambda: nxt in (self.hold_reason() or ""), msg="held again")
        self.rpc("stream_close", launch_id=nxt)
        self.wait_for(lambda: nxt not in self.dm._streams, msg="closed")
        real = os.write
        calls = []

        def half_then_full_disk(fd, data):
            calls.append(fd)
            if len(calls) == 1:
                return real(fd, bytes(data)[:len(data) // 2])
            raise OSError(28, "No space left on device")
        with mock.patch.object(ps.os, "write", half_then_full_disk):
            r = self.rpc("pipeline_release", pipeline=self.fid)
        self.assertFalse(r["ok"])
        self.assertIn(nxt, self.hold_reason())                             # the hold stays
        self.assertEqual(record.read_bytes(), before)                      # not replaced
        self.assertFalse((record.parent / ".released.json.tmp").exists())
        r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
        self.assertFalse(r["ok"])

    def test_recovery_holds_the_flow(self):
        launch_id, _ = self.open("hang")
        self.dispatch(launch_id)
        self.wait_for(lambda: (self.work / "hang-ready").exists(), msg="turn in flight")
        self.wait_for(lambda: self.dm._streams[launch_id].js.state == "running", msg="confirmed")
        self.crash_daemon()
        self.restart_daemon()
        self.assertIn("daemon 重啟時回合未完成", self.hold_reason())


class OuterGuardTests(StreamCase):
    """Claude review finding 4: an unexpected exception in any per-session
    step of the event loop becomes a session error and a failure hold; the
    session is given up to manual review; the daemon goes on."""

    def hold_reason(self):
        path = self.base / "holds" / self.fid
        return json.loads(path.read_text())["reason"] if path.exists() else None

    def setUp(self):
        super().setUp()
        self.dm._held_next = float("inf")    # no recheck: once its group is empty a held leader is reaped

    def crashed(self, launch_id):
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="given up")
        self.assertTrue(self.thread.is_alive(), "the daemon loop ended")
        self.assertTrue(self.rpc("hello")["ok"])
        m = self.manifest(launch_id)
        self.assertEqual(m["state"], "manual_review")
        self.assertIn("未預期的錯誤", m["retained_reason"])
        self.assertIn("未預期的錯誤", self.hold_reason())
        return m

    def test_an_exception_in_tick(self):
        launch_id, _ = self.open()
        pid = self.launched()["pid"]
        s = self.dm._streams[launch_id]
        with mock.patch.object(s, "tick", side_effect=RuntimeError("synthetic tick failure")):
            self.crashed(launch_id)
        res = self.journal(launch_id)
        self.assertEqual(res.state.protocol_errors[-1]["reason"], "internal_error")
        self.assertIn(pid, [h["pid"] for h in self.dm._held_leaders])      # kept, never reaped (5.8)
        self.assertFalse((self.work / "got-sigterm").exists())              # nothing was signalled

    def test_an_exception_on_pipe_readiness(self):
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        with mock.patch.object(s, "on_stdout", side_effect=RuntimeError("synthetic read failure")):
            self.dispatch(launch_id)                    # its output makes stdout ready
            self.crashed(launch_id)

    def test_an_exception_in_the_clean_up_itself(self):
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        with mock.patch.object(self.dm, "_finish_stream", side_effect=RuntimeError("synthetic clean-up failure")), \
                mock.patch.object(s, "tick", side_effect=RuntimeError("synthetic tick failure")):
            self.crashed(launch_id)
        self.assertIn(s.pid, [h["pid"] for h in self.dm._held_leaders])

    def test_a_failure_after_the_leader_was_reaped_holds_no_phantom(self):
        # S2b part 1 review (boundary case): _finish reaps the leader and then
        # fails; the outer guard must not put the already reaped leader on the
        # held list, where it would keep a session slot for good.
        launch_id, _ = self.open()
        s = self.dm._streams[launch_id]
        with mock.patch.object(s.writer, "close", side_effect=RuntimeError("synthetic failure after the reap")):
            self.rpc("stream_close", launch_id=launch_id)
            self.wait_for(lambda: launch_id not in self.dm._streams, msg="given up")
        self.assertTrue(s.reaped)
        self.assertFalse(stream_session.leader_exited(s.pid))              # really reaped
        self.assertNotIn(s.pid, [h["pid"] for h in self.dm._held_leaders])
        self.assertEqual(self.manifest(launch_id)["state"], "manual_review")
        self.assertIn("未預期的錯誤", self.hold_reason())

    def test_a_hold_reason_that_cannot_be_encoded_does_not_escape(self):
        self.dm._hold_for_failure(self.fid, "l-0000000000000000", "x\ud800")    # sanitize raises ValueError
        self.assertTrue(self.rpc("hello")["ok"])


class HeldLeaderLimitTests(StreamCase):
    """Review round 4 #1: held leaders count toward the session limit, and
    too many of them stop every new open until they are resolved."""

    def hold(self, n):
        procs = [subprocess.Popen(["/bin/sleep", "600"], start_new_session=True) for _ in range(n)]
        for p in procs:
            self.pids.append(p.pid)
            self.dm._held_leaders.append({"proc": p, "pid": p.pid, "launch_id": "l-test"})
        return procs

    def test_held_leaders_fill_the_session_limit(self):
        import vbear.runtime.daemon_stream as ds
        self.dm.max_sessions = 2
        procs = self.hold(2)
        with mock.patch.object(ds, "MAX_HELD_LEADERS", 10):
            r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
            self.assertFalse(r["ok"])
            self.assertIn("session 上限", r["error"]["message"])
            for p in procs:                       # their groups end: the recheck may reap them now
                os.kill(p.pid, 9)
            self.dm._held_next = 0.0
            self.wait_for(lambda: not self.dm._held_leaders, msg="held leaders reaped")
            self.open()

    def test_too_many_held_leaders_stop_every_open(self):
        import vbear.runtime.daemon_stream as ds
        with mock.patch.object(ds, "MAX_HELD_LEADERS", 1):
            self.hold(1)
            r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
            self.assertFalse(r["ok"])
            self.assertIn("需要人工處理", r["error"]["message"])
            r = self.rpc("open", argv=["/bin/sh"], cwd=str(self.work))      # a terminal too
            self.assertFalse(r["ok"])
            self.assertIn("需要人工處理", r["error"]["message"])


class LedgerTests(StreamCase):
    def test_session_reservation_and_release(self):
        launch_id, _ = self.open()
        self.assertIn(f"session:{launch_id}", self.dm._ledger.reservations)
        self.rpc("stream_close", launch_id=launch_id)
        self.wait_for(lambda: launch_id not in self.dm._streams, msg="finished")
        self.assertNotIn(f"session:{launch_id}", self.dm._ledger.reservations)

    def test_rebuild_refuses_a_sessions_root_it_cannot_list(self):
        # R4 audit: only a sessions root that was never created means "no
        # launch"; any other listing error leaves nothing granted.
        for error in (PermissionError(13, "Permission denied"), NotADirectoryError(20, "Not a directory")):
            with self.subTest(error=type(error).__name__):
                real = os.listdir

                def listdir(path=".", _e=error):
                    if str(path).endswith("/sessions"):
                        raise _e
                    return real(path)
                with mock.patch("vbear.runtime.daemon_stream.os.listdir", listdir):
                    self.assertFalse(self.dm._rebuild_ledger())
                self.assertIsNone(self.dm._ledger.used)
                self.assertIn("額度無法核算", self.dm._ledger.problem)
        self.assertTrue(self.dm._rebuild_ledger())

    def test_rebuild_refuses_an_unrecognized_sessions_entry(self):
        (self.base / "sessions").mkdir(mode=0o700, exist_ok=True)
        (self.base / "sessions" / "notes").mkdir(mode=0o700)
        self.assertFalse(self.dm._rebuild_ledger())
        self.assertIsNone(self.dm._ledger.used)
        self.assertIn("無法判斷哪些寫入者仍在進行", self.dm._ledger.problem)

    def test_the_reservation_covers_more_than_the_journal(self):
        # Review B4: room for exactly the journal is not enough.
        from vbear import strictjson
        from vbear.runtime import quota
        self.assertEqual(quota.JOURNAL_MAX, strictjson.SESSION_LOG.file_bytes)
        self.assertEqual(quota.MANIFEST_MAX, strictjson.MANIFEST.file_bytes)
        self.assertEqual(quota.START_RECORD_MAX, strictjson.MANIFEST.file_bytes)
        led = self.dm._ledger
        led.limit = led.used + sum(led.reservations.values()) + quota.JOURNAL_MAX
        r = self.rpc("open_stream", launch_id=self.prepare()["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn("quota", r["error"]["message"])
        led.limit = led.used + sum(led.reservations.values()) + quota.RESERVE_SESSION
        self.open()

    def test_release_reports_everything_the_session_added(self):
        led = self.dm._ledger
        m = self.prepare()
        ldir = self.base / "sessions" / m["launch_id"]
        before_manifest, before_used = (ldir / "manifest.json").stat().st_size, led.used
        prepared = sum(p.stat().st_size for p in ldir.iterdir())     # the console wrote these; open counts them (S2c)
        r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])
        self.rpc("stream_close", launch_id=m["launch_id"])
        self.wait_for(lambda: m["launch_id"] not in self.dm._streams, msg="ended")
        added = ((ldir / "journal.jsonl").stat().st_size + (ldir / "manifest.json").stat().st_size - before_manifest
                 + (self.base / "pipelines" / self.tid / "started.json").stat().st_size)
        self.assertEqual(led.used - before_used, added + prepared)
        self.assertEqual(led.overrun, "")

    # ---- review B-1: a failed write still counts what reached the disk

    def prepare_with(self, launch_id, *patches):
        led = self.dm._ledger
        before = led.used
        d = fx.new_uuid()
        for p in patches:
            p.start()
        try:
            r = self.rpc("dispatch_prepare", launch_id=launch_id, pipeline=self.fid, dispatch_id=d,
                         text="全文" * 10, approval={"kind": "preview", "id": "pv"})
        finally:
            for p in patches:
                p.stop()
        self.assertFalse(r["ok"])
        ddir = self.base / "pipelines" / self.tid / "dispatches"
        on_disk = sum(p.stat().st_size for p in ddir.iterdir() if d in p.name)
        return led.used - before, on_disk, d

    def test_text_write_failures_count_what_is_on_disk(self):
        from vbear.runtime import pipeline_store as ps
        launch_id, _ = self.open()
        real_unlink, real_write = os.unlink, os.write

        def unlink(path, *a, **kw):
            if str(path).endswith(".partial") and kw.get("dir_fd") is not None:
                raise OSError(5, "Input/output error")
            return real_unlink(path, *a, **kw)

        def short_write(fd, data):
            real_write(fd, bytes(data)[:7])
            raise OSError(28, "No space left on device")
        cases = {
            "unlink of .partial fails after the link": mock.patch.object(ps.os, "unlink", unlink),
            "directory sync fails": mock.patch.object(ps, "_fsync_dir", side_effect=ps.StoreRefused("sync")),
            ".partial write fails (removed again)": mock.patch.object(ps.os, "write", short_write),
        }
        for name, patch in cases.items():
            with self.subTest(case=name):
                try:
                    added, on_disk, d = self.prepare_with(launch_id, patch)
                    self.assertGreater(on_disk, 0) if "removed" not in name else self.assertEqual(on_disk, 0)
                    self.assertEqual(added, on_disk)
                    self.assertEqual(self.dm._ledger.overrun, "")
                finally:                                  # every case starts from an empty directory
                    for p in (self.base / "pipelines" / self.tid / "dispatches").iterdir():
                        p.unlink()

    def test_unmeasurable_text_counts_the_reservation_and_stops_granting(self):
        from vbear.runtime import pipeline_store as ps, quota
        launch_id, _ = self.open()
        real = ps.Pipeline.text_bytes
        calls = []

        def text_bytes(p, d):
            calls.append(d)
            if len(calls) > 1:
                raise OSError(5, "Input/output error")
            return real(p, d)
        added, _, _ = self.prepare_with(launch_id, mock.patch.object(ps, "_fsync_dir",
                                                                     side_effect=ps.StoreRefused("sync")),
                                        mock.patch.object(ps.Pipeline, "text_bytes", text_bytes))
        self.assertEqual(added, quota.RESERVE_DISPATCH)
        self.assertTrue(self.dm._ledger.overrun)
        self.assertIn("額度", self.dm._ledger.reserve("x", 1))

    def journal_failure(self, fail):
        """``fail(data)`` -> True for the journal line whose write fails."""
        from vbear.runtime import stream_journal
        led = self.dm._ledger
        m = self.prepare()
        ldir = self.base / "sessions" / m["launch_id"]
        before_manifest, before_used = (ldir / "manifest.json").stat().st_size, led.used
        prepared = sum(p.stat().st_size for p in ldir.iterdir())     # the console wrote these; open counts them (S2c)
        r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertTrue(r["ok"], r)
        self.pids.append(self.launched()["pid"])
        with fail(stream_journal):
            self.dispatch(m["launch_id"])
            self.wait_for(lambda: m["launch_id"] not in self.dm._streams, msg="ended after the failure")
        texts = sum(p.stat().st_size for p in (self.base / "pipelines" / self.tid / "dispatches").iterdir())
        added = ((ldir / "journal.jsonl").stat().st_size + (ldir / "manifest.json").stat().st_size - before_manifest
                 + (self.base / "pipelines" / self.tid / "started.json").stat().st_size + texts)
        self.assertEqual(led.used - before_used, added + prepared)
        self.assertEqual(self.manifest(m["launch_id"])["state"], "manual_review")

    def test_a_short_journal_write_is_counted(self):
        real = os.write

        def fail(sj):
            def write(fd, data):
                if b'"kind":"dispatch_confirmed"' in bytes(data):
                    return real(fd, bytes(data)[:20])                     # short: 20 bytes reach the disk
                return real(fd, data)
            return mock.patch.object(sj.os, "write", write)
        self.journal_failure(fail)

    def test_a_journal_line_whose_fsync_failed_is_counted(self):
        real_write, real_fsync = os.write, os.fsync
        last = {}

        def fail(sj):
            import contextlib

            def write(fd, data):
                last[fd] = bytes(data)
                return real_write(fd, data)

            def fsync(fd):
                if b'"kind":"dispatch_confirmed"' in last.get(fd, b""):
                    raise OSError(5, "Input/output error")
                return real_fsync(fd)
            stack = contextlib.ExitStack()
            stack.enter_context(mock.patch.object(sj.os, "write", write))
            stack.enter_context(mock.patch.object(sj.os, "fsync", fsync))
            return stack
        self.journal_failure(fail)

    # ---- review B-2: the manifest's temp file and a start record whose fsync failed

    def failed_open(self, *patches):
        led = self.dm._ledger
        m = self.prepare()
        before = led.used
        # what the console's prepare wrote is counted at open (S2c); the tests below are about what the open itself added
        prepared = sum(p.stat().st_size for p in (self.base / "sessions" / m["launch_id"]).iterdir())
        for p in patches:
            p.start()
        try:
            r = self.rpc("open_stream", launch_id=m["launch_id"])
        finally:
            for p in patches:
                p.stop()
        self.assertFalse(r["ok"])
        self.assertNotIn(f"session:{m['launch_id']}", led.reservations)
        return m, led.used - before - prepared

    def test_a_manifest_temp_file_left_by_a_failed_rewrite_is_counted(self):
        real = a._write_private

        def write_private(path, text, *, replace=False):
            if replace and path.name == a.MANIFEST and '"launching"' in text:
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(text)
                tmp.chmod(0o600)
                raise OSError(5, "Input/output error")                    # the fsync of the temp file failed
            return real(path, text, replace=replace)
        m, added = self.failed_open(mock.patch.object(a, "_write_private", write_private))
        tmp = self.base / "sessions" / m["launch_id"] / (a.MANIFEST + ".tmp")
        self.assertTrue(tmp.exists())
        self.assertEqual(added, tmp.stat().st_size)

    def test_a_start_record_whose_sync_failed_is_removed_or_counted(self):
        from vbear.runtime import pipeline_store as ps
        started = self.base / "pipelines" / self.tid / "started.json"
        real_sync = ps._fsync_dir
        calls = []

        def sync_fails_once(fd):
            calls.append(fd)
            if len(calls) == 1:
                raise ps.StoreRefused("sync")                               # the record landed, its sync failed
            return real_sync(fd)
        m, added = self.failed_open(mock.patch.object(ps, "_fsync_dir", sync_fails_once))
        self.assertFalse(started.exists())                                   # ours, so removed exactly
        self.assertEqual(added, 0)
        calls.clear()
        m, added = self.failed_open(mock.patch.object(ps, "_fsync_dir", sync_fails_once),
                                    mock.patch.object(ps.Pipeline, "remove_start",
                                                      side_effect=ps.StoreRefused("unlink")))
        self.assertTrue(started.exists())
        self.assertEqual(json.loads(started.read_text())["launch_id"], m["launch_id"])
        self.assertEqual(added, started.stat().st_size)                     # left on disk: counted
        started.unlink()

    def test_an_unmeasurable_start_record_counts_the_reservation(self):
        from vbear.runtime import pipeline_store as ps, quota
        m, added = self.failed_open(mock.patch.object(ps, "_fsync_dir", side_effect=ps.StoreRefused("sync")),
                                    mock.patch.object(ps.Pipeline, "start_record_bytes",
                                                      side_effect=OSError(5, "Input/output error")))
        self.assertEqual(added, quota.RESERVE_SESSION)
        self.assertTrue(self.dm._ledger.overrun)

    def test_full_ledger_refuses(self):
        self.dm._ledger.limit = self.dm._ledger.used + 1024
        m = self.prepare()
        r = self.rpc("open_stream", launch_id=m["launch_id"])
        self.assertFalse(r["ok"])
        self.assertIn("quota", r["error"]["message"])


if __name__ == "__main__":
    unittest.main()
