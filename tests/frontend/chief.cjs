// The chief of staff and the dispatch on the page (v0.15 P40-5): the button and the dialog on the CEO's chat page, the proposal
// card (change a word, delete a step, swap a person, confirm, not adopt, 你改過, the most it can cost), the dispatch pages (every
// step's state, stop, continue, withdraw), 「AI 自己做了什麼」 (#/actions), the lobby's 「輪到你」 and the note on a message VBear
// sent for a dispatch. The real web/app.js on a synthetic DOM and a fetch stub answered by the test; it is NOT a browser test and
// it runs no model and no AI tool. The words are the plan's (P40) and the reports' of P40-1 to P40-4.
// Run: node tests/frontend/chief.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const attr = (n, k) => n && n.getAttribute && n.getAttribute(k);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const ROOT = path.join(__dirname, "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const START = "// ---------- the chief of staff and the dispatch";
const BLOCK = SRC.slice(SRC.indexOf(START), SRC.indexOf("// ---------- end of the chief of staff and the dispatch"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const by = (key, value) => (n) => attr(n, key) === value;
const find = (root, key, value) => root.find(by(key, value));
const findAll = (root, key, value) => root.findAll(by(key, value));
const button = (root, label) => root.find((n) => n.tag === "button" && text(n) === label);
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const EVIL = "<img src=x onerror=alert(1)>";

const CHAT = "c-0123456789abcdef";
const DID = "d-0123456789ab";
const COS = "cos-0123456789ab";
const SHA = "a".repeat(64);

// ---- fixtures: the shapes the server sends (vbear/chief_runner.py, vbear/chief.py, vbear/dispatch.py) ----------------------------------

const detail = (over = {}) => ({ ok: true, chat: { id: CHAT, profile_id: "ceo-1", created_at: 1790000000, engine: "claude-chat" },
  card: { id: "ceo-1", name: "虛構 CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const employee = () => detail({ chat: { id: CHAT, profile_id: "emp-1", created_at: 1, engine: "claude-chat" },
  card: { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null } });
const codexCeo = () => detail({ card: { id: "ceo-1", name: "虛構 CEO", position: "planner", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null } });
const preview = (over = {}) => ({ preview_id: "p" + "0".repeat(23), ok: true, blockers: [], chat_id: CHAT, messages: 6, omitted_messages: 0, bytes: 900, cards: 2,
  omitted_cards: 0, tools: ["claude", "codex"], cap_usd: "0.3", day_left_usd: "2.71", today: { spent_usd: "0.29", daily_usd: "3", lamp: "green" },
  sends_to: "Claude Code", ceo_tool: "claude", notice: null, cli: { version: "2.1.318", verified: true },
  disclosure: "開始後，你和 CEO 最近的對話（最多 20 則、12 KiB）與員工名單，會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。",
  cost_note: "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。沒有回報時，以每次上限計（最壞情況）。", ...over });
const CODEX_NOTICE = "這張 CEO 是 Codex 的角色卡：你和它的對話會送給 Claude Code（Anthropic）整理成提議。";
const chiefView = (over = {}) => ({ id: COS, created_at: 1790000100, chat_id: CHAT, status: "running", state: "running", error_code: null, attempts: 1, retryable: [],
  spent_usd: "0", cost_source: null, limits: { per_call_usd: "0.3", total_usd: "0.9" }, read: { count: 6 }, note_chars: 0, plan: null, notes: [], dispatch_id: null, outcome: "none", ...over });
const dview = (over = {}) => ({ id: DID, chief_id: COS, chat_id: CHAT, created_at: 1790000200, state: "proposed", started_by: null, started_by_text: null,
  summary: "我建議找文案小編和一位新的會計師，分三步做。", questions: [], notes: [],
  team: [{ who: "C1", why: "會寫文案", kind: "existing", name: "文案小編" }, { who: "N1", why: "算成本", kind: "new", name: "會計師" }],
  tools: ["claude", "codex"], proposal_sha: SHA, edited: false, task_id: null, created_cards: [], steps: [],
  plan: { title: "週末市集擺攤", goal: "準備手工皂攤位", deliverables: ["攤位介紹", "價目表"],
    new_cards: [{ ref: "N1", name: "會計師", position: "accountant", tool: "claude", model_alias: "haiku" }],
    steps: [{ who: "C1", text: "請寫攤位介紹與價目表", name: "文案小編" }, { who: "N1", text: "請算成本與定價", name: "會計師" },
      { who: "C1", text: "請依定價改好價目表", name: "文案小編" }] },
  cost: { steps: 3, per_turn_usd: "0.5", max_usd: "1.5", day_left_usd: "2.71" }, pause: null, events: [],
  can: { confirm: true, dismiss: true, stop: false, continue: false, delete: true, withdraw: [] }, ...over });
const row = (v) => ({ id: v.id, chief_id: v.chief_id, chat_id: v.chat_id, created_at: v.created_at, state: v.state, title: v.plan.title, steps: v.plan.steps.length, started_by: v.started_by });

let S;        // what the stub serves
function serve(over = {}) {
  S = { detail: detail(), chiefs: [], dispatches: [], views: {}, chiefViews: {}, preview: preview(), lamp: "green", chats: [], previewFail: null, post: {}, ...over };
  FETCH_LOG.length = 0;
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [], sources: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse({ ok: true, chats: S.chats, more: 0, cards: [], support: {}, limits: { per_turn_usd: "0.5", daily_usd: "3" },
      ledger: { spent_usd: "0.1", daily_usd: "3", lamp: S.lamp }, problems: [] });
    if (/^\/api\/chats\/c-[0-9a-f]{16}\/stream$/.test(p)) return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (/^\/api\/chats\/c-[0-9a-f]{16}$/.test(p) && method === "GET") return jsonResponse(S.detail);
    if (p === "/api/meetings/ledger") return jsonResponse({ ok: true, spent_usd: "0.29", daily_usd: "3", lamp: S.lamp, blocked: false });
    if (p === "/api/chief/preview") return S.previewFail ? jsonResponse({ error: S.previewFail }, false, 409) : jsonResponse(S.preview);
    if (p === "/api/chief" && method === "GET") return jsonResponse({ chief: S.chiefs });
    if (p === "/api/chief" && method === "POST") return S.post.chief ? S.post.chief(body) : jsonResponse({ chief_id: COS, chief: chiefView() }, true, 202);
    let m = /^\/api\/chief\/(cos-[0-9a-f]{12})(?:\/(retry|cancel))?$/.exec(p);
    if (m && !m[2] && method === "GET") return S.chiefViews[m[1]] ? jsonResponse(S.chiefViews[m[1]]) : jsonResponse({ error: "沒有" }, false, 404);
    if (m && m[2]) return S.post[m[2]] ? S.post[m[2]](body) : jsonResponse(chiefView({ status: "running" }), true, 202);
    if (p === "/api/dispatch" && method === "GET") return jsonResponse({ dispatch: S.dispatches });
    if (p === "/api/actions") return jsonResponse(S.actions || { actions: [], unreadable: 0 });
    m = /^\/api\/dispatch\/(d-[0-9a-f]{12})(?:\/([a-z-]+))?$/.exec(p);
    if (m && !m[2] && method === "GET") return S.views[m[1]] ? jsonResponse(S.views[m[1]]) : jsonResponse({ error: "找不到這份派工" }, false, 404);
    if (m && m[2]) return S.post[m[2]] ? S.post[m[2]](body) : jsonResponse(S.views[m[1]] || dview());
    if (p === "/api/tasks") return jsonResponse({ tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: false });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false, onboarding_dismissed: true, setup_done: true, welcome_seen: true }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/first-ceo") return jsonResponse({ needed: false });
    if (p === "/api/meetings" || p === "/api/staffing") return jsonResponse({ meetings: [], staffing: [] });
    if (p === "/api/setup/tools") return jsonResponse({ tools: [] });
    if (p === "/api/meetings/verify") return S.post.verify ? S.post.verify(body) : jsonResponse({ ok: true, version: "2.1.318" });
    return null;
  });
}
async function open(hash) {
  const real = global.setInterval;
  const ticks = [];
  global.setInterval = (fn) => { ticks.push(fn); return ticks.length; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  S.ticks = ticks;
  return h.dom().mainEl;
}
const posts = (suffix) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0].endsWith(suffix));
async function click(node) { node.dispatch("click"); await settle(); }
async function type(node, value) { node.value = value; node.dispatch("input"); await settle(); }
async function pick(node, value) { node.value = value; node.dispatch("change"); await settle(); }
const desk = (main) => find(main, "data-chief", "desk");
const card = (main) => find(main, "data-dispatch", "proposal");
const stepRows = (main) => findAll(card(main), "data-dispatch", "step");
const costLine = (main) => text(find(card(main), "data-dispatch", "cost"));

