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

// ---- one staffing meeting: fixtures ----------------------------------------------------------------------------------

const REV = (c) => c.repeat(64);
const SENT = () => ({ cards: [["C1", "ceo"], ["C2", "pm"], ["C3", "eng"], ["C4", "eng2"], ["C5", "law"], ["C6", "art-off"], ["C7", "rev"], ["C8", "gone"]]
  .map(([alias, profile_id]) => ({ alias, profile_id, revision: REV("a"), enabled: profile_id !== "art-off" })),
  skills: [["S1", "sk-web"], ["S2", "sk-test"], ["S3", "sk-gone"], ["S4", "sk-codex"], ["S5", "sk-law-agy"]].map(([alias, skill_id]) => ({ alias, skill_id })),
  omitted: { cards: 0, skills: 2 }, inputs_sha256: REV("e") });
const skillOf = (skill_id, name, tool, categories, over = {}) => ({ skill_id, name, invoke_name: name, tool, read_by: [], scope: "user",
  activation: "active", mtime: 1, excerpt: "", categories, ...over });
const CATALOG = () => ({ ok: true, tools: ["claude", "codex", "agy", "shared"],
  skills: [skillOf("sk-web", "網站前端 " + EVIL, "claude", ["frontend"]), skillOf("sk-test", "測試檢查", "shared", ["quality"]),
    skillOf("sk-codex", "Codex 測試", "codex", ["quality"]), skillOf("sk-law-agy", "授權檢查（AGY）", "agy", ["legal"], { read_by: ["agy"] }),
    skillOf("sk-law-codex", "授權檢查（Codex）", "codex", ["legal"]), skillOf("sk-more", "前端再一張", "claude", ["frontend"])],
  skill_categories: [{ id: "frontend", label: "網站與前端" }, { id: "legal", label: "法律與合規" }, { id: "quality", label: "測試與審查" }] });
const people3 = () => [
  { profile_id: "pm", name: "PM 卡", position: "pm", tool: "claude", model_used: "sonnet", revision: REV("a"), proxy: false },
  { profile_id: "law", name: "法務卡", position: "legal", tool: "agy", model_used: "sonnet", revision: REV("a"), proxy: true },
  { profile_id: "ceo", name: "執行長卡", position: "planner", tool: "claude", model_used: "opus", revision: REV("a"), proxy: false }];
const evidence = (over = {}) => ({ cli_version: "2.1.296", model_reported: "claude-sonnet-x", tools_reported: ["StructuredOutput"],
  mcp_servers_reported: [], exit_code: 0, duration_ms: 4200, cost_usd: "0.0412", cost_source: "cli", ...over });
const sturn = (seq, profile_id, kind, state, over = {}) => ({ seq, profile_id, kind, state, attempts: 1, started_at: 1790000000 + seq,
  ended_at: state === "queued" || state === "running" ? null : 1790000010 + seq, prompt_sha256: REV("a"),
  evidence: state === "done" ? evidence() : null, output: null, error_code: null, ...over });
const pmSaid = () => ({ kept: { summary: "進度在前端 " + EVIL, needs: [{ what: "會測試的人 " + EVIL, position: "executor" }],
  recommend: [{ card: "C3", position: "executor", slot: "executor", why: "會前端 " + EVIL, flags: [] },
    { card: "", position: "legal", slot: "staff", why: "沒有合適的法務卡", flags: [] },
    { card: "C8", position: "reviewer", slot: "reviewer1", why: "已刪掉的卡", flags: [] },
    { card: "C6", position: "art", slot: "staff", why: "停用的藝術", flags: ["disabled"] }],
  skills: [{ skill: "S1", for: "C3", why: "已經插著", flags: ["already_equipped"] }, { skill: "S2", for: "executor", why: "給執行的人", flags: [] },
    { skill: "S3", for: "C3", why: "已不在技能庫", flags: [] }],
  skill_gaps: [{ need: "圖片授權檢查 " + EVIL, category: "legal", search_words: ["授權", EVIL] }],
  risks: [{ level: "中", text: "時程緊 " + EVIL, source: "" }] },
  notes: [{ code: "unknown_skill", text: "提到清單上沒有的技能「S99」，已拿掉" }] });
