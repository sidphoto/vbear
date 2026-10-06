"""Agent Profile storage, validation, and lifecycle management (Phase C1).

An Agent Profile is a user-assembled bundle the console persists *only inside
its own state directory*. It is NOT an AgentRole: roles are the read-only
configuration the scanner picked up from `~/.codex/agents`, `~/.claude/agents`,
plugin caches and similar sources; profiles are the user's own composition of
a Profession (chosen from the read-only role catalog), a tool/model setting,
and a Skill Loadout. The two never leak into each other's namespaces.

Profiles are also NOT what an Agent Session runs with. Equipped is never Loaded
(plan section 2.1): the loadout field lists skills by their scanner id, but
saving a profile never starts, restarts, or injects anything into a session.
A profile's permission_intents keys are always intent-only — they are not
applied to the underlying CLI tools and never relax or strengthen any
existing per-call authority of the CLI tools themselves.

Storage follows the same fail-closed invariants as tasks.py:

  * `~/.vbear/agent_profiles.json` is owner-only (0600), in a 0700 dir.
  * Cross-process lock (flock) + thread lock guard the entire read-modify-write.
  * Writes go to a unique mkstemp temp, fsync, chmod 0600, atomic replace,
    then directory fsync.
  * A corrupt store is quarantined and a marker file blocks further reads
    and writes until a human clears it (see _mark_corrupt).
  * Reads fail closed (TaskStorageError) for permissions, symlinks, hard
    links and missing fields — never silently returning an empty profile set.
  * Strict schema: unknown top-level and unknown profile fields are rejected,
    so the file cannot quietly drift into shapes it can't promise to interpret.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import config as cfg

MAX_PROFILES = 500
MAX_TEXT_NAME = 200
MAX_MODEL_ID = 200
MAX_TOOL_ID = 64
MAX_SKILLS_PER_PROFILE = 200
MAX_PROFILE_ID_LEN = 64
MAX_PROFILE_ID_BODY = 63

# Same safe character class as Task IDs (plan section 4.1): the body is
# kept short because it is also visible in URLs the agent builder renders.
VALID_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")

# Fixed key set from C-D4: read / write / test / deploy. The values are the
# three intent levels the UI is allowed to pick. Anything else (including a
# client-supplied "enforce":true, "force":true, etc.) is rejected at the
# validation boundary.
PERMISSION_KEYS: tuple[str, ...] = ("read", "write", "test", "deploy")
PERMISSION_VALUES: tuple[str, ...] = ("allow", "deny", "unspecified")

# The fixed tool ids the catalog is allowed to advertise in this build.
# Anything else a client claims as model.tool is rejected; a future Phase C
# slice that adds new tools must add them here too. There is intentionally
# no separate "model registry" file: this list IS the registry.
KNOWN_TOOLS: frozenset[str] = frozenset({"claude", "codex", "shared"})


class AgentProfileStorageError(RuntimeError):
    """Raised when agent_profiles.json is corrupted and needs manual recovery.

    Reads and writes are blocked until the corrupt file's quarantine copy has
    been inspected and the marker below removed by a human.
    """


_lock = threading.Lock()


def _path() -> Path:
    return cfg.state_dir() / "agent_profiles.json"


def _lock_path() -> Path:
    return cfg.state_dir() / "agent_profiles.json.lock"


def _corrupt_marker_path() -> Path:
    return cfg.state_dir() / "agent_profiles.json.corrupted"


# --- shared fsync / quarantine plumbing ----------------------------------------
# The corruption-recovery path is identical in shape to tasks.py's, but lives
# here instead of being imported from tasks.py so this module remains
# independently reusable (and can be tightened independently later without
# a coordinated change to the tasks storage invariants). Both modules must
# keep their invariant identical: marker first, never move first; the only
# way to get out of a marker write failure is to retry or get human help.

def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_marker(
    marker: Path, quarantine_path: Path, original_path: Path, exc: Exception
) -> None:
    payload = json.dumps(
        {
            "detected_at": time.time(),
            "quarantine_file": str(quarantine_path),
            "original_file": str(original_path),
            "error": str(exc),
        },
        ensure_ascii=False,
        indent=2,
    )
    fd, tmp_name = tempfile.mkstemp(
        dir=marker.parent, prefix=marker.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, cfg.STATE_FILE_MODE)
        os.replace(tmp, marker)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise

    try:
        _fsync_dir(marker.parent)
    except OSError:
        pass


def _mark_corrupt(path: Path, marker: Path, exc: Exception) -> Path:
    """Quarantine `path` and durably write the marker that blocks all
    further reads and writes. See tasks._mark_corrupt for the full fail-closed
    rationale; the same ordering and the same never-rollback-the-move rule
    applies here.
    """
    quarantine_path = path.with_name(f"{path.name}.corrupt-{int(time.time())}")

    try:
        _write_marker(marker, quarantine_path, path, exc)
    except OSError as marker_exc:
        raise AgentProfileStorageError(
            f"Agent Profile 儲存損毀復原失敗：無法寫入復原標記 {marker}（{marker_exc}）。"
            f"損毀檔案未搬移、原封保留於 {path}，下次讀取會重新嘗試隔離；"
            "請人工檢查檔案系統（磁碟空間與權限）後重試"
        ) from marker_exc

    try:
        path.rename(quarantine_path)
    except OSError as move_exc:
        remark = ""
        try:
            _write_marker(marker, path, path, exc)
        except OSError as remark_exc:
            remark = f"；另外無法更新標記內的實際位置（{remark_exc}）"
        raise AgentProfileStorageError(
            f"Agent Profile 儲存檔案損毀，且無法搬移至 {quarantine_path}（{move_exc}）。"
            f"損毀檔案原地保留於 {path}，復原標記 {marker} 已寫入，"
            f"讀寫已封鎖至人工復原為止{remark}"
        ) from move_exc

    try:
        _fsync_dir(path.parent)
    except OSError:
        pass

    return quarantine_path


def _read_raw(path: Path) -> str | None:
    """Read agent_profiles.json's exact bytes, or None if it simply doesn't
    exist yet. Fails closed (raises OSError) for any other filesystem
    surprise — permissions, a symlink where a regular file must be, an
    unexpected hard link, or a directory in the way.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"agent_profiles.json 不是一般檔案 (mode={oct(st.st_mode)})")
        if st.st_nlink > 1:
            raise OSError(
                f"agent_profiles.json 有多個硬連結 (nlink={st.st_nlink})，拒絕讀取"
            )
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            return fh.read()
    finally:
        if fd != -1:
            os.close(fd)


