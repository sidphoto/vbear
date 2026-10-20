// P10 (v0.8.0 small fixes): the next step you can act on, the words of the terminal's back button, the launch pass that
// previews itself, plain words for the engineering ones, same-name task cards, the skill categories in Chinese, and the
// colours that were below the contrast line. The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/p10.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, SyntheticNode, FETCH_LOG, jsonResponse, setHandler } = h;

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
// the side panel's scan status is not part of these pages (the lobby test does the same)
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
const OVERVIEW = { ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- fixtures ---------------------------------------------------------------------------------------------------
const FLOW_ID = "flow-000000000001";
function flowView(phase, over = {}) {
  return {
    id: FLOW_ID, task_id: "task-1", task_title: "整理首頁文案",
    phase: { key: phase, label: phase, reason: `${phase} 的說明` },
    automation: { mode: "manual" },
    roles: { planner: { name: "CEO", family: "anthropic", profile_id: "p-ceo" },
      executor: { name: "工匠", family: "anthropic", profile_id: "p-maker" },
      reviewers: [{ name: "審查員", family: "openai", profile_id: "p-rev" }] },
    ...over,
  };
}
const task = { id: "task-1", title: "整理首頁文案", workdir: "/tmp/p10-work" };

// ---- F2: the next step box --------------------------------------------------------------------------------------
test("F2 awaiting approval: the box has the approve buttons, and the lobby's compact card does not", () => {
  const node = app.nextStepActionNode(flowView("awaiting_approval"), { task });
  assert(node, "the box has an action area");
  const plan = byData(node, "data-ns", "approve-plan")[0];
  const auto = byData(node, "data-ns", "approve-auto")[0];
  assert.strictEqual(text(plan), "核准計畫");
  assert.strictEqual(text(auto), "核准計畫並開啟自動執行…");
  assert(/primary/.test(plan.className), "the main button");
  assert.strictEqual(app.nextStepActionNode(flowView("awaiting_approval"), { task, compact: true }), null);
  assert.strictEqual(byData(app.nextStepActionNode(flowView("planning"), { task }), "data-ns", "approve-plan").length, 0, "only on the step that is yours");
  assert.strictEqual(byData(app.nextStepActionNode(flowView("implementing"), { task }), "data-ns", "approve-plan").length, 0);
});

test("F2 approve-plan keeps its confirmation: nothing is written until the dialog is confirmed, and it says what it writes", async () => {
  closeDialogs(); FETCH_LOG.length = 0;
  setHandler(() => null);
  const node = app.nextStepActionNode(flowView("awaiting_approval"), { task });
  byData(node, "data-ns", "approve-plan")[0].click();
  await settle();
  const d = dialog();
  assert(d, "a confirmation dialog opened");
  assert(text(d).includes("手動記錄") && text(d).includes("未驗證") && text(d).includes("不會派工"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "nothing written before confirming");
  d.find(isButton("取消")).click();
  await settle();
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "cancel writes nothing");
  closeDialogs();
  byData(node, "data-ns", "approve-plan")[0].click();
  await settle();
  dialog().find(isButton("核准計畫")).click();
  await settle();
  const posts = FETCH_LOG.filter((c) => c.method === "POST");
  assert.strictEqual(posts.length, 1);
  assert.strictEqual(posts[0].url, `/api/flows/${FLOW_ID}/events`, "the same route the manual form uses");
  assert.deepStrictEqual(posts[0].body, { kind: "plan_approved", note: "" }, "the same body the manual form sends");
  closeDialogs();
});

test("F2 approve-and-automatic opens the same dialog as the 自動執行 panel (its own preview first), and is absent once automatic", async () => {
  closeDialogs(); FETCH_LOG.length = 0;
  setHandler(() => null);
  const node = app.nextStepActionNode(flowView("awaiting_approval"), { task });
  byData(node, "data-ns", "approve-auto")[0].click();
  await settle();
  const d = dialog();
  assert(d && text(d).includes("核准計畫並開啟自動執行"), "the auto dialog");
  assert(FETCH_LOG.some((c) => c.method === "POST" && c.url === `/api/flows/${FLOW_ID}/automation-preview`), "its own preview route");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST" && !c.url.endsWith("automation-preview")).length, 0, "nothing else was sent");
  const confirm = d.find(isButton("核准並開啟自動執行"));
  assert(confirm, "its confirm button is still in the dialog");
  closeDialogs();
  const inAuto = app.nextStepActionNode(flowView("awaiting_approval", { automation: { mode: "auto" } }), { task });
  assert.strictEqual(byData(inAuto, "data-ns", "approve-auto").length, 0, "already automatic: no second switch");
});

test("F2 your merge and your push are sentences, not buttons", () => {
  const merge = app.nextStepActionNode(flowView("awaiting_merge"), { task });
  assert.strictEqual(merge.findAll((n) => n.tag === "button" || n.tag === "a").length, 0, "no fake button");
  assert(text(merge).includes("到你的專案資料夾") && text(merge).includes("合併") && text(merge).includes("不會替你合併"));
  assert(!text(merge).includes("合併與上傳關卡"), "off the flow page there is no such panel to point to");
  const onPage = app.nextStepActionNode(flowView("awaiting_merge"), { task, onFlowPage: true });
  assert(text(onPage).includes("下方「合併與上傳關卡」"));
  const push = app.nextStepActionNode(flowView("awaiting_push"), { task });
  assert.strictEqual(push.findAll((n) => n.tag === "button" || n.tag === "a").length, 0);
  assert(text(push).includes("到你的專案資料夾") && text(push).includes("不會替你上傳"));
  assert.strictEqual(app.nextStepActionNode(flowView("done"), { task }), null, "nothing to do once done");
  assert.strictEqual(app.nextStepActionNode({ id: FLOW_ID, phase: { key: "no-such-phase" } }, { task }), null, "an unknown phase invents nothing");
});

test("F2 the box is on the flow page's and the workbench's task card (both go through nextStepsList)", () => {
  const list = app.nextStepsList(flowView("awaiting_approval"), { task, onFlowPage: true });
  assert.strictEqual(byData(list, "data-ns", "approve-plan").length, 1);
  const box = app.teamSection(task, { flow: flowView("awaiting_approval"), profiles: [], hideOpen: true });
  return settle().then(() => assert.strictEqual(byData(box, "data-ns", "approve-plan").length, 1, "the team section carries it"));
});

// ---- F3: the terminal page's way back ---------------------------------------------------------------------------
const PANE = "n-0123456789ab";
function liveWith(over = {}) {
  return { runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] }, ...over };
}
async function openTerminal(paneId, { live, tasks }) {
  setHandler((url) => {
    const p = String(url).split("?")[0];
    if (p === "/api/overview") return jsonResponse(OVERVIEW);
    if (p === "/api/live") return jsonResponse(live);
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    return null;
  });
  global.location.hash = `#/term/${encodeURIComponent(paneId)}`;
  await app.route();
  await settle();
  return h.dom().mainEl;
}
const roleLive = () => liveWith({ sessions: [{ terminal_id: PANE, pane_id: PANE, agent: "claude", status: "waiting", role_label: "CEO" }],
  panes: [{ pane_id: PANE, kind: "agent" }] });

