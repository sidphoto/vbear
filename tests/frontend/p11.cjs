// P11 (v0.8.0): after a launch, and who is at the keyboard. A terminal this tab has just started takes the keyboard on its own
// (only then, only once, only for two minutes, only from memory); any other terminal is watched until the person takes over,
// and the takeover says what it means; a card made by a hand-over says where it came from; the workbench with no terminal is
// a page of cards; the engineering columns are behind 進階. The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/p11.cjs   (exit code 0 = pass)
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
const isButton = (label) => (n) => n.tag === "button" && n.textContent === label;
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const closeDialogs = () => { for (const d of h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop"))) d.remove(); };
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));

// minimal xterm.js / fit addon, so the terminal pages get as far as connecting a stream
class FakeTerminal { constructor() { this.cols = 80; this.rows = 24; } loadAddon() {} open() {} onData() {} dispose() {} focus() {} write() {} scrollToBottom() {} }
class FakeFitAddon { fit() {} proposeDimensions() { return null; } }
global.Terminal = FakeTerminal;
global.FitAddon = FakeFitAddon;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const OVERVIEW = { ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] };
const PANE = "n-0123456789ab";
const OTHER = "n-ba9876543210";
const WORKDIR = "/tmp/p11-work";
const posts = () => FETCH_LOG.filter((c) => c.method === "POST");
const takeovers = () => posts().filter((c) => /\/api\/term\/[^/]+\/control$/.test(c.url.split("?")[0]) && c.body && c.body.action === "takeover");
const releases = () => posts().filter((c) => /\/api\/term\/[^/]+\/control$/.test(c.url.split("?")[0]) && c.body && c.body.action === "release");

function liveWith(over = {}) {
  return { runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] }, ...over };
}
const roleLive = (status = "waiting", extraPane = {}) => liveWith({
  sessions: [{ terminal_id: PANE, pane_id: PANE, agent: "claude", status, role_label: "CEO" }],
  panes: [{ pane_id: PANE, kind: "agent", ...extraPane }] });
function flowView(phase, label, over = {}) {
  return { id: "flow-000000000001", task_id: "task-1", task_title: "整理首頁文案", phase: { key: phase, label, reason: "" },
    automation: { mode: "manual" },
    roles: { planner: { name: "CEO", family: "anthropic", profile_id: "p-ceo" }, executor: { name: "工匠", family: "anthropic", profile_id: "p-maker" },
      reviewers: [{ name: "審查員", family: "openai", profile_id: "p-rev" }] }, ...over };
}
const mkTask = (over = {}) => ({ id: "task-1", title: "整理首頁文案", template: "custom", goal: "", scope: [], out_of_scope: [], deliverables: [],
  acceptance_criteria: [], evidence: [], steps: [], artifacts: [], status: "draft", workdir: WORKDIR,
  provenance: { agent: "pending", tests: "untested", human: "pending", verified: false, verification_asserted: false },
  associated_pane_id: null, pickup: { state: "unclaimed", detail: "" }, created_at: 1, updated_at: 1, ...over });

// What the server answers; a test changes pieces through `over` (keys are "METHOD /path").
function server(state) {
  const sseOk = () => ({ ok: true, status: 200, body: { getReader: () => ({ read: () => new Promise(() => {}) }) } });
  return (url, opts = {}) => {
    const p = String(url).split("?")[0];
    const m = (opts.method || "GET").toUpperCase();
    const key = `${m} ${p}`;
    if (state.over && state.over[key]) return state.over[key](url, opts);
    if (/^\/api\/term\/[^/]+\/stream$/.test(p)) return state.stream ? state.stream() : sseOk();
    if (m === "POST" && /^\/api\/term\/[^/]+\/control$/.test(p)) {
      const body = JSON.parse(opts.body || "{}");
      return jsonResponse(body.action === "takeover" ? { ok: true, token: "tok-1" } : { ok: true });
    }
    if (m === "POST" && /^\/api\/tasks\/[^/]+$/.test(p)) {
      const body = JSON.parse(opts.body || "{}");
      return jsonResponse({ ok: true, task: { ...((state.tasks || []).find((t) => p.endsWith("/" + t.id)) || mkTask()), ...body } });
    }
    if (m === "GET" && p === "/api/overview") return jsonResponse(OVERVIEW);
    if (m === "GET" && p === "/api/live") return jsonResponse(state.live || liveWith());
    if (m === "GET" && p === "/api/tasks") return state.tasksError ? jsonResponse({ error: "down" }, false, 500) : jsonResponse({ ok: true, tasks: state.tasks || [] });
    if (m === "GET" && p === "/api/flows") return state.flowsError ? jsonResponse({ error: "down" }, false, 500) : jsonResponse({ ok: true, flows: state.flows || [] });
    if (m === "GET" && p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (m === "GET" && p === "/api/roles") return jsonResponse({ roles: [] });
    if (m === "GET" && p === "/api/task-templates") return jsonResponse({ ok: true, templates: { custom: { title: "自訂任務" } } });
    if (m === "GET" && p === "/api/governance") return jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } });
    if (m === "GET" && p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: state.profiles || [] });
    if (m === "GET" && p === "/api/agent-builder/catalog") return jsonResponse({ ok: true, tools: [], professions: [], skills: [], positions: [] });
    if (m === "GET" && /^\/api\/agent-profiles\/[^/]+\/loadout$/.test(p)) return jsonResponse({ ok: true, profile: {}, blockers: [], skills: { items: [] } });
    if (m === "GET" && p === "/api/folders/inspect") return jsonResponse({ ok: true, exists: true, git: {}, terminals: { known: true, count: 0, items: [] } });
    return null;
  };
}
async function openTerminal(paneId, state) {
  state.live = state.live || roleLive();
  setHandler(server(state));
  FETCH_LOG.length = 0;
  global.location.hash = `#/term/${encodeURIComponent(paneId)}`;
  await app.route();
  await settle();
  return h.dom().mainEl;
}
async function openWorkbench(hash, state) {
  setHandler(server(state));
  FETCH_LOG.length = 0;
  global.location.hash = hash;
  await app.route();
  await settle();
  return h.dom().mainEl;
}
const badgeText = (main) => text(main.find((n) => /badge/.test(n.className || "") && /^(你正在操作|只能觀看)$/.test(n.textContent)));

