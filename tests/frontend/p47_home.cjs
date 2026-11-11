// P47-2 (ADR 0013): the new home page (等你決定, 我的員工, 今天, 想做什麼？跟 CEO 說, the three first steps), the employees' page and the work page.
// Guard 15c lives here: the home page never sends by itself. It draws with GETs only; typing sends nothing; one press of 送出 sends at most one
// POST /api/chats (when there is no chat yet) and exactly one POST /api/chats/<id>/messages with the typed words; when the CEO is busy (a turn
// is running or a card waits) nothing is sent and the words go to the box of the CEO's chat; "等你決定" lists the same things in the normal and
// in the advanced mode. The home page shows no amount of money.
// Runs the whole of web/app.js (with its start-up code) in a vm context against a small synthetic DOM and a fetch stub. NOT a browser test.
//
// Run: node tests/frontend/p47_home.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this._attrs = {}; this._classes = new Set(); this._l = {}; this.value = ""; this.nodeType = tag === "#text" ? 3 : 1; this.disabled = false; this.open = false; this.parentNode = null; }
  get classList() { const s = this; return { add: (...c) => c.forEach((x) => s._classes.add(x)), remove: (...c) => c.forEach((x) => s._classes.delete(x)), contains: (c) => s._classes.has(c),
    toggle(c, force) { const want = force === undefined ? !s._classes.has(c) : force; if (want) s._classes.add(c); else s._classes.delete(c); return want; } }; }
  get className() { return [...this._classes].join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this.tag === "#text" ? (this._text || "") : this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = []; if (this.tag === "#text") this._text = String(v); else if (v !== "") { const t = new Node("#text"); t._text = String(v); this.children.push(t); } }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k); }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(ev, fn) { (this._l[ev] = this._l[ev] || []).push(fn); }
  removeEventListener() {}
  dispatch(ev, e = {}) { for (const fn of (this._l[ev] || []).slice()) fn({ type: ev, target: this, currentTarget: this, preventDefault() {}, ...e }); }
  click() { this.dispatch("click"); }
  append(...kids) { for (const k of kids) { if (k instanceof Node) { if (k.parentNode) { const i = k.parentNode.children.indexOf(k); if (i >= 0) k.parentNode.children.splice(i, 1); } k.parentNode = this; } this.children.push(k); } }
  replaceChildren() { for (const k of this.children) if (k instanceof Node) k.parentNode = null; this.children = []; }
  remove() { if (this.parentNode) { const i = this.parentNode.children.indexOf(this); if (i >= 0) this.parentNode.children.splice(i, 1); this.parentNode = null; } }
  contains(n) { return this === n || this.children.some((c) => c.contains && c.contains(n)); }
  get childNodes() { return this.children; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() { Node.focused = this; }
  scrollIntoView() {}
}
const walk = (n) => n.children.flatMap((c) => [c, ...walk(c)]);
const all = (root, pred) => walk(root).filter(pred);
const byData = (root, k, v) => all(root, (n) => n.getAttribute && n.getAttribute(k) === v);
const one = (root, k, v) => byData(root, k, v)[0] || null;
const rows = (root) => all(root, (n) => n.hasAttribute && n.hasAttribute("data-home-row"));
const text = (n) => (n ? n.textContent : "");

const tick = async (n = 12) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };

// ---- fixtures: what the console answers ----------------------------------------------------------------------------
const profile = (id, name, over = {}) => ({ id, name, position: "executor", model: { tool: "claude", model_id: "" }, enabled: true, launch_mode: "safe", ...over });
const cardOf = (p, over = {}) => ({ id: p.id, name: p.name, position: p.position, tool: p.model.tool, engine: p.model.tool + "-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false, ...over });
const chatRow = (id, profileId, over = {}) => ({ id, profile_id: profileId, engine: "claude-chat", created_at: 1000, last_at: 2000, last_kind: "reply", last_text: "好", turns: 1, spent_usd: "0.01", open: false, waiting: false, problem: null, ...over });
const CEO = profile("p-ceo", "小執", { position: "planner" });
const ACCOUNTANT = profile("p-acc", "小帳", { position: "executor" });

function world(over = {}) {
  const profiles = over.profiles || [CEO, ACCOUNTANT];
  return {
    config: { advanced_mode: false, setup_done: true, first_ceo_id: "", onboarding_dismissed: true, ...(over.config || {}) },
    profiles,
    chats: over.chats || [],
    cards: over.cards || profiles.map((p) => cardOf(p)),
    lamp: over.lamp || "green",
    routines: over.routines || [],
    waiting: over.waiting || [],
    flows: over.flows || [],
    meetings: over.meetings || [],
    staffing: over.staffing || [],
    dispatch: over.dispatch || [],
    groups: over.groups || [],
    live: over.live || { runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } },
    tools: over.tools || [{ id: "claude", ready: true, state: "ready" }],
    support: over.support || { state: "verified", detected: "2.1.318" },       // what GET /api/chats says of the chat support (Claude Code checked for chat)
    tasks: over.tasks || [],
    fail: over.fail || {},
    posts: over.posts || {},
  };
}

function boot(hash, W, extra = {}) {
  const ids = new Map();
  const log = [];
  const docListeners = {};
  const winListeners = {};
  const mkId = (id, tag = "div") => { const n = new Node(tag); n.setAttribute("id", id); ids.set(id, n); return n; };
  const main = mkId("main", "main");
  mkId("toast");
  mkId("scan-status");
  mkId("advanced-note", "p");
  mkId("waiting-bar");
  const side = new Node("nav"); side._classes.add("side");
  const body = new Node("body");
  const skip = new Node("a");
  const location = { hash, pathname: "/", search: "" };
  const history = { replaceState: (_s, _t, url) => { location.hash = url.slice(url.indexOf("#")); } };
  const doc = {
    createElement: (t) => new Node(t), createElementNS: (_n, t) => new Node(t), createTextNode: (t) => { const n = new Node("#text"); n._text = String(t); return n; },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (sel) => (sel === "a.skip" ? skip : sel === "nav.side" ? side : null),
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    body, documentElement: new Node("html"), activeElement: null, hidden: false,
  };
  const reply = (status, data) => ({ ok: status < 400, status, headers: { get: () => "application/json" }, json: async () => data });
  const fetchStub = async (url, options = {}) => {
    const method = options.method || "GET";
    const p = String(url).split("?")[0];
    const b = options.body ? JSON.parse(options.body) : null;
    log.push([method, String(url), b]);
    if (extra.fetch) { const r = await extra.fetch(String(url), method, b, W); if (r) return r; }
    if (W.fail[`${method} ${p}`]) return reply(W.fail[`${method} ${p}`].status || 500, W.fail[`${method} ${p}`].body || { error: "壞了" });
    if (method === "GET") {
      if (p === "/api/config") return reply(200, { config: W.config, state_dir: "/x", runtime_socket: "" });
      if (p === "/api/agent-profiles") return reply(200, { ok: true, profiles: W.profiles });
      if (p === "/api/agent-builder/catalog") return reply(200, { ok: true, tool_list: [], skills: [] });
      if (p === "/api/chats") return reply(200, { chats: W.chats, more: 0, cards: W.cards, support: W.support, limits: { per_turn_usd: "0.05", daily_usd: "3" }, ledger: { lamp: W.lamp, spent_usd: "0.2", daily_usd: "3" }, problems: [] });
      if (p === "/api/meetings/ledger") return reply(200, { lamp: W.lamp, spent_usd: "0.2", daily_usd: "3" });
      if (p === "/api/routines") return reply(200, { routines: W.routines, readable: true, cards: W.cards, waiting: W.waiting.filter((r) => r.kind === "routine_due" || r.kind === "routine_missed"), settings: {}, limits: {}, today: {}, autonomy: {} });
      if (p === "/api/waiting") return reply(200, { waiting: W.waiting });
      if (p === "/api/flows") return reply(200, { ok: true, flows: W.flows });
      if (p === "/api/meetings") return reply(200, { meetings: W.meetings });
      if (p === "/api/staffing") return reply(200, { staffing: W.staffing });
      if (p === "/api/dispatch") return reply(200, { dispatch: W.dispatch });
      if (p === "/api/groups") return reply(200, { groups: W.groups });
      if (p === "/api/live") return reply(200, W.live);
      if (p === "/api/tasks") return reply(200, { ok: true, tasks: W.tasks });
      if (p === "/api/setup/tools") return reply(200, { tools: W.tools });
      if (p === "/api/overview") return reply(200, { ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
      if (p === "/api/skills") return reply(200, { skills: [], categories: [] });
      if (p === "/api/roles") return reply(200, { roles: [] });
      return reply(200, {});
    }
    // writes: the test says what comes back
    const k = `${method} ${p}`;
    if (W.posts[k]) { const r = typeof W.posts[k] === "function" ? W.posts[k](b, String(url)) : W.posts[k]; return reply(r.status || 200, r.body || {}); }
    if (k === "POST /api/chats") return reply(200, { chat: { id: "c-new", profile_id: b && b.profile_id } });
    if (/^POST \/api\/chats\/[^/]+\/messages$/.test(k)) return reply(200, { ok: true });
    return reply(200, {});
  };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams,
    window: { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: fetchStub,
    setInterval: (fn) => { ctx.__tick = fn; return 1; }, clearInterval() {},
    setTimeout: (fn) => { if (typeof fn === "function") Promise.resolve().then(fn); return 0; }, clearTimeout() {},
    scrollTo() {}, scrollY: 0, confirm: () => true,
    module: undefined,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(SOURCE, ctx);
  const go = async (to) => { location.hash = to; for (const fn of winListeners.hashchange || []) fn(); await tick(30); };
  return { ctx, main, log, location, ids, go, body };
}
const evalIn = (page, code) => vm.runInContext(code, page.ctx);
const posts = (page) => page.log.filter(([m]) => m !== "GET");
const postsTo = (page, re) => posts(page).filter(([, u]) => re.test(u.split("?")[0]));
async function home(W, hash = "#/", extra) { const page = boot(hash, W, extra); await tick(40); return page; }
const askBox = (page) => one(page.main, "data-home", "ask-input");
const sendBtn = (page) => one(page.main, "data-home", "ask-send");

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); } catch (e) { console.log("FAIL -", name); console.log((e && e.stack) || e); process.exitCode = 1; }
}

// ---- guard 15c: the checks, and a small sample for each that must trip them -------------------------------------------
// 15c: a log of requests [method, url, body]. phase "draw": only GET. phase "typed": still only GET. phase "pressed": at most one POST /api/chats
// (its body only the profile) and exactly `messages` POST to a chat's /messages whose text is the typed words; nothing else is written.
function check15c(log, phase, typed, messages) {
  const bad = [];
  const writes = log.filter(([m]) => m !== "GET");
  if (phase === "draw" || phase === "typed") { for (const [m, u] of writes) bad.push(`${m} ${u} while ${phase}`); return bad; }
  const opens = writes.filter(([m, u]) => m === "POST" && u === "/api/chats");
  const sends = writes.filter(([m, u]) => m === "POST" && /^\/api\/chats\/[^/]+\/messages$/.test(u));
  if (opens.length > 1) bad.push("more than one chat opened");
  for (const [, , b] of opens) if (!b || Object.keys(b).join() !== "profile_id") bad.push("an open that carries more than the profile");
  if (sends.length !== messages) bad.push(`${sends.length} messages, wanted ${messages}`);
  for (const [, , b] of sends) if (!b || b.text !== typed || Object.keys(b).join() !== "text") bad.push("a message that is not the typed words");
  for (const w of writes) if (!opens.includes(w) && !sends.includes(w)) bad.push(`${w[0]} ${w[1]} is not part of the press`);
  return bad;
}

(async () => {
  // ---- 15c: the checks themselves trip ---------------------------------------------------------------------------------
  await test("15c: the checker trips on a POST while drawing or typing, a second open, a changed text, an extra write", () => {
    assert.deepStrictEqual(check15c([["GET", "/api/chats", null]], "draw"), []);
    assert.strictEqual(check15c([["GET", "/api/chats", null], ["POST", "/api/config", {}]], "draw").length, 1, "a write while drawing");
    assert.strictEqual(check15c([["POST", "/api/chats/c1/messages", { text: "x" }]], "typed").length, 1, "a send while typing");
    const ok = [["POST", "/api/chats", { profile_id: "p" }], ["POST", "/api/chats/c1/messages", { text: "hi" }]];
    assert.deepStrictEqual(check15c(ok, "pressed", "hi", 1), []);
    assert.ok(check15c([...ok, ["POST", "/api/chats", { profile_id: "p" }]], "pressed", "hi", 1).length >= 1, "two opens");
    assert.ok(check15c([ok[0], ["POST", "/api/chats/c1/messages", { text: "other" }]], "pressed", "hi", 1).length >= 1, "another text");
    assert.ok(check15c([...ok, ["POST", "/api/chats/c1/messages", { text: "hi" }]], "pressed", "hi", 1).length >= 1, "two sends");
    assert.ok(check15c([...ok, ["POST", "/api/config", { a: 1 }]], "pressed", "hi", 1).length >= 1, "another write");
    assert.ok(check15c([ok[0]], "pressed", "hi", 0).length === 0, "busy: no message wanted");
    assert.ok(check15c(ok, "pressed", "hi", 0).length >= 1, "busy: a message was sent");
  });

  // ---- the home page, normal mode ----------------------------------------------------------------------------------------
  await test("home: title 首頁 (hidden, for the screen reader); waiting, ask, team and today are there, in this order (P50-1: the box comes before the team); the old lobby is not; drawing sends nothing; no amount of money", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")] });
    const page = await home(W);
    assert.strictEqual(text(all(page.main, (n) => n.tag === "h1")[0]), "首頁");
    const order = all(page.main, (n) => n.getAttribute && ["waiting", "team", "today", "ask"].includes(n.getAttribute("data-home"))).filter((n) => n.tag === "section").map((n) => n.getAttribute("data-home"));
    assert.deepStrictEqual(order, ["waiting", "ask", "team", "today"]);
    const t = text(page.main);
    assert.ok(!/US\$|\$|金額|花了|花費/.test(t), "no money on the home page: " + t.match(/US\$[^ ]*|花[^，。]{0,6}/));
    assert.ok(!t.includes("冒險者大廳") && !t.includes("任務告示板") && !t.includes("新手第一局"));
    assert.ok(!one(page.main, "id", "h-board") && !byData(page.main, "data-board", "turn").length, "the old board is for the advanced mode");
    assert.deepStrictEqual(check15c(page.log, "draw"), []);
  });

  await test("home: with nobody waiting (everything read) the waiting block takes no room and says nothing (P50-1: no 現在沒有要你決定的事 line any more); it is not claimed in words either", async () => {
    const page = await home(world());
    assert.ok(one(page.main, "data-home", "waiting").getAttribute("hidden") !== null, "hidden");
    assert.ok(!text(page.main).includes("沒有要你決定的事"));
    assert.strictEqual(rows(page.main).length, 0);
  });

  await test("home: my employees are avatars with a name; a click opens a chat (the one there is) or brings the person to the page that prepares it", async () => {
    const W = world({ chats: [chatRow("c-old", "p-acc")], cards: [cardOf(CEO), cardOf(ACCOUNTANT, { can_chat: false, reason: "這張卡的 AI 工具還沒準備好" })] });
    const page = await home(W);
    const ceoBtn = one(page.main, "data-employee", "p-ceo");
    assert.ok(ceoBtn && text(ceoBtn).includes("小執") && ceoBtn.getAttribute("title") === "CEO", "the name on the avatar, the position as its tooltip (P50-1)");
    const accBtn = one(page.main, "data-employee", "p-acc");
    assert.ok(text(page.main).includes("這張卡的 AI 工具還沒準備好"), "the reason is under the grey one");
    assert.ok(accBtn.className.includes("home-avatar-off") || accBtn.getAttribute("aria-disabled") === "true", "grey");
    accBtn.click(); await tick(20);
    assert.strictEqual(page.location.hash, "#/chat?profile=p-acc", "not ready: to the page that prepares it");
    assert.strictEqual(posts(page).length, 0);
    ceoBtn.click(); await tick(20);
    assert.strictEqual(postsTo(page, /^\/api\/chats$/).length, 1, "no chat with the CEO yet: one is opened (it costs nothing)");
    assert.strictEqual(page.location.hash, "#/chat/c-new");
    assert.strictEqual(postsTo(page, /messages/).length, 0, "and nothing is sent");
  });

  await test("home: an employee who has a chat gets that chat, newest first; a chat opened by a routine or with a problem is not the one", async () => {
    const W = world({ chats: [chatRow("c-routine", "p-ceo", { last_at: 5000 }), chatRow("c-bad", "p-ceo", { last_at: 4000, problem: "壞了" }), chatRow("c-new1", "p-ceo", { last_at: 3000 }), chatRow("c-old1", "p-ceo", { last_at: 1000 })],
      routines: [{ id: "r1", name: "晨間整理", enabled: true, days: [0, 1, 2, 3, 4, 5, 6], times: ["08:00"], runs: [{ chat_id: "c-routine", state: "done" }] }] });
    const page = await home(W);
    one(page.main, "data-employee", "p-ceo").click(); await tick(20);
    assert.strictEqual(page.location.hash, "#/chat/c-new1");
    assert.strictEqual(postsTo(page, /^\/api\/chats$/).length, 0);
  });

  // ---- the ask box (15c) -----------------------------------------------------------------------------------------------------
  await test("15c ask: typing sends nothing; one press with no chat yet opens one chat and sends exactly one message with the typed words, then goes to the chat", async () => {
    const page = await home(world());
    const box = askBox(page);
    box.value = "幫我整理下個月的開銷"; box.dispatch("input"); box.dispatch("keydown", { key: "Enter" }); await tick(5);
    assert.deepStrictEqual(check15c(page.log, "typed"), []);
    sendBtn(page).click(); await tick(30);
    assert.deepStrictEqual(check15c(page.log, "pressed", "幫我整理下個月的開銷", 1), []);
    assert.strictEqual(postsTo(page, /^\/api\/chats$/).length, 1);
    assert.strictEqual(page.location.hash, "#/chat/c-new");
    sendBtn(page).click(); await tick(10);
  });

  await test("15c ask: with a chat already there only the message goes; an empty box sends nothing", async () => {
    const page = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    sendBtn(page).click(); await tick(10);
    assert.strictEqual(posts(page).length, 0, "empty box: nothing");
    askBox(page).value = "  你好  "; sendBtn(page).click(); await tick(30);
    assert.deepStrictEqual(check15c(page.log, "pressed", "  你好  ", 1), []);
    assert.strictEqual(postsTo(page, /^\/api\/chats$/).length, 0);
    assert.strictEqual(page.location.hash, "#/chat/c1");
  });

  await test("15c ask: the CEO is answering (a turn is open) or a card waits: no message is sent, the words wait in the box of the CEO's chat", async () => {
    for (const busy of [{ open: true }, { open: true, waiting: true }]) {
      const page = await home(world({ chats: [chatRow("c1", "p-ceo", busy)] }));
      askBox(page).value = "晚點再說的話"; sendBtn(page).click(); await tick(30);
      assert.deepStrictEqual(check15c(page.log, "pressed", "晚點再說的話", 0), []);
      assert.strictEqual(page.location.hash, "#/chat/c1");
      assert.strictEqual(evalIn(page, 'ceoDrafts.get("c1")'), "晚點再說的話", "the box of that chat will have them");
    }
  });

  await test("15c ask: the chat is read again at the press: a CEO that began answering after the page was drawn is not sent to", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")] });
    const page = await home(W);
    W.chats = [chatRow("c1", "p-ceo", { open: true })];
    askBox(page).value = "新的一句"; sendBtn(page).click(); await tick(30);
    assert.strictEqual(postsTo(page, /messages/).length, 0);
    assert.strictEqual(evalIn(page, 'ceoDrafts.get("c1")'), "新的一句");
  });

  await test("ask: a chat that cannot open (the server refuses) leads to the page that prepares it, sends nothing, and keeps the words under the employee's id", async () => {
    const page = await home(world({ posts: { "POST /api/chats": { status: 409, body: { error: "還沒通過聊天驗證" } } } }));
    askBox(page).value = "先留著的話"; sendBtn(page).click(); await tick(30);
    assert.strictEqual(page.location.hash, "#/chat?profile=p-ceo");
    assert.strictEqual(postsTo(page, /messages/).length, 0);
    assert.strictEqual(evalIn(page, 'ceoDrafts.get("p-ceo")'), "先留著的話");
  });

  await test("ask: the limit stopped it: a plain notice with a way to the settings, the words still in the box, nobody moved", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")], posts: { "POST /api/chats/c1/messages": { status: 409, body: { error: "今天的額度已用完（亮紅燈），沒有送出。", code: "red" } } } });
    const page = await home(W);
    askBox(page).value = "還想問一件事"; sendBtn(page).click(); await tick(30);
    const n = one(page.main, "data-limit", "reached");
    assert.ok(n, "the limit notice");
    assert.ok(text(n).includes("沒有花錢"));
    assert.strictEqual(one(n, "data-limit", "go").getAttribute("href"), "#/settings?open=limits");
    assert.ok(text(n).includes("今天的額度已用完（亮紅燈）"), "the original is kept in the details");
    assert.strictEqual(askBox(page).value, "還想問一件事");
    assert.notStrictEqual(page.location.hash, "#/chat/c1");
    assert.ok(!/US\$/.test(text(page.main)));
  });

  await test("ask: another refusal is said as the server said it (plain where the table knows it), the words stay, and the button works again", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")], posts: { "POST /api/chats/c1/messages": { status: 409, body: { error: "員工正在回覆，請等這回合結束。", code: "busy" } } } });
    const page = await home(W);
    askBox(page).value = "你好"; sendBtn(page).click(); await tick(30);
    assert.ok(text(one(page.main, "data-home", "ask-result")).includes("員工正在回覆"));
    assert.strictEqual(askBox(page).value, "你好");
    assert.ok(!sendBtn(page).disabled);
  });

  await test("ask: today's lamp is red: pressing sends nothing, says it in plain words with the way to the settings, the words stay", async () => {
    const page = await home(world({ lamp: "red", chats: [chatRow("c1", "p-ceo")] }));
    askBox(page).value = "試試看"; sendBtn(page).click(); await tick(30);
    assert.strictEqual(posts(page).length, 0);
    assert.ok(one(one(page.main, "data-home", "ask"), "data-limit", "reached"));
    assert.strictEqual(askBox(page).value, "試試看");
  });

  await test("ask: the CEO cannot chat yet: no box, the reason, one way to prepare it; employees without a CEO: one line and the way to make one", async () => {
    const W = world({ cards: [cardOf(CEO, { can_chat: false, reason: "這個 AI 工具還沒通過聊天驗證" }), cardOf(ACCOUNTANT)] });
    const page = await home(W);
    const ask = one(page.main, "data-home", "ask");
    assert.ok(!askBox(page));
    assert.ok(text(ask).includes("這個 AI 工具還沒通過聊天驗證"));
    assert.ok(all(ask, (n) => n.tag === "a" && n.getAttribute("href") === "#/chat?profile=p-ceo").length === 1);
    const none = await home(world({ profiles: [ACCOUNTANT] }));
    const ask2 = one(none.main, "data-home", "ask");
    assert.ok(!askBox(none));
    assert.ok(text(ask2).includes("先建立一位 CEO"));
    assert.ok(all(ask2, (n) => n.tag === "a" && n.getAttribute("href") === "#/ceo").length === 1);
  });

  // ---- fix47: a CEO whose AI tool cannot chat yet is not sent to (the real-Mac check found a dead end here) -------------------------------
  await test("fix47 ask: the CEO's tool is held back by an administrator's policy or not checked for chat: no box, one line with the real reason, one way to the page that prepares it", async () => {
    for (const [support, reason] of [[{ state: "policy", detected: "2.1.318" }, "這台電腦的 Claude Code 有管理員設定，VBear 不能用它聊天"], [{ state: "unverified", detected: "2.1.318" }, "先處理這一步才能和 小執 聊天"]]) {
      const page = await home(world({ support, chats: [chatRow("c1", "p-ceo")] }));
      const ask = one(page.main, "data-home", "ask");
      assert.ok(!askBox(page) && !sendBtn(page), support.state + ": no box to type into");
      assert.ok(text(ask).includes(reason), text(ask));
      assert.strictEqual(all(ask, (n) => n.tag === "a" && n.getAttribute("href") === "#/chat?profile=p-ceo").length, 1);
      assert.strictEqual(posts(page).length, 0);
    }
  });

  await test("fix47 ask: the tool stopped being able to chat after the page was drawn: a press sends nothing, opens nothing, keeps the words under the employee's id and leads to the page that says why", async () => {
    for (const chats of [[], [chatRow("c1", "p-ceo")]]) {
      const W = world({ chats });
      const page = await home(W);
      W.support = { state: "policy", detected: "2.1.318" };
      askBox(page).value = "晚一點要用的話"; sendBtn(page).click(); await tick(30);
      assert.strictEqual(posts(page).length, 0, "no chat opened, no message sent");
      assert.strictEqual(page.location.hash, "#/chat?profile=p-ceo");
      assert.strictEqual(evalIn(page, 'ceoDrafts.get("p-ceo")'), "晚一點要用的話");
    }
  });

  // ---- fix47b (review R2, Q1/Q2): only a state that was read and says "start" may open a chat or send ---------------------------------------
  await test("fix47b ask: a state that cannot be read, or a missing employee card, is not a go: nothing is opened or sent, the words wait under the employee's id and the page that says so is shown", async () => {
    const unreadable = (W) => { W.fail["GET /api/chats"] = { status: 503, body: { error: "壞了" } }; };
    const noCard = (W) => { W.cards = []; };
    const noSupport = (W) => { W.support = undefined; };
    for (const [name, spoil] of [["GET fails", unreadable], ["no card", noCard], ["no support", noSupport]]) {
      for (const chats of [[], [chatRow("c1", "p-ceo")]]) {
        const W = world({ chats });
        const page = await home(W);
        spoil(W);
        askBox(page).value = "幫我排下週的事"; sendBtn(page).click(); await tick(30);
        assert.strictEqual(posts(page).length, 0, `${name} (${chats.length} chats): no chat opened, no message sent`);
        assert.strictEqual(page.location.hash, "#/chat?profile=p-ceo", name);
        assert.strictEqual(evalIn(page, 'ceoDrafts.get("p-ceo")'), "幫我排下週的事", name);
      }
    }
  });

  await test("fix47b employees: a click on an employee when the state cannot be read opens no chat; it goes to the page that says so", async () => {
    const W = world();
    const page = await home(W);
    W.fail["GET /api/chats"] = { status: 503, body: { error: "壞了" } };
    one(page.main, "data-employee", "p-ceo").click(); await tick(30);
    assert.strictEqual(posts(page).length, 0);
    assert.strictEqual(page.location.hash, "#/chat?profile=p-ceo");
  });

  await test("fix47b ask: read as ready, then refused by the server as 'not checked for chat': the state is read again, the real reason (the administrator's policy) is said in plain words with a link to the page that prepares it, the server's sentence is behind 「技術細節」, and the words stay in the box", async () => {
    const SERVER = "這個版本的聊天模式還沒有在這台 Mac 上通過驗證，不會啟動。（Claude Code 2.1.318 的聊天模式還沒有通過驗證。處理方式：先執行聊天模式的驗證（會花一點額度）。）";
    const W = world({ chats: [chatRow("c1", "p-ceo")] });
    W.posts["POST /api/chats/c1/messages"] = () => { W.support = { state: "policy", detected: "2.1.318" }; return { status: 409, body: { ok: false, error: SERVER, code: "unverified" } }; };
    const page = await home(W);
    askBox(page).value = "請幫我整理"; sendBtn(page).click(); await tick(40);
    assert.strictEqual(postsTo(page, /messages/).length, 1, "the one send that was refused");
    assert.strictEqual(postsTo(page, /^\/api\/chats$/).length, 0);
    const n = one(page.main, "data-home", "not-ready");
    assert.ok(n, "a notice");
    const outside = text(n).split(SERVER).join("");
    assert.ok(outside.includes("這台電腦的 Claude Code 有管理員設定，VBear 不能用它聊天"), outside);
    assert.ok(!/先執行聊天模式的驗證|還沒有在這台 Mac/.test(outside.split("技術細節").join("")), "the server's sentence is only in the fold");
    assert.ok(text(n).includes(SERVER), "kept whole");
    assert.ok(all(n, (x) => x.tag === "details").length === 1, "behind the fold");
    const links = all(n, (x) => x.tag === "a" && x.getAttribute("href") === "#/chat?profile=p-ceo");
    assert.strictEqual(links.length, 1);
    assert.strictEqual(askBox(page).value, "請幫我整理", "the words stay in the box");
    links[0].click();
    assert.strictEqual(evalIn(page, 'ceoDrafts.get("p-ceo")'), "請幫我整理", "and wait under the employee's id when the link is followed");
  });

  await test("R3 ask: a chat made, then the send refused and the state unreadable: the notice does not say no chat was made", async () => {
    const W = world({ chats: [] });
    W.posts["POST /api/chats/c-new/messages"] = () => { W.support = undefined; return { status: 409, body: { ok: false, error: "還沒通過驗證", code: "unverified" } }; };
    const page = await home(W);
    askBox(page).value = "請幫我整理"; sendBtn(page).click(); await tick(40);
    assert.strictEqual(postsTo(page, /^\/api\/chats$/).length, 1, "the chat was made");
    assert.strictEqual(postsTo(page, /messages/).length, 1, "the one send that was refused");
    const shown = text(page.main);
    assert.ok(shown.includes("讀不到這位員工現在能不能聊天的狀態"), shown);
    assert.ok(!shown.includes("沒有開對話"), "it must not deny the chat that was made");
    assert.strictEqual(askBox(page).value, "請幫我整理", "the words stay in the box");
  });

  await test("fix47 ask: an employee's avatar with a chat already there still opens it (reading is free), but one with none and a tool that cannot chat goes to the page that prepares it", async () => {
    const W = world({ support: { state: "unverified", detected: "2.1.318" }, chats: [chatRow("c-old", "p-acc")] });
    const page = await home(W);
    one(page.main, "data-employee", "p-acc").click(); await tick(20);
    assert.strictEqual(page.location.hash, "#/chat/c-old");
    one(page.main, "data-employee", "p-ceo").click(); await tick(20);
    assert.strictEqual(page.location.hash, "#/chat?profile=p-ceo");
    assert.strictEqual(posts(page).length, 0);
  });

  await test("fix47 ask: a chat the server labels with a routine's title is never the chat with the employee, even when the routines list does not name it (a deleted routine, a run older than the last ten)", async () => {
    const W = world({ chats: [chatRow("c-routine", "p-ceo", { last_at: 9000, routine_title: "已刪除的早報" }), chatRow("c-mine", "p-ceo", { last_at: 1000 })], routines: [] });
    const page = await home(W);
    one(page.main, "data-employee", "p-ceo").click(); await tick(20);
    assert.strictEqual(page.location.hash, "#/chat/c-mine");
    askBox(page).value = "你好"; sendBtn(page).click(); await tick(30);
    assert.deepStrictEqual(postsTo(page, /messages/).map(([, u]) => u), ["/api/chats/c-mine/messages"]);
    const only = world({ chats: [chatRow("c-routine", "p-ceo", { routine_title: "早報" })] });
    const p2 = await home(only);
    askBox(p2).value = "你好"; sendBtn(p2).click(); await tick(30);
    assert.strictEqual(postsTo(p2, /^\/api\/chats$/).length, 1, "none that is a personal chat: one is opened");
    assert.strictEqual(p2.location.hash, "#/chat/c-new");
  });

  await test("fix47 first run: a tool's card says 'can chat' only when a chat can start; a policy or an unchecked tool is said as it is (P52-1: the card of the picker, in place of step 1)", async () => {
    const READY = (id, over = {}) => ({ id, ready: true, state: "ready", installed: true, version: "1.2.3", login: "logged_in", ...over });
    const card = async (support, tools, id = "claude") => { const page = await home(world({ profiles: [], cards: [], support, tools: tools || [READY("claude")] })); return { page, node: one(one(page.main, "data-home", "first-run"), "data-setup-pick", id) }; };
    const ok = await card({ state: "verified", detected: "2.1.318" });
    assert.ok(text(ok.node).includes("可以聊天"));
    const held = await card({ state: "policy", detected: "2.1.318" });
    assert.ok(!text(held.node).includes("可以聊天") && text(held.node).includes("管理員設定"), text(held.node));
    const unchecked = await card({ state: "unverified", detected: "2.1.318" });
    assert.ok(!text(unchecked.node).includes("可以聊天") && text(unchecked.node).includes("安全檢查"), text(unchecked.node));
    const codex = await card({ state: "unknown", codex: { state: "ready" } }, [READY("codex", { chat_login: { state: "logged_in", problem: "" } })], "codex");
    assert.ok(text(codex.node).includes("可以聊天"), "any tool that can chat says so");
    assert.ok(all(held.page.main, (n) => n.tag === "a" && n.getAttribute("href") === "#/setup" && n.getAttribute("data-home") === "first-setup-link").length === 1, "still the way to look at all the tools");
  });

  await test("fix47 look: the home box (now the rounded .home-box of P50-1) and the settings' own limit box have the other boxes' style (border, panel colour, the page's font), not the browser's grey box", () => {
    const ruleOf = (sel) => CSS.split("}").filter((r) => r.split("{")[0].split(",").some((x) => x.trim() === sel)).join(";");
    const box = ruleOf(".home-box");
    assert.ok(/border:\s*1px solid var\(--line-2\)/.test(box) && /background:\s*var\(--panel\)/.test(box), `.home-box: ${box}`);
    assert.ok(/font:\s*inherit/.test(ruleOf(".home-box textarea")), "the textarea in it has the page's font");
    const limit = ruleOf("input[data-limit-input]");
    assert.ok(/border:\s*1px solid var\(--line-2\)/.test(limit) && /background:\s*var\(--panel\)/.test(limit) && /font:\s*inherit/.test(limit), `input[data-limit-input]: ${limit}`);
  });

  await test("ask: the CEO is the first CEO of the config when that card is there, else the first employee whose position is CEO", async () => {
    const boss = profile("p-boss", "老闆", { position: "planner" });
    const page = await home(world({ profiles: [CEO, boss], config: { first_ceo_id: "p-boss" }, chats: [chatRow("c-boss", "p-boss"), chatRow("c-ceo", "p-ceo", { last_at: 9000 })] }));
    askBox(page).value = "你好"; sendBtn(page).click(); await tick(30);
    assert.strictEqual(page.location.hash, "#/chat/c-boss");
  });

  // ---- the three first steps -----------------------------------------------------------------------------------------------
  await test("no employees: the first-run block (the big line, the three cards) and nothing else; nothing is chosen; GET only (P52-1: in place of the three steps)", async () => {
    const page = await home(world({ profiles: [], cards: [] }));
    const first = one(page.main, "data-home", "first-run");
    assert.ok(first);
    assert.ok(text(first).includes("先選一家你有在用的 AI"));
    assert.deepStrictEqual(all(first, (n) => n.getAttribute && n.getAttribute("data-setup-pick")).map((n) => n.getAttribute("data-setup-pick")), ["claude", "codex", "agy"]);
    assert.strictEqual(one(page.main, "data-home", "first-steps"), null, "the old three steps are not drawn");
    assert.strictEqual(all(page.main, (n) => n.tag === "a" && n.getAttribute("href") === "#/ceo").length, 0);
    assert.ok(!one(page.main, "data-home", "ask") && !one(page.main, "data-home", "team"));
    assert.deepStrictEqual(check15c(page.log, "draw"), []);
    const none = await home(world({ profiles: [], cards: [], tools: [{ id: "claude", ready: false, state: "not_installed" }], support: { state: "unknown", detected: null } }));
    assert.ok(!text(one(one(none.main, "data-home", "first-run"), "data-setup-pick", "claude")).includes("可以聊天"), "no ready tool: not said");
  });

  await test("no employees: what waits for the person is still listed above the first-run block", async () => {
    const page = await home(world({ profiles: [], cards: [], waiting: [{ kind: "routine_due", run_id: "run1", routine_id: "r1", name: "晨間整理", slot: "2026-11-10T08:00" }] }));
    const order = all(page.main, (n) => n.tag === "section" && n.getAttribute("data-home")).map((n) => n.getAttribute("data-home"));
    assert.deepStrictEqual(order, ["waiting", "first-run"]);
    assert.strictEqual(rows(page.main).length, 1);
  });

  // ---- waiting: everything the old lobby and the line over every page listed, in both modes -----------------------------
  const hour = "2026-11-10T08:00";
  function busyWorld(advanced) {
    return world({
      config: { advanced_mode: advanced },
      waiting: [
        { kind: "routine_due", run_id: "run1", routine_id: "r1", name: "晨間整理", slot: hour },
        { kind: "routine_missed", run_id: "run2", routine_id: "r2", name: "週報", slot: hour, count: 2, too_old: false },
        { kind: "dispatch_resume", dispatch_id: "d-aaaaaaaaaaaa", name: "整理照片", reason: "daily_limit", state: "counting", text: "明天 0 點接著做" },
        { kind: "group_resume", group_id: "g-aaaaaaaaaaaa", name: "家人群", state: "counting", text: "明天 0 點接著做" },
      ],
      flows: [{ id: "flow-000000000001", task_title: "改版", task_missing: false, phase: { key: "awaiting_approval", label: "等核准", reason: "等核准的說明" }, attention: true, attention_reason: "等你核准計畫",
        automation: { mode: "manual", held: false, step_label: "" }, roles: { planner: { name: "P" }, executor: { name: "E" }, reviewers: [] }, executor_live: { label: "x", reason: "y" }, latest_review: null, binding: { detail: "" } }],
      meetings: [{ id: "m-000000000001", topic: "下個月計畫", status: "waiting_chairman", created_at: 1, spent_usd: "0.2", blocked: false }],
      staffing: [{ id: "s-000000000001", task_id: "t1", status: "ready", created_at: 1, spent_usd: "0.1", blocked: false }],
      dispatch: [{ id: "d-bbbbbbbbbbbb", state: "proposed", title: "寄送清單", steps: 3, created_at: 2, blocked: false }, { id: "d-aaaaaaaaaaaa", state: "paused", title: "整理照片", steps: 2, created_at: 1, blocked: false }],
      groups: [{ id: "g-bbbbbbbbbbbb", name: "工作群", state: "idle", waiting: true, members: [], last_at: 3 }, { id: "g-aaaaaaaaaaaa", name: "家人群", state: "paused", waiting: false, members: [], last_at: 2 }],
      live: { runtime: { available: true, problems: [] }, sessions: [{ terminal_id: "t-a", pane_id: "pane-a", workspace_id: "w", workspace_label: "w", agent: "claude", status: "waiting", role_label: "工人甲", title: "", activity: null, models_observed: {}, skills_used: [], usage_matched: false, supported_tool: true, project_id: "p1" }], attention: ["t-a"], projects: [], panes: [], usage: { sessions: [] } },
      lamp: "red",
    });
  }
  const rowSummary = (page) => rows(page.main).map((r) => [r.getAttribute("data-home-row"), text(r).replace(/\s+/g, " ")]);

  await test("waiting: every kind the old lobby and the top line listed is a row, and the normal and the advanced mode list the same rows", async () => {
    const normal = await home(busyWorld(false));
    const advanced = await home(busyWorld(true));
    assert.deepStrictEqual(rowSummary(normal), rowSummary(advanced), "not a row fewer in the normal mode");
    const kinds = rowSummary(normal).map(([k]) => k);
    for (const k of ["routine_due", "routine_missed", "dispatch_resume", "group_resume", "flow", "session", "meeting", "staffing", "dispatch_proposed", "group_waiting", "limit"]) assert.ok(kinds.includes(k), k);
    assert.ok(!kinds.includes("dispatch_paused") && !kinds.includes("group_paused"), "a pause that has its countdown row is not said twice");
    const t = rowSummary(normal).map((r) => r[1]).join("\n");
    for (const w of ["晨間整理", "週報", "整理照片", "家人群", "改版", "工人甲", "下個月計畫", "寄送清單", "工作群"]) assert.ok(t.includes(w), w);
    assert.ok(!/US\$/.test(t), "and no money");
    for (const r of rows(normal.main)) assert.ok(all(r, (n) => n.tag === "a" || n.tag === "button").length >= 1, "each row has an action: " + text(r));
  });

  await test("waiting: a paused dispatch or group without a countdown row is its own row; a damaged or finished record is not", async () => {
    const W = world({ dispatch: [{ id: "d-cccccccccccc", state: "paused", title: "停住的", steps: 2, created_at: 1, blocked: false }, { id: "d-dddddddddddd", state: "paused", title: "壞的", steps: 2, created_at: 1, blocked: true }, { id: "d-eeeeeeeeeeee", state: "done", title: "做完了", steps: 2, created_at: 1, blocked: false }],
      groups: [{ id: "g-cccccccccccc", name: "停住的群", state: "paused", waiting: false, members: [], last_at: 3 }, { id: "g-dddddddddddd", name: "唯讀群", state: "readonly", waiting: true, members: [], last_at: 3 }] });
    const page = await home(W);
    const kinds = rowSummary(page).map(([k]) => k).sort();
    assert.deepStrictEqual(kinds, ["dispatch_paused", "group_paused"]);
  });

  await test("waiting: the limit row appears when today's lamp is red, links to the settings, says no amount; not when it is green or yellow", async () => {
    const red = await home(world({ lamp: "red" }));
    const row = one(red.main, "data-home", "limit-reached");
    assert.ok(row && text(row).includes("今天的用量到上限了") && text(row).includes("明天 0 點"));
    assert.strictEqual(all(row, (n) => n.tag === "a")[0].getAttribute("href"), "#/settings?open=limits");
    assert.ok(!/US\$/.test(text(row)));
    for (const lamp of ["green", "yellow"]) assert.ok(!one((await home(world({ lamp }))).main, "data-home", "limit-reached"), lamp);
  });

  await test("waiting: 現在開始 and 這次跳過 are the routines page's own requests, one POST each; 補做 and 不用了 likewise", async () => {
    const W = world({ waiting: [{ kind: "routine_due", run_id: "run1", routine_id: "r1", name: "晨間整理", slot: hour }, { kind: "routine_missed", run_id: "run2", routine_id: "r2", name: "週報", slot: hour, count: 1, too_old: false }] });
    const page = await home(W);
    const act = (k) => one(page.main, "data-home-action", k);
    assert.deepStrictEqual(check15c(page.log, "draw"), []);
    act("wait-start").click(); await tick(20);
    assert.deepStrictEqual(posts(page).map(([m, u, b]) => [m, u, b]), [["POST", "/api/routines/waiting/run1", { action: "start" }]]);
    const p2 = await home(W);
    one(p2.main, "data-home-action", "wait-skip").click(); await tick(20);
    assert.deepStrictEqual(posts(p2).map(([m, u, b]) => [m, u, b]), [["POST", "/api/routines/waiting/run1", { action: "skip" }]]);
    const p3 = await home(W);
    one(p3.main, "data-home-action", "missed-run").click(); await tick(20);
    assert.deepStrictEqual(posts(p3).map(([m, u, b]) => [m, u, b]), [["POST", "/api/routines/missed/r2", { action: "run" }]]);
    const p4 = await home(W);
    one(p4.main, "data-home-action", "missed-dismiss").click(); await tick(20);
    assert.deepStrictEqual(posts(p4).map(([m, u, b]) => [m, u, b]), [["POST", "/api/routines/missed/r2", { action: "dismiss" }]]);
  });

  await test("waiting: a read that failed is said, and the empty sentence is not claimed", async () => {
    const W = world({ fail: { "GET /api/meetings": { status: 500, body: { error: "讀不到 meetings.json" } } } });
    const page = await home(W);
    const t = text(one(page.main, "data-home", "waiting"));
    assert.ok(t.includes("讀不到會議"), t);
    assert.ok(!t.includes("現在沒有要你決定的事。"), "not claimed when something could not be read");
    const p2 = await home(world({ fail: { "GET /api/waiting": { status: 500, body: { error: "壞了" } } } }));
    assert.ok(text(one(p2.main, "data-home", "waiting")).includes("讀不到"));
    assert.ok(!text(one(p2.main, "data-home", "waiting")).includes("現在沒有要你決定的事。"));
  });

  await test("waiting: the 5-second refresh repaints the block only when what it shows changed, and leaves the box under it alone", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")] });
    const page = await home(W);
    assert.ok(page.ctx.__tick, "the home page registers a refresh");
    const host = one(page.main, "data-home", "waiting");
    askBox(page).value = "寫到一半";
    const before = host.children.slice();
    await page.ctx.__tick(); await tick(20);
    assert.ok(host.children.every((c, i) => c === before[i]) && host.children.length === before.length, "same data, same nodes");
    W.waiting = [{ kind: "routine_due", run_id: "run9", routine_id: "r1", name: "新的提醒", slot: hour }];
    await page.ctx.__tick(); await tick(20);
    assert.ok(text(host).includes("新的提醒"));
    assert.strictEqual(askBox(page).value, "寫到一半", "the typing is not lost");
    assert.deepStrictEqual(check15c(page.log, "draw"), [], "the refresh reads only");
  });

  await test("the line over every page is not repeated on the home page (the same things are under 等你決定), and is there on the other pages", async () => {
    const W = world({ waiting: [{ kind: "routine_due", run_id: "run1", routine_id: "r1", name: "晨間整理", slot: hour }] });
    const page = await home(W);
    const bar = page.ids.get("waiting-bar");
    assert.ok(bar.hidden === true && !text(bar), "hidden on the home page");
    assert.strictEqual(rows(page.main).length, 1, "and the row is on the page");
    await page.go("#/work");
    assert.ok(bar.hidden === false && text(bar).includes("晨間整理"), "shown on another page");
    await page.go("#/");
    assert.ok(bar.hidden === true, "hidden again on coming back");
  });

  // ---- today -----------------------------------------------------------------------------------------------------------------
  await test("today: how many routines are still to come today and the next one (one grey line, P50-1: the last chats moved to the side bar); no amounts; a read that failed is said, not 0; none to say: no room", async () => {
    const now = new Date(2026, 10, 10, 12, 0, 0);   // Tuesday, 12:00 (the page's clock is passed in)
    const day = (now.getDay() + 6) % 7;
    const rs = [{ id: "r1", name: "記帳提醒", enabled: true, days: [day], times: ["18:00", "07:00"], runs: [], next: { slot: "x", at: now.getTime() / 1000 + 6 * 3600 } },
      { id: "r2", name: "關著的", enabled: false, days: [day], times: ["19:00"], runs: [] }, { id: "r3", name: "別天", enabled: true, days: [(day + 1) % 7], times: ["20:00"], runs: [] }];
    const late = { id: "r9", name: "收工整理", enabled: true, days: [0, 1, 2, 3, 4, 5, 6], times: ["23:59"], runs: [] };   // still to come at any time of the day the test runs
    const page = await home(world({ routines: [late], chats: [chatRow("c1", "p-ceo", { last_at: now.getTime() / 1000 - 600 }), chatRow("c2", "p-acc", { last_at: now.getTime() / 1000 - 86400 * 3 })] }));
    const m = evalIn(page, "typeof homeTodayModel");
    assert.strictEqual(m, "function");
    const model = page.ctx.homeTodayModel(JSON.parse(JSON.stringify({ routines: rs, readable: true })), now);
    assert.strictEqual(model.left, 1);
    assert.strictEqual(model.next.name, "記帳提醒");
    assert.strictEqual(model.next.time, "18:00");
    const t = text(one(page.main, "data-home", "today"));
    assert.ok(t.includes("今天還有 1 件，下一件 23:59「收工整理」") && t.includes("看定時工作"), t);
    assert.ok(!t.includes("小執") && !t.includes("最近聊過"), "the last chats are not on the home page any more");
    assert.ok(!/US\$/.test(t));
    const bad = await home(world({ fail: { "GET /api/routines": { status: 500, body: { error: "讀不到" } } } }));
    const bt = text(one(bad.main, "data-home", "today"));
    assert.ok(bt.includes("讀不到定時工作") && !/今天(還有|沒有)\s*0/.test(bt), bt);
    const none = await home(world());
    assert.ok(one(none.main, "data-home", "today").getAttribute("hidden") !== null && !text(one(none.main, "data-home", "today")), "no routine: the block takes no room");
  });

  await test("team: a list that could not be read says so (not an empty team); a chats list that could not be read does not make anyone grey", async () => {
    const bad = await home(world({ fail: { "GET /api/agent-profiles": { status: 500, body: { error: "壞了" } } } }));
    assert.ok(text(one(bad.main, "data-home", "team")).includes("讀不到員工"));
    assert.ok(!one(bad.main, "data-home", "first-run"), "not the first run for a team nobody could read");
    const nochat = await home(world({ fail: { "GET /api/chats": { status: 500, body: { error: "壞了" } } } }));
    assert.ok(all(nochat.main, (n) => n.getAttribute && n.getAttribute("data-employee") && n.className.includes("home-avatar-off")).length === 0);
  });

  // ---- the advanced mode -------------------------------------------------------------------------------------------------
  await test("advanced mode: the old lobby's parts come back under 進階 (board, task cards, skill search, recent projects), after the new blocks; the normal mode has none", async () => {
    const adv = await home(world({ config: { advanced_mode: true } }));
    const t = text(adv.main);
    const sec = one(adv.main, "data-home", "advanced");
    assert.ok(sec && text(sec).includes("進階"));
    assert.ok(one(sec, "id", "h-board") && one(sec, "id", "h-tasks"));
    const heads = all(sec, (n) => n.tag === "h2").map(text);
    for (const h of ["找技能", "最近的專案"]) assert.ok(heads.includes(h), h);
    const order = all(adv.main, (n) => n.tag === "section" && n.getAttribute("data-home")).map((n) => n.getAttribute("data-home"));
    assert.deepStrictEqual(order, ["waiting", "ask", "team", "today", "advanced"]);
    assert.ok(t.includes("首頁"));
    const normal = await home(world({ config: { advanced_mode: false } }));
    assert.ok(!one(normal.main, "data-home", "advanced") && !one(normal.main, "id", "h-board") && !one(normal.main, "id", "h-tasks"));
    assert.deepStrictEqual(check15c(adv.log, "draw"), []);
  });

  await test("advanced mode: with no employees the first game is under 進階, the first-run block stays on top", async () => {
    const page = await home(world({ profiles: [], cards: [], config: { advanced_mode: true, onboarding_dismissed: false } }));
    const order = all(page.main, (n) => n.tag === "section" && n.getAttribute("data-home")).map((n) => n.getAttribute("data-home"));
    assert.deepStrictEqual(order, ["waiting", "first-run", "advanced"]);
    assert.ok(text(one(page.main, "data-home", "advanced")).includes("新手第一局") || byData(page.main, "id", "h-onboarding").length === 1);
    const normal = await home(world({ profiles: [], cards: [], config: { advanced_mode: false, onboarding_dismissed: false } }));
    assert.ok(!text(normal.main).includes("新手第一局"));
  });

  // ---- the employees' page ----------------------------------------------------------------------------------------------
  await test("employees: a card for each, the avatar and 聊天 open a chat, 設定 and 刪除 are there, 新增員工 on top; the shared things below; no amounts", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")], cards: [cardOf(CEO), cardOf(ACCOUNTANT, { can_chat: false, reason: "還沒準備好" })] });
    const page = await home(W, "#/employees");
    assert.strictEqual(text(all(page.main, (n) => n.tag === "h1")[0]), "員工");
    for (const id of ["p-ceo", "p-acc"]) {
      const card = one(page.main, "data-employee", id);
      assert.ok(card, id);
      for (const a of ["chat", "edit", "delete"]) assert.ok(all(card, (n) => n.getAttribute && n.getAttribute("data-employee-action") === a).length >= 1, `${id} ${a}`);
    }
    assert.ok(text(one(page.main, "data-employee", "p-acc")).includes("還沒準備好"));
    assert.ok(one(page.main, "data-employee-action", "new"));
    const hrefs = all(page.main, (n) => n.tag === "a").map((n) => n.getAttribute("href"));
    for (const h of ["#/memory", "#/shared", "#/chat", "#/office", "#/templates"]) assert.ok(hrefs.includes(h), h);
    assert.ok(!/US\$|角色卡|冒險者/.test(text(page.main)), text(page.main));
    assert.strictEqual(posts(page).length, 0);
    all(one(page.main, "data-employee", "p-ceo"), (n) => n.getAttribute && n.getAttribute("data-employee-action") === "chat")[0].click(); await tick(20);
    assert.strictEqual(page.location.hash, "#/chat/c1");
  });

  await test("fix47 employees: the memory entry does not say every employee knows it (Codex and AGY employees have it off until the person says yes)", async () => {
    const page = await home(world(), "#/employees");
    const t = text(page.main);
    assert.ok(t.includes("可以讓員工帶著的幾句話") && t.includes("你可以選哪些員工帶著"), t);
    assert.ok(!t.includes("每位員工都會知道"));
  });

  await test("employees: 刪除 asks first (nothing is sent until the person agrees); no employees: a plain sentence and the ways to add", async () => {
    const page = await home(world({ chats: [] }), "#/employees");
    all(one(page.main, "data-employee", "p-acc"), (n) => n.getAttribute && n.getAttribute("data-employee-action") === "delete")[0].click(); await tick(20);
    assert.strictEqual(postsTo(page, /delete/).length, 0, "the dialog is open, nothing sent");
    const empty = await home(world({ profiles: [], cards: [] }), "#/employees");
    assert.ok(text(empty.main).includes("還沒有員工"));
    assert.ok(one(empty.main, "data-employee-action", "new"));
    const bad = await home(world({ fail: { "GET /api/agent-profiles": { status: 500, body: { error: "壞了" } } } }), "#/employees");
    assert.ok(text(bad.main).includes("讀不到員工") && !text(bad.main).includes("還沒有員工"));
  });

  // ---- the work page --------------------------------------------------------------------------------------------------------
  await test("work: one link and one sentence for each of the pages of work, all routes that exist; no counts, no amounts", async () => {
    const page = await home(world(), "#/work");
    assert.strictEqual(text(all(page.main, (n) => n.tag === "h1")[0]), "工作");
    const links = all(page.main, (n) => n.getAttribute && n.getAttribute("data-work"));
    assert.deepStrictEqual(links.map((n) => n.getAttribute("data-work")).sort(), ["actions", "chat", "dispatch", "meetings", "my-skills", "routines"]);
    const NAV = evalIn(page, "NAV_PARENT");
    for (const a of links) {
      const route = a.getAttribute("data-work");
      assert.strictEqual(a.getAttribute("href"), `#/${route}`);
      assert.ok(NAV[route], route + " is a page the menu knows");
    }
    const t = text(page.main);
    for (const w of ["對話紀錄", "分配工作", "定時工作", "會議", "常用做法", "AI 自己做了什麼"]) assert.ok(t.includes(w), w);
    assert.ok(!/US\$|\d+\s*(件|個|則)/.test(t));
    assert.strictEqual(page.log.filter(([m]) => m !== "GET").length, 0);
  });

  // ---- source rules -----------------------------------------------------------------------------------------------------------
  await test("source: the new pages use el() only (no innerHTML), no emoji, no outside resource, and the names are the plan's", () => {
    const start = SOURCE.indexOf("// ---------- plain pages (v0.21, P47-2)");
    const end = SOURCE.indexOf("// ---------- end of plain pages");
    assert.ok(start > 0 && end > start, "the section is marked");
    const src = SOURCE.slice(start, end);
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(src));
    assert.ok(!/\p{Extended_Pictographic}/u.test(src));
    assert.ok(!/https?:\/\//.test(src));
    for (const f of ["viewEmployees", "viewWork", "openChatWith", "homeWaiting", "homeToday", "homeAsk", "homeFirstSteps"]) assert.ok(new RegExp(`function ${f}\\b`).test(src), f);
    assert.ok(!/US\$/.test(src), "the home page and the employees' page show no amount");
    for (const k of ["waiting", "team", "today", "ask", "ask-input", "ask-send", "first-steps", "limit-reached"]) assert.ok(src.includes(`"${k}"`), k);
    assert.ok(/\.home-avatar/.test(CSS) && /P47-2 home/.test(CSS), "the CSS has its own marked part");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
})();
