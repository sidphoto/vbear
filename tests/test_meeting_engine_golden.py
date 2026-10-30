"""The meeting engine's golden values (P35-0).

One synthetic meeting day, run with a fixed clock, fixed meeting ids and a fake call, must give the same prompts (by hash),
the same records (as JSON), the same previews and the same ledger as v0.9.0's meeting runner (6b1d7bd), from which
meeting_engine_golden.json was recorded. The file is not regenerated to make a change pass: a change that is meant to alter
what a meeting sends, keeps or counts says so in its own commit and records new values there.
"""
import hashlib
import json
import os
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import meeting_runner as mr, meetings as mt, translations as tr

GOLDEN = Path(__file__).with_name("meeting_engine_golden.json")
VERSION = "2.1.296"
NOW = 1_893_456_000.0
EVIDENCE = {"cli_version": VERSION, "model_reported": "claude-sonnet-5-5", "tools_reported": ["StructuredOutput"],
            "mcp_servers_reported": [], "exit_code": 0, "duration_ms": 7}
FAILED = dict(EVIDENCE, exit_code=1, duration_ms=3)
UNCLEAN = dict(EVIDENCE, tools_reported=["StructuredOutput", "Bash"])


def _opinion(summary, risks=()):
    return {"stance": "有條件支持", "summary": summary, "points": ["先做首頁", "再看其他頁"], "risks": list(risks),
            "needs_chairman": False}


DECISION = {"decision": "先改首頁按鈕", "rationale": "範圍小、可以回復", "dissent_addressed": ["法務的授權疑慮：只用自己畫的圖"],
            "actions": [{"type": "寫草稿", "text": "寫按鈕的改法"}], "escalate": False, "escalate_reason": "",
            "follow_up_topics": ["其他頁要不要跟著改"]}
LEGAL = _opinion("授權要先確認", [{"level": "中", "text": "圖示的授權不明", "source": ""}])


def _card(pid, position, tool="claude", model_id=""):
    return {"id": pid, "name": f"虛構{pid.upper()}", "profession_role_id": None, "model": {"tool": tool, "model_id": model_id},
            "equipped_skill_ids": [], "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"},
            "enabled": True, "created_at": 1.0, "updated_at": 1.0, "position": position,
            "instructions": f"你是虛構的{position}，只依資料回答。"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FakeCall:
    """Answers each call from a script of steps, and keeps what each call was given (its prompt by hash)."""

    def __init__(self):
        self.steps = []
        self.log = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, spec, cancel):
        self.log.append({"kind": spec.kind, "binary": spec.binary, "version": spec.version, "model": spec.model,
                         "per_call": mt.fmt(spec.per_call), "timeout": spec.timeout,
                         "schema_sha256": _sha(json.dumps(spec.schema, sort_keys=True)),
                         "prompt_sha256": _sha(spec.prompt), "prompt_bytes": len(spec.prompt.encode())})
        step = self.steps.pop(0)
        if step[0] == "hold":
            self.entered.set()
            while not self.release.wait(0.02):
                if cancel.is_set():
                    raise mr.CallFailed("cancelled", dict(EVIDENCE, exit_code=None, duration_ms=None), None)
            step = step[1]
        if step[0] == "fail":
            raise mr.CallFailed(step[1], dict(step[2]), step[3])
        return mr.CallResult(step[1], dict(EVIDENCE), step[2])


def _preview(out: dict) -> dict:
    """What a preview showed: its texts by hash, and in clear what decides whether the meeting may start."""
    masked = dict(out, preview_id=None if out["preview_id"] is None else "kept")
    return {"sha256": _sha(json.dumps(masked, ensure_ascii=False, sort_keys=True)), "preview_id": masked["preview_id"],
            **{k: out[k] for k in ("startable", "blockers", "calls", "reserve_usd", "today", "cli") if k in out},
            "prompts": [p["prompt_sha256"] for p in out.get("participants", [])]
            + [out[k]["prompt_sha256"] for k in ("chair",) if k in out] + ([out["prompt_sha256"]] if "prompt_sha256" in out else []),
            **({"decision_again": out["decision_again"], "attempt": out["attempt"]} if "decision_again" in out else {})}