// ---- 3.2: the mark of a terminal this tab started -------------------------------------------------------------------
test("3.2 the mark is used once", () => {
  app.grantFreshTerminal(PANE, 1000);
  assert.strictEqual(app.hasFreshTerminalGrant(PANE, 1000), true);
  assert.strictEqual(app.takeFreshTerminalGrant(PANE, 1000), true);
  assert.strictEqual(app.takeFreshTerminalGrant(PANE, 1001), false, "gone after one use");
  assert.strictEqual(app.takeFreshTerminalGrant(OTHER, 1001), false, "a terminal that was never started here has none");
});

test("3.2 the mark is void after two minutes, and not a moment before", () => {
  assert.strictEqual(app.TERM_GRANT_MS, 120000);
  app.grantFreshTerminal(PANE, 5000);
  assert.strictEqual(app.takeFreshTerminalGrant(PANE, 5000 + 120000), false, "exactly two minutes: void");
  app.grantFreshTerminal(PANE, 5000);
  assert.strictEqual(app.takeFreshTerminalGrant(PANE, 5000 + 119999), true, "just under: still good");
  app.grantFreshTerminal(PANE, 5000);
  assert.strictEqual(app.takeFreshTerminalGrant(PANE, 4000), false, "a mark from the future (clock moved) is not trusted");
});

