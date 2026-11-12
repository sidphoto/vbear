// P42-6: a chat page that tells the person when the memory (or the employee's own instructions) are not what the chat works with.
// Claude Code keeps the system prompt a session was started with, so a change reaches only a NEW chat: the page says so in plain
// words and offers 「開新聊天」 (the same employee). The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser
// test. Nothing here runs a model, and nothing is sent to an employee: the only request the button makes is the one that opens a chat.
// Run: node tests/frontend/memory_changed.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
global.document.querySelector = () => null;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const attr = (n, k) => n && n.getAttribute && n.getAttribute(k);
const CID = "c-0123456789abcdef";
const NEW_CID = "c-fedcba9876543210";
const EVIL = "<img src=x onerror=alert(1)>";

const detail = (memory, over = {}) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" },
  card: { id: "emp-1", name: "文案小編", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, memory, ...over });
const mem = (over = {}) => ({ on: true, count: 3, readable: true, changed: false, started_with_memory: true, ...over });
const listing = () => ({ ok: true, chats: [], more: 0, cards: [], support: { state: "verified", verify: { running: false }, policy: { ok: true, found: [], problems: [], reason: "" }, money: "x" },
  limits: { per_turn_usd: "0.5", daily_usd: "3" }, ledger: null, ledger_error: null, problems: [], scratch: "" });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { detail: detail(mem()), createStatus: 201, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(listing());
    if (p === "/api/chats" && method === "POST") {
      return page.createStatus < 400 ? jsonResponse({ chat: { id: NEW_CID, profile_id: JSON.parse(opts.body).profile_id, created_at: 1790000100, engine: "claude-chat" } }, true, 201)
        : jsonResponse({ error: "同時聊天的員工太多。", code: "limit" }, false, page.createStatus);
    }
    if (p === `/api/chats/${CID}` && method === "GET") return jsonResponse(page.detail);
    if (p === `/api/chats/${CID}/stream`) return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
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
const changedBox = (main) => main.find((n) => attr(n, "data-memory") === "chat-changed");
const newChatButton = (main) => main.find((n) => n.tag === "button" && attr(n, "data-memory") === "new-chat");
const posts = () => FETCH_LOG.filter((c) => c.method === "POST");

test("a chat whose memory and instructions are as they were says nothing and has no button", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  assert(main.find((n) => attr(n, "data-memory") === "chat-state"), "the one line about the memory is there");
  assert.strictEqual(changedBox(main), null);
  assert.strictEqual(newChatButton(main), null);
});

test("a chat that is not as it was started says so in plain words and offers a new chat, and does not promise the next message", async () => {
  setPage({ detail: detail(mem({ changed: true })) });
  const main = await open("#/chat/" + CID);
  const box = changedBox(main);
  assert(box, "the notice is there");
  assert(text(box).includes("你改過記憶（或這位員工的名字、職位、固定指示），這個聊天還是用開始時的內容。要用新的，請開新聊天。"));
  assert(!text(box).includes("收不回來"), "the chat started with the memory and still has it on: that sentence is for a card switched off");
  assert(!/下一句|下一則|馬上|立刻/.test(text(box)), "no promise that the next message has it");
  assert(newChatButton(main), "the button");
  assert.strictEqual(text(newChatButton(main)), "開新聊天");
});

test("a card switched off after the chat started with the memory says that what was sent cannot be taken back", async () => {
  setPage({ detail: detail(mem({ on: false, count: 0, changed: true, started_with_memory: true })) });
  const main = await open("#/chat/" + CID);
  const box = changedBox(main);
  assert(text(box).includes("這個聊天開始時已經帶著記憶，已送出的內容收不回來。"));
  assert(text(box).includes("開新聊天"));
  assert(text(main.find((n) => attr(n, "data-memory") === "chat-state")).includes("這位員工不帶記憶"), "the one line still says how it is now");
});

test("a chat that started without the memory and has it now does not say that anything was sent", async () => {
  setPage({ detail: detail(mem({ changed: true, started_with_memory: false })) });
  const main = await open("#/chat/" + CID);
  assert(changedBox(main));
  assert(!text(changedBox(main)).includes("收不回來"));
});

test("the button opens a chat with the same employee and goes to it, and sends nothing else", async () => {
  setPage({ detail: detail(mem({ changed: true })) });
  const main = await open("#/chat/" + CID);
  newChatButton(main).click();
  await settle(60);
  assert.deepStrictEqual(posts().map((c) => [c.url.split("?")[0], c.body]), [["/api/chats", { profile_id: "emp-1" }]]);
  assert.strictEqual(global.location.hash, "#/chat/" + NEW_CID);
});

test("a refusal to open the chat is said and the page stays", async () => {
  setPage({ detail: detail(mem({ changed: true })), createStatus: 409 });
  const main = await open("#/chat/" + CID);
  newChatButton(main).click();
  await settle(60);
  assert(text(h.dom().toastEl).includes("同時聊天的員工太多"));
  assert.strictEqual(global.location.hash, "#/chat/" + CID);
});

test("an older server sends neither field: no notice", async () => {
  setPage({ detail: detail({ on: true, count: 3, readable: true }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(changedBox(main), null);
});

test("a chat a group opened has no notice and no button (a new chat would not be in the group)", async () => {
  setPage({ detail: detail(mem({ changed: true }), { group: { id: "g-0123456789ab", name: "虛構群組" } }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(changedBox(main), null);
  assert.strictEqual(newChatButton(main), null);
});

test("an employee's name that holds markup stays text and the notice sets no markup", async () => {
  setPage({ detail: detail(mem({ changed: true }), { card: { id: "emp-1", name: EVIL, position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null } }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const part = source.slice(source.indexOf("function memoryChatLine"), source.indexOf("async function viewMemory"));
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(part));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(part));
});

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
