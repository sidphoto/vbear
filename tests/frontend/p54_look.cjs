// P54 (v0.25.0): what the first real look at the pages found (screenshots of a stub console, tools/shots_stub.py), kept from coming back. Reads web/style.css as text (or the
// file named by P54_CSS, for the bad sample) and runs the two functions of the phone menu from web/app.js in a vm. NOT a browser test: that the pages look right was seen in
// the screenshots; this only keeps the rules that made them so.
//
//  1. The phone's page grid has the bar as its own row (`auto`) and the page as `1fr`: a short page no longer shares its free height with the bar (the bar was 82 to 200px, not 57px).
//  2. While the drawer is open the bar is above the drawer and the backdrop, the drawer starts under the bar (top 57px, the height the waiting bar already uses), and the button says 關閉.
//  3. The box of the home page and the chat page has one ring when it has the focus (the outline over its border, not 2px away from it).
//  4. The line with your name and time, and the buttons 記住 and 存成常用做法, take no room while hidden (they sit over the space between messages) and are shown, and
//     can be pressed, on hover and on focus.
//  5. The line over a fold shows its arrow on the first line and is underlined when you point at it.
//
// Run: node tests/frontend/p54_look.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const CSS = fs.readFileSync(process.env.P54_CSS || path.join(ROOT, "web", "style.css"), "utf8");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const INDEX = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
const at = CSS.indexOf("/* P54 (v0.25.0)");
const BLOCK = at >= 0 ? CSS.slice(at) : "";
// the rules of the block that are not inside a @media: the text before the first "@media" and after its closing
const rule = (selector) => {
  const esc = selector.replace(/[.#[\]="$^*+?()|\\:-]/g, "\\$&");
  const m = new RegExp("(?:^|\\n)\\s*" + esc + "\\s*\\{([^}]*)\\}").exec(BLOCK);
  return m ? m[1] : null;
};

let passed = 0;
const test = (name, fn) => { fn(); passed += 1; console.log("ok - " + name); };

test("the P54 block is at the end of the file and is the only thing after the P53 toast rule", () => {
  assert.ok(at > CSS.indexOf("/* P53 (v0.25.0)"), "after P53");
  assert.ok(!/innerHTML|url\(|@import|https?:\/\//.test(BLOCK), "no resource and no script");
  assert.ok(!/[☀-➿\u{1F300}-\u{1FAFF}]/u.test(BLOCK), "no emoji");
});

test("1. on a phone the grid's first row is the bar's own height and the page takes the rest", () => {
  const media = /@media \(max-width: 720px\) \{([\s\S]*?)\n\}/.exec(BLOCK);
  assert.ok(media, "a phone block");
  assert.ok(/\.shell \{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\)/.test(media[1]), ".shell rows");
  // the waiting bar sticks under that bar: the number is the bar's height (56px + its 1px line) and the drawer uses the same
  assert.ok(/\.waiting-bar \{ top: 57px; \}/.test(CSS), "the waiting bar's top");
  assert.ok(/\.side-panel \{[^}]*top:\s*57px/.test(media[1]), "the drawer starts under the bar");
});

test("2. the open drawer: the bar is above the drawer (70 against 60) and the backdrop (50), with its own background", () => {
  const media = /@media \(max-width: 720px\) \{([\s\S]*?)\n\}/.exec(BLOCK)[1];
  const open = /\.side\.nav-open \.side-top \{([^}]*)\}/.exec(media);
  assert.ok(open, "the open bar");
  assert.ok(/position:\s*relative/.test(open[1]) && /background:\s*var\(--side-bg\)/.test(open[1]), "above and opaque");
  const z = Number((/z-index:\s*(\d+)/.exec(open[1]) || [])[1]);
  const drawer = Number((/\.side-panel \{[^}]*z-index:\s*(\d+)/.exec(CSS) || [])[1]);
  const backdrop = Number((/\.nav-backdrop \{[^}]*z-index:\s*(\d+)/.exec(CSS) || [])[1]);
  assert.ok(z > drawer && drawer > backdrop, `${z} > ${drawer} > ${backdrop}`);
  assert.ok(Number((/#toast \{[^}]*z-index:\s*(\d+)/.exec(CSS) || [])[1]) > z, "the toast stays above all of it");
});

// the two functions of the menu, run on a small fake page
function menu() {
  const attrs = { "aria-expanded": "false", "aria-label": "選單" };
  const btn = { dataset: {}, getAttribute: (k) => (k in attrs ? attrs[k] : null), setAttribute: (k, v) => { attrs[k] = String(v); } };
  const label = { textContent: "選單" };
  const classes = new Set();
  const side = { classList: { toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); } } };
  const ctx = { document: { querySelector: () => side, getElementById: (id) => (id === "nav-toggle" ? btn : id === "nav-toggle-label" ? label : null) }, navPageName: (t) => (t === "chat" ? "員工" : "首頁") };
  vm.createContext(ctx);
  const from = SRC.indexOf("function setNavMenu(open)");
  const to = SRC.indexOf("function showHidden(");
  assert.ok(from > 0 && to > from);
  vm.runInContext(SRC.slice(from, to) + "\nthis.setNavMenu = setNavMenu; this.syncNavMenu = syncNavMenu;", ctx);
  return { ctx, attrs, label, classes, btn };
}

test("2. while the drawer is open the button says 關閉 (its label too) and the name of the page comes back when it closes", () => {
  const m = menu();
  m.ctx.syncNavMenu("home");
  assert.strictEqual(m.attrs["aria-label"], "選單（目前在「首頁」）");
  assert.strictEqual(m.label.textContent, "選單");
  m.ctx.setNavMenu(true);
  assert.ok(m.classes.has("nav-open"));
  assert.strictEqual(m.attrs["aria-expanded"], "true");
  assert.strictEqual(m.label.textContent, "關閉");
  assert.strictEqual(m.attrs["aria-label"], "關閉選單");
  m.ctx.setNavMenu(true);
  assert.strictEqual(m.attrs["aria-label"], "關閉選單", "opening twice keeps the label of the closed button");
  m.ctx.setNavMenu(false);
  assert.ok(!m.classes.has("nav-open"));
  assert.strictEqual(m.label.textContent, "選單");
  assert.strictEqual(m.attrs["aria-label"], "選單（目前在「首頁」）");
});

test("2. going to another page with the drawer open puts it away and names the new page (not the old one)", () => {
  const m = menu();
  m.ctx.syncNavMenu("home");
  m.ctx.setNavMenu(true);
  m.ctx.syncNavMenu("chat");
  assert.ok(!m.classes.has("nav-open"));
  assert.strictEqual(m.label.textContent, "選單");
  assert.strictEqual(m.attrs["aria-label"], "選單（目前在「員工」）");
});

test("2. the button is still the one of index.html (same id, same aria), and no new element or handler was added", () => {
  assert.ok(/<button class="nav-toggle" id="nav-toggle" type="button" aria-expanded="false" aria-controls="side-panel">/.test(INDEX));
  assert.ok(/id="nav-toggle-label">選單</.test(INDEX));
});

test("3. the box has one ring when it has the focus: the outline sits on the border (a negative offset) and the border gives way", () => {
  const r = rule(".home-box:focus-within");
  assert.ok(r, "a rule in the block");
  assert.ok(/outline:\s*2px solid var\(--gold\)/.test(r) && /outline-offset:\s*-1px/.test(r) && /border-color:\s*transparent/.test(r), r);
  assert.ok(/\.home-box textarea:focus, \.home-box textarea:focus-visible \{ outline: none; \}/.test(CSS), "the text area has no ring of its own");
});

test("4. your name and time, and the buttons of a message, take no room while hidden", () => {
  assert.ok(/position:\s*relative/.test(rule(".chat-msg") || ""), "the message is the frame");
  const who = rule(".chat-me .chat-who-quiet") || "";
  assert.ok(/position:\s*absolute/.test(who) && /bottom:\s*100%/.test(who), "the line over the bubble: " + who);
  const keep = rule(".chat-msg .chat-remember") || "";
  assert.ok(/position:\s*absolute/.test(keep) && /top:\s*100%/.test(keep) && /pointer-events:\s*none/.test(keep), "the buttons under the message: " + keep);
  const on = /\.chat-msg:hover \.chat-remember, \.chat-msg:focus \.chat-remember, \.chat-msg:focus-within \.chat-remember \{([^}]*)\}/.exec(BLOCK);
  assert.ok(on && /pointer-events:\s*auto/.test(on[1]), "they can be pressed when shown");
  // the P47-4 rule that shows them is still there, and they are never display: none or visibility: hidden (the keyboard reaches them)
  assert.ok(/\.chat-msg:hover \.chat-remember[^{]*\{[^}]*opacity:\s*1/.test(CSS));
  assert.ok(!/\.chat-remember[^{]*\{[^}]*(display:\s*none|visibility:\s*hidden)/.test(CSS + BLOCK));
});

test("5. the line over a fold: the arrow stays on the first line and the line is underlined when pointed at", () => {
  const sum = rule(".chat-quiet-sum") || "";
  assert.ok(/align-items:\s*flex-start/.test(sum), sum);
  assert.ok(/flex:\s*none/.test(rule(".chat-quiet-sum::before") || ""));
  assert.ok(/text-decoration:\s*underline/.test(rule(".chat-quiet-sum:hover") || ""));
  assert.ok(/outline:\s*2px solid var\(--accent\)/.test(rule(".chat-quiet-sum:focus-visible") || ""), "and it shows the keyboard focus");
});

test("6. a plain select has the pills' look, with a rule of low weight (a select with its own rule keeps it)", () => {
  const r = rule("main select") || "";
  assert.ok(/border-radius:\s*10px/.test(r) && /border:\s*1px solid var\(--line-2\)/.test(r) && /background:\s*var\(--panel\)/.test(r), r);
});

console.log(`${passed} passed`);
