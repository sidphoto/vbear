// P51-1 (v0.24.0 極簡對話 2, ADR 0016): the chat page reads like text. What the employee says has no frame; what you say is a soft bubble; the tool, result,
// auto-allowed, cost and process lines that follow one another are one folded line (a closed <details>) with the true counts and no money; a card that waits, a
// decision, a refusal, an error and an odd message are never folded. The folding is only a display: every record is still drawn, in order, with its data-seq and
// data-chat, and a record that arrives later joins the open group without closing it. The time stays in the page and shows on hover, on focus and (with no mouse) always.
// Guards 18a (what a group may hold) and 18d (no money on the summary line) are checked on the page here and on the source in tests/test_autonomy_guard.py.
// The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model.
// Run: node tests/frontend/p51_chat.cjs   (exit code 0 = pass)
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

// ---- P51-1: the folded line ----------------------------------------------------------------------------------------

test("18a: tool, result, auto, cost, process and process-end that follow one another are one closed fold; the words said stay outside and in order", async () => {
  seqNo = 0;
  const records = [rec("user_message", { turn: 1, text: "你好" }), rec("process_started", { mode: "new", budget_usd: "0.5", instructions: true }),
    rec("tool_call", { turn: 1, tool_use_id: "t1", tool: "Read", summary: "a.txt" }), rec("tool_result", { turn: 1, tool_use_id: "t1", tool: "Read", is_error: false, text: "x", truncated: false }),
    rec("tool_call", { turn: 1, tool_use_id: "t2", tool: "Bash", summary: "ls" }), rec("auto_allowed", { turn: 1, tool_use_id: "t3", tool: "Read", summary: "b", reason: "folder" }),
    rec("reply", { turn: 1, text: "做好了", truncated: false }),
    rec("turn_ended", { turn: 1, cost_usd: "0.0015", reported: true, total_usd: 0.0015, reason: "result", subtype: "success", is_error: false })];
  withDetail(records);
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  assert.deepStrictEqual(log.children.map(dataOf), ["user", "quiet-item", "reply", "quiet-item"]);
  const groups = qa(main, "quiet-group");
  assert.strictEqual(groups.length, 2);
  for (const g of groups) { assert.strictEqual(g.tag, "details"); assert(!isOpen(g), "closed at first"); assert.strictEqual(g.find((n) => n.tag === "summary").getAttribute("data-chat"), "quiet-summary"); }
  assert.deepStrictEqual(groups[0].find((n) => n.getAttribute && n.getAttribute("data-chat") === "quiet-list").children.map(dataOf), ["process", "tool", "result", "tool", "auto"]);
  assert.deepStrictEqual(groups[1].find((n) => n.getAttribute && n.getAttribute("data-chat") === "quiet-list").children.map(dataOf), ["cost"]);
  assert.strictEqual(text(groups[0].find((n) => n.tag === "summary")), "員工上線 1 次・用了 2 次工具・工具回了 1 筆結果・自動允許 1 次・細節");
  assert.strictEqual(text(groups[1].find((n) => n.tag === "summary")), "1 回合結算・細節");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0);
});

test("nothing is lost by folding: every record the page draws is in the page with its own data-seq and data-chat, in the order it came", async () => {
  seqNo = 0;
  const records = [rec("user_message", { turn: 1, text: "a" }), rec("tool_call", { turn: 1, tool_use_id: "t1", tool: "Bash", summary: "ls" }),
    rec("tool_result", { turn: 1, tool_use_id: "t1", tool: "Bash", is_error: true, text: "no", truncated: false }), rec("card", { turn: 1, card_id: KID, tool: "Bash", input: {}, editable: "command", state: "asked", reason: "" }),
    rec("card_decision", { turn: 1, card_id: KID, decision: "deny", value: null }), rec("denied", { turn: 1, tool_use_id: "t9", tool: "Write", summary: "x", reason: "outside", by: "vbear" }),
    rec("tool_call", { turn: 1, tool_use_id: "t4", tool: "Read", summary: "z" }), rec("anomaly", { event_type: "weird", fields: [] }), rec("error", { turn: 1, message: "壞了" }),
    rec("reply", { turn: 1, text: "b", truncated: false }), rec("turn_ended", { turn: 1, cost_usd: "0.1", reported: true, total_usd: 0.1, reason: "result", subtype: "success", is_error: false })];
  withDetail(records);
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  const drawn = log.findAll((n) => n.getAttribute && n.getAttribute("data-seq") !== null);
  assert.deepStrictEqual(drawn.map((n) => [n.getAttribute("data-seq"), dataOf(n)]), records.map((r) => [String(r.seq), { user_message: "user", tool_call: "tool", tool_result: "result", card: "card", card_decision: "decision", denied: "denied", anomaly: "anomaly", error: "error", reply: "reply", turn_ended: "cost" }[r.kind]]));
});

