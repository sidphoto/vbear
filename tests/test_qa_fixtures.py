"""The QA console's own fixtures (tests/qa_game_ui.py): the fake translation CLI follows the real translation
path, and the empty / fresh-user scenarios are really empty. No real model or CLI is called."""
from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

from tests import qa_game_ui as qa
from vbear import flows, headless_cli, tasks, translations


class _Qa(qa._Env):
    ENV: dict = {}

    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ, self.ENV)
        patch.start()
        self.addCleanup(patch.stop)
        self.build()

    def wait_job(self):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            view = self.api("/api/translations")
            if view["job"]["status"] not in ("running", "cancelling"):
                return view
            time.sleep(0.05)
        self.fail("the fake translation did not finish")


class FakeTranslationTests(_Qa):
    ENV = {"VBEAR_QA_TRANSLATE": "1"}

    def test_translate_a_skill_with_the_claude_engine(self):
        self.assertEqual(self.api("/api/translations")["engine"], "claude")
        skill_id = self.skill_ids["spare-skill"]
        self.assertEqual(self.call(f"/api/skills/{skill_id}/translate", "POST", {})[0], 202)
        view = self.wait_job()
        self.assertEqual(view["job"]["status"], "completed", view["job"])
        self.assertEqual(view["job"]["failed"], 0)
        entry = view["entries"][skill_id]["entry"]
        self.assertEqual(entry["engine"], "claude")
        self.assertEqual(entry["cli_version"], "2.1.296")
        self.assertTrue(entry["description_zh"].startswith("QA 假 CLI 中文說明："))

    def test_verify_succeeds_and_never_looks_for_the_real_claude(self):
        with mock.patch.object(translations.shutil, "which", side_effect=AssertionError("the real claude")), \
             mock.patch.object(headless_cli.subprocess, "Popen", wraps=headless_cli.subprocess.Popen) as popen:  # the one place a translation starts a program
            status, result = self.call("/api/translations/verify", "POST", {})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["version"], "2.1.296")
        self.assertGreater(result["passed_at"], 0)
        argv = popen.call_args.args[0]
        self.assertEqual(os.path.basename(argv[0]), "qa-translation-cli")
        self.assertTrue(str(argv[0]).startswith(str(self.tmp)))
        self.assertIn("2.1.296", translations.BoundaryStore().load())


class EmptyLobbyTests(_Qa):
    ENV = {"VBEAR_QA_LOBBY": "empty"}

    def test_no_session_no_flow_nothing_waiting(self):
        live = self.api("/api/live?force=1")
        self.assertEqual(live["sessions"], [])
        self.assertEqual(live["attention"], [])
        self.assertEqual(self.api("/api/flows")["flows"], [])
        self.assertEqual(flows.list_flows(), [])

    def test_the_role_cards_stay(self):
        ids = {p["id"] for p in self.api("/api/agent-profiles")["profiles"]}
        self.assertEqual(ids, {qa.CLAUDE_PROFILE, qa.CODEX_PROFILE})


class FreshUserTests(_Qa):
    ENV = {"VBEAR_QA_FRESH": "1"}

    def test_nothing_of_the_demo_is_left(self):
        self.assertEqual(self.api("/api/agent-profiles")["profiles"], [])
        self.assertEqual(tasks.list_tasks(), [])
        self.assertEqual(self.api("/api/flows")["flows"], [])
        live = self.api("/api/live?force=1")
        self.assertEqual((live["sessions"], live["attention"]), ([], []))

    def test_the_skills_stay_so_there_is_something_to_equip(self):
        self.assertIn("code-review", self.skill_ids)

    def test_the_html_probe_skill_is_for_security_checks_not_for_a_new_user(self):
        self.assertFalse((self.home / ".claude" / "skills" / "html-probe").exists())
        self.assertNotIn(qa.PROBE, self.skill_ids)
        self.assertNotIn(qa.PROBE, json.dumps(self.api("/api/skills")))


class DefaultEnvironmentKeepsTheProbeTests(_Qa):
    ENV = {"VBEAR_QA_LOBBY": "empty"}

    def test_the_probe_skill_is_there_outside_the_fresh_scenario(self):
        self.assertTrue((self.home / ".claude" / "skills" / "html-probe" / "SKILL.md").is_file())
        self.assertIn(qa.PROBE, json.dumps(self.api("/api/skills")))


class FreshWithOtherFlagsTests(_Qa):
    ENV = {"VBEAR_QA_FRESH": "1", "VBEAR_QA_LOBBY": "1", "VBEAR_QA_OFFICE": "1", "VBEAR_QA_TRANSLATE": "1"}

    def test_fresh_wins_over_the_lobby_and_office_scenarios_and_keeps_translation(self):
        self.assertEqual(self.api("/api/agent-profiles")["profiles"], [])
        self.assertEqual(tasks.list_tasks(), [])
        self.assertEqual(self.api("/api/flows")["flows"], [])
        live = self.api("/api/live?force=1")
        self.assertEqual(live["sessions"], [])
        self.assertEqual(self.api("/api/translations")["provider"], "fake")
        self.assertEqual(self.call("/api/translations/verify", "POST", {})[0], 200)


if __name__ == "__main__":
    unittest.main()
