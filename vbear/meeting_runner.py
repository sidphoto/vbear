"""Running a meeting (P34-4): the preview the chairman confirms, one worker, and the calls it makes.

A meeting is held by headless Claude Code calls with no tools (the translation boundary, shared through headless_cli):

  * every call is the translation argv plus three changed values (--model, --max-budget-usd and the schema) and a stream
    output with --verbose, so that its init event can be read; the init event must say that the only tool is
    StructuredOutput and that there are no MCP servers, checked on every call as the line arrives. A call that says
    anything else is killed (the whole process group) on the spot, its result is not used, and the version's pass in
    translation-boundaries.json is revoked until it is checked again;
  * speakers run one after another, never at the same time, and never see each other; then the CEO writes the decision;
  * nothing is retried by itself. A failed turn waits for a person to retry it (twice at most), and the meeting is held
    for the chairman meanwhile (meeting_rules R7);
  * one worker at a time (``meeting-worker.lock``), with its own ``meeting-worker.blocked`` marker;
  * what a call cost is what the CLI reported, or the most a call may cost when it reported nothing.

The decision is a record. Nothing in this module acts on it: it writes no task card, no flow, no project folder.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from . import agent_profiles as ap, config as cfg, headless_cli, meeting_rules as rules, meetings as mt, model_options, strictjson
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
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")
POSITION_LABELS = {row["id"]: row["label"] for row in ap.POSITION_TABLE}
DEFAULT_ALIAS = "sonnet"

DISCLOSURE = ("開始後，下面每一段文字會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。VBear 不會把任何文字送到其他地方。"
              "每次發言前，VBear 都會確認這個版本的 Claude Code 沒有任何工具、沒有 MCP；確認不了就不送。")
COST_NOTE = "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。沒有回報時，以每次上限計（最壞情況）。"
PLACEHOLDER_OPINIONS = [{"說明": "各職位的發言，要等他們發言之後才有；CEO 看到的是已通過格式檢查、遮蔽過敏感字串的內容。"}]
PLACEHOLDER_SPEND = "（執行時由 VBear 填入這場會議到目前為止的花費）"
STATE_LABELS = {"failed": "發言失敗", "blocked": "卡住", "skipped": "沒有發言", "cancelled": "已取消", "interrupted": "中斷"}


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


@dataclass
class Context:
    """Everything a meeting's prompts are made from; for a new meeting it is what the preview showed."""
    topic: str
    context: str
    flags: list
    task_id: str | None
    task: dict | None
    progress: str | None
    chair: dict
    speakers: list
    instructions: dict
    limits: dict
    daily_usd: Decimal
    version: str
    binary: str
    expected_sha: dict = field(default_factory=dict)

    def people(self) -> list[dict]:
        return self.speakers + [self.chair]

    def who(self, profile_id: str) -> dict:
        return next(p for p in self.people() if p["profile_id"] == profile_id)

    def prompt(self, kind: str, person: dict, *, opinions=None, spend=None) -> str:
        return mt.build_prompt(kind, instructions=self.instructions.get(person["profile_id"]), position=person["position"],
                               topic=self.topic, context=self.context, task=self.task,
                               opinions=opinions, progress=self.progress if person["position"] == "pm" else None,
                               spend=spend if person["position"] == "accountant" else None)


def _provider_code(exc: tr.TranslationError) -> str:
    """Why no Claude Code can be used, in the meeting's words: not installed, storage, an unconfirmed process, or (for
    anything else, such as a version query that failed or timed out) not verified."""
    return exc.code if exc.code in ("cli_not_found", "storage", "process_unconfirmed") else "boundary_unverified"


def _flows(sources: Sources, task_id: str) -> list | None:
    try:
        return sources.flows(task_id)
    except Exception:
        return None  # the flow store cannot be read: the PM is told so, not that there are none


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _instructions_of(profile: dict) -> str:
    return ap.instructions_of(profile)["text"] or ""


def _opinions_for_chair(rec: dict, ctx: Context) -> list[dict]:
    out = []
    for turn in rec["turns"]:
        if turn["kind"] != "opinion":
            continue
        who = ctx.who(turn["profile_id"])
        item = {"職位": POSITION_LABELS.get(who["position"], who["position"]), "名稱": who["name"], "代發言": who["proxy"]}
        if turn["state"] == "done":
            item["發言"] = turn["output"]
        else:
            item["狀態"] = "沒有發言（" + STATE_LABELS.get(turn["state"], turn["state"]) + "）"
        out.append(item)
    return out


