// P1 and P2 (design card-play 3.1 to 3.4): the card pool page, the three-step card wizard, the starter deck, the pure helpers
// (permissionSuggestion, cardLight, sameNameCard, skillCompatible, cardSlots, cardDeparture), the card vocabulary and the
// honesty rules; the role card (two faces, flip, slots, light), the art and the camp frames.
// Runs the real viewTeam() / openCardWizard() / openStarterDeck() / viewWorkbench() from web/app.js against a
// synthetic DOM and a fetch stub. It is NOT a browser test.
//
// Run: node tests/frontend/card_pool.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");

// --- synthetic DOM (structure, listeners, attributes, classList) ---------
const idRegistry = new Map();
class Node {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.dataset = {};
    this._classes = new Set();
    this._attrs = {};
    this._listeners = {};
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.multiple = false;
    this.size = 0;
  }
  contains(node) { return this === node || this.children.some(c => c instanceof Node && c.contains(node)); }
  get classList() {
    const self = this;
    return {
      add: (...cls) => cls.forEach((c) => self._classes.add(c)),
      remove: (...cls) => cls.forEach((c) => self._classes.delete(c)),
      contains: (c) => self._classes.has(c),
      toggle(c, force) {
        const want = force === undefined ? !self._classes.has(c) : force;
        if (want) self._classes.add(c); else self._classes.delete(c);
        return want;
      },
    };
  }
  get className() { return Array.from(this._classes).join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get id() { return this._attrs.id || ""; }
  set id(v) { this.setAttribute("id", v); }
  set textContent(v) {
    this.children = [];
    if (v !== "" && this.tag !== "#text") {
      const t = new Node("#text"); t.textContent = String(v); t.parentNode = this;
      this.children.push(t);
    } else if (this.tag === "#text") {
      this._text = String(v);
    }
  }
  get textContent() {
    if (this.tag === "#text") return this._text || "";
    return this.children.map((c) => c.textContent || "").join("");
  }
  setAttribute(k, v) {
    this._attrs[k] = String(v);
    if (k === "id") idRegistry.set(String(v), this);
  }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
  }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k); }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
  removeEventListener(ev, fn) {
    if (!this._listeners[ev]) return;
    this._listeners[ev] = this._listeners[ev].filter((f) => f !== fn);
  }
  dispatch(type, evt = {}) {
    for (const fn of (this._listeners[type] || []).slice()) fn({ type, target: this, preventDefault() {}, ...evt });
  }
  click() { this.dispatch("click"); }
  append(...kids) {
    for (const kid of kids) {
      if (kid instanceof Node) {
        // like the real DOM: a node has one parent, so adding it here takes it away from the old one
        if (kid.parentNode) {
          const i = kid.parentNode.children.indexOf(kid);
          if (i >= 0) kid.parentNode.children.splice(i, 1);
        }
        kid.parentNode = this;
      }
      this.children.push(kid);
    }
  }
  appendChild(kid) { this.append(kid); return kid; }
  replaceChildren() {
    for (const k of this.children) if (k instanceof Node) k.parentNode = null;
    this.children = [];
  }
  remove() {
    if (this.parentNode) {
      const i = this.parentNode.children.indexOf(this);
      if (i >= 0) this.parentNode.children.splice(i, 1);
      this.parentNode = null;
    }
  }
  querySelector(sel) { return walk(this).find((n) => n.tag === sel) || null; }
  querySelectorAll(sel) { return walk(this).filter((n) => n.tag === sel); }
  focus() {}
  blur() {}
  get selectedOptions() {
    return this.children.filter((c) => c.hasAttribute("selected") && c.tag === "option");
  }
}
function walk(n) {
  const out = [];
  for (const c of n.children) {
    if (c instanceof Node) { out.push(c); out.push(...walk(c)); }
  }
  return out;
}

const main = new Node("main");
const body = new Node("body");
body.append(main);
main.setAttribute("id", "main");
idRegistry.set("main", main);

// --- fetch stub --------------------------------------------------------
const fetchCalls = [];
const fetchHandlers = {};

function makeFetchResponse(status, body) {
  return { ok: status >= 200 && status < 300, status,
           json: async () => body };
}
function jsonResponse(body, status = 200) { return makeFetchResponse(status, body); }

async function fetchStub(url, options) {
  fetchCalls.push({ url, options });
  const m = (options && options.method) || "GET";
  const key = `${m} ${url}`;
  const handler = fetchHandlers[key];
  if (!handler) throw new Error(`no handler for ${key}`);
  return handler(url, options);
}

// --- canned responses ---------------------------------------------------
const catalogBody = {
  ok: true,
  tools: ["claude", "codex", "shared"],
  permission_keys: ["read", "write", "test", "deploy"],
  permission_values: ["allow", "deny", "unspecified"],
  permission_intent_only: true,
  model_id_max_length: 200,
  max_profiles: 500,
  max_skills_per_profile: 200,
  professions: [
    { role_id: "r-1", name: "Writer", tool: "claude", kind: "subagent",
      skill_link_count: 1, skill_link_basis: "declared" },
    { role_id: "r-2", name: "Reviewer", tool: "codex", kind: "subagent",
      skill_link_count: 0, skill_link_basis: "undeclared" },
  ],
  skills: [
    { skill_id: "s-1", name: "alpha", invoke_name: "tool:alpha", tool: "claude",
      scope: "user", activation: "active", excerpt: "alpha desc" },
    { skill_id: "s-2", name: "beta", invoke_name: "tool:beta", tool: "codex",
      scope: "user", activation: "active", excerpt: "beta desc" },
  ],
  disclosures: [
    "技能卡插在角色卡上，只是你的挑選紀錄，不代表已經進入任何執行中的終端。",
    "權限意圖是隊伍分工的標記，VBear 不會因此限制這個程式的真實能力。",
    "角色卡只存放在這個主控台自己的狀態資料夾。",
  ],
  verified_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" },
  starter_deck: [
    { key: "planner", name: "CEO", position: "planner", tool: "claude",
      permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } },
    { key: "executor", name: "工匠", position: "executor", tool: "claude",
      permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } },
    { key: "reviewer", name: "審查員", position: "reviewer", tool: "codex",
      permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } },
  ],
  positions: ["planner", "executor", "reviewer"],
  demo_id_prefix: "demo-",
  codex_installed: true,
};

const profilesList = [
  { id: "p-1", name: "First", profession_role_id: "r-1",
    model: { tool: "claude", model_id: "opus-4.1" },
    equipped_skill_ids: ["s-1"],
    permission_intents: { read: "allow", write: "deny", test: "unspecified", deploy: "deny" },
    enabled: true, created_at: 1700000000, updated_at: 1700000000,
    _unresolved: { profession: false, skills: [] } },
  { id: "p-2", name: "Stuck", profession_role_id: "r-2",
    model: { tool: "codex", model_id: "gpt-test" },
    equipped_skill_ids: ["s-2", "gone-skill"],
    permission_intents: { read: "unspecified", write: "unspecified",
                          test: "unspecified", deploy: "unspecified" },
    enabled: false, created_at: 1700000010, updated_at: 1700000010,
    _unresolved: { profession: false, skills: ["gone-skill"] } },
];

const staticData = {
  skills: [
    { skill_id: "s-1", name: "alpha", invoke_name: "tool:alpha", tool: "claude",
      scope: "user", activation: "active", description: { value: "alpha desc" } },
    { skill_id: "s-2", name: "beta", invoke_name: "tool:beta", tool: "codex",
      scope: "user", activation: "active", description: { value: "beta desc" } },
  ],
  roles: [
    { role_id: "r-1", name: "Writer", tool: "claude", kind: "subagent",
      skill_link_ids: ["s-1"], skill_link_basis: "declared" },
    { role_id: "r-2", name: "Reviewer", tool: "codex", kind: "subagent",
      skill_link_ids: [], skill_link_basis: "undeclared" },
  ],
};

function freshContext(handlers) {
  Object.keys(fetchHandlers).forEach((k) => delete fetchHandlers[k]);
  fetchHandlers["GET /api/translations"] = () => jsonResponse({entries:{},counts:{fresh:0,stale:0,none:0,orphan:0},job:null,engine:"claude"});
  Object.assign(fetchHandlers, handlers);
  fetchCalls.length = 0;
  for (const id of [...idRegistry.keys()]) idRegistry.delete(id);
  main.replaceChildren();
  body.replaceChildren();
  body.append(main);
  main.setAttribute("id", "main");
  idRegistry.set("main", main);
  // The toast region referenced by toast(); must exist with id "toast".
  const toastNode = new Node("div");
  toastNode.setAttribute("id", "toast");
  body.append(toastNode);

  const documentElement = new Node("html");
  const ctx = {
    Node, console: { log: () => {}, warn: () => {}, error: () => {} },
    document: {
      createElement: (t) => new Node(t),
      createElementNS: (_ns, t) => new Node(t),
      createTextNode: (t) => { const n = new Node("#text"); n.textContent = t; return n; },
      getElementById: (id) => idRegistry.get(id) || null,
      body, documentElement, activeElement: null,
    },
    setTimeout: (f, _ms) => { if (typeof f === "function") f(); return 0; },
    clearTimeout: () => {},
    location: { hash: "" },
    history: { replaceState: (_s, _t, url) => { ctx.__replaced.push(url); } },
    __replaced: [],
    localStorage: { getItem: (k) => (ctx.__ls.has(k) ? ctx.__ls.get(k) : null), setItem: (k, v) => { ctx.__ls.set(k, v); } },
    __ls: new Map(),
    URLSearchParams,
    confirm: () => true,
    fetch: fetchStub,
    window: {
      addEventListener: () => {}, removeEventListener: () => {}, innerWidth: 1024,
    },
    setKids: (parent, ...kids) => {
      parent.replaceChildren();
      for (const k of kids) parent.append(k);
    },
  };
  vm.createContext(ctx);
  return ctx;
}

function evalAgentBuilderSlice(ctx) {
  const idxStart = source.indexOf("function el(");
  const idxEnd = source.indexOf("setTheme(store.get");
  const slice = source.slice(idxStart, idxEnd);
  vm.runInContext(slice, ctx);
}

function findText(node, needle) {
  return walk(node).some((n) => (n.textContent || "").includes(needle));
}

let lastFocus = null;
Node.prototype.focus = function () { lastFocus = this; };
const tick = async (n = 4) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
const btnByText = (root, text) => walk(root).find((n) => n.tag === "button" && (n.textContent || "").trim() === text);
const byData = (root, attr, value) => walk(root).filter((n) => n.getAttribute && n.getAttribute(attr) === value);
const textOf = (root) => walk(root).filter((n) => n.tag === "#text").map((n) => n.textContent).join(" ");
const dialog = () => body.children.find((c) => c !== main && c.getAttribute && c.getAttribute("role") === "dialog");

const catalog = {
  ok: true, tools: ["claude", "codex", "shared"],
  permission_keys: ["read", "write", "test", "deploy"], permission_values: ["allow", "deny", "unspecified"],
  permission_intent_only: true, model_id_max_length: 200, max_profiles: 500, max_skills_per_profile: 200,
  professions: [{ role_id: "r-1", name: "Writer", tool: "claude", kind: "subagent", skill_link_count: 1, skill_link_basis: "declared" }],
  skills: [
    { skill_id: "s-c", name: "claude-skill", tool: "claude", scope: "user", activation: "active", excerpt: "for claude" },
    { skill_id: "s-x", name: "codex-skill", tool: "codex", scope: "user", activation: "active", excerpt: "for codex" },
    { skill_id: "s-s", name: "shared-skill", tool: "shared", scope: "user", activation: "active", excerpt: "for both" },
  ],
  disclosures: ["技能卡插在角色卡上，只是你的挑選紀錄。"],
  verified_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" },
  starter_deck: [
    { key: "planner", name: "CEO", position: "planner", tool: "claude", permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } },
    { key: "executor", name: "工匠", position: "executor", tool: "claude", permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } },
    { key: "reviewer", name: "審查員", position: "reviewer", tool: "codex", permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } },
  ],
  positions: ["planner", "executor", "reviewer"], demo_id_prefix: "demo-", codex_installed: true,
};
const VERIFIED = { read: "allow", write: "allow", test: "allow", deploy: "deny" };
const ALL_DENY = { read: "deny", write: "deny", test: "deny", deploy: "deny" };
const mkProfile = (id, name, tool, intents, extra = {}) => ({
  id, name, profession_role_id: null, model: { tool, model_id: "" }, equipped_skill_ids: [],
  permission_intents: intents, enabled: true, created_at: 1, updated_at: 1, _unresolved: { profession: false, skills: [] }, ...extra });
const roles = [
  { role_id: "cli-claude", name: "Claude Code 主代理", tool: "claude", kind: "cli", skill_link_ids: [], skill_link_basis: "load_scope",
    description: { value: "d", origin: "derived" }, model: { value: "m", origin: "author" } },
  { role_id: "r-1", name: "Writer", tool: "claude", kind: "subagent", skill_link_ids: [], skill_link_basis: "undeclared" },
];

// What the server's loadout says of a profile: no reason against a launch unless a test gives one.
function loadoutBody(p, over = {}) {
  return { ok: true, profile: { id: p.id }, index: { loaded: true }, profession: { state: "none", role_id: null },
    skills: { title: "技能卡（收藏中：VBear 啟動時不載入）", all_inactive: true,
      items: (p.equipped_skill_ids || []).map((id) => ({ skill_id: id, state: "in_index", name: id, will_load: false, effective: false })) },
    blockers: [], ...over };
}
function baseHandlers(profiles, cat = catalog, extra = {}) {
  const loadouts = {};
  for (const p of profiles) loadouts[`GET /api/agent-profiles/${encodeURIComponent(p.id)}/loadout`] = () => jsonResponse(loadoutBody(p));
  return {
    ...loadouts,
    "GET /api/overview": () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
    "GET /api/skills": () => jsonResponse({ skills: [], categories: [] }),
    "GET /api/roles": () => jsonResponse({ roles }),
    "GET /api/live": () => jsonResponse({ sessions: [], projects: [], attention: [], usage: { sessions: [] }, runtime: { available: true, problems: [] } }),
    "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [] }),
    "GET /api/task-templates": () => jsonResponse({ ok: true, templates: { custom: {} } }),
    "GET /api/governance": () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
    "GET /api/agent-profiles": () => jsonResponse({ ok: true, profiles }),
    "GET /api/agent-builder/catalog": () => jsonResponse(cat),
    ...extra,
  };
}
async function openPool(profiles, cat = catalog, extra = {}) {
  const ctx = freshContext(baseHandlers(profiles, cat, extra));
  evalAgentBuilderSlice(ctx);
  await ctx.viewTeam();
  await tick(8);
  return ctx;
}

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); }
  catch (e) { console.log("FAIL -", name); console.log(e && e.stack || e); process.exitCode = 1; }
}

