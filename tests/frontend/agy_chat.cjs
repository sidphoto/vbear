// P46-5 (ADR 0012): the pages that take an AGY employee in. The chat page (the notice per state, the cards of an AGY chat: a command, a file
// change, a read outside the work folder, the words of "改內容再問", the estimated cost), the pages of memory and the shared folder (off, and
// a yes to Google before they open), the group dialog, the chief of staff's and dispatch's sentences, the team templates, the first CEO,
// the start-up page's line and the role card pool. The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test.
// Nothing here runs a model or an AI tool: the server answers with made-up fixtures, and every string a model or a card could hold is tried
// with markup in it.
// Run: node tests/frontend/agy_chat.cjs   (exit code 0 = pass)
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
const attr = (key) => (n) => n.getAttribute && n.getAttribute(key) !== null;
const q = (n, key, name = "data-chat") => n.find((x) => x.getAttribute && x.getAttribute(name) === key);
const qa = (n, key, name = "data-chat") => n.findAll((x) => x.getAttribute && x.getAttribute(name) === key);
const EVIL = "<img src=x onerror=alert(1)>";
const noMarkup = (node) => assert.strictEqual(node.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");
const AGY_CID = "c-aaaaaaaaaaaaaaaa";
const CARD_ID = "k-" + "a".repeat(16);

// ---- fixtures: a made-up AGY employee, a made-up AGY that is installed -------------------------------------------------

let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const card = (over = {}) => ({ card_id: CARD_ID, token: "t".repeat(32), turn: 1, expires_in: 290, reason: "AGY 要執行指令", ...over });
const agyCommand = (over = {}) => card({ tool: "command", editable: "command", input: { command: "ls -a", cwd: "." }, ...over });
const agyFile = (over = {}) => card({ tool: "file_change", editable: "content", reason: "AGY 要改檔案",
  input: { changes: [{ path: "post.md", kind: "add", diff: "hello from agy\n" }, { path: "old.md", kind: "update", diff: "-a\n+b\n" }] }, ...over });
const agyRead = (over = {}) => card({ tool: "read", editable: null, reason: "AGY 要讀工作資料夾以外的檔案", input: { paths: ["/tmp/outside-note.txt", "/tmp/second.txt"] }, ...over });
const AGY_MONEY = "聊天用你自己的 Google 方案（AGY），不另外收費。AGY 不回報金額，VBear 依 token 數估算（每 100 萬 token 計 US$1，至少 US$0.01）後算進每天上限；這是 VBear 的記帳規則，不是帳單。";
const agySupport = (over = {}) => ({ engine: "agy-chat", state: "ready", installed: true, version: "1.5.3", verified: true, shared_verified: false,
  admin_policy_ok: true, hooks_ok: true, why: "", verified_versions: ["1.5.3"], verify: { running: false }, money: AGY_MONEY, ...over });
const support = (over = {}) => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" },
  verify: { running: false }, money: "x", ...over });
