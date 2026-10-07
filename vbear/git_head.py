"""Which commit a working directory is on, read from the repository's files.

Task cards bind a test result or an approval to the exact commit it was given
for (OpenRig's "exact candidate"). This module answers "what is HEAD now?".

VBear never runs ``git`` for this. Repository config (clean filters,
fsmonitor and the like) can make git execute arbitrary programs, and a
managed Agent may write ``.git`` (the commit opt-in), so a git command run by
the console would run Agent-controlled code outside every sandbox. HEAD and
refs are read here as plain, bounded files instead; nothing is executed.

Limits, stated where the result is shown:
  * Uncommitted changes are invisible. A result bound to a commit stays
    current while the working tree changes without a new commit.
  * The reftable ref format is not read; such repositories report unknown.
  * Anyone who can write ``.git`` can point HEAD anywhere. The binding
    notices change; it does not authenticate history.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

MAX_SMALL_FILE = 4096          # HEAD, a loose ref, a .git file, commondir
MAX_PACKED_REFS = 8 << 20
MAX_PARENTS = 64
MAX_SYMREF_DEPTH = 5
SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
# git check-ref-format, conservatively: no component starts with "." and none
# holds a control character, space, ~ ^ : ? * [ or backslash ("/" separates).
_REF_PART = r"(?!\.)[^\x00-\x20~^:?*\[\\\x7f/]+"
REF_RE = re.compile(rf"^refs/(?:{_REF_PART}/)*{_REF_PART}$")


class _Unreadable(Exception):
    pass


def _read_small(path: Path, limit: int = MAX_SMALL_FILE) -> str | None:
    """A regular, non-symlinked file's text, or None if it does not exist.

    O_NONBLOCK keeps a FIFO planted in .git from blocking the open (and the
    request) forever; it is then refused as not a regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _Unreadable(f"無法讀取 {path.name}（{exc.strerror or exc}）") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise _Unreadable(f"{path.name} 不是一般檔案")
        if st.st_size > limit:
            raise _Unreadable(f"{path.name} 超過 {limit} bytes")
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _Unreadable(f"{path.name} 不是 UTF-8 文字") from exc


def _is_dir(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode)


def _find_repo(start: Path) -> tuple[Path, Path] | None:
    """(worktree root, its .git entry). The home directory is never a project
    (dotfile repos are common), the same rule the project index uses."""
    home = Path(os.path.realpath(Path.home()))
    current = start
    for _ in range(MAX_PARENTS):
        if current == home or current == current.parent:
            return None
        entry = current / ".git"
        try:
            os.lstat(entry)
            return current, entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise _Unreadable(f"無法檢查 .git（{exc.strerror or exc}）") from exc
        current = current.parent
    return None


def _git_dirs(entry: Path) -> tuple[Path, Path]:
    """(this worktree's git dir, the common dir holding shared refs)."""
    st = os.lstat(entry)
    if stat.S_ISLNK(st.st_mode):
        raise _Unreadable(".git 是符號連結，不讀取")
    if stat.S_ISDIR(st.st_mode):
        gitdir = entry
    elif stat.S_ISREG(st.st_mode):
        text = (_read_small(entry) or "").strip()
        if not text.startswith("gitdir:"):
            raise _Unreadable(".git 檔案格式不符")
        target = Path(text[len("gitdir:"):].strip())
        gitdir = target if target.is_absolute() else entry.parent / target
        if not _is_dir(gitdir):
            raise _Unreadable(".git 指向的資料夾不存在或是符號連結")
    else:
        raise _Unreadable(".git 不是資料夾或檔案")
    common = gitdir
    pointer = _read_small(gitdir / "commondir")
    if pointer is not None:
        target = Path(pointer.strip())
        common = target if target.is_absolute() else gitdir / target
        if not _is_dir(common):
            raise _Unreadable("commondir 指向的資料夾不存在或是符號連結")
    return gitdir, common


def _packed(common: Path, ref: str) -> str | None:
    text = _read_small(common / "packed-refs", MAX_PACKED_REFS)
    if text is None:
        return None
    for line in text.splitlines():
        if not line or line[0] in "#^":
            continue
        sha, _, name = line.partition(" ")
        if name == ref:
            if not SHA_RE.match(sha):
                raise _Unreadable("packed-refs 內容格式不符")
            return sha
    return None


def _resolve(gitdir: Path, common: Path, ref: str) -> str | None:
    for _ in range(MAX_SYMREF_DEPTH):
        if not REF_RE.match(ref) or ".." in ref or "@{" in ref or ref.endswith((".lock", ".")):
            raise _Unreadable("ref 名稱格式不符")
        # Branches and tags live in the common dir; a few refs are per worktree.
        base = gitdir if ref.startswith(("refs/bisect/", "refs/worktree/", "refs/rewritten/")) else common
        text = _read_small(base / ref)
        if text is None:
            return _packed(common, ref)
        text = text.strip()
        if text.startswith("ref:"):
            ref = text[len("ref:"):].strip()
            continue
        if not SHA_RE.match(text):
            raise _Unreadable("ref 內容不是 commit 雜湊")
        return text
    raise _Unreadable("符號 ref 層數過多")


def read_head(workdir: str) -> dict:
    """``{"commit", "ref", "repo", "error"}``. ``commit`` is None whenever it
    cannot be read, with ``error`` saying why; it is never guessed."""
    out = {"commit": None, "ref": None, "repo": None, "error": None}
    if not isinstance(workdir, str) or not workdir or "\0" in workdir or not os.path.isabs(workdir):
        out["error"] = "工作目錄必須是絕對路徑"
        return out
    start = Path(os.path.realpath(workdir))
    if not start.is_dir():
        out["error"] = "工作目錄不存在"
        return out
    try:
        found = _find_repo(start)
        if found is None:
            out["error"] = "工作目錄不在 git 儲存庫內"
            return out
        root, entry = found
        out["repo"] = str(root)
        gitdir, common = _git_dirs(entry)
        if _is_dir(common / "reftable"):
            out["error"] = "此儲存庫使用 reftable 格式，無法讀取 HEAD"
            return out
        head = _read_small(gitdir / "HEAD")
        if head is None:
            out["error"] = "找不到 HEAD"
            return out
        head = head.strip()
        if head.startswith("ref:"):
            ref = head[len("ref:"):].strip()
            out["ref"] = ref if REF_RE.match(ref) else None
            commit = _resolve(gitdir, common, ref)
            if commit is None:
                out["error"] = "分支還沒有任何 commit"
                return out
            out["commit"] = commit
        elif SHA_RE.match(head):
            out["commit"] = head  # detached HEAD
        else:
            out["error"] = "HEAD 內容格式不符"
    except _Unreadable as exc:
        out["error"] = str(exc)
    except OSError as exc:
        out["error"] = f"無法讀取儲存庫（{exc.strerror or exc}）"
    return out
