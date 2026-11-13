// P52-2 (v0.25.0, ADR 0017): why an AI tool cannot be used is said in plain words. The big one: the person's own tool updated itself and VBear does not know that version
// (state `unsupported`): the picker's card, the check list of the start-up page, the page that prepares a chat and the sentence tables all say
// 「你的 {工具} 是 {版本} 版，VBear 還不認得這一版，所以先不能用它聊天。等 VBear 出新版就能用。」, the server's own sentence whole behind 「技術細節」.
// And: where a tool is not ready the page says which step is missing (not installed, not logged in, no safety check yet, an administrator's settings, a version VBear
// does not know), from the state that was read and nothing else; the start-up page's first line stops repeating what the card says once a tool is chosen.
//
// Guard 19c: the sentence for a version VBear does not know holds no version number the page did not get from the server's data (no number written into the code).
// The real web/app.js on a synthetic DOM, fetch answered by the test. Nothing here runs a tool: every state is a fixture; the versions are invented.
// Run: node tests/frontend/p52_words.cjs   (exit code 0 = pass)
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
const byAttr = (root, k, v) => root.findAll((n) => attr(n, k) === v);
const one = (root, k, v) => byAttr(root, k, v)[0] || null;
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const ROOT = path.join(__dirname, "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");
const PICK = "vbear-setup-pick";

// ---- the sentences the server really says (word for word from chat_service.py, admin_policy.py, agy_chat_env.py and agent_sessions.py; versions invented) ----
const UNKNOWN_CLAUDE = "VBear 沒有 Claude Code 2.1.999 的聊天模式常數，所以不能聊天。VBear 目前能聊天的版本：2.1.318、2.1.319、2.1.322、2.1.323。"
  + "處理方式：安裝其中一個版本（放在 Claude Code 自己的版本資料夾裡，VBear 就會自動選用），或等 VBear 更新。";