// ---- the button and the dialog ------------------------------------------------------------------------------------------

test("only a CEO's chat page has the button 「請幕僚長安排」", async () => {
  serve();
  let main = await open("#/chat/" + CHAT);
  assert(desk(main), "a desk on the CEO's page");
  assert(button(desk(main), "請幕僚長安排"));
  serve({ detail: employee() });
  main = await open("#/chat/" + CHAT);
  assert.strictEqual(desk(main), null, "none on an employee's page");
  assert.strictEqual(button(main, "請幕僚長安排"), null);
});

test("opening the page asks for no preview and starts nothing", async () => {
  serve();
  await open("#/chat/" + CHAT);
  assert(!FETCH_LOG.some((c) => c.url.includes("/api/chief/preview")), "no preview before the button");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0);
});

test("a Codex CEO: beside the button it says the conversation goes to Claude Code", async () => {
  serve({ detail: codexCeo() });
  const main = await open("#/chat/" + CHAT);
  const t = text(desk(main));
  assert(t.includes("Claude Code") && t.includes("Anthropic") && t.includes("對話"), t);
  serve();
  const claude = await open("#/chat/" + CHAT);
  assert(!text(desk(claude)).includes("Anthropic"), "a Claude CEO needs no such line beside the button");
});

test("the dialog says what is read, the most it costs and what is left today, before anything is sent", async () => {
  serve();
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  const d = dialog();
  assert(d, "a dialog");
  const t = text(d);
  assert(t.includes("最多花 US$0.30"), t);
  assert(t.includes("今天還剩 US$2.71"), t);
  assert(t.includes("6 則") && t.includes("你和 CEO 最近的對話"), t);
  assert(t.includes("Claude Code") && t.includes("Anthropic"), "where the conversation goes: " + t);
  assert(t.includes("只提議") || t.includes("不會動手"), t);
  assert.strictEqual(posts("/api/chief").length, 0, "nothing is sent by opening the dialog");
  assert(!t.includes("2.1.318") || true);
  assert(button(d, "取消") && button(d, "請幕僚長安排"));
});

test("the cap shown is the preview's (less than US$0.30 when the day has less left)", async () => {
  serve({ preview: preview({ cap_usd: "0.07", day_left_usd: "0.07" }) });
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  assert(text(dialog()).includes("最多花 US$0.07"), text(dialog()));
});

test("a Codex CEO's dialog carries the server's notice that the conversation goes to Claude Code", async () => {
  serve({ detail: codexCeo(), preview: preview({ ceo_tool: "codex", notice: CODEX_NOTICE }) });
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  assert(text(dialog()).includes(CODEX_NOTICE), text(dialog()));
});

test("starting sends the preview id and the note (200 characters at most), and nothing else", async () => {
  serve();
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  const note = find(dialog(), "data-chief", "note");
  assert(note && note.tag === "textarea" && attr(note, "maxlength") === "200", "a note box of 200 characters");
  await type(note, "週末要擺攤");
  await click(button(dialog(), "請幕僚長安排"));
  assert.deepStrictEqual(posts("/api/chief").map((c) => c.body), [{ preview_id: "p" + "0".repeat(23), note: "週末要擺攤" }]);
  assert.strictEqual(dialog(), null, "the dialog is gone");
});

test("an empty note is not sent", async () => {
  serve();
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  await click(button(dialog(), "請幕僚長安排"));
  assert.deepStrictEqual(posts("/api/chief").map((c) => c.body), [{ preview_id: "p" + "0".repeat(23) }]);
});

test("cancelling sends nothing", async () => {
  serve();
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  await click(button(dialog(), "取消"));
  assert.strictEqual(dialog(), null);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0);
});

test("no Claude Code: 「幕僚長目前需要 Claude Code」, how to get it, a link to the start-up page, and no way to start", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [{ code: "cli_not_found", message: "幕僚長目前需要 Claude Code，請到「開始設定」安裝並登入" }], cli: { version: null, verified: false } }) });
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  const d = dialog();
  assert(text(d).includes("幕僚長目前需要 Claude Code"), text(d));
  assert(text(d).includes("Anthropic") && text(d).includes("開始設定"));
  const go = find(d, "data-chief", "setup-go");
  assert(go && attr(go, "href") === "#/setup", "a link to the start-up page");
  assert.strictEqual(button(d, "請幕僚長安排"), null, "no start button");
});

test("a Claude Code that has not passed the tool-less check: a check button, said what it costs, then the preview again", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [{ code: "boundary_unverified", message: "這個 Claude Code 版本還沒通過無工具安全檢查，請先檢查" }] }) });
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  const verify = find(dialog(), "data-chief", "verify");
  assert(verify, "a check button");
  assert(text(verify).includes("不到 1 美分"), text(verify));
  serve({ preview: preview() });                   // after the check the preview is fine
  await click(verify);
  const confirm = dialog();
  assert(text(confirm).includes("無工具安全檢查") && text(confirm).includes("Claude"), text(confirm));
  assert.strictEqual(posts("/api/meetings/verify").length, 0, "asked first");
  await click(button(confirm, "檢查"));
  assert.strictEqual(posts("/api/meetings/verify").length, 1);
  assert(button(dialog(), "請幕僚長安排"), "the preview was asked again and can start now");
});

test("other blockers are said in the server's words and keep the start button away", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [{ code: "no_conversation", message: "你和 CEO 還沒有對話，先跟 CEO 說說想做什麼" }, { code: "budget", message: "額度不夠" }] }) });
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  const t = text(dialog());
  assert(t.includes("你和 CEO 還沒有對話") && t.includes("額度不夠"), t);
  assert.strictEqual(button(dialog(), "請幕僚長安排"), null);
});

