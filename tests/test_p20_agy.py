"""P20: Antigravity (AGY) as a fourth camp of role cards. VBear does not launch it: the card is a record for
building teams. These tests lock the backend side — the tool id, its family, the refusal to launch, the flow
snapshot, the independent-review rule and the words of the role card's back. (That the page's own tables are the
same ones is locked in test_p20_agy_page.)

Run: python3 -m unittest tests.test_p20_agy -v
"""

from __future__ import annotations

import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

if "VBEAR_HOME" not in os.environ:
    _HOME = Path(tempfile.mkdtemp(prefix="vbear-p20-"))
    os.environ["HOME"] = str(_HOME)
    os.environ["VBEAR_HOME"] = str(_HOME / ".vbear")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_launch, agent_profiles, flows, loadout, risk_acceptance  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GOOD = {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"}
NET_OFF = {"enabled": False, "approved_domains": []}
REV = "ab" * 32
AGY_NOT_LAUNCHED = "VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄"


def profile(tool="agy", **over):
    base = {"id": "prof-agy", "name": "AGY 審查員", "profession_role_id": None,
            "model": {"tool": tool, "model_id": ""}, "equipped_skill_ids": [],
            "permission_intents": dict(GOOD), "enabled": True, "created_at": 1.0, "updated_at": 1.0}
    base.update(over)
    return base


def snapshot(**over):
    return {**{"name": "AGY 審查員", "tool": "agy", "model_id": "", "revision": REV}, **over}


def role(family="google", **over):
    return {"name": "AGY 審查員", "family": family, "profile_id": "prof-agy", "profile_snapshot": snapshot(**over)}


class ToolRegistryTests(unittest.TestCase):
    def test_agy_is_a_known_tool_and_nothing_else_was_added(self):
        self.assertEqual(agent_profiles.KNOWN_TOOLS, frozenset({"claude", "codex", "agy", "shared"}))
        self.assertEqual(set(agent_profiles.TOOL_ORDER), set(agent_profiles.KNOWN_TOOLS))
        self.assertEqual(len(agent_profiles.TOOL_ORDER), len(agent_profiles.KNOWN_TOOLS))

    def test_the_order_the_camps_are_offered_in(self):
        # the three tools of before keep their places; AGY sits before the generic shared camp
        self.assertEqual(agent_profiles.TOOL_ORDER, ("claude", "codex", "agy", "shared"))

    def test_the_family_of_each_tool(self):
        self.assertEqual(agent_profiles.TOOL_FAMILY, {"claude": "anthropic", "codex": "openai", "agy": "google",
                                                       "shared": "unknown"})
        self.assertEqual(agent_profiles.family_of_tool("agy"), "google")
        for other in ("gemini", "AGY", "", None, 5, ["agy"], "toString"):
            self.assertEqual(agent_profiles.family_of_tool(other), "unknown", repr(other))

    def test_every_family_the_table_names_is_one_a_flow_accepts(self):
        for family in agent_profiles.TOOL_FAMILY.values():
            self.assertIn(family, flows.FAMILIES)

    def test_an_agy_card_can_be_saved_and_a_new_tool_string_still_cannot(self):
        body = {"name": "A", "model": {"tool": "agy", "model_id": ""},
                "permission_intents": dict(GOOD)}
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {"VBEAR_HOME": tmp}):
            saved = agent_profiles.save_profile(None, body, known_skills=set(), known_roles=set())
            self.assertEqual(saved["model"]["tool"], "agy")
            self.assertEqual(agent_profiles.get_profile(saved["id"])["model"]["tool"], "agy")
            for bad in ("gemini", "AGY", "antigravity", "google", ""):
                with self.subTest(tool=bad):
                    with self.assertRaises(ValueError):
                        agent_profiles.save_profile(None, {**body, "model": {"tool": bad, "model_id": ""}},
                                                    known_skills=set(), known_roles=set())

    def test_the_error_for_an_unknown_tool_lists_agy(self):
        body = {"name": "A", "model": {"tool": "gemini", "model_id": ""}, "permission_intents": dict(GOOD)}
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {"VBEAR_HOME": tmp}):
            with self.assertRaises(ValueError) as cm:
                agent_profiles.save_profile(None, body, known_skills=set(), known_roles=set())
        self.assertIn("agy", str(cm.exception))