const cardsList = () => [
  { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
  { id: "emp-5", name: "AGY 員工", position: "pm", tool: "agy", engine: "agy-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
];
const listing = (over = {}) => ({ ok: true, chats: [], more: 0, cards: cardsList(), support: support({ agy: agySupport() }), limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["meetings", "staffing", "chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const agyDetail = (over = {}) => ({ ok: true, chat: { id: AGY_CID, profile_id: "emp-5", created_at: 1790000000, engine: "agy-chat" },
  card: { id: "emp-5", name: "AGY 員工", position: "pm", tool: "agy", engine: "agy-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const live = (over = {}) => ({ state: "idle", turn: null, partial: "", partial_truncated: false, model: "gemini-3.8-flash-high", cards: [], ...over });

let page;
const streams = [];
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), detail: agyDetail(), verifyStatus: 202, ...over };
  streams.length = 0;
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/groups") return jsonResponse({ ok: true, groups: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/chats" && method === "POST") return jsonResponse({ ok: true, chat: { id: AGY_CID, profile_id: "emp-5", created_at: 1 } }, true, 201);
    if (p === "/api/chat-support/verify") return jsonResponse(page.verifyBody || { ok: true, status: { running: true } }, page.verifyStatus < 400, page.verifyStatus);
    if (p === "/api/memory/cards" && method === "POST") return jsonResponse({ ok: true });
    if (p === "/api/shared/cards" && method === "POST") return jsonResponse({ ok: true });
    if (p === "/api/setup/tools") return jsonResponse(page.setup || { tools: [] });
    if (p === "/api/memory") return jsonResponse(page.memory || { ok: true, entries: [], used: { count: 0, chars: 0, max_count: 50, max_chars: 4000 }, readable: true, where_text: "", cards: [] });
    if (p === "/api/shared") return jsonResponse(page.shared || { ok: true });
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (m && !m[2] && method === "GET") return jsonResponse(page.detail);
    if (m && !m[2] && method === "DELETE") return jsonResponse({ ok: true, deleted: m[1] });
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
const posts = (suffix) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0].endsWith(suffix));
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const opts = (over = {}) => ({ edit: { open: false }, onAnswer() {}, redraw() {}, engine: "agy-chat", ...over });

// ---- the cards of an AGY chat --------------------------------------------------------------------------------------------

test("a command card of an AGY chat says it runs in AGY's sandbox, not the Codex sentence, and has the three honest buttons", () => {
  const calls = [];
  const node = app.chatCardNode(agyCommand(), opts({ onAnswer: (c, d, v) => calls.push([d, v]) }));
  const all = text(node);
  for (const w of ["員工想執行指令", "ls -a", "員工的工作資料夾"]) assert(all.includes(w), w);
  const warn = text(q(node, "sandbox-warning"));
  for (const w of ["AGY 的沙盒", "不能連網", "只能寫工作資料夾", "暫存資料夾", "看得懂"]) assert(warn.includes(w), w);
  assert(!all.includes("可能在沙盒外執行"), "the Codex warning is not on an AGY card");
  assert(!/Bash|Edit|read/.test(all.replace(/ls -a/g, "")), "the words of the tools are not shown: " + all);
  assert(q(node, "allow") && q(node, "deny") && q(node, "modify"));
  assert.strictEqual(text(q(node, "modify")), "改內容再問");
  q(node, "allow").click();
  assert.deepStrictEqual(calls, [["allow", null]]);
});

test("the Codex command card keeps its own warning", () => {
  const node = app.chatCardNode(agyCommand({ input: { command: "ls", cwd: ".", actions: [] } }), { edit: { open: false }, onAnswer() {}, redraw() {}, engine: "codex-chat" });
  assert(text(q(node, "sandbox-warning")).includes("可能在沙盒外執行"));
});

test("asking again with an AGY card says the change goes in as the next message and AGY asks again", () => {
  const calls = [];
  const edit = { open: true, text: "echo hi" };
  const node = app.chatCardNode(agyCommand(), opts({ edit, onAnswer: (c, d, v) => calls.push([d, v]) }));
  const again = text(q(node, "ask-again"));
  for (const w of ["先拒絕原本的", "這一回合結束", "下一則訊息", "AGY 會再問你一次"]) assert(again.includes(w), w);
  assert(!again.includes("Codex"));
  assert.strictEqual(text(q(node, "allow-edited")), "拒絕原本的，照這樣再問我");
  q(node, "allow-edited").click();
  assert.deepStrictEqual(calls, [["modify", "echo hi"]]);
});

test("a file card of an AGY chat shows the path, what is done and the diff as text, and can be changed", () => {
  const node = app.chatCardNode(agyFile(), opts());
  const all = text(node);
  for (const w of ["員工想修改檔案", "post.md", "新增", "hello from agy", "old.md", "修改", "-a", "+b"]) assert(all.includes(w), w);
  assert(qa(node, "x", "data-none").length === 0);
  assert(node.findAll((n) => n.tag === "pre").some((p) => text(p).includes("hello from agy")), "a diff is a <pre> text node");
  assert(!q(node, "sandbox-warning"), "a file card is not a command");
  assert(q(node, "modify"));
  noMarkup(app.chatCardNode(agyFile({ input: { changes: [{ path: EVIL, kind: EVIL, diff: EVIL, move_to: EVIL }] } }), opts()));
});

test("a read card says what is read outside the work folder, that it goes to Google, and that there is nothing to change", () => {
  const calls = [];
  const node = app.chatCardNode(agyRead(), opts({ onAnswer: (c, d) => calls.push(d) }));
  const all = text(node);
  assert(all.includes("員工想讀取檔案"), "not the generic 工具 read: " + all);
  assert(!all.includes("工具 read"));
  for (const w of ["/tmp/outside-note.txt", "/tmp/second.txt", "工作資料夾以外", "送到 Google"]) assert(all.includes(w), w);
  const note = text(q(node, "read-note"));
  assert(note.includes("沒有可以改的內容") && note.includes("只能允許或拒絕"), note);
  assert(q(node, "allow") && q(node, "deny"));
  assert.strictEqual(q(node, "modify"), null, "no button to change what is read");
  assert.strictEqual(q(node, "sandbox-warning"), null);
  q(node, "deny").click();
  assert.deepStrictEqual(calls, ["deny"]);
  noMarkup(app.chatCardNode(agyRead({ input: { paths: [EVIL] } }), opts()));
  assert(text(app.chatCardNode(agyRead({ input: { paths: "x" } }), opts())).includes("員工想讀取檔案"), "a shape it does not know still draws");
});

test("the lines of the transcript name the tools of an AGY chat in plain words", () => {
  const t = (r, o = { engine: "agy-chat" }) => text(app.chatLine({ seq: 1, at: 1790000000, ...r }, o));
  assert(t({ kind: "card", card_id: CARD_ID, tool: "read" }).includes("員工想讀取檔案"));
  assert(t({ kind: "card", card_id: CARD_ID, tool: "other" }).includes("員工想做其他的事"));
  assert(t({ kind: "tool_call", tool: "read", summary: "/tmp/x" }).includes("讀取檔案"));
  assert(t({ kind: "tool_call", tool: "command", summary: "ls" }).includes("執行指令"));
  assert(t({ kind: "auto_allowed", tool: "read", summary: "a.md", reason: "工作資料夾內" }).includes("讀取檔案"));
  assert(!t({ kind: "auto_allowed", tool: "read", summary: "a.md", reason: "工作資料夾內" }).includes("允許了 read"));
  const denied = t({ kind: "denied", tool: "command", summary: "curl x", reason: "AGY 要在沙盒外執行指令，聊天不允許", by: "vbear" });
  assert(denied.includes("已拒絕") && denied.includes("沙盒外") && denied.includes("執行指令"));
  const modified = t({ kind: "card_decision", card_id: CARD_ID, decision: "modify", value: "echo hi" });
  assert(modified.includes("這一回合結束") && modified.includes("下一則訊息") && !modified.includes("Codex"), modified);
  assert(t({ kind: "card_decision", card_id: CARD_ID, decision: "modify", value: "echo hi" }, { engine: "codex-chat" }).includes("請 Codex 照你改的內容再問一次"));
  assert(t({ kind: "card_decision", card_id: CARD_ID, decision: "allow" }).includes("你允許了這一次"));
});

test("the cost of an AGY turn is an estimate, says it is not a bill and that it is the Google plan; a turn with no count is the cap", () => {
  const est = app.chatTurnCost({ kind: "turn_ended", cost_usd: "0.09", estimate: true, tokens: 86000, reason: "result" }, "agy-chat");
  for (const w of ["估計", "US$0.09", "86,000", "AGY 不回報金額", "不是帳單", "Google 方案"]) assert(est.includes(w), w + ": " + est);
  assert(!est.includes("Codex") && !est.includes("ChatGPT"));
  const cap = app.chatTurnCost({ kind: "turn_ended", cost_usd: "0.5", estimate: false, reason: "result" }, "agy-chat");
  assert(cap.includes("上限") && cap.includes("AGY 沒有回報用量") && !cap.includes("Codex"), cap);
  assert(app.chatTurnCost({ kind: "turn_ended", cost_usd: "0.09", estimate: true, tokens: 5, reason: "result" }).includes("Codex 不回報金額"), "without an engine it is what it was");
  const line = text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.09", estimate: true, tokens: 86000, reason: "result" }, { engine: "agy-chat" }));
  assert(line.includes("AGY 不回報金額"), line);
});

test("an AGY employee is named AGY wherever an AI tool is named", () => {
  assert.strictEqual(app.chatToolName("agy"), "AGY");
  assert.strictEqual(app.chatToolName("agy-chat"), "AGY");
  assert.strictEqual(app.chatToolName("claude"), "Claude Code");
});

// ---- the notice per state, the chat list ---------------------------------------------------------------------------------

test("the AGY notice says each state in words, with the way out only where there is one, and never a login button", () => {
  const ui = { confirm: false, pending: false, ask() {}, go() {}, cancel() {} };
  const node = (state, extra = {}) => app.chatAgySupportNode(agySupport({ state, verified: state === "ready", ...extra }), ui);
  const ready = node("ready");
  assert(text(ready).includes("可以聊天") && text(ready).includes("AGY 1.5.3"));
  assert(text(q(ready, "money")).includes("Google 方案") && text(q(ready, "money")).includes("不是帳單"));
  assert.strictEqual(text(q(ready, "skills-note")), "AGY 員工會用到你自己裝的 AGY 技能。");
  const words = { not_installed: "還沒安裝 AGY", unsupported: "還不認得", unverified: "還沒通過聊天驗證", policy: "管理員政策", hooks: "AGY 設定", folder: "資料夾不能用", version_unreadable: "讀不到 AGY 的版本" };
  for (const [state, w] of Object.entries(words)) {
    const n = node(state, { why: "虛構的原因 " + state });
    assert(text(n).includes(w), state);
    assert(text(q(n, "support-message")).includes("虛構的原因 " + state), state);
    assert.strictEqual(q(n, "skills-note"), null, "only a ready AGY promises the skills");
    assert(!text(n).includes("登入"), state + " has no login button: " + text(n));
  }
  assert(q(node("not_installed"), "setup-go") && q(node("folder"), "setup-go"));
  for (const state of ["unsupported", "policy", "hooks", "version_unreadable"]) assert.strictEqual(q(node(state), "setup-go"), null, state);
  const hooks = text(q(node("hooks"), "hooks-note"));
  assert(hooks.includes("hooks") && hooks.includes("VBear 不會幫你改它"), hooks);
  assert(text(app.chatAgySupportNode(null, ui)).includes("讀不到"));
  assert.strictEqual(app.CHAT_AGY_WORD.ready[0], "可以聊天");
});

test("a version not yet checked says what the check costs (the person's Google plan), asks first, and posts the engine and the version it showed", async () => {
  const ui = { confirm: false, pending: false, ask() {}, go() {}, cancel() {} };
  const un = agySupport({ state: "unverified", verified: false, why: "AGY 1.5.3 還沒有通過聊天驗證。" });
  const cost = text(q(app.chatAgySupportNode(un, ui), "verify-cost"));
  for (const w of ["Google 方案", "不另外收費", "送到 Google", "每個指令都先問你"]) assert(cost.includes(w), w);
  assert(q(app.chatAgySupportNode(un, ui), "verify") && !q(app.chatAgySupportNode(un, ui), "verify-go"));
  const asking = app.chatAgySupportNode(un, { ...ui, confirm: true });
  assert(text(q(asking, "verify-go")).includes("Google 方案") && q(asking, "verify-cancel"));
  assert(q(app.chatAgySupportNode(un, { confirm: false, pending: true }), "verifying") && !q(app.chatAgySupportNode(un, { confirm: false, pending: true }), "verify"));
  const failed = app.chatAgySupportNode({ ...un, verify: { running: false, result: "failed", message: "聊天驗證：虛構項目 沒有通過" } }, ui);
  assert(text(q(failed, "verify-result")).includes("虛構項目"));
  setPage({ list: listing({ support: support({ agy: un }) }) });
  const main = await open("#/chat?profile=emp-5");
  q(main, "verify").click();
  await settle();
  assert.strictEqual(posts("/api/chat-support/verify").length, 0, "the first press only asks");
  q(h.dom().mainEl, "verify-go").click();
  await settle();
  assert.deepStrictEqual(posts("/api/chat-support/verify").map((c) => c.body), [{ engine: "agy", version: "1.5.3" }]);
});

test("the list shows the AGY notice for an AGY card and opens an AGY chat only when it is ready", async () => {
  setPage({ list: listing({ chats: [
    { id: AGY_CID, profile_id: "emp-5", engine: "agy-chat", created_at: 1790000000, last_at: 1790000100, last_kind: "reply", last_text: "好", turns: 1, spent_usd: "0.02", open: false, waiting: false, problem: null }] }) });
  let main = await open("#/chat");
  assert.deepStrictEqual(qa(main, "row").map((r) => text(q(r, "tool"))), ["AGY"], "the row names its AI tool");
  assert(q(main, "agy-support") && q(main, "support"), "both notices while no card is chosen");
  const sel = q(main, "card");
  sel.value = "emp-5";
  sel.dispatch("change");
  main = h.dom().mainEl;
  assert(q(main, "agy-support") && !q(main, "support"), "an AGY card: AGY's notice only");
  assert.strictEqual(q(main, "open").disabled, false);
  q(main, "open").click();
  await settle();
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: "emp-5" }]);
  for (const state of ["unverified", "hooks", "policy", "unsupported", "folder"]) {
    setPage({ list: listing({ support: support({ agy: agySupport({ state, verified: false, why: "虛構的原因" }) }) }) });
    main = await open("#/chat?profile=emp-5");
    assert.strictEqual(q(main, "open").disabled, true, state);
    assert(text(main).includes("AGY 準備好之前") && !text(main).includes("這個 Claude Code 版本通過聊天驗證之前"), state);
  }
  setPage({ list: listing({ support: support({ agy: agySupport() }) }) });
  main = await open("#/chat?profile=emp-1");
  assert.strictEqual(q(main, "open").disabled, false, "a Claude card does not wait for AGY");
  assert(q(main, "support") && !q(main, "agy-support"));
});

