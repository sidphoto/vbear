// P48-4 (ADR 0014 / v0.22.0 好上手 2): the Mac notification (off unless the person turns it on), the number for the app's Dock and window title, and the
// message bridge `vbearWaiting` (guard 16e).
//
// 16e  通知預設關、只在本機、不含對話全文:
//      - without the key `vbear-notify` the switch is off; loading pages (the home page, the settings page, the other pages) asks the browser 0 times for
//        the allowance and sends the app 0 `ask` messages; only the click on the switch asks (once per click);
//      - a notification made by the page has the title `VBear` and a body of the form `有 N 件事等你決定` (N a number of up to three digits) and nothing else;
//      - only when the number grew (the page counted a whole read), the switch is on, and the page is not in front; the same number, fewer, the first
//        number, an incomplete read and the switch off make none;
//      - what the page hands the app has the keys count and notify (or ask) and nothing else; when the allowance is refused the switch goes back off and
//        says so (no `vbear-notify` is written);
//      - the page has no push, no service worker, no innerHTML.
// The Swift side is macos/test_waiting_bridge.sh; the sources are read by tests/test_p48_notify_static.py.
// Runs the whole of web/app.js (with its start-up code) in a vm context against a small synthetic DOM, a fetch stub, a fake Notification and a clock the
// test moves by hand. NOT a browser test.
//
// Run: node tests/frontend/p48_notify.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this._attrs = {}; this._classes = new Set(); this._l = {}; this.value = ""; this.nodeType = tag === "#text" ? 3 : 1; this.disabled = false; this.open = false; this.parentNode = null; this.hidden = false; this.complete = false; this.naturalWidth = 0; this.checked = false; }
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
  const page = { focus: true };
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
    body, documentElement: new Node("html"), activeElement: null, hidden: false, title: "VBear", hasFocus: () => page.focus,
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
  const store = new Map(Object.entries(extra.store || {}));
  const writes = [];                    // every write to the browser's storage except the page's own `sid:` settings (theme): [key, value|null]
  const shown = [];                     // the notifications the page made: { title, body, options, onclick }
  const asked = { n: 0 };               // how many times the page asked the browser for the allowance
  class FakeNotification {
    constructor(title, options = {}) { this.title = title; this.options = options; this.onclick = null; this.closed = false; shown.push(this); }
    close() { this.closed = true; }
    static requestPermission(cb) {
      asked.n += 1;
      const answer = extra.permissionAnswer || "granted";
      FakeNotification.permission = answer;
      if (typeof cb === "function") cb(answer);
      return Promise.resolve(answer);
    }
  }
  FakeNotification.permission = extra.permission || "default";
  const sent = [];                      // what the page handed to the app
  const win = { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
  if (extra.bridge) win.webkit = { messageHandlers: { vbearWaiting: { postMessage: (m) => sent.push(JSON.parse(JSON.stringify(m))) } } };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams, Date: FakeDate,
    window: win,
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); if (!k.startsWith("sid:")) writes.push([k, String(v)]); }, removeItem: (k) => { store.delete(k); if (!k.startsWith("sid:")) writes.push([k, null]); } },
    ...(extra.noNotification ? {} : { Notification: FakeNotification }),
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
  Object.assign(page, { ctx, main, log, store, writes, shown, asked, Notification: FakeNotification, focusCalls: 0 });
  win.focus = () => { page.focusCalls += 1; };
  return Object.assign(page, { ctx, main, log, location, ids, go, body, doc, bar, logo, mark, sent, advance, fireNow, hold, release, tickHome, tickBar, intervals });
}

const evalIn = (page, code) => vm.runInContext(code, page.ctx);
const posts = (page) => page.log.filter(([m]) => m !== "GET");

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); } catch (e) { console.log("FAIL -", name); console.log((e && e.stack) || e); process.exitCode = 1; }
}

