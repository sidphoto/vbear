// P42-2: the least the pages need of the memory switches: the memory page lists who takes memory along and switches a card (a
// Codex card is switched on only after the person agreed that it goes to OpenAI), and a chat page says in one line whether this
// employee has the memory with them. The full memory page (editing, clearing, exporting, the 「記住」 button) is P42-3's. The real
// web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model.
// Run: node tests/frontend/memory_boundary.cjs   (exit code 0 = pass)
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
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-memory") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-memory") === key);
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const EVIL = "<img src=x onerror=alert(1)>";
const CID = "c-0123456789abcdef";

const WHERE = "員工開新程序時，記憶會跟著送給 Anthropic（Claude Code 的員工）或 OpenAI（Codex 的員工）。不要寫密碼、帳號、卡號；VBear 看到像這樣的內容會擋下。";
const cardRow = (over = {}) => ({ profile_id: "emp-1", name: "文案小編", tool: "claude", company: "Anthropic", can_chat: true, on: true, ...over });
const CARDS = () => [cardRow(), cardRow({ profile_id: "emp-4", name: "會計師", tool: "codex", company: "OpenAI", on: false }),
  cardRow({ profile_id: "emp-3", name: "Grok 員工", tool: "grok", company: null, can_chat: false, on: false })];
const view = (over = {}) => ({ ok: true, entries: [], used: { count: 0, chars: 0, max_count: 50, max_chars: 4000 }, readable: true,
  where_text: WHERE, problem: null, cards: CARDS(), ...over });
const detail = (memory) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" },
  card: { id: "emp-1", name: "文案小編", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, memory });
const listing = () => ({ ok: true, chats: [], more: 0, cards: [], support: { state: "verified", verify: { running: false }, policy: { ok: true, found: [], problems: [], reason: "" }, money: "x" },
  limits: { per_turn_usd: "0.5", daily_usd: "3" }, ledger: null, ledger_error: null, problems: [], scratch: "" });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { memory: view(), cardsStatus: 200, cardsBody: null, detail: detail({ on: true, count: 3, readable: true }), ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/memory" && method === "GET") return jsonResponse(page.memory);
    if (p === "/api/memory/cards" && method === "POST") {
      const body = JSON.parse(opts.body);
      if (page.cardsStatus >= 400) return jsonResponse(page.cardsBody, false, page.cardsStatus);
      page.memory = view({ cards: page.memory.cards.map((c) => (c.profile_id === body.profile_id ? { ...c, on: body.on } : c)) });
      return jsonResponse({ ok: true, profile_id: body.profile_id, on: body.on });
    }
    if (p === "/api/chats" && method === "GET") return jsonResponse(listing());
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
const cardPosts = () => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === "/api/memory/cards");
const rowOf = (main, id) => qa(main, "card").find((n) => n.getAttribute("data-profile-id") === id);

test("the memory page lists who takes memory along, the company it goes to, and what cannot use it", async () => {
  setPage();
  const main = await open("#/memory");
  assert.strictEqual(qa(main, "card").length, 3);
  const claude = rowOf(main, "emp-1"), codex = rowOf(main, "emp-4"), grok = rowOf(main, "emp-3");
  assert(text(claude).includes("文案小編") && text(claude).includes("Anthropic"));
  assert(text(codex).includes("會計師") && text(codex).includes("OpenAI"));
  assert.strictEqual(q(claude, "card-switch").checked, true);
  assert.strictEqual(q(codex, "card-switch").checked, false);
  assert(text(grok).includes("這位員工的 AI 工具還不能聊天，用不到記憶"));
  assert(!q(grok, "card-switch"), "no switch for a card that cannot chat");
  assert(text(q(main, "terminal")).includes("在終端機（完整模式）出發時不帶記憶"));
});

test("switching a Claude Code card off sends exactly the card and off, and the page is read again", async () => {
  setPage();
  const main = await open("#/memory");
  const sw = q(rowOf(main, "emp-1"), "card-switch");
  sw.checked = false;
  sw.dispatch("change");
  await settle(80);
  assert.deepStrictEqual(cardPosts().map((c) => c.body), [{ profile_id: "emp-1", on: false }]);
  assert.strictEqual(q(rowOf(h.dom().mainEl, "emp-1"), "card-switch").checked, false);
});