test("a person with AGY not installed sees no AGY notice until an AGY card is chosen; one with only AGY sees no warning about a Claude Code that is not there", async () => {
  setPage({ list: listing({ support: support({ agy: agySupport({ state: "not_installed", installed: false, version: null, verified: false, why: "找不到 AGY。" }) }) }) });
  let main = await open("#/chat");
  assert(q(main, "support") && !q(main, "agy-support"));
  const sel = q(main, "card");
  sel.value = "emp-5";
  sel.dispatch("change");
  assert(q(h.dom().mainEl, "agy-support") && text(h.dom().mainEl).includes("還沒安裝 AGY"));
  setPage({ list: listing({ support: support({ detected: null, state: "unknown", verified: [], message: "讀不到 Claude Code 的版本（沒有安裝）", agy: agySupport() }) }) });
  main = await open("#/chat");
  assert(!q(main, "support") && q(main, "agy-support"));
});

test("the start-up status decides whether AGY chat is ready from the row alone, not from a login mark", () => {
  const row = (over) => ({ tools: [{ id: "agy", installed: true, ready: false, chat: { verified: true }, ...over }] });
  assert.strictEqual(app.agyChatReady(row({})), true);
  assert.strictEqual(app.agyChatReady(row({ chat: { verified: false } })), false);
  assert.strictEqual(app.agyChatReady(row({ installed: false })), false);
  assert.strictEqual(app.agyChatReady({ tools: [] }), false);
  assert.strictEqual(app.agyChatReady(null), false);
});