# ---- the runner ----------------------------------------------------------------------------------------------------

class MeetingRunner:
    def __init__(self, *, call: Callable | None = None, provider: Callable | None = None, clock: Callable[[], float] = time.time):
        self.call = call or default_call
        self.provider = provider or tr.resolve_provider
        self.clock = clock
        self.lock = threading.RLock()
        self.previews: dict[str, dict] = {}
        self.job: dict | None = None
        self.recover()

    # -- helpers ---------------------------------------------------------------------------------------------------

    def _resolve(self):
        """(binary, version) of the Claude Code that has passed the no-tool check; MeetingError otherwise."""
        try:
            return self.provider("claude")
        except tr.TranslationError as exc:
            raise mt.MeetingError(_provider_code(exc)) from None

    def _all(self) -> list[dict]:
        out = []
        for mid in mt.meeting_ids():
            try:
                out.append(mt.load(mid))
            except mt.MeetingError:
                continue  # a damaged meeting is shown as blocked in the list; it adds nothing here
        return out

    def _update(self, mid: str, change: Callable[[dict], None]) -> dict:
        store = mt.MeetingStore(mid)
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

    def _blockers(self, calls: int, per_call: Decimal, meeting_room: Decimal, limits: dict, *, check_lock=True) -> tuple[list, dict]:
        """(blockers, today): why a meeting that needs ``calls`` more calls may not start, and the day's money."""
        day = mt.daily_spent(self._all(), self.clock())
        today = {"spent_usd": mt.fmt(day), "daily_usd": mt.fmt(limits["daily_usd"]), "lamp": mt.lamp(day, limits)}
        blockers = []
        reserve = per_call * calls
        if reserve > meeting_room:
            blockers.append({"code": "budget", "message": f"預留 {mt.fmt(reserve)} 美元超過這場會議剩下的額度 {mt.fmt(max(meeting_room, Decimal(0)))}"})
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

    # -- a new meeting ---------------------------------------------------------------------------------------------

    def preview(self, body, sources: Sources) -> dict:
        allowed = {"topic", "context", "flags", "task_id", "chair_profile_id", "speaker_profile_ids"}
        if not isinstance(body, dict) or set(body) - allowed or not {"topic", "chair_profile_id", "speaker_profile_ids"} <= set(body):
            raise mt.MeetingError("bad_request", "會議要求的欄位不符")
        topic = mt.clean_line(body["topic"], mt.TOPIC_MAX, "議題", required=True)
        context = mt.clean_line(body.get("context"), mt.CONTEXT_MAX, "補充說明", required=False)
        flags = mt.clean_flags(body.get("flags"))
        task_id, task = body.get("task_id"), None
        if task_id is not None:
            if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
                raise mt.MeetingError("bad_request", "task_id 不符格式")
            task = sources.task(task_id)
            if task is None:
                raise mt.MeetingError("not_found", "找不到這張任務卡")
        chair_card, speaker_cards = _select(sources, body["chair_profile_id"], body["speaker_profile_ids"])
        limits = mt.limits_from(sources.conf)
        if len(mt.meeting_ids()) >= mt.MAX_MEETINGS:
            raise mt.MeetingError("too_many")
        blockers: list = []
        binary, version = self._provider_state(blockers)
        ctx = Context(topic=topic, context=context, flags=flags, task_id=task_id, task=task,
                      progress=mt.progress_summary(task, _flows(sources, task_id)) if task_id else None,
                      chair=participant(*chair_card), speakers=[participant(*c) for c in speaker_cards],
                      instructions={c[0]["id"]: _instructions_of(c[0]) for c in [chair_card] + speaker_cards},
                      limits=limits, daily_usd=limits["daily_usd"], version=version or "", binary=binary or "")
        calls = len(ctx.speakers) + 1
        more, today = self._blockers(calls, limits["per_call_usd"], limits["meeting_usd"], limits)
        blockers += more
        people = []
        for person in ctx.speakers:
            dynamic = person["position"] == "accountant"
            text = ctx.prompt("opinion", person, spend=PLACEHOLDER_SPEND if dynamic else None)
            sha = _sha(text)
            if not dynamic:
                ctx.expected_sha[person["profile_id"]] = sha
            people.append({**person, "model": person["model_used"], "instructions": ctx.instructions[person["profile_id"]], "prompt": text,
                           "prompt_sha256": sha, "dynamic": dynamic})
        chair = ctx.chair
        chair_text = ctx.prompt("decision", chair, opinions=PLACEHOLDER_OPINIONS)
        out = {"preview_id": None, "startable": not blockers, "blockers": blockers, "topic": topic, "context": context,
               "flags": flags, "task": mt.task_context(task), "participants": people,
               "chair": {**chair, "model": chair["model_used"], "instructions": ctx.instructions[chair["profile_id"]], "prompt": chair_text,
                         "prompt_sha256": _sha(chair_text), "dynamic": True},
               "calls": calls, "reserve_usd": mt.fmt(limits["per_call_usd"] * calls),
               "limits": {k: mt.fmt(v) for k, v in limits.items()}, "today": today,
               "cli": {"version": version, "verified": version is not None},
               "disclosure": DISCLOSURE, "cost_note": COST_NOTE, "rules": [dict(r) for r in rules.RULES]}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "new", "ctx": ctx, "calls": calls})
        return out

    def start(self, preview_id, sources: Sources) -> dict:
        entry = self._take(preview_id, "new")
        ctx: Context = entry["ctx"]
        self._same_cards(ctx.people(), sources)
        binary, version = self._resolve()
        if version != ctx.version:
            raise mt.MeetingError("stale_preview")
        ctx.binary = binary
        limits = mt.limits_from(sources.conf)
        ctx.limits, ctx.daily_usd = limits, limits["daily_usd"]
        if len(mt.meeting_ids()) >= mt.MAX_MEETINGS:
            raise mt.MeetingError("too_many")
        blockers, _ = self._blockers(entry["calls"], limits["per_call_usd"], limits["meeting_usd"], limits, check_lock=False)
        if blockers:
            raise mt.MeetingError("budget")
        fd = self._worker()
        try:
            mid = mt.new_id()
            while mt.MeetingStore(mid).path().exists() or mt.MeetingStore(mid).marker_path().exists():
                mid = mt.new_id()
            rec = mt.new_record(mid, topic=ctx.topic, context=ctx.context, flags=ctx.flags, task_id=ctx.task_id,
                                chair=ctx.chair, speakers=ctx.speakers, limits=limits, now=self.clock(),
                                inputs_sha256=mt.inputs_hash(ctx.task) if ctx.task_id else None)
            store = mt.MeetingStore(rec["id"])
            with store.locked():
                store.save(rec)
        except BaseException:
            os.close(fd)
            raise
        self._launch(rec["id"], ctx, fd)
        return mt.view(rec)

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

    def _launch(self, mid: str, ctx: Context, fd: int) -> None:
        cancel = threading.Event()
        thread = threading.Thread(target=self._work, args=(mid, ctx, cancel, fd), daemon=True, name=f"meeting-{mid}")
        with self.lock:
            self.job = {"meeting_id": mid, "cancel": cancel, "thread": thread}
        thread.start()

    # -- the worker ------------------------------------------------------------------------------------------------

    def _work(self, mid: str, ctx: Context, cancel, fd: int) -> None:
        stop = None
        try:
            while True:
                rec = mt.load(mid)
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
            pass  # the record cannot be read or written: nothing more can be said about this meeting
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

    def _turn(self, mid: str, rec: dict, turn: dict, ctx: Context, cancel) -> str | None:
        """Run one queued turn. Returns what must stop the meeting ("cancelled", "boundary_revoked", "process_unconfirmed")
        or None."""
        seq = turn["seq"]
        who = ctx.who(turn["profile_id"])
        per_call = mt.money(rec["limits"]["per_call_usd"])
        room = mt.money(rec["limits"]["meeting_usd"]) - mt.spent(rec)
        day = mt.daily_spent(self._all(), self.clock())
        if per_call > room or day + per_call > ctx.daily_usd:
            self._end(mid, seq, "skipped", "budget", evidence=None)
            return None
        spend = mt.fmt(mt.spent(rec))
        if turn["kind"] == "decision":
            if not any(t["state"] == "done" for t in rec["turns"] if t["kind"] == "opinion"):
                self._end(mid, seq, "skipped", "no_opinions", evidence=None)
                return None
            prompt = ctx.prompt("decision", who, opinions=_opinions_for_chair(rec, ctx))
        else:
            prompt = ctx.prompt("opinion", who, spend=spend)
        sha = _sha(prompt)
        expected = ctx.expected_sha.get(who["profile_id"])
        attempts = turn["attempts"] + 1
        if turn["kind"] == "opinion" and expected is not None and expected != sha:
            self._end(mid, seq, "failed", "prompt_changed", evidence=None, attempts=attempts)  # never sent
            return None

        def start(r):
            r["turns"][seq - 1].update(state="running", attempts=attempts, started_at=self.clock(), ended_at=None,
                                       prompt_sha256=sha, error_code=None, output=None)
        self._update(mid, start)
        spec = CallSpec(turn["kind"], ctx.binary, ctx.version, who["model_used"],
                        mt.DECISION_SCHEMA if turn["kind"] == "decision" else mt.OPINION_SCHEMA, prompt, per_call)
        previous = turn["evidence"]
        output, code, stop = None, None, None
        try:
            result = self.call(spec, cancel)
            evidence = self._merged(previous, result.evidence, result.cost, per_call)
            try:
                output = (mt.validate_decision(result.output) if turn["kind"] == "decision"
                          else mt.validate_opinion(result.output, who["position"]))
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
            if turn["kind"] == "decision":
                self._record_verdict(mid)
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

    def _record_verdict(self, mid: str) -> None:
        def change(rec):
            rec["major_at_decision"] = rules.evaluate(rec)["major"] or rec.get("major_at_decision") is True
        self._update(mid, change)

    @staticmethod
    def _revoke(version: str) -> None:
        store = tr.BoundaryStore()
        try:
            with store.locked():
                data = store.load()
                data.pop(version, None)
                store.save(data)
        except StoreError:
            pass  # the check is then also unreadable, which already refuses every later meeting

    def wait(self, timeout: float = 10.0) -> None:
        with self.lock:
            job = self.job
        if job is not None:
            job["thread"].join(timeout)

    # -- after a restart -------------------------------------------------------------------------------------------

    def recover(self) -> None:
        """A turn that was running when the console stopped is interrupted, and costs what a call may cost at the most; a
        queued one is interrupted without cost. Nothing is resumed. Only when no other process holds the worker."""
        try:
            fd = headless_cli.acquire_worker(WORKER, check_blocked=False)
        except headless_cli.HeadlessError:
            return
        try:
            for mid in mt.meeting_ids():
                try:
                    rec = mt.load(mid)
                except mt.MeetingError:
                    continue
                if not any(t["state"] in ("queued", "running") for t in rec["turns"]):
                    continue
                self._update(mid, self._interrupt)
        finally:
            os.close(fd)

    def _interrupt(self, rec: dict) -> None:
        per_call = mt.money(rec["limits"]["per_call_usd"])
        for turn in rec["turns"]:
            if turn["state"] not in ("queued", "running"):
                continue
            if turn["state"] == "running":
                turn["evidence"] = self._merged(turn["evidence"], turn["evidence"], None, per_call)
            turn.update(state="blocked" if turn["attempts"] >= mt.MAX_ATTEMPTS else "interrupted", error_code="restart",
                        ended_at=self.clock())

    # -- retry -------------------------------------------------------------------------------------------------------

    def _context_of(self, rec: dict, sources: Sources, binary: str, version: str) -> Context:
        """The context of a meeting that exists, rebuilt from today's cards and task card; MeetingError('changed') when
        either is not what the meeting started from."""
        people = rec["participants"]
        self._same_cards(people, sources, "changed")
        task = None
        if rec.get("task_id"):
            task = sources.task(rec["task_id"])
            if task is None or mt.inputs_hash(task) != rec.get("inputs_sha256"):
                raise mt.MeetingError("changed")
        limits = mt.limits_from(sources.conf)
        chair, speakers = people[-1], people[:-1]
        cards = {p["profile_id"]: sources.profile(p["profile_id"]) for p in people}
        return Context(topic=rec["topic"], context=rec["context"], flags=rec["flags_by_chairman"], task_id=rec.get("task_id"),
                       task=task, progress=mt.progress_summary(task, _flows(sources, rec["task_id"])) if rec.get("task_id") else None,
                       chair=chair, speakers=speakers, instructions={k: _instructions_of(v) for k, v in cards.items()},
                       limits={"per_call_usd": mt.money(rec["limits"]["per_call_usd"]), "meeting_usd": mt.money(rec["limits"]["meeting_usd"]),
                               "daily_usd": limits["daily_usd"]},
                       daily_usd=limits["daily_usd"], version=version, binary=binary)

    def _retry_plan(self, mid: str, seq, sources: Sources) -> tuple[dict, dict, bool]:
        rec = mt.load(mid)
        with self.lock:
            if self.job is not None and self.job["meeting_id"] == mid:
                raise mt.MeetingError("running")
        if rec["chairman"]["state"] in ("approved", "rejected"):
            raise mt.MeetingError("already_decided")
        if type(seq) is not int or not 1 <= seq <= len(rec["turns"]):
            raise mt.MeetingError("bad_request", "seq 必須是這場會議的發言編號")
        turn, last = rec["turns"][seq - 1], rec["turns"][-1]
        if any(t["state"] in ("queued", "running") for t in rec["turns"]):
            raise mt.MeetingError("running")
        if turn["state"] not in mt.RETRYABLE_STATES or turn["attempts"] >= mt.MAX_ATTEMPTS:
            raise mt.MeetingError("not_retryable")
        again = False
        if turn["kind"] == "opinion":
            if last["attempts"] >= mt.MAX_ATTEMPTS and last["state"] != "blocked":
                raise mt.MeetingError("not_retryable")  # a decision that cannot be asked again would stand on an old opinion
            again = last["attempts"] < mt.MAX_ATTEMPTS
        return rec, turn, again

    def retry_preview(self, mid: str, body, sources: Sources) -> dict:
        if not isinstance(body, dict) or set(body) != {"seq"}:
            raise mt.MeetingError("bad_request", "只需要 seq")
        rec, turn, again = self._retry_plan(mid, body["seq"], sources)
        blockers: list = []
        binary, version = self._provider_state(blockers)
        ctx = self._context_of(rec, sources, binary or "", version or "")
        per_call = mt.money(rec["limits"]["per_call_usd"])
        calls = 1 + (1 if again else 0)
        room = mt.money(rec["limits"]["meeting_usd"]) - mt.spent(rec)
        more, today = self._blockers(calls, per_call, room, {**ctx.limits, "daily_usd": ctx.daily_usd})
        blockers += more
        who = ctx.who(turn["profile_id"])
        if turn["kind"] == "decision":
            text = ctx.prompt("decision", who, opinions=_opinions_for_chair(rec, ctx))
        else:
            text = ctx.prompt("opinion", who, spend=PLACEHOLDER_SPEND if who["position"] == "accountant" else None)
        out = {"preview_id": None, "startable": not blockers, "blockers": blockers, "meeting_id": mid, "seq": turn["seq"],
               "participant": {**who, "instructions": ctx.instructions[who["profile_id"]]}, "prompt": text, "prompt_sha256": _sha(text),
               "calls": calls, "reserve_usd": mt.fmt(per_call * calls), "decision_again": again,
               "attempt": turn["attempts"] + 1, "today": today, "cli": {"version": version, "verified": version is not None},
               "disclosure": DISCLOSURE, "cost_note": COST_NOTE}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "retry", "meeting_id": mid, "seq": turn["seq"], "version": version, "calls": calls})
        return out

    def retry(self, preview_id, sources: Sources, meeting_id: str | None = None) -> dict:
        with self.lock:  # a preview named under another meeting's address is refused and is not used up
            seen = self.previews.get(preview_id) if isinstance(preview_id, str) else None
            if seen is not None and meeting_id is not None and seen.get("meeting_id") != meeting_id:
                raise mt.MeetingError("preview_expired")
        entry = self._take(preview_id, "retry")
        mid, seq = entry["meeting_id"], entry["seq"]
        rec, turn, again = self._retry_plan(mid, seq, sources)
        binary, version = self._resolve()
        if version != entry["version"]:
            raise mt.MeetingError("stale_preview")
        ctx = self._context_of(rec, sources, binary, version)
        per_call = mt.money(rec["limits"]["per_call_usd"])
        calls = 1 + (1 if again else 0)
        more, _ = self._blockers(calls, per_call, mt.money(rec["limits"]["meeting_usd"]) - mt.spent(rec),
                                 {**ctx.limits, "daily_usd": ctx.daily_usd}, check_lock=False)
        if more or calls != entry["calls"]:
            raise mt.MeetingError("budget" if more else "stale_preview")
        fd = self._worker()

        def requeue(r):
            for t in ([r["turns"][seq - 1]] + ([r["turns"][-1]] if again else [])):
                t.update(state="queued", error_code=None, output=None, ended_at=None)
        try:
            rec = self._update(mid, requeue)
        except BaseException:
            os.close(fd)
            raise
        # the prompt hash of a speaker was shown in the first preview; a retry shows its own, so none is compared
        self._launch(mid, ctx, fd)
        return mt.view(rec)

    # -- the rest of the API ---------------------------------------------------------------------------------------

    def cancel(self, mid: str) -> dict:
        with self.lock:
            job = self.job
            if job is None or job["meeting_id"] != mid:
                raise mt.MeetingError("not_running")
            job["cancel"].set()
        return mt.view(mt.load(mid))

    def chairman(self, mid: str, body) -> dict:
        if not isinstance(body, dict) or not {"decision"} <= set(body) <= {"decision", "note"} or body["decision"] not in ("approve", "reject"):
            raise mt.MeetingError("bad_request", "decision 必須是 approve 或 reject")
        note = mt.clean_line(body.get("note"), mt.NOTE_MAX, "備註", required=False)
        with self.lock:
            if self.job is not None and self.job["meeting_id"] == mid:
                raise mt.MeetingError("running")

        def change(rec):
            if any(t["state"] in ("queued", "running") for t in rec["turns"]):
                raise mt.MeetingError("running")
            if rec["chairman"]["state"] in ("approved", "rejected"):
                raise mt.MeetingError("already_decided")
            if body["decision"] == "approve":
                if rec["turns"][-1]["state"] != "done":
                    raise mt.MeetingError("not_decided")
                if not mt.view(rec)["major"]:
                    raise mt.MeetingError("not_needed")
            rec["chairman"] = {"state": "approved" if body["decision"] == "approve" else "rejected", "at": self.clock(), "note": note}
        return mt.view(self._update(mid, change))

    def delete(self, mid: str) -> None:
        with self.lock:
            if self.job is not None and self.job["meeting_id"] == mid:
                raise mt.MeetingError("running")
        mt.delete(mid)

    def get(self, mid: str) -> dict:
        return mt.view(mt.load(mid))

    def list(self) -> dict:
        out = []
        for mid in mt.meeting_ids():
            try:
                v = mt.view(mt.load(mid))
            except mt.MeetingError as exc:
                out.append({"id": mid, "blocked": True, "error": str(exc)})
                continue
            out.append({"id": v["id"], "topic": v["topic"], "created_at": v["created_at"], "status": v["status"], "major": v["major"],
                        "chairman_state": v["chairman"]["state"], "spent_usd": v["spent_usd"], "task_id": v.get("task_id"),
                        "participants": len(v["participants"])})
        out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return {"meetings": out}

    def ledger(self, conf) -> dict:
        limits = mt.limits_from(conf)
        day = mt.daily_spent(self._all(), self.clock())
        with self.lock:
            running = self.job["meeting_id"] if self.job else None
        return {"spent_usd": mt.fmt(day), "daily_usd": mt.fmt(limits["daily_usd"]), "per_call_usd": mt.fmt(limits["per_call_usd"]),
                "meeting_usd": mt.fmt(limits["meeting_usd"]), "lamp": mt.lamp(day, limits), "running": running,
                "blocked": (cfg.state_dir() / f"{WORKER}.blocked").exists(), "note": COST_NOTE}
