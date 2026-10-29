"""P34-2: a position's instructions, its boundaries by tool and launch mode, the recommended skill categories, the
card's `instructions` and `launch_mode` fields, the launch pass's words, and the two new skill categories.

The guide (vbear/position_guide.py) is the one place the words live. Three kinds of boundary are told apart, and the
test below that matters most is the contract: every boundary that says "VBear enforces this if it launches the card"
must point at an item of agent_launch.armor_items whose level is enforced or partial, so the screens never draw a
shield VBear has not earned.

Run: python3 -m unittest tests.test_p34_instructions -v
"""

from __future__ import annotations

import hashlib
import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-p34-2-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_launch, agent_profiles, categories, index as index_mod, loadout, position_guide  # noqa: E402
from vbear.config import state_dir  # noqa: E402
from tests.test_p34_positions import PRIVATE_WORD_HASHES  # noqa: E402

IDS = ["planner", "executor", "social", "art", "pm", "legal", "accountant", "reviewer"]
KINDS = {"enforced_if_launched", "reminder", "not_possible"}


def _fresh_state():
    sd = state_dir()
    if sd.exists():
        shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)


def _body(**kw):
    base = {"name": "Card", "model": {"tool": "claude", "model_id": ""}, "equipped_skill_ids": [],
            "permission_intents": dict(agent_profiles.VERIFIED_INTENTS)}
    base.update(kw)
    return base


class GuideTableTests(unittest.TestCase):
    def test_one_guide_row_per_position_and_nothing_else(self):
        self.assertEqual(list(position_guide.GUIDE), IDS)

    def test_each_row_has_its_prompt_boundaries_categories_and_folder(self):
        for pid, row in position_guide.GUIDE.items():
            self.assertEqual(sorted(row), ["boundaries", "prompt", "skill_categories", "suggested_folder"], pid)
            self.assertTrue(row["prompt"].strip(), pid)
            self.assertLessEqual(len(row["prompt"]), position_guide.MAX_INSTRUCTIONS, pid)
            self.assertTrue(row["boundaries"], pid)
            self.assertTrue(row["suggested_folder"] is None or row["suggested_folder"].strip(), pid)

    def test_a_default_prompt_is_text_a_card_could_store(self):
        # a default is what the wizard offers to edit and the terminal pastes: it must pass the field's own rules
        for pid, row in position_guide.GUIDE.items():
            self.assertEqual(agent_profiles.clean_instructions(row["prompt"]), row["prompt"], pid)
            self.assertNotRegex(row["prompt"], r"^-", pid)

    def test_recommended_categories_exist_in_the_skill_categories(self):
        known = {c["id"] for c in categories.CATEGORIES}
        for pid, row in position_guide.GUIDE.items():
            self.assertTrue(set(row["skill_categories"]) <= known, pid)
        self.assertEqual(position_guide.GUIDE["legal"]["skill_categories"], ["security", "legal"])
        self.assertEqual(position_guide.GUIDE["accountant"]["skill_categories"], ["documents", "finance"])
        self.assertEqual(position_guide.GUIDE["executor"]["skill_categories"],
                         ["frontend", "backend", "quality", "security"])

    def test_the_suggested_folders(self):
        folders = {pid: row["suggested_folder"] for pid, row in position_guide.GUIDE.items()}
        self.assertEqual(folders, {"planner": None, "executor": None, "social": "社群草稿", "art": "素材", "pm": None,
                                   "legal": "法務報告", "accountant": "帳務報告", "reviewer": None})

    def test_every_boundary_has_an_id_a_text_and_a_known_kind(self):
        for pid, row in position_guide.GUIDE.items():
            ids = [b["id"] for b in row["boundaries"]] + [b["id"] for b in position_guide.COMMON_BOUNDARIES]
            self.assertEqual(len(ids), len(set(ids)), pid)
            for b in row["boundaries"] + list(position_guide.COMMON_BOUNDARIES):
                self.assertIn(b["kind"], KINDS, (pid, b["id"]))
                self.assertTrue(b["text"].strip(), (pid, b["id"]))
                self.assertEqual(("armor" in b), b["kind"] == "enforced_if_launched", (pid, b["id"]))

    def test_no_private_name_is_in_the_words(self):
        for pid, row in position_guide.GUIDE.items():
            blob = row["prompt"] + " ".join(b["text"] + b.get("full_text", "") for b in row["boundaries"])
            for w in re.findall(r"[A-Za-z]+", blob):
                self.assertNotIn(hashlib.sha256(w.lower().encode()).hexdigest()[:16], PRIVATE_WORD_HASHES, pid)

    def test_the_prompts_do_not_promise_what_vbear_cannot_do(self):
        for pid, row in position_guide.GUIDE.items():
            self.assertNotRegex(row["prompt"], r"(VBear 會|VBear 已|強制)", pid)


