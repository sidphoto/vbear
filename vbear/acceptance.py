"""Risk acceptance records (design 10) and the flow limits they carry (6).

A ``risk_acknowledged`` flow event is what lets a flow run a stream executor
and, later, VBear-launched reviews (planner decisions 2026-10-08, S2a-2 Q1/Q3/
Q4). The console writes it from a server-held preview (S2c); this module is
the one validator both the console and the daemon use, and it decides:

  * whether a stored event is well formed: exactly the nine design-10 fields,
    each of the right type and range, ``limits`` field by field;
  * whether it is valid now: well formed, written for the current risk text,
    and bound to the current HMAC key (``login_key_id``);
  * how many valid acceptances there are, which is what decides whether a new
    HMAC key may be created (login_identity.create_login_key): a key that is
    missing or damaged leaves every earlier acceptance void, because none of
    their key ids can match.

Limits are re-read and re-validated against the hard caps every time they
are used; a record that fails is not an acceptance.
"""

from __future__ import annotations

import math
import re

from .numbers import finite_real

RISK_TEXT_VERSION = "2026-10-11.1"      # v29.11: Codex 0.160.0 cannot turn multi-agent off (design 10, item 1)

# name -> (default, hard cap). Design 6; integers unless noted.
LIMITS = {
    "max_reviews": (6, 10),
    "max_dispatches": (20, 40),
    "review_max_responses": (300, 600),
    "executor_turn_max_responses": (200, 400),
    "executor_total_max_responses": (1000, 2000),
    "review_timeout_min": (45, 90),
    "executor_turn_timeout_min": (60, 180),
    "max_elapsed_h": (8, 24),
    "executor_budget_usd": (20.0, 100.0),          # finite, positive, at most two decimals
}
DEFAULT_LIMITS = {k: v[0] for k, v in LIMITS.items()}

FIELDS = frozenset({"text_version", "codex_version", "model", "executor_claude_version", "executor_model",
                    "executor_login_fingerprint", "login_fingerprint", "login_key_id", "limits"})

# Phase 3 (S3 design 9, v11.1 G1): the acceptance that also approves the plan and turns automation on. Four more
# fields, all there or none. The first version of the automation text is 2026-10-11.1 (it differs from v11's draft
# because ".git is writable" is part of it, v11.1 G3).
AUTO_RISK_TEXT_VERSION = "2026-10-11.1"
AUTO_SCOPE = ["dispatch", "review", "forward_review_opinion"]       # dispatch, start reviews, forward review comments
AUTO_FIELDS = frozenset({"auto_text_version", "automation_scope", "plan_sha256", "plan_bytes"})
PLAN_MAX_BYTES = 32 << 10                                           # plan.txt
AUTO_APPROVAL_RE = re.compile(r"^auto-([1-9][0-9]{0,8})\Z")

_VERSION = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}\Z")
_TEXT_VERSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]{1,4}\Z")
_HMAC = re.compile(r"^[0-9a-f]{64}\Z")
_KEY_ID = re.compile(r"^[0-9a-f]{16}\Z")
# A full Claude model id, never an alias ("haiku", "opus"): the executor is
# launched with exactly this id and every turn's init must report it.
CLAUDE_MODEL_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.-]{0,62}\Z")
_OPENAI_MODEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\Z")


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def limits_problem(limits) -> str | None:
    """None when ``limits`` has exactly the nine fields, each within 1..cap
    (the budget: finite, > 0, <= cap, at most two decimals)."""
    if not isinstance(limits, dict):
        return "limits 不是物件"
    if set(limits) != set(LIMITS):
        return "limits 的欄位不符"
    for name, (_, cap) in LIMITS.items():
        value = limits[name]
        if name == "executor_budget_usd":
            if isinstance(value, bool):
                return f"{name} 不合法"
            amount = finite_real(value)
            if amount is None or not 0 < amount <= cap:
                return f"{name} 不合法"
            if not math.isclose(round(amount, 2), amount, rel_tol=0.0, abs_tol=1e-9):
                return f"{name} 最多兩位小數"
        elif not _int_in(value, 1, cap):
            return f"{name} 必須是 1–{cap} 的整數"
    return None


