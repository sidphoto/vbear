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


// ---- shared: the camp frames, as the page's css holds them ------------------------------------------------------------
const THEME_INK = { light: { ink: "#1f2522", ink2: "#4a524d" }, dark: { ink: "#e9ece8", ink2: "#bcc3be" } };
const CAMPS = ["anthropic", "openai", "google", "other"];
function cssVars(block) { return Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]])); }
function ruleLine(prefix, sel) { return CSS_SRC.split("\n").find((l) => l.startsWith(prefix + sel + " {")); }
// the task card's tokens (art cardShapes.task), as the page's css holds them
function dossierTokens() {
  const light = CSS_SRC.match(/\n:root \{ (--dossier-head:[^}]*)\}/);
  const dark = CSS_SRC.match(/\n:root\[data-theme="dark"\] \{ (--dossier-head:[^}]*)\}/);
  return { light: cssVars(light[1]), dark: cssVars(dark[1]) };
}
const ART_TASK = {
  light: { header: "#e8e3d8", headerText: "#1f2522", draft: "#626b66", inProgress: "#1f2522", yourTurn: "#da251d", complete: "#16815e", active: "#b45309", notStarted: "#626b66" },
  dark: { header: "#343b37", headerText: "#e9ece8", draft: "#a7b0aa", inProgress: "#e9ece8", yourTurn: "#ff6b61", complete: "#45d09a", active: "#fbbf24", notStarted: "#a7b0aa" },
};

const mkCard = (id, name, tool, extra = {}) => ({ id, name, profession_role_id: null, model: { tool, model_id: "" }, equipped_skill_ids: [],
  permission_intents: { read: "allow", write: "deny", test: "deny", deploy: "deny" }, enabled: true, created_at: 1, updated_at: 1, revision: "1".repeat(64),
  _unresolved: { profession: false, skills: [] }, ...extra });
const CEO = mkCard("p-ceo", "CEO", "claude");
const MAKER = mkCard("p-maker", "工匠", "claude");
const REVIEWER = mkCard("p-rev", "審查員", "codex");
const SHARED = mkCard("p-shared", "共用卡", "shared");
const PROFILES = [CEO, MAKER, REVIEWER, SHARED];
const REPO = "/Users/tester/projects/demo";
const flowOf = (phaseKey, over = {}) => ({ id: "flow-0123456789ab", task_id: "task-1", task_title: "Demo", task_missing: false, created_at: 1,
  roles: {
    planner: { name: "CEO", family: "anthropic", profile_id: "p-ceo", profile_snapshot: { name: "CEO", tool: "claude", model_id: "", revision: "1".repeat(64) } },
    executor: { name: "工匠", family: "anthropic", workdir: REPO, session_id: "n-0123456789ab", profile_id: "p-maker", profile_snapshot: { name: "工匠", tool: "claude", model_id: "", revision: "1".repeat(64) } },
    reviewers: [{ name: "審查員", family: "openai", profile_id: "p-rev", profile_snapshot: { name: "審查員", tool: "codex", model_id: "", revision: "1".repeat(64) } }],
  },
  phase: { key: phaseKey, label: "階段", reason: "" }, automation: { mode: "manual" }, events: [], ...over });

// ---- C1 / C2: the team places and the small cards of the pool ----------------------------------------------------------
test("C1 a place with a card takes that card's camp frame and the badge of the place; a vacant place stays as it was", () => {
  const b = app.teamBoard({ task: { id: "task-1", title: "Demo", status: "draft", workdir: REPO }, flow: flowOf("implementing"), profiles: PROFILES, catalog: null, gitState: "git" });
  const slot = (k) => byData(b.node, "data-slot", k)[0];
  assert.deepStrictEqual(["planner", "executor", "reviewer1"].map((k) => slot(k).getAttribute("data-camp")), ["anthropic", "anthropic", "openai"]);
  for (const k of ["planner", "executor", "reviewer1"]) assert(slot(k).hasClass("camp-frame") && slot(k).hasClass("ts-filled"), k);
  const glyphOf = (k) => slot(k).find((n) => n.hasClass && n.hasClass("pos-glyph"));
  assert.deepStrictEqual(["planner", "executor", "reviewer1"].map((k) => text(glyphOf(k))), ["規", "執", "審"], "the badge is the place's position, not a guess about the card");
  assert.strictEqual(glyphOf("planner").getAttribute("aria-hidden"), "true", "the words beside it say the same");
  const empty = slot("reviewer2");
  assert(!empty.hasClass("camp-frame") && empty.getAttribute("data-camp") === null);
  assert.strictEqual(empty.find((n) => n.hasClass && n.hasClass("pos-glyph")), null, "no badge on an empty place");
  assert(empty.hasClass("ts-vacant"));
  assert.strictEqual(text(slot("planner").find((n) => n.tag === "strong")), "規劃位", "the place's own words are still there");
});

