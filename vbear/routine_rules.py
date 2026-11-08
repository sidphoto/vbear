"""The pure rules of a routine (例行工作, P44-2, ADR 0010 points 3, 4 and 5): what a routine is, the times it is due, the daily limit of
routines, and the fixed words VBear puts in front of the person's own text.

No file, no clock of the machine, no process: every function is given what it needs (the zone, the instants), so a test can say any
day and any zone. ``vbear/routines.py`` keeps the records, ``vbear/routine_runner.py`` is the thread that acts on them.

A routine is one employee, one text, some days of the week and one to three times of day. Everything is in the machine's **local time**
(``tz=None`` means the system zone; a ``zoneinfo`` zone can be given). A *slot* is one day and one time of one routine, named by the
local minute ("2026-11-09T08:00"). A routine does at most one run for a slot (the records enforce it), whatever the clock does:

  * a time a clock skips (the spring hour) is done at the next minute that exists; its slot key stays the time that was asked for;
  * a time a clock repeats (the autumn hour) is one slot, due at its first occurrence;
  * a clock set back makes no slot due again: the key is the same.

The money rule is here too: routines have their own daily limit (``ROUTINE_DAILY_FRACTION`` of the day's limit unless the person has set
one, never above the day's limit), because they run when the person is not at the computer.
"""

from __future__ import annotations

import datetime
import json
import math
import re
from decimal import Decimal, ROUND_DOWN

from .runtime import memory_rules

NAME_MAX = 40
TEXT_MAX = 4000
MAX_ROUTINES = 20
MAX_ENABLED = 10
MAX_TIMES = 3
MIN_GAP_MIN = 60                      # times of one routine are at least this far apart (around the clock)

ROUTINE_DAILY_FRACTION = Decimal("0.5")   # the default daily limit of routines, as a part of the day's limit (the person may change it)
ON_TIME_S = 120.0                     # a slot is "on time" for this long after it is due; later it is a late one
WAITING_FOR_S = 12 * 3600.0           # a reminder nobody pressed is put away after this long (or at the routine's next time)
BUSY_RETRY_S = 30.0                   # an employee who is busy (or a room that is full) is asked again this often ...
BUSY_FOR_S = 12 * 60.0                # ... for this long, then the run is skipped
WAKE_GAP_S = 90.0                     # two looks further apart than this: the Mac slept, or VBear was closed (P44-3)
BEAT_S = 60.0                         # the heartbeat file is written this often
LOOK_BACK_S = 7 * 86400.0             # a wake-up counts the missed times of at most this many days back
CATCH_UP_AUTO_S = 12 * 3600.0         # item 3 catches up by itself only when the latest missed time is younger than this ...
CATCH_UP_AUTO_MAX = 3                 # ... and only this many routines per wake-up
CATCH_UP_LISTED_S = 24 * 3600.0       # a missed time nobody answered is put away after this long (or at the routine's next time)
ASLEEP = "asleep_"                    # the reason of a listed missed time is ``asleep_<count>``
PER_RUN_NOTE = "到時間時 VBear 會提醒你，你按「現在開始」才會做。"

MARK_BEGIN, MARK_END = "BEGIN_UNTRUSTED_JSON_STRING", "END_UNTRUSTED_JSON_STRING"
FIXED_LINE = ("（這是用的人排定的例行工作，名稱與排定時間在下面的 JSON 字串裡。用的人可能不在電腦前："
              "要跑指令或改檔案時照舊會問他，沒有回覆會當作拒絕。）")

PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)\Z")
SLOT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):([0-5]\d)\Z")
FIELDS = ("name", "profile_id", "text", "days", "times", "enabled")


# ---- the fields -------------------------------------------------------------------------------------------------------------

def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def minutes_of(clock_time) -> int | None:
    found = TIME_RE.match(clock_time) if isinstance(clock_time, str) else None
    return int(found.group(1)) * 60 + int(found.group(2)) if found else None


def _name(value) -> str:
    if not isinstance(value, str):
        raise ValueError("name 必須是文字")
    value = value.strip()
    if not 1 <= len(value) <= NAME_MAX or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"名稱要 1 到 {NAME_MAX} 個字，而且只能一行")
    return value