const UNKNOWN_AGY = "AGY 9.9.9 不是 VBear 能聊天的版本。VBear 目前能聊天的 AGY 版本：1.5.3、1.5.6、1.5.7。";
const NO_SOURCE_LIST = (tool, v) => `${tool} ${v} 沒有管理員政策來源清單，不能啟動`;
const NO_SOURCE_FULL = (tool, v) => `${NO_SOURCE_LIST(tool, v)}。請使用者或系統管理員處理後再啟動。`;
const NO_CONSTANTS = (tool, v) => `${tool} ${v} 沒有聊天模式的常數`;
const NO_CONSTANTS_BARE = "VBear 沒有這個版本的聊天模式常數，不會啟動。";
const SAY = (tool, v) => `你的 ${tool} 是 ${v} 版，VBear 還不認得這一版，所以先不能用它聊天。`;
const SAY_BARE = (tool) => `你的 ${tool} 的版本 VBear 還不認得，所以先不能用它聊天。`;
const NEXT = "等 VBear 出新版就能用。";

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- the judge of 19c: a sentence about a version VBear does not know, and what the server's data said ------------------------------------------------------------
// `said`: the plain sentence; `served`: the version strings the page was given by the server (an empty list: it was given none).
const VERSION_TOKEN = /\d+(?:\.\d+)+/g;
function judge19c(said, served) {
  const bad = [];
  for (const t of said.match(VERSION_TOKEN) || []) if (!served.includes(t)) bad.push(`the sentence says ${t}, which the server's data did not give`);
  if (/降級|降版|改設定|設定檔|downgrade/i.test(said)) bad.push("it tells the person to go back to an older version or to edit a file");
  return bad;
}
// 19c (source): the function that says it holds no number of its own: no string with a dotted version in it.
function judge19cSource(src) {
  const at = src.indexOf("function versionUnknownWords(");
  if (at < 0) return ["no function versionUnknownWords"];
  const body = src.slice(at, src.indexOf("\n}\n", at) + 3);
  const bad = [];
  for (const m of body.matchAll(/"[^"\n]*"|`[^`\n]*`|'[^'\n]*'/g)) if (/\d+\.\d+/.test(m[0])) bad.push(`a version written into the code: ${m[0]}`);
  return bad;
}

// ---- fixtures: the pages of the start-up and the CEO ---------------------------------------------------------------------------------------------------------------------
const NAMES = { claude: "Claude Code", codex: "Codex CLI", agy: "Antigravity（AGY）", grok: "Grok", mcode: "MCODE" };
function trow(id, over = {}) {
  const byStatus = id === "claude" || id === "codex";
  return { id, name: NAMES[id], short: NAMES[id], blurb: `${NAMES[id]} 是誰家的、要什麼方案。`, hidden: id === "mcode",
    installed: false, version: null, install_problem: "not_found", login_by: byStatus ? "status" : "mark", login: byStatus ? "unknown" : "not_marked",
    can_mark: !byStatus, marked_at: null, state: "not_installed", ready: false, login_regions: [], ...(id === "codex" ? { chat_login: { state: "not_logged_in", problem: "" } } : {}), ...over };
}
const installedRow = (id, over = {}) => trow(id, { installed: true, version: "1.2.3", install_problem: "", state: "not_logged_in", login: id === "claude" || id === "codex" ? "not_logged_in" : "not_marked", ...over });
const readyRow = (id, over = {}) => installedRow(id, { state: "ready", ready: true, login: id === "claude" || id === "codex" ? "logged_in" : "marked", marked_at: 1.5,
  ...(id === "codex" ? { chat_login: { state: "logged_in", problem: "" } } : {}), ...over });
const supportOf = (over = {}) => ({ engine: "claude-chat", detected: "2.1.300", verified: [], state: "unverified", message: "Claude Code 2.1.300 還沒通過聊天驗證。", policy: null, verify: { running: false },
  codex: { state: "unverified", version: "0.9.1", why: "", verify: { running: false } }, agy: { state: "unverified", version: "3.0.2", why: "", verify: { running: false } }, ...over });
const CEO_ID = "prof-0123456789ab";
const CARD_OF = { claude: "claude-chat", codex: "codex-chat", agy: "agy-chat" };
let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  global.localStorage._store = {};
  page = { tools: [trow("claude"), trow("codex"), trow("agy"), trow("grok")], support: supportOf(), plan: null, toolsFail: false, cards: [], ...over };
  FETCH_LOG.length = 0;
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true });
    if (p === "/api/config") return jsonResponse({ ok: true, config: { setup_done: true } });
    if (p === "/api/setup/tools" && method === "GET") return page.toolsFail ? jsonResponse({ error: "壞了" }, false, 500) : jsonResponse({ ok: true, any_ready: page.tools.some((t) => t.ready), setup_done: true, tools: page.tools });
    if (p === "/api/setup/daily-limit") return jsonResponse({ ok: true, daily_usd: 3, choices: [1, 3, 10] });
    if (p === "/api/first-ceo") return page.plan ? jsonResponse(page.plan) : jsonResponse({ ok: false, error: "x" }, false, 503);
    if (p === "/api/chats" && method === "GET") return jsonResponse({ ok: true, chats: [], more: 0, cards: page.cards, support: page.support, limits: { per_turn_usd: "0.5", daily_usd: "3" },
      ledger: { spent_usd: "0", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "" });
    return null;
  });
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const click = async (node) => { node.dispatch("click"); await settle(); };
const pickCard = (main, id) => one(main, "data-setup-pick", id);
const techOf = (node) => node.findAll((n) => attr(n, "data-plain") === "tech");
const w = (raw) => app.plainWords(raw);

// ---- plainWords ----------------------------------------------------------------------------------------------------------------------------------------------------
test("plainWords: a Claude Code the server has no chat constants for is said in plain words with the version taken from the sentence; the whole original is kept for the technical details", () => {
  const x = w(UNKNOWN_CLAUDE);
  assert.strictEqual(x.known, true);
  assert.strictEqual(x.text, SAY("Claude Code", "2.1.999"));
  assert.strictEqual(x.next, NEXT);
  assert.strictEqual(x.detail, UNKNOWN_CLAUDE, "the original, whole (the list of versions is in it)");
  assert.deepStrictEqual(judge19c(x.text + x.next, ["2.1.999"]), []);
  assert.ok(!/降級|設定檔|安裝其中一個版本/.test(x.text + x.next), "no instruction to go back to an older version");
});

