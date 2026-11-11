// P38-8, the first CEO: the step after 「開始使用」 (#/ceo) that makes the first role card, the chat it opens with the opening
// sentence only put in the box, the way the start-up page leads to it, and the lobby's two doors (make one / chat with it).
// The real web/app.js on a synthetic DOM, fetch answered by the test. Nothing here runs a tool: the server's answers are fixtures.
// Run: node tests/frontend/first_ceo.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const attr = (n, k) => n.getAttribute && n.getAttribute(k);
const byAttr = (root, k, v) => root.find((n) => attr(n, k) === v);
const allByAttr = (root, k, v) => root.findAll((n) => attr(n, k) === v);
const ceo = (root, v) => byAttr(root, "data-ceo", v);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const CARD_ID = "prof-0123456789ab";
const CHAT_ID = "c-0123456789abcdef";
const OPENING = "你好，請先問我三個問題，了解我想做什麼。";
const INSTRUCTIONS = "你是我的 CEO（執行長）。請用一般人聽得懂的話跟我說話。";
const plan = (over = {}) => ({ ok: true, needed: true, can_create: true, go: null, reason: "", tool: "claude", tool_name: "Claude Code", name: "CEO",
  position: "planner", launch_mode: "safe", instructions: INSTRUCTIONS, opening: OPENING, chat_ready: null, chat_note: "", ...over });
const profile = (over = {}) => ({ id: CARD_ID, name: "CEO", position: "planner", model: { tool: "claude", model_id: "" }, launch_mode: "safe", enabled: true,
  equipped_skill_ids: [], permission_intents: {}, ...over });
const chatCards = (over = {}) => [{ id: CARD_ID, name: "CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true, ...over }];
const support = () => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" }, verify: { running: false }, money: "x" });
const chatRowOf = (over = {}) => ({ id: CHAT_ID, profile_id: CARD_ID, engine: "claude-chat", created_at: 1, last_at: 1, last_kind: null, last_text: "", turns: 0, spent_usd: "0",
  open: false, waiting: false, problem: null, ...over });
const detail = () => ({ ok: true, chat: { id: CHAT_ID, profile_id: CARD_ID, created_at: 1790000000 },
  card: { id: CARD_ID, name: "CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { plan: plan(), profiles: [], chats: [], config: { setup_done: true }, createError: null, chatError: null, tools: [], ...over };
  FETCH_LOG.length = 0;
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true });
    if (p === "/api/first-ceo") return page.planStatus ? jsonResponse({ ok: false, error: "x" }, false, page.planStatus) : jsonResponse(page.plan);
    if (p === "/api/agent-profiles" && method === "POST") {
      if (page.createError) return jsonResponse({ ok: false, error: page.createError }, false, 400);
      page.profiles = [...page.profiles, profile({ name: body.name, model: body.model })];
      return jsonResponse({ ok: true, profile: page.profiles[page.profiles.length - 1] });
    }
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: page.profiles });
    if (p === "/api/config" && method === "POST") { Object.assign(page.config, body); return jsonResponse({ ok: true, config: page.config }); }
    if (p === "/api/config") return jsonResponse({ ok: true, config: page.config });
    if (p === "/api/setup/tools" && method === "GET") return jsonResponse({ ok: true, any_ready: true, setup_done: page.config.setup_done === true,
      tools: [{ id: "claude", name: "Claude Code", short: "Claude Code", blurb: "x", hidden: false, installed: true, version: "2.1.318", install_problem: "", login_by: "status",
        login: "logged_in", can_mark: false, marked_at: null, state: "ready", ready: true, login_regions: [] }] });
    if (p === "/api/setup/daily-limit") return jsonResponse({ ok: true, daily_usd: 3, choices: [1, 3, 10] });
    if (p === "/api/setup/settle") return jsonResponse({ ok: true, setup_done: true, setup_notice: false, upgraded: false });
    if (p === "/api/chats" && method === "POST") {
      if (page.chatError) return jsonResponse({ ok: false, error: page.chatError }, false, 409);
      return jsonResponse({ ok: true, chat: { id: CHAT_ID, profile_id: body.profile_id, created_at: 1 } }, true, 201);
    }
    if (p === "/api/chats") return jsonResponse({ ok: true, chats: page.chats, more: 0, cards: chatCards(), support: { ...support(), ...(page.supportExtra || {}) }, limits: { per_turn_usd: "0.5", daily_usd: "3" },
      ledger: { spent_usd: "0", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "" });
    if (p === `/api/chats/${CHAT_ID}` && method === "GET") return jsonResponse(detail());
    if (p === `/api/chats/${CHAT_ID}/stream`) return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    return null;
  });
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = (fn) => { page.tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const posts = (suffix) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0].endsWith(suffix));
const click = async (node) => { node.dispatch("click"); await settle(); };
const typeInto = (node, value) => { node.value = value; node.dispatch("input"); };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- the step ---------------------------------------------------------------------------------------------------