test("18a: a card that asks, its decision, a refusal, an error, an odd message, the person's words and the employee's words are never in a fold; a failed tool result is counted on the line", async () => {
  seqNo = 0;
  const records = [rec("user_message", { turn: 1, text: "a" }), rec("tool_call", { turn: 1, tool_use_id: "t1", tool: "Bash", summary: "ls" }),
    rec("tool_result", { turn: 1, tool_use_id: "t1", tool: "Bash", is_error: true, text: "no", truncated: false }),
    rec("card", { turn: 1, card_id: KID, tool: "Bash", input: {}, editable: "command", state: "asked", reason: "" }), rec("card_decision", { turn: 1, card_id: KID, decision: "allow", value: null }),
    rec("denied", { turn: 1, tool_use_id: "t9", tool: "Write", summary: "x", reason: "outside", by: "vbear" }), rec("anomaly", { event_type: "weird", fields: [] }),
    rec("error", { turn: 1, message: "壞了" }), rec("reply", { turn: 1, text: "b", truncated: false })];
  withDetail(records, { live: live({ state: "waiting_for_you", turn: 1, cards: [cardOf()] }) });
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  for (const key of ["user", "card", "decision", "denied", "anomaly", "error", "reply"]) {
    const n = q(log, key);
    assert(n, key + " is drawn");
    assert(!inFold(n, log), key + " is outside every fold");
  }
  assert(q(main, "live-card") && !inFold(q(main, "live-card"), main), "the card that waits is outside every fold");
  const sum = text(q(main, "quiet-summary"));
  assert(sum.includes("工具回了 1 筆結果（1 筆失敗）"), sum);
  for (const g of qa(main, "quiet-group")) for (const n of g.findAll((x) => x.getAttribute && x.getAttribute("data-chat") && x.tag === "li")) assert(["tool", "result", "auto", "cost", "process", "process-end"].includes(dataOf(n)), "a fold holds only the quiet kinds: " + dataOf(n));
});

test("a turn that was stopped, hit a limit or went wrong, and a process that ended for an unknown reason, say so in the open; one that ended well is in the fold", async () => {
  seqNo = 0;
  const records = [rec("process_started", { mode: "new", budget_usd: "0.5", instructions: true }),
    rec("turn_ended", { turn: 1, cost_usd: "0.01", reported: true, total_usd: 0.01, reason: "result", subtype: "success", is_error: false }),
    rec("turn_ended", { turn: 2, cost_usd: "0.5", reported: false, total_usd: 0.5, reason: "stopped", subtype: "x", is_error: true }),
    rec("turn_ended", { turn: 3, cost_usd: "0.2", reported: true, total_usd: 0.2, reason: "limit", subtype: "x", is_error: true }),
    rec("process_ended", { reason: "你按了停止", returncode: 0 }),
    rec("process_ended", { reason: "交人工處理：無法確認程序已結束", returncode: null })];
  withDetail(records);
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  assert.deepStrictEqual(log.children.map(dataOf), ["quiet-item", "cost", "cost", "quiet-item", "process-end"]);
  const open1 = log.children.filter((c) => dataOf(c) === "cost");
  assert(text(open1[0]).includes("你按了停止") && text(open1[1]).includes("用量到了這回合的上限"));
  assert(text(log.children[4]).includes("交人工處理"));
  assert.strictEqual(text(qa(main, "quiet-summary")[0]), "員工上線 1 次・1 回合結算・細節");
  assert.strictEqual(text(qa(main, "quiet-summary")[1]), "程序結束 1 次・細節");
});

