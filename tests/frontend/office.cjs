// The pixel office (design office v1.3): the pure functions — station, species, sprite, weapons, the model, the key
// that decides a repaint, the selection that survives it, the list for a phone, the counts, the errors.
// The real web/app.js on a synthetic DOM. Run: node tests/frontend/office.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const root = path.join(__dirname, "..", "..", "web");

global.document.querySelector = () => null;

// ---- fixtures -------------------------------------------------------------------------------------------------

const PHASE_LABEL = { planning: "計畫中", awaiting_approval: "等核准", implementing: "實作中", in_review: "審查第 2 輪",
  needs_fix: "等修正", awaiting_merge: "審查通過・等合併", review_stale: "審查結果已過期",
  review_unverified: "審查通過・無法核對 HEAD", awaiting_push: "等 push", done: "完成" };
const PHASES = Object.keys(PHASE_LABEL);
let flowN = 0;
function flow(key, over = {}) {
  flowN += 1;
  const id = "flow-" + String(flowN).padStart(12, "0");
  return {
    id, task_title: `任務 ${flowN}`, task_missing: false,
    phase: { key, label: PHASE_LABEL[key] || "新的階段", reason: `${PHASE_LABEL[key] || "新的階段"}的說明` },
    attention: false, attention_reason: "",
    automation: { mode: "manual", held: false, step_label: "" },
    roles: { planner: { name: "規劃者", family: "anthropic", family_label: "Anthropic（Claude）" },
      executor: { name: "Claude Code", family: "anthropic", family_label: "Anthropic（Claude）", model: "haiku" },
      reviewers: [{ name: "Codex", family: "openai", family_label: "OpenAI（Codex）", model: "gpt-6-luna" }] },
    executor_live: { state: "idle", label: "工作中", reason: "", freshness: { state: "fresh", age_s: 3 } },
    latest_review: null, binding: { detail: "" },
    ...over,
  };
}
function bound(f, sessionId, live) {
  return { ...f, roles: { ...f.roles, executor: { ...f.roles.executor, session_id: sessionId } },
    executor_live: live || f.executor_live };
}
function session(id, over = {}) {
  return { terminal_id: id, pane_id: id, agent: "claude", status: "working", role_label: "Claude 工人",
    title: "做事中", activity: { reason: "標題顯示工作中", evidence: [] }, project_id: "p1", ...over };
}
function live(over = {}) {
  return { runtime: { available: true, problems: [] }, sessions: [], attention: [],
    projects: [{ project_id: "p1", name: "專案一" }], ...over };
}
const flowsOf = (flows, over = {}) => ({ ok: true, flows, ...over });
const profile = (id, tool, over = {}) => ({ id, name: `角色 ${id}`, model: { tool, model_id: "" }, ...over });
const profilesOf = (profiles, over = {}) => ({ ok: true, profiles, ...over });
const model = (l, f, p, ov) => app.officeModel(l || live(), f || flowsOf([]), p || profilesOf([]), ov);
const allTeams = (m) => ["board", "build", "review", "gate"].flatMap((st) => m.stations[st].teams);
const clone = (x) => JSON.parse(JSON.stringify(x));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- stations -------------------------------------------------------------------------------------------------

test("every phase has its station; an unknown phase goes to the plan board; done is not shown", () => {
  const want = { planning: "board", awaiting_approval: "board", implementing: "build", needs_fix: "build",
    in_review: "review", review_stale: "review", review_unverified: "review", awaiting_merge: "gate",
    awaiting_push: "gate" };
  assert.strictEqual(PHASES.length, 10);
  for (const [key, st] of Object.entries(want)) assert.strictEqual(app.stationFor(key), st, key);
  assert.strictEqual(app.stationFor("done"), null);
  assert.strictEqual(app.stationFor("something_new"), "board");
  assert.strictEqual(app.stationFor(undefined), "board");
  // in the model: the unknown phase is at the plan board with its own label; done is nowhere
  const unknown = flow("something_new");
  const done = flow("done");
  const m = model(null, flowsOf([unknown, done]));
  assert.deepStrictEqual(m.stations.board.teams.map((t) => t.id), [unknown.id]);
  assert.strictEqual(m.stations.board.teams[0].phaseLabel, "新的階段");
  assert.strictEqual(allTeams(m).length, 1);
  assert.strictEqual(m.teamsTotal, 1);
});

test("the waiting rule is the lobby's, in one place, and the lobby's grouping did not change", () => {
  const stale = (a) => flow("review_stale", { automation: a });
  assert.strictEqual(app.waitsForYou(flow("awaiting_merge", { attention: true })), true);
  assert.strictEqual(app.waitsForYou(flow("implementing", { attention: true })), true, "whatever the phase");
  assert.strictEqual(app.waitsForYou(flow("awaiting_approval")), false, "the page does not re-derive it");
  assert.strictEqual(app.waitsForYou(stale({ mode: "manual", held: false })), true);
  assert.strictEqual(app.waitsForYou(stale(undefined)), true);
  assert.strictEqual(app.waitsForYou(stale({ mode: "auto", held: true })), true);
  assert.strictEqual(app.waitsForYou(stale({ mode: "auto", held: false })), false);
  // the board still groups with it
  const a = flow("awaiting_approval", { attention: true });
  const b = flow("review_stale", { automation: { mode: "manual" } });
  const c = flow("implementing");
  const g = app.boardGroups(live(), flowsOf([c, a, b]));
  assert.deepStrictEqual(g.yourTurnFlows.map((f) => f.id), [a.id, b.id]);
  assert.deepStrictEqual(g.inProgress.map((f) => f.id), [c.id]);
});

test("each station keeps its own limit of 3, with a count for the rest", () => {
  // six flows spread over the stations: every one is visible
  const spread = [flow("planning"), flow("awaiting_approval"), flow("implementing"), flow("needs_fix"),
    flow("in_review"), flow("awaiting_merge")];
  const m = model(null, flowsOf(spread));
  assert.strictEqual(allTeams(m).length, 6);
  for (const st of ["board", "build", "review", "gate"]) assert.strictEqual(m.stations[st].more, 0, st);
  // crowding one station does not take places from another, and is not cut by the lobby's limit of 4
  const crowd = [...Array.from({ length: 5 }, () => flow("planning")), flow("in_review"), flow("in_review"), flow("awaiting_push")];
  const c = model(null, flowsOf(crowd));
  assert.strictEqual(c.stations.board.teams.length, 3);
  assert.strictEqual(c.stations.board.more, 2);
  assert.strictEqual(c.stations.review.teams.length, 2);
  assert.strictEqual(c.stations.review.more, 0);
  assert.strictEqual(c.stations.gate.teams.length, 1);
  // a team that waits for you is not left behind the limit: it comes first, the rest keep the API order
  const plain = Array.from({ length: 4 }, () => flow("planning"));
  const waiting = flow("awaiting_approval", { attention: true });
  const w = model(null, flowsOf([...plain, waiting]));
  assert.deepStrictEqual(w.stations.board.teams.map((t) => t.id), [waiting.id, plain[0].id, plain[1].id]);
  assert.strictEqual(w.stations.board.more, 2);
});

test("a team is its roles, the phase's own words and where the task is; reviewers are capped", () => {
  const f = flow("in_review", { automation: { mode: "auto", held: false, step_label: "審查中" },
    roles: { planner: { name: "p", family: "anthropic" },
      executor: { name: "Claude Code", family: "anthropic", family_label: "Anthropic（Claude）", model: "haiku" },
      reviewers: [1, 2, 3, 4, 5].map((i) => ({ name: `R${i}`, family: i % 2 ? "openai" : "google" })) } });
  const t = model(null, flowsOf([f])).stations.review.teams[0];
  assert.strictEqual(t.phaseLabel, "審查第 2 輪");
  assert.strictEqual(t.stationLabel, "審查室");
  assert.strictEqual(t.executor.name, "Claude Code");
  assert.strictEqual(t.executor.species, "bear");
  assert.strictEqual(t.reviewers.length, 3);
  assert.strictEqual(t.moreReviewers, 2);
  assert.deepStrictEqual(t.reviewers.map((r) => r.species), ["robot", "fox", "robot"]);
  assert.deepStrictEqual([t.automation.mode, t.automation.stepLabel], ["auto", "審查中"]);
  // no personal status is carried by a team member
  for (const member of [t.executor, ...t.reviewers]) {
    assert(!("status" in member) && !("bubble" in member), "a team member has no state of its own");
  }
  assert(!("bubble" in t));
});

// ---- desks ----------------------------------------------------------------------------------------------------

test("one desk per live session, with the words of its status and none when it has ended", () => {
  const sessions = [session("t-w", { status: "working" }), session("t-i", { status: "waiting" }),
    session("t-n", { status: "needs-input" }), session("t-u", { status: "unknown" }), session("t-x", { status: "exited" }),
    session("t-q", { status: "something-new" })];
  const m = model(live({ sessions }));
  assert.deepStrictEqual(m.desks.map((d) => d.bubble), ["工作中", "等你回覆", "需要你處理", "? 狀態未知", "", "? 狀態未知"]);
  assert.strictEqual(m.desks[4].ended, true);
  assert.strictEqual(m.desks[5].status, "unknown", "a word the taxonomy does not define is not shown as a state");
  assert.strictEqual(m.desks.length, 6);
  const d = m.desks[0];
  assert.deepStrictEqual([d.name, d.toolLabel, d.project, d.tool], ["Claude 工人", "Claude Code", "專案一", "claude"]);
  // no role label: the tool's name
  const bare = model(live({ sessions: [session("t-b", { role_label: "", agent: "codex" })] })).desks[0];
  assert.strictEqual(bare.name, "Codex CLI");
});

