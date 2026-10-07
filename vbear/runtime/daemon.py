"""VBear native runtime daemon (Phase R2, contract v2).

S0: secure state directory, single-instance lock, stale-socket recovery,
owner-only Unix socket, peer-uid check, RPC ``hello`` / ``shutdown``.
S1: PTY sessions — ``open`` / ``list`` / ``close``, natural-exit reaping,
event-driven HUP -> TERM -> KILL close, scrollback ring, limits.
S2: attach connections (contract v2 §1, §2B, §10 S2): an RPC connection
whose first request is ``attach`` becomes a long-lived stream. Daemon ->
client carries only frames (``terminal.frame`` / ``control_lost`` /
``error`` / ``closed``); client -> daemon carries only fire-and-forget
``terminal.input`` / ``resize`` / ``release``. Control is bound to the
attach connection: a new control attach demotes the previous holder, and a
dropped connection releases control at once. Per-attachment output is
bounded; on overflow the queue is discarded and exactly one full replay
(<= 64 KiB, UTF-8 aligned) is produced once the socket drains again. An
attachment whose writes make no progress for WRITE_STALL seconds is dropped.

Startup order (contract v2 §3):
  1. umask 077; state dir must be owned by us, 0700, not a symlink.
  2. ``runtimed.lock`` flock(LOCK_EX|LOCK_NB), held for the daemon's life.
     Failing to get it means another daemon is running: exit, never touch
     its socket. This is what makes step 3 safe against concurrent starts.
  3. With the lock held, an existing ``runtime.sock`` is removed only if it
     is a socket owned by us; symlinks / regular files are refused.
  4. bind, chmod 0600, and check every accepted peer's uid
     (Darwin LOCAL_PEERCRED / struct xucred). Failure to read it closes the
     connection (fail closed); 0700 dir + 0600 socket stay the main defence.

RPC connection (contract v2 §2A): one newline-terminated JSON request
(<= 64 KiB), one response, then the daemon closes the connection. ``close``
answers only once the session is fully gone (deferred reply).

Process model (contract v2 §4, §10 S1):
  * Children are spawned with ``subprocess`` (start_new_session=True) via
    the ``_ptyexec`` trampoline, never ``os.fork`` from this possibly
    threaded process. The leader's pid is the process-group id.
  * Reaping polls each session leader (``Popen.poll``) on every loop turn;
    we deliberately do not ``waitpid(-1)`` so an embedding process's other
    children are never stolen. SIGCHLD (installed by ``main``) only wakes
    the loop so natural exits are noticed promptly.
  * ``close`` is a state machine advanced by the loop: HUP (1s) -> TERM (2s)
    -> KILL (1s). The master keeps being drained throughout, so a child
    writing on its way out never blocks on a full PTY; other sessions keep
    streaming. Signals and reaping come first; the master closes last.
  * Known limit: a descendant that calls setsid() itself leaves our process
    group and is not reached by killpg.

R3 managed Claude/Codex sessions (``open_managed``): the daemon itself builds
argv and environment from a validated launch manifest (``agent_sessions``);
callers supply only a launch id and a size. Agent tool commands can run in
their own process groups, so managed sessions also track observed
descendants (``proctrack``): closing signals the verified descendant groups
too, and the session's scratch and settings are deleted only when the leader
and every observed descendant are proven gone. Otherwise they are retained
and marked for manual review. Plain ``open`` sessions are unchanged.
"""

from __future__ import annotations

import base64
import binascii
import errno
import json
import os
import re
import secrets
import selectors
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Callable

from .. import config as cfg
from . import agent_sessions, osc_title, proctrack

PROTOCOL_VERSION = 1
DAEMON_VERSION = "native-r2-s3"  # s3: activity evidence in session info
MAX_LINE = 64 * 1024
SUN_PATH_MAX = 103  # macOS sockaddr_un.sun_path is 104 bytes incl. NUL
SOCKET_NAME = "runtime.sock"
LOCK_NAME = "runtimed.lock"
DEFAULT_IDLE_TIMEOUT = 5.0

SCROLLBACK_MAX = 1 << 20  # 1 MiB ring per session (contract v2 §6)
MAX_SESSIONS = 16
HUP_GRACE = 1.0
TERM_GRACE = 2.0
KILL_GRACE = 1.0
CLOSE_WAIT = HUP_GRACE + TERM_GRACE + KILL_GRACE + 4.0  # deferred-reply deadline
ENV_ALLOW = ("PATH", "TERM", "LANG", "HOME")  # caller may override these
# Inherited but never caller-overridable: identity of the daemon's own user.
# Claude Code looks up its Keychain login by USER; without it the CLI reports
# "Login expired" (Gate 9 finding).
ENV_IDENTITY = ("USER", "LOGNAME")
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
SESSION_RE = re.compile(r"^n-[0-9a-f]{12}$")
MAX_ATTACHMENTS = 4           # per session (contract v2 §6)
ATTACH_QUEUE_MAX = 256        # frames queued per attachment before resync
ATTACH_QUEUE_BYTES = 4 << 20  # ... or this many encoded bytes
FULL_REPLAY_MAX = 64 * 1024   # full-frame replay cap incl. the reset (§10 S2)
WRITE_STALL = 10.0            # seconds without write progress -> drop
INPUT_MAX = 16 * 1024         # decoded bytes per terminal.input
MANAGED_OBSERVE = 0.5         # seconds between process-table looks (managed sessions)
MANAGED_OBSERVE_CLOSING = 0.2  # ... while a managed session is being closed
PREPARED_SWEEP = 60.0         # seconds between sweeps of abandoned prepared launches
RIS = b"\x1bc"                # full reset: a full frame replaces the screen
PTYEXEC = str(Path(__file__).with_name("_ptyexec.py"))

# Darwin: SOL_LOCAL = 0, LOCAL_PEERCRED = 1 (sys/un.h). Python does not
# export them on macOS, hence the explicit fallbacks.
SOL_LOCAL = 0
LOCAL_PEERCRED = getattr(socket, "LOCAL_PEERCRED", 1)
XUCRED_VERSION = 0
# struct xucred { u_int cr_version; uid_t cr_uid; short cr_ngroups;
#                 gid_t cr_groups[16]; }  -> 4 + 4 + 2 (+2 pad) + 64 = 76
XUCRED_SIZE = 76

