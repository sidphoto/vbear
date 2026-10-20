// P3 (design card-play 3.6, 4, 6, R4, R5, R8): a task card is one folder. The folder picker (projects VBear saw, recent
// folders, a pasted path, the app's native chooser), the import dialog, the front of a task card, the lobby's section of
// task cards, the launch check's folder field, and the honesty rules (no version history is said; terminals are counted by
// directory, never "working"; the picker only reads).
// Runs the real functions of web/app.js against a synthetic DOM and a fetch stub. It is NOT a browser test.
//
// Run: node tests/frontend/task_folder.cjs   (exit code 0 = pass)
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
const live = { home: HOME, managed_root: HOME, sessions: [], projects: [
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
  for (const name of ["NO_GIT_BADGE", "NO_GIT_NOTE", "FOLDER_BROWSER_NOTE", "FOLDER_TERMINAL_NOTE", "FOLDER_REFUSED_HOME_DIRS", "D"]) ctx[name] = vm.runInContext(name, ctx);
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

(async () => {
  const pure = newCtx();

  // ---- pure helpers ----------------------------------------------------------------------------------------------
  await test("expandHome: ~ and ~/x mean the home directory, nothing else is touched", () => {
    const rows = [["~", HOME], ["~/projects/x", HOME + "/projects/x"], ["  ~/a ", HOME + "/a"], ["/abs/path", "/abs/path"],
      ["~other/x", "~other/x"], ["relative", "relative"], ["", ""], [null, ""], [undefined, ""]];
    for (const [text, want] of rows) assert.strictEqual(pure.expandHome(text, HOME), want, String(text));
    assert.strictEqual(pure.expandHome("~/a", HOME + "/"), HOME + "/a", "a trailing slash on home is not doubled");
    assert.strictEqual(pure.expandHome("~/a", ""), "~/a", "without a home it stays as typed");
    assert.strictEqual(pure.expandHome("~/a", null), "~/a");
  });

  await test("the places the page leaves out of its lists are the server's list", () => {
    assert.deepStrictEqual(plain(pure.FOLDER_REFUSED_HOME_DIRS), [".ssh", ".gnupg", ".aws", ".config", ".vbear", ".claude", ".codex", ".gemini", "Library"]);
  });

  await test("folderSources: seen projects keep name, path and basis; home, unknown, relative, repeated and refused places are left out", () => {
    const projects = [
      { project_id: "a", name: "demo", path: REPO, basis: "git 儲存庫根目錄" },
      { project_id: "home", name: "家目錄（未指定專案）", path: HOME, basis: "工作目錄是使用者家目錄" },
      { project_id: "unknown", name: "未知工作目錄", path: "", basis: "session 未回報工作目錄" },
      { project_id: "b", name: "rel", path: "relative/dir", basis: "x" },
      { project_id: "c", name: "dup", path: REPO, basis: "again" },
      { project_id: "d", name: "ssh", path: HOME + "/.ssh", basis: "x" },
      { project_id: "e", name: "sub", path: HOME + "/.Claude/projects/x", basis: "x" },
      { project_id: "f", name: "lib", path: HOME + "/Library/Mobile", basis: "x" },
      { project_id: "g", name: "dots", path: HOME + "/.sshkeys", basis: "not under .ssh" },
      null, { project_id: "h" }, { project_id: "i", path: 5 },
    ];
    const out = pure.folderSources({ home: HOME, projects }, { recent_folders: [] });
    assert.deepStrictEqual(plain(out.seen.map((s) => [s.name, s.path, s.basis])), [
      ["demo", REPO, "git 儲存庫根目錄"], ["dots", HOME + "/.sshkeys", "not under .ssh"]]);
    assert.deepStrictEqual(plain(pure.folderSources(null, null).seen), []);
    assert.deepStrictEqual(plain(pure.folderSources({}, {}).recent), []);
  });

  await test("folderSources: at most 24 seen projects and 10 recent folders; recent keeps its order and drops what is not a path", () => {
    const projects = Array.from({ length: 40 }, (_, i) => ({ project_id: "p" + i, name: "p" + i, path: `${HOME}/p${i}`, basis: "b" }));
    const recent = Array.from({ length: 14 }, (_, i) => `${HOME}/r${i}`);
    const out = pure.folderSources({ home: HOME, projects }, { recent_folders: ["rel", 5, null, ...recent, `${HOME}/r0`] });
    assert.strictEqual(out.seen.length, 24);
    assert.deepStrictEqual(plain(out.recent.map((r) => r.path)), recent.slice(0, 10));
    assert.strictEqual(out.recent[0].name, "r0");
  });

  await test("folderTerminalHeadline: a count by directory, never 'working'; unknown when the live view was not read", () => {
    const h = pure.folderTerminalHeadline;
    assert.strictEqual(h({ known: true, count: 3, items: [] }), "這個資料夾目前有 3 個終端");
    assert.strictEqual(h({ known: true, count: 0, items: [] }), "這個資料夾目前有 0 個終端");
    for (const t of [null, undefined, {}, { known: false, count: 2 }, { known: "yes", count: 2 }]) assert.strictEqual(h(t), "這個資料夾的終端數暫時讀不到");
    for (const t of [{ known: true, count: 5 }, null]) assert.ok(!/在工作|工作中/.test(h(t)), "the headline does not say what they do");
  });

  await test("folderTerminalStatusText: the existing status words, counted, in the status order", () => {
    const s = pure.folderTerminalStatusText;
    assert.strictEqual(s([{ status: "working" }, { status: "waiting" }, { status: "exited" }]), "1 個等你回覆、1 個工作中、1 個已結束");
    assert.strictEqual(s([{ status: "working" }, { status: "working" }]), "2 個工作中");
    assert.strictEqual(s([{ status: "needs-input" }, { status: "mystery" }, {}]), "1 個需要你處理、2 個狀態未知");
    assert.strictEqual(s([]), "");
    assert.strictEqual(s(null), "");
  });

  await test("folderVerdict: only an existing folder is usable; no git is a state of its own", () => {
    const v = pure.folderVerdict;
    assert.deepStrictEqual(plain(v(gitInfo())), { usable: true, kind: "git", noGit: false, text: "" });
    assert.deepStrictEqual(plain(v(plainInfo())), { usable: true, kind: "nogit", noGit: true, text: "" });
    assert.strictEqual(v({ ok: true, exists: false }).usable, false);
    assert.strictEqual(v({ ok: true, exists: false }).text, "找不到這個資料夾");
    assert.strictEqual(v({ ok: true, exists: true, is_dir: false }).text, "這不是資料夾");
    for (const bad of [null, undefined, {}, { ok: false }, "x"]) assert.strictEqual(v(bad).usable, false, JSON.stringify(bad));
  });

  await test("folderGitLine: branch and short HEAD, a detached HEAD in words, an unreadable HEAD with its reason, nothing without a repository", () => {
    const g = pure.folderGitLine;
    assert.strictEqual(g(gitInfo().git), "分支 main · HEAD 01234567");
    assert.strictEqual(g({ ...gitInfo().git, branch: null }), "不在任何分支上（停在某一個版本） · HEAD 01234567");
    assert.strictEqual(g({ is_repo: true, commit: null, error: "分支還沒有任何 commit" }), "已找到 git 儲存庫，但讀不到目前的版本：分支還沒有任何 commit");
    assert.strictEqual(g({ is_repo: true, commit: null, error: null }), "已找到 git 儲存庫，但讀不到目前的版本：原因不明");
    assert.strictEqual(g({ is_repo: false }), null);
    assert.strictEqual(g(null), null);
  });

  // ---- folderFacts -------------------------------------------------------------------------------------------------
  await test("folderFacts: a repository shows branch and HEAD, the skills, the terminals by directory and the open cards", () => {
    const node = pure.folderFacts(gitInfo({ project_skill_count: 3,
      terminals: { known: true, count: 3, items: [{ terminal_id: "t1", status: "working", title: "" }, { terminal_id: "t2", status: "waiting", title: "fix" }, { terminal_id: "t3", status: "exited", title: "" }] },
      tasks: { known: true, count: 1, items: [{ id: "task-9", title: "Open one" }] } }));
    const text = textOf(node);
    assert.ok(text.includes("分支 main · HEAD 01234567"));
    assert.ok(text.includes("3 張"));
    assert.ok(text.includes("這個資料夾目前有 3 個終端"));
    assert.ok(text.includes("1 個等你回覆、1 個工作中、1 個已結束"), "the statuses are in the opened list");
    assert.ok(text.includes("Open one"));
    assert.ok(text.includes(pure.FOLDER_TERMINAL_NOTE), "it says it is only by directory");
    assert.ok(!text.includes("在工作"), "never 'in work'");
    assert.ok(!text.includes(pure.NO_GIT_BADGE));
  });

  await test("folderFacts: no version history says so on the front (badge and the whole sentence), R4", () => {
    const node = pure.folderFacts(plainInfo());
    const text = textOf(node);
    assert.ok(text.includes("沒有版本紀錄"));
    assert.ok(text.includes("這個資料夾還沒有 git 版本紀錄。任務卡可以建立，也能從這裡出發；但隊伍的審查結果要綁定版本編號，在這個資料夾裡不會算數，合併關卡也用不了。"));
    assert.ok(walk(node).some((n) => n.className && n.className.includes("badge") && n.textContent === "沒有版本紀錄"));
    assert.ok(!text.includes("分支"));
  });

  await test("folderFacts: unknown things are said unknown, not zero", () => {
    const text = textOf(pure.folderFacts(gitInfo({ project_skill_count: null, terminals: { known: false, count: 0, items: [] }, tasks: { known: false, items: [] } })));
    assert.ok(text.includes("技能索引還沒載入，數量未知"));
    assert.ok(text.includes("這個資料夾的終端數暫時讀不到"));
    assert.ok(text.includes("暫時讀不到任務卡"));
    assert.ok(!text.includes("0 張"));
  });

  await test("folderFacts: a missing folder or a file is a warning, with no facts", () => {
    assert.ok(textOf(pure.folderFacts({ ok: true, exists: false })).includes("找不到這個資料夾"));
    assert.ok(textOf(pure.folderFacts({ ok: true, exists: true, is_dir: false })).includes("這不是資料夾"));
  });

  await test("more than the listed terminals: the statuses say how many they cover", () => {
    const items = [{ terminal_id: "t1", status: "working", title: "" }];
    const text = textOf(pure.folderFacts(gitInfo({ terminals: { known: true, count: 25, items } })));
    assert.ok(text.includes("這個資料夾目前有 25 個終端"));
    assert.ok(text.includes("只列出前 1 個的狀態"));
  });

  // ---- the native chooser bridge -----------------------------------------------------------------------------------
  function bridgeCtx(over = {}) {
    const ctx = newCtx(over);
    const sent = [];
    ctx.window.webkit = { messageHandlers: { vbearPickFolder: { postMessage: (m) => sent.push(m) } } };
    return { ctx, sent };
  }

  await test("the page is ready for the app's answer: window.__vbearFolderPicked exists", () => {
    assert.strictEqual(typeof pure.window.__vbearFolderPicked, "function");
  });

  await test("bridge: the request id is a short lowercase token (^[a-z0-9-]{1,32}$), a new one every time, and only that is sent", async () => {
    const { ctx, sent } = bridgeCtx();
    const picker = ctx.folderPicker({ live });
    const btn = btnByText(picker.node, "選擇資料夾…");
    assert.ok(btn, "the app window offers the chooser");
    assert.ok(!findText(picker.node, ctx.FOLDER_BROWSER_NOTE), "and does not say the browser cannot");
    btn.dispatch("click");
    assert.strictEqual(sent.length, 1);
    assert.deepStrictEqual(Object.keys(sent[0]), ["requestId"]);
    assert.ok(/^[a-z0-9-]{1,32}$/.test(sent[0].requestId), sent[0].requestId);
    ctx.window.__vbearFolderPicked({ requestId: sent[0].requestId, status: "cancel" });
    await tick();
    btn.dispatch("click");
    assert.notStrictEqual(sent[1].requestId, sent[0].requestId);
    assert.ok(/^[a-z0-9-]{1,32}$/.test(sent[1].requestId));
  });

  await test("bridge: an 'ok' answer is only text; the page asks the server about it before anything else", async () => {
    const { ctx, sent } = bridgeCtx();
    const picker = ctx.folderPicker({ live });
    btnByText(picker.node, "選擇資料夾…").dispatch("click");
    ctx.window.__vbearFolderPicked({ requestId: sent[0].requestId, status: "ok", path: REPO });
    await tick();
    assert.ok(fetchCalls.some((c) => c.url === `/api/folders/inspect?path=${encodeURIComponent(REPO)}`), "inspect was asked");
    assert.strictEqual(picker.input.value, REPO);
    assert.ok(findText(picker.node, "分支 main"), "and its answer is what is shown");
  });

  await test("bridge: cancel does nothing, busy says so, an answer to no request or in a wrong shape is ignored", async () => {
    const { ctx, sent } = bridgeCtx();
    const picker = ctx.folderPicker({ live });
    const click = () => btnByText(picker.node, "選擇資料夾…").dispatch("click");
    click();
    ctx.window.__vbearFolderPicked({ requestId: sent[0].requestId, status: "cancel" });
    await tick();
    assert.ok(!fetchCalls.some((c) => c.url.startsWith("/api/folders/inspect")));
    click();
    ctx.window.__vbearFolderPicked({ requestId: sent[1].requestId, status: "busy" });
    await tick();
    assert.ok(findText(body, "選擇資料夾的視窗已經開著了"), "toast");
    assert.ok(!fetchCalls.some((c) => c.url.startsWith("/api/folders/inspect")));
    const before = fetchCalls.length;
    for (const bad of [null, undefined, 5, "x", {}, { requestId: 5 }, { requestId: "pick-never-asked", status: "ok", path: REPO },
      { requestId: sent[0].requestId, status: "ok", path: REPO } /* already answered */]) ctx.window.__vbearFolderPicked(bad);
    await tick();
    assert.strictEqual(fetchCalls.length, before, "none of them reached the server");
    // a status the page does not know, or a path that is not a short string, is a cancel
    click();
    ctx.window.__vbearFolderPicked({ requestId: sent[2].requestId, status: "approved", path: REPO });
    click();
    ctx.window.__vbearFolderPicked({ requestId: sent[3].requestId, status: "ok", path: "/" + "a".repeat(1100) });
    click();
    ctx.window.__vbearFolderPicked({ requestId: sent[4].requestId, status: "ok", path: 5 });
    await tick();
    assert.strictEqual(fetchCalls.length, before);
  });

  await test("bridge: a handler that throws is a cancel, and the button comes back", async () => {
    const ctx = newCtx();
    ctx.window.webkit = { messageHandlers: { vbearPickFolder: { postMessage: () => { throw new Error("gone"); } } } };
    const picker = ctx.folderPicker({ live });
    const btn = btnByText(picker.node, "選擇資料夾…");
    btn.dispatch("click");
    await tick();
    assert.strictEqual(btn.disabled, false);
  });

  await test("browser mode: no chooser button, and it says why in the design's words", () => {
    const picker = pure.folderPicker({ live });
    assert.ok(!btnByText(picker.node, "選擇資料夾…"));
    assert.ok(findText(picker.node, "瀏覽器拿不到完整路徑，請從清單選或貼上。"));
  });

  // ---- the picker --------------------------------------------------------------------------------------------------
  await test("picker: seen projects show name, path and basis; recent folders come from the config; a click asks the server", async () => {
    const ctx = newCtx();
    const picker = ctx.folderPicker({ live, conf: { recent_folders: [PLAIN] } });
    const text = textOf(picker.node);
    for (const s of ["VBear 在你電腦上看到的專案", "demo", REPO, "依據：git 儲存庫根目錄", "最近用過", "貼上路徑"]) assert.ok(text.includes(s), s);
    byData(picker.node, "data-path", REPO)[0].dispatch("click");
    await tick();
    assert.deepStrictEqual(fetchCalls.map((c) => c.url), [`/api/folders/inspect?path=${encodeURIComponent(REPO)}`]);
    assert.ok(findText(picker.node, "分支 main · HEAD 01234567"));
    assert.strictEqual(picker.input.value, REPO);
  });

  await test("picker: the config arrives later and the lists are drawn again", () => {
    const ctx = newCtx();
    const picker = ctx.folderPicker({ live });
    assert.strictEqual(byData(picker.node, "data-path", PLAIN).length, 1, "the seen list has it");
    picker.setConf({ recent_folders: ["/Users/tester/old"] });
    assert.strictEqual(byData(picker.node, "data-path", "/Users/tester/old").length, 1);
  });

  await test("picker: a pasted ~/path is made absolute; Enter checks it; nothing is asked for an empty box", async () => {
    const ctx = newCtx();
    const picker = ctx.folderPicker({ live });
    picker.input.value = "~/projects/demo";
    picker.input.dispatch("keydown", { key: "Enter" });
    await tick();
    assert.strictEqual(fetchCalls[0].url, `/api/folders/inspect?path=${encodeURIComponent(REPO)}`);
    fetchCalls.length = 0;
    picker.input.value = "   ";
    picker.input.dispatch("keydown", { key: "Enter" });
    btnByText(picker.node, "檢查").dispatch("click");
    await tick();
    assert.strictEqual(fetchCalls.length, 0);
  });

  await test("picker: an IME composition Enter does not check the path", async () => {
    const ctx = newCtx();
    const picker = ctx.folderPicker({ live });
    picker.input.value = REPO;
    picker.input.dispatch("keydown", { key: "Enter", isComposing: true });
    await tick();
    assert.strictEqual(fetchCalls.length, 0);
  });

  await test("picker: a refused or bad answer is the server's sentence and offers nothing to continue with", async () => {
    let acted = 0;
    const ctx = newCtx({ [inspectKey(HOME + "/.ssh")]: () => jsonResponse({ error: "這個位置不能當成專案" }, 403),
      [inspectKey("relative")]: () => jsonResponse({ error: "路徑必須是絕對路徑" }, 400) });
    const picker = ctx.folderPicker({ live, onResult: (info) => { if (info) acted++; } });
    picker.inspect(HOME + "/.ssh");
    await tick();
    assert.ok(findText(picker.node, "這個位置不能當成專案"));
    picker.inspect("relative");
    await tick();
    assert.ok(findText(picker.node, "路徑必須是絕對路徑"));
    assert.strictEqual(acted, 0);
  });

  await test("picker: a missing folder or a file gets no continue button", async () => {
    let acted = 0;
    const ctx = newCtx({ [inspectKey("/Users/tester/gone")]: () => jsonResponse({ ok: true, path: "/Users/tester/gone", name: "gone", exists: false, is_dir: false }) });
    const picker = ctx.folderPicker({ live, onResult: (info) => { if (info) acted++; } });
    picker.inspect("/Users/tester/gone");
    await tick();
    assert.ok(findText(picker.node, "找不到這個資料夾"));
    assert.strictEqual(acted, 0);
  });

  await test("picker: only the newest answer is drawn (a slow older one does not overwrite it)", async () => {
    let releaseFirst;
    const first = new Promise((r) => { releaseFirst = r; });
    const ctx = newCtx({ [inspectKey(REPO)]: async () => { await first; return jsonResponse(gitInfo()); } });
    const picker = ctx.folderPicker({ live });
    picker.inspect(REPO);
    picker.inspect(PLAIN);
    await tick();
    assert.ok(findText(picker.node, "沒有版本紀錄"));
    releaseFirst();
    await tick();
    assert.ok(findText(picker.node, "沒有版本紀錄"), "still the newest one");
    assert.ok(!findText(picker.node, "分支 main"));
  });

  // ---- the import dialog -------------------------------------------------------------------------------------------
  const importOpts = () => { const calls = { created: [], opened: [] }; return { calls, opts: { onCreated: (t) => calls.created.push(t), onOpenTask: (id) => calls.opened.push(id), paneId: "w1:pA" } }; };
  async function openImport(over = {}, o = {}) {
    const posts = [];
    const ctx = newCtx({ "POST /api/tasks": (url, options) => { const b = JSON.parse(options.body); posts.push(b); return jsonResponse({ ok: true, task: baseTask({ id: "task-NEW", title: b.title, workdir: b.workdir }) }); }, ...over });
    ctx.D.live = live;
    const { calls, opts } = importOpts();
    const handle = ctx.openImportProject({ ...opts, ...o });
    await tick();
    return { ctx, posts, calls, handle, d: dialog() };
  }
  async function pickFolder(d, ctx, path) {
    byData(d, "data-path", path)[0].dispatch("click");
    await tick();
  }

  await test("import: the dialog opens at once with the picker, focus on the path box, and two steps named", async () => {
    const ctx = newCtx();
    ctx.D.live = live;
    const handle = ctx.openImportProject({});
    const d = dialog();
    assert.ok(d, "open before anything was fetched");
    assert.strictEqual(lastFocus, handle.picker.input);
    const steps = walk(d).filter((n) => n.tag === "span" && n.className === "cw-step");
    assert.deepStrictEqual(steps.map((s) => s.getAttribute("aria-label")), ["第 1 步，共 2 步：挑資料夾", "第 2 步，共 2 步：填寫任務卡"]);
    assert.strictEqual(walk(d).find((n) => n.tag === "h2").textContent, "新任務卡：導入專案");
    assert.ok(findText(d, "一張任務卡就是一個資料夾"));
    await tick();
    assert.ok(byData(d, "data-path", PLAIN).length >= 1);
    assert.ok(labels(d).includes("取消"));
  });

  await test("import: a repository goes to step 2 with the title already the folder's name; create posts the checked path and the pane", async () => {
    const { ctx, posts, calls, d } = await openImport();
    await pickFolder(d, ctx, REPO);
    assert.ok(act(d, "next"), "下一步");
    assert.strictEqual(act(d, "next").textContent, "下一步：填寫任務卡");
    assert.ok(!act(d, "open-card") && !act(d, "new-anyway"));
    act(d, "next").dispatch("click");
    assert.ok(findText(d, "demo") && findText(d, REPO));
    const title = walk(d).find((n) => n.tag === "input" && n.getAttribute("aria-label") === "任務標題");
    assert.strictEqual(title.getAttribute("value") || title.value, "demo");
    assert.ok(!findText(d, ctx.NO_GIT_BADGE));
    act(d, "create").dispatch("click");
    await tick();
    assert.strictEqual(posts.length, 1);
    assert.strictEqual(posts[0].workdir, REPO);
    assert.strictEqual(posts[0].title, "demo");
    assert.strictEqual(posts[0].associated_pane_id, "w1:pA");
    assert.strictEqual(posts[0].template, "custom");
    assert.deepStrictEqual(Object.keys(posts[0]).sort(), ["acceptance_criteria", "associated_pane_id", "deliverables", "evidence", "goal", "out_of_scope", "scope", "template", "title", "workdir"]);
    assert.strictEqual(calls.created.length, 1);
    assert.strictEqual(calls.created[0].id, "task-NEW");
    assert.ok(!dialog(), "closed");
  });

  await test("import: a folder without git says so in the design's words and offers 仍要建立 and 換資料夾 only", async () => {
    const { ctx, d, posts } = await openImport();
    await pickFolder(d, ctx, PLAIN);
    const text = textOf(d);
    assert.ok(text.includes(ctx.NO_GIT_NOTE));
    assert.ok(text.includes("這個資料夾還沒有 git 版本紀錄。任務卡可以建立，也能從這裡出發；但隊伍的審查結果要綁定版本編號，在這個資料夾裡不會算數，合併關卡也用不了。"));
    assert.deepStrictEqual(labels(foot(d)), ["取消", "仍要建立", "換資料夾"]);
    act(d, "next").dispatch("click");
    assert.ok(findText(d, ctx.NO_GIT_BADGE), "step 2 keeps saying it");
    assert.ok(findText(d, ctx.NO_GIT_NOTE));
    act(d, "create").dispatch("click");
    await tick();
    assert.strictEqual(posts[0].workdir, PLAIN, "allowed, as the design says");
  });

  await test("import: 換資料夾 empties the answer and the path box", async () => {
    const { ctx, d, handle } = await openImport();
    await pickFolder(d, ctx, PLAIN);
    act(d, "change").dispatch("click");
    assert.strictEqual(handle.picker.input.value, "");
    assert.ok(!findText(d, "沒有版本紀錄"));
    assert.ok(!act(d, "next"));
  });

  await test("import: a folder that has an unfinished card offers to open it first; a new one is the second choice", async () => {
    const open = { known: true, count: 2, items: [{ id: "task-7", title: "Old one" }, { id: "task-8", title: "Other" }] };
    const { ctx, d, calls, posts } = await openImport({ [inspectKey(REPO)]: () => jsonResponse(gitInfo({ tasks: open })) });
    await pickFolder(d, ctx, REPO);
    assert.ok(findText(d, "這個資料夾已經有 2 張未結案的任務卡"));
    assert.deepStrictEqual(labels(foot(d)), ["取消", "打開那張卡（Old one）", "打開「Other」", "仍要建一張新的", "換資料夾"]);
    assert.ok(act(d, "open-card").className.includes("primary"), "the default action");
    assert.ok(!act(d, "next"));
    act(d, "new-anyway").dispatch("click");
    assert.ok(act(d, "create"), "仍要建一張新的 goes to the form");
    act(d, "back").dispatch("click");
    act(d, "open-card").dispatch("click");
    assert.deepStrictEqual(calls.opened, ["task-7"]);
    assert.ok(!dialog());
    assert.strictEqual(posts.length, 0);
  });

  await test("import: one unfinished card says 打開那張卡; with no onOpenTask it goes to the workbench for that card", async () => {
    const open = { known: true, count: 1, items: [{ id: "task-7", title: "Old one" }] };
    const ctx = newCtx({ [inspectKey(REPO)]: () => jsonResponse(gitInfo({ tasks: open })) });
    ctx.D.live = live;
    ctx.openImportProject({});
    await tick();
    const d = dialog();
    await pickFolder(d, ctx, REPO);
    assert.strictEqual(act(d, "open-card").textContent, "打開那張卡");
    act(d, "open-card").dispatch("click");
    assert.strictEqual(ctx.location.hash, "#/workbench?task=task-7");
  });

  await test("import: no title, no card; a failed create keeps the dialog and the typed text", async () => {
    let fail = true;
    const { ctx, d, posts } = await openImport({ "POST /api/tasks": () => (fail ? jsonResponse({ error: "任務卡已達上限 1000 筆" }, 400) : jsonResponse({ ok: true, task: baseTask() })) });
    await pickFolder(d, ctx, REPO);
    act(d, "next").dispatch("click");
    const title = walk(d).find((n) => n.tag === "input" && n.getAttribute("aria-label") === "任務標題");
    title.value = "   ";
    title.dispatch("input");
    act(d, "create").dispatch("click");
    await tick();
    assert.ok(findText(body, "請填寫任務標題"));
    assert.strictEqual(fetchCalls.filter((c) => c.options && c.options.method === "POST").length, 0);
    title.value = "My title";
    title.dispatch("input");
    act(d, "create").dispatch("click");
    await tick();
    assert.ok(findText(body, "建立失敗：任務卡已達上限 1000 筆"));
    assert.ok(dialog(), "still open");
    assert.strictEqual(act(d, "create").disabled, false, "can try again");
    fail = false;
    act(d, "create").dispatch("click");
    await tick();
    assert.ok(!dialog());
  });

  await test("import: step 2 keeps the extra fields under 更多, with Chinese template names and no key in brackets", async () => {
    const { ctx, d, posts } = await openImport();
    await pickFolder(d, ctx, REPO);
    act(d, "next").dispatch("click");
    const more = walk(d).find((n) => n.tag === "details");
    assert.ok(more && walk(more).some((n) => n.tag === "summary" && n.textContent === "更多"));
    const select = walk(more).find((n) => n.tag === "select");
    const optionTexts = walk(select).filter((n) => n.tag === "option").map((n) => n.textContent);
    assert.deepStrictEqual(optionTexts, ["自訂任務", "Bug 修復任務"]);
    assert.ok(!optionTexts.some((t) => /\(|bug_fix|custom/.test(t)));
    select.value = "bug_fix";
    select.dispatch("change");
    const goal = walk(d).filter((n) => n.tag === "textarea")[0];
    assert.strictEqual(goal.value, "修復特定錯誤或異常行為");
    act(d, "create").dispatch("click");
    await tick();
    assert.strictEqual(posts[0].template, "bug_fix");
    assert.strictEqual(posts[0].goal, "修復特定錯誤或異常行為");
    assert.strictEqual(posts[0].scope, "需修復之檔案");
  });

  await test("import: templates that arrive after step 2 opened are used; one that cannot be read leaves the form working", async () => {
    const ctx = newCtx({ "GET /api/task-templates": () => jsonResponse({ error: "x" }, 500) });
    ctx.D.live = live;
    ctx.openImportProject({});
    await tick();
    const d = dialog();
    await pickFolder(d, ctx, REPO);
    act(d, "next").dispatch("click");
    assert.ok(act(d, "create"));
  });

  await test("import: Escape closes it; the page behind is inert while it is open and restored after", async () => {
    const { d } = await openImport();
    assert.strictEqual(main.hasAttribute("inert"), true);
    d.dispatch("keydown", { key: "Escape" });
    assert.ok(!dialog());
    assert.strictEqual(main.hasAttribute("inert"), false);
  });

  await test("import: the dialog controls sit in the sticky footer like the card wizard (reachable on a phone)", async () => {
    const { d, ctx } = await openImport();
    assert.ok(d.children[0].className.includes("cw-box"));
    assert.ok(walk(d).some((n) => n.className === "modal-actions cw-foot" || (n.className.includes("cw-foot"))));
    await pickFolder(d, ctx, REPO);
    act(d, "next").dispatch("click");
    const foot = walk(d).find((n) => n.className.includes("cw-foot"));
    assert.deepStrictEqual(labels(foot), ["取消", "上一步", "建立任務卡"]);
  });

  await test("import: a startPath is checked at once", async () => {
    const ctx = newCtx();
    ctx.D.live = live;
    ctx.openImportProject({ startPath: REPO });
    await tick();
    assert.ok(findText(dialog(), "分支 main · HEAD 01234567"));
  });

  // ---- the front of a task card -------------------------------------------------------------------------------------
  await test("task card front: folder name and path at once, then branch and HEAD, project skills and the terminals by directory", async () => {
    const terms = { known: true, count: 3, items: [{ terminal_id: "a", status: "working", title: "" }, { terminal_id: "b", status: "waiting", title: "" }, { terminal_id: "c", status: "exited", title: "" }] };
    const ctx = newCtx({ [inspectKey(REPO)]: () => jsonResponse(gitInfo({ terminals: terms, project_skill_count: 4 })) });
    const block = ctx.taskFolderBlock(baseTask());
    assert.ok(findText(block, "demo") && findText(block, REPO), "name and path before the answer");
    assert.ok(findText(block, "讀取資料夾資訊"));
    await tick();
    const text = textOf(block);
    assert.ok(text.includes("分支 main · HEAD 01234567"));
    assert.ok(text.includes("這個資料夾目前有 3 個終端"));
    assert.ok(text.includes("1 個等你回覆、1 個工作中、1 個已結束"));
    assert.ok(text.includes("專案技能 4 張"));
    assert.ok(text.includes(ctx.FOLDER_TERMINAL_NOTE));
    assert.ok(!text.includes("在工作"));
    assert.ok(!text.includes(ctx.NO_GIT_BADGE));
    assert.ok(walk(block).some((n) => n.tag === "svg" || n.tag === "rect" || (n.className || "").includes("card-px")), "the folder icon from the art");
  });

  await test("task card front: a folder without git is marked 沒有版本紀錄, with the sentence", async () => {
    const ctx = newCtx();
    const block = ctx.taskFolderBlock(baseTask({ workdir: PLAIN }));
    await tick();
    assert.ok(findText(block, "沒有版本紀錄"));
    assert.ok(findText(block, ctx.NO_GIT_NOTE));
    assert.ok(!findText(block, "分支"));
  });

  await test("task card front: the terminals are unknown when the live view is not read, and the card never says they work", async () => {
    const ctx = newCtx({ [inspectKey(REPO)]: () => jsonResponse(gitInfo({ terminals: { known: false, count: 0, items: [] } })) });
    const block = ctx.taskFolderBlock(baseTask());
    await tick();
    assert.ok(findText(block, "這個資料夾的終端數暫時讀不到"));
    assert.ok(!findText(block, "0 個終端"));
  });

  await test("task card front: a refused, missing or unreadable folder is said, not shown as empty", async () => {
    const ctx = newCtx({ [inspectKey("/Users/tester/.ssh")]: () => jsonResponse({ error: "這個位置不能當成專案" }, 403),
      [inspectKey("/Users/tester/gone")]: () => jsonResponse({ ok: true, path: "/Users/tester/gone", name: "gone", exists: false, is_dir: false }),
      [inspectKey("/Users/tester/boom")]: () => jsonResponse({ error: "內部錯誤：X" }, 500) });
    const a = ctx.taskFolderBlock(baseTask({ workdir: "/Users/tester/.ssh" }));
    const b = ctx.taskFolderBlock(baseTask({ workdir: "/Users/tester/gone" }));
    const c = ctx.taskFolderBlock(baseTask({ workdir: "/Users/tester/boom" }));
    await tick();
    assert.ok(findText(a, "這個位置不能當成專案（請換一個資料夾）"));
    assert.ok(findText(b, "這個資料夾已經不存在或搬走了"));
    assert.ok(findText(c, "讀不到這個資料夾的資訊：內部錯誤：X"));
  });

  await test("task card front: a card made before folders were required says so and offers to pick one", async () => {
    const changed = [];
    const ctx = newCtx({ "POST /api/tasks/task-1": (url, options) => jsonResponse({ ok: true, task: baseTask({ workdir: JSON.parse(options.body).workdir }) }) });
    ctx.D.live = live;
    const block = ctx.taskFolderBlock(baseTask({ workdir: null }), { onChanged: (t) => changed.push(t) });
    assert.ok(findText(block, "還沒有資料夾 · "));
    assert.strictEqual(fetchCalls.filter((c) => c.url.startsWith("/api/folders")).length, 0, "nothing to inspect");
    act(block, "pick-folder").dispatch("click");
    await tick();
    const d = dialog();
    assert.ok(d && findText(d, "選資料夾：Demo task"));
    await pickFolder(d, ctx, REPO);
    assert.strictEqual(act(d, "use").textContent, "設為這張任務卡的資料夾");
    act(d, "use").dispatch("click");
    await tick();
    const post = fetchCalls.find((c) => c.options && c.options.method === "POST");
    assert.strictEqual(post.url, "/api/tasks/task-1");
    assert.deepStrictEqual(JSON.parse(post.options.body), { workdir: REPO });
    assert.strictEqual(changed[0].workdir, REPO);
    assert.ok(!dialog());
  });

  await test("folder dialog: a failed save keeps it open and says why; Escape closes it", async () => {
    const ctx = newCtx({ "POST /api/tasks/task-1": () => jsonResponse({ error: "工作目錄不存在" }, 400) });
    ctx.D.live = live;
    const block = ctx.taskFolderBlock(baseTask({ workdir: null }), {});
    act(block, "pick-folder").dispatch("click");
    await tick();
    const d = dialog();
    await pickFolder(d, ctx, REPO);
    act(d, "use").dispatch("click");
    await tick();
    assert.ok(dialog(), "still open");
    assert.ok(findText(body, "無法使用這個資料夾：工作目錄不存在"));
    d.dispatch("keydown", { key: "Escape" });
    assert.ok(!dialog());
  });

  await test("taskFrontCard: title, status, the folder block and a link that opens the card in the workbench", () => {
    const card = pure.taskFrontCard(baseTask({ id: "task-5", title: "Fix it" }));
    assert.ok(findText(card, "Fix it"));
    assert.ok(findText(card, "草稿"));
    const link = walk(card).find((n) => n.tag === "a");
    assert.strictEqual(link.getAttribute("href"), "#/workbench?task=task-5");
    assert.strictEqual(link.textContent, "打開");
  });

  await test("taskCardsSection: empty gets a start sentence; closed and handed-off cards are not listed; at most six; the button opens the import", async () => {
    const ctx = newCtx();
    ctx.D.live = live;
    const empty = ctx.taskCardsSection([], {});
    assert.ok(findText(empty, "還沒有任務卡"));
    assert.ok(findText(empty, "一張任務卡就是一個資料夾"));
    const tasks = [baseTask({ id: "a", status: "closed" }), baseTask({ id: "b", status: "handed_off" }),
      ...Array.from({ length: 9 }, (_, i) => baseTask({ id: "t" + i, title: "Task " + i }))];
    const sec = ctx.taskCardsSection(tasks, {});
    const cards = walk(sec).filter((n) => n.tag === "article");
    assert.strictEqual(cards.length, 6);
    assert.ok(findText(sec, "還有 3 張未結案的任務卡，"), "the ones not shown are counted and linked");
    assert.ok(walk(sec).some((n) => n.tag === "a" && n.getAttribute("href") === "#/workbench"));
    assert.ok(!cards.some((c) => ["a", "b"].includes(c.getAttribute("data-task"))));
    act(sec, "import").dispatch("click");
    assert.ok(dialog() && findText(dialog(), "新任務卡：導入專案"));
  });

  await test("lobby: viewHome lists the unfinished task cards and the button that imports a project; a task list it cannot read is just an empty section", async () => {
    const ctx = newCtx({ "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [baseTask({ id: "t1", title: "Lobby task" })] }) });
    await ctx.viewHome();
    await tick(6);
    assert.ok(findText(main, "任務卡") && findText(main, "Lobby task"));
    assert.ok(findText(main, "＋ 任務卡（導入專案）"));
    assert.ok(findText(main, "分支 main · HEAD 01234567"));
    const ctx2 = newCtx({ "GET /api/tasks": () => jsonResponse({ error: "x" }, 503) });
    await ctx2.viewHome();
    await tick(6);
    assert.ok(findText(main, "還沒有任務卡"));
  });

  await test("flows page: the create-flow section has the import button", async () => {
    const ctx = newCtx({ "GET /api/flows/storage": () => jsonResponse({ ok: true }) });
    await ctx.viewFlows();
    await tick(6);
    assert.ok(findText(main, "＋ 任務卡（導入專案）"));
  });

  // ---- the workbench -----------------------------------------------------------------------------------------------
  const wbHandlers = (over = {}) => ({
    "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [baseTask(), baseTask({ id: "task-2", title: "No folder", workdir: null })] }),
    "GET /api/governance": () => jsonResponse({ ok: true, global: { categories: [] }, project: { contract: {} } }),
    "GET /api/agent-profiles": () => jsonResponse({ ok: true, profiles: [mkProfile("p-1", "Mine", "claude", ALL_DENY)] }),
    "GET /api/agent-builder/catalog": () => jsonResponse(catalog),
    "GET /api/agent-profiles/p-1/loadout": () => jsonResponse({ ok: true, profile: {}, skills: { items: [] }, armor: { applicable: false }, blockers: [] }),
    ...over,
  });

  await test("workbench: the task tab shows the folder of the card, the button says ＋ 任務卡 and opens the import dialog", async () => {
    const ctx = newCtx(wbHandlers());
    await ctx.viewWorkbench(null, "task-1", null, false);
    await tick(6);
    assert.ok(findText(main, "分支 main · HEAD 01234567"), "folder facts in the task tab");
    const add = btnByText(main, "＋ 任務卡");
    assert.ok(add && !btnByText(main, "＋ 新增"));
    add.dispatch("click");
    assert.ok(dialog() && findText(dialog(), "新任務卡：導入專案"));
  });

  await test("workbench: a card without a folder offers 選資料夾 in the tab", async () => {
    const ctx = newCtx(wbHandlers());
    await ctx.viewWorkbench(null, "task-2", null, false);
    await tick(6);
    assert.ok(findText(main, "還沒有資料夾"));
    assert.ok(act(main, "pick-folder"));
  });

  await test("workbench: creating from the dialog puts the new card first and selects it", async () => {
    const ctx = newCtx(wbHandlers({ "POST /api/tasks": (u, o) => jsonResponse({ ok: true, task: baseTask({ id: "task-NEW", title: JSON.parse(o.body).title, workdir: REPO }) }) }));
    await ctx.viewWorkbench(null, "task-1", null, false);
    await tick(6);
    btnByText(main, "＋ 任務卡").dispatch("click");
    const d = dialog();
    await pickFolder(d, ctx, REPO);
    act(d, "next").dispatch("click");
    act(d, "create").dispatch("click");
    await tick(6);
    assert.ok(findText(main, "demo") && findText(main, "狀態依據"));
    const post = fetchCalls.find((c) => c.options && c.options.method === "POST");
    assert.strictEqual(JSON.parse(post.options.body).workdir, REPO);
  });

  await test("launch check: the allowed range is the real one (the home directory), and there is a folder chooser button", async () => {
    const ctx = newCtx(wbHandlers());
    await ctx.viewWorkbench(null, null, "p-1", true);
    await tick(6);
    const d = dialog();
    assert.ok(d && findText(d, "出發通行證：Mine"));
    assert.ok(findText(d, `可以選的範圍：${HOME} 之內、已經存在的資料夾。`));
    assert.ok(!findText(d, "家目錄內的資料夾"), "not the fixed sentence");
    assert.ok(act(d, "pick-folder"));
    const input = walk(d).find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir");
    assert.strictEqual(input.value, "", "launched alone from the card pool: nothing assumed");
    assert.ok((input.getAttribute("placeholder") || "").includes(HOME + "/projects/demo"));
  });

  await test("launch check: the folder chooser fills the field and asks for a new preview", async () => {
    const ctx = newCtx(wbHandlers());
    await ctx.viewWorkbench(null, null, "p-1", true);
    await tick(6);
    const d = dialog();
    act(d, "pick-folder").dispatch("click");
    await tick();
    const picker = body.children.filter((c) => c.getAttribute && c.getAttribute("role") === "dialog").pop();
    assert.notStrictEqual(picker, d, "a second dialog on top");
    await pickFolder(picker, ctx, REPO);
    assert.strictEqual(act(picker, "use").textContent, "用這個資料夾出發");
    act(picker, "use").dispatch("click");
    await tick();
    const input = walk(d).find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir");
    assert.strictEqual(input.value, REPO);
    assert.ok(findText(d, "輸入已變更，請重新產生預覽。"));
  });

  await test("launch check: opened from a task, the folder of that card is filled in and says where it came from", async () => {
    const ctx = newCtx(wbHandlers());
    await ctx.viewWorkbench(null, "task-1", "p-1", true);
    await tick(6);
    const d = dialog();
    const input = walk(d).find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir");
    assert.strictEqual(input.value, REPO);
    assert.ok(findText(d, "已帶入任務卡「Demo task」的資料夾，可以改。"));
    // a card without a folder, or an unknown task, fills nothing
    const ctx2 = newCtx(wbHandlers());
    await ctx2.viewWorkbench(null, "task-2", "p-1", true);
    await tick(6);
    const input2 = walk(dialog()).find((n) => n.tag === "input" && n.getAttribute("id") === "agent-launch-workdir");
    assert.strictEqual(input2.value, "");
  });

  // ---- the page source: the honesty rules and the house rules ------------------------------------------------------
  const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const block = app.slice(app.indexOf("// ---------- task cards are folders"), app.indexOf("// ---------- router"));

  await test("source: the new block builds with el(), has no innerHTML, no emoji, no outside resource", () => {
    assert.ok(block.length > 5000, "found the block");
    assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(block));
    assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(block.replace(/[＋…]/g, "")), "no emoji");
    assert.ok(!/https?:\/\//.test(block));
    assert.ok(!/\bfetch\(|XMLHttpRequest|WebSocket|importScripts/.test(block), "only api.get / api.post");
    assert.ok(!/api\.post\([^)]*folders/.test(block), "nothing is ever posted to the folder API");
    assert.ok(/api\.get\(folderInspectUrl\(/.test(block));
  });

  await test("source: the card words — no old terms on screen, no numbers/levels/rarity, no 'working' said about terminals", () => {
    for (const bad of ["Profile", "AgentRole", "Agent Builder", "Permission Intents", "equipped skills"]) assert.ok(!block.includes(bad), bad);
    assert.ok(!/稀有|等級|星數|抽卡|攻擊力|防禦力|傷害|經驗值/.test(block), "no stats, levels, rarity or draws");
    assert.ok(!block.includes("在工作"), "R8: 'in work' is not said");
    assert.ok(!/(安全|已限制|已擋住)/.test(block.replace(/不代表[^"]*/g, "")), "nothing here claims safety");
    assert.ok(block.includes("這個資料夾目前有 ${terminals.count} 個終端"));
  });

  await test("source: the picker opens nothing by itself (no window.open, no navigation from typed text)", () => {
    assert.ok(!/window\.open\(/.test(block));
    assert.ok(!/location\.(href|assign|replace)\b/.test(block));
    // the only navigation is to a task card the server named, by its id
    const hashes = block.match(/location\.hash = [^;]+;/g) || [];
    assert.deepStrictEqual(hashes, ["location.hash = `#/workbench?task=${encodeURIComponent(id)}`;"]);
  });

  // ---- P9: full-width brackets next to full stops, and a list that shows it can scroll ------------------------------
  await test("P9: NO_GIT_NOTE has no full-width bracket next to a full stop, semicolon or comma, and still says all of it", () => {
    const note = pure.NO_GIT_NOTE;
    assert.ok(!/[\uff09\u300d\u300f][\u3002\uff1b\u3001\uff0c]/.test(note), note);
    assert.ok(!note.includes("\uff09\u3002"));
    for (const part of ["git 版本紀錄", "任務卡可以建立", "也能從這裡出發", "審查結果要綁定版本編號", "不會算數", "合併關卡也用不了"]) assert.ok(note.includes(part), part);
    assert.ok(!note.includes("沒有版本紀錄（"), "the badge text stays the badge, the note is a sentence of its own");
  });

  await test("P9: the sentences of the main paths that used to end a bracket right before a stop were reworded", () => {
    const gone = ["（只是提醒，仍然可以用這個名字）。", "（只是提醒）。", "（沒有找到固定版本的安裝）。", "（這次讀不到實際範圍）。",
      "（${turnOf(ns.after.who)}）。", "（第二位審查選填）。", "（新開一個終端）。", "（唯讀）並存", "（限已測的路徑、版本與執行層）。",
      "（關聯只是追蹤記錄，不會把內容送進終端）。", "有效（到 ${fmtTime", "（或無法確認）；", "（存在 ${refs.present"];
    for (const g of gone) assert.ok(!source.includes(g), g);
    const there = ["已經有一張叫「${same.name}」的卡，只是提醒，仍然可以用這個名字。", "找不到 Codex，沒有找到固定版本的安裝。", "接下來：${ns.after.text}，${turnOf(ns.after.who)}。",
      "審查各一位，第二位審查選填。", "必須重新啟動角色，也就是新開一個終端。", "已實測確實擋住，限已測的路徑、版本與執行層。"];
    for (const t of there) assert.ok(source.includes(t), t);
  });

  await test("P9: folderListHidesMore reads the box's own measures (more below the edge, with a little slack)", () => {
    const row = (scrollHeight, clientHeight, scrollTop) => ({ scrollHeight, clientHeight, scrollTop });
    assert.strictEqual(pure.folderListHidesMore(row(500, 220, 0)), true, "rows below the edge");
    assert.strictEqual(pure.folderListHidesMore(row(500, 220, 100)), true, "halfway");
    assert.strictEqual(pure.folderListHidesMore(row(500, 220, 280)), false, "the end is in view");
    assert.strictEqual(pure.folderListHidesMore(row(500, 220, 277)), false, "within the slack of the end");
    assert.strictEqual(pure.folderListHidesMore(row(220, 220, 0)), false, "everything fits");
    assert.strictEqual(pure.folderListHidesMore(row(223, 220, 0)), false, "a few pixels over is not a hidden row");
    assert.strictEqual(pure.folderListHidesMore(row(0, 0, 0)), false, "not laid out yet");
    assert.strictEqual(pure.folderListHidesMore(null), false);
    assert.strictEqual(pure.folderListMoreText(12), "共 12 個，往下捲動看更多");
  });

  await test("P9: the list of seen projects says there is more only while rows are hidden, and the line goes with the end of the list", () => {
    const ctx = newCtx();
    const picker = ctx.folderPicker({ live });
    const seen = walk(picker.node).find((n) => n.classList && n.classList.contains("fp-items"));
    const more = byData(picker.node, "data-fp", "more")[0];
    assert.ok(seen && more, "the list and its line exist");
    assert.ok(more.hidden === true || more.hasAttribute("hidden"), "hidden until the box is measured");
    assert.ok(!seen.hasAttribute("data-more"));
    assert.ok(more.textContent.startsWith("共 ") && more.textContent.endsWith("個，往下捲動看更多"), more.textContent);
    Object.assign(seen, { scrollHeight: 640, clientHeight: 220, scrollTop: 0 });
    seen.dispatch("scroll");
    assert.strictEqual(seen.getAttribute("data-more"), "1", "the edge fades");
    assert.strictEqual(more.hidden, false, "and the line shows");
    seen.scrollTop = 420;
    seen.dispatch("scroll");
    assert.ok(!seen.hasAttribute("data-more"), "at the end the fade is gone");
    assert.strictEqual(more.hidden, true);
    Object.assign(seen, { scrollHeight: 200, clientHeight: 220, scrollTop: 0 });
    seen.dispatch("scroll");
    assert.ok(!seen.hasAttribute("data-more"), "a short list never does");
  });

  await test("P9: a list with nothing in it has no fade line (no list to scroll)", () => {
    const ctx = newCtx();
    const picker = ctx.folderPicker({ live: { home: "/Users/tester", projects: [] } });
    assert.strictEqual(byData(picker.node, "data-fp", "more").length, 0);
  });

  // ---- the css -----------------------------------------------------------------------------------------------------
  await test("CSS: the picker, the import dialog and the card front are styled; the list collapses to one column on a phone", () => {
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    for (const sel of [".fp-items", ".fp-item", ".fp-result", ".tf-card", ".tf-block", ".tf-git", ".tf-actions"]) assert.ok(css.includes(sel + " {") || css.includes(sel + ","), sel);
    assert.ok(/@media \(max-width: 720px\)\s*\{\s*\.fp-items \{ grid-template-columns: 1fr;/.test(css), "one column on a phone");
    assert.ok(/\.fp-path \{[^}]*overflow-wrap: anywhere/.test(css), "a long path wraps");
    assert.ok(!/url\(\s*["']?https?:/.test(css));
  });

  await test("CSS P9: the fade is on the scroll box only while it has more (data-more), has no global text-spacing rule, and hides the line when [hidden]", () => {
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    assert.ok(/\.fp-items\[data-more="1"\] \{[^}]*mask-image: linear-gradient\(to bottom, #000 calc\(100% - \d+px\), transparent\)/.test(css));
    assert.ok(/\.fp-items\[data-more="1"\] \{[^}]*-webkit-mask-image/.test(css), "WebKit spelling too");
    assert.ok(/\.fp-more\[hidden\] \{ display: none; \}/.test(css));
    assert.ok(!/text-spacing-trim|font-feature-settings:\s*["']halt/.test(css), "no sitewide typography change for the bracket spacing");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL TASK FOLDER FRONTEND TESTS PASSED");
})();