test("C1 a hand-written role (no card) and a role of a family this page does not know are 'other', not a camp it was not", () => {
  assert.strictEqual(app.campKeyOf({ name: "手寫", family: "mystery" }), "other");
  assert.strictEqual(app.campKeyOf({ name: "手寫" }), "other");
  assert.strictEqual(app.campKeyOf({ family: "openai" }), "openai");
  assert.strictEqual(app.campKeyOf({ profile_snapshot: { tool: "codex" } }), "openai");
  assert.strictEqual(app.campKeyOf({ model: { tool: "claude" } }), "anthropic");
  assert.strictEqual(app.campKeyOf({ tool: "shared" }), "other");
  assert.strictEqual(app.campKeyOf(null), "other");
});

test("C1 a place that does not count keeps its red frame over the camp frame", () => {
  const f = flowOf("implementing");
  f.roles.reviewers = [{ name: "也是工匠", family: "anthropic", profile_id: "p-maker", profile_snapshot: { name: "也是工匠", tool: "claude", model_id: "", revision: "1".repeat(64) } }];
  const b = app.teamBoard({ task: { id: "task-1", title: "Demo", status: "draft", workdir: REPO }, flow: f, profiles: PROFILES, catalog: null, gitState: "git" });
  const rev = byData(b.node, "data-slot", "reviewer1")[0];
  assert.strictEqual(rev.getAttribute("data-state"), "problem");
  assert(rev.hasClass("ts-bad") && rev.hasClass("camp-frame"));
  assert(/\.team-slot\.ts-filled\.camp-frame\.ts-bad \{ border-color: var\(--bad\); \}/.test(CSS_SRC));
  assert(/\.team-slot\.ts-bad \{[^}]*border-left-width: 6px/.test(CSS_SRC), "and the thick edge is still not only a colour");
});

test("C2 the pool under the places is small cards: camp frame, the name, the tool, the position badge; picking and dragging are as before", () => {
  app.setCardPosition("p-ceo", "planner");
  app.setCardPosition("p-rev", "reviewer");
  app.setCardPosition("p-maker", null);
  const b = app.teamBoard({ task: { id: "task-9", title: "Demo", status: "draft", workdir: REPO }, flow: null, profiles: PROFILES, catalog: null, gitState: "git" });
  const chip = (id) => byData(b.node, "data-card", id)[0];
  assert.deepStrictEqual(PROFILES.map((p) => chip(p.id).getAttribute("data-camp")), ["anthropic", "anthropic", "openai", "other"]);
  for (const p of PROFILES) { assert(chip(p.id).hasClass("camp-frame") && chip(p.id).hasClass("ts-chip")); assert.strictEqual(chip(p.id).getAttribute("draggable"), "true"); }
  const glyph = (id) => chip(id).find((n) => n.hasClass && n.hasClass("pos-glyph"));
  assert.strictEqual(text(glyph("p-ceo")), "規");
  assert.strictEqual(text(glyph("p-rev")), "審");
  assert.strictEqual(text(glyph("p-maker")), "？", "a card with no suggested position says so");
  assert.strictEqual(glyph("p-maker").getAttribute("data-pos"), "unspecified");
  assert(/位置未指定/.test(chip("p-maker").getAttribute("title")));
  assert(/你建議放「規劃」位/.test(chip("p-ceo").getAttribute("title")));
  assert(text(chip("p-ceo")).includes("CEO") && text(chip("p-ceo")).includes("Claude"), "name and tool are words");
  assert.strictEqual(chip("p-ceo").getAttribute("aria-pressed"), "false");
  chip("p-ceo").click();
  assert.strictEqual(byData(b.node, "data-card", "p-ceo")[0].getAttribute("aria-pressed"), "true", "a click still picks the card up");
  const planner = byData(b.node, "data-slot", "planner")[0];
  planner.find((n) => n.tag === "button" && n.getAttribute("data-act") === "slot").click();
  assert.strictEqual(b.state.slots.planner.profile_id, "p-ceo", "and a place takes it");
  assert.strictEqual(byData(b.node, "data-slot", "planner")[0].getAttribute("data-camp"), "anthropic");
});

