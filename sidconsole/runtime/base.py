"""Runtime protocol (PHASE-R-PLAN §4) for the terminal-host backend.

The one implementation is ``NativeRuntime``. The protocol keeps server.py /
index.py / __main__.py independent of it and lets tests substitute a fake.
(The original R1 ``HerdrRuntime`` was removed after Gate 10; see tag
``last-herdr``.)

Shape choice (Protocol vs ABC):
  - ``typing.Protocol`` with ``runtime_checkable`` lets the contract tests
    ask ``isinstance(runtime, Runtime)`` against any object that quacks
    like one — useful when a test rig substitutes a fake that does not want
    to formally subclass ``Runtime``.
  - Methods the §4 table marks as "MUST exist" are declared as abstract on
    a concrete ``ABC`` (``RuntimeBase``); concrete implementations inherit
    from it and get a clear ``TypeError`` if they forget one.
  - Optional methods (``open_session``, ``close``) are concrete on the base
    and ``raise NotSupported``. Implementations that can honour
    them override; those that cannot inherit the explicit refusal and the
    UI gets a real failure to translate, not a silent pretend-success.

User-facing contract (see also PHASE-R-PLAN §4):

  describe()              -> dict  name / version / binary / available / problems
  is_available()          -> bool  ready to be asked for sessions at all
  list_sessions()         -> dict  panes + agents + workspaces + tabs;
                                  supersets the per-session read surface
  snapshot()              -> dict  an alias for list_sessions(); kept so the
                                  Doctor / Store paths do not need their
                                  shape renamed just to migrate
  validate_target(t)      -> bool  syntax-level id check
  status(session_id)      -> str   ``idle`` / ``working`` / ``exited`` /
                                  ``unknown``. ``unknown`` whenever the
                                  backend cannot tell, per the project's
                                  standing "no data → say unknown" rule.
  observe(session_id)     -> SessionView | None
  control(session_id)     -> SessionView | None
  release(session_id)     -> SessionView | None
  abandon(session_id, token=None) -> bool
  send_input(sid, data)   -> bool
  resize(sid, cols, rows) -> bool
  get(session_id)         -> SessionView | None  current live session
  close_all()             -> None  stop every active session (server-down)

Optional (raise NotSupported on the base; override to support):

  open_session(spec)      -> SessionView
  close(session_id)       -> bool

The "describe" extra, the "snapshot"/"validate_target" extras, and
the ``list_sessions``-is-superset note come from the R1 contract section 3.1
(not all are in §4, but server.py and Doctor already rely on them, so the
protocol must keep them).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NotSupported(Exception):
    """The Runtime advertises the capability but cannot honour it right now.

    Not to be confused with "the Runtime is unavailable" (which surfaces as
    ``is_available() == False`` and ``describe()['available'] == False``).
    UI / API code is expected to treat the exception as a user-visible
    "not available" and not retry.
    """


class SessionView:
    """The per-session object a Runtime hands to server.py after open.

    A structural specification, not a wrapper: ``NativeRuntime`` returns its
    attachment object, which carries this surface (mode / cols / rows /
    token / queue / send_input / resize).

    Kept as a class (not an ABC) because the public surface is read-mostly;
    implementations are free to be richer objects.
    """

    session_id: str
    mode: str  # "observe" | "control"
    cols: int
    rows: int
    token: str

    # Terminal frames are placed on .queue (one dict per frame, sentinel
    # None at end of stream).
    queue: Any

    def send_input(self, data: bytes) -> bool:
        raise NotImplementedError

    def resize(self, cols: int, rows: int) -> bool:
        raise NotImplementedError


class RuntimeBase(ABC):
    """Common Runtime behaviour: identification helpers, R1 stubs.

    Subclasses implement the abstract §4 methods and override the R1 stubs
    only when they actually honour them.
    """

    # ---- identification (concrete, every Runtime can describe itself) ----

    def is_available(self) -> bool:
        """Whether this Runtime is presently usable. Default = no, which is
        correct for an uninitialised Runtime; subclasses with a real backend
        should override (typically via describe()['available']).
        """
        return bool(self.describe().get("available"))

    @abstractmethod
    def describe(self) -> dict:
        """{name, version, binary, available, problems}. Used by Doctor and
        /api/config. The shape is fixed; native R2 will populate it from
        its own daemon, not the empty default."""

    def binary(self) -> str | None:
        """Cheap path lookup for /api/config (no backend round-trips).
        Default falls back to describe(); backends with a cheaper resolver
        should override."""
        return self.describe().get("binary")

    def close_if_current(self, session_id: str, expected: SessionView) -> None:
        """SSE stream-end cleanup: stop ``expected`` only if it is still the
        live session for session_id (identity check), releasing control
        first. Backends must override; there is no safe generic fallback."""
        raise NotSupported("close_if_current is not supported by the active runtime")

    # ---- optional capabilities: the explicit refusal is the contract here,
    # not a silent fallback. Override only in implementations that can
    # honour them. ----

    def open_session(self, spec: Any) -> SessionView:
        """Open a new session by specification (cwd, command, env, ...).

        A runtime without this capability fails explicitly rather than
        faking success.
        """
        raise NotSupported("open_session is not supported by the active runtime")

    def close(self, session_id: str) -> bool:
        """End a session and its process group (§4 close).

        A runtime that does not own the session lifecycle raises NotSupported.
        """
        raise NotSupported("close is not supported by the active runtime")

    # ---- abstract §4 surface (subclasses must provide) ----

    @abstractmethod
    def list_sessions(self) -> dict:
        """All sessions and panes (panes, agents, workspaces, tabs, problems).
        server.py / index.py iterate this view."""

    @abstractmethod
    def snapshot(self) -> dict:
        """Alias of list_sessions()."""

    @abstractmethod
    def validate_target(self, target: str) -> bool:
        """Syntax-only validity of a session id."""

    @abstractmethod
    def status(self, session_id: str) -> str:
        """``idle`` / ``working`` / ``exited`` / ``unknown``.

        ``unknown`` whenever the runtime cannot tell; that is also what
        the project ships in this state otherwise, per the standing
        honesty rule."""

    @abstractmethod
    def observe(self, session_id: str, cols: int = 80, rows: int = 24) -> SessionView | None:
        """Begin watch-only streaming of session_id."""

    @abstractmethod
    def control(self, session_id: str, cols: int = 80, rows: int = 24) -> SessionView | None:
        """Take over (can type) session_id; replaces any prior session."""

    @abstractmethod
    def release(self, session_id: str) -> SessionView | None:
        """Drop back from ``control`` to ``observe`` (fresh session).

        Returns the new observe session, or ``None`` when there was no
        control session to release."""
        ...

    @abstractmethod
    def abandon(self, session_id: str, token: str | None = None) -> bool:
        """Stop the session entirely without spawning an observe session.
        With ``token``: only stop if the token matches the live session
        (atomic no-op when it does not)."""

    @abstractmethod
    def send_input(self, session_id: str, data: bytes) -> bool:
        """Write raw bytes to the active control session of session_id."""

    @abstractmethod
    def resize(self, session_id: str, cols: int, rows: int) -> bool:
        """Resize the active session of session_id."""

    @abstractmethod
    def get(self, session_id: str) -> SessionView | None:
        """Currently active session of session_id, or None."""

    @abstractmethod
    def close_all(self) -> None:
        """Stop every active session (server shutdown)."""


# Public re-exports so callers do not need to reach into base directly.
__all__ = ["NotSupported", "RuntimeBase", "SessionView"]
