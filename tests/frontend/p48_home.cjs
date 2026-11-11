// P48-2 (ADR 0014 / v0.22.0 好上手 2): the home page draws its frame first and each block fills itself when its own data is in (guard 16c), and
// what waits for the person includes the permission cards of every chat, counted in the page title and handed to the app as a number (guard 16d).
//
// 16c  載入中不假裝: while data is missing, each of the three blocks says 載入中 (data-home-loading) and never "nothing waits" or a zero; the
//      progress line (data-home="loading-note") names only what is really still being read; when everything is in there is no 載入中 left; only GETs.
// 16d  等你決定與標題只計數、不送: a chat with a card that waits is a row of its own that leads to that chat; document.title is `VBear` or `(N) VBear`
//      (a number only: no name, no words of a chat); computing it sends only GETs; what goes to the app (if it has the bridge) has the keys count and
//      notify and nothing else.
// Also: the logo is retried once and then replaced by the letters VB (no broken picture), and the logo's file is not touched.
// Runs the whole of web/app.js (with its start-up code) in a vm context against a small synthetic DOM, a fetch stub whose answers can be held back,
// and a clock the test moves by hand. NOT a browser test.
//
// Run: node tests/frontend/p48_home.cjs   (exit code 0 = pass)
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
  focus() { Node.focused = this; }
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
    body, documentElement: new Node("html"), activeElement: null, hidden: false, title: "VBear",
  };
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

// ---- guard 16c / 16d: the checks, and a small sample for each that must trip them ----------------------------------------------
// 16c: while something is missing: each of the three blocks says 載入中 and none says "nothing waits" or a number; when everything is in: no 載入中.
function check16c(main, phase, blocks = ["waiting", "team", "today"]) {
  const bad = [];
  const t = text(main);
  if (phase === "loading") {
    for (const b of blocks) if (!loadingKeys(main).includes(b)) bad.push(`block ${b} has no 載入中`);
    if (/沒有要你決定的事/.test(t)) bad.push("says nothing waits before the data is in");
    if (/(^|[^\d])0 (件|位|個)/.test(t)) bad.push("shows a zero before the data is in");
  } else if (phase === "done") {
    if (loadingNodes(main).length) bad.push("a 載入中 is left: " + loadingKeys(main).join());
    if (/載入中/.test(t)) bad.push("the word 載入中 is left");
    if (one(main, "data-home", "loading-note")) bad.push("the progress line is left");
  }
  return bad;
}
// 16c, the progress line: it names exactly the blocks that are still being read.
const BLOCK_WORDS = { waiting: "等你決定的事", team: "你的員工", today: "今天的定時工作" };
function check16cNote(main, pending) {
  const bad = [];
  const note = one(main, "data-home", "loading-note");
  if (!pending.length) { if (note) bad.push("a progress line with nothing pending"); return bad; }
  if (!note) return ["no progress line"];
  const t = text(note);
  for (const [k, w] of Object.entries(BLOCK_WORDS)) {
    if (pending.includes(k) && !t.includes(w)) bad.push(`the line does not name ${k}`);
    if (!pending.includes(k) && t.includes(w)) bad.push(`the line names ${k}, which is in`);
  }
  return bad;
}
// 16d: the title is a number only; the log has no write; what goes to the app has exactly the keys count and notify.
const TITLE_RE = /^(\(\d{1,3}\) )?VBear$/;
function check16d(title, log, sent) {
  const bad = [];
  if (!TITLE_RE.test(title)) bad.push("title is not a number only: " + title);
  for (const [m, u] of log) if (m !== "GET") bad.push(`${m} ${u}: counting writes`);
  for (const s of sent || []) {
    if (!s || typeof s !== "object" || Object.keys(s).sort().join() !== "count,notify") bad.push("a message with keys " + (s ? Object.keys(s).join() : s));
    else if (!Number.isInteger(s.count) || s.count < 0 || s.count > 999 || typeof s.notify !== "boolean") bad.push("a message with a wrong type " + JSON.stringify(s));
  }
  return bad;
}

