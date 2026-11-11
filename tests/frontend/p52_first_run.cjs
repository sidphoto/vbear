// P52-1 (v0.25.0, ADR 0017): a person with no employee does the first run on the home page, on one page: pick one AI, prepare it with the start-up page's own pieces, press
// 「建立 CEO，開始聊」, and be in the conversation. Every step is the person's own press.
//
// Guard 19a: on the home page the chat safety check is asked for only by 「確認，開始」 of the confirmation (the start-up page's one button), after the whole cost was told; there is no
//            second way in (choosing, loading, drawing again and the 5-second refresh send nothing).
// Guard 19b: the CEO is made only by the press of 「建立 CEO，開始聊」 (one POST /api/agent-profiles, in safe mode, on the tool the person chose); loading the page, choosing a card and
//            drawing again make nothing; the opening sentence is only put in the box.
// (19c, the words for a version VBear does not know, is in tests/frontend/p52_words.cjs.) Each rule has made-up broken runs that the judges below must catch (see the last tests).
// Runs the whole of web/app.js (with its start-up code) in a vm context against a small synthetic DOM, a fetch stub the test answers, and a clock the test moves by hand.
// NOT a browser test.
//
// Run: node tests/frontend/p52_first_run.cjs   (exit code 0 = pass)
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
  focus() { Node.focused = this; if (Node.docRef) Node.docRef.activeElement = this; }
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
  Node.docRef = doc;
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
  const store = { ...(extra.storage || {}) };       // the browser's storage; `stored` lists the keys written, in order
  const stored = [];
  const sent = [];                      // what the page handed to the app
  const win = { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
  if (extra.bridge) win.webkit = { messageHandlers: { vbearWaiting: { postMessage: (m) => sent.push(m) } } };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams, Date: FakeDate,
    window: win,
    localStorage: { getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null), setItem: (k, v) => { store[k] = String(v); stored.push(k); } },
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
  return { ctx, main, log, location, ids, go, body, doc, bar, logo, mark, sent, advance, fireNow, hold, release, tickHome, tickBar, intervals, store, stored };
}
const evalIn = (page, code) => vm.runInContext(code, page.ctx);
const posts = (page) => page.log.filter(([m]) => m !== "GET");
async function home(W, hash = "#/", extra) { const page = boot(hash, W, extra); await tick(60); return page; }

const jr = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => "application/json" }, json: async () => data });
const PICK = "vbear-setup-pick";
const inDetails = (n) => { for (let p = n.parentNode; p; p = p.parentNode) if (p.tag === "details") return true; return false; };

// ---- fixtures: what the console answers (invented tools and versions) -------------------------------------------------------------------------
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
const WARM = "2.1.300";
const supportOf = (over = {}) => ({ engine: "claude-chat", detected: WARM, verified: [], state: "unverified", message: "Claude Code 2.1.300 還沒通過聊天驗證。", policy: null, verify: { running: false },
  codex: { state: "unverified", version: "0.9.1", why: "", verify: { running: false } }, agy: { state: "unverified", version: "3.0.2", why: "", verify: { running: false } }, ...over });
const verifiedSupport = () => supportOf({ state: "verified", message: "" });
const OPENING = "你好，請先問我三個問題，了解我想做什麼。";
const INSTRUCTIONS = "你是我的 CEO（執行長）。請用一般人聽得懂的話跟我說話。";
const CARD = "prof-0123456789ab";
const CHAT = "c-0123456789abcdef";
const planOf = (tool = "claude", over = {}) => ({ ok: true, needed: true, can_create: true, go: null, reason: "", tool, tool_name: NAMES[tool], name: "CEO", position: "planner",
  launch_mode: "safe", instructions: INSTRUCTIONS, opening: OPENING, chat_ready: null, chat_note: "", ...over });

// What the console says for the first run; the tests change `F`. Everything is a fixture: no tool is run.
function makeConsole(over = {}) {
  const F = {
    tools: [trow("claude"), trow("codex"), trow("agy"), trow("grok")], support: supportOf(), plan: (tool) => planOf(tool || "claude"), daily: 3, chatsFail: false, toolsFail: false, created: null,
    tryReply: () => jr({ ok: true, success: true, result: "success", message: "Claude Code 回應了，這個 AI 工具可以用。", spent_usd: "0.01" }),
    verifyReply: () => jr({ ok: true, status: { running: true } }, 202), createFail: null, ...over,
  };
  F.fetch = async (url, method, body) => {
    const p = url.split("?")[0];
    if (method === "GET" && p === "/api/setup/tools") return F.toolsFail ? jr({ error: "壞了" }, 500) : jr({ ok: true, any_ready: F.tools.some((t) => t.ready), setup_done: true, tools: F.tools });
    if (method === "GET" && p === "/api/chats") {
      if (F.chatsFail) return jr({ error: "壞了" }, 500);
      const cards = F.created ? [{ id: CARD, name: F.created.name, position: "planner", tool: F.created.tool, engine: `${F.created.tool}-chat`, enabled: true, can_chat: true, code: null, reason: null, instructions: true }] : [];
      return jr({ chats: [], more: 0, cards, support: F.support, limits: { per_turn_usd: "0.05", daily_usd: "3" }, ledger: { lamp: "green", spent_usd: "0", daily_usd: "3" }, problems: [] });
    }
    if (method === "GET" && p === "/api/first-ceo") { const t = /[?&]tool=([a-z]+)/.exec(url); return jr(F.plan(t ? t[1] : null)); }
    if (method === "GET" && p === "/api/setup/daily-limit") return F.daily === null ? jr({ error: "壞了" }, 500) : jr({ ok: true, daily_usd: F.daily, choices: [1, 3, 10] });
    if (method === "POST" && /^\/api\/setup\/tools\/[a-z]+\/try$/.test(p)) return F.tryReply(p.split("/")[4], body);
    if (method === "POST" && p === "/api/chat-support/verify") return F.verifyReply(body);
    if (method === "POST" && p === "/api/agent-profiles") {
      if (F.createFail) return jr({ ok: false, error: F.createFail }, 400);
      F.created = { name: body.name, tool: body.model.tool };
      return jr({ ok: true, profile: { id: CARD, name: body.name } });
    }
    if (method === "POST" && p === "/api/chats") return jr({ ok: true, chat: { id: CHAT, profile_id: body.profile_id, created_at: 1 } }, 201);
    return null;
  };
  return F;
}
async function firstPage(over = {}, extra = {}) {
  const F = makeConsole(over);
  const W = world({ profiles: [], cards: [], tools: [], support: {}, config: extra.config, posts: extra.posts });
  const page = boot("#/", W, { ...extra, fetch: F.fetch });
  await tick(60);
  page.F = F; page.W = W;
  return page;
}
// the page keeps its own small preference (the theme) in the same storage; only the keys of the first run are looked at
const written = (page) => page.stored.filter((k) => k !== "sid:theme");
const gets = (page, p) => page.log.filter(([m, u]) => m === "GET" && u.split("?")[0] === p);
const block = (page) => one(page.main, "data-home", "first-run");
const pickIds = (page) => all(page.main, (n) => n.hasAttribute && n.hasAttribute("data-setup-pick")).map((n) => n.getAttribute("data-setup-pick"));
const goBtn = (page, id) => byData(page.main, "data-setup-pick-go", id)[0];
const chk = (page, k) => byData(page.main, "data-setup-check", k)[0];
const item = (page, k) => byData(page.main, "data-setup-check-item", k)[0];
const h = (page, v) => one(page.main, "data-home", v);
const click = async (n, t = 30) => { n.click(); await tick(t); };
const choose = async (page, id) => { await click(goBtn(page, id)); };
// a page whose Claude Code is logged in and has not passed the chat check yet / has passed it
const readyClaude = () => ({ tools: [readyRow("claude", { version: WARM }), trow("codex"), trow("agy"), trow("grok")] });

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); } catch (e) { console.log("FAIL -", name); console.log((e && e.stack) || e); process.exitCode = 1; }
}