(async () => {
  const pure = freshContext({});
  evalAgentBuilderSlice(pure);

  await test("permissionSuggestion: every position and no position take the one combination the server names (R10); no catalog data is all deny", () => {
    const sug = pure.permissionSuggestion;
    for (const p of ["planner", "executor", "reviewer", null, "", "boss", "constructor", undefined]) assert.deepStrictEqual({ ...sug(catalog, p) }, VERIFIED, String(p));
    // the page holds no copy: a catalog that names another combination changes every suggestion
    const other = { ...catalog, verified_intents: { read: "allow", write: "deny", test: "allow", deploy: "deny" },
      starter_deck: catalog.starter_deck.map((c) => ({ ...c, permission_intents: { read: "allow", write: "deny", test: "allow", deploy: "deny" } })) };
    for (const p of ["planner", "executor", "reviewer", null]) assert.deepStrictEqual({ ...sug(other, p) }, { read: "allow", write: "deny", test: "allow", deploy: "deny" }, String(p));
    // no deck: the verified set; neither: all deny, which grants nothing
    const noDeck = { verified_intents: catalog.verified_intents };
    for (const p of ["planner", null]) assert.deepStrictEqual({ ...sug(noDeck, p) }, VERIFIED);
    assert.deepStrictEqual({ ...sug({}, "planner") }, ALL_DENY);
    assert.deepStrictEqual({ ...sug(null, "planner") }, ALL_DENY);
    // a deck entry with a value that is not allow or deny is not used (never "unspecified"); the verified set stands in
    const odd = { verified_intents: catalog.verified_intents, starter_deck: [{ position: "planner", permission_intents: { read: "unspecified", write: "allow", test: "x", deploy: 1 } }] };
    assert.deepStrictEqual({ ...sug(odd, "planner") }, VERIFIED);
    assert.deepStrictEqual({ ...sug({ verified_intents: { read: "allow", write: "enforce", test: "allow", deploy: "deny" } }, null) }, ALL_DENY);
  });

  await test("cardLight: green only when all four intents are decided, in the design's words, never 安全", () => {
    const L = pure.cardLight;
    const green = L({ permission_intents: { read: "allow", write: "deny", test: "allow", deploy: "deny" } });
    assert.strictEqual(green.state, "green");
    assert.strictEqual(green.text, "可以出發（權限意圖都已決定）");
    assert.ok(!/安全|已限制/.test(green.text));
    const yellow = L({ permission_intents: { read: "allow", write: "unspecified", test: "deny", deploy: "deny" } });
    assert.strictEqual(yellow.state, "yellow");
    assert.strictEqual(yellow.text, "還差一步：權限意圖還沒決定");
    assert.deepStrictEqual([...yellow.undecided], ["編輯寫入"]);
    for (const bad of [null, {}, { permission_intents: null }, { permission_intents: { read: "allow" } },
      { permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "enforce" } }]) {
      assert.strictEqual(L(bad).state, "yellow", JSON.stringify(bad));
    }
  });

  await test("sameNameCard: case, width and spaces are ignored; the card itself and empty names never match", () => {
    const list = [{ id: "a", name: "CEO" }, { id: "b", name: "工匠" }];
    assert.strictEqual(pure.sameNameCard(list, "ceo", null).id, "a");
    assert.strictEqual(pure.sameNameCard(list, "  ＣＥＯ ", null).id, "a");
    assert.strictEqual(pure.sameNameCard(list, "CEO", "a"), null);
    assert.strictEqual(pure.sameNameCard(list, "", null), null);
    assert.strictEqual(pure.sameNameCard(list, "   ", null), null);
    assert.strictEqual(pure.sameNameCard(null, "CEO", null), null);
    assert.strictEqual(pure.sameNameCard(list, "新名字", null), null);
  });

  await test("isDemoCard and sortCards: sample cards by id prefix go last, the rest keep their order", () => {
    const l = [{ id: "demo-a" }, { id: "mine-1" }, { id: "demo-b" }, { id: "mine-2" }];
    assert.deepStrictEqual([...pure.sortCards(l, catalog).map((p) => p.id)], ["mine-1", "mine-2", "demo-a", "demo-b"]);
    assert.strictEqual(pure.isDemoCard({ id: "demo-x" }, null), true);
    assert.strictEqual(pure.isDemoCard({ id: "xdemo-x" }, catalog), false);
    assert.strictEqual(pure.isDemoCard(null, catalog), false);
    assert.strictEqual(pure.isDemoCard({ id: "my-1" }, { demo_id_prefix: "my-" }), true);
  });

  await test("skillCompatible: row by row (card tool x skill source)", () => {
    const rows = [
      ["claude", "claude", true], ["claude", "codex", false], ["claude", "shared", true], ["claude", "agy", false],
      ["codex", "codex", true], ["codex", "claude", false], ["codex", "shared", true],
      ["shared", "shared", true], ["shared", "claude", false], ["shared", "codex", false],
      ["claude", undefined, false], ["claude", "", false], [undefined, "claude", false],
    ];
    for (const [tool, source, want] of rows) {
      assert.strictEqual(pure.skillCompatible({ tool: source }, tool), want, `${tool} card, ${source} skill`);
    }
    assert.strictEqual(pure.skillCompatible(null, "claude"), false);
    assert.strictEqual(pure.skillIncompatibleNote("codex"), "Codex 不會讀這張卡");
    assert.strictEqual(pure.skillIncompatibleNote("claude"), "Claude Code 不會讀這張卡");
    assert.strictEqual(pure.skillIncompatibleNote("shared"), "共用角色卡只能插共用的技能卡");
  });

  await test("the pool page: title, header buttons, cards in a grid, sample cards last and labelled 示範", async () => {
    const profiles = [
      mkProfile("demo-1", "示範工匠", "claude", ALL_DENY),
      mkProfile("p-1", "Mine", "claude", { read: "allow", write: "deny", test: "allow", deploy: "deny" }),
      mkProfile("p-2", "Reviewer", "codex", { read: "allow", write: "unspecified", test: "deny", deploy: "deny" }),
    ];
    const ctx = await openPool(profiles);
    assert.strictEqual(walk(main).find((n) => n.tag === "h1").textContent, "角色卡池");
    assert.ok(btnByText(main, "＋ 新角色卡"), "new card button");
    assert.ok(!btnByText(main, "用起手牌組開始"), "the starter deck is for a person with no card of their own");
    const cards = walk(main).filter((n) => n.tag === "article" && n.getAttribute("data-profile-id"));
    assert.deepStrictEqual(cards.map((c) => c.getAttribute("data-profile-id")), ["p-1", "p-2", "demo-1"]);
    assert.ok(findText(cards[2], "示範") && !findText(cards[0], "示範"));
    assert.ok(cards.every((c) => findText(c, "名冊，不代表正在出勤")));
    assert.ok(!findText(main, "出勤中"), "no attendance is claimed");
    const light = (c) => byData(c, "data-pcard", "light")[0];
    assert.ok(light(cards[0]).className.includes("rcard-green") && findText(light(cards[0]), "可以出發（權限意圖都已決定）"));
    assert.ok(light(cards[1]).className.includes("rcard-yellow") && findText(light(cards[1]), "還差一步：權限意圖還沒決定"));
    assert.ok(byData(cards[1], "data-pcard", "decide").length === 1 && byData(cards[0], "data-pcard", "decide").length === 0);
    assert.ok(findText(light(cards[0]), "實際能不能出發，以出發通行證為準"), "the green light does not promise a launch");
    // the scanned role templates are folded away by default
    const tpl = byData(main, "data-pool", "templates")[0];
    assert.strictEqual(tpl.tag, "details");
    assert.ok(!tpl.hasAttribute("open") && findText(tpl, "你電腦裡現成的角色範本（職業標籤）"));
    assert.ok(findText(tpl, "Claude Code 主代理") && findText(tpl, "Writer"));
    assert.ok(ctx.document.body === body);
  });

  await test("the starter deck button shows with no card of one's own (none at all, or only samples)", async () => {
    await openPool([]);
    assert.ok(btnByText(main, "用起手牌組開始") && findText(main, "還沒有角色卡"));
    await openPool([mkProfile("demo-1", "示範", "claude", ALL_DENY)]);
    assert.ok(btnByText(main, "用起手牌組開始"));
    await openPool([mkProfile("p-1", "Mine", "claude", ALL_DENY)]);
    assert.ok(!btnByText(main, "用起手牌組開始"));
  });

  await test("the tool filter keeps only that tool's cards and says so", async () => {
    const profiles = [mkProfile("a", "A", "claude", ALL_DENY), mkProfile("b", "B", "codex", ALL_DENY)];
    const ctx = await openPool(profiles);
    ctx.localStorage.setItem("sid:teamCardTool", JSON.stringify("codex"));
    await ctx.viewTeam();
    const ids = () => walk(main).filter((n) => n.tag === "article" && n.getAttribute("data-profile-id")).map((n) => n.getAttribute("data-profile-id"));
    assert.deepStrictEqual(ids(), ["b"]);
    const pressed = byData(main, "data-filter", "codex")[0];
    assert.strictEqual(pressed.getAttribute("aria-pressed"), "true");
    ctx.localStorage.setItem("sid:teamCardTool", JSON.stringify("nonsense"));
    await ctx.viewTeam();
    assert.deepStrictEqual(ids(), ["a", "b"], "an unknown filter value is no filter");
  });

  await test("出發 on a card goes to the workbench with the pre-launch check requested; a disabled card cannot", async () => {
    const ctx = await openPool([mkProfile("p-1", "Mine", "claude", ALL_DENY), mkProfile("p-2", "Off", "claude", ALL_DENY, { enabled: false })]);
    const launch = (id) => byData(walk(main).find((n) => n.getAttribute && n.getAttribute("data-profile-id") === id), "data-pcard", "launch")[0];
    launch("p-1").dispatch("click");
    assert.strictEqual(ctx.location.hash, "#/workbench?profile=p-1&launch=1");
    assert.ok(launch("p-2").disabled, "a disabled card has no 出發");
  });

  await test("viewWorkbench with the launch request opens the pre-launch check once and cleans the address", async () => {
    const profiles = [mkProfile("p-1", "Mine", "claude", ALL_DENY)];
    const ctx = freshContext(baseHandlers(profiles, catalog, {
      "GET /api/agent-profiles/p-1/loadout": () => jsonResponse({ ok: true, profile: { permission_intents: ALL_DENY }, skills: { items: [] }, armor: { applicable: false }, blockers: [] }),
    }));
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null, "p-1", true);
    await tick();
    const d = dialog();
    assert.ok(d && findText(d, "出發通行證：Mine"), "the check is open");
    assert.deepStrictEqual([...ctx.__replaced], ["#/workbench?profile=p-1"]);
    // without the request nothing opens
    const ctx2 = freshContext(baseHandlers(profiles, catalog, {
      "GET /api/agent-profiles/p-1/loadout": () => jsonResponse({ ok: true, profile: {}, skills: { items: [] }, armor: { applicable: false }, blockers: [] }),
    }));
    evalAgentBuilderSlice(ctx2);
    await ctx2.viewWorkbench(null, null, "p-1", false);
    await tick();
    assert.ok(!dialog());
  });

  // ---- the wizard ----
  async function openWizard(profiles = [], cat = catalog, extra = {}) {
    const posts = [];
    const ctx = await openPool(profiles, cat, {
      "POST /api/agent-profiles": (url, options) => {
        const b = JSON.parse(options.body); posts.push(b);
        return jsonResponse({ ok: true, profile: mkProfile("p-NEW", b.name, b.model.tool, b.permission_intents, { equipped_skill_ids: b.equipped_skill_ids }) });
      }, ...extra });
    btnByText(main, "＋ 新角色卡").dispatch("click");
    await tick();
    return { ctx, posts, d: dialog() };
  }
  const typeName = (d, text) => { const i = walk(d).find((n) => n.tag === "input"); i.value = text; i.dispatch("input"); return i; };

  await test("wizard: three steps, the controls at the bottom, no step entered without a name", async () => {
    const { d } = await openWizard();
    assert.ok(d, "dialog opened");
    assert.strictEqual(walk(d).find((n) => n.tag === "h2").textContent, "新角色卡");
    const steps = walk(d).filter((n) => n.tag === "button" && n.className.includes("cw-step"));
    assert.deepStrictEqual(steps.map((s) => s.getAttribute("aria-label")), ["第 1 步，共 3 步：名字與外觀", "第 2 步，共 3 步：陣營與位置", "第 3 步，共 3 步：技能卡"]);
    assert.strictEqual(steps[0].getAttribute("aria-current"), "step");
    assert.ok(btnByText(d, "取消") && btnByText(d, "下一步") && !btnByText(d, "上一步") && !btnByText(d, "建立"));
    // the footer is its own sibling of the scrolling body, so it stays in view on a phone
    const foot = walk(d).find((n) => n.className.includes("cw-foot"));
    assert.ok(foot && foot.parentNode === walk(d).find((n) => n.className.includes("cw-box")));
    btnByText(d, "下一步").dispatch("click");
    assert.ok(findText(d, "請先替這張卡取個名字"), "the error is on the name field");
    assert.strictEqual(steps[0].getAttribute("aria-current"), "step");
    const s1 = walk(d).filter((n) => n.tag === "button" && n.className.includes("cw-step"));
    s1[2].dispatch("click");
    assert.ok(findText(d, "請先替這張卡取個名字"), "jumping ahead without a name is refused too");
    typeName(d, "Alpha");
    btnByText(d, "下一步").dispatch("click");
    assert.ok(findText(d, "陣營就是這張卡用哪個工具") && btnByText(d, "上一步"));
    btnByText(d, "下一步").dispatch("click");
    assert.ok(btnByText(d, "建立") && !btnByText(d, "下一步") && findText(d, "收藏中"));
    btnByText(d, "上一步").dispatch("click");
    btnByText(d, "上一步").dispatch("click");
    assert.ok(walk(d).some((n) => n.tag === "input" && n.getAttribute("id") === "cw-name"));
  });

  await test("wizard: the focus stays inside the dialog when the step changes or a choice redraws it", async () => {
    const { d } = await openWizard();
    typeName(d, "Focus");
    btnByText(d, "下一步").dispatch("click");
    assert.strictEqual(lastFocus.getAttribute("data-step"), "2", "the step's own button takes the focus");
    byData(dialog(), "data-tool", "codex")[0].dispatch("click");
    assert.strictEqual(lastFocus.getAttribute("data-tool"), "codex", "a redrawn choice keeps the focus");
    byData(dialog(), "data-position", "reviewer")[0].dispatch("click");
    assert.strictEqual(lastFocus.getAttribute("data-position"), "reviewer");
    assert.ok(dialog().contains(lastFocus));
  });

  await test("wizard: Enter in the name field goes to step 2; Escape closes the dialog", async () => {
    const { d } = await openWizard();
    const input = typeName(d, "Alpha");
    input.dispatch("keydown", { key: "Enter", isComposing: false });
    assert.ok(findText(d, "陣營就是這張卡用哪個工具"));
    d.dispatch("keydown", { key: "Escape" });
    assert.ok(!dialog(), "Escape closed it");
  });

  await test("wizard: the species picker changes only the look and says so", async () => {
    const { ctx, d } = await openWizard();
    assert.ok(findText(d, "種族只換外觀，不影響能力。"));
    const fox = byData(d, "data-species", "fox")[0];
    fox.dispatch("click");
    assert.strictEqual(byData(dialog(), "data-species", "fox")[0].getAttribute("aria-pressed"), "true");
    assert.strictEqual(byData(dialog(), "data-species", "auto")[0].getAttribute("aria-pressed"), "false");
    assert.ok(ctx);
  });

  await test("wizard: same name shows a hint beside the field and never blocks saving", async () => {
    const { posts, d } = await openWizard([mkProfile("p-1", "CEO", "claude", ALL_DENY)]);
    typeName(d, "ceo");
    const hint = byData(d, "data-cw", "same-name")[0];
    assert.ok(findText(hint, "已經有一張叫「CEO」的卡"));
    btnByText(d, "下一步").dispatch("click");
    btnByText(d, "下一步").dispatch("click");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.strictEqual(posts.length, 1);
    assert.strictEqual(posts[0].name, "ceo");
  });

  const CHECK = "GET /api/agent-builder/intent-check?";
  const writeDenyBlockers = [{ code: "readonly_unverified", message: "這張角色卡的啟動組合尚未驗證唯讀模式；不會退化成可寫模式" }];
  const selectOf = (label) => walk(dialog()).find((n) => n.tag === "select" && n.getAttribute("aria-label") === label);
  const setIntent = (label, value) => { const sel = selectOf(label); sel.value = value; sel.dispatch("change"); };

  await test("wizard step 2 (R10): a new card starts from the verified combination marked 建議，可改, with both notes beside it, and asks nothing", async () => {
    const { posts, d } = await openWizard();
    typeName(d, "Planner one");
    btnByText(d, "下一步").dispatch("click");
    let cur = dialog();
    const chipsOf = (node) => textOf(byData(node, "data-cw", "intent-summary")[0]);
    // no position: the verified set, and it is a suggestion
    assert.ok(byData(cur, "data-cw", "suggested").length === 1 && findText(cur, "建議，可改"));
    let chips = chipsOf(cur);
    assert.ok(chips.includes("讀取檔案・允許") && chips.includes("編輯寫入・允許") && chips.includes("執行測試・允許") && chips.includes("部署上線・拒絕"), chips);
    assert.ok(findText(cur, "不代表 VBear 已經限制這個程式的真實能力"), "the R3 sentence is always beside the intents");
    assert.ok(findText(byData(cur, "data-cw", "launch-note")[0],
      "目前 VBear 能啟動的只有這一組權限。想讓規劃者或審查者不改檔案，VBear 現在無法強制，請在任務卡的目標裡寫清楚。"));
    const note = byData(cur, "data-cw", "intent-note")[0], launch = byData(cur, "data-cw", "launch-note")[0];
    const order = walk(cur); assert.ok(order.indexOf(note) < order.indexOf(launch), "the launch sentence comes after the R3 sentence");
    assert.ok(byData(cur, "data-cw", "intent-check")[0].hasAttribute("hidden"), "the verified combination needs no warning");
    assert.ok(!fetchCalls.some((c) => c.url.includes("intent-check")), "and nothing was asked");
    for (const position of ["planner", "executor", "reviewer"]) {
      byData(dialog(), "data-position", position)[0].dispatch("click");
      cur = dialog();
      assert.ok(byData(cur, "data-cw", "suggested").length === 1);
      assert.strictEqual(chipsOf(cur), chips, position);
    }
    assert.ok(!findText(cur, "還沒決定"), "the wizard does not produce an undecided intent");
    btnByText(cur, "下一步").dispatch("click");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.deepStrictEqual(posts[0].permission_intents, VERIFIED);
    assert.ok(!fetchCalls.some((c) => c.url.includes("intent-check")));
  });

  await test("wizard step 2 (R10): a hand-made combination is kept on a position change, asks the server why it cannot go, and says so on the spot", async () => {
    const { posts, d } = await openWizard([], catalog, {
      [CHECK + "read=allow&write=deny&test=allow&deploy=deny"]: () => jsonResponse({ ok: true, can_launch: false, blockers: writeDenyBlockers }) });
    typeName(d, "Hand made");
    btnByText(d, "下一步").dispatch("click");
    byData(dialog(), "data-position", "planner")[0].dispatch("click");
    setIntent("編輯寫入", "deny");
    await tick();
    assert.ok(byData(dialog(), "data-cw", "suggested").length === 0, "no longer the suggestion once it was changed");
    const box = byData(dialog(), "data-cw", "intent-check")[0];
    assert.ok(!box.hasAttribute("hidden"));
    assert.ok(findText(box, "這個組合目前不能出發"), "the headline");
    assert.ok(findText(box, writeDenyBlockers[0].message), "the server's own reason, not a page copy");
    assert.strictEqual(fetchCalls.filter((c) => c.url.includes("intent-check")).length, 1);
    assert.ok(fetchCalls.find((c) => c.url.includes("intent-check")).url.endsWith("read=allow&write=deny&test=allow&deploy=deny"));
    byData(dialog(), "data-position", "reviewer")[0].dispatch("click");
    assert.strictEqual(selectOf("編輯寫入").value, "deny", "not overwritten");
    assert.ok(findText(byData(dialog(), "data-cw", "intent-check")[0], writeDenyBlockers[0].message), "still there after the redraw");
    assert.strictEqual(fetchCalls.filter((c) => c.url.includes("intent-check")).length, 1, "the answer for a combination is remembered");
    const apply = byData(dialog(), "data-cw", "apply-suggestion")[0];
    assert.ok(apply, "the suggestion is offered");
    apply.dispatch("click");
    assert.strictEqual(selectOf("編輯寫入").value, "allow");
    assert.ok(byData(dialog(), "data-cw", "intent-check")[0].hasAttribute("hidden"), "back on the verified combination: no warning");
    btnByText(dialog(), "下一步").dispatch("click");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.deepStrictEqual(posts[0].permission_intents, VERIFIED);
  });

  await test("wizard step 2 (R10): while the question is open it says so; an answer that cannot be read says the pass decides; no reasons means no warning", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const { d } = await openWizard([], catalog, {
      [CHECK + "read=allow&write=allow&test=deny&deploy=deny"]: async () => { await gate; return jsonResponse({ ok: true, can_launch: false, blockers: [{ code: "test_deny_unenforceable", message: "x" }] }); },
      [CHECK + "read=deny&write=allow&test=allow&deploy=deny"]: () => { throw new Error("offline"); },
      [CHECK + "read=allow&write=allow&test=allow&deploy=allow"]: () => jsonResponse({ ok: true, can_launch: true, blockers: [] }) });
    typeName(d, "Q");
    btnByText(d, "下一步").dispatch("click");
    setIntent("執行測試", "deny");
    assert.ok(findText(byData(dialog(), "data-cw", "intent-check")[0], "檢查這個組合能不能出發"), "while asking");
    release(); await tick(4);
    assert.ok(findText(byData(dialog(), "data-cw", "intent-check")[0], "這個組合目前不能出發"));
    setIntent("執行測試", "allow");
    setIntent("讀取檔案", "deny");
    await tick(4);
    assert.ok(findText(byData(dialog(), "data-cw", "intent-check")[0], "讀不到這個組合的檢查，實際能不能出發以出發通行證為準。"));
    setIntent("讀取檔案", "allow");
    setIntent("部署上線", "allow");
    await tick(4);
    assert.ok(byData(dialog(), "data-cw", "intent-check")[0].hasAttribute("hidden"), "no reasons, no warning");
  });

  await test("wizard (R10): editing a card keeps its own intents, not marked as a suggestion, and the check speaks for them", async () => {
    const mine = mkProfile("p-1", "Mine", "claude", ALL_DENY);
    await openPool([mine], catalog, {
      [CHECK + "read=deny&write=deny&test=deny&deploy=deny"]: () => jsonResponse({ ok: true, can_launch: false, blockers: [
        { code: "read_deny_unenforceable", message: "無法強制禁止讀取：讀取範圍沒有被隔離" },
        { code: "readonly_unverified", message: writeDenyBlockers[0].message }] }) });
    byData(main, "data-pcard", "edit")[0].dispatch("click");
    await tick();
    btnByText(dialog(), "下一步").dispatch("click");
    await tick(4);
    const d = dialog();
    assert.ok(byData(d, "data-cw", "suggested").length === 0);
    assert.strictEqual(selectOf("編輯寫入").value, "deny");
    const box = byData(d, "data-cw", "intent-check")[0];
    assert.ok(findText(box, "這個組合目前不能出發") && findText(box, "無法強制禁止讀取") && findText(box, writeDenyBlockers[0].message));
  });

  await test("wizard step 2: the profession label and Model ID sit in 進階, with the new explanation", async () => {
    const { d } = await openWizard();
    typeName(d, "X");
    btnByText(d, "下一步").dispatch("click");
    const adv = byData(dialog(), "data-cw", "advanced")[0];
    assert.strictEqual(adv.tag, "details");
    assert.ok(!adv.hasAttribute("open"));
    assert.ok(findText(adv, "職業標籤") && findText(adv, "你電腦裡現成的角色範本，可以不選，只是標籤") && findText(adv, "Model ID"));
  });

  await test("wizard step 3: skill cards in a grid, one click inserts; the other tool's cards are greyed with the reason", async () => {
    const { posts, d } = await openWizard();
    typeName(d, "Skilled");
    btnByText(d, "下一步").dispatch("click");
    btnByText(dialog(), "下一步").dispatch("click");
    const cur = dialog();
    assert.ok(findText(cur, "這次的安全啟動不會載入它們"));
    const sk = (id) => byData(dialog(), "data-skill", id)[0];
    assert.strictEqual(sk("s-c").getAttribute("aria-disabled"), null);
    assert.strictEqual(sk("s-x").getAttribute("aria-disabled"), "true");
    assert.ok(findText(sk("s-x"), "Claude Code 不會讀這張卡"), "claude card: a codex skill says why");
    assert.strictEqual(sk("s-s").getAttribute("aria-disabled"), null);
    sk("s-x").dispatch("click");
    assert.strictEqual(sk("s-x").getAttribute("aria-pressed"), "false", "an incompatible card cannot be inserted");
    sk("s-c").dispatch("click"); sk("s-s").dispatch("click");
    assert.strictEqual(sk("s-c").getAttribute("aria-pressed"), "true");
    assert.ok(findText(byData(dialog(), "data-cw", "chosen")[0], "claude-skill") && findText(dialog(), "已插入（2）"));
    sk("s-c").dispatch("click");
    assert.ok(findText(dialog(), "已插入（1）"));
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.deepStrictEqual(posts[0].equipped_skill_ids, ["s-s"]);
  });

  await test("wizard: changing the tool drops the skill cards the new tool does not read, and says so", async () => {
    const { posts, d } = await openWizard();
    typeName(d, "Switch");
    btnByText(d, "下一步").dispatch("click");
    btnByText(dialog(), "下一步").dispatch("click");
    byData(dialog(), "data-skill", "s-c")[0].dispatch("click");
    byData(dialog(), "data-skill", "s-s")[0].dispatch("click");
    btnByText(dialog(), "上一步").dispatch("click");
    byData(dialog(), "data-tool", "codex")[0].dispatch("click");
    btnByText(dialog(), "下一步").dispatch("click");
    assert.ok(findText(dialog(), "換了陣營，已移除 1 張這個陣營不會讀的技能卡。"));
    assert.ok(findText(dialog(), "已插入（1）"));
    assert.strictEqual(byData(dialog(), "data-skill", "s-x")[0].getAttribute("aria-disabled"), null, "now the codex skill fits");
    assert.strictEqual(byData(dialog(), "data-skill", "s-c")[0].getAttribute("aria-disabled"), "true");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.strictEqual(posts[0].model.tool, "codex");
    assert.deepStrictEqual(posts[0].equipped_skill_ids, ["s-s"]);
  });

  await test("wizard: a failed save keeps the dialog and the answers, and says why", async () => {
    const { d } = await openWizard([], catalog, { "POST /api/agent-profiles": () => jsonResponse({ error: "角色卡已達上限 500 筆" }, 400) });
    typeName(d, "Too many");
    btnByText(d, "下一步").dispatch("click");
    btnByText(dialog(), "下一步").dispatch("click");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.ok(dialog(), "still open");
    assert.ok(btnByText(dialog(), "建立") && !btnByText(dialog(), "建立").disabled);
    assert.ok(idRegistry.get("toast").textContent.includes("建立失敗：角色卡已達上限 500 筆"), "the reason is told");
  });

  await test("editing an existing card with an undecided intent shows it, and 現在決定 opens step 2 with the intents open", async () => {
    const ctx = await openPool([mkProfile("p-2", "Reviewer", "codex", { read: "allow", write: "unspecified", test: "deny", deploy: "deny" })]);
    byData(main, "data-pcard", "decide")[0].dispatch("click");
    await tick();
    const d = dialog();
    assert.ok(findText(d, "陣營就是這張卡用哪個工具"), "step 2");
    assert.ok(findText(d, "有權限意圖還沒決定；出發前要先決定。"));
    assert.ok(findText(d, "編輯寫入・還沒決定"));
    const intents = byData(d, "data-cw", "intents")[0];
    assert.ok(intents.hasAttribute("open"));
    assert.ok(btnByText(d, "儲存修改"), "editing can save on any step");
    // a position chosen on an existing card does not overwrite its intents; the suggestion is only offered
    byData(d, "data-position", "planner")[0].dispatch("click");
    const after = walk(dialog()).find((n) => n.tag === "select" && n.getAttribute("aria-label") === "編輯寫入");
    assert.strictEqual(after.value, "unspecified");
    assert.ok(byData(dialog(), "data-cw", "apply-suggestion").length === 1);
    assert.ok(ctx);
  });

  // ---- the starter deck ----
  await test("starter deck: lists the three cards, the names are editable, confirm creates the checked ones through the ordinary save", async () => {
    const posts = [];
    const ctx = await openPool([], catalog, {
      "POST /api/agent-profiles": (url, options) => {
        const b = JSON.parse(options.body); posts.push(b);
        return jsonResponse({ ok: true, profile: mkProfile(`p-${posts.length}`, b.name, b.model.tool, b.permission_intents) });
      } });
    btnByText(main, "用起手牌組開始").dispatch("click");
    await tick();
    const d = dialog();
    const rows = walk(d).filter((n) => n.getAttribute && n.getAttribute("data-deck"));
    assert.deepStrictEqual(rows.map((r) => r.getAttribute("data-deck")), ["planner", "executor", "reviewer"]);
    assert.ok(findText(d, "規劃") && findText(d, "執行") && findText(d, "審查"));
    assert.ok(findText(d, "不代表 VBear 已經限制這個程式的真實能力"));
    const names = walk(d).filter((n) => n.tag === "input" && n.getAttribute("type") === "text");
    names[1].value = "我的工匠"; names[1].dispatch("input");
    assert.ok(btnByText(d, "建立 3 張角色卡"));
    btnByText(d, "建立 3 張角色卡").dispatch("click");
    await tick(8);
    assert.deepStrictEqual(posts.map((p) => p.name), ["CEO", "我的工匠", "審查員"]);
    assert.deepStrictEqual(posts.map((p) => p.model.tool), ["claude", "claude", "codex"]);
    for (const p of posts) assert.deepStrictEqual(p.permission_intents, VERIFIED, "R10: every starter card carries the verified combination");
    assert.ok(posts.every((p) => p.enabled === true && p.profession_role_id === null && p.equipped_skill_ids.length === 0));
    for (const p of posts) for (const v of Object.values(p.permission_intents)) assert.ok(v === "allow" || v === "deny");
    assert.strictEqual(JSON.parse(ctx.__ls.get("sid:card.position.p-1")), "planner");
    assert.strictEqual(JSON.parse(ctx.__ls.get("sid:card.position.p-3")), "reviewer");
    assert.ok(!dialog(), "closed after the deck was made");
  });

  await test("starter deck: no Codex found means the reviewer is unticked with the reason; ticking it back is allowed", async () => {
    const posts = [];
    await openPool([], { ...catalog, codex_installed: false }, {
      "POST /api/agent-profiles": (url, options) => {
        const b = JSON.parse(options.body); posts.push(b);
        return jsonResponse({ ok: true, profile: mkProfile(`p-${posts.length}`, b.name, b.model.tool, b.permission_intents) });
      } });
    btnByText(main, "用起手牌組開始").dispatch("click");
    await tick();
    const d = dialog();
    const rev = byData(d, "data-deck", "reviewer")[0];
    assert.ok(findText(rev, "這台電腦找不到 Codex") && findText(rev, "審查位需要和工匠不同陣營的卡"));
    const box = walk(rev).find((n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
    assert.strictEqual(box.hasAttribute("checked"), false);
    assert.ok(btnByText(d, "建立 2 張角色卡"));
    btnByText(d, "建立 2 張角色卡").dispatch("click");
    await tick(8);
    assert.deepStrictEqual(posts.map((p) => p.model.tool), ["claude", "claude"]);
  });

  await test("starter deck: a failure in the middle says what was made and what failed", async () => {
    let n = 0;
    await openPool([], catalog, {
      "POST /api/agent-profiles": (url, options) => {
        const b = JSON.parse(options.body); n += 1;
        if (n === 2) return jsonResponse({ error: "名稱重複的測試錯誤" }, 400);
        return jsonResponse({ ok: true, profile: mkProfile(`p-${n}`, b.name, b.model.tool, b.permission_intents) });
      } });
    btnByText(main, "用起手牌組開始").dispatch("click");
    await tick();
    btnByText(dialog(), "建立 3 張角色卡").dispatch("click");
    await tick(8);
    const d = dialog();
    assert.ok(d, "the dialog stays");
    assert.ok(findText(d, "已建立 1 張；") && findText(d, "「工匠」建立失敗：") && findText(d, "名稱重複的測試錯誤"));
    assert.ok(btnByText(d, "建立 2 張角色卡"), "what is left can be retried without making the first one twice");
  });

  // ---- vocabulary and honesty ----
  const FORBIDDEN = ["Agent Profile", "AgentRole", "Agent Builder", "Permission Intents", "Agent 團隊", "Equipped Skill", "已選技能"];
  const hasProfileWord = (t) => /\bProfile\b/.test(t);
  await test("vocabulary: the pool, the wizard (every step) and the starter deck use the card words", async () => {
    const profiles = [mkProfile("p-1", "Mine", "claude", { read: "allow", write: "unspecified", test: "deny", deploy: "deny" }, { equipped_skill_ids: ["s-c", "gone"], _unresolved: { profession: false, skills: ["gone"] } })];
    const ctx = await openPool(profiles);
    const pages = [textOf(main)];
    btnByText(main, "＋ 新角色卡").dispatch("click"); await tick();
    let d = dialog(); typeName(d, "N");
    pages.push(textOf(d)); btnByText(d, "下一步").dispatch("click");
    pages.push(textOf(dialog())); btnByText(dialog(), "下一步").dispatch("click");
    pages.push(textOf(dialog()));
    dialog().dispatch("keydown", { key: "Escape" });
    await ctx.viewTeam();
    btnByText(main, "編輯").dispatch("click"); await tick();
    pages.push(textOf(dialog()));
    dialog().dispatch("keydown", { key: "Escape" });
    const ctx2 = await openPool([]);
    btnByText(main, "用起手牌組開始").dispatch("click"); await tick();
    pages.push(textOf(dialog()));
    const all = pages.join("\n");
    for (const w of FORBIDDEN) assert.ok(!all.includes(w), `forbidden word on screen: ${w}`);
    assert.ok(!hasProfileWord(all), "Profile");
    for (const w of ["角色卡", "技能卡", "陣營", "權限意圖", "職業標籤"]) assert.ok(all.includes(w), `missing word: ${w}`);
    assert.ok(ctx2);
  });

  await test("vocabulary: the workbench's role tab uses 角色卡 and the same wizard", async () => {
    const ctx = freshContext(baseHandlers([mkProfile("p-1", "Mine", "claude", ALL_DENY)]));
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    const tab = walk(main).find((n) => n.tag === "button" && (n.textContent || "").trim() === "角色");
    tab.dispatch("click"); await tick();
    const right = walk(main).find((n) => n.className && n.className.includes("wb-right"));
    const t = textOf(right);
    for (const w of FORBIDDEN) assert.ok(!t.includes(w), w);
    assert.ok(!hasProfileWord(t));
    const create = btnByText(right, "＋ 新角色卡");
    assert.ok(create);
    create.dispatch("click"); await tick();
    assert.ok(findText(dialog(), "新角色卡") && walk(dialog()).some((n) => n.className === "modal-box cw-box"), "the same wizard");
  });

  await test("source scan: no retired word in a string literal, no innerHTML call, no emoji in the card pool code", () => {
    const lines = source.split("\n");
    const code = lines.filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l));
    const literalLines = code.filter((l) => /["'`]/.test(l));
    for (const w of ["Agent 團隊", "Agent Builder", "Permission Intents", "AgentRole"]) {
      assert.ok(!literalLines.some((l) => l.includes(w)), `retired word in code: ${w}`);
    }
    // "Agent Profile" and "Profile" inside a quoted Chinese sentence on screen
    const quoted = literalLines.filter((l) => /["'`][^"'`]*\bProfile\b[^"'`]*["'`]/.test(l) && /[\u4e00-\u9fff]/.test(l));
    assert.deepStrictEqual(quoted, [], "a Chinese sentence with the word Profile");
    assert.ok(!code.some((l) => /\.innerHTML\s*=|insertAdjacentHTML|outerHTML\s*=/.test(l)), "innerHTML");
    const start = source.indexOf("// ---------- the card pool (design card-play");
    const end = source.indexOf("const STATUS_ORDER = ");
    const poolCode = source.slice(start, end);
    assert.ok(start > 0 && end > start);
    assert.ok(!/\p{Extended_Pictographic}/u.test(poolCode), "emoji in the card pool code");
    assert.ok(!/https?:\/\//.test(poolCode.split("http://www.w3.org/2000/svg").join("")), "external resource (the SVG namespace is a name, not a load)");
    const html = fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8");
    assert.ok(html.includes("</span>角色卡池</a>") && !html.includes("Agent 團隊"));
  });

  await test("honesty: the pool shows no stats, levels, rarity, stars or draws; no attendance; the intents carry their disclaimer", async () => {
    const profiles = [mkProfile("p-1", "Mine", "claude", ALL_DENY, { equipped_skill_ids: ["s-c"] }), mkProfile("p-2", "Other", "codex", ALL_DENY)];
    await openPool(profiles);
    const t = textOf(main);
    for (const w of ["稀有", "星數", "星等", "抽卡", "隨機", "攻擊力", "防禦力", "等級", "Lv.", "★", "☆", "出勤中"]) {
      assert.ok(!t.includes(w), `forbidden on the pool page: ${w}`);
    }
    // the card face never shows a permission on its own: the intents are on the back, beside their disclaimer
    for (const card of walk(main).filter((n) => n.tag === "article" && n.getAttribute("data-profile-id"))) {
      const face = (which) => walk(card).find((n) => n.getAttribute && n.getAttribute("data-face") === which && n.tag === "div");
      assert.ok(!/(讀取檔案|編輯寫入|執行測試|部署上線|寫入|讀取)[・：](允許|拒絕|還沒決定)/.test(textOf(face("front"))), "no single intent on the card face");
      assert.ok(findText(face("back"), "只是記錄，不是授權") && findText(face("back"), "不代表 VBear 已經限制"), "the back carries the disclaimer");
    }
    // the slots say the cards are kept, not loaded; none is in effect
    assert.ok(findText(main, "技能卡 1 張") && findText(main, "收藏中") && findText(main, "這次的安全啟動不會載入"));
    assert.ok(!findText(main, "生效中"), "no card claims to be in effect");
    assert.strictEqual(vm.runInContext("CARD_INTENT_NOTE", pure), "權限意圖是隊伍分工的標記，不代表 VBear 已經限制這個程式的真實能力；真正的限制，看出發通行證上的盾牌。");
  });

  await test("CSS: the wizard keeps its footer in view and honours reduced motion", () => {
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    assert.ok(/\.cw-foot\s*\{[^}]*position:\s*sticky[^}]*bottom:\s*0/.test(css));
    assert.ok(/\.cw-body\s*\{[^}]*overflow-y:\s*auto/.test(css));
    assert.ok(/prefers-reduced-motion[^{]*\{[^}]*\.cw-choice/.test(css));
    assert.ok(!/@import|url\(\s*["']?https?:/.test(css), "no external resource in the CSS");
  });

  // ======== P2 (design card-play 3.2, 3.4, R1): the role card, its slots, the art ========================================

  const cardOf = (id) => walk(main).find((n) => n.tag === "article" && n.getAttribute("data-profile-id") === id);
  const faceOf = (card, which) => walk(card).find((n) => n.tag === "div" && n.getAttribute("data-face") === which);
  const slotsOf = (card) => walk(card).filter((n) => n.tag === "li" && ["collected", "active"].includes(n.getAttribute("data-slot")));
  const okState = (data) => ({ state: "ok", data });
  const loadoutWith = (items, over = {}) => ({ blockers: [], profession: { state: "none", role_id: null },
    skills: { all_inactive: true, items }, ...over });

  await test("cardSlotState: solid only for will_load === true, for that very skill; words and other values never decide", () => {
    const rows = [
      [{ will_load: true }, "active"], [{ will_load: false }, "collected"], [{}, "collected"], [null, "collected"],
      [undefined, "collected"], [{ will_load: "true" }, "collected"], [{ will_load: 1 }, "collected"],
      [{ will_load: null }, "collected"], [{ effective: true }, "collected"], [{ state: "生效中" }, "collected"],
    ];
    for (const [item, want] of rows) assert.strictEqual(pure.cardSlotState(item), want, JSON.stringify(item));
    assert.deepStrictEqual({ ...vm.runInContext("CARD_SLOT_LABEL", pure) }, { collected: "收藏中", active: "生效中" });
  });

  await test("cardSlots: the profile's own list before the loadout, the loadout's rows after; all_inactive is read, not guessed", () => {
    const p = { equipped_skill_ids: ["s-c", "s-x"] };
    const before = pure.cardSlots(p, null, catalog);
    assert.strictEqual(before.loaded, false);
    assert.deepStrictEqual(before.rows.map((r) => [r.id, r.name, r.state]), [["s-c", "claude-skill", "collected"], ["s-x", "codex-skill", "collected"]]);
    assert.strictEqual(before.allInactive, null, "nothing is claimed before the loadout is read");
    assert.strictEqual(pure.cardSlots(p, { state: "loading" }, catalog).loaded, false);
    assert.strictEqual(pure.cardSlots(p, { state: "error", error: "x" }, catalog).allInactive, null);
    const items = [{ skill_id: "s-c", state: "in_index", name: "a", will_load: false }, { skill_id: "gone", state: "not_in_index", will_load: false }];
    const after = pure.cardSlots(p, okState(loadoutWith(items)), catalog);
    assert.strictEqual(after.loaded, true);
    assert.deepStrictEqual(after.rows.map((r) => [r.id, r.state, r.missing]), [["s-c", "collected", false], ["gone", "collected", true]]);
    assert.strictEqual(after.allInactive, true);
    // one skill that will load: that slot is solid, and the section is no longer "all inactive" even if the flag says so
    const mixed = pure.cardSlots(p, okState(loadoutWith([{ skill_id: "s-c", state: "in_index", will_load: true }, items[1]])), catalog);
    assert.deepStrictEqual(mixed.rows.map((r) => r.state), ["active", "collected"]);
    assert.strictEqual(mixed.allInactive, false);
    assert.strictEqual(pure.cardSlots(p, okState({ skills: { items } }), catalog).allInactive, null, "no flag: no claim");
    assert.strictEqual(pure.cardSlots(p, okState({ skills: { all_inactive: "yes", items } }), catalog).allInactive, null, "a flag that is not a boolean is no flag");
    assert.strictEqual(pure.cardSlots({}, null, null).rows.length, 0);
  });

  await test("cardDeparture: yellow for undecided intents; green only with a loadout that was read and lists no reason", () => {
    const decided = { permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } };
    const undecided = { permission_intents: { read: "allow", write: "unspecified", test: "allow", deploy: "deny" } };
    const rows = [
      ["undecided, no loadout", undecided, null, "yellow"],
      ["undecided, blockers listed", undecided, okState({ blockers: [{ code: "x", message: "m" }] }), "yellow"],
      ["decided, no loadout", decided, null, "checking"],
      ["decided, loading", decided, { state: "loading" }, "checking"],
      ["decided, error", decided, { state: "error", error: "e" }, "unknown"],
      ["decided, ok without data", decided, { state: "ok" }, "unknown"],
      ["decided, blockers not a list", decided, okState({ blockers: "none" }), "unknown"],
      ["decided, blockers missing", decided, okState({}), "unknown"],
      ["decided, no blockers", decided, okState({ blockers: [] }), "green"],
      ["decided, one blocker", decided, okState({ blockers: [{ code: "c", message: "不能出發的原因" }] }), "blocked"],
      ["decided, blocker without text", decided, okState({ blockers: [{ code: "c" }] }), "blocked"],
      // R11: only codex_ reasons make the neutral fifth state; any other reason keeps the red
      ["only a codex_ reason", decided, okState({ blockers: [{ code: "codex_interactive_flags_unsupported", message: "m" }] }), "codex"],
      ["only the two codex_ reasons", decided, okState({ blockers: [{ code: "codex_interactive_flags_unsupported", message: "a" }, { code: "codex_evidence_missing", message: "b" }] }), "codex"],
      ["a codex_ reason and another", decided, okState({ blockers: [{ code: "codex_evidence_missing", message: "a" }, { code: "readonly_unverified", message: "b" }] }), "blocked"],
      ["another reason first, then codex_", decided, okState({ blockers: [{ code: "commit_not_enforceable", message: "a" }, { code: "codex_evidence_missing", message: "b" }] }), "blocked"],
      ["a code that only contains codex_", decided, okState({ blockers: [{ code: "not_codex_x", message: "a" }] }), "blocked"],
      ["a reason with no code", decided, okState({ blockers: [{ message: "a" }] }), "blocked"],
      ["a reason whose code is not text", decided, okState({ blockers: [{ code: 7, message: "a" }, { code: "codex_evidence_missing" }] }), "blocked"],
      ["undecided beats the codex state", undecided, okState({ blockers: [{ code: "codex_evidence_missing", message: "a" }] }), "yellow"],
    ];
    for (const [label, p, ld, want] of rows) assert.strictEqual(pure.cardDeparture(p, ld).state, want, label);
    assert.deepStrictEqual([...pure.cardDeparture(decided, okState({ blockers: [{ message: "A" }, { message: "B" }] })).reasons], ["A", "B"]);
    assert.deepStrictEqual([...pure.cardDeparture(decided, okState({ blockers: [{ code: "c" }] })).reasons], ["原因未提供"]);
    assert.strictEqual(pure.cardDeparture(decided, okState({ blockers: [] })).text, "可以出發（權限意圖都已決定）");
    const codex = pure.cardDeparture(decided, okState({ blockers: [{ code: "codex_interactive_flags_unsupported", message: "A" }, { code: "codex_evidence_missing", message: "B" }] }));
    assert.strictEqual(codex.text, "不能直接開終端");
    assert.strictEqual(codex.note, "放在任務卡的審查位時，自動模式會派它在暫存副本裡審查；也可以手動記錄審查結果。");
    assert.deepStrictEqual([...codex.reasons], ["A", "B"], "the original reasons are kept for the back");
    for (const r of rows) assert.ok(!/安全|已限制/.test(pure.cardDeparture(r[1], r[2]).text), "the light never says safe or limited");
  });

  await test("the card on the pool page: dashed slots for will_load false, solid for true, whatever the section's words say", async () => {
    const profiles = [mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" }, { equipped_skill_ids: ["s-c", "s-s"] })];
    const items = [{ skill_id: "s-c", state: "in_index", name: "claude-skill", will_load: false },
      { skill_id: "s-s", state: "in_index", name: "shared-skill", will_load: true }];
    await openPool(profiles, catalog, { "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutWith(items, {
      skills: { title: "全部都是收藏中", all_inactive: false, items } })) });
    const card = cardOf("p-1");
    assert.deepStrictEqual(slotsOf(card).map((n) => [n.getAttribute("data-slot"), n.className.includes("rcard-slot-active")]), [["collected", false], ["active", true]]);
    assert.ok(findText(faceOf(card, "front"), "生效中") && findText(faceOf(card, "front"), "收藏中"));
    assert.ok(!findText(card, "這次的安全啟動不會載入"), "no blanket 'not loaded' line when one skill will load");
    // the words of the title are not what decides: all slots dashed although the title says 生效中
    const items2 = items.map((x) => ({ ...x, will_load: false }));
    await openPool(profiles, catalog, { "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutWith(items2, {
      skills: { title: "技能卡（生效中）", all_inactive: true, items: items2 } })) });
    const card2 = cardOf("p-1");
    assert.ok(slotsOf(card2).length === 2 && slotsOf(card2).every((n) => n.getAttribute("data-slot") === "collected" && !n.className.includes("rcard-slot-active")));
    assert.ok(findText(card2, "這次的安全啟動不會載入"));
    // a card with no skill says so, and a long list shows six and counts the rest
    const many = Array.from({ length: 9 }, (_, i) => `k-${i}`);
    await openPool([mkProfile("p-1", "None", "claude", ALL_DENY), mkProfile("p-2", "Many", "claude", ALL_DENY, { equipped_skill_ids: many })]);
    assert.ok(findText(cardOf("p-1"), "沒有插技能卡"));
    assert.strictEqual(slotsOf(cardOf("p-2")).length, 6);
    assert.ok(findText(cardOf("p-2"), "技能卡 9 張") && findText(cardOf("p-2"), "另有 3 張"));
  });

  await test("a card whose loadout lists a reason is not green: the front gives the first reason, the back all of them", async () => {
    const p = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    const q = mkProfile("p-2", "Fine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    await openPool([p, q], catalog, { "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutBody(p, {
      blockers: [{ code: "a", message: "第一個原因" }, { code: "b", message: "第二個原因" }], blockers_note: "假設已勾選" })) });
    const light = (id) => byData(cardOf(id), "data-pcard", "light")[0];
    assert.strictEqual(light("p-1").getAttribute("data-light"), "blocked");
    assert.ok(findText(faceOf(cardOf("p-1"), "front"), "目前不能出發") && findText(faceOf(cardOf("p-1"), "front"), "第一個原因"));
    assert.ok(!findText(faceOf(cardOf("p-1"), "front"), "第二個原因") && findText(faceOf(cardOf("p-1"), "front"), "另有 1 項，翻到背面看"));
    const reasons = byData(cardOf("p-1"), "data-rc", "blockers")[0];
    assert.ok(!reasons.hasAttribute("hidden") && findText(reasons, "第一個原因") && findText(reasons, "第二個原因") && findText(reasons, "假設已勾選"));
    assert.strictEqual(light("p-2").getAttribute("data-light"), "green");
    assert.ok(byData(cardOf("p-2"), "data-rc", "blockers")[0].hasAttribute("hidden"), "nothing to list: the block is hidden");
    for (const l of byData(main, "data-pcard", "light")) assert.ok(!/安全|已限制/.test(textOf(l)), "no light says safe or limited");
  });

  await test("a Codex card whose only reasons are codex_ shows the neutral light, not the red; one other reason brings the red back (R11)", async () => {
    const intents = { read: "allow", write: "allow", test: "allow", deploy: "deny" };
    const cx = [{ code: "codex_interactive_flags_unsupported", message: "固定版 Codex CLI 互動 TUI 不支援" }, { code: "codex_evidence_missing", message: "Codex 驗收尚未完成" }];
    const p = mkProfile("p-1", "Reviewer", "codex", intents), q = mkProfile("p-2", "Mixed", "codex", intents), r = mkProfile("p-3", "Claude", "claude", intents);
    await openPool([p, q, r], catalog, {
      "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutBody(p, { blockers: cx })),
      "GET /api/agent-profiles/p-2/loadout": () => jsonResponse(loadoutBody(q, { blockers: [...cx, { code: "readonly_unverified", message: "尚未驗證唯讀" }] })) });
    const light = (id) => byData(cardOf(id), "data-pcard", "light")[0];
    assert.strictEqual(light("p-1").getAttribute("data-light"), "codex");
    assert.ok(light("p-1").className.includes("rcard-codex") && !light("p-1").className.includes("rcard-blocked"));
    const front = faceOf(cardOf("p-1"), "front");
    assert.ok(findText(front, "不能直接開終端"));
    assert.ok(findText(front, "放在任務卡的審查位時，自動模式會派它在暫存副本裡審查；也可以手動記錄審查結果。"));
    assert.ok(!findText(front, "目前不能出發"), "not the red words");
    const reasons = byData(cardOf("p-1"), "data-rc", "blockers")[0];
    assert.ok(!reasons.hasAttribute("hidden") && findText(reasons, "固定版 Codex CLI 互動 TUI 不支援") && findText(reasons, "Codex 驗收尚未完成"), "the back lists the original reasons");
    assert.ok(findText(reasons, "不能直接開終端的原因"));
    assert.strictEqual(light("p-2").getAttribute("data-light"), "blocked");
    assert.ok(findText(faceOf(cardOf("p-2"), "front"), "目前不能出發") && !findText(faceOf(cardOf("p-2"), "front"), "不能直接開終端"));
    assert.strictEqual(light("p-3").getAttribute("data-light"), "green");
    for (const l of byData(main, "data-pcard", "light")) assert.ok(!/安全|已限制/.test(textOf(l)));
  });

  // ---- P7: the pass line on a card, the picker's Chinese ----------------------------------------------------------------
  const ARMOR_LEVEL = { enforced: "強制（限已測路徑、版本與執行層）", partial: "部分強制", unverified: "未驗證（此 Claude Code 版本尚未實測）",
    unknown: "未知", intent: "僅意圖", unrestricted: "未限制", notGranted: "不授予" };
  const armorOf = (write, commit = ARMOR_LEVEL.unrestricted, over = {}) => ({ applicable: true, items: [
    { name: "Read", level: ARMOR_LEVEL.intent }, { name: "Write", level: write }, { name: "Commit", level: commit }, { name: "Network", level: ARMOR_LEVEL.enforced }], ...over });

  await test("P7 #13 cardPassLine: made from the armor items; never more hopeful than the pass; unreadable armor gives no line", () => {
    const line = (write, commit) => pure.cardPassLine({ state: "ok", data: { armor: armorOf(write, commit) } });
    const rows = [
      [ARMOR_LEVEL.enforced, "出發後可以改檔案（限工作資料夾）；擋不住存下版本紀錄；詳情看出發通行證"],
      [ARMOR_LEVEL.partial, "出發後可以改檔案（範圍只部分擋住）；擋不住存下版本紀錄；詳情看出發通行證"],
      [ARMOR_LEVEL.unverified, "出發後可以改檔案（範圍限制還沒實測）；擋不住存下版本紀錄；詳情看出發通行證"],
      [ARMOR_LEVEL.unknown, "出發後可以改檔案（範圍不明）；擋不住存下版本紀錄；詳情看出發通行證"],
      [ARMOR_LEVEL.notGranted, "出發後可以改檔案（範圍不明）；擋不住存下版本紀錄；詳情看出發通行證"],
      [ARMOR_LEVEL.intent, "出發後可以改檔案（範圍沒有被擋住）；擋不住存下版本紀錄；詳情看出發通行證"],
      [ARMOR_LEVEL.unrestricted, "出發後可以改檔案（範圍沒有被擋住）；擋不住存下版本紀錄；詳情看出發通行證"],
      ["something new", "出發後可以改檔案（範圍不明）；擋不住存下版本紀錄；詳情看出發通行證"],
    ];
    for (const [level, want] of rows) assert.strictEqual(line(level), want, level);
    // only an enforced write may say the reach; commit is never said to be stopped, whatever its own level says
    for (const level of Object.values(ARMOR_LEVEL)) {
      const t = line(level, ARMOR_LEVEL.enforced);
      assert.ok(t.includes("擋不住存下版本紀錄") && !/安全|已限制/.test(t), level);
      assert.strictEqual(t.includes("限工作資料夾"), level === ARMOR_LEVEL.enforced, level);
    }
    // the same table the pass front uses decides the reach
    for (const level of Object.values(ARMOR_LEVEL)) {
      const kind = pure.passKind(level);
      assert.strictEqual(line(level).includes("限工作資料夾"), kind === "enforced");
    }
  });

  await test("P7 #13 cardPassLine: nothing when the armor cannot be read, does not apply, or lacks the two items", () => {
    const bad = [undefined, null, { state: "loading" }, { state: "error", error: "x" }, { state: "ok" }, { state: "ok", data: null },
      { state: "ok", data: {} }, { state: "ok", data: { armor: null } }, { state: "ok", data: { armor: { applicable: false, why: "x" } } },
      { state: "ok", data: { armor: { applicable: true } } }, { state: "ok", data: { armor: { applicable: true, items: "x" } } },
      { state: "ok", data: { armor: { applicable: true, items: [] } } },
      { state: "ok", data: { armor: { applicable: true, items: [{ name: "Write", level: ARMOR_LEVEL.enforced }] } } },
      { state: "ok", data: { armor: { applicable: true, items: [{ name: "Commit", level: ARMOR_LEVEL.unrestricted }] } } },
      { state: "ok", data: { armor: { applicable: true, items: [{ name: "Write" }, { name: "Commit", level: 5 }, null, "x"] } } }];
    for (const st of bad) assert.strictEqual(pure.cardPassLine(st), null, JSON.stringify(st));
  });

  await test("P10 A7 the back says 「往下捲動看更多」 only while there is more below, and not when it all fits or the front is showing", () => {
    const p = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    const card = pure.profileCard(p, { catalog, face: "back" });
    const back = byData(card.node, "data-face", "back")[0];
    const note = byData(card.node, "data-pcard", "more")[0];
    assert.ok(note, "the line is on the back");
    assert.strictEqual(note.textContent, "往下捲動看更多");
    const measure = (total, shown, top = 0) => { back.scrollHeight = total; back.clientHeight = shown; back.scrollTop = top; back.dispatch("scroll"); };
    measure(500, 500);
    assert.ok(note.hasAttribute("hidden"), "all of it fits: no line");
    measure(900, 560, 0);
    assert.ok(!note.hasAttribute("hidden"), "more below: the line");
    measure(900, 560, 200);
    assert.ok(!note.hasAttribute("hidden"), "still more below");
    measure(900, 560, 340);
    assert.ok(note.hasAttribute("hidden"), "scrolled to the end: the line goes away");
    // the front is showing: nothing is said about a back nobody sees
    measure(900, 560, 0);
    const front = pure.profileCard(p, { catalog, face: "front" });
    const fb = byData(front.node, "data-face", "back")[0];
    fb.scrollHeight = 900; fb.clientHeight = 560; fb.dispatch("scroll");
    assert.ok(byData(front.node, "data-pcard", "more")[0].hasAttribute("hidden"), "the front face is up");
    // the same words and the same measure as the import window's list; the line sits inside the scrolling back
    assert.ok(back.children.includes(note));
    assert.ok(/\.rcard-more \{[^}]*position: sticky/.test(fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8")), "the line stays at the bottom edge while the back scrolls");
  });

  await test("P7 #13 the card's front shows that line, made from its loadout, and hides it while unread or unreadable", () => {
    const p = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    const card = pure.profileCard(p, { catalog });
    const box = () => byData(card.node, "data-pcard", "pass-line")[0];
    assert.ok(box().hasAttribute("hidden"), "before the loadout arrives");
    assert.strictEqual(box().textContent, "");
    card.setLoadout(okState(loadoutBody(p, { armor: armorOf(ARMOR_LEVEL.enforced) })));
    assert.ok(!box().hasAttribute("hidden"));
    assert.strictEqual(box().textContent, "出發後可以改檔案（限工作資料夾）；擋不住存下版本紀錄；詳情看出發通行證");
    assert.ok(byData(card.node, "data-face", "front")[0] && walk(byData(card.node, "data-face", "front")[0]).includes(box()), "on the front");
    card.setLoadout(okState(loadoutBody(p, { armor: armorOf(ARMOR_LEVEL.unverified) })));
    assert.ok(box().textContent.includes("範圍限制還沒實測") && !box().textContent.includes("限工作資料夾"));
    card.setLoadout(okState(loadoutBody(p, { armor: { applicable: false, why: "x" } })));
    assert.ok(box().hasAttribute("hidden") && box().textContent === "");
    card.setLoadout({ state: "error", error: "x" });
    assert.ok(box().hasAttribute("hidden"));
  });

  await test("P7 #4 the back of a card calls the intents 「權限意圖（分工記號）」", () => {
    const p = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    const back = byData(pure.profileCard(p, { catalog, face: "back" }).node, "data-rc", "intents")[0];
    assert.strictEqual(walk(back).find((n) => n.tag === "h4").textContent, "權限意圖（分工記號）");
    assert.ok(findText(back, "只是記錄，不是授權。"));
  });

  await test("P7 #12 the skill picker: the Chinese 「what it does」 when there is a translation (過期 marked), the original behind 「看原文」, the English as it was when there is none", async () => {
    const entry = (zh) => ({ engine: "claude", model: "haiku", cli_version: "2.1.296", created_at: 1, name_zh: "甲", description_zh: zh });
    const cat = { ...catalog, skills: [...catalog.skills, { skill_id: "s-3", name: "gamma", invoke_name: "tool:gamma", tool: "shared", scope: "user", activation: "active", excerpt: "gamma desc" }] };
    const { d } = await openWizard([], cat, { "GET /api/translations": () => jsonResponse({
      entries: { "s-c": { state: "fresh", entry: entry("替程式變更做審查，並列出有風險的行，同時標出需要補測試的地方。") }, "s-x": { state: "stale", entry: entry("舊的翻譯。") } },
      counts: { fresh: 1, stale: 1, none: 1, orphan: 0 }, job: null, engine: "claude" }) });
    typeName(d, "Alpha");
    btnByText(d, "下一步").dispatch("click");
    btnByText(d, "下一步").dispatch("click");
    await tick(8);                           // translations the page had not read are read when the list opens
    const cell = (id) => byData(d, "data-skill-cell", id)[0];
    const fresh = cell("s-c");
    assert.strictEqual(byData(fresh, "data-cw", "skill-zh")[0].textContent, "替程式變更做審查，並列出有風險的行，同時標出需要補測試的地方。");
    assert.ok(findText(fresh, "機器翻譯") && !findText(fresh, "過期"));
    const orig = byData(fresh, "data-cw", "skill-orig")[0];
    assert.ok(orig && orig.tag === "details" && !orig.hasAttribute("open"), "folded");
    assert.strictEqual(orig.children[0].textContent, "看原文");
    assert.ok(textOf(orig).includes("for claude"));
    assert.ok(!walk(byData(fresh, "data-skill", "s-c")[0]).includes(orig), "the original is beside the card, not inside the button");
    const stale = cell("s-x");
    assert.ok(findText(stale, "過期") && byData(stale, "data-cw", "skill-zh")[0].textContent === "舊的翻譯。");
    assert.ok(byData(stale, "data-cw", "skill-orig")[0]);
    const none = cell("s-3");
    assert.strictEqual(byData(none, "data-cw", "skill-en")[0].textContent, "gamma desc");
    assert.strictEqual(byData(none, "data-cw", "skill-zh").length, 0);
    assert.strictEqual(byData(none, "data-cw", "skill-orig").length, 0, "nothing to show the original of");
    // clicking the card still picks it
    byData(fresh, "data-skill", "s-c")[0].dispatch("click");
    assert.ok(findText(d, "已插入（1）"));
  });

  await test("a late loadout repaints the slots and the light only: the buttons are the same nodes and keep their handlers", async () => {
    const p = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" }, { equipped_skill_ids: ["s-c"] });
    const calls = [];
    const card = pure.profileCard(p, { catalog, handlers: { launch: (x) => calls.push(["launch", x.id]), edit: (x) => calls.push(["edit", x.id]) } });
    const launch = byData(card.node, "data-pcard", "launch")[0];
    assert.strictEqual(byData(card.node, "data-pcard", "light")[0].getAttribute("data-light"), "checking");
    assert.ok(findText(card.node, "確認出發條件中"));
    card.setLoadout(okState(loadoutBody(p)));
    assert.strictEqual(byData(card.node, "data-pcard", "light")[0].getAttribute("data-light"), "green");
    assert.strictEqual(byData(card.node, "data-pcard", "launch")[0], launch, "the same button");
    launch.dispatch("click"); byData(card.node, "data-pcard", "edit")[0].dispatch("click");
    assert.deepStrictEqual(calls, [["launch", "p-1"], ["edit", "p-1"]]);
    card.setLoadout({ state: "error", error: "x" });
    assert.strictEqual(byData(card.node, "data-pcard", "light")[0].getAttribute("data-light"), "unknown");
    assert.ok(findText(card.node, "讀不到出發條件"));
    // no handlers given: no action button, only the flip
    const bare = pure.profileCard(p, { catalog }).node;
    assert.deepStrictEqual(["launch", "edit", "duplicate", "remove", "decide"].map((k) => byData(bare, "data-pcard", k).length), [0, 0, 0, 0, 0]);
    assert.strictEqual(byData(bare, "data-pcard", "flip").length, 2);
  });

  await test("flip: both faces stay in the DOM, one is hidden and aria-hidden; button and F key turn it, the focus follows", async () => {
    const p = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    const faces = [];
    const card = pure.profileCard(p, { catalog, handlers: {}, onFace: (f) => faces.push(f) }).node;
    const front = faceOf(card, "front"), back = faceOf(card, "back");
    const state = () => [card.getAttribute("data-face"), front.hasAttribute("hidden"), front.getAttribute("aria-hidden"), back.hasAttribute("hidden"), back.getAttribute("aria-hidden")];
    assert.deepStrictEqual(state(), ["front", false, "false", true, "true"]);
    assert.ok(front.children.length && back.children.length, "both are built");
    const flips = byData(card, "data-pcard", "flip");
    assert.strictEqual(flips.length, 2);
    assert.ok(flips.every((b) => b.getAttribute("aria-keyshortcuts") === "F" && /按 F/.test(b.getAttribute("title"))));
    flips[0].dispatch("click");
    assert.deepStrictEqual(state(), ["back", true, "true", false, "false"]);
    assert.strictEqual(lastFocus, flips[1], "the button of the face that is up takes the focus");
    flips[1].dispatch("click");
    assert.deepStrictEqual(state(), ["front", false, "false", true, "true"]);
    assert.strictEqual(lastFocus, flips[0]);
    const key = (k, target, extra = {}) => card.dispatch("keydown", { key: k, target, ...extra });
    key("f", flips[0]);
    assert.strictEqual(card.getAttribute("data-face"), "back");
    key("F", flips[1]);
    assert.strictEqual(card.getAttribute("data-face"), "front");
    key("f", new Node("input")); key("f", new Node("textarea")); key("f", new Node("select"));
    key("f", flips[0], { ctrlKey: true }); key("f", flips[0], { metaKey: true }); key("f", flips[0], { altKey: true });
    key("x", flips[0]);
    assert.strictEqual(card.getAttribute("data-face"), "front", "typing in a field, a shortcut with a modifier, another key: no turn");
    assert.deepStrictEqual(faces, ["back", "front", "back", "front"]);
    const back2 = pure.profileCard(p, { catalog, face: "back" }).node;
    assert.strictEqual(back2.getAttribute("data-face"), "back");
    assert.ok(faceOf(back2, "front").hasAttribute("hidden") && !faceOf(back2, "back").hasAttribute("hidden"));
    assert.strictEqual(back.getAttribute("role"), "region");
    assert.strictEqual(back.getAttribute("tabindex"), "0", "the scrollable back can be scrolled from the keyboard");
  });

  await test("flip: with reduced motion there is no turning class; otherwise it is added and taken off", () => {
    const p = mkProfile("p-1", "Mine", "claude", ALL_DENY);
    const run = (reduced) => {
      const ctx = freshContext({});
      ctx.window.matchMedia = (q) => ({ matches: reduced && /prefers-reduced-motion/.test(q) });
      const timers = [];
      ctx.setTimeout = (f, ms) => { timers.push([f, ms]); return timers.length; };
      evalAgentBuilderSlice(ctx);
      const card = ctx.profileCard(p, { catalog }).node;
      byData(card, "data-pcard", "flip")[0].dispatch("click");
      return { card, timers };
    };
    const calm = run(true);
    assert.ok(!calm.card.classList.contains("rcard-turn") && calm.timers.length === 0);
    assert.strictEqual(calm.card.getAttribute("data-face"), "back", "it still turns, only without the motion");
    const moving = run(false);
    assert.ok(moving.card.classList.contains("rcard-turn") && moving.timers.length === 1);
    moving.timers[0][0]();
    assert.ok(!moving.card.classList.contains("rcard-turn"));
  });

  await test("the back: tool and model, the intents with their notes, evidence, the actions; Tool ID and Model ID only under 進階", async () => {
    const p = mkProfile("p-1", "Mine", "codex", { read: "allow", write: "deny", test: "allow", deploy: "deny" }, { profession_role_id: "r-1" });
    p.model = { tool: "codex", model_id: "gpt-test" };
    const desc = { value: "Writes docs", origin: "author", detail: "front matter" };
    await openPool([p], catalog, { "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutBody(p, {
      profession: { state: "found", role_id: "r-1", name: "Writer", description: desc } })) });
    const card = cardOf("p-1");
    const back = faceOf(card, "back");
    const front = faceOf(card, "front");
    assert.ok(findText(back, "Codex CLI") && findText(back, "gpt-test"));
    assert.ok(findText(back, "Writer") && findText(back, "只是標籤"), "the profession label, said to be only a label");
    assert.ok(findText(back, "證據來源") && findText(back, "你自己在主控台建立") && findText(back, "Writes docs"));
    assert.ok(findText(back, "讀取檔案・允許") && findText(back, "編輯寫入・拒絕") && findText(back, "執行測試・允許") && findText(back, "部署上線・拒絕"));
    assert.ok(findText(back, "只是記錄，不是授權"));
    assert.strictEqual(textOf(byData(back, "data-rc", "intent-note")[0]), vm.runInContext("CARD_INTENT_NOTE", pure));
    for (const kind of ["edit", "duplicate", "remove"]) {
      assert.strictEqual(byData(back, "data-pcard", kind).length, 1, `${kind} is on the back`);
      assert.strictEqual(byData(front, "data-pcard", kind).length, 0, `${kind} is not on the front`);
    }
    assert.strictEqual(byData(front, "data-pcard", "launch").length, 1);
    const adv = byData(back, "data-rc", "advanced")[0];
    assert.strictEqual(adv.tag, "details");
    assert.ok(!adv.hasAttribute("open") && findText(adv, "Tool ID") && findText(adv, "Model ID") && findText(adv, "英文說明") && findText(adv, "Writes docs"));
    const outside = textOf(card).replace(textOf(adv), "");
    for (const w of ["Tool ID", "Model ID", "Permission Intents", "AgentRole", "Agent Builder"]) assert.ok(!outside.includes(w), `${w} is for 進階 only`);
    assert.ok(!/\bProfile\b/.test(outside), "no 'Profile' on either face");
    assert.ok(!findText(card, "出勤中"));
  });

  await test("the front shows the suggested position with its badge, the camp frame, and the sample label", async () => {
    const ctx = await openPool([mkProfile("p-1", "Mine", "claude", ALL_DENY), mkProfile("demo-1", "Demo", "codex", ALL_DENY), mkProfile("p-3", "Shared", "shared", ALL_DENY)]);
    ctx.localStorage.setItem("sid:card.position.p-1", JSON.stringify("reviewer"));
    await ctx.viewTeam(); await tick(8);
    assert.strictEqual(cardOf("p-1").getAttribute("data-camp"), "anthropic");
    assert.strictEqual(cardOf("demo-1").getAttribute("data-camp"), "openai");
    assert.strictEqual(cardOf("p-3").getAttribute("data-camp"), "other");
    const pos = byData(cardOf("p-1"), "data-pcard", "position")[0];
    assert.ok(findText(pos, "審查位"), "words");
    const glyph = (node) => walk(node).find((n) => n.className === "pos-glyph");
    assert.strictEqual(textOf(glyph(pos)), "審", "and the badge: one Chinese character (art v3), not a pixel map");
    assert.strictEqual(glyph(pos).getAttribute("aria-hidden"), "true", "decoration: the words say the same");
    assert.ok(!walk(pos).some((n) => n.tag === "svg"), "the 12x12 position pixel maps are not used");
    const none = byData(cardOf("p-3"), "data-pcard", "position")[0];
    assert.ok(findText(none, "位置未指定"));
    assert.strictEqual(textOf(glyph(none)), "？");
    assert.deepStrictEqual(["planner", "executor", "reviewer", null, "x", "__proto__", "constructor"].map((x) => pure.cardPositionBadgeKey(x)),
      ["planning", "execution", "review", "unspecified", "unspecified", "unspecified", "unspecified"]);
    assert.deepStrictEqual(["planner", "executor", "reviewer", null].map((x) => textOf(glyph(pure.positionBadge(x)))), ["規", "執", "審", "？"]);
  });

  await test("readLoadouts: at most four requests in flight, every id once, and it stops when the page is gone", async () => {
    const ctx = freshContext({});
    evalAgentBuilderSlice(ctx);
    let inflight = 0, peak = 0;
    const done = [];
    const api = vm.runInContext("api", ctx);
    api.get = (url) => { inflight += 1; peak = Math.max(peak, inflight);
      return new Promise((r) => setImmediate(() => { inflight -= 1; r({ url }); })); };
    const ids = Array.from({ length: 11 }, (_, i) => `p-${i}`);
    ctx.readLoadouts(ids, (id, state) => done.push([id, state.state]), () => false);
    await tick(40);
    assert.strictEqual(done.length, 11);
    assert.deepStrictEqual(done.map((d) => d[0]).sort(), [...ids].sort());
    assert.ok(peak <= 4 && peak >= 2, `peak ${peak}`);
    let gone = false;
    const seen = [];
    ctx.readLoadouts(ids, (id) => { seen.push(id); gone = true; }, () => gone);
    await tick(40);
    assert.ok(seen.length <= 4, "after the page is gone nothing more is read or applied");
    api.get = () => Promise.reject(new Error("boom"));
    const errs = [];
    ctx.readLoadouts(["a"], (id, st) => errs.push(st), () => false);
    await tick(6);
    assert.deepStrictEqual(errs.map((x) => [x.state, x.error]), [["error", "boom"]]);
  });

  await test("the art (v4): every map is a full grid of palette characters; shields differ in shape; icons exist; no position pixel maps", () => {
    const px = vm.runInContext("CARD_PIXELS", pure), pal = vm.runInContext("CARD_PALETTE", pure);
    assert.deepStrictEqual(Object.keys(px).sort(), ["backPattern", "deskStrip", "icons", "officeProps", "shields"], "the position pixel maps are retired (R12)");
    assert.deepStrictEqual(Object.keys(px.shields).sort(), ["enforced", "none", "recorded"]);
    assert.deepStrictEqual(Object.keys(px.icons).sort(), ["emptySlot", "importProject", "taskFolder"]);
    const grids = [["backPattern", px.backPattern, 16], ...["shields", "icons"].flatMap((g) => Object.entries(px[g]).map(([k, m]) => [`${g}.${k}`, m, 12]))];
    assert.strictEqual(grids.length, 7);
    for (const [name, rows, size] of grids) {
      assert.strictEqual(rows.length, size, `${name} height`);
      for (const row of rows) {
        assert.strictEqual(row.length, size, `${name} width`);
        for (const c of row) assert.ok(c === "." || Object.prototype.hasOwnProperty.call(pal, c), `${name}: ${c} is not in the palette`);
      }
    }
    assert.ok(Object.values(pal).every((v) => /^#[0-9a-f]{6}$/i.test(v)) && !Object.values(pal).some((v) => v.toLowerCase() === "#da251d"), "no vn red");
    // the shield differs in shape, not only in colour
    const shape = (rows) => rows.map((r) => r.replace(/[^.]/g, "#")).join("|");
    assert.strictEqual(new Set(Object.values(px.shields).map(shape)).size, 3);
    assert.ok(px.shields.recorded.join("").split("").filter((c) => c !== ".").every((c) => c === "K" || c === "H"), "dashed: outline dashes and the pale inside");
    assert.ok(/H/.test(px.shields.recorded.join("")) && !/T/.test(px.shields.recorded.join("")), "dashed: pale inside, not the solid fill");
    assert.ok(/[^.K]/.test(px.shields.enforced.join("")), "solid: filled");
    // v3: three flat-topped, pointed-bottom shields of one outline extent (the art's own check)
    const bounds = (rows) => { const pts = rows.flatMap((r, y) => [...r].map((c, x) => (c === "." ? null : [x, y])).filter(Boolean));
      return [Math.min(...pts.map((q) => q[0])), Math.max(...pts.map((q) => q[0])), Math.min(...pts.map((q) => q[1])), Math.max(...pts.map((q) => q[1]))]; };
    for (const k of ["enforced", "recorded", "none"]) assert.deepStrictEqual(bounds(px.shields[k]), [0, 11, 0, 11], k);
    for (const k of ["enforced", "recorded", "none"]) assert.strictEqual(px.shields[k][11], ".....KK.....", `${k}: the same pointed bottom`);
    assert.strictEqual(px.shields.enforced[0], "KKKKKKKKKKKK", "flat top");
    assert.ok(px.shields.none.join("").split("").filter((c) => c !== ".").every((c) => c === "K") && px.shields.none[5][5] === "K", "empty shield: outline and a slash across it");
    assert.strictEqual(px.shields.recorded[0], "KK.KK.KK.KK.", "dashed: two on, one off along the top");
    assert.ok(px.shields.recorded.slice(1, 6).some((r) => r[0] === "." && r[11] === "."), "dashed: the sides have gaps too (the outline is not solid)");
    // the icons the card play needs
    assert.ok(/Y/.test(px.icons.taskFolder.join("")) && /Y/.test(px.icons.importProject.join("")));
    assert.ok(px.icons.importProject[1] === ".....YY....." && px.icons.importProject[6] === "....KYYK....", "the import arrow points down into the tray");
  });

  await test("position badges (art v3): one character and one label per position, a hard 2px square coloured by the camp", () => {
    const b = vm.runInContext("CARD_POSITION_BADGES", pure);
    assert.deepStrictEqual(Object.keys(b), ["planning", "execution", "review", "unspecified"]);
    assert.deepStrictEqual(Object.values(b).map((x) => [x.glyph, x.label]), [["規", "規劃"], ["執", "執行"], ["審", "審查"], ["？", "未指定"]]);
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    const rule = /\.pos-glyph\s*\{([^}]*)\}/.exec(css);
    assert.ok(rule, "the badge rule");
    assert.ok(/border:\s*2px solid var\(--pos-border/.test(rule[1]) && /border-radius:\s*0\b/.test(rule[1]), "hard 2px square");
    assert.ok(/background:\s*var\(--pos-bg/.test(rule[1]) && /color:\s*var\(--pos-text/.test(rule[1]));
    // the art's positionBadges.themes values, in light and in both dark blocks; text 4.5:1, border 3:1 (recomputed here)
    const want = {
      light: { anthropic: ["#fffbeb", "#92400e", "#78350f"], openai: ["#f0fdfa", "#115e59", "#134e4a"], google: ["#f0f9ff", "#075985", "#0c4a6e"], other: ["#faf5ff", "#6b21a8", "#581c87"] },
      dark: { anthropic: ["#292315", "#fde68a", "#fbbf24"], openai: ["#142522", "#99f6e4", "#5eead4"], google: ["#14232b", "#bae6fd", "#7dd3fc"], other: ["#24182e", "#e9d5ff", "#d8b4fe"] },
    };
    const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
    const ratio = (a, c) => { const [x, y] = [lum(a), lum(c)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
    const prefixes = { light: [""], dark: ["  :root:not([data-theme=\"light\"]) ", ":root[data-theme=\"dark\"] "] };
    let seen = 0;
    for (const mode of ["light", "dark"]) for (const camp of Object.keys(want[mode])) for (const prefix of prefixes[mode]) {
      const line = css.split("\n").find((l) => l.startsWith(prefix + `.rcard[data-camp="${camp}"] {`));
      assert.ok(line, `${mode} ${camp}`);
      const get = (n) => new RegExp(`--pos-${n}: (#[0-9a-fA-F]{6})`).exec(line)[1];
      assert.deepStrictEqual([get("bg"), get("text"), get("border")], want[mode][camp], `${mode} ${camp}`);
      assert.ok(ratio(get("text"), get("bg")) >= 4.5 && ratio(get("border"), get("bg")) >= 3, `${mode} ${camp} contrast`);
      seen += 1;
    }
    assert.strictEqual(seen, 12);
  });

  await test("cardArt: an SVG with the cell grid, decoration only; a name it does not have is null", () => {
    const svg = pure.cardArt("shields", "enforced", 2);
    assert.strictEqual(svg.tag, "svg");
    assert.strictEqual(svg.getAttribute("viewBox"), "0 0 12 12");
    assert.strictEqual(svg.getAttribute("aria-hidden"), "true");
    assert.strictEqual(svg.getAttribute("width"), "24");
    const rects = walk(svg).filter((n) => n.tag === "rect");
    assert.ok(rects.length > 10 && rects.every((r) => Number(r.getAttribute("height")) === 1));
    assert.ok(rects.some((r) => r.getAttribute("class") === "px-k"), "the outline takes the theme's colour");
    assert.ok(rects.filter((r) => r.getAttribute("class") !== "px-k").every((r) => /^#[0-9a-f]{6}$/i.test(r.getAttribute("fill"))));
    for (const [g, n] of [["shields", "nope"], ["nope", "enforced"], ["backPattern", "backPattern"], ["positions", "planning"], ["positions", "__proto__"], ["icons", "constructor"]]) {
      assert.strictEqual(pure.cardArt(g, n), null, `${g}.${n}`);
    }
    const strip = pure.cardPatternStrip();
    const pattern = walk(strip).find((n) => n.tag === "pattern");
    assert.ok(pattern && pattern.getAttribute("width") === "16" && pattern.getAttribute("height") === "16");
    const fill = walk(strip).filter((n) => n.tag === "rect").pop().getAttribute("fill");
    assert.strictEqual(fill, `url(#${pattern.getAttribute("id")})`, "fills with its own pattern, nothing outside");
    const other = walk(pure.cardPatternStrip()).find((n) => n.tag === "pattern");
    assert.notStrictEqual(other.getAttribute("id"), pattern.getAttribute("id"), "each strip has its own id");
  });

  await test("armorShieldKind: only enforced, intent-only and unrestricted have a shield, by the server's level words", () => {
    const rows = [["強制（限已測路徑、版本與執行層）", "enforced"], ["僅意圖", "recorded"], ["未限制", "none"],
      ["部分強制", null], ["未驗證（此 Claude Code 版本尚未實測）", null], ["未知", null], ["不授予", null], ["", null], [undefined, null], ["enforced", null]];
    for (const [level, want] of rows) assert.strictEqual(pure.armorShieldKind(level), want, String(level));
  });

  // The frame colours of the art, read from the CSS the page ships: every camp has them in light, in the dark media block
  // and in the dark theme, each text colour reaches 4.5:1 on its card colour, each frame line 3:1, and no card uses the vn red.
  await test("CSS: camp frames in light and both dark blocks, with their contrast; no vn red on a card; the dark outline", () => {
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
    const grab = (prefix, camp) => {
      const m = css.split("\n").find((l) => l.startsWith(prefix + `.rcard[data-camp="${camp}"] {`));
      assert.ok(m, `${prefix}${camp}`);
      const v = (name) => new RegExp(`--card-frame-${name}: (#[0-9a-fA-F]{6})`).exec(m)[1];
      return { bg: v("bg"), line: v("line"), title: v("title") };
    };
    const modes = [["light", "", "#1f2522"], ["dark media", "  :root:not([data-theme=\"light\"]) ", "#e9ece8"], ["dark theme", ":root[data-theme=\"dark\"] ", "#e9ece8"]];
    let checked = 0;
    for (const [label, prefix, ink] of modes) for (const camp of ["anthropic", "openai", "google", "other"]) {
      const f = grab(prefix, camp);
      assert.ok(ratio(f.title, f.bg) >= 4.5, `${label} ${camp} title ${ratio(f.title, f.bg)}`);
      assert.ok(ratio(ink, f.bg) >= 4.5, `${label} ${camp} text ${ratio(ink, f.bg)}`);
      assert.ok(ratio(f.line, f.bg) >= 3, `${label} ${camp} line ${ratio(f.line, f.bg)}`);
      checked += 1;
    }
    assert.strictEqual(checked, 12);
    const cardCss = css.split("\n").filter((l) => /rcard|card-px|px-k|armor-shield/.test(l)).join("\n");
    assert.ok(!/da251d|--vn-red/i.test(cardCss), "the vn red is not on a card");
    assert.ok(/\.px-k\s*\{\s*fill:\s*#18181b/.test(css) && /\[data-theme="dark"\]\s*\.px-k\s*\{\s*fill:\s*#f8fafc/.test(css) && /:not\(\[data-theme="light"\]\)\s*\.px-k\s*\{\s*fill:\s*#f8fafc/.test(css), "outline: dark on light, light on dark");
    assert.ok(/\.rcard-slot\s*\{[^}]*border:\s*2px dashed/.test(css) && /\.rcard-slot-active\s*\{[^}]*border-style:\s*solid/.test(css), "collected is dashed, in effect is solid");
    assert.ok(/\.rcard-face\[hidden\]\s*\{\s*display:\s*none/.test(css), "a hidden face is not shown by the face's own display");
    assert.ok(/prefers-reduced-motion:\s*reduce\)\s*\{\s*\.rcard-turn[^}]*animation:\s*none/.test(css), "no turning animation with reduced motion");
    assert.ok(!/url\(\s*["']?https?:/.test(css));
  });

  await test("CSS: the fifth light (R11) differs from the red in shape and colour", () => {
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    const dot = (cls) => (new RegExp(`\\.rcard-${cls} \\.rcard-dot\\s*\\{([^}]*)\\}`).exec(css) || [])[1] || "";
    const codex = dot("codex"), red = dot("blocked");
    assert.ok(codex && red);
    assert.ok(/var\(--info\)/.test(codex) && !/var\(--bad\)/.test(codex), "the info colour, not the red");
    assert.ok(/border-radius:\s*50%/.test(codex) && /linear-gradient/.test(codex), "a half-filled ring");
    assert.ok(/border-radius:\s*2px/.test(red) && /var\(--bad\)/.test(red), "the red is the square");
    assert.ok(/\.rcard-codex\s*\{\s*background:\s*var\(--info-soft\)/.test(css));
  });

  // ======== P18 #1: the skill cards on a role card open the skill card window, and 從這個角色移除 works from there =========

  const skillBody = (id, name) => {
    const miss = () => ({ value: null, origin: "missing", detail: "" });
    return { ok: true, index: { loaded: true, generated_at: 1 },
      skill: { skill_id: id, name: { value: name, origin: "author", detail: "x" }, tool: miss(), scope: miss(), activation: "active",
        installed: true, activation_reason: "r", status_source: { origin: "derived", detail: "d" },
        description: miss(), when_to_use: miss(), inputs: miss(), outputs: miss(), dependencies: miss(),
        categories: { value: null, origin: "missing", detail: "", matches: [] },
        referenced_files: { count: 0, items: [], truncated: false, note: "n", origin: "derived", detail: "x" },
        missing_files: { items: [], origin: "derived", detail: "d" }, warnings: { items: [], origin: "derived", detail: "d" } },
      added_to_roles: { items: [], effective: false, note: "n", origin: "user", detail: "d" },
      observation: { state: "unavailable", window_days: null, source: "s", origin: "runtime", detail: "d" },
      marketplace_copies: [], marketplace_source: { origin: "derived", detail: "d" }, effect_note: "e" };
  };
  const skillHandlers = (ids) => Object.fromEntries(ids.map((id) => [`GET /api/skills/${id}?view=card`, () => jsonResponse(skillBody(id, `name-${id}`))]));
  const dialogsNow = () => body.children.filter((c) => c !== main && c.getAttribute && c.getAttribute("role") === "dialog");
  const removeButton = (root) => walk(root).find((n) => n.tag === "button" && (n.textContent || "") === "從這個角色移除");

  await test("P18 #1 the back lists the skill cards on the card; each opens the skill card with 從這個角色移除; confirming posts the rest and redraws", async () => {
    const p = mkProfile("p-1", "Mine", "claude", VERIFIED, { equipped_skill_ids: ["s-c", "s-s"] });
    const posts = [];
    let changed = 0;
    const ctx = freshContext({ ...skillHandlers(["s-c", "s-s"]),
      "POST /api/agent-profiles/p-1": (_u, o) => { posts.push(JSON.parse(o.body)); return jsonResponse({ ok: true }); } });
    evalAgentBuilderSlice(ctx);
    const card = ctx.profileCard(p, { catalog, face: "back", handlers: { skillsChanged: async () => { changed += 1; } } });
    const sec = byData(card.node, "data-rc", "skills")[0];
    assert.ok(sec, "the back has a section for the skill cards on the card");
    assert.ok(faceOf(card.node, "back").contains(sec), "it is on the back, not the front");
    assert.ok(findText(sec, "已插的技能卡"));
    const btns = byData(sec, "data-pcard", "skill-card");
    assert.strictEqual(btns.length, 2);
    assert.ok(btns.every((b) => b.textContent === "技能卡特性"));
    btns[0].dispatch("click"); await tick(8);
    const modal = dialog();
    assert.ok(modal && findText(modal, "name-s-c"), "the skill card of the first one");
    const remove = removeButton(modal);
    assert.ok(remove, "從這個角色移除 is there when opened from the card");
    remove.dispatch("click"); await tick(8);
    const ds = dialogsNow();
    const confirmBox = ds[ds.length - 1];
    assert.ok(findText(confirmBox, "把「name-s-c」從角色「Mine」的已選技能移除？這只會改你的挑選紀錄，不會刪除技能。"));
    btnByText(confirmBox, "移除").dispatch("click"); await tick(8);
    assert.deepStrictEqual(posts, [{ equipped_skill_ids: ["s-s"] }]);
    assert.strictEqual(changed, 1, "the page is told once, so it can redraw");
    assert.strictEqual(dialogsNow().length, 0, "both windows are closed");
  });

  await test("P18 #1 without a change handler, on a sample card, or from the armory: the skill card opens but offers no removal", async () => {
    const ids = ["s-c"];
    const open = async (p, handlers) => {
      const ctx = freshContext(skillHandlers(ids));
      evalAgentBuilderSlice(ctx);
      const card = ctx.profileCard(p, { catalog, face: "back", handlers });
      const btn = byData(card.node, "data-pcard", "skill-card")[0];
      assert.ok(btn, "the entry is there");
      btn.dispatch("click"); await tick(8);
      const modal = dialog();
      assert.ok(modal && findText(modal, "name-s-c"));
      return modal;
    };
    const mine = mkProfile("p-1", "Mine", "claude", VERIFIED, { equipped_skill_ids: ids });
    assert.ok(!removeButton(await open(mine, {})), "no handler: nothing could redraw the card");
    const demo = mkProfile("demo-1", "Sample", "claude", VERIFIED, { equipped_skill_ids: ids });
    assert.ok(!removeButton(await open(demo, { skillsChanged: async () => {} })), "a sample card is not edited");
    const ctx = freshContext(skillHandlers(ids));
    evalAgentBuilderSlice(ctx);
    await ctx.openSkillCard("s-c"); await tick(8);
    assert.ok(!removeButton(dialog()), "opened from the armory: no profile, no removal");
  });

  await test("P18 #1 a long list stays on the scrolling back; a skill the index cannot find has no entry and says why", async () => {
    const ids = Array.from({ length: 40 }, (_, i) => `s-${i}`);
    const p = mkProfile("p-1", "Mine", "claude", VERIFIED, { equipped_skill_ids: ids });
    const card = pure.profileCard(p, { catalog, face: "back", handlers: { skillsChanged: async () => {} } });
    const sec = byData(card.node, "data-rc", "skills")[0];
    assert.strictEqual(byData(sec, "data-pcard", "skill-card").length, 40, "every skill on the card is reachable");
    assert.ok(faceOf(card.node, "back").contains(sec));
    assert.strictEqual(slotsOf(card.node).length, 6, "the front keeps its six slots");
    const items = [{ skill_id: "s-1", state: "in_index", name: "one", will_load: false, effective: false },
      { skill_id: "s-2", state: "not_in_index", name: "s-2", will_load: false, effective: false }];
    card.setLoadout(okState(loadoutWith(items)));
    const rows = byData(card.node, "data-rc", "skills")[0];
    assert.strictEqual(byData(rows, "data-pcard", "skill-card").length, 1, "only the one the index has");
    assert.ok(findText(rows, "目前索引找不到") && findText(rows, "編輯"), "the other says why, and where to take it off");
  });

  await test("P18 #1 the card pool redraws after a removal: skill count and slots follow, no page reload", async () => {
    const p = mkProfile("p-1", "Mine", "claude", VERIFIED, { equipped_skill_ids: ["s-c", "s-s"] });
    const ctx = await openPool([p], catalog, { ...skillHandlers(["s-c", "s-s"]),
      "POST /api/agent-profiles/p-1": (_u, o) => { p.equipped_skill_ids = JSON.parse(o.body).equipped_skill_ids; return jsonResponse({ ok: true }); } });
    assert.ok(findText(cardOf("p-1"), "技能卡 2 張"));
    byData(cardOf("p-1"), "data-pcard", "skill-card")[1].dispatch("click"); await tick(8);
    removeButton(dialog()).dispatch("click"); await tick(8);
    const ds = dialogsNow();
    btnByText(ds[ds.length - 1], "移除").dispatch("click"); await tick(12);
    assert.ok(findText(cardOf("p-1"), "技能卡 1 張"), "the count is the new one");
    assert.strictEqual(slotsOf(cardOf("p-1")).length, 1);
    assert.strictEqual(ctx.location.hash, "", "no navigation: the page was redrawn in place");
  });

  await test("P18 #1 the workbench role tab: the same entry, and a removal redraws the tab", async () => {
    const p = mkProfile("p-1", "Mine", "claude", VERIFIED, { equipped_skill_ids: ["s-c", "s-s"] });
    const ctx = freshContext(baseHandlers([p], catalog, { ...skillHandlers(["s-c", "s-s"]),
      "POST /api/agent-profiles/p-1": (_u, o) => { p.equipped_skill_ids = JSON.parse(o.body).equipped_skill_ids; return jsonResponse({ ok: true }); } }));
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    walk(main).find((n) => n.tag === "button" && (n.textContent || "").trim() === "角色").dispatch("click"); await tick();
    assert.ok(findText(cardOf("p-1"), "技能卡 2 張"));
    byData(cardOf("p-1"), "data-pcard", "skill-card")[0].dispatch("click"); await tick(8);
    removeButton(dialog()).dispatch("click"); await tick(8);
    const ds = dialogsNow();
    btnByText(ds[ds.length - 1], "移除").dispatch("click"); await tick(12);
    assert.ok(findText(cardOf("p-1"), "技能卡 1 張"), "the tab shows the new count");
  });

  await test("P18 #1 the office roster card: the same entry; its change handler is the view's, which reads the roster and the loadout again", async () => {
    const p = mkProfile("p-1", "Mine", "claude", VERIFIED, { equipped_skill_ids: ["s-c"] });
    let told = 0;
    const posts = [];
    const ctx = freshContext({ ...skillHandlers(["s-c"]),
      "POST /api/agent-profiles/p-1": (_u, o) => { posts.push(JSON.parse(o.body)); return jsonResponse({ ok: true }); } });
    evalAgentBuilderSlice(ctx);
    const S = { profiles: { profiles: [p] }, loadout: null, face: "back", skillsChanged: async () => { told += 1; } };
    const node = ctx.officeRoleCard({ id: "p-1", key: "profile:p-1" }, S);
    byData(node, "data-pcard", "skill-card")[0].dispatch("click"); await tick(8);
    removeButton(dialog()).dispatch("click"); await tick(8);
    const ds = dialogsNow();
    btnByText(ds[ds.length - 1], "移除").dispatch("click"); await tick(8);
    assert.deepStrictEqual(posts, [{ equipped_skill_ids: [] }]);
    assert.strictEqual(told, 1);
    const view = source.slice(source.indexOf("async function viewOffice("), source.indexOf("function officeJump("));
    assert.ok(/S\.skillsChanged\s*=\s*async/.test(view) && /S\.reloadRoster\(\)/.test(view.slice(view.indexOf("S.skillsChanged"))), "the view wires it to the roster reload");
  });

  // ---- P20: Antigravity (AGY) as a fourth camp -----------------------------------------------------------------------
  const catalogAgy = { ...catalog, tools: ["claude", "codex", "agy", "shared"] };
  const AGY_NOT_LAUNCHED = "VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄";
  const agyLoadout = (p) => loadoutBody(p, {
    armor: { applicable: false, why: "VBear 還不會啟動 AGY，沒有防具" },
    blockers: [{ code: "tool_not_launchable", message: AGY_NOT_LAUNCHED }],
    skills: { title: "技能卡（收藏中：VBear 啟動時不載入）", all_inactive: true, note: "x",
      items: (p.equipped_skill_ids || []).map((id) => ({ skill_id: id, state: "in_index", name: id, will_load: false, effective: false })) } });
  const shadowOf = (root) => { const n = walk(root).find((x) => x.getAttribute && /box-shadow/.test(x.getAttribute("style") || "")); return n ? n.getAttribute("style") : ""; };

  await test("P20 the vocabulary: the camp is Antigravity（AGY）, short AGY, and it sits before the shared camp", () => {
    const label = vm.runInContext("CARD_TOOL_LABEL", pure), short = vm.runInContext("CARD_TOOL_SHORT", pure);
    assert.deepStrictEqual(Object.keys(label), ["claude", "codex", "agy", "shared"]);
    assert.strictEqual(label.agy, "Antigravity（AGY）");
    assert.strictEqual(short.agy, "AGY");
    assert.deepStrictEqual(Object.keys(short), ["claude", "codex", "agy", "shared"]);
    assert.strictEqual(vm.runInContext("TOOL.agy", pure), "Antigravity（AGY）");
  });

  await test("P20 look: an AGY card is the fox in the Google colours; any other tool string is still the alien, and nothing else changed", () => {
    assert.strictEqual(pure.speciesFor({ tool: "agy" }), "fox");
    assert.strictEqual(pure.campOf({ tool: "agy" }).key, "google");
    assert.strictEqual(pure.campOf({ tool: "agy" }).shirt, pure.campOf({ family: "google" }).shirt);
    assert.strictEqual(pure.speciesFor({ tool: "agy" }, "bear"), "bear", "the person may still pick another species");
    for (const tool of ["gemini", "AGY", "antigravity", "agy ", ""]) {
      assert.strictEqual(pure.speciesFor({ tool }), "alien", tool);
      assert.strictEqual(pure.campOf({ tool }).key, "other", tool);
    }
    assert.strictEqual(pure.speciesFor({ tool: "claude" }), "bear");
    assert.strictEqual(pure.speciesFor({ tool: "codex" }), "robot");
    assert.strictEqual(pure.campOf({ tool: "claude" }).key, "anthropic");
    assert.strictEqual(pure.campOf({ tool: "codex" }).key, "openai");
    assert.strictEqual(pure.campOf({ tool: "shared" }).key, "other");
    assert.strictEqual(pure.campKeyOf({ model: { tool: "agy" } }), "google");
  });

  await test("P20 skillCompatible: an AGY card takes shared skill cards only (a record, not a load); VBear does not know what AGY reads", () => {
    const rows = [["agy", "shared", true], ["agy", "claude", false], ["agy", "codex", false], ["agy", "agy", false],
      ["agy", "", false], ["agy", undefined, false], ["claude", "agy", false], ["codex", "agy", false], ["shared", "agy", false]];
    for (const [tool, source, want] of rows) assert.strictEqual(pure.skillCompatible({ tool: source }, tool), want, `${tool} card, ${source} skill`);
    assert.strictEqual(pure.skillIncompatibleNote("agy"), "VBear 還不知道 AGY 會讀哪些技能");
    assert.strictEqual(pure.skillIncompatibleNote("claude"), "Claude Code 不會讀這張卡");
    assert.strictEqual(pure.skillIncompatibleNote("codex"), "Codex 不會讀這張卡");
    assert.strictEqual(pure.skillIncompatibleNote("shared"), "共用角色卡只能插共用的技能卡");
  });

  await test("P20 wizard step 2: AGY is in the camp row with the others, drawn as the fox, and choosing it saves tool agy", async () => {
    const { posts, d } = await openWizard([], catalogAgy);
    typeName(d, "AGY 審查員");
    btnByText(d, "下一步").dispatch("click");
    const group = byData(dialog(), "role", "group").find((n) => n.getAttribute("aria-label") === "陣營（工具）");
    const buttons = group.children.filter((n) => n.tag === "button");
    assert.deepStrictEqual(buttons.map((b) => b.getAttribute("data-tool")), ["claude", "codex", "agy", "shared"], "one row, in this order");
    const agy = buttons[2];
    assert.ok(findText(agy, "Antigravity（AGY）"));
    assert.strictEqual(shadowOf(agy), shadowOf(pure.officeSprite("fox", "google", 2)), "the fox in the Google colours");
    assert.strictEqual(byData(dialog(), "data-cw", "agy-note").length, 0, "the note shows only for AGY");
    agy.dispatch("click");
    const now = dialog();
    assert.strictEqual(byData(now, "data-tool", "agy")[0].getAttribute("aria-pressed"), "true");
    assert.strictEqual(byData(now, "data-tool", "claude")[0].getAttribute("aria-pressed"), "false");
    const note = byData(now, "data-cw", "agy-note")[0];
    assert.ok(note && findText(note, "VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄"), "says it plainly beside the choice");
    assert.ok(!findText(now, "找不到 Codex"));
    btnByText(now, "下一步").dispatch("click");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.strictEqual(posts[0].model.tool, "agy");
  });

  await test("P20 wizard: a catalog from an older server (three tools) offers three camps, as before", async () => {
    const { d } = await openWizard();
    typeName(d, "Old");
    btnByText(d, "下一步").dispatch("click");
    assert.deepStrictEqual(byData(dialog(), "data-tool", "agy").length, 0);
    assert.deepStrictEqual(walk(dialog()).filter((n) => n.getAttribute && n.getAttribute("data-tool")).map((n) => n.getAttribute("data-tool")), ["claude", "codex", "shared"]);
  });

  await test("P20 wizard step 1: the 'by camp' look of an AGY card is the fox", async () => {
    const existing = mkProfile("p-agy", "AGY 一號", "agy", VERIFIED);
    const ctx = await openPool([existing], catalogAgy, { "GET /api/agent-profiles/p-agy/loadout": () => jsonResponse(agyLoadout(existing)) });
    cardOf("p-agy").dispatch("click");
    byData(cardOf("p-agy"), "data-pcard", "flip")[0].dispatch("click");
    byData(cardOf("p-agy"), "data-pcard", "edit")[0].dispatch("click");
    await tick();
    assert.ok(findText(dialog(), "依陣營（狐）"), "the automatic choice names the fox");
  });

  await test("P20 wizard step 3: with an AGY card only shared skill cards can be inserted, the rest say VBear does not know what AGY reads", async () => {
    const { posts, d } = await openWizard([], catalogAgy);
    typeName(d, "AGY 收藏");
    btnByText(d, "下一步").dispatch("click");
    byData(dialog(), "data-tool", "agy")[0].dispatch("click");
    btnByText(dialog(), "下一步").dispatch("click");
    const cur = dialog();
    const note = byData(cur, "data-cw", "agy-skills-note")[0];
    assert.ok(note && findText(note, "VBear 還不知道 AGY 會讀哪些技能") && findText(note, "只是收藏"), "the page says it before any skill is picked");
    const sk = (id) => byData(dialog(), "data-skill", id)[0];
    for (const id of ["s-c", "s-x"]) {
      assert.strictEqual(sk(id).getAttribute("aria-disabled"), "true", id);
      assert.ok(findText(sk(id), "VBear 還不知道 AGY 會讀哪些技能"), id);
      sk(id).dispatch("click");
      assert.strictEqual(sk(id).getAttribute("aria-pressed"), "false", `${id} cannot be inserted`);
    }
    assert.strictEqual(sk("s-s").getAttribute("aria-disabled"), null);
    sk("s-s").dispatch("click");
    assert.strictEqual(sk("s-s").getAttribute("aria-pressed"), "true");
    assert.ok(!findText(dialog(), "AGY 會載入") || findText(dialog(), "不代表"), "no sentence claims a load");
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.deepStrictEqual(posts[0].equipped_skill_ids, ["s-s"]);
    assert.strictEqual(posts[0].model.tool, "agy");
  });

  await test("P20 wizard: switching to AGY drops the Claude and Codex skill cards and the profession label, and says so", async () => {
    const { posts, d } = await openWizard([], catalogAgy);
    typeName(d, "Switch to AGY");
    btnByText(d, "下一步").dispatch("click");
    const sel = walk(dialog()).find((n) => n.tag === "select" && n.getAttribute("id") === "cw-profession");
    sel.value = "r-1"; sel.dispatch("change");
    btnByText(dialog(), "下一步").dispatch("click");
    byData(dialog(), "data-skill", "s-c")[0].dispatch("click");
    byData(dialog(), "data-skill", "s-s")[0].dispatch("click");
    btnByText(dialog(), "上一步").dispatch("click");
    byData(dialog(), "data-tool", "agy")[0].dispatch("click");
    btnByText(dialog(), "下一步").dispatch("click");
    assert.ok(findText(dialog(), "換了陣營，已移除 1 張這個陣營不會讀的技能卡。"));
    assert.ok(findText(dialog(), "已插入（1）"));
    btnByText(dialog(), "建立").dispatch("click");
    await tick();
    assert.strictEqual(posts[0].profession_role_id, null, "the Claude role label does not stay on an AGY card");
    assert.deepStrictEqual(posts[0].equipped_skill_ids, ["s-s"]);
  });

  await test("P20 wizard 進階: an AGY card lists no profession labels and says VBear has not scanned any; the other tools still list theirs", async () => {
    const { d } = await openWizard([], catalogAgy);
    typeName(d, "Prof");
    btnByText(d, "下一步").dispatch("click");
    const options = () => walk(byData(dialog(), "data-cw", "advanced")[0]).filter((n) => n.tag === "option").map((n) => (n.textContent || "").trim());
    assert.deepStrictEqual(options(), ["（不綁定）", "Writer (claude)"]);
    byData(dialog(), "data-tool", "agy")[0].dispatch("click");
    assert.deepStrictEqual(options(), ["（不綁定）"], "no Claude or Codex role stands in for an AGY one");
    const adv = byData(dialog(), "data-cw", "advanced")[0];
    assert.ok(findText(adv, "VBear 沒有掃描 AGY 的 Agent 角色，沒有可選的職業標籤"));
    byData(dialog(), "data-tool", "shared")[0].dispatch("click");
    assert.deepStrictEqual(options(), ["（不綁定）", "Writer (claude)"]);
  });

  await test("P20 the card: the front and back of an AGY card — Antigravity（AGY）, the fox, the Google frame, a red light with the plain reason and no shield", async () => {
    const p = mkProfile("p-agy", "AGY 一號", "agy", VERIFIED, { equipped_skill_ids: ["s-s"] });
    await openPool([p], catalogAgy, { "GET /api/agent-profiles/p-agy/loadout": () => jsonResponse(agyLoadout(p)) });
    const card = cardOf("p-agy");
    assert.strictEqual(card.getAttribute("data-camp"), "google");
    const front = faceOf(card, "front"), back = faceOf(card, "back");
    assert.ok(findText(front, "Antigravity（AGY）"));
    assert.strictEqual(shadowOf(front), shadowOf(pure.officeSprite("fox", "google", 3)), "the fox in the Google colours");
    const light = byData(card, "data-light", "blocked")[0];
    assert.ok(light, "the light is the red one, not a green");
    assert.ok(findText(light, "目前不能出發") && findText(light, AGY_NOT_LAUNCHED));
    assert.strictEqual(byData(card, "data-pcard", "pass-line").filter((n) => !n.hasAttribute("hidden")).length, 0, "no line about what a start does");
    assert.ok(!walk(card).some((n) => /armor-shield/.test(n.className || "")), "no shield anywhere on the card");
    assert.ok(findText(back, "Antigravity（AGY）"));
    assert.ok(findText(byData(back, "data-rc", "blockers")[0], AGY_NOT_LAUNCHED));
    assert.ok(findText(byData(front, "data-slot", "collected")[0].parentNode, "收藏中"));
    assert.strictEqual(byData(card, "data-slot", "active").length, 0, "no skill is shown as in effect");
    const adv = byData(back, "data-rc", "advanced")[0];
    assert.ok(findText(adv, "Tool ID") && findText(adv, "agy"));
  });

  await test("P20 the pool: the camp filter has AGY in order and keeps only AGY cards", async () => {
    const profiles = [mkProfile("a", "A", "claude", ALL_DENY), mkProfile("b", "B", "agy", ALL_DENY), mkProfile("c", "C", "codex", ALL_DENY)];
    const ctx = await openPool(profiles, catalogAgy, { "GET /api/agent-profiles/b/loadout": () => jsonResponse(agyLoadout(profiles[1])) });
    const bar = byData(main, "role", "group").find((n) => n.getAttribute("aria-label") === "依陣營篩選");
    assert.deepStrictEqual(bar.children.filter((n) => n.tag === "button").map((n) => n.getAttribute("data-filter")), ["all", "claude", "codex", "agy", "shared"]);
    assert.ok(findText(byData(main, "data-filter", "agy")[0], "Antigravity（AGY）"));
    ctx.localStorage.setItem("sid:teamCardTool", JSON.stringify("agy"));
    await ctx.viewTeam();
    const ids = walk(main).filter((n) => n.tag === "article" && n.getAttribute("data-profile-id")).map((n) => n.getAttribute("data-profile-id"));
    assert.deepStrictEqual(ids, ["b"]);
  });

  await test("P20 出發 on an AGY card: the pass says VBear does not start AGY, offers no preview or start, makes no request and shows no shield", async () => {
    const p = mkProfile("p-agy", "AGY 一號", "agy", VERIFIED);
    const ctx = freshContext(baseHandlers([p], catalogAgy, { "GET /api/agent-profiles/p-agy/loadout": () => jsonResponse(agyLoadout(p)) }));
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null, "p-agy", true);
    await tick();
    const d = dialog();
    assert.ok(d && findText(d, "出發通行證：AGY 一號"), "the pass opens");
    const notice = byData(d, "data-pass", "agy-not-launchable")[0];
    assert.ok(notice, "the plain sentence is on the pass before anything is typed");
    assert.ok(findText(notice, AGY_NOT_LAUNCHED));
    assert.ok(!findText(notice, "保護") && !findText(notice, "擋住"), "no word of protection");
    const confirm = btnByText(d, "確認啟動"), preview = btnByText(d, "產生預覽");
    assert.strictEqual(confirm.disabled, true);
    assert.strictEqual(preview.disabled, true, "there is nothing to preview");
    preview.dispatch("click"); confirm.dispatch("click");
    await tick();
    assert.strictEqual(fetchCalls.filter((c) => /agent-launch|preview|launch/.test(c.url) && c.options && c.options.method === "POST").length, 0, "no request to preview or start");
    const why = walk(d).find((n) => n.className === "small agent-launch-why");
    assert.ok(why && findText(why, AGY_NOT_LAUNCHED), "the reason beside the disabled button");
    assert.ok(!walk(d).some((n) => /armor-shield|pass-lines/.test(n.className || "")), "no shield, no limits listed");
    assert.ok(!byData(d, "data-pass", "front").length);
    // a Claude card's pass has no such notice
    const c = mkProfile("p-1", "Mine", "claude", ALL_DENY);
    const ctx2 = freshContext(baseHandlers([c], catalogAgy, { "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutBody(c)) }));
    evalAgentBuilderSlice(ctx2);
    await ctx2.viewWorkbench(null, null, "p-1", true);
    await tick();
    assert.strictEqual(byData(dialog(), "data-pass", "agy-not-launchable").length, 0);
    assert.strictEqual(btnByText(dialog(), "產生預覽").disabled, false);
  });

  await test("P20 source: the pass and the wizard speak of AGY in the words the server uses, and no AGY string claims a load or a protection", () => {
    const wizard = source.slice(source.indexOf("function openCardWizard("), source.indexOf("// ---- footer + save"));
    assert.ok(!/AGY[^"`\n]*(會載入|已保護|受保護|安全)/.test(wizard.replace(/不代表[^"]*/g, "")));
    assert.ok(source.includes("VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄"));
    assert.ok(source.includes("VBear 還不知道 AGY 會讀哪些技能"));
    assert.ok(source.includes("VBear 沒有掃描 AGY 的 Agent 角色，沒有可選的職業標籤"));
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL CARD POOL FRONTEND TESTS PASSED");
})();
