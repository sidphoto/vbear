"""Phase R2 S2: attach connections + NativeRuntime (contract v2 §1, §2B, §5, §10 S2).

Synthetic programs only (user decision §9.3).
"""

from __future__ import annotations

import base64
import json
import queue as queue_mod
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from sidconsole.runtime import daemon as d
from sidconsole.runtime import native as n
from sidconsole.runtime import NativeRuntime, RuntimeBase

PY = sys.executable
ECHO = [PY, "-c", "import sys\nfor l in sys.stdin: print('ECHO:'+l.strip(),flush=True)"]
SLEEP = ["/bin/sh", "-c", "echo ready; exec sleep 100"]


class RawAttach:
    """Minimal raw attach client for daemon-level assertions."""

    def __init__(self, base, sid, mode="observe", cols=80, rows=24, rcvbuf=None):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if rcvbuf:
            self.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        self.s.settimeout(5)
        self.s.connect(str(d.socket_path(base)))
        self.s.sendall(json.dumps({"v": 1, "id": "h", "op": "attach", "session_id": sid,
                                   "mode": mode, "cols": cols, "rows": rows}).encode() + b"\n")
        self.buf = bytearray()

    def line(self, timeout=5.0):
        self.s.settimeout(timeout)
        while b"\n" not in self.buf:
            c = self.s.recv(1 << 20)
            if not c:
                return None
            self.buf += c
        i = self.buf.find(b"\n")
        raw = bytes(self.buf[:i])
        del self.buf[:i + 1]
        return json.loads(raw)

    def until(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        seen = []
        while time.monotonic() < end:
            try:
                m = self.line(max(0.05, end - time.monotonic()))
            except socket.timeout:
                break
            if m is None:
                break
            seen.append(m)
            if pred(m, seen):
                return seen
        raise AssertionError(f"condition not met; saw {len(seen)} msgs: {seen[-3:]}")

    def send(self, obj):
        self.s.sendall(json.dumps(obj).encode() + b"\n")

    def close(self):
        self.s.close()


def text(m) -> str:
    return base64.b64decode(m.get("bytes") or "").decode("utf-8", "replace")


class DaemonCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sidr2-", dir="/tmp"))
        self.base = self.tmp / "st"
        self.dm = d.Daemon(self.base, log=lambda m: None)
        self.dm.start()
        self.thread = threading.Thread(target=self.dm.serve_forever, daemon=True)
        self.thread.start()
        self.raws: list[RawAttach] = []

    def tearDown(self):
        for r in self.raws:
            r.close()
        self.dm.stop()
        self.thread.join(5)
        self.dm.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rpc(self, op, **kw):
        return d.rpc(op, base=self.base, timeout=10, **kw)

    def open(self, argv, **kw) -> str:
        r = self.rpc("open", argv=argv, cwd=str(self.tmp), **kw)
        self.assertTrue(r["ok"], r)
        return r["result"]["session_id"]

    def raw(self, sid, **kw) -> RawAttach:
        r = RawAttach(self.base, sid, **kw)
        self.raws.append(r)
        return r

    def sinfo(self, sid):
        for s in self.rpc("list")["result"]["sessions"]:
            if s["session_id"] == sid:
                return s
        return None

    def wait_for(self, pred, timeout=5.0, msg="condition"):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            time.sleep(0.02)
        self.fail(f"timed out waiting for {msg}")

    def wait_out(self, sid, needle: bytes, timeout=5.0):
        self.wait_for(lambda: sid in self.dm._sessions and needle in self.dm._sessions[sid].scrollback,
                      timeout, repr(needle))


# ---------------------------------------------------------------- daemon level

class ReplayTests(unittest.TestCase):
    def test_replay_capped_and_utf8_aligned(self):
        data = ("中" * 40000).encode()  # 3-byte chars, > 64 KiB
        out = d.replay_bytes(data)
        self.assertLessEqual(len(out), d.FULL_REPLAY_MAX)
        self.assertTrue(out.startswith(d.RIS))
        out[len(d.RIS):].decode("utf-8")  # must not start mid-sequence
        self.assertEqual(d.replay_bytes(b"abc"), d.RIS + b"abc")


class SynthFullTests(unittest.TestCase):
    def test_synth_full_utf8_aligned_and_tracks_size(self):
        v = n.NativeAttachment("n-0123456789ab", "observe", 80, 24, fail_reason="x")
        v._tail = bytearray(("中" * 40000).encode())  # no RIS prefix, > cap
        raw = base64.b64decode(v._synth_full()["bytes"])
        self.assertLessEqual(len(raw), n.TAIL_MAX)
        self.assertTrue(raw.startswith(d.RIS))
        raw[len(d.RIS):].decode("utf-8")  # must not start mid-sequence
        v._tail = bytearray(d.RIS + ("中" * 40000).encode())  # RIS-prefixed but over cap
        raw = base64.b64decode(v._synth_full()["bytes"])
        self.assertLessEqual(len(raw), n.TAIL_MAX)
        self.assertTrue(raw.startswith(d.RIS))
        raw[len(d.RIS):].decode("utf-8")
        v._publish({"type": "terminal.frame", "bytes": "", "full": False,
                    "seq": 3, "width": 120, "height": 40})
        self.assertEqual((v.cols, v.rows), (120, 40))
        self.assertEqual(v._synth_full()["width"], 120)


class AttachProtocolTests(DaemonCase):
    def test_handshake_then_full_frame_with_history(self):
        sid = self.open(SLEEP)
        self.wait_out(sid, b"ready")
        a = self.raw(sid)
        hs = a.line()
        self.assertTrue(hs["ok"])
        self.assertRegex(hs["result"]["attachment_id"], r"^a-[0-9a-f]{12}$")
        fr = a.line()
        self.assertEqual(fr["type"], "terminal.frame")
        self.assertTrue(fr["full"])
        self.assertIn("ready", text(fr))
        self.assertTrue(base64.b64decode(fr["bytes"]).startswith(d.RIS))

    def test_observe_input_rejected_control_input_echoed(self):
        sid = self.open(ECHO)
        obs = self.raw(sid)
        obs.line(); obs.line()
        obs.send({"type": "terminal.input", "bytes": base64.b64encode(b"x\n").decode()})
        obs.until(lambda m, _: m.get("type") == "terminal.error" and m["code"] == "not_control")
        ctl = self.raw(sid, mode="control")
        ctl.line(); ctl.line()
        ctl.send({"type": "terminal.input", "bytes": base64.b64encode(b"hello\n").decode()})
        ctl.until(lambda m, seen: "ECHO:hello" in "".join(text(x) for x in seen))
        # observers see the same output (fan-out)
        obs.until(lambda m, seen: "ECHO:hello" in "".join(text(x) for x in seen))

    def test_takeover_demotes_previous_control(self):
        sid = self.open(SLEEP)
        a = self.raw(sid, mode="control")
        aid_a = a.line()["result"]["attachment_id"]
        b = self.raw(sid, mode="control")
        aid_b = b.line()["result"]["attachment_id"]
        a.until(lambda m, _: m.get("type") == "terminal.control_lost")
        self.assertEqual(self.sinfo(sid)["control_attachment"], aid_b)
        self.assertNotEqual(aid_a, aid_b)

    def test_disconnect_releases_control(self):
        sid = self.open(SLEEP)
        a = self.raw(sid, mode="control")
        a.line()
        self.wait_for(lambda: self.sinfo(sid)["control_attachment"] is not None)
        a.close()
        self.wait_for(lambda: self.sinfo(sid)["control_attachment"] is None, msg="release on drop")
        self.assertEqual(self.sinfo(sid)["attachments"], 0)
        b = self.raw(sid, mode="control")  # immediately re-controllable
        self.assertTrue(b.line()["ok"])

    def test_release_closes_attachment(self):
        sid = self.open(SLEEP)
        a = self.raw(sid, mode="control")
        a.line()
        a.send({"type": "terminal.release"})
        msgs = a.until(lambda m, _: m.get("type") == "terminal.closed")
        self.assertEqual(msgs[-1]["reason"], "released")
        self.assertIsNone(a.line())
        self.wait_for(lambda: self.sinfo(sid)["control_attachment"] is None)
        self.assertIsNotNone(self.sinfo(sid))  # the terminal keeps running

    def test_attach_limit_and_unknown_session(self):
        sid = self.open(SLEEP)
        self.dm.max_attachments = 2
        for _ in range(2):
            self.assertTrue(self.raw(sid).line()["ok"])
        self.assertEqual(self.raw(sid).line()["error"]["code"], "limit")
        self.assertEqual(self.raw("n-000000000000").line()["error"]["code"], "not_found")
        self.assertEqual(self.raw(sid, mode="boss").line()["error"]["code"], "bad_request")

    def test_natural_exit_closes_attachments(self):
        sid = self.open([PY, "-c", "import sys;sys.stdin.readline();print('bye');sys.exit(4)"])
        a = self.raw(sid, mode="control")
        a.line()
        a.send({"type": "terminal.input", "bytes": base64.b64encode(b"\n").decode()})
        msgs = a.until(lambda m, _: m.get("type") == "terminal.closed")
        self.assertIn("exit 4", msgs[-1]["reason"])
        self.assertIn("bye", "".join(text(m) for m in msgs))
        late = self.raw(sid)  # attaching after exit: history, then closed
        late.line()
        late.until(lambda m, _: m.get("type") == "terminal.closed")

    def test_close_rpc_notifies_attachments(self):
        sid = self.open(SLEEP)
        a = self.raw(sid)
        a.line()
        self.assertTrue(self.rpc("close", session_id=sid)["ok"])
        a.until(lambda m, _: m.get("type") == "terminal.closed")

    def test_resize_sends_sigwinch(self):
        code = ("import signal,os,sys,time\n"
                "signal.signal(signal.SIGWINCH,lambda *a: print('WINCH',*os.get_terminal_size(0),flush=True))\n"
                "print('armed',flush=True)\ntime.sleep(100)")
        sid = self.open([PY, "-c", code])
        self.wait_out(sid, b"armed")
        a = self.raw(sid, mode="control")
        a.line()
        a.send({"type": "terminal.resize", "cols": 101, "rows": 33})
        a.until(lambda m, seen: "WINCH 101 33" in "".join(text(x) for x in seen))

    def test_slow_reader_resyncs_with_capped_full_frame(self):
        spew = [PY, "-c", "import sys\nwhile True: sys.stdout.write('z'*4000+'\\n')"]
        sid = self.open(spew)
        built = []
        real_full = self.dm._full_line

        def counting_full(s):
            built.append(time.monotonic())
            return real_full(s)
        with mock.patch.object(d, "ATTACH_QUEUE_MAX", 8), \
             mock.patch.object(self.dm, "_full_line", side_effect=counting_full):
            a = self.raw(sid, rcvbuf=4096)
            a.line()
            att = next(iter(self.dm._attachments.values()))
            self.wait_for(lambda: att.resync, 5, "resync flagged")
            # §10 S2: while the socket stays blocked, no full frame is rebuilt,
            # however much output keeps arriving.
            before = len(built)
            time.sleep(1.0)  # still not reading
            self.assertEqual(len(built), before, "full frame rebuilt while socket blocked")
            fulls = 0
            for _ in range(50):
                m = a.line()
                if m and m.get("full"):
                    fulls += 1
                    raw = base64.b64decode(m["bytes"])
                    self.assertLessEqual(len(raw), d.FULL_REPLAY_MAX)
                    self.assertTrue(raw.startswith(d.RIS))
            self.assertGreaterEqual(fulls, 1)  # resync delivered once the reader resumes
        self.rpc("close", session_id=sid)

    def test_resync_pending_counts_as_stalled(self):
        # Overflow empties the queue; a blocked socket with only a pending
        # resync must still be dropped (flake seen under full-suite load).
        sid = self.open(SLEEP)
        a = self.raw(sid)
        a.line()
        self.wait_for(lambda: self.dm._attachments, msg="attachment")
        att = next(iter(self.dm._attachments.values()))
        self.dm.stop(); self.thread.join(5)  # freeze the loop; drive _sweep by hand
        att.out.clear(); att.out_bytes = 0; att.cur.clear()
        att.resync = True
        att.last_progress = time.monotonic() - 60
        self.dm._sweep(time.monotonic())
        self.assertNotIn(att.sock, self.dm._attachments)

    def test_stalled_reader_dropped_other_session_unaffected(self):
        spew = [PY, "-c", "import sys\nwhile True: sys.stdout.write('z'*4000+'\\n')"]
        sid = self.open(spew)
        other = self.open(ECHO)
        self.dm.write_stall = 0.5
        a = self.raw(sid, rcvbuf=4096)
        a.line()
        self.wait_for(lambda: self.sinfo(sid)["attachments"] == 0, 8, "stalled attachment dropped")
        c = self.raw(other, mode="control")
        c.line(); c.line()
        c.send({"type": "terminal.input", "bytes": base64.b64encode(b"alive\n").decode()})
        c.until(lambda m, seen: "ECHO:alive" in "".join(text(x) for x in seen))
        self.rpc("close", session_id=sid)


# --------------------------------------------------------------- runtime level

class NativeRuntimeTests(DaemonCase):
    def setUp(self):
        super().setUp()
        self.rt = NativeRuntime(self.base)
        self.addCleanup(self.rt.close_all)

    def drain(self, q, pred, timeout=5.0):
        acc = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                m = q.get(timeout=0.1)
            except queue_mod.Empty:
                continue
            acc.append(m)
            if pred(acc):
                return acc
        self.fail(f"drain timeout; last {acc[-3:]}")

    @staticmethod
    def joined(acc):
        return "".join(text(m) for m in acc if m and m.get("type") == "terminal.frame")

    def test_is_runtime_and_describe(self):
        self.assertIsInstance(self.rt, RuntimeBase)
        info = self.rt.describe()
        self.assertEqual(info["name"], "native")
        self.assertTrue(info["available"])
        down = NativeRuntime(self.tmp / "nobody")
        self.assertFalse(down.describe()["available"])
        self.assertFalse(down.is_available())
        self.assertEqual(down.list_sessions()["panes"], [])

    def test_list_sessions_shape_and_status(self):
        sid = self.open(SLEEP)
        snap = self.rt.list_sessions()
        for k in ("panes", "agents", "workspaces", "tabs", "problems", "available"):
            self.assertIn(k, snap)
        [p] = snap["panes"]
        self.assertEqual((p["pane_id"], p["terminal_id"]), (sid, sid))
        self.assertEqual(p["title"], "sh")
        self.assertEqual(self.rt.status(sid), "unknown")
        self.assertEqual(set(self.rt.snapshot()), set(snap))
        ex = self.open(["/bin/sh", "-c", "exit 0"])
        self.wait_for(lambda: self.rt.status(ex) == "exited", msg="exited status")

    def test_validate_target_and_focus(self):
        self.assertTrue(self.rt.validate_target("n-0123456789ab"))
        for bad in ("", "w1:pA", "--x", "n-XYZ", "a/b", "n-" + "0" * 200):
            self.assertFalse(self.rt.validate_target(bad), bad)
        self.assertFalse(self.rt.focus("n-0123456789ab")["ok"])

    def test_observe_first_frame_and_readonly(self):
        sid = self.open(SLEEP)
        self.wait_out(sid, b"ready")
        v = self.rt.observe(sid)
        self.assertEqual(v.mode, "observe")
        for attr in ("session_id", "mode", "cols", "rows", "token", "queue", "send_input", "resize"):
            self.assertTrue(hasattr(v, attr))
        acc = self.drain(v.queue, lambda a: a and a[0].get("full"))
        self.assertIn("ready", self.joined(acc))
        self.assertFalse(v.send_input(b"x"))
        self.assertFalse(self.rt.send_input(sid, b"x"))
        self.assertFalse(self.rt.resize(sid, 90, 30))
        self.assertIs(self.rt.observe(sid), v)  # same pane, same view

    def test_control_input_resize_release(self):
        sid = self.open(ECHO)
        v = self.rt.control(sid)
        self.assertEqual(v.mode, "control")
        q = v.queue
        self.assertTrue(self.rt.send_input(sid, b"world\n"))
        self.drain(q, lambda a: "ECHO:world" in self.joined(a))
        self.assertTrue(self.rt.resize(sid, 100, 40))
        self.wait_for(lambda: (self.sinfo(sid)["cols"], self.sinfo(sid)["rows"]) == (100, 40))
        new = self.rt.release(sid)
        self.assertEqual(new.mode, "observe")
        self.assertTrue(v.closed)
        self.wait_for(lambda: self.sinfo(sid)["control_attachment"] is None)
        self.assertIsNone(self.rt.release("n-000000000000"))

    def test_takeover_stops_previous_view(self):
        sid = self.open(SLEEP)
        first = self.rt.observe(sid)
        second = self.rt.control(sid)
        self.assertIsNot(first, second)
        self.assertIs(self.rt.get(sid), second)
        self.wait_for(lambda: first.closed, msg="old view stopped")
        self.assertEqual(self.sinfo(sid)["control_attachment"], second.attachment_id)

    def test_concurrent_takeovers_stay_consistent(self):
        # §10 S2: 20 racing takeovers -> server's control view == daemon's holder, and it types.
        sid = self.open(ECHO)
        barrier = threading.Barrier(20)

        def go():
            barrier.wait()
            self.rt.control(sid)
        ths = [threading.Thread(target=go) for _ in range(20)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(30)
        v = self.rt.get(sid)
        self.assertEqual(v.mode, "control")
        self.wait_for(lambda: self.sinfo(sid)["attachments"] == 1, 10, "losers dropped")
        self.assertEqual(self.sinfo(sid)["control_attachment"], v.attachment_id)
        q = v.queue
        self.assertTrue(v.send_input(b"race\n"))
        self.drain(q, lambda a: "ECHO:race" in self.joined(a))

    def test_two_readers_each_get_all_frames(self):
        sid = self.open(ECHO)
        v = self.rt.control(sid)
        results = {}

        def reader(name):
            q = v.queue
            ready.wait()
            try:
                results[name] = self.joined(self.drain(q, lambda a: "ECHO:fan" in self.joined(a)))
            except AssertionError as exc:
                results[name] = exc
        ready = threading.Event()
        ths = [threading.Thread(target=reader, args=(i,)) for i in range(2)]
        for t in ths:
            t.start()
        time.sleep(0.2)
        ready.set()
        v.send_input(b"fan\n")
        for t in ths:
            t.join(10)
        for name in (0, 1):
            self.assertIsInstance(results.get(name), str, results)
            self.assertIn("ECHO:fan", results[name])

    def test_abandon_close_if_current_close_all(self):
        sid = self.open(SLEEP)
        v = self.rt.observe(sid)
        self.assertFalse(self.rt.abandon(sid, token="stale"))
        self.assertIs(self.rt.get(sid), v)
        self.assertTrue(self.rt.abandon(sid, token=v.token))
        self.assertIsNone(self.rt.get(sid))
        first = self.rt.observe(sid)
        newer = self.rt.control(sid)
        self.rt.close_if_current(sid, first)  # stale reference: no-op
        self.assertIs(self.rt.get(sid), newer)
        self.rt.close_all()
        self.assertIsNone(self.rt.get(sid))
        self.assertIsNotNone(self.sinfo(sid), "close_all must not end the terminal")

    def test_open_session_and_close(self):
        v = self.rt.open_session({"argv": SLEEP, "cwd": str(self.tmp), "cols": 90, "rows": 30})
        self.assertEqual(v.mode, "observe")
        sid = v.session_id
        q = v.queue
        self.drain(q, lambda a: "ready" in self.joined(a))
        self.assertTrue(self.rt.close(sid))
        acc = self.drain(q, lambda a: a[-1] is None)
        self.assertEqual(acc[-2]["type"], "terminal.closed")
        self.assertIsNone(self.sinfo(sid))
        self.assertFalse(self.rt.close(sid))
        with self.assertRaises(n.NativeRuntimeError):
            self.rt.open_session({"argv": ["sid-no-such-cmd"], "cwd": str(self.tmp)})

    def test_attach_to_missing_session_surfaces_closed(self):
        v = self.rt.control("n-000000000000")
        self.assertIsNotNone(v)
        acc = self.drain(v.queue, lambda a: a[-1] is None)
        self.assertEqual(acc[0]["type"], "terminal.closed")
        self.assertIn("attach failed", acc[0]["reason"])

    def test_daemon_down_returns_none(self):
        down = NativeRuntime(self.tmp / "nobody")
        self.assertIsNone(down.observe("n-0123456789ab"))
        self.assertIsNone(down.control("n-0123456789ab"))


if __name__ == "__main__":
    unittest.main()