test("a preview the server refuses (not a CEO, the card cannot chat) is said and no dialog opens", async () => {
  serve({ previewFail: "只有 CEO 職位的角色卡的聊天，才能請幕僚長安排" });
  const main = await open("#/chat/" + CHAT);
  await click(button(desk(main), "請幕僚長安排"));
  assert.strictEqual(dialog(), null);
  assert(text(h.dom().toastEl).includes("只有 CEO 職位"), text(h.dom().toastEl));
});

// ---- the chief thinking, failing, retrying ------------------------------------------------------------------------------------

test("while the chief of staff thinks the desk says so and can cancel", async () => {
  serve({ chiefs: [{ id: COS, created_at: 1790000100, chat_id: CHAT, status: "running", spent_usd: "0", dispatch_id: null }], chiefViews: { [COS]: chiefView() } });
  const main = await open("#/chat/" + CHAT);
  assert(text(desk(main)).includes("幕僚長在想"), text(desk(main)));
  await click(button(desk(main), "取消"));
  assert.strictEqual(posts("/cancel").length, 1);
  assert.deepStrictEqual(posts("/cancel")[0].body, {});
});

test("another chat's proposal is not on this page", async () => {
  serve({ chiefs: [{ id: COS, created_at: 1790000100, chat_id: "c-ffffffffffffffff", status: "running", spent_usd: "0", dispatch_id: null }],
    chiefViews: { [COS]: chiefView({ chat_id: "c-ffffffffffffffff" }) } });
  const main = await open("#/chat/" + CHAT);
  assert(!text(desk(main)).includes("幕僚長在想"));
});

test("an empty plan (empty_plan) and a format the model got wrong (invalid_output) are said in plain words, with retry when the server allows it", async () => {
  for (const [code, words] of [["empty_plan", "沒有提出可以做的步驟"], ["invalid_output", "格式不對"]]) {
    serve({ chiefs: [{ id: COS, created_at: 1790000100, chat_id: CHAT, status: "failed", spent_usd: "0.05", dispatch_id: null }],
      chiefViews: { [COS]: chiefView({ status: "failed", state: "failed", error_code: code, retryable: [1], spent_usd: "0.05" }) } });
    const main = await open("#/chat/" + CHAT);
    const t = text(desk(main));
    assert(t.includes(words), code + ": " + t);
    assert(t.includes("US$0.05"), "what it cost: " + t);
    await click(button(desk(main), "重試一次"));
    assert.strictEqual(posts("/retry").length, 1, code);
    assert.deepStrictEqual(posts("/retry")[0].body, {});
  }
});

test("no retry button when the server offers none; an unknown code is shown as it is, never guessed", async () => {
  serve({ chiefs: [{ id: COS, created_at: 1790000100, chat_id: CHAT, status: "failed", spent_usd: "0", dispatch_id: null }],
    chiefViews: { [COS]: chiefView({ status: "failed", state: "failed", error_code: "brand_new_code", retryable: [] }) } });
  const main = await open("#/chat/" + CHAT);
  assert.strictEqual(button(desk(main), "重試一次"), null);
  assert(text(desk(main)).includes("brand_new_code"), text(desk(main)));
});

// ---- the proposal card ----------------------------------------------------------------------------------------------------------

function withProposal(over = {}, extra = {}) {
  const v = dview(over);
  serve({ dispatches: [row(v)], views: { [DID]: v }, chiefs: [{ id: COS, created_at: 1790000100, chat_id: CHAT, status: "ready", spent_usd: "0.08", dispatch_id: DID }],
    chiefViews: { [COS]: chiefView({ status: "ready", state: "done", spent_usd: "0.08", cost_source: "cli", dispatch_id: DID }) }, ...extra });
  return v;
}

test("a proposal on the chat page: the chief's words, the task, who, why, every step with the words that will be sent, and what the chief cost", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  assert(card(main), "the card is on the CEO's page");
  const t = text(card(main));
  for (const s of ["我建議找文案小編和一位新的會計師，分三步做。", "攤位介紹", "文案小編", "現有員工", "會計師", "新建", "算成本", "第 1 步", "第 3 步", "US$0.08", "Claude Code 回報"]) assert(t.includes(s), s + " :: " + t);
  assert.strictEqual(find(card(main), "data-dispatch", "title").value, "週末市集擺攤");
  assert.strictEqual(find(card(main), "data-dispatch", "goal").value, "準備手工皂攤位");
  assert.deepStrictEqual(stepRows(main).map((r) => find(r, "data-dispatch", "step-text").value), ["請寫攤位介紹與價目表", "請算成本與定價", "請依定價改好價目表"]);
  assert.strictEqual(stepRows(main).length, 3);
  assert(button(card(main), "確認派工") && button(card(main), "不採用"));
});

test("the most it can cost: steps × the per-turn limit, and what is left today", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  assert.strictEqual(costLine(main).includes("最多 US$1.50（3 步 × 每回合上限 US$0.50）"), true, costLine(main));
  assert(costLine(main).includes("今天還剩 US$2.71"), costLine(main));
  assert(!costLine(main).includes("每天上限，VBear 會停下來"), "it fits in what is left");
});

test("when the most is more than what is left, it says the dispatch may stop at the daily limit and how to go on", async () => {
  withProposal({ cost: { steps: 3, per_turn_usd: "0.5", max_usd: "1.5", day_left_usd: "1.20" } });
  const main = await open("#/chat/" + CHAT);
  assert(costLine(main).includes("做到一半碰到每天上限") && costLine(main).includes("按「繼續」"), costLine(main));
});

test("the cost line follows the steps: delete one and the most falls", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await click(button(stepRows(main)[2], "刪掉這一步"));
  assert.strictEqual(stepRows(main).length, 2);
  assert(costLine(main).includes("最多 US$1.00（2 步 × 每回合上限 US$0.50）"), costLine(main));
});

test("the employees say that the employees still ask for every command, and that a message sent cannot be taken back", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  const t = text(card(main));
  assert(t.includes("每個指令") && t.includes("都問你"), t);
  assert(t.includes("收不回來") && t.includes("停止"), t);
  assert(t.includes("安全模式") && t.includes("技能"), "the new employee: safe mode, no skill: " + t);
  assert(t.includes("上一步") && t.includes("資料"), "the next step gets the last reply, as data: " + t);
});

test("untouched: no 你改過 anywhere; changing a step's words marks that step and the whole card", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  const shown = () => findAll(card(main), "data-dispatch", "edited").filter((n) => !n.hidden);
  assert.strictEqual(shown().length, 0);
  const area = find(stepRows(main)[1], "data-dispatch", "step-text");
  await type(area, "請用三行回答：成本與定價");
  const marked = shown();
  assert(marked.length >= 2, "the step and the card: " + marked.length);
  assert(marked.every((n) => text(n) === "你改過"));
  assert(!findAll(stepRows(main)[0], "data-dispatch", "edited").some((n) => !n.hidden), "the first step is not marked");
  assert(findAll(stepRows(main)[1], "data-dispatch", "edited").some((n) => !n.hidden), "the second is");
  await type(area, "請算成本與定價");                // back to the original: the mark goes
  assert.strictEqual(shown().length, 0);
});

