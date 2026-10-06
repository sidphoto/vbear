"""Contract tests for the Runtime abstraction.

These check ``RuntimeBase`` itself and the runtime factory. The concrete
``NativeRuntime`` is exercised end to end in tests/test_runtimed_*.py.
The Herdr-backed contract tests were removed with the Herdr bridge after
Gate 10 (R-D5); the last version is under tag ``last-herdr``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class RuntimeBaseContract(unittest.TestCase):

    def test_runtime_base_is_abstract(self):
        from vbear.runtime import RuntimeBase
        # Cannot instantiate directly without providing every abstract method.
        with self.assertRaises(TypeError):
            RuntimeBase()  # type: ignore[abstract]

    def test_runtime_base_default_close_is_not_supported(self):
        from vbear.runtime import NotSupported, RuntimeBase

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
            def close_all(self): pass

        stub = Stub()
        # Explicit refusal from the base for optional ops.
        with self.assertRaises(NotSupported):
            stub.open_session({})
        with self.assertRaises(NotSupported):
            stub.close("w1:pA")
        with self.assertRaises(NotSupported):
            stub.close_if_current("w1:pA", object())
        # binary() default falls back to describe()
        self.assertIsNone(stub.binary())

    def test_get_runtime_factory_is_native(self):
        from vbear.runtime import NativeRuntime, RUNTIME_KINDS, get_runtime
        self.assertEqual(RUNTIME_KINDS, ("native",))
        self.assertIsInstance(get_runtime(), NativeRuntime)

    def test_get_runtime_factory_rejects_other_kinds_including_herdr(self):
        from vbear.runtime import NotSupported, get_runtime
        for kind in ("herdr", "native-2026", ""):
            with self.subTest(kind=kind):
                with self.assertRaises(NotSupported):
                    get_runtime(kind=kind)

    def test_herdr_runtime_is_gone(self):
        import vbear.runtime as runtime
        self.assertFalse(hasattr(runtime, "HerdrRuntime"))
        with self.assertRaises(ImportError):
            __import__("vbear.bridge.herdr")


if __name__ == "__main__":
    unittest.main()
