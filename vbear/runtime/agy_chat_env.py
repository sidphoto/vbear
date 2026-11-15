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
``~/.agents/hooks.json`` and the other hooks and plugins places of the four customization roots (commands and programs AGY
starts by itself; their presence refuses the chat, ``home_hooks_state``) and the top level of a chat's work folder (``.agents``,
``.agent``, ``_agents``, ``_agent``, ``.gemini``, ``GEMINI.md`` and ``AGENTS.md`` there are read by AGY as project settings and
rules; ``check_workdir``). The person's skills in ``~/.agents/skills`` are loaded by AGY anyway: the person
accepted that (ADR 0012), and the screen says so.

Every check either returns a value that was checked or says why not. ``agy --version`` is the only program run, and it
starts AGY but not a model. Nothing of what AGY prints is kept apart from the version it is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .. import admin_policy
from . import agy_chat_protocol as acp, cli_versions, review_codex, review_store

CHAT_HOME_NAME = "agy-chat-home"
CLI_DIR = "antigravity-cli"
SETTINGS_NAME = "settings.json"
HOME_LIMIT = review_codex.HOME_LIMIT          # 512 MiB: a monitoring threshold, not a hard cap (counted as Codex's is)
STATUS_TIMEOUT_S = 10.0
CACHE_TTL_S = 10.0
POLICY_ROOT = "/"                              # where the administrator policy is looked for (tests give another root)

# Everything that depends on the version of AGY is written once, in the protocol's version table (agy_chat_protocol.VERSIONS, P46-1):
# the settings VBear makes AGY read (ADR 0012, decision 1; "useG1Credits" is the paid-credits switch, and that it is a key of this
# file is read from the binary's strings, not proven, and the chat check says whether AGY still starts with it), the names that
# must not be in the chat folder and at the top of a work folder. The names below are that table's own objects, not copies; a test
# (tests/test_p46_agy_chat_launch.py) holds them to it, and so does rule 14b of tests/test_autonomy_guard.py.
CONFIG_DIR = "config"
NEWEST_VERSION = max(acp.VERSIONS, key=cli_versions._version_key)
_NEWEST = acp.VERSIONS[NEWEST_VERSION]
# The tables below are the newest version's. They are the same in every version VBear knows (the settings VBear writes, the names it
# never writes, the names AGY makes by itself, the names refused in a work folder): a test (tests/test_p46_agy_chat_env.py) and rule 20 of
# tests/test_autonomy_guard.py hold every version to that, so that a table that starts to differ is made per version before it is used.
# The one table that does differ between versions, AGY's own built-in content, is read per version (``builtin_table``).
SETTINGS = _NEWEST.settings
SETTINGS_BYTES = acp.settings_bytes(_NEWEST)
# Names VBear never writes in the chat folder: finding one means another program put it there. (name as shown, where it sits)
FORBIDDEN_TOP = tuple(n for n in _NEWEST.home_forbidden if "/" not in n)
FORBIDDEN_CONFIG = tuple(n.split("/", 1)[1] for n in _NEWEST.home_forbidden if n.startswith(CONFIG_DIR + "/"))
# The names AGY makes there itself (the same table): at the top of the folder and in its config folder. Any other name is refused.
CREATED_TOP = tuple(n for n in _NEWEST.home_created if "/" not in n)
CREATED_CONFIG = tuple(n.split("/", 1)[1] for n in _NEWEST.home_created if n.startswith(CONFIG_DIR + "/"))
PROJECTS_NAME = "projects"
PROJECT_ENTRIES = _NEWEST.project_entries
FORBIDDEN_ANYWHERE = _NEWEST.forbidden_anywhere
PROJECTS_MAX_DEPTH = 4                         # project folder = depth 1
PROJECTS_MAX_ENTRIES = 200
CLI_MAX_DEPTH = 10
CLI_MAX_ENTRIES = 20_000
CREATED_CLI = tuple(n.split("/", 1)[1] for n in _NEWEST.home_created if n.startswith(CLI_DIR + "/"))
CLI_CLOSED = {name: frozenset(allowed) for name, allowed in _NEWEST.cli_closed}   # folders of antigravity-cli with a closed list of names
BUILTIN_NAME = "builtin"


