"""What the Codex chat needs before any process starts (P38-2, ADR 0005): its own login folder, the pinned binary, the
login state and the one answer "may this Mac chat with Codex, and if not, why".

The Codex that chats never uses the person's own ``~/.codex``: ``codex app-server`` always reads that folder's settings
(it has no way to ignore them), so the chat logs in to ``<state>/codex-chat-home`` instead. VBear never writes a
``config.toml``, ``rules/`` or ``AGENTS.md`` there, so finding one means another program put it there and the chat is
refused. This folder is not the review's ``codex-home`` (that one has its own login fingerprint and size watch; a chat's
saved conversations must not block a review).

Every check either returns a value that was checked or says why not. No model is called: ``codex --version`` and
``codex login status`` start Codex but not a model. The login state is the exit code of the status command and nothing
else; what it prints is read nowhere and kept nowhere.
"""

from __future__ import annotations

import os
import platform
import re
import stat
import tempfile
import threading
import time
from pathlib import Path

from .. import admin_policy
from . import cli_versions, review_codex, review_store
from .review_codex import CodexRefused

CHAT_HOME_NAME = "codex-chat-home"
HOME_LIMIT = review_codex.HOME_LIMIT          # 512 MiB: a monitoring threshold, not a hard cap (counted as the review's is)
FORBIDDEN = ("config.toml", "rules", "AGENTS.md")      # VBear never writes these here: any of them is someone else's
STATUS_TIMEOUT_S = 20.0
CACHE_TTL_S = 10.0
POLICY_ROOT = "/"                              # where the administrator policy is looked for (tests give another root)
RELEASES = ".codex/packages/standalone/releases"


# ---- the folder ------------------------------------------------------------------------------------------------------

def chat_home_path(base) -> Path:
    """<state>/codex-chat-home. The state folder itself is resolved once (a person may keep it behind a link, as the review's
    folders are); the chat folder under it is never resolved: a link in its place or inside it is refused by the checks."""
    return Path(os.path.realpath(os.fspath(base))) / CHAT_HOME_NAME


def _open_checked(base):
    """(path, fd): the folder opened from "/" one component at a time without following any link, and found to be this
    user's own plain 0700 folder. The caller closes the fd. CodexRefused otherwise."""
    path = chat_home_path(base)
    try:
        fd = review_store.open_dir_chain(path)
    except (OSError, ValueError) as exc:
        raise CodexRefused("unsafe_path", "聊天用的 Codex 資料夾不存在，或路徑上有符號連結、不是資料夾"
                           f"（{type(exc).__name__}）") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise CodexRefused("unsafe_path", "聊天用的 Codex 資料夾必須是本人的 0700 一般資料夾")
    except BaseException:
        os.close(fd)
        raise
    return path, fd


def check_chat_home(base, *, size: bool = True) -> Path:
    """The folder is usable: ours, 0700, no link on its path, none of ``FORBIDDEN`` in it (whatever kind of entry it is,
    a link included), and within the size threshold (``size=False`` leaves the count out). CodexRefused otherwise."""
    path, fd = _open_checked(base)
    try:
        for name in FORBIDDEN:
            try:
                os.lstat(name, dir_fd=fd)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise CodexRefused("foreign_settings", f"無法確認聊天用的 Codex 資料夾裡有沒有 {name}"
                                   f"（{exc.strerror or type(exc).__name__}），所以不使用它") from exc
            raise CodexRefused("foreign_settings", f"聊天用的 Codex 資料夾裡有 {name}，不是 VBear 放的，"
                               "所以不使用它。請把它移走（VBear 不會替你刪）。")
    finally:
        os.close(fd)
    if size:
        counted = review_codex.home_size(path)
        if review_codex.over_limit(counted, HOME_LIMIT):
            raise CodexRefused("too_big", "聊天用的 Codex 資料夾超過 512 MiB（或無法算出大小），所以不使用它。"
                               "它是 Codex 自己存的對話副本，請到狀態資料夾處理。")
    return path


