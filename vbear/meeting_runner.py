"""Running a meeting (P34-4): the preview the chairman confirms, and what a meeting gives the engine that runs it.

A meeting is held by headless Claude Code calls with no tools, run by board_engine.HeadlessBoard: the call and the check
of its init event, the one worker, the money, the speed (the effort and the clock, meetings.speed_from) and what a restart
leaves are described there. What is a meeting's own:

  * speakers run one after another, never at the same time, and never see each other; then the CEO writes the decision;
  * nothing is retried by itself. A failed turn waits for a person to retry it (twice at most), and the meeting is held
    for the chairman meanwhile (meeting_rules R7);
  * a decision is judged by the major rules (meeting_rules) when it is kept, and the chairman approves only a major one.

The decision is a record. Nothing in this module acts on it: it writes no task card, no flow, no project folder.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import agent_profiles as ap, config as cfg, meeting_rules as rules, meetings as mt, staffing as st
from .board_engine import HeadlessBoard, Sources, _select, _sha, opinions_for_chair, participant
# the names the server and the tests have always found here
from .board_engine import CHECK_ERRORS, WORKER, CallFailed, CallResult, CallSpec, default_call, meeting_argv, model_for  # noqa: F401
from .board_engine import POSITION_LABELS, STATE_LABELS  # noqa: F401

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}\Z")

DISCLOSURE = ("開始後，下面每一段文字會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。VBear 不會把任何文字送到其他地方。"
              "每次發言前，VBear 都會確認這個版本的 Claude Code 沒有任何工具、沒有 MCP；確認不了就不送。")
COST_NOTE = "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。沒有回報時，以每次上限計（最壞情況）。"
PLACEHOLDER_OPINIONS = [{"說明": "各職位的發言，要等他們發言之後才有；CEO 看到的是已通過格式檢查、遮蔽過敏感字串的內容。"}]
PLACEHOLDER_SPEND = "（執行時由 VBear 填入這場會議到目前為止的花費）"


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
    speed: dict = field(default_factory=lambda: dict(mt.DEFAULT_SPEED))

    def people(self) -> list[dict]:
        return self.speakers + [self.chair]

    def who(self, profile_id: str) -> dict:
        return next(p for p in self.people() if p["profile_id"] == profile_id)

    def prompt(self, kind: str, person: dict, *, opinions=None, spend=None) -> str:
        return mt.build_prompt(kind, instructions=self.instructions.get(person["profile_id"]), position=person["position"],
                               topic=self.topic, context=self.context, task=self.task,
                               opinions=opinions, progress=self.progress if person["position"] == "pm" else None,
                               spend=spend if person["position"] == "accountant" else None)


def _flows(sources: Sources, task_id: str) -> list | None:
    try:
        return sources.flows(task_id)
    except Exception:
        return None  # the flow store cannot be read: the PM is told so, not that there are none


def _instructions_of(profile: dict) -> str:
    return ap.instructions_of(profile)["text"] or ""


def _opinions_for_chair(rec: dict, ctx: Context) -> list[dict]:
    return opinions_for_chair(rec, ctx.who, lambda turn: turn["output"])


# ---- the runner ----------------------------------------------------------------------------------------------------

class MeetingRunner(HeadlessBoard):
    final_kind = "decision"
    store_cls = mt.MeetingStore
    room_name = "這場會議"

    # -- what a meeting gives the engine ---------------------------------------------------------------------------

    def ids(self) -> list[str]:
        return mt.meeting_ids()

    def load(self, mid: str) -> dict:
        return mt.load(mid)

    def view(self, rec: dict) -> dict:
        return mt.view(rec)

    def remove(self, mid: str) -> None:
        mt.delete(mid)

    def schema(self, kind: str) -> dict:
        return mt.DECISION_SCHEMA if kind == "decision" else mt.OPINION_SCHEMA

    def validate(self, kind: str, output, who: dict, ctx: Context) -> dict:
        return mt.validate_decision(output) if kind == "decision" else mt.validate_opinion(output, who["position"])

    def prompt(self, kind: str, who: dict, rec: dict, ctx: Context) -> str:
        if kind == "decision":
            return ctx.prompt("decision", who, opinions=_opinions_for_chair(rec, ctx))
        return ctx.prompt("opinion", who, spend=mt.fmt(self.spent(rec)))

    def per_call(self, rec: dict, turn: dict) -> Decimal:
        return mt.per_call_limit(rec, turn)

    def total_limit(self, rec: dict) -> Decimal:
        return mt.money(rec["limits"]["meeting_usd"])

    def decided(self, rec: dict) -> bool:
        return rec["chairman"]["state"] in ("approved", "rejected")

    def on_final(self, mid: str) -> None:
        self._record_verdict(mid)

    def spend_kinds(self) -> list:
        """A meeting shares the day with the staffing meetings (staffing_runner)."""
        return [(self.ids, self.load, self.per_call), (st.record_ids, st.load, st.per_call_of)]

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
        speed = mt.speed_from(sources.conf)  # what the preview shows is what is sent, whatever the config says by then
        ctx = Context(topic=topic, context=context, flags=flags, task_id=task_id, task=task,
                      progress=mt.progress_summary(task, _flows(sources, task_id)) if task_id else None,
                      chair=participant(*chair_card), speakers=[participant(*c) for c in speaker_cards],
                      instructions={c[0]["id"]: _instructions_of(c[0]) for c in [chair_card] + speaker_cards},
                      limits=limits, daily_usd=limits["daily_usd"], version=version or "", binary=binary or "", speed=speed)
        calls = len(ctx.speakers) + 1
        more, today = self._blockers(limits["per_call_usd"] * calls, limits["meeting_usd"], limits)
        blockers += more
        people = []
        for person in ctx.speakers:
            dynamic = person["position"] == "accountant"
            text = ctx.prompt("opinion", person, spend=PLACEHOLDER_SPEND if dynamic else None)
            sha = _sha(text)
            if not dynamic:
                ctx.expected_sha[person["profile_id"]] = sha
            people.append({**person, "model": person["model_used"], "effort": speed["speaker_effort"],
                           "instructions": ctx.instructions[person["profile_id"]], "prompt": text, "prompt_sha256": sha, "dynamic": dynamic})
        chair = ctx.chair
        chair_text = ctx.prompt("decision", chair, opinions=PLACEHOLDER_OPINIONS)
        out = {"preview_id": None, "startable": not blockers, "blockers": blockers, "topic": topic, "context": context,
               "flags": flags, "task": mt.task_context(task), "participants": people,
               "chair": {**chair, "model": chair["model_used"], "effort": speed["chair_effort"],
                         "instructions": ctx.instructions[chair["profile_id"]], "prompt": chair_text,
                         "prompt_sha256": _sha(chair_text), "dynamic": True},
               "calls": calls, "reserve_usd": mt.fmt(limits["per_call_usd"] * calls),
               "limits": {k: mt.fmt(v) for k, v in limits.items()}, "today": today,
               "cli": {"version": version, "verified": version is not None}, "speed": mt.speed_view(speed),
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
        blockers, _ = self._blockers(limits["per_call_usd"] * entry["calls"], limits["meeting_usd"], limits, check_lock=False)
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

    def _record_verdict(self, mid: str) -> None:
        def change(rec):
            rec["major_at_decision"] = rules.evaluate(rec)["major"] or rec.get("major_at_decision") is True
        self._update(mid, change)

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

    def retry_preview(self, mid: str, body, sources: Sources) -> dict:
        if not isinstance(body, dict) or set(body) != {"seq"}:
            raise mt.MeetingError("bad_request", "只需要 seq")
        rec, turn, again = self._retry_plan(mid, body["seq"], sources)
        blockers: list = []
        binary, version = self._provider_state(blockers)
        ctx = self._context_of(rec, sources, binary or "", version or "")
        ctx.speed = speed = mt.speed_from(sources.conf)
        per_call = mt.money(rec["limits"]["per_call_usd"])
        calls = 1 + (1 if again else 0)
        more, today = self._blockers(per_call * calls, self.room(rec), {**ctx.limits, "daily_usd": ctx.daily_usd})
        blockers += more
        who = ctx.who(turn["profile_id"])
        if turn["kind"] == "decision":
            text = ctx.prompt("decision", who, opinions=_opinions_for_chair(rec, ctx))
        else:
            text = ctx.prompt("opinion", who, spend=PLACEHOLDER_SPEND if who["position"] == "accountant" else None)
        out = {"preview_id": None, "startable": not blockers, "blockers": blockers, "meeting_id": mid, "seq": turn["seq"],
               "participant": {**who, "effort": speed["chair_effort" if turn["kind"] == "decision" else "speaker_effort"],
                               "instructions": ctx.instructions[who["profile_id"]]}, "prompt": text, "prompt_sha256": _sha(text),
               "calls": calls, "reserve_usd": mt.fmt(per_call * calls), "decision_again": again,
               "attempt": turn["attempts"] + 1, "today": today, "cli": {"version": version, "verified": version is not None},
               "speed": mt.speed_view(speed), "disclosure": DISCLOSURE, "cost_note": COST_NOTE}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "retry", "meeting_id": mid, "seq": turn["seq"], "version": version, "calls": calls,
                                            "speed": speed})
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
        ctx.speed = entry["speed"]
        per_call = mt.money(rec["limits"]["per_call_usd"])
        calls = 1 + (1 if again else 0)
        more, _ = self._blockers(per_call * calls, self.room(rec), {**ctx.limits, "daily_usd": ctx.daily_usd}, check_lock=False)
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

    def get(self, mid: str) -> dict:
        """A meeting as mt.view shows it, and, while it runs here, its clock (clock_of)."""
        out = mt.view(mt.load(mid))
        clock = self.clock_of(mid)
        if clock is not None:
            out["clock"] = clock
        return out

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
        """The day's money of the meetings and the staffing meetings together (``includes`` says so)."""
        limits = mt.limits_from(conf)
        day = self._day()
        with self.lock:
            running = self.job["meeting_id"] if self.job else None
        return {"spent_usd": mt.fmt(day), "daily_usd": mt.fmt(limits["daily_usd"]), "per_call_usd": mt.fmt(limits["per_call_usd"]),
                "meeting_usd": mt.fmt(limits["meeting_usd"]), "lamp": mt.lamp(day, limits), "running": running,
                "blocked": (cfg.state_dir() / f"{WORKER}.blocked").exists(), "note": COST_NOTE, "includes": ["meetings", "staffing"]}
