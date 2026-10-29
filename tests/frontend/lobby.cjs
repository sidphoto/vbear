// The home page's quest board (design lobby v1.2): the grouping, the key that decides a repaint, the flow card,
// the empty states and the errors. The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/lobby.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, SyntheticNode, jsonResponse, setHandler } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const isEl = (tag) => (n) => n.tag === tag;
global.document.querySelector = () => null;
// the side panel's scan status is not part of this page; its first load (before a test's handler is set) leaves a
// bare overview that it cannot draw
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));

// ---- fixtures -------------------------------------------------------------------------------------------------

const PHASE_LABEL = { planning: "計畫中", awaiting_approval: "等核准", implementing: "實作中", in_review: "審查第 2 輪",
  needs_fix: "等修正", awaiting_merge: "審查通過・等合併", review_stale: "審查結果已過期",
  review_unverified: "審查通過・無法核對 HEAD", awaiting_push: "等 push", done: "完成" };
let flowN = 0;
function flow(key, over = {}) {
  flowN += 1;
  const id = "flow-" + String(flowN).padStart(12, "0");
  return {
    id, task_title: `任務 ${flowN}`, task_missing: false,
    phase: { key, label: PHASE_LABEL[key] || "？", reason: `${PHASE_LABEL[key] || "？"}的說明` },
    attention: false, attention_reason: "",
    automation: { mode: "manual", held: false, step_label: "" },
    roles: { planner: { name: "規劃者", family_label: "Anthropic（Claude）" },
      executor: { name: "Claude Code", family_label: "Anthropic（Claude）", model: "haiku" },
      reviewers: [{ name: "Codex", family_label: "OpenAI（Codex）", model: "gpt-6-luna" }] },
    executor_live: { label: "工作中", reason: "有回應", freshness: { state: "fresh", age_s: 3 } },
    latest_review: null, binding: { detail: "" },
    ...over,
  };
}
function session(id, over = {}) {
  return { terminal_id: id, pane_id: id, workspace_id: "ws1", workspace_label: "工作區", agent: "claude", status: "waiting",
    role_label: "Claude 工人", role_label_source: "tab", title: "等你回覆", activity: { reason: "等你的下一則訊息", evidence: [] },
    models_observed: { "claude-haiku": 2 }, skills_used: [], usage_matched: true, supported_tool: true, project_id: "p1", ...over };
}
function live(over = {}) {
  return { runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [{ project_id: "p1", name: "專案一", path: "/p/one", live_session_ids: [], recent_session_ids: [], last_activity: null }],
    panes: [], usage: { sessions: [] }, ...over };
}
const flowsOf = (flows, over = {}) => ({ ok: true, flows, ...over });
const group = (l, f) => app.boardGroups(l, f);
const ids = (arr) => arr.map((f) => f.id);

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- boardGroups ----------------------------------------------------------------------------------------------

test("the server's attention flag decides who waits for you, whatever the phase", () => {
  const stopped = flow("implementing", { attention: true, attention_reason: "自動執行已停止", automation: { mode: "auto", held: true, step_label: "" } });
  const atMerge = flow("in_review", { attention: true, attention_reason: "停在合併關卡" });
  const approval = flow("awaiting_approval", { attention: true });
  // a phase that sounds like waiting, but the server did not flag it: the page does not re-derive it
  const quiet = flow("awaiting_approval", { attention: false });
  const working = flow("implementing");
  const g = group(live(), flowsOf([working, stopped, quiet, atMerge, approval]));
  assert.deepStrictEqual(ids(g.yourTurnFlows), ids([stopped, atMerge, approval]), "API order is kept");
  assert.deepStrictEqual(ids(g.inProgress), ids([working, quiet]));
  assert.strictEqual(g.moreInProgress, 0);
});

test("a stale review waits for you in manual mode and when the automatic run has stopped, not while it runs", () => {
  const manual = flow("review_stale", { automation: { mode: "manual", held: false } });
  const noAutomation = flow("review_stale", { automation: undefined });
  const held = flow("review_stale", { automation: { mode: "auto", held: true, step_label: "已停止" } });
  const running = flow("review_stale", { automation: { mode: "auto", held: false, step_label: "正在重新送審" } });
  const g = group(live(), flowsOf([manual, held, running, noAutomation]));
  assert.deepStrictEqual(ids(g.yourTurnFlows), ids([manual, held, noAutomation]));
  assert.deepStrictEqual(ids(g.inProgress), ids([running]));
  // the card of the running one shows the runner's own step label
  const card = app.questCard(running, false);
  assert(text(card).includes("自動執行中") && text(card).includes("正在重新送審"));
});

test("a finished flow is never on the board, even when the server still says attention", () => {
  const done = flow("done", { attention: true, attention_reason: "你手動記錄了 push" });
  const doneQuiet = flow("done");
  const g = group(live(), flowsOf([done, doneQuiet]));
  assert.strictEqual(g.yourTurnFlows.length, 0);
  assert.strictEqual(g.inProgress.length, 0);
  assert.strictEqual(g.moreInProgress, 0);
  // two finished flows are flows: the board is empty but it is not the first-run state
  assert.strictEqual(g.allEmpty, false);
});

test("at most 4 other flows, the rest is a count, and the API order is kept", () => {
  const six = Array.from({ length: 6 }, () => flow("implementing"));
  const g = group(live(), flowsOf(six));
  assert.deepStrictEqual(ids(g.inProgress), ids(six.slice(0, 4)));
  assert.strictEqual(g.moreInProgress, 2);
  const four = group(live(), flowsOf(six.slice(0, 4)));
  assert.strictEqual(four.moreInProgress, 0);
  assert.strictEqual(four.inProgress.length, 4);
  // flows waiting for you are not cut at 4
  const turn = Array.from({ length: 5 }, () => flow("awaiting_merge", { attention: true }));
  assert.strictEqual(group(live(), flowsOf(turn)).yourTurnFlows.length, 5);
});

