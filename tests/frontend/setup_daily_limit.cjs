// The choice of the daily limit on the start-up page: three options (US$1, US$3 the default, US$10) each with one plain
// sentence, what a click sends, and the result the person sees afterwards. The real web/app.js on a synthetic DOM, fetch
// answered by the test.
// Run: node tests/frontend/setup_daily_limit.cjs   (exit code 0 = pass)
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
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- the start-up page"), SRC.indexOf("// ---------- chat with role cards"));

const tool = (id) => ({ id, name: id, short: id, blurb: `${id} 一句說明。`, hidden: false, installed: true, version: "1.0.0", install_problem: "",
  login_by: "status", login: "logged_in", can_mark: false, marked_at: null, state: "ready", ready: true, login_regions: [] });

let state;
let calls;
function setServer(over = {}) {
  state = { daily: 3, post: null, getFails: false, ...over };
  calls = [];
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
    if (p === "/api/setup/tools") return jsonResponse({ ok: true, any_ready: true, setup_done: true, tools: ["claude", "codex", "agy", "grok"].map(tool) });
    if (p === "/api/setup/daily-limit" && method === "GET") {
      return state.getFails ? jsonResponse({ error: "壞了" }, false, 500) : jsonResponse({ ok: true, daily_usd: state.daily, choices: [1, 3, 10] });
    }
    if (p === "/api/setup/daily-limit" && method === "POST") {
      if (state.post) return state.post(body);
      state.daily = body.daily_usd;
      return jsonResponse({ ok: true, daily_usd: body.daily_usd, changed: [] });
    }
    if (p === "/api/config") return jsonResponse({ ok: true, config: {} });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    return null;
  });
}
async function open() {
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = "#/setup";
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const section = (main) => main.find((n) => attr(n, "data-setup-slot") === "daily-limit");
const choices = (main) => section(main).findAll((n) => ["1", "3", "10"].includes(attr(n, "data-daily-choice")));
const choiceButton = (main, v) => section(main).find((n) => attr(n, "data-daily-pick") === String(v));
const click = async (node) => { node.dispatch("click"); await settle(); };
const posts = () => calls.filter((c) => c[0] === "POST" && c[1] === "/api/setup/daily-limit");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("the page offers US$1, US$3 and US$10, in that order, each with a sentence of what it is about enough for", async () => {
  setServer();
  const main = await open();
  const rows = choices(main);
  assert.deepStrictEqual(rows.map((r) => attr(r, "data-daily-choice")), ["1", "3", "10"]);
  assert.deepStrictEqual(rows.map((r) => text(choiceButton(main, attr(r, "data-daily-choice")))).map((t) => t.replace(/（預設）/, "")), ["US$1", "US$3", "US$10"]);
  for (const r of rows) {
    const note = r.find((n) => attr(n, "data-daily-note") !== null && attr(n, "data-daily-note") !== undefined && attr(n, "data-daily-note") !== false);
    assert(note && text(note).length > 12, "a sentence next to every option: " + text(r));
    assert(/聊天/.test(text(note)) && /會議/.test(text(note)), "in terms of chat turns and meetings: " + text(note));
    assert(/最多|最壞|上限/.test(text(note)), "says it is the most, not a promise: " + text(note));
  }
  assert.strictEqual(section(main).tag, "details");
  assert.strictEqual(attr(section(main), "open"), null, "folded by default");
  assert(text(main).includes("之後隨時可以從「設定」的「AI 工具」回到這一頁"));
  assert(/每天/.test(text(section(main))) && /0 點/.test(text(section(main))), "says what the day is");
  assert(/設定/.test(text(section(main))), "says it can be changed later in the settings");
});

test("the default is US$3: it is marked as the default and is the one selected while the server says 3", async () => {
  setServer({ daily: 3 });
  const main = await open();
  assert(text(choiceButton(main, 3)).includes("預設"));
  assert(!text(choiceButton(main, 1)).includes("預設") && !text(choiceButton(main, 10)).includes("預設"));
  const sel = choices(main).filter((r) => attr(r, "data-selected") === "true").map((r) => attr(r, "data-daily-choice"));
  assert.deepStrictEqual(sel, ["3"]);
  assert.strictEqual(attr(choiceButton(main, 3), "aria-pressed"), "true");
  assert.strictEqual(attr(choiceButton(main, 1), "aria-pressed"), "false");
  assert.strictEqual(posts().length, 0, "looking at the page writes nothing");
});

test("the selected option follows what the server has; a number that is none of the three selects none and is said", async () => {
  setServer({ daily: 10 });
  let main = await open();
  assert.deepStrictEqual(choices(main).filter((r) => attr(r, "data-selected") === "true").map((r) => attr(r, "data-daily-choice")), ["10"]);
  setServer({ daily: 2.5 });
  main = await open();
  assert.strictEqual(choices(main).filter((r) => attr(r, "data-selected") === "true").length, 0);
  assert(text(section(main)).includes("US$2.5"), "the number in force is shown");
});

test("choosing stages the number; Save sends only the number, once, and shows the result", async () => {
  setServer({ daily: 3 });
  const main = await open();
  await click(choiceButton(main, 10));
  assert.strictEqual(posts().length, 0);
  await click(section(main).find((n) => attr(n, "data-limit-save") === ""));
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ daily_usd: 10 }]);
  const result = section(main).find((n) => attr(n, "data-setup") === "daily-result");
  assert(result, "the result is shown");
  assert(text(result).includes("US$10"), text(result));
  assert(/沒有|不用|本來就/.test(text(result)), "says nothing else had to change: " + text(result));
  assert.deepStrictEqual(choices(main).filter((r) => attr(r, "data-selected") === "true").map((r) => attr(r, "data-daily-choice")), ["10"]);
});