test("3.2 the mark is only in memory: not in the address, localStorage or sessionStorage", () => {
  const before = JSON.stringify(global.localStorage._store);
  const hashBefore = global.location.hash;
  app.grantFreshTerminal(PANE, Date.now());
  assert.strictEqual(JSON.stringify(global.localStorage._store), before, "localStorage is untouched");
  assert.strictEqual(global.location.hash, hashBefore, "the address is untouched");
  assert(!global.sessionStorage, "there is no sessionStorage in play");
  app.takeFreshTerminalGrant(PANE);
  const a = APP_SRC.indexOf("const TERM_GRANT_MS");
  const block = APP_SRC.slice(a, APP_SRC.indexOf("function hasFreshTerminalGrant", a));
  assert(block.length > 300);
  const code = block.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
  assert(!/localStorage|sessionStorage|store\.(get|set)|location\.|history\.|document\.cookie|indexedDB/.test(code), "the mark's code touches no storage and no address");
  assert(!APP_SRC.split("\n").filter((l) => !/^\s*\/\//.test(l)).some((l) => /sessionStorage/.test(l)), "the page's code never uses sessionStorage");
});

test("3.2 a freshly started terminal takes the keyboard once the stream is connected, and says so with a way back to watching", async () => {
  app.grantFreshTerminal(PANE);
  const state = { live: roleLive(), tasks: [] };
  const main = await openTerminal(PANE, state);
  assert.strictEqual(takeovers().length, 1, "one takeover, through the ordinary control route");
  assert.strictEqual(takeovers()[0].url, `/api/term/${PANE}/control`);
  assert(/^\d+$/.test(String(takeovers()[0].body.cols)) && /^\d+$/.test(String(takeovers()[0].body.rows)), "with the terminal's size, like every takeover");
  assert.strictEqual(badgeText(main), "你正在操作");
  const note = byData(main, "data-term", "fresh")[0];
  assert(note, "the line is there");
  assert(text(note).includes("這是你剛開的終端，可以直接打字；打的字會直接送給 Agent。"));
  const release = byData(main, "data-term", "fresh-release")[0];
  assert.strictEqual(text(release), "改成只觀看");
  assert.strictEqual(app.hasFreshTerminalGrant(PANE), false, "the mark is used up");
  release.click();
  await settle();
  assert.strictEqual(releases().length, 1, "the button releases the control");
  assert.strictEqual(badgeText(h.dom().mainEl), "只能觀看");
  assert.strictEqual(byData(h.dom().mainEl, "data-term", "fresh").length, 0, "the line is gone once it is only watching");
  assert(h.dom().mainEl.find(isButton("接管操作")), "and the takeover button is back");
  app.cleanupActiveTerminal();
});

test("3.2 without the mark (a reload, a shared address, another tab) a terminal is only watched", async () => {
  app.takeFreshTerminalGrant(PANE);
  const main = await openTerminal(PANE, { live: roleLive(), tasks: [] });
  assert.strictEqual(takeovers().length, 0, "no takeover request at all");
  assert.strictEqual(badgeText(main), "只能觀看");
  assert(main.find(isButton("接管操作")), "the person has to ask for it");
  assert.strictEqual(byData(main, "data-term", "fresh").length, 0);
  app.cleanupActiveTerminal();
});

test("3.2 a mark for another terminal, or an expired one, gives nothing", async () => {
  app.grantFreshTerminal(OTHER);
  await openTerminal(PANE, { live: roleLive(), tasks: [] });
  assert.strictEqual(takeovers().length, 0, "a mark is for one terminal");
  assert.strictEqual(app.hasFreshTerminalGrant(OTHER), true, "and it is not used up by looking at another");
  app.takeFreshTerminalGrant(OTHER);
  app.cleanupActiveTerminal();
  app.grantFreshTerminal(PANE, Date.now() - 121000);
  const main = await openTerminal(PANE, { live: roleLive(), tasks: [] });
  assert.strictEqual(takeovers().length, 0, "two minutes old: void");
  assert.strictEqual(badgeText(main), "只能觀看");
  app.cleanupActiveTerminal();
});

test("3.2 no connected stream, no keyboard: the mark waits (and is not spent) while the stream is down", async () => {
  app.grantFreshTerminal(PANE);
  const main = await openTerminal(PANE, { live: roleLive(), tasks: [], stream: () => jsonResponse({ error: "no" }, false, 500) });
  assert.strictEqual(takeovers().length, 0, "the stream never connected: nothing was asked for");
  assert.notStrictEqual(badgeText(main), "你正在操作");
  assert.strictEqual(app.hasFreshTerminalGrant(PANE), true, "the mark is still there for a connection within the two minutes");
  app.cleanupActiveTerminal();
  app.takeFreshTerminalGrant(PANE);
});

test("3.2 the mark is for the first connection only: opening the same terminal again is only watching", async () => {
  app.grantFreshTerminal(PANE);
  await openTerminal(PANE, { live: roleLive(), tasks: [] });
  assert.strictEqual(takeovers().length, 1);
  app.cleanupActiveTerminal();
  const main = await openTerminal(PANE, { live: roleLive(), tasks: [] });
  assert.strictEqual(takeovers().length, 0, "the second visit asks for nothing");
  assert.strictEqual(badgeText(main), "只能觀看");
  app.cleanupActiveTerminal();
});

test("3.2 the workbench's terminal takes the keyboard the same way, and shows the same line", async () => {
  app.grantFreshTerminal(PANE);
  const main = await openWorkbench(`#/workbench/${PANE}?task=task-1`, { live: roleLive(), tasks: [mkTask({ associated_pane_id: PANE })] });
  assert.strictEqual(takeovers().length, 1);
  assert.strictEqual(badgeText(main), "你正在操作");
  assert(text(byData(main, "data-term", "fresh")[0]).includes("這是你剛開的終端，可以直接打字"));
  assert.strictEqual(text(byData(main, "data-term", "fresh-release")[0]), "改成只觀看");
  app.cleanupActiveTerminal();
  const main2 = await openWorkbench(`#/workbench/${PANE}?task=task-1`, { live: roleLive(), tasks: [mkTask({ associated_pane_id: PANE })] });
  assert.strictEqual(takeovers().length, 0, "a second visit is only watching");
  assert.strictEqual(badgeText(main2), "只能觀看");
  app.cleanupActiveTerminal();
});

test("3.2 one shared request for taking input: the pages, the dialogs and the built-in terminal all go through it", () => {
  assert.strictEqual((APP_SRC.match(/action: "takeover"/g) || []).length, 1, "only requestTerminalControl asks");
  assert.strictEqual((APP_SRC.match(/requestTerminalControl\(\{/g) || []).length, 5, "standalone dialog + auto, workbench dialog + auto, and the function itself is not counted twice");
  assert(!/async function autoTakeover\(\)/.test(APP_SRC), "the copy of the built-in terminal's takeover is gone");
});

// ---- 3.3: the takeover reminder -------------------------------------------------------------------------------------
async function openReminder(state, live = roleLive("working")) {
  const main = await openTerminal(PANE, { live, ...state });
  FETCH_LOG.length = 0;
  main.find(isButton("接管操作")).click();
  await settle();
  return dialog();
}
const factText = (d, key) => text(byData(d, "data-fact", key)[0]);
const allFacts = (d) => byData(d, "data-fact", "task").concat(byData(d, "data-fact", "next"), byData(d, "data-fact", "state"), byData(d, "data-fact", "interrupt"), byData(d, "data-fact", "waiting")).map(text);

test("3.3 the dialog is 接手提醒; the focus starts on 取消; Enter alone takes nothing; 確認接手 is what takes", async () => {
  const d = await openReminder({ tasks: [], flows: [] });
  assert(d, "opened");
  assert.strictEqual(text(d.find((n) => n.tag === "h2")), "接手提醒");
  assert(!text(d).includes("確認接管終端操作"), "the old title is gone");
  const cancel = d.find(isButton("取消")); const confirm = d.find(isButton("確認接手"));
  assert(cancel && confirm);
  assert.strictEqual(global.document.activeElement, cancel, "the focus is on 取消");
  d.dispatch("keydown", { key: "Enter" });
  await settle();
  assert.strictEqual(takeovers().length, 0, "an Enter in the dialog takes nothing");
  cancel.click();
  await settle();
  assert.strictEqual(takeovers().length, 0, "取消 takes nothing");
  assert.strictEqual(dialog(), null, "and closes");
  assert.strictEqual(badgeText(h.dom().mainEl), "只能觀看");
  app.cleanupActiveTerminal();
});

test("3.3 確認接手 asks once, through the control route, and then the page is in control without the generic 'fresh' line", async () => {
  const d = await openReminder({ tasks: [], flows: [] });
  const confirm = d.find(isButton("確認接手"));
  assert.strictEqual(confirm.disabled, false, "enabled once the facts are in");
  confirm.click();
  await settle();
  assert.strictEqual(takeovers().length, 1);
  assert.strictEqual(takeovers()[0].url, `/api/term/${PANE}/control`);
  assert.strictEqual(dialog(), null);
  const main = h.dom().mainEl;
  assert.strictEqual(badgeText(main), "你正在操作");
  assert.strictEqual(byData(main, "data-term", "fresh").length, 0, "taking over by the dialog is not the 'you just opened it' line");
  assert(main.find(isButton("改成只觀看")), "the way back to watching is the toolbar button");
  app.cleanupActiveTerminal();
});

test("3.3 the fixed lines are always there, in the design's words", async () => {
  const d = await openReminder({ tasks: [], flows: [] });
  const fixed = byData(d, "data-takeover", "fixed")[0];
  assert(fixed);
  assert.deepStrictEqual(fixed.findAll((n) => n.tag === "li").map(text), [
    "接手後，你在這裡打的字會直接送給 Agent。",
    "同一時間只有一個分頁能控制；你接手後，其他分頁會改成只觀看。",
    "接手後隨時可以按「改成只觀看」放開。"]);
  closeDialogs(); app.cleanupActiveTerminal();
});

test("3.3 a terminal with no task card says so; one that is tracked names the card and its next step", async () => {
  let d = await openReminder({ tasks: [mkTask({ id: "t-x", associated_pane_id: OTHER })], flows: [] });
  assert.strictEqual(factText(d, "task"), "這個終端沒有關聯任務卡。");
  assert.strictEqual(byData(d, "data-fact", "next").length, 0, "no card, no next step");
  closeDialogs(); app.cleanupActiveTerminal();
  const tasks = [mkTask({ associated_pane_id: PANE })];
  d = await openReminder({ tasks, flows: [flowView("planning", "計畫中")] });
  assert.strictEqual(factText(d, "task"), "這個終端關聯的任務卡：「整理首頁文案」。");
  assert.strictEqual(factText(d, "next"), "下一步：規劃者提出計畫（輪到 CEO）");
  closeDialogs(); app.cleanupActiveTerminal();
});

test("3.3 what is not known is said to be not known: unreadable task list, unreadable flows, a card with no team", async () => {
  let d = await openReminder({ tasksError: true, flows: [] });
  assert.strictEqual(factText(d, "task"), "讀不到任務卡清單，不知道這個終端有沒有關聯任務卡。");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [mkTask({ associated_pane_id: PANE })], flowsError: true });
  assert.strictEqual(factText(d, "next"), "讀不到流程，不知道這張卡的下一步。");
  assert.strictEqual(byData(d, "data-fact", "waiting").length, 0, "nothing is claimed to be waiting");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [mkTask({ associated_pane_id: PANE })], flows: [] });
  assert.strictEqual(factText(d, "next"), "這張任務卡還沒有隊伍，沒有下一步可以說。");
  closeDialogs(); app.cleanupActiveTerminal();
});

