"""Launch preview and confirmation for Profile-managed Claude sessions (Phase R3 S0).

Flow: build a preview from a Profile and a work directory -> show what this
launch will and will not enforce -> the user confirms -> re-validate -> start.
A preview is single use and short lived; a changed Profile, settings digest,
CLI file or path invalidates it and a new preview is required.

What a preview states is derived from evidence, never from intent:
only one Claude configuration has been verified (CLI baseline version, Bash
tool confined by Claude's sandbox to the work directory and a session scratch,
Edit/Write tools not offered, empty network allowlist). A Profile that this
configuration cannot honour is reported as not launchable, with the reason;
nothing is silently widened or narrowed to make it fit.

The seven labels are launch metadata. They are not stored in the Profile and
they are not seven grades of one permission. None of them is an unbypassable
boundary: a user typing in the advanced terminal can change what the CLI does.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from .runtime import agent_sessions, cli_versions
from .runtime.native import NativeRuntimeError, NativeRuntimeUnavailable

PREVIEW_TTL = 300.0
PREVIEW_ID_BYTES = 16
MAX_PREVIEWS = 32
BYPASS_PTY = "使用者可在進階終端自行輸入指令或改變 CLI 行為；此標籤不是不可繞過的邊界"
EVIDENCE_S2 = ".local/spikes/r3/round9/s2-record.md"
EVIDENCE_T01 = ".local/spikes/r3/round9/controlled-temp-final-record.md"
# Evidence for the empty network allowlist with this exact settings shape
# (S0 acceptance, Claude Code 2.1.286): an HTTPS request was refused by the
# sandbox proxy and a direct TCP connect failed with EPERM, while the same
# request succeeded outside the sandbox. Set to None to report Network as
# unknown again if the settings shape or the CLI baseline changes.
NETWORK_EVIDENCE: str | None = ".local/spikes/r3/round9/controlled-temp-evidence/s0-summary.json"

ENFORCED = "強制（限已測路徑、版本與執行層）"
PARTIAL = "部分強制"
INTENT = "僅意圖"
UNKNOWN = "未知"
NOT_GRANTED = "不授予"
UNRESTRICTED = "未限制"
VERIFIED_INTENTS = {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"}


class PreviewError(Exception):
    """An HTTP-mappable refusal. ``status`` 409 always means: make a new preview."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def profile_digest(profile: dict) -> str:
    """Digest of the validated Profile snapshot (the Profile has no revision)."""
    stable = {k: v for k, v in profile.items() if not k.startswith("_")}
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def launch_blockers(profile: dict, commit, network) -> list[dict]:
    """Why this Profile and these launch inputs cannot be started as they are.
    Empty means the one verified configuration honours them."""
    out = []

    def block(code, message):
        out.append({"code": code, "message": message})

    tool = (profile.get("model") or {}).get("tool")
    if tool != "claude":
        block("tool_not_launchable",
              "shared 不是可啟動的工具" if tool == "shared" else "目前只有 Claude 有已驗證的受管啟動設定")
    if profile.get("enabled") is False:
        block("profile_disabled", "此 Profile 已停用")
    intents = profile.get("permission_intents") or {}
    for key in ("read", "write", "test", "deploy"):
        if intents.get(key, "unspecified") == "unspecified":
            block("intent_unspecified", f"{key} 未指定；未指定不會被當成允許")
    if intents.get("read") == "deny":
        block("read_deny_unenforceable", "無法強制禁止讀取：讀取範圍沒有被隔離")
    if intents.get("write") == "deny":
        block("readonly_unverified", "唯讀設定尚未在此啟動架構下驗證；已驗證的設定允許在工作目錄寫入")
    if intents.get("test") == "deny":
        block("test_deny_unenforceable", "無法強制禁止執行指令：已驗證的設定會提供 Bash 工具")
    if intents.get("deploy") == "allow":
        block("deploy_not_available", "沒有可安全表達「只可發布」的 CLI 設定；發布須留在 Agent session 之外")
    # Whitelist, not blacklist: the one verified configuration honours exactly
    # this combination. Anything else that slipped past the reasons above
    # (an unexpected value, a future intent key) is refused too.
    if not out and {k: intents.get(k) for k in VERIFIED_INTENTS} != VERIFIED_INTENTS:
        block("intents_not_supported", "此權限組合不是已驗證設定所能對應的組合")
    if commit is not True:
        block("commit_not_enforceable",
              "目前無法強制不 commit：工作目錄的 .git 在可寫範圍內。要啟動必須明確以 commit=true 知悉此事")
    if not (isinstance(network, dict) and network.get("enabled") is False
            and not network.get("approved_domains")):
        block("network_not_available", "已驗證的設定只有關閉網路（空 allowlist）；不支援開啟網路或指定網域")
    return out


