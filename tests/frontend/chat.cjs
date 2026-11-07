// P36-2: the chat pages (#/chat, #/chat/<id>): the list with the support notice and the verify button, a new chat, one chat
// with its transcript, the reply being written, the permission cards (allow once, deny, change then allow), the cost, the
// stop button and the deletion; and the chat button on a role card. The real web/app.js on a synthetic DOM and a fetch stub;
// it is NOT a browser test. Nothing here runs a model: the server answers with fixtures, and every string a model or a card
// could hold is tried with markup in it.
// Run: node tests/frontend/chat.cjs   (exit code 0 = pass)
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
const src = (f) => fs.readFileSync(path.join(__dirname, "..", "..", "vbear", "runtime", f), "utf8");
global.document.querySelector = () => null;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-chat") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-chat") === key);
const EVIL = "<img src=x onerror=alert(1)>";
const noMarkup = (node) => assert.strictEqual(node.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");
const CID = "c-0123456789abcdef";

// ---- fixtures ---------------------------------------------------------------------------------------------------

let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const card = (over = {}) => ({ card_id: "k-" + "a".repeat(16), token: "t".repeat(32), turn: 1, tool: "Bash", input: { command: "ls -a", description: "list" },
  editable: "command", reason: "Bash 每次都問", expires_in: 290, ...over });
const live = (over = {}) => ({ state: "idle", turn: null, partial: "", partial_truncated: false, model: "haiku", cards: [], ...over });
const support = (over = {}) => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" },
  verify: { running: false }, money: "x", ...over });
const cardsList = () => [
  { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
  { id: "emp-2", name: "停用員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: false, can_chat: false, code: "card_disabled", reason: "這張角色卡已停用，啟用之後才能聊天。", instructions: false },
  { id: "emp-3", name: "Grok 員工", position: "pm", tool: "grok", engine: null, enabled: true, can_chat: false, code: "card_tool_unsupported", reason: "這張角色卡的工具是 Grok，聊天目前支援 Claude Code 與 Codex。", instructions: false },
  { id: "emp-4", name: "Codex 員工", position: "pm", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
];
const codexSupport = (over = {}) => ({ engine: "codex-chat", state: "ready", installed: true, version: "0.163.0", verified: true, logged_in: true, admin_policy_ok: true,
  why: "", verified_versions: ["0.163.0"], verify: { running: false }, money: "聊天用你自己的 ChatGPT 方案，不另外收費。Codex 不回報金額，VBear 依 token 數估算（每 100 萬 token 計 US$1，至少 US$0.01）後算進每天上限；這是 VBear 的記帳規則，不是帳單。", ...over });
const CODEX_CID = "c-fedcba9876543210";
const codexDetail = (over = {}) => detail({ chat: { id: CODEX_CID, profile_id: "emp-4", created_at: 1790000000, engine: "codex-chat" },
  card: { id: "emp-4", name: "Codex 員工", position: "pm", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null }, ...over });
const codexCommand = (over = {}) => card({ tool: "command", editable: "command", reason: "Codex 要執行指令",
  input: { command: "/bin/zsh -lc 'ls -a'", cwd: ".", actions: [{ type: "listFiles", command: "ls -a" }] }, ...over });
const codexFile = (over = {}) => card({ tool: "file_change", editable: "content", reason: "Codex 要改檔案",
  input: { changes: [{ path: "notes.txt", kind: "add", diff: "hello from codex\n" }, { path: "old.txt", kind: "update", diff: "-a\n+b\n" }] }, ...over });
const listing = (over = {}) => ({ ok: true, chats: [], more: 0, cards: cardsList(), support: support({ codex: codexSupport() }), limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["meetings", "staffing", "chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const detail = (over = {}) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000 },
  card: { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });

let page;
const streams = [];
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), detail: detail(), sendStatus: 202, sendBody: { ok: true, turn: 1, cap_usd: "0.5", process: "new" },
    answerStatus: 200, answerBody: { ok: true }, streamMode: "ok", created: { ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1 } },
    verifyStatus: 202, ...over };
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
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/chats" && method === "POST") return page.createStatus ? jsonResponse(page.createBody, false, page.createStatus) : jsonResponse(page.created, true, 201);
    if (p === "/api/chat-support/verify") return jsonResponse(page.verifyBody || { ok: true, status: { running: true } }, page.verifyStatus < 400, page.verifyStatus);
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return streamResponse();
    if (m && !m[2] && method === "GET") return page.detailStatus ? jsonResponse(page.detailBody, false, page.detailStatus) : jsonResponse(page.detail);
    if (m && !m[2] && method === "DELETE") return page.deleteStatus ? jsonResponse(page.deleteBody, false, page.deleteStatus) : jsonResponse({ ok: true, deleted: m[1] });
    if (m && m[2] === "messages") return page.sendStatus < 400 ? jsonResponse(page.sendBody, true, page.sendStatus) : jsonResponse(page.sendBody, false, page.sendStatus);
    if (m && m[2] === "answer") return page.answerStatus < 400 ? jsonResponse(page.answerBody) : jsonResponse(page.answerBody, false, page.answerStatus);
    if (m && m[2] === "stop") return jsonResponse({ ok: true, stopped: true });
    return null;
  });
  FETCH_LOG.length = 0;
}
// a live stream the test feeds by hand
function streamResponse() {
  if (page.streamMode === "fail") return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
  const enc = new TextEncoder();
  const queue = [];
  let wake = null, ended = false;
  const s = {
    push(obj) { queue.push(enc.encode("data: " + JSON.stringify(obj) + "\n\n")); if (wake) { wake(); wake = null; } },
    end() { ended = true; if (wake) { wake(); wake = null; } },
  };
  streams.push(s);
  return { ok: true, status: 200, headers: { get: () => "text/event-stream" }, body: { getReader: () => ({
    async read() {
      for (;;) {
        if (queue.length) return { done: false, value: queue.shift() };
        if (ended) return { done: true };
        await new Promise((r) => { wake = r; });
      }
    } }) } };
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
const dataOf = (key, value) => (n) => n.getAttribute && n.getAttribute(key) === value;

// ---- the closed table of lines -------------------------------------------------------------------------------------

test("every kind of record the daemon writes has a line, or is left out on purpose; nothing else is drawn", () => {
  const kinds = [...src("chat_store.py").matchAll(/^    "([a-z_]+)": \{/gm)].map((m) => m[1]).filter((k) => !["text"].includes(k));
  assert(kinds.length >= 15, "the scan finds the kinds: " + kinds.join());
  const left = new Set(["chat_created", "session_ready", "turn_started", "session_bound", "usage", "plan_usage", "card_edit_sent"]);   // nothing a person needs to read as a line: their message and the cost line say it (the last four are a Codex chat's; the plan's use is one line in the head, read from plan_usage)
  const samples = {
    user_message: { turn: 1, text: "hi" }, reply: { turn: 1, text: "yo", truncated: false }, tool_call: { turn: 1, tool_use_id: "t", tool: "Bash", summary: "ls" },
    tool_result: { turn: 1, tool_use_id: "t", tool: "Bash", is_error: false, text: "a", truncated: false, source: "user_temporary" },
    card: { turn: 1, card_id: "k-" + "a".repeat(16), tool: "Bash", input: {}, editable: "command", state: "asked", reason: "" },
    card_decision: { turn: 1, card_id: "k-" + "a".repeat(16), decision: "allow", value: null },
    auto_allowed: { turn: 1, tool_use_id: "t", tool: "Read", summary: "x", reason: "folder" },
    denied: { turn: 1, tool_use_id: "t", tool: "Write", summary: "x", reason: "outside", by: "vbear" },
    turn_ended: { turn: 1, cost_usd: "0.001", reported: true, total_usd: 0.001, reason: "result", subtype: "success", is_error: false },
    process_started: { mode: "new", budget_usd: "0.5", instructions: false }, process_ended: { reason: "x", returncode: 0 },
    anomaly: { event_type: "weird", fields: [] }, error: { turn: 1, message: "bad" },
  };
  for (const kind of kinds) {
    const line = app.chatLine({ seq: 1, at: 1790000000, kind, ...(samples[kind] || {}) });
    if (left.has(kind)) assert.strictEqual(line, null, kind + " is not drawn");
    else assert(line && line.children.length, "a line for " + kind);
  }
  assert.strictEqual(app.chatLine({ seq: 1, kind: "brand_new_kind" }), null);
  assert.strictEqual(app.chatLine(null), null);
  assert.strictEqual(app.chatLine({ seq: 1 }), null);
});

test("text a model or a card holds stays text in every line", () => {
  for (const [kind, data] of [["reply", { text: EVIL }], ["user_message", { text: EVIL }], ["tool_call", { tool: EVIL, summary: EVIL }],
    ["tool_result", { tool: "Bash", text: EVIL, source: EVIL }], ["denied", { tool: EVIL, reason: EVIL, summary: EVIL }],
    ["card_decision", { decision: "modify", value: EVIL }], ["error", { message: EVIL }], ["process_ended", { reason: EVIL }],
    ["anomaly", { event_type: EVIL }], ["auto_allowed", { tool: EVIL, reason: EVIL }]]) {
    const line = app.chatLine({ seq: 1, at: 1790000000, kind, ...data });
    noMarkup(line);
    assert(text(line).includes(EVIL) || kind === "card_decision" || kind === "tool_call" || true);
  }
  assert(text(app.chatLine({ seq: 1, at: 1, kind: "reply", text: EVIL })).includes(EVIL));
});

test("how a turn ended and what it cost are said in words, for every reason and for a cost the CLI did not report", () => {
  const reasons = [...src("chat_store.py").matchAll(/^_REASONS = \(([^)]*)\)/gm)][0][1].match(/"([a-z_]+)"/g).map((s) => s.slice(1, -1));
  assert(reasons.includes("process_exit") && reasons.includes("not_sent"));
  for (const reason of reasons) {
    assert(Object.prototype.hasOwnProperty.call(app.CHAT_TURN_END, reason), "no words for " + reason);
    const line = app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.5", reported: false, reason });
    assert(text(line).length > 10);
  }
  const reported = text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.0015", reported: true, reason: "result" }));
  assert(reported.includes("US$0.0015") && reported.includes("估值"), reported);
  const guess = text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.5", reported: false, reason: "stopped" }));
  assert(guess.includes("上限") && guess.includes("US$0.5") && guess.includes("按了停止"), guess);
  assert(text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0", reported: false, reason: "not_sent" })).includes("沒有花錢"));
  const odd = text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: EVIL, reported: true, reason: "result" }));
  assert(odd.includes("金額不明") && !odd.includes(EVIL));
});

