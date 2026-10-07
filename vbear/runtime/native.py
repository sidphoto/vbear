"""NativeRuntime: the R2 Runtime backed by VBear's own runtime daemon.

Contract v2 §1/§2B/§5/§10 S2. The daemon (``runtime/daemon.py``) owns the
PTY sessions; this adapter owns *attachments* — one attach connection per
``SessionView`` — and maps the R1 ``RuntimeBase`` surface onto them:

* ``observe`` / ``control`` / ``release`` / ``abandon`` / ``close_if_current``
  only open or drop attach connections; the terminal keeps running.
* ``close(session_id)`` is the only call that ends a terminal.
* ``close_all`` drops this server's attachments; sessions survive (R-D4).
* ``control`` / ``release`` are serialised per session (a per-pane lock), so
  the daemon's "last control attach wins" order and the order this adapter
  installs views can never invert (§10 S2).
* Observer fan-out: server.py reads ``view.queue`` from each SSE thread. The
  ``queue`` property hands every reading thread its own queue, primed with a
  full frame built from the recent tail, so two tabs never steal each
  other's frames (§10 S2).

Frames placed on the queues have the terminal-frame shape the web client expects
(``terminal.frame`` / ``terminal.closed`` / ``None`` sentinel), so the SSE
loop in server.py needs no change.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import platform
import queue as queue_mod
import re
import secrets
import socket
import threading
import time
from pathlib import Path

from .. import config as cfg
from . import daemon as _d
from . import cli_versions as _cli_versions
from . import agent_sessions as _agent_sessions
from .base import RuntimeBase, SessionView

QUEUE_MAX = 200               # per subscriber, drop-oldest
MAX_SUBSCRIBERS = 8
MAX_CONCURRENT_PANES = 4
LINE_MAX = 2 << 20            # client-side frame line cap
TAIL_MAX = _d.FULL_REPLAY_MAX
SESSION_RE = re.compile(r"^n-[0-9a-f]{12}$")
WORKSPACE_ID = "native"


class NativeRuntimeError(Exception):
    """A native runtime request failed; message is user-facing."""


class NativeRuntimeUnavailable(NativeRuntimeError):
    """The daemon cannot be reached (and could not be started)."""


class AttachRefused(NativeRuntimeError):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def _pinned_claude_binary() -> str | None:
    """Install path of the newest verified Claude Code version that is present,
    or None to fall back to PATH lookup (the current, possibly unverified,
    release). Either way the version check decides and reports which it is."""
    versions = Path.home() / ".local/share/claude/versions"
    ordered = sorted(_cli_versions.verified_versions("claude"),
                     key=lambda v: tuple(int(x) for x in v.split(".")))
    for version in reversed(ordered):
        pinned = versions / version
        if pinned.is_file():
            return str(pinned)
    return None


def _pinned_codex_binary() -> str:
    """Install path of the fixed Codex baseline; never fall back to newer PATH."""
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    release = f"{_cli_versions.EXPECTED_VERSIONS['codex']}-{arch}-apple-darwin"
    pinned = Path.home() / ".codex/packages/standalone/releases" / release / "bin/codex"
    return str(pinned)


def _agent_engine(info: dict) -> str | None:
    """Which Agent CLI a daemon session runs: the managed launch's engine, or
    the command name for a plain session started as ``claude`` / ``codex``."""
    engine = info.get("engine")
    if engine in ("claude", "codex"):
        return engine
    argv = info.get("argv") or []
    name = Path(argv[0]).name if argv else ""
    return name if name in ("claude", "codex") else None


def _line(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"


def _put(q: queue_mod.Queue, msg) -> None:
    while True:
        try:
            q.put_nowait(msg)
            return
        except queue_mod.Full:
            try:
                q.get_nowait()
            except queue_mod.Empty:
                pass


def attach_socket(path, session_id: str, mode: str, cols: int, rows: int,
                  timeout: float = 3.0):
    """Open an attach connection. Returns (sock, handshake_result, leftover).
    Raises AttachRefused when the daemon says no, OSError/ValueError when it
    cannot be reached or answers garbage."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(str(path))
        s.sendall(_line({"v": _d.PROTOCOL_VERSION, "id": secrets.token_hex(8), "op": "attach",
                         "session_id": session_id, "mode": mode, "cols": cols, "rows": rows}))
        buf = bytearray()
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("runtime daemon closed the attach connection")
            buf += chunk
            if len(buf) > LINE_MAX:
                raise ConnectionError("attach handshake too long")
        nl = buf.find(b"\n")
        resp = json.loads(bytes(buf[:nl]).decode("utf-8"))
        if not isinstance(resp, dict):
            raise ValueError("bad handshake")
        if not resp.get("ok"):
            err = resp.get("error") or {}
            raise AttachRefused(str(err.get("message") or "attach refused"), str(err.get("code") or ""))
        s.settimeout(None)
        return s, resp.get("result") or {}, bytes(buf[nl + 1:])
    except BaseException:
        s.close()
        raise


