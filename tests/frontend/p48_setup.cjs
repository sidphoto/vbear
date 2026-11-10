// P48-1 (v0.22.0, ADR 0014): the start-up page asks one thing first, 「你要用哪一家的 AI？」, as three cards (Anthropic Claude, OpenAI ChatGPT, Google Gemini)
// and expands only the one the person chose; the two checks (「試一下」 and the chat safety check) are one button whose first press opens a
// confirmation with the whole cost sentences, and whose result is listed item by item.
//
// Guard 16a: the chat safety check in the start-up page is still told with its cost first and asked for by a press, and not carried across versions.
// Guard 16b: the picker does not log anyone in and does not decide for anyone.
// Each rule has made-up broken samples that the judges below must catch (see the last tests).
// The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/p48_setup.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const attr = (n, k) => n.getAttribute && n.getAttribute(k);
const byAttr = (root, k, v) => root.findAll((n) => attr(n, k) === v);
const hasAttr = (root, k) => root.findAll((n) => n.getAttribute && n.getAttribute(k) !== null && n.getAttribute(k) !== undefined);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const ROOT = path.join(__dirname, "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");
const PICK_KEY = "vbear-setup-pick";

// ---- fixtures -----------------------------------------------------------------------------------------------------------------------------
const NAMES = { claude: "Claude Code", codex: "Codex CLI", agy: "Antigravity（AGY）", grok: "Grok", mcode: "MCODE" };
function row(id, over = {}) {
  const byStatus = id === "claude" || id === "codex";
  return { id, name: NAMES[id], short: NAMES[id], blurb: `${NAMES[id]} 是誰家的、要什麼方案。`, hidden: id === "mcode",
    installed: false, version: null, install_problem: "not_found", login_by: byStatus ? "status" : "mark", login: byStatus ? "unknown" : "not_marked",
    can_mark: !byStatus, marked_at: null, state: "not_installed", ready: false,
    login_regions: [], ...(id === "codex" ? { chat_login: { state: "not_logged_in", problem: "" } } : {}), ...over };
}
const installed = (id, over = {}) => row(id, { installed: true, version: "1.2.3", install_problem: "", state: "not_logged_in",
  login: id === "claude" || id === "codex" ? "not_logged_in" : "not_marked", ...over });
const ready = (id, over = {}) => installed(id, { state: "ready", ready: true, login: id === "claude" || id === "codex" ? "logged_in" : "marked", marked_at: 1.5,
  ...(id === "codex" ? { chat_login: { state: "logged_in", problem: "" } } : {}), ...over });
const WARM = "2.1.300";

// what GET /api/chats says of the chat support of the three; `claude` is the top block, the others sit under codex and agy
function support(over = {}) {
  return { engine: "claude-chat", detected: WARM, verified: [], state: "unverified", message: "Claude Code 2.1.300 還沒通過聊天驗證。", policy: null, verify: { running: false },
    codex: { state: "unverified", version: "0.9.1", why: "", verify: { running: false } },
    agy: { state: "unverified", version: "3.0.2", why: "", verify: { running: false } }, ...over };
}
const verifiedClaude = () => support({ state: "verified", message: "" });