// ---- the chat page of an AGY employee ------------------------------------------------------------------------------------

test("the chat page of an AGY employee says what AGY does differently: the sandbox, Google, the skills, the estimate", async () => {
  setPage();
  const main = await open(`#/chat/${AGY_CID}`);
  const note = text(q(main, "agy-note"));
  for (const w of ["不能連網", "送到 Google", "AGY 員工會用到你自己裝的 AGY 技能", "不是帳單", "超過花費上限", "Google 方案"]) assert(note.includes(w), w);
  assert.strictEqual(q(main, "codex-note"), null);
  assert(text(main).includes("工具：AGY"));
  assert.strictEqual(q(main, "plan-usage"), null, "AGY reports no plan use");
  noMarkup(main);
});

test("a card that asks while an AGY chat is open is drawn as an AGY card", async () => {
  setPage({ detail: agyDetail({ live: live({ state: "waiting_for_you", turn: 1, cards: [agyRead()] }) }) });
  const main = await open(`#/chat/${AGY_CID}`);
  const cardNode = q(main, "live-card");
  assert(cardNode && text(cardNode).includes("員工想讀取檔案") && q(cardNode, "read-note") && !q(cardNode, "modify"));
  setPage({ detail: agyDetail({ live: live({ state: "waiting_for_you", turn: 1, cards: [agyCommand()] }) }) });
  const again = await open(`#/chat/${AGY_CID}`);
  assert(text(q(again, "sandbox-warning")).includes("AGY 的沙盒"));
});

