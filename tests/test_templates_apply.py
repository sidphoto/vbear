"""P45-2: the record of the applies and the rules of the undo (vbear/templates_apply.py), over a temporary state folder. Nothing here
starts a program or reaches a chat. Every name and text is made up. The record holds ids, the id and key of a team template, digests,
states, times and counts, never a name or a word of a card, a skill or a routine."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import templates_apply as ta
from vbear.jsonstore import StoreError
from vbear.runtime import chat_store

CARD1, CARD2 = "prof-aaaaaaaaaaaa", "prof-bbbbbbbbbbbb"
SKILL1, SKILL2 = "k-111111111111", "k-222222222222"
ROUTINE1, ROUTINE2 = "r-111111111111", "r-222222222222"
FP = "f" * 64


def frm(template="shop", key="copy"):
    return {"template": template, "key": key}


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbta-")
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(os.path.realpath(self.tmp.name)) / "s"
        self.state.mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state), "HOME": str(self.state.parent)})
        patch.start()
        self.addCleanup(patch.stop)

    def made(self, apply_id, kind, ident, key="copy", template="shop", fp=FP, index=None):
        return ta.record_item(apply_id, {"kind": kind, "id": ident, "from": frm(template, key), "state": "made", "why": None, "fp": fp, "at": 1.0}, index)


class TheRecord(Home):
    def test_an_apply_is_begun_filled_and_ended_and_read_back_newest_first(self):
        first = ta.begin_apply("claude", now=100.0)
        self.made(first, "card", CARD1)
        ta.end_apply(first, "done", now=101.0)
        second = ta.begin_apply("codex", now=200.0)
        ta.end_apply(second, "partial", now=201.0)
        rows = ta.read_applies()
        self.assertEqual([r["id"] for r in rows], [second, first])
        self.assertRegex(first, r"^ta-[0-9a-f]{12}$")
        self.assertEqual((rows[1]["tool"], rows[1]["state"], rows[1]["at"], rows[1]["undone_at"]), ("claude", "done", 100.0, None))
        self.assertEqual(rows[1]["items"], [{"kind": "card", "id": CARD1, "from": frm(), "state": "made", "why": None, "fp": FP, "at": 1.0}])
        self.assertEqual(rows[0]["state"], "partial")

    def test_an_item_is_written_first_as_an_intent_and_then_replaced_in_place(self):
        a = ta.begin_apply("claude", now=1.0)
        index = ta.record_item(a, {"kind": "card", "id": CARD1, "from": frm(), "state": "intent", "why": None, "fp": None, "at": 2.0})
        self.assertEqual(index, 0)
        self.made(a, "card", CARD1, index=index)
        other = self.made(a, "skill", SKILL1, key="product")
        self.assertEqual(other, 1)
        items = ta.read_applies()[0]["items"]
        self.assertEqual([(i["kind"], i["state"]) for i in items], [("card", "made"), ("skill", "made")])

    def test_the_file_and_the_log_are_private_and_the_folder_too(self):
        a = ta.begin_apply("claude", now=1.0)
        ta.end_apply(a, "done", now=2.0)
        folder = self.state / "templates"
        self.assertEqual(stat.S_IMODE(os.lstat(folder).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(folder / "applies.json").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(folder / "log.jsonl").st_mode), 0o600)

    def test_the_log_has_an_id_a_kind_of_event_and_numbers_and_nothing_else(self):
        a = ta.begin_apply("claude", now=1.0)
        self.made(a, "card", CARD1)
        ta.end_apply(a, "done", now=2.0)
        ta.record_undo(a, [CARD1], now=3.0)
        lines = [json.loads(x) for x in (self.state / "templates" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([l["what"] for l in lines], ["applied", "undo"])
        for line in lines:
            self.assertEqual(set(line), {"at", "what", "id", "counts"})
            self.assertEqual(line["id"], a)
        self.assertEqual(lines[0]["counts"], {"cards": 1, "skills": 0, "routines": 0})
        self.assertEqual(lines[1]["counts"], {"cards": 1, "skills": 0, "routines": 0})

    def test_only_the_last_fifty_are_kept(self):
        ids = []
        for i in range(53):
            a = ta.begin_apply("claude", now=float(i))
            ta.end_apply(a, "done", now=float(i) + 0.5)
            ids.append(a)
        rows = ta.read_applies()
        self.assertEqual(len(rows), ta.MAX_APPLIES)
        self.assertEqual([r["id"] for r in rows], list(reversed(ids[3:])), "the three oldest are gone")

    def test_undo_marks_the_items_deleted_and_the_time_and_leaves_the_others(self):
        a = ta.begin_apply("claude", now=1.0)
        self.made(a, "card", CARD1)
        self.made(a, "skill", SKILL1, key="product")
        ta.end_apply(a, "done", now=2.0)
        ta.record_undo(a, [SKILL1], now=5.0)
        row = ta.read_applies()[0]
        self.assertEqual([(i["id"], i["state"]) for i in row["items"]], [(CARD1, "made"), (SKILL1, "deleted")])
        self.assertEqual(row["undone_at"], 5.0)

    def test_an_id_that_is_not_in_the_apply_is_refused_by_the_record(self):
        a = ta.begin_apply("claude", now=1.0)
        self.made(a, "card", CARD1)
        with self.assertRaises(StoreError):
            ta.record_undo(a, [CARD2], now=2.0)
        self.assertEqual(ta.read_applies()[0]["items"][0]["state"], "made")

    def test_a_file_the_module_could_not_have_written_blocks_reading_and_writing_and_is_not_mended(self):
        folder = self.state / "templates"
        folder.mkdir(mode=0o700)
        bad = {"v": 1, "applies": [{"id": "ta-0123456789ab", "at": 1.0, "tool": "claude", "state": "done", "undone_at": None, "items": [],
                                    "name": "額外的欄位"}]}
        (folder / "applies.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(StoreError):
            ta.read_applies()
        with self.assertRaises(StoreError):
            ta.begin_apply("claude", now=1.0)

    def test_a_record_of_another_shape_is_refused_at_every_field(self):
        good = {"id": "ta-0123456789ab", "at": 1.0, "tool": "claude", "state": "done", "undone_at": None,
                "items": [{"kind": "card", "id": CARD1, "from": frm(), "state": "made", "why": None, "fp": FP, "at": 1.0}]}
        self.assertIsNone(ta.problem_of_apply(good))
        for change in ({"id": "x"}, {"tool": "agy"}, {"state": "kept"}, {"at": "now"}, {"undone_at": "x"}, {"extra": 1}, {"items": [{}]},
                       {"items": [dict(good["items"][0], kind="group")]}, {"items": [dict(good["items"][0], state="kept")]},
                       {"items": [dict(good["items"][0], id="../x")]}, {"items": [dict(good["items"][0], fp="12")]},
                       {"items": [dict(good["items"][0], why="有名字的原因")]}, {"items": [dict(good["items"][0], name="客服")]},
                       {"items": [dict(good["items"][0], **{"from": {"template": "shop"}})]},
                       {"items": [dict(good["items"][0], **{"from": {"template": "shop", "key": "Bad Key"}})]}):
            self.assertTrue(ta.problem_of_apply(dict(good, **change)), change)

    def test_a_linked_folder_is_not_used(self):
        target = self.state.parent / "elsewhere"
        target.mkdir()
        os.symlink(target, self.state / "templates")
        with self.assertRaises(StoreError):
            ta.begin_apply("claude", now=1.0)
        self.assertEqual(list(target.iterdir()), [])


class TheFingerprint(Home):
    def test_a_card_uses_the_cards_digest_and_the_others_the_whole_record(self):
        from vbear import agent_profiles as ap
        card = {"id": CARD1, "name": "A", "updated_at": 1.0, "_decoration": 1}
        self.assertEqual(ta.fingerprint("card", card), ap.profile_digest(card))
        self.assertEqual(ta.fingerprint("card", dict(card, _decoration=2)), ta.fingerprint("card", card), "a key that starts with an underscore does not count")
        skill = {"id": SKILL1, "name": "S", "text": "t", "updated_at": 1.0}
        self.assertRegex(ta.fingerprint("skill", skill), r"^[0-9a-f]{64}$")
        self.assertNotEqual(ta.fingerprint("skill", skill), ta.fingerprint("skill", dict(skill, updated_at=2.0)))
        routine = {"id": ROUTINE1, "enabled": False, "updated_at": 1.0}
        self.assertNotEqual(ta.fingerprint("routine", routine), ta.fingerprint("routine", dict(routine, enabled=True)))
        self.assertEqual(ta.fingerprint("routine", routine), ta.fingerprint("routine", dict(reversed(list(routine.items())))), "the order of keys does not count")


class TheRecovery(Home):
    def test_an_apply_that_was_left_applying_is_closed_as_interrupted(self):
        a = ta.begin_apply("claude", now=1.0)
        ta.record_item(a, {"kind": "card", "id": CARD1, "from": frm(), "state": "intent", "why": None, "fp": None, "at": 2.0})
        ta.record_item(a, {"kind": "card", "id": CARD2, "from": frm(key="accounting"), "state": "intent", "why": None, "fp": None, "at": 3.0})
        ta.record_item(a, {"kind": "skill", "id": None, "from": frm(key="product"), "state": "intent", "why": None, "fp": None, "at": 4.0})
        ta.record_item(a, {"kind": "routine", "id": None, "from": frm(key="spend"), "state": "intent", "why": None, "fp": None, "at": 4.5})
        self.made(a, "card", "prof-cccccccccccc", key="service")
        done = ta.begin_apply("claude", now=10.0)
        ta.end_apply(done, "done", now=11.0)
        digests = {CARD1: "d" * 64}
        self.assertEqual(ta.recover(lambda pid: digests.get(pid)), 1)
        rows = {r["id"]: r for r in ta.read_applies()}
        self.assertEqual(rows[done]["state"], "done", "a finished one is left as it is")
        row = rows[a]
        self.assertEqual(row["state"], "interrupted")
        by_kind = [(i["kind"], i["state"], i["id"], i["fp"]) for i in row["items"]]
        self.assertEqual(by_kind[0], ("card", "made", CARD1, "d" * 64), "the card that is there is recorded as made, with its digest as it is now")
        self.assertEqual(by_kind[1], ("card", "failed", CARD2, None), "the card that is not there is recorded as failed")
        self.assertEqual(by_kind[2], ("skill", "unknown", None, None))
        self.assertEqual(by_kind[3], ("routine", "unknown", None, None))
        self.assertEqual(by_kind[4][1], "made", "what was recorded stays")

    def test_a_card_that_cannot_be_looked_at_is_unknown_and_never_made(self):
        a = ta.begin_apply("claude", now=1.0)
        ta.record_item(a, {"kind": "card", "id": CARD1, "from": frm(), "state": "intent", "why": None, "fp": None, "at": 2.0})

        def broken(pid):
            raise OSError("x")
        ta.recover(broken)
        self.assertEqual(ta.read_applies()[0]["items"][0]["state"], "unknown")

    def test_nothing_to_do_changes_nothing(self):
        self.assertEqual(ta.recover(lambda pid: None), 0)
        self.assertFalse((self.state / "templates").exists(), "looking creates nothing")


class TheMentions(Home):
    def chat(self, chat_id, **fields):
        folder = self.state / "chats" / chat_id
        folder.mkdir(parents=True)
        (folder / "chat.json").write_text(json.dumps(dict({"id": chat_id}, **fields)), encoding="utf-8")

    def put(self, relative, text="{}"):
        path = self.state / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_nothing_mentions_a_card_that_nobody_used(self):
        self.put("chats/c-0123456789abcdef/chat.json", json.dumps({"profile_id": "prof-zzzzzzzzzzzz"}))
        self.put("groups/g-0123456789ab.json", json.dumps({"members": ["prof-zzzzzzzzzzzz"]}))
        self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: set()})

    def test_each_place_gives_its_own_reason(self):
        places = {
            "chatted": [("chats/c-0123456789abcdef/chat.json", {"profile_id": CARD1})],
            "in_use": [("groups/g-0123456789ab.json", {"members": [CARD1]}), ("dispatch/d-0123456789ab.json", {"who": CARD1}),
                       ("chief/x.json", {"who": CARD1}), ("meetings/m.json", {"p": CARD1}), ("staffing/s.json", {"p": CARD1}),
                       ("sessions/l-0123456789abcdef/manifest.json", {"p": CARD1}), ("flows.json", {"roles": [CARD1]}), ("tasks.json", {"t": CARD1})],
            "switches": [("memory/memory.json", {"cards_off": [CARD1]}), ("shared-meta/state.json", {"cards_on": [CARD1]})],
        }
        for reason, rows in places.items():
            for relative, content in rows:
                with self.subTest(relative):
                    path = self.put(relative, json.dumps(content))
                    self.assertEqual(ta.card_mentions(self.state, [CARD1, CARD2]), {CARD1: {reason}, CARD2: set()})
                    path.unlink()

    def test_the_work_folder_of_the_card_counts_as_a_chat(self):
        (self.state / "chat-work" / chat_store.work_dir_name(CARD1)).mkdir(parents=True)
        self.assertEqual(ta.card_mentions(self.state, [CARD1, CARD2]), {CARD1: {"chatted"}, CARD2: set()})

    def test_what_cannot_be_read_counts_as_mentioned(self):
        target = self.state.parent / "elsewhere"
        target.mkdir()
        (target / "g.json").write_text("{}")
        os.symlink(target, self.state / "groups")
        self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: {"unreadable"}}, "a folder that is a link is not followed")

    def test_a_link_inside_a_folder_a_file_over_four_mib_and_too_many_files_are_all_unreadable(self):
        self.put("groups/a.json")
        os.symlink(self.state / "groups" / "a.json", self.state / "groups" / "b.json")
        self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: {"unreadable"}}, "a link")
        (self.state / "groups" / "b.json").unlink()
        self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: set()})
        with open(self.state / "groups" / "big.json", "wb") as fh:
            fh.truncate(ta.MENTION_FILE_MAX + 1)
        self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: {"unreadable"}}, "a file over 4 MiB")
        (self.state / "groups" / "big.json").unlink()
        with mock.patch.object(ta, "MENTION_FILES_MAX", 2):
            for i in range(3):
                self.put(f"groups/{i}.json")
            self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: {"unreadable"}}, "too many files")

    def test_a_file_that_cannot_be_opened_is_unreadable(self):
        path = self.put("chats/c-0123456789abcdef/chat.json")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest("this account reads everything")
        self.assertEqual(ta.card_mentions(self.state, [CARD1]), {CARD1: {"unreadable"}})

    def test_only_ordinary_files_are_looked_at_and_the_scan_reads_each_once(self):
        self.put("groups/a.json", json.dumps({"p": CARD1}))
        self.put("groups/b.json", json.dumps({"p": CARD2}))
        opened = []
        real = os.open

        def counting(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)
        with mock.patch.object(ta.os, "open", counting):
            found = ta.card_mentions(self.state, [CARD1, CARD2])
        self.assertEqual(found, {CARD1: {"in_use"}, CARD2: {"in_use"}})
        self.assertEqual(sorted(p for p in opened if p.endswith(".json")).count(str(self.state / "groups" / "a.json")), 1)


def routine(profile_id=CARD1):
    return {"fp": FP, "profile_id": profile_id}


class TheUndoPlan(unittest.TestCase):
    """The rules of the undo over the facts the console gathers: nothing is read or written here."""

    def apply_with(self, *items):
        rows = []
        for kind, ident, state in items:
            rows.append({"kind": kind, "id": ident, "from": frm(), "state": state, "why": None, "fp": FP if state == "made" else None, "at": 1.0})
        return {"id": "ta-0123456789ab", "at": 1.0, "tool": "claude", "state": "done", "undone_at": None, "items": rows}

    def facts(self, **over):
        base = {"cards": {CARD1: FP, CARD2: FP}, "skills": {SKILL1: FP, SKILL2: FP}, "routines": {ROUTINE1: routine(), ROUTINE2: routine(CARD2)},
                "run_ids": set(), "mentions": {}}
        base.update(over)
        return base

    def test_what_nobody_changed_or_used_is_deleted_routines_first_then_skills_then_cards(self):
        record = self.apply_with(("card", CARD1, "made"), ("skill", SKILL1, "made"), ("routine", ROUTINE1, "made"))
        out = ta.undo_plan(record, self.facts())
        self.assertEqual(out["delete"], [{"kind": "routine", "id": ROUTINE1}, {"kind": "skill", "id": SKILL1}, {"kind": "card", "id": CARD1}])
        self.assertEqual((out["keep"], out["gone"]), ([], []))

    def test_the_rules_for_a_routine(self):
        record = self.apply_with(("routine", ROUTINE1, "made"))
        for change, expected in (({"routines": {ROUTINE1: dict(routine(), fp="0" * 64)}}, ("keep", "changed")),
                                 ({"run_ids": {ROUTINE1}}, ("keep", "ran")),
                                 ({"routines": {}}, ("gone", None)),
                                 ({"routines": None}, ("keep", "unreadable")),
                                 ({"run_ids": None}, ("keep", "unreadable"))):
            out = ta.undo_plan(record, self.facts(**change))
            self.assertEqual(out["delete"], [], change)
            if expected[0] == "gone":
                self.assertEqual(out["gone"], [{"kind": "routine", "id": ROUTINE1}])
            else:
                self.assertEqual(out["keep"], [{"kind": "routine", "id": ROUTINE1, "why": expected[1]}], change)

    def test_the_rules_for_a_skill(self):
        record = self.apply_with(("skill", SKILL1, "made"))
        for change, expected in (({"skills": {SKILL1: "0" * 64}}, ("keep", "changed")), ({"skills": {}}, ("gone", None)), ({"skills": None}, ("keep", "unreadable"))):
            out = ta.undo_plan(record, self.facts(**change))
            self.assertEqual(out["delete"], [], change)
            if expected[0] == "gone":
                self.assertEqual(out["gone"], [{"kind": "skill", "id": SKILL1}])
            else:
                self.assertEqual(out["keep"], [{"kind": "skill", "id": SKILL1, "why": expected[1]}])

    def test_the_rules_for_a_card_one_reason_each(self):
        record = self.apply_with(("card", CARD1, "made"))
        cases = (({"cards": {CARD1: "0" * 64}}, "changed"), ({"mentions": {CARD1: {"chatted"}}}, "chatted"), ({"mentions": {CARD1: {"in_use"}}}, "in_use"),
                 ({"mentions": {CARD1: {"switches"}}}, "switches"), ({"mentions": {CARD1: {"unreadable"}}}, "unreadable"),
                 ({"cards": None}, "unreadable"), ({"routines": None}, "unreadable"))
        for change, why in cases:
            out = ta.undo_plan(record, self.facts(**change))
            self.assertEqual((out["delete"], out["keep"]), ([], [{"kind": "card", "id": CARD1, "why": why}]), change)
        out = ta.undo_plan(record, self.facts(cards={}))
        self.assertEqual((out["delete"], out["gone"]), ([], [{"kind": "card", "id": CARD1}]))

    def test_when_a_card_has_several_reasons_the_first_in_this_order_is_said(self):
        record = self.apply_with(("card", CARD1, "made"))
        out = ta.undo_plan(record, self.facts(cards={CARD1: "0" * 64}, mentions={CARD1: {"chatted", "in_use", "switches", "unreadable"}}))
        self.assertEqual(out["keep"][0]["why"], "unreadable")
        out = ta.undo_plan(record, self.facts(cards={CARD1: "0" * 64}, mentions={CARD1: {"chatted"}}))
        self.assertEqual(out["keep"][0]["why"], "changed")
        out = ta.undo_plan(record, self.facts(mentions={CARD1: {"switches", "in_use", "chatted"}}))
        self.assertEqual(out["keep"][0]["why"], "chatted")

    def test_a_routine_that_stays_keeps_the_card_it_is_given_to_and_one_that_goes_does_not(self):
        record = self.apply_with(("card", CARD1, "made"), ("routine", ROUTINE1, "made"))
        stays = self.facts(run_ids={ROUTINE1})
        out = ta.undo_plan(record, stays)
        self.assertEqual(out["keep"], [{"kind": "routine", "id": ROUTINE1, "why": "ran"}, {"kind": "card", "id": CARD1, "why": "routine_kept"}])
        self.assertEqual(out["delete"], [])
        out = ta.undo_plan(record, self.facts())
        self.assertEqual([d["id"] for d in out["delete"]], [ROUTINE1, CARD1])

    def test_a_routine_of_the_person_given_to_the_card_keeps_it_too(self):
        record = self.apply_with(("card", CARD1, "made"))
        out = ta.undo_plan(record, self.facts(routines={"r-999999999999": routine(CARD1)}))
        self.assertEqual(out["keep"], [{"kind": "card", "id": CARD1, "why": "routine_kept"}])

    def test_an_item_that_is_not_made_is_never_touched_or_listed_but_counted(self):
        record = self.apply_with(("card", CARD1, "intent"), ("card", CARD2, "failed"), ("skill", None, "unknown"), ("skill", SKILL2, "deleted"),
                                 ("routine", None, "intent"))
        out = ta.undo_plan(record, self.facts())
        self.assertEqual((out["delete"], out["keep"], out["gone"]), ([], [], []))
        self.assertEqual(out["unsure"], 3)

    def test_the_plan_never_names_an_id_that_is_not_in_the_record(self):
        record = self.apply_with(("card", CARD1, "made"))
        out = ta.undo_plan(record, self.facts(cards={CARD1: FP, "prof-zzzzzzzzzzzz": FP}, skills={SKILL1: FP}, routines={ROUTINE1: routine()}))
        ids = {x["id"] for part in ("delete", "keep", "gone") for x in out[part]}
        self.assertEqual(ids, {CARD1})

    def test_the_input_is_not_changed(self):
        record = self.apply_with(("card", CARD1, "made"), ("routine", ROUTINE1, "made"))
        facts = self.facts(mentions={CARD1: {"chatted"}})
        import copy
        before = (copy.deepcopy(record), copy.deepcopy(facts))
        ta.undo_plan(record, facts)
        self.assertEqual((record, facts), before)


if __name__ == "__main__":
    unittest.main()
