"""P57 follow-up 2: the small classifier that tells a few well-known failures of an AI tool apart by the words it printed.

Shared by 「試一下」 (vbear/setup_try.py, the tail of the error output of a failed program) and by the Codex chat (the message
of Codex's ``error`` notification when a turn fails). It only maps text to one of a few fixed words; it keeps nothing.
"""
from __future__ import annotations

import unittest

from vbear.runtime import failure_words as fw

# Codex 0.167.0, a ChatGPT account, a model the account cannot use (the sentence is OpenAI's; the model name is made up here)
MODEL_SENTENCE = "The 'gpt-0.0-example' model is not supported when using Codex with a ChatGPT account."


class ClassifyTests(unittest.TestCase):
    def test_the_model_sentence_is_a_model_problem(self):
        self.assertEqual(fw.classify(MODEL_SENTENCE), "model")
        self.assertEqual(fw.classify(MODEL_SENTENCE.encode()), "model")
        for text in ("model is not supported", "The model gpt-x is NOT supported here", "Unsupported model: gpt-x", "unsupported model"):
            self.assertEqual(fw.classify(text), "model", text)

    def test_other_model_sentences_are_not_guessed(self):
        for text in ("The model 'x' does not exist", "model overloaded", "this feature is not supported", "not supported", "models list"):
            self.assertEqual(fw.classify(text), "failed", text)

    def test_the_other_classes_are_as_before(self):
        self.assertEqual(fw.classify("unexpected status 401 Unauthorized: Missing bearer"), "not_logged_in")
        self.assertEqual(fw.classify("You've hit your usage limit"), "limit")
        self.assertEqual(fw.classify("failed to connect to Responses WebSocket"), "network")
        self.assertEqual(fw.classify(""), "failed")
        self.assertEqual(fw.classify(None), "failed")

    def test_the_order_is_login_then_model_then_limit_then_network(self):
        self.assertEqual(fw.classify("timed out\n" + MODEL_SENTENCE), "model")
        self.assertEqual(fw.classify(MODEL_SENTENCE + "\n429 Too Many Requests"), "model")
        self.assertEqual(fw.classify(MODEL_SENTENCE + "\nunexpected status 401 Unauthorized"), "not_logged_in")
        self.assertEqual(fw.classify("429 Too Many Requests\ntimed out"), "limit")

    def test_every_class_has_a_chat_sentence_and_only_the_model_one_talks_about_models(self):
        self.assertEqual(set(fw.CHAT_WORDS), {"not_logged_in", "model", "limit", "network", "failed"})
        for code, words in fw.CHAT_WORDS.items():
            self.assertTrue(words and "\n" not in words, code)
        self.assertIn("不能用這個模型", fw.CHAT_WORDS["model"])
        self.assertIn("工具預設", fw.CHAT_WORDS["model"])
        self.assertIn("新對話", fw.CHAT_WORDS["model"])
        self.assertNotIn("模型", fw.CHAT_WORDS["failed"])
        self.assertIn("登入", fw.CHAT_WORDS["not_logged_in"])
        self.assertIn("用量到上限", fw.CHAT_WORDS["limit"])
        self.assertIn("網路", fw.CHAT_WORDS["network"])
        self.assertIn("原因 VBear 看不出來", fw.CHAT_WORDS["failed"])


class ChatRecordTextTests(unittest.TestCase):
    def test_the_text_is_the_sentence_then_the_original_cut_to_a_limit(self):
        text = fw.chat_error_text(MODEL_SENTENCE, 4000)
        sentence, _, detail = text.partition(fw.DETAIL_MARK)
        self.assertEqual(sentence, fw.CHAT_WORDS["model"])
        self.assertEqual(detail, MODEL_SENTENCE)

    def test_it_is_never_longer_than_the_limit_and_keeps_the_sentence_whole(self):
        for limit in (400, 1000, 4000):
            text = fw.chat_error_text("x" * 100000, limit)
            self.assertLessEqual(len(text), limit)
            self.assertTrue(text.startswith(fw.CHAT_WORDS["failed"] + fw.DETAIL_MARK))
        self.assertLessEqual(len(fw.chat_error_text("unexpected status 401 Unauthorized " + "y" * 9000, 4000)), 4000)

    def test_white_space_and_control_characters_are_flattened_in_the_original(self):
        text = fw.chat_error_text("line one\r\n\tline two\x00\x1b[31m red\n\n  end", 4000)
        detail = text.partition(fw.DETAIL_MARK)[2]
        self.assertEqual(detail, "line one line two [31m red end")
        self.assertNotIn("\x1b", text)

    def test_an_empty_message_gives_no_text(self):
        for empty in ("", "   \n ", None, 5, [], {}):
            self.assertEqual(fw.chat_error_text(empty, 4000), "", repr(empty))


if __name__ == "__main__":
    unittest.main()
