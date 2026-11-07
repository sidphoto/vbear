"""P43-3 (ADR 0009 point 4): the chief of staff's list of employees says which of them have the shared folder open, and its fixed rules say that
only those can pass files to each other. The proposal's format does not change (no field to open a folder), and with no folder open the
prompt, the list and the hash are exactly what they were. Nothing runs: no CLI, no network. All names are made up."""
import json
import unittest

from tests.test_chief import card
from tests.test_chief_runner import Base, plan
from vbear import chief, chief_runner as cr


def listing(on=()):
    profiles = [card("w1", "social", name="文案小編"), card("w2", "pm", name="專案經理"), card("cx", "executor", tool="codex", name="會計")]
    return chief.candidates(profiles, ("claude", "codex"), (lambda pid, engine: pid in on) if on is not None else None)


def prompt(cards, omitted=0):
    return chief.build_prompt(messages=[{"role": "user", "text": "我想擺攤"}], omitted=0, cards=cards, omitted_cards=omitted,
                              tools=("claude", "codex"), note="")


class TheListTests(unittest.TestCase):
    def test_a_card_says_whether_the_folder_is_open_for_it_only_when_the_console_asks(self):
        without, _ = chief.candidates([card("w1", "social")], ("claude",))
        self.assertNotIn("shared", without[0])
        cards, _ = listing(on=())
        self.assertEqual([c["shared"] for c in cards], [False, False, False])

    def test_the_question_gets_the_role_card_and_its_engine(self):
        asked = []
        chief.candidates([card("w1", "social"), card("cx", "executor", tool="codex")], ("claude", "codex"),
                         lambda pid, engine: asked.append((pid, engine)) or False)
        self.assertEqual(sorted(asked), [("cx", "codex-chat"), ("w1", "claude-chat")])

    def test_with_none_open_the_list_the_prompt_and_the_hash_are_what_they_were(self):
        old, _ = chief.candidates([card("w1", "social", name="文案小編"), card("w2", "pm", name="專案經理"),
                                   card("cx", "executor", tool="codex", name="會計")], ("claude", "codex"))
        new, _ = listing(on=())
        self.assertEqual(chief.model_view(new), chief.model_view(old))
        self.assertEqual(prompt(new), prompt(old))
        self.assertEqual(chief.inputs_sha(new, 0, ("claude",)), chief.inputs_sha(old, 0, ("claude",)))
        self.assertNotIn("共用資料夾", prompt(new))

    def test_with_one_open_every_employee_says_so_and_the_rule_is_added(self):
        cards, _ = listing(on={"w1"})
        shown = chief.model_view(cards)
        self.assertEqual([(c["name"], c["shared"]) for c in shown], [("專案經理", False), ("文案小編", True), ("會計", False)])
        text = prompt(cards)
        self.assertIn(chief.SHARED_RULES, text)
        self.assertIn("只有這些員工之間可以用共用資料夾交接檔案", chief.SHARED_RULES)
        self.assertIn("在那一步的字裡寫明檔名", chief.SHARED_RULES)
        self.assertLess(text.index(chief.SHARED_RULES), text.index("BEGIN_UNTRUSTED_JSON_STRING"), "the rule is VBear's, outside the data")

    def test_the_hash_follows_who_has_the_folder_open(self):
        none, _ = listing(on=())
        one, _ = listing(on={"w1"})
        two, _ = listing(on={"w1", "w2"})
        shas = {chief.inputs_sha(c, 0, ("claude",)) for c in (none, one, two)}
        self.assertEqual(len(shas), 3)

    def test_the_stored_list_keeps_no_shared_field_so_the_record_does_not_change(self):
        cards, _ = listing(on={"w1"})
        sent = chief.sent_of(cards, 0, ("claude",), "a" * 64)
        self.assertTrue(all(set(c) == chief._SENT_CARD_KEYS for c in sent["cards"]))
        self.assertIsNone(chief._sent_problem(sent))

    def test_the_proposals_format_has_no_field_for_the_folder(self):
        schema = chief.plan_schema(("claude", "codex"))
        self.assertNotIn("shared", json.dumps(schema).lower())
        self.assertNotIn("共用", json.dumps(schema))


class ThroughTheRunnerTests(Base):
    def test_a_preview_and_a_proposal_use_the_list_with_the_folders_state(self):
        runner = self.board(plan(team=[{"who": "C1", "why": "會寫文案"}]))
        sources = self.sources()
        sources.shared = lambda pid, engine: pid == "copy"
        preview = runner.preview(self.chat_id, sources)
        self.assertTrue(preview["ok"], preview["blockers"])
        rec = runner.start(preview["preview_id"], {}, sources)
        runner.wait(10)
        (spec,) = self.specs
        self.assertIn(chief.SHARED_RULES, spec.prompt)
        saved = chief.load(rec["id"])
        self.assertEqual(set(saved["sent"]["cards"][0]), chief._SENT_CARD_KEYS)

    def test_a_request_without_the_question_is_as_before(self):
        runner = self.board(plan())
        saved = self.run_one(runner)
        self.assertNotIn("共用資料夾", self.specs[0].prompt)
        self.assertEqual(set(saved["sent"]["cards"][0]), chief._SENT_CARD_KEYS)

    def test_changing_the_switch_between_preview_and_start_is_a_changed_list(self):
        runner = self.board(plan())
        on = set()
        sources = self.sources()
        sources.shared = lambda pid, engine: pid in on
        preview = runner.preview(self.chat_id, sources)
        on.add("copy")
        with self.assertRaises(chief.ChiefError):
            runner.start(preview["preview_id"], {}, sources)


if __name__ == "__main__":
    unittest.main()