let page, calls, chatsReply, tryReply, verifyReply, gate;
function setPage(over = {}) {
  global.localStorage._store = {};
  page = { tools: ["claude", "codex", "agy", "grok"].map((i) => row(i)), setup_done: false, ...over };
  chatsReply = () => jsonResponse({ ok: true, chats: [], cards: [], support: support(), limits: {}, ledger: {} });
  tryReply = () => jsonResponse({ ok: true, success: true, result: "success", message: "Claude Code 回應了，這個 AI 工具可以用。", spent_usd: "0.01" });
  verifyReply = () => jsonResponse({ ok: true, status: { running: true } }, true, 202);
  gate = null;
  calls = [];
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body, url.includes("?") ? url.split("?")[1] : ""]);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/setup/tools" && method === "GET") return gate && gate.tools ? gate.tools() : jsonResponse({ ok: true, any_ready: page.tools.some((t) => t.ready), ...page });
    if (p === "/api/chats" && method === "GET") return chatsReply();
    if (p === "/api/chat-support/verify") return verifyReply(body);
    if (p.startsWith("/api/setup/tools/") && p.endsWith("/try")) return tryReply(p.split("/")[4], body);
    if (p === "/api/setup/terminals") return jsonResponse({ ok: true, session: { session_id: "n-0123456789ab" }, command: "x" });
    if (p.startsWith("/api/setup/tools/") && p.endsWith("/marker")) return jsonResponse({ ok: true });
    if (p === "/api/setup/daily-limit") return jsonResponse({ ok: true, daily_usd: 3, choices: [1, 3, 10] });
    if (p === "/api/config" && method === "POST") return jsonResponse({ ok: true, config: body });
    if (p === "/api/config") return jsonResponse({ ok: true, config: {} });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true });
    return null;
  });
}
let tick = null;
async function open(hash) {
  const realSetInterval = global.setInterval;
  tick = null;
  global.setInterval = (fn) => { tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const click = async (node) => { node.dispatch("click"); await settle(); };
const posts = () => calls.filter((c) => c[0] !== "GET");
const pickCards = (main) => hasAttr(main, "data-setup-pick");
const pickIds = (main) => pickCards(main).map((n) => attr(n, "data-setup-pick"));
const goBtn = (main, id) => byAttr(main, "data-setup-pick-go", id)[0];
const toolCards = (main) => main.findAll((n) => attr(n, "data-tool"));
const toolCard = (main, id) => toolCards(main).find((n) => attr(n, "data-tool") === id);
const item = (main, key) => byAttr(main, "data-setup-check-item", key)[0];
const checkBtn = (main, k) => byAttr(main, "data-setup-check", k)[0];

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- the judges: a recorded run goes in, the broken things come out. The made-up broken runs at the end must be caught. -----------------------
// 16a: the order and the content of what was sent. `log`: [method, path, body] in order; `shown`: the version the page shows for the chosen tool;
// `passedBefore`: the safety check of that version had passed when the person pressed 「確認，開始」.
function judge16a(log, { engine, shown, passedBefore, confirmed }) {
  const bad = [];
  const post = log.filter((c) => c[0] !== "GET");
  const tries = post.filter((c) => /^\/api\/setup\/tools\/[^/]+\/try$/.test(c[1]));
  const verifies = post.filter((c) => c[1] === "/api/chat-support/verify");
  if (!confirmed && post.length) bad.push("something was sent before 「確認，開始」");
  if (confirmed && tries.length !== 1) bad.push("not exactly one try");
  if (tries[0] && JSON.stringify(tries[0][2]) !== JSON.stringify({ confirmed: true })) bad.push("the try did not carry confirmed:true");
  if (passedBefore && verifies.length) bad.push("a version that had passed was verified again");
  if (verifies.length > 1) bad.push("more than one verify");
  for (const v of verifies) {
    if (!v[2] || v[2].engine !== engine) bad.push("the verify is for another tool");
    if (!v[2] || v[2].version !== shown) bad.push("the verify does not carry the version on screen");
  }
  const ti = log.indexOf(tries[0]);
  for (const v of verifies) if (ti < 0 || log.indexOf(v) < ti) bad.push("the verify came before the try");
  return bad;
}
// 16a (source): the keys the page writes to the browser's storage are a fixed list, and none of them keeps a verification result.
const STORAGE_ALLOWED = new Set([PICK_KEY, "vbear-notify"]);
function storageKeyViolations(src) {
  const bad = [];
  const consts = new Map([...src.matchAll(/\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*("[^"\n]*"|'[^'\n]*')\s*;/g)].map((m) => [m[1], m[2].slice(1, -1)]));
  for (const m of src.matchAll(/\b(?:local|session)Storage\.setItem\(\s*([^,)]+?)\s*,/g)) {
    const arg = m[1];
    if (/^"sid:"\s*\+\s*k$/.test(arg)) continue;            // the small preference store of the page (store.set), which keeps no verification
    const lit = /^"([^"]*)"$/.exec(arg);
    const key = lit ? lit[1] : consts.get(arg);
    if (key === undefined) bad.push(`key not a fixed string: ${arg}`);
    else if (!STORAGE_ALLOWED.has(key)) bad.push(`key not on the list: ${key}`);
    else if (/verif|safe|pass/i.test(key)) bad.push(`key keeps a verdict: ${key}`);
  }
  return bad;
}
// 16b: what the picker may and may not do.
function judge16b(main, log, { stateOrderSame, pressedPick }) {
  const bad = [];
  const ids = hasAttr(main, "data-setup-pick").map((n) => attr(n, "data-setup-pick"));
  if (JSON.stringify(ids) !== JSON.stringify(["claude", "codex", "agy"]) && ids.length) bad.push("order or members of the cards");
  if (!stateOrderSame) bad.push("the order follows the state");
  if (/建議|推薦|Recommended/.test(text(main))) bad.push("a tool is recommended");
  const posts = log.filter((c) => c[0] !== "GET");
  if (pressedPick && posts.length) bad.push("choosing sent a POST");
  if (log.some((c) => c[1] === "/api/setup/terminals" && !pressedPick)) bad.push("a terminal was opened by the page");
  return bad;
}

// ---- 16b: the picker -----------------------------------------------------------------------------------------------------------------------
test("first time: only three cards, in the fixed order, each with its tool, its account and the state of this Mac; nothing is expanded or recommended", async () => {
  setPage({ tools: [row("claude"), installed("codex"), ready("agy"), row("grok")] });
  const main = await open("#/setup");
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "開始設定");
  assert.deepStrictEqual(pickIds(main), ["claude", "codex", "agy"]);
  const cs = pickCards(main);
  assert(text(cs[0]).includes("Anthropic Claude") && text(cs[0]).includes("Claude Code") && text(cs[0]).includes("Claude 的付費方案"));
  assert(text(cs[1]).includes("OpenAI ChatGPT") && text(cs[1]).includes("Codex") && text(cs[1]).includes("ChatGPT 帳號"));
  assert(text(cs[2]).includes("Google Gemini") && text(cs[2]).includes("AGY") && text(cs[2]).includes("Google 帳號"));
  assert(text(cs[0]).includes("還沒安裝"), text(cs[0]));
  assert(text(cs[1]).includes("裝好了，還沒登入"), text(cs[1]));
  assert(!/建議|推薦/.test(text(main)));
  assert.strictEqual(toolCards(main).length, 0, "no tool card is expanded before a choice");
  assert.strictEqual(byAttr(main, "data-setup", "others").length, 0);
  assert.strictEqual(byAttr(main, "data-setup", "picked").length, 0);
  assert.deepStrictEqual(["claude", "codex", "agy"].map((i) => !!goBtn(main, i)), [true, true, true]);
  assert.deepStrictEqual(posts(), [], "loading the page sent only GETs");
  assert.strictEqual(global.localStorage.getItem(PICK_KEY), null, "nothing is written until a card is chosen");
});

test("xAI Grok is one grey line, not a button: it cannot be chosen and pressing it sends nothing", async () => {
  setPage();
  const main = await open("#/setup");
  const later = byAttr(main, "data-setup-later", "xai")[0];
  assert(later && text(later) === "xAI Grok：之後支援（現在還不能用來聊天）");
  assert.notStrictEqual(later.tag, "button");
  assert.strictEqual(byAttr(main, "data-setup-pick-go", "xai").length, 0);
  assert.strictEqual(byAttr(main, "data-setup-pick", "xai").length, 0);
  assert.strictEqual(later.findAll((n) => n.tag === "button" || n.tag === "a").length, 0);
  const before = calls.length;
  await click(later);
  assert.strictEqual(calls.length, before, "pressing it sent nothing");
  assert.strictEqual(global.localStorage.getItem(PICK_KEY), null);
  assert(!text(main).includes("MCODE"), "the private option is not listed on the cards");
});

test("the order of the cards does not follow the state of the tools", async () => {
  const orders = [];
  for (const tools of [
    [row("claude"), row("codex"), row("agy"), row("grok")],
    [ready("claude"), installed("codex"), row("agy"), row("grok")],
    [row("claude"), installed("codex"), ready("agy"), row("grok")],
    [ready("agy"), ready("codex"), ready("claude"), ready("grok")].reverse(),
  ]) {
    setPage({ tools });
    const main = await open("#/setup");
    orders.push(pickIds(main).join(","));
  }
  assert.deepStrictEqual([...new Set(orders)], ["claude,codex,agy"]);
});

test("choosing a card sends nothing, writes only vbear-setup-pick, and expands that one tool; the others go into 「其他 AI 工具」", async () => {
  setPage({ tools: [ready("claude"), installed("codex"), row("agy"), installed("grok")] });
  let main = await open("#/setup");
  await click(goBtn(main, "codex"));
  assert.deepStrictEqual(posts(), [], "choosing sent no POST (no terminal, no config)");
  assert.deepStrictEqual(Object.keys(global.localStorage._store), [PICK_KEY]);
  assert.strictEqual(global.localStorage.getItem(PICK_KEY), "codex");
  main = h.dom().mainEl;
  assert.strictEqual(pickCards(main).length, 0, "the cards are put away");
  const picked = byAttr(main, "data-setup", "picked")[0];
  assert(picked && text(picked).includes("你選了：OpenAI ChatGPT（Codex）"), text(picked));
  assert(byAttr(picked, "data-setup", "change-pick")[0], "a way to choose another");
  const others = byAttr(main, "data-setup", "others")[0];
  assert(others && others.tag === "details" && !others.open, "the other tools are folded, closed");
  assert(text(others).includes("其他 AI 工具（之後隨時可以加）"));
  const expanded = toolCards(main).filter((c) => !others.findAll((n) => n === c).length);
  assert.deepStrictEqual(expanded.map((c) => attr(c, "data-tool")), ["codex"]);
  assert.deepStrictEqual(toolCards(main).map((c) => attr(c, "data-tool")).sort(), ["agy", "claude", "codex", "grok"]);
  // the old 「試一下」 of the other tools is still there, inside the fold
  assert(byAttr(others, "data-setup-try-act", "try").length >= 2);
  assert(!byAttr(expanded[0], "data-setup-try-act", "try").length, "the chosen tool has the new button instead");
});

test("a remembered choice opens that tool at once; a value that is not one of the three is ignored", async () => {
  setPage({ tools: [ready("claude"), row("codex"), row("agy"), row("grok")] });
  global.localStorage._store[PICK_KEY] = "agy";
  let main = await open("#/setup");
  assert(byAttr(main, "data-setup", "picked")[0] && text(byAttr(main, "data-setup", "picked")[0]).includes("Google Gemini（AGY）"));
  assert.deepStrictEqual(posts(), []);
  global.localStorage._store[PICK_KEY] = "xai";
  main = await open("#/setup");
  assert.deepStrictEqual(pickIds(main), ["claude", "codex", "agy"], "an unknown value is a page with no choice");
  assert.strictEqual(toolCards(main).length, 0);
});

test("「換一家」 only shows the cards again: GETs only, and it writes nothing", async () => {
  setPage({ tools: [ready("claude"), row("codex"), row("agy"), row("grok")] });
  global.localStorage._store[PICK_KEY] = "claude";
  let main = await open("#/setup");
  const before = JSON.stringify(global.localStorage._store);
  await click(byAttr(main, "data-setup", "change-pick")[0]);
  main = h.dom().mainEl;
  assert.deepStrictEqual(pickIds(main), ["claude", "codex", "agy"]);
  assert.deepStrictEqual(posts(), []);
  assert.strictEqual(JSON.stringify(global.localStorage._store), before);
});

test("the terminal is opened only by the install or login button of the expanded card, and then with the tool and the action alone", async () => {
  setPage({ tools: [row("claude"), installed("codex"), row("agy"), row("grok")] });
  let main = await open("#/setup");
  await click(goBtn(main, "claude"));
  assert(!calls.some((c) => c[1] === "/api/setup/terminals"), "choosing did not open a terminal");
  main = h.dom().mainEl;
  await click(byAttr(toolCard(main, "claude"), "data-setup-act", "install")[0]);
  assert.deepStrictEqual(calls.filter((c) => c[1] === "/api/setup/terminals").map((c) => c[2]), [{ tool: "claude", action: "install" }]);
});

test("the three states of this Mac: nothing installed, Claude ready but not checked, Claude held back by an administrator", async () => {
  // nothing installed
  setPage();
  let main = await open("#/setup");
  assert(["claude", "codex", "agy"].every((i) => text(byAttr(main, "data-setup-pick", i)[0]).includes("還沒安裝")));
  assert.strictEqual(byAttr(main, "data-setup", "leave")[0].disabled, true);
  // Claude ready, the version has not passed the chat check
  setPage({ tools: [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")] });
  main = await open("#/setup");
  assert(text(byAttr(main, "data-setup-pick", "claude")[0]).includes("已登入，第一次聊天前要做一次安全檢查"), text(byAttr(main, "data-setup-pick", "claude")[0]));
  assert.notStrictEqual(byAttr(main, "data-setup", "leave")[0].disabled, true);
  // Claude ready and an administrator's settings hold chat back
  setPage({ tools: [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")] });
  chatsReply = () => jsonResponse({ ok: true, support: support({ state: "policy", message: "管理員設定擋住了" }) });
  main = await open("#/setup");
  assert(text(byAttr(main, "data-setup-pick", "claude")[0]).includes("管理員設定"), text(byAttr(main, "data-setup-pick", "claude")[0]));
  // and a verified one
  setPage({ tools: [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")] });
  chatsReply = () => jsonResponse({ ok: true, support: verifiedClaude() });
  main = await open("#/setup");
  assert(text(byAttr(main, "data-setup-pick", "claude")[0]).includes("可以聊天了"));
});

test("when the chat state cannot be read the card says it cannot be read; it does not guess", async () => {
  setPage({ tools: [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")] });
  chatsReply = () => jsonResponse({ error: "boom" }, false, 500);
  const main = await open("#/setup");
  const t = text(byAttr(main, "data-setup-pick", "claude")[0]);
  assert(t.includes("讀不到"), t);
  assert(!t.includes("可以聊天了") && !t.includes("第一次聊天前"), t);
});

test("the skeleton comes first: the title, the cards and 「正在看這台 Mac…」 are drawn before the answers arrive", async () => {
  setPage();
  let release;
  gate = { tools: () => new Promise((resolve) => { release = () => resolve(jsonResponse({ ok: true, any_ready: false, ...page })); }) };
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = "#/setup";
  const routing = app.route();
  await settle();
  const main = h.dom().mainEl;
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "開始設定");
  assert.deepStrictEqual(pickIds(main), ["claude", "codex", "agy"]);
  assert(byAttr(main, "data-setup", "loading").length >= 1 && text(main).includes("正在看這台 Mac…"));
  assert.strictEqual(byAttr(main, "data-setup-pick-go", "claude").length, 0, "nothing can be chosen before the state is known");
  release();
  await routing; await settle();
  global.setInterval = realSetInterval;
  assert.strictEqual(byAttr(h.dom().mainEl, "data-setup", "loading").length, 0, "nothing is loading any more");
  assert(goBtn(h.dom().mainEl, "claude"));
});

test("a tool list that cannot be read is said so, not drawn as an empty Mac", async () => {
  setPage();
  gate = { tools: () => jsonResponse({ error: "boom" }, false, 500) };
  const main = await open("#/setup");
  assert(text(main).includes("讀不到 AI 工具的狀態"));
  assert.strictEqual(byAttr(main, "data-setup-pick-go", "claude").length, 0);
});

test("on a narrow screen the cards sit one under the other and the first card's button is in the first screen", async () => {
  setPage();
  const main = await open("#/setup");
  const picker = byAttr(main, "data-setup", "picker")[0];
  const idx = main.children.findIndex((n) => n === picker || n.contains(picker));
  assert(idx >= 0 && idx <= 3, "the picker is among the first things of the page");
  const firstCard = picker.children[0];
  assert(byAttr(firstCard, "data-setup-pick-go", "claude").length === 1, "the first card has its own button");
  const css = CSS.slice(CSS.indexOf("/* P48-1"));
  assert(css.length < CSS.length, "P48-1 has its own part at the end of the style sheet");
  assert(/\.setup-picker\s*\{[^}]*grid-template-columns:\s*repeat\(3/.test(css));
  const narrow = css.slice(css.search(/@media \(max-width: (5|6)\d\dpx\)\s*\{[^}]*\.setup-picker/));
  assert(/\.setup-picker\s*\{[^}]*grid-template-columns:\s*1fr/.test(narrow), "one column on a narrow screen");
  assert(!/url\(|@import|https?:\/\//.test(css));
  assert(!/#[0-9a-fA-F]{3,6}\b/.test(css), "colours come from the theme variables");
});

// ---- 16a: the one button --------------------------------------------------------------------------------------------------------------------
async function chosen(id, tools, over = {}) {
  setPage({ tools });
  if (over.chats) chatsReply = () => jsonResponse({ ok: true, chats: [], cards: [], support: over.chats, limits: {}, ledger: {} });
  global.localStorage._store = { [PICK_KEY]: id };
  return open("#/setup");
}

test("the expanded card lists what is checked item by item, then offers one button; the list says what has and has not been done", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")]);
  const list = byAttr(main, "data-setup", "check-list")[0];
  assert(list, "the list");
  assert.deepStrictEqual(list.findAll((n) => attr(n, "data-setup-check-item")).map((n) => [attr(n, "data-setup-check-item"), attr(n, "data-result")]),
    [["installed", "pass"], ["login", "pass"], ["try", "todo"], ["chat", "todo"]]);
  assert(text(item(main, "installed")).includes(`版本 ${"1.2.3"}`) || text(item(main, "installed")).includes("裝好了"));
  assert(text(item(main, "installed")).includes("通過"));
  assert(text(item(main, "try")).includes("還沒做") && text(item(main, "chat")).includes("還沒做"));
  const go = checkBtn(main, "go");
  assert(go && text(go) === "試一下，並做聊天安全檢查");
});

test("16a: the button only opens the confirmation (0 POST) with the whole cost sentences; cancel puts it back (0 POST)", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")]);
  await click(checkBtn(main, "go"));
  assert.deepStrictEqual(posts(), [], "the first press sent nothing");
  const box = byAttr(main, "data-setup", "check-confirm")[0];
  assert(box, "the confirmation is in the card");
  assert(text(box).includes(app.SETUP_TRY_ESTIMATE) && text(box).includes("大約花不到 US$0.01"));
  assert(text(box).includes(app.CHAT_VERIFY_COST_CLAUDE), "the whole sentence of the safety check's cost");
  assert(text(box).includes("安全檢查在背景做，你可以先按「下一步：建立 CEO」；做完會自己更新。"));
  assert(checkBtn(main, "confirm") && text(checkBtn(main, "confirm")) === "確認，開始" && checkBtn(main, "cancel") && text(checkBtn(main, "cancel")) === "取消");
  assert(!checkBtn(main, "go"), "the first button is replaced by the two");
  await click(checkBtn(main, "cancel"));
  assert.deepStrictEqual(posts(), [], "cancel sent nothing");
  assert(checkBtn(main, "go") && !checkBtn(main, "confirm") && !byAttr(main, "data-setup", "check-confirm").length);
});

test("16a: 「確認，開始」 sends one try, and the safety check of the version on screen once the try passed; the list is updated by the server's word", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")]);
  await click(checkBtn(main, "go"));
  // after the try the server says the check is running
  verifyReply = () => { chatsReply = () => jsonResponse({ ok: true, support: support({ verify: { running: true } }) }); return jsonResponse({ ok: true, status: { running: true } }, true, 202); };
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => [c[0], c[1], c[2]]), [
    ["POST", "/api/setup/tools/claude/try", { confirmed: true }],
    ["POST", "/api/chat-support/verify", { engine: "claude", version: WARM }]]);
  assert.deepStrictEqual(judge16a(calls, { engine: "claude", shown: WARM, passedBefore: false, confirmed: true }), []);
  assert.strictEqual(attr(item(main, "try"), "data-result"), "pass");
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "running");
  assert(text(item(main, "chat")).includes("在背景做，通常要幾分鐘。可以先去建立 CEO。"));
  assert(!checkBtn(main, "go"), "no second press while it runs");
  // later the server says it passed: the quiet refresh updates the item (GET only)
  chatsReply = () => jsonResponse({ ok: true, support: verifiedClaude() });
  const n = posts().length;
  await tick(); await settle();
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "pass");
  assert.strictEqual(posts().length, n, "the refresh only reads");
});

test("16a: a version that has already passed is not verified again (the try alone)", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")], { chats: verifiedClaude() });
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "pass");
  await click(checkBtn(main, "go"));
  assert(!text(byAttr(main, "data-setup", "check-confirm")[0]).includes(app.CHAT_VERIFY_COST_CLAUDE), "it does not tell a cost it will not spend");
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => c[1]), ["/api/setup/tools/claude/try"]);
  assert.deepStrictEqual(judge16a(calls, { engine: "claude", shown: WARM, passedBefore: true, confirmed: true }), []);
});

test("16a: a try that did not pass stops there: no verify; the item says why in plain words and the original stays in the technical details", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")]);
  tryReply = () => jsonResponse({ ok: true, success: false, result: "not_logged_in", message: "Claude Code 沒有成功回應，看起來還沒登入。請先按「登入」，登入好了再試一次。" });
  await click(checkBtn(main, "go"));
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => c[1]), ["/api/setup/tools/claude/try"]);
  assert.strictEqual(attr(item(main, "try"), "data-result"), "fail");
  assert(text(item(main, "try")).includes("看起來還沒登入"));
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "todo", "the safety check was not done");
  assert(checkBtn(main, "go") && text(checkBtn(main, "go")) === "再試一次", "and it can be asked again, with the confirmation first");
  await click(checkBtn(main, "go"));
  assert.strictEqual(posts().length, 1, "again: nothing is sent before the confirmation");
});

test("16a: a try the server refuses (the day's limit) is a failure with the server's sentence; nothing else is sent", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")]);
  tryReply = () => jsonResponse({ error: "今天已花 US$3，再試一次可能超過每天上限 US$3，所以今天不能再試了。" }, false, 409);
  await click(checkBtn(main, "go"));
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => c[1]), ["/api/setup/tools/claude/try"]);
  assert(text(item(main, "try")).includes("今天不能再試了"));
});