test("a flow whose task card is gone is still a card", () => {
  const f = flow("awaiting_approval", { attention: true, task_missing: true, task_title: "" });
  const g = group(live(), flowsOf([f]));
  assert.strictEqual(g.yourTurnFlows.length, 1);
  assert(text(app.questCard(f, true)).includes("（任務卡已刪除或無法讀取）"));
});

test("agents that wait for you follow the live attention order; an id without a session is dropped", () => {
  const a = session("t-a"), b = session("t-b"), c = session("t-c");
  const g = group(live({ sessions: [a, b, c], attention: ["t-c", "t-gone", "t-a"] }), flowsOf([]));
  assert.deepStrictEqual(g.yourTurnSessions.map((s) => s.terminal_id), ["t-c", "t-a"]);
  assert.strictEqual(g.allEmpty, false);
});

test("a flows error is carried, the lists are empty and the board is not 'all empty'", () => {
  const g = group(live({ sessions: [session("t-a")], attention: ["t-a"] }), { error: "讀不到 flows.json", flows: [] });
  assert.strictEqual(g.error, "讀不到 flows.json");
  assert.deepStrictEqual([g.yourTurnFlows.length, g.inProgress.length, g.moreInProgress], [0, 0, 0]);
  assert.strictEqual(g.allEmpty, false);
  assert.strictEqual(g.yourTurnSessions.length, 1, "the agent is still shown");
  // not loaded at all, or an answer in a shape the page does not know: said, not drawn as empty
  assert(group(live(), null).error);
  assert(group(live(), { ok: true }).error);
  assert.strictEqual(group(live(), null).allEmpty, false);
});

test("runtime not connected: the flag is false and the board is not 'all empty'", () => {
  const g = group(live({ runtime: { available: false, problems: ["x"] } }), flowsOf([]));
  assert.strictEqual(g.runtimeAvailable, false);
  assert.strictEqual(g.allEmpty, false);
  assert.strictEqual(group(null, flowsOf([])).runtimeAvailable, false);
});

test("all empty: flows loaded and empty, no agent waiting, runtime connected", () => {
  const g = group(live(), flowsOf([]));
  assert.strictEqual(g.allEmpty, true);
  assert.strictEqual(g.error, "");
  assert.deepStrictEqual(Object.keys(g).sort(),
    ["allEmpty", "error", "inProgress", "meetingsError", "moreInProgress", "runtimeAvailable", "yourTurnFlows", "yourTurnMeetings", "yourTurnSessions"]);
});

// ---- boardKey -------------------------------------------------------------------------------------------------

const clone = (x) => JSON.parse(JSON.stringify(x));
function keyOf(l, f, ctx) { return app.boardKey(group(l, f), ctx); }

test("the key does not change for the same data and changes for every field the board shows", () => {
  const base = () => ({
    l: live({ sessions: [session("t-a")], attention: ["t-a"] }),
    f: flowsOf([flow("awaiting_approval", { attention: true, attention_reason: "請核准計畫", latest_review: { verdict: "PASS", counts_as_pass: true, commit: "a".repeat(40), why: "" },
      binding: { detail: "HEAD 與審查的 commit 相同" } }), flow("implementing")]),
  });
  const b = base();
  const key = keyOf(b.l, b.f);
  assert.strictEqual(keyOf(base().l, base().f).length > 20, true);
  assert.strictEqual(key, keyOf(clone(b.l), clone(b.f)), "the same data is the same key");

  // each case edits one displayed field of the first (waiting) flow or of the second (in progress) flow
  const turn = (fn) => (x) => fn(x.f.flows[0]);
  const going = (fn) => (x) => fn(x.f.flows[1]);
  const sess = (fn) => (x) => fn(x.l.sessions[0]);
  const cases = {
    "id": turn((f) => { f.id = "flow-changed00000"; }),
    "task_title": turn((f) => { f.task_title = "別的標題"; }),
    "task_missing": turn((f) => { f.task_missing = true; }),
    "phase.key": turn((f) => { f.phase.key = "awaiting_merge"; }),
    "phase.label": turn((f) => { f.phase.label = "等你核准"; }),
    "phase.reason": turn((f) => { f.phase.reason = "另一個說明"; }),
    "attention_reason": turn((f) => { f.attention_reason = "另一個原因"; }),
    "executor role name": turn((f) => { f.roles.executor.name = "別的執行者"; }),
    "executor model": turn((f) => { f.roles.executor.model = "opus"; }),
    "executor family": turn((f) => { f.roles.executor.family_label = "OpenAI（Codex）"; }),
    "reviewer": turn((f) => { f.roles.reviewers[0].name = "別的審查者"; }),
    "second reviewer": turn((f) => { f.roles.reviewers.push({ name: "AGY", family_label: "Google（Gemini）" }); }),
    "executor_live.label": turn((f) => { f.executor_live.label = "閒置"; }),
    "executor_live.reason": turn((f) => { f.executor_live.reason = "沒有新的回應"; }),
    "executor_live.freshness": turn((f) => { f.executor_live.freshness.age_s = 40; }),
    "executor_live missing": turn((f) => { f.executor_live = null; }),
    "review verdict": turn((f) => { f.latest_review.verdict = "NEEDS_WORK"; }),
    "review counts_as_pass": turn((f) => { f.latest_review.counts_as_pass = false; }),
    "review commit": turn((f) => { f.latest_review.commit = "b".repeat(40); }),
    "review gone": turn((f) => { f.latest_review = null; }),
    "binding note": turn((f) => { f.binding.detail = "無法核對 HEAD"; }),
    "automation.mode": going((f) => { f.automation.mode = "auto"; }),
    "automation.held": going((f) => { f.automation.mode = "auto"; f.automation.held = true; }),
    "automation.step_label": going((f) => { f.automation.mode = "auto"; f.automation.step_label = "送審中"; }),
    "attention flips the group": going((f) => { f.attention = true; }),
    "in progress phase": going((f) => { f.phase.label = "審查第 3 輪"; }),
    "a flow appears": (x) => { x.f.flows.push(flow("planning")); },
    "a flow goes": (x) => { x.f.flows.pop(); },
    "order": (x) => { x.f.flows.reverse(); },
    "session terminal_id": (x) => { x.l.sessions[0].terminal_id = "t-z"; x.l.attention = ["t-z"]; },
    "session status": sess((s) => { s.status = "working"; }),
    "session title": sess((s) => { s.title = "別的標題"; }),
    "session activity": sess((s) => { s.activity = { reason: "新的原因", evidence: [] }; }),
    "session role label": sess((s) => { s.role_label = "別的名字"; }),
    "session agent": sess((s) => { s.agent = "codex"; }),
    "session models": sess((s) => { s.models_observed = { "gpt-6": 1 }; }),
    "session skills used": sess((s) => { s.skills_used = [{ label: "code-review", count: 1, evidence: "explicit" }]; }),
    "session pane": sess((s) => { s.pane_id = "t-other"; }),
    "session workspace": sess((s) => { s.workspace_label = "另一個工作區"; }),
    "session project id": sess((s) => { s.project_id = "p2"; }),
    "project name": (x) => { x.l.projects[0].name = "改名的專案"; },
    "an agent stops waiting": (x) => { x.l.attention = []; },
  };
  for (const [name, edit] of Object.entries(cases)) {
    const x = base();
    edit(x);
    // keep the project list in step with the live object the key reads by default
    const ctx = { projects: x.l.projects };
    assert.notStrictEqual(keyOf(x.l, x.f, ctx), keyOf(b.l, b.f, { projects: b.l.projects }), `the key changes with: ${name}`);
  }
});

