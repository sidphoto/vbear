"""「驗證聊天」 for a Codex chat (P38-5): runs ``python -m vbear.boundary_check --mode codex-chat`` in a child process and
reports how it went, the way claude_verify.ChatVerifier does for Claude Code.

The check records a pass itself, in ``<state>/codex-chat-verified.json`` with its report; this class then asks
``cli_versions`` whether the version really counts, so a pass is never taken from the child's words. It uses the Codex the
vendor's installer left (the newest version, which is the one the chat support answer names) and the person's own ChatGPT
plan: about fourteen short model calls, not billed apart. One verification runs at a time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import claude_verify
from .runtime import cli_versions, codex_chat_env


class CodexChatVerifier(claude_verify.ChatVerifier):
    LABEL = "Codex"

    def _report_path(self, version: str) -> Path:
        return claude_verify.reports_dir() / f"codex-{version}-chat.json"

    def _argv(self, binary: str, out: Path) -> list[str]:
        # No --codex: the check takes the newest Codex the vendor's installer left, the one the support answer names.
        return [sys.executable, "-B", "-m", "vbear.boundary_check", "--mode", "codex-chat", "--out", str(out)]

    def _verified(self) -> tuple[str, ...]:
        return cli_versions.codex_chat_verified_versions()

    def _unfinished(self, report: Path) -> str:
        """The check says in its report why it could not run (not logged in, a folder it will not use...)."""
        try:
            data = json.loads(report.read_text())
        except (OSError, ValueError):
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, str) and error.strip():
            return "驗證沒有完成：" + error.strip()[:300]
        return "驗證沒有完成（模型可能沒有回應，或登入失效）"

    def _finish(self, result: str, message: str, **extra) -> None:
        codex_chat_env.invalidate()                       # the support answer is looked at again, not read from its cache
        super()._finish(result, message, **extra)