test("deleting an AGY chat says AGY keeps its own copy and where", async () => {
  setPage();
  const main = await open(`#/chat/${AGY_CID}`);
  q(main, "delete").click();
  await settle();
  const dlg = text(dialog());
  for (const w of ["AGY 自己", "對話副本", "agy-chat-home", "不會刪掉"]) assert(dlg.includes(w), w);
  assert(!dlg.includes("codex-chat-home"));
});

test("the first-time notes name AGY: what it costs, that it goes to Google, the read card, and 改內容再問", () => {
  const all = app.CHAT_INTRO.map(([t, b]) => t + "：" + b).join("\n");
  assert(app.CHAT_INTRO.some(([t]) => t === "用 AGY 聊天"));
  const agy = app.CHAT_INTRO.find(([t]) => t === "用 AGY 聊天")[1];
  for (const w of ["Google 方案", "送到 Google", "不是帳單", "超過花費上限", "驗證聊天", "AGY 員工會用到你自己裝的 AGY 技能", "讀取檔案", "沒有可以改的內容", "下一則訊息"]) assert(agy.includes(w), w);
  assert(all.includes("Claude Code 或 Codex、而且已啟用的角色卡可以聊天（AGY 的員工也可以"), "the old sentence stays, with AGY beside it");
});

// ---- memory and the shared folder: off, and a yes to Google first -----------------------------------------------------------

const MEM_CARDS = () => [
  { profile_id: "emp-1", name: "文案小編", tool: "claude", company: "Anthropic", can_chat: true, on: true },
  { profile_id: "emp-5", name: "AGY 員工", tool: "agy", company: "Google", can_chat: true, on: false },
];
const memView = (over = {}) => ({ ok: true, entries: [], used: { count: 3, chars: 30, max_count: 50, max_chars: 4000 }, readable: true, where_text: "", problem: null, cards: MEM_CARDS(), ...over });

