"""P14: words on the screens that a person reads. The launch pass's bypass sentence has no development code in it and keeps
what it says; no Chinese sentence in the page or the launch labels carries a stage code (S0, L2 ...); every task template
the server has is named in Chinese by the page (the stored key is not changed)."""
import re
import unittest
from pathlib import Path

from vbear import agent_launch, tasks

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CJK = re.compile(r"[一-鿿]")
STAGE_CODE = re.compile(r"\b[SLR][0-9]\b")


def string_literals(source: str):
    """Quoted text of lines that are not comments: good enough to find a code word inside a sentence."""
    for no, line in enumerate(source.splitlines(), 1):
        code = line.strip()
        if code.startswith(("//", "#", "*", "/*")):
            continue
        for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\\n]|\\.)*)`', line):
            yield no, m.group(1) or m.group(2) or ""


class BypassSentence(unittest.TestCase):
    def test_the_claude_bypass_sentence_says_what_was_tested_in_plain_words(self):
        text = agent_launch.BYPASS_PTY
        self.assertNotRegex(text, STAGE_CODE)
        self.assertIn("實測過：這種模式可以寫入你的家目錄", text)
        # nothing weaker: it is still said that the shell command skips the sandbox and that the label is no boundary
        self.assertIn("不經沙盒", text)
        self.assertIn("不是不可繞過的邊界", text)

    def test_every_bypass_sentence_is_free_of_stage_codes(self):
        for text in (agent_launch.BYPASS_PTY, agent_launch.BYPASS_OTHER_PTY, agent_launch.BYPASS_CODEX_PTY):
            self.assertNotRegex(text, STAGE_CODE)

    def test_no_sentence_in_the_page_carries_a_stage_code(self):
        found = [(no, t) for no, t in string_literals(APP) if CJK.search(t) and STAGE_CODE.search(t)]
        self.assertEqual(found, [])

    def test_no_user_facing_sentence_of_the_launch_module_carries_a_stage_code(self):
        source = (ROOT / "vbear" / "agent_launch.py").read_text(encoding="utf-8")
        found = [(no, t) for no, t in string_literals(source) if CJK.search(t) and STAGE_CODE.search(t)]
        self.assertEqual(found, [])


class TemplateNames(unittest.TestCase):
    def test_every_server_template_has_a_chinese_name_in_the_page(self):
        block = re.search(r"const TEMPLATE_NAMES = \{(.*?)\};", APP, re.S)
        self.assertIsNotNone(block)
        names = dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))
        self.assertEqual(set(names), set(tasks.TEMPLATES))
        for key, name in names.items():
            self.assertRegex(name, CJK, key)
            self.assertNotEqual(name, key)

    def test_the_stored_value_is_still_the_key(self):
        self.assertIn("custom", tasks.TEMPLATES)
        self.assertEqual(tasks.TEMPLATES["custom"]["title"], "自訂任務")


if __name__ == "__main__":
    unittest.main()
