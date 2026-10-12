"""tools/s3_run_summary.py is a whitelist: whatever free text a result file, a journal or a manifest holds, none of
it reaches the summary (it is published)."""

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_under_test", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HOSTILE = ("/Users/someone/projects/secret-project", "someone@example.invalid", "a very long sentence about the "
           "user's private matters and a path /home/x/y that must never be published " * 3, "SECRET-TOKEN-1234")


class WhitelistTests(unittest.TestCase):
    def setUp(self):
        self.m = load("s3_run_summary")
        self.tmp = Path(tempfile.mkdtemp(prefix="vbsum-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run = self.tmp / "run"
        self.state = self.tmp / "state"
        self.run.mkdir()
        (self.state / "sessions" / "l-0123456789abcdef").mkdir(parents=True)
        (self.state / "reviews" / "r-0123456789abcdef").mkdir(parents=True)

    def write(self, result=None, journal=None, manifest=None, snapshot=None):
        h1, h2, h3, h4 = HOSTILE
        base = {"scenario": "full", "passed": False, "error": f"AssertionError: {h1} {h3}", "wall_seconds": 12.5,
                "cleanup_problems": [h1, h2], "clean": False, "real_state_unchanged": True,
                "leftover_processes": [h1], "open_files_touching_real_state": [h4],
                "limits": {"max_reviews": 3, "max_dispatches": 6, "evil": h3},
                "verdicts": ["NEEDS WORK", "PASS", h3], "counts": {"dispatches": 2, "review_rounds": 2,
                                                                  "review_jobs": 2, "extra": h2},
                "assertions": [{"name": "the flow is held", "ok": True, "detail": h1},
                               {"name": h3, "ok": False, "detail": h2}],
                "stop": {"review_round": 1, "held": True, "kinds_after_the_stop": [h1, h2], "note": h3},
                "restart": {"review_round": 1, "console_exit_code": 0, "note": h2},
                "notes": [h1, h2, h3], "real_state_before": {"x": h1}, "started": h2}
        base.update(result or {})
        (self.run / "result.json").write_text(json.dumps(base))
        facts = [
            {"kind": "turn_anomaly", "data": {"reason": "extra_fields", "event_type": "assistant",
                                             "fields": ["wire_ingest_context", h1, "x" * 70]}},
            {"kind": "turn_anomaly", "data": {"reason": h3, "event_type": h1, "fields": [h2]}},
            {"kind": "permission_denied", "data": {"tool_name": "Bash", "reason_type": h3}},
            {"kind": h3, "data": {}},
            {"kind": "turn_result", "data": {"subtype": "success", "num_turns": 3, "total_cost_usd": 0.0123,
                                             "assistant_events": [{"request_id": "req_1"}, {"request_id": "req_1"}],
                                             "tool_calls": [{}], "result_text": h3,
                                             "structured_output": {"status": "done", "notes": h3,
                                                                   "tests": {"result": "passed", "summary": h1}}}},
        ]
        (self.state / "sessions" / "l-0123456789abcdef" / "journal.jsonl").write_text(
            "".join(json.dumps(f) + "\n" for f in (journal or facts)))
        man = {"round": 1, "state": "cleaned", "outcome": "valid", "model": "gpt-6-luna", "codex_version": "0.160.0",
               "exit_code": 0, "invalid_reasons": [h1, h3], "scratch": {"path": h1}, "workdir": h1, "created": 1.5,
               "ended_at": 2.5, "retained_reason": h3}
        man.update(manifest or {})
        (self.state / "reviews" / "r-0123456789abcdef" / "manifest.json").write_text(json.dumps(man))
        snap = snapshot or {"flow": {"flow": {"events": [
            {"seq": 1, "source": "console", "kind": "risk_acknowledged", "note": h1},
            {"seq": 2, "source": h3, "kind": "auto_review_result", "round": 1, "verdict": "NEEDS WORK", "detail": h2},
            {"seq": 3, "source": "automation", "kind": h3, "detail": h1}]}},
            "executor": {"accounting": {"dispatches": 2, "responses": 22, "spent_usd": 0.0923, "reviews": 2,
                                        "elapsed_s": 248.5, "started_at": 1791771640.0, "workdir": h1}}}
        (self.run / "snapshot-final.json").write_text(json.dumps(snap))

    def test_no_free_text_of_any_kind_reaches_the_summary(self):
        self.write()
        text = json.dumps(self.m.summarize(self.run, self.state), ensure_ascii=False)
        for h in HOSTILE:
            self.assertNotIn(h, text)
        for needle in ("someone", "Users", "secret", "SECRET", "example.invalid", "AssertionError", "sentence",
                       "private matters", "/home", "1791771640", "scratch", "workdir"):
            self.assertNotIn(needle, text, needle)
        self.assertNotRegex(text, r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")        # nothing path-shaped

    def test_what_is_kept_is_the_names_the_counts_and_the_costs(self):
        self.write()
        s = self.m.summarize(self.run, self.state)
        self.assertEqual((s["scenario"], s["passed"], s["has_error"], s["cleanup_problem_count"]), ("full", False, True, 2))
        self.assertEqual(s["verdicts"], ["NEEDS WORK", "PASS", "?"])
        self.assertEqual(s["assertions"], [{"name": "the flow is held", "ok": True}, {"name": "?", "ok": False}])
        sess = s["sessions"][0]
        self.assertEqual(sess["anomalies"][0], {"reason": "extra_fields", "event_type": "assistant",
                                                "fields": ["wire_ingest_context", "?", "?"]})
        self.assertEqual(sess["permission_denied"], [{"tool_name": "Bash", "reason_type": "?"}])
        self.assertEqual((sess["responses"], sess["final_cost_usd"]), (1, 0.0123))
        self.assertEqual(sess["turns"][0]["report_tests"], "passed")
        self.assertEqual(s["reviews"][0], {"round": 1, "state": "cleaned", "outcome": "valid", "model": "gpt-6-luna",
                                           "codex_version": "0.160.0", "exit_code": 0, "invalid_reason_count": 2})
        self.assertEqual(s["accounting"]["spent_usd"], 0.0923)
        self.assertEqual([e["kind"] for e in s["events"]], ["risk_acknowledged", "auto_review_result"])
        self.assertEqual(s["events"][1]["source"], "?")
        self.assertEqual(s["stop"]["events_after_the_stop"], 2)
        self.assertNotIn("evil", s["limits"])

    def test_every_assertion_name_of_the_driver_is_on_the_list(self):
        source = (TOOLS / "s3_real_e2e.py").read_text()
        names = set(re.findall(r'\.expect\(\s*"([^"]+)"', source))
        names |= set(re.findall(r'\.expect\("([^"]+)",', source))
        self.assertTrue(names)
        self.assertEqual(names - self.m.ASSERTIONS, set())


if __name__ == "__main__":
    unittest.main()