test("memory page: an AGY employee starts off, the notes name Google, and switching on asks first and says the content goes to Google", async () => {
  setPage({ memory: memView() });
  const main = await open("#/memory");
  const rows = qa(main, "card", "data-memory");
  assert(text(rows[1]).includes("AGY") && text(rows[1]).includes("Google"));
  assert.strictEqual(q(rows[1], "card-switch", "data-memory").checked, false, "off by default");
  assert(text(q(main, "cards-note", "data-memory")).includes("AGY 的員工預設不帶") && text(q(main, "cards-note", "data-memory")).includes("送到 Google"));
  assert(text(main).includes("Google（AGY 的員工）"), "the line over the page names Google");
  const sw = q(rows[1], "card-switch", "data-memory");
  sw.checked = true; sw.dispatch("change");
  await settle();
  const dlg = text(dialog());
  assert(dlg.includes("內容會送到 Google") || dlg.includes("記憶的內容會送到 Google"), dlg);
  assert(dlg.includes("3 條都會送") && !dlg.includes("OpenAI"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.url === "/api/memory/cards").length, 0, "nothing before the yes");
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.url === "/api/memory/cards").map((c) => c.body), [{ profile_id: "emp-5", on: true, confirm_company: true }]);
});

test("memory page: saying no leaves AGY off and posts nothing; switching it off asks nothing", async () => {
  setPage({ memory: memView() });
  let main = await open("#/memory");
  let sw = q(qa(main, "card", "data-memory")[1], "card-switch", "data-memory");
  sw.checked = true; sw.dispatch("change");
  await settle();
  dialog().find((n) => n.tag === "button" && text(n) === "取消").click();
  await settle(80);
  assert.strictEqual(FETCH_LOG.filter((c) => c.url === "/api/memory/cards").length, 0);
  assert.strictEqual(q(qa(h.dom().mainEl, "card", "data-memory")[1], "card-switch", "data-memory").checked, false);
  setPage({ memory: memView({ cards: MEM_CARDS().map((c) => (c.profile_id === "emp-5" ? { ...c, on: true } : c)) }) });
  main = await open("#/memory");
  sw = q(qa(main, "card", "data-memory")[1], "card-switch", "data-memory");
  sw.checked = false; sw.dispatch("change");
  await settle(80);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.url === "/api/memory/cards").map((c) => c.body), [{ profile_id: "emp-5", on: false }]);
  assert.strictEqual(dialog(), null);
});

test("the chat page's memory line names Google for an AGY employee", () => {
  const line = text(app.memoryChatLine({ on: true, count: 2, readable: true }, "agy-chat"));
  assert(line.includes("Google") && line.includes("2 條"), line);
  assert(text(app.memoryChatLine({ on: false, count: 2, readable: true }, "agy-chat")).includes("不帶記憶"));
});

const SH_CARDS = () => [
  { profile_id: "emp-1", name: "文案小編", tool: "claude", company: "Anthropic", can_chat: true, on: false, verified: null },
  { profile_id: "emp-5", name: "AGY 員工", tool: "agy", company: "Google", can_chat: true, on: false, verified: null },
];
const shView = (over = {}) => ({ ok: true, where_text: "~/.vbear/shared", exists: true, problem: null, readable: true,
  used: { bytes: 0, entries: 0, max_bytes: 1073741824, max_entries: 10000, over: false }, links: 0, files: [], cards: SH_CARDS(), ...over });

test("shared folder page: the rule line names Google, an AGY employee has a switch, and switching on asks first and then sends the yes", async () => {
  setPage({ shared: shView() });
  const main = await open("#/shared");
  const company = text(q(main, "rule-company", "data-shared"));
  assert(company.includes("AGY 的員工送到 Google") && company.includes("不要放密碼、帳號、金鑰"));
  const rows = qa(main, "card", "data-shared");
  assert(text(q(rows[1], "company", "data-shared")).includes("打開後，讀到的檔案會送給 Google"));
  const sw = q(rows[1], "card-switch", "data-shared");
  assert(sw && sw.checked === false);
  sw.checked = true; sw.dispatch("change");
  await settle();
  const dlg = text(dialog());
  assert(dlg.includes("會送到 Google") && dlg.includes("AGY"), dlg);
  assert.strictEqual(FETCH_LOG.filter((c) => c.url === "/api/shared/cards").length, 0);
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.url === "/api/shared/cards").map((c) => c.body), [{ profile_id: "emp-5", on: true, confirm_company: true }]);
});

