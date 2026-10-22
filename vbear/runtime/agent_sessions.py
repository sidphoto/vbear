"""Managed Claude and Codex launch state: per-session settings, scratch and
manifest. Both engines share the same daemon ownership, process tracking,
single-use launch IDs and fail-closed cleanup lifecycle.

Layout (decision D1):
  ``<state>/sessions/<launch-id>/``   0700, holds ``settings.json`` and
                                      ``manifest.json`` (0600)
  ``/private/tmp/sc-<random>/``       0700 launch-owned scratch; Claude receives
                                      it as ``CLAUDE_CODE_TMPDIR`` and Codex
                                      receives it only as an explicit writable root

The scratch is not under the state directory on purpose: Claude Code 2.1.286
falls back to the shared ``/tmp/claude-<uid>`` when its per-UID temp path
exceeds 44 UTF-8 bytes, and a path below ``~/.vbear`` is longer than
that. The exact scratch path, inode, uid and mode are recorded in the manifest
and re-checked before every use and before deletion.

What this module does and does not provide:
  * Engine settings and argv are built here from a pinned manifest; caller raw
    argv, environment and credentials never enter this module.
  * The CLI version and settings evidence are engine-specific. A configuration
    change must be re-tested before its evidence label can claim enforcement.
  * Read isolation between sessions is NOT provided (decision D2).
  * 0700 directories are ownership and lifecycle controls. They are not a
    security boundary between processes of the same user.
  * No credential is read, copied or stored here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
from pathlib import Path

from .. import folders
from . import proctrack
from . import stream_protocol

SESSIONS_DIR = "sessions"
MANIFEST = "manifest.json"
SETTINGS = "settings.json"
# \Z, not $: $ also matches before a trailing newline, and these name paths.
LAUNCH_RE = re.compile(r"^l-[0-9a-f]{16}\Z")
SCRATCH_PARENT = "/private/tmp"
SCRATCH_PREFIX = "sc-"
# Claude Code 2.1.286: per-UID temp path limit before the shared-tmp fallback.
CLAUDE_TMP_PATH_LIMIT = 44
MANIFEST_VERSION = 1
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,63}\Z")
# States recovery may act on; "manual_review" is left for a human. A stream
# launch whose processes are proven gone becomes "ended": its directory (the
# journal) is kept until the user deletes the flow (design 2.5, 9).
_ACTIVE_STATES = ("prepared", "launching", "running")
ENGINES = ("claude", "codex", "claude-stream")
FLOW_ID_RE = re.compile(r"^flow-[0-9a-f]{12}\Z")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")       # tasks.VALID_ID_RE; never "." or ".."
JOURNAL = "journal.jsonl"
# A prepared launch younger than this may still be about to start (the daemon
# can be autostarted by the very RPC that launches it), so recovery skips it.
PREPARED_TTL = 600.0


class LaunchRefused(Exception):
    """A managed launch precondition failed. Callers must not downgrade to an
    unmanaged or looser launch."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _owned_dir(path: Path, uid: int) -> os.stat_result:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise LaunchRefused("unsafe_path", f"不是一般資料夾：{path}")
    if st.st_uid != uid or st.st_mode & 0o077:
        raise LaunchRefused("unsafe_path", f"資料夾擁有者或權限不符（需本人、0700）：{path}")
    if os.path.realpath(path) != str(path):
        raise LaunchRefused("unsafe_path", f"路徑含 symlink：{path}")
    return st


def _owned_file(path: Path, uid: int) -> os.stat_result:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_mode & 0o077:
        raise LaunchRefused("unsafe_path", f"不是本人擁有的 0600 一般檔案：{path}")
    return st


def _write_private(path: Path, text: str, *, replace: bool = False) -> None:
    """0600 write. New files are created exclusively; ``replace`` swaps in a
    sibling temp file atomically."""
    target = path.with_name(path.name + ".tmp") if replace else path
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_TRUNC if replace else os.O_EXCL)
    fd = os.open(target, flags, 0o600)
    try:
        data = memoryview(text.encode("utf-8"))
        while data:                               # every byte (review round 7)
            n = os.write(fd, data)
            if n <= 0:
                raise OSError(5, "寫入沒有進展")
            data = data[n:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(target)                         # the temp file, or the new file just created
        raise
    os.close(fd)
    if replace:
        os.replace(target, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sessions_root(base: Path) -> Path:
    return Path(os.path.realpath(base)) / SESSIONS_DIR


def launch_dir(base: Path, launch_id: str) -> Path:
    if not isinstance(launch_id, str) or not LAUNCH_RE.match(launch_id):
        raise LaunchRefused("bad_request", "無效的 launch id")
    return sessions_root(base) / launch_id


def per_uid_tmp(scratch: str, uid: int) -> str:
    return f"{scratch}/claude-{uid}"


def binary_identity(path: str) -> list[int]:
    info = os.stat(path, follow_symlinks=True)
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise OSError("binary is not a regular executable file")
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def claude_settings(workdir: str, scratch: str, uid: int) -> dict:
    """The settings shape verified in T-01 (short4 / round 11 / S2 W0)."""
    return {"sandbox": {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "autoAllowBashIfSandboxed": True,
        "filesystem": {
            "allowWrite": [workdir, scratch],
            "denyWrite": [f"/private/tmp/claude-{uid}", f"/tmp/claude-{uid}"],
        },
        "network": {"allowedDomains": [], "strictAllowlist": True},
    }}


# The tools a Claude launch offers (decision D4: Edit and Write are not covered by the Bash sandbox). The argv of
# both launch shapes is built from these two tuples (read when the argv is built), and the role card's tool list
# (loadout.py) reads the same tuples, so what the page says is what the argv says. Joined with a comma they are
# the exact argv values: "Bash" and "Edit,Write".
CLAUDE_TOOLS_ALLOWED = ("Bash",)
CLAUDE_TOOLS_BLOCKED = ("Edit", "Write")


def _tools_arg() -> str:
    return ",".join(CLAUDE_TOOLS_ALLOWED)


def _disallowed_tools_arg() -> str:
    return ",".join(CLAUDE_TOOLS_BLOCKED)


def stream_settings(workdir: str, scratch: str, uid: int, cli_version: str) -> dict:
    """Design 2.1: the managed sandbox settings plus an ``env`` block that
    pins the API endpoint and provider. ``--settings`` ranks above user and
    project settings, so neither can move the endpoint."""
    consts = stream_protocol.constants_for(cli_version)
    if consts is None:
        raise LaunchRefused("unsupported_version", f"Claude Code {cli_version} 沒有串流模式的常數")
    return {**claude_settings(workdir, scratch, uid), "env": dict(consts.pinned_env)}


def stream_argv(manifest: dict) -> list[str]:
    """Design 2.1, exactly. Everything comes from the validated manifest; the
    session id and remaining budget are set by the daemon before spawning."""
    from .. import executor_report  # here: executor_report imports this package
    sid, budget, model = manifest.get("claude_session_id"), manifest.get("budget_usd"), manifest.get("model_id")
    if not (isinstance(sid, str) and stream_protocol.UUID_RE.match(sid)):
        raise LaunchRefused("manifest_invalid", "claude_session_id 格式不符")
    if not _budget_ok(budget):
        raise LaunchRefused("manifest_invalid", "額度必須是有限正數")
    if not (isinstance(model, str) and STREAM_MODEL_RE.match(model)):
        raise LaunchRefused("manifest_invalid", "串流執行者必須以完整的 Claude 模型 id 啟動")
    schema = json.dumps(executor_report.JSON_SCHEMA, separators=(",", ":"), sort_keys=True)
    return [manifest["cli_binary"], "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose", "--replay-user-messages", "--permission-prompts", "none",
            "--json-schema", schema, "--max-budget-usd", f"{budget:.2f}",
            "--safe-mode", "--settings", manifest["settings_path"], "--permission-mode", "acceptEdits",
            "--tools", _tools_arg(), "--disallowedTools", _disallowed_tools_arg(), "--strict-mcp-config",
            "--session-id", sid, "--model", model]


def _budget_ok(value) -> bool:
    import math
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and 0 < value <= 100 and round(value, 2) == value)


# A full Claude model id (acceptance.CLAUDE_MODEL_RE), never an alias.
STREAM_MODEL_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.-]{0,62}\Z")


