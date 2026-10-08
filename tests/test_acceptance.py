"""Risk acceptance records (vbear/acceptance.py, design 6 and 10; planner
decisions S2a-2 Q1/Q3/Q4). flows.json here is synthetic."""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import acceptance as acc
from vbear import flows, login_identity, tasks

NAN, INF = float("nan"), float("inf")


def record(key_id, **over):
    fields = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
              "executor_claude_version": "2.1.292", "executor_model": "claude-haiku-4-5-20251001",
              "executor_login_fingerprint": "a" * 64, "login_fingerprint": "b" * 64, "login_key_id": key_id,
              "limits": dict(acc.DEFAULT_LIMITS)}
    fields.update(over)
    return fields


class LimitsTests(unittest.TestCase):
    def test_defaults_and_caps(self):
        self.assertIsNone(acc.limits_problem(dict(acc.DEFAULT_LIMITS)))
        caps = {k: v[1] for k, v in acc.LIMITS.items()}
        self.assertIsNone(acc.limits_problem(caps))
        self.assertEqual(len(acc.LIMITS), 9)

    def test_bad_limits(self):
        base = dict(acc.DEFAULT_LIMITS)
        cases = [None, [], {}, {**base, "extra": 1}]
        cases += [{k: v for k, v in base.items() if k != "max_reviews"}]
        for name, (_, cap) in acc.LIMITS.items():
            for bad in (0, -1, cap + 1, True, False, None, "5", [], NAN, INF, 10 ** 400):
                if name == "executor_budget_usd" and bad == cap + 1:
                    bad = cap + 0.01
                cases.append({**base, name: bad})
        cases.append({**base, "max_reviews": 5.0})                 # a float is not an integer
        cases.append({**base, "executor_budget_usd": 1.005})       # three decimals
        for limits in cases:
            with self.subTest(limits=repr(limits)[-60:]):
                self.assertIsNotNone(acc.limits_problem(limits))
        self.assertIsNone(acc.limits_problem({**base, "executor_budget_usd": 0.01}))
        self.assertIsNone(acc.limits_problem({**base, "executor_budget_usd": 12}))


class RecordTests(unittest.TestCase):
    def test_well_formed(self):
        self.assertIsNone(acc.record_problem(record("0" * 16)))

    def test_malformed(self):
        good = record("0" * 16)
        cases = [{k: v for k, v in good.items() if k != "model"}, {**good, "extra": 1}]
        for name in acc.FIELDS - {"limits"}:
            for bad in (None, 1, True, "", " " + str(good[name]), str(good[name]) + "\n", "X" * 70):
                cases.append({**good, name: bad})
        cases.append({**good, "executor_model": "haiku"})                 # an alias, not a full id
        cases.append({**good, "executor_model": "Claude-haiku"})
        cases.append({**good, "limits": {**good["limits"], "max_dispatches": 41}})
        for fields in cases:
            with self.subTest(fields=repr(fields)[:80]):
                self.assertIsNotNone(acc.record_problem(fields))


class ValidityTests(unittest.TestCase):
    def event(self, key_id, **over):
        return {"seq": 1, "at": 1.0, "kind": "risk_acknowledged", "source": "console", "note": "",
                **record(key_id, **over)}

    def test_valid_only_for_the_current_key_and_text(self):
        e = self.event("1" * 16)
        self.assertTrue(acc.is_valid_now(e, "1" * 16))
        self.assertFalse(acc.is_valid_now(e, "2" * 16))
        self.assertFalse(acc.is_valid_now(e, None))
        self.assertFalse(acc.is_valid_now(self.event("1" * 16, text_version="2025-01-01.1"), "1" * 16))
        self.assertFalse(acc.is_valid_now({**e, "kind": "note"}, "1" * 16))

    def test_latest_valid_wins(self):
        old = self.event("1" * 16, limits={**acc.DEFAULT_LIMITS, "max_dispatches": 5})
        new = self.event("1" * 16, limits={**acc.DEFAULT_LIMITS, "max_dispatches": 7})
        broken = self.event("1" * 16, limits={**acc.DEFAULT_LIMITS, "max_dispatches": 99})
        flow = {"events": [old, new, broken, {"kind": "note"}]}
        self.assertEqual(acc.latest_valid(flow, "1" * 16)["limits"]["max_dispatches"], 7)
        self.assertIsNone(acc.latest_valid(flow, "2" * 16))
        self.assertIsNone(acc.latest_valid({"events": "x"}, "1" * 16))


