"""The pixel bear: macos/AppIcon.pixels.json is the one source (a 32 x 32 grid, a 16 x 16 grid for small sizes, the
palette and the plate colour). web/favicon.svg (16 x 16) and web/logo.svg (32 x 32) must be exactly those cells, drawn
with <rect> only and only the declared colours, and the page's mark must be that picture, served by the console."""
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"
PIXELS = json.loads((ROOT / "macos" / "AppIcon.pixels.json").read_text(encoding="utf-8"))


def plate_cells(dim):
    """The cells of the rounded plate (a 9% margin and a 0.225 radius, taken to whole cells)."""
    inset = round(dim * 0.09)
    body = dim - 2 * inset
    radius = body * 0.225
    cells = set()
    for gy in range(dim):
        for gx in range(dim):
            px, py = gx + 0.5 - inset, gy + 0.5 - inset
            cx, cy = max(radius, min(body - radius, px)), max(radius, min(body - radius, py))
            if 0 <= px < body and 0 <= py < body and (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2:
                cells.add((gx, gy))
    return cells


def expected(rows):
    """{(x, y): colour} for the bear's cells and the plate under it."""
    background = PIXELS["palette"][PIXELS["iconBackground"]]
    plate = plate_cells(len(rows))
    out = {}
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                out[(x, y)] = PIXELS["palette"][ch]
            elif (x, y) in plate:
                out[(x, y)] = background
    return out


def drawn(path, dim):
    """The cells an SVG draws, as {(x, y): colour}; fails on anything that is not a rect in a colour group."""
    text = path.read_text(encoding="utf-8")
    bare = text.replace('xmlns="http://www.w3.org/2000/svg"', "")
    for banned in ("<text", "<image", "<use", "<script", "<style", "<filter", "http", "xlink", "href", "url("):
        assert banned not in bare, f"{path.name} contains {banned}"
    root = ET.fromstring(text)
    assert root.tag == SVG + "svg"
    assert root.get("viewBox") == f"0 0 {dim} {dim}"
    assert root.get("shape-rendering") == "crispEdges"
    cells, colours = {}, set()
    for group in root:
        assert group.tag == SVG + "g" and set(group.attrib) == {"fill"}, group.tag
        colours.add(group.get("fill"))
        for rect in group:
            assert rect.tag == SVG + "rect" and set(rect.attrib) == {"x", "y", "width", "height"}, rect.attrib
            x, y, w, h = (int(rect.get(k)) for k in ("x", "y", "width", "height"))
            assert h == 1 and w >= 1 and x + w <= dim and 0 <= x and 0 <= y < dim, rect.attrib
            for cx in range(x, x + w):
                assert (cx, y) not in cells, f"{path.name}: cell {(cx, y)} is drawn twice"
                cells[(cx, y)] = group.get("fill")
    return cells, colours


class PixelData(unittest.TestCase):
    def test_only_the_fields_the_icon_needs(self):
        self.assertEqual(set(PIXELS), {"rows", "icon16", "palette", "iconBackground"})

    def test_grids_are_the_right_size_and_use_declared_colours(self):
        for key, dim in (("rows", 32), ("icon16", 16)):
            grid = PIXELS[key]
            self.assertEqual(len(grid), dim, key)
            for row in grid:
                self.assertEqual(len(row), dim, key)
                for ch in row:
                    self.assertIn(ch, PIXELS["palette"], f"{key}: {ch!r} is not in the palette")
        self.assertIsNone(PIXELS["palette"]["."])
        self.assertIsNotNone(PIXELS["palette"][PIXELS["iconBackground"]])
        for value in PIXELS["palette"].values():
            self.assertTrue(value is None or re.fullmatch(r"#[0-9a-f]{6}", value), value)

    def test_the_bear_is_left_right_symmetric(self):
        for key in ("rows", "icon16"):
            for y, row in enumerate(PIXELS[key]):
                self.assertEqual(row, row[::-1], f"{key} row {y}")

    def test_the_chest_v_is_white_and_the_bear_is_not_empty(self):
        for key in ("rows", "icon16"):
            text = "".join(PIXELS[key])
            self.assertGreater(text.count("W"), 10, key)
            self.assertGreater(text.count("K"), 80, key)


class SvgFiles(unittest.TestCase):
    def check(self, name, key, dim):
        cells, colours = drawn(ROOT / "web" / name, dim)
        self.assertEqual(cells, expected(PIXELS[key]), f"{name} is not the {key} grid")
        declared = {v for v in PIXELS["palette"].values() if v}
        self.assertLessEqual(colours, declared)
        return cells

    def test_the_tab_icon_is_the_16_grid_one_rect_a_cell(self):
        cells = self.check("favicon.svg", "icon16", 16)
        text = (ROOT / "web" / "favicon.svg").read_text(encoding="utf-8")
        self.assertEqual(text.count("<rect"), len(cells))  # width 1 each: one rect, one cell
        self.assertEqual(len(re.findall(r'width="1" height="1"', text)), len(cells))

    def test_the_page_mark_is_the_32_grid(self):
        self.check("logo.svg", "rows", 32)

    def test_the_plate_corners_are_empty_and_the_bear_is_inside_the_plate(self):
        for name, dim in (("favicon.svg", 16), ("logo.svg", 32)):
            cells, _ = drawn(ROOT / "web" / name, dim)
            for corner in ((0, 0), (dim - 1, 0), (0, dim - 1), (dim - 1, dim - 1)):
                self.assertNotIn(corner, cells, name)
            self.assertIn((dim // 2, dim // 2), cells, name)


class PageMark(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_the_brand_mark_is_the_picture_not_the_letter_v(self):
        match = re.search(r'<span class="brand-mark"([^>]*)>(.*?)</span>\s*<span class="brand-text">', self.html, re.S)
        self.assertIsNotNone(match)
        attrs, inner = match.groups()
        self.assertIn('aria-hidden="true"', attrs)
        self.assertNotRegex(inner.strip(), r"^V$")
        img = re.fullmatch(r'<img src="(/[^"]+\.svg)" alt="" width="32" height="32">', inner.strip())
        self.assertIsNotNone(img, inner)
        self.assertTrue((ROOT / "web" / img.group(1).lstrip("/")).is_file())
        self.assertEqual(img.group(1), "/logo.svg")
        self.assertIn("VBear<small>", self.html)  # the words stay

    def test_the_tab_icon_link_points_at_the_new_file(self):
        self.assertIn('<link rel="icon" href="/favicon.svg" type="image/svg+xml">', self.html)

    def test_the_mark_is_shown_one_pixel_a_cell(self):
        css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.brand-mark img \{[^}]*width: 32px; height: 32px;")
        self.assertNotRegex(css, r"\.brand-mark \{[^}]*background")

    def test_the_light_theme_marks_the_edge_of_the_plate_and_the_dark_theme_does_not(self):
        css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
        # the page's own theme decides, through the same three places that hold every theme colour:
        # the light :root, the dark rules for "follow the system", and the dark rules for an explicit choice
        light = re.search(r"^:root \{(.*?)^\}", css, re.S | re.M)
        follow = re.search(r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{(.*?)\n  \}\n\}', css, re.S)
        chosen = re.search(r'^:root\[data-theme="dark"\] \{(.*?)^\}', css, re.S | re.M)
        for name, block in (("light", light), ("follow-system dark", follow), ("chosen dark", chosen)):
            self.assertIsNotNone(block, name)
        value = re.search(r"--brand-mark-filter:\s*([^;]+);", light.group(1))
        self.assertIsNotNone(value, "the light theme defines the edge")
        steps = ["drop-shadow(" + part for part in value.group(1).split("drop-shadow(")[1:]]
        # four hard copies, one cell (1 CSS px at 32 px) to each side: no blur radius, so every edge stays a pixel edge
        self.assertEqual(sorted(re.match(r"drop-shadow\(([-\d]+(?:px)? [-\d]+(?:px)?) 0 ", x).group(1) for x in steps),
                         sorted(["1px 0", "-1px 0", "0 1px", "0 -1px"]))
        self.assertNotIn("blur(", value.group(1))
        for name, block in (("follow-system dark", follow), ("chosen dark", chosen)):
            self.assertRegex(block.group(1), r"--brand-mark-filter:\s*none;", name)
        rule = re.search(r"\.brand-mark img \{([^}]*)\}", css)
        self.assertIn("filter: var(--brand-mark-filter);", rule.group(1))
        self.assertNotRegex(rule.group(1), r"transform|scale|zoom")  # the mark is never resized
        self.assertNotIn("data-theme", rule.group(0))

    def test_the_mark_file_itself_carries_no_theme_rule(self):
        # an image's SVG cannot read the page's data-theme, so a prefers-color-scheme rule in it would disagree with the page
        for name in ("logo.svg", "favicon.svg"):
            self.assertNotIn("prefers-color-scheme", (ROOT / "web" / name).read_text(encoding="utf-8"), name)

    def test_the_server_sends_both_files(self):
        server = (ROOT / "vbear" / "server.py").read_text(encoding="utf-8")
        for route in ("/favicon.svg", "/logo.svg"):
            self.assertIn(f'"{route}": "{route[1:]}"', server)


class AppIconScript(unittest.TestCase):
    def test_the_icon_script_reads_the_pixel_file_and_build_passes_it(self):
        swift = (ROOT / "macos" / "make_icon.swift").read_text(encoding="utf-8")
        self.assertIn("JSONSerialization", swift)
        self.assertIn('json["icon16"]', swift)
        self.assertIn('json["rows"]', swift)
        build = (ROOT / "macos" / "build.sh").read_text(encoding="utf-8")
        self.assertIn('make_icon.swift" "$ICONSET" "$ROOT/macos/AppIcon.pixels.json"', build)

    def test_no_binary_picture_for_the_icon_is_in_macos(self):
        self.assertEqual([p.name for p in (ROOT / "macos").rglob("*") if p.suffix in (".png", ".icns")], [])


if __name__ == "__main__":
    unittest.main()