test("the key also carries the error, the runtime flag, the live error and the count of the rest", () => {
  const l = live();
  const f = flowsOf([flow("implementing")]);
  const key = app.boardKey(group(l, f), { liveError: "", projects: l.projects });
  assert.notStrictEqual(key, app.boardKey(group(l, f), { liveError: "讀取即時狀態逾時", projects: l.projects }), "live.error rewords the session column");
  assert.notStrictEqual(key, app.boardKey(group(l, { error: "壞了", flows: [] }), { liveError: "", projects: l.projects }));
  assert.notStrictEqual(key, app.boardKey(group(live({ runtime: { available: false, problems: [] } }), f), { liveError: "", projects: l.projects }));
  const many = flowsOf(Array.from({ length: 5 }, () => flow("implementing")));
  const more = flowsOf([...many.flows, flow("implementing")]);
  assert.notStrictEqual(app.boardKey(group(l, many), { projects: [] }), app.boardKey(group(l, more), { projects: [] }),
    "a 6th flow that is not drawn still changes the 'N more' count");
  // the failing live load makes the executor column say so
  const liveFlow = flow("implementing");
  const withErr = app.boardKey(group(l, flowsOf([liveFlow])), { liveError: "boom", projects: [] });
  assert.notStrictEqual(withErr, app.boardKey(group(l, flowsOf([liveFlow])), { liveError: "", projects: [] }));
});

// ---- questCard ------------------------------------------------------------------------------------------------

const INTERACTIVE = new Set(["a", "button", "input", "select", "textarea", "summary", "details"]);

test("a flow card is one article with one link, and nothing interactive inside", () => {
  const f = flow("awaiting_merge", { attention: true, attention_reason: "審查通過，等你合併",
    latest_review: { verdict: "PASS", counts_as_pass: true, commit: "c".repeat(40), why: "" } });
  for (const yourTurn of [true, false]) {
    const card = app.questCard(f, yourTurn);
    assert.strictEqual(card.tag, "article");
    assert(card.hasClass("card"));
    const links = card.findAll(isEl("a"));
    assert.strictEqual(links.length, 1, "exactly one link");
    assert.strictEqual(links[0].getAttribute("href"), `#/flows/${f.id}`);
    assert.strictEqual(text(links[0]), f.task_title, "the link is the title");
    const inner = card.findAll((n) => INTERACTIVE.has(n.tag));
    assert.strictEqual(inner.length, 1, "no nested interactive element: " + inner.map((n) => n.tag).join(","));
    assert.strictEqual(card.findAll((n) => n.getAttribute && n.getAttribute("tabindex") !== null).length, 0);
  }
});

test("the type label is the phase's own label, its icon is hidden, the action hint is plain text", () => {
  for (const key of ["awaiting_approval", "awaiting_merge", "review_unverified", "awaiting_push", "in_review", "review_stale"]) {
    const f = flow(key, { attention: true });
    const card = app.questCard(f, true);
    const type = card.find((n) => n.hasClass && n.hasClass("quest-type"));
    assert(type, key);
    assert.strictEqual(text(type), PHASE_LABEL[key], "the label is not reworded");
    const svg = type.find(isEl("svg"));
    assert(svg && svg.getAttribute("aria-hidden") === "true");
    assert.strictEqual(svg.getAttribute("focusable"), "false");
    assert(card.hasClass("quest-turn"));
    assert(text(card).includes("前往處理 →"));
    assert(!text(card).includes("查看流程"));
  }
  const going = app.questCard(flow("implementing"), false);
  assert(going.hasClass("quest-going") && !going.hasClass("quest-turn"));
  assert(text(going).includes("查看流程 →") && !text(going).includes("前往處理"));
  const goBox = going.find((n) => n.hasClass && n.hasClass("quest-go"));
  assert.strictEqual(goBox.findAll((n) => INTERACTIVE.has(n.tag)).length, 0);
});

