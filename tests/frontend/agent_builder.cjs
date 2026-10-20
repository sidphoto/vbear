// Tests the Phase C Agent Builder UI by clicking the real "Agent" tab
// inside the rendered right column. Runs the real viewWorkbench() /
// renderRightColumn() / renderAgentTabContent() / promptAgentProfileEditor()
// / promptDeleteAgentProfile() from web/app.js against a synthetic DOM and
// a controllable fetch stub. It is NOT a browser test: real keyboard focus,
// CSS, screen readers, and the actual HTTP API are untested.
//
// Run: node tests/frontend/agent_builder.cjs   (exit code 0 = pass)
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
    history: { replaceState: () => {} },
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

function findRightColumn() {
  // Right column is the element with class wb-right inside the workbench
  // shell. Returned by walk that filters on className.
  return walk(main).find((n) => n.className && n.className.includes("wb-right"));
}

async function switchToAgentTab() {
  // Find a button whose text starts with the agent tab label.
  const btn = walk(main).find((n) =>
    n.tag === "button" && /^角色$/.test((n.textContent || "").trim()));
  if (!btn) throw new Error("agent tab button not found");
  btn.dispatch("click");
  // yield microtasks
  await new Promise((r) => setImmediate(r));
}

async function clickCreateAgentProfileButton() {
  const btn = walk(main).find((n) =>
    n.tag === "button" && /＋ 新角色卡/.test(n.textContent || ""));
  if (!btn) throw new Error("create button not found");
  btn.dispatch("click");
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
}

// The role tab shows the same two-faced cards as the card pool (P11 3.6): one article per card, found by its name.
function roleCardNode(name) {
  return walk(main).find((n) => n.tag === "article" && n.getAttribute("aria-label") === `角色卡：${name}`);
}
function cardButton(name, label) {
  const card = roleCardNode(name);
  return card ? walk(card).find((n) => n.tag === "button" && (n.textContent || "").trim() === label) : undefined;
}

function findModalInBody() {
  return body.children.find((c) => c !== main && c.tag === "div"
                                    && c.getAttribute("role") === "dialog");
}

