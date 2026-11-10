// Memory suggestions on the page (v0.17 P42-4): the button 「整理要記住的事」 on a one-to-one chat page, the dialog that says what is read,
// the most it costs, what is left today and where it goes, and the suggestion card (every line unticked, the words and the kind
// may be changed, a refused line cannot be ticked, a line that reads like an order needs 「我確定」, and no 「全部存」). The real
// web/app.js on a synthetic DOM and a fetch stub answered by the test; it is NOT a browser test and it runs no model and no AI
// tool. Nothing is saved except by the person's own press of 「存進記憶」, one POST /api/memory for each ticked line.
// Run: node tests/frontend/memory_suggest.cjs   (exit code 0 = pass)
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
const START = "// ---------- memory suggestions (v0.17, P42-4)";
const BLOCK = SRC.slice(SRC.indexOf(START), SRC.indexOf("// ---------- end of memory suggestions"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const by = (key, value) => (n) => attr(n, key) === value;
const find = (root, key, value) => root.find(by(key, value));
const findAll = (root, key, value) => root.findAll(by(key, value));
const button = (root, label) => root.find((n) => n.tag === "button" && text(n) === label);
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && attr(n, "data-msuggest") === "dialog");
const EVIL = "<img src=x onerror=alert(1)>";

const CHAT = "c-0123456789abcdef";
const OTHER_CHAT = "c-fedcba9876543210";
const SID = "ms-0123456789ab";
const KEY = "sk-ant-" + "api03-" + "Q".repeat(40);

// ---- fixtures: the shapes the server sends (vbear/memory_suggest_runner.py, vbear/memory_suggest.py) -------------------------------------

const detail = (over = {}) => ({ ok: true, chat: { id: CHAT, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" },
  card: { id: "emp-1", name: "虛構員工", position: "social", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const ceo = () => detail({ card: { id: "ceo-1", name: "虛構 CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null } });
const inGroup = () => detail({ group: { id: "g-0123456789ab", name: "虛構群組" } });
const preview = (over = {}) => ({ preview_id: "pv-" + "0".repeat(16), ok: true, blockers: [], chat_id: CHAT, messages: 6, omitted_messages: 0, bytes: 900,
  memory_lines: 3, cap_usd: "0.1", day_left_usd: "2.71", today: { spent_usd: "0.29", daily_usd: "3", lamp: "green" }, sends_to: "Anthropic",
  engine: "claude-chat", notice: null, save_note: "整理只是提議：每一條都不會自己存，你勾選、可以改字，按「存進記憶」才會存。",
  cli: { version: "2.1.318", verified: true },
  disclosure: "開始後，你和這位員工最近的對話（最多 20 則、12 KiB）與你目前的記憶，會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。",
  cost_note: "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。沒有回報時，以每次上限計（最壞情況）。", ...over });
const line = (index, over = {}) => ({ index, kind: "work", text: `虛構的第${index + 1}條`, why: "以後會用到", refuse: null, refuse_text: null, warn: [], warn_text: [], saved: false, ...over });
const view = (over = {}) => ({ id: SID, created_at: 1790000100, chat_id: CHAT, engine: "claude-chat", status: "ready", state: "done", error_code: null, attempts: 1,
  spent_usd: "0.02", cost_source: "cli", limits: { per_call_usd: "0.1", total_usd: "0.1" }, read: { count: 6 }, memory_sent: 3, sends_to: "Anthropic",
  items: [line(0), line(1, { kind: "about_you" }), line(2, { kind: "decision" })], saved: [], dismissed: false, outcome: "ready", ...over });
const row = (v, over = {}) => ({ id: v.id, created_at: v.created_at, chat_id: v.chat_id, status: v.status, spent_usd: v.spent_usd, saved: v.saved.length,
  dismissed: v.dismissed, ...over });

let S;        // what the stub serves
function serve(over = {}) {
  S = { verifyFail: null, detail: detail(), list: [], views: {}, preview: preview(), previewFail: null, startFail: null, post: {}, memory: null, saved: [], ...over };
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
    if (p === "/api/chats" && method === "GET") return jsonResponse({ ok: true, chats: [], more: 0, cards: [], support: {}, limits: { per_turn_usd: "0.5", daily_usd: "3" },
      ledger: { spent_usd: "0.1", daily_usd: "3", lamp: "green" }, problems: [] });
    if (/^\/api\/chats\/c-[0-9a-f]{16}\/stream$/.test(p)) return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (/^\/api\/chats\/c-[0-9a-f]{16}$/.test(p) && method === "GET") return jsonResponse(S.detail);
    if (p === "/api/meetings/ledger") return jsonResponse({ ok: true, spent_usd: "0.29", daily_usd: "3", lamp: "green", blocked: false });
    if (p === "/api/chief" && method === "GET") return jsonResponse({ chief: [] });
    if (p === "/api/dispatch" && method === "GET") return jsonResponse({ dispatch: [] });
    if (p === "/api/memory/suggest/preview" && method === "POST") return S.previewFail ? jsonResponse({ error: S.previewFail, code: "not_found" }, false, 404) : jsonResponse(S.preview);
    if (p === "/api/memory/suggest" && method === "GET") return jsonResponse({ suggestions: S.list });
    if (p === "/api/memory/suggest" && method === "POST") return S.startFail ? jsonResponse(S.startFail, false, 409) : jsonResponse({ id: SID, suggestion: view({ status: "running", state: "running", items: [], outcome: "pending" }) }, true, 202);
    let m = /^\/api\/memory\/suggest\/(ms-[0-9a-f]{12})(?:\/(saved|dismiss|cancel))?$/.exec(p);
    if (m && !m[2] && method === "GET") return S.views[m[1]] ? jsonResponse(S.views[m[1]]) : jsonResponse({ error: "沒有", code: "not_found" }, false, 404);
    if (m && m[2]) {
      if (S.post[m[2]]) return S.post[m[2]](body);
      if (m[2] === "saved") { S.saved.push(...body.indexes); return jsonResponse(view({ saved: S.saved.slice().sort() })); }
      if (m[2] === "dismiss") return jsonResponse(view({ dismissed: true }));
      return jsonResponse(view({ status: "cancelled", state: "cancelled", items: [] }));
    }
    if (p === "/api/memory" && method === "POST") return S.memory ? S.memory(body) : jsonResponse({ ok: true, entry: { id: "m-0123456789", ...body } }, true, 201);
    if (p === "/api/meetings/verify" && method === "POST") return S.verifyFail ? jsonResponse({ error: S.verifyFail, code: "refused" }, false, 409) : jsonResponse({ ok: true, version: "2.1.318" });
    if (p === "/api/tasks") return jsonResponse({ tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: false });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false, onboarding_dismissed: true, setup_done: true, welcome_seen: true }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/first-ceo") return jsonResponse({ needed: false });
    if (p === "/api/meetings" || p === "/api/staffing") return jsonResponse({ meetings: [], staffing: [] });
    if (p === "/api/setup/tools") return jsonResponse({ tools: [] });
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
async function tick(n = 1) { for (let i = 0; i < n; i++) for (const fn of S.ticks) await fn(); await settle(); }
async function tickBox(node, on = true) { node.checked = on; node.dispatch("change"); await settle(); }
const desk = (main) => find(main, "data-msuggest", "desk");
const card = (main) => find(main, "data-msuggest", "card");
const items = (main) => findAll(card(main), "data-msuggest", "item");
const part = (item, name) => find(item, "data-msuggest", name);
const saveButton = (main) => find(card(main), "data-msuggest", "save");

async function started(over = {}) {
  serve(over);
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  await click(find(dialog(), "data-msuggest", "start"));
  return main;
}
async function ready(over = {}, v = view()) {
  const main = await started(over);
  S.views[SID] = v;
  await tick();
  return main;
}

// ---- the button and the dialog -------------------------------------------------------------------------------------------------

test("a one-to-one chat page has the item 「整理要記住的事」 (in the 「⋯」 menu), a CEO's or an employee's; a chat a group opened has none", async () => {
  const item = (main) => find(main, "data-msuggest", "open");           // (P47-4) the button is an item of the menu; the desk keeps only what came back
  serve();
  let main = await open("#/chat/" + CHAT);
  assert(desk(main), "a desk on an employee's page");
  assert(item(main) && text(item(main)).includes("整理要記住的事") && find(main, "data-chat-menu", "memory") === item(main));
  serve({ detail: ceo() });
  main = await open("#/chat/" + CHAT);
  assert(item(main) && text(item(main)).includes("整理要記住的事"), "and on a CEO's page");
  serve({ detail: inGroup() });
  main = await open("#/chat/" + CHAT);
  assert.strictEqual(desk(main), null, "none in a group's chat");
  assert.strictEqual(item(main), null);
});

test("the menu item says what it does and that nothing is saved by itself, and pressing it asks nothing of the model", async () => {
  serve();
  const main = await open("#/chat/" + CHAT);
  const words = text(find(main, "data-msuggest", "open"));       // (P47-4) the sentence that stood on the desk stands under the item
  for (const w of ["最近的對話", "US$0.10", "Anthropic", "勾選", "存進記憶"]) assert(words.includes(w), w);
  assert.strictEqual(posts("/api/memory/suggest").length, 0);
  await click(find(main, "data-msuggest", "open"));
  assert.strictEqual(posts("/api/memory/suggest/preview").length, 1);
  assert.deepStrictEqual(posts("/api/memory/suggest/preview")[0].body, { chat_id: CHAT });
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === "/api/memory/suggest").length, 0, "no call before 開始整理");
  assert.strictEqual(posts("/api/memory").length, 0);
});

test("the dialog says what is read, the most it costs, what is left today and where it goes", async () => {
  serve();
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  const d = dialog();
  assert(d, "a dialog");
  const words = text(d);
  assert(words.includes("6 則"), "how many messages");
  assert(words.includes("最多花 US$0.10，今天還剩 US$2.71"), words);
  assert(words.includes("這段對話會送給 Anthropic"), words);
  assert(words.includes("3 條"), "how many lines of memory go along");
  assert(words.includes("不會自己存"), "the save note");
  assert(words.includes("金額是 Claude Code 回報的估值"));
  assert(find(d, "data-msuggest", "start"), "a start button");
  assert(button(d, "取消"));
});

test("a chat with a Codex employee is told it goes to Anthropic too", async () => {
  serve({ preview: preview({ engine: "codex-chat", notice: "這是和 Codex 員工的對話，也會送給 Anthropic（Claude Code）整理。" }) });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  assert(text(dialog()).includes("這是和 Codex 員工的對話，也會送給 Anthropic"));
});

test("no Claude Code: it says the feature needs it, links to the setup and has no start button", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [{ code: "cli_not_found", message: "這個功能目前需要 Claude Code，請到「開始設定」安裝並登入" }] }) });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  const d = dialog();
  assert(text(d).includes("這個功能目前需要 Claude Code"));
  assert(find(d, "data-msuggest", "needs-claude"));
  assert.strictEqual(find(d, "data-msuggest", "start"), null);
});

const modal = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));        // any dialog, also the page's own question
const UNVERIFIED = { code: "boundary_unverified", message: "這個 Claude Code 版本還沒通過無工具安全檢查，請先檢查" };

