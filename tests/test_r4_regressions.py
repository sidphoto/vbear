"""Codex review r4: data that is wrong must fail closed, never raise, never pass."""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import activity, boundary_check, claude_verify
from vbear.runtime import cli_versions

W, I = "working", "waiting"
FOUR = ("idle_before_prompt", "working_after_prompt", "idle_after_turn", "spinner_cadence")


class R4Regressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_passing_summary_cannot_override_reversed_events(self):
        path = self.dir / "r.json"
        path.write_text(json.dumps({"passed": True, "claude_version": "2.1.299", "title": {
            "passed": True, "typed_at": 1.5, "events": [[2.0, W], [1.0, I]],
            "checks": {n: {"pass": True} for n in FOUR}}}))
        self.assertFalse(cli_versions._title_report_backs(str(path), "2.1.299"))
        self.assertFalse(claude_verify._title_result(path)["passed"])

    def test_title_checks_never_raise(self):
        for events, typed in (([(10 ** 10000, W)], 1.0), ([(1.0, I)], 10 ** 10000),
                              (None, 1.0), ("abc", 1.0), ({"a": 1}, 1.0), ([(1.0, I)], "1")):
            r = boundary_check.title_checks(events, typed_at=typed)
            self.assertFalse(r["passed"])

    def test_activity_now_must_be_a_finite_number(self):
        info = {"engine": "claude", "managed": "l-1", "cli_version": "2.1.292",
                "activity_evidence": {"claude_title": {"state": "working", "last_seen": 1000.0}}}
        for now in (float("inf"), float("nan"), "1000", 10 ** 10000):
            r = activity.arbitrate(info, now)
            self.assertEqual(r["activity"], "unknown", now)


if __name__ == "__main__":
    unittest.main()
