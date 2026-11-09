"""「驗證聊天」 for an AGY chat (P46-4): runs ``python -m vbear.boundary_check --mode agy-chat --shared`` in a child process and reports
how it went, the way codex_verify.CodexChatVerifier does for Codex.

The check records a pass itself, in ``<state>/agy-chat-verified.json`` with its report; this class then asks ``cli_versions`` whether the
version really counts, so a pass is never taken from the child's words. It uses the AGY the full-mode terminal would find (the version the
chat support answer names) and the person's own Google plan: about twenty short model calls, not billed apart, the shared folder part
included. It takes longer than the others (AGY's turns are slow, and one step waits to see that a stopped command did not finish), so its
run may last longer. One verification runs at a time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import claude_verify
from .runtime import agy_chat_env, chat_engines, cli_versions


class AgyChatVerifier(claude_verify.ChatVerifier):
    LABEL = "AGY"
    TIMEOUT = 2700                     # seconds: the check stops itself well before (a step takes at most four minutes)

    def _report_path(self, version: str) -> Path:
        return claude_verify.reports_dir() / f"agy-{version}-chat.json"

    def _argv(self, binary: str, out: Path) -> list[str]:
        # No --agy: the check takes the AGY the support answer names (found along the terminal's search path), as the Codex check does.
        return [sys.executable, "-B", "-m", "vbear.boundary_check", "--mode", chat_engines.by_tool("agy").check_mode, "--shared",
                "--out", str(out)]

    def _verified(self) -> tuple[str, ...]:
        return cli_versions.agy_chat_verified_versions()

    def _unfinished(self, report: Path) -> str:
        """The check says in its report why it could not run (not logged in, hooks, a folder it will not use...)."""
        try:
            data = json.loads(report.read_text())
        except (OSError, ValueError):
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, str) and error.strip():
            return "驗證沒有完成：" + error.strip()[:300]
        return "驗證沒有完成（模型可能沒有回應，或登入失效）"

    def _finish(self, result: str, message: str, **extra) -> None:
        agy_chat_env.invalidate()                         # the support answer is looked at again, not read from its cache
        super()._finish(result, message, **extra)