test("a Codex card is switched on only after the person agreed that memory goes to OpenAI", async () => {
  setPage();
  const main = await open("#/memory");
  const sw = q(rowOf(main, "emp-4"), "card-switch");
  sw.checked = true;
  sw.dispatch("change");
  await settle(20);
  const dlg = dialog();
  assert(dlg, "a question first");
  assert(text(dlg).includes("OpenAI"));
  assert.strictEqual(cardPosts().length, 0, "nothing is sent before the answer");
  dlg.find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle(40);
  assert.strictEqual(cardPosts().length, 0, "cancel sends nothing");
  assert.strictEqual(q(rowOf(h.dom().mainEl, "emp-4"), "card-switch").checked, false, "and the switch goes back");
  const again = q(rowOf(h.dom().mainEl, "emp-4"), "card-switch");
  again.checked = true;
  again.dispatch("change");
  await settle(20);
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.deepStrictEqual(cardPosts().map((c) => c.body), [{ profile_id: "emp-4", on: true, confirm_company: true }]);
  assert.strictEqual(q(rowOf(h.dom().mainEl, "emp-4"), "card-switch").checked, true);
});

test("switching a Codex card off asks nothing", async () => {
  setPage({ memory: view({ cards: [cardRow({ profile_id: "emp-4", name: "會計師", tool: "codex", company: "OpenAI", on: true })] }) });
  const main = await open("#/memory");
  const sw = q(rowOf(main, "emp-4"), "card-switch");
  sw.checked = false;
  sw.dispatch("change");
  await settle(80);
  assert(!dialog());
  assert.deepStrictEqual(cardPosts().map((c) => c.body), [{ profile_id: "emp-4", on: false }]);
});

test("a refusal of the server is shown and the switch shows what the server has", async () => {
  setPage({ cardsStatus: 404, cardsBody: { error: "找不到這位員工。", code: "not_found" } });
  const main = await open("#/memory");
  const sw = q(rowOf(main, "emp-1"), "card-switch");
  sw.checked = false;
  sw.dispatch("change");
  await settle(80);
  assert(text(h.dom().toastEl).includes("找不到這位員工"));
  assert.strictEqual(q(rowOf(h.dom().mainEl, "emp-1"), "card-switch").checked, true);
});

test("a name that holds markup stays text", async () => {
  setPage({ memory: view({ cards: [cardRow({ name: EVIL })] }) });
  const main = await open("#/memory");
  assert(text(rowOf(main, "emp-1")).includes("<img"));
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
});

test("a chat page says in one line whether this employee has the memory with them", async () => {
  setPage({ detail: detail({ on: true, count: 3, readable: true }) });
  let main = await open("#/chat/" + CID);
  const line = main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "memory");
  assert(line, "the line is there");
  assert(text(line).includes("這位員工帶著你的記憶（3 條）"));
  assert(line.find((n) => n.tag === "a" && n.getAttribute("href") === "#/memory"), "it leads to the memory page");
  setPage({ detail: detail({ on: false, count: 0, readable: true }) });
  main = await open("#/chat/" + CID);
  assert(text(main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "memory")).includes("這位員工不帶記憶"));
  setPage({ detail: detail({ on: false, count: 0, readable: false }) });
  main = await open("#/chat/" + CID);
  assert(text(main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "memory")).includes("記憶讀不到，這次沒有帶"));
  setPage({ detail: detail(undefined) });
  main = await open("#/chat/" + CID);
  assert(!main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "memory"), "an older server says nothing");
});

test("the new code keeps the rules of the page", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const part = source.slice(source.indexOf("// ---------- memory (P42-1"), source.indexOf("// ---------- meetings (P34-5)"));
  assert(/\/api\/memory\/cards/.test(part) && /confirm_company/.test(part));
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  assert(!emoji.test(part));
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(part));
  assert(!/https?:\/\//.test(part));
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