test("the explanation is the attention reason, else the phase's reason, as given", () => {
  const withReason = app.questCard(flow("awaiting_merge", { attention: true, attention_reason: "停在合併關卡" }), true);
  assert(text(withReason).includes("停在合併關卡"));
  const plain = flow("implementing");
  assert(text(app.questCard(plain, false)).includes("實作中的說明"));
});

test("each mode says what it is: automatic running, automatic stopped, manual", () => {
  const auto = text(app.questCard(flow("implementing", { automation: { mode: "auto", held: false, step_label: "派工給執行者" } }), false));
  assert(auto.includes("自動執行中") && auto.includes("派工給執行者") && !auto.includes("手動模式"));
  const held = text(app.questCard(flow("implementing", { automation: { mode: "auto", held: true, step_label: "已停止：額度用完" } }), false));
  assert(held.includes("自動（已停止）") && held.includes("已停止：額度用完"));
  const manual = text(app.questCard(flow("implementing"), false));
  assert(manual.includes("手動模式：VBear 不會替你推進，下一步由你或你啟動的角色處理"));
  // a waiting card of a stopped automatic flow carries the stopped tag too
  const heldTurn = text(app.questCard(flow("implementing", { attention: true, automation: { mode: "auto", held: true, step_label: "" } }), true));
  assert(heldTurn.includes("自動（已停止）"));
  const manualTurn = text(app.questCard(flow("awaiting_approval", { attention: true }), true));
  assert(!manualTurn.includes("手動模式：VBear"), "the waiting card says what to do, not the mode sentence");
});

test("a hostile name or title is text, not an element", () => {
  const f = flow("awaiting_approval", { attention: true, task_title: "<img src=x onerror=alert(1)>",
    roles: { planner: { name: "p" }, executor: { name: "<script>1</script>", family_label: "不明" }, reviewers: [{ name: "<b>r</b>" }] } });
  const card = app.questCard(f, true);
  assert.strictEqual(card.findAll((n) => n.tag === "img" || n.tag === "script" || n.tag === "b" && n.parentNode && n.parentNode.tag !== "span").length, 0);
  assert(text(card).includes("<img src=x onerror=alert(1)>"));
});

test("flowCard and sessionCard keep their own structure for the other pages", () => {
  const f = flow("awaiting_approval", { attention: true });
  const fc = app.flowCard(f);
  assert.strictEqual(fc.tag, "a");
  assert(fc.hasClass("card"));
  assert.strictEqual(fc.getAttribute("href"), `#/flows/${f.id}`);
  assert(!fc.hasClass("quest"));
  const sc = app.sessionCard(session("t-a"));
  assert.strictEqual(sc.tag, "div");
  assert(sc.hasClass("card") && !sc.hasClass("quest"));
  assert(text(sc).includes("狀態依據") && text(sc).includes("開啟終端"));
});

// ---- the page -------------------------------------------------------------------------------------------------

let handlerState;
function setPage(over = {}) {
  handlerState = { live: live(), flows: flowsOf([]), liveError: null, ...over };
  setHandler((url) => {
    const p = url.split("?")[0];
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return handlerState.liveError ? jsonResponse({ error: handlerState.liveError }, false, 500) : jsonResponse(handlerState.live);
    if (p === "/api/flows") return handlerState.flowsError ? jsonResponse({ error: handlerState.flowsError }, false, 500) : jsonResponse(handlerState.flows);
    if (p === "/api/agent-profiles" && handlerState.profiles) return jsonResponse({ ok: true, profiles: handlerState.profiles });
    if (p === "/api/agent-builder/catalog" && handlerState.catalog) return jsonResponse(handlerState.catalog);
    if (p === "/api/tasks" && handlerState.tasks) return jsonResponse({ ok: true, tasks: handlerState.tasks });
    if (p === "/api/config" && handlerState.config) return jsonResponse({ ok: true, config: handlerState.config });
    return null;
  });
}
let tick = null;
async function open() {
  const realSetInterval = global.setInterval;
  tick = null;
  global.setInterval = (fn) => { tick = fn; return 0; };
  global.location.hash = "#/";
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
async function refresh() { assert(tick, "the home page registered a refresh"); tick(); await settle(); }
const board = (main) => main.find((n) => n.getAttribute && n.getAttribute("id") === "h-board");
const headings = (main) => main.findAll(isEl("h2")).map(text);

test("the page is the lobby: title, lede, and the board before the search", async () => {
  setPage({ flows: flowsOf([flow("awaiting_approval", { attention: true })]) });
  const main = await open();
  assert.strictEqual(text(main.find(isEl("h1"))), "冒險者大廳");
  assert(text(main).includes("這裡看哪些任務在等你、隊伍走到哪一步。"));
  assert(!text(main).includes("先看告示板上輪到你的任務"));
  const hs = headings(main);
  assert.deepStrictEqual(hs.slice(0, 2), ["輪到你", "其他進行中的任務"]);
  assert(hs.indexOf("找技能") > hs.indexOf("其他進行中的任務"), "the search stays after the board");
  assert(hs.includes("最近的專案"));
  assert(!text(main).includes("需要你處理"), "the old block is gone");
});

test("opening the lobby does not put the cursor in the skill search (it would scroll the page)", async () => {
  setPage({ flows: flowsOf([flow("awaiting_approval", { attention: true })]) });
  global.document.activeElement = null;
  const main = await open();
  await sleep(20);
  const search = main.find((n) => n.tag === "input" && n.getAttribute("type") === "search");
  assert(search, "the search box is still on the page");
  assert(!search._focused && global.document.activeElement !== search, "the search box is not focused on arrival");
  assert(!/setTimeout\(\(\) => input\.focus\(\)/.test(fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8")), "no deferred focus call on the lobby search");
});

test("the nav's first item is renamed and the others are not", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8");
  assert(/data-nav="home"><span aria-hidden="true">⌂<\/span>冒險者大廳</.test(html));
  assert(!html.includes("我的工作台"));
  for (const label of ["終端機", "終端工作台", "流程", "技能庫", "角色卡池", "專案", "設定"]) assert(html.includes(`</span>${label}</a>`), label);
});

test("flows and agents share the first block: the flows come first, in API order", async () => {
  const a = flow("awaiting_approval", { attention: true });
  const b = flow("awaiting_merge", { attention: true });
  setPage({ flows: flowsOf([a, b, flow("implementing")]),
    live: live({ sessions: [session("t-a")], attention: ["t-a"] }) });
  const main = await open();
  const turn = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "turn");
  const cards = turn.findAll((n) => n.hasClass && n.hasClass("card"));
  assert.strictEqual(cards.length, 3);
  assert.deepStrictEqual(cards.slice(0, 2).map((c) => c.getAttribute("data-flow-id")), [a.id, b.id]);
  assert.strictEqual(cards[2].tag, "div", "the agent's card is the existing session card");
  assert(text(turn).includes("1 個終端在等你") && text(turn).includes("2 則流程等你"));
  assert(text(turn).includes("每 5 秒更新") && text(turn).includes("角色卡池"));
  const going = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "going");
  assert.strictEqual(going.findAll((n) => n.getAttribute && n.getAttribute("data-quest") === "flow").length, 1);
});

test("more than 4 other flows: four cards and a link for the rest", async () => {
  setPage({ flows: flowsOf(Array.from({ length: 7 }, () => flow("implementing"))) });
  const main = await open();
  const going = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "going");
  assert.strictEqual(going.findAll((n) => n.getAttribute && n.getAttribute("data-quest") === "flow").length, 4);
  const more = going.find((n) => n.hasClass && n.hasClass("quest-more"));
  assert.strictEqual(text(more), "還有 3 則 →");
  assert.strictEqual(more.getAttribute("href"), "#/flows");
});

