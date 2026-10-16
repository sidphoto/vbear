"""Team slots (design card-play 3.5, P4): the digest that moved to agent_profiles, the role card fields
(profile_id, profile_snapshot) of a flow's roles, and the revision the profile API shows.

Run: python3 -m unittest tests.test_team_slots -v
"""

from __future__ import annotations

import ast
import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-team-slots-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_launch, agent_profiles, flows, server, tasks  # noqa: E402
from vbear import runtime as rt_mod  # noqa: E402
from vbear.config import state_dir  # noqa: E402
from vbear.index import Store  # noqa: E402
from vbear.jsonstore import StoreError  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REV1, REV2 = "1" * 64, "ab" * 32

# The digest of this profile, computed by agent_launch.profile_digest BEFORE it moved to agent_profiles.
# It is the value a launch preview and a team slot both record, so it must never change.
GOLDEN_PROFILE = {
    "id": "prof-a1", "name": "CEO 工匠", "profession_role_id": None,
    "model": {"tool": "claude", "model_id": "claude-x"}, "equipped_skill_ids": ["a", "b"],
    "permission_intents": {"read": "allow", "write": "deny", "test": "deny", "deploy": "deny"},
    "enabled": True, "created_at": 1.5, "updated_at": 2, "_unresolved": ["zzz"],
}
GOLDEN_DIGEST = "714d9e83be93f34a41d48ef87169f5159e7958d95e1e43f8450a36972dc78c77"


def snapshot(**over):
    snap = {"name": "CEO", "tool": "claude", "model_id": "", "revision": REV1}
    snap.update(over)
    return snap


def card(role, profile_id="prof-ceo", **over):
    return {**role, "profile_id": profile_id, "profile_snapshot": snapshot(**over)}


def roles(**cards):
    """A complete team; any of planner / executor / reviewer can be replaced with the role given."""
    base = {"planner": {"name": "CEO", "family": "anthropic"},
            "executor": {"name": "工匠", "family": "anthropic"},
            "reviewers": [{"name": "審查員", "family": "openai"}]}
    for key, value in cards.items():
        base[key] = value
    return base


