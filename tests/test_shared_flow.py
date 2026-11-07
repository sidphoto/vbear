"""P43-5 (ADR 0009): the whole shared folder, walked once over HTTP the way a person walks it. One real loopback console over the real
``ChatService``, ``Groups``, ``GroupRunner`` and ``Dispatcher`` on the fake runtime daemon (the group and dispatch tests' fixtures), a
real shared folder under the synthetic state folder, and Finder replaced by a fake that records the argv.

The walk: the page starts with every switch off and no folder -> the person opens one Claude Code employee, then a Codex employee (which
asks for ``confirm_company`` first) -> a group is made with the tick -> a round is spoken, the first member leaves a file, and the second
is sent its name (as data between the markers) while the page shows it under the first one's reply -> the person turns the second
employee off, a file is left again, and the second is told there are files and not which -> a dispatch is confirmed with the tick (the
new employee is opened, the existing ones are as they were) -> the Finder button asks for the one folder with the fixed command -> at the
end ``config.json`` is as it was, nothing in ``shared-meta`` holds a file name, no file was deleted, and the shared folder holds none of
the switches.

No CLI runs, no model, no Finder (``reveal_command`` is a fake in this console, as in every test); every name and file is made up."""

from __future__ import annotations

import json
import os
import stat
import unittest
from unittest import mock

from tests.test_shared_routes import DispatchBase
from vbear import agent_profiles as ap, chat_service, config as cfg, shared_folder

MARK_BEGIN, MARK_END = "BEGIN_UNTRUSTED_JSON_STRING", "END_UNTRUSTED_JSON_STRING"
FILE_A, FILE_B, FILE_C = "價目表-fictional.md", "進貨單-fictional.md", "草稿-fictional.md"


