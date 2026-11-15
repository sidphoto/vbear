"""Fail-closed compatibility checks for the supported agent CLIs.

This is a version compatibility check, not binary authentication. A program
that can emit the expected version string is not thereby proven genuine.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from . import daemon


# Versions whose sandbox boundary was verified (oldest first). Callers cannot
# supply or override them; adding one is a code change backed by a passing
# tools/verify_claude_boundary.py run and docs/evidence/<engine>-<version>.md.
VERIFIED_VERSIONS = MappingProxyType({
    "codex": ("0.159.2",),
    "claude": ("2.1.286", "2.1.291", "2.1.292", "2.1.296"),
})
# The newest verified version per engine (where one fixed install is needed).
EXPECTED_VERSIONS = MappingProxyType({k: v[-1] for k, v in VERIFIED_VERSIONS.items()})
# Claude Code versions verified on this machine with the boundary check
# (vbear/boundary_check.py), recorded in the state directory.
LOCAL_VERIFIED_FILE = "claude-verified.json"
# The terminal-title checks of the interactive verification run; judged by
# vbear/title_check.py from a report's own events.
from ..title_check import TITLE_CHECKS, report_title_passes  # noqa: E402
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+\Z")


def local_verified_versions() -> dict:
    """{version: record} of Claude Code versions that passed the boundary
    check here. Unreadable or malformed entries count as not verified."""
    from .. import config as cfg
    try:
        data = json.loads((cfg.state_dir() / LOCAL_VERIFIED_FILE).read_text())
    except (OSError, ValueError):
        return {}
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, dict):
        return {}
    return {v: r for v, r in versions.items()
            if isinstance(v, str) and _VERSION_RE.match(v) and isinstance(r, dict) and r.get("passed") is True
            and all(isinstance(r.get(k), str) and r.get(k) for k in ("report", "binary", "verified_at"))
            and _report_backs(r, v)}


def local_title_verified_versions() -> dict:
    """{version: record} whose terminal-title check passed on this Mac. A
    record written before titles were checked, or a malformed one, counts
    as title-unverified."""
    out = {}
    for v, r in local_verified_versions().items():
        title = r.get("title")
        if (isinstance(title, dict) and title.get("passed") is True
                and isinstance(title.get("report"), str) and _title_report_backs(title["report"], v)):
            out[v] = r
    return out


def _title_report_backs(path: str, version: str) -> bool:
    """The report at ``path`` shows a passing title check for ``version``,
    re-judged from its own events (the written summary alone never counts)."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return False
    return report_title_passes(data, version)


def _report_backs(record: dict, version: str) -> bool:
    """Every recorded report exists, is the check's output, passed, and is for
    this version. ``reports`` must be a non-empty {mode: path} map and
    ``report`` one of its paths; any other shape means "not verified"."""
    reports = record.get("reports")
    if not (isinstance(reports, dict) and reports
            and all(isinstance(k, str) and isinstance(p, str) and p for k, p in reports.items())):
        return False
    if record.get("report") not in reports.values():
        return False
    for path in reports.values():
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError, TypeError):
            return False
        if not (isinstance(data, dict) and data.get("passed") is True and data.get("claude_version") == version):
            return False
    return True


def verified_versions(engine: str) -> tuple[str, ...]:
    """Built-in verified versions, plus (Claude Code only) local ones."""
    built_in = VERIFIED_VERSIONS.get(engine, ())
    if engine != "claude":
        return built_in
    return built_in + tuple(v for v in sorted(local_verified_versions()) if v not in built_in)


# Claude Code versions whose stream mode (design 2.2) passed
# ``boundary_check --mode stream``: built in only with a code change backed by
# docs/evidence/claude-code-<version>-stream.md, or recorded on this Mac by
# the probe. Kept apart from the headless/interactive records. A version that
# is neither cannot start a stream session; there is no "start unverified".
# 2.1.292: boundary_check --mode stream passed 2026-10-08
# (docs/evidence/claude-code-2.1.292-stream.md).
# 2.1.296: the same, 2026-10-12 (docs/evidence/claude-code-2.1.296-stream.md), after Claude Code's own update left
# the machine without any stream-verified version.
STREAM_VERIFIED_VERSIONS: tuple[str, ...] = ("2.1.292", "2.1.296")
LOCAL_STREAM_VERIFIED_FILE = "claude-stream-verified.json"
_STREAM_REPORT_MAX = 8 << 20