test("a Claude Code that has not passed the tool-less check: a check button (the chief of staff's and the meetings'), said what it costs, then the preview again", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [UNVERIFIED] }) });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  const verify = find(dialog(), "data-msuggest", "verify");
  assert(verify, "a check button, not only the words 「請先檢查」");
  assert(text(verify).includes("不到 1 美分"), text(verify));
  assert.strictEqual(find(dialog(), "data-msuggest", "start"), null, "nothing to start before the check");
  S.preview = preview();                           // after the check the preview is fine
  await click(verify);
  const confirm = modal();
  assert(text(confirm).includes("無工具安全檢查") && text(confirm).includes("Claude") && text(confirm).includes("幕僚長和會議用同一個檢查"), text(confirm));
  assert.strictEqual(posts("/api/meetings/verify").length, 0, "asked first");
  await click(button(confirm, "檢查"));
  assert.strictEqual(posts("/api/meetings/verify").length, 1);
  assert.deepStrictEqual(FETCH_LOG.find((c) => c.url.split("?")[0] === "/api/meetings/verify").body, {});
  assert(text(h.dom().toastEl).includes("通過無工具安全檢查"), text(h.dom().toastEl));
  assert(find(dialog(), "data-msuggest", "start"), "the preview was asked again and can start now");
  assert.strictEqual(find(dialog(), "data-msuggest", "verify"), null);
  assert.strictEqual(posts("/api/memory/suggest").length, 0, "the check does not start the suggestion");
});

