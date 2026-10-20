// P12 (v0.8.0): the card feel and the new art. The shields of art v4 (three, coloured by the shield's own tokens), the props
// of the office, the filled team places and the small cards under them, the chip cards of skills, the frame of the starter
// deck and the task card with its three lamps, and the card pool that stays put after a card is placed. The real web/app.js
// on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/p12.cjs   (exit code 0 = pass)
// VBEAR_FLOW_ART=<dir of the art> also compares the page's copy with the art's own cards.json.
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, FETCH_LOG, jsonResponse, setHandler } = h;

const APP_SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const CSS_SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const byData = (root, k, v) => root.findAll((n) => n.getAttribute && n.getAttribute(k) === v);
const byClass = (root, c) => root.findAll((n) => n.hasClass && n.hasClass(c));
const isButton = (label) => (n) => n.tag === "button" && n.textContent === label;
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const closeDialogs = () => { for (const d of h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop"))) d.remove(); };
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const CONTRAST_LOG = [];

// ---- colour helpers (WCAG relative luminance) -----------------------------------------------------------------------
const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const ratioOf = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
function themeTokens() {
  const varsOf = (b) => Object.fromEntries([...b.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
  const light = varsOf(CSS_SRC.slice(CSS_SRC.indexOf(":root {"), CSS_SRC.indexOf("@media (prefers-color-scheme: dark)")));
  const dark = varsOf(CSS_SRC.slice(CSS_SRC.indexOf(":root[data-theme=\"dark\"]"), CSS_SRC.indexOf("* { box-sizing")));
  return { light, dark };
}
// the camp frames of the art (frames.themes), as the cards use them
const FRAMES = {
  light: { anthropic: { bg: "#fffbeb", line: "#78350f", title: "#92400e" }, openai: { bg: "#f0fdfa", line: "#134e4a", title: "#115e59" },
    google: { bg: "#f0f9ff", line: "#0c4a6e", title: "#075985" }, other: { bg: "#faf5ff", line: "#581c87", title: "#6b21a8" } },
  dark: { anthropic: { bg: "#292315", line: "#fbbf24", title: "#fde68a" }, openai: { bg: "#142522", line: "#5eead4", title: "#99f6e4" },
    google: { bg: "#14232b", line: "#7dd3fc", title: "#bae6fd" }, other: { bg: "#24182e", line: "#d8b4fe", title: "#e9d5ff" } },
};
// the art's shieldTokens (cards.json, art v4)
const SHIELD_TOKENS = { light: { K: "#18181b", T: "#0f766e", H: "#e6fffb" }, dark: { K: "#f8fafc", T: "#5eead4", H: "#142522" } };

// ---- C5: the shields, and the rest of the v4 art ---------------------------------------------------------------------
test("C5 the page's art is the art's: shields, office props and desk strip, character for character, when the art is at hand", () => {
  const dir = process.env.VBEAR_FLOW_ART;
  // what v4 says, written out once more here so the check does not rest on a file outside the repo
  assert.deepStrictEqual(app.CARD_PIXELS.shields.recorded, ["KK.KK.KK.KK.", "KHHHHHHHHHHK", "KHHHHHHHHHHK", ".HHHHHHHHHH.", "KHHHHHHHHHHK", "KHHHHHHHHHHK", "..HHHHHHHH..", ".KHHHHHHHHK.", "..KHHHHHHK..", "....HHHH....", "....KHHK....", ".....KK....."]);
  assert.deepStrictEqual(app.CARD_PIXELS.shields.none, ["KKKKKKKKKKKK", "KK.........K", "K.K........K", "K..K.......K", "K...K......K", "K....K.....K", ".K....K...K.", ".K.....K..K.", "..K.....KK..", "...K....K...", "....K..K....", ".....KK....."]);
  assert.strictEqual(app.CARD_PIXELS.shields.enforced[1], "KTTTTTTTTTTK");
  assert.deepStrictEqual(Object.keys(app.CARD_PIXELS.officeProps), ["stationPlan", "stationImpl", "stationReview", "stationMerge", "loungeCoffee"]);
  for (const rows of Object.values(app.CARD_PIXELS.officeProps)) { assert.strictEqual(rows.length, 16); assert(rows.every((r) => r.length === 16)); }
  assert.strictEqual(app.CARD_PIXELS.deskStrip.length, 4);
  assert(app.CARD_PIXELS.deskStrip.every((r) => r.length === 24));
  if (!dir) { console.log("     (VBEAR_FLOW_ART not set: not compared with the art's cards.json)"); return; }
  const art = JSON.parse(fs.readFileSync(path.join(dir, "cards.json"), "utf8"));
  assert.strictEqual(art.version, "0.8.0-art-4", "this is the v4 art");
  const rowsOf = (m) => (Array.isArray(m) ? m : m.rows);
  assert.deepStrictEqual(app.CARD_PIXELS.backPattern, rowsOf(art.backPattern.pixel));
  for (const k of ["enforced", "recorded", "none"]) assert.deepStrictEqual(app.CARD_PIXELS.shields[k], rowsOf(art.shields[k]), `shield ${k}`);
  for (const k of Object.keys(art.icons)) assert.deepStrictEqual(app.CARD_PIXELS.icons[k], rowsOf(art.icons[k]), `icon ${k}`);
  for (const k of Object.keys(art.officeProps)) assert.deepStrictEqual(app.CARD_PIXELS.officeProps[k], rowsOf(art.officeProps[k]), `prop ${k}`);
  assert.deepStrictEqual(app.CARD_PIXELS.deskStrip, rowsOf(art.deskStrip));
  const { themeOverrides, ...base } = art.palette;
  assert.deepStrictEqual(Object.fromEntries(Object.entries(base).filter(([, v]) => v)), app.CARD_PALETTE, "the shared palette, with the new H");
  assert.deepStrictEqual(art.shieldTokens, SHIELD_TOKENS, "the shield tokens this test (and the css) hold");
  assert.deepStrictEqual(themeOverrides, { dark: { K: "#f8fafc" } });
  for (const mode of ["light", "dark"]) for (const camp of Object.keys(FRAMES[mode])) {
    const f = art.frames.themes[mode][camp];
    assert.deepStrictEqual([f.background, f.border, f.title], [FRAMES[mode][camp].bg, FRAMES[mode][camp].line, FRAMES[mode][camp].title], `${mode} ${camp}`);
  }
});

test("C5 the shield's own colours come from the art's shieldTokens, in the light, the automatic dark and the chosen dark theme", () => {
  const rule = (sel) => { const m = new RegExp(`${sel.replace(/[.[\]()*+?^$|\\]/g, "\\$&")} \\{ fill: (#[0-9a-f]{6}); \\}`).exec(CSS_SRC); return m && m[1]; };
  assert.strictEqual(rule(".px-st"), SHIELD_TOKENS.light.T);
  assert.strictEqual(rule(".px-sh"), SHIELD_TOKENS.light.H);
  assert.strictEqual(rule(":root[data-theme=\"dark\"] .px-st"), SHIELD_TOKENS.dark.T);
  assert.strictEqual(rule(":root[data-theme=\"dark\"] .px-sh"), SHIELD_TOKENS.dark.H, "the dark pale inside is dark, not the light #e6fffb (a dark recorded shield must not be one white block)");
  assert.strictEqual(rule(":root:not([data-theme=\"light\"]) .px-st"), SHIELD_TOKENS.dark.T);
  assert.strictEqual(rule(":root:not([data-theme=\"light\"]) .px-sh"), SHIELD_TOKENS.dark.H);
  assert(/\.px-k \{ fill: #18181b; \}/.test(CSS_SRC) && /:root\[data-theme="dark"\] \.px-k \{ fill: #f8fafc; \}/.test(CSS_SRC), "the outline K is the token K in both themes");
  assert(!/\.px-t\b/.test(CSS_SRC), "the shared palette's T is no longer recoloured for everything");
});

test("C5 the drawn shields: K is the theme outline, T and H carry their shield classes, nothing else; the office props keep the shared palette", () => {
  const classes = (svg) => new Set(svg.findAll((n) => n.tag === "rect").map((r) => r.getAttribute("class") || "fixed"));
  assert.deepStrictEqual([...classes(app.cardArt("shields", "enforced"))].sort(), ["px-k", "px-st"]);
  assert.deepStrictEqual([...classes(app.cardArt("shields", "recorded"))].sort(), ["px-k", "px-sh"]);
  assert.deepStrictEqual([...classes(app.cardArt("shields", "none"))], ["px-k"]);
  // a prop's T (the screen, the tick mark) is the palette's, whatever the theme: the shield tokens are not applied to it
  const impl = app.cardArt("officeProps", "stationImpl");
  assert(impl.findAll((n) => n.tag === "rect" && n.getAttribute("fill") === "#0f766e").length > 0);
  assert.strictEqual(impl.findAll((n) => n.tag === "rect" && /px-s[th]/.test(n.getAttribute("class") || "")).length, 0);
  assert.strictEqual(app.cardArt("deskStrip", "deskStrip"), null, "the strip is drawn by its own function");
});

test("C5 shield contrast: the outline against every camp card and the panel, the solid fill and the pale inside against each other, in both themes", () => {
  const t = themeTokens();
  for (const mode of ["light", "dark"]) {
    const tok = SHIELD_TOKENS[mode];
    const grounds = { ...Object.fromEntries(Object.entries(FRAMES[mode]).map(([c, f]) => [c + " card", f.bg])), panel: t[mode].panel, "panel-2": t[mode]["panel-2"] };
    for (const [name, bg] of Object.entries(grounds)) {
      const r = ratioOf(tok.K, bg);
      CONTRAST_LOG.push(`C5 ${mode} shield outline ${tok.K} on ${name} ${bg}: ${r.toFixed(2)}`);
      assert(r >= 3, `${mode} ${name}: ${r.toFixed(2)}`);
      const solid = ratioOf(tok.T, bg);
      CONTRAST_LOG.push(`C5 ${mode} solid fill ${tok.T} on ${name} ${bg}: ${solid.toFixed(2)}`);
      assert(solid >= 3, `${mode} solid ${name}: ${solid.toFixed(2)}`);
    }
    const inner = ratioOf(tok.H, tok.T);
    CONTRAST_LOG.push(`C5 ${mode} pale inside ${tok.H} against the solid fill ${tok.T}: ${inner.toFixed(2)} (the art asks 2:1)`);
    assert(inner >= 2, "the two fills tell apart");
    CONTRAST_LOG.push(`C5 ${mode} dashes ${tok.K} against the pale inside ${tok.H}: ${ratioOf(tok.K, tok.H).toFixed(2)}`);
    assert(ratioOf(tok.K, tok.H) >= 3, "the dashes show against the inside");
  }
  // honest: the dark pale inside is dark (a dashed shield is not a white block on a dark card)
  assert(lum(SHIELD_TOKENS.dark.H) < lum(SHIELD_TOKENS.dark.K));
});

test("C5 still three shields: partial, unverified, unknown and not-granted get none, in the pass and in the legend", () => {
  assert.deepStrictEqual(Object.keys(app.CARD_PIXELS.shields).sort(), ["enforced", "none", "recorded"]);
  for (const level of ["部分強制", "未驗證（此 Claude Code 版本尚未實測）", "未知", "不授予", "partial", "unverified", "", null, undefined]) {
    assert.strictEqual(app.armorShield(level), null, String(level));
  }
  assert.strictEqual(app.armorShield("強制（限已測路徑、版本與執行層）").findAll((n) => n.tag === "svg").length, 1);
  assert.strictEqual(app.armorShieldKind("僅意圖"), "recorded");
  assert.strictEqual(app.armorShieldKind("未限制"), "none");
  // no 'partial' or 'unverified' art has been added to the page
  assert(!/partial:\s*\[|unverified:\s*\[/.test(APP_SRC.slice(APP_SRC.indexOf("const CARD_PIXELS"), APP_SRC.indexOf("const CARD_POSITION_BADGES"))));
  assert(/const PASS_LEGEND_NOTE = "部分擋住、未實測、不明的項目不畫盾牌，以文字為準。";/.test(APP_SRC), "the legend still says it");
  const pv = { derived_labels: { Write: { level: "部分強制" }, Network: { level: "未驗證（此 Claude Code 版本尚未實測）" } }, canonical_paths: { workdir: "/w" } };
  const front = app.passFront(pv);
  assert.strictEqual(front.findAll((n) => n.getAttribute && n.getAttribute("data-shield")).length, 3 /* the legend's three */, "no shield on a line that is partial or untested");
  assert.strictEqual(app.passSummary(pv).lines.filter((l) => l.shield).length, 0);
});

// ---- C6: the office's props and desk strip ---------------------------------------------------------------------------
function officeFixtures() {
  const flow = { id: "flow-000000000001", task_title: "整理首頁文案", task_missing: false, phase: { key: "planning", label: "計畫中", reason: "" },
    attention: false, attention_reason: "", automation: { mode: "manual", held: false, step_label: "" },
    roles: { planner: { name: "CEO", family: "anthropic" }, executor: { name: "工匠", family: "anthropic" }, reviewers: [{ name: "審查員", family: "openai" }] },
    executor_live: { state: "idle", label: "工作中", reason: "", freshness: { state: "fresh", age_s: 3 } }, latest_review: null, binding: { detail: "" } };
  const live = { runtime: { available: true, problems: [] }, sessions: [{ terminal_id: "n-0123456789ab", pane_id: "n-0123456789ab", agent: "claude", status: "working", role_label: "工人",
    title: "做事中", activity: { reason: "", evidence: [] }, project_id: "p1" }], attention: [], projects: [{ project_id: "p1", name: "專案一" }] };
  const profiles = { ok: true, profiles: [{ id: "p-1", name: "角色一", model: { tool: "claude", model_id: "" } }] };
  return app.officeModel(live, { ok: true, flows: [flow] }, profiles);
}
const SELECT = { key: null, select() {}, reloadRoster() {} };

test("C6 each station's title carries its own prop (plan board, build area, review room, merge gate) and the lounge carries the coffee; the words are unchanged", () => {
  const [stations, , lounge] = app.officeSections(officeFixtures(), SELECT, new Set());
  const titles = byClass(stations, "office-station-title");
  assert.strictEqual(titles.length, 4);
  assert.deepStrictEqual(titles.map((t) => t.find((n) => n.hasClass && n.hasClass("office-prop")).getAttribute("data-prop")), ["stationPlan", "stationImpl", "stationReview", "stationMerge"]);
  assert.deepStrictEqual(titles.map(text), ["計畫板", "實作區", "審查室", "合併關卡"], "a prop adds no words and is not what tells the stations apart");
  const loungeTitle = lounge.find((n) => n.tag === "h2");
  assert.strictEqual(text(loungeTitle), "休息室");
  assert.strictEqual(loungeTitle.find((n) => n.hasClass && n.hasClass("office-prop")).getAttribute("data-prop"), "loungeCoffee");
  for (const t of [...titles, loungeTitle]) {
    const prop = t.find((n) => n.hasClass && n.hasClass("office-prop"));
    assert.strictEqual(prop.getAttribute("aria-hidden"), "true", "decoration");
    const svg = prop.find((n) => n.tag === "svg");
    assert.strictEqual(svg.getAttribute("viewBox"), "0 0 16 16");
    assert.strictEqual(svg.getAttribute("width"), "32", "2x");
  }
  assert.deepStrictEqual(Object.keys(app.OFFICE_STATION_PROP), ["board", "build", "review", "gate"]);
  assert(!/<img|url\(/.test(text(stations)));
});

test("C6 a desk's character stands on the art's 24x4 desk strip (3x), the strip is decoration", () => {
  const m = officeFixtures();
  assert.strictEqual(m.desks.length, 1);
  const btn = app.officeDeskButton(m.desks[0], false, false, () => {});
  const top = byClass(btn, "office-desk-top")[0];
  assert.strictEqual(top.getAttribute("aria-hidden"), "true");
  const svg = top.find((n) => n.tag === "svg");
  assert.strictEqual(svg.getAttribute("viewBox"), "0 0 24 4");
  assert.strictEqual(svg.getAttribute("width"), "72");
  assert.strictEqual(svg.getAttribute("height"), "12");
  assert(svg.findAll((n) => n.tag === "rect" && n.getAttribute("class") === "px-k").length > 0, "its outline is the theme's K (light on a dark floor)");
  assert(/\.office-desk-top \{[^}]*width: 72px; height: 12px/.test(CSS_SRC));
});

test("C6 the props are 2x, small, beside the title, and the office never relies on one: the station buttons keep their words and labels", () => {
  const m = officeFixtures();
  const team = m.stations.board.teams[0];
  const b = app.officeTeamButton(team, false, false, () => {});
  assert(text(b).includes("計畫板") || text(b).includes("任務在"));
  assert(!b.find((n) => n.hasClass && n.hasClass("office-prop")), "no prop inside the team button");
  assert(/\.office-station-title \{[^}]*display: flex/.test(CSS_SRC));
});

// ---- run ----------------------------------------------------------------------------------------------------------
(async () => {
  const timer = setTimeout(() => { console.error("TIMEOUT"); process.exit(2); }, 120000);
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name); console.log(e && e.stack || e); }
  }
  clearTimeout(timer);
  if (process.env.P12_CONTRAST_LOG) console.log(CONTRAST_LOG.join("\n"));
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