def derive_labels(manifest: dict | None, workdir: str | None) -> dict:
    """The seven labels with the contract's metadata fields. ``manifest`` is
    None when nothing was prepared (the Profile is not launchable)."""
    version = (manifest or {}).get("cli_version") or "不適用"
    digest = (manifest or {}).get("settings_sha256") or "none"
    scratch = ((manifest or {}).get("scratch") or {}).get("path")
    write_scope = [p for p in (workdir, scratch) if p] or "不適用"
    unprepared = None if manifest else "此 Profile 無法啟動，未產生設定"

    def label(level, note, *, path_scope="不適用", evidence=(), unknown_reason="none"):
        return {"level": UNKNOWN if unprepared else level,
                "note": unprepared or note,
                "source_version": {"value": version, "kind": "本次啟動實測版本" if manifest else "不適用"},
                "settings_digest": digest,
                "path_scope": path_scope if manifest else "不適用",
                "evidence_refs": list(evidence) if manifest else [],
                "bypass": BYPASS_PTY,
                "unknown_reason": unprepared or unknown_reason}

    net = (label(ENFORCED, "空 allowlist：Bash 工具的對外連線被拒（已測：HTTPS 請求經沙盒 proxy 回 403、"
                           "直接 TCP 連線 EPERM；其他協定未測）", evidence=[NETWORK_EVIDENCE])
           if NETWORK_EVIDENCE else
           label(UNKNOWN, "設定為空 allowlist，但尚未以這組設定實測",
                 unknown_reason="空 allowlist 在此設定形狀下尚無實測證據"))
    return {
        "Read": label(INTENT, "讀取範圍沒有被隔離；同一使用者可讀的檔案都讀得到，包括其他 session 的暫存區",
                      evidence=[EVIDENCE_S2]),
        "Write": label(PARTIAL, "Bash 工具的寫入由 Claude 沙盒限制在工作目錄與本 session 暫存區（OS 拒絕）；"
                                "Edit/Write 工具未提供，屬工具層意圖，不是 OS 邊界",
                       path_scope=write_scope, evidence=[EVIDENCE_S2, EVIDENCE_T01]),
        "Test": label(INTENT, "可用 Bash 執行指令；只受寫入範圍與網路設定限制", evidence=[EVIDENCE_S2]),
        "Commit": label(UNRESTRICTED, "工作目錄內的 .git 在可寫範圍內，無法阻止本機 commit；未驗證 push",
                        path_scope=[workdir] if workdir else "不適用",
                        unknown_reason="未測試以 denyWrite 排除 .git 的效果"),
        "Deploy": label(NOT_GRANTED, "沒有可安全表達「只可發布」的設定；不提供"),
        "Network": net,
        "Filesystem": label(ENFORCED, "寫入邊界：工作目錄與本 session 暫存區之外的寫入被 OS 拒絕"
                                      "（含家目錄與全域 CLI 設定的已測路徑）。這不是讀取隔離",
                            path_scope=write_scope, evidence=[EVIDENCE_S2, EVIDENCE_T01]),
    }


