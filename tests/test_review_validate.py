"""When a Codex review is valid (design 5.5, 5.6, v29.9): events, report and
rollout. A valid fake run (tests/review_fixtures) with one rule broken at a
time. No Codex, no model."""

import json
import unittest

from tests import review_fixtures as rf
from vbear.runtime import review_validate as rv

C = rf.C


def run_events(objs):
    t = rv.EventsTracker(C)
    for o in objs:
        t.feed(json.dumps(o).encode() if not isinstance(o, bytes) else o)
    return t.finish()


def run_rollout(recs, *, raw=None, **over):
    kw = dict(thread_id=rf.THREAD, scratch=rf.SCRATCH, model=rf.MODEL, events_usage=None, last_message=None)
    evs, good, text = rf.valid_run()
    kw["events_usage"] = evs[-1]["usage"]
    kw["last_message"] = text
    kw.update(over)
    fd = rf.rollout_fd(raw if raw is not None else recs)
    try:
        return rv.validate_rollout(fd, C, **kw)
    finally:
        import os
        os.close(fd)


class ValidRunTests(unittest.TestCase):
    def test_a_valid_run_passes_every_check(self):
        evs, recs, text = rf.valid_run()
        res = run_events(evs)
        self.assertEqual((res.thread_id, res.last_message, res.events), (rf.THREAD, text, len(evs)))
        out = run_rollout(recs)
        self.assertEqual((out.reasons, out.responses, out.turn_id), ([], 2, rf.TURN))
        self.assertEqual(len(out.sha256), 64)
        rep = rv.check_report(text, rf.COMMIT)
        self.assertEqual((rep.problems, rep.verdict, rep.base_is_ancestor), ([], "PASS", True))

    def test_the_hash_covers_the_whole_file(self):
        import hashlib
        _, recs, _ = rf.valid_run()
        raw = rf.lines(recs)
        self.assertEqual(run_rollout(recs).sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(run_rollout(None, raw=raw).size, len(raw))

    def test_fields_vbear_does_not_read_are_allowed(self):
        evs, recs, _ = rf.valid_run()
        evs[1]["surprise"] = {"a": [1, 2]}
        recs[0]["extra_top_level"] = 1
        recs[3]["payload"]["new_field"] = "x"
        run_events(evs)
        self.assertEqual(run_rollout(recs).reasons, [])


class EventsTests(unittest.TestCase):
    def broken(self, mutate):
        evs, _, _ = rf.valid_run()
        changed = mutate(evs)
        evs = changed if isinstance(changed, list) else evs
        with self.assertRaises(rv.ReviewInvalid) as cm:
            run_events(evs)
        return cm.exception

    def test_every_rule(self):
        def drop(i):
            return lambda e: e.__delitem__(i)
        cases = {
            "not json": lambda e: e.__setitem__(2, b"{not json"),
            "not an object": lambda e: e.__setitem__(2, b"[1]"),
            "duplicate key": lambda e: e.__setitem__(2, b'{"type":"turn.started","type":"turn.started"}'),
            "NaN": lambda e: e.__setitem__(5, b'{"type":"turn.completed","usage":NaN}'),
            "unknown kind": lambda e: e.insert(2, {"type": "surprise"}),
            "type not a string": lambda e: e.insert(2, {"type": 1}),
            "turn.failed": lambda e: e.insert(3, {"type": "turn.failed"}),
            "error": lambda e: e.insert(3, {"type": "error", "message": "x"}),
            "first is not thread.started": lambda e: e.insert(0, {"type": "turn.started"}),
            "thread id bad": lambda e: e[0].update(thread_id="x"),
            "thread id missing": lambda e: e[0].pop("thread_id"),
            "thread.started twice": lambda e: e.insert(1, {"type": "thread.started", "thread_id": rf.THREAD}),
            "turn.started twice": lambda e: e.insert(2, {"type": "turn.started"}),
            "item before turn.started": lambda e: e.insert(1, {"type": "item.started", "item": {"type": "x"}}),
            "item not an object": lambda e: e[2].update(item="x"),
            "item type missing": lambda e: e[2].update(item={}),
            "reply not text": lambda e: e[4]["item"].update(text=5),
            "reply too long": lambda e: e[4]["item"].update(text="x" * (rv.REPORT_MAX + 1)),
            "reply lone surrogate": lambda e: e[4]["item"].update(text="a\ud800"),
            "event after turn.completed": lambda e: e.append({"type": "item.started", "item": {"type": "x"}}),
            "usage missing": lambda e: e[5].pop("usage"),
            "usage not an object": lambda e: e[5].update(usage=3),
            "usage field missing": lambda e: e[5]["usage"].pop("output_tokens"),
            "usage negative": lambda e: e[5]["usage"].update(output_tokens=-1),
            "usage bool": lambda e: e[5]["usage"].update(output_tokens=True),
            "usage float": lambda e: e[5]["usage"].update(output_tokens=1.5),
            "usage huge": lambda e: e[5]["usage"].update(output_tokens=10 ** 15),
            "no turn.completed": drop(5),
            "no turn.started": drop(1),
            "no thread.started": drop(0),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.broken(mutate)

    def test_no_final_reply(self):
        e = self.broken(lambda evs: [x for x in evs if not (x["type"] == "item.completed"
                                                             and x["item"]["type"] == C.message_item_type)])
        self.assertIn("最後一則回覆", str(e))

    def test_reasons_never_echo_input(self):
        secret = "SECRET/TOKEN-1234"
        for mutate in (lambda e: e[0].update(thread_id=secret), lambda e: e.insert(2, {"type": secret}),
                       lambda e: e[4]["item"].update(text=secret * 100000)):
            with self.subTest():
                self.assertNotIn(secret, str(self.broken(mutate).reasons))


class ReportTests(unittest.TestCase):
    def test_every_rule(self):
        good = rf.report()
        cases = {
            "commit differs": good.replace(rf.COMMIT, "b" * 40),
            "commit twice": good + f"REVIEWED_COMMIT: {rf.COMMIT}\nVERDICT: PASS\n",
            "commit missing": good.replace(f"REVIEWED_COMMIT: {rf.COMMIT}\n", ""),
            "commit has trailing text": good.replace(f"REVIEWED_COMMIT: {rf.COMMIT}", f"REVIEWED_COMMIT: {rf.COMMIT} x"),
            "commit has CR": good.replace(f"REVIEWED_COMMIT: {rf.COMMIT}", f"REVIEWED_COMMIT: {rf.COMMIT}\r"),
            "ancestor missing": good.replace("BASE_IS_ANCESTOR: yes\n", ""),
            "ancestor maybe": good.replace("BASE_IS_ANCESTOR: yes", "BASE_IS_ANCESTOR: maybe"),
            "ancestor Yes": good.replace("BASE_IS_ANCESTOR: yes", "BASE_IS_ANCESTOR: Yes"),
            "ancestor twice": good.replace("No defects", "BASE_IS_ANCESTOR: yes\nNo defects"),
            "verdict missing": good.replace("VERDICT: PASS\n", ""),
            "verdict unknown": good.replace("VERDICT: PASS", "VERDICT: MAYBE"),
            "verdict lower": good.replace("VERDICT: PASS", "VERDICT: pass"),
            "verdict twice": good + "VERDICT: PASS\n",
            "verdict not last": good + "Thanks.\n",
            "verdict with text": good.replace("VERDICT: PASS", "VERDICT: PASS (really)"),
            "empty": "",
            "too long": good + "x" * (rv.REPORT_MAX + 1),
            "lone surrogate": good + "\ud800",
            "not a string": None,
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertTrue(rv.check_report(text, rf.COMMIT).problems, name)

    def test_the_verdicts_and_the_ancestor_line(self):
        for verdict in rv.VERDICTS:
            rep = rv.check_report(rf.report(verdict=verdict), rf.COMMIT)
            self.assertEqual((rep.verdict, rep.problems), (verdict, []))
        rep = rv.check_report(rf.report(ancestor="no"), rf.COMMIT)
        self.assertEqual((rep.base_is_ancestor, rep.problems), (False, []))      # the caller makes this invalid
        rep = rv.check_report(rf.report() + "\n\n", rf.COMMIT)
        self.assertEqual(rep.problems, [])                                       # blank lines after are fine


class RolloutTests(unittest.TestCase):
    def reasons(self, mutate, **over):
        evs, recs, text = rf.valid_run()
        changed = mutate(recs)
        recs = changed if isinstance(changed, list) else recs
        return run_rollout(recs, **over).reasons

    def find(self, recs, typ, sub=None):
        return [r for r in recs if r["type"] == typ and (sub is None or r["payload"].get("type") == sub)]

    def test_every_rule(self):
        f = self.find

        def set_(typ, key, value, sub=None, nested=None):
            def m(recs):
                p = f(recs, typ, sub)[0]["payload"]
                (p if nested is None else p[nested])[key] = value
            return m

        def del_(typ, key, sub=None, nested=None):
            def m(recs):
                p = f(recs, typ, sub)[0]["payload"]
                (p if nested is None else p[nested]).pop(key)
            return m

        def renumber(recs):
            for n, r in enumerate(recs):
                r["ordinal"] = n
        cases = {
            "ordinal skips": lambda r: r[3].update(ordinal=9),
            "ordinal starts at 1": lambda r: [x.update(ordinal=x["ordinal"] + 1) for x in r],
            "ordinal a string": lambda r: r[3].update(ordinal="3"),
            "ordinal bool": lambda r: r[0].update(ordinal=False),
            "first is not session_meta": lambda r: (r.insert(0, r.pop(1)), renumber(r)),
            "session_meta twice": lambda r: (r.insert(1, json.loads(json.dumps(r[0]))), renumber(r)),
            "thread id differs": set_("session_meta", "id", "other-thread-0001"),
            "scratch differs": set_("session_meta", "cwd", "/private/tmp/sr-zzzzzzzz"),
            "cli version differs": set_("session_meta", "cli_version", "0.159.0"),
            "originator": set_("session_meta", "originator", "codex_cli"),
            "source": set_("session_meta", "source", "cli"),
            "provider": set_("session_meta", "model_provider", "other"),
            "provider missing": del_("session_meta", "model_provider"),
            "unknown record kind": lambda r: (r.insert(5, {"ordinal": 5, "type": "mystery", "payload": {}}), renumber(r)),
            "unknown event_msg": lambda r: (r.insert(5, {"ordinal": 5, "type": "event_msg", "payload": {"type": "x"}}),
                                            renumber(r)),
            "unknown response_item": lambda r: (r.insert(5, {"ordinal": 5, "type": "response_item",
                                                             "payload": {"type": "mcp_call"}}), renumber(r)),
            "event_msg without a type": lambda r: (r.insert(5, {"ordinal": 5, "type": "event_msg", "payload": {}}),
                                                   renumber(r)),
            "payload not an object": lambda r: r[3].update(payload=[]),
            "no type": lambda r: r[3].pop("type"),
            "tool not allowed": set_("response_item", "name", "mcp__x__y", sub="custom_tool_call"),
            "tool name missing": del_("response_item", "name", sub="custom_tool_call"),
            "tool name not a string": set_("response_item", "name", ["exec"], sub="custom_tool_call"),
            "model differs": set_("turn_context", "model", "gpt-6.1-sol"),
            "model not listed": lambda r: ([x["payload"].update(model="gpt-other") for x in r if x["type"] == "turn_context"]),
            "sandbox type": set_("turn_context", "type", "danger-full-access", nested="sandbox_policy"),
            "sandbox network on": set_("turn_context", "network_access", True, nested="sandbox_policy"),
            "sandbox network missing": del_("turn_context", "network_access", nested="sandbox_policy"),
            "slash tmp writable": set_("turn_context", "exclude_slash_tmp", False, nested="sandbox_policy"),
            "tmpdir writable": set_("turn_context", "exclude_tmpdir_env_var", False, nested="sandbox_policy"),
            "extra writable roots": set_("turn_context", "writable_roots", ["/Users"], nested="sandbox_policy"),
            "sandbox missing": del_("turn_context", "sandbox_policy"),
            "permission network": set_("turn_context", "network", "enabled", nested="permission_profile"),
            "permission network missing": del_("turn_context", "network", nested="permission_profile"),
            "permission profile missing": del_("turn_context", "permission_profile"),
            "approval": set_("turn_context", "approval_policy", "on-request"),
            "turn cwd": set_("turn_context", "cwd", "/Users/x"),
            "turn id differs": set_("turn_context", "turn_id", "turn-0002"),
            "second turn_context bad": lambda r: (r.insert(4, {"ordinal": 4, "type": "turn_context", "payload": {
                **json.loads(json.dumps(r[3]["payload"])), "approval_policy": "always"}}), renumber(r)),
            "no turn_context": lambda r: (r.pop(3), renumber(r)),
            "no world_state": lambda r: (r.pop(1), renumber(r)),
            "world_state after turn_context": lambda r: (r.insert(3, r.pop(1)), renumber(r)),
            "apps on": set_("world_state", "apps_instructions", True),
            "apps missing": del_("world_state", "apps_instructions"),
            "plugins on": set_("world_state", "plugins_instructions", True),
            "host skills": set_("world_state", "host_skills", ["x"]),
            "host skills missing": del_("world_state", "host_skills"),
            "multi agent missing": del_("world_state", "multi_agent_mode"),
            "multi agent on": set_("world_state", "multi_agent_mode", "enabled"),
            "second world_state bad": lambda r: (r.insert(2, {"ordinal": 2, "type": "world_state", "payload": {
                **json.loads(json.dumps(r[1]["payload"])), "multi_agent_mode": "enabled"}}), renumber(r)),
            "task_started twice": lambda r: (r.insert(3, json.loads(json.dumps(r[2]))), renumber(r)),
            "no task_started": lambda r: (r.pop(2), renumber(r)),
            "task_started turn id": set_("event_msg", "turn_id", "turn-0002", sub="task_started"),
            "task_started time": set_("event_msg", "started_at", -1, sub="task_started"),
            "task_started time bool": set_("event_msg", "started_at", True, sub="task_started"),
            "no task_complete": lambda r: r.pop(),
            "task_complete twice": lambda r: (r.append(json.loads(json.dumps(r[-1]))), renumber(r)),
            "task_complete not last": lambda r: (r.append({"ordinal": len(r), "type": "response_item",
                                                           "payload": {"type": "reasoning"}})),
            "task_complete turn id": set_("event_msg", "turn_id", "turn-0002", sub="task_complete"),
            "completed before started": set_("event_msg", "completed_at", 5, sub="task_complete"),
            "completed missing": del_("event_msg", "completed_at", sub="task_complete"),
            "last message differs": set_("event_msg", "last_agent_message", "something else", sub="task_complete"),
            "last message null": set_("event_msg", "last_agent_message", None, sub="task_complete"),
            "no token records": lambda r: ([r.remove(x) for x in list(r) if x["type"] == "token_usage_record"],
                                           renumber(r)),
            "one token record missing (chain)": lambda r: (r.remove([x for x in r if x["type"] == "token_usage_record"][0]),
                                                           renumber(r)),
            "token record turn id": set_("token_usage_record", "turn_id", "turn-0002"),
            "usage input zero": lambda r: ([x["payload"]["usage"].update(input_tokens=0) for x in r
                                            if x["type"] == "token_usage_record"][:1]),
            "usage total zero": lambda r: ([x["payload"]["usage"].update(total_tokens=0) for x in r
                                            if x["type"] == "token_usage_record"][:1]),
            "cached above input": lambda r: ([x["payload"]["usage"].update(cached_input_tokens=10 ** 6) for x in r
                                              if x["type"] == "token_usage_record"][:1]),
            "turn total off by one": lambda r: ([x["payload"]["turn_token_usage"].update(
                output_tokens=x["payload"]["turn_token_usage"]["output_tokens"] + 1) for x in r
                if x["type"] == "token_usage_record"][:1]),
            "thread total off by one": lambda r: ([x["payload"]["thread_token_usage"].update(
                total_tokens=x["payload"]["thread_token_usage"]["total_tokens"] + 1) for x in r
                if x["type"] == "token_usage_record"][-1:]),
            "usage field missing": lambda r: ([x["payload"]["usage"].pop("cache_write_input_tokens") for x in r
                                               if x["type"] == "token_usage_record"][:1]),
            "usage field bool": lambda r: ([x["payload"]["usage"].update(output_tokens=True) for x in r
                                            if x["type"] == "token_usage_record"][:1]),
            "usage not an object": set_("token_usage_record", "usage", 5),
            "usage huge": lambda r: ([x["payload"]["usage"].update(output_tokens=10 ** 15) for x in r
                                      if x["type"] == "token_usage_record"][:1]),
            "last usage differs from the events": lambda r: ([x["payload"]["turn_token_usage"].update(
                reasoning_output_tokens=x["payload"]["turn_token_usage"]["reasoning_output_tokens"] + 1) for x in r
                if x["type"] == "token_usage_record"][-1:]),
            "nothing from the model": lambda r: ([r.remove(x) for x in list(r) if x["type"] == "response_item"
                                                  and x["payload"].get("type") in ("reasoning", "custom_tool_call")
                                                  or x["type"] == "response_item"
                                                  and x["payload"].get("role") == "assistant"], renumber(r)),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertTrue(self.reasons(mutate), name)

    def test_the_safety_rules_fail_for_their_own_reason(self):
        # Each of these must be caught by the rule that exists for it, not by
        # accident of another.
        def one(mutate, expect):
            _, recs, _ = rf.valid_run()
            mutate(recs)
            reasons = " | ".join(run_rollout(recs).reasons)
            self.assertIn(expect, reasons)
        tc = lambda r: [x for x in r if x["type"] == "turn_context"][0]["payload"]
        ws = lambda r: [x for x in r if x["type"] == "world_state"][0]["payload"]
        tok = lambda r: [x for x in r if x["type"] == "token_usage_record"]
        one(lambda r: tc(r)["sandbox_policy"].update(network_access=True), "sandbox_policy")
        one(lambda r: tc(r)["permission_profile"].update(network="enabled"), "permission_profile.network")
        one(lambda r: ws(r).pop("multi_agent_mode"), "multi_agent_mode")
        one(lambda r: ws(r).update(apps_instructions=True), "apps")
        one(lambda r: tc(r).update(approval_policy="on-request"), "approval_policy")
        one(lambda r: tc(r).update(cwd="/Users/someone"), "turn_context.cwd")
        one(lambda r: [x for x in r if x["payload"].get("type") == "custom_tool_call"][0]["payload"].update(name="browser"),
            "允許清單")
        one(lambda r: tok(r)[0]["payload"]["turn_token_usage"].update(output_tokens=1), "累計鏈")
        one(lambda r: tok(r)[-1]["payload"]["turn_token_usage"].update(reasoning_output_tokens=999999)
            or tok(r)[-1]["payload"]["thread_token_usage"].update(reasoning_output_tokens=999999), "累計鏈")
        def without_usage(r):
            keep = [x for x in r if x["type"] != "token_usage_record"]
            for n, x in enumerate(keep):
                x["ordinal"] = n
            r[:] = keep
        one(without_usage, "token_usage_record")
        one(lambda r: [x for x in r if x["payload"].get("type") == "task_complete"][0]["payload"].update(
            last_agent_message="different"), "last_agent_message")
        one(lambda r: r[0]["payload"].update(model_provider="other"), "model_provider")
        # and the events' own usage against the rollout's last record
        evs, recs, text = rf.valid_run()
        usage = dict(evs[-1]["usage"], output_tokens=evs[-1]["usage"]["output_tokens"] + 1)
        self.assertIn("turn.completed.usage", " | ".join(run_rollout(recs, events_usage=usage).reasons))

    def test_file_level_rules(self):
        _, recs, _ = rf.valid_run()
        raw = rf.lines(recs)
        cases = {
            "no final newline": raw[:-1],
            "empty": b"",
            "a line that is not json": raw + b"{not json\n",
            "a blank line": raw + b"\n",
            "a line that is not an object": raw + b"[1]\n",
            "duplicate key": raw.replace(b'"ordinal": 0,', b'"ordinal": 0, "ordinal": 0,', 1),
            "NaN": raw.replace(b'"started_at": 1791467000', b'"started_at": NaN', 1),
            "a line over the limit": raw + b'{"a":"' + b"x" * (4 << 20) + b'"}\n',
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self.assertTrue(run_rollout(None, raw=data).reasons, name)

    def test_values_are_never_echoed_and_surrogates_are_reasons(self):
        secret = "SECRET-CWD-7788"
        _, recs, _ = rf.valid_run()
        recs[0]["payload"]["cwd"] = "/Users/" + secret
        recs[3]["payload"]["model"] = secret
        self.assertNotIn(secret, " ".join(run_rollout(recs).reasons))
        _, recs, _ = rf.valid_run()
        raw = rf.lines(recs).replace(b'"model_provider": "openai"', b'"model_provider": "\\ud800"', 1)
        self.assertTrue(run_rollout(None, raw=raw).reasons)                  # a reason, no exception
        recs[0]["payload"]["id"] = "x\ud800"
        self.assertTrue(run_rollout(recs).reasons)

    def test_many_problems_are_capped(self):
        _, recs, _ = rf.valid_run(responses=30)
        for r in recs:
            r["ordinal"] = 7
        out = run_rollout(recs)
        self.assertLessEqual(len(out.reasons), rv.MAX_REASONS)


class LocateAndCopyTests(unittest.TestCase):
    def setUp(self):
        import datetime
        import shutil
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp(prefix="vbrr-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "codex-home"
        self.home.mkdir(mode=0o700)
        self.day1 = datetime.datetime(2026, 10, 8, 23, 59)
        self.day2 = datetime.datetime(2026, 10, 9, 0, 3)
        self.name = f"rollout-2026-10-08T23-59-00-{rf.THREAD}.jsonl"

    def put(self, when, name=None, data=b"x\n"):
        d = self.home / "sessions" / when.strftime("%Y") / when.strftime("%m") / when.strftime("%d")
        d.mkdir(parents=True, exist_ok=True)
        (d / (name or self.name)).write_bytes(data)
        return d / (name or self.name)

    def open_(self, dates=None):
        return rv.open_rollout(self.home, C, rf.THREAD, dates or [self.day1, self.day2])

    def test_exactly_one_file_in_the_review_days(self):
        self.put(self.day1)
        fd, st, rel = self.open_()
        import os
        os.close(fd)
        self.assertEqual(rel, f"sessions/2026/10/08/{self.name}")

    def test_none_or_more_than_one_or_the_wrong_one(self):
        for label, setup in (("none", lambda: None),
                             ("two", lambda: (self.put(self.day1), self.put(self.day2, self.name))),
                             ("another thread", lambda: self.put(self.day1, "rollout-2026-10-08T23-59-00-other-thread-1.jsonl")),
                             ("thread id only inside the name",
                              lambda: self.put(self.day1, f"rollout-{rf.THREAD}-x.jsonl")),
                             ("not a rollout name", lambda: self.put(self.day1, f"{rf.THREAD}.jsonl")),
                             ("another day", lambda: self.put(self.day1.replace(day=1)))):
            with self.subTest(case=label):
                import shutil
                shutil.rmtree(self.home / "sessions", ignore_errors=True)
                setup()
                with self.assertRaises(rv.ReviewInvalid):
                    self.open_()
        with self.assertRaises(rv.ReviewInvalid):
            rv.open_rollout(self.home, C, "bad id", [self.day1])

    def test_nothing_is_followed_through_a_symlink_and_only_a_plain_file_counts(self):
        import os
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        real = elsewhere / self.name
        real.write_bytes(b"x\n")
        d = self.home / "sessions" / "2026" / "10" / "08"
        d.mkdir(parents=True)
        (d / self.name).symlink_to(real)                          # the file itself
        with self.assertRaises(rv.ReviewInvalid):
            self.open_()
        (d / self.name).unlink()
        import shutil
        shutil.rmtree(self.home / "sessions")
        (self.home / "sessions").mkdir()
        (self.home / "sessions" / "2026").symlink_to(elsewhere)    # a directory on the way
        with self.assertRaises(rv.ReviewInvalid):
            self.open_()
        (self.home / "sessions" / "2026").unlink()
        d.mkdir(parents=True)
        os.mkfifo(d / self.name)                                  # not a regular file
        with self.assertRaises(rv.ReviewInvalid):
            self.open_()

    def test_a_codex_home_that_cannot_be_opened_or_listed(self):
        from unittest import mock
        self.put(self.day1)
        with self.assertRaises(rv.ReviewInvalid):
            rv.open_rollout(self.tmp / "missing", C, rf.THREAD, [self.day1])
        with mock.patch.object(rv.os, "listdir", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(rv.ReviewInvalid):
                self.open_()

    def test_a_file_over_the_limit_is_refused(self):
        from unittest import mock
        self.put(self.day1, data=b"x" * 100)
        with mock.patch.object(rv, "ROLLOUT_MAX", 50), self.assertRaises(rv.ReviewInvalid):
            self.open_()

    def copy_setup(self, data=b"line\n"):
        import hashlib
        import os
        path = self.put(self.day1, data=data)
        out = self.tmp / "record"
        out.mkdir(mode=0o700)
        fd, st, _ = self.open_()
        dfd = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        self.addCleanup(os.close, dfd)
        return path, out, fd, st, dfd, hashlib.sha256(data).hexdigest()

    def test_the_copy_is_exact_exclusive_and_leaves_the_source(self):
        path, out, fd, st, dfd, sha = self.copy_setup(b"a\nb\n")
        info = rv.copy_rollout(fd, dfd, "rollout.jsonl", expect_sha256=sha, src_before=st)
        self.assertEqual((info["sha256"], info["size"], info["source_inode"]), (sha, 4, st.st_ino))
        self.assertEqual((out / "rollout.jsonl").read_bytes(), b"a\nb\n")
        self.assertEqual(oct((out / "rollout.jsonl").stat().st_mode & 0o777), "0o600")
        self.assertTrue(path.exists())                            # never deleted
        with self.assertRaises(FileExistsError):                  # exclusive
            rv.copy_rollout(fd, dfd, "rollout.jsonl", expect_sha256=sha, src_before=st)
        self.assertEqual((out / "rollout.jsonl").read_bytes(), b"a\nb\n")

    def test_a_source_that_changed_or_a_hash_that_differs_leaves_no_copy(self):
        path, out, fd, st, dfd, sha = self.copy_setup(b"a\nb\n")
        with self.assertRaises(rv.ReviewInvalid):
            rv.copy_rollout(fd, dfd, "x.jsonl", expect_sha256="0" * 64, src_before=st)     # not what was validated
        with open(path, "ab") as f:
            f.write(b"c\n")                                       # grown after validation
        with self.assertRaises(rv.ReviewInvalid):
            rv.copy_rollout(fd, dfd, "y.jsonl", expect_sha256=sha, src_before=st)
        self.assertEqual(list(out.iterdir()), [])

    def test_a_failing_write_or_sync_leaves_no_copy(self):
        from unittest import mock
        path, out, fd, st, dfd, sha = self.copy_setup(b"a\nb\n")
        for patch in (mock.patch.object(rv.os, "write", side_effect=OSError(28, "No space left on device")),
                      mock.patch.object(rv.os, "fsync", side_effect=OSError(5, "Input/output error")),
                      mock.patch.object(rv.os, "write", return_value=0)):
            with self.subTest(patch=str(patch)[:40]), patch, self.assertRaises(OSError):
                rv.copy_rollout(fd, dfd, "z.jsonl", expect_sha256=sha, src_before=st)
            self.assertEqual(list(out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
