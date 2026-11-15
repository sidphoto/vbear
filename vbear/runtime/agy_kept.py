"""The AGY that VBear keeps (P62, v0.26.0, ADR 0021).

AGY updates itself by overwriting ``~/.local/bin/agy``, so the version that passed the chat check disappears at the next update and the
chat stops until VBear knows the new one and the person checks it. Claude Code and Codex keep their old versions in folders of their own;
AGY does not. So the chat check keeps what it checked: a copy of the very file it ran, in ``<state>/tools/agy/<version>/agy``.

What makes this safe is that nothing is taken on trust:

* the copy is made by VBear from the AGY on the search path (``locate_binary``'s checks), the SHA-256 is computed while it is written, and
  the chat check runs ``--agy <the copy>``: the file that was checked is the file that is kept (``stage``, ``promote``);
* the pass record carries the file's SHA-256 and size and the report says the same two (``cli_versions.local_agy_chat_kept_records``);
  no path is recorded: where a copy is follows from its version alone (``path_of``), so nothing in a JSON file can name a program to run;
* a copy is used (``choose``, ``check_for_launch``) only when everything holds, every time, and the whole file is hashed again: the folders
  are this user's own 0700 plain folders reached without a link, the folder holds the one file, the file is this user's own plain file with
  exactly mode 0500 and no other name (``st_nlink`` 1), its size and SHA-256 are the recorded ones, and ``--version`` prints its version.
  A copy for which any of it fails is skipped, never repaired or removed by the look;
* at most two copies are kept; only a folder that is named like a version, owned by this user, and holds nothing but ``agy`` is ever removed
  (a file first, then the folder; nothing is removed recursively and nothing is followed).

Every refusal is an ``agy_chat_env.AgyRefused`` whose sentence carries no path.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from . import agy_chat_env as env, cli_versions, review_store

TOOLS_DIR = "tools"
AGY_DIR = "agy"
BINARY_NAME = "agy"
STAGING_PREFIX = "staging-"
STAGING_RE = re.compile(r"staging-[0-9a-f]{16}\Z")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
FILE_MODE = 0o500                      # read and run for this user, nothing else: nobody (but root) writes it, not even this user without chmod
DIR_MODE = 0o700
KEEP = 2                               # copies kept in all (the one just made counts)
MAX_BYTES = 1 << 30                    # a program of this size is not AGY (the real one is about 235 MB)
SPACE_MARGIN = 256 << 20               # free space wanted beyond the file itself
CHUNK = 1 << 20
STALE_STAGING_S = 24 * 3600
_NOFOLLOW_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _refused(why: str, code: str = "kept") -> env.AgyRefused:
    return env.AgyRefused(code, why)


@dataclass(frozen=True)
class Staged:
    """A copy made for the chat check, not kept yet: ``name`` of its folder in ``root(base)``, the ``path`` of the file, its SHA-256 and size."""
    name: str
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Kept:
    """A kept copy that every condition holds for: the file's path, its version, ``cli_identity`` (six numbers) and SHA-256."""
    binary: str
    version: str
    identity: list
    sha256: str


# ---- where --------------------------------------------------------------------------------------------------------------

def root(base) -> str:
    """``<state>/tools/agy`` (the state folder resolved once; nothing below it is ever resolved)."""
    return os.path.join(os.path.realpath(os.fspath(base)), TOOLS_DIR, AGY_DIR)


def path_of(base, version) -> str:
    """Where the copy of ``version`` is: ``<state>/tools/agy/<version>/agy``. AgyRefused unless ``version`` is one the protocol table has."""
    if not (isinstance(version, str) and VERSION_RE.match(version) and version in env.KNOWN_VERSIONS):
        raise _refused("保留的 AGY 只能是 VBear 認得的版本。", "unsupported")
    return os.path.join(root(base), version, BINARY_NAME)


def is_kept_path(base, binary) -> bool:
    """Whether ``binary`` lies under the folder the copies are kept in (so that it must be one)."""
    return isinstance(binary, str) and binary.startswith(root(base) + os.sep)


# ---- folders, by descriptor ---------------------------------------------------------------------------------------------

def _mine(st, private: bool) -> bool:
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & (0o077 if private else 0o022)


