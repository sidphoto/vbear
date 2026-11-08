"""P42-5: one memory, from the first line to clearing it, over a real loopback console, the real chat service, a real runtime daemon
(in this process, in a temporary folder) and the fake Claude Code (tests/fake_chat_cli.py); the memory suggestion's call is a fake
(as in tests/test_memory_suggest_api.py). Every request here is one the pages make, with the body they send. Nothing here starts a
real AI tool or leaves the machine; every line of memory, every card and every reply is made up, and a key is built at run time.

The walk: save a line (a phone number needs 「我確定」, a password is refused), a new chat carries the memory (and says how many
lines), the suggestion (nothing saved by it; a line of it saved by the person, as ``suggested``), a change reaches the next
message, a card off and on again, a Codex card on only with the word about OpenAI, the export, and clearing it all. Also the
source of a suggested line: why the save asks for a file and does not ask ``memory_suggest.exists``."""

from __future__ import annotations

import json
import os
import re
import unittest
from decimal import Decimal

from tests.test_chat_daemon import clean
from tests.test_memory_api import RoutesCase
from tests.test_memory_suggest_api import EVIDENCE, VERSION, item
from vbear import config as cfg, meeting_runner as mr_mod, memory_suggest as ms, memory_suggest_runner as msr

SHOP = "我的店叫小熊皂坊，在週末市集擺攤（虛構）"
SHOP_NEW = "我的店改叫小熊肥皂，在週末市集擺攤（虛構）"
PHONE = "店的客服電話是 0912-345-678（虛構）"
PRICE = "價格一律用新台幣標示"
SUGGESTED = "每週六下午固定出貨（虛構）"
WORDS = ("小熊", "客服電話", "0912", "新台幣", "每週六", "qa-Pass")


def message_text(body):
    """What a log or a record says in words: the strings of every JSON line (a line that is not JSON is kept whole). The numbers of a
    line (its time, a cost) are not words and can hold any four digits by chance, so they are left out of the comparison."""
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    out = []
    for line in body.splitlines():
        try:
            out.extend(strings(json.loads(line)))
        except ValueError:
            out.append(line)
    return "\n".join(out)


def state_bytes(*parts):
    path = cfg.state_dir().joinpath(*parts)
    return path.read_bytes() if path.exists() else None


class MessageTextTests(unittest.TestCase):
    """The walk below looks for four digits of a phone number in the logs: only in words, never in a time or a cost."""

    def test_a_time_that_holds_the_four_digits_is_not_a_word(self):
        line = '{"seq":14,"at":1794107358.309124,"cost_usd":0.00912,"kind":"reply","text":"好的"}'
        self.assertNotIn("0912", message_text(line))
        self.assertIn("好的", message_text(line))

    def test_the_same_digits_in_a_message_or_a_line_that_is_not_json_still_count(self):
        self.assertIn("0912", message_text('{"at":1.5,"text":"打 0912-345 給我"}'))
        self.assertIn("0912", message_text("a plain log line 0912"))
        self.assertIn("0912", message_text('{"a":[{"b":"x0912"}]}'))


