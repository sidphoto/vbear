"""Running a memory suggestion (P42-4): the preview, the one call, and what this feature gives the engine of the meetings.

The call is held by the engine (board_engine.HeadlessBoard) exactly as the chief of staff's is (chief_runner): one headless Claude
Code call with no tools, the check of its init event, the one worker shared with the meetings, the staffing meetings and the chief
of staff (so that they never run at the same time), the money and what a restart leaves are described there. What is this
feature's own:

  * a board of one turn, with no retry: another press of the button is a new suggestion (and a new preview, with its own cap);
  * VBear chose the model, the thinking and the limits (``sonnet``, low, at most CALL_USD = US$0.10, or what the day has left when
    that is less; 120 seconds); the person's config sets none of them and an answer sets none;
  * only a one-to-one chat may ask (a chat a group opened is refused: a group has 「記住」 on each line and nothing more). What is
    read of the chat is the preview's: counts and sizes, never a word of it; the start reads the chat and the lines of memory again
    and goes on only when both are what was previewed;
  * the suggestions share the day with the meetings, the staffing meetings, the chats, the tries and the chief of staff
    (memory_suggest.spend_kind is in each of their lists, and in the chat daemon's count of the day);
  * what the person does with an answer (the lines they saved, 「不用了」) is written on the suggestion's record, and only there.

Nothing here writes memory.json, config.json or a role card, starts a terminal, installs a skill or answers a question of a chat:
a suggestion is saved only by the person's own press, through the browser's ``POST /api/memory`` (vbear/server.py), line by line.
Nothing but the memory/suggest/ folder (and the worker's lock) is written.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Callable

from . import chief, config as cfg, memory_suggest as ms, meetings as mt, skillbook_suggest, staffing as st, try_spend
from .board_engine import HeadlessBoard
from .jsonstore import StoreError
from .meeting_runner import COST_NOTE
from .runtime import chat_store as cs

CENT = Decimal("0.01")
DISCLOSURE = ("開始後，你和這位員工最近的對話（最多 20 則、12 KiB）與你目前的記憶，會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。"
              "VBear 不會把任何文字送到其他地方。每次呼叫前，VBear 都會確認這個版本的 Claude Code 沒有任何工具、沒有 MCP；確認不了就不送。")
CODEX_NOTICE = "這是和 Codex 員工的對話，也會送給 Anthropic（Claude Code）整理。"
SAVE_NOTE = "整理只是提議：每一條都不會自己存，你勾選、可以改字，按「存進記憶」才會存。"


@dataclass
class SuggestSources:
    """Where a request reads from (the server passes the stores; tests pass dicts): a chat as (its chat.json, its records), whether a
    chat belongs to a group, and the texts of the memory the person already has (None when memory cannot be read)."""
    chat: Callable[[str], tuple]
    in_group: Callable[[str], bool]
    memory: Callable[[], list | None]
    conf: dict = field(default_factory=dict)


@dataclass
class Context:
    """Everything the one prompt is made from; for a new suggestion it is what the preview counted."""
    chat_id: str
    engine: str
    read: dict
    memory_lines: list
    inputs_sha: str
    limits: dict
    daily_usd: Decimal
    version: str
    binary: str
    expected_sha: dict = field(default_factory=dict)
    speed: dict = field(default_factory=lambda: dict(ms.SPEED))

    def who(self, profile_id: str) -> dict:
        return ms.participant()


def chat_reader(base=None) -> Callable[[str], tuple]:
    """A reader of chats for SuggestSources: (chat.json, records) of a chat in the state folder (or ``base``). A chat that is missing
    is not_found; one that does not read whole to its end is refused (storage), since the end of it is what matters."""
    def read(chat_id):
        if not isinstance(chat_id, str) or not chief.CHAT_ID_RE.match(chat_id):
            raise ms.SuggestError("bad_request", "chat_id 不符格式")
        root = Path(base) if base is not None else cfg.state_dir()
        try:
            chat = cs.load(root, chat_id)
            events = cs.read_events(root, chat_id)
        except cs.ChatStoreError as exc:
            if exc.code == "not_found":
                raise ms.SuggestError("not_found", "找不到這個聊天") from None
            raise ms.SuggestError("storage", "這個聊天的紀錄讀不出來，不整理它") from None
        if events.problem:
            raise ms.SuggestError("storage", "這個聊天的紀錄不完整，不整理它")
        return chat, events.records
    return read


def cap_usd(day: Decimal, daily: Decimal) -> Decimal:
    """The most the one call may cost: CALL_USD, or what the day has left when that is less, in whole cents downward (zero when
    the day has none left)."""
    left = daily - day
    if left <= 0:
        return Decimal(0)
    return min(ms.CALL_USD, left).quantize(CENT, rounding=ROUND_DOWN)


class MemorySuggestRunner(HeadlessBoard):
    final_kind = ms.TURN_KIND
    final_needs_answers = False
    store_cls = ms.SuggestStore
    room_name = "這次整理"
    error_cls = ms.SuggestError

    # -- what this feature gives the engine ------------------------------------------------------------------------

    def ids(self) -> list[str]:
        return ms.record_ids()

    def load(self, sid: str) -> dict:
        return ms.load(sid)

    def view(self, rec: dict) -> dict:
        return ms.view(rec)

    def remove(self, sid: str) -> None:
        ms.delete(sid)

    def schema(self, kind: str, ctx=None) -> dict:
        return ms.SCHEMA

    def validate(self, kind: str, output, who: dict, ctx: Context) -> dict:
        return ms.validate(output)

    def prompt(self, kind: str, who: dict, rec: dict, ctx: Context) -> str:
        return ms.build_prompt(messages=ctx.read["messages"], omitted=ctx.read["omitted"], memory_lines=ctx.memory_lines)

    def per_call(self, rec: dict, turn: dict) -> Decimal:
        return ms.per_call_of(rec, turn)

    def total_limit(self, rec: dict) -> Decimal:
        return mt.money(rec["limits"]["total_usd"]) or Decimal(0)

    def decided(self, rec: dict) -> bool:
        return rec["outcome"]["dismissed"]

    def timeout(self, kind: str) -> float:
        return ms.TIMEOUT

    def on_final(self, sid: str) -> None:
        def ready(rec):
            rec["outcome"]["state"] = "ready"
            rec["outcome"]["at"] = self.clock()
        self._update(sid, ready)

    def spend_kinds(self) -> list:
        """The suggestions share the day with the meetings, the staffing meetings, the chief of staff, the chats and the tries."""
        return [(mt.meeting_ids, mt.load, mt.per_call_limit), (st.record_ids, st.load, st.per_call_of), chief.spend_kind(),
                cs.spend_kind(self.clock), try_spend.spend_kind(), ms.spend_kind(),
                skillbook_suggest.spend_kind()]

    # -- the chat and the memory -----------------------------------------------------------------------------------

    def _context(self, chat_id, sources: SuggestSources) -> Context:
        chat, records = sources.chat(chat_id)
        if sources.in_group(chat_id):
            raise ms.SuggestError("group_chat")
        read = chief.select_messages(records)
        lines = ms.sendable_memory(sources.memory())
        daily = mt.limits_from(sources.conf)["daily_usd"]
        engine = chat.get("engine", "claude-chat")
        return Context(chat_id=chat_id, engine=engine, read=read, memory_lines=lines, inputs_sha=ms.inputs_sha(lines),
                       limits={"per_call_usd": ms.CALL_USD, "total_usd": ms.TOTAL_USD}, daily_usd=daily, version="", binary="")

    def _check_count(self) -> None:
        if len(ms.record_ids()) >= ms.MAX_RECORDS:
            raise ms.SuggestError("too_many")

    # -- a new suggestion ------------------------------------------------------------------------------------------

    def preview(self, chat_id, sources: SuggestSources) -> dict:
        """What would be read and what it may cost, without a word of the chat or of the memory. Starts nothing."""
        ctx = self._context(chat_id, sources)
        self._check_count()
        blockers: list = []
        binary, version = self._provider_state(blockers)
        if ctx.read["count"] == 0:
            blockers.append({"code": "no_conversation", "message": str(ms.SuggestError("no_conversation"))})
        day = self._day()
        cap = cap_usd(day, ctx.daily_usd)
        more, today = self._blockers(max(cap, CENT), ms.TOTAL_USD, {"daily_usd": ctx.daily_usd})
        blockers += more
        out = {"preview_id": None, "ok": not blockers, "blockers": blockers, "chat_id": chat_id,
               "messages": ctx.read["count"], "omitted_messages": ctx.read["omitted"], "bytes": ctx.read["bytes"],
               "memory_lines": len(ctx.memory_lines), "cap_usd": mt.fmt(cap),
               "day_left_usd": mt.fmt(max(ctx.daily_usd - day, Decimal(0))), "today": today, "sends_to": ms.SENDS_TO,
               "engine": ctx.engine, "notice": CODEX_NOTICE if ctx.engine == "codex-chat" else None, "save_note": SAVE_NOTE,
               "cli": {"version": version, "verified": version is not None}, "disclosure": DISCLOSURE, "cost_note": COST_NOTE}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "new", "chat_id": chat_id, "read_sha": ctx.read["sha256"],
                                            "inputs_sha": ctx.inputs_sha, "version": version})
        return out

    def start(self, preview_id, sources: SuggestSources) -> dict:
        entry = self._take(preview_id, "new")
        ctx = self._context(entry["chat_id"], sources)
        if ctx.read["sha256"] != entry["read_sha"] or ctx.inputs_sha != entry["inputs_sha"]:
            raise ms.SuggestError("stale_preview")
        ctx.binary, ctx.version = self._resolve()
        if ctx.version != entry["version"]:
            raise ms.SuggestError("stale_preview")
        self._check_count()
        cap = cap_usd(self._day(), ctx.daily_usd)
        more, _ = self._blockers(max(cap, CENT), ms.TOTAL_USD, {"daily_usd": ctx.daily_usd}, check_lock=False)
        if more or cap < CENT:
            raise ms.SuggestError("budget")
        ctx.limits = {"per_call_usd": cap, "total_usd": ms.TOTAL_USD}
        fd = self._worker()
        try:
            sid = ms.new_id()
            while ms.SuggestStore(sid).path().exists() or ms.SuggestStore(sid).marker_path().exists():
                sid = ms.new_id()
            rec = ms.new_record(sid, chat_id=ctx.chat_id, engine=ctx.engine, read=ctx.read, memory_count=len(ctx.memory_lines),
                                inputs=ctx.inputs_sha, limits=ctx.limits, now=self.clock())
            store = ms.SuggestStore(sid)
            with store.locked():
                store.save(rec)
        except StoreError as exc:
            os.close(fd)
            raise ms.SuggestError("storage", str(exc)) from None
        except BaseException:
            os.close(fd)
            raise
        self._launch(sid, ctx, fd)
        return rec

    # -- what the person does with an answer ---------------------------------------------------------------------------

    def mark_saved(self, sid: str, indexes) -> dict:
        """Write on the record which lines the person saved (their own presses, through POST /api/memory, did the saving). The
        record of a suggestion that has answered and was not dropped; a line that is not in it is a bad request."""
        if (not isinstance(indexes, list) or len(indexes) > ms.MAX_ITEMS or len(set(indexes)) != len(indexes)
                or any(type(i) is not int or i < 0 for i in indexes)):
            raise ms.SuggestError("bad_request", "indexes 必須是不重複的非負整數清單")

        def change(rec):
            out = rec["turns"][0]["output"]
            if rec["outcome"]["state"] != "ready" or out is None:
                raise ms.SuggestError("not_ready")
            if rec["outcome"]["dismissed"]:
                raise ms.SuggestError("already_decided")
            if any(i >= len(out["items"]) for i in indexes):
                raise ms.SuggestError("bad_request", "沒有這一條")
            rec["outcome"]["saved"] = sorted(set(rec["outcome"]["saved"]) | set(indexes))
        return self._update(sid, change)

    def dismiss(self, sid: str) -> dict:
        """「不用了」: the person drops the suggestion. It stays in the list (the money it cost is the day's) until it is deleted."""
        def change(rec):
            if rec["outcome"]["state"] != "ready":
                raise ms.SuggestError("not_ready")
            rec["outcome"]["dismissed"] = True
        return self._update(sid, change)

    # -- the rest of the API ---------------------------------------------------------------------------------------

    def get(self, sid: str) -> dict:
        """A suggestion as ms.view shows it, and, while it runs here, its clock."""
        out = ms.view(ms.load(sid))
        clock = self.clock_of(sid)
        if clock is not None:
            out["clock"] = clock
        return out

    def list(self) -> dict:
        out = []
        for sid in ms.record_ids():
            try:
                v = ms.view(ms.load(sid))
            except mt.MeetingError as exc:
                out.append({"id": sid, "blocked": True, "error": str(exc)})
                continue
            out.append({"id": sid, "created_at": v["created_at"], "chat_id": v["chat_id"], "status": v["status"], "spent_usd": v["spent_usd"],
                        "saved": len(v["saved"]), "dismissed": v["dismissed"]})
        out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return {"suggestions": out}