def claude_argv(manifest: dict) -> list[str]:
    """Trusted argv; nothing here comes from an RPC caller. Edit/Write tools are
    not offered (decision D4): they are not covered by the Bash sandbox."""
    argv = [manifest["cli_binary"], "--safe-mode", "--settings", manifest["settings_path"],
            "--permission-mode", "acceptEdits", "--tools", _tools_arg(),
            "--disallowedTools", _disallowed_tools_arg(), "--strict-mcp-config"]
    model_id = manifest.get("model_id")
    if model_id:
        if not isinstance(model_id, str) or not MODEL_ID_RE.match(model_id):
            raise LaunchRefused("manifest_invalid", "model id 格式不符")
        argv += ["--model", model_id]
    return argv


def codex_settings(workdir: str, scratch: str, *, sandbox_mode: str,
                   commit: bool) -> dict:
    """Codex 0.159.2 settings passed as trusted ``-c`` arguments.

    ``read-only`` has no writable roots. ``workspace-write`` explicitly
    excludes both shared temporary roots and grants only this work directory,
    its owned scratch directory, and (when opted in) this repository's .git.
    Commit remains an opt-in disclosure, not a command-pattern restriction.
    """
    if sandbox_mode == "read-only":
        return {"sandbox_mode": sandbox_mode}
    if sandbox_mode != "workspace-write":
        raise LaunchRefused("unsupported_sandbox", "Codex sandbox 模式不支援")
    if commit is not True:
        raise LaunchRefused("commit_not_enforceable", "workspace-write 無法排除 .git；需要明確 commit=true")
    roots = [workdir, scratch]
    if commit:
        roots.append(str(Path(workdir) / ".git"))
    return {
        "sandbox_mode": sandbox_mode,
        "sandbox_workspace_write": {
            "exclude_slash_tmp": True,
            "exclude_tmpdir_env_var": True,
            "network_access": False,
            "writable_roots": roots,
        },
    }


def codex_argv(manifest: dict) -> list[str]:
    """Build the Codex command from a validated, private launch manifest."""
    if manifest.get("engine") != "codex":
        raise LaunchRefused("manifest_invalid", "Codex argv 需要 Codex manifest")
    settings = manifest.get("_validated_settings")
    if not isinstance(settings, dict):
        raise LaunchRefused("manifest_invalid", "Codex settings 尚未經 launch 驗證")
    mode = settings.get("sandbox_mode")
    if mode not in ("read-only", "workspace-write"):
        raise LaunchRefused("manifest_invalid", "Codex sandbox 模式不符")
    argv = [manifest["cli_binary"], "--ignore-user-config", "--ignore-rules",
            "--ephemeral", "--sandbox", mode, "--cd", manifest["canonical_workspace"],
            "--skip-git-repo-check"]
    if mode == "workspace-write":
        sandbox = settings.get("sandbox_workspace_write")
        if not isinstance(sandbox, dict) or sandbox != codex_settings(
                manifest["canonical_workspace"], manifest["scratch"]["path"],
                sandbox_mode=mode, commit=True
        ).get("sandbox_workspace_write"):
            raise LaunchRefused("manifest_invalid", "Codex workspace-write 設定不符")
        for key in ("exclude_slash_tmp", "exclude_tmpdir_env_var", "network_access"):
            argv += ["-c", f"sandbox_workspace_write.{key}={str(sandbox[key]).lower()}"]
        roots = json.dumps(sandbox["writable_roots"], ensure_ascii=False, separators=(",", ":"))
        argv += ["-c", f"sandbox_workspace_write.writable_roots={roots}"]
    model_id = manifest.get("model_id")
    if model_id:
        if not isinstance(model_id, str) or not MODEL_ID_RE.match(model_id):
            raise LaunchRefused("manifest_invalid", "model id 格式不符")
        argv += ["--model", model_id]
    return argv


def managed_argv(manifest: dict) -> list[str]:
    engine = manifest.get("engine")
    if engine == "claude":
        return claude_argv(manifest)
    if engine == "codex":
        return codex_argv(manifest)
    if engine == "claude-stream":
        return stream_argv(manifest)
    raise LaunchRefused("manifest_invalid", "不支援的 managed Agent 引擎")


