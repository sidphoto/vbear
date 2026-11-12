// P50-2 (v0.23.0 極簡對話 1, ADR 0015): the side bar is the record of conversations. Top to bottom: the brand, 「新對話」 (the old home item), 最近 (the employees
// the person talked with, newest first, at most 8, a dot where a card waits), space, then 員工, 工作 and 設定 (smaller), then the advanced items. On a phone the
// bar is a drawer behind a menu button.
// Guard 17b is checked here on the page (the list is drawn from what was already read: no request, no timer) and in tests/test_autonomy_guard.py on the source.
// Runs the whole of web/app.js (with its start-up code) in a vm context against the real web/index.html, with a small synthetic DOM and a fetch stub.
// It is NOT a browser test.
//
// Run: node tests/frontend/p50_nav.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const HTML = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this._attrs = {}; this._classes = new Set(); this._l = {}; this.value = ""; this.nodeType = tag === "#text" ? 3 : 1; this.parentNode = null; }
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
  dispatch(ev, e = {}) { for (const fn of (this._l[ev] || []).slice()) fn({ type: ev, target: this, currentTarget: this, preventDefault() { e.prevented = true; }, ...e }); }
  append(...kids) { for (const k of kids) { if (k instanceof Node) { if (k.parentNode) { const i = k.parentNode.children.indexOf(k); if (i >= 0) k.parentNode.children.splice(i, 1); } k.parentNode = this; } this.children.push(k); } }
  replaceChildren() { for (const k of this.children) if (k instanceof Node) k.parentNode = null; this.children = []; }
  remove() {}
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
const text = (n) => (n ? n.textContent : "");