class BoundaryContractTests(unittest.TestCase):
    """Every boundary that claims enforcement is backed by an armor item of the verified Claude Code launch."""

    def all_boundaries(self):
        for pid, row in position_guide.GUIDE.items():
            for b in row["boundaries"]:
                yield pid, b
        for b in position_guide.COMMON_BOUNDARIES:
            yield "common", b

    def test_an_enforced_boundary_names_an_armor_item_that_is_enforced_or_partial(self):
        items = agent_launch.armor_items("claude", True, agent_launch.NETWORK_VERIFIED, False)
        n = 0
        for pid, b in self.all_boundaries():
            if b["kind"] != "enforced_if_launched":
                continue
            n += 1
            self.assertIn(b["armor"], items, (pid, b["id"]))
            self.assertIn(items[b["armor"]]["level"], (agent_launch.ENFORCED, agent_launch.PARTIAL), (pid, b["id"]))
        self.assertGreaterEqual(n, 4)

    def test_what_the_armor_does_not_stop_is_never_told_as_enforced(self):
        # read, commit, deploy and the bang command are intent or unrestricted in the armor
        items = agent_launch.armor_items("claude", True, agent_launch.NETWORK_VERIFIED, False)
        for pid, b in self.all_boundaries():
            if b["kind"] == "enforced_if_launched":
                self.assertNotIn(items[b["armor"]]["level"],
                                 (agent_launch.INTENT, agent_launch.UNRESTRICTED, agent_launch.NOT_GRANTED), b["id"])
        common = {b["id"]: b for b in position_guide.COMMON_BOUNDARIES}
        for bid in ("read", "commit", "bang"):
            self.assertEqual(common[bid]["kind"], "not_possible", bid)

    def test_without_a_verified_version_nothing_would_stay_enforced(self):
        # the contract is stated for the verified version; an unverified one has no enforced level at all
        items = agent_launch.armor_items("claude", False, agent_launch.NETWORK_VERIFIED, False)
        for name in {b["armor"] for _, b in self.all_boundaries() if b["kind"] == "enforced_if_launched"}:
            self.assertNotIn(items[name]["level"], (agent_launch.ENFORCED,), name)


