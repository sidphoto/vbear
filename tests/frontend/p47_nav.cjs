// P47-1 (ADR 0013): the menu of four (首頁、員工、工作、設定), the advanced mode that shows the engineering pages in it, the table that says which
// menu item a page lights, and the old routes that still open. Advanced mode is only a display: the page reads it, shows or hides, and
// never asks for or sends anything else.
// Runs the whole of web/app.js (with its start-up code) in a vm context against the real web/index.html, with a small synthetic DOM
// and a fetch stub. It is NOT a browser test.
//
// Run: node tests/frontend/p47_nav.cjs   (exit code 0 = pass)
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
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this._attrs = {}; this._classes = new Set(); this._l = {}; this.value = ""; this.nodeType = tag === "#text" ? 3 : 1; }
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

// the nav of index.html, as nodes: the same markup the browser has
function navFromHtml() {
  const list = HTML.slice(HTML.indexOf('<ul class="nav" id="nav-list">'), HTML.indexOf("</ul>", HTML.indexOf('<ul class="nav" id="nav-list">')));
  const items = [];
  // P50-2: the home item is 「新對話」, above the list (it is still a [data-nav] link)
  const home = /<a class="new-chat" href="([^"]*)" data-nav="([^"]*)"><span aria-hidden="true">([^<]*)<\/span>([^<]*)<\/a>/.exec(HTML);
  if (home) {
    const anchor = new Node("a"); anchor.setAttribute("href", home[1]); anchor.dataset.nav = home[2]; anchor.setAttribute("data-nav", home[2]);
    const g = new Node("span"); g.textContent = home[3]; const t = new Node("#text"); t.textContent = home[4];
    anchor.children.push(g, t);
    items.push({ li: new Node("li"), anchor, html: home[0] });
  }
  for (const m of list.matchAll(/<li([^>]*)>([\s\S]*?)<\/li>/g)) {
    const li = new Node("li");
    for (const a of m[1].matchAll(/([a-z-]+)(?:="([^"]*)")?/g)) if (a[1]) li.setAttribute(a[1], a[2] === undefined ? "" : a[2]);
    const link = /<a href="([^"]*)" data-nav="([^"]*)"><span aria-hidden="true">([^<]*)<\/span>([^<]*)<\/a>/.exec(m[2]);
    let anchor = null;
    if (link) {
      anchor = new Node("a"); anchor.setAttribute("href", link[1]); anchor.dataset.nav = link[2]; anchor.setAttribute("data-nav", link[2]);
      const g = new Node("span"); g.textContent = link[3]; const t = new Node("#text"); t.textContent = link[4];
      anchor.children.push(g, t); li.children.push(anchor);
    } else li.textContent = m[2].replace(/<[^>]*>/g, "");
    items.push({ li, anchor, html: m[0] });
  }
  return items;
}

function boot(hash, { fetchImpl, config } = {}) {
  const ids = new Map();
  const log = [];
  const docListeners = {};
  const winListeners = {};
  const mkId = (id, tag = "div") => { const n = new Node(tag); n.setAttribute("id", id); ids.set(id, n); return n; };
  const main = mkId("main", "main");
  mkId("toast");
  const scan = mkId("scan-status");
  if (/id="scan-status"[^>]*hidden|hidden[^>]*id="scan-status"/.test(HTML)) scan.setAttribute("hidden", "");
  const note = mkId("advanced-note", "p");
  if (/id="advanced-note"[^>]*hidden/.test(HTML)) note.setAttribute("hidden", "");
  const side = new Node("nav"); side._classes.add("side");
  const toggle = mkId("nav-toggle", "button"); toggle.setAttribute("aria-expanded", "false");
  const label = mkId("nav-toggle-label", "span"); label.textContent = (/id="nav-toggle-label">([^<]*)</.exec(HTML) || [])[1] || "";
  const items = navFromHtml();
  const navLinks = items.filter((i) => i.anchor).map((i) => i.anchor);
  const advanced = items.filter((i) => i.li.hasAttribute("data-advanced")).map((i) => i.li);
  const skip = new Node("a");
  const body = new Node("body");
  const location = { hash, pathname: "/", search: "" };
  const history = { replaceState: (_s, _t, url) => { location.hash = url.slice(url.indexOf("#")); } };
  const doc = {
    createElement: (t) => new Node(t), createElementNS: (_n, t) => new Node(t), createTextNode: (t) => { const n = new Node("#text"); n._text = String(t); return n; },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (sel) => (sel === "a.skip" ? skip : sel === "nav.side" ? side : null),
    querySelectorAll: (sel) => (sel === "[data-nav]" ? navLinks : sel === "[data-advanced]" ? advanced : []),
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    body, documentElement: new Node("html"), activeElement: null, hidden: false,
  };
  const cfg = config === undefined ? { advanced_mode: false } : config;
  const fetchStub = async (url, options = {}) => {
    const method = options.method || "GET";
    log.push([method, String(url), options.body ? JSON.parse(options.body) : null]);
    if (fetchImpl) { const r = await fetchImpl(String(url), options, method); if (r) return r; }
    if (url === "/api/config" && method === "GET") return { ok: true, status: 200, json: async () => ({ config: cfg, state_dir: "/x", runtime_socket: "" }) };
    return { ok: true, status: 200, json: async () => ({}) };
  };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, Node, document: doc, location, history, URLSearchParams,
    window: { addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }, removeEventListener() {}, scrollTo() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: fetchStub,
    setInterval: () => 0, clearInterval() {},
    setTimeout: (fn) => { if (typeof fn === "function") Promise.resolve().then(fn); return 0; }, clearTimeout() {},
    scrollTo() {}, scrollY: 0, confirm: () => true,
    module: undefined,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(SOURCE, ctx);
  const go = async (to) => { location.hash = to; for (const fn of winListeners.hashchange || []) fn(); await tick(30); };
  return { ctx, main, log, location, toggle, label, side, navLinks, advanced, items, scan, note, ids, go, docListeners };
}
const tick = async (n = 12) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
const hiddenOf = (n) => n.getAttribute("hidden") !== null;
const current = (page) => page.navLinks.filter((a) => a.getAttribute("aria-current") === "page").map((a) => a.dataset.nav);
const evalIn = (page, code) => vm.runInContext(code, page.ctx);

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); }
  catch (e) { console.log("FAIL -", name); console.log(e && e.stack || e); process.exitCode = 1; }
}

