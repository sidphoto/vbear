// P7 (closing fixes): the import box's hint and paste, the next step you can act on, the launch memo, the tracking box without a
// terminal, the word 工作中, a card reviewing itself, the pass line on a card, the lobby's second button, the picker's Chinese
// "what it does", and the words of the main path.
// Runs the real functions of web/app.js against a synthetic DOM and a fetch stub. It is NOT a browser test.
//
// Run: node tests/frontend/p7.cjs   (exit code 0 = pass)
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

// ---- canned answers ---------------------------------------------------------------------------------------------
const HOME = "/Users/tester";
const REPO = HOME + "/projects/demo";
const PLAIN = HOME + "/notes";
const SHA = "0123456789abcdef0123456789abcdef01234567";
const gitInfo = (over = {}) => ({ ok: true, path: REPO, name: "demo", exists: true, is_dir: true,
  git: { is_repo: true, root: REPO, branch: "main", commit: SHA, short: SHA.slice(0, 8), error: null },
  project_skill_count: 2, terminals: { known: true, count: 0, items: [] }, tasks: { known: true, items: [], count: 0 }, ...over });
const plainInfo = (over = {}) => ({ ok: true, path: PLAIN, name: "notes", exists: true, is_dir: true,
  git: { is_repo: false, root: null, branch: null, commit: null, short: null, error: null },
  project_skill_count: 0, terminals: { known: true, count: 0, items: [] }, tasks: { known: true, items: [], count: 0 }, ...over });
const inspectKey = (p) => `GET /api/folders/inspect?path=${encodeURIComponent(p)}`;
const live = { home: HOME, sessions: [], projects: [
  { project_id: "proj-1", name: "demo", path: REPO, basis: "git 儲存庫根目錄", live_session_ids: [], last_activity: "" },
  { project_id: "proj-2", name: "notes", path: PLAIN, basis: "工作目錄（非 git）", live_session_ids: [], last_activity: "" }], attention: [], usage: { sessions: [] }, runtime: { available: true, problems: [] } };
const baseTask = (over = {}) => ({ id: "task-1", title: "Demo task", template: "custom", goal: "", scope: [], out_of_scope: [], deliverables: [],
  acceptance_criteria: [], evidence: [], steps: [], artifacts: [], status: "draft", workdir: REPO,
  provenance: { agent: "pending", tests: "untested", human: "pending", verified: false, verification_asserted: false, notes: "", source: "unauthenticated_console_ui" },
  associated_pane_id: null, associated_session_id: null, association_mode: "tracking_only", association_label: "x", created_at: 1, updated_at: 1, ...over });
const templates = { custom: { title: "自訂任務", goal: "", scope: [] }, bug_fix: { title: "Bug 修復任務", goal: "修復特定錯誤或異常行為", scope: ["需修復之檔案"] } };

function handlers(over = {}) {
  return {
    "GET /api/config": () => jsonResponse({ config: { recent_folders: [PLAIN, "/Users/tester/old"] }, state_dir: "/x" }),
    "GET /api/task-templates": () => jsonResponse({ ok: true, templates }),
    "GET /api/live": () => jsonResponse(live),
    "GET /api/overview": () => jsonResponse({ stale: false, generated_at: 1, totals: {} }),
    "GET /api/skills": () => jsonResponse({ skills: [], categories: [] }),
    "GET /api/roles": () => jsonResponse({ roles: [] }),
    "GET /api/flows": () => jsonResponse({ ok: true, flows: [], families: [] }),
    "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [] }),
    [inspectKey(REPO)]: () => jsonResponse(gitInfo()),
    [inspectKey(PLAIN)]: () => jsonResponse(plainInfo()),
    ...over,
  };
}
function newCtx(over = {}) {
  const ctx = freshContext(handlers(over));
  evalAgentBuilderSlice(ctx);
  ctx.window.webkit = undefined;
  ctx.AbortController = AbortController;
  for (const a of ["inert", "aria-hidden"]) main.removeAttribute(a);   // the shared node of an earlier test
  // top-level const of the page are not properties of the context: hand the ones the tests read over, and D
  for (const name of ["NO_GIT_BADGE", "NO_GIT_NOTE", "FOLDER_BROWSER_NOTE", "FOLDER_FINDER_TIP", "FOLDER_TERMINAL_NOTE", "ONBOARD_STEPS", "SLOT_REVIEW_SELF", "WEAPON_LOCKED_NOTE", "TRACKING_NOTE", "CARD_INTENT_TITLE", "SKILL_EQUIPPED_NOTE", "LAUNCH_MEMO_KEY", "PASS_WORKDIR_LABEL", "D", "T"]) ctx[name] = vm.runInContext(name, ctx);
  return ctx;
}
const plain = (x) => JSON.parse(JSON.stringify(x));
const buttons = (root) => walk(root).filter((n) => n.tag === "button");
const labels = (root) => buttons(root).map((b) => (b.textContent || "").trim());
const act = (root, name) => byData(root, "data-act", name)[0];
const foot = (root) => walk(root).find((n) => n.className && n.className.includes("cw-foot"));
const inputOf = (root) => walk(root).find((n) => n.tag === "input" && n.getAttribute("type") === "text");

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); }
  catch (e) { console.log("FAIL -", name); console.log(e && e.stack || e); process.exitCode = 1; }
}


// ---- fixtures for the team --------------------------------------------------------------------------------------
const REV = (c) => c.repeat(64);
const mkCard = (id, name, tool, rev, extra = {}) => ({ id, name, profession_role_id: null, model: { tool, model_id: "" },
  equipped_skill_ids: [], permission_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" }, enabled: true,
  created_at: 1, updated_at: 1, revision: rev, _unresolved: { profession: false, skills: [] }, ...extra });
const CEO = mkCard("p-ceo", "CEO", "claude", REV("1"));
const MAKER = mkCard("p-maker", "工匠", "claude", REV("2"));
const REVIEWER = mkCard("p-rev", "審查員", "codex", REV("3"));
const PROFILES = [CEO, MAKER, REVIEWER];
const FLOW_ID = "flow-0123456789ab";
const flowView = (phaseKey = "implementing", over = {}) => ({ id: FLOW_ID, task_id: "task-1", task_title: "Demo task", task_missing: false, created_at: 1,
  roles: {
    planner: { name: "CEO", family: "anthropic", family_label: "Anthropic（Claude）", profile_id: "p-ceo",
      profile_snapshot: { name: "CEO", tool: "claude", model_id: "", revision: REV("1") } },
    executor: { name: "工匠", family: "anthropic", family_label: "Anthropic（Claude）", workdir: REPO, session_id: "n-0123456789ab",
      profile_id: "p-maker", profile_snapshot: { name: "工匠", tool: "claude", model_id: "", revision: REV("2") } },
    reviewers: [{ name: "審查員", family: "openai", family_label: "OpenAI（Codex）", profile_id: "p-rev",
      profile_snapshot: { name: "審查員", tool: "codex", model_id: "", revision: REV("3") } }],
  },
  phase: { key: phaseKey, label: phaseKey, reason: "" }, automation: { mode: "manual" }, events: [], ...over });
