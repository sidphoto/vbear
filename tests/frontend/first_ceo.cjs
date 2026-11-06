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
    if (p === "/api/chats") return jsonResponse({ ok: true, chats: page.chats, more: 0, cards: chatCards(), support: support(), limits: { per_turn_usd: "0.5", daily_usd: "3" },
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
  assert(/Claude Code/.test(text(ceo(main, "tool"))) && /已就緒/.test(text(ceo(main, "tool"))));
  assert(/安全模式/.test(text(ceo(main, "mode"))) && /先問你/.test(text(ceo(main, "mode"))), "safe mode, said in words");
  const go = ceo(main, "create");
  assert.strictEqual(go.tag, "button");
  assert(/建立/.test(text(go)));
  assert.strictEqual(go.disabled, false);
  assert(/不花錢|不會花錢/.test(text(ceo(main, "cost"))) && /送出/.test(text(ceo(main, "cost"))), "creating costs nothing, a message does");
  assert.strictEqual(posts("/api/agent-profiles").length + posts("/api/chats").length, 0, "opening the page makes nothing");
  assert.strictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).length, 0);
});

test("the page promises no more than there is: it chats and plans, it does not hand out work yet", async () => {
  setPage();
  const main = await open("#/ceo");
  const said = text(main);
  assert(/整理成計畫|整理成一份計畫|整理想法/.test(said));
  assert(/還沒有/.test(text(ceo(main, "limits"))) && /分派|分給/.test(text(ceo(main, "limits"))), text(ceo(main, "limits")));
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
  assert(/CEO/.test(t) || t === "", "the toast, if the harness keeps it");
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

// ---- the lobby ---------------------------------------------------------------------------------------------------

test("lobby: a person with no card to chat with is offered to make a CEO; one who has a card is not", async () => {
  setPage();
  let main = await open("#/");
  const door = ceo(main, "create-invite");
  assert(door, "the door is on the lobby");
  assert(/CEO/.test(text(door)));
  assert.strictEqual(attr(door.find((n) => n.tag === "a"), "href"), "#/ceo");
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }) });
  main = await open("#/");
  assert.strictEqual(ceo(main, "create-invite"), null);
  setPage({ plan: plan({ can_create: false, go: "setup", tool: null }) });
  main = await open("#/");
  assert.strictEqual(ceo(main, "create-invite"), null, "no ready tool: the start-up's job, not a door that leads nowhere");
  setPage({ planStatus: 503 });
  main = await open("#/");
  assert.strictEqual(ceo(main, "create-invite"), null);
});

test("lobby: once the CEO is made it is offered once: a button opens the chat with the opening in the box, and the offer is put away", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], config: { setup_done: true, first_ceo_id: CARD_ID } });
  let main = await open("#/");
  const door = ceo(main, "chat-invite");
  assert(door);
  assert(/跟你的 CEO 聊聊/.test(text(door)));
  assert.strictEqual(posts("/api/chats").length, 0, "showing it opens nothing");
  await click(ceo(main, "chat-go"));
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: CARD_ID }]);
  assert.strictEqual(global.location.hash, `#/chat/${CHAT_ID}`);
  assert.deepStrictEqual(posts("/api/config").map((c) => c.body), [{ first_ceo_id: "" }]);
  main = await open(`#/chat/${CHAT_ID}`);
  assert.strictEqual(byAttr(main, "data-chat", "input").value, OPENING);
  assert.strictEqual(FETCH_LOG.filter((c) => /\/messages$/.test(c.url)).length, 0);
  main = await open("#/");
  assert.strictEqual(ceo(main, "chat-invite"), null, "shown once");
});

test("lobby: the offer re-uses the empty chat the first step already opened, and can be put away without opening anything", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], chats: [chatRowOf()],
    config: { setup_done: true, first_ceo_id: CARD_ID } });
  let main = await open("#/");
  await click(ceo(main, "chat-go"));
  assert.strictEqual(posts("/api/chats").length, 0, "the empty chat is opened, not another one made");
  assert.strictEqual(global.location.hash, `#/chat/${CHAT_ID}`);
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], config: { setup_done: true, first_ceo_id: CARD_ID } });
  main = await open("#/");
  await click(ceo(main, "chat-dismiss"));
  assert.strictEqual(posts("/api/chats").length, 0);
  assert.deepStrictEqual(posts("/api/config").map((c) => c.body), [{ first_ceo_id: "" }]);
  assert.strictEqual(ceo(main, "chat-invite"), null);
});

test("lobby: no offer when the person has already talked with that CEO, when the card is gone, or when it cannot chat", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], chats: [chatRowOf({ turns: 2 })],
    config: { setup_done: true, first_ceo_id: CARD_ID } });
  let main = await open("#/");
  assert.strictEqual(ceo(main, "chat-invite"), null);
  assert.deepStrictEqual(posts("/api/config").map((c) => c.body), [{ first_ceo_id: "" }], "and it is not offered again");
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [], config: { setup_done: true, first_ceo_id: CARD_ID } });
  main = await open("#/");
  assert.strictEqual(ceo(main, "chat-invite"), null);
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile({ enabled: false })], config: { setup_done: true, first_ceo_id: CARD_ID } });
  main = await open("#/");
  assert.strictEqual(ceo(main, "chat-invite"), null);
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile({ model: { tool: "grok", model_id: "" } })], config: { setup_done: true, first_ceo_id: CARD_ID } });
  main = await open("#/");
  assert.strictEqual(ceo(main, "chat-invite"), null);
});

test("lobby: a chat that cannot open sends the person to the chat page with the CEO chosen", async () => {
  setPage({ plan: plan({ needed: false, can_create: false, tool: null }), profiles: [profile()], chatError: "還沒通過聊天驗證",
    config: { setup_done: true, first_ceo_id: CARD_ID } });
  const main = await open("#/");
  await click(ceo(main, "chat-go"));
  assert.strictEqual(global.location.hash, `#/chat?profile=${CARD_ID}`);
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
