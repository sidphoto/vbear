"""The engine under the meetings, as P35-2 changes it for every kind of board: a turn whose text cannot be made ends as a
failure instead of staying queued. No CLI runs: the calls are fakes."""
import unittest
from decimal import Decimal

from tests.test_meeting_runner import DECISION, OPINION, VERSION, Base, profile
from vbear import meeting_runner as mr, meetings as mt

EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}
# an opinion at every limit the check allows, in a three-byte character: six of them do not fit the CEO's 48 KiB
LONG_OPINION = {"stance": "支持", "summary": "長" * 120, "points": ["長" * 200] * 5,
                "risks": [{"level": "中", "text": "長" * 200, "source": "長" * 200}] * 5, "needs_chairman": False}
SIX = ["pm", "social", "eng", "art", "legal", "acct"]


class PromptFailureTests(Base):
    def setUp(self):
        super().setUp()
        self.profiles.update({p["id"]: p for p in (profile("social", "social"), profile("art", "art"))})
        self.profiles["eng"] = profile("eng", "executor")

    def board(self, cls=mr.MeetingRunner, answer=None):
        self.specs = []

        def call(spec, cancel):
            self.specs.append(spec.kind)
            out = (answer or OPINION) if spec.kind == "opinion" else DECISION
            return mr.CallResult(out, dict(EVIDENCE), Decimal("0.01"))
        runner = cls(provider=lambda e: ("x", VERSION), call=call)
        self.runners.append(runner)
        self.addCleanup(runner.wait, 5)
        return runner

    def test_a_decision_too_long_to_send_fails_instead_of_staying_queued(self):
        runner = self.board(answer=LONG_OPINION)
        _, m = self.run_meeting(runner, self.body(speaker_profile_ids=SIX),
                                meeting_limits={"per_call_usd": 0.2, "meeting_usd": 2, "daily_usd": 3})
        last = m["turns"][-1]
        self.assertEqual([t["state"] for t in m["turns"][:-1]], ["done"] * 6)
        self.assertEqual((last["state"], last["error_code"], last["attempts"], last["prompt_sha256"], last["evidence"]),
                         ("failed", "too_large", 1, None, None))
        self.assertEqual(self.specs, ["opinion"] * 6)  # the decision was never sent
        self.assertEqual(m["status"], "incomplete")
        self.assertIsNone(runner.job)
        self.assertEqual(m["retryable"], [7])

    def test_a_turn_whose_text_cannot_be_made_for_another_reason_fails_as_internal(self):
        class Broken(mr.MeetingRunner):
            def prompt(self, kind, who, rec, ctx):
                if who["position"] == "pm":
                    raise KeyError("synthetic")
                return super().prompt(kind, who, rec, ctx)
        _, m = self.run_meeting(self.board(Broken))
        self.assertEqual([(t["state"], t["error_code"]) for t in m["turns"]], [("failed", "internal"), ("done", None), ("done", None)])
        self.assertEqual(self.specs, ["opinion", "decision"])


if __name__ == "__main__":
    unittest.main()