test("the check asks first: cancelling sends nothing; a check that fails is said and the preview is not asked again", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [UNVERIFIED] }) });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  await click(find(dialog(), "data-msuggest", "verify"));
  await click(button(modal(), "取消"));
  assert.strictEqual(posts("/api/meetings/verify").length, 0);
  S.verifyFail = "Claude Code 沒有通過檢查";
  await click(find(main, "data-msuggest", "open"));
  await click(find(dialog(), "data-msuggest", "verify"));
  const asked = posts("/api/memory/suggest/preview").length;
  await click(button(modal(), "檢查"));
  assert.strictEqual(posts("/api/meetings/verify").length, 1);
  assert(text(h.dom().toastEl).includes("檢查失敗") && text(h.dom().toastEl).includes("沒有通過檢查"), text(h.dom().toastEl));
  assert.strictEqual(posts("/api/memory/suggest/preview").length, asked, "no new preview after a check that failed");
});

test("another blocker has no check button", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, blockers: [{ code: "budget", message: "額度不夠" }] }) });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  assert.strictEqual(find(dialog(), "data-msuggest", "verify"), null);
});

test("a red light: the reason is shown and there is nothing to press", async () => {
  serve({ preview: preview({ ok: false, preview_id: null, today: { spent_usd: "3", daily_usd: "3", lamp: "red" }, day_left_usd: "0", cap_usd: "0",
    blockers: [{ code: "budget", message: "今天已花 3 美元，加上預留 0.01 會超過每日上限 3" }] }) });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  const d = dialog();
  assert(text(d).includes("超過每日上限"));
  assert.strictEqual(find(d, "data-msuggest", "start"), null);
});

