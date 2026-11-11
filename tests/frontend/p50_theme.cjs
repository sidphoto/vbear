// P50-3 (v0.23.0 極簡對話 1, ADR 0015): the look. The base colours of both themes are neutral (no green, no beige) with the plan's values; text keeps at least the contrast it
// had (and reaches 4.5:1 on the surfaces the base colours make); the side bar is one step off the page's colour; the accent green is only the text of the item you are on and
// the main actions (a primary button), not a large background; the status colours, the office and the card colours are untouched; buttons are pills, cards have no shadow
// but keep their border; the home blocks have no card frame; the focus ring is still there.
// Reads web/style.css as text. NOT a browser test.
//
// Run: node tests/frontend/p50_theme.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const CSS = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");

// ---- reading the variables -------------------------------------------------------------------------------------------------
const braceBlock = (src, at) => {          // the text between the { at `at` and its matching }
  let depth = 0;
  for (let i = at; i < src.length; i++) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") { depth -= 1; if (depth === 0) return src.slice(at + 1, i); }
  }
  throw new Error("unbalanced");
};
const vars = (block) => Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
const LIGHT = vars(braceBlock(CSS, CSS.indexOf(":root {") + ":root ".length));
const mediaAt = CSS.indexOf("@media (prefers-color-scheme: dark) {");
const mediaBlock = braceBlock(CSS, mediaAt + "@media (prefers-color-scheme: dark) ".length);
const DARK_MEDIA = vars(braceBlock(mediaBlock, mediaBlock.indexOf(":root:not([data-theme=\"light\"]) {") + ":root:not([data-theme=\"light\"]) ".length));
const DARK = vars(braceBlock(CSS, CSS.indexOf(':root[data-theme="dark"] {') + ':root[data-theme="dark"] '.length));

// ---- contrast ---------------------------------------------------------------------------------------------------------------
const lum = (hex) => {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// what the plan says (light and dark), and what they were before (v0.22.1) for the contrast that must not drop
const WANT_LIGHT = { "--bg": "#ffffff", "--panel": "#ffffff", "--panel-2": "#f5f5f4", "--ink": "#17191a", "--ink-2": "#4b5052", "--ink-3": "#686e70", "--line": "#e6e6e3", "--line-2": "#d6d6d2", "--mute-soft": "#f0f0ee" };
const WANT_DARK = { "--bg": "#111213", "--panel": "#17191a", "--panel-2": "#1e2021", "--ink": "#ecedeb", "--ink-2": "#bfc3c2", "--ink-3": "#8d9394", "--line": "#26282a", "--line-2": "#34373a", "--mute-soft": "#242628" };
const OLD_LIGHT = { bg: "#f4f1ea", panel: "#fffdf8", panel2: "#f8f4ec", mute: "#ebe8e1", ink: "#1f2522", ink2: "#4a524d", ink3: "#737b75" };
const OLD_DARK = { bg: "#151917", panel: "#1c211f", panel2: "#222826", mute: "#2a2f2d", ink: "#e9ece8", ink2: "#bcc3be", ink3: "#8c948f" };
const KEEP = ["--ok", "--ok-soft", "--warn", "--warn-soft", "--bad", "--bad-soft", "--info", "--info-soft", "--mute", "--quest-edge", "--quest-bar", "--quest-ok", "--quest-warn", "--quest-mute",
  "--vn-red", "--vn-on-red", "--vn-red-ink", "--vn-red-deep", "--vn-gold", "--office-outline", "--office-floor", "--office-floor-line", "--office-desk", "--office-box-bg", "--office-box-ink", "--office-box-line", "--gold"];
const OLD_KEPT = {
  light: { "--ok": "#2e7d4f", "--ok-soft": "#e3f1e8", "--warn": "#9a6a00", "--warn-soft": "#fbf0d4", "--bad": "#b3372b", "--bad-soft": "#f8e2de", "--info": "#2f5f8f", "--info-soft": "#e1ebf5", "--mute": "#6b6f6c",
    "--quest-edge": "#8a5a00", "--quest-bar": "#8a5a00", "--quest-ok": "#256a42", "--quest-warn": "#7a5500", "--quest-mute": "#585c59", "--vn-red": "#DA251D", "--vn-on-red": "#ffffff", "--vn-red-ink": "#b3180f",
    "--vn-red-deep": "#7a1d17", "--vn-gold": "#ffcd00", "--office-outline": "#18181b", "--office-floor": "#efe8d8", "--office-floor-line": "#e0d7c2", "--office-desk": "#c9a578", "--office-box-bg": "#f4efe6",
    "--office-box-ink": "#0b0f0e", "--office-box-line": "#0b0f0e", "--gold": "#b7862d" },
  dark: { "--ok": "#74c793", "--ok-soft": "#1d3326", "--warn": "#e4b54f", "--warn-soft": "#3a2f14", "--bad": "#f08a7d", "--bad-soft": "#3d201c", "--info": "#86b4e3", "--info-soft": "#1c2b3b", "--mute": "#9aa09c",
    "--quest-edge": "#e4b54f", "--quest-bar": "#e4b54f", "--quest-ok": "#74c793", "--quest-warn": "#e4b54f", "--quest-mute": "#9aa09c", "--vn-red": "#DA251D", "--vn-on-red": "#ffffff", "--vn-red-ink": "#ff8f85",
    "--vn-red-deep": "#d9776b", "--vn-gold": "#ffcd00", "--office-outline": "#e5e0d5", "--office-floor": "#1f2523", "--office-floor-line": "#262d2a", "--office-desk": "#5a4632", "--office-box-bg": "#f4efe6",
    "--office-box-ink": "#0b0f0e", "--office-box-line": "#0b0f0e", "--gold": "#e0b25c" },
};

// the last rule of a selector (a later rule wins), as { body }
const CSS_PLAIN = CSS.replace(/\/\*[\s\S]*?\*\//g, "");   // no comments (a comment before a rule must not be taken for part of its selector)
const lastRule = (sel) => {
  let found = null;
  for (const m of CSS_PLAIN.matchAll(/(^|\n)([^{}\n@][^{}]*)\{([^{}]*)\}/g)) if (m[2].split(",").some((s) => s.trim() === sel)) found = m[3];
  return found;
};
// the value a property ends up with for a selector: the last rule that sets it
const propOf = (sel, prop) => {
  let found = null;
  for (const m of CSS_PLAIN.matchAll(/(^|\n)([^{}\n@][^{}]*)\{([^{}]*)\}/g)) if (m[2].split(",").some((x) => x.trim() === sel)) { const v = declOf(m[3], prop); if (v !== null) found = v; }
  return found;
};
const declOf = (rule, prop) => { const m = new RegExp(`(?:^|;|\\s)${prop}:\\s*([^;]+)`).exec(rule || ""); return m ? m[1].trim() : null; };

let passed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log("ok   -", name); } catch (e) { console.log("FAIL -", name); console.log((e && e.stack) || e); process.exitCode = 1; }
}