@contextlib.contextmanager
def _cross_process_lock(timeout: float = 10.0):
    """OS-level exclusive lock spanning save_profile()/delete_profile().

    See tasks._cross_process_lock for the rationale: a process-level
    threading.Lock alone cannot see a *second* vbear process (e.g. a CLI
    running alongside the server) doing the same read-modify-write, so two
    writes would silently lose one of them. flock() is enough on its own —
    it also serialises threads inside this process, because each acquire
    opens its own fd.
    """
    cfg.ensure_state_dir()
    fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, cfg.STATE_FILE_MODE)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AgentProfileStorageError(
                        "Agent Profile 儲存鎖定逾時（可能有其他程序正在寫入），請稍後再試"
                    )
                time.sleep(0.02)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


# --- schema validation -------------------------------------------------------

def _entry_schema_problem(key: Any, value: Any, known_skills: set[str],
                          known_roles: set[str]) -> str | None:
    """None if `value` is a plausible stored profile record for `key`;
    otherwise a short reason it isn't. Conservative: only rejects shapes
    this module could never have produced (wrong id, missing name, an
    out-of-enum permission value, ...), so a future schema extension that
    adds new optional fields does not start failing closed on previously
    valid data.

    `known_skills` and `known_roles` are the *current* catalog sets, not
    historical ones. A profile keeps references that have since disappeared
    from the catalog; that is handled separately as unresolved at the API
    layer, not as a storage-shape error.
    """
    if not isinstance(key, str) or not VALID_PROFILE_ID_RE.match(key):
        return "鍵值不是有效的 Profile 識別碼"
    if not isinstance(value, dict):
        return "值不是物件"
    if value.get("id") != key:
        return "id 欄位與鍵值不一致"
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return "name 缺失或為空白"

    profession = value.get("profession_role_id")
    if profession is not None and not isinstance(profession, str):
        return "profession_role_id 必須是字串或 null"
    if isinstance(profession, str) and len(profession) > 256:
        return "profession_role_id 過長"

    model = value.get("model")
    if not isinstance(model, dict):
        return "model 不是物件"
    tool = model.get("tool")
    if not isinstance(tool, str) or tool not in KNOWN_TOOLS:
        return "model.tool 不是支援的工具識別"
    model_id = model.get("model_id", "")
    if not isinstance(model_id, str):
        return "model.model_id 必須是字串"
    if len(model_id) > MAX_MODEL_ID:
        return f"model.model_id 過長 (>{MAX_MODEL_ID})"

    skills = value.get("equipped_skill_ids")
    if not isinstance(skills, list):
        return "equipped_skill_ids 不是陣列"
    if len(skills) > MAX_SKILLS_PER_PROFILE:
        return f"equipped_skill_ids 過多 (>{MAX_SKILLS_PER_PROFILE})"
    for s in skills:
        if not isinstance(s, str) or not s:
            return "equipped_skill_ids 含非字串或空白項"

    perms = value.get("permission_intents")
    if not isinstance(perms, dict):
        return "permission_intents 不是物件"
    for pk, pv in perms.items():
        if pk not in PERMISSION_KEYS:
            return f"permission_intents 包含未支援的鍵：{pk!r}"
        if pv not in PERMISSION_VALUES:
            return f"permission_intents.{pk} 的值不是合法意圖：{pv!r}"

    if "enabled" in value and not isinstance(value["enabled"], bool):
        return "enabled 必須是布林"

    for ts_field in ("created_at", "updated_at"):
        if ts_field in value and not isinstance(value[ts_field], (int, float)):
            return f"{ts_field} 非數值"

    return None