def _open_child(parent_fd: int, name: str, *, private: bool, create: bool = False) -> int:
    """The folder ``name`` of the open folder ``parent_fd``, opened without following a link, found to be this user's own plain folder (made
    first with ``create``, mode 0700). AgyRefused otherwise. The caller closes the descriptor."""
    if create:
        try:
            os.mkdir(name, DIR_MODE, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _refused(f"無法建立保留 AGY 的資料夾（{exc.strerror or type(exc).__name__}）。") from exc
    try:
        fd = os.open(name, _NOFOLLOW_DIR, dir_fd=parent_fd)
    except OSError as exc:
        raise _refused(f"保留 AGY 的資料夾不存在，或是連結、不是資料夾（{exc.strerror or type(exc).__name__}）。") from exc
    try:
        if not _mine(os.fstat(fd), private):
            raise _refused("保留 AGY 的資料夾必須是本人的一般資料夾（0700），別人不能改動。")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_root(base, *, create: bool) -> int:
    """A descriptor on ``<state>/tools/agy``. With ``create`` the two folders are made when they are not there (0700); every folder
    on the way, the state folder included, is reached without following a link."""
    state = os.path.realpath(os.fspath(base))
    try:
        state_fd = review_store.open_dir_chain(state)
    except (OSError, ValueError) as exc:
        raise _refused(f"狀態資料夾無法開啟（{type(exc).__name__}）。") from exc
    try:
        tools_fd = _open_child(state_fd, TOOLS_DIR, private=False, create=create)
    finally:
        os.close(state_fd)
    try:
        return _open_child(tools_fd, AGY_DIR, private=True, create=create)
    finally:
        os.close(tools_fd)


def _hash_fd(fd: int) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while True:
        chunk = os.read(fd, CHUNK)
        if not chunk:
            return digest.hexdigest(), size
        digest.update(chunk)
        size += len(chunk)


def hash_file(path) -> tuple[str, int]:
    """(SHA-256 hex, size) of the whole file at ``path``, opened without following a link. OSError when it cannot be read."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        return _hash_fd(fd)
    finally:
        os.close(fd)


# ---- looking at a copy --------------------------------------------------------------------------------------------------

def _inspect(root_fd: int, name: str, sha256: str, size: int) -> list:
    """Everything that must hold for the folder ``name`` of the kept folder and its file; the file is hashed whole. Returns the file's
    ``cli_identity`` (read from the opened file). AgyRefused with the first thing that does not hold."""
    dir_fd = _open_child(root_fd, name, private=True)
    try:
        names = os.listdir(dir_fd)
        if names != [BINARY_NAME]:
            raise _refused("保留的 AGY 資料夾裡不只一個 agy 檔案（或不是剛好這一個），所以不使用它。", "unsafe_binary")
        try:
            lst = os.stat(BINARY_NAME, dir_fd=dir_fd, follow_symlinks=False)
            fd = os.open(BINARY_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
        except OSError as exc:
            raise _refused(f"保留的 AGY 檔案無法開啟（{exc.strerror or type(exc).__name__}）。", "unsafe_binary") from exc
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != FILE_MODE or st.st_nlink != 1
                    or (st.st_dev, st.st_ino) != (lst.st_dev, lst.st_ino)):
                raise _refused("保留的 AGY 不是本人的一般檔案、權限不是 0500，或有別的名字指向它，所以不使用它。", "unsafe_binary")
            if st.st_size != size:
                raise _refused("保留的 AGY 大小與通過紀錄不同，所以不使用它。", "unsafe_binary")
            digest, read = _hash_fd(fd)
            after = os.fstat(fd)
            if (after.st_mtime_ns, after.st_ctime_ns, after.st_size) != (st.st_mtime_ns, st.st_ctime_ns, st.st_size) or read != size:
                raise _refused("保留的 AGY 在檢查的時候被改動，所以不使用它。", "unsafe_binary")
            if digest != sha256:
                raise _refused("保留的 AGY 的 SHA-256 與通過紀錄不同，所以不使用它。", "unsafe_binary")
            return [st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


def _check_copy(base, version: str, record: dict, *, run: bool = True) -> Kept:
    """The copy of ``version`` against its record ({sha256, size}): ``_inspect``, the folders above it (nobody else can change them),
    a file that can run, and ``--version`` that prints the version (``run``: the daemon does not run it, the whole file's hash is what it
    checks). AgyRefused / OSError otherwise."""
    path = path_of(base, version)
    root_fd = _open_root(base, create=False)
    try:
        identity = _inspect(root_fd, version, record["sha256"], record["size"])
    finally:
        os.close(root_fd)
    env._check_chain(os.path.dirname(path))
    if env.cli_identity(path) != identity:
        raise _refused("保留的 AGY 在檢查的時候被換掉，所以不使用它。", "unsafe_binary")
    if run and env.read_version(path) != version:
        raise _refused("保留的 AGY 印出的版本與它的資料夾不符，所以不使用它。", "version_unreadable")
    return Kept(path, version, identity, record["sha256"])


def choose(base) -> Kept | None:
    """The newest kept copy that every condition holds for, or None. Versions come from this Mac's pass records that name a file
    (``local_agy_chat_kept_records``), only those the protocol table has; a copy that fails is skipped and the next older one is tried."""
    records = cli_versions.local_agy_chat_kept_records(Path(base))
    for version in sorted((v for v in records if v in env.KNOWN_VERSIONS), key=cli_versions._version_key, reverse=True):
        try:
            return _check_copy(base, version, records[version])
        except (env.AgyRefused, OSError):
            continue
    return None


def check_for_launch(base, version, binary, identity) -> bool:
    """The daemon's look before it starts an AGY whose file is under the kept folder (False for any other file: those keep the checks
    they always had). The file must be the copy of exactly this version, hold every condition again with the whole file hashed, and be the
    file the console looked at (``identity``, the six numbers). AgyRefused otherwise."""
    if not is_kept_path(base, binary):
        return False
    record = cli_versions.local_agy_chat_kept_records(Path(base)).get(version)
    if record is None:
        raise _refused("這個版本的通過紀錄沒有記下檔案的 SHA-256，所以不啟動保留的 AGY。", "unverified")
    if binary != path_of(base, version):
        raise _refused("保留的 AGY 的位置與它的版本不符，所以不啟動。", "unsafe_binary")
    try:
        kept = _check_copy(base, version, record, run=False)
    except OSError as exc:
        raise _refused(f"保留的 AGY 無法確認（{exc.strerror or type(exc).__name__}），所以不啟動。", "unsafe_binary") from exc
    if not (isinstance(identity, (list, tuple)) and list(identity) == kept.identity):
        raise _refused("保留的 AGY 檔案身分與主控台看到的不同，所以不啟動。", "drift")
    return True


# ---- making a copy ------------------------------------------------------------------------------------------------------

def _remove_folder(root_fd: int, name: str) -> bool:
    """Remove the folder ``name`` of the kept folder if it is this user's own plain folder holding nothing but ``agy`` (a file: unlinked
    first, then the folder). Anything else is left as it is and the answer is False. Nothing is followed, nothing removed recursively."""
    try:
        dir_fd = _open_child(root_fd, name, private=False)
    except env.AgyRefused:
        return False
    try:
        names = os.listdir(dir_fd)
        if names not in ([], [BINARY_NAME]):
            return False
        if names:
            st = os.stat(BINARY_NAME, dir_fd=dir_fd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
                return False
            os.unlink(BINARY_NAME, dir_fd=dir_fd)
    except OSError:
        return False
    finally:
        os.close(dir_fd)
    try:
        os.rmdir(name, dir_fd=root_fd)
    except OSError:
        return False
    return True


def _clean_old_staging(root_fd: int) -> None:
    """Remove ``staging-*`` folders a crashed check left (more than a day old)."""
    now = time.time()
    for name in os.listdir(root_fd):
        if STAGING_RE.match(name):
            try:
                st = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode) and now - st.st_mtime > STALE_STAGING_S:
                _remove_folder(root_fd, name)


def stage(base, source: str, version: str) -> Staged:
    """Copy the AGY at ``source`` (the real path ``locate_binary`` gave) to ``<state>/tools/agy/staging-<random>/agy``: a folder of 0700, a
    file created new (``O_EXCL``, no link followed) with mode 0500, its SHA-256 and size taken from what was written, read from the opened
    source. The copy's ``--version`` must print ``version``. Everything made is removed again when anything fails. AgyRefused / OSError."""
    if not VERSION_RE.match(version):
        raise _refused("版本的格式不對。")
    root_fd = _open_root(base, create=True)
    name = None
    try:
        _clean_old_staging(root_fd)
        src = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(src)
            if not stat.S_ISREG(info.st_mode) or not env._trusted_owner(info.st_uid) or info.st_mode & 0o022:
                raise env.AgyRefused("unsafe_binary", "找到的 AGY 執行檔不是本人的一般檔案，或別人可以改動它，所以不保存它。")
            if not 0 < info.st_size <= MAX_BYTES:
                raise _refused("AGY 執行檔的大小不合理，所以不保存它。")
            room = os.statvfs(root_fd)
            if room.f_bavail * room.f_frsize < info.st_size + SPACE_MARGIN:
                raise _refused(f"磁碟空間不夠：保存一份 AGY 要約 {info.st_size // (1 << 20) + SPACE_MARGIN // (1 << 20)} MB 的空間。")
            name = STAGING_PREFIX + secrets.token_hex(8)
            dir_fd = _open_child(root_fd, name, private=True, create=True)
            try:
                digest = _copy_into(src, dir_fd, info)
            finally:
                os.close(dir_fd)
        finally:
            os.close(src)
        path = os.path.join(root(base), name, BINARY_NAME)
        env.check_binary_file(path)
        if _version_of(path) != version:
            raise _refused(f"複製下來的 AGY 印出的版本不是 {version}，所以不保存它。", "version_unreadable")
        return Staged(name, path, digest, info.st_size)
    except BaseException:
        if name is not None:
            _remove_folder(root_fd, name)
        raise
    finally:
        os.close(root_fd)


