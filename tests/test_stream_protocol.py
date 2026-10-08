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


class Harness:
    """Plays the daemon: writes its own records and feeds events through the
    tracker; every record goes through encode -> strict parse -> apply."""

    def __init__(self, model=fx.MODEL):
        self.sid = fx.new_uuid()
        self.tracker = sp.EventTracker(C, self.sid, CWD, model)
        self.js = sj.JournalState()
        self.seq = 0
        self.records = []
        self.record("session_started", {"claude_session_id": self.sid, "pipeline_id": "flow-0123456789ab",
                                        "cli_version": "2.1.292", "argv_sha256": "a" * 64, "budget_usd": 20.0})

    def record(self, kind, data):
        self.seq += 1
        line = sj.encode(self.seq, time.time(), kind, data)
        parsed = strictjson.loads(line[:-1], strictjson.SESSION_LOG)
        assert parsed.ok, parsed.problem
        self.js.apply_record(parsed.value)
        self.records.append(line)

    def dispatch(self, text="please do the work"):
        d = fx.new_uuid()
        self.record("dispatch_accepted", {"dispatch_id": d, "text_sha256": sp.sha256_hex(text),
                                          "length": len(text.encode()), "approval": {"kind": "preview", "id": "p1"}})
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


class HappyPathTests(unittest.TestCase):
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
        d3 = h.run_turn(rep=None)
        self.assertTrue(h.validity(d3)[0])
        self.assertEqual(h.js.result_index, 2)
        self.assertEqual(h.js.responses, 1 + 2 + 1)

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
            res = sj.read(fd)
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

    def invalid(self, closes=False, **kw):
        h = Harness()
        d = h.run_turn(**kw)
        ok, reasons = h.validity(d)
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertEqual(bool(h.js.closed_reasons), closes, reasons)
        return reasons

    def test_cases(self):
        so = lambda d: fx.report(d)
        self.invalid(subtype="error_max_budget_usd", is_error=True)
        self.invalid(is_error=True)
        self.invalid(responses=[[{"type": "thinking", "thinking": "."}]])                     # no StructuredOutput
        self.invalid(structured_is_error=True)
        self.invalid(structured_result="Structured output failed")
        self.invalid(structured_output={"other": 1})
        self.invalid(structured_output=None)
        self.invalid(closes=True, num_turns=5)                                                  # CLI count differs
        self.invalid(rep={"v": 1})                                                              # schema v1 fails

    def test_tool_without_result(self):
        h = Harness()
        d, text = h.dispatch()
        events = fx.turn(h.sid, d, text, cwd=CWD, prefix="t")
        dangling = copy.deepcopy(events[6])
        dangling["uuid"] = fx.new_uuid()
        dangling["message"]["content"] = [{"type": "tool_use", "id": "dangling", "name": "Bash", "input": {}}]
        events.insert(8, dangling)
        h.feed(events)
        ok, reasons = h.validity(d)
        self.assertFalse(ok)
        self.assertIn("有工具呼叫沒有結果", reasons)

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


if __name__ == "__main__":
    unittest.main()
