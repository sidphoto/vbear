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

    def write(self, result=None, journal=None, manifest=None, snapshot=None, result_json=None):
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
               "ended_at": 2.5, "retained_reason": h3, "task_id": "task-1"}
        man.update(manifest or {})
        rec = self.state / "pipelines" / man["task_id"] / "reviews" / "1"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "result.json").write_text(json.dumps(result_json if result_json is not None else {
            "v": 1, "verdict": "PASS", "reasons": [h1, h3], "thread_id": h2,
            "usage": {"complete": True, "counts": {"input_tokens": 1500, "cached_input_tokens": 100,
                                                    "cache_write_input_tokens": 0, "output_tokens": 70,
                                                    "reasoning_output_tokens": 20, "total_tokens": 1570,
                                                    "free_text": h3, "extra": h1}},
            "usage_problem": h2}))
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
                                           "codex_version": "0.160.0", "exit_code": 0, "invalid_reason_count": 2,
                                           "usage": {"state": "complete", "reason": None, "input_tokens": 1500,
                                                     "cached_input_tokens": 100, "cache_write_input_tokens": 0,
                                                     "output_tokens": 70, "reasoning_output_tokens": 20,
                                                     "total_tokens": 1570}})
        self.assertEqual(s["accounting"]["spent_usd"], 0.0923)
        self.assertEqual([e["kind"] for e in s["events"]], ["risk_acknowledged", "auto_review_result"])
        self.assertEqual(s["events"][1]["source"], "?")
        self.assertEqual(s["stop"]["events_after_the_stop"], 2)
        self.assertNotIn("evil", s["limits"])

    def test_a_review_without_usable_usage_has_none_not_zero(self):
        names = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
                 "reasoning_output_tokens", "total_tokens")
        h1, h2, h3, h4 = HOSTILE
        cases = (
            ({"v": 1, "usage": None, "usage_problem": "chain_mismatch"}, "unavailable", "chain_mismatch"),
            ({"v": 1, "usage": None, "usage_problem": h3}, "unavailable", "?"),               # free text never passes
            ({"v": 1}, "unavailable", "no_usage_field"),                                        # an earlier record
            ({"v": 1, "usage": {"counts": [1, 2], "complete": True}, "usage_problem": None}, "unavailable", "?"),
            ([1, 2], "unavailable", "no_usage_field"),
        )
        for rj, state, reason in cases:
            with self.subTest(rj=rj):
                self.write(result_json=rj)
                u = self.m.summarize(self.run, self.state)["reviews"][0]["usage"]
                self.assertEqual((u["state"], u["reason"]), (state, reason))
                self.assertEqual([u[n] for n in names], [None] * 6)                              # never 0
        # a count that is not a plain non-negative integer is not had, the rest are kept
        self.write(result_json={"v": 1, "usage": {"complete": False, "counts": {
            "input_tokens": 10, "output_tokens": True, "total_tokens": -5, "cached_input_tokens": 1.5,
            "cache_write_input_tokens": "9", "reasoning_output_tokens": 3}}})
        u = self.m.summarize(self.run, self.state)["reviews"][0]["usage"]
        self.assertEqual((u["state"], u["input_tokens"], u["reasoning_output_tokens"]), ("partial", 10, 3))
        self.assertEqual([u["output_tokens"], u["total_tokens"], u["cached_input_tokens"], u["cache_write_input_tokens"]],
                         [None, None, None, None])
        # no record at all, and a task id that is not a plain id
        (self.state / "pipelines" / "task-1" / "reviews" / "1" / "result.json").unlink()
        self.assertEqual(self.m.summarize(self.run, self.state)["reviews"][0]["usage"]["reason"], "no_result")
        self.write(manifest={"task_id": "../../x"})
        u = self.m.summarize(self.run, self.state)["reviews"][0]["usage"]
        self.assertEqual((u["state"], u["reason"], u["input_tokens"]), ("unavailable", "?", None))

    def test_the_summary_names_are_the_products(self):
        import sys
        sys.path.insert(0, str(TOOLS.parent))
        from vbear.runtime import codex_constants as cc, review_validate as rv
        self.assertEqual(set(self.m.USAGE_PROBLEMS), set(rv.USAGE_PROBLEMS))
        for version, consts in cc.VERSIONS.items():
            self.assertEqual(set(self.m.USAGE_NAMES), set(consts.usage_fields), version)

    def test_every_assertion_name_of_the_driver_is_on_the_list(self):
        source = (TOOLS / "s3_real_e2e.py").read_text()
        names = set(re.findall(r'\.expect\(\s*"([^"]+)"', source))
        names |= set(re.findall(r'\.expect\("([^"]+)",', source))
        self.assertTrue(names)
        self.assertEqual(names - self.m.ASSERTIONS, set())


if __name__ == "__main__":
    unittest.main()