test("16a: an administrator's settings: no button, no POST, the list says why and points to 「換一家」", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")],
    { chats: support({ state: "policy", message: "管理員設定擋住了" }) });
  assert(!checkBtn(main, "go"), "no button");
  assert.deepStrictEqual(posts(), []);
  const chat = item(main, "chat");
  assert.strictEqual(attr(chat, "data-result"), "fail");
  assert(text(chat).includes("這台 Mac 的 Claude Code 有管理員設定，VBear 不能用它聊天"), text(chat));
  assert(text(chat).includes("可以按上面的「換一家」選別家。"));
});

test("16a: a verify the server refuses (the version changed) is said in the item; the page does not try another way", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")]);
  verifyReply = () => jsonResponse({ error: "目前的 Claude Code 是 2.1.301，不是 2.1.300；請重新整理後再驗證。" }, false, 409);
  await click(checkBtn(main, "go"));
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => c[1]), ["/api/setup/tools/claude/try", "/api/chat-support/verify"]);
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "fail");
  assert(text(item(main, "chat")).includes("2.1.301"));
});

test("when the chat state cannot be read the chat item says 讀不到 (not 沒過) and there is no button", async () => {
  setPage({ tools: [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")] });
  chatsReply = () => jsonResponse({ error: "boom" }, false, 500);
  global.localStorage._store = { [PICK_KEY]: "claude" };
  const main = await open("#/setup");
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "unknown");
  assert(text(item(main, "chat")).includes("讀不到"));
  assert(!checkBtn(main, "go"));
});

test("Codex: without the chat login the list has one more item and no button; with it the whole Codex sentence is in the confirmation", async () => {
  let main = await chosen("codex", [row("claude"), ready("codex", { version: "0.9.1", chat_login: { state: "not_logged_in", problem: "" } }), row("agy"), row("grok")]);
  assert.deepStrictEqual(main.findAll((n) => attr(n, "data-setup-check-item")).map((n) => attr(n, "data-setup-check-item")),
    ["installed", "login", "chat-login", "try", "chat"]);
  assert.strictEqual(attr(item(main, "chat-login"), "data-result"), "todo");
  assert(!checkBtn(main, "go"), "no button until the chat login is done");
  main = await chosen("codex", [row("claude"), ready("codex", { version: "0.9.1" }), row("agy"), row("grok")]);
  assert.strictEqual(attr(item(main, "chat-login"), "data-result"), "pass");
  await click(checkBtn(main, "go"));
  assert(text(byAttr(main, "data-setup", "check-confirm")[0]).includes(app.CHAT_VERIFY_COST_CODEX));
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/setup/tools/codex/try", { confirmed: true }], ["/api/chat-support/verify", { engine: "codex", version: "0.9.1" }]]);
  assert.deepStrictEqual(judge16a(calls, { engine: "codex", shown: "0.9.1", passedBefore: false, confirmed: true }), []);
});

test("AGY: the confirmation has the whole AGY sentence (it says the chat goes to Google); the verify is for agy", async () => {
  const main = await chosen("agy", [row("claude"), row("codex"), ready("agy", { version: "3.0.2" }), row("grok")]);
  await click(checkBtn(main, "go"));
  const t = text(byAttr(main, "data-setup", "check-confirm")[0]);
  assert(t.includes(app.CHAT_AGY_VERIFY_COST) && t.includes("對話內容會送到 Google"));
  await click(checkBtn(main, "confirm"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/setup/tools/agy/try", { confirmed: true }], ["/api/chat-support/verify", { engine: "agy", version: "3.0.2" }]]);
});

test("a tool that is not ready has no button, and the list says which step is missing", async () => {
  const main = await chosen("claude", [installed("claude"), row("codex"), row("agy"), row("grok")]);
  assert(!checkBtn(main, "go"));
  assert.strictEqual(attr(item(main, "installed"), "data-result"), "pass");
  assert.strictEqual(attr(item(main, "login"), "data-result"), "todo");
  assert.deepStrictEqual(posts(), []);
});

test("the quiet refresh while a safety check runs reads /api/chats and nothing is posted; a page without a running check asks only for the tools", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), row("codex"), row("agy"), row("grok")], { chats: support({ verify: { running: true } }) });
  assert.strictEqual(attr(item(main, "chat"), "data-result"), "running");
  const n = calls.length;
  await tick(); await settle();
  assert(calls.slice(n).some((c) => c[1] === "/api/chats" && c[0] === "GET"));
  assert.deepStrictEqual(posts(), []);
  assert(!checkBtn(main, "go"), "the server's running flag hides the button as well");
});

