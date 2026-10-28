// P33: the hover box that shows a skill's whole description. Real components in a synthetic DOM with fake timers;
// where it lands in a real window is checked in a headless browser (see the P33 report), the arithmetic here.
"use strict";
const fs = require("fs"), vm = require("vm"), assert = require("assert"), path = require("path");
const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../web/style.css"), "utf8");

// ---- a small DOM: events (several listeners, capture flag), parents, rects, isConnected -------------------------------
let active = null;
function walk(n) { return [n, ...n.children.flatMap(walk)]; }
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.attrs = {};
    this.hidden = false; this.rect = { left: 0, top: 0, right: 100, bottom: 40, width: 100, height: 40 }; this.className = ""; }
  append(child) { if (child.parent) child.parent.children = child.parent.children.filter((x) => x !== child); this.children.push(child); child.parent = this; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this); this.parent = null; }
  replaceChildren() { for (const c of this.children) c.parent = null; this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k, fn, opt) { (this.listeners[k] = this.listeners[k] || []).push({ fn, capture: opt === true || (opt && opt.capture) }); }
  removeEventListener(k, fn) { this.listeners[k] = (this.listeners[k] || []).filter((x) => x.fn !== fn); }
  fire(k, ev = {}) { const e = Object.assign({ type: k, target: this, stopped: false, prevented: false,
    stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; } }, ev);
    for (const l of [...(this.listeners[k] || [])]) l.fn(e); return e; }
  contains(node) { return this === node || this.children.some((c) => c.contains(node)); }
  get parentNode() { return this.parent || null; }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n === body; }
  closest(sel) { const cls = sel.replace(/^\./, ""); for (let n = this; n; n = n.parent) if ((n.className || "").split(/\s+/).includes(cls)) return n; return null; }
  getBoundingClientRect() { return this.size ? { ...this.rect, width: this.size.width, height: this.size.height, right: this.rect.left + this.size.width, bottom: this.rect.top + this.size.height } : this.rect; }
  focus() { active = this; }
  get textContent() { return this.tag === "#text" ? this.text : this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(); this.text = String(v); }
}
const body = new Node("body");
const document = { body, documentElement: { clientWidth: 1280, clientHeight: 800 }, listeners: {},
  createElement: (t) => new Node(t), createTextNode: (t) => Object.assign(new Node("#text"), { text: String(t) }),
  getElementById: (id) => walk(body).find((n) => n.id === id) || null,
  addEventListener(k, fn, opt) { (this.listeners[k] = this.listeners[k] || []).push({ fn, capture: opt === true || (opt && opt.capture) }); },
  fire(k, ev = {}) { const e = Object.assign({ type: k, target: body, stopped: false, prevented: false,
    stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; } }, ev);
    for (const l of [...(this.listeners[k] || [])].sort((a, b) => Number(b.capture) - Number(a.capture))) { if (e.stopped && !l.capture) break; l.fn(e); } return e; },
  get activeElement() { return active; } };
const win = { innerWidth: 1280, innerHeight: 800, listeners: {}, addEventListener(k, fn, opt) { (this.listeners[k] = this.listeners[k] || []).push({ fn, capture: opt === true || (opt && opt.capture) }); },
  fire(k, ev = {}) { const e = Object.assign({ type: k, target: body }, ev); for (const l of this.listeners[k] || []) l.fn(e); } };

// ---- fake clock ----------------------------------------------------------------------------------------------------
let now = 0, nextTimer = 1; const timers = new Map();
const fakeSetTimeout = (fn, ms) => { const id = nextTimer++; timers.set(id, { at: now + (ms || 0), fn }); return id; };
const fakeClearTimeout = (id) => { timers.delete(id); };
function advance(ms) {
  const end = now + ms;
  for (;;) {
    const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) break;
    now = due[1].at; timers.delete(due[0]); due[1].fn();
  }
  now = end;
}

const ctx = { Node, document, window: win, console, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout,
  badge: (label) => { const n = new Node("span"); n.append(document.createTextNode(label)); return n; }, fmtTime: (x) => `time:${x}` };
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf("function el("), source.indexOf("const api =")), ctx);
vm.runInContext(source.slice(source.indexOf("// ---------- skill translations"), source.indexOf("// ---------- end skill help float")), ctx);
const run = (s) => vm.runInContext(s, ctx);

