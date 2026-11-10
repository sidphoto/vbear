"""P47-1 (ADR 0013): the sentences the screen says in plain words (``PLAIN_ERRORS`` of web/app.js) are the ones the server and the runtime
really send, and the server's own words are not changed: they are found, word for word, in the Python code. (The screen's table and its
behaviour are tested in tests/frontend/p47_words.cjs, which carries the same list; this one reads only the Python side.)"""

from __future__ import annotations

import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "vbear"

# sentence -> a file that says it
SENTENCES = {
    "VBear runtime 背景程序無法連線（": "daemon_client.py",
    "VBear runtime 背景程序無法使用（": "daemon_client.py",
    "VBear runtime 背景程序無法啟動或連線": "server.py",
    "VBear runtime 背景程序沒有在執行": "runtime/native.py",
    "VBear runtime 未連線，無法確認關聯的終端": "tasks.py",
    "VBear runtime 無法連線：": "runtime/native.py",
    "VBear runtime 未啟動或無法連線：": "runtime/native.py",
    "與 VBear runtime 的連線中斷": "runtime/native.py",
    "Agent CLI 版本檢查回傳失敗": "runtime/cli_versions.py",
    "Agent CLI 版本檢查逾時": "runtime/cli_versions.py",
    "Agent CLI 版本檢查失敗": "runtime/cli_versions.py",
    "Agent CLI 版本檢查無法執行": "runtime/cli_versions.py",
    "manual_review": "runtime/daemon_chat.py",
    "，需要人工處理": "runtime/daemon_chat.py",
    "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算。": "chat_service.py",
    "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算": "groups.py",
    "今天剩下的額度不到 US$0.01，不送出。": "chat_service.py",
}


class ServerSentencesAreUnchanged(unittest.TestCase):
    def test_each_sentence_the_screen_translates_is_still_said_by_the_server_as_it_was(self):
        for sentence, name in SENTENCES.items():
            with self.subTest(sentence=sentence):
                text = (PACKAGE / name).read_text(encoding="utf-8")
                self.assertIn(sentence, text, f"{name} no longer says it: the screen's table (PLAIN_ERRORS) must follow, never the other way round")

    def test_the_screen_table_knows_each_of_them(self):
        app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        table = app[app.index("const PLAIN_ERRORS = ["):app.index("// x: the original (a string, or an Error")]
        for word in ("今天的額度已用完（亮紅燈）", "今天剩下的額度不到 US\\$0\\.01", "無法連線到 VBear runtime", "Agent CLI 版本檢查", "manual_review", "孤兒翻譯"):
            self.assertIn(word, table, word)


if __name__ == "__main__":
    unittest.main()
