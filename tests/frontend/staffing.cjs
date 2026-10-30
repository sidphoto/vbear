// P35-3: the pages of a staffing meeting (組隊會議). The entries (a task card in the lobby, the workbench, the team board),
// the form with VBear's suggested speakers and their reasons, the preview, one staffing meeting (seats with bubbles from a
// closed table, what each speaker said, the CEO's proposal with the opinions adopted and not) and the person's draft of
// the proposal. The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a
// model: the server answers with fixtures, and every string a model or a card could hold is tried with markup in it.
// Run: node tests/frontend/staffing.cjs   (exit code 0 = pass)
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

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-st") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-st") === key);
const qm = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-mt") === key);
const EVIL = "<img src=x onerror=alert(1)>";
const noMarkup = (node) => assert.strictEqual(node.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");

// ---- fixtures ---------------------------------------------------------------------------------------------------

const SID = "s-0123456789ab";
const SID2 = "s-ba9876543210";
const cardOf = (id, name, position, tool = "claude", over = {}) => ({ id, name, position, enabled: true, model: { tool, model_id: "" },
  equipped_skill_ids: [], revision: id.padEnd(64, "0").slice(0, 64).replace(/[^0-9a-f]/g, "a"), ...over });
const PROFILES = () => [
  cardOf("ceo", "執行長卡", "planner"),
  cardOf("pm", "PM 卡 " + EVIL, "pm"),
  cardOf("eng", "全端工程師", "executor"),
  cardOf("eng2", "Codex 工程師", "executor", "codex"),
  cardOf("law", "法務卡", "legal", "agy"),
  cardOf("art-off", "停用的藝術", "art", "claude", { enabled: false }),
  cardOf("rev", "審查員", "reviewer", "codex"),
];
const TASK = (over = {}) => ({ id: "task-1", title: "官網改版", goal: "改版並檢查圖片授權", scope: [], out_of_scope: [], deliverables: [],
  acceptance_criteria: [], evidence: [], status: "draft", workdir: "/tmp/x", provenance: {}, steps: [], artifacts: [], ...over });
const SUGGEST = () => ({ task_id: "task-1",
  categories: [{ id: "frontend", label: "網站與前端", keyword: "前端" }, { id: "legal", label: "法律與合規", keyword: "授權" }],
  suggested: [
    { profile_id: "pm", position: "pm", why: "有 PM 卡，負責講進度與分工", name: "PM 卡 " + EVIL },
    { profile_id: "eng", position: "executor", why: "任務分類有「網站與前端」（提到「前端」），所以找全端工程師", name: "全端工程師" },
    { profile_id: "law", position: "legal", why: "任務分類有「法律與合規」（提到「授權」），所以找法務經理 " + EVIL, name: "法務卡" }],
  chairs: [{ profile_id: "ceo", name: "執行長卡" }] });
const SPEED = { speaker_effort: "low", chair_effort: "medium", max_minutes: 15, chair_reserve_minutes: 3,
  labels: { speaker_effort: "低", chair_effort: "中" }, note: "伺服器的說明" };
const person = (id, name, position, tool, over = {}) => ({ profile_id: id, name, position, tool, model: "sonnet", model_used: "sonnet",
  proxy: tool !== "claude", effort: "low", instructions: `你是${name}`, prompt: `給${name}的 prompt ${EVIL}`, prompt_sha256: "b".repeat(64),
  dynamic: false, ...over });
const previewOf = (over = {}) => ({ preview_id: "sp-1", startable: true, blockers: [], task_id: "task-1", note: "", task: { title: "官網改版" },
  categories: SUGGEST().categories,
  suggested: SUGGEST().suggested.map((s) => ({ ...s, chosen: s.profile_id !== "law" })),
  list: { list_max: 40960, cards: 6, skills: 12, omitted: { cards: 0, skills: 3 } },
  participants: [person("pm", "PM 卡", "pm", "claude"), person("eng2", "Codex 工程師", "executor", "codex")],
  chair: person("ceo", "執行長卡", "planner", "claude", { model: "opus", model_used: "opus", effort: "medium", dynamic: true, prompt: "給 CEO 的 prompt" }),
  calls: 3, reserve_usd: "0.90", reserve: { speakers: 2, per_call_usd: "0.20", proposal_call_usd: "0.50" },
  limits: { per_call_usd: "0.20", proposal_call_usd: "0.50", total_usd: "2.00", daily_usd: "3.00" },
  today: { spent_usd: "0.40", daily_usd: "3.00", lamp: "green" }, cli: { version: "2.1.296", verified: true }, speed: SPEED,
  disclosure: "開始後，下面每一段文字會用你的 Claude 帳號送到 Anthropic。", cost_note: "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。", ...over });
const ledger = (over = {}) => ({ spent_usd: "0.40", daily_usd: "3.00", per_call_usd: "0.20", meeting_usd: "1.50", lamp: "green",
  running: null, blocked: false, includes: ["meetings", "staffing"], note: "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。", ...over });
const row = (over = {}) => ({ id: SID, task_id: "task-1", created_at: 1790000000, status: "ready", chairman_state: "pending", spent_usd: "0.6100",
  high_risk: false, participants: 3, ...over });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { profiles: PROFILES(), tasks: [TASK(), TASK({ id: "task-9", title: "別張卡" })], suggest: SUGGEST(), suggestStatus: 200, ledger: ledger(),
    list: [row(), row({ id: SID2, task_id: "task-9", status: "running" })], details: {}, preview: previewOf(), previewStatus: 200,
    catalog: { ok: true, skills: [], skill_categories: [] }, ...over };
  setHandler((url, opts) => {
    const [p, qs] = url.split("?");
    const params = new URLSearchParams(qs || "");
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: page.profiles });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: page.tasks });
    if (p === "/api/config") return jsonResponse({ ok: true, config: {} });
    if (p === "/api/agent-builder/catalog") return jsonResponse(page.catalog);
    if (p === "/api/meetings" && method === "GET") return jsonResponse({ meetings: [] });
    if (p === "/api/meetings/ledger") return jsonResponse(page.ledger);
    if (p === "/api/staffing/suggest") {
      return page.suggestStatus === 200 ? jsonResponse({ ...page.suggest, task_id: params.get("task_id") })
        : jsonResponse({ code: "not_found", error: "找不到這張任務卡" }, false, page.suggestStatus);
    }
    if (p === "/api/staffing/preview") return page.previewStatus === 200 ? jsonResponse(page.preview) : jsonResponse(page.preview, false, page.previewStatus);
    if (p === "/api/staffing" && method === "GET") {
      const t = params.get("task_id");
      return jsonResponse({ staffing: t ? page.list.filter((r) => r.blocked || r.task_id === t) : page.list });
    }
    if (p === "/api/staffing" && method === "POST") return jsonResponse(page.details[SID] || { id: SID }, true, 202);
    const m = /^\/api\/staffing\/(s-[0-9a-f]{12})(?:\/([a-z-]+))?$/.exec(p);
    if (m && !m[2] && method === "GET") return page.details[m[1]] ? jsonResponse(page.details[m[1]]) : jsonResponse({ code: "not_found", error: "找不到這份組隊紀錄" }, false, 404);
    if (m && !m[2] && method === "DELETE") return jsonResponse({ ok: true, deleted: m[1] });
    if (m && m[2] === "retry-preview") return jsonResponse(page.retryPreview);
    if (m && (m[2] === "retry" || m[2] === "cancel")) return jsonResponse(page.details[m[1]], true, m[2] === "retry" ? 202 : 200);
    if (p === "/api/meetings/verify") return jsonResponse({ version: "2.1.296", passed_at: 1790000000 });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    return null;
  });
  FETCH_LOG.length = 0;
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = (fn) => { page.tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const posts = (suffix) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.endsWith(suffix));
const writes = () => FETCH_LOG.filter((c) => c.method !== "GET");
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const speakerBox = (main, id) => qa(main, "speaker").find((b) => b.getAttribute("data-profile") === id);

