"""Stream protocol (design 2.2-2.4, 3.1, 3.3) and journal (2.5): the event
tracker, the journal state machine, turn validity, sanitising and the
dispatch line. Events are synthetic (tests/stream_fixtures.py)."""

import copy
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from tests import stream_fixtures as fx
from vbear import executor_report, strictjson
from vbear.runtime import stream_journal as sj
from vbear.runtime import stream_protocol as sp

NAN, INF = float("nan"), float("inf")
CWD = "/private/tmp/vbear-task"
C = sp.VERSIONS["2.1.292"]
TURN_CAP = 200
IDENTITY = {"model_id": fx.MODEL, "workdir": CWD, "executor_claude_version": "2.1.292", "executor_model": fx.MODEL}


class Harness:
    """Plays the daemon: writes its own records and feeds events through the
    tracker; every record goes through encode -> strict parse -> apply."""

    def __init__(self, model=fx.MODEL, identity=IDENTITY, consts=C):
        self.sid = fx.new_uuid()
        self.tracker = sp.EventTracker(consts, self.sid, CWD, model)
        self.js = sj.JournalState(identity=identity)
        self.seq = 0
        self.records = []
        self.record("session_started", {"claude_session_id": self.sid, "pipeline_id": "flow-0123456789ab",
                                        "cli_version": consts.version, "argv_sha256": "a" * 64, "budget_usd": 20.0})

    def record(self, kind, data):
        line = sj.encode(self.seq + 1, time.time(), kind, data)
        parsed = strictjson.loads(line[:-1], strictjson.SESSION_LOG)
        assert parsed.ok, parsed.problem
        self.js.apply_record(parsed.value)             # a refused record is not kept, as in JournalWriter
        self.seq += 1
        self.records.append(line)

    def dispatch(self, text="please do the work"):
        d = fx.new_uuid()
        self.record("dispatch_accepted", {"dispatch_id": d, "text_sha256": sp.sha256_hex(text),
                                          "length": len(text.encode()), "approval": {"kind": "preview", "id": "p1"}})
        self.record("dispatch_writing", {"dispatch_id": d, "turn_cap": TURN_CAP})
        self.record("dispatch_written", {"dispatch_id": d})
        self.tracker.begin(d, text)
        return d, text

    def feed(self, events):
        for ev in events:
            for kind, data in self.tracker.on_event(copy.deepcopy(ev)):
                self.record(kind, data)

    def run_turn(self, **kw):
        d, text = self.dispatch()
        kw.setdefault("result_index", self.tracker.result_index + 1)
        kw.setdefault("cost", self.tracker.last_cost + 0.01)
        kw.setdefault("prefix", d[:8])
        self.feed(fx.turn(self.sid, d, text, cwd=CWD, **kw))
        return d

    def validity(self, d):
        return sj.turn_validity(self.js, d, executor_report.problem)


class UnfinishedTurnTests(unittest.TestCase):
    """Design v29.7: a dispatch that may have reached the CLI (from
    dispatch_writing) and has no turn_result counts at its worst case: its
    turn cap, and the session's budget as its spend."""

    def started(self, h):
        """A dispatch written and confirmed, the turn running, no result."""
        d, text = h.dispatch()
        h.feed(fx.turn(h.sid, d, text, cwd=CWD, prefix=d[:6])[:5])
        self.assertEqual(h.js.state, "running")
        return d

    def test_writing_comes_before_written(self):
        h = Harness()
        d = fx.new_uuid()
        h.record("dispatch_accepted", {"dispatch_id": d, "text_sha256": "b" * 64, "length": 1,
                                       "approval": {"kind": "preview", "id": "p"}})
        with self.assertRaises(sj.JournalCorrupt):
            h.record("dispatch_written", {"dispatch_id": d})
        for cap in (0, sj.TURN_CAP_MAX + 1, True, "200"):
            with self.subTest(cap=cap), self.assertRaises(sj.JournalCorrupt):
                h.record("dispatch_writing", {"dispatch_id": d, "turn_cap": cap})   # schema refuses it
        h.record("dispatch_writing", {"dispatch_id": d, "turn_cap": 7})
        self.assertEqual((h.js.state, h.js.turns[d].status, h.js.unfinished()), ("writing", "writing", [d]))
        h.record("dispatch_written", {"dispatch_id": d})
        self.assertEqual((h.js.state, h.js.turns[d].status), ("sent", "written"))

    def test_every_way_a_sent_dispatch_can_end_without_a_result(self):
        endings = {
            "no_progress": lambda h, d: h.record("dispatch_failed", {"dispatch_id": d, "reason": "no_progress"}),
            "turn_timeout": lambda h, d: h.record("dispatch_failed", {"dispatch_id": d, "reason": "turn_timeout"}),
            "response_cap": lambda h, d: h.record("dispatch_failed", {"dispatch_id": d, "reason": "response_cap"}),
            "process_exited": lambda h, d: (h.record("dispatch_failed", {"dispatch_id": d, "reason": "process_exited"}),
                                            h.record("exited", {"returncode": 1, "signal": None, "stderr_tail": ""})),
            "protocol_error": lambda h, d: h.record("protocol_error", {"reason": "bad_json", "detail": ""}),
            "recovered": lambda h, d: h.record("recovered", {"process": "gone"}),
            "journal just stops": lambda h, d: None,
        }
        for name, end in endings.items():
            with self.subTest(ending=name):
                h = Harness()
                h.run_turn(cost=0.05)                                     # one finished turn first
                d = self.started(h)
                end(h, d)
                self.assertEqual(h.js.unfinished(), [d])
                self.assertEqual(h.js.counted_responses, 1 + TURN_CAP)
                self.assertEqual(h.js.counted_cost, 20.0)                # the session's budget_usd
                self.assertEqual((h.js.responses, h.js.cost), (1, 0.05))   # what was observed stays apart
        for reason in ("not_confirmed", "partial_write"):
            with self.subTest(ending=reason):
                h = Harness()
                d, _ = h.dispatch() if reason == "not_confirmed" else (None, None)
                if reason == "partial_write":
                    d = fx.new_uuid()
                    h.record("dispatch_accepted", {"dispatch_id": d, "text_sha256": "b" * 64, "length": 1,
                                                   "approval": {"kind": "preview", "id": "p"}})
                    h.record("dispatch_writing", {"dispatch_id": d, "turn_cap": 9})
                h.record("dispatch_failed", {"dispatch_id": d, "reason": reason})
                cap = TURN_CAP if reason == "not_confirmed" else 9
                self.assertEqual((h.js.counted_responses, h.js.counted_cost), (cap, 20.0))

    def test_what_never_reached_the_cli_or_has_a_result_counts_exactly(self):
        h = Harness()
        d = fx.new_uuid()
        h.record("dispatch_accepted", {"dispatch_id": d, "text_sha256": "b" * 64, "length": 1,
                                       "approval": {"kind": "preview", "id": "p"}})
        h.record("exited", {"returncode": 0, "signal": None, "stderr_tail": ""})   # never written
        self.assertEqual((h.js.unfinished(), h.js.counted_responses, h.js.counted_cost), ([], 0, 0.0))
        h = Harness()
        d, text = h.dispatch()
        h.feed(fx.turn(h.sid, d, text, cwd=CWD, prefix="nc", cost=0.07)[:-1])     # result, no completed
        h.record("dispatch_failed", {"dispatch_id": d, "reason": "no_completed"})
        self.assertEqual((h.js.unfinished(), h.js.counted_responses, h.js.counted_cost), ([], 1, 0.07))

    def test_recovered_ends_the_session(self):
        h = Harness()
        d = self.started(h)
        h.record("recovered", {"process": "alive"})
        self.assertEqual((h.js.state, h.js.turns[d].failed), ("recovered", "daemon_restart"))
        self.assertFalse(sj.turn_validity(h.js, d)[0])
        for kind, data in (("recovered", {"process": "gone"}),
                           ("exited", {"returncode": 0, "signal": None, "stderr_tail": ""})):
            with self.subTest(after=kind), self.assertRaises(sj.JournalCorrupt):
                h.record(kind, data)
        for bad in ({"process": "dead"}, {"process": "gone", "x": 1}, {}):
            with self.subTest(bad=bad), self.assertRaises(sj.JournalCorrupt):
                Harness().record("recovered", bad)