def local_stream_verified_versions() -> dict:
    """{version: record} whose stream probe passed here, each backed by its
    report (mode "stream", passed, this version), re-read every time."""
    from .. import config as cfg, strictjson
    rec = strictjson.load_owned_object(cfg.state_dir() / LOCAL_STREAM_VERIFIED_FILE, strictjson.MANIFEST)
    versions = rec.value.get("versions") if rec.ok else None
    if not isinstance(versions, dict):
        return {}
    out = {}
    for v, r in versions.items():
        if not (isinstance(v, str) and _VERSION_RE.match(v) and isinstance(r, dict) and r.get("passed") is True
                and isinstance(r.get("report"), str) and isinstance(r.get("verified_at"), str)):
            continue
        report = strictjson.load_owned_object(r["report"], strictjson.Limits(_STREAM_REPORT_MAX, 2_000_000, 64,
                                                                             _STREAM_REPORT_MAX))
        data = report.value if report.ok else {}
        if data.get("mode") == "stream" and data.get("passed") is True and data.get("claude_version") == v:
            out[v] = r
    return out


def stream_verified_versions() -> tuple[str, ...]:
    built_in = STREAM_VERIFIED_VERSIONS
    return built_in + tuple(v for v in sorted(local_stream_verified_versions()) if v not in built_in)


# Claude Code versions whose chat mode (P36) passed ``boundary_check --mode chat`` on this Mac. None is built in: the
# check is still to be written (P36-2), and until a version passes it no chat process starts.
CHAT_VERIFIED_VERSIONS: tuple[str, ...] = ()
LOCAL_CHAT_VERIFIED_FILE = "claude-chat-verified.json"
SHARED_PASSED = "passed"          # what a chat-check report says of its shared-folder part when it went well (P43-2)


def _local_chat_record(file_name: str, mode: str, version_key: str, shared: bool = False, *, state=None, with_report: bool = False) -> dict:
    """{version: record} of a chat-check record file in the state folder: each entry passed, names its report and a time,
    and the report (read again, owned by this user) is of ``mode``, passed, and names the same version under ``version_key``.
    ``shared`` (P43-2) also wants the report to say ``"shared": "passed"`` (the part of the check made with the shared folder).
    ``state`` is another state folder than the configured one (P62: the kept AGY is looked for in the folder it is kept in);
    ``with_report`` makes each value ``(record, report)``."""
    from .. import config as cfg, strictjson
    rec = strictjson.load_owned_object((cfg.state_dir() if state is None else Path(state)) / file_name, strictjson.MANIFEST)
    versions = rec.value.get("versions") if rec.ok else None
    if not isinstance(versions, dict):
        return {}
    out = {}
    for v, r in versions.items():
        if not (isinstance(v, str) and _VERSION_RE.match(v) and isinstance(r, dict) and r.get("passed") is True
                and isinstance(r.get("report"), str) and isinstance(r.get("verified_at"), str)):
            continue
        report = strictjson.load_owned_object(r["report"], strictjson.Limits(_STREAM_REPORT_MAX, 2_000_000, 64,
                                                                             _STREAM_REPORT_MAX))
        data = report.value if report.ok else {}
        if data.get("mode") == mode and data.get("passed") is True and data.get(version_key) == v:
            if shared and data.get("shared") != SHARED_PASSED:
                continue
            out[v] = (r, data) if with_report else r
    return out


def local_chat_verified_versions() -> dict:
    """{version: record} whose chat check passed here, each backed by its report (mode "chat", passed, this
    version), re-read every time. The same shape as the stream record."""
    return _local_chat_record(LOCAL_CHAT_VERIFIED_FILE, "chat", "claude_version")


def chat_verified_versions() -> tuple[str, ...]:
    built_in = CHAT_VERIFIED_VERSIONS
    return built_in + tuple(v for v in sorted(local_chat_verified_versions()) if v not in built_in)


def chat_shared_verified_versions() -> tuple[str, ...]:
    """Claude Code versions whose chat check passed here AND whose report says the shared-folder part passed too (P43-2). A report
    from before v0.17.1 does not say so: a version it verified is still good for chats, and unchecked for the shared folder."""
    return tuple(sorted(_local_chat_record(LOCAL_CHAT_VERIFIED_FILE, "chat", "claude_version", shared=True), key=_version_key))