test("with no card to chat with, #/ceo shows the step: a name, a plain sentence about the job, the ready tool, safe mode, one button", async () => {
  setPage();
  const main = await open("#/ceo");
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "建立你的 CEO");
  const name = ceo(main, "name"), about = ceo(main, "instructions");
  assert.strictEqual(name.value, "CEO");
  assert.strictEqual(about.value, INSTRUCTIONS);
  assert.strictEqual(about.tag, "textarea");
  assert(/Claude Code/.test(text(ceo(main, "tool"))) && /可以聊天了/.test(text(ceo(main, "tool"))));       // (P48-3) 「已就緒」 became 「可以聊天了」: said only when a chat can start
  assert(/每件事先問我/.test(text(ceo(main, "mode"))) && /先問你/.test(text(ceo(main, "mode"))), "safe mode, said in words");       // (P47-4) the new name of the mode
  const go = ceo(main, "create");
  assert.strictEqual(go.tag, "button");
  assert(/建立/.test(text(go)));
  assert.strictEqual(go.disabled, false);
  assert(/不花錢|不會花錢/.test(text(ceo(main, "cost"))) && /送出/.test(text(ceo(main, "cost"))), "creating costs nothing, a message does");
  assert.strictEqual(posts("/api/agent-profiles").length + posts("/api/chats").length, 0, "opening the page makes nothing");
  assert.strictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).length, 0);
});

test("the page promises no more than there is: it chats and plans, and work is handed out only by the chief of staff's proposal that the person confirms", async () => {
  setPage();
  const main = await open("#/ceo");
  const said = text(main);
  assert(/整理成計畫|整理成一份計畫|整理想法/.test(said));
  // (P47-4) it used to say the assignment feature was not there; it is (the chief of staff), and the page says where and that it only proposes
  assert(/請幕僚長安排/.test(text(ceo(main, "limits"))) && /分配|分給/.test(text(ceo(main, "limits"))) && /提議/.test(text(ceo(main, "limits"))) && /你確認/.test(text(ceo(main, "limits"))), text(ceo(main, "limits")));
  assert(!/還沒有/.test(text(ceo(main, "limits"))));
  for (const bad of ["終端機", "CLI", "sandbox", "token", "agent", "orchestrator"]) assert(!said.includes(bad), bad);
});

test("pressing the button makes one safe-mode card on the ready tool with the words in the boxes, notes it, opens the chat; nothing is sent", async () => {
  setPage();
  const main = await open("#/ceo");
  await click(ceo(main, "create"));
  const made = posts("/api/agent-profiles");
  assert.strictEqual(made.length, 1);
  assert.deepStrictEqual(made[0].body, { name: "CEO", position: "planner", instructions: INSTRUCTIONS, launch_mode: "safe", model: { tool: "claude", model_id: "" } });
  assert.deepStrictEqual(posts("/api/config").map((c) => c.body), [{ first_ceo_id: CARD_ID }]);
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: CARD_ID }]);
  assert.strictEqual(global.location.hash, `#/chat/${CHAT_ID}`);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST" && /\/(messages|answer)$/.test(c.url)).length, 0, "no message, nothing allowed");
});

