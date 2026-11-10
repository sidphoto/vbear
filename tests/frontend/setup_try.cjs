// 「試一下」 on the start-up page (task 4): the button is on the installed tools only; the first press shows "about under US$0.01"
// and asks again, nothing is sent before the second press; while it runs the card says so and the page stops asking; the result
// is plain words (success, not logged in, timed out, not found, odd answer, refused for the day's limit); the page looks again,
// forced, afterwards; entering the page and 「重新檢查」 are forced looks, the quiet refresh is not.
// The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/setup_try.cjs   (exit code 0 = pass)
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

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- the start-up page"), SRC.indexOf("// ---------- chat with role cards"));

function row(id, over = {}) {
  const names = { claude: "Claude Code", codex: "Codex CLI", agy: "Antigravity（AGY）", grok: "Grok" };
  const byStatus = id === "claude" || id === "codex";
  return { id, name: names[id], short: names[id], blurb: `${names[id]} 是誰家的。`, hidden: false, installed: false, version: null,
    install_problem: "not_found", login_by: byStatus ? "status" : "mark", login: byStatus ? "unknown" : "not_marked", can_mark: !byStatus,
    marked_at: null, state: "not_installed", ready: false, login_regions: [], ...over };
}
const installed = (id, over = {}) => row(id, { installed: true, version: "1.2.3", install_problem: "", state: "not_logged_in",
  login: id === "claude" || id === "codex" ? "not_logged_in" : "not_marked", ...over });

