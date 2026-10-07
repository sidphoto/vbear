"""「驗證這個版本」: run the boundary check on the Claude Code that a managed
launch would use, and record a pass in ~/.vbear/claude-verified.json.

The check is vbear/boundary_check.py, run twice in a child process
(headless, then interactive in a PTY); each run makes one small model call
with the user's own Claude login. A version counts as verified only when both
runs pass every check. One verification runs at a time.

The interactive run also checks the terminal title (activity evidence); that
result is recorded next to the boundary result, under ``title``. A title
failure never undoes a boundary pass: the version still launches as verified,
and its working/waiting state just stays unknown.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config as cfg
from .runtime import cli_versions

MODES = ("headless", "interactive")
RUN_TIMEOUT = 600  # per mode; the check itself stops a session after 240 s
PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)


def reports_dir() -> Path:
    return cfg.state_dir() / "verifications"


class ClaudeVerifier:
    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict = {"running": False}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, binary: str, version: str) -> dict:
        """Start verifying `binary` (reported as `version`); returns the status."""
        with self._lock:
            if self._state.get("running"):
                return dict(self._state)
            self._state = {"running": True, "version": version, "binary": binary,
                           "started_at": time.time(), "step": MODES[0], "result": None}
        threading.Thread(target=self._run, args=(binary, version), daemon=True,
                         name="vbear-claude-verify").start()
        return self.status()

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    def _run(self, binary: str, version: str) -> None:
        try:
            self._run_checks(binary, version)
        except Exception as exc:  # never leave the status stuck at "running"
            self._finish("error", f"驗證中斷：{type(exc).__name__}")

    def _run_checks(self, binary: str, version: str) -> None:
        out_dir = reports_dir()
        cfg.ensure_state_dir()
        out_dir.mkdir(mode=0o700, exist_ok=True)
        reports = {}
        for mode in MODES:
            self._set(step=mode)
            out = out_dir / f"claude-{version}-{mode}.json"
            try:
                proc = subprocess.run(
                    [sys.executable, "-B", "-m", "vbear.boundary_check", "--claude", binary,
                     "--mode", mode, "--out", str(out)],
                    cwd=PACKAGE_PARENT, stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, timeout=RUN_TIMEOUT)
                code = proc.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                return self._finish("error", f"{mode} 無法完成：{type(exc).__name__}")
            reports[mode] = str(out)
            if code != 0:
                failed = _failed_checks(out)
                why = ("、".join(failed) + " 沒有通過") if failed else (
                    "驗證沒有完成（模型可能沒有執行探測，或登入失效）")
                return self._finish("failed", f"{mode}：{why}", reports=reports, failed=failed)
            try:
                report = json.loads(out.read_text())
            except (OSError, ValueError):
                return self._finish("error", f"{mode} 的報告無法讀取")
            if not isinstance(report, dict) or report.get("passed") is not True:
                return self._finish("error", f"{mode} 的報告格式不符")
            if report.get("claude_version") != version:
                return self._finish("error", "驗證期間 Claude Code 版本改變了，請重新驗證")
        title = _title_result(Path(reports["interactive"]))
        record_pass(version, binary, reports, title=title)
        title_note = ("終端標題也通過，這台 Mac 可以判斷「工作中／等你回覆」" if title["passed"]
                      else "終端標題沒有通過（" + "、".join(title["failed"]) + "），狀態會維持未知")
        self._finish("passed", f"Claude Code {version} 通過啟動邊界檢查；{title_note}",
                     reports=reports, title_result="passed" if title["passed"] else "failed",
                     title_failed=title["failed"])

    def _finish(self, result: str, message: str, **extra) -> None:
        self._set(running=False, result=result, message=message, finished_at=time.time(), **extra)


def _failed_checks(report: Path) -> list[str]:
    try:
        data = json.loads(report.read_text())
    except (OSError, ValueError):
        return []
    checks = data.get("checks") if isinstance(data, dict) else None
    if not isinstance(checks, dict):
        return []
    return [name for name, c in checks.items() if not (isinstance(c, dict) and c.get("pass"))]


def _title_result(report: Path) -> dict:
    """The interactive report's title check, as recorded: passed, failed check names."""
    try:
        data = json.loads(report.read_text())
    except (OSError, ValueError):
        data = None
    title = data.get("title") if isinstance(data, dict) else None
    checks = title.get("checks") if isinstance(title, dict) else None
    if not isinstance(checks, dict) or not checks:
        return {"passed": False, "failed": ["title_check_missing"], "report": str(report)}
    failed = [n for n, c in checks.items() if not (isinstance(c, dict) and c.get("pass") is True)]
    return {"passed": title.get("passed") is True and not failed, "failed": failed, "report": str(report)}


def record_pass(version: str, binary: str, reports: dict, title: dict | None = None) -> None:
    path = cfg.state_dir() / cli_versions.LOCAL_VERIFIED_FILE
    try:
        data = json.loads(path.read_text())
        versions = data.get("versions") if isinstance(data, dict) else None
    except (OSError, ValueError):
        versions = None
    versions = dict(versions) if isinstance(versions, dict) else {}
    versions[version] = {
        "passed": True,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "binary": binary,
        "report": reports.get("interactive") or next(iter(reports.values()), ""),
        "reports": reports,
        "tool": "vbear.boundary_check",
        # Separate from the boundary result; absent in records written before
        # titles were checked, which therefore count as title-unverified.
        "title": ({"passed": title["passed"] is True, "failed": list(title.get("failed") or []),
                   "report": title["report"]} if title else {"passed": False, "failed": ["not_checked"]}),
    }
    cfg.write_private(path, json.dumps({"versions": versions}, ensure_ascii=False, indent=1) + "\n")
