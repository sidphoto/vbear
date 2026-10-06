"""Runtime factory.

VBear runs its own terminal runtime (``NativeRuntime`` backed by
``vbear runtimed``). The Herdr bridge was removed after Gate 10 (R-D5);
the last Herdr-capable code is tagged ``last-herdr``.
"""

from __future__ import annotations

from .base import NotSupported, RuntimeBase, SessionView
from .native import NativeRuntime


RUNTIME_KINDS = ("native",)


def get_runtime(*, kind: str = "native", base=None, autostart: bool = False) -> RuntimeBase:
    """Return the runtime. ``autostart`` lets it spawn ``vbear runtimed``
    on first need. Any kind other than ``native`` is an explicit failure."""
    if kind != "native":
        raise NotSupported(f"runtime kind '{kind}' is not available")
    return NativeRuntime(base, autostart=autostart)


__all__ = ["RUNTIME_KINDS", "get_runtime", "NativeRuntime", "RuntimeBase", "SessionView", "NotSupported"]