test("plainWords: 「沒有管理員政策來源清單，不能啟動」 (a version with no list of administrator sources) is the same plain sentence for each of the three tools, with and without the closing sentence", () => {
  for (const tool of ["Claude Code", "Codex", "AGY"]) {
    for (const raw of [NO_SOURCE_LIST(tool, "4.5.6"), NO_SOURCE_FULL(tool, "4.5.6")]) {
      const x = w(raw);
      assert.strictEqual(x.known, true, raw);
      assert.strictEqual(x.text, SAY(tool, "4.5.6"), raw);
      assert.strictEqual(x.next, NEXT);
      assert.strictEqual(x.detail, raw);
    }
  }
});

test("plainWords: 「沒有聊天模式的常數」, the AGY version table and the bare sentence of the daemon; a sentence with no version says so without making one up", () => {
  for (const tool of ["Claude Code", "Codex", "AGY"]) {
    const x = w(NO_CONSTANTS(tool, "7.8.9"));
    assert.deepStrictEqual([x.known, x.text, x.next, x.detail], [true, SAY(tool, "7.8.9"), NEXT, NO_CONSTANTS(tool, "7.8.9")]);
  }
  const agy = w(UNKNOWN_AGY);
  assert.deepStrictEqual([agy.known, agy.text, agy.next, agy.detail], [true, SAY("AGY", "9.9.9"), NEXT, UNKNOWN_AGY]);
  const bare = w(NO_CONSTANTS_BARE);
  assert.deepStrictEqual([bare.known, bare.text, bare.next, bare.detail], [true, SAY_BARE("AI 工具"), NEXT, NO_CONSTANTS_BARE]);
  assert.deepStrictEqual(judge19c(bare.text + bare.next, []), []);
  const noversion = w("Codex 沒有聊天模式的常數");
  assert.notStrictEqual(noversion.known, true, "a sentence the table does not know stays as it is");
});

test("plainWords: sentences that look alike but say something else are left as they are (a stream constant, a missing binary, another tool's policy words)", () => {
  for (const raw of ["Claude Code 2.1.999 沒有串流模式的常數", "讀不到 Claude Code 的版本（找不到）。", "存在管理員政策或系統設定：/etc/codex。請使用者或系統管理員處理後再啟動。"]) {
    const x = w(raw);
    assert.ok(!/還不認得/.test(x.text), raw + " -> " + x.text);
  }
});

// ---- the picker's card ---------------------------------------------------------------------------------------------------------------------------------------------
test("setupVendorStatus: a tool whose version VBear does not know says so on its card with the version the server gave (the chat support, else the tool's own row), and keeps the server's sentence", () => {
  const tools = { tools: [readyRow("claude", { version: "2.1.998" })] };
  const withVersion = app.setupVendorStatus(app.SETUP_VENDORS[0], tools, { support: supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE }) });
  assert.strictEqual(withVersion.kind, "unsupported");
  assert.strictEqual(withVersion.text, SAY("Claude Code", "2.1.999") + NEXT);
  assert.strictEqual(withVersion.raw, UNKNOWN_CLAUDE);
  const fromRow = app.setupVendorStatus(app.SETUP_VENDORS[0], tools, { support: supportOf({ state: "unsupported", detected: null, message: UNKNOWN_CLAUDE }) });
  assert.strictEqual(fromRow.text, SAY("Claude Code", "2.1.998") + NEXT, "the tool's own row is the server's data too");
  const none = app.setupVendorStatus(app.SETUP_VENDORS[0], { tools: [readyRow("claude", { version: null })] }, { support: supportOf({ state: "unsupported", detected: null, message: "" }) });
  assert.strictEqual(none.text, SAY_BARE("Claude Code") + NEXT, "no version anywhere: it does not make one up");
  assert.strictEqual(none.raw || "", "");
  const codex = app.setupVendorStatus(app.SETUP_VENDORS[1], { tools: [readyRow("codex", { version: null })] }, { support: supportOf({ codex: { state: "unsupported", version: "0.999.0", why: "" } }) });
  assert.strictEqual(codex.text, SAY("Codex", "0.999.0") + NEXT);
  const agy = app.setupVendorStatus(app.SETUP_VENDORS[2], { tools: [readyRow("agy", { version: null })] }, { support: supportOf({ agy: { state: "unsupported", version: "9.9.9", why: UNKNOWN_AGY } }) });
  assert.strictEqual(agy.text, SAY("AGY", "9.9.9") + NEXT);
  assert.strictEqual(agy.raw, UNKNOWN_AGY);
});