class WalkTests(RoutesCase):
    def setUp(self):
        super().setUp()
        self.svc.restart_pause = 0.25          # the old process is closed gracefully; the service tries again a few times
        self.runner = msr.MemorySuggestRunner(provider=lambda e: ("unused", VERSION), call=self.fake)
        self.console.memory_suggest = self.runner
        self.addCleanup(self.runner.wait, 5)
        self.key = "sk-ant-" + "api03-" + "Q" * 40
        self.answer = {"items": [item(SUGGESTED), item("回答一律用繁體中文", "about_you"), item(f"後台的金鑰是 {self.key}")]}
        self.specs = []

    def fake(self, spec, cancel):
        self.specs.append(spec)
        return mr_mod.CallResult(self.answer, dict(EVIDENCE), Decimal("0.02"))

    def turn(self, chat_id, n, text="你好"):
        status, out = self.say(chat_id, text)
        self.assertEqual(status, 202, out)
        self.wait_http_turn(chat_id, n)

    def starts(self):
        return [x for x in self.fake_log() if x["event"] == "start"]

    def entries_log(self):
        return [line.rsplit("entries=", 1)[1].split()[0] for line in self.logs if "chat process memory entries=" in line]

    def memory(self):
        return self.call("/api/memory")[1]

    def test_one_memory_from_the_first_line_to_clearing_it(self):
        # room for the day, so that a process is replaced only for the memory and never for what is left of the day's money
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 10}})[0], 200)
        config_before = state_bytes("config.json")
        self.configure([clean("text", 0) for _ in range(8)])   # every turn is the same recorded plain answer

        # a line, typed: a phone number asks for 「我確定」 first, a password is refused and left nowhere
        status, out = self.add("work", SHOP)
        self.assertEqual((status, out["entry"]["source"]), (201, {"how": "typed", "speaker": None}), out)
        status, out = self.add("about_you", PHONE)
        self.assertEqual((status, out["code"], out["warn"]), (409, "memory_confirm", ["personal"]), out)
        self.assertEqual(self.memory()["used"]["count"], 1, "nothing was saved without the word")
        status, out = self.add("about_you", PHONE, confirm_warning=True)
        self.assertEqual((status, out["entry"]["confirmed_warning"]), (201, True), out)
        phone_id = out["entry"]["id"]
        status, out = self.add("work", "我的後台密碼是 qa-Pass-4242")
        self.assertEqual((status, out["code"], out["refuse"]), (400, "memory_refused", "secret_password"), out)
        self.assertNotIn("qa-Pass", json.dumps(out, ensure_ascii=False))
        self.assertNotIn(b"qa-Pass", state_bytes("memory", "memory.json"))
        self.assertEqual(self.memory()["used"]["count"], 2)

        # a new chat carries the memory, and the chat says how many lines
        chat_id = self.open_http()
        self.assertEqual(self.view(chat_id)["memory"], {"on": True, "count": 2, "readable": True, "changed": False, "started_with_memory": None},
                         "nothing is known of the start before the first message")
        self.turn(chat_id, 1)
        self.assertEqual(self.view(chat_id)["memory"], {"on": True, "count": 2, "readable": True, "changed": False, "started_with_memory": True})
        first = self.starts()[0]["argv"]
        carried = first[first.index("--append-system-prompt") + 1]
        self.assertIn(SHOP, carried)
        self.assertEqual(self.entries_log(), ["2"])
        self.turn(chat_id, 2)
        self.assertEqual(len(self.starts()), 1, "nothing changed: the same process answers")

        # the suggestion: nothing of it is saved by VBear; a line of it is saved by the person, as a suggested one
        before = state_bytes("memory", "memory.json")
        preview = self.call("/api/memory/suggest/preview", "POST", {"chat_id": chat_id})[1]
        self.assertTrue(preview["ok"], preview)
        status, started = self.call("/api/memory/suggest", "POST", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 202, started)
        self.runner.wait(10)
        sid = started["id"]
        proposed = self.call(f"/api/memory/suggest/{sid}")[1]
        self.assertEqual([i["text"] for i in proposed["items"][:2]], [SUGGESTED, "回答一律用繁體中文"])
        self.assertEqual([i["refuse"] for i in proposed["items"]], [None, None, "secret_key"], "the key is shown as refused")
        self.assertEqual(state_bytes("memory", "memory.json"), before, "the run saved nothing")
        status, out = self.add("work", SUGGESTED, source={"how": "suggested", "suggestion_id": sid})
        self.assertEqual((status, out["entry"]["source"]), (201, {"how": "suggested", "suggestion_id": sid, "speaker": None}), out)
        self.assertEqual(self.add("work", proposed["items"][2]["text"], source={"how": "suggested", "suggestion_id": sid})[0], 400,
                         "a refused line stays refused whatever the source")
        self.assertEqual(self.call(f"/api/memory/suggest/{sid}/saved", "POST", {"indexes": [0]})[1]["saved"], [0])
        self.assertEqual(self.memory()["used"]["count"], 3)
        ledger = self.call("/api/meetings/ledger")[1]
        self.assertIn("memory_suggest", ledger["includes"])
        self.assertGreaterEqual(Decimal(ledger["spent_usd"]), Decimal("0.02"), "the day counts what the suggestion cost")

        # a line from the chat, by the person's press of 「記住」
        status, out = self.add("decision", PRICE, source={"how": "chat", "chat_id": chat_id, "turn": 1, "speaker": "you"})
        self.assertEqual((status, out["entry"]["source"]["how"]), (201, "chat"), out)
        self.assertEqual(self.view(chat_id)["memory"]["count"], 4)

        # P42-6: Claude Code does not apply a new system prompt to a session it goes on with, so a change does NOT reach the chat that
        # was already started: its next message goes to the same process, the page says the chat still has what it started with, and
        # only a NEW chat carries the new line
        shop_id = next(e["id"] for e in self.memory()["entries"] if e["text"] == SHOP)
        status, out = self.call(f"/api/memory/{shop_id}", "PATCH", {"text": SHOP_NEW})
        self.assertEqual(status, 200, out)
        self.assertTrue(self.view(chat_id)["memory"]["changed"], "the chat is told it still has what it started with")
        self.turn(chat_id, 3)
        self.assertEqual(len(self.starts()), 1, "no process is started for a prompt Claude Code would not use")
        fresh = self.open_http()
        self.assertEqual(self.view(fresh)["memory"]["changed"], False)
        self.turn(fresh, 1)                     # the employee has one process: the older chat's is closed for it, and the page of that chat goes on
        self.assertEqual(len(self.starts()), 2)
        second = self.starts()[1]["argv"]
        carried = second[second.index("--append-system-prompt") + 1]
        self.assertIn(SHOP_NEW, carried)
        self.assertNotIn(SHOP + "\"", carried)
        self.assertNotIn("--resume", second)
        self.assertEqual(self.starts()[1]["system_prompt"], carried, "a new chat works with the new memory")
        self.assertNotIn(SHOP_NEW, self.starts()[0]["system_prompt"], "and the first one with the old")

        # a card off: a chat that has the memory says so (what was sent cannot be taken back). The older chat goes on in a resumed process
        # that is sent no memory at all, and still works with the memory it started with
        self.assertEqual(self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": False})[0], 200)
        view = self.view(fresh)["memory"]
        self.assertEqual((view["on"], view["count"], view["readable"], view["changed"], view["started_with_memory"]), (False, 0, True, True, True))
        self.turn(chat_id, 4)
        third = self.starts()[2]
        self.assertIn("--resume", third["argv"])
        self.assertNotIn("--append-system-prompt", third["argv"])
        self.assertIn(SHOP, third["system_prompt"], "the session keeps what it was started with")
        # a chat started now carries not a word; on again: it says that it started without, and a new one has the memory
        third_chat = self.open_http()
        self.turn(third_chat, 1)
        self.assertNotIn("--append-system-prompt", self.starts()[3]["argv"])
        self.assertIsNone(self.starts()[3]["system_prompt"])
        self.assertEqual(self.view(third_chat)["memory"]["started_with_memory"], False)
        self.assertEqual(self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True})[0], 200)
        self.assertTrue(self.view(third_chat)["memory"]["changed"])
        fourth_chat = self.open_http()
        self.turn(fourth_chat, 1)
        fourth = self.starts()[4]["argv"]
        self.assertIn(PRICE, fourth[fourth.index("--append-system-prompt") + 1])
        self.assertEqual(self.entries_log(), ["2", "4", "none", "none", "4"])

        # a Codex card goes on only with the word about OpenAI
        codex = self.card("Codex 員工", "codex")
        status, out = self.call("/api/memory/cards", "POST", {"profile_id": codex, "on": True})
        self.assertEqual((status, out["code"], out["warn"]), (409, "memory_confirm", ["send_to_openai"]), out)
        status, out = self.call("/api/memory/cards", "POST", {"profile_id": codex, "on": True, "confirm_company": True})
        self.assertEqual((status, out["on"]), (200, True), out)
        self.assertEqual(self.call("/api/memory/cards", "POST", {"profile_id": codex, "on": False})[0], 200)

        # the export: every line, in words, and no id of a chat
        status, out = self.call("/api/memory/export")
        self.assertEqual(status, 200, out)
        self.assertRegex(out["filename"], r"^vbear-記憶-\d{8}\.md$")
        for text in (SHOP_NEW, PHONE, SUGGESTED, PRICE):
            self.assertIn(text, out["text"])
        self.assertNotIn(chat_id, out["text"])
        self.assertNotIn(sid, out["text"])

        # clearing needs the word; then nothing is left, and no word of it is in the log, the daemon's log or the chat's record
        self.assertEqual(self.call("/api/memory/clear", "POST", {"confirm": "清掉"})[0], 400)
        self.assertEqual(self.memory()["used"]["count"], 4)
        self.assertEqual(self.call("/api/memory/clear", "POST", {"confirm": "全部刪除"})[1]["cleared"], 4)
        self.assertEqual((self.memory()["entries"], self.memory()["used"]["count"]), ([], 0))
        self.assertEqual(self.view(chat_id)["memory"]["count"], 0)
        log = cfg.state_dir().joinpath("memory", "log.jsonl").read_text(encoding="utf-8")
        record = self.raw(chat_id)
        for where, body in (("memory log", log), ("daemon log", "\n".join(self.logs)), ("chat record", record)):
            for word in WORDS:
                self.assertNotIn(word, message_text(body).replace("你好", ""), (where, word))
        whats = [json.loads(x)["what"] for x in log.splitlines()]
        self.assertEqual(whats[-1], "cleared")
        for what in ("added", "edited", "card_off", "card_on", "exported"):
            self.assertIn(what, whats)
        self.assertIn(phone_id, log, "the log names the line by its id")
        self.assertEqual(state_bytes("config.json"), config_before, "no limit, mode or card changed on the way")


