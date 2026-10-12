"""Preview and confirm a flow's risk acceptance (design 10; S2c-1).

The user never sends values to be recorded. ``preview`` gathers the facts
from this machine (the Claude Code and Codex versions that would run, the
models, both accounts' login fingerprints, the HMAC key's id, the limits),
writes them as a server-held preview record and returns what the screen
shows. ``confirm`` takes only the ``preview_id``: under the store's lock it
looks at the facts *again*, and if any of them is not what the record says
(a new login, a new CLI version, a new key, a new text) the preview is void
and the answer is 409; otherwise it writes the ``risk_acknowledged`` event
from the record's values.

Facts are read through a ``Host`` so that tests (and nothing else) can put
synthetic ones in its place; the default one runs the pinned binaries and
reads the real login files, and neither the full fingerprints nor anything
of the login files is returned or logged: the screen gets the first 16 hex
digits.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from . import acceptance, config as cfg, flows, login_identity, previews, risk_text
from .api_error import ApiError
from .runtime import cli_versions, codex_constants, pipeline_store, review_codex
from .runtime import native as rt_native

DEFAULT_EXECUTOR_MODEL = "claude-haiku-4-5-20251001"
SUGGESTED_EXECUTOR_MODELS = ("claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5")
DEFAULT_REVIEW_MODEL = "gpt-6-luna"
PREVIEW_KEYS = frozenset({"executor_model", "review_model", "limits"})
LIMIT_LABELS = {
    "max_reviews": ("審查次數", "次"), "max_dispatches": ("派工則數", "則"),
    "review_max_responses": ("單次審查的模型回應數（監測）", "次"),
    "executor_turn_max_responses": ("執行者每一輪的模型回應數", "次"),
    "executor_total_max_responses": ("執行者整個流程的模型回應數", "次"),
    "review_timeout_min": ("單次審查逾時", "分鐘"), "executor_turn_timeout_min": ("執行者一輪的硬逾時", "分鐘"),
    "max_elapsed_h": ("流程經過時間", "小時"), "executor_budget_usd": ("執行者額度（total_cost_usd）", "USD"),
}


class AcceptanceError(ApiError):
    """An acceptance step that cannot be done; see ApiError."""


class Host:
    """What this machine says. The default reads the pinned binaries and the
    login files; tests subclass it."""

    def claude_binary(self, cwd: str | None = None) -> tuple[str | None, str | None, str]:
        """(path, version, why not): the pinned Claude Code that would run."""
        binary = rt_native._pinned_claude_binary()
        res = cli_versions.check_cli_version("claude", binary, cwd=cwd or str(Path.home()), allow_unverified=True)
        if res.compatible and res.observed_version and res.binary_path:
            return res.binary_path, res.observed_version, ""
        return None, None, res.reason

    def claude_version(self) -> tuple[str | None, str]:
        _, version, why = self.claude_binary()
        return (version, "") if version else (None, why)

    def claude_json(self) -> Path:
        return Path.home() / ".claude.json"

    def codex_version(self) -> tuple[str | None, str]:
        for version in sorted(codex_constants.VERIFIED_VERSIONS, key=lambda v: tuple(int(x) for x in v.split(".")),
                              reverse=True):
            try:
                binary = review_codex.codex_binary(version)
            except review_codex.CodexRefused:
                continue
            seen, why = review_codex.read_version_detail(binary, cli_versions._run_probe)
            if seen == version:
                return seen, ""
        return None, "找不到已驗證版本的 Codex（固定安裝位置沒有，或版本不符）"

    def codex_binary_path(self, version: str) -> str | None:
        try:
            return review_codex.codex_binary(version)
        except review_codex.CodexRefused:
            return None


DEFAULT_HOST = Host()


def refuse_if_automatic(flow_id: str, what: str) -> None:
    """S3 v11.1 G4: while a flow is in automatic mode its manual dispatches,
    manual reviews and manual acceptances are refused (the daemon refuses the
    first two as well). To change something: stop, switch back to manual,
    approve again."""
    info = pipeline_store.mode_info(cfg.state_dir(), flow_id)
    if info["mode"] == "auto":
        raise AcceptanceError(409, "automation_active",
                              f"這個流程在自動執行模式，{what}一律拒絕；要先停止流程並切回手動")


# ---- the facts --------------------------------------------------------------------------------------------

def _flow(flow_id: str) -> dict:
    try:
        return flows.get_flow(flow_id)
    except KeyError:
        raise AcceptanceError(404, "no_flow", "找不到這個流程") from None


def _check_families(flow: dict) -> None:
    """Principle 5: the executor is Anthropic, the reviewer OpenAI."""
    roles = flow["roles"]
    if roles["executor"]["family"] != "anthropic":
        raise AcceptanceError(409, "family", "由 VBear 啟動的執行者必須是 Anthropic 家族（Claude）")
    if not any(r["family"] == "openai" for r in roles["reviewers"]):
        raise AcceptanceError(409, "family", "由 VBear 啟動 Codex 審查，需要一位 OpenAI 家族的審查者")


def _key(state: Path) -> login_identity.LoginKey:
    """The HMAC key; created only when it is missing or unusable (then no
    earlier acceptance can match it anyway), design 5.1."""
    try:
        return login_identity.load_login_key(state)
    except login_identity.KeyUnavailable:
        try:
            return login_identity.create_login_key(state, valid_acceptances=0)
        except (OSError, ValueError, login_identity.KeyUnavailable) as exc:
            raise AcceptanceError(500, "key", f"登入指紋金鑰無法建立（{type(exc).__name__}）") from exc


def _gather(host: Host, state: Path, key: login_identity.LoginKey, executor_model: str, review_model: str) -> dict:
    """The values an acceptance binds, checked. AcceptanceError for anything
    that cannot be accepted (no usable fact is read as a fact)."""
    if not (isinstance(executor_model, str) and acceptance.CLAUDE_MODEL_RE.match(executor_model)):
        raise AcceptanceError(400, "bad_model", "執行者必須用完整的 Claude 模型 id（不能用別名）")
    claude, why = host.claude_version()
    if claude is None:
        raise AcceptanceError(409, "claude_version", f"讀不到 Claude Code 的版本（{why}）")
    if claude not in cli_versions.stream_verified_versions():
        raise AcceptanceError(409, "claude_unverified", cli_versions.stream_unverified_text(claude))
    cfp = login_identity.claude_login_fingerprint(host.claude_json(), key)
    if not cfp.ok:
        raise AcceptanceError(409, "no_claude_login", f"取不到執行者的 Claude 帳號指紋（{cfp.problem}）")
    codex, why = host.codex_version()
    if codex is None:
        raise AcceptanceError(409, "codex_version", f"讀不到 Codex 的版本（{why}）")
    if codex not in codex_constants.VERIFIED_VERSIONS or codex not in codex_constants.VERSIONS:
        raise AcceptanceError(409, "codex_unverified", f"Codex {codex} 還沒有通過驗證")
    if review_model not in codex_constants.VERSIONS[codex].models:
        raise AcceptanceError(400, "bad_model", "審查模型不在這個 Codex 版本已驗證的清單內："
                              + "、".join(sorted(codex_constants.VERSIONS[codex].models)))
    home = review_codex.codex_home_path(state)
    try:
        review_codex.check_codex_home(state)
        xfp = login_identity.codex_login_fingerprint(home, key)
        problem = "" if xfp.ok else xfp.problem
    except review_codex.CodexRefused as exc:
        xfp, problem = None, str(exc)
    if xfp is None or not xfp.ok:
        binary = host.codex_binary_path(codex) or "codex"
        raise AcceptanceError(
            409, "needs_login", f"VBear 專用的 Codex 設定目錄還沒有可用的登入（{problem}）",
            login_command=f"CODEX_HOME={home} {binary} login -c cli_auth_credentials_store=file", codex_home=str(home))
    return {"text_version": acceptance.RISK_TEXT_VERSION, "codex_version": codex, "model": review_model,
            "executor_claude_version": claude, "executor_model": executor_model,
            "executor_login_fingerprint": cfp.hmac, "login_fingerprint": xfp.hmac, "login_key_id": key.key_id}


def _limits(over) -> dict:
    limits = dict(acceptance.DEFAULT_LIMITS)
    if over is None:
        return limits
    if not isinstance(over, dict):
        raise AcceptanceError(400, "bad_limits", "limits 必須是物件")
    unknown = set(over) - set(acceptance.LIMITS)
    if unknown:
        raise AcceptanceError(400, "bad_limits", "不認得的上限欄位：" + "、".join(sorted(map(str, unknown))))
    limits.update(over)
    problem = acceptance.limits_problem(limits)
    if problem:
        raise AcceptanceError(400, "bad_limits", f"上限不合法（{problem}）")
    return limits


def _display(fields: dict) -> dict:
    """What the screen shows of an acceptance: values, and the first 16 hex
    digits of each account's fingerprint, never the whole."""
    n = login_identity.DISPLAY_DIGITS
    return {
        "text_version": fields["text_version"],
        "codex_version": fields["codex_version"], "review_model": fields["model"],
        "executor_claude_version": fields["executor_claude_version"], "executor_model": fields["executor_model"],
        "executor_account": fields["executor_login_fingerprint"][:n],
        "review_account": fields["login_fingerprint"][:n], "login_key_id": fields["login_key_id"],
        "limits": [{"name": name, "label": LIMIT_LABELS[name][0], "unit": LIMIT_LABELS[name][1],
                    "value": fields["limits"][name], "default": default, "cap": cap}
                   for name, (default, cap) in acceptance.LIMITS.items()],
    }


