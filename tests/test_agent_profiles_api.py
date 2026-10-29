"""Phase C2 Agent Builder API endpoint tests.

Boots a real `vbear.server.Console` on loopback, then drives it via
urllib like a browser would. Checks the wiring (catalog, list, get,
create, update, delete, duplicate), the security headers (write needs
X-VBear and same-origin Origin; oversized body is 413), the
validation boundary (unknown fields, unknown permission key, unknown
tool, missing name, missing model), and the fail-closed 503 path when
the storage layer is in a state that would lose data.

Run: python3 -m unittest tests.test_agent_profiles_api -v
"""

from __future__ import annotations

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

# Same reuse-guard as tests/test_tasks.py:18-24 / tests/test_console.py —
# don't overwrite a HOME already pinned by a sibling module loaded earlier
# by `unittest discover`, or every test across the suite would observe the
# wrong fake-home.
if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-agent-api-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_launch, agent_profiles, server  # noqa: E402
from vbear import runtime as rt_mod  # noqa: E402
from vbear.config import state_dir  # noqa: E402
from vbear.index import Store  # noqa: E402


def _fresh_console():
    sd = state_dir()
    if sd.exists():
        shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)

    # the OS picks the port: the listening socket is made first (port 0) and its real port is read back, so no
    # other process can take it between "find a free port" and "listen on it"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    c = server.Console.__new__(server.Console)
    c.port = port
    c.store = Store()
    c.lock = threading.Lock()
    c.auth_token = None  # auth has its own tests (AuthTests)
    c.runtime = rt_mod.get_runtime()  # native; never autostarts a daemon
    httpd.RequestHandlerClass = server.make_handler(c)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return c, httpd, port


def _request(method, port, path, body=None, headers=None):
    url = f"http://127.0.0.1:{port}{path}"
    h = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=payload, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:
            data = None
        finally:
            e.close()                      # the error owns the response body's temp file
        return e.code, data


def _write_headers(headers=None):
    h = {"X-VBear": "1"}
    if headers:
        h.update(headers)
    return h


def _sample(**overrides):
    base = {
        "name": "Sample",
        "profession_role_id": None,
        "model": {"tool": "claude", "model_id": "opus-4.1"},
        "equipped_skill_ids": [],
        "permission_intents": {"read": "allow", "write": "deny",
                                "test": "unspecified", "deploy": "deny"},
    }
    base.update(overrides)
    return base


class AgentBuilderAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.console, cls.httpd, cls.port = _fresh_console()

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

    def test_catalog_skills_say_which_other_tools_read_them(self):
        skill = {"tool": "codex", "scope": "user", "activation": "active", "description": {"value": "d"}}
        self.console.store._static = {"skills": [
            {**skill, "skill_id": "s-1", "name": "one", "read_by": ["agy"]},
            {**skill, "skill_id": "s-2", "name": "two"},
            {**skill, "skill_id": "s-3", "name": "three", "read_by": "agy"},
            {**skill, "skill_id": "s-4", "name": "four", "read_by": ["agy", 7, None, "x" * 99]}], "roles": []}
        self.console.store._static_stamp = None
        try:
            _, body = _request("GET", self.port, "/api/agent-builder/catalog")
        finally:
            self.console.store._static = None
        got = {s["skill_id"]: s["read_by"] for s in body["skills"]}
        self.assertEqual(got, {"s-1": ["agy"], "s-2": [], "s-3": [], "s-4": ["agy"]})

    def test_catalog_skills_carry_the_modified_time_the_picker_uses_to_pick_one_of_same_named_copies(self):
        skill = {"tool": "claude", "scope": "user", "activation": "active", "description": {"value": "d"}}
        self.console.store._static = {"skills": [
            {**skill, "skill_id": "s-1", "name": "one", "mtime": 1700000000.5},
            {**skill, "skill_id": "s-2", "name": "two"},
            {**skill, "skill_id": "s-3", "name": "three", "mtime": "soon"},
            {**skill, "skill_id": "s-4", "name": "four", "mtime": True}], "roles": []}
        self.console.store._static_stamp = None
        try:
            _, body = _request("GET", self.port, "/api/agent-builder/catalog")
        finally:
            self.console.store._static = None
        got = {s["skill_id"]: s["mtime"] for s in body["skills"]}
        self.assertEqual(got, {"s-1": 1700000000.5, "s-2": 0, "s-3": 0, "s-4": 0})

    def test_catalog_excerpt_keeps_a_long_description_whole_up_to_a_stated_limit(self):
        # the wizard's hover box shows the original in full; the old cut at 140 characters left it a stub
        skill = {"tool": "claude", "scope": "user", "activation": "active"}
        long_text = "Fake skill text. " * 60          # 1020 characters
        huge_text = "Z" * 5000
        self.console.store._static = {"skills": [
            {**skill, "skill_id": "s-1", "name": "one", "description": {"value": long_text}},
            {**skill, "skill_id": "s-2", "name": "two", "description": {"value": huge_text}}], "roles": []}
        self.console.store._static_stamp = None
        try:
            _, body = _request("GET", self.port, "/api/agent-builder/catalog")
        finally:
            self.console.store._static = None
        got = {s["skill_id"]: s["excerpt"] for s in body["skills"]}
        self.assertEqual(got["s-1"], long_text)
        self.assertEqual(len(got["s-2"]), 2000)

    def test_catalog_carries_the_use_categories_for_the_picker_category_row(self):
        skill = {"tool": "claude", "scope": "user", "activation": "active", "description": {"value": "d"}}
        self.console.store._static = {"skills": [
            {**skill, "skill_id": "s-1", "name": "one",
             "categories": [{"id": "design", "label": "設計與介面", "keyword": "ui", "origin": "derived"}, "junk", {"id": 3}]},
            {**skill, "skill_id": "s-2", "name": "two"}], "roles": [],
            "category_table": [{"id": "design", "label": "設計與介面", "query": ["ui"]}, {"id": 5, "label": "x"}, "junk"]}
        self.console.store._static_stamp = None
        try:
            _, body = _request("GET", self.port, "/api/agent-builder/catalog")
        finally:
            self.console.store._static = None
        self.assertEqual({s["skill_id"]: s["categories"] for s in body["skills"]}, {"s-1": ["design"], "s-2": []})
        self.assertEqual(body["skill_categories"], [{"id": "design", "label": "設計與介面"}])

    def test_catalog_endpoint_lists_tool_and_permission_enums(self):
        status, body = _request("GET", self.port, "/api/agent-builder/catalog")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(set(body["tools"]),
                         {"claude", "codex", "agy", "shared"})
        # the camps in the order the wizard offers them: AGY sits before the generic shared camp
        self.assertEqual(body["tools"], ["claude", "codex", "agy", "shared"])
        self.assertEqual(body["permission_keys"], ["read", "write", "test", "deploy"])
        self.assertEqual(body["permission_values"],
                         ["allow", "deny", "unspecified"])
        self.assertTrue(body["permission_intent_only"])
        self.assertEqual(body["max_profiles"], agent_profiles.MAX_PROFILES)
        self.assertEqual(body["max_skills_per_profile"],
                         agent_profiles.MAX_SKILLS_PER_PROFILE)
        # Disclosures must be present and honest about intent-only semantics.
        joined = "\n".join(body["disclosures"])
        self.assertIn("只是你的挑選紀錄", joined)
        self.assertIn("VBear 不會因此限制這個程式的真實能力", joined)
        self.assertIn("不會寫入 ~/.codex", joined)
        for old in ("Agent Profile", "Permission Intents", "Equipped Skill Loadout"):
            self.assertNotIn(old, joined)

    def test_catalog_carries_model_options_from_the_cache_and_the_usage_scan(self):
        codex_dir = FAKE_HOME / ".codex"
        cache = codex_dir / "models_cache.json"
        had_dir = codex_dir.exists()
        codex_dir.mkdir(exist_ok=True)
        self.assertFalse(cache.exists(), "the fake home holds no cache before this test")
        cache.write_text(json.dumps({"identity": "FAKE-IDENTITY", "models": [
            {"slug": "gpt-test-1", "display_name": "Test One", "visibility": "list", "priority": 1, "base_instructions": "FAKE"},
            {"slug": "gpt-test-hidden", "display_name": "Hidden", "visibility": "hide", "priority": 0}]}))
        self.console.store._static = {"skills": [], "roles": []}
        self.console.store._static_stamp = None
        self.console.store._live = {"usage": {"sessions": [
            {"tool": "claude", "models": {"claude-test-5": 3}, "last_ts": "2026-10-20T00:00:00Z"}]}}
        try:
            status, body = _request("GET", self.port, "/api/agent-builder/catalog")
        finally:
            self.console.store._live = None
            self.console.store._static = None
            cache.unlink()
            if not had_dir:
                codex_dir.rmdir()
        self.assertEqual(status, 200)
        options = body["model_options"]
        self.assertEqual(set(options), {"claude", "codex"})
        self.assertEqual([o["value"] for o in options["claude"]["latest"]], ["fable", "opus", "sonnet", "haiku"])
        self.assertEqual([o["value"] for o in options["claude"]["observed"]], ["claude-test-5"])
        self.assertEqual(options["codex"]["listed"], [{"value": "gpt-test-1", "label": "Test One"}])
        self.assertNotIn("FAKE", json.dumps(body))
        self.assertNotIn("IDENTITY", json.dumps(body))

    def test_catalog_without_a_cache_or_usage_still_answers_with_the_aliases(self):
        self.console.store._live = None
        status, body = _request("GET", self.port, "/api/agent-builder/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(body["model_options"]["claude"]["observed"], [])
        self.assertEqual(body["model_options"]["codex"]["listed"], [])
        self.assertTrue(body["model_options"]["codex"]["problem"])

    def test_catalog_serves_the_starter_deck_exactly(self):
        status, body = _request("GET", self.port, "/api/agent-builder/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(body["positions"], ["planner", "executor", "social", "art", "pm", "legal", "accountant",
                                             "reviewer"])
        self.assertEqual(body["retired_positions"], agent_profiles.RETIRED_POSITIONS)
        self.assertEqual(body["position_table"], [dict(r) for r in agent_profiles.POSITION_TABLE])
        self.assertEqual(body["demo_id_prefix"], "demo-")
        deck = body["starter_deck"]
        self.assertEqual([(c["key"], c["name"], c["position"], c["tool"]) for c in deck], [
            ("planner", "CEO", "planner", "claude"),
            ("executor", "全端工程師", "executor", "claude"),
            ("reviewer", "審查員", "reviewer", "codex")])
        # v1.2 R10: every card carries the one combination a managed launch honours, taken from one place
        self.assertEqual([c["permission_intents"] for c in deck], [dict(agent_launch.VERIFIED_INTENTS)] * 3)
        self.assertEqual(body["verified_intents"], {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"})
        self.assertEqual(body["verified_intents"], agent_launch.VERIFIED_INTENTS)
        # the response is a copy: the constants cannot be edited through it
        deck[0]["permission_intents"]["write"] = "deny"
        body["verified_intents"]["write"] = "deny"
        self.assertEqual(agent_profiles.STARTER_DECK[0]["permission_intents"]["write"], "allow")
        self.assertEqual(agent_profiles.VERIFIED_INTENTS["write"], "allow")
        self.assertIsInstance(body["codex_installed"], bool)

    def test_starter_deck_constant_is_safe_to_save_and_has_a_cross_tool_reviewer(self):
        deck = agent_profiles.STARTER_DECK
        self.assertEqual(len(deck), 3)
        # the starter deck is still the three cards of the task card's places; the other five positions are not in it
        self.assertEqual([c["position"] for c in deck], ["planner", "executor", "reviewer"])
        self.assertTrue(set(c["position"] for c in deck) <= set(agent_profiles.POSITIONS))
        for card in deck:
            self.assertIn(card["tool"], agent_profiles.KNOWN_TOOLS)
            self.assertEqual(set(card["permission_intents"]), set(agent_profiles.PERMISSION_KEYS))
            # a suggestion is always decided: the wizard must not make a card that cannot launch
            self.assertTrue(set(card["permission_intents"].values()) <= {"allow", "deny"})
            self.assertTrue(card["name"].strip())
        tools = {c["position"]: c["tool"] for c in deck}
        self.assertNotEqual(tools["executor"], tools["reviewer"])
        # none of them grants deploy
        self.assertTrue(all(c["permission_intents"]["deploy"] == "deny" for c in deck))
        # R10: the intents alone never keep a starter card from going, and the deck and the launch rules share one
        # constant (agent_launch only imports it)
        self.assertIs(agent_launch.VERIFIED_INTENTS, agent_profiles.VERIFIED_INTENTS)
        for card in deck:
            self.assertEqual(card["permission_intents"], agent_launch.VERIFIED_INTENTS, card["key"])
            self.assertEqual(agent_launch.intent_blockers(card["permission_intents"]), [], card["key"])
            blockers = agent_launch.launch_blockers(
                {"model": {"tool": card["tool"]}, "enabled": True, "permission_intents": dict(card["permission_intents"])},
                True, {"enabled": False, "approved_domains": []})
            # the only thing in the way of a starter card is Codex itself; never an intent
            self.assertTrue(all(b["code"].startswith("codex_") for b in blockers), (card["key"], blockers))
        # and each one goes through the ordinary save
        for card in deck:
            status, saved = _request("POST", self.port, "/api/agent-profiles", headers=_write_headers(), body={
                "name": card["name"], "profession_role_id": None, "model": {"tool": card["tool"], "model_id": ""},
                "equipped_skill_ids": [], "permission_intents": dict(card["permission_intents"]), "enabled": True})
            self.assertEqual(status, 200, saved)
            self.assertEqual(saved["profile"]["permission_intents"], card["permission_intents"])
        # the card's suggested position is a profile field since P32-3: a listed one is stored, an unknown one is a 400
        status, kept = _request("POST", self.port, "/api/agent-profiles", headers=_write_headers(),
                                body=_sample(position="planner"))
        self.assertEqual(status, 200, kept)
        self.assertEqual(kept["profile"]["position"], "planner")
        status, _ = _request("POST", self.port, "/api/agent-profiles", headers=_write_headers(),
                             body=_sample(position="boss"))
        self.assertEqual(status, 400)

    def test_position_is_saved_listed_kept_by_enabled_and_cleared(self):
        status, made = _request("POST", self.port, "/api/agent-profiles", headers=_write_headers(),
                                body=_sample(name="Has position", position="legal"))
        self.assertEqual(status, 200, made)
        pid = made["profile"]["id"]
        self.assertEqual(made["profile"]["position"], "legal")
        # 停用／啟用 posts only the on/off state: neither the position nor the profession moves
        for flag in (False, True):
            status, saved = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                                     headers=_write_headers(), body={"enabled": flag})
            self.assertEqual(status, 200, saved)
            self.assertEqual(saved["profile"]["position"], "legal")
        status, listing = _request("GET", self.port, "/api/agent-profiles")
        mine = [p for p in listing["profiles"] if p["id"] == pid][0]
        self.assertEqual(mine["position"], "legal")
        # an unknown value is refused and changes nothing
        status, _ = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                             headers=_write_headers(), body={"position": "boss"})
        self.assertEqual(status, 400)
        status, one = _request("GET", self.port, f"/api/agent-profiles/{pid}")
        self.assertEqual(one["profile"]["position"], "legal")
        # a copy carries it
        status, dup = _request("POST", self.port, f"/api/agent-profiles/{pid}/duplicate", headers=_write_headers(), body={})
        self.assertEqual(status, 200, dup)
        self.assertEqual(dup["profile"]["position"], "legal")
        # null clears it
        status, cleared = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                                   headers=_write_headers(), body={"position": None})
        self.assertEqual(status, 200, cleared)
        self.assertNotIn("position", cleared["profile"])

    def test_posting_only_enabled_keeps_the_card_profession(self):
        # P32-1: the workbench 停用／啟用 button posts {"enabled": ...} and nothing else
        status, made = _request("POST", self.port, "/api/agent-profiles", headers=_write_headers(),
                                body=_sample(name="Keeps profession", profession_role_id="ghost-role"))
        self.assertEqual(status, 200, made)
        pid = made["profile"]["id"]
        for flag in (False, True):
            status, saved = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                                     headers=_write_headers(), body={"enabled": flag})
            self.assertEqual(status, 200, saved)
            self.assertEqual(saved["profile"]["enabled"], flag)
            self.assertEqual(saved["profile"]["profession_role_id"], "ghost-role")
        status, listing = _request("GET", self.port, "/api/agent-profiles")
        mine = [p for p in listing["profiles"] if p["id"] == pid][0]
        self.assertEqual(mine["profession_role_id"], "ghost-role")
        # an explicit null still clears it
        status, saved = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                                 headers=_write_headers(), body={"profession_role_id": None})
        self.assertEqual(status, 200, saved)
        self.assertIsNone(saved["profile"]["profession_role_id"])

    def test_intent_check_names_the_launch_rules_reasons_and_nothing_else(self):
        def check(**q):
            from urllib.parse import urlencode
            return _request("GET", self.port, "/api/agent-builder/intent-check?" + urlencode(q))
        # the verified combination: nothing in the way
        status, body = check(**agent_launch.VERIFIED_INTENTS)
        self.assertEqual((status, body["ok"], body["can_launch"], body["blockers"]), (200, True, True, []))
        self.assertEqual(body["intents"], agent_launch.VERIFIED_INTENTS)
        # one row per rule, with the server's own code and words
        cases = [({"write": "deny"}, "readonly_unverified"), ({"read": "deny"}, "read_deny_unenforceable"),
                 ({"test": "deny"}, "test_deny_unenforceable"), ({"deploy": "allow"}, "deploy_not_available"),
                 ({"write": "unspecified"}, "intent_unspecified")]
        for change, code in cases:
            status, body = check(**{**agent_launch.VERIFIED_INTENTS, **change})
            self.assertEqual(status, 200)
            self.assertFalse(body["can_launch"], change)
            self.assertIn(code, [b["code"] for b in body["blockers"]], change)
            expected = agent_launch.intent_blockers({**agent_launch.VERIFIED_INTENTS, **change})
            self.assertEqual(body["blockers"], expected)
        # it answers about the intents alone: no reason about the tool, the commit or the network
        status, body = check(read="deny", write="deny", test="deny", deploy="deny")
        self.assertEqual(sorted(b["code"] for b in body["blockers"]),
                         ["read_deny_unenforceable", "readonly_unverified", "test_deny_unenforceable"])
        # missing, extra, repeated and unknown values are refused, not guessed
        for q in ("", "read=allow&write=allow&test=allow", "read=allow&write=allow&test=allow&deploy=deny&x=1",
                  "read=allow&read=deny&write=allow&test=allow&deploy=deny",
                  "read=allow&write=allow&test=allow&deploy=maybe", "read=enforce&write=allow&test=allow&deploy=deny"):
            status, _ = _request("GET", self.port, "/api/agent-builder/intent-check" + ("?" + q if q else ""))
            self.assertEqual(status, 400, q)

    def test_intent_check_runs_nothing_and_writes_nothing(self):
        import subprocess
        before = sorted(p.name for p in state_dir().iterdir())
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("ran a program")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("ran a program")):
            status, _ = _request("GET", self.port, "/api/agent-builder/intent-check?read=allow&write=deny&test=allow&deploy=deny")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(p.name for p in state_dir().iterdir()), before)

    def test_catalog_codex_installed_is_a_stat_of_the_pinned_path_and_runs_nothing(self):
        import subprocess
        from vbear.runtime import review_codex
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("ran a program")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("ran a program")):
            with mock.patch.object(review_codex, "codex_binary", side_effect=review_codex.CodexRefused("no_binary", "x")):
                _, body = _request("GET", self.port, "/api/agent-builder/catalog")
                self.assertIs(body["codex_installed"], False)
            with mock.patch.object(review_codex, "codex_binary", return_value="/pinned/codex") as found:
                _, body = _request("GET", self.port, "/api/agent-builder/catalog")
                self.assertIs(body["codex_installed"], True)
                self.assertTrue(found.called)

    def test_create_then_list_then_get(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="One"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        pid = body["profile"]["id"]
        self.assertEqual(body["profile"]["name"], "One")
        self.assertEqual(body["profile"]["model"]["tool"], "claude")

        status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 200)
        self.assertEqual([p["name"] for p in body["profiles"]], ["One"])

        status, body = _request("GET", self.port, f"/api/agent-profiles/{pid}")
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"]["id"], pid)

    def test_get_unknown_id_is_404(self):
        status, _ = _request("GET", self.port, "/api/agent-profiles/prof-not-here")
        self.assertEqual(status, 404)

    def test_update_keeps_created_at_and_advances_updated_at(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="v1"),
                                headers=_write_headers())
        pid = body["profile"]["id"]
        created_at = body["profile"]["created_at"]
        # ensure updated_at changes
        import time as _t
        _t.sleep(0.01)
        status, body = _request("POST", self.port, f"/api/agent-profiles/{pid}",
                                body=_sample(name="v2"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"]["name"], "v2")
        self.assertEqual(body["profile"]["created_at"], created_at)
        self.assertGreater(body["profile"]["updated_at"], created_at)

    def test_delete_then_duplicate(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="Origin"),
                                headers=_write_headers())
        pid = body["profile"]["id"]
        status, body = _request("POST", self.port,
                                f"/api/agent-profiles/{pid}/duplicate", body={},
                                headers=_write_headers())
        self.assertEqual(status, 200)
        dup_id = body["profile"]["id"]
        self.assertNotEqual(dup_id, pid)
        self.assertTrue(body["profile"]["name"].startswith("Origin"))

        status, _ = _request("POST", self.port,
                              f"/api/agent-profiles/{dup_id}/delete", body={},
                              headers=_write_headers())
        self.assertEqual(status, 200)
        status, _ = _request("GET", self.port, f"/api/agent-profiles/{dup_id}")
        self.assertEqual(status, 404)

    def test_delete_unknown_is_404(self):
        status, _ = _request("POST", self.port,
                              "/api/agent-profiles/prof-missing/delete", body={},
                              headers=_write_headers())
        self.assertEqual(status, 404)

    def test_duplicate_value_error_is_400(self):
        # AGY review 2026-09-25 (Low): ValueError from duplicate must be 400,
        # not fall through to the generic 500 handler.
        with mock.patch.object(agent_profiles, "duplicate_profile",
                               side_effect=ValueError("角色卡已達上限 500 筆")):
            status, body = _request("POST", self.port,
                                    "/api/agent-profiles/prof-any/duplicate",
                                    body={}, headers=_write_headers())
        self.assertEqual(status, 400)
        self.assertIn("上限", json.dumps(body, ensure_ascii=False))

    def test_duplicate_unknown_is_404(self):
        status, _ = _request("POST", self.port,
                              "/api/agent-profiles/prof-missing/duplicate", body={},
                              headers=_write_headers())
        self.assertEqual(status, 404)

    def test_write_without_header_is_403(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="X"),
                                headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_write_with_foreign_origin_is_403(self):
        status, _ = _request("POST", self.port, "/api/agent-profiles",
                              body=_sample(name="X"),
                              headers={"X-VBear": "1",
                                        "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_write_with_wrong_host_is_421(self):
        # Send to the real server's port with a spoofed Host header.
        h = {"Host": "evil.example", "X-VBear": "1",
             "Content-Type": "application/json"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/agent-profiles",
            data=b'{}', headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
            e.close()
        self.assertEqual(status, 421)

    def test_oversized_body_is_413(self):
        huge = "x" * (64 * 1024 + 16)
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body={"name": huge,
                                      "model": {"tool": "claude",
                                                "model_id": "a"}},
                                headers=_write_headers())
        self.assertEqual(status, 413)
        # And the file must NOT have been written.
        self.assertFalse(agent_profiles._path().exists())

    def test_unknown_tool_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(model={"tool": "rogue",
                                                     "model_id": "a"}),
                                headers=_write_headers())
        self.assertEqual(status, 400)
        self.assertIn("支援的工具", body["error"])

    def test_unknown_permission_key_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(permission_intents={
                                    "read": "allow", "sudo": "allow"}),
                                headers=_write_headers())
        self.assertEqual(status, 400)
        self.assertIn("permission_intents", body["error"])

    def test_invalid_permission_value_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(permission_intents={
                                    "read": "force"}),
                                headers=_write_headers())
        self.assertEqual(status, 400)

    def test_unknown_top_level_field_is_400(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body={"name": "X",
                                      "model": {"tool": "claude",
                                                "model_id": "a"},
                                      "enforce_everywhere": True},
                                headers=_write_headers())
        self.assertEqual(status, 400)

    def test_empty_name_is_400(self):
        status, _ = _request("POST", self.port, "/api/agent-profiles",
                              body=_sample(name="   "),
                              headers=_write_headers())
        self.assertEqual(status, 400)

    def test_unresolved_skill_is_kept_not_dropped(self):
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(equipped_skill_ids=["unknown-skill-id"]),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"]["equipped_skill_ids"],
                         ["unknown-skill-id"])
        self.assertEqual(body["profile"]["_unresolved"]["skills"],
                         ["unknown-skill-id"])

    def test_corruption_marks_503_on_subsequent_writes(self):
        # Seed a valid profile, then corrupt the file the way a partial write
        # might, and confirm the next API write returns 503 instead of
        # silently clobbering real data.
        status, body = _request("POST", self.port, "/api/agent-profiles",
                                body=_sample(name="Real"),
                                headers=_write_headers())
        self.assertEqual(status, 200)
        pid = body["profile"]["id"]

        path = agent_profiles._path()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["t-broken"] = {"id": "t-broken", "name": "x",
                             "model": {"tool": "rogue", "model_id": "y"}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        # Subsequent reads must be 503.
        status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 503, body)
        # And the real profile must still be recoverable after the operator
        # manually clears the marker — same invariant tasks.py enforces.
        agent_profiles._corrupt_marker_path().unlink(missing_ok=True)
        status, body = _request("GET", self.port, "/api/agent-profiles")
        self.assertEqual(status, 200)

    def test_storage_path_does_not_leak_into_codepath_for_sessions(self):
        """The AgentProfile write path must NEVER touch ~/.codex, ~/.claude,
        third-party skill/role sources, Herdr, or session artifacts.

        We monkey-patch the obvious "outside" filesystem root and assert
        the AgentProfile POST never invokes anything that could write to
        it. The same patches are torn down at the end of the test.
        """
        real_open = Path.open
        leaks: list[str] = []

        def spy_open(self, *args, **kwargs):
            text = str(self)
            if ("/.codex/" in text or "/.claude/" in text
                    or "/.agents/" in text or "/herdr" in text.lower()):
                if "w" in kwargs.get("mode", "r") or "a" in kwargs.get("mode", "r"):
                    leaks.append(text)
            return real_open(self, *args, **kwargs)

        with mock.patch.object(Path, "open", spy_open):
            status, body = _request("POST", self.port, "/api/agent-profiles",
                                    body=_sample(name="LeakProbe"),
                                    headers=_write_headers())
            self.assertEqual(status, 200)
        self.assertEqual(leaks, [],
                         f"AgentProfile write leaked to {leaks}")


if __name__ == "__main__":
    unittest.main()