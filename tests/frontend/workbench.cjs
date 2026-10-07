// Tests the Phase B1-B4 Unified Three-Column Workbench, Task Card MVP,
// Status Provenance, and G/P/A/T Read-Only Foundation.
// Run: node tests/frontend/workbench.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const appSource = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const styleSource = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");

// ---------------------------------------------------------------------------
// A small but real synthetic DOM: actual parent/child tree, actual
// classList/attribute/id state, and a real global.document.getElementById
// that looks nodes up by id instead of fabricating a disconnected stub. This
// is what lets the tests below mount the real viewWorkbench() and assert on
// its actual output, instead of grepping app.js's source text (the previous
// version of this file did the latter, which is how the missing
// `shell.append(leftCol, centerCol, rightCol)` call — an empty, unusable
// workbench — went undetected: nothing here ever rendered the view).
// ---------------------------------------------------------------------------

const idRegistry = new Map();

class SyntheticNode {
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
    this.disabled = false;
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
  get textContent() {
    if (this.tag === "#text") return this._text || "";
    return this.children.map((c) => (c instanceof SyntheticNode ? c.textContent : String(c))).join("");
  }
  set textContent(v) {
    this.replaceChildren();
    if (this.tag !== "#text" && v !== "") this.append(new SyntheticNode("#text").withText(String(v)));
    else this._text = String(v);
  }
  withText(t) { this._text = t; return this; }
  append(...kids) {
    for (const kid of kids) {
      if (kid instanceof SyntheticNode) kid.parentNode = this;
      this.children.push(kid);
    }
  }
  replaceChildren() {
    for (const kid of this.children) if (kid instanceof SyntheticNode) kid.parentNode = null;
    this.children = [];
  }
  remove() {
    if (this.parentNode) {
      const idx = this.parentNode.children.indexOf(this);
      if (idx >= 0) this.parentNode.children.splice(idx, 1);
      this.parentNode = null;
    }
    if (global.document && global.document.activeElement === this) global.document.activeElement = null;
  }
  setAttribute(k, v) {
    this._attrs[k] = String(v);
    if (k === "id") idRegistry.set(String(v), this);
  }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; }
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
  // Real focus/activeElement tracking (not just a local flag) so the modal
  // a11y trap (initial focus, Tab/Shift-Tab wrap, focus restore) can be
  // exercised behaviorally: withModalA11y reads document.activeElement to
  // decide whether a caller already focused something inside the dialog.
  focus() {
    this._focused = true;
    if (!this.disabled) global.document.activeElement = this;
  }
  blur() {
    this._focused = false;
    if (global.document && global.document.activeElement === this) global.document.activeElement = null;
  }
  scrollIntoView() {}
  // Depth-first search of descendants matching `pred`.
  find(pred) {
    for (const kid of this.children) {
      if (!(kid instanceof SyntheticNode)) continue;
      if (pred(kid)) return kid;
      const nested = kid.find(pred);
      if (nested) return nested;
    }
    return null;
  }
  findAll(pred, out = []) {
    for (const kid of this.children) {
      if (!(kid instanceof SyntheticNode)) continue;
      if (pred(kid)) out.push(kid);
      kid.findAll(pred, out);
    }
    return out;
  }
  hasClass(c) { return this._classes.has(c); }
  // A tiny selector engine covering only what withModalA11y's focus-trap
  // actually queries: a bare tag name, or an attribute-presence check like
  // "a[href]" / "[tabindex]" — no descendant/child combinators needed.
  querySelectorAll(selectorList) {
    const selectors = String(selectorList).split(",").map((s) => s.trim()).filter(Boolean);
    return this.findAll((node) => selectors.some((sel) => {
      const m = sel.match(/^([a-zA-Z0-9_-]*)(\[([a-zA-Z-]+)\])?$/);
      if (!m) return false;
      const [, tag, , attr] = m;
      if (tag && node.tag !== tag) return false;
      if (attr && !node.hasAttribute(attr)) return false;
      return true;
    }));
  }
}

function resetDom() {
  idRegistry.clear();
  const bodyEl = new SyntheticNode("body");
  const mainEl = new SyntheticNode("main");
  mainEl.setAttribute("id", "main");
  const toastEl = new SyntheticNode("div");
  toastEl.setAttribute("id", "toast");
  const scanStatusEl = new SyntheticNode("div");
  scanStatusEl.setAttribute("id", "scan-status");
  bodyEl.append(mainEl, toastEl);
  if (typeof global.document !== "undefined" && global.document) {
    global.document.body = bodyEl;
    global.document.activeElement = null;
  }
  return { mainEl, toastEl, scanStatusEl, bodyEl };
}

// Window listener bookkeeping, exposed so tests can assert on leak/cleanup
// behavior (L1) instead of just trusting the code never leaks.
const windowListeners = { keydown: [], resize: [] };

global.Node = SyntheticNode;

function jsonResponse(body, ok = true, status = 200) {
  return { ok, status, headers: { get: () => "application/json" }, json: async () => body };
}

const FETCH_ROUTES = {
  "/api/overview": () => jsonResponse({ stale: false, generated_at: Date.now() / 1000, totals: { active: 3 } }),
  "/api/skills": () => jsonResponse({ skills: [], categories: [] }),
  "/api/roles": () => jsonResponse({ roles: [] }),
  "/api/live": () => jsonResponse({ sessions: [{ pane_id: "w1:pA", agent: "claude", role_label: "Fix Writer", status: "running", model: "sonnet", skills_used: [] }], projects: [], attention: [], usage: { sessions: [] }, runtime: { available: true, problems: [] } }),
  "/api/tasks": () => jsonResponse({
    ok: true,
    tasks: [{
      id: "task-sample", title: "Sample Task", template: "custom", goal: "", scope: [],
      out_of_scope: [], deliverables: [], acceptance_criteria: [], evidence: [], steps: [], artifacts: [],
      status: "draft",
      provenance: { agent: "pending", tests: "untested", human: "pending", verified: false, verification_asserted: false, notes: "", source: "unauthenticated_console_ui" },
      associated_pane_id: null, associated_session_id: null,
      association_mode: "tracking_only", association_label: "僅追蹤關聯 (Tracking Only) · 未注入 Context",
      created_at: Date.now() / 1000, updated_at: Date.now() / 1000,
    }],
  }),
  "/api/task-templates": () => jsonResponse({ ok: true, templates: { custom: { title: "自訂任務", goal: "", scope: [], deliverables: [] } } }),
  "/api/governance": () => jsonResponse({
    ok: true, compiler_active: false, effective_context_enabled: false,
    notice: "G/P 層於本階段為唯讀介面骨架展示，尚未進行全域治理遷移，無 Policy Compiler 或自動注入。",
    global: { source_type: "skeleton_read_only", status: "唯讀骨架", categories: [] },
    project: { source_type: "skeleton_read_only", contract: { stack: "Python 3.11+" } },
  }),
};