ENVELOPE = frozenset({"v", "id", "op"})
RPC_OPS: dict[str, frozenset] = {
    "hello": frozenset(),
    "shutdown": frozenset({"force"}),
    "open": frozenset({"argv", "cwd", "cols", "rows", "env", "kind"}),
    "open_managed": frozenset({"launch_id", "cols", "rows"}),
    "list": frozenset(),
    "close": frozenset({"session_id"}),
    "attach": frozenset({"session_id", "mode", "cols", "rows"}),
}
_ATTACHED = object()  # _dispatch result: the connection became an attachment


class RuntimedError(Exception):
    """Daemon cannot start safely; message is user-facing Chinese."""


class AlreadyRunning(RuntimedError):
    pass


class UnsafePath(RuntimedError):
    pass


def socket_path(base: Path | None = None) -> Path:
    return Path(base or cfg.state_dir()) / SOCKET_NAME


def lock_path(base: Path | None = None) -> Path:
    return Path(base or cfg.state_dir()) / LOCK_NAME


# --- peer credentials -------------------------------------------------------

def parse_xucred(raw: bytes) -> int:
    """uid from a Darwin ``struct xucred``; ValueError on anything odd."""
    if len(raw) < 8:
        raise ValueError("xucred too short")
    version, uid = struct.unpack_from("=II", raw, 0)
    if version != XUCRED_VERSION:
        raise ValueError(f"unexpected xucred version {version}")
    return uid


