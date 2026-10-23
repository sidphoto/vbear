"""The pixel bear: macos/AppIcon.pixels.json is the one source (a 32 x 32 grid, a 16 x 16 grid for small sizes, the
palette and the plate colour). web/favicon.svg (16 x 16) and web/logo.svg (32 x 32) must be exactly those cells, drawn
with <rect> only and only the declared colours, and the page's mark must be that picture, served by the console."""
import json
import platform
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"
PIXELS = json.loads((ROOT / "macos" / "AppIcon.pixels.json").read_text(encoding="utf-8"))
DARK_PATH = ROOT / "macos" / "AppIcon-dark.pixels.json"
ICON_PATH = ROOT / "macos" / "AppIcon.icon" / "icon.json"


def rgb(hex_colour):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def read_png(data):
    """(width, height, rows of RGBA tuples) of an 8-bit RGBA, non-interlaced PNG."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            size = struct.unpack(">IIBBBBB", body)
            assert size[2:] == (8, 6, 0, 0, 0), size  # 8 bit, RGBA, no interlace
        elif kind == b"IDAT":
            idat += body
    width, height = size[0], size[1]
    raw, stride = zlib.decompress(idat), width * 4
    rows, prev = [], bytearray(stride)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b = prev[i]
            c = prev[i - 4] if i >= 4 else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * 4:x * 4 + 4]) for x in range(width)])
        prev = line
    return width, height, rows


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


class DarkAppIcon(unittest.TestCase):
    """The dark Dock/Finder icon: a second pixel file and an Icon Composer .icon that swaps plate and bear picture."""

    @property
    def dark(self):
        return json.loads(DARK_PATH.read_text(encoding="utf-8"))

    @property
    def icon(self):
        return json.loads(ICON_PATH.read_text(encoding="utf-8"))

    def test_dark_pixel_file_has_the_same_format_as_the_light_one(self):
        self.assertEqual(set(self.dark), set(PIXELS))
        for key, dim in (("rows", 32), ("icon16", 16)):
            self.assertEqual(len(self.dark[key]), dim, key)
            for row in self.dark[key]:
                self.assertEqual(len(row), dim, key)
                for ch in row:
                    self.assertIn(ch, self.dark["palette"], f"{key}: {ch!r} is not in the palette")
        self.assertEqual(set(self.dark["palette"]), set(PIXELS["palette"]))
        self.assertIsNone(self.dark["palette"]["."])
        for value in self.dark["palette"].values():
            self.assertTrue(value is None or re.fullmatch(r"#[0-9a-f]{6}", value), value)
        # the file is written the way the light one is, so the two diff cleanly
        for path, data in ((DARK_PATH, self.dark), (ROOT / "macos" / "AppIcon.pixels.json", PIXELS)):
            self.assertEqual(path.read_text(encoding="utf-8"), json.dumps(data, indent=2, ensure_ascii=False) + "\n", path.name)

    def test_dark_plate_is_dark_light_plate_is_light_and_the_bear_keeps_its_colours(self):
        def luminance(key, data):
            r, g, b = rgb(data["palette"][data["iconBackground"]])
            return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        self.assertGreater(luminance("light", PIXELS), 0.8)
        self.assertLess(luminance("dark", self.dark), 0.2)
        self.assertEqual(self.dark["palette"][self.dark["iconBackground"]], "#1d1d1b")
        for ch in "KkWfGT":
            self.assertEqual(self.dark["palette"][ch], PIXELS["palette"][ch], ch)

    def test_dark_bear_is_the_light_bear_plus_one_outline_cell(self):
        for key in ("rows", "icon16"):
            for y, (light_row, dark_row) in enumerate(zip(PIXELS[key], self.dark[key])):
                self.assertEqual(dark_row, dark_row[::-1], f"{key} row {y}")
                for x, (a, b) in enumerate(zip(light_row, dark_row)):
                    if a != b:
                        self.assertEqual((a, b), (".", "O"), f"{key} cell {(x, y)}")

    def test_icon_fill_colours_are_the_two_plate_colours(self):
        fills = self.icon["fill-specializations"]
        self.assertEqual(len(fills), 2)
        by_appearance = {f.get("appearance", "default"): f["value"]["solid"] for f in fills}
        self.assertEqual(set(by_appearance), {"default", "dark"})
        for name, data in (("default", PIXELS), ("dark", self.dark)):
            match = re.fullmatch(r"srgb:([\d.]+),([\d.]+),([\d.]+),1(?:\.0+)?", by_appearance[name])
            self.assertIsNotNone(match, by_appearance[name])
            got = tuple(round(float(v) * 255) for v in match.groups())
            self.assertEqual(got, rgb(data["palette"][data["iconBackground"]]), name)

    def test_icon_has_one_bear_layer_and_asks_the_system_for_no_effects(self):
        self.assertEqual(self.icon["supported-platforms"], {"squares": ["macOS"]})
        self.assertEqual(len(self.icon["groups"]), 1)
        group = self.icon["groups"][0]
        self.assertEqual(len(group["layers"]), 1)
        layer = group["layers"][0]
        self.assertIs(layer["glass"], False)
        self.assertIs(group["specular"], False)
        self.assertEqual(group["shadow"]["kind"], "none")
        self.assertIs(group["translucency"]["enabled"], False)
        self.assertEqual(layer["image-name-specializations"],
                         [{"value": "light.png"}, {"appearance": "dark", "value": "dark.png"}])
        self.assertNotIn("blend-mode", layer)
        self.assertNotIn("opacity", layer)

    def test_icon_document_holds_only_json_the_pictures_are_made_at_build_time(self):
        self.assertEqual(sorted(p.name for p in (ICON_PATH.parent).rglob("*") if p.is_file()), ["icon.json"])

    def test_info_plist_keeps_the_icns_name_and_names_the_asset_catalog_icon(self):
        plist = (ROOT / "macos" / "Info.plist.in").read_text(encoding="utf-8")
        self.assertIn("<key>CFBundleIconFile</key><string>AppIcon</string>", plist)
        self.assertIn("<key>CFBundleIconName</key><string>AppIcon</string>", plist)

    def test_build_makes_the_icns_for_old_systems_then_assets_car_with_actool(self):
        build = (ROOT / "macos" / "build.sh").read_text(encoding="utf-8")
        icns = build.index('iconutil -c icns -o "$RES/AppIcon.icns"')
        self.assertIn('make_icon.swift" "$ICONSET" "$ROOT/macos/AppIcon.pixels.json"', build)
        for needle in ('AppIcon-dark.pixels.json', "--layer", "macos/AppIcon.icon", "xcrun --find actool",
                       "--app-icon AppIcon", "--minimum-deployment-target", 'Assets.car'):
            self.assertIn(needle, build, needle)
        self.assertGreater(build.index("xcrun actool"), icns)  # actool comes after the icns is in place
        # without actool: one clear line and no failure; the icns stays the one iconutil made
        self.assertRegex(build, r"else\s+echo \"==> actool not found[^\n]*Assets\.car[^\n]*\"")
        # actool also writes its own AppIcon.icns: only Assets.car is taken from its output, and the icns is checked
        self.assertNotRegex(build, r"cp [^\n]*actool[^\n]*\.icns")
        self.assertRegex(build, r'cmp -s "\$RES/AppIcon\.icns" "\$BUILD/AppIcon\.icns"')

    def test_release_refuses_a_bundle_without_the_dark_icon(self):
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        smoke = release[release.index("Smoke-check the bundle"):release.index("Publish to the release")]
        self.assertIn("assetutil --info", smoke)
        self.assertIn("NSAppearanceNameDarkAqua", smoke)
        self.assertIn("NSAppearanceNameAqua", smoke)
        self.assertIn("Resources/Assets.car", smoke)
        script = (ROOT / "macos" / "smoke_test.sh").read_text(encoding="utf-8")
        self.assertIn("NSAppearanceNameDarkAqua", script)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("build.sh", ci)  # CI does not build the app

    @unittest.skipUnless(platform.system() == "Darwin" and shutil.which("swift"), "needs swift on macOS")
    def test_the_layer_picture_is_only_the_bear_one_cell_is_32_pixels(self):
        for name, data in (("light", PIXELS), ("dark", self.dark)):
            with tempfile.TemporaryDirectory() as tmp:
                src = ROOT / "macos" / ("AppIcon.pixels.json" if name == "light" else "AppIcon-dark.pixels.json")
                out = Path(tmp) / "layer.png"
                subprocess.run(["swift", str(ROOT / "macos" / "make_icon.swift"), str(Path(tmp) / "set"), str(src),
                                "--layer", str(out)], check=True, cwd=tmp, capture_output=True, timeout=300)
                width, height, rows = read_png(out.read_bytes())
            self.assertEqual((width, height), (1024, 1024), name)
            for y, row in enumerate(data["rows"]):
                for x, ch in enumerate(row):
                    colour = data["palette"][ch]
                    want = (0, 0, 0, 0) if colour is None else rgb(colour) + (255,)
                    for dx, dy in ((0, 0), (31, 0), (0, 31), (31, 31), (16, 16)):
                        self.assertEqual(rows[y * 32 + dy][x * 32 + dx], want, f"{name} cell {(x, y)} +{(dx, dy)}")
            # no plate in the layer: every "." cell above was transparent, the plate's cells included
            self.assertIn((3, 16), plate_cells(32))
            self.assertEqual(data["rows"][16][3], ".")


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
