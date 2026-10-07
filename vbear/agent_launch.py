"""Launch preview and confirmation for Profile-managed Claude/Codex sessions.

Flow: build a preview from a Profile and a work directory -> show what this
launch will and will not enforce -> the user confirms -> re-validate -> start.
A preview is single use and short lived; a changed Profile, settings digest,
CLI file or path invalidates it and a new preview is required.

What a preview states is derived from engine-specific evidence, never from
intent. A Profile that the exact pinned CLI configuration cannot honour is
reported as not launchable, with the reason; nothing is silently widened.

The seven labels are launch metadata. They are not stored in the Profile and
they are not seven grades of one permission. None of them is an unbypassable
boundary: a user typing in the advanced terminal can change what the CLI does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from . import activity
from .runtime import agent_sessions, cli_versions
from .runtime.native import NativeRuntimeError, NativeRuntimeUnavailable

PREVIEW_TTL = 300.0
PREVIEW_ID_BYTES = 16
MAX_PREVIEWS = 32
BYPASS_PTY = ("使用者在進階終端可自行改變 CLI 行為；例如在 Claude Code 以 ! 開頭直接執行的 shell 指令"
              "不經沙盒（S0 驗收實測可寫入家目錄）。此標籤只約束 Agent，不是不可繞過的邊界")
BYPASS_CODEX_PTY = ("使用者在 Codex Terminal 可輸入 ! 直接執行使用者 shell，繞過 Codex sandbox；此標籤只描述 Agent 執行層，"
                    "不代表 OS 對使用者 shell 的隔離。")
# Public evidence per verified Claude Code version: docs/evidence/claude-code-<version>.md,
# with #writes, #network and #lifecycle sections.
EVIDENCE_DIR = "docs/evidence"
# The empty network allowlist with this exact settings shape was verified
# (HTTPS refused by the sandbox proxy, direct TCP EPERM). Set to False to
# report Network as unknown again if the settings shape changes.
NETWORK_VERIFIED = True


def _last_title_failure(engine: str | None, version: str) -> list[str] | None:
    """Failed title checks of this version's last verification on this Mac,
    or None when there is no failed title result to report."""
    if engine != "claude" or not isinstance(version, str):
        return None
    record = cli_versions.local_verified_versions().get(version) or {}
    title = record.get("title")
    if not isinstance(title, dict) or title.get("passed") is True:
        return None
    # Only a title report for this very version explains this version's failure.
    try:
        report = json.loads(Path(title.get("report") or "").read_text())
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(report, dict) or report.get("claude_version") != version:
        return None
    failed = title.get("failed")
    names = [n for n in failed if isinstance(n, str)][:8] if isinstance(failed, list) else []
    return names or ["unknown"]


def claude_evidence(version: str, section: str) -> str | None:
    """Evidence for a verified Claude Code version: the public page for a
    built-in one, the local report for one verified on this machine, None
    for an unverified version."""
    if not isinstance(version, str):
        return None
    if version in cli_versions.VERIFIED_VERSIONS["claude"]:
        return f"{EVIDENCE_DIR}/claude-code-{version}.md#{section}"
    record = cli_versions.local_verified_versions().get(version)
    if record and isinstance(record.get("report"), str):
        return record["report"]
    return None
CODEX_ACCEPTANCE_EVIDENCE: str | None = None
CODEX_EVIDENCE_CHECKS = frozenset({
    "readonly_workspace_denied", "readonly_tmp_denied", "workspace_write_allowed",
    "scratch_write_allowed", "shared_tmp_denied", "home_write_denied",
    "network_denied", "git_write_allowed",
})

ENFORCED = "強制（限已測路徑、版本與執行層）"
UNVERIFIED = "未驗證（此 Claude Code 版本尚未實測）"
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


def _codex_evidence_reference() -> str | None:
    """Return the evidence path only when its small acceptance record is complete."""
    reference = CODEX_ACCEPTANCE_EVIDENCE
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute() or ".." in Path(reference).parts:
        return None
    path = Path(__file__).resolve().parents[1] / reference
    try:
        if path.is_symlink() or path.stat().st_size > 32 * 1024:
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("engine") != "codex" or record.get("version") != "0.159.2":
        return None
    if not isinstance(record.get("binary_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["binary_sha256"]):
        return None
    checks = record.get("checks")
    if not isinstance(checks, dict) or not CODEX_EVIDENCE_CHECKS.issubset(checks):
        return None
    if not all(checks[name] is True for name in CODEX_EVIDENCE_CHECKS):
        return None
    return reference


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
    if tool not in {"claude", "codex"}:
        block("tool_not_launchable",
              "shared 不是可啟動的工具" if tool == "shared" else "此 Agent 工具沒有受管啟動設定")
    if profile.get("enabled") is False:
        block("profile_disabled", "此 Profile 已停用")
    intents = profile.get("permission_intents") or {}
    for key in ("read", "write", "test", "deploy"):
        if intents.get(key, "unspecified") == "unspecified":
            block("intent_unspecified", f"{key} 未指定；未指定不會被當成允許")
    if intents.get("read") == "deny":
        block("read_deny_unenforceable", "無法強制禁止讀取：讀取範圍沒有被隔離")
    if intents.get("write") == "deny":
        block("readonly_unverified", "此 R3 Profile 啟動組合尚未驗證唯讀模式；不會退化成可寫模式")
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
              "目前無法強制不 commit：工作目錄的 .git 在可寫範圍內。要啟動，請勾選「我知道這個設定無法阻止 commit」")
    if not (isinstance(network, dict) and network.get("enabled") is False
            and not network.get("approved_domains")):
        block("network_not_available", "已驗證的設定只有關閉網路（空 allowlist）；不支援開啟網路或指定網域")
    if tool == "codex" and not cli_versions.CODEX_INTERACTIVE_FLAGS_SUPPORTED:
        block("codex_interactive_flags_unsupported",
              "固定版 Codex CLI 0.159.2 只在 codex exec 支援 ignore-user-config/ephemeral；互動 TUI 會拒絕這些旗標，不能安全啟動受管 PTY")
    if tool == "codex" and _codex_evidence_reference() is None:
        block("codex_evidence_missing", "Codex 0.159.2 本輪 OS sandbox 驗收尚未完成；Network/Filesystem 維持未知並拒絕啟動")
    return out


def derive_labels(manifest: dict | None, workdir: str | None, engine: str | None = None) -> dict:
    """The seven labels with the contract's metadata fields. ``manifest`` is
    None when nothing was prepared (the Profile is not launchable)."""
    engine = (manifest or {}).get("engine") or engine
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
                "evidence_refs": [e for e in evidence if e] if manifest else [],
                "bypass": BYPASS_CODEX_PTY if engine == "codex" else BYPASS_PTY,
                "unknown_reason": unprepared or unknown_reason}

    writes, lifecycle = claude_evidence(version, "writes"), claude_evidence(version, "lifecycle")
    unverified = bool(manifest) and engine == "claude" and manifest.get("cli_verified") is False
    net = (label(ENFORCED, "空 allowlist：Bash 工具的對外連線被拒（已測：HTTPS 請求經沙盒 proxy 回 403、"
                           "直接 TCP 連線與連回本機 EPERM；其他協定未測）",
                 evidence=[claude_evidence(version, "network")])
           if NETWORK_VERIFIED else
           label(UNKNOWN, "設定為空 allowlist，但尚未以這組設定實測",
                 unknown_reason="空 allowlist 在此設定形狀下尚無實測證據"))
    if engine == "codex":
        codex_ref = _codex_evidence_reference()
        codex_evidence = [codex_ref] if codex_ref else []
        codex_unknown = ("尚無 Codex 0.159.2 OS sandbox 驗收證據" if not codex_evidence else "none")
        codex_proven = bool(codex_evidence)
        scope = [workdir, scratch] if scratch else (workdir or "不適用")
        return {
            "Read": label(INTENT, "CLI 可讀取目前使用者可讀的其他路徑；沒有讀取隔離",
                           evidence=codex_evidence, unknown_reason=codex_unknown),
            "Write": label(ENFORCED if codex_proven else UNKNOWN,
                           "Codex 0.159.2 workspace-write 的 Bash 寫入限於工作目錄與本 launch scratch；/tmp 與 TMPDIR 排除路徑已由 OS 拒絕"
                           if codex_proven else "Codex workspace-write 邊界尚無本輪 OS 證據",
                           path_scope=scope, evidence=codex_evidence,
                           unknown_reason="none" if codex_proven else codex_unknown),
            "Test": label(INTENT, "可執行指令；執行能力由 Codex sandbox 管理，不是 Test-only 權限",
                          evidence=codex_evidence, unknown_reason=codex_unknown),
            "Commit": label(UNRESTRICTED, "commit=true 明確允許工作目錄與 .git 寫入；沒有命令樣式攔截，也不涵蓋 push",
                            path_scope=[workdir, str(Path(workdir) / ".git")] if workdir else "不適用",
                            evidence=codex_evidence, unknown_reason="none" if codex_proven else codex_unknown),
            "Deploy": label(NOT_GRANTED, "沒有 deploy 專用沙盒權限；不得把 shell 命令規則或網路設定當成完整部署隔離",
                            evidence=codex_evidence, unknown_reason=codex_unknown),
            "Network": label(ENFORCED if codex_proven else UNKNOWN,
                             "workspace-write 明確設 network_access=false；本輪數字 IP 連線由 OS sandbox 拒絕"
                             if codex_proven else "network_access=false 尚無本輪 OS 負向證據",
                             evidence=codex_evidence, unknown_reason="none" if codex_proven else codex_unknown),
            "Filesystem": label(ENFORCED if codex_proven else UNKNOWN,
                                "僅工作目錄、session scratch 與明確 opt-in 的 .git 可寫；讀取未隔離"
                                if codex_proven else "Codex filesystem sandbox 尚無本輪 OS 證據",
                                path_scope=scope, evidence=codex_evidence,
                                unknown_reason="none" if codex_proven else codex_unknown),
        }
    if unverified:
        why = f"Claude Code {version} 尚未驗證（說明見上方提示）"
        return {
            "Read": label(INTENT, "讀取範圍沒有被隔離；同一使用者可讀的檔案都讀得到", unknown_reason=why),
            "Write": label(UNVERIFIED, "設定為只允許寫入工作目錄與本 session 暫存區，但此版本未實測",
                           path_scope=write_scope, unknown_reason=why),
            "Test": label(INTENT, "可用 Bash 執行指令；限制尚未在此版本實測", unknown_reason=why),
            "Commit": label(UNRESTRICTED, "工作目錄內的 .git 在可寫範圍內，無法阻止本機 commit；未驗證 push",
                            path_scope=[workdir] if workdir else "不適用", unknown_reason=why),
            "Deploy": label(NOT_GRANTED, "沒有可安全表達「只可發布」的設定；不提供"),
            "Network": label(UNVERIFIED, "設定為空 allowlist（不連網），但此版本未實測", unknown_reason=why),
            "Filesystem": label(UNVERIFIED, "設定為工作目錄與本 session 暫存區之外不可寫，但此版本未實測",
                                path_scope=write_scope, unknown_reason=why),
        }
    return {
        "Read": label(INTENT, "讀取範圍沒有被隔離；同一使用者可讀的檔案都讀得到，包括其他 session 的暫存區",
                      evidence=[writes]),
        "Write": label(PARTIAL, "Bash 工具的寫入由 Claude 沙盒限制在工作目錄與本 session 暫存區（OS 拒絕）；"
                                "Edit/Write 工具未提供，屬工具層意圖，不是 OS 邊界",
                       path_scope=write_scope, evidence=[writes, lifecycle]),
        "Test": label(INTENT, "可用 Bash 執行指令；只受寫入範圍與網路設定限制", evidence=[writes]),
        "Commit": label(UNRESTRICTED, "工作目錄內的 .git 在可寫範圍內，無法阻止本機 commit；未驗證 push",
                        path_scope=[workdir] if workdir else "不適用",
                        unknown_reason="未測試以 denyWrite 排除 .git 的效果"),
        "Deploy": label(NOT_GRANTED, "沒有可安全表達「只可發布」的設定；不提供"),
        "Network": net,
        "Filesystem": label(ENFORCED, "Agent 的 Bash 工具寫入邊界：工作目錄與本 session 暫存區之外的寫入被 OS 拒絕"
                                      "（含家目錄與全域 CLI 設定的已測路徑）。這不是讀取隔離",
                            path_scope=write_scope, evidence=[writes, lifecycle]),
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
                discard = getattr(self._runtime, "discard_prepared_agent_launch", None)
                if discard is None:
                    discard = getattr(self._runtime, "discard_prepared_claude_launch", None)
                if discard is not None:
                    discard(launch_id)
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
        engine = (profile.get("model") or {}).get("tool")
        if not blockers:
            model_id = (profile.get("model") or {}).get("model_id") or None
            try:
                allowed_root = self._allowed_root() if callable(self._allowed_root) else self._allowed_root
                spec = {"cwd": canonical, **({"model_id": model_id} if model_id else {})}
                if engine == "claude":
                    prepared = self._runtime.prepare_managed_claude_launch(spec, allowed_root=allowed_root)
                elif engine == "codex":
                    prepared = self._runtime.prepare_managed_codex_launch(
                        {**spec, "commit": commit is True, "read_only": False}, allowed_root=allowed_root)
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
            "cli": ({"binary": manifest["cli_binary"], "version": manifest["cli_version"],
                     "verified": manifest.get("cli_verified") is not False,
                     # whether VBear can tell "working" from "waiting" for this version
                     "activity_verified": activity.title_verified(engine, manifest["cli_version"]),
                     # why the last title check on this Mac failed, if it did (retrying is allowed)
                     "activity_last_failure": _last_title_failure(engine, manifest["cli_version"])}
                    if manifest else None),
            "settings_digest": manifest["settings_sha256"] if manifest else None,
            "canonical_paths": {"workdir": canonical, "scratch": manifest["scratch"]["path"] if manifest else None},
            "derived_labels": derive_labels(manifest, canonical, (profile.get("model") or {}).get("tool")),
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
                *, cols: int | None = None, rows: int | None = None,
                accept_unverified_cli=None) -> dict:
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
            manifest = (entry.get("prepared") or {}).get("manifest") or {}
            if manifest.get("cli_verified") is False and accept_unverified_cli is not True:
                # Checked before consuming, so the same preview can still be confirmed.
                raise PreviewError(409, "cli_unverified_not_acknowledged",
                                   f"Claude Code {manifest.get('cli_version')} 尚未驗證；"
                                   "需要明確勾選「我知道這個版本未驗證，仍要啟動」")
            entry["consumed"] = True  # single use from here on, whatever happens next
        try:
            if expected_settings_digest != entry["settings_digest"]:
                raise PreviewError(409, "settings_drift", "settings digest 不符；請重新 preview")
            current = load_profile(entry["profile_id"])
            if current is None or profile_digest(current) != entry["profile_digest"]:
                raise PreviewError(409, "profile_drift", "Profile 在 preview 之後已變更；請重新 preview")
            try:
                if manifest.get("cli_verified") is False:
                    # accept_unverified_cli is True here (checked above, before consuming).
                    launch = self._runtime.launch_prepared_agent_after_acknowledgement
                else:
                    launch = getattr(self._runtime, "launch_prepared_agent", None)
                    if launch is None:
                        launch = self._runtime.launch_prepared_claude
                result = launch(entry["prepared"], cols=cols, rows=rows)
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