# ---- preview and confirm -------------------------------------------------------------------------------------

def preview(flow_id: str, body, *, store: previews.PreviewStore, host: Host | None = None) -> dict:
    host = host or DEFAULT_HOST
    if body is None:
        body = {}
    if not isinstance(body, dict) or set(body) - PREVIEW_KEYS:
        raise AcceptanceError(400, "bad_request", "只接受 executor_model、review_model、limits")
    flow = _flow(flow_id)
    refuse_if_automatic(flow_id, "手動接受風險")
    _check_families(flow)
    state = cfg.state_dir()
    key = _key(state)
    limits = _limits(body.get("limits"))
    values = _gather(host, state, key, body.get("executor_model", DEFAULT_EXECUTOR_MODEL),
                     body.get("review_model", DEFAULT_REVIEW_MODEL))
    fields = {**values, "limits": limits}
    problem = acceptance.record_problem(fields)
    if problem:
        raise AcceptanceError(500, "internal", f"接受內容不合法（{problem}）")
    try:
        rec = store.create("acceptance", flow_id, {"fields": fields})
    except previews.PreviewError as exc:
        raise AcceptanceError(exc.status, exc.code, str(exc)) from exc
    return {"preview_id": rec["preview_id"], "expires_at": rec["expires"], "ttl_s": previews.TTL,
            "risk_text": {"zh": risk_text.render("zh"), "en": risk_text.render("en")},
            "values": _display(fields), "suggested_executor_models": list(SUGGESTED_EXECUTOR_MODELS),
            "review_models": sorted(codex_constants.VERSIONS[fields["codex_version"]].models)}