test("the dark theme is the same in the two places that set it (the system's choice and the person's choice)", () => {
  for (const k of Object.keys(WANT_DARK)) assert.strictEqual(DARK_MEDIA[k], DARK[k], k);
  assert.strictEqual(DARK_MEDIA["--side-bg"], DARK["--side-bg"]);
});

test("light: the base colours are the plan's neutral values", () => { for (const [k, v] of Object.entries(WANT_LIGHT)) assert.strictEqual(LIGHT[k], v, k); });
test("dark: the base colours are the plan's neutral values", () => { for (const [k, v] of Object.entries(WANT_DARK)) assert.strictEqual(DARK[k], v, k); });

test("neutral: no green and no beige in the base colours (the three channels are within 10 of each other)", () => {
  for (const [theme, t] of [["light", LIGHT], ["dark", DARK]]) {
    for (const k of [...Object.keys(WANT_LIGHT), "--side-bg"]) {
      const h = t[k].replace("#", "");
      const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
      assert.ok(Math.max(r, g, b) - Math.min(r, g, b) <= 10, `${theme} ${k} ${t[k]}`);
    }
  }
});

test("the side bar is one step off the page's colour in both themes (its own token, --side-bg), and the bar uses it", () => {
  assert.notStrictEqual(LIGHT["--side-bg"], LIGHT["--bg"]);
  assert.notStrictEqual(DARK["--side-bg"], DARK["--bg"]);
  assert.ok(Math.abs(lum(LIGHT["--side-bg"]) - lum(LIGHT["--bg"])) < 0.08, "light: only a step");
  assert.ok(Math.abs(lum(DARK["--side-bg"]) - lum(DARK["--bg"])) < 0.08, "dark: only a step");
  assert.strictEqual(propOf(".side", "background"), "var(--side-bg)");
});

