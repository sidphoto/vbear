"""What the AGY chat needs before any process starts (P46-2, ADR 0012): its own settings folder, the folders AGY would read
as project settings, the pinned binary and the one answer "may this Mac chat with AGY, and if not, why".

The AGY that chats uses the person's own login (it follows HOME) but not the person's own settings: ``agy acp --gemini-dir
<state>/agy-chat-home`` reads ``antigravity-cli/settings.json`` from there, and VBear writes that file itself, with the same
content, before every process (``write_settings``). Nothing else is written into the folder by VBear. A ``GEMINI.md``, an
``AGENTS.md`` or a ``config/`` entry that carries hooks, skills, workflows, plugins or projects, and an MCP configuration that
says anything, are things another program put there; the chat is refused until the person moves them (VBear never deletes
them). The folder is not Codex's ``codex-chat-home``: the two share nothing. AGY's own saved conversations
(``antigravity-cli/conversations/``) are never deleted by VBear.

Two things outside this folder can still reach AGY and are looked at here, by name only and never read: the person's
``~/.agents/hooks.json`` (commands AGY runs by itself; its presence refuses the chat, ``home_hooks_state``) and the top level of a
chat's work folder (``.agents``, ``.agent``, ``.gemini``, ``GEMINI.md`` and ``AGENTS.md`` there are read by AGY as project
settings and rules; ``check_workdir``). The person's skills in ``~/.agents/skills`` are loaded by AGY anyway: the person
accepted that (ADR 0012), and the screen says so.

Every check either returns a value that was checked or says why not. ``agy --version`` is the only program run, and it
starts AGY but not a model. Nothing of what AGY prints is kept apart from the version it is.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import threading
import time
from pathlib import Path

from .. import admin_policy
from . import cli_versions, review_codex, review_store

CHAT_HOME_NAME = "agy-chat-home"
CLI_DIR = "antigravity-cli"
SETTINGS_NAME = "settings.json"
HOME_LIMIT = review_codex.HOME_LIMIT          # 512 MiB: a monitoring threshold, not a hard cap (counted as Codex's is)
STATUS_TIMEOUT_S = 10.0
CACHE_TTL_S = 10.0
POLICY_ROOT = "/"                              # where the administrator policy is looked for (tests give another root)

# What VBear makes AGY read (ADR 0012, decision 1): the five keys of the design. "useG1Credits" is the paid-credits switch; that
# it is a key of this file is read from the binary's strings, not proven, and the chat check says whether AGY still starts with it.
SETTINGS = {"toolPermission": "request-review", "allowNonWorkspaceAccess": False, "enableTerminalSandbox": True,
            "useG1Credits": False, "permissions": {"allow": [], "ask": [], "deny": []}}
SETTINGS_BYTES = (json.dumps(SETTINGS, indent=2, sort_keys=True) + "\n").encode("utf-8")

# Names VBear never writes in the chat folder: finding one means another program put it there. (name as shown, where it sits)
FORBIDDEN_TOP = ("GEMINI.md", "AGENTS.md")
FORBIDDEN_CONFIG = ("hooks.json", "skills", "workflows", "global_workflows", "plugins", "projects")
CONFIG_DIR = "config"
MCP_CONFIG_NAME = "mcp_config.json"
MCP_CONFIG_MAX = 64 << 10

# Names at the top of a work folder (or an open shared folder) that AGY reads as settings and rules.
WORKDIR_FORBIDDEN = (".agents", ".agent", ".gemini", "GEMINI.md", "AGENTS.md")
WORKDIR_SCAN_MAX = 10_000
HOOKS_FILE = ".agents/hooks.json"             # under the person's HOME; looked for, never read

# Versions this code knows how to run. The argv, environment and message constants of a version are the protocol table's
# (agy_chat_protocol, P46-1); this is only the list the binary's version is matched against, and agrees with it by a test.
KNOWN_VERSIONS = ("1.5.3",)
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)\n?\Z")


class AgyRefused(Exception):
    """Something here is not safe or not as expected. ``code`` is stable; the message is a sentence for the person and
    carries no path and nothing AGY printed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---- the folder ------------------------------------------------------------------------------------------------------

