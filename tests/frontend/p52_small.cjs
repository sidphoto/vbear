// P52-3 (v0.25.0): three small things of the settings page and the team-template dialogs (#104).
//   1. the settings page: 「用量與上限」 is above 「通知」;
//   2. 存成團隊範本: its name box has the site's input style, and at 400px the dialog's content scrolls while the button row stays at the bottom (wrapping);
//   3. the preview dialog's bottom bar leaves nothing of the content showing under it (the box's own bottom padding was what showed).
// The real web/app.js on a synthetic DOM, fetch answered by the test; the CSS is read as text. Not a browser test: the pixels are for a person to look at.
// Run: node tests/frontend/p52_small.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler } = h;

const ROOT = path.join(__dirname, "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const attr = (n, k) => n.getAttribute && n.getAttribute(k);
const by = (root, key, value) => root.find((n) => attr(n, key) === value);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const NOW = { cards: [{ id: "prof-aaaaaaaaaaaa", name: "虛構會計", position: "accountant", tool: "claude", can_chat: true }], skills: [], routines: [] };
function server() {
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [], sources: [], facts: {}, problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/waiting") return jsonResponse({ waiting: [] });
    if (p === "/api/settings/autonomy") return jsonResponse({ autonomy: {}, items: [], never: [] });
    if (p === "/api/meetings/ledger") return jsonResponse({ spent_usd: "0.42", daily_usd: 3, lamp: "green" });
    if (p === "/api/setup/daily-limit") return jsonResponse({ daily_usd: 3 });
    if (p === "/api/templates") {
      return jsonResponse({ ok: true, builtin: [], mine: [], mine_readable: true, problems: [], applies: [], counts: { cards: 1, skills: 0, routines: 0 }, current: NOW,
        limits: { max_mine: 20, max_name: 40, per_template: { cards: 12, skills: 24, routines: 12 }, per_apply: { cards: 12, skills: 24, routines: 12 } },
        tools: { claude: { ready: true, why: "" }, codex: { ready: true, why: "" }, default: "claude" } });
    }
    return null;
  });
}
async function open(hash) {
  const real = global.setInterval; global.setInterval = () => 0; global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const CSS_PLAIN = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = () => [...CSS_PLAIN.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ selectors: m[1].split(",").map((s) => s.trim()), body: m[2] }));
const bodyOf = (re) => rules().filter((r) => r.selectors.some((s) => re.test(s))).map((r) => r.body).join(";");

const tests = [], test = (n, f) => tests.push([n, f]);

test("1. settings: 「用量與上限」 comes before 「通知」", async () => {
  server();
  const main = await open("#/settings");
  const order = main.children.map((n) => (n && n.getAttribute ? attr(n, "data-settings") : null));
  const limits = order.indexOf("limits"), notify = order.indexOf("notify");
  assert.ok(limits >= 0 && notify >= 0, JSON.stringify(order));
  assert.ok(limits < notify, `limits at ${limits}, notify at ${notify}`);
});

test("2. 存成團隊範本: the name box has the input class, and the dialog scrolls inside while its button row stays", async () => {
  server();
  await open("#/templates");
  const box = h.dom().mainEl.find((n) => attr(n, "data-tpl-now") === "cards");
  assert.ok(box, "a ticked row to save");
  box.checked = true; box.dispatch("change"); await settle();
  const save = h.dom().mainEl.find((n) => n.tag === "button" && attr(n, "data-tpl-action") === "save-now");
  save.dispatch("click"); await settle();
  const dlg = h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop"))[0];
  assert.ok(dlg && attr(dlg, "data-templates") === "save");
  const name = by(dlg, "data-tpl-save", "name");
  assert.ok(name.hasClass("input"), "the site's input style");
  const modalBox = dlg.find((n) => n.hasClass && n.hasClass("modal-box"));
  assert.ok(modalBox.hasClass("tpl-dialog"), "its own layout class");
  const foot = by(dlg, "data-templates", "save-foot");
  const css = bodyOf(/data-templates="save-foot"/);
  assert.ok(/position\s*:\s*sticky/.test(css) && /bottom\s*:\s*0/.test(css) && /background\s*:/.test(css) && /flex-wrap\s*:\s*wrap/.test(css), `save-foot: ${css}`);
  assert.ok(foot, "the foot is there");
});

test("3. the dialogs' bottom bar leaves nothing under it: the box has no bottom padding of its own (the bar has the padding), for the save, preview and undo dialogs", () => {
  const css = bodyOf(/^\.modal-box\.tpl-dialog$/);
  assert.ok(/padding-bottom\s*:\s*0/.test(css), `.tpl-dialog: ${css}`);
  const bar = bodyOf(/data-templates="preview-foot"/);
  assert.ok(/position\s*:\s*sticky/.test(bar) && /padding-block\s*:\s*\d+px/.test(bar), bar);
  for (const key of ["save-foot", "preview-foot", "undo-foot"]) {
    const part = bodyOf(new RegExp(`data-templates="${key}"`));
    assert.ok(/position\s*:\s*sticky/.test(part), `${key} is sticky`);
  }
  for (const fn of ["function openTemplatesSave(", "function openTemplatesPreview(", "function openTemplatesUndo("]) {
    const from = SRC.indexOf(fn); assert.ok(from > 0, fn);
    const part = SRC.slice(from, from + 1800);
    assert.ok(/class: "modal-box tpl-dialog"/.test(part), `${fn} uses the layout class`);
  }
});

test("3. at 400px the buttons wrap instead of running off the screen (the bar may wrap; its buttons may not be wider than the box)", () => {
  const wrap = bodyOf(/\.tpl-dialog \.modal-actions|data-templates="save-foot"/);
  assert.ok(/flex-wrap\s*:\s*wrap/.test(wrap), wrap);
  const btn = bodyOf(/\.tpl-dialog \.modal-actions \.btn|\.tpl-dialog \.btn/);
  assert.ok(/max-width\s*:\s*100%/.test(btn), btn);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) { try { await fn(); console.log("ok - " + name); } catch (e) { failed++; console.log("FAIL - " + name + "\n" + e.stack); } }
  console.log(`${tests.length - failed}/${tests.length} passed`); process.exit(failed ? 1 : 0);
})();
