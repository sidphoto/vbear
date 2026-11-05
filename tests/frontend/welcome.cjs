// The "first time you open VBear" page (task 8): shown once, only in the app window, before the start-up page; it can be skipped;
// once read or skipped it does not come again; a browser never gets it. Its picture is drawn by the page itself (an
// illustration, not a screenshot of anyone's settings). The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/welcome.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const attr = (n, k) => n.getAttribute && n.getAttribute(k);
const byAttr = (root, k, v) => root.findAll((n) => attr(n, k) === v);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const ROOT = path.join(__dirname, "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- the first-time page"), SRC.indexOf("// ---------- the start-up page"));

const asApp = () => { global.window.webkit = { messageHandlers: { vbearPickFolder: { postMessage() {} } } }; };
const asBrowser = () => { delete global.window.webkit; };

let calls;
let saveFails = false;
function setPage(config) {
  calls = [];
  const tools = ["claude", "codex", "agy", "grok"].map((id) => ({ id, name: id, short: id, blurb: "", hidden: false, installed: false, version: null,
    install_problem: "not_found", login_by: "mark", login: "not_marked", can_mark: true, marked_at: null, state: "not_installed", ready: false, login_regions: [] }));
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body]);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/setup/tools") return jsonResponse({ ok: true, any_ready: false, setup_done: false, tools });
    if (p === "/api/setup/daily-limit") return jsonResponse({ ok: true, daily_usd: 3, choices: [1, 3, 10] });
    if (p === "/api/setup/settle") return jsonResponse({ ok: true, setup_done: false, setup_notice: false, upgraded: false });
    if (p === "/api/config" && method === "POST") return saveFails ? jsonResponse({ error: "boom" }, false, 500) : jsonResponse({ ok: true, config: body });
    if (p === "/api/config") return jsonResponse({ ok: true, config });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true });
    return null;
  });
}
async function open(hash) {
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const click = async (node) => { node.dispatch("click"); await settle(); };
const saved = () => calls.filter((c) => c[0] === "POST" && c[1] === "/api/config").map((c) => c[2]);

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("the app window, first time, nothing finished: the home page sends the person to the first-time page, not yet to the start-up", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: false, onboarding_dismissed: true });
  await open("#/");
  assert.strictEqual(global.location.hash, "#/welcome");
});

test("the page explains the block in plain words and has the steps in order", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: false });
  const main = await open("#/welcome");
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "第一次打開 VBear");
  const t = text(main);
  for (const w of ["系統設定", "隱私權與安全性", "強制打開", "Apple", "病毒"]) assert(t.includes(w), w);
  const steps = byAttr(main, "data-welcome", "step");
  assert(steps.length >= 3 && steps.length <= 5, String(steps.length));
  const joined = steps.map(text);
  assert(joined.findIndex((s) => s.includes("隱私權與安全性")) < joined.findIndex((s) => s.includes("強制打開")), "the button comes after the page it is on");
});

test("the picture is drawn by the page, says it is an illustration and marks where the button is", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: false });
  const main = await open("#/welcome");
  const fig = byAttr(main, "data-welcome", "diagram")[0];
  assert(fig, "a diagram");
  assert(/示意圖/.test(attr(fig, "aria-label") || "") && attr(fig, "role") === "img");
  assert(text(fig).includes("強制打開") && text(fig).includes("隱私權與安全性"));
  const mark = byAttr(fig, "data-welcome", "mark-button")[0];
  assert(mark && text(mark).includes("強制打開"), "the button is pointed at");
  const cap = byAttr(main, "data-welcome", "diagram-note")[0];
  assert(cap && /示意圖/.test(text(cap)) && /不是你電腦的真實畫面/.test(text(cap)), "said to be an illustration, not a screenshot");
  assert(main.findAll((n) => n.tag === "img").length === 0, "no picture file, no outside image");
});