test("a flows error says so in both blocks, is not 'no tasks', and the agent card stays", async () => {
  setPage({ flowsError: "讀不到 flows.json", live: live({ sessions: [session("t-a")], attention: ["t-a"] }) });
  const main = await open();
  const b = text(board(main));
  assert.strictEqual(b.split("讀不到流程：讀不到 flows.json").length - 1, 2, "once in each block");
  assert(!b.includes("沒有輪到你的任務") && !b.includes("沒有其他進行中的任務") && !b.includes("大廳目前沒有任務"));
  const turn = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "turn");
  const going = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "going");
  // each block holds its own copy: one node is never in two parents (the fake DOM moves a node like the real one)
  for (const [name, block] of [["輪到你", turn], ["其他進行中", going]]) {
    assert.strictEqual(text(block).split("讀不到流程：讀不到 flows.json").length - 1, 1, `${name} has the error text`);
  }
  const notices = board(main).findAll((n) => n.hasClass && n.hasClass("notice"));
  assert.strictEqual(notices.length, 2);
  assert.notStrictEqual(notices[0], notices[1], "two nodes");
  assert.notStrictEqual(notices[0].parentNode, notices[1].parentNode);
  assert(text(turn).includes("Claude 工人"), "the agent is still drawn");
  // no agent either: still no 'no tasks'
  setPage({ flowsError: "讀不到 flows.json" });
  const again = await open();
  const t2 = text(board(again));
  assert(t2.includes("讀不到流程：") && !t2.includes("沒有輪到你的任務") && !t2.includes("大廳目前沒有任務"));
});

test("runtime not connected and no flow card: the board says it cannot tell whether an agent waits", async () => {
  setPage({ live: live({ runtime: { available: false, problems: ["連不上"] } }), flows: flowsOf([flow("implementing")]) });
  const main = await open();
  const turn = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "turn");
  assert(text(turn).includes("VBear runtime 未連線，無法判斷有沒有終端在等你"));
  assert(!text(turn).includes("沒有輪到你的任務"));
  assert(text(main).includes("無法連線到 VBear runtime"), "the page notice is kept");
  assert(!text(board(main)).includes("大廳目前沒有任務"));
});

test("a failed live load is not drawn as an empty lobby either", async () => {
  setPage({ liveError: "背景程序沒有回應" });
  const main = await open();
  assert(text(board(main)).includes("無法判斷有沒有終端在等你"));
  assert(!text(board(main)).includes("大廳目前沒有任務"));
});

test("connected, nobody waiting, flows in progress: both empty sentences are the real ones", async () => {
  setPage({ flows: flowsOf([flow("implementing")]) });
  let main = await open();
  const turn = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "turn");
  assert(text(turn).includes("告示板上目前沒有輪到你的任務"));
  assert(text(turn).includes("狀態未知"), "the existing explanation of who can be judged");
  // finished flows only: nothing in progress
  setPage({ flows: flowsOf([flow("done")]) });
  main = await open();
  const going = main.find((n) => n.getAttribute && n.getAttribute("data-board") === "going");
  assert(text(going).includes("目前沒有其他進行中的任務"));
  assert(!text(board(main)).includes("想開始第一個任務"));
});

test("all empty: one start block that points at the terminal workbench and explains the task card first", async () => {
  setPage();
  const main = await open();
  const b = board(main);
  assert(text(b).includes("大廳目前沒有任務。想開始第一個任務？"));
  const links = b.findAll(isEl("a"));
  assert.strictEqual(links.length, 1);
  assert.strictEqual(links[0].getAttribute("href"), "#/workbench");
  assert.strictEqual(text(links[0]), "到終端工作台");
  assert(text(b).includes("先按下方「＋ 任務卡（導入專案）」挑一個專案資料夾，再把角色卡放上任務卡的隊伍位置"));
  assert(!text(b).includes("右側「任務卡」分頁"));
  assert(!headings(main).includes("輪到你"), "the two blocks are replaced by the start block");
});