class NativeAttachment(SessionView):
    """One attach connection, exposing the R1 SessionView surface."""

    def __init__(self, session_id: str, mode: str, cols: int, rows: int, *,
                 sock: socket.socket | None = None, attachment_id: str | None = None,
                 leftover: bytes = b"", fail_reason: str | None = None):
        self.session_id = session_id
        self.pane_id = session_id  # R1 vocabulary alias
        self.mode = mode
        self.cols, self.rows = cols, rows
        self.token = secrets.token_hex(16)
        self.attachment_id = attachment_id
        self.closed = False
        self.close_reason: str | None = None
        self.last_error: str | None = None
        self._sock = sock
        self._wlock = threading.Lock()
        self._slock = threading.Lock()
        self._subs: dict[int, queue_mod.Queue] = {}
        self._tail = bytearray()
        self._seq = 0
        self._have_frame = False
        self._closed_msg: dict | None = None
        self._stopped = False
        self._reader: threading.Thread | None = None
        if sock is None:
            self._finish({"type": "terminal.closed", "reason": fail_reason or "無法連線到 runtime"})
        else:
            self._reader = threading.Thread(target=self._read_loop, args=(leftover,), daemon=True,
                                            name=f"sid-native-{session_id}")
            self._reader.start()

    # ---- per-reader queues (fan-out) ----

    @property
    def queue(self) -> queue_mod.Queue:
        ident = threading.get_ident()
        with self._slock:
            q = self._subs.get(ident)
            if q is not None:
                return q
            alive = {t.ident for t in threading.enumerate()}
            for k in [k for k in self._subs if k not in alive]:
                del self._subs[k]
            while len(self._subs) >= MAX_SUBSCRIBERS:
                self._subs.pop(next(iter(self._subs)))
            q = queue_mod.Queue(maxsize=QUEUE_MAX)
            if self._have_frame:
                _put(q, self._synth_full())
            if self._closed_msg is not None:
                _put(q, self._closed_msg)
                _put(q, None)
            self._subs[ident] = q
            return q

    def _synth_full(self) -> dict:
        data = bytes(self._tail)
        if len(data) > TAIL_MAX or not data.startswith(_d.RIS):
            # Cut the tail first, then skip continuation bytes, then add the
            # reset -- same order as daemon.replay_bytes (AGY S2 F1).
            buf = data[-(TAIL_MAX - len(_d.RIS)):]
            start = 0
            while start < len(buf) and start < 4 and (buf[start] & 0xC0) == 0x80:
                start += 1
            data = _d.RIS + buf[start:]
        return {"type": "terminal.frame", "bytes": base64.b64encode(data).decode("ascii"),
                "encoding": "ansi", "full": True, "seq": self._seq,
                "width": self.cols, "height": self.rows}

    def _publish(self, msg: dict) -> None:
        with self._slock:
            try:
                data = base64.b64decode(msg.get("bytes") or "", validate=True)
            except (binascii.Error, ValueError, TypeError):
                data = b""
            if msg.get("full"):
                self._tail = bytearray(data)
            else:
                self._tail += data
            over = len(self._tail) - TAIL_MAX
            if over > 0:
                del self._tail[:over]
            if isinstance(msg.get("seq"), int):
                self._seq = msg["seq"]
            w, h = msg.get("width"), msg.get("height")
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                self.cols, self.rows = w, h  # follow the controller's resize (AGY S2 F2)
            self._have_frame = True
            for q in self._subs.values():
                _put(q, msg)

    def _finish(self, msg: dict) -> None:
        with self._slock:
            if self._closed_msg is not None:
                return
            self._closed_msg = msg
            self.close_reason = str(msg.get("reason") or "已結束")
            for q in self._subs.values():
                _put(q, msg)
                _put(q, None)
            self.closed = True

    def _read_loop(self, leftover: bytes) -> None:
        buf = bytearray(leftover)
        try:
            while True:
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    raw = bytes(buf[:nl])
                    del buf[:nl + 1]
                    try:
                        msg = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if not isinstance(msg, dict):
                        continue
                    kind = msg.get("type")
                    if kind == "terminal.frame":
                        self._publish(msg)
                    elif kind == "terminal.control_lost":
                        self.mode = "observe"  # another view took over
                    elif kind == "terminal.error":
                        self.last_error = str(msg.get("code") or "")
                    elif kind == "terminal.closed":
                        self._finish(msg)
                        return
                if len(buf) > LINE_MAX:
                    break
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except OSError:
            pass
        # EOF without terminal.closed: the connection, not the terminal, ended.
        self._finish({"type": "terminal.closed", "connection_interrupted": True,
                      "reason": "與 VBear runtime 的連線中斷（未收到結束訊息，Terminal 本身可能仍在執行）"})

    # ---- writing ----

    def _write(self, msg: dict) -> bool:
        if self._sock is None or self.closed or self._stopped:
            return False
        try:
            with self._wlock:
                self._sock.sendall(_line(msg))
            return True
        except OSError:
            return False

    def send_input(self, data: bytes) -> bool:
        if self.mode != "control" or not data:
            return False
        ok = True
        for i in range(0, len(data), _d.INPUT_MAX):
            chunk = base64.b64encode(data[i:i + _d.INPUT_MAX]).decode("ascii")
            ok = self._write({"type": "terminal.input", "bytes": chunk}) and ok
        return ok

    def resize(self, cols: int, rows: int) -> bool:
        if self.mode != "control":
            return False
        self.cols, self.rows = cols, rows
        return self._write({"type": "terminal.resize", "cols": cols, "rows": rows})

    def release_control(self) -> bool:
        return self.mode == "control" and self._write({"type": "terminal.release"})

    def release_and_stop(self, grace_s: float = 2.0) -> None:
        if self.mode == "control" and self.release_control() and self._reader is not None \
                and self._reader is not threading.current_thread():
            self._reader.join(grace_s)  # daemon answers terminal.closed "released"
        self.stop()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(2)
        if self._sock is not None:
            self._sock.close()


