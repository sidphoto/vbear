// P4 (design card-play 3.5, R6, 6): role cards on a task card — the team places, slotProblem, the next steps, the draft,
// "放上任務卡", the stale-card hint, and the honesty rules (a review that cannot count is said plainly; nothing here starts
// or sends anything; the only writes are the flow and its roles).
// Runs the real functions of web/app.js against a synthetic DOM and a fetch stub. It is NOT a browser test.
//
// Run: node tests/frontend/team_slots.cjs   (exit code 0 = pass)
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


// ---- fixtures ---------------------------------------------------------------------------------------------------
const HOME = "/Users/tester";
const REPO = HOME + "/projects/demo";
const PLAIN = HOME + "/notes";
const SHA = "0123456789abcdef0123456789abcdef01234567";
const REV = (c) => c.repeat(64);
const gitInfo = (over = {}) => ({ ok: true, path: REPO, name: "demo", exists: true, is_dir: true,
  git: { is_repo: true, root: REPO, branch: "main", commit: SHA, short: SHA.slice(0, 8), error: null },
  project_skill_count: 2, terminals: { known: true, count: 0, items: [] }, tasks: { known: true, items: [], count: 0 }, ...over });
const plainInfo = () => ({ ok: true, path: PLAIN, name: "notes", exists: true, is_dir: true,
  git: { is_repo: false, root: null, branch: null, commit: null, short: null, error: null },
  project_skill_count: 0, terminals: { known: true, count: 0, items: [] }, tasks: { known: true, items: [], count: 0 } });
const inspectKey = (p) => `GET /api/folders/inspect?path=${encodeURIComponent(p)}`;
const mkCard = (id, name, tool, rev, extra = {}) => ({ id, name, profession_role_id: null, model: { tool, model_id: "" },
  equipped_skill_ids: [], permission_intents: { read: "allow", write: "deny", test: "deny", deploy: "deny" }, enabled: true,
  created_at: 1, updated_at: 1, revision: rev, _unresolved: { profession: false, skills: [] }, ...extra });
const CEO = mkCard("p-ceo", "CEO", "claude", REV("1"));
const MAKER = mkCard("p-maker", "工匠", "claude", REV("2"));
const REVIEWER = mkCard("p-rev", "審查員", "codex", REV("3"));
const SHARED = mkCard("p-shared", "共用卡", "shared", REV("4"));
const PROFILES = [CEO, MAKER, REVIEWER, SHARED];
const baseTask = (over = {}) => ({ id: "task-1", title: "Demo task", status: "draft", workdir: REPO, ...over });
const FLOW_ID = "flow-0123456789ab";
const flowView = (over = {}) => ({ id: FLOW_ID, task_id: "task-1", task_title: "Demo task", task_missing: false, created_at: 1,
  roles: {
    planner: { name: "CEO", family: "anthropic", family_label: "Anthropic（Claude）", profile_id: "p-ceo",
      profile_snapshot: { name: "CEO", tool: "claude", model_id: "", revision: REV("1") } },
    executor: { name: "工匠", family: "anthropic", family_label: "Anthropic（Claude）", workdir: REPO, session_id: "n-0123456789ab",
      profile_id: "p-maker", profile_snapshot: { name: "工匠", tool: "claude", model_id: "", revision: REV("2") } },
    reviewers: [{ name: "審查員", family: "openai", family_label: "OpenAI（Codex）", profile_id: "p-rev",
      profile_snapshot: { name: "審查員", tool: "codex", model_id: "", revision: REV("3") } }],
  },
  phase: { key: "implementing", label: "實作中", reason: "執行者實作中" }, automation: { mode: "manual" }, events: [], ...over });
const live = { home: HOME, sessions: [], projects: [], attention: [], usage: { sessions: [] }, runtime: { available: true, problems: [] } };
const catalog = { ok: true, tools: ["claude", "codex", "shared"], demo_id_prefix: "demo-", starter_deck: [] };

function handlers(over = {}) {
  return {
    "GET /api/live": () => jsonResponse(live),
    "GET /api/flows": () => jsonResponse({ ok: true, flows: [], families: [] }),
    "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [baseTask()] }),
    "GET /api/agent-profiles": () => jsonResponse({ ok: true, profiles: PROFILES }),
    "GET /api/agent-builder/catalog": () => jsonResponse(catalog),
    "GET /api/config": () => jsonResponse({ config: { recent_folders: [] }, state_dir: "/x" }),
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
  for (const a of ["inert", "aria-hidden"]) main.removeAttribute(a);
  for (const name of ["NO_GIT_BADGE", "NO_GIT_NOTE", "TEAM_INFO", "TEAM_SLOTS", "SLOT_REVIEW_NEEDS_DIFF", "TEAM_SAVE_NOTE", "D"]) ctx[name] = vm.runInContext(name, ctx);
  return ctx;
}
const plain = (x) => JSON.parse(JSON.stringify(x));
const buttons = (root) => walk(root).filter((n) => n.tag === "button");
const act = (root, name) => byData(root, "data-act", name)[0];
const slotNode = (root, key) => byData(root, "data-slot", key)[0];
const slotButton = (root, key) => act(slotNode(root, key), "slot");
const pick = (root, id) => byData(root, "data-pick", id)[0];
const chip = (root, id) => byData(root, "data-card", id)[0];
const saveButton = (root) => act(root, "save");
function board(ctx, { flow = null, profiles = PROFILES, task = baseTask(), gitState = "git", onSaved } = {}) {
  const b = ctx.teamBoard({ task, flow, profiles, catalog, gitState, onSaved });
  main.append(b.node);
  return b;
}
function putVia(b, key, id) {
  slotButton(b.node, key).click();
  pick(b.node, id).click();
}
const posts = () => fetchCalls.filter((c) => c.options && c.options.method === "POST");
const bodyOf = (c) => JSON.parse(c.options.body);

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log("ok   -", name); }
  catch (e) { console.log("FAIL -", name); console.log(e && e.stack || e); process.exitCode = 1; }
}