let page, calls, tryReply;
function setPage(over = {}) {
  // P48-1: the chosen tool (here Codex, which this file does not try) has the new one-button check (p48_setup.cjs); the old 「試一下」 of every other tool is
  // the one under 「其他 AI 工具」, which is what this file is about.
  global.localStorage._store = { "vbear-setup-pick": "codex" };
  page = { tools: [installed("claude"), row("codex"), installed("agy"), installed("grok")], setup_done: true, ...over };
  calls = [];
  tryReply = () => jsonResponse({ ok: true, tool: "agy", success: true, result: "success", message: "Antigravity（AGY）回應了，這個 AI 工具可以用。", spent_usd: "0.01" });
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body, url.includes("?") ? url.split("?")[1] : ""]);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/setup/tools" && method === "GET") return jsonResponse({ ok: true, any_ready: page.tools.some((t) => t.ready), ...page });
    if (p.startsWith("/api/setup/tools/") && p.endsWith("/try")) return tryReply(p.split("/")[4], body);
    if (p === "/api/config") return jsonResponse({ ok: true, config: {} });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true });
    return null;
  });
}
let tick = null;
async function open(hash) {
  const realSetInterval = global.setInterval;
  tick = null;
  global.setInterval = (fn) => { tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const cardOf = (main, id) => main.findAll((n) => attr(n, "data-tool") === id)[0];
const tryBox = (card) => byAttr(card, "data-setup", "try")[0];
const tryBtn = (card, key) => byAttr(card, "data-setup-try-act", key)[0];
const click = async (node) => { node.dispatch("click"); await settle(); };
const tryCalls = () => calls.filter((c) => c[1].endsWith("/try"));
const toolGets = () => calls.filter((c) => c[1] === "/api/setup/tools" && c[0] === "GET");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("setupTryView: only an installed tool has it; idle, asking again, running and the results each say their part", () => {
  assert.strictEqual(app.setupTryView(row("agy"), undefined).show, false, "not installed: no button");
  let v = app.setupTryView(installed("agy"), undefined);
  assert.strictEqual(v.show, true);
  assert.deepStrictEqual(v.buttons.map((b) => [b.key, b.label]), [["try", "試一下"]]);
  assert(/大約花不到 US\$0\.01/.test(v.note), "the estimate is on the page before anything is pressed");
  v = app.setupTryView(installed("agy"), { phase: "confirm" });
  assert.deepStrictEqual(v.buttons.map((b) => b.key), ["try-confirm", "try-cancel"]);
  assert(/大約花不到 US\$0\.01/.test(v.note) && /花費上限/.test(v.note));
  v = app.setupTryView(installed("agy"), { phase: "running" });
  assert.deepStrictEqual(v.buttons, []);
  assert(/正在試/.test(v.note));
  v = app.setupTryView(installed("agy"), { phase: "done", success: true, message: "好了" });
  assert.deepStrictEqual([v.result.text, v.result.ok], ["好了", true]);
  assert.deepStrictEqual(v.buttons.map((b) => b.key), ["try"], "again is one press, then the estimate and the question again");
  v = app.setupTryView(installed("agy"), { phase: "done", success: false, message: "看起來還沒登入" });
  assert.strictEqual(v.result.ok, false);
});

test("the button is on the installed tools and not on the others", async () => {
  setPage();
  const main = await open("#/setup");
  assert.deepStrictEqual(["claude", "codex", "agy", "grok"].map((id) => !!tryBtn(cardOf(main, id), "try")), [true, false, true, true]);
  const slot = byAttr(cardOf(main, "agy"), "data-setup-slot", "try")[0];
  assert(slot && tryBox(slot), "it sits in the place the start-up page kept for it");
});

test("the first press shows the estimate and sends nothing; cancel puts it back; the second press sends the confirmation", async () => {
  setPage();
  const main = await open("#/setup");
  await click(tryBtn(cardOf(main, "agy"), "try"));
  assert.deepStrictEqual(tryCalls(), [], "nothing was sent by the first press");
  assert(text(tryBox(cardOf(main, "agy"))).includes("大約花不到 US$0.01"));
  assert(tryBtn(cardOf(main, "agy"), "try-confirm") && !tryBtn(cardOf(main, "agy"), "try"));
  await click(tryBtn(cardOf(main, "agy"), "try-cancel"));
  assert.deepStrictEqual(tryCalls(), []);
  assert(tryBtn(cardOf(main, "agy"), "try"));
  await click(tryBtn(cardOf(main, "agy"), "try"));
  await click(tryBtn(cardOf(main, "agy"), "try-confirm"));
  assert.deepStrictEqual(tryCalls().map((c) => [c[0], c[1], c[2]]), [["POST", "/api/setup/tools/agy/try", { confirmed: true }]]);
});

test("a success says so in plain words; a failure shows the server's plain reason; a refusal for the day's limit is shown as it is", async () => {
  setPage();
  let main = await open("#/setup");
  const press = async (id) => { await click(tryBtn(cardOf(main, id), "try")); await click(tryBtn(cardOf(main, id), "try-confirm")); };
  await press("agy");
  let box = tryBox(cardOf(main, "agy"));
  assert(text(box).includes("回應了，這個 AI 工具可以用"));
  assert.strictEqual(attr(byAttr(box, "data-setup", "try-result")[0], "data-ok"), "yes");
  tryReply = () => jsonResponse({ ok: true, success: false, result: "not_logged_in", message: "Grok 沒有成功回應，看起來還沒登入。請先按「登入」，登入好了再試一次。" });
  await press("grok");
  box = tryBox(cardOf(main, "grok"));
  assert(text(box).includes("看起來還沒登入"));
  assert.strictEqual(attr(byAttr(box, "data-setup", "try-result")[0], "data-ok"), "no");
  tryReply = () => jsonResponse({ error: "今天已花 US$3，再試一次可能超過每天上限 US$3，所以今天不能再試了。" }, false, 409);
  await press("claude");
  assert(text(tryBox(cardOf(main, "claude"))).includes("所以今天不能再試了"));
  tryReply = () => jsonResponse({ ok: true, success: false, result: "timeout", message: "等了 60 秒，Grok 都沒有回應。" });
  await press("grok");
  assert(text(tryBox(cardOf(main, "grok"))).includes("等了 60 秒"));
  assert(tryBtn(cardOf(main, "grok"), "try"), "and it can be tried again");
});

test("while it runs the card says so, no second press is possible and the page stops asking; afterwards it looks again, forced", async () => {
  setPage();
  const main = await open("#/setup");
  let release;
  tryReply = () => new Promise((resolve) => { release = () => resolve(jsonResponse({ ok: true, success: true, result: "success", message: "好了", spent_usd: "0.01" })); });
  await click(tryBtn(cardOf(main, "agy"), "try"));
  await click(tryBtn(cardOf(main, "agy"), "try-confirm"));
  let card = cardOf(main, "agy");
  assert(text(tryBox(card)).includes("正在試"));
  assert(!tryBtn(card, "try") && !tryBtn(card, "try-confirm"), "nothing to press again");
  const before = toolGets().length;
  await tick(); await settle();
  assert.strictEqual(toolGets().length, before, "the quiet refresh does not run while a try is out");
  assert.strictEqual(tryCalls().length, 1);
  release(); await settle();
  card = cardOf(main, "agy");
  assert(text(tryBox(card)).includes("好了"));
  const gets = toolGets();
  assert.strictEqual(gets.length, before + 1);
  assert.strictEqual(gets[gets.length - 1][3], "force=1", "the look after a try is a fresh one");
});

test("the result stays when the page is redrawn by a refresh", async () => {
  setPage();
  const main = await open("#/setup");
  await click(tryBtn(cardOf(main, "agy"), "try"));
  await click(tryBtn(cardOf(main, "agy"), "try-confirm"));
  page.tools = [installed("claude"), row("codex"), installed("agy", { version: "9.9.9" }), installed("grok")];
  await tick(); await settle();
  assert(text(cardOf(main, "agy")).includes("9.9.9"), "redrawn");
  assert(text(tryBox(cardOf(main, "agy"))).includes("回應了"), "and the result is still there");
});

test("coming into the page and 「重新檢查」 look again for real; the quiet refresh may use what the server kept", async () => {
  setPage();
  const main = await open("#/setup");
  assert.strictEqual(toolGets()[0][3], "force=1", "entering the page");
  await tick(); await settle();
  assert.strictEqual(toolGets()[1][3], "", "the quiet refresh");
  await click(byAttr(main, "data-setup", "recheck")[0]);
  assert.strictEqual(toolGets()[2][3], "force=1", "the recheck button");
});

test("a tool that stops being installed loses its button on the next look", async () => {
  setPage();
  const main = await open("#/setup");
  assert(tryBtn(cardOf(main, "agy"), "try"));
  page.tools = [installed("claude"), row("codex"), row("agy"), installed("grok")];
  await tick(); await settle();
  assert(!tryBtn(cardOf(main, "agy"), "try"));
});

test("source: the estimate is written once in the page's words, the model's reply is not a thing the page knows, no innerHTML, no emoji", () => {
  assert(BLOCK.includes("大約花不到 US$0.01"));
  assert(/data-setup-slot/.test(BLOCK));
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/\p{Extended_Pictographic}/u.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/\.reply|\.output|\.stdout|\.text\b/.test(BLOCK.slice(BLOCK.indexOf("function setupTryView"), BLOCK.indexOf("function setupTryView") + 2500)),
    "the view reads the plain message of the server only");
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
