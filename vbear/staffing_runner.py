"""Running a staffing meeting (P35-2): the preview the chairman confirms, and what a staffing meeting gives the engine.

A staffing meeting is held by the engine of the meetings (board_engine.HeadlessBoard): headless Claude Code calls with no
tools, the check of each call's init event, the one worker shared with the meetings (so that a meeting and a staffing
meeting never run at the same time), the money, the speed (meetings.speed_from: low or medium effort, a clock with time
kept for the CEO) and what a restart leaves. What is a staffing meeting's own (staffing holds the pure part):

  * it is about one task card. VBear suggests who speaks (staffing.suggest_speakers, a fixed table); a person chooses;
  * every speaker says once, alone, then the CEO writes a staffing proposal from what they said; with no answer at all
    the CEO is not asked;
  * the list of cards and skills is made once, at the preview, at the most bytes that leave the CEO's text within its
    limit whatever the speakers write (staffing.fit_inputs); a start or a retry on a list that is no longer the same is
    refused;
  * the CEO's call has a limit of its own (staffing_limits.proposal_call_usd), and so has the whole record
    (staffing_limits.total_usd); a speaker's call and the day are the meetings' (meeting_limits);
  * no rule of the meetings (R1-R8) is run, and the chairman's answer (adopt or dismiss) is a record of the console that
    does nothing: no card is made, no skill inserted, no one put on a team.

Nothing but the staffing/ folder (and the worker's lock) is written here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from . import agent_profiles as ap, meetings as mt, staffing as st
from .board_engine import CHAIR_POSITION, CHECK_ERRORS, HeadlessBoard, _select, _sha, participant
from .jsonstore import StoreError
from .meeting_runner import COST_NOTE, DISCLOSURE, PLACEHOLDER_OPINIONS, PLACEHOLDER_SPEND, _flows, _instructions_of

PROPOSAL_TIMEOUT = 180.0  # the CEO's call: the whole list and every speaker's answer; also the time kept for the CEO


@dataclass
class StaffingSources:
    """Where a request reads from: the cards and the task cards (as a meeting's Sources), and every card, the skills a
    card can use, and their fresh Chinese summaries by skill id (the server passes the stores; tests pass lists)."""
    profile: Callable[[str], dict | None]
    task: Callable[[str], dict | None]
    flows: Callable[[str], list]
    profiles: Callable[[], list]
    skills: Callable[[], list]
    summaries: Callable[[], dict]
    conf: dict = field(default_factory=dict)


@dataclass
class Context:
    """Everything a staffing meeting's prompts are made from; for a new one it is what the preview showed."""
    task_id: str
    task: dict
    note: str
    inputs: dict
    list_max: int
    progress: str | None
    chair: dict
    speakers: list
    instructions: dict
    suggested: list
    limits: dict
    daily_usd: Decimal
    version: str
    binary: str
    expected_sha: dict = field(default_factory=dict)
    speed: dict = field(default_factory=lambda: dict(mt.DEFAULT_SPEED))
    spoke: set = field(default_factory=set)  # the positions whose answer the CEO is given (set when the CEO's text is made)

    def people(self) -> list[dict]:
        return self.speakers + [self.chair]

    def who(self, profile_id: str) -> dict:
        return next(p for p in self.people() if p["profile_id"] == profile_id)

    def prompt(self, kind: str, person: dict, *, opinions=None, spend=None) -> str:
        return st.build_prompt(kind, instructions=self.instructions.get(person["profile_id"]), position=person["position"],
                               task=self.task, note=self.note, inputs=self.inputs, opinions=opinions,
                               progress=self.progress if person["position"] == "pm" else None,
                               spend=spend if person["position"] == "accountant" else None)


def _reserve(limits: dict, speakers: int) -> Decimal:
    """What a new staffing meeting reserves: every speaker's call and the CEO's, each at its own limit."""
    return limits["per_call_usd"] * speakers + limits["proposal_call_usd"]


class StaffingRunner(HeadlessBoard):
    final_kind = "proposal"
    store_cls = st.StaffingStore
    room_name = "這份組隊提案"
    error_cls = st.StaffingError

    # -- what a staffing meeting gives the engine ------------------------------------------------------------------

    def ids(self) -> list[str]:
        return st.record_ids()

    def load(self, sid: str) -> dict:
        return st.load(sid)

    def view(self, rec: dict) -> dict:
        return st.view(rec)

    def remove(self, sid: str) -> None:
        st.delete(sid)

    def schema(self, kind: str) -> dict:
        return st.PROPOSAL_SCHEMA if kind == "proposal" else st.STAFF_OPINION_SCHEMA

    def validate(self, kind: str, output, who: dict, ctx: Context) -> dict:
        if kind == "proposal":
            return st.validate_proposal(output, ctx.inputs, ctx.spoke)
        return st.validate_opinion(output, who["position"], ctx.inputs)

    def prompt(self, kind: str, who: dict, rec: dict, ctx: Context) -> str:
        if kind == "proposal":
            ctx.spoke = {ctx.who(t["profile_id"])["position"] for t in rec["turns"] if t["kind"] == "opinion" and t["state"] == "done"}
            return ctx.prompt("proposal", who, opinions=st.chair_opinions(rec, ctx.who))
        return ctx.prompt("opinion", who, spend=mt.fmt(self.spent(rec)))

    def per_call(self, rec: dict, turn: dict) -> Decimal:
        return st.per_call_of(rec, turn)

    def total_limit(self, rec: dict) -> Decimal:
        return mt.money(rec["limits"]["total_usd"])

    def decided(self, rec: dict) -> bool:
        return rec["chairman"]["state"] in ("adopted", "dismissed")

    def timeout(self, kind: str) -> float:
        return PROPOSAL_TIMEOUT if kind == "proposal" else mt.CALL_TIMEOUT

    def spend_kinds(self) -> list:
        """A staffing meeting shares the day with the meetings."""
        return [(mt.meeting_ids, mt.load, mt.per_call_limit), (self.ids, self.load, self.per_call)]

    def _provider_error(self, code: str) -> mt.MeetingError:
        # the tool-less check's record, not a staffing record, is what cannot be read
        return st.StaffingError(code, CHECK_ERRORS["storage"] if code == "storage" else None)

    # -- the list --------------------------------------------------------------------------------------------------

    @staticmethod
    def _task(task_id, sources: StaffingSources) -> dict:
        if not isinstance(task_id, str) or not st.TASK_ID_RE.match(task_id):
            raise st.StaffingError("bad_request", "task_id 不符格式")
        task = sources.task(task_id)
        if task is None:
            raise st.StaffingError("not_found", "找不到這張任務卡")
        return task

    @staticmethod
    def _fit(task: dict, sources: StaffingSources, instructions: str, note: str, speakers: list[dict]) -> tuple[int, dict]:
        return st.fit_inputs(task, sources.profiles(), sources.skills(), summaries=sources.summaries(), instructions=instructions,
                             note=note, speakers=speakers)

    # -- who VBear suggests ----------------------------------------------------------------------------------------

    def suggest(self, task_id, sources: StaffingSources) -> dict:
        """Who VBear ticks for a staffing meeting on this task card and why, the task's categories, and the cards that
        may chair it. Read only: nothing is sent, run or written."""
        task = self._task(task_id, sources)
        profiles = [p for p in sources.profiles() if isinstance(p, dict) and isinstance(p.get("id"), str)]
        names = {p["id"]: str(p.get("name") or "") for p in profiles}
        return {"task_id": task_id, "categories": st.task_categories(task),
                "suggested": [{**s, "name": names[s["profile_id"]]} for s in st.suggest_speakers(task, profiles)],
                "chairs": [{"profile_id": p["id"], "name": names[p["id"]]} for p in profiles
                           if p.get("enabled") is not False and ap.position_of(p) == CHAIR_POSITION]}

    # -- a new staffing meeting ------------------------------------------------------------------------------------

    def preview(self, body, sources: StaffingSources) -> dict:
        allowed = {"task_id", "chair_profile_id", "speaker_profile_ids", "note"}
        if not isinstance(body, dict) or set(body) - allowed or not allowed - {"note"} <= set(body):
            raise st.StaffingError("bad_request", "組隊要求的欄位不符")
        task = self._task(body["task_id"], sources)
        note = mt.clean_line(body.get("note"), st.NOTE_MAX, "補充說明", required=False)
        chair_card, speaker_cards = _select(sources, body["chair_profile_id"], body["speaker_profile_ids"])
        if len(st.record_ids()) >= st.MAX_RECORDS:
            raise st.StaffingError("too_many")
        limits = st.limits_from(sources.conf)
        speed = mt.speed_from(sources.conf)  # what the preview shows is what is sent, whatever the config says by then
        blockers: list = []
        binary, version = self._provider_state(blockers)
        chair, speakers = participant(*chair_card), [participant(*c) for c in speaker_cards]
        instructions = {c[0]["id"]: _instructions_of(c[0]) for c in [chair_card] + speaker_cards}
        list_max, inputs = self._fit(task, sources, instructions[chair["profile_id"]], note, speakers)
        profiles = [p for p in sources.profiles() if isinstance(p, dict) and isinstance(p.get("id"), str)]
        ctx = Context(task_id=body["task_id"], task=task, note=note, inputs=inputs, list_max=list_max,
                      progress=mt.progress_summary(task, _flows(sources, body["task_id"])), chair=chair, speakers=speakers,
                      instructions=instructions, suggested=st.suggest_speakers(task, profiles), limits=limits,
                      daily_usd=limits["daily_usd"], version=version or "", binary=binary or "", speed=speed)
        reserve = _reserve(limits, len(speakers))
        more, today = self._blockers(reserve, limits["total_usd"], limits)
        blockers += more
        people = []
        for person in speakers:
            dynamic = person["position"] == "accountant"
            text = ctx.prompt("opinion", person, spend=PLACEHOLDER_SPEND if dynamic else None)
            sha = _sha(text)
            if not dynamic:
                ctx.expected_sha[person["profile_id"]] = sha
            people.append({**person, "model": person["model_used"], "effort": speed["speaker_effort"],
                           "instructions": instructions[person["profile_id"]], "prompt": text, "prompt_sha256": sha, "dynamic": dynamic})
        chair_text = ctx.prompt("proposal", chair, opinions=PLACEHOLDER_OPINIONS)
        names = {p["id"]: str(p.get("name") or "") for p in profiles}
        chosen = {p["profile_id"] for p in speakers}
        out = {"preview_id": None, "startable": not blockers, "blockers": blockers, "task_id": body["task_id"], "note": note,
               "task": mt.task_context(task), "categories": st.task_categories(task),
               "suggested": [{**s, "name": names.get(s["profile_id"], ""), "chosen": s["profile_id"] in chosen} for s in ctx.suggested],
               "list": {"list_max": list_max, "cards": len(inputs["cards"]), "skills": len(inputs["skills"]),
                        "omitted": dict(inputs["omitted"])},
               "participants": people,
               "chair": {**chair, "model": chair["model_used"], "effort": speed["chair_effort"],
                         "instructions": instructions[chair["profile_id"]], "prompt": chair_text, "prompt_sha256": _sha(chair_text),
                         "dynamic": True},
               "calls": len(speakers) + 1, "reserve_usd": mt.fmt(reserve),
               "reserve": {"speakers": len(speakers), "per_call_usd": mt.fmt(limits["per_call_usd"]),
                           "proposal_call_usd": mt.fmt(limits["proposal_call_usd"])},
               "limits": {k: mt.fmt(v) for k, v in limits.items()}, "today": today,
               "cli": {"version": version, "verified": version is not None}, "speed": mt.speed_view(speed),
               "disclosure": DISCLOSURE, "cost_note": COST_NOTE}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "new", "ctx": ctx})
        return out

    def start(self, preview_id, sources: StaffingSources) -> dict:
        entry = self._take(preview_id, "new")
        ctx: Context = entry["ctx"]
        self._same_cards(ctx.people(), sources)
        task = sources.task(ctx.task_id)  # the list made again at the same size must be the one previewed
        if task is None or st.build_inputs(task, sources.profiles(), sources.skills(), summaries=sources.summaries(),
                                           list_max=ctx.list_max)["inputs_sha256"] != ctx.inputs["inputs_sha256"]:
            raise st.StaffingError("stale_preview")
        binary, version = self._resolve()
        if version != ctx.version:
            raise st.StaffingError("stale_preview")
        ctx.binary = binary
        limits = st.limits_from(sources.conf)
        ctx.limits, ctx.daily_usd = limits, limits["daily_usd"]
        if len(st.record_ids()) >= st.MAX_RECORDS:
            raise st.StaffingError("too_many")
        blockers, _ = self._blockers(_reserve(limits, len(ctx.speakers)), limits["total_usd"], limits, check_lock=False)
        if blockers:
            raise st.StaffingError("budget")
        fd = self._worker()
        try:
            sid = st.new_id()
            while st.StaffingStore(sid).path().exists() or st.StaffingStore(sid).marker_path().exists():
                sid = st.new_id()
            rec = st.new_record(sid, task_id=ctx.task_id, note=ctx.note, chair=ctx.chair, speakers=ctx.speakers,
                                suggested=ctx.suggested, sent=st.sent_of(ctx.inputs), limits=limits, now=self.clock())
            store = st.StaffingStore(sid)
            with store.locked():
                store.save(rec)
        except StoreError as exc:
            os.close(fd)
            raise st.StaffingError("storage", str(exc)) from None
        except BaseException:
            os.close(fd)
            raise
        self._launch(sid, ctx, fd)
        return st.view(rec)

    # -- retry -------------------------------------------------------------------------------------------------------

    def _context_of(self, rec: dict, sources: StaffingSources, binary: str, version: str) -> Context:
        """The context of a staffing meeting that exists, rebuilt from today's cards, skills and task card;
        StaffingError('changed') when the speakers, the CEO or the list are not what it started from."""
        people = rec["participants"]
        self._same_cards(people, sources, "changed")
        task = sources.task(rec["task_id"])
        if task is None:
            raise st.StaffingError("changed")
        chair, speakers = people[-1], people[:-1]
        instructions = {p["profile_id"]: _instructions_of(sources.profile(p["profile_id"])) for p in people}
        try:
            list_max, inputs = self._fit(task, sources, instructions[chair["profile_id"]], rec["note"], speakers)
        except st.StaffingError:
            raise st.StaffingError("changed") from None
        if st.sent_of(inputs) != rec["sent"]:
            raise st.StaffingError("changed")
        daily = st.limits_from(sources.conf)["daily_usd"]
        limits = {**{k: mt.money(rec["limits"][k]) for k in st.DEFAULT_LIMITS}, "daily_usd": daily}
        return Context(task_id=rec["task_id"], task=task, note=rec["note"], inputs=inputs, list_max=list_max,
                       progress=mt.progress_summary(task, _flows(sources, rec["task_id"])), chair=chair, speakers=speakers,
                       instructions=instructions, suggested=rec["suggested"], limits=limits, daily_usd=daily,
                       version=version, binary=binary)

    def _retry_reserve(self, rec: dict, turn: dict, again: bool) -> Decimal:
        return self.per_call(rec, turn) + (self.per_call(rec, rec["turns"][-1]) if again else Decimal(0))

    def retry_preview(self, sid: str, body, sources: StaffingSources) -> dict:
        if not isinstance(body, dict) or set(body) != {"seq"}:
            raise st.StaffingError("bad_request", "只需要 seq")
        rec, turn, again = self._retry_plan(sid, body["seq"], sources)
        blockers: list = []
        binary, version = self._provider_state(blockers)
        ctx = self._context_of(rec, sources, binary or "", version or "")
        ctx.speed = speed = mt.speed_from(sources.conf)
        reserve = self._retry_reserve(rec, turn, again)
        more, today = self._blockers(reserve, self.room(rec), ctx.limits)
        blockers += more
        who = ctx.who(turn["profile_id"])
        if turn["kind"] == "proposal":
            text = self.prompt("proposal", who, rec, ctx)
        else:
            text = ctx.prompt("opinion", who, spend=PLACEHOLDER_SPEND if who["position"] == "accountant" else None)
        calls = 2 if again else 1
        out = {"preview_id": None, "startable": not blockers, "blockers": blockers, "staffing_id": sid, "seq": turn["seq"],
               "participant": {**who, "effort": speed["chair_effort" if turn["kind"] == "proposal" else "speaker_effort"],
                               "instructions": ctx.instructions[who["profile_id"]]}, "prompt": text, "prompt_sha256": _sha(text),
               "calls": calls, "reserve_usd": mt.fmt(reserve), "proposal_again": again, "attempt": turn["attempts"] + 1,
               "today": today, "cli": {"version": version, "verified": version is not None}, "speed": mt.speed_view(speed),
               "disclosure": DISCLOSURE, "cost_note": COST_NOTE}
        if not blockers:
            out["preview_id"] = self._keep({"kind": "retry", "meeting_id": sid, "seq": turn["seq"], "version": version,
                                            "calls": calls, "speed": speed})
        return out

    def retry(self, preview_id, sources: StaffingSources, staffing_id: str | None = None) -> dict:
        with self.lock:  # a preview named under another record's address is refused and is not used up
            seen = self.previews.get(preview_id) if isinstance(preview_id, str) else None
            if seen is not None and staffing_id is not None and seen.get("meeting_id") != staffing_id:
                raise st.StaffingError("preview_expired")
        entry = self._take(preview_id, "retry")
        sid, seq = entry["meeting_id"], entry["seq"]
        rec, turn, again = self._retry_plan(sid, seq, sources)
        binary, version = self._resolve()
        if version != entry["version"]:
            raise st.StaffingError("stale_preview")
        ctx = self._context_of(rec, sources, binary, version)
        ctx.speed = entry["speed"]
        more, _ = self._blockers(self._retry_reserve(rec, turn, again), self.room(rec), ctx.limits, check_lock=False)
        if more or (2 if again else 1) != entry["calls"]:
            raise st.StaffingError("budget" if more else "stale_preview")
        fd = self._worker()

        def requeue(r):
            for t in ([r["turns"][seq - 1]] + ([r["turns"][-1]] if again else [])):
                t.update(state="queued", error_code=None, output=None, ended_at=None)
        try:
            rec = self._update(sid, requeue)
        except BaseException:
            os.close(fd)
            raise
        # the prompt hash of a speaker was shown in the first preview; a retry shows its own, so none is compared
        self._launch(sid, ctx, fd)
        return st.view(rec)

    # -- the rest of the API ---------------------------------------------------------------------------------------

    def chairman(self, sid: str, body) -> dict:
        """The chairman's answer to the proposal, adopt or dismiss, with a note: a record of the console, nothing more."""
        if (not isinstance(body, dict) or not {"decision"} <= set(body) <= {"decision", "note"}
                or body["decision"] not in ("adopt", "dismiss")):
            raise st.StaffingError("bad_request", "decision 必須是 adopt 或 dismiss")
        note = mt.clean_line(body.get("note"), st.NOTE_MAX, "備註", required=False)
        with self.lock:
            if self.job is not None and self.job["meeting_id"] == sid:
                raise st.StaffingError("running")

        def change(rec):
            if any(t["state"] in ("queued", "running") for t in rec["turns"]):
                raise st.StaffingError("running")
            if self.decided(rec):
                raise st.StaffingError("already_decided")
            if body["decision"] == "adopt" and rec["turns"][-1]["state"] != "done":
                raise st.StaffingError("not_decided")
            rec["chairman"] = {"state": "adopted" if body["decision"] == "adopt" else "dismissed", "at": self.clock(),
                               "note": note, "adopted": None}
        return st.view(self._update(sid, change))

    def get(self, sid: str, sources: StaffingSources | None = None) -> dict:
        """A staffing record as staffing.view shows it (with the cards changed since, when ``sources`` is given), and,
        while it runs here, its clock."""
        out = st.view(st.load(sid), sources.profile if sources is not None else None)
        clock = self.clock_of(sid)
        if clock is not None:
            out["clock"] = clock
        return out

    def list(self, task_id: str | None = None) -> dict:
        """Every staffing record, or those of one task card; a damaged one is listed, blocked, whatever its task."""
        out = []
        for sid in st.record_ids():
            try:
                v = st.view(st.load(sid))
            except mt.MeetingError as exc:
                out.append({"id": sid, "blocked": True, "error": str(exc)})
                continue
            if task_id is not None and v["task_id"] != task_id:
                continue
            out.append({"id": v["id"], "task_id": v["task_id"], "created_at": v["created_at"], "status": v["status"],
                        "chairman_state": v["chairman"]["state"], "spent_usd": v["spent_usd"], "high_risk": v["high_risk"],
                        "participants": len(v["participants"])})
        out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return {"staffing": out}
