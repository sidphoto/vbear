"""The READMEs' pictures: every <img> (and the dark banner's <source srcset>) points at a file in docs/images, every
file there is used by both READMEs, each picture is a PNG of at most 150 KB, and the two READMEs show the same
pictures in the same order (the captions are written once per language)."""
import re
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
READMES = ("README.md", "README.zh-TW.md")
MAX_BYTES = 150 * 1024


def png_top(path, rows=120):
    """Width, height and the mean luminance (0..1) of the first rows of a palette PNG with 8-bit indexes (what the
    screenshots are saved as), read with the standard library only."""
    data = path.read_bytes()
    pos, plte, idat, header = 8, b"", b"", None
    while pos < len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"IDAT":
            idat += body
        pos += 12 + size
    width, height, depth, color, _, _, interlace = header
    assert (depth, color, interlace) == (8, 3, 0), f"{path.name}: expected an 8-bit palette PNG"
    raw = zlib.decompress(idat)
    stride = width + 1
    prev, total, count = bytearray(width), 0.0, 0
    lum = [(0.2126 * plte[i] + 0.7152 * plte[i + 1] + 0.0722 * plte[i + 2]) / 255 for i in range(0, len(plte), 3)]
    for y in range(min(rows, height)):
        kind, line = raw[y * stride], bytearray(raw[y * stride + 1:(y + 1) * stride])
        for x in range(width):
            a = line[x - 1] if x else 0
            b = prev[x]
            c = prev[x - 1] if x else 0
            if kind == 1:
                line[x] = (line[x] + a) & 255
            elif kind == 2:
                line[x] = (line[x] + b) & 255
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif kind == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        total += sum(lum[i] for i in line)
        count += width
        prev = line
    return width, height, total / count