// A terminal SSE stream that connects successfully and then just hangs (its
// reader.read() promise never resolves) — enough for startStream() to reach
// and stay at connState "connected" (so the real "接管操作" takeover button
// renders) without ever completing the read loop or throwing, unlike a bare
// jsonResponse() (no .body) which would make res.body.getReader() throw.
const SSE_STREAM_PATH_RE = /^\/api\/term\/[^/]+\/stream$/;
function sseStreamResponse() {
  return { ok: true, status: 200, body: { getReader: () => ({ read: () => new Promise(() => {}) }) } };
}

global.fetch = async (url) => {
  const path = String(url).split("?")[0];
  if (SSE_STREAM_PATH_RE.test(path)) return sseStreamResponse();
  const route = FETCH_ROUTES[path];
  if (route) return route();
  return jsonResponse({ ok: true }, true);
};

let dom = resetDom();
global.document = {
  createElement: (tag) => new SyntheticNode(tag),
  createTextNode: (text) => new SyntheticNode("#text").withText(String(text)),
  getElementById: (id) => idRegistry.get(id) || null,
  querySelectorAll: () => [],
  querySelector: () => new SyntheticNode(""),
  documentElement: { setAttribute: () => {}, removeAttribute: () => {} },
  addEventListener: () => {},
  activeElement: null,
  body: dom.bodyEl,
};
global.window = {
  addEventListener: (ev, fn) => { if (windowListeners[ev]) windowListeners[ev].push(fn); },
  removeEventListener: (ev, fn) => {
    if (!windowListeners[ev]) return;
    const idx = windowListeners[ev].indexOf(fn);
    if (idx >= 0) windowListeners[ev].splice(idx, 1);
  },
  dispatchEvent: () => {},
  scrollTo: () => {},
};
global.location = { hash: "", pathname: "/", search: "" };
global.history = { replaceState: () => {} };
global.localStorage = {
  _store: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._store, k) ? this._store[k] : null; },
  setItem(k, v) { this._store[k] = String(v); },
};

let app;
try {
  app = require("../../web/app.js");
} catch (e) {
  assert.fail("Failed to load web/app.js: " + e.stack);
}

const {
  STATUS,
  statusBadge,
  activityBasis,
  computeTaskProvenance,
  taskStatusBadge,
  TASK_STATUS_LABELS,
  parseHash,
  viewWorkbench,
  viewTerminal,
  cleanupActiveView,
  cleanupActiveTerminal,
  withModalA11y,
  closeOpenModals,
} = app;

// Minimal xterm.js/FitAddon stand-ins so initTerminalInstance() succeeds and
// startStream() actually runs (with no window.Terminal defined, the real
// code treats terminal init as failed and forces connState to "error",
// which would hide the takeover dialogs' trigger button entirely).
class FakeTerminal {
  constructor() { this.cols = 80; this.rows = 24; }
  loadAddon() {}
  open() {}
  onData() {}
  dispose() {}
}
class FakeFitAddon {
  fit() {}
  proposeDimensions() { return null; }
}

// Flushes pending microtasks (promise `.then` chains) without waiting on any
// real timer — enough for startStream()'s `await fetch(...)` and its
// synchronous continuation (up to connState = "connected") to settle before
// assertions run, since viewTerminal()/viewWorkbench() call startStream()
// without awaiting it (fire-and-forget, so the stream keeps running after
// the view has finished mounting).
async function flushMicrotasks(times = 10) {
  for (let i = 0; i < times; i++) await Promise.resolve();
}

