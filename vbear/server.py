"""Local HTTP server: JSON API plus the static web UI.

Security posture (plan section 9):
  - binds to loopback only
  - Host header must be the loopback address, which blocks DNS rebinding
  - state-changing requests need a custom header and a same-origin Origin,
    which blocks cross-site request forgery from other pages in the browser
  - API reads refuse browser requests whose Sec-Fetch-Site is not same-origin
    (or none), and the one GET with a side effect (/api/live?force=1, which
    queries the runtime) also needs the custom header
  - strict Content-Security-Policy; the UI renders skill text as text, never
    as HTML, because skill content is untrusted
  - files are served only by skill id or by a reference the scanner already
    verified inside that skill's directory; never by a caller-supplied path
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import signal
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import queue as queue_mod
from urllib.parse import unquote

from . import annotations
from . import agent_launch
from . import agent_profiles
from . import armory
from . import config as cfg
from . import tasks
from . import runtime as rt
from .index import HOME, STALE_AFTER_S, Store
from .model import ACT_ACTIVE
from .scan import document

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
STATIC_FILES = {
    "/": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
    "/favicon.svg": "favicon.svg",
    "/vendor/xterm/xterm.js": "vendor/xterm/xterm.js",
    "/vendor/xterm/xterm.css": "vendor/xterm/xterm.css",
    "/vendor/xterm/addon-fit.js": "vendor/xterm/addon-fit.js",
    "/vendor/xterm/LICENSE": "vendor/xterm/LICENSE",
}
MAX_FILE_BYTES = document.MAX_FILE_BYTES
# Content Security Policy:
# - script-src is strictly pinned to 'self' (zero CDN, zero eval, zero inline scripts).
# - style-src includes 'unsafe-inline' deliberately because xterm.js 5.5.0 requires dynamic
#   <style> injection (_injectCss) and inline style attributes on row elements (_addStyle
#   calling element.setAttribute('style', ...)) for ANSI 24-bit truecolor rendering.
#   Without 'unsafe-inline', Chrome DevTools logs CSP violations and truecolor colors
#   fall back to monochromatic terminal defaults. Because VBear contains zero
#   untrusted HTML/style injection sinks (all dynamic text uses textContent or strict
#   DOM APIs), allowing 'unsafe-inline' in style-src is a safe, bounded trade-off.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
SKILL_SUMMARY_FIELDS = (
    "skill_id", "name", "invoke_name", "tool", "scope", "activation", "activation_reason",
    "path", "description", "missing_files", "warnings", "origin_package", "duplicate_of",
    "mtime", "categories",
)
SEARCH_EXCERPT_CHARS = 280  # enough of "when to use" for search; full text is in detail
CONFIG_WRITABLE = {"advanced_mode", "usage_enabled", "usage_days", "project_roots", "language",
                   "herdr_migration_acknowledged"}
LANGUAGES = {"zh-TW"}  # the only UI language shipped
MAX_PROJECT_ROOTS = 20
MAX_BODY = 64 * 1024
BODY_DEADLINE_S = 15.0  # whole body, not per read: a byte-at-a-time sender is cut off too
FETCH_SITE_OK = {"same-origin", "none"}  # "same-site" would admit other localhost ports
# A terminal this narrow or short cannot render anything usable: a stray
# `cols=2` (which a browser really does propose when it measures the canvas
# before the grid has laid out) makes every TUI and even plain wrapped text
# unreadable, and the session's PTY is resized for every viewer too. Out
# of range values fall back to the defaults rather than being clamped, so a
# degenerate measurement yields a sane 80x24 instead of a silently ruined
# 20-column session.
TERM_MIN_DIM, TERM_MAX_DIM = 20, 500
TERM_MIN_ROWS = 5
TERM_DEFAULT_COLS, TERM_DEFAULT_ROWS = 80, 24


class Console:
    def __init__(self, port: int):
        self.port = port
        # Every /api/ request must carry this token (cookie or Bearer). It is
        # new for each server start and is shared only through an owner-only
        # file in the state directory. None turns the check off; only test
        # code does that, there is no setting for it.
        self.auth_token: str | None = secrets.token_urlsafe(32)
        self.store = Store()
        self.lock = threading.Lock()
        # The Runtime is the single seam the console has with the terminal
        # backend (`vbear runtimed`), built once at console startup.
        # VBEAR_RUNTIME_AUTOSTART=0 keeps the console from spawning the daemon
        # (tests run their own, and must never leave one behind).
        self.runtime_kind = "native"
        self.runtime = rt.get_runtime(autostart=os.environ.get("VBEAR_RUNTIME_AUTOSTART", "1") != "0")
        # Store's live snapshot must come from the same backend.
        self.store.runtime = self.runtime
        # Profile-managed launches (R3 S0): work directories must be inside this root.
        self.managed_root = Path.home()
        self._previews = None

    def previews(self):
        """Preview store for Profile-managed launches; native runtime only."""
        with self.lock:
            if self._previews is None:
                self._previews = agent_launch.PreviewStore(
                    self.runtime, allowed_root=lambda: str(self.managed_root.resolve()))
            return self._previews

    def runtime_unavailable_message(self) -> str:
        return "VBear runtime 背景程序無法啟動或連線"

    # derived views ------------------------------------------------------

    def skill_index(self) -> dict:
        return {s["skill_id"]: s for s in self.store.static()["skills"]}

    def roles_for_skill(self, skill_id: str) -> list[dict]:
        out = []
        for role in self.store.static()["roles"]:
            if skill_id in role.get("skill_link_ids", []):
                out.append({"role_id": role["role_id"], "name": role["name"],
                            "tool": role["tool"], "basis": role["skill_link_basis"]})
        return out

    def usage_for_skill(self, skill_id: str) -> list[dict]:
        rows = []
        for sess in self.store.live(stale_ok=True)["usage"]["sessions"]:
            for used in sess["skills"]:
                if skill_id in used["skill_ids"]:
                    rows.append({"session_id": sess["session_id"], "tool": sess["tool"],
                                 "project_id": sess["project_id"], "cwd": sess["cwd"],
                                 "count": used["count"], "last_ts": used["last_ts"],
                                 "evidence": used["evidence"], "resolution": used["resolution"]})
        rows.sort(key=lambda r: r["last_ts"], reverse=True)
        return rows

    def armory_view(self) -> dict:
        """D1 read-only projection; profile storage failures deliberately
        propagate to the handler's existing AgentProfileStorageError -> 503."""
        static = self.store.static()
        skills = static["skills"]
        profiles = agent_profiles.list_profiles(
            known_skills={s["skill_id"] for s in skills},
            known_roles={r["role_id"] for r in static.get("roles", []) if r.get("role_id")},
        )
        return armory.project(skills, profiles, self.usage_for_skill)

    def annotation_keys(self) -> set[str]:
        return {annotations.key_for(s) for s in self.store.static()["skills"]}

    def live_targets(self, force: bool = False) -> set[str]:
        """Session ids the runtime reported in the current live snapshot:
        every terminal (`panes`) plus the Agent terminals (`sessions`)."""
        live = self.store.live(force=force)
        ids: set[str] = set()
        for row in list(live.get("panes", ())) + list(live["sessions"]):
            for field in ("pane_id", "terminal_id"):
                if isinstance(row.get(field), str) and row[field]:
                    ids.add(row[field])
        return ids


