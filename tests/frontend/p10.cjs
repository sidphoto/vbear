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
  assert(!text(merge).includes("合併與 push 關卡"), "off the flow page there is no such panel to point to");
  const onPage = app.nextStepActionNode(flowView("awaiting_merge"), { task, onFlowPage: true });
  assert(text(onPage).includes("下方「合併與 push 關卡」"));
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