test("F3 a role terminal's way back is 回角色卡池, and the old name is gone", async () => {
  const main = await openTerminal(PANE, { live: roleLive(), tasks: [] });
  const back = byData(main, "data-term", "back")[0];
  assert.strictEqual(text(back), "回角色卡池");
  assert.strictEqual(back.getAttribute("href"), "#/team");
  assert.strictEqual(byData(main, "data-term", "back-task").length, 0, "no task card tracks it: no button for one");
  assert(!text(main).includes("返回團隊"));
  assert(!APP_SRC.includes("返回團隊"), "the old name is nowhere in the page code");
});

test("F3 a terminal tracked on a task card also gets 回任務卡, to that card", async () => {
  const tasks = [{ id: "t-other", title: "別的", associated_pane_id: "n-ffffffffffff" }, { id: "t-mine", title: "我的", associated_pane_id: PANE }];
  const main = await openTerminal(PANE, { live: roleLive(), tasks });
  const toTask = byData(main, "data-term", "back-task")[0];
  assert(toTask, "the button is there");
  assert.strictEqual(text(toTask), "回任務卡");
  assert.strictEqual(toTask.getAttribute("href"), "#/workbench?task=t-mine");
  assert.strictEqual(text(byData(main, "data-term", "back")[0]), "回角色卡池", "the pool button stays");
});