test("3.3 the Agent's state comes from the live data: working adds the warning; waiting, exited and unknown do not", async () => {
  let d = await openReminder({ tasks: [], flows: [] }, roleLive("working"));
  assert.strictEqual(factText(d, "state"), "Agent 現在正在工作。");
  assert.strictEqual(factText(d, "interrupt"), "現在打字可能打斷它。");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [], flows: [] }, roleLive("waiting"));
  assert.strictEqual(factText(d, "state"), "Agent 現在停下來等你。");
  assert.strictEqual(byData(d, "data-fact", "interrupt").length, 0);
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [], flows: [] }, roleLive("needs-input"));
  assert.strictEqual(factText(d, "state"), "Agent 現在停下來等你。");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [], flows: [] }, roleLive("working", { exited: true }));
  assert.strictEqual(factText(d, "state"), "這個終端已經結束。");
  assert.strictEqual(byData(d, "data-fact", "interrupt").length, 0, "an ended terminal is not 'working'");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [], flows: [] }, roleLive("unknown"));
  assert.strictEqual(factText(d, "state"), "Agent 現在的狀態不明。");
  assert.strictEqual(byData(d, "data-fact", "interrupt").length, 0, "not known is not 'working'");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks: [], flows: [] }, liveWith({ panes: [{ pane_id: PANE, kind: "agent" }] }));
  assert.strictEqual(factText(d, "state"), "Agent 現在的狀態不明。", "no session record at all: not known");
  closeDialogs(); app.cleanupActiveTerminal();
});

test("3.3 a flow waiting for you is said; one waiting for somebody else is not", async () => {
  const tasks = [mkTask({ associated_pane_id: PANE })];
  let d = await openReminder({ tasks, flows: [flowView("awaiting_approval", "等核准")] }, roleLive("waiting"));
  assert.strictEqual(factText(d, "waiting"), "這張卡的流程正在等你處理：你核准計畫。");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks, flows: [flowView("awaiting_push", "等你上傳")] }, roleLive("waiting"));
  assert.strictEqual(factText(d, "waiting"), "這張卡的流程正在等你處理：你自己上傳到遠端。");
  closeDialogs(); app.cleanupActiveTerminal();
  d = await openReminder({ tasks, flows: [flowView("implementing", "實作中")] }, roleLive("working"));
  assert.strictEqual(byData(d, "data-fact", "waiting").length, 0, "the executor's turn is not yours");
  closeDialogs(); app.cleanupActiveTerminal();
});