test("the result names each limit that was brought down, with the number before and after", async () => {
  setServer({
    post: () => jsonResponse({ ok: true, daily_usd: 1, changed: [
      { limit: "meeting_usd", from: 1.5, to: 1 }, { limit: "staffing_total_usd", from: 2, to: 1 },
      { limit: "per_call_usd", from: 0.2, to: 0.2 }, { limit: "chat_per_turn_usd", from: 4, to: 1 }] }),
  });
  const main = await open();
  await click(choiceButton(main, 1));
  assert.strictEqual(posts().length, 0);
  await click(section(main).find((n) => attr(n, "data-limit-save") === ""));
  const t = text(section(main).find((n) => attr(n, "data-setup") === "daily-result"));
  assert(t.includes("US$1"), t);
  assert(/每場會議[^，。；]*US\$1\.5[^，。；]*US\$1/.test(t), t);
  assert(/組隊[^，。；]*US\$2[^，。；]*US\$1/.test(t), t);
  assert(/聊天[^，。；]*US\$4[^，。；]*US\$1/.test(t), t);
  assert(!/limit|usd|_usd/.test(t), "no key names in the words: " + t);
  assert(/調低/.test(t));
});

test("a refusal from the server is shown in its words, nothing is called done, and the selection stays where it was", async () => {
  setServer({ daily: 3, post: () => jsonResponse({ error: "每天上限沒有存進去：磁碟寫不進去" }, false, 503) });
  const main = await open();
  await click(choiceButton(main, 1));
  assert.strictEqual(posts().length, 0);
  await click(section(main).find((n) => attr(n, "data-limit-save") === ""));
  const err = section(main).find((n) => attr(n, "data-setup") === "daily-error");
  assert(err && text(err).includes("磁碟寫不進去"), err && text(err));
  assert(!section(main).find((n) => attr(n, "data-setup") === "daily-result"));
  assert.deepStrictEqual(choices(main).filter((r) => attr(r, "data-selected") === "true").map((r) => attr(r, "data-daily-choice")), ["3"]);
  assert.strictEqual(posts().length, 1);
});

test("when the number in force cannot be read, the options are still there and nothing is shown as chosen", async () => {
  setServer({ getFails: true });
  const main = await open();
  assert.strictEqual(choices(main).length, 3);
  assert.strictEqual(choices(main).filter((r) => attr(r, "data-selected") === "true").length, 0);
  assert(/讀不到/.test(text(section(main))));
});

test("source: the section is built with el(), no innerHTML, no emoji, no outside resource", () => {
  assert(/daily-limit/.test(BLOCK) && /\/api\/setup\/daily-limit/.test(BLOCK));
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/\p{Extended_Pictographic}/u.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
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