def referenced(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return re.findall(r'<(?:img src|source media="[^"]+" srcset)="(docs/images/[^"]+)"', text)


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

    def test_the_banner_opens_both_readmes_with_a_dark_version_for_the_dark_theme(self):
        picture = ('<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="docs/images/banner-dark.png">\n'
                   '  <img src="docs/images/banner.png" alt="%s" width="960">\n</picture>\n')
        for name, alt in (("README.md", "VBear — a pixel Formosan black bear at work"),
                          ("README.zh-TW.md", "VBear：戴耳機上班的像素台灣黑熊")):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# VBear\n\n" + picture % alt), name)
            self.assertEqual(referenced(name)[:2], ["docs/images/banner-dark.png", "docs/images/banner.png"], name)
            # it is not a screenshot: the one banner picture sits above the first paragraph, before the screenshot section
            self.assertLess(text.index("banner.png"), text.index("**"), name)
        # the banner is a palette PNG as wide as it is shown or wider, and the dark one is really dark
        for n in ("banner.png", "banner-dark.png"):
            width, height, mean = png_top(IMAGES / n)
            self.assertGreaterEqual(width, 960)
            self.assertEqual((width, height), (1280, 320))
            self.assertEqual(mean < 0.3, "dark" in n, n)

    def test_stale_sentences_are_gone_and_the_status_says_v09(self):
        en = (ROOT / "README.md").read_text(encoding="utf-8")
        zh = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
        for stale in ("predate the embodied upgrade", "taken before the three-line front", "(v0.3)"):
            self.assertNotIn(stale, en)
        for stale in ("尚未更新至人物化版本", "加上三行正面之前拍的", "（v0.3）"):
            self.assertNotIn(stale, zh)
        self.assertIn("Status: early (v0.9)", en)
        self.assertIn("目前狀態：早期版本（v0.9）", zh)
        for old in ("(v0.7)", "(v0.8)"):
            self.assertNotIn(old, en)
        for old in ("（v0.7）", "（v0.8）"):
            self.assertNotIn(old, zh)

    def test_the_v090_screens_are_shown_in_both_readmes(self):
        """The screens this release added: step 2 of the card wizard, a full-mode launch pass, a meeting and the office's
        meeting room."""
        for name in READMES:
            refs = referenced(name)
            for picture in ("card-wizard-position.png", "launch-pass-full.png", "meeting.png", "office-meeting-room.png"):
                self.assertIn(f"docs/images/{picture}", refs, f"{name}: {picture}")

    def test_the_position_badges_are_the_ones_the_pages_draw_now(self):
        """The starter deck and a task card's team places show the badge of the position (長, 工, 審 for CEO, 全端工程師
        and the review gate); a task card's three progress lights keep 規, 執, 審, which are phases, not positions."""
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        for glyph in ('glyph: "長"', 'glyph: "工"', 'glyph: "審"'):
            self.assertIn(glyph, app)
        for name, starter, team, lights, badges, old in (
                ("README.md", "Left: the **starter deck**", "A flow's **progress and team places**", "**Task cards** (demo data)",
                 "(長, 工, 審)", "(規, 執, 審)"),
                ("README.zh-TW.md", "左：**起手牌組**", "流程的**任務進度與隊伍位置**", "**任務卡**（示範資料）",
                 "（長、工、審）", "（規、執、審）")):
            text = (ROOT / name).read_text(encoding="utf-8")
            for start in (starter, team):
                block = text[text.index(start):].split("\n\n", 1)[0]
                self.assertIn(badges, block, f"{name}: {start}")
                self.assertNotIn(old, block, f"{name}: {start}")
            self.assertIn(old, text[text.index(lights):].split("\n\n", 1)[0], f"{name}: the progress lights")

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

    def test_a_picture_is_never_shown_larger_than_it_is(self):
        for name in READMES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for src, width in re.findall(r'<img src="(docs/images/[^"]+)"[^>]*width="(\d+)"', text):
                pixels = png_top(ROOT / src, rows=1)[0]
                self.assertLessEqual(int(width), pixels, f"{name}: {src} is shown at {width} px but is {pixels} px wide")

    def test_most_pictures_are_the_light_theme_and_the_dark_ones_are_really_dark(self):
        names = sorted({Path(r).name for r in referenced("README.md")})
        dark = [n for n in names if "-dark" in n]
        self.assertGreaterEqual(len(dark), 1)
        self.assertLess(len(dark), len(names) / 2)
        for n in names:
            mean = png_top(IMAGES / n)[2]
            if n in dark:
                self.assertLess(mean, 0.3, f"{n} is named dark but its top is light ({mean:.2f})")
            else:
                self.assertGreater(mean, 0.6, f"{n} should be the light theme but its top is dark ({mean:.2f})")

    def test_the_screens_the_readmes_describe_show_words_the_app_really_has(self):
        """The captions quote what is on the screen. Each quoted phrase of the new screens must still be in the page's
        source, so a rename cannot leave a README describing a button that is gone."""
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        quoted = ("接手提醒", "改成只觀看", "這是你剛開的終端，可以直接打字；打的字會直接送給 Agent", "核准計畫並開啟自動執行…",
                  "終端工作台", "標記：", "這是什麼", "打開角色卡", "回角色卡池", "回任務卡", "往下捲動看更多", "確認啟動",
                  "這個終端沒有關聯任務卡", "現在打字可能打斷它", "名冊，不代表正在出勤", "收藏中", "生效中", "看七項細節",
                  # v0.9.0: the wizard's step 2, the full-mode pass, the meeting pages and the office's meeting room
                  "VBear 內建：審查關卡（給任務卡的審查位）", "出發方式", "回復預設", "貼上職位指示", "VBear 沒有限制這張卡",
                  "開會討論", "預覽（還不會開始）", "開始開會", "代發言", "董事長桌", "去核准", "寫進任務卡", "輪到你：董事長核准")
        for phrase in quoted:
            self.assertIn(phrase, app, phrase)
        en = (ROOT / "README.md").read_text(encoding="utf-8")
        zh = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
        for phrase in ("接手提醒", "改成只觀看", "這是你剛開的終端，可以直接打字；打的字會直接送給 Agent", "核准計畫並開啟自動執行…",
                       "這個終端沒有關聯任務卡", "現在打字可能打斷它",
                       "VBear 內建：審查關卡（給任務卡的審查位）", "回復預設", "貼上職位指示", "VBear 沒有限制這張卡", "開會討論",
                       "開始開會", "代發言", "董事長桌", "去核准", "寫進任務卡", "輪到你：董事長核准"):
            self.assertIn(phrase, en, phrase)
            self.assertIn(phrase, zh, phrase)

    def test_the_readmes_no_longer_say_typing_always_needs_a_takeover(self):
        en = (ROOT / "README.md").read_text(encoding="utf-8")
        zh = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
        self.assertNotIn("typing takes an explicit takeover (one tab at a time)", en)
        self.assertNotIn("Typing into it takes an explicit takeover, and only", en)
        self.assertNotIn("要打字必須\n明確「接管」", zh)
        self.assertNotIn("要打字必須明確接管，", zh)
        # the exception is written down in both: a terminal this tab just started
        self.assertIn("has just started", en)
        self.assertIn("剛從出發通行證開出來", zh)


class ChangelogRelease(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_the_release_heading_matches_the_version(self):
        headings = [h for h in re.findall(r"^## (.+)$", self.text, re.M) if h != "Unreleased"]
        self.assertTrue(headings[0].startswith("v0.10.0"), headings[:3])
        self.assertTrue(headings[1].startswith("v0.9.0"), headings[:3])
        self.assertTrue(headings[2].startswith("v0.8.9"), headings[:3])
        init = (ROOT / "vbear" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "0.10.0"', init)

    def test_the_v090_section_covers_positions_professions_and_the_hover_box(self):
        section = self.text[self.text.index("## v0.9.0"):self.text.index("## v0.8.9")]
        for topic in ("one-person company", "全端工程師", "審查關卡", "picker you can read", "no longer clears its profession",
                      "kept on the card", "read whole"):
            self.assertIn(topic, section, topic)

    def test_the_v090_section_covers_the_meetings_and_the_office(self):
        section = self.text[self.text.index("## v0.9.0"):self.text.index("## v0.8.9")]
        for topic in ("`#/meetings`", "開會討論", "no tools", "StructuredOutput", "代發言", "R1–R8", "only to raise",
                      "董事長桌", "未驗證身分", "寫進任務卡", "`meeting_limits`", "80%", "Anthropic", "never its folder",
                      "會議室", "去核准", "輪到你：董事長核准", "carries out nothing"):
            self.assertIn(topic, section, topic)

    def test_the_v090_section_is_one_release_with_one_way_back(self):
        """v0.9.0 was never published on its own: its section reads as one release (a title that names the meetings, a
        short summary first) and says once, in one place, what going back to v0.8.9 does."""
        self.assertEqual(self.text.count("\n## v0.9.0"), 1)
        heading = re.search(r"^## (v0\.9\.0.*)$", self.text, re.M)[1]
        self.assertIn("meetings", heading)
        section = self.text[self.text.index("## v0.9.0"):self.text.index("## v0.8.9")]
        first = section.split("\n\n")[1]
        self.assertFalse(first.startswith("- "), "a summary comes before the list")
        for scattered in ("Going back to an earlier version", "An earlier version does not know",
                          "Going back to an earlier version reads the card file"):
            self.assertNotIn(scattered, section)
        self.assertEqual(section.count("**Going back to v0.8.9.**"), 1)
        back = section[section.index("**Going back to v0.8.9.**"):]
        for fact in ("`position`", "`instructions`", "`launch_mode`", "saving or copying a card", "sandboxed launch",
                     "this browser remembers", "index", "`meetings/`", "`meeting_limits`", "`plan.txt`",
                     "`translation-boundaries.json`"):
            self.assertIn(fact, back, fact)

    def test_the_v089_section_covers_the_category_row(self):
        section = self.text[self.text.index("## v0.8.9"):self.text.index("## v0.8.8")]
        for topic in ("sorts the skills by use", "全部", "其他", "rough"):
            self.assertIn(topic, section, topic)

    def test_the_v089_section_covers_role_names_and_the_model_menu(self):
        section = self.text[self.text.index("## v0.8.9"):self.text.index("## v0.8.8")]
        for topic in ("profession menu", "machine translation", "model box", "其他（自己輸入）", "never its other fields"):
            self.assertIn(topic, section, topic)

    def test_the_v088_section_covers_the_whole_chinese_summary(self):
        section = self.text[self.text.index("## v0.8.8"):self.text.index("## v0.8.7")]
        for topic in ("看完整說明", "never cut", "looks at the Chinese"):
            self.assertIn(topic, section, topic)

    def test_the_v087_section_covers_the_cli_path_the_tiles_and_delete(self):
        section = self.text[self.text.index("## v0.8.7"):self.text.index("## v0.8.6")]
        for topic in (".local/bin", "read in one glance", "delete buttons"):
            self.assertIn(topic, section, topic)

    def test_the_v086_section_covers_the_skill_picker_and_the_tidy_ups(self):
        section = self.text[self.text.index("## v0.8.6"):self.text.index("## v0.8.5")]
        for topic in ("Step 3 of the card wizard", "does not load these skills", "same name", "never three and one"):
            self.assertIn(topic, section, topic)

    def test_the_v085_section_covers_the_agy_skills_and_the_warning(self):
        section = self.text[self.text.index("## v0.8.5"):self.text.index("## v0.8.4")]
        for topic in ("without running AGY", "skills.json", "~/.agents/skills", "No false launch warning"):
            self.assertIn(topic, section, topic)

    def test_the_v084_section_says_agy_cards_are_not_started(self):
        section = self.text[self.text.index("## v0.8.4"):self.text.index("## v0.8.3")]
        for topic in ("Antigravity", "VBear does not start Antigravity", "Google", "shared skill cards", "Automatic mode is unchanged"):
            self.assertIn(topic, section, topic)

    def test_the_v083_section_covers_the_focus_and_the_terminal_words(self):
        section = self.text[self.text.index("## v0.8.3"):self.text.index("## v0.8.2")]
        for topic in ("skill card window", "Esc", "plain words", "技術細節", "原文"):
            self.assertIn(topic, section, topic)

    def test_the_v082_section_covers_the_hardening_and_the_interface_changes(self):
        section = self.text[self.text.index("## v0.8.2"):self.text.index("## v0.8.1")]
        for topic in ("Skill secrets", "~/Library", "taken off a role card", "one-pixel edge", "light and dark mode"):
            self.assertIn(topic, section, topic)

    def test_the_v081_section_says_the_new_logo_is_everywhere(self):
        section = self.text[self.text.index("## v0.8.1"):self.text.index("## v0.8.0")]
        for topic in ("pixel Formosan black bear", "app icon", "tab icon", "banner"):
            self.assertIn(topic, section, topic)

    def test_unreleased_covers_every_part_of_this_release(self):
        start = self.text.index("## v0.8.0")
        section = self.text[start:self.text.index("## v0.7.0")]
        for topic in ("After a start", "接手提醒", "改成只觀看", "取消", "Workbench", "下一步", "Plain words", "Card feel",
                      "shields", "Dark theme", "README screenshots"):
            self.assertIn(topic, section, topic)

    def test_unreleased_does_not_claim_more_than_the_pages_do(self):
        section = self.text[self.text.index("## v0.8.0"):self.text.index("## v0.7.0")]
        # the typing right and the note on the card are said with their limits
        self.assertIn("held only in memory", section)
        self.assertIn("lapses after two minutes", section)
        self.assertIn("a tracking record", section)
        # nothing says a skill card now loads, or that a shield means more than it did
        self.assertNotIn("loads", section.replace("never loads", "").replace("does not load", ""))
        self.assertIn("partly blocked,\n  untested and unknown still get none", section)


if __name__ == "__main__":
    unittest.main()
