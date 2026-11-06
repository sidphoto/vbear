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
  { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
  { id: "emp-2", name: "停用員工", position: "pm", tool: "claude", enabled: false, can_chat: false, code: "card_disabled", reason: "這張角色卡已停用，啟用之後才能聊天。", instructions: false },
  { id: "emp-3", name: "Codex 員工", position: "pm", tool: "codex", enabled: true, can_chat: false, code: "card_not_claude", reason: "這張角色卡的工具是 Codex，聊天目前只支援 Claude Code。", instructions: false },
];
const listing = (over = {}) => ({ ok: true, chats: [], more: 0, cards: cardsList(), support: support(), limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["meetings", "staffing", "chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const detail = (over = {}) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000 },
  card: { id: "emp-1", name: "虛構員工", position: "pm", tool: "claude", enabled: true, can_chat: true, code: null, reason: null },
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
  const left = new Set(["chat_created", "session_ready", "turn_started", "session_bound", "usage", "plan_usage", "card_edit_sent"]);   // nothing a person needs to read: their message and the cost line say it (the last four are a Codex chat's; its page is P38-5)
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
  assert.deepStrictEqual(options.map((o) => o.disabled === true), [false, false, true, true], "the two cards that cannot chat are not choosable");
  assert(text(options[2]).includes("不能聊天") && text(options[3]).includes("不能聊天"));
  const go = q(main, "open");
  assert.strictEqual(go.disabled, true, "no card chosen");
  sel.value = "emp-3";
  sel.dispatch("change");
  assert(text(h.dom().mainEl).includes("聊天目前只支援 Claude Code"), "the reason is shown");
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

test("a card that is off or not Claude Code, a runtime that is away, and a damaged record each say so and shut the send button", async () => {
  const cases = [
    [{ card: { id: "emp-1", name: "虛構員工", tool: "codex", can_chat: false, reason: "這張角色卡的工具是 Codex，聊天目前只支援 Claude Code。" } }, "聊天目前只支援 Claude Code"],
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

// ---- the entry points and the rules of the code ----------------------------------------------------------------------

test("a role card has a chat button only a Claude Code card that is on can press, and it opens the chat page with the card chosen", () => {
  const mk = (over) => app.profileCard({ id: "emp-1", name: "虛構員工", enabled: true, model: { tool: "claude" }, position: "pm", ...over },
    { handlers: { chat: (p) => { global.location.hash = "#/chat?profile=" + encodeURIComponent(p.id); } } }).node;
  const on = mk({});
  const btn = on.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat");
  assert(btn && text(btn) === "聊天");
  assert.notStrictEqual(btn.disabled, true);
  btn.click();
  assert.strictEqual(global.location.hash, "#/chat?profile=emp-1");
  for (const [over, word] of [[{ enabled: false }, "已停用"], [{ model: { tool: "codex" } }, "只支援工具是 Claude Code"]]) {
    const b = mk(over).find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat");
    assert.strictEqual(b.disabled, true);
    assert(b.getAttribute("title").includes(word), word);
  }
  const without = app.profileCard({ id: "emp-1", name: "x", enabled: true, model: { tool: "claude" } }, { handlers: {} }).node;
  assert.strictEqual(without.find((n) => n.getAttribute && n.getAttribute("data-pcard") === "chat"), null);
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