class BuiltinTable(NamedTuple):
    """AGY's own built-in content (``antigravity-cli/builtin``) as one version of AGY writes it, from the protocol's table: the exact paths
    (nothing else is let through there), which of them are folders, the SHA-256 of every file and the endings of files that can run."""
    version: str
    paths: frozenset
    dirs: frozenset
    sha: dict                                          # path -> sha256 hex of the file
    runnable: tuple


def _builtin_table(consts) -> BuiltinTable:
    paths = frozenset(consts.builtin_paths)
    return BuiltinTable(consts.version, paths, frozenset(p for p in paths if any(q.startswith(p + "/") for q in paths)),
                        dict(consts.builtin_sha256), tuple(consts.builtin_runnable))


BUILTIN_TABLES = {version: _builtin_table(consts) for version, consts in acp.VERSIONS.items()}      # (a test patches it)
BUILTIN_HASH_MAX = 4 << 20                             # a pinned file is read up to this many bytes
LETTERS_DIFFER = object()                              # table_folder: it is spelled with other letters than the table's
MCP_CONFIG_NAME = "mcp_config.json"
MCP_CONFIG_MAX = 64 << 10

# Names at the top of a work folder (or an open shared folder) that AGY reads as settings and rules.
WORKDIR_FORBIDDEN = _NEWEST.workdir_forbidden
WORKDIR_SCAN_MAX = 10_000
HOOKS_FILE = ".agents/hooks.json"             # under the person's HOME; looked for, never read
# The places in the person's HOME where AGY reads hooks or plugins from (a plugin may carry hooks and an MCP server it starts). AGY's own
# guide (``skills/agy-customizations``, the same bytes in 1.5.3 and 1.5.6) names four folder spellings as the "customization root"; each is
# only looked at (``lstat``), never opened, for these three names (P56-2).
HOOKS_ROOTS = (".agents", ".agent", "_agents", "_agent")
HOOKS_ITEMS = ("hooks.json", "plugins.json", "plugins")
CHAT_WORK_NAME = "chat-work"                  # ``chat_store.WORK``: the folder of the chats' work folders in the state folder (a test holds them equal)
HOOKS_PLACES = tuple(f"{root}/{item}" for root in HOOKS_ROOTS for item in HOOKS_ITEMS)

# Versions this code knows how to run: the protocol table's keys. The binary's version is matched against this list.
KNOWN_VERSIONS = tuple(acp.VERSIONS)
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


def _refuse_strangers(names, known, exact: bool = False) -> None:
    """AgyRefused when a name is neither one AGY makes by itself nor one VBear writes (compared without regard to case, or, with
    ``exact``, with the very letters of the table)."""
    allowed = set(known) if exact else {n.casefold() for n in known}
    strangers = sorted(n for n in names if (n if exact else n.casefold()) not in allowed)
    if strangers:
        raise _foreign("、".join(strangers[:5]))