def _normalize_profile(value: dict[str, Any], *, profile_id: str,
                       existing: dict[str, Any] | None,
                       existing_ids: set[str],
                       known_skills: set[str],
                       known_roles: set[str]) -> dict[str, Any]:
    """Validate and reduce `value` to the on-disk shape, with timestamps and
    the unresolved-reference view attached. The on-disk shape is the only
    shape the rest of this module trusts; the API layer can re-decorate it.
    """
    name = _clean_str(value.get("name") or (existing.get("name") if existing else ""),
                      MAX_TEXT_NAME)
    if not name:
        raise ValueError("Profile 名稱不得為空")

    profession = value.get("profession_role_id")
    if profession is not None and not isinstance(profession, str):
        raise ValueError("profession_role_id 必須是字串或 null")
    if isinstance(profession, str):
        profession = _clean_str(profession, 256)
        if profession and profession not in known_roles:
            # Keep the reference but mark it unresolved so the UI can still
            # render and the user can re-pick. Silently rewriting to null
            # would lose data.
            stored_profession = profession
            profession_unresolved = True
        else:
            stored_profession = profession
            profession_unresolved = False
    else:
        stored_profession = None
        profession_unresolved = False

    model_raw = value.get("model")
    if model_raw is None and existing is not None:
        model_raw = existing.get("model", {})
    if not isinstance(model_raw, dict):
        raise ValueError("model 必須是物件")
    tool = _clean_str(model_raw.get("tool") or "", MAX_TOOL_ID)
    if not tool or tool not in KNOWN_TOOLS:
        raise ValueError(f"model.tool 必須是支援的工具之一：{', '.join(sorted(KNOWN_TOOLS))}")
    model_id = _clean_str(model_raw.get("model_id", ""), MAX_MODEL_ID)

    skills_in = value.get("equipped_skill_ids")
    if skills_in is None:
        if existing is not None:
            skills_in = existing.get("equipped_skill_ids", [])
        else:
            skills_in = []
    if not isinstance(skills_in, list):
        raise ValueError("equipped_skill_ids 必須是陣列")
    equipped: list[str] = []
    seen: set[str] = set()
    for item in skills_in:
        s = _clean_str(item, 256)
        if not s or s in seen:
            continue
        seen.add(s)
        equipped.append(s)
    if len(equipped) > MAX_SKILLS_PER_PROFILE:
        raise ValueError(f"equipped_skill_ids 不可超過 {MAX_SKILLS_PER_PROFILE} 項")

    perms_in = value.get("permission_intents")
    if perms_in is None:
        if existing is not None:
            perms_in = existing.get("permission_intents", {})
        else:
            perms_in = {}
    if not isinstance(perms_in, dict):
        raise ValueError("permission_intents 必須是物件")
    extra_keys = sorted(k for k in perms_in.keys() if k not in PERMISSION_KEYS)
    if extra_keys:
        raise ValueError(
            "permission_intents 包含未支援的鍵：" + ", ".join(extra_keys)
        )
    permission_intents: dict[str, str] = {}
    for key in PERMISSION_KEYS:
        raw = perms_in.get(key) if isinstance(perms_in, dict) else None
        if raw is None:
            # Default to unspecified when the client omits the key, so the
            # on-disk shape always carries the full key set — the absence of a
            # value is itself a statement (and matches what the UI shows).
            permission_intents[key] = "unspecified"
            continue
        if not isinstance(raw, str):
            raise ValueError(f"permission_intents.{key} 必須是字串")
        if raw not in PERMISSION_VALUES:
            raise ValueError(
                f"permission_intents.{key} 必須是 {', '.join(PERMISSION_VALUES)} 之一"
            )
        permission_intents[key] = raw

    if "enabled" in value:
        enabled = bool(value["enabled"])
    elif existing is not None and "enabled" in existing:
        enabled = bool(existing["enabled"])
    else:
        enabled = True

    # Resolve current unresolved-reference view against today's catalog.
    # Unknown keys are filtered out of unknown_fields so the saved shape is
    # always the closed set this module knows how to read back.
    unknown_fields = sorted(
        k for k in value.keys()
        if k not in {
            "id", "name", "profession_role_id", "model", "equipped_skill_ids",
            "permission_intents", "enabled",
        }
    )
    if unknown_fields:
        raise ValueError(
            "Profile 包含未支援的欄位：" + ", ".join(unknown_fields)
        )

    skill_unresolved = [s for s in equipped if s not in known_skills]

    now = time.time()
    created_at = (existing.get("created_at") if existing else None) or now

    normalized = {
        "id": profile_id,
        "name": name,
        "profession_role_id": stored_profession,
        "model": {"tool": tool, "model_id": model_id},
        "equipped_skill_ids": equipped,
        "permission_intents": permission_intents,
        "enabled": enabled,
        "created_at": created_at,
        "updated_at": now,
        "_unresolved": {
            "profession": bool(profession_unresolved),
            "skills": skill_unresolved,
        },
    }
    return normalized


