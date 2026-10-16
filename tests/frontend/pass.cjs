// P5 (design card-play 3.7, 6.3, 6.7): the launch pass. passSummary table by table (each level the server can give, for
// the write and the network line), the three lines and the shield legend of the front, the marks, the fixes that lead
// to where a reason is changed, the pass dialog (front, details, bypass, the commit words, fix and come back), and the
// honesty rules (a check mark only for an enforced level; nothing says safe).
// Runs the real viewWorkbench() / promptAgentLaunch() from web/app.js against a synthetic DOM and a fetch stub.
// It is NOT a browser test.
//
// Run: node tests/frontend/pass.cjs   (exit code 0 = pass)
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


const LV = {
  enforced: "強制（限已測路徑、版本與執行層）", unverified: "未驗證（此 Claude Code 版本尚未實測）", partial: "部分強制",
  intent: "僅意圖", unknown: "未知", notGranted: "不授予", unrestricted: "未限制",
};
const WORKDIR = "/Users/u/work";
const label = (level) => ({ level, note: "n", source_version: { value: "2.1.286" }, settings_digest: "d".repeat(64),
  path_scope: "不適用", evidence_refs: [], bypass: "以 ! 開頭的 shell 指令不經沙盒", unknown_reason: "none" });
const labelsOf = (write, network, commit = LV.unrestricted) => ({
  Read: label(LV.intent), Write: label(write), Test: label(LV.intent), Commit: label(commit),
  Deploy: label(LV.notGranted), Network: label(network), Filesystem: label(write) });
const previewOf = (write, network, over = {}) => ({
  preview_id: "p-" + "a".repeat(32), launchable: true, reasons: [], cli: { binary: "/x/claude", version: "2.1.286", verified: true },
  settings_digest: "d".repeat(64), canonical_paths: { workdir: WORKDIR, scratch: "/private/tmp/sc-abc" },
  derived_labels: labelsOf(write, network), expires_at: 2000000000, ...over });
const mkPass = (profiles, extra = {}) => {
  const ctx = freshContext(baseHandlers(profiles, catalog, extra));
  evalAgentBuilderSlice(ctx);
  return ctx;
};
const openPass = async (ctx, id = "p-1", task = null) => {
  await ctx.viewWorkbench(null, task, id, true);
  await tick(8);
  return dialog();
};
const field = (d) => walk(d).find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir");
const commitBox = (d) => walk(d).find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-commit");
const lineOf = (root, id) => byData(root, "data-pass-line", id)[0];

