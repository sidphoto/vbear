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
  AGY          /etc/antigravity   (admin_settings.json)
               managed preferences domain com.google.antigravity (a candidate, see AGY_SOURCES)

Managed preferences are looked up in ``/Library/Managed Preferences/`` and in
every per-user directory under it.

Claude Code's server-managed settings are fetched from claude.ai and are no
local file. Its cache, ``~/.claude/remote-settings.json`` (in the HOME the
executor runs with; 2.1.318 also ``~/.claude/policy-limits.json``), refuses the launch when present (design v29.3, 2.1);
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

# 2.1.296: the same sources as 2.1.292. Checked on 2026-10-12 against the vendor's documentation (the managed-settings
# page: /Library/Application Support/ClaudeCode/managed-settings.json and the MDM domain com.anthropic.claudecode;
# the server-managed-settings page: the cache ~/.claude/remote-settings.json) and against the strings of the 2.1.296
# binary, which names no other source (managed-settings.d is a drop-in directory inside the checked ClaudeCode
# directory). Method and result: docs/evidence/claude-code-2.1.296-stream.md.
# 2.1.318 (P36-2): the same system sources, checked on 2026-11-05 against the strings of the installed 2.1.318 binary
# (macOS: /Library/Application Support/ClaudeCode, with managed-settings.json, managed-settings.d and the managed
# files; /Library/Managed Preferences/<user>/ and /Library/Managed Preferences/ with com.anthropic.claudecode.plist;
# /etc/claude-code and C:\Program Files\ClaudeCode are the Linux and Windows places). It names one more cache
# under the config home that a server delivers, ~/.claude/policy-limits.json (org-side policy verdicts); it is not
# in 2.1.296's strings, and strings cannot show that it never changes how a run behaves, so its presence refuses like
# remote-settings.json does. Vendor documentation was not read again for 2.1.318 (no network in that run); the pages
# read on 2026-10-12 are in docs/evidence/claude-code-2.1.296-stream.md. Method and result:
# docs/evidence/claude-code-2.1.318-chat.md.
_CLAUDE_2_1_318 = dict(_CLAUDE, home_paths=_CLAUDE["home_paths"] + (".claude/policy-limits.json",))
# 2.1.319 (P40-6): the same list as 2.1.318. Checked on 2026-11-07 with the same method against the strings of the installed
# 2.1.319 binary: the same /Library paths, the same /etc/claude-code place, the same managed-settings names, and
# policy-limits.json is still the one more cache (docs/evidence/claude-code-2.1.318-chat.md, "2.1.319").
# 2.1.322 (v0.22.1): the same list again. Checked on 2026-11-11, side by side with 2.1.319, against the strings of the installed
# 2.1.322 binary: the same /Library paths, the same /etc/claude-code place, the same managed-settings names, policy-limits.json
# still the one more cache (docs/evidence/claude-code-2.1.322-chat.md).
# 2.1.323 (v0.25.5): the same list again. The /Library and /etc/...claude... path lists of its binary are identical to 2.1.322's, and so are the
# counts of the places it names (docs/evidence/claude-code-2.1.323-chat.md). It also names a managed-settings channel that is not a place on
# disk: a host may hand the settings over in the ``initialize`` request of an SDK launch that was given a launch flag for it. A person's Mac has
# nothing to check for that channel, because only the program that starts Claude Code can open it; VBear starts it without the flag and sends
# no such key (guard rule 24).
CLAUDE_SOURCES = {"2.1.292": _CLAUDE, "2.1.296": _CLAUDE, "2.1.318": _CLAUDE_2_1_318, "2.1.319": _CLAUDE_2_1_318,
                  "2.1.322": _CLAUDE_2_1_318, "2.1.323": _CLAUDE_2_1_318}