const teamHandlers = (over = {}) => ({
  "GET /api/agent-profiles": () => jsonResponse({ ok: true, profiles: PROFILES }),
  "GET /api/agent-builder/catalog": () => jsonResponse(catalog),
  ...over,
});
const anchors = (root) => walk(root).filter((n) => n.tag === "a");
const hrefOf = (root, pred) => (anchors(root).find(pred) || { getAttribute: () => null }).getAttribute("href");

(async () => {
  const pure = newCtx(teamHandlers());

  // ---- #1 the import box ---------------------------------------------------------------------------------------------
  await test("#1 folderLooksLikePath: an absolute path, ~/…, or ~ is looked at; anything else waits for the button", () => {
    const rows = [["/Users/me/projects/x", true], ["  /Users/me/a b/c  ", true], ["~/projects", true], ["~", true], ["/", true],
      ["projects/x", false], ["", false], ["   ", false], ["hello world", false], ["/a\nb", false], ["/a\u0000b", false],
      ["/" + "x".repeat(1100), false], [null, false], [undefined, false], [5, false], ["C:\\Users\\me", false], ["file:///Users/me", false]];
    for (const [text, want] of rows) assert.strictEqual(pure.folderLooksLikePath(text), want, JSON.stringify(text));
  });

  const emptyLive = { home: HOME, projects: [] };
  const mkPicker = (ctx, opts = {}) => { const p = ctx.folderPicker({ live: emptyLive, conf: { recent_folders: [] }, ...opts }); main.replaceChildren(); main.append(p.node); return p; };

  await test("#1 with both lists empty, the Finder tip and the browser note sit right under the box, in the same section as the input", () => {
    const ctx = newCtx(teamHandlers());
    const p = mkPicker(ctx);
    const tip = byData(p.node, "data-fp", "finder-tip")[0];
    const note = byData(p.node, "data-fp", "browser-note")[0];
    assert.ok(tip && note);
    assert.strictEqual(tip.textContent, ctx.FOLDER_FINDER_TIP);
    assert.strictEqual(ctx.FOLDER_FINDER_TIP, "在 Finder 對資料夾按右鍵，按住 Option，選『拷貝\"…\"為路徑名稱』，再貼到這裡");
    assert.strictEqual(note.textContent, ctx.FOLDER_BROWSER_NOTE);
    const sectionOf = (n) => { let x = n; while (x && !(x.className || "").includes("fp-list")) x = x.parentNode; return x; };
    assert.strictEqual(sectionOf(tip), sectionOf(p.input), "the tip is in the section of the input");
    assert.strictEqual(sectionOf(note), sectionOf(p.input));
    // the box comes first, then the hints
    const section = sectionOf(p.input);
    assert.ok(section.children.findIndex((c) => walk(c).includes(p.input) || c === p.input) < section.children.findIndex((c) => c.className === "fp-hints"));
  });

  await test("#1 the Finder tip goes away once there is a project or a recent folder to click; the browser note stays (and goes in the app window)", async () => {
    const ctx = newCtx(teamHandlers());
    const p = ctx.folderPicker({ live, conf: { recent_folders: [] } });
    assert.strictEqual(byData(p.node, "data-fp", "finder-tip").length, 0, "projects exist");
    assert.strictEqual(byData(p.node, "data-fp", "browser-note").length, 1);
    const q = ctx.folderPicker({ live: emptyLive, conf: { recent_folders: [PLAIN] } });
    assert.strictEqual(byData(q.node, "data-fp", "finder-tip").length, 0, "a recent folder exists");
    // the config arrives after the box is open: the tip is drawn with what is known then
    const r = ctx.folderPicker({ live: emptyLive });
    assert.strictEqual(byData(r.node, "data-fp", "finder-tip").length, 1);
    r.setConf({ recent_folders: [PLAIN] });
    assert.strictEqual(byData(r.node, "data-fp", "finder-tip").length, 0);
    r.setConf({ recent_folders: [] });
    assert.strictEqual(byData(r.node, "data-fp", "finder-tip").length, 1);
    // the app window has a chooser, so there is no browser note
    const app = newCtx(teamHandlers());
    app.window.webkit = { messageHandlers: { vbearPickFolder: { postMessage: () => {} } } };
    const a = app.folderPicker({ live: emptyLive, conf: { recent_folders: [] } });
    assert.strictEqual(byData(a.node, "data-fp", "browser-note").length, 0);
    assert.strictEqual(byData(a.node, "data-fp", "finder-tip").length, 1);
  });

  await test("#1 「檢查」 is the main button until there is a usable answer; Enter checks; the answer hands the main button to the dialog", async () => {
    const ctx = newCtx(teamHandlers());
    const p = mkPicker(ctx);
    const check = p.checkBtn;
    assert.strictEqual((check.textContent || "").trim(), "檢查");
    assert.ok(check.classList.contains("primary"), "main button");
    assert.strictEqual(act(p.node, "check"), check);
    p.input.value = REPO;
    p.input.dispatch("keydown", { key: "Enter", isComposing: false });
    await tick(6);
    assert.strictEqual(fetchCalls.filter((c) => c.url === `/api/folders/inspect?path=${encodeURIComponent(REPO)}`).length, 1, "Enter asks once");
    assert.ok(findText(p.node, "分支 main"));
    assert.ok(!check.classList.contains("primary"), "a usable answer: the dialog's own button is the main one");
    p.clear();
    assert.ok(check.classList.contains("primary"), "and back to the main button when it is cleared");
    // Enter during IME composition does not check
    fetchCalls.length = 0;
    p.input.value = REPO;
    p.input.dispatch("keydown", { key: "Enter", isComposing: true });
    await tick(4);
    assert.strictEqual(fetchCalls.length, 0);
    // a click checks too
    check.dispatch("click");
    await tick(6);
    assert.strictEqual(fetchCalls.filter((c) => c.url.startsWith("/api/folders/inspect")).length, 1);
  });

  await test("#1 a pasted path is checked once (read-only inspect only); a pasted word, a relative path or the same text again is not", async () => {
    const ctx = newCtx(teamHandlers());
    const p = mkPicker(ctx);
    const inspects = () => fetchCalls.filter((c) => c.url.startsWith("/api/folders/inspect"));
    p.input.value = "hello";
    p.input.dispatch("paste", {});
    await tick(4);
    assert.strictEqual(inspects().length, 0, "words are not a path");
    p.input.value = "projects/demo";
    p.input.dispatch("paste", {});
    await tick(4);
    assert.strictEqual(inspects().length, 0, "a relative path is not looked at");
    p.input.value = "  " + REPO + "  ";
    p.input.dispatch("paste", {});
    await tick(6);
    assert.strictEqual(inspects().length, 1);
    assert.strictEqual(inspects()[0].url, `/api/folders/inspect?path=${encodeURIComponent(REPO)}`);
    assert.ok(findText(p.node, "分支 main"));
    p.input.value = REPO;
    p.input.dispatch("paste", {});
    await tick(4);
    assert.strictEqual(inspects().length, 1, "the same path again is not asked again");
    assert.ok(fetchCalls.every((c) => !c.options || !c.options.method || c.options.method === "GET"), "only reads");
    // "~/x" is expanded before it is asked
    p.input.value = "~/notes";
    p.input.dispatch("paste", {});
    await tick(6);
    assert.strictEqual(inspects()[1].url, `/api/folders/inspect?path=${encodeURIComponent(PLAIN)}`);
    // after clearing, the same path can be pasted and checked again
    p.clear();
    p.input.value = REPO;
    p.input.dispatch("paste", {});
    await tick(6);
    assert.strictEqual(inspects().length, 3);
  });

  await test("#1 the import dialog says it too: tip in step 1, main 「檢查」, then the dialog's own 「下一步」 is the main button", async () => {
    const ctx = newCtx(teamHandlers({ "GET /api/config": () => jsonResponse({ config: { recent_folders: [] }, state_dir: "/x" }),
      "GET /api/live": () => jsonResponse({ ...live, projects: [] }) }));
    ctx.D.live = { ...live, projects: [] };
    ctx.openImportProject({});
    await tick(6);
    const d = dialog();
    assert.ok(findText(d, ctx.FOLDER_FINDER_TIP));
    assert.ok(act(d, "check").classList.contains("primary"));
    const input = inputOf(d);
    input.value = REPO;
    input.dispatch("paste", {});
    await tick(6);
    assert.ok(findText(d, "下一步：填寫任務卡"));
    assert.ok(!act(d, "check").classList.contains("primary"));
    assert.ok(act(d, "next").classList.contains("primary"));
  });

  // ---- #2 the next step you can act on ---------------------------------------------------------------------------------
  const noteOf = (name, words) => `手動模式下，VBear 不會自動推進。${name} 在終端裡完成這一步後，回到這裡記錄（例如『記錄：${words}』）。`;

  await test("#2 nextStepAction: whose step it is, the button, and the sentence — row by row (manual mode)", () => {
    const rows = [
      // phase,             step,       launches,                 turn,     note
      ["planning", "plan", [["CEO", "p-ceo"]], "CEO", noteOf("CEO", "計畫已提交")],
      ["implementing", "implement", [["工匠", "p-maker"]], "工匠", noteOf("工匠", "執行者回報")],
      ["needs_fix", "implement", [["工匠", "p-maker"]], "工匠", noteOf("工匠", "執行者回報")],
      ["in_review", "review", [["審查員", "p-rev"]], "審查員", noteOf("審查員", "審查結果")],
      ["review_stale", "review", [["審查員", "p-rev"]], "審查員", noteOf("審查員", "審查結果")],
    ];
    for (const [phase, step, launches, turn, note] of rows) {
      const a = pure.nextStepAction(flowView(phase), { profiles: PROFILES });
      assert.strictEqual(a.step, step, phase);
      assert.deepStrictEqual(plain(a.launches.map((l) => [l.name, l.profile_id])), launches, phase);
      assert.strictEqual(a.turn, turn, phase);
      assert.strictEqual(a.note, note, phase);
      assert.strictEqual(a.manual, true);
    }
    // steps that are yours, or past, or unknown: nothing to launch and no sentence
    for (const phase of ["awaiting_approval", "awaiting_merge", "review_unverified", "awaiting_push", "done", "no-such-phase"]) {
      const a = pure.nextStepAction(flowView(phase), { profiles: PROFILES });
      assert.ok(a === null || (a.launches.length === 0 && a.step === "merge"), phase);
      assert.strictEqual(pure.nextStepAction(flowView(phase)) === null, ["awaiting_approval", "awaiting_merge", "review_unverified", "awaiting_push", "done", "no-such-phase"].includes(phase), phase);
    }
  });

  await test("#2 nextStepAction: in automatic mode only the planner is yours to start; the sentence is a manual-mode sentence", () => {
    const auto = (phase) => flowView(phase, { automation: { mode: "auto" } });
    const plan = pure.nextStepAction(auto("planning"), { profiles: PROFILES });
    assert.deepStrictEqual(plain(plan.launches.map((l) => l.profile_id)), ["p-ceo"]);
    assert.strictEqual(plan.note, "");
    assert.strictEqual(plan.manual, false);
    for (const phase of ["implementing", "in_review"]) {
      const a = pure.nextStepAction(auto(phase), { profiles: PROFILES });
      assert.deepStrictEqual(plain(a.launches), [], phase + ": VBear starts the executor and sends the review itself");
      assert.strictEqual(a.note, "", phase);
    }
  });

  await test("#2 nextStepAction: a card that is gone or switched off, or a role typed by hand, gets no button", () => {
    const f = flowView("implementing");
    assert.deepStrictEqual(plain(pure.nextStepAction(f, { profiles: [CEO] }).launches), [], "the card is not in the pool any more");
    assert.deepStrictEqual(plain(pure.nextStepAction(f, { profiles: [{ ...MAKER, enabled: false }] }).launches), [], "switched off");
    assert.strictEqual(pure.nextStepAction(f, { profiles: [{ ...MAKER, enabled: true }] }).launches.length, 1);
    assert.strictEqual(pure.nextStepAction(f).launches.length, 1, "without the pool, the record decides");
    const hand = flowView("implementing");
    delete hand.roles.executor.profile_id; delete hand.roles.executor.profile_snapshot;
    const a = pure.nextStepAction(hand, { profiles: PROFILES });
    assert.deepStrictEqual(plain(a.launches), []);
    assert.strictEqual(a.note, noteOf("工匠", "執行者回報"), "the sentence still says what to do by hand");
    // two reviewers: one button each
    const two = flowView("in_review");
    two.roles.reviewers.push({ name: "CEO", family: "anthropic", profile_id: "p-ceo" });
    assert.deepStrictEqual(plain(pure.nextStepAction(two, { profiles: PROFILES }).launches.map((l) => l.name)), ["審查員", "CEO"]);
  });

  await test("#2 the action under the next steps: 「讓 X 出發」 goes the way a place's own 出發 goes, plus the sentence and the record link", () => {
    const ctx = newCtx(teamHandlers());
    const node = ctx.nextStepActionNode(flowView("planning"), { task: baseTask(), profiles: PROFILES });
    const go = byData(node, "data-ns", "launch")[0];
    assert.strictEqual(go.textContent, "讓 CEO 出發");
    assert.strictEqual(go.getAttribute("href"), "#/workbench?task=task-1&profile=p-ceo&launch=1&step=plan");
    assert.ok(findText(node, noteOf("CEO", "計畫已提交")));
    assert.strictEqual(byData(node, "data-ns", "record")[0].getAttribute("href"), `#/flows/${FLOW_ID}`, "no existing entry here: it links to the flow's page");
    // on the flow's own page the entry is on the same page: a button that goes there
    let went = 0;
    const onPage = ctx.nextStepActionNode(flowView("planning"), { task: baseTask(), profiles: PROFILES, onRecord: () => { went += 1; } });
    const rec = byData(onPage, "data-ns", "record")[0];
    assert.strictEqual(rec.tag, "button");
    rec.dispatch("click");
    assert.strictEqual(went, 1);
    // the lobby's card is compact: the button, not the long sentence
    const compact = ctx.nextStepActionNode(flowView("planning"), { task: baseTask(), profiles: PROFILES, compact: true });
    assert.ok(byData(compact, "data-ns", "launch")[0]);
    assert.strictEqual(byData(compact, "data-ns", "manual").length, 0);
    // a step that is yours has no launch button (P10 F2 gives it its own buttons; the lobby's compact card has none)
    const yours = ctx.nextStepActionNode(flowView("awaiting_approval"), { task: baseTask(), profiles: PROFILES });
    assert.strictEqual(byData(yours, "data-ns", "launch").length, 0);
    assert.strictEqual(ctx.nextStepActionNode(flowView("awaiting_approval"), { task: baseTask(), profiles: PROFILES, compact: true }), null);
    // nothing in it writes or navigates by itself
    assert.ok(walk(node).every((n) => n.tag !== "form"));
  });

  await test("#2 the next-steps list and the team section carry the action; the flow page's section is given the jump to the record form", async () => {
    const ctx = newCtx(teamHandlers({ "GET /api/flows": () => jsonResponse({ ok: true, flows: [flowView("planning")], families: [] }) }));
    const list = ctx.nextStepsList(flowView("planning"), { task: baseTask(), profiles: PROFILES });
    assert.ok(byData(list, "data-ns", "launch")[0]);
    assert.ok(byData(list, "data-ns", "action")[0]);
    let jumped = 0;
    const box = ctx.teamSection(baseTask(), { flow: flowView("implementing"), profiles: PROFILES, catalog, hideOpen: true, onRecord: () => { jumped += 1; } });
    main.replaceChildren(); main.append(box);
    await tick(8);
    assert.strictEqual(byData(box, "data-ns", "launch")[0].textContent, "讓 工匠 出發");
    byData(box, "data-ns", "record")[0].dispatch("click");
    assert.strictEqual(jumped, 1);
  });

  await test("#2 a place's own 出發 now says which step it is for", async () => {
    const ctx = newCtx(teamHandlers());
    const b = ctx.teamBoard({ task: baseTask(), flow: flowView("implementing"), profiles: PROFILES, catalog, gitState: "git" });
    main.replaceChildren(); main.append(b.node);
    const href = (slot) => byData(byData(b.node, "data-slot", slot)[0], "data-act", "launch")[0].getAttribute("href");
    assert.ok(href("planner").endsWith("&launch=1&step=plan"));
    assert.ok(href("executor").endsWith("&launch=1&step=implement"));
    assert.ok(href("reviewer1").endsWith("&launch=1&step=review"));
  });

  await test("#2 the lobby's task card has the button too (and the sentence only on the card's own page)", async () => {
    const ctx = newCtx(teamHandlers());
    const card = ctx.taskFrontCard(baseTask(), { flows: [flowView("planning")], profiles: PROFILES });
    main.replaceChildren(); main.append(card);
    assert.strictEqual(byData(card, "data-ns", "launch")[0].textContent, "讓 CEO 出發");
    assert.strictEqual(byData(card, "data-ns", "manual").length, 0);
    assert.ok(findText(card, "下一步：規劃者提出計畫（輪到 CEO）"));
    const gone = ctx.taskFrontCard(baseTask(), { flows: [flowView("planning")], profiles: [MAKER] });
    assert.strictEqual(byData(gone, "data-ns", "launch").length, 0, "a card that is not in the pool gets no button");
    const noFlow = ctx.taskFrontCard(baseTask(), { flows: [] });
    assert.strictEqual(byData(noFlow, "data-ns", "launch").length, 0);
  });

  await test("#2 the launch memo: only what VBear's own launch result gave, for this task and this step, for a day; never a guess about which terminal is which card", () => {
    const ctx = newCtx(teamHandlers());
    const f = flowView("planning");
    const text = (taskId = "task-1") => { const n = ctx.nextStepActionNode(f, { task: baseTask({ id: taskId }), profiles: PROFILES }); return n ? textOf(n) : ""; };
    assert.ok(!text().includes("已開啟"), "nothing was launched from this page");
    ctx.launchMemoAdd("task-1", { step: "plan", session_id: "n-aaaaaaaaaaaa", name: "CEO" });
    assert.ok(text().includes("已開啟 1 個終端；接下來在終端裡請它提出計畫。"));
    assert.strictEqual(hrefOf(ctx.nextStepActionNode(f, { task: baseTask(), profiles: PROFILES }), (a) => a.textContent === "打開終端"), "#/term/n-aaaaaaaaaaaa");
    ctx.launchMemoAdd("task-1", { step: "plan", session_id: "n-aaaaaaaaaaaa", name: "CEO" });
    assert.ok(text().includes("已開啟 1 個終端"), "the same terminal is not counted twice");
    ctx.launchMemoAdd("task-1", { step: "plan", session_id: "n-bbbbbbbbbbbb", name: "CEO" });
    assert.ok(text().includes("已開啟 2 個終端；接下來在終端裡請它提出計畫。"));
    assert.ok(!text("task-2").includes("已開啟"), "another task card");
    assert.ok(!ctx.nextStepActionNode(flowView("implementing"), { task: baseTask(), profiles: PROFILES }) || !textOf(ctx.nextStepActionNode(flowView("implementing"), { task: baseTask(), profiles: PROFILES })).includes("已開啟"), "another step");
    ctx.launchMemoAdd("task-1", { step: "implement", session_id: "n-cccccccccccc", name: "工匠" });
    const impl = textOf(ctx.nextStepActionNode(flowView("implementing"), { task: baseTask(), profiles: PROFILES }));
    assert.ok(impl.includes("已開啟 1 個終端；接下來在終端裡請它動手實作。"));
    // it never says which card a terminal belongs to
    assert.ok(!/(CEO|工匠)[^。]*(是|屬於)[^。]*終端/.test(impl));
    // bad input and old entries are not kept or shown
    ctx.launchMemoAdd("task-1", { step: "nonsense", session_id: "n-dddddddddddd" });
    ctx.launchMemoAdd("task-1", { step: "plan" });
    ctx.launchMemoAdd("", { step: "plan", session_id: "n-eeeeeeeeeeee" });
    assert.strictEqual(ctx.launchMemoRead("task-1").length, 3);
    ctx.__ls.set("sid:" + ctx.LAUNCH_MEMO_KEY + "task-9", JSON.stringify([
      { step: "plan", session_id: "n-old", name: "x", at: Date.now() - 25 * 3600 * 1000 }, { step: "plan", session_id: 5, at: Date.now() },
      { step: "plan", session_id: "n-ok", at: Date.now() }, "junk", null]));
    assert.deepStrictEqual(plain(ctx.launchMemoRead("task-9").map((e) => e.session_id)), ["n-ok"]);
    ctx.__ls.set("sid:" + ctx.LAUNCH_MEMO_KEY + "task-8", "not an array");
    assert.deepStrictEqual(plain(ctx.launchMemoRead("task-8")), []);
    for (let i = 0; i < 12; i++) ctx.launchMemoAdd("task-7", { step: "plan", session_id: "n-" + i, name: "x" });
    assert.strictEqual(ctx.launchMemoRead("task-7").length, 8, "at most eight are kept");
  });

  await test("#2 source: the memo is written only after the launch POST answered, from VBear's own result; nothing is written into a folder", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    const block = app.slice(app.indexOf("async function doLaunch()"), app.indexOf("function promptDeleteAgentProfile("));
    const post = block.indexOf('api.post("/api/native/agent-launches"');
    const add = block.indexOf("launchMemoAdd(launchOpts.fromTask.id");
    assert.ok(post >= 0 && add > post, "after the answer");
    assert.ok(block.includes("res.launch.session.session_id"));
    assert.ok(app.includes("params.step"), "the step comes in through the address");
    const stepBlock = app.slice(app.indexOf("function nextStepAction("), app.indexOf("function nextStepsList("));
    assert.ok(!/innerHTML|window\.open\(|location\.(href|assign|replace)\b/.test(stepBlock));
  });

  // ---- #3 the skill page says 收藏中, like the card ---------------------------------------------------------------------
  await test("#3 a skill's page: 「已插在哪些角色卡上」 says 收藏中（這次出發不載入）, and 啟用／已停用 only about the card itself", async () => {
    const skill = { skill_id: "s-1", name: "code-review", invoke_name: "code-review", tool: "claude", activation: "active", activation_reason: "x",
      description: { value: "Review a diff", origin: "file" }, when_to_use: null, inputs: null, outputs: null, dependencies: null,
      categories: [], warnings: [], missing_files: [], referenced_files: [], origin_package: {}, sources: {}, path: HOME + "/.claude/skills/code-review/SKILL.md", mtime: 1, scope: "user" };
    const detail = { ok: true, duplicates: [], skill, annotation: null, annotation_key: "k", roles: [], usage: [], origin: {}, source_files: [],
      equipped_by: [{ id: "p-ceo", name: "CEO", enabled: true }, { id: "p-off", name: "舊卡", enabled: false }] };
    const ctx = newCtx(teamHandlers({ "GET /api/skills/s-1": () => jsonResponse(detail) }));
    ctx.window.scrollTo = () => {};
    await ctx.viewSkillDetail("s-1");
    await tick(6);
    const list = byData(main, "data-skill", "equipped")[0];
    assert.ok(list, "the list is there");
    const rows = list.children.map((li) => textOf(li));
    assert.ok(rows[0].includes("CEO") && rows[0].includes("收藏中（這次出發不載入）") && rows[0].includes("角色卡本身啟用中"), rows[0]);
    assert.ok(rows[1].includes("舊卡") && rows[1].includes("收藏中（這次出發不載入）") && rows[1].includes("角色卡本身已停用"), rows[1]);
    assert.ok(!/(^|[^本身])啟用(?!中)/.test(rows[0].replace("角色卡本身啟用中", "")), "no bare 啟用 beside a skill");
    assert.strictEqual(byData(main, "data-skill", "equipped-note")[0].textContent, ctx.SKILL_EQUIPPED_NOTE);
    assert.ok(ctx.SKILL_EQUIPPED_NOTE.includes("收藏中") && ctx.SKILL_EQUIPPED_NOTE.includes("只在說那張角色卡本身"));
  });

  // ---- #4 the back of a card and the weapons --------------------------------------------------------------------------
  await test("#4 weapons: 鎖住 is explained in plain words when there is a locked tool; the intent title says it is a mark for dividing work", () => {
    const ctx = newCtx(teamHandlers());
    const gear = (tools) => { const box = new Node("div"); ctx.setKids(box, ctx.officeGear({ state: "ok", data: { tools, skills: { items: [] }, armor: { applicable: false, why: "x" } } })); return box; };
    const note = ctx.WEAPON_LOCKED_NOTE;
    assert.strictEqual(note, "鎖住＝VBear 啟動時不開放這個工具；寫檔改由終端指令在限制範圍內進行。");
    const withLocked = gear({ known: true, allowed: ["Read"], blocked: ["Edit"], source: "s" });
    assert.ok(findText(withLocked, "Edit・鎖住") && findText(withLocked, note));
    const nothingLocked = gear({ known: true, allowed: ["Read"], blocked: [], source: "s" });
    assert.ok(!findText(nothingLocked, note), "nothing is locked, so nothing to explain");
    const unknown = gear({ known: false, unknown_reason: "no" });
    assert.ok(!findText(unknown, note));
    assert.strictEqual(ctx.CARD_INTENT_TITLE, "權限意圖（分工記號）");
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    assert.strictEqual((app.match(/el\("h4", null, CARD_INTENT_TITLE\)/g) || []).length, 2, "the card back and the workbench card back");
    assert.ok(!/el\("h4", null, "權限意圖"\)/.test(app), "no bare title left");
  });

  // ---- #5 the tracking box without a terminal ----------------------------------------------------------------------------
  await test("#5 taskTerminalLink: with no terminal chosen nothing is linked — null equals null is not a link", () => {
    const rows = [
      [{ associated_pane_id: null }, null, "none"], [{ associated_pane_id: null }, undefined, "none"], [{}, "", "none"], [{ associated_pane_id: "" }, "", "none"],
      [{ associated_pane_id: "w:p1" }, null, "none"], [null, null, "none"],
      [{ associated_pane_id: "w:p1" }, "w:p1", "linked"], [{ associated_pane_id: "w:p1" }, "w:p2", "unlinked"], [{ associated_pane_id: null }, "w:p2", "unlinked"],
      [{}, "w:p2", "unlinked"],
    ];
    for (const [task, pane, want] of rows) assert.strictEqual(pure.taskTerminalLink(task, pane).state, want, JSON.stringify([task, pane]));
    assert.strictEqual(pure.taskTerminalLink({}, null).text, "目前沒有可關聯的終端");
    assert.ok(!pure.taskTerminalLink({ associated_pane_id: null }, null).text.includes("已與"));
    assert.strictEqual(pure.taskTerminalLink({ associated_pane_id: "a" }, "a").text, "已與目前的終端關聯（僅追蹤記錄）");
    assert.strictEqual(pure.taskTerminalLink({ associated_pane_id: "a" }, "b").text, "尚未與目前的終端關聯");
  });

  const wbHandlers = (over = {}) => teamHandlers({
    "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [baseTask(), baseTask({ id: "task-2", title: "Other", associated_pane_id: null, status: "draft" })] }),
    "GET /api/governance": () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
    "GET /api/task-templates": () => jsonResponse({ ok: true, templates }),
    "GET /api/agent-profiles/p-ceo/loadout": () => jsonResponse({ ok: true, profile: {}, skills: { items: [] }, armor: { applicable: false }, blockers: [] }),
    ...over,
  });

  await test("#5 the workbench with no terminal: the box says there is none to link, offers no link button, and never says 已與", async () => {
    const ctx = newCtx(wbHandlers());
    await ctx.viewWorkbench(null, "task-1", null, false);
    await tick(8);
    const state = byData(main, "data-wb", "tracking-state")[0];
    assert.ok(state, "the box is there");
    assert.strictEqual(state.textContent, "目前沒有可關聯的終端");
    const box = byData(main, "data-wb", "tracking")[0];
    assert.ok(!findText(box, "已與"));
    assert.ok(!buttons(box).some((b) => /關聯/.test(b.textContent)), "no button to link or unlink");
    assert.ok(findText(box, ctx.TRACKING_NOTE));
    assert.ok(!/Tracking Only|Context|Task Card|Effective|Agent Session/.test(textOf(box)), "and no English in it");
  });

  // ---- #6 工作中 only for status working -------------------------------------------------------------------------------
  await test("#6 a project's 「N 個開啟中的終端」 counts open terminals and does not say 工作中; none says so", () => {
    const ctx = newCtx(teamHandlers());
    ctx.D.live = { ...live, sessions: [{ project_id: "proj-1", status: "waiting" }, { project_id: "proj-1", status: "unknown" }, { project_id: "other", status: "working" }] };
    const card = ctx.projectCard({ project_id: "proj-1", name: "demo", path: REPO, basis: "x", git_branch: "main", recent_session_ids: [], last_activity: 0 });
    assert.ok(findText(card, "2 個開啟中的終端"));
    assert.ok(!textOf(card).includes("工作中"));
    ctx.D.live = { ...live, sessions: [] };
    const none = ctx.projectCard({ project_id: "proj-1", name: "demo", path: REPO, basis: "x", git_branch: "main", recent_session_ids: [], last_activity: 0 });
    assert.ok(findText(none, "沒有開啟中的終端") && !textOf(none).includes("工作中"));
  });

  await test("#6 source: 工作中 appears only where the status is working (a status table, or the words of the verified signal); never for 'open' or 'known'", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8").split("\n");
    const allowed = [
      /\bworking\b/,                                  // a table or branch keyed by the working status
      /「工作中／等你回覆」/,                          // naming the two states the verified signal tells apart
      /^\s*\/\//,                                     // a comment
      /工作中的 ◐／◑/, /工作中的標題更新間隔/,        // what the title check looks for
    ];
    const bad = [];
    app.forEach((line, i) => { if (line.includes("工作中") && !allowed.some((re) => re.test(line))) bad.push(`${i + 1}: ${line.trim().slice(0, 100)}`); });
    assert.deepStrictEqual(bad, []);
    // the two places the review found
    assert.ok(!app.join("\n").includes("個工作中`"), "no 'N 個工作中' count of terminals");
    assert.ok(!app.join("\n").includes('"工作中的 Terminal"') && !app.join("\n").includes("沒有工作中的 Agent"));
  });

  // ---- #7 the phone: coming in from a task card starts at the task card and its team ----------------------------------------
  const scrolled = [];
  Node.prototype.scrollIntoView = function (o) { scrolled.push([this.className || "", o]); };

  await test("#7 narrow screen + a task named in the address: the page starts at the right column (tasks and team); wide, or without a task, it does not", async () => {
    const run = async (matches, task) => {
      scrolled.length = 0;
      const ctx = newCtx(wbHandlers());
      ctx.window.matchMedia = (q) => ({ matches: matches && q === "(max-width: 900px)" });
      await ctx.viewWorkbench(null, task, null, false);
      await tick(8);
      return scrolled.filter(([cls]) => cls.includes("wb-right"));
    };
    assert.strictEqual((await run(true, "task-1")).length, 1, "narrow, from a task card");
    assert.strictEqual((await run(false, "task-1")).length, 0, "wide");
    assert.strictEqual((await run(true, null)).length, 0, "no task in the address");
  });

  await test("#7 the right column's button is 「任務與隊伍」 (the old 「右欄」 is gone), and a task in the address opens it even if it was folded", async () => {
    const ctx = newCtx(wbHandlers());
    ctx.__ls.set("sid:wb:right_collapsed", "true");
    await ctx.viewWorkbench(null, "task-1", null, false);
    await tick(8);
    const toggles = walk(main).filter((n) => n.tag === "button" && (n.className || "").includes("wb-col-toggle")).map((b) => b.textContent);
    assert.ok(toggles.includes("任務與隊伍 ►"), JSON.stringify(toggles));
    assert.ok(!toggles.some((t) => t.includes("右欄")));
    const ctx2 = newCtx(wbHandlers());
    ctx2.__ls.set("sid:wb:right_collapsed", "true");
    await ctx2.viewWorkbench(null, null, null, false);
    await tick(8);
    // P11 3.5: with no terminal open the card is the page, so a remembered fold is not applied and the column buttons are put away
    const shell = walk(main).find((n) => (n.className || "").split(/\s+/).includes("wb-shell"));
    assert.ok(shell && shell.className.includes("no-term") && !shell.className.includes("right-collapsed"), "no terminal: the card column is shown");
    assert.ok(walk(main).filter((n) => n.tag === "button" && (n.className || "").includes("wb-col-toggle")).every((b) => b.hidden === true), "no terminal: column buttons hidden");
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    assert.ok(!app.includes("右欄 ►") && !app.includes("右欄 ◄"));
  });

  // ---- #8 a card cannot review itself --------------------------------------------------------------------------------------
  await test("#8 slotProblem: the same card in the execution place and a review place — 同一張卡不能審查自己, whatever its family", () => {
    const card = (id, tool, extra = {}) => ({ profile_id: id, name: id, family: tool === "codex" ? "openai" : tool === "claude" ? "anthropic" : "unknown", ...extra });
    const rows = [
      // slot, reviewer card, executor, code
      ["reviewer1", card("a", "claude"), card("a", "claude"), "same_card"],
      ["reviewer2", card("a", "codex"), card("a", "codex"), "same_card"],
      ["reviewer1", card("a", "shared"), card("a", "shared"), "same_card"],
      ["reviewer1", card("a", "claude"), card("b", "claude"), "same_family"],
      ["reviewer1", card("a", "codex"), card("b", "claude"), null],
      ["reviewer1", { name: "手打", family: "openai" }, { name: "手打", family: "openai" }, "same_family"],
      ["reviewer1", card("a", "claude"), { name: "x", family: "anthropic" }, "same_family"],
      ["executor", card("a", "claude"), card("a", "claude"), null],
      ["planner", card("a", "claude"), card("a", "claude"), null],
    ];
    for (const [slot, rv, ex, want] of rows) {
      const p = pure.slotProblem(slot, rv, { executor: ex });
      assert.strictEqual(p ? p.code : null, want, `${slot} ${JSON.stringify([rv, ex])}`);
    }
    const p = pure.slotProblem("reviewer1", card("a", "claude"), { executor: card("a", "claude") });
    assert.strictEqual(p.text, "同一張卡不能審查自己");
    assert.strictEqual(pure.SLOT_REVIEW_SELF, "同一張卡不能審查自己");
  });

  await test("#8 on the board: putting the executor's card in the review place shows it there; changing the executor takes it away", async () => {
    const ctx = newCtx(teamHandlers());
    const b = ctx.teamBoard({ task: baseTask(), flow: null, profiles: PROFILES, catalog, gitState: "git" });
    main.replaceChildren(); main.append(b.node);
    const slot = (k) => byData(b.node, "data-slot", k)[0];
    b.place("executor", MAKER);
    b.place("reviewer1", MAKER);
    const problem = () => byData(slot("reviewer1"), "data-slot-problem", "same_card")[0];
    assert.ok(problem(), "the review place says why");
    assert.ok(findText(slot("reviewer1"), "同一張卡不能審查自己"));
    assert.strictEqual(slot("reviewer1").getAttribute("data-state"), "problem");
    b.place("executor", CEO);          // the executor is another card now
    assert.ok(!problem());
    assert.ok(byData(slot("reviewer1"), "data-slot-problem", "same_family")[0], "still the same family, which is its own reason");
    b.place("reviewer1", REVIEWER);
    assert.strictEqual(byData(slot("reviewer1"), "data-slot-problem", "same_card").length, 0);
  });

  // ---- #9 the pass ---------------------------------------------------------------------------------------------------------
  await test("#9 the pass names the folder field 「在哪裡做（工作資料夾）」 and says the unverified signal in plain words", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    assert.strictEqual(pure.PASS_WORKDIR_LABEL, "在哪裡做（工作資料夾）");
    const dlg = app.slice(app.indexOf("function promptAgentLaunch("), app.indexOf("function promptDeleteAgentProfile("));
    assert.strictEqual((dlg.match(/PASS_WORKDIR_LABEL/g) || []).length, 2, "the field and the preview line");
    assert.ok(!dlg.includes('"工作目錄"'));
    assert.ok(dlg.includes("出發後 VBear 暫時看不出它在忙還是在等你"));
    assert.ok(!/的「工作中／等你回覆」判斷還沒有驗證/.test(app));
    assert.ok(dlg.includes("驗證會同時檢查啟動邊界與終端標題") && dlg.includes("lastFailure"), "the verify button and its explanation stay");
  });

  // ---- #10 the range hint ----------------------------------------------------------------------------------------------------
  await test("#10 launchRangeText: the folder the server allows, not the home directory", () => {
    assert.strictEqual(pure.launchRangeText({ home: "/Users/a", managed_root: "/Users/a/work" }), "可以選的範圍：/Users/a/work 之內、已經存在的資料夾。");
    assert.strictEqual(pure.launchRangeText({ home: "/Users/a", managed_root: "/Users/a" }), "可以選的範圍：/Users/a 之內、已經存在的資料夾。");
    for (const bad of [{ home: "/Users/a" }, { home: "/Users/a", managed_root: "" }, { managed_root: 5 }, null, undefined]) {
      const t = pure.launchRangeText(bad);
      assert.ok(!t.includes("/Users/a") && t.includes("讀不到實際範圍"), JSON.stringify(bad) + " -> " + t);
    }
  });

  // ---- #11 words --------------------------------------------------------------------------------------------------------------
  await test("#11 the words on screen: no Terminal, Session, Armory, Context or Status Provenance in any string of the page", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    const index = fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8");
    const lit = /"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\\n]|\\.)*)`/g;
    const bad = [];
    app.split("\n").forEach((line, i) => {
      if (/^\s*(\/\/|\*)/.test(line)) return;
      for (const m of line.matchAll(lit)) {
        const t = m[1] !== undefined ? m[1] : m[2];
        if (/\b(Terminal|Session|Armory|Context)\b|Provenance/.test(t)) bad.push(`${i + 1}: ${t.slice(0, 80)}`);
      }
    });
    assert.deepStrictEqual(bad, []);
    assert.ok(!/\b(Terminal|Session|Armory|Context)\b|Provenance/.test(index.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]+>/g, " ")));
    // the replaced words
    for (const gone of ["尚未選取 Terminal", "工作中的 Terminal", "沒有工作中的 Agent", "執行中 Agent", "追蹤關聯 (Tracking Only)", "未綁定 session", "狀態證明 (Status Provenance)", "VBear Armory"]) {
      assert.ok(!app.includes(gone), gone);
    }
  });

  await test("#11 the main path, rendered: lobby, task card, pool and the pass have none of those English words", async () => {
    const FORBIDDEN = /\b(Terminal|Session|Armory|Context)\b|Provenance|Tracking Only/;
    const ctx = newCtx(teamHandlers({ "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [baseTask({ id: "t1", title: "Lobby task" })] }),
      "GET /api/flows": () => jsonResponse({ ok: true, flows: [flowView("planning", { task_id: "t1" })], families: [] }) }));
    await ctx.viewHome();
    await tick(8);
    assert.ok(findText(main, "Lobby task"));
    assert.ok(!FORBIDDEN.test(textOf(main)), textOf(main).match(FORBIDDEN));
    const pool = newCtx(teamHandlers());
    await pool.viewTeam();
    await tick(8);
    assert.ok(findText(main, "角色卡池"));
    assert.ok(!FORBIDDEN.test(textOf(main)), String(textOf(main).match(FORBIDDEN)));
    const card = ctx.taskFrontCard(baseTask(), { flows: [flowView("planning")], profiles: PROFILES });
    await tick(4);
    assert.ok(!FORBIDDEN.test(textOf(card)));
  });

  await test("#11 「先不要」 is 「先收起新手引導」; draft and 尚未認領 each get a sentence", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    assert.ok(!app.includes('"先不要"'));
    const ctx = newCtx(teamHandlers());
    const sec = ctx.onboardingSection({ mode: "steps", steps: ctx.ONBOARD_STEPS.map((s, i) => ({ ...s, n: i + 1, done: false })), next: "", firstTaskId: null }, {});
    assert.ok(buttons(sec).some((b) => b.textContent === "先收起新手引導"));
    assert.deepStrictEqual(plain(pure.taskStatusExplain("draft", { state: "unclaimed" })),
      ["草稿：還沒有人把這張任務卡標成「執行中」。這只是標記，不代表沒人在做；做到哪一步，看下方的隊伍與下一步。", "尚未認領：還沒有把這張任務卡關聯到任何終端。關聯只是追蹤記錄，不會把內容送進終端。"]);
    assert.deepStrictEqual(plain(pure.taskStatusExplain("in_progress", { state: "working" })), []);
    assert.deepStrictEqual(plain(pure.taskStatusExplain("draft", null)), ["草稿：還沒有人把這張任務卡標成「執行中」。這只是標記，不代表沒人在做；做到哪一步，看下方的隊伍與下一步。"]);
    const card = pure.taskFrontCard(baseTask({ status: "draft", pickup: { state: "unclaimed" } }), {});
    assert.ok(findText(card, "草稿：還沒有人把這張任務卡標成「執行中」。這只是標記，不代表沒人在做；做到哪一步，看下方的隊伍與下一步。"));
  });

  await test("#11b the draft sentence says only what the status means (nobody marked it in progress), nowhere says work has not begun", () => {
    // tasks.py derives "draft" when no agent field and no in_progress mark exist; it is not "work has not started"
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
    assert.ok(!app.includes("還沒開始做"), "the old claim is gone from the app");
    assert.ok(!app.includes("尚未開始執行"), "the old badge tooltip is gone too");
    const [text] = plain(pure.taskStatusExplain("draft", null));
    assert.ok(!/還沒開始做|沒有開始|尚未開始/.test(text), text);
    assert.ok(text.includes("還沒有人把這張任務卡標成「執行中」"), text);
    assert.ok(text.includes("只是標記"), text);
    // it must not send people to a control that the card front does not have
    assert.ok(!/按|選|請把/.test(text), text);
    assert.ok(/隊伍與下一步/.test(text), "it points to where progress actually shows");
    // the badge tooltip says the same thing as the sentence
    const tip = pure.taskStatusBadge("draft").getAttribute("title");
    assert.ok(tip.includes("標成「執行中」") && tip.includes("只是標記") && !/開始/.test(tip), tip);
    // both places read the one function: the workbench head and the card front
    const front = pure.taskFrontCard(baseTask({ status: "draft", pickup: { state: "working" } }), { flows: [flowView("planning")], profiles: PROFILES });
    assert.ok(findText(front, text));
    assert.ok(!findText(front, "還沒開始做"));
    // a card the user did mark in progress gets no draft sentence
    assert.deepStrictEqual(plain(pure.taskStatusExplain("in_progress", null)), []);
  });

  // ---- #14 the lobby's second button ----------------------------------------------------------------------------------------------
  await test("#14 an empty board: during the first game 「到終端工作台」 is a plain button; after it, the main one", () => {
    const g = { allEmpty: true, error: null, yourTurnFlows: [], yourTurnSessions: [], inProgress: [], moreInProgress: 0, runtimeAvailable: true };
    const go = (sec) => byData(sec, "data-board", "workbench")[0];
    const during = pure.boardSection(g, { firstGame: true });
    assert.ok(go(during) && go(during).className === "btn", go(during) && go(during).className);
    const after = pure.boardSection(g, { firstGame: false });
    assert.strictEqual(go(after).className, "btn primary");
    assert.strictEqual(go(after).textContent, "到終端工作台");
  });

  await test("#14 the home page sets it from the first-game steps: no card yet -> plain; all three done -> main", async () => {
    const mk = (profiles, tasks, flows) => newCtx(teamHandlers({
      "GET /api/agent-profiles": () => jsonResponse({ ok: true, profiles }), "GET /api/tasks": () => jsonResponse({ ok: true, tasks }),
      "GET /api/flows": () => jsonResponse({ ok: true, flows, families: [] }),
      "GET /api/config": () => jsonResponse({ config: { recent_folders: [], onboarding_dismissed: false }, state_dir: "/x" }) }));
    const go = () => byData(main, "data-board", "workbench")[0];
    const fresh = mk([], [], []);
    await fresh.viewHome();
    await tick(8);
    assert.ok(go() && go().className === "btn", "first game still on");
    const done = mk(PROFILES, [baseTask()], [flowView("done")]);
    await done.viewHome();
    await tick(8);
    const after = go();
    assert.ok(!after || after.className === "btn primary", "after the first game");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL P7 FRONTEND TESTS PASSED");
})();