test("18d: the summary line of a fold has no money; the money of each turn is still in the page inside the fold", async () => {
  seqNo = 0;
  const records = [rec("process_started", { mode: "new", budget_usd: "0.5", instructions: true }),
    rec("turn_ended", { turn: 1, cost_usd: "0.0123", reported: true, total_usd: 0.0123, reason: "result", subtype: "success", is_error: false }),
    rec("turn_ended", { turn: 2, cost_usd: "0.0456", reported: false, total_usd: 0.04, reason: "result", subtype: "success", is_error: false })];
  withDetail(records);
  const main = await open("#/chat/" + CID);
  const sum = text(q(main, "quiet-summary"));
  assert.strictEqual(sum, "員工上線 1 次・2 回合結算・細節");
  assert(!/US\$|\$|\d\.\d/.test(sum), "no amount on the line: " + sum);
  assert(text(q(main, "quiet-group")).includes("US$0.0123") && text(q(main, "quiet-group")).includes("US$0.0456"), "the amounts are inside");
  assert.strictEqual(app.chatQuietSummary({ tool: 3, auto: 1 }), "用了 3 次工具・自動允許 1 次・細節");
  assert.strictEqual(app.chatQuietSummary({}), "細節");
});

test("a record that arrives later joins the open fold without closing it; a spoken line ends the group and the next quiet record starts a new one", async () => {
  seqNo = 0;
  const first = [rec("user_message", { turn: 1, text: "a" }), rec("tool_call", { turn: 1, tool_use_id: "t1", tool: "Read", summary: "a" })];
  withDetail(first);
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  const g = q(main, "quiet-group");
  g.setAttribute("open", "");
  const sumNode = g.find((n) => n.tag === "summary");
  assert.strictEqual(text(sumNode), "用了 1 次工具・細節");
  streams[0].push({ ok: true, ...detail({ records: [rec("tool_call", { turn: 1, tool_use_id: "t2", tool: "Bash", summary: "ls" }), rec("auto_allowed", { turn: 1, tool_use_id: "t3", tool: "Read", summary: "b", reason: "folder" })], next_after: 4 }) });
  await settle();
  assert.strictEqual(qa(main, "quiet-group").length, 1, "the same fold");
  assert.strictEqual(q(main, "quiet-group"), g, "the node was not redrawn");
  assert(isOpen(g), "still open");
  assert.strictEqual(text(g.find((n) => n.tag === "summary")), "用了 2 次工具・自動允許 1 次・細節");
  assert.strictEqual(g.find((n) => n.getAttribute && n.getAttribute("data-chat") === "quiet-list").children.length, 3);
  streams[0].push({ ok: true, ...detail({ records: [rec("reply", { turn: 1, text: "好", truncated: false }), rec("tool_call", { turn: 2, tool_use_id: "t4", tool: "Read", summary: "c" })], next_after: 6 }) });
  await settle();
  assert.deepStrictEqual(log.children.map(dataOf), ["user", "quiet-item", "reply", "quiet-item"]);
  assert(isOpen(qa(main, "quiet-group")[0]) && !isOpen(qa(main, "quiet-group")[1]), "the earlier one is as it was; the new one is closed");
});

test("the person's words are a soft bubble on the right, the employee's are plain text with only the name over them; the time is in the page", async () => {
  seqNo = 0;
  withDetail([rec("user_message", { turn: 1, text: "你好" }), rec("reply", { turn: 1, text: "你好，我是虛構員工。", truncated: false }),
    rec("user_message", { turn: 2, text: "第二步", origin: { dispatch: "d-0123456789ab", step: 2 } })]);
  const main = await open("#/chat/" + CID);
  const [me, them, sent] = q(main, "log").children;
  assert(me.hasClass("chat-me") && them.hasClass("chat-them"));
  const who = (n) => n.find((x) => x.hasClass && x.hasClass("chat-who"));
  const timeOf = (n) => n.find((x) => x.hasClass && x.hasClass("chat-time"));
  assert(timeOf(them) && /\d/.test(text(timeOf(them))), "the time is in the page (a screen reader reads it)");
  assert.strictEqual(text(who(them)).split("・")[0], "虛構員工", "only the name is shown; the time is its own element");
  assert(!text(timeOf(them)).includes("虛構員工"));
  assert(who(me).hasClass("chat-who-quiet"), "the line over your own words shows on hover");
  assert(text(who(sent)).startsWith("VBear 依分配工作送出") && !who(sent).hasClass("chat-who-quiet"), "who really sent a message is always said");
  assert(!text(who(them)).includes("你"), "no 'you' over the employee");
});