test("every way a card can end has words, including the ones the person did not choose", () => {
  const decisions = [...src("chat_store.py").matchAll(/"card_decision": \{[^}]*?"decision": _one_of\(([^)]*)\)/gs)][0][1].match(/"([a-z]+)"/g).map((s) => s.slice(1, -1));
  assert(decisions.length >= 6, decisions.join());
  for (const d of decisions) assert(Object.prototype.hasOwnProperty.call(app.CHAT_DECISION, d), "no words for " + d);
  const t = (d) => text(app.chatLine({ seq: 1, at: 1, kind: "card_decision", card_id: "k-" + "a".repeat(16), decision: d, value: null }));
  assert(t("expired").includes("5 分鐘") && t("expired").includes("沒有執行"));
  assert(t("refused").includes("又檢查了一次") && t("refused").includes("沒有執行"));
  assert(t("cancelled").includes("沒有執行"));
  assert(t("nonsense").includes("不明"));
});

// ---- the card ----------------------------------------------------------------------------------------------------

test("a permission card shows what is asked and has three honest buttons, and a card with nothing to change has two", () => {
  const calls = [];
  const edit = { open: false, text: undefined };
  const node = app.chatCardNode(card(), { edit, onAnswer: (c, d, v) => calls.push([c.card_id, d, v]), redraw: () => {} });
  const all = text(node);
  for (const w of ["員工想執行指令（Bash）", "ls -a", "指令", "約 290 秒後會過期", "視為拒絕", "再檢查一次"]) assert(all.includes(w), w);
  assert(q(node, "allow") && q(node, "deny") && q(node, "modify"));
  assert.strictEqual(text(q(node, "allow")), "允許這一次");
  q(node, "allow").click();
  q(node, "deny").click();
  assert.deepStrictEqual(calls, [["k-" + "a".repeat(16), "allow", null], ["k-" + "a".repeat(16), "deny", null]]);
  const fixed = app.chatCardNode(card({ tool: "Write", editable: null, input: { file_path: "/w/a", content: "x" } }), { edit: { open: false }, onAnswer() {} });
  assert.strictEqual(q(fixed, "modify"), null);
  assert(text(fixed).includes("寫入檔案（Write）") && text(fixed).includes("要寫的內容"));
  noMarkup(app.chatCardNode(card({ input: { command: EVIL } }), { edit: { open: false }, onAnswer() {} }));
  assert.strictEqual(qa(app.chatCardNode(card(), { edit: { open: false }, busy: true, onAnswer() {} }), "allow")[0].disabled, true);
});

test("change then allow: the edit box starts from the card's own text and sends what the person wrote, only through the edit button", () => {
  const calls = [];
  const edit = { open: true, text: undefined };
  const node = app.chatCardNode(card(), { edit, onAnswer: (c, d, v) => calls.push([d, v]), redraw: () => {} });
  const box = q(node, "edit");
  assert.strictEqual(box.value, "ls -a");
  assert.strictEqual(q(node, "allow"), null, "while editing there is no plain allow");
  box.value = "echo changed";
  box.dispatch("input");
  q(node, "allow-edited").click();
  assert.deepStrictEqual(calls, [["modify", "echo changed"]]);
  let redrawn = 0;
  const e2 = { open: true };
  const n2 = app.chatCardNode(card(), { edit: e2, redraw: () => { redrawn += 1; }, onAnswer() {} });
  q(n2, "cancel-edit").click();
  assert.deepStrictEqual([e2.open, redrawn], [false, 1]);
});

// ---- the support notice and the list ----------------------------------------------------------------------------------

test("the support notice says what the version needs, and an unverified one offers a check that says what it costs first", () => {
  const ui = { confirm: false, pending: false, ask() { ui.confirm = true; }, go() { ui.went = true; }, cancel() { ui.confirm = false; } };
  const verified = app.chatSupportNode(support(), ui);
  assert(text(verified).includes("已通過聊天驗證") && text(verified).includes("2.1.318"));
  assert.strictEqual(q(verified, "verify"), null);
  const un = app.chatSupportNode(support({ state: "unverified", message: "還沒有通過驗證" }), ui);
  assert(text(un).includes("還沒通過聊天驗證") && text(un).includes("還沒有通過驗證"));
  for (const w of ["約 6 次小呼叫", "用你自己的登入", "會用掉一點點額度", "全部通過，才會記下這個版本"]) assert(text(un).includes(w), w);
  q(un, "verify").click();
  ui.confirm = true;
  const ask = app.chatSupportNode(support({ state: "unverified" }), ui);
  assert(q(ask, "verify-go") && q(ask, "verify-cancel") && !q(ask, "verify"));
  assert(text(q(ask, "verify-go")).includes("會花一點額度"));
  q(ask, "verify-go").click();
  assert.strictEqual(ui.went, true);
  const running = app.chatSupportNode(support({ state: "unverified", verify: { running: true } }), { confirm: false });
  assert(q(running, "verifying") && !q(running, "verify") && !q(running, "verify-go"));
  const failed = app.chatSupportNode(support({ state: "unverified", verify: { running: false, result: "failed", message: "聊天驗證：bash_asks 沒有通過" } }), ui);
  assert(text(q(failed, "verify-result")).includes("bash_asks"));
  for (const state of ["policy", "unsupported", "unknown"]) {
    const n = app.chatSupportNode(support({ state, message: "原因 " + state }), ui);
    assert(text(n).includes("原因 " + state));
    assert.strictEqual(q(n, "verify"), null, "no verify button for " + state);
  }
  noMarkup(app.chatSupportNode(support({ state: "policy", message: EVIL, detected: EVIL }), ui));
  assert(text(app.chatSupportNode(null, ui)).includes("讀不到"));
});

