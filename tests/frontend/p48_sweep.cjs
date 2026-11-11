// P48-6 (v0.22.0): the small things left over from v0.21.0.
//   1. a request that never reached the server (the browser's own "Failed to fetch", WebKit's "Load failed", Firefox's "NetworkError ...") is said in plain words;
//   2. the look of the page: every tick box is 18px (also inside .switch), the name box of the team-template preview has the .input style, and the
//      bottom bar of that dialog stays in view (sticky) when the dialog scrolls.
// The words of the settings page (資料流向, the summary of the limits), the team-template preview and the translation line are tested where those
// pages are tested: tests/frontend/p47_settings.cjs, templates.cjs, translations.cjs. Not a browser test; nothing here reaches a network.
//
// Run: node tests/frontend/p48_sweep.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app } = h;

const ROOT = path.join(__dirname, "..", "..");
const CSS = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");
const tests = [], test = (n, f) => tests.push([n, f]);

const SERVER_LOST = "連不上 VBear 的伺服器，可能剛關掉或正在重新啟動。等一下再重新整理。";

test("1. the browser's words for a lost server become one plain sentence, the original kept whole in the detail", () => {
  for (const raw of ["Failed to fetch", "Load failed", "NetworkError when attempting to fetch resource.", "NetworkError when attempting to fetch resource", "TypeError: Failed to fetch", "  load failed "]) {
    const w = app.plainWords(raw);
    assert.strictEqual(w.known, true, raw);
    assert.strictEqual(w.text + w.next, SERVER_LOST, raw);
    assert.strictEqual(w.detail, raw.trim(), raw);
    assert.strictEqual(app.plainLine(raw), `${SERVER_LOST}（原文：${raw.trim()}）`, raw);
  }
  const err = app.plainWords(new Error("Failed to fetch"));
  assert.strictEqual(err.text + err.next, SERVER_LOST, "an Error carries the same words");
});

test("1. only those exact sentences: a longer sentence that happens to contain them, or another failure, is shown as it is", () => {
  for (const raw of ["Failed to fetch dynamically imported module: x.js", "Load failed because the disk is full", "NetworkError", "HTTP 500", "資料夾讀不到", ""]) {
    const w = app.plainWords(raw);
    assert.strictEqual(w.known, false, raw);
    assert.strictEqual(w.text, raw);
  }
});

const rules = () => Array.from(CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)).map((m) => ({ selectors: m[1].split(",").map((x) => x.trim().replace(/^\/\*[\s\S]*?\*\/\s*/, "")), body: m[2] }));
const ruleOf = (selector) => rules().filter((r) => r.selectors.includes(selector));
const px = (body, prop) => { const m = new RegExp(`(?:^|[;\\s])${prop}\\s*:\\s*(\\d+)px`).exec(body); return m ? Number(m[1]) : null; };

test("2. every tick box is 18px, also inside .switch (no other size is left for a tick box)", () => {
  const all = ruleOf('input[type="checkbox"]');
  assert(all.length >= 1, "a rule for every tick box");
  assert(all.some((r) => px(r.body, "width") === 18 && px(r.body, "height") === 18), "18px wide and high");
  assert(all.some((r) => /flex\s*:\s*none/.test(r.body)), "it is not squeezed in a flex row");
  for (const r of rules().filter((x) => x.selectors.some((s) => /(^|\s)\.switch\s+input(?![\w\[])/.test(s) && !/radio/.test(s)))) {
    for (const prop of ["width", "height"]) assert(px(r.body, prop) === null || px(r.body, prop) === 18, `.switch input ${prop}: ${r.body}`);
  }
  const sizes = rules().filter((r) => r.selectors.some((s) => /checkbox/.test(s)) && (px(r.body, "width") !== null));
  for (const r of sizes) assert.strictEqual(px(r.body, "width"), 18, `${r.selectors.join(",")}`);
});

test("2. the name box of the team-template preview is in the .input style (a border, a background, the page's own font)", () => {
  const r = ruleOf(".modal-box .input").concat(ruleOf(".tpl-list .input"));
  assert(r.length >= 1, "a rule for .input in the preview");
  const body = r.map((x) => x.body).join(";");
  assert(/border\s*:/.test(body) && /background\s*:/.test(body) && /font\s*:\s*inherit/.test(body), body);
});

test("2. the bottom bar of the preview dialog stays in view: sticky at the bottom with its own background", () => {
  const r = rules().filter((x) => x.selectors.some((s) => /data-templates="preview-foot"/.test(s)));
  assert(r.length >= 1, "a rule for the foot of the preview");
  const body = r.map((x) => x.body).join(";");
  assert(/position\s*:\s*sticky/.test(body) && /bottom\s*:/.test(body) && /background\s*:/.test(body), body);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) { try { await fn(); console.log("ok - " + name); } catch (e) { failed++; console.log("FAIL - " + name + "\n" + e.stack); } }
  console.log(`${tests.length - failed}/${tests.length} passed`); process.exit(failed ? 1 : 0);
})();
