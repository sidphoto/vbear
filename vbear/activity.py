"""Agent activity: what a session's Agent is doing, and how VBear knows.

The vocabulary follows OpenRig's agent state taxonomy, adapted to what VBear
can actually observe. Three axes are kept apart and never blended:

  session       does the process exist: ``present`` | ``exited``
  activity      what a present Agent is doing: ``working`` | ``waiting`` | ``unknown``
  resumability  whether the conversation could be continued. No source serves
                it in this version, so it is always ``unknown``.

``waiting`` means "not working; the Agent waits for the user". The only signal
VBear has (Claude Code's idle title mark) is shown both at the input prompt and
on dialogs, so VBear does not claim which of the two it is.

``needs_input`` is a count plus a short reason, never an activity value. No
source in this version can observe it: it stays ``{count: 0, reason: None}``
with ``needs_input_evidence`` None, which means "nobody can tell", not
"nothing is pending".

Evidence arrives in rungs, and each rung declares how far it is trusted for
this session:

  authoritative  consulted for the decision
  trial          recorded and shown, never consulted
  absent         the source does not exist for this session

A rung is authoritative only for the engine versions listed in ``VERIFIED``,
each backed by a file in docs/evidence/, plus (for the Claude title rung) the
versions whose title check passed on this Mac through 「驗證這個版本」
(``cli_versions.local_title_verified_versions``). Any other version gets the
same rung as trial. ``unknown`` is a first-class answer: it beats a confident
wrong one.
"""

from __future__ import annotations

import time

from .numbers import finite_real

SESSION_VALUES = ("present", "exited")
ACTIVITY_VALUES = ("working", "waiting", "unknown")
DISPLAY_VALUES = ("working", "waiting", "needs-input", "exited", "unknown")
TRUST_VALUES = ("authoritative", "trial", "absent")

RUNG_CLAUDE_TITLE = "claude-title"
RUNG_LABELS = {RUNG_CLAUDE_TITLE: "Claude Code 終端標題（Agent 自己回報）"}

# rung -> engine -> versions whose behaviour was observed and recorded.
VERIFIED = {
    # docs/evidence/claude-code-2.1.291-activity.md, docs/evidence/claude-code-2.1.292-activity.md
    RUNG_CLAUDE_TITLE: {"claude": frozenset({"2.1.291", "2.1.292"})},
}

_LOCAL_TTL_S = 10.0
_local_cache: dict = {"key": None, "at": 0.0, "versions": frozenset()}


def _local_title_versions() -> frozenset:
    """Versions whose title check passed on this Mac, re-read when the record
    file changes and at most every few seconds otherwise."""
    from .runtime import cli_versions
    from . import config as cfg
    path = cfg.state_dir() / cli_versions.LOCAL_VERIFIED_FILE
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(path), None, None)
    now = time.monotonic()
    if key == _local_cache["key"] and now - _local_cache["at"] < _LOCAL_TTL_S:
        return _local_cache["versions"]
    versions = frozenset(cli_versions.local_title_verified_versions()) if key[1] is not None else frozenset()
    _local_cache.update(key=key, at=now, versions=versions)
    return versions


def title_verified(engine: str, version) -> bool:
    """Whether the terminal-title rung is authoritative for this engine version."""
    if not isinstance(version, str):
        return False
    if version in VERIFIED[RUNG_CLAUDE_TITLE].get(engine, ()):
        return True
    return engine == "claude" and version in _local_title_versions()

# The working spinner re-sends its title about once a second (observed 0.96 s).
SPINNER_STALE_S = 5.0
# A working title stamped up to this far in the future still counts: the
# daemon stamps it, the console reads it, and their clocks are the same
# machine's but sampled at different moments. Further ahead is not trusted.
# Together with SPINNER_STALE_S this bounds how long "working" can still show
# after the spinner stops: at most SPINNER_STALE_S + CLOCK_SKEW_S (about 7 s).
CLOCK_SKEW_S = 2.0


def display_value(session: str, activity: str, needs_input: dict) -> str:
    """The one bridge from the axes to the value the UI renders. Values that
    are not part of the taxonomy are refused, so a surface-local word can
    never leak into the display."""
    if session not in SESSION_VALUES:
        raise ValueError(f"not a session value: {session!r}")
    if activity not in ACTIVITY_VALUES:
        raise ValueError(f"not an activity value: {activity!r}")
    if session == "exited":
        return "exited"
    if needs_input.get("count", 0) > 0:
        return "needs-input"
    return activity