// ---- fake data: obviously invented, long on purpose -----------------------------------------------------------------
const LONG_ZH = Array.from({ length: 60 }, (_, i) => `第${i + 1}句假的中文說明，用來確認浮動框不會把長說明截短。`).join("") + "最後一句收尾。";
const LONG_EN = Array.from({ length: 40 }, (_, i) => `Fake sentence number ${i + 1} of a long original description.`).join(" ") + " THE-VERY-END";
assert(LONG_ZH.length > 500 && LONG_EN.length > 500);
const skillZh = { skill_id: "s-zh", name: "fake-zh", description: { value: LONG_EN }, excerpt: LONG_EN.slice(0, 140) };
const skillEn = { skill_id: "s-en", name: "fake-en", description: { value: LONG_EN }, excerpt: LONG_EN };
const skillNone = { skill_id: "s-none", name: "fake-none", description: { value: "" }, excerpt: "" };
const skillEvil = { skill_id: "s-evil", name: "fake-evil", description: { value: "<img src=x onerror=alert(1)> plain words" } };
run(`T.entries["s-zh"] = { state: "fresh", entry: { description_zh: ${JSON.stringify(LONG_ZH)}, summary: { what: "短摘要", when: "要審查程式碼的時候", needs: "一份差異檔" },
  engine: "claude", model: "haiku", created_at: 1 } };
T.entries["s-stale"] = { state: "stale", entry: { description_zh: "過期的翻譯內容", summary: { what: "x", when: "原文未提供", needs: "原文未提供" }, engine: "claude", model: "haiku", created_at: 1 } };`);
const skillStale = { skill_id: "s-stale", name: "fake-stale", description: { value: "Stale original." } };

const mk = (rect, extra = {}) => { const n = new Node("a"); Object.assign(n, { rect: { left: 100, top: 100, right: 300, bottom: 160, width: 200, height: 60, ...rect } }, extra); body.append(n); return n; };
const tip = () => walk(body).filter((n) => n.attrs.role === "tooltip");
const shown = () => { const t = tip()[0]; return Boolean(t) && !t.hidden; };
const text = () => tip()[0].textContent;
// the tip measures itself: a fixed size in the fake DOM, as a real browser would report after max-width/max-height
const SIZE = { width: 420, height: 300 };
const sizeTip = () => { const t = tip()[0]; if (t) t.size = SIZE; };

// ---- 1. the position, a pure function -------------------------------------------------------------------------------
{
  const place = (a, size = SIZE, view = { width: 1280, height: 800 }) => run(`skillTipPlace(${JSON.stringify(a)}, ${JSON.stringify(size)}, ${JSON.stringify(view)})`);
  const A = (left, top, w = 200, h = 60) => ({ left, top, right: left + w, bottom: top + h });
  let p = place(A(100, 100));
  assert.equal(p.side, "below"); assert(p.top >= 160 && p.left === 100, "ordinary: under the card, edges aligned");
  p = place(A(1000, 100));   // right edge of the window: opens to the left
  assert(p.left + SIZE.width <= 1280 - 8 && p.left < 1000, `right card flips left: ${JSON.stringify(p)}`);
  assert.equal(p.left, 1200 - SIZE.width, "right edge of the tip lines up with the right edge of the card");
  p = place(A(100, 700));    // bottom of the window: opens above
  assert.equal(p.side, "above"); assert(p.top + SIZE.height <= 700, "ends above the card");
  p = place(A(1050, 720));   // both
  assert.equal(p.side, "above"); assert(p.left + SIZE.width <= 1272 && p.top >= 8);
  // whatever the card and the window, the tip stays whole inside the window
  for (const view of [{ width: 1280, height: 800 }, { width: 390, height: 640 }, { width: 600, height: 300 }])
    for (let x = -50; x <= view.width + 50; x += 97) for (let y = -50; y <= view.height + 50; y += 61) {
      const size = { width: Math.min(420, view.width - 16), height: 300 };
      const q = place(A(x, y), size, view);
      const h = Math.min(size.height, q.maxHeight);
      assert(q.left >= 8 && q.left + size.width <= view.width - 8, `horizontal ${JSON.stringify([view, x, y, q])}`);
      assert(q.top >= 8 && q.top + h <= view.height - 8 + 0.001, `vertical ${JSON.stringify([view, x, y, q])}`);
      assert(q.maxHeight > 0);
    }
  // taller than either side: it takes the roomier side and the limit shrinks to fit (it scrolls inside)
  p = place(A(100, 300, 200, 60), { width: 420, height: 700 }, { width: 1280, height: 800 });
  assert(p.maxHeight < 700 && p.maxHeight >= 300, JSON.stringify(p));
}

