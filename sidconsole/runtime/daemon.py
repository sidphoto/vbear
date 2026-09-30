"""SID native runtime daemon (Phase R2, contract v2).

S0: secure state directory, single-instance lock, stale-socket recovery,
owner-only Unix socket, peer-uid check, RPC ``hello`` / ``shutdown``.
S1: PTY sessions — ``open`` / ``list`` / ``close``, natural-exit reaping,
event-driven HUP -> TERM -> KILL close, scrollback ring, limits.
Attach connections (observe/control/input/resize) are S2.

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
"""

from __future__ import annotations

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
from pathlib import Path
from typing import Callable

from .. import config as cfg

PROTOCOL_VERSION = 1
DAEMON_VERSION = "native-r2-s1"
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
ENV_ALLOW = ("PATH", "TERM", "LANG", "HOME")
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
SESSION_RE = re.compile(r"^n-[0-9a-f]{12}$")
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
    "open": frozenset({"argv", "cwd", "cols", "rows", "env"}),
    "list": frozenset(),
    "close": frozenset({"session_id"}),
}


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
            raise AlreadyRunning("已有 SID runtime 背景程序在執行") from exc
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
    """Child environment: only PATH/TERM/LANG/HOME (contract v2 §5).

    PATH gets the usual Homebrew/system dirs appended when missing, because a
    daemon started from Finder / an .app does not inherit the login shell
    PATH (PHASE-R-PLAN §8 risk 2). Existing entries keep their order."""
    env = {k: os.environ[k] for k in ENV_ALLOW if os.environ.get(k)}
    env.update(overrides or {})
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

    def poll(self) -> int | None:
        if self.exit_code is None:
            rc = self.proc.poll()
            if rc is not None:
                self.exit_code = rc
        return self.exit_code

    def group_alive(self) -> bool:
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
                "closing": self.phase is not None, "output_bytes": self.total}


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
        self._stopping = False
        self._shutdown_requested = False

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
        # Already exited with an empty group: signal nobody (a reused pgid
        # must never be hit); the next _tick finalizes it (AGY S1 P3).
        if s.poll() is not None and not s.group_alive():
            return
        s.signal(signal.SIGHUP)

    def _tick(self, now: float) -> None:
        for s in list(self._sessions.values()):
            s.poll()  # reaps natural exits too (no zombies)
            if s.phase is None:
                continue
            if s.exit_code is not None and not s.group_alive():
                self._finalize(s)
                continue
            if now < s.deadline:
                continue
            if s.phase == "hup":
                s.phase, s.deadline = "term", now + TERM_GRACE
                s.signal(signal.SIGTERM)
            elif s.phase == "term":
                s.phase, s.deadline, s.forced = "kill", now + KILL_GRACE, True
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
        result = {"session_id": s.sid, "exit_code": s.exit_code, "forced": s.forced}
        for conn in s.waiters:
            if self._conns.get(conn.sock) is conn and conn.waiting:
                conn.waiting = False
                self._respond(conn, _ok(conn.rid, result))
        s.waiters.clear()

    def _kill_all_sessions(self) -> None:
        sessions = list(self._sessions.values())
        if not sessions:
            return
        alive = lambda s: s.poll() is None or s.group_alive()
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
            self._close_master(s)
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
                             "pid": os.getpid(), "sessions": len(self._sessions)})
        if op == "list":
            return _ok(rid, {"sessions": [s.info() for s in
                                          sorted(self._sessions.values(), key=lambda s: s.started)]})
        if op == "open":
            return self._op_open(rid, req)
        if op == "close":
            return self._op_close(rid, req, conn)
        if op == "shutdown":
            return self._op_shutdown(rid, req, conn)
        return _err(rid, "internal", "未處理的指令")

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


__all__ = ["AlreadyRunning", "Daemon", "RuntimedError", "Session", "UnsafePath",
           "build_env", "lock_path", "main", "parse_xucred", "peer_uid", "rpc",
           "socket_path"]