const lawSaid = () => ({ kept: { summary: "注意授權", needs: [], recommend: [], skills: [], skill_gaps: [],
  risks: [{ level: "高", text: "圖片沒有授權", source: "查無出處，需人工複核" }] }, notes: [] });
const ceoSaid = () => ({ kept: { summary: "用全端工程師做，Codex 審查 " + EVIL,
  team: [
    { slot: "planner", pick: "existing", card: "C1", new_ref: "", reason: "CEO 規劃", skills: [], flags: [] },
    { slot: "executor", pick: "existing", card: "C3", new_ref: "", reason: "會前端 " + EVIL,
      skills: [{ skill: "S1", why: "已經有", flags: ["already_equipped"] }, { skill: "S2", why: "要會測試", flags: [] }], flags: [] },
    { slot: "reviewer1", pick: "existing", card: "C4", new_ref: "", reason: "陣營不同", skills: [{ skill: "S4", why: "Codex 的測試", flags: [] }], flags: [] },
    { slot: "reviewer2", pick: "existing", card: "C2", new_ref: "", reason: "多一雙眼", skills: [], flags: ["slot_fit", "same_family"] }],
  staff: [{ position: "legal", pick: "new", card: "", new_ref: "N1", reason: "要一張法務卡", skills: [], flags: [] },
    { position: "art", pick: "existing", card: "C6", new_ref: "", reason: "停用中的藝術", skills: [], flags: ["disabled"] }],
  new_cards: [{ ref: "N1", position: "legal", tool: "claude", model_alias: "sonnet", name: "法務新卡 " + EVIL, reason: "沒有 Claude 的法務", skills: [] }],
  skill_gaps: [{ for: "C3", need: "圖片授權檢查", category: "legal", search_words: ["授權 檢查"], why: "技能庫沒有" },
    { for: "reviewer1", need: "資安", category: "other", search_words: [], why: "以後再說" }],
  risks: ["授權風險 " + EVIL], questions_for_chairman: ["要不要先做首頁？ " + EVIL],
  opinions_used: [{ from: "pm", point: "要會測試", adopted: true, why: "範圍需要 " + EVIL },
    { from: "legal", point: "加第二位審查", adopted: false, why: "範圍小" }] },
  notes: [{ code: "missing", text: "還差：審查位" }] });
function record(over = {}) {
  return { id: SID, kind: "staffing", task_id: "task-1", note: "補充 " + EVIL, created_at: 1790000000, participants: people3(),
    suggested: [{ profile_id: "pm", why: "有 PM 卡，負責講進度與分工" }, { profile_id: "eng", why: "任務分類有「網站與前端」" }],
    sent: SENT(), limits: { per_call_usd: "0.20", proposal_call_usd: "0.50", total_usd: "2.00" },
    turns: [sturn(1, "pm", "opinion", "done", { output: pmSaid() }), sturn(2, "law", "opinion", "done", { output: lawSaid() }),
      sturn(3, "ceo", "proposal", "done", { output: ceoSaid() })],
    status: "ready", chairman: { state: "pending", at: null, note: "", adopted: null, label: "主控台記錄（未驗證身分）" },
    spent_usd: "0.6100", retryable: [], high_risk: true, changed_cards: ["C3"], ...over };
}
function detail(r) { page.details[r.id] = r; return r; }
const PROFILES3 = () => PROFILES().map((p) => (p.id === "eng" ? { ...p, equipped_skill_ids: ["sk-web"] } : p));
function setRecord(over = {}, pageOver = {}) {
  setPage({ profiles: PROFILES3(), catalog: CATALOG(), ...pageOver });
  return detail(record(over));
}

