"""When a meeting is major and goes to the chairman (P34-4): a fixed, visible table, not a judgement by an AI.

Any one rule that holds makes the meeting major. Nothing a model writes can lower the verdict: its fields are only
read, and only to raise it (R2, R5, R6, R8). The verdict is derived on every read from the record; ``major_at_decision``,
the verdict stored when the decision was made, can only keep it major (is_major), never make it less so.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

RULES: tuple[dict[str, str], ...] = (
    {"id": "R1", "text": "董事長建立會議時勾了「涉及」的選項（發布、花錢、刪除、法律或合約、上線、個資）。"},
    {"id": "R2", "text": "CEO 的行動含對外發布、部署上線、花錢付款、刪除資料、簽約承諾或調整價格。"},
    {"id": "R3", "text": "議題、補充說明、決策或行動的文字出現發布、付款、刪除、合約、個資等關鍵字。"},
    {"id": "R4", "text": "議題、補充說明、決策或行動的文字出現金額（大於等於門檻；預設門檻 0，就是任何金額）。"},
    {"id": "R5", "text": "有發言標了高風險，或法務的出處是「查無出處，需人工複核」。"},
    {"id": "R6", "text": "法務經理的立場是反對。"},
    {"id": "R7", "text": "有發言或 CEO 決策失敗、卡住、被略過或中斷。"},
    {"id": "R8", "text": "CEO 要求交給董事長，或有發言要求交給董事長。"},
)

# what the chairman may tick when the meeting is made (id -> words on the screen)
FLAGS: dict[str, str] = {"publish": "對外發布", "spend": "花錢", "delete": "刪除資料", "legal": "法律或合約",
                         "deploy": "上線部署", "personal": "個資"}

ACTION_TYPES: tuple[str, ...] = ("撰寫程式", "修改文件", "寫草稿", "對外發布", "部署上線", "花錢付款", "刪除資料", "簽約承諾",
                                 "調整價格", "其他")
MAJOR_ACTION_TYPES = frozenset({"對外發布", "部署上線", "花錢付款", "刪除資料", "簽約承諾", "調整價格"})
SAFE_ACTION_TYPES = frozenset(ACTION_TYPES) - MAJOR_ACTION_TYPES
BAD_TURN_STATES = frozenset({"failed", "blocked", "skipped", "interrupted"})
NO_SOURCE = "查無出處，需人工複核"
AMOUNT_THRESHOLD = Decimal(0)

_ZH_KEYWORDS = ("發布", "公開", "上架", "部署", "上線", "付款", "購買", "訂閱", "匯款", "廣告費", "刪除", "清空", "合約", "簽約",
                "個資", "退款", "價格")
# English stems with their endings, so that "deploying", "released" and "paid" count and "postgres", "payload" and
# "priceless" do not
_EN_STEMS = (r"publish\w*", r"post(?:s|ed|ing)?", r"deploy\w*", r"releas\w*", r"pa(?:y|ys|id|ying|yment|yments)", r"purchas\w*",
             r"bought", r"subscri\w*", r"delet\w*", r"contract\w*", r"refund\w*", r"pric(?:e|es|ed|ing)")
KEYWORD_RE = re.compile("|".join(_ZH_KEYWORDS) + r"|\b(?:" + "|".join(_EN_STEMS) + r")\b", re.I)

_NUM = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
_MULT = r"(百萬|千萬|億|萬|千|k|m|million|billion)?"
_MULTIPLIERS = {"百萬": 10**6, "千萬": 10**7, "億": 10**8, "萬": 10**4, "千": 10**3, "k": 10**3, "m": 10**6, "million": 10**6,
                "billion": 10**9}
_UNIT = (r"(?:元|美元|美金|塊|台幣|新台幣|人民幣|日圓|歐元|越南盾|NT\$|NTD|TWD|USD|VND|EUR|JPY|CNY|RMB|dollars?|dong)")
_SYMBOL = r"(?:NT\$|US\$|NTD|TWD|USD|VND|EUR|JPY|CNY|RMB|\$|€|¥|￥)"
_AMOUNTS = (re.compile(_SYMBOL + r"\s*" + _NUM + r"\s*" + _MULT, re.I),
            re.compile(_NUM + r"\s*" + _MULT + r"\s*" + _UNIT, re.I))
# a sum written in Chinese numerals next to a unit ("三萬元") or a symbol with no digits after it: the amount cannot be
# read, so it counts as an amount of any size
_UNREADABLE = re.compile(r"[零〇一二兩三四五六七八九十百千萬億]+\s*" + _UNIT + "|" + _SYMBOL + r"\s*[零〇一二兩三四五六七八九十百千萬億]", re.I)


def _texts(meeting: dict) -> list[str]:
    """The words the keyword and amount rules read: topic, context, the decision, its rationale and its actions."""
    out = [meeting.get("topic"), meeting.get("context")]
    for turn in meeting.get("turns") or []:
        o = turn.get("output") if turn.get("kind") == "decision" and turn.get("state") == "done" else None
        if isinstance(o, dict):
            out += [o.get("decision"), o.get("rationale")]
            for action in o.get("actions") or []:
                if isinstance(action, dict):
                    out.append(action.get("text"))
    return [unicodedata.normalize("NFKC", t) for t in out if isinstance(t, str)]


def _amounts(text: str):
    """The amounts written in the text; an amount that cannot be read is yielded as infinitely large (fail closed)."""
    for pattern in _AMOUNTS:
        for m in pattern.finditer(text):
            try:
                value = Decimal(m.group(1).replace(",", ""))
            except InvalidOperation:
                yield Decimal("Infinity")
                continue
            yield value * _MULTIPLIERS.get((m.group(2) or "").lower(), 1)
    if _UNREADABLE.search(text):
        yield Decimal("Infinity")


def _outputs(meeting: dict, kind: str):
    for turn in meeting.get("turns") or []:
        if turn.get("kind") == kind and turn.get("state") == "done" and isinstance(turn.get("output"), dict):
            yield turn, turn["output"]


def _action_type(action: dict):
    kind = action.get("type")
    return unicodedata.normalize("NFKC", kind).strip() if isinstance(kind, str) else None


def _position(meeting: dict, profile_id) -> str | None:
    for p in meeting.get("participants") or []:
        if isinstance(p, dict) and p.get("profile_id") == profile_id:
            return p.get("position")
    return None


def evaluate(meeting: dict, amount_threshold: Decimal = AMOUNT_THRESHOLD) -> dict:
    """{"major": bool, "rules": [{"id", "text"}, ...]} for the rules that hold now. Reads the record, changes nothing."""
    held: set[str] = set()
    turns = meeting.get("turns")
    # a record is validated before it is stored; if one with a turn that is not a record gets here anyway, that turn is a
    # failed one (R7) rather than a crash
    meeting = {**meeting, "turns": [t if isinstance(t, dict) else {"state": "failed"} for t in turns] if isinstance(turns, list) else []}
    if meeting.get("flags_by_chairman"):
        held.add("R1")
    texts = _texts(meeting)
    if any(KEYWORD_RE.search(t) for t in texts):
        held.add("R3")
    if any(v >= amount_threshold for t in texts for v in _amounts(t)):
        held.add("R4")
    for _, out in _outputs(meeting, "decision"):
        # a type this table does not list (or that is not text) is treated as major: the check fails closed
        if any(not isinstance(a, dict) or _action_type(a) not in SAFE_ACTION_TYPES for a in out.get("actions") or []):
            held.add("R2")
        if out.get("escalate") is True:
            held.add("R8")
    for turn, out in _outputs(meeting, "opinion"):
        legal = _position(meeting, turn.get("profile_id")) == "legal"
        for risk in out.get("risks") or []:
            if isinstance(risk, dict):
                if risk.get("level") == "高":
                    held.add("R5")
                if legal and isinstance(risk.get("source"), str) and NO_SOURCE in risk["source"]:
                    held.add("R5")
        if legal and out.get("stance") == "反對":
            held.add("R6")
        if out.get("needs_chairman") is True:
            held.add("R8")
    if any(t.get("state") in BAD_TURN_STATES for t in meeting.get("turns") or []):
        held.add("R7")
    rules = [{"id": r["id"], "text": r["text"]} for r in RULES if r["id"] in held]
    return {"major": bool(rules), "rules": rules}


def is_major(meeting: dict, amount_threshold: Decimal = AMOUNT_THRESHOLD) -> bool:
    """Major by today's table, or because it was major when the decision was made: the verdict only goes up."""
    return evaluate(meeting, amount_threshold)["major"] or meeting.get("major_at_decision") is True
