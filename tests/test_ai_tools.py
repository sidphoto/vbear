"""v0.12 task 1: the AI tool list is written once (vbear/ai_tools.py) and every other table is made from it.

Four seams, none of them an internal function:
  * the registry's own public surface (what it lists, and that every entry carries every field);
  * the old constants of the other modules, which must keep their exact values (nothing about behaviour changed);
  * the page: web/app.js repeats a few tables because it has no import, and each must equal the registry;
  * adding a tool: one entry in the registry is enough for every Python table (shown in a fresh interpreter).

Run: python3 -m unittest tests.test_ai_tools -v
"""

from __future__ import annotations

import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if "VBEAR_HOME" not in os.environ:
    _HOME = Path(tempfile.mkdtemp(prefix="vbear-ai-tools-"))
    os.environ["HOME"] = str(_HOME)
    os.environ["VBEAR_HOME"] = str(_HOME / ".vbear")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_launch, agent_profiles, ai_tools, flows, position_guide  # noqa: E402
from vbear.runtime import agent_sessions, native  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIELDS = ("id", "name", "short", "family", "species", "generic", "safe_launch", "full_launch", "model_flag",
          "hidden", "install_command", "login_command", "status_command", "family_enforced", "not_launchable_message")


class RegistryTests(unittest.TestCase):
    def test_the_tools_of_this_build_in_the_order_the_camps_are_offered(self):
        self.assertEqual([t.id for t in ai_tools.REGISTRY], ["claude", "codex", "agy", "shared"])
        self.assertEqual(ai_tools.ids(), ("claude", "codex", "agy", "shared"))

    def test_every_entry_carries_every_field_the_spec_names(self):
        for t in ai_tools.REGISTRY:
            self.assertEqual(tuple(t._fields), FIELDS, t.id)

    def test_names_families_and_species(self):
        by = {t.id: t for t in ai_tools.REGISTRY}
        self.assertEqual({k: v.name for k, v in by.items()},
                         {"claude": "Claude Code", "codex": "Codex CLI", "agy": "Antigravity（AGY）", "shared": "共用（skills CLI）"})
        self.assertEqual({k: v.short for k, v in by.items()},
                         {"claude": "Claude Code", "codex": "Codex", "agy": "AGY", "shared": "共用卡"})
        self.assertEqual({k: v.family for k, v in by.items()},
                         {"claude": "anthropic", "codex": "openai", "agy": "google", "shared": "unknown"})
        self.assertEqual({k: v.species for k, v in by.items()},
                         {"claude": "bear", "codex": "robot", "agy": "fox", "shared": None})

    def test_what_each_tool_can_do_today(self):
        by = {t.id: t for t in ai_tools.REGISTRY}
        self.assertEqual({k for k, v in by.items() if v.safe_launch}, {"claude", "codex"})
        self.assertEqual({k for k, v in by.items() if v.full_launch}, {"claude", "codex", "agy"})
        self.assertEqual({k: v.model_flag for k, v in by.items() if v.full_launch},
                         {"claude": "--model", "codex": "-m", "agy": "--model"})
        self.assertEqual({k for k, v in by.items() if v.generic}, {"shared"})
        self.assertEqual({k for k, v in by.items() if v.family_enforced}, {"agy"})

    def test_no_tool_is_hidden_yet_and_grok_and_mcode_are_not_in_this_batch(self):
        self.assertFalse(any(t.hidden for t in ai_tools.REGISTRY))
        self.assertTrue({"grok", "mcode"}.isdisjoint(ai_tools.ids()))

    def test_the_status_commands_the_spec_names_and_no_install_command_is_invented(self):
        by = {t.id: t for t in ai_tools.REGISTRY}
        self.assertEqual(by["claude"].status_command, ("claude", "auth", "status"))
        self.assertEqual(by["codex"].status_command, ("codex", "login", "status"))
        self.assertIsNone(by["agy"].status_command)
        for t in ai_tools.REGISTRY:
            self.assertEqual((t.install_command, t.login_command), ("", ""), t.id)

    def test_the_view_is_what_the_server_may_serve_and_has_no_command(self):
        view = ai_tools.view()
        self.assertEqual([v["id"] for v in view], list(ai_tools.ids()))
        for v in view:
            self.assertEqual(set(v), {"id", "name", "short", "family", "generic", "safe_launch", "full_launch", "hidden"})
        json.dumps(view)