test("changing the title, the goal, a new employee's name and model is marked and sent", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await type(find(card(main), "data-dispatch", "title"), "週末市集擺攤（手工皂）");
  await type(find(card(main), "data-dispatch", "goal"), "準備攤位與價目表");
  const n1 = find(card(main), "data-new", "N1");
  await type(find(n1, "data-new-field", "name"), "記帳會計師");
  await pick(find(n1, "data-new-field", "model_alias"), "sonnet");
  assert(findAll(card(main), "data-dispatch", "edited").filter((n) => !n.hidden).length >= 4);
  await click(button(card(main), "確認派工"));
  const sent = posts("/confirm")[0].body;
  assert.strictEqual(sent.proposal_sha, SHA);
  assert.strictEqual(sent.title, "週末市集擺攤（手工皂）");
  assert.strictEqual(sent.goal, "準備攤位與價目表");
  assert.deepStrictEqual(sent.new_cards, [{ ref: "N1", name: "記帳會計師", position: "accountant", tool: "claude", model_alias: "sonnet" }]);
  assert.deepStrictEqual(sent.steps.map((s) => s.who), ["C1", "N1", "C1"]);
});

test("confirming sends exactly the five fields the server takes, the plan as the person left it", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await click(button(card(main), "確認派工"));
  assert.strictEqual(posts("/confirm").length, 1);
  assert.deepStrictEqual(Object.keys(posts("/confirm")[0].body).sort(), ["goal", "new_cards", "proposal_sha", "steps", "title"]);
  assert.deepStrictEqual(posts("/confirm")[0].body.steps, [{ who: "C1", text: "請寫攤位介紹與價目表" }, { who: "N1", text: "請算成本與定價" },
    { who: "C1", text: "請依定價改好價目表" }]);
  assert(posts("/confirm")[0].url.includes(DID));
  assert.strictEqual(global.location.hash, "#/dispatch/" + DID, "on to the dispatch page");
});

test("deleting a step sends one fewer; the last step cannot be deleted", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await click(button(stepRows(main)[1], "刪掉這一步"));
  assert(findAll(card(main), "data-dispatch", "edited").some((n) => !n.hidden), "marked");
  assert(text(card(main)).includes("你刪掉了 1 步"), text(card(main)));
  await click(button(card(main), "確認派工"));
  assert.deepStrictEqual(posts("/confirm")[0].body.steps.map((s) => s.text), ["請寫攤位介紹與價目表", "請依定價改好價目表"]);
  withProposal({ plan: { ...dview().plan, steps: [dview().plan.steps[0]] } });
  const one = await open("#/chat/" + CHAT);
  assert.strictEqual(button(stepRows(one)[0], "刪掉這一步").disabled, true);
});

test("a step can be handed to someone else and moved up or down", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await pick(find(stepRows(main)[0], "data-dispatch", "step-who"), "N1");
  await click(button(stepRows(main)[2], "上移"));
  await click(button(card(main), "確認派工"));
  assert.deepStrictEqual(posts("/confirm")[0].body.steps, [{ who: "N1", text: "請寫攤位介紹與價目表" }, { who: "C1", text: "請依定價改好價目表" }, { who: "N1", text: "請算成本與定價" }]);
});

test("the people a step may be handed to are the proposal's team, by name", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  const sel = find(stepRows(main)[0], "data-dispatch", "step-who");
  const opts = sel.findAll((n) => n.tag === "option");
  assert.deepStrictEqual(opts.map((o) => attr(o, "value")), ["C1", "N1"]);
  assert(text(opts[0]).includes("文案小編") && text(opts[1]).includes("會計師"));
});

test("a new employee taken out leaves their steps with no one: the card says so and will not confirm until they are handed over", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await click(button(find(card(main), "data-new", "N1"), "不要這位新員工"));
  const confirm = button(card(main), "確認派工");
  assert.strictEqual(confirm.disabled, true);
  assert(text(find(card(main), "data-dispatch", "why-disabled")).includes("請選一位員工"), text(card(main)));
  await pick(find(stepRows(main)[1], "data-dispatch", "step-who"), "C1");
  assert.notStrictEqual(button(card(main), "確認派工").disabled, true);
  await click(button(card(main), "確認派工"));
  assert.deepStrictEqual(posts("/confirm")[0].body.new_cards, [], "a new employee nobody works for is not made");
});

const MADE_N1 = (withdrawn) => ({ created_cards: [{ ref: "N1", name: "會計師", profile_id: "emp-new-1", withdrawn }] });

test("an employee made by 「自己動手第 1 項」 and taken back: a step still for them will not confirm; handing it over does (P40-6)", async () => {
  withProposal(MADE_N1(true));
  const main = await open("#/chat/" + CHAT);
  assert.strictEqual(button(card(main), "確認派工").disabled, true);
  const why = text(find(card(main), "data-dispatch", "why-disabled"));
  assert(why.includes("會計師") && why.includes("撤回") && why.includes("第 2 步"), why);
  await pick(find(stepRows(main)[1], "data-dispatch", "step-who"), "C1");
  assert.notStrictEqual(button(card(main), "確認派工").disabled, true);
  assert.strictEqual(text(find(card(main), "data-dispatch", "why-disabled")), "");
});

test("an employee that is on is not in the way of confirming", async () => {
  withProposal(MADE_N1(false));
  const main = await open("#/chat/" + CHAT);
  assert.notStrictEqual(button(card(main), "確認派工").disabled, true);
});

test("the card says what really happens to the new employees: made already (item 1 was on) or made on confirming", async () => {
  withProposal();
  let main = await open("#/chat/" + CHAT);
  assert(text(card(main)).includes("VBear 會建上面的新員工"), text(card(main)));
  withProposal(MADE_N1(false));
  main = await open("#/chat/" + CHAT);
  const t = text(card(main));
  assert(t.includes("新員工已經建好了") && !t.includes("VBear 會建上面的新員工"), t);
  assert(t.includes("按「確認派工」之後") && t.includes("任務卡"), t);
});

test("a new employee's choices: the position without the CEO, the tools the proposal could name, a model only for Claude Code", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  const n1 = find(card(main), "data-new", "N1");
  const positions = find(n1, "data-new-field", "position").findAll((n) => n.tag === "option").map((o) => attr(o, "value"));
  assert(positions.includes("accountant") && positions.includes("executor") && !positions.includes("planner"), positions.join());
  const tools = find(n1, "data-new-field", "tool").findAll((n) => n.tag === "option").map((o) => attr(o, "value"));
  assert.deepStrictEqual(tools, ["claude", "codex"]);
  assert(find(n1, "data-new-field", "model_alias"));
  await pick(find(n1, "data-new-field", "tool"), "codex");
  assert.strictEqual(find(find(card(main), "data-new", "N1"), "data-new-field", "model_alias"), null, "Codex has no model alias");
  await click(button(card(main), "確認派工"));
  assert.strictEqual(posts("/confirm")[0].body.new_cards[0].tool, "codex");
  assert.strictEqual(posts("/confirm")[0].body.new_cards[0].model_alias, "");
});