def peer_uid(conn: socket.socket) -> int:
    if sys.platform == "darwin":
        return parse_xucred(conn.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, XUCRED_SIZE))
    if hasattr(socket, "SO_PEERCRED"):  # Linux dev boxes only; R2 targets macOS
        _pid, uid, _gid = struct.unpack("3i", conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        return uid
    raise OSError("no peer credential mechanism on this platform")


# --- filesystem safety ------------------------------------------------------

def _secure_dir(path: Path, uid: int) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise UnsafePath(f"狀態目錄不是一般資料夾：{path}")
    if st.st_uid != uid:
        raise UnsafePath(f"狀態目錄不屬於目前使用者：{path}")
    if st.st_mode & 0o077:
        raise UnsafePath(f"狀態目錄權限必須是 0700（目前 {oct(st.st_mode & 0o777)}）：{path}")


def _acquire_lock(path: Path, uid: int) -> int:
    import fcntl
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        raise UnsafePath(f"無法安全開啟鎖檔（可能是 symlink）：{path}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != uid:
            raise UnsafePath(f"鎖檔不是本人擁有的一般檔案：{path}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning("已有 VBear runtime 背景程序在執行") from exc
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        return fd
    except BaseException:
        os.close(fd)
        raise


def _clear_stale_socket(path: Path, uid: int) -> None:
    """Only ever called while holding the lock (contract v2 §3 step 3)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != uid:
        raise UnsafePath(f"socket 路徑被非本人 socket 佔用（symlink／一般檔案）：{path}")
    os.unlink(path)


# --- PTY helpers ------------------------------------------------------------

def _set_winsize(fd: int, rows: int, cols: int) -> None:
    import fcntl
    import termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def build_env(overrides: dict | None = None) -> dict:
    """Child environment: PATH/TERM/LANG/HOME (contract v2 §5) plus the
    daemon user's USER/LOGNAME, which callers cannot override.

    PATH gets the usual Homebrew/system dirs appended when missing, because a
    daemon started from Finder / an .app does not inherit the login shell
    PATH. Existing entries keep their order."""
    env = {k: os.environ[k] for k in ENV_ALLOW if os.environ.get(k)}
    env.update({k: v for k, v in (overrides or {}).items() if k in ENV_ALLOW})
    try:
        import pwd
        name = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        name = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if name:
        for k in ENV_IDENTITY:
            env[k] = name
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("LANG", "en_US.UTF-8")
    env.setdefault("HOME", str(Path.home()))
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    for extra in EXTRA_PATH:
        if extra not in parts:
            parts.append(extra)
    env["PATH"] = os.pathsep.join(parts)
    return env


def _resolve(cmd: str, cwd: str, path: str) -> str | None:
    if "/" in cmd:
        full = cmd if os.path.isabs(cmd) else os.path.join(cwd, cmd)
        return full if os.path.isfile(full) and os.access(full, os.X_OK) else None
    return shutil.which(cmd, path=path)


class Session:
    """One PTY + process group owned by the daemon (the v2 "Session" layer)."""

    def __init__(self, sid: str, proc: subprocess.Popen, master: int, argv: list,
                 cwd: str, cols: int, rows: int):
        self.sid = sid
        self.proc = proc
        self.pid = proc.pid
        self.pgid = proc.pid  # start_new_session: leader pid == pgid
        self.master = master
        self.argv = argv
        self.cwd = cwd
        self.cols = cols
        self.rows = rows
        self.started = time.time()
        self.scrollback = bytearray()
        self.total = 0
        self.eof = False
        self.registered = False
        self.exit_code: int | None = None
        self.phase: str | None = None  # None | "hup" | "term" | "kill"
        self.deadline = 0.0
        self.forced = False
        self.waiters: list = []
        self.seq = 0
        self.attachments: list = []
        self.control = None  # the Attachment holding control, if any
        self.exit_notified = False
        self.exit_reason = ""
        # Managed (R3 S2) sessions only; all stay inert for plain sessions.
        self.launch_id: str | None = None
        self.engine: str | None = None      # "claude" / "codex" for a managed session
        self.kind: str | None = None        # "shell" for a user-opened login shell (label only)
        self.tracker: proctrack.DescendantTracker | None = None
        self.extra_groups: list[int] = []   # verified descendant groups, from the last look
        self.extra_alive = False            # an observed descendant outside our group still exists
        # True when the *latest* look could not vouch for every descendant: the
        # process table was unreadable, or a descendant cannot be verified. It is
        # deliberately not sticky: cleanup is decided on a fresh forced look, and
        # an earlier transient failure says nothing about what exists now.
        self.unproven = False
        self.missed_looks = 0               # how often the table was unreadable (logged at cleanup)
        self.next_observe = 0.0
        self.cli_version: str | None = None  # managed only: the version the launch was checked against
        # Managed Claude only: the class of the latest terminal title (never its text).
        self.titles: osc_title.TitleTracker | None = None

    def poll(self) -> int | None:
        if self.exit_code is None:
            rc = self.proc.poll()
            if rc is not None:
                self.exit_code = rc
        return self.exit_code

    def group_alive(self) -> bool:
        return self.leader_group_alive() or self.extra_alive

    def leader_group_alive(self) -> bool:
        if self.pgid <= 1 or self.pgid == os.getpgrp():
            return False  # symmetric with signal(): never probe ourselves/init
        try:
            os.killpg(self.pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def signal(self, sig: int) -> None:
        # Never signal ourselves or init, whatever the bookkeeping says.
        if self.pgid <= 1 or self.pgid == os.getpgrp():
            return
        try:
            os.killpg(self.pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        for pgid in self.extra_groups:  # managed only; refreshed right before signalling
            if pgid <= 1 or pgid == os.getpgrp() or pgid == self.pgid:
                continue
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    def append(self, data: bytes) -> None:
        self.total += len(data)
        self.scrollback += data
        over = len(self.scrollback) - SCROLLBACK_MAX
        if over > 0:
            del self.scrollback[:over]

    def info(self) -> dict:
        return {"session_id": self.sid, "pid": self.pid, "pgid": self.pgid,
                "argv": list(self.argv), "cwd": self.cwd,
                "cols": self.cols, "rows": self.rows, "started": self.started,
                "exited": self.exit_code is not None, "exit_code": self.exit_code,
                "closing": self.phase is not None, "output_bytes": self.total,
                "attachments": len(self.attachments),
                "control_attachment": self.control.aid if self.control else None,
                "managed": self.launch_id, "engine": self.engine, "kind": self.kind,
                "cli_version": self.cli_version,
                "activity_evidence": ({"claude_title": self.titles.snapshot()}
                                      if self.titles is not None else None)}


class Attachment:
    """One attach connection (the v2 "Attachment" layer == R1 SessionView)."""

    __slots__ = ("sock", "sess", "aid", "mode", "out", "out_bytes", "cur", "inbuf",
                 "closing", "resync", "writing", "last_progress")

    def __init__(self, sock: socket.socket, sess: Session, mode: str):
        self.sock = sock
        self.sess = sess
        self.aid = "a-" + secrets.token_hex(6)
        self.mode = mode
        self.out: deque = deque()
        self.out_bytes = 0
        self.cur = bytearray()
        self.inbuf = bytearray()
        self.closing = False
        self.resync = False
        self.writing = False
        self.last_progress = time.monotonic()


def _line(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"


def _frame(s: Session, data: bytes, full: bool) -> dict:
    return {"type": "terminal.frame", "bytes": base64.b64encode(data).decode("ascii"),
            "encoding": "ansi", "full": full, "seq": s.seq,
            "width": s.cols, "height": s.rows}


def replay_bytes(scrollback: bytes | bytearray) -> bytes:
    """Reset + the scrollback tail, <= FULL_REPLAY_MAX, never starting inside
    a UTF-8 sequence."""
    buf = scrollback[-(FULL_REPLAY_MAX - len(RIS)):]
    start = 0
    while start < len(buf) and start < 4 and (buf[start] & 0xC0) == 0x80:
        start += 1
    return RIS + bytes(buf[start:])


# --- responses --------------------------------------------------------------

def _ok(rid, result) -> dict:
    return {"v": PROTOCOL_VERSION, "id": rid, "ok": True, "result": result}


def _err(rid, code: str, message: str) -> dict:
    return {"v": PROTOCOL_VERSION, "id": rid, "ok": False,
            "error": {"code": code, "message": message}}


def _int_in(value, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


class _Conn:
    __slots__ = ("sock", "buf", "out", "deadline", "stop_after", "rid", "waiting")

    def __init__(self, sock: socket.socket, deadline: float):
        self.sock = sock
        self.buf = bytearray()
        self.out = bytearray()
        self.deadline = deadline
        self.stop_after = False
        self.rid = None
        self.waiting = False


class Daemon:
    """Single-threaded selectors loop. ``stop()`` / ``wake()`` are the only
    thread-safe entry points (they only set a flag and poke the wake pipe)."""

    def __init__(self, base: Path | None = None, *, expected_uid: int | None = None,
                 idle_timeout: float = DEFAULT_IDLE_TIMEOUT,  # total per-RPC deadline
                 max_sessions: int = MAX_SESSIONS,
                 log: Callable[[str], None] | None = None):
        self.base = Path(base or cfg.state_dir())
        self.sock_path = socket_path(self.base)
        self.lock_path = lock_path(self.base)
        self.uid = os.getuid() if expected_uid is None else expected_uid
        self.idle_timeout = idle_timeout
        self.max_sessions = max_sessions
        self._log = log or (lambda m: print(f"[runtimed] {m}", file=sys.stderr, flush=True))
        self._lock_fd: int | None = None
        self._listener: socket.socket | None = None
        self._sock_id: tuple[int, int] | None = None
        self._sel: selectors.BaseSelector | None = None
        self._wake_r = self._wake_w = -1
        self._conns: dict[socket.socket, _Conn] = {}
        self._sessions: dict[str, Session] = {}
        self._attachments: dict[socket.socket, Attachment] = {}
        self.max_attachments = MAX_ATTACHMENTS
        self.write_stall = WRITE_STALL
        self._stopping = False
        self._shutdown_requested = False
        self._next_prepared_sweep = time.monotonic() + PREPARED_SWEEP

    # ---- lifecycle ----

    def start(self) -> None:
        if len(os.fsencode(str(self.sock_path))) > SUN_PATH_MAX:
            raise UnsafePath(f"socket 路徑過長（macOS 上限 {SUN_PATH_MAX} bytes）：{self.sock_path}")
        me = os.getuid()
        old_umask = os.umask(0o077)
        try:
            _secure_dir(self.base, me)
            self._lock_fd = _acquire_lock(self.lock_path, me)
            try:
                _clear_stale_socket(self.sock_path, me)
                lst = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    lst.bind(str(self.sock_path))
                    os.chmod(self.sock_path, 0o600)
                    lst.listen(16)
                    lst.setblocking(False)
                except BaseException:
                    lst.close()
                    raise
            except BaseException:
                self._release_lock()
                raise
        finally:
            os.umask(old_umask)
        self._listener = lst
        try:
            st = os.lstat(self.sock_path)
            self._sock_id = (st.st_dev, st.st_ino)
            self._wake_r, self._wake_w = os.pipe()
            for fd in (self._wake_r, self._wake_w):
                os.set_blocking(fd, False)
            self._sel = selectors.DefaultSelector()
            self._sel.register(lst, selectors.EVENT_READ, "listen")
            self._sel.register(self._wake_r, selectors.EVENT_READ, "wake")
        except BaseException:
            # Anything failing after bind must not leak the listener, the
            # socket file, the wake pipe or the lock (AGY S0 P2).
            self.close()
            raise
        self._log(f"listening on {self.sock_path} (pid {os.getpid()})")
        try:  # launches left behind by a previous daemon; never fatal
            for item in agent_sessions.recover(self.base):
                self._log(f"managed launch {item['launch_id']}: " +
                          ("cleaned" if item.get("cleaned") else f"retained ({item.get('retained_reason')})"))
        except Exception as exc:
            self._log(f"managed launch recovery failed: {exc}")

    def wake(self) -> None:
        if self._wake_w >= 0:
            try:
                os.write(self._wake_w, b"x")
            except OSError:
                pass

    def stop(self) -> None:
        self._stopping = True
        self.wake()

    def serve_forever(self) -> None:
        assert self._sel is not None, "start() first"
        while not self._stopping:
            busy = self._shutdown_requested or any(s.phase for s in self._sessions.values())
            for key, mask in self._sel.select(timeout=0.05 if busy else 0.25):
                data = key.data
                if isinstance(data, Session):
                    if data.registered:
                        self._read_master(data)
                elif isinstance(data, Attachment):
                    if self._attachments.get(data.sock) is not data:
                        continue
                    if mask & selectors.EVENT_READ:
                        self._att_read(data)
                    if mask & selectors.EVENT_WRITE and self._attachments.get(data.sock) is data:
                        self._att_flush(data)
                elif isinstance(data, _Conn):
                    if self._conns.get(data.sock) is not data:
                        continue  # dropped earlier in this same batch
                    if mask & selectors.EVENT_READ:
                        self._on_read(data)
                    elif mask & selectors.EVENT_WRITE:
                        self._flush(data)
                elif data == "listen":
                    self._accept()
                elif data == "wake":
                    try:
                        while os.read(self._wake_r, 512):
                            pass
                    except BlockingIOError:
                        pass
            now = time.monotonic()
            self._tick(now)
            self._sweep(now)

    def close(self) -> None:
        """Tear everything down. Idempotent. Sessions are killed here: with
        the daemon gone nobody could manage them, and orphans are worse."""
        self._kill_all_sessions()
        for att in list(self._attachments.values()):
            self._drop_att(att)
        for conn in list(self._conns.values()):
            self._drop(conn)
        if self._sel is not None:
            self._sel.close()
            self._sel = None
        if self._listener is not None:
            self._listener.close()
            self._listener = None
            try:  # only remove the socket file we created
                st = os.lstat(self.sock_path)
                if (st.st_dev, st.st_ino) == self._sock_id:
                    os.unlink(self.sock_path)
            except OSError:
                pass
        for fd in (self._wake_r, self._wake_w):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._wake_r = self._wake_w = -1
        self._release_lock()

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)  # closing the description releases flock
            self._lock_fd = None

    # ---- sessions ----

    def _spawn(self, argv: list, cwd: str, cols: int, rows: int, env: dict) -> Session:
        master, slave = os.openpty()
        try:
            _set_winsize(slave, rows, cols)
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", PTYEXEC, *argv],
                stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                start_new_session=True, close_fds=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        try:
            os.set_blocking(master, False)
            sid = "n-" + secrets.token_hex(6)
            while sid in self._sessions:
                sid = "n-" + secrets.token_hex(6)
            sess = Session(sid, proc, master, list(argv), cwd, cols, rows)
            self._sel.register(master, selectors.EVENT_READ, sess)
            sess.registered = True
            self._sessions[sid] = sess
            return sess
        except BaseException:
            # Not tracked yet: nobody else would ever reap it (AGY S1 P2).
            os.close(master)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            raise

    def _observe_managed(self, s: Session, *, force: bool = False, rows: list | None = None) -> None:
        """Refresh what we know about a managed session's descendants. Costs
        one process-table read unless ``rows`` is supplied, so it is
        rate-limited unless ``force`` is set."""
        if s.tracker is None:
            return
        now = time.monotonic()
        if not force and now < s.next_observe:
            return
        s.next_observe = now + (MANAGED_OBSERVE_CLOSING if s.phase else MANAGED_OBSERVE)
        try:
            rows = proctrack.process_table() if rows is None else rows
        except proctrack.ProcessTableUnavailable as exc:
            if not s.unproven:
                self._log(f"{s.sid}: process table unavailable: {exc}")
            s.unproven = True
            s.missed_looks += 1
            return
        added = s.tracker.observe(rows)
        groups, uncertain = s.tracker.groups(rows, uid=os.getuid(), exclude_pgid=s.pgid)
        s.extra_groups = groups
        s.extra_alive = any(r["pgid"] != s.pgid for r in s.tracker.live(rows))
        s.unproven = bool(uncertain)
        if added:
            try:
                agent_sessions.update_manifest(self.base, s.launch_id, observed=s.tracker.export())
            except (OSError, agent_sessions.LaunchRefused) as exc:
                self._log(f"{s.sid}: manifest update failed: {exc}")

    def _finish_managed(self, s: Session) -> dict | None:
        """Exact cleanup of a managed session's scratch and settings, or retain."""
        if s.launch_id is None:
            return None
        self._observe_managed(s, force=True)
        reason = ""
        if s.exit_code is None:
            reason = "leader 尚未結束"
        elif s.leader_group_alive():
            reason = "leader 的 process group 仍有程序"
        elif s.extra_alive:
            reason = "仍有已觀測的後代程序存活"
        elif s.unproven:
            reason = "無法取得程序表或有無法確認身分的後代"
        result = agent_sessions.cleanup_launch(self.base, s.launch_id, proven_dead=not reason, reason=reason)
        self._log(f"{s.sid}: managed launch {s.launch_id} " +
                  ("cleaned" if result.get("cleaned") else f"retained ({result.get('retained_reason')})") +
                  (f"; process table was unreadable {s.missed_looks} time(s) during the session"
                   if s.missed_looks else ""))
        return result

    def _read_master(self, s: Session, budget: int = 16) -> None:
        for _ in range(budget):  # bounded so one noisy session cannot starve others
            try:
                data = os.read(s.master, 65536)
            except BlockingIOError:
                return
            except InterruptedError:
                continue
            except OSError as exc:
                # macOS reports EIO once every slave fd is closed: that is EOF.
                if exc.errno != errno.EIO:
                    self._log(f"{s.sid}: master read failed: {exc}")
                data = b""
            if not data:
                s.eof = True
                self._unregister_master(s)
                return
            s.append(data)
            if s.titles is not None:
                s.titles.feed(data, time.time())
            if s.attachments:  # fan-out: encode once, queue per attachment
                s.seq += 1
                line = _line(_frame(s, data, False))
                for att in list(s.attachments):
                    self._att_enqueue(att, line)

    def _unregister_master(self, s: Session) -> None:
        if s.registered:
            s.registered = False
            if self._sel is not None:
                try:
                    self._sel.unregister(s.master)
                except (KeyError, ValueError):
                    pass

    def _close_master(self, s: Session) -> None:
        self._unregister_master(s)
        if s.master >= 0:
            try:
                os.close(s.master)
            except OSError:
                pass
            s.master = -1

    def _begin_close(self, s: Session) -> None:
        if s.phase is not None:
            return
        s.phase = "hup"
        s.deadline = time.monotonic() + HUP_GRACE
        self._observe_managed(s, force=True)  # descendant groups current before signalling
        # Already exited with an empty group: signal nobody (a reused pgid
        # must never be hit); the next _tick finalizes it (AGY S1 P3).
        if s.poll() is not None and not s.group_alive():
            return
        s.signal(signal.SIGHUP)

    def _tick(self, now: float) -> None:
        if now >= self._next_prepared_sweep:
            self._next_prepared_sweep = now + PREPARED_SWEEP
            try:  # previews nobody confirmed; they never had a process
                for item in agent_sessions.expire_prepared(self.base):
                    self._log(f"prepared launch {item['launch_id']} expired: " +
                              ("removed" if item.get("cleaned") else f"kept ({item.get('retained_reason')})"))
            except Exception as exc:
                self._log(f"prepared launch sweep failed: {exc}")
        due = [s for s in self._sessions.values() if s.tracker is not None and now >= s.next_observe]
        if due:  # one process table per tick, shared by every managed session that is due
            try:
                table = proctrack.process_table()
            except proctrack.ProcessTableUnavailable:
                table = None
            for s in due:
                self._observe_managed(s, rows=table)
        for s in list(self._sessions.values()):
            s.poll()  # reaps natural exits too (no zombies)
            if (s.exit_code is not None and not s.exit_notified
                    and (s.eof or not s.registered or not s.group_alive())):
                if s.registered:
                    self._read_master(s, budget=64)
                s.exit_notified = True
                s.exit_reason = f"程序已結束（exit {s.exit_code}）"
                for att in list(s.attachments):
                    self._att_close_with(att, s.exit_reason)
            if s.phase is None:
                continue
            if s.exit_code is not None and not s.group_alive():
                self._finalize(s)
                continue
            if now < s.deadline:
                continue
            if s.phase == "hup":
                s.phase, s.deadline = "term", now + TERM_GRACE
                self._observe_managed(s, force=True)
                s.signal(signal.SIGTERM)
            elif s.phase == "term":
                s.phase, s.deadline, s.forced = "kill", now + KILL_GRACE, True
                self._observe_managed(s, force=True)
                s.signal(signal.SIGKILL)
            else:
                self._log(f"{s.sid}: process group still present after SIGKILL; finalizing")
                s.poll()
                self._finalize(s)
        if (self._shutdown_requested and not self._sessions
                and not any(c.stop_after for c in self._conns.values())):
            self.stop()

    def _finalize(self, s: Session) -> None:
        if s.registered:
            self._read_master(s, budget=64)  # last output before the master closes
        self._close_master(s)
        self._sessions.pop(s.sid, None)
        for att in list(s.attachments):
            self._att_close_with(att, s.exit_reason or "session 已關閉")
            att.sess = None
        s.attachments.clear()
        s.control = None
        result = {"session_id": s.sid, "exit_code": s.exit_code, "forced": s.forced}
        managed = self._finish_managed(s)
        if managed is not None:
            result["managed"] = managed
        for conn in s.waiters:
            if self._conns.get(conn.sock) is conn and conn.waiting:
                conn.waiting = False
                self._respond(conn, _ok(conn.rid, result))
        s.waiters.clear()

    def _kill_all_sessions(self) -> None:
        sessions = list(self._sessions.values())
        if not sessions:
            return
        def alive(s):
            self._observe_managed(s, force=True)
            return s.poll() is None or s.group_alive()
        for s in sessions:
            if alive(s):
                s.signal(signal.SIGTERM)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and any(alive(s) for s in sessions):
            time.sleep(0.05)
        for s in sessions:
            if alive(s):
                s.signal(signal.SIGKILL)
        for s in sessions:
            try:
                s.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._log(f"{s.sid}: leader did not exit after SIGKILL")
            s.poll()
            self._close_master(s)
            if s.launch_id is not None:
                end = time.monotonic() + 1.0  # let SIGKILLed descendants disappear
                while time.monotonic() < end and alive(s):
                    time.sleep(0.05)
                self._finish_managed(s)
        self._sessions.clear()

    # ---- connections ----

    def _accept(self) -> None:
        while True:
            try:
                sock, _ = self._listener.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError as exc:
                self._log(f"accept failed: {exc}")
                return
            try:
                uid = peer_uid(sock)
            except (OSError, ValueError) as exc:
                self._log(f"reject connection: cannot read peer credentials ({exc})")
                sock.close()
                continue
            if uid != self.uid:
                self._log(f"reject connection from uid {uid}")
                sock.close()
                continue
            sock.setblocking(False)
            conn = _Conn(sock, time.monotonic() + self.idle_timeout)
            self._conns[sock] = conn
            self._sel.register(sock, selectors.EVENT_READ, conn)

    def _drop(self, conn: _Conn) -> None:
        self._conns.pop(conn.sock, None)
        conn.waiting = False
        if self._sel is not None:
            try:
                self._sel.unregister(conn.sock)
            except (KeyError, ValueError):
                pass
        conn.sock.close()

    def _sweep(self, now: float) -> None:
        # ``deadline`` is fixed at accept: a whole RPC (connect -> request ->
        # reply) must finish within ``idle_timeout``. Deliberately not
        # refreshed on partial reads, so a slow-drip client cannot hold a fd.
        # A deferred ``close`` reply gets CLOSE_WAIT instead. S2 attach
        # connections use their own write-stall rule.
        for conn in [c for c in self._conns.values() if c.deadline < now]:
            self._drop(conn)
        for att in [a for a in self._attachments.values()
                    # resync counts as pending: after an overflow the queue is
                    # empty but a full replay is still owed to a blocked socket.
                    if (a.cur or a.out or a.resync)
                    and now - a.last_progress > self.write_stall]:
            self._log(f"{att.aid}: no write progress for {self.write_stall}s; dropping")
            self._drop_att(att)

    def _on_read(self, conn: _Conn) -> None:
        try:
            chunk = conn.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            return self._drop(conn)
        if not chunk:
            return self._drop(conn)
        if conn.waiting or conn.out:
            return  # one request per connection; extra bytes are ignored
        conn.buf += chunk
        nl = conn.buf.find(b"\n")
        if nl < 0:
            if len(conn.buf) > MAX_LINE:
                self._respond(conn, _err(None, "bad_request", "請求超過 64 KiB"))
            return
        if nl > MAX_LINE:
            return self._respond(conn, _err(None, "bad_request", "請求超過 64 KiB"))
        resp = self._dispatch(bytes(conn.buf[:nl]), conn)
        if resp is _ATTACHED:  # this socket is now an attachment
            rest = bytes(conn.buf[nl + 1:])
            conn.buf.clear()
            att = self._attachments.get(conn.sock)
            if att is not None and rest:
                att.inbuf += rest
                self._att_process(att)
            return
        if resp is None:  # deferred (close): answered from _finalize
            conn.buf.clear()
            conn.waiting = True
            conn.deadline = time.monotonic() + CLOSE_WAIT
            return
        self._respond(conn, resp)

    def _respond(self, conn: _Conn, resp: dict) -> None:
        conn.buf.clear()
        conn.out = bytearray(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
        self._sel.modify(conn.sock, selectors.EVENT_WRITE, conn)
        self._flush(conn)

    def _flush(self, conn: _Conn) -> None:
        try:
            n = conn.sock.send(conn.out)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            return self._drop(conn)
        del conn.out[:n]
        if conn.out:
            return
        self._drop(conn)  # RPC connections are one request, one response

    # ---- RPC ----

    def _dispatch(self, line: bytes, conn: _Conn) -> dict | None:
        try:
            req = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _err(None, "bad_request", "不是有效的 JSON")
        if not isinstance(req, dict):
            return _err(None, "bad_request", "請求必須是 JSON 物件")
        rid = req.get("id")
        if not isinstance(rid, str) or not 1 <= len(rid) <= 128:
            return _err(None, "bad_request", "缺少或無效的 request id")
        conn.rid = rid
        if req.get("v") != PROTOCOL_VERSION:
            return _err(rid, "bad_request", "不支援的協定版本")
        op = req.get("op")
        if op not in RPC_OPS:
            return _err(rid, "bad_request", f"未知的指令：{op!r}")
        extra = set(req) - ENVELOPE - RPC_OPS[op]
        if extra:
            return _err(rid, "bad_request", f"未知欄位：{', '.join(sorted(extra))}")
        if op == "hello":
            return _ok(rid, {"protocol": PROTOCOL_VERSION, "version": DAEMON_VERSION,
                             "pid": os.getpid(), "sessions": len(self._sessions),
                             "attachments": len(self._attachments)})
        if op == "list":
            return _ok(rid, {"sessions": [s.info() for s in
                                          sorted(self._sessions.values(), key=lambda s: s.started)]})
        if op == "open":
            return self._op_open(rid, req)
        if op == "open_managed":
            return self._op_open_managed(rid, req)
        if op == "close":
            return self._op_close(rid, req, conn)
        if op == "shutdown":
            return self._op_shutdown(rid, req, conn)
        if op == "attach":
            return self._op_attach(rid, req, conn)
        return _err(rid, "internal", "未處理的指令")

    # ---- attachments ----

    def _op_attach(self, rid: str, req: dict, conn: _Conn):
        sid = req.get("session_id")
        if not isinstance(sid, str) or not SESSION_RE.match(sid):
            return _err(rid, "bad_request", "無效的 session id")
        mode = req.get("mode")
        if mode not in ("observe", "control"):
            return _err(rid, "bad_request", "mode 必須是 observe 或 control")
        s = self._sessions.get(sid)
        if s is None or s.phase is not None:
            return _err(rid, "not_found", "沒有這個 session（或正在關閉）")
        cols, rows = req.get("cols", s.cols), req.get("rows", s.rows)
        if not (_int_in(cols, 1, 1000) and _int_in(rows, 1, 1000)):
            return _err(rid, "bad_request", "cols/rows 必須是 1–1000 的整數")
        if len(s.attachments) >= self.max_attachments:
            return _err(rid, "limit", f"此 session 已達連線上限（{self.max_attachments}）")
        self._conns.pop(conn.sock, None)
        att = Attachment(conn.sock, s, mode)
        self._attachments[conn.sock] = att
        self._sel.modify(conn.sock, selectors.EVENT_READ, att)
        s.attachments.append(att)
        if mode == "control":
            prev = s.control
            if prev is not None and prev is not att:
                prev.mode = "observe"
                self._att_enqueue(prev, _line({"type": "terminal.control_lost"}), frame=False)
            s.control = att
            if (cols, rows) != (s.cols, s.rows) and s.master >= 0 and s.exit_code is None:
                try:
                    _set_winsize(s.master, rows, cols)
                    s.cols, s.rows = cols, rows
                except OSError:
                    pass
        # The handshake reply (with attachment_id) precedes the first frame.
        self._att_push(att, _line(_ok(rid, {"attachment_id": att.aid, "session_id": sid,
                                            "mode": mode, "cols": s.cols, "rows": s.rows})))
        self._att_push(att, self._full_line(s))
        if s.exit_notified:
            self._att_close_with(att, s.exit_reason)
        return _ATTACHED

    def _full_line(self, s: Session) -> bytes:
        return _line(_frame(s, replay_bytes(s.scrollback), True))

    def _att_push(self, att: Attachment, line: bytes) -> None:
        if not att.out and not att.cur:
            att.last_progress = time.monotonic()
        att.out.append(line)
        att.out_bytes += len(line)
        self._att_want_write(att)

    def _att_enqueue(self, att: Attachment, line: bytes, frame: bool = True) -> None:
        if att.closing:
            return
        if frame:
            if att.resync:
                return  # the pending full replay will cover this output
            if len(att.out) >= ATTACH_QUEUE_MAX or att.out_bytes + len(line) > ATTACH_QUEUE_BYTES:
                # Slow reader: discard, and replay once the socket drains.
                # Never build a full frame while the socket is still blocked.
                att.out.clear()
                att.out_bytes = 0
                att.resync = True
                self._att_want_write(att)
                return
        self._att_push(att, line)

    def _att_close_with(self, att: Attachment, reason: str) -> None:
        if att.closing:
            return
        if att.resync and att.sess is not None:
            att.resync = False
            self._att_push(att, self._full_line(att.sess))
        self._att_push(att, _line({"type": "terminal.closed", "reason": reason}))
        att.closing = True

    def _att_error(self, att: Attachment, code: str) -> None:
        self._att_enqueue(att, _line({"type": "terminal.error", "code": code}), frame=False)

    def _att_want_write(self, att: Attachment) -> None:
        if not att.writing and self._sel is not None:
            att.writing = True
            self._sel.modify(att.sock, selectors.EVENT_READ | selectors.EVENT_WRITE, att)

    def _att_flush(self, att: Attachment) -> None:
        while True:
            if not att.cur:
                if att.out:
                    line = att.out.popleft()
                    att.out_bytes -= len(line)
                    att.cur = bytearray(line)
                elif att.resync and att.sess is not None and not att.closing:
                    att.resync = False
                    att.cur = bytearray(self._full_line(att.sess))
                else:
                    break
            try:
                n = att.sock.send(att.cur)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return self._drop_att(att)
            if n:
                att.last_progress = time.monotonic()
                del att.cur[:n]
            if att.cur:
                return
        if att.closing:
            return self._drop_att(att)
        if att.writing and self._sel is not None:
            att.writing = False
            self._sel.modify(att.sock, selectors.EVENT_READ, att)

    def _att_read(self, att: Attachment) -> None:
        try:
            chunk = att.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            return self._drop_att(att)
        if not chunk:
            return self._drop_att(att)  # disconnect releases control (§1)
        if att.closing:
            return
        att.inbuf += chunk
        self._att_process(att)

    def _att_process(self, att: Attachment) -> None:
        while self._attachments.get(att.sock) is att and not att.closing:
            nl = att.inbuf.find(b"\n")
            if nl < 0:
                if len(att.inbuf) > MAX_LINE:
                    self._drop_att(att)
                return
            line = bytes(att.inbuf[:nl])
            del att.inbuf[:nl + 1]
            if nl > MAX_LINE:
                return self._drop_att(att)
            self._att_command(att, line)

    def _att_command(self, att: Attachment, line: bytes) -> None:
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self._att_error(att, "bad_request")
        if not isinstance(msg, dict):
            return self._att_error(att, "bad_request")
        kind, s = msg.get("type"), att.sess
        if kind == "terminal.release":
            if s is not None and s.control is att:
                s.control = None
            att.mode = "observe"
            return self._att_close_with(att, "released")
        if kind not in ("terminal.input", "terminal.resize"):
            return self._att_error(att, "bad_request")
        if s is None or s.exit_code is not None or s.master < 0:
            return self._att_error(att, "exited")
        if s.control is not att:
            return self._att_error(att, "not_control")
        if kind == "terminal.input":
            try:
                data = base64.b64decode(msg.get("bytes"), validate=True)
            except (binascii.Error, ValueError, TypeError):
                return self._att_error(att, "bad_request")
            if not data or len(data) > INPUT_MAX:
                return self._att_error(att, "bad_request")
            view = memoryview(data)
            while view:
                try:
                    n = os.write(s.master, view)
                except BlockingIOError:
                    return self._att_error(att, "input_busy")
                except InterruptedError:
                    continue
                except OSError:
                    return self._att_error(att, "exited")
                view = view[n:]
            return
        cols, rows = msg.get("cols"), msg.get("rows")
        if not (_int_in(cols, 1, 1000) and _int_in(rows, 1, 1000)):
            return self._att_error(att, "bad_request")
        try:
            _set_winsize(s.master, rows, cols)  # kernel sends SIGWINCH to the fg group
        except OSError:
            return self._att_error(att, "exited")
        s.cols, s.rows = cols, rows

    def _drop_att(self, att: Attachment) -> None:
        self._attachments.pop(att.sock, None)
        if self._sel is not None:
            try:
                self._sel.unregister(att.sock)
            except (KeyError, ValueError):
                pass
        att.sock.close()
        s = att.sess
        if s is not None:
            if att in s.attachments:
                s.attachments.remove(att)
            if s.control is att:
                s.control = None
        att.sess = None

    def _op_open(self, rid: str, req: dict) -> dict:
        if self._shutdown_requested:
            return _err(rid, "limit", "背景程序正在關閉，不接受新的 session")
        argv = req.get("argv")
        if not (isinstance(argv, list) and 1 <= len(argv) <= 256
                and all(isinstance(a, str) and "\0" not in a and len(a) <= 4096 for a in argv)
                and argv[0]):
            return _err(rid, "bad_request", "argv 必須是非空字串陣列")
        cwd = req.get("cwd")
        if not (isinstance(cwd, str) and "\0" not in cwd and os.path.isabs(cwd)
                and os.path.isdir(cwd)):
            return _err(rid, "bad_request", "cwd 必須是既存的絕對路徑資料夾")
        cols, rows = req.get("cols", 80), req.get("rows", 24)
        if not (_int_in(cols, 1, 1000) and _int_in(rows, 1, 1000)):
            return _err(rid, "bad_request", "cols/rows 必須是 1–1000 的整數")
        kind = req.get("kind")
        if kind not in (None, "shell"):
            return _err(rid, "bad_request", "kind 只能是 shell")
        env_in = req.get("env", {})
        if not isinstance(env_in, dict) or any(
                k not in ENV_ALLOW or not isinstance(v, str) or "\0" in v
                for k, v in env_in.items()):
            return _err(rid, "bad_request", f"env 只允許 {', '.join(ENV_ALLOW)}")
        if len(self._sessions) >= self.max_sessions:
            return _err(rid, "limit", f"已達 session 上限（{self.max_sessions}）")
        env = build_env(env_in)
        if _resolve(argv[0], cwd, env["PATH"]) is None:
            return _err(rid, "not_found", f"找不到可執行的指令：{argv[0]}")
        try:
            sess = self._spawn(argv, cwd, cols, rows, env)
        except OSError as exc:
            return _err(rid, "internal", f"無法啟動：{exc}")
        sess.kind = kind
        return _ok(rid, sess.info())

    def _op_open_managed(self, rid: str, req: dict) -> dict:
        """Start a managed Claude or Codex session from a prepared launch.

        argv, cwd and environment come from the validated manifest in our own
        state directory; the caller can pass neither. A launch id is single
        use. Any failed check refuses the launch; nothing is downgraded."""
        if self._shutdown_requested:
            return _err(rid, "limit", "背景程序正在關閉，不接受新的 session")
        launch_id = req.get("launch_id")
        cols, rows = req.get("cols", 80), req.get("rows", 24)
        if not (_int_in(cols, 1, 1000) and _int_in(rows, 1, 1000)):
            return _err(rid, "bad_request", "cols/rows 必須是 1–1000 的整數")
        if len(self._sessions) >= self.max_sessions:
            return _err(rid, "limit", f"已達 session 上限（{self.max_sessions}）")
        try:
            m = agent_sessions.load_validated(self.base, launch_id)
            if m.get("state") != "prepared" or m.get("native_session_id"):
                raise agent_sessions.LaunchRefused("consumed", "此 launch 已使用或不可啟動")
            # The daemon decides itself whether the version is verified (not from a
            # caller's flag or the manifest's own field); an unverified one starts only
            # with the acknowledgement the confirm step recorded in this state dir.
            from . import cli_versions  # here: cli_versions imports this module
            if (m["engine"] == "claude"
                    and m.get("cli_version") not in cli_versions.verified_versions("claude")
                    and m.get("unverified_acknowledged") is not True):
                raise agent_sessions.LaunchRefused(
                    "unverified_not_acknowledged",
                    f"Claude Code {m.get('cli_version')} 尚未驗證，需要使用者在確認畫面明確知悉")
            argv = agent_sessions.managed_argv(m)
            cwd = m["canonical_workspace"]
            env = build_env()
            if m["engine"] == "claude":
                env["CLAUDE_CODE_TMPDIR"] = m["scratch"]["path"]
                # An interactive session otherwise runs the CLI's self-updater, which
                # rewrites the user's global ``claude`` install (seen in S2 acceptance).
                env["DISABLE_AUTOUPDATER"] = "1"
            # Consume before spawning: a replay can never start a second process.
            agent_sessions.update_manifest(self.base, launch_id, state="launching")
        except agent_sessions.LaunchRefused as exc:
            return _err(rid, "refused", f"{exc.code}: {exc}")
        except OSError as exc:
            return _err(rid, "refused", f"launch 狀態無法驗證：{exc}")
        try:
            sess = self._spawn(argv, cwd, cols, rows, env)
        except OSError as exc:
            # No process exists; the prepared state is ours to remove exactly.
            agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)
            return _err(rid, "internal", f"無法啟動：{exc}")
        sess.launch_id = launch_id
        sess.engine = m.get("engine")
        sess.cli_version = m.get("cli_version")
        if sess.engine == "claude":
            sess.titles = osc_title.TitleTracker()
        sess.tracker = proctrack.DescendantTracker(sess.pid)
        leader = None
        try:
            table = proctrack.process_table()
            sess.tracker.observe(table)
            row = next((r for r in table if r["pid"] == sess.pid), None)
            leader = ({"pid": sess.pid, "start": row["start"], "source": proctrack.SOURCE}
                      if row else None)
        except proctrack.ProcessTableUnavailable as exc:
            self._log(f"{sess.sid}: process table unavailable at launch: {exc}")
        try:
            agent_sessions.update_manifest(self.base, launch_id, state="running",
                                           native_session_id=sess.sid, leader=leader,
                                           observed=sess.tracker.export())
        except (OSError, agent_sessions.LaunchRefused) as exc:
            self._log(f"{sess.sid}: manifest update failed: {exc}")
        return _ok(rid, sess.info())

    def _op_close(self, rid: str, req: dict, conn: _Conn) -> dict | None:
        sid = req.get("session_id")
        if not isinstance(sid, str) or not SESSION_RE.match(sid):
            return _err(rid, "bad_request", "無效的 session id")
        sess = self._sessions.get(sid)
        if sess is None:
            return _err(rid, "not_found", "沒有這個 session")
        sess.waiters.append(conn)
        self._begin_close(sess)
        return None

    def _op_shutdown(self, rid: str, req: dict, conn: _Conn) -> dict:
        force = req.get("force", False)
        if not isinstance(force, bool):
            return _err(rid, "bad_request", "force 必須是 true/false")
        n = len(self._sessions)
        if n and not force:
            return _err(rid, "busy", f"仍有 {n} 個 session；要一併關閉請帶 force")
        conn.stop_after = True
        self._shutdown_requested = True
        for s in list(self._sessions.values()):
            self._begin_close(s)
        return _ok(rid, {"stopping": True, "sessions": n})


# --- client -----------------------------------------------------------------

def rpc(op: str, *, base: Path | None = None, path: Path | None = None,
        timeout: float = 2.0, request_id: str | None = None, **fields) -> dict:
    """One RPC round trip. Raises OSError if the daemon is unreachable or
    closes the connection without answering. ``close`` can take up to
    HUP_GRACE + TERM_GRACE + KILL_GRACE seconds: pass a larger timeout."""
    target = str(path or socket_path(base))
    req = {"v": PROTOCOL_VERSION, "id": request_id or secrets.token_hex(8), "op": op, **fields}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(target)
        s.sendall(json.dumps(req, ensure_ascii=False).encode("utf-8") + b"\n")
        buf = bytearray()
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("runtime daemon closed the connection without a reply")
            buf += chunk
            if len(buf) > MAX_LINE:
                raise ConnectionError("runtime daemon reply too long")
    return json.loads(bytes(buf[:buf.find(b"\n")]).decode("utf-8"))


# --- entry point ------------------------------------------------------------

def main(base: Path | None = None) -> int:
    os.umask(0o077)
    daemon = Daemon(base)
    try:
        daemon.start()
    except AlreadyRunning as exc:
        print(f"[runtimed] {exc}", file=sys.stderr)
        return 3
    except RuntimedError as exc:
        print(f"[runtimed] 無法安全啟動：{exc}", file=sys.stderr)
        return 2
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: daemon.stop())
    signal.signal(signal.SIGCHLD, lambda *_: daemon.wake())
    try:
        daemon.serve_forever()
    finally:
        daemon.close()
    return 0


__all__ = ["AlreadyRunning", "Attachment", "Daemon", "RuntimedError", "Session",
           "UnsafePath", "replay_bytes",
           "build_env", "lock_path", "main", "parse_xucred", "peer_uid", "rpc",
           "socket_path"]