test("shared folder page: when the server does not support the shared folder for an AGY employee, the page says the AI tool cannot use it and offers no switch", async () => {
  setPage({ shared: shView({ cards: SH_CARDS().map((c) => (c.tool === "agy" ? { ...c, company: null } : c)) }) });
  const main = await open("#/shared");
  const row = qa(main, "card", "data-shared")[1];
  assert.strictEqual(q(row, "card-switch", "data-shared"), null);
  assert(text(q(row, "unsupported", "data-shared")).includes("還不能用共用資料夾"));
});

// ---- groups, dispatch, the chief of staff -----------------------------------------------------------------------------------

const GROUP_CARDS = () => [
  { id: "emp-1", name: "文案小編", tool: "claude", can_chat: true },
  { id: "emp-4", name: "會計師", tool: "codex", can_chat: true },
  { id: "emp-5", name: "AGY 員工", tool: "agy", can_chat: true },
];
function groupDialog(onCreate = async () => ({})) {
  app.openGroupDialog(GROUP_CARDS(), { onCreate });
  const all = h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop"));
  return all[all.length - 1];
}
const pickIn = (dlg, id) => { const b = qa(dlg, "pick", "data-group").find((x) => x.getAttribute("data-profile-id") === id); b.checked = true; b.dispatch("change"); };

test("group dialog: the sentence names every company in the group, in the order Claude Code, Codex, AGY, and says nothing for one company", () => {
  const dlg = groupDialog();
  pickIn(dlg, "emp-1");
  pickIn(dlg, "emp-5");
  assert.strictEqual(text(q(dlg, "mixed-box", "data-group")).includes("群組裡有 Claude Code 和 AGY 的員工，群組裡的對話會同時送給 Anthropic 和 Google。"), true, text(q(dlg, "mixed-box", "data-group")));
  pickIn(dlg, "emp-4");
  const three = text(q(dlg, "mixed-box", "data-group"));
  assert(three.includes("Claude Code、Codex 和 AGY") && three.includes("Anthropic、OpenAI 和 Google"), three);
  assert.strictEqual(app.groupMixedNote(["claude", "codex"]), app.GROUP_MIXED_NOTE, "the old sentence is word for word");
  assert.strictEqual(app.groupMixedNote(["agy", "agy"]), "");
  assert.strictEqual(app.groupMixedNote(["claude"]), "");
});

test("group dialog: ticking the shared folder with an AGY member says the files go to Google and the request carries confirm_company", async () => {
  const bodies = [];
  const dlg = groupDialog(async (b) => { bodies.push(b); return {}; });
  pickIn(dlg, "emp-1"); pickIn(dlg, "emp-5");
  assert.strictEqual(q(dlg, "shared-google", "data-group"), null, "the line waits for the tick");
  const tick = q(dlg, "shared", "data-group");
  tick.checked = true; tick.dispatch("change");
  assert.strictEqual(text(q(dlg, "shared-google", "data-group")), app.GROUP_SHARED_GOOGLE_NOTE);
  assert(text(q(dlg, "shared-google", "data-group")).includes("Google") && !q(dlg, "shared-codex", "data-group"));
  q(dlg, "create", "data-group").click();
  await settle();
  assert.deepStrictEqual(bodies, [{ profile_ids: ["emp-1", "emp-5"], shared_folder: true, confirm_company: true }]);
});

test("a group's reply of an AGY employee is costed as an estimate that AGY reports at the end of the turn; the other tools keep their words", () => {
  const cost = (tool, extra = {}) => app.groupReplyCost({ tool, cost_usd: "0.02", ...extra });
  assert(cost("agy").includes("估計 US$0.02") && cost("agy").includes("AGY 到一回合結束才回報用量"), cost("agy"));
  assert.strictEqual(cost("codex"), "按上限 US$0.02 計");
  assert.strictEqual(cost("claude"), "US$0.02（Claude Code 回報的估值）");
});

test("a dispatch proposal with an AGY employee: the tick says the files go to Google and the confirmation carries the yes", async () => {
  const SHA = "a".repeat(64), DID = "d-0123456789ab";
  FETCH_LOG.length = 0;
  setHandler((url) => (url.split("?")[0] === `/api/dispatch/${DID}/confirm` ? jsonResponse({ id: DID, state: "running", shared: { opened: [] } }) : null));
  const v = { id: DID, chief_id: "cos-0123456789ab", chat_id: AGY_CID, created_at: 1790000200, state: "proposed", started_by: null, started_by_text: null, summary: "找 AGY 員工。",
    questions: [], notes: [], team: [{ who: "C1", why: "會寫", kind: "existing", name: "AGY 員工" }], tools: ["claude", "codex", "agy"], proposal_sha: SHA, edited: false, task_id: null,
    created_cards: [], steps: [], plan: { title: "週末市集", goal: "準備", deliverables: ["x"], new_cards: [], steps: [{ who: "C1", text: "請寫", name: "AGY 員工" }] },
    cost: { steps: 1, per_turn_usd: "0.5", max_usd: "0.5", day_left_usd: "2.71" }, pause: null, events: [],
    can: { confirm: true, dismiss: true, stop: false, continue: false, delete: true, withdraw: [] },
    shared: { people: [{ who: "C1", name: "AGY 員工", on: false, company: "Google", usable: true }] } };
  const node = app.proposalCard(v, {});
  await settle();
  const tick = q(node, "shared", "data-dispatch");
  assert(tick);
  tick.checked = true; tick.dispatch("change");
  assert.strictEqual(text(q(node, "shared-google", "data-dispatch")), app.DISPATCH_SHARED_GOOGLE_NOTE);
  assert(!q(node, "shared-codex", "data-dispatch"));
  q(node, "confirm", "data-dispatch").click();
  await settle();
  const sent = FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === `/api/dispatch/${DID}/confirm`)[0].body;
  assert.strictEqual(sent.shared_folder, true);
  assert.strictEqual(sent.confirm_company, true);
});