// ---- the bubbles and the seats ---------------------------------------------------------------------------------------

test("a staffing bubble comes from the record only, from a closed table of its own", () => {
  const table = new Set(app.STAFFING_BUBBLES);
  for (const w of ["等發言", "發言中", "已建議", "失敗", "卡住", "額度不夠沒發言", "時間到沒發言", "整理意見中", "已提案"]) assert(table.has(w), w);
  const b = (kind, state, code = null) => app.staffingBubble({ kind, state, error_code: code });
  assert.deepStrictEqual(["queued", "running", "done", "failed", "blocked"].map((s) => b("opinion", s)), ["等發言", "發言中", "已建議", "失敗", "卡住"]);
  assert.strictEqual(b("opinion", "skipped", "budget"), "額度不夠沒發言");
  assert.strictEqual(b("opinion", "skipped", "time_up"), "時間到沒發言");
  assert.strictEqual(b("opinion", "skipped", "boundary_revoked"), "沒有發言");
  assert.strictEqual(b("proposal", "running"), "整理意見中");
  assert.strictEqual(b("proposal", "done"), "已提案");
  assert.strictEqual(b("proposal", "skipped", "no_opinions"), "沒有發言");
  for (const kind of ["opinion", "proposal", "decision", EVIL]) for (const state of ["queued", "running", "done", "failed", "blocked", "skipped", "cancelled", "interrupted", "x", undefined]) {
    for (const code of [null, "budget", "time_up", EVIL]) assert(table.has(b(kind, state, code)), JSON.stringify({ kind, state, code }));
  }
  assert.strictEqual(app.staffingBubble(null), "狀態不明");
  assert.strictEqual(b("decision", "done"), "狀態不明", "a meeting's kind is not a staffing one");
});

test("seats: the speakers in order, the CEO last, a spoken-for card marked, the label names the staffing record", () => {
  const seats = app.staffingSeats(record());
  assert.deepStrictEqual(seats.map((s) => s.profileId), ["pm", "law", "ceo"]);
  assert.deepStrictEqual(seats.map((s) => s.bubble), ["已建議", "已建議", "已提案"]);
  assert.deepStrictEqual(seats.map((s) => s.proxy), [false, true, false]);
  assert(seats[2].label.includes("組隊紀錄 " + SID), seats[2].label);
});

// ---- one staffing meeting ----------------------------------------------------------------------------------------

test("one staffing meeting: what each speaker said, with every alias shown as a name or as 「找不到」, all as text", async () => {
  setRecord();
  const main = await open("#/staffing/" + SID);
  noMarkup(main);
  const all = text(main);
  for (const piece of ["官網改版", "CEO 已提案：等你看", "0.6100", "2.00", "補充 ", "進度在前端", "會測試的人", "時程緊", "提到清單上沒有的技能「S99」，已拿掉",
    "圖片沒有授權", "查無出處，需人工複核", "2.1.296", "0.0412", "不是另外扣款"]) assert(all.includes(piece), piece);
  assert(all.includes(EVIL));
  const seats = qa(main, "seat");
  assert.strictEqual(seats.length, 3);
  assert(text(seats[1]).includes("代發言"));
  const recs = qa(seats[0], "recommend").map(text);
  assert(recs[0].includes("全端工程師") && recs[0].includes("執行位") && !recs[0].includes("C3"), recs[0]);
  assert(recs[1].includes("沒有合適的卡") && recs[1].includes("開會時找的幕僚") && recs[1].includes("法務經理"), recs[1]);
  assert(recs[2].includes("找不到"), "a card deleted since: " + recs[2]);
  assert(recs[3].includes("停用的藝術") && recs[3].includes("停用中"), recs[3]);
  const picks = qa(seats[0], "skill-pick").map(text);
  assert(picks[0].includes("網站前端") && picks[0].includes("全端工程師") && picks[0].includes("已插上"), picks[0]);
  assert(picks[1].includes("測試檢查") && picks[1].includes("全端工程師"), "a position is named by its label: " + picks[1]);
  assert(picks[2].includes("找不到"), "a skill gone from the index: " + picks[2]);
  const legal = text(seats[1]);
  assert(legal.includes("高"), legal);
});