test("a refresh repaints the board only when something it shows changed, and the search keeps its focus", async () => {
  const f = flow("awaiting_approval", { attention: true });
  const other = flow("implementing");
  setPage({ flows: flowsOf([f, other]) });
  const main = await open();
  const box = board(main);
  const search = main.find((n) => n.tag === "input" && n.getAttribute("type") === "search");
  assert(search);
  search.focus();
  assert.strictEqual(global.document.activeElement, search);
  const before = box.children.slice();
  await refresh();
  assert.strictEqual(box.children.length, before.length);
  assert(box.children.every((c, i) => c === before[i]), "same data: the same nodes, no repaint");
  // a visible change: the executor's live label
  handlerState.flows = flowsOf([{ ...f, executor_live: { label: "閒置", reason: "沒有新的回應" } }, other]);
  await refresh();
  assert(box.children.some((c, i) => c !== before[i]), "a changed field repaints");
  assert(text(box).includes("閒置"));
  assert.strictEqual(global.document.activeElement, search, "the search box is untouched and keeps focus");
  // the live load fails on the next refresh: the executor column is reworded, so the board repaints
  const painted = box.children.slice();
  handlerState.liveError = "逾時";
  await refresh();
  assert(box.children.some((c, i) => c !== painted[i]), "live.error changes what the executor column says");
  assert(text(box).includes("即時狀態未載入"));
});

test("runtime already away: only the live error's words change, and the board repaints with them", async () => {
  const f = flow("awaiting_approval", { attention: true });
  const other = flow("implementing");
  setPage({ liveError: "逾時了", flows: flowsOf([f, other]) });
  const main = await open();
  const box = board(main);
  const titled = (text) => box.findAll((n) => n.getAttribute && (n.getAttribute("title") || "").includes(text));
  assert(titled("這次讀取即時狀態失敗：逾時了").length >= 2, "the executor column carries the live error");
  assert(text(box).includes("VBear runtime 未連線") || text(box).includes("即時狀態未載入"));
  const before = box.children.slice();
  // same data again: no repaint
  await refresh();
  assert(box.children.every((c, i) => c === before[i]), "nothing changed, nothing repainted");
  // only the live error's text changes: the runtime stays away, the flows are the same
  handlerState.liveError = "拒絕連線";
  await refresh();
  assert(box.children.some((c, i) => c !== before[i]), "the board was repainted");
  assert.strictEqual(titled("逾時了").length, 0, "the old words are gone");
  assert(titled("這次讀取即時狀態失敗：拒絕連線").length >= 2, "the new words are shown");
  // the key's default reads the same values the page passes
  const g = group(handlerState.live, handlerState.flows);
  const ctx = app.boardKeyContext();
  assert.strictEqual(ctx.liveError, "拒絕連線");
  assert.strictEqual(app.boardKey(g), app.boardKey(g, ctx), "without a context the key reads the live error itself");
  assert.notStrictEqual(app.boardKey(g, ctx), app.boardKey(g, { ...ctx, liveError: "" }));
});

test("the CSS defines the new tokens in light and in both dark blocks, with enough contrast", () => {
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
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
    for (const token of ["quest-edge", "quest-bar", "quest-ok", "quest-warn", "quest-mute"]) assert(v[token], `${name} defines --${token}`);
    // the frame and the bar are shapes: 3:1 against the card and the page
    for (const t of ["quest-edge", "quest-bar"]) {
      assert(ratio(v[t], v.panel) >= 3, `${name} --${t} on the card: ${ratio(v[t], v.panel)}`);
      assert(ratio(v[t], v.bg) >= 3, `${name} --${t} on the page: ${ratio(v[t], v.bg)}`);
    }
    // the badge words are text: 4.5:1 on their soft background
    for (const t of ["ok", "warn", "mute"]) assert(ratio(v["quest-" + t], v[t + "-soft"]) >= 4.5, `${name} --quest-${t}: ${ratio(v["quest-" + t], v[t + "-soft"])}`);
    // the text inside the card: the second ink and the accent action hint on the card's own background
    assert(ratio(v["ink-2"], v.panel) >= 4.5, `${name} ink-2`);
    assert(ratio(v.accent, v.panel) >= 4.5, `${name} accent`);
    for (const t of ["bad", "info"]) assert(ratio(v[t], v[t + "-soft"]) >= 4.5, `${name} --${t}: ${ratio(v[t], v[t + "-soft"])}`);
  }
});


// ---- the first game (design card-play 3.8) and the bulletin ---------------------------------------------------

const catalogOf = () => ({ ok: true, demo_id_prefix: "demo-" });
const mkCard = (id) => ({ id, name: id, model: { tool: "claude", model_id: "" }, equipped_skill_ids: [], permission_intents: {} });
const taskOf = (id, workdir) => ({ id, title: `卡 ${id}`, status: "open", workdir });
const stateOf = (over = {}) => app.onboardingState({ profiles: [], catalog: catalogOf(), tasks: [], flows: [], dismissed: false, ...over });
const stepsDone = (st) => st.steps.map((x) => x.done);
const onboard = (main) => main.find((n) => n.getAttribute && n.getAttribute("id") === "h-onboarding");

test("onboardingState: unreadable data or a dismissed block shows nothing; a guess is never drawn", () => {
  const base = { profiles: [], catalog: catalogOf(), tasks: [], flows: [], dismissed: false };
  assert.strictEqual(app.onboardingState(base).mode, "steps");
  for (const key of ["profiles", "tasks", "flows", "dismissed"]) {
    for (const bad of [null, undefined, "x", {}, 3]) {
      if (key === "dismissed" && bad === null) continue;
      assert.strictEqual(app.onboardingState({ ...base, [key]: bad }).mode, "none", `${key}=${String(bad)}`);
    }
  }
  for (const nope of [undefined, null, 5, "x", []]) assert.strictEqual(app.onboardingState(nope).mode, "none");
  assert.strictEqual(app.onboardingState({ ...base, dismissed: true }).mode, "none");
  assert.strictEqual(app.onboardingSection(app.onboardingState({ ...base, dismissed: true })), null);
});

