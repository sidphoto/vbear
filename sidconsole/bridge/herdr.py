"""Bridge to a running herdr server through its own CLI.

The herdr CLI is the plugin API (docs: plugins.mdx), so the console never
touches herdr internals. Every call is an argv list (no shell), bounded by a
timeout, and failures are returned as data so the UI can say "unknown"
instead of pretending.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

# Must not start with "-" (herdr would read it as an option such as --help).
# `herdr agent focus` takes exactly one argument and has no "--" separator
# (src/cli/agent.rs agent_focus), so the id itself has to be safe.
_TARGET = re.compile(r"[A-Za-z0-9:_][A-Za-z0-9:_\-]{0,63}")
TIMEOUT_S = 5


def binary(configured: str = "") -> str | None:
    for candidate in (configured, os.environ.get("HERDR_BIN_PATH", "")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("herdr")


def _run(bin_path: str | None, *args: str) -> dict:
    if not bin_path:
        return {"ok": False, "error": "找不到 herdr 執行檔"}
    try:
        proc = subprocess.run(
            [bin_path, *args],
            capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"herdr {' '.join(args)} 逾時"}
    except OSError as exc:
        return {"ok": False, "error": f"無法執行 herdr：{exc}"}
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        detail = (proc.stderr or out or "").strip().splitlines()[:1]
        return {"ok": False, "error": f"herdr {' '.join(args)} 失敗：{detail[0] if detail else proc.returncode}"}
    try:
        payload = json.loads(out)
    except ValueError:
        return {"ok": False, "error": "herdr 回傳的不是 JSON"}
    if "error" in payload:
        return {"ok": False, "error": str(payload["error"])[:200]}
    return {"ok": True, "data": payload.get("result", payload)}


def snapshot(configured_bin: str = "") -> dict:
    """Agents, workspaces and tabs in one call set. Partial failures are kept."""
    bin_path = binary(configured_bin)
    agents = _run(bin_path, "agent", "list")
    workspaces = _run(bin_path, "workspace", "list")
    tabs = _run(bin_path, "tab", "list")
    version = None
    if bin_path:
        try:
            proc = subprocess.run([bin_path, "--version"], capture_output=True, text=True,
                                  timeout=TIMEOUT_S, check=False, stdin=subprocess.DEVNULL)
            version = proc.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            version = None
    problems = [r["error"] for r in (agents, workspaces, tabs) if not r["ok"]]
    return {
        "available": agents["ok"],
        "binary": bin_path,
        "version": version,
        "agents": (agents.get("data") or {}).get("agents", []) if agents["ok"] else [],
        "workspaces": (workspaces.get("data") or {}).get("workspaces", []) if workspaces["ok"] else [],
        "tabs": (tabs.get("data") or {}).get("tabs", []) if tabs["ok"] else [],
        "problems": problems,
    }


def focus(target: str, configured_bin: str = "") -> dict:
    """Bring an existing agent terminal to the front in herdr.

    Navigation only: it changes which pane herdr shows and sends nothing to
    the agent. The target is validated before it reaches argv.
    """
    if not valid_target(target):
        return {"ok": False, "error": "無效的目標識別碼"}
    return _run(binary(configured_bin), "agent", "focus", target)


def valid_target(target) -> bool:
    return isinstance(target, str) and _TARGET.fullmatch(target) is not None
