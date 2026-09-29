"""Phase D1 Armory projections are pure, read-only derivations."""
from __future__ import annotations

import unittest

from sidconsole import armory


class ArmoryProjectionTests(unittest.TestCase):
    def setUp(self):
        self.skills = [
            {"skill_id": "available", "name": "Available", "activation": "not_installed"},
            {"skill_id": "installed", "name": "Installed", "activation": "active"},
            {"skill_id": "disabled", "name": "Disabled", "activation": "disabled"},
            {"skill_id": "old", "name": "Old", "activation": "superseded"},
            {"skill_id": "other", "name": "Other", "activation": "archived"},
        ]
        self.profiles = [
            {"id": "p1", "name": "Enabled", "enabled": True,
             "equipped_skill_ids": ["installed", "missing"]},
            {"id": "p2", "name": "Disabled", "enabled": False,
             "equipped_skill_ids": ["installed"]},
        ]

    def test_four_state_mapping_and_sources(self):
        out = armory.project(self.skills, self.profiles,
                             lambda skill_id: [{"evidence": "explicit"}] if skill_id == "installed" else [])
        rows = {row["skill_id"]: row for row in out["skills"]}
        self.assertTrue(rows["available"]["states"]["available"])
        self.assertTrue(rows["installed"]["states"]["installed"])
        self.assertTrue(rows["disabled"]["states"]["installed"])
        self.assertTrue(rows["old"]["states"]["installed"])
        self.assertFalse(rows["other"]["states"]["installed"])
        self.assertEqual([p["id"] for p in rows["installed"]["states"]["equipped"]], ["p1", "p2"])
        self.assertFalse(rows["installed"]["states"]["equipped"][1]["enabled"])
        self.assertTrue(rows["installed"]["states"]["loaded"]["observed"])
        self.assertFalse(rows["available"]["states"]["loaded"]["observed"])
        self.assertEqual(rows["available"]["sources"]["loaded"], "未知：沒有執行觀察證據")
        self.assertEqual(rows["installed"]["sources"]["available"], "不適用：這不是市集未安裝副本")

    def test_unresolved_equipped_reference_is_reported_not_dropped(self):
        out = armory.project(self.skills, self.profiles, lambda _: [])
        self.assertEqual(out["unresolved_equipped"], [{
            "skill_id": "missing",
            "profile": {"id": "p1", "name": "Enabled", "enabled": True},
        }])

    def test_project_has_no_write_callback_or_mutation(self):
        before = repr((self.skills, self.profiles))
        armory.project(self.skills, self.profiles, lambda _: [])
        self.assertEqual(repr((self.skills, self.profiles)), before)


if __name__ == "__main__":
    unittest.main()