def chat_home_path(base) -> Path:
    """<state>/agy-chat-home. The state folder itself is resolved once (a person may keep it behind a link); the chat folder
    under it is never resolved: a link in its place or inside it is refused by the checks."""
    return Path(os.path.realpath(os.fspath(base))) / CHAT_HOME_NAME


def _open_checked(base, home=None):
    """(path, fd): the folder opened from "/" one component at a time without following any link, and found to be this
    user's own plain 0700 folder. The caller closes the fd. AgyRefused otherwise. ``home`` is another folder than
    <state>/agy-chat-home, which only the version check gives (a temporary one)."""
    path = Path(home) if home else chat_home_path(base)
    try:
        fd = review_store.open_dir_chain(path)
    except (OSError, ValueError) as exc:
        raise AgyRefused("unsafe_path", "聊天用的 AGY 設定資料夾不存在，或路徑上有符號連結、不是資料夾"
                         f"（{type(exc).__name__}）") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise AgyRefused("unsafe_path", "聊天用的 AGY 設定資料夾必須是本人的 0700 一般資料夾")
    except BaseException:
        os.close(fd)
        raise
    return path, fd


def _foreign(name: str) -> AgyRefused:
    return AgyRefused("foreign_settings", f"聊天用的 AGY 設定資料夾裡有 {name}，不是 VBear 放的，所以不使用它。"
                      "請把它移走（VBear 不會替你刪）。")


def _names(fd) -> list[str]:
    with os.scandir(fd) as it:
        return [entry.name for entry in it]