test("the start-up page: the card of a tool VBear does not know says it in plain words, the server's sentence is behind 「技術細節」, and no instruction to go back to an older version is on the page", async () => {
  setPage({ tools: [readyRow("claude", { version: "2.1.999" }), trow("codex"), trow("agy"), trow("grok")], support: supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE }) });
  const main = await open("#/setup");
  const card = pickCard(main, "claude");
  assert.ok(text(card).includes(SAY("Claude Code", "2.1.999") + NEXT), text(card));
  assert.strictEqual(attr(one(card, "data-setup-status", "unsupported"), "data-setup-status"), "unsupported");
  const tech = techOf(card);
  assert.strictEqual(tech.length, 1, "one fold");
  assert.strictEqual(text(tech[0].find((n) => n.tag === "code")), UNKNOWN_CLAUDE, "the server's sentence, whole");
  assert.ok(!/降級|降版|改設定檔|downgrade/i.test(text(main).replace(UNKNOWN_CLAUDE, "")), "nothing on the page tells the person to go back");
  assert.ok(one(card, "data-setup-pick-go", "claude"), "it can still be chosen (the person decides)");
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method !== "GET"), []);
});

test("the start-up page, chosen: the list says 「還不認得這一版」 in the chat item, and there is no button to check", async () => {
  setPage({ tools: [readyRow("claude", { version: "2.1.999" }), trow("codex"), trow("agy"), trow("grok")], support: supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE }) });
  global.localStorage._store[PICK] = "claude";
  const main = await open("#/setup");
  const chat = one(main, "data-setup-check-item", "chat");
  assert.strictEqual(attr(chat, "data-result"), "fail");
  assert.ok(text(chat).includes(SAY("Claude Code", "2.1.999") + NEXT), text(chat));
  assert.strictEqual(techOf(chat).length, 1);
  assert.strictEqual(byAttr(main, "data-setup-check", "go").length, 0, "nothing to check on a version that cannot chat");
  // Codex and AGY say it the same way, also when the server has no sentence of its own
  setPage({ tools: [trow("claude"), readyRow("codex", { version: "0.999.0" }), trow("agy"), trow("grok")], support: supportOf({ codex: { state: "unsupported", version: "0.999.0", why: "" } }) });
  global.localStorage._store[PICK] = "codex";
  const cx = await open("#/setup");
  assert.ok(text(one(cx, "data-setup-check-item", "chat")).includes(SAY("Codex", "0.999.0") + NEXT));
});

test("the start-up page: choosing a tool puts away the first line 「目前還沒有就緒的 AI 工具…」 (the card says it); before choosing it is there", async () => {
  setPage();
  let main = await open("#/setup");
  assert.ok(text(main).includes("目前還沒有就緒的 AI 工具"));
  await click(one(main, "data-setup-pick-go", "claude"));
  main = h.dom().mainEl;
  assert.ok(!text(main).includes("目前還沒有就緒的 AI 工具"), "gone once a tool is chosen");
  assert.ok(text(main).includes("你選了：Anthropic Claude"));
  await click(one(main, "data-setup", "change-pick"));
  assert.ok(text(h.dom().mainEl).includes("目前還沒有就緒的 AI 工具"), "and back with the cards");
});

// ---- the page that prepares a chat ---------------------------------------------------------------------------------------------------------------------------------
test("chatPrepState: a tool VBear does not know is its own sentence for each of the three tools, with the server's sentence as `raw`; no button that cannot help", () => {
  const cardFor = (engine) => ({ id: "x", name: "虛構", can_chat: true, engine });
  const data = (over) => ({ support: supportOf(over) });
  const cases = [
    ["claude-chat", data({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE }), "Claude Code", "2.1.999", UNKNOWN_CLAUDE],
    ["codex-chat", data({ codex: { state: "unsupported", version: "0.999.0", why: "" } }), "Codex", "0.999.0", ""],
    ["agy-chat", data({ agy: { state: "unsupported", version: "9.9.9", why: UNKNOWN_AGY } }), "AGY", "9.9.9", UNKNOWN_AGY],
  ];
  for (const [engine, d, tool, version, raw] of cases) {
    const st = app.chatPrepState(cardFor(engine), d);
    assert.strictEqual(st.kind, "link", engine);
    assert.strictEqual(st.reason, SAY(tool, version) + NEXT, engine);
    assert.strictEqual(st.raw || "", raw, engine);
    assert.ok(!st.verify, "nothing to verify");
    assert.deepStrictEqual(judge19c(st.reason, [version]), []);
  }
  const noVersion = app.chatPrepState(cardFor("claude-chat"), data({ state: "unsupported", detected: null, message: "" }));
  assert.strictEqual(noVersion.reason, SAY_BARE("Claude Code") + NEXT);
});