def record_problem(fields) -> str | None:
    """None when ``fields`` (the event without its seq/at/kind/source/note)
    is a well-formed acceptance."""
    if not isinstance(fields, dict):
        return "不是物件"
    keys = set(fields)
    if keys != FIELDS and keys != FIELDS | AUTO_FIELDS:       # the auto fields are all there or all absent
        return "欄位不符"
    checks = (
        ("text_version", _TEXT_VERSION), ("codex_version", _VERSION), ("model", _OPENAI_MODEL),
        ("executor_claude_version", _VERSION), ("executor_model", CLAUDE_MODEL_RE),
        ("executor_login_fingerprint", _HMAC), ("login_fingerprint", _HMAC), ("login_key_id", _KEY_ID),
    )
    for name, pattern in checks:
        value = fields.get(name)
        if not (isinstance(value, str) and pattern.match(value)):
            return f"{name} 格式不符"
    problem = limits_problem(fields["limits"])
    if problem:
        return problem
    if AUTO_FIELDS <= keys:
        return auto_problem(fields)
    return None


def auto_problem(fields: dict) -> str | None:
    """The four automation fields: the text version is a well-formed version
    string (whether it is the current one is is_auto_valid_now's question),
    the scope is exactly the fixed list, the plan hash is sha256 hex and its
    size is 1..PLAN_MAX_BYTES."""
    if not (isinstance(fields.get("auto_text_version"), str) and _TEXT_VERSION.match(fields["auto_text_version"])):
        return "auto_text_version 格式不符"
    if fields.get("automation_scope") != AUTO_SCOPE:
        return "automation_scope 不是固定值"
    if not (isinstance(fields.get("plan_sha256"), str) and _HMAC.match(fields["plan_sha256"])):
        return "plan_sha256 格式不符"
    if not _int_in(fields.get("plan_bytes"), 1, PLAN_MAX_BYTES):
        return f"plan_bytes 必須是 1–{PLAN_MAX_BYTES}"
    return None


def acceptance_fields(event: dict) -> dict:
    """The event's acceptance fields: the nine, and the automation four when
    the event carries any of them."""
    names = FIELDS | (AUTO_FIELDS if any(k in event for k in AUTO_FIELDS) else frozenset())
    return {k: event.get(k) for k in names}


def is_auto_event(event) -> bool:
    return isinstance(event, dict) and any(k in event for k in AUTO_FIELDS)


def approval_id(event: dict) -> str:
    """The approval id the automation uses for this acceptance event."""
    return f"auto-{event['seq']}"


def approval_seq(approval: str) -> int | None:
    m = AUTO_APPROVAL_RE.match(approval) if isinstance(approval, str) else None
    return int(m.group(1)) if m else None


def is_valid_now(event, key_id: str | None) -> bool:
    """Well formed, for the current risk text, and bound to the current key.
    With no usable key (``key_id`` None) nothing is valid."""
    if not isinstance(event, dict) or event.get("kind") != "risk_acknowledged":
        return False
    fields = acceptance_fields(event)
    return (record_problem(fields) is None and fields["text_version"] == RISK_TEXT_VERSION
            and isinstance(key_id, str) and fields["login_key_id"] == key_id)


def is_auto_valid_now(event, key_id: str | None) -> bool:
    """An acceptance that is valid now and carries the current automation
    text: all four fields, the text version equal to AUTO_RISK_TEXT_VERSION."""
    return (is_valid_now(event, key_id) and AUTO_FIELDS <= set(event)
            and event.get("auto_text_version") == AUTO_RISK_TEXT_VERSION
            and auto_problem(event) is None)


def latest_valid(flow: dict, key_id: str | None) -> dict | None:
    """The newest acceptance of ``flow`` that is valid now, or None."""
    events = flow.get("events") if isinstance(flow, dict) else None
    if not isinstance(events, list):
        return None
    for event in reversed(events):
        if is_valid_now(event, key_id):
            return event
    return None


def count_valid(flows: dict, key_id: str | None) -> int:
    """Valid acceptances over all flows: what create_login_key needs."""
    if not isinstance(flows, dict):
        return 0
    return sum(1 for flow in flows.values() if isinstance(flow, dict)
               for event in (flow.get("events") or ()) if is_valid_now(event, key_id))
