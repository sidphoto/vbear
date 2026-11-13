"""P59-2 fixtures: three fake AI tools (Claude Code, Codex, AGY) in a temporary HOME, each writing one line to a log whenever it is
started, so a test can count how many times the console started each tool. Nothing here runs a real AI tool: the search path,
the Claude Code versions folder and the Codex releases folder are all inside the temporary folder, and ``assert_private`` fails if
any of the three programs a lookup finds is not.
"""
from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path
from unittest import mock

from vbear import admin_policy
from vbear.runtime import agy_chat_env, cli_versions, codex_chat_env

CLAUDE_VERSION = "2.1.322"
CODEX_VERSION = "0.159.2"
AGY_VERSION = "1.5.6"

SCRIPTS = {
    "claude": '[ "$*" = "--safe-mode --version" ] && echo "%s (Claude Code)"\nexit 0\n' % CLAUDE_VERSION,
    "codex": '[ "$*" = "--version" ] && echo "codex-cli %s"\nexit 0\n' % CODEX_VERSION,
    "agy": '[ "$*" = "--version" ] && echo "%s"\nexit 0\n' % AGY_VERSION,
}


class Fakes:
    """Context manager. ``calls(tool)`` is the list of argument lines the tool was started with, oldest first."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="v59f.")
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "h"
        self.state = self.home / ".vbear"
        self.bin = self.root / "bin"
        self.logs = self.root / "logs"
        self._patches = []

    def _script(self, path: Path, tool: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        log = self.logs / tool
        path.write_text(f'#!/bin/sh\necho "$*" >> {log}\n' + SCRIPTS[tool])
        path.chmod(0o700)

    def __enter__(self):
        for d in (self.home, self.state, self.bin, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.claude = self.home / ".local/share/claude/versions" / CLAUDE_VERSION
        arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        self.codex = self.home / ".codex/packages/standalone/releases" / f"{CODEX_VERSION}-{arch}-apple-darwin/bin/codex"
        self.agy = self.bin / "agy"
        self._script(self.claude, "claude")
        self._script(self.codex, "codex")
        self._script(self.agy, "agy")
        env = {"HOME": str(self.home), "VBEAR_HOME": str(self.state), "VBEAR_RUNTIME_AUTOSTART": "0",
               "PATH": f"{self.bin}:/usr/bin:/bin"}
        self._patches = [
            mock.patch.dict(os.environ, env),
            mock.patch.object(cli_versions, "chat_verified_versions", return_value=(CLAUDE_VERSION,)),
            mock.patch.object(cli_versions, "codex_chat_verified_versions", return_value=(CODEX_VERSION,)),
            mock.patch.object(cli_versions, "agy_chat_verified_versions", return_value=(AGY_VERSION,)),
            mock.patch.object(admin_policy, "check_claude", return_value=admin_policy.PolicyCheck(True)),
            mock.patch.object(admin_policy, "check_codex", return_value=admin_policy.PolicyCheck(True)),
            mock.patch.object(admin_policy, "check_agy", return_value=admin_policy.PolicyCheck(True)),
        ]
        for p in self._patches:
            p.start()
        self.reset_caches()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        self.reset_caches()
        self._tmp.cleanup()
        return False

    @staticmethod
    def reset_caches():
        codex_chat_env.invalidate()
        agy_chat_env.invalidate()
        invalidate = getattr(cli_versions, "invalidate_display_cache", None)
        if invalidate:
            invalidate()

    def calls(self, tool: str) -> list[str]:
        try:
            return (self.logs / tool).read_text().splitlines()
        except FileNotFoundError:
            return []

    def counts(self) -> dict:
        return {tool: len(self.calls(tool)) for tool in ("claude", "codex", "agy")}

    def assert_private(self):
        """Every program a console lookup would pick is under the temporary folder (never a real AI tool)."""
        from vbear.runtime import native
        assert str(native._pinned_claude_chat_binary()).startswith(str(self.root)), "claude is not the fake"
        assert str(agy_chat_env.locate_binary()).startswith(str(self.root)), "agy is not the fake"
        assert str(codex_chat_env.pinned_binary()[0]).startswith(str(self.root)), "codex is not the fake"