# 0.163.0 (P38-2, chat mode): the same sources as 0.160.0. The Codex chat (ADR 0005) does not pass --ignore-user-config (app-server
# has no such flag), so the system and managed layers matter as much as for the review. The list is taken over from 0.160.0 and
# is to be checked against the installed 0.163.0 on a real Mac when the chat check is run (docs/evidence/codex-0.163.0-chat.md).
# 0.167.0 (v0.22.1): the same list again. Checked on 2026-11-11, side by side with the installed 0.163.0, against the strings of both
# binaries: /etc/codex (config.toml, requirements.toml, managed_config.toml in it), the managed preferences domain com.openai.codex
# (config_toml_base64, requirements_toml_base64 and the legacy managed_config.toml from it) and the cloud bundle cache inside
# CODEX_HOME are named in both, and the other paths the binaries name are the same
# (docs/evidence/codex-0.167.0-chat.md).
CODEX_SOURCES = {"0.160.0": _CODEX, "0.163.0": _CODEX, "0.167.0": _CODEX}
# 1.5.3 (P46-2, the AGY chat, ADR 0012): NOT taken from the vendor's documentation. The planner read the strings of the
# installed 1.5.3 binary on 2026-11-09 (the file was not run): /etc/antigravity/admin_settings.json appears as a whole path,
# beside the words AdminSettings and AdminSettingsPath; com.google.antigravity appears too, and nothing shows whether it is a
# macOS managed-preferences domain. So the whole folder /etc/antigravity is listed (stricter than naming the file, and a
# later file in it refuses as well) and the domain is a candidate: if its plist exists the launch is refused, which costs a
# person nothing when it is not a real source. "Better to refuse too much" is the rule here. AGY's own user-level
# hooks (~/.agents/hooks.json) are not a policy source and are checked by agy_chat_env.home_hooks_state. Method and result:
# docs/evidence/agy-1.5.3-chat.md, section 8.
# 1.5.6 (P56-2, v0.25.2): the 1.5.3 list and one more place. The strings of the real 1.5.6 (counted on 2026-11-12, the program was
# not run for them) still hold /etc/antigravity (once), admin_settings (7), AdminSettings (18) and com.google.antigravity (6), and
# nothing named managed-settings or policy.json. They also hold /Library/Application Support/Antigravity once, a path the 1.5.3
# reading met too and left out as unexplained. The strings cannot show what it is, so for 1.5.6 the whole folder is a source: if it
# is there the launch is refused (only stricter than 1.5.3, and a Mac without that folder is not affected). 1.5.3's entry did not
# change. It is a candidate only ("unconfirmed"): the refusal sentence says its use is not confirmed, not that a policy exists.
# Method and result: docs/evidence/agy-1.5.6-chat.md, section 3.
# 1.5.7 (v0.25.5): the 1.5.6 list, unchanged. The strings of the real 1.5.7 (counted on 2026-11-13, the program was not run for them) still hold
# /etc/antigravity/admin_settings.json (once), /Library/Application Support/Antigravity (once), admin_settings (6), AdminSettings (18), and nothing named
# managed-settings or policy.json. They also list three longer names that begin with com.google.antigravity (".companion", ".dev", ".insiders"), which sit
# in the program beside other applications' bundle identifiers; they are not shown to be managed-preference domains, the table holds one domain per
# version, and the counting of 1.5.6 cannot tell whether they are new, so they are not added (docs/evidence/agy-1.5.7-chat.md, section 3).
_AGY_1_5_6 = {"paths": ("etc/antigravity", "Library/Application Support/Antigravity"), "domain": "com.google.antigravity",
              "home_paths": (), "unconfirmed": ("Library/Application Support/Antigravity",)}
# 1.5.8 (v0.25.6): the 1.5.6 list again, unchanged. The strings of the real 1.5.8 (counted on 2026-11-13, the program was not run for them) hold the same
# two places (/etc/antigravity/admin_settings.json once, /Library/Application Support/Antigravity once), the same com.google.antigravity domain
# (10 in the same counting as 1.5.7's; the three longer com.google.antigravity.* names of 1.5.7 are there still and are still not added), no new
# place, no new ANTIGRAVITY_* name. What grew is what an administrator can control through those
# same places: an ``authControls`` section of the same admin_settings.json (consumer login, the workload-identity provider, the Google Cloud project and
# location, the licence type), a web-fetch switch, a remote-control switch and a ceiling on the permission preset, plus the controls the server hands
# over (``FetchAdminControls``, already in 1.5.7). A local source that exists is refused whatever it contains, so a new field inside an existing
# source needs no new entry; the server-fetched controls are the residual SECURITY-MODEL already names (docs/evidence/agy-1.5.8-chat.md, section 3).
AGY_SOURCES = {"1.5.3": {"paths": ("etc/antigravity",), "domain": "com.google.antigravity", "home_paths": ()},
               "1.5.6": _AGY_1_5_6, "1.5.7": dict(_AGY_1_5_6), "1.5.8": dict(_AGY_1_5_6)}


@dataclass
class PolicyCheck:
    ok: bool
    found: list[str] = field(default_factory=list)       # sources that exist
    problems: list[str] = field(default_factory=list)    # could not be established
    unconfirmed: list[str] = field(default_factory=list)  # found, but nothing shows it is an administrator source (a candidate only)

    def reason(self) -> str:
        if self.ok:
            return ""
        confirmed = [p for p in self.found if p not in self.unconfirmed]
        parts = [f"存在管理員政策或系統設定：{p}" for p in confirmed]
        parts += self.problems
        text = "；".join(parts) + "。請使用者或系統管理員處理後再啟動。" if parts or not self.unconfirmed else ""
        if self.unconfirmed:
            text += ("；" if text else "") + "、".join(self.unconfirmed) + (
                " 這個位置的用途 VBear 還不能確認（它可能是管理員設定，也可能只是一般的安裝資料），為了安全先不啟動聊天。"
                "VBear 不會替你動它；等 VBear 確認它的用途後才能放行。")
        return text


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

    def look(path: str, shown: str | None = None, candidate: bool = False):
        shown = shown or ("/" + os.path.relpath(path, root) if root != "/" else path)
        try:
            if _exists(path):
                result.found.append(shown)
                if candidate:
                    result.unconfirmed.append(shown)
        except OSError as exc:
            result.problems.append(f"無法確認 {shown} 是否存在（{exc.strerror or type(exc).__name__}）")

    for rel in spec["paths"]:
        look(os.path.join(root, rel), candidate=rel in spec.get("unconfirmed", ()))
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


def check_agy(version: str, root: str = "/") -> PolicyCheck:
    """Before every AGY chat process (P46-2, ADR 0012). Never raises."""
    try:
        return _check(AGY_SOURCES.get(version) if isinstance(version, str) else None, str(version), root,
                      "", "AGY")
    except Exception as exc:
        return PolicyCheck(False, problems=[f"系統設定層檢查失敗（{type(exc).__name__}）"])