class PreviewStore:
    """Server-held previews: short TTL, atomic single consumption."""

    def __init__(self, runtime, *, ttl: float = PREVIEW_TTL, allowed_root=None):
        """``allowed_root`` is a path or a callable returning the current one."""
        self._runtime = runtime
        self._ttl = ttl
        self._allowed_root = allowed_root
        self._lock = threading.Lock()
        self._previews: dict[str, dict] = {}

    def _discard(self, entry: dict) -> None:
        launch_id = entry.get("launch_id")
        if launch_id:
            try:
                self._runtime.discard_prepared_claude_launch(launch_id)
            except Exception:  # best effort; daemon recovery also expires stale prepared launches
                pass

    def _sweep(self, now: float) -> None:
        for pid in [k for k, v in self._previews.items() if v["expires"] <= now]:
            self._discard(self._previews.pop(pid))

    def create(self, profile: dict, workdir, commit=False, network=None) -> dict:
        if network is None:
            network = {"enabled": False, "approved_domains": []}
        if not isinstance(workdir, str) or not os.path.isabs(workdir):
            raise PreviewError(400, "bad_request", "workdir 必須是絕對路徑")
        canonical = os.path.realpath(workdir)
        if not os.path.isdir(canonical):
            raise PreviewError(400, "bad_request", "workdir 不存在")
        now = time.time()
        with self._lock:
            self._sweep(now)
            if len(self._previews) >= MAX_PREVIEWS:
                raise PreviewError(429, "too_many_previews", "待確認的 preview 過多，請稍後再試")
        blockers = launch_blockers(profile, commit, network)
        prepared = None
        if not blockers:
            model_id = (profile.get("model") or {}).get("model_id") or None
            try:
                prepared = self._runtime.prepare_managed_claude_launch(
                    {"cwd": canonical, **({"model_id": model_id} if model_id else {})},
                    allowed_root=self._allowed_root() if callable(self._allowed_root) else self._allowed_root)
            except cli_versions.VersionAssertionError as exc:
                blockers.append({"code": "cli_" + str(exc.code or "version"), "message": str(exc)})
            except agent_sessions.LaunchRefused as exc:
                blockers.append({"code": exc.code, "message": str(exc)})
            except NativeRuntimeError as exc:
                blockers.append({"code": "runtime", "message": str(exc)})
        manifest = prepared["manifest"] if prepared else None
        body = {
            "preview_id": None,
            "profile_id": profile.get("id"),
            "profile_revision": profile_digest(profile),
            "launchable": not blockers,
            "reasons": blockers,
            "launch_inputs": {"commit": commit is True, "network": {"enabled": False, "approved_domains": []}},
            "cli": ({"binary": manifest["cli_binary"], "version": manifest["cli_version"]} if manifest else None),
            "settings_digest": manifest["settings_sha256"] if manifest else None,
            "canonical_paths": {"workdir": canonical, "scratch": manifest["scratch"]["path"] if manifest else None},
            "derived_labels": derive_labels(manifest, canonical),
            "expires_at": None,
            "persisted": "commit 與 network 是本次啟動的輸入，不會寫回 Profile",
        }
        if prepared:
            preview_id = "p-" + secrets.token_hex(PREVIEW_ID_BYTES)
            entry = {"prepared": prepared, "launch_id": manifest["launch_id"],
                     "profile_id": profile.get("id"), "profile_digest": body["profile_revision"],
                     "settings_digest": manifest["settings_sha256"], "expires": now + self._ttl,
                     "consumed": False}
            with self._lock:
                self._previews[preview_id] = entry
            body["preview_id"] = preview_id
            body["expires_at"] = entry["expires"]
        return body

    def consume(self, preview_id, expected_settings_digest, user_confirmed, load_profile,
                *, cols: int | None = None, rows: int | None = None) -> dict:
        """Confirm and launch. ``load_profile(profile_id)`` returns the current
        Profile so a change since the preview is detected."""
        if user_confirmed is not True:
            raise PreviewError(400, "not_confirmed", "需要 user_confirmed: true")
        if not isinstance(preview_id, str) or not isinstance(expected_settings_digest, str):
            raise PreviewError(400, "bad_request", "preview_id 與 expected_settings_digest 必須是字串")
        now = time.time()
        with self._lock:
            entry = self._previews.get(preview_id)
            if entry is None:
                self._sweep(now)
                raise PreviewError(404, "preview_unknown", "沒有這個 preview（可能已過期或已使用）")
            if entry["consumed"]:
                raise PreviewError(409, "preview_consumed", "此 preview 已使用；請重新 preview")
            if entry["expires"] <= now:
                self._discard(self._previews.pop(preview_id))
                raise PreviewError(410, "preview_expired", "preview 已過期；請重新 preview")
            entry["consumed"] = True  # single use from here on, whatever happens next
        try:
            if expected_settings_digest != entry["settings_digest"]:
                raise PreviewError(409, "settings_drift", "settings digest 不符；請重新 preview")
            current = load_profile(entry["profile_id"])
            if current is None or profile_digest(current) != entry["profile_digest"]:
                raise PreviewError(409, "profile_drift", "Profile 在 preview 之後已變更；請重新 preview")
            try:
                result = self._runtime.launch_prepared_claude(entry["prepared"], cols=cols, rows=rows)
            except cli_versions.VersionAssertionError as exc:
                raise PreviewError(409, "cli_drift", f"CLI 在 preview 之後已變更：{exc}") from exc
            except NativeRuntimeUnavailable as exc:
                raise PreviewError(503, "runtime_unavailable", str(exc)) from exc
            except NativeRuntimeError as exc:
                # The daemon re-validates settings, paths and the CLI file and refuses on any change.
                raise PreviewError(409, "launch_refused", f"啟動前重新驗證未通過：{exc}；請重新 preview") from exc
        except PreviewError as exc:
            # 503: either nothing was sent (the runtime already removed the prepared
            # state) or the outcome is unknown and the daemon may own the launch; a
            # launch the daemon never started is expired by the daemon's own sweep.
            if exc.status != 503:
                self._discard(entry)
            with self._lock:
                self._previews.pop(preview_id, None)
            raise
        except BaseException:
            # Unexpected failure: never leave a consumed preview or its state behind.
            # _discard refuses anything a daemon has already taken over.
            self._discard(entry)
            with self._lock:
                self._previews.pop(preview_id, None)
            raise
        with self._lock:
            self._previews.pop(preview_id, None)
        return result

    def close(self) -> None:
        with self._lock:
            entries, self._previews = list(self._previews.values()), {}
        for entry in entries:
            if not entry["consumed"]:
                self._discard(entry)