test("contrast: text is at least 4.5:1 on every surface (light and dark), and never lower than it was in v0.22.1", () => {
  for (const [theme, t, old] of [["light", LIGHT, OLD_LIGHT], ["dark", DARK, OLD_DARK]]) {
    const surfaces = { "--bg": old.bg, "--panel": old.panel, "--panel-2": old.panel2, "--mute-soft": old.mute };
    for (const ink of ["--ink", "--ink-2", "--ink-3"]) {
      const oldInk = old[ink.slice(2).replace("-", "")];
      for (const s of ["--bg", "--panel", "--panel-2", "--mute-soft", "--side-bg"]) {
        const now = ratio(t[ink], t[s]);
        assert.ok(now >= 4.5, `${theme} ${ink} on ${s}: ${now.toFixed(2)}`);
        if (surfaces[s]) assert.ok(now >= ratio(oldInk, surfaces[s]) - 0.001, `${theme} ${ink} on ${s} dropped below the old ${ratio(oldInk, surfaces[s]).toFixed(2)}`);
      }
    }
  }
});

test("contrast: the accent as text (the item you are on) and the text of a primary button keep 4.5:1; the focus ring is 3:1 on the page", () => {
  for (const [theme, t] of [["light", LIGHT], ["dark", DARK]]) {
    const accent = (t["--accent"] || (theme === "dark" ? "#7fb8a4" : LIGHT["--accent"]));
    for (const s of ["--bg", "--panel-2", "--mute-soft", "--side-bg"]) assert.ok(ratio(accent, t[s]) >= 4.5, `${theme} accent on ${s}`);
    const accentInk = t["--accent-ink"] || LIGHT["--accent-ink"];
    assert.ok(ratio(accentInk, accent) >= 4.5, `${theme} primary button text`);
    assert.ok(ratio(t["--gold"] || LIGHT["--gold"], t["--bg"]) >= 3, `${theme} focus ring`);
  }
  assert.ok(/:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--gold\)/.test(CSS), "the focus ring is still there");
});

test("the status colours, the office and the card colours are not touched", () => {
  for (const [theme, t] of [["light", LIGHT], ["dark", { ...LIGHT, ...DARK }]]) for (const k of KEEP) assert.strictEqual(t[k], OLD_KEPT[theme][k], `${theme} ${k}`);
});

test("the accent green is not a large background: the item you are on is lit by the text colour alone; the old accent-soft fill of the menu is gone", () => {
  const rules = [...CSS_PLAIN.matchAll(/(^|\n)([^{}\n@][^{}]*)\{([^{}]*)\}/g)].filter((m) => /aria-current="page"/.test(m[2]) && /\.nav|\.new-chat|\.recent-link|\.side/.test(m[2]));
  assert.ok(rules.length >= 3, "the lit-item rules");
  for (const m of rules) assert.ok(!/background:\s*var\(--accent/.test(m[3]), `a lit menu item has a green fill: ${m[2].trim()}`);
  assert.ok(/\.side-panel \.nav a\[aria-current="page"\]\s*\{[^}]*color:\s*var\(--accent\)/.test(CSS));
  const primary = lastRule(".btn.primary");
  assert.ok(primary, ".btn.primary");
  assert.ok(/background:\s*var\(--accent\)/.test(primary), "the primary action keeps the green");
});

test("buttons are pills; a card has no shadow and keeps its border", () => {
  assert.strictEqual(propOf(".btn", "border-radius"), "999px");
  assert.strictEqual(propOf(".card", "box-shadow"), "none");
  assert.strictEqual(propOf(".card", "border"), "1px solid var(--line)", "the border stays");
});

test("the home blocks have no card frame or fill: the steps of a person with no employee are lines, not boxes", () => {
  const step = lastRule(".home-page .home-step");
  assert.ok(/border:\s*0/.test(step) && /background:\s*transparent/.test(step), step);
  assert.ok(!/box-shadow:\s*var/.test(lastRule(".home-block") || ""));
  assert.ok(/\.home-page \.home-steps/.test(CSS), "the steps stand in the same column");
});

test("the shadow token is neutral black, not a warm tone", () => {
  assert.ok(/rgba\(0,\s*0,\s*0/.test(LIGHT["--shadow"]), LIGHT["--shadow"]);
});

test("a marked P50-3 part at the end of the file (after P50-2)", () => {
  assert.ok(CSS.indexOf("/* P50-3") > CSS.indexOf("/* P50-2"));
});

console.log(`\n${passed} passed`);