def login_shell() -> str:
    """The account's login shell when it is a listed, executable absolute path;
    /bin/zsh (the macOS default) otherwise."""
    import pwd
    try:
        shell = pwd.getpwuid(os.getuid()).pw_shell
        listed = {line.strip() for line in Path("/etc/shells").read_text().splitlines()
                  if line.strip() and not line.startswith("#")}
    except (KeyError, OSError):
        return "/bin/zsh"
    if os.path.isabs(shell) and shell in listed and os.access(shell, os.X_OK):
        return shell
    return "/bin/zsh"


def make_handler(console: Console):
    allowed_hosts = {f"127.0.0.1:{console.port}", f"localhost:{console.port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "VBear/0.1"
        sys_version = ""
        timeout = 15.0

        def log_message(self, fmt, *args):  # keep the terminal quiet; no request bodies
            if "--verbose" in sys.argv:
                sys.stderr.write("%s %s\n" % (self.command, self.path.split("?", 1)[0]))

        # plumbing ---------------------------------------------------------

        def _headers(self, status: int, ctype: str, length: int):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if self.close_connection:  # say so, instead of only hanging up
                self.send_header("Connection", "close")
            self.end_headers()

        def _json(self, payload, status: int = 200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)

        def _error(self, status: int, message: str):
            self._json({"error": message}, status)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def _write_ok(self) -> bool:
            if self.headers.get("X-VBear") != "1":
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in allowed_origins

        def _cookie_name(self) -> str:
            # Cookies are per host, not per port: two consoles on 127.0.0.1
            # must not overwrite each other's session.
            return f"vbear_session_{console.port}"

        def _authed(self) -> bool:
            want = console.auth_token
            if want is None:
                return True
            got = ""
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                got = auth[len("Bearer "):].strip()
            else:
                for part in self.headers.get("Cookie", "").split(";"):
                    name, _, value = part.strip().partition("=")
                    if name == self._cookie_name():
                        got = value
                        break
            return bool(got) and hmac.compare_digest(got.encode(), want.encode())

        def _auth_error(self):
            return self._json({"error": "需要從 VBear 開啟（執行 python3 -m vbear launch 或打開 VBear App）",
                               "code": "auth_required"}, 401)

        def _auth_exchange(self, body: dict):
            """Browser bootstrap: trade the launch token for an HttpOnly cookie."""
            token = body.get("token")
            want = console.auth_token
            if want is None:
                return self._json({"ok": True})
            if not (isinstance(token, str) and hmac.compare_digest(token.encode(), want.encode())):
                return self._error(401, "token 不正確或已過期（主控台重新啟動過），請重新從 VBear 開啟")
            body_bytes = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Set-Cookie", f"{self._cookie_name()}={want}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body_bytes)

        def _read_ok(self) -> bool:
            # Browsers always send Sec-Fetch-Site; its absence means a non-browser
            # local client (curl, the launcher's health check), which is allowed.
            site = self.headers.get("Sec-Fetch-Site")
            return site is None or site in FETCH_SITE_OK

        def _read_content_length(self) -> int:
            """Plain ASCII digits only. int() would also take "+5", "1_0" or
            " 7 ", which no HTTP client sends and proxies may read differently."""
            raw = self.headers.get("Content-Length")
            if raw is None or raw == "":
                return 0
            if not (raw.isascii() and raw.isdigit()) or len(raw) > 9:
                raise ValueError("無效的 Content-Length")
            return int(raw)

        def _read_body_bytes(self, length: int) -> bytes:
            """Read exactly `length` bytes within BODY_DEADLINE_S in total.

            The handler's socket timeout bounds each read; this bounds their
            sum, so a client trickling a byte every few seconds cannot hold a
            worker thread indefinitely.
            """
            deadline = time.monotonic() + BODY_DEADLINE_S
            chunks, remaining = [], length
            while remaining > 0:
                if time.monotonic() > deadline:
                    raise TimeoutError("request body too slow")
                chunk = self.rfile.read1(min(remaining, 8192))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)

        def _body(self) -> dict:
            length = self._read_content_length()
            if length <= 0:
                return {}
            try:
                data = json.loads(self._read_body_bytes(length).decode("utf-8"))
            except TimeoutError:
                raise
            except (ValueError, UnicodeDecodeError, RecursionError):
                return {}
            return data if isinstance(data, dict) else {}

        # routes -----------------------------------------------------------

        def do_GET(self):
            if not self._host_ok():
                return self._error(HTTPStatus.MISDIRECTED_REQUEST, "invalid host")
            url = urlparse(self.path)
            path = url.path
            if path.startswith("/api/") and not self._read_ok():
                return self._error(403, "forbidden")
            if path.startswith("/api/") and not self._authed():
                return self._auth_error()
            try:
                if path in STATIC_FILES:
                    return self._static(STATIC_FILES[path])
                if path == "/api/overview":
                    return self._json(self._overview())
                if path == "/api/skills":
                    return self._json(self._skills())
                if path == "/api/armory":
                    return self._json(console.armory_view())
                if path.startswith("/api/skills/"):
                    rest = path[len("/api/skills/"):]
                    if rest.endswith("/file"):
                        ref = parse_qs(url.query).get("ref", [""])[0]
                        return self._skill_file(rest[:-5], ref)
                    return self._skill_detail(rest)
                if path == "/api/roles":
                    return self._json(self._roles())
                if path == "/api/live":
                    force = parse_qs(url.query).get("force", ["0"])[0] == "1"
                    if force and self.headers.get("X-VBear") != "1":
                        return self._error(403, "強制更新需要主控台標頭")
                    return self._json(console.store.live(force=force))
                if path == "/api/config":
                    return self._json(self._config_view())
                if path == "/api/tasks":
                    return self._json({"ok": True, "tasks": tasks.list_tasks()})
                if path == "/api/task-templates":
                    return self._json({"ok": True, "templates": tasks.get_templates()})
                if path.startswith("/api/tasks/"):
                    task_id = path[len("/api/tasks/"):]
                    t = tasks.get_task(task_id)
                    if t is None:
                        return self._error(404, "找不到此任務卡")
                    return self._json({"ok": True, "task": t})
                if path == "/api/governance":
                    return self._json(self._governance_view())
                if path == "/api/agent-builder/catalog":
                    return self._json(self._agent_builder_catalog())
                if path == "/api/agent-profiles":
                    index = console.skill_index()
                    known_skills = set(index.keys())
                    known_roles = {
                        r.get("role_id") for r in console.store.static().get("roles", [])
                        if r.get("role_id")
                    }
                    return self._json({
                        "ok": True,
                        "profiles": agent_profiles.list_profiles(
                            known_skills=known_skills, known_roles=known_roles),
                    })
                if path.startswith("/api/agent-profiles/"):
                    rest = path[len("/api/agent-profiles/"):]
                    index = console.skill_index()
                    known_skills = set(index.keys())
                    known_roles = {
                        r.get("role_id") for r in console.store.static().get("roles", [])
                        if r.get("role_id")
                    }
                    p = agent_profiles.get_profile(rest, known_skills=known_skills,
                                                    known_roles=known_roles)
                    if p is None:
                        return self._error(404, "找不到此 Agent Profile")
                    return self._json({"ok": True, "profile": p})
                if path.startswith("/api/term/"):
                    pane_enc, _, action = path[len("/api/term/"):].rpartition("/")
                    if action == "stream" and pane_enc:
                        return self._term_stream(unquote(pane_enc), url.query)
                return self._error(404, "not found")
            except TimeoutError:
                raise
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client went away mid-request; nothing left to answer
            except tasks.TaskStorageError as exc:
                return self._error(503, str(exc))
            except agent_profiles.AgentProfileStorageError as exc:
                return self._error(503, str(exc))
            except Exception as exc:  # report, never crash the server
                return self._error(500, f"內部錯誤：{type(exc).__name__}")

        def do_HEAD(self):
            if not self._host_ok():
                return self._error(HTTPStatus.MISDIRECTED_REQUEST, "invalid host")
            self._headers(200 if urlparse(self.path).path in STATIC_FILES else 404,
                          "text/html; charset=utf-8", 0)

        def do_POST(self):
            if not self._host_ok():
                return self._error(HTTPStatus.MISDIRECTED_REQUEST, "invalid host")
            if not self._write_ok():
                return self._error(403, "forbidden")
            if urlparse(self.path).path != "/api/auth" and not self._authed():
                return self._auth_error()
            try:
                length = self._read_content_length()
            except ValueError as exc:
                self.close_connection = True
                return self._error(400, str(exc))
            if length > MAX_BODY:
                self.close_connection = True  # the unread body must not be parsed as a request
                return self._error(413, "請求內容過大")
            path = urlparse(self.path).path
            try:
                if path == "/api/auth":
                    return self._auth_exchange(self._body())
                if path == "/api/rescan":
                    try:
                        data = console.store.rescan()
                    except ValueError as exc:  # corrupt config: scan scope unknown
                        return self._error(409, str(exc))
                    return self._json({"ok": True, "generated_at": data["generated_at"],
                                       "scan_seconds": data["scan_seconds"]})
                if path == "/api/config":
                    try:
                        return self._json(self._config_update(self._body()))
                    except ValueError as exc:
                        return self._error(400, str(exc))
                if path == "/api/annotations":
                    body = self._body()
                    try:
                        saved = annotations.save(str(body.get("key", "")), body,
                                                 allowed_keys=console.annotation_keys())
                    except ValueError as exc:
                        return self._error(400, str(exc))
                    return self._json({"ok": True, "annotation": saved})
                if path == "/api/native/sessions":
                    return self._native_open(self._body())
                if path == "/api/native/terminals":
                    return self._terminal_open(self._body())
                if path == "/api/native/agent-previews":
                    return self._agent_preview(self._body())
                if path == "/api/native/agent-launches":
                    return self._agent_launch(self._body())
                if path.startswith("/api/native/sessions/") and path.endswith("/close"):
                    return self._native_close(unquote(path[len("/api/native/sessions/"):-len("/close")]))
                if path == "/api/tasks":
                    try:
                        saved = tasks.save_task(None, self._body())
                        return self._json({"ok": True, "task": saved})
                    except ValueError as exc:
                        return self._error(400, str(exc))
                if path.startswith("/api/tasks/"):
                    rest = path[len("/api/tasks/"):]
                    if rest.endswith("/delete"):
                        task_id = rest[:-7]
                        ok = tasks.delete_task(task_id)
                        if not ok:
                            return self._error(404, "找不到此任務卡或已刪除")
                        return self._json({"ok": True, "deleted": task_id})
                    task_id = rest
                    body = self._body()
                    if body.get("action") == "delete":
                        ok = tasks.delete_task(task_id)
                        if not ok:
                            return self._error(404, "找不到此任務卡或已刪除")
                        return self._json({"ok": True, "deleted": task_id})
                    try:
                        saved = tasks.save_task(task_id, body)
                        return self._json({"ok": True, "task": saved})
                    except ValueError as exc:
                        return self._error(400, str(exc))
                if path == "/api/agent-profiles":
                    body = self._body()
                    index = console.skill_index()
                    known_skills = set(index.keys())
                    known_roles = {
                        r.get("role_id") for r in console.store.static().get("roles", [])
                        if r.get("role_id")
                    }
                    try:
                        saved = agent_profiles.save_profile(None, body,
                                                             known_skills=known_skills,
                                                             known_roles=known_roles)
                    except ValueError as exc:
                        return self._error(400, str(exc))
                    return self._json({"ok": True, "profile": saved})
                if path.startswith("/api/agent-profiles/"):
                    rest = path[len("/api/agent-profiles/"):]
                    body = self._body()
                    index = console.skill_index()
                    known_skills = set(index.keys())
                    known_roles = {
                        r.get("role_id") for r in console.store.static().get("roles", [])
                        if r.get("role_id")
                    }
                    if rest.endswith("/delete"):
                        target = rest[:-7]
                        ok = agent_profiles.delete_profile(target)
                        if not ok:
                            return self._error(404, "找不到此 Agent Profile 或已刪除")
                        return self._json({"ok": True, "deleted": target})
                    if rest.endswith("/duplicate"):
                        target = rest[:-10]
                        try:
                            dup = agent_profiles.duplicate_profile(
                                target, known_skills=known_skills,
                                known_roles=known_roles)
                        except ValueError as exc:
                            return self._error(400, str(exc))
                        if dup is None:
                            return self._error(404, "找不到此 Agent Profile")
                        return self._json({"ok": True, "profile": dup})
                    target = rest
                    try:
                        saved = agent_profiles.save_profile(target, body,
                                                             known_skills=known_skills,
                                                             known_roles=known_roles)
                    except ValueError as exc:
                        return self._error(400, str(exc))
                    return self._json({"ok": True, "profile": saved})
                if path.startswith("/api/term/"):
                    pane_enc, _, action = path[len("/api/term/"):].rpartition("/")
                    if pane_enc and action in ("input", "control"):
                        pane_id = unquote(pane_enc)
                        if not self._term_target_ok(pane_id):
                            return self._error(400, "目前沒有這個 Terminal")
                        if action == "input":
                            return self._term_input(pane_id, self._body())
                        return self._term_control(pane_id, self._body())
                return self._error(404, "not found")
            except TimeoutError:
                raise
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client went away mid-request; nothing left to answer
            except tasks.TaskStorageError as exc:
                return self._error(503, str(exc))
            except agent_profiles.AgentProfileStorageError as exc:
                return self._error(503, str(exc))
            except Exception as exc:
                return self._error(500, f"內部錯誤：{type(exc).__name__}")

        def do_DELETE(self):
            if not self._host_ok():
                return self._error(HTTPStatus.MISDIRECTED_REQUEST, "invalid host")
            if not self._write_ok():
                return self._error(403, "forbidden")
            path = urlparse(self.path).path
            try:
                if path.startswith("/api/tasks/"):
                    task_id = path[len("/api/tasks/"):]
                    ok = tasks.delete_task(task_id)
                    if not ok:
                        return self._error(404, "找不到此任務卡或已刪除")
                    return self._json({"ok": True, "deleted": task_id})
                return self._error(404, "not found")
            except TimeoutError:
                raise
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client went away mid-request; nothing left to answer
            except tasks.TaskStorageError as exc:
                return self._error(503, str(exc))
            except agent_profiles.AgentProfileStorageError as exc:
                # Parity with do_GET/do_POST so a future DELETE endpoint for
                # profiles fails closed with 503 instead of a generic 500.
                return self._error(503, str(exc))
            except Exception as exc:
                return self._error(500, f"內部錯誤：{type(exc).__name__}")

        # terminal streaming ---------------------------------------------------

        def _term_target_ok(self, pane_id: str) -> bool:
            if not console.runtime.validate_target(pane_id):
                return False
            return (pane_id in console.live_targets()
                    or pane_id in console.live_targets(force=True))

        def _term_dims(self, body: dict) -> tuple[int, int]:
            def dim(value, default, low):
                try:
                    n = int(value)
                except (TypeError, ValueError):
                    return default
                return n if low <= n <= TERM_MAX_DIM else default
            return (dim(body.get("cols"), TERM_DEFAULT_COLS, TERM_MIN_DIM),
                    dim(body.get("rows"), TERM_DEFAULT_ROWS, TERM_MIN_ROWS))

        def _term_stream(self, pane_id: str, query: str):
            """Server-sent events: one 'data: <json>\\n\\n' per terminal frame.

            A plain <script>-less EventSource cannot carry the X-VBear
            header this endpoint requires (it has a side effect: attaching to
            the runtime), so the frontend must open this with fetch() and read
            the streamed body itself, not `new EventSource`.
            """
            if self.headers.get("X-VBear") != "1":
                return self._error(403, "forbidden")
            if not self._term_target_ok(pane_id):
                return self._error(404, "目前沒有這個 Terminal")
            q = parse_qs(query)
            cols, rows = self._term_dims({"cols": q.get("cols", [None])[0],
                                          "rows": q.get("rows", [None])[0]})
            sess = console.runtime.observe(pane_id, cols, rows)
            if sess is None:
                if not console.runtime.is_available():
                    return self._error(503, console.runtime_unavailable_message())
                return self._error(429, "同時開啟的 Terminal 過多，請先關閉其他分頁")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            current = sess
            try:
                while True:
                    live = console.runtime.get(pane_id)
                    if live is None:
                        break
                    if live is not current:
                        current = live  # a takeover/release swapped the session
                    try:
                        msg = current.queue.get(timeout=1)
                    except queue_mod.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    # A takeover or release can swap the pane's session while this
                    # call was blocked above; re-check before trusting what just
                    # came off `current`'s queue. A message from a session that has
                    # already been superseded — including its own end-of-session
                    # sentinel or synthetic "connection interrupted" close — belongs to
                    # the old session, not the pane, and must not reach the client
                    # as if the Terminal itself ended. The new session's own first
                    # frame (a full redraw) follows right behind on the next spin.
                    live = console.runtime.get(pane_id)
                    if live is not current:
                        if live is None:
                            break
                        current = live
                        continue
                    if msg is None:  # current is still live and it legitimately ended
                        break
                    payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
                    self.wfile.write(b"data: " + payload + b"\n\n")
                    self.wfile.flush()
            finally:
                # Stop `current` only if still the pane's live session
                # (identity check, releases control first).
                console.runtime.close_if_current(pane_id, current)

        def _term_input(self, pane_id: str, body: dict):
            sess = console.runtime.get(pane_id)
            if sess is None or sess.mode != "control":
                return self._error(409, "目前不是這個 Terminal 的操作者")
            text = body.get("text")
            if not isinstance(text, str) or not text:
                return self._error(400, "缺少輸入內容")
            if len(text.encode("utf-8")) > 4096:  # one input call, not a file upload
                return self._error(413, "單次輸入過長")
            ok = sess.send_input(text.encode("utf-8"))
            return self._json({"ok": ok})

        def _term_control(self, pane_id: str, body: dict):
            action = body.get("action")
            if action == "takeover":
                cols, rows = self._term_dims(body)
                sess = console.runtime.control(pane_id, cols, rows)
                if sess is None:
                    return self._error(503, console.runtime_unavailable_message())
                return self._json({"ok": True, "mode": sess.mode, "token": sess.token})
            if action == "release":
                sess = console.runtime.release(pane_id)
                return self._json({"ok": True, "mode": sess.mode if sess else None,
                                   "token": sess.token if sess else None})
            if action == "abandon":
                expected_token = body.get("token")
                if expected_token is not None and not isinstance(expected_token, str):
                    return self._error(400, "無效的 session token")
                stopped = console.runtime.abandon(pane_id, token=expected_token)
                curr = console.runtime.get(pane_id)
                return self._json({
                    "ok": True,
                    "action": "abandon",
                    "mode": curr.mode if curr else None,
                    "stopped": stopped,
                })
            if action == "resize":
                sess = console.runtime.get(pane_id)
                cols, rows = self._term_dims(body)
                ok = bool(sess) and sess.mode == "control" and sess.resize(cols, rows)
                return self._json({"ok": ok})
            return self._error(400, "未知的操作")

        # native sessions (R2 S3) -------------------------------------------

        def _native_open(self, body: dict):
            argv = body.get("argv")
            if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
                return self._error(400, "argv 必須是非空字串陣列（不經過 shell）")
            cwd = body.get("cwd") or str(Path.home())
            if not isinstance(cwd, str) or not os.path.isabs(cwd):
                return self._error(400, "cwd 必須是絕對路徑")
            real = Path(os.path.realpath(cwd))
            if not real.is_dir() or not real.is_relative_to(Path.home().resolve()):
                return self._error(400, "cwd 必須是家目錄內既存的資料夾")
            cols, rows = self._term_dims(body)
            try:
                info = console.runtime.create_session(
                    {"argv": argv, "cwd": str(real), "cols": cols, "rows": rows})
            except rt.native.NativeRuntimeUnavailable as exc:
                return self._error(503, str(exc))
            except rt.native.NativeRuntimeError as exc:
                return self._error(400, str(exc))
            console.store.live(force=True)  # new pane must be a live target at once
            return self._json({"ok": True, "session": info})

        def _terminal_open(self, body: dict):
            """Built-in terminal: the user's login shell in a folder they pick.

            The command is chosen here, never by the caller. It is an ordinary
            terminal under the user's account, with no sandbox; the UI says so."""
            extra = set(body) - {"cwd", "cols", "rows"}
            if extra:
                return self._error(400, f"不接受的欄位：{', '.join(sorted(extra))}")
            cwd = body.get("cwd") or "~"
            if not isinstance(cwd, str) or "\0" in cwd:
                return self._error(400, "資料夾必須是路徑字串")
            if cwd.strip().lower().startswith("file://"):
                return self._error(400, "請填資料夾路徑（例如 ~/projects/app），不是 file:// 連結")
            expanded = os.path.expanduser(cwd.strip())
            if not os.path.isabs(expanded):
                return self._error(400, "資料夾必須是絕對路徑，或以 ~ 開頭")
            try:
                real = Path(os.path.realpath(expanded))
                found = real.is_dir()
            except (OSError, ValueError):  # e.g. a name too long for the file system
                return self._error(400, "資料夾路徑無效")
            if not found:
                return self._error(400, "找不到這個資料夾")
            if not real.is_relative_to(Path.home().resolve()):
                return self._error(400, "資料夾必須在你的家目錄內")
            cols, rows = self._term_dims(body)
            try:
                info = console.runtime.create_session(
                    {"argv": [login_shell(), "-l"], "cwd": str(real), "cols": cols, "rows": rows,
                     "env": {"TERM": "xterm-256color"}, "kind": "shell"})
            except rt.native.NativeRuntimeUnavailable as exc:
                return self._error(503, str(exc))
            except rt.native.NativeRuntimeError as exc:
                return self._error(400, str(exc))
            console.store.live(force=True)
            return self._json({"ok": True, "session": info})

        # Profile-managed launch (R3 S0): preview, then confirm ---------------

        def _load_profile(self, profile_id):
            index = console.skill_index()
            known_roles = {r.get("role_id") for r in console.store.static().get("roles", [])
                           if r.get("role_id")}
            return agent_profiles.get_profile(profile_id, known_skills=set(index.keys()),
                                              known_roles=known_roles)

        def _agent_preview(self, body: dict):
            """What a Profile-managed launch would apply. Starts nothing. Raw
            argv, env, settings and credentials are not accepted here."""
            extra = set(body) - {"profile_id", "workdir", "commit", "network", "tool"}
            if extra:
                return self._error(400, f"不接受的欄位：{', '.join(sorted(extra))}")
            profile = self._load_profile(body.get("profile_id"))
            if profile is None:
                return self._error(404, "找不到此 Profile")
            tool = body.get("tool")
            if tool is not None and (tool == "shared" or tool != (profile.get("model") or {}).get("tool")):
                return self._error(400, "tool 必須與 Profile 的工具相符，且不可為 shared")
            workdir = body.get("workdir")
            if isinstance(workdir, str) and workdir.strip().lower().startswith("file://"):
                return self._error(400, "工作目錄請填資料夾路徑（例如 /Users/you/project），不是 file:// 連結")
            root = console.managed_root.resolve()
            if (not isinstance(workdir, str) or not os.path.isabs(workdir)
                    or not Path(os.path.realpath(workdir)).is_dir()
                    or not Path(os.path.realpath(workdir)).is_relative_to(root)):
                return self._error(400, "workdir 必須是家目錄內既存的資料夾")
            try:
                preview = console.previews().create(profile, workdir, body.get("commit", False),
                                                    body.get("network"))
            except agent_launch.PreviewError as exc:
                return self._json({"error": str(exc), "code": exc.code}, exc.status)
            return self._json({"ok": True, "preview": preview})

        def _agent_launch(self, body: dict):
            """Confirm a preview and start it. Anything that changed since the
            preview answers 409 and needs a new preview."""
            extra = set(body) - {"preview_id", "expected_settings_digest", "user_confirmed", "cols", "rows"}
            if extra:
                return self._error(400, f"不接受的欄位：{', '.join(sorted(extra))}")
            cols, rows = self._term_dims(body)
            try:
                result = console.previews().consume(
                    body.get("preview_id"), body.get("expected_settings_digest"),
                    body.get("user_confirmed"), self._load_profile, cols=cols, rows=rows)
            except agent_launch.PreviewError as exc:
                return self._json({"error": str(exc), "code": exc.code}, exc.status)
            console.store.live(force=True)  # the new pane must be a live target at once
            return self._json({"ok": True, "launch": result})

        def _native_close(self, sid: str):
            if not console.runtime.validate_target(sid):
                return self._error(400, "無效的 session id")
            closer = getattr(console.runtime, "close_session", None)
            result = closer(sid) if closer else ({} if console.runtime.close(sid) else None)
            console.store.live(force=True)
            if result is None:
                return self._error(404, "沒有這個 session 或無法關閉")
            body = {"ok": True, "closed": sid}
            if result.get("managed") is not None:
                body["managed"] = result["managed"]  # cleaned, or retained with the reason
            return self._json(body)

        # handlers ---------------------------------------------------------

        def _static(self, name: str):
            file = (WEB_ROOT / name).resolve()
            if not file.is_relative_to(WEB_ROOT):
                return self._error(404, "missing asset")
            try:
                body = file.read_bytes()
            except OSError:
                return self._error(404, "missing asset")
            ctype = mimetypes.guess_type(name)[0]
            if not ctype:
                if name.endswith("LICENSE"):
                    ctype = "text/plain"
                else:
                    ctype = "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8"
            self._headers(200, ctype, len(body))
            self.wfile.write(body)

        def _overview(self) -> dict:
            static = console.store.static()
            skills = static["skills"]
            counts: dict = {}
            for s in skills:
                counts.setdefault(s["tool"], {}).setdefault(s["activation"], 0)
                counts[s["tool"]][s["activation"]] += 1
            problems_active = [s["skill_id"] for s in skills
                               if s["activation"] == ACT_ACTIVE and (s["missing_files"] or s["warnings"])]
            recent = sorted((s for s in skills if s["activation"] == ACT_ACTIVE),
                            key=lambda s: s["mtime"], reverse=True)[:6]
            return {
                "generated_at": static["generated_at"],
                "scan_seconds": static["scan_seconds"],
                "age_seconds": round(time.time() - static["generated_at"]),
                "stale": time.time() - static["generated_at"] > STALE_AFTER_S,
                "config_corrupt": bool(console.store.conf.get("_corrupt")) or cfg.is_corrupt(),
                # Shown once after a Herdr-era config was switched to native, until acknowledged.
                "herdr_migration_notice": bool(console.store.conf.get("herdr_migrated_at"))
                and not console.store.conf.get("herdr_migration_acknowledged"),
                "counts": counts,
                "totals": {"skills": len(skills), "roles": len(static["roles"]),
                           "active": sum(1 for s in skills if s["activation"] == ACT_ACTIVE)},
                "sources": static["sources"],
                "problems": static["problems"],
                "facts": static["facts"],
                "skills_with_problems": problems_active,
                "recent_skill_ids": [s["skill_id"] for s in recent],
            }

        def _skills(self) -> dict:
            items = []
            notes = annotations.load()
            for s in console.store.static()["skills"]:
                item = {k: s.get(k) for k in SKILL_SUMMARY_FIELDS}
                item["annotation_key"] = annotations.key_for(s)
                item["annotation"] = notes.get(item["annotation_key"])
                when = s.get("when_to_use") or {}
                item["when_to_use"] = {"value": str(when.get("value") or "")[:SEARCH_EXCERPT_CHARS],
                                       "origin": when.get("origin")}
                items.append(item)
            return {"skills": items, "categories": console.store.static().get("category_table", [])}

        def _skill_detail(self, skill_id: str):
            skill = console.skill_index().get(skill_id)
            if not skill:
                return self._error(404, "找不到這個技能（索引可能已更新，請重新整理）")
            raw, raw_error = "", ""
            try:
                # re-check at read time: the file may have become a symlink since the scan
                file = document.contained_file(Path(skill["path"]), Path(skill.get("root") or "/-"))
                if file is None and not Path(skill["path"]).exists():
                    raw_error = "原始檔已不存在（索引可能已過期，請重新掃描）"
                elif file is None:
                    raw_error = "原始檔不在此技能的來源目錄內（符號連結），基於安全未載入"
                elif file.stat().st_size > MAX_FILE_BYTES:
                    raw_error = "檔案超過 256KB，未載入原文"
                else:
                    raw = document.redact(file.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                raw_error = f"無法讀取原始檔：{exc.strerror or exc}"
            index = console.skill_index()
            dups = [{"skill_id": d, "tool": index[d]["tool"], "scope": index[d]["scope"],
                     "activation": index[d]["activation"], "path": index[d]["path"],
                     "origin_package": index[d]["origin_package"]}
                    for d in skill.get("duplicate_of", []) if d in index]
            key = annotations.key_for(skill)
            armory_row = next((row for row in console.armory_view()["skills"]
                               if row["skill_id"] == skill_id), None)
            return self._json({
                "skill": skill,
                "equipped_by": (armory_row or {}).get("states", {}).get("equipped", []),
                "annotation_key": key,
                "annotation": annotations.load().get(key),
                "raw": raw,
                "raw_error": raw_error,
                "roles": console.roles_for_skill(skill_id),
                "usage": console.usage_for_skill(skill_id),
                "duplicates": dups,
            })

        def _skill_file(self, skill_id: str, ref: str):
            skill = console.skill_index().get(skill_id)
            if not skill:
                return self._error(404, "找不到這個技能")
            allowed = {r["ref"] for r in skill.get("referenced_files", []) if r.get("status") == "present"}
            if ref not in allowed:
                return self._error(403, "只能開啟此技能已驗證存在的引用檔")
            base = Path(skill["path"]).parent.resolve()
            root = Path(skill.get("root") or "/-")
            target = document.contained_file(base / ref, base)
            if target is None or document.contained_file(target, root) is None:
                return self._error(403, "引用檔不在技能目錄內")
            if target.stat().st_size > MAX_FILE_BYTES:
                return self._json({"ref": ref, "text": "", "error": "檔案超過 256KB，未載入"})
            data = target.read_bytes()
            if b"\x00" in data[:4096]:
                return self._json({"ref": ref, "text": "", "error": "二進位檔，不顯示內容"})
            return self._json({"ref": ref, "text": document.redact(data.decode("utf-8", "replace"))})

        def _roles(self) -> dict:
            index = console.skill_index()
            roles = []
            for role in console.store.static()["roles"]:
                linked = [index[i] for i in role.get("skill_link_ids", []) if i in index]
                roles.append({**role, "skills": [
                    {"skill_id": s["skill_id"], "name": s["name"], "invoke_name": s["invoke_name"],
                     "scope": s["scope"], "description": (s["description"] or {}).get("value")}
                    for s in linked]})
            return {"roles": roles}

        def _config_view(self) -> dict:
            conf = console.store.conf
            res = {"config": {k: v for k, v in conf.items() if not k.startswith("_")},
                   "state_dir": str(cfg.state_dir()),
                   "runtime_socket": console.runtime.binary(),
                   "runtime_kind_active": "native"}
            if conf.get("_corrupt") or cfg.is_corrupt():
                res["corrupt"] = True
            return res

        def _config_update(self, body: dict) -> dict:
            with console.lock:
                if cfg.is_corrupt():
                    raise ValueError(cfg.corrupt_message())
                conf = cfg.load()
                for key in CONFIG_WRITABLE & body.keys():
                    value = body[key]
                    if key == "usage_days":
                        try:
                            value = max(1, min(365, int(value)))
                        except (TypeError, ValueError):
                            continue
                    if key == "project_roots":
                        value = _valid_project_roots(value)
                    if key == "language" and (not isinstance(value, str) or value not in LANGUAGES):
                        raise ValueError("不支援的語言設定")
                    if key in ("advanced_mode", "usage_enabled"):
                        value = bool(value)
                    if key == "herdr_migration_acknowledged":
                        value = bool(value)
                    conf[key] = value
                toggles = body.get("source_enabled")
                if isinstance(toggles, dict):
                    for src in conf.get("sources", []):
                        if src["source_id"] in toggles:
                            src["enabled"] = bool(toggles[src["source_id"]])
                cfg.save(conf)
                console.store.set_conf(conf)
            return {"ok": True, "config": conf, "rescan_needed": "source_enabled" in body
                    or "project_roots" in body}

        def _agent_builder_catalog(self) -> dict:
            """Read-only catalog used by the Agent Builder UI.

            The console already knows the role catalog (from `self.store`),
            the skill catalog, the supported tool ids, the permission key
            / value enums and the model configuration shape. This view just
            decorates that into the exact form the UI needs to render
            selectors with no follow-up fetches: a Profession list pulled
            from the read-only AgentRole catalog (C-D1 — strictly separate
            from AgentProfile), a Tool list drawn from `agent_profiles.
            KNOWN_TOOLS` (C-D2 / C-D3 — the catalog IS the registry, no
            external list), a Skill Loadout entry per skill with the
            minimum fields the picker needs, and the four-key Permission
            Intent surface (C-D4). No `permission_intents` value is ever
            `enforce`/`force`/`allow_unattended`: those would imply the
            key has authority over something, which it does not
            (permission values are intent-only — Phase C-D6).
            """
            index = console.skill_index()
            skills_for_picker = []
            for s in index.values():
                desc = (s.get("description") or {}).get("value") or ""
                skills_for_picker.append({
                    "skill_id": s["skill_id"],
                    "name": s["name"],
                    "invoke_name": s.get("invoke_name", ""),
                    "tool": s.get("tool", ""),
                    "scope": s.get("scope", ""),
                    "activation": s.get("activation", ""),
                    "excerpt": desc[:140],
                })
            skills_for_picker.sort(key=lambda x: (x["tool"], x["name"].lower()))

            roles = []
            for r in console.store.static().get("roles", []):
                roles.append({
                    "role_id": r.get("role_id"),
                    "name": r.get("name"),
                    "tool": r.get("tool"),
                    "kind": r.get("kind"),
                    "skill_link_count": len(r.get("skill_link_ids") or []),
                    "skill_link_basis": r.get("skill_link_basis"),
                })

            return {
                "ok": True,
                "tools": sorted(agent_profiles.KNOWN_TOOLS),
                "permission_keys": list(agent_profiles.PERMISSION_KEYS),
                "permission_values": list(agent_profiles.PERMISSION_VALUES),
                "permission_intent_only": True,
                "model_id_max_length": agent_profiles.MAX_MODEL_ID,
                "max_profiles": agent_profiles.MAX_PROFILES,
                "max_skills_per_profile": agent_profiles.MAX_SKILLS_PER_PROFILE,
                "professions": roles,
                "skills": skills_for_picker,
                # Honest disclosure: equipped != loaded, intent != enforce.
                # This text is shown to the user verbatim, never as an HTML
                # permission warning or as an enforced UI block.
                "disclosures": [
                    "Equipped Skill Loadout ≠ Loaded into any running session. "
                    "Saving a Profile never starts, restarts, or injects anything.",
                    "Permission Intents are intent-only and are NOT enforced. "
                    "They are descriptive records of what this Profile is composed "
                    "for; the underlying CLI tools' actual authority comes from "
                    "their own per-call rules; only a Profile-managed launch applies "
                    "a verified sandbox configuration.",
                    "Agent Profiles are stored only inside this console's own state "
                    "directory. They never write to ~/.codex, ~/.claude, third-"
                    "party skill/role sources, or any third-party marketplace cache.",
                ],
            }

        def _governance_view(self) -> dict:
            return {
                "ok": True,
                "version": "3.0.0-foundation",
                "compiler_active": False,
                "effective_context_enabled": False,
                "notice": "G/P 層於本階段為唯讀介面骨架展示，尚未進行全域治理遷移，無 Policy Compiler 或自動注入。",
                "global": {
                    "source": "全域規則骨架 (Global Skeleton)",
                    "source_type": "skeleton_read_only",
                    "status": "唯讀骨架 (未遷移 / 無主動編譯)",
                    "description": "系統與專案底線規範，適用於所有 Agent",
                    "categories": [
                        {
                            "name": "Security & Secrets",
                            "rules": [
                                {"id": "SEC-001", "name": "Protect Secrets", "type": "Mandatory",
                                 "description": "API Key、Private Key 等機密資訊嚴禁寫入日誌、提示詞或程式碼庫。"},
                                {"id": "SEC-002", "name": "Require Production Approval", "type": "Mandatory",
                                 "description": "生產環境變更、發布、支付、對外通訊需具體人類批准。"},
                            ],
                        },
                        {
                            "name": "Operations & Git",
                            "rules": [
                                {"id": "GIT-001", "name": "Deny Force Push Main", "type": "Mandatory",
                                 "description": "嚴禁對 main 分支進行強制推送 (force push)。"},
                                {"id": "ACT-001", "name": "Destructive Operations Require Confirmation", "type": "Mandatory",
                                 "description": "不可逆刪除、權限變更等破壞性操作需人類明確確認。"},
                            ],
                        },
                        {
                            "name": "Evidence & Verification",
                            "rules": [
                                {"id": "EVI-001", "name": "Important Conclusions Require Evidence", "type": "Mandatory",
                                 "description": "重要變更與交付成果須有可驗證之實測證據，未實測不可稱 verified。"},
                            ],
                        },
                    ],
                },
                "project": {
                    "source": "專案契約骨架 (Project Contract)",
                    "source_type": "skeleton_read_only",
                    "status": "唯讀展示 (未編譯)",
                    "description": "目前專案之架構、建置、測試與邊界契約",
                    "contract": {
                        "stack": "Python 3.13+ / Vanilla JS / xterm.js vendored / VBear native runtime",
                        "runtime": "Localhost only (127.0.0.1:7788)",
                        "security": "Strict CSP, Safe DOM textContent, Same-Origin + X-VBear: 1",
                        "tests": "python3 -B -m unittest discover -s tests -q && node tests/frontend/*.cjs",
                        "boundaries": "Zero external pip dependencies, zero CDN, one writer per worktree",
                    },
                },
            }

    return Handler


def _valid_project_roots(value) -> list[str]:
    """Absolute directories (a leading ~ is allowed), never / or the home
    directory or anything above it: project discovery lists one level of
    children, and those would turn it into a scan of the whole account."""
    if not isinstance(value, list) or len(value) > MAX_PROJECT_ROOTS:
        raise ValueError(f"project_roots 必須是最多 {MAX_PROJECT_ROOTS} 個路徑的清單")
    out: list[str] = []
    home = HOME().resolve()
    for raw in value:
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 1024 or "\x00" in raw:
            raise ValueError("project_roots 只能包含路徑字串")
        text = raw.strip()
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ValueError(f"project_roots 必須是絕對路徑：{text}")
        real = path.resolve()
        if real == Path(real.anchor) or home.is_relative_to(real):
            raise ValueError(f"不能把根目錄或家目錄本身設為專案目錄：{text}")
        if text not in out:
            out.append(text)
    return out


def serve(port: int | None = None, open_browser: bool = False) -> None:
    conf = cfg.load()
    port = int(port or conf.get("port") or cfg.DEFAULT_PORT)
    console = Console(port)
    console.store.static()  # load cached index or perform the first scan
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(console))
    url = f"http://127.0.0.1:{port}/"
    write_access_files(port, console.auth_token)
    print(f"VBear 已啟動：{url}（只接受本機連線，Ctrl+C 結束）", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: open_in_browser(port)).start()

    def _stop(signum, frame):  # SIGTERM (the app quitting, kill) cleans up like Ctrl+C
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if console._previews is not None:
            console._previews.close()  # unconfirmed previews: remove their prepared state
        console.runtime.close_all()  # no orphaned child processes on exit
        httpd.server_close()
        remove_access_files(console.auth_token)