class NativeRuntime(RuntimeBase):
    """R2 Runtime backed by ``vbear runtimed``."""

    def __init__(self, base: Path | None = None, *, autostart: bool = False):
        self._base = Path(base) if base is not None else None
        self.autostart = autostart
        self._lock = threading.Lock()
        self._spawn_lock = threading.Lock()
        self._spawned: list = []  # Popen handles kept so they are never GC-warned
        self._last_spawn = 0.0
        self._sessions: dict[str, NativeAttachment] = {}
        self._pane_locks: dict[str, threading.Lock] = {}

    # ---- plumbing ----

    def socket_path(self) -> Path:
        return _d.socket_path(self._base or cfg.state_dir())

    def _rpc(self, op: str, timeout: float = 2.0, **fields) -> dict:
        try:
            return _d.rpc(op, path=self.socket_path(), timeout=timeout, **fields)
        except (FileNotFoundError, ConnectionRefusedError):
            if not self.ensure_daemon():
                raise
            return _d.rpc(op, path=self.socket_path(), timeout=timeout, **fields)

    def ensure_daemon(self, wait: float = 3.0) -> bool:
        """Spawn ``vbear runtimed`` if autostart is on and nobody answers.

        The daemon runs in its own session and is *not* stopped when the
        server exits (user decision §9.2). Spawns are rate-limited; a second
        concurrent daemon exits on its own via the flock (S0)."""
        if not self.autostart:
            return False
        import os
        import subprocess
        import sys
        import time
        with self._spawn_lock:
            try:
                return bool(_d.rpc("hello", path=self.socket_path(), timeout=0.5).get("ok"))
            except (OSError, ValueError):
                pass
            now = time.monotonic()
            if now - self._last_spawn < 5.0:
                return False
            self._last_spawn = now
            base = self._base or cfg.state_dir()
            os.makedirs(base, mode=0o700, exist_ok=True)
            env = dict(os.environ)
            env["VBEAR_HOME"] = str(base)
            log_fd = os.open(base / "runtimed.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "vbear", "runtimed"],
                    cwd=str(Path(__file__).resolve().parent.parent.parent), env=env,
                    stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
                    start_new_session=True)
            finally:
                os.close(log_fd)
            self._spawned.append(proc)
            end = time.monotonic() + wait
            while time.monotonic() < end:
                try:
                    if _d.rpc("hello", path=self.socket_path(), timeout=0.5).get("ok"):
                        return True
                except (OSError, ValueError):
                    pass
                if proc.poll() is not None:
                    return False
                time.sleep(0.1)
            return False

    def create_session(self, spec) -> dict:
        """Open a terminal without attaching (API use: the browser attaches
        later through the normal stream). Returns the daemon's session info."""
        if not isinstance(spec, dict):
            raise NativeRuntimeError("spec 必須是物件")
        fields = {k: spec[k] for k in ("argv", "cwd", "cols", "rows", "env", "kind") if k in spec}
        try:
            r = self._rpc("open", timeout=5.0, **fields)
        except (OSError, ValueError) as exc:
            raise NativeRuntimeUnavailable(f"VBear runtime 無法連線：{exc}") from exc
        if not r.get("ok"):
            err = r.get("error") or {}
            raise NativeRuntimeError(str(err.get("message") or "無法開啟"))
        return r["result"]

    def create_checked_agent_session(self, engine: str, spec: dict) -> dict:
        """Internal, version-checked Agent launch; not a Profile security gate.

        This entry is deliberately not connected to the raw HTTP session API.
        It checks the selected CLI before any daemon RPC/autostart, pins argv[0]
        to the checked canonical path, and rechecks file identity immediately
        before opening the PTY. The final path check and exec are not atomic,
        so this does not claim to eliminate the filesystem TOCTOU window.
        A successful result means version-checked/unmanaged only; it does not
        confirm a preview or establish sandbox/Profile protection.
        """
        if not isinstance(engine, str) or engine not in _cli_versions.EXPECTED_VERSIONS:
            raise _cli_versions.VersionAssertionError(
                _cli_versions.check_cli_version(engine, cwd="/"))
        if not isinstance(spec, dict) or set(spec) - {"argv", "cwd", "cols", "rows"}:
            raise NativeRuntimeError("checked Agent spec 欄位無效")
        for dim in ("cols", "rows"):
            if dim in spec:
                value = spec[dim]
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
                    raise NativeRuntimeError(f"checked Agent {dim} 必須是 1–1000 的整數")
        argv = spec.get("argv")
        cwd = spec.get("cwd")
        if not isinstance(argv, list) or not 1 <= len(argv) <= 256 or any(
                not isinstance(arg, str) or "\0" in arg or len(arg) > 4096 for arg in argv):
            raise NativeRuntimeError("checked Agent argv 必須是非空字串陣列")
        if not argv[0] or Path(argv[0]).name != engine:
            raise NativeRuntimeError("checked Agent argv[0] 必須是指定引擎的 CLI")
        if (not isinstance(cwd, str) or "\0" in cwd
                or not os.path.isabs(cwd) or not os.path.isdir(cwd)):
            raise NativeRuntimeError("checked Agent cwd 必須是既存的絕對路徑資料夾")

        # No client baseline parameter exists: the guard reads trusted module
        # constants and uses only the engine-specific fixed version argv.
        canonical_cwd = os.path.realpath(cwd)
        assertion = _cli_versions.assert_cli_version(engine, argv[0], cwd=canonical_cwd)
        _cli_versions.ensure_binary_unchanged(assertion)

        checked_spec = dict(spec)
        checked_spec["argv"] = [assertion.binary_path, *argv[1:]]
        checked_spec["cwd"] = canonical_cwd
        session = self.create_session(checked_spec)
        return {
            "session": session,
            "version_assertion": assertion.as_dict(),
            "state": "version_checked_unmanaged",
        }

    def prepare_managed_claude_launch(self, spec: dict, *, allowed_root: str | None = None) -> dict:
        """Step 1 of a managed Claude launch (R3 S2/S0): check the CLI version
        and create the per-session settings, scratch and manifest. Starts
        nothing. The result feeds a preview and, later, ``launch_prepared_claude``.

        Only ``cwd`` and an optional validated ``model_id`` are accepted. The
        CLI must be the verified baseline version; the pinned install path is
        preferred so a newer default ``claude`` on PATH is never used by accident.
        """
        if not isinstance(spec, dict) or set(spec) - {"cwd", "model_id"}:
            raise NativeRuntimeError("managed Agent spec 欄位無效")
        cwd = spec.get("cwd")
        if (not isinstance(cwd, str) or "\0" in cwd
                or not os.path.isabs(cwd) or not os.path.isdir(cwd)):
            raise NativeRuntimeError("managed Agent cwd 必須是既存的絕對路徑資料夾")
        canonical_cwd = os.path.realpath(cwd)
        # A genuine but unverified Claude Code release is allowed; the manifest
        # records it so every label says "unverified" and launching needs an
        # explicit acknowledgement.
        assertion = _cli_versions.assert_cli_version(
            "claude", _pinned_claude_binary(), cwd=canonical_cwd, allow_unverified=True)
        base = self._base or cfg.state_dir()
        manifest = _agent_sessions.prepare_claude_launch(
            base, canonical_cwd, cli_binary=assertion.binary_path,
            cli_version=assertion.observed_version,
            cli_identity=list(assertion._binary_identity), allowed_root=allowed_root,
            model_id=spec.get("model_id") or None, cli_verified=assertion.verified)
        return {"manifest": manifest, "assertion": assertion}

    def prepare_managed_codex_launch(self, spec: dict, *, allowed_root: str | None = None) -> dict:
        """Prepare Codex 0.159.2 with its user config/rules and session persistence disabled.

        The real HOME remains so the CLI can use its existing login. The runtime
        neither reads nor copies auth material and does not set CODEX_HOME.
        """
        if not _cli_versions.CODEX_INTERACTIVE_FLAGS_SUPPORTED:
            raise NativeRuntimeError(
                "固定版 Codex CLI 不支援在互動 TUI 同時使用 ignore-user-config/ephemeral；拒絕受管啟動")
        if not isinstance(spec, dict) or set(spec) - {"cwd", "model_id", "commit", "read_only"}:
            raise NativeRuntimeError("managed Agent spec 欄位無效")
        cwd = spec.get("cwd")
        if (not isinstance(cwd, str) or "\0" in cwd
                or not os.path.isabs(cwd) or not os.path.isdir(cwd)):
            raise NativeRuntimeError("managed Agent cwd 必須是既存的絕對路徑資料夾")
        canonical_cwd = os.path.realpath(cwd)
        assertion = _cli_versions.assert_cli_version(
            "codex", _pinned_codex_binary(), cwd=canonical_cwd)
        base = self._base or cfg.state_dir()
        manifest = _agent_sessions.prepare_codex_launch(
            base, canonical_cwd, cli_binary=assertion.binary_path,
            cli_version=assertion.observed_version,
            cli_identity=list(assertion._binary_identity), allowed_root=allowed_root,
            model_id=spec.get("model_id") or None,
            commit=spec.get("commit", True), read_only=spec.get("read_only", False))
        return {"manifest": manifest, "assertion": assertion}

    def discard_prepared_claude_launch(self, launch_id: str) -> dict:
        """Remove a prepared launch that will not be started (expired preview)."""
        return _agent_sessions.discard_prepared(self._base or cfg.state_dir(), launch_id)

    def discard_prepared_agent_launch(self, launch_id: str) -> dict:
        """Shared Claude/Codex prepared-launch cleanup lifecycle."""
        return self.discard_prepared_claude_launch(launch_id)

    def launch_prepared_agent(self, prepared: dict, *, cols: int | None = None,
                              rows: int | None = None, unverified_acknowledged: bool = False) -> dict:
        """Step 2: hand a prepared launch to the daemon. The daemon re-validates
        the manifest, settings, paths and CLI file and builds argv and
        environment itself. Every failed precondition refuses the launch;
        nothing falls back to an unmanaged or looser session.

        The daemon validates the same engine-specific settings used at preview.
        A user typing in the advanced terminal can still change CLI behavior;
        the caller must keep that bypass explicit in its labels.
        """
        manifest, assertion = prepared["manifest"], prepared["assertion"]
        base = self._base or cfg.state_dir()
        if manifest.get("cli_verified") is False:
            if unverified_acknowledged is not True:
                _agent_sessions.discard_prepared(base, manifest["launch_id"])
                raise _cli_versions.VersionAssertionError(_cli_versions._blocked(
                    "claude", "unverified_not_acknowledged",
                    f"Claude Code {manifest.get('cli_version')} 尚未驗證，需要使用者明確知悉才能啟動",
                    observed=manifest.get("cli_version"), binary_path=manifest.get("cli_binary")))
            # Recorded in the state directory, where the daemon (which decides on
            # its own whether the version is verified) looks for it.
            _agent_sessions.update_manifest(base, manifest["launch_id"], unverified_acknowledged=True,
                                            unverified_acknowledged_at=time.time())
        dims = {}
        for dim, value in (("cols", cols), ("rows", rows)):
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
                    raise NativeRuntimeError(f"managed Agent {dim} 必須是 1–1000 的整數")
                dims[dim] = value
        launch_id = manifest["launch_id"]
        try:
            _cli_versions.ensure_binary_unchanged(assertion)
            r = self._rpc("open_managed", timeout=5.0, launch_id=launch_id, **dims)
        except _cli_versions.VersionAssertionError:
            _agent_sessions.discard_prepared(base, launch_id)  # nothing was sent to a daemon
            raise
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            # No daemon answered, so no process can exist for this launch.
            _agent_sessions.discard_prepared(base, launch_id)
            raise NativeRuntimeUnavailable(f"VBear runtime 未啟動或無法連線：{exc}") from exc
        except (OSError, ValueError) as exc:
            # Outcome unknown (e.g. timeout): the daemon may own a session. Keep the state.
            raise NativeRuntimeUnavailable(f"VBear runtime 無法連線：{exc}") from exc
        if not r.get("ok"):
            # Refused before anything started (the daemon removes its own state
            # when a spawn fails); a still-prepared launch is ours to remove.
            _agent_sessions.discard_prepared(base, launch_id)
            err = r.get("error") or {}
            raise NativeRuntimeError(str(err.get("message") or "無法開啟"))
        return {
            "session": r["result"],
            "launch_id": launch_id,
            "version_assertion": assertion.as_dict(),
            "boundary": manifest["boundary"],
            "state": "profile_managed",
        }

    def launch_prepared_claude(self, prepared: dict, *, cols: int | None = None,
                               rows: int | None = None, unverified_acknowledged: bool = False) -> dict:
        """Compatibility wrapper for existing Claude callers."""
        return self.launch_prepared_agent(prepared, cols=cols, rows=rows,
                                          unverified_acknowledged=unverified_acknowledged)

    def create_managed_claude_session(self, spec: dict, *, allowed_root: str | None = None) -> dict:
        """Internal one-shot form of prepare + launch (no preview). Not on the HTTP API."""
        if not isinstance(spec, dict) or set(spec) - {"cwd", "cols", "rows", "model_id"}:
            raise NativeRuntimeError("managed Agent spec 欄位無效")
        for dim in ("cols", "rows"):
            if dim in spec:
                value = spec[dim]
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
                    raise NativeRuntimeError(f"managed Agent {dim} 必須是 1–1000 的整數")
        prepared = self.prepare_managed_claude_launch(
            {k: spec[k] for k in ("cwd", "model_id") if k in spec}, allowed_root=allowed_root)
        assertion = prepared["assertion"]
        if not assertion.verified:
            # Unverified versions start only through a preview the user acknowledged.
            self.discard_prepared_claude_launch(prepared["manifest"]["launch_id"])
            raise _cli_versions.VersionAssertionError(_cli_versions._blocked(
                "claude", "version_mismatch", "Agent CLI 版本不在已驗證的版本清單",
                expected=assertion.expected_version, observed=assertion.observed_version,
                binary_path=assertion.binary_path))
        return self.launch_prepared_claude(prepared, cols=spec.get("cols"), rows=spec.get("rows"))

    def create_managed_codex_session(self, spec: dict, *, allowed_root: str | None = None) -> dict:
        """Internal one-shot Codex form; preview APIs use prepare/launch separately."""
        if not isinstance(spec, dict) or set(spec) - {"cwd", "cols", "rows", "model_id", "commit", "read_only"}:
            raise NativeRuntimeError("managed Agent spec 欄位無效")
        prepared = self.prepare_managed_codex_launch(
            {k: spec[k] for k in ("cwd", "model_id", "commit", "read_only") if k in spec},
            allowed_root=allowed_root)
        return self.launch_prepared_agent(prepared, cols=spec.get("cols"), rows=spec.get("rows"))

    def _pane_lock(self, sid: str) -> threading.Lock:
        with self._lock:
            return self._pane_locks.setdefault(sid, threading.Lock())

    def _purge_locked(self) -> None:
        for sid in [k for k, v in self._sessions.items() if v.closed]:
            self._sessions.pop(sid, None)

    def _attach(self, sid: str, mode: str, cols: int, rows: int) -> NativeAttachment | None:
        if self.autostart and not self.socket_path().exists():
            self.ensure_daemon()
        try:
            sock, res, left = attach_socket(self.socket_path(), sid, mode, cols, rows)
        except AttachRefused as exc:
            return NativeAttachment(sid, mode, cols, rows,
                                    fail_reason=f"terminal attach failed: {exc}")
        except (OSError, ValueError):
            return None
        return NativeAttachment(sid, res.get("mode", mode), res.get("cols", cols),
                                res.get("rows", rows), sock=sock,
                                attachment_id=res.get("attachment_id"), leftover=left)

    # ---- identification ----

    def describe(self) -> dict:
        try:
            r = self._rpc("hello", timeout=1.0)
        except (OSError, ValueError):
            return {"name": "native", "version": None, "binary": str(self.socket_path()),
                    "available": False, "problems": ["VBear runtime 背景程序沒有在執行"]}
        res = r.get("result") or {}
        return {"name": "native", "version": res.get("version"),
                "binary": str(self.socket_path()), "available": bool(r.get("ok")),
                "problems": [] if r.get("ok") else ["VBear runtime 回應異常"]}

    def binary(self) -> str | None:
        return str(self.socket_path())  # path only; no round trip (/api/config)

    def is_available(self) -> bool:
        try:
            return bool(self._rpc("hello", timeout=1.0).get("ok"))
        except (OSError, ValueError):
            return False

    # ---- read-only ----

    def list_sessions(self) -> dict:
        info = self.describe()
        snap = {"available": info["available"], "binary": info["binary"],
                "version": info["version"], "problems": list(info["problems"]),
                "workspaces": [{"workspace_id": WORKSPACE_ID, "label": "本機 Terminal"}],
                "tabs": [], "agents": [], "panes": []}
        if not info["available"]:
            return snap
        try:
            r = self._rpc("list")
        except (OSError, ValueError):
            snap["available"] = False
            snap["problems"].append("無法讀取 session 清單")
            return snap
        for s in (r.get("result") or {}).get("sessions") or ():
            argv = s.get("argv") or []
            engine = _agent_engine(s)
            if engine:
                # Claude / Codex sessions are the console's working Agents. Their
                # working/idle state is not detectable from a PTY, so it is unknown.
                snap["agents"].append({
                    "terminal_id": s["session_id"], "pane_id": s["session_id"],
                    "workspace_id": WORKSPACE_ID, "tab_id": "", "agent": engine,
                    "agent_status": "exited" if s.get("exited") else "unknown",
                    "name": "", "cwd": s.get("cwd"), "foreground_cwd": s.get("cwd"),
                    "terminal_title_stripped": engine, "focused": False,
                    "managed": s.get("managed"), "agent_session": {}})
            snap["panes"].append({
                "pane_id": s["session_id"], "terminal_id": s["session_id"],
                "workspace_id": WORKSPACE_ID,
                "title": Path(argv[0]).name if argv else s["session_id"],
                "cwd": s.get("cwd"), "command": argv, "pid": s.get("pid"),
                "terminal_title_stripped": Path(argv[0]).name if argv else "",
                "agent": engine, "agent_status": "exited" if s.get("exited") else "unknown",
                "exited": bool(s.get("exited")), "exit_code": s.get("exit_code"),
                "cols": s.get("cols"), "rows": s.get("rows"), "kind": s.get("kind")})
        return snap

    def snapshot(self) -> dict:
        return self.list_sessions()

    def validate_target(self, target: str) -> bool:
        return isinstance(target, str) and bool(SESSION_RE.match(target))

    def status(self, session_id: str) -> str:
        if not self.validate_target(session_id):
            return "unknown"
        for p in self.list_sessions()["panes"]:
            if p["pane_id"] == session_id:
                return "exited" if p["exited"] else "unknown"  # R2 does not guess idle/working
        return "unknown"

    # ---- session lifecycle ----

    def open_session(self, spec) -> SessionView:
        info = self.create_session(spec)
        sid = info["session_id"]
        view = self.observe(sid, int(info.get("cols", 80)), int(info.get("rows", 24)))
        if view is None:
            raise NativeRuntimeError("session 已開啟，但目前無法連線觀看")
        return view

    def close(self, session_id: str) -> bool:
        return self.close_session(session_id) is not None

    def close_session(self, session_id: str) -> dict | None:
        """Close and return the daemon's result (including, for a managed
        session, whether its scratch and settings were cleaned), or None."""
        if not self.validate_target(session_id):
            return None
        try:
            r = self._rpc("close", timeout=_d.CLOSE_WAIT + 2, session_id=session_id)
        except (OSError, ValueError):
            return None
        # The view receives terminal.closed from the daemon; the SSE loop
        # delivers it and then calls close_if_current.
        return r.get("result") or {} if r.get("ok") else None

    def observe(self, session_id: str, cols: int = 80, rows: int = 24) -> SessionView | None:
        if not self.validate_target(session_id):
            return None
        with self._pane_lock(session_id):
            with self._lock:
                self._purge_locked()
                existing = self._sessions.get(session_id)
                if existing is not None:
                    return existing
                if len(self._sessions) >= MAX_CONCURRENT_PANES:
                    return None
            view = self._attach(session_id, "observe", cols, rows)
            if view is None:
                return None
            with self._lock:
                self._sessions[session_id] = view
            return view

    def control(self, session_id: str, cols: int = 80, rows: int = 24) -> SessionView | None:
        if not self.validate_target(session_id):
            return None
        with self._pane_lock(session_id):  # serialised: daemon order == install order
            with self._lock:
                self._purge_locked()
                old = self._sessions.get(session_id)
            new = self._attach(session_id, "control", cols, rows)
            if new is None:
                return None
            with self._lock:
                self._sessions[session_id] = new
            if old is not None:
                old.stop()  # already demoted by the daemon (control_lost)
            return new

    def release(self, session_id: str) -> SessionView | None:
        with self._pane_lock(session_id):
            with self._lock:
                self._purge_locked()
                old = self._sessions.get(session_id)
            if old is None:
                return None
            new = self._attach(session_id, "observe", old.cols, old.rows)
            if new is None or new.closed:
                with self._lock:
                    if self._sessions.get(session_id) is old:
                        self._sessions.pop(session_id, None)
                if new is not None:
                    new.stop()
                old.release_and_stop()
                return None
            with self._lock:
                if self._sessions.get(session_id) is not old:
                    new.stop()
                    return self._sessions.get(session_id)
                self._sessions[session_id] = new
            old.release_and_stop()
            return new

    def abandon(self, session_id: str, token: str | None = None) -> bool:
        with self._lock:
            self._purge_locked()
            cur = self._sessions.get(session_id)
            if cur is None or (token is not None and cur.token != token):
                return False
            self._sessions.pop(session_id, None)
        cur.release_and_stop()
        return True

    def close_if_current(self, session_id: str, expected: SessionView) -> None:
        with self._lock:
            if self._sessions.get(session_id) is not expected:
                return
            self._sessions.pop(session_id, None)
        expected.release_and_stop()

    def send_input(self, session_id: str, data: bytes) -> bool:
        view = self.get(session_id)
        return bool(view) and view.mode == "control" and view.send_input(data)

    def resize(self, session_id: str, cols: int, rows: int) -> bool:
        view = self.get(session_id)
        return bool(view) and view.mode == "control" and view.resize(cols, rows)

    def get(self, session_id: str) -> SessionView | None:
        with self._lock:
            return self._sessions.get(session_id)

    def close_all(self) -> None:
        """Drop this server's attachments only; terminals keep running (R-D4)."""
        with self._lock:
            views = list(self._sessions.values())
            self._sessions.clear()
        for v in views:
            v.release_and_stop()


__all__ = ["AttachRefused", "NativeAttachment", "NativeRuntime", "NativeRuntimeError",
           "NativeRuntimeUnavailable",
           "attach_socket"]