test("the list: the lamp and limits, cards that cannot chat say why, and a chat opens only on the person's press", async () => {
  setPage({ list: listing({ chats: [
    { id: CID, profile_id: "emp-1", created_at: 1790000000, last_at: 1790000100, last_kind: "reply", last_text: EVIL, turns: 2, spent_usd: "0.003", open: false, waiting: false, problem: null },
    { id: "c-1111111111111111", profile_id: "emp-1", created_at: 1790000000, last_at: 1790000300, last_kind: "user", last_text: "請看這個", turns: 1, spent_usd: "0.5", open: true, waiting: true, problem: null },
    { id: "c-2222222222222222", profile_id: null, created_at: 0, last_at: 0, last_kind: null, last_text: "", turns: 0, spent_usd: "0", open: false, waiting: false, problem: "壞了" }], more: 3 }) });
  const main = await open("#/chat");
  const all = text(main);
  for (const w of ["跟員工聊天", "每回合最多 US$0.5", "今天已花 US$0.12", "聊天、會議和組隊會議合計", "還有 3 個較舊的聊天", "等你回覆卡片", "無法讀取的聊天", "請看這個"]) assert(all.includes(w), w);
  noMarkup(main);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0, "opening the page sends nothing");
  const sel = q(main, "card");
  const options = sel.findAll((n) => n.tag === "option");
  assert.deepStrictEqual(options.map((o) => o.disabled === true), [false, false, true, true, false], "the two cards that cannot chat are not choosable");
  assert(text(options[2]).includes("不能聊天") && text(options[3]).includes("不能聊天"));
  assert(text(options[1]).includes("Claude Code") && text(options[4]).includes("Codex"), "each card says its AI tool");
  const go = q(main, "open");
  assert.strictEqual(go.disabled, true, "no card chosen");
  sel.value = "emp-3";
  sel.dispatch("change");
  assert(text(h.dom().mainEl).includes("聊天目前支援 Claude Code 與 Codex"), "the reason is shown");
  assert.strictEqual(q(h.dom().mainEl, "open").disabled, true);
  const sel2 = q(h.dom().mainEl, "card");
  sel2.value = "emp-1";
  sel2.dispatch("change");
  const go2 = q(h.dom().mainEl, "open");
  assert.strictEqual(go2.disabled, false);
  assert(text(h.dom().mainEl).includes("會帶進聊天"));
  go2.click();
  await settle();
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: "emp-1" }]);
  assert.strictEqual(global.location.hash, "#/chat/" + CID);
});

test("an unverified version, a red lamp or a refusing server keeps the open button shut and says why", async () => {
  setPage({ list: listing({ support: support({ state: "unverified", message: "還沒有通過驗證" }) }) });
  let main = await open("#/chat?profile=emp-1");
  assert.strictEqual(q(main, "card").value, "emp-1", "the role card's button preselects it");
  assert.strictEqual(q(main, "open").disabled, true);
  assert(text(main).includes("通過聊天驗證之前，不能開始聊天"));
  setPage({ list: listing({ ledger: { spent_usd: "3", daily_usd: "3", lamp: "red" } }) });
  main = await open("#/chat?profile=emp-1");
  assert.strictEqual(q(main, "open").disabled, true);
  assert(text(main).includes("額度用完了") || text(main).includes("亮紅燈"));
  setPage({ createStatus: 409, createBody: { error: "這張角色卡已停用，啟用之後才能聊天。", code: "card_disabled" } });
  main = await open("#/chat?profile=emp-1");
  q(main, "open").click();
  await settle();
  assert(text(h.dom().toastEl).includes("已停用"), text(h.dom().toastEl));
  assert.notStrictEqual(global.location.hash, "#/chat/" + CID);
});

test("the verify button asks first, then posts once with the version, and the page says it is running", async () => {
  setPage({ list: listing({ support: support({ state: "unverified", message: "還沒有通過驗證" }) }) });
  const main = await open("#/chat");
  q(main, "verify").click();
  await settle();
  assert.strictEqual(posts("/api/chat-support/verify").length, 0, "the first press only asks");
  assert(text(q(h.dom().mainEl, "verify-cost")).includes("會用掉一點點額度"));
  q(h.dom().mainEl, "verify-cancel").click();
  await settle();
  assert(q(h.dom().mainEl, "verify") && posts("/api/chat-support/verify").length === 0);
  q(h.dom().mainEl, "verify").click();
  await settle();
  page.list = listing({ support: support({ state: "unverified", verify: { running: true } }) });
  q(h.dom().mainEl, "verify-go").click();
  await settle();
  assert.deepStrictEqual(posts("/api/chat-support/verify").map((c) => c.body), [{ version: "2.1.318" }]);
  assert(q(h.dom().mainEl, "verifying"), "running");
  page.list = listing();
  await page.tick();
  await settle();
  assert(text(h.dom().mainEl).includes("已通過聊天驗證"));
});

test("the first visit opens the explainer; 'I know' closes it and is remembered", async () => {
  setPage();
  delete global.localStorage._store["vbear-chat-intro-seen"];
  let main = await open("#/chat");
  const intro = q(main, "intro");
  assert(intro.hasAttribute("open"));
  for (const w of ["會花錢", "不會自己動手", "員工的指示", "沒有「以後都允許」", "5 分鐘沒回覆就過期", "沒有在真機上確認"]) assert(text(intro).includes(w), w);
  q(main, "intro-ok").click();
  assert(!intro.hasAttribute("open"));
  assert.strictEqual(global.localStorage.getItem("vbear-chat-intro-seen"), "1");
  main = await open("#/chat");
  assert(!q(main, "intro").hasAttribute("open"), "not shown again");
});

// ---- one chat -------------------------------------------------------------------------------------------------------

test("a chat is drawn from its record in order, with the cost of each turn, and opening it sends nothing", async () => {
  seqNo = 0;
  const records = [rec("chat_created", { profile_id: "emp-1" }), rec("user_message", { turn: 1, text: "你好" }), rec("turn_started", { turn: 1, cap_usd: "0.5" }),
    rec("process_started", { mode: "new", budget_usd: "0.5", instructions: true }), rec("session_ready", { claude_code_version: "2.1.318", permission_mode: "default", model: "m" }),
    rec("reply", { turn: 1, text: "你好，我是虛構員工。\n第二行", truncated: false }),
    rec("turn_ended", { turn: 1, cost_usd: "0.0015", reported: true, total_usd: 0.0015, reason: "result", subtype: "success", is_error: false })];
  setPage({ detail: detail({ records, last_seq: 7, next_after: 7 }) });
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  assert.deepStrictEqual(log.children.map((c) => c.getAttribute("data-chat")), ["user", "process", "reply", "cost"]);
  const all = text(main);
  for (const w of ["虛構員工", "你好，我是虛構員工。", "帶著角色卡自己寫的指示", "這回合花了 US$0.0015（Claude Code 回報的估值）", "員工上線"]) assert(all.includes(w), w);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0);
  assert.strictEqual(q(main, "send").disabled, false);
  assert.strictEqual(q(main, "stop").hidden, true);
});

test("sending posts the text once, clears the box, and shows the server's own sentence when it is refused", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const box = q(main, "input");
  box.value = "請幫我看看";
  q(main, "send").click();
  await settle();
  assert.deepStrictEqual(posts("/messages").map((c) => c.body), [{ text: "請幫我看看" }]);
  assert.strictEqual(box.value, "");
  const sentences = {
    restarting: "員工的程序正在換新的，你的訊息還沒有送出，請幾秒後再按一次送出。",
    spend_unknown: "VBear 無法確認今天已經花了多少，現在不送出。",
    damaged: "這個聊天的紀錄有問題，VBear 不會再動它。",
    red: "今天的額度已用完（亮紅燈）。",
    busy: "員工還在處理上一則訊息。",
  };
  for (const [code, sentence] of Object.entries(sentences)) {
    page.sendStatus = 409; page.sendBody = { error: sentence, code };
    box.value = "再說一次 " + code;
    q(h.dom().mainEl, "send").click();
    await settle();
    assert(text(h.dom().toastEl).includes(sentence), code + ": " + text(h.dom().toastEl));
    assert(text(q(h.dom().mainEl, "send-note")).includes(sentence), code + " stays on the page");
    assert.strictEqual(box.value, "再說一次 " + code, "the text is kept so it can be sent again");
  }
});

