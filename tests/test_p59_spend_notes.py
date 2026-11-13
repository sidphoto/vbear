"""P59-4 (v0.25.4): two notes about the day's money are written in docs/SECURITY-MODEL.md as the code is today; these tests hold the code to the notes, so that a
change of the code has to change the notes too. They read the syntax trees of the sources and start nothing.

  1. The chief of staff reads the chat and builds its list of cards first (``_context``, "the scan": local, nothing sent, nothing spent) and checks the day's money
     (``_day``, ``_blockers``) after it, in ``preview``, ``start`` and ``retry``; the skill suggestions' ``start`` is shaped the same.
  2. What 「整理成技能」 (``skill_suggest``) spent counts in the ledger and in every other board's check of the day, but not in the check a chat turn makes in the
     runtime (``daemon_chat.ChatOps._chat_day_spent``): the gap that SECURITY-MODEL.md calls "A known gap in the day's money". Its own limits are named in the notes
     (the per-call cap, the check at its start, one call per press, at most 200 records) and held here.
"""
from __future__ import annotations

import ast
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "vbear"


def tree_of(*parts):
    return ast.parse(PACKAGE.joinpath(*parts).read_text(encoding="utf-8"))


def method(tree, class_name, name):
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name):
            return fn
    return None


def first_self_call_line(fn, names):
    """The line of the first ``self.<name>(...)`` call in ``fn`` for any name in ``names`` (None when there is none)."""
    lines = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in names
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"]
    return min(lines) if lines else None


def order_problems(tree, class_name, name, label=None):
    """The scan (``_context``) comes before the day's money (``_day`` or ``_blockers``) in the method; a problem for each way it does not."""
    label = label or f"{class_name}.{name}"
    fn = method(tree, class_name, name)
    if fn is None:
        return [f"{label} is not there"]
    scan, day = first_self_call_line(fn, {"_context"}), first_self_call_line(fn, {"_day", "_blockers"})
    if scan is None:
        return [f"{label} does not read the chat and the cards (_context)"]
    if day is None:
        return [f"{label} does not look at the day's money (_day or _blockers)"]
    return [] if scan < day else [f"{label} looks at the day's money (line {day}) before it reads the chat and the cards (line {scan})"]


def names_in(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.ImportFrom):
            out.update(a.asname or a.name for a in n.names)
    return out


class ChiefScanComesBeforeTheDaysMoney(unittest.TestCase):
    def test_preview_start_and_retry_read_the_chat_and_the_cards_before_they_look_at_the_day(self):
        tree = tree_of("chief_runner.py")
        for name in ("preview", "start", "retry"):
            self.assertEqual(order_problems(tree, "ChiefRunner", name), [], name)

    def test_the_skill_suggestions_start_is_shaped_the_same(self):
        self.assertEqual(order_problems(tree_of("skillbook_suggest_runner.py"), "SkillSuggestRunner", "start"), [])

    def test_the_check_catches_a_day_look_that_comes_first(self):
        bad = ast.parse("class ChiefRunner:\n    def preview(self):\n        day = self._day()\n        ctx = self._context(1)\n")
        self.assertNotEqual(order_problems(bad, "ChiefRunner", "preview"), [])
        none = ast.parse("class ChiefRunner:\n    def preview(self):\n        return 1\n")
        self.assertNotEqual(order_problems(none, "ChiefRunner", "preview"), [])
        late = ast.parse("class ChiefRunner:\n    def start(self):\n        ctx = self._context(1)\n        more = self._blockers(1, 2, {})\n")
        self.assertEqual(order_problems(late, "ChiefRunner", "start"), [])

    def test_a_refusal_for_the_budget_comes_before_the_worker_lock_and_the_record(self):
        fn = method(tree_of("chief_runner.py"), "ChiefRunner", "start")
        day, lock, record = first_self_call_line(fn, {"_blockers"}), first_self_call_line(fn, {"_worker"}), first_self_call_line(fn, {"_launch"})
        self.assertTrue(day < lock < record)


class SkillSuggestionsAreOutsideTheChatsDay(unittest.TestCase):
    def test_a_chat_turn_adds_up_the_day_without_the_skill_suggestions(self):
        fn = method(tree_of("runtime", "daemon_chat.py"), "ChatOps", "_chat_day_spent")
        self.assertIsNotNone(fn)
        seen = names_in(fn)
        for kind in ("chief", "memory_suggest", "try_spend", "day_spent"):
            self.assertIn(kind, seen, kind)
        for kind in ("skillbook_suggest", "ks", "skill_suggest"):
            self.assertNotIn(kind, seen, f"{kind}: SECURITY-MODEL.md says a chat turn's day does not include the skill suggestions; change the note with the code")

    def test_every_board_and_the_ledger_count_them(self):
        for filename, cls in (("meeting_runner.py", "MeetingRunner"), ("chief_runner.py", "ChiefRunner"), ("memory_suggest_runner.py", "MemorySuggestRunner"),
                              ("staffing_runner.py", "StaffingRunner"), ("skillbook_suggest_runner.py", "SkillSuggestRunner")):
            fn = method(tree_of(filename), cls, "spend_kinds")
            self.assertIsNotNone(fn, filename)
            self.assertTrue({"skillbook_suggest", "ks"} & names_in(fn), filename)
        text = (PACKAGE / "meeting_runner.py").read_text(encoding="utf-8")
        self.assertIn('"includes": ["meetings", "staffing", "chats", "setup_try", "chief", "memory_suggest", "skill_suggest"]', text)

    def test_the_skill_suggestions_have_limits_of_their_own(self):
        from vbear import skillbook_suggest as ks, skillbook_suggest_runner as runner
        self.assertEqual(ks.CALL_USD, Decimal("0.10"))
        self.assertEqual(ks.TOTAL_USD, ks.CALL_USD)
        self.assertEqual(ks.MAX_RECORDS, 200)
        self.assertEqual(ks.KIND, "skill_suggest")
        self.assertEqual(runner.cap_usd(Decimal("0"), Decimal("3")), Decimal("0.10"))
        self.assertEqual(runner.cap_usd(Decimal("2.95"), Decimal("3")), Decimal("0.05"))
        self.assertEqual(runner.cap_usd(Decimal("3"), Decimal("3")), Decimal("0"))
        start = method(tree_of("skillbook_suggest_runner.py"), "SkillSuggestRunner", "start")
        self.assertIsNotNone(first_self_call_line(start, {"_blockers"}))
        self.assertIsNotNone(first_self_call_line(start, {"_check_count"}))
        text = ast.unparse(start)
        self.assertIn("raise ks.SuggestError('budget')", text)

    def test_the_note_says_so_in_the_security_model(self):
        text = (ROOT / "docs" / "SECURITY-MODEL.md").read_text(encoding="utf-8")
        gap = text[text.index("### A known gap in the day's money"):]
        gap = gap[:gap.index("### Residual risks of skills and routines")]
        for part in ("`_chat_day_spent`", "does not include", "`skill_suggest`", "Checked again in v0.25.4", "`CALL_USD`", "US$0.10", "200", "`daily_usd`"):
            self.assertIn(part, gap, part)


if __name__ == "__main__":
    unittest.main()