def chat_unverified_text(version: str) -> str:
    """The one wording for "this Claude Code has no chat-mode verification"."""
    supported = chat_verified_versions()
    if not supported:
        return (f"Claude Code {version} 的聊天模式還沒有通過驗證，VBear 目前沒有任何通過聊天驗證的版本。"
                "處理方式：先執行聊天模式的驗證（會花一點額度）。")
    listed = "、".join(sorted(supported, key=_version_key))
    return (f"Claude Code {version} 的聊天模式還沒有通過驗證。已通過的版本：{listed}。"
            f"處理方式：安裝其中一個版本，或先為 {version} 執行聊天模式的驗證（會花一點額度）。")


# Codex versions whose chat mode (P38, ADR 0005) passed ``boundary_check --mode codex-chat`` on this Mac. None is built in:
# a version counts only when this Mac's own record names a report that mode "codex-chat" wrote, that passed, and that names
# the same version under ``codex_version``. Kept apart from Claude Code's chat record and from the review's list
# (codex_constants.VERIFIED_VERSIONS): passing one says nothing about the others.
CODEX_CHAT_VERIFIED_VERSIONS: tuple[str, ...] = ()
LOCAL_CODEX_CHAT_VERIFIED_FILE = "codex-chat-verified.json"


def local_codex_chat_verified_versions() -> dict:
    """{version: record} whose Codex chat check passed here, each backed by its report, re-read every time."""
    return _local_chat_record(LOCAL_CODEX_CHAT_VERIFIED_FILE, "codex-chat", "codex_version")


def codex_chat_verified_versions() -> tuple[str, ...]:
    built_in = CODEX_CHAT_VERIFIED_VERSIONS
    return built_in + tuple(v for v in sorted(local_codex_chat_verified_versions()) if v not in built_in)


def codex_chat_shared_verified_versions() -> tuple[str, ...]:
    """The same for Codex: the chat check and its shared-folder part (P43-2)."""
    return tuple(sorted(_local_chat_record(LOCAL_CODEX_CHAT_VERIFIED_FILE, "codex-chat", "codex_version", shared=True),
                        key=_version_key))


def codex_chat_unverified_text(version: str) -> str:
    """The one wording for "this Codex has no chat-mode verification"."""
    supported = codex_chat_verified_versions()
    if not supported:
        return (f"Codex {version} 的聊天模式還沒有通過驗證，VBear 目前沒有任何通過聊天驗證的 Codex 版本。"
                "處理方式：先執行聊天模式的驗證（會用到你的 ChatGPT 方案，約 8 到 10 次很短的對話）。")
    listed = "、".join(sorted(supported, key=_version_key))
    return (f"Codex {version} 的聊天模式還沒有通過驗證。已通過的版本：{listed}。"
            f"處理方式：安裝其中一個版本，或先為 {version} 執行聊天模式的驗證（會用到你的 ChatGPT 方案）。")


# AGY versions whose chat mode (P46, ADR 0012) passed ``boundary_check --mode agy-chat`` on this Mac. None is built in: a version
# counts only when this Mac's own record names a report that mode "agy-chat" wrote, that passed, and that names the same version
# under ``agy_version``. Kept apart from the other two records: passing one says nothing about the others.
AGY_CHAT_VERIFIED_VERSIONS: tuple[str, ...] = ()
LOCAL_AGY_CHAT_VERIFIED_FILE = "agy-chat-verified.json"


def local_agy_chat_verified_versions() -> dict:
    """{version: record} whose AGY chat check passed here, each backed by its report, re-read every time."""
    return _local_chat_record(LOCAL_AGY_CHAT_VERIFIED_FILE, "agy-chat", "agy_version")


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def local_agy_chat_kept_records(state=None) -> dict:
    """{version: {"sha256", "size"}} of the AGY versions whose pass says WHICH file was checked (P62, ADR 0021): the record has a SHA-256 (64
    lower-case hex digits) and a size, and the report it names says the same two (``agy_sha256``, ``agy_size``). A pass recorded before
    v0.26.0, or one whose record and report disagree, is not here: it says a version and no file. ``state`` is the state folder the kept
    copies are in (the configured one when None). Re-read every time."""
    out = {}
    for version, (record, report) in _local_chat_record(LOCAL_AGY_CHAT_VERIFIED_FILE, "agy-chat", "agy_version", state=state,
                                                        with_report=True).items():
        sha, size = record.get("sha256"), record.get("size")
        if (isinstance(sha, str) and _SHA256_RE.match(sha) and isinstance(size, int) and not isinstance(size, bool) and size > 0
                and report.get("agy_sha256") == sha and report.get("agy_size") == size):
            out[version] = {"sha256": sha, "size": size}
    return out