test("a preview that cannot be had says why and opens no dialog", async () => {
  serve({ previewFail: "找不到這個聊天" });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  assert.strictEqual(dialog(), null);
  assert(text(h.dom().toastEl).includes("找不到這個聊天"));
});

// ---- the run ------------------------------------------------------------------------------------------------------------------------

test("start sends only the preview id; the desk then says VBear is working, with a way to stop", async () => {
  const main = await started();
  const call = FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === "/api/memory/suggest");
  assert.deepStrictEqual(call.map((c) => c.body), [{ preview_id: "pv-" + "0".repeat(16) }]);
  assert.strictEqual(dialog(), null, "the dialog closed");
  const run = find(main, "data-msuggest", "run");
  assert(run && text(run).includes("正在整理"), text(desk(main)));
  S.views[SID] = view({ status: "running", state: "running", items: [], outcome: "pending" });
  await click(find(run, "data-msuggest", "cancel"));
  assert.strictEqual(posts(`/api/memory/suggest/${SID}/cancel`).length, 1);
});

test("a start the server refuses is said and nothing is shown as running", async () => {
  serve({ startFail: { error: "預覽之後對話或記憶變了，請重新預覽", code: "stale_preview" } });
  const main = await open("#/chat/" + CHAT);
  await click(find(main, "data-msuggest", "open"));
  await click(find(dialog(), "data-msuggest", "start"));
  assert(text(h.dom().toastEl).includes("預覽之後對話或記憶變了"));
  assert.strictEqual(find(main, "data-msuggest", "run"), null);
});

