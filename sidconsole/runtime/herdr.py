"""HerdrRuntime: the R1 implementation of the Runtime protocol.

This module is the seam between the abstract ``RuntimeBase`` and the
two pre-existing bridged pieces (``bridge.herdr`` for the CLI-shaped
queries, ``bridge.terminal`` for the per-pane observe/control child
processes). It does not move any logic out of those modules; it only
forwards, so behaviour, error messages, timeouts, and concurrency
semantics remain bit-for-bit identical. R2's ``NativeRuntime`` will sit
next to this file and replace both pieces wholesale; the rest of the
console never imports ``bridge.*`` directly again (see grep guard in
R1 contract §6.3).

Herdr-specific notes worth recording here rather than only in the bridge
modules:

* ``herdr binary`` is resolved on every call. The underlying CLI may be
  installed or removed between requests, and the binary path is read
  from the live config (which the user can change via ``/api/config``
  without a server restart). We forward the same resolver into the
  terminal bridge so its lazy open_observer() sees the new path too.
* The "two child processes per pane are not necessary" rationale lives
  in ``bridge.terminal``; this module does not duplicate it.
* ``focus`` returns the herdr shape (``{"ok": bool, "data"|"error": ...}``)
  unchanged so server.py's ``_json(herdr.focus(...))`` keeps returning the
  same body the frontend already knows how to render.
"""

from __future__ import annotations

from typing import Any

from ..bridge import herdr as _herdr_bridge
from ..bridge import terminal as _term_bridge
from .base import NotSupported, RuntimeBase, SessionView