// ---- 2. hover: after a short wait, whole text, gone after leaving ---------------------------------------------------
const card = mk({});
const wire = (n, s, o) => ctx.withSkillTip(n, s, o);
wire(card, skillZh);
card.fire("mouseenter");
advance(250); assert(!shown(), "not before the wait is over");
advance(150); assert(shown(), "after about 350 ms");
sizeTip();
{
  const t = text();
  assert(t.includes(LONG_ZH), "the whole Chinese text, nothing cut");
  assert(t.includes("THE-VERY-END") && t.includes(LONG_EN), "the whole original, nothing cut");
  assert(t.includes("最後一句收尾。") && !t.includes("…"), "no ellipsis");
  assert(t.includes("要審查程式碼的時候") && t.includes("一份差異檔"), "when / needs shown");
  assert(t.includes("機器翻譯，可能不準"), "machine-translation line");
  assert(t.indexOf("原文") > t.indexOf(LONG_ZH.slice(0, 20)), "original comes under the translation");
  assert.equal(tip()[0].attrs.role, "tooltip");
  assert(tip()[0].id && card.attrs["aria-describedby"] === tip()[0].id, "aria-describedby points at the tip");
  assert(tip()[0].style.left !== undefined && tip()[0].style.top !== undefined, "placed");
}
card.fire("mouseleave"); assert(shown(), "does not vanish the instant the pointer leaves");
advance(400); assert(!shown(), "gone after leaving");
assert.equal(card.getAttribute("aria-describedby"), null, "link removed with it");

// the pointer can cross into the tip and scroll it
card.fire("mouseenter"); advance(400); assert(shown());
card.fire("mouseleave"); advance(50); tip()[0].fire("mouseenter"); advance(1000);
assert(shown(), "stays while the pointer is in the tip");
tip()[0].fire("mouseleave"); advance(400); assert(!shown(), "goes when the pointer leaves the tip");

// a quick pass over the card shows nothing
card.fire("mouseenter"); advance(100); card.fire("mouseleave"); advance(1000); assert(!shown());

// ---- 3. keyboard: focus shows, blur hides, Esc hides ----------------------------------------------------------------
{
  const btn = mk({ left: 20, top: 20, right: 220, bottom: 80 });
  wire(btn, skillZh);
  btn.fire("focusin"); assert(shown(), "focus shows it at once");
  assert.equal(btn.attrs["aria-describedby"], tip()[0].id);
  btn.fire("focusout"); assert(!shown(), "blur hides it");
  btn.fire("focusin"); assert(shown());
  const e = document.fire("keydown", { key: "Escape" });
  assert(!shown(), "Esc hides it"); assert(e.stopped, "and Esc is not passed on to a dialog while a tip was open");
  assert.equal(btn.getAttribute("aria-describedby"), null);
  const e2 = document.fire("keydown", { key: "Escape" });
  assert(!e2.stopped && !e2.prevented, "with no tip open, Esc is left alone for the dialog and the rest");
  const other = document.fire("keydown", { key: "a" }); assert(!other.stopped);
  // Esc keeps it away until the pointer comes back
  btn.fire("mouseenter"); advance(400); assert(shown()); document.fire("keydown", { key: "Escape" }); assert(!shown());
  advance(2000); assert(!shown(), "stays closed");
  // focus did not move: the tip never takes it
  assert.equal(active === tip()[0], false);
  btn.remove();
}