def agy_chat_verified_versions() -> tuple[str, ...]:
    built_in = AGY_CHAT_VERIFIED_VERSIONS
    return built_in + tuple(v for v in sorted(local_agy_chat_verified_versions()) if v not in built_in)


def agy_chat_shared_verified_versions() -> tuple[str, ...]:
    """The same for AGY: the chat check and its shared-folder part."""
    return tuple(sorted(_local_chat_record(LOCAL_AGY_CHAT_VERIFIED_FILE, "agy-chat", "agy_version", shared=True),
                        key=_version_key))


def agy_chat_unverified_text(version: str) -> str:
    """The one wording for "this AGY has no chat-mode verification"."""
    supported = agy_chat_verified_versions()
    if not supported:
        return (f"AGY {version} 的聊天模式還沒有通過驗證，VBear 目前沒有任何通過聊天驗證的 AGY 版本。"
                "處理方式：先執行聊天模式的驗證（會用到你的 Google 方案，約十幾次很短的對話）。")
    listed = "、".join(sorted(supported, key=_version_key))
    return (f"AGY {version} 的聊天模式還沒有通過驗證。已通過的版本：{listed}。"
            f"處理方式：安裝其中一個版本，或先為 {version} 執行聊天模式的驗證（會用到你的 Google 方案）。")


def shared_verified(engine, version) -> bool:
    """Whether this version of the AI tool a chat ``engine`` ("claude-chat", "codex-chat", "agy-chat") runs has passed the chat check
    with the shared folder (P43-2). Anything else, a bad name or no report included, is no."""
    if not (isinstance(version, str) and _VERSION_RE.match(version)):
        return False
    if engine == "claude-chat":
        return version in chat_shared_verified_versions()
    if engine == "codex-chat":
        return version in codex_chat_shared_verified_versions()
    if engine == "agy-chat":
        return version in agy_chat_shared_verified_versions()
    return False


def shared_unverified_text(engine: str, version: str) -> str:
    """The one wording for "this version has not passed the check with the shared folder": which tool and version, which versions
    have, and what to do (the check costs Claude Code a few cents; Codex uses the person's ChatGPT plan, AGY the Google plan)."""
    name = {"codex-chat": "Codex", "agy-chat": "AGY"}.get(engine, "Claude Code")
    supported = {"codex-chat": codex_chat_shared_verified_versions,
                 "agy-chat": agy_chat_shared_verified_versions}.get(engine, chat_shared_verified_versions)()
    head = f"{name} {version} 還沒有通過含共用資料夾的檢查。"
    if supported:
        head += "已通過的版本：" + "、".join(sorted(supported, key=_version_key)) + "。"
    cost = {"codex-chat": "會用到你的 ChatGPT 方案，約十幾次很短的對話",
            "agy-chat": "會用到你的 Google 方案，約十幾次很短的對話"}.get(engine, "約 US$0.01")
    return head + f"處理方式：按聊天頁的「檢查」（{cost}），或先把這位員工的共用資料夾關掉。"


def _version_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (0,)


def stream_unverified_text(version: str, supported: tuple[str, ...] | None = None) -> str:
    """The one wording for "this Claude Code has no stream-mode verification":
    what was found, which versions VBear supports (generated from the lists
    above, never typed here) and what can be done about it. Facts only."""
    supported = stream_verified_versions() if supported is None else supported
    if not supported:
        return (f"Claude Code {version} 的串流模式還沒有通過驗證。VBear 目前沒有任何支援串流模式的版本。"
                "處理方式：等 VBear 更新。")
    listed = "、".join(sorted(supported, key=_version_key))
    return (f"Claude Code {version} 的串流模式還沒有通過驗證。VBear 目前支援串流模式的版本：{listed}。"
            f"處理方式：安裝其中一個支援的版本，或等 VBear 更新、支援 {version}。")


def stream_support(version: str | None, why: str = "") -> dict:
    """What the screen shows before the executor is started: the detected
    version, the supported list and the state.

      verified    the detected version is on the list;
      unverified  it is not (message says what can be done);
      unknown     the version could not be read (message says why).

    Never a guess: an unreadable version is "unknown", not "unverified"."""
    supported = stream_verified_versions()
    shown = sorted(supported, key=_version_key)
    if version is None:
        return {"state": "unknown", "detected": None, "supported": shown,
                "message": f"讀不到 Claude Code 的版本（{why or '原因不明'}），無法確認串流模式是否已通過驗證"}
    if version in supported:
        return {"state": "verified", "detected": version, "supported": shown, "message": ""}
    return {"state": "unverified", "detected": version, "supported": shown,
            "message": stream_unverified_text(version, supported)}
