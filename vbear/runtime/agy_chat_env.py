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
import stat
import threading
import time
from dataclasses import dataclass
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
VERSION_OUT = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+)\n?")        # the whole output of ``agy --version``, nothing else
BINARY_NAME = "agy"


class AgyRefused(Exception):
    """Something here is not safe or not as expected. ``code`` is stable; the message is a sentence for the person and
    carries no path and nothing AGY printed (a version number that matched the version pattern is the one exception)."""

    def __init__(self, code: str, message: str, version: str | None = None):
        super().__init__(message)
        self.code = code
        self.version = version             # the version AGY printed, when the refusal came after reading it


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


# ---- the binary ------------------------------------------------------------------------------------------------------

def _uid() -> int:
    return os.getuid()


@dataclass(frozen=True)
class PinnedAgy:
    """The AGY that may chat: its real path, the version it printed, and ``cli_identity`` (the six numbers a launch manifest
    keeps, so a file that changed after the check is seen at the next start)."""
    binary: str
    version: str
    identity: list


def cli_identity(path: str) -> list[int]:
    """[device, inode, mode, size, mtime_ns, ctime_ns] of the executable file (the same list ``agent_sessions.binary_identity``
    gives). OSError when it is not a plain executable file."""
    info = os.stat(path, follow_symlinks=True)
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise OSError("binary is not a regular executable file")
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def unchanged(binary: str, identity) -> bool:
    """Whether the file at ``binary`` is, by its identity, the one that was checked. A file that is gone is no."""
    if not (isinstance(identity, (list, tuple)) and len(identity) == 6):
        return False
    try:
        return cli_identity(binary) == list(identity)
    except OSError:
        return False


def _trusted_owner(uid: int) -> bool:
    return uid in (0, _uid())


def _unsafe_binary(why: str) -> AgyRefused:
    return AgyRefused("unsafe_binary", f"找到的 AGY 執行檔{why}，所以不使用它。")


def _check_chain(directory: str) -> None:
    """Every folder from ``directory`` up to "/" belongs to this user or to root, and none can be changed by anyone else: no
    group or other write bit, except a sticky folder (like /tmp) that a trusted owner has, where nobody can replace what is
    inside it that is not theirs."""
    current = directory
    while True:
        try:
            info = os.stat(current)
        except OSError as exc:
            raise _unsafe_binary(f"所在的資料夾無法確認（{exc.strerror or type(exc).__name__}）") from exc
        if not _trusted_owner(info.st_uid):
            raise _unsafe_binary("所在的路徑上有別人的資料夾")
        if info.st_mode & 0o022 and not (info.st_mode & stat.S_ISVTX):
            raise _unsafe_binary("所在的路徑上有別人可以改動的資料夾")
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def locate_binary(search_path: str | None = None) -> str:
    """The real path of the first executable file named ``agy`` on the search path (``daemon.cli_search_path()``, the one the
    full-mode terminal looks along, unless one is given), after the checks that make it the person's own program: a plain
    file owned by this user (or by root), that nobody else can write, in folders (its link's and its own) that nobody else can
    change. AgyRefused ``not_installed`` when there is none, ``unsafe_binary`` when the first one found is not safe (later
    entries are not tried: the same file must be found every time). The program is not run here."""
    if search_path is None:
        from . import daemon                                 # not at import time: the daemon imports the chat code
        search_path = daemon.cli_search_path()
    for folder in search_path.split(os.pathsep):
        if not folder or not os.path.isabs(folder):
            continue
        candidate = os.path.join(folder, BINARY_NAME)
        try:
            info = os.stat(candidate)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or not os.access(candidate, os.X_OK):
            continue
        real = os.path.realpath(candidate)
        try:
            real_info = os.lstat(real)
        except OSError as exc:
            raise _unsafe_binary(f"無法確認（{exc.strerror or type(exc).__name__}）") from exc
        if not stat.S_ISREG(real_info.st_mode) or not _trusted_owner(real_info.st_uid) or real_info.st_mode & 0o022:
            raise _unsafe_binary("不是本人的一般檔案，或別人可以改動它")
        _check_chain(os.path.dirname(real))
        _check_chain(os.path.realpath(folder))
        return real
    raise AgyRefused("not_installed", "找不到 AGY。請到「開始設定」安裝 AGY。")


def read_version(binary: str) -> str:
    """``agy --version`` run from "/" with the daemon's safe environment and no input: its output must be exactly one line,
    X.Y.Z, and the exit code 0. AgyRefused ``version_unreadable`` otherwise (the sentence does not carry what it printed)."""
    def unreadable(why: str) -> AgyRefused:
        return AgyRefused("version_unreadable", f"AGY 沒有印出剛好是 X.Y.Z 的版本行（{why}），所以不使用它。")
    try:
        code, out, err = cli_versions.run_capture([binary, "--version"], "/", cli_versions._probe_environment(),
                                                  STATUS_TIMEOUT_S, 4096)
    except Exception as exc:
        raise unreadable(f"無法執行：{type(exc).__name__}") from exc
    if err:
        raise unreadable("執行失敗或逾時")
    if code != 0:
        raise unreadable(f"結束碼 {code}")
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        raise unreadable("輸出不是 UTF-8") from None
    match = VERSION_OUT.fullmatch(text)
    if not match:
        raise unreadable("輸出不是剛好一行版本號")
    return match.group(1)