test("a note of VBear's names a card or a skill by its alias; the page adds what that alias is today, or that it is not found", async () => {
  const pm = pmSaid();
  pm.notes = [{ code: "incompatible_skill", text: "技能「S1」和這張卡的工具不相容，已拿掉" },
    { code: "duplicate_card", text: "同一張卡「C3」出現在兩個地方，只留第一筆" },
    { code: "unknown_skill", text: "提到清單上沒有的技能「S99」，已拿掉" }, { code: "missing", text: "還差：審查位" }];
  const ceo = ceoSaid();
  ceo.notes = [{ code: "unknown_new_ref", text: "提到沒有寫出來的新卡「N3」，已拿掉" }, { code: "duplicate_ref", text: "新卡的代號「N1」重複，只留第一筆" }];
  setRecord({ turns: [sturn(1, "pm", "opinion", "done", { output: pm }), sturn(2, "law", "opinion", "done", { output: lawSaid() }),
    sturn(3, "ceo", "proposal", "done", { output: ceo })] });
  const main = await open("#/staffing/" + SID);
  const notes = qa(main, "notes");
  assert.strictEqual(notes.length, 2, "the speaker's notes and the CEO's");
  notes.forEach(noMarkup);
  const said = notes.map(text).join("\n");
  assert(said.includes("技能「S1」和這張卡的工具不相容，已拿掉（S1 是「網站前端 " + EVIL + "」）"), said);
  assert(said.includes("同一張卡「C3」出現在兩個地方，只留第一筆（C3 是「全端工程師」）"), said);
  assert(said.includes("提到清單上沒有的技能「S99」，已拿掉（S99 找不到）"), said);
  assert(said.includes("還差：審查位") && !said.includes("還差：審查位（"), said);
  assert(said.includes("提到沒有寫出來的新卡「N3」，已拿掉（N3 找不到）"), said);
  assert(said.includes("新卡的代號「N1」重複，只留第一筆（N1 是新卡「法務新卡 " + EVIL + "」）"), said);
});

test("the CEO's proposal: the places, the staff, the new cards, the gaps, and the opinions adopted and not, in two columns", async () => {
  setRecord();
  const main = await open("#/staffing/" + SID);
  const prop = q(main, "proposal");
  assert(prop, "the proposal");
  noMarkup(prop);
  const rows = qa(prop, "team-row");
  assert.deepStrictEqual(rows.map((r) => r.getAttribute("data-slot")), ["planner", "executor", "reviewer1", "reviewer2"]);
  assert(text(rows[0]).includes("規劃位") && text(rows[0]).includes("執行長卡"), text(rows[0]));
  assert(text(rows[1]).includes("全端工程師") && text(rows[1]).includes("網站前端") && text(rows[1]).includes("已插上") && text(rows[1]).includes("CEO 建議"), text(rows[1]));
  assert(text(rows[3]).includes("審查位和執行位同一陣營，審查結果不算數") && text(rows[3]).includes("職位和這個位置不太合"), text(rows[3]));
  const staff = qa(prop, "staff-row").map(text);
  assert(staff[0].includes("法務經理") && staff[0].includes("法務新卡") && staff[0].includes("建議新建"), staff[0]);
  assert(staff[1].includes("停用的藝術") && staff[1].includes("這張卡停用中，要先啟用"), staff[1]);
  assert(text(q(prop, "new-card")).includes("法務新卡") && text(q(prop, "new-card")).includes("Claude Code"), text(q(prop, "new-card")));
  const adopted = q(prop, "adopted");
  const not = q(prop, "not-adopted");
  assert(text(adopted).includes("採納的意見") && text(adopted).includes("PM") && text(adopted).includes("要會測試") && text(adopted).includes("範圍需要"), text(adopted));
  assert(text(not).includes("沒採納的意見") && text(not).includes("法務經理") && text(not).includes("加第二位審查"), text(not));
  assert(!text(adopted).includes("加第二位審查") && !text(not).includes("要會測試"));
  for (const piece of ["授權風險", "要不要先做首頁", "還差：審查位", "用全端工程師做"]) assert(text(prop).includes(piece), piece);
  assert(text(main).includes("這只是提醒"), "a high risk is a reminder, not a block");
  assert(text(q(main, "changed")).includes("全端工程師"), "the cards changed since are named");
});

