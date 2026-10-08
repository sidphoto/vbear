"""Flows board (stage 1): storage, derivation, family rule, commit binding,
API and malformed input. No model calls; repositories are fake .git dirs."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from vbear import flows, tasks
from vbear.jsonstore import StoreError

C1, C2, C3 = "a" * 40, "b" * 40, "c" * 64
NAN, INF = float("nan"), float("inf")


def fake_repo(root: Path, commit: str) -> Path:
    (root / ".git" / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "refs" / "heads" / "main").write_text(commit + "\n")
    return root


def roles(workdir=None, executor_family="anthropic", reviewer_families=("openai",)):
    ex = {"name": "執行者", "family": executor_family}
    if workdir:
        ex["workdir"] = str(workdir)
    return {"planner": {"name": "規劃者", "family": "anthropic"}, "executor": ex,
            "reviewers": [{"name": f"審查{i}", "family": f} for i, f in enumerate(reviewer_families)]}


class FlowCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "st"
        self.home.mkdir()
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.repo = fake_repo(self.root / "repo", C1)

    def task(self, title="任務"):
        return tasks.save_task(None, {"title": title})["id"]

    def flow(self, **kw):
        return flows.create_flow({"task_id": self.task(), "roles": roles(**kw)},
                                 lambda t: tasks.get_task(t) is not None)["id"]

    def add(self, fid, kind, **fields):
        return flows.append_event(fid, {"kind": kind, **fields})

    def derive(self, fid):
        return flows.derive(flows.get_flow(fid), flows.head_reader)


class StorageTests(FlowCase):
    def test_file_is_private_and_round_trips(self):
        fid = self.flow(workdir=self.repo)
        path = self.home / "flows.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(flows.get_flow(fid)["roles"]["executor"]["workdir"], str(self.repo))

    def corrupt_and_expect_block(self, content):
        self.flow()
        (self.home / "flows.json").write_text(content)
        with self.assertRaises(StoreError):
            flows.list_flows()
        self.assertTrue((self.home / "flows.json.corrupted").exists())
        with self.assertRaises(StoreError):     # blocked until a person clears the marker
            flows.list_flows()
        with self.assertRaises(StoreError):
            self.flow()
        self.assertTrue(list(self.home.glob("flows.json.corrupt-*")))   # bad bytes kept aside

    def test_unparseable_file_blocks_reads_and_writes(self):
        self.corrupt_and_expect_block("{not json")

    def test_entry_this_module_never_writes_blocks(self):
        self.corrupt_and_expect_block(json.dumps({"flow-000000000000": {"id": "flow-000000000000"}}))

    def test_event_with_bad_time_or_order_blocks(self):
        fid = self.flow()
        self.add(fid, "note")
        self.add(fid, "note")
        data = json.loads((self.home / "flows.json").read_text())
        for first, second in ((NAN, None), ("1", None), (10 ** 400, None), (-5.0, None), (0, None),
                              (1e12, None), (2e9, 1e9), (None, None), (True, None)):
            with self.subTest(first=type(first).__name__, second=second):
                broken = json.loads(json.dumps(data))
                broken[fid]["events"][0]["at"] = first
                if second is not None:
                    broken[fid]["events"][1]["at"] = second
                self.assertIsNotNone(flows._entry_problem(fid, broken[fid]))

    def test_symlink_or_hard_link_is_refused(self):
        self.flow()
        real = self.home / "flows.json"
        other = self.root / "elsewhere.json"
        os.link(real, other)
        with self.assertRaises(StoreError):
            flows.list_flows()

    def test_concurrent_writers_lose_nothing(self):
        fid = self.flow()
        errors = []

        def write(n):
            try:
                for _ in range(n):
                    self.add(fid, "note", note="x")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
        threads = [threading.Thread(target=write, args=(10,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        events = flows.get_flow(fid)["events"]
        self.assertEqual([e["seq"] for e in events], list(range(1, 41)))


class DerivationTests(FlowCase):
    def test_phases_follow_the_events(self):
        fid = self.flow(workdir=self.repo)
        expect = []
        self.assertEqual(self.derive(fid)["phase"]["key"], "planning")
        for kind, fields, phase in (
                ("plan_submitted", {}, "awaiting_approval"),
                ("plan_approved", {}, "implementing"),
                ("executor_report", {"commit": C1}, "in_review"),
                ("review_result", {"reviewer": 0, "verdict": "NEEDS_WORK", "commit": C1}, "needs_fix"),
                ("executor_report", {"commit": C1}, "in_review"),
                ("review_result", {"reviewer": 0, "verdict": "PASS", "commit": C1}, "awaiting_merge"),
                ("merge_done", {}, "awaiting_push"),
                ("push_done", {}, "done")):
            self.add(fid, kind, **fields)
            d = self.derive(fid)
            expect.append(d["phase"]["key"])
            self.assertEqual(d["phase"]["key"], phase, kind)
        d = self.derive(fid)
        self.assertEqual(len(d["rounds"]), 2)
        self.assertEqual(d["warnings"], [])

    def test_attention_is_only_for_the_users_gates(self):
        fid = self.flow(workdir=self.repo)
        self.assertFalse(self.derive(fid)["attention"])
        self.add(fid, "plan_submitted")
        self.assertTrue(self.derive(fid)["attention"])
        self.add(fid, "plan_approved")
        self.assertFalse(self.derive(fid)["attention"])

    def test_same_or_unknown_family_review_never_passes(self):
        for ex, rv in (("anthropic", "anthropic"), ("anthropic", "unknown"), ("anthropic", "other"),
                       ("unknown", "openai"), ("other", "openai")):
            with self.subTest(executor=ex, reviewer=rv):
                fid = self.flow(workdir=self.repo, executor_family=ex, reviewer_families=(rv,))
                self.add(fid, "executor_report", commit=C1)
                self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
                d = self.derive(fid)
                self.assertEqual(d["phase"]["key"], "in_review")
                self.assertFalse(d["rounds"][0]["reviews"][0]["counts_as_pass"])
                self.assertTrue(d["rounds"][0]["reviews"][0]["why"])

    def test_roles_changed_later_do_not_turn_an_old_review_into_a_pass(self):
        fid = self.flow(workdir=self.repo, reviewer_families=("anthropic",))
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        flows.set_roles(fid, {"roles": roles(workdir=self.repo, reviewer_families=("openai",))})
        d = self.derive(fid)
        self.assertNotEqual(d["phase"]["key"], "awaiting_merge")
        self.assertEqual(flows.get_flow(fid)["events"][-1]["kind"], "roles_changed")

    def test_a_pass_goes_stale_when_head_moves(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.assertEqual(self.derive(fid)["binding"]["state"], "current")
        fake_repo(self.repo, C2)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["binding"]["state"]), ("review_stale", "stale"))
        self.assertIn("已過期", d["phase"]["reason"])

    def test_a_pass_without_a_readable_head_is_unverified(self):
        fid = self.flow()                                       # no workdir
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.assertEqual(self.derive(fid)["phase"]["key"], "review_unverified")
        fid2 = self.flow(workdir=self.root)                     # not a repository
        self.add(fid2, "executor_report", commit=C1)
        self.add(fid2, "review_result", reviewer=0, verdict="PASS", commit=C1)
        d = self.derive(fid2)
        self.assertEqual(d["phase"]["key"], "review_unverified")
        self.assertTrue(d["attention"])

    def test_a_review_of_an_older_commit_is_not_this_rounds_result(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C2)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C2)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "in_review")
        self.assertEqual(len(d["stray_reviews"]), 1)

    def passed_merged_pushed(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.add(fid, "merge_done")
        self.add(fid, "push_done")
        self.assertEqual(self.derive(fid)["phase"]["key"], "done")
        return fid

    def test_a_late_pass_of_the_merged_commit_does_not_reopen_the_flow(self):
        # Codex S1 #3: report, PASS, merge, push, then another PASS of the same commit.
        fid = self.passed_merged_pushed()
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "done")
        late = d["rounds"][-1]["reviews"][-1]
        self.assertFalse(late["counts_as_pass"])
        self.assertIn("合併後", late["why"])
        self.assertEqual(d["warnings"], [])

    def test_a_late_pass_between_merge_and_push_does_not_go_back_to_awaiting_merge(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.add(fid, "merge_done")
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        self.assertEqual(self.derive(fid)["phase"]["key"], "awaiting_push")

    def test_a_late_objection_keeps_the_phase_and_is_flagged(self):
        fid = self.passed_merged_pushed()
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "done")
        self.assertEqual(len(d["warnings"]), 1)
        self.assertIn("NEEDS_WORK", d["warnings"][0])

    def test_reporting_the_merged_commit_again_does_not_open_a_round(self):
        fid = self.passed_merged_pushed()
        self.add(fid, "executor_report", commit=C1)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], len(d["rounds"])), ("done", 1))
        self.assertEqual(len(d["warnings"]), 1)

    def test_a_new_commit_after_push_opens_a_new_round(self):
        fid = self.passed_merged_pushed()
        fake_repo(self.repo, C2)
        self.add(fid, "executor_report", commit=C2)
        d = self.derive(fid)
        self.assertEqual((d["phase"]["key"], d["phase"]["round"]), ("in_review", 2))
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C2)
        self.assertEqual(self.derive(fid)["phase"]["key"], "awaiting_merge")

    def test_re_reporting_the_same_commit_before_merge_still_opens_a_round(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="NEEDS_WORK", commit=C1)
        self.add(fid, "executor_report", commit=C1)
        self.assertEqual(self.derive(fid)["phase"]["round"], 2)

    def test_merge_without_a_valid_pass_is_flagged(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "merge_done")
        self.add(fid, "push_done")
        d = self.derive(fid)
        self.assertEqual(d["phase"]["key"], "done")
        self.assertEqual(len(d["warnings"]), 1)


class InputTests(FlowCase):
    def test_one_flow_per_task_and_task_must_exist(self):
        tid = self.task()
        ok = lambda t: tasks.get_task(t) is not None  # noqa: E731
        flows.create_flow({"task_id": tid, "roles": roles()}, ok)
        with self.assertRaises(ValueError):
            flows.create_flow({"task_id": tid, "roles": roles()}, ok)
        with self.assertRaises(ValueError):
            flows.create_flow({"task_id": "no-such-task", "roles": roles()}, ok)

    def test_strict_fields_per_kind(self):
        fid = self.flow()
        bad = [
            {"kind": "launch_agent"},                                       # not a kind
            {"kind": "roles_changed", "roles": roles()},                    # server-only kind
            {"kind": "note", "commit": C1},                                 # field not for this kind
            {"kind": "note", "at": 1.0},                                    # time is the server's
            {"kind": "note", "source": "vbear"},                            # source is the server's
            {"kind": "executor_report", "commit": "abc1234"},               # short commit
            {"kind": "executor_report", "commit": C1.upper()},
            {"kind": "review_result", "reviewer": 0, "verdict": "LGTM", "commit": C1},
            {"kind": "review_result", "reviewer": 5, "verdict": "PASS", "commit": C1},
            {"kind": "review_result", "reviewer": True, "verdict": "PASS", "commit": C1},
            {"kind": "note", "note": "x" * 2001},
        ]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                with self.assertRaises(ValueError):
                    flows.append_event(fid, body)
        self.assertEqual(flows.get_flow(fid)["events"], [])
        with self.assertRaises(KeyError):
            flows.append_event("flow-ffffffffffff", {"kind": "note"})

    def test_role_validation(self):
        tid = self.task()
        ok = lambda t: True  # noqa: E731
        bad_roles = [
            {**roles(), "extra": {}},
            {**roles(), "reviewers": []},
            {**roles(), "reviewers": [{"name": "x", "family": "openai"}] * 5},
            {**roles(), "planner": {"name": "", "family": "anthropic"}},
            {**roles(), "planner": {"name": "p", "family": "gpt"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "session_id": "n-zz"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "workdir": "relative"}},
            {**roles(), "executor": {"name": "e", "family": "anthropic", "workdir": str(self.root / "missing")}},
            {**roles(), "planner": {"name": "p", "family": "anthropic", "workdir": "/tmp"}},   # only executor has one
        ]
        for r in bad_roles:
            with self.subTest(roles=str(r)[:70]):
                with self.assertRaises(ValueError):
                    flows.create_flow({"task_id": tid, "roles": r}, ok)


class MalformedInputTests(FlowCase):
    """Fixed review checks a-d for every entry: no exception, never a pass."""
    BAD = [None, True, False, "1", "", NAN, INF, -INF, 10 ** 10000, -1, [], {}, [1], {"a": 1}]

    def test_api_bodies(self):
        fid = self.flow()
        for v in self.BAD:
            for body in ({"kind": v}, {"kind": "note", "note": v}, {"kind": "executor_report", "commit": v},
                         {"kind": "review_result", "reviewer": v, "verdict": "PASS", "commit": C1},
                         {"kind": "review_result", "reviewer": 0, "verdict": v, "commit": C1}):
                if "note" in body and isinstance(v, str):
                    continue  # any string up to the limit is a valid note
                try:
                    flows.append_event(fid, body)
                except ValueError:
                    pass
                else:
                    self.fail(f"accepted {str(body)[:60]}")
            for entry in (lambda: flows.append_event(fid, v), lambda: flows.set_roles(fid, v),
                          lambda: flows.set_roles(fid, {"roles": v}),
                          lambda: flows.create_flow(v, lambda t: True),
                          lambda: flows.create_flow({"task_id": v, "roles": roles()}, lambda t: False)):
                with self.assertRaises((ValueError, KeyError)):
                    entry()
            with self.assertRaises(KeyError):
                flows.get_flow(v if isinstance(v, str) else "x")

    def test_stored_values(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        good = flows.get_flow(fid)
        self.assertIsNone(flows._entry_problem(fid, good))
        paths = [("created_at",), ("task_id",), ("roles",), ("events",), ("events", 0, "at"), ("events", 0, "seq"),
                 ("events", 0, "kind"), ("events", 0, "source"), ("events", 0, "note"), ("events", 0, "commit"),
                 ("roles", "executor", "family"), ("roles", "executor", "workdir"), ("roles", "reviewers"),
                 ("roles", "planner", "model"), ("roles", "executor", "session_id")]
        valid = {("events", 0, "note"): lambda v: isinstance(v, str),          # any string is a note
                 ("events",): lambda v: v == [],                                 # no events is valid
                 ("task_id",): lambda v: v == "1",                               # "1" is a valid task id
                 ("roles", "planner", "model"): lambda v: v == "1"}              # and a valid model name
        for path in paths:
            for v in self.BAD:
                if valid.get(path, lambda v: False)(v):
                    continue
                broken = json.loads(json.dumps(good))
                target = broken
                for k in path[:-1]:
                    target = target[k]
                target[path[-1]] = v if not (isinstance(v, int) and not isinstance(v, bool) and v > 10 ** 100) else 10 ** 400
                with self.subTest(path=path, v=type(v).__name__):
                    self.assertIsNotNone(flows._entry_problem(fid, broken))

    def test_derive_with_unreadable_or_odd_heads(self):
        fid = self.flow(workdir=self.repo)
        self.add(fid, "executor_report", commit=C1)
        self.add(fid, "review_result", reviewer=0, verdict="PASS", commit=C1)
        flow = flows.get_flow(fid)
        for head in ({}, {"commit": None, "error": "x"}, {"commit": 5}, {"commit": C1.upper()}, {"commit": "a" * 39},
                     None):
            with self.subTest(head=head):
                d = flows.derive(flow, lambda wd, h=head: h)
                self.assertNotEqual(d["phase"]["key"], "awaiting_merge")

    def test_events_time_never_goes_back_even_if_the_clock_does(self):
        fid = self.flow()
        self.add(fid, "note")
        first = flows.get_flow(fid)["events"][0]["at"]
        with mock.patch("vbear.flows.time.time", return_value=first - 1000):
            self.add(fid, "note")
        events = flows.get_flow(fid)["events"]
        self.assertGreaterEqual(events[1]["at"], events[0]["at"])
        with mock.patch("vbear.flows.time.time", return_value=NAN):
            with self.assertRaises(StoreError):
                self.add(fid, "note")


class LiveCachedTests(FlowCase):
    """Flows decorate themselves with live state from the cache only: a live
    build calls the runtime, which may start its daemon (Codex S1 #1)."""

    def test_never_builds_and_never_waits(self):
        from vbear.index import Store
        store = Store(runtime=mock.Mock())
        with mock.patch.object(store, "_build_live") as build:
            self.assertIsNone(store.live_cached())
            built = {"sessions": [], "panes": []}
            with store._live_cond:
                store._live, store._live_at = built, 0.0      # stale on purpose
            self.assertIs(store.live_cached(), built)
            build.assert_not_called()
        store.runtime.assert_not_called()
        self.assertEqual(store.runtime.method_calls, [])


class FlowApiTests(unittest.TestCase):
    """The HTTP surface: needs the access token, rejects bad input, adds no
    execution capability (only GET /api/flows[/id] and three POST routes)."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from vbear.server import Console, make_handler
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"VBEAR_HOME": cls.tmp.name, "VBEAR_RUNTIME_AUTOSTART": "0"})
        cls.env.start()
        # Like the other server tests: no scan sources, no usage scan, so the
        # live view built in the background stays small and never reads HOME.
        from vbear import config as cfg
        conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
        for src in conf["sources"]:
            src["enabled"] = False
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        cls.port = cls.httpd.server_address[1]
        cls.console = Console(cls.port)
        cls.token = cls.console.auth_token
        cls.httpd.RequestHandlerClass = make_handler(cls.console)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.env.stop()
        cls.tmp.cleanup()

    def call(self, path, method="GET", body=None, token=True):
        import urllib.error
        import urllib.request
        h = {"X-VBear": "1", "Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {self.token}"
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"null")
            e.close()
            return e.code, data

    def test_flow_routes_never_build_the_live_view(self):
        tid = tasks.save_task(None, {"title": "不觸發即時建置"})["id"]
        with mock.patch.object(self.console.store, "_build_live") as build, \
                mock.patch.object(self.console.store, "live", side_effect=AssertionError("live() called")):
            st, r = self.call("/api/flows", "POST", {"task_id": tid, "roles": roles()})
            self.assertEqual(st, 200, r)
            fid = r["flow"]["id"]
            self.assertEqual(self.call(f"/api/flows/{fid}/events", "POST", {"kind": "note"})[0], 200)
            self.assertEqual(self.call(f"/api/flows/{fid}/roles", "POST", {"roles": roles()})[0], 200)
            self.assertEqual(self.call(f"/api/flows/{fid}")[0], 200)
            self.assertEqual(self.call("/api/flows")[0], 200)
            build.assert_not_called()

    def test_token_required(self):
        self.assertEqual(self.call("/api/flows", token=False)[0], 401)
        self.assertEqual(self.call("/api/flows", "POST", {"task_id": "x", "roles": {}}, token=False)[0], 401)

    def test_create_record_and_read(self):
        tid = tasks.save_task(None, {"title": "API 任務"})["id"]   # the tasks API is not under test here
        st, r = self.call("/api/flows", "POST", {"task_id": tid, "roles": roles()})
        self.assertEqual(st, 200, r)
        fid = r["flow"]["id"]
        self.assertEqual(r["flow"]["phase"]["key"], "planning")
        st, r = self.call(f"/api/flows/{fid}/events", "POST", {"kind": "plan_submitted", "note": "請核准"})
        self.assertEqual((st, r["flow"]["phase"]["key"]), (200, "awaiting_approval"))
        self.assertEqual(r["flow"]["events"][0]["source_label"], flows.MANUAL_LABEL)
        st, r = self.call("/api/flows")
        self.assertEqual(st, 200)
        self.assertTrue(r["flows"][0]["attention"])
        self.assertEqual({f["key"] for f in r["families"]}, set(flows.FAMILIES))
        st, r = self.call(f"/api/flows/{fid}/events", "POST", {"kind": "run_tests"})
        self.assertEqual(st, 400)
        self.assertEqual(self.call(f"/api/flows/{fid}/launch", "POST", {})[0], 404)   # no such capability
        self.assertEqual(self.call("/api/flows/flow-ffffffffffff")[0], 404)
        self.assertEqual(self.call("/api/flows/../tasks")[0], 404)


if __name__ == "__main__":
    unittest.main()
