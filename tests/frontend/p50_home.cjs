// P50-1 (v0.23.0 極簡對話 1, ADR 0015): the home page is a greeting and one box. 等你決定 is a pill that opens the list where it is (and takes no room
// when nothing waits); the box is the old 「跟 CEO 說」 box with the same requests; the example sentences only put words in the box; my employees are
// a row of small avatars; today is one grey line; the recent chats moved to the side bar (P50-2).
// Guards 17a (an example sentence sends and asks for nothing) and 17c (only Cmd/Ctrl+Enter sends from the box) are checked here on the page, and in
// tests/test_autonomy_guard.py on the source.
// Runs the whole of web/app.js (with its start-up code) in a vm context against a small synthetic DOM, a fetch stub whose answers can be held back,
// and a clock the test moves by hand. NOT a browser test.
//
// Run: node tests/frontend/p50_home.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this._attrs = {}; this._classes = new Set(); this._l = {}; this.value = ""; this.nodeType = tag === "#text" ? 3 : 1; this.disabled = false; this.open = false; this.parentNode = null; this.hidden = false; this.complete = false; this.naturalWidth = 0; }
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
  focus() { Node.focused = this; if (Node.doc) Node.doc.activeElement = this; }
  scrollIntoView() {}
}
const walk = (n) => n.children.flatMap((c) => [c, ...walk(c)]);
const all = (root, pred) => walk(root).filter(pred);
const byData = (root, k, v) => all(root, (n) => n.getAttribute && n.getAttribute(k) === v);
const one = (root, k, v) => byData(root, k, v)[0] || null;
const rowsOf = (root) => all(root, (n) => n.hasAttribute && n.hasAttribute("data-home-row"));
const loadingNodes = (root) => all(root, (n) => n.hasAttribute && n.hasAttribute("data-home-loading"));
const loadingKeys = (root) => loadingNodes(root).map((n) => n.getAttribute("data-home-loading"));
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
    chatsMore: over.chatsMore || 0,
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
    support: over.support || { state: "verified", detected: "2.1.318" },
    tasks: over.tasks || [],
    fail: over.fail || {},
    posts: over.posts || {},
  };
}