test("3.3 every line comes from data: a built-in terminal is described as one, and every dialog line is one of the known keys", async () => {
  const live = liveWith({ panes: [{ pane_id: PANE, kind: "shell", cwd: WORKDIR }] });
  const main = await openTerminal(PANE, { live, tasks: [] });
  app.cleanupActiveTerminal();
  const lines = app.takeoverReminderLines({ paneId: PANE, session: null, pane: { kind: "shell" }, tasks: [], flows: [] });
  assert.strictEqual(lines.find((l) => l.key === "state").text, "這是一般終端機，不是 Agent。");
  assert(main, "the page rendered");
  for (const l of app.takeoverReminderLines({ paneId: PANE, session: { status: "working" }, pane: {}, tasks: [mkTask({ associated_pane_id: PANE })], flows: [flowView("awaiting_approval", "x")] })) {
    assert(["task", "next", "state", "interrupt", "waiting"].includes(l.key), l.key);
  }
});

test("3.3 the workbench's dialog is the same dialog: same words, same focus, same request", async () => {
  const main = await openWorkbench(`#/workbench/${PANE}?task=task-1`, { live: roleLive("working"), tasks: [mkTask({ associated_pane_id: PANE })], flows: [flowView("planning", "計畫中")] });
  FETCH_LOG.length = 0;
  main.find(isButton("接管操作")).click();
  await settle();
  const d = dialog();
  assert.strictEqual(d.getAttribute("aria-labelledby"), "wb-modal-takeover-title");
  assert.strictEqual(text(d.find((n) => n.tag === "h2")), "接手提醒");
  assert.strictEqual(global.document.activeElement, d.find(isButton("取消")));
  assert.strictEqual(factText(d, "task"), "這個終端關聯的任務卡：「整理首頁文案」。");
  assert.strictEqual(factText(d, "interrupt"), "現在打字可能打斷它。");
  d.find(isButton("確認接手")).click();
  await settle();
  assert.strictEqual(takeovers().length, 1);
  assert.strictEqual(badgeText(h.dom().mainEl), "你正在操作");
  app.cleanupActiveTerminal();
});