test("a call that did not succeed is said in words, with its code, and there is no card", async () => {
  const main = await ready({}, view({ status: "failed", state: "failed", error_code: "invalid_output", items: [], outcome: "pending" }));
  assert.strictEqual(card(main), null);
  const run = find(main, "data-msuggest", "run");
  assert(text(run).includes("沒有成功") && text(run).includes("invalid_output"), text(run));
  assert(!text(run).includes("undefined"));
});

// ---- the card -----------------------------------------------------------------------------------------------------------------------

test("every line starts unticked, there is a tick for each and no 「全部存」 or 「全選」, and the save button waits for a tick", async () => {
  const main = await ready();
  assert(card(main), "a card");
  const rows = items(main);
  assert.strictEqual(rows.length, 3);
  for (const r of rows) {
    const box = part(r, "check");
    assert(box && box.tag === "input" && attr(box, "type") === "checkbox");
    assert(!box.checked, "not ticked at first");
    assert(!box.disabled);
  }
  assert.deepStrictEqual(rows.map((r) => part(r, "text").value), ["虛構的第1條", "虛構的第2條", "虛構的第3條"]);
  assert.deepStrictEqual(rows.map((r) => part(r, "kind").value), ["work", "about_you", "decision"]);
  assert(text(rows[0]).includes("以後會用到"));
  assert(saveButton(main).disabled, "nothing ticked: nothing to save");
  const all = text(card(main));
  for (const w of ["全部存", "全選", "全部勾", "一次存"]) assert(!all.includes(w), w);
  assert.strictEqual(posts("/api/memory").length, 0, "nothing saved by itself");
  assert.strictEqual(card(main) && findAll(card(main), "data-msuggest", "check-all").length, 0);
});

test("ticking two and pressing 「存進記憶」 posts each line once, with its own words and kind, then writes down which were saved", async () => {
  const main = await ready();
  const rows = items(main);
  await type(part(rows[1], "text"), "回答一律用繁體中文");
  await pick(part(rows[1], "kind"), "decision");
  await tickBox(part(rows[0], "check"));
  await tickBox(part(rows[1], "check"));
  assert(!saveButton(main).disabled);
  await click(saveButton(main));
  const memory = posts("/api/memory");
  assert.deepStrictEqual(memory.map((c) => c.body), [
    { kind: "work", text: "虛構的第1條", source: { how: "suggested", suggestion_id: SID } },
    { kind: "decision", text: "回答一律用繁體中文", source: { how: "suggested", suggestion_id: SID } }]);
  assert.deepStrictEqual(posts(`/api/memory/suggest/${SID}/saved`).map((c) => c.body), [{ indexes: [0, 1] }]);
  assert.strictEqual(posts("/api/memory").length, 2, "the third line was not ticked and was not sent");
  const after = items(main);
  assert(text(after[0]).includes("已存") && text(after[1]).includes("已存"));
  assert(part(after[0], "check").disabled, "a saved line cannot be saved twice");
  assert(!text(after[2]).includes("已存"));
});