def _check_workdir(workdir: str, allowed_root: str, base: Path) -> str:
    if not isinstance(workdir, str) or not workdir or "\0" in workdir or not os.path.isabs(workdir):
        raise LaunchRefused("invalid_workdir", "工作目錄必須是絕對路徑")
    canonical = os.path.realpath(workdir)
    root = os.path.realpath(allowed_root)
    # The work directory becomes writable, so it follows the folder picker's rules (folders.resolve_allowed):
    # the home directory, credentials, tool state and the state directory may not be, or contain, a project.
    # Case is folded, symlinks are already resolved, and this comes before the existence check so the
    # answer is the same whether or not the place exists.
    homes = [Path(os.path.realpath(Path.home()))]
    if folders.fold(homes[0]) != folders.fold(Path(root)):
        homes.append(Path(root))
    if folders.is_refused(Path(canonical), homes) or folders.covers_refused(Path(canonical), homes):
        raise LaunchRefused("invalid_workdir", folders.REFUSED)
    if not os.path.isdir(canonical):
        raise LaunchRefused("invalid_workdir", "工作目錄不存在")
    if canonical == root or os.path.commonpath([canonical, root]) != root:
        raise LaunchRefused("invalid_workdir", "工作目錄必須在允許的根目錄之內，且不能是根目錄本身")
    protected = [Path(os.path.realpath(base)), Path(os.path.realpath(SCRATCH_PARENT)),
                 Path(os.path.realpath("/tmp"))]
    for p in protected:
        # It may neither contain a protected location nor be one.
        if folders.inside(p, Path(canonical)):
            raise LaunchRefused("invalid_workdir", f"工作目錄不可包含受保護的位置：{p}")
    if folders.inside(Path(canonical), protected[0]):
        raise LaunchRefused("invalid_workdir", f"工作目錄不可位於受保護的位置之內：{protected[0]}")
    return canonical


def prepare_claude_launch(base: Path, workdir: str, *, cli_binary: str, cli_version: str,
                          cli_identity: list[int], allowed_root: str | None = None,
                          model_id: str | None = None, cli_verified: bool = True) -> dict:
    """Create the launch directory, scratch, settings and manifest. No process
    is started. On any failure everything created here is removed again."""
    return _prepare_claude(base, workdir, cli_binary=cli_binary, cli_version=cli_version,
                           cli_identity=cli_identity, allowed_root=allowed_root, model_id=model_id,
                           cli_verified=cli_verified, engine="claude", extra=None)


def prepare_stream_launch(base: Path, workdir: str, *, cli_binary: str, cli_version: str,
                          cli_identity: list[int], model_id: str, pipeline_id: str, task_id: str,
                          allowed_root: str | None = None) -> dict:
    """A stream executor launch (design 2.1): the managed launch plus the
    flow it belongs to. The daemon adds the Claude session id and the
    remaining budget when it starts the process."""
    if not (isinstance(pipeline_id, str) and FLOW_ID_RE.match(pipeline_id)):
        raise LaunchRefused("bad_request", "流程 id 格式不符")
    if not (isinstance(task_id, str) and TASK_ID_RE.match(task_id)) or task_id in (".", ".."):
        raise LaunchRefused("bad_request", "任務 id 格式不符")
    if not (isinstance(model_id, str) and STREAM_MODEL_RE.match(model_id)):
        raise LaunchRefused("invalid_model", "串流執行者必須以完整的 Claude 模型 id 啟動")
    if stream_protocol.constants_for(cli_version) is None:
        from . import cli_versions         # here: cli_versions imports daemon, which imports this module
        raise LaunchRefused("unsupported_version", cli_versions.stream_unverified_text(cli_version))
    return _prepare_claude(base, workdir, cli_binary=cli_binary, cli_version=cli_version,
                           cli_identity=cli_identity, allowed_root=allowed_root, model_id=model_id,
                           cli_verified=True, engine="claude-stream",
                           extra={"pipeline_id": pipeline_id, "task_id": task_id,
                                  "claude_session_id": None, "budget_usd": None})