async function runWorkbenchTests() {
  console.log("Starting frontend workbench test suite (Phase B1-B4)...");

  // 1. Status Provenance: separates agent claim from test verification and
  // human approval. There is no authenticated verifier anywhere in this
  // console (H1): only verificationAsserted (an honestly-named self-report,
  // never a governed "verified" claim) can produce derivedStatus
  // "verification_asserted".
  {
    const prov1 = computeTaskProvenance({ agent: "completed", tests: "untested", human: "pending" });
    assert.strictEqual(prov1.verificationAsserted, false, "Agent completion alone must never assert verification");
    assert.strictEqual(prov1.derivedStatus, "agent_completed");

    const prov2 = computeTaskProvenance({ agent: "completed", tests: "passed", human: "pending" });
    assert.strictEqual(prov2.verificationAsserted, false, "Passing tests without human approval must not assert verification");
    assert.strictEqual(prov2.derivedStatus, "agent_completed");

    // Both results asserted, and the server confirms they still refer to the
    // commit the workdir is on now (tasks._derive): verification asserted.
    const prov3 = computeTaskProvenance({ agent: "completed", tests: "passed", human: "approved", verification_asserted: true });
    assert.strictEqual(prov3.verificationAsserted, true, "Only passing tests and human approval can assert verification");
    assert.strictEqual(prov3.derivedStatus, "verification_asserted");

    // The same results without the server's confirmation (the commit moved,
    // or could not be read) are stale, never asserted.
    const prov3b = computeTaskProvenance({ agent: "completed", tests: "passed", human: "approved", verification_asserted: false });
    assert.strictEqual(prov3b.verificationAsserted, false, "A result bound to another commit must not assert verification");
    assert.strictEqual(prov3b.derivedStatus, "verification_stale");
    assert.strictEqual(computeTaskProvenance({ agent: "completed", tests: "passed", human: "pending", verification_asserted: true }).verificationAsserted,
      false, "The server flag alone never asserts verification");

    // Closure shapes the status of a completed card.
    assert.strictEqual(computeTaskProvenance({ agent: "completed" }, "draft", { reason: "handed_off_to", target: "x" }).derivedStatus, "handed_off");
    assert.strictEqual(computeTaskProvenance({ agent: "completed" }, "draft", { reason: "canceled" }).derivedStatus, "closed");
    assert.strictEqual(computeTaskProvenance({ agent: "completed" }, "draft", { reason: "no_follow_on" }).derivedStatus, "agent_completed");
    for (const st of ["verification_stale", "handed_off", "closed"]) assert.ok(TASK_STATUS_LABELS[st], st);

    const prov4 = computeTaskProvenance({ agent: "in_progress", tests: "untested", human: "pending" });
    assert.strictEqual(prov4.derivedStatus, "in_progress");

    const prov5 = computeTaskProvenance({ agent: "blocked", tests: "untested", human: "pending" });
    assert.strictEqual(prov5.derivedStatus, "blocked");

    // H1 (frontend mirror): a raw client status of "verification_asserted"
    // must never be trusted directly — only verificationAsserted (tests
    // passed AND human approved) may produce that derivedStatus.
    const prov6 = computeTaskProvenance({ agent: "pending", tests: "untested", human: "pending" }, "verification_asserted");
    assert.notStrictEqual(prov6.derivedStatus, "verification_asserted", "A raw status of 'verification_asserted' must not be trusted without real provenance");
    assert.strictEqual(prov6.derivedStatus, "draft");

    console.log("ok: Category 1 - Status provenance verification strictly enforced (incl. H1 forgery guard)");
  }

  // 1b. Agent activity badges (vbear/activity.py): only the taxonomy's display
  // values render as a state, and every badge says how VBear knows.
  {
    assert.deepStrictEqual(Object.keys(STATUS).sort(), ["exited", "needs-input", "unknown", "waiting", "working"]);
    const act = {
      display: "working", decided_by: "claude-title", reason: "終端標題顯示工作中的動畫",
      evidence: [{ rung: "claude-title", label: "Claude Code 終端標題（Agent 自己回報）", trust: "authoritative" }],
    };
    const working = statusBadge("working", act);
    assert.strictEqual(working.textContent, "工作中");
    assert.strictEqual(working.getAttribute("title"), "終端標題顯示工作中的動畫｜依據：Claude Code 終端標題（Agent 自己回報）");
    const trial = { display: "unknown", decided_by: null, reason: "Claude Code 2.1.286 的終端標題訊號尚未驗證：只記錄、不採用（試用中）",
      evidence: [{ rung: "claude-title", label: "Claude Code 終端標題（Agent 自己回報）", trust: "trial" }] };
    assert.ok(activityBasis(trial).endsWith("｜沒有可採用的證據"), "trial evidence must never read as the basis");
    // Herdr-era words are not taxonomy values: they render as unknown.
    for (const legacy of ["blocked", "done", "idle"]) assert.strictEqual(statusBadge(legacy, null).textContent, "狀態未知");
    assert.ok(activityBasis(null).includes("沒有任何狀態證據"));
    console.log("ok: Category 1b - activity badges render only taxonomy values, each with its basis");
  }

  // 2. Hash Routing & Compatibility
  {
    global.location.hash = "#/workbench";
    const p1 = parseHash();
    assert.strictEqual(p1.parts[0], "workbench");

    global.location.hash = "#/workbench/w1%3ApA";
    const p2 = parseHash();
    assert.strictEqual(p2.parts[0], "workbench");
    assert.strictEqual(decodeURIComponent(p2.parts[1]), "w1:pA");

    global.location.hash = "#/term/w1%3ApA";
    const p3 = parseHash();
    assert.strictEqual(p3.parts[0], "term");
    assert.strictEqual(decodeURIComponent(p3.parts[1]), "w1:pA");

    console.log("ok: Category 2 - Workbench and #/term backward compatibility routing verified");
  }

  // 3. Mount the real workbench and inspect the rendered DOM (behavioral,
  // not source-string). This is the test that would have caught the missing
  // shell.append() call: without it, `main` never gets a populated shell.
  let mainEl, seqBefore;
  {
    dom = resetDom();
    for (const el of Object.values(dom)) idRegistry.set(el.getAttribute("id"), el);
    mainEl = dom.mainEl;

    await viewWorkbench("w1:pA", null);

    const shellEl = mainEl.find((n) => n.hasClass("wb-shell"));
    assert.ok(shellEl, "wb-shell must be present under #main");
    const cols = shellEl.children.filter((c) => c instanceof SyntheticNode && c.hasClass("wb-col"));
    assert.strictEqual(cols.length, 3, "wb-shell must actually contain its three wb-col children (left/center/right) — regression guard for the missing shell.append() bug");
    assert.ok(cols.some((c) => c.hasClass("wb-left")), "left column must be mounted");
    assert.ok(cols.some((c) => c.hasClass("wb-term-center")), "center column must be mounted");
    assert.ok(cols.some((c) => c.hasClass("wb-right")), "right column must be mounted");

    console.log("ok: Category 3 - viewWorkbench actually mounts its three-column shell under #main");
  }

  // 4. Persistent reopen controls (M3): reachable and functional regardless
  // of collapsed state, independent of any active pane.
  {
    const shellEl = mainEl.find((n) => n.hasClass("wb-shell"));
    const toolbar = mainEl.find((n) => n.hasClass("wb-toolbar"));
    assert.ok(toolbar, "a persistent wb-toolbar must exist outside the collapsible columns");
    const toggles = toolbar.findAll((n) => n.hasClass("wb-col-toggle"));
    assert.strictEqual(toggles.length, 2, "toolbar must expose exactly one reopen/collapse toggle per side column");

    const [leftToggle, rightToggle] = toggles;
    assert.strictEqual(shellEl.hasClass("left-collapsed"), false, "left column starts expanded by default");
    leftToggle.click();
    assert.strictEqual(shellEl.hasClass("left-collapsed"), true, "clicking the persistent toggle must collapse the left column");
    leftToggle.click();
    assert.strictEqual(shellEl.hasClass("left-collapsed"), false, "clicking it again must reopen the left column — this is the only way back once the in-column collapse button has vanished with its column");

    // Both collapsed at once (M2): the CSS needs an explicit
    // .left-collapsed.right-collapsed rule, but that only matters if the
    // markup can actually reach that combined state — assert it can.
    leftToggle.click();
    rightToggle.click();
    assert.strictEqual(shellEl.hasClass("left-collapsed"), true);
    assert.strictEqual(shellEl.hasClass("right-collapsed"), true);
    leftToggle.click();
    rightToggle.click();

    console.log("ok: Category 4 - persistent left/right reopen controls work independent of pane/collapse state");
  }

  // 5. G/P/A/T tabs follow the WAI-ARIA tabs pattern (L4), not just plain
  // unlabeled buttons.
  {
    const tablist = mainEl.find((n) => n.getAttribute("role") === "tablist");
    assert.ok(tablist, "the G/P/A/T tab header must have role=tablist");
    const tabs = tablist.findAll((n) => n.getAttribute("role") === "tab");
    assert.strictEqual(tabs.length, 4, "there must be exactly 4 tabs (T/A/P/G)");
    const selected = tabs.filter((t) => t.getAttribute("aria-selected") === "true");
    assert.strictEqual(selected.length, 1, "exactly one tab must be marked aria-selected=true at a time");
    for (const t of tabs) {
      assert.ok(t.getAttribute("aria-controls"), "each tab must point at its panel via aria-controls");
      assert.ok(t.getAttribute("id"), "each tab must have a stable id for aria-controls/-labelledby to reference");
    }
    const panel = mainEl.find((n) => n.getAttribute("role") === "tabpanel");
    assert.ok(panel, "the active tab's content must be exposed as role=tabpanel");
    assert.strictEqual(panel.getAttribute("aria-labelledby"), selected[0].getAttribute("id"), "the panel must be labelled by the currently-selected tab");

    // Switching tabs updates aria-selected on the DOM (not just internal
    // state), and every tab — not just [A] — must render without throwing:
    // renderAgentTabContent/renderProjectTabContent/renderGlobalTabContent
    // all called the non-variadic append() with multiple loose arguments,
    // which silently dropped content (or threw for a lone child) in every
    // one of them; clicking through all four is what catches that.
    for (const marker of ["[A]", "[P]", "[G]", "[T]"]) {
      const tab = mainEl.find((n) => n.getAttribute("role") === "tab" && n.textContent.includes(marker));
      tab.click();
      const nowSelected = mainEl
        .find((n) => n.getAttribute("role") === "tablist")
        .findAll((n) => n.getAttribute("role") === "tab")
        .filter((t) => t.getAttribute("aria-selected") === "true");
      assert.strictEqual(nowSelected.length, 1, `exactly one tab selected after clicking ${marker}`);
      assert.ok(nowSelected[0].textContent.includes(marker), `clicking the ${marker} tab must move aria-selected to it`);
      assert.ok(mainEl.find((n) => n.getAttribute("role") === "tabpanel"), `${marker} tab must render a tabpanel without throwing`);
    }

    console.log("ok: Category 5 - G/P/A/T tabs expose a real tablist/tab/tabpanel ARIA structure, and every tab renders without throwing");
  }

  // 6. Escape-exits-focus-mode listener is owned and released by the view
  // (L1): route() calls cleanupActiveView() before entering any view, and
  // that must actually remove the listener viewWorkbench registered —
  // mounting repeatedly without it would otherwise leak one listener (and
  // its stale DOM-holding closure) per navigation.
  {
    const before = windowListeners.keydown.length;
    assert.ok(before >= 1, "viewWorkbench must register its Escape handler");

    cleanupActiveView();
    assert.strictEqual(
      windowListeners.keydown.length, before - 1,
      "cleanupActiveView() must remove exactly the listener viewWorkbench registered"
    );

    // A second cleanup call (idempotent, as route() calls it unconditionally
    // on every navigation) must not throw or double-remove.
    cleanupActiveView();
    assert.strictEqual(windowListeners.keydown.length, before - 1);

    // Remounting after cleanup must not accumulate listeners beyond one.
    dom = resetDom();
    for (const el of Object.values(dom)) idRegistry.set(el.getAttribute("id"), el);
    mainEl = dom.mainEl;
    await viewWorkbench("w1:pA", null);
    assert.strictEqual(windowListeners.keydown.length, before - 1 + 1, "remounting must register exactly one new listener, not stack on top of leaked ones");

    console.log("ok: Category 6 - workbench Escape listener is cleanly owned/released, no leak across remounts");
  }

  // 7. Truthful labeling, verified behaviorally against the rendered DOM
  // (L5) — not by grepping app.js's source text for the Chinese strings,
  // which proves nothing about what a user or screen reader actually sees.
  {
    // Category 5 left the view on the [A] tab; switch back to [T] Task Card
    // (where the tracking-only association box lives) before inspecting text.
    const tablist = mainEl.find((n) => n.getAttribute("role") === "tablist");
    const taskTab = tablist.findAll((n) => n.getAttribute("role") === "tab").find((t) => t.textContent.includes("[T]"));
    taskTab.click();

    const bodyText = mainEl.textContent;
    assert.ok(
      bodyText.includes("追蹤關聯 (Tracking Only)") && bodyText.includes("絕非 Context 注入"),
      "the rendered task tab must label task/session association as tracking-only, never context injection"
    );
    assert.ok(
      !bodyText.includes("獨占鎖定") && !bodyText.includes("獨佔鎖定") && !bodyText.includes("exclusive lock"),
      "the rendered UI must never claim takeover is an exclusive lock"
    );
    assert.ok(
      bodyText.includes("同一時間只有一個分頁能控制"),
      "the rendered terminal legend must describe the single-controller takeover model"
    );
    // Provenance fields must not overclaim identity verification (L5): the
    // human-approval field is really just an unauthenticated UI assertion.
    assert.ok(
      bodyText.includes("未經身份驗證"),
      "provenance UI must honestly disclose that approval is not identity-verified"
    );
    // H1: no authenticated verifier exists anywhere in this console, so the
    // rendered UI must never claim a governed "Verified" status — only the
    // honestly-named self-reported "verification asserted".
    assert.ok(
      !bodyText.includes("已達 Verified 標準") && !bodyText.includes("已驗證 (Verified)"),
      "the rendered UI must never claim a governed Verified status"
    );

    console.log("ok: Category 7 - truthful labeling verified against rendered DOM text");
  }

  // 8. Source structure checks that are genuinely about code shape, not
  // user-facing truth claims, are fine to keep as source assertions.
  {
    assert(appSource.includes("async function viewWorkbench("), "viewWorkbench must be defined in app.js");
    assert(appSource.includes("focusMode"), "Focus mode state must be supported in workbench");
    assert(appSource.includes("leftCollapsed"), "Left panel collapse must be supported");
    assert(appSource.includes("rightCollapsed"), "Right panel collapse must be supported");

    console.log("ok: Category 8 - workbench source structure sanity checks");
  }

  // 9. Dialog accessibility (L6): aria-labelledby, initial focus, Tab/
  // Shift-Tab trap, Escape-to-close, focus restored to the trigger, and the
  // rest of the page marked inert while a dialog is open — exercised
  // behaviorally against the real task-edit dialog (promptEditTask), which
  // previously moved initial focus nowhere at all and had no
  // aria-labelledby, focus trap, or background inert.
  {
    const tablist = mainEl.find((n) => n.getAttribute("role") === "tablist");
    const taskTab = tablist.findAll((n) => n.getAttribute("role") === "tab").find((t) => t.textContent.includes("[T]"));
    taskTab.click();

    const editBtn = mainEl.find((n) => n.tag === "button" && n.textContent.includes("編輯任務"));
    assert.ok(editBtn, "task tab must render an 編輯任務 (edit task) trigger button");
    editBtn.focus(); // a real click also focuses the clicked button
    editBtn.click();

    const modal = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal, "promptEditTask must append its dialog to document.body");
    assert.strictEqual(modal.getAttribute("role"), "dialog");
    assert.strictEqual(modal.getAttribute("aria-modal"), "true");

    const labelledbyId = modal.getAttribute("aria-labelledby");
    assert.ok(labelledbyId, "dialog must set aria-labelledby");
    const titleEl = modal.find((n) => n.getAttribute("id") === labelledbyId);
    assert.ok(titleEl && titleEl.textContent.includes("編輯任務卡"), "aria-labelledby must point at the dialog's actual visible title");

    const focusable = modal.querySelectorAll('a[href], button, textarea, input, select, [tabindex]');
    assert.ok(focusable.length >= 2, "dialog must expose multiple focusable controls");
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    assert.strictEqual(document.activeElement, first, "initial focus must move into the dialog (previously promptEditTask left focus on the trigger button)");
    assert.notStrictEqual(document.activeElement, editBtn, "focus must leave the trigger button once the dialog opens");

    assert.strictEqual(mainEl.hasAttribute("inert"), true, "background content must be marked inert while a dialog is open");
    assert.strictEqual(mainEl.getAttribute("aria-hidden"), "true", "background content must be aria-hidden while a dialog is open");

    last.focus();
    modal.dispatch("keydown", { key: "Tab", shiftKey: false });
    assert.strictEqual(document.activeElement, first, "Tab on the last control must wrap focus to the first (focus trap)");

    first.focus();
    modal.dispatch("keydown", { key: "Tab", shiftKey: true });
    assert.strictEqual(document.activeElement, last, "Shift+Tab on the first control must wrap focus to the last (focus trap)");

    modal.dispatch("keydown", { key: "Escape" });
    assert.strictEqual(modal.parentNode, null, "Escape must remove the dialog from the DOM");
    assert.strictEqual(mainEl.hasAttribute("inert"), false, "closing the dialog must restore background inert state");
    assert.strictEqual(mainEl.getAttribute("aria-hidden"), null, "closing the dialog must restore background aria-hidden state");
    assert.strictEqual(document.activeElement, editBtn, "closing the dialog must restore focus to whatever triggered it");

    console.log("ok: Category 9 - task-edit dialog is a real accessible dialog (aria-labelledby, initial focus, Tab trap, Escape, focus restore, background inert)");
  }

  // 10. Router-level cleanup: route() itself must call cleanupActiveView()
  // before mounting each view, not just individual views coincidentally
  // calling it — Category 6 exercised cleanupActiveView() directly; this
  // exercises the actual router entrypoint, which previously documented the
  // contract in a comment but never actually called it, so navigating to
  // the same route twice in a row leaked one Escape listener per navigation.
  {
    assert.strictEqual(typeof app.route, "function", "route() must be exported for router-level testing");

    global.location.hash = "#/workbench";
    dom = resetDom();
    mainEl = dom.mainEl;

    await app.route();
    assert.strictEqual(windowListeners.keydown.length, 1, "after navigating, exactly one Escape listener must be registered (any earlier one cleaned up first)");

    await app.route(); // navigate to the same route again
    assert.strictEqual(
      windowListeners.keydown.length, 1,
      "route() must call cleanupActiveView() before every mount, so repeated navigation to the same route does not accumulate listeners"
    );

    console.log("ok: Category 10 - route() itself cleans up the active view before every mount (repeated navigation)");
  }

  // 11. Create-task dialog (promptCreateTask) focus restore — governance
  // review blocker #1: it used to call titleInput.focus() *before*
  // withModalA11y ran, so withModalA11y captured titleInput itself as the
  // "opener", and Escape/close then tried to restore focus to the very
  // element it had just removed, instead of the "＋ 新增" button that
  // actually opened the dialog.
  {
    global.location.hash = "#/workbench";
    dom = resetDom();
    mainEl = dom.mainEl;
    await app.route();

    const tablist = mainEl.find((n) => n.getAttribute("role") === "tablist");
    const taskTab = tablist.findAll((n) => n.getAttribute("role") === "tab").find((t) => t.textContent.includes("[T]"));
    taskTab.click();

    const newTaskBtn = mainEl.find((n) => n.tag === "button" && n.textContent.includes("＋ 新增"));
    assert.ok(newTaskBtn, "task tab must render a ＋ 新增 (create task) trigger button");
    newTaskBtn.focus(); // a real click also focuses the clicked button
    newTaskBtn.click();

    const modal = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal, "promptCreateTask must append its dialog to document.body");
    const titleInput = modal.find((n) => n.tag === "input");
    assert.ok(titleInput, "dialog must contain the title input");
    assert.strictEqual(document.activeElement, titleInput, "initial focus must move to the title input, as the dialog explicitly requests");
    assert.strictEqual(mainEl.hasAttribute("inert"), true, "background must be inert while the create-task dialog is open");

    modal.dispatch("keydown", { key: "Escape" });
    assert.strictEqual(modal.parentNode, null, "Escape must remove the create-task dialog");
    assert.strictEqual(mainEl.hasAttribute("inert"), false, "closing the dialog must restore background inert state");
    assert.strictEqual(
      document.activeElement, newTaskBtn,
      "closing the dialog must restore focus to the ＋ 新增 button that opened it, not the title input the dialog auto-focused"
    );

    console.log("ok: Category 11 - create-task dialog restores focus to its actual opener, not the title input it auto-focuses");
  }

  // 12. Navigating away while the create-task dialog is still open
  // (governance review blocker #2): closeOpenModals(), invoked from
  // cleanupActiveView(), must close it through its own registered teardown
  // (removing it and restoring background inert/aria-hidden) instead of the
  // dialog being left behind with the rest of the page stuck inert. This
  // must also compose with, not overwrite, viewWorkbench's own
  // activeViewCleanup (which owns the separate Escape-exits-focus-mode
  // window listener) — both must still be cleaned up.
  {
    const beforeKeydownListeners = windowListeners.keydown.length;
    assert.ok(beforeKeydownListeners >= 1, "workbench's Escape-exits-focus-mode listener must still be registered");

    const newTaskBtn = mainEl.find((n) => n.tag === "button" && n.textContent.includes("＋ 新增"));
    newTaskBtn.focus();
    newTaskBtn.click();
    const modal = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal, "create-task dialog must be open again");
    assert.strictEqual(mainEl.hasAttribute("inert"), true);

    global.location.hash = "#/team";
    await app.route();

    assert.strictEqual(modal.parentNode, null, "navigating away must remove the still-open create-task dialog");
    assert.strictEqual(mainEl.hasAttribute("inert"), false, "navigating away must restore background inert state, not leave it permanently inert");
    assert.strictEqual(mainEl.getAttribute("aria-hidden"), null, "navigating away must restore background aria-hidden state");
    assert.strictEqual(
      windowListeners.keydown.length, beforeKeydownListeners - 1,
      "navigating away must still remove exactly viewWorkbench's own Escape listener via activeViewCleanup, proving the modal registry composes with it instead of overwriting it"
    );

    console.log("ok: Category 12 - navigating away while the create-task dialog is open closes it via its own teardown, composed with (not overwriting) the view's own cleanup");
  }

  // 13. Standalone terminal view (viewTerminal)'s takeover confirmation
  // dialog — governance review blocker #1: confirmBtn.focus() used to run
  // *before* withModalA11y, so it captured confirmBtn (about to be removed)
  // as the "opener" instead of the actual 接管操作 trigger button.
  {
    global.Terminal = FakeTerminal;
    global.FitAddon = FakeFitAddon;

    global.location.hash = "#/term/w1%3ApA";
    dom = resetDom();
    mainEl = dom.mainEl;
    await app.route();
    await flushMicrotasks(); // let startStream()'s fire-and-forget fetch settle to connState "connected"

    const takeoverBtn = mainEl.find((n) => n.tag === "button" && n.textContent.includes("接管操作"));
    assert.ok(takeoverBtn, "a connected terminal view must render a 接管操作 (takeover) trigger button");
    takeoverBtn.focus();
    takeoverBtn.click();

    const modal = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal, "promptTakeover must append its dialog to document.body");
    assert.strictEqual(modal.getAttribute("aria-labelledby"), "modal-takeover-title");

    const confirmBtn = modal.find((n) => n.tag === "button" && n.textContent.includes("確認接管操作"));
    assert.ok(confirmBtn, "dialog must contain the explicit confirm button");
    assert.strictEqual(document.activeElement, confirmBtn, "initial focus must move to the explicit confirm button, as the dialog explicitly requests");
    assert.strictEqual(mainEl.hasAttribute("inert"), true, "background must be inert while the takeover dialog is open");

    modal.dispatch("keydown", { key: "Escape" });
    assert.strictEqual(modal.parentNode, null, "Escape must remove the takeover dialog");
    assert.strictEqual(mainEl.hasAttribute("inert"), false, "closing the dialog must restore background inert state");
    assert.strictEqual(
      document.activeElement, takeoverBtn,
      "closing the dialog must restore focus to the 接管操作 button that opened it, not confirmBtn"
    );

    console.log("ok: Category 13 - standalone terminal view's takeover dialog restores focus to its actual opener, not confirmBtn");
  }

  // 14. Navigating away from the standalone terminal view while its
  // takeover dialog is open (governance review blocker #2): cleanupActiveTerminal()
  // must close it through its own registered teardown, not by reaching in
  // and removing modalElem directly (which used to skip restoring
  // background inert/aria-hidden entirely).
  {
    const takeoverBtn = mainEl.find((n) => n.tag === "button" && n.textContent.includes("接管操作"));
    assert.ok(takeoverBtn, "takeover trigger button must still be present");
    takeoverBtn.focus();
    takeoverBtn.click();
    const modal = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal, "takeover dialog must be open again");
    assert.strictEqual(mainEl.hasAttribute("inert"), true);

    global.location.hash = "#/team";
    await app.route();

    assert.strictEqual(modal.parentNode, null, "navigating away must remove the still-open takeover dialog");
    assert.strictEqual(mainEl.hasAttribute("inert"), false, "navigating away must restore background inert state, not leave it permanently inert");
    assert.strictEqual(mainEl.getAttribute("aria-hidden"), null, "navigating away must restore background aria-hidden state");

    console.log("ok: Category 14 - navigating away from the terminal view while its takeover dialog is open closes it via its own teardown");
  }

  // 15. Workbench's embedded terminal pane takeover dialog — the same
  // pattern as Categories 13-14 but exercised through the three-column
  // workbench view's own copy of promptTakeover ("workbench takeover" in
  // the governance review), proving the fix was applied at both call sites,
  // not just the standalone terminal view's.
  {
    global.location.hash = "#/workbench/w1%3ApA";
    dom = resetDom();
    mainEl = dom.mainEl;
    await app.route();
    await flushMicrotasks();

    const takeoverBtn = mainEl.find((n) => n.tag === "button" && n.textContent.includes("接管操作"));
    assert.ok(takeoverBtn, "a connected workbench terminal pane must render a 接管操作 trigger button");
    takeoverBtn.focus();
    takeoverBtn.click();

    const modal = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal, "workbench's promptTakeover must append its dialog to document.body");
    assert.strictEqual(modal.getAttribute("aria-labelledby"), "wb-modal-takeover-title");

    const confirmBtn = modal.find((n) => n.tag === "button" && n.textContent.includes("確認接管操作"));
    assert.strictEqual(document.activeElement, confirmBtn, "initial focus must move to the explicit confirm button");
    assert.strictEqual(mainEl.hasAttribute("inert"), true);

    modal.dispatch("keydown", { key: "Escape" });
    assert.strictEqual(modal.parentNode, null);
    assert.strictEqual(mainEl.hasAttribute("inert"), false);
    assert.strictEqual(
      document.activeElement, takeoverBtn,
      "closing the dialog must restore focus to the 接管操作 button, not confirmBtn"
    );

    // Reopen, then navigate away entirely while it is still open.
    takeoverBtn.focus();
    takeoverBtn.click();
    const modal2 = document.body.find((n) => n.hasClass("modal-backdrop"));
    assert.ok(modal2, "takeover dialog must be open again");
    assert.strictEqual(mainEl.hasAttribute("inert"), true);

    global.location.hash = "#/team";
    await app.route();

    assert.strictEqual(modal2.parentNode, null, "navigating away must remove the still-open workbench takeover dialog");
    assert.strictEqual(mainEl.hasAttribute("inert"), false, "navigating away must restore background inert state");

    console.log("ok: Category 15 - workbench's embedded terminal pane takeover dialog restores focus and tears down cleanly on navigation");
  }

  // 16. Every close path must deregister the dialog from the modal registry
  // — not just the teardown invoked *by* the registry. Escape (and a
  // dialog's own cancel/confirm buttons) call the close function directly,
  // so if that path did not remove itself from the registry, the entry
  // would linger and a later navigation would run the teardown a second
  // time. That is not merely wasteful: the takeover dialogs' teardown
  // closures capture a single reusable `modalElem` variable, so a stale
  // second teardown can tear down a *newly reopened* dialog instead of the
  // one that actually closed.
  {
    dom = resetDom();
    mainEl = dom.mainEl;

    let teardownCount = 0;
    const opener = new SyntheticNode("button");
    dom.bodyEl.append(opener);
    opener.focus();

    const modal = new SyntheticNode("div");
    modal.setAttribute("role", "dialog");
    const btn = new SyntheticNode("button");
    modal.append(btn);
    dom.bodyEl.append(modal);

    const close = withModalA11y(modal, () => { teardownCount += 1; modal.remove(); });
    assert.strictEqual(mainEl.hasAttribute("inert"), true, "opening must make the background inert");

    // Close the way Escape does: the returned close(), not the registry.
    close();
    assert.strictEqual(teardownCount, 1);
    assert.strictEqual(mainEl.hasAttribute("inert"), false);
    assert.strictEqual(document.activeElement, opener, "focus must return to the opener");

    // A later navigation/teardown must find nothing left to close.
    closeOpenModals();
    assert.strictEqual(
      teardownCount, 1,
      "a dialog already closed by Escape must have deregistered itself; running it again could tear down a newly reopened dialog sharing the same modalElem variable"
    );

    // And calling close() again directly must also be a no-op (idempotent).
    close();
    assert.strictEqual(teardownCount, 1, "close() must be idempotent");

    console.log("ok: Category 16 - every close path deregisters from the modal registry, so teardown can never run twice");
  }

  // 17. Stacked dialogs must unwind innermost-first and leave *no* residual
  // inert/aria-hidden behind. Each dialog only inerts what was not already
  // inert, and restores only what it itself inerted; closing them in
  // insertion (outermost-first) order instead would have the outer dialog
  // clear inert while the inner one is still open, and then have the inner
  // dialog write back its "was already inert" snapshot — leaving the page
  // permanently inert after every dialog has closed.
  {
    dom = resetDom();
    mainEl = dom.mainEl;

    const order = [];
    const outer = new SyntheticNode("div");
    outer.append(new SyntheticNode("button"));
    dom.bodyEl.append(outer);
    withModalA11y(outer, () => { order.push("outer"); outer.remove(); });
    assert.strictEqual(mainEl.hasAttribute("inert"), true);

    const inner = new SyntheticNode("div");
    inner.append(new SyntheticNode("button"));
    dom.bodyEl.append(inner);
    withModalA11y(inner, () => { order.push("inner"); inner.remove(); });

    // The inner dialog must not have re-inerted (and therefore must not
    // later "restore") what the outer dialog already inerted.
    assert.strictEqual(mainEl.hasAttribute("inert"), true);
    assert.strictEqual(
      outer.hasAttribute("inert"), true,
      "the outer dialog is background from the inner dialog's point of view and must itself be inerted"
    );

    closeOpenModals();

    assert.deepStrictEqual(order, ["inner", "outer"], "stacked dialogs must unwind innermost-first (LIFO), not in insertion order");
    assert.strictEqual(inner.parentNode, null);
    assert.strictEqual(outer.parentNode, null);
    assert.strictEqual(
      mainEl.hasAttribute("inert"), false,
      "once every dialog has closed, nothing may be left inert"
    );
    assert.strictEqual(
      mainEl.getAttribute("aria-hidden"), null,
      "once every dialog has closed, nothing may be left aria-hidden"
    );

    console.log("ok: Category 17 - stacked dialogs unwind innermost-first and leave no residual inert/aria-hidden");
  }

  // 18. Status Provenance must remain inside the right-column card at narrow
  // widths. The synthetic DOM has no layout engine, so lock the CSS contract
  // that removes intrinsic flex-item minima, permits wrapping, and bounds the
  // native select/badge to the card width. Also lock the semantic class used
  // instead of an untestable inline flex style.
  {
    assert(
      appSource.includes('class: "wb-provenance-head"'),
      "Status Provenance header must use the responsive class"
    );
    assert(
      /\.wb-provenance-head,\s*\n\.wb-provenance-row\s*\{[^}]*flex-wrap:\s*wrap;[^}]*min-width:\s*0;/s.test(styleSource),
      "Provenance header and rows must wrap and allow their flex items to shrink"
    );
    assert(
      /\.wb-provenance-head\s*>\s*\*,\s*\n\.wb-provenance-row\s*>\s*\*\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s.test(styleSource),
      "Every direct provenance flex child must be bounded by the card"
    );
    assert(
      /\.wb-provenance-head\s+\.badge\s*\{[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/s.test(styleSource),
      "The long verification badge must be allowed to wrap"
    );
    assert(
      /\.wb-provenance-row\s+select\s*\{[^}]*max-width:\s*100%;/s.test(styleSource),
      "Native provenance selects must never exceed the card width"
    );

    console.log("ok: Category 18 - narrow Status Provenance layout is bounded and wrap-safe");
  }

  // 19. Task custody (tasks.py, adopted from OpenRig): handing off posts to
  // the atomic /handoff endpoint and shows the chain of record; completing a
  // card goes through the closure dialog, never straight to the API, and a
  // reason that names someone cannot be sent without its target.
  {
    const sample = (await FETCH_ROUTES["/api/tasks"]().json()).tasks[0];
    const calls = [];
    const realFetch = global.fetch;
    global.fetch = async (url, opts = {}) => {
      const path = String(url).split("?")[0];
      if (opts.method === "POST" && path.startsWith("/api/tasks/")) {
        const body = JSON.parse(opts.body || "{}");
        calls.push({ path, body });
        if (path.endsWith("/handoff")) {
          return jsonResponse({
            ok: true,
            from: { ...sample, status: "handed_off", provenance: { ...sample.provenance, agent: "completed" },
              closure: { reason: "handed_off_to", target: body.to, note: body.note, set_at: 1, successor: "task-next" } },
            to: { ...sample, id: "task-next", title: body.title, owner: body.to, handed_off_from: sample.id,
              chain_of_record: [sample.id], pickup: { state: "unclaimed", detail: "還沒有關聯任何 Terminal" } },
          });
        }
        const id = decodeURIComponent(path.slice("/api/tasks/".length));
        return jsonResponse({ ok: true, task: { ...sample, id, provenance: { ...sample.provenance, ...(body.provenance || {}) },
          closure: body.closure ? { ...body.closure, set_at: 1 } : null } });
      }
      return realFetch(url, opts);
    };
    try {
      global.location.hash = "#/workbench";
      dom = resetDom();
      mainEl = dom.mainEl;
      await app.route();
      const tab = mainEl.find((n) => n.getAttribute("role") === "tab" && n.textContent.includes("[T]"));
      tab.click();
      assert.ok(mainEl.find((n) => n.textContent === "處理狀態未知"), "a card without a pickup state must read unknown, not idle");
      assert.ok(mainEl.find((n) => n.tag === "span" && n.textContent.startsWith("4. 結果對應的版本")), "the commit binding row must render");

      // Handoff.
      mainEl.find((n) => n.tag === "button" && n.textContent === "交接給…").click();
      let modal = document.body.find((n) => n.hasClass("modal-backdrop"));
      assert.ok(modal && modal.find((n) => n.getAttribute("id") === "task-handoff-modal-title"), "handoff dialog must open");
      const submitHandoff = modal.find((n) => n.tag === "button" && n.textContent === "交接");
      submitHandoff.click();
      await flushMicrotasks();
      assert.strictEqual(calls.length, 0, "a handoff without a target must not be sent");
      modal.find((n) => n.tag === "input" && (n.getAttribute("placeholder") || "").startsWith("接手")).value = "審查者";
      // The synthetic DOM does not reflect the value attribute into .value the
      // way a browser does, so check the default title on the attribute and
      // type the title explicitly.
      const titleField = modal.find((n) => n.tag === "input" && n.getAttribute("value") === `交接：${sample.title}`);
      assert.ok(titleField, "the successor title must default to 交接：<old title>");
      titleField.value = titleField.getAttribute("value");
      submitHandoff.click();
      await flushMicrotasks();
      assert.strictEqual(calls.length, 1);
      assert.strictEqual(calls[0].path, `/api/tasks/${sample.id}/handoff`);
      assert.deepStrictEqual(calls[0].body, { to: "審查者", title: `交接：${sample.title}`, note: "" });
      assert.strictEqual(modal.parentNode, null, "the handoff dialog must close after success");
      const chain = mainEl.find((n) => n.textContent.startsWith("交接鏈："));
      assert.ok(chain && chain.textContent.endsWith("本卡"), "the successor must show its chain of record");

      // Closure on the successor (now the active card).
      const agentSelect = () => mainEl.find((n) => n.tag === "select"
        && n.findAll((o) => o.tag === "option" && o.getAttribute("value") === "completed").length > 0);
      agentSelect().value = "completed";
      agentSelect().dispatch("change");
      await flushMicrotasks();
      assert.strictEqual(calls.length, 1, "completing must wait for a closure reason");
      modal = document.body.find((n) => n.hasClass("modal-backdrop"));
      assert.ok(modal && modal.find((n) => n.getAttribute("id") === "task-closure-modal-title"), "closure dialog must open");
      const reason = modal.find((n) => n.tag === "select");
      reason.value = "handed_off_to";
      reason.dispatch("change");
      const confirmBtn = modal.find((n) => n.tag === "button" && n.textContent === "確定");
      confirmBtn.click();
      await flushMicrotasks();
      assert.strictEqual(calls.length, 1, "a reason that names someone needs its target");
      modal.find((n) => n.tag === "input").value = "下一位";
      confirmBtn.click();
      await flushMicrotasks();
      assert.strictEqual(calls.length, 2);
      assert.strictEqual(calls[1].path, "/api/tasks/task-next");
      assert.strictEqual(calls[1].body.provenance.agent, "completed");
      assert.deepStrictEqual(calls[1].body.closure, { reason: "handed_off_to", target: "下一位", note: "" });
      assert.strictEqual(modal.parentNode, null, "the closure dialog must close after success");
      assert.ok(mainEl.find((n) => n.tag === "b" && n.textContent === "交給下一位"), "the stored closure must be shown");

      // Cancelling sends nothing.
      agentSelect().value = "blocked";
      agentSelect().dispatch("change");
      modal = document.body.find((n) => n.hasClass("modal-backdrop"));
      modal.dispatch("keydown", { key: "Escape" });
      await flushMicrotasks();
      assert.strictEqual(modal.parentNode, null);
      assert.strictEqual(calls.length, 2, "a cancelled closure dialog must not post");
    } finally {
      global.fetch = realFetch;
    }

    console.log("ok: Category 19 - handoff and closure dialogs post only complete custody records");
  }

  console.log("\nALL WORKBENCH FRONTEND TESTS PASSED (19/19 categories verified)");
}

runWorkbenchTests()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Workbench test failure:", err);
    process.exit(1);
  });