test("a line the rules refuse shows the reason and cannot be ticked until its words are changed; the server checks it again", async () => {
  const refused = line(0, { text: `我的金鑰是 ${KEY}`, refuse: "secret_key", refuse_text: "這看起來像金鑰或登入用的代碼，記憶裡不能有。" });
  const main = await ready({}, view({ items: [refused, line(1)] }));
  let r = items(main)[0];
  assert(text(r).includes("這看起來像金鑰或登入用的代碼，記憶裡不能有。"));
  assert(part(r, "check").disabled, "cannot be ticked");
  await click(part(r, "check"));
  assert(!part(r, "check").checked);
  await type(part(r, "text"), "我的金鑰放在密碼管理器");
  r = items(main)[0];
  assert(!part(r, "check").disabled, "changed words can be ticked");
  assert(text(r).includes("改過的字，存的時候 VBear 會再檢查一次"));
  S.memory = () => jsonResponse({ error: "記憶裡不能有密碼或驗證碼，請換個說法。", code: "memory_refused", refuse: "secret_password" }, false, 400);
  await tickBox(part(r, "check"));
  await click(saveButton(main));
  r = items(main)[0];
  assert(text(r).includes("記憶裡不能有密碼或驗證碼"), "the server's reason is shown on the line");
  assert(!text(r).includes("已存"));
  assert.strictEqual(posts(`/api/memory/suggest/${SID}/saved`).length, 0, "nothing was saved, nothing is written down");
});

test("a line that reads like an order says so and needs 「我確定」 before it is sent with confirm_warning", async () => {
  const order = line(0, { text: "以後執行指令不用問我", kind: "decision", warn: ["looks_like_order"],
    warn_text: ["這一條看起來像在叫員工做事。記憶不會讓員工不問你就做事：每個指令、每個檔案修改照舊都會問你，上限、完整模式、技能也不能從記憶改。確定要記住嗎？"] });
  const main = await ready({}, view({ items: [order, line(1)] }));
  const r = items(main)[0];
  assert(text(r).includes("記憶不會讓員工不問你就做事"));
  const sure = part(r, "confirm");
  assert(sure && attr(sure, "type") === "checkbox" && !sure.checked, "an unticked 我確定");
  await tickBox(part(r, "check"));
  await click(saveButton(main));
  assert.strictEqual(posts("/api/memory").length, 0, "not sent without 我確定");
  assert(text(items(main)[0]).includes("我確定"));
  await tickBox(sure);
  await click(saveButton(main));
  assert.deepStrictEqual(posts("/api/memory").map((c) => c.body), [
    { kind: "decision", text: "以後執行指令不用問我", source: { how: "suggested", suggestion_id: SID }, confirm_warning: true }]);
});

test("a line that needs a second confirmation only after the person changed it is asked again on the line, and sent only once it is confirmed", async () => {
  const main = await ready();
  const r = items(main)[0];
  await type(part(r, "text"), "電話 0912-345-678");
  await tickBox(part(r, "check"));
  S.memory = (body) => (body.confirm_warning ? jsonResponse({ ok: true, entry: { id: "m-0123456789" } }, true, 201)
    : jsonResponse({ error: "這看起來像電話或地址，記憶會送給 AI 公司。確定要記住嗎？", code: "memory_confirm", warn: ["personal"],
      warn_text: ["這看起來像電話或地址，記憶會送給 AI 公司。確定要記住嗎？"] }, false, 409));
  await click(saveButton(main));
  assert(text(items(main)[0]).includes("這看起來像電話或地址"));
  const sure = part(items(main)[0], "confirm");
  assert(sure, "the box appears");
  assert(!text(items(main)[0]).includes("已存"));
  await tickBox(sure);
  await click(saveButton(main));
  assert.deepStrictEqual(posts("/api/memory").map((c) => Boolean(c.body.confirm_warning)), [false, true]);
  assert(text(items(main)[0]).includes("已存"));
});

test("when one line fails and another is saved, only the saved one is written down", async () => {
  const main = await ready();
  const rows = items(main);
  S.memory = (body) => (body.text === "虛構的第2條" ? jsonResponse({ error: "記憶滿了（50 條或 4,000 字），請先刪掉幾條。", code: "memory_full" }, false, 409)
    : jsonResponse({ ok: true, entry: { id: "m-0123456789" } }, true, 201));
  await tickBox(part(rows[0], "check"));
  await tickBox(part(rows[1], "check"));
  await click(saveButton(main));
  assert.deepStrictEqual(posts(`/api/memory/suggest/${SID}/saved`).map((c) => c.body), [{ indexes: [0] }]);
  const after = items(main);
  assert(text(after[0]).includes("已存"));
  assert(text(after[1]).includes("記憶滿了"));
  assert(!part(after[1], "check").disabled, "the failed line can be tried again");
});

