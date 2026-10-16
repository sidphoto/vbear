// P5 (design card-play 3.9): how the page starts and the phone menu.
//  - #auth=<token>: the login code is traded for the session cookie first, and nothing else talks to the server (the
//    translation poll, a hash change, a tab coming back) or starts the router until that is done. A 401 met while the
//    trade is under way must not put up "open VBear".
//  - the phone menu: the nav folds behind one button that names the page you are on.
// Runs the whole of web/app.js (including its start-up code) in a vm context with a small synthetic DOM and a fetch stub.
// It is NOT a browser test.
//
// Run: node tests/frontend/boot.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const appPath = path.join(__dirname, "..", "..", "web", "app.js");
const source = fs.readFileSync(appPath, "utf8");
const TOKEN = "A".repeat(10) + "b".repeat(10) + "_-" + "9".repeat(6);

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this._attrs = {}; this._classes = new Set(); this._l = {}; this.value = ""; this.nodeType = tag === "#text" ? 3 : 1; }
  get classList() { const s = this; return { add: (...c) => c.forEach((x) => s._classes.add(x)), remove: (...c) => c.forEach((x) => s._classes.delete(x)), contains: (c) => s._classes.has(c),
    toggle(c, force) { const want = force === undefined ? !s._classes.has(c) : force; if (want) s._classes.add(c); else s._classes.delete(c); return want; } }; }
  get className() { return [...this._classes].join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this.tag === "#text" ? (this._text || "") : this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = []; if (this.tag === "#text") this._text = String(v); else if (v !== "") { const t = new Node("#text"); t._text = String(v); this.children.push(t); } }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(ev, fn) { (this._l[ev] = this._l[ev] || []).push(fn); }
  removeEventListener() {}
  dispatch(ev, e = {}) { for (const fn of (this._l[ev] || []).slice()) fn({ type: ev, target: this, preventDefault() {}, ...e }); }
  append(...kids) { for (const k of kids) this.children.push(k); }
  replaceChildren() { this.children = []; }
  remove() {}
  contains(n) { return this === n || this.children.some((c) => c.contains && c.contains(n)); }
  get childNodes() { return this.children; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() { Node.focused = this; }
  scrollIntoView() {}
}
const walk = (n) => n.children.flatMap((c) => [c, ...walk(c)]);

function boot(hash, { fetchImpl } = {}) {
  const ids = new Map();
  const log = [];
  const intervals = [];
  const docListeners = {};
  const winListeners = {};
  const mkId = (id, tag = "div") => { const n = new Node(tag); n.setAttribute("id", id); ids.set(id, n); return n; };
  const main = mkId("main", "main");
  mkId("toast"); mkId("scan-status");
  const side = new Node("nav"); side._classes.add("side");
  const toggle = mkId("nav-toggle", "button"); toggle.setAttribute("aria-expanded", "false");
  const label = mkId("nav-toggle-label", "span"); label.textContent = "選單";
  const navLinks = [["home", "⌂", "冒險者大廳"], ["team", "☰", "角色卡池"], ["flows", "⇄", "流程"]].map(([nav, glyph, name]) => {
    const a = new Node("a"); a.dataset.nav = nav;
    const g = new Node("span"); g.textContent = glyph; const t = new Node("#text"); t.textContent = name;
    a.children.push(g, t);
    return a;
  });
  const skip = new Node("a");
  const body = new Node("body");
  const state = { fetchHidden: false };
  const location = { hash, pathname: "/", search: "" };
  const history = { replaceState: (_s, _t, url) => { log.push(["replaceState", url]); location.hash = url.slice(url.indexOf("#")); } };
  const doc = {
    createElement: (t) => new Node(t), createElementNS: (_n, t) => new Node(t), createTextNode: (t) => { const n = new Node("#text"); n._text = String(t); return n; },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (sel) => (sel === "a.skip" ? skip : sel === "nav.side" ? side : null),
    querySelectorAll: (sel) => (sel === "[data-nav]" ? navLinks : []),
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    body, documentElement: new Node("html"), activeElement: null, hidden: false,
  };
  const pending = [];
  const fetchStub = async (url, options = {}) => {
    const method = options.method || "GET";
    log.push([method, String(url)]);
    if (fetchImpl) { const r = await fetchImpl(String(url), options, method); if (r) return r; }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams,
    window: { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: fetchStub,
    setInterval: (fn, ms) => { intervals.push([fn, ms]); return intervals.length; }, clearInterval() {},
    setTimeout: (fn) => { if (typeof fn === "function") Promise.resolve().then(fn); return 0; }, clearTimeout() {},
    scrollTo() {}, scrollY: 0, confirm: () => true,
    module: undefined,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return { ctx, main, log, intervals, docListeners, winListeners, location, toggle, label, side, navLinks, ids };
}
const tick = async (n = 12) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
const gets = (log, prefix) => log.filter(([m, u]) => m === "GET" && u.startsWith(prefix));
const unauthorized = () => ({ ok: false, status: 401, json: async () => ({ error: "請從 VBear 開啟", code: "auth_required" }) });

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); }
  catch (e) { console.log("FAIL -", name); console.log(e && e.stack || e); process.exitCode = 1; }
}