def confirm(flow_id: str, body, *, store: previews.PreviewStore, host: Host | None = None) -> dict:
    """The user's approval. ``body`` is exactly {"preview_id"}: the values
    come from the stored record and nowhere else."""
    host = host or DEFAULT_HOST
    if not isinstance(body, dict) or set(body) != {"preview_id"}:
        raise AcceptanceError(400, "bad_request", "只接受 preview_id；要記錄的值一律取自預覽紀錄")
    _flow(flow_id)
    refuse_if_automatic(flow_id, "手動接受風險")

    def check(rec: dict) -> None:
        stored = rec["data"]["fields"]
        try:
            _check_families(_flow(flow_id))
        except AcceptanceError as exc:
            raise previews.PreviewError("conflict", f"預覽之後的情況已改變（{exc}），請重新預覽") from exc
        state = cfg.state_dir()
        try:
            key = login_identity.load_login_key(state)
        except login_identity.KeyUnavailable as exc:
            raise previews.PreviewError("conflict", f"登入指紋金鑰已不可用（{exc}），請重新預覽") from exc
        try:
            now = _gather(host, state, key, stored["executor_model"], stored["model"])
        except AcceptanceError as exc:
            raise previews.PreviewError("conflict", f"預覽之後的情況已改變（{exc}），請重新預覽") from exc
        changed = [name for name in now if now[name] != stored[name]]
        if changed:
            raise previews.PreviewError("conflict", "預覽之後下列內容已改變，請重新預覽：" + "、".join(sorted(changed)))
        problem = acceptance.record_problem(stored)
        if problem:
            raise previews.PreviewError("invalid", f"預覽內容不合法（{problem}）")

    try:
        rec = store.consume(body["preview_id"], kind="acceptance", flow_id=flow_id, check=check)
        flow = flows.append_risk_acknowledged(flow_id, rec["data"]["fields"])
    except previews.PreviewError as exc:
        raise AcceptanceError(exc.status, exc.code, str(exc)) from exc
    except ValueError as exc:
        raise AcceptanceError(400, "bad_request", str(exc)) from exc
    except KeyError:
        raise AcceptanceError(404, "no_flow", "找不到這個流程") from None
    return flow


# ---- what a flow shows ---------------------------------------------------------------------------------------

FACT_TTL = 10.0                       # how long the machine's facts are reused for the screen (Codex S2c-1 review)
_FACT_LABELS = {"claude_version": "Claude Code 版本", "claude_account": "執行者的 Claude 帳號",
                "codex_version": "Codex 版本", "codex_account": "審查者的 Codex 帳號"}
_facts_lock = threading.Lock()
_facts_cache: dict = {}


def _machine_facts(host: Host, state: Path, key: login_identity.LoginKey) -> dict:
    """The four things an acceptance binds that can change without it:
    {name: (value or None, why not)}. Nothing is a guess: a fact that cannot
    be had is None with its reason."""
    facts: dict = {}
    version, why = host.claude_version()
    facts["claude_version"] = (version, why)
    cfp = login_identity.claude_login_fingerprint(host.claude_json(), key)
    facts["claude_account"] = (cfp.hmac, "") if cfp.ok else (None, cfp.problem)
    version, why = host.codex_version()
    facts["codex_version"] = (version, why)
    try:
        review_codex.check_codex_home(state)
        xfp = login_identity.codex_login_fingerprint(review_codex.codex_home_path(state), key)
        facts["codex_account"] = (xfp.hmac, "") if xfp.ok else (None, xfp.problem)
    except review_codex.CodexRefused as exc:
        facts["codex_account"] = (None, str(exc))
    return facts