test("F3 the built-in terminal keeps 所有終端機 and never gets 回任務卡", async () => {
  const live = liveWith({ panes: [{ pane_id: PANE, kind: "shell", cwd: "/tmp/x" }] });
  const main = await openTerminal(PANE, { live, tasks: [{ id: "t-mine", associated_pane_id: PANE }] });
  assert.strictEqual(text(byData(main, "data-term", "back")[0]), "所有終端機");
  assert.strictEqual(byData(main, "data-term", "back")[0].getAttribute("href"), "#/terminals");
  assert.strictEqual(byData(main, "data-term", "back-task").length, 0);
});

test("F3 if the task list cannot be read the terminal page still has its back button", async () => {
  setHandler(() => null);
  const main = await (async () => {
    const orig = global.fetch;
    global.fetch = async (url, opts) => { if (String(url).startsWith("/api/tasks")) throw new Error("down"); return orig(url, opts); };
    try { return await openTerminal(PANE, { live: roleLive(), tasks: [] }); } finally { global.fetch = orig; }
  })();
  assert.strictEqual(text(byData(main, "data-term", "back")[0]), "回角色卡池");
});

// ---- F5: plain words for the engineering ones ------------------------------------------------------------------
test("F5 the main words are plain: the engineering names are gone from the page code, the technical values stay beside them", () => {
  const gone = ["僅觀看 (Observe)", "操作控制中 (Control)", "Pane ID", "關閉 session", "已有執行中的 session", "還沒有執行者 session",
    "無法核對 HEAD", "用來核對 HEAD", "BASE_IS_ANCESTOR：", "你自己 push", "合併與 push 關卡", "push（你來）", "HEAD 分離", "＋HEAD 核對",
    "不再核對目前的 HEAD", "目前的 commit。VBear", "bytes，sha256", " bytes・sha256", "關閉這個執行者 session"];
  for (const w of gone) assert(!APP_SRC.includes(w), `still in the page code: ${w}`);
  // the values a person decides on are still there, named in words
  for (const w of ["計畫雜湊（sha256）前 16 碼", "計畫長度", "位元組", "指紋（sha256）", "（BASE_IS_ANCESTOR）", "終端編號："]) assert(APP_SRC.includes(w), `lost: ${w}`);
});

test("F5 the next step after merging says 上傳, and the gates and the merge panel are named the same way", () => {
  const ns = app.nextSteps(flowView("awaiting_push"));
  assert.deepStrictEqual({ text: ns.after.text, who: ns.after.who }, { text: "你自己上傳到遠端", who: "你" });
  assert.strictEqual(app.nextStepSummary(flowView("awaiting_push")), "下一步：你自己上傳到遠端（輪到 你）");
  const grid = app.flowGateGrid(Object.assign(flowView("awaiting_push"), { attention: true, phase: { key: "awaiting_push", label: "等你上傳", reason: "" } }));
  assert(text(grid).includes("上傳（你來）") && !/push/.test(text(grid)));
});

test("F5 the terminal's mode badge speaks plainly, in both the standalone page and the toolbar", async () => {
  const main = await openTerminal(PANE, { live: roleLive(), tasks: [] });
  const t = text(main);
  assert(t.includes("只能觀看"), "a terminal that was only opened is 只能觀看");
  assert(!/Observe|Control\)/.test(t), "no English mode names on the page");
  assert(t.includes("終端編號：" + PANE), "the terminal's number is named in words");
});