(async () => {
  await test("#auth=: the code is traded first, the address is cleaned at once, and the router starts only after the trade", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    let authed = false;
    const page = boot(`#auth=${TOKEN}`, { fetchImpl: async (url, o, method) => {
      if (method === "POST" && url === "/api/auth") { await gate; authed = true; return { ok: true, status: 200, json: async () => ({ ok: true }) }; }
      if (!authed) return unauthorized();
      return null;
    } });
    await tick();
    assert.deepStrictEqual(page.log[0], ["replaceState", "/#/"], "the code leaves the address bar before anything else");
    assert.deepStrictEqual(page.log[1], ["POST", "/api/auth"]);
    assert.strictEqual(vm.runInContext("authPending", page.ctx), true, "marked pending");
    assert.strictEqual(page.log.length, 2, "nothing else was asked of the server while the trade is under way");
    // the translation poll fires while the trade is pending: it is held back
    for (const [fn] of page.intervals) await fn();
    // a tab coming back to the front, and a hash change, are held back too
    for (const fn of page.docListeners.visibilitychange || []) fn();
    page.location.hash = "#/team";
    for (const fn of page.winListeners.hashchange || []) fn();
    await tick();
    assert.strictEqual(page.log.length, 2, "still nothing");
    assert.ok(!page.main.textContent.includes("請從 VBear 開啟"), "no 'open VBear' while the page is logging in");
    release();
    await tick(40);
    const postAt = page.log.findIndex(([m, u]) => m === "POST" && u === "/api/auth");
    const firstGet = page.log.findIndex(([m]) => m === "GET");
    assert.ok(firstGet > postAt, "the router's first request comes after the trade");
    assert.ok(!page.main.textContent.includes("請從 VBear 開啟"), "and the page is not the login page");
    assert.ok(gets(page.log, "/api/translations").length === 0 || page.log.findIndex(([, u]) => u === "/api/translations") > postAt);
    // the route that ran is the one in the address now (#/team), not the home page
    assert.ok(page.log.some(([m, u]) => m === "GET" && /agent-profiles|\/api\/live|\/api\/overview/.test(u)));
    assert.strictEqual(vm.runInContext("authPending", page.ctx), false);
  });

  await test("#auth=: a code the server refuses ends the pending state; the first request then shows how to open VBear", async () => {
    const page = boot(`#auth=${TOKEN}`, { fetchImpl: async (url, o, method) => {
      if (method === "POST" && url === "/api/auth") return unauthorized();
      return unauthorized();
    } });
    await tick(40);
    assert.strictEqual(vm.runInContext("authPending", page.ctx), false, "not stuck pending");
    assert.ok(page.main.textContent.includes("請從 VBear 開啟"), "the page says how to get in");
    // and once it has said so, the poll stops asking (the existing behaviour)
    const before = page.log.length;
    for (const [fn] of page.intervals) await fn();
    await tick();
    assert.strictEqual(page.log.length, before);
  });

  await test("#auth=: an address that is not a login code (wrong shape) is not traded and starts the router at once", async () => {
    for (const hash of ["#auth=short", "#auth=" + "x".repeat(201), "#auth=" + TOKEN + "!", "#/team", "", "#auth="]) {
      const page = boot(hash);
      await tick(8);
      assert.ok(!page.log.some(([m, u]) => m === "POST" && u === "/api/auth"), hash);
      assert.ok(page.log.some(([m]) => m === "GET") || page.main.textContent !== "", `${hash}: the router started`);
      assert.strictEqual(vm.runInContext("authPending", page.ctx), false);
    }
  });

  await test("without a pending trade a 401 still puts up the login page (the guard is only for the trade)", async () => {
    const page = boot("#/", { fetchImpl: async () => unauthorized() });
    await tick(40);
    assert.ok(page.main.textContent.includes("請從 VBear 開啟"));
  });

  // ---- the phone menu --------------------------------------------------------------------------------------
  await test("phone menu: the button names the page you are on, and going to a page puts the menu away", async () => {
    const page = boot("#/team");
    await tick(20);
    assert.strictEqual(page.label.textContent, "選單：角色卡池");
    page.toggle.dispatch("click");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "true");
    assert.ok(page.side.classList.contains("nav-open"));
    page.toggle.dispatch("click");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false");
    assert.ok(!page.side.classList.contains("nav-open"));
    // open it, then reach another page: it folds again and the name follows
    page.toggle.dispatch("click");
    page.location.hash = "#/flows";
    for (const fn of page.winListeners.hashchange || []) fn();
    await tick(20);
    assert.strictEqual(page.label.textContent, "選單：流程");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false");
    assert.ok(!page.side.classList.contains("nav-open"));
  });

  await test("phone menu: Escape closes it and gives focus back to the button; Escape while closed does nothing", async () => {
    const page = boot("#/");
    await tick(20);
    const esc = () => { for (const fn of page.docListeners.keydown || []) fn({ key: "Escape" }); };
    page.toggle.dispatch("click");
    Node.focused = null;
    esc();
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false");
    assert.strictEqual(Node.focused, page.toggle);
    Node.focused = null;
    esc();
    assert.strictEqual(Node.focused, null, "nothing to close, nothing to focus");
  });

  await test("phone menu: the page name is the link's own words, not its glyph; an unknown page is just 選單", async () => {
    const page = boot("#/");
    await tick(20);
    assert.strictEqual(vm.runInContext('navPageName("home")', page.ctx), "冒險者大廳");
    assert.strictEqual(vm.runInContext('navPageName("nope")', page.ctx), "");
    vm.runInContext('syncNavMenu("nope")', page.ctx);
    assert.strictEqual(page.label.textContent, "選單");
  });

  await test("phone menu: index.html has the button before the list, wired by id; the CSS folds the list only at 720px and narrower", () => {
    const html = fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8");
    assert.ok(html.indexOf('id="nav-toggle"') > html.indexOf('class="brand"') && html.indexOf('id="nav-toggle"') < html.indexOf('id="nav-list"'));
    assert.ok(/<button class="nav-toggle" id="nav-toggle" type="button" aria-expanded="false" aria-controls="nav-list">/.test(html));
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    assert.ok(/\.nav-toggle\s*\{\s*display:\s*none;/.test(css), "hidden on a wide window");
    const block = css.slice(css.lastIndexOf("@media (max-width: 720px) {\n  .nav-toggle"));
    assert.ok(/\.nav-toggle\s*\{\s*display:\s*inline-flex/.test(block));
    assert.ok(/\.side \.nav\s*\{\s*display:\s*none;\s*\}/.test(block) && /\.side\.nav-open \.nav\s*\{\s*display:\s*grid/.test(block));
    assert.ok(/min-height:\s*44px/.test(css.slice(css.indexOf(".nav-toggle {"))), "a touch-sized target");
    assert.ok(!/overflow-x:\s*auto/.test(block), "the phone menu does not scroll sideways");
  });

  await test("source: the start-up and menu code use no innerHTML and no outside resource", () => {
    const part = source.slice(source.indexOf("// The phone menu"), source.indexOf("let liveTimer = null;")) + source.slice(source.indexOf("async function bootstrap()"));
    assert.ok(!/innerHTML|insertAdjacentHTML/.test(part) && !/https?:\/\//.test(part) && !/\p{Extended_Pictographic}/u.test(part));
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL BOOT FRONTEND TESTS PASSED");
})();