// ---- the entries -------------------------------------------------------------------------------------------------

test("a task card in the lobby, the workbench and the team board each lead to the staffing form of that card", async () => {
  const href = "#/staffing?task=task-1";
  const card = app.taskFrontCard(TASK(), { flows: [], profiles: [], tasks: [TASK()] });
  const link = card.find((n) => n.tag === "a" && n.getAttribute("href") === href);
  assert(link && text(link).includes("請 CEO 組隊"), "the lobby's task card");
  const board = app.teamBoard({ task: TASK(), flow: null, profiles: PROFILES(), catalog: { ok: false }, gitState: "git" });
  const onBoard = board.node.find((n) => n.tag === "a" && n.getAttribute("href") === href);
  assert(onBoard && text(onBoard).includes("請 CEO 組隊"), "the team board's head");
  setPage();
  const main = await open("#/workbench?task=task-1");
  const block = q(main, "task-staffing");
  assert(block, "the workbench's task tab has a block of its staffing meetings");
  assert(block.find((n) => n.tag === "a" && n.getAttribute("href") === href), "a new one about it");
  assert(block.find((n) => n.tag === "a" && n.getAttribute("href") === "#/staffing/" + SID), "its own record");
  assert(!block.find((n) => n.tag === "a" && n.getAttribute("href") === "#/staffing/" + SID2), "not another card's");
});

