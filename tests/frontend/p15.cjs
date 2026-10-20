// P15 (v0.8.0): the back of a role card has the art's v5 pattern, a tidy row of small crosses on a clear ground, and it is
// drawn strong enough to show on every camp's card in both themes. The real web/app.js and web/style.css.
// Run: node tests/frontend/p15.cjs   (exit code 0 = pass)
// VBEAR_FLOW_ART=<dir of the art> also compares the page's copy with the art's own cards.json.
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app } = h;

const CSS_SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
const APP_SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// the pattern of art 0.8.0-art-5, written out so the check does not rest on a file outside the repo
const V5 = [
  "................", "....K.......K...", "...KKK.....KKK..", "....K.......K...",
  "................", "................", "................", "................",
  "................", "....K.......K...", "...KKK.....KKK..", "....K.......K...",
  "................", "................", "................", "................",
];

const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const ratioOf = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const blend = (fg, bg, a) => "#" + [1, 3, 5].map((i) => Math.round(a * parseInt(fg.slice(i, i + 2), 16) + (1 - a) * parseInt(bg.slice(i, i + 2), 16)).toString(16).padStart(2, "0")).join("");

test("the back pattern is the v5 art: a clear ground and only the outline colour", () => {
  assert.deepStrictEqual(app.CARD_PIXELS.backPattern, V5);
  assert.strictEqual(app.CARD_PIXELS.backPattern.length, 16);
  assert(app.CARD_PIXELS.backPattern.every((r) => r.length === 16));
  // no old pale ground (n) and no yellow dot (Y): nothing but clear cells and the theme's outline
  assert.deepStrictEqual([...new Set(app.CARD_PIXELS.backPattern.join(""))].sort(), [".", "K"]);
});

test("the back pattern is a regular row of plus-shaped crosses (8x8 period, four of them in the tile)", () => {
  const rows = app.CARD_PIXELS.backPattern;
  const cells = [];
  rows.forEach((r, y) => [...r].forEach((c, x) => { if (c === "K") cells.push([x, y]); }));
  assert.strictEqual(cells.length, 20, "four crosses of five cells");
  const has = (x, y) => rows[y][x] === "K";
  // the centres are the cells with all four neighbours set
  const centres = cells.filter(([x, y]) => has(x - 1, y) && has(x + 1, y) && has(x, y - 1) && has(x, y + 1));
  assert.deepStrictEqual(centres, [[4, 2], [12, 2], [4, 10], [12, 10]]);
  // every set cell belongs to one of those crosses (no stray dots, no merged blobs)
  const inCross = new Set(centres.flatMap(([x, y]) => [[x, y], [x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]].map((p) => p.join(","))));
  assert.strictEqual(inCross.size, 20);
  for (const [x, y] of cells) assert(inCross.has(`${x},${y}`), `stray cell ${x},${y}`);
  // an 8x8 period: it tiles without a seam
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) assert.strictEqual(rows[y][x], rows[(y + 8) % 16][x], "vertical period");
  for (const r of rows) assert.strictEqual(r.slice(0, 8), r.slice(8), "horizontal period");
});

test("the strip draws the crosses only in the theme's outline class and no ground", () => {
  const strip = app.cardPatternStrip();
  const rects = strip.findAll((n) => n.tag === "rect");
  const tileRects = strip.findAll((n) => n.tag === "pattern")[0].findAll((n) => n.tag === "rect");
  assert(tileRects.length > 0);
  for (const r of tileRects) assert.strictEqual(r.getAttribute("class"), "px-k", "outline colour from the theme, no fixed fill");
  assert(!tileRects.some((r) => r.getAttribute("fill")), "no fixed-colour ground");
  // 4 crosses, each one row of three, plus a one-cell row above and below: 12 runs of cells in the tile
  assert.strictEqual(tileRects.length, 12);
  assert.strictEqual(tileRects.reduce((n, r) => n + Number(r.getAttribute("width")), 0), 20);
  assert.strictEqual(rects.length, tileRects.length + 1, "the tile's rects plus the one rect that repeats it");
  assert.strictEqual(strip.getAttribute("aria-hidden"), "true", "decoration");
});

test("the strip is still drawn on a role card's back", () => {
  assert(/el\("div", \{ class: "rcard-pattern", "aria-hidden": "true" \}, cardPatternStrip\(\)\)/.test(APP_SRC));
});

test("opacity: the crosses are >= 3:1 on every camp's card in both themes (graphics, rule 1.6)", () => {
  const m = CSS_SRC.match(/\.rcard-pattern \.card-pattern \{[^}]*opacity:\s*([0-9.]+)/);
  assert(m, "the rule is there");
  const a = Number(m[1]);
  assert(a > 0 && a <= 1);
  const frames = { light: ["#fffbeb", "#f0fdfa", "#f0f9ff", "#faf5ff"], dark: ["#292315", "#142522", "#14232b", "#24182e"] };
  const outline = { light: "#18181b", dark: "#f8fafc" };
  // the CSS holds the same card grounds and outline colours this test measures against
  for (const bg of [...frames.light, ...frames.dark]) assert(CSS_SRC.includes(`--card-frame-bg: ${bg};`), bg);
  assert(/\.px-k \{ fill: #18181b; \}/.test(CSS_SRC) && /\.px-k \{ fill: #f8fafc; \}/.test(CSS_SRC));
  const seen = [];
  for (const mode of ["light", "dark"]) for (const bg of frames[mode]) {
    const shown = blend(outline[mode], bg, a);
    const r = ratioOf(shown, bg);
    seen.push(`${mode} ${bg}: ${r.toFixed(2)}`);
    assert(r >= 3, `${mode} ${bg}: ${r.toFixed(2)} at opacity ${a}`);
  }
  if (process.env.P15_LOG) console.log(`opacity ${a}\n` + seen.join("\n"));
});

test("opacity: it was not made weaker than the v4 pattern's .4, which measured 2.5:1 in the light theme", () => {
  const a = Number(CSS_SRC.match(/\.rcard-pattern \.card-pattern \{[^}]*opacity:\s*([0-9.]+)/)[1]);
  assert(a > 0.4);
  assert(ratioOf(blend("#18181b", "#fffbeb", 0.4), "#fffbeb") < 3, "the old value really was below 3:1, so the change is needed");
});

test("with VBEAR_FLOW_ART the page's copy is the art's own v5 backPattern", () => {
  const dir = process.env.VBEAR_FLOW_ART;
  if (!dir) { console.log("     (VBEAR_FLOW_ART not set: not compared with the art's cards.json)"); return; }
  const art = JSON.parse(fs.readFileSync(path.join(dir, "cards.json"), "utf8"));
  assert.strictEqual(art.version, "0.8.0-art-5");
  assert.deepStrictEqual(app.CARD_PIXELS.backPattern, art.backPattern.pixel.rows);
});

(async () => {
  const timer = setTimeout(() => { console.error("TIMEOUT"); process.exit(2); }, 60000);
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name); console.log(e && e.stack || e); }
  }
  clearTimeout(timer);
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
