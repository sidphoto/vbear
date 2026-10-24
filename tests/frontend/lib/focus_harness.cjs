// A synthetic DOM that behaves like a browser where the keyboard focus is concerned, for the tests that are about
// where the focus is: document.activeElement follows focus(); a node that is removed, replaced or moved takes the
// focus with it and the focus falls back to <body>; a key event goes to the focused node and bubbles up.
// It runs the real web/app.js code (the slice from el() to the first line that starts the page) in a vm context.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "..", "web", "app.js"), "utf8");

function createHarness() {
  const idRegistry = new Map();
  const doc = { activeElement: null, body: null, documentElement: null };

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
      return this.children.map((c) => (c instanceof Node ? c.textContent : String(c))).join("");
    }
    set textContent(v) {
      this.replaceChildren();
      if (this.tag === "#text") this._text = String(v);
      else if (v !== "") { const t = new Node("#text"); t._text = String(v); this.append(t); }
    }
    get isConnected() {
      let n = this;
      while (n.parentNode) n = n.parentNode;
      return n === doc.body;
    }
    contains(node) {
      for (let n = node; n; n = n.parentNode) if (n === this) return true;
      return false;
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
      if (this._listeners[ev]) this._listeners[ev] = this._listeners[ev].filter((f) => f !== fn);
    }
    // like a browser: the event starts at this node and goes up through its parents
    dispatch(type, extra = {}) {
      const evt = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
      for (let n = this; n; n = n.parentNode) {
        for (const fn of (n._listeners[type] || []).slice()) fn(evt);
      }
      return evt;
    }
    click() { this.dispatch("click"); }
    // a node leaving its place (removed, replaced, moved) loses the focus, whether it holds it or one of its descendants does
    _detach() {
      if (!this.parentNode) return;
      const at = this.parentNode.children.indexOf(this);
      if (at >= 0) this.parentNode.children.splice(at, 1);
      if (doc.activeElement && this.contains(doc.activeElement)) doc.activeElement = doc.body;
      this.parentNode = null;
    }
    append(...kids) {
      for (const kid of kids) {
        if (kid instanceof Node) { kid._detach(); kid.parentNode = this; }
        this.children.push(kid);
      }
    }
    appendChild(kid) { this.append(kid); return kid; }
    replaceChildren() {
      for (const k of this.children.slice()) if (k instanceof Node) k._detach();
      this.children = [];
    }
    remove() { this._detach(); }
    focus() { if (!this.disabled) doc.activeElement = this; }
    blur() { if (doc.activeElement === this) doc.activeElement = doc.body; }
    scrollIntoView() {}
    // a bare tag, or tag[attr], or [attr], joined by commas: all that the code under test asks for
    querySelectorAll(list) {
      const sels = String(list).split(",").map((s) => s.trim()).filter(Boolean);
      return all(this).filter((n) => sels.some((sel) => {
        const m = sel.match(/^([a-zA-Z0-9_-]*)(\[([a-zA-Z-]+)\])?$/);
        return m && (!m[1] || n.tag === m[1]) && (!m[3] || n.hasAttribute(m[3]));
      }));
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  }
  function all(n) {
    const out = [];
    for (const c of n.children) if (c instanceof Node) { out.push(c, ...all(c)); }
    return out;
  }

  const main = new Node("main");
  main.setAttribute("id", "main");
  main.setAttribute("tabindex", "-1");

  function reset() {
    idRegistry.clear();
    const body = new Node("body");
    doc.body = body;
    doc.activeElement = body;
    doc.documentElement = new Node("html");
    main._detach();
    main.replaceChildren();
    idRegistry.set("main", main);
    const toast = new Node("div");
    toast.setAttribute("id", "toast");
    body.append(main, toast);
    return body;
  }

  // routes: { "GET /path": (url, options) => response | Promise<response> }; an unknown route throws, like a network failure
  function context(routes) {
    const body = reset();
    const calls = [];
    const ctx = {
      Node, console: { log: () => {}, warn: () => {}, error: () => {} },
      document: {
        createElement: (t) => new Node(t),
        createElementNS: (_ns, t) => new Node(t),
        createTextNode: (t) => { const n = new Node("#text"); n._text = String(t); return n; },
        getElementById: (id) => idRegistry.get(id) || null,
        get body() { return doc.body; },
        get activeElement() { return doc.activeElement; },
        documentElement: doc.documentElement,
      },
      setTimeout: (f) => { if (typeof f === "function") f(); return 0; },
      clearTimeout: () => {},
      location: { hash: "" },
      history: { replaceState: () => {} },
      localStorage: { getItem: () => null, setItem: () => {} },
      URLSearchParams,
      confirm: () => true,
      fetch: async (url, options) => {
        const key = `${(options && options.method) || "GET"} ${url}`;
        calls.push(key);
        const route = routes[key];
        if (!route) throw new Error(`no route for ${key}`);
        return route(url, options);
      },
      window: { addEventListener: () => {}, removeEventListener: () => {}, innerWidth: 1024 },
      setKids: (parent, ...kids) => { parent.replaceChildren(); for (const k of kids.flat(Infinity)) if (k) parent.append(k); },
    };
    ctx.calls = calls;
    vm.createContext(ctx);
    const start = source.indexOf("function el(");
    const end = source.indexOf("setTheme(store.get");
    vm.runInContext(source.slice(start, end), ctx);
    return { ctx, body, main, calls };
  }

  const json = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
  // a response that is held back until release() is called, to stand for a slow server
  function slow(data, status = 200) {
    let release;
    const held = new Promise((r) => { release = () => r(json(data, status)); });
    const fn = () => held;
    fn.release = release;
    return fn;
  }
  const tick = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
  const walk = (n) => all(n);
  const button = (root, text) => walk(root).find((n) => n.tag === "button" && (n.textContent || "").trim() === text);
  const dialogs = (body) => body.children.filter((c) => c.getAttribute && c.getAttribute("role") === "dialog");
  const press = (key, extra = {}) => (doc.activeElement || doc.body).dispatch("keydown", { key, ...extra });

  return { Node, doc, context, json, slow, tick, walk, button, dialogs, press, main };
}

module.exports = { createHarness };