// ---- the checks, and a small sample for each that must trip them -----------------------------------------------------------------
const NOTE_BODY = /^有 \d{1,3} 件事等你決定$/;
// 16e: every notification the page made: title VBear, the fixed body, nothing else in the options that could carry words.
function check16eShown(shown) {
  const bad = [];
  for (const n of shown) {
    if (n.title !== "VBear") bad.push("title " + JSON.stringify(n.title));
    const o = n.options || {};
    if (typeof o.body !== "string" || !NOTE_BODY.test(o.body)) bad.push("body " + JSON.stringify(o.body));
    for (const k of Object.keys(o)) if (!["body", "tag"].includes(k)) bad.push("option " + k);
    if (o.tag !== undefined && o.tag !== "vbear-waiting") bad.push("tag " + JSON.stringify(o.tag));
  }
  return bad;
}
// 16e: what goes to the app: { count, notify } or { ask: true }, nothing else.
function check16eSent(sent) {
  const bad = [];
  for (const s of sent) {
    const keys = s && typeof s === "object" ? Object.keys(s).sort().join() : "";
    if (keys === "ask") { if (s.ask !== true) bad.push("ask that is not true"); }
    else if (keys === "count,notify") { if (!Number.isInteger(s.count) || s.count < 0 || s.count > 999 || typeof s.notify !== "boolean") bad.push("wrong type " + JSON.stringify(s)); }
    else bad.push("keys " + keys);
  }
  return bad;
}
// 16e: the storage: only the key vbear-notify, and only the value "on" (or its removal).
function check16eWrites(writes) {
  const bad = [];
  for (const [k, v] of writes) if (k !== "vbear-notify" || (v !== "on" && v !== null)) bad.push(`write ${k}=${v}`);
  return bad;
}

const DUE = (i) => ({ kind: "routine_due", name: "晨間整理", run_id: "run-" + i, slot: "2026-11-10T08:00" });
const dues = (n) => Array.from({ length: n }, (_, i) => DUE(i + 1));
const switchOf = (page) => one(page.main, "data-setting", "notify");
const resultOf = (page) => one(page.main, "data-settings", "notify-result");
const isOn = (input) => !!input.checked;
async function settingsPage(extra = {}, W = world()) { const page = boot("#/settings", W, extra); await tick(80); return page; }
async function press(page, want) { const input = switchOf(page); input.checked = want; input.dispatch("change"); await tick(30); }