def _text(value) -> str:
    if not isinstance(value, str):
        raise ValueError("text 必須是文字")
    value = value.strip()
    if not 1 <= len(value) <= TEXT_MAX:
        raise ValueError(f"內容要 1 到 {TEXT_MAX:,} 個字")
    return value


def _days(value) -> list:
    if not (isinstance(value, list) and value and all(_is_int(d) and 0 <= d <= 6 for d in value) and len(set(value)) == len(value)):
        raise ValueError("days 要是 0 到 6 的整數（星期一是 0），至少一天，不能重複")
    return sorted(value)


def _times(value) -> list:
    if not (isinstance(value, list) and 1 <= len(value) <= MAX_TIMES and all(minutes_of(t) is not None for t in value)
            and len(set(value)) == len(value)):
        raise ValueError(f"times 要是 1 到 {MAX_TIMES} 個 HH:MM，不能重複")
    value = sorted(value)
    mins = [minutes_of(t) for t in value]
    for i, a in enumerate(mins):
        for b in mins[i + 1:]:
            if min(abs(a - b), 1440 - abs(a - b)) < MIN_GAP_MIN:
                raise ValueError(f"同一件例行工作的時間要彼此至少差 {MIN_GAP_MIN} 分鐘")
    return value


def _profile(value) -> str:
    if not (isinstance(value, str) and PROFILE_RE.match(value)):
        raise ValueError("profile_id 必須是員工的識別碼")
    return value


def _enabled(value) -> bool:
    if not isinstance(value, bool):
        raise ValueError("enabled 必須是 true 或 false")
    return value


_CHECKS = {"name": _name, "profile_id": _profile, "text": _text, "days": _days, "times": _times, "enabled": _enabled}


def validate_fields(body, *, full: bool) -> dict:
    """The fields of a request, checked and tidied (days and times sorted, text trimmed). ``full``: exactly the six fields (a new
    routine); otherwise at least one of them. ``confirm_warning`` (a boolean) may come beside them and is not returned. ValueError (zh)."""
    if not isinstance(body, dict):
        raise ValueError("請求內容必須是一個 JSON 物件")
    extra = set(body) - set(FIELDS) - {"confirm_warning"}
    if extra:
        raise ValueError("只接受 " + "、".join(FIELDS) + " 與 confirm_warning")
    if "confirm_warning" in body and not isinstance(body["confirm_warning"], bool):
        raise ValueError("confirm_warning 必須是 true 或 false")
    present = [k for k in FIELDS if k in body]
    if full and len(present) != len(FIELDS):
        raise ValueError("新增例行工作需要 " + "、".join(FIELDS))
    if not present:
        raise ValueError("要改至少一個欄位：" + "、".join(FIELDS))
    return {k: _CHECKS[k](body[k]) for k in present}


# ---- what the text may say ---------------------------------------------------------------------------------------------------

def check_content(text) -> dict:
    """``{"refuse": code | None, "warn": [code, ...]}`` for a routine's name or text: the memory's rules (vbear/runtime/memory_rules.py),
    the same ones a skill is held to. A text may have lines and be long; ``memory_rules.check_text`` does that when it is there, and
    until then the text is read in overlapping pieces of the length ``check`` accepts, so that nothing a rule would catch falls between
    two of them."""
    check_text = getattr(memory_rules, "check_text", None)
    if check_text is not None:
        return check_text(text, TEXT_MAX)
    flat = " ".join(str(text).split())
    refuse, warn = None, []
    step, width = 100, memory_rules.MAX_TEXT
    for start in range(0, max(len(flat) - step, 0) + 1, step):
        piece = flat[start:start + width].strip()
        if not piece:
            continue
        got = memory_rules.check(piece)
        refuse = refuse or got["refuse"]
        warn += [w for w in got["warn"] if w not in warn]
    return {"refuse": refuse, "warn": warn}


# ---- the times ---------------------------------------------------------------------------------------------------------------

def slot_key(local: datetime.datetime) -> str:
    return local.strftime("%Y-%m-%dT%H:%M")


def title_time(slot: str) -> str:
    found = SLOT_RE.match(slot) if isinstance(slot, str) else None
    return f"{found.group(2)}/{found.group(3)} {found.group(4)}:{found.group(5)}" if found else "?"