class LaunchRefusalTests(unittest.TestCase):
    def reasons(self, prof, commit=True):
        return agent_launch.launch_blockers(prof, commit, NET_OFF)

    def test_an_agy_card_is_refused_in_clear_words(self):
        out = self.reasons(profile())
        self.assertEqual([b["code"] for b in out], ["tool_not_launchable"])
        self.assertEqual(out[0]["message"], AGY_NOT_LAUNCHED)

    def test_the_other_refusals_keep_their_words(self):
        shared = self.reasons(profile(tool="shared"))
        self.assertEqual(shared[0]["message"], "shared 不是可啟動的工具")
        unknown = self.reasons(profile(tool="gemini"))
        self.assertEqual(unknown[0]["message"], "此 Agent 工具沒有受管啟動設定")

    def test_an_agy_card_stays_refused_with_every_other_input_in_order(self):
        # a good folder, commit acknowledged, network off: the tool alone still stops it
        self.assertTrue(any(b["code"] == "tool_not_launchable" for b in self.reasons(profile(), commit=True)))
        # and the other reasons are still reported beside it, none dropped
        out = self.reasons(profile(permission_intents={k: "unspecified" for k in GOOD}), commit=False)
        codes = {b["code"] for b in out}
        self.assertTrue({"tool_not_launchable", "intent_unspecified", "commit_not_enforceable"} <= codes)

    def test_the_labels_of_a_refused_agy_preview_claim_nothing(self):
        labels = agent_launch.derive_labels(None, "/tmp/work", "agy")
        self.assertEqual({v["level"] for v in labels.values()}, {agent_launch.UNKNOWN})
        text = " ".join(str(v) for v in labels.values())
        self.assertNotIn("強制", text)
        groups = agent_launch.armor_groups("agy")
        self.assertNotIn(agent_launch.UNVERIFIED, [lv for g in groups for lv in g["levels"]])


class RoleCardOfAgyTests(unittest.TestCase):
    """The back of the card (loadout): no shield, no tool list, no skill that loads, and no borrowed words."""

    def build(self, **over):
        return loadout.build(profile(**over), None, None, None)

    def test_no_armor_and_the_reason_names_agy(self):
        data = self.build()
        self.assertIs(data["armor"]["applicable"], False)
        self.assertEqual(data["armor"]["why"], "VBear 還不會啟動 AGY，沒有防具")
        self.assertEqual([b["message"] for b in data["blockers"]], [AGY_NOT_LAUNCHED])

    def test_the_tool_list_is_unknown_and_says_so_in_agys_words(self):
        tools = self.build()["tools"]
        self.assertEqual(tools, {"known": False, "allowed": [], "blocked": [],
                                 "unknown_reason": loadout.TOOLS_AGY_NOT_RECORDED})
        self.assertIn("AGY", loadout.TOOLS_AGY_NOT_RECORDED)
        self.assertNotIn("Claude", loadout.TOOLS_AGY_NOT_RECORDED)

    def test_skills_are_only_collected_and_the_note_is_not_the_shared_one(self):
        data = self.build(equipped_skill_ids=["s-1"])
        sk = data["skills"]
        self.assertEqual([i["will_load"] for i in sk["items"]], [False])
        self.assertIs(sk["all_inactive"], True)
        self.assertEqual(sk["note"], loadout.AGY_SKILLS_NOTE)
        self.assertNotIn("不知道 AGY 會讀哪些技能", loadout.AGY_SKILLS_NOTE)  # P22: it is now judged from AGY's own files
        self.assertIn("不代表 AGY 會載入", loadout.AGY_SKILLS_NOTE)
        self.assertNotIn("shared", sk["note"])
        self.assertNotIn("Claude", sk["note"])

    def test_the_version_and_profession_words_do_not_speak_for_another_tool(self):
        data = self.build(profession_role_id="cli-claude")
        self.assertEqual(data["version_status"]["state"], "unknown")
        self.assertIn("AGY", data["profession"]["label_only"])
        self.assertNotIn("Claude", data["profession"]["label_only"])
        self.assertNotIn("Codex", data["profession"]["label_only"])
        none = self.build()
        self.assertIn("AGY", none["profession"]["label_only"])

    def test_the_other_tools_loadout_words_did_not_change(self):
        self.assertEqual(loadout._label_only("claude"), "職業只是標籤，不會把角色指示載入 Claude Code")
        self.assertEqual(loadout._label_only("codex"), "職業只是標籤，不會把角色指示載入 Codex")
        self.assertEqual(loadout._label_only("shared"), "職業只是標籤，不會把角色指示載入 任何工具")
        self.assertEqual(self.build(model={"tool": "shared", "model_id": ""})["skills"]["note"],
                         loadout.SHARED_SKILLS_NOTE)


