"""Running the chief of staff's proposal (P40-1): the preview, the one call, and what the chief of staff gives the engine.

The proposal is held by the engine of the meetings (board_engine.HeadlessBoard): one headless Claude Code call with no
tools, the check of its init event, the one worker shared with the meetings and the staffing meetings (so that they never
run at the same time), the money and what a restart leaves are described there. What is the chief of staff's own:

  * a board of one turn (``final_needs_answers`` is False: the engine does not wait for an earlier turn's answer);
  * VBear chose the model, the thinking and the limits (``sonnet``, low, at most CHIEF_CALL_USD, or what the day has left when
    that is less; 120 seconds); the person's config sets none of them and a proposal sets none;
  * only a chat with a CEO card may ask. What is read of the chat is the preview's: counts and sizes, never a word of it;
    the start reads the chat and the list again and goes on only when both are what was previewed;
  * a retry reads them again and goes on only when they are what the proposal started from;
  * when the proposal is kept, ``on_proposal(chief_id)`` is called once (the hook P40-3 uses to make a dispatch record);
    here the proposal is only recorded as ready;
  * the proposals share the day with the meetings, the staffing meetings, the chats and the tries (chief.spend_kind).

Nothing here makes a card, sends a message to an employee, writes the settings or installs a skill. Nothing but the
chief/ folder (and the worker's lock) is written.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Callable

from . import agent_profiles as ap, chief, config as cfg, meetings as mt, memory_suggest, skillbook_suggest, staffing as st, try_spend
from .board_engine import HeadlessBoard
from .jsonstore import StoreError
from .meeting_runner import COST_NOTE
from .runtime import chat_engines, chat_store as cs

CENT = Decimal("0.01")
DISCLOSURE = ("開始後，你和 CEO 最近的對話（最多 20 則、12 KiB）與員工名單，會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。"
              "VBear 不會把任何文字送到其他地方。每次呼叫前，VBear 都會確認這個版本的 Claude Code 沒有任何工具、沒有 MCP；確認不了就不送。")
CODEX_NOTICE = "這張 CEO 是 Codex 的角色卡：你和它的對話會送給 Claude Code（Anthropic）整理成提議。"


@dataclass
class ChiefSources:
    """Where a request reads from (the server passes the stores; tests pass dicts): a chat as (its chat.json, its records), a
    card by id, every card, and the AI tools whose chat can run now."""
    chat: Callable[[str], tuple]
    profile: Callable[[str], dict | None]
    profiles: Callable[[], list]
    tools: Callable[[], tuple]
    conf: dict = field(default_factory=dict)
    shared: Callable[[str, str], bool] | None = None      # (role card id, engine) -> whether the person opened the shared folder for the employee


@dataclass
class Context:
    """Everything the one prompt is made from; for a new proposal it is what the preview counted."""
    chat_id: str
    ceo_id: str
    ceo_tool: str
    note: str
    read: dict
    cards: list
    omitted_cards: int
    tools: tuple
    inputs_sha: str
    limits: dict
    daily_usd: Decimal
    version: str
    binary: str
    expected_sha: dict = field(default_factory=dict)
    speed: dict = field(default_factory=lambda: dict(chief.SPEED))

    def who(self, profile_id: str) -> dict:
        return chief.participant()


def usable_tools(support: dict) -> tuple:
    """The AI tools whose chat can run now, from ChatService.support(): Claude Code's top-level state is "verified", every
    other engine's own block (its row's ``support_key``) is "ready"."""
    out = []
    for row in chat_engines.TABLE:
        block = support if row.support_key is None else support.get(row.support_key)
        if isinstance(block, dict) and block.get("state") == ("verified" if row.support_key is None else "ready"):
            out.append(row.tool)
    return tuple(out)


def chat_reader(base=None) -> Callable[[str], tuple]:
    """A reader of chats for ChiefSources: (chat.json, records) of a chat in the state folder (or ``base``). A chat that is
    missing is not_found; one that does not read whole to its end is refused (storage), since the end of it is what matters."""
    def read(chat_id):
        if not isinstance(chat_id, str) or not chief.CHAT_ID_RE.match(chat_id):
            raise chief.ChiefError("bad_request", "chat_id 不符格式")
        root = Path(base) if base is not None else cfg.state_dir()
        try:
            chat = cs.load(root, chat_id)
            events = cs.read_events(root, chat_id)
        except cs.ChatStoreError as exc:
            if exc.code == "not_found":
                raise chief.ChiefError("not_found", "找不到這個聊天") from None
            raise chief.ChiefError("storage", "這個聊天的紀錄讀不出來，幕僚長不讀它") from None
        if events.problem:
            raise chief.ChiefError("storage", "這個聊天的紀錄不完整，幕僚長不讀它")
        return chat, events.records
    return read


def cap_usd(day: Decimal, daily: Decimal) -> Decimal:
    """The most the one call may cost: CHIEF_CALL_USD, or what the day has left when that is less, in whole cents downward (zero
    when the day has none left)."""
    left = daily - day
    if left <= 0:
        return Decimal(0)
    return min(chief.CHIEF_CALL_USD, left).quantize(CENT, rounding=ROUND_DOWN)


class ChiefRunner(HeadlessBoard):
    final_kind = chief.TURN_KIND
    final_needs_answers = False
    store_cls = chief.ChiefStore
    room_name = "這份幕僚長的提議"
    error_cls = chief.ChiefError

    def __init__(self, *, on_proposal: Callable[[str], None] | None = None, **kw):
        self.on_proposal = on_proposal
        super().__init__(**kw)

    # -- what the chief of staff gives the engine ------------------------------------------------------------------

    def ids(self) -> list[str]:
        return chief.record_ids()

    def load(self, cid: str) -> dict:
        return chief.load(cid)

    def view(self, rec: dict) -> dict:
        return chief.view(rec)

    def remove(self, cid: str) -> None:
        chief.delete(cid)

    def schema(self, kind: str, ctx=None) -> dict:
        tools = getattr(ctx, "tools", None)
        return chief.PLAN_SCHEMA if tools is None or tuple(tools) == tuple(ap.TOOL_ORDER) else chief.plan_schema(tools)

    def validate(self, kind: str, output, who: dict, ctx: Context) -> dict:
        return chief.validate_plan(output, ctx.cards, ctx.tools)

    def prompt(self, kind: str, who: dict, rec: dict, ctx: Context) -> str:
        return chief.build_prompt(messages=ctx.read["messages"], omitted=ctx.read["omitted"], cards=ctx.cards,
                                  omitted_cards=ctx.omitted_cards, tools=ctx.tools, note=ctx.note)

    def per_call(self, rec: dict, turn: dict) -> Decimal:
        return chief.per_call_of(rec, turn)

    def total_limit(self, rec: dict) -> Decimal:
        return mt.money(rec["limits"]["total_usd"]) or Decimal(0)

    def decided(self, rec: dict) -> bool:
        """A dispatch made from the proposal closes it: it is no longer retried."""
        return rec["outcome"]["dispatch_id"] is not None

    def timeout(self, kind: str) -> float:
        return chief.TIMEOUT

    def on_final(self, cid: str) -> None:
        def ready(rec):
            rec["outcome"] = {"state": "ready", "at": self.clock(), "dispatch_id": None}
        self._update(cid, ready)
        hook = self.on_proposal
        if hook is not None:
            try:
                hook(cid)
            except Exception:
                pass  # the proposal is kept whatever the hook does; whoever hooks in reports its own failure

    def link_dispatch(self, cid: str, dispatch_id: str) -> dict:
        """Record the dispatch made from a kept proposal on it (what P40-3's dispatch code does in ``on_proposal``). A proposal
        that is kept (``ready``) takes one dispatch for good: the same one again is the same, another is ``already_decided``.
        From then on the proposal is ``decided`` and is not asked again."""
        if not isinstance(dispatch_id, str) or not 0 < len(dispatch_id) <= 64:
            raise chief.ChiefError("bad_request", "派工的識別碼不符")

        def link(rec):
            outcome = rec["outcome"]
            if outcome["state"] != "ready":
                raise chief.ChiefError("not_retryable", "這份提議還沒有好，不能接上派工")
            if outcome["dispatch_id"] not in (None, dispatch_id):
                raise chief.ChiefError("already_decided")
            outcome["dispatch_id"] = dispatch_id
        return self._update(cid, link)

    def spend_kinds(self) -> list:
        """The proposals share the day with the meetings, the staffing meetings, the chats and the tries."""
        return [(mt.meeting_ids, mt.load, mt.per_call_limit), (st.record_ids, st.load, st.per_call_of), chief.spend_kind(),
                cs.spend_kind(self.clock), try_spend.spend_kind(), memory_suggest.spend_kind(),
                skillbook_suggest.spend_kind()]

    # -- the list and the chat -------------------------------------------------------------------------------------

    @staticmethod
    def _ceo(chat: dict, sources: ChiefSources) -> dict:
        """The CEO card of a chat; ChiefError when the chat is not with an enabled card in the CEO's position whose tool can
        chat (and is the tool the chat was opened with)."""
        profile = sources.profile(chat["profile_id"])
        if profile is None or profile.get("enabled") is False:
            raise chief.ChiefError("card_unavailable")
        if ap.position_of(profile) != "planner":
            raise chief.ChiefError("not_ceo")
        model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
        row = chat_engines.by_tool(model.get("tool"))
        if row is None or row.engine != chat.get("engine", "claude-chat"):
            raise chief.ChiefError("card_unavailable")
        return profile

    def _context(self, chat_id, sources: ChiefSources, note: str) -> Context:
        chat, records = sources.chat(chat_id)
        ceo = self._ceo(chat, sources)
        read = chief.select_messages(records)
        tools = tuple(sources.tools())
        cards, omitted = chief.candidates(sources.profiles(), tools, sources.shared)
        daily = mt.limits_from(sources.conf)["daily_usd"]
        return Context(chat_id=chat_id, ceo_id=ceo["id"], ceo_tool=ceo["model"]["tool"], note=note, read=read, cards=cards,
                       omitted_cards=omitted, tools=tools, inputs_sha=chief.inputs_sha(cards, omitted, tools),
                       limits={"per_call_usd": chief.CHIEF_CALL_USD, "total_usd": chief.TOTAL_USD}, daily_usd=daily, version="", binary="")

    @staticmethod
    def _clean_note(body) -> str:
        if not isinstance(body, dict) or set(body) - {"note"}:
            raise chief.ChiefError("bad_request", "只需要 note")
        try:
            return mt.clean_line(body.get("note"), chief.NOTE_MAX, "補充說明", required=False)
        except mt.MeetingError as exc:
            raise chief.ChiefError("bad_request", str(exc)) from None

    def _check_count(self) -> None:
        if len(chief.record_ids()) >= chief.MAX_RECORDS:
            raise chief.ChiefError("too_many")

    # -- a new proposal --------------------------------------------------------------------------------------------

    def preview(self, chat_id, sources: ChiefSources) -> dict:
        """What would be read and what it may cost, without a word of the chat. Starts nothing."""
        ctx = self._context(chat_id, sources, "")
        self._check_count()
        blockers: list = []
        binary, version = self._provider_state(blockers)
        if not ctx.tools:
            blockers.append({"code": "no_chat_tool", "message": str(chief.ChiefError("no_chat_tool"))})
        if ctx.read["count"] == 0:
            blockers.append({"code": "no_conversation", "message": str(chief.ChiefError("no_conversation"))})
        day = self._day()
        cap = cap_usd(day, ctx.daily_usd)
        more, today = self._blockers(max(cap, CENT), chief.TOTAL_USD, {"daily_usd": ctx.daily_usd})
        blockers += more
        out = {"preview_id": None, "ok": not blockers, "blockers": blockers, "chat_id": chat_id,
               "messages": ctx.read["count"], "omitted_messages": ctx.read["omitted"], "bytes": ctx.read["bytes"],
               "cards": len(ctx.cards), "omitted_cards": ctx.omitted_cards, "tools": list(ctx.tools),
               "cap_usd": mt.fmt(cap), "day_left_usd": mt.fmt(max(ctx.daily_usd - day, Decimal(0))), "today": today,
               "sends_to": "Claude Code", "ceo_tool": ctx.ceo_tool, "notice": CODEX_NOTICE if ctx.ceo_tool == "codex" else None,
               "cli": {"version": version, "verified": version is not None}, "disclosure": DISCLOSURE, "cost_note": COST_NOTE}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "new", "chat_id": chat_id, "read_sha": ctx.read["sha256"],
                                            "inputs_sha": ctx.inputs_sha, "version": version})
        return out

    def start(self, preview_id, body, sources: ChiefSources) -> dict:
        note = self._clean_note(body)
        entry = self._take(preview_id, "new")
        ctx = self._context(entry["chat_id"], sources, note)
        if ctx.read["sha256"] != entry["read_sha"] or ctx.inputs_sha != entry["inputs_sha"]:
            raise chief.ChiefError("stale_preview")
        ctx.binary, ctx.version = self._resolve()
        if ctx.version != entry["version"]:
            raise chief.ChiefError("stale_preview")
        self._check_count()
        cap = cap_usd(self._day(), ctx.daily_usd)
        more, _ = self._blockers(max(cap, CENT), chief.TOTAL_USD, {"daily_usd": ctx.daily_usd}, check_lock=False)
        if more or cap < CENT:
            raise chief.ChiefError("budget")
        ctx.limits = {"per_call_usd": cap, "total_usd": chief.TOTAL_USD}
        fd = self._worker()
        try:
            cid = chief.new_id()
            while chief.ChiefStore(cid).path().exists() or chief.ChiefStore(cid).marker_path().exists():
                cid = chief.new_id()
            rec = chief.new_record(cid, chat_id=ctx.chat_id, ceo_profile_id=ctx.ceo_id, note=note, read=ctx.read,
                                   sent=chief.sent_of(ctx.cards, ctx.omitted_cards, ctx.tools, ctx.inputs_sha),
                                   limits=ctx.limits, now=self.clock())
            store = chief.ChiefStore(cid)
            with store.locked():
                store.save(rec)
        except StoreError as exc:
            os.close(fd)
            raise chief.ChiefError("storage", str(exc)) from None
        except BaseException:
            os.close(fd)
            raise
        self._launch(cid, ctx, fd)
        return rec

    # -- retry -------------------------------------------------------------------------------------------------------

    def retry(self, cid: str, sources: ChiefSources) -> dict:
        """Ask again after a failed call (twice at most), on the same chat and list the proposal started from: a chat that
        has more in it since, or a list that is not the same, is ``changed``. The cap is worked out again for the day."""
        rec, _turn, _again = self._retry_plan(cid, 1, sources)
        ctx = self._context(rec["chat_id"], sources, rec["note"])
        if ctx.read["sha256"] != rec["read"]["sha256"] or ctx.inputs_sha != rec["sent"]["inputs_sha256"]:
            raise chief.ChiefError("changed")
        ctx.binary, ctx.version = self._resolve()
        cap = cap_usd(self._day(), ctx.daily_usd)
        more, _ = self._blockers(max(cap, CENT), self.room(rec), {"daily_usd": ctx.daily_usd}, check_lock=False)
        if more or cap < CENT:
            raise chief.ChiefError("budget")
        ctx.limits = {"per_call_usd": cap, "total_usd": mt.money(rec["limits"]["total_usd"])}
        fd = self._worker()

        def requeue(r):
            r["limits"]["per_call_usd"] = mt.fmt(cap)
            r["turns"][0].update(state="queued", error_code=None, output=None, ended_at=None)
        try:
            rec = self._update(cid, requeue)
        except BaseException:
            os.close(fd)
            raise
        self._launch(cid, ctx, fd)
        return rec

    # -- the rest of the API ---------------------------------------------------------------------------------------

    def get(self, cid: str) -> dict:
        """A proposal as chief.view shows it, and, while it runs here, its clock."""
        out = chief.view(chief.load(cid))
        clock = self.clock_of(cid)
        if clock is not None:
            out["clock"] = clock
        return out

    def list(self) -> dict:
        out = []
        for cid in chief.record_ids():
            try:
                v = chief.view(chief.load(cid))
            except mt.MeetingError as exc:
                out.append({"id": cid, "blocked": True, "error": str(exc)})
                continue
            out.append({k: v[k] for k in ("id", "created_at", "chat_id", "status", "spent_usd", "dispatch_id")})
        out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return {"chief": out}