// extra.hold: [path] — a request to that exact path waits until page.release(path) before it is answered (it is logged when sent). extra.bridge: the page has the app's message bridge.
function boot(hash, W, extra = {}) {
  const ids = new Map();
  const log = [];
  const holds = [];
  const docListeners = {};
  const winListeners = {};
  const intervals = [];
  const timers = [];
  let timerId = 0;
  const clock = { now: 1_700_000_000_000 };
  const mkId = (id, tag = "div") => { const n = new Node(tag); n.setAttribute("id", id); ids.set(id, n); return n; };
  const main = mkId("main", "main");
  mkId("toast");
  mkId("scan-status");
  mkId("advanced-note", "p");
  const bar = mkId("waiting-bar");
  const side = new Node("nav"); side._classes.add("side");
  const body = new Node("body");
  const skip = new Node("a");
  // the brand mark of the page: <span class="brand-mark"><img></span>
  const mark = new Node("span"); mark._classes.add("brand-mark");
  const logo = new Node("img"); logo.setAttribute("src", "/logo.svg"); mark.append(logo);
  if (extra.logoFailedBeforeScript) { logo.complete = true; logo.naturalWidth = 0; }
  const location = { hash, pathname: "/", search: "" };
  const history = { replaceState: (_s, _t, url) => { location.hash = url.slice(url.indexOf("#")); } };
  const doc = {
    createElement: (t) => new Node(t), createElementNS: (_n, t) => new Node(t), createTextNode: (t) => { const n = new Node("#text"); n._text = String(t); return n; },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (sel) => (sel === "a.skip" ? skip : sel === "nav.side" ? side : sel === ".brand-mark img" ? (logo.parentNode ? logo : null) : sel === ".brand-mark" ? mark : null),
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    body, documentElement: new Node("html"), activeElement: extra.focused ? new Node("button") : null, hidden: false, title: "VBear",
  };
  Node.doc = doc;
  const reply = (status, data) => ({ ok: status < 400, status, headers: { get: () => "application/json" }, json: async () => data });
  const fetchStub = async (url, options = {}) => {
    const method = options.method || "GET";
    const p = String(url).split("?")[0];
    const b = options.body ? JSON.parse(options.body) : null;
    log.push([method, String(url), b, clock.now]);       // the 4th is the page's clock, for the tests that look at the pace of a read
    for (const h of holds) if (h.path === p) await h.promise;
    if (extra.fetch) { const r = await extra.fetch(String(url), method, b, W); if (r) return r; }
    if (W.fail[`${method} ${p}`]) return reply(W.fail[`${method} ${p}`].status || 500, W.fail[`${method} ${p}`].body || { error: "壞了" });
    if (method === "GET") {
      if (p === "/api/config") return reply(200, { config: W.config, state_dir: "/x", runtime_socket: "" });
      if (p === "/api/agent-profiles") return reply(200, { ok: true, profiles: W.profiles });
      if (p === "/api/agent-builder/catalog") return reply(200, { ok: true, tool_list: [], skills: [] });
      if (p === "/api/chats") return reply(200, { chats: W.chats, more: W.chatsMore, cards: W.cards, support: W.support, limits: { per_turn_usd: "0.05", daily_usd: "3" }, ledger: { lamp: W.lamp, spent_usd: "0.2", daily_usd: "3" }, problems: [] });
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
    const k = `${method} ${p}`;
    if (W.posts[k]) { const r = typeof W.posts[k] === "function" ? W.posts[k](b, String(url)) : W.posts[k]; return reply(r.status || 200, r.body || {}); }
    return reply(200, {});
  };
  class FakeDate extends Date {
    constructor(...a) { if (a.length) super(...a); else super(clock.now); }
    static now() { return clock.now; }
  }
  const sent = [];                      // what the page handed to the app
  const win = { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
  if (extra.bridge) win.webkit = { messageHandlers: { vbearWaiting: { postMessage: (m) => sent.push(m) } } };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams, Date: FakeDate,
    window: win,
    localStorage: { getItem: () => null, setItem() {} },
    fetch: fetchStub,
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; }, clearInterval() {},
    setTimeout: (fn, ms) => { timerId += 1; timers.push({ id: timerId, fn, at: clock.now + (Number(ms) || 0) }); return timerId; },
    clearTimeout: (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); },
    scrollTo() {}, scrollY: 0, confirm: () => true,
    module: undefined,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(SOURCE, ctx);
  const go = async (to) => { location.hash = to; for (const fn of winListeners.hashchange || []) fn(); await tick(30); };
  // moves the clock and runs the timers that are due, in order
  const advance = async (ms) => {
    const end = clock.now + ms;
    for (;;) {
      const due = timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      timers.splice(timers.indexOf(due), 1);
      clock.now = Math.max(clock.now, due.at);
      due.fn();
      await tick(6);
    }
    clock.now = end;
    await tick(10);
  };
  // a request to this exact path waits (is logged when sent, answered when released)
  const fireNow = async () => { for (const t of timers.splice(0)) t.fn(); await tick(10); };    // every timer, whatever its time: timers that fire too early
  const hold = (p) => { let open; const promise = new Promise((r) => { open = r; }); holds.push({ path: p, promise, open }); };
  const release = async (...paths) => { for (const h of holds) if (!paths.length || paths.includes(h.path)) h.open(); await tick(40); };
  for (const p of extra.hold || []) hold(p);
  const tickHome = async () => { const fn = intervals.filter((i) => i.ms === 5000).pop(); if (fn) await fn.fn(); await tick(30); };
  const tickBar = async () => { const fn = intervals.filter((i) => i.ms === 30000).pop(); if (fn) await fn.fn(); await tick(30); };
  return { ctx, main, log, location, ids, go, body, doc, bar, logo, mark, sent, advance, fireNow, hold, release, tickHome, tickBar, intervals };
}
const evalIn = (page, code) => vm.runInContext(code, page.ctx);
const posts = (page) => page.log.filter(([m]) => m !== "GET");
async function home(W, hash = "#/", extra) { const page = boot(hash, W, extra); await tick(60); return page; }

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); } catch (e) { console.log("FAIL -", name); console.log((e && e.stack) || e); process.exitCode = 1; }
}
// ---- the checks of 17a and 17c, and a small sample for each that must trip them ----------------------------------------------------
const EXAMPLES = ["幫我整理今天的待辦", "幫我寫一篇貼文", "每天早上給我一份摘要"];
// 17a: pressing an example sentence: no request at all, the box holds exactly that sentence, and the box has the focus.
function check17a(log, before, box, doc, sentence) {
  const bad = [];
  if (log.length !== before) bad.push(`${log.length - before} request(s) after the press`);
  if (box.value !== sentence) bad.push(`the box holds ${JSON.stringify(box.value)}`);
  if (doc.activeElement !== box) bad.push("the box has no focus");
  return bad;
}
// 17c: the keys of the box: only Enter together with Cmd or Ctrl sends; a request log says how many sends there were.
async function keySends(page, box, ev) {
  const before = page.log.filter(([m, u]) => m === "POST" && /\/messages$/.test(u)).length;
  box.dispatch("keydown", ev);
  await tick(30);
  return page.log.filter(([m, u]) => m === "POST" && /\/messages$/.test(u)).length - before;
}
const askBox = (page) => one(page.main, "data-home", "ask-input");
const sendBtn = (page) => one(page.main, "data-home", "ask-send");
const pill = (page) => one(page.main, "data-home", "waiting-pill");
const waitingBlock = (page) => one(page.main, "data-home", "waiting");
const rowsList = (page) => one(page.main, "data-home", "waiting-rows");
const hiddenOf = (n) => !!n && n.getAttribute("hidden") !== null;
const DUE = { kind: "routine_due", name: "晨間整理", run_id: "run-1", slot: "2026-11-10T08:00" };
const DUE2 = { kind: "routine_missed", name: "記帳提醒", routine_id: "r9", count: 2 };
const ALWAYS = { id: "r1", name: "收工整理", enabled: true, days: [0, 1, 2, 3, 4, 5, 6], times: ["23:59"], runs: [] };
const GETS = ["/api/overview", "/api/skills", "/api/roles", "/api/live", "/api/flows", "/api/tasks", "/api/agent-profiles", "/api/agent-builder/catalog", "/api/chats",
  "/api/routines", "/api/waiting", "/api/meetings/ledger", "/api/meetings", "/api/staffing", "/api/dispatch", "/api/groups", "/api/setup/tools"];

