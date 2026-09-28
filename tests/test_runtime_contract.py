"""Phase R1 contract tests for the Runtime abstraction (PHASE-R-PLAN §3.3).

The point of these tests is the OPPOSITE of the unit tests in
``tests/test_console.py``: those exercise one specific implementation
(``bridge.terminal.TerminalBridge``). These tests assert what every
implementation of ``RuntimeBase`` MUST do, regardless of how it gets done.

Parameterisation
----------------
R1 ships a single implementation (``HerdrRuntime``). R2 will add
``NativeRuntime``. The tests are written so the future native
implementation only has to drop in alongside ``HerdrRuntime`` in
``RUNTIME_IMPLEMENTATIONS`` and rerun this file — every contract
assertion below must hold for both backends.

Layout
------
``RuntimeContractBase`` is a plain mixin whose ``setUp`` builds a fresh
runtime instance on the synthetic fake-herdr backend (reused in spirit
from ``tests/test_console.PaneSessionTests``). Concrete subclasses pin
a specific runtime implementation and inherit from
``unittest.TestCase`` so the unittest discoverer picks them up. The
mixin itself is NOT a ``TestCase`` — that would let Python's discoverer
double-run the template class alongside any concrete subclass.

Coverage map (PHASE-R-PLAN §3.3 requirement):

  - list sessions
  - observe first frame
  - control / release
  - input
  - resize
  - invalid target rejection
  - unsupported ops explicitly fail (NotSupported)
  - status unobservable -> 'unknown'
  - herdr-missing graceful degradation

The base RuntimeBase API also covers describe / focus / snapshot /
validate_target / get / abandon / close_all; they are exercised in the
contract too because the protocol can only ship once every existing
call-site has its equivalent checked.
"""

from __future__ import annotations

import base64
import json
import os
import queue as queue_mod
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# Note: we deliberately do NOT inherit HOME from a sibling module. The
# sibling test_console.py sets HOME to a per-test scratch dir and
# removes it on tearDown; if our contract tests run after that, our
# FAKE_HOME would point at a deleted directory and mkdtemp(dir=...) would
# crash. Instead we let each setUp create a fresh tempdir under the
# system default temp location, and we never depend on a sibling module's
# HOME state. The HerdrRuntime itself doesn't read HOME; the only thing
# that cares is sid-console's profile store, which the contract tests
# never exercise.
os.environ["PATH"] = "/usr/bin:/bin"  # no real herdr on PATH
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# The fake herdr script used by the contract tests. Mirrors the protocol
# recorded from real herdr 0.9.1 (terminal.frame initial full, incremental
# frames on input/resize, terminal.closed on release). Implemented to be
# shareable with the existing tests/test_console.py fixture style — same
# argv shape herdr itself uses (`herdr terminal session observe|control
# pane_id --cols --rows [--takeover]`).
_FAKE_TERM_HERDR = r"""#!/usr/bin/env python3
import base64, json, sys, time
from pathlib import Path

lock_dir = Path(sys.argv[0]).resolve().parent / "attach-locks"
lock_dir.mkdir(exist_ok=True)


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def frame(text, seq, full):
    send({"type": "terminal.frame", "bytes": base64.b64encode(text.encode()).decode(),
          "encoding": "ansi", "full": full, "height": 24, "width": 80, "seq": seq})


args = sys.argv[1:]
mode, target = args[2], args[3]
takeover = "--takeover" in args
lock = lock_dir / target

if mode == "control" and target == "always-conflict":
    send({"type": "terminal.closed",
          "reason": "terminal attach failed: simulated conflict"})
    sys.exit(0)
if mode == "control" and lock.exists() and not takeover:
    send({"type": "terminal.closed",
          "reason": f"terminal attach failed: terminal {target} already has an "
                    "attached client; retry with --takeover"})
    sys.exit(0)
if mode == "control":
    lock.write_text("attached")

if target == "closes-immediately":
    send({"type": "terminal.closed", "reason": f"terminal {target} exited"})
    sys.exit(0)

frame(f"{mode.upper()}-INIT", 1, True)
seq = 1
try:
    if mode == "observe":
        while True:
            time.sleep(3600)  # observe takes no stdin; wait until killed
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg["type"] == "terminal.input":
            seq += 1
            text = base64.b64decode(msg["bytes"]).decode("utf-8", "replace")
            frame(f"ECHO:{text}", seq, False)
        elif msg["type"] == "terminal.resize":
            seq += 1
            frame(f"RESIZED:{msg['cols']}x{msg['rows']}", seq, False)
        elif msg["type"] == "terminal.release":
            send({"type": "terminal.closed", "reason": "released"})
            break
finally:
    if lock.exists():
        lock.unlink()
"""