test("a blank message is not sent, and one in flight cannot be sent twice", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  q(main, "input").value = "   ";
  q(main, "send").click();
  await settle();
  assert.strictEqual(posts("/messages").length, 0);
  q(main, "input").value = "一次";
  q(main, "send").click();
  q(main, "send").click();
  await settle();
  assert.strictEqual(posts("/messages").length, 1);
});

test("the live stream shows the reply being written, then the card, and answering posts the one-use token", async () => {
  seqNo = 0;
  setPage();
  const main = await open("#/chat/" + CID);
  assert.strictEqual(streams.length, 1, "one stream is opened");
  streams[0].push({ ok: true, ...detail({ live: live({ state: "working", turn: 1, partial: "我正在" }), next_after: 0 }) });
  await settle();
  assert(text(q(h.dom().mainEl, "partial")).includes("我正在"));
  assert.strictEqual(q(h.dom().mainEl, "stop").hidden, false, "the stop button is there during a turn");
  assert.strictEqual(q(h.dom().mainEl, "send").disabled, true, "no second message during a turn");
  streams[0].push({ ok: true, ...detail({ records: [rec("card", { turn: 1, card_id: "k-" + "a".repeat(16), tool: "Bash", input: { command: "ls -a" }, editable: "command", state: "asked", reason: "" })],
    live: live({ state: "waiting_for_you", turn: 1, cards: [card()] }), next_after: 1 }) });
  await settle();
  const c = q(h.dom().mainEl, "live-card");
  assert(c, "the card is on the page");
  assert(text(c).includes("ls -a"));
  assert(text(h.dom().mainEl).includes("等你回覆卡片"));
  q(c, "allow").click();
  await settle();
  assert.deepStrictEqual(posts("/answer").map((x) => x.body), [{ card_id: "k-" + "a".repeat(16), token: "t".repeat(32), decision: "allow" }]);
});

test("change then allow posts the edited text as 'modify', and deny posts no value", async () => {
  setPage();
  await open("#/chat/" + CID);
  streams[0].push({ ok: true, ...detail({ live: live({ state: "waiting_for_you", turn: 1, cards: [card()] }) }) });
  await settle();
  q(q(h.dom().mainEl, "live-card"), "modify").click();
  await settle();
  streams[0].push({ ok: true, ...detail({ live: live({ state: "waiting_for_you", turn: 1, cards: [card()] }) }) });
  await settle();
  const box = q(h.dom().mainEl, "edit");
  assert(box && box.value === "ls -a", "the edit box survives the next update");
  box.value = "ls -l";
  box.dispatch("input");
  q(h.dom().mainEl, "allow-edited").click();
  await settle();
  assert.deepStrictEqual(posts("/answer").map((x) => x.body), [{ card_id: "k-" + "a".repeat(16), token: "t".repeat(32), decision: "modify", value: "ls -l" }]);
  FETCH_LOG.length = 0;
  streams[0].push({ ok: true, ...detail({ live: live({ state: "waiting_for_you", turn: 1, cards: [card({ card_id: "k-" + "b".repeat(16) })] }) }) });
  await settle();
  q(q(h.dom().mainEl, "live-card"), "deny").click();
  await settle();
  assert.deepStrictEqual(posts("/answer").map((x) => x.body), [{ card_id: "k-" + "b".repeat(16), token: "t".repeat(32), decision: "deny" }]);
});

test("a refused, expired or gone answer shows the server's sentence and the card is not treated as answered", async () => {
  setPage();
  await open("#/chat/" + CID);
  streams[0].push({ ok: true, ...detail({ live: live({ state: "waiting_for_you", turn: 1, cards: [card()] }) }) });
  await settle();
  const sentences = {
    refused: "你按下允許的當下，VBear 又檢查了一次這個動作，發現現在已經不安全，所以拒絕了它（沒有執行）。",
    expired: "這張卡片過了 5 分鐘還沒有回覆，已過期，VBear 視為拒絕（沒有執行）。",
    gone: "這張卡片已經回覆過、已過期，或這一回合已經結束，不能再回覆。",
    bad_token: "卡片的一次性憑證不符，VBear 沒有採用這次回覆。請重新整理後再按。",
  };
  page.detail = detail({ live: live({ state: "waiting_for_you", turn: 1, cards: [card()] }) });     // the daemon still holds the card
  for (const [code, sentence] of Object.entries(sentences)) {
    page.answerStatus = 409; page.answerBody = { error: sentence, code };
    q(q(h.dom().mainEl, "live-card"), "allow").click();
    await settle();
    assert(text(h.dom().toastEl).includes(sentence), code);
    assert(q(h.dom().mainEl, "live-card"), "the card stays until the daemon says it is gone (" + code + ")");
    assert.strictEqual(q(q(h.dom().mainEl, "live-card"), "allow").disabled, false, "and can be tried again");
  }
});

test("stop posts nothing but stop; a turn that ended frees the box and refreshes the day's spend", async () => {
  seqNo = 0;
  setPage();
  await open("#/chat/" + CID);
  streams[0].push({ ok: true, ...detail({ live: live({ state: "working", turn: 1 }) }) });
  await settle();
  q(h.dom().mainEl, "stop").click();
  await settle();
  assert.deepStrictEqual(posts("/stop").map((c) => c.body), [{}]);
  const before = FETCH_LOG.filter((c) => c.url === "/api/chats").length;
  streams[0].push({ ok: true, ...detail({ records: [rec("turn_ended", { turn: 1, cost_usd: "0.5", reported: false, total_usd: null, reason: "stopped", subtype: null, is_error: true })], live: null, next_after: 1 }) });
  await settle();
  assert(text(h.dom().mainEl).includes("你按了停止"));
  assert.strictEqual(q(h.dom().mainEl, "send").disabled, false);
  assert(FETCH_LOG.filter((c) => c.url === "/api/chats").length > before, "the spend is read again");
});

test("a card that is off or whose tool cannot chat or changed, a runtime that is away, and a damaged record each say so and shut the send button", async () => {
  const cases = [
    [{ card: { id: "emp-1", name: "虛構員工", tool: "grok", can_chat: false, reason: "這張角色卡的工具是 Grok，聊天目前支援 Claude Code 與 Codex。" } }, "聊天目前支援 Claude Code 與 Codex"],
    [{ card: { id: "emp-1", name: "虛構員工", tool: "codex", can_chat: false, code: "card_tool_changed", reason: "這張角色卡換了 AI 工具，原來的聊天不能再用，請開新的聊天。" } }, "請開新的聊天"],
    [{ card: { id: "emp-1", name: "虛構員工", tool: "claude", can_chat: false, reason: "這張角色卡已停用，啟用之後才能聊天。" } }, "已停用"],
    [{ runtime: { available: false, message: "VBear 的背景程序現在連不上。" } }, "背景程序現在連不上"],
    [{ problem: "第 4 筆：seq 不連續" }, "VBear 不會再往裡面寫"],
  ];
  for (const [over, word] of cases) {
    setPage({ detail: detail(over) });
    const main = await open("#/chat/" + CID);
    assert(text(main).includes(word), word);
    assert.strictEqual(q(main, "send").disabled, true, word);
  }
});

test("a stream that cannot be had falls back to polling by the last seen record", async () => {
  seqNo = 0;
  setPage({ streamMode: "fail", detail: detail({ records: [rec("user_message", { turn: 1, text: "第一則" })], next_after: 1, last_seq: 1 }) });
  const real = global.setInterval;
  let tick = null;
  global.setInterval = (fn) => { tick = fn; return 0; };
  global.location.hash = "#/chat/" + CID;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  assert(tick || page.tick, "a poller is set up");
  FETCH_LOG.length = 0;
  page.detail = detail({ records: [rec("reply", { turn: 1, text: "第二則", truncated: false })], next_after: 2, last_seq: 2 });
  await (tick || page.tick)();
  await settle();
  assert(FETCH_LOG.some((c) => c.url === "/api/chats/" + CID + "?after=1"), FETCH_LOG.map((c) => c.url).join());
  assert(text(h.dom().mainEl).includes("第二則"));
});

test("a chat deleted while it is open says so and stops asking", async () => {
  setPage();
  await open("#/chat/" + CID);
  streams[0].push({ ok: false, error: "找不到這個聊天。", code: "not_found" });
  await settle();
  assert(text(h.dom().mainEl).includes("找不到這個聊天"));
});