(async () => {
  // ---- the markup ---------------------------------------------------------------------------------------------------
  await test("index.html: 新對話 and three items (員工, 工作, 設定; P50-2), in this order, with these words; there is no 花費 in the menu", () => {
    const items = navFromHtml().filter((i) => i.anchor && !i.li.hasAttribute("data-advanced"));
    assert.deepStrictEqual(items.map((i) => [i.anchor.dataset.nav, i.anchor.getAttribute("href"), i.anchor.children[1].textContent]),
      [["home", "#/", "新對話"], ["employees", "#/employees", "員工"], ["work", "#/work", "工作"], ["settings", "#/settings", "設定"]]);
    for (const i of items) assert.ok(!i.li.hasAttribute("hidden"), `${i.anchor.dataset.nav} is always shown`);
    const nav = HTML.slice(HTML.indexOf("<nav"), HTML.indexOf("</nav>"));
    assert.ok(!/花費|spending/.test(nav), "no spending item: the limit lives in the settings");
    for (const gone of ["冒險者大廳", "角色卡池", "終端機", "終端工作台", "技能庫", "派工", "例行工作", ">專案<", ">聊天<", "開始設定"]) assert.ok(!nav.includes(gone), `the menu no longer says ${gone}`);
  });

  await test("index.html: the advanced part is a separator and six items, each hidden until the advanced mode is on", () => {
    const all = navFromHtml();
    const adv = all.filter((i) => i.li.hasAttribute("data-advanced"));
    assert.strictEqual(adv.length, 7, "a separator and six items");
    assert.ok(adv.every((i) => i.li.hasAttribute("hidden")), "all hidden in the markup, so nothing flashes");
    assert.ok(!adv[0].anchor && adv[0].li.textContent.includes("進階"), "the separator comes first");
    assert.deepStrictEqual(adv.slice(1).map((i) => [i.anchor.dataset.nav, i.anchor.getAttribute("href"), i.anchor.children[1].textContent]),
      [["terminals", "#/terminals", "指令視窗"], ["workbench", "#/workbench", "工作台"], ["flows", "#/flows", "流程"],
        ["projects", "#/projects", "專案資料夾"], ["skills", "#/skills", "AI 工具的外掛清單"], ["team", "#/team", "員工詳細資料"]]);
    assert.strictEqual(all.indexOf(adv[0]), 4, "after the four");
  });

  await test("index.html: the icons are text symbols with aria-hidden, no emoji; the brand says 你的 AI 員工; the scan status shows only in advanced", () => {
    const nav = HTML.slice(HTML.indexOf("<nav"), HTML.indexOf("</nav>"));
    assert.ok(!/\p{Emoji_Presentation}|\uFE0F/u.test(nav), "no emoji in the menu");
    for (const m of nav.matchAll(/<span aria-hidden="true">([^<]*)<\/span>/g)) assert.ok(m[1].length >= 1 && m[1].length <= 2, m[1]);
    assert.strictEqual((nav.match(/<span aria-hidden="true">/g) || []).length, 10, "ten links, ten hidden icons");
    assert.ok(HTML.includes("<small>你的 AI 員工</small>") && !HTML.includes("技能與團隊主控台"));
    assert.ok(/id="scan-status"[^>]*hidden|hidden[^>]*id="scan-status"/.test(HTML), "hidden until advanced");
    assert.ok(/id="advanced-note"/.test(HTML) && /id="advanced-note"[^>]*hidden/.test(HTML), "the line for an advanced page opened by an address");
    assert.ok(/<button class="nav-toggle" id="nav-toggle" type="button" aria-expanded="false" aria-controls="side-panel">/.test(HTML));
    assert.ok(/id="nav-toggle-label">選單</.test(HTML), "on a phone this button is 選單 (P50-2: it opens the whole bar, not only the advanced list)");
  });

  // ---- which menu item a page lights --------------------------------------------------------------------------------
  await test("NAV_PARENT: the plan's table, page by page", () => {
    const page = boot("#/");
    const t = evalIn(page, "NAV_PARENT");
    const want = {
      home: "home",
      employees: "employees", chat: "employees", ceo: "employees", memory: "employees", shared: "employees", templates: "employees", office: "employees",
      work: "work", dispatch: "work", routines: "work", meetings: "work", actions: "work", "my-skills": "work",
      settings: "settings", setup: "settings", welcome: "settings",
      terminals: "terminals", term: "terminals", workbench: "workbench", flows: "flows", projects: "projects", skills: "skills", armory: "skills", team: "team", staffing: "team",
    };
    assert.deepStrictEqual(Object.fromEntries(Object.entries(t)), want);
    // every parent is an item of the menu
    const navs = new Set(page.navLinks.map((a) => a.dataset.nav));
    for (const v of Object.values(want)) assert.ok(navs.has(v), v);
  });

  await test("a page lights exactly its menu item (aria-current), the old routes included", async () => {
    const page = boot("#/");
    await tick(30);
    assert.deepStrictEqual(current(page), ["home"]);
    for (const [hash, nav] of [["#/employees", "employees"], ["#/chat", "employees"], ["#/chat/group/g1", "employees"], ["#/ceo", "employees"], ["#/memory", "employees"],
      ["#/shared", "employees"], ["#/templates", "employees"], ["#/office", "employees"], ["#/work", "work"], ["#/dispatch", "work"], ["#/routines", "work"],
      ["#/meetings", "work"], ["#/actions", "work"], ["#/my-skills", "work"], ["#/settings", "settings"], ["#/settings?open=limits", "settings"], ["#/setup", "settings"],
      ["#/welcome", "settings"], ["#/terminals", "terminals"], ["#/term/t1", "terminals"], ["#/workbench", "workbench"], ["#/flows", "flows"], ["#/flows/f1", "flows"],
      ["#/projects", "projects"], ["#/skills", "skills"], ["#/skills/s1", "skills"], ["#/armory", "skills"], ["#/team", "team"], ["#/team/role/r1", "team"], ["#/staffing", "team"]]) {
      await page.go(hash);
      assert.deepStrictEqual(current(page), [nav], `${hash} lights ${nav}`);
    }
    await page.go("#/nowhere");
    assert.deepStrictEqual(current(page), [], "a page that does not exist lights nothing");
    assert.ok(page.main.textContent.includes("找不到這個頁面"));
  });

  await test("every route of v0.20.0 still paints a page (not 找不到這個頁面)", async () => {
    const page = boot("#/");
    await tick(30);
    const routes = ["#/", "#/workbench", "#/workbench/x", "#/ceo", "#/chat", "#/chat/c1", "#/chat/group", "#/chat/group/g1", "#/memory", "#/my-skills", "#/shared", "#/dispatch", "#/dispatch/d1",
      "#/actions", "#/routines", "#/templates", "#/meetings", "#/meetings/m1", "#/staffing", "#/staffing/s1", "#/armory", "#/skills", "#/skills/s1", "#/team", "#/team/role/r1",
      "#/projects", "#/projects/p1", "#/settings", "#/setup", "#/welcome", "#/term/t1", "#/terminals", "#/office", "#/flows", "#/flows/f1", "#/employees", "#/work"];
    for (const hash of routes) {
      await page.go(hash);
      assert.ok(!page.main.textContent.includes("找不到這個頁面"), `${hash} is still a page`);
    }
    // the source: route() has every top of the list, so a route added later or removed would show here
    const body = SOURCE.slice(SOURCE.indexOf("async function route()"), SOURCE.indexOf("// ---------- the Claude Code note"));
    for (const top of ["workbench", "ceo", "chat", "memory", "my-skills", "shared", "dispatch", "actions", "routines", "templates", "meetings", "staffing", "armory", "skills", "team",
      "projects", "settings", "setup", "welcome", "term", "terminals", "office", "flows", "employees", "work"]) assert.ok(body.includes(`top === "${top}"`), top);
  });

  await test("the two new pages are there with their names (P47-2 fills them in)", async () => {
    const page = boot("#/employees");
    await tick(30);
    assert.ok(page.main.textContent.includes("員工"), page.main.textContent);
    assert.ok(walk(page.main).some((n) => n.tag === "h1" && n.textContent === "員工"));
    await page.go("#/work");
    assert.ok(walk(page.main).some((n) => n.tag === "h1" && n.textContent === "工作"));
  });

  // ---- advanced mode: a display, nothing else --------------------------------------------------------------------------
  await test("advanced mode off (the default): the advanced items and the scan status stay hidden; the page reads /api/config once, GET only", async () => {
    const page = boot("#/employees");
    await tick(30);
    assert.ok(page.advanced.length === 7 && page.advanced.every(hiddenOf), "hidden");
    assert.ok(hiddenOf(page.scan));
    assert.ok(!page.side.classList.contains("adv-on"));
    const reads = () => page.log.filter(([m, u]) => m === "GET" && u === "/api/config").length;
    assert.strictEqual(reads(), 1, "read once at the start");
    await page.go("#/work");
    await page.go("#/employees");
    assert.strictEqual(reads(), 1, "and not again on each page");
    assert.ok(page.log.every(([m]) => m === "GET"), "nothing was sent");
  });

  await test("advanced mode on: the separator and the six items show, the scan status shows, the side bar says so (for the phone)", async () => {
    const page = boot("#/", { config: { advanced_mode: true } });
    await tick(30);
    assert.ok(page.advanced.every((li) => !hiddenOf(li)), "all shown");
    assert.ok(!hiddenOf(page.scan));
    assert.ok(page.side.classList.contains("adv-on"));
  });

  await test("syncAdvancedNav(on) shows and hides at once; a refusal of the save does not change the menu", async () => {
    const page = boot("#/", { config: { advanced_mode: false } });
    await tick(30);
    evalIn(page, "syncAdvancedNav(true)");
    assert.ok(page.advanced.every((li) => !hiddenOf(li)) && !hiddenOf(page.scan) && page.side.classList.contains("adv-on"));
    evalIn(page, "syncAdvancedNav(false)");
    assert.ok(page.advanced.every(hiddenOf) && hiddenOf(page.scan) && !page.side.classList.contains("adv-on"));
    evalIn(page, "syncAdvancedNav(true)");
    page.toggle.dispatch("click");
    evalIn(page, "syncAdvancedNav(false)");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false", "turning it off puts the phone menu away");
  });

  await test("the switch on the settings page: changing it saves {advanced_mode} to /api/config and the menu follows; a failed save leaves the menu as it was", async () => {
    let saved = null;
    let fail = false;
    const answer = (obj, ok = true, status = 200) => ({ ok, status, json: async () => obj });
    const handler = async (url, o, method) => {
      if (url === "/api/config" && method === "POST") { if (fail) return answer({ error: "x" }, false, 500); saved = JSON.parse(o.body); return answer({ ok: true, config: {}, rescan_needed: false }); }
      if (url === "/api/config") return answer({ config: { advanced_mode: !!(saved && saved.advanced_mode), show_mcode: false }, state_dir: "/x", runtime_socket: "" });
      if (url === "/api/overview") return answer({ sources: [], facts: {}, problems: [], generated_at: 1, scan_seconds: 0, totals: { active: 0 } });
      if (url === "/api/skills") return answer({ skills: [], categories: [] });
      if (url === "/api/roles") return answer({ roles: [] });
      if (url === "/api/translations" || url === "/api/role-translations") return answer({ entries: {}, counts: { fresh: 0, stale: 0, none: 0, orphan: 0 }, job: null, engine: "claude" });
      return null;
    };
    const page = boot("#/settings", { fetchImpl: handler });
    await tick(60);
    const sw = () => { const label = walk(page.main).find((n) => n.tag === "label" && /進階模式/.test(n.textContent)); return label && walk(label).find((n) => n.tag === "input"); };
    assert.ok(sw(), "the switch is on the page");
    assert.ok(page.advanced.every(hiddenOf));
    fail = true;
    sw().checked = true;
    sw().dispatch("change", { target: sw() });
    await tick(40);
    assert.ok(page.advanced.every(hiddenOf), "the save failed: the menu is as it was");
    fail = false;
    sw().checked = true;
    sw().dispatch("change", { target: sw() });
    await tick(60);
    assert.deepStrictEqual(saved, { advanced_mode: true }, "only the one key");
    assert.ok(page.advanced.every((li) => !hiddenOf(li)), "and the menu follows");
    sw().checked = false;
    sw().dispatch("change", { target: sw() });
    await tick(60);
    assert.deepStrictEqual(saved, { advanced_mode: false });
    assert.ok(page.advanced.every(hiddenOf));
  });

  await test("the advanced mode asks for nothing and sends nothing but its own key: switching it makes no other request", async () => {
    const page = boot("#/", { config: { advanced_mode: true } });
    await tick(30);
    const before = page.log.length;
    evalIn(page, "syncAdvancedNav(false)");
    evalIn(page, "syncAdvancedNav(true)");
    await tick(10);
    assert.strictEqual(page.log.length, before, "syncAdvancedNav makes no request");
  });

  // ---- an advanced page opened by its address, advanced mode off ----------------------------------------------------------
  await test("an advanced page opened by an address while advanced mode is off: it opens, with one line at the top; it is not blocked", async () => {
    const page = boot("#/terminals", { config: { advanced_mode: false } });
    await tick(30);
    assert.ok(!page.main.textContent.includes("找不到這個頁面"));
    assert.ok(!hiddenOf(page.note), "the line is shown");
    assert.ok(page.note.textContent.startsWith("這是進階頁面。要在選單看到它，到設定打開進階模式。"), page.note.textContent);
    const link = walk(page.note).find((n) => n.tag === "a");
    assert.ok(link && link.getAttribute("href") === "#/settings", "with a way to the switch");
    for (const hash of ["#/workbench", "#/flows", "#/projects", "#/skills", "#/team", "#/term/t1", "#/armory", "#/staffing"]) {
      await page.go(hash);
      assert.ok(!hiddenOf(page.note), `${hash}: the line`);
    }
    for (const hash of ["#/", "#/employees", "#/work", "#/settings", "#/chat", "#/office", "#/setup"]) {
      await page.go(hash);
      assert.ok(hiddenOf(page.note), `${hash}: no line`);
    }
  });

  await test("with advanced mode on the line is not shown on an advanced page; it goes away when the switch is turned on", async () => {
    const on = boot("#/terminals", { config: { advanced_mode: true } });
    await tick(30);
    assert.ok(hiddenOf(on.note));
    const off = boot("#/terminals", { config: { advanced_mode: false } });
    await tick(30);
    assert.ok(!hiddenOf(off.note));
    evalIn(off, "syncAdvancedNav(true)");
    assert.ok(hiddenOf(off.note), "turned on: the line goes away");
    evalIn(off, "syncAdvancedNav(false)");
    assert.ok(!hiddenOf(off.note), "and comes back when it is turned off while on the page");
  });

  await test("when /api/config cannot be read the menu stays at the four and no line is shown (nothing is guessed)", async () => {
    const page = boot("#/terminals", { fetchImpl: async (url) => (url === "/api/config" ? { ok: false, status: 500, json: async () => ({ error: "x" }) } : null) });
    await tick(30);
    assert.ok(page.advanced.every(hiddenOf));
    assert.ok(hiddenOf(page.note));
  });

  // ---- the phone ------------------------------------------------------------------------------------------------------
  await test("phone: the button says 選單 and a screen reader hears the page you are on (P50-2; it was 進階：…); on a page that lights nothing it is just 選單; going to a page puts the menu away", async () => {
    const page = boot("#/team", { config: { advanced_mode: true } });
    await tick(30);
    assert.strictEqual(page.label.textContent, "選單");
    assert.strictEqual(page.toggle.getAttribute("aria-label"), "選單（目前在「員工詳細資料」）");
    page.toggle.dispatch("click");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "true");
    assert.ok(page.side.classList.contains("nav-open"));
    await page.go("#/flows");
    assert.strictEqual(page.toggle.getAttribute("aria-label"), "選單（目前在「流程」）");
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false");
    await page.go("#/chat");
    assert.strictEqual(page.toggle.getAttribute("aria-label"), "選單（目前在「員工」）");
    await page.go("#/term/t1");
    assert.strictEqual(page.toggle.getAttribute("aria-label"), "選單（目前在「指令視窗」）");
    await page.go("#/nowhere");
    assert.strictEqual(page.toggle.getAttribute("aria-label"), "選單");
  });

  await test("phone: Escape closes the open advanced list and gives focus back to the button; the page name is the link's own words", async () => {
    const page = boot("#/", { config: { advanced_mode: true } });
    await tick(30);
    const esc = () => { for (const fn of page.docListeners.keydown || []) fn({ key: "Escape" }); };
    page.toggle.dispatch("click");
    Node.focused = null;
    esc();
    assert.strictEqual(page.toggle.getAttribute("aria-expanded"), "false");
    assert.strictEqual(Node.focused, page.toggle);
    assert.strictEqual(evalIn(page, 'navPageName("home")'), "新對話");
    assert.strictEqual(evalIn(page, 'navPageName("chat")'), "員工", "the item that a page belongs to");
    assert.strictEqual(evalIn(page, 'navPageName("team")'), "員工詳細資料");
    assert.strictEqual(evalIn(page, 'navPageName("nope")'), "");
  });

  await test("css: on a phone (P50-2) the bar is a drawer behind the menu button (it holds the advanced items too), the button is not there on a wide window, and nothing scrolls sideways", () => {
    const at = CSS.indexOf("/* P50-2");
    assert.ok(at > 0, "the P50-2 part");
    const block = /@media \(max-width: 720px\) \{([\s\S]*?)\n\}\n/.exec(CSS.slice(at))[1];
    assert.ok(/\.nav-toggle\s*\{[^}]*display:\s*none/.test(CSS.slice(CSS.indexOf(".nav-toggle {"))), "the button is not there by default");
    assert.ok(/\.nav-toggle\s*\{[^}]*display:\s*inline-flex/.test(block), "the button shows on a phone, whatever the advanced mode");
    assert.ok(/\.side-panel\s*\{[^}]*translateX\(-100%\)/.test(block) && /\.side\.nav-open \.side-panel\s*\{[^}]*transform:\s*none/.test(block), "the whole bar (advanced items included) is in the drawer");
    assert.ok(!/overflow-x:\s*auto/.test(block), "no sideways scroll");
    assert.ok(/min-height:\s*44px/.test(CSS.slice(CSS.indexOf(".nav-toggle {"))), "a touch-sized target");
    assert.ok(/\.nav \[hidden\]\s*\{\s*display:\s*none/.test(CSS), "a hidden item stays hidden whatever the layout says");
  });

  // ---- the source ---------------------------------------------------------------------------------------------------
  await test("source: advanced_mode is only read (conf.advanced_mode) and sent as the body of the settings switch; the menu code reads nothing else from it", () => {
    const hits = SOURCE.split("\n").map((l, i) => [i + 1, l]).filter(([, l]) => l.includes("advanced_mode"));
    assert.ok(hits.length >= 2 && hits.length <= 4, `${hits.length} places: ${hits.map(([n]) => n).join(",")}`);
    for (const [n, l] of hits) assert.ok(/\b(?:conf|config)\.advanced_mode\b|\{ advanced_mode: [^}]*\}/.test(l), `line ${n}: ${l.trim()}`);
  });

  await test("source: the menu code uses no innerHTML, no emoji and no outside resource", () => {
    const part = SOURCE.slice(SOURCE.indexOf("// The side bar (ADR 0013, 0015)"), SOURCE.indexOf("let liveTimer = null;"));
    assert.ok(part.includes("NAV_PARENT") && part.includes("syncAdvancedNav"));
    assert.ok(!/innerHTML|insertAdjacentHTML/.test(part) && !/https?:\/\//.test(part) && !/\p{Extended_Pictographic}/u.test(part));
  });

  console.log(`\n${passed} passed`);
})();