def _cached_facts(host: Host, state: Path, key: login_identity.LoginKey, now: float) -> dict:
    """The facts, gathered at most once per FACT_TTL for the whole machine
    (the screen polls; the CLIs are not run each time). The real protection
    is the re-check at review_start and open_stream: this only keeps the
    screen honest."""
    token = (str(state), key.key_id, id(host))
    with _facts_lock:
        hit = _facts_cache.get(token)
        if hit is not None and 0 <= now - hit[0] < FACT_TTL:
            return hit[1]
        facts = _machine_facts(host, state, key)
        _facts_cache.clear()
        _facts_cache[token] = (now, facts)
        return facts


def claude_stream_support(*, host: Host | None = None, now: float | None = None) -> dict:
    """The Claude Code version this machine would run and whether its stream
    mode is verified (cli_versions.stream_support), for the flow screen to
    show BEFORE the executor is started. The version is read at most once per
    FACT_TTL, like the facts of the acceptance; the real check is still the
    one at the acceptance and at open_stream."""
    host = host or DEFAULT_HOST
    now = time.time() if now is None else now
    token = ("claude_stream_support", id(host))
    with _facts_lock:
        hit = _facts_cache.get(token)
        if hit is None or not 0 <= now - hit[0] < FACT_TTL:
            hit = (now, host.claude_version())
            _facts_cache[token] = hit
    version, why = hit[1]
    return cli_versions.stream_support(version, why)


def status(flow: dict, state: Path | None = None, *, host: Host | None = None, now: float | None = None) -> dict:
    """The newest acceptance of a flow and whether it counts now.

      none     there is no acceptance;
      valid    it is for the current text and key, and every bound fact
               (both CLI versions, both accounts) is what it was;
      stale    it no longer counts, and why: a new text or key, or a bound
               value that is different now (named);
      unknown  nothing differs that could be seen, but a fact could not be
               had (no login, a version that cannot be read): never "valid".

    The model and the limits are what was chosen, not facts of the machine."""
    state = state or cfg.state_dir()
    host = host or DEFAULT_HOST
    now = time.time() if now is None else now
    events = [e for e in flow.get("events", ()) if isinstance(e, dict) and e.get("kind") == "risk_acknowledged"]
    if not events:
        return {"state": "none", "reason": "還沒有接受殘餘風險"}
    last = events[-1]
    fields = acceptance.acceptance_fields(last)
    shown = _display(fields) if acceptance.record_problem(fields) is None else None
    try:
        key_obj = login_identity.load_login_key(state)
        key_id = key_obj.key_id
    except login_identity.KeyUnavailable as exc:
        return {"state": "stale", "reason": f"登入指紋金鑰不可用（{exc}），先前的接受已失效，請重新接受",
                "accepted_at": last["at"], "values": shown}
    if shown is None:
        return {"state": "stale", "reason": "接受紀錄不合法", "accepted_at": last["at"], "values": None}
    if fields["text_version"] != acceptance.RISK_TEXT_VERSION:
        return {"state": "stale", "reason": "風險文字已改版，請重新接受", "accepted_at": last["at"], "values": shown}
    if fields["login_key_id"] != key_id:
        return {"state": "stale", "reason": "登入指紋金鑰已更換，請重新接受", "accepted_at": last["at"], "values": shown}
    facts = _cached_facts(host, state, key_obj, now)
    bound = {"claude_version": fields["executor_claude_version"], "claude_account": fields["executor_login_fingerprint"],
             "codex_version": fields["codex_version"], "codex_account": fields["login_fingerprint"]}
    different = [name for name, (value, _) in facts.items() if value is not None and value != bound[name]]
    missing = [(name, why) for name, (value, why) in facts.items() if value is None]
    if different:
        text = "、".join(_FACT_LABELS[n] for n in different)
        return {"state": "stale", "reason": f"下列內容已和接受時不同：{text}。請重新接受", "changed": different,
                "accepted_at": last["at"], "values": shown}
    if missing:
        text = "；".join(f"{_FACT_LABELS[n]}（{why or '讀不到'}）" for n, why in missing)
        return {"state": "unknown", "reason": f"無法確認下列內容和接受時相同：{text}", "unavailable": [n for n, _ in missing],
                "accepted_at": last["at"], "values": shown}
    return {"state": "valid", "reason": "", "accepted_at": last["at"], "values": shown}