test("a flow is named on a desk only when its executor is that row and the live data is current", () => {
  const sess = session("t-1", { pane_id: "pane-9" });
  const byPane = bound(flow("implementing"), "pane-9");
  const byTerminal = bound(flow("in_review"), "t-1");
  const other = bound(flow("planning"), "t-2");
  const m = model(live({ sessions: [sess] }), flowsOf([byPane, byTerminal, other]));
  assert.deepStrictEqual(m.desks[0].bound.map((b) => b.id), [byPane.id, byTerminal.id]);
  assert.deepStrictEqual(m.desks[0].bound.map((b) => b.stationLabel), ["實作區", "審查室"]);
  assert.strictEqual(m.desks[0].boundMore, 0);
  // the row is not in the live sessions: nothing is drawn for it, and no desk is made for the flow
  const gone = model(live({ sessions: [] }), flowsOf([byPane]));
  assert.strictEqual(gone.desks.length, 0);
  // the live data is not current
  for (const state of ["stale", "not_loaded"]) {
    const f = bound(flow("implementing"), "pane-9", { state, label: "即時狀態已過期", reason: "", freshness: { state: "stale" } });
    assert.strictEqual(model(live({ sessions: [sess] }), flowsOf([f])).desks[0].bound.length, 0, state);
  }
  const invalid = bound(flow("implementing"), "pane-9", { state: "unknown", label: "即時狀態時間不明", freshness: { state: "invalid" } });
  assert.strictEqual(model(live({ sessions: [sess] }), flowsOf([invalid])).desks[0].bound.length, 0);
  // a flow that is done is not named
  const finished = bound(flow("done"), "pane-9");
  assert.strictEqual(model(live({ sessions: [sess] }), flowsOf([finished])).desks[0].bound.length, 0);
  // several flows on one session: two are named and the rest counted; the desk is not drawn twice
  const many = ["planning", "implementing", "in_review", "awaiting_merge"].map((k) => bound(flow(k), "t-1"));
  const crowded = model(live({ sessions: [session("t-1")] }), flowsOf(many));
  assert.strictEqual(crowded.desks.length, 1);
  assert.strictEqual(crowded.desks[0].bound.length, 2);
  assert.strictEqual(crowded.desks[0].boundMore, 2);
});

// ---- species, sprites, weapons --------------------------------------------------------------------------------

test("species by tool and by family, an override only when it is one of the four", () => {
  assert.strictEqual(app.speciesFor({ tool: "claude" }), "bear");
  assert.strictEqual(app.speciesFor({ tool: "codex" }), "robot");
  assert.strictEqual(app.speciesFor({ tool: "shared" }), "alien");
  assert.strictEqual(app.speciesFor({ tool: "" }), "alien");
  assert.strictEqual(app.speciesFor({ family: "anthropic" }), "bear");
  assert.strictEqual(app.speciesFor({ family: "openai" }), "robot");
  assert.strictEqual(app.speciesFor({ family: "google" }), "fox");
  assert.strictEqual(app.speciesFor({ family: "minimax" }), "alien");
  assert.strictEqual(app.speciesFor({ family: "unknown" }), "alien");
  assert.strictEqual(app.speciesFor(undefined), "alien");
  for (const sp of ["bear", "fox", "robot", "alien"]) assert.strictEqual(app.speciesFor({ tool: "claude" }, sp), sp);
  for (const bad of ["dragon", "", null, 3, {}, "BEAR", "__proto__", "constructor"]) {
    assert.strictEqual(app.speciesFor({ tool: "claude" }, bad), "bear", String(bad));
  }
});

test("the override is read defensively: a throwing store or an unknown value is the default", () => {
  const profiles = [profile("a", "claude"), profile("b", "codex"), profile("c", "claude"), { id: 7 }, null];
  const store = { get: (k) => ({ "office.species.a": "fox", "office.species.b": "dragon", "office.species.c": 3 })[k] };
  assert.deepStrictEqual(app.officeOverrides(profiles, store), { a: "fox" });
  const throwing = { get() { throw new Error("storage is blocked"); } };
  assert.deepStrictEqual(app.officeOverrides(profiles, throwing), {});
  assert.deepStrictEqual(app.officeOverrides(null, store), {});
  // and the model uses it, and says which one was changed
  const m = model(null, null, profilesOf([profile("a", "claude"), profile("b", "codex")]), { a: "fox", b: "dragon" });
  assert.deepStrictEqual(m.lounge.items.map((p) => [p.species, p.overridden]), [["fox", true], ["robot", false]]);
});