test("the person can change the name and the words before it is made", async () => {
  setPage();
  const main = await open("#/ceo");
  typeInto(ceo(main, "name"), "小明的 CEO");
  typeInto(ceo(main, "instructions"), "請說白話，先問我想做什麼。");
  await click(ceo(main, "create"));
  const body = posts("/api/agent-profiles")[0].body;
  assert.strictEqual(body.name, "小明的 CEO");
  assert.strictEqual(body.instructions, "請說白話，先問我想做什麼。");
  assert.strictEqual(body.launch_mode, "safe", "the mode is not a box: it is always safe here");
  assert.strictEqual(body.model.tool, "claude");
});

test("a blank name makes nothing and says so", async () => {
  setPage();
  const main = await open("#/ceo");
  typeInto(ceo(main, "name"), "   ");
  await click(ceo(main, "create"));
  assert.strictEqual(posts("/api/agent-profiles").length, 0);
  assert(/名字/.test(text(ceo(main, "error"))));
  assert.strictEqual(ceo(main, "create").disabled, false, "it can be tried again");
});

test("the card can be made on the ready Codex when Claude Code is not ready, and the page says Codex chats on its own login", async () => {
  setPage({ plan: plan({ tool: "codex", tool_name: "Codex", chat_ready: false,
    chat_note: "Codex 聊天要用另一份登入：先到「開始設定」按「讓聊天用的 Codex 登入」。" }) });
  const main = await open("#/ceo");
  assert(/Codex/.test(text(ceo(main, "tool"))));
  assert(/聊天用的 Codex 登入/.test(text(ceo(main, "chat-note"))));
  assert(attr(byAttr(main, "data-ceo", "chat-note").find((n) => n.tag === "a"), "href") === "#/setup");
  await click(ceo(main, "create"));
  assert.strictEqual(posts("/api/agent-profiles")[0].body.model.tool, "codex");
  assert.strictEqual(posts("/api/agent-profiles")[0].body.launch_mode, "safe");
});

test("AGY: the card can be made on a ready AGY (the last choice), and the page says the talk goes to Google and the AGY skills are used", async () => {
  setPage({ plan: plan({ tool: "agy", tool_name: "AGY", chat_ready: false,
    chat_note: "AGY 聊天要先通過驗證：到聊天頁按「驗證聊天」（用你的 Google 方案）。" }), supportExtra: { agy: { state: "unverified" } } });
  const main = await open("#/ceo");
  // the tool is there, but its chat is not checked yet: the page does not say 「已就緒」 (fix47), it says the check comes first
  assert(/AGY/.test(text(ceo(main, "tool"))) && /先做一次安全檢查/.test(text(ceo(main, "tool"))) && !/已就緒|可以聊天了/.test(text(ceo(main, "tool"))));
  const note = text(ceo(main, "agy-note"));
  assert(note.includes("送到 Google") && note.includes("AGY 技能") && note.includes("通過驗證"), note);
  assert(/驗證聊天/.test(text(ceo(main, "chat-note"))));
  await click(ceo(main, "create"));
  assert.strictEqual(posts("/api/agent-profiles")[0].body.model.tool, "agy");
  assert.strictEqual(posts("/api/agent-profiles")[0].body.launch_mode, "safe");
  const other = await open("#/ceo");
  setPage();
  const claude = await open("#/ceo");
  assert.strictEqual(byAttr(claude, "data-ceo", "agy-note"), null, "only an AGY CEO gets the line");
});

test("a card that could not be made says why and makes no chat", async () => {
  setPage({ createError: "角色卡已達上限 500 筆" });
  const main = await open("#/ceo");
  await click(ceo(main, "create"));
  assert(/角色卡已達上限/.test(text(ceo(main, "error"))));
  assert.strictEqual(posts("/api/chats").length, 0);
  assert.strictEqual(posts("/api/config").length, 0);
  assert.strictEqual(global.location.hash, "#/ceo");
  assert.strictEqual(ceo(main, "create").disabled, false);
});