test("the page that prepares a chat: the plain sentence, then 「技術細節」 with the server's sentence whole", async () => {
  const card = { id: CEO_ID, name: "虛構 CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true };
  setPage({ cards: [card], support: supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE }) });
  const main = await open("#/chat?profile=" + CEO_ID);
  const reason = one(main, "data-chat", "prep-reason");
  assert.ok(reason && text(reason) === SAY("Claude Code", "2.1.999") + NEXT, text(reason));
  const tech = techOf(one(main, "data-chat", "prep"));
  assert.strictEqual(tech.length, 1);
  assert.strictEqual(text(tech[0].find((n) => n.tag === "code")), UNKNOWN_CLAUDE);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method !== "GET"), []);
});

// ---- which step is missing -------------------------------------------------------------------------------------------------------------------------------------------
test("setupMissingLine: each state that was read has its own line naming the missing step; a state that was not read says it could not be read; a tool that is ready has none", () => {
  const V = app.SETUP_VENDORS[0];
  const line = (tools, support) => app.setupMissingLine(V, app.setupVendorStatus(V, tools ? { tools } : null, support === undefined ? null : { support }));
  assert.ok(line([trow("claude")], supportOf()).includes("還沒安裝"));
  assert.ok(line([trow("claude", { install_problem: "version_unreadable" })], supportOf()).includes("讀不出版本"));
  assert.ok(line([installedRow("claude")], supportOf()).includes("還沒登入"));
  assert.ok(line([installedRow("claude", { login: "unknown" })], supportOf()).includes("查不出有沒有登入"));
  assert.ok(line([readyRow("claude")], supportOf()).includes("安全檢查"));
  assert.ok(line([readyRow("claude")], supportOf({ verify: { running: true } })).includes("還在做"));
  assert.ok(line([readyRow("claude")], supportOf({ state: "policy", message: "x" })).includes("管理員設定"));
  assert.ok(line([readyRow("claude", { version: "2.1.999" })], supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE })).includes(SAY("Claude Code", "2.1.999")));
  assert.ok(line(null, null).includes("讀不到"));
  assert.ok(line([readyRow("claude")], null).includes("讀不到"));
  assert.strictEqual(line([readyRow("claude")], supportOf({ state: "verified", message: "" })), "");
  const codex = app.SETUP_VENDORS[1];
  assert.ok(app.setupMissingLine(codex, app.setupVendorStatus(codex, { tools: [readyRow("codex", { chat_login: { state: "not_logged_in", problem: "" } })] }, { support: supportOf() })).includes("聊天用的 Codex"));
  for (const t of ["install", "login", "check"]) assert.ok(!/猜|可能/.test(line([trow("claude")], supportOf())), t);
});

test("the CEO page: a tool that is not ready says which step is missing (read from the tools, not guessed); a tool VBear does not know says it, and the safety-check line is not claimed", async () => {
  const reason = "你選的 Claude Code 還沒準備好，回開始設定把它準備好，或換一家。";
  setPage({ tools: [installedRow("claude")], plan: { ok: true, needed: true, can_create: false, go: "setup", reason, tool: null, tool_name: null, name: "CEO", position: "planner", instructions: "", opening: "" } });
  global.localStorage._store[PICK] = "claude";
  let main = await open("#/ceo");
  assert.ok(text(main).includes(reason), "the server's sentence stays");
  assert.ok(text(one(main, "data-ceo", "missing")).includes("還沒登入"), text(one(main, "data-ceo", "missing")));
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method !== "GET"), []);
  // no pick at all: nothing to say about one tool
  setPage({ plan: { ok: true, needed: true, can_create: false, go: "setup", reason: "目前沒有已經就緒、而且能聊天的 AI 工具。", tool: null, tool_name: null, name: "CEO", position: "planner", instructions: "", opening: "" } });
  main = await open("#/ceo");
  assert.strictEqual(one(main, "data-ceo", "missing"), null);
  // the tool is logged in but its version is not known: the page can make the card, and says why it cannot chat yet in the same plain words
  const plan = { ok: true, needed: true, can_create: true, go: null, reason: "", tool: "claude", tool_name: "Claude Code", name: "CEO", position: "planner", instructions: "x", opening: "y", chat_ready: null, chat_note: "" };
  setPage({ tools: [readyRow("claude", { version: "2.1.999" })], plan, support: supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN_CLAUDE }) });
  main = await open("#/ceo");
  assert.ok(text(one(main, "data-ceo", "tool")).includes(SAY("Claude Code", "2.1.999") + NEXT), text(one(main, "data-ceo", "tool")));
  assert.ok(!text(one(main, "data-ceo", "tool")).includes("建立後會告訴你原因"));
});