class OtherModulesKeepTheirValuesTests(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(agent_profiles.TOOL_ORDER, ("claude", "codex", "agy", "shared"))
        self.assertEqual(agent_profiles.KNOWN_TOOLS, frozenset({"claude", "codex", "agy", "shared"}))
        self.assertEqual(agent_profiles.TOOL_FAMILY,
                         {"claude": "anthropic", "codex": "openai", "agy": "google", "shared": "unknown"})

    def test_position_guide_and_flows(self):
        self.assertEqual(position_guide.TOOLS, ("claude", "codex", "agy", "shared"))
        self.assertEqual(flows.SNAPSHOT_TOOLS, ("claude", "codex", "agy", "shared"))
        self.assertEqual(flows.SNAPSHOT_TOOL_FAMILY, agent_profiles.TOOL_FAMILY)
        self.assertEqual(flows.FAMILY_FIXED_TOOLS, ("agy",))

    def test_launch(self):
        self.assertEqual(agent_sessions.FULL_ENGINES, ("claude", "codex", "agy"))
        self.assertEqual(agent_sessions._FULL_MODEL_FLAG, {"claude": "--model", "codex": "-m", "agy": "--model"})
        self.assertEqual(agent_launch.TOOL_NOT_LAUNCHABLE,
                         {"shared": "shared 不是可啟動的工具", "agy": "VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄"})
        self.assertEqual(set(agent_launch.UNLAUNCHABLE_TOOLS), {"agy", "shared"})

    def test_which_agent_a_runtime_session_is(self):
        pick = native._agent_engine
        self.assertEqual(pick({"engine": "claude"}), "claude")
        self.assertEqual(pick({"engine": "codex"}), "codex")
        self.assertEqual(pick({"engine": "claude-stream"}), "claude")
        self.assertEqual(pick({"engine": "agy", "launch_mode": "full"}), "agy")
        self.assertIsNone(pick({"engine": "agy"}))
        self.assertIsNone(pick({"engine": "shared", "launch_mode": "full"}))
        self.assertEqual(pick({"argv": ["/x/codex"]}), "codex")
        self.assertIsNone(pick({"argv": ["/x/agy"]}))


class PageTablesTests(unittest.TestCase):
    """web/app.js has no import, so it repeats some tables; every one must be made of the registry's values."""
    SOURCE = (REPO / "web" / "app.js").read_text(encoding="utf-8")

    def js_object(self, name: str) -> dict:
        m = re.search(r"const %s = \{([^}]*)\};" % re.escape(name), self.SOURCE)
        self.assertIsNotNone(m, name)
        return dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", m.group(1)))

    def js_list(self, name: str) -> list:
        m = re.search(r"const %s = \[([^\]]*)\];" % re.escape(name), self.SOURCE)
        self.assertIsNotNone(m, name)
        return re.findall(r"\"(\w+)\"", m.group(1))

    def test_labels(self):
        want = {t.id: t.name for t in ai_tools.REGISTRY}
        self.assertEqual(self.js_object("CARD_TOOL_LABEL"), want)
        self.assertEqual(list(self.js_object("CARD_TOOL_LABEL")), list(ai_tools.ids()))
        self.assertEqual(self.js_object("CARD_TOOL_SHORT"), {t.id: t.short for t in ai_tools.REGISTRY})

    def test_the_skill_page_names_only_differ_for_the_generic_camp(self):
        got = self.js_object("TOOL")
        self.assertEqual(set(got), set(ai_tools.ids()))
        for t in ai_tools.REGISTRY:
            if not t.generic:
                self.assertEqual(got[t.id], t.name, t.id)
        self.assertEqual(got["shared"], "skills CLI")

    def test_families_species_and_camps(self):
        self.assertEqual(self.js_object("TEAM_TOOL_FAMILY"), {t.id: t.family for t in ai_tools.REGISTRY})
        self.assertEqual(self.js_object("OFFICE_TOOL_SPECIES"), {t.id: t.species for t in ai_tools.REGISTRY if t.species})
        self.assertEqual(self.js_object("OFFICE_TOOL_CAMP"), {t.id: t.family for t in ai_tools.REGISTRY if t.species})

    def test_the_list_the_card_pool_falls_back_to_when_the_server_sends_none(self):
        m = re.search(r"function cardCatalogTools\(catalog\) \{.*?return tools\.length \? tools : \[([^\]]*)\];", self.SOURCE, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r"\"(\w+)\"", m.group(1)), list(ai_tools.ids()))

    def test_the_tools_the_safe_launch_does_not_start(self):
        self.assertEqual(sorted(self.js_list("UNLAUNCHABLE_TOOLS")), sorted(t.id for t in ai_tools.REGISTRY if not t.safe_launch))
        self.assertEqual(sorted(self.js_list("UNLAUNCHABLE_TOOLS")), sorted(agent_launch.UNLAUNCHABLE_TOOLS))


