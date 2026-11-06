"""「自己動手」: what the person may let the chief of staff do without asking (ADR 0003, v0.15 P40-2).

ADR 0003 lists five items. Only the first two work in this version, and both are off until the person turns them on in the
settings page; the other three are in the table so that the page and the tests say what is not here yet.

Only ``POST /api/settings/autonomy`` writes ``config.json``'s ``autonomy`` block (never ``/api/config``, never an AI-written
plan). This module only reads and checks: it writes nothing and imports nothing from the launch, skill or limit code, and
``tests/test_autonomy_guard.py`` keeps it, ``chief*.py`` and ``dispatch*.py`` that way.

Never allowed, whatever is ticked (ADR 0003): raising the daily limit, starting a worker in full mode, installing a skill
from the network. They are not items here; they are the ``NEVER`` lines the page shows.
"""

from __future__ import annotations

KEYS = ("create_cards", "dispatch")  # the two items that work in this version, in the order of the page

ITEMS = (
    {"id": 1, "adr": "0003", "key": "create_cards", "active": True,
     "title": "幕僚長可以自己建新員工",
     "effect": "幕僚長提議要新員工時，VBear 不等你確認就建好（一律安全模式），你可以在「AI 自己做了什麼」撤回。"},
    {"id": 2, "adr": "0003", "key": "dispatch", "active": True,
     "title": "幕僚長可以自己派工給員工",
     "effect": "幕僚長的提議一到就開始派工，不再停在提議卡；員工照舊每個指令都問你。提議要新員工（而第 1 項沒勾）、"
               "VBear 拿掉了東西、或幕僚長有問題要問你時，還是會停下來等你。"},
    {"id": 3, "adr": "0003", "key": None, "active": False,
     "title": "例行工作可以自己啟用、定時執行",
     "effect": "跟著例行工作一起在之後的版本加入。"},
    {"id": 4, "adr": "0003", "key": None, "active": False,
     "title": "員工在安全模式裡跑指令、改檔案時不必每次問",
     "effect": "還沒有；聊天照舊每個指令、每個檔案修改都問你。"},
    {"id": 5, "adr": "0003", "key": None, "active": False,
     "title": "碰到上限暫停的工作，倒數結束後自動接續",
     "effect": "跟著例行工作一起在之後的版本加入；現在暫停後由你按「繼續」。"},
)

LATER_NOTE = "例行工作、不必每次問、倒數後自動接續這三項會在之後的版本加入。"

NEVER = (
    "AI 不能自己調高每天的花費上限。",
    "AI 不能自己讓員工用完整模式出發。",
    "AI 不能自己從網路安裝新技能。",
)

# What the chief of staff's own call may cost at most (US$); the page says so before an item is turned on. The chief of staff's
# code holds the same number (vbear/chief.py CHIEF_CALL_USD); a test keeps the two equal once that module exists.
CHIEF_CALL_USD = 0.30

_OFF = {key: False for key in KEYS}


def read(conf) -> dict:
    """{create_cards, dispatch}: each True only when config.json holds exactly ``True`` for it; anything else is False.

    A missing block, a block that is not an object, a value that is not a boolean, or a config flagged corrupt: all off.
    """
    if not isinstance(conf, dict) or conf.get("_corrupt"):
        return dict(_OFF)
    block = conf.get("autonomy")
    if not isinstance(block, dict):
        return dict(_OFF)
    return {key: block.get(key) is True for key in KEYS}


def validate(body) -> dict:
    """The block to store for a request: exactly the two booleans, nothing more, nothing less. Raises ValueError (zh-TW)."""
    if not isinstance(body, dict) or set(body) != set(KEYS):
        raise ValueError("請求只能有 create_cards 與 dispatch 兩個欄位，值是 true 或 false")
    if any(type(body[key]) is not bool for key in KEYS):
        raise ValueError("create_cards 與 dispatch 必須是 true 或 false")
    return {key: body[key] for key in KEYS}
