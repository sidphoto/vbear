"""P46 documents: what the public repository may hold (P46-1: the evidence file and the synthetic fixtures). P46-6 adds the
checks of the glossary, the codes, rule 14 and the ADR to this file."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "docs" / "evidence" / "agy-1.5.3-chat.md"
FIXTURES = REPO / "tests" / "fixtures" / "agy-chat"

# What must never be in the repository, spelled in pieces so that this file does not hold it either: the names of the maintainer's own
# skills, plan and providers, the name of a temporary folder, the title of a test conversation.
PERSONAL = ["identi" + "fy-me", "grill" + "-me", "team" + "work", "minimax" + "-global", "vs." + "8kOc", "AI " + "Pro",
            "permissions " + "test", "MiniMax-" + "M3", "side" + "chang"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")


def problems(text: str, label: str) -> list[str]:
    found = []
    for word in PERSONAL:
        if word.casefold() in text.casefold():
            found.append(f"{label}: names something personal ({len(word)} characters)")
    for m in EMAIL.finditer(text):
        if not m.group(0).lower().endswith(SAFE_EMAIL_DOMAINS):
            found.append(f"{label}: an email-like string")
    for m in HOME_PATH.finditer(text):
        if m.group(0) not in ("/Users/fake-user", "/home/fake-user"):
            found.append(f"{label}: a path in a home folder")
    return found


class EvidenceFileTests(unittest.TestCase):
    def test_the_file_exists_and_holds_the_sections_of_the_plan(self):
        text = EVIDENCE.read_text(encoding="utf-8")
        for number in range(1, 12):
            self.assertRegex(text, rf"(?m)^## {number}\. ", f"section {number}")
        self.assertIn("raw messages were not kept", text)

    def test_the_file_holds_nothing_personal(self):
        text = EVIDENCE.read_text(encoding="utf-8")
        self.assertEqual(problems(text, "agy-1.5.3-chat.md"), [])

    def test_the_scan_fires_on_small_made_up_texts(self):
        for text in ("my home is /Users/alice/projects", "mail a.b@gmail.com now", "skill " + PERSONAL[0], "plan " + PERSONAL[5].lower(),
                     "at /home/bob/x"):
            self.assertTrue(problems(text, "x"), text)
        for text in ("mail a.b@example.com now", "/Users/fake-user/.codex", "the ~/.agents/hooks.json file", "plain words"):
            self.assertEqual(problems(text, "x"), [], text)


class FixtureFilesTests(unittest.TestCase):
    def test_every_fixture_says_it_is_synthetic_and_holds_nothing_personal(self):
        files = sorted(FIXTURES.glob("*.jsonl"))
        self.assertGreaterEqual(len(files), 15)
        for path in files:
            text = path.read_text(encoding="utf-8")
            first = text.splitlines()[0]
            self.assertTrue(first.startswith('{"_synthetic": "'), path.name)
            self.assertIn("not a recording", first, path.name)
            self.assertEqual(problems(text, path.name), [])

    def test_the_fake_agy_and_the_fixture_loader_hold_nothing_personal(self):
        for name in ("fake_agy_acp.py", "agy_chat_fixtures.py"):
            self.assertEqual(problems((REPO / "tests" / name).read_text(encoding="utf-8"), name), [])
        self.assertEqual(problems((REPO / "vbear" / "runtime" / "agy_chat_protocol.py").read_text(encoding="utf-8"),
                                  "agy_chat_protocol.py"), [])


if __name__ == "__main__":
    unittest.main()