(async () => {
  // Test 1: render the workbench, click the Agent tab, confirm empty-state
  // shows disclosures, the create button, and the boundary disclosure.
  {
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [],
                                                          attention: [], usage: { sessions: [] },
                                                          runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: [] }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
    });
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    const right = findRightColumn();
    assert.ok(right, "right column present");
    assert.ok(findText(right, "角色卡"), "title rendered");
    assert.ok(findText(right, "技能卡僅為挑選紀錄"), "honest disclosure present");
    assert.ok(findText(right, "絕對不會寫入 ~/.codex"), "boundary disclosure present");
    assert.ok(findText(right, "＋ 新角色卡"), "create button visible");
    console.log("ok empty-state renders title, disclosures, create button");
  }

  // Test 2: list shows both profiles, and the unresolved warning surfaces.
  {
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [],
                                                          attention: [], usage: { sessions: [] },
                                                          runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: profilesList }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
    });
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    const right = findRightColumn();
    assert.ok(findText(right, "First"), "first profile name in list");
    assert.ok(findText(right, "Stuck"), "second profile name in list");
    assert.ok(findText(right, "1 張目前索引找不到"), "unresolved warning surfaced on the role card");
    assert.ok(!findText(right, "已從掃描結果中消失"), "not worded as 'disappeared' (design v1.1 #6)");
    console.log("ok list+unresolved-warning");
  }

  // Test 3: clicking the create button opens the editor modal with
  // permission_intents populated as defaults, and save POSTs a profile.
  {
    const posts = [];
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [],
                                                          attention: [], usage: { sessions: [] },
                                                          runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: [] }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
      "POST /api/agent-profiles":    (url, options) => {
        const body = JSON.parse(options.body);
        posts.push({ url, body });
        return jsonResponse({ ok: true, profile: {
          id: "p-NEW", name: body.name, profession_role_id: body.profession_role_id,
          model: body.model, equipped_skill_ids: body.equipped_skill_ids,
          permission_intents: body.permission_intents, enabled: body.enabled,
          created_at: 1, updated_at: 1,
          _unresolved: { profession: false, skills: [] } } });
      },
    });
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    await clickCreateAgentProfileButton();
    const modal = findModalInBody();
    assert.ok(modal, "modal opened on create click");
    const inputs = walk(modal).filter((n) => n.tag === "input");
    assert.ok(inputs.length >= 1, "modal has inputs");
    inputs[0].dispatch("input", { target: Object.assign(inputs[0], { value: "My new profile" }) });
    const btn = (label) => walk(modal).filter((n) =>
      n.tag === "button" && (n.textContent || "").trim() === label)[0];
    btn("下一步").dispatch("click");
    btn("下一步").dispatch("click");
    const saveBtn = btn("建立");
    assert.ok(saveBtn, "save button labelled  建立 (third step)");
    saveBtn.dispatch("click");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const createPost = posts.find((x) => x.url === "/api/agent-profiles");
    assert.ok(createPost, "create POST was made to /api/agent-profiles");
    assert.equal(createPost.body.name, "My new profile");
    assert.deepEqual(createPost.body.permission_intents,
                     { read: "allow", write: "allow", test: "allow", deploy: "deny" });
    assert.equal(createPost.body.enabled, true);
    console.log("ok wizard sends POST with every intent decided (the verified combination without a position, R10)");
  }

  // Test 4: delete confirm → POST to /<id>/delete (then a list refresh).
  {
    const posts = [];
    const refreshProfile = profilesList.slice();
    let listPayload = refreshProfile;
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [],
                                                          attention: [], usage: { sessions: [] },
                                                          runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => {
        return jsonResponse({ ok: true, profiles: listPayload });
      },
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
      "POST /api/agent-profiles/p-1/delete": () => {
        posts.push({ url: "/api/agent-profiles/p-1/delete" });
        listPayload = listPayload.filter((p) => p.id !== "p-1");
        return jsonResponse({ ok: true, deleted: "p-1" });
      },
    });
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    // The card's back holds 編輯／複製／刪除 (and the tab adds 停用／啟用 there).
    const deleteBtn = cardButton("First", "刪除");
    assert.ok(deleteBtn, "delete button labelled  刪除, on the First card");
    assert.ok(cardButton("First", "編輯") && cardButton("First", "複製") && cardButton("First", "停用"), "and its siblings");
    assert.ok(cardButton("Stuck", "啟用"), "a card that is switched off offers 啟用");
    deleteBtn.dispatch("click");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    assert.ok(posts.some((x) => x.url === "/api/agent-profiles/p-1/delete"),
              "delete POST was made to /<id>/delete");
    console.log("ok delete confirm → POST to /<id>/delete");
  }

  // Preview-and-launch dialog (R3 S0): preview first, confirm only when the
  // server says launchable, single use, navigate to the new terminal.
  {
    const posts = [];
    const label = (level, note, unknown = "none") => ({ level, note, source_version: { value: "2.1.286" },
      settings_digest: "d".repeat(64), path_scope: "不適用", evidence_refs: [], bypass: "以 ! 開頭的 shell 指令不經沙盒", unknown_reason: unknown });
    const labels = { Read: label("僅意圖", "讀取不隔離"), Write: label("部分強制", "Bash 寫入受限"),
      Test: label("僅意圖", "可執行指令"), Commit: label("未限制", ".git 可寫", "未測試 denyWrite .git"),
      Deploy: label("不授予", "不提供"), Network: label("強制（限已測路徑、版本與執行層）", "空 allowlist"),
      Filesystem: label("強制（限已測路徑、版本與執行層）", "寫入邊界") };
    const launchable = { preview_id: "p-" + "a".repeat(32), launchable: true, reasons: [],
      cli: { binary: "/x/claude", version: "2.1.286" }, settings_digest: "d".repeat(64),
      canonical_paths: { workdir: "/Users/u/work", scratch: "/private/tmp/sc-abc" },
      derived_labels: labels, expires_at: 2000000000 };
    const blocked = { preview_id: null, launchable: false,
      reasons: [{ code: "commit_not_enforceable", message: "目前無法強制不 commit" }], cli: null,
      settings_digest: null, canonical_paths: { workdir: "/Users/u/work", scratch: null },
      derived_labels: labels, expires_at: null };
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [], attention: [],
                                                          usage: { sessions: [] }, runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: profilesList }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
      "POST /api/native/agent-previews": (_u, o) => {
        const body = JSON.parse(o.body);
        posts.push({ url: "previews", body });
        return jsonResponse({ ok: true, preview: body.commit ? launchable : blocked });
      },
      "POST /api/native/agent-launches": (_u, o) => {
        posts.push({ url: "launches", body: JSON.parse(o.body) });
        return jsonResponse({ ok: true, launch: { state: "profile_managed", session: { session_id: "n-0123456789ab" } } });
      },
    });
    const tick = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    await tick();
    const openBtn = cardButton("First", "出發");
    assert.ok(openBtn, "the card front offers 出發, which opens the launch pass");
    assert.ok(!walk(main).some((n) => n.tag === "button" && (n.textContent || "").trim() === "出發通行證"), "the old button name is gone from the tab");
    assert.ok(!walk(main).some((n) => (n.textContent || "").trim() === "預覽並啟動"), "the old name is gone");
    openBtn.dispatch("click");
    await tick();
    const modal = findModalInBody();
    assert.ok(modal, "launch dialog opened");
    assert.ok(findText(modal, "出發通行證：First"), "the dialog is named like the button");
    assert.ok(findText(modal, "現在不能出發：還沒有產生這次的預覽"), "the button is off with a reason beside it");
    const button = (text) => walk(modal).find((n) => n.tag === "button" && (n.textContent || "").trim() === text);
    const workdir = walk(modal).find((n) => n.tag === "input" && n.getAttribute("type") === "text");
    const commit = walk(modal).find((n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
    assert.strictEqual(button("確認啟動").disabled, true, "confirm disabled before any preview");

    workdir.value = "/Users/u/work";
    button("產生預覽").dispatch("click");
    await tick();
    assert.deepStrictEqual(posts[0].body, { profile_id: "p-1", workdir: "/Users/u/work", commit: false });
    assert.ok(findText(modal, "這張角色卡目前無法啟動") && findText(modal, "目前無法強制不 commit"),
              "non-launchable preview shows the reason");
    assert.ok(findText(modal, "現在不能出發：目前無法強制不 commit"), "the reason is also beside the off button");
    assert.strictEqual(button("確認啟動").disabled, true, "confirm stays disabled when not launchable");

    commit.checked = true;
    commit.dispatch("change");
    button("產生預覽").dispatch("click");
    await tick();
    assert.strictEqual(posts[1].body.commit, true);
    for (const name of Object.keys(labels)) assert.ok(findText(modal, name), `label ${name} rendered`);
    // the actual labels of this preview, in the five groups, with their own level words
    const groups = walk(modal).filter((n) => n.getAttribute && n.getAttribute("data-armor-group"));
    assert.deepStrictEqual(groups.map((g) => g.getAttribute("data-armor-group")),
      ["blocked", "partial", "not_granted", "not_blocked", "unproven"]);
    const inGroup = (id) => walk(groups.find((g) => g.getAttribute("data-armor-group") === id))
      .filter((n) => n.tag === "strong").map((n) => n.textContent);
    assert.deepStrictEqual(inGroup("blocked"), ["Network", "Filesystem"]);
    assert.deepStrictEqual(inGroup("partial"), ["Write"]);
    assert.deepStrictEqual(inGroup("not_granted"), ["Deploy"]);
    assert.deepStrictEqual(inGroup("not_blocked"), ["Read", "Test", "Commit"]);
    assert.deepStrictEqual(inGroup("unproven"), []);
    assert.ok(groups.every((g) => g.tag === "section" && g.className === "rc-armor-group"), "same element and class");
    assert.ok(findText(modal, "技能卡清單（收藏中），本次不會載入") && findText(modal, "這次出發不會把這些技能帶上"));
    assert.ok(findText(modal, "alpha"), "the chosen skill is listed by name");
    assert.ok(findText(modal, "版本驗證"), "the version verification row");
    assert.ok(findText(modal, "未限制") && findText(modal, "未測試 denyWrite .git"), "level and unknown reason shown");
    assert.ok(findText(modal, "沒有一項是不可繞過的邊界"), "bypass disclosure shown");
    assert.ok(findText(modal, "可繞過") && findText(modal, "以 ! 開頭的 shell 指令不經沙盒"),
              "the concrete bypass from the labels is shown (S0 browser QA finding)");
    assert.strictEqual(walk(modal).filter((n) => (n.textContent || "") === "以 ! 開頭的 shell 指令不經沙盒").length, 1,
                       "the shared bypass text is shown once, not per label");
    assert.strictEqual(button("確認啟動").disabled, false, "confirm enabled for a launchable preview");

    workdir.value = "/Users/u/other";
    workdir.dispatch("input");
    assert.strictEqual(button("確認啟動").disabled, true, "changing an input invalidates the preview");
    button("確認啟動").dispatch("click");
    await tick();
    assert.ok(!posts.some((x) => x.url === "launches"), "no launch without a current preview");

    button("產生預覽").dispatch("click");
    await tick();
    button("確認啟動").dispatch("click");
    await tick();
    const launch = posts.find((x) => x.url === "launches");
    assert.deepStrictEqual(launch.body, { preview_id: launchable.preview_id,
      expected_settings_digest: launchable.settings_digest, user_confirmed: true });
    assert.strictEqual(posts.filter((x) => x.url === "launches").length, 1, "exactly one launch request");
    assert.strictEqual(ctx.location.hash, "#/term/n-0123456789ab", "navigates to the new terminal");
    assert.ok(!findModalInBody(), "dialog closed after launch");
    console.log("ok preview → confirm → launch dialog");
  }

  // A nameless skill removed from a role: the confirmation names it by its ID, not by an object.
  {
    const miss = (detail = "") => ({ value: null, origin: "missing", detail });
    const ctx = freshContext({
      "GET /api/skills/s-7?view=card": () => jsonResponse({ ok: true, index: { loaded: true, generated_at: 1 },
        skill: { skill_id: "s-7", name: miss(), tool: miss(), scope: miss(), activation: "active", installed: true,
                 activation_reason: "r", status_source: { origin: "derived", detail: "d" },
                 description: miss(), when_to_use: miss(), inputs: miss(), outputs: miss(), dependencies: miss(),
                 categories: { value: null, origin: "missing", detail: "", matches: [] },
                 referenced_files: { count: 0, items: [], truncated: false, note: "n", origin: "derived", detail: "x" },
                 missing_files: { items: [], origin: "derived", detail: "掃描結果" },
                 warnings: { items: [], origin: "derived", detail: "掃描結果" } },
        added_to_roles: { items: [], effective: false, note: "n", origin: "user", detail: "d" },
        observation: { state: "unavailable", window_days: null, source: "執行觀察", origin: "runtime", detail: "d" },
        marketplace_copies: [], marketplace_source: { origin: "derived", detail: "d" }, effect_note: "e" }),
    });
    evalAgentBuilderSlice(ctx);
    await ctx.openSkillCard("s-7", { profile: { id: "p-1", name: "First", equipped_skill_ids: ["s-7"] } });
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const modal = findModalInBody();
    const remove = walk(modal).find((n) => n.tag === "button" && (n.textContent || "") === "從這個角色移除");
    assert.ok(remove, "the remove action is there");
    remove.dispatch("click");
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const dialogs = body.children.filter((c) => c !== main && c.tag === "div" && c.getAttribute("role") === "dialog");
    const confirm = dialogs[dialogs.length - 1];
    assert.ok(findText(confirm, "把「未提供（ID：s-7）」從角色「First」"), "a missing name reads 未提供（ID：…）");
    assert.ok(!findText(confirm, "[object Object]"));
    console.log("ok remove confirmation names a nameless skill by its ID");
  }

  // The pre-launch dialog of a Codex role: its own words only, the reason beside the button, and nothing about
  // a Claude Code version, its terminal title or a Haiku call (AGY QA).
  {
    const label = (level, note, unknown = "none", evidence = []) => ({ level, note, source_version: { value: "0.159.2" },
      settings_digest: "d".repeat(64), path_scope: "不適用", evidence_refs: evidence, bypass: "以 ! 開頭的 shell 指令不經沙盒",
      unknown_reason: unknown });
    const labels = { Read: label("僅意圖", "讀取不隔離"), Write: label("強制（限已測路徑、版本與執行層）", "限工作目錄",
        "none", [".local/qa/codex-acceptance.json"]),
      Test: label("僅意圖", "可執行指令"), Commit: label("未限制", ".git 可寫"), Deploy: label("不授予", "不提供"),
      Network: label("未知", "network_access=false 尚無本輪 OS 負向證據", "尚無證據"),
      Filesystem: label("強制（限已測路徑、版本與執行層）", "寫入邊界", "none", [".local/qa/codex-acceptance.json"]) };
    const groupsNoClaude = [
      { id: "blocked", label: "擋住了", levels: ["強制（限已測路徑、版本與執行層）"] },
      { id: "partial", label: "部分擋住", levels: ["部分強制"] },
      { id: "not_granted", label: "沒有專用權限", levels: ["不授予"] },
      { id: "not_blocked", label: "沒有擋", levels: ["僅意圖", "未限制"] },
      { id: "unproven", label: "未證明", levels: ["未知"] }];
    const launchable = { preview_id: "p-" + "b".repeat(32), launchable: true, reasons: [],
      cli: { binary: "/x/codex", version: "0.159.2", verified: true, activity_verified: false, activity_last_failure: null },
      settings_digest: "d".repeat(64), canonical_paths: { workdir: "/Users/u/work", scratch: "/private/tmp/sc-abc" },
      derived_labels: labels, armor_groups: groupsNoClaude, expires_at: 2000000000 };
    const blocked = { preview_id: null, launchable: false,
      reasons: [{ code: "codex_interactive_flags_unsupported", message: "Codex 的互動模式還不能安全地受管啟動" }],
      cli: null, settings_digest: null, canonical_paths: { workdir: "/Users/u/work", scratch: null },
      derived_labels: Object.fromEntries(Object.keys(labels).map((k) => [k, label("未知", "此角色卡無法啟動，未產生設定",
        "此角色卡無法啟動，未產生設定")])), armor_groups: groupsNoClaude, expires_at: null };
    let answer = launchable;
    const loadout = { ok: true,
      profile: { id: "p-2", name: "Stuck", enabled: false, tool: "codex", model_id: "gpt-test", profession_role_id: "r-2",
                 permission_intents: {}, intents_note: "只是記錄，不會變成實際權限" },
      index: { loaded: true, generated_at: 1791770000 }, profession: { state: "none", role_id: null },
      skills: { title: "已選技能（VBear 啟動時不載入）", items: [], note: "n" },
      version_status: { state: "unknown", text: "未知（這個畫面不探測 Codex 版本）" },
      armor: { applicable: true, basis: "verified_setting", title: "防具（以 Codex 已記錄的驗證證據為準）",
               basis_note: "b", preview_decides: "實際以出發通行證為準",
               launch_note: "目前無法從 VBear 啟動這個角色（Codex 的互動模式還不能安全地受管啟動）",
               groups: groupsNoClaude, items: [] },
      blockers: [{ code: "profile_disabled", message: "這張角色卡已停用" }], blockers_note: "n" };
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [], attention: [],
                                                          usage: { sessions: [] }, runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: profilesList }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
      "GET /api/agent-profiles/p-2/loadout": () => jsonResponse(loadout),
      "POST /api/native/agent-previews": () => jsonResponse({ ok: true, preview: answer }),
    });
    const tick = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r)); };
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    await tick();
    // the reason a card cannot go is on its own front, beside 出發 (the card pool's light)
    const light = walk(roleCardNode("Stuck")).find((n) => n.getAttribute && n.getAttribute("data-pcard") === "light");
    assert.ok(light, "a light for the reason is on the card");
    // (what the light says for each state, blockers included, is card_pool.cjs's)
    assert.ok(cardButton("Stuck", "出發"), "the front holds the button");
    cardButton("Stuck", "出發").dispatch("click");
    await tick();
    const modal = findModalInBody();
    const button = (text) => walk(modal).find((n) => n.tag === "button" && (n.textContent || "").trim() === text);
    const workdir = walk(modal).find((n) => n.tag === "input" && n.getAttribute("type") === "text");
    const commit = walk(modal).find((n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
    workdir.value = "/Users/u/work";
    commit.checked = true;
    commit.dispatch("change");
    button("產生預覽").dispatch("click");
    await tick();
    assert.ok(findText(modal, "Codex CLI 0.159.2"), "the version carries the right tool name");
    for (const word of ["Claude", "Haiku", "工作中／等你回覆", "驗證這個版本", "再驗證一次", "終端標題", "尚未實測"]) {
      assert.ok(!findText(modal, word), `a Codex preview has no 「${word}」`);
    }
    assert.ok(!walk(modal).some((n) => n.tag === "button" && /驗證/.test(n.textContent || "")), "no verify button");
    const unproven = walk(modal).find((n) => n.getAttribute && n.getAttribute("data-armor-group") === "unproven");
    assert.ok(findText(unproven, "未證明 · 未知"), "the group lists only the levels this tool can show");
    assert.ok(findText(modal, ".local/qa/codex-acceptance.json"), "the evidence reference is shown");
    assert.strictEqual(button("確認啟動").disabled, false, "a launchable Codex preview can be confirmed");

    // a preview with the reasons it cannot be launched: shown, and the confirm button stays off with its reason
    answer = blocked;
    workdir.dispatch("input");
    commit.checked = true;
    commit.dispatch("change");
    button("產生預覽").dispatch("click");
    await tick();
    assert.ok(findText(modal, "這張角色卡目前無法啟動") && findText(modal, "Codex 的互動模式還不能安全地受管啟動"));
    assert.strictEqual(button("確認啟動").disabled, true);
    assert.ok(findText(modal, "現在不能出發：Codex 的互動模式還不能安全地受管啟動"));
    for (const word of ["Claude", "Haiku", "尚未實測"]) assert.ok(!findText(modal, word), `blocked: no 「${word}」`);

    // an answer without the server's groups still never lists the Claude-only level on a Codex role
    answer = { ...launchable, armor_groups: undefined };
    workdir.dispatch("input");
    commit.checked = true;
    commit.dispatch("change");
    button("產生預覽").dispatch("click");
    await tick();
    assert.ok(!findText(modal, "尚未實測") && !findText(modal, "Claude"));
    console.log("ok Codex pre-launch dialog: its own words, the reason beside the button, no Claude wording");
  }

  // A profile of another tool (shared): the dialog shows what the preview returned and no tool's words.
  {
    const unknown = (note) => ({ level: "未知", note, source_version: { value: "不適用" }, settings_digest: "none",
      path_scope: "不適用", evidence_refs: [], bypass: "使用者在進階終端可自行改變 CLI 行為；此標籤只約束 Agent，不是不可繞過的邊界",
      unknown_reason: note });
    const names = ["Read", "Write", "Test", "Commit", "Deploy", "Network", "Filesystem"];
    const groups = [
      { id: "blocked", label: "擋住了", levels: ["強制（限已測路徑、版本與執行層）"] },
      { id: "partial", label: "部分擋住", levels: ["部分強制"] },
      { id: "not_granted", label: "沒有專用權限", levels: ["不授予"] },
      { id: "not_blocked", label: "沒有擋", levels: ["僅意圖", "未限制"] },
      { id: "unproven", label: "未證明", levels: ["未知"] }];
    const note = "此角色卡無法啟動，未產生設定";
    const blocked = { preview_id: null, launchable: false,
      reasons: [{ code: "tool_not_launchable", message: "shared 不是可啟動的工具" }], cli: null,
      settings_digest: null, canonical_paths: { workdir: "/Users/u/work", scratch: null },
      derived_labels: Object.fromEntries(names.map((n) => [n, unknown(note)])), armor_groups: groups, expires_at: null };
    let answer = blocked;
    const shared = { id: "p-3", name: "Common", profession_role_id: null, model: { tool: "shared", model_id: "" },
      equipped_skill_ids: [], permission_intents: { read: "unspecified", write: "unspecified", test: "unspecified",
        deploy: "unspecified" }, enabled: true, created_at: 1700000020, updated_at: 1700000020,
      _unresolved: { profession: false, skills: [] } };
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [], attention: [],
                                                          usage: { sessions: [] }, runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: profilesList.concat([shared]) }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
      "GET /api/agent-profiles/p-3/loadout": () => jsonResponse({ ok: true,
        profile: { id: "p-3", name: "Common", enabled: true, tool: "shared", model_id: null, profession_role_id: null,
                   permission_intents: {}, intents_note: "n" },
        index: { loaded: true, generated_at: 1 }, profession: { state: "none", role_id: null },
        skills: { title: "已選技能（VBear 啟動時不載入）", items: [], note: "n" },
        version_status: { state: "unknown", text: "未知" },
        armor: { applicable: false, why: "shared 不是可啟動的工具，沒有防具" }, blockers: [] }),
      "POST /api/native/agent-previews": () => jsonResponse({ ok: true, preview: answer }),
    });
    const tick = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r)); };
    evalAgentBuilderSlice(ctx);
    await ctx.viewWorkbench(null, null);
    await switchToAgentTab();
    await tick();
    cardButton("Common", "出發").dispatch("click");
    await tick();
    const modal = findModalInBody();
    const button = (text) => walk(modal).find((n) => n.tag === "button" && (n.textContent || "").trim() === text);
    const workdir = walk(modal).find((n) => n.tag === "input" && n.getAttribute("type") === "text");
    const commit = walk(modal).find((n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
    for (const variant of [blocked, { ...blocked, armor_groups: undefined }]) {
      answer = variant;
      workdir.value = "/Users/u/work";
      workdir.dispatch("input");
      commit.checked = true;
      commit.dispatch("change");
      button("產生預覽").dispatch("click");
      await tick();
      assert.ok(findText(modal, "這張角色卡目前無法啟動") && findText(modal, "shared 不是可啟動的工具"), "the reason is shown");
      assert.strictEqual(button("確認啟動").disabled, true);
      assert.ok(findText(modal, "現在不能出發：shared 不是可啟動的工具"));
      for (const word of ["Claude", "Codex", "Haiku", "尚未實測", "驗證這個版本"]) {
        assert.ok(!findText(modal, word), `another tool's dialog has no 「${word}」`);
      }
    }
    console.log("ok another tool's pre-launch dialog shows only the reasons, in no tool's words");
  }

  // Close button for native sessions (R3 S0 acceptance finding: the console
  // had no way to close a session, so a managed session was never cleaned).
  {
    const posts = [];
    let reply = { ok: true, closed: "n-0123456789ab", managed: { launch_id: "l-1", cleaned: true } };
    let failureStatus = 200;
    const ctx = freshContext({
      "POST /api/native/sessions/n-0123456789ab/close": (u) => {
        posts.push(u);
        return failureStatus === 200 ? jsonResponse(reply) : jsonResponse({ error: "沒有這個 session" }, failureStatus);
      },
    });
    evalAgentBuilderSlice(ctx);
    const tick = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
    assert.strictEqual(ctx.closeSessionButton("w1:p2"), null, "non-native ids get no close button");
    assert.strictEqual(ctx.closeSessionButton("n-xyz"), null, "malformed ids get no close button");
    // Clicks "關閉終端", then answers the in-page dialog with confirm or cancel.
    const confirmDialog = async (answer) => {
      const dlg = findModalInBody();
      assert.ok(dlg, "an in-page confirmation dialog opened");
      const pick = walk(dlg).find((n) => n.tag === "button"
        && (n.textContent || "").trim() === (answer ? "關閉終端" : "取消"));
      assert.ok(pick, "dialog offers the expected button");
      pick.dispatch("click");
      await tick();
      assert.ok(!findModalInBody(), "dialog closed after answering");
    };
    const closeVia = async (answer = true) => {
      ctx.closeSessionButton("n-0123456789ab").dispatch("click");
      await tick();
      await confirmDialog(answer);
    };
    const btn = ctx.closeSessionButton("n-0123456789ab");
    assert.ok(btn && (btn.textContent || "").includes("關閉終端"));
    btn.dispatch("click");
    await tick();
    assert.deepStrictEqual(posts, [], "nothing is sent before the dialog is answered");
    await confirmDialog(true);
    assert.deepStrictEqual(posts, ["/api/native/sessions/n-0123456789ab/close"]);
    assert.strictEqual(ctx.location.hash, "#/team", "returns to the team view");
    const toastNode = walk(body).find((n) => n.getAttribute && n.getAttribute("id") === "toast");
    assert.ok((toastNode.textContent || "").includes("暫存區與設定已清除"), "cleanup reported");

    reply = { ok: true, closed: "n-0123456789ab", managed: { launch_id: "l-1", cleaned: false, retained_reason: "仍有已觀測的後代程序存活" } };
    ctx.location.hash = "";
    await closeVia();
    assert.ok((toastNode.textContent || "").includes("保留待檢查") && (toastNode.textContent || "").includes("後代程序"),
              "a retained launch says why");

    ctx.location.hash = "#/workbench?project=p-1";
    await closeVia();
    assert.strictEqual(ctx.location.hash, "#/workbench?project=p-1", "keeps the workbench open after close");

    failureStatus = 404;
    ctx.location.hash = "#/term/n-0123456789ab";
    await closeVia();
    assert.strictEqual(ctx.location.hash, "#/team", "returns from the terminal when the session is already gone");
    assert.ok((toastNode.textContent || "").includes("已不存在或已結束"), "404 is treated as an already ended session");

    posts.length = 0;
    await closeVia(false);
    assert.deepStrictEqual(posts, [], "cancelled confirmation sends nothing");
    assert.ok(!(walk(body).some((n) => n.tag === "script")), "no native confirm() needed");
    console.log("ok close button for native sessions");
  }

  // (The old role-card detail pane of the workbench tab is gone: the tab shows the card pool's cards, which
  // card_pool.cjs covers face by face. The armor grid and the skill rows live on in the launch pass and the skill card dialog.)

  // The skill card dialog (design game-ui 4.2): opened from the armory or a role's skill, from ?view=card, text only.
  {
    const hostile = '<img src=x onerror=alert(1)>';
    const sourced = (value, origin = "author", detail = "front matter") => ({ value, origin, detail });
    const card = {
      ok: true, index: { loaded: true, generated_at: 1791770000 },
      skill: { skill_id: "s-1", name: sourced(hostile, "derived", "技能檔案（掃描整理）"), invoke_name: "code-review",
               tool: sourced("claude", "derived", "掃描位置判讀"), scope: sourced("user", "derived", "掃描位置判讀"),
               activation: "active", activation_reason: "位於使用者技能目錄", installed: true,
               status_source: { origin: "derived", detail: "掃描位置與設定檔判讀" },
               description: sourced(hostile), when_to_use: sourced("送出 PR 之前"), inputs: sourced("diff", "derived", "章節"),
               outputs: sourced(null, "missing", ""), dependencies: sourced(null, "missing", ""),
               categories: { value: ["審查"], origin: "derived", detail: "描述關鍵字", matches: [] },
               referenced_files: { count: 2, items: [{ ref: "a.py", status: "present" }, { ref: "b.sh", status: "missing" }],
                                   truncated: false, note: "VBear 不會執行這些檔案", origin: "derived", detail: "技能檔內容裡的引用" },
               missing_files: { items: ["b.sh"], origin: "derived", detail: "掃描結果" },
               warnings: { items: ["w1"], origin: "derived", detail: "掃描結果" } },
      added_to_roles: { items: [{ id: "p-1", name: "First", enabled: true }], effective: false,
                        note: "已加入角色只是挑選紀錄，本次不生效", origin: "user", detail: "主控台角色卡（使用者意圖）" },
      observation: { state: "none", window_days: 30, source: "執行觀察", origin: "runtime", detail: "執行觀察" },
      marketplace_copies: [{ skill_id: "s-m", tool: "claude", scope: "marketplace" }],
      marketplace_source: { origin: "derived", detail: "市集掃描" },
      effect_note: "效果是作者的描述，不是 VBear 驗證過的能力，只適用於你自己啟動並載入這張技能的工具",
    };
    const loadout = {
      ok: true,
      profile: { id: "p-1", name: "First", enabled: true, tool: "claude", model_id: null, profession_role_id: null,
                 permission_intents: {}, intents_note: "只是記錄，不會變成實際權限" },
      index: { loaded: true, generated_at: 1791770000 }, profession: { state: "none", role_id: null },
      skills: { title: "已選技能（VBear 啟動時不載入）", note: "n", safe_mode: "s", items: [
        { skill_id: "s-1", state: "in_index", effective: false, name: hostile, tool: "claude", scope: "user",
          description: sourced(hostile), when_to_use: sourced("t"), categories: [],
          referenced_files: { count: 0, present: 0, missing: 0 }, warnings: [],
          observed: { state: "none", window_days: 30, source: "執行觀察" } }] },
      version_status: { state: "unknown", text: "未知" }, armor: { applicable: false, why: "x" }, blockers: [],
    };
    const posts = [];
    const ctx = freshContext({
      "GET /api/overview":           () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
      "GET /api/skills":             () => jsonResponse({ skills: staticData.skills, categories: [] }),
      "GET /api/roles":              () => jsonResponse({ roles: staticData.roles }),
      "GET /api/live":               () => jsonResponse({ sessions: [], projects: [], attention: [],
                                                          usage: { sessions: [] }, runtime: { available: true, problems: [] } }),
      "GET /api/tasks":              () => jsonResponse({ ok: true, tasks: [] }),
      "GET /api/task-templates":     () => jsonResponse({ ok: true, templates: { custom: {} } }),
      "GET /api/governance":         () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
      "GET /api/agent-profiles":     () => jsonResponse({ ok: true, profiles: profilesList }),
      "GET /api/agent-builder/catalog": () => jsonResponse(catalogBody),
      "GET /api/agent-profiles/p-1/loadout": () => jsonResponse(loadout),
      "GET /api/skills/s-1?view=card": () => jsonResponse(card),
      "POST /api/agent-profiles/p-1": (_u, o) => { posts.push(JSON.parse(o.body)); return jsonResponse({ ok: true }); },
    });
    const tick = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r)); };
    evalAgentBuilderSlice(ctx);
    await ctx.openSkillCard("s-1", { profile: profilesList[0] });
    await tick();
    const modal = findModalInBody();
    assert.ok(modal, "skill card dialog opened");
    assert.ok(!walk(modal).some((n) => n.tag === "img" || n.tag === "script"), "no element is built from text");
    assert.ok(findText(modal, hostile), "the hostile name is shown as text");
    assert.ok(walk(modal).some((n) => n.tag === "span" && (n.textContent || "") === "出發時不會載入"), "出發時不會載入 is fixed");
    assert.ok(findText(modal, "效果是作者的描述，不是 VBear 驗證過的能力，只適用於你自己啟動並載入這張技能的工具"));
    assert.ok(findText(modal, "未提供"), "a missing field reads 未提供");
    assert.ok(findText(modal, "a.py") && findText(modal, "存在") && findText(modal, "缺少") && findText(modal, "VBear 不會執行這些檔案"));
    assert.ok(!findText(modal, "可執行腳本"), "no script count");
    assert.ok(findText(modal, "收藏在 1 張角色卡上：First（出發時不會載入）"));
    assert.ok(findText(modal, "目前沒有觀察紀錄（最近 30 天；來源：執行觀察）"));
    assert.ok(findText(modal, "市集有其他副本（1 個，尚未安裝）"));
    assert.ok(findText(modal, "已安裝（可使用）：位於使用者技能目錄"), "the status names the state and the reason");
    // every field has its source tag: 類別, 工具, 來源, files, status, roles, observation, marketplace
    const sourceTags = walk(modal).filter((n) => n.className && n.className.includes("prov"));
    assert.ok(sourceTags.length >= 12, `source tags on the card (got ${sourceTags.length})`);
    assert.ok(findText(modal, "類別") && findText(modal, "陣營") && findText(modal, "來源（位置）"));
    // the name, the missing files and the structure warnings carry their source too
    const provOf = (needle) => walk(modal).filter((n) => n.className && n.className.includes("prov")
      && (n.getAttribute("title") || "").includes(needle));
    const nameHead = walk(modal).find((n) => n.className && n.className.includes("sc-head"));
    assert.ok(walk(nameHead).some((n) => n.className && n.className.includes("prov") && /技能檔案（掃描整理）/.test(n.textContent || "")),
              "the name has a source tag");
    const missingNotice = walk(modal).find((n) => n.className && n.className.includes("notice")
      && (n.textContent || "").includes("缺少的檔案：b.sh"));
    assert.ok(missingNotice && walk(missingNotice).some((n) => n.className && n.className.includes("prov")
      && (n.textContent || "").includes("掃描結果")), "missing files carry 掃描結果");
    const warnNotice = walk(modal).find((n) => n.className && n.className.includes("notice")
      && (n.textContent || "").includes("結構檢查：w1"));
    assert.ok(warnNotice && walk(warnNotice).some((n) => n.className && n.className.includes("prov")
      && (n.textContent || "").includes("掃描結果")), "warnings carry 掃描結果");
    const clickable = walk(modal).filter((n) => (n._listeners.click || []).length);
    assert.ok(clickable.every((n) => n.tag === "button" || n.tag === "a"), "only buttons and links are clickable");
    const file = walk(modal).find((n) => n.tag === "a" && /^#\/skills\/s-1$/.test(n.getAttribute("href") || ""));
    assert.ok(file && file.textContent === "打開技能檔案", "the file action goes to the existing skill page");
    const remove = walk(modal).find((n) => n.tag === "button" && (n.textContent || "") === "從這個角色移除");
    assert.ok(remove, "the remove action is offered from a role card");
    remove.dispatch("click");
    await tick();
    assert.deepStrictEqual(posts, [], "nothing is sent before the confirmation");
    const dialogs = body.children.filter((c) => c !== main && c.tag === "div" && c.getAttribute("role") === "dialog");
    const confirm = dialogs[dialogs.length - 1];
    assert.strictEqual(dialogs.length, 2, "the confirmation sits on top of the skill card");
    assert.ok(findText(confirm, `把「${hostile}」從角色「First」`), "the confirmation names the skill by its name");
    assert.ok(!findText(confirm, "[object Object]"), "no object is printed into the confirmation");
    const yes = walk(confirm).find((n) => n.tag === "button" && (n.textContent || "").trim() === "移除");
    assert.ok(yes, "an in-page confirmation");
    yes.dispatch("click");
    await tick();
    assert.deepStrictEqual(posts, [{ equipped_skill_ids: [] }], "the body carries only the new list");
    console.log("ok skill card dialog from the role card, with the remove action");
  }

  // a nameless skill in an 'unknown' state with no observation data: the ID is shown as an ID, the state is not
  // turned into "not installed", and the missing period is said
  {
    const miss = (detail = "") => ({ value: null, origin: "missing", detail });
    const ctx = freshContext({
      "GET /api/skills/s-7?view=card": () => jsonResponse({ ok: true, index: { loaded: true, generated_at: 1 },
        skill: { skill_id: "s-7", name: miss(), tool: miss(), scope: miss(), activation: "unknown",
                 activation_reason: "沒有任何設定檔能證明它是否被載入", installed: false,
                 status_source: { origin: "derived", detail: "掃描位置與設定檔判讀" },
                 description: miss(), when_to_use: miss(), inputs: miss(), outputs: miss(), dependencies: miss(),
                 categories: { value: null, origin: "missing", detail: "", matches: [] },
                 referenced_files: { count: 0, items: [], truncated: false, note: "VBear 不會執行這些檔案", origin: "derived", detail: "x" },
                 missing_files: { items: [], origin: "derived", detail: "掃描結果" },
                 warnings: { items: [], origin: "derived", detail: "掃描結果" } },
        added_to_roles: { items: [], effective: false, note: "n", origin: "user", detail: "d" },
        observation: { state: "unavailable", window_days: null, source: "執行觀察", origin: "runtime", detail: "執行觀察" },
        marketplace_copies: [], marketplace_source: { origin: "derived", detail: "市集掃描" },
        effect_note: "效果是作者的描述，不是 VBear 驗證過的能力，只適用於你自己啟動並載入這張技能的工具" }),
    });
    evalAgentBuilderSlice(ctx);
    await ctx.openSkillCard("s-7");
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const modal = findModalInBody();
    assert.ok(findText(modal, "未提供（ID：s-7）"), "a missing name is not replaced by the ID");
    assert.ok(findText(modal, "無法確認") && findText(modal, "沒有任何設定檔能證明它是否被載入"));
    assert.ok(!findText(modal, "沒有安裝在這台 Mac"), "unknown is not turned into 'not installed'");
    assert.ok(findText(modal, "觀察資料不可用（觀察期間：未知；來源：執行觀察）"), "the missing period is said");
    const said = walk(modal).map((n) => n.tag === "#text" ? n.textContent : "").join("");
    assert.ok(!said.replace("觀察期間：未知", "").includes("未知"), "a missing field is 未提供, not 未知");
    console.log("ok skill card with missing fields");
  }

  // an error from the server is shown in its fixed words, with no path
  {
    const ctx = freshContext({
      "GET /api/skills/s-8?view=card": () => jsonResponse({ ok: true, index: { loaded: true, generated_at: 1 },
        skill: { skill_id: "s-8", name: "x", tool: { value: "claude", origin: "derived", detail: "d" },
                 scope: { value: "user", origin: "derived", detail: "d" }, activation: "active", installed: true,
                 status_source: { origin: "derived", detail: "d" }, description: { value: null, origin: "missing" },
                 when_to_use: { value: null, origin: "missing" }, inputs: { value: null, origin: "missing" },
                 outputs: { value: null, origin: "missing" }, dependencies: { value: null, origin: "missing" },
                 categories: { value: null, origin: "missing" },
                 referenced_files: { count: 0, items: [], note: "n", origin: "derived", detail: "d" }, missing_files: [], warnings: [] },
        added_to_roles: { items: [], effective: false, unavailable: "角色資料無法讀取，請到角色頁處理",
                          code: "profile_store_damaged", note: "n", origin: "missing", detail: "" },
        observation: { state: "none", window_days: 7, source: "執行觀察", origin: "runtime", detail: "執行觀察" },
        marketplace_copies: [], marketplace_source: { origin: "derived", detail: "d" }, effect_note: "e" }),
    });
    evalAgentBuilderSlice(ctx);
    await ctx.openSkillCard("s-8");
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const text = walk(findModalInBody()).map((n) => n.tag === "#text" ? n.textContent : "").join("");
    assert.ok(text.includes("收藏在哪些角色卡上：無法讀取（角色資料無法讀取，請到角色頁處理）"));
    assert.ok(!/\/(Users|home|private)\//.test(text) && !text.includes("marker"), "no path or marker in the dialog");
    console.log("ok skill card shows the fixed unreadable-roles words");
  }

  // from the Armory there is no role, so no remove action; an unloaded index is said, not guessed
  {
    const ctx = freshContext({
      "GET /api/skills/s-9?view=card": () => jsonResponse({ error: "索引未載入，無法顯示技能卡", code: "index_not_loaded" }, 409),
    });
    evalAgentBuilderSlice(ctx);
    const tick = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r)); };
    await ctx.openSkillCard("s-9");
    await tick();
    const modal = findModalInBody();
    assert.ok(modal && findText(modal, "無法顯示技能卡") && findText(modal, "索引未載入"), "a failed load is said");
    assert.ok(!walk(modal).some((n) => (n.textContent || "") === "從這個角色移除"));
    console.log("ok skill card without a role or an index");
  }

  console.log("\nALL AGENT BUILDER FRONTEND TESTS PASSED");
})().catch((e) => { console.error(e); process.exitCode = 1; });
