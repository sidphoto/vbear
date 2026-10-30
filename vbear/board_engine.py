"""The engine under the meetings (P35-0): a sequence of headless Claude Code calls with no tools, one turn after another,
and what keeps them safe and paid for. A meeting is one kind of board (meeting_runner); the engine does not know what the
turns say, which rules judge them, or what the chairman may decide.

For every kind of board:

  * every call is the translation argv plus three changed values (--model, --max-budget-usd and the schema) and a stream
    output with --verbose, so that its init event can be read; the init event must say that the only tool is
    StructuredOutput and that there are no MCP servers, checked on every call as the line arrives. A call that says
    anything else is killed (the whole process group) on the spot, its result is not used, and the version's pass in
    translation-boundaries.json is revoked until it is checked again;
  * turns run one after another, never at the same time; the last turn (``final_kind``) is asked only when an earlier
    one has an answer;
  * nothing is retried by itself. A failed turn waits for a person to retry it (twice at most);
  * a turn whose text cannot be made (over the size limit, ``too_large``) fails without being sent, as does one whose
    text is not the one previewed; it never stays queued;
  * one worker at a time (``meeting-worker.lock``), with its own ``meeting-worker.blocked`` marker, whatever the kind of
    board, so that two boards never run at the same time;
  * before a board starts, what it reserves must fit what is left of the record's own limit and of the day; before every
    call, the most that turn's call may cost must fit both again, or the turn is skipped;
  * what a call cost is what the CLI reported, or the most that turn's call may cost when it reported nothing; a turn
    left running by a stopped console costs that too, and nothing resumes.

A kind of board gives the engine its hooks: where its records live (``store_cls``, ``ids``, ``load``, ``view``,
``remove``), the schema, the check and the prompt of a turn, the most one turn's call may cost (``per_call``), the most a
whole record may cost (``total_limit``), whether the chairman has closed the record (``decided``), and what to do when the
last turn is answered (``on_final``).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from . import agent_profiles as ap, config as cfg, headless_cli, meetings as mt, model_options, strictjson
from . import translations as tr
from .jsonstore import StoreError
from .runtime.agent_sessions import MODEL_ID_RE

PREVIEW_TTL = 300.0
MAX_PREVIEWS = 16
MAX_STREAM = 256 * 1024
STREAM_LIMITS = strictjson.Limits(MAX_STREAM, 50_000, 16, MAX_STREAM)
WORKER = "meeting-worker"
SPEAKER_POSITIONS = ("pm", "social", "executor", "art", "legal", "accountant")
CHAIR_POSITION = "planner"
DEFAULT_ALIAS = "sonnet"


@dataclass
class Sources:
    """Where a request reads cards and task cards from (the server passes the stores; tests pass dicts)."""
    profile: Callable[[str], dict | None]
    task: Callable[[str], dict | None]
    flows: Callable[[str], list]
    conf: dict = field(default_factory=dict)


@dataclass
class CallSpec:
    kind: str
    binary: str
    version: str
    model: str
    schema: dict
    prompt: str
    per_call: Decimal
    timeout: float = mt.CALL_TIMEOUT


@dataclass
class CallResult:
    output: Any
    evidence: dict
    cost: Decimal | None


class CallFailed(Exception):
    """A call that gave no usable result. ``evidence`` is what was seen of it; ``cost`` what the CLI reported, if it did."""

    def __init__(self, code: str, evidence: dict | None = None, cost: Decimal | None = None):
        self.code = code
        self.evidence = evidence
        self.cost = cost
        super().__init__(code)


# ---- the call ----------------------------------------------------------------------------------------------------

def meeting_argv(binary: str, model: str, schema: dict, per_call: Decimal) -> list[str]:
    """The translation argv (tools "", safe mode, strict empty MCP, no session kept) with only the model, the schema and
    the budget changed, and the output a stream with --verbose: the shape the no-tool check verified."""
    args = tr.translation_argv("claude", binary, "", schema)
    args[args.index("--model") + 1] = model
    args[args.index("--max-budget-usd") + 1] = mt.fmt(per_call)
    args[args.index("--output-format") + 1] = "stream-json"
    return args + ["--verbose"]


class _Stream:
    """Reads the stream a call prints, line by line, and refuses what a no-tool call cannot print."""

    def __init__(self):
        self.init = None
        self.result = None

    def feed(self, line: bytes) -> None:
        if not line.strip():
            return
        parsed = strictjson.loads_object(line, STREAM_LIMITS)
        if not parsed.ok:
            raise headless_cli.HeadlessError("invalid_output")
        event = parsed.value
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            if self.init is not None or event.get("tools") != ["StructuredOutput"] or event.get("mcp_servers") != []:
                raise headless_cli.HeadlessError("tools_not_clean")
            self.init = event
        elif kind == "assistant":
            content = (event.get("message") or {}).get("content") if isinstance(event.get("message"), dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") != "StructuredOutput":
                    raise headless_cli.HeadlessError("tools_not_clean")
        elif kind == "result":
            if self.result is not None:
                raise headless_cli.HeadlessError("invalid_output")
            self.result = event

    def evidence(self, version: str, returncode, duration_ms) -> dict:
        init = self.init or {}
        model = init.get("model")
        return {"cli_version": version, "model_reported": model[:200] if isinstance(model, str) else None,
                "tools_reported": init.get("tools") if isinstance(init.get("tools"), list) else None,
                "mcp_servers_reported": init.get("mcp_servers") if isinstance(init.get("mcp_servers"), list) else None,
                "exit_code": returncode, "duration_ms": duration_ms}


def default_call(spec: CallSpec, cancel) -> CallResult:
    stream = _Stream()
    try:
        run = headless_cli.run(lambda tmp: meeting_argv(spec.binary, spec.model, spec.schema, spec.per_call), spec.prompt.encode(), cancel,
                               timeout=spec.timeout, max_output=MAX_STREAM, blocked_name=f"{WORKER}.blocked",
                               prefix="vbear-meeting-", on_line=stream.feed)
        tail = run.output.rsplit(b"\n", 1)[-1]
        stream.feed(tail)  # a last line with no line break has not been seen yet
    except headless_cli.HeadlessError as exc:
        raise CallFailed(exc.code, stream.evidence(spec.version, exc.returncode, None), None) from None
    evidence = stream.evidence(spec.version, run.returncode, run.duration_ms)
    result = stream.result
    if stream.init is None or result is None:
        raise CallFailed("invalid_output", evidence, None)
    cost = None
    if "total_cost_usd" in result:
        cost = mt.money(result["total_cost_usd"])
        if cost is None:
            raise CallFailed("invalid_output", evidence, None)
    if result.get("is_error") is not False:
        raise CallFailed("cli_error", evidence, cost)
    if not isinstance(result.get("structured_output"), dict):
        raise CallFailed("invalid_output", evidence, cost)
    return CallResult(result["structured_output"], evidence, cost)


# ---- who sits ----------------------------------------------------------------------------------------------------

def model_for(profile: dict, position: str | None) -> str:
    """The model a card speaks with: a Claude card's own model (an alias or a name that is safe on a command line), else
    the alias its position suggests. A card of another tool does not speak itself: Claude speaks for it."""
    model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
    own = model.get("model_id")
    if model.get("tool") == "claude" and isinstance(own, str) and own and MODEL_ID_RE.match(own):
        return own
    alias = next((r["suggested_model_alias"] for r in ap.POSITION_TABLE if r["id"] == position), None)
    return alias if alias in model_options.CLAUDE_ALIASES else DEFAULT_ALIAS


def participant(profile: dict, position: str) -> dict:
    tool = profile["model"]["tool"]
    return {"profile_id": profile["id"], "name": profile["name"], "position": position, "tool": tool,
            "model_used": model_for(profile, position), "revision": ap.profile_digest(profile), "proxy": tool != "claude"}


def _card(sources: Sources, pid, *, role: str) -> tuple[dict, str]:
    if not isinstance(pid, str) or not pid:
        raise mt.MeetingError("bad_request", f"{role}必須是角色卡 id")
    profile = sources.profile(pid)
    if profile is None:
        raise mt.MeetingError("bad_request", f"找不到角色卡 {pid[:64]}")
    if profile.get("enabled") is False:
        raise mt.MeetingError("bad_request", f"角色卡「{profile.get('name')}」已停用")
    return profile, ap.position_of(profile) or ""


def _select(sources: Sources, chair_id, speaker_ids) -> tuple[tuple[dict, str], list[tuple[dict, str]]]:
    chair = _card(sources, chair_id, role="主席")
    if chair[1] != CHAIR_POSITION:
        raise mt.MeetingError("bad_request", "主席必須是 CEO 職位的角色卡")
    if not isinstance(speaker_ids, list) or not 1 <= len(speaker_ids) <= mt.MAX_SPEAKERS:
        raise mt.MeetingError("bad_request", f"發言者要 1 到 {mt.MAX_SPEAKERS} 位")
    speakers, seen_ids, seen_positions = [], set(), set()
    for pid in speaker_ids:
        card = _card(sources, pid, role="發言者")
        if pid in seen_ids or pid == chair_id:
            raise mt.MeetingError("bad_request", "同一張角色卡不能重複")
        if card[1] not in SPEAKER_POSITIONS:
            raise mt.MeetingError("bad_request", f"角色卡「{card[0].get('name')}」的職位不能發言（要是 PM、社群媒體經理、全端工程師、藝術總監、法務經理或會計師）")
        if card[1] in seen_positions:
            raise mt.MeetingError("bad_request", "每個職位只能有一張角色卡發言")
        seen_ids.add(pid)
        seen_positions.add(card[1])
        speakers.append(card)
    return chair, speakers


def _provider_code(exc: tr.TranslationError) -> str:
    """Why no Claude Code can be used, in the meeting's words: not installed, storage, an unconfirmed process, or (for
    anything else, such as a version query that failed or timed out) not verified."""
    return exc.code if exc.code in ("cli_not_found", "storage", "process_unconfirmed") else "boundary_unverified"


# A failed tool-less check in the meeting's words: the translations' own texts speak of translating (and of Codex). A code
# not listed keeps the translations' text, which already fits (Claude Code not found).
CHECK_ERRORS = {
    "boundary_unverified": "這個 Claude Code 版本沒有通過無工具安全檢查（版本或檢查的回應看不懂，或它回報的不是只有 StructuredOutput、沒有 MCP），會議仍然不能開始",
    "busy": "正在翻譯或正在做另一次檢查，請等它結束再檢查",
    "timeout": "檢查超過 60 秒，已停止",
    "invalid_output": "Claude Code 沒有回傳看得懂的檢查結果",
    "cli_failed": "Claude Code 執行失敗，請自行檢查登入與額度",
    "storage": "無工具安全檢查的紀錄無法安全讀寫，請人工檢查狀態目錄",
    "process_unconfirmed": "無法確認檢查的程序群組已結束，已封鎖後續的翻譯與檢查，請人工檢查",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---- what the last turn is given of the speakers -------------------------------------------------------------------

POSITION_LABELS = {row["id"]: row["label"] for row in ap.POSITION_TABLE}
STATE_LABELS = {"failed": "發言失敗", "blocked": "卡住", "skipped": "沒有發言", "cancelled": "已取消", "interrupted": "中斷"}


def opinions_for_chair(rec: dict, who: Callable[[str], dict], said: Callable[[dict], Any]) -> list[dict]:
    """For every speaker's turn, in order: the position, the name and whether Claude spoke for the card, then what was
    said (``said(turn)``, the kind of board's own form of a kept answer) or, when nothing was, why."""
    out = []
    for turn in rec["turns"]:
        if turn["kind"] != "opinion":
            continue
        person = who(turn["profile_id"])
        item = {"職位": POSITION_LABELS.get(person["position"], person["position"]), "名稱": person["name"], "代發言": person["proxy"]}
        if turn["state"] == "done":
            item["發言"] = said(turn)
        else:
            item["狀態"] = "沒有發言（" + STATE_LABELS.get(turn["state"], turn["state"]) + "）"
        out.append(item)
    return out


# ---- the engine ----------------------------------------------------------------------------------------------------

class HeadlessBoard:
    """The engine. A kind of board subclasses it and gives the hooks. ``ctx`` is that kind's own context of a running
    board; the engine reads only ``who(profile_id)``, ``expected_sha``, ``binary``, ``version`` and ``daily_usd`` of it."""

    final_kind = ""  # the kind of the last turn, the one that answers the others
    store_cls: Any = None  # the GuardedJsonStore of one record, built from its id
    room_name = ""  # how a message names what is left of one record's own limit

    def __init__(self, *, call: Callable | None = None, provider: Callable | None = None, verifier: Callable | None = None,
                 clock: Callable[[], float] = time.time):
        self.call = call or default_call
        self.provider = provider or tr.resolve_provider
        self.verifier = verifier or tr.verify_boundary
        self.clock = clock
        self.lock = threading.RLock()
        self.previews: dict[str, dict] = {}
        self.job: dict | None = None
        self.recover()

    # -- the hooks of a kind of board ------------------------------------------------------------------------------

    def ids(self) -> list[str]:
        """The ids of the records in the folder, a damaged one included."""
        raise NotImplementedError

    def load(self, rid: str) -> dict:
        """One record, checked; MeetingError when it is missing or damaged."""
        raise NotImplementedError

    def view(self, rec: dict) -> dict:
        raise NotImplementedError

    def remove(self, rid: str) -> None:
        raise NotImplementedError

    def schema(self, kind: str) -> dict:
        raise NotImplementedError

    def validate(self, kind: str, output, who: dict, ctx) -> dict:
        """What a model wrote for a turn of this kind, as it is kept; mt.OutputError when it is not what the schema allows."""
        raise NotImplementedError

    def prompt(self, kind: str, who: dict, rec: dict, ctx) -> str:
        """The text of the turn about to run, made from the record as it is now."""
        raise NotImplementedError

    def per_call(self, rec: dict, turn: dict) -> Decimal:
        """The most one call of this turn may cost: its --max-budget-usd, and its cost when none was reported."""
        raise NotImplementedError

    def total_limit(self, rec: dict) -> Decimal:
        """The most the whole record may cost."""
        raise NotImplementedError

    def decided(self, rec: dict) -> bool:
        """Whether the chairman has closed the record, after which no turn is retried."""
        raise NotImplementedError

    def on_final(self, rid: str) -> None:
        """Called when the last turn has been answered and kept."""

    # -- helpers ---------------------------------------------------------------------------------------------------

    def _resolve(self):
        """(binary, version) of the Claude Code that has passed the no-tool check; MeetingError otherwise."""
        try:
            return self.provider("claude")
        except tr.TranslationError as exc:
            raise mt.MeetingError(_provider_code(exc)) from None

    def spend_records(self) -> list[dict]:
        """The records whose turns count toward the day's limit."""
        out = []
        for rid in self.ids():
            try:
                out.append(self.load(rid))
            except mt.MeetingError:
                continue  # a damaged record is shown as blocked in the list; it adds nothing here
        return out

    def spent(self, rec: dict) -> Decimal:
        return mt.spent(rec, self.per_call)

    def room(self, rec: dict) -> Decimal:
        """What is left of the record's own limit (below zero when the worst case has passed it)."""
        return self.total_limit(rec) - self.spent(rec)

    def _day(self) -> Decimal:
        return mt.daily_spent(self.spend_records(), self.clock(), self.per_call)

    def _update(self, mid: str, change: Callable[[dict], None]) -> dict:
        store = self.store_cls(mid)
        try:
            with store.locked():
                rec = store.load()
                if not rec:
                    raise mt.MeetingError("not_found")
                change(rec)
                store.save(rec)
                return rec
        except StoreError as exc:
            raise mt.MeetingError("storage", str(exc)) from None

    def _take(self, preview_id, kind: str) -> dict:
        with self.lock:
            now = self.clock()
            for key in [k for k, v in self.previews.items() if v["expires"] <= now]:
                del self.previews[key]
            entry = self.previews.pop(preview_id, None) if isinstance(preview_id, str) else None
        if entry is None or entry["kind"] != kind:
            raise mt.MeetingError("preview_expired")
        return entry

    def _keep(self, entry: dict) -> str:
        with self.lock:
            now = self.clock()
            for key in [k for k, v in self.previews.items() if v["expires"] <= now]:
                del self.previews[key]
            while len(self.previews) >= MAX_PREVIEWS:
                self.previews.pop(next(iter(self.previews)))
            preview_id = "pv-" + secrets.token_hex(8)
            self.previews[preview_id] = {**entry, "expires": now + PREVIEW_TTL}
            return preview_id

    def _blockers(self, reserve: Decimal, room: Decimal, limits: dict, *, check_lock=True) -> tuple[list, dict]:
        """(blockers, today): why a board that reserves ``reserve`` for the calls it still needs may not start, when
        ``room`` is what is left of its own limit; and the day's money."""
        day = self._day()
        today = {"spent_usd": mt.fmt(day), "daily_usd": mt.fmt(limits["daily_usd"]), "lamp": mt.lamp(day, limits)}
        blockers = []
        if reserve > room:
            blockers.append({"code": "budget", "message": f"預留 {mt.fmt(reserve)} 美元超過{self.room_name}剩下的額度 {mt.fmt(max(room, Decimal(0)))}"})
        if day + reserve > limits["daily_usd"] or today["lamp"] == "red":
            blockers.append({"code": "budget", "message": f"今天已花 {today['spent_usd']} 美元，加上預留 {mt.fmt(reserve)} 會超過每日上限 {today['daily_usd']}"})
        if check_lock:
            if (cfg.state_dir() / f"{WORKER}.blocked").exists():
                blockers.append({"code": "process_unconfirmed", "message": mt.ERRORS["process_unconfirmed"]})
            elif self.job is not None or self._worker_busy():
                blockers.append({"code": "busy", "message": mt.ERRORS["busy"]})
        return blockers, today

    @staticmethod
    def _worker_busy() -> bool:
        try:
            fd = headless_cli.acquire_worker(WORKER, check_blocked=False)
        except headless_cli.HeadlessError:
            return True
        os.close(fd)
        return False

    def _provider_state(self, blockers: list) -> tuple[str | None, str | None]:
        try:
            binary, version = self.provider("claude")
            return binary, version
        except tr.TranslationError as exc:
            code = _provider_code(exc)
            blockers.append({"code": code, "message": mt.ERRORS[code]})
            return None, None

    # -- the tool-less check ---------------------------------------------------------------------------------------

    def verify(self) -> dict:
        """The tool-less check of the Claude Code every meeting uses, asked by a person from a preview: the probe and the record
        of the settings page's check (translations.verify_boundary), but always of Claude. The translations' engine is not
        read: a meeting speaks only through Claude Code, and with Codex chosen for translations that check refuses at once."""
        try:
            return self.verifier("claude")
        except tr.TranslationError as exc:
            raise mt.MeetingError(exc.code, CHECK_ERRORS.get(exc.code, str(exc))) from None

    def _same_cards(self, people: list[dict], sources: Sources, code: str = "stale_preview") -> None:
        for person in people:
            current = sources.profile(person["profile_id"])
            if current is None or current.get("enabled") is False or ap.profile_digest(current) != person["revision"]:
                raise mt.MeetingError(code)

    def _worker(self) -> int:
        with self.lock:
            if self.job is not None:
                raise mt.MeetingError("busy")
        try:
            return headless_cli.acquire_worker(WORKER)
        except headless_cli.HeadlessError as exc:
            raise mt.MeetingError(exc.code if exc.code in mt.ERRORS else "storage") from None

    def _launch(self, mid: str, ctx, fd: int) -> None:
        cancel = threading.Event()
        thread = threading.Thread(target=self._work, args=(mid, ctx, cancel, fd), daemon=True, name=f"meeting-{mid}")
        with self.lock:
            self.job = {"meeting_id": mid, "cancel": cancel, "thread": thread}
        thread.start()

    # -- the worker ------------------------------------------------------------------------------------------------

    def _work(self, mid: str, ctx, cancel, fd: int) -> None:
        stop = None
        try:
            while True:
                rec = self.load(mid)
                turn = next((t for t in rec["turns"] if t["state"] == "queued"), None)
                if turn is None:
                    break
                if stop is None and cancel.is_set():
                    stop = "cancelled"
                if stop is not None:
                    self._end(mid, turn["seq"], "cancelled" if stop == "cancelled" else "skipped", stop, evidence=None)
                    continue
                stop = self._turn(mid, rec, turn, ctx, cancel)
        except (mt.MeetingError, StoreError):
            pass  # the record cannot be read or written: nothing more can be said about this board
        finally:
            os.close(fd)
            with self.lock:
                self.job = None

    def _end(self, mid: str, seq: int, state: str, code: str | None, *, evidence, output=None, attempts=None) -> None:
        def change(rec):
            turn = rec["turns"][seq - 1]
            turn.update(state=state, error_code=code, ended_at=self.clock(), output=output)
            if evidence is not None:
                turn["evidence"] = evidence
            if attempts is not None:
                turn["attempts"] = attempts
        self._update(mid, change)

    def _merged(self, previous: dict | None, evidence: dict | None, cost: Decimal | None, per_call: Decimal) -> dict:
        """The turn's evidence after this attempt: what this attempt saw, and the cost over every attempt (an unreported
        cost is the most a call may cost)."""
        evidence = evidence or {"cli_version": None, "model_reported": None, "tools_reported": None, "mcp_servers_reported": None,
                                "exit_code": None, "duration_ms": None}
        before = mt.money(previous.get("cost_usd")) if previous else None
        worst = previous is not None and previous.get("cost_source") == "worst_case" or cost is None
        added = per_call if cost is None else cost
        return {**evidence, "cost_usd": mt.fmt((before or Decimal(0)) + added), "cost_source": "worst_case" if worst else "cli"}

    def _turn(self, mid: str, rec: dict, turn: dict, ctx, cancel) -> str | None:
        """Run one queued turn. Returns what must stop the board ("cancelled", "boundary_revoked", "process_unconfirmed")
        or None."""
        seq = turn["seq"]
        who = ctx.who(turn["profile_id"])
        per_call = self.per_call(rec, turn)
        room = self.room(rec)
        day = self._day()
        if per_call > room or day + per_call > ctx.daily_usd:
            self._end(mid, seq, "skipped", "budget", evidence=None)
            return None
        final = turn["kind"] == self.final_kind
        if final and not any(t["state"] == "done" for t in rec["turns"] if t["kind"] != self.final_kind):
            self._end(mid, seq, "skipped", "no_opinions", evidence=None)
            return None
        attempts = turn["attempts"] + 1
        try:
            prompt = self.prompt(turn["kind"], who, rec, ctx)
        except mt.MeetingError:  # the only one a prompt raises: its text is over the size limit
            self._end(mid, seq, "failed", "too_large", evidence=None, attempts=attempts)  # never sent
            return None
        except Exception:
            self._end(mid, seq, "failed", "internal", evidence=None, attempts=attempts)  # never sent
            return None
        sha = _sha(prompt)
        expected = ctx.expected_sha.get(who["profile_id"])
        if not final and expected is not None and expected != sha:
            self._end(mid, seq, "failed", "prompt_changed", evidence=None, attempts=attempts)  # never sent
            return None

        def start(r):
            r["turns"][seq - 1].update(state="running", attempts=attempts, started_at=self.clock(), ended_at=None,
                                       prompt_sha256=sha, error_code=None, output=None)
        self._update(mid, start)
        spec = CallSpec(turn["kind"], ctx.binary, ctx.version, who["model_used"], self.schema(turn["kind"]), prompt, per_call)
        previous = turn["evidence"]
        output, code, stop = None, None, None
        try:
            result = self.call(spec, cancel)
            evidence = self._merged(previous, result.evidence, result.cost, per_call)
            try:
                output = self.validate(turn["kind"], result.output, who, ctx)
            except mt.OutputError as exc:
                code = exc.code
        except CallFailed as exc:
            code = exc.code
            evidence = self._merged(previous, exc.evidence, exc.cost, per_call)
        except Exception:
            code = "internal"
            evidence = self._merged(previous, None, None, per_call)
        if code is None:
            self._end(mid, seq, "done", None, evidence=evidence, output=output, attempts=attempts)
            if final:
                self.on_final(mid)
            return None
        if code == "cancelled":
            self._end(mid, seq, "cancelled", code, evidence=evidence, attempts=attempts)
            return "cancelled"
        if code == "tools_not_clean":
            self._revoke(ctx.version)
            stop = "boundary_revoked"
        elif code == "process_unconfirmed":
            stop = "process_unconfirmed"
        state = "blocked" if attempts >= mt.MAX_ATTEMPTS and stop is None else "failed"
        self._end(mid, seq, state, code, evidence=evidence, attempts=attempts)
        return stop

    @staticmethod
    def _revoke(version: str) -> None:
        store = tr.BoundaryStore()
        try:
            with store.locked():
                data = store.load()
                data.pop(version, None)
                store.save(data)
        except StoreError:
            pass  # the check is then also unreadable, which already refuses every later board

    def wait(self, timeout: float = 10.0) -> None:
        with self.lock:
            job = self.job
        if job is not None:
            job["thread"].join(timeout)

    # -- after a restart -------------------------------------------------------------------------------------------

    def recover(self) -> None:
        """A turn that was running when the console stopped is interrupted, and costs what its call may cost at the most;
        a queued one is interrupted without cost. Nothing is resumed. Only when no other process holds the worker."""
        try:
            fd = headless_cli.acquire_worker(WORKER, check_blocked=False)
        except headless_cli.HeadlessError:
            return
        try:
            for mid in self.ids():
                try:
                    rec = self.load(mid)
                except mt.MeetingError:
                    continue
                if not any(t["state"] in ("queued", "running") for t in rec["turns"]):
                    continue
                self._update(mid, self._interrupt)
        finally:
            os.close(fd)

    def _interrupt(self, rec: dict) -> None:
        for turn in rec["turns"]:
            if turn["state"] not in ("queued", "running"):
                continue
            if turn["state"] == "running":
                turn["evidence"] = self._merged(turn["evidence"], turn["evidence"], None, self.per_call(rec, turn))
            turn.update(state="blocked" if turn["attempts"] >= mt.MAX_ATTEMPTS else "interrupted", error_code="restart",
                        ended_at=self.clock())

    # -- retry -------------------------------------------------------------------------------------------------------

    def _retry_plan(self, mid: str, seq, sources: Sources) -> tuple[dict, dict, bool]:
        """(record, turn, again): the turn a person asks to retry, and whether the last turn is asked again after it."""
        rec = self.load(mid)
        with self.lock:
            if self.job is not None and self.job["meeting_id"] == mid:
                raise mt.MeetingError("running")
        if self.decided(rec):
            raise mt.MeetingError("already_decided")
        if type(seq) is not int or not 1 <= seq <= len(rec["turns"]):
            raise mt.MeetingError("bad_request", "seq 必須是這場會議的發言編號")
        turn, last = rec["turns"][seq - 1], rec["turns"][-1]
        if any(t["state"] in ("queued", "running") for t in rec["turns"]):
            raise mt.MeetingError("running")
        if turn["state"] not in mt.RETRYABLE_STATES or turn["attempts"] >= mt.MAX_ATTEMPTS:
            raise mt.MeetingError("not_retryable")
        again = False
        if turn["kind"] != self.final_kind:
            if last["attempts"] >= mt.MAX_ATTEMPTS and last["state"] != "blocked":
                raise mt.MeetingError("not_retryable")  # a last turn that cannot be asked again would stand on an old answer
            again = last["attempts"] < mt.MAX_ATTEMPTS
        return rec, turn, again

    # -- the rest of the API ---------------------------------------------------------------------------------------

    def cancel(self, mid: str) -> dict:
        with self.lock:
            job = self.job
            if job is None or job["meeting_id"] != mid:
                raise mt.MeetingError("not_running")
            job["cancel"].set()
        return self.view(self.load(mid))

    def delete(self, mid: str) -> None:
        with self.lock:
            if self.job is not None and self.job["meeting_id"] == mid:
                raise mt.MeetingError("running")
        self.remove(mid)
