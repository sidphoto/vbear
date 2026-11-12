"""Which well-known failure an AI tool's own words describe, and the plain sentence for it. Pure: no I/O, nothing kept.

Two callers use the same phrases: 「試一下」 (``vbear/setup_try.py``, the tail of the error output of a program that exited with an
error) and the Codex chat (``codex_chat_session``, the message of Codex's ``error`` notification when a turn fails). ``classify`` maps
text to one fixed word; the text itself goes no further than the caller that read it.

Only clear, general phrases. The classes are tried in the order of ``PHRASES`` and the first class that has a hit wins: the server's own
answer (a login one, then an unusable model, then a plan limit) outranks the retry noise of a connection that came before it (Codex 0.167.0
with no login prints many "failed to connect" lines and then a 401). Real samples: the empty-home Codex 0.167.0 lines (login) and OpenAI's
"The '<model>' model is not supported when using Codex with a ChatGPT account." (model). The limit and connection phrases, and every phrase
for Claude Code, AGY, Grok and MCODE, are general wording, not a sample of that tool failing.
"""
from __future__ import annotations

import re

PHRASES = (
    ("not_logged_in", re.compile(r"\b401\b[^\n]{0,40}\bunauthorized\b|\bmissing bearer\b|\bnot logged in\b|\bauthentication required\b"
                                 r"|\bplease run [^\n]{0,60}\blogin\b")),
    ("model", re.compile(r"\bmodel\b[^\n]{0,80}\bnot supported\b|\bunsupported model\b")),
    ("limit", re.compile(r"\busage limit\b|\brate[- ]limit|\b429\b|\bquota\b")),
    ("network", re.compile(r"failed to connect|(?:could not|can[’']?t|cannot|unable to) connect|could not resolve|\bdns\b"
                           r"|connection (?:refused|reset|timed out)|network is unreachable|timed out|name or service not known"
                           r"|nodename nor servname")),
)

# The sentences for a chat whose turn failed (the engine is Codex; no other chat engine has a sample yet).
CHAT_WORDS = {
    "not_logged_in": "Codex 說你還沒登入，或登入過期了。請到「AI 工具」重新登入聊天用的 Codex，再開一個新對話。",
    "model": "ChatGPT 說你的帳號現在不能用這個模型（OpenAI 有時會更換可用的模型）。開一個新對話通常就好；"
             "如果這位員工有指定模型，到員工設定把模型改回「工具預設」。",
    "limit": "Codex 說你的方案現在用量到上限了，晚一點再說一次。",
    "network": "Codex 連不上它的伺服器，可能是網路問題，稍後再說一次。",
    "failed": "Codex 這一回合失敗了，原因 VBear 看不出來。可以再說一次；如果一直這樣，開一個新對話。",
}
DETAIL_MARK = "\n技術細節："


def classify(text) -> str:
    """not_logged_in, model, limit, network or failed, from the words of a tool (a str, or bytes). The words are looked at here and nowhere else."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    if not isinstance(text, str):
        return "failed"
    low = text.lower()
    for code, rule in PHRASES:
        if rule.search(low):
            return code
    return "failed"


def chat_error_text(raw, limit: int) -> str:
    """The text of the ``error`` record of a failed chat turn: the fixed sentence of the class, then ``DETAIL_MARK`` and the original, flattened to one
    line and cut so that the whole is at most ``limit`` characters. "" when there are no words to go on (nothing is guessed)."""
    if not isinstance(raw, str):
        return ""
    flat = " ".join("".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in raw).split())
    if not flat:
        return ""
    head = CHAT_WORDS[classify(flat)] + DETAIL_MARK
    room = max(limit - len(head), 0)
    return head + (flat if len(flat) <= room else flat[:max(room - 1, 0)] + ("…" if room else ""))
