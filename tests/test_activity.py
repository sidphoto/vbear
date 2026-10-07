"""Activity taxonomy and terminal-title evidence (vbear/activity.py,
vbear/runtime/osc_title.py). Pure functions: no daemon, no HOME access."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from vbear import activity
from vbear.runtime import osc_title

T = "\x1b]0;{}\x07".format
# What Claude Code 2.1.292 printed around its titles, trimmed: cursor moves,
# colours and the spinner frames between them.
NOISE = b"\x1b[?25l\x1b[2K\x1b[1G\x1b[38;5;174m\xe2\x9c\xbb\x1b[39m Thinking\xe2\x80\xa6\x1b[?25h"


def feed_all(chunks, now=100.0):
    tr = osc_title.TitleTracker()
    for i, c in enumerate(chunks):
        tr.feed(c, now + i)
    return tr


class TitleTrackerTests(unittest.TestCase):
    def test_classifies_the_first_glyph(self):
        self.assertEqual(osc_title.classify("✳ Claude Code"), "waiting")
        self.assertEqual(osc_title.classify("◐ Reply with OK"), "working")
        self.assertEqual(osc_title.classify("◑ Reply with OK"), "working")
        self.assertEqual(osc_title.classify(""), "empty")
        self.assertEqual(osc_title.classify("zsh"), "other")

    def test_bel_and_st_terminated_titles(self):
        tr = feed_all([NOISE + T("✳ Claude Code").encode() + NOISE])
        self.assertEqual(tr.state, "waiting")
        tr.feed(b"\x1b]2;\xe2\x97\x90 task\x1b\\", 200.0)
        self.assertEqual((tr.state, tr.since, tr.last_seen, tr.titles), ("working", 200.0, 200.0, 2))

    def test_spinner_frames_refresh_last_seen_but_not_since(self):
        tr = osc_title.TitleTracker()
        tr.feed(T("◐ a").encode(), 10.0)
        tr.feed(T("◑ a").encode(), 11.0)
        tr.feed(T("◐ b").encode(), 12.0)
        self.assertEqual((tr.state, tr.since, tr.last_seen, tr.titles), ("working", 10.0, 12.0, 3))
        tr.feed(T("✳ b").encode(), 13.0)
        self.assertEqual((tr.state, tr.since, tr.last_seen), ("waiting", 13.0, 13.0))

    def test_any_chunk_split_gives_the_same_result(self):
        data = NOISE + T("◐ Reply").encode() + NOISE + b"\x1b]2;\xe2\x9c\xb3 done\x1b\\" + NOISE
        whole = feed_all([data])
        for cut in range(1, len(data)):
            split = feed_all([data[:cut], data[cut:]])
            self.assertEqual((split.state, split.titles), (whole.state, whole.titles), cut)
        bytewise = feed_all([bytes([b]) for b in data])
        self.assertEqual((bytewise.state, bytewise.titles), ("waiting", 2))

    def test_other_osc_codes_are_ignored(self):
        tr = feed_all([b"\x1b]11;?\x07", b"\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\",
                       b"\x1b]9;notification\x07", b"\x1b]1;icon\x07"])
        self.assertIsNone(tr.state)
        self.assertEqual(tr.titles, 0)

    def test_overlong_osc_is_skipped_and_parsing_recovers(self):
        long_title = "\x1b]0;◐" + "x" * (osc_title.MAX_OSC + 10) + "\x07"
        tr = feed_all([long_title.encode()[:3000], long_title.encode()[3000:], T("✳ ok").encode()])
        self.assertEqual((tr.state, tr.titles), ("waiting", 1))

    def test_osc_cancelled_by_another_escape_sequence(self):
        tr = feed_all([b"\x1b]0;\xe2\x97\x90 half\x1b[2K", T("✳ ok").encode()])
        self.assertEqual((tr.state, tr.titles), ("waiting", 1))
        tr = feed_all([b"\x1b]0;\xe2\x97\x90 half\x1b", b"]0;\xe2\x9c\xb3 next\x07"])
        self.assertEqual((tr.state, tr.titles), ("waiting", 1))

    def test_can_and_sub_cancel_a_title(self):
        # Review finding: a cancelled title must not count as one.
        for cancel in (b"\x18", b"\x1a"):
            tr = feed_all([b"\x1b]0;\xe2\x97\x90 partial" + cancel + b"\x07"])
            self.assertEqual((tr.state, tr.titles), (None, 0), cancel)
            tr = feed_all([b"\x1b]0;\xe2\x97\x90 partial" + cancel, T("✳ next").encode()])
            self.assertEqual((tr.state, tr.titles), ("waiting", 1), cancel)

    def test_snapshot_never_contains_title_text(self):
        tr = feed_all([T("◐ a secret task summary").encode()])
        snap = tr.snapshot()
        self.assertEqual(set(snap), {"state", "since", "last_seen", "titles"})
        self.assertNotIn("secret", json.dumps(snap, ensure_ascii=False))


def managed(version="2.1.292", **title):
    info = {"session_id": "n-000000000001", "engine": "claude", "managed": "l-0000000000000001",
            "cli_version": version, "exited": False, "closing": False}
    if title:
        info["activity_evidence"] = {"claude_title": {"state": None, "since": None, "last_seen": None,
                                                      "titles": 0, **title}}
    return info


class ArbitrateTests(unittest.TestCase):
    NOW = 1000.0

    def arb(self, info):
        return activity.arbitrate(info, self.NOW)

    def test_verified_working_title_decides(self):
        r = self.arb(managed(state="working", since=990.0, last_seen=999.0, titles=5))
        self.assertEqual((r["session"], r["activity"], r["display"], r["decided_by"]),
                         ("present", "working", "working", "claude-title"))
        self.assertEqual(r["evidence"][0]["trust"], "authoritative")

    def test_verified_waiting_title_decides(self):
        r = self.arb(managed(state="waiting", since=990.0, last_seen=990.0, titles=1))
        self.assertEqual((r["activity"], r["display"], r["decided_by"]), ("waiting", "waiting", "claude-title"))

    def test_waiting_does_not_go_stale(self):
        r = self.arb(managed(state="waiting", since=10.0, last_seen=10.0, titles=1))
        self.assertEqual(r["display"], "waiting")

    def test_stale_working_title_is_unknown(self):
        r = self.arb(managed(state="working", since=900.0,
                             last_seen=self.NOW - activity.SPINNER_STALE_S - 1, titles=9))
        self.assertEqual((r["activity"], r["decided_by"]), ("unknown", None))
        self.assertIn("沒有更新", r["reason"])

    def test_no_title_yet_is_unknown(self):
        r = self.arb(managed(state=None))
        self.assertEqual(r["display"], "unknown")
        self.assertIn("信任確認", r["reason"])

    def test_empty_or_other_title_is_unknown(self):
        for state in ("empty", "other"):
            r = self.arb(managed(state=state, since=999.0, last_seen=999.0, titles=1))
            self.assertEqual((r["display"], r["decided_by"]), ("unknown", None), state)

    def test_unverified_version_is_trial_and_never_consulted(self):
        r = self.arb(managed(version="2.1.286", state="working", since=999.0, last_seen=999.5, titles=2))
        self.assertEqual((r["display"], r["decided_by"]), ("unknown", None))
        self.assertEqual([(e["trust"], e["value"]) for e in r["evidence"]], [("trial", "working")])
        self.assertIn("試用中", r["reason"])
        r = self.arb(managed(version=None, state="waiting", since=999.0, last_seen=999.0, titles=1))
        self.assertEqual(r["evidence"][0]["trust"], "trial")

    def test_exited_and_closing(self):
        info = managed(state="working", since=999.0, last_seen=999.5, titles=2)
        r = self.arb({**info, "exited": True})
        self.assertEqual((r["session"], r["display"], r["decided_by"]), ("exited", "exited", None))
        r = self.arb({**info, "closing": True})
        self.assertEqual((r["session"], r["display"], r["reason"]), ("present", "unknown", "正在關閉"))

    def test_sessions_without_a_verified_source(self):
        for info, word in ((managed(), "沒有回報"),  # a managed Claude whose daemon sent no evidence
                           ({"engine": "claude", "managed": None}, "不是 VBear 受管"),
                           ({"engine": "codex", "managed": "l-0000000000000002"}, "Codex"),
                           ({"engine": None}, "不是 Agent")):
            r = self.arb(info)
            self.assertEqual((r["display"], r["decided_by"], r["evidence"]), ("unknown", None, []), info)
            self.assertIn(word, r["reason"], info)

    def test_axes_not_served_are_honest(self):
        r = self.arb(managed(state="working", since=999.0, last_seen=999.5, titles=2))
        self.assertEqual(r["needs_input"], {"count": 0, "reason": None})
        self.assertIsNone(r["needs_input_evidence"])
        self.assertEqual(r["resumability"], "unknown")

    def test_display_refuses_values_outside_the_taxonomy(self):
        self.assertEqual(activity.display_value("present", "working", {"count": 1}), "needs-input")
        for bad in (("present", "idle"), ("present", "blocked"), ("detached", "working")):
            with self.assertRaises(ValueError):
                activity.display_value(bad[0], bad[1], {"count": 0})



class LiveAttentionTests(unittest.TestCase):
    """index.build_live: "需要你處理" holds only Agents some evidence decided
    are waiting for the user; "unknown" never qualifies."""

    def test_attention_lists_waiting_agents_only(self):
        from vbear import index

        def agent(tid, status, act):
            return {"terminal_id": tid, "pane_id": tid, "workspace_id": "native", "tab_id": "",
                    "agent": "claude", "agent_status": status, "activity": act, "cwd": ""}

        decided = {"display": "waiting", "decided_by": "claude-title", "reason": "", "evidence": []}

        class Runtime:
            def snapshot(self):
                return {"available": True, "version": "t", "binary": "t", "problems": [],
                        "workspaces": [], "tabs": [], "panes": [],
                        "agents": [agent("t-work", "working", {**decided, "display": "working"}),
                                   agent("t-wait", "waiting", decided),
                                   agent("t-unknown", "unknown", None),
                                   agent("t-need", "needs-input", {**decided, "display": "needs-input"}),
                                   agent("t-legacy", "blocked", None)]}

        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}):
            live = index.build_live({"usage_enabled": False}, {"skills": []}, Runtime())
        self.assertEqual(live["attention"], ["t-need", "t-wait"])
        by_id = {s["terminal_id"]: s for s in live["sessions"]}
        self.assertEqual(by_id["t-wait"]["activity"]["decided_by"], "claude-title")
        self.assertIsNone(by_id["t-unknown"]["activity"])


if __name__ == "__main__":
    unittest.main()