class AddingATool(unittest.TestCase):
    """The proof that one entry is enough: a fresh interpreter adds a made-up tool to the registry before anything
    else is imported and prints what every Python table then holds."""
    PROGRAM = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from vbear import ai_tools
demo = ai_tools.Tool(id="demo", name="Demo CLI", short="Demo", family="acme", species=None, generic=False,
                     safe_launch=False, full_launch=True, model_flag="--model", hidden=False, install_command="",
                     login_command="", status_command=None, family_enforced=True,
                     not_launchable_message="demo says no")
ai_tools.REGISTRY = ai_tools.REGISTRY[:-1] + (demo,) + ai_tools.REGISTRY[-1:]
from vbear import agent_launch, agent_profiles, flows, position_guide
from vbear.runtime import agent_sessions
print(json.dumps({
    "order": agent_profiles.TOOL_ORDER, "known": sorted(agent_profiles.KNOWN_TOOLS),
    "family": agent_profiles.TOOL_FAMILY["demo"], "guide": position_guide.TOOLS,
    "snap": flows.SNAPSHOT_TOOLS, "snap_family": flows.SNAPSHOT_TOOL_FAMILY["demo"], "fixed": flows.FAMILY_FIXED_TOOLS,
    "full": agent_sessions.FULL_ENGINES, "flag": agent_sessions._FULL_MODEL_FLAG["demo"],
    "not_launchable": agent_launch.TOOL_NOT_LAUNCHABLE, "unlaunchable": agent_launch.UNLAUNCHABLE_TOOLS,
    "view": [v["id"] for v in ai_tools.view()],
}))
"""

    def test_one_entry_reaches_every_table(self):
        with tempfile.TemporaryDirectory(prefix="vbear-ai-demo-") as tmp:
            env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "VBEAR_HOME": str(Path(tmp) / ".vbear"),
                   "VBEAR_RUNTIME_AUTOSTART": "0"}
            run = subprocess.run([sys.executable, "-I", "-c", self.PROGRAM, str(REPO)], env=env, cwd=tmp, capture_output=True,
                                 text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout)
        self.assertEqual(got["order"], ["claude", "codex", "agy", "demo", "shared"])
        self.assertIn("demo", got["known"])
        self.assertEqual(got["family"], "acme")
        self.assertEqual(got["guide"], ["claude", "codex", "agy", "demo", "shared"])
        self.assertEqual(got["snap"], ["claude", "codex", "agy", "demo", "shared"])
        self.assertEqual(got["snap_family"], "acme")
        self.assertEqual(got["fixed"], ["agy", "demo"])
        self.assertEqual(got["full"], ["claude", "codex", "agy", "demo"])
        self.assertEqual(got["flag"], "--model")
        self.assertEqual(got["not_launchable"]["demo"], "demo says no")
        self.assertIn("demo", got["unlaunchable"])
        self.assertEqual(got["view"], ["claude", "codex", "agy", "demo", "shared"])


if __name__ == "__main__":
    unittest.main()
