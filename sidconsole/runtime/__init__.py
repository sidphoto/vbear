"""Runtime factory.

R1 ships one implementation: ``HerdrRuntime``. The factory exists so that
when R2 adds ``NativeRuntime``, swapping backends is one line at a call
site (or one config field) instead of a rewire of every importer.

Today there is no native toggle, no environment switch, no config flag —
exactly what the R1 contract §3.1 says: "**不得**新增 native 設定開關
（R2 範圍）". Adding one here would be a premature commit.
"""

from __future__ import annotations

from typing import Callable

from .base import NotSupported, RuntimeBase, SessionView
from .herdr import HerdrRuntime
from .native import NativeRuntime  # R2 S2; not selectable via get_runtime until S3


def get_runtime(bin_getter: Callable[[], str] | None = None, *, kind: str = "herdr") -> RuntimeBase:
    """Return the active Runtime.

    Parameters
    ----------
    bin_getter:
        Callable returning the configured herdr binary path (or ``""``).
        Required for ``kind="herdr"`` because the runtime needs to look the
        path up on every call — config updates via ``/api/config`` have
        to take effect without a server restart.
    kind:
        Reserved. R1 only accepts ``"herdr"``; passing anything else is
        an explicit failure rather than a silent fallback to herdr, since
        the project promises "R1 abstract layer; R2 brings native".
    """
    if kind != "herdr":
        raise NotSupported(f"runtime kind '{kind}' is not implemented (R1 ships only 'herdr')")
    if bin_getter is None:
        # Default getter: empty string. The herdr binary search falls back
        # to PATH / HERDR_BIN_PATH, so an empty getter is identical to
        # calling herdr.binary("") directly. This keeps tests / one-shot
        # scripts working without wiring config first.
        bin_getter = lambda: ""
    return HerdrRuntime(bin_getter)


__all__ = ["get_runtime", "HerdrRuntime", "NativeRuntime", "RuntimeBase", "SessionView",
           "NotSupported"]