// ---- guard 19c ---------------------------------------------------------------------------------------------------------------------------------------------------------
test("19c: the sentence has only versions the server's data gave; the real sentences of every place pass the judge, and the judge catches a number the page made up", () => {
  const places = [
    [w(UNKNOWN_CLAUDE), ["2.1.999"]], [w(NO_SOURCE_FULL("AGY", "4.5.6")), ["4.5.6"]], [w(NO_CONSTANTS_BARE), []],
    [app.versionUnknownWords("Codex", "0.999.0"), ["0.999.0"]], [app.versionUnknownWords("Codex", ""), []], [app.versionUnknownWords("Codex", undefined), []], [app.versionUnknownWords("", ""), []],
  ];
  for (const [x, served] of places) assert.deepStrictEqual(judge19c(x.text + x.next, served), [], x.text);
  // made-up broken sentences
  assert.ok(judge19c("你的 Claude Code 是 2.1.318 版，VBear 還不認得這一版。", []).some((m) => /2\.1\.318/.test(m)), "a number written into the code");
  assert.ok(judge19c("你的 Claude Code 是 2.1.999 版，VBear 還不認得這一版。", ["2.1.998"]).length, "a number the server did not give");
  assert.ok(judge19c("請降級到 2.1.322。", ["2.1.322"]).some((m) => /older version/.test(m)));
  assert.ok(judge19c("請改設定檔，再試一次。", []).some((m) => /older version|edit/.test(m)));
});

test("19c (source): the function holds no version number of its own; the real page passes, a function with one written into it is caught", () => {
  assert.deepStrictEqual(judge19cSource(SRC), []);
  assert.ok(judge19cSource('function versionUnknownWords(tool, v) {\n  return { text: `你的 ${tool} 是 2.1.318 版` };\n}\n').some((m) => /written into the code/.test(m)));
  assert.ok(judge19cSource('function versionUnknownWords(tool, v) {\n  const known = "1.5.3";\n  return { text: tool + known };\n}\n').length);
  assert.deepStrictEqual(judge19cSource('function versionUnknownWords(tool, v) {\n  return { text: `你的 ${tool} 是 ${v} 版` };\n}\n'), []);
  assert.ok(judge19cSource("nothing").length);
});

test("source: the plain-words table rules for these sentences are in PLAIN_ERRORS, the new words have no emoji and no outside resource, and the style part of P52-2 (if any) uses the theme's variables", () => {
  const table = SRC.slice(SRC.indexOf("const PLAIN_ERRORS = ["), SRC.indexOf("// x: the original (a string, or an Error"));
  for (const word of ["沒有管理員政策來源清單", "聊天模式常數", "不是 VBear 能聊天的版本"]) assert.ok(table.includes(word), word);
  const start = SRC.indexOf("function versionUnknownWords(");
  assert.ok(start > 0);
  const part = SRC.slice(start, start + 600);
  assert.ok(!/\p{Extended_Pictographic}/u.test(part) && !/https?:\/\//.test(part) && !/innerHTML/.test(part));
  const css = CSS.indexOf("/* P52-2") >= 0 ? CSS.slice(CSS.indexOf("/* P52-2")) : "";
  assert.ok(!/#[0-9a-fA-F]{3,6}\b|url\(|@import|https?:\/\//.test(css));
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