test("the four sprites are 16x16 of known letters, original, with no alarm red; the shadow is cached", () => {
  const letters = new Set(Object.keys(app.OFFICE_PALETTE).concat(["C", "R", "."]));
  for (const sp of app.OFFICE_SPECIES) {
    const rows = app.OFFICE_SPRITES[sp];
    assert.strictEqual(rows.length, 16, sp);
    rows.forEach((r, i) => {
      assert.strictEqual(r.length, 16, `${sp} row ${i}`);
      for (const ch of r) assert(letters.has(ch), `${sp}: ${ch}`);
    });
    assert(rows.join("").includes("K"), "outlined in black");
  }
  const reds = Object.values({ ...app.OFFICE_PALETTE, ...Object.fromEntries(Object.entries(app.OFFICE_CAMPS).flatMap(([k, c]) => [[k + "s", c.shirt], [k + "b", c.badge]])) })
    .filter((c) => c.toLowerCase() === "#da251d");
  assert.deepStrictEqual(reds, [], "the red is only for 'your turn'");
  const pal = { shirt: app.OFFICE_CAMPS.anthropic.shirt, badge: app.OFFICE_CAMPS.anthropic.badge };
  const a = app.spriteShadow("bear", pal, 3);
  assert.strictEqual(app.spriteShadow("bear", pal, 3), a, "cached: the same string");
  assert.notStrictEqual(app.spriteShadow("bear", pal, 5), a, "another scale is another string");
  assert.notStrictEqual(app.spriteShadow("fox", pal, 3), a);
  assert.notStrictEqual(app.spriteShadow("bear", { shirt: app.OFFICE_CAMPS.openai.shirt, badge: pal.badge }, 3), a);
  const px = a.split(",");
  assert(px.length > 80 && px.length < 256);
  assert(px.every((p) => /^\d+px \d+px 0 0 (#[0-9a-f]{6}|var\(--office-outline\))$/.test(p)), "one 1x1 shadow per pixel");
  assert(px.some((p) => p.endsWith("var(--office-outline)")) && !px.some((p) => p.endsWith("#18181b")), "the outline takes the theme's colour (P10 A1)");
  assert.strictEqual(app.spriteShadow("dragon", pal, 3), app.spriteShadow("alien", pal, 3), "an unknown species draws as an alien");
});

test("camp shirts stay lighter and character contrast meets 2:1 except user-decided known exceptions", () => {
  const lum = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const fur = { bear: app.OFFICE_PALETTE.B, fox: app.OFFICE_PALETTE.F, robot: app.OFFICE_PALETTE.S, alien: app.OFFICE_PALETTE.V };
  // User-decided known exceptions: 2026-10-15 user decision to retain the specification's colors.
  // Pin each pair to its approved colors; every other pair still requires at least 2:1.
  const knownExceptions = {
    "other shirt on fox": ["#a855f7", "#c2410c"],
    "other shirt on robot": ["#a855f7", "#52525b"],
    "bear fur against its outline": ["#78350f", "#18181b"],
    "alien fur against its outline": ["#4c1d95", "#18181b"],
  };
  const seenExceptions = [];
  const checkContrast = (name, a, b) => {
    if (Object.hasOwn(knownExceptions, name)) {
      assert.deepStrictEqual([a, b], knownExceptions[name], `${name}: colors approved on 2026-10-15`);
      assert(ratio(a, b) < 2, `${name}: reconsider the known exception if contrast now meets 2:1`);
      seenExceptions.push(name);
    } else {
      assert(ratio(a, b) >= 2, `${name}: ${ratio(a, b).toFixed(2)}`);
    }
  };
  for (const [sp, color] of Object.entries(fur)) {
    for (const [camp, c] of Object.entries(app.OFFICE_CAMPS)) {
      assert(lum(c.shirt) > lum(color), `${camp} shirt is lighter than the ${sp}`);
      checkContrast(`${camp} shirt on ${sp}`, c.shirt, color);
    }
    checkContrast(`${sp} fur against its outline`, color, app.OFFICE_PALETTE.K);
  }
  assert.deepStrictEqual(seenExceptions.sort(), Object.keys(knownExceptions).sort());
});

test("weapons come from the loadout's tools and nowhere else", () => {
  const claude = { tools: { known: true, allowed: ["Bash"], blocked: ["Edit", "Write"], source: "同一組常數" },
    armor: { items: [{ name: "Test", note: "可用 Bash 執行指令" }] } };
  assert.deepStrictEqual(app.weaponsFrom(claude), { known: true, allowed: ["Bash"], blocked: ["Edit", "Write"],
    source: "同一組常數", reason: "" });
  const codex = { tools: { known: false, allowed: [], blocked: [], unknown_reason: "目前無法從 VBear 啟動這個角色" } };
  assert.deepStrictEqual(app.weaponsFrom(codex), { known: false, allowed: [], blocked: [], source: "",
    reason: "目前無法從 VBear 啟動這個角色" });
  const other = { tools: { known: false, allowed: [], blocked: [], unknown_reason: "VBear 目前只支援用角色卡啟動 Claude Code" } };
  assert.strictEqual(app.weaponsFrom(other).reason, "VBear 目前只支援用角色卡啟動 Claude Code");
  // an older answer without the field: unknown, even though the armor's words mention Bash
  for (const old of [{ armor: claude.armor }, { tools: null }, { tools: "Bash" }, { tools: { known: "yes" } }, null, undefined, 3]) {
    const w = app.weaponsFrom(old);
    assert.strictEqual(w.known, false);
    assert.deepStrictEqual(w.allowed, []);
    assert(w.reason.length > 0);
  }
  // an unknown tool set with no reason still says why it is unknown
  assert(app.weaponsFrom({ tools: { known: false } }).reason.length > 0);
  // garbage in the lists is dropped, not shown
  assert.deepStrictEqual(app.weaponsFrom({ tools: { known: true, allowed: ["Bash", 3, null], blocked: "Edit" } }).allowed, ["Bash"]);
  assert.deepStrictEqual(app.weaponsFrom({ tools: { known: true, allowed: ["Bash"], blocked: "Edit" } }).blocked, []);
});

test("a skill the index does not have is said so with the index time, never as 'gone'", () => {
  const loadout = { skills: { note: "VBear 啟動的角色不會載入這些技能；這份清單是你的挑選紀錄。", items: [
    { skill_id: "s-code", state: "in_index", name: "code-review", invoke_name: "code-review" },
    { skill_id: "s-gone", state: "not_in_index", note: "目前索引找不到此技能", indexed_at: 1791770000 },
    { skill_id: "s-x", state: "index_not_loaded" }] } };
  const r = app.officeSkills(loadout);
  assert.strictEqual(r.note, "VBear 啟動的角色不會載入這些技能；這份清單是你的挑選紀錄。");
  assert.deepStrictEqual(r.rows.map((x) => x.state), ["in_index", "not_in_index", "index_not_loaded"]);
  assert(r.rows[1].text.startsWith("目前索引找不到此技能（索引時間 "));
  assert(r.rows[2].text.includes("索引尚未載入"));
  for (const row of r.rows) assert(!row.text.includes("已消失") && !row.text.includes("消失"));
  assert.deepStrictEqual(app.officeSkills(null), { note: "", rows: [] });
});

// ---- the key --------------------------------------------------------------------------------------------------

test("the key is the same for the same data and changes with every field the office shows", () => {
  const base = () => ({
    l: live({ sessions: [session("t-1", { pane_id: "pane-1" }), session("t-2", { status: "waiting", agent: "codex" })],
      attention: ["t-2"] }),
    f: flowsOf([bound(flow("awaiting_merge", { attention: true, attention_reason: "停在合併關卡" }), "pane-1"),
      flow("implementing", { automation: { mode: "auto", held: false, step_label: "派工中" } })]),
    p: profilesOf([profile("a", "claude"), profile("b", "codex")]),
    ov: {},
  });
  const keyOf = (x) => app.officeKey(model(x.l, x.f, x.p, x.ov));
  const b = base();
  const key = keyOf(b);
  assert.strictEqual(key, keyOf(clone(b)), "the same data is the same key");
  const team = (fn) => (x) => fn(x.f.flows[0]);
  const going = (fn) => (x) => fn(x.f.flows[1]);
  const sess = (fn) => (x) => fn(x.l.sessions[0]);
  const cases = {
    "flow id": team((f) => { f.id = "flow-changed00000"; }),
    "task title": team((f) => { f.task_title = "別的標題"; }),
    "task missing": team((f) => { f.task_missing = true; }),
    "phase key": team((f) => { f.phase.key = "awaiting_push"; }),
    "phase label": team((f) => { f.phase.label = "等你合併"; }),
    "phase reason": team((f) => { f.phase.reason = "別的說明"; }),
    "waits for you": team((f) => { f.attention = false; }),
    "attention reason": team((f) => { f.attention_reason = "別的原因"; }),
    "automation mode": going((f) => { f.automation.mode = "manual"; }),
    "automation held": going((f) => { f.automation.held = true; }),
    "automation step": going((f) => { f.automation.step_label = "送審中"; }),
    "executor name": team((f) => { f.roles.executor.name = "別的執行者"; }),
    "executor family": team((f) => { f.roles.executor.family = "google"; }),
    "executor model": team((f) => { f.roles.executor.model = "opus"; }),
    "reviewer name": team((f) => { f.roles.reviewers[0].name = "別的審查者"; }),
    "reviewer family": team((f) => { f.roles.reviewers[0].family = "google"; }),
    "reviewer model": team((f) => { f.roles.reviewers[0].model = "gpt-7"; }),
    "reviewer added": team((f) => { f.roles.reviewers.push({ name: "R2", family: "other" }); }),
    "more reviewers": team((f) => { for (let i = 0; i < 4; i++) f.roles.reviewers.push({ name: `x${i}`, family: "other" }); }),
    "station more": (x) => { for (let i = 0; i < 4; i++) x.f.flows.push(flow("awaiting_merge")); },
    "a flow appears": (x) => { x.f.flows.push(flow("planning")); },
    "a flow goes": (x) => { x.f.flows.pop(); },
    "session id": (x) => { x.l.sessions[1].terminal_id = "t-9"; x.l.attention = ["t-9"]; },
    "session status": sess((s) => { s.status = "needs-input"; }),
    "session activity": sess((s) => { s.activity = { reason: "新的依據", evidence: [] }; }),
    "session role label": sess((s) => { s.role_label = "別的名字"; }),
    "session title": sess((s) => { s.title = "別的標題"; }),
    "session tool": sess((s) => { s.agent = "codex"; }),
    "session project": sess((s) => { s.project_id = "p2"; x_projects(s); }),
    "project name": (x) => { x.l.projects[0].name = "改名的專案"; },
    "session waits": (x) => { x.l.attention = []; },
    "bound flow goes": (x) => { x.f.flows[0].roles.executor.session_id = "nobody"; },
    "bound flow's title": (x) => { x.f.flows[0].task_title = "別的標題"; },
    "bound flow's station": (x) => { x.f.flows[0].phase.key = "implementing"; },
    "profile name": (x) => { x.p.profiles[0].name = "改名的角色"; },
    "profile tool": (x) => { x.p.profiles[0].model.tool = "codex"; },
    "profile model": (x) => { x.p.profiles[0].model.model_id = "claude-haiku"; },
    "profile added": (x) => { x.p.profiles.push(profile("c", "shared")); },
    "profile species override": (x) => { x.ov = { a: "fox" }; },
    "flows error": (x) => { x.f = { error: "讀不到 flows.json", flows: [] }; },
    "profiles error": (x) => { x.p = { error: "讀不到名冊", profiles: [] }; },
    "runtime away": (x) => { x.l.runtime.available = false; },
    "live error": (x) => { x.l.error = "逾時"; },
  };
  function x_projects(s) { s.project_id = "p2"; }
  for (const [name, edit] of Object.entries(cases)) {
    const x = base();
    edit(x);
    assert.notStrictEqual(keyOf(x), key, `the key changes with: ${name}`);
  }
});

// ---- selection ------------------------------------------------------------------------------------------------

test("the selection stays when its key is still there and falls back to a heading when it is not", () => {
  const f = flow("implementing");
  const m = model(live({ sessions: [session("t-1")] }), flowsOf([f]), profilesOf([profile("a", "claude")]));
  for (const key of [`flow:${f.id}`, "session:t-1", "profile:a"]) {
    const r = app.restoreSelection(key, m);
    assert.deepStrictEqual([r.kept, r.key, r.focusKey, r.focusSection, r.message], [true, key, key, "", ""]);
  }
  const gone = app.restoreSelection({ key: "session:t-gone", name: "Claude 工人" }, m);
  assert.strictEqual(gone.kept, false);
  assert.strictEqual(gone.message, "剛才選的Claude 工人已不在辦公室");
  assert.strictEqual(gone.focusSection, "desks");
  assert.strictEqual(gone.focusKey, "");
  assert.strictEqual(app.restoreSelection("flow:nope", m).focusSection, "stations");
  assert.strictEqual(app.restoreSelection("profile:nope", m).focusSection, "lounge");
  assert.notStrictEqual(app.restoreSelection("profile:nope", m).focusSection, "body");
  // nothing was selected: nothing to say
  assert.deepStrictEqual(app.restoreSelection("", m), { kept: false, key: "", message: "", focusKey: "", focusSection: "" });
  // a team that moved from one station to another is the same team
  const moved = model(live({ sessions: [session("t-1")] }),
    flowsOf([{ ...f, phase: { key: "in_review", label: "審查第 2 輪", reason: "" } }]));
  assert.strictEqual(app.restoreSelection(`flow:${f.id}`, moved).kept, true);
});

// ---- counts, errors, empty, phone list ------------------------------------------------------------------------

test("the counts follow the design, and 'cannot tell' is not a zero", () => {
  const sessions = [session("t-1", { status: "working" }), session("t-2", { status: "working" }),
    session("t-3", { status: "waiting" }), session("t-4", { status: "unknown" })];
  const flows = [flow("awaiting_merge", { attention: true }), flow("review_stale", { automation: { mode: "manual" } }),
    flow("implementing"), flow("done", { attention: true })];
  const m = model(live({ sessions, attention: ["t-3"] }), flowsOf(flows), profilesOf([profile("a", "claude"), profile("b", "codex")]));
  assert.deepStrictEqual([m.counts.turn, m.counts.turnFlows, m.counts.turnSessions], [3, 2, 1]);
  assert.strictEqual(m.counts.working, 2);
  assert.strictEqual(m.counts.unknown, 1);
  assert.strictEqual(m.counts.roster, 2);
  // runtime away: the two live counts are not 0, they are unknown
  const away = model(live({ runtime: { available: false, problems: ["x"] }, sessions: [], attention: [] }), flowsOf(flows));
  assert.strictEqual(away.counts.working, null);
  assert.strictEqual(away.counts.unknown, null);
  assert.strictEqual(away.runtimeAvailable, false);
  assert.strictEqual(away.counts.turnFlows, 2, "the flows' part is still counted");
});

test("errors are carried and an empty office is not claimed when something could not be read", () => {
  const e1 = model(null, { error: "讀不到 flows.json", flows: [] });
  assert.strictEqual(e1.errors.flows, "讀不到 flows.json");
  assert.strictEqual(e1.allEmpty, false);
  assert.strictEqual(allTeams(e1).length, 0);
  const e2 = model(null, null, { error: "名冊壞了", profiles: [] });
  assert.strictEqual(e2.errors.profiles, "名冊壞了");
  assert.strictEqual(e2.counts.roster, null);
  assert.strictEqual(e2.allEmpty, false);
  assert(app.officeModel(live(), flowsOf([]), null).errors.profiles, "a roster that was never read is an error");
  assert(app.officeModel(live(), null, profilesOf([])).errors.flows, "flows that were never read are an error");
  assert(model(null, { ok: true }).errors.flows, "a shape the page does not know is an error, not an empty list");
  const away = model(live({ runtime: { available: false, problems: [] } }));
  assert.strictEqual(away.errors.runtime, true);
  assert.strictEqual(away.allEmpty, false, "no desks drawn as if nobody was there");
  const ok = model();
  assert.strictEqual(ok.allEmpty, true);
  assert.deepStrictEqual([ok.errors.flows, ok.errors.profiles, ok.errors.runtime], ["", "", false]);
  // one of the three present: not empty
  assert.strictEqual(model(null, null, profilesOf([profile("a", "claude")])).allEmpty, false);
  assert.strictEqual(model(live({ sessions: [session("t-1")] })).allEmpty, false);
  assert.strictEqual(model(null, flowsOf([flow("planning")])).allEmpty, false);
  // only finished flows: no team is shown, and nobody else: empty
  assert.strictEqual(model(null, flowsOf([flow("done")])).allEmpty, true);
});

test("the lounge shows 24 at most and counts the rest; it is a roster, not attendance", () => {
  const profiles = Array.from({ length: 30 }, (_, i) => profile(`p${i}`, i % 2 ? "codex" : "claude"));
  const m = model(null, null, profilesOf(profiles));
  assert.strictEqual(m.lounge.items.length, 24);
  assert.strictEqual(m.lounge.more, 6);
  assert.strictEqual(m.lounge.total, 30);
  assert.strictEqual(m.counts.roster, 30);
  assert.deepStrictEqual(m.lounge.items.map((p) => p.id), profiles.slice(0, 24).map((p) => p.id), "the API order");
  assert(m.lounge.items.every((p) => !("status" in p) && !("bubble" in p)));
});

test("the phone's list: who waits for you, the stations in order, the desks, the lounge", () => {
  const waiting = flow("awaiting_approval", { attention: true });
  const going = flow("implementing");
  const rev = flow("in_review");
  const m = model(live({ sessions: [session("t-1"), session("t-2", { status: "waiting" })], attention: ["t-2"] }),
    flowsOf([going, rev, waiting]), profilesOf([profile("a", "claude")]));
  const groups = app.officeList(m);
  assert.deepStrictEqual(groups.map((g) => g.id), ["turn", "station-board", "station-build", "station-review",
    "station-gate", "desks", "lounge"]);
  assert.deepStrictEqual(groups.map((g) => g.label), ["輪到你", "計畫板", "實作區", "審查室", "合併關卡", "辦公桌", "休息室"]);
  const by = Object.fromEntries(groups.map((g) => [g.id, g.keys]));
  assert.deepStrictEqual(by.turn, [`flow:${waiting.id}`, "session:t-2"]);
  assert.deepStrictEqual(by["station-board"], [`flow:${waiting.id}`]);
  assert.deepStrictEqual(by["station-build"], [`flow:${going.id}`]);
  assert.deepStrictEqual(by.desks, ["session:t-1", "session:t-2"]);
  assert.deepStrictEqual(by.lounge, ["profile:a"]);
});


// ---- the page -------------------------------------------------------------------------------------------------

let page;
let tick = null;
let mobile = false;
global.window.matchMedia = (q) => ({ matches: mobile && /max-width: 820px/.test(q), addEventListener() {}, removeEventListener() {} });
function loadoutOf(tool, over = {}) {
  const tools = tool === "claude" ? { known: true, allowed: ["Bash"], blocked: ["Edit", "Write"], source: "與 argv 相同的常數" }
    : { known: false, allowed: [], blocked: [], unknown_reason: tool === "codex" ? "目前無法從 VBear 啟動這個角色" : "VBear 目前只支援用角色卡啟動 Claude Code" };
  return { ok: true, tools,
    skills: { title: "已選技能（VBear 啟動時不載入）", note: "VBear 啟動的角色不會載入這些技能；這份清單是你的挑選紀錄。", items: [
      { skill_id: "s-code", state: "in_index", name: "code-review", invoke_name: "code-review" },
      { skill_id: "s-gone", state: "not_in_index", note: "目前索引找不到此技能", indexed_at: 1791770000 }] },
    armor: { applicable: true, preview_decides: "實際以出發通行證為準", items: [
      { name: "Write", group: "blocked", level: "強制（限已測路徑、版本與執行層）", note: "寫入只限工作目錄" },
      { name: "Test", group: "not_blocked", level: "僅意圖", note: "可用 Bash 執行指令" }] }, ...over };
}
function setPage(over = {}) {
  page = { live: live(), flows: flowsOf([]), profiles: profilesOf([]), loadout: {}, loadoutError: null, flowsError: null,
    profilesError: null, liveError: null, ...over };
  setHandler((url) => {
    const p = url.split("?")[0];
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return page.liveError ? jsonResponse({ error: page.liveError }, false, 500) : jsonResponse(page.live);
    if (p === "/api/flows") return page.flowsError ? jsonResponse({ error: page.flowsError }, false, 500) : jsonResponse(page.flows);
    if (p === "/api/agent-profiles") return page.profilesError ? jsonResponse({ error: page.profilesError }, false, 500) : jsonResponse(page.profiles);
    const m = /^\/api\/agent-profiles\/([^/]+)\/loadout$/.exec(p);
    if (m) return page.loadoutError ? jsonResponse({ error: page.loadoutError }, false, 500) : jsonResponse(page.loadout[m[1]] || loadoutOf("claude"));
    return null;
  });
}
async function open() {
  const real = global.setInterval;
  tick = null;
  global.setInterval = (fn) => { tick = fn; return 0; };
  global.location.hash = "#/office";
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
async function refresh() { assert(tick, "the office registered a refresh"); tick(); await settle(); }
const byKey = (mainEl, key) => mainEl.find((n) => n.getAttribute && n.getAttribute("data-office-key") === key);
const byClass = (n, c) => n.findAll((x) => x.hasClass && x.hasClass(c));
const panel = (mainEl) => mainEl.find((n) => n.hasClass && n.hasClass("office-panel"));
const INTERACTIVE = new Set(["a", "button", "input", "select", "textarea", "summary"]);
const scene = () => {
  const turn = flow("awaiting_merge", { attention: true, attention_reason: "停在合併關卡" });
  const going = flow("implementing", { automation: { mode: "auto", held: false, step_label: "派工中" } });
  const bnd = bound(flow("in_review"), "pane-1");
  return { turn, going, bnd, flows: [turn, going, bnd] };
};

test("the office page: three areas, the counts twice, jump links, one button per team and character", async () => {
  const sc = scene();
  setPage({ flows: flowsOf(sc.flows), live: live({ sessions: [session("t-1", { pane_id: "pane-1" }),
    session("t-2", { status: "waiting", agent: "codex", role_label: "" }), session("t-3", { status: "unknown" })], attention: ["t-2"] }),
  profiles: profilesOf([profile("a", "claude"), profile("b", "codex")]) });
  const main = await open();
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "辦公室");
  const heads = main.findAll((n) => n.tag === "h2").map(text);
  assert.deepStrictEqual(heads.slice(0, 3), ["工作站", "辦公桌", "休息室"]);
  assert.strictEqual(byClass(main, "office-counts").length, 2, "the counts at the top and at the foot of the scene");
  const jumps = byClass(main, "office-jump").map(text);
  assert.deepStrictEqual(jumps, ["工作站", "辦公桌", "休息室"]);
  assert(text(main).includes("每 5 秒更新"));
  // each team and character is one button with a label of its name and its state or place
  const buttons = main.findAll((n) => n.getAttribute && n.getAttribute("data-office-key"));
  assert.strictEqual(buttons.length, 3 + 3 + 2);
  for (const b of buttons) {
    assert.strictEqual(b.tag, "button");
    const label = b.getAttribute("aria-label");
    assert(label && label.length > 3, "a label");
    // nothing interactive inside a button
    assert.strictEqual(b.findAll((n) => INTERACTIVE.has(n.tag)).length, 0, label);
  }
  const t = byKey(main, `flow:${sc.turn.id}`);
  assert(t.getAttribute("aria-label").includes("審查通過・等合併") && t.getAttribute("aria-label").includes("任務在：合併關卡"));
  assert(t.getAttribute("aria-label").includes("輪到你"));
  assert(byKey(main, "session:t-3").getAttribute("aria-label").includes("狀態未知"));
  assert(byKey(main, "profile:a").getAttribute("aria-label").includes("名冊"));
});

test("a team that waits for you has the badge with words and a thick frame; teams have no personal status bubble", async () => {
  const sc = scene();
  setPage({ flows: flowsOf(sc.flows) });
  const main = await open();
  const team = byKey(main, `flow:${sc.turn.id}`);
  const badges = byClass(team, "office-turn");
  assert.strictEqual(badges.length, 1);
  assert(text(badges[0]).includes("輪到你") && text(badges[0]).includes("!"));
  assert(team.hasClass("office-team-waits"));
  const station = main.find((n) => n.getAttribute && n.getAttribute("data-station") === "gate");
  assert(station.hasClass("office-station-waits"));
  const plain = byKey(main, `flow:${sc.going.id}`);
  assert.strictEqual(byClass(plain, "office-turn").length, 0);
  // no bubble in any team: not 工作中, not zz, not ?
  for (const k of [sc.turn, sc.going, sc.bnd]) {
    const b = byKey(main, `flow:${k.id}`);
    assert.strictEqual(byClass(b, "office-bubble").length, 0);
    for (const word of ["工作中", "zz", "?"]) assert(!text(b).includes(word), `${word} in a team`);
  }
  // the other station is not framed
  assert(!main.find((n) => n.getAttribute && n.getAttribute("data-station") === "build").hasClass("office-station-waits"));
  // the team's words: task, the phase's own label, where, the mode
  assert(text(plain).includes(sc.going.task_title) && text(plain).includes("實作中") && text(plain).includes("任務在：實作區"));
  assert(text(plain).includes("自動執行中・派工中"));
  assert(text(byKey(main, `flow:${sc.turn.id}`)).includes("手動記錄"));
});

test("a desk's bubble always has words; an ended session has none and its plate says so; flows are named on the plate", async () => {
  const sc = scene();
  setPage({ flows: flowsOf(sc.flows), live: live({ sessions: [session("t-1", { pane_id: "pane-1" }),
    session("t-2", { status: "waiting" }), session("t-3", { status: "unknown" }), session("t-4", { status: "exited" }),
    session("t-5", { status: "needs-input" })], attention: ["t-2"] }) });
  const main = await open();
  const bubbleOf = (k) => byClass(byKey(main, k), "office-bubble").map(text);
  assert.deepStrictEqual(bubbleOf("session:t-1"), ["工作中"]);
  assert.deepStrictEqual(bubbleOf("session:t-2"), ["等你回覆"]);
  assert.deepStrictEqual(bubbleOf("session:t-3"), ["? 狀態未知"]);
  assert.deepStrictEqual(bubbleOf("session:t-5"), ["需要你處理"]);
  assert.deepStrictEqual(bubbleOf("session:t-4"), []);
  assert(text(byKey(main, "session:t-4")).includes("已結束"));
  // the bound flow is on the plate of the very row, with its station
  assert(text(byKey(main, "session:t-1")).includes(`流程：${sc.bnd.task_title}（任務在：審查室）`));
  assert(!text(byKey(main, "session:t-2")).includes("流程："));
  // the desk of a session that waits for you has the badge
  assert(byClass(byKey(main, "session:t-2"), "office-turn").length === 1);
});

test("each station has its own limit, with a link for the rest; the lounge stops at 24", async () => {
  const flows = [...Array.from({ length: 5 }, () => flow("planning")), flow("in_review"), flow("awaiting_merge")];
  const profiles = Array.from({ length: 30 }, (_, i) => profile(`p${i}`, "claude"));
  setPage({ flows: flowsOf(flows), profiles: profilesOf(profiles) });
  const main = await open();
  const board = main.find((n) => n.getAttribute && n.getAttribute("data-station") === "board");
  assert.strictEqual(board.findAll((n) => n.getAttribute && (n.getAttribute("data-office-key") || "").startsWith("flow:")).length, 3);
  const more = byClass(board, "office-more");
  assert.strictEqual(more.length, 1);
  assert.strictEqual(text(more[0]), "這站還有 2 隊 →");
  assert.strictEqual(more[0].getAttribute("href"), "#/flows");
  const lounge = main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "lounge");
  assert.strictEqual(lounge.findAll((n) => n.getAttribute && (n.getAttribute("data-office-key") || "").startsWith("profile:")).length, 24);
  const loungeMore = byClass(lounge, "office-more")[0];
  assert.strictEqual(text(loungeMore), "還有 6 個角色 →");
  assert.strictEqual(loungeMore.getAttribute("href"), "#/team");
  assert(text(lounge).includes("名冊：角色設定，不代表正在出勤"));
});

test("selecting a profile reads its loadout once and shows weapons, armor and skills as they are", async () => {
  setPage({ profiles: profilesOf([profile("a", "claude"), profile("b", "codex")]),
    loadout: { a: loadoutOf("claude"), b: loadoutOf("codex") } });
  const main = await open();
  const reads = () => FETCH_LOG.filter((x) => /\/loadout$/.test(x.url)).length;
  const before = reads();
  byKey(main, "profile:a").click();
  await settle();
  const p = panel(main);
  assert(text(p).includes("名冊：這是角色設定，不代表正在出勤"));
  const weapons = p.find((n) => n.getAttribute && n.getAttribute("data-office-gear") === "weapons");
  assert(text(weapons).includes("Bash・可用") && text(weapons).includes("Edit・鎖住") && text(weapons).includes("Write・鎖住"));
  const armor = p.find((n) => n.getAttribute && n.getAttribute("data-office-gear") === "armor");
  const cells = byClass(armor, "office-armor-cell");
  assert.strictEqual(cells.length, 2);
  assert(cells[0].hasClass("office-armor-solid") && text(cells[0]).includes("強制（限已測路徑、版本與執行層）"));
  assert(cells[1].hasClass("office-armor-dashed") && text(cells[1]).includes("僅意圖"), "dashed is not enforced, and has words");
  const skills = p.find((n) => n.getAttribute && n.getAttribute("data-office-gear") === "skills");
  assert(text(skills).includes("這份清單是你的挑選紀錄"));
  assert(text(skills).includes("目前索引找不到此技能（索引時間 "));
  assert(!text(p).includes("已消失"));
  assert.strictEqual(reads() - before, 1);
  assert(text(p).includes("打開角色卡"));
  assert.strictEqual(byClass(p, "office-go")[0].getAttribute("href"), "#/workbench?profile=a");
  // a refresh with nothing changed does not read it again, and the selection is still there
  await refresh();
  assert.strictEqual(reads() - before, 1);
  assert(byKey(main, "profile:a").hasClass("office-selected"));
  // the other tool: unknown, with the reason as it came
  byKey(main, "profile:b").click();
  await settle();
  assert(text(panel(main)).includes("未知：目前無法從 VBear 啟動這個角色"));
  assert.strictEqual(reads() - before, 2);
});

test("the roster card in the panel is the pool's card: a short front, the gear on the back, the face kept across repaints", async () => {
  setPage({ profiles: profilesOf([profile("a", "claude", { equipped_skill_ids: ["s-code", "s-gone"],
    permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } }), profile("b", "codex")]),
  loadout: { a: loadoutOf("claude"), b: loadoutOf("codex") } });
  const main = await open();
  byKey(main, "profile:a").click();
  await settle();
  const cardIn = () => panel(main).find((n) => n.tag === "article" && n.getAttribute && n.getAttribute("data-profile-id") === "a");
  const face = (c, which) => c.find((n) => n.tag === "div" && n.getAttribute && n.getAttribute("data-face") === which);
  let card = cardIn();
  assert(card && card.hasClass("rcard") && card.getAttribute("data-camp") === "anthropic");
  assert.strictEqual(card.getAttribute("data-face"), "front");
  const gearIn = (f, kind) => f.find((n) => n.getAttribute && n.getAttribute("data-office-gear") === kind);
  assert(!gearIn(face(card, "front"), "weapons") && !gearIn(face(card, "front"), "armor"), "the front is short: no gear");
  assert(gearIn(face(card, "back"), "weapons") && gearIn(face(card, "back"), "armor") && gearIn(face(card, "back"), "skills"), "the gear is on the back");
  // the slots of the front come from the loadout: both skills are kept, neither one loads
  const slots = card.findAll((n) => n.getAttribute && ["collected", "active"].includes(n.getAttribute("data-slot")));
  assert.deepStrictEqual(slots.map((n) => n.getAttribute("data-slot")), ["collected", "collected"]);
  assert(text(face(card, "front")).includes("技能卡 2 張") && text(face(card, "front")).includes("收藏中"));
  assert.strictEqual(face(card, "back").getAttribute("aria-hidden"), "true");
  assert(face(card, "back").hasAttribute("hidden") && !face(card, "front").hasAttribute("hidden"));
  // turning the card, then selecting the same character again (a repaint of the panel), keeps the back up
  card.findAll((n) => n.getAttribute && n.getAttribute("data-pcard") === "flip")[0].click();
  assert.strictEqual(card.getAttribute("data-face"), "back");
  byKey(main, "profile:a").click();
  await settle();
  card = cardIn();
  assert.strictEqual(card.getAttribute("data-face"), "back", "the same character: the face stays");
  // another character starts on its front
  byKey(main, "profile:b").click();
  await settle();
  const other = panel(main).find((n) => n.tag === "article" && n.getAttribute && n.getAttribute("data-profile-id") === "b");
  assert.strictEqual(other.getAttribute("data-face"), "front");
  assert(text(panel(main)).includes("打開角色卡"), "the link to the workbench stays");
  assert(!text(panel(main)).includes("出勤中"));
});

test("a failed loadout is said in the gear area and the rest of the panel stays", async () => {
  setPage({ profiles: profilesOf([profile("a", "claude")]), loadoutError: "讀取失敗" });
  const main = await open();
  byKey(main, "profile:a").click();
  await settle();
  const p = panel(main);
  assert(text(p).includes("讀不到這個角色的裝備：讀取失敗"));
  assert(text(p).includes("名冊：這是角色設定"));
  assert.strictEqual(byClass(p, "office-go").length, 1);
});

test("a session's panel says its gear is unknown; a team's panel has no gear and says why", async () => {
  const sc = scene();
  setPage({ flows: flowsOf(sc.flows), live: live({ sessions: [session("t-1", { pane_id: "pane-1" })] }) });
  const main = await open();
  byKey(main, "session:t-1").click();
  await settle();
  let p = panel(main);
  assert(text(p).includes("未知：不是用角色卡啟動的，VBear 看不到它的裝備"));
  assert(text(p).includes("標題顯示工作中"), "the basis of its status");
  const term = byClass(p, "office-go")[0];
  assert.strictEqual(term.getAttribute("href"), "#/term/pane-1");
  byKey(main, `flow:${sc.turn.id}`).click();
  await settle();
  p = panel(main);
  assert(text(p).includes("流程角色只記名稱與模型家族，沒有裝備資料"));
  assert(text(p).includes("停在合併關卡"));
  assert(text(p).includes("Claude Code") && text(p).includes("Codex") && text(p).includes("gpt-6-luna"));
  assert.strictEqual(p.findAll((n) => n.getAttribute && n.getAttribute("data-office-gear")).length, 0);
  assert.strictEqual(byClass(p, "office-go")[0].getAttribute("href"), `#/flows/${sc.turn.id}`);
});

test("the species of a profile can be changed, is stored, and a bad stored value is the default", async () => {
  global.localStorage._store = {};
  setPage({ profiles: profilesOf([profile("a", "claude"), profile("b", "codex")]) });
  let main = await open();
  const spritesOf = (key) => byClass(byKey(main, key), "office-px")[0].style.cssText;
  const before = spritesOf("profile:a");
  byKey(main, "profile:a").click();
  await settle();
  const select = panel(main).find((n) => n.tag === "select");
  assert(select, "a species selector");
  select.value = "fox";
  select.dispatch("change", { target: select });
  await settle();
  assert.strictEqual(JSON.parse(global.localStorage._store["sid:office.species.a"]), "fox");
  assert.notStrictEqual(spritesOf("profile:a"), before, "the sprite changed");
  assert(text(panel(main)).includes("只換名冊上的外觀；出勤的終端與流程角色依工具或模型家族顯示"));
  // an unknown stored value is ignored
  global.localStorage._store["sid:office.species.b"] = JSON.stringify("dragon");
  main = await open();
  const sp = app.speciesFor({ tool: "codex" }, "dragon");
  assert.strictEqual(sp, "robot");
  global.localStorage._store = {};
});

test("a refresh repaints only when something shown changed; the selection stays and the focus follows it", async () => {
  const sc = scene();
  setPage({ flows: flowsOf(sc.flows), live: live({ sessions: [session("t-1")] }) });
  const main = await open();
  const ch = byKey(main, "session:t-1");
  ch.focus();
  ch.click();
  await settle();
  const layout = main.find((n) => n.hasClass && n.hasClass("office-layout"));
  const scened = layout.children[0];
  await refresh();
  assert.strictEqual(layout.children[0], scened, "no change: not repainted");
  // a visible change: the session now waits
  page.live = live({ sessions: [session("t-1", { status: "waiting" })], attention: ["t-1"] });
  await refresh();
  const again = byKey(main, "session:t-1");
  assert(again && again !== ch, "repainted");
  assert(again.hasClass("office-selected"), "the selection is kept");
  assert.strictEqual(global.document.activeElement, again, "the focus is on the new element of the same character");
  assert(text(panel(main)).includes("等你回覆"));
});

test("a selected session that ended: the panel goes back, says what was there, and the focus goes to the heading", async () => {
  setPage({ live: live({ sessions: [session("t-1"), session("t-2")] }) });
  const main = await open();
  const ch = byKey(main, "session:t-1");
  ch.focus();
  ch.click();
  await settle();
  page.live = live({ sessions: [session("t-2")] });
  await refresh();
  assert.strictEqual(panel(main).getAttribute("data-office-panel"), "idle");
  assert(text(panel(main)).includes("剛才選的Claude 工人已不在辦公室"));
  const active = global.document.activeElement;
  assert(active && active.tag !== "body", "the focus is not left on the body");
  assert.strictEqual(active.getAttribute("id"), "office-desks");
  assert.strictEqual(active.getAttribute("tabindex"), "-1");
});

test("the selection is gone while the focus is in its panel: the focus goes to that kind's own heading, exactly", async () => {
  // desktop: the focus on the panel's close button, then on its title
  for (const where of ["close", "title"]) {
    setPage({ live: live({ sessions: [session("t-1"), session("t-2")] }) });
    const main = await open();
    byKey(main, "session:t-1").click();
    await settle();
    const target = where === "close" ? panel(main).find((n) => n.getAttribute && n.getAttribute("data-office-close") === "1")
      : panel(main).find((n) => n.getAttribute && n.getAttribute("id") === "office-panel-title");
    target.focus();
    assert.strictEqual(global.document.activeElement, target);
    page.live = live({ sessions: [session("t-2")] });
    await refresh();
    const active = global.document.activeElement;
    assert.strictEqual(active.getAttribute("id"), "office-desks", `from the ${where}`);
    assert.strictEqual(active.getAttribute("tabindex"), "-1");
    assert(text(panel(main)).includes("已不在辦公室"));
  }
  // a flow: the heading of the stations; a profile: the lounge
  const f = flow("implementing");
  setPage({ flows: flowsOf([f]), profiles: profilesOf([profile("a", "claude")]) });
  let main = await open();
  byKey(main, `flow:${f.id}`).click();
  await settle();
  panel(main).find((n) => n.getAttribute && n.getAttribute("data-office-close") === "1").focus();
  page.flows = flowsOf([]);
  await refresh();
  assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-stations");
  setPage({ profiles: profilesOf([profile("a", "claude"), profile("b", "codex")]) });
  main = await open();
  byKey(main, "profile:a").click();
  await settle();
  const sel = panel(main).find((n) => n.tag === "select");
  sel.focus();
  page.profiles = profilesOf([profile("b", "codex")]);
  const reload = main.find((n) => n.getAttribute && n.getAttribute("data-office-reload") === "1");
  reload.click();
  await settle();
  assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-lounge");
  // focus on something that is not tied to the selection stays where it was (a count button)
  setPage({ live: live({ sessions: [session("t-1"), session("t-2")] }) });
  main = await open();
  byKey(main, "session:t-1").click();
  await settle();
  const count = byClass(main, "office-count").find((n) => n.getAttribute("data-office-count") === "working");
  count.focus();
  page.live = live({ sessions: [session("t-2")] });
  await refresh();
  const again = global.document.activeElement;
  assert.strictEqual(again.getAttribute("data-office-count"), "working", "a control that survives keeps the focus");
});

test("on a phone, the focus goes to the heading of its area when the selection is gone", async () => {
  mobile = true;
  try {
    const f = flow("implementing");
    setPage({ flows: flowsOf([f]), live: live({ sessions: [session("t-1")] }) });
    let main = await open();
    byKey(main, `flow:${f.id}`).click();
    await settle();
    assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-panel-title");
    page.flows = flowsOf([]);
    await refresh();
    assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-station-build");
    // a session: the desks
    main = await open();
    byKey(main, "session:t-1").click();
    await settle();
    assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-panel-title");
    page.live = live({ sessions: [] });
    await refresh();
    assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-desks");
  } finally { mobile = false; }
});

test("every control of the office has a touch height of 44px, the species selector too", () => {
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  const rules = new Map();
  for (const m of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    for (const sel of m[1].split(",").map((x) => x.trim())) {
      const h = /min-height:\s*(\d+)px/.exec(m[2]);
      if (h) rules.set(sel, Math.max(rules.get(sel) || 0, Number(h[1])));
    }
  }
  const mustBe44 = [".office-count", ".office-jump", ".office-team", ".office-char", ".office-row", ".office-more",
    ".office-close", ".office-go", ".office-species select", ".office-start .btn"];
  for (const sel of mustBe44) assert((rules.get(sel) || 0) >= 44, `${sel} has min-height >= 44px (${rules.get(sel)})`);
  // and the page really builds the selector that rule is for
  const src = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(src.includes('el("label", { class: "office-species" }, "種族 ", species)'));
});

test("Esc closes the panel and the focus goes back to the character; the close button does the same", async () => {
  setPage({ live: live({ sessions: [session("t-1")] }) });
  const main = await open();
  const ch = byKey(main, "session:t-1");
  ch.focus();
  ch.click();
  await settle();
  assert.strictEqual(panel(main).getAttribute("data-office-panel"), "open");
  const rootEl = main.find((n) => n.hasClass && n.hasClass("office"));
  rootEl.dispatch("keydown", { key: "Escape", target: ch });
  await settle();
  assert.strictEqual(panel(main).getAttribute("data-office-panel"), "idle");
  assert.strictEqual(global.document.activeElement.getAttribute("data-office-key"), "session:t-1");
  byKey(main, "session:t-1").click();
  await settle();
  const closeBtn = panel(main).find((n) => n.getAttribute && n.getAttribute("data-office-close") === "1");
  closeBtn.click();
  await settle();
  assert.strictEqual(panel(main).getAttribute("data-office-panel"), "idle");
});

test("a count moves the focus to the first of its kind, or says there is none", async () => {
  const sc = scene();
  setPage({ flows: flowsOf(sc.flows), live: live({ sessions: [session("t-1"), session("t-3", { status: "unknown" })] }),
    profiles: profilesOf([profile("a", "claude")]) });
  const main = await open();
  const count = (kind) => byClass(main, "office-count").find((n) => n.getAttribute("data-office-count") === kind);
  assert(text(count("turn")).includes("輪到你"));
  count("turn").click();
  await settle();
  assert(byKey(main, `flow:${sc.turn.id}`).hasClass("office-selected"));
  assert.strictEqual(global.document.activeElement, byKey(main, `flow:${sc.turn.id}`));
  count("unknown").click();
  await settle();
  assert(byKey(main, "session:t-3").hasClass("office-selected"));
  setPage({ flows: flowsOf([flow("implementing")]), live: live({ sessions: [session("t-1")] }) });
  const empty = await open();
  const c2 = byClass(empty, "office-count").find((n) => n.getAttribute("data-office-count") === "turn");
  c2.click();
  await settle();
  assert(text(empty).includes("目前沒有輪到你的角色"));
});

test("errors are said where they are: flows, runtime, roster; and an empty office is only claimed when everything was read", async () => {
  setPage({ flowsError: "讀不到 flows.json", profilesError: "名冊壞了" });
  let main = await open();
  assert(text(main).includes("讀不到流程：讀不到 flows.json"));
  assert(text(main).includes("讀不到角色名冊：名冊壞了"));
  assert(!text(main).includes("辦公室目前沒有人"));
  assert(!text(main).includes("這站沒有隊伍"), "no empty stations drawn as if there were no tasks");
  setPage({ live: live({ runtime: { available: false, problems: ["連不上"] } }) });
  main = await open();
  assert(text(main).includes("無法連線到 VBear runtime"));
  assert(!text(main).includes("目前沒有出勤中的終端"));
  assert(text(byClass(main, "office-counts")[0]).includes("無法判斷"));
  assert(!text(main).includes("辦公室目前沒有人"));
  setPage();
  main = await open();
  assert(text(main).includes("辦公室目前沒有人。到終端工作台建立角色。"));
  const link = main.findAll((n) => n.tag === "a").find((n) => n.getAttribute("href") === "#/workbench");
  assert(link);
});

test("on a phone: no scene, a list in the design's order; a row opens a full panel and 'back' returns to the row", async () => {
  const sc = scene();
  mobile = true;
  try {
    setPage({ flows: flowsOf(sc.flows), live: live({ sessions: [session("t-1", { pane_id: "pane-1" }), session("t-2", { status: "waiting" })], attention: ["t-2"] }),
      profiles: profilesOf([profile("a", "claude")]) });
    const main = await open();
    assert.strictEqual(byClass(main, "office-scene").length, 0, "the scene is not drawn");
    const heads = main.findAll((n) => n.tag === "h2").map(text);
    assert.deepStrictEqual(heads, ["輪到你", "計畫板", "實作區", "審查室", "合併關卡", "辦公桌", "休息室"]);
    assert.deepStrictEqual(byClass(main, "office-jump").map(text), ["輪到你", "工作站", "辦公桌", "休息室"]);
    const rows = byClass(main, "office-row");
    assert(rows.length >= 7);
    for (const r of rows) assert.strictEqual(r.tag, "button");
    // a row that waits for you says so in words, not only in its frame
    for (const r of rows.filter((x) => x.hasClass("office-row-waits"))) {
      assert(byClass(r, "office-turn").length === 1 && text(r).includes("輪到你"));
    }
    assert(rows.some((x) => x.hasClass("office-row-waits")));
    const row = byKey(main, `flow:${sc.going.id}`);
    row.focus();
    row.click();
    await settle();
    assert.strictEqual(byClass(main, "office-list").length, 0, "the list is replaced by the full panel");
    assert.strictEqual(panel(main).getAttribute("data-office-panel"), "open");
    assert.strictEqual(global.document.activeElement.getAttribute("id"), "office-panel-title");
    const back = panel(main).find((n) => n.getAttribute && n.getAttribute("data-office-close") === "1");
    assert.strictEqual(text(back), "返回");
    back.click();
    await settle();
    assert.strictEqual(global.document.activeElement.getAttribute("data-office-key"), `flow:${sc.going.id}`);
    // the row is gone when the user returns: the focus goes to the list's heading
    byKey(main, "session:t-1").click();
    await settle();
    page.live = live({ sessions: [session("t-2", { status: "waiting" })], attention: ["t-2"] });
    await refresh();
    const active = global.document.activeElement;
    assert(active && active.tag !== "body");
  } finally { mobile = false; }
});

test("the red is only for 'your turn', and every pair the design names has the contrast it asks for", () => {
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  const blocks = {
    light: css.slice(css.indexOf(":root {"), css.indexOf("@media (prefers-color-scheme: dark)")),
    dark: css.slice(css.indexOf(":root:not([data-theme=\"light\"])"), css.indexOf(":root[data-theme=\"dark\"]")),
    darkManual: css.slice(css.indexOf(":root[data-theme=\"dark\"]"), css.indexOf("* { box-sizing")),
  };
  const varsOf = (b) => Object.fromEntries([...b.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
  const lum = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  for (const [name, block] of Object.entries(blocks)) {
    const v = varsOf(block);
    for (const t of ["vn-red", "vn-on-red", "vn-red-ink", "vn-red-deep", "vn-gold", "office-floor", "office-box-bg", "office-box-ink"]) {
      assert(v[t], `${name} defines --${t}`);
    }
    assert(ratio(v["vn-on-red"], v["vn-red"]) >= 4.5, `${name}: white on the red badge ${ratio(v["vn-on-red"], v["vn-red"]).toFixed(2)}`);
    assert(ratio(v["vn-red-ink"], v.panel) >= 4.5, `${name}: red text on the card ${ratio(v["vn-red-ink"], v.panel).toFixed(2)}`);
    assert(ratio(v["vn-red-ink"], v.bg) >= 4.5, `${name}: red text on the page`);
    assert(ratio(v["vn-red-ink"], v["office-floor"]) >= 4.5, `${name}: red text on the floor`);
    // the frame and the badge against what is behind them: 3:1
    assert(ratio(v["vn-red"], v.panel) >= 3, `${name}: red frame on the card ${ratio(v["vn-red"], v.panel).toFixed(2)}`);
    assert(ratio(v["vn-red"], v.bg) >= 3, `${name}: red frame on the page ${ratio(v["vn-red"], v.bg).toFixed(2)}`);
    assert(ratio(v["vn-red"], v["office-floor"]) >= 3, `${name}: red on the floor`);
    // the decoration is far darker/lighter than the alarm red: it cannot be taken for it
    // (the dark theme cannot go darker and still be seen against a dark page: P10 A2 makes it clearly lighter instead)
    if (name === "light") assert(lum(v["vn-red-deep"]) < lum(v["vn-red"]) * 0.6, `${name}: deep red is much darker`);
    else assert(lum(v["vn-red-deep"]) > lum(v["vn-red"]) * 1.5, `${name}: deep red is much lighter, so it is not the alarm red`);
    // the rules and borders it draws are graphics: 3:1 against the page, the card and the floor, in both themes
    for (const behind of ["bg", "panel", "office-floor"]) {
      assert(ratio(v["vn-red-deep"], v[behind]) >= 3, `${name}: deep red line on ${behind} ${ratio(v["vn-red-deep"], v[behind]).toFixed(2)}`);
    }
    assert(ratio(v["office-box-ink"], v["office-box-bg"]) >= 4.5, `${name}: bubble text`);
    assert(ratio(v["ink-2"], v.panel) >= 4.5 && ratio(v["ink-2"], v["panel-2"]) >= 4.5, `${name}: second ink on the cards`);
  }
  // the alarm red is used by 'your turn' rules only
  const rules = [...css.slice(css.indexOf("the office (design office v1.3)", css.indexOf("/* ---- the office"))).matchAll(/([^{}]+)\{([^}]*)\}/g)];
  const users = rules.filter((r) => /var\(--vn-red(-ink)?\)/.test(r[2])).map((r) => r[1].trim());
  assert(users.length > 0);
  for (const sel of users) assert(/turn|waits/.test(sel), `red used by a rule that is not about 'your turn': ${sel}`);
  // and nothing outside the office block uses it
  const before = css.slice(0, css.indexOf("/* ---- the office"));
  const usesBefore = [...before.matchAll(/([^{}]+)\{([^}]*)\}/g)].filter((r) => /var\(--vn-red/.test(r[2]));
  assert.strictEqual(usesBefore.length, 0);
});

test("the page's code uses only what a real DOM has (the test's fake nodes have find/findAll, a browser does not)", () => {
  const src = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const a = src.indexOf("// ---------- the office (design office v1.3): the page");
  const b = src.indexOf("function projectCard(p) {");
  assert(a > 0 && b > a);
  const code = src.slice(a, b);
  for (const bad of [/\broot\.find\(/, /\.findAll\(/, /\bslot\.find\(/, /\.hasClass\(/, /\.withText\(/, /\.dispatch\(/]) {
    assert(!bad.test(code), `the page's code calls a test-only method: ${bad}`);
  }
});

test("the nav has the office after the lobby, and the route exists", () => {
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  const a = html.indexOf('data-nav="home"');
  const b = html.indexOf('data-nav="office"');
  assert(a > 0 && b > a, "office comes after the lobby");
  assert(html.includes('href="#/office" data-nav="office"><span aria-hidden="true">▦</span>辦公室</a>'));
  assert.strictEqual(typeof app.viewOffice, "function");
});

test("both supplied frames use the palette and working shadows keep a separate cache", () => {
  const letters = new Set([...Object.keys(app.OFFICE_PALETTE), "C", "R", "."]);
  for (const sp of app.OFFICE_SPECIES) {
    for (const rows of [app.OFFICE_SPRITES[sp], app.OFFICE_SPRITES_WORKING[sp]]) {
      assert.strictEqual(rows.length, 16);
      for (const row of rows) {
        assert.strictEqual(row.length, 16);
        for (const c of row) assert(letters.has(c));
      }
    }
    const idle = app.spriteShadow(sp, app.OFFICE_CAMPS.openai, 3);
    const working = app.spriteShadow(sp, app.OFFICE_CAMPS.openai, 3, true);
    assert.notStrictEqual(idle, working);
    assert(working.includes(app.OFFICE_CAMPS.openai.shirt));
    assert(working.includes(app.OFFICE_CAMPS.openai.badge));
    assert.strictEqual(app.spriteShadow(sp, app.OFFICE_CAMPS.openai, 3), idle);
  }
});

test("only working desk sprites alternate; team and roster sprites remain idle", () => {
  for (const status of ["working", "waiting", "needs-input", "exited", "unknown"]) {
    const d = model(live({ sessions: [session("animation", { status })] })).desks[0];
    const n = app.officeDeskButton(d, false, false, () => {});
    assert.strictEqual(byClass(n, "office-sprite-working").length, status === "working" ? 1 : 0);
  }
  const m = model(null, flowsOf([flow("implementing")]), profilesOf([profile("idle", "claude")]));
  assert.strictEqual(byClass(app.officeTeamButton(m.stations.build.teams[0], false, false, () => {}), "office-sprite-working").length, 0);
  assert.strictEqual(byClass(app.officeProfileButton(m.lounge.items[0], false, () => {}), "office-sprite-working").length, 0);
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  assert(css.includes(".8s steps(1, end) infinite"));
  assert(/@media \(prefers-reduced-motion: reduce\)\s*{\s*\.office-sprite-working \.office-frame-idle { animation: none; visibility: visible; }\s*\.office-sprite-working \.office-frame-working { animation: none; visibility: hidden; }/.test(css));
});

test("persona lines and labels follow the corrected evidence table exactly", () => {
  const title = "依據：Claude Code 終端標題";
  const stream = "依據：Claude Code 串流協定的回合事件";
  const rows = [
    ["working", "claude-title", title + "（開頭的轉圈符號）", "我正在終端機裡忙！VBear 依標題第一個字元分類，不把標題文字作為終端標題保存或回傳。"],
    ["working", "claude-stream", stream, "我正在跑自動派工的這一輪，做完會交回結果。"],
    ["waiting", "claude-title", title + "（閒置符號 ✳）", "我停下來等你囉（! 輪到你），打開終端機看看我吧。"],
    ["waiting", "claude-stream", stream, "這一輪背景派工已結束，等待下一則任務。"],
    ["exited", null, "依據：VBear runtime（終端已結束）", "這個終端已經結束了。"],
  ];
  for (const [status, decided_by, sourceLabel, line] of rows) {
    assert.deepStrictEqual(app.personaSpeech({ key: "session:test", tool: "claude", status, activity: { decided_by, reason: "原文 <test>" } }),
      { sourceLabel, line, reason: "原文 <test>" });
  }
  for (const tool of ["claude", "codex", "other"]) {
    for (const status of ["unknown"]) {
      for (const decided_by of [null, "unrecognized"]) {
        const r = app.personaSpeech({ tool, status, activity: { decided_by } });
        assert.strictEqual(r.sourceLabel, "依據：沒有可採用的證據");
        assert.strictEqual(r.line, tool === "claude"
          ? "VBear 現在看不出我在做什麼（例如版本還沒驗證、或標題超過 5 秒沒更新），所以誠實寫『狀態未知』。"
          : "VBear 目前沒有這個工具的即時狀態來源，所以寫『狀態未知』。");
      }
    }
  }
  const cases = [
    ["in_review", "auto", "依據：流程紀錄（自動模式）", "任務位於審查階段；自動模式已設定，不代表審查程序正在執行。"],
    ["in_review", "manual", "依據：流程紀錄（手動記錄）", "任務在審查室。手動模式下，VBear 不會替你送審。"],
    ["awaiting_approval", "auto", "依據：流程紀錄", "計畫等候核准中；核准前執行者不會開工。"],
    ["awaiting_approval", "manual", "依據：流程紀錄", "計畫等候核准中；手動模式需由你自行在終端執行。"],
    ["awaiting_merge", "manual", "依據：流程紀錄＋目前版本核對", "審查通過，而且就是目前的版本。VBear 不會替你合併或上傳，輪到你了！"],
    ["review_stale", "manual", "依據：流程紀錄＋目前版本核對", "審查過的不是目前的版本，需要重新審查。"],
  ];
  for (const [phaseKey, mode, sourceLabel, line] of cases) {
    assert.deepStrictEqual(app.personaSpeech({ key: "flow:test", phaseKey, phaseReason: "原因", automation: { mode } }),
      { sourceLabel, line, reason: "原因" });
  }
  for (const phaseKey of ["planning", "implementing", "needs_fix", "review_unverified", "awaiting_push", "new-phase"]) {
    assert.strictEqual(app.personaSpeech({ key: "flow:test", phaseKey, stationLabel: "計畫板", phaseLabel: "原文 <test>" }).line,
      "任務目前在計畫板：原文 <test>");
  }
  assert.strictEqual(app.personaSpeech({ key: "profile:test" }).line, "名冊角色不在出勤，沒有即時狀態");
});

test("every session status stays consistent across persona, badge and screen for every evidence source", () => {
  const neutral = { working: "工作中", waiting: "等你回覆", "needs-input": "需要你處理" };
  const category = {
    working: /工作中|終端機裡忙|正在跑自動派工/,
    waiting: /等你回覆|停下來等你|等待下一則任務/,
    "needs-input": /需要你處理/,
    exited: /終端已經結束/,
    unknown: /狀態未知/,
  };
  for (const agent of ["claude", "codex", "other"]) {
    for (const status of Object.keys(category)) {
      for (const decided_by of ["claude-title", "claude-stream", null, "unrecognized", undefined]) {
        for (const activity of [undefined, null, { decided_by, reason: "原始原因" }]) {
          const m = model(live({ sessions: [session("matrix", { agent, status, title: "合成終端", activity })] }));
          const d = m.desks[0];
          const r = app.personaSpeech(d);
          const context = JSON.stringify({ agent, status, activity });
          assert(category[status].test(r.line), context + ": " + r.line);
          assert.strictEqual(r.line.includes("狀態未知"), status === "unknown", context);
          assert.strictEqual(r.reason, activity ? "原始原因" : "", context);
          const specific = agent === "claude" && ["working", "waiting"].includes(status)
            && activity && ["claude-title", "claude-stream"].includes(activity.decided_by);
          if (neutral[status] && !specific) {
            assert.strictEqual(r.sourceLabel, "依據：VBear runtime 回報的狀態（沒有附上證據來源）", context);
            assert.strictEqual(r.line, `VBear runtime 回報我在${neutral[status]}，但沒有附上是哪一種證據。`, context);
          }
          const rendered = app.officePanelContent(m, { key: d.key }, { close() {} }).map(text).join("");
          assert.strictEqual(rendered.includes("狀態未知"), status === "unknown", context);
          if (status === "working") assert(rendered.includes("◐ 工作中"), context);
        }
      }
    }
  }
});

test("stage screens keep session status separate from task location and roster membership", () => {
  const expected = {
    working: ["#064e3b", "#34d399", "◐ 工作中"],
    waiting: ["#7f1d1d", "#fca5a5", "✳ 輪到你"],
    "needs-input": ["#7f1d1d", "#fca5a5", "✳ 輪到你"],
    exited: ["#27272a", "#a1a1aa", "已結束"],
    unknown: ["#27272a", "#a1a1aa", "? 狀態未知"],
  };
  const lum = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  for (const [status, [fill, ink, label]] of Object.entries(expected)) {
    assert.deepStrictEqual(app.officeStageScreen({ key: "session:s", status }), { fill, ink, label });
    assert((lum(ink) + .05) / (lum(fill) + .05) >= 4.5);
    for (const species of app.OFFICE_SPECIES) {
      const target = { key: "session:s", status, species, camp: "openai", name: "<img src=x>" };
      const svg = app.officeStageSvg(target);
      assert.strictEqual(svg.tag, "svg");
      assert.strictEqual(svg.getAttribute("role"), "img");
      assert(svg.getAttribute("aria-label").includes("<img src=x>"));
      assert(svg.getAttribute("aria-label").includes(label));
      assert.strictEqual(svg.findAll((n) => (n.getAttribute("class") || "").split(/\s+/).includes("office-stage-working")).length, status === "working" ? 1 : 0);
      assert.strictEqual(svg.findAll((n) => n.getAttribute && n.getAttribute("data-stage-screen") === "1")[0].getAttribute("fill"), fill);
      assert(text(svg).includes(label));
      assert.strictEqual(svg.findAll((n) => ["image", "script", "foreignObject"].includes(n.tag)).length, 0);
    }
  }
  for (const key of ["flow:f", "profile:p"]) {
    const target = { key, status: "working", waits: true, stationLabel: "實作區", species: "fox", camp: "google",
      executor: { species: "bear", camp: "anthropic", name: "執行者" } };
    const screen = app.officeStageScreen(target);
    assert.strictEqual(screen.fill, "#27272a");
    assert.strictEqual(screen.label, key.startsWith("flow:") ? "任務在實作區" : "名冊");
    assert.strictEqual(app.officeStageSvg(target).findAll((n) => (n.getAttribute("class") || "").split(/\s+/).includes("office-stage-working")).length, 0);
  }
});

test("stage collapse is accessible, persists, and storage failure defaults to expanded", () => {
  let saved = false;
  const storage = { get: (key, fallback) => key === "office.stage.collapsed" ? saved : fallback,
    set: (key, value) => { assert.strictEqual(key, "office.stage.collapsed"); saved = value; } };
  const t = { key: "profile:p", species: "bear", camp: "anthropic", name: "角色" };
  const stage = app.officeStage(t, storage);
  const button = byClass(stage, "office-stage-toggle")[0];
  const container = byClass(stage, "office-stage-container")[0];
  assert.strictEqual(button.getAttribute("aria-controls"), container.id);
  assert.strictEqual(button.getAttribute("aria-expanded"), "true");
  assert.strictEqual(button.tag, "button");
  button.dispatch("click");
  assert.strictEqual(button.getAttribute("aria-expanded"), "false");
  assert.strictEqual(container.hidden, true);
  assert.strictEqual(text(button), "展開角色舞台");
  assert.strictEqual(saved, true);
  assert.strictEqual(byClass(app.officeStage(t, storage), "office-stage-toggle")[0].getAttribute("aria-expanded"), "false");
  button.dispatch("click");
  assert.strictEqual(container.hidden, false);
  assert.strictEqual(saved, false);
  const blocked = { get() { throw Error("blocked"); }, set() { throw Error("blocked"); } };
  assert.strictEqual(app.officeStageCollapsed(blocked), false);
  const blockedStage = app.officeStage(t, blocked);
  const blockedButton = byClass(blockedStage, "office-stage-toggle")[0];
  assert.strictEqual(blockedButton.getAttribute("aria-expanded"), "true");
  assert.doesNotThrow(() => blockedButton.dispatch("click"));
  for (const bad of [null, "true", 1, {}, false]) assert.strictEqual(app.officeStageCollapsed({ get: () => bad }), false);
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  assert(css.includes(".office-stage-container[hidden] { display: none; }"));
  assert(css.includes("width: 100%; max-width: 360px; height: auto"));
  assert(/@media \(prefers-reduced-motion: reduce\)\s*{\s*\.office-stage-working { animation: none; transform: none; }/.test(css));
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(source));
});

test("persona and stage integrate into panels and collapse focus survives refresh", async () => {
  global.localStorage._store = {};
  const f = flow("in_review", { automation: { mode: "auto", held: true } });
  setPage({ flows: flowsOf([f]), profiles: profilesOf([profile("stage", "codex")]),
    live: live({ sessions: [session("stage", { status: "waiting", activity: { decided_by: "claude-stream", reason: "<原始原因>" } })] }) });
  const main = await open();
  byKey(main, "session:stage").click();
  await settle();
  assert(text(panel(main)).includes("這一輪背景派工已結束，等待下一則任務。"));
  assert(text(panel(main)).includes("<原始原因>"));
  const button = byClass(panel(main), "office-stage-toggle")[0];
  button.click();
  button.focus();
  assert.strictEqual(button.getAttribute("aria-expanded"), "false");
  page.live.sessions[0].activity.reason = "更新原因";
  await refresh();
  const next = byClass(panel(main), "office-stage-toggle")[0];
  assert.strictEqual(next.getAttribute("aria-expanded"), "false");
  assert.strictEqual(global.document.activeElement, next);
  assert(text(panel(main)).includes("更新原因"));
  byKey(main, "flow:" + f.id).click();
  await settle();
  assert(text(panel(main)).includes("任務位於審查階段；自動模式已設定，不代表審查程序正在執行。"));
  assert(text(panel(main)).includes("任務在審查室"));
  byKey(main, "profile:stage").click();
  await settle();
  assert(text(panel(main)).includes("名冊角色不在出勤，沒有即時狀態"));
  assert.strictEqual(byClass(panel(main), "office-persona-speech").length, 0);
  global.localStorage._store = {};
});

// ---- run ------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