test("the old 「試一下」 in 「其他 AI 工具」 still asks first and sends the confirmation only on the second press", async () => {
  const main = await chosen("claude", [ready("claude", { version: WARM }), installed("codex"), row("agy"), installed("grok")]);
  await click(byAttr(toolCard(main, "grok"), "data-setup-try-act", "try")[0]);
  assert.deepStrictEqual(posts(), []);
  await click(byAttr(toolCard(main, "grok"), "data-setup-try-act", "try-confirm")[0]);
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/setup/tools/grok/try", { confirmed: true }]]);
});

test("the way out is 「下一步：建立 CEO」 (the same button, data-setup=leave) and still needs a ready tool", async () => {
  setPage({ tools: [installed("claude"), row("codex"), row("agy"), row("grok")] });
  let main = await open("#/setup");
  const leave = byAttr(main, "data-setup", "leave")[0];
  assert.strictEqual(text(leave), "下一步：建立 CEO");
  assert.strictEqual(leave.disabled, true);
  assert(text(byAttr(main, "data-setup", "leave-note")[0]).includes("要先有一個 AI 工具就緒"));
});

// ---- the guards must catch what they are written to catch (made-up broken runs) ------------------------------------------------------------
test("16a judge: it catches a try before the confirmation, a missing confirmed:true, a verify of a passed version, two verifies, a wrong tool or version, a verify before the try", () => {
  const ok = [["POST", "/api/setup/tools/claude/try", { confirmed: true }], ["POST", "/api/chat-support/verify", { engine: "claude", version: WARM }]];
  const base = { engine: "claude", shown: WARM, passedBefore: false, confirmed: true };
  assert.deepStrictEqual(judge16a(ok, base), []);
  assert(judge16a(ok, { ...base, confirmed: false }).length, "a POST before the confirmation");
  assert(judge16a([["POST", "/api/setup/tools/claude/try", {}], ok[1]], base).some((m) => /confirmed/.test(m)));
  assert(judge16a(ok, { ...base, passedBefore: true }).some((m) => /passed/.test(m)));
  assert(judge16a([ok[0], ok[1], ok[1]], base).some((m) => /more than one/.test(m)));
  assert(judge16a([ok[0], ["POST", "/api/chat-support/verify", { engine: "codex", version: WARM }]], base).some((m) => /another tool/.test(m)));
  assert(judge16a([ok[0], ["POST", "/api/chat-support/verify", { engine: "claude", version: "9.9" }]], base).some((m) => /version/.test(m)));
  assert(judge16a([ok[1], ok[0]], base).some((m) => /before the try/.test(m)));
  assert(judge16a([ok[0]], base).length === 0, "a try that did not pass has no verify, which is fine");
  assert(judge16a([], base).some((m) => /exactly one try/.test(m)));
});