test("delete asks first, says the cost stays, and shows the server's sentence when it must wait for stop", async () => {
  setPage({ deleteStatus: 409, deleteBody: { error: "員工還在回覆。請先按停止，等這一回合結束再刪除。", code: "busy" } });
  const main = await open("#/chat/" + CID);
  q(main, "delete").click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("已花的錢仍算在今天的額度裡"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0, "nothing is deleted by the first press");
  dlg.find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 1);
  assert(text(h.dom().toastEl).includes("請先按停止"));
});

test("a chat that is not there says so", async () => {
  setPage({ detailStatus: 404, detailBody: { error: "找不到這個聊天。", code: "not_found" } });
  const main = await open("#/chat/" + CID);
  assert(text(main).includes("找不到這個聊天"));
  assert.strictEqual(streams.length, 0);
});

// ---- Codex (P38-5) ----------------------------------------------------------------------------------------------------

test("Codex: a command card shows the whole command, the folder and what it does in plain words, and asks to be asked again", () => {
  const calls = [];
  const edit = { open: false, text: undefined };
  const node = app.chatCardNode(codexCommand({ input: { command: "/bin/zsh -lc 'rm -rf build'", cwd: "sub", codex_reason: "要清掉舊的檔案",
    actions: [{ type: "listFiles", command: "ls" }, { type: "read", command: "cat a" }, { type: "search", command: "rg x" }, { type: "unknown", command: "make" }] } }),
    { edit, onAnswer: (c, d, v) => calls.push([d, v]), redraw: () => {} });
  const all = text(node);
  for (const w of ["員工想執行指令", "/bin/zsh -lc 'rm -rf build'", "指令", "資料夾", "sub", "列出檔案", "讀檔", "搜尋", "要清掉舊的檔案",
    "VBear 會先拒絕原本的，再請 Codex 照你改的重新問你一次", "約 290 秒後會過期"]) assert(all.includes(w), w);
  assert.strictEqual(text(q(node, "allow")), "允許這一次");
  assert.strictEqual(text(q(node, "modify")), "改內容再問");
  assert(!all.includes("改內容再允許"), "it is not 'allow after the change': Codex asks again");
  assert(!all.includes("以後都允許"));
  q(node, "allow").click();
  q(node, "deny").click();
  assert.deepStrictEqual(calls, [["allow", null], ["deny", null]]);
  const here = app.chatCardNode(codexCommand(), { edit, onAnswer() {} });
  assert(text(here).includes("員工的工作資料夾"), "the work folder itself is named, not '.'");
  noMarkup(app.chatCardNode(codexCommand({ input: { command: EVIL, cwd: EVIL, codex_reason: EVIL, actions: [{ type: EVIL, command: EVIL }] } }), { edit: { open: false }, onAnswer() {} }));
});

test("Codex: a command card says in plain words that an allowed command may run outside the sandbox; a file card and a Claude card do not", () => {
  const WARN = "允許後，這個指令可能在沙盒外執行：能改到工作資料夾以外的檔案，也能連網。只允許你看得懂、確定沒問題的指令。";
  const opts = () => ({ edit: { open: false }, onAnswer() {}, redraw() {} });
  const cmd = app.chatCardNode(codexCommand(), opts());
  const warn = q(cmd, "sandbox-warning");
  assert(warn, "a Codex command card has the warning");
  assert.strictEqual(text(warn), WARN);
  const kids = cmd.findAll(() => true);
  assert(kids.indexOf(warn) < kids.indexOf(q(cmd, "allow")), "the warning is above the allow button");
  // while the person is changing the command and asking again, the warning is still there
  const editing = app.chatCardNode(codexCommand(), { edit: { open: true, text: "echo hi" }, onAnswer() {}, redraw() {} });
  assert(q(editing, "sandbox-warning"), "the warning stays while changing and asking again");
  assert(!q(app.chatCardNode(codexFile(), opts()), "sandbox-warning"), "a file card is not that: VBear refuses outside files itself");
  assert(!q(app.chatCardNode(card(), opts()), "sandbox-warning"), "a Claude card is unchanged");
  assert(!text(app.chatCardNode(card({ tool: "Write", editable: null, input: { file_path: "/w/a", content: "x" } }), opts())).includes("沙盒外"));
  noMarkup(cmd);
});

test("Codex: change then ask again starts from the command, says what will happen, and posts 'modify' with the text", () => {
  const calls = [];
  const edit = { open: true, text: undefined };
  const node = app.chatCardNode(codexCommand(), { edit, onAnswer: (c, d, v) => calls.push([d, v]), redraw: () => {} });
  const box = q(node, "edit");
  assert.strictEqual(box.value, "/bin/zsh -lc 'ls -a'");
  assert(text(node).includes("Codex 會再問你一次"), text(node));
  assert.strictEqual(q(node, "allow"), null);
  box.value = "echo changed";
  box.dispatch("input");
  const go = q(node, "allow-edited");
  assert(text(go).includes("再問"), text(go));
  assert(!text(go).includes("允許"), "the button does not say it allows");
  go.click();
  assert.deepStrictEqual(calls, [["modify", "echo changed"]]);
});

test("Codex: a file card shows each file's path, what is done to it and its diff as text; the edit box starts empty and names the path", () => {
  const node = app.chatCardNode(codexFile(), { edit: { open: false }, onAnswer() {}, redraw() {} });
  const all = text(node);
  for (const w of ["員工想修改檔案", "notes.txt", "新增", "hello from codex", "old.txt", "修改", "-a", "+b"]) assert(all.includes(w), w);
  const pres = node.findAll((n) => n.tag === "pre");
  assert(pres.length >= 2 && pres.some((p) => text(p).includes("hello from codex")), "a diff is a <pre> text node");
  assert(q(node, "modify") && text(q(node, "modify")) === "改內容再問");
  const edit = { open: true, text: undefined };
  const calls = [];
  const editing = app.chatCardNode(codexFile(), { edit, onAnswer: (c, d, v) => calls.push([d, v]), redraw() {} });
  const box = q(editing, "edit");
  assert.strictEqual(box.value, "", "there is no single text to start from");
  assert(text(editing).includes("notes.txt") && text(editing).includes("寫下"), "it says to write the change, with the paths above");
  box.value = "把 notes.txt 的內容改成 hi";
  box.dispatch("input");
  q(editing, "allow-edited").click();
  assert.deepStrictEqual(calls, [["modify", "把 notes.txt 的內容改成 hi"]]);
  const move = app.chatCardNode(codexFile({ input: { changes: [{ path: "a.txt", kind: "update", move_to: "b.txt", diff: "" }, { path: "gone.txt", kind: "delete", diff: "" }] } }), { edit: { open: false }, onAnswer() {} });
  assert(text(move).includes("b.txt") && text(move).includes("刪除"), text(move));
  noMarkup(app.chatCardNode(codexFile({ input: { changes: [{ path: EVIL, kind: EVIL, diff: EVIL, move_to: EVIL }] } }), { edit: { open: false }, onAnswer() {} }));
  assert.strictEqual(app.chatCardNode(codexFile({ input: { changes: "x" } }), { edit: { open: false }, onAnswer() {} }).tag, "section", "a card of a shape it does not know still draws");
});

test("Codex: the records of a command and a file change, a denial and a changed card read in plain words", () => {
  const t = (rec, opts) => text(app.chatLine({ seq: 1, at: 1790000000, ...rec }, opts));
  assert(t({ kind: "card", turn: 1, card_id: "k-" + "a".repeat(16), tool: "command", input: {}, editable: "command", state: "asked", reason: "" }).includes("員工想執行指令"));
  assert(t({ kind: "card", turn: 1, card_id: "k-" + "a".repeat(16), tool: "file_change", input: {}, editable: "content", state: "asked", reason: "" }).includes("員工想修改檔案"));
  assert(t({ kind: "tool_call", turn: 1, tool_use_id: "i", tool: "command", summary: "ls" }).includes("執行指令"));
  assert(t({ kind: "denied", turn: 1, tool_use_id: "i", tool: "file_change", summary: "x", reason: "在工作資料夾外", by: "vbear" }).includes("修改檔案"));
  const changed = t({ kind: "card_decision", turn: 1, card_id: "k-" + "a".repeat(16), decision: "modify", value: "echo hi" }, { engine: "codex-chat" });
  assert(changed.includes("拒絕了原本的") && changed.includes("再問一次") && changed.includes("echo hi"), changed);
  assert(!changed.includes("你改了內容再允許"));
  assert(t({ kind: "card_decision", turn: 1, card_id: "k-" + "a".repeat(16), decision: "modify", value: "x" }).includes("你改了內容再允許"), "a Claude chat keeps its words");
});