# In 0.159.2, --ignore-user-config and --ephemeral are accepted by `codex exec`
# but rejected by the interactive TUI command. Managed PTY launches require the
# interactive command, so they stay disabled until a pinned build supports both.
CODEX_INTERACTIVE_FLAGS_SUPPORTED = False

VERSION_PROBE_TIMEOUT_SECONDS = 8.0  # bounds the wait only; a busy Mac can be slow to start a CLI
VERSION_PROBE_MAX_OUTPUT_BYTES = 4096
_CLEANUP_GRACE_SECONDS = 0.15
_SAFE_ENV_KEYS = ("USER", "LOGNAME", "PATH", "TERM", "LANG", "HOME")
_VERSION_OUTPUT = MappingProxyType({
    "codex": re.compile(r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)"),
    "claude": re.compile(r"([0-9]+\.[0-9]+\.[0-9]+) \(Claude Code\)"),
})


@dataclass(frozen=True)
class VersionCheckResult:
    """Structured compatibility result suitable for a later preview layer."""

    engine: str
    expected_version: str | None
    observed_version: str | None
    binary_path: str | None
    compatible: bool
    state: str
    reason: str
    error_code: str | None = None
    verified: bool = False  # True only when the observed version is on a verified list
    _binary_identity: tuple[int, ...] | None = field(default=None, repr=False, compare=False)

    def as_dict(self) -> dict:
        """Return only reviewable result fields; omit local stat internals."""
        return {
            "engine": self.engine,
            "expected_version": self.expected_version,
            "observed_version": self.observed_version,
            "binary_path": self.binary_path,
            "compatible": self.compatible,
            "state": self.state,
            "reason": self.reason,
            "error_code": self.error_code,
            "verified": self.verified,
        }


class VersionAssertionError(RuntimeError):
    """A version assertion failed with a stable, structured error code."""

    def __init__(self, result: VersionCheckResult):
        self.result = result
        self.code = result.error_code or "version_assertion_failed"
        super().__init__(result.reason)


def _blocked(
    engine: object,
    code: str,
    reason: str,
    *,
    expected: str | None = None,
    observed: str | None = None,
    binary_path: str | None = None,
    identity: tuple[int, ...] | None = None,
) -> VersionCheckResult:
    return VersionCheckResult(
        engine=engine if isinstance(engine, str) else "",
        expected_version=expected,
        observed_version=observed,
        binary_path=binary_path,
        compatible=False,
        state="blocked",
        reason=reason,
        error_code=code,
        _binary_identity=identity,
    )


def _file_identity(path: str) -> tuple[int, ...]:
    info = os.stat(path, follow_symlinks=True)
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise OSError("binary is not a regular executable file")
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _probe_environment() -> dict[str, str]:
    """Use the daemon's safe environment shape, then force OS identity."""
    source = daemon.build_env()
    identity = pwd.getpwuid(os.getuid()).pw_name
    if not identity:
        raise RuntimeError("OS user identity is unavailable")
    env = {key: source[key] for key in _SAFE_ENV_KEYS if source.get(key)}
    env["USER"] = identity
    env["LOGNAME"] = identity
    return env


def _canonical_cwd(cwd: str | os.PathLike[str] | None) -> str:
    if cwd is None:
        raise ValueError("cwd is required")
    raw = os.fspath(cwd)
    if not isinstance(raw, str) or not raw or "\0" in raw or not os.path.isabs(raw):
        raise ValueError("cwd must be an absolute directory")
    canonical = os.path.realpath(raw)
    if not os.path.isdir(canonical):
        raise ValueError("cwd must be an existing directory")
    return canonical


def _resolve_binary(binary: str | os.PathLike[str] | None, engine: str,
                    cwd: str, env: dict[str, str]) -> str:
    selector = engine if binary is None else os.fspath(binary)
    if not isinstance(selector, str) or not selector or "\0" in selector:
        raise ValueError("binary selector is invalid")
    if os.path.isabs(selector):
        candidate = selector
    elif os.sep in selector:
        candidate = os.path.join(cwd, selector)
    else:
        found = shutil.which(selector, path=env.get("PATH", ""))
        if found is None:
            raise FileNotFoundError(selector)
        candidate = found
    return os.path.realpath(candidate)