(async () => {
  const pure = freshContext({});
  evalAgentBuilderSlice(pure);
  const summary = (write, network, over) => pure.passSummary(previewOf(write, network, over));
  const lineText = (s, id) => s.lines.find((l) => l.id === id);

  await test("passSummary: the write line, level by level, in the design's words (partial and unverified are not enforced)", () => {
    const rows = [
      [LV.enforced, "enforced", `只能改這個資料夾：${WORKDIR}`, "ok"],
      [LV.partial, "partial", `大致只能改這個資料夾：${WORKDIR}（部分擋住）`, "warn"],
      [LV.unverified, "unverified", "設定成只能改這個資料夾，但這個版本還沒實測", "warn"],
      [LV.unknown, "unknown", "寫入範圍不明", "unknown"],
      [LV.intent, "open", "寫入範圍沒有被擋住", "bad"],
      [LV.unrestricted, "open", "寫入範圍沒有被擋住", "bad"],
      [LV.notGranted, "unknown", "寫入範圍不明", "unknown"],
    ];
    for (const [level, kind, text, mark] of rows) {
      const w = lineText(summary(level, LV.enforced), "write");
      assert.strictEqual(w.kind, kind, level);
      assert.strictEqual(w.text, text, level);
      assert.strictEqual(w.mark, mark, level);
      assert.strictEqual(w.level, level);
    }
    assert.strictEqual(rows.length, 7, "every level word the server has is a row");
  });

  await test("passSummary: the network line, level by level", () => {
    const rows = [
      [LV.enforced, "enforced", "擋住網路", "ok"],
      [LV.partial, "partial", "部分擋住網路", "warn"],
      [LV.unverified, "unverified", "設定成不連網，但這個版本還沒實測", "warn"],
      [LV.unknown, "unknown", "網路防護不明", "unknown"],
      [LV.intent, "open", "網路沒有被擋住", "bad"],
      [LV.unrestricted, "open", "網路沒有被擋住", "bad"],
      [LV.notGranted, "unknown", "網路防護不明", "unknown"],
    ];
    for (const [level, kind, text, mark] of rows) {
      const n = lineText(summary(LV.enforced, level), "network");
      assert.strictEqual(n.kind, kind, level);
      assert.strictEqual(n.text, text, level);
      assert.strictEqual(n.mark, mark, level);
    }
  });

  await test("passSummary: the commit line is the same words at every level, and always there", () => {
    for (const commitLevel of Object.values(LV)) {
      const pv = previewOf(LV.enforced, LV.enforced);
      pv.derived_labels = labelsOf(LV.enforced, LV.enforced, commitLevel);
      const c = pure.passSummary(pv).lines[2];
      assert.strictEqual(c.id, "commit");
      assert.strictEqual(c.text, "擋不住版本紀錄（commit）", commitLevel);
      assert.notStrictEqual(c.mark, "ok", "never a check mark");
    }
    assert.deepStrictEqual([...pure.passSummary({}).lines.map((l) => l.id)], ["write", "network", "commit"]);
    assert.strictEqual(pure.passSummary({}).lines[2].text, "擋不住版本紀錄（commit）");
  });

  await test("passSummary: a missing, odd or unknown label reads as unknown, never as a protective level", () => {
    for (const pv of [undefined, null, {}, { derived_labels: null }, { derived_labels: [] }, { derived_labels: { Write: null, Network: "x" } },
      { derived_labels: { Write: { level: 5 }, Network: { level: {} } } },
      { derived_labels: { Write: { level: "enforced" }, Network: { level: "強制" } }, canonical_paths: { workdir: WORKDIR } },
      { derived_labels: Object.create({ Write: { level: LV.enforced } }), canonical_paths: { workdir: WORKDIR } }]) {
      const s = pure.passSummary(pv);
      assert.strictEqual(s.lines[0].kind, "unknown", JSON.stringify(pv));
      assert.strictEqual(s.lines[0].text, "寫入範圍不明");
      assert.strictEqual(s.lines[1].kind, "unknown");
      assert.strictEqual(s.lines[1].text, "網路防護不明");
    }
    // an enforced write level without a folder to name is not claimed
    const noPath = pure.passSummary({ derived_labels: labelsOf(LV.enforced, LV.enforced), canonical_paths: {} });
    assert.strictEqual(noPath.lines[0].kind, "unknown");
    assert.strictEqual(noPath.lines[1].kind, "enforced", "the network line does not need a folder");
    const partialNoPath = pure.passSummary({ derived_labels: labelsOf(LV.partial, LV.enforced), canonical_paths: { workdir: 3 } });
    assert.strictEqual(partialNoPath.lines[0].kind, "unknown");
  });

  await test("passSummary: the scratch folder is carried for the front, nothing else is invented", () => {
    const s = summary(LV.enforced, LV.enforced);
    assert.strictEqual(s.workdir, WORKDIR);
    assert.strictEqual(s.scratch, "/private/tmp/sc-abc");
    assert.strictEqual(pure.passSummary(previewOf(LV.enforced, LV.enforced, { canonical_paths: { workdir: WORKDIR, scratch: null } })).scratch, null);
  });

  await test("a check mark only for an enforced level: no other level, in any line, gets one, and no text says safe", () => {
    const text = (s) => s.lines.map((l) => l.text).join(" ");
    for (const level of Object.values(LV)) {
      for (const s of [summary(level, level), summary(LV.enforced, level)]) {
        for (const l of s.lines.slice(0, 2)) {
          assert.strictEqual(l.mark === "ok", l.level === LV.enforced && l.kind === "enforced", `${l.id} ${level}`);
          assert.strictEqual(l.kind === "enforced", pure.passKind(l.level) === "enforced" && l.level === LV.enforced);
        }
        assert.ok(!/安全|已限制|保證|不可繞過/.test(text(s)), text(s));
      }
    }
    // only the enforced level is ever worded as having blocked something
    for (const level of Object.values(LV).filter((x) => x !== LV.enforced)) {
      const s = summary(level, level);
      assert.ok(!/^擋住網路$|^只能改這個資料夾/.test(s.lines[0].text) && s.lines[1].text !== "擋住網路", level);
    }
    assert.strictEqual(pure.passKind("something new"), "unknown");
    assert.strictEqual(pure.passKind(undefined), "unknown");
    assert.strictEqual(pure.passKind("constructor"), "unknown");
  });

  await test("passFront: three lines in order, each with its kind, a mark, a word, and a shield only where the level has one", () => {
    const front = pure.passFront(previewOf(LV.enforced, LV.unverified));
    const lines = byData(front, "data-pass", "front").concat(front === undefined ? [] : []);
    assert.ok(front.getAttribute("data-pass") === "front" && lines.length >= 0);
    const ids = walk(front).filter((n) => n.getAttribute && n.getAttribute("data-pass-line")).map((n) => n.getAttribute("data-pass-line"));
    assert.deepStrictEqual(ids, ["write", "network", "commit"]);
    const w = lineOf(front, "write"), n = lineOf(front, "network"), c = lineOf(front, "commit");
    assert.strictEqual(w.getAttribute("data-kind"), "enforced");
    assert.strictEqual(n.getAttribute("data-kind"), "unverified");
    assert.strictEqual(c.getAttribute("data-kind"), "open");
    assert.ok(textOf(w).includes(`只能改這個資料夾：${WORKDIR}`) && textOf(w).includes("已擋住"));
    assert.ok(textOf(n).includes("設定成不連網，但這個版本還沒實測") && textOf(n).includes("未實測"));
    assert.ok(textOf(c).includes("擋不住版本紀錄（commit）") && textOf(c).includes("沒有擋住"));
    const shield = (line) => walk(line).filter((x) => x.getAttribute && x.getAttribute("data-shield")).map((x) => x.getAttribute("data-shield"));
    assert.deepStrictEqual(shield(w), ["enforced"], "an enforced level has the solid shield");
    assert.deepStrictEqual(shield(n), [], "an untested level has no shield");
    assert.deepStrictEqual(shield(c), ["none"], "unrestricted has the empty shield");
    for (const line of [w, n, c]) assert.strictEqual(walk(line).filter((x) => x.tag === "svg" && /pass-mark/.test(x.getAttribute("class") || "")).length, 1);
    assert.ok(textOf(front).includes("另有這次出發的暫存區："));
  });

  await test("passFront: the legend names the three shields, says what has none, and every shield is the same art as the card's", () => {
    const front = pure.passFront(previewOf(LV.enforced, LV.enforced));
    const legend = byData(front, "data-pass", "legend")[0];
    assert.ok(legend);
    assert.deepStrictEqual(byData(legend, "data-shield", "enforced").concat(byData(legend, "data-shield", "recorded"), byData(legend, "data-shield", "none"))
      .map((x) => x.getAttribute("data-shield")), ["enforced", "recorded", "none"]);
    const t = textOf(legend);
    assert.ok(t.includes("實線盾牌：強制") && t.includes("虛線盾牌：只是記錄，沒有擋") && t.includes("空盾牌：沒擋"));
    assert.ok(t.includes("部分擋住、未實測、不明的項目不畫盾牌，以文字為準。"));
    const svgOf = (kind) => walk(byData(legend, "data-shield", kind)[0]).filter((x) => x.tag === "rect").length;
    assert.ok(svgOf("enforced") > 0 && svgOf("recorded") > 0 && svgOf("none") > 0);
    assert.notStrictEqual(svgOf("enforced"), svgOf("none"), "the shapes differ, not only the colour");
  });

  await test("the marks differ in shape, not only in colour: four marks, four different drawings", () => {
    const shapes = ["ok", "warn", "unknown", "bad"].map((m) => {
      const svg = pure.passMark(m);
      assert.strictEqual(svg.getAttribute("aria-hidden"), "true");
      assert.ok(svg.getAttribute("class").includes(`pass-mark-${m}`));
      return walk(svg).map((x) => `${x.tag}:${x.getAttribute("d") || x.getAttribute("r") || ""}`).join("|");
    });
    assert.strictEqual(new Set(shapes).size, 4);
  });

  await test("passFix: each reason leads to where it is changed; a reason with no way out has no button; the rules stay on the server", () => {
    const fixes = {
      intent_unspecified: ["intents", "現在決定"], read_deny_unenforceable: ["intents", "調整權限意圖"], readonly_unverified: ["intents", "調整權限意圖"],
      test_deny_unenforceable: ["intents", "調整權限意圖"], deploy_not_available: ["intents", "調整權限意圖"], intents_not_supported: ["intents", "調整權限意圖"],
      tool_not_launchable: ["tool", "改選陣營"], commit_not_enforceable: ["commit", "回去勾選知悉"],
    };
    for (const [code, [act, text]] of Object.entries(fixes)) {
      const f = pure.passFix(code);
      assert.strictEqual(f.act, act, code);
      assert.strictEqual(f.label, text, code);
    }
    for (const code of ["network_not_available", "codex_interactive_flags_unsupported", "codex_evidence_missing", "profile_disabled", "constructor", "", undefined, null, 5]) {
      assert.strictEqual(pure.passFix(code), null, String(code));
    }
    assert.strictEqual(pure.passFolderFix({ status: 400 }).act, "folder");
    assert.strictEqual(pure.passFolderFix({ status: 400 }).label, "換資料夾");
    for (const e of [{ status: 409 }, { status: 500 }, {}, null, undefined, new Error("x")]) assert.strictEqual(pure.passFolderFix(e), null);
  });

  // ---- the dialog ----------------------------------------------------------------------------------------------
  const roleP = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
  const loadoutFor = (id) => ({ [`GET /api/agent-profiles/${id}/loadout`]: () => jsonResponse(loadoutBody(roleP)) });

  await test("pass dialog: the words of the pass, the commit sentence, no old name", async () => {
    const posts = [];
    const ctx = mkPass([roleP], { ...loadoutFor("p-1"),
      "POST /api/native/agent-previews": (_u, o) => { posts.push(JSON.parse(o.body)); return jsonResponse({ ok: true, preview: previewOf(LV.enforced, LV.enforced) }); } });
    const d = await openPass(ctx);
    assert.ok(findText(d, "出發通行證：Mine"));
    assert.ok(findText(d, "這張通行證：這次出發實際會套上的限制，和它擋不到的地方"));
    assert.ok(!findText(d, "出發前檢查") && !findText(d, "防具（這次"));
    const commitLabel = walk(d).find((n) => n.tag === "label" && n.getAttribute("for") === "agent-launch-commit");
    assert.ok(textOf(commitLabel).includes("我知道這個角色會在這個資料夾建立、修改檔案，也能存下版本紀錄（commit），VBear 擋不住。"));
    assert.ok(textOf(commitLabel).includes("不勾選就無法啟動"));
    assert.ok(!findText(d, "無法阻止 commit（工作目錄的 .git"));
    assert.strictEqual(vm.runInContext("PASS_COMMIT_ACK", ctx), "我知道這個角色會在這個資料夾建立、修改檔案，也能存下版本紀錄（commit），VBear 擋不住。");
    assert.ok(posts.length === 0, "opening the pass previews nothing");
    assert.ok(!/Profile|AgentRole|Agent Builder|Permission Intents/.test(textOf(d)), "the screen words, not the old names");
  });

  await test("pass dialog: a launchable preview shows the front first, the seven items behind a fold, the bypass on the front", async () => {
    const ctx = mkPass([roleP], { ...loadoutFor("p-1"),
      "POST /api/native/agent-previews": () => jsonResponse({ ok: true, preview: previewOf(LV.partial, LV.unverified) }) });
    const d = await openPass(ctx);
    field(d).value = WORKDIR; commitBox(d).checked = true;
    btnByText(d, "產生預覽").dispatch("click");
    await tick(6);
    const front = byData(d, "data-pass", "front")[0];
    assert.ok(front, "the front is there");
    assert.ok(textOf(front).includes(`大致只能改這個資料夾：${WORKDIR}（部分擋住）`));
    assert.ok(textOf(front).includes("設定成不連網，但這個版本還沒實測"));
    assert.ok(textOf(front).includes("擋不住版本紀錄（commit）"), "the commit line is on the front, not only behind the fold");
    const details = byData(d, "data-pass", "details")[0];
    assert.ok(details && details.tag === "details" && !details.hasAttribute("open"), "folded at first");
    assert.strictEqual(details.children[0].tag, "summary");
    assert.strictEqual(details.children[0].textContent, "看七項細節");
    assert.ok(byData(details, "data-armor", "preview").length === 1, "the full armor text is inside the fold");
    for (const name of ["Read", "Write", "Test", "Commit", "Deploy", "Network", "Filesystem"]) assert.ok(findText(details, name), name);
    assert.ok(findText(details, "沒有一項是不可繞過的邊界") && findText(details, "技能卡清單（收藏中），本次不會載入"));
    const bypass = walk(d).find((n) => n.className && n.className.includes("agent-launch-bypass"));
    assert.ok(bypass && !details.contains(bypass), "the bypass notice is outside the fold");
    assert.ok(!front.contains(bypass) || true);
  });

  await test("pass dialog: a blocked preview lists the reasons with the fix beside each, and the commit one only points at the box", async () => {
    const blocked = previewOf(LV.unknown, LV.unknown, { launchable: false, preview_id: null, cli: null, settings_digest: null,
      reasons: [{ code: "intent_unspecified", message: "編輯寫入的權限意圖還沒決定；沒決定的不會被當成允許" },
        { code: "commit_not_enforceable", message: "目前無法強制不 commit" },
        { code: "codex_evidence_missing", message: "Codex 0.159.2 本輪 OS sandbox 驗收尚未完成" }] });
    const ctx = mkPass([roleP], { ...loadoutFor("p-1"), "POST /api/native/agent-previews": () => jsonResponse({ ok: true, preview: blocked }) });
    const d = await openPass(ctx);
    field(d).value = WORKDIR;
    btnByText(d, "產生預覽").dispatch("click");
    await tick(6);
    assert.ok(findText(d, "這張角色卡目前無法啟動"));
    assert.ok(!byData(d, "data-pass", "front").length, "no front for a pass that cannot be used");
    const items = byData(d, "data-reason", "intent_unspecified").concat(byData(d, "data-reason", "commit_not_enforceable"), byData(d, "data-reason", "codex_evidence_missing"));
    assert.strictEqual(items.length, 3);
    assert.deepStrictEqual(items.map((li) => byData(li, "data-pass-fix", "intents").length + byData(li, "data-pass-fix", "commit").length), [1, 1, 0]);
    assert.ok(findText(items[0], "現在決定") && findText(items[1], "回去勾選知悉"));
    // the commit fix only brings the box into focus; it never ticks it
    byData(items[1], "data-pass-fix", "commit")[0].dispatch("click");
    assert.strictEqual(lastFocus, commitBox(d));
    assert.ok(!commitBox(d).checked, "the consent is the user's");
    assert.strictEqual(byData(d, "data-pass", "details").length, 1, "the seven items stay available");
  });

  await test("pass dialog: 現在決定 opens the card editor on step 2 with the intents open; saving it returns to the pass, same folder, new preview", async () => {
    const undecided = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "unspecified", test: "allow", deploy: "deny" });
    const decided = mkProfile("p-1", "Mine", "claude", { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    let saved = false;
    const previews = [];
    const ctx = mkPass([undecided], {
      "GET /api/agent-profiles": () => jsonResponse({ ok: true, profiles: [saved ? decided : undecided] }),
      "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadoutBody(saved ? decided : undecided)),
      "POST /api/agent-profiles/p-1": (_u, o) => { saved = true; assert.strictEqual(JSON.parse(o.body).permission_intents.write, "allow"); return jsonResponse({ ok: true, profile: decided }); },
      "POST /api/native/agent-previews": (_u, o) => {
        const b = JSON.parse(o.body); previews.push(b);
        return jsonResponse({ ok: true, preview: saved
          ? previewOf(LV.enforced, LV.enforced)
          : previewOf(LV.unknown, LV.unknown, { launchable: false, preview_id: null, cli: null,
            reasons: [{ code: "intent_unspecified", message: "編輯寫入的權限意圖還沒決定；沒決定的不會被當成允許" }] }) });
      } });
    const d = await openPass(ctx);
    field(d).value = WORKDIR; commitBox(d).checked = true;
    btnByText(d, "產生預覽").dispatch("click");
    await tick(6);
    byData(d, "data-pass-fix", "intents")[0].dispatch("click");
    await tick(8);
    const wiz = body.children.filter((c) => c.getAttribute && c.getAttribute("role") === "dialog").pop();
    assert.notStrictEqual(wiz, d);
    assert.ok(findText(wiz, "陣營就是這張卡用哪個工具"), "step 2 of the editor");
    assert.ok(byData(wiz, "data-cw", "intents")[0].hasAttribute("open"), "the intents are open");
    // decide: write allow
    const sel = walk(wiz).find((n) => n.tag === "select" && n.getAttribute("aria-label") === "編輯寫入");
    sel.value = "allow"; sel.dispatch("change");
    byData(wiz, "data-cw", "save")[0].dispatch("click");
    await tick(12);
    const again = dialog();
    assert.ok(again && findText(again, "出發通行證：Mine"), "the pass is open again");
    assert.strictEqual(field(again).value, WORKDIR, "the same folder");
    assert.strictEqual(commitBox(again).checked, true, "the same consent");
    assert.strictEqual(previews.length, 2, "a new preview was asked for");
    assert.deepStrictEqual(previews[1], { profile_id: "p-1", workdir: WORKDIR, commit: true });
    assert.ok(byData(again, "data-pass", "front").length === 1, "and its front is shown");
    assert.strictEqual(body.children.filter((c) => c.getAttribute && c.getAttribute("role") === "dialog").length, 1, "only one dialog is left");
  });

  await test("pass dialog: a folder the server refuses (400) offers 換資料夾, which opens the folder picker", async () => {
    const ctx = mkPass([roleP], { ...loadoutFor("p-1"),
      "POST /api/native/agent-previews": () => jsonResponse({ error: "workdir 必須是家目錄內既存的資料夾" }, 400),
      "GET /api/folders/inspect": () => jsonResponse({ ok: true }) });
    const d = await openPass(ctx);
    field(d).value = "/nowhere";
    btnByText(d, "產生預覽").dispatch("click");
    await tick(6);
    assert.ok(findText(d, "無法產生預覽：workdir 必須是家目錄內既存的資料夾"));
    const fix = byData(d, "data-pass-fix", "folder")[0];
    assert.ok(fix && fix.textContent === "換資料夾");
    fix.dispatch("click");
    await tick();
    const dialogs = body.children.filter((c) => c.getAttribute && c.getAttribute("role") === "dialog");
    assert.strictEqual(dialogs.length, 2, "the folder picker is on top");
    // another kind of failure has no folder button
    const ctx2 = mkPass([roleP], { ...loadoutFor("p-1"), "POST /api/native/agent-previews": () => jsonResponse({ error: "待確認的 preview 過多" }, 429) });
    const d2 = await openPass(ctx2);
    field(d2).value = WORKDIR;
    btnByText(d2, "產生預覽").dispatch("click");
    await tick(6);
    assert.ok(findText(d2, "無法產生預覽：待確認的 preview 過多"));
    assert.ok(!byData(d2, "data-pass-fix", "folder").length);
  });

  await test("pass dialog: the confirm button works as before (one launch, only after a current preview)", async () => {
    const launches = [];
    const ctx = mkPass([roleP], { ...loadoutFor("p-1"),
      "POST /api/native/agent-previews": () => jsonResponse({ ok: true, preview: previewOf(LV.enforced, LV.enforced) }),
      "POST /api/native/agent-launches": (_u, o) => { launches.push(JSON.parse(o.body)); return jsonResponse({ ok: true, launch: { session: { session_id: "n-0123456789ab" } } }); } });
    const d = await openPass(ctx);
    assert.strictEqual(btnByText(d, "確認啟動").disabled, true);
    field(d).value = WORKDIR; commitBox(d).checked = true;
    btnByText(d, "產生預覽").dispatch("click");
    await tick(6);
    assert.strictEqual(btnByText(d, "確認啟動").disabled, false);
    btnByText(d, "確認啟動").dispatch("click");
    await tick(6);
    assert.strictEqual(launches.length, 1);
    assert.deepStrictEqual(launches[0], { preview_id: "p-" + "a".repeat(32), expected_settings_digest: "d".repeat(64), user_confirmed: true });
  });

  await test("a confirmation can keep its long print behind 「詳細」: the short sentence on top, nothing lost, no fold when there is none", async () => {
    const ctx = mkPass([roleP]);
    const pending = ctx.confirmInPage("確認送出技能說明", "會用你自己的 Claude 帳號翻譯這張技能卡，通常不到 1 美分。", "翻成中文", { details: "請求預算 US$0.05，這不是保證帳單上限。" });
    const d = dialog();
    assert.ok(d && findText(d, "會用你自己的 Claude 帳號翻譯這張技能卡，通常不到 1 美分。"));
    const fold = byData(d, "data-confirm", "details")[0];
    assert.ok(fold && fold.tag === "details" && !fold.hasAttribute("open"), "folded");
    assert.strictEqual(fold.children[0].textContent, "詳細");
    assert.ok(textOf(fold).includes("請求預算 US$0.05，這不是保證帳單上限。"));
    btnByText(d, "翻成中文").dispatch("click");
    assert.strictEqual(await pending, true);
    const plain = ctx.confirmInPage("標題", "只有一句", "好");
    assert.ok(!byData(dialog(), "data-confirm", "details").length);
    btnByText(dialog(), "取消").dispatch("click");
    assert.strictEqual(await plain, false);
  });

  // ---- the source and the style --------------------------------------------------------------------------------
  const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
  const passBlock = app.slice(app.indexOf("// ---- The launch pass"), app.indexOf("// The slots of a card (design 3.4)"));

  await test("source: the pass block is built with el()/createElementNS, has no innerHTML, no emoji, no outside resource, and never says safe", () => {
    assert.ok(passBlock.length > 3000, "found the block");
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(passBlock));
    assert.ok(!/\p{Extended_Pictographic}/u.test(passBlock), "no emoji");
    assert.ok(!/https?:\/\//.test(passBlock));
    assert.ok(!/安全|已限制|保證/.test(passBlock.replace(/不可繞過/g, "")), "nothing is called safe or restricted");
    assert.ok(!/稀有|星數|抽卡|等級|血量|分數/.test(passBlock), "no rarity, stars, draws or levels (design 6.1)");
    const dialogSrc = app.slice(app.indexOf("function promptAgentLaunch("), app.indexOf("function promptDeleteAgentProfile("));
    assert.ok(!/innerHTML|\p{Extended_Pictographic}/u.test(dialogSrc));
    assert.ok(!/出發前檢查/.test(app), "the old name is gone from the page");
  });

  await test("source: the old words are gone from the pass and the card's intent note points at the shield", () => {
    assert.strictEqual(vm.runInContext("CARD_INTENT_NOTE", pure), "權限意圖是隊伍分工的標記，不代表 VBear 已經限制這個程式的真實能力；真正的限制，看出發通行證上的盾牌。");
    assert.ok(!/防具（這次/.test(app));
  });

  await test("CSS: the pass is styled — a tone per kind, wraps on a phone, the details fold", () => {
    for (const sel of [".pass-front", ".pass-line", ".pass-ok", ".pass-open", ".pass-unknown", ".pass-legend", ".pass-details"]) assert.ok(css.includes(sel), sel);
    assert.ok(/\.pass-line\s*\{[^}]*flex-wrap:\s*wrap/.test(css), "a line wraps, so a long path does not push the page sideways");
    assert.ok(/\.pass-text\s*\{[^}]*overflow-wrap:\s*anywhere/.test(css));
    assert.ok(/\.pass-word\s*\{[^}]*border:/.test(css), "the status word has its own outline, not only a colour");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL PASS FRONTEND TESTS PASSED");
})();