(async () => {
  const pure = newCtx();

  // ---- pure functions --------------------------------------------------------------------------------------------
  await test("teamFamily: claude is anthropic, codex is openai, agy is google, shared and anything else is unknown", () => {
    const rows = [["claude", "anthropic"], ["codex", "openai"], ["shared", "unknown"], ["agy", "google"], ["gemini", "unknown"], ["AGY", "unknown"], ["", "unknown"], [null, "unknown"],
      [undefined, "unknown"], ["toString", "unknown"], ["constructor", "unknown"], [5, "unknown"]];
    for (const [tool, want] of rows) assert.strictEqual(pure.teamFamily(tool), want, String(tool));
  });

  await test("teamCardTool: a card or snapshot says its tool; a hand-written role is read back from its family only where a tool exists", () => {
    const rows = [[{ model: { tool: "codex" } }, "codex"], [{ tool: "claude" }, "claude"], [{ profile_snapshot: { tool: "shared" }, family: "openai" }, "shared"],
      [{ family: "anthropic" }, "claude"], [{ family: "openai" }, "codex"], [{ family: "google" }, ""], [{ family: "unknown" }, ""], [{ family: "toString" }, ""],
      [{}, ""], [null, ""], ["x", ""]];
    for (const [card, want] of rows) assert.strictEqual(pure.teamCardTool(card), want, JSON.stringify(card));
  });

  await test("teamCardFamily: a role says its own family; a card is read from its tool; nothing readable is unknown", () => {
    const rows = [[{ family: "openai" }, "openai"], [{ family: "weird", model: { tool: "claude" } }, "anthropic"], [{ model: { tool: "codex" } }, "openai"],
      [{ tool: "claude" }, "anthropic"], [{ model: { tool: "shared" } }, "unknown"], [{}, "unknown"], [null, "unknown"], ["x", "unknown"],
      [{ family: "other" }, "other"], [{ family: "google" }, "google"]];
    for (const [card, want] of rows) assert.strictEqual(pure.teamCardFamily(card), want, JSON.stringify(card));
  });

  await test("slotProblem: row by row — only a review place can be wrong, exactly as the server judges a review", () => {
    const claude = { model: { tool: "claude" } }, codex = { model: { tool: "codex" } }, shared = { model: { tool: "shared" } };
    const other = { family: "other" }, google = { family: "google" }, anth = { family: "anthropic" };
    const rows = [
      // slot,       card,   executor, expected code
      ["reviewer1", codex, claude, null],
      ["reviewer1", claude, claude, "same_family"],
      ["reviewer1", codex, codex, "same_family"],
      ["reviewer1", shared, claude, "reviewer_family_unknown"],
      ["reviewer1", shared, null, "reviewer_family_unknown"],
      ["reviewer1", other, claude, "reviewer_family_unknown"],
      ["reviewer1", codex, shared, "executor_family_unknown"],
      ["reviewer1", codex, other, "executor_family_unknown"],
      ["reviewer1", codex, null, null],
      ["reviewer1", google, anth, null],
      ["reviewer1", anth, anth, "same_family"],
      ["reviewer2", claude, claude, "same_family"],
      ["reviewer2", codex, claude, null],
      ["reviewer2", shared, codex, "reviewer_family_unknown"],
      ["planner", claude, claude, null],
      ["planner", shared, claude, null],
      ["executor", claude, claude, null],
      ["executor", shared, codex, null],
      ["reviewer1", null, claude, null],
      ["nonsense", claude, claude, null],
      [undefined, claude, claude, null],
    ];
    for (const [slot, card, executor, want] of rows) {
      const got = pure.slotProblem(slot, card, { executor });
      assert.strictEqual(got ? got.code : null, want, `${slot} ${JSON.stringify(card)} vs ${JSON.stringify(executor)}`);
      if (got) {
        assert.strictEqual(got.text, "這個位置需要和執行位不同陣營的卡，審查結果才算數");
        assert.ok(got.why && got.why.length > 4, "says why");
      }
    }
    assert.strictEqual(pure.slotProblem("reviewer1", codex, null), null, "no team yet");
  });

  await test("slotProblem agrees with the server's rule: both families known and different, nothing else counts", () => {
    const families = ["anthropic", "openai", "google", "minimax", "other", "unknown"];
    for (const e of families) for (const r of families) {
      const counted = !["unknown", "other"].includes(e) && !["unknown", "other"].includes(r) && e !== r;
      const got = pure.slotProblem("reviewer1", { family: r }, { executor: { family: e } });
      assert.strictEqual(got === null, counted, `${e} / ${r}`);
    }
  });

  await test("roleFromCard: name, family from the tool, model, and the card's id with a snapshot of its revision", () => {
    const role = plain(pure.roleFromCard({ ...CEO, model: { tool: "claude", model_id: "claude-x" } }));
    assert.deepStrictEqual(role, { name: "CEO", family: "anthropic", model: "claude-x", profile_id: "p-ceo",
      profile_snapshot: { name: "CEO", tool: "claude", model_id: "claude-x", revision: REV("1") } });
    assert.strictEqual(pure.roleFromCard(REVIEWER).family, "openai");
    assert.strictEqual(pure.roleFromCard(SHARED).family, "unknown");
    assert.ok(!("model" in pure.roleFromCard(CEO)), "no model when the card names none");
  });

  await test("roleFromCard: a long name is cut for the role and kept whole in the snapshot; a long model id is left out, not cut", () => {
    const long = "名".repeat(120);
    const role = plain(pure.roleFromCard({ ...CEO, name: long, model: { tool: "claude", model_id: "m".repeat(120) } }));
    assert.strictEqual(role.name.length, 80);
    assert.strictEqual(role.profile_snapshot.name, long);
    assert.ok(!("model" in role));
    assert.strictEqual(role.profile_snapshot.model_id.length, 120);
  });

  await test("roleFromCard: without a usable revision (or an unknown tool) the role carries no card fields at all", () => {
    for (const bad of [{ ...CEO, revision: undefined }, { ...CEO, revision: "short" }, { ...CEO, revision: "A".repeat(64) }, { ...CEO, revision: 5 },
      { ...CEO, model: { tool: "gemini", model_id: "" } }]) {
      const role = plain(pure.roleFromCard(bad));
      assert.ok(!("profile_id" in role) && !("profile_snapshot" in role), JSON.stringify(bad.revision));
    }
  });

  await test("roleFromCard: an executor keeps its session and folder when only the card changes, and starts from the task's folder", () => {
    const keep = { name: "old", family: "anthropic", session_id: "n-0123456789ab", workdir: "/a/b" };
    assert.strictEqual(pure.roleFromCard(MAKER, { executor: true, keep, workdir: "/task" }).session_id, "n-0123456789ab");
    assert.strictEqual(pure.roleFromCard(MAKER, { executor: true, keep, workdir: "/task" }).workdir, "/a/b");
    assert.strictEqual(pure.roleFromCard(MAKER, { executor: true, workdir: "/task" }).workdir, "/task");
    assert.ok(!("workdir" in pure.roleFromCard(MAKER, { executor: true })));
    assert.ok(!("session_id" in pure.roleFromCard(MAKER, { keep, workdir: "/task" })), "only the executor has them");
    assert.ok(!("workdir" in pure.roleFromCard(MAKER, { keep, workdir: "/task" })));
  });

  await test("teamMissing and teamRolesBody: planner, executor and one review are needed; the empty second review is never sent", () => {
    const slots = pure.teamSlotsFromRoles(null);
    assert.deepStrictEqual(plain(pure.teamMissing(slots)), ["規劃位", "執行位", "審查位"]);
    assert.strictEqual(pure.teamRolesBody(slots), null);
    slots.planner = pure.roleFromCard(CEO);
    slots.executor = pure.roleFromCard(MAKER, { executor: true, workdir: REPO });
    assert.deepStrictEqual(plain(pure.teamMissing(slots)), ["審查位"]);
    assert.strictEqual(pure.teamRolesBody(slots), null);
    slots.reviewer2 = pure.roleFromCard(REVIEWER);
    assert.strictEqual(pure.teamRolesBody(slots), null, "a second review does not stand in for the first");
    slots.reviewer1 = pure.roleFromCard(REVIEWER);
    let body = plain(pure.teamRolesBody(slots));
    assert.strictEqual(body.reviewers.length, 2);
    slots.reviewer2 = null;
    body = plain(pure.teamRolesBody(slots));
    assert.strictEqual(body.reviewers.length, 1, "the empty place is not counted");
    assert.deepStrictEqual(Object.keys(body).sort(), ["executor", "planner", "reviewers"]);
    assert.strictEqual(body.executor.workdir, REPO);
    assert.strictEqual(body.planner.profile_id, "p-ceo");
  });

  await test("teamRolesBody sends only the role's own fields — no UI keys, and session/folder only on the executor", () => {
    const slots = { planner: { ...pure.roleFromCard(CEO), family_label: "x", independent_of_executor: {}, session_id: "n-0123456789ab", workdir: "/x" },
      executor: { ...pure.roleFromCard(MAKER, { executor: true, workdir: REPO }), family_label: "y", stray: 1 },
      reviewer1: { ...pure.roleFromCard(REVIEWER), workdir: "/z", independent_of_executor: {} }, reviewer2: null };
    const body = plain(pure.teamRolesBody(slots));
    const allowed = ["name", "family", "model", "profile_id", "profile_snapshot"];
    for (const r of [body.planner, ...body.reviewers]) for (const k of Object.keys(r)) assert.ok(allowed.includes(k), k);
    for (const k of Object.keys(body.executor)) assert.ok([...allowed, "session_id", "workdir"].includes(k), k);
  });

  await test("teamCardState: manual, gone, same, changed and unknown", () => {
    const entry = pure.roleFromCard(CEO);
    assert.strictEqual(pure.teamCardState({ name: "x", family: "other" }, PROFILES).state, "manual");
    assert.strictEqual(pure.teamCardState(null, PROFILES).state, "manual");
    assert.strictEqual(pure.teamCardState(entry, []).state, "gone");
    assert.strictEqual(pure.teamCardState(entry, PROFILES).state, "same");
    assert.strictEqual(pure.teamCardState(entry, [{ ...CEO, revision: REV("9") }]).state, "changed");
    assert.strictEqual(pure.teamCardState(entry, [{ ...CEO, revision: undefined }]).state, "unknown");
    assert.strictEqual(pure.teamCardState(entry, [{ ...CEO, revision: REV("9") }]).current.revision, REV("9"));
  });

  await test("a draft keeps only card ids; a card that is gone, or junk, simply is not there", () => {
    const ctx = newCtx();
    ctx.teamDraftWrite("t-1", { planner: ctx.roleFromCard(CEO), executor: ctx.roleFromCard(MAKER, { executor: true }), reviewer1: null, reviewer2: null });
    const raw = JSON.parse(ctx.__ls.get([...ctx.__ls.keys()].find((k) => k.includes("team.draft.t-1"))));
    const value = typeof raw === "string" ? JSON.parse(raw) : raw;
    assert.deepStrictEqual(plain(value), { planner: "p-ceo", executor: "p-maker" });
    const read = ctx.teamDraftRead("t-1", [CEO], "/wd");
    assert.strictEqual(read.planner.name, "CEO");
    assert.strictEqual(read.executor, null, "the executor's card is gone");
    ctx.teamDraftWrite("t-1", { planner: null, executor: null, reviewer1: null, reviewer2: null });
    assert.ok(ctx.teamDraftRead("t-1", PROFILES, "/wd").planner === null, "an empty draft is removed");
    for (const junk of ["x", 5, [], { planner: 7 }, { planner: "nope" }]) {
      ctx.__ls.set([...ctx.__ls.keys()].find((k) => k.includes("team.draft.t-1")) || "vbear.team.draft.t-1", JSON.stringify(junk));
      assert.deepStrictEqual(plain(ctx.teamDraftRead("t-1", PROFILES, "/wd")), { planner: null, executor: null, reviewer1: null, reviewer2: null });
    }
  });

  // ---- nextSteps --------------------------------------------------------------------------------------------------
  const fv = (phaseKey, extra = {}) => flowView({ phase: { key: phaseKey, label: phaseKey, reason: "原因：" + phaseKey }, ...extra });
  await test("nextSteps: the steps, who does each, and whose turn it is, row by row (manual mode)", () => {
    const names = (ns) => ns.steps.map((s) => s.key);
    const rows = [
      // phase, current step key, turn
      ["planning", "plan", "CEO"],
      ["awaiting_approval", "approve", "你"],
      ["implementing", "implement", "工匠"],
      ["needs_fix", "implement", "工匠"],
      ["in_review", "review", "審查員"],
      ["review_stale", "review", "審查員"],
      ["awaiting_merge", "merge", "你"],
      ["review_unverified", "merge", "你"],
    ];
    for (const [phase, key, turn] of rows) {
      const ns = pure.nextSteps(fv(phase));
      assert.deepStrictEqual(plain(names(ns)), ["plan", "approve", "implement", "review", "merge"], "step 3 is only for automatic mode");
      assert.strictEqual(ns.known, true);
      assert.strictEqual(ns.steps[ns.current].key, key, phase);
      assert.strictEqual(ns.turn, turn, phase);
      assert.strictEqual(ns.steps.filter((s) => s.state === "now").length, 1, phase);
      ns.steps.forEach((s, i) => assert.strictEqual(s.state, i < ns.current ? "past" : i === ns.current ? "now" : "next", `${phase} ${s.key}`));
      assert.strictEqual(ns.reason, "原因：" + phase, "the server's reason stays beside the step");
    }
  });

  await test("nextSteps: the push comes after step 6 and is yours; a finished flow has every step past; an unknown phase claims nothing", () => {
    const push = pure.nextSteps(fv("awaiting_push"));
    assert.strictEqual(push.current, -1);
    assert.ok(push.steps.every((s) => s.state === "past"));
    assert.deepStrictEqual(plain(push.after), { text: "你自己上傳到遠端", who: "你" });
    assert.strictEqual(push.turn, "你");
    const done = pure.nextSteps(fv("done"));
    assert.ok(done.steps.every((s) => s.state === "past") && done.after === null && done.turn === null);
    for (const bad of [fv("brand_new_phase"), fv(""), { phase: {} }, {}, null, undefined, { phase: { key: 5 } }]) {
      const ns = pure.nextSteps(bad);
      assert.strictEqual(ns.known, false);
      assert.ok(ns.steps.every((s) => s.state === "next"), "no step is marked");
      assert.strictEqual(ns.turn, null);
    }
  });

  await test("nextSteps: automatic mode adds step 3 (you accept the risk) and VBear sends the review; manual review is by the reviewer cards", () => {
    const auto = { automation: { mode: "auto" } };
    const ns = pure.nextSteps(fv("implementing", auto));
    assert.deepStrictEqual(plain(ns.steps.map((s) => s.key)), ["plan", "approve", "risk", "implement", "review", "merge"]);
    assert.strictEqual(ns.steps[ns.current].key, "implement");
    assert.strictEqual(ns.steps[2].who, "你");
    assert.strictEqual(ns.steps[2].state, "past");
    const rv = pure.nextSteps(fv("in_review", auto));
    assert.strictEqual(rv.turn, "VBear（自動送審）");
    assert.ok(rv.steps.find((s) => s.key === "review").who.startsWith("VBear 送審"));
    const manual = pure.nextSteps(fv("in_review"));
    assert.strictEqual(manual.steps.find((s) => s.key === "review").who, "審查員");
    const two = flowView({ phase: { key: "in_review", label: "x", reason: "" } });
    two.roles.reviewers.push({ name: "第二", family: "google" });
    assert.strictEqual(pure.nextSteps(two).turn, "審查員、第二");
    for (const m of [{ mode: "manual" }, undefined, {}]) assert.strictEqual(pure.nextSteps(fv("planning", { automation: m })).steps.length, 5);
  });

  await test("nextSteps: texts are the six steps of the design, in order", () => {
    const ns = pure.nextSteps(fv("planning", { automation: { mode: "auto" } }));
    assert.deepStrictEqual(plain(ns.steps.map((s) => s.text)), ["規劃者提出計畫", "你核准計畫", "你接受風險", "執行者實作", "審查者檢查", "你自己合併"]);
  });

  await test("nextStepSummary: one honest line for the card front", () => {
    assert.strictEqual(pure.nextStepSummary(fv("implementing")), "下一步：執行者實作（輪到工匠）");
    assert.strictEqual(pure.nextStepSummary(fv("awaiting_merge")), "下一步：你自己合併（輪到你）");
    assert.strictEqual(pure.nextStepSummary(fv("awaiting_push")), "下一步：你自己上傳到遠端（輪到你）");
    assert.strictEqual(pure.nextStepSummary(fv("done")), "這個流程的步驟都走完了");
    assert.strictEqual(pure.nextStepSummary(fv("???")), "", "an unknown phase is not turned into a step");
  });

  await test("nextStepsList: the current step is bold and says whose turn; the reason stays beside it; info tips on risk and executor", () => {
    const node = pure.nextStepsList(fv("implementing", { automation: { mode: "auto" } }));
    const now = byData(node, "data-state", "now");
    assert.strictEqual(now.length, 1);
    assert.strictEqual(now[0].getAttribute("aria-current"), "step");
    assert.ok(walk(now[0]).some((n) => n.tag === "strong" && n.textContent === "執行者實作"));
    assert.ok(findText(now[0], "輪到工匠"));
    assert.ok(findText(now[0], "原因：implementing"));
    const risk = byData(node, "data-step", "risk")[0];
    assert.ok(walk(risk).some((n) => n.className === "armory-tip" && n.getAttribute("data-tip") === pure.TEAM_INFO.risk));
    assert.ok(walk(now[0]).some((n) => n.className === "armory-tip" && n.getAttribute("data-tip") === pure.TEAM_INFO.executor));
    assert.ok(!walk(byData(node, "data-state", "past")[0]).some((n) => n.getAttribute && n.getAttribute("data-ns") === "turn"));
    const unknown = pure.nextStepsList(fv("zzz"));
    assert.ok(findText(unknown, "無法對應到步驟") && byData(unknown, "data-state", "now").length === 0);
    const push = pure.nextStepsList(fv("awaiting_push"));
    assert.ok(findText(byData(push, "data-ns", "after")[0], "你自己上傳到遠端"));
  });

  await test("info tips: the fixed sentences exist for 風險接受, 體力 and 串流執行者, and claim nothing VBear does not do", () => {
    for (const k of ["risk", "stamina", "executor"]) {
      assert.ok(pure.TEAM_INFO[k].length > 30, k);
      assert.ok(!/(安全|已限制|已擋住|保證)/.test(pure.TEAM_INFO[k]), k);
    }
    assert.ok(pure.TEAM_INFO.risk.includes("不會讓 VBear 多擋住什麼"));
    assert.ok(pure.TEAM_INFO.stamina.includes("連續失敗 1 次就停止"));
  });

  await test("info tips sit beside 風險接受 and 串流執行者 on the flow page", () => {
    const panel = pure.s2AcceptancePanel(FLOW_ID, { acceptance: { state: "none" }, automation: { mode: "manual" } }, () => {});
    const tips = walk(panel).filter((n) => n.className === "armory-tip");
    assert.ok(tips.some((n) => n.getAttribute("data-tip") === pure.TEAM_INFO.risk));
    assert.ok(findText(panel, "風險接受"));
  });

  // ---- the board --------------------------------------------------------------------------------------------------
  await test("board (no flow): four places, the second review dashed and optional, the save button off, what is missing said", () => {
    const ctx = newCtx();
    const b = board(ctx);
    const slots = walk(b.node).filter((n) => n.getAttribute && n.getAttribute("data-slot"));
    assert.deepStrictEqual(slots.map((n) => n.getAttribute("data-slot")), ["planner", "executor", "reviewer1", "reviewer2"]);
    assert.ok(slots.every((n) => n.getAttribute("data-state") === "empty"));
    assert.ok(slots[3].classList.contains("ts-optional") && slots[3].classList.contains("ts-vacant"));
    assert.ok(findText(slots[3], "第二位審查（選填）"));
    assert.strictEqual(saveButton(b.node).disabled, true);
    assert.ok(findText(byData(b.node, "data-team", "missing")[0], "還差：規劃位、執行位、審查位"));
    assert.strictEqual(saveButton(b.node).textContent.trim(), "建立隊伍");
    assert.deepStrictEqual(plain(ctx.TEAM_SLOTS.map((s) => s.key)), ["planner", "executor", "reviewer1", "reviewer2"]);
  });

  await test("board: click a place, a list of cards opens; picking one fills it; the executor takes the task's folder", () => {
    const ctx = newCtx();
    const b = board(ctx);
    slotButton(b.node, "executor").click();
    const menu = byData(b.node, "data-menu", "executor")[0];
    assert.ok(menu, "the list is open");
    assert.strictEqual(slotButton(b.node, "executor").getAttribute("aria-expanded"), "true");
    for (const id of ["p-ceo", "p-maker", "p-rev", "p-shared"]) assert.ok(pick(b.node, id), id);
    pick(b.node, "p-maker").click();
    assert.strictEqual(slotNode(b.node, "executor").getAttribute("data-state"), "filled");
    assert.ok(findText(slotNode(b.node, "executor"), "工匠"));
    assert.strictEqual(b.state.slots.executor.workdir, REPO);
    assert.strictEqual(b.state.slots.executor.profile_id, "p-maker");
    assert.ok(!byData(b.node, "data-menu", "executor")[0], "the list closed");
  });

  await test("board: Escape closes the list; a suggestion from the card's own position is named in the list", () => {
    const ctx = newCtx();
    ctx.setCardPosition("p-ceo", "planner");
    const b = board(ctx);
    slotButton(b.node, "planner").click();
    assert.ok(findText(pick(b.node, "p-ceo"), "你建議放這裡"));
    assert.ok(!findText(pick(b.node, "p-maker"), "你建議放這裡"));
    slotNode(b.node, "planner").dispatch("keydown", { key: "Escape" });
    assert.ok(!byData(b.node, "data-menu", "planner")[0]);
  });

  await test("P34-1 board: two cards made for the independent review are both suggested at both review places, and the suggested cards come first", () => {
    const ctx = newCtx();
    ctx.setCardPosition("p-rev", "reviewer");
    ctx.setCardPosition("p-maker", "reviewer");
    ctx.setCardPosition("p-ceo", "planner");
    ctx.setCardPosition("p-shared", "legal");
    const order = (key) => {
      const b = board(ctx);
      slotButton(b.node, key).click();
      const ids = walk(b.node).filter((n) => n.getAttribute && n.getAttribute("data-pick")).map((n) => n.getAttribute("data-pick"));
      const marked = ids.filter((id) => findText(pick(b.node, id), "你建議放這裡"));
      b.node.remove();
      return { ids, marked };
    };
    for (const key of ["reviewer1", "reviewer2"]) {
      const o = order(key);
      assert.deepStrictEqual(plain(o.marked.sort()), ["p-maker", "p-rev"], key);
      assert.deepStrictEqual(plain(o.ids.slice(0, 2).sort()), ["p-maker", "p-rev"], key + ": suggested cards are listed first");
    }
    const p = order("planner");
    assert.deepStrictEqual(plain(p.marked), ["p-ceo"]);
    assert.strictEqual(p.ids[0], "p-ceo");
    const e = order("executor");
    assert.deepStrictEqual(plain(e.marked), [], "no card of the executor position here; a staff card is suggested nowhere");
    assert.deepStrictEqual(plain(e.ids), ["p-ceo", "p-maker", "p-rev", "p-shared"], "nothing is suggested: the order is the pool's");
  });

  await test("P32-3 board: a card's own position field is used with nothing kept in the browser", () => {
    const ctx = newCtx();
    const withField = (card, position) => ({ ...card, position });
    const profiles = [withField(CEO, "planner"), withField(MAKER, "qa"), withField(REVIEWER, "reviewer"), withField(SHARED, "legal")];
    const b = board(ctx, { profiles });
    assert.strictEqual(ctx.__ls.size, 0, "no note in this store");
    slotButton(b.node, "reviewer1").click();
    assert.ok(findText(pick(b.node, "p-maker"), "你建議放這裡"), "a qa card from its field");
    assert.ok(findText(pick(b.node, "p-rev"), "你建議放這裡"));
    assert.ok(!findText(pick(b.node, "p-ceo"), "你建議放這裡"));
    assert.ok(chip(b.node, "p-shared").getAttribute("title").includes("幕僚卡"), chip(b.node, "p-shared").getAttribute("title"));
    assert.ok(chip(b.node, "p-maker").getAttribute("title").includes("獨立審查"), "a retired qa field reads as the review it became");
  });

  await test("P32-2 board: each place says what suits it; the pool's small cards say the position in the title", () => {
    const ctx = newCtx();
    const b = board(ctx);
    const head = (key) => textOf(byData(slotNode(b.node, key), "data-ts", "")[0] || walk(slotNode(b.node, key)).find((n) => n.className === "ts-head"));
    assert.ok(head("planner").includes("適合：CEO、PM"));
    assert.ok(head("executor").includes("適合：全端工程師、社群媒體經理、藝術總監"));
    for (const key of ["reviewer1", "reviewer2"]) {
      assert.ok(head(key).includes("適合：獨立審查、另一陣營的全端工程師"), key);
      assert.ok(head(key).includes("要和執行位不同陣營"), key);
    }
    assert.ok(findText(b.node, "審查位可以放獨立審查，或另一陣營的全端工程師的卡"));
    assert.ok(findText(b.node, "審查各一位，第二位審查選填。"));
    ctx.setCardPosition("p-rev", "reviewer");
    ctx.setCardPosition("p-shared", "legal");
    const b2 = board(ctx);
    assert.ok(chip(b2.node, "p-rev").getAttribute("title").includes("你建議放「審查」位"), chip(b2.node, "p-rev").getAttribute("title"));
    assert.ok(chip(b2.node, "p-rev").getAttribute("title").includes("獨立審查"));
    const staff = chip(b2.node, "p-shared").getAttribute("title");
    assert.ok(staff.includes("法務經理") && staff.includes("通常不上任務卡"), staff);
  });

  await test("P32-2 board: the places keep their keys, names and families (the flow format is not touched)", () => {
    const ctx = newCtx();
    assert.deepStrictEqual(plain(ctx.TEAM_SLOTS.map((s) => [s.key, s.label, s.position])), [
      ["planner", "規劃位", "planner"], ["executor", "執行位", "executor"], ["reviewer1", "審查位", "reviewer"], ["reviewer2", "第二位審查", "reviewer"]]);
  });

  await test("board: the list can be searched by name and shows at most 48 cards", () => {
    const ctx = newCtx();
    const many = Array.from({ length: 60 }, (_, i) => mkCard("p-" + i, "卡" + i, "claude", REV("a")));
    const b = board(ctx, { profiles: [...many, REVIEWER] });
    slotButton(b.node, "planner").click();
    assert.strictEqual(byData(b.node, "data-pick", "p-0").length + walk(b.node).filter((n) => n.getAttribute && n.getAttribute("data-pick")).length - 1, 48);
    assert.ok(findText(b.node, "還有 13 張"));
    const search = walk(b.node).find((n) => n.tag === "input" && n.getAttribute("type") === "search");
    search.value = "審查";
    search.dispatch("input", { target: search });
    const picks = walk(b.node).filter((n) => n.getAttribute && n.getAttribute("data-pick"));
    assert.deepStrictEqual(picks.map((n) => n.getAttribute("data-pick")), ["p-rev"]);
  });

  await test("board: a card dropped on a place lands there (drag and drop); dropping something else does nothing", () => {
    const ctx = newCtx();
    const b = board(ctx);
    const li = slotNode(b.node, "planner");
    li.dispatch("dragover");
    li.dispatch("drop", { dataTransfer: { getData: (t) => (t === "text/x-vbear-card" ? "p-ceo" : "") } });
    assert.strictEqual(b.state.slots.planner.profile_id, "p-ceo");
    slotNode(b.node, "executor").dispatch("drop", { dataTransfer: { getData: () => "not-a-card" } });
    assert.strictEqual(b.state.slots.executor, null);
    slotNode(b.node, "executor").dispatch("drop", {});
    assert.strictEqual(b.state.slots.executor, null);
    slotNode(b.node, "executor").dispatch("drop", { dataTransfer: { getData: () => { throw new Error("refused"); } } });
    assert.strictEqual(b.state.slots.executor, null);
    // the tray chips are draggable and carry the card id
    const c = chip(b.node, "p-maker");
    assert.strictEqual(c.getAttribute("draggable"), "true");
    const data = {};
    c.dispatch("dragstart", { dataTransfer: { setData: (t, v) => { data[t] = v; } } });
    assert.strictEqual(data["text/x-vbear-card"], "p-maker");
  });

  await test("board (touch): tap a card, then tap a place — no drag needed", () => {
    const ctx = newCtx();
    const b = board(ctx);
    chip(b.node, "p-rev").click();
    assert.strictEqual(chip(b.node, "p-rev").getAttribute("aria-pressed"), "true");
    assert.ok(findText(b.node, "已拿起「審查員」"));
    assert.ok(slotNode(b.node, "reviewer1").classList.contains("ts-armed"));
    slotButton(b.node, "reviewer1").click();
    assert.strictEqual(b.state.slots.reviewer1.profile_id, "p-rev");
    assert.ok(!findText(b.node, "已拿起"), "the card was put down");
    chip(b.node, "p-rev").click();
    chip(b.node, "p-rev").click();
    assert.strictEqual(chip(b.node, "p-rev").getAttribute("aria-pressed"), "false", "tapping again lets go");
  });

  await test("board: the same family on the review place turns it red at once, with the sentence, and it is still allowed", () => {
    const ctx = newCtx();
    const b = board(ctx);
    putVia(b, "executor", "p-maker");
    putVia(b, "reviewer1", "p-ceo");        // claude reviewing claude
    const rev = slotNode(b.node, "reviewer1");
    assert.strictEqual(rev.getAttribute("data-state"), "problem");
    const problem = byData(rev, "data-slot-problem", "same_family")[0];
    assert.ok(problem);
    assert.ok(findText(problem, "這個位置需要和執行位不同陣營的卡，審查結果才算數"));
    assert.ok(findText(problem, "不算數"));
    assert.ok(findText(problem, "同為 Anthropic（Claude）"));
    assert.ok(rev.classList.contains("ts-bad"));
    assert.strictEqual(b.state.slots.reviewer1.profile_id, "p-ceo", "it was allowed");
    putVia(b, "reviewer1", "p-rev");        // codex reviewing claude
    assert.strictEqual(slotNode(b.node, "reviewer1").getAttribute("data-state"), "filled");
    assert.ok(!byData(b.node, "data-slot-problem", "same_family")[0]);
  });

  await test("board: changing the executor re-judges the review place; a shared card cannot make a counting review", () => {
    const ctx = newCtx();
    const b = board(ctx);
    putVia(b, "reviewer1", "p-rev");
    putVia(b, "executor", "p-maker");
    assert.strictEqual(slotNode(b.node, "reviewer1").getAttribute("data-state"), "filled");
    putVia(b, "executor", "p-rev");         // now codex executes, and the very same codex card reviews
    assert.ok(byData(slotNode(b.node, "reviewer1"), "data-slot-problem", "same_card")[0], "the same card, which is said first (P7 #8)");
    putVia(b, "executor", "p-shared");
    assert.ok(byData(slotNode(b.node, "reviewer1"), "data-slot-problem", "executor_family_unknown")[0]);
    putVia(b, "executor", "p-maker");        // another card than the shared one, so it is the family that is unknown
    putVia(b, "reviewer2", "p-shared");
    assert.ok(byData(slotNode(b.node, "reviewer2"), "data-slot-problem", "reviewer_family_unknown")[0]);
    // the list shows the consequence before the card is chosen
    slotButton(b.node, "reviewer1").click();
    putVia(b, "executor", "p-maker");
    slotButton(b.node, "reviewer1").click();
    assert.ok(findText(pick(b.node, "p-ceo"), "放這裡審查不算數"));
    assert.ok(!findText(pick(b.node, "p-rev"), "放這裡審查不算數"));
  });

  await test("board: a card can be taken off; the draft follows (only ids), and a new board over the same task finds it again", () => {
    const ctx = newCtx();
    const b = board(ctx);
    putVia(b, "planner", "p-ceo");
    putVia(b, "executor", "p-maker");
    const again = ctx.teamBoard({ task: baseTask(), flow: null, profiles: PROFILES, catalog, gitState: "git" });
    assert.strictEqual(again.state.slots.planner.profile_id, "p-ceo");
    assert.strictEqual(again.state.slots.executor.profile_id, "p-maker");
    act(slotNode(b.node, "planner"), "clear").click();
    assert.strictEqual(b.state.slots.planner, null);
    const third = ctx.teamBoard({ task: baseTask(), flow: null, profiles: PROFILES, catalog, gitState: "git" });
    assert.strictEqual(third.state.slots.planner, null);
    assert.strictEqual(third.state.slots.executor.profile_id, "p-maker");
  });

  await test("board: a complete team is created with one POST — planner, executor, one reviewer; the empty second place is not in it", async () => {
    const created = flowView();
    const ctx = newCtx({ "POST /api/flows": () => jsonResponse({ ok: true, flow: created }) });
    const saved = [];
    const b = board(ctx, { onSaved: (f) => saved.push(f) });
    putVia(b, "planner", "p-ceo");
    putVia(b, "executor", "p-maker");
    assert.strictEqual(saveButton(b.node).disabled, true, "still one short");
    putVia(b, "reviewer1", "p-rev");
    assert.strictEqual(saveButton(b.node).disabled, false);
    saveButton(b.node).click();
    await tick();
    assert.strictEqual(posts().length, 1);
    assert.ok(posts()[0].url.endsWith("/api/flows"));
    const body = bodyOf(posts()[0]);
    assert.strictEqual(body.task_id, "task-1");
    assert.strictEqual(body.roles.reviewers.length, 1);
    assert.strictEqual(body.roles.planner.profile_snapshot.revision, REV("1"));
    assert.strictEqual(body.roles.executor.workdir, REPO);
    assert.strictEqual(body.roles.reviewers[0].family, "openai");
    assert.strictEqual(saved.length, 1, "the page is told");
    assert.ok(![...ctx.__ls.keys()].some((k) => k.includes("team.draft.task-1") && ctx.__ls.get(k) !== "null"), "the draft is gone");
  });

  await test("board: two reviews are two entries in order, and a review that does not count is still sent (the record says it plainly)", async () => {
    const ctx = newCtx({ "POST /api/flows": () => jsonResponse({ ok: true, flow: flowView() }) });
    const b = board(ctx);
    putVia(b, "planner", "p-ceo");
    putVia(b, "executor", "p-maker");
    putVia(b, "reviewer1", "p-ceo");
    putVia(b, "reviewer2", "p-rev");
    saveButton(b.node).click();
    await tick();
    const body = bodyOf(posts()[0]);
    assert.deepStrictEqual(body.roles.reviewers.map((r) => r.profile_id), ["p-ceo", "p-rev"]);
  });

  await test("board: the server's refusal is shown on the place it names, not only in a toast", async () => {
    const rows = [
      ["reviewers[0]：角色名稱不合法", "reviewer1"], ["planner：角色名稱不合法", "planner"], ["executor：工作目錄不合法", "executor"],
      ["工作目錄不存在", "executor"], ["session id 格式不符（n- 加 12 碼十六進位）", "executor"], ["reviewers[1]：模型家族不合法", "reviewer2"],
    ];
    for (const [message, key] of rows) {
      const ctx = newCtx({ "POST /api/flows": () => jsonResponse({ error: message }, 400) });
      const b = board(ctx);
      putVia(b, "planner", "p-ceo"); putVia(b, "executor", "p-maker"); putVia(b, "reviewer1", "p-rev"); putVia(b, "reviewer2", "p-rev");
      saveButton(b.node).click();
      await tick();
      const where = byData(b.node, "data-slot-error", key)[0];
      assert.ok(where && findText(where, message), message);
      assert.ok(!byData(b.node, "data-team", "error")[0], "not also at the bottom");
      assert.strictEqual(saveButton(b.node).disabled, false, "can try again");
    }
    const ctx = newCtx({ "POST /api/flows": () => jsonResponse({ error: "這張任務卡已經有流程（一張任務卡對應一個流程）" }, 400) });
    const b = board(ctx);
    putVia(b, "planner", "p-ceo"); putVia(b, "executor", "p-maker"); putVia(b, "reviewer1", "p-rev");
    saveButton(b.node).click();
    await tick();
    assert.ok(findText(byData(b.node, "data-team", "error")[0], "已經有流程"), "a refusal about no place stays under the buttons");
    assert.ok(byData(b.node, "data-slot-error", "planner").length === 0);
    assert.strictEqual(b.state.slots.planner.profile_id, "p-ceo", "the draft is kept after a refusal");
  });

  await test("board (existing flow): shows the saved team, the save stays off until something changes, and saves with set-roles", async () => {
    const after = flowView();
    const ctx = newCtx({ [`POST /api/flows/${FLOW_ID}/roles`]: () => jsonResponse({ ok: true, flow: after }) });
    const b = board(ctx, { flow: flowView() });
    assert.strictEqual(b.state.slots.planner.profile_id, "p-ceo");
    assert.strictEqual(b.state.slots.executor.session_id, "n-0123456789ab");
    assert.strictEqual(saveButton(b.node).textContent.trim(), "儲存隊伍");
    assert.strictEqual(saveButton(b.node).disabled, true);
    assert.ok(findText(b.node, "沒有未儲存的改動"));
    assert.ok(findText(b.node, ctx.TEAM_SAVE_NOTE), "what a save does to the record is said");
    putVia(b, "reviewer1", "p-ceo");
    assert.strictEqual(saveButton(b.node).disabled, false);
    saveButton(b.node).click();
    await tick();
    assert.strictEqual(posts().length, 1);
    assert.ok(posts()[0].url.endsWith(`/api/flows/${FLOW_ID}/roles`));
    const body = bodyOf(posts()[0]);
    assert.deepStrictEqual(Object.keys(body), ["roles"]);
    assert.strictEqual(body.roles.reviewers[0].profile_id, "p-ceo");
    assert.strictEqual(body.roles.executor.session_id, "n-0123456789ab", "the executor keeps its session");
    assert.strictEqual(body.roles.executor.workdir, REPO);
    assert.ok(!("family_label" in body.roles.planner), "view-only fields are not sent back");
    assert.ok(!("independent_of_executor" in body.roles.reviewers[0]));
  });

  await test("board: swapping the executor's card keeps its session and folder", async () => {
    const ctx = newCtx({ [`POST /api/flows/${FLOW_ID}/roles`]: () => jsonResponse({ ok: true, flow: flowView() }) });
    const b = board(ctx, { flow: flowView() });
    putVia(b, "executor", "p-rev");
    assert.strictEqual(b.state.slots.executor.session_id, "n-0123456789ab");
    assert.strictEqual(b.state.slots.executor.workdir, REPO);
    assert.strictEqual(b.state.slots.executor.profile_id, "p-rev");
    // and the review place is judged against the new executor: the very same card, said first (P7 #8)
    assert.ok(byData(slotNode(b.node, "reviewer1"), "data-slot-problem", "same_card")[0]);
  });

  await test("board: a place with a card can start the launch check with the task card's folder; not while changes are unsaved, not for a card that is gone", () => {
    const ctx = newCtx();
    const fl = flowView();
    const b = board(ctx, { flow: fl, profiles: PROFILES.filter((p) => p.id !== "p-rev") });
    const link = act(slotNode(b.node, "executor"), "launch");
    assert.strictEqual(link.getAttribute("href"), "#/workbench?task=task-1&profile=p-maker&launch=1&step=implement");
    assert.ok(!act(slotNode(b.node, "reviewer1"), "launch"), "the card is gone");
    assert.ok(!act(slotNode(b.node, "reviewer2"), "launch"), "an empty place has nothing to launch");
    putVia(b, "reviewer2", "p-shared");
    assert.ok(!act(slotNode(b.node, "executor"), "launch"), "unsaved changes would be lost by leaving");
    const draft = board(newCtx(), {});
    putVia(draft, "planner", "p-ceo");
    assert.strictEqual(act(slotNode(draft.node, "planner"), "launch").getAttribute("href"), "#/workbench?task=task-1&profile=p-ceo&launch=1&step=plan", "a draft survives leaving");
    const hand = flowView();
    hand.roles.planner = { name: "手填", family: "other" };
    assert.ok(!act(slotNode(board(newCtx(), { flow: hand }).node, "planner"), "launch"));
  });

  await test("board: a card that changed after it was put here says so by name and updates only when asked (and saves it)", async () => {
    const changed = PROFILES.map((p) => (p.id === "p-ceo" ? { ...p, name: "CEO 二號", revision: REV("9") } : p));
    const ctx = newCtx({ [`POST /api/flows/${FLOW_ID}/roles`]: () => jsonResponse({ ok: true, flow: flowView() }) });
    const b = board(ctx, { flow: flowView(), profiles: changed });
    const note = byData(slotNode(b.node, "planner"), "data-slot-stale", "changed")[0];
    assert.ok(note);
    assert.ok(findText(note, "CEO 的設定在放上隊伍後改過了 · "), "the name it was put here with");
    assert.ok(findText(note, "更新成最新"));
    assert.ok(!byData(slotNode(b.node, "executor"), "data-slot-stale", "changed")[0], "the others did not change");
    assert.strictEqual(posts().length, 0, "nothing happened by itself");
    assert.strictEqual(b.state.slots.planner.profile_snapshot.revision, REV("1"));
    act(note, "refresh").click();
    await tick();
    assert.strictEqual(posts().length, 1);
    const body = bodyOf(posts()[0]);
    assert.strictEqual(body.roles.planner.profile_snapshot.revision, REV("9"));
    assert.strictEqual(body.roles.planner.name, "CEO 二號");
    assert.strictEqual(body.roles.executor.profile_snapshot.revision, REV("2"), "the other places are as they were");
  });

  await test("board: with unsaved changes pending, 'update' only changes the place and does not save the rest by surprise", async () => {
    const changed = PROFILES.map((p) => (p.id === "p-ceo" ? { ...p, revision: REV("9") } : p));
    const ctx = newCtx();
    const b = board(ctx, { flow: flowView(), profiles: changed });
    putVia(b, "reviewer1", "p-shared");
    act(byData(slotNode(b.node, "planner"), "data-slot-stale", "changed")[0], "refresh").click();
    await tick();
    assert.strictEqual(posts().length, 0);
    assert.strictEqual(b.state.slots.planner.profile_snapshot.revision, REV("9"));
    assert.ok(b.state.dirty);
  });

  await test("board: a card that is gone, and a hand-written role, are each said plainly; neither is called stale", () => {
    const ctx = newCtx();
    const fl = flowView();
    fl.roles.reviewers = [{ name: "手填", family: "google", family_label: "Google" }];
    const b = board(ctx, { flow: fl, profiles: PROFILES.filter((p) => p.id !== "p-maker") });
    assert.ok(findText(byData(slotNode(b.node, "executor"), "data-slot-stale", "gone")[0], "已經不在角色卡池了"));
    assert.ok(findText(byData(slotNode(b.node, "reviewer1"), "data-slot-stale", "manual")[0], "手動填寫的角色"));
    assert.ok(!act(slotNode(b.node, "executor"), "refresh"), "nothing to update from");
    assert.ok(byData(slotNode(b.node, "reviewer1"), "data-slot-problem", "reviewer_family_unknown").length === 0, "google vs anthropic counts");
  });

  await test("board: a folder with no version history says so beside the review places, in the sentence; one with git does not", () => {
    const ctx = newCtx();
    const none = board(ctx, { gitState: "nogit" });
    const note = byData(none.node, "data-team", "nogit")[0];
    assert.ok(note && findText(note, ctx.NO_GIT_NOTE) && findText(note, "沒有版本紀錄"));
    assert.ok(findText(note, "隊伍的審查結果要綁定版本編號"));
    main.replaceChildren();
    const yes = board(ctx, { gitState: "git" });
    assert.ok(!byData(yes.node, "data-team", "nogit")[0]);
    main.replaceChildren();
    const unknown = board(ctx, { gitState: null });
    assert.ok(!byData(unknown.node, "data-team", "nogit")[0], "not knowing is not said as 'no history'");
  });

  await test("board: no cards in the pool — the tray says so and points to the pool page; the places still open a list that says it is empty", () => {
    const ctx = newCtx();
    const b = board(ctx, { profiles: [] });
    assert.ok(findText(b.node, "角色卡池是空的"));
    assert.ok(walk(b.node).some((n) => n.tag === "a" && n.getAttribute("href") === "#/team"));
    slotButton(b.node, "planner").click();
    assert.ok(findText(byData(b.node, "data-menu", "planner")[0], "角色卡池是空的"));
  });

  await test("board: the keyboard path — every place is a button that opens its list, and the labels say what Enter does", () => {
    const ctx = newCtx();
    const b = board(ctx);
    for (const key of ["planner", "executor", "reviewer1", "reviewer2"]) {
      const btn = slotButton(b.node, key);
      assert.strictEqual(btn.tag, "button");
      assert.strictEqual(btn.getAttribute("type"), "button");
      assert.ok(/Enter/.test(btn.getAttribute("aria-label")), key);
      assert.strictEqual(btn.getAttribute("aria-expanded"), "false");
    }
    putVia(b, "planner", "p-ceo");
    assert.ok(slotButton(b.node, "planner").getAttribute("aria-label").includes("CEO"));
    assert.ok(lastFocus === slotButton(b.node, "planner"), "the focus returns to the place that was filled");
  });

  // ---- the section of a task card --------------------------------------------------------------------------------
  await test("teamSection (no flow): loads cards, the flow list and the folder, and shows the draft board", async () => {
    const ctx = newCtx();
    const node = ctx.teamSection(baseTask(), {});
    main.append(node);
    assert.ok(findText(node, "讀取隊伍"));
    await tick(8);
    assert.ok(byData(node, "data-team", "board")[0], "the board");
    assert.ok(!byData(node, "data-team", "next")[0], "no flow, no next steps");
    assert.ok(!byData(node, "data-team", "nogit")[0]);
    assert.ok(fetchCalls.some((c) => c.url === `/api/folders/inspect?path=${encodeURIComponent(REPO)}`));
  });

  await test("teamSection (no version history): the folder's answer reaches the review places", async () => {
    const ctx = newCtx();
    const node = ctx.teamSection(baseTask({ workdir: PLAIN }), {});
    main.append(node);
    await tick(8);
    assert.ok(byData(node, "data-team", "nogit")[0]);
  });

  await test("teamSection (flow): next steps above the board, with the flow's phase and a way to open it", async () => {
    const ctx = newCtx({ "GET /api/flows": () => jsonResponse({ ok: true, flows: [flowView()], families: [] }) });
    const node = ctx.teamSection(baseTask(), {});
    main.append(node);
    await tick(8);
    const next = byData(node, "data-team", "next")[0];
    assert.ok(next && findText(next, "輪到工匠"));
    assert.ok(walk(next).some((n) => n.tag === "a" && n.getAttribute("href") === `#/flows/${FLOW_ID}`));
    assert.ok(byData(node, "data-team", "board")[0]);
    // a flow of another task is not this task's team
    main.replaceChildren();
    const other = newCtx({ "GET /api/flows": () => jsonResponse({ ok: true, flows: [flowView({ task_id: "task-9" })], families: [] }) });
    const n2 = other.teamSection(baseTask(), {});
    main.append(n2);
    await tick(8);
    assert.ok(!byData(n2, "data-team", "next")[0]);
  });

  await test("teamSection: what the caller already has is used once; a failed read says so instead of showing an empty team as fact", async () => {
    const ctx = newCtx({ "GET /api/flows": () => jsonResponse({ error: "boom" }, 500) });
    const node = ctx.teamSection(baseTask(), { profiles: PROFILES, catalog });
    main.append(node);
    await tick(8);
    assert.ok(findText(node, "讀不到流程"), "the failure is said");
    assert.ok(!fetchCalls.some((c) => c.url === "/api/agent-profiles"), "profiles were handed in");
    const hidden = newCtx();
    const n2 = hidden.teamSection(baseTask(), { flow: flowView(), hideOpen: true, profiles: PROFILES, catalog });
    main.append(n2);
    await tick(8);
    assert.ok(!walk(byData(n2, "data-team", "next")[0]).some((n) => n.tag === "a" && (n.getAttribute("href") || "").startsWith("#/flows/")), "no link to the page it is already on");
  });

  // ---- 放上任務卡 ---------------------------------------------------------------------------------------------------
  const dlg = () => body.children.find((c) => c !== main && c.getAttribute && c.getAttribute("role") === "dialog");
  async function placeFlow(ctx, card, taskId) {
    const handle = ctx.openPlaceDialog(card, { profiles: PROFILES, taskId });
    await tick(6);
    return handle;
  }

  await test("place dialog: lists only unfinished task cards; picking a place shows what the card would do there", async () => {
    const tasks = [baseTask(), baseTask({ id: "task-2", title: "Closed", status: "closed" }), baseTask({ id: "task-3", title: "Handed", status: "handed_off" }),
      baseTask({ id: "task-4", title: "No folder", workdir: undefined })];
    const ctx = newCtx({ "GET /api/tasks": () => jsonResponse({ ok: true, tasks }) });
    await placeFlow(ctx, CEO);
    const d = dlg();
    assert.ok(d);
    assert.deepStrictEqual(plain(byData(d, "data-place-task", "task-1").concat(byData(d, "data-place-task", "task-4")).map((n) => n.getAttribute("data-place-task"))), ["task-1", "task-4"]);
    assert.strictEqual(byData(d, "data-place-task", "task-2").length, 0);
    assert.strictEqual(byData(d, "data-place-task", "task-3").length, 0);
    assert.ok(findText(byData(d, "data-place-task", "task-4")[0], "還沒有資料夾"));
    assert.strictEqual(act(d, "place").disabled, true);
    byData(d, "data-place-task", "task-1")[0].click();
    assert.ok(findText(dlg(), "還沒有隊伍，會先放進草稿"));
    const slots = byData(dlg(), "data-place-slot", "planner").length + byData(dlg(), "data-place-slot", "reviewer2").length;
    assert.strictEqual(slots, 2);
    assert.strictEqual(act(dlg(), "place").disabled, true, "a place is needed too");
  });

  await test("P32-2 place dialog: a card made for a place of the task card has that place chosen once the task is picked", async () => {
    const cases = [["planner", "planner"], ["executor", "executor"], ["social", "executor"], ["art", "executor"], ["reviewer", "reviewer1"]];
    for (const [position, want] of cases) {
      const ctx = newCtx();
      ctx.setCardPosition("p-ceo", position);
      await placeFlow(ctx, CEO);
      byData(dlg(), "data-place-task", "task-1")[0].click();
      const on = byData(dlg(), "data-place-slot", want)[0];
      assert.strictEqual(on.getAttribute("aria-pressed"), "true", position);
      assert.strictEqual(walk(dlg()).filter((n) => n.getAttribute && n.getAttribute("data-place-slot") && n.getAttribute("aria-pressed") === "true").length, 1, position);
      assert.strictEqual(act(dlg(), "place").disabled, false, position + ": ready to put");
      assert.ok(!byData(dlg(), "data-place", "staff-note")[0]);
    }
  });

  await test("P34-1 place dialog: a card with a retired qa field is preselected to the review place it became; a PM card preselects nothing", async () => {
    const ctx = newCtx();
    await placeFlow(ctx, { ...CEO, position: "qa" });
    byData(dlg(), "data-place-task", "task-1")[0].click();
    assert.strictEqual(byData(dlg(), "data-place-slot", "reviewer1")[0].getAttribute("aria-pressed"), "true");
    dlg().dispatch("keydown", { key: "Escape" });
    await placeFlow(ctx, { ...CEO, position: "pm" });
    byData(dlg(), "data-place-task", "task-1")[0].click();
    assert.strictEqual(walk(dlg()).filter((n) => n.getAttribute && n.getAttribute("data-place-slot") && n.getAttribute("aria-pressed") === "true").length, 0);
    assert.ok(byData(dlg(), "data-place", "staff-note")[0], "and says it is a staff card");
  });

  await test("P32-2 place dialog: a review card is preselected to the empty review place; a preselected place is still only put when the person presses the button", async () => {
    const withFirst = flowView();
    const ctx = newCtx({
      "GET /api/flows": () => jsonResponse({ ok: true, flows: [withFirst], families: [] }),
      [`POST /api/flows/${FLOW_ID}/roles`]: () => jsonResponse({ ok: true, flow: withFirst }),
    });
    ctx.setCardPosition("p-shared", "reviewer");
    ctx.setCardPosition("p-ceo", "reviewer");
    await placeFlow(ctx, REVIEWER, "task-1");
    assert.strictEqual(byData(dlg(), "data-place-slot", "reviewer1")[0].getAttribute("aria-pressed"), "false", "a card with no position preselects nothing");
    dlg().dispatch("keydown", { key: "Escape" });
    ctx.setCardPosition("p-rev", "reviewer");
    await placeFlow(ctx, REVIEWER, "task-1");
    assert.strictEqual(byData(dlg(), "data-place-slot", "reviewer2")[0].getAttribute("aria-pressed"), "true", "reviewer1 holds a card already: the empty one is chosen");
    assert.strictEqual(posts().length, 0, "nothing was written by choosing");
    // both review places full: the first is chosen and the row says it will be replaced
    dlg().dispatch("keydown", { key: "Escape" });
    const full = flowView({ roles: { ...flowView().roles, reviewers: [flowView().roles.reviewers[0], { ...flowView().roles.reviewers[0], name: "二審" }] } });
    const ctx2 = newCtx({ "GET /api/flows": () => jsonResponse({ ok: true, flows: [full], families: [] }) });
    ctx2.setCardPosition("p-rev", "reviewer");
    await placeFlow(ctx2, REVIEWER, "task-1");
    const first = byData(dlg(), "data-place-slot", "reviewer1")[0];
    assert.strictEqual(first.getAttribute("aria-pressed"), "true");
    assert.ok(findText(first, "會換成這張"));
  });

  await test("P32-3 place dialog: the card's own position field chooses the place and a staff card gets the note", async () => {
    const ctx = newCtx();
    await placeFlow(ctx, { ...CEO, position: "executor" });
    byData(dlg(), "data-place-task", "task-1")[0].click();
    assert.strictEqual(byData(dlg(), "data-place-slot", "executor")[0].getAttribute("aria-pressed"), "true");
    dlg().dispatch("keydown", { key: "Escape" });
    await placeFlow(ctx, { ...CEO, position: "legal" });
    byData(dlg(), "data-place-task", "task-1")[0].click();
    assert.ok(byData(dlg(), "data-place", "staff-note")[0]);
  });

  await test("P32-2 place dialog: a staff card says it is not for the task card and preselects nothing; a card with no position says nothing extra", async () => {
    for (const position of ["pm", "legal", "accountant"]) {
      const ctx = newCtx();
      ctx.setCardPosition("p-ceo", position);
      await placeFlow(ctx, CEO);
      byData(dlg(), "data-place-task", "task-1")[0].click();
      const note = byData(dlg(), "data-place", "staff-note")[0];
      assert.ok(note, position);
      assert.ok(findText(note, position === "pm" ? "這是幕僚卡，通常不上任務卡；沒有 CEO 時可以放規劃位" : "這是幕僚卡，不佔任務卡的位置，通常單獨出發"), position);
      assert.strictEqual(walk(dlg()).filter((n) => n.getAttribute && n.getAttribute("data-place-slot") && n.getAttribute("aria-pressed") === "true").length, 0, position);
      assert.strictEqual(act(dlg(), "place").disabled, true, position);
      dlg().dispatch("keydown", { key: "Escape" });
    }
    const none = newCtx();
    await placeFlow(none, CEO);
    byData(dlg(), "data-place-task", "task-1")[0].click();
    assert.ok(!byData(dlg(), "data-place", "staff-note")[0]);
  });

  await test("place dialog (task without a team): the card goes into the draft and the page stays; the dialog says where and offers the task card", async () => {
    const ctx = newCtx();
    await placeFlow(ctx, CEO);
    byData(dlg(), "data-place-task", "task-1")[0].click();
    byData(dlg(), "data-place-slot", "planner")[0].click();
    assert.strictEqual(act(dlg(), "place").disabled, false);
    act(dlg(), "place").click();
    await tick();
    assert.strictEqual(posts().length, 0, "nothing is written to the flow yet");
    assert.strictEqual(ctx.location.hash, "", "P12 C7: the page did not move");
    assert.strictEqual(ctx.teamDraftRead("task-1", PROFILES, REPO).planner.profile_id, "p-ceo");
    assert.ok(dlg(), "the dialog stays, with the answer in it");
    assert.ok(findText(byData(dlg(), "data-place", "done")[0], "還要放其他位置嗎？"));
  });

  await test("place dialog (task with a team): saved at once with set-roles, and the note about the record is shown first", async () => {
    const ctx = newCtx({
      "GET /api/flows": () => jsonResponse({ ok: true, flows: [flowView()], families: [] }),
      [`POST /api/flows/${FLOW_ID}/roles`]: () => jsonResponse({ ok: true, flow: flowView() }),
    });
    await placeFlow(ctx, REVIEWER);
    byData(dlg(), "data-place-task", "task-1")[0].click();
    assert.ok(findText(dlg(), "已有隊伍，放上去會直接儲存"));
    assert.ok(findText(dlg(), ctx.TEAM_SAVE_NOTE));
    byData(dlg(), "data-place-slot", "reviewer2")[0].click();
    act(dlg(), "place").click();
    await tick();
    assert.strictEqual(posts().length, 1);
    const roles = bodyOf(posts()[0]).roles;
    assert.strictEqual(roles.reviewers.length, 2);
    assert.strictEqual(roles.reviewers[1].profile_id, "p-rev");
    assert.strictEqual(roles.executor.session_id, "n-0123456789ab");
    assert.strictEqual(ctx.location.hash, "", "P12 C7: the page did not move");
    assert.ok(findText(byData(dlg(), "data-place", "done")[0], "已放到「"), "and it says where");
  });

  await test("place dialog: a review place that would not count shows it before the click; the server's refusal appears inside the dialog", async () => {
    const ctx = newCtx({
      "GET /api/flows": () => jsonResponse({ ok: true, flows: [flowView()], families: [] }),
      [`POST /api/flows/${FLOW_ID}/roles`]: () => jsonResponse({ error: "executor：工作目錄不合法" }, 400),
    });
    await placeFlow(ctx, MAKER, "task-1");
    assert.ok(byData(dlg(), "data-place", "slots")[0], "the task was preselected");
    const rev = byData(dlg(), "data-place-slot", "reviewer1")[0];
    assert.ok(findText(rev, "同一張卡不能審查自己"), "the executor's own card on its review place (P7 #8)");
    assert.ok(!findText(byData(dlg(), "data-place-slot", "planner")[0], "審查結果才算數"));
    byData(dlg(), "data-place-slot", "executor")[0].click();
    act(dlg(), "place").click();
    await tick();
    assert.ok(dlg(), "still open");
    assert.ok(findText(byData(dlg(), "data-place", "error")[0], "工作目錄不合法"));
    assert.strictEqual(ctx.location.hash, "", "it did not leave");
  });

  await test("place dialog: no unfinished task cards — says so; a failed read says why", async () => {
    const ctx = newCtx({ "GET /api/tasks": () => jsonResponse({ ok: true, tasks: [] }) });
    await placeFlow(ctx, CEO);
    assert.ok(findText(dlg(), "沒有未結案的任務卡"));
    dlg().dispatch("keydown", { key: "Escape" });
    const bad = newCtx({ "GET /api/tasks": () => jsonResponse({ error: "down" }, 500) });
    await placeFlow(bad, CEO);
    assert.ok(findText(dlg(), "讀不到任務卡"));
  });

  // ---- the card, the card front -----------------------------------------------------------------------------------
  await test("role card: 放上任務卡 shows only when the page gives a handler, and calls it with the card", () => {
    const ctx = newCtx();
    const placed = [];
    const withIt = ctx.profileCard(CEO, { catalog, handlers: { place: (p) => placed.push(p.id) } });
    const btn = byData(withIt.node, "data-pcard", "place")[0];
    assert.ok(btn && btn.textContent.trim() === "放上任務卡");
    btn.click();
    assert.deepStrictEqual(placed, ["p-ceo"]);
    assert.strictEqual(byData(ctx.profileCard(CEO, { catalog, handlers: {} }).node, "data-pcard", "place").length, 0);
    assert.strictEqual(byData(ctx.profileCard(CEO, { catalog }).node, "data-pcard", "place").length, 0);
  });

  await test("task card front: the team's small heads and the next step when there is a flow; an invitation when there is none; nothing claimed when unknown", () => {
    const ctx = newCtx();
    const withFlow = ctx.taskFrontCard(baseTask(), { flows: [flowView()] });
    const team = byData(withFlow, "data-tf", "team")[0];
    assert.ok(team);
    assert.strictEqual(byData(team, "data-position", "規劃").length + byData(team, "data-position", "執行").length + byData(team, "data-position", "審查1").length, 3);
    assert.ok(findText(byData(team, "data-tf", "next")[0], "下一步：執行者實作（輪到工匠）"));
    const none = ctx.taskFrontCard(baseTask(), { flows: [] });
    assert.ok(findText(byData(none, "data-tf", "team")[0], "還沒有隊伍"));
    assert.ok(walk(none).some((n) => n.tag === "a" && n.getAttribute("href") === "#/workbench?task=task-1"));
    const unknown = ctx.taskFrontCard(baseTask(), {});
    assert.strictEqual(byData(unknown, "data-tf", "team").length, 0, "flows not read: nothing is said");
    const other = ctx.taskFrontCard(baseTask(), { flows: [flowView({ task_id: "task-9" })] });
    assert.ok(findText(byData(other, "data-tf", "team")[0], "還沒有隊伍"));
    const odd = ctx.taskFrontCard(baseTask(), { flows: [flowView({ phase: { key: "zzz", label: "z", reason: "" } })] });
    assert.strictEqual(byData(odd, "data-tf", "next").length, 0, "an unknown phase gives no next step");
  });

  await test("flow page detail: the tool of a role is read from its card, and a hand-written role says it has none", () => {
    const ctx = newCtx();
    assert.ok(ctx.flowRoleToolText(flowView().roles.planner).startsWith("Claude Code（放上隊伍時的角色卡：CEO）"));
    assert.ok(ctx.flowRoleToolText(flowView().roles.reviewers[0]).startsWith("Codex CLI"));
    assert.strictEqual(ctx.flowRoleToolText({ name: "x", family: "other" }), "未提供（流程記錄沒有這個欄位）");
    assert.strictEqual(ctx.flowRoleToolText(null), "未提供（流程記錄沒有這個欄位）");
    assert.strictEqual(ctx.flowRoleToolText({ profile_snapshot: { tool: "weird", name: "x" } }), "未提供（流程記錄沒有這個欄位）");
  });

  await test("teamAvatars: one small head per role, named; none without roles", () => {
    const ctx = newCtx();
    const node = ctx.teamAvatars(flowView());
    assert.strictEqual(walk(node).filter((n) => n.getAttribute && n.getAttribute("data-position")).length, 3);
    assert.ok(findText(node, "規劃・CEO") && findText(node, "審查1・審查員"));
    assert.strictEqual(ctx.teamAvatars(null), null);
    assert.strictEqual(ctx.teamAvatars({}), null);
  });

  // ---- the source and the css -------------------------------------------------------------------------------------
  const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const block = app.slice(app.indexOf("// ---------- team slots: put role cards"), app.indexOf("// ---------- task cards are folders"));
  await test("source: the team block builds with el(), no innerHTML, no emoji, no outside resource, no stats or rarity", () => {
    assert.ok(block.length > 8000, "found the block");
    assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(block));
    assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(block.replace(/[＋…]/g, "")), "no emoji");
    assert.ok(!/https?:\/\//.test(block));
    assert.ok(!/\bfetch\(|XMLHttpRequest|WebSocket|importScripts|window\.open\(/.test(block));
    assert.ok(!/稀有|等級|星數|抽卡|攻擊力|防禦力|傷害|經驗值/.test(block), "no stats, levels, rarity or draws");
    for (const bad of ["Profile", "AgentRole", "Agent Builder", "Permission Intents", "equipped skills"]) assert.ok(!block.includes(bad), bad);
  });

  await test("source: the only writes are the flow and its roles; the only navigation is to a task card by id", () => {
    const posted = [...new Set((block.match(/api\.post\(([^,]+),/g) || []).map((x) => x.replace(/\s+/g, " ")))].sort();
    // P10 F2: the next-step box's 「核准計畫」 writes the one manual event the form at the bottom of the flow page writes
    // (after its own confirmation); no other kind is written from here
    assert.deepStrictEqual(posted, ["api.post(\"/api/flows\",", "api.post(`/api/flows/${encodeURIComponent(flow.id)}/events`,", "api.post(`/api/flows/${encodeURIComponent(flow.id)}/roles`,"]);
    assert.deepStrictEqual([...new Set(block.match(/flowEventBody\("[a-z_]+"/g))], ['flowEventBody("plan_approved"']);
    const hashes = block.match(/location\.hash = [^;]+;/g) || [];
    assert.ok(hashes.every((h) => h === "location.hash = `#/workbench?task=${encodeURIComponent(t.id)}`;"), hashes.join("|"));
    // P12 C7: the place dialog no longer moves the page by itself; its only way out is a link the person presses
    const links = block.match(/href: `#\/workbench\?task=\$\{encodeURIComponent\(d\.taskId\)\}`/g) || [];
    assert.strictEqual(links.length, 1);
    assert.ok(!/api\.post\([^)]*(executor|dispatch|review|automation|accept)/.test(block), "nothing is started or sent from the team board");
  });

  await test("source: the honesty rules — nothing says safe or restricted; a review that does not count says so; the slot text is the design's", () => {
    assert.ok(!/(安全|已限制|已擋住)/.test(block.replace(/不代表[^"]*/g, "")));
    assert.ok(block.includes("這個位置需要和執行位不同陣營的卡，審查結果才算數"));
    assert.ok(block.includes("可能不再算數"));
    assert.ok(block.includes("更新成最新"));
    assert.ok(block.includes("在放上隊伍後改過了"));
  });

  await test("CSS: the places, the tray, the next steps and the problem line are styled; one column on a phone; the red is not the only cue", () => {
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
    for (const sel of [".team-slots", ".team-slot", ".ts-vacant", ".ts-bad", ".ts-problem", ".ts-menu", ".ts-pick", ".ts-chip", ".ns-list", ".ns-now", ".team-avatars", ".tf-team"]) {
      assert.ok(css.includes(sel + " {") || css.includes(sel + ",") || css.includes(sel + "."), sel);
    }
    assert.ok(/\.team-slot\.ts-vacant \{[^}]*border-style: dashed/.test(css), "empty places are dashed");
    assert.ok(/\.team-slot\.ts-bad \{[^}]*border-left-width: 6px/.test(css), "a bad place also has a thick edge, not only a colour");
    assert.ok(/@media \(max-width: 720px\)\s*\{\s*\.team-slots \{ grid-template-columns: 1fr;/.test(css));
    assert.ok(!/url\(\s*["']?https?:/.test(css));
    const teamCss = css.slice(css.indexOf("/* ---- team slots and next steps"));
    assert.ok(!/#da251d|--vn-red/i.test(teamCss), "the red of 'your turn' is not used here");
  });

  // ---- P20: Antigravity (AGY) cards in the team places ---------------------------------------------------------------
  const AGY = mkCard("p-agy", "AGY 審查員", "agy", REV("5"));
  const AGY2 = mkCard("p-agy2", "AGY 二號", "agy", REV("6"));
  const spriteStyle = (root) => { const n = walk(root).find((x) => x.getAttribute && /box-shadow/.test(x.getAttribute("style") || "")); return n ? n.getAttribute("style") : ""; };
  const GOOGLE_HAND = { name: "手填的 Gemini", family: "google" };

  await test("P20 roleFromCard: an AGY card becomes a role of the Google family with its snapshot; a hand-written Google role is not read back as AGY", () => {
    const role = plain(pure.roleFromCard(AGY));
    assert.deepStrictEqual(role, { name: "AGY 審查員", family: "google", profile_id: "p-agy",
      profile_snapshot: { name: "AGY 審查員", tool: "agy", model_id: "", revision: REV("5") } });
    assert.strictEqual(pure.teamCardFamily(AGY), "google");
    assert.strictEqual(pure.teamCardFamily(role), "google");
    assert.strictEqual(pure.teamCardTool(role), "agy", "a role filled from the card says its tool in its snapshot");
    assert.strictEqual(pure.teamCardTool({ family: "google" }), "", "a Google role written by hand is not an AGY card");
    assert.strictEqual(pure.teamCardTool({ family: "google", name: "x" }), "");
  });

  await test("P20 slotProblem: an AGY card in a review place — fine against Claude or Codex, red against a Google executor or another AGY card", () => {
    const claude = { model: { tool: "claude" } }, codex = { model: { tool: "codex" } }, agy = { model: { tool: "agy" } };
    const rows = [
      ["reviewer1", agy, claude, null],
      ["reviewer1", agy, codex, null],
      ["reviewer2", agy, claude, null],
      ["reviewer1", agy, GOOGLE_HAND, "same_family"],
      ["reviewer1", agy, agy, "same_family"],
      ["reviewer1", claude, agy, null],
      ["reviewer1", codex, agy, null],
      ["reviewer1", { family: "google" }, agy, "same_family"],
      ["planner", agy, claude, null],
      ["executor", agy, claude, null],
    ];
    for (const [slot, card, executor, want] of rows) {
      const got = pure.slotProblem(slot, card, { executor });
      assert.strictEqual(got ? got.code : null, want, `${slot} ${JSON.stringify(card)} vs ${JSON.stringify(executor)}`);
    }
    const red = pure.slotProblem("reviewer1", agy, { executor: GOOGLE_HAND });
    assert.strictEqual(red.text, "這個位置需要和執行位不同陣營的卡，審查結果才算數");
    assert.ok(red.why.includes("Google（Gemini）"), red.why);
    assert.strictEqual(pure.slotProblem("reviewer1", agy, { executor: { ...AGY2, profile_id: "p-agy2", model: { tool: "agy" } } }).code, "same_family");
    // the very same card in both places is still the first thing said
    assert.strictEqual(pure.slotProblem("reviewer1", pure.roleFromCard(AGY), { executor: pure.roleFromCard(AGY) }).code, "same_card");
  });

  await test("P20 board: an AGY review place beside a Claude executor shows no red; beside a hand-written Google executor it does, in the existing words", () => {
    const profiles = [...PROFILES, AGY];
    const ok = board(newCtx(), { profiles });
    putVia(ok, "executor", "p-maker");
    putVia(ok, "reviewer1", "p-agy");
    assert.strictEqual(byData(slotNode(ok.node, "reviewer1"), "data-slot-problem", "same_family").length, 0);
    assert.strictEqual(byData(ok.node, "data-slot-problem", "same_family").length, 0);
    assert.strictEqual(ok.state.slots.reviewer1.family, "google");
    assert.strictEqual(ok.state.slots.reviewer1.profile_snapshot.tool, "agy");
    const fl = flowView();
    fl.roles.executor = { ...fl.roles.executor, ...GOOGLE_HAND, profile_id: undefined, profile_snapshot: undefined };
    delete fl.roles.executor.profile_id; delete fl.roles.executor.profile_snapshot;
    const red = board(newCtx(), { flow: fl, profiles });
    putVia(red, "reviewer2", "p-agy");
    const problem = byData(slotNode(red.node, "reviewer2"), "data-slot-problem", "same_family")[0];
    assert.ok(problem, "red beside a Google executor");
    assert.ok(findText(problem, "不算數"));
    assert.ok(findText(problem, "這個位置需要和執行位不同陣營的卡，審查結果才算數"));
    assert.ok(findText(problem, "Google（Gemini）"));
  });

  await test("P20 board: the menu warns an AGY card before it is put beside a Google executor, and not beside a Claude one", () => {
    const profiles = [...PROFILES, AGY];
    const claudeExec = board(newCtx(), { flow: flowView(), profiles });
    slotButton(claudeExec.node, "reviewer2").click();
    assert.ok(pick(claudeExec.node, "p-agy"));
    assert.ok(!findText(pick(claudeExec.node, "p-agy"), "放這裡審查不算數"));
    const fl = flowView();
    fl.roles.executor = { name: "手填", family: "google", workdir: REPO };
    const googleExec = board(newCtx(), { flow: fl, profiles });
    slotButton(googleExec.node, "reviewer2").click();
    assert.ok(findText(pick(googleExec.node, "p-agy"), "放這裡審查不算數"));
  });

  await test("P20 board: an AGY card is drawn as the fox in the Google colours, and its place says AGY and Google", () => {
    const profiles = [...PROFILES, AGY];
    const b = board(newCtx(), { profiles });
    putVia(b, "reviewer1", "p-agy");
    const node = slotNode(b.node, "reviewer1");
    assert.strictEqual(spriteStyle(byData(node, "data-ts", "name")[0].parentNode.parentNode), spriteStyle(newCtx().officeSprite("fox", "google", 3)));
    assert.ok(findText(node, "AGY"), "the short name");
    assert.ok(findText(node, "Google（Gemini）"), "the family");
    const chipNode = chip(b.node, "p-agy");
    assert.strictEqual(chipNode.getAttribute("data-camp"), "google");
    assert.ok(findText(chipNode, "AGY"));
  });

  await test("P20 board: nothing offers to launch an AGY card — no 出發 on its place, no 讓 … 出發 in the next steps", () => {
    const profiles = [...PROFILES, AGY];
    const fl = flowView();
    fl.roles.executor = { name: "AGY 審查員", family: "google", workdir: REPO, session_id: "n-0123456789ab", profile_id: "p-agy",
      profile_snapshot: { name: "AGY 審查員", tool: "agy", model_id: "", revision: REV("5") } };
    const b = board(newCtx(), { flow: fl, profiles });
    assert.ok(!act(slotNode(b.node, "executor"), "launch"), "an AGY place has no launch link");
    assert.ok(act(slotNode(b.node, "planner"), "launch"), "a Claude place still has one");
    const ctx = newCtx();
    const act1 = plain(ctx.nextStepAction({ ...fl, phase: { key: "implementing", label: "實作中", reason: "" }, automation: { mode: "manual" } }, { profiles }));
    assert.strictEqual(act1.step, "implement");
    assert.deepStrictEqual(act1.launches, [], "the executor is an AGY card: nothing to start");
    assert.ok(act1.note.includes("在終端裡完成這一步後，回到這裡記錄"), "the manual way is still said");
    const claudeFlow = plain(ctx.nextStepAction({ ...flowView(), phase: { key: "implementing", label: "實作中", reason: "" } }, { profiles }));
    assert.deepStrictEqual(claudeFlow.launches.map((l) => l.profile_id), ["p-maker"]);
    const reviewFlow = flowView();
    reviewFlow.roles.reviewers = [reviewFlow.roles.reviewers[0], { name: "AGY 審查員", family: "google", profile_id: "p-agy",
      profile_snapshot: { name: "AGY 審查員", tool: "agy", model_id: "", revision: REV("5") } }];
    const review = plain(ctx.nextStepAction({ ...reviewFlow, phase: { key: "in_review", label: "審查中", reason: "" } }, { profiles }));
    assert.deepStrictEqual(review.launches.map((l) => l.profile_id), ["p-rev"], "the Codex reviewer stays, the AGY one is left out");
  });

  await test("P20 board: saving a team with an AGY card sends the Google family and the AGY snapshot", async () => {
    const ctx = newCtx({ "POST /api/flows": () => jsonResponse({ ok: true, flow: flowView() }) });
    const b = board(ctx, { profiles: [...PROFILES, AGY] });
    putVia(b, "planner", "p-ceo");
    putVia(b, "executor", "p-maker");
    putVia(b, "reviewer1", "p-agy");
    saveButton(b.node).click();
    await tick();
    const sent = bodyOf(posts()[0]);
    assert.strictEqual(sent.roles.reviewers[0].family, "google");
    assert.deepStrictEqual(sent.roles.reviewers[0].profile_snapshot, { name: "AGY 審查員", tool: "agy", model_id: "", revision: REV("5") });
  });

  await test("P20 flow view: a role filled from an AGY card says its tool in the camp's name", () => {
    const ctx = newCtx();
    const role = { name: "AGY 審查員", family: "google", profile_id: "p-agy", profile_snapshot: { name: "AGY 審查員", tool: "agy", model_id: "", revision: REV("5") } };
    assert.strictEqual(ctx.flowRoleToolText(role), "Antigravity（AGY）（放上隊伍時的角色卡：AGY 審查員）");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL TEAM SLOTS FRONTEND TESTS PASSED");
})();
