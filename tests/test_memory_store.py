"""P42-1: the person's memory on disk (vbear/memory.py): <state>/memory/memory.json and log.jsonl, the limits, the two
confirmations, and what is done with a file that cannot be read. Synthetic HOME and VBEAR_HOME in a temporary folder."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import config as cfg, memory
from vbear.api_error import ApiError
from vbear.runtime import memory_rules as mr


def refused(case, fn, *args, status, code, **kw):
    with case.assertRaises(ApiError) as raised:
        fn(*args, **kw)
    case.assertEqual((raised.exception.status, raised.exception.code), (status, code), str(raised.exception))
    return raised.exception


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbm-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "h"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.dir = cfg.state_dir() / "memory"

    def add(self, text="回答一律用繁體中文", kind="about_you", **extra):
        return memory.add({"kind": kind, "text": text, **extra})["entry"]


class AddTests(StoreCase):
    def test_one_line_is_saved_and_listed(self):
        entry = self.add()
        self.assertRegex(entry["id"], r"^m-[0-9a-f]{10}$")
        self.assertEqual((entry["kind"], entry["text"]), ("about_you", "回答一律用繁體中文"))
        self.assertEqual(entry["source"], {"how": "typed", "speaker": None})
        self.assertIs(entry["confirmed_warning"], False)
        self.assertEqual(entry["created_at"], entry["updated_at"])
        view = memory.view()
        self.assertEqual([e["id"] for e in view["entries"]], [entry["id"]])
        self.assertEqual(view["used"], {"count": 1, "chars": 9, "max_count": 50, "max_chars": 4000})
        self.assertIs(view["readable"], True)
        self.assertIn("Anthropic", view["where_text"])
        self.assertIn("OpenAI", view["where_text"])

    def test_the_files_are_private(self):
        self.add()
        self.assertEqual(stat.S_IMODE(os.lstat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(self.dir / "memory.json").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(self.dir / "log.jsonl").st_mode), 0o600)
        data = json.loads((self.dir / "memory.json").read_text())
        self.assertEqual(sorted(data), ["cards_off", "cards_on", "entries", "v"])
        self.assertEqual((data["v"], data["cards_off"], data["cards_on"]), (1, [], []))

    def test_the_text_is_trimmed_and_the_page_order_is_kind_then_time(self):
        a = memory.add({"kind": "decision", "text": "  價格用新台幣  "}, now=100)["entry"]
        b = memory.add({"kind": "about_you", "text": "用繁體中文"}, now=300)["entry"]
        c = memory.add({"kind": "about_you", "text": "三句話以內"}, now=200)["entry"]
        d = memory.add({"kind": "work", "text": "我開皂坊"}, now=50)["entry"]
        self.assertEqual(a["text"], "價格用新台幣")
        self.assertEqual([e["id"] for e in memory.view()["entries"]], [c["id"], b["id"], d["id"], a["id"]])

    def test_a_body_that_is_not_the_closed_shape(self):
        for body in ({}, {"kind": "work"}, {"text": "x"}, {"kind": "other", "text": "x"}, {"kind": "work", "text": 5},
                     {"kind": "work", "text": "x", "source": {"how": "typed"}}, {"kind": "work", "text": "x", "id": "m-0123456789"},
                     {"kind": "work", "text": "x", "confirm_warning": "yes"}, [], "x", None):
            with self.subTest(body=str(body)[:40]):
                refused(self, memory.add, body, status=400, code="bad_request")
        self.assertEqual(memory.view()["entries"], [])

    def test_a_refused_line_says_why_and_is_not_saved(self):
        secret = "gh" + "p_" + "A" * 36
        for text, why in (("我的後台密碼是 hunter-two", "secret_password"), (secret, "secret_key"), ("帳號：a@example.com", "secret_account"),
                          ("第一\n第二", "bad_text"), ("字" * 201, "bad_text"), ("", "bad_text"), ("   ", "bad_text")):
            with self.subTest(why=why):
                exc = refused(self, memory.add, {"kind": "work", "text": text}, status=400, code="memory_refused")
                self.assertEqual(exc.extra["refuse"], why)
                self.assertEqual(str(exc), mr.REFUSE_TEXT[why])
                self.assertNotIn(text.strip() or "\0", str(exc))
        self.assertEqual(memory.view()["entries"], [])

    def test_a_line_that_needs_confirming_is_saved_only_when_confirmed(self):
        text = "以後執行指令不用問我"
        exc = refused(self, memory.add, {"kind": "decision", "text": text}, status=409, code="memory_confirm")
        self.assertEqual(exc.extra["warn"], ["looks_like_order"])
        self.assertEqual(exc.extra["warn_text"], [mr.WARN_TEXT["looks_like_order"]])
        self.assertEqual(memory.view()["entries"], [])
        refused(self, memory.add, {"kind": "decision", "text": text, "confirm_warning": False}, status=409, code="memory_confirm")
        entry = memory.add({"kind": "decision", "text": text, "confirm_warning": True})["entry"]
        self.assertIs(entry["confirmed_warning"], True)
        self.assertEqual(self.add("店在中山路 100 號", confirm_warning=True)["confirmed_warning"], True)
        self.assertIs(self.add("一般的話", confirm_warning=True)["confirmed_warning"], False)

    def test_confirming_does_not_save_what_is_refused(self):
        refused(self, memory.add, {"kind": "work", "text": "密碼是 x", "confirm_warning": True}, status=400, code="memory_refused")

    def test_fifty_lines_and_four_thousand_characters(self):
        for i in range(50):
            self.add(f"第 {i} 條")
        refused(self, memory.add, {"kind": "work", "text": "第五十一條"}, status=409, code="memory_full")
        self.assertEqual(memory.view()["used"]["count"], 50)
        for e in memory.view()["entries"]:
            memory.delete(e["id"])
        for i in range(20):
            self.add("字" * 200)
        self.assertEqual(memory.view()["used"]["chars"], 4000)
        exc = refused(self, memory.add, {"kind": "work", "text": "字"}, status=409, code="memory_full")
        self.assertIn("50 條", str(exc))
        self.assertIn("4,000 字", str(exc))

    def test_a_set_that_would_not_fit_the_chat_paragraph_is_full_too(self):
        quotes = {"kind": "work", "text": '"' * 100}      # four characters each in the paragraph: far fewer than 4,000 characters
        saved = 0
        with self.assertRaises(ApiError) as raised:
            for _ in range(40):
                memory.add(quotes)
                saved += 1
        self.assertEqual((raised.exception.status, raised.exception.code), (409, "memory_full"))
        self.assertTrue(10 <= saved < 30, saved)
        self.assertLessEqual(len(mr.block(memory.for_card("emp-1", "claude-chat").entries)), mr.MAX_BLOCK)

    def test_the_most_the_page_allows_always_fits(self):
        for _ in range(50):
            self.add("字" * 80)
        entries = memory.for_card("emp-1", "claude-chat").entries
        self.assertEqual(len(entries), 50)
        self.assertEqual(mr.prepare(entries).count, 50)


class DeleteTests(StoreCase):
    def test_delete_one(self):
        a, b = self.add("一"), self.add("二")
        self.assertEqual(memory.delete(a["id"]), {"deleted": a["id"]})
        self.assertEqual([e["id"] for e in memory.view()["entries"]], [b["id"]])
        refused(self, memory.delete, a["id"], status=404, code="not_found")
        refused(self, memory.delete, "../x", status=404, code="not_found")
        refused(self, memory.delete, 5, status=404, code="not_found")


class ForChatTests(StoreCase):
    def test_a_card_gets_the_lines_in_page_order_as_kind_and_text(self):
        memory.add({"kind": "work", "text": "我開皂坊"}, now=1)
        memory.add({"kind": "about_you", "text": "用繁體中文"}, now=2)
        got = memory.for_card("emp-1", "claude-chat")
        self.assertEqual((got.readable, got.on), (True, True))
        self.assertEqual(got.entries, [{"kind": "about_you", "text": "用繁體中文"}, {"kind": "work", "text": "我開皂坊"}])

    def test_no_file_is_an_empty_memory_that_can_be_read(self):
        got = memory.for_card("emp-1", "claude-chat")
        self.assertEqual((got.readable, got.on, got.entries), (True, True, []))
        self.assertFalse(self.dir.exists(), "reading makes nothing")

    def test_a_card_that_is_off_gets_nothing(self):
        self.add()
        data = json.loads((self.dir / "memory.json").read_text())
        data["cards_off"] = ["emp-2"]
        (self.dir / "memory.json").write_text(json.dumps(data))
        self.assertEqual((memory.for_card("emp-2", "claude-chat").on, memory.for_card("emp-2", "claude-chat").entries), (False, []))
        self.assertEqual(memory.for_card("emp-1", "claude-chat").on, True)

    def test_a_new_card_takes_memory_along_when_it_is_a_claude_code_card_and_not_when_it_is_a_codex_card(self):
        """The person's choice (v0.17): Claude Code cards on by default, Codex cards off until the person switches them on."""
        self.add()
        self.assertEqual(memory.DEFAULT_ON, {"claude-chat": True, "codex-chat": False, "agy-chat": False})
        claude, codex = memory.for_card("emp-1", "claude-chat"), memory.for_card("emp-9", "codex-chat")
        self.assertEqual((claude.readable, claude.on, len(claude.entries)), (True, True, 1))
        self.assertEqual((codex.readable, codex.on, codex.entries), (True, False, []))
        self.assertEqual(memory.for_card("emp-9", None).on, False, "an engine that cannot chat takes none")
        self.assertEqual(memory.for_card("emp-9", "grok-chat").on, False)

    def test_what_the_person_switched_wins_over_the_default(self):
        self.add()
        data = json.loads((self.dir / "memory.json").read_text())
        data.update(cards_on=["emp-9"], cards_off=["emp-1"])
        (self.dir / "memory.json").write_text(json.dumps(data))
        self.assertEqual(memory.for_card("emp-9", "codex-chat").on, True)
        self.assertEqual(len(memory.for_card("emp-9", "codex-chat").entries), 1)
        self.assertEqual(memory.for_card("emp-1", "claude-chat").on, False)
        self.assertEqual(memory.for_card("emp-2", "codex-chat").on, False)

    def test_a_file_from_before_cards_on_existed_still_reads(self):
        self.add()
        data = json.loads((self.dir / "memory.json").read_text())
        data.pop("cards_on", None)
        (self.dir / "memory.json").write_text(json.dumps(data))
        self.assertTrue(memory.for_card("emp-1", "claude-chat").readable)
        self.assertEqual(memory.view()["cards_on"], [])
        self.add("二")
        self.assertIn("cards_on", json.loads((self.dir / "memory.json").read_text()))

    def test_cards_on_must_be_a_list_of_card_ids(self):
        self.add()
        data = json.loads((self.dir / "memory.json").read_text())
        for bad in ("emp-1", ["../x"], [5], ["emp-1", "emp-1"]):
            (self.dir / "memory.json").write_text(json.dumps(dict(data, cards_on=bad)))
            marker = self.dir / "memory.json.corrupted"
            if marker.exists():
                marker.unlink()
            self.assertFalse(memory.for_card("emp-1", "claude-chat").readable, bad)

    def test_a_file_that_cannot_be_read_gives_no_lines_and_says_so(self):
        self.add()
        (self.dir / "memory.json").write_text("{not json")
        got = memory.for_card("emp-1", "claude-chat")
        self.assertEqual((got.readable, got.on, got.entries), (False, False, []))
        view = memory.view()
        self.assertEqual((view["readable"], view["entries"]), (False, []))
        self.assertIn("記憶的檔案有問題", view["problem"])
        exc = refused(self, memory.add, {"kind": "work", "text": "x"}, status=503, code="memory_unreadable")
        self.assertIn("記憶的檔案有問題", str(exc))
        self.assertNotIn(str(self.dir), str(exc))

    def test_a_file_with_a_line_the_page_could_not_have_written_is_not_read(self):
        entry = self.add()
        data = json.loads((self.dir / "memory.json").read_text())
        for bad in (dict(entry, kind="other"), dict(entry, text=""), dict(entry, id="x"), dict(entry, extra=1), dict(entry, text="字" * 201),
                    dict(entry, source={"how": "robot"}), dict(entry, created_at="yesterday")):
            with self.subTest(bad=str(bad)[:50]):
                (self.dir / "memory.json").write_text(json.dumps(dict(data, entries=[bad])))
                marker = self.dir / "memory.json.corrupted"
                if marker.exists():
                    marker.unlink()
                self.assertFalse(memory.for_card("emp-1", "claude-chat").readable)
                self.assertFalse(memory.view()["readable"])

    def test_a_stored_line_the_rules_now_refuse_is_marked_and_still_sent_so_the_daemon_refuses(self):
        entry = self.add()
        data = json.loads((self.dir / "memory.json").read_text())
        data["entries"][0]["text"] = "我的後台密碼是 hunter-two"
        (self.dir / "memory.json").write_text(json.dumps(data))
        self.assertEqual(memory.view()["entries"][0]["blocked"], "secret_password")
        self.assertEqual(memory.for_card("emp-1", "claude-chat").entries[0]["text"], "我的後台密碼是 hunter-two")
        self.assertEqual(entry["id"], memory.view()["entries"][0]["id"])