class FlowSnapshotTests(unittest.TestCase):
    def test_the_snapshot_tools_are_the_profile_tools_and_the_family_table_is_the_same(self):
        self.assertEqual(set(flows.SNAPSHOT_TOOLS), set(agent_profiles.KNOWN_TOOLS))
        self.assertEqual(flows.SNAPSHOT_TOOL_FAMILY, agent_profiles.TOOL_FAMILY)

    def test_an_agy_snapshot_with_the_google_family_is_accepted_for_input_and_stored_shape(self):
        for executor in (False, True):
            with self.subTest(executor=executor):
                clean = flows._clean_role(role(), executor=executor)
                self.assertEqual(clean["profile_snapshot"]["tool"], "agy")
                self.assertEqual(clean["family"], "google")
                self.assertIsNone(flows._role_problem(clean, executor=executor))

    def test_an_agy_snapshot_with_any_other_family_is_refused(self):
        for family in ("anthropic", "openai", "minimax", "other", "unknown"):
            with self.subTest(family=family):
                with self.assertRaises(ValueError) as cm:
                    flows._clean_role(role(family=family), executor=False)
                self.assertIn("google", str(cm.exception))
                self.assertIn("google", flows._role_problem(role(family=family), executor=False))

    def test_other_tools_are_judged_exactly_as_before(self):
        for tool, family in (("claude", "openai"), ("codex", "anthropic"), ("shared", "google"), ("claude", "google")):
            with self.subTest(tool=tool, family=family):
                r = {"name": "x", "family": family, "profile_id": "prof-x", "profile_snapshot": snapshot(tool=tool)}
                self.assertEqual(flows._clean_role(r, executor=False)["profile_snapshot"]["tool"], tool)
                self.assertIsNone(flows._role_problem(r, executor=False))

    def test_a_new_tool_string_is_still_refused(self):
        for tool in ("gemini", "AGY", "antigravity", "agy ", "Agy", "", None, ["agy"]):
            with self.subTest(tool=tool):
                with self.assertRaises(ValueError):
                    flows._clean_role(role(tool=tool), executor=False)


class IndependentReviewTests(unittest.TestCase):
    def test_agy_reviewer_against_a_claude_executor_counts(self):
        counted, why = flows._independent("anthropic", "google")
        self.assertTrue(counted)
        self.assertEqual(why, "")

    def test_agy_reviewer_against_a_codex_executor_counts(self):
        self.assertTrue(flows._independent("openai", "google")[0])

    def test_agy_reviewer_against_a_hand_written_google_executor_does_not(self):
        counted, why = flows._independent("google", "google")
        self.assertFalse(counted)
        self.assertEqual(why, "審查者與執行者同為 Google（Gemini），不算獨立審查，不算通過")

    def test_the_view_says_it_before_any_review_exists(self):
        self.assertEqual(flows._independence_view("anthropic", "google"), {"counted": True, "why": ""})
        self.assertFalse(flows._independence_view("google", "google")["counted"])

    def test_the_automatic_review_is_still_openai_and_never_says_agy(self):
        src = (REPO / "vbear" / "flows.py").read_text(encoding="utf-8")
        self.assertIn('"name": "自動審查（VBear 啟動的 Codex）", "family": "openai"', src)