class ResolveBoundaryTests(unittest.TestCase):
    def kinds(self, pid, tool, mode):
        return {b["id"]: b["kind"] for b in position_guide.resolve(pid, tool, mode)["items"]}

    def test_claude_safe_keeps_each_kind_as_the_table_says(self):
        for pid in IDS:
            got = self.kinds(pid, "claude", "safe")
            want = {b["id"]: b["kind"] for b in list(position_guide.COMMON_BOUNDARIES) + position_guide.GUIDE[pid]["boundaries"]}
            self.assertEqual(got, want, pid)
        self.assertEqual(self.kinds("social", "claude", "safe")["network"], "enforced_if_launched")

    def test_full_mode_makes_everything_a_reminder_and_no_text_claims_a_block(self):
        for pid in IDS:
            for tool in ("claude", "codex", "agy", "shared"):
                r = position_guide.resolve(pid, tool, "full")
                self.assertEqual({b["kind"] for b in r["items"]}, {"reminder"}, (pid, tool))
                self.assertTrue(all("armor" not in b for b in r["items"]))
                self.assertIn("沒有限制", r["mode_note"])
                for b in r["items"]:
                    # the safe-mode words ("連不上網路", "被擋") must not survive into full mode
                    self.assertNotRegex(b["text"], r"(連不上網路|被擋|擋得住|沒有網路|限在)", (pid, tool, b["id"]))

    def test_every_boundary_that_speaks_of_vbear_blocking_has_its_full_mode_words(self):
        for pid in IDS:
            for b in position_guide.GUIDE[pid]["boundaries"] + list(position_guide.COMMON_BOUNDARIES):
                if b["kind"] != "reminder":
                    self.assertTrue(b.get("full_text", "").strip(), (pid, b["id"]))

    def test_codex_agy_and_shared_in_safe_mode_have_nothing_enforced(self):
        for pid in IDS:
            for tool in ("codex", "agy", "shared"):
                r = position_guide.resolve(pid, tool, "safe")
                kinds = {b["kind"] for b in r["items"]}
                self.assertFalse(kinds & {"enforced_if_launched", "not_possible"}, (pid, tool))
                self.assertIn("not_applicable", kinds, (pid, tool))
                self.assertIn("不幫這張卡出發", r["mode_note"])
                # a reminder stays a reminder: the words are for the AI, whoever runs it
                reminders = {b["id"] for b in position_guide.GUIDE[pid]["boundaries"] if b["kind"] == "reminder"}
                self.assertTrue(reminders <= {b["id"] for b in r["items"] if b["kind"] == "reminder"}, (pid, tool))

    def test_an_unknown_mode_is_safe_and_an_unknown_position_has_no_boundaries(self):
        self.assertEqual(position_guide.resolve("planner", "claude", "bogus")["launch_mode"], "safe")
        self.assertEqual(position_guide.resolve("planner", "claude", None)["launch_mode"], "safe")
        self.assertIsNone(position_guide.resolve("nobody", "claude", "safe"))
        self.assertIsNone(position_guide.resolve(None, "claude", "safe"))

    def test_the_views_cover_every_position_tool_and_mode(self):
        v = position_guide.views()
        self.assertEqual(list(v), IDS)
        for pid in IDS:
            self.assertEqual(sorted(v[pid]), ["agy", "claude", "codex", "shared"])
            for tool in v[pid]:
                self.assertEqual(sorted(v[pid][tool]), ["full", "safe"])
        self.assertEqual(v["legal"]["claude"]["safe"], position_guide.resolve("legal", "claude", "safe"))
        json.dumps(v)   # servable