def _terminate_process_group(proc: subprocess.Popen, grace: float = _CLEANUP_GRACE_SECONDS) -> None:
    """Stop the isolated probe group, including children that kept its pipes."""
    pgid = proc.pid  # start_new_session=True makes the child its own group.
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        pass

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        except OSError:
            break
        time.sleep(0.01)
    else:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            pass

    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def _wait_without_reaping(proc: subprocess.Popen, deadline: float) -> int | None:
    """Read the leader's exit status without freeing its PID before group cleanup.

    Keeping the leader unreaped prevents its process-group id from being
    recycled between observing exit and terminating any remaining children.
    """
    if not hasattr(os, "waitid"):
        raise OSError("waitid(WNOWAIT) is required for safe probe cleanup")
    while True:
        info = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if info is not None:
            if info.si_code == os.CLD_EXITED:
                return info.si_status
            return -info.si_status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.01, remaining))


def _run_probe(binary_path: str, engine: str, cwd: str, env: dict[str, str],
               timeout: float) -> tuple[int | None, bytes, str | None]:
    argv = ([binary_path, "--version"] if engine == "codex"
            else [binary_path, "--safe-mode", "--version"])
    return run_capture(argv, cwd, env, timeout, VERSION_PROBE_MAX_OUTPUT_BYTES)


def run_capture(argv: list[str], cwd: str, env: dict[str, str], timeout: float,
                max_bytes: int) -> tuple[int | None, bytes, str | None]:
    """Run ``argv`` in its own session with no stdin, read stdout and stderr
    (each at most ``max_bytes``), and end its whole group afterwards.
    (exit code, stdout, error): the error is ours ("probe_timeout",
    "output_too_large"), never the program's own stderr."""
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        start_new_session=True,
        bufsize=0,
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    try:
        assert proc.stdout is not None and proc.stderr is not None
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, bytes(output["stdout"]), "probe_timeout"
            for key, _ in selector.select(min(remaining, 0.1)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                except OSError:
                    # Not the end of the output (Codex 3d A4): what was read so
                    # far may be a prefix of something longer.
                    return None, bytes(output["stdout"]), "read_error"
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buf = output[key.data]
                if len(buf) + len(chunk) > max_bytes:
                    return None, bytes(output["stdout"]), "output_too_large"
                buf.extend(chunk)
        exit_code = _wait_without_reaping(proc, deadline)
        if exit_code is None:
            return None, bytes(output["stdout"]), "probe_timeout"
        return exit_code, bytes(output["stdout"]), None
    finally:
        selector.close()
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
        _terminate_process_group(proc)


def _parse_version(engine: str, stdout: bytes) -> tuple[str | None, str | None]:
    try:
        text = stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, "invalid_utf8"
    if text.endswith("\n"):
        text = text[:-1]
    match = _VERSION_OUTPUT[engine].fullmatch(text)
    if match is None:
        return None, "invalid_output"
    return match.group(1), None


def check_cli_version(
    engine: str,
    binary: str | os.PathLike[str] | None = None,
    *,
    cwd: str | os.PathLike[str],
    timeout: float = VERSION_PROBE_TIMEOUT_SECONDS,
    allow_unverified: bool = False,
) -> VersionCheckResult:
    """Probe a supported CLI and return a preview-ready structured result.

    Only the fixed, engine-specific ``--version`` argv is executed. ``binary``
    is supplied by trusted upper-level resolution or defaults to PATH lookup.
    """
    if not isinstance(engine, str) or engine not in VERIFIED_VERSIONS:
        return _blocked(engine, "unsupported_engine", "不支援此 Agent 引擎")
    verified = verified_versions(engine)
    expected = "、".join(verified)  # shown when the version does not match
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not (0 < timeout <= VERSION_PROBE_TIMEOUT_SECONDS)):
        return _blocked(engine, "invalid_probe_options", "版本檢查逾時設定無效", expected=expected)
    try:
        canonical_cwd = _canonical_cwd(cwd)
    except (OSError, TypeError, ValueError):
        return _blocked(engine, "invalid_cwd", "版本檢查工作目錄無效", expected=expected)
    try:
        env = _probe_environment()
    except Exception:
        return _blocked(
            engine, "identity_unavailable", "無法取得本機使用者身分", expected=expected)
    try:
        binary_path = _resolve_binary(binary, engine, canonical_cwd, env)
        identity = _file_identity(binary_path)
    except FileNotFoundError:
        return _blocked(engine, "binary_not_found", "找不到指定的 Agent CLI", expected=expected)
    except (OSError, TypeError, ValueError):
        return _blocked(
            engine, "binary_not_executable", "Agent CLI 不是可執行的一般檔案", expected=expected)

    try:
        exit_code, stdout, probe_error = _run_probe(
            binary_path, engine, canonical_cwd, env, float(timeout))
    except (OSError, ValueError, subprocess.SubprocessError):
        return _blocked(engine, "probe_failed", "Agent CLI 版本檢查無法執行", expected=expected,
                        binary_path=binary_path, identity=identity)
    if probe_error:
        reason = {
            "probe_timeout": "Agent CLI 版本檢查逾時",
            "output_too_large": "Agent CLI 版本輸出超出上限",
        }.get(probe_error, "Agent CLI 版本檢查失敗")
        return _blocked(engine, probe_error, reason, expected=expected,
                        binary_path=binary_path, identity=identity)
    if exit_code != 0:
        return _blocked(engine, "probe_failed", "Agent CLI 版本檢查回傳失敗", expected=expected,
                        binary_path=binary_path, identity=identity)
    observed, parse_error = _parse_version(engine, stdout)
    if parse_error:
        reason = ("Agent CLI 版本輸出不是有效 UTF-8" if parse_error == "invalid_utf8"
                  else "Agent CLI 版本輸出格式無效")
        return _blocked(engine, parse_error, reason, expected=expected,
                        binary_path=binary_path, identity=identity)
    # A genuine Claude Code release that nobody verified yet may still run when the
    # caller asks for it; the result says so and the labels must say "unverified".
    unverified_ok = allow_unverified and engine == "claude"
    if observed not in verified and not unverified_ok:
        return _blocked(engine, "version_mismatch", "Agent CLI 版本不在已驗證的版本清單",
                        expected=expected, observed=observed, binary_path=binary_path,
                        identity=identity)
    try:
        after_identity = _file_identity(binary_path)
    except OSError:
        return _blocked(engine, "binary_changed_during_probe", "版本檢查期間 Agent CLI 檔案改變",
                        expected=expected, observed=observed, binary_path=binary_path,
                        identity=identity)
    if after_identity != identity:
        return _blocked(engine, "binary_changed_during_probe", "版本檢查期間 Agent CLI 檔案改變",
                        expected=expected, observed=observed, binary_path=binary_path,
                        identity=identity)
    is_verified = observed in verified
    return VersionCheckResult(
        engine=engine,
        expected_version=observed if is_verified else expected,
        observed_version=observed,
        binary_path=binary_path,
        compatible=True,
        state="compatible" if is_verified else "unverified",
        reason="version_matches_baseline" if is_verified else "version_not_verified",
        verified=is_verified,
        _binary_identity=identity,
    )