test("16a judge (source): the storage keys are a fixed list; a made-up source that stores a verdict or an unknown key is caught", () => {
  assert.deepStrictEqual(storageKeyViolations(SRC), [], "the real page");
  assert(storageKeyViolations('localStorage.setItem("vbear-chat-verified", "1");').length);
  assert(storageKeyViolations('localStorage.setItem("vbear-safety-pass", "1");').length);
  assert(storageKeyViolations('sessionStorage.setItem(someKey, "1");').length);
  assert(storageKeyViolations('const K = "vbear-verify-result"; localStorage.setItem(K, "1");').length);
  assert.deepStrictEqual(storageKeyViolations('const K = "vbear-setup-pick"; localStorage.setItem(K, "claude"); localStorage.setItem("vbear-notify", "on");'), []);
  assert(SRC.includes(`"${PICK_KEY}"`));
});

test("16b judge: it catches a reordered or recommended card, and a choice that sends a POST", async () => {
  setPage();
  const main = await open("#/setup");
  assert.deepStrictEqual(judge16b(main, calls, { stateOrderSame: true, pressedPick: false }), []);
  assert(judge16b(main, calls, { stateOrderSame: false, pressedPick: false }).length);
  assert(judge16b(main, [["POST", "/api/config", {}]], { stateOrderSame: true, pressedPick: true }).length);
  assert(judge16b(main, [["POST", "/api/setup/terminals", {}]], { stateOrderSame: true, pressedPick: true }).length);
  const fake = { findAll: () => [{ getAttribute: () => "codex" }, { getAttribute: () => "claude" }, { getAttribute: () => "agy" }], textContent: "" };
  assert(judge16b(fake, [], { stateOrderSame: true, pressedPick: false }).some((m) => /order/.test(m)));
  assert(judge16b({ findAll: () => [], textContent: "Claude（建議）" }, [], { stateOrderSame: true, pressedPick: false }).some((m) => /recommended/.test(m)));
});

test("source: the new part of the page is built with el(), has no innerHTML, no emoji, no outside resource, and does not run any AI tool", () => {
  const start = SRC.indexOf("// ---------- setup picker (v0.22, P48-1)");
  const end = SRC.indexOf("// ---------- end of the setup picker");
  assert(start > 0 && end > start, "the part has its own marked place");
  const part = SRC.slice(start, end);
  assert(part.length > 3000);
  assert(!/innerHTML|insertAdjacentHTML/.test(part));
  assert(!/\p{Extended_Pictographic}/u.test(part));
  assert(!/https?:\/\//.test(part));
  assert(!/\/api\/chat-support(?!\/verify)/.test(part), "the page reads the chat state from /api/chats (15b)");
  assert(!/localStorage\.setItem/.test(part.replace(/function setupPickWrite[\s\S]*?\n}\n/, "")), "only setupPickWrite writes to the storage");
  const strings = (part.match(/"[^"\n]*[一-鿿][^"\n]*"|`[^`\n]*[一-鿿][^`\n]*`/g) || []).join("\n");
  assert(!/\bCLI\b|argv|\bPATH\b|provider|LLM/.test(strings), "the words of the glossary only");
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