test("a skill gap is plain text with a search of the skill library in this console, never a link out", async () => {
  setRecord();
  const main = await open("#/staffing/" + SID);
  const links = qa(main, "gap-link");
  assert(links.length >= 3, "a search per word");
  for (const a of links) {
    const href = a.getAttribute("href");
    assert(href.startsWith("#/skills?q="), href);
    assert(!href.includes("<") && !href.includes(" ") && !href.includes("://"), href);
  }
  const evil = links.find((a) => a.getAttribute("href").includes(encodeURIComponent(EVIL)));
  assert(evil && evil.getAttribute("href").endsWith("&cat=legal"), "a word is encoded, the category kept");
  const other = links.find((a) => a.getAttribute("href") === "#/skills?q=" + encodeURIComponent("授權 檢查") + "&cat=legal");
  assert(other, links.map((a) => a.getAttribute("href")).join(" "));
  const states = qa(main, "gap-state").map(text);
  assert(states.some((s) => s.includes("技能庫有 2 張") && s.includes("這張卡讀不到")), states.join("|"));
  assert(states.some((s) => s.includes("其他")), "a gap of 「其他」 is not counted: " + states.join("|"));
});

test("a running staffing meeting shows its clock and can be cancelled; nothing can be recorded meanwhile", async () => {
  const clock = { started_at: 1790000000, deadline_at: 1790000900, speakers_until: 1790000720, max_minutes: 15, remaining_s: 300 };
  const r = setRecord({ status: "running", clock, high_risk: false, changed_cards: [] });
  r.turns[1] = sturn(2, "law", "opinion", "running");
  r.turns[2] = sturn(3, "ceo", "proposal", "queued");
  const main = await open("#/staffing/" + SID);
  assert(text(qm(main, "clock")).includes("剩下 5 分 00 秒"), text(main));
  assert.deepStrictEqual(app.staffingSeats(r).map((s) => s.bubble), ["已建議", "發言中", "等發言"]);
  assert.strictEqual(q(main, "proposal"), null);
  assert.strictEqual(qm(main, "delete"), null, "a running one is not deleted");
  page.details[SID] = record({ status: "incomplete", high_risk: false, changed_cards: [] });
  qm(main, "cancel").click();
  await settle();
  assert.strictEqual(posts("/cancel").length, 1);
  assert.deepStrictEqual(posts("/cancel")[0].body, {});
});