test("onboardingState: each step is ticked from data the server has", () => {
  assert.deepStrictEqual([...stepsDone(stateOf())], [false, false, false]);
  // a sample card is not a card of your own
  assert.deepStrictEqual([...stepsDone(stateOf({ profiles: [mkCard("demo-a"), mkCard("demo-b")] }))], [false, false, false]);
  assert.deepStrictEqual([...stepsDone(stateOf({ profiles: [mkCard("demo-a"), mkCard("mine")] }))], [true, false, false]);
  // a task card counts when it has a folder
  assert.deepStrictEqual([...stepsDone(stateOf({ tasks: [taskOf("t1", null), taskOf("t2", "")] }))], [false, false, false]);
  assert.deepStrictEqual([...stepsDone(stateOf({ tasks: [taskOf("t1", "/p/one")] }))], [false, true, false]);
  // a team counts when a flow has a planner and an executor
  const withTeam = flow("planning");
  assert.deepStrictEqual([...stepsDone(stateOf({ flows: [withTeam] }))], [false, false, true]);
  assert.deepStrictEqual([...stepsDone(stateOf({ flows: [flow("planning", { roles: {} })] }))], [false, false, false]);
  assert.deepStrictEqual([...app.onboardingState({ profiles: [mkCard("a")], catalog: null, tasks: [taskOf("t1", "/p")], flows: [], dismissed: false }).steps.map((x) => x.key)], ["cards", "task", "team"]);
});

test("onboardingState: all three done folds to one line with the current step of the flow that waits for you", () => {
  const quiet = flow("implementing");
  const waiting = flow("awaiting_approval", { attention: true });
  const all = { profiles: [mkCard("mine")], tasks: [taskOf("t1", "/p/one")] };
  const st = stateOf({ ...all, flows: [quiet, waiting] });
  assert.strictEqual(st.mode, "done");
  assert.strictEqual(st.next, app.nextStepSummary(waiting));
  assert(st.next.startsWith("下一步："));
  assert.strictEqual(stateOf({ ...all, flows: [quiet] }).next, app.nextStepSummary(quiet));
  // only a finished flow, or a phase the table does not know: the line has no next step to say
  assert.strictEqual(stateOf({ ...all, flows: [flow("done")] }).next, "");
  assert.strictEqual(stateOf({ ...all, flows: [flow("mystery")] }).next, "");
});

test("the page: the three steps sit above the board, the next undone step has the only button, 先不要 is there", async () => {
  setPage({ profiles: [], catalog: catalogOf(), tasks: [], config: { onboarding_dismissed: false } });
  const main = await open();
  const host = onboard(main);
  assert(host, "the block is on the page");
  const hs = headings(main);
  assert.strictEqual(hs[0], "新手第一局", "above the board");
  const html = main.findAll((n) => n.getAttribute && n.getAttribute("data-step")).map((n) => [n.getAttribute("data-step"), n.getAttribute("data-done")]);
  assert.deepStrictEqual(html, [["cards", "false"], ["task", "false"], ["team", "false"]]);
  assert(text(host).includes("1. 拿角色卡") && text(host).includes("2. 導入專案，建立任務卡") && text(host).includes("3. 把隊伍放上任務卡"));
  const gos = host.findAll((n) => n.getAttribute && n.getAttribute("data-onboard-go"));
  assert.deepStrictEqual(gos.map((n) => n.getAttribute("data-onboard-go")), ["cards"], "one button, on the first step that is not done");
  assert.strictEqual(gos[0].getAttribute("href"), "#/team");
  assert(host.find((n) => n.getAttribute && n.getAttribute("data-onboard") === "dismiss"));
  assert(!/安全|已限制|保證/.test(text(host)));
});

test("the page: steps tick from the server's data, and the button moves on to the step that is next", async () => {
  setPage({ profiles: [mkCard("mine")], catalog: catalogOf(), tasks: [], config: { onboarding_dismissed: false } });
  let main = await open();
  assert.deepStrictEqual(main.findAll((n) => n.getAttribute && n.getAttribute("data-step")).map((n) => n.getAttribute("data-done")), ["true", "false", "false"]);
  assert.deepStrictEqual(onboard(main).findAll((n) => n.getAttribute && n.getAttribute("data-onboard-go")).map((n) => n.getAttribute("data-onboard-go")), ["task"]);
  setPage({ profiles: [mkCard("mine")], catalog: catalogOf(), tasks: [taskOf("t-1", "/p/one")], config: { onboarding_dismissed: false } });
  main = await open();
  const go = onboard(main).findAll((n) => n.getAttribute && n.getAttribute("data-onboard-go"));
  assert.deepStrictEqual(go.map((n) => n.getAttribute("data-onboard-go")), ["team"]);
  assert.strictEqual(go[0].getAttribute("href"), "#/workbench?task=t-1");
});

test("the page: 先不要 saves onboarding_dismissed and the block goes away; the board stays", async () => {
  const posts = [];
  setPage({ profiles: [], catalog: catalogOf(), tasks: [], config: { onboarding_dismissed: false } });
  const inner = global.fetch;
  global.fetch = async (url, options) => {
    if (url === "/api/config" && options && options.method === "POST") {
      posts.push(JSON.parse(options.body));
      return { ok: true, status: 200, json: async () => ({ ok: true, config: { onboarding_dismissed: true } }) };
    }
    return inner(url, options);
  };
  try {
    const main = await open();
    const dismiss = onboard(main).find((n) => n.getAttribute && n.getAttribute("data-onboard") === "dismiss");
    dismiss.dispatch ? dismiss.dispatch("click") : dismiss._listeners.click.forEach((f) => f({ preventDefault() {} }));
    await settle();
    assert.deepStrictEqual(posts, [{ onboarding_dismissed: true }]);
    assert.strictEqual(onboard(main).children.length, 0, "nothing left");
    assert(board(main), "the board is still there");
  } finally { global.fetch = inner; }
});