class StoredTests(unittest.TestCase):
    """Through the real stores: flows.json with acceptance events, and the
    HMAC key. A lost or damaged key voids every earlier acceptance."""

    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbacc-")))
        self.addCleanup(shutil.rmtree, self.home, True)
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        tid = tasks.save_task(None, {"title": "t"})["id"]
        roles = {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": "anthropic"},
                 "reviewers": [{"name": "c", "family": "openai"}]}
        self.fid = flows.create_flow({"task_id": tid, "roles": roles}, lambda t: True)["id"]

    def add_acceptance(self, key_id, **over):
        with flows.store.locked():
            data = flows.store.load()
            events = data[self.fid]["events"]
            events.append({"seq": len(events) + 1, "at": time.time(), "kind": "risk_acknowledged",
                           "source": "console", "note": "", **record(key_id, **over)})
            flows.store.save(data)

    def test_store_accepts_well_formed_console_events_only(self):
        key = login_identity.create_login_key(self.home, valid_acceptances=0)
        self.add_acceptance(key.key_id)
        self.assertEqual(acc.count_valid(flows.store.load(), key.key_id), 1)
        data = flows.store.load()
        bad = dict(data[self.fid]["events"][-1])
        for change in ({"source": "manual"}, {"limits": {}}, {"login_key_id": "x"}):
            with self.subTest(change=change):
                self.assertIsNotNone(flows._entry_problem(self.fid, {**data[self.fid],
                                                                     "events": [{**bad, **change}]}))
        manual_note = {"seq": 1, "at": 1.0, "kind": "note", "source": "console", "note": ""}
        self.assertIsNotNone(flows._entry_problem(self.fid, {**data[self.fid], "events": [manual_note]}))
        with self.assertRaises(ValueError):                         # the API cannot write one
            flows.append_event(self.fid, {"kind": "risk_acknowledged"})

    def test_lost_or_damaged_key_voids_every_earlier_acceptance(self):
        state = self.home
        damages = {
            "missing": lambda p: p.unlink(),
            "damaged": lambda p: p.write_bytes(b"short"),
            "wrong mode": lambda p: p.chmod(0o644),
        }
        for name, damage in damages.items():
            with self.subTest(damage=name):
                path = state / login_identity.KEY_NAME
                if path.exists():
                    path.unlink()
                key = login_identity.create_login_key(state, valid_acceptances=0)
                self.add_acceptance(key.key_id)
                self.add_acceptance(key.key_id)
                flows_now = flows.store.load()
                self.assertEqual(acc.count_valid(flows_now, key.key_id), 2)
                # A working key is returned as it is, never replaced.
                same = login_identity.create_login_key(state, valid_acceptances=acc.count_valid(flows_now, key.key_id))
                self.assertEqual(same.key_id, key.key_id)
                damage(path)
                with self.assertRaises(login_identity.KeyUnavailable):
                    login_identity.load_login_key(state)
                # No usable key: nothing matches, so a new key may be made...
                self.assertEqual(acc.count_valid(flows.store.load(), None), 0)
                new = login_identity.create_login_key(state, valid_acceptances=0)
                self.assertNotEqual(new.key_id, key.key_id)
                # ...and every acceptance made with the old one stays void.
                self.assertEqual(acc.count_valid(flows.store.load(), new.key_id), 0)
                self.assertIsNone(acc.latest_valid(flows.get_flow(self.fid), new.key_id))


if __name__ == "__main__":
    unittest.main()