class HappyPathTests(unittest.TestCase):
    def test_result_text_must_be_a_valid_string(self):
        for bad in (None, 7, {"text": "missing"}, "\ud800"):
            with self.subTest(result=repr(bad)):
                h = Harness()
                d, text = h.dispatch()
                events = fx.turn(h.sid, d, text, cwd=CWD, prefix="badresult")
                result = next(e for e in events if e.get("type") == "result")
                result["result"] = bad
                with self.assertRaises(sp.ProtocolError) as cm:
                    h.feed(events)
                h.record("protocol_error", {"reason": cm.exception.reason, "detail": cm.exception.detail})
                self.assertEqual(h.js.state, "error")
                self.assertIsNone(h.js.turns[d].result)
                self.assertFalse(h.validity(d)[0])

    def test_invalid_unicode_in_tool_input_is_a_protocol_error(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="badunicode")
        tool = next(x for e in events if e.get("type") == "assistant"
                    for x in e["message"]["content"] if x.get("type") == "tool_use")
        tool["input"] = {"bad": "\ud800"}
        with self.assertRaises(sp.ProtocolError) as cm:
            h.feed(events)
        self.assertEqual(cm.exception.reason, "bad_json")

    def test_invalid_unicode_in_nested_structured_output_is_a_protocol_error(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="badstructuredunicode")
        result = next(e for e in events if e.get("type") == "result")
        result["structured_output"] = {"nested": ["\ud800"]}
        with self.assertRaises(sp.ProtocolError) as cm:
            h.feed(events)
        self.assertEqual(cm.exception.reason, "bad_json")

    def test_invalid_unicode_in_event_key_is_a_protocol_error(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="badkeyunicode")
        result = next(e for e in events if e.get("type") == "result")
        result["\ud800"] = "value"
        with self.assertRaises(sp.ProtocolError) as cm:
            h.feed(events)
        self.assertEqual(cm.exception.reason, "bad_json")

    def test_journal_rejects_null_result_text_unless_it_was_too_large(self):
        h = Harness()
        d = h.run_turn()
        data = dict(h.js.turns[d].result)
        self.assertTrue(sj.SCHEMAS["turn_result"](data))
        data["result_text"], data["result_too_large"] = None, False
        self.assertFalse(sj.SCHEMAS["turn_result"](data))

    def test_an_oversized_result_text_does_not_invalidate_the_turn(self):
        # Planner ruling (part 2 review A1): design 2.5 records an oversized
        # result as result_text=null, result_too_large=true; the report is the
        # structured_output, so the turn stays valid.
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="big")
        result = next(e for e in events if e.get("type") == "result")
        result["result"] = "x" * (sp.MAX_RESULT_TEXT + 1)
        h.feed(events)
        r = h.js.turns[d].result
        self.assertEqual((r["result_text"], r["result_too_large"]), (None, True))
        self.assertEqual(h.validity(d), (True, []))
        self.assertEqual(r["structured_output"], fx.report(d))
        self.assertIsNone(executor_report.problem(r["structured_output"], d))
        self.assertLess(max(len(x) for x in h.records), sj.MAX_LINE)       # the journal line stays small

    def test_two_valid_turns(self):
        h = Harness()
        d1 = h.run_turn()
        self.assertEqual(h.js.state, "idle")
        self.assertEqual(h.validity(d1), (True, []))
        d2 = h.run_turn(responses=[[{"type": "tool_use", "id": "toolu_b_bash", "name": "Bash",
                                     "input": {"command": "ls"}}],
                                   [{"type": "tool_use", "id": "toolu_b_so", "name": "StructuredOutput",
                                     "input": fx.report("PLACEHOLDER")}]])
        self.assertFalse(h.validity(d2)[0])                         # the placeholder dispatch id is wrong
        self.assertEqual(h.js.result_index, 1)
        self.assertEqual(h.js.responses, 1 + 2)
        self.assertTrue(h.js.closed_reasons)                         # an invalid turn stops dispatching (A-1)

    def later_cases(self, change, *, first=False):
        """One turn whose later (or first) assistant events get ``change``;
        returns (valid, harness, dispatch) or the ProtocolError."""
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix=d[:6])
        assistants = [e for e in events if e.get("type") == "assistant"]
        self.assertGreaterEqual(len(assistants), 2)
        for e in (assistants[:1] if first else assistants[1:]):
            change(e, d)
        try:
            h.feed(events)
        except sp.ProtocolError as exc:
            # The daemon records it; the turn can then never be valid.
            h.record("protocol_error", {"reason": exc.reason, "detail": exc.detail})
            ok, reasons = h.validity(d)
            self.assertFalse(ok)
            return exc
        return h.validity(d)

    def test_v29_6_later_assistant_attribution(self):
        # Design v29.6 (stream probe 2026-10-08): absent or null on later
        # events is fine; any non-null value is not; the first must carry d.
        def omit(e, d):
            del e["user_message_uuid"], e["user_message_uuids"]

        def null(e, d):
            e["user_message_uuid"] = e["user_message_uuids"] = None

        def wrong(e, d):
            e["user_message_uuid"], e["user_message_uuids"] = fx.new_uuid(), [fx.new_uuid()]

        def same_as_d(e, d):
            e["user_message_uuid"], e["user_message_uuids"] = d, [d]

        def only_one_field(e, d):
            del e["user_message_uuid"]
            e["user_message_uuids"] = [d]
        self.assertEqual(self.later_cases(omit), (True, []))
        self.assertEqual(self.later_cases(null), (True, []))
        for name, change in (("wrong value", wrong), ("equal to d", same_as_d), ("one field set", only_one_field)):
            with self.subTest(case=name):
                result = self.later_cases(change)
                self.assertIsInstance(result, sp.ProtocolError)
                self.assertEqual(result.reason, "attribution")
        result = self.later_cases(omit, first=True)                       # the first must carry both
        self.assertIsInstance(result, sp.ProtocolError)
        self.assertEqual(result.reason, "missing_field")

    def test_absent_attribution_is_journaled_as_null(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="j")
        for e in [e for e in events if e.get("type") == "assistant"][1:]:
            del e["user_message_uuid"], e["user_message_uuids"]
        h.feed(events)
        later = h.js.turns[d].result["assistant_events"][1:]
        self.assertTrue(later)
        self.assertTrue(all(e["user_message_uuid"] is None and e["user_message_uuids"] is None for e in later))

    def test_bash_then_report_with_two_responses(self):
        h = Harness()
        d, text = h.dispatch()
        rep = fx.report(d)
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="x", responses=[
            [{"type": "thinking", "thinking": "."}, {"type": "tool_use", "id": "t1", "name": "Bash",
                                                     "input": {"command": "ls"}}],
            [{"type": "tool_use", "id": "t2", "name": "StructuredOutput", "input": rep}]], rep=rep)
        h.feed(events)
        self.assertEqual(h.validity(d), (True, []))

    def test_journal_bytes_read_back_to_the_same_state(self):
        h = Harness()
        d = h.run_turn()
        tmp = tempfile.mkdtemp(prefix="vbsp-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, sj.JOURNAL_NAME), "wb") as f:
            f.write(b"".join(h.records))
        os.chmod(os.path.join(tmp, sj.JOURNAL_NAME), 0o600)
        fd = os.open(tmp, os.O_RDONLY)
        try:
            res = sj.read(fd, IDENTITY)
        finally:
            os.close(fd)
        self.assertEqual(res.problem, "")
        self.assertEqual((res.state.state, res.state.result_index), ("idle", 0))
        self.assertTrue(sj.turn_validity(res.state, d, executor_report.problem)[0])


class ProtocolErrorTests(unittest.TestCase):
    """Each case breaks one rule; the tracker raises ProtocolError."""

    def broken(self, mutate):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="p")
        mutate(events, d, h)
        with self.assertRaises(sp.ProtocolError) as cm:
            h.feed(events)
        return cm.exception.reason

    def find(self, events, pred):
        return next(i for i, e in enumerate(events) if pred(e))

    def test_cases(self):
        is_type = lambda t, **kw: (lambda e: e.get("type") == t and all(e.get(k) == v for k, v in kw.items()))
        cases = {
            "session_mismatch": lambda ev, d, h: ev[3].update(session_id=fx.new_uuid()),
            "bad uuid": lambda ev, d, h: ev[3].update(uuid="not-a-uuid"),
            "uppercase uuid": lambda ev, d, h: ev[3].update(uuid=ev[3]["uuid"].upper()),
            "duplicate uuid": lambda ev, d, h: ev[3].update(uuid=ev[2]["uuid"]),
            "init tools": lambda ev, d, h: ev[2].update(tools=["Bash", "StructuredOutput", "Edit"]),
            "init tools duplicated": lambda ev, d, h: ev[2].update(tools=["Bash", "Bash", "StructuredOutput"]),
            "init permission": lambda ev, d, h: ev[2].update(permissionMode="bypassPermissions"),
            "init mcp": lambda ev, d, h: ev[2].update(mcp_servers=[{"name": "x"}]),
            "init version": lambda ev, d, h: ev[2].update(claude_code_version="2.1.291"),
            "init key source": lambda ev, d, h: ev[2].update(apiKeySource="ANTHROPIC_API_KEY"),
            "init cwd": lambda ev, d, h: ev[2].update(cwd="/elsewhere"),
            "init model": lambda ev, d, h: ev[2].update(model="claude-other-1"),
            "init before started": lambda ev, d, h: ev.insert(1, ev.pop(2)),
            "replay before init": lambda ev, d, h: ev.insert(2, ev.pop(4)),
            "lifecycle for another dispatch": lambda ev, d, h: ev[0].update(command_uuid=fx.new_uuid()),
            "replay text differs": lambda ev, d, h: ev[4]["message"]["content"][0].update(text="other"),
            "replay uuid differs": lambda ev, d, h: ev[4].update(uuid=fx.new_uuid()),
            "thinking for another dispatch": lambda ev, d, h: ev[3].update(user_message_uuid=fx.new_uuid()),
            "first assistant unattributed": lambda ev, d, h: ev[5].update(user_message_uuid=None,
                                                                          user_message_uuids=None),
            "later assistant attributed": lambda ev, d, h: ev[6].update(user_message_uuid=d, user_message_uuids=[d]),
            "one request two messages": lambda ev, d, h: ev[6]["message"].update(id="msg_other"),
            "result for another dispatch": lambda ev, d, h: ev[-2].update(user_message_uuids=[fx.new_uuid()]),
            "result index skips": lambda ev, d, h: ev[-2].update(result_index=1),
            "event between result and completed": lambda ev, d, h: ev.insert(-1, {
                "type": "rate_limit_event", "rate_limit_info": {}, "session_id": h.sid, "uuid": fx.new_uuid()}),
            "rate limit before replay": lambda ev, d, h: ev.insert(3, {
                "type": "rate_limit_event", "rate_limit_info": {}, "session_id": h.sid, "uuid": fx.new_uuid()}),
            "result before replay": lambda ev, d, h: ev.insert(3, ev.pop(-2)),
            "unknown tool result id": lambda ev, d, h: ev[7]["message"]["content"][0].update(tool_use_id="nope"),
            "two results for one call": lambda ev, d, h: ev[7]["message"]["content"].append(
                dict(ev[7]["message"]["content"][0])),
            "duplicate tool_use id": lambda ev, d, h: ev.insert(7, {**ev[6], "uuid": fx.new_uuid()}),
            "num_turns bool": lambda ev, d, h: ev[-2].update(num_turns=True),
            "num_turns huge": lambda ev, d, h: ev[-2].update(num_turns=10 ** 5),
            "cost NaN": lambda ev, d, h: ev[-2].update(total_cost_usd=NAN),
            "cost inf": lambda ev, d, h: ev[-2].update(total_cost_usd=INF),
            "cost negative": lambda ev, d, h: ev[-2].update(total_cost_usd=-1),
            "cost bool": lambda ev, d, h: ev[-2].update(total_cost_usd=True),
            "queued turns": lambda ev, d, h: ev[-2].update(queued_turn_count=1),
            "structured output list": lambda ev, d, h: ev[-2].update(structured_output=[]),
            "estimated tokens negative": lambda ev, d, h: ev[3].update(estimated_tokens=-1),
            "estimated tokens bool": lambda ev, d, h: ev[3].update(estimated_tokens=True),
            "estimated tokens huge": lambda ev, d, h: ev[3].update(estimated_tokens=10 ** 9),
            "assistant without request id": lambda ev, d, h: ev[5].pop("request_id"),
            "tool_use without input": lambda ev, d, h: ev[6]["message"]["content"][0].pop("input"),
            "replay not marked": lambda ev, d, h: ev[4].update(isReplay=False),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertIn(self.broken(mutate), sp.PROTOCOL_REASONS)

    def test_event_while_idle(self):
        h = Harness()
        with self.assertRaises(sp.ProtocolError) as cm:
            h.tracker.on_event({"type": "rate_limit_event", "session_id": h.sid, "uuid": fx.new_uuid()})
        self.assertEqual(cm.exception.reason, "event_while_idle")

    def test_cost_never_decreases_and_ids_never_return(self):
        h = Harness()
        h.run_turn(cost=0.5)
        d, text = h.dispatch()
        with self.assertRaises(sp.ProtocolError):
            h.feed(fx.turn(h.sid, d, text, cwd=CWD, result_index=1, cost=0.4, prefix="q"))
        h2 = Harness()
        h2.run_turn(prefix="same")
        d, text = h2.dispatch()
        with self.assertRaises(sp.ProtocolError) as cm:          # request ids of an earlier turn
            h2.feed(fx.turn(h2.sid, d, text, cwd=CWD, result_index=1, cost=1, prefix="same"))
        self.assertEqual(cm.exception.reason, "response_ids")


class InvalidTurnTests(unittest.TestCase):
    """The turn completes; validity says no, with a reason."""

    def invalid(self, h=None, d=None, **kw):
        """A completed turn turn_validity calls invalid: it closes the
        session, and the next dispatch is refused (part 2 review A-1,
        design 6: one failure stops the flow)."""
        h = h or Harness()
        d = d or h.run_turn(**kw)
        ok, reasons = h.validity(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertEqual(h.js.state, "idle")                          # it did complete
        self.assertTrue(h.js.closed_reasons, reasons)
        with self.assertRaises(sj.JournalCorrupt):
            h.record("dispatch_accepted", {"dispatch_id": fx.new_uuid(), "text_sha256": "b" * 64, "length": 1,
                                           "approval": {"kind": "preview", "id": "p"}})
        return reasons

    def test_cases(self):
        table = {
            "result not success": dict(subtype="error_max_budget_usd", is_error=True),
            "result is_error": dict(is_error=True),
            "no StructuredOutput": dict(responses=[[{"type": "thinking", "thinking": "."}]]),
            "StructuredOutput is_error": dict(structured_is_error=True),
            "StructuredOutput failed": dict(structured_result="Structured output failed"),
            "structured_output differs": dict(structured_output={"other": 1}),
            "no structured_output": dict(structured_output=None),
            "num_turns differs": dict(num_turns=5),
            "report schema fails": dict(rep={"v": 1}),
        }
        for name, kw in table.items():
            with self.subTest(reason=name):
                self.invalid(**kw)
        with self.subTest(reason="init shows another model"):
            h = Harness(identity={**IDENTITY, "model_id": "claude-other-1"})
            self.assertIn("init 的模型不是這次啟動與接受時的模型", self.invalid(h))
        with self.subTest(reason="an unknown event field"):
            h = Harness()
            d, text = h.dispatch()
            events = fx.turn(h.sid, d, text, cwd=CWD, prefix="x")
            events[3]["surprise"] = 1                                     # thinking_tokens with an extra field
            h.feed(events)
            self.assertIn("出現未知種類或多餘欄位", self.invalid(h, d))

    def test_tool_without_result(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="t")
        dangling = copy.deepcopy(events[6])
        dangling["uuid"] = fx.new_uuid()
        dangling["message"]["content"] = [{"type": "tool_use", "id": "dangling", "name": "Bash", "input": {}}]
        events.insert(8, dangling)
        h.feed(events)
        self.assertIn("有工具呼叫沒有結果", self.invalid(h, d))

    def test_disallowed_tool_closes_the_session(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="u", responses=[
            [{"type": "tool_use", "id": "e1", "name": "Edit", "input": {}},
             {"type": "tool_use", "id": "so", "name": "StructuredOutput", "input": fx.report(d)}]],
            rep=fx.report(d))
        h.feed(events)
        self.assertFalse(h.validity(d)[0])
        self.assertTrue(h.js.closed_reasons)

    def test_anomalies_close_the_session(self):
        for name, extra in (("unknown type", {"type": "telemetry_event"}), ("unknown system", {"type": "system",
                                                                                                "subtype": "hooks"})):
            with self.subTest(anomaly=name):
                h = Harness()
                d, text = h.dispatch()
                events = fx.turn(h.sid, d, text, cwd=CWD, prefix="v")
                events.insert(7, {**extra, "session_id": h.sid, "uuid": fx.new_uuid()})
                h.feed(events)
                self.assertFalse(h.validity(d)[0])
                self.assertTrue(h.js.closed_reasons)
                with self.assertRaises(sj.JournalCorrupt):            # no further dispatch
                    h.dispatch()
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="w")
        events[3]["surprise"] = 1                                     # an extra field
        h.feed(events)
        self.assertFalse(h.validity(d)[0])
        self.assertIn("extra_fields", [a["reason"] for a in h.js.turns[d].anomalies])

    def test_malformed_tool_results_invalidate(self):
        for change in ({"content": ["list"]}, {"is_error": "no"}, {"extra": 1}, {"type": "text"}):
            with self.subTest(change=change):
                h = Harness()
                d, text = h.dispatch()
                events = fx.turn(h.sid, d, text, cwd=CWD, prefix="m")
                events[7]["message"]["content"][0].update(change)
                h.feed(events)
                self.assertFalse(h.validity(d)[0])


C296 = sp.VERSIONS["2.1.296"]
IDENTITY296 = {**IDENTITY, "executor_claude_version": "2.1.296"}


class VcsStateChangedTests(unittest.TestCase):
    """Claude Code 2.1.296 sends ``system/vcs_state_changed`` between a tool call and its result when a tool changed
    the repository (S3 real end-to-end, run 1; fields from tools/stream_capture.py)."""

    def vcs(self, h, **over):
        e = {"type": "system", "subtype": "vcs_state_changed", "kind": "commit", "branch": "main", "cwd": CWD,
             "session_id": h.sid, "uuid": fx.new_uuid()}
        e.update(over)
        return e

    def turn_with(self, h, event, **kw):
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="g", version="2.1.296", extra_tool=event, **kw)
        return d, events

    def harness(self):
        return Harness(consts=C296, identity=IDENTITY296)

    def test_the_event_is_accepted_and_is_neither_a_response_nor_an_anomaly(self):
        h = self.harness()
        d, events = self.turn_with(h, self.vcs(h))
        h.feed(events)
        self.assertTrue(h.validity(d)[0], h.validity(d))
        self.assertEqual(h.js.turns[d].anomalies, [])
        self.assertEqual(h.tracker.total_responses, 1)                  # the one model response, nothing from this event
        self.assertFalse(h.js.closed_reasons)
        h.dispatch()                                                    # the session takes the next dispatch

    def test_every_other_system_subtype_is_still_an_unknown_type(self):
        h = self.harness()
        d, events = self.turn_with(h, self.vcs(h, subtype="hooks"))
        h.feed(events)
        self.assertFalse(h.validity(d)[0])
        self.assertIn("unknown_type", [a["reason"] for a in h.js.turns[d].anomalies])

    def test_a_version_without_the_entry_does_not_know_it(self):
        h = Harness()                                                   # the 2.1.292 constants
        d, events = self.turn_with(h, self.vcs(h))
        for ev in events:                                               # (2.1.292 sessions report 2.1.292)
            if ev.get("subtype") == "init":
                ev["claude_code_version"] = "2.1.292"
        h.feed(events)
        self.assertFalse(h.validity(d)[0])
        self.assertIn("unknown_type", [a["reason"] for a in h.js.turns[d].anomalies])

    def test_the_work_directory_and_anything_below_it_are_accepted(self):
        for cwd in (CWD, CWD + "/", CWD + "/sub", CWD + "/sub/deeper", CWD + "/./sub", CWD + "/sub/../other"):
            with self.subTest(cwd=cwd):
                h = self.harness()
                d, events = self.turn_with(h, self.vcs(h, cwd=cwd))
                h.feed(events)
                self.assertTrue(h.validity(d)[0], h.validity(d))

    def test_assistant_events_with_the_ingest_context_are_accepted_for_2_1_296_only(self):
        for consts, identity, version, ok in ((C296, IDENTITY296, "2.1.296", True), (C, IDENTITY, "2.1.292", False)):
            with self.subTest(version=version):
                h = Harness(consts=consts, identity=identity)
                d, text = h.dispatch()
                events = fx.turn(h.sid, d, text, cwd=CWD, prefix="i", version=version)
                for ev in events:
                    if ev["type"] == "assistant":
                        ev["wire_ingest_context"] = {"toolu_x": {"cwd": CWD}}
                h.feed(events)
                self.assertEqual(h.validity(d)[0], ok)
                if not ok:
                    self.assertEqual({a["reason"] for a in h.js.turns[d].anomalies}, {"extra_fields"})
                    self.assertEqual(h.js.turns[d].anomalies[0]["fields"], ["wire_ingest_context"])

    def test_an_extra_field_is_an_anomaly(self):
        h = self.harness()
        d, events = self.turn_with(h, self.vcs(h, surprise=1))
        h.feed(events)
        self.assertFalse(h.validity(d)[0])
        self.assertIn("extra_fields", [a["reason"] for a in h.js.turns[d].anomalies])

    def test_a_bad_shape_or_place_is_a_protocol_error(self):
        for name, change, reason in (("kind missing", {"kind": None}, "missing_field"),
                                     ("branch not a string", {"branch": 5}, "missing_field"),
                                     ("too long", {"cwd": "/" + "x" * 600}, "missing_field"),
                                     ("another directory", {"cwd": "/private/tmp/elsewhere"}, "attribution"),
                                     ("a similar prefix", {"cwd": CWD + "2"}, "attribution"),
                                     ("the parent", {"cwd": os.path.dirname(CWD)}, "attribution"),
                                     ("a sibling", {"cwd": os.path.dirname(CWD) + "/other"}, "attribution"),
                                     ("out by ..", {"cwd": CWD + "/../elsewhere"}, "attribution"),
                                     ("not absolute", {"cwd": "vbear-task"}, "attribution"),
                                     ("another session", {"session_id": fx.new_uuid()}, "session_mismatch")):
            with self.subTest(case=name):
                h = self.harness()
                d, events = self.turn_with(h, self.vcs(h, **change))
                with self.assertRaises(sp.ProtocolError) as cm:
                    h.feed(events)
                self.assertEqual(cm.exception.reason, reason)
        h = self.harness()
        d, text = h.dispatch()
        with self.assertRaises(sp.ProtocolError) as cm:                  # before the turn's init: not "running"
            h.feed([self.vcs(h)])
        self.assertEqual(cm.exception.reason, "out_of_order")


