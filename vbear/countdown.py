"""The countdown of a paused dispatch or group (P44-4, ADR 0010 point 6), in words.

A dispatch that stopped for the day's money (``daily_limit``) or the AI tool's plan (``plan_limit``) and a group's round that stopped for
the day's money show when they can go on: 「還有 H 小時 M 分可以繼續（MM/DD HH:MM）」, then 「可以繼續了」, and, when the AI tool did not say
when its plan is usable again, 「AI 工具沒說什麼時候恢復」 (no countdown). Any other reason has no countdown: somebody has to look first.

This is words only: it reads two numbers and a zone and writes nothing, starts nothing and decides nothing. Whether VBear itself presses
「繼續」 is ``auto_continue`` (and 「自己動手」 item 5); a group never goes on by itself.
"""

from __future__ import annotations

import datetime
import math

REASONS = ("daily_limit", "plan_limit")


def _epoch(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def stamp(ts: float, tz=None) -> str:
    """``MM/DD HH:MM`` of an instant in the zone (None: the machine's own)."""
    return datetime.datetime.fromtimestamp(ts, tz).strftime("%m/%d %H:%M")


def words(reason, until, now: float, tz=None) -> dict | None:
    """{state: counting|ready|unknown, until, text} for a pause, or None when this reason has no countdown."""
    if reason not in REASONS:
        return None
    if not _epoch(until):
        return {"state": "unknown", "until": None, "text": "AI 工具沒說什麼時候恢復"}
    when = stamp(until, tz)
    if now >= until:
        return {"state": "ready", "until": float(until), "text": f"可以繼續了（{when} 恢復）"}
    hours, minutes = divmod(max(1, math.ceil((until - now) / 60)), 60)
    left = (f"{hours} 小時 {minutes} 分" if hours and minutes else f"{hours} 小時" if hours else f"{minutes} 分")
    return {"state": "counting", "until": float(until), "text": f"還有 {left}可以繼續（{when}）"}