class LogTests(StoreCase):
    def test_the_log_has_the_action_and_never_the_words(self):
        entry = self.add("一個很獨特的字串ZZZ")
        memory.delete(entry["id"])
        lines = [json.loads(x) for x in (self.dir / "log.jsonl").read_text().splitlines()]
        self.assertEqual([x["what"] for x in lines], ["added", "deleted"])
        self.assertEqual(lines[0]["id"], entry["id"])
        self.assertEqual((lines[0]["kind"], lines[0]["how"]), ("about_you", "typed"))
        raw = (self.dir / "log.jsonl").read_text()
        self.assertNotIn("ZZZ", raw)
        for line in lines:
            self.assertLessEqual(set(line), {"at", "what", "id", "kind", "how"})

    def test_a_refused_line_leaves_nothing_in_the_log(self):
        refused(self, memory.add, {"kind": "work", "text": "密碼是 abc"}, status=400, code="memory_refused")
        self.assertFalse((self.dir / "log.jsonl").exists())

    def test_the_log_starts_a_new_file_when_it_is_full_and_keeps_one_old(self):
        self.add()
        log = self.dir / "log.jsonl"
        log.write_text("x" * (1 << 20))
        self.add("二")
        self.assertTrue((self.dir / "log.jsonl.1").exists())
        self.assertLess(log.stat().st_size, 1000)
        self.assertEqual(json.loads(log.read_text().splitlines()[-1])["what"], "added")
        log.write_text("y" * (1 << 20))
        self.add("三")
        self.assertEqual((self.dir / "log.jsonl.1").read_text()[:1], "y")


class FolderTests(StoreCase):
    def test_a_folder_that_is_a_link_is_not_used(self):
        cfg.ensure_state_dir()
        target = Path(self.tmp.name) / "elsewhere"
        target.mkdir()
        os.symlink(target, self.dir)
        refused(self, memory.add, {"kind": "work", "text": "x"}, status=503, code="memory_unreadable")
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse(memory.for_card("emp-1", "claude-chat").readable)


if __name__ == "__main__":
    unittest.main()