class PermissionDeniedTests(unittest.TestCase):
    """2.1.296 ``system/permission_denied``: a refused tool call is the safety mechanism working. The turn stays
    valid; what is recorded is the tool's name and the type of the decision, filtered, never the message."""

    PREFIX = "p"

    def event(self, h, **over):
        e = {"type": "system", "subtype": "permission_denied", "tool_name": "Bash",
             "tool_use_id": f"toolu_{self.PREFIX}_so", "decision_reason_type": "mode",
             "decision_reason": "SECRET-REASON-TEXT", "message": "SECRET-MESSAGE-TEXT",
             "session_id": h.sid, "uuid": fx.new_uuid()}
        e.update(over)
        return e

    def feed(self, h, *events, **kw):
        d, text = h.dispatch()
        evs = fx.turn(h.sid, d, text, cwd=CWD, prefix=self.PREFIX, version="2.1.296", **kw)
        at = next(i for i, e in enumerate(evs) if e["type"] == "rate_limit_event")
        evs[at:at] = list(events)
        h.feed(evs)
        return d

    def harness(self):
        return Harness(consts=C296, identity=IDENTITY296)

    def test_a_denial_is_recorded_by_name_and_the_turn_stays_valid(self):
        h = self.harness()
        d = self.feed(h, self.event(h), self.event(h, tool_name="Edit", decision_reason_type="rule"))
        self.assertTrue(h.validity(d)[0], h.validity(d))
        turn = h.js.turns[d]
        self.assertEqual((turn.denial_count, turn.anomalies), (2, []))
        self.assertEqual(turn.denials, [{"tool_name": "Bash", "reason_type": "mode"},
                                        {"tool_name": "Edit", "reason_type": "rule"}])
        self.assertEqual(h.tracker.total_responses, 1)                     # not a model response
        raw = b"".join(h.records)
        self.assertNotIn(b"SECRET-REASON-TEXT", raw)                       # no text of the decision is kept
        self.assertNotIn(b"SECRET-MESSAGE-TEXT", raw)
        h.dispatch()                                                       # the session takes the next dispatch

    def test_the_names_are_filtered_and_the_list_is_bounded(self):
        h = self.harness()
        d = self.feed(h, self.event(h, tool_name="bad name; rm -rf", decision_reason_type="x" * 65))
        self.assertEqual(h.js.turns[d].denials, [{"tool_name": "?", "reason_type": "?"}])
        h = self.harness()
        d = self.feed(h, *[self.event(h) for _ in range(20)])
        turn = h.js.turns[d]
        self.assertEqual((turn.denial_count, len(turn.denials)), (20, sp.MAX_ANOMALY_FIELDS))
        self.assertTrue(h.validity(d)[0])

    def test_a_denial_that_does_not_fit_the_turn_is_a_protocol_error(self):
        cases = (("a call this turn did not make", {"tool_use_id": "toolu_other"}, "tool_result_unknown"),
                 ("no tool name", {"tool_name": None}, "missing_field"),
                 ("no reason type", {"decision_reason_type": 7}, "missing_field"),
                 ("another session", {"session_id": fx.new_uuid()}, "session_mismatch"))
        for name, change, reason in cases:
            with self.subTest(case=name):
                h = self.harness()
                with self.assertRaises(sp.ProtocolError) as cm:
                    self.feed(h, self.event(h, **change))
                self.assertEqual(cm.exception.reason, reason)
        h = self.harness()
        d, text = h.dispatch()
        with self.assertRaises(sp.ProtocolError) as cm:                    # before the turn is running
            h.feed([self.event(h)])
        self.assertEqual(cm.exception.reason, "out_of_order")

    def test_a_version_without_the_entry_keeps_it_an_unknown_type_and_names_its_fields(self):
        h = Harness()
        d, text = h.dispatch()
        evs = fx.turn(h.sid, d, text, cwd=CWD, prefix=self.PREFIX)
        at = next(i for i, e in enumerate(evs) if e["type"] == "rate_limit_event")
        evs.insert(at, self.event(h))
        h.feed(evs)
        self.assertFalse(h.validity(d)[0])
        a = h.js.turns[d].anomalies[0]
        self.assertEqual(a["reason"], "unknown_type")
        self.assertIn("decision_reason_type", a["fields"])
        self.assertNotIn(b"SECRET-MESSAGE-TEXT", b"".join(h.records))

    def test_the_journal_record_is_names_only(self):
        d = fx.new_uuid()
        schema = sj.SCHEMAS["permission_denied"]
        self.assertTrue(schema({"dispatch_id": d, "tool_name": "Bash", "reason_type": "mode"}))
        self.assertTrue(schema({"dispatch_id": d, "tool_name": "?", "reason_type": "?"}))
        for bad in ({"dispatch_id": d, "tool_name": "Bash"},
                    {"dispatch_id": d, "tool_name": "Bash", "reason_type": "a b"},
                    {"dispatch_id": d, "tool_name": "x" * 65, "reason_type": "mode"},
                    {"dispatch_id": d, "tool_name": "Bash", "reason_type": "mode", "message": "text"},
                    {"dispatch_id": d, "tool_name": 5, "reason_type": "mode"}):
            with self.subTest(record=str(bad)[:50]):
                self.assertFalse(schema(bad))


