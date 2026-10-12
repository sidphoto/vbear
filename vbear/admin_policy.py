"""Refuse to launch when an administrator policy or system config layer exists.

Claude Code applies managed settings above ``--settings`` (design 2.1), so a
policy could override the API endpoint VBear pins; Codex reads its system
and managed layers even with ``--ignore-user-config`` (design 5.2). VBear
does not parse these sources or judge what they set: if any known source
exists, the launch is refused and the screen names it. A source whose
existence cannot be established (``lstat`` fails for any reason other than
"not there") refuses too.

The source lists are per-version constants taken from the vendors'
documentation (read 2026-10-08) and change only through a code review. A
version without a list cannot launch. Whole directories are listed where the
vendor keeps several policy files together, which is stricter than naming
each file and does not miss a file a later version adds:

  Claude Code  /Library/Application Support/ClaudeCode   (managed-settings.json,
               managed-settings.d/, managed-mcp.json, the managed CLAUDE.md)
               managed preferences domain com.anthropic.claudecode
  Codex        /etc/codex   (managed_config.toml, requirements.toml, config.toml)
               managed preferences domain com.openai.codex

Managed preferences are looked up in ``/Library/Managed Preferences/`` and in
every per-user directory under it.

Claude Code's server-managed settings are fetched from claude.ai and are no
local file. Its cache, ``~/.claude/remote-settings.json`` (in the HOME the
executor runs with), refuses the launch when present (design v29.3, 2.1);
that cannot prove the source absent (a ``-p`` run applies such settings
without caching them), so the rest is a residual risk the user accepts per
flow (user decision 2026-10-08, design 10).

"Not there" means ``lstat`` raised FileNotFoundError, nothing else: a parent
that is a regular file (ENOTDIR), a permission error or any other failure
leaves the question open, and the launch is refused.

Tests pass another ``root`` instead of ``/`` and another ``home``.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field

MANAGED_PREFS = "Library/Managed Preferences"
MANAGED_PREFS_MAX_ENTRIES = 10_000

_CLAUDE = {"paths": ("Library/Application Support/ClaudeCode",), "domain": "com.anthropic.claudecode",
           "home_paths": (".claude/remote-settings.json",)}
_CODEX = {"paths": ("etc/codex",), "domain": "com.openai.codex", "home_paths": ()}

# 2.1.296: the same sources as 2.1.292 (the vendor's documented managed-settings locations have not changed; to be
# re-read from the vendor documentation by the reviewer, docs/evidence/claude-code-2.1.296-stream.md).
CLAUDE_SOURCES = {"2.1.292": _CLAUDE, "2.1.296": _CLAUDE}
CODEX_SOURCES = {"0.160.0": _CODEX}


@dataclass
class PolicyCheck:
    ok: bool
    found: list[str] = field(default_factory=list)       # sources that exist
    problems: list[str] = field(default_factory=list)    # could not be established

    def reason(self) -> str:
        if self.ok:
            return ""
        parts = [f"存在管理員政策或系統設定：{p}" for p in self.found]
        parts += self.problems
        return "；".join(parts) + "。請使用者或系統管理員處理後再啟動。"


def _exists(path: str) -> bool:
    """lstat: True if anything is there, False only for FileNotFoundError;
    any other failure (ENOTDIR included) raises and the caller refuses."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _check(spec: dict | None, version: str, root: str, home: str, tool: str) -> PolicyCheck:
    if spec is None:
        return PolicyCheck(False, problems=[f"{tool} {version} 沒有管理員政策來源清單，不能啟動"])
    result = PolicyCheck(True)

    def look(path: str, shown: str | None = None):
        shown = shown or ("/" + os.path.relpath(path, root) if root != "/" else path)
        try:
            if _exists(path):
                result.found.append(shown)
        except OSError as exc:
            result.problems.append(f"無法確認 {shown} 是否存在（{exc.strerror or type(exc).__name__}）")

    for rel in spec["paths"]:
        look(os.path.join(root, rel))
    for rel in spec["home_paths"]:
        if not isinstance(home, str) or not home.startswith("/"):
            result.problems.append("不知道執行者的 HOME，無法確認伺服器管理設定的快取")
            continue
        look(os.path.join(home, rel), "~/" + rel)
    plist = spec["domain"] + ".plist"
    prefs = os.path.join(root, MANAGED_PREFS)
    look(os.path.join(prefs, plist))
    try:
        st = os.lstat(prefs)
    except FileNotFoundError:
        st = None
    except OSError as exc:
        result.problems.append(f"無法確認 /{MANAGED_PREFS} 是否存在（{exc.strerror or type(exc).__name__}）")
        st = None
    if st is not None:
        if not stat.S_ISDIR(st.st_mode):
            result.problems.append(f"/{MANAGED_PREFS} 不是一般資料夾，無法判斷")
        else:
            try:
                with os.scandir(prefs) as entries:
                    for n, entry in enumerate(entries):
                        if n >= MANAGED_PREFS_MAX_ENTRIES:
                            result.problems.append(f"/{MANAGED_PREFS} 項目過多，無法判斷")
                            break
                        if entry.is_symlink():
                            result.problems.append(f"/{MANAGED_PREFS}/{entry.name} 是符號連結，無法判斷")
                        elif entry.is_dir(follow_symlinks=False):
                            look(os.path.join(prefs, entry.name, plist))
            except OSError as exc:
                result.problems.append(f"無法列出 /{MANAGED_PREFS}（{exc.strerror or type(exc).__name__}）")
    result.ok = not result.found and not result.problems
    return result


def check_claude(version: str, root: str = "/", home: str | None = None) -> PolicyCheck:
    """Before every stream session and probe (design 2.1). ``home`` is the
    HOME the executor runs with (default: this process's). Never raises."""
    try:
        if home is None:
            home = os.path.expanduser("~")
        return _check(CLAUDE_SOURCES.get(version) if isinstance(version, str) else None, str(version), root,
                      home, "Claude Code")
    except Exception as exc:
        return PolicyCheck(False, problems=[f"管理員政策檢查失敗（{type(exc).__name__}）"])


def check_codex(version: str, root: str = "/") -> PolicyCheck:
    """Before every review (design 5.2). Never raises."""
    try:
        return _check(CODEX_SOURCES.get(version) if isinstance(version, str) else None, str(version), root,
                      "", "Codex")
    except Exception as exc:
        return PolicyCheck(False, problems=[f"系統設定層檢查失敗（{type(exc).__name__}）"])