class DigestMovedTests(unittest.TestCase):
    def test_digest_value_did_not_change_when_it_moved(self):
        self.assertEqual(agent_profiles.profile_digest(GOLDEN_PROFILE), GOLDEN_DIGEST)

    def test_agent_launch_uses_the_same_function(self):
        self.assertIs(agent_launch.profile_digest, agent_profiles.profile_digest)
        self.assertEqual(agent_launch.profile_digest(GOLDEN_PROFILE), GOLDEN_DIGEST)

    def test_transient_keys_do_not_count_and_real_ones_do(self):
        self.assertEqual(agent_profiles.profile_digest({**GOLDEN_PROFILE, "_unresolved": [], "_x": 1}), GOLDEN_DIGEST)
        self.assertNotEqual(agent_profiles.profile_digest({**GOLDEN_PROFILE, "name": "CEO 工匠 2"}), GOLDEN_DIGEST)
        changed = json.loads(json.dumps(GOLDEN_PROFILE))
        changed["permission_intents"]["write"] = "allow"
        self.assertNotEqual(agent_profiles.profile_digest(changed), GOLDEN_DIGEST)

    def test_flows_does_not_import_the_launch_or_profile_modules(self):
        tree = ast.parse((REPO / "vbear" / "flows.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        for name in ("agent_launch", "agent_profiles", "vbear.agent_launch", "vbear.agent_profiles"):
            self.assertNotIn(name, imported)
        source = (REPO / "vbear" / "flows.py").read_text(encoding="utf-8")
        self.assertNotIn("profile_digest(", source)
        self.assertNotIn("hashlib", source)


class MirroredRulesTests(unittest.TestCase):
    """flows.py repeats three rules of agent_profiles because it must not import it; these keep them equal."""

    def test_profile_id_rule_is_the_same(self):
        self.assertEqual(flows.PROFILE_ID_RE.pattern, agent_profiles.VALID_PROFILE_ID_RE.pattern)
        for ok in ("a", "prof-0123456789ab", "A_b-9", "x" * 64, "demo-ceo"):
            self.assertTrue(flows.PROFILE_ID_RE.match(ok) and agent_profiles.VALID_PROFILE_ID_RE.match(ok), ok)
        for bad in ("", "-a", "_a", "a b", "x" * 65, "a\n", "a/b", "中文", " a"):
            self.assertFalse(flows.PROFILE_ID_RE.match(bad) or agent_profiles.VALID_PROFILE_ID_RE.match(bad), repr(bad))

    def test_limits_and_tools_are_the_same(self):
        self.assertEqual(flows.MAX_SNAPSHOT_NAME, agent_profiles.MAX_TEXT_NAME)
        self.assertEqual(flows.MAX_SNAPSHOT_MODEL_ID, agent_profiles.MAX_MODEL_ID)
        self.assertEqual(set(flows.SNAPSHOT_TOOLS), set(agent_profiles.KNOWN_TOOLS))

    def test_revision_rule_is_a_sha256_hex_and_the_digest_fits_it(self):
        self.assertTrue(flows._SHA256_RE.match(GOLDEN_DIGEST))
        self.assertEqual(len(agent_profiles.profile_digest({"id": "x"})), 64)


class FlowCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "st"
        self.home.mkdir()
        p = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)

    def task(self, title="任務"):
        return tasks.save_task(None, {"title": title})["id"]

    def create(self, team):
        return flows.create_flow({"task_id": self.task(), "roles": team}, lambda t: tasks.get_task(t) is not None)


class RoleCardFieldsTests(FlowCase):
    def full_team(self):
        return roles(planner=card({"name": "CEO", "family": "anthropic"}, "prof-ceo", name="CEO"),
                     executor=card({"name": "工匠", "family": "anthropic"}, "prof-maker", name="工匠", revision=REV2),
                     reviewers=[card({"name": "審查員", "family": "openai"}, "prof-rev", name="審查員", tool="codex"),
                                {"name": "手填", "family": "google"}])

    def test_every_role_can_carry_the_card_and_it_round_trips(self):
        flow = self.create(self.full_team())
        stored = flows.get_flow(flow["id"])
        self.assertEqual(stored["roles"]["planner"]["profile_id"], "prof-ceo")
        self.assertEqual(stored["roles"]["executor"]["profile_snapshot"],
                         {"name": "工匠", "tool": "claude", "model_id": "", "revision": REV2})
        self.assertEqual(stored["roles"]["reviewers"][0]["profile_snapshot"]["tool"], "codex")
        self.assertNotIn("profile_id", stored["roles"]["reviewers"][1])     # the hand-written role has none
        self.assertEqual(json.loads((self.home / "flows.json").read_text())[flow["id"]]["roles"], stored["roles"])
        self.assertIsNone(flows._entry_problem(flow["id"], stored))

    def test_old_roles_without_the_fields_read_and_save_as_before(self):
        flow = self.create(roles())
        stored = flows.get_flow(flow["id"])
        for role in (stored["roles"]["planner"], stored["roles"]["executor"], *stored["roles"]["reviewers"]):
            self.assertFalse({"profile_id", "profile_snapshot"} & set(role))
        self.assertIsNone(flows._entry_problem(flow["id"], stored))
        flows.set_roles(flow["id"], {"roles": self.full_team()})
        self.assertIn("profile_id", flows.get_flow(flow["id"])["roles"]["planner"])

    def test_set_roles_keeps_the_card_in_the_roles_changed_event(self):
        flow = self.create(roles())
        flows.set_roles(flow["id"], {"roles": self.full_team()})
        event = flows.get_flow(flow["id"])["events"][-1]
        self.assertEqual(event["kind"], "roles_changed")
        self.assertEqual(event["roles"]["executor"]["profile_snapshot"]["revision"], REV2)
        self.assertIsNone(flows._event_problem(event, 0, None))

    def test_the_view_passes_the_card_through_and_changes_no_family(self):
        flow = self.create(self.full_team())
        view = flows.view(flows.get_flow(flow["id"]), heads=flows.head_reader, task_title=lambda _t: "t",
                          live=None, now=1.0)
        self.assertEqual(view["roles"]["executor"]["profile_id"], "prof-maker")
        self.assertEqual(view["roles"]["reviewers"][0]["profile_snapshot"]["name"], "審查員")
        self.assertEqual(view["roles"]["executor"]["family"], "anthropic")     # nothing is derived from the card

    def test_a_card_does_not_change_whether_a_review_counts(self):
        # claude snapshot on both sides but different families written by hand: the family fields decide
        team = roles(executor=card({"name": "工匠", "family": "openai"}, "prof-maker"),
                     reviewers=[card({"name": "審查員", "family": "openai"}, "prof-rev", tool="codex")])
        view = flows.view(self.create(team), heads=flows.head_reader, task_title=lambda _t: "t", live=None, now=1.0)
        self.assertFalse(view["roles"]["reviewers"][0]["independent_of_executor"]["counted"])

    def bad(self, team, *needle):
        with self.assertRaises(ValueError) as ctx:
            self.create(team)
        for part in needle:
            self.assertIn(part, str(ctx.exception))

    def role(self, **over):
        return {"name": "CEO", "family": "anthropic", "profile_id": "prof-ceo", "profile_snapshot": snapshot(), **over}

    def test_input_is_strict_about_the_snapshot(self):
        cases = {
            "extra key": snapshot(extra="x"),
            "missing name": {k: v for k, v in snapshot().items() if k != "name"},
            "missing revision": {k: v for k, v in snapshot().items() if k != "revision"},
            "empty": {},
            "not a dict": ["name"],
            "string": "CEO",
            "none": None,
            "blank name": snapshot(name="  "),
            "name not str": snapshot(name=5),
            "name too long": snapshot(name="x" * 201),
            "name nul": snapshot(name="a\x00b"),
            "model_id not str": snapshot(model_id=None),
            "model_id too long": snapshot(model_id="m" * 201),
            "model_id nul": snapshot(model_id="a\x00"),
            "tool unknown": snapshot(tool="agy"),
            "tool upper": snapshot(tool="Claude"),
            "tool not str": snapshot(tool=["claude"]),
            "revision short": snapshot(revision="a" * 63),
            "revision long": snapshot(revision="a" * 65),
            "revision upper": snapshot(revision="A" * 64),
            "revision newline": snapshot(revision="a" * 63 + "\n"),
            "revision non hex": snapshot(revision="g" * 64),
            "revision int": snapshot(revision=12),
        }
        for label, snap in cases.items():
            with self.subTest(label):
                self.bad(roles(planner=self.role(profile_snapshot=snap)), "profile_snapshot")

    def test_input_is_strict_about_the_profile_id(self):
        for label, pid in {"empty": "", "none": None, "int": 7, "bool": True, "list": ["a"], "space": "a b",
                           "leading dash": "-a", "too long": "x" * 65, "newline": "prof-a\n", "slash": "a/b",
                           "non ascii": "角色"}.items():
            with self.subTest(label):
                self.bad(roles(planner=self.role(profile_id=pid)), "profile_id")

    def test_the_two_fields_come_together(self):
        only_id = {"name": "CEO", "family": "anthropic", "profile_id": "prof-ceo"}
        only_snap = {"name": "CEO", "family": "anthropic", "profile_snapshot": snapshot()}
        for label, role in {"id only": only_id, "snapshot only": only_snap}.items():
            with self.subTest(label):
                self.bad(roles(planner=role), "一起")

    def test_every_position_is_checked(self):
        bad = self.role(profile_snapshot=snapshot(tool="agy"))
        self.bad(roles(planner=bad), "profile_snapshot")
        self.bad(roles(executor=bad), "profile_snapshot")
        self.bad(roles(reviewers=[{"name": "r", "family": "openai"}, bad]), "profile_snapshot")
        flow = self.create(roles())
        with self.assertRaises(ValueError):
            flows.set_roles(flow["id"], {"roles": roles(executor=bad)})

    def test_unknown_role_keys_are_still_refused(self):
        self.bad(roles(planner=self.role(profile_revision=REV1)), "不接受")
        self.bad(roles(planner=self.role(profile_snapshot={**snapshot(), "extra": 1})), "profile_snapshot")

    def test_a_refused_role_writes_nothing(self):
        flow = self.create(roles())
        before = (self.home / "flows.json").read_text()
        with self.assertRaises(ValueError):
            flows.set_roles(flow["id"], {"roles": roles(planner=self.role(profile_id="a b"))})
        self.assertEqual((self.home / "flows.json").read_text(), before)

    def test_family_name_and_model_stay_the_callers_own_words(self):
        # the server neither derives them from the snapshot nor rewrites the snapshot from them
        team = roles(planner=self.role(name="另一個名字", family="google", model="m-1"))
        stored = flows.get_flow(self.create(team)["id"])["roles"]["planner"]
        self.assertEqual((stored["name"], stored["family"], stored["model"]), ("另一個名字", "google", "m-1"))
        self.assertEqual(stored["profile_snapshot"]["name"], "CEO")
        self.assertEqual(stored["profile_snapshot"]["tool"], "claude")

    def test_empty_second_reviewer_is_the_callers_to_leave_out(self):
        # the page does not send an empty slot; the server's rule of 1-4 reviewers is unchanged
        self.bad(roles(reviewers=[]), "1–4")
        self.bad(roles(reviewers=[{"name": "", "family": "openai"}]), "名稱")
        self.assertEqual(len(flows.get_flow(self.create(roles())["id"])["roles"]["reviewers"]), 1)


class StoredShapeTests(FlowCase):
    """Whatever is on disk is held to the same shape; an entry flows.py could not have written blocks the store."""

    def corrupt(self, mutate):
        flow = self.create(roles(planner=card({"name": "CEO", "family": "anthropic"}, "prof-ceo")))
        data = json.loads((self.home / "flows.json").read_text())
        mutate(data[flow["id"]]["roles"])
        return flow["id"], data

    def test_bad_stored_snapshots_block(self):
        mutators = {
            "extra key": lambda r: r["planner"]["profile_snapshot"].update(extra=1),
            "bad tool": lambda r: r["planner"]["profile_snapshot"].update(tool="agy"),
            "bad revision": lambda r: r["planner"]["profile_snapshot"].update(revision="xyz"),
            "snapshot dropped": lambda r: r["planner"].pop("profile_snapshot"),
            "id dropped": lambda r: r["planner"].pop("profile_id"),
            "bad id": lambda r: r["planner"].update(profile_id="a b"),
            "snapshot is list": lambda r: r["planner"].update(profile_snapshot=[]),
            "on a reviewer": lambda r: r["reviewers"][0].update(profile_id="prof-x"),
        }
        for label, mutate in mutators.items():
            with self.subTest(label):
                fid, data = self.corrupt(mutate)
                self.assertIsNotNone(flows._entry_problem(fid, data[fid]))

    def test_a_corrupt_card_blocks_the_store_on_load(self):
        fid, data = self.corrupt(lambda r: r["planner"]["profile_snapshot"].update(tool="agy"))
        (self.home / "flows.json").write_text(json.dumps(data))
        with self.assertRaises(StoreError):
            flows.list_flows()
        self.assertTrue((self.home / "flows.json.corrupted").exists())

    def test_the_read_only_snapshot_refuses_it_too(self):
        fid, data = self.corrupt(lambda r: r["planner"]["profile_snapshot"].update(revision="1"))
        (self.home / "flows.json").write_text(json.dumps(data))
        with self.assertRaises(StoreError):
            flows.read_only_snapshot(self.home)

    def test_good_stored_cards_pass_the_read_only_snapshot(self):
        flow = self.create(roles(executor=card({"name": "工匠", "family": "anthropic"}, "prof-maker")))
        self.assertIn(flow["id"], flows.read_only_snapshot(self.home))


# --- the API: the revision of a profile and a flow carrying it ------------------------------------------------

def _request(method, port, path, body=None):
    headers = {"X-VBear": "1"} if method != "GET" else {}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        finally:
            e.close()


def _sample(**over):
    base = {"name": "CEO", "profession_role_id": None, "model": {"tool": "claude", "model_id": ""},
            "equipped_skill_ids": [],
            "permission_intents": {"read": "allow", "write": "deny", "test": "deny", "deploy": "deny"}}
    base.update(over)
    return base


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sd = state_dir()
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        cls.port = cls.httpd.server_address[1]
        c = server.Console.__new__(server.Console)
        c.port = cls.port
        c.store = Store()
        c.lock = threading.Lock()
        c.auth_token = None
        c.runtime = rt_mod.get_runtime()
        cls.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        sd = state_dir()
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)

    def make(self, **over):
        status, body = _request("POST", self.port, "/api/agent-profiles", _sample(**over))
        self.assertEqual(status, 200, body)
        return body["profile"]

    def test_every_profile_answer_carries_the_revision_of_the_stored_card(self):
        made = self.make()
        stored = agent_profiles.get_profile_readonly(made["id"])
        digest = agent_profiles.profile_digest(stored)
        self.assertEqual(made["revision"], digest)
        status, listed = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual([p["revision"] for p in listed["profiles"]], [digest])
        status, one = _request("GET", self.port, f"/api/agent-profiles/{made['id']}")
        self.assertEqual(one["profile"]["revision"], digest)
        status, dup = _request("POST", self.port, f"/api/agent-profiles/{made['id']}/duplicate", {})
        self.assertEqual(dup["profile"]["revision"],
                         agent_profiles.profile_digest(agent_profiles.get_profile_readonly(dup["profile"]["id"])))
        self.assertNotEqual(dup["profile"]["revision"], digest)

    def test_the_revision_is_the_launch_previews_digest_and_follows_edits(self):
        made = self.make()
        status, edited = _request("POST", self.port, f"/api/agent-profiles/{made['id']}", _sample(name="CEO 二號"))
        self.assertEqual(status, 200, edited)
        self.assertNotEqual(edited["profile"]["revision"], made["revision"])
        self.assertEqual(edited["profile"]["revision"],
                         agent_launch.profile_digest(agent_profiles.get_profile_readonly(made["id"])))
        # a save stamps updated_at, so even a save that changes nothing else is a new revision: the page then says
        # the card "changed", which is true of the stored record (it was saved again)
        self.assertNotEqual(edited["profile"]["revision"], made["revision"])

    def test_the_revision_is_never_stored_or_accepted_from_a_request(self):
        made = self.make()
        stored = json.loads((state_dir() / "agent_profiles.json").read_text())[made["id"]]
        self.assertNotIn("revision", stored)
        self.assertEqual(made["revision"], agent_profiles.profile_digest(stored))
        before = (state_dir() / "agent_profiles.json").read_text()
        status, body = _request("POST", self.port, f"/api/agent-profiles/{made['id']}", _sample(revision="f" * 64))
        self.assertEqual(status, 400, body)
        self.assertEqual((state_dir() / "agent_profiles.json").read_text(), before)

    def test_a_flow_keeps_the_card_through_the_api(self):
        made = self.make()
        status, task = _request("POST", self.port, "/api/tasks", {"title": "T"})
        self.assertEqual(status, 200, task)
        snap = {"name": made["name"], "tool": "claude", "model_id": "", "revision": made["revision"]}
        team = roles(planner={"name": "CEO", "family": "anthropic", "profile_id": made["id"], "profile_snapshot": snap})
        status, created = _request("POST", self.port, "/api/flows", {"task_id": task["task"]["id"], "roles": team})
        self.assertEqual(status, 200, created)
        status, got = _request("GET", self.port, f"/api/flows/{created['flow']['id']}")
        self.assertEqual(got["flow"]["roles"]["planner"]["profile_snapshot"], snap)
        # the card changes; the flow keeps what was recorded and the page compares
        _request("POST", self.port, f"/api/agent-profiles/{made['id']}", _sample(name="CEO 二號"))
        status, now = _request("GET", self.port, f"/api/agent-profiles/{made['id']}")
        status, got = _request("GET", self.port, f"/api/flows/{created['flow']['id']}")
        self.assertEqual(got["flow"]["roles"]["planner"]["profile_snapshot"]["revision"], made["revision"])
        self.assertNotEqual(now["profile"]["revision"], made["revision"])

    def test_the_api_refuses_a_bad_snapshot_with_400(self):
        status, task = _request("POST", self.port, "/api/tasks", {"title": "T"})
        bad = roles(planner={"name": "CEO", "family": "anthropic", "profile_id": "prof-a",
                             "profile_snapshot": snapshot(tool="agy")})
        status, body = _request("POST", self.port, "/api/flows", {"task_id": task["task"]["id"], "roles": bad})
        self.assertEqual(status, 400)
        self.assertIn("profile_snapshot", body["error"])


if __name__ == "__main__":
    unittest.main()