// ---- 4. one element for the whole page, re-used ---------------------------------------------------------------------
{
  const cards = [mk({}), mk({ left: 400 }), mk({ left: 700 })];
  cards.forEach((c, i) => wire(c, i === 1 ? skillEn : skillZh));
  const first = tip()[0];
  for (const c of cards) { c.fire("mouseenter"); advance(400); assert(shown()); c.fire("mouseleave"); advance(400); }
  assert.equal(tip().length, 1, "exactly one tooltip element in the page");
  assert.equal(tip()[0], first, "and it is the same one");
  assert.equal(walk(body).filter((n) => n.id === first.id).length, 1);
  // moving straight from one card to the next re-uses it, with the new text
  cards[0].fire("mouseenter"); advance(400); cards[0].fire("mouseleave");
  cards[1].fire("mouseenter"); advance(400);
  assert(shown() && text().includes("THE-VERY-END") && !text().includes("機器翻譯"), "now the second card's text");
  assert.equal(cards[0].getAttribute("aria-describedby"), null, "the first card no longer points at it");
  assert.equal(cards[1].attrs["aria-describedby"], first.id);
  assert.equal(tip().length, 1);
  cards[1].fire("mouseleave"); advance(400);
  cards.forEach((c) => c.remove());
}

// ---- 5. a skill without a translation shows the whole original ------------------------------------------------------
{
  const c = mk({}); wire(c, skillEn);
  c.fire("mouseenter"); advance(400);
  assert(shown());
  assert(text().includes(LONG_EN), "the whole original");
  assert(!text().includes("機器翻譯"), "no machine-translation line for something that was not translated");
  c.fire("mouseleave"); advance(400);
  // the card wizard only has `excerpt`
  const w = mk({}); wire(w, { skill_id: "s-w", name: "w", excerpt: LONG_EN });
  w.fire("mouseenter"); advance(400); assert(text().includes(LONG_EN), "excerpt is used when there is no description field");
  w.fire("mouseleave"); advance(400);
  c.remove(); w.remove();
}

// ---- 6. other cases ---------------------------------------------------------------------------------------------------
{
  // nothing to say: no box
  const c = mk({}); wire(c, skillNone);
  c.fire("mouseenter"); advance(1000); assert(!shown(), "no box when there is no text at all");
  c.fire("focusin"); assert(!shown()); c.remove();

  // text is text: markup in a description is not parsed
  const e = mk({}); wire(e, skillEvil); e.fire("mouseenter"); advance(400);
  assert(text().includes("<img src=x onerror=alert(1)>"));
  assert(!walk(tip()[0]).some((n) => n.tag === "img"), "no element made from the description");
  e.fire("mouseleave"); advance(400); e.remove();

  // a stale translation says so
  const s = mk({}); wire(s, skillStale); s.fire("mouseenter"); advance(400);
  assert(text().includes("過期的翻譯內容") && text().includes("過期") && text().includes("Stale original."));
  assert(!text().includes("原文未提供"), "a field the author left out is not shown as if it were an answer");
  s.fire("mouseleave"); advance(400); s.remove();

  // the card goes away while the box is up (a redraw, a closed dialog): the box goes too
  const g = mk({}); wire(g, skillZh); g.fire("mouseenter"); advance(400); assert(shown());
  g.remove(); advance(1000); assert(!shown(), "no box left behind when its card has left the page");
  assert.equal(g.getAttribute("aria-describedby") === null || g.getAttribute("aria-describedby") === tip()[0].id, true);

  // an explicit hide (route change) and a page scroll
  const h = mk({}); wire(h, skillZh); h.fire("mouseenter"); advance(400); assert(shown());
  run("hideSkillTip()"); assert(!shown());
  h.fire("mouseenter"); advance(400); assert(shown());
  win.fire("scroll", { target: body }); assert(!shown(), "scrolling the page puts it away");
  h.fire("mouseenter"); advance(400); assert(shown());
  win.fire("scroll", { target: tip()[0] }); assert(shown(), "scrolling inside the box does not");
  h.fire("mouseleave"); advance(400); h.remove();

  // inside a dialog the box lives in the dialog (the rest of the page is inert while it is open) and goes back to the page after
  const dialog = new Node("div"); dialog.className = "modal-backdrop"; body.append(dialog);
  const inner = new Node("button"); inner.rect = { left: 10, top: 10, right: 210, bottom: 70, width: 200, height: 60 }; dialog.append(inner);
  wire(inner, skillZh); inner.fire("mouseenter"); advance(400);
  assert(shown()); assert.equal(tip()[0].parent, dialog, "inside the dialog, so it is not inert");
  assert.equal(tip().length, 1);
  inner.fire("mouseleave"); advance(400);
  dialog.remove();
  const k = mk({}); wire(k, skillZh); k.fire("mouseenter"); advance(400);
  assert.equal(tip()[0].parent, body, "back on the page for a card outside any dialog"); assert.equal(tip().length, 1);
  k.fire("mouseleave"); advance(400); k.remove();

  // a table row: hover the description cell, keyboard on the row, described on the link
  const row = mk({}); const cell = mk({}); const link = mk({}); wire(cell, skillZh, { focus: row, describe: link });
  row.fire("focusin"); assert(shown()); assert.equal(link.attrs["aria-describedby"], tip()[0].id); assert.equal(cell.getAttribute("aria-describedby"), null);
  row.fire("focusout"); assert(!shown());
  [row, cell, link].forEach((n) => n.remove());
}