test("a card made but a chat that cannot open yet (not verified, not logged in…) leads to the chat page with the card chosen, and keeps the note", async () => {
  setPage({ chatError: "這個 Claude Code 版本還沒通過聊天驗證。" });
  const main = await open("#/ceo");
  await click(ceo(main, "create"));
  assert.strictEqual(posts("/api/agent-profiles").length, 1);
  assert.deepStrictEqual(posts("/api/config").map((c) => c.body), [{ first_ceo_id: CARD_ID }], "the lobby will still offer it");
  assert.strictEqual(global.location.hash, `#/chat?profile=${CARD_ID}`);
  const t = h.dom().toastEl ? text(h.dom().toastEl) : "";
  assert(/員工/.test(t) || t === "", "the toast, if the harness keeps it");
});

test("the second press while it is being made does nothing", async () => {
  setPage();
  const main = await open("#/ceo");
  const go = ceo(main, "create");
  go.dispatch("click"); go.dispatch("click");
  await settle();
  assert.strictEqual(posts("/api/agent-profiles").length, 1);
});

test("a person who already has a card to chat with is not shown the step: #/ceo goes to the lobby", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null, tool_name: null }) });
  const main = await open("#/ceo");
  assert.strictEqual(global.location.hash, "#/");
  assert.strictEqual(ceo(main, "create"), null);
  assert.strictEqual(ceo(main, "name"), null);
});

test("with no ready tool the page does not offer to make anything and leads back to the start-up", async () => {
  setPage({ plan: plan({ can_create: false, go: "setup", tool: null, tool_name: null, reason: "目前沒有已經就緒、而且能聊天的 AI 工具。" }) });
  const main = await open("#/ceo");
  assert.strictEqual(ceo(main, "create"), null);
  const back = ceo(main, "setup-go");
  assert.strictEqual(attr(back, "href"), "#/setup");
  assert(/AI 工具/.test(text(main)));
});

test("a plan that cannot be read says so and makes nothing", async () => {
  setPage({ planStatus: 503 });
  const main = await open("#/ceo");
  assert.strictEqual(ceo(main, "create"), null);
  assert(/讀不到/.test(text(main)));
});

// ---- the chat that opens ----------------------------------------------------------------------------------------

test("the chat opens with the opening sentence in the box, changeable, not sent, once", async () => {
  setPage();
  let main = await open("#/ceo");
  await click(ceo(main, "create"));
  main = await open(`#/chat/${CHAT_ID}`);
  const input = byAttr(main, "data-chat", "input");
  assert.strictEqual(input.value, OPENING, "put in the box");
  assert(/可以改/.test(text(ceo(main, "opening-note"))) && /送出/.test(text(ceo(main, "opening-note"))));
  assert.strictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).length, 0, "nothing sent by opening the page");
  assert.strictEqual(byAttr(main, "data-chat", "send").disabled, false, "the person's own press is what sends");
  // a message is sent only by the button, with what is in the box then
  typeInto(input, "我想做一個賣手作餅乾的網站");
  await click(byAttr(main, "data-chat", "send"));
  const sent = FETCH_LOG.filter((c) => /\/messages$/.test(c.url));
  assert.strictEqual(sent.length, 1);
  assert.strictEqual(sent[0].body.text, "我想做一個賣手作餅乾的網站");
  // the next time the chat is opened the box is empty
  main = await open(`#/chat/${CHAT_ID}`);
  assert.strictEqual(byAttr(main, "data-chat", "input").value, "");
  assert.strictEqual(ceo(main, "opening-note"), null);
});

test("a chat nobody prepared an opening for has an empty box", async () => {
  setPage();
  const main = await open(`#/chat/${CHAT_ID}`);
  assert.strictEqual(byAttr(main, "data-chat", "input").value, "");
});

// ---- the way in from the start-up page --------------------------------------------------------------------------