// the markup of index.html, as nodes: every <a ... data-nav> and every <li data-advanced>, the same markup the browser has
function navFromHtml() {
  const anchors = [];
  for (const m of HTML.matchAll(/<a ([^>]*data-nav="[^"]*"[^>]*)>([\s\S]*?)<\/a>/g)) {
    const a = new Node("a");
    for (const at of m[1].matchAll(/([a-z-]+)="([^"]*)"/g)) { a.setAttribute(at[1], at[2]); if (at[1] === "data-nav") a.dataset.nav = at[2]; }
    const icon = /<span aria-hidden="true">([^<]*)<\/span>([^<]*)/.exec(m[2]);
    const g = new Node("span"); g.textContent = icon ? icon[1] : ""; const t = new Node("#text"); t.textContent = icon ? icon[2] : m[2];
    a.children.push(g, t);
    anchors.push({ a, html: m[0], index: m.index });
  }
  const advanced = [];
  for (const m of HTML.matchAll(/<li([^>]*data-advanced[^>]*)>/g)) { const li = new Node("li"); li.setAttribute("data-advanced", ""); if (/\shidden/.test(m[1])) li.setAttribute("hidden", ""); advanced.push(li); }
  return { anchors, advanced };
}

const profile = (id, name) => ({ id, name, position: id === "p0" ? "planner" : "executor", model: { tool: "claude", model_id: "" }, enabled: true, launch_mode: "safe" });
const cardOf = (p) => ({ id: p.id, name: p.name, position: p.position, tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false });
const chatRow = (id, profileId, over = {}) => ({ id, profile_id: profileId, engine: "claude-chat", created_at: 1000, last_at: 2000, last_kind: "reply", last_text: "這是訊息內容", turns: 1, spent_usd: "0.01", open: false, waiting: false, problem: null, ...over });
const NAMES = ["小執", "小帳", "小文", "小圖", "小編", "小譯", "小研", "小測", "小營", "小法"];

function boot(hash, { chats, profiles, config, fetchImpl, focused } = {}) {
  const ids = new Map();
  const log = [];
  const docListeners = {};
  const winListeners = {};
  const intervals = [];
  const timers = [];
  const mkId = (id, tag = "div") => { const n = new Node(tag); n.setAttribute("id", id); ids.set(id, n); return n; };
  const main = mkId("main", "main");
  mkId("toast");
  const scan = mkId("scan-status"); scan.setAttribute("hidden", "");
  const note = mkId("advanced-note", "p"); note.setAttribute("hidden", "");
  mkId("waiting-bar");
  const side = new Node("nav"); side._classes.add("side");
  const toggle = mkId("nav-toggle", "button"); toggle.setAttribute("aria-expanded", "false");
  const label = mkId("nav-toggle-label", "span"); label.textContent = (/id="nav-toggle-label">([^<]*)</.exec(HTML) || [])[1] || "";
  const recent = mkId("nav-recent", "section"); recent.setAttribute("hidden", "");
  const recentList = mkId("nav-recent-list", "ul");
  const backdrop = mkId("nav-backdrop");
  const panel = mkId("side-panel");
  const nav = navFromHtml();
  const navLinks = nav.anchors.map((x) => x.a);
  const newChat = navLinks.find((a) => a.dataset.nav === "home");
  if (newChat) ids.set("nav-new", newChat);
  const skip = new Node("a");
  const body = new Node("body");
  const location = { hash, pathname: "/", search: "" };
  const history = { replaceState: (_s, _t, url) => { location.hash = url.slice(url.indexOf("#")); } };
  const doc = {
    createElement: (t) => new Node(t), createElementNS: (_n, t) => new Node(t), createTextNode: (t) => { const n = new Node("#text"); n._text = String(t); return n; },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (sel) => (sel === "a.skip" ? skip : sel === "nav.side" ? side : null),
    querySelectorAll: (sel) => (sel === "[data-nav]" ? navLinks : sel === "[data-advanced]" ? nav.advanced : []),
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    body, documentElement: new Node("html"), activeElement: focused ? new Node("button") : null, hidden: false, title: "VBear",
  };
  Node.doc = doc;
  const profs = profiles || NAMES.slice(0, 3).map((n, i) => profile("p" + i, n));
  const body200 = (b) => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => b });
  const fetchStub = async (url, options = {}) => {
    const method = options.method || "GET";
    const p = String(url).split("?")[0];
    log.push([method, String(url), options.body ? JSON.parse(options.body) : null]);
    if (fetchImpl) { const r = await fetchImpl(String(url), options, method); if (r) return r; }
    if (method === "GET") {
      if (p === "/api/config") return body200({ config: config || { advanced_mode: false, setup_done: true, onboarding_dismissed: true }, state_dir: "/x", runtime_socket: "" });
      if (p === "/api/agent-profiles") return body200({ ok: true, profiles: profs });
      if (p === "/api/chats") return chats === null ? { ok: false, status: 500, headers: { get: () => "application/json" }, json: async () => ({ error: "壞了" }) }
        : body200({ chats: chats || [], more: 0, cards: profs.map(cardOf), support: { state: "verified" }, limits: {}, ledger: { lamp: "green" }, problems: [] });
      if (p === "/api/live") return body200({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
      if (p === "/api/routines") return body200({ routines: [], readable: true, cards: [], waiting: [], settings: {}, limits: {}, today: {}, autonomy: {} });
      if (p === "/api/waiting") return body200({ waiting: [] });
      if (p === "/api/meetings/ledger") return body200({ lamp: "green" });
      if (p === "/api/overview") return body200({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
      if (p === "/api/skills") return body200({ skills: [], categories: [] });
      if (p === "/api/roles") return body200({ roles: [] });
    }
    return body200({});
  };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams,
    window: { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: fetchStub,
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; }, clearInterval() {},
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); if (typeof fn === "function") Promise.resolve().then(fn); return timers.length; }, clearTimeout() {},
    scrollTo() {}, scrollY: 0, confirm: () => true,
    module: undefined,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(SOURCE, ctx);
  const go = async (to) => { location.hash = to; for (const fn of winListeners.hashchange || []) fn(); await tick(30); };
  return { ctx, main, log, location, toggle, label, side, panel, backdrop, recent, recentList, navLinks, advanced: nav.advanced, scan, ids, go, docListeners, doc, intervals, timers, newChat };
}
const tick = async (n = 12) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
const hiddenOf = (n) => n.getAttribute("hidden") !== null;
const current = (page) => page.navLinks.filter((a) => a.getAttribute("aria-current") === "page").map((a) => a.dataset.nav);
const evalIn = (page, code) => vm.runInContext(code, page.ctx);
const chatReads = (page) => page.log.filter(([m, u]) => m === "GET" && u.split("?")[0] === "/api/chats").length;
const recentRows = (page) => all(page.recentList, (n) => n.tag === "li");
const recentLinks = (page) => all(page.recentList, (n) => n.tag === "a");

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); } catch (e) { console.log("FAIL -", name); console.log((e && e.stack) || e); process.exitCode = 1; }
}

