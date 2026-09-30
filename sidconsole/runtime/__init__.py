"""Runtime factory.

Two implementations: ``HerdrRuntime`` (R1, default) and ``NativeRuntime``
(R2). The console picks one from the ``runtime_kind`` config field at
startup (R2 S3); ``herdr`` stays the default so existing installs are
unchanged.
"""

from __future__ import annotations

from typing import Callable

from .base import NotSupported, RuntimeBase, SessionView
from .herdr import HerdrRuntime
from .native import NativeRuntime


RUNTIME_KINDS = ("herdr", "native")


def get_runtime(bin_getter: Callable[[], str] | None = None, *, kind: str = "herdr",
                base=None, autostart: bool = False) -> RuntimeBase:
    """Return the active Runtime.

    ``kind="herdr"`` (default) keeps the R1 behaviour; ``bin_getter`` is read
    on every call so /api/config changes apply without a restart.
    ``kind="native"`` (R2 S3) returns a NativeRuntime; ``autostart`` lets it
    spawn ``sidconsole runtimed`` on first need. Any other kind is an
    explicit failure, never a silent fallback.
    """
    if kind == "native":
        return NativeRuntime(base, autostart=autostart)
    if kind != "herdr":
        raise NotSupported(f"runtime kind '{kind}' is not implemented")
    if bin_getter is None:
        bin_getter = lambda: ""
    return HerdrRuntime(bin_getter)


__all__ = ["RUNTIME_KINDS", "get_runtime", "HerdrRuntime", "NativeRuntime", "RuntimeBase", "SessionView",
           "NotSupported"]
