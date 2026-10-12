#!/usr/bin/env python3
"""A compact, publishable summary of one s3_real_e2e run, read from the dedicated state directory right after the
run (the next run cleans it): journal fact kinds, anomaly field names, refused tool calls (names only), costs and
counts, review outcomes. No model words, no paths, no account values.

    python3 tools/s3_run_summary.py <run directory under _sandbox/e2e-real>
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "_sandbox" / "vbear-home"


def main() -> int:
    run = Path(sys.argv[1])
    result = json.loads((run / "result.json").read_text())
    out: dict = {"scenario": result.get("scenario"), "passed": result.get("passed"), "error": result.get("error"),
                 "wall_seconds": result.get("wall_seconds"), "assertions": result.get("assertions"),
                 "verdicts": result.get("verdicts"), "counts": result.get("counts"), "clean": result.get("clean"),
                 "cleanup_problems": result.get("cleanup_problems"),
                 "real_state_unchanged": result.get("real_state_unchanged"),
                 "leftover_processes": len(result.get("leftover_processes") or []),
                 "open_files_touching_real_state": len(result.get("open_files_touching_real_state") or []),
                 "limits": result.get("limits"), "stop": result.get("stop"), "restart": result.get("restart")}
    sessions = []
    for j in sorted(glob.glob(str(STATE / "sessions" / "l-*" / "journal.jsonl"))):
        kinds: dict[str, int] = {}
        anomalies, denials, turns = [], [], []
        for line in open(j):
            r = json.loads(line)
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
            d = r.get("data") or {}
            if r["kind"] == "turn_anomaly":
                anomalies.append({"reason": d.get("reason"), "event_type": d.get("event_type"),
                                  "fields": d.get("fields")})
            elif r["kind"] == "permission_denied":
                denials.append({"tool_name": d.get("tool_name"), "reason_type": d.get("reason_type")})
            elif r["kind"] == "turn_result":
                turns.append({"subtype": d.get("subtype"), "num_turns": d.get("num_turns"),
                              "total_cost_usd": d.get("total_cost_usd"),
                              "responses": len({a["request_id"] for a in d.get("assistant_events", [])}),
                              "tool_calls": len(d.get("tool_calls", [])),
                              "report_status": (d.get("structured_output") or {}).get("status"),
                              "report_tests": ((d.get("structured_output") or {}).get("tests") or {}).get("result")})
        sessions.append({"fact_kinds": kinds, "anomalies": anomalies, "permission_denied": denials, "turns": turns,
                         "final_cost_usd": turns[-1]["total_cost_usd"] if turns else None,
                         "responses": sum(t["responses"] for t in turns)})
    out["sessions"] = sessions
    reviews = []
    for m in sorted(glob.glob(str(STATE / "reviews" / "r-*" / "manifest.json"))):
        d = json.loads(open(m).read())
        reviews.append({k: d.get(k) for k in ("round", "state", "outcome", "model", "codex_version", "exit_code",
                                              "invalid_reasons", "created", "ended_at")})
    out["reviews"] = reviews
    flow = None
    for p in sorted(glob.glob(str(run / "snapshot-final.json"))):
        flow = json.loads(open(p).read())
    if flow:
        ev = flow.get("flow", {}).get("flow", {}).get("events") or flow.get("flow", {}).get("events") or []
        out["events"] = [{"seq": e.get("seq"), "source": e.get("source"), "kind": e.get("kind"),
                          **{k: e[k] for k in ("round", "verdict", "reason_code") if k in e}}
                         for e in ev if str(e.get("kind", "")).startswith("auto_")
                         or e.get("kind") in ("automation_mode", "risk_acknowledged")]
        acc = (flow.get("executor") or {}).get("accounting") or {}
        out["accounting"] = {k: acc.get(k) for k in ("dispatches", "responses", "spent_usd", "reviews", "elapsed_s")}
    (run / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("scenario", "passed", "verdicts", "counts", "accounting", "reviews")},
                     ensure_ascii=False, indent=1))
    print("sessions:", json.dumps([{k: s[k] for k in ("anomalies", "permission_denied", "responses",
                                                      "final_cost_usd")} for s in sessions], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