class AnomalyFieldNameTests(unittest.TestCase):
    """A turn_anomaly names the unexpected top-level fields: names only, bounded, never a value."""

    def run_with(self, change):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="n")
        change(events)
        h.feed(events)
        return h, d

    def test_the_names_are_recorded_and_the_values_are_not(self):
        h, d = self.run_with(lambda ev: ev[3].update({"surprise_field": "VALUE-THAT-MUST-NOT-APPEAR", "n_2": 7}))
        anomaly = h.js.turns[d].anomalies[0]
        self.assertEqual((anomaly["reason"], anomaly["fields"]), ("extra_fields", ["n_2", "surprise_field"]))
        self.assertNotIn(b"VALUE-THAT-MUST-NOT-APPEAR", b"".join(h.records))

    def test_more_than_the_limit_is_cut_and_a_bad_name_is_a_question_mark(self):
        many = {f"f{i:02d}": i for i in range(40)}
        h, d = self.run_with(lambda ev: ev[3].update(many))
        fields = h.js.turns[d].anomalies[0]["fields"]
        self.assertEqual(len(fields), sp.MAX_ANOMALY_FIELDS)
        self.assertEqual(fields, sorted(many)[:sp.MAX_ANOMALY_FIELDS])
        bad = {"bad-name!": 1, "x" * 65: 2, "ключ": 3, "with space": 4, "ok_name": 5}
        h, d = self.run_with(lambda ev: ev[3].update(bad))
        self.assertEqual(sorted(h.js.turns[d].anomalies[0]["fields"]), ["?", "?", "?", "?", "ok_name"])
        self.assertNotIn("bad-name".encode(), b"".join(h.records))

    def test_an_unknown_kind_names_all_of_its_top_level_fields(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="u")
        events.insert(7, {"type": "telemetry_event", "payload": "SECRET-PAYLOAD", "session_id": h.sid,
                          "uuid": fx.new_uuid()})
        h.feed(events)
        anomaly = h.js.turns[d].anomalies[0]
        self.assertEqual((anomaly["reason"], anomaly["fields"]), ("unknown_type", ["payload", "session_id", "type",
                                                                                     "uuid"]))
        self.assertNotIn(b"SECRET-PAYLOAD", b"".join(h.records))

    def test_an_extra_field_of_a_tool_result_item_is_named_too(self):
        h, d = self.run_with(lambda ev: ev[7]["message"]["content"][0].update({"extra_item": "x"}))
        anomaly = h.js.turns[d].anomalies[0]
        self.assertEqual((anomaly["event_type"], anomaly["fields"]), ("user/tool_result", ["extra_item"]))

    def test_the_schema_bounds_the_names_and_old_records_stay_valid(self):
        d = fx.new_uuid()
        base = {"dispatch_id": d, "reason": "extra_fields", "event_type": "assistant"}
        schema = sj.SCHEMAS["turn_anomaly"]
        self.assertTrue(schema(base))                                    # a record from before the key existed
        self.assertTrue(schema({**base, "fields": ["a", "?", "b_2"]}))
        for bad in ("a", [1], ["a-b"], ["x" * 65], ["a"] * 17, [""], ["?x"]):
            with self.subTest(fields=bad):
                self.assertFalse(schema({**base, "fields": bad}))
        self.assertFalse(schema({**base, "fields": [], "extra": 1}))


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vbsj-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, lines):
        path = os.path.join(self.dir, sj.JOURNAL_NAME)
        with open(path, "wb") as f:
            f.write(b"".join(lines))
        os.chmod(path, 0o600)

    def read(self):
        fd = os.open(self.dir, os.O_RDONLY)
        try:
            return sj.read(fd)
        finally:
            os.close(fd)

    def good(self):
        h = Harness()
        h.run_turn()
        return list(h.records)

    def test_round_trip(self):
        self.write(self.good())
        self.assertEqual(self.read().problem, "")

    def test_tampering_is_corruption(self):
        lines = self.good()
        mutations = {
            "a byte changed": lambda ls: ls.__setitem__(1, ls[1].replace(b'"preview"', b'"automation"')),
            "a line removed": lambda ls: ls.pop(3),
            "lines swapped": lambda ls: ls.insert(4, ls.pop(5)),
            "a line repeated": lambda ls: ls.insert(4, ls[3]),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                ls = list(lines)
                mutate(ls)
                self.write(ls)
                res = self.read()
                self.assertTrue(res.problem.startswith("日誌損壞"), res.problem)

    def test_truncated_last_line(self):
        lines = self.good()
        lines[-1] = lines[-1][:-5]
        self.write(lines)
        res = self.read()
        self.assertTrue(res.truncated_tail)
        self.assertEqual(res.problem, "日誌末筆不完整")

    def rewrite(self, transform):
        """Re-encode the good journal after ``transform(records)``, with
        valid sha256s, so only the semantic check can object."""
        recs = [json.loads(l) for l in self.good()]
        recs = transform(recs)
        out = []
        enc = lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        for r in recs:
            body = {k: r[k] for k in ("v", "seq", "t", "kind", "data")}
            # allow_nan: a damaged file can hold a NaN literal; the reader must refuse it.
            out.append(enc(dict(body, sha256=sp.sha256_hex(enc(body)))) + b"\n")
        self.write(out)
        return self.read()

    def test_semantic_corruption_with_valid_hashes(self):
        def kind_index(recs, kind):
            return next(i for i, r in enumerate(recs) if r["kind"] == kind)

        def drop(kind):
            def f(recs):
                i = kind_index(recs, kind)
                recs.pop(i)
                for n, r in enumerate(recs, 1):
                    r["seq"] = n
                return recs
            return f

        def edit(kind, **changes):
            def f(recs):
                recs[kind_index(recs, kind)]["data"].update(changes)
                return recs
            return f

        def edit_record(**changes):
            def f(recs):
                recs[2].update(changes)
                return recs
            return f
        cases = {
            "confirmed without written": drop("dispatch_written"),
            "result without init": drop("turn_init"),
            "result index not continuous": edit("turn_result", result_index=3),
            "result for other uuids": edit("turn_result", user_message_uuids=[fx.new_uuid()]),
            "init off the constants": edit("turn_init", permissionMode="default"),
            "extra data field": edit("dispatch_written", extra=1),
            "unknown kind": lambda recs: [*recs[:2], {**recs[2], "kind": "mystery"}, *recs[3:]],
            "v is 2": edit_record(v=2),
            "v is true": edit_record(v=True),
            "seq jumps": edit_record(seq=7),
            "time NaN": edit_record(t=NAN),
            "time before 2020": edit_record(t=1.0),
            "time far ahead": edit_record(t=time.time() + 10 * 86400),
            "time steps back": edit_record(t=1700000000.0),
            "two message ids for one request": lambda recs: [
                r if r["kind"] != "turn_result" else {**r, "data": {**r["data"], "assistant_events": [
                    *r["data"]["assistant_events"], {**r["data"]["assistant_events"][0], "message_id": "m2",
                                                     "user_message_uuid": None, "user_message_uuids": None}]}}
                for r in recs],
            "A, B, A response order": lambda recs: [
                r if r["kind"] != "turn_result" else {**r, "data": {
                    **r["data"], "num_turns": 3, "assistant_events": [
                        r["data"]["assistant_events"][0],
                        {"request_id": "req_B", "message_id": "msg_B", "user_message_uuid": None,
                         "user_message_uuids": None},
                        {**r["data"]["assistant_events"][0], "user_message_uuid": None,
                         "user_message_uuids": None}]}}
                for r in recs],
            "tool id repeated": lambda recs: [
                r if r["kind"] != "turn_result" else {**r, "data": {**r["data"], "tool_calls":
                                                                     r["data"]["tool_calls"] * 2}}
                for r in recs],
            "cost NaN": edit("turn_result", total_cost_usd=NAN),
            "dispatch accepted twice": lambda recs: [*recs[:2], recs[1], *recs[2:]],
        }
        for name, transform in cases.items():
            with self.subTest(case=name):
                res = self.rewrite(transform)
                self.assertNotEqual(res.problem, "", name)

    def test_nothing_after_exit_and_size_limit(self):
        h = Harness()
        h.record("exited", {"returncode": 0, "signal": None, "stderr_tail": ""})
        with self.assertRaises(sj.JournalCorrupt):
            h.record("protocol_error", {"reason": "bad_json", "detail": ""})
        with self.assertRaises(sj.JournalCorrupt):
            h.dispatch()
        fd = os.open(self.dir, os.O_RDONLY)
        try:
            w = sj.JournalWriter(fd)
            with mock.patch.object(sj, "MAX_JOURNAL", 200):
                with self.assertRaises(sj.JournalCorrupt):
                    w.append("session_started", {"claude_session_id": fx.new_uuid(), "pipeline_id":
                                                 "flow-0123456789ab", "cli_version": "2.1.292",
                                                 "argv_sha256": "a" * 64, "budget_usd": 20.0})
            w.close()
        finally:
            os.close(fd)


class RecoveryMatchesLiveTests(unittest.TestCase):
    """Codex S2a-2 p1 #1: what the tracker refuses live, the journal state
    machine refuses on recovery."""

    def test_a_b_a_is_refused_in_both(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="z", responses=[
            [{"type": "thinking", "thinking": "."}],
            [{"type": "thinking", "thinking": "."}],
            [{"type": "tool_use", "id": "so", "name": "StructuredOutput", "input": fx.report(d)}]],
            rep=fx.report(d))
        a_event = next(e for e in events if e.get("type") == "assistant" and e["request_id"] == "req_z_1")
        back = copy.deepcopy(a_event)
        back.update(uuid=fx.new_uuid(), user_message_uuid=None, user_message_uuids=None)
        events.insert(events.index(next(e for e in events if e.get("request_id") == "req_z_2")) + 1, back)
        with self.assertRaises(sp.ProtocolError) as cm:              # live
            h.feed(events)
        self.assertEqual(cm.exception.reason, "response_ids")
        js = sj.JournalState()                                        # recovery, from facts alone
        sid = fx.new_uuid()
        recs = [("session_started", {"claude_session_id": sid, "pipeline_id": "flow-0123456789ab",
                                     "cli_version": "2.1.292", "argv_sha256": "a" * 64, "budget_usd": 20.0}),
                ("dispatch_accepted", {"dispatch_id": d, "text_sha256": "b" * 64, "length": 1,
                                       "approval": {"kind": "preview", "id": "p"}}),
                ("dispatch_writing", {"dispatch_id": d, "turn_cap": TURN_CAP}),
                ("dispatch_written", {"dispatch_id": d}),
                ("turn_lifecycle", {"dispatch_id": d, "state": "queued"}),
                ("turn_lifecycle", {"dispatch_id": d, "state": "started"}),
                ("turn_init", {"dispatch_id": d, "permissionMode": "acceptEdits", "tools": ["Bash", "StructuredOutput"],
                               "mcp_servers": [], "model": fx.MODEL, "cwd": CWD, "claude_code_version": "2.1.292",
                               "apiKeySource": "none"}),
                ("dispatch_confirmed", {"dispatch_id": d})]
        for n, (kind, data) in enumerate(recs, 1):
            js.apply(kind, data, time.time())
        ev = lambda rid, first: {"request_id": rid, "message_id": "m" + rid, "user_message_uuid": d if first else None,
                                 "user_message_uuids": [d] if first else None}
        result = {"dispatch_id": d, "subtype": "success", "is_error": False, "num_turns": 3, "total_cost_usd": 0.1,
                  "result_index": 0, "user_message_uuids": [d],
                  "assistant_events": [ev("A", True), ev("B", False), ev("A", False)], "tool_calls": [],
                  "structured_output": None, "result_text": None, "result_too_large": False}
        with self.assertRaises(sj.JournalCorrupt):
            js.apply("turn_result", result, time.time())


class IdentityTests(unittest.TestCase):
    """Codex S2a-2 p1 R2 #2: a turn counts only when its init shows the
    manifest's model and work directory and the accepted version and model."""

    def test_wrong_identity_in_init_invalidates_and_closes(self):
        cases = {"model": {"model_id": "claude-other-1", "executor_model": "claude-other-1"},
                 "accepted model": {"executor_model": "claude-other-1"},
                 "work directory": {"workdir": "/wrong/workdir"},
                 "accepted version": {"executor_claude_version": "2.1.291"}}
        for name, change in cases.items():
            with self.subTest(case=name):
                h = Harness(identity={**IDENTITY, **change})
                d = h.run_turn()
                ok, reasons = h.validity(d)
                self.assertFalse(ok)
                self.assertTrue(any("init" in r for r in reasons), reasons)
                self.assertTrue(h.js.closed_reasons)

    def test_without_an_identity_nothing_is_valid(self):
        for identity in (None, {}, {**IDENTITY, "extra": 1}, {k: v for k, v in IDENTITY.items() if k != "workdir"}):
            with self.subTest(identity=identity):
                h = Harness(identity=identity)
                d = h.run_turn()
                ok, reasons = h.validity(d)
                self.assertFalse(ok)
                self.assertIn("無法核對執行者身分（缺少 manifest 或接受時的資料）", reasons)

    def test_recovery_with_a_rewritten_init(self):
        h = Harness()
        d = h.run_turn()
        recs = [json.loads(l) for l in h.records]
        for r in recs:
            if r["kind"] == "turn_init":
                r["data"]["model"], r["data"]["cwd"] = "claude-not-the-one", "/wrong/workdir"
        tmp = tempfile.mkdtemp(prefix="vbsi-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, sj.JOURNAL_NAME), "wb") as f:
            for r in recs:
                body = {k: r[k] for k in ("v", "seq", "t", "kind", "data")}
                f.write(sp.canonical(dict(body, sha256=sp.sha256_hex(sp.canonical(body)))) + b"\n")
        os.chmod(os.path.join(tmp, sj.JOURNAL_NAME), 0o600)
        fd = os.open(tmp, os.O_RDONLY)
        try:
            res = sj.read(fd, IDENTITY)
        finally:
            os.close(fd)
        self.assertEqual(res.problem, "")
        ok, reasons = sj.turn_validity(res.state, d, executor_report.problem)
        self.assertFalse(ok)
        self.assertIn("init 的模型不是這次啟動與接受時的模型", reasons)
        self.assertIn("init 的工作目錄不是這個任務的工作目錄", reasons)

    def test_identity_from(self):
        manifest = {"model_id": fx.MODEL, "canonical_workspace": CWD}
        accepted = {"executor_claude_version": "2.1.292", "executor_model": fx.MODEL}
        self.assertEqual(sj.identity_from(manifest, accepted), IDENTITY)
        self.assertIsNone(sj.identity_from(manifest, None))
        self.assertIsNone(sj.identity_from({}, accepted))
        self.assertIsNone(sj.identity_from({**manifest, "model_id": 5}, accepted))

    def test_tracker_checks_the_accepted_version_live(self):
        h = Harness()
        h.tracker.executor_version = "2.1.291"
        d, text = h.dispatch()
        with self.assertRaises(sp.ProtocolError) as cm:
            h.feed(fx.turn(h.sid, d, text, cwd=CWD))
        self.assertEqual(cm.exception.reason, "init_mismatch")


class SanitizeTests(unittest.TestCase):
    def test_rewrites(self):
        self.assertEqual(sp.sanitize("a\nb\tc"), "a\nb\tc")
        self.assertEqual(sp.sanitize("x\x1b[31my"), "x\\u001b[31my")
        self.assertEqual(sp.sanitize("\x7f\x85"), "\\u007f\\u0085")
        self.assertEqual(sp.sanitize("a‮b⁦c‎d؜"), "a\\u202eb\\u2066c\\u200ed\\u061c")
        self.assertEqual(sp.sanitize("zero​width﻿"), "zero\\u200bwidth\\ufeff")      # other Cf
        self.assertEqual(sp.sanitize("中文 😀 é"), "中文 😀 é")
        self.assertEqual(sp.sanitize("\r"), "\\u000d")

    def test_refusals(self):
        for bad in ("\ud800", "a\udfffb", None, 5, b"bytes"):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    sp.sanitize(bad)


class DispatchLineTests(unittest.TestCase):
    def test_exact_line_and_limit(self):
        sid, d = fx.new_uuid(), fx.new_uuid()
        line = sp.dispatch_line("hi", sid, d)
        self.assertTrue(line.endswith(b"\n"))
        obj = json.loads(line)
        self.assertEqual(obj, {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                               "parent_tool_use_id": None, "session_id": sid, "uuid": d})
        overhead = len(sp.dispatch_line("", sid, d))
        self.assertEqual(len(sp.dispatch_line("x" * (sp.MAX_DISPATCH_LINE - overhead), sid, d)), sp.MAX_DISPATCH_LINE)
        with self.assertRaises(ValueError):
            sp.dispatch_line("x" * (sp.MAX_DISPATCH_LINE - overhead + 1), sid, d)
        with self.assertRaises(ValueError):
            sp.dispatch_line("中" * 30000, sid, d)                      # bytes, not characters
        for bad in ("x", d.upper(), d + "\n"):
            with self.assertRaises(ValueError):
                sp.dispatch_line("hi", sid, bad)


class ReportTests(unittest.TestCase):
    def test_schema_v1(self):
        d = fx.new_uuid()
        self.assertIsNone(executor_report.problem(fx.report(d), d))
        bad = [None, [], {}, {**fx.report(d), "extra": 1}, fx.report(fx.new_uuid()),
               {**fx.report(d), "v": True}, {**fx.report(d), "v": 2}, {**fx.report(d), "v": 1.0},
               {**fx.report(d), "status": "finished"}, {**fx.report(d), "head": "A" * 40},
               {**fx.report(d), "head": "a" * 40 + "\n"}, {**fx.report(d), "notes": "x" * 4097},
               {**fx.report(d), "notes": "中" * 1366}, {**fx.report(d), "notes": "\ud800"},
               {**fx.report(d), "tests": {"command": "x" * 513, "result": "passed", "summary": ""}},
               {**fx.report(d), "tests": {"command": "", "result": "skipped", "summary": ""}},
               {**fx.report(d), "tests": {"command": "", "result": "passed"}},
               {**fx.report(d), "tests": {"command": "", "result": "passed", "summary": "x" * 2049}}]
        for r in bad:
            with self.subTest(report=repr(r)[:60]):
                self.assertIsNotNone(executor_report.problem(r, d))
        self.assertIsNone(executor_report.problem({**fx.report(d), "notes": "中" * 1365}, d))

    def test_the_report_request_names_the_dispatch_and_the_schema(self):
        d = fx.new_uuid()
        text = executor_report.report_request(d)
        self.assertIn(f'"v":1,"dispatch_id":"{d}"', text)
        # one JSON object with exactly the schema's fields
        shape = json.loads(text[text.index("{"):text.rindex("}") + 1])
        self.assertEqual(set(shape), set(executor_report.JSON_SCHEMA["required"]))
        self.assertEqual(set(shape["tests"]), {"command", "result", "summary"})
        # the dispatch line that carries it stays under the limit with a text of the largest accepted size
        self.assertLess(len(text.encode()), 1024)
        for bad in (None, "", "not-a-uuid", d.upper(), d + "x"):
            with self.assertRaises(ValueError):
                executor_report.report_request(bad)


if __name__ == "__main__":
    unittest.main()