class HerdrRuntime(RuntimeBase):
    """The R1 Runtime backed by ``herdr``.

    Constructor takes a ``bin_getter`` callable rather than a static path.
    The console pulls the configured herdr_bin through this getter on
    every call so a config update via ``/api/config`` takes effect without
    a server restart (behaviour the existing ``Console.__init__`` has
    today; preserved verbatim — server.py L94-95 in commit b34e966).
    """

    def __init__(self, bin_getter):
        if bin_getter is None or not callable(bin_getter):
            raise TypeError("HerdrRuntime needs a callable bin_getter "
                            "(configured binary or env override)")
        self._bin_getter = bin_getter
        self._bridge = _term_bridge.TerminalBridge(self._bin_path)

    # --- resolver ----------------------------------------------------------

    def _bin_path(self) -> str | None:
        """The configured herdr path, or None if herdr is unavailable.

        Mirrors ``bridge.herdr.binary`` but routes through the injectable
        getter so tests can pin a fake binary without touching PATH or
        environment variables.
        """
        return _herdr_bridge.binary(self._bin_getter() or "")

    # --- identification ----------------------------------------------------

    def describe(self) -> dict:
        """Doctor / config payload.

        Not a session list; that's ``list_sessions()``.
        """
        snap = _herdr_bridge.snapshot(self._bin_getter() or "")
        return {
            "name": "herdr",
            "version": snap.get("version"),
            "binary": snap.get("binary"),
            "available": bool(snap.get("available")),
            "problems": list(snap.get("problems") or []),
        }

    def binary(self) -> str | None:
        """Resolved herdr path only — same as pre-R1 ``herdr.binary(...)``;
        no subprocess calls (used by /api/config)."""
        return self._bin_path()

    def is_available(self) -> bool:
        """True only when herdr itself can be invoked right now.

        This is the hot-path gate (``observe`` / ``control`` / ``focus``
        skip their backend call when False). Kept separate from
        ``describe`` so callers that just want a yes/no do not pay for the
        five-round snapshot.
        """
        return self._bin_path() is not None

    # --- read-only ---------------------------------------------------------

    def list_sessions(self) -> dict:
        """Full herdr-shaped view (panes, agents, workspaces, tabs)."""
        return _herdr_bridge.snapshot(self._bin_getter() or "")

    def snapshot(self) -> dict:
        """Alias of list_sessions().

        Kept for callers already using the old ``herdr.snapshot()`` name.
        PHASE-R-PLAN §4 calls it ``list_sessions``; both must point at
        the same data.
        """
        return self.list_sessions()

    def validate_target(self, target: str) -> bool:
        return _herdr_bridge.valid_target(target)

    def status(self, session_id: str) -> str:
        """Best-effort status from the latest snapshot.

        Returns ``"unknown"`` whenever the pane is not in the snapshot,
        has no agent, or herdr is unavailable. PHASE-R-PLAN §4 mandates
        the ``unknown`` fallback and the project's standing honesty rule
        "no data → say unknown" demands the same.
        """
        if not self.is_available():
            return "unknown"
        snap = self.list_sessions()
        for agent in snap.get("agents") or ():
            ref = agent.get("pane_id") or agent.get("terminal_id")
            if ref == session_id:
                return str(agent.get("agent_status") or "unknown") or "unknown"
        for pane in snap.get("panes") or ():
            if pane.get("pane_id") == session_id or pane.get("terminal_id") == session_id:
                return str(pane.get("agent_status") or "unknown") or "unknown"
        return "unknown"

    def focus(self, target: str) -> dict:
        """Bring ``target`` to the foreground (herdr ``agent focus``).

        Validates before reaching argv: herdr treats any ``--``-prefixed
        string as an option, so a syntactically bad id must be refused
        here, not passed through. Returns the same dict shape the
        existing server.py expects unchanged.
        """
        if not self.validate_target(target):
            return {"ok": False, "error": "無效的目標識別碼"}
        return _herdr_bridge.focus(target, self._bin_getter() or "")

    # --- session lifecycle (delegated to bridge.terminal) ------------------

    def observe(self, session_id: str, cols: int = 80, rows: int = 24) -> SessionView | None:
        """Watch-only session (herdr ``terminal session observe``).

        Returns ``None`` when either herdr is unavailable or the
        MAX_CONCURRENT_PANES cap is reached. Callers distinguish by
        checking ``is_available()`` on their own.
        """
        if not self.is_available():
            return None
        return self._bridge.open_observer(session_id, cols, rows)

    def control(self, session_id: str, cols: int = 80, rows: int = 24) -> SessionView | None:
        """Take over (herdr ``terminal session control --takeover``).

        Spawns a new control session and atomically replaces any prior
        session on this pane (the CAS guard inside TerminalBridge does
        this; do not change the ordering here).
        """
        if not self.is_available():
            return None
        return self._bridge.takeover(session_id, cols, rows)

    def release(self, session_id: str) -> SessionView | None:
        """Drop back from control to a fresh observe session.

        Delegates entirely to the bridge: ``TerminalBridge.release``
        already handles the case where herdr has become unavailable since
        the control session started (it tears the session down without
        spawning an observe replacement). Do not short-circuit on
        ``is_available()`` here — that path loses the cleanup.
        """
        return self._bridge.release(session_id)

    def abandon(self, session_id: str, token: str | None = None) -> bool:
        """Stop the session entirely; with ``token`` only if the live
        session matches (atomic no-op otherwise — bridge handles both).
        """
        return self._bridge.abandon(session_id, token)

    def close_if_current(self, session_id: str, expected: SessionView) -> None:
        """Verbatim delegation to TerminalBridge.close_if_current (SSE
        stream end). Unlike ``abandon(token=...)`` it still calls
        release_and_stop() on ``expected`` even if it already closed."""
        self._bridge.close_if_current(session_id, expected)

    def send_input(self, session_id: str, data: bytes) -> bool:
        """Write to the pane's active control session, if any."""
        sess = self._bridge.get(session_id)
        if sess is None or sess.mode != "control":
            return False
        return sess.send_input(data)

    def resize(self, session_id: str, cols: int, rows: int) -> bool:
        sess = self._bridge.get(session_id)
        if sess is None or sess.mode != "control":
            return False
        return sess.resize(cols, rows)

    def get(self, session_id: str) -> SessionView | None:
        return self._bridge.get(session_id)

    def close_all(self) -> None:
        self._bridge.close_all()

    # --- context manager (server-down cleanup convenience) ----------------

    def __enter__(self) -> "HerdrRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close_all()


__all__ = ["HerdrRuntime"]
