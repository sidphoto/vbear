"""Terminal-title verification inside 「驗證這個版本」 (no model calls).

The interactive boundary check watches Claude Code's terminal title in the
same session; the result is recorded apart from the launch-boundary result,
and only a passing title record makes the title rung authoritative.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import activity, boundary_check, claude_verify
from vbear.runtime import cli_versions

W, I = "working", "waiting"


class TitleChecksTests(unittest.TestCase):
    def good(self):
        return [(1.0, I), (3.1, W), (4.0, W), (5.0, W), (6.2, I)]

    def test_a_normal_turn_passes(self):
        r = boundary_check.title_checks(self.good(), typed_at=2.0)
        self.assertTrue(r["passed"], r)
        self.assertEqual(r["checks"]["spinner_cadence"]["max_gap_s"], 1.0)

    def test_each_missing_step_fails_its_check(self):
        cases = {
            "idle_before_prompt": ([(3.1, W), (4.0, W), (6.2, I)], 2.0),        # no ✳ before typing
            "working_after_prompt": ([(1.0, I), (6.2, I)], 2.0),                # spinner never shown
            "idle_after_turn": ([(1.0, I), (3.1, W), (4.0, W)], 2.0),            # never back to ✳
            "spinner_cadence": ([(1.0, I), (3.1, W), (9.5, W), (10.0, I)], 2.0),  # 6.4 s without a frame
        }
        for name, (events, typed) in cases.items():
            with self.subTest(name):
                r = boundary_check.title_checks(events, typed_at=typed)
                self.assertFalse(r["passed"])
                self.assertFalse(r["checks"][name]["pass"], r["checks"])

    def test_never_typed_fails(self):
        r = boundary_check.title_checks([(1.0, I)], typed_at=None)
        self.assertFalse(r["checks"]["idle_before_prompt"]["pass"])
        self.assertFalse(r["passed"])

    def test_gaps_across_an_idle_period_are_not_spinner_gaps(self):
        events = [(1.0, I), (3.0, W), (4.0, W), (5.0, I), (20.0, W), (21.0, W), (22.0, I)]
        self.assertTrue(boundary_check.title_checks(events, typed_at=2.0)["passed"])

    def test_only_title_classes_are_kept_and_two_titles_in_one_read_are_both_seen(self):
        obs = boundary_check.TitleObservation(start=100.0)
        obs.feed(b"\x1b]0;\xe2\x97\x90 secret task summary\x07noise\x1b]0;\xe2\x9c\xb3 done\x07", 101.0)
        self.assertEqual(obs.events, [(1.0, W), (1.0, I)])
        self.assertNotIn("secret", json.dumps(boundary_check.title_checks(obs.events, 0.5)))


FAKE_TUI = r'''#!%(py)s
import os, sys, time
mode = %(mode)r
def title(t):
    sys.stdout.write("\x1b]0;" + t + "\x07"); sys.stdout.flush()
if mode != "no-idle-first":
    title("✳ Claude Code")
print("ready", flush=True)
sys.stdin.readline()
for i in range(3):
    title(("◐", "◑")[i %% 2] + " task"); time.sleep(0.3)
open("probe-result.json", "w").write("{}")
if mode != "never-idle":
    time.sleep(0.3); title("✳ task")
time.sleep(600)
'''


class RunInteractiveTitleTests(unittest.TestCase):
    """run_interactive against a fake TUI in a real PTY."""

    def run_fake(self, mode, **kw):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "fake-claude"
            fake.write_text(FAKE_TUI % {"py": sys.executable, "mode": mode})
            fake.chmod(0o700)
            start = time.monotonic()
            _, title = boundary_check.run_interactive(
                [str(fake)], {"PATH": "/usr/bin:/bin", "HOME": d}, d, Path(d) / "probe-result.json", **kw)
            return title, time.monotonic() - start

    def test_full_turn_passes_and_waits_for_the_idle_title(self):
        title, took = self.run_fake("normal")
        self.assertTrue(title["passed"], title)
        self.assertLess(took, 20)

    def test_never_returning_to_idle_fails_after_the_bounded_wait(self):
        title, took = self.run_fake("never-idle", idle_wait=2.0)
        self.assertFalse(title["checks"]["idle_after_turn"]["pass"])
        self.assertLess(took, 20)

    def test_no_idle_title_before_the_prompt_fails(self):
        title, _ = self.run_fake("no-idle-first", prompt_wait=3.0)
        self.assertFalse(title["checks"]["idle_before_prompt"]["pass"])
        self.assertTrue(title["checks"]["working_after_prompt"]["pass"])


class TitleRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "st"
        self.home.mkdir()
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        activity._local_cache.update(key=None)

    def report(self, name, version, title_pass=True):
        path = self.home / name
        checks = {k: {"pass": True} for k in ("idle_before_prompt", "working_after_prompt",
                                              "idle_after_turn", "spinner_cadence")}
        if not title_pass:
            checks["idle_after_turn"]["pass"] = False
        path.write_text(json.dumps({"passed": True, "claude_version": version,
                                    "title": {"passed": title_pass, "checks": checks}}))
        return str(path)

    def record(self, version, *, title_pass=True):
        inter = self.report(f"{version}-i.json", version, title_pass)
        head = self.home / f"{version}-h.json"
        head.write_text(json.dumps({"passed": True, "claude_version": version}))
        claude_verify.record_pass(version, "/x/claude", {"headless": str(head), "interactive": inter},
                                  title=claude_verify._title_result(Path(inter)))

    def test_title_pass_makes_the_version_judgeable(self):
        self.record("2.1.299")
        self.assertIn("2.1.299", cli_versions.local_title_verified_versions())
        self.assertTrue(activity.title_verified("claude", "2.1.299"))
        info = {"engine": "claude", "managed": "l-1", "cli_version": "2.1.299",
                "activity_evidence": {"claude_title": {"state": "waiting", "last_seen": time.time()}}}
        r = activity.arbitrate(info)
        self.assertEqual((r["activity"], r["evidence"][0]["trust"]), ("waiting", "authoritative"))

    def test_title_failure_keeps_the_boundary_pass(self):
        self.record("2.1.299", title_pass=False)
        self.assertIn("2.1.299", cli_versions.verified_versions("claude"))       # launches as verified
        self.assertNotIn("2.1.299", cli_versions.local_title_verified_versions())
        self.assertFalse(activity.title_verified("claude", "2.1.299"))

    def test_old_and_broken_records_are_title_unverified(self):
        head = self.home / "h.json"
        head.write_text(json.dumps({"passed": True, "claude_version": "2.1.299"}))
        base = {"passed": True, "report": str(head), "binary": "/x", "verified_at": "t",
                "reports": {"headless": str(head)}}
        broken_report = self.home / "b.json"
        broken_report.write_text("[1]")
        other_version = self.report("o.json", "2.1.250")
        variants = {
            "old format (no title)": {},
            "title not an object": {"title": "yes"},
            "title passed but no report": {"title": {"passed": True}},
            "report is not an object": {"title": {"passed": True, "report": str(broken_report)}},
            "report for another version": {"title": {"passed": True, "report": other_version}},
            "missing report file": {"title": {"passed": True, "report": str(self.home / "gone.json")}},
        }
        for name, extra in variants.items():
            with self.subTest(name):
                (self.home / cli_versions.LOCAL_VERIFIED_FILE).write_text(
                    json.dumps({"versions": {"2.1.299": {**base, **extra}}}))
                activity._local_cache.update(key=None)
                self.assertIn("2.1.299", cli_versions.local_verified_versions())  # boundary still counts
                self.assertEqual(cli_versions.local_title_verified_versions(), {})
                self.assertFalse(activity.title_verified("claude", "2.1.299"))

    def test_corrupt_record_file_means_nothing_is_verified(self):
        (self.home / cli_versions.LOCAL_VERIFIED_FILE).write_text("{not json")
        self.assertFalse(activity.title_verified("claude", "2.1.299"))
        self.assertTrue(activity.title_verified("claude", "2.1.292"))  # built-in stays

    def test_codex_never_uses_local_title_records(self):
        self.record("2.1.299")
        self.assertFalse(activity.title_verified("codex", "2.1.299"))


if __name__ == "__main__":
    unittest.main()