# A sub-agent that fakes a single `agent list` row with agent_status so
# the protocol-level `status(session_id)` path can find a known id.
_FAKE_AGENT_SCRIPT = r"""#!/usr/bin/env python3
import json, sys

cmd = sys.argv[1:3]  # e.g. ['agent','list']
if cmd == ["agent", "list"]:
    print(json.dumps({"result": {
        "agents": [{"terminal_id": "w1:pA", "pane_id": "w1:pA",
                    "agent": "claude", "agent_status": "working"}]
    }}))
elif cmd == ["pane", "list"]:
    print(json.dumps({"result": {"panes": [
        {"pane_id": "w1:pA", "terminal_id": "w1:pA", "agent": "claude",
         "agent_status": "working"},
        {"pane_id": "w1:pB", "terminal_id": "w1:pB", "agent": None,
         "agent_status": "unknown"},
    ]}}))
elif cmd == ["workspace", "list"]:
    print(json.dumps({"result": {"workspaces": []}}))
elif cmd == ["tab", "list"]:
    print(json.dumps({"result": {"tabs": []}}))
else:
    sys.exit(1)
"""


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _rm(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# --- contract surface ---------------------------------------------------------


class RuntimeContractBase:
    """Mixin that verifies every Runtime impl honours the §4 surface.

    Subclasses must also inherit from ``unittest.TestCase`` (the discoverer
    only picks up TestCase subclasses). The mixin provides ``setUp`` and
    the contract assertions; subclasses override ``build_runtime`` to
    return a concrete Runtime instance wired to a fake herdr backend (or,
    in R2, a fake native daemon).

    Tests are written idempotently with a Runtime instance scoped to
    one test method (setUp creates it; the cleanup callback registered
    in ``addCleanup`` tears it down), so a flaky test in one runtime impl
    does not poison another.
    """

    def build_runtime(self):
        """Return a fresh Runtime for the current test."""
        raise NotImplementedError

    def setUp(self):
        # Each test gets a fresh system tempdir. We deliberately do NOT
        # pin under a sibling test's HOME — see the module-level note.
        self.fake_root = Path(tempfile.mkdtemp(prefix="contract-"))
        self.fake_herdr = _write_executable(self.fake_root / "herdr", _FAKE_TERM_HERDR)
        self.fake_agent = _write_executable(self.fake_root / "fake-agent", _FAKE_AGENT_SCRIPT)
        # The HerdrRuntime bin_getter points at the fake herdr; the
        # fake-agent script isn't used directly (the term herdr script
        # does the observe/control dance) but its presence keeps the
        # test layout aligned with the existing bridge test rig.
        self.runtime = self.build_runtime()
        self._opened: list = []
        self.addCleanup(self._cleanup)
        self.addCleanup(lambda: _rm(self.fake_root))

    def _cleanup(self):
        for sess in self._opened:
            try:
                self.runtime.abandon(sess.session_id, token=sess.token)
            except Exception:
                pass
        try:
            self.runtime.close_all()
        except Exception:
            pass

    # ---------- helpers ----------

    def _open(self, mode: str, target: str = "w1:pA") -> object:
        fn = self.runtime.observe if mode == "observe" else self.runtime.control
        sess = fn(target)
        if sess is not None:
            self._opened.append(sess)
        return sess

    def _drain(self, sess, n: int = 1, timeout: float = 5.0):
        out = []
        deadline = time.time() + timeout
        while len(out) < n and time.time() < deadline:
            try:
                out.append(sess.queue.get(timeout=0.2))
            except queue_mod.Empty:
                continue
        return out

    # ---------- identification ----------

    def test_describe_shape(self):
        d = self.runtime.describe()
        for key in ("name", "binary", "available", "problems"):
            self.assertIn(key, d, f"describe() missing {key!r}")
        self.assertTrue(isinstance(d["name"], str) and d["name"])

    def test_is_available_reflects_backend(self):
        # With the fake herdr backed the runtime reports True.
        self.assertTrue(self.runtime.is_available())

    def test_list_sessions_superset_shape(self):
        snap = self.runtime.list_sessions()
        for key in ("panes", "agents", "workspaces", "tabs"):
            self.assertIn(key, snap, f"list_sessions() missing {key!r}")
        self.assertTrue(isinstance(snap["panes"], list))

    def test_snapshot_alias_of_list_sessions(self):
        """snapshot() must return identical data to list_sessions() so
        existing call sites don't diverge between two calls' shapes."""
        snap = self.runtime.list_sessions()
        snap2 = self.runtime.snapshot()
        # We do NOT assert equality (agents can churn between the two
        # herdr calls), only that both have the same shape.
        self.assertEqual(set(snap.keys()), set(snap2.keys()))

    # ---------- target validation ----------

    def test_validate_target_accepts_known_good(self):
        self.assertTrue(self.runtime.validate_target("w1:pA"))
        self.assertTrue(self.runtime.validate_target("pane-id_1"))

    def test_validate_target_rejects_hostile_inputs(self):
        for hostile in ("", "--bad", "-flag", "a/b", "x" * 200):
            with self.subTest(hostile=hostile):
                self.assertFalse(self.runtime.validate_target(hostile))

    def test_focus_invalid_target_fails_loud(self):
        for hostile in ("--drop", "", "a/b", "x" * 200):
            with self.subTest(hostile=hostile):
                out = self.runtime.focus(hostile)
                self.assertFalse(out.get("ok"), f"focus({hostile!r}) succeeded: {out}")

    # ---------- observe / control / release lifecycle ----------

    def test_observe_yields_initial_full_frame(self):
        sess = self._open("observe")
        self.assertIsNotNone(sess, "observe() returned None on a working backend")
        self.assertEqual(sess.mode, "observe")
        # The session must carry the surface server.py reads (token / cols
        # / rows / queue / send_input / resize).
        for attr in ("session_id", "mode", "cols", "rows", "token", "queue",
                     "send_input", "resize"):
            self.assertTrue(hasattr(sess, attr), f"SessionView missing {attr!r}")
        [frame] = self._drain(sess, 1)
        self.assertEqual(frame["type"], "terminal.frame")
        self.assertTrue(frame["full"])

    def test_control_round_trip_input(self):
        sess = self._open("control")
        self.assertIsNotNone(sess)
        self.assertEqual(sess.mode, "control")
        self._drain(sess, 1)  # initial frame
        self.assertTrue(sess.send_input(b"hello"))
        [frame] = self._drain(sess, 1)
        self.assertIn("ECHO:hello", base64.b64decode(frame["bytes"]).decode())

    def test_observe_cannot_send_input(self):
        sess = self._open("observe")
        self._drain(sess, 1)
        # observe sessions are read-only; the bridge always returns False
        # from send_input in that mode. The contract only requires that
        # the runtime not pretend to deliver, so a False return suffices.
        self.assertFalse(sess.send_input(b"nope"))

    def test_release_yields_fresh_observe_session(self):
        self._open("control")
        new = self.runtime.release("w1:pA")
        self.assertIsNotNone(new)
        self.assertEqual(new.mode, "observe")

    # ---------- R1 review fixes (coordinator 2026-09-25) ----------

    def test_binary_is_path_only_no_backend_calls(self):
        """/api/config's herdr_binary must stay a cheap path lookup, as
        pre-R1 herdr.binary() was: no snapshot / subprocess round-trips."""
        from sidconsole.bridge import herdr as hb
        with mock.patch.object(hb, "snapshot", side_effect=AssertionError("snapshot called")), \
             mock.patch.object(hb, "_run", side_effect=AssertionError("_run called")):
            self.assertEqual(self.runtime.binary(), str(self.fake_herdr))

    def test_close_if_current_releases_even_if_already_closed(self):
        """SSE stream end: identical to TerminalBridge.close_if_current —
        release_and_stop() still runs on `expected` even when its child
        has already exited (abandon(token=) would purge it silently)."""
        sess = self._open("control")
        self.assertIsNotNone(sess)
        sess.closed = True  # child exited before the stream loop noticed
        with mock.patch.object(type(sess), "release_and_stop", autospec=True) as ras:
            self.runtime.close_if_current("w1:pA", sess)
        ras.assert_called_once_with(sess)
        self.assertIsNone(self.runtime.get("w1:pA"))

    def test_close_if_current_leaves_newer_session_running(self):
        first = self._open("observe")
        newer = self._open("control")  # takeover replaces `first`
        self.assertIsNot(first, newer)
        self.runtime.close_if_current("w1:pA", first)  # stale SSE reference
        self.assertIs(self.runtime.get("w1:pA"), newer)
        self.assertFalse(newer.closed)

    def test_release_with_no_active_session_is_none(self):
        self.assertIsNone(self.runtime.release("w1:nothing"))

    def test_get_returns_live_session_only(self):
        self.assertIsNone(self.runtime.get("w1:pA"))
        self._open("observe")
        self.assertIsNotNone(self.runtime.get("w1:pA"))

    # ---------- input / resize through Runtime methods ----------

    def test_input_round_trip_through_runtime_api(self):
        sess = self._open("control")
        self.assertIsNotNone(sess)
        self._drain(sess, 1)
        self.assertTrue(self.runtime.send_input("w1:pA", b"world"))
        [frame] = self._drain(sess, 1)
        self.assertIn("ECHO:world", base64.b64decode(frame["bytes"]).decode())

    def test_input_without_active_session_returns_false(self):
        self.assertFalse(self.runtime.send_input("w1:nope", b"x"))

    def test_resize_through_runtime_api(self):
        sess = self._open("control")
        self._drain(sess, 1)
        self.assertTrue(self.runtime.resize("w1:pA", 100, 40))
        [frame] = self._drain(sess, 1)
        self.assertIn("RESIZED:100x40", base64.b64decode(frame["bytes"]).decode())

    def test_resize_without_active_session_returns_false(self):
        self.assertFalse(self.runtime.resize("w1:nope", 80, 24))

    # ---------- abandon / close_all ----------

    def test_abandon_with_matching_token_stops(self):
        sess = self._open("observe")
        self._drain(sess, 1)
        self.assertTrue(self.runtime.abandon("w1:pA", token=sess.token))
        # Stopped: public get() no longer returns a session.
        self.assertIsNone(self.runtime.get("w1:pA"))

    def test_abandon_with_stale_token_is_noop(self):
        sess = self._open("observe")
        self._drain(sess, 1)
        self.assertFalse(self.runtime.abandon("w1:pA", token="not-the-right-token"))
        self.assertIs(self.runtime.get("w1:pA"), sess)

    def test_close_all_clears_bridge_state(self):
        self._open("observe")
        self.runtime.close_all()
        self.assertIsNone(self.runtime.get("w1:pA"))

    # ---------- unsupported ops (R1 §3.1 explicit refusal) ----------

    def test_open_session_raises_notsupported(self):
        """R1's HerdrRuntime cannot open a session; the contract demands
        an explicit NotSupported, not a silent no-op or fake success."""
        from sidconsole.runtime import NotSupported
        with self.assertRaises(NotSupported):
            self.runtime.open_session({"cwd": "/"})

    def test_close_raises_notsupported(self):
        from sidconsole.runtime import NotSupported
        with self.assertRaises(NotSupported):
            self.runtime.close("w1:pA")

    # ---------- status / no-data path ----------

    def test_status_unknown_for_untracked_session(self):
        # No fake herdr session for this id; contract says: say 'unknown'.
        self.assertEqual(self.runtime.status("w1:unknown"), "unknown")

    def test_status_falls_back_to_unknown_when_backend_missing(self):
        """When herdr itself is unavailable, status returns 'unknown'
        rather than crashing. Validates the project's "no data → say
        unknown" rule (PHASE-R-PLAN §6 + standing principle)."""
        from sidconsole.runtime import HerdrRuntime
        # Point at a non-existent binary to simulate herdr being absent.
        no_herdr = HerdrRuntime(bin_getter=lambda: "/no/such/herdr-binary")
        self.assertEqual(no_herdr.status("w1:pA"), "unknown")

    # ---------- conflict / error modes from the fake backend ----------

    def test_attach_conflict_surfaces_as_closed(self):
        """A backend refusing an attach must surface as a
        terminal.closed frame, not a hang. Confirms the contract the
        existing bridge already held (A0 finding)."""
        sess = self.runtime.control("always-conflict")
        self.assertIsNotNone(sess)
        [closed] = self._drain(sess, 1)
        self.assertEqual(closed["type"], "terminal.closed")
        self.assertIn("conflict", closed["reason"].lower())


# R1 ships exactly one implementation; the subclass below is what makes
# the existing tests run against that implementation. R2 adds another
# subclass by repeating the pattern. The class name encodes the impl so
# a test failure says "HerdrRuntime failed X" rather than "Runtime failed X".
# Inheriting from unittest.TestCase is what lets the discoverer find it;
# the contract assertions come from the RuntimeContractBase mixin.
class HerdrRuntimeContract(RuntimeContractBase, unittest.TestCase):
    """The R1 contract as HerdrRuntime honours it."""

    def build_runtime(self):
        # Called from RuntimeContractBase.setUp after the fake herdr is
        # written; a future NativeRuntimeContract overrides only this.
        from sidconsole.runtime import HerdrRuntime
        return HerdrRuntime(bin_getter=lambda: str(self.fake_herdr))


# ---------------------------------------------------------------------------
# Direct tests on the abstract RuntimeBase — these check the contract
# itself, independent of any implementation, so an obvious gap (a
# missing method) fails the build before any runtime is instantiated.
# ---------------------------------------------------------------------------

class RuntimeBaseContract(unittest.TestCase):

    def test_runtime_base_is_abstract(self):
        from sidconsole.runtime import RuntimeBase
        # Cannot instantiate directly without providing every abstract method.
        with self.assertRaises(TypeError):
            RuntimeBase()  # type: ignore[abstract]

    def test_runtime_base_default_close_is_not_supported(self):
        from sidconsole.runtime import NotSupported, RuntimeBase

        class Stub(RuntimeBase):
            # Only implement the methods needed so the class is concrete.
            def describe(self): return {"name": "stub", "available": False,
                                        "binary": None, "version": None, "problems": []}
            def list_sessions(self): return {}
            def snapshot(self): return {}
            def validate_target(self, t): return bool(t)
            def status(self, sid): return "unknown"
            def observe(self, sid, cols=80, rows=24): return None
            def control(self, sid, cols=80, rows=24): return None
            def release(self, sid): return None
            def abandon(self, sid, token=None): return False
            def send_input(self, sid, data): return False
            def resize(self, sid, cols, rows): return False
            def get(self, sid): return None
            def focus(self, target): return {"ok": True}
            def close_all(self): pass

        stub = Stub()
        # Explicit refusal from the base for R1-cannot-honour ops.
        with self.assertRaises(NotSupported):
            stub.open_session({})
        with self.assertRaises(NotSupported):
            stub.close("w1:pA")
        with self.assertRaises(NotSupported):
            stub.close_if_current("w1:pA", object())
        # binary() default falls back to describe()
        self.assertIsNone(stub.binary())

    def test_get_runtime_factory_herdr(self):
        from sidconsole.runtime import HerdrRuntime, NotSupported, get_runtime
        rt = get_runtime(bin_getter=lambda: "")
        self.assertIsInstance(rt, HerdrRuntime)

    def test_get_runtime_factory_rejects_unknown_kind(self):
        from sidconsole.runtime import NotSupported, get_runtime
        with self.assertRaises(NotSupported):
            get_runtime(bin_getter=lambda: "", kind="native-2026")


if __name__ == "__main__":
    unittest.main()