test("a failed speaker shows why and can be tried again after its own preview; the CEO is asked again", async () => {
  const r = setRecord({ status: "incomplete", retryable: [2], high_risk: false });
  r.turns[1] = sturn(2, "law", "opinion", "failed", { error_code: "timeout", evidence: null });
  page.retryPreview = { preview_id: "rp-1", startable: true, blockers: [], staffing_id: SID, seq: 2,
    participant: { ...people3()[1], effort: "low", instructions: "指示" }, prompt: "重試的 prompt " + EVIL, prompt_sha256: REV("f"),
    calls: 2, reserve_usd: "0.70", proposal_again: true, attempt: 2, today: { spent_usd: "0.5", daily_usd: "3.00", lamp: "green" },
    cli: { version: "2.1.296", verified: true }, speed: SPEED, disclosure: "送到 Anthropic", cost_note: "估值" };
  const main = await open("#/staffing/" + SID);
  const seat = qa(main, "seat")[1];
  assert(text(seat).includes("失敗") && text(seat).includes("逾時"), text(seat));
  q(seat, "retry").click();
  await settle();
  assert.deepStrictEqual(posts("/retry-preview")[0].body, { seq: 2 });
  const dlg = dialog();
  noMarkup(dlg);
  assert(text(dlg).includes("重試的 prompt") && text(dlg).includes("CEO 會重問"), text(dlg));
  assert(text(q(dlg, "reserve")).includes("預留 US$0.70"), text(q(dlg, "reserve")));
  qm(dlg, "start").click();
  await settle();
  assert.deepStrictEqual(posts("/retry")[0].body, { preview_id: "rp-1" });
});

test("a decision the chairman recorded is shown as a record of the console; this page offers no way to record one", async () => {
  setRecord({ status: "adopted", chairman: { state: "adopted", at: 1790009999, note: "照做 " + EVIL, adopted: null, label: "主控台記錄（未驗證身分）" } });
  const main = await open("#/staffing/" + SID);
  const desk = q(main, "chairman");
  assert(text(desk).includes("採用") && text(desk).includes("主控台記錄（未驗證身分）") && text(desk).includes("照做"), text(desk));
  noMarkup(desk);
  assert.strictEqual(posts("/chairman").length, 0);
  assert.strictEqual(desk.findAll((n) => n.tag === "button").length, 0);
});

test("every flag of the server has words; a code the page does not know is shown as it is", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "..", "vbear", "staffing.py"), "utf8");
  const block = src.slice(src.indexOf("FLAGS = {"), src.indexOf("}", src.indexOf("FLAGS = {")));
  const codes = [...block.matchAll(/"([a-z_]+)": "([^"]+)"/g)];
  assert.strictEqual(codes.length, 8, block);
  for (const [, code, words] of codes) assert.strictEqual(app.STAFFING_FLAG_TEXT[code], words, code);
  assert.strictEqual(app.staffingFlagText("brand_new"), "代碼：brand_new");
});

test("deleting a staffing record asks first; a record that cannot be read says so", async () => {
  setRecord();
  let main = await open("#/staffing/" + SID);
  qm(main, "delete").click();
  await settle();
  const ask = h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("aria-labelledby") === "modal-confirm-title");
  assert(ask, "asked in the page");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0, "nothing deleted by the first click");
  ask.remove();
  main = await open("#/staffing/s-ffffffffffff");
  assert(text(main).includes("找不到這份組隊紀錄"), text(main));
});

// ---- the person's draft of the proposal ------------------------------------------------------------------------------

const draftRow = (main, key) => qa(main, "draft-row").find((r) => r.getAttribute("data-key") === key);
const takeOf = (r) => q(r, "take").checked;
const skillBoxes = (r) => qa(r, "draft-skill");
async function choose(select, value) { select.value = value; select.dispatch("change"); await settle(); }
const draftKey = "sid:staffing.edit." + SID;