test("skipping saves that it was seen and goes on to the start-up", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: false });
  const main = await open("#/welcome");
  const skip = byAttr(main, "data-welcome", "skip")[0];
  assert(skip && text(skip) === "略過");
  await click(skip);
  assert.deepStrictEqual(saved(), [{ welcome_seen: true }]);
  assert.strictEqual(global.location.hash, "#/setup");
});

test("reading it and going on saves the same mark and goes to the start-up", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: false });
  const main = await open("#/welcome");
  const next = byAttr(main, "data-welcome", "next")[0];
  assert(next && /開始設定/.test(text(next)));
  await click(next);
  assert.deepStrictEqual(saved(), [{ welcome_seen: true }]);
  assert.strictEqual(global.location.hash, "#/setup");
});

test("a save that fails does not trap the person: they still go on, and are told it may come again", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: false });
  const main = await open("#/welcome");
  saveFails = true;
  try { await click(byAttr(main, "data-welcome", "skip")[0]); } finally { saveFails = false; }
  assert.strictEqual(global.location.hash, "#/setup");
  assert(/下次/.test(text(h.dom().toastEl || realGetById("toast"))), "told in the toast");
});

test("after it was seen the home page goes straight to the start-up", async () => {
  asApp();
  setPage({ setup_done: false, welcome_seen: true, onboarding_dismissed: true });
  await open("#/");
  assert.strictEqual(global.location.hash, "#/setup");
});

test("a browser never gets it, whatever the mark says", async () => {
  asBrowser();
  setPage({ setup_done: false, welcome_seen: false, onboarding_dismissed: true });
  await open("#/");
  assert.strictEqual(global.location.hash, "#/setup");
  await open("#/welcome");
  assert.strictEqual(global.location.hash, "#/setup", "even when opened by hand");
  assert.deepStrictEqual(saved(), []);
});

test("the server saying nothing about the mark forces nothing (no welcome_seen key: the start-up as before)", async () => {
  asApp();
  setPage({ setup_done: false, onboarding_dismissed: true });
  await open("#/");
  assert.strictEqual(global.location.hash, "#/setup");
});

test("a person who finished the start-up, or who has a ready tool, is not shown it", async () => {
  asApp();
  setPage({ setup_done: true, welcome_seen: false, onboarding_dismissed: true });
  await open("#/");
  assert.strictEqual(global.location.hash, "#/");
});

test("the wording helper: only the app window, only while the mark is false", () => {
  asApp();
  assert.strictEqual(app.welcomeWanted({ config: { welcome_seen: false } }), true);
  assert.strictEqual(app.welcomeWanted({ config: { welcome_seen: true } }), false);
  assert.strictEqual(app.welcomeWanted({ config: {} }), false);
  assert.strictEqual(app.welcomeWanted(null), false);
  asBrowser();
  assert.strictEqual(app.welcomeWanted({ config: { welcome_seen: false } }), false);
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, no word a first-time person cannot read", () => {
  assert(BLOCK.length > 1500, "the block is found");
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/\p{Extended_Pictographic}/u.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/<img|url\(|\.png|\.jpg/.test(BLOCK));
  const strings = (BLOCK.match(/"[^"\n]*[一-鿿][^"\n]*"|`[^`\n]*[一-鿿][^`\n]*`/g) || []).join("\n");
  assert(!/\bCLI\b|argv|\bPATH\b|Gatekeeper|quarantine/.test(strings));
});

test("style: the picture follows the theme variables, wraps on a narrow screen and has no outside resource", () => {
  const css = fs.readFileSync(path.join(ROOT, "web", "style.css"), "utf8");
  const part = css.slice(css.indexOf("/* the first-time page"), css.indexOf("/* the start-up page"));
  assert(part.length > 300);
  for (const sel of [".welcome-diagram", ".welcome-steps", ".welcome-mark"]) assert(part.includes(sel), sel);
  assert(!/#[0-9a-fA-F]{3,6}\b/.test(part), "colours come from the theme variables");
  assert(/@media \(max-width: 520px\)/.test(part));
  assert(!/url\(|@import|https?:\/\//.test(part));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