class SourceOfASuggestionTests(RoutesCase):
    """The save of a line asks whether the suggestion is a plain file of ours, not ``memory_suggest.exists``: that one reads the
    record whole and, when it does not read, moves it aside and blocks it, which a save of a line must not do."""

    def real_record(self):
        rec = ms.new_record(ms.new_id(), chat_id="c-" + "0" * 16, engine="claude-chat", read={"count": 1, "omitted": 0, "bytes": 1, "sha256": "0" * 64},
                            memory_count=0, inputs="0" * 64, limits={"per_call_usd": Decimal("0.1"), "total_usd": Decimal("0.1")},
                            now=1_800_000_000.0)
        ms.SuggestStore(rec["id"]).save(rec)
        return rec["id"]

    def test_both_ways_of_asking_agree_on_a_real_record_a_missing_one_a_link_and_a_folder(self):
        from vbear import memory
        self.assertEqual(memory.SUGGESTION_RE.pattern, ms.ID_RE.pattern)
        folder = ms.folder()
        sid = self.real_record()
        (folder / "ms-0123456789ab.json").mkdir()
        (folder / "ms-aaaaaaaaaaaa.json").symlink_to(folder / "elsewhere")
        for name, expect in ((sid, True), ("ms-ffffffffffff", False), ("ms-0123456789ab", False), ("ms-aaaaaaaaaaaa", False)):
            with self.subTest(name=name):
                self.assertEqual(ms.exists(name), expect)
                self.assertEqual(self.add("work", "週末在市集擺攤", source={"how": "suggested", "suggestion_id": name})[0],
                                 201 if expect else 400)
                if expect:
                    self.call(f"/api/memory/{self.memory_ids()[-1]}", "DELETE")

    def memory_ids(self):
        return [e["id"] for e in self.call("/api/memory")[1]["entries"]]

    def test_a_record_that_does_not_read_is_only_a_label_here_and_is_not_moved_aside_by_a_save(self):
        folder = ms.folder()
        os.makedirs(folder, mode=0o700, exist_ok=True)
        path = folder / "ms-0123456789ab.json"
        path.write_text("{not a record", encoding="utf-8")
        status, out = self.add("work", "週末在市集擺攤", source={"how": "suggested", "suggestion_id": "ms-0123456789ab"})
        self.assertEqual(status, 201, out)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not a record", "still in place")
        self.assertEqual(sorted(os.listdir(folder)), ["ms-0123456789ab.json"], "no marker, no quarantine file")


if __name__ == "__main__":
    unittest.main()