(async () => {
  await test("16e: the checkers trip on a name in the title, a body with words, an extra option, an extra key, a wrong type and a write of another key", () => {
    assert.deepStrictEqual(check16eShown([{ title: "VBear", options: { body: "有 3 件事等你決定", tag: "vbear-waiting" } }]), []);
    assert.ok(check16eShown([{ title: "小執", options: { body: "有 3 件事等你決定" } }]).length >= 1, "a name as the title");
    assert.ok(check16eShown([{ title: "VBear", options: { body: "小執想動手" } }]).length >= 1, "words in the body");
    assert.ok(check16eShown([{ title: "VBear", options: { body: "有 1234 件事等你決定" } }]).length >= 1, "four digits");
    assert.ok(check16eShown([{ title: "VBear", options: { body: "有 3 件事等你決定", icon: "/x.png" } }]).length >= 1, "an extra option");
    assert.deepStrictEqual(check16eSent([{ count: 2, notify: true }, { ask: true }]), []);
    assert.ok(check16eSent([{ count: 2, notify: true, text: "x" }]).length >= 1, "an extra key");
    assert.ok(check16eSent([{ ask: true, count: 1 }]).length >= 1, "ask with another key");
    assert.ok(check16eSent([{ ask: false }]).length >= 1, "ask that is not true");
    assert.ok(check16eSent([{ count: "2", notify: true }]).length >= 1, "a string count");
    assert.ok(check16eSent([{ count: 1000, notify: true }]).length >= 1, "over 999");
    assert.deepStrictEqual(check16eWrites([["vbear-notify", "on"], ["vbear-notify", null]]), []);
    assert.ok(check16eWrites([["sid:theme", "\"dark\""]]).length >= 1, "another key");
    assert.ok(check16eWrites([["vbear-notify", "yes"]]).length >= 1, "another value");
  });

  // ---- off unless the person turned it on; nothing asked while loading ------------------------------------------------------------------
  await test("16e: there is a block 通知 in the settings, the switch is off, its line says where it shows and what it holds; nothing is written", async () => {
    const page = await settingsPage();
    const box = one(page.main, "data-settings", "notify");
    assert.ok(box, "the notification block is there");
    const input = switchOf(page);
    assert.ok(input && input.tag === "input", "the switch");
    assert.strictEqual(isOn(input), false, "off by default");
    const t = text(box);
    assert.ok(t.includes("通知只在這台 Mac 上顯示，內容只有「有幾件事等你決定」，不會有員工說的話或你的對話。"), t);
    assert.ok(t.includes("有事等你決定時，用 Mac 的通知提醒我"));
    assert.deepStrictEqual(page.writes, []);
    assert.strictEqual(page.asked.n, 0);
    assert.strictEqual(posts(page).length, 0);
  });

  await test("16e: a key other than \"on\" is off (nothing, \"off\", \"1\", \"true\")", async () => {
    for (const v of ["off", "1", "true", "ON", ""]) {
      const page = await settingsPage({ store: { "vbear-notify": v } });
      assert.strictEqual(isOn(switchOf(page)), false, JSON.stringify(v));
    }
    const on = await settingsPage({ store: { "vbear-notify": "on" } });
    assert.strictEqual(isOn(switchOf(on)), true, "\"on\" is on");
  });

  await test("16e: loading the home page, the settings page and another page asks the browser 0 times and the app 0 times", async () => {
    for (const hash of ["#/", "#/settings", "#/routines", "#/skills"]) {
      for (const bridge of [false, true]) {
        const page = boot(hash, world({ waiting: dues(2) }), { bridge });
        await tick(80);
        await page.tickBar(); await page.tickHome();
        assert.strictEqual(page.asked.n, 0, `${hash} bridge=${bridge}`);
        assert.strictEqual(page.sent.filter((s) => s && s.ask !== undefined).length, 0, `${hash} bridge=${bridge}: an ask message`);
        assert.deepStrictEqual(check16eSent(page.sent), [], hash);
        assert.deepStrictEqual(page.writes, [], hash);
        assert.strictEqual(page.shown.length, 0);
      }
    }
  });

  // ---- the click on the switch is the only thing that asks ------------------------------------------------------------------------------
  await test("16e (browser): turning the switch on asks the browser once; allowed: the key is written, the switch stays on, the line says so", async () => {
    const page = await settingsPage({ permissionAnswer: "granted" });
    await press(page, true);
    assert.strictEqual(page.asked.n, 1, "one request for the allowance");
    assert.deepStrictEqual(page.writes, [["vbear-notify", "on"]]);
    assert.strictEqual(isOn(switchOf(page)), true);
    assert.ok(/已打開/.test(text(resultOf(page))), text(resultOf(page)));
    assert.strictEqual(posts(page).length, 0, "nothing is sent to the server");
  });

  await test("16e (browser): not allowed: the switch goes back off, nothing is written, the line says the browser did not allow; it does not ask again by itself", async () => {
    const page = await settingsPage({ permissionAnswer: "denied" });
    await press(page, true);
    assert.strictEqual(page.asked.n, 1);
    assert.strictEqual(isOn(switchOf(page)), false, "back off");
    assert.deepStrictEqual(page.writes, []);
    assert.ok(text(resultOf(page)).includes("瀏覽器沒有允許"), text(resultOf(page)));
    await page.tickBar(); await tick(10);
    assert.strictEqual(page.asked.n, 1, "no second request");
  });

  await test("16e (browser): already denied in the browser: pressing the switch does not ask again, it says the browser did not allow", async () => {
    const page = await settingsPage({ permission: "denied" });
    await press(page, true);
    assert.strictEqual(page.asked.n, 0, "a refusal that is already there is not asked again");
    assert.strictEqual(isOn(switchOf(page)), false);
    assert.ok(text(resultOf(page)).includes("瀏覽器沒有允許"), text(resultOf(page)));
    assert.deepStrictEqual(page.writes, []);
  });

  await test("16e (browser): already allowed: pressing the switch turns it on without asking", async () => {
    const page = await settingsPage({ permission: "granted" });
    await press(page, true);
    assert.strictEqual(page.asked.n, 0);
    assert.deepStrictEqual(page.writes, [["vbear-notify", "on"]]);
  });

  await test("16e (browser): a browser without notifications: the switch goes back off and says so; nothing is written", async () => {
    const page = await settingsPage({ noNotification: true });
    await press(page, true);
    assert.strictEqual(isOn(switchOf(page)), false);
    assert.deepStrictEqual(page.writes, []);
    assert.ok(/不能發通知|沒有.*通知/.test(text(resultOf(page))), text(resultOf(page)));
  });

  await test("16e (browser): turning it off removes the key and says so", async () => {
    const page = await settingsPage({ permission: "granted", store: { "vbear-notify": "on" } });
    await press(page, false);
    assert.deepStrictEqual(page.writes, [["vbear-notify", null]]);
    assert.strictEqual(page.asked.n, 0);
    assert.ok(/已關閉/.test(text(resultOf(page))), text(resultOf(page)));
  });

  await test("16e (browser): the allowance was taken back later: the switch shows on, and says the browser does not allow now", async () => {
    const page = await settingsPage({ permission: "denied", store: { "vbear-notify": "on" } });
    assert.ok(text(resultOf(page)).includes("瀏覽器現在沒有允許"), text(resultOf(page)));
  });

  await test("16e (app): the click sends one {ask:true}; the switch waits (no key yet); granted: on, the key is written, the app is told the number with notify true", async () => {
    const page = await settingsPage({ bridge: true }, world({ waiting: dues(2) }));
    await page.tickBar();
    const before = page.sent.length;
    await press(page, true);
    const asks = page.sent.filter((s) => s && s.ask !== undefined);
    assert.strictEqual(asks.length, 1, "one ask");
    assert.deepStrictEqual(asks[0], { ask: true });
    assert.strictEqual(page.asked.n, 0, "the app asks the system, not the browser");
    assert.deepStrictEqual(page.writes, [], "no key before the answer");
    assert.strictEqual(typeof evalIn(page, "window.vbearNotifyAnswer"), "function");
    evalIn(page, 'window.vbearNotifyAnswer("granted")'); await tick(20);
    assert.deepStrictEqual(page.writes, [["vbear-notify", "on"]]);
    assert.strictEqual(isOn(switchOf(page)), true);
    const told = page.sent.slice(before).filter((s) => s && s.count !== undefined);
    assert.ok(told.length >= 1 && told[told.length - 1].notify === true && told[told.length - 1].count === 2, JSON.stringify(told));
    assert.deepStrictEqual(check16eSent(page.sent), []);
  });

  await test("16e (app): denied: the switch goes back off and says Mac did not allow; no key", async () => {
    const page = await settingsPage({ bridge: true });
    await press(page, true);
    evalIn(page, 'window.vbearNotifyAnswer("denied")'); await tick(20);
    assert.strictEqual(isOn(switchOf(page)), false);
    assert.deepStrictEqual(page.writes, []);
    assert.ok(text(resultOf(page)).includes("Mac 沒有允許 VBear 發通知，可以到「系統設定 → 通知」打開。"), text(resultOf(page)));
  });

  await test("16e (app): the system cannot answer (not signed): the switch goes back off and says Mac did not allow, truthfully", async () => {
    const page = await settingsPage({ bridge: true });
    await press(page, true);
    evalIn(page, 'window.vbearNotifyAnswer("unavailable")'); await tick(20);
    assert.strictEqual(isOn(switchOf(page)), false);
    assert.deepStrictEqual(page.writes, []);
    assert.ok(text(resultOf(page)).includes("Mac 沒有允許"), text(resultOf(page)));
  });

  await test("16e (app): an answer nobody asked for, or a word that is not one of the three, changes nothing", async () => {
    const page = await settingsPage({ bridge: true });
    evalIn(page, 'window.vbearNotifyAnswer("granted")'); await tick(10);
    assert.deepStrictEqual(page.writes, [], "no question, no answer taken");
    await press(page, true);
    evalIn(page, 'window.vbearNotifyAnswer("<b>granted</b>")'); await tick(10);
    assert.deepStrictEqual(page.writes, [], "a word that is not one of the three");
    evalIn(page, 'window.vbearNotifyAnswer("granted")'); await tick(10);
    assert.deepStrictEqual(page.writes, [["vbear-notify", "on"]]);
  });

  await test("16e (app): turning it off removes the key and tells the app notify false with the same number", async () => {
    const page = await settingsPage({ bridge: true, store: { "vbear-notify": "on" } }, world({ waiting: dues(3) }));
    await page.tickBar();
    await press(page, false);
    assert.deepStrictEqual(page.writes, [["vbear-notify", null]]);
    const last = page.sent[page.sent.length - 1];
    assert.deepStrictEqual(last, { count: 3, notify: false });
    assert.strictEqual(page.sent.filter((s) => s.ask !== undefined).length, 0);
  });

  await test("16e (app): notify is true in the message only with the key on and a whole read; the number goes with it", async () => {
    const W = world({ waiting: dues(2) });
    const off = boot("#/routines", W, { bridge: true }); await tick(80); await off.tickBar();
    assert.ok(off.sent.length >= 1 && off.sent.every((s) => s.notify === false), "off: " + JSON.stringify(off.sent));
    const on = boot("#/routines", world({ waiting: dues(2) }), { bridge: true, store: { "vbear-notify": "on" } }); await tick(80); await on.tickBar();
    assert.deepStrictEqual(on.sent[on.sent.length - 1], { count: 2, notify: true });
    const part = boot("#/routines", world({ waiting: dues(2), fail: { "GET /api/waiting": { status: 500 } } }), { bridge: true, store: { "vbear-notify": "on" } }); await tick(80); await part.tickBar();
    assert.ok(part.sent.length >= 1 && part.sent.every((s) => s.notify === false && s.count === 0), "a read that was not whole: " + JSON.stringify(part.sent));
    assert.strictEqual(on.shown.length, 0, "in the app the page makes none: the app does");
  });

  await test("16e (app): a read that was not whole and then whole again sends the number with notify false and then true (the app does not read it as new)", async () => {
    const W = world({ waiting: dues(2) });
    const page = boot("#/routines", W, { bridge: true, store: { "vbear-notify": "on" } }); await tick(80);
    await page.tickBar();
    W.fail["GET /api/waiting"] = { status: 500 };
    await page.tickBar();
    delete W.fail["GET /api/waiting"];
    await page.tickBar();
    const seq = page.sent.map((s) => `${s.count}:${s.notify}`);
    assert.deepStrictEqual(seq.slice(-3), ["2:true", "0:false", "2:true"], seq.join(" "));
  });

  // ---- when the browser makes one ----------------------------------------------------------------------------------------------------
  await test("16e (browser): the number grew while the page is hidden: one notification, title VBear, body 有 N 件事等你決定; clicking it goes home", async () => {
    const W = world({ waiting: dues(1) });
    const page = boot("#/routines", W, { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    await page.tickBar();                                    // the first number is only remembered
    assert.strictEqual(page.shown.length, 0);
    page.doc.hidden = true;
    W.waiting = dues(2);
    await page.tickBar();
    assert.strictEqual(page.shown.length, 1);
    assert.deepStrictEqual(check16eShown(page.shown), []);
    assert.strictEqual(page.shown[0].options.body, "有 2 件事等你決定");
    page.location.hash = "#/skills";
    page.shown[0].onclick();
    assert.strictEqual(page.location.hash, "#/");
    assert.ok(page.shown[0].closed, "the notification is closed");
    assert.ok(page.focusCalls >= 1, "the window is brought forward");
  });

  await test("16e (browser): no notification when the page is in front and focused; one when it is visible but the window has no focus", async () => {
    const W = world({ waiting: dues(1) });
    const page = boot("#/routines", W, { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    await page.tickBar();
    W.waiting = dues(2); await page.tickBar();
    assert.strictEqual(page.shown.length, 0, "in front");
    page.focus = false;
    W.waiting = dues(3); await page.tickBar();
    assert.strictEqual(page.shown.length, 1, "no focus");
    assert.strictEqual(page.shown[0].options.body, "有 3 件事等你決定");
  });

  await test("16e (browser): the same number, fewer, the switch off, the allowance gone, an incomplete read: none; a new one after fewer: one", async () => {
    const W = world({ waiting: dues(2) });
    const page = boot("#/routines", W, { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    page.focus = false;                    // the window is behind another one: the timer runs, so the switch is what decides
    await page.tickBar();
    await page.tickBar();
    assert.strictEqual(page.shown.length, 0, "the same number");
    W.waiting = dues(1); await page.tickBar();
    assert.strictEqual(page.shown.length, 0, "fewer");
    W.waiting = dues(2); W.fail["GET /api/waiting"] = { status: 500 }; await page.tickBar();
    assert.strictEqual(page.shown.length, 0, "an incomplete read");
    delete W.fail["GET /api/waiting"]; await page.tickBar();
    assert.strictEqual(page.shown.length, 1, "after fewer and a whole read, one more is new");
    assert.strictEqual(page.shown[0].options.body, "有 2 件事等你決定");
    page.Notification.permission = "denied";
    W.waiting = dues(3); await page.tickBar();
    assert.strictEqual(page.shown.length, 1, "the browser's allowance is gone");
    page.Notification.permission = "granted";
    page.store.delete("vbear-notify");
    W.waiting = dues(4); await page.tickBar();
    assert.strictEqual(page.shown.length, 1, "the switch is off");
  });

  await test("16e (browser): the switch off from the start never makes one, however the number moves", async () => {
    const W = world({ waiting: dues(1) });
    const page = boot("#/routines", W, { permission: "granted" }); await tick(80);
    page.focus = false;
    for (const n of [2, 5, 9]) { W.waiting = dues(n); await page.tickBar(); }
    assert.strictEqual(page.shown.length, 0);
    assert.strictEqual(page.asked.n, 0);
  });

  await test("16e (browser): turning it on while 2 wait is not 'new': the next whole read at 2 is silent, at 3 tells", async () => {
    const W = world({ waiting: dues(2) });
    const page = boot("#/settings", W, { permission: "granted" }); await tick(80);
    await page.tickBar();
    await press(page, true);
    page.doc.hidden = true;
    await page.tickBar();
    assert.strictEqual(page.shown.length, 0);
    W.waiting = dues(3); await page.tickBar();
    assert.strictEqual(page.shown.length, 1);
  });

  await test("16e (browser): a number of 1000 or more is a notification of up to three digits (999)", async () => {
    const W = world({ waiting: dues(1) });
    const page = boot("#/routines", W, { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    await page.tickBar();
    page.doc.hidden = true;
    W.waiting = dues(1200); await page.tickBar();
    assert.strictEqual(page.shown.length, 1);
    assert.strictEqual(page.shown[0].options.body, "有 999 件事等你決定");
    assert.deepStrictEqual(check16eShown(page.shown), []);
  });

  await test("16e: the home page's 5-second update also makes one (the number grew while the page is away)", async () => {
    const W = world({ waiting: dues(1) });
    const page = boot("#/", W, { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    page.focus = false;                    // the window is behind another one (the page itself is visible: the 5-second timer runs)
    W.waiting = dues(2);
    await page.tickHome();
    assert.strictEqual(page.shown.length, 1, "home tick");
    assert.deepStrictEqual(check16eShown(page.shown), []);
  });

  await test("16e: no reads are added: only GETs, /api/chats not more often than every 30 seconds, and nothing is read while hidden with the switch off", async () => {
    const W = world({ waiting: dues(1) });
    const off = boot("#/routines", W, {}); await tick(80);
    off.doc.hidden = true;
    const n0 = off.log.length;
    await off.tickBar();
    assert.strictEqual(off.log.length, n0, "hidden and off: the timer reads nothing, as before");
    const on = boot("#/routines", world({ waiting: dues(1) }), { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    on.doc.hidden = true;
    const n1 = on.log.length;
    await on.tickBar();
    assert.ok(on.log.length > n1, "hidden and on: it goes on reading");
    assert.strictEqual(posts(on).length, 0);
    const homeOn = boot("#/", world({ waiting: dues(1) }), { permission: "granted", store: { "vbear-notify": "on" } }); await tick(80);
    homeOn.doc.hidden = true;
    const n2 = homeOn.log.length;
    await homeOn.tickBar();
    assert.ok(homeOn.log.slice(n2).some(([, u]) => u.startsWith("/api/waiting")), "on the home page, hidden and on: the 30-second timer reads the waiting list");
    assert.strictEqual(posts(homeOn).length, 0);
  });

  // ---- the sources -----------------------------------------------------------------------------------------------------------------
  await test("16e: the page's sources have no push, no service worker, no innerHTML; the allowance is asked in one place, and only the switch's handler reaches it", () => {
    for (const w of ["PushManager", "serviceWorker", "ServiceWorker", "pushManager"]) assert.ok(!SOURCE.includes(w), w);
    const asks = SOURCE.split("requestPermission").length - 1;
    assert.strictEqual(asks, 1, "one place asks the browser: " + asks);
    const i = SOURCE.indexOf("// ---------- notifications (v0.22, P48-4)");
    const j = SOURCE.indexOf("// ---------- end of notifications");
    assert.ok(i > 0 && j > i, "the section is marked");
    const section = SOURCE.slice(i, j);
    assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(section));
    assert.ok(!/api\.(post|patch|send|del)\(|fetch\(/.test(section), "the section sends nothing to the server");
    assert.ok(section.includes("requestPermission"), "the one question is in the section");
    const sectionAsk = section.split("postMessage({ ask: true })").length - 1;
    assert.strictEqual(sectionAsk, 1, "one ask message");
    assert.strictEqual(SOURCE.split("postMessage({ ask: true })").length - 1, 1, "and only in the section");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) console.log("SOME FAILED");
})();
