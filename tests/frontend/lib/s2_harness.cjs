// S2c-4: the flow page's VBear-managed panels (acceptance dialog, executor, dispatch composer, reports, reviews, gate).
// Run: node tests/frontend/coordinator.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const appSource = fs.readFileSync(path.join(__dirname, "..", "..", "..", "web", "app.js"), "utf8");

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

const FETCH_LOG = [];
let FETCH_HANDLER = () => null;
global.fetch = async (url, opts = {}) => {
  const p = String(url);
  FETCH_LOG.push({ url: p, method: (opts.method || 'GET'), body: opts.body ? JSON.parse(opts.body) : null });
  const r = FETCH_HANDLER(p, opts);
  if (r) return r;
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
try { app = require("../../../web/app.js"); } catch (e) { assert.fail("Failed to load web/app.js: " + e.stack); }
module.exports = { app, SyntheticNode, FETCH_LOG, jsonResponse, setHandler: (fn) => { FETCH_HANDLER = fn; }, dom: () => dom };