// ---- 3.1: after the launch --------------------------------------------------------------------------------------------
const PROFILE = { id: "p-ceo", name: "CEO", profession_role_id: null, model: { tool: "claude", model_id: "" }, equipped_skill_ids: [],
  permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" }, enabled: true, created_at: 1, updated_at: 1, _unresolved: { profession: false, skills: [] } };
const LV = { enforced: "強制（限已測路徑、版本與執行層）", intent: "僅意圖", notGranted: "不授予", unrestricted: "未限制" };
const label = (level) => ({ level, note: "n", source_version: { value: "2.1.286" }, settings_digest: "d".repeat(64), path_scope: "不適用", evidence_refs: [], bypass: "", unknown_reason: "none" });
const previewBody = (workdir = WORKDIR) => ({ ok: true, preview: { preview_id: "p-" + "a".repeat(32), launchable: true, reasons: [],
  cli: { binary: "/x/claude", version: "2.1.286", verified: true }, settings_digest: "d".repeat(64),
  canonical_paths: { workdir, scratch: "/private/tmp/sc" },
  derived_labels: { Read: label(LV.intent), Write: label(LV.enforced), Test: label(LV.intent), Commit: label(LV.unrestricted), Deploy: label(LV.notGranted), Network: label(LV.enforced), Filesystem: label(LV.enforced) },
  expires_at: 2000000000 } });
async function launchFromTask(state, { typed } = {}) {
  const over = { "POST /api/native/agent-previews": () => jsonResponse(previewBody(typed || WORKDIR)),
    "POST /api/native/agent-launches": () => jsonResponse({ ok: true, launch: { session: { session_id: PANE } } }),
    ...(state.over || {}) };
  const st = { profiles: [PROFILE], tasks: [mkTask(state.task || {})], live: liveWith(), ...state, over };
  await openWorkbench("#/workbench?task=task-1&profile=p-ceo&launch=1&step=plan", st);
  const d = dialog();
  assert(d, "the launch pass opened");
  if (typed) { const f = d.find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir"); f.value = typed; }
  const box = d.find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-commit");
  box.checked = true; box.dispatch("change");
  await settle();
  FETCH_LOG.length = 0;
  d.find(isButton("確認啟動")).click();
  await settle();
  return d;
}

test("3.1 a launch from a task card opens the workbench (terminal on the left, the same card on the right) and records the terminal on the card", async () => {
  app.takeFreshTerminalGrant(PANE);
  await launchFromTask({});
  assert.strictEqual(global.location.hash, `#/workbench/${PANE}?task=task-1`, "not the standalone #/term/ page");
  const link = posts().filter((c) => c.url === "/api/tasks/task-1");
  assert.strictEqual(link.length, 1, "one update of the card");
  assert.deepStrictEqual(link[0].body, { associated_pane_id: PANE }, "the ordinary association update, and nothing else in it");
  assert.strictEqual(posts().filter((c) => /\/(input|control)$/.test(c.url)).length, 0, "nothing is sent into the terminal by the launch");
  assert.strictEqual(app.hasFreshTerminalGrant(PANE), true, "and the new terminal is marked as started here");
  assert(text(h.dom().toastEl).includes("記到任務卡「整理首頁文案」上"), text(h.dom().toastEl));
  app.takeFreshTerminalGrant(PANE);
});

test("3.1 the card keeps what the server stored: a different answer is reported, not hidden", async () => {
  app.takeFreshTerminalGrant(PANE);
  await launchFromTask({ over: { "POST /api/tasks/task-1": () => jsonResponse({ ok: true, task: mkTask({ associated_pane_id: null }) }) } });
  assert.strictEqual(global.location.hash, `#/workbench/${PANE}?task=task-1`, "the terminal is still opened and usable");
  assert(text(h.dom().toastEl).startsWith("終端已開啟，但沒能記到任務卡上"), text(h.dom().toastEl));
  app.takeFreshTerminalGrant(PANE);
});

test("3.1 if recording fails the person is told, and the terminal is still opened with the keyboard mark", async () => {
  app.takeFreshTerminalGrant(PANE);
  await launchFromTask({ over: { "POST /api/tasks/task-1": () => jsonResponse({ error: "磁碟寫入失敗" }, false, 500) } });
  assert.strictEqual(global.location.hash, `#/workbench/${PANE}?task=task-1`);
  const t = text(h.dom().toastEl);
  assert(t.startsWith("終端已開啟，但沒能記到任務卡上：") && t.includes("磁碟寫入失敗") && t.includes("終端可以照常使用"), t);
  assert.strictEqual(app.hasFreshTerminalGrant(PANE), true);
  app.takeFreshTerminalGrant(PANE);
});

test("3.1 a card that was tracking another running terminal now tracks the new one, and says the old one is still running", async () => {
  app.takeFreshTerminalGrant(PANE);
  const live = liveWith({ panes: [{ pane_id: OTHER, kind: "agent", exited: false }], sessions: [{ terminal_id: OTHER, pane_id: OTHER, agent: "claude", status: "working" }] });
  await launchFromTask({ live, task: { associated_pane_id: OTHER },
    over: { "POST /api/tasks/task-1": (_u, o) => jsonResponse({ ok: true, task: mkTask({ associated_pane_id: JSON.parse(o.body).associated_pane_id }) }) } });
  assert.deepStrictEqual(posts().filter((c) => c.url === "/api/tasks/task-1")[0].body, { associated_pane_id: PANE });
  assert(text(h.dom().toastEl).includes("這張卡原本關聯的終端還在執行"), text(h.dom().toastEl));
  app.takeFreshTerminalGrant(PANE);
});

test("3.1 a launch on a folder other than the card's is not recorded on the card, and says why", async () => {
  app.takeFreshTerminalGrant(PANE);
  await launchFromTask({}, { typed: "/tmp/somewhere-else" });
  assert.strictEqual(posts().filter((c) => c.url === "/api/tasks/task-1").length, 0, "no association is written");
  assert(text(h.dom().toastEl).includes("沒有記到任務卡上"), text(h.dom().toastEl));
  assert.strictEqual(global.location.hash, `#/workbench/${PANE}?task=task-1`);
  app.takeFreshTerminalGrant(PANE);
});

test("3.1 a launch that is not from a task card (the card pool) opens the terminal's own page and records nothing", async () => {
  app.takeFreshTerminalGrant(PANE);
  const over = { "POST /api/native/agent-previews": () => jsonResponse(previewBody()),
    "POST /api/native/agent-launches": () => jsonResponse({ ok: true, launch: { session: { session_id: PANE } } }) };
  await openWorkbench("#/workbench?profile=p-ceo&launch=1", { profiles: [PROFILE], tasks: [mkTask()], over });
  const d = dialog();
  d.find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir").value = WORKDIR;
  const box = d.find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-commit");
  box.checked = true; box.dispatch("change");
  await settle();
  FETCH_LOG.length = 0;
  d.find(isButton("確認啟動")).click();
  await settle();
  assert.strictEqual(global.location.hash, `#/term/${PANE}`);
  assert.strictEqual(posts().filter((c) => /^\/api\/tasks\//.test(c.url)).length, 0);
  assert.strictEqual(app.hasFreshTerminalGrant(PANE), true, "it was started here too");
  app.takeFreshTerminalGrant(PANE);
});

test("3.1 a launch that failed leaves no mark and records nothing", async () => {
  app.takeFreshTerminalGrant(PANE);
  await launchFromTask({ over: { "POST /api/native/agent-launches": () => jsonResponse({ error: "no" }, false, 500) } });
  assert.strictEqual(app.hasFreshTerminalGrant(PANE), false);
  assert.strictEqual(posts().filter((c) => c.url === "/api/tasks/task-1").length, 0);
});

test("3.1 folder match: the card's folder as typed, or as the server resolved it; a trailing slash does not matter", () => {
  assert.strictEqual(app.launchFolderMatchesTask("/a/b", "/a/b", "/private/a/b"), true);
  assert.strictEqual(app.launchFolderMatchesTask("/a/b", "/a/b/", null), true);
  assert.strictEqual(app.launchFolderMatchesTask("/a/b", " /x ", "/a/b"), true);
  assert.strictEqual(app.launchFolderMatchesTask("/a/b", "/a/c", "/a/c"), false);
  assert.strictEqual(app.launchFolderMatchesTask("", "", ""), false, "a card with no folder matches nothing");
});

// ---- 3.4: the hand-over reminder ----------------------------------------------------------------------------------------
const PREV = mkTask({ id: "task-0", title: "第一棒：整理首頁", status: "handed_off", provenance: { agent: "completed", tests: "untested", human: "pending" },
  closure: { reason: "handed_off_to", target: "工匠", note: "首頁文案改到第三段。\n還沒測手機版。", set_at: 1760000000 } });
const NEXT = mkTask({ id: "task-1", title: "交接：第一棒：整理首頁", handed_off_from: "task-0", chain_of_record: ["task-0"], owner: "工匠" });

test("3.4 a handed-over card shows where it came from, the note word for word, and the state the last card was left in", () => {
  const box = app.handoffReminder(NEXT, [PREV, NEXT], { onOpen: () => {} });
  assert(box, "there is a reminder");
  assert.strictEqual(text(byData(box, "data-handoff", "from")[0]).startsWith("這張卡是從「第一棒：整理首頁」交接過來的。"), true);
  assert.strictEqual(text(byData(box, "data-handoff", "to")[0]), "交給：工匠");
  const note = byData(box, "data-handoff", "note")[0].find((n) => n.tag === "blockquote");
  assert.strictEqual(note.textContent, "首頁文案改到第三段。\n還沒測手機版。", "the note as written");
  const state = text(byData(box, "data-handoff", "state")[0]);
  assert(state.includes("已交接") && state.includes("交給下一位"), state);
  assert(text(box).includes("接手提醒") && text(box).includes("VBear 不知道上一位實際做完了什麼"));
  assert.strictEqual(byData(box, "data-handoff", "open").length, 1, "the previous card can be opened");
});

test("3.4 only stored data: no note says 'no note', a card that is gone says it cannot be read; nothing about what was done is made up", () => {
  const noNote = { ...PREV, closure: { ...PREV.closure, note: "" } };
  const box = app.handoffReminder(NEXT, [noNote, NEXT], { onOpen: () => {} });
  assert.strictEqual(text(byData(box, "data-handoff", "note-empty")[0]), "上一位沒有寫交接說明。");
  const gone = app.handoffReminder(NEXT, [NEXT], { onOpen: () => {} });
  assert(text(byData(gone, "data-handoff", "from")[0]).includes("已經不在清單裡（編號 task-0）"));
  assert.strictEqual(text(byData(gone, "data-handoff", "note-missing")[0]), "交接說明存在前一張卡上，現在讀不到。");
  assert.strictEqual(byData(gone, "data-handoff", "open").length, 0, "no button to a card that is not there");
  assert.strictEqual(byData(gone, "data-handoff", "state").length, 0, "no state of a card that cannot be read");
  assert(!/做完了(?!什麼)|已完成|完成度/.test(text(box)), "no claim about what was finished");
});

test("3.4 a card with no hand-over source has no reminder", () => {
  assert.strictEqual(app.handoffReminder(mkTask(), [PREV], {}), null);
  assert.strictEqual(app.handoffReminder(mkTask({ handed_off_from: "" }), [PREV], {}), null);
  assert.strictEqual(app.handoffReminder(null, [], {}), null);
});

test("3.4 in the workbench the reminder is at the top of the card, before its title; a card without one has none; 打開前一張卡 moves to it", async () => {
  const main = await openWorkbench("#/workbench?task=task-1", { tasks: [NEXT, PREV], live: liveWith() });
  const box = byData(main, "data-handoff", "box")[0];
  assert(box, "shown");
  const content = box.parentNode;
  const kids = content.children.filter((c) => c && c.tag);
  const idxBox = kids.indexOf(box);
  const idxHead = kids.findIndex((c) => c.hasClass && c.hasClass("wb-task-head"));
  assert(idxBox >= 0 && idxHead > idxBox, `reminder ${idxBox} comes before the head ${idxHead}`);
  assert(idxBox <= 1, "directly under the task chooser");
  byData(box, "data-handoff", "open")[0].click();
  await settle();
  assert.strictEqual(byData(h.dom().mainEl, "data-handoff", "box").length, 0, "the earlier card has none");
  assert(text(h.dom().mainEl).includes("第一棒：整理首頁"));
  const main2 = await openWorkbench("#/workbench?task=task-0", { tasks: [PREV, NEXT], live: liveWith() });
  assert.strictEqual(byData(main2, "data-handoff", "box").length, 0, "the first card was not handed over from anything");
});

test("3.4 the lobby's card shows a compact reminder too, with the note folded", () => {
  const card = app.handoffReminder(NEXT, [PREV, NEXT], { compact: true, hrefOf: (id) => `#/workbench?task=${id}` });
  assert(card && byData(card, "data-handoff", "open")[0].getAttribute("href") === "#/workbench?task=task-0");
  const fold = card.find((n) => n.tag === "details");
  assert(fold && !fold.hasAttribute("open"), "folded");
  assert(text(fold).includes("首頁文案改到第三段。"), "the note is kept whole inside");
});

// ---- 3.5: the workbench ------------------------------------------------------------------------------------------------
test("3.5 with no terminal open the card is the page: no empty terminal area, a one-line note, no list of terminals", async () => {
  const main = await openWorkbench("#/workbench?task=task-1", { tasks: [mkTask()], live: liveWith() });
  const shell = main.find((n) => n.hasClass && n.hasClass("wb-shell"));
  assert(shell.hasClass("no-term"));
  assert.strictEqual(main.findAll((n) => n.hasClass && n.hasClass("term-container")).length, 0, "no terminal container at all");
  const strip = byData(main, "data-wb", "no-terminal")[0];
  assert.strictEqual(text(strip), "還沒有開啟終端；從下一步讓角色出發");
  assert(!text(main.find((n) => n.hasClass && n.hasClass("wb-left"))).includes("開啟中的終端") || shell.hasClass("no-term"), "the left column is hidden by the layout");
  assert(/\.wb-shell\.no-term > \.wb-left\s*\{[^}]*display:\s*none/.test(CSS_SRC), "css hides the terminal list in this state");
  assert(/\.wb-shell\.no-term\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/.test(CSS_SRC), "css gives the card the whole page");
  assert(main.find((n) => n.getAttribute && n.getAttribute("data-wb") === "advanced"), "and the card is there");
});

test("3.5 with a terminal open the layout is the three columns it was, and a remembered fold still applies", async () => {
  global.localStorage._store["sid:wb:right_collapsed"] = "true";
  const main = await openWorkbench(`#/workbench/${PANE}`, { tasks: [mkTask({ associated_pane_id: PANE })], live: roleLive() });
  const shell = main.find((n) => n.hasClass && n.hasClass("wb-shell"));
  assert(!shell.hasClass("no-term"));
  assert(shell.hasClass("right-collapsed"), "the fold the person chose is kept when there is a terminal");
  delete global.localStorage._store["sid:wb:right_collapsed"];
  app.cleanupActiveTerminal();
});

test("3.5 the four-column status basis and the [P]/[G] pages are behind 進階（工程資訊）, which starts shut; nothing is deleted", async () => {
  const main = await openWorkbench("#/workbench?task=task-1", { tasks: [mkTask()], live: liveWith() });
  const adv = byData(main, "data-wb", "advanced")[0];
  assert(adv && adv.tag === "details" && !adv.hasAttribute("open"));
  assert.strictEqual(text(adv.children[0]), "進階（工程資訊）");
  assert(text(adv).includes("狀態依據（誰說了算）") && text(adv).includes("自我回報狀態"), "the four fields are inside");
  const outside = main.findAll((n) => n.hasClass && n.hasClass("wb-provenance-box")).filter((n) => { for (let p = n.parentNode; p; p = p.parentNode) if (p === adv) return false; return true; });
  assert.strictEqual(outside.length, 0, "and nowhere outside it");
  const tabs = main.findAll((n) => n.getAttribute && n.getAttribute("role") === "tab").map(text);
  assert.deepStrictEqual(tabs, ["[T] 任務卡", "角色"], "no [P]/[G] tab until opened");
  byData(adv, "data-wb", "open-project")[0].click();
  await settle();
  assert(h.dom().mainEl.findAll((n) => n.getAttribute && n.getAttribute("role") === "tab").map(text).includes("[P] 專案契約"), "the contract page is one click away");
});

test("3.5 the top of the card says where the flow is; the mark becomes small text; other marks keep their place; no flow, no gate", () => {
  const gate = app.taskGate(flowView("planning", "計畫中"));
  assert.strictEqual(gate.text, "① 計畫中");
  const nodes = app.taskStatusNodes("draft", flowView("planning", "計畫中"));
  assert.strictEqual(text(nodes[0]), "① 計畫中");
  assert.strictEqual(text(nodes[1]), "標記：草稿", "the original mark is kept, as small text");
  assert(/small/.test(nodes[1].className) && !/badge/.test(nodes[1].className));
  assert.strictEqual(app.taskStatusNodes("in_progress", flowView("in_review", "審查中")).map(text).join("|"), "④ 審查中|標記：執行中");
  for (const status of ["closed", "handed_off", "blocked", "verification_asserted", "agent_completed"]) {
    const only = app.taskStatusNodes(status, flowView("planning", "計畫中"));
    assert.strictEqual(only.length, 1, status);
    assert(/badge/.test(only[0].className), `${status} stays the pill`);
  }
  assert.strictEqual(text(app.taskStatusNodes("draft", null)[0]), "草稿", "no flow: nothing is invented");
  assert.strictEqual(app.taskStatusNodes("draft", { phase: {} }).length, 1);
  assert.strictEqual(app.taskGate(flowView("awaiting_push", "等你上傳")).text, "等你上傳", "a step that is not in the list has no number");
  assert.strictEqual(app.taskGate(null), null);
});

test("3.5 in the workbench the gate appears once the flow is read, and the lobby's card uses it too", async () => {
  const main = await openWorkbench("#/workbench?task=task-1", { tasks: [mkTask()], flows: [flowView("planning", "計畫中")], live: liveWith() });
  const slot = byData(main, "data-task", "status")[0];
  assert(text(slot).includes("① 計畫中") && text(slot).includes("標記：草稿"), text(slot));
  const card = app.taskFrontCard(mkTask(), { flows: [flowView("planning", "計畫中")], profiles: [] });
  assert(text(byData(card, "data-task", "status")[0]).includes("① 計畫中"));
  const noTeam = app.taskFrontCard(mkTask(), { flows: [], profiles: [] });
  assert.strictEqual(text(byData(noTeam, "data-task", "status")[0]), "草稿");
});

// ---- the rules that hold everywhere ----------------------------------------------------------------------------------
test("rules: the new code has no innerHTML, no emoji, no outside resource; the shield rules are untouched", () => {
  const a = APP_SRC.indexOf("// ---- who is at the keyboard (P11)");
  const block = APP_SRC.slice(a, APP_SRC.indexOf("function handleTerminalFrame", a));
  assert(block.length > 4000);
  assert(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(block));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(block), "no emoji");
  assert(!/https?:\/\//.test(block));
  for (const level of ["部分強制", "未驗證（此 Claude Code 版本尚未實測）", "未知", "不授予"]) assert.strictEqual(app.armorShield(level), null, `${level} has no shield`);
});

// ---- run ----------------------------------------------------------------------------------------------------------
(async () => {
  const timer = setTimeout(() => { console.error("TIMEOUT"); process.exit(2); }, 240000);
  let failed = 0;
  const only = process.env.P11_ONLY;
  for (const [name, fn] of tests) {
    if (only && !name.includes(only)) continue;
    try { await fn(); console.log("ok   - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name); console.log(e && e.stack || e); }
  }
  clearTimeout(timer);
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