test("the chief of staff's desk on an AGY CEO's chat says the talk goes to Claude Code; other CEOs' desks do not", async () => {
  setHandler(() => jsonResponse({ ok: true, chiefs: [], dispatch: [] }));
  const real = global.setInterval;
  global.setInterval = () => 0;
  try {
    const agy = app.chiefDesk(AGY_CID, { tool: "agy" });
    assert(text(q(agy.node, "agy-sends", "data-chief")).includes("AGY") && text(q(agy.node, "agy-sends", "data-chief")).includes("Claude Code（Anthropic）"));
    assert.strictEqual(q(agy.node, "codex-sends", "data-chief"), null);
    agy.stop();
    const claude = app.chiefDesk(AGY_CID, { tool: "claude" });
    assert.strictEqual(q(claude.node, "agy-sends", "data-chief"), null);
    claude.stop();
  } finally { global.setInterval = real; }
  assert(app.CHIEF_NEEDS_WHY.includes("Codex 或 AGY"));
});

// ---- the role card pool, the first CEO, the start-up page, templates -------------------------------------------------------------

test("a role card of an AGY employee can chat and says what AGY is for; a card of another unsupported tool still cannot", () => {
  const mk = (tool) => app.profileCard({ id: "emp-5", name: "虛構員工", enabled: true, model: { tool }, position: "pm" },
    { handlers: { chat: () => {} } }).node;
  const agy = mk("agy");
  const btn = agy.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat");
  assert.notStrictEqual(btn.disabled, true);
  assert.strictEqual(text(agy.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "agy-note")), "AGY 的員工可以聊天（每個指令都問你）；要在終端機出發請選完整模式。");
  const grok = mk("grok");
  assert.strictEqual(grok.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat").disabled, true);
  assert.strictEqual(grok.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "agy-note"), null);
});

test("the start-up page says whether AGY chat has been checked, with no login button for it", () => {
  const row = { id: "agy", name: "AGY", state: "ready", installed: true, version: "1.5.3", login: "marked", can_mark: true, chat: { verified: false } };
  const bad = app.setupToolView(row);
  assert(bad.note.includes("聊天：還沒驗證") && bad.note.includes("驗證聊天") && bad.note.includes("Google 方案") && bad.note.includes("hooks"), bad.note);
  assert(bad.note.includes("AGY 員工會用到你自己裝的 AGY 技能"));
  assert(!bad.buttons.some((b) => b.kind === "chat_login"), "no chat login for AGY");
  const good = app.setupToolView({ ...row, chat: { verified: true } });
  assert(good.note.includes("聊天：已驗證"));
  const away = app.setupToolView({ ...row, installed: false, state: "not_installed", chat: { verified: false } });
  assert(!away.note.includes("聊天：") || away.note.includes("安裝"), "not installed: nothing about chat");
  assert.strictEqual(app.setupToolView({ id: "claude", state: "ready", installed: true }).note.includes("聊天："), false);
});

test("the whole of the new code has no innerHTML, no emoji and no external address", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(source));
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  for (const marker of ["CHAT_AGY_SANDBOX_WARNING", "CHAT_AGY_WORD", "SETUP_AGY_NOT_VERIFIED", "CEO_AGY_NOTE", "MEMORY_CONFIRM_COMPANY", "GROUP_SHARED_GOOGLE_NOTE"]) assert(source.includes(marker), marker);
  const mine = source.split("\n").filter((l) => /AGY|agy/.test(l)).join("\n");
  assert(!emoji.test(mine), "no emoji");
  assert(!/https?:\/\//.test(mine), "no external address");
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  assert(!emoji.test(css));
});

// ---- run ---------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  await settle();
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