def _version_of(path: str) -> str:
    """``agy --version`` of the file just written. A program that was written a moment ago can be refused with "text file busy" while another
    thread's child still holds the descriptor, so a refusal is tried again a few times."""
    for attempt in range(4):
        try:
            return env.read_version(path)
        except env.AgyRefused:
            if attempt == 3:
                raise
            time.sleep(0.25)
    raise AssertionError("unreachable")


def _copy_into(src: int, dir_fd: int, info) -> str:
    """Write the open source file to a new ``agy`` in the folder ``dir_fd`` and return the SHA-256 of what was written. The file is
    created only if it is not there (``O_EXCL``), with mode 0500, flushed to disk. The source must be as long at the end as at the start."""
    out = os.open(BINARY_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, FILE_MODE, dir_fd=dir_fd)
    try:
        digest, total = hashlib.sha256(), 0
        while True:
            chunk = os.read(src, CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                raise _refused("AGY 執行檔的大小不合理，所以不保存它。")
            view = memoryview(chunk)
            while view:
                view = view[os.write(out, view):]
        after = os.fstat(src)
        if total != info.st_size or (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
            raise _refused("AGY 執行檔在複製的時候被改動，所以不保存它。")
        os.fchmod(out, FILE_MODE)
        os.fsync(out)
    finally:
        os.close(out)
    return digest.hexdigest()


def discard(base, staged: Staged) -> None:
    """Remove what ``stage`` made, if it is still there (a copy that was kept has been renamed, and is not touched). Never raises."""
    if not STAGING_RE.match(staged.name):
        return
    try:
        root_fd = _open_root(base, create=False)
    except env.AgyRefused:
        return
    try:
        _remove_folder(root_fd, staged.name)
    finally:
        os.close(root_fd)


def promote(base, staged: Staged, version: str) -> list[str]:
    """Keep the staged copy as the copy of ``version``: it is looked at again as it is now (the whole file hashed against what was
    written), the folder is renamed to ``<state>/tools/agy/<version>`` (a copy of that version already there goes first), and the copy is
    looked at once more in its place, as the chat will, before the oldest copies beyond ``KEEP`` are removed. Returns the versions removed.
    AgyRefused / OSError; a copy that was moved is removed again when that last look fails."""
    path_of(base, version)                                     # the version is one the table has
    if not STAGING_RE.match(staged.name):
        raise _refused("保存的暫存資料夾名稱不對。")
    record = {"sha256": staged.sha256, "size": staged.size}
    root_fd = _open_root(base, create=False)
    try:
        _inspect(root_fd, staged.name, staged.sha256, staged.size)
        if os.path.lexists(os.path.join(root(base), version)) and not _remove_folder(root_fd, version):
            raise _refused(f"{version} 之前保留的那份無法移除（裡面不只一個 agy 檔案，或不是本人的），所以沒有保存新的。請自己看一下那個資料夾。")
        os.rename(staged.name, version, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        try:
            _inspect(root_fd, version, record["sha256"], record["size"])
            env._check_chain(os.path.dirname(path_of(base, version)))
        except BaseException:
            _remove_folder(root_fd, version)
            raise
        return prune(root_fd, version)
    finally:
        os.close(root_fd)


def prune(root_fd: int, keep_version: str) -> list[str]:
    """Keep ``keep_version`` and the newest other copy (``KEEP`` in all); remove the rest, each only by ``_remove_folder``. Returns the
    versions removed. Names that are not versions are not looked at."""
    others = sorted((n for n in os.listdir(root_fd) if VERSION_RE.match(n) and n != keep_version), key=cli_versions._version_key,
                    reverse=True)
    return [n for n in others[KEEP - 1:] if _remove_folder(root_fd, n)]