def assert_cli_version(
    engine: str,
    binary: str | os.PathLike[str] | None = None,
    *,
    cwd: str | os.PathLike[str],
    timeout: float = VERSION_PROBE_TIMEOUT_SECONDS,
    allow_unverified: bool = False,
) -> VersionCheckResult:
    """Return a compatible result or raise a structured version error."""
    result = check_cli_version(engine, binary, cwd=cwd, timeout=timeout,
                               allow_unverified=allow_unverified)
    if not result.compatible:
        raise VersionAssertionError(result)
    return result


def ensure_binary_unchanged(result: VersionCheckResult) -> None:
    """Reject a checked binary that disappeared or changed before launch."""
    if not result.compatible or not result.binary_path or result._binary_identity is None:
        raise VersionAssertionError(_blocked(
            result.engine, "version_assertion_missing", "缺少有效的版本檢查結果",
            expected=result.expected_version, observed=result.observed_version,
            binary_path=result.binary_path))
    try:
        identity = _file_identity(result.binary_path)
    except OSError:
        identity = None
    if identity != result._binary_identity:
        raise VersionAssertionError(_blocked(
            result.engine, "binary_changed_before_launch", "啟動前 Agent CLI 檔案已變更或消失",
            expected=result.expected_version, observed=result.observed_version,
            binary_path=result.binary_path))


def assert_agent_version(engine: str, binary: str | os.PathLike[str] | None = None,
                         *, cwd: str | os.PathLike[str]) -> VersionCheckResult:
    """Compatibility alias for internal launch guards."""
    return assert_cli_version(engine, binary, cwd=cwd)