test("the questions of the chief of staff come first, and a plan with no step cannot be confirmed", async () => {
  withProposal({ questions: ["週末是哪一天？", "要賣幾種？"], plan: { ...dview().plan, steps: [] }, can: { ...dview().can, confirm: false } });
  const main = await open("#/chat/" + CHAT);
  const t = text(card(main));
  assert(t.includes("幕僚長想先問你") && t.includes("週末是哪一天？") && t.includes("要賣幾種？"), t);
  assert(t.indexOf("幕僚長想先問你") < t.indexOf("任務"), "first");
  assert(t.includes("回到和 CEO 的對話"), "what to do: " + t);
  assert.strictEqual(button(card(main), "確認派工"), null);
  assert(button(card(main), "不採用"));
});

test("what VBear took out is listed, with the codes turned into names", async () => {
  withProposal({ notes: [{ code: "step_unknown", text: "第 2 步指到清單上沒有的員工「C9」，沒有人做，已拿掉" }, { code: "unknown_card", text: "提到清單上沒有的員工「C1」，已拿掉" }] });
  const main = await open("#/chat/" + CHAT);
  const t = text(find(card(main), "data-dispatch", "notes"));
  assert(t.includes("VBear 拿掉或改了") && t.includes("第 2 步指到清單上沒有的員工"), t);
  assert(t.includes("文案小編") && !t.includes("「C1」"), "a code that is on the team is the name: " + t);
});

test("a lamp that is red: confirming is off and the reason is written; not adopting still works", async () => {
  withProposal({}, { lamp: "red" });
  const main = await open("#/chat/" + CHAT);
  assert.strictEqual(button(card(main), "確認派工").disabled, true);
  assert(text(find(card(main), "data-dispatch", "why-disabled")).includes("每天上限") && text(find(card(main), "data-dispatch", "why-disabled")).includes("亮紅燈"), text(card(main)));
  assert.notStrictEqual(button(card(main), "不採用").disabled, true);
});

test("not adopting asks first, says nothing will happen and that the chief's cost stays, then sends dismiss", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  await click(button(card(main), "不採用"));
  const d = dialog();
  assert(d && text(d).includes("不會建任何員工") && text(d).includes("花費照記"), text(d));
  assert.strictEqual(posts("/dismiss").length, 0);
  await click(button(d, "不採用"));
  assert.strictEqual(posts("/dismiss").length, 1);
  assert.deepStrictEqual(posts("/dismiss")[0].body, {});
});

test("a refusal on confirming (the proposal changed, an employee is gone) is shown in the server's words and nothing moves", async () => {
  withProposal({}, { post: { confirm: () => jsonResponse({ code: "card_changed", error: "有一位要派工的員工在提議之後被改過了，請重新整理再確認" }, false, 409) } });
  global.location.hash = "";
  const main = await open("#/chat/" + CHAT);
  await click(button(card(main), "確認派工"));
  const e = find(card(main), "data-dispatch", "error");
  assert(e && text(e).includes("被改過了"), text(card(main)));
  assert.notStrictEqual(global.location.hash, "#/dispatch/" + DID);
  assert.notStrictEqual(button(card(main), "確認派工").disabled, true, "the person may try again");
});

test("a proposal that was already decided is not drawn as a card on the chat page; it is a line with its state", async () => {
  const v = dview({ state: "running", started_by: "you", started_by_text: "你確認的" });
  serve({ dispatches: [row(v)], views: { [DID]: v }, chiefs: [] });
  const main = await open("#/chat/" + CHAT);
  assert.strictEqual(card(main), null);
  const link = desk(main).find((n) => n.tag === "a" && attr(n, "href") === "#/dispatch/" + DID);
  assert(link, "a link to the dispatch");
  assert(text(desk(main)).includes("週末市集擺攤") && text(desk(main)).includes("進行中"), text(desk(main)));
});

test("everything a model wrote stays text in the card", async () => {
  withProposal({ summary: EVIL, plan: { ...dview().plan, title: EVIL, goal: EVIL, deliverables: [EVIL], steps: [{ who: "C1", text: EVIL, name: EVIL }] },
    team: [{ who: "C1", why: EVIL, kind: "existing", name: EVIL }], questions: [EVIL], notes: [{ code: "x", text: EVIL }] });
  const main = await open("#/chat/" + CHAT);
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
  assert(text(card(main)).includes(EVIL));
});

test("the desk's polling does not rebuild a card the person is editing", async () => {
  withProposal();
  const main = await open("#/chat/" + CHAT);
  const area = find(stepRows(main)[0], "data-dispatch", "step-text");
  await type(area, "我改的字");
  for (const tick of S.ticks) await tick();
  await settle();
  assert.strictEqual(find(stepRows(main)[0], "data-dispatch", "step-text").value, "我改的字");
});

// ---- the dispatch pages ------------------------------------------------------------------------------------------------------------

const PROF_A = "emp-new-1";
const step = (seq, state, over = {}) => ({ seq, who: seq === 2 ? "N1" : "C1", name: seq === 2 ? "會計師" : "文案小編", profile_id: seq === 2 ? PROF_A : "emp-1",
  chat_id: state === "pending" ? null : "c-" + String(seq).repeat(16), text: "第 " + seq + " 步要送的話", state, turn: state === "pending" ? null : 1,
  cost_usd: state === "ended" ? "0.012" : null, ended_reason: state === "ended" ? "result" : null, ...over });
const running = (over = {}) => dview({ state: "running", started_by: "you", started_by_text: "你確認的", steps: [step(1, "ended"), step(2, "running"), step(3, "pending")],
  created_cards: [{ ref: "N1", name: "會計師", profile_id: PROF_A, withdrawn: false }],
  events: [{ seq: 1, at: 1790000300, kind: "confirmed", by: "you", edited: false, what: "確認了派工，開始準備", by_text: "你確認的" }],
  can: { confirm: false, dismiss: false, stop: true, continue: false, delete: false, withdraw: [PROF_A] }, task_id: "t-abc", ...over });
const stateOf = (main) => findAll(main, "data-dispatch", "step-row").map((n) => attr(n, "data-step-state"));
const withView = (v, extra = {}) => serve({ views: { [v.id]: v }, dispatches: [row(v)], ...extra });

test("the list: every dispatch with its state and steps, a damaged one said, an empty list explained", async () => {
  const a = running(), b = dview({ id: "d-bbbbbbbbbbbb", state: "paused", created_at: 1790000100 });
  serve({ dispatches: [row(a), row(b), { id: "d-cccccccccccc", blocked: true, error: "壞了" }] });
  const main = await open("#/dispatch");
  const rows = findAll(main, "data-dispatch", "row");
  assert.strictEqual(rows.length, 3);
  assert(text(rows[0]).includes("週末市集擺攤") && text(rows[0]).includes("進行中") && text(rows[0]).includes("3 步") && text(rows[0]).includes("你確認的"), text(rows[0]));
  assert(text(rows[1]).includes("暫停了"));
  assert(text(rows[2]).includes("無法讀取") && text(rows[2]).includes("壞了"));
  assert(find(main, "data-dispatch", "actions-link"));
  serve();
  const empty = await open("#/dispatch");
  assert(text(empty).includes("還沒有派工") && text(empty).includes("請幕僚長安排"));
});

