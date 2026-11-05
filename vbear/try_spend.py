"""What the start-up page's 「試一下」 spent, kept for the day's limit.

One small file in the state folder, ``setup-try.json``: one entry per try, {tool, state, started_at, ended_at, cap_usd,
evidence: {cost_usd}}. Nothing else: no reply, no argv, no account or session information. The entries are turns in the shape
``meetings.daily_spent`` counts, so the meetings, the staffing meetings and the chats see the same day (``spend_kind``, used
by the board engine's kinds and by the daemon's check for a chat). A try that has started and not ended counts at its cap;
a record that cannot be read stops anything new that costs money, as for the chats (``spend_unknown``).
"""

from __future__ import annotations

import secrets
import time
from decimal import Decimal

from . import meetings as mt
from .jsonstore import GuardedJsonStore, StoreError

KIND_ID = "try"
KEEP_S = 3 * 86400                 # a try older than this can no longer count toward any day's limit
MAX_ENTRIES = 500
STATES = ("running", "done", "failed")


def _finite_time(value) -> bool:
    return isinstance(value, float) and value == value and value not in (float("inf"), float("-inf"))


def _problem(key, value):
    if not isinstance(key, str) or not key.startswith("t-") or len(key) > 40:
        return "不是試一下的編號"
    if not isinstance(value, dict) or not {"tool", "state", "started_at", "cap_usd"} <= set(value) \
            or set(value) - {"tool", "state", "started_at", "ended_at", "cap_usd", "evidence"}:
        return "欄位不符"
    if not (isinstance(value["tool"], str) and value["state"] in STATES and _finite_time(value["started_at"])):
        return "工具、狀態或時間不符"
    if "ended_at" in value and not _finite_time(value["ended_at"]):
        return "結束時間不符"
    if mt.money(value["cap_usd"]) is None:
        return "上限金額不符"
    if "evidence" in value and not (isinstance(value["evidence"], dict) and set(value["evidence"]) == {"cost_usd"}
                                    and mt.money(value["evidence"]["cost_usd"]) is not None):
        return "花費不符"
    return None


store = GuardedJsonStore("setup-try.json", "試一下的花費紀錄", _problem)


def start(tool_id: str, now: float, cap: Decimal = Decimal("0.01")) -> str:
    """Book a try that is about to start, at its cap, and drop what is too old to count. -> its id. StoreError when the
    record cannot be used."""
    with store.locked():
        data = store.load()
        for key in [k for k, v in data.items() if (v.get("ended_at") or v["started_at"]) < now - KEEP_S]:
            del data[key]
        if len(data) >= MAX_ENTRIES:
            raise StoreError("試一下的花費紀錄太多筆，先不再記")
        key = "t-" + secrets.token_hex(8)
        data[key] = {"tool": tool_id, "state": "running", "started_at": float(now), "cap_usd": mt.fmt(cap)}
        store.save(data)
    return key


def finish(key: str, state: str, cost: Decimal, now: float) -> None:
    """Close a try with what it cost (its cap when the tool reported nothing)."""
    with store.locked():
        data = store.load()
        entry = data.get(key)
        if entry is None:
            raise StoreError("找不到這次試一下的紀錄")
        entry.update(state=state, ended_at=float(now), evidence={"cost_usd": mt.fmt(cost)})
        store.save(data)


def record(_rid=None) -> dict:
    """The tries as one record meetings.daily_spent can count. StoreError when they cannot be read."""
    return {"turns": sorted(store.load().values(), key=lambda t: t["started_at"])}


def turn_cap(_record: dict, turn: dict) -> Decimal:
    return mt.money(turn.get("cap_usd")) or Decimal(0)


def spend_kind():
    """(ids, load, per_call) for the kinds that share the day's limit (board_engine.spend_kinds). What cannot be read raises
    MeetingError("spend_unknown"): the day is then unknown and nothing new that costs money starts."""

    def unknown(exc):
        return mt.MeetingError(mt.SPEND_UNKNOWN, f"試一下的花費讀不出來（{exc}）")

    def ids():
        try:
            return [KIND_ID] if store.load() else []       # no tries kept: no record, as for no chats
        except StoreError as exc:
            raise unknown(exc) from None

    def load(_rid):
        try:
            return record()
        except StoreError as exc:
            raise unknown(exc) from None

    return ids, load, turn_cap
