"""v0.12 task 2: Grok and MCODE are employees in full mode, and MCODE is behind a switch.

Over HTTP with the runtime daemon in a thread (tests/test_p34_full_launch.FullApiCase), each tool played by a stand-in
file named after it. No Grok, MCODE or any other AI tool is started and nothing leaves this computer.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_agent_launch_api import GOOD
from tests.test_p34_full_launch import FullApiCase
from vbear import agent_launch, agent_profiles, ai_tools, config as cfg, flows, staffing
from vbear.runtime import agent_sessions as a
from vbear.runtime import daemon as d


class FullArgvTests(unittest.TestCase):
    def test_the_two_new_tools_take_the_model_with_dash_m_and_never_the_instructions(self):
        self.assertEqual(a.full_argv("grok", "/x/grok", None, None), ["/x/grok"])
        self.assertEqual(a.full_argv("grok", "/x/grok", "grok-x", "指示"), ["/x/grok", "-m", "grok-x"])
        self.assertEqual(a.full_argv("mcode", "/x/mcode", "MiniMax-X", "指示"), ["/x/mcode", "-m", "MiniMax-X"])

    def test_the_file_name_must_be_the_tool_id(self):
        for engine, binary in (("grok", "/x/mcode"), ("mcode", "/x/grok"), ("grok", "/x/grok-cli"), ("mcode", "grok")):
            with self.subTest(engine=engine, binary=binary), self.assertRaises(a.LaunchRefused):
                a.full_argv(engine, binary, None, None)

    def test_the_daemons_check_takes_what_is_built_and_nothing_else(self):
        for engine in ("grok", "mcode"):
            self.assertIsNone(a.full_argv_problem(engine, a.full_argv(engine, f"/x/{engine}", "m-1", None)))
            self.assertIsNotNone(a.full_argv_problem(engine, [f"/x/{engine}", "--model", "m-1"]))
            self.assertIsNotNone(a.full_argv_problem(engine, [f"/x/{engine}", "--yolo"]))
            self.assertIsNotNone(a.full_argv_problem(engine, [f"/x/{engine}", "--append-system-prompt", "x"]))


class SearchPathTests(unittest.TestCase):
    def test_the_vendors_own_install_folders_are_searched_after_the_system_ones(self):
        extra = d.extra_path("/home/fake")
        self.assertIn("/home/fake/.grok/bin", extra)
        self.assertIn("/home/fake/.minimax-code/bin", extra)
        self.assertIn("/home/fake/.local/bin", extra)
        for sys_dir in d.SYSTEM_EXTRA_PATH:
            self.assertLess(extra.index(sys_dir), extra.index("/home/fake/.grok/bin"))
            self.assertLess(extra.index(sys_dir), extra.index("/home/fake/.minimax-code/bin"))

    def test_a_home_that_is_not_a_plain_absolute_path_adds_none_of_them(self):
        for bad in (None, "", "relative", "/a:b"):
            self.assertEqual(d.extra_path(bad), d.SYSTEM_EXTRA_PATH, bad)

    def test_a_tool_in_those_folders_is_found(self):
        with tempfile.TemporaryDirectory(prefix="vbear-t15-path-") as home:
            for folder, name in ((".grok/bin", "grok"), (".minimax-code/bin", "mcode")):
                target = Path(home, folder)
                target.mkdir(parents=True)
                exe = target / name
                exe.write_text("#!/bin/sh\n")
                exe.chmod(0o700)
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "HOME": home}):
                path = d.cli_search_path()
            import shutil
            self.assertEqual(shutil.which("grok", path=path), str(Path(home, ".grok/bin/grok")))
            self.assertEqual(shutil.which("mcode", path=path), str(Path(home, ".minimax-code/bin/mcode")))


class FamilyRuleTests(unittest.TestCase):
    """The reviewer's camp: xAI and MiniMax are families of their own."""

    def test_each_tool_has_its_own_family(self):
        self.assertEqual(agent_profiles.family_of_tool("grok"), "xai")
        self.assertEqual(agent_profiles.family_of_tool("mcode"), "minimax")
        families = {agent_profiles.family_of_tool(t) for t in ("claude", "codex", "agy", "grok", "mcode")}
        self.assertEqual(len(families), 5)

    def test_a_review_by_another_family_counts_and_one_by_the_same_family_does_not(self):
        def flag(reviewer, executor):
            return staffing._review_flag({"key": "r", "who": {"tool": reviewer}}, {"key": "e", "who": {"tool": executor}})
        for executor, reviewer in (("claude", "grok"), ("grok", "claude"), ("grok", "mcode"), ("mcode", "agy"),
                                   ("codex", "grok"), ("mcode", "claude")):
            with self.subTest(executor=executor, reviewer=reviewer):
                self.assertIsNone(flag(reviewer, executor))
        for tool in ("grok", "mcode"):
            self.assertEqual(flag(tool, tool), "same_family")

    def test_the_flows_accept_and_label_both_families(self):
        for family, label in (("xai", "xAI（Grok）"), ("minimax", "MiniMax")):
            self.assertIn(family, flows.FAMILIES)
            self.assertEqual(flows.FAMILY_LABELS[family], label)

    def test_a_role_made_from_a_grok_or_mcode_card_must_carry_that_tools_family(self):
        def role(tool, family):
            return {"name": "n", "family": family, "profile_id": "p-1",
                    "profile_snapshot": {"name": "n", "tool": tool, "model_id": "", "revision": "0" * 64}}
        for tool, family in (("grok", "xai"), ("mcode", "minimax")):
            self.assertIsNone(flows._role_card_problem(role(tool, family)), tool)
            self.assertIn(family, flows._role_card_problem(role(tool, "openai")), tool)