test("「開始使用」 on the start-up page leads to the step when there is no card to chat with, else to the lobby", async () => {
  setPage({ config: { setup_done: false } });
  let main = await open("#/setup");
  await click(byAttr(main, "data-setup", "leave"));
  assert.strictEqual(global.location.hash, "#/ceo");
  assert.deepStrictEqual(posts("/api/config").map((c) => c.body), [{ setup_done: true }]);
  setPage({ config: { setup_done: false }, plan: plan({ needed: false, can_create: false, tool: null }) });
  main = await open("#/setup");
  await click(byAttr(main, "data-setup", "leave"));
  assert.strictEqual(global.location.hash, "#/");
  setPage({ config: { setup_done: false }, planStatus: 503 });
  main = await open("#/setup");
  await click(byAttr(main, "data-setup", "leave"));
  assert.strictEqual(global.location.hash, "#/", "a plan that cannot be read never traps the person");
});

test("P48-3: the AI the person picked is not ready (another one is): 「下一步：建立 CEO」 still opens the step, which says why and offers nothing to make", async () => {
  const REASON = "你選的 Codex 還沒準備好，回開始設定把它準備好，或換一家。";
  setPage({ config: { setup_done: false }, plan: plan({ can_create: false, go: "setup", tool: null, tool_name: null, reason: REASON }) });
  global.localStorage.setItem("vbear-setup-pick", "codex");
  let main = await open("#/setup");
  await click(byAttr(main, "data-setup", "leave"));
  assert(FETCH_LOG.some((c) => c.url === "/api/first-ceo?tool=codex"), "the plan was asked for the picked AI");
  assert.strictEqual(global.location.hash, "#/ceo", "not the home page: the person is told why");
  main = await open("#/ceo");
  assert(text(main).includes(REASON));
  assert.strictEqual(ceo(main, "create"), null, "nothing can be made on another AI");
  assert.strictEqual(attr(ceo(main, "setup-go"), "href"), "#/setup");
  global.localStorage._store = {};
  // a person who has a card to chat with is still sent to the home page, and so is a plan that could not be read
  setPage({ config: { setup_done: false }, plan: plan({ needed: false, can_create: false, tool: null }) });
  main = await open("#/setup");
  await click(byAttr(main, "data-setup", "leave"));
  assert.strictEqual(global.location.hash, "#/");
});

// ---- the lobby ---------------------------------------------------------------------------------------------------

// P47-2: the lobby's two doors (make a CEO / chat with the CEO that was made, once) are replaced by the new home page: the three steps for a person
// with no employee (step 2 is 建立 CEO), and for a person who has a CEO the box 「想做什麼？跟 CEO 說」, which sends only on the person's own press.
// What the doors did on pressing 聊聊看 (open the chat, the opening sentence in its box) is the work of 「建立 CEO，開始聊」 now (P47-4).
const homeOf = (main, key) => byAttr(main, "data-home", key);
test("home: a person with no card to chat with is offered to make a CEO on the home page itself (P52-1: the first-run block, no longer step 2 and a link to #/ceo); one who has a card is not", async () => {
  setPage();
  let main = await open("#/");
  assert(homeOf(main, "first-run"), "the first-run block is on the home page");
  assert.strictEqual(homeOf(main, "first-steps"), null);
  assert.strictEqual(main.findAll((n) => n.tag === "a" && attr(n, "href") === "#/ceo").length, 0, "there is no way to another page: it is made here");
  assert.strictEqual(homeOf(main, "first-ceo-create"), null, "nothing to make before the person chose an AI");
  await click(byAttr(main, "data-setup-pick-go", "claude"));
  main = h.dom().mainEl;
  assert(FETCH_LOG.some((c) => c.url === "/api/first-ceo?tool=claude"), "the plan was read for the chosen AI");
  const make = homeOf(main, "first-ceo-create");
  assert(make && /建立 CEO，開始聊/.test(text(make)), "and the button that makes it");
  assert.strictEqual(posts("/api/chats").length + posts("/api/agent-profiles").length, 0, "showing it makes nothing");
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()] });
  main = await open("#/");
  assert.strictEqual(homeOf(main, "first-run"), null, "a person who has a card is not shown the first run");
  assert(homeOf(main, "ask"), "and has the box for the CEO");
  global.localStorage._store = {};
  setPage({ planStatus: 503 });
  main = await open("#/");
  assert(homeOf(main, "first-run"), "a plan that cannot be read does not remove the block: the page asks the start-up page's tool list, not the plan");
});