test("F5 the CLI word is gone from the places that spoke to a person (product names such as Codex CLI stay)", () => {
  for (const w of ["消耗你的 CLI 帳號額度", "使用自己的本機 CLI：", "（CLI 回報）", 'el("dt", null, "CLI")', "改變 CLI 行為"]) assert(!APP_SRC.includes(w), w);
});

// ---- F6: same-name task cards and flows -------------------------------------------------------------------------
const day = (iso) => Math.floor(new Date(iso + "T12:00:00").getTime() / 1000);
test("F6 a title that two cards share gets the folder and the day; one that is alone gets nothing", () => {
  const a = { id: "t-a", title: "更新安裝說明", workdir: "/home/u/site-a", created_at: day("2026-10-01") };
  const b = { id: "t-b", title: "更新安裝說明", workdir: "/home/u/site-b", created_at: day("2026-10-09") };
  const c = { id: "t-c", title: "只有一張", workdir: "/home/u/site-c", created_at: day("2026-10-09") };
  assert.strictEqual(app.taskHintText(a), "資料夾 site-a・建立於 2026-10-01");
  assert.strictEqual(app.taskHintText(b), "資料夾 site-b・建立於 2026-10-09");
  assert.strictEqual(app.taskHintText({ id: "x", title: "t" }), "", "no folder and no date: nothing is made up");
  assert.strictEqual(app.taskHintText({ id: "x", workdir: "/p/q", created_at: "yesterday" }), "資料夾 q");
  assert.strictEqual(app.taskHintText(null), "");
  assert.deepStrictEqual([...app.duplicateTitles([a, b, c])], ["更新安裝說明"]);
  const cards = [a, b, c].map((t) => app.taskFrontCard(t, { flows: [], sameTitle: app.duplicateTitles([a, b, c]) }));
  const hint = (card) => byData(card, "data-hint", "same-title")[0];
  assert.strictEqual(text(hint(cards[0])), "資料夾 site-a・建立於 2026-10-01");
  assert.strictEqual(text(hint(cards[1])), "資料夾 site-b・建立於 2026-10-09");
  assert.strictEqual(hint(cards[2]), undefined, "a title nothing else shares has no extra line");
});

test("F6 two flows with one task title are told apart on the board and the list, and the repaint key follows", () => {
  const a = { id: "t-a", title: "整理首頁文案", workdir: "/home/u/site-a", created_at: day("2026-10-01") };
  const b = { id: "t-b", title: "整理首頁文案", workdir: "/home/u/site-b", created_at: day("2026-10-09") };
  app.noteTasks([a, b]);
  const f1 = Object.assign(flowView("planning"), { id: "flow-000000000001", task_id: "t-a", task_title: "整理首頁文案", roles: flowView("planning").roles, executor_live: null, latest_review: null });
  const f2 = Object.assign(flowView("planning"), { id: "flow-000000000002", task_id: "t-b", task_title: "整理首頁文案", executor_live: null, latest_review: null });
  const f3 = Object.assign(flowView("planning"), { id: "flow-000000000003", task_id: "t-c", task_title: "別的任務", executor_live: null, latest_review: null });
  app.D.flows = { flows: [f1, f2, f3] };
  assert.strictEqual(app.flowTitleHint(f1), "資料夾 site-a・建立於 2026-10-01");
  assert.strictEqual(app.flowTitleHint(f2), "資料夾 site-b・建立於 2026-10-09");
  assert.strictEqual(app.flowTitleHint(f3), "");
  for (const make of [(f) => app.questCard(f, true), (f) => app.flowCard(f)]) {
    assert.strictEqual(text(byData(make(f1), "data-hint", "same-title")[0]), "資料夾 site-a・建立於 2026-10-01");
    assert.strictEqual(byData(make(f3), "data-hint", "same-title").length, 0);
  }
  const key = (g) => app.boardKey({ error: "", yourTurnFlows: g, yourTurnSessions: [], inProgress: [], moreInProgress: 0, runtimeAvailable: true, allEmpty: false }, { liveError: "", projects: [] });
  const before = key([f1]);
  app.noteTasks([{ ...a, workdir: "/home/u/renamed" }, b]);
  assert.notStrictEqual(key([f1]), before, "the hint is part of what the board shows, so a change repaints it");
  app.D.flows = null;
});