def _title_reading(title: dict, now: float) -> tuple[str, str]:
    """(activity value, explanation) for one claude-title evidence snapshot."""
    state = title.get("state")
    last_seen = title.get("last_seen")
    if state is None:
        return "unknown", "尚未收到 Claude 的終端標題（可能停在啟動時的信任確認畫面）"
    if state == "working":
        seen = finite_real(last_seen)
        if seen is None:
            return "unknown", "工作中的標題沒有有效的時間紀錄"
        if now is None:
            return "unknown", "主控台的現在時間無效，無法判斷"
        age = now - seen
        if age < -CLOCK_SKEW_S:
            return "unknown", "工作中的標題時間在未來（時鐘不一致），不採用"
        if age > SPINNER_STALE_S:
            return "unknown", f"工作中的標題已 {int(age)} 秒沒有更新"
        return "working", "終端標題顯示工作中的動畫"
    if state == "waiting":
        return "waiting", "終端標題顯示閒置符號 ✳：Claude 沒有在工作，正在等你輸入或確認"
    if state == "empty":
        return "unknown", "Claude 已清除終端標題（通常是正在結束）"
    return "unknown", "終端標題的格式不是已驗證的樣式"


def arbitrate(info: dict, now: float | None = None) -> dict:
    """Decide one runtime session's state from the evidence in its info.

    ``info`` is a runtime session as the daemon lists it (``exited``,
    ``closing``, ``engine``, ``managed``, ``cli_version`` and
    ``activity_evidence``). The result is the single arbitrated answer every
    surface renders from, with the rung that decided it and every piece of
    evidence considered, consulted or not."""
    # ``now`` and everything in ``info`` may come from outside; anything not
    # usable reads as unknown, never raises.
    now = finite_real(time.time() if now is None else now)
    if not isinstance(info, dict):
        info = {}
    session = "exited" if info.get("exited") else "present"
    activity, decided_by, reason = "unknown", None, ""
    evidence: list[dict] = []
    engine = info.get("engine")
    managed = bool(info.get("managed"))
    evidence_in = info.get("activity_evidence")
    title = evidence_in.get("claude_title") if isinstance(evidence_in, dict) else None

    if engine == "claude" and managed and isinstance(title, dict):
        version = info.get("cli_version")
        trust = "authoritative" if title_verified("claude", version) else "trial"
        value, note = _title_reading(title, now)
        evidence.append({"rung": RUNG_CLAUDE_TITLE, "label": RUNG_LABELS[RUNG_CLAUDE_TITLE],
                         "trust": trust, "value": value, "note": note,
                         "since": title.get("since"), "observed_at": title.get("last_seen")})
        if session == "present" and not info.get("closing"):
            if trust == "authoritative":
                if value != "unknown":
                    activity, decided_by = value, RUNG_CLAUDE_TITLE
                reason = note
            else:
                reason = (f"Claude Code {version or '（版本不明）'} 的終端標題訊號尚未驗證："
                          "只記錄、不採用（試用中）。可在啟動對話框按「驗證這個版本」")
    elif engine == "claude" and managed:
        reason = "VBear runtime 沒有回報這個 session 的狀態證據（背景程序可能是舊版，重新啟動後才會提供）"
    elif engine == "claude":
        reason = "不是 VBear 受管啟動的 Claude，無法確認版本與訊號"
    elif engine == "codex":
        reason = "Codex session 目前沒有已驗證的狀態訊號"
    else:
        reason = "不是 Agent session"

    if session == "exited":
        activity, decided_by, reason = "unknown", None, "程序已結束"
    elif info.get("closing"):
        activity, decided_by, reason = "unknown", None, "正在關閉"

    needs_input = {"count": 0, "reason": None}
    return {
        "session": session,
        "activity": activity,
        "needs_input": needs_input,
        "needs_input_evidence": None,
        "resumability": "unknown",
        "display": display_value(session, activity, needs_input),
        "decided_by": decided_by,
        "reason": reason,
        "evidence": evidence,
    }