class ConfigSwitchTests(FullApiCase):
    def conf(self):
        st, r = self.req("GET", "/api/config")
        self.assertEqual(st, 200)
        return r["config"]

    def set_show(self, value):
        return self.req("POST", "/api/config", {"show_mcode": value})

    def tool_ids(self):
        st, cat = self.req("GET", "/api/agent-builder/catalog")
        self.assertEqual(st, 200)
        return cat["tools"], [t["id"] for t in cat["tool_list"]], cat

    def test_the_switch_is_off_by_default_and_the_config_says_so(self):
        self.assertIs(cfg.DEFAULT_CONFIG["show_mcode"], False)
        self.assertIs(self.conf()["show_mcode"], False)

    def test_it_can_be_written_and_is_kept(self):
        st, r = self.set_show(True)
        self.assertEqual(st, 200, r)
        self.assertIs(r["config"]["show_mcode"], True)
        self.assertIs(self.conf()["show_mcode"], True)
        self.assertIs(cfg.load()["show_mcode"], True)
        self.assertEqual(self.set_show(False)[0], 200)
        self.assertIs(self.conf()["show_mcode"], False)

    def test_only_a_real_boolean_is_taken(self):
        for bad in ("true", 1, None, [], {}):
            with self.subTest(value=bad):
                st, r = self.set_show(bad)
                self.assertEqual(st, 400, r)
        self.assertIs(self.conf()["show_mcode"], False)

    def test_off_the_menu_and_the_catalog_have_no_mcode_but_grok_is_there(self):
        tools, listed, cat = self.tool_ids()
        self.assertEqual(tools, ["claude", "codex", "agy", "grok", "shared"])
        self.assertEqual(listed, tools)
        self.assertNotIn("mcode", str([t["id"] for t in cat["tool_list"]]))
        grok = next(t for t in cat["tool_list"] if t["id"] == "grok")
        self.assertEqual((grok["name"], grok["family"], grok["safe_launch"], grok["full_launch"]), ("Grok", "xai", False, True))
        self.assertEqual([t["id"] for t in cat["unavailable_tools"]], ["mcode"])
        mcode = cat["unavailable_tools"][0]
        self.assertEqual((mcode["name"], mcode["family"], mcode["full_launch"]), ("MCODE", "minimax", True))
        self.assertIn("顯示 MCODE", mcode["unavailable_reason"])

    def test_on_the_menu_has_mcode_after_grok(self):
        self.set_show(True)
        tools, listed, cat = self.tool_ids()
        self.assertEqual(tools, ["claude", "codex", "agy", "grok", "mcode", "shared"])
        self.assertEqual(listed, tools)
        self.assertEqual(cat["unavailable_tools"], [])

    def test_no_command_is_served_with_the_list(self):
        self.set_show(True)
        _, _, cat = self.tool_ids()
        for row in cat["tool_list"] + cat["unavailable_tools"]:
            self.assertFalse({"install_command", "login_command", "status_command"} & set(row), row["id"])

    def test_a_new_mcode_card_is_refused_while_the_switch_is_off(self):
        body = {"name": "m-off", "model": {"tool": "mcode", "model_id": ""}, "permission_intents": GOOD,
                "enabled": True, "launch_mode": "full"}
        st, r = self.req("POST", "/api/agent-profiles", body)
        self.assertEqual(st, 400, r)
        self.assertIn("顯示 MCODE", r["error"])
        self.set_show(True)
        st, r = self.req("POST", "/api/agent-profiles", body)
        self.assertEqual(st, 200, r)
        self.assertEqual(r["profile"]["model"]["tool"], "mcode")

    def test_a_card_cannot_be_changed_to_mcode_while_the_switch_is_off_but_one_that_is_mcode_can_be_edited(self):
        pid = self.save_full(tool="claude")
        st, r = self.req("POST", f"/api/agent-profiles/{pid}", {"model": {"tool": "mcode", "model_id": ""}})
        self.assertEqual(st, 400, r)
        self.set_show(True)
        mid = self.save_full(tool="mcode", position="executor")
        self.set_show(False)
        st, r = self.req("POST", f"/api/agent-profiles/{mid}", {"name": "renamed"})
        self.assertEqual(st, 200, r)
        st, r = self.req("POST", f"/api/agent-profiles/{mid}", {"name": "renamed again", "model": {"tool": "mcode", "model_id": "m-2"}})
        self.assertEqual(st, 200, r)
        st, r = self.req("POST", f"/api/agent-profiles/{mid}/duplicate", {})
        self.assertEqual(st, 400, r)

    def test_turning_the_switch_off_deletes_no_card_and_the_card_is_still_listed_and_readable(self):
        self.set_show(True)
        mid = self.save_full(tool="mcode", position="executor")
        self.assertEqual(self.set_show(False)[0], 200)
        st, r = self.req("GET", "/api/agent-profiles")
        self.assertIn(mid, [p["id"] for p in r["profiles"]])
        st, r = self.req("GET", f"/api/agent-profiles/{mid}")
        self.assertEqual((st, r["profile"]["model"]["tool"]), (200, "mcode"))
        self.assertEqual(self.req("GET", f"/api/agent-profiles/{mid}/loadout")[0], 200)
        self.assertEqual(self.req("POST", f"/api/agent-profiles/{mid}/delete", {})[0], 200)

    def test_the_card_that_is_hidden_says_why_in_the_loadout_and_cannot_depart(self):
        self.set_show(True)
        mid = self.save_full(tool="mcode", position="executor")
        self.set_show(False)
        st, ld = self.req("GET", f"/api/agent-profiles/{mid}/loadout")
        self.assertEqual(st, 200, ld)
        self.assertIn("tool_hidden", [b["code"] for b in ld["blockers"]])
        self.assertIn("顯示 MCODE", next(b["message"] for b in ld["blockers"] if b["code"] == "tool_hidden"))
        st, r = self.full_preview(mid)
        self.assertEqual(st, 200, r)
        self.assertFalse(r["preview"]["launchable"])
        self.assertIn("tool_hidden", [x["code"] for x in r["preview"]["reasons"]])
        self.assertIsNone(r["preview"]["preview_id"])
        self.assertEqual(self.sessions(), [])

    def test_a_card_comes_back_to_life_when_the_switch_is_turned_on_again(self):
        self.set_show(True)
        mid = self.save_full(tool="mcode", position="executor")
        self.set_show(False)
        self.set_show(True)
        pv = self.full_preview(mid)[1]["preview"]
        self.assertTrue(pv["launchable"], pv["reasons"])