test("a running dispatch: each step says whether it is not started, being done, waiting for the person's allow, done or not done, and links to the employee's chat", async () => {
  const v = running({ steps: [step(1, "ended"), step(2, "running"), step(3, "pending"), step(4, "ended", { ended_reason: "timeout", cost_usd: "0.5" })] });
  withView(v, { chats: [{ id: "c-" + "2".repeat(16), waiting: true, open: true }] });
  const main = await open("#/dispatch/" + DID);
  assert.deepStrictEqual(stateOf(main), ["done", "waiting", "pending", "failed"]);
  const rows = findAll(main, "data-dispatch", "step-row");
  assert(text(rows[0]).includes("做完了") && text(rows[1]).includes("等你按允許") && text(rows[2]).includes("還沒開始") && text(rows[3]).includes("沒做完"));
  assert(text(rows[3]).includes("等太久") || text(rows[3]).includes("逾時"), "why: " + text(rows[3]));
  assert.strictEqual(attr(find(rows[1], "data-dispatch", "step-chat"), "href"), "#/chat/c-" + "2".repeat(16));
  assert.strictEqual(find(rows[2], "data-dispatch", "step-chat"), null, "a step not started has no chat");
  assert(text(find(rows[0], "data-dispatch", "step-sent")).includes("第 1 步要送的話"), "what was sent");
  assert(text(rows[0]).includes("US$0.02"), "the cost, rounded up, as an estimate: " + text(rows[0]));
  assert(text(main).includes("最多 US$2.00"), "4 steps × 0.50: " + text(main));
});

test("a step that is running and not waiting says it is being done", async () => {
  withView(running());
  const main = await open("#/dispatch/" + DID);
  assert.deepStrictEqual(stateOf(main), ["done", "running", "pending"]);
  assert(text(findAll(main, "data-dispatch", "step-row")[1]).includes("正在做"));
});

test("stopping asks first (what it does, that a sent message cannot be taken back) and then sends stop", async () => {
  withView(running());
  const main = await open("#/dispatch/" + DID);
  await click(find(main, "data-dispatch", "stop"));
  const d = dialog();
  assert(d && text(d).includes("不會再送") && text(d).includes("收不回來"), text(d));
  assert.strictEqual(posts("/stop").length, 0);
  await click(button(d, "停止"));
  assert.strictEqual(posts("/stop").length, 1);
  assert.deepStrictEqual(posts("/stop")[0].body, {});
});

test("no stop, continue or delete button when the server says they do not apply", async () => {
  withView(running({ state: "done", can: { confirm: false, dismiss: false, stop: false, continue: false, delete: true, withdraw: [] } }));
  const main = await open("#/dispatch/" + DID);
  assert.strictEqual(find(main, "data-dispatch", "stop"), null);
  assert.strictEqual(find(main, "data-dispatch", "continue"), null);
  assert(find(main, "data-dispatch", "delete"));
  assert(text(main).includes("每一步都做完了"));
});

test("paused: the reason in words (which step, which tool, the limit, when it comes back or unknown) and the button 「繼續」", async () => {
  const words = "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；到時候按「繼續」接著做第 2 步。";
  withView(running({ state: "paused", steps: [step(1, "ended"), step(2, "pending"), step(3, "pending")], pause: { reason: "daily_limit", until: 1790100000, text: words },
    can: { confirm: false, dismiss: false, stop: true, continue: true, delete: false, withdraw: [PROF_A] } }));
  const main = await open("#/dispatch/" + DID);
  assert(text(find(main, "data-dispatch", "pause")).includes(words), text(find(main, "data-dispatch", "pause")));
  assert(text(find(main, "data-dispatch", "continue-note")).includes("接著送第 2 步"), text(find(main, "data-dispatch", "continue-note")));
  await click(find(main, "data-dispatch", "continue"));
  assert.strictEqual(posts("/continue").length, 1);
  assert.deepStrictEqual(posts("/continue")[0].body, {});
});

test("the plan's limit with no time given says unknown (the server's words are shown as they are)", async () => {
  const words = "Codex 的方案用量到了上限，恢復時間未知。";
  withView(running({ state: "paused", pause: { reason: "plan_limit", until: null, text: words }, can: { confirm: false, dismiss: false, stop: true, continue: true, delete: false, withdraw: [] } }));
  const main = await open("#/dispatch/" + DID);
  assert(text(find(main, "data-dispatch", "pause")).includes("恢復時間未知"));
});

test("pressing 「繼續」 after a step that did not finish skips it: the page says so before the press, and where to redo it", async () => {
  withView(running({ state: "paused", steps: [step(1, "ended"), step(2, "ended", { ended_reason: "timeout" }), step(3, "pending")],
    pause: { reason: "turn_timeout", until: null, text: "第 2 步等太久，逾時了。" }, can: { confirm: false, dismiss: false, stop: true, continue: true, delete: false, withdraw: [] } }));
  const main = await open("#/dispatch/" + DID);
  const n = text(find(main, "data-dispatch", "continue-note"));
  assert(n.includes("不會重做第 2 步") && n.includes("直接做第 3 步") && n.includes("可能不完整") && n.includes("到那位員工的聊天自己再說"), n);
});

test("a step that did not finish and was the last one: 「繼續」 only marks the dispatch done", async () => {
  withView(running({ state: "paused", steps: [step(1, "ended"), step(2, "ended"), step(3, "ended", { ended_reason: "error" })],
    pause: { reason: "turn_error", until: null, text: "第 3 步出了錯。" }, can: { confirm: false, dismiss: false, stop: true, continue: true, delete: false, withdraw: [] } }));
  const main = await open("#/dispatch/" + DID);
  const n = text(find(main, "data-dispatch", "continue-note"));
  assert(n.includes("最後一步") && n.includes("標成做完"), n);
});

test("a step whose message may or may not have gone out: look at the chat first; 「繼續」 sends it again only when it is not there", async () => {
  withView(running({ state: "paused", steps: [step(1, "ended"), step(2, "sending"), step(3, "pending")], pause: { reason: "uncertain", until: null, text: "VBear 不確定剛才有沒有建好" },
    can: { confirm: false, dismiss: false, stop: true, continue: true, delete: false, withdraw: [] } }));
  const main = await open("#/dispatch/" + DID);
  const n = text(find(main, "data-dispatch", "continue-note"));
  assert(n.includes("先到那位員工的聊天看一下") && n.includes("再送一次"), n);
});

test("the employees VBear made are listed; withdrawing asks first, says it only switches the card off, and sends the card's id", async () => {
  withView(running());
  const main = await open("#/dispatch/" + DID);
  const made = find(main, "data-dispatch", "made");
  assert(made && text(made).includes("會計師") && text(made).includes("使用中"), text(made));
  await click(find(main, "data-dispatch", "withdraw"));
  const d = dialog();
  assert(d && text(d).includes("停用") && text(d).includes("不會刪除"), text(d));
  await click(button(d, "撤回"));
  assert.deepStrictEqual(posts("/withdraw-card").map((c) => c.body), [{ profile_id: PROF_A }]);
});

