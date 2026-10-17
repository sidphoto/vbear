"""The READMEs' pictures: every <img> points at a file in docs/images, every file there is used by both READMEs, each
picture is a PNG of at most 150 KB, and the two READMEs show the same pictures in the same order (the captions are
written once per language)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
READMES = ("README.md", "README.zh-TW.md")
MAX_BYTES = 150 * 1024


def referenced(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return re.findall(r'<img src="(docs/images/[^"]+)"', text)


class ReadmeImages(unittest.TestCase):
    def test_every_reference_exists_and_is_a_small_png(self):
        for name in READMES:
            refs = referenced(name)
            self.assertTrue(refs, name)
            for ref in refs:
                path = ROOT / ref
                self.assertTrue(path.is_file(), f"{name}: {ref} is missing")
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n", ref)
                self.assertLessEqual(path.stat().st_size, MAX_BYTES, f"{ref} is over 150 KB")

    def test_no_picture_is_left_unused(self):
        used = {Path(r).name for name in READMES for r in referenced(name)}
        self.assertEqual({p.name for p in IMAGES.glob("*.png")}, used)

    def test_both_readmes_show_the_same_pictures_in_order(self):
        self.assertEqual(referenced("README.md"), referenced("README.zh-TW.md"))

    def test_every_picture_has_alt_text_and_a_width(self):
        for name in READMES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for tag in re.findall(r"<img [^>]*>", text):
                self.assertRegex(tag, r'alt="[^"]+"', tag)
                self.assertRegex(tag, r'width="\d+"', tag)

    def test_stale_sentences_are_gone_and_the_status_says_v07(self):
        en = (ROOT / "README.md").read_text(encoding="utf-8")
        zh = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
        for stale in ("predate the embodied upgrade", "taken before the three-line front", "(v0.3)"):
            self.assertNotIn(stale, en)
        for stale in ("尚未更新至人物化版本", "加上三行正面之前拍的", "（v0.3）"):
            self.assertNotIn(stale, zh)
        self.assertIn("Status: early (v0.7)", en)
        self.assertIn("目前狀態：早期版本（v0.7）", zh)

    def test_every_caption_says_demo_data(self):
        for name, start, end, mark in (("README.md", "### What it looks like", "## What you can do with it", "demo data"),
                                       ("README.zh-TW.md", "### 畫面長這樣", "## 你可以用它做什麼", "示範資料")):
            text = (ROOT / name).read_text(encoding="utf-8")
            section = text[text.index(start):text.index(end)]
            blocks = [b.strip() for b in section.split("\n\n") if b.strip()]
            self.assertIn(mark, blocks[1], name)
            seen = 0
            for i, block in enumerate(blocks):
                if block.startswith("<img") or block.startswith("<p>"):
                    seen += 1
                    self.assertIn(mark, blocks[i + 1], f"{name}: the caption after {block[:60]!r}")
            self.assertGreaterEqual(seen, 10, name)


if __name__ == "__main__":
    unittest.main()
