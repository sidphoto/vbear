"""Before and around a Codex review (design 5.1, 5.2, 5.4): finding the pinned
binary, the fixed argv, prompt and environment, the dedicated CODEX_HOME and
its size, `codex mcp list`, and the binding to the user's risk acceptance.

Everything here either returns a value that was checked or says why not; a
failed or impossible check is a refusal, never a pass. No model is called
(`codex --version` and `codex mcp list --json` start Codex but not a model).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path

from . import codex_constants as cc
from . import review_store

CODEX_HOME_NAME = "codex-home"
RUN_HOMES = "codex-run-homes"
HOME_LIMIT = 512 << 20            # the monitoring threshold for CODEX_HOME (5.1): not a hard cap
WORK_LIMIT = 2 << 30              # review scratch + run home together (5.4): not a hard cap
SCAN_MAX_ENTRIES = 100_000
WORKDIR_RE = review_store.WORKDIR_RE
VERSION_OUT = re.compile(r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)\n?")     # the whole output, nothing else
ENV_KEYS = ("PATH", "USER", "LOGNAME", "LANG", "CODEX_HOME", "HOME")


class CodexRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---- the binary -----------------------------------------------------------------------------------

def codex_binary(version: str, home: str | None = None) -> str:
    """The pinned install of this version: ~/.codex/packages/standalone/
    releases/<version>-<arch>-apple-darwin/bin/codex, as VBear pins its
    terminal baseline. It must be an executable regular file whose path has
    no symlink; never a copy found on PATH."""
    if not (isinstance(version, str) and review_store.VERSION_RE.match(version)):
        raise CodexRefused("bad_request", "Codex 版本格式不符")
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    root = Path(home) if home else Path.home()
    path = root / ".codex/packages/standalone/releases" / f"{version}-{arch}-apple-darwin" / "bin/codex"
    try:
        st = os.stat(path)
    except OSError as exc:
        raise CodexRefused("no_binary", f"找不到固定版本的 Codex（{exc.strerror}）") from exc
    if not stat.S_ISREG(st.st_mode) or not os.access(path, os.X_OK) or os.path.realpath(path) != str(path):
        raise CodexRefused("no_binary", "固定版本的 Codex 不是路徑上沒有符號連結的可執行檔")
    return str(path)


def read_version_detail(binary: str, run) -> tuple[str | None, str]:
    """`codex --version`, parsed: (version, "") or (None, why it could not be
    read). ``run`` is cli_versions._run_probe-shaped:
    run(binary, "codex", cwd, env, timeout)."""
    from . import cli_versions
    try:
        code, out, err = run(binary, "codex", "/", cli_versions._probe_environment(), 10.0)
    except Exception as exc:
        return None, f"無法執行（{type(exc).__name__}）"
    if err:
        return None, f"執行失敗（{err}）"
    if code != 0:
        return None, f"結束碼 {code}"
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        return None, "輸出不是 UTF-8"
    m = VERSION_OUT.fullmatch(text)
    return (m.group(1), "") if m else (None, "輸出不是剛好一行 codex-cli X.Y.Z")


def read_version(binary: str, run) -> str | None:
    """The version, or None when it cannot be read (read_version_detail says why)."""
    return read_version_detail(binary, run)[0]


# ---- environment, prompt, argv --------------------------------------------------------------------

def build_env(codex_home: str, run_home: str) -> dict:
    """Exactly PATH, USER, LOGNAME, LANG, CODEX_HOME and HOME (design 5.2).
    HOME is the job's own empty directory, which drops ~/.agents/skills, the
    user's git config and their login shell; nothing that could name another
    API endpoint (OPENAI_BASE_URL and the like) is passed on."""
    from .daemon import build_env as daemon_env
    src = daemon_env()
    env = {}
    for k in ("PATH", "USER", "LOGNAME", "LANG"):
        if not (isinstance(src.get(k), str) and src[k]):
            raise CodexRefused("bad_env", f"環境變數 {k} 缺少或是空值，不啟動審查")
        env[k] = src[k]
    for k, v in (("CODEX_HOME", codex_home), ("HOME", run_home)):
        if not (isinstance(v, (str, os.PathLike)) and str(v)):
            raise CodexRefused("bad_env", f"環境變數 {k} 缺少或是空值，不啟動審查")
        env[k] = str(v)
    if set(env) != set(ENV_KEYS):
        raise CodexRefused("bad_env", "環境變數不是固定的六個")
    return env


def prompt_for(c: cc.CodexConstants, *, workdir: str, commit: str, base: str) -> str:
    """The fixed prompt with its three values. The work directory goes in
    shell-quoted and must be plain printable text (a newline in it could
    add lines to the prompt); the commits are hex."""
    for sha in (commit, base):
        if not (isinstance(sha, str) and review_store.COMMIT_RE.match(sha)):
            raise CodexRefused("bad_request", "commit 格式不符")
    if not (isinstance(workdir, str) and WORKDIR_RE.match(workdir)):
        raise CodexRefused("bad_request", "任務工作目錄含有不能放進審查說明的字元")
    return c.prompt_template.format(workdir=shlex.quote(workdir), commit=commit, base=base)


def common_flags(c: cc.CodexConstants) -> list[str]:
    """The -c settings and --disable features, for `codex mcp list` (the
    exec argv places -s between the two -c groups)."""
    out: list[str] = []
    for item in (*c.config_head, *c.config_tail):
        out += ["-c", item]
    for feature in c.disable:
        out += ["--disable", feature]
    return out


def review_argv(c: cc.CodexConstants, binary: str, *, model: str, scratch: str, prompt: str) -> list[str]:
    """The fixed argv of design 5.2."""
    if model not in c.models or not review_store.MODEL_RE.match(model):
        raise CodexRefused("bad_request", "審查模型不在已驗證的清單內")
    argv = [binary, "exec", "--json", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "-m", model]
    for item in c.config_head:
        argv += ["-c", item]
    argv += ["-s", c.sandbox_type]
    for item in c.config_tail:
        argv += ["-c", item]
    for feature in c.disable:
        argv += ["--disable", feature]
    return argv + ["-C", scratch, prompt]


def mcp_list_argv(c: cc.CodexConstants, binary: str) -> list[str]:
    """`codex mcp list --json` with the same settings (design 5.2)."""
    return [binary, *common_flags(c), "mcp", "list", "--json"]


def run_argv(argv: list[str], env: dict, timeout: float):
    """(exit code, stdout, error) of a short Codex command (`codex mcp list
    --json`): its own session, no stdin, output capped, the whole group ended
    afterwards. The working directory is "/" (nothing there is read or
    written). Never raises."""
    from . import cli_versions
    try:
        return cli_versions.run_capture(argv, "/", env, timeout, 64 << 10)
    except Exception as exc:
        return None, b"", type(exc).__name__


def mcp_list_is_empty(c: cc.CodexConstants, binary: str, env: dict, run_argv) -> bool:
    """True only when it exits 0 and prints exactly the empty JSON array.
    ``run_argv(argv, env, timeout) -> (code, stdout, error)``."""
    try:
        code, out, err = run_argv(mcp_list_argv(c, binary), env, 20.0)
    except Exception:
        return False
    if code != 0 or err:
        return False
    try:
        return json.loads(out.decode("utf-8")) == [] and out.strip() == b"[]"
    except Exception:
        return False


# ---- CODEX_HOME and the sizes that are watched ---------------------------------------------------

def codex_home_path(base) -> Path:
    """<state>/codex-home, as the state directory was given (not resolved:
    check_codex_home looks for a symlink on the way instead of hiding it)."""
    return Path(os.fspath(base)) / CODEX_HOME_NAME


def check_codex_home(base) -> Path:
    """The dedicated CODEX_HOME: ours, 0700, a plain directory, opened from
    "/" one component at a time without following any symlink (design 5.1):
    a symlink anywhere on its path is refused. CodexRefused otherwise."""
    path = codex_home_path(base)
    try:
        fd = review_store.open_dir_chain(path)
    except (OSError, ValueError) as exc:
        raise CodexRefused("unsafe_path", "專用的 CODEX_HOME 不存在，或路徑上有符號連結、不是資料夾"
                           f"（{type(exc).__name__}）") from exc
    try:
        st = os.fstat(fd)
    finally:
        os.close(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise CodexRefused("unsafe_path", "專用的 CODEX_HOME 必須是本人的 0700 一般資料夾")
    return path


def tree_size(*paths) -> int | None:
    """Bytes in these directory trees, walked by descriptor, nothing followed.
    None for anything not exactly countable (an error, a vanished entry, a
    symlink, a special file, more than 100 000 entries): the caller treats
    it as over the limit and never as a partial count (design 5.1, 5.4)."""
    total, seen = 0, 0
    stack: list[int] = []
    try:
        for p in paths:
            stack.append(os.open(str(p), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC))
        while stack:
            fd = stack.pop()
            try:
                with os.scandir(fd) as it:
                    for entry in it:
                        seen += 1
                        if seen > SCAN_MAX_ENTRIES:
                            return None
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode):
                            stack.append(os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                                 | os.O_CLOEXEC, dir_fd=fd))
                        elif stat.S_ISREG(st.st_mode):
                            total += st.st_size
                        else:
                            return None
            finally:
                os.close(fd)
        return total
    except OSError:
        return None
    finally:
        for fd in stack:
            try:
                os.close(fd)
            except OSError:
                pass


def over_limit(size: int | None, limit: int) -> bool:
    return size is None or size > limit


# ---- the risk acceptance (design 10, planner Q4) -------------------------------------------------

@dataclass
class Binding:
    ok: bool
    reason: str = ""


def check_binding(acceptance: dict, *, version: str, model: str, login_fingerprint: str | None,
                  key_id: str, current_key_id: str) -> Binding:
    """The review runs only with what the user accepted: the Codex version
    and model, the dedicated CODEX_HOME's login (its HMAC fingerprint), and
    the current login key. Anything different, or a fingerprint that cannot
    be had, is a refusal."""
    if acceptance.get("codex_version") != version:
        return Binding(False, "Codex 版本與風險接受時不同，請重新接受")
    if acceptance.get("model") != model:
        return Binding(False, "審查模型與風險接受時不同，請重新接受")
    if key_id != current_key_id or acceptance.get("login_key_id") != current_key_id:
        return Binding(False, "登入指紋的金鑰與接受時不同，請重新接受")
    if not isinstance(login_fingerprint, str) or acceptance.get("login_fingerprint") != login_fingerprint:
        return Binding(False, "專用 CODEX_HOME 的登入與風險接受時不同或無法取得，請重新接受")
    return Binding(True)