// 16d pace: the times (ms) a page read /api/chats; each must be 30 seconds after the one before, except the ones the person asked for (`forced`).
function check16dPace(times, forced) {
  const bad = [];
  for (let i = 1; i < times.length; i++) if (times[i] - times[i - 1] < 30000 && !forced.includes(times[i])) bad.push(`a read of the chats ${times[i] - times[i - 1]} ms after the one before`);
  return bad;
}

(async () => {
  // ---- the checks themselves trip -----------------------------------------------------------------------------------------------
  await test("16c: the checkers trip on a missing 載入中, a premature 'nothing waits', a premature zero, a left-over 載入中, a wrong progress line", () => {
    const mk = (kids) => { const n = new Node("main"); for (const k of kids) { if (typeof k === "string") { const t = new Node("p"); t.textContent = k; n.append(t); } else n.append(k); } return n; };
    const loading = (k) => { const p = new Node("p"); p.setAttribute("data-home-loading", k); p.textContent = "載入中…"; return p; };
    const note = (s) => { const p = new Node("p"); p.setAttribute("data-home", "loading-note"); p.textContent = s; return p; };
    assert.deepStrictEqual(check16c(mk([loading("waiting"), loading("team"), loading("today")]), "loading"), []);
    assert.ok(check16c(mk([loading("waiting"), loading("team")]), "loading").length >= 1, "a block without 載入中");
    assert.ok(check16c(mk([loading("waiting"), loading("team"), loading("today"), "現在沒有要你決定的事。"]), "loading").length >= 1, "premature nothing waits");
    assert.ok(check16c(mk([loading("waiting"), loading("team"), loading("today"), "0 件"]), "loading").length >= 1, "premature zero");
    assert.deepStrictEqual(check16c(mk(["好了"]), "done"), []);
    assert.ok(check16c(mk([loading("team")]), "done").length >= 1, "left-over loading attribute");
    assert.ok(check16c(mk(["載入中"]), "done").length >= 1, "left-over word");
    assert.ok(check16c(mk([note("還在讀：等你決定的事。")]), "done").length >= 1, "left-over progress line");
    assert.deepStrictEqual(check16cNote(mk([note("還在讀：等你決定的事。")]), ["waiting"]), []);
    assert.ok(check16cNote(mk([note("還在讀：等你決定的事、你的員工。")]), ["waiting"]).length >= 1, "names one that is in");
    assert.ok(check16cNote(mk([note("還在讀：等你決定的事。")]), ["waiting", "today"]).length >= 1, "misses one that is pending");
    assert.ok(check16cNote(mk([]), ["waiting"]).length >= 1, "no line while pending");
    assert.ok(check16cNote(mk([note("還在讀：等你決定的事。")]), []).length >= 1, "a line with nothing pending");
  });

  await test("16d: the checkers trip on a title with a name or words, a write while counting, a message with another key, a wrong type or a number out of range", () => {
    assert.deepStrictEqual(check16d("VBear", [["GET", "/api/chats", null]], [{ count: 0, notify: false }]), []);
    assert.deepStrictEqual(check16d("(3) VBear", [], [{ count: 3, notify: false }]), []);
    assert.ok(check16d("(小執) VBear", [], []).length >= 1, "a name in the title");
    assert.ok(check16d("(2) 小執想動手 - VBear", [], []).length >= 1, "words in the title");
    assert.ok(check16d("(1234) VBear", [], []).length >= 1, "four digits");
    assert.ok(check16d("VBear", [["POST", "/api/config", {}]], []).length >= 1, "a write");
    assert.ok(check16d("VBear", [], [{ count: 1, notify: false, text: "x" }]).length >= 1, "an extra key");
    assert.ok(check16d("VBear", [], [{ count: 1 }]).length >= 1, "a missing key");
    assert.ok(check16d("VBear", [], [{ count: "1", notify: false }]).length >= 1, "a string count");
    assert.ok(check16d("VBear", [], [{ count: 1000, notify: false }]).length >= 1, "over 999");
    assert.ok(check16d("VBear", [], [{ count: -1, notify: false }]).length >= 1, "negative");
  });

  const GETS = ["/api/overview", "/api/skills", "/api/roles", "/api/live", "/api/flows", "/api/tasks", "/api/agent-profiles", "/api/agent-builder/catalog", "/api/chats",
    "/api/routines", "/api/waiting", "/api/meetings/ledger", "/api/meetings", "/api/staffing", "/api/dispatch", "/api/groups", "/api/setup/tools"];
  const waitingBlock = (page) => one(page.main, "data-home", "waiting");
  const cardWaiting = (id, who, over = {}) => chatRow(id, who, { open: true, waiting: true, ...over });
  const DUE = { kind: "routine_due", name: "晨間整理", run_id: "run-1", slot: "2026-11-10T08:00" };

  // ---- 16c: the frame first ---------------------------------------------------------------------------------------------------
  await test("16c: only /api/config is in: the title, the lede and the three blocks are there and say 載入中; nothing says 'nothing waits' or a zero; only GETs", async () => {
    const page = await home(world(), "#/", { hold: GETS });
    assert.strictEqual(text(all(page.main, (n) => n.tag === "h1")[0]), "首頁");
    assert.ok(all(page.main, (n) => n.className === "lede").length === 1, "the lede is there");
    assert.deepStrictEqual(check16c(page.main, "loading"), []);
    assert.deepStrictEqual(loadingKeys(page.main).sort(), ["team", "today", "waiting"]);
    assert.strictEqual(posts(page).length, 0, "only GETs");
    assert.strictEqual(rowsOf(page.main).length, 0);
    const requested = page.log.map(([, u]) => u.split("?")[0]);
    assert.ok(requested.includes("/api/config") && requested.includes("/api/chats"), "the data is asked for at once, not after the frame");
  });

  await test("16c: everything comes in: no 載入中 and no progress line is left; the waiting block says nobody waits, in words; only GETs", async () => {
    const page = await home(world(), "#/", { hold: GETS });
    await page.release();
    assert.deepStrictEqual(check16c(page.main, "done"), []);
    assert.ok(text(waitingBlock(page)).includes("現在沒有要你決定的事。"));
    assert.ok(one(page.main, "data-employee", "p-ceo"), "the team is there");
    assert.ok(one(page.main, "data-home", "ask"), "the ask box is there");
    assert.strictEqual(posts(page).length, 0);
  });

  await test("16c: the progress line shows after 3 seconds, names only what is still being read, and a block that came in leaves it", async () => {
    const page = await home(world(), "#/", { hold: GETS });
    await page.advance(2999);
    assert.strictEqual(one(page.main, "data-home", "loading-note"), null, "not before 3 seconds");
    await page.advance(1);
    assert.deepStrictEqual(check16cNote(page.main, ["waiting", "team", "today"]), []);
    assert.ok(text(one(page.main, "data-home", "loading-note")).includes("第一次打開 VBear 要先叫醒背景程式"));
    await page.release("/api/agent-profiles", "/api/chats", "/api/routines", "/api/agent-builder/catalog");
    assert.deepStrictEqual(check16cNote(page.main, ["waiting"]), [], "team and today are in: only the waiting block is named");
    assert.ok(!loadingKeys(page.main).includes("team") && !loadingKeys(page.main).includes("today"));
    assert.deepStrictEqual(check16c(page.main, "loading", ["waiting"]), []);
    await page.release();
    assert.deepStrictEqual(check16cNote(page.main, []), []);
    assert.deepStrictEqual(check16c(page.main, "done"), []);
  });

  await test("16c: a block fills itself when its own data is in: the team shows while the waiting block is still being read, and that one still says 載入中", async () => {
    const page = await home(world(), "#/", { hold: GETS });
    await page.release("/api/agent-profiles", "/api/chats", "/api/agent-builder/catalog");
    assert.ok(one(page.main, "data-employee", "p-ceo") && one(page.main, "data-employee", "p-acc"), "the avatars are there");
    assert.ok(loadingKeys(page.main).includes("waiting"));
    assert.ok(!/沒有要你決定的事/.test(text(page.main)), "not claimed while the waiting data is missing");
    assert.strictEqual(rowsOf(page.main).length, 0);
  });

  await test("16c: a request that is not back after 60 seconds: that block says it could not read (not 載入中, not 'nothing waits'); when it comes later the block is redrawn", async () => {
    const page = await home(world({ chats: [cardWaiting("c1", "p-ceo")] }), "#/", { hold: ["/api/waiting"] });
    await page.advance(59999);
    assert.ok(loadingKeys(page.main).includes("waiting"), "still waiting at 59.999 seconds");
    await page.advance(1);
    const t = text(waitingBlock(page));
    assert.ok(!loadingKeys(page.main).includes("waiting"), "no longer 載入中");
    assert.ok(!t.includes("現在沒有要你決定的事。"), "not claimed: " + t);
    assert.ok(/讀不到/.test(t), "it says it could not read: " + t);
    await page.release();
    assert.ok(rowsOf(page.main).length === 1 && text(waitingBlock(page)).includes("小執"), "the late answer is drawn");
    assert.deepStrictEqual(check16c(page.main, "done"), []);
  });

  await test("16c: a timer that fires too early does nothing (the 3-second line and the 60-second give-up look at the clock)", async () => {
    const page = await home(world(), "#/", { hold: GETS });
    await page.fireNow();
    assert.strictEqual(one(page.main, "data-home", "loading-note"), null);
    assert.deepStrictEqual(check16c(page.main, "loading"), []);
  });

  await test("16c: a person who has not finished the start-up: only the title and one line (what is waited for) are drawn until the server has settled it; none of the blocks, no requests for them; then the start-up", async () => {
    const W = world({ config: { setup_done: false }, posts: { "POST /api/setup/settle": { body: { setup_done: false } } } });
    const page = await home(W, "#/", { hold: ["/api/setup/settle"] });
    assert.strictEqual(text(all(page.main, (n) => n.tag === "h1")[0]), "首頁");
    assert.deepStrictEqual(loadingKeys(page.main), ["setup"]);
    assert.strictEqual(one(page.main, "data-home", "waiting"), null, "no block yet");
    assert.ok(!page.log.some(([, u]) => u === "/api/chats"), "the data of the blocks is not asked for before the person is known to stay");
    await page.release();
    assert.strictEqual(page.location.hash, "#/setup");
    assert.ok(!page.log.some(([, u]) => u === "/api/chats"));
  });

  await test("16c: leaving the page: a timer that fires after the person went elsewhere draws nothing into the new page", async () => {
    const page = await home(world(), "#/", { hold: GETS });
    await page.go("#/work");
    await page.advance(70000);
    assert.strictEqual(one(page.main, "data-home", "loading-note"), null);
    assert.ok(text(page.main).includes("對話紀錄"), "the work page is there");
  });

  await test("16c: no employee yet: the three steps' frame is there at once, step 1 says it is looking at the tools until they are read, then the words", async () => {
    const page = await home(world({ profiles: [], cards: [] }), "#/", { hold: ["/api/setup/tools"] });
    const step = one(page.main, "data-home-step", "1");
    assert.ok(step, "step 1 is there");
    assert.deepStrictEqual(loadingKeys(page.main), ["first-steps"]);
    assert.ok(text(step).includes("正在看你的 AI 工具…"));
    assert.ok(!/AI 工具已就緒|還沒有就緒|讀不到 AI 工具/.test(text(step)), "no conclusion before the answer");
    await page.release();
    assert.deepStrictEqual(loadingKeys(page.main), []);
    assert.ok(/已經有可以聊天的 AI 工具就緒了/.test(text(one(page.main, "data-home-step", "1"))));
    assert.ok(one(page.main, "data-home", "first-steps"));
  });

  await test("16c: the employees' data could not be read: the block says so (the frame stays, nothing is shown as an empty team) and no 載入中 is left", async () => {
    const page = await home(world({ fail: { "GET /api/agent-profiles": { status: 500, body: { error: "壞了" } } } }));
    assert.ok(/讀不到員工的資料/.test(text(one(page.main, "data-home", "team"))));
    assert.ok(!one(page.main, "data-home", "first-steps"));
    assert.deepStrictEqual(check16c(page.main, "done"), []);
  });

  // ---- 16d: what waits, in the title and for the app ------------------------------------------------------------------------------
  await test("16d: a chat with a card that waits is a row of its own that leads to that chat; the title is (1) VBear; the app is handed the number only; only GETs", async () => {
    const page = await home(world({ chats: [cardWaiting("c1", "p-ceo")] }), "#/", { bridge: true });
    const rows = rowsOf(page.main);
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(rows[0].getAttribute("data-home-row"), "chat_card");
    const t = text(rows[0]);
    assert.ok(t.includes("小執") && t.includes("允許這一次") && t.includes("拒絕"), t);
    const go = one(rows[0], "data-home-action", "go");
    assert.strictEqual(go.getAttribute("href"), "#/chat/c1");
    assert.strictEqual(page.doc.title, "(1) VBear");
    assert.deepStrictEqual(check16d(page.doc.title, page.log, page.sent), []);
    assert.strictEqual(JSON.stringify(page.sent), JSON.stringify([{ count: 1, notify: false }]));
  });

  await test("16d: a chat a routine opened counts too; a chat with no card waiting does not; the row names the employee from the cards (text only)", async () => {
    const W = world({ chats: [cardWaiting("c-routine", "p-acc", { routine_title: "晨間整理" }), chatRow("c-quiet", "p-ceo", { open: true, waiting: false })] });
    const page = await home(W);
    const rows = rowsOf(page.main);
    assert.strictEqual(rows.length, 1);
    assert.ok(text(rows[0]).includes("小帳"));
    assert.strictEqual(one(rows[0], "data-home-action", "go").getAttribute("href"), "#/chat/c-routine");
    assert.strictEqual(page.doc.title, "(1) VBear");
  });

  await test("16d: the number counts every row (a due routine, a chat card, the limit line); it holds no name and no words of a chat", async () => {
    const W = world({ waiting: [DUE], chats: [cardWaiting("c1", "p-ceo", { last_text: "我想刪掉整個資料夾" })], lamp: "red" });
    const page = await home(W, "#/", { bridge: true });
    assert.strictEqual(rowsOf(page.main).length, 3);
    assert.strictEqual(page.doc.title, "(3) VBear");
    assert.deepStrictEqual(check16d(page.doc.title, page.log, page.sent), []);
    assert.ok(!page.doc.title.includes("小執") && !page.doc.title.includes("資料夾"));
    assert.strictEqual(JSON.stringify(page.sent), JSON.stringify([{ count: 3, notify: false }]));
  });

  await test("16d: nothing waits: the title is VBear and the app is handed 0", async () => {
    const page = await home(world(), "#/", { bridge: true });
    assert.strictEqual(page.doc.title, "VBear");
    assert.strictEqual(JSON.stringify(page.sent), JSON.stringify([{ count: 0, notify: false }]));
    assert.deepStrictEqual(check16d(page.doc.title, page.log, page.sent), []);
  });

  await test("16d: a read that failed: no number (the title is VBear, the app gets 0) even when a row is known, and the page says what it could not read", async () => {
    const W = world({ chats: [cardWaiting("c1", "p-ceo")], fail: { "GET /api/waiting": { status: 500, body: { error: "壞了" } } } });
    const page = await home(W, "#/", { bridge: true });
    assert.strictEqual(page.doc.title, "VBear");
    assert.strictEqual(JSON.stringify(page.sent), JSON.stringify([{ count: 0, notify: false }]));
    assert.ok(text(waitingBlock(page)).includes("讀不到定時工作和接著做的提醒"));
    assert.strictEqual(rowsOf(page.main).length, 1, "the row that is known is still listed");
  });

  await test("16d: the chats could not be read: it is said, and the title has no number", async () => {
    const page = await home(world({ chats: [cardWaiting("c1", "p-ceo")], fail: { "GET /api/chats": { status: 500, body: { error: "壞了" } } } }), "#/", { bridge: true });
    assert.ok(text(waitingBlock(page)).includes("讀不到聊天裡有沒有在等你的卡片"));
    assert.ok(!text(waitingBlock(page)).includes("現在沒有要你決定的事。"));
    assert.strictEqual(page.doc.title, "VBear");
  });

  await test("16d: the home page every 5 seconds: the other reads go every tick; a card that began to wait shows up (title and app) at the next read of the chats, and goes away when it is answered; only GETs", async () => {
    const W = world();
    const page = await home(W, "#/", { bridge: true });
    assert.strictEqual(page.doc.title, "VBear");
    W.chats = [cardWaiting("c1", "p-ceo")];
    await page.advance(5000); await page.tickHome();
    assert.strictEqual(rowsOf(page.main).length, 0, "the chats are not read again within 30 seconds");
    await page.advance(25000); await page.tickHome();
    assert.strictEqual(rowsOf(page.main).length, 1);
    assert.strictEqual(page.doc.title, "(1) VBear");
    W.chats = [chatRow("c1", "p-ceo")];
    await page.advance(30000); await page.tickHome();
    assert.strictEqual(rowsOf(page.main).length, 0);
    assert.strictEqual(page.doc.title, "VBear");
    assert.strictEqual(JSON.stringify(page.sent), JSON.stringify([{ count: 0, notify: false }, { count: 1, notify: false }, { count: 0, notify: false }]));
    assert.deepStrictEqual(check16d(page.doc.title, page.log, page.sent), []);
  });

  await test("16d pace: the home page reads /api/chats at most every 30 seconds (the server runs the AI tools' --version at each read) while its other reads go every 5 seconds; the person's own press and a new visit read at once", async () => {
    const W = world({ waiting: [DUE] });
    const page = await home(W);
    const at = (re) => page.log.filter(([, u]) => re.test(u.split("?")[0])).map((e) => e[3]);
    for (let i = 0; i < 14; i++) { await page.advance(5000); await page.tickHome(); }        // 70 seconds of ticks
    const chats = at(/^\/api\/chats$/);
    assert.deepStrictEqual(check16dPace(chats, []), [], "chats read at " + chats.join());
    assert.strictEqual(chats.length, 3, "at the page's first read, after 30 and after 60 seconds: " + chats.join());
    assert.strictEqual(at(/^\/api\/waiting$/).length, 15, "every other read still goes at every tick");
    assert.strictEqual(at(/^\/api\/meetings$/).length, 15);
    // the press of a button of a row: the chats are read again at once
    const before = at(/^\/api\/chats$/).length;
    await page.advance(5000);
    one(one(page.main, "data-home-row", "routine_due"), "data-home-action", "wait-start").click();
    await tick(40);
    assert.strictEqual(at(/^\/api\/chats$/).length, before + 1, "the press reads the chats at once");
    assert.deepStrictEqual(check16dPace(at(/^\/api\/chats$/), [at(/^\/api\/chats$/).slice(-1)[0]]), []);
    // a new visit to the home page reads at once
    await page.go("#/work"); await page.go("#/");
    assert.strictEqual(at(/^\/api\/chats$/).length, before + 2);
  });

  await test("16d pace: the checker trips on a read of the chats less than 30 seconds after the last one (unless it was asked for by the person), and on none being allowed to repeat", () => {
    assert.deepStrictEqual(check16dPace([0, 30000, 60000], []), []);
    assert.ok(check16dPace([0, 5000, 10000], []).length >= 1, "a read at every tick");
    assert.ok(check16dPace([0, 29999], []).length >= 1, "a hair too soon");
    assert.deepStrictEqual(check16dPace([0, 5000], [5000]), [], "a forced one is allowed");
  });

  await test("16d: the same number is not handed to the app twice in a row", async () => {
    const page = await home(world(), "#/", { bridge: true });
    await page.tickHome(); await page.tickHome();
    assert.strictEqual(page.sent.length, 1);
  });

  await test("16d: another page: the line over the page counts the chat cards too, the title follows, the home page's own list is not doubled; only GETs", async () => {
    const W = world({ chats: [cardWaiting("c1", "p-ceo")] });
    const page = await home(W, "#/employees", { bridge: true });
    const bar = page.bar;
    assert.ok(!bar.hidden, "the line is shown");
    assert.ok(text(bar).includes("小執") && text(bar).includes("允許這一次"), text(bar));
    assert.strictEqual(one(bar, "data-waiting", "chat-link").getAttribute("href"), "#/chat/c1");
    assert.strictEqual(page.doc.title, "(1) VBear");
    assert.deepStrictEqual(check16d(page.doc.title, page.log, page.sent), []);
    W.chats = [];
    await page.tickBar();
    assert.ok(bar.hidden, "gone when answered");
    assert.strictEqual(page.doc.title, "VBear");
    await page.go("#/");
    assert.ok(page.bar.hidden, "the home page lists them itself");
  });

  await test("16d: moving between pages does not ask the server for everything at each click: the cards of the chats read in the last 30 seconds are drawn again (the line's own rows are read each time); the 30-second timer always asks", async () => {
    const page = await home(world({ chats: [cardWaiting("c1", "p-ceo")] }), "#/work");
    const reads = () => page.log.filter(([, u]) => u === "/api/chats").length;
    const waits = () => page.log.filter(([, u]) => u === "/api/waiting").length;
    assert.strictEqual(reads(), 1);
    const w0 = waits();
    await page.go("#/work"); await page.go("#/work");
    assert.strictEqual(reads(), 1, "the clicks reuse it");
    assert.strictEqual(waits(), w0 + 2, "but the line's own rows are read at each click");
    assert.ok(text(page.bar).includes("小執"), "and the line is still there");
    await page.advance(29000);
    await page.go("#/work");
    assert.strictEqual(reads(), 1, "still within 30 seconds");
    await page.advance(1000);
    await page.go("#/work");
    assert.strictEqual(reads(), 2, "after 30 seconds a click asks again");
    await page.tickBar();
    assert.strictEqual(reads(), 3, "the timer always asks");
  });

  await test("16d: reading what waits from another page does not write into the page's shared data (other pages compare it before and after)", async () => {
    const W = world();
    const page = await home(W, "#/employees");
    const snap = () => evalIn(page, "JSON.stringify([D.live, D.flows, D.meetings, D.staffing, D.dispatch, D.groups])");
    const before = snap();
    W.live = { runtime: { available: true, problems: [] }, sessions: [{ terminal_id: "t", status: "x", skills_used: [] }], attention: [], projects: [], usage: { sessions: [] } };
    W.meetings = [{ id: "m1", topic: "新的議題", state: "x" }];
    await page.tickBar();
    assert.strictEqual(snap(), before);
  });

  await test("16d: onWaitingCount: a listener is called each time the number is worked out with { count, complete } and nothing else", async () => {
    const W = world();
    const page = await home(W);
    evalIn(page, "globalThis.__seen = []; onWaitingCount((m) => __seen.push(m));");
    W.chats = [cardWaiting("c1", "p-ceo")];
    await page.advance(30000); await page.tickHome();
    const seen = JSON.parse(evalIn(page, "JSON.stringify(__seen)"));
    assert.deepStrictEqual(seen, [{ count: 1, complete: true }]);
  });

  await test("16d: homeWaitingRows with the chats: a row per waiting chat; unread chats are a note and not complete; more than listed is a note; the old three-argument call is as before", () => {
    const page = boot("#/", world(), { hold: GETS });
    page.ctx.__g = evalIn(page, "boardGroups({ runtime: { available: true } }, { flows: [] }, { meetings: [] }, { staffing: [] }, { dispatch: [] }, { groups: [] })");
    const run = (chats) => JSON.parse(evalIn(page, `JSON.stringify(homeWaitingRows(__g, [], "green", ${chats}))`));
    assert.deepStrictEqual(run("undefined"), { rows: [], notes: [], complete: true });
    const unread = run("null");
    assert.strictEqual(unread.complete, false);
    assert.deepStrictEqual(unread.notes, ["讀不到聊天裡有沒有在等你的卡片"]);
    const some = run(JSON.stringify({ chats: [{ id: "c9", profile_id: "x", waiting: true }, { id: "c8", profile_id: "x", waiting: false }], cards: [] }));
    assert.strictEqual(some.rows.length, 1);
    assert.strictEqual(some.rows[0].kind, "chat_card");
    assert.ok(some.rows[0].text.startsWith("有員工想動手"), some.rows[0].text);
    assert.strictEqual(some.rows[0].href, "#/chat/c9");
    const more = run(JSON.stringify({ chats: [], cards: [], more: 5 }));
    assert.strictEqual(more.notes.length, 1);
    assert.ok(/最近的/.test(more.notes[0]));
    assert.strictEqual(more.complete, true, "only the oldest chats are out of sight: the number stays");
  });

  // ---- the logo ---------------------------------------------------------------------------------------------------------------
  await test("logo: the first failure loads it once more (?r=1); the second shows the letters VB and no picture; a picture that loads is left alone", async () => {
    const page = await home(world());
    assert.strictEqual(page.logo.getAttribute("src"), "/logo.svg");
    page.logo.dispatch("error");
    assert.strictEqual(page.logo.getAttribute("src"), "/logo.svg?r=1");
    assert.ok(page.logo.parentNode, "still the picture");
    page.logo.dispatch("error");
    assert.strictEqual(page.logo.parentNode, null, "the picture is gone");
    assert.strictEqual(text(page.mark), "VB");
    assert.strictEqual(page.mark.getAttribute("data-brand"), "text");
    const ok = await home(world());
    assert.strictEqual(ok.logo.getAttribute("src"), "/logo.svg");
    assert.strictEqual(text(ok.mark), "");
  });

  await test("logo: a picture that had already failed before the script ran is loaded once more at once", async () => {
    const page = await home(world(), "#/", { logoFailedBeforeScript: true });
    assert.strictEqual(page.logo.getAttribute("src"), "/logo.svg?r=1");
  });

  // ---- source rules -----------------------------------------------------------------------------------------------------------
  await test("source: the waiting-model part uses el() only (no innerHTML), no emoji, no outside resource, no storage, no notification; the bridge message has only count and notify", () => {
    const start = SOURCE.indexOf("// ---------- waiting model (v0.22, P48-2)");
    const end = SOURCE.indexOf("// ---------- end of waiting model");
    assert.ok(start > 0 && end > start, "the part is marked");
    const src = SOURCE.slice(start, end);
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(src));
    assert.ok(!/\p{Extended_Pictographic}/u.test(src));
    assert.ok(!/https?:\/\//.test(src));
    assert.ok(!/localStorage|sessionStorage|Notification|serviceWorker|PushManager/.test(src), "storing and notifying are P48-4's, not here");
    assert.ok(!/US\$/.test(src));
    const sends = src.match(/vbearWaiting\.postMessage\(([^)]*)\)/g) || [];
    assert.ok(sends.length === 1 && /\{ count: [^,]+, notify: [^}]+ \}/.test(sends[0]) && !/ask/.test(sends[0]), "one message, the keys count and notify: " + sends.join());
    for (const f of ["waitingModel", "waitingFold", "onWaitingCount", "waitingPublish", "waitingTitleText"]) assert.ok(new RegExp(`function ${f}\\b`).test(src), f);
    assert.ok(/let waitingListeners = \[\]/.test(src));
    assert.ok(/document\.title = /.test(src));
  });

  await test("source: the home page and its blocks keep the plan's data-* names, and the CSS has its own marked part", () => {
    for (const k of ["data-home-loading", "loading-note", "chat_card", "first-steps"]) assert.ok(SOURCE.includes(k), k);
    for (const k of ["waiting", "team", "today", "ask"]) assert.ok(SOURCE.includes(`"${k}"`), k);
    assert.ok(/\/\* P48-2 /.test(CSS), "style.css has the P48-2 part");
  });

  await test("source: the server's queue length is not changed (it was measured not to be the cause) and the address is still 127.0.0.1 only", () => {
    const server = fs.readFileSync(path.join(ROOT, "vbear", "server.py"), "utf8");
    assert.ok(!/request_queue_size/.test(server), "no change without a measured cause");
    assert.ok(/ThreadingHTTPServer\(\("127\.0\.0\.1", port\)/.test(server));
  });
  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
})();