test("home: a CEO who was made and not yet talked to: the box says to say the first words; showing it opens nothing; the press opens the chat and sends the typed words", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], config: { setup_done: true, first_ceo_id: CARD_ID } });
  let main = await open("#/");
  const ask = homeOf(main, "ask");
  assert(ask && /第一句話/.test(text(ask)));
  assert.strictEqual(posts("/api/chats").length, 0, "showing it opens nothing");
  assert.strictEqual(posts("/api/config").length, 0, "and puts nothing away");
  const box = byAttr(main, "data-home", "ask-input");
  typeInto(box, "幫我整理下載資料夾");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0, "typing sends nothing");
  await click(byAttr(main, "data-home", "ask-send"));
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: CARD_ID }]);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).map((c) => c.body), [{ text: "幫我整理下載資料夾" }]);
  assert.strictEqual(global.location.hash, `#/chat/${CHAT_ID}`);
});

test("home: the box re-uses the empty chat the first step already opened (no second chat is made)", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], chats: [chatRowOf()], config: { setup_done: true, first_ceo_id: CARD_ID } });
  const main = await open("#/");
  typeInto(byAttr(main, "data-home", "ask-input"), "你好");
  await click(byAttr(main, "data-home", "ask-send"));
  assert.strictEqual(posts("/api/chats").length, 0, "the empty chat is used, not another one made");
  assert.strictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).length, 1);
  assert.strictEqual(global.location.hash, `#/chat/${CHAT_ID}`);
});

test("home: no first-words line once the person has talked with the CEO; a CEO whose card is gone or stopped is not the one to talk to", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], chats: [chatRowOf({ turns: 2 })], config: { setup_done: true, first_ceo_id: CARD_ID } });
  let main = await open("#/");
  assert(!/第一句話/.test(text(homeOf(main, "ask"))), "they already talked");
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile({ enabled: false })], config: { setup_done: true, first_ceo_id: CARD_ID } });
  main = await open("#/");
  assert(!byAttr(main, "data-home", "ask-input"), "a stopped card is not sent to");
  assert(/先建立一位 CEO/.test(text(homeOf(main, "ask"))));
});

test("home: a chat that cannot open sends the person to the chat page with the CEO chosen, and nothing is sent", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], chatError: "還沒通過聊天驗證",
    config: { setup_done: true, first_ceo_id: CARD_ID } });
  const main = await open("#/");
  typeInto(byAttr(main, "data-home", "ask-input"), "你好");
  await click(byAttr(main, "data-home", "ask-send"));
  assert.strictEqual(global.location.hash, `#/chat?profile=${CARD_ID}`);
  assert.strictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).length, 0);
});

// ---- source -----------------------------------------------------------------------------------------------------

test("source: the first-CEO block is built with el(), no innerHTML, no emoji, no outside resource, no message sent by the step", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const start = src.indexOf("// ---------- the first CEO");
  const end = src.indexOf("// ---------- chat with role cards");
  assert(start > 0 && end > start, "the block is there");
  const block = src.slice(start, end);
  assert(block.length > 2000);
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(block));
  assert(!/\p{Extended_Pictographic}/u.test(block));
  assert(!/https?:\/\//.test(block));
  assert(!/\/messages/.test(block), "the step never posts a message");
  assert(!/\/answer/.test(block));
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
  for (const sel of [".ceo-form", ".ceo-door"]) assert(css.includes(sel), sel);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