def _clean_str(value: Any, max_len: int = MAX_TEXT_NAME) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if "\x00" in text:
        text = text.replace("\x00", "")
    return text[:max_len]


def load_all(known_skills: set[str] | None = None,
             known_roles: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Load every stored Agent Profile from disk.

    `known_skills` and `known_roles` are the *current* scanner-derived
    catalogs; they decorate the loaded profiles with `_unresolved` markers
    but they do NOT change whether a profile loads. References that have
    since disappeared stay in the file (C-D1 / C-D2: never silently delete
    or rewrite to null).

    Raises AgentProfileStorageError (never silently returns {} or drops an
    entry) if the storage file exists but cannot be safely read, is
    corrupt, or holds an entry this module could never have written. A
    missing file is a normal empty/fresh state, not corruption.
    """
    skills = known_skills if known_skills is not None else set()
    roles = known_roles if known_roles is not None else set()

    marker = _corrupt_marker_path()
    if marker.exists():
        raise AgentProfileStorageError(
            f"Agent Profile 儲存先前偵測到損毀，需人工復原後才能繼續讀寫。"
            f"詳見 {marker}"
        )

    path = _path()
    try:
        raw = _read_raw(path)
    except OSError as exc:
        raise AgentProfileStorageError(
            f"無法安全讀取 Agent Profile 儲存檔案 {path}：{exc}；為避免資料遺失，"
            "讀寫已暫停，請人工檢查檔案系統（權限、是否為符號連結或硬連結）後重試"
        ) from exc
    if raw is None:
        return {}

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("agent_profiles.json 根節點必須為物件")
    except (ValueError, RecursionError) as exc:
        quarantine_path = _mark_corrupt(path, marker, exc)
        raise AgentProfileStorageError(
            f"Agent Profile 儲存檔案損毀，已隔離至 {quarantine_path}，"
            f"請人工復原後刪除 {marker} 以恢復讀寫"
        ) from exc

    profiles: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        problem = _entry_schema_problem(k, v, skills, roles)
        if problem is not None:
            exc = ValueError(f"Profile 項目 {k!r} 結構不符：{problem}")
            quarantine_path = _mark_corrupt(path, marker, exc)
            raise AgentProfileStorageError(
                f"Agent Profile 儲存檔案含有不符結構的項目（{k!r}：{problem}），"
                f"已隔離至 {quarantine_path}，請人工復原後刪除 {marker} 以恢復讀寫"
            ) from exc
        # Re-decorate the resolved/unresolved view against the current
        # catalog each time load_all runs, in case the catalog has changed.
        equipped = v.get("equipped_skill_ids") or []
        profession = v.get("profession_role_id")
        out_v = dict(v)
        out_v["_unresolved"] = {
            "profession": bool(profession) and profession not in roles,
            "skills": [s for s in equipped if s not in skills],
        }
        profiles[k] = out_v
    return profiles


def list_profiles(known_skills: set[str] | None = None,
                  known_roles: set[str] | None = None) -> list[dict[str, Any]]:
    """All profiles, newest update first."""
    with _lock:
        all_profiles = load_all(known_skills, known_roles)
    items = list(all_profiles.values())
    items.sort(key=lambda p: p.get("updated_at", 0), reverse=True)
    return items


def get_profile(profile_id: str, known_skills: set[str] | None = None,
                known_roles: set[str] | None = None) -> dict[str, Any] | None:
    if not isinstance(profile_id, str) or not profile_id:
        return None
    with _lock:
        return load_all(known_skills, known_roles).get(profile_id)


def save_profile(profile_id: str | None, body: dict[str, Any],
                 known_skills: set[str] | None = None,
                 known_roles: set[str] | None = None) -> dict[str, Any]:
    """Create or update one Agent Profile atomically, holding the cross-
    process lock for the entire read-modify-write. Same shape as
    tasks.save_task."""
    if not isinstance(body, dict):
        raise ValueError("Profile body 必須是物件")

    with _cross_process_lock():
        skills_cat = known_skills if known_skills is not None else set()
        roles_cat = known_roles if known_roles is not None else set()
        all_profiles = load_all(skills_cat, roles_cat)

        raw_id = profile_id if profile_id is not None else body.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raise ValueError("無效的 Profile 識別碼 (必須是字串)")
        if raw_id is not None:
            if not VALID_PROFILE_ID_RE.match(raw_id):
                raise ValueError(
                    "無效的 Profile 識別碼 (必須為 1-64 字元 ASCII 字母、數字、底線或連字號)"
                )
            tid = raw_id
        else:
            # Collision-resistant id, same approach as tasks.save_task.
            for _ in range(8):
                tid = f"prof-{secrets.token_hex(6)}"
                if tid not in all_profiles:
                    break
            else:
                raise ValueError("無法產生唯一的 Profile 識別碼，請稍後再試")

        existing = all_profiles.get(tid) if profile_id or raw_id else None
        if not existing and len(all_profiles) >= MAX_PROFILES:
            raise ValueError(f"Agent Profile 已達上限 {MAX_PROFILES} 筆")

        normalized = _normalize_profile(
            body, profile_id=tid, existing=existing,
            existing_ids=set(all_profiles.keys()),
            known_skills=skills_cat, known_roles=roles_cat,
        )
        # Strip the transient decoration before persisting; we recompute it
        # every load so the on-disk shape stays a closed, validated set.
        on_disk = {k: v for k, v in normalized.items() if not k.startswith("_")}
        all_profiles[tid] = on_disk
        data_str = json.dumps(all_profiles, ensure_ascii=False, indent=2)
        cfg.write_private(_path(), data_str)
    # Return the normalized record (with _unresolved) — that's what callers
    # want to render.
    return normalized


def delete_profile(profile_id: str) -> bool:
    """Delete one Agent Profile by id, holding the cross-process lock for the
    entire read-modify-write."""
    if not isinstance(profile_id, str) or not profile_id:
        return False
    with _cross_process_lock():
        all_profiles = load_all()
        if profile_id not in all_profiles:
            return False
        del all_profiles[profile_id]
        # Strip transient decoration before persisting; on-disk shape must
        # stay a closed, validated set (C-D1).
        cleaned = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                   for k, v in all_profiles.items()}
        data_str = json.dumps(cleaned, ensure_ascii=False, indent=2)
        cfg.write_private(_path(), data_str)
    return True


def duplicate_profile(profile_id: str,
                     known_skills: set[str] | None = None,
                     known_roles: set[str] | None = None) -> dict[str, Any] | None:
    """Create a copy of an existing profile with a fresh id and " (副本)"
    suffix on the name. Returns None if the source does not exist."""
    skills_cat = known_skills if known_skills is not None else set()
    roles_cat = known_roles if known_roles is not None else set()
    with _cross_process_lock():
        all_profiles = load_all(skills_cat, roles_cat)
        if profile_id not in all_profiles:
            return None
        if len(all_profiles) >= MAX_PROFILES:
            raise ValueError(f"Agent Profile 已達上限 {MAX_PROFILES} 筆")
        existing = all_profiles[profile_id]
        for _ in range(8):
            new_id = f"prof-{secrets.token_hex(6)}"
            if new_id not in all_profiles:
                break
        else:
            raise ValueError("無法產生唯一的 Profile 識別碼，請稍後再試")

        body = {
            "name": _clean_str((existing.get("name") or "") + " (副本)", MAX_TEXT_NAME),
            "profession_role_id": existing.get("profession_role_id"),
            "model": dict(existing.get("model") or {}),
            "equipped_skill_ids": list(existing.get("equipped_skill_ids") or []),
            "permission_intents": dict(existing.get("permission_intents") or {}),
            "enabled": bool(existing.get("enabled", True)),
        }
        normalized = _normalize_profile(
            body, profile_id=new_id, existing=None,
            existing_ids=set(all_profiles.keys()),
            known_skills=skills_cat, known_roles=roles_cat,
        )
        on_disk = {k: v for k, v in normalized.items() if not k.startswith("_")}
        all_profiles[new_id] = on_disk
        data_str = json.dumps(all_profiles, ensure_ascii=False, indent=2)
        cfg.write_private(_path(), data_str)
    return normalized