class TheWholeWalk(DispatchBase):
    def setUp(self):
        super().setUp()
        self.opened_in_finder: list = []
        self.console.reveal_command = self.opened_in_finder.append

    def everything_is_checked(self):
        """The AI tool's version has passed the chat check with the shared folder (the check itself is another test's)."""
        for patch in (mock.patch.object(chat_service.cli_versions, "shared_verified", return_value=True),
                      mock.patch.object(self.console.chats, "_shared_verified", return_value=True)):
            patch.start()
            self.addCleanup(patch.stop)

    # -- helpers ---------------------------------------------------------------------------------------------------------

    def switch(self, pid, on=True, **extra):
        return self.call("/api/shared/cards", "POST", {"profile_id": pid, "on": on, **extra})

    def put(self, name):
        self.shared.mkdir(mode=0o700, exist_ok=True)
        (self.shared / name).write_text("fictional words")

    def names_in(self, text):
        lines = text.split("\n")
        self.assertEqual((lines.count(MARK_BEGIN), lines.count(MARK_END)), (2, 2), text)       # the reply's block and the files' block
        return json.loads(lines[len(lines) - 1 - lines[::-1].index(MARK_BEGIN) + 1])

    def run_round(self, gid, text, leave):
        """The person speaks to everybody; the first member answers while ``leave()`` runs; the others are sent their messages."""
        runner = self.console.group_runner()
        status, out = self.call(f"/api/groups/{gid}/messages", "POST", {"text": text, "to": "all"})
        self.assertEqual(status, 202, out)
        runner.tick()
        leave()
        for _ in range(8):
            current = self.console.group_service().current(gid)
            if current is None:
                break
            self.daemon.finish(current["chat_id"], reply="好，我寫好了")
            runner.tick()
            runner.tick()
        self.assertIsNone(self.console.group_service().current(gid), "the round ended")

    def group_replies(self, gid):
        return [i for i in self.call(f"/api/groups/{gid}")[1]["items"] if i["kind"] == "reply"]

    # -- the walk --------------------------------------------------------------------------------------------------------

    def test_the_whole_walk(self):
        self.everything_is_checked()
        config_before = self.config_bytes()

        # 1. a fresh page: everything off, nothing made, no Finder
        status, page = self.call("/api/shared")
        self.assertEqual(status, 200, page)
        self.assertFalse(page["exists"])
        self.assertFalse(self.shared.exists())
        self.assertTrue(page["cards"] and not any(c["on"] for c in page["cards"]), "every switch starts off")
        self.assertEqual(self.opened_in_finder, [])

        # 2. the person opens a Claude Code employee; a Codex employee needs the person's yes about OpenAI first
        status, out = self.switch(self.writer)
        self.assertEqual(status, 200, out)
        self.assertEqual(stat.S_IMODE(os.lstat(self.shared).st_mode), 0o700)
        status, out = self.switch(self.codex_hand)
        self.assertEqual((status, out["code"], out["warn"]), (409, "shared_confirm", ["send_to_openai"]), out)
        self.assertEqual(self.switches(), [self.writer])
        self.assertEqual(self.switch(self.codex_hand, confirm_company=True)[0], 200)
        self.assertEqual(sorted(self.switches()), sorted([self.writer, self.codex_hand]))
        by = {c["profile_id"]: c for c in self.call("/api/shared")[1]["cards"]}
        self.assertEqual((by[self.writer]["on"], by[self.codex_hand]["on"], by[self.accountant]["on"]), (True, True, False))
        self.assertEqual(by[self.codex_hand]["company"], "OpenAI")

        # 3. a group with the tick: the member who had it off gets it, the one who had it on is not logged again
        status, made = self.call("/api/groups", "POST", {"profile_ids": [self.writer, self.accountant], "shared_folder": True})
        self.assertEqual(status, 200, made)
        self.assertEqual(made["shared"], {"opened": [self.accountant]})
        gid = made["group"]["id"]
        self.assertEqual([(x["what"], x["how"]) for x in self.log()],
                         [("card_on", "page"), ("card_on", "page"), ("card_on", "group")])

        # 4. a round: the writer leaves a file; the accountant is told its name, as data, and the page shows it under the writer's reply
        self.put("old-fictional.md")
        self.run_round(gid, "我想在週末市集賣手工皂", lambda: self.put(FILE_A))
        sent = [m for m in self.daemon.sent if m["text"] and "共用資料夾" in m["text"] and MARK_END in m["text"]]
        self.assertEqual(len(sent), 1, "only the second member gets a list")
        self.assertEqual(self.names_in(sent[0]["text"]), [FILE_A])
        self.assertTrue(all(m.get("shared") is True for m in self.daemon.sent), "both were sent with the folder on")
        replies = self.group_replies(gid)
        self.assertEqual([r.get("shared_changes", {}).get("names") for r in replies], [[FILE_A], None])
        changes = json.loads((self.meta / "changes" / f"{gid}.jsonl").read_text().splitlines()[0])
        self.assertEqual(changes["names"], [FILE_A])

        # 5. the person turns the accountant off: it takes hold at once, nothing is deleted, and the next list says there are files, not which
        status, out = self.switch(self.accountant, False)
        self.assertEqual(status, 200, out)
        self.assertEqual(sorted(self.switches()), sorted([self.writer, self.codex_hand]))
        self.assertTrue((self.shared / FILE_A).exists() and (self.shared / "old-fictional.md").exists(), "closing deletes nothing")
        mark = len(self.daemon.sent)
        self.run_round(gid, "再補一份進貨單", lambda: self.put(FILE_B))
        later = self.daemon.sent[mark:]
        self.assertEqual(len(later), 2)
        self.assertTrue(later[0].get("shared") is True and "shared" not in later[1], "the one that is off is sent without the folder")
        self.assertIn("你沒有打開共用資料夾", later[1]["text"])
        self.assertNotIn(FILE_B, later[1]["text"])

        # 6. a dispatch confirmed with the tick: the new employee is opened, the existing one stays as it was
        did = self.propose()
        known = set(ap.load_all(None, None, mark_corrupt=False))
        status, out = self.tick(did)
        self.assertEqual(status, 200, out)
        (new_id,) = set(ap.load_all(None, None, mark_corrupt=False)) - known
        self.assertIn(new_id, self.switches())
        self.assertEqual(out["shared"], {"opened": []}, "the writer was on already")
        self.assertEqual([x["how"] for x in self.log() if x["profile_id"] == new_id], ["dispatch"])
        self.assertEqual(self.pending(did)["on"], False, "the tick is spent")

        # 7. the Finder button asks for the one folder with the fixed command, once, and the console has opened nothing itself
        status, out = self.call("/api/shared/reveal", "POST", {})
        self.assertEqual((status, out), (200, {"ok": True, "revealed": True}))
        self.assertEqual(self.opened_in_finder, [["/usr/bin/open", str(self.shared)]])

        # 8. what must be true at the end
        self.assertEqual(self.config_bytes(), config_before, "config.json was not written by any of it")
        self.assertTrue((self.shared / FILE_A).exists() and (self.shared / FILE_B).exists(), "no file was deleted")
        for path in self.meta.rglob("*"):
            if path.is_file() and path.parent.name != "changes":
                self.assertNotIn("fictional", path.read_text(), f"{path.name} holds a file name")
        for item in self.shared.iterdir():
            self.assertNotIn(item.name, ("settings.json", "log.jsonl", "pending", "changes"), "the switches are not in the folder employees write to")
        group_dir = cfg.state_dir() / "groups" / gid
        for path in group_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn("fictional", path.read_text(), f"the group's {path.name} holds a file name")
        self.assertEqual({x["what"] for x in self.log()}, {"card_on", "card_off", "revealed"})

    def test_the_tick_alone_never_opens_a_codex_employee_without_the_yes(self):
        status, out = self.call("/api/groups", "POST", {"profile_ids": [self.writer, self.codex_hand], "shared_folder": True})
        self.assertEqual((status, out["code"]), (409, "shared_confirm"), out)
        self.assertEqual(self.call("/api/groups")[1]["groups"], [])
        self.assertEqual(self.switches(), [])
        self.assertFalse(self.shared.exists())

    def test_a_version_not_checked_with_the_folder_stops_an_employee_that_is_on_and_not_one_that_is_off(self):
        self.assertEqual(self.switch(self.writer)[0], 200)
        _, chat = self.call("/api/chats", "POST", {"profile_id": self.writer})
        status, out = self.call(f"/api/chats/{chat['chat']['id']}/messages", "POST", {"text": "你好"})
        self.assertEqual((status, out["code"]), (409, "shared_unverified"), out)
        self.assertEqual(self.daemon.sent, [], "nothing was sent")
        _, other = self.call("/api/chats", "POST", {"profile_id": self.accountant})
        status, out = self.call(f"/api/chats/{other['chat']['id']}/messages", "POST", {"text": "你好"})
        self.assertEqual(status, 202, out)


if __name__ == "__main__":
    unittest.main()