test("C1 C2 css: the camp frame rules for the places and cards are the art's frames, the same ones the role card has, in the three theme forms", () => {
  for (const prefix of ["", "  :root:not([data-theme=\"light\"]) ", ":root[data-theme=\"dark\"] "]) {
    for (const camp of CAMPS) {
      const rcard = ruleLine(prefix, `.rcard[data-camp="${camp}"]`);
      const frame = ruleLine(prefix, `.camp-frame[data-camp="${camp}"]`);
      assert(rcard && frame, `${prefix}${camp}`);
      assert.strictEqual(frame.replace(".camp-frame[", ".rcard["), rcard, `${prefix}${camp}: the shared frame is the role card's frame`);
    }
  }
});

test("C1 C2 C3 text and frame contrast on every camp card in both themes: ink 4.5, the quiet ink 4.5, the title 4.5, the frame line 3 (values logged)", () => {
  const t = themeTokens();
  for (const mode of ["light", "dark"]) for (const camp of CAMPS) {
    const f = FRAMES[mode][camp];
    for (const [what, fg, min] of [["ink", THEME_INK[mode].ink, 4.5], ["quiet ink-2", THEME_INK[mode].ink2, 4.5], ["title", f.title, 4.5], ["frame line", f.line, 3]]) {
      const r = ratioOf(fg, f.bg);
      CONTRAST_LOG.push(`C1-3 ${mode} ${camp} ${what} ${fg} on ${f.bg}: ${r.toFixed(2)}`);
      assert(r >= min, `${mode} ${camp} ${what}: ${r.toFixed(2)}`);
    }
    const onPage = ratioOf(f.line, t[mode].bg);
    CONTRAST_LOG.push(`C1-3 ${mode} ${camp} frame line ${f.line} on the page ${t[mode].bg}: ${onPage.toFixed(2)}`);
    assert(onPage >= 3, `${mode} ${camp} frame on the page: ${onPage.toFixed(2)}`);
  }
  assert.strictEqual(t.light.ink, THEME_INK.light.ink);
  assert.strictEqual(t.dark["ink-2"], THEME_INK.dark.ink2);
  assert(/\.camp-frame \.muted, \.camp-frame \.card-sub, \.camp-frame\.card p \{ color: var\(--ink-2\); \}/.test(CSS_SRC), "the quiet text on a camp card is the second ink");
});

// ---- C3: the skill chip cards ---------------------------------------------------------------------------------------
const skillOf = (tool, over = {}) => ({ skill_id: "s-" + tool, name: "pdf", invoke_name: "pdf", tool, scope: "user", activation: "active", categories: [], duplicate_of: [], missing_files: [], ...over });

test("C3 a skill card in the library is a chip card in the colours of its tool; the tool is still said in words", () => {
  for (const [tool, camp, word] of [["claude", "anthropic", "Claude"], ["codex", "openai", "Codex"], ["shared", "other", ""]]) {
    const c = app.skillCard(skillOf(tool));
    assert(c.hasClass("skill-chip") && c.hasClass("camp-frame") && c.hasClass("card"), tool);
    assert.strictEqual(c.getAttribute("data-camp"), camp, tool);
    if (word) assert(text(c).includes(word), `${tool}: the tag says the tool, the colour is not the only cue`);
    assert(c.getAttribute("href").startsWith("#/skills/"), "still a link to the skill");
  }
  assert.strictEqual(app.skillCard(skillOf("mystery-tool")).getAttribute("data-camp"), "other", "a tool this page does not know is not given a camp");
});