def _collect_tree(first_fd: int, label: str, max_depth: int, max_entries: int):
    """(the names below the folder ``first_fd`` is open on as [(where, depth, mode)], the first place that was too deep or too many
    or None). Walked by descriptor, nothing followed; ``first_fd`` is closed. Only names and modes are looked at."""
    found: list[tuple[str, int, int]] = []
    stack: list[tuple[int, tuple]] = [(first_fd, ())]
    too_much = None
    try:
        while stack and too_much is None:
            fd, parts = stack.pop()
            try:
                try:
                    with os.scandir(fd) as it:
                        entries = list(it)
                    for entry in entries:
                        where = "/".join((*parts, entry.name))
                        st = entry.stat(follow_symlinks=False)
                        found.append((where, len(parts), st.st_mode))
                        if len(found) > max_entries:
                            too_much = where
                            break
                        if stat.S_ISDIR(st.st_mode):
                            if len(parts) + 1 >= max_depth:
                                too_much = where
                                break
                            stack.append((os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                                  dir_fd=fd), (*parts, entry.name)))
                except OSError as exc:
                    raise AgyRefused("foreign_settings", f"無法列出 AGY 的 {label} 資料夾（{exc.strerror or type(exc).__name__}），"
                                     "所以不使用聊天用的 AGY 設定資料夾") from exc
            finally:
                os.close(fd)
    finally:
        for fd, _ in stack:
            try:
                os.close(fd)
            except OSError:
                pass
    return found, too_much


def _is_forbidden_name(name: str) -> bool:
    folded = name.casefold()
    return folded.split(".", 1)[0] in FORBIDDEN_ANYWHERE or folded in ("gemini.md", "agents.md")


def _check_projects(cfd) -> None:
    """``config/projects``, when it is there: a plain folder; in it only plain folders, and in those only the names of
    ``PROJECT_ENTRIES`` (none are known yet, so they must be empty). A name that is a hook, rule, workflow, skill, plugin, setting
    or instruction file is refused at any depth, in any letters (and named first); so is a link, a file where a folder belongs,
    anything deeper than ``PROJECTS_MAX_DEPTH`` and anything past ``PROJECTS_MAX_ENTRIES`` names. Only names are looked at; the
    sentence says where in ``projects`` (``p/a/b``), never a path of the disk."""
    try:
        os.lstat(PROJECTS_NAME, dir_fd=cfd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _foreign(PROJECTS_NAME) from exc
    try:
        first = os.open(PROJECTS_NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=cfd)
    except OSError as exc:
        raise _foreign(PROJECTS_NAME) from exc
    found, too_much = _collect_tree(first, PROJECTS_NAME, PROJECTS_MAX_DEPTH, PROJECTS_MAX_ENTRIES)
    for where, depth, mode in found:                    # the forbidden names first, at any depth
        if _is_forbidden_name(where.rsplit("/", 1)[-1]):
            raise _foreign("projects/" + where)
    if too_much is not None:
        raise _foreign("projects/" + too_much)
    known = {n.casefold() for n in PROJECT_ENTRIES}
    for where, depth, mode in found:
        name = where.rsplit("/", 1)[-1]
        if depth == 0 and not stat.S_ISDIR(mode):
            raise _foreign("projects/" + where)         # a project is a folder (a link or a file is not)
        if depth >= 1 and (name.casefold() not in known or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
            raise _foreign("projects/" + where)


def builtin_table(version=None) -> BuiltinTable:
    """The built-in table of the AGY ``version`` (the newest known one when None). AgyRefused ``unsupported`` for a version VBear has no
    table for: the folder is never checked against another version's paths."""
    key = NEWEST_VERSION if version is None else version
    table = BUILTIN_TABLES.get(key) if isinstance(key, str) else None
    if table is None:
        raise AgyRefused("unsupported", f"AGY {str(key)[:32]} 沒有內建檔案的表，所以不使用聊天用的 AGY 設定資料夾。")
    return table


def pinned_hashes(rel: str) -> frozenset:
    """Every SHA-256 that any AGY version VBear knows pins for the built-in file ``rel``, none when no version pins it. AGY's own
    files only: a folder an older AGY wrote is still AGY's own after AGY updated itself (ADR 0018). A hash in no table is in none."""
    return frozenset(table.sha[rel] for table in BUILTIN_TABLES.values() if rel in table.sha)


def builtin_executable_like(rel: str) -> bool:
    """Whether a built-in file can run or be run by something, by the ending of its name (any letters): the endings of every known
    version together, so that an ending one version names is enough to need a pinned hash."""
    endings = tuple(sorted({e for table in BUILTIN_TABLES.values() for e in table.runnable}))
    return rel.casefold().endswith(endings)


def table_folder(where: str):
    """The one function that says which folder of the table a path below ``antigravity-cli`` is in: ``builtin`` or a closed folder
    (``CLI_CLOSED``), spelled exactly as the table spells it; ``LETTERS_DIFFER`` when its first part is the same word in other letters
    (that is never the table's folder); None for any other path."""
    first = where.split("/", 1)[0]
    for name in (BUILTIN_NAME, *CLI_CLOSED):
        if first == name:
            return name
        if first.casefold() == name.casefold():
            return LETTERS_DIFFER
    return None


def _file_sha256(fd: int, parts) -> str | None:
    """The SHA-256 of the plain file ``antigravity-cli/<parts>`` below the folder ``fd`` is open on, or None (not a plain file, a link on
    the way, too big, unreadable). Every part is opened without following a link; only the hash leaves this function."""
    opened = []
    try:
        cur = fd
        for part in (CLI_DIR, *parts[:-1]):
            cur = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=cur)
            opened.append(cur)
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0), dir_fd=cur)
        opened.append(leaf)
        if not stat.S_ISREG(os.fstat(leaf).st_mode):
            return None
        digest, size = hashlib.sha256(), 0
        while True:
            chunk = os.read(leaf, 1 << 16)
            if not chunk:
                return digest.hexdigest()
            size += len(chunk)
            if size > BUILTIN_HASH_MAX:
                return None
            digest.update(chunk)
    except OSError:
        return None
    finally:
        for each in opened:
            try:
                os.close(each)
            except OSError:
                pass