def run_day(root: Path) -> dict:
    """The synthetic day: every path of the engine a meeting takes, captured as plain JSON."""
    home = root / "home"
    home.mkdir()
    env = {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"}
    ids = iter(f"m-{n:012x}" for n in range(1, 100))
    with mock.patch.dict(os.environ, env), mock.patch.object(mt, "new_id", side_effect=lambda: next(ids)):
        return _run_day()


def _run_day() -> dict:
    out: dict = {}
    profiles = {p["id"]: p for p in (
        _card("ceo", "planner", model_id="claude-opus-5-5"), _card("pm", "pm"), _card("legal", "legal"),
        _card("acct", "accountant"), _card("eng", "executor", tool="codex", model_id="gpt-6-luna"))}
    task = {"id": "t-1", "title": "首頁按鈕改大（虛構）", "goal": "讓按鈕好按", "scope": "只動首頁",
            "workdir": "/nonexistent/synthetic-project", "status": "draft"}
    flows = [{"flow_id": "f-1", "events": [{"kind": "plan"}, {"kind": "review"}]}]

    def sources(**conf):  # a day's limit that the whole synthetic day fits in, unless a case sets its own
        return mr.Sources(profile=profiles.get, task=lambda tid: task if tid == "t-1" else None,
                          flows=lambda tid: flows if tid == "t-1" else [], conf=conf or {"meeting_limits": {"daily_usd": 20}})

    def body(speakers, **kw):
        return {"topic": "要不要把首頁按鈕改大（虛構）", "chair_profile_id": "ceo", "speaker_profile_ids": speakers, **kw}

    call = FakeCall()
    runner = mr.MeetingRunner(provider=lambda engine: ("/nonexistent/claude", VERSION), call=call, clock=lambda: NOW)

    def meet(name, speakers, steps, conf=None, **kw):
        call.steps = list(steps)
        src = sources(**(conf or {}))
        preview = runner.preview(body(speakers, **kw), src)
        started = runner.start(preview["preview_id"], src)
        runner.wait(10)
        out[name] = {"preview": _preview(preview), "started": started, "record": mt.load(started["id"]), "view": runner.get(started["id"])}
        return started["id"]

    def retry(name, mid, seq, steps, conf=None):
        call.steps = list(steps)
        src = sources(**(conf or {}))
        preview = runner.retry_preview(mid, {"seq": seq}, src)
        view = runner.retry(preview["preview_id"], src, mid)
        runner.wait(10)
        out[name] = {"preview": _preview(preview), "started": view, "record": mt.load(mid), "view": runner.get(mid)}

    # every speaker answers (one with no reported cost: the worst case), the CEO decides, a ticked flag makes it major
    full = meet("full", ["pm", "legal", "acct", "eng"],
                [("ok", _opinion("可以做"), Decimal("0.011")), ("ok", LEGAL, None), ("ok", _opinion("花費可控"), Decimal("0.013")),
                 ("ok", _opinion("工程上可行"), Decimal("0.014")), ("ok", DECISION, Decimal("0.05"))],
                context="補充：只動首頁", flags=["spend"], task_id="t-1")
    out["full"]["chairman"] = runner.chairman(full, {"decision": "approve", "note": "照辦（虛構）"})

    # a speaker fails, the CEO is told who did not speak; a retry asks the speaker and the CEO again
    failed = meet("failed", ["pm", "legal"], [("fail", "cli_failed", FAILED, None), ("ok", LEGAL, Decimal("0.02")),
                                              ("ok", DECISION, Decimal("0.03"))])
    retry("failed_retry", failed, 1, [("ok", _opinion("補上發言"), Decimal("0.015")), ("ok", DECISION, Decimal("0.031"))])

    # the decision fails on what it wrote; it is retried on its own
    undecided = meet("undecided", ["pm"], [("ok", _opinion("可以做"), Decimal("0.01")), ("ok", {"a": 1}, Decimal("0.02"))])
    retry("undecided_retry", undecided, 2, [("ok", DECISION, Decimal("0.02"))])

    # the reserve does not fit the meeting; then a turn that would pass the meeting's limit is skipped
    tight = {"meeting_limits": {"per_call_usd": 0.5, "meeting_usd": 1.5, "daily_usd": 9}}
    out["too_big"] = _preview(runner.preview(body(["pm", "legal", "acct", "eng"]), sources(**tight)))
    meet("budget", ["pm", "legal"], [("ok", _opinion("可以做"), Decimal("0.9")), ("ok", LEGAL, Decimal("0.9"))], conf=tight)

    # no opinion at all: the CEO is not asked; a retry that does not fit what is left of the meeting is not startable
    silent = meet("silent", ["pm"], [("fail", "cli_failed", FAILED, None)])
    store = mt.MeetingStore(silent)
    with store.locked():
        rec = store.load()
        rec["limits"]["meeting_usd"] = "0.25"
        store.save(rec)
    out["silent_retry_blocked"] = _preview(runner.retry_preview(silent, {"seq": 1}, sources()))

    # an init with a tool: the version's pass is revoked and the rest is skipped
    boundary = tr.BoundaryStore()
    with boundary.locked():
        boundary.save({VERSION: NOW, "2.1.200": NOW})
    meet("unclean", ["pm", "legal"], [("fail", "tools_not_clean", UNCLEAN, None)])
    out["unclean"]["boundaries"] = sorted(boundary.load())

    # while a call runs: the ledger counts it at the worst case, a new meeting is busy; then it is cancelled
    call.steps = [("hold", ("ok", _opinion("可以做"), Decimal("0.01"))), ("ok", LEGAL, Decimal("0.01")), ("ok", DECISION, Decimal("0.01"))]
    call.entered.clear()
    call.release.clear()
    src = sources()
    held = runner.start(runner.preview(body(["pm", "legal"]), src)["preview_id"], src)
    call.entered.wait(10)
    out["held"] = {"ledger": runner.ledger({}), "view": runner.get(held["id"]),
                   "busy": _preview(runner.preview(body(["pm"]), src))}
    runner.cancel(held["id"])  # what it returns races with the worker: the record after the wait is what is compared
    runner.wait(10)
    out["held"]["record"] = mt.load(held["id"])

    # after a restart: a running turn is interrupted at the worst case (blocked with no attempts left), nothing resumes
    people = [mr.participant(profiles["pm"], "pm"), mr.participant(profiles["legal"], "legal")]
    chair = mr.participant(profiles["ceo"], "planner")
    for mid, running, attempts in (("m-0000000000a1", 2, 1), ("m-0000000000a2", 1, 3)):
        rec = mt.new_record(mid, topic="重啟前的會議（虛構）", context="", flags=[], task_id=None, chair=chair, speakers=people,
                            limits=mt.DEFAULT_LIMITS, now=NOW)
        for t in rec["turns"][:running - 1]:
            t.update(state="done", attempts=1, started_at=NOW, ended_at=NOW, prompt_sha256="b" * 64, output=_opinion("可以做"),
                     evidence=dict(EVIDENCE, cost_usd="0.01", cost_source="cli"))
        rec["turns"][running - 1].update(state="running", attempts=attempts, started_at=NOW, prompt_sha256="c" * 64,
                                         evidence=dict(EVIDENCE, cost_usd="0.03", cost_source="cli") if attempts > 1 else None)
        store = mt.MeetingStore(mid)
        with store.locked():
            store.save(rec)
    restarted = mr.MeetingRunner(provider=lambda engine: ("/nonexistent/claude", VERSION), call=call, clock=lambda: NOW)
    out["recovered"] = {mid: mt.load(mid) for mid in ("m-0000000000a1", "m-0000000000a2")}

    # the day as a whole: the ledger, the list, a red lamp, a delete
    out["ledger"] = restarted.ledger({})
    out["ledger_tight"] = restarted.ledger(tight)
    out["red"] = _preview(restarted.preview(body(["pm"]), sources(meeting_limits={"daily_usd": 1})))
    restarted.delete(silent)
    out["list"] = restarted.list()
    out["calls"] = call.log
    return json.loads(json.dumps(out, ensure_ascii=False, sort_keys=True))


class MeetingEngineGoldenTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-meeting-golden-test-")
        self.addCleanup(self.tmp.cleanup)

    def test_the_day_is_what_v0_9_0_sent_kept_and_counted(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        day = run_day(Path(self.tmp.name))
        self.assertEqual(sorted(day), sorted(golden))
        for key in sorted(golden):  # one section at a time, so that a difference names where it is
            with self.subTest(section=key):
                self.assertEqual(day[key], golden[key])

    def test_the_golden_day_covers_every_path_it_claims(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        states = {t["state"] for part in golden.values() if isinstance(part, dict) and isinstance(part.get("record"), dict)
                  for t in part["record"]["turns"]}
        states |= {t["state"] for rec in golden["recovered"].values() for t in rec["turns"]}
        self.assertEqual(states, {"done", "failed", "skipped", "cancelled", "interrupted", "blocked"})
        codes = {t["error_code"] for part in golden.values() if isinstance(part, dict) and isinstance(part.get("record"), dict)
                 for t in part["record"]["turns"]}
        self.assertTrue({"cli_failed", "invalid_output", "budget", "no_opinions", "tools_not_clean", "boundary_revoked",
                         "cancelled"} <= codes, codes)
        self.assertEqual({c["per_call"] for c in golden["calls"]}, {"0.2", "0.5"})
        self.assertEqual(golden["unclean"]["boundaries"], ["2.1.200"])
        self.assertEqual(golden["held"]["busy"]["blockers"][0]["code"], "busy")
        self.assertTrue(golden["full"]["record"]["major_at_decision"])
        self.assertNotIn("/nonexistent/synthetic-project", json.dumps(golden, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