test("the draft starts from the proposal: what VBear flagged, a same-camp review included, is not ticked; the CEO's skills are", async () => {
  delete global.localStorage._store[draftKey];
  setRecord();
  const main = await open("#/staffing/" + SID);
  const draft = q(main, "draft");
  assert(draft, "a draft");
  noMarkup(draft);
  assert.deepStrictEqual(qa(draft, "draft-row").map((r) => r.getAttribute("data-key")),
    ["slot:planner", "slot:executor", "slot:reviewer1", "slot:reviewer2", "staff:legal", "staff:art"]);
  const ticks = Object.fromEntries(qa(draft, "draft-row").map((r) => [r.getAttribute("data-key"), takeOf(r)]));
  assert.deepStrictEqual(ticks, { "slot:planner": true, "slot:executor": true, "slot:reviewer1": true, "slot:reviewer2": false,
    "staff:legal": true, "staff:art": false });
  const rev2 = draftRow(draft, "slot:reviewer2");
  assert(text(rev2).includes("審查位和執行位同一陣營，審查結果不算數"), text(rev2));
  assert(text(draftRow(draft, "staff:art")).includes("這張卡停用中，要先啟用"));
  const exec = draftRow(draft, "slot:executor");
  const boxes = skillBoxes(exec);
  assert.deepStrictEqual(boxes.map((b) => [b.getAttribute("data-skill"), b.checked, b.disabled]), [["sk-web", false, true], ["sk-test", true, false]]);
  assert(text(exec).includes("已插上") && text(exec).includes("CEO 建議"), text(exec));
  assert(text(exec).includes("組隊會議之後改過"), "a card changed since says so");
  assert(text(draftRow(draft, "staff:legal")).includes("法務新卡"), "a new card is the CEO's, by its name");
  const sum = text(q(draft, "draft-sum"));
  assert(sum.includes("要採用 4 列") && sum.includes("要插 2 張技能"), sum);
  assert(text(draft).includes("只存在這個瀏覽器"), "the draft says where it is kept");
  assert.strictEqual(writes().length, 0, "nothing is sent");
});

test("換人 checks the review places again by the page's own rule, and takes out the skills the new card cannot read", async () => {
  delete global.localStorage._store[draftKey];
  setRecord();
  const main = await open("#/staffing/" + SID);
  await choose(q(draftRow(main, "slot:executor"), "swap"), "card:eng2");
  let exec = draftRow(main, "slot:executor");
  assert(text(exec).includes("Codex 工程師"), text(exec));
  assert.deepStrictEqual(skillBoxes(exec).map((b) => b.getAttribute("data-skill")), ["sk-test"], "the Claude skill is taken out; the shared one stays");
  assert(text(exec).includes("拿掉了 1 張這張卡讀不到的技能"), text(exec));
  assert(text(exec).includes("出發通行證"), "whether VBear can start the card is not judged again here, and the page says so");
  const rev1 = draftRow(main, "slot:reviewer1");
  assert(text(rev1).includes("同一張卡不能審查自己") && !takeOf(rev1), "the same card in the execution and a review place");
  await choose(q(rev1, "swap"), "card:rev");
  assert(text(draftRow(main, "slot:reviewer1")).includes("審查位和執行位同一陣營"), "a Codex review of a Codex executor");
  assert(!takeOf(draftRow(main, "slot:reviewer1")));
  await choose(q(draftRow(main, "slot:executor"), "swap"), "card:eng");
  const after = draftRow(main, "slot:reviewer1");
  assert(!text(after).includes("審查結果不算數"), text(after));
  assert(!takeOf(after), "a row is never ticked by a change in another row");
  q(after, "take").checked = true;
  q(after, "take").dispatch("change");
  await settle();
  assert(takeOf(draftRow(main, "slot:reviewer1")));
  assert.strictEqual(writes().length, 0);
});