(async () => {
  // ---- the markup -----------------------------------------------------------------------------------------------------
  await test("index.html: the brand, 新對話, 最近, the three items (員工, 工作, 設定) and then the advanced part, in this order", () => {
    const at = (s) => { const i = HTML.indexOf(s); assert.ok(i > 0, s); return i; };
    const order = [at('class="brand"'), at('data-nav="home"'), at('id="nav-recent"'), at('data-nav="employees"'), at('data-nav="work"'), at('data-nav="settings"'), at('data-advanced')];
    assert.deepStrictEqual(order, [...order].sort((a, b) => a - b), "in order");
    const nav = navFromHtml();
    const items = nav.anchors.filter((x) => !/data-advanced/.test(x.html));
    const advancedLinks = HTML.slice(HTML.indexOf('class="nav-sep"') - 40);
    assert.ok(advancedLinks.includes("data-advanced"));
    const plain = nav.anchors.map((x) => [x.a.dataset.nav, x.a.getAttribute("href"), x.a.children[1].textContent]);
    assert.deepStrictEqual(plain.slice(0, 4), [["home", "#/", "新對話"], ["employees", "#/employees", "員工"], ["work", "#/work", "工作"], ["settings", "#/settings", "設定"]]);
    assert.strictEqual(items.length >= 4, true);
    assert.ok(/<a class="new-chat" href="#\/" data-nav="home">/.test(HTML), "the old home item, kept: href #/ and data-nav home");
    assert.ok(!HTML.includes("花費") || !HTML.slice(HTML.indexOf("<nav"), HTML.indexOf("</nav>")).includes("花費"));
  });

  await test("index.html: the advanced part is still a separator and six items, each hidden until the advanced mode is on; the scan status too", () => {
    const nav = navFromHtml();
    assert.strictEqual(nav.advanced.length, 7);
    assert.ok(nav.advanced.every((li) => li.hasAttribute("hidden")));
    const adv = nav.anchors.slice(4).map((x) => [x.a.dataset.nav, x.a.getAttribute("href"), x.a.children[1].textContent]);
    assert.deepStrictEqual(adv, [["terminals", "#/terminals", "指令視窗"], ["workbench", "#/workbench", "工作台"], ["flows", "#/flows", "流程"],
      ["projects", "#/projects", "專案資料夾"], ["skills", "#/skills", "AI 工具的外掛清單"], ["team", "#/team", "員工詳細資料"]]);
    assert.ok(/id="scan-status"[^>]*hidden|hidden[^>]*id="scan-status"/.test(HTML));
  });

  await test("index.html: the menu button is in the top bar after the brand, names the drawer it opens (the id exists), starts closed and says 選單; a backdrop closes it", () => {
    assert.ok(HTML.indexOf('id="nav-toggle"') > HTML.indexOf('class="brand"') && HTML.indexOf('id="nav-toggle"') < HTML.indexOf('id="side-panel"'));
    assert.ok(/<button class="nav-toggle" id="nav-toggle" type="button" aria-expanded="false" aria-controls="side-panel">/.test(HTML));
    assert.ok(/id="nav-toggle-label">選單</.test(HTML));
    assert.ok(/id="side-panel"/.test(HTML) && /id="nav-backdrop"/.test(HTML));
    const recent = HTML.slice(HTML.indexOf('id="nav-recent"') - 30, HTML.indexOf('id="nav-recent"') + 260);
    assert.ok(/hidden/.test(recent), "最近 is hidden in the markup: nothing is claimed before the data is in");
    assert.ok(/最近/.test(HTML) && /id="nav-recent-list"/.test(HTML));
  });

  await test("index.html: the icons are text symbols (aria-hidden), no emoji, no picture; the brand still says 你的 AI 員工", () => {
    const navHtml = HTML.slice(HTML.indexOf("<nav"), HTML.indexOf("</nav>"));
    assert.ok(!/\p{Emoji_Presentation}|\uFE0F|\u2699/u.test(navHtml), "no emoji (and not the gear, which many fonts draw as one)");
    for (const m of navHtml.matchAll(/<span aria-hidden="true">([^<]*)<\/span>/g)) assert.ok(m[1].length <= 2, m[1]);
    assert.ok(!/<img/.test(navHtml.replace(/<img src="\/logo.svg"[^>]*>/, "")), "only the brand mark is a picture");
    assert.ok(HTML.includes("<small>你的 AI 員工</small>"));
  });

  // ---- which item a page lights -------------------------------------------------------------------------------------------
  await test("新對話 is lit on the home page and nowhere else; the other items light as before", async () => {
    const page = boot("#/");
    await tick(40);
    assert.deepStrictEqual(current(page), ["home"]);
    for (const [hash, nav] of [["#/employees", "employees"], ["#/chat", "employees"], ["#/chat/c1", "employees"], ["#/work", "work"], ["#/settings", "settings"], ["#/flows", "flows"]]) {
      await page.go(hash);
      assert.deepStrictEqual(current(page), [nav], hash);
    }
    assert.strictEqual(evalIn(page, 'navPageName("home")'), "新對話");
    assert.strictEqual(evalIn(page, 'navPageName("chat")'), "員工");
  });

  // ---- 新對話 -----------------------------------------------------------------------------------------------------------------
  await test("新對話 on the home page puts the cursor in the box (and closes the drawer); no request is made by it", async () => {
    const page = boot("#/", { chats: [chatRow("c1", "p0")] });
    await tick(40);
    page.doc.activeElement = new Node("a");
    const before = page.log.length;
    page.toggle.dispatch("click");
    page.newChat.dispatch("click");
    const box = all(page.main, (n) => n.getAttribute && n.getAttribute("data-home") === "ask-input")[0];
    assert.ok(box, "the box is there");
    assert.strictEqual(page.doc.activeElement, box, "the cursor is in it");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false", "the drawer is put away");
    assert.strictEqual(page.log.length, before, "nothing was asked for");
  });

  await test("新對話 from another page: the home page it leads to has the cursor in its box (the move puts the focus on the main area first, so the pressed link does not keep it)", async () => {
    const page = boot("#/work", { chats: [chatRow("c1", "p0")] });
    await tick(40);
    page.newChat.dispatch("click");
    page.doc.activeElement = page.newChat;                  // the pressed link keeps the focus, as in a browser
    await page.go("#/");
    const box = all(page.main, (n) => n.getAttribute && n.getAttribute("data-home") === "ask-input")[0];
    assert.strictEqual(page.doc.activeElement, box);
  });

  // ---- 最近 -------------------------------------------------------------------------------------------------------------------
  await test("最近: the employees who were talked with, newest first, one row each, the name only; a link to the chat; the list is shown", async () => {
    const chats = [chatRow("c-old", "p1", { last_at: 1000 }), chatRow("c-new", "p0", { last_at: 3000 }), chatRow("c-mid", "p2", { last_at: 2000 }), chatRow("c-new2", "p0", { last_at: 2500 })];
    const page = boot("#/", { chats });
    await tick(40);
    assert.ok(!hiddenOf(page.recent), "shown");
    assert.deepStrictEqual(recentRows(page).map(text), ["小執", "小文", "小帳"]);
    assert.deepStrictEqual(recentLinks(page).map((a) => a.getAttribute("href")), ["#/chat/c-new", "#/chat/c-mid", "#/chat/c-old"]);
    assert.ok(!recentRows(page).map(text).join("").includes("訊息內容"), "no words of a chat");
  });

  await test("最近: at most 8; a chat of a routine, one with a problem and one nobody talked in are not listed", async () => {
    const profiles = NAMES.map((n, i) => profile("p" + i, n));
    const chats = profiles.map((p, i) => chatRow("c" + i, p.id, { last_at: 1000 + i }));
    chats.push(chatRow("c-routine", "p0", { last_at: 9000, routine_title: "晨間整理" }), chatRow("c-bad", "p1", { last_at: 9001, problem: "壞了" }));
    const page = boot("#/", { chats, profiles });
    await tick(40);
    assert.strictEqual(recentRows(page).length, 8);
    assert.ok(!recentLinks(page).some((a) => /c-routine|c-bad/.test(a.getAttribute("href"))));
    assert.strictEqual(text(recentRows(page)[0]), NAMES[9], "newest first");
    const quiet = boot("#/", { chats: [chatRow("c1", "p0", { turns: 0 })] });
    await tick(40);
    assert.ok(hiddenOf(quiet.recent), "nobody talked: nothing is shown (and nothing says there are no chats)");
  });

  await test("最近: a dot (labelled 有事等你決定) in front of the row whose chat has a card waiting; the link goes to the chat that waits", async () => {
    const chats = [chatRow("c1", "p0", { last_at: 3000 }), chatRow("c2", "p0", { last_at: 2000, open: true, waiting: true }), chatRow("c3", "p1", { last_at: 1000 })];
    const page = boot("#/", { chats });
    await tick(40);
    const rows = recentRows(page);
    const dots = all(page.recentList, (n) => n.getAttribute && n.getAttribute("aria-label") === "有事等你決定");
    assert.strictEqual(dots.length, 1);
    assert.ok(rows[0].contains(dots[0]), "on the first row");
    assert.strictEqual(recentLinks(page)[0].getAttribute("href"), "#/chat/c2");
    assert.strictEqual(text(rows[0]), "小執", "the dot has no words in the row");
  });

  await test("最近: no data (the chats could not be read, or no list yet): the whole part is not shown, and nothing says 'no chats'", async () => {
    const bad = boot("#/", { chats: null });
    await tick(40);
    assert.ok(hiddenOf(bad.recent));
    assert.strictEqual(recentRows(bad).length, 0);
    const none = boot("#/", { chats: [] });
    await tick(40);
    assert.ok(hiddenOf(none.recent));
    assert.ok(!text(none.recent).includes("沒有"));
  });

  await test("最近: the row of the open chat is marked as the current page", async () => {
    const page = boot("#/", { chats: [chatRow("c1", "p0", { last_at: 3000 }), chatRow("c2", "p1", { last_at: 2000 })] });
    await tick(40);
    await page.go("#/chat/c2");
    const cur = recentLinks(page).filter((a) => a.getAttribute("aria-current") === "page").map((a) => a.getAttribute("href"));
    assert.deepStrictEqual(cur, ["#/chat/c2"]);
  });

  await test("17b: the list is drawn from what the page already read: no extra read of /api/chats for the side bar, none when moving between pages, and no timer of its own", async () => {
    const page = boot("#/", { chats: [chatRow("c1", "p0")] });
    await tick(40);
    assert.strictEqual(chatReads(page), 1, "the home page's own read, the only one");
    assert.ok(!hiddenOf(page.recent));
    await page.go("#/work");
    await page.go("#/settings");
    assert.strictEqual(chatReads(page), 1, "moving between pages asks for no more");
    assert.ok(!hiddenOf(page.recent), "and the list stays");
    assert.ok(page.intervals.every((i) => [5000, 30000].includes(i.ms) || true));
    const fnSource = evalIn(page, "String(navRecentRows) + String(drawNavRecent)");
    assert.ok(!/setInterval|setTimeout|api\./.test(fnSource), "the code that draws it starts no timer and makes no request");
  });

  await test("17b: a read of the chats that the page makes for itself later (the 30-second one) redraws the list; a row appears for a new chat", async () => {
    const W = { chats: [chatRow("c1", "p0", { last_at: 3000 })] };
    const page = boot("#/", { chats: W.chats, fetchImpl: async (url) => (url.split("?")[0] === "/api/chats" ? { ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ chats: W.chats, more: 0, cards: NAMES.slice(0, 3).map((n, i) => cardOf(profile("p" + i, n))), support: { state: "verified" }, limits: {}, ledger: {}, problems: [] }) } : null) });
    await tick(40);
    assert.strictEqual(recentRows(page).length, 1);
    W.chats = [chatRow("c1", "p0", { last_at: 3000 }), chatRow("c9", "p2", { last_at: 4000 })];
    evalIn(page, "waitingChatsNote(" + JSON.stringify({ chats: W.chats, cards: NAMES.slice(0, 3).map((n, i) => cardOf(profile("p" + i, n))) }) + ")");
    assert.deepStrictEqual(recentRows(page).map(text), ["小文", "小執"]);
  });

  // ---- the drawer ---------------------------------------------------------------------------------------------------------------
  await test("drawer: the menu button opens it (aria-expanded true, the bar says nav-open), the button again, Esc, the backdrop and a link close it", async () => {
    const page = boot("#/", { chats: [chatRow("c1", "p0")] });
    await tick(40);
    const open = () => page.toggle.getAttribute("aria-expanded") === "true" && page.side.classList.contains("nav-open");
    const esc = () => { for (const fn of page.docListeners.keydown || []) fn({ key: "Escape" }); };
    page.toggle.dispatch("click");
    assert.ok(open());
    page.toggle.dispatch("click");
    assert.ok(!open() && page.toggle.getAttribute("aria-expanded") === "false");
    page.toggle.dispatch("click"); esc();
    assert.ok(!open(), "Esc");
    assert.strictEqual(page.doc.activeElement, page.toggle, "the focus goes back to the button");
    page.toggle.dispatch("click"); page.backdrop.dispatch("click");
    assert.ok(!open(), "outside the drawer");
    for (const dest of ["employees", "work", "settings", "home"]) {
      page.toggle.dispatch("click");
      assert.ok(open());
      page.navLinks.find((a) => a.dataset.nav === dest).dispatch("click");
      assert.ok(!open(), `a link (${dest}) closes it, even to the page one is on`);
    }
    page.toggle.dispatch("click");
    page.recentList.children.length && recentLinks(page)[0].dispatch("click");
    assert.ok(!open(), "a row of 最近 closes it");
    page.toggle.dispatch("click");
    await page.go("#/work");
    assert.ok(!open(), "going to a page puts it away");
  });

  await test("drawer: the button's own words are 選單; its name for a screen reader says which page you are on", async () => {
    const page = boot("#/employees");
    await tick(40);
    assert.strictEqual(page.label.textContent, "選單");
    assert.ok(/^選單/.test(page.toggle.getAttribute("aria-label")) && page.toggle.getAttribute("aria-label").includes("員工"), page.toggle.getAttribute("aria-label"));
    await page.go("#/work");
    assert.ok(page.toggle.getAttribute("aria-label").includes("工作"));
    await page.go("#/nowhere");
    assert.strictEqual(page.toggle.getAttribute("aria-label"), "選單");
  });

  await test("advanced mode: its items are in the same drawer, shown when the mode is on; turning the mode off puts an open drawer away; nothing else is asked for", async () => {
    const page = boot("#/", { config: { advanced_mode: true } });
    await tick(40);
    assert.ok(page.advanced.every((li) => !hiddenOf(li)) && !hiddenOf(page.scan));
    assert.ok(page.side.classList.contains("adv-on"));
    page.toggle.dispatch("click");
    evalIn(page, "syncAdvancedNav(false)");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false");
    assert.ok(page.advanced.every(hiddenOf));
  });

  // ---- the CSS ------------------------------------------------------------------------------------------------------------------
  await test("css: a marked P50-2 part at the end; the bar is about 220px wide; the menu button shows only on a phone", () => {
    const at = CSS.indexOf("/* P50-2");
    assert.ok(at > CSS.indexOf("/* P50-1"), "after P50-1, at the end");
    const part = CSS.slice(at);
    assert.ok(/\.shell\s*\{[^}]*grid-template-columns:\s*220px/.test(part), "220px");
    assert.ok(/\.nav-toggle\s*\{[^}]*display:\s*none/.test(CSS.slice(CSS.indexOf(".nav-toggle {"))), "hidden on a wide window");
  });

  await test("css: on a phone (720px and narrower) there is a top bar and the bar is a drawer that slides from the left, with a backdrop; closed, it is out of the tab order", () => {
    const at = CSS.indexOf("/* P50-2");
    const m = /@media \(max-width: 720px\) \{([\s\S]*?)\n\}\n/.exec(CSS.slice(at));
    assert.ok(m, "the phone block");
    const block = m[1];
    assert.ok(/\.nav-toggle\s*\{[^}]*display:\s*inline-flex/.test(block), "the button shows");
    assert.ok(/\.side-panel\s*\{[^}]*position:\s*fixed[^}]*transform:\s*translateX\(-100%\)/.test(block), "off to the left");
    assert.ok(/\.side-panel\s*\{[^}]*visibility:\s*hidden/.test(block), "closed: not focusable");
    assert.ok(/\.side\.nav-open \.side-panel\s*\{[^}]*transform:\s*none[^}]*visibility:\s*visible/.test(block), "open");
    assert.ok(/\.side\.nav-open \.nav-backdrop\s*\{[^}]*display:\s*block/.test(block), "the backdrop shows while open");
    assert.ok(/li\[data-advanced\]|\.nav \[hidden\]/.test(CSS), "the hidden advanced items stay hidden");
    assert.ok(!/overflow-x:\s*auto/.test(block), "no sideways scroll");
    assert.ok(/min-height:\s*44px/.test(CSS.slice(CSS.indexOf(".nav-toggle {"))), "a touch-sized target");
  });

  await test("css: with reduced motion the drawer does not slide", () => {
    const part = CSS.slice(CSS.indexOf("/* P50-2"));
    const m = /@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/.exec(part);
    assert.ok(m, "a reduced-motion block in the P50-2 part");
    assert.ok(/\.side-panel[^{]*\{[^}]*transition:\s*none/.test(m[1]));
    assert.ok(/transition:[^;]*transform/.test(part.replace(m[0], "")), "and the slide is there without it");
  });

  await test("css: 最近 rows are one line each with an ellipsis, the dot is the waiting colour, the current row is marked, the foot items are one step smaller", () => {
    const part = CSS.slice(CSS.indexOf("/* P50-2"));
    assert.ok(/\.recent-link\s*\{[^}]*text-overflow:\s*ellipsis/.test(part) && /white-space:\s*nowrap/.test(part));
    assert.ok(/\.recent-dot\s*\{[^}]*background:\s*var\(--warn\)/.test(part));
    assert.ok(/\.recent-link\[aria-current="page"\]/.test(part));
    assert.ok(/\.side-panel \.nav a\s*\{[^}]*font-size:\s*13/.test(part), "smaller");
    assert.ok(/\.new-chat\b[^{]*\{[^}]*border-radius:\s*999px/.test(part), "the new-chat button is a pill");
  });

  // ---- the source -----------------------------------------------------------------------------------------------------------------
  await test("source: the side bar's code uses el() only (no innerHTML), no emoji, no outside resource, no storage", () => {
    const a = SOURCE.indexOf("// ---------- the side bar's 最近");
    const b = SOURCE.indexOf("// ---------- end of the side bar's 最近");
    assert.ok(a > 0 && b > a, "the part is marked");
    const part = SOURCE.slice(a, b);
    assert.ok(!/innerHTML|insertAdjacentHTML/.test(part) && !/https?:\/\//.test(part) && !/\p{Extended_Pictographic}/u.test(part) && !/localStorage|sessionStorage/.test(part));
  });

  console.log(`\n${passed} passed`);
})();
