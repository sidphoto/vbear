// The pixel office (design office v1.3): the pure functions — station, species, sprite, weapons, the model, the key
// that decides a repaint, the selection that survives it, the list for a phone, the counts, the errors.
// The real web/app.js on a synthetic DOM. Run: node tests/frontend/office.cjs   (exit code 0 = pass)
"use strict";

const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app } = h;

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
  assert(px.every((p) => /^\d+px \d+px 0 0 #[0-9a-f]{6}$/.test(p)), "one 1x1 shadow per pixel");
  assert.strictEqual(app.spriteShadow("dragon", pal, 3), app.spriteShadow("alien", pal, 3), "an unknown species draws as an alien");
});

test("the camps' shirts are lighter than every species' fur, so a character reads the same whatever its species", () => {
  const lum = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const fur = { bear: app.OFFICE_PALETTE.B, fox: app.OFFICE_PALETTE.F, robot: app.OFFICE_PALETTE.S, alien: app.OFFICE_PALETTE.V };
  for (const [sp, color] of Object.entries(fur)) {
    for (const [camp, c] of Object.entries(app.OFFICE_CAMPS)) {
      assert(lum(c.shirt) > lum(color), `${camp} shirt is lighter than the ${sp}`);
      assert(ratio(c.shirt, color) >= 2, `${camp} shirt on ${sp}: ${ratio(c.shirt, color).toFixed(2)}`);
    }
    assert(ratio(color, app.OFFICE_PALETTE.K) >= 2, `${sp} fur against its outline`);
  }
});

test("weapons come from the loadout's tools and nowhere else", () => {
  const claude = { tools: { known: true, allowed: ["Bash"], blocked: ["Edit", "Write"], source: "同一組常數" },
    armor: { items: [{ name: "Test", note: "可用 Bash 執行指令" }] } };
  assert.deepStrictEqual(app.weaponsFrom(claude), { known: true, allowed: ["Bash"], blocked: ["Edit", "Write"],
    source: "同一組常數", reason: "" });
  const codex = { tools: { known: false, allowed: [], blocked: [], unknown_reason: "目前無法從 VBear 啟動這個角色" } };
  assert.deepStrictEqual(app.weaponsFrom(codex), { known: false, allowed: [], blocked: [], source: "",
    reason: "目前無法從 VBear 啟動這個角色" });
  const other = { tools: { known: false, allowed: [], blocked: [], unknown_reason: "VBear 目前只支援用 Profile 啟動 Claude Code" } };
  assert.strictEqual(app.weaponsFrom(other).reason, "VBear 目前只支援用 Profile 啟動 Claude Code");
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
