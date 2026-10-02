"""Managed Claude launch state: per-session settings, scratch and manifest
(Phase R3 S2; boundary adopted 2026-10-02 = work directory + session-owned
controlled scratch).

Layout (decision D1):
  ``<state>/sessions/<launch-id>/``   0700, holds ``settings.json`` and
                                      ``manifest.json`` (0600)
  ``/private/tmp/sc-<random>/``       0700 scratch handed to the CLI through
                                      ``CLAUDE_CODE_TMPDIR``

The scratch is not under the state directory on purpose: Claude Code 2.1.286
falls back to the shared ``/tmp/claude-<uid>`` when its per-UID temp path
exceeds 44 UTF-8 bytes, and a path below ``~/.sid-console`` is longer than
that. The exact scratch path, inode, uid and mode are recorded in the manifest
and re-checked before every use and before deletion.

What this module does and does not provide:
  * Write isolation for Bash-tool commands is enforced by Claude's sandbox and
    was verified for 2.1.286 with exactly this settings shape and argv. Other
    CLI versions are refused by the caller's version check.
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

from . import proctrack

SESSIONS_DIR = "sessions"
MANIFEST = "manifest.json"
SETTINGS = "settings.json"
LAUNCH_RE = re.compile(r"^l-[0-9a-f]{16}$")
SCRATCH_PARENT = "/private/tmp"
SCRATCH_PREFIX = "sc-"
# Claude Code 2.1.286: per-UID temp path limit before the shared-tmp fallback.
CLAUDE_TMP_PATH_LIMIT = 44
MANIFEST_VERSION = 1
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,63}$")
# States recovery may act on; "manual_review" is left for a human.
_ACTIVE_STATES = ("prepared", "launching", "running")
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
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if replace:
        os.replace(target, path)


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


def claude_argv(manifest: dict) -> list[str]:
    """Trusted argv; nothing here comes from an RPC caller. Edit/Write tools are
    not offered (decision D4): they are not covered by the Bash sandbox."""
    argv = [manifest["cli_binary"], "--safe-mode", "--settings", manifest["settings_path"],
            "--permission-mode", "acceptEdits", "--tools", "Bash",
            "--disallowedTools", "Edit,Write", "--strict-mcp-config"]
    model_id = manifest.get("model_id")
    if model_id:
        if not isinstance(model_id, str) or not MODEL_ID_RE.match(model_id):
            raise LaunchRefused("manifest_invalid", "model id 格式不符")
        argv += ["--model", model_id]
    return argv


def _check_workdir(workdir: str, allowed_root: str, base: Path) -> str:
    if not isinstance(workdir, str) or not workdir or "\0" in workdir or not os.path.isabs(workdir):
        raise LaunchRefused("invalid_workdir", "工作目錄必須是絕對路徑")
    canonical = os.path.realpath(workdir)
    if not os.path.isdir(canonical):
        raise LaunchRefused("invalid_workdir", "工作目錄不存在")
    root = os.path.realpath(allowed_root)
    if canonical == root or os.path.commonpath([canonical, root]) != root:
        raise LaunchRefused("invalid_workdir", "工作目錄必須在允許的根目錄之內，且不能是根目錄本身")
    home = os.path.realpath(Path.home())
    protected = [os.path.realpath(base), os.path.join(home, ".claude"), os.path.join(home, ".codex"),
                 os.path.realpath(SCRATCH_PARENT), os.path.realpath("/tmp")]
    for p in protected:
        # The work directory becomes writable: it may neither contain nor be a protected location.
        if canonical == p or os.path.commonpath([canonical, p]) == canonical:
            raise LaunchRefused("invalid_workdir", f"工作目錄不可包含受保護的位置：{p}")
    for p in protected[:3]:
        if os.path.commonpath([canonical, p]) == p:
            raise LaunchRefused("invalid_workdir", f"工作目錄不可位於受保護的位置之內：{p}")
    return canonical


def prepare_claude_launch(base: Path, workdir: str, *, cli_binary: str, cli_version: str,
                          cli_identity: list[int], allowed_root: str | None = None,
                          model_id: str | None = None) -> dict:
    """Create the launch directory, scratch, settings and manifest. No process
    is started. On any failure everything created here is removed again."""
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
        _write_private(settings_path, json.dumps(claude_settings(canonical, str(scratch), uid),
                                                 ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "launch_id": launch_id,
            "native_session_id": None,
            "engine": "claude",
            "cli_binary": cli_binary,
            "cli_version": cli_version,
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
                "write": "enforced for Bash-tool commands (Claude sandbox; verified for this version/settings only)",
                "read": "not isolated",
                "edit_write_tools": "disabled",
                "network": "strict empty allowlist",
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
    path = ldir / MANIFEST
    _owned_file(path, uid)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchRefused("manifest_invalid", "manifest 無法讀取") from exc
    if not isinstance(data, dict) or data.get("manifest_version") != MANIFEST_VERSION:
        raise LaunchRefused("manifest_invalid", "manifest 格式不符")
    return data


def load_validated(base: Path, launch_id: str) -> dict:
    """Re-check everything the launch depends on. Raises ``LaunchRefused``;
    there is no partial or degraded result."""
    uid = os.getuid()
    ldir = launch_dir(base, launch_id)
    try:
        _owned_dir(sessions_root(base), uid)
        lst = _owned_dir(ldir, uid)
        m = _read_manifest(ldir, uid)
        if m.get("launch_id") != launch_id or m.get("engine") != "claude":
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
        if len(per_uid_tmp(str(scratch), uid).encode("utf-8")) > CLAUDE_TMP_PATH_LIMIT:
            raise LaunchRefused("scratch_path_too_long", "暫存路徑過長")
        workdir = m.get("canonical_workspace")
        if (not isinstance(workdir, str) or os.path.realpath(workdir) != workdir
                or not os.path.isdir(workdir)):
            raise LaunchRefused("drift", "工作目錄已改變或不存在")
        # The same rules as at preparation, against the state as it is now.
        if _check_workdir(workdir, m.get("allowed_root") or str(Path.home()), Path(os.path.realpath(base))) != workdir:
            raise LaunchRefused("drift", "工作目錄不再符合規則")
        expected = claude_settings(workdir, str(scratch), uid)
        if json.loads(settings_path.read_text(encoding="utf-8")) != expected:
            raise LaunchRefused("drift", "settings 不是核准的形狀")
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
        if scratch.exists() or scratch.is_symlink():
            sst = _owned_dir(scratch, uid)
            if sst.st_ino != m["scratch"]["inode"]:
                return _retain(base, launch_id, "暫存區 inode 與 manifest 不符")
            shutil.rmtree(scratch)
            if scratch.exists() or scratch.is_symlink():
                return _retain(base, launch_id, "暫存區刪除後仍存在")
        shutil.rmtree(ldir)
        if ldir.exists():
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
