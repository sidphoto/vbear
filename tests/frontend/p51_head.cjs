// P51-3 (v0.24.0 極簡對話 2, ADR 0016): the head of the chat page is one row (the name, the state word and 「⋯」), and the line about the work, the AI tool, that
// everything asks first and which company the words go to is kept, one step smaller and grey (it says where the words go and what is asked: it is not removed).
// The page that prepares a chat is the same 720px column with the same reason and button; the list of chats is plain rows, no card frame, with the same words and links.
// The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model.
// Run: node tests/frontend/p51_head.cjs   (exit code 0 = pass)
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
const CSS = fs.readFileSync(path.join(root, "style.css"), "utf8");
const SOURCE = fs.readFileSync(path.join(root, "app.js"), "utf8");
global.document.querySelector = () => null;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-chat") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-chat") === key);
const isOpen = (d) => !!d && (d.hasAttribute("open") || d.open === true);
const CID = "c-0123456789abcdef";
const KID = "k-" + "a".repeat(16);

// ---- fixtures ------------------------------------------------------------------------------------------------------
let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const cardOf = (over = {}) => ({ card_id: KID, token: "t".repeat(32), turn: 1, tool: "Bash", input: { command: "ls -a", description: "list" },
  editable: "command", reason: "每個指令都要你允許才會執行", expires_in: 290, ...over });
const support = (over = {}) => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" }, verify: { running: false }, money: "x", ...over });
const cardsList = () => [
  { id: "emp-1", name: "虛構員工", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
];
const listing = (over = {}) => ({ ok: true, chats: [], more: 0, cards: cardsList(), support: support(), limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const live = (over = {}) => ({ state: "idle", turn: null, partial: "", partial_truncated: false, model: "haiku", cards: [], ...over });
const detail = (over = {}) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" }, card: cardsList()[0],
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });

let page;
const streams = [];
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), detail: detail(), ...over };
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
    if (p === "/api/groups") return jsonResponse({ groups: page.groups || [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return streamResponse();
    if (m && !m[2] && method === "GET") return jsonResponse(page.detail);
    return null;
  });
  FETCH_LOG.length = 0;
}
function streamResponse() {
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
const withDetail = (records, over = {}) => setPage({ detail: detail({ records, last_seq: records.length, next_after: records.length, ...over }) });
const dataOf = (n) => n.getAttribute("data-chat");
const inFold = (n, stop) => { for (let p = n.parentNode; p && p !== stop; p = p.parentNode) if (p.tag === "details") return true; return false; };
const part = (marker) => { const at = CSS.indexOf(marker); assert(at > 0, "the " + marker + " part of the css"); return CSS.slice(at); };

// ---- P51-3: the head, the preparation page, the list ---------------------------------------------------------------

test("the head is one row: the name (a smaller h1), the state word and 「⋯」; the line about the work, the tool, asking first and which company stays, smaller and grey", async () => {
  seqNo = 0;
  setPage({ detail: detail({ live: live() }) });
  const main = await open("#/chat/" + CID);
  const page1 = q(main, "page");
  assert(page1 && page1.hasClass("chat-page"), "the page is one column");
  const head = main.find((n) => n.hasClass && n.hasClass("chat-head"));
  const top = head.find((n) => n.hasClass && n.hasClass("chat-head-top"));
  assert(top.find((n) => n.tag === "h1") && q(top, "more"), "the name and 「⋯」 are in one row");
  const title = top.find((n) => n.hasClass && n.hasClass("chat-title"));
  assert(title.find((n) => n.hasClass && n.hasClass("badge")), "the state word is beside the name");
  const line = q(main, "line");
  assert(!line.find((n) => n.hasClass && n.hasClass("badge")), "the line under it is only the facts");
  assert(text(line).includes("每件事先問你") && text(line).includes("對話會送到 Anthropic") && text(line).includes("Claude Code"));
  assert(q(main, "details") && q(main, "details").tag === "details", "「詳細資訊」 is still there");
  const p = part("/* P51-3");
  assert(/\.chat-head h1\s*\{[^}]*font-size:\s*(1\d|2[0-2])px/.test(p), "a smaller h1");
  assert(/\.chat-line\s*\{[^}]*color:\s*var\(--ink-3\)/.test(p), "grey");
});

test("the page that prepares a chat is the same column, with the same reason and the same one button", async () => {
  setPage({ list: listing({ cards: [{ ...cardsList()[0], can_chat: false, reason: "這張角色卡已停用，啟用之後才能聊天。" }] }) });
  const main = await open("#/chat?profile=emp-1");
  const pageNode = q(main, "page");
  assert(pageNode && pageNode.hasClass("chat-page"));
  assert(text(q(main, "prep-reason")).includes("已停用") && q(main, "prep-action"));
});

test("the list of chats is plain rows (no card frame), each with the name, the last time, and a dot when a card waits; the words and links are unchanged", async () => {
  const chats = [{ id: CID, profile_id: "emp-1", name: "虛構員工", engine: "claude-chat", created_at: 1790000000, last_at: 1790000100, turns: 2, spent_usd: "0.03", open: false, waiting: true, last_text: "你好", last_kind: "user" },
    { id: "c-fedcba9876543210", profile_id: "emp-1", name: "虛構員工", engine: "claude-chat", created_at: 1789000000, last_at: 1789000100, turns: 1, spent_usd: "0.01", open: false, waiting: false, last_text: "好", last_kind: "reply" }];
  setPage({ list: listing({ chats }) });
  const main = await open("#/chat");
  const rows = qa(main, "row");
  assert.strictEqual(rows.length, 2);
  for (const r of rows) {
    assert(!r.hasClass("card"), "no card frame");
    const a = r.find((n) => n.tag === "a");
    assert.strictEqual(a.getAttribute("href"), "#/chat/" + r.getAttribute("data-chat-id"));
  }
  assert(rows[0].find((n) => n.hasClass && n.hasClass("chat-wait-dot")), "a dot for the one that waits");
  assert(!rows[1].find((n) => n.hasClass && n.hasClass("chat-wait-dot")));
  assert(text(rows[0]).includes("等你回覆卡片") && text(rows[0]).includes("2 回合") && text(rows[0]).includes("你：你好"), text(rows[0]));
  const p = part("/* P51-3");
  assert(/\.chat-list-box \.mt-row\b[^{]*\{[^}]*border:\s*0/.test(p) || /\.chat-list-box \.mt-row[^{]*\{[^}]*border-width:\s*0/.test(p), "rows without the card frame");
  assert(/\.chat-wait-dot\s*\{[^}]*border-radius:\s*50%/.test(p));
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
