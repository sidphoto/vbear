#!/usr/bin/env python3
"""A publishable summary of one s3_real_e2e run, read from the dedicated state directory right after the run (the
next run cleans it).

A WHITELIST, not a copy: every value is either a number, a boolean, a member of a fixed set, or a name that matched
a strict pattern; nothing else is written. No free text of any kind (no error message, no reason sentence, no path,
no user name, no timestamp, no model word, no account value): when something went wrong the summary says only that
there is an error, and the local result file has it.

    python3 tools/s3_run_summary.py <run directory under _sandbox/e2e-real>
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "_sandbox" / "vbear-home"

SCENARIOS = {"dry", "full", "stop", "restart"}
VERDICTS = {"PASS", "NEEDS WORK", "BLOCKED"}
REVIEW_STATES = {"prepared", "launching", "running", "finished", "invalid", "manual_review", "cleaned"}
REVIEW_OUTCOMES = {"valid", "invalid", "manual_review", None}
SOURCES = {"console", "automation"}
ANOMALY_REASONS = {"unknown_type", "extra_fields"}
REPORT_STATUS = {"done", "blocked", "needs_input", None}
REPORT_TESTS = {"passed", "failed", "not_run", None}
LIMIT_NAMES = {"max_reviews", "max_dispatches", "review_max_responses", "executor_turn_max_responses",
               "executor_total_max_responses", "review_timeout_min", "executor_turn_timeout_min", "max_elapsed_h",
               "executor_budget_usd"}
# the names of the driver's assertions (tests/test_s3_run_summary.py checks that this set holds every one of them)
ASSERTIONS = {
    "the loop ended at the merge gate", "a NEEDS WORK came before the PASS",
    "every review is valid, complete and cleaned", "one dispatch per review round",
    "no dispatch id was used twice", "no review round was started twice", "no review job was started twice",
    "every automatic event is marked as the automation's own", "a review was running when the stop was pressed",
    "the flow is held", "the review's process was cleaned up", "the stopped review is not a valid review",
    "nothing was dispatched or reviewed after the stop", "the flow did not resume by itself",
    "a review was running when the console was restarted", "the daemon kept running while the console was down",
    "the last verdict is PASS",
}
NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}\Z")
KIND_RE = re.compile(r"^[a-z_]{1,40}\Z")
EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9_]+(/[A-Za-z0-9_]+)?\Z")
MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\Z")
VERSION_RE = re.compile(r"^[0-9]{1,4}(\.[0-9]{1,4}){1,2}\Z")
EVENT_KIND_RE = re.compile(r"^(auto_[a-z_]{1,40}|automation_mode|risk_acknowledged)\Z")


def num(v, *, kind=float):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return kind(round(v, 4)) if kind is float else int(v)


def boolean(v):
    return v if isinstance(v, bool) else None


def member(v, allowed):
    return v if (v is None or isinstance(v, str)) and v in allowed else "?"


def ident(v, pattern=NAME_RE):
    return v if isinstance(v, str) and pattern.match(v) else "?"


def ints(d, names):
    d = d if isinstance(d, dict) else {}
    return {n: num(d.get(n), kind=int) for n in names}


def summarize(run: Path, state: Path = STATE) -> dict:
    result = json.loads((run / "result.json").read_text())
    out: dict = {
        "scenario": member(result.get("scenario"), SCENARIOS), "passed": boolean(result.get("passed")),
        "has_error": bool(result.get("error")),                      # the text stays in the local result file
        "wall_seconds": num(result.get("wall_seconds")),
        "cleanup_problem_count": len(result.get("cleanup_problems") or []),
        "clean": boolean(result.get("clean")),
        "real_state_unchanged": boolean(result.get("real_state_unchanged")),
        "leftover_process_count": len(result.get("leftover_processes") or []),
        "open_real_state_file_count": len(result.get("open_files_touching_real_state") or []),
        "limits": {k: num((result.get("limits") or {}).get(k)) for k in sorted(LIMIT_NAMES)},
        "verdicts": [member(v, VERDICTS) for v in (result.get("verdicts") or [])][:20],
        "counts": ints(result.get("counts"), ("dispatches", "review_rounds", "review_jobs")),
        "assertions": [{"name": a["name"] if a.get("name") in ASSERTIONS else "?", "ok": boolean(a.get("ok"))}
                       for a in (result.get("assertions") or []) if isinstance(a, dict)][:40],
    }
    stop = result.get("stop") if isinstance(result.get("stop"), dict) else {}
    out["stop"] = {"review_round": num(stop.get("review_round"), kind=int),
                   "still_running_when_stopped": boolean(stop.get("still_running_when_stopped")),
                   "held": boolean(stop.get("held")),
                   "review_ended_after_s": num(stop.get("review_ended_after_s")),
                   "events_after_the_stop": len(stop.get("kinds_after_the_stop") or [])}
    rs = result.get("restart") if isinstance(result.get("restart"), dict) else {}
    out["restart"] = {"review_round": num(rs.get("review_round"), kind=int),
                      "still_running": boolean(rs.get("still_running")),
                      "daemon_alive_while_console_down": boolean(rs.get("daemon_alive_while_console_down")),
                      "console_exit_code": num(rs.get("console_exit_code"), kind=int)}
    sessions = []
    for j in sorted(glob.glob(str(state / "sessions" / "l-*" / "journal.jsonl"))):
        kinds: dict[str, int] = {}
        anomalies, denials, turns = [], [], []
        for line in Path(j).read_text().splitlines():
            r = json.loads(line)
            kind = ident(r.get("kind"), KIND_RE)
            kinds[kind] = kinds.get(kind, 0) + 1
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            if r.get("kind") == "turn_anomaly":
                anomalies.append({"reason": member(d.get("reason"), ANOMALY_REASONS),
                                  "event_type": ident(d.get("event_type"), EVENT_TYPE_RE),
                                  "fields": [ident(x) for x in (d.get("fields") or [])][:16]})
            elif r.get("kind") == "permission_denied":
                denials.append({"tool_name": ident(d.get("tool_name")), "reason_type": ident(d.get("reason_type"))})
            elif r.get("kind") == "turn_result":
                so = d.get("structured_output") if isinstance(d.get("structured_output"), dict) else {}
                tests = so.get("tests") if isinstance(so.get("tests"), dict) else {}
                turns.append({"subtype": ident(d.get("subtype"), KIND_RE), "num_turns": num(d.get("num_turns"), kind=int),
                              "total_cost_usd": num(d.get("total_cost_usd")),
                              "responses": len({a.get("request_id") for a in (d.get("assistant_events") or [])
                                                if isinstance(a, dict)}),
                              "tool_calls": len(d.get("tool_calls") or []),
                              "report_status": member(so.get("status"), REPORT_STATUS),
                              "report_tests": member(tests.get("result"), REPORT_TESTS)})
        sessions.append({"fact_kinds": kinds, "anomalies": anomalies, "permission_denied": denials, "turns": turns,
                         "responses": sum(t["responses"] for t in turns),
                         "final_cost_usd": turns[-1]["total_cost_usd"] if turns else None})
    out["sessions"] = sessions
    reviews = []
    for m in sorted(glob.glob(str(state / "reviews" / "r-*" / "manifest.json"))):
        d = json.loads(Path(m).read_text())
        reviews.append({"round": num(d.get("round"), kind=int), "state": member(d.get("state"), REVIEW_STATES),
                        "outcome": member(d.get("outcome"), REVIEW_OUTCOMES),
                        "model": ident(d.get("model"), MODEL_RE), "codex_version": ident(d.get("codex_version"), VERSION_RE),
                        "exit_code": num(d.get("exit_code"), kind=int),
                        "invalid_reason_count": len(d.get("invalid_reasons") or [])})
    out["reviews"] = reviews
    snap = run / "snapshot-final.json"
    if snap.exists():
        flow = json.loads(snap.read_text())
        view = flow.get("flow") if isinstance(flow.get("flow"), dict) else {}
        ev = (view.get("flow") or view).get("events") if isinstance(view.get("flow") or view, dict) else None
        out["events"] = [{"seq": num(e.get("seq"), kind=int), "source": member(e.get("source"), SOURCES),
                          "kind": ident(e.get("kind"), EVENT_KIND_RE),
                          "round": num(e.get("round"), kind=int) if "round" in e else None,
                          "verdict": member(e.get("verdict"), VERDICTS) if "verdict" in e else None,
                          "reason_code": ident(e.get("reason_code"), KIND_RE) if "reason_code" in e else None}
                         for e in (ev or []) if isinstance(e, dict) and EVENT_KIND_RE.match(str(e.get("kind", "")))][:80]
        acc = (flow.get("executor") or {}).get("accounting") if isinstance(flow.get("executor"), dict) else None
        out["accounting"] = ints(acc, ("dispatches", "responses", "reviews")) | {
            "spent_usd": num((acc or {}).get("spent_usd")), "elapsed_s": num((acc or {}).get("elapsed_s"))}
    return out


def main() -> int:
    run = Path(sys.argv[1])
    out = summarize(run)
    (run / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out.get(k) for k in ("scenario", "passed", "has_error", "verdicts", "counts", "accounting",
                                              "reviews")}, ensure_ascii=False, indent=1))
    print("sessions:", json.dumps([{k: s[k] for k in ("anomalies", "permission_denied", "responses",
                                                      "final_cost_usd")} for s in out["sessions"]],
                                  ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
