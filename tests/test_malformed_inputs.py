"""Every entry that reads numbers, times or report/record data fails closed.

Codex review r4: for each entry and each bad value: no exception, and never a
pass (verified / working / passed). Values cover None, bool, strings, NaN,
±inf, an int too large for a float, negatives, reversed order, empty and
wrong-typed containers.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import activity, agent_launch, claude_verify, numbers, title_check
from vbear.runtime import cli_versions

NAN, INF = float("nan"), float("inf")


def show(v) -> str:
    """A subTest label for any value (repr of 10**10000 itself would raise)."""
    try:
        return repr(v)[:60]
    except ValueError:  # contains an int too large to print
        return f"<{type(v).__name__} with a huge int>"
BAD_NUMBERS = [None, True, False, "1", "", NAN, INF, -INF, 10 ** 10000, -1, -1.5, [], {}, [1.0], {"t": 1.0},
               object()]
BAD_CONTAINERS = [None, True, 1, 1.5, NAN, "events", "", b"x", {}, {"a": 1}, object()]
BAD_EVENTS = [
    [],                                              # empty: nothing observed
    [[2.0, "working"], [1.0, "waiting"]],            # reversed
    [[1.0, "waiting"], [1.0]],                       # short pair
    [[1.0, "waiting", "x"]],                         # long pair
    [[1.0, 5]],                                      # class not a string
    [[1.0, "running"]],                              # unknown class
    [["1.0", "waiting"]],                            # time as text
    [{"t": 1.0, "s": "waiting"}],                    # wrong shape
    "not a list", None, 5, {"events": []},
] + [[[1.0, "waiting"], [v, "working"], [9.0, "waiting"]] for v in BAD_NUMBERS]
GOOD_EVENTS = [[1.0, "waiting"], [3.0, "working"], [4.0, "working"], [5.0, "working"], [6.0, "waiting"]]
FOUR = {n: {"pass": True} for n in title_check.TITLE_CHECKS}


class StrictNumberTests(unittest.TestCase):
    def test_finite_real_never_raises_and_refuses_bad_values(self):
        for v in BAD_NUMBERS[:-6] + [object(), 10 ** 400]:
            with self.subTest(v=show(v)):
                got = numbers.finite_real(v)
                self.assertTrue(got is None or got < 0, got)  # negatives are numbers; callers refuse them
        self.assertEqual(numbers.finite_real(3), 3.0)
        self.assertEqual(numbers.finite_real(2.5), 2.5)


class TitleCheckEntryTests(unittest.TestCase):
    def test_title_checks_with_bad_events_or_times(self):
        for events in BAD_EVENTS:
            with self.subTest(events=show(events)):
                r = title_check.title_checks(events, 2.0)
                self.assertFalse(r["passed"])
        for typed in BAD_NUMBERS:
            with self.subTest(typed_at=show(typed)):
                r = title_check.title_checks(GOOD_EVENTS, typed)
                if typed is None:
                    self.assertFalse(r["checks"]["idle_before_prompt"]["pass"])  # never typed
                self.assertFalse(r["passed"])
        self.assertTrue(title_check.title_checks(GOOD_EVENTS, 2.0)["passed"])  # the good case still passes

    def test_report_title_passes_with_bad_data(self):
        good = {"passed": True, "claude_version": "2.1.299", "title": {"passed": True, "checks": FOUR,
                                                       "events": GOOD_EVENTS, "typed_at": 2.0}}
        self.assertTrue(title_check.report_title_passes(good, "2.1.299"))
        variants = [None, [], "x", 1, {}, {"claude_version": "2.1.299"},
                    {**good, "claude_version": 2.1}, {**good, "title": None}, {**good, "title": []},
                    {**good, "passed": "true"}, {**good, "passed": 1},
                    {**good, "title": {**good["title"], "events": "x"}},
                    {**good, "title": {**good["title"], "typed_at": NAN}},
                    {**good, "title": {**good["title"], "typed_at": 10 ** 10000}},
                    {**good, "title": {**good["title"], "checks": None}},
                    {**good, "title": {**good["title"], "passed": "true"}}]
        variants += [{**good, "title": {**good["title"], "events": ev}} for ev in BAD_EVENTS]
        for data in variants:
            with self.subTest(data=show(data)):
                self.assertFalse(title_check.report_title_passes(data, "2.1.299"))
        for version in BAD_NUMBERS:
            self.assertFalse(title_check.report_title_passes(good, version))


class ReportAndRecordEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "st"
        self.home.mkdir()
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        activity._local_cache.update(key=None)
        self.n = 0

    def file(self, content) -> str:
        self.n += 1
        path = self.home / f"f{self.n}.json"
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return str(path)

    def bad_report_contents(self):
        out = ["", "{", "null", "[]", "1", '"x"', "NaN"]
        good = {"passed": True, "claude_version": "2.1.299",
                "title": {"passed": True, "checks": FOUR, "events": GOOD_EVENTS, "typed_at": 2.0}}
        out += [json.dumps({**good, "title": {**good["title"], "events": ev}}) for ev in BAD_EVENTS[:12]]
        out += [json.dumps({**good, "title": None}), json.dumps({**good, "passed": "yes"}),
                json.dumps({**good, "claude_version": None})]
        return out

    def test_report_readers(self):
        for content in self.bad_report_contents():
            path = self.file(content)
            with self.subTest(content=content[:60]):
                self.assertFalse(cli_versions._title_report_backs(path, "2.1.299"))
                self.assertFalse(claude_verify._title_result(Path(path))["passed"])
                claude_verify._failed_checks(Path(path))   # must not raise
        for bad_path in [None, 5, "", str(self.home / "missing.json"), str(self.home)]:
            with self.subTest(path=bad_path):
                self.assertFalse(cli_versions._title_report_backs(bad_path, "2.1.299"))

    def test_record_readers(self):
        good_report = self.file({"passed": True, "claude_version": "2.1.299",
                                 "title": {"passed": True, "checks": FOUR, "events": GOOD_EVENTS, "typed_at": 2.0}})
        good = {"passed": True, "report": good_report, "binary": "/x", "verified_at": "t",
                "reports": {"interactive": good_report},
                "title": {"passed": True, "failed": [], "report": good_report}}
        record_files = ["", "{", "null", "[]", json.dumps({"versions": None}), json.dumps({"versions": []}),
                        json.dumps({"versions": {"2.1.299": None}}), json.dumps({"versions": {"2.1.299": []}})]
        record_files += [json.dumps({"versions": {"2.1.299": {**good, k: v}}})
                         for k in ("passed", "report", "binary", "verified_at", "reports", "title")
                         for v in (None, True, 1, NAN, "", [], {}, "x")
                         # binary and verified_at are informational: any non-empty string is fine
                         if not (k in ("binary", "verified_at") and v == "x")
                         and not (k == "passed" and v is True)]
        path = self.home / cli_versions.LOCAL_VERIFIED_FILE
        for content in record_files:
            path.write_text(content)
            activity._local_cache.update(key=None)
            with self.subTest(record=content[:80]):
                titled = cli_versions.local_title_verified_versions()
                self.assertNotIn("2.1.299", titled)
                self.assertFalse(activity.title_verified("claude", "2.1.299"))
                agent_launch._last_title_failure("claude", "2.1.299")   # must not raise
                agent_launch.claude_evidence("2.1.299", "writes")        # must not raise
        path.write_text(json.dumps({"versions": {"2.1.299": good}}))
        activity._local_cache.update(key=None)
        self.assertIn("2.1.299", cli_versions.local_title_verified_versions())  # the good record still counts

    def test_version_arguments(self):
        for v in BAD_NUMBERS:
            with self.subTest(version=show(v)):
                self.assertFalse(activity.title_verified("claude", v))
                self.assertIsNone(agent_launch._last_title_failure("claude", v))


class ArbitrateEntryTests(unittest.TestCase):
    NOW = 1000.0

    def info(self, **title):
        return {"engine": "claude", "managed": "l-1", "cli_version": "2.1.292",
                "activity_evidence": {"claude_title": {"state": "working", "last_seen": 999.0, **title}}}

    def test_bad_last_seen_now_and_info(self):
        for v in BAD_NUMBERS:
            with self.subTest(last_seen=show(v)):
                self.assertNotEqual(activity.arbitrate(self.info(last_seen=v), self.NOW)["activity"], "working")
            with self.subTest(now=show(v)):
                if v is None:
                    continue  # None means "use the clock": 999.0 is then long stale, still not working
                self.assertNotEqual(activity.arbitrate(self.info(), v)["activity"], "working")
        for info in BAD_CONTAINERS + [{"activity_evidence": v} for v in BAD_CONTAINERS]:
            with self.subTest(info=show(info)):
                self.assertEqual(activity.arbitrate(info, self.NOW)["activity"], "unknown")
        for state in [None, 1, NAN, [], {}, "running"]:
            with self.subTest(state=repr(state)):
                self.assertNotEqual(activity.arbitrate(self.info(state=state), self.NOW)["activity"], "working")
        # The good case is still read.
        self.assertEqual(activity.arbitrate(self.info(), self.NOW)["activity"], "working")

    def test_extreme_but_finite_times(self):
        """Codex review r5: each value finite, their difference not (age overflowed to inf)."""
        big = 1.7976931348623157e308
        pairs = [(big, -big), (-big, big), (1e308, -1e308), (big, big), (big, 1.0),
                 (-1.0, 999.0), (1000.0, -1.0), (0.0, 0.0), (1000.0, 0.0), (0.0, -5.0)]
        for now, last_seen in pairs:
            with self.subTest(now=now, last_seen=last_seen):
                r = activity.arbitrate(self.info(last_seen=last_seen), now)
                self.assertEqual(r["activity"], "unknown")
                self.assertTrue(r["reason"])

    def test_title_checks_with_extreme_times_never_raise(self):
        big = 1.7976931348623157e308
        for events, typed in (([[0.0, "waiting"], [big / 2, "working"], [big, "working"], [big, "waiting"]], 1.0),
                              ([[0.0, "waiting"], [1.0, "working"], [big, "working"], [big, "waiting"]], 0.5),
                              ([[0.0, "waiting"], [1.0, "working"]], big)):
            r = title_check.title_checks(events, typed)
            self.assertFalse(r["passed"])


if __name__ == "__main__":
    unittest.main()
