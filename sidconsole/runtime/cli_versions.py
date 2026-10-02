"""Fail-closed compatibility checks for the supported agent CLIs.

This is a version compatibility check, not binary authentication. A program
that can emit the expected version string is not thereby proven genuine.
"""

from __future__ import annotations

import os
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from . import daemon


# These values are the reviewed spike baselines. Callers cannot supply or
# override them; a future baseline change must be made in trusted code here.
EXPECTED_VERSIONS = MappingProxyType({
    "codex": "0.159.2",
    "claude": "2.1.286",
})

VERSION_PROBE_TIMEOUT_SECONDS = 3.0
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
                    chunk = b""
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buf = output[key.data]
                if len(buf) + len(chunk) > VERSION_PROBE_MAX_OUTPUT_BYTES:
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
) -> VersionCheckResult:
    """Probe a supported CLI and return a preview-ready structured result.

    Only the fixed, engine-specific ``--version`` argv is executed. ``binary``
    is supplied by trusted upper-level resolution or defaults to PATH lookup.
    """
    if not isinstance(engine, str) or engine not in EXPECTED_VERSIONS:
        return _blocked(engine, "unsupported_engine", "不支援此 Agent 引擎")
    expected = EXPECTED_VERSIONS[engine]
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
    if observed != expected:
        return _blocked(engine, "version_mismatch", "Agent CLI 版本與核准基準不符",
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
    return VersionCheckResult(
        engine=engine,
        expected_version=expected,
        observed_version=observed,
        binary_path=binary_path,
        compatible=True,
        state="compatible",
        reason="version_matches_baseline",
        _binary_identity=identity,
    )


def assert_cli_version(
    engine: str,
    binary: str | os.PathLike[str] | None = None,
    *,
    cwd: str | os.PathLike[str],
    timeout: float = VERSION_PROBE_TIMEOUT_SECONDS,
) -> VersionCheckResult:
    """Return a compatible result or raise a structured version error."""
    result = check_cli_version(engine, binary, cwd=cwd, timeout=timeout)
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


__all__ = [
    "EXPECTED_VERSIONS",
    "VersionAssertionError",
    "VersionCheckResult",
    "assert_agent_version",
    "assert_cli_version",
    "check_cli_version",
    "ensure_binary_unchanged",
]
