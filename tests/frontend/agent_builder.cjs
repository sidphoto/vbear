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
      if (kid instanceof Node) kid.parentNode = this;
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
    "Equipped Skill Loadout ≠ Loaded into any running session.",
    "Permission Intents are intent-only and are NOT enforced.",
    "Agent Profiles are stored only inside this console's own state directory.",
  ],
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
    n.tag === "button" && /\[A\] 角色裝備/.test(n.textContent || ""));
  if (!btn) throw new Error("agent tab button not found");
  btn.dispatch("click");
  // yield microtasks
  await new Promise((r) => setImmediate(r));
}

async function clickCreateAgentProfileButton() {
  const btn = walk(main).find((n) =>
    n.tag === "button" && /建立 Agent Profile/.test(n.textContent || ""));
  if (!btn) throw new Error("create button not found");
  btn.dispatch("click");
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
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
                                                          herdr: { available: true, problems: [] } }),
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
    assert.ok(findText(right, "Agent Builder"), "title rendered");
    assert.ok(findText(right, "Equipped Skill Loadout"), "honest disclosure present");
    assert.ok(findText(right, "絕對不會寫入 ~/.codex"), "boundary disclosure present");
    assert.ok(findText(right, "建立 Agent Profile"), "create button visible");
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
                                                          herdr: { available: true, problems: [] } }),
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
    assert.ok(findText(right, "已從掃描結果中消失"), "unresolved warning surfaced in list view");
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
                                                          herdr: { available: true, problems: [] } }),
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
    inputs[0].value = "My new profile";
    const saveBtn = walk(modal).filter((n) =>
      n.tag === "button" && /建立 Profile/.test(n.textContent || ""))[0];
    assert.ok(saveBtn, "save button labelled  建立 Profile");
    saveBtn.dispatch("click");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const createPost = posts.find((x) => x.url === "/api/agent-profiles");
    assert.ok(createPost, "create POST was made to /api/agent-profiles");
    assert.equal(createPost.body.name, "My new profile");
    assert.deepEqual(createPost.body.permission_intents,
                     { read: "unspecified", write: "unspecified",
                       test: "unspecified", deploy: "unspecified" });
    assert.equal(createPost.body.enabled, true);
    console.log("ok editor sends POST with default permission_intents");
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
                                                          herdr: { available: true, problems: [] } }),
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
    // Select p-1 by clicking its list-item button.
    const listItem = walk(main).find((n) =>
      n.tag === "button" && n.className.includes("wb-list-item")
      && /First/.test(n.textContent || ""));
    assert.ok(listItem, "first profile's list-item button found");
    listItem.dispatch("click");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    // Detail view should show the Edit/Copy/Delete/Disable buttons.
    const deleteBtn = walk(main).find((n) =>
      n.tag === "button" && (n.textContent || "").trim() === "刪除");
    assert.ok(deleteBtn, "delete button labelled  刪除");
    deleteBtn.dispatch("click");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    assert.ok(posts.some((x) => x.url === "/api/agent-profiles/p-1/delete"),
              "delete POST was made to /<id>/delete");
    console.log("ok delete confirm → POST to /<id>/delete");
  }

  console.log("\nALL AGENT BUILDER FRONTEND TESTS PASSED");
})().catch((e) => { console.error(e); process.exitCode = 1; });