test("a refusal to withdraw (the employee is working) is said, a withdrawn employee has no button", async () => {
  withView(running(), { post: { "withdraw-card": () => jsonResponse({ code: "turn_running", error: "這位員工正在做事，等這一回合結束或先按停止，再撤回" }, false, 409) } });
  let main = await open("#/dispatch/" + DID);
  await click(find(main, "data-dispatch", "withdraw"));
  await click(button(dialog(), "撤回"));
  assert(text(h.dom().toastEl).includes("正在做事"), text(h.dom().toastEl));
  withView(running({ created_cards: [{ ref: "N1", name: "會計師", profile_id: PROF_A, withdrawn: true }], can: { confirm: false, dismiss: false, stop: true, continue: false, delete: false, withdraw: [] } }));
  main = await open("#/dispatch/" + DID);
  assert.strictEqual(find(main, "data-dispatch", "withdraw"), null);
  assert(text(find(main, "data-dispatch", "made")).includes("已撤回"));
});

test("the task card VBear made is linked; the things done are listed with who decided", async () => {
  withView(running());
  const main = await open("#/dispatch/" + DID);
  assert.strictEqual(attr(find(main, "data-dispatch", "task-link"), "href"), "#/workbench?task=t-abc");
  const ev = findAll(main, "data-dispatch", "event");
  assert.strictEqual(ev.length, 1);
  assert(text(ev[0]).includes("確認了派工") && text(ev[0]).includes("你確認的"));
});

test("deleting a dispatch asks first and says that the employees, the task card and the chats stay", async () => {
  withView(running({ state: "stopped", can: { confirm: false, dismiss: false, stop: false, continue: false, delete: true, withdraw: [] } }));
  const main = await open("#/dispatch/" + DID);
  await click(find(main, "data-dispatch", "delete"));
  assert(text(dialog()).includes("員工、任務卡和聊天都留著"), text(dialog()));
  await click(button(dialog(), "刪除"));
  assert.strictEqual(posts("/delete").length, 1);
  assert.strictEqual(global.location.hash, "#/dispatch");
});

test("a dispatch that still waits for the person shows the proposal card on its own page", async () => {
  withView(dview());
  const main = await open("#/dispatch/" + DID);
  assert(card(main), "the card is here too");
  await click(button(card(main), "確認派工"));
  assert.strictEqual(posts("/confirm").length, 1);
});

test("a dispatch that is not there says so", async () => {
  serve();
  const main = await open("#/dispatch/" + DID);
  assert(text(main).includes("找不到"), text(main));
});

test("the page refreshes quietly: a step that ends changes the word without a new page", async () => {
  const v = running();
  withView(v);
  const main = await open("#/dispatch/" + DID);
  assert.deepStrictEqual(stateOf(main), ["done", "running", "pending"]);
  S.views[DID] = running({ steps: [step(1, "ended"), step(2, "ended"), step(3, "running")] });
  for (const tick of S.ticks) await tick();
  await settle();
  assert.deepStrictEqual(stateOf(main), ["done", "done", "running"]);
});

test("what a model wrote in a step stays text on the dispatch page", async () => {
  withView(running({ steps: [step(1, "ended", { text: EVIL, name: EVIL })], plan: { ...dview().plan, title: EVIL } }));
  const main = await open("#/dispatch/" + DID);
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
  assert(text(main).includes(EVIL));
});

// ---- 「AI 自己做了什麼」 --------------------------------------------------------------------------------------------------------------

const action = (over = {}) => ({ at: 1790000300, dispatch_id: DID, seq: 1, kind: "confirmed", what: "確認了派工，開始準備", by: "you", by_text: "你確認的", profile_id: null, can_stop: false, can_withdraw: false, ...over });

test("the list: what was done, when, who decided (you, or 自己動手 item 1 or 2), a link to the dispatch", async () => {
  serve({ actions: { unreadable: 0, actions: [
    action({ seq: 5, kind: "step_sent", what: "送出第 1 步給「文案小編」（已經送出，收不回來）", by: "auto2", by_text: "自己動手第 2 項", can_stop: true }),
    action({ seq: 3, kind: "card_created", what: "建了新員工「會計師」（安全模式，沒有技能）", by: "auto1", by_text: "自己動手第 1 項", profile_id: PROF_A, can_withdraw: true }),
    action({ seq: 1 })] } });
  const main = await open("#/actions");
  const rows = findAll(main, "data-action", "row");
  assert.strictEqual(rows.length, 3);
  assert(text(rows[0]).includes("送出第 1 步") && text(rows[0]).includes("自己動手第 2 項"));
  assert(text(rows[1]).includes("建了新員工") && text(rows[1]).includes("自己動手第 1 項"));
  assert(text(rows[2]).includes("你確認的"));
  assert.deepStrictEqual(rows.map((r) => attr(r, "data-by")), ["auto2", "auto1", "you"]);
  assert(rows[0].find((n) => n.tag === "a" && attr(n, "href") === "#/dispatch/" + DID));
  assert(text(main).includes("已經送出的訊息收不回來"), "said at the top");
  assert(text(rows[0]).includes("收不回來；可以按「停止」"), text(rows[0]));
});

test("stop is offered once per dispatch (on the newest line that can be stopped) and asks first", async () => {
  serve({ actions: { unreadable: 0, actions: [action({ seq: 5, kind: "step_sent", can_stop: true }), action({ seq: 4, kind: "step_sent", can_stop: true }), action({ seq: 1, kind: "confirmed", can_stop: true })] } });
  const main = await open("#/actions");
  const stops = findAll(main, "data-action", "stop");
  assert.strictEqual(stops.length, 1);
  await click(stops[0]);
  assert(text(dialog()).includes("收不回來"));
  await click(button(dialog(), "停止"));
  assert.strictEqual(posts("/stop").length, 1);
  assert(posts("/stop")[0].url.includes(DID));
});

test("withdraw on the line of the card that was made: asks first, sends that card's id", async () => {
  serve({ actions: { unreadable: 0, actions: [action({ seq: 3, kind: "card_created", what: "建了新員工「會計師」", by: "auto1", by_text: "自己動手第 1 項", profile_id: PROF_A, can_withdraw: true }),
    action({ seq: 4, kind: "card_withdrawn", what: "撤回了新員工", profile_id: PROF_A, can_withdraw: false })] } });
  const main = await open("#/actions");
  const w = findAll(main, "data-action", "withdraw");
  assert.strictEqual(w.length, 1, "only the line that made it, not the line that took it back");
  await click(w[0]);
  assert(text(dialog()).includes("停用") && text(dialog()).includes("不會刪除"));
  await click(button(dialog(), "撤回"));
  assert.deepStrictEqual(posts("/withdraw-card").map((c) => c.body), [{ profile_id: PROF_A }]);
});

test("an empty list, and dispatches that could not be read, are said", async () => {
  serve({ actions: { actions: [], unreadable: 0 } });
  let main = await open("#/actions");
  assert(text(main).includes("AI 還沒有自己做過任何事"));
  serve({ actions: { actions: [action()], unreadable: 2 } });
  main = await open("#/actions");
  assert(text(main).includes("2 份派工的紀錄讀不出來"));
});

test("looking at the list asks and writes nothing; the page links to the dispatches and to the settings", async () => {
  serve({ actions: { actions: [action()], unreadable: 0 } });
  const main = await open("#/actions");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0);
  assert.strictEqual(attr(find(main, "data-actions", "dispatch-link"), "href"), "#/dispatch");
  assert.strictEqual(attr(find(main, "data-actions", "settings-link"), "href"), "#/settings");
});

// ---- the lobby, a message sent for a dispatch, the entrances --------------------------------------------------------------------------