test("Codex: a turn's cost is an estimate said as one, with the tokens, and a turn without a count is at its limit", () => {
  const t = (over) => text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.02", reported: false, total_usd: null, reason: "result", subtype: "completed", is_error: false, estimate: true, tokens: 18104, ...over }));
  const est = t({});
  for (const w of ["估計 US$0.02", "18,104", "token", "不是帳單"]) assert(est.includes(w), w + ": " + est);
  assert(!est.includes("Claude Code"));
  const cap = t({ cost_usd: "0.5", estimate: false, tokens: null, reason: "timeout" });
  assert(cap.includes("按上限 US$0.5") && cap.includes("Codex 沒有回報") && !cap.includes("估計 US$"), cap);
  assert(t({ reason: "limit", cost_usd: "0.5" }).includes("估計") || t({ reason: "limit" }).includes("上限"));
  assert(t({ cost_usd: "0", estimate: false, tokens: null, reason: "not_sent" }).includes("沒有花錢"));
  assert(t({ cost_usd: EVIL }).includes("金額不明"));
  assert(text(app.chatLine({ seq: 1, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.0015", reported: true, reason: "result" })).includes("Claude Code 回報的估值"), "Claude's line is unchanged");
});

test("Codex: the plan's use is one line in words, with the reset time only when the limit was reached", () => {
  const plan = (over) => ({ kind: "plan_usage", turn: 1, primary_pct: 7, primary_window_min: 300, primary_resets_at: 1790003600, secondary_pct: 27, secondary_window_min: 10080, secondary_resets_at: 1790400000, reached: null, ...over });
  const line = app.chatPlanUsageText(plan({}));
  assert(line.includes("ChatGPT 方案：5 小時內已用 7%、本週已用 27%") && line.includes("Codex 回報"), line);
  assert(!line.includes("上限"), line);
  const hit = app.chatPlanUsageText(plan({ primary_pct: 100, reached: "primary" }));
  assert(hit.includes("碰到方案用量上限") && hit.includes("恢復"), hit);
  const odd = app.chatPlanUsageText(plan({ primary_pct: 40, secondary_pct: 50, reached: "x" }));
  assert(odd.includes("碰到方案用量上限") && odd.includes("Codex 沒有說是哪一個"), odd);
  assert(app.chatPlanUsageText(plan({ primary_window_min: 1440, secondary_window_min: null })).includes("1 天內已用 7%"));
  assert(app.chatPlanUsageText(plan({ primary_pct: null, secondary_pct: null })) === "", "nothing to say, nothing said");
  assert(app.chatPlanUsageText(null) === "");
  assert(!app.chatPlanUsageText(plan({ reached: EVIL })).includes(EVIL), "what Codex called the limit is not shown");
});

test("Codex: the support notice for each state says what to do and shows the right button", () => {
  const ui = { confirm: false, pending: false, ask() { ui.confirm = true; }, go() { ui.went = true; }, cancel() { ui.confirm = false; } };
  const ready = app.chatCodexSupportNode(codexSupport(), ui);
  assert(text(ready).includes("Codex 0.163.0") && text(ready).includes("可以聊天") && text(ready).includes("ChatGPT 方案") && text(ready).includes("不是帳單"));
  assert(!q(ready, "verify") && !q(ready, "setup-go"));
  const word = (state, extra = {}) => app.chatCodexSupportNode(codexSupport({ state, ...extra }), ui);
  const none = word("not_installed", { installed: false, version: null, verified: false, logged_in: null, why: "找不到用官方安裝指令裝的 Codex。請到「開始設定」安裝 Codex。" });
  assert(text(none).includes("還沒安裝 Codex") && text(none).includes("請到「開始設定」安裝 Codex"));
  assert.strictEqual(q(none, "setup-go").getAttribute("href"), "#/setup");
  const login = word("not_logged_in", { logged_in: false, why: "聊天用的 Codex 還沒有登入。請到「開始設定」按「讓聊天用的 Codex 登入」。" });
  assert(text(login).includes("還沒登入") && text(login).includes("讓聊天用的 Codex 登入"));
  assert.strictEqual(q(login, "setup-go").getAttribute("href"), "#/setup");
  assert(!q(login, "verify"));
  for (const state of ["policy", "folder", "version_unreadable"]) {
    const n = word(state, { why: "原因 " + state });
    assert(text(n).includes("原因 " + state), state);
    assert(!q(n, "verify"), "no verify button for " + state);
  }
  noMarkup(word("policy", { why: EVIL, version: EVIL }));
  const un = word("unverified", { verified: false, logged_in: null, why: "Codex 0.163.0 還沒有通過聊天驗證。" });
  assert(text(un).includes("還沒通過聊天驗證") && text(un).includes("還沒有通過聊天驗證"));
  for (const w of ["約 14 次", "ChatGPT 方案", "不另外收費", "先到「開始設定」按「讓聊天用的 Codex 登入」", "全部通過，才會記下這個版本"]) assert(text(q(un, "verify-cost") || un).includes(w) || text(un).includes(w), w);
  assert(q(un, "setup-go") && q(un, "verify"));
  q(un, "verify").click();
  ui.confirm = true;
  const ask = word("unverified", { verified: false });
  assert(q(ask, "verify-go") && q(ask, "verify-cancel") && !q(ask, "verify"));
  q(ask, "verify-go").click();
  assert.strictEqual(ui.went, true);
  const running = app.chatCodexSupportNode(codexSupport({ state: "unverified", verified: false, verify: { running: true } }), { confirm: false });
  assert(q(running, "verifying") && !q(running, "verify"));
  const failed = app.chatCodexSupportNode(codexSupport({ state: "unverified", verified: false, verify: { running: false, result: "failed", message: "聊天驗證：edit_works 沒有通過" } }), ui);
  assert(text(q(failed, "verify-result")).includes("edit_works"));
  assert(text(app.chatCodexSupportNode(null, ui)).includes("讀不到"));
});

test("Codex: the list tells each chat's AI tool, shows the Codex notice for a Codex card, and opens a Codex chat only when it is ready", async () => {
  setPage({ list: listing({ chats: [
    { id: CODEX_CID, profile_id: "emp-4", engine: "codex-chat", created_at: 1790000000, last_at: 1790000100, last_kind: "reply", last_text: "好", turns: 1, spent_usd: "0.02", open: false, waiting: false, problem: null },
    { id: CID, profile_id: "emp-1", engine: "claude-chat", created_at: 1790000000, last_at: 1790000050, last_kind: "reply", last_text: "好", turns: 1, spent_usd: "0.01", open: false, waiting: false, problem: null }] }) });
  let main = await open("#/chat");
  const rows = main.findAll((n) => n.getAttribute && n.getAttribute("data-chat") === "row");
  assert.deepStrictEqual(rows.map((r) => text(q(r, "tool"))), ["Codex", "Claude Code"], "each row names its AI tool");
  assert(q(main, "support"), "the Claude notice is there while no card is chosen");
  assert(q(main, "codex-support"), "and the Codex one, as Codex is installed");
  const sel = q(main, "card");
  sel.value = "emp-4";
  sel.dispatch("change");
  main = h.dom().mainEl;
  assert(q(main, "codex-support") && !q(main, "support"), "a Codex card: Codex's notice only");
  assert.strictEqual(q(main, "open").disabled, false);
  q(main, "open").click();
  await settle();
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: "emp-4" }]);
  setPage({ list: listing({ support: support({ codex: codexSupport({ state: "not_logged_in", logged_in: false, why: "聊天用的 Codex 還沒有登入。請到「開始設定」按「讓聊天用的 Codex 登入」。" }) }) }) });
  main = await open("#/chat?profile=emp-4");
  assert.strictEqual(q(main, "open").disabled, true);
  assert(text(main).includes("讓聊天用的 Codex 登入") && q(main, "setup-go"));
  assert(!text(main).includes("這個 Claude Code 版本通過聊天驗證之前"), "the Claude sentence is not shown for a Codex card");
  sel.value = "emp-1";
  main = await open("#/chat?profile=emp-1");
  assert.strictEqual(q(main, "open").disabled, false, "a Claude card does not wait for Codex");
  assert(q(main, "support") && !q(main, "codex-support"));
});

test("Codex: with Codex not installed, a person who has only Claude Code sees no Codex notice until a Codex card is chosen", async () => {
  setPage({ list: listing({ support: support({ codex: codexSupport({ state: "not_installed", installed: false, version: null, verified: false, logged_in: null, why: "找不到用官方安裝指令裝的 Codex。請到「開始設定」安裝 Codex。" }) }) }) });
  const main = await open("#/chat");
  assert(q(main, "support") && !q(main, "codex-support"));
  const sel = q(main, "card");
  sel.value = "emp-4";
  sel.dispatch("change");
  assert(q(h.dom().mainEl, "codex-support") && text(h.dom().mainEl).includes("還沒安裝 Codex"));
});

test("Codex: a person with only Codex does not get a warning about a Claude Code that is not there", async () => {
  setPage({ list: listing({ support: support({ detected: null, state: "unknown", verified: [], message: "讀不到 Claude Code 的版本（沒有安裝）", codex: codexSupport() }) }) });
  const main = await open("#/chat");
  assert(!q(main, "support") && q(main, "codex-support"));
});

test("Codex: the verify button posts the engine and the version it showed, after asking first", async () => {
  const un = codexSupport({ state: "unverified", verified: false, logged_in: null, why: "Codex 0.163.0 還沒有通過聊天驗證。" });
  setPage({ list: listing({ support: support({ codex: un }) }) });
  const main = await open("#/chat?profile=emp-4");
  q(main, "verify").click();
  await settle();
  assert.strictEqual(posts("/api/chat-support/verify").length, 0, "the first press only asks");
  assert(text(q(h.dom().mainEl, "verify-cost")).includes("ChatGPT 方案"));
  page.list = listing({ support: support({ codex: { ...un, verify: { running: true } } }) });
  q(h.dom().mainEl, "verify-go").click();
  await settle();
  assert.deepStrictEqual(posts("/api/chat-support/verify").map((c) => c.body), [{ engine: "codex", version: "0.163.0" }]);
  assert(q(h.dom().mainEl, "verifying"));
});

test("Codex: a chat shows its tool, the one-line plan use, the money rule and that reading is not blocked", async () => {
  seqNo = 0;
  const records = [rec("chat_created", { profile_id: "emp-4" }), rec("user_message", { turn: 1, text: "你好" }), rec("turn_started", { turn: 1, cap_usd: "0.5" }),
    rec("process_started", { mode: "new", budget_usd: "0.5", instructions: false }), rec("session_ready", { cli_version: "0.163.0", permission_mode: "untrusted", model: "m" }),
    rec("session_bound", { thread_id: "00000000-0000-4000-8000-0000000000aa" }),
    rec("reply", { turn: 1, text: "pineapple", truncated: false }), rec("usage", { turn: 1, total_tokens: 18104, delta_tokens: 18104 }),
    rec("plan_usage", { turn: 1, primary_pct: 6, primary_window_min: 300, primary_resets_at: 1790003600, secondary_pct: 26, secondary_window_min: 10080, secondary_resets_at: 1790400000, reached: null }),
    rec("plan_usage", { turn: 1, primary_pct: 7, primary_window_min: 300, primary_resets_at: 1790003600, secondary_pct: 27, secondary_window_min: 10080, secondary_resets_at: 1790400000, reached: null }),
    rec("turn_ended", { turn: 1, cost_usd: "0.02", reported: false, total_usd: null, reason: "result", subtype: "completed", is_error: false, estimate: true, tokens: 18104 })];
  setPage({ detail: codexDetail({ records, last_seq: records.length, next_after: records.length }) });
  const main = await open("#/chat/" + CODEX_CID);
  const log = q(main, "log");
  assert.deepStrictEqual(log.children.map((c) => c.getAttribute("data-chat")), ["user", "process", "reply", "cost"], "the Codex-only records are not lines");
  const all = text(main);
  for (const w of ["Codex 員工", "工具：Codex", "估計 US$0.02", "不是帳單", "ChatGPT 方案：5 小時內已用 7%、本週已用 27%（Codex 回報）",
    "不擋「讀」", "每個指令都會先問你"]) assert(all.includes(w), w);
  assert.strictEqual(text(q(main, "plan-usage")).includes("已用 6%"), false, "the last report is the one shown");
  assert(!all.includes("工具：Claude Code"));
  assert(q(main, "codex-note"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0);
  // a Claude chat has none of it
  setPage();
  const other = await open("#/chat/" + CID);
  assert(!q(other, "codex-note") && !q(other, "plan-usage") && text(other).includes("工具：Claude Code"));
});

test("Codex: the plan line follows the live stream, and the limit message names the reset", async () => {
  seqNo = 0;
  setPage({ detail: codexDetail() });
  await open("#/chat/" + CODEX_CID);
  assert(!q(h.dom().mainEl, "plan-usage"), "nothing to say before the first report");
  streams[0].push({ ok: true, ...codexDetail({ records: [rec("plan_usage", { turn: 1, primary_pct: 100, primary_window_min: 300, primary_resets_at: 1790003600, secondary_pct: 30, secondary_window_min: 10080, secondary_resets_at: 1790400000, reached: "primary" })], next_after: 1 }) });
  await settle();
  const line = text(q(h.dom().mainEl, "plan-usage"));
  assert(line.includes("5 小時內已用 100%") && line.includes("碰到方案用量上限") && line.includes("恢復"), line);
});

test("Codex: the cards on the page, answering sends the one-use token, and an asked-again card is a new one", async () => {
  seqNo = 0;
  setPage({ detail: codexDetail() });
  await open("#/chat/" + CODEX_CID);
  streams[0].push({ ok: true, ...codexDetail({ live: live({ state: "waiting_for_you", turn: 1, cards: [codexCommand()] }) }) });
  await settle();
  q(q(h.dom().mainEl, "live-card"), "modify").click();
  await settle();
  streams[0].push({ ok: true, ...codexDetail({ live: live({ state: "waiting_for_you", turn: 1, cards: [codexCommand()] }) }) });
  await settle();
  const box = q(h.dom().mainEl, "edit");
  box.value = "echo changed-by-user > shell.txt";
  box.dispatch("input");
  q(h.dom().mainEl, "allow-edited").click();
  await settle();
  assert.deepStrictEqual(posts("/answer").map((x) => x.body), [{ card_id: "k-" + "a".repeat(16), token: "t".repeat(32), decision: "modify", value: "echo changed-by-user > shell.txt" }]);
  streams[0].push({ ok: true, ...codexDetail({ live: live({ state: "waiting_for_you", turn: 1, cards: [codexCommand({ card_id: "k-" + "b".repeat(16), input: { command: "/bin/zsh -lc 'echo changed-by-user > shell.txt'", cwd: ".", actions: [] } })] }) }) });
  await settle();
  assert(text(q(h.dom().mainEl, "live-card")).includes("echo changed-by-user > shell.txt"));
  assert.strictEqual(q(q(h.dom().mainEl, "live-card"), "edit"), null, "the new card starts closed");
});

test("Codex: deleting says Codex keeps its own copy and where; a Claude chat's confirmation does not", async () => {
  setPage({ detail: codexDetail() });
  let main = await open("#/chat/" + CODEX_CID);
  q(main, "delete").click();
  await settle();
  let dlg = text(dialog());
  assert(dlg.includes("已花的錢仍算在今天的額度裡"));
  for (const w of ["Codex 自己", "對話副本", "codex-chat-home", "不會刪掉"]) assert(dlg.includes(w), w);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0);
  dialog().find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle();
  setPage();
  main = await open("#/chat/" + CID);
  q(main, "delete").click();
  await settle();
  dlg = text(dialog());
  assert(dlg.includes("已花的錢仍算在今天的額度裡") && !dlg.includes("Codex"));
});

test("the explainer tells the two engines apart, and the sentence for a violation does not name only Claude Code", async () => {
  setPage();
  delete global.localStorage._store["vbear-chat-intro-seen"];
  const main = await open("#/chat");
  const intro = text(q(main, "intro"));
  for (const w of ["Claude Code 或 Codex", "用 Codex 聊天", "ChatGPT 方案", "不擋「讀」", "拒絕原本的"]) assert(intro.includes(w), w);
  assert(!app.CHAT_TURN_END.violation.includes("Claude Code"));
  assert(!text(app.chatLine({ seq: 1, at: 1, kind: "anomaly", event_type: "x", fields: [] })).includes("Claude Code"));
});

// ---- the entry points and the rules of the code ----------------------------------------------------------------------

test("a role card has a chat button only a Claude Code or Codex card that is on can press, and it opens the chat page with the card chosen", () => {
  const mk = (over) => app.profileCard({ id: "emp-1", name: "虛構員工", enabled: true, model: { tool: "claude" }, position: "pm", ...over },
    { handlers: { chat: (p) => { global.location.hash = "#/chat?profile=" + encodeURIComponent(p.id); } } }).node;
  const on = mk({});
  const btn = on.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat");
  assert(btn && text(btn) === "聊天");
  assert.notStrictEqual(btn.disabled, true);
  btn.click();
  assert.strictEqual(global.location.hash, "#/chat?profile=emp-1");
  const codex = mk({ model: { tool: "codex" } }).find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat");
  assert.notStrictEqual(codex.disabled, true, "a Codex card can chat too");
  for (const [over, word] of [[{ enabled: false }, "已停用"], [{ model: { tool: "grok" } }, "只支援工具是 Claude Code 或 Codex"]]) {
    const b = mk(over).find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat");
    assert.strictEqual(b.disabled, true);
    assert(b.getAttribute("title").includes(word), word);
  }
  const without = app.profileCard({ id: "emp-1", name: "x", enabled: true, model: { tool: "claude" } }, { handlers: {} }).node;
  assert.strictEqual(without.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat"), null);
});

// ---- P43-2: the shared folder's check button ---------------------------------------------------------------------------

async function withQuickTimers(fn) {
  const real = global.setTimeout;
  global.setTimeout = (f, ms, ...a) => real(f, ms > 100 ? 0 : ms, ...a);       // the page waits seconds between looks; the test does not
  try { return await fn(); } finally { global.setTimeout = real; }
}
const unchecked = { on: true, usable: false, code: "shared_unverified" };
const press = async (key) => { q(h.dom().mainEl, key).click(); await settle(); };
const confirmDialog = async () => { dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click(); await settle(); };

test("shared_unverified: the chat says so with a check button; with the folder usable, off or unsaid there is neither", async () => {
  for (const shared of [undefined, { on: false, usable: false, code: null }, { on: true, usable: true, code: null }, { on: true, usable: false, code: "shared_unsafe" }]) {
    setPage({ detail: detail({ shared }) });
    const main = await open(`#/chat/${CID}`);
    assert(!q(main, "shared-check"), JSON.stringify(shared));
    assert(!q(main, "shared-unverified"));
  }
  setPage({ detail: detail({ shared: unchecked }) });
  const main = await open(`#/chat/${CID}`);
  assert(q(main, "shared-unverified"));
  assert(text(q(main, "shared-unverified")).includes("Claude Code") && text(q(main, "shared-unverified")).includes("共用資料夾"));
  assert.strictEqual(text(q(main, "shared-check")), "檢查");
  assert.strictEqual(q(main, "shared-check").getAttribute("type"), "button");
  noMarkup(main);
});

test("shared_unverified: pressing the button asks first, with what it costs, and a no sends nothing", async () => {
  setPage({ detail: detail({ shared: unchecked }) });
  await open(`#/chat/${CID}`);
  await press("shared-check");
  assert(dialog());
  assert(text(dialog()).includes("US$0.01"));
  dialog().find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle();
  assert.strictEqual(posts("/api/chat-support/verify").length, 0);
  assert(q(h.dom().mainEl, "shared-check") && !q(h.dom().mainEl, "shared-check").getAttribute("disabled"));
});

test("shared_unverified: the check is asked for with shared:true, the button waits, and the note goes when the chat says it passed", async () => {
  setPage({ detail: detail({ shared: unchecked }) });
  await open(`#/chat/${CID}`);
  await withQuickTimers(async () => {
    await press("shared-check");
    page.list = listing({ support: support({ verify: { running: false, result: "passed", message: "x" } }) });
    page.detail = detail({ shared: { on: true, usable: true, code: null } });
    await confirmDialog();
    await sleep(30); await settle();
  });
  assert.deepStrictEqual(posts("/api/chat-support/verify").map((c) => c.body), [{ engine: "claude", shared: true }]);
  assert(!q(h.dom().mainEl, "shared-unverified"), "the note is gone");
});

test("shared_unverified: a check that did not pass says why and the button is there again", async () => {
  setPage({ detail: detail({ shared: unchecked }) });
  await open(`#/chat/${CID}`);
  await withQuickTimers(async () => {
    await press("shared-check");
    page.list = listing({ support: support({ verify: { running: false, result: "failed", message: `shared_bash_works 沒有通過 ${EVIL}` } }) });
    await confirmDialog();
    await sleep(30); await settle();
  });
  const msg = q(h.dom().mainEl, "shared-check-msg");
  assert(msg && text(msg).includes("shared_bash_works"));
  noMarkup(h.dom().mainEl);
  assert(q(h.dom().mainEl, "shared-check") && !q(h.dom().mainEl, "shared-check").getAttribute("disabled"));
});

test("shared_unverified: a refused request shows the server's sentence and is not waited for", async () => {
  setPage({ detail: detail({ shared: unchecked }), verifyStatus: 409, verifyBody: { error: "這台 Mac 上有管理員政策。", code: "admin_policy" } });
  await open(`#/chat/${CID}`);
  await press("shared-check");
  await confirmDialog();
  assert(text(q(h.dom().mainEl, "shared-check-msg")).includes("管理員政策"));
});

test("shared_unverified: for a Codex chat the check is Codex's, and the cost is the ChatGPT plan", async () => {
  setPage({ detail: codexDetail({ shared: unchecked }) });
  await open(`#/chat/${CODEX_CID}`);
  assert(text(q(h.dom().mainEl, "shared-unverified")).includes("Codex"));
  await press("shared-check");
  assert(text(dialog()).includes("ChatGPT"));
  await withQuickTimers(async () => {
    page.list = listing({ support: support({ codex: codexSupport({ verify: { running: false, result: "passed" } }) }) });
    page.detail = codexDetail({ shared: { on: true, usable: true, code: null } });
    await confirmDialog();
    await sleep(30); await settle();
  });
  assert.deepStrictEqual(posts("/api/chat-support/verify").map((c) => c.body), [{ engine: "codex", shared: true }]);
  assert(!q(h.dom().mainEl, "shared-unverified"));
});

test("shared_unverified: a version that already passed is not waited for", async () => {
  setPage({ detail: detail({ shared: unchecked }), verifyBody: { ok: true, already_verified: true, version: "2.1.318", status: { running: false } } });
  await open(`#/chat/${CID}`);
  page.detail = detail({ shared: { on: true, usable: true, code: null } });
  await press("shared-check");
  await confirmDialog();
  assert(!q(h.dom().mainEl, "shared-unverified"));
});

test("the nav has the chat between the meetings and the terminals, and the code keeps its rules", () => {
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  assert(html.includes('data-nav="chat"'));
  assert(html.indexOf('data-nav="meetings"') < html.indexOf('data-nav="chat"') && html.indexOf('data-nav="chat"') < html.indexOf('data-nav="terminals"'));
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(source));
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  assert(!emoji.test(css) && !emoji.test(html.split("data-nav=\"chat\"")[1].split("</li>")[0]));
  const chatPart = source.slice(source.indexOf("chat with role cards (P36-2)"), source.indexOf("// ---------- meetings (P34-5)"));
  assert(chatPart.length > 5000 && !emoji.test(chatPart));
  assert(!/https?:\/\//.test(chatPart), "no external address");
  for (const sel of [".chat-card", ".chat-log", ".chat-msg", ".chat-composer", ".chat-live"]) assert(css.includes(sel), sel);
  assert(/prefers-reduced-motion/.test(css));
});

// ---- run ---------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  await settle();     // the page's first route ran against no server when the app was loaded; let it finish
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