// ---- 7. wired into every place a skill description is cut short ------------------------------------------------------
assert(!/innerHTML|outerHTML|insertAdjacentHTML/.test(source.slice(source.indexOf("// ---------- skill help float"), source.indexOf("// ---------- end skill help float"))), "no innerHTML");
const section = source.slice(source.indexOf("// ---------- skill help float"), source.indexOf("// ---------- end skill help float"));
assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(section), "no emoji");
assert(!/title\s*[:=]/.test(section.replace(/\/\/.*$/gm, "")), "the native title attribute is not used");
const lib = source.slice(source.indexOf("function skillCard(s, why)"), source.indexOf("function sessionCard(x)"));
assert(/withSkillTip\(/.test(lib), "the skill library card");
const listing = source.slice(source.indexOf("const row = ({ s, why }) =>"), source.indexOf("const more = el(\"button\", { type: \"button\", class: \"btn\", style: \"margin-top:14px\""));
assert(/withSkillTip\(/.test(listing), "the skills table");
const armory = source.slice(source.indexOf("const armoryCard = el("), source.indexOf("window.scrollTo(0, 0);", source.indexOf("const armoryCard = el(")));
assert(/withSkillTip\(/.test(armory), "the four-state overview card");
const wizard = source.slice(source.indexOf("function skillCard(e) {"), source.indexOf("function drawList() {"));
assert(/withSkillTip\(/.test(wizard), "the card wizard's skill card");
assert(wizard.includes('"data-cw": "skill-full"') && wizard.includes("看完整說明"), "the 看完整說明 fold stays, for touch");
assert(/hideSkillTip\(\)/.test(source.slice(source.indexOf("async function route()"), source.indexOf("async function route()") + 400)), "a route change puts the box away");
// the card keeps its short line
assert(/class: "clamp" \}, firstSentence\(translationDescription\(s\), 170\)/.test(lib), "the card's own summary is unchanged");

// ---- 8. style ---------------------------------------------------------------------------------------------------------
const rule = (sel) => { const i = css.indexOf(sel + " {"); assert(i >= 0, `rule ${sel}`); return css.slice(i, css.indexOf("}", i)); };
const r = rule(".skill-tip");
assert(/position:\s*fixed/.test(r) && /max-width:[^;]*420px/.test(r) && /max-height:\s*60vh/.test(r) && /overflow-y:\s*auto/.test(r));
assert(/z-index:\s*(1[2-9]\d|[2-9]\d\d)/.test(r), "above the dialog backdrop (z-index 100)");
assert(/var\(--panel\)/.test(r) && /var\(--ink\)/.test(r) && !/#[0-9a-f]{3,6}\b(?![^;]*rgba)/i.test(r.replace(/box-shadow[^;]*;/, "")), "colours come from the theme variables");
assert(/@media \(prefers-reduced-motion: reduce\)[^{]*\{[^}]*\.skill-tip[^}]*animation:\s*none/.test(css), "no animation under reduced motion");
assert(!/https?:\/\//.test(r), "no external resource");
console.log("ok skill hover box: whole text, keyboard, Esc, one element, placement inside the window");