test("the workbench says so when the staffing meetings could not be read, and when there are none", () => {
  const none = app.taskStaffingBlock("task-1", { staffing: [] });
  assert(text(none).includes("還沒有組隊會議"), text(none));
  const unread = app.taskStaffingBlock("task-1", null);
  assert(text(unread).includes("讀不到組隊會議"), text(unread));
  const blocked = app.taskStaffingBlock("task-1", { staffing: [{ id: SID, blocked: true, error: "壞了 " + EVIL }] });
  assert(text(blocked).includes("無法讀取"), text(blocked));
  noMarkup(blocked);
});

// ---- the form ----------------------------------------------------------------------------------------------------

test("the form ticks VBear's suggestions with their reasons; a person may change them; a disabled card is not listed", async () => {
  setPage();
  const main = await open("#/staffing?task=task-1");
  noMarkup(main);
  assert(text(main).includes("官網改版"), "the task card's title");
  const ids = qa(main, "speaker").map((b) => b.getAttribute("data-profile"));
  assert.deepStrictEqual(ids, ["pm", "eng", "eng2", "law"], "one box per enabled card of a speaking position, in the table's order");
  assert(!ids.includes("art-off") && !ids.includes("rev") && !ids.includes("ceo"));
  assert.deepStrictEqual(qa(main, "speaker").filter((b) => b.checked).map((b) => b.getAttribute("data-profile")), ["pm", "eng", "law"]);
  const whys = qa(main, "why").map(text);
  assert(whys.some((w) => w.includes("有 PM 卡，負責講進度與分工")), whys.join("|"));
  assert(whys.some((w) => w.includes("提到「授權」") && w.includes(EVIL)), "the reason is the server's words, as text");
  assert(text(speakerBox(main, "eng2").parentNode).includes("VBear 沒有建議"), text(speakerBox(main, "eng2").parentNode));
  assert(text(speakerBox(main, "law").parentNode).includes("代發言"), "a card of another tool is spoken for by Claude");
  assert(text(q(main, "disabled-note")).includes("停用的卡不能發言，但 CEO 可以提案用它"), text(main));
  assert(text(q(main, "disabled-note")).includes("1 張"), text(q(main, "disabled-note")));
  assert.deepStrictEqual(qm(main, "chair").findAll((n) => n.tag === "option").map((n) => n.getAttribute("value")), ["ceo"]);
  assert(text(q(main, "categories")).includes("網站與前端") && text(q(main, "categories")).includes("提到「前端」"));
  assert(text(main).includes("不提供高"), "the speed is said before the preview too");
  assert(text(qm(main, "money-why")).includes("不是另外扣款"));
  assert(qm(main, "lamp"), "today's lamp");
  assert.strictEqual(writes().length, 0, "opening the form sends nothing");
});

test("the preview is asked with what is ticked, in the table's order, and the note", async () => {
  setPage();
  const main = await open("#/staffing?task=task-1");
  speakerBox(main, "law").checked = false;
  speakerBox(main, "eng").checked = false;
  speakerBox(main, "eng2").checked = true;
  q(main, "note").value = "  先做首頁  ";
  qm(main, "preview").click();
  await settle();
  const sent = posts("/api/staffing/preview");
  assert.strictEqual(sent.length, 1);
  assert.deepStrictEqual(sent[0].body, { task_id: "task-1", chair_profile_id: "ceo", speaker_profile_ids: ["pm", "eng2"], note: "先做首頁" });
});

test("the form refuses no speaker or two cards of one position before asking the server", async () => {
  setPage();
  const main = await open("#/staffing?task=task-1");
  for (const b of qa(main, "speaker")) b.checked = false;
  qm(main, "preview").click();
  await settle();
  assert(text(h.dom().toastEl).includes("至少"), text(h.dom().toastEl));
  speakerBox(main, "eng").checked = true;
  speakerBox(main, "eng2").checked = true;
  qm(main, "preview").click();
  await settle();
  assert(text(h.dom().toastEl).includes("每個職位只能有一張卡"), text(h.dom().toastEl));
  assert.strictEqual(posts("/api/staffing/preview").length, 0);
});

test("a red lamp or no CEO card: no preview can be asked, and the page says why", async () => {
  setPage({ ledger: ledger({ lamp: "red", spent_usd: "3.00" }) });
  let main = await open("#/staffing?task=task-1");
  assert.strictEqual(qm(main, "preview").disabled, true);
  assert(text(main).includes("額度"), text(main));
  setPage({ profiles: PROFILES().filter((p) => p.id !== "ceo") });
  main = await open("#/staffing?task=task-1");
  assert.strictEqual(qm(main, "preview").disabled, true);
  assert(text(main).includes("CEO 職位的角色卡"), text(main));
});