def _local(ts: float, tz) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ts, tz).replace(tzinfo=None)


def _ts(local: datetime.datetime, tz) -> float:
    return (local.replace(tzinfo=tz) if tz is not None else local).timestamp()


def _due(local: datetime.datetime, tz) -> float:
    """The instant a local minute is due: its first occurrence; when the clock skips it, the next minute that exists."""
    at = _ts(local, tz)
    if _local(at, tz) == local:
        return at
    probe = local
    for _ in range(24 * 60):
        probe += datetime.timedelta(minutes=1)
        at = _ts(probe, tz)
        if _local(at, tz) == probe:
            return at
    return _ts(local, tz)                                      # not reached for any real zone


def slot_due(slot, tz) -> float | None:
    """The instant a slot key is due, or None for a text that is not a slot key."""
    found = SLOT_RE.match(slot) if isinstance(slot, str) else None
    if not found:
        return None
    try:
        local = datetime.datetime(*(int(g) for g in found.groups()))
    except ValueError:
        return None
    return _due(local, tz)


def slots_between(routine: dict, start: float, end: float, tz) -> list:
    """``[(slot key, due instant)]`` of the routine whose instant is after ``start`` and not after ``end``, earliest first."""
    if not end > start:
        return []
    first = _local(start, tz).date() - datetime.timedelta(days=1)
    last = _local(end, tz).date() + datetime.timedelta(days=1)
    out, day = [], first
    while day <= last:
        if day.weekday() in routine["days"]:
            for clock_time in routine["times"]:
                mins = minutes_of(clock_time)
                local = datetime.datetime.combine(day, datetime.time(mins // 60, mins % 60))
                due = _due(local, tz)
                if start < due <= end:
                    out.append((slot_key(local), due))
        day += datetime.timedelta(days=1)
    return sorted(out, key=lambda item: (item[1], item[0]))


def next_due(routine: dict, now: float, tz):
    """``(slot key, instant)`` of the first slot after ``now`` (looked for in the next nine days), or None."""
    found = slots_between(routine, now, now + 9 * 86400, tz)
    return found[0] if found else None


# ---- the money ----------------------------------------------------------------------------------------------------------------

CENT = Decimal("0.01")


def default_daily_usd(daily: Decimal) -> Decimal:
    """The routines' daily limit when the person has not set one: ``ROUTINE_DAILY_FRACTION`` of the day's limit, in whole cents, at
    least one cent."""
    return max((Decimal(daily) * ROUTINE_DAILY_FRACTION).quantize(CENT, rounding=ROUND_DOWN), CENT)


def effective_daily_usd(setting, daily: Decimal) -> Decimal:
    """The limit in force: the person's setting (None: the default), never above the day's limit (which may have been lowered since)."""
    if setting is None:
        return default_daily_usd(daily)
    return min(Decimal(str(setting)), Decimal(daily))


def check_daily_usd(value, daily: Decimal) -> float:
    """A setting the person sends: a number from one cent to the day's limit. ValueError (zh) otherwise."""
    bad = ValueError(f"例行工作每天上限必須是 0.01 到每天上限（US${Decimal(daily):f}）之間的數字")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        raise bad
    amount = Decimal(str(value))
    if amount < CENT or amount > Decimal(daily):
        raise bad
    return float(value)


# ---- the words ----------------------------------------------------------------------------------------------------------------

def message_text(name: str, slot: str, text: str) -> str:
    """What a run sends: VBear's fixed line (the routine was set by the person, who may be away; every command and file change still
    asks him, and no reply is a no), then the routine's name and slot as one JSON string between the untrusted markers (the escaping
    keeps a name from ending the string or starting a line), a blank line, and the person's own text, outside the markers."""
    data = json.dumps(json.dumps({"name": name, "slot": slot}, ensure_ascii=False), ensure_ascii=False)
    return f"{FIXED_LINE}\n{MARK_BEGIN}\n{data}\n{MARK_END}\n\n{text}"


def chat_title(name, slot: str) -> str:
    return f"例行工作：{name if isinstance(name, str) and name else '（已刪除的例行工作）'} {title_time(slot)}"
