// P58 (v0.25.3 員工知道自己的名字, ADR 0020): the "employee goes online" line of the chat page does NOT say whether the employee was told its name (the chat record gained no field, so v0.25.2
// can still read a chat started in v0.25.3); the changed-notice does name the name and the position. The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test.
// Nothing here runs a model.
// Run: node tests/frontend/p58_chat.cjs   (exit code 0 = pass)
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


// ---- P58: the line that goes with a process start says nothing about names ---------------------------------------------------------------------------------------------

const processLine = async (extra) => {
  seqNo = 0;
  withDetail([rec("user_message", { turn: 1, text: "你好" }), rec("process_started", { mode: "new", budget_usd: "0.5", instructions: true, ...extra }),
    rec("reply", { turn: 1, text: "好", truncated: false })]);
  const main = await open("#/chat/" + CID);
  const lines = qa(main, "process");
  assert.strictEqual(lines.length, 1, "one process line");
  return lines[0];
};

test("the process line is as it was in v0.25.2 and says nothing about names", async () => {
  const words = text(await processLine({}));
  assert(words.includes("員工上線，帶著員工自己寫的指示"), words);
  assert(!words.includes("名字"), words);
});

test("even a record with an identity field (there is none) does not make the line talk about names", async () => {
  for (const v of [true, false, "yes", 1, null]) {
    const words = text(await processLine({ identity: v }));
    assert(!words.includes("名字"), String(v) + ": " + words);
  }
});

test("a resumed process keeps its own sentence", async () => {
  const words = text(await processLine({ mode: "resume", instructions: false }));
  assert(words.includes("員工接續上次的對話上線，沒有帶指示（員工設定上沒有自己寫的）"), words);
});

test("the notice that the chat is not as it was started names the name and the position", async () => {
  seqNo = 0;
  withDetail([rec("process_started", { mode: "new", budget_usd: "0.5", instructions: false })], { memory: { on: true, count: 0, readable: true, changed: true, started_with_memory: true } });
  const main = await open("#/chat/" + CID);
  const box = main.find((n) => n.getAttribute && n.getAttribute("data-memory") === "chat-changed");
  assert(box, "the notice");
  assert(text(box).includes("名字、職位、固定指示") && text(box).includes("請開新聊天"), text(box));
});

test("the source: the page has no helper for the name on the process line, and the new notice words have no innerHTML and no emoji", () => {
  assert(!SOURCE.includes("chatIdentityWords"), "no helper that reads an identity field of the record");
  const at = SOURCE.indexOf("const MEMORY_CHANGED_TEXT");
  assert(at > 0);
  const mine = SOURCE.slice(at, SOURCE.indexOf("function memoryChangedNote", at));
  assert(mine.length > 100);
  assert(!/innerHTML|insertAdjacentHTML|outerHTML|localStorage|sessionStorage|https?:\/\//.test(mine));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u.test(mine), "no emoji");
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