class StoredDataTests(unittest.TestCase):
    """Role cards and flows stored before AGY existed read back exactly as they did, and a flow that holds an AGY
    card is read back from the file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = unittest.mock.patch.dict(os.environ, {"VBEAR_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def flow_entry(self, *, planner, reviewers):
        return {"id": "flow-0123456789ab", "task_id": "task-" + "1" * 12, "created_at": 1.0,
                "roles": {"planner": planner, "executor": {"name": "工匠", "family": "anthropic"}, "reviewers": reviewers},
                "events": []}

    def write(self, entry):
        import json
        (Path(self.tmp.name) / "flows.json").write_text(json.dumps({entry["id"]: entry}), encoding="utf-8")

    def test_a_flow_stored_before_agy_with_every_old_tool_and_family_pairing_still_loads(self):
        # the old tools were accepted with any family; only the new tool's family is checked
        reviewers = [role(family=family, tool=tool) for tool, family in
                     (("claude", "openai"), ("codex", "anthropic"), ("shared", "google"))]
        entry = self.flow_entry(planner={"name": "CEO", "family": "anthropic"}, reviewers=reviewers)
        self.assertIsNone(flows._entry_problem(entry["id"], entry))
        self.write(entry)
        self.assertEqual(len(flows.get_flow(entry["id"])["roles"]["reviewers"]), 3)

    def test_a_flow_that_holds_an_agy_card_is_read_back_from_the_file(self):
        entry = self.flow_entry(planner=role(), reviewers=[role()])
        self.assertIsNone(flows._entry_problem(entry["id"], entry))
        self.write(entry)
        got = flows.get_flow(entry["id"])
        self.assertEqual(got["roles"]["planner"]["profile_snapshot"], snapshot())
        self.assertEqual(got["roles"]["reviewers"][0]["family"], "google")

    def test_a_stored_agy_card_with_another_family_blocks_the_store_like_any_other_malformed_entry(self):
        entry = self.flow_entry(planner=role(family="anthropic"), reviewers=[role()])
        self.assertIn("google", flows._entry_problem(entry["id"], entry))
        self.write(entry)
        with self.assertRaises(flows.StoreError):
            flows.list_flows()


class AutomaticModeIsUnchangedTests(unittest.TestCase):
    """The automatic review is the Codex that VBear starts. An AGY card on a review place is a hand record; it is
    neither the automatic reviewer nor a stand-in for it (no change to the automatic mode was made)."""

    def flow(self, *reviewer_families):
        return {"roles": {"planner": {"family": "anthropic"}, "executor": {"family": "anthropic"},
                          "reviewers": [{"family": f} for f in reviewer_families]}}

    def test_an_agy_reviewer_alone_cannot_stand_for_the_automatic_codex_review(self):
        with self.assertRaises(risk_acceptance.AcceptanceError) as cm:
            risk_acceptance._check_families(self.flow("google"))
        self.assertIn("OpenAI 家族的審查者", str(cm.exception))

    def test_with_an_openai_reviewer_beside_it_the_rule_is_met_by_that_reviewer_only(self):
        risk_acceptance._check_families(self.flow("google", "openai"))
        risk_acceptance._check_families(self.flow("openai", "google"))

    def test_the_automatic_reviewer_is_still_recorded_as_codex_whatever_cards_sit_on_the_team(self):
        src = (REPO / "vbear" / "flows.py").read_text(encoding="utf-8")
        self.assertIn('reviewer = {"index": None, "name": "自動審查（VBear 啟動的 Codex）", "family": "openai"}', src)
        for path in ("flow_review.py", "automation.py", "runner.py"):
            text = (REPO / "vbear" / path).read_text(encoding="utf-8")
            self.assertNotIn("agy", text.lower(), path)


if __name__ == "__main__":
    unittest.main()