# Access token handoff -------------------------------------------------------
# server.token lets local tools (the launcher, the macOS app) authenticate;
# open.html lets a browser do it without the token ever appearing in a
# command line or a URL that leaves this machine's owner-only state directory.

def token_path() -> Path:
    return cfg.state_dir() / "server.token"


def opener_path() -> Path:
    return cfg.state_dir() / "open.html"


def write_access_files(port: int, token: str | None) -> None:
    if token is None:
        return
    cfg.write_private(token_path(), json.dumps({"port": port, "token": token, "pid": os.getpid()}))
    target = json.dumps(f"http://127.0.0.1:{port}/#auth={token}")
    cfg.write_private(opener_path(),
                      "<!doctype html><meta charset=utf-8><title>VBear</title>"
                      f"<script>location.replace({target})</script>"
                      "<p>正在開啟 VBear…</p>\n")


def read_access_token(port: int) -> str | None:
    try:
        data = json.loads(token_path().read_text())
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("port") == port and isinstance(data.get("token"), str):
        return data["token"]
    return None


def remove_access_files(token: str | None) -> None:
    """Remove the handoff files if they still belong to this server."""
    if token is None:
        return
    try:
        if json.loads(token_path().read_text()).get("token") != token:
            return
    except (OSError, ValueError, AttributeError):
        return
    for p in (token_path(), opener_path()):
        try:
            p.unlink()
        except OSError:
            pass


def open_in_browser(port: int) -> None:
    import webbrowser
    if read_access_token(port) and opener_path().is_file():
        webbrowser.open(opener_path().as_uri())
    else:
        webbrowser.open(f"http://127.0.0.1:{port}/")