test("the page: a dismissed block, or a config that cannot be read, shows nothing", async () => {
  setPage({ profiles: [], catalog: catalogOf(), tasks: [], config: { onboarding_dismissed: true } });
  assert.strictEqual(onboard(await open()).children.length, 0);
  setPage({ profiles: [], catalog: catalogOf(), tasks: [] });   // /api/config answers nothing usable
  assert.strictEqual(onboard(await open()).children.length, 0);
  setPage({ tasks: [], config: { onboarding_dismissed: false } });   // the cards could not be read
  assert.strictEqual(onboard(await open()).children.length, 0);
});

test("the page: with all three done it is one line, 你的小隊已就位 · 下一步", async () => {
  const waiting = flow("awaiting_approval", { attention: true });
  setPage({ profiles: [mkCard("mine")], catalog: catalogOf(), tasks: [taskOf("t-1", "/p/one")], flows: flowsOf([waiting]), config: { onboarding_dismissed: false } });
  const main = await open();
  const host = onboard(main);
  const line = host.find((n) => n.getAttribute && n.getAttribute("data-onboarding") === "done");
  assert(line, "the folded line");
  assert.strictEqual(text(line.find((n) => n.hasClass && n.hasClass("onboard-line"))), `你的小隊已就位 · ${app.nextStepSummary(waiting)}`);
  assert(!host.find((n) => n.getAttribute && n.getAttribute("data-step")), "no steps any more");
  assert(host.find((n) => n.getAttribute && n.getAttribute("data-onboard") === "dismiss"), "it can be put away too");
});

test("settings: the block can be brought back (or put away) from the settings page", async () => {
  const saved = [];
  const saveConf = async (body, msg) => { saved.push([body, msg]); return { config: body }; };
  const hidden = app.onboardingSettings({ onboarding_dismissed: true }, saveConf);
  assert(text(hidden).includes("新手第一局") && text(hidden).includes("目前已收起"));
  const showBtn = hidden.find((n) => n.getAttribute && n.getAttribute("data-onboard") === "show");
  assert.strictEqual(text(showBtn), "重新顯示大廳的新手第一局");
  const shown = app.onboardingSettings({ onboarding_dismissed: false }, saveConf);
  const hideBtn = shown.find((n) => n.getAttribute && n.getAttribute("data-onboard") === "hide");
  assert.strictEqual(text(hideBtn), "不要再顯示新手第一局");
  assert(text(shown).includes("三步都完成後會收成一行"));
});

test("the bulletin: a flow card shows its team's avatars and whose turn the next step is; the key repaints when they change", () => {
  const f = flow("awaiting_approval", { attention: true });
  const card = app.questCard(f, true);
  const avatars = card.find((n) => n.getAttribute && n.getAttribute("data-team") === "avatars");
  assert(avatars, "the team's avatars");
  assert(avatars.hasClass("team-avatars-compact"), "compact on the board: the card names its roles already");
  const heads = avatars.findAll((n) => n.getAttribute && n.getAttribute("data-position"));
  assert.deepStrictEqual(heads.map((n) => n.getAttribute("data-position")), ["規劃", "執行", "審查1"]);
  assert(heads.every((n) => /：./.test(n.getAttribute("title"))), "the role's name stays in the tooltip");
  assert.strictEqual(text(heads[0]), "規劃", "only the place is written under the head");
  const next = card.find((n) => n.getAttribute && n.getAttribute("data-quest") === "next");
  assert(next && text(next) === app.nextStepSummary(f));
  assert(/輪到/.test(text(next)));
  // a phase the table does not know says nothing about the next step
  const odd = app.questCard(flow("mystery"), false);
  assert(!odd.find((n) => n.getAttribute && n.getAttribute("data-quest") === "next"));
  // the repaint key reads them
  const key = (x) => app.boardKey(group(live(), flowsOf([x])), { liveError: "", projects: [] });
  const g = flow("awaiting_approval", { attention: true });
  assert.strictEqual(key(f).includes("輪到"), true);
  const other = flow("awaiting_approval", { attention: true, roles: { ...g.roles, planner: { name: "另一位規劃者", family_label: "x" } } });
  other.id = f.id;
  assert.notStrictEqual(key(f), key(other), "a changed planner repaints");
  const later = flow("implementing", { attention: true }); later.id = f.id;
  assert.notStrictEqual(key(f), key(later), "a changed next step repaints");
});

test("source: the first-game block is built with el(), no innerHTML, no emoji, no outside resource", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const blockSrc = src.slice(src.indexOf("// ---------- the first game"), src.indexOf("// ---------- the office (design office v1.3)"));
  assert(blockSrc.length > 2000);
  assert(!/innerHTML|insertAdjacentHTML/.test(blockSrc));
  assert(!/\p{Extended_Pictographic}/u.test(blockSrc));
  assert(!/https?:\/\//.test(blockSrc));
  assert(!/稀有|星數|抽卡|等級|血量|分數|安全|已限制|保證/.test(blockSrc), "no rarity, levels or promises in the first game");
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
  for (const sel of [".onboard-steps", ".onboard-step", ".onboard-done", ".quest-next"]) assert(css.includes(sel), sel);
  assert(/\.onboard-text\s*\{[^}]*overflow-wrap:\s*anywhere/.test(css));
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