test("拿掉 empties a place or takes out a staff row; 加人 adds a staff position; a skill is added only from those the card can read", async () => {
  delete global.localStorage._store[draftKey];
  setRecord();
  const main = await open("#/staffing/" + SID);
  q(draftRow(main, "slot:reviewer2"), "remove").click();
  await settle();
  const rev2 = draftRow(main, "slot:reviewer2");
  assert(text(rev2).includes("空著") && !takeOf(rev2), text(rev2));
  q(draftRow(main, "staff:art"), "remove").click();
  await settle();
  assert.strictEqual(draftRow(main, "staff:art"), undefined);
  const add = q(main, "add-staff");
  assert(add.findAll((n) => n.tag === "option").map((o) => o.getAttribute("value")).includes("accountant"));
  assert(!add.findAll((n) => n.tag === "option").map((o) => o.getAttribute("value")).includes("legal"), "a position already on the draft is not offered");
  await choose(add, "accountant");
  const acc = draftRow(main, "staff:accountant");
  assert(acc && text(acc).includes("空著"), "a new staff row starts empty");
  const exec = draftRow(main, "slot:executor");
  const offered = q(exec, "add-skill").findAll((n) => n.tag === "option").map((o) => o.getAttribute("value")).filter(Boolean);
  assert.deepStrictEqual(offered.sort(), ["sk-more"], "a Claude card: its own and shared skills not already in the row, nothing of Codex or AGY");
  await choose(q(exec, "add-skill"), "sk-more");
  const added = skillBoxes(draftRow(main, "slot:executor")).find((b) => b.getAttribute("data-skill") === "sk-more");
  assert(added && added.checked, "the added skill is ticked");
  assert(text(draftRow(main, "slot:executor")).includes("你加的"));
  assert.strictEqual(writes().length, 0);
});

test("the draft is kept in this browser only: it comes back on the next visit, and 回到 CEO 的提案 drops it", async () => {
  delete global.localStorage._store[draftKey];
  setRecord();
  let main = await open("#/staffing/" + SID);
  q(draftRow(main, "slot:reviewer2"), "remove").click();
  await settle();
  assert(global.localStorage._store[draftKey], "kept under the record's own key");
  main = await open("#/staffing/" + SID);
  assert(text(draftRow(main, "slot:reviewer2")).includes("空著"), "the draft is read back");
  q(main, "draft-reset").click();
  await settle();
  assert(text(draftRow(main, "slot:reviewer2")).includes("PM 卡"), text(draftRow(main, "slot:reviewer2")));
  assert.strictEqual(JSON.parse(global.localStorage._store[draftKey] || "null"), null, "no draft is kept");
  assert.strictEqual(writes().length, 0);
});

test("a draft of an earlier proposal, or one that cannot be read, is not used", async () => {
  for (const kept of [JSON.stringify({ basis: "3:0:1", rows: [] }), "not json", JSON.stringify({ basis: null, rows: "x" })]) {
    global.localStorage._store[draftKey] = kept;
    setRecord();
    const main = await open("#/staffing/" + SID);
    assert(text(draftRow(main, "slot:reviewer2")).includes("PM 卡"), "made again from the proposal");
    if (kept.startsWith("{\"basis\":\"3")) assert(text(q(main, "draft")).includes("CEO 重新提案過"), text(q(main, "draft")));
  }
  delete global.localStorage._store[draftKey];
});

test("no draft while the CEO has not proposed, or once the chairman has recorded a decision", async () => {
  const r = setRecord({ status: "incomplete", high_risk: false });
  r.turns[2] = sturn(3, "ceo", "proposal", "failed", { error_code: "invalid_output", evidence: null });
  let main = await open("#/staffing/" + SID);
  assert.strictEqual(q(main, "draft"), null);
  setRecord({ status: "dismissed", chairman: { state: "dismissed", at: 1790009999, note: "", adopted: null, label: "x" } });
  main = await open("#/staffing/" + SID);
  assert.strictEqual(q(main, "draft"), null);
});

test("the page's places fit the positions the server's do", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "..", "vbear", "staffing.py"), "utf8");
  const block = src.slice(src.indexOf("SLOT_FIT = {"), src.indexOf("\n\n", src.indexOf("SLOT_FIT = {")));
  for (const slot of ["planner", "executor", "reviewer1", "reviewer2"]) {
    const m = new RegExp(`"${slot}": \\(([^)]*)\\)`).exec(block);
    assert(m, slot);
    assert.deepStrictEqual(app.STAFFING_SLOT_FIT[slot], [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]), slot);
  }
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