def _prepare_claude(base: Path, workdir: str, *, cli_binary: str, cli_version: str, cli_identity: list[int],
                    allowed_root: str | None, model_id: str | None, cli_verified: bool, engine: str,
                    extra: dict | None) -> dict:
    uid = os.getuid()
    base = Path(os.path.realpath(base))
    canonical = _check_workdir(workdir, allowed_root or str(Path.home()), base)
    if (not isinstance(cli_binary, str) or not os.path.isabs(cli_binary)
            or os.path.realpath(cli_binary) != cli_binary):
        raise LaunchRefused("invalid_binary", "CLI 必須是已解析的絕對路徑")
    if model_id is not None and (not isinstance(model_id, str) or not MODEL_ID_RE.match(model_id)):
        raise LaunchRefused("invalid_model", "model id 格式不符")
    root = base / SESSIONS_DIR
    old_umask = os.umask(0o077)
    ldir = scratch = None
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
        _owned_dir(root, uid)
        launch_id = "l-" + secrets.token_hex(8)
        os.mkdir(root / launch_id, 0o700)  # fails if it already exists
        ldir = root / launch_id  # ours from here on; only now may the error path remove it
        lst = _owned_dir(ldir, uid)
        scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=SCRATCH_PARENT))
        if os.path.realpath(scratch) != str(scratch):
            raise LaunchRefused("unsafe_path", "暫存區路徑含 symlink")
        sst = _owned_dir(scratch, uid)
        tmp_bytes = len(per_uid_tmp(str(scratch), uid).encode("utf-8"))
        if tmp_bytes > CLAUDE_TMP_PATH_LIMIT:
            raise LaunchRefused("scratch_path_too_long",
                                f"暫存路徑 {tmp_bytes} bytes 超過 {CLAUDE_TMP_PATH_LIMIT}，CLI 會退回共用暫存區")
        settings_path = ldir / SETTINGS
        settings = (claude_settings(canonical, str(scratch), uid) if engine == "claude"
                    else stream_settings(canonical, str(scratch), uid, cli_version))
        _write_private(settings_path, json.dumps(settings, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "launch_id": launch_id,
            "native_session_id": None,
            "engine": engine,
            "cli_binary": cli_binary,
            "cli_version": cli_version,
            "cli_verified": cli_verified is True,
            "cli_identity": list(cli_identity),
            "model_id": model_id,
            "settings_path": str(settings_path),
            "settings_sha256": _sha256(settings_path),
            "canonical_workspace": canonical,
            "allowed_root": os.path.realpath(allowed_root or str(Path.home())),
            "launch_dir": {"path": str(ldir), "inode": lst.st_ino, "uid": lst.st_uid},
            "scratch": {"path": str(scratch), "inode": sst.st_ino, "uid": sst.st_uid,
                        "per_uid_tmp_bytes": tmp_bytes},
            "state": "prepared",
            "created": time.time(),
            "leader": None,
            "observed": [],
            "boundary": {
                "write": ("enforced for Bash-tool commands (Claude sandbox; verified for this version/settings only)"
                          if cli_verified is True else
                          "configured for Bash-tool commands (Claude sandbox); not verified for this version"),
                "read": "not isolated",
                "edit_write_tools": "disabled",
                "network": ("strict empty allowlist" if cli_verified is True
                            else "strict empty allowlist configured; not verified for this version"),
            },
            **(extra or {}),
        }
        _write_private(ldir / MANIFEST, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return manifest
    except BaseException:
        for p in (scratch, ldir):
            if p is not None:
                shutil.rmtree(p, ignore_errors=True)
        raise
    finally:
        os.umask(old_umask)


def prepare_codex_launch(base: Path, workdir: str, *, cli_binary: str, cli_version: str,
                         cli_identity: list[int], allowed_root: str | None = None,
                         model_id: str | None = None, commit: bool = True,
                         read_only: bool = False) -> dict:
    """Prepare a Codex launch without starting a process or changing user state."""
    uid = os.getuid()
    base = Path(os.path.realpath(base))
    canonical = _check_workdir(workdir, allowed_root or str(Path.home()), base)
    if not isinstance(cli_binary, str) or not os.path.isabs(cli_binary) or os.path.realpath(cli_binary) != cli_binary:
        raise LaunchRefused("invalid_binary", "CLI 必須是已解析的絕對路徑")
    if model_id is not None and (not isinstance(model_id, str) or not MODEL_ID_RE.match(model_id)):
        raise LaunchRefused("invalid_model", "model id 格式不符")
    if not isinstance(commit, bool) or not isinstance(read_only, bool):
        raise LaunchRefused("bad_request", "Codex launch flags 必須是布林值")
    root = base / SESSIONS_DIR
    old_umask = os.umask(0o077)
    ldir = scratch = None
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
        _owned_dir(root, uid)
        launch_id = "l-" + secrets.token_hex(8)
        os.mkdir(root / launch_id, 0o700)
        ldir = root / launch_id
        lst = _owned_dir(ldir, uid)
        scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=SCRATCH_PARENT))
        if os.path.realpath(scratch) != str(scratch):
            raise LaunchRefused("unsafe_path", "暫存區路徑含 symlink")
        sst = _owned_dir(scratch, uid)
        settings = codex_settings(canonical, str(scratch),
                                  sandbox_mode="read-only" if read_only else "workspace-write",
                                  commit=commit)
        settings_path = ldir / SETTINGS
        _write_private(settings_path, json.dumps(settings, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "launch_id": launch_id,
            "native_session_id": None,
            "engine": "codex",
            "cli_binary": cli_binary,
            "cli_version": cli_version,
            "cli_identity": list(cli_identity),
            "model_id": model_id,
            "settings_path": str(settings_path),
            "settings_sha256": _sha256(settings_path),
            "canonical_workspace": canonical,
            "allowed_root": os.path.realpath(allowed_root or str(Path.home())),
            "launch_dir": {"path": str(ldir), "inode": lst.st_ino, "uid": lst.st_uid},
            "scratch": {"path": str(scratch), "inode": sst.st_ino, "uid": sst.st_uid},
            "state": "prepared",
            "created": time.time(),
            "leader": None,
            "observed": [],
            "boundary": {
                "write": "Codex OS sandbox mode selected per launch; evidence is version/settings specific",
                "read": "not isolated",
                "network": "explicitly disabled in workspace-write; read-only uses its own sandbox policy",
            },
        }
        _write_private(ldir / MANIFEST, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return manifest
    except BaseException:
        for p in (scratch, ldir):
            if p is not None:
                shutil.rmtree(p, ignore_errors=True)
        raise
    finally:
        os.umask(old_umask)


def _read_manifest(ldir: Path, uid: int) -> dict:
    """Design 2.3: read through one O_NOFOLLOW descriptor (owned by us, a
    regular file, <= 64 KiB) and parsed strictly (node and depth limits, no
    duplicate keys, no NaN/Infinity). A claude-stream manifest is then checked
    field by field against its exact schema."""
    from .. import strictjson
    path = ldir / MANIFEST
    _owned_file(path, uid)
    parsed = strictjson.load_owned_object(path, strictjson.MANIFEST)
    if not parsed.ok:
        raise LaunchRefused("manifest_invalid", f"manifest 無法讀取（{parsed.problem}）")
    data = parsed.value
    if data.get("manifest_version") != MANIFEST_VERSION or isinstance(data.get("manifest_version"), bool):
        raise LaunchRefused("manifest_invalid", "manifest 格式不符")
    if data.get("engine") == "claude-stream":
        problem = stream_manifest_problem(data)
        if problem:
            raise LaunchRefused("manifest_invalid", f"串流 manifest 不符（{problem}）")
    return data


_STREAM_REQUIRED = frozenset({
    "manifest_version", "launch_id", "native_session_id", "engine", "cli_binary", "cli_version", "cli_verified",
    "cli_identity", "model_id", "settings_path", "settings_sha256", "canonical_workspace", "allowed_root",
    "launch_dir", "scratch", "state", "created", "leader", "observed", "boundary", "pipeline_id", "task_id",
    "claude_session_id", "budget_usd"})
_STREAM_OPTIONAL = frozenset({"retained_reason", "retained_at", "ended_at"})
_STREAM_STATES = ("prepared", "launching", "running", "manual_review", "ended")
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
_LIBPROC_START = re.compile(r"^([0-9]{1,12})\.[0-9]{6}\Z")
_PS_START = re.compile(r"^[A-Z][a-z]{2} [A-Z][a-z]{2} [ 0-9][0-9] [0-9]{2}:[0-9]{2}:[0-9]{2} ([0-9]{4})\Z")
_EARLIEST = 1577836800.0                                   # 2020-01-01


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _epoch_ok(value) -> bool:
    import math
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and _EARLIEST <= value <= time.time() + 86400)


def _start_ok(value) -> bool:
    """A process start time as proctrack writes it (design 2.4: between
    2020-01-01 and a day from now). Never empty: an identity without a start
    time matches no process, so a live descendant could pass for gone
    (Codex S2a-2 p1 R2 #3)."""
    if not isinstance(value, str):
        return False
    m = _LIBPROC_START.match(value)
    if m:
        return _EARLIEST <= int(m.group(1)) <= time.time() + 86400
    m = _PS_START.match(value)
    return m is not None and 2020 <= int(m.group(1)) <= time.gmtime(time.time() + 86400).tm_year


def _abs_path(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 4096 and "\0" not in value and os.path.isabs(value)


def _leader_ok(v) -> bool:
    return v is None or (isinstance(v, dict) and set(v) == {"pid", "start", "source"}
                         and _int_in(v["pid"], 1, 99999) and _start_ok(v["start"])
                         and v["source"] in ("libproc", "ps"))


def _observed_ok(v) -> bool:
    return (isinstance(v, list) and len(v) <= 4096
            and all(isinstance(x, list) and len(x) == 2 and _int_in(x[0], 1, 99999) and _start_ok(x[1]) for x in v))


def _boundary_ok(v) -> bool:
    return (isinstance(v, dict) and len(v) <= 16
            and all(isinstance(k, str) and isinstance(x, str) and len(x) <= 512 for k, x in v.items()))


def _launch_dir_ok(v) -> bool:
    return (isinstance(v, dict) and set(v) == {"path", "inode", "uid"} and _abs_path(v["path"])
            and _int_in(v["inode"], 0, 2 ** 63) and _int_in(v["uid"], 0, 2 ** 31))


def _scratch_ok(v, keys: frozenset) -> bool:
    return (isinstance(v, dict) and set(v) == keys and _abs_path(v["path"])
            and _int_in(v["inode"], 0, 2 ** 63) and _int_in(v["uid"], 0, 2 ** 31)
            and ("per_uid_tmp_bytes" not in v or _int_in(v["per_uid_tmp_bytes"], 0, CLAUDE_TMP_PATH_LIMIT)))


_SCRATCH_CLAUDE = frozenset({"path", "inode", "uid", "per_uid_tmp_bytes"})
_SCRATCH_CODEX = frozenset({"path", "inode", "uid"})
_MANAGED_COMMON = frozenset({
    "manifest_version", "launch_id", "native_session_id", "engine", "cli_binary", "cli_version", "cli_identity",
    "model_id", "settings_path", "settings_sha256", "canonical_workspace", "allowed_root", "launch_dir", "scratch",
    "state", "created", "leader", "observed", "boundary"})
# What prepare_claude_launch / prepare_codex_launch write, and what
# native._launch_prepared, the daemon and _retain may add later.
_MANAGED_REQUIRED = {"claude": _MANAGED_COMMON | {"cli_verified"}, "codex": _MANAGED_COMMON}
_MANAGED_OPTIONAL = {"claude": frozenset({"retained_reason", "retained_at", "unverified_acknowledged",
                                          "unverified_acknowledged_at"}),
                     "codex": frozenset({"retained_reason", "retained_at"})}
_MANAGED_STATES = ("prepared", "launching", "running", "manual_review")
_CLI_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}\Z")


def managed_manifest_problem(m: dict) -> str | None:
    """None when ``m`` is exactly a claude or codex (terminal) manifest as
    VBear writes one. Used where such a launch is skipped as "not part of a
    flow": only one that passes is skipped (Codex S2a-2 p1 R5 #1)."""
    engine = m.get("engine")
    if engine not in _MANAGED_REQUIRED:
        return "engine 不符"
    keys, required = set(m), _MANAGED_REQUIRED[engine]
    if not required <= keys or keys - required - _MANAGED_OPTIONAL[engine]:
        return "欄位不符"
    checks = [
        ("manifest_version", m["manifest_version"] == MANIFEST_VERSION and not isinstance(m["manifest_version"], bool)),
        ("launch_id", isinstance(m["launch_id"], str) and LAUNCH_RE.match(m["launch_id"]) is not None),
        ("native_session_id", m["native_session_id"] is None or (isinstance(m["native_session_id"], str)
                                                                 and re.match(r"^n-[0-9a-f]{12}\Z",
                                                                              m["native_session_id"]) is not None)),
        ("cli_binary", _abs_path(m["cli_binary"])),
        ("cli_version", isinstance(m["cli_version"], str) and _CLI_VERSION_RE.match(m["cli_version"]) is not None),
        ("cli_verified", engine != "claude" or isinstance(m["cli_verified"], bool)),
        ("cli_identity", isinstance(m["cli_identity"], list) and len(m["cli_identity"]) == 6
                         and all(_int_in(x, 0, 2 ** 63) for x in m["cli_identity"])),
        ("model_id", m["model_id"] is None or (isinstance(m["model_id"], str)
                                               and MODEL_ID_RE.match(m["model_id"]) is not None)),
        ("settings_path", _abs_path(m["settings_path"])),
        ("settings_sha256", isinstance(m["settings_sha256"], str) and _HEX64.match(m["settings_sha256"]) is not None),
        ("canonical_workspace", _abs_path(m["canonical_workspace"])),
        ("allowed_root", _abs_path(m["allowed_root"])),
        ("launch_dir", _launch_dir_ok(m["launch_dir"])),
        ("scratch", _scratch_ok(m["scratch"], _SCRATCH_CLAUDE if engine == "claude" else _SCRATCH_CODEX)),
        ("state", m["state"] in _MANAGED_STATES),
        ("created", _epoch_ok(m["created"])),
        ("leader", _leader_ok(m["leader"])),
        ("observed", _observed_ok(m["observed"])),
        ("boundary", _boundary_ok(m["boundary"])),
        ("retained_reason", "retained_reason" not in m
                            or (isinstance(m["retained_reason"], str) and len(m["retained_reason"]) <= 4096)),
        ("retained_at", "retained_at" not in m or _epoch_ok(m["retained_at"])),
        ("unverified_acknowledged", "unverified_acknowledged" not in m or m["unverified_acknowledged"] is True),
        ("unverified_acknowledged_at", "unverified_acknowledged_at" not in m
                                       or _epoch_ok(m["unverified_acknowledged_at"])),
    ]
    for name, ok in checks:
        if not ok:
            return f"{name} 不合法"
    return None


def _lexists(path) -> bool:
    """Whether anything is at ``path`` (a link counts). Errors other than
    "not found" are raised, never read as absent: Path.exists() follows a
    dangling link to False and, on Python 3.14, returns False on any OSError."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def stream_manifest_problem(m: dict) -> str | None:
    """None when ``m`` is exactly a claude-stream manifest (design 2.1, 2.4:
    identifiers by their formats, process identities within range, no other
    fields)."""
    keys = set(m)
    if not _STREAM_REQUIRED <= keys or keys - _STREAM_REQUIRED - _STREAM_OPTIONAL:
        return "欄位不符"
    checks = [
        ("launch_id", isinstance(m["launch_id"], str) and LAUNCH_RE.match(m["launch_id"]) is not None),
        ("native_session_id", m["native_session_id"] is None or (isinstance(m["native_session_id"], str)
                                                                 and re.match(r"^n-[0-9a-f]{12}\Z",
                                                                              m["native_session_id"]) is not None)),
        ("cli_binary", _abs_path(m["cli_binary"])),
        ("cli_version", stream_protocol.constants_for(m["cli_version"]) is not None),
        ("cli_verified", m["cli_verified"] is True),
        ("cli_identity", isinstance(m["cli_identity"], list) and len(m["cli_identity"]) == 6
                         and all(_int_in(x, 0, 2 ** 63) for x in m["cli_identity"])),
        ("model_id", isinstance(m["model_id"], str) and STREAM_MODEL_RE.match(m["model_id"]) is not None),
        ("settings_path", _abs_path(m["settings_path"])),
        ("settings_sha256", isinstance(m["settings_sha256"], str) and _HEX64.match(m["settings_sha256"]) is not None),
        ("canonical_workspace", _abs_path(m["canonical_workspace"])),
        ("allowed_root", _abs_path(m["allowed_root"])),
        ("launch_dir", isinstance(m["launch_dir"], dict) and set(m["launch_dir"]) == {"path", "inode", "uid"}
                       and _abs_path(m["launch_dir"]["path"]) and _int_in(m["launch_dir"]["inode"], 0, 2 ** 63)
                       and _int_in(m["launch_dir"]["uid"], 0, 2 ** 31)),
        ("scratch", isinstance(m["scratch"], dict)
                    and set(m["scratch"]) == {"path", "inode", "uid", "per_uid_tmp_bytes"}
                    and _abs_path(m["scratch"]["path"]) and _int_in(m["scratch"]["inode"], 0, 2 ** 63)
                    and _int_in(m["scratch"]["uid"], 0, 2 ** 31)
                    and _int_in(m["scratch"]["per_uid_tmp_bytes"], 0, CLAUDE_TMP_PATH_LIMIT)),
        ("state", m["state"] in _STREAM_STATES),
        ("created", _epoch_ok(m["created"])),
        ("leader", m["leader"] is None or (isinstance(m["leader"], dict)
                                           and set(m["leader"]) == {"pid", "start", "source"}
                                           and _int_in(m["leader"]["pid"], 1, 99999)
                                           and _start_ok(m["leader"]["start"])
                                           and m["leader"]["source"] in ("libproc", "ps"))),
        ("observed", isinstance(m["observed"], list) and len(m["observed"]) <= 4096
                     and all(isinstance(x, list) and len(x) == 2 and _int_in(x[0], 1, 99999)
                             and _start_ok(x[1]) for x in m["observed"])),
        ("boundary", isinstance(m["boundary"], dict) and len(m["boundary"]) <= 16
                     and all(isinstance(k, str) and isinstance(v, str) and len(v) <= 512
                             for k, v in m["boundary"].items())),
        ("pipeline_id", isinstance(m["pipeline_id"], str) and FLOW_ID_RE.match(m["pipeline_id"]) is not None),
        ("task_id", isinstance(m["task_id"], str) and TASK_ID_RE.match(m["task_id"]) is not None
                    and m["task_id"] not in (".", "..")),
        ("claude_session_id", m["claude_session_id"] is None
                              or (isinstance(m["claude_session_id"], str)
                                  and stream_protocol.UUID_RE.match(m["claude_session_id"]) is not None)),
        ("budget_usd", m["budget_usd"] is None or _budget_ok(m["budget_usd"])),
        ("retained_reason", "retained_reason" not in m
                            or (isinstance(m["retained_reason"], str) and len(m["retained_reason"]) <= 4096)),
        ("retained_at", "retained_at" not in m or _epoch_ok(m["retained_at"])),
        ("ended_at", "ended_at" not in m or _epoch_ok(m["ended_at"])),
    ]
    for name, ok in checks:
        if not ok:
            return f"{name} 不合法"
    return None


def load_validated(base: Path, launch_id: str) -> dict:
    """Re-check everything the launch depends on. Raises ``LaunchRefused``;
    there is no partial or degraded result."""
    uid = os.getuid()
    ldir = launch_dir(base, launch_id)
    try:
        _owned_dir(sessions_root(base), uid)
        lst = _owned_dir(ldir, uid)
        m = _read_manifest(ldir, uid)
        if m.get("launch_id") != launch_id or m.get("engine") not in ENGINES:
            raise LaunchRefused("manifest_invalid", "manifest 與 launch id 不符")
        if m["launch_dir"] != {"path": str(ldir), "inode": lst.st_ino, "uid": uid}:
            raise LaunchRefused("drift", "launch 目錄身分已改變")
        settings_path = ldir / SETTINGS
        if m.get("settings_path") != str(settings_path):
            raise LaunchRefused("manifest_invalid", "settings 路徑不符")
        _owned_file(settings_path, uid)
        if _sha256(settings_path) != m.get("settings_sha256"):
            raise LaunchRefused("drift", "settings 內容已改變")
        scratch = Path(m["scratch"]["path"])
        if (scratch.parent != Path(SCRATCH_PARENT) or not scratch.name.startswith(SCRATCH_PREFIX)):
            raise LaunchRefused("manifest_invalid", "暫存區位置不符")
        sst = _owned_dir(scratch, uid)
        if sst.st_ino != m["scratch"]["inode"] or sst.st_uid != m["scratch"]["uid"]:
            raise LaunchRefused("drift", "暫存區身分已改變")
        if (m["engine"] in ("claude", "claude-stream")
                and len(per_uid_tmp(str(scratch), uid).encode("utf-8")) > CLAUDE_TMP_PATH_LIMIT):
            raise LaunchRefused("scratch_path_too_long", "暫存路徑過長")
        workdir = m.get("canonical_workspace")
        if (not isinstance(workdir, str) or os.path.realpath(workdir) != workdir
                or not os.path.isdir(workdir)):
            raise LaunchRefused("drift", "工作目錄已改變或不存在")
        # The same rules as at preparation, against the state as it is now.
        if _check_workdir(workdir, m.get("allowed_root") or str(Path.home()), Path(os.path.realpath(base))) != workdir:
            raise LaunchRefused("drift", "工作目錄不再符合規則")
        actual_settings = json.loads(settings_path.read_text(encoding="utf-8"))
        if m["engine"] == "claude-stream":
            _check_stream_fields(m)
            expected = stream_settings(workdir, str(scratch), uid, m.get("cli_version"))
        elif m["engine"] == "claude":
            expected = claude_settings(workdir, str(scratch), uid)
        else:
            mode = actual_settings.get("sandbox_mode") if isinstance(actual_settings, dict) else None
            if mode == "read-only":
                expected = codex_settings(workdir, str(scratch), sandbox_mode=mode, commit=False)
            elif mode == "workspace-write":
                expected = codex_settings(workdir, str(scratch), sandbox_mode=mode, commit=True)
            else:
                raise LaunchRefused("manifest_invalid", "Codex sandbox policy 欄位不符")
        if actual_settings != expected:
            raise LaunchRefused("drift", "settings 不是核准的形狀")
        if m["engine"] == "codex":
            # Pass exactly the object checked above to argv construction. Do
            # not reopen the settings file between validation and spawn.
            m["_validated_settings"] = actual_settings
        binary = m.get("cli_binary")
        if not isinstance(binary, str) or os.path.realpath(binary) != binary:
            raise LaunchRefused("drift", "CLI 路徑已改變")
        try:
            identity = binary_identity(binary)
        except OSError as exc:
            raise LaunchRefused("drift", "CLI 檔案已消失或不可執行") from exc
        if identity != m.get("cli_identity"):
            raise LaunchRefused("drift", "CLI 檔案在版本檢查後已改變")
    except (OSError, KeyError, TypeError) as exc:
        raise LaunchRefused("unsafe_path", f"launch 狀態無法驗證：{exc}") from exc
    return m


def _check_stream_fields(m: dict) -> None:
    """Design 2.1: every stream-only field, exactly (UUID, flow id, task id,
    a full model id, a finite positive budget once set)."""
    if not (isinstance(m.get("pipeline_id"), str) and FLOW_ID_RE.match(m["pipeline_id"])):
        raise LaunchRefused("manifest_invalid", "流程 id 格式不符")
    tid = m.get("task_id")
    if not (isinstance(tid, str) and TASK_ID_RE.match(tid)) or tid in (".", ".."):
        raise LaunchRefused("manifest_invalid", "任務 id 格式不符")
    if not (isinstance(m.get("model_id"), str) and STREAM_MODEL_RE.match(m["model_id"])):
        raise LaunchRefused("manifest_invalid", "模型 id 格式不符")
    if stream_protocol.constants_for(m.get("cli_version")) is None:
        raise LaunchRefused("manifest_invalid", "沒有串流模式常數的版本")
    sid, budget = m.get("claude_session_id"), m.get("budget_usd")
    if sid is not None and not (isinstance(sid, str) and stream_protocol.UUID_RE.match(sid)):
        raise LaunchRefused("manifest_invalid", "claude_session_id 格式不符")
    if budget is not None and not _budget_ok(budget):
        raise LaunchRefused("manifest_invalid", "額度必須是有限正數")


def update_manifest(base: Path, launch_id: str, **fields) -> dict:
    uid = os.getuid()
    ldir = launch_dir(base, launch_id)
    _owned_dir(ldir, uid)
    m = _read_manifest(ldir, uid)
    m.update(fields)
    _write_private(ldir / MANIFEST, json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                   replace=True)
    return m


def _retain(base: Path, launch_id: str, reason: str) -> dict:
    try:
        update_manifest(base, launch_id, state="manual_review", retained_reason=reason,
                        retained_at=time.time())
    except (OSError, LaunchRefused):
        pass
    return {"launch_id": launch_id, "cleaned": False, "retained_reason": reason}


def cleanup_launch(base: Path, launch_id: str, *, proven_dead: bool, reason: str = "") -> dict:
    """Delete exactly the recorded scratch and launch directory, and only when
    the caller has proven every tracked process dead. Anything unexpected
    leaves both in place, marked for manual review. Never globs."""
    uid = os.getuid()
    if not proven_dead:
        return _retain(base, launch_id, reason or "無法證明程序已全部結束")
    try:
        ldir = launch_dir(base, launch_id)
        lst = _owned_dir(ldir, uid)
        m = _read_manifest(ldir, uid)
        if m.get("launch_id") != launch_id or m["launch_dir"] != {"path": str(ldir), "inode": lst.st_ino, "uid": uid}:
            return _retain(base, launch_id, "launch 目錄身分與 manifest 不符")
        scratch = Path(m["scratch"]["path"])
        if scratch.parent != Path(SCRATCH_PARENT) or not scratch.name.startswith(SCRATCH_PREFIX):
            return _retain(base, launch_id, "暫存區位置與核准樣式不符")
        if _lexists(scratch):
            sst = _owned_dir(scratch, uid)
            if sst.st_ino != m["scratch"]["inode"]:
                return _retain(base, launch_id, "暫存區 inode 與 manifest 不符")
            shutil.rmtree(scratch)
            if _lexists(scratch):
                return _retain(base, launch_id, "暫存區刪除後仍存在")
        if m.get("engine") == "claude-stream" and _lexists(ldir / JOURNAL):
            # The journal is the session's record; it stays until the user
            # deletes the flow (design 2.5, 9). Only the scratch goes.
            update_manifest(base, launch_id, state="ended", ended_at=time.time())
            return {"launch_id": launch_id, "cleaned": True, "kept": "journal"}
        shutil.rmtree(ldir)
        if _lexists(ldir):
            return {"launch_id": launch_id, "cleaned": False, "retained_reason": "launch 目錄刪除後仍存在"}
    except (OSError, KeyError, TypeError, LaunchRefused) as exc:
        return _retain(base, launch_id, f"清理檢查失敗：{exc}")
    return {"launch_id": launch_id, "cleaned": True}


def discard_prepared(base: Path, launch_id: str) -> dict:
    """Remove a launch that was prepared but never handed to a process
    (an expired or refused preview). Refuses anything in another state."""
    uid = os.getuid()
    try:
        m = _read_manifest(launch_dir(base, launch_id), uid)
    except (OSError, LaunchRefused) as exc:
        return {"launch_id": launch_id, "cleaned": False, "retained_reason": f"manifest 無法讀取：{exc}"}
    if m.get("state") != "prepared" or m.get("native_session_id") or m.get("leader"):
        return {"launch_id": launch_id, "cleaned": False, "retained_reason": "launch 已交給 daemon，不可在此移除"}
    return cleanup_launch(base, launch_id, proven_dead=True)


def expire_prepared(base: Path) -> list[dict]:
    """Remove launches that were prepared but never started and are older than
    ``PREPARED_TTL`` (an abandoned preview, a server that went away). Called
    periodically by the running daemon; a prepared launch has never had a
    process, and anything in another state is left alone."""
    uid = os.getuid()
    root = sessions_root(base)
    if not root.is_dir() or root.is_symlink():
        return []
    out, now = [], time.time()
    for name in sorted(os.listdir(root)):
        if not LAUNCH_RE.match(name):
            continue
        try:
            m = _read_manifest(launch_dir(base, name), uid)
        except (OSError, LaunchRefused):
            continue
        created = m.get("created")
        if (m.get("state") == "prepared" and isinstance(created, (int, float))
                and not isinstance(created, bool) and now - created >= PREPARED_TTL):
            out.append(discard_prepared(base, name))
    return out


def _stream_process(m: dict, rows) -> tuple[str, str]:
    """("gone" | "alive" | "unknown", why) for a stream launch's recorded
    processes. Nothing is signalled."""
    if rows is None:
        return "unknown", "daemon 重啟後無法取得程序表"
    leader = m.get("leader")
    if not leader:
        return "unknown", "daemon 重啟後缺少 leader 身分紀錄"
    if leader.get("source") != proctrack.SOURCE:
        return "unknown", "程序身分紀錄的來源與目前不同，無法比對"
    identities = list(m.get("observed") or []) + [[leader["pid"], leader["start"]]]
    alive = proctrack.DescendantTracker(leader["pid"], identities).live(rows)
    if alive:
        return "alive", "daemon 重啟後仍有已記錄的程序存活：" + ", ".join(str(r["pid"]) for r in alive)
    # Part 2 review round 5 B-1: a member of the leader's group that was
    # never recorded (started after the last observation) is alive too.
    members = [r for r in rows if r["pgid"] == leader["pid"] and "Z" not in r["stat"]]
    if members:
        return "alive", "daemon 重啟後程序群組裡仍有未記錄的程序存活：" + ", ".join(str(r["pid"]) for r in members[:8])
    return "gone", ""


def _recover_stream(base: Path, name: str, m: dict, rows, has_journal: bool) -> dict:
    """Design v29.7: a stream launch a previous daemon left launching or
    running. The journal is read and replayed first: a damaged one is kept
    for a person (nothing written); a sound one gets a ``recovered`` fact,
    after which a dispatch that may have reached the CLI without a result
    counts at its worst case. Then the launch is cleaned up when its
    processes are provably gone, otherwise kept for manual review. Nothing
    is ever signalled here."""
    from . import stream_journal
    if not has_journal:
        if m.get("state") == "launching" and m.get("leader") is None and m.get("native_session_id") is None:
            # The journal is created before the process starts: none ever ran.
            return cleanup_launch(base, name, proven_dead=True)
        return _retain(base, name, "串流 launch 沒有日誌")
    process, why = _stream_process(m, rows)
    try:
        dfd = os.open(str(launch_dir(base, name)), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        return _retain(base, name, f"launch 資料夾無法開啟（{exc.strerror}）")
    try:
        res = stream_journal.read(dfd)
        if res.problem:
            return _retain(base, name, f"日誌無法使用（{res.problem}），需要人工檢查")
        if res.state.recovered is None:
            try:
                writer = stream_journal.JournalWriter.resume(dfd, res)
                try:
                    writer.append("recovered", {"process": process})
                finally:
                    writer.close()
            except (OSError, stream_journal.JournalCorrupt) as exc:
                return _retain(base, name, f"無法寫入恢復紀錄（{exc}）")
    finally:
        os.close(dfd)
    # v29.8: a failure found here (a turn cut off, or processes that cannot
    # be cleaned up) holds the flow until the user presses "continue".
    failed = res.state.failures[-1][0] if res.state.failures else (why if process != "gone" else "")
    if failed:
        from . import pipeline_store
        try:
            pipeline_store.hold(base, m["pipeline_id"], f"failure: session {name}: {failed}")
        except (OSError, pipeline_store.StoreRefused):
            pass                          # open_stream recomputes the failures from the journals
    if process == "gone":
        return cleanup_launch(base, name, proven_dead=True)
    return _retain(base, name, why)


def recover(base: Path) -> list[dict]:
    """Run once at daemon start, when the daemon owns no session.

    A launch left ``prepared`` or ``running`` belongs to a previous daemon.
    It is cleaned only if the recorded leader and every recorded descendant
    are provably gone; otherwise it is retained for manual review. Nothing
    is ever signalled here."""
    uid = os.getuid()
    root = sessions_root(base)
    if not root.is_dir() or root.is_symlink():
        return []
    try:
        rows = proctrack.process_table()
    except proctrack.ProcessTableUnavailable:
        rows = None
    out = []
    for name in sorted(os.listdir(root)):
        if not LAUNCH_RE.match(name):
            continue
        try:
            m = _read_manifest(launch_dir(base, name), uid)
        except (OSError, LaunchRefused):
            out.append({"launch_id": name, "cleaned": False, "retained_reason": "manifest 無法讀取"})
            continue
        if m.get("state") not in _ACTIVE_STATES:
            continue  # already under manual review
        if m.get("engine") == "claude-stream":
            try:
                has_journal = _lexists(launch_dir(base, name) / JOURNAL)
            except OSError as exc:
                out.append(_retain(base, name, f"日誌無法檢查（{exc}）"))
                continue
            if has_journal or m.get("state") != "prepared":
                out.append(_recover_stream(base, name, m, rows, has_journal))
                continue
        created = m.get("created")
        if m.get("state") == "prepared":
            if not isinstance(created, (int, float)) or isinstance(created, bool):
                out.append(_retain(base, name, "manifest 的 created 欄位損壞"))
                continue
            if time.time() - created < PREPARED_TTL:
                continue
        if rows is None:
            out.append(_retain(base, name, "daemon 重啟後無法取得程序表"))
            continue
        identities = list(m.get("observed") or [])
        leader = m.get("leader")
        if leader and leader.get("source") != proctrack.SOURCE:
            # Start times from another process-table source cannot be compared.
            out.append(_retain(base, name, "程序身分紀錄的來源與目前不同，無法比對"))
            continue
        if m.get("state") in ("launching", "running") and not leader:
            out.append(_retain(base, name, "daemon 重啟後缺少 leader 身分紀錄"))
            continue
        if leader:
            identities.append([leader["pid"], leader["start"]])
        tracker = proctrack.DescendantTracker(leader["pid"] if leader else 0, identities)
        alive = tracker.live(rows)
        if alive:
            out.append(_retain(base, name, "daemon 重啟後仍有已記錄的程序存活：" +
                               ", ".join(str(r["pid"]) for r in alive)))
        else:
            out.append(cleanup_launch(base, name, proven_dead=True))
    return out
