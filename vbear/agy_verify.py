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

from . import claude_verify, config as cfg
from .runtime import agy_chat_env, agy_kept, chat_engines, cli_versions


class AgyChatVerifier(claude_verify.ChatVerifier):
    LABEL = "AGY"
    TIMEOUT = 2700                     # seconds: the check stops itself well before (a step takes at most four minutes)

    def _report_path(self, version: str) -> Path:
        return claude_verify.reports_dir() / f"agy-{version}-chat.json"

    def _argv(self, binary: str, out: Path) -> list[str]:
        # --agy: the check runs the COPY that was just made of the AGY on the search path (``_run_check``), not that AGY itself: the file
        # that is checked is the file that is kept (ADR 0021).
        return [sys.executable, "-B", "-m", "vbear.boundary_check", "--mode", chat_engines.by_tool("agy").check_mode, "--shared",
                "--agy", binary, "--out", str(out)]

    _staged = None

    def _stage(self, base, version: str) -> agy_kept.Staged:
        """Copy the AGY on the search path (the same safety checks as when a chat looks for it); it must still be ``version``."""
        source = agy_chat_env.locate_binary()
        seen = agy_chat_env.read_version(source)
        if seen != version:
            raise agy_chat_env.AgyRefused("version_changed", f"目前的 AGY 是 {seen}，不是 {version}；請重新整理後再驗證。")
        return agy_kept.stage(base, source, version)

    def _run_check(self, binary: str, version: str) -> None:
        base = cfg.state_dir()
        try:
            staged = self._stage(base, version)
        except agy_chat_env.AgyRefused as exc:
            return self._finish("error", f"沒有開始檢查：{exc}")
        except OSError as exc:
            return self._finish("error", f"沒有開始檢查：保存一份給聊天用的 AGY 時出了問題（{exc.strerror or type(exc).__name__}）")
        self._staged = staged
        try:
            super()._run_check(staged.path, version)
        finally:
            self._staged = None
            agy_kept.discard(base, staged)                # nothing stays behind unless the copy was kept (then its folder has a new name)

    def _keep(self, binary: str, version: str) -> tuple[str | None, str]:
        """The check passed on ``binary``, the staged copy. The pass record must name that very file (SHA-256 and size, from the copy
        VBear made and from the check, which hashed it itself); then it is kept as the copy of ``version`` and the oldest beyond two go."""
        staged, base = self._staged, cfg.state_dir()
        record = cli_versions.local_agy_chat_kept_records(base).get(version)
        if staged is None or binary != staged.path or record != {"sha256": staged.sha256, "size": staged.size}:
            return ("檢查說通過了，但通過紀錄裡檔案的 SHA-256 與 VBear 保存的那一份不一樣（或紀錄裡沒有），所以沒有保存。請看報告。"), ""
        try:
            removed = agy_kept.promote(base, staged, version)
        except agy_chat_env.AgyRefused as exc:
            return f"檢查通過了，但沒辦法保存這一份：{exc}", ""
        except OSError as exc:
            return f"檢查通過了，但沒辦法保存這一份（{exc.strerror or type(exc).__name__}）。", ""
        gone = f"，並移除了比較舊的 {'、'.join(removed)}" if removed else ""
        return None, f"；VBear 也保存了這一份 AGY{gone}，之後 AGY 自己更新時，聊天會先用它（直到 VBear 認得新版並通過檢查）"

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