test("F6 the 放上任務卡 menu adds the day to a title another card shares", async () => {
  closeDialogs();
  const t1 = { id: "t-a", title: "更新安裝說明", workdir: "/home/u/site-a", status: "draft", created_at: day("2026-10-01") };
  const t2 = { id: "t-b", title: "更新安裝說明", workdir: "/home/u/site-b", status: "draft", created_at: day("2026-10-09") };
  const t3 = { id: "t-c", title: "唯一的", workdir: "/home/u/site-c", status: "draft", created_at: day("2026-10-09") };
  setHandler((url) => {
    const p = String(url).split("?")[0];
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [t1, t2, t3] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    return null;
  });
  app.openPlaceDialog({ id: "p-1", name: "CEO" }, {});
  await settle();
  const rows = dialog().findAll((n) => n.getAttribute && n.getAttribute("data-place-task"));
  assert.strictEqual(rows.length, 3);
  const hints = (row) => byData(row, "data-hint", "same-title").map(text);
  assert.deepStrictEqual(hints(rows[0]), ["建立於 2026-10-01"]);
  assert.deepStrictEqual(hints(rows[1]), ["建立於 2026-10-09"]);
  assert.deepStrictEqual(hints(rows[2]), []);
  closeDialogs();
});

// ---- F7: the skill categories in Chinese ------------------------------------------------------------------------
test("F7 the seven English category names are shown in Chinese, any case; others stay as they came", () => {
  const want = { Development: "開發", Testing: "測試", Debugging: "除錯", Documentation: "文件", Security: "資安", DevOps: "部署維運", Data: "資料處理" };
  for (const [en, zh] of Object.entries(want)) {
    assert.strictEqual(app.categoryZh(en), zh, en);
    assert.strictEqual(app.categoryZh(en.toLowerCase()), zh, en.toLowerCase());
    assert.strictEqual(app.categoryZh(`  ${en.toUpperCase()} `), zh, "case and spaces do not matter");
  }
  for (const other of ["Design", "資安與防護", "constructor", "__proto__", "", "Data science"]) assert.strictEqual(app.categoryZh(other), other, other);
  assert.strictEqual(app.categoryZh(null), null);
});

test("F7 the 用途 filter shows the Chinese name and keeps the English id as its value", async () => {
  setHandler((url) => {
    const p = String(url).split("?")[0];
    if (p === "/api/overview") return jsonResponse(OVERVIEW);
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [{ id: "development", label: "Development" }, { id: "testing", label: "Testing" }, { id: "mystery", label: "Mystery" }] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse(liveWith());
    return null;
  });
  app.D.skills = null; app.D.categories = [];   // the earlier pages cached an empty index
  global.location.hash = "#/skills";
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  const main = h.dom().mainEl;
  const optVal = (o) => (o.getAttribute("value") !== null ? o.getAttribute("value") : o.value);
  const sel = main.findAll((n) => n.tag === "select").find((n) => n.findAll((o) => o.tag === "option").some((o) => optVal(o) === "development"));
  assert(sel, "the 用途 select is on the page: " + text(main).slice(0, 200));
  const opts = sel.findAll((o) => o.tag === "option").map((o) => [optVal(o), text(o)]);
  assert.deepStrictEqual(opts, [["", "全部"], ["development", "開發"], ["testing", "測試"], ["mystery", "Mystery"]]);
});

// ---- run ----------------------------------------------------------------------------------------------------------
(async () => {
  const timer = setTimeout(() => { console.error("TIMEOUT"); process.exit(2); }, 120000);
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name); console.log(e && e.stack || e); }
  }
  clearTimeout(timer);
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
