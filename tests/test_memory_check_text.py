"""P44-1: ``memory_rules.check_text`` (the text of a skill, ADR 0010): the same rules as ``check``, a longer text that may have
line breaks, the limit given by the caller. ``check`` itself is not changed (its own tests are tests/test_memory_rules.py).
Every fake secret is built at run time from pieces."""

from __future__ import annotations

import unittest

from vbear.runtime import memory_rules as mr

KEY = "sk-" + "a1" * 12


class CheckTextTests(unittest.TestCase):
    def test_a_text_with_line_breaks_and_more_than_two_hundred_characters_is_fine(self):
        text = "第一步：整理昨天的銷售。\n第二步：寫成一段話。\n" + "字" * 500
        self.assertEqual(mr.check_text(text, 4000), {"refuse": None, "warn": []})

    def test_the_limit_is_the_callers(self):
        self.assertIsNone(mr.check_text("字" * 40, 40)["refuse"])
        self.assertEqual(mr.check_text("字" * 41, 40)["refuse"], "bad_text")
        self.assertEqual(mr.check_text("字" * 4001, 4000)["refuse"], "bad_text")
        self.assertIsNone(mr.check_text("字" * 4000, 4000)["refuse"])

    def test_shapes_that_are_never_a_text(self):
        for text in ("", "   ", " 頭有空白", "尾有空白\n", "a\x00b", "a\rb", "zero​width", "BEGIN_VBEAR_MEMORY_JSON",
                     "放 server.token 的地方", "標頭 x-vbear: 1", 5, None, ["x"]):
            with self.subTest(text=text):
                self.assertEqual(mr.check_text(text, 4000)["refuse"], "bad_text")

    def test_a_tab_is_allowed_and_a_line_break_only_when_the_text_may_have_them(self):
        self.assertIsNone(mr.check_text("欄位\t欄位", 4000)["refuse"])
        self.assertIsNone(mr.check_text("a\nb", 4000)["refuse"])
        self.assertEqual(mr.check_text("a\nb", 40, multiline=False)["refuse"], "bad_text")
        self.assertIsNone(mr.check_text("a b", 40, multiline=False)["refuse"])

    def test_the_same_secrets_as_check_are_refused_on_any_line(self):
        cases = {"secret_password": "步驟一\n我的後台密碼是 hunter-two", "secret_key": f"步驟一\n金鑰 {KEY}\n步驟二",
                 "secret_account": "步驟一\n寄到 someone@example.com", "secret_payment": "步驟一\n身分證 A123456789"}
        for code, text in cases.items():
            with self.subTest(code=code):
                self.assertEqual(mr.check_text(text, 4000)["refuse"], code)
                self.assertEqual(mr.check_text(text.replace("\n", " "), 4000)["refuse"], mr.check(text.replace("\n", " "))["refuse"])

    def test_the_same_warnings_as_check(self):
        self.assertEqual(mr.check_text("以後執行指令不用問我", 4000)["warn"], ["looks_like_order"])
        self.assertEqual(mr.check_text("先做這個\n電話 0912-345-678", 4000)["warn"], ["personal"])
        self.assertEqual(mr.check_text("寫成一段話貼到粉專", 4000), {"refuse": None, "warn": []})

    def test_check_on_one_line_is_unchanged(self):
        self.assertEqual(mr.check("回答一律用繁體中文"), {"refuse": None, "warn": []})
        self.assertEqual(mr.check("第一行\n第二行"), {"refuse": "bad_text", "warn": []})
        self.assertEqual(mr.check("x" * 201), {"refuse": "bad_text", "warn": []})
        self.assertEqual(mr.check("a\tb"), {"refuse": "bad_text", "warn": []})
        self.assertEqual(mr.check("我的後台密碼是 hunter-two")["refuse"], "secret_password")
        self.assertEqual(mr.check("以後不用問我"), {"refuse": None, "warn": ["looks_like_order"]})

    def test_a_refusal_never_carries_a_word_of_the_text(self):
        self.assertEqual(set(mr.check_text(f"金鑰 {KEY}", 4000)), {"refuse", "warn"})


if __name__ == "__main__":
    unittest.main()