// ---- the judges: a recorded run goes in, the broken things come out ------------------------------------------------------------------------------
// 19a: what was sent for the chat safety check. `log`: [method, url, body]; `confirmed`: 「確認，開始」 was pressed; `shown`: the version on screen; `passedBefore`: that version had passed.
function judge19a(log, { engine, shown, passedBefore, confirmed }) {
  const bad = [];
  const post = log.filter((c) => c[0] !== "GET");
  const tries = post.filter((c) => /^\/api\/setup\/tools\/[^/]+\/try$/.test(c[1].split("?")[0]));
  const verifies = post.filter((c) => c[1] === "/api/chat-support/verify");
  if (!confirmed && (tries.length || verifies.length)) bad.push("a check was asked for before 「確認，開始」");
  if (confirmed && tries.length !== 1) bad.push("not exactly one try");
  if (tries[0] && JSON.stringify(tries[0][2]) !== JSON.stringify({ confirmed: true })) bad.push("the try did not carry confirmed:true");
  if (passedBefore && verifies.length) bad.push("a version that had passed was verified again");
  if (verifies.length > 1) bad.push("more than one verify");
  for (const v of verifies) {
    if (!v[2] || v[2].engine !== engine) bad.push("the verify is for another tool");
    if (!v[2] || v[2].version !== shown) bad.push("the verify does not carry the version on screen");
    if (!tries.length || log.indexOf(v) < log.indexOf(tries[0])) bad.push("the verify came before the try");
  }
  return bad;
}
// 19a (source): the requests of the safety check are written only inside setupKit, in the handler of 「確認，開始」; the home block names neither of them.
function judge19aSource(src) {
  const bad = [];
  const hs = src.indexOf("function homeFirstRun("), he = src.indexOf("// ---- end of the first run on the home page");
  const ks = src.indexOf("function setupKit("), ke = src.indexOf("// ---------- end of the setup kit");
  if (hs < 0 || he < hs || ks < 0 || ke < ks) return ["the parts are not where they are expected"];
  const home = src.slice(hs, he), kit = src.slice(ks, ke);
  if (/chat-support|\/try\b/.test(home)) bad.push("the home block asks for a check itself");
  const cs = kit.indexOf("confirm: async (id)");
  const ce = kit.indexOf("return { toolCard");
  if (cs < 0 || ce < cs) return bad.concat(["no confirm handler"]);
  const inConfirm = kit.slice(cs, ce);
  if (!/chat-support\/verify/.test(inConfirm)) bad.push("the confirm handler does not ask for the verify");
  for (const m of kit.matchAll(/chat-support\/verify/g)) if (m.index < cs || m.index > ce) bad.push("the verify is asked for outside the confirm handler");
  return bad;
}
// 19b: what was sent to make the CEO. `pressed`: 「建立 CEO，開始聊」 was pressed; `tool`: the one the person chose.
// P52-5: the first run also writes `setup_done` (the same request as the start-up page's leave button), once, only after the press has made the CEO, and only if it was not already true
// (`wasDone`: what the config said before; leave it out when that is not looked at).
function judge19b(log, { pressed, tool, wasDone }) {
  const bad = [];
  const post = log.filter((c) => c[0] !== "GET");
  const made = post.filter((c) => c[1] === "/api/agent-profiles");
  const done = post.filter((c) => c[1] === "/api/config" && c[2] && Object.prototype.hasOwnProperty.call(c[2], "setup_done"));
  if (!pressed && done.length) bad.push("setup_done was written without the press");
  if (done.some((c) => JSON.stringify(c[2]) !== JSON.stringify({ setup_done: true }))) bad.push("setup_done was written with something else than true alone");
  if (pressed && done.length > 1) bad.push("setup_done was written more than once");
  if (pressed && wasDone === true && done.length) bad.push("setup_done was written though it was already true");
  if (pressed && wasDone === false && done.length !== 1) bad.push("setup_done was not written once after the press");
  if (done.length && made.length) { const first = post.findIndex((c) => c[1] === "/api/agent-profiles"); const at = post.indexOf(done[0]); if (at < first) bad.push("setup_done was written before the CEO was made"); }
  if (done.length && !made.length) bad.push("setup_done was written though no CEO was made");
  if (!pressed && made.length) bad.push("a CEO was made without the press");
  if (pressed) {
    if (made.length !== 1) bad.push("not exactly one card made");
    const b = made[0] && made[0][2];
    if (b && b.launch_mode !== "safe") bad.push("the card is not in safe mode");
    if (b && (!b.model || b.model.tool !== tool)) bad.push("the card is for another tool than the one chosen");
    if (b && b.position !== "planner") bad.push("not the CEO's position");
  }
  if (post.some((c) => /\/messages$/.test(c[1]))) bad.push("a message was sent");
  return bad;
}
// 19b (source): the card is made in one function (ceoCreate), and it is called from exactly two places, each inside a click handler.
function judge19bSource(src) {
  const bad = [];
  const calls = [...src.matchAll(/\bceoCreate\(/g)].map((m) => m.index).filter((i) => !/function\s+$/.test(src.slice(Math.max(0, i - 12), i)));
  if (calls.length !== 2) bad.push(`ceoCreate is called ${calls.length} times, not twice`);
  for (const i of calls) if (!/addEventListener\("click"/.test(src.slice(Math.max(0, i - 700), i))) bad.push("a call of ceoCreate that is not inside a click handler");
  if ([...src.matchAll(/api\.post\("\/api\/agent-profiles"/g)].filter((m) => m.index > src.indexOf("async function ceoCreate(") && m.index < src.indexOf("async function viewCeo(")).length !== 1) bad.push("the card is not made in ceoCreate");
  // P52-5: in the home block `setup_done` is written only from inside the press's click handler (never when the block is built, loaded or redrawn)
  const from = src.indexOf("function homeFirstRun("), to = src.indexOf("// ---- end of the first run on the home page");
  if (from >= 0 && to > from) {
    const part = src.slice(from, to);
    for (const m of part.matchAll(/setup_done\s*:\s*true/g)) {
      const before = part.slice(0, m.index);
      const click = before.lastIndexOf('addEventListener("click"');
      if (click < 0 || m.index - click > 1400) bad.push("setup_done is written outside the click of 「建立 CEO，開始聊」");
    }
  }
  return bad;
}

(async () => {
  // ---- what the block shows -----------------------------------------------------------------------------------------------------------------------
  await test("no employee: the block opens with the big line and the small line, the picker in the fixed order, nothing chosen; the three steps and their two buttons are gone", async () => {
    const page = await firstPage();
    const b = block(page);
    assert.ok(b, "the block is there");
    const title = all(b, (n) => n.tag === "h2" && n.className.includes("home-first-title"))[0];
    assert.strictEqual(text(title), "先選一家你有在用的 AI");
    assert.ok(text(b).includes("選了就能開始聊，之後隨時可以再加。"));
    assert.deepStrictEqual(pickIds(page), ["claude", "codex", "agy"]);
    assert.ok(text(b).includes("xAI Grok：之後支援（現在還不能用來聊天）"), "the grey line of ADR 0014");
    assert.ok(!/建議|推薦/.test(text(b)));
    assert.strictEqual(one(page.main, "data-home", "first-steps"), null);
    assert.strictEqual(byData(page.main, "data-home-step", "1").length, 0);
    assert.strictEqual(all(page.main, (n) => n.tag === "a" && ["#/ceo"].includes(n.getAttribute("href"))).length, 0, "no button to the CEO page on the home page");
    assert.strictEqual(all(b, (n) => n.tag === "a" && n.getAttribute("href") === "#/setup" && text(n) === "看 AI 工具").length, 0);
    const link = h(page, "first-setup-link");
    assert.ok(link && link.tag === "a" && link.getAttribute("href") === "#/setup" && text(link) === "到開始設定看全部 AI 工具");
    assert.deepStrictEqual(all(page.main, (n) => n.tag === "section" && n.getAttribute("data-home")).map((n) => n.getAttribute("data-home")), ["waiting", "first-run"]);
    assert.deepStrictEqual(loadingKeys(page.main), []);
    assert.deepStrictEqual(posts(page), [], "loading the page sent only GETs");
    assert.deepStrictEqual(written(page), [], "nothing is written to the browser until a card is chosen");
    assert.ok(text(byData(page.main, "data-setup-pick", "claude")[0]).includes("還沒安裝"));
    assert.strictEqual(h(page, "first-ceo-create"), null, "no CEO button before a tool is chosen and can chat");
  });

  await test("the frame is there at once: while the tools are being read it says 正在看你的 AI 工具… (one loading mark) and draws no conclusion and no button to choose; then the cards", async () => {
    const page = await firstPage({}, { hold: ["/api/setup/tools"] });
    assert.ok(block(page), "the block is there");
    assert.deepStrictEqual(loadingKeys(page.main), ["first-run"]);
    assert.ok(text(block(page)).includes("正在看你的 AI 工具…"));
    assert.ok(!/還沒安裝|裝好了|讀不到|可以聊天了/.test(text(block(page))), "no conclusion before the answer: " + text(block(page)));
    assert.strictEqual(byData(page.main, "data-setup-pick-go", "claude").length, 0, "nothing can be chosen before the state is known");
    await page.release();
    assert.deepStrictEqual(loadingKeys(page.main), []);
    assert.ok(goBtn(page, "claude") && goBtn(page, "codex") && goBtn(page, "agy"));
  });

  await test("the tools cannot be read: it says so (no cards, nothing drawn as an empty Mac) and 「再讀一次」 reads again on the press", async () => {
    const page = await firstPage({ toolsFail: true });
    assert.ok(text(block(page)).includes("讀不到你的 AI 工具的狀態。"));
    assert.strictEqual(pickIds(page).length, 0);
    assert.deepStrictEqual(loadingKeys(page.main), []);
    page.F.toolsFail = false;
    await click(h(page, "first-retry"));
    assert.deepStrictEqual(pickIds(page), ["claude", "codex", "agy"]);
    assert.ok(gets(page, "/api/setup/tools").some(([, u]) => u.includes("force=1")), "the press asked for a fresh look");
    assert.deepStrictEqual(posts(page), []);
  });

  await test("choosing a card sends nothing and writes only vbear-setup-pick; it expands that one tool in place; 「換一家」 puts the cards back and writes nothing", async () => {
    const page = await firstPage(readyClaude());
    await choose(page, "claude");
    assert.deepStrictEqual(posts(page), []);
    assert.deepStrictEqual(written(page), [PICK]);
    assert.strictEqual(page.store[PICK], "claude");
    assert.strictEqual(pickIds(page).length, 0, "the cards are put away");
    assert.ok(text(h(page, "first-prepare")).includes("Claude Code") && byData(page.main, "data-tool", "claude").length === 1);
    assert.ok(text(one(page.main, "data-setup", "picked")).includes("你選了：Anthropic Claude（Claude Code）"));
    assert.ok(chk(page, "go"), "the one button of the safety check is there");
    await click(one(page.main, "data-setup", "change-pick"));
    assert.deepStrictEqual(pickIds(page), ["claude", "codex", "agy"]);
    assert.deepStrictEqual(written(page), [PICK], "「換一家」 wrote nothing");
    assert.deepStrictEqual(posts(page), []);
  });

  await test("a remembered choice opens that tool at once (the person's own earlier choice); a value that is not one of the three is ignored", async () => {
    let page = await firstPage(readyClaude(), { storage: { [PICK]: "claude" } });
    assert.ok(text(one(page.main, "data-setup", "picked")).includes("Anthropic Claude"));
    assert.deepStrictEqual(posts(page), []);
    page = await firstPage({}, { storage: { [PICK]: "xai" } });
    assert.deepStrictEqual(pickIds(page), ["claude", "codex", "agy"]);
  });

  await test("a tool that cannot chat yet: no CEO button, no name box, no request for the plan; one line says it (the state that was read)", async () => {
    const page = await firstPage({}, { storage: { [PICK]: "claude" } });
    assert.strictEqual(h(page, "first-ceo-create"), null);
    assert.strictEqual(h(page, "first-ceo-name"), null);
    assert.strictEqual(gets(page, "/api/first-ceo").length, 0, "the plan is only asked for when the tool can chat");
    assert.ok(text(h(page, "first-reason")).includes("還沒安裝"), text(h(page, "first-reason")));
    page.F.tools = [readyRow("claude", { version: WARM }), trow("codex"), trow("agy"), trow("grok")];
    await page.advance(5000); await page.tickHome();
    assert.ok(text(h(page, "first-reason")).includes("安全檢查"), "the quiet refresh of the tools updates it: " + text(h(page, "first-reason")));
    assert.strictEqual(h(page, "first-ceo-create"), null);
  });

  await test("P52-2: the line says which step is missing, from the state that was read: not installed, not logged in, no safety check yet, an administrator's settings, a version VBear does not know", async () => {
    const lineOf = async (over) => text(h(await firstPage(over, { storage: { [PICK]: "claude" } }), "first-reason"));
    assert.ok((await lineOf({})).includes("還差一步：安裝 Claude Code"), "not installed");
    assert.ok((await lineOf({ tools: [installedRow("claude"), trow("codex"), trow("agy"), trow("grok")] })).includes("還差一步：登入 Claude Code"), "not logged in");
    assert.ok((await lineOf(readyClaude())).includes("還差一步：做一次聊天安全檢查"), "no safety check yet");
    assert.ok((await lineOf({ ...readyClaude(), support: supportOf({ state: "policy", message: "管理員設定擋住了" }) })).includes("有管理員設定"), "an administrator's settings");
    const UNKNOWN = "VBear 沒有 Claude Code 2.1.999 的聊天模式常數，所以不能聊天。VBear 目前能聊天的版本：2.1.318。處理方式：安裝其中一個版本，或等 VBear 更新。";
    const page = await firstPage({ tools: [readyRow("claude", { version: "2.1.999" }), trow("codex"), trow("agy"), trow("grok")], support: supportOf({ state: "unsupported", detected: "2.1.999", message: UNKNOWN }) }, { storage: { [PICK]: "claude" } });
    const unknown = h(page, "first-reason");
    assert.ok(text(unknown).includes("你的 Claude Code 是 2.1.999 版，VBear 還不認得這一版，所以先不能用它聊天。等 VBear 出新版就能用。"), text(unknown));
    const fold = all(unknown, (n) => n.getAttribute && n.getAttribute("data-plain") === "tech");
    assert.strictEqual(fold.length, 1, "the server's sentence is behind the technical details");
    assert.ok(text(fold[0]).includes(UNKNOWN));
    assert.strictEqual(h(page, "first-ceo-create"), null);
    assert.strictEqual(h(page, "first-recheck").tag, "button", "and a way to read again");
    assert.deepStrictEqual(posts(page), []);
  });

  await test("chats that cannot be read: a ready tool is said to have an unknown chat state; nothing can be made", async () => {
    const page = await firstPage({ ...readyClaude(), chatsFail: true }, { storage: { [PICK]: "claude" } });
    assert.ok(text(h(page, "first-prepare")).includes("讀不到"), text(h(page, "first-prepare")));
    assert.strictEqual(h(page, "first-ceo-create"), null);
    assert.ok(text(h(page, "first-reason")).includes("聊天的狀態讀不到"), text(h(page, "first-reason")));
  });

  // ---- 19a: the one button of the safety check --------------------------------------------------------------------------------------------------
  await test("19a: the button only opens the confirmation (0 POST) with the whole cost sentences; cancel puts it back (0 POST); loading, choosing and the refresh sent no check", async () => {
    const page = await firstPage(readyClaude());
    await choose(page, "claude");
    await page.advance(5000); await page.tickHome();
    assert.deepStrictEqual(judge19a(page.log, { engine: "claude", shown: WARM, passedBefore: false, confirmed: false }), []);
    assert.strictEqual(text(chk(page, "go")), "試一下，並做聊天安全檢查");
    await click(chk(page, "go"));
    assert.deepStrictEqual(posts(page), [], "the first press sent nothing");
    const box = one(page.main, "data-setup", "check-confirm");
    assert.ok(box, "the confirmation is in the card");
    assert.ok(text(box).includes(evalIn(page, "SETUP_TRY_ESTIMATE")) && text(box).includes("大約花不到 US$0.01"));
    assert.ok(text(box).includes(evalIn(page, "CHAT_VERIFY_COST_CLAUDE")), "the whole sentence of the safety check's cost");
    assert.ok(chk(page, "confirm") && text(chk(page, "confirm")) === "確認，開始" && chk(page, "cancel"));
    assert.strictEqual(h(page, "first-ceo-create"), null);
    await click(chk(page, "cancel"));
    assert.deepStrictEqual(posts(page), [], "cancel sent nothing");
    assert.ok(chk(page, "go") && !chk(page, "confirm"));
  });

  await test("19a: 「確認，開始」 sends one try and then the safety check of the version on screen; when the server says it passed, the CEO part opens by itself (nothing is made)", async () => {
    const page = await firstPage(readyClaude());
    await choose(page, "claude");
    await click(chk(page, "go"));
    page.F.verifyReply = () => { page.F.support = supportOf({ verify: { running: true } }); return jr({ ok: true, status: { running: true } }, 202); };
    await click(chk(page, "confirm"), 60);
    assert.deepStrictEqual(posts(page).map((c) => [c[0], c[1], c[2]]), [
      ["POST", "/api/setup/tools/claude/try", { confirmed: true }],
      ["POST", "/api/chat-support/verify", { engine: "claude", version: WARM }]]);
    assert.deepStrictEqual(judge19a(page.log, { engine: "claude", shown: WARM, passedBefore: false, confirmed: true }), []);
    assert.strictEqual(item(page, "chat").getAttribute("data-result"), "running");
    assert.ok(text(item(page, "chat")).includes("在背景做，通常要幾分鐘。可以先去建立 CEO。"));
    assert.strictEqual(h(page, "first-ceo-create"), null, "not while the check runs");
    page.F.support = verifiedSupport();
    const n = posts(page).length;
    await page.advance(31000); await page.tickHome();
    assert.strictEqual(posts(page).length, n, "the refresh only reads");
    assert.strictEqual(item(page, "chat").getAttribute("data-result"), "pass");
    assert.ok(h(page, "first-ceo-create"), "the CEO part is there now");
    assert.strictEqual(posts(page).filter((c) => c[1] === "/api/agent-profiles").length, 0, "and nothing was made");
  });

  await test("19a: a version that has already passed is not verified again (the try alone); an administrator's settings: no button, no POST", async () => {
    let page = await firstPage({ ...readyClaude(), support: verifiedSupport() }, { storage: { [PICK]: "claude" } });
    await click(chk(page, "go"));
    assert.ok(!text(one(page.main, "data-setup", "check-confirm")).includes(evalIn(page, "CHAT_VERIFY_COST_CLAUDE")), "it does not tell a cost it will not spend");
    await click(chk(page, "confirm"), 60);
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/tools/claude/try"]);
    assert.deepStrictEqual(judge19a(page.log, { engine: "claude", shown: WARM, passedBefore: true, confirmed: true }), []);
    page = await firstPage({ ...readyClaude(), support: supportOf({ state: "policy", message: "管理員設定擋住了" }) }, { storage: { [PICK]: "claude" } });
    assert.strictEqual(chk(page, "go"), undefined);
    assert.deepStrictEqual(posts(page), []);
    assert.ok(text(h(page, "first-reason")).includes("管理員設定"), text(h(page, "first-reason")));
  });

  await test("19a: a try that did not pass stops there (no verify), and what the person typed, the open fold and the open confirmation are not cleared by the refresh", async () => {
    const page = await firstPage(readyClaude(), { storage: { [PICK]: "claude" } });
    await click(chk(page, "go"));
    page.F.tryReply = () => jr({ ok: true, success: false, result: "not_logged_in", message: "Claude Code 沒有成功回應，看起來還沒登入。請先按「登入」，登入好了再試一次。" });
    await click(chk(page, "confirm"), 60);
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/tools/claude/try"]);
    assert.strictEqual(item(page, "try").getAttribute("data-result"), "fail");
    assert.strictEqual(item(page, "chat").getAttribute("data-result"), "todo");
    await click(chk(page, "go"));
    const boxBefore = one(page.main, "data-setup", "check-confirm");
    assert.ok(boxBefore);
    // something else changes (a tool the person did not choose): the block is drawn again, and the open confirmation is still open
    page.F.tools = [readyRow("claude", { version: WARM }), trow("codex"), trow("agy"), installedRow("grok", { state: "ready", ready: true, login: "marked", marked_at: 2 })];
    await page.advance(5000); await page.tickHome();
    assert.ok(one(page.main, "data-setup", "check-confirm"), "the open confirmation survived the redraw");
    assert.strictEqual(posts(page).length, 1);
  });

  // ---- 19b: the CEO ---------------------------------------------------------------------------------------------------------------------------------
  const chatReady = (over = {}) => ({ ...readyClaude(), support: verifiedSupport(), ...over });
  await test("19b: when the chosen tool can chat the plan is read for that tool (a GET), the name box has the CEO page's default, the mode line is there and not folded; nothing is made", async () => {
    const page = await firstPage(chatReady(), { storage: { [PICK]: "claude" } });
    assert.deepStrictEqual(gets(page, "/api/first-ceo").map(([, u]) => u), ["/api/first-ceo?tool=claude"]);
    const name = h(page, "first-ceo-name");
    assert.ok(name && name.value === "CEO");
    assert.strictEqual(text(h(page, "first-ceo-create")), "建立 CEO，開始聊");
    const mode = h(page, "first-ceo-mode");
    assert.strictEqual(text(mode), evalIn(page, "CEO_MODE"));
    assert.ok(!inDetails(mode) && !inDetails(h(page, "first-ceo-create")));
    assert.strictEqual(h(page, "first-ceo-agy"), null, "the Google line is only for AGY");
    assert.deepStrictEqual(judge19b(page.log, { pressed: false, tool: "claude" }), []);
    assert.deepStrictEqual(written(page), [], "a remembered pick is not written again");
  });

  await test("19b: the press makes the card the CEO page makes (one POST, safe mode, the chosen tool, the typed name), then opens the chat; the opening sentence is only put in the box", async () => {
    const page = await firstPage(chatReady(), { storage: { [PICK]: "claude" } });
    const name = h(page, "first-ceo-name");
    name.value = "小說助理"; name.dispatch("input");
    await click(h(page, "first-ceo-create"), 80);
    assert.deepStrictEqual(posts(page).map((c) => [c[0], c[1]]), [["POST", "/api/agent-profiles"], ["POST", "/api/config"], ["POST", "/api/chats"]]);
    assert.deepStrictEqual(posts(page)[0][2], { name: "小說助理", position: "planner", instructions: INSTRUCTIONS, launch_mode: "safe", model: { tool: "claude", model_id: "" } });
    assert.deepStrictEqual(posts(page)[1][2], { first_ceo_id: CARD });
    assert.deepStrictEqual(posts(page)[2][2], { profile_id: CARD });
    assert.strictEqual(page.location.hash, `#/chat/${CHAT}`, "straight into the conversation");
    assert.strictEqual(evalIn(page, `ceoDrafts.get("${CHAT}")`), OPENING, "the opening sentence waits in the box");
    assert.deepStrictEqual(judge19b(page.log, { pressed: true, tool: "claude" }), []);
    assert.strictEqual(h(page, "first-ceo-create").disabled, true, "no second press while it goes");
  });

  await test("19b: an empty name makes nothing and says so; a card the server refuses says why with the server's words and the button works again", async () => {
    const page = await firstPage(chatReady(), { storage: { [PICK]: "claude" } });
    h(page, "first-ceo-name").value = "  "; h(page, "first-ceo-name").dispatch("input");
    await click(h(page, "first-ceo-create"));
    assert.ok(text(h(page, "first-ceo-error")).includes("請幫 CEO 取個名字，不能空白。"));
    assert.deepStrictEqual(posts(page), []);
    h(page, "first-ceo-name").value = "小秘書"; h(page, "first-ceo-name").dispatch("input");
    page.F.createFail = "名字重複了";
    await click(h(page, "first-ceo-create"), 60);
    assert.ok(text(h(page, "first-ceo-error")).includes("沒有建立成功：名字重複了"));
    assert.strictEqual(h(page, "first-ceo-create").disabled, false);
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/agent-profiles"]);
    page.F.createFail = null;
    await click(h(page, "first-ceo-create"), 80);
    assert.strictEqual(page.location.hash, `#/chat/${CHAT}`);
  });

  await test("19b: the CEO is made on the tool the person chose, never another: the plan for another tool is refused with its reason, nothing can be made", async () => {
    const page = await firstPage({ ...chatReady(), plan: () => planOf("codex") }, { storage: { [PICK]: "claude" } });
    assert.strictEqual(h(page, "first-ceo-create"), null);
    assert.ok(h(page, "first-ceo-retry"));
    const bad = await firstPage({ ...chatReady(), plan: () => planOf("claude", { needed: true, can_create: false, tool: null, reason: "你選的 Claude Code 還沒準備好，回開始設定把它準備好，或換一家。" }) }, { storage: { [PICK]: "claude" } });
    assert.ok(text(h(bad, "first-ceo")).includes("你選的 Claude Code 還沒準備好"));
    assert.strictEqual(h(bad, "first-ceo-create"), null);
    assert.deepStrictEqual(posts(bad), []);
  });

  await test("19b: AGY: the line that the conversation goes to Google is on the page (not folded), and so is the mode line; the plan was asked for agy", async () => {
    const page = await firstPage({ tools: [trow("claude"), trow("codex"), readyRow("agy", { version: "3.0.2" }), trow("grok")], support: supportOf({ agy: { state: "ready", version: "3.0.2", why: "", verify: { running: false } } }),
      plan: (t) => planOf(t) }, { storage: { [PICK]: "agy" } });
    assert.deepStrictEqual(gets(page, "/api/first-ceo").map(([, u]) => u), ["/api/first-ceo?tool=agy"]);
    const note = h(page, "first-ceo-agy");
    assert.strictEqual(text(note), evalIn(page, "CEO_AGY_NOTE"));
    assert.ok(text(note).includes("對話內容會送到 Google"));
    assert.ok(!inDetails(note) && !inDetails(h(page, "first-ceo-mode")));
  });

  await test("the typed name, the focus and the daily fold survive a redraw (the 5-second refresh finds a change); with no change nothing is drawn again and only the tools are read", async () => {
    const page = await firstPage(chatReady(), { storage: { [PICK]: "claude" } });
    const name = h(page, "first-ceo-name");
    name.value = "老闆"; name.dispatch("input"); name.focus();
    const fold = one(page.main, "data-setup-slot", "daily-limit");
    fold.open = true;
    // no change: the same nodes, no write, no new read of the chats by the block
    const kids = block(page).children.slice();
    const chatsBefore = gets(page, "/api/chats").length;
    await page.advance(5000); await page.tickHome();
    assert.deepStrictEqual(block(page).children, kids, "nothing was drawn again");
    assert.strictEqual(gets(page, "/api/chats").length, chatsBefore, "the block does not read the chats");
    assert.ok(gets(page, "/api/setup/tools").some(([, u]) => !u.includes("force")), "the tools are read quietly");
    // a change elsewhere: drawn again, the same boxes are put back
    page.F.tools = [readyRow("claude", { version: WARM }), installedRow("codex"), trow("agy"), trow("grok")];
    await page.advance(5000); await page.tickHome();
    assert.notDeepStrictEqual(block(page).children, kids, "it was drawn again");
    assert.strictEqual(h(page, "first-ceo-name"), name, "the same name box");
    assert.strictEqual(name.value, "老闆");
    assert.strictEqual(page.doc.activeElement, name, "the focus is put back");
    assert.strictEqual(one(page.main, "data-setup-slot", "daily-limit"), fold);
    assert.strictEqual(fold.open, true);
    assert.deepStrictEqual(posts(page), []);
  });

  await test("the daily limit is a fold at the bottom (closed) with the start-up page's own words and editor; unread says 未知; the link to the start-up page is the last line", async () => {
    const page = await firstPage();
    const fold = one(page.main, "data-setup-slot", "daily-limit");
    assert.ok(fold && fold.tag === "details" && fold.open === false);
    assert.ok(text(all(fold, (n) => n.tag === "summary")[0]).includes("每天最多花 US$3"), text(all(fold, (n) => n.tag === "summary")[0]));
    assert.ok(byData(fold, "data-limit-save", "").length === 1, "the editor of the start-up page");
    const kids = block(page).children;
    assert.strictEqual(kids[kids.length - 1], h(page, "first-setup-link").parentNode, "the link is the last line");
    assert.strictEqual(kids[kids.length - 2], fold, "the fold is above it");
    const unread = await firstPage({ daily: null });
    assert.ok(text(one(unread.main, "data-setup-slot", "daily-limit")).includes("未知"));
    assert.deepStrictEqual(posts(page), []);
  });

  await test("a person who has an employee is not shown the block (the old home); the three old pages are still reachable by their links", async () => {
    const page = boot("#/", world(), {});
    await tick(60);
    assert.strictEqual(block(page), null);
    assert.ok(one(page.main, "data-home", "team"));
  });

  // ---- the guards must catch what they are written to catch (made-up broken runs) -----------------------------------------------------------------
  await test("19a judge: it catches a check before the confirmation, a missing confirmed:true, a verify of a passed version, two verifies, a wrong tool or version, a verify before the try", () => {
    const ok = [["POST", "/api/setup/tools/claude/try", { confirmed: true }], ["POST", "/api/chat-support/verify", { engine: "claude", version: WARM }]];
    const base = { engine: "claude", shown: WARM, passedBefore: false, confirmed: true };
    assert.deepStrictEqual(judge19a(ok, base), []);
    assert.ok(judge19a(ok, { ...base, confirmed: false }).length, "a request before the confirmation");
    assert.ok(judge19a([["POST", "/api/setup/tools/claude/try", {}], ok[1]], base).some((m) => /confirmed/.test(m)));
    assert.ok(judge19a(ok, { ...base, passedBefore: true }).some((m) => /passed/.test(m)));
    assert.ok(judge19a([ok[0], ok[1], ok[1]], base).some((m) => /more than one/.test(m)));
    assert.ok(judge19a([ok[0], ["POST", "/api/chat-support/verify", { engine: "codex", version: WARM }]], base).some((m) => /another tool/.test(m)));
    assert.ok(judge19a([ok[0], ["POST", "/api/chat-support/verify", { engine: "claude", version: "9.9" }]], base).some((m) => /version/.test(m)));
    assert.ok(judge19a([ok[1], ok[0]], base).some((m) => /before the try/.test(m)));
    assert.ok(judge19a([], base).some((m) => /exactly one try/.test(m)));
    assert.ok(judge19a([["POST", "/api/chat-support/verify", { engine: "claude", version: WARM }]], { ...base, confirmed: false }).length, "a verify with no press at all");
  });

  await test("19a judge (source): the real page passes; a home block that asks for the check itself, or a verify outside 「確認，開始」, is caught", () => {
    assert.deepStrictEqual(judge19aSource(SOURCE), []);
    const mk = (home, kit) => `function homeFirstRun(env) {${home}}\n// ---- end of the first run on the home page ----\nfunction setupKit(ctx) { ${kit} }\n// ---------- end of the setup kit`;
    const good = `const checkOn = { confirm: async (id) => { await api.post("/api/chat-support/verify", {}); }, };\n  return { toolCard };`;
    assert.deepStrictEqual(judge19aSource(mk("", good)), []);
    assert.ok(judge19aSource(mk("api.post('/api/chat-support/verify', {});", good)).some((m) => /home block/.test(m)));
    assert.ok(judge19aSource(mk("api.post(`/api/setup/tools/${x}/try`, {});", good)).some((m) => /home block/.test(m)));
    assert.ok(judge19aSource(mk("", `const checkOn = { ask: async () => { await api.post("/api/chat-support/verify", {}); }, confirm: async (id) => { await api.post("/api/chat-support/verify", {}); }, };\n  return { toolCard };`)).some((m) => /outside/.test(m)));
    assert.ok(judge19aSource(mk("", `const checkOn = { confirm: async (id) => { }, };\n  return { toolCard };`)).some((m) => /does not ask/.test(m)));
    assert.ok(judge19aSource("nothing").length);
  });

  await test("P52-5 gate: a person who has not finished the start-up, with no ready tool, is not sent away: the home page stays and draws the first run (only the existing settle is asked); nothing writes setup_done on load, pick or redraw", async () => {
    const page = await firstPage({}, { config: { setup_done: false }, storage: { [PICK]: "claude" } });
    assert.strictEqual(page.location.hash, "#/");
    assert.ok(block(page), "the first-run block is drawn");
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/settle"], "the settle of the gate is the only write, and it is the old one");
    await page.advance(5000); await page.tickHome();
    assert.deepStrictEqual(judge19b(page.log, { pressed: false, tool: "claude", wasDone: false }), []);
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/settle"]);
  });

  await test("P52-5 gate: a person who had not finished but has a ready tool is counted as done by the server as before (settle says so) and stays on the home page", async () => {
    const page = await firstPage({}, { config: { setup_done: false }, posts: { "POST /api/setup/settle": { body: { ok: true, setup_done: true, setup_notice: false } } } });
    assert.strictEqual(page.location.hash, "#/");
    assert.ok(block(page));
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/settle"]);
  });

  await test("P52-5 gate: a person with employees whose setup_done is not true (older data) is not sent away either, and does not see the first run", async () => {
    const W = world({ config: { setup_done: false } });
    const page = await home(W);
    assert.strictEqual(page.location.hash, "#/");
    assert.strictEqual(block(page), null);
    assert.ok(one(page.main, "data-home", "team"), "the home page of a person with a team is drawn");
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/settle"]);
  });

  await test("P52-5 setup_done: after 「建立 CEO，開始聊」 has made the CEO, a setup_done that was not true is written once with the start-up page's own request ({setup_done: true}); before the press nothing is written", async () => {
    const page = await firstPage(chatReady(), { config: { setup_done: false }, storage: { [PICK]: "claude" } });
    assert.deepStrictEqual(posts(page).map((c) => c[1]), ["/api/setup/settle"], "loading and choosing wrote nothing");
    await click(h(page, "first-ceo-create"), 80);
    assert.deepStrictEqual(posts(page).map((c) => [c[1], c[2] && Object.keys(c[2]).join()]), [["/api/setup/settle", ""], ["/api/agent-profiles", "name,position,instructions,launch_mode,model"],
      ["/api/config", "first_ceo_id"], ["/api/config", "setup_done"], ["/api/chats", "profile_id"]]);
    assert.deepStrictEqual(posts(page)[3][2], { setup_done: true });
    assert.strictEqual(page.location.hash, `#/chat/${CHAT}`);
    assert.deepStrictEqual(judge19b(page.log, { pressed: true, tool: "claude", wasDone: false }), []);
  });

  await test("P52-5 setup_done: a person who had finished the start-up is not written to again; a write that fails does not keep the person out of the conversation", async () => {
    const done = await firstPage(chatReady(), { config: { setup_done: true }, storage: { [PICK]: "claude" } });
    await click(h(done, "first-ceo-create"), 80);
    assert.deepStrictEqual(judge19b(done.log, { pressed: true, tool: "claude", wasDone: true }), []);
    const fail = await firstPage(chatReady(), { config: { setup_done: false }, storage: { [PICK]: "claude" } });
    fail.W.posts["POST /api/config"] = (b) => (b && b.setup_done ? { status: 500, body: { error: "寫不進去" } } : {});
    await click(h(fail, "first-ceo-create"), 80);
    assert.strictEqual(fail.location.hash, `#/chat/${CHAT}`, "into the conversation all the same");
    assert.ok(posts(fail).some((c) => c[1] === "/api/config" && c[2] && c[2].setup_done === true), "it was tried");
  });

  await test("P52-5 setup_done: a CEO the server refuses writes no setup_done (it follows the made card, not the press)", async () => {
    const page = await firstPage(chatReady({ createFail: "名字重複了" }), { config: { setup_done: false }, storage: { [PICK]: "claude" } });
    await click(h(page, "first-ceo-create"), 60);
    assert.ok(!posts(page).some((c) => c[1] === "/api/config" && c[2] && c[2].setup_done === true));
    assert.deepStrictEqual(judge19b(page.log.filter((c) => c[1] !== "/api/agent-profiles"), { pressed: false, tool: "claude" }), []);
  });

  await test("P52-5 judge: the 19b judge catches a setup_done written on load, twice, with something else, before the CEO, without a CEO, though already true, or not written when it was not true", () => {
    const made = ["POST", "/api/agent-profiles", { name: "CEO", position: "planner", launch_mode: "safe", model: { tool: "claude", model_id: "" } }];
    const done = (b = { setup_done: true }) => ["POST", "/api/config", b];
    assert.deepStrictEqual(judge19b([made, done()], { pressed: true, tool: "claude", wasDone: false }), []);
    assert.deepStrictEqual(judge19b([made], { pressed: true, tool: "claude", wasDone: true }), []);
    assert.ok(judge19b([done()], { pressed: false, tool: "claude" }).some((m) => /without the press/.test(m)), "on load");
    assert.ok(judge19b([made, done(), done()], { pressed: true, tool: "claude", wasDone: false }).some((m) => /more than once/.test(m)));
    assert.ok(judge19b([made, done({ setup_done: true, welcome_seen: true })], { pressed: true, tool: "claude", wasDone: false }).some((m) => /something else/.test(m)));
    assert.ok(judge19b([done(), made], { pressed: true, tool: "claude", wasDone: false }).some((m) => /before the CEO/.test(m)));
    assert.ok(judge19b([done()], { pressed: true, tool: "claude", wasDone: false }).some((m) => /no CEO was made/.test(m)));
    assert.ok(judge19b([made, done()], { pressed: true, tool: "claude", wasDone: true }).some((m) => /already true/.test(m)));
    assert.ok(judge19b([made], { pressed: true, tool: "claude", wasDone: false }).some((m) => /not written once/.test(m)));
  });

  await test("P52-5 judge (source): the real page writes setup_done only inside the press's click; a source that writes it when the block is built is caught", () => {
    assert.deepStrictEqual(judge19bSource(SOURCE), []);
    assert.ok(SOURCE.slice(SOURCE.indexOf("function homeFirstRun("), SOURCE.indexOf("// ---- end of the first run on the home page")).includes("setup_done"), "the home block does write it, in its click");
    const click = `a.addEventListener("click", async () => { await ceoCreate(plan, n, i); });\n`;
    const shell = (inside) => `async function ceoCreate(plan, name, instructions) { await api.post("/api/agent-profiles", {}); }\nfunction homeFirstRun(env) {${inside}${click}${click}}\n// ---- end of the first run on the home page ----\nasync function viewCeo() {}`;
    assert.deepStrictEqual(judge19bSource(shell("")), []);
    assert.ok(judge19bSource(shell("api.post('/api/config', { setup_done: true });")).some((m) => /outside the click/.test(m)));
  });

  await test("19b judge: it catches a card made without the press, two cards, a card not in safe mode, a card on another tool, a wrong position and a message sent", () => {
    const made = (over = {}) => ["POST", "/api/agent-profiles", { name: "CEO", position: "planner", launch_mode: "safe", model: { tool: "claude", model_id: "" }, ...over }];
    assert.deepStrictEqual(judge19b([made()], { pressed: true, tool: "claude" }), []);
    assert.deepStrictEqual(judge19b([], { pressed: false, tool: "claude" }), []);
    assert.ok(judge19b([made()], { pressed: false, tool: "claude" }).some((m) => /without the press/.test(m)));
    assert.ok(judge19b([made(), made()], { pressed: true, tool: "claude" }).some((m) => /exactly one/.test(m)));
    assert.ok(judge19b([], { pressed: true, tool: "claude" }).some((m) => /exactly one/.test(m)));
    assert.ok(judge19b([made({ launch_mode: "full" })], { pressed: true, tool: "claude" }).some((m) => /safe mode/.test(m)));
    assert.ok(judge19b([made({ model: { tool: "codex", model_id: "" } })], { pressed: true, tool: "claude" }).some((m) => /another tool/.test(m)));
    assert.ok(judge19b([made({ position: "executor" })], { pressed: true, tool: "claude" }).some((m) => /position/.test(m)));
    assert.ok(judge19b([made(), ["POST", "/api/chats/c1/messages", { text: "hi" }]], { pressed: true, tool: "claude" }).some((m) => /message/.test(m)));
  });

  await test("19b judge (source): the real page passes; a third caller, or a call outside a click handler, or a second place that makes the card, is caught", () => {
    assert.deepStrictEqual(judge19bSource(SOURCE), []);
    const click = (extra = "") => `a.addEventListener("click", async () => { await ceoCreate(plan, n, i); ${extra} });\n`;
    const mk = (body) => `async function ceoCreate(plan, name, instructions) { await api.post("/api/agent-profiles", {}); }\n${body}async function viewCeo() {}`;
    assert.deepStrictEqual(judge19bSource(mk(click() + click())), []);
    assert.ok(judge19bSource(mk(click() + click() + click())).some((m) => /not twice/.test(m)));
    assert.ok(judge19bSource(mk(click())).some((m) => /not twice/.test(m)));
    assert.ok(judge19bSource(mk(click() + "x".repeat(800) + "\nconst auto = () => ceoCreate(plan, n, i);\n")).some((m) => /not inside a click/.test(m)));
    assert.ok(judge19bSource(`async function ceoCreate() {}\n${click() + click()}async function viewCeo() { await api.post("/api/agent-profiles", {}); }`).some((m) => /not made in ceoCreate/.test(m)));
  });

  await test("source: the home block is built with el(), has no innerHTML, no emoji, no outside resource and runs no AI tool; its style is its own part at the end of the style sheet", () => {
    const start = SOURCE.indexOf("// ---- the first run on the home page (v0.25, P52-1");
    const end = SOURCE.indexOf("// ---- end of the first run on the home page");
    assert.ok(start > 0 && end > start, "the part has its own marked place");
    const part = SOURCE.slice(start, end);
    assert.ok(part.length > 3000);
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(part));
    assert.ok(!/\p{Extended_Pictographic}/u.test(part));
    assert.ok(!/https?:\/\//.test(part));
    assert.ok(!/localStorage\.setItem/.test(part), "only setupPickWrite writes to the browser");
    const css = CSS.slice(CSS.indexOf("/* P52-1"));
    assert.ok(css.length < CSS.length && css.length > 200, "P52-1 has its own part at the end of the style sheet");
    assert.ok(!/url\(|@import|https?:\/\//.test(css));
    assert.ok(!/#[0-9a-fA-F]{3,6}\b/.test(css), "colours come from the theme variables");
    assert.ok(!SOURCE.includes("function homeFirstSteps(") && !SOURCE.includes("homeToolStep"), "the old three steps are gone (nobody calls them)");
    assert.ok(!/\.home-step\b/.test(CSS), "and so is their style");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
})();