def _config_fd(fd):
    """A descriptor on <folder>/config when it is there as a plain folder, None when it is not there at all. Anything else
    in its place (a link, a file) is someone else's."""
    try:
        os.lstat(CONFIG_DIR, dir_fd=fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AgyRefused("foreign_settings", f"無法確認聊天用的 AGY 設定資料夾裡有沒有 config（{exc.strerror or type(exc).__name__}），"
                         "所以不使用它") from exc
    try:
        return os.open(CONFIG_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    except OSError as exc:
        raise _foreign(CONFIG_DIR) from exc


def _says_nothing(value, depth: int = 0) -> bool:
    """True for a parsed JSON value that holds no value at all: null, "", and lists and objects of such. A number, a
    boolean or any text is a value (a setting, a server), so an MCP configuration that holds one is not empty."""
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, list):
        return all(_says_nothing(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return all(_says_nothing(v, depth + 1) for v in value.values())
    return False


def _check_mcp_config(cfd) -> None:
    try:
        os.lstat(MCP_CONFIG_NAME, dir_fd=cfd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AgyRefused("foreign_settings", f"無法確認 AGY 的 MCP 設定檔存不存在（{exc.strerror or type(exc).__name__}），"
                         "所以不使用聊天用的 AGY 設定資料夾") from exc
    problem = AgyRefused("foreign_settings", "聊天用的 AGY 設定資料夾裡有 MCP 設定（mcp_config.json），不是空的，"
                         "所以不使用它。請把它移走（VBear 不會替你刪）。")
    try:
        fd = os.open(MCP_CONFIG_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=cfd)
    except OSError as exc:
        raise problem from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MCP_CONFIG_MAX:
            raise problem
        data = os.read(fd, MCP_CONFIG_MAX + 1)
    except OSError as exc:
        raise problem from exc
    finally:
        os.close(fd)
    if len(data) > MCP_CONFIG_MAX:
        raise problem
    if not data.strip():
        return
    try:
        parsed = json.loads(data.decode("utf-8"))
        empty = _says_nothing(parsed)
    except (ValueError, RecursionError):
        raise problem from None
    if not empty:
        raise problem


def _tree_size(path) -> int | None:
    """Bytes in the folder tree, walked by descriptor, nothing followed. None for anything not exactly countable (an error, a
    special file, more than ``review_codex.SCAN_MAX_ENTRIES`` entries, a link): the caller treats that as over the limit. The
    one link let through is ``antigravity-cli/settings.json`` (counted at the size of the link): it is VBear's own file, which
    ``write_settings`` replaces, and a link left in its place must not keep the folder from being repaired."""
    total, seen = 0, 0
    stack: list[tuple[int, tuple]] = []
    try:
        stack.append((os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC), ()))
        while stack:
            fd, parts = stack.pop()
            try:
                with os.scandir(fd) as it:
                    for entry in it:
                        seen += 1
                        if seen > review_codex.SCAN_MAX_ENTRIES:
                            return None
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode):
                            stack.append((os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                                  dir_fd=fd), (*parts, entry.name)))
                        elif stat.S_ISREG(st.st_mode) or (stat.S_ISLNK(st.st_mode) and parts == (CLI_DIR,)
                                                          and entry.name == SETTINGS_NAME):
                            total += st.st_size
                        else:
                            return None
            finally:
                os.close(fd)
        return total
    except OSError:
        return None
    finally:
        for fd, _ in stack:
            try:
                os.close(fd)
            except OSError:
                pass


def check_chat_home(base, *, size: bool = True, home=None) -> Path:
    """The folder is usable: ours, 0700, no link on its path, none of ``FORBIDDEN_TOP`` at its top and none of
    ``FORBIDDEN_CONFIG`` in its config folder (whatever kind of entry, a link included; compared without regard to case,
    as the Mac's file system does), an MCP configuration that is missing or says nothing, and within the size threshold
    (``size=False`` leaves the count out). AgyRefused otherwise. Only names are looked at, and the MCP file is read."""
    path, fd = _open_checked(base, home)
    try:
        try:
            top = _names(fd)
        except OSError as exc:
            raise AgyRefused("foreign_settings", f"無法列出聊天用的 AGY 設定資料夾（{exc.strerror or type(exc).__name__}），"
                             "所以不使用它") from exc
        folded = {n.casefold() for n in top}
        for name in FORBIDDEN_TOP:
            if name.casefold() in folded:
                raise _foreign(name)
        cfd = _config_fd(fd)
        if cfd is not None:
            try:
                try:
                    inner = {n.casefold() for n in _names(cfd)}
                except OSError as exc:
                    raise AgyRefused("foreign_settings", f"無法列出 AGY 的 config 資料夾（{exc.strerror or type(exc).__name__}），"
                                     "所以不使用聊天用的 AGY 設定資料夾") from exc
                for name in FORBIDDEN_CONFIG:
                    if name.casefold() in inner:
                        raise _foreign(name)
                _check_mcp_config(cfd)
            finally:
                os.close(cfd)
    finally:
        os.close(fd)
    if size:
        counted = _tree_size(path)
        if review_codex.over_limit(counted, HOME_LIMIT):
            raise AgyRefused("too_big", "聊天用的 AGY 設定資料夾超過 512 MiB（或無法算出大小、裡面有符號連結），所以不使用它。"
                             "它是 AGY 自己存的對話副本，請到狀態資料夾處理。")
    return path


def ensure_chat_home(base, *, size: bool = True) -> Path:
    """Make the folder (0700) when it is not there, then check it. An existing folder is never repaired or changed."""
    try:
        parent = review_store.open_dir_chain(chat_home_path(base).parent)       # a link anywhere on the way is refused before anything is made
    except (OSError, ValueError) as exc:
        raise AgyRefused("unsafe_path", "狀態資料夾不存在，或路徑上有符號連結、不是資料夾"
                         f"（{type(exc).__name__}）") from exc
    try:
        try:
            os.mkdir(CHAT_HOME_NAME, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        except OSError as exc:
            raise AgyRefused("unsafe_path", f"無法建立聊天用的 AGY 設定資料夾（{exc.strerror or type(exc).__name__}）") from exc
        else:
            fd = os.open(CHAT_HOME_NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                os.fchmod(fd, 0o700)
            finally:
                os.close(fd)
    finally:
        os.close(parent)
    return check_chat_home(base, size=size)


def home_state(base, home=None) -> tuple[str, str]:
    """("missing" | "ok" | "refused", why): a look that makes nothing. A folder that is not there yet is not a problem."""
    try:
        os.lstat(Path(home) if home else chat_home_path(base))
    except FileNotFoundError:
        return "missing", ""
    except OSError as exc:
        return "refused", f"無法確認聊天用的 AGY 設定資料夾（{exc.strerror or type(exc).__name__}）"
    try:
        check_chat_home(base, home=home)
    except AgyRefused as exc:
        return "refused", str(exc)
    return "ok", ""


# ---- settings.json ---------------------------------------------------------------------------------------------------

def write_settings(base, home=None) -> Path:
    """Write ``antigravity-cli/settings.json`` with the fixed content, before every process starts (and make the folder and
    ``antigravity-cli/`` first when they are not there). The file is written to a new name in the same folder and renamed over
    the old one: a link or a file someone left in its place is replaced, never followed or written through. 0600. A link or a
    file in place of ``antigravity-cli``, or a folder in place of the file, is refused. AgyRefused otherwise."""
    if home is None:
        ensure_chat_home(base, size=False)         # the size is the status's business: a big folder must not keep the file from being repaired
    else:
        check_chat_home(base, home=home, size=False)
    path, hfd = _open_checked(base, home)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        try:
            os.mkdir(CLI_DIR, 0o700, dir_fd=hfd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise AgyRefused("unsafe_path", f"無法建立 AGY 的 antigravity-cli 資料夾（{exc.strerror or type(exc).__name__}）") from exc
        try:
            cfd = os.open(CLI_DIR, flags, dir_fd=hfd)
        except OSError as exc:
            raise AgyRefused("unsafe_path", "聊天用的 AGY 設定資料夾裡的 antigravity-cli 是符號連結或不是資料夾，所以不使用它"
                             ) from exc
    finally:
        os.close(hfd)
    try:
        if os.fstat(cfd).st_uid != os.getuid():
            raise AgyRefused("unsafe_path", "聊天用的 AGY 設定資料夾裡的 antigravity-cli 不是本人的資料夾，所以不使用它")
        tmp = f".settings.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=cfd)
        except OSError as exc:
            raise AgyRefused("unsafe_path", f"無法寫入 AGY 的設定檔（{exc.strerror or type(exc).__name__}）") from exc
        try:
            try:
                os.fchmod(fd, 0o600)
                view = memoryview(SETTINGS_BYTES)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(tmp, SETTINGS_NAME, src_dir_fd=cfd, dst_dir_fd=cfd)
        except OSError as exc:
            try:
                os.unlink(tmp, dir_fd=cfd)
            except OSError:
                pass
            raise AgyRefused("unsafe_path", f"無法寫入 AGY 的設定檔（{exc.strerror or type(exc).__name__}）") from exc
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=cfd)
            except OSError:
                pass
            raise
        try:
            os.fsync(cfd)
        except OSError:
            pass
    finally:
        os.close(cfd)
    return path / CLI_DIR / SETTINGS_NAME


def settings_intact(base, home=None) -> bool:
    """Whether ``antigravity-cli/settings.json`` is, byte for byte, what ``write_settings`` wrote and a plain file (a link, a
    folder, a missing file, a different size or a different content are all no). Checked after every turn and when the process ends;
    a no is a violation of the chat (the next start writes the file again). Never raises."""
    try:
        path = Path(home) if home else chat_home_path(base)
        dfd = review_store.open_dir_chain(path / CLI_DIR)
    except (OSError, ValueError):
        return False
    try:
        fd = os.open(SETTINGS_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size != len(SETTINGS_BYTES):
                return False
            return os.read(fd, len(SETTINGS_BYTES) + 1) == SETTINGS_BYTES
        finally:
            os.close(fd)
    except OSError:
        return False
    finally:
        os.close(dfd)


# ---- the person's hooks ----------------------------------------------------------------------------------------------

def home_hooks_state(home=None) -> tuple[str, str]:
    """("absent" | "present" | "unreadable", why): ``lstat`` of ~/.agents/hooks.json and nothing else; the file is never opened.
    "absent" only when the system says the name is not there. Anything there (a file, a folder, a link, a dangling link) and
    any other failure to tell is a refusal: hooks are commands AGY runs by itself, which VBear can neither ask about nor stop."""
    root = os.fspath(home) if home else str(Path.home())
    try:
        os.lstat(os.path.join(root, HOOKS_FILE))
    except FileNotFoundError:
        return "absent", ""
    except OSError as exc:
        return "unreadable", (f"無法確認 ~/{HOOKS_FILE} 存不存在（{exc.strerror or type(exc).__name__}），所以不啟動 AGY 聊天。")
    return "present", ("你自己的 AGY 設定裡有 hooks（AGY 會自動執行的指令）。AGY 聊天會載入它們，VBear 管不到，所以不啟動。"
                       f"把 ~/{HOOKS_FILE} 移走（VBear 不會替你動）才能用 AGY 聊天。")


# ---- the work folder -------------------------------------------------------------------------------------------------

def check_workdir(path, *, code: str = "agy_workdir", label: str = "工作資料夾") -> Path:
    """The folder AGY will be started in (a chat's work folder, or an open shared folder with ``code="shared_unsafe"`` and
    ``label="共用資料夾"``) holds nothing AGY would read as settings or rules, and no link that leads out of it. A folder that is
    not there yet passes (it is made later). Names and links only: no file is opened, no link is followed (a link is
    resolved as a name, to see where it ends), and at most ``WORKDIR_SCAN_MAX`` entries are looked at. AgyRefused (``code``)
    otherwise, with a sentence that names the entry (one of the five fixed names) but no path.

    - the top level has none of ``WORKDIR_FORBIDDEN`` (compared without regard to case): AGY reads ``.agents`` (skills, hooks,
      workflows, agents), ``.gemini``, ``GEMINI.md`` and ``AGENTS.md`` as project settings and rules;
    - no link in the tree ends outside the folder: a read AGY does by itself inside the work folder would otherwise reach out.
    This is a look before the start. A link made while AGY runs is the tracker's business (agy_chat_protocol)."""
    path = Path(path)

    def refuse(text: str) -> AgyRefused:
        return AgyRefused(code, text)

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return path
    except OSError as exc:
        raise refuse(f"無法確認{label}（{exc.strerror or type(exc).__name__}），所以不啟動 AGY 聊天。") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise refuse(f"{label}不是一般資料夾（是符號連結或檔案），所以不啟動 AGY 聊天。")
    root = os.path.realpath(path)
    prefix = root.rstrip("/") + "/"
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise refuse(f"無法打開{label}（{exc.strerror or type(exc).__name__}），所以不啟動 AGY 聊天。") from exc
    stack: list[tuple[int, tuple]] = [(fd, ())]
    seen = 0
    try:
        while stack:
            fd, parts = stack.pop()
            try:
                with os.scandir(fd) as it:
                    for entry in it:
                        seen += 1
                        if seen > WORKDIR_SCAN_MAX:
                            raise refuse(f"{label}的項目太多（超過 {WORKDIR_SCAN_MAX} 項），無法確認裡面沒有指向外面的連結，"
                                         "所以不啟動 AGY 聊天。")
                        if not parts:
                            for name in WORKDIR_FORBIDDEN:
                                if entry.name.casefold() == name.casefold():
                                    raise refuse(f"{label}裡有 {name}，AGY 會把它當成設定讀進來，所以不啟動 AGY 聊天。"
                                                 "請把它移走（VBear 不會替你刪）。")
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            end = os.path.realpath(os.path.join(root, *parts, entry.name))
                            if end != root and not end.startswith(prefix):
                                raise refuse(f"{label}裡有指向外面的連結，AGY 的讀取會讀到{label}以外的地方，所以不啟動 AGY 聊天。"
                                             "請把它移走（VBear 不會替你刪）。")
                        elif stat.S_ISDIR(info.st_mode):
                            stack.append((os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                                  dir_fd=fd), (*parts, entry.name)))
            except OSError as exc:
                raise refuse(f"無法檢查{label}裡的項目（{exc.strerror or type(exc).__name__}），所以不啟動 AGY 聊天。") from exc
            finally:
                os.close(fd)
    finally:
        for fd, _ in stack:
            try:
                os.close(fd)
            except OSError:
                pass
    return path