def pinned_binary(search_path: str | None = None, verified=None) -> PinnedAgy:
    """The AGY that may chat: located (``locate_binary``), its version read (``read_version``), the version one of
    ``KNOWN_VERSIONS`` (``unsupported`` otherwise) and one that passed the chat check on this Mac (``unverified`` otherwise;
    ``verified`` is given by tests). The file must be the same one before and after the run. AgyRefused carries the version
    when it was read."""
    verified = cli_versions.agy_chat_verified_versions() if verified is None else verified
    binary = locate_binary(search_path)
    try:
        before = cli_identity(binary)
    except OSError as exc:
        raise _unsafe_binary("不是可以執行的一般檔案") from exc
    version = read_version(binary)
    if not unchanged(binary, before):
        raise AgyRefused("version_unreadable", "AGY 的執行檔在檢查版本的時候被換掉了，所以不使用它。")
    if version not in KNOWN_VERSIONS:
        raise AgyRefused("unsupported", f"AGY {version} 不是 VBear 能聊天的版本。VBear 目前能聊天的 AGY 版本："
                         + "、".join(KNOWN_VERSIONS) + "。", version)
    if version not in verified:
        raise AgyRefused("unverified", cli_versions.agy_chat_unverified_text(version), version)
    return PinnedAgy(binary, version, before)


# ---- the answer ------------------------------------------------------------------------------------------------------

_cache: dict = {}
_cache_lock = threading.Lock()


def invalidate() -> None:
    with _cache_lock:
        _cache.clear()


def status(base, *, home=None, root: str | None = None, search_path: str | None = None, force: bool = False) -> dict:
    """May this Mac chat with AGY now? One dict, no path and no command output in it:

    state: "not_installed" | "unsupported" | "unverified" | "policy" | "hooks" | "folder" | "version_unreadable" | "ready"
    (the first that does not hold, in the order of the checks: binary and version, then the policy, the hooks, the folder)
    installed / version (the one AGY printed, when it was read) / verified / shared_verified (the shared-folder part of the
    check passed too) / admin_policy_ok and hooks_ok (None until they were asked) / why (the sentence for a person; "" when
    ready) / verified_versions. Not logged in is not a state here: the chat check needs the real login, and "not logged in"
    shows when a chat starts (``not_logged_in``). Nothing is made on disk. ``home`` is the person's HOME (the hooks), ``root``
    where the administrator policy is looked for, ``search_path`` where ``agy`` is looked for (all three are given by tests)."""
    root = POLICY_ROOT if root is None else root
    key = (os.fspath(base), str(home or ""), root, search_path or "")
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and CACHE_TTL_S > 0 and now - hit[0] < CACHE_TTL_S:
            return dict(hit[1], verified_versions=list(hit[1]["verified_versions"]))
    out = _look(base, home, root, search_path)
    with _cache_lock:
        if CACHE_TTL_S > 0:
            _cache[key] = (now, out)
    return dict(out, verified_versions=list(out["verified_versions"]))


def _look(base, home, root, search_path) -> dict:
    verified = cli_versions.agy_chat_verified_versions()
    out = {"state": "", "installed": False, "version": None, "verified": False, "shared_verified": False,
           "admin_policy_ok": None, "hooks_ok": None, "why": "",
           "verified_versions": sorted(verified, key=cli_versions._version_key)}
    try:
        pinned = pinned_binary(search_path, verified)
    except AgyRefused as exc:
        out.update(installed=exc.code != "not_installed", version=exc.version, why=str(exc),
                   state={"not_installed": "not_installed", "unsupported": "unsupported",
                          "unverified": "unverified"}.get(exc.code, "version_unreadable"))
        return out
    out.update(installed=True, version=pinned.version, verified=True,
               shared_verified=cli_versions.shared_verified("agy-chat", pinned.version))
    policy = admin_policy.check_agy(pinned.version, root)
    out["admin_policy_ok"] = policy.ok
    if not policy.ok:
        out.update(state="policy", why=policy.reason())
        return out
    hooks, why = home_hooks_state(home)
    out["hooks_ok"] = hooks == "absent"
    if hooks != "absent":
        out.update(state="hooks", why=why)
        return out
    folder, why = home_state(base)
    if folder == "refused":
        out.update(state="folder", why=why)
        return out
    out["state"] = "ready"
    return out
