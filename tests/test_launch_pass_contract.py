"""The launch pass (design card-play 3.7, R2) words each line by the level the preview gives it. The level words are
copied into web/app.js; this test makes a change on either side fail here instead of a line saying more than the
level does. It also keeps the pass's name the same on the server and in the page."""

from __future__ import annotations

import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vbear import agent_launch, loadout  # noqa: E402

APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
ALL_LEVELS = (agent_launch.ENFORCED, agent_launch.PARTIAL, agent_launch.UNVERIFIED, agent_launch.UNKNOWN,
              agent_launch.INTENT, agent_launch.UNRESTRICTED, agent_launch.NOT_GRANTED)


def _kind_table() -> dict:
    block = re.search(r"const PASS_LEVEL_KIND = \{(.*?)\n\};", APP, re.S)
    assert block, "PASS_LEVEL_KIND is not in web/app.js"
    return dict(re.findall(r'"([^"]+)":\s*"([a-z]+)"', block.group(1)))


class PassLevelTableTests(unittest.TestCase):
    def test_every_level_constant_has_a_row_and_nothing_else_does(self):
        self.assertEqual(set(_kind_table()), set(ALL_LEVELS))

    def test_only_the_enforced_level_is_worded_as_enforced(self):
        table = _kind_table()
        self.assertEqual([lv for lv, kind in table.items() if kind == "enforced"], [agent_launch.ENFORCED])
        self.assertEqual(table[agent_launch.PARTIAL], "partial")
        self.assertEqual(table[agent_launch.UNVERIFIED], "unverified")
        # the levels that mean "not blocked" are never worded as a block, and a level with no write or network
        # meaning (not granted) reads as unknown
        self.assertEqual(table[agent_launch.INTENT], "open")
        self.assertEqual(table[agent_launch.UNRESTRICTED], "open")
        self.assertEqual(table[agent_launch.UNKNOWN], "unknown")
        self.assertEqual(table[agent_launch.NOT_GRANTED], "unknown")

    def test_the_levels_the_armor_can_hold_are_all_in_the_table(self):
        held = {lv for g in agent_launch.armor_groups("claude") for lv in g["levels"]}
        self.assertEqual(held, set(_kind_table()))


class PassWordsTests(unittest.TestCase):
    def test_a_launch_reason_names_the_role_card_not_a_profile(self):
        for intents in ({"read": "allow", "write": "deny", "test": "allow", "deploy": "deny"},
                        {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"}):
            profile = {"enabled": False, "model": {"tool": "claude"}, "permission_intents": intents}
            reasons = agent_launch.launch_blockers(profile, True, {"enabled": False, "approved_domains": []})
            self.assertTrue(reasons)
            for r in reasons:
                self.assertNotIn("Profile", r["message"], r["code"])
        self.assertIn("角色卡", agent_launch.launch_blockers(
            {"enabled": False, "model": {"tool": "claude"}, "permission_intents": {}}, True,
            {"enabled": False, "approved_domains": []})[0]["message"])

    def test_an_undecided_intent_is_named_in_the_screen_words_not_the_api_key(self):
        self.assertEqual(agent_launch.INTENT_LABELS, {"read": "讀取檔案", "write": "編輯寫入", "test": "執行測試", "deploy": "部署上線"})
        for key, word in agent_launch.INTENT_LABELS.items():
            intents = dict(agent_launch.VERIFIED_INTENTS, **{key: "unspecified"})
            profile = {"enabled": True, "model": {"tool": "claude"}, "permission_intents": intents}
            reasons = [r for r in agent_launch.launch_blockers(profile, True, {"enabled": False, "approved_domains": []})
                       if r["code"] == "intent_unspecified"]
            self.assertEqual(len(reasons), 1, key)
            self.assertIn(word, reasons[0]["message"])
            self.assertNotIn(key, reasons[0]["message"])
            self.assertNotIn("安全", reasons[0]["message"])

    def test_the_commit_reason_quotes_the_sentence_the_page_asks_you_to_tick(self):
        reasons = agent_launch.launch_blockers(
            {"enabled": True, "model": {"tool": "claude"}, "permission_intents": dict(agent_launch.VERIFIED_INTENTS)},
            False, {"enabled": False, "approved_domains": []})
        message = next(r["message"] for r in reasons if r["code"] == "commit_not_enforceable")
        sentence = re.search(r'const PASS_COMMIT_ACK = "([^"]+)"', APP).group(1)
        self.assertIn(sentence.rstrip("。"), message)
        self.assertTrue(message.startswith("目前無法強制不 commit"))

    def test_the_pass_has_one_name_on_the_server_and_in_the_page(self):
        self.assertNotIn("出發前檢查", APP)
        self.assertNotIn("出發前檢查", (ROOT / "vbear" / "loadout.py").read_text(encoding="utf-8"))
        self.assertIn("出發通行證", loadout.VERSION_BASIS)
        self.assertIn("出發通行證", loadout.CODEX_BASIS)


if __name__ == "__main__":
    unittest.main()