test("「不用了」 drops the suggestion and the card goes", async () => {
  const main = await ready();
  await click(find(card(main), "data-msuggest", "dismiss"));
  assert.strictEqual(posts(`/api/memory/suggest/${SID}/dismiss`).length, 1);
  assert.strictEqual(card(main), null);
  assert.strictEqual(posts("/api/memory").length, 0);
});

test("an answer with nothing worth remembering says so", async () => {
  const main = await ready({}, view({ items: [] }));
  assert(card(main));
  assert(text(card(main)).includes("沒有值得記住的事"), text(card(main)));
  assert.strictEqual(items(main).length, 0);
  assert.strictEqual(saveButton(main), null);
  await click(find(card(main), "data-msuggest", "dismiss"));
  assert.strictEqual(card(main), null);
});

test("what a model wrote is set as text, never as markup", async () => {
  const main = await ready({}, view({ items: [line(0, { text: EVIL, why: EVIL })] }));
  const r = items(main)[0];
  assert.strictEqual(part(r, "text").value, EVIL);
  assert(text(r).includes(EVIL), "the reason is shown as text");
  assert.strictEqual(r.find((n) => n.tag === "img"), null);
});

// ---- coming back to the page ----------------------------------------------------------------------------------------------------------

test("a page opened while a suggestion is running or waiting shows it; a dropped one, an all-saved one and another chat's do not", async () => {
  const waiting = view();
  serve({ list: [row(waiting)], views: { [SID]: waiting } });
  let main = await open("#/chat/" + CHAT);
  assert(card(main), "a waiting suggestion is shown again");
  assert.strictEqual(items(main).length, 3);
  serve({ list: [row(view({ dismissed: true }))], views: { [SID]: view({ dismissed: true }) } });
  main = await open("#/chat/" + CHAT);
  assert.strictEqual(card(main), null);
  const done = view({ saved: [0, 1, 2], items: [line(0, { saved: true }), line(1, { saved: true }), line(2, { saved: true })] });
  serve({ list: [row(done)], views: { [SID]: done } });
  main = await open("#/chat/" + CHAT);
  assert.strictEqual(card(main), null, "everything saved: nothing to show");
  serve({ list: [row(view({ chat_id: OTHER_CHAT }))], views: { [SID]: view({ chat_id: OTHER_CHAT }) } });
  main = await open("#/chat/" + CHAT);
  assert.strictEqual(card(main), null);
  const running = view({ status: "running", state: "running", items: [], outcome: "pending" });
  serve({ list: [row(running)], views: { [SID]: running } });
  main = await open("#/chat/" + CHAT);
  assert(find(main, "data-msuggest", "run"), "a running one is shown");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "just looking asks for and saves nothing");
});

// ---- the words in the page's source -------------------------------------------------------------------------------------------------------

test("the code sets text only: no innerHTML, no emoji, no outside resource, no autosave, and it never writes a setting or answers a card", async () => {
  assert(BLOCK.length > 2000, "the block is there");
  assert(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(BLOCK));
  assert(!/\p{Extended_Pictographic}/u.test(BLOCK), "no emoji");
  assert(!/https?:\/\//.test(BLOCK), "no outside address");
  assert(!/\/api\/config|\/api\/settings|\/api\/setup\/daily-limit|\/answer|\/api\/native|\/api\/agent-profiles|\/api\/memory\/(cards|clear)/.test(BLOCK));
  assert(!/全部存|全選/.test(BLOCK.replace(/assert.*\n/g, "")), "no 「全部存」 in the code");
  assert(/checked\s*=\s*false|checked: false|!box\.checked|\.checked/.test(BLOCK));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed++; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  if (failed) { console.log(`${failed} of ${tests.length} failed`); process.exit(1); }
  console.log(`${tests.length} tests passed`);
  process.exit(0);
})();
