"""The daily limit and the limits that must stay under it (v0.12 task 5).

Four families of limits live in config.json and each has its own rule on write: the meetings' (a call <= a meeting <= the
day), the staffing records' (the CEO's call <= the record <= the day), and a chat turn (<= the day). When the day goes down,
the others that are above it are brought down to it, so that every rule still holds; nothing is ever brought up.
This module only works out the values; the server validates them with the rules of each family and writes them in one go.
"""

from __future__ import annotations

from decimal import Decimal

from . import meetings as mt
from . import staffing as st
from .runtime import chat_store as cs

CHOICES = (1, 3, 10)          # what the start-up page offers (US$); the default is the meetings' DEFAULT_LIMITS daily_usd
DAILY_MIN = Decimal("0.01")   # a chat turn's smallest limit: a day under it would leave no turn that fits


def accepted(raw) -> Decimal | None:
    """The new daily limit of a request, or None: a number (not a bool or text) from DAILY_MIN to the meetings' cap."""
    value = None if isinstance(raw, (str, bool)) else mt.money(raw)
    if value is None or not DAILY_MIN <= value <= mt.LIMIT_CAPS["daily_usd"]:
        return None
    return value


def below_the_day(conf: dict, daily: Decimal, *, meeting: bool = True, skip: frozenset | set = frozenset()) -> tuple[dict, list]:
    """(writes, changed) for a daily limit of ``daily``: the config keys to write and the limits brought down.

    ``meeting``: also write ``meeting_limits`` (the day with the call and meeting limits under it); False leaves that block to
    the caller. ``skip``: config keys the caller writes itself. ``changed`` lists {limit, from, to} of each limit that was
    above the day.
    """
    writes: dict = {}
    changed: list = []

    def lower(name: str, old: Decimal, new: Decimal) -> None:
        if new != old:
            changed.append({"limit": name, "from": float(old), "to": float(new)})

    m = mt.limits_from(conf)
    if meeting and "meeting_limits" not in skip:
        meeting_usd = min(m["meeting_usd"], daily)
        per_call = min(m["per_call_usd"], meeting_usd)
        lower("meeting_usd", m["meeting_usd"], meeting_usd)
        lower("per_call_usd", m["per_call_usd"], per_call)
        writes["meeting_limits"] = {"per_call_usd": float(per_call), "meeting_usd": float(meeting_usd), "daily_usd": float(daily)}
    s = st.limits_from(conf)
    if s["total_usd"] > daily and "staffing_limits" not in skip:
        proposal = min(s["proposal_call_usd"], daily)
        lower("staffing_total_usd", s["total_usd"], daily)
        lower("staffing_proposal_call_usd", s["proposal_call_usd"], proposal)
        writes["staffing_limits"] = {"proposal_call_usd": float(proposal), "total_usd": float(daily)}
    c = cs.limits_from(conf)
    if c["per_turn_usd"] > daily and "chat_limits" not in skip:
        lower("chat_per_turn_usd", c["per_turn_usd"], daily)
        writes["chat_limits"] = {"per_turn_usd": float(daily)}
    return writes, changed