test("the css: the employee's words have no frame, your words are a --panel-2 bubble without a border, only the card that waits keeps a frame, the column is 720px", () => {
  const p = part("/* P51-1");
  assert(/\.chat-msg\s*\{[^}]*border:\s*0[^}]*background:\s*transparent[^}]*box-shadow:\s*none/.test(p), "chat-msg: no border, no fill, no shadow");
  assert(/\.chat-me\s*\{[^}]*background:\s*var\(--panel-2\)[^}]*border-radius:\s*1\d+px/.test(p) || /\.chat-msg\.chat-me\s*\{[^}]*background:\s*var\(--panel-2\)/.test(p), "your bubble");
  assert(!/\.chat-me\s*\{[^}]*border:\s*1px/.test(p));
  assert(/\.chat-partial\s*\{[^}]*border:\s*0/.test(p), "the reply being written has no frame either");
  assert(/\.chat-page\s*\{[^}]*max-width:\s*720px[^}]*margin:\s*0 auto/.test(p), "one 720px column");
  assert(/\.chat-card\b/.test(CSS) && /\.chat-card\s*\{[^}]*border:\s*2px solid var\(--quest-edge\)/.test(CSS), "the card that waits keeps its frame (the one framed thing)");
  assert(!/\.chat-card\s*\{[^}]*border:\s*0/.test(p));
  // time: on hover, on focus, and always where there is no hover
  assert(/\.chat-time\s*\{[^}]*opacity:\s*0/.test(p) && !/\.chat-time\s*\{[^}]*display:\s*none/.test(p), "hidden by opacity (it stays in the page)");
  assert(/\.chat-msg:hover \.chat-time/.test(p) && /\.chat-msg:focus-within \.chat-time/.test(p), "shown on hover and on focus");
  assert(/@media \(hover: none\)\s*\{[^}]*\.chat-time\s*\{[^}]*opacity:\s*1/.test(p), "always shown without a mouse");
  assert(/\.chat-who-quiet/.test(p));
  // the fold is a quiet line
  assert(/\.chat-quiet-sum\b/.test(p) && /\.chat-quiet-list\b/.test(p));
  assert(!/\.chat-quiet[^{]*\{[^}]*display:\s*none/.test(p.replace(/\.chat-quiet-sum::-webkit-details-marker\s*\{[^}]*\}/, "")), "the fold is never display none (a closed details already hides its body; only the browser's own marker is hidden, the line draws its own)");
});

test("the buttons on a message still show on hover and on focus, and stay reachable by keyboard (not display none)", () => {
  assert(/\.chat-msg:hover \.chat-remember/.test(CSS) && /\.chat-msg:focus-within \.chat-remember/.test(CSS));
  assert(/\.chat-msg \.chat-remember\s*\{[^}]*opacity:\s*0/.test(CSS) && !/\.chat-msg \.chat-remember\s*\{[^}]*display:\s*none/.test(CSS));
});

test("the source: the new code has no innerHTML and no emoji, loads nothing from outside, and adds no localStorage key", () => {
  const at = SOURCE.indexOf("// ---------- P51 ");
  assert(at > 0, "the P51 part of app.js");
  const mine = SOURCE.slice(at, SOURCE.indexOf("// ---------- end of P51", at));
  assert(mine.length > 1500);
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(mine));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u.test(mine), "no emoji");
  assert(!/https?:\/\//.test(mine) && !/localStorage|sessionStorage/.test(mine));
  const css = part("/* P51-1");
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u.test(css) && !/https?:\/\/|@import|url\(/.test(css));
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