def ensure_chat_home(base) -> Path:
    """Make the folder (0700) when it is not there, then check it. An existing folder is never repaired or changed."""
    try:
        parent = review_store.open_dir_chain(chat_home_path(base).parent)       # a link anywhere on the way is refused before anything is made
    except (OSError, ValueError) as exc:
        raise CodexRefused("unsafe_path", "狀態資料夾不存在，或路徑上有符號連結、不是資料夾"
                           f"（{type(exc).__name__}）") from exc
    try:
        try:
            os.mkdir(CHAT_HOME_NAME, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CodexRefused("unsafe_path", f"無法建立聊天用的 Codex 資料夾（{exc.strerror or type(exc).__name__}）") from exc
        else:
            fd = os.open(CHAT_HOME_NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                os.fchmod(fd, 0o700)
            finally:
                os.close(fd)
    finally:
        os.close(parent)
    return check_chat_home(base)


def home_state(base) -> tuple[str, str]:
    """("missing" | "ok" | "refused", why): a look that makes nothing. A folder that is not there yet is not a problem."""
    try:
        os.lstat(chat_home_path(base))
    except FileNotFoundError:
        return "missing", ""
    except OSError as exc:
        return "refused", f"無法確認聊天用的 Codex 資料夾（{exc.strerror or type(exc).__name__}）"
    try:
        check_chat_home(base)
    except CodexRefused as exc:
        return "refused", str(exc)
    return "ok", ""


# ---- the binary ------------------------------------------------------------------------------------------------------

def _arch() -> str:
    return "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"


def installed_versions(home=None) -> list[str]:
    """The Codex versions the vendor's installer left for this machine under the HOME, oldest first. Only the folder names
    are read: <version>-<arch>-apple-darwin, with a plain version. A stray file or another name is ignored."""
    root = (Path(home) if home else Path.home()) / RELEASES
    pattern = re.compile(r"^([0-9.]+)-" + re.escape(_arch()) + r"-apple-darwin\Z")
    found = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                m = pattern.match(entry.name)
                if m and review_store.VERSION_RE.match(m.group(1)) and entry.is_dir(follow_symlinks=False):
                    found.append(m.group(1))
    except OSError:
        return []
    return sorted(found, key=cli_versions._version_key)


def pinned_binary(home=None, verified=None) -> tuple[str, str] | None:
    """(binary, version) of the newest installed Codex that passed the chat check, or None. Never a copy found on PATH; the
    file must be a plain executable with no link on its path (review_codex.codex_binary). ``verified`` is given by tests."""
    verified = cli_versions.codex_chat_verified_versions() if verified is None else verified
    for version in reversed(installed_versions(home)):
        if version not in verified:
            continue
        try:
            return review_codex.codex_binary(version, str(home) if home else None), version
        except CodexRefused:
            continue
    return None


# ---- the login -------------------------------------------------------------------------------------------------------

def login_state(binary: str, chat_home) -> str:
    """"logged_in" | "not_logged_in" | "unknown": the exit code of ``codex login status -c ...`` run with CODEX_HOME set to
    the chat folder and an empty HOME of its own (0 is logged in). A command that could not be started or did not finish in
    time is "unknown", never a login. The output goes nowhere."""
    from .. import ai_tools
    args = ai_tools.chat_login_status_args("codex")
    try:
        with tempfile.TemporaryDirectory(prefix="vbear-cx-") as scratch:
            run_env = review_codex.build_env(str(chat_home), scratch)
            code, _out, err = cli_versions.run_capture([binary, *args], "/", run_env, STATUS_TIMEOUT_S, 64 << 10)
    except Exception:
        return "unknown"
    if err or code is None:
        return "unknown"
    return "logged_in" if code == 0 else "not_logged_in"


# ---- the answer ------------------------------------------------------------------------------------------------------

_cache: dict = {}
_cache_lock = threading.Lock()


def invalidate() -> None:
    with _cache_lock:
        _cache.clear()


def status(base, *, home=None, root: str | None = None, force: bool = False) -> dict:
    """May this Mac chat with Codex now? One dict, no path and no command output in it:

    state: "not_installed" | "unverified" | "policy" | "folder" | "version_unreadable" | "not_logged_in" | "ready"
    installed / version (the pinned one, else the newest installed) / verified / logged_in (None until it was asked) /
    admin_policy_ok (None until it was asked) / why (the sentence for a person; "" when ready) / verified_versions."""
    root = POLICY_ROOT if root is None else root
    key = (os.fspath(base), str(home or ""), root)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and CACHE_TTL_S > 0 and now - hit[0] < CACHE_TTL_S:
            return dict(hit[1], verified_versions=list(hit[1]["verified_versions"]))
    out = _look(base, home, root)
    with _cache_lock:
        if CACHE_TTL_S > 0:
            _cache[key] = (now, out)
    return dict(out, verified_versions=list(out["verified_versions"]))


def _look(base, home, root) -> dict:
    verified = cli_versions.codex_chat_verified_versions()
    out = {"state": "", "installed": False, "version": None, "verified": False, "logged_in": None,
           "admin_policy_ok": None, "why": "", "verified_versions": sorted(verified, key=cli_versions._version_key)}
    versions = installed_versions(home)
    if not versions:
        out.update(state="not_installed", why="找不到用官方安裝指令裝的 Codex。請到「開始設定」安裝 Codex。")
        return out
    out.update(installed=True, version=versions[-1])
    pinned = pinned_binary(home, verified)
    if pinned is None:
        out.update(state="unverified", why=cli_versions.codex_chat_unverified_text(versions[-1]))
        return out
    binary, version = pinned
    out.update(version=version, verified=True)
    policy = admin_policy.check_codex(version, root)
    out["admin_policy_ok"] = policy.ok
    if not policy.ok:
        out.update(state="policy", why=policy.reason())
        return out
    folder, why = home_state(base)
    if folder == "refused":
        out.update(state="folder", why=why)
        return out
    read, detail = review_codex.read_version_detail(binary, cli_versions._run_probe)
    if read != version:
        out.update(state="version_unreadable",
                   why=f"Codex {version} 沒有印出剛好是 codex-cli {version} 的版本行（{detail or '版本不符'}），所以不使用它。")
        return out
    logged = "not_logged_in" if folder == "missing" else login_state(binary, chat_home_path(base))
    out["logged_in"] = logged == "logged_in"
    if logged != "logged_in":
        out.update(state="not_logged_in",
                   why=("聊天用的 Codex 還沒有登入。請到「開始設定」按「讓聊天用的 Codex 登入」。" if logged == "not_logged_in"
                        else "查不出聊天用的 Codex 有沒有登入。可以到「開始設定」按「重新檢查」再試。"))
        return out
    out["state"] = "ready"
    return out