# ---- the display-only version cache (v0.25.4) ----------------------------------------------------------------------------
#
# A page that only shows which version is installed (the chat list's ``support``, the start-up page's read of Claude Code's chat
# state) used to start the AI tool with ``--version`` on every read. ``check_cli_version_for_display`` keeps a successful
# reading for DISPLAY_CACHE_TTL_S seconds. It is for showing only: starting a chat, a verification, a dispatch or a terminal must
# call ``check_cli_version`` / ``assert_cli_version`` / ``ensure_binary_unchanged`` (never this function), and those never read
# this cache. docs/SECURITY-MODEL.md, "Display-only version cache (v0.25.4)", says why that is safe; guards 23a and 23b in
# tests/test_autonomy_guard.py hold the two rules: no launch path names this function or the cache, and the key carries the
# file's identity.
DISPLAY_CACHE_TTL_S = 30.0       # the same as ai_tool_status.CACHE_TTL_S (a test holds them equal)
DISPLAY_CACHE_MAX = 16
_display_cache: dict = {}        # key -> (time it was read, result without the file identity)
_display_lock = threading.Lock()


def invalidate_display_cache() -> None:
    """Forget every kept reading: the next display reads the tools again (the 「重新檢查」 button, a finished chat check, ...)."""
    with _display_lock:
        _display_cache.clear()


def _display_key(engine, binary, cwd, allow_unverified) -> tuple | None:
    """The cache key, or None when any part of it cannot be established (then nothing is read from or kept in the cache). The
    file is stat'ed again on every call, so a program that was replaced (an automatic update) has another identity and another key."""
    if not isinstance(engine, str) or engine not in VERIFIED_VERSIONS:
        return None
    try:
        canonical_cwd = _canonical_cwd(cwd)
        binary_path = _resolve_binary(binary, engine, canonical_cwd, _probe_environment())
        identity = _file_identity(binary_path)
    except Exception:
        return None
    return (engine, binary_path, identity, canonical_cwd, verified_versions(engine), bool(allow_unverified))


def check_cli_version_for_display(
    engine: str,
    binary: str | os.PathLike[str] | None = None,
    *,
    cwd: str | os.PathLike[str],
    timeout: float = VERSION_PROBE_TIMEOUT_SECONDS,
    allow_unverified: bool = False,
    clock=None,
) -> VersionCheckResult:
    """``check_cli_version`` for a page that only shows the version; NEVER for anything that starts a program.

    A reading that found a version is kept for DISPLAY_CACHE_TTL_S seconds under (engine, resolved path, file identity, folder,
    the versions the engine recognizes now, allow_unverified); a program that changed has another identity, so it is read again
    at once. A reading that did not find a version (timeout, too much output, unreadable, the file changed while it was read) is
    never kept. The result has no file identity, so it cannot be handed to ``ensure_binary_unchanged`` (that refuses it).
    ``clock`` is a function returning seconds (tests give one); the default is ``time.monotonic``."""
    now = (clock or time.monotonic)()
    key = _display_key(engine, binary, cwd, allow_unverified)
    if key is not None:
        with _display_lock:
            kept = _display_cache.get(key)
            if kept is not None and 0 <= now - kept[0] < DISPLAY_CACHE_TTL_S:
                return kept[1]
    result = check_cli_version(engine, binary, cwd=cwd, timeout=timeout, allow_unverified=allow_unverified)
    shown = replace(result, _binary_identity=None)
    if (key is not None and result.observed_version is not None and result._binary_identity == key[2]
            and result.error_code != "binary_changed_during_probe"):
        with _display_lock:
            _display_cache[key] = (now, shown)
            for old in [k for k, v in _display_cache.items() if not 0 <= now - v[0] < DISPLAY_CACHE_TTL_S]:
                del _display_cache[old]
            while len(_display_cache) > DISPLAY_CACHE_MAX:
                del _display_cache[min(_display_cache, key=lambda k: _display_cache[k][0])]
    return shown


__all__ = [
    "EXPECTED_VERSIONS",
    "VERIFIED_VERSIONS",
    "TITLE_CHECKS",
    "local_title_verified_versions",
    "local_verified_versions",
    "verified_versions",
    "VersionAssertionError",
    "VersionCheckResult",
    "assert_agent_version",
    "assert_cli_version",
    "check_cli_version",
    "check_cli_version_for_display",
    "ensure_binary_unchanged",
    "invalidate_display_cache",
]