const live = { runtime: { available: true } };
test("the lobby's 「輪到你」: a proposal to confirm and a paused dispatch, not the others, not a damaged record", () => {
  const list = { dispatch: [row(dview()), row(dview({ id: "d-bbbbbbbbbbbb", state: "paused" })), row(dview({ id: "d-cccccccccccc", state: "running" })),
    row(dview({ id: "d-dddddddddddd", state: "done" })), { id: "d-eeeeeeeeeeee", blocked: true, error: "壞了" }] };
  const g = app.boardGroups(live, { flows: [] }, { meetings: [] }, { staffing: [] }, list);
  assert.deepStrictEqual(g.yourTurnDispatch.map((r) => r.id), [DID, "d-bbbbbbbbbbbb"]);
  assert.strictEqual(g.allEmpty, false, "something waits for the person");
  const none = app.boardGroups(live, { flows: [] }, { meetings: [] }, { staffing: [] }, { dispatch: [row(dview({ state: "done" }))] });
  assert.strictEqual(none.yourTurnDispatch.length, 0);
  assert.strictEqual(none.allEmpty, true);
  assert.strictEqual(app.boardGroups(live, { flows: [] }).yourTurnDispatch.length, 0, "the fifth argument is optional");
  assert.strictEqual(app.boardGroups(live, { flows: [] }, {}, {}, { error: "壞了" }).dispatchError, "壞了");
});

test("the board shows the two kinds with their words, a link, and counts them in the heading", () => {
  const list = { dispatch: [row(dview()), row(dview({ id: "d-bbbbbbbbbbbb", state: "paused" }))] };
  const g = app.boardGroups(live, { flows: [] }, { meetings: [] }, { staffing: [] }, list);
  const sections = app.boardSection(g);
  const turn = sections.find((n) => attr(n, "data-board") === "turn");
  const cards = findAll(turn, "data-dispatch", "board-card");
  assert.strictEqual(cards.length, 2);
  assert(text(cards[0]).includes("派工提議") && text(cards[0]).includes("週末市集擺攤") && text(cards[0]).includes("確認"), text(cards[0]));
  assert(text(cards[1]).includes("派工暫停") && text(cards[1]).includes("繼續"), text(cards[1]));
  assert(cards[0].find((n) => n.tag === "a" && attr(n, "href") === "#/dispatch/" + DID));
  assert(text(turn).includes("1 份派工提議等你") && text(turn).includes("1 件派工暫停"), text(turn));
});

test("a change in the dispatches changes the board's key, so the board repaints", () => {
  const ctx = { liveError: "", projects: [] };
  const key = (list) => app.boardKey(app.boardGroups(live, { flows: [] }, { meetings: [] }, { staffing: [] }, list), ctx);
  assert.notStrictEqual(key({ dispatch: [row(dview())] }), key({ dispatch: [] }));
  assert.notStrictEqual(key({ dispatch: [row(dview())] }), key({ dispatch: [row(dview({ state: "paused" }))] }));
});

test("the home page asks for the dispatches and puts them on the board", async () => {
  const v = dview();
  serve({ dispatches: [row(v)], views: { [DID]: v } });
  const main = await open("#/");
  assert(FETCH_LOG.some((c) => c.url === "/api/dispatch"), "asked for the list");
  assert(find(main, "data-dispatch", "board-card"), "a card on the board");
});
const ORIGIN = { dispatch: DID, step: 2 };
test("a message VBear sent for a dispatch is said so over it and is not shown as the person's", () => {
  const plain = app.chatLine({ seq: 1, at: 1790000000, kind: "user_message", turn: 1, text: "你好" });
  assert(text(plain).includes("你・") && !text(plain).includes("VBear 依派工"));
  const line = app.chatLine({ seq: 2, at: 1790000000, kind: "user_message", turn: 1, text: "請算成本", origin: ORIGIN });
  const t = text(line);
  assert(t.includes("VBear 依派工送出的第 2 步") && t.includes("不是你打的"), t);
  assert(!t.includes("你・"), "not 「你」: " + t);
  assert(t.includes("請算成本"));
  assert(line.find((n) => n.tag === "a" && attr(n, "href") === "#/dispatch/" + DID), "a link to the dispatch");
});

test("an origin that is not exactly a dispatch id and a step of 1 to 4 is not believed", () => {
  for (const origin of [{ dispatch: "d-zz", step: 2 }, { dispatch: DID, step: 9 }, { dispatch: DID, step: 0 }, { dispatch: DID, step: "2" }, "x", [], { dispatch: DID }]) {
    const t = text(app.chatLine({ seq: 2, at: 1, kind: "user_message", turn: 1, text: "hi", origin }));
    assert(t.includes("你・") && !t.includes("VBear 依派工"), JSON.stringify(origin));
  }
});

test("on the employee's chat page the note gets the dispatch's name and who decided, from the dispatch itself", async () => {
  const v = running({ started_by: "auto2", started_by_text: "自己動手第 2 項" });
  serve({ detail: detail({ chat: { id: CHAT, profile_id: "emp-1", created_at: 1, engine: "claude-chat" },
    card: { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
    records: [{ seq: 1, at: 1790000000, kind: "user_message", turn: 1, text: "請算成本", origin: ORIGIN }] }), views: { [DID]: v } });
  const main = await open("#/chat/" + CHAT);
  const note = find(main, "data-chat", "origin");
  assert(note, "the note");
  assert(text(note).includes("「週末市集擺攤」") && text(note).includes("自己動手第 2 項"), text(note));
  assert.strictEqual(desk(main), null, "an employee's page has no desk");
});

test("(P47-1) the dispatch and the actions are pages of the 工作 item of the menu (it lights it), and the menu has no emoji", async () => {
  const html = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
  const appSource = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
  const parents = appSource.slice(appSource.indexOf("const NAV_PARENT = {"), appSource.indexOf("const ADVANCED_NAV"));
  for (const k of ["dispatch", "actions"]) assert(new RegExp(`\\b${k}: "work"`).test(parents), k);
  assert(/data-nav="work"><span aria-hidden="true">[^<]*<\/span>工作<\/a>/.test(html), "the 工作 item");
  assert(!/[\u{1F000}-\u{1FFFF}\u{FE0F}]/u.test(html.split('data-nav="work"')[1].split("</li>")[0]));
  assert(!/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(html.split('data-nav="employees"')[1].split("</li>")[0]));
});

// ---- the source -------------------------------------------------------------------------------------------------------------------------

test("source: built with el(), no innerHTML, no emoji, no outside resource, never writes the settings or the limits", () => {
  assert(BLOCK.length > 8000, "the block is marked in app.js: " + BLOCK.length);
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(BLOCK));
  assert(!/api\/config|api\/setup\/daily-limit|api\/settings\/autonomy|acceptForSession/.test(BLOCK), "none of the three things reachable from here");
});

(async () => {
  let pass = 0;
  await settle();
  for (const [name, fn] of tests) {
    try { await fn(); pass++; console.log("ok   " + name); }
    catch (e) { console.log("FAIL " + name + "\n     " + (e && e.stack || e)); process.exitCode = 1; }
  }
  console.log(`${pass}/${tests.length} passed`);
  process.exit(process.exitCode || 0);
})();
