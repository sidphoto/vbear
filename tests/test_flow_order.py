"""Which report is "the latest" (Gemini S2c-3 review): by the time the daemon
recorded a session, never by its name; unknown order fails closed."""

import unittest
from unittest import mock

from vbear import flow_review
from vbear.api_error import ApiError
from vbear.flow_executor import ordered_sessions
from vbear.runtime import stream_flow

COMMIT_A, COMMIT_B, COMMIT_C = "a" * 40, "b" * 40, "c" * 40


def manifest(launch, created):
    m = {"launch_id": launch, "state": "ended"}
    if created is not ...:
        m["created"] = created
    return m


class OrderedSessionsTests(unittest.TestCase):
    def test_by_creation_time_not_by_name(self):
        old, new = manifest("l-" + "f" * 16, 100.0), manifest("l-" + "0" * 16, 200.0)
        ordered, problem = ordered_sessions([new, old])
        self.assertEqual([m["launch_id"] for m in ordered], [old["launch_id"], new["launch_id"]])
        self.assertIsNone(problem)
        ordered, _ = ordered_sessions([old, new])
        self.assertEqual([m["launch_id"] for m in ordered], [old["launch_id"], new["launch_id"]])

    def test_an_order_that_cannot_be_told_is_said_and_never_guessed(self):
        same = [manifest("l-" + "1" * 16, 100.0), manifest("l-" + "2" * 16, 100.0)]
        self.assertIn("建立時間相同", ordered_sessions(same)[1])
        for bad in (..., None, True, "2026", float("nan"), float("inf"), [1]):
            ordered, problem = ordered_sessions([manifest("l-" + "1" * 16, 100.0), manifest("l-" + "2" * 16, bad)])
            self.assertIn("沒有可用的建立時間", problem, bad)
            self.assertEqual(len(ordered), 2)

    def test_one_session_and_none_are_fine(self):
        self.assertEqual(ordered_sessions([]), ([], None))
        only = manifest("l-" + "1" * 16, 5.0)
        self.assertEqual(ordered_sessions([only]), ([only], None))


class FakeExecutor:
    """What FlowReview asks of the executor service, with sessions chosen by the test."""

    def __init__(self, sessions):
        self.sessions = sessions          # {launch_id: [dispatch entries]}

    def _flow(self, flow_id):
        return {"id": flow_id, "task_id": "task-1", "events": []}

    def _workdir(self, flow):
        return "/work"

    def _lock(self, flow_id):
        import threading
        return threading.Lock()

    def _session_view(self, m):
        return {"launch_id": m["launch_id"], "status": {"dispatches": self.sessions[m["launch_id"]]}}


def dispatch(n, head):
    return {"dispatch_id": f"{n:08x}-aaaa-4bbb-8ccc-0123456789ab", "status": "ended", "valid": True, "reasons": [],
            "report": {"v": 1, "status": "done", "head": head, "tests": {"command": "t", "result": "passed", "summary": ""},
                       "notes": ""}}


class LatestReportTests(unittest.TestCase):
    def reports(self, manifests, sessions):
        review = flow_review.FlowReview(FakeExecutor(sessions))
        with mock.patch.object(stream_flow, "flow_sessions", return_value=manifests), \
                mock.patch.object(flow_review.FlowReview, "_started", return_value=True), \
                mock.patch.object(flow_review.FlowReview, "_review_manifests", return_value=[]), \
                mock.patch.object(flow_review.FlowReview, "_checks",
                                  return_value=[{"id": "x", "ok": True, "label": "", "detail": ""}]):
            return review, review.reports("flow-0123456789ab")

    def test_the_newest_session_wins_even_when_its_name_sorts_first(self):
        old, new = "l-" + "f" * 16, "l-" + "0" * 16                  # the old one sorts last by name
        manifests = [manifest(new, 200.0), manifest(old, 100.0)]
        sessions = {old: [dispatch(1, COMMIT_A)], new: [dispatch(2, COMMIT_B)]}
        _, r = self.reports(manifests, sessions)
        latest = [e for e in r["reports"] if e["latest"]]
        self.assertEqual([e["report"]["head"] for e in latest], [COMMIT_B])
        self.assertEqual(r["latest_dispatch_id"], sessions[new][0]["dispatch_id"])
        self.assertEqual([e["report"]["head"] for e in r["reports"]], [COMMIT_A, COMMIT_B])      # oldest first
        self.assertIsNone(r["order_problem"])

    def test_inside_a_session_the_journal_order_is_kept(self):
        a = "l-" + "1" * 16
        _, r = self.reports([manifest(a, 1.0)], {a: [dispatch(9, COMMIT_A), dispatch(3, COMMIT_B), dispatch(5, COMMIT_C)]})
        self.assertEqual([e["report"]["head"] for e in r["reports"]], [COMMIT_A, COMMIT_B, COMMIT_C])
        self.assertEqual([e["report"]["head"] for e in r["reports"] if e["latest"]], [COMMIT_C])

    def test_an_unknown_order_has_no_latest_and_review_start_refuses(self):
        a, b = "l-" + "1" * 16, "l-" + "2" * 16
        for created in ((100.0, 100.0), (100.0, ...), (100.0, None)):
            with self.subTest(created=created):
                manifests = [manifest(a, created[0]), manifest(b, created[1])]
                sessions = {a: [dispatch(1, COMMIT_A)], b: [dispatch(2, COMMIT_B)]}
                review, r = self.reports(manifests, sessions)
                self.assertTrue(r["order_problem"])
                self.assertFalse(any(e["latest"] for e in r["reports"]))
                self.assertIsNone(r["latest_dispatch_id"])
                with mock.patch.object(stream_flow, "flow_sessions", return_value=manifests), \
                        mock.patch.object(flow_review.FlowReview, "_started", return_value=True), \
                        mock.patch.object(flow_review.FlowReview, "_review_manifests", return_value=[]), \
                        mock.patch.object(flow_review.risk_acceptance, "status", return_value={"state": "valid"}), \
                        mock.patch.object(flow_review.pipeline_store, "hold_info",
                                          return_value={"held": False, "reason": "", "at": None}):
                    with self.assertRaises(ApiError) as cm:
                        review.start("flow-0123456789ab", {})
                self.assertEqual((cm.exception.status, cm.exception.code), (409, "order_unknown"))


if __name__ == "__main__":
    unittest.main()
