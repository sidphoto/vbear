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

RISK_TEXT_VERSION = "2026-10-08.1"

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
    if set(fields) != FIELDS:
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
    return limits_problem(fields["limits"])


def acceptance_fields(event: dict) -> dict:
    return {k: event.get(k) for k in FIELDS}


def is_valid_now(event, key_id: str | None) -> bool:
    """Well formed, for the current risk text, and bound to the current key.
    With no usable key (``key_id`` None) nothing is valid."""
    if not isinstance(event, dict) or event.get("kind") != "risk_acknowledged":
        return False
    fields = acceptance_fields(event)
    return (record_problem(fields) is None and fields["text_version"] == RISK_TEXT_VERSION
            and isinstance(key_id, str) and fields["login_key_id"] == key_id)


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
