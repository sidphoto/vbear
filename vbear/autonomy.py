"""「自己動手」: what the person may let the chief of staff do without asking (ADR 0003, v0.15 P40-2).

ADR 0003 lists five items. Items 1, 2, 3 and 5 work in this version (3: P44-2, a routine starts by itself at its time; 5: P44-4, a
dispatch that stopped for a limit goes on by itself when the limit is over), and every one is off until the person turns it on in the
settings page; item 4 is in the table so that the page and the tests say what is not here yet. The stored block always has exactly four
booleans: ``create_cards``, ``dispatch``, ``routines`` (item 3) and ``auto_continue`` (item 5).

Only ``POST /api/settings/autonomy`` writes ``config.json``'s ``autonomy`` block (never ``/api/config``, never an AI-written
plan). This module only reads and checks: it writes nothing and imports nothing from the launch, skill or limit code, and
``tests/test_autonomy_guard.py`` keeps it, ``chief*.py`` and ``dispatch*.py`` that way.

Never allowed, whatever is ticked (ADR 0003): raising the daily limit, starting a worker in full mode, installing a skill
from the network. They are not items here; they are the ``NEVER`` lines the page shows.
"""

from __future__ import annotations

KEYS = ("create_cards", "dispatch", "routines", "auto_continue")  # the four booleans of the block, in the order of the page

ITEMS = (
    {"id": 1, "adr": "0003", "key": "create_cards", "active": True,
     "title": "幕僚長可以自己建新員工",
     "effect": "幕僚長提議要新員工時，VBear 不等你確認就建好（一律每件事先問我），你可以在「AI 自己做了什麼」撤回。"},
    {"id": 2, "adr": "0003", "key": "dispatch", "active": True,
     "title": "幕僚長可以自己分配工作給員工",
     "effect": "幕僚長的提議一到就開始分配工作，不再停在提議卡；員工照舊每個指令都問你。提議要新員工（而第 1 項沒勾）、"
               "VBear 拿掉了東西、或幕僚長有問題要問你時，還是會停下來等你。"},
    {"id": 3, "adr": "0003", "key": "routines", "active": True,
     "title": "定時工作到時間可以自己開始",
     "effect": "定時工作到時間時 VBear 自己開始；Mac 醒來或 VBear 打開時，12 小時內錯過的也自己補做一次（每次醒來最多 3 件）。"
               "不勾時，到時間只提醒你，由你按「現在開始」。員工要跑指令、改檔案時照舊問你；你不在電腦前時，卡片 5 分鐘沒人按就當作拒絕。"
               "定時工作不會自己建立或啟用，只有你能。"},
    {"id": 4, "adr": "0003", "key": None, "active": False,
     "title": "員工在保護範圍裡跑指令、改檔案時不必每次問",
     "effect": "還沒有；聊天照舊每個指令、每個檔案修改都問你。"},
    {"id": 5, "adr": "0003", "key": "auto_continue", "active": True,
     "title": "碰到上限暫停的工作，倒數結束後自動接續",
     "effect": "分配工作碰到花費上限或 AI 工具的方案用量上限暫停時，到了恢復時間 VBear 自己按「繼續」（每份分配工作最多 3 次，全部加起來每天最多 5 次）。"
               "被打斷的那一步不會重做，下一步會被告知上一步可能不完整。AI 工具沒說恢復時間時（Claude Code 目前都沒說）不會自己接續；群組不會自己接續。"},
)

LATER_NOTE = "第 4 項（不必每次問）會在之後的版本加入。"

NEVER = (
    "AI 不能自己調高每天的花費上限。",
    "AI 不能自己讓員工用「完全交給他（有風險）」開始工作。",
    "AI 不能自己從網路安裝新技能。",
)

# What the chief of staff's own call may cost at most (US$); the page says so before an item is turned on. The chief of staff's
# code holds the same number (vbear/chief.py CHIEF_CALL_USD); a test keeps the two equal once that module exists.
CHIEF_CALL_USD = 0.30

_OFF = {key: False for key in KEYS}


def read(conf) -> dict:
    """{create_cards, dispatch, routines, auto_continue}: each True only when config.json holds exactly ``True`` for it; anything else is False.

    A missing block, a block that is not an object, a value that is not a boolean, or a config flagged corrupt: all off. A block of
    v0.17.1 (two keys) reads the new two as off. Item 3 (a routine starts by itself) looks at ``routines`` here and nowhere else; item 5 (a dispatch goes on by itself) at ``auto_continue``.
    """
    if not isinstance(conf, dict) or conf.get("_corrupt"):
        return dict(_OFF)
    block = conf.get("autonomy")
    if not isinstance(block, dict):
        return dict(_OFF)
    return {key: block.get(key) is True for key in KEYS}


def validate(body) -> dict:
    """The block to store for a request: exactly the four booleans, nothing more, nothing less. Raises ValueError (zh-TW)."""
    if not isinstance(body, dict) or set(body) != set(KEYS):
        raise ValueError("請求只能有 create_cards、dispatch、routines 與 auto_continue 四個欄位，值是 true 或 false")
    if any(type(body[key]) is not bool for key in KEYS):
        raise ValueError("create_cards、dispatch、routines 與 auto_continue 必須是 true 或 false")
    return {key: body[key] for key in KEYS}