def _check_builtin_entry(fd, where: str, mode: int, table: BuiltinTable) -> None:
    """One path below ``antigravity-cli/builtin`` (``where`` starts with ``builtin/``): it must be a path of ``table`` (the AGY version that
    is about to start), a folder where the table has something below it and a plain file otherwise; a plain file with a pinned hash must
    have one of the hashes any known version pins for that path (``pinned_hashes``), and one that can run and has none is refused.
    AgyRefused (naming ``where``) when not."""
    rel = where[len(BUILTIN_NAME) + 1:]
    is_dir = rel in table.dirs
    if rel not in table.paths or not (stat.S_ISDIR(mode) if is_dir else stat.S_ISREG(mode)):
        raise _foreign(CLI_DIR + "/" + where)
    if is_dir:
        return
    pinned = pinned_hashes(rel)
    if not pinned:
        if builtin_executable_like(rel):
            raise _foreign(CLI_DIR + "/" + where)
        return
    if _file_sha256(fd, (*where.split("/"),)) not in pinned:
        raise _foreign(CLI_DIR + "/" + where)


def _check_cli_dir(fd, table: BuiltinTable) -> None:
    """``antigravity-cli`` (AGY's own working folder, with VBear's ``settings.json`` in it), when it is there: a plain folder whose
    top level holds only the names of ``CREATED_CLI``. Below the top level nothing is allowed that is named like a hook, rule,
    workflow, skill, plugin, setting or instruction file, at any depth (so an AGY that puts such a thing in its cache folders is
    refused by name and a person decides), and nothing but folders and plain files. The one exception is ``builtin``: AGY's own
    built-in skills and plugin, named like the things refused elsewhere. Inside it only the exact paths of ``table.paths`` (the table of the
    version about to start) pass and any other path is refused, so what is not on the table is never let in by its name."""
    try:
        st = os.lstat(CLI_DIR, dir_fd=fd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _foreign(CLI_DIR) from exc
    if not stat.S_ISDIR(st.st_mode):
        return                                           # a link or a file there is for the code that writes the settings to refuse
    try:
        first = os.open(CLI_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    except OSError as exc:
        raise _foreign(CLI_DIR) from exc
    found, too_much = _collect_tree(first, CLI_DIR, CLI_MAX_DEPTH, CLI_MAX_ENTRIES)
    top = [w for w, depth, _ in found if depth == 0]
    _refuse_strangers(top, CREATED_CLI, exact=True)        # AGY spells its folders one way: other letters are a stranger
    for where, depth, mode in found:
        folder = table_folder(where)
        if folder is LETTERS_DIFFER:
            raise _foreign(CLI_DIR + "/" + where)
        if folder == BUILTIN_NAME:                         # AGY's own built-in content: only the paths of the table, exactly
            if depth >= 1:
                _check_builtin_entry(fd, where, mode, table)
        elif folder is not None:                           # a folder AGY made whose content nobody knows: only the listed names
            if depth >= 1 and (where.split("/", 1)[1] not in CLI_CLOSED[folder] or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                raise _foreign(CLI_DIR + "/" + where)
        elif depth >= 1 and _is_forbidden_name(where.rsplit("/", 1)[-1]):
            raise _foreign(CLI_DIR + "/" + where)
    if too_much is not None:
        raise _foreign(CLI_DIR + "/" + too_much)


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


def check_chat_home(base, *, size: bool = True, home=None, version=None) -> Path:
    """The folder is usable: ours, 0700, no link on its path, none of ``FORBIDDEN_TOP`` at its top and none of
    ``FORBIDDEN_CONFIG`` in its config folder (whatever kind of entry, a link included; compared without regard to case,
    as the Mac's file system does), an MCP configuration that is missing or says nothing, and within the size threshold
    (``size=False`` leaves the count out). AgyRefused otherwise. Only names are looked at, and the MCP file is read.

    ``version`` is the AGY that is about to start (the newest known one when None): its built-in table gives the paths that may be
    in ``antigravity-cli/builtin``, and a file there passes with the hash of any known version (``pinned_hashes``)."""
    table = builtin_table(version)
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
        _refuse_strangers(top, CREATED_TOP)
        _check_cli_dir(fd, table)
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
                _refuse_strangers(_names(cfd), CREATED_CONFIG)
                _check_projects(cfd)
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


def ensure_chat_home(base, *, size: bool = True, version=None) -> Path:
    """Make the folder (0700) when it is not there, then check it (for the AGY ``version``). An existing folder is never repaired or changed."""
    builtin_table(version)                          # a version without a table makes nothing
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
    return check_chat_home(base, size=size, version=version)


def home_state(base, home=None, version=None) -> tuple[str, str]:
    """("missing" | "ok" | "refused", why): a look that makes nothing. A folder that is not there yet is not a problem."""
    try:
        os.lstat(Path(home) if home else chat_home_path(base))
    except FileNotFoundError:
        return "missing", ""
    except OSError as exc:
        return "refused", f"無法確認聊天用的 AGY 設定資料夾（{exc.strerror or type(exc).__name__}）"
    try:
        check_chat_home(base, home=home, version=version)
    except AgyRefused as exc:
        return "refused", str(exc)
    return "ok", ""


# ---- settings.json ---------------------------------------------------------------------------------------------------

def write_settings(base, home=None, version=None) -> Path:
    """Write ``antigravity-cli/settings.json`` with the fixed content, before every process starts (and make the folder and
    ``antigravity-cli/`` first when they are not there). The file is written to a new name in the same folder and renamed over
    the old one: a link or a file someone left in its place is replaced, never followed or written through. 0600. A link or a
    file in place of ``antigravity-cli``, or a folder in place of the file, is refused. AgyRefused otherwise."""
    if home is None:
        ensure_chat_home(base, size=False, version=version)         # the size is the status's business: a big folder must not keep the file from being repaired
    else:
        check_chat_home(base, home=home, size=False, version=version)
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
    """("absent" | "present" | "unreadable", why): ``lstat`` of each of ``HOOKS_PLACES`` (hooks.json, plugins.json and plugins in
    ~/.agents, ~/.agent, ~/_agents and ~/_agent) and nothing else; nothing is opened or listed.
    "absent" only when the system says every name is not there. Anything there (a file, a folder, a link, a dangling link) and
    any other failure to tell is a refusal: hooks are commands AGY runs by itself, and a plugin may carry hooks and an MCP server
    AGY starts, which VBear can neither ask about nor stop."""
    root = os.fspath(home) if home else str(Path.home())
    for place in HOOKS_PLACES:
        try:
            os.lstat(os.path.join(root, place))
        except FileNotFoundError:
            continue
        except OSError as exc:
            return "unreadable", (f"無法確認 ~/{place} 存不存在（{exc.strerror or type(exc).__name__}），所以不啟動 AGY 聊天。")
        return "present", ("你自己的 AGY 設定裡有 hooks 或外掛（hooks 是 AGY 會自動執行的指令，外掛可以帶 hooks 或自己啟動的程式）。"
                           f"AGY 聊天會載入它們，VBear 管不到，所以不啟動。把 ~/{place} 移走（VBear 不會替你動）才能用 AGY 聊天。")
    return "absent", ""


def _folders_above(path, include_self: bool = False) -> list[str]:
    """The folders above ``path`` (nearest first, up to ``/``), as the path is written and then as the file system has it (AGY's own
    working folder is the real one), without a repeat. ``path`` itself only with ``include_self``."""
    out: list[str] = []
    for form in (os.path.abspath(os.fspath(path)), os.path.realpath(os.fspath(path))):
        current = form if include_self else os.path.dirname(form)
        while True:
            if current not in out:
                out.append(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return out


def _shown(path: str, homes) -> str:
    """``path`` for a sentence: the person's home written as ``~``; any other folder as it is (it is the person's own, and the sentence
    has to say which one to move)."""
    for home in homes:
        if home and home != "/" and (path == home or path.startswith(home.rstrip("/") + "/")):
            return "~" + path[len(home.rstrip("/")):]
    return path


def ancestor_hooks_state(path, home=None, *, include_self: bool = False) -> tuple[str, str]:
    """("absent" | "present" | "unreadable", why): the same twelve places as ``home_hooks_state`` (``hooks.json``, ``plugins.json`` and
    ``plugins`` in ``.agents``, ``.agent``, ``_agents`` and ``_agent``), looked at by ``lstat`` in every folder above ``path`` up to the
    file system root, and nothing else; nothing is opened or listed. AGY looks for its customization roots from the folder it starts
    in up to the repository root (its own guide, the same in 1.5.3 and 1.5.6), so ``$HOME/project/_agent/hooks.json`` is loaded by
    a chat whose state folder is ``$HOME/project/.vbear``. The person's HOME is left to ``home_hooks_state`` (not counted twice).
    Anything there is a refusal, and so is every failure to tell except "there is no such name" (a file where a root folder would be
    has no ``hooks.json`` in it). ``include_self``: ``path`` itself too (a folder that is not a work folder, like the state folder)."""
    home_root = os.fspath(home) if home else str(Path.home())
    homes = {h for h in (os.path.abspath(home_root), os.path.realpath(home_root)) if h}
    for folder in _folders_above(path, include_self):
        if folder in homes:
            continue
        for place in HOOKS_PLACES:
            where = os.path.join(folder, place)
            shown = _shown(where, homes)
            if len(shown) > 110:
                shown = "…" + shown[-109:]
            try:
                os.lstat(where)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError as exc:
                return "unreadable", f"無法確認 {shown} 存不存在（{exc.strerror or type(exc).__name__}），所以不啟動 AGY 聊天。"
            return "present", (f"AGY 會從聊天的工作資料夾往上找設定，在 {shown} 找到 hooks 或外掛（會自動執行的指令或程式），VBear 管不到，所以不啟動 AGY 聊天。"
                               "請把它移走，或把 VBear 的資料夾（VBEAR_HOME）放到別處。")
    return "absent", ""


def check_ancestors(path, home=None, *, include_self: bool = False, code: str = "agy_hooks"):
    """``path`` unchanged when ``ancestor_hooks_state`` finds nothing above it; AgyRefused (``code``) with its sentence otherwise."""
    state, why = ancestor_hooks_state(path, home, include_self=include_self)
    if state != "absent":
        raise AgyRefused(code, why)
    return path


# ---- the work folder -------------------------------------------------------------------------------------------------

def check_workdir(path, *, code: str = "agy_workdir", label: str = "工作資料夾") -> Path:
    """The folder AGY will be started in (a chat's work folder, or an open shared folder with ``code="shared_unsafe"`` and
    ``label="共用資料夾"``) holds nothing AGY would read as settings or rules, and no link that leads out of it. A folder that is
    not there yet passes (it is made later). Names and links only: no file is opened, no link is followed (a link is
    resolved as a name, to see where it ends), and at most ``WORKDIR_SCAN_MAX`` entries are looked at. AgyRefused (``code``)
    otherwise, with a sentence that names the entry (one of the fixed names) but no path.

    - the top level has none of ``WORKDIR_FORBIDDEN`` (compared without regard to case): AGY reads ``.agents`` and its spellings ``.agent``, ``_agents``, ``_agent`` (skills, hooks,
      plugins, workflows, agents), ``.gemini``, ``GEMINI.md`` and ``AGENTS.md`` as project settings and rules;
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
    keeps, so a file that changed after the check is seen at the next start). ``kept`` (P62, ADR 0021): it is the copy VBear kept
    of a version that passed the chat check, chosen because the AGY on the search path is a version that cannot chat; ``installed``
    is then the version that one printed."""
    binary: str
    version: str
    identity: list
    kept: bool = False
    installed: str | None = None


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
        check_binary_file(real)
        _check_chain(os.path.realpath(folder))
        return real
    raise AgyRefused("not_installed", "找不到 AGY。請到「開始設定」安裝 AGY。")


def check_binary_file(real: str) -> None:
    """The checks that make a file the person's own program (``locate_binary`` makes them on what it finds; the chat check makes them
    on the AGY it is given, P62): a plain file owned by this user (or by root) that nobody else can write, in folders that nobody else
    can change. ``real`` is the file's own path (no link on the way is followed here; the caller resolved it). AgyRefused
    ``unsafe_binary`` otherwise."""
    try:
        real_info = os.lstat(real)
    except OSError as exc:
        raise _unsafe_binary(f"無法確認（{exc.strerror or type(exc).__name__}）") from exc
    if not stat.S_ISREG(real_info.st_mode) or not _trusted_owner(real_info.st_uid) or real_info.st_mode & 0o022:
        raise _unsafe_binary("不是本人的一般檔案，或別人可以改動它")
    _check_chain(os.path.dirname(real))


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


def pinned_binary(search_path: str | None = None, verified=None, *, base=None) -> PinnedAgy:
    """The AGY that may chat: located (``locate_binary``), its version read (``read_version``), the version one of
    ``KNOWN_VERSIONS`` (``unsupported`` otherwise) and one that passed the chat check on this Mac (``unverified`` otherwise;
    ``verified`` is given by tests). The file must be the same one before and after the run. AgyRefused carries the version
    when it was read.

    ``base`` (P62, ADR 0021) is the state folder the kept copies are in. Given, and the AGY found is safe and printed a version but
    that version is ``unsupported`` or ``unverified``, the newest copy VBear kept of a version that passed the chat check is
    pinned instead (``agy_kept.choose``: every condition, the whole file's SHA-256 included); none that holds, and the refusal is
    the one above. An AGY that is not installed, not safe or whose version cannot be read is never replaced by a copy. Without
    ``base`` nothing is kept (the chat check asks for the AGY on the search path itself)."""
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
        refusal = AgyRefused("unsupported", f"AGY {version} 不是 VBear 能聊天的版本。VBear 目前能聊天的 AGY 版本："
                             + "、".join(KNOWN_VERSIONS) + "。", version)
    elif version not in verified:
        refusal = AgyRefused("unverified", cli_versions.agy_chat_unverified_text(version), version)
    else:
        return PinnedAgy(binary, version, before)
    if base is not None:
        from . import agy_kept                               # not at import time: it imports this module
        kept = agy_kept.choose(base)
        if kept is not None:
            return PinnedAgy(kept.binary, kept.version, kept.identity, True, version)
    raise refusal


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
    ready; the hooks sentence names the folder it found, the home written as ``~``) / verified_versions. Only when the chat runs the
    copy VBear kept of a version that passed (P62, ADR 0021, because the AGY on the search path cannot chat): ``kept`` =
    {using, installed, installed_state}, ``version`` is then the one that runs (``using``), ``installed`` the one on the search path and
    ``installed_state`` "unsupported" (VBear does not know it) or "unverified" (known, not checked yet). Not logged in is not a state here: the chat check needs the real login, and "not logged in"
    shows when a chat starts (``not_logged_in``). Nothing is made on disk. ``home`` is the person's HOME (the hooks), ``root``
    where the administrator policy is looked for, ``search_path`` where ``agy`` is looked for (all three are given by tests)."""
    root = POLICY_ROOT if root is None else root
    key = (os.fspath(base), str(home or ""), root, search_path or "")
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and CACHE_TTL_S > 0 and now - hit[0] < CACHE_TTL_S:
            return _copy(hit[1])
    out = _look(base, home, root, search_path)
    with _cache_lock:
        if CACHE_TTL_S > 0:
            _cache[key] = (now, out)
    return _copy(out)


def _copy(out: dict) -> dict:
    """The answer as a new dict, so that a caller cannot change the cached one."""
    copy = dict(out, verified_versions=list(out["verified_versions"]))
    if "kept" in out:
        copy["kept"] = dict(out["kept"])
    return copy


def _look(base, home, root, search_path) -> dict:
    verified = cli_versions.agy_chat_verified_versions()
    out = {"state": "", "installed": False, "version": None, "verified": False, "shared_verified": False,
           "admin_policy_ok": None, "hooks_ok": None, "why": "",
           "verified_versions": sorted(verified, key=cli_versions._version_key)}
    try:
        pinned = pinned_binary(search_path, verified, base=base)
    except AgyRefused as exc:
        out.update(installed=exc.code != "not_installed", version=exc.version, why=str(exc),
                   state={"not_installed": "not_installed", "unsupported": "unsupported",
                          "unverified": "unverified"}.get(exc.code, "version_unreadable"))
        return out
    out.update(installed=True, version=pinned.version, verified=True,
               shared_verified=cli_versions.shared_verified("agy-chat", pinned.version))
    if pinned.kept:                                  # P62: the AGY on the search path cannot chat; the copy kept of the one that passed does
        out["kept"] = {"using": pinned.version, "installed": pinned.installed,
                       "installed_state": "unsupported" if pinned.installed not in KNOWN_VERSIONS else "unverified"}
    policy = admin_policy.check_agy(pinned.version, root)
    out["admin_policy_ok"] = policy.ok
    if not policy.ok:
        out.update(state="policy", why=policy.reason())
        return out
    hooks, why = home_hooks_state(home)
    if hooks == "absent":                          # the folders above the work folders (<state>/chat-work/…) up to the root: AGY looks there too
        hooks, why = ancestor_hooks_state(os.path.join(os.fspath(base), CHAT_WORK_NAME), home, include_self=True)
    out["hooks_ok"] = hooks == "absent"
    if hooks != "absent":
        out.update(state="hooks", why=why)
        return out
    folder, why = home_state(base, version=pinned.version)
    if folder == "refused":
        out.update(state="folder", why=why)
        return out
    out["state"] = "ready"
    return out