class GrokAndMcodeLaunchTests(FullApiCase):
    def setUp(self):
        super().setUp()
        self.req("POST", "/api/config", {"show_mcode": True})

    def test_the_stand_ins_are_found_by_their_tool_names(self):
        for tool in ("grok", "mcode"):
            self.assertEqual(os.path.basename(self.found[tool]), tool)

    def test_a_card_of_each_is_saved_with_its_family_and_mode(self):
        for tool, family in (("grok", "xai"), ("mcode", "minimax")):
            with self.subTest(tool=tool):
                pid = self.save_full(tool=tool, position="executor", model={"tool": tool, "model_id": "m-1"})
                p = self.get_profile(pid)
                self.assertEqual((p["model"]["tool"], p["launch_mode"]), (tool, "full"))
                self.assertEqual(agent_profiles.family_of_tool(p["model"]["tool"]), family)

    def test_the_pass_is_launchable_in_full_mode_and_says_the_instructions_are_pasted(self):
        for tool in ("grok", "mcode"):
            with self.subTest(tool=tool):
                pid = self.save_full(tool=tool, position="legal")
                st, r = self.full_preview(pid)
                self.assertEqual(st, 200, r)
                pv = r["preview"]
                self.assertTrue(pv["launchable"], pv["reasons"])
                self.assertEqual(pv["instructions"]["delivery"], "paste")
                self.assertEqual(pv["command"], [self.found[tool]])
                self.assertEqual(pv["cli"]["binary"], self.found[tool])
                self.assertEqual({b["kind"] for b in pv["boundaries"]["items"]}, {"reminder"})

    def test_the_card_departs_in_a_terminal_with_the_model_flag_and_no_instruction_argument(self):
        for tool in ("grok", "mcode"):
            with self.subTest(tool=tool):
                pid = self.save_full(tool=tool, position="art", instructions="這段只能貼上",
                                     model={"tool": tool, "model_id": "m-1"})
                pv = self.full_preview(pid)[1]["preview"]
                self.fresh()
                st, r = self.confirm(pv)
                self.assertEqual(st, 200, r)
                session = r["launch"]["session"]
                self.assertEqual((session["engine"], session["launch_mode"], session["managed"]), (tool, "full", None))
                self.assertEqual(r["launch"]["state"], "full_mode")
                seen = self.seen()
                self.assertEqual(seen["argv"], [self.found[tool], "-m", "m-1"])
                self.assertEqual(seen["cwd"], str(self.work))
                self.assertNotIn("這段只能貼上", " ".join(seen["argv"]))
                self.dm_rpc("close", session_id=session["session_id"])

    def test_the_new_terminal_is_listed_as_that_agent_with_an_unknown_state(self):
        for tool in ("grok", "mcode"):
            with self.subTest(tool=tool):
                pv = self.full_preview(self.save_full(tool=tool, position="executor"))[1]["preview"]
                sid = self.confirm(pv)[1]["launch"]["session"]["session_id"]
                agents = self.console.runtime.list_sessions()["agents"]
                mine = [x for x in agents if x["terminal_id"] == sid]
                self.assertEqual((mine[0]["agent"], mine[0]["agent_status"]), (tool, "unknown"))
                self.assertIn("完整模式", mine[0]["activity"]["reason"])
                self.dm_rpc("close", session_id=sid)

    def test_a_tool_that_is_not_installed_is_said_not_guessed(self):
        for tool in ("grok", "mcode"):
            self.found.pop(tool)
            r = self.full_preview(self.save_full(tool=tool))[1]["preview"]
            self.assertEqual([x["code"] for x in r["reasons"]], ["cli_not_found"])
            self.assertIn(tool, r["reasons"][0]["message"])

    def test_the_safe_mode_of_these_tools_is_refused_and_says_full_mode_only(self):
        for tool in ("grok", "mcode"):
            with self.subTest(tool=tool):
                pid = self.save(position="executor", launch_mode="safe", model={"tool": tool, "model_id": ""})
                st, r = self.preview(pid)
                self.assertEqual(st, 200, r)
                reasons = r["preview"]["reasons"]
                self.assertEqual(reasons[0]["code"], "tool_not_launchable")
                self.assertIn("完整模式", reasons[0]["message"])
                self.assertIsNone(r["preview"]["preview_id"])

    def test_the_card_back_blockers_for_full_mode_are_empty_and_the_armor_is_not_applicable(self):
        for tool in ("grok", "mcode"):
            pid = self.save_full(tool=tool, position="executor")
            st, ld = self.req("GET", f"/api/agent-profiles/{pid}/loadout")
            self.assertEqual(st, 200)
            self.assertEqual(ld["blockers"], [])
            self.assertFalse(ld["armor"]["applicable"])
            self.assertFalse(ld["instructions"]["automatic"])
            self.assertIn("貼上職位指示", ld["instructions"]["where"])

    def test_the_catalog_still_says_which_tools_full_mode_alone_starts(self):
        st, cat = self.req("GET", "/api/agent-builder/catalog")
        full_only = [t["id"] for t in cat["tool_list"] if t["full_launch"] and not t["safe_launch"]]
        self.assertEqual(full_only, ["agy", "grok", "mcode"])
        for t in cat["tool_list"]:
            if t["id"] in full_only:
                self.assertTrue(t["not_launchable_message"])


class StaffingFlagTests(unittest.TestCase):
    def test_the_cards_that_cannot_start_are_counted_by_the_tools_full_mode_alone_starts(self):
        for tool in ("grok", "mcode"):
            self.assertEqual(staffing.can_start({"model": {"tool": tool}, "launch_mode": "full"}), "full")
            self.assertEqual(staffing.can_start({"model": {"tool": tool}, "launch_mode": "safe"}), "no")
            self.assertEqual(staffing.can_start({"model": {"tool": tool}}), "no")


if __name__ == "__main__":
    unittest.main()