test("a task card the server cannot find says so and offers no form", async () => {
  setPage({ suggestStatus: 404 });
  const main = await open("#/staffing?task=task-1");
  assert(text(main).includes("找不到這張任務卡"), text(main));
  assert.strictEqual(qm(main, "preview"), null);
});

test("without a task card the page lists every staffing meeting and asks which card first", async () => {
  setPage({ list: [row(), row({ id: SID2, task_id: "task-9", status: "running" }), { id: "s-cccccccccccc", blocked: true, error: "結構不符 " + EVIL }] });
  const main = await open("#/staffing");
  noMarkup(main);
  const rows = qa(main, "staffing-row");
  assert.strictEqual(rows.length, 3);
  assert(text(main).includes("官網改版") && text(main).includes("別張卡"), "a record is named by its task card");
  assert(text(rows[2]).includes("無法讀取"));
  const pick = q(main, "task-pick");
  assert(pick, "a task card picker");
  pick.value = "task-9";
  pick.dispatch("change");
  await settle();
  assert.strictEqual(global.location.hash, "#/staffing?task=task-9");
});

test("the page's order of the speaking positions and the note's limit are the server's", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "..", "vbear", "staffing.py"), "utf8");
  const table = src.slice(src.indexOf("SUGGEST_SPEAKERS: tuple"), src.indexOf("def _why"));
  const order = [...table.matchAll(/"position": "([a-z]+)"/g)].map((m) => m[1]);
  assert.strictEqual(order.length, 6, table);
  assert.deepStrictEqual(app.STAFFING_SPEAKER_ORDER, order);
  assert(/NOTE_MAX, WHY_MAX = 500, 200/.test(src), "the note's limit is 500 on the server");
  assert(fs.readFileSync(path.join(root, "app.js"), "utf8").includes("const STAFFING_NOTE_MAX = 500;"));
});

// ---- the preview -------------------------------------------------------------------------------------------------

test("the preview: the reserve as speakers × their limit + the CEO's, the record's and the day's limits, the list, the suggestions", async () => {
  setPage();
  const main = await open("#/staffing?task=task-1");
  qm(main, "preview").click();
  await settle();
  const dlg = dialog();
  assert(dlg, "a dialog");
  noMarkup(dlg);
  const all = text(dlg);
  assert(all.includes("組隊會議前的預覽"), all.slice(0, 80));
  const reserve = text(q(dlg, "reserve"));
  for (const piece of ["預留 US$0.90", "發言 2 × US$0.20", "CEO US$0.50", "這份組隊提案最多 US$2.00", "每天 US$3.00", "和會議共用"]) {
    assert(reserve.includes(piece), piece + " | " + reserve);
  }
  const size = text(q(dlg, "list-size"));
  assert(size.includes("角色卡 6 張") && size.includes("技能 12 張") && size.includes("3 張技能沒有列出"), size);
  const sug = text(q(dlg, "suggested"));
  assert(sug.includes("有 PM 卡") && sug.includes("你勾了") && sug.includes("你沒勾"), sug);
  for (const piece of ["給PM 卡的 prompt", "給 CEO 的 prompt", "你是執行長卡", "2.1.296", "送到 Anthropic", "代發言", "不提供高"]) assert(all.includes(piece), piece);
  assert(all.includes(EVIL));
  assert(text(qm(dlg, "money-why")).includes("不是另外扣款"));
  assert(qm(dlg, "speed"));
  qm(dlg, "start").click();
  await settle();
  const start = FETCH_LOG.filter((c) => c.method === "POST" && c.url === "/api/staffing");
  assert.deepStrictEqual(start.map((c) => c.body), [{ preview_id: "sp-1" }], "start sends only the preview id");
  assert.strictEqual(global.location.hash, "#/staffing/" + SID);
});

test("a preview that cannot start shows the server's blocker and no start button", async () => {
  setPage({ preview: previewOf({ startable: false, preview_id: null, blockers: [{ code: "budget", message: "額度不夠：超過這份組隊提案或每日上限" }] }) });
  const main = await open("#/staffing?task=task-1");
  qm(main, "preview").click();
  await settle();
  assert(text(dialog()).includes("額度不夠：超過這份組隊提案或每日上限"));
  assert.strictEqual(qm(dialog(), "start"), null);
});

test("a refused preview says what the server said and opens nothing", async () => {
  setPage({ previewStatus: 409, preview: { code: "busy", error: "已有一場會議或組隊會議在進行，請等它結束或取消" } });
  const main = await open("#/staffing?task=task-1");
  qm(main, "preview").click();
  await settle();
  assert.strictEqual(dialog(), null);
  assert(text(h.dom().toastEl).includes("已有一場會議或組隊會議在進行"), text(h.dom().toastEl));
});

// ---- run ---------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
    const d = dialog();
    if (d) d.remove();
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