class InstructionsFieldTests(unittest.TestCase):
    def setUp(self):
        _fresh_state()

    def save(self, pid=None, **kw):
        return agent_profiles.save_profile(pid, _body(**kw))

    def test_a_card_without_instructions_has_no_key_and_keeps_its_digest(self):
        saved = self.save(position="executor")
        self.assertNotIn("instructions", saved)
        self.assertNotIn("launch_mode", saved)
        # the digest of a stored card without the new keys is exactly what it was
        stable = {k: v for k, v in saved.items() if not k.startswith("_")}
        blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(agent_profiles.profile_digest(saved), hashlib.sha256(blob.encode()).hexdigest())
        self.assertEqual(set(stable), {"id", "name", "profession_role_id", "model", "equipped_skill_ids",
                                       "permission_intents", "enabled", "created_at", "updated_at", "position"})

    def test_instructions_are_saved_trimmed_and_listed(self):
        saved = self.save(instructions="  先問清楚再動手。\n再跑測試。  ")
        self.assertEqual(saved["instructions"], "先問清楚再動手。\n再跑測試。")
        self.assertEqual(agent_profiles.get_profile(saved["id"])["instructions"], "先問清楚再動手。\n再跑測試。")

    def test_a_missing_key_keeps_null_and_empty_clear(self):
        saved = self.save(instructions="自訂")
        kept = self.save(saved["id"], name="Renamed")
        self.assertEqual(kept["instructions"], "自訂")
        cleared = self.save(saved["id"], instructions=None)
        self.assertNotIn("instructions", cleared)
        again = self.save(saved["id"], instructions="自訂")
        self.assertEqual(self.save(saved["id"], instructions="")["name"], "Card")
        self.assertNotIn("instructions", agent_profiles.get_profile(again["id"]))

    def test_the_length_limit_is_2000_characters(self):
        self.assertEqual(agent_profiles.MAX_INSTRUCTIONS, 2000)
        ok = self.save(instructions="字" * 2000)
        self.assertEqual(len(ok["instructions"]), 2000)
        with self.assertRaises(ValueError) as cm:
            self.save(instructions="字" * 2001)
        self.assertIn("2000", str(cm.exception))

    def test_control_characters_are_refused_but_newline_and_tab_are_text(self):
        for bad in ("a\x00b", "a\x1bb", "a\x07b", "a\x7fb", "a b", "a\u0085b"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.save(instructions=bad)
        saved = self.save(instructions="第一行\r\n第二行\t縮排")
        self.assertEqual(saved["instructions"], "第一行\n第二行\t縮排")

    def test_only_text_is_accepted(self):
        for bad in (5, True, ["x"], {"a": 1}, 1.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.save(instructions=bad)

    def test_a_blank_text_is_the_same_as_clearing(self):
        saved = self.save(instructions="x")
        self.assertNotIn("instructions", self.save(saved["id"], instructions="  \n \t "))

    def test_disabling_and_enabling_leave_the_instructions_and_the_mode_alone(self):
        saved = self.save(instructions="自訂", launch_mode="full", position="legal")
        off = agent_profiles.save_profile(saved["id"], {"enabled": False})
        on = agent_profiles.save_profile(saved["id"], {"enabled": True})
        for card in (off, on):
            self.assertEqual((card["instructions"], card["launch_mode"], card["position"]), ("自訂", "full", "legal"))
        self.assertTrue(on["enabled"])

    def test_a_copy_carries_the_instructions_and_the_mode_as_stored(self):
        src = self.save(instructions="自訂", launch_mode="safe")
        dup = agent_profiles.duplicate_profile(src["id"])
        self.assertEqual((dup["instructions"], dup["launch_mode"]), ("自訂", "safe"))
        plain = agent_profiles.duplicate_profile(self.save()["id"])
        self.assertNotIn("instructions", plain)
        self.assertNotIn("launch_mode", plain)

    def test_a_stored_value_this_build_could_not_write_does_not_isolate_the_file(self):
        saved = self.save()
        path = state_dir() / "agent_profiles.json"
        data = json.loads(path.read_text())
        data[saved["id"]]["instructions"] = "x" * 5000
        data[saved["id"]]["launch_mode"] = "turbo"
        path.write_text(json.dumps(data))
        os.chmod(path, 0o600)
        card = agent_profiles.get_profile(saved["id"])
        self.assertEqual(len(card["instructions"]), 5000)
        self.assertEqual(agent_profiles.effective_launch_mode(card), "safe")   # anything but "full" reads as safe

    def test_a_non_text_stored_value_is_a_damaged_file(self):
        saved = self.save()
        path = state_dir() / "agent_profiles.json"
        data = json.loads(path.read_text())
        data[saved["id"]]["instructions"] = 7
        path.write_text(json.dumps(data))
        os.chmod(path, 0o600)
        with self.assertRaises(agent_profiles.AgentProfileStorageError):
            agent_profiles.get_profile(saved["id"])


class EffectiveInstructionsTests(unittest.TestCase):
    def test_no_key_means_the_position_default(self):
        got = agent_profiles.instructions_of({"position": "legal"})
        self.assertEqual((got["source"], got["position"]), ("default", "legal"))
        self.assertEqual(got["text"], position_guide.GUIDE["legal"]["prompt"])

    def test_a_key_is_the_cards_own_text(self):
        got = agent_profiles.instructions_of({"position": "legal", "instructions": "自己的"})
        self.assertEqual((got["source"], got["text"]), ("custom", "自己的"))
        self.assertEqual(got["default"], position_guide.GUIDE["legal"]["prompt"])

    def test_a_card_with_no_position_and_no_text_has_none(self):
        got = agent_profiles.instructions_of({})
        self.assertEqual((got["source"], got["text"], got["position"]), ("none", None, None))

    def test_a_retired_position_reads_as_the_one_it_became_and_one_with_no_successor_as_none(self):
        self.assertEqual(agent_profiles.position_of({"position": "qa"}), "reviewer")
        self.assertEqual(agent_profiles.position_of({"position": "design"}), "art")
        self.assertIsNone(agent_profiles.position_of({"position": "research"}))
        self.assertIsNone(agent_profiles.position_of({"position": "from-the-future"}))
        self.assertEqual(agent_profiles.position_of({"position": "pm"}), "pm")
        self.assertEqual(agent_profiles.instructions_of({"position": "research"})["source"], "none")

    def test_only_a_stored_text_longer_than_nothing_is_custom(self):
        self.assertEqual(agent_profiles.instructions_of({"position": "pm", "instructions": "  "})["source"], "default")


class LaunchModeFieldTests(unittest.TestCase):
    def setUp(self):
        _fresh_state()

    def test_the_two_modes_and_the_default_a_new_card_is_offered(self):
        self.assertEqual(agent_profiles.LAUNCH_MODES, ("full", "safe"))
        self.assertEqual(agent_profiles.DEFAULT_LAUNCH_MODE_FOR_NEW, "full")

    def test_a_card_without_the_key_is_safe_and_is_not_rewritten(self):
        saved = agent_profiles.save_profile(None, _body())
        self.assertNotIn("launch_mode", saved)
        self.assertEqual(agent_profiles.effective_launch_mode(saved), "safe")
        again = agent_profiles.save_profile(saved["id"], {"name": "Other"})
        self.assertNotIn("launch_mode", again)

    def test_a_value_outside_the_two_is_refused(self):
        for bad in ("turbo", "FULL", 1, True, ["full"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                agent_profiles.save_profile(None, _body(launch_mode=bad))

    def test_saved_kept_and_cleared_like_the_position(self):
        saved = agent_profiles.save_profile(None, _body(launch_mode="full"))
        self.assertEqual(saved["launch_mode"], "full")
        self.assertEqual(agent_profiles.save_profile(saved["id"], {"name": "N"})["launch_mode"], "full")
        self.assertEqual(agent_profiles.save_profile(saved["id"], {"launch_mode": "safe"})["launch_mode"], "safe")
        self.assertNotIn("launch_mode", agent_profiles.save_profile(saved["id"], {"launch_mode": None}))

    def test_only_the_word_full_reads_as_full(self):
        for card, want in (({}, "safe"), ({"launch_mode": "full"}, "full"), ({"launch_mode": "safe"}, "safe"),
                           ({"launch_mode": "Full"}, "safe"), ({"launch_mode": None}, "safe"), ({"launch_mode": 1}, "safe")):
            self.assertEqual(agent_profiles.effective_launch_mode(card), want, card)


class FullModeLaunchTests(unittest.TestCase):
    """Full-mode launching is the next batch. Until it exists a full-mode card is not launched in safe mode behind
    the person's back: the pass says it cannot go, and why."""

    NET = {"enabled": False, "approved_domains": []}

    def card(self, **kw):
        return {"id": "prof-x", "name": "x", "enabled": True, "model": {"tool": "claude", "model_id": ""},
                "permission_intents": dict(agent_profiles.VERIFIED_INTENTS), **kw}

    def test_a_safe_card_is_unchanged(self):
        self.assertEqual(agent_launch.launch_blockers(self.card(), True, self.NET), [])
        self.assertEqual(agent_launch.launch_blockers(self.card(launch_mode="safe"), True, self.NET), [])

    def test_a_full_card_is_not_held_to_the_rules_of_the_safe_launch(self):
        # intents, the commit sentence and the network input belong to the safe launch; a full one applies none of them
        self.assertIs(agent_launch.FULL_MODE_LAUNCHABLE, True)
        self.assertEqual(agent_launch.launch_blockers(self.card(launch_mode="full"), True, self.NET), [])
        odd = {"read": "deny", "write": "deny", "test": "unspecified", "deploy": "allow"}
        self.assertEqual(agent_launch.launch_blockers(self.card(launch_mode="full", permission_intents=odd), False, None), [])
        for tool in ("claude", "codex", "agy"):
            card = self.card(launch_mode="full", model={"tool": tool, "model_id": ""})
            self.assertEqual(agent_launch.launch_blockers(card, False, None), [], tool)

    def test_a_full_card_is_still_stopped_by_a_tool_that_is_not_started_and_by_being_off(self):
        out = agent_launch.launch_blockers(self.card(launch_mode="full", model={"tool": "shared", "model_id": ""}), True, self.NET)
        self.assertEqual([b["code"] for b in out], ["tool_not_launchable"])

    def test_a_disabled_full_card_says_so(self):
        out = agent_launch.launch_blockers(self.card(launch_mode="full", enabled=False), True, self.NET)
        self.assertEqual([b["code"] for b in out], ["profile_disabled"])

    def test_the_wizards_combination_check_is_not_affected(self):
        self.assertEqual(agent_launch.intent_blockers(dict(agent_profiles.VERIFIED_INTENTS)), [])

    def test_the_mode_and_a_stale_unknown_value(self):
        # a value that is not exactly "full" is the safe launch, as before
        self.assertEqual(agent_launch.launch_blockers(self.card(launch_mode="turbo"), True, self.NET), [])


class FolderAdviceTests(unittest.TestCase):
    def test_no_advice_for_a_position_without_a_suggested_folder(self):
        self.assertIsNone(agent_launch.folder_advice("executor", "safe", "/tmp/a/b"))
        self.assertIsNone(agent_launch.folder_advice(None, "safe", "/tmp/a/b"))

    def test_the_folder_itself_or_one_inside_it_is_quiet(self):
        self.assertIsNone(agent_launch.folder_advice("art", "safe", "/home/u/素材"))
        self.assertIsNone(agent_launch.folder_advice("art", "safe", "/home/u/素材/banner/v1"))

    def test_another_folder_gets_a_warning_that_names_both(self):
        text = agent_launch.folder_advice("art", "safe", "/home/u/projects/demo")
        self.assertIn("素材", text)
        self.assertIn("demo", text)
        self.assertIn("只是提醒", text)
        self.assertNotIn("/home/u", text, "the path stays out; only the folder's name is quoted")

    def test_the_warning_for_a_parent_folder_says_the_write_range_is_wider(self):
        text = agent_launch.folder_advice("legal", "safe", "/home/u/projects")
        self.assertIn("法務報告", text)
        self.assertIn("寫入", text)

    def test_full_mode_words_do_not_claim_the_write_range(self):
        text = agent_launch.folder_advice("social", "full", "/home/u/projects/demo")
        self.assertIn("社群草稿", text)
        self.assertIn("不限制", text)

    def test_the_names_are_compared_as_text_not_as_bytes(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "社群草稿")
        self.assertIsNone(agent_launch.folder_advice("social", "safe", f"/home/u/{nfd}"))


class LoadoutSectionsTests(unittest.TestCase):
    def profile(self, **kw):
        return {"id": "prof-a", "name": "A", "enabled": True, "model": {"tool": "claude", "model_id": ""},
                "equipped_skill_ids": [], "permission_intents": dict(agent_profiles.VERIFIED_INTENTS), **kw}

    def build(self, **kw):
        return loadout.build(self.profile(**kw), None, None, None)

    def test_a_card_without_a_mode_reads_as_safe_and_says_it_is_an_old_card(self):
        d = self.build()
        self.assertEqual(d["launch_mode"]["mode"], "safe")
        self.assertFalse(d["launch_mode"]["stored"])
        self.assertIn("沒有設定", d["launch_mode"]["text"])

    def test_the_instructions_section_says_where_they_go_and_that_nothing_goes_by_itself(self):
        d = self.build(position="legal")
        ins = d["instructions"]
        self.assertEqual((ins["source"], ins["position"]), ("default", "legal"))
        self.assertEqual(ins["text"], position_guide.GUIDE["legal"]["prompt"])
        self.assertEqual(ins["title"], "這份指示會交到哪裡")
        self.assertIs(ins["automatic"], False)
        self.assertIn("貼上職位指示", ins["where"])
        self.assertIn("Enter", ins["where"])
        self.assertIn("不會自動", ins["where"])

    def test_a_custom_text_is_marked_custom(self):
        d = self.build(position="legal", instructions="自己寫的")
        self.assertEqual((d["instructions"]["source"], d["instructions"]["text"]), ("custom", "自己寫的"))

    def test_a_card_with_neither_says_so(self):
        d = self.build()
        self.assertEqual(d["instructions"]["source"], "none")
        self.assertIsNone(d["instructions"]["text"])

    def test_boundaries_follow_the_cards_tool_and_mode(self):
        safe = self.build(position="social")["boundaries"]
        self.assertEqual((safe["launch_mode"], safe["tool"]), ("safe", "claude"))
        self.assertIn("enforced_if_launched", {b["kind"] for b in safe["items"]})
        full = self.build(position="social", launch_mode="full")["boundaries"]
        self.assertEqual({b["kind"] for b in full["items"]}, {"reminder"})
        codex = loadout.build(self.profile(position="social", model={"tool": "codex", "model_id": ""}), None, None, None)
        self.assertNotIn("enforced_if_launched", {b["kind"] for b in codex["boundaries"]["items"]})
        self.assertIsNone(self.build()["boundaries"])   # no position, no boundaries

    def test_a_full_card_has_no_armor_to_show_and_can_depart(self):
        d = self.build(position="executor", launch_mode="full")
        self.assertFalse(d["armor"]["applicable"])
        self.assertIn("沒有限制", d["armor"]["why"])
        self.assertEqual(d["blockers"], [])

    def test_a_safe_card_keeps_its_armor(self):
        d = self.build(position="executor")
        self.assertTrue(d["armor"]["applicable"])
        self.assertEqual(d["blockers"], [])


class SkillCategoryTests(unittest.TestCase):
    def test_legal_and_finance_exist_with_labels_and_query_words(self):
        by_id = {c["id"]: c for c in categories.CATEGORIES}
        self.assertEqual(by_id["legal"]["label"], "法規與合規")
        self.assertEqual(by_id["finance"]["label"], "財務與帳務")
        self.assertIn("法律", by_id["legal"]["query"])
        self.assertIn("會計", by_id["finance"]["query"])
        self.assertEqual(len(categories.CATEGORIES), 12)

    def test_the_index_is_rebuilt_once_for_the_new_categories(self):
        self.assertEqual(index_mod.INDEX_VERSION, 3)

    def test_skills_land_in_the_new_categories_by_their_words(self):
        def ids(name, desc):
            return [c["id"] for c in categories.categorize(name, desc, "")]
        self.assertIn("legal", ids("gdpr-check", "Check privacy compliance and license terms"))
        self.assertIn("legal", ids("合約審閱", "檢查合約與法律風險"))
        self.assertIn("finance", ids("invoice-helper", "Bookkeeping and invoice tracking"))
        self.assertIn("finance", ids("報稅", "整理帳務與預算"))
        # a word that only looks like one does not file a skill under it
        self.assertNotIn("legal", ids("lawn", "Mow the lawn"))
        self.assertNotIn("finance", ids("syntax-tree", "Parse the syntax and keep a taxonomy"))

    def test_an_old_cached_index_is_not_trusted(self):
        # index.py reads its cache only when index_version equals INDEX_VERSION: a v2 file is rebuilt
        self.assertNotEqual(2, index_mod.INDEX_VERSION)


if __name__ == "__main__":
    unittest.main()