(async () => {
  await test("17a/17c: the checkers trip on a request after an example, a wrong sentence, a missing focus, and on a send by a plain Enter", async () => {
    const box = new Node("textarea"); box.value = "x";
    const doc = { activeElement: box };
    assert.deepStrictEqual(check17a([[1], [2]], 2, box, doc, "x"), []);
    assert.strictEqual(check17a([[1], [2], [3]], 2, box, doc, "x").length, 1, "a request");
    assert.strictEqual(check17a([[1]], 1, box, doc, "y").length, 1, "another sentence");
    assert.strictEqual(check17a([[1]], 1, box, { activeElement: null }, "x").length, 1, "no focus");
    const fake = { log: [], };
    const sender = { dispatch: (_ev, e) => { if (e.key === "Enter") fake.log.push(["POST", "/api/chats/c/messages"]); } };
    assert.strictEqual(await keySends(fake, sender, { key: "Enter" }), 1, "the checker sees a plain Enter that sends");
  });

  // ---- the shape of the page ----------------------------------------------------------------------------------------------
  await test("home: a hidden title for the screen reader, then waiting, the greeting and the box, my employees, today; the old title and lede are gone", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")], routines: [ALWAYS], waiting: [DUE] });
    const page = await home(W);
    const h1s = all(page.main, (n) => n.tag === "h1");
    assert.strictEqual(h1s.length, 1, "one h1");
    assert.strictEqual(text(h1s[0]), "首頁");
    assert.ok(h1s[0].className.includes("sr-only"), "visually hidden, still read by a screen reader");
    assert.ok(!all(page.main, (n) => n.className === "lede").length, "the sentence under the title is gone");
    assert.ok(!text(page.main).includes("這裡看有什麼等你決定"));
    assert.strictEqual(text(one(page.main, "data-home", "greeting")), "今天想做什麼？");
    const order = all(page.main, (n) => n.tag === "section" && n.getAttribute("data-home")).map((n) => n.getAttribute("data-home"));
    assert.deepStrictEqual(order, ["waiting", "ask", "team", "today"]);
    assert.ok(!/US\$|金額|花了|花費/.test(text(page.main)), "no money on the home page");
    assert.deepStrictEqual(posts(page), [], "drawing sends nothing");
  });

  await test("home: the old lobby's words are not there: no 我的員工 heading, no 點頭像就能聊, no 想做什麼？跟 CEO 說 heading, no 最近聊過", async () => {
    const page = await home(world({ chats: [chatRow("c1", "p-ceo")], routines: [ALWAYS] }));
    const t = text(page.main);
    for (const gone of ["點頭像就能聊", "想做什麼？跟 CEO 說", "最近聊過", "最近還沒聊過天"]) assert.ok(!t.includes(gone), gone);
    assert.ok(!all(page.main, (n) => n.tag === "h2").some((n) => ["我的員工", "今天", "等你決定"].includes(text(n))), "no block titles");
  });

  await test("home: a person with nobody waiting and nothing to say about it sees no waiting block at all (it is hidden, nothing says nobody waits)", async () => {
    const page = await home(world());
    assert.ok(hiddenOf(waitingBlock(page)), "the block takes no room");
    assert.ok(!pill(page));
    assert.ok(!/沒有要你決定的事/.test(text(page.main)), "not worded either");
    assert.strictEqual(rowsOf(page.main).length, 0);
  });

  // ---- 等你決定 as a pill -----------------------------------------------------------------------------------------------------
  await test("waiting: with N things waiting there is one pill 有 N 件事等你決定, closed; pressing it opens the same list where it is, and again closes it", async () => {
    const page = await home(world({ waiting: [DUE, DUE2] }));
    assert.ok(!hiddenOf(waitingBlock(page)));
    assert.strictEqual(text(pill(page)), "有 2 件事等你決定");
    assert.strictEqual(pill(page).tag, "button");
    assert.strictEqual(pill(page).getAttribute("aria-expanded"), "false");
    const list = rowsList(page);
    assert.strictEqual(pill(page).getAttribute("aria-controls"), list.getAttribute("id"), "aria-controls names the list");
    assert.ok(hiddenOf(list), "closed");
    assert.strictEqual(rowsOf(page.main).length, 2, "the rows are the old rows");
    pill(page).click();
    assert.strictEqual(pill(page).getAttribute("aria-expanded"), "true");
    assert.ok(!hiddenOf(list), "open");
    pill(page).click();
    assert.strictEqual(pill(page).getAttribute("aria-expanded"), "false");
    assert.ok(hiddenOf(rowsList(page)));
    assert.deepStrictEqual(posts(page), [], "opening and closing sends nothing");
  });

  await test("waiting: the list is the old one: the buttons of a row are the routines page's own requests (one POST each)", async () => {
    const page = await home(world({ waiting: [DUE] }));
    pill(page).click();
    const start = all(page.main, (n) => n.getAttribute && n.getAttribute("data-home-action") === "wait-start")[0];
    assert.ok(start && text(start) === "現在開始");
    start.click();
    await tick(40);
    assert.deepStrictEqual(posts(page).map(([m, u, b]) => [m, u, b]), [["POST", "/api/routines/waiting/run-1", { action: "start" }]]);
  });

  await test("waiting: an open list stays open when the 5-second refresh changes the rows, and the pill's number follows", async () => {
    const W = world({ waiting: [DUE] });
    const page = await home(W);
    pill(page).click();
    assert.strictEqual(text(pill(page)), "有 1 件事等你決定");
    W.waiting = [DUE, DUE2];
    await page.tickHome();
    assert.strictEqual(text(pill(page)), "有 2 件事等你決定");
    assert.strictEqual(pill(page).getAttribute("aria-expanded"), "true", "still open");
    assert.ok(!hiddenOf(rowsList(page)));
    W.waiting = [];
    await page.tickHome();
    assert.ok(hiddenOf(waitingBlock(page)), "nothing waits any more: the block goes");
  });

  await test("waiting: a chat card is a row too (the pill counts it); a read that failed is said outside the closed pill (never hidden under it)", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo", { open: true, waiting: true })], fail: { "GET /api/waiting": { status: 500, body: { error: "壞了" } } } });
    const page = await home(W);
    assert.strictEqual(text(pill(page)), "有 1 件事等你決定");
    assert.ok(hiddenOf(rowsList(page)), "closed");
    const notes = all(waitingBlock(page), (n) => !hiddenOf(n) && n.className.includes("notice") && /讀不到/.test(text(n)));
    assert.ok(notes.length >= 1, "the note is visible while the list is closed: " + text(waitingBlock(page)));
  });

  await test("waiting: nothing waits but a read failed: the block stays and says what could not be read (the limit of what is known), without claiming nothing waits", async () => {
    const page = await home(world({ fail: { "GET /api/waiting": { status: 500, body: { error: "壞了" } } } }));
    assert.ok(!hiddenOf(waitingBlock(page)));
    assert.ok(/讀不到/.test(text(waitingBlock(page))));
    assert.ok(!/現在沒有要你決定的事/.test(text(page.main)));
    assert.ok(!pill(page), "no pill for zero");
  });

  await test("waiting: while the data is not in, the block says 載入中 (never nothing, never a zero); drawn only when it is in", async () => {
    const page = await home(world({ waiting: [DUE] }), "#/", { hold: ["/api/waiting"] });
    assert.ok(loadingKeys(page.main).includes("waiting"), "載入中");
    assert.ok(!hiddenOf(waitingBlock(page)), "the frame is there so the page does not jump");
    assert.ok(!pill(page), "no number yet");
    assert.ok(!/(^|[^\d])0 (件|位|個)/.test(text(page.main)));
    await page.release();
    assert.ok(!loadingKeys(page.main).includes("waiting"));
    assert.strictEqual(text(pill(page)), "有 1 件事等你決定");
  });

  // ---- the box ---------------------------------------------------------------------------------------------------------------
  await test("ask: the box is a textarea of two rows that grows with what is typed up to about eight lines; the hint under it is the old sentence; the send button is in the box", async () => {
    const page = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    const box = askBox(page);
    assert.strictEqual(box.tag, "textarea");
    assert.strictEqual(box.getAttribute("rows"), "2");
    assert.strictEqual(box.getAttribute("maxlength"), "20000");
    assert.strictEqual(box.getAttribute("aria-label"), "要對 CEO 說的話");
    box.scrollHeight = 120; box.value = "a\nb\nc"; box.dispatch("input");
    assert.strictEqual(box.style.height, "120px");
    box.scrollHeight = 5000; box.dispatch("input");
    const h = parseInt(box.style.height, 10);
    assert.ok(h >= 120 && h <= 240, "capped at about eight lines: " + box.style.height);
    box.scrollHeight = 0; box.value = ""; box.dispatch("input");
    const ask = one(page.main, "data-home", "ask");
    assert.ok(text(ask).includes("CEO 要動手前都會先問你。"));
    assert.ok(text(ask).includes("Cmd") && text(ask).includes("Enter"), "how to send is said");
    const shell = all(ask, (n) => n.className.includes("home-box"))[0];
    assert.ok(shell && shell.contains(box) && shell.contains(sendBtn(page)), "the textarea and the send button are in one rounded box");
    assert.strictEqual(text(sendBtn(page)), "送出");
  });

  await test("17c: only Cmd+Enter or Ctrl+Enter sends from the box; a plain Enter, Shift+Enter, another key and an IME's Enter send nothing", async () => {
    const page = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    const box = askBox(page);
    box.value = "你好";
    assert.strictEqual(await keySends(page, box, { key: "Enter" }), 0, "Enter");
    assert.strictEqual(await keySends(page, box, { key: "Enter", shiftKey: true }), 0, "Shift+Enter");
    assert.strictEqual(await keySends(page, box, { key: "a", metaKey: true }), 0, "Cmd+a");
    assert.strictEqual(await keySends(page, box, { key: "Enter", altKey: true }), 0, "Alt+Enter");
    assert.deepStrictEqual(posts(page), [], "nothing was sent");
    assert.strictEqual(await keySends(page, box, { key: "Enter", ctrlKey: true }), 1, "Ctrl+Enter");
    const page2 = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    const box2 = askBox(page2); box2.value = "你好";
    assert.strictEqual(await keySends(page2, box2, { key: "Enter", metaKey: true }), 1, "Cmd+Enter");
  });

  await test("ask: the press of 送出 is the old request (one message with the typed words) and the old busy, limit and red-lamp answers are as before", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")] });
    const page = await home(W);
    askBox(page).value = "整理下週的貼文";
    sendBtn(page).click();
    await tick(40);
    const sends = posts(page).filter(([, u]) => /\/messages$/.test(u));
    assert.strictEqual(sends.length, 1);
    assert.deepStrictEqual(sends[0][2], { text: "整理下週的貼文" });
    assert.strictEqual(page.location.hash, "#/chat/c1");
    const red = await home(world({ chats: [chatRow("c1", "p-ceo")], lamp: "red" }));
    askBox(red).value = "x";
    sendBtn(red).click();
    await tick(30);
    assert.deepStrictEqual(posts(red), [], "the red lamp stops it");
    assert.ok(/上限/.test(text(one(red.main, "data-home", "ask-result"))));
  });

  await test("focus: the cursor is in the box once the page is drawn, only when nothing else has the focus", async () => {
    const page = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    assert.strictEqual(page.doc.activeElement, askBox(page), "the box has the focus");
    const other = await home(world({ chats: [chatRow("c1", "p-ceo")] }), "#/", { focused: true });
    assert.notStrictEqual(other.doc.activeElement, askBox(other), "a focused element is not taken away");
    const away = await home(world({ chats: [chatRow("c1", "p-ceo")] }), "#/employees");
    assert.strictEqual(away.doc.activeElement, null, "other pages are left alone");
  });

  await test("focus: the focus is taken once; a refresh does not pull it back to the box", async () => {
    const W = world({ chats: [chatRow("c1", "p-ceo")], waiting: [DUE] });
    const page = await home(W);
    const elsewhere = new Node("button");
    elsewhere.focus();
    W.waiting = [DUE, DUE2];
    await page.tickHome();
    assert.strictEqual(page.doc.activeElement, elsewhere);
  });

  // ---- example sentences -------------------------------------------------------------------------------------------------------
  await test("17a examples: before the first chat there are three, in order; pressing one only puts the words in the box and focuses it (no request); another replaces them", async () => {
    const page = await home(world());
    const chips = byData(page.main, "data-home", "ask-example");
    assert.deepStrictEqual(chips.map(text), EXAMPLES);
    assert.ok(chips.every((c) => c.tag === "button" && c.getAttribute("type") === "button"));
    const box = askBox(page);
    box.value = "寫到一半的字";
    for (const [i, sentence] of EXAMPLES.entries()) {
      const before = page.log.length;
      chips[i].click();
      await tick(30);
      assert.deepStrictEqual(check17a(page.log, before, box, page.doc, sentence), [], sentence);
    }
    assert.deepStrictEqual(posts(page), []);
  });

  await test("17a examples: not shown once the person has talked, nor when the CEO cannot chat yet or there is no CEO", async () => {
    const talked = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    assert.strictEqual(byData(talked.main, "data-home", "ask-example").length, 0);
    const cannot = await home(world({ cards: [cardOf(CEO, { can_chat: false, code: "off", reason: "這位員工目前停用。" }), cardOf(ACCOUNTANT)] }));
    assert.strictEqual(byData(cannot.main, "data-home", "ask-example").length, 0);
    assert.ok(!askBox(cannot), "no box");
    const noCeo = await home(world({ profiles: [ACCOUNTANT] }));
    assert.strictEqual(byData(noCeo.main, "data-home", "ask-example").length, 0);
    assert.ok(one(noCeo.main, "data-home", "ask-ceo"), "the way to make a CEO");
  });

  await test("a CEO who cannot chat: the greeting, the reason and the one way to prepare it, as before", async () => {
    const page = await home(world({ cards: [cardOf(CEO, { can_chat: false, code: "unverified", reason: "聊天模式還沒有在這台 Mac 上通過驗證" }), cardOf(ACCOUNTANT)], support: { state: "unverified" } }));
    assert.strictEqual(text(one(page.main, "data-home", "greeting")), "今天想做什麼？");
    const link = one(page.main, "data-home", "ask-prepare");
    assert.ok(link && link.getAttribute("href") === "#/chat?profile=p-ceo");
    assert.ok(/還不能聊天/.test(text(one(page.main, "data-home", "ask"))));
  });

  // ---- my employees ----------------------------------------------------------------------------------------------------------
  await test("team: a row of avatars with names (a press opens the chat as before); no heading; 新增員工 is the last one, a plus with its name for the screen reader", async () => {
    const page = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    const team = one(page.main, "data-home", "team");
    assert.ok(!all(team, (n) => n.tag === "h2").length, "no heading");
    const people = all(team, (n) => n.getAttribute && n.getAttribute("data-employee-action") === "chat");
    assert.deepStrictEqual(people.map((n) => n.getAttribute("data-employee")), ["p-ceo", "p-acc"], "the CEO first");
    assert.ok(text(people[0]).includes("小執") && text(people[1]).includes("小帳"));
    const plus = all(team, (n) => n.getAttribute && n.getAttribute("data-employee-action") === "new");
    assert.strictEqual(plus.length, 1);
    assert.strictEqual(plus[0].getAttribute("aria-label"), "新增員工");
    assert.ok(text(plus[0]).trim() === "＋" || text(plus[0]).trim() === "+", "a plus: " + text(plus[0]));
    const row = all(team, (n) => n.className.includes("home-people"))[0];
    assert.strictEqual(row.children[row.children.length - 1].contains(plus[0]), true, "last in the row");
    people[0].click();
    await tick(40);
    assert.strictEqual(page.location.hash, "#/chat/c1", "the press opens the chat there is");
  });

  await test("team: an employee who cannot chat is grey with the reason under it, as before", async () => {
    const page = await home(world({ cards: [cardOf(CEO), cardOf(ACCOUNTANT, { can_chat: false, code: "off", reason: "這位員工目前停用。" })] }));
    const note = one(page.main, "data-employee-note", "p-acc");
    assert.ok(note && text(note).length > 0);
    assert.ok(all(page.main, (n) => n.getAttribute && n.getAttribute("data-employee") === "p-acc" && n.className.includes("home-avatar-off")).length === 1);
  });

  await test("team: the plus says so when the catalog could not be read (nothing is opened or sent)", async () => {
    const page = await home(world({ fail: { "GET /api/agent-builder/catalog": { status: 500, body: { error: "壞了" } } } }));
    one(page.main, "data-employee-action", "new").click();
    await tick(10);
    assert.ok(text(page.ids.get("toast")).includes("現在還不能新增員工"), text(page.ids.get("toast")));
    assert.deepStrictEqual(posts(page), [], "nothing was sent");
  });

  // ---- today -----------------------------------------------------------------------------------------------------------------
  await test("today: one grey line (how many are still to come today and the next one) with the link to the routines; nothing about the chats", async () => {
    const page = await home(world({ routines: [ALWAYS] }));
    const today = one(page.main, "data-home", "today");
    assert.ok(!hiddenOf(today));
    const line = one(today, "data-home-today", "routines");
    assert.ok(line.className.includes("muted"), "grey");
    assert.ok(/今天還有 1 件，下一件 23:59「收工整理」/.test(text(line)), text(line));
    assert.ok(all(today, (n) => n.tag === "a" && n.getAttribute("href") === "#/routines").length === 1);
    assert.ok(!one(today, "data-home-today", "chats"));
    assert.ok(!all(today, (n) => n.tag === "h2").length, "no heading");
  });

  await test("today: no routines, or none left today: the block takes no room; a read that failed is said (never a zero)", async () => {
    const none = await home(world());
    assert.ok(hiddenOf(one(none.main, "data-home", "today")), "no routines");
    const past = await home(world({ routines: [{ ...ALWAYS, times: ["00:00"] }] }));
    assert.ok(hiddenOf(one(past.main, "data-home", "today")), "none left today");
    const bad = await home(world({ fail: { "GET /api/routines": { status: 500, body: { error: "壞了" } } } }));
    const t = one(bad.main, "data-home", "today");
    assert.ok(!hiddenOf(t) && /讀不到定時工作/.test(text(t)));
    assert.ok(!/(今天還有|今天沒有)\s*0/.test(text(t)));
  });

  await test("today: while the routines are not read it says 載入中 and nothing else", async () => {
    const page = await home(world({ routines: [ALWAYS] }), "#/", { hold: ["/api/routines"] });
    assert.ok(loadingKeys(page.main).includes("today"));
    await page.release();
    assert.ok(!loadingKeys(page.main).includes("today"));
    assert.ok(/今天還有 1 件/.test(text(one(page.main, "data-home", "today"))));
  });

  // ---- the layout ---------------------------------------------------------------------------------------------------------------
  await test("layout: the page's column is marked centred while nothing waits and a CEO can be talked to, and not otherwise", async () => {
    const quiet = await home(world({ chats: [chatRow("c1", "p-ceo")] }));
    const col = one(quiet.main, "data-home", "page");
    assert.strictEqual(col.getAttribute("data-home-layout"), "center");
    const busy = await home(world({ chats: [chatRow("c1", "p-ceo")], waiting: [DUE] }));
    assert.strictEqual(one(busy.main, "data-home", "page").getAttribute("data-home-layout"), "top");
    const nobody = await home(world({ profiles: [], cards: [] }));
    assert.strictEqual(one(nobody.main, "data-home", "page").getAttribute("data-home-layout"), "top", "the three steps are not centred");
  });

  await test("a person with no employee: the three steps as before under the hidden title, nothing of the box", async () => {
    const page = await home(world({ profiles: [], cards: [] }));
    assert.ok(one(page.main, "data-home", "first-steps"));
    assert.strictEqual(all(page.main, (n) => n.getAttribute && n.getAttribute("data-home-step")).length, 3);
    assert.ok(!askBox(page) && !one(page.main, "data-home", "greeting"));
    assert.ok(all(page.main, (n) => n.tag === "h1")[0].className.includes("sr-only"));
  });

  await test("advanced mode: the old parts stay at the bottom, outside the narrow column, after the new blocks", async () => {
    const adv = await home(world({ config: { advanced_mode: true }, chats: [chatRow("c1", "p-ceo")] }));
    const order = all(adv.main, (n) => n.tag === "section" && n.getAttribute("data-home")).map((n) => n.getAttribute("data-home"));
    assert.deepStrictEqual(order, ["waiting", "ask", "team", "today", "advanced"]);
    const col = one(adv.main, "data-home", "page");
    assert.ok(!col.contains(one(adv.main, "data-home", "advanced")), "the advanced part is not squeezed into the column");
  });

  // ---- the CSS and the source ----------------------------------------------------------------------------------------------------
  await test("css: a marked P50-1 part at the end; the column is 720px; the hidden title is visually hidden; the centred layout leaves about 22vh above; the box is rounded", () => {
    const at = CSS.indexOf("/* P50-1");
    assert.ok(at > 0, "the part is marked");
    assert.ok(CSS.indexOf("/* P50-1") > CSS.indexOf("/* P48-2"), "at the end of the file, after the older parts");
    const part = CSS.slice(at);
    assert.ok(/\.home-page\s*\{[^}]*max-width:\s*720px/.test(part));
    assert.ok(/\.sr-only\s*\{[^}]*position:\s*absolute/.test(part) && /clip/.test(part));
    assert.ok(/\[data-home-layout="center"\][^{]*\{[^}]*22vh/.test(part), "22vh above");
    assert.ok(/\.home-box\s*\{[^}]*border-radius:\s*(2\d|3\d)px/.test(part), "rounded box");
    assert.ok(/\.home-box textarea\s*\{[^}]*border:\s*0/.test(part) && /\.home-box:focus-within/.test(part), "the box has the one frame and shows the focus");
    assert.ok(/\.home-pill\b/.test(part));
  });

  await test("source: the new home code uses el() only (no innerHTML), no emoji, no outside resource, and sets no storage", () => {
    const start = SOURCE.indexOf("function homeGreeting");
    assert.ok(start > 0, "the greeting function");
    const part = SOURCE.slice(start, SOURCE.indexOf("// ---- the three steps of a person with no employee ----"));
    assert.ok(!/innerHTML|insertAdjacentHTML/.test(part) && !/https?:\/\//.test(part) && !/\p{Extended_Pictographic}/u.test(part));
    assert.ok(!/localStorage|sessionStorage/.test(part), "no storage");
  });

  console.log(`\n${passed} passed`);
})();