test("C3 the chip card's css: the top right corner cut 12px, a band 4px across the top in the camp's frame colour; the card's dashed/solid meaning is not touched", () => {
  assert(/\.skill-chip \{[^}]*clip-path: polygon\(0 0, calc\(100% - 12px\) 0, 100% 12px, 100% 100%, 0 100%\)/.test(CSS_SRC));
  assert(/\.skill-chip::before \{[^}]*height: 4px; background: var\(--card-frame-line/.test(CSS_SRC));
  assert(/\.skill-chip::after \{[^}]*width: 12px; height: 12px/.test(CSS_SRC), "the cut edge has a line along it");
  assert(/forced-colors: active\) \{ \.skill-chip \{ clip-path: none;/.test(CSS_SRC), "no clipped frame in forced colours");
  const chipRule = /\.skill-chip \{([^}]*)\}/.exec(CSS_SRC)[1];
  assert(!/border(-style)?:\s*[^;]*(solid|dashed)/.test(chipRule), "the chip does not reset the border style: a card on the back is dashed when collected and solid when active");
  assert(/\.rcard-slot \{[^}]*border: 2px dashed/.test(CSS_SRC) && /\.rcard-slot-active \{ border-style: solid; \}/.test(CSS_SRC));
});

test("C3 the skill slots on the back of a role card are chip cards, and 收藏中 / 生效中 are still their words and their dashed / solid", () => {
  const p = mkCard("p-1", "卡", "claude", { equipped_skill_ids: ["a", "b"] });
  const rows = app.cardSlots(p, { state: "ok", data: { skills: { items: [{ skill_id: "a", name: "A", will_load: true }, { skill_id: "b", name: "B", will_load: false }] } } }, null).rows;
  assert.deepStrictEqual(rows.map((r) => r.state), ["active", "collected"]);
  assert(/class: `rcard-slot skill-chip rcard-slot-\$\{r\.state\}`/.test(APP_SRC));
});

// ---- C4: the starter deck and the task card ----------------------------------------------------------------------------
test("C4 each starter card is a framed card of its camp with the badge of its position", () => {
  closeDialogs();
  const deck = [{ key: "a", name: "規劃者", tool: "claude", position: "planner", permission_intents: { read: "allow", write: "deny", test: "deny", deploy: "deny" } },
    { key: "b", name: "審查者", tool: "codex", position: "reviewer", permission_intents: { read: "allow", write: "deny", test: "deny", deploy: "deny" } }];
  app.openStarterDeck({ catalog: { starter_deck: deck, codex_installed: true }, profiles: [], onSaved() {} });
  const d = dialog();
  const rows = byData(d, "data-deck", "a").concat(byData(d, "data-deck", "b"));
  assert.deepStrictEqual(rows.map((r) => r.getAttribute("data-camp")), ["anthropic", "openai"]);
  assert(rows.every((r) => r.hasClass("camp-frame")));
  assert.deepStrictEqual(rows.map((r) => text(r.find((n) => n.hasClass && n.hasClass("pos-glyph")))), ["規", "審"]);
  assert(text(rows[0]).includes("規劃") && text(rows[1]).includes("審查"), "and the words are still there");
  closeDialogs();
});

test("C4 the three lights of a task card follow the flow's phase and nothing else: past, now, not yet, and empty when there is no data", () => {
  const states = (f) => app.taskLightStates(f);
  assert.deepStrictEqual(states(flowOf("planning")), ["active", "none", "none"]);
  assert.deepStrictEqual(states(flowOf("awaiting_approval")), ["active", "none", "none"], "waiting for your approval is still the plan's light");
  assert.deepStrictEqual(states(flowOf("implementing")), ["complete", "active", "none"]);
  assert.deepStrictEqual(states(flowOf("needs_fix")), ["complete", "active", "none"], "a fix is the executor's turn");
  assert.deepStrictEqual(states(flowOf("in_review")), ["complete", "complete", "active"]);
  assert.deepStrictEqual(states(flowOf("review_stale")), ["complete", "complete", "active"]);
  for (const k of ["awaiting_merge", "review_unverified", "awaiting_push", "done"]) assert.deepStrictEqual(states(flowOf(k)), ["complete", "complete", "complete"], k);
  for (const bad of [null, undefined, {}, flowOf("some_new_phase"), flowOf(""), "x"]) assert.deepStrictEqual(states(bad), ["empty", "empty", "empty"], JSON.stringify(bad));
  const node = app.taskLights(null);
  assert.strictEqual(node.findAll((n) => n.hasClass && n.hasClass("task-light")).length, 3);
  assert.deepStrictEqual(node.findAll((n) => n.hasClass && n.hasClass("task-light")).map(text), ["規", "執", "審"]);
  assert(node.findAll((n) => n.hasClass && n.hasClass("task-light")).every((n) => n.getAttribute("data-state") === "empty" && /沒有資料/.test(n.getAttribute("aria-label"))), "no data: an empty light that says so");
  const live = app.taskLights(flowOf("in_review")).findAll((n) => n.hasClass && n.hasClass("task-light"));
  assert.deepStrictEqual(live.map((n) => n.getAttribute("aria-label")), ["規劃：已過", "執行：已過", "審查：目前"], "a light says its state in words, not only in colour");
  assert(/不代表當時有記錄到核准/.test(app.taskLights(flowOf("planning")).getAttribute("aria-label")), "and says it is a place, not a record of approval");
});

test("C4 the task card on the front: a folder's head with the title, the mark and the lights; the frame says draft, under way, or your turn", () => {
  const task = { id: "task-1", title: "整理文案", status: "draft", workdir: "" };
  const front = (t, flows) => app.taskFrontCard(t, { flows, tasks: [t] });
  const noFlow = front(task, []);
  assert(noFlow.hasClass("task-dossier"));
  assert.strictEqual(noFlow.getAttribute("data-tstate"), "draft", "a mark of draft and no flow: dashed");
  const head = noFlow.find((n) => n.hasClass && n.hasClass("task-dossier-head"));
  assert(head && text(head).includes("整理文案"));
  assert.strictEqual(head.findAll((n) => n.hasClass && n.hasClass("task-light-empty")).length, 3, "no flow: the lights are empty");
  const going = front({ ...task, status: "in_progress" }, [flowOf("implementing")]);
  assert.strictEqual(going.getAttribute("data-tstate"), "progress");
  assert.deepStrictEqual(going.findAll((n) => n.hasClass && n.hasClass("task-light")).map((n) => n.getAttribute("data-state")), ["complete", "active", "none"]);
  const turn = front(task, [flowOf("awaiting_approval", { attention: true })]);
  assert.strictEqual(turn.getAttribute("data-tstate"), "turn");
  assert.strictEqual(app.taskDossierState({ status: "closed" }, null), "plain");
  assert.strictEqual(app.taskDossierState({ status: "handed_off" }, flowOf("done")), "plain", "a flow that is done is not 'under way'");
  assert.strictEqual(app.taskDossierState({ status: "draft" }, flowOf("planning")), "progress", "the flow's phase, not the generic mark, says it is under way");
  assert.strictEqual(app.taskDossierState({ status: "draft" }, flowOf("planning", { attention: false })), "progress");
  // the status and the explanation are still on the card (A5 words are not lost)
  assert(text(noFlow).includes("標記") || text(noFlow).includes("草稿"));
});

test("C4 the task card's css holds the art's cardShapes.task, and the frame is not colour alone: dashed, solid, thick", () => {
  const tok = dossierTokens();
  for (const mode of ["light", "dark"]) {
    const a = ART_TASK[mode];
    assert.deepStrictEqual(tok[mode], { "dossier-head": a.header, "dossier-head-ink": a.headerText, "dossier-draft": a.draft, "dossier-progress": a.inProgress, "dossier-turn": a.yourTurn,
      "lamp-complete": a.complete, "lamp-active": a.active, "lamp-none": a.notStarted }, mode);
  }
  const auto = CSS_SRC.match(/@media \(prefers-color-scheme: dark\) \{ :root:not\(\[data-theme="light"\]\) \{ (--dossier-head:[^}]*)\} \}/);
  assert.deepStrictEqual(cssVars(auto[1]), tok.dark, "the automatic dark theme has the same");
  assert(/\.task-dossier\[data-tstate="draft"\] \{ border: 2px dashed var\(--dossier-draft\)/.test(CSS_SRC));
  assert(/\.task-dossier\[data-tstate="progress"\] \{ border: 2px solid var\(--dossier-progress\)/.test(CSS_SRC));
  assert(/\.task-dossier\[data-tstate="turn"\] \{ border: 3px solid var\(--dossier-turn\)/.test(CSS_SRC));
  assert(/\.task-light-complete \{[^}]*color: var\(--panel\)/.test(CSS_SRC), "the glyph on a filled lamp is the card's ground");
  assert(/\.task-light-active \{[^}]*box-shadow/.test(CSS_SRC) && /\.task-light-empty \{ border-style: dotted/.test(CSS_SRC), "now and empty differ by shape too");
  if (process.env.VBEAR_FLOW_ART) {
    const art = JSON.parse(fs.readFileSync(path.join(process.env.VBEAR_FLOW_ART, "cards.json"), "utf8")).cardShapes;
    for (const mode of ["light", "dark"]) {
      const t = art.task[mode], l = art.task.progressLights[mode];
      assert.deepStrictEqual({ header: t.header, headerText: t.headerText, draft: t.draft, inProgress: t.inProgress, yourTurn: t.yourTurn, complete: l.complete, active: l.active, notStarted: l.notStarted }, ART_TASK[mode], mode);
    }
    assert.strictEqual(art.skill.cornerCut, 12);
    assert.strictEqual(art.skill.campBandHeight, 4);
  }
});

test("C4 task card contrast, light and dark: the head's text 4.5, the lights and the frames 3 (values logged)", () => {
  const t = themeTokens();
  const tok = dossierTokens();
  for (const mode of ["light", "dark"]) {
    const v = tok[mode];
    const ground = t[mode].panel;
    const rows = [
      ["head text on the head", v["dossier-head-ink"], v["dossier-head"], 4.5],
      ["lamp complete on the head", v["lamp-complete"], v["dossier-head"], 3],
      ["lamp active on the head", v["lamp-active"], v["dossier-head"], 3],
      ["lamp not yet on the head", v["lamp-none"], v["dossier-head"], 3],
      ["glyph on a complete lamp", t[mode].panel, v["lamp-complete"], 4.5],
      ["draft frame on the card", v["dossier-draft"], ground, 3],
      ["under-way frame on the card", v["dossier-progress"], ground, 3],
      ["your-turn frame on the card", v["dossier-turn"], ground, 3],
      ["head on the card (the head reads as a head)", v["dossier-head"], ground, 1.1],
    ];
    for (const [what, fg, bg, min] of rows) {
      const r = ratioOf(fg, bg);
      CONTRAST_LOG.push(`C4 ${mode} ${what} ${fg} on ${bg}: ${r.toFixed(2)}`);
      assert(r >= min, `${mode} ${what}: ${r.toFixed(2)}`);
    }
  }
});

// ---- C7: the card pool stays put after a card is put ---------------------------------------------------------------
test("C7 putting a card on a task card stays on the page: the dialog says where, offers another place and a link to the task card", async () => {
  closeDialogs();
  global.location.hash = "";
  let flow = flowOf("implementing");
  const taskList = [{ id: "task-1", title: "整理文案", status: "in_progress", workdir: REPO, created_at: 1 }];
  const roleBodies = [];
  setHandler((url, opts) => {
    if (url === "/api/tasks") return jsonResponse({ ok: true, tasks: taskList });
    if (url === "/api/flows") return jsonResponse({ ok: true, flows: [flow] });
    if (url === `/api/flows/${flow.id}/roles` && opts.method === "POST") {
      const body = JSON.parse(opts.body);
      roleBodies.push(body);
      flow = { ...flow, roles: { planner: body.roles.planner ? { ...flow.roles.planner, ...body.roles.planner } : flow.roles.planner, executor: flow.roles.executor,
        reviewers: body.roles.reviewers || flow.roles.reviewers } };
      return jsonResponse({ ok: true, flow });
    }
    return null;
  });
  const placed = [];
  app.openPlaceDialog(REVIEWER, { profiles: PROFILES, taskId: "task-1", onPlaced: () => placed.push(1) });
  await settle();
  const d1 = dialog();
  byData(d1, "data-place-slot", "reviewer2")[0].click();
  d1.find((n) => n.tag === "button" && n.getAttribute("data-act") === "place").click();
  await settle();
  assert.strictEqual(roleBodies.length, 1);
  assert.strictEqual(global.location.hash, "", "the page did not move");
  const d = dialog();
  assert(d, "the dialog is still there");
  const done = byData(d, "data-place", "done")[0];
  assert.strictEqual(text(done), "已放到「整理文案」的第二位審查，隊伍已儲存。 還要放其他位置嗎？");
  assert.strictEqual(placed.length, 1, "the page that opened the dialog is told once");
  const open = d.find((n) => n.tag === "a" && n.getAttribute("data-act") === "open-task");
  assert.strictEqual(open.getAttribute("href"), "#/workbench?task=task-1");
  assert.strictEqual(text(open), "打開任務卡");
  const again = d.find((n) => n.tag === "button" && n.getAttribute("data-act") === "again");
  again.click();
  await settle();
  const d2 = dialog();
  assert(!byData(d2, "data-place", "done").length, "back to choosing");
  assert.strictEqual(byData(d2, "data-place-task", "task-1")[0].getAttribute("aria-pressed"), "true", "the same task card is still the one chosen");
  assert(byData(d2, "data-place-slot", "planner")[0], "its places are listed again");
  assert.strictEqual(d2.find((n) => n.tag === "button" && n.getAttribute("data-act") === "place").disabled, true, "and a place has to be chosen again");
  byData(d2, "data-place-slot", "reviewer1")[0].click();
  d2.find((n) => n.tag === "button" && n.getAttribute("data-act") === "place").click();
  await settle();
  assert.strictEqual(roleBodies.length, 2);
  assert.strictEqual(roleBodies[1].roles.reviewers.length, 2, "the second put is made on what the server now holds (the first one is still there)");
  assert.strictEqual(roleBodies[1].roles.reviewers[1].profile_id, "p-rev", "the first put stays in its place");
  assert.strictEqual(global.location.hash, "");
  const done2 = dialog().find((n) => n.tag === "button" && n.getAttribute("data-act") === "close");
  done2.click();
  assert(!dialog(), "完成 closes it, and still nowhere else");
  assert.strictEqual(global.location.hash, "");
  setHandler(() => null);
});

test("C7 a task card with no team yet gets the card in its draft, and the dialog says it is only a draft and what is still missing", async () => {
  closeDialogs();
  global.location.hash = "";
  app.teamDraftWrite("task-2", { planner: null, executor: null, reviewer1: null, reviewer2: null });
  setHandler((url) => {
    if (url === "/api/tasks") return jsonResponse({ ok: true, tasks: [{ id: "task-2", title: "新卡", status: "draft", workdir: REPO, created_at: 1 }] });
    if (url === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    return null;
  });
  app.openPlaceDialog(CEO, { profiles: PROFILES, taskId: "task-2" });
  await settle();
  byData(dialog(), "data-place-slot", "planner")[0].click();
  dialog().find((n) => n.tag === "button" && n.getAttribute("data-act") === "place").click();
  await settle();
  const done = byData(dialog(), "data-place", "done")[0];
  assert(text(done).startsWith("已放進「新卡」的草稿：規劃位。"), text(done));
  assert(text(byData(dialog(), "data-place", "done-note")[0]).includes("這只是草稿，隊伍還沒建立；還差："));
  assert.strictEqual(global.location.hash, "");
  assert(!FETCH_LOG.some((c) => c.method === "POST" && /flows/.test(c.url) && c.url.includes("task-2")), "nothing was written to a flow");
  closeDialogs();
  setHandler(() => null);
});

test("C7 the place dialog never moves the page by itself any more (source)", () => {
  const block = APP_SRC.slice(APP_SRC.indexOf("function openPlaceDialog("), APP_SRC.indexOf("// One line for a flow's next step"));
  assert(!/location\.hash\s*=/.test(block));
  assert(/data-act": "open-task", href: `#\/workbench\?task=\$\{encodeURIComponent\(d\.taskId\)\}`/.test(block));
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
