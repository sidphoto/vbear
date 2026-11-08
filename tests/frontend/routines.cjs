// P44-2: the 例行工作 page (#/routines), the line over every page for what waits for the person, the routine rows of
// 「AI 自己做了什麼」 and the routine title of a chat in the list. The real web/app.js on a synthetic DOM, fetch answered by the test;
// every name and text here is made up and the page shows them as text only.
// Run: node tests/frontend/routines.cjs   (exit code 0 = pass)
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
const BLOCK = SRC.slice(SRC.indexOf("// ---------- routines (v0.18, P44-2)"), SRC.indexOf("// ---------- end of routines"));
const HTML = fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8");

const ROUTINE = {
  id: "r-0123456789ab", name: "市集日報", profile_id: "p-writer", text: "請整理昨天的銷售。", days: [0, 1, 2, 3, 4], times: ["08:00", "13:00"],
  enabled: true, enabled_at: 1, created_at: 1, updated_at: 1, profile_name: "文案小編", can_chat: true,
  next: { slot: "2026-11-09T08:00", at: 1794000000 }, per_run_usd: "0.50", runs: [],
};
const WAITING = { kind: "routine_due", run_id: "rr-aaaaaaaaaaaa", routine_id: ROUTINE.id, name: "市集日報", slot: "2026-11-09T08:00", due_at: 1794000000 };

let state;
let calls;
function view() {
  return {
    routines: state.routines, readable: state.readable, problem: state.readable ? null : "壞了", waiting: state.waiting,
    cards: [{ id: "p-writer", name: "文案小編", can_chat: true, reason: null }, { id: "p-off", name: "停用員工", can_chat: false, reason: "停用" }],
    settings: { daily_usd: "1.50", daily_usd_set: null, default_usd: "1.50", keep_awake: false, problem: null },
    today: { routine_spent_usd: "0.20", routine_limit_usd: "1.50", day_usd: "3.00", day_left_usd: "2.50", lamp: "green" },
    autonomy: { routines: state.auto }, limits: { per_turn_usd: "0.50", max_routines: 20, max_enabled: 10 },
  };
}
function setServer(over = {}) {
  state = { routines: [{ ...ROUTINE }], waiting: [], readable: true, auto: false, post: null, getFails: false, ...over };
  calls = [];
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body]);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [], sources: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/routines" && method === "GET") return state.getFails ? jsonResponse({ error: "壞了" }, false, 500) : jsonResponse(view());
    if (p === "/api/waiting") return jsonResponse({ waiting: state.waiting });
    if (method === "POST" && p.startsWith("/api/routines")) return state.post ? state.post(p, body) : jsonResponse({ ok: true });
    return null;
  });
}
async function open(hash = "#/routines") {
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const posts = () => calls.filter((c) => c[0] === "POST");
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const button = (root, label) => root.find((n) => n.tag === "button" && text(n) === label);
const act = (root, name) => root.find((n) => n.tag === "button" && attr(n, "data-routine-action") === name);
const by = (root, key, value) => root.find((n) => attr(n, key) === value);
const click = async (node) => { node.dispatch("click"); await settle(); };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("the page lists a routine with its employee, days, times, next time, limit and text, as text", async () => {
  setServer();
  const main = await open();
  assert(text(main.find((n) => n.tag === "h1")).includes("例行工作"));
  const card = by(main, "data-routine", "card");
  assert(card, "a card");
  const t = text(card);
  for (const s of ["市集日報", "文案小編", "每週一、二、三、四、五", "08:00、13:00", "請整理昨天的銷售。", "US$0.50", "開啟"]) assert(t.includes(s), s);
  assert(text(by(card, "data-routine", "next")).includes("下一次"));
});

test("the money line says what was spent, the limit, the default rule and who starts them", async () => {
  setServer();
  const main = await open();
  const t = text(by(main, "data-routines", "money"));
  for (const s of ["US$0.20", "US$1.50", "每天上限 US$3.00 的一半", "不會超過每天上限", "共用每天上限"]) assert(t.includes(s), s);
  assert(text(by(main, "data-routines", "auto-line")).includes("沒有打開"));
  setServer({ auto: true });
  const again = await open();
  assert(text(by(again, "data-routines", "auto-line")).includes("自己開始"));
});

test("saving the limit posts only daily_usd, and going back to the default posts null", async () => {
  setServer();
  const main = await open();
  const input = by(main, "data-routine-field", "daily");
  input.value = "0.75";
  await click(act(main, "limit-save"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/routines/settings", { daily_usd: 0.75 }]]);
  await click(act(main, "limit-default"));
  assert.deepStrictEqual(posts()[1].slice(1), ["/api/routines/settings", { daily_usd: null }]);
});

test("a reminder offers 「現在開始」 and 「這次跳過」 and posts the run's id with the action", async () => {
  setServer({ waiting: [WAITING] });
  const main = await open();
  const row = by(main, "data-routine-waiting", WAITING.run_id);
  assert(row && text(row).includes("市集日報") && text(row).includes("08:00") && text(row).includes("還沒花錢"));
  await click(act(row, "wait-start"));
  await click(act(by(await open(), "data-routine-waiting", WAITING.run_id), "wait-skip"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [
    [`/api/routines/waiting/${WAITING.run_id}`, { action: "start" }], [`/api/routines/waiting/${WAITING.run_id}`, { action: "skip" }]]);
});

test("switching a routine off posts enabled false at once; switching one on needs the dialog only when item 3 is on", async () => {
  setServer();
  let main = await open();
  await click(act(main, "toggle"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [[`/api/routines/${ROUTINE.id}`, { enabled: false }]]);
  setServer({ routines: [{ ...ROUTINE, enabled: false, next: null }] });
  main = await open();
  await click(act(main, "toggle"));
  assert.strictEqual(dialog(), null);
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ enabled: true }]);
  setServer({ routines: [{ ...ROUTINE, enabled: false, next: null }], auto: true });
  main = await open();
  await click(act(main, "toggle"));
  assert(dialog() && text(dialog()).includes("自己開始"), "item 3 is on: the dialog says VBear will start it");
  assert.strictEqual(posts().length, 0);
  await click(button(dialog(), "取消"));
  assert.strictEqual(posts().length, 0);
});

test("start now asks first (it costs money), then posts to /start", async () => {
  setServer();
  const main = await open();
  await click(act(main, "start"));
  assert(text(dialog()).includes("US$0.50"));
  assert.strictEqual(posts().length, 0);
  await click(button(dialog(), "現在開始"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [[`/api/routines/${ROUTINE.id}/start`, {}]]);
});

test("delete asks first and posts to /delete", async () => {
  setServer();
  const main = await open();
  await click(act(main, "delete"));
  assert.strictEqual(posts().length, 0);
  await click(button(dialog(), "刪除"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [[`/api/routines/${ROUTINE.id}/delete`, {}]]);
});

test("the new-routine form lists only employees who can chat and posts exactly the six fields", async () => {
  setServer({ routines: [] });
  const main = await open();
  assert(text(main).includes("還沒有例行工作"));
  await click(act(main, "new"));
  const form = by(main, "data-routines", "form");
  const who = by(form, "data-routine-field", "profile");
  assert.deepStrictEqual(who.children.map((o) => text(o)), ["文案小編"], "an employee who cannot chat is not offered");
  by(form, "data-routine-field", "name").value = "晨間整理";
  by(form, "data-routine-field", "text").value = "請整理收件匣。";
  await click(act(form, "save"));
  const [call] = posts();
  assert.strictEqual(call[1], "/api/routines");
  assert.deepStrictEqual(Object.keys(call[2]).sort(), ["days", "enabled", "name", "profile_id", "text", "times"]);
  assert.deepStrictEqual([call[2].name, call[2].profile_id, call[2].days, call[2].times, call[2].enabled], ["晨間整理", "p-writer", [0, 1, 2, 3, 4], ["08:00"], false]);
});

test("the second yes: a routine_confirm answer opens a dialog and a yes sends it again with confirm_warning", async () => {
  let n = 0;
  setServer({ routines: [], post: (p, body) => (++n === 1 ? jsonResponse({ error: "這段話要求不經確認", code: "routine_confirm", warn_text: ["這段話要求不經確認就動手。"] }, false, 409) : jsonResponse({ ok: true })) });
  const main = await open();
  await click(act(main, "new"));
  const form = by(main, "data-routines", "form");
  by(form, "data-routine-field", "name").value = "x";
  by(form, "data-routine-field", "text").value = "y";
  await click(act(form, "save"));
  assert(dialog() && text(dialog()).includes("不經確認"));
  assert.strictEqual(posts().length, 1);
  await click(button(dialog(), "我了解，照這樣存"));
  assert.strictEqual(posts().length, 2);
  assert.strictEqual(posts()[1][2].confirm_warning, true);
});

test("a refusal is shown and the form stays open with what the person typed", async () => {
  setServer({ routines: [], post: () => jsonResponse({ error: "沒有可用的員工", code: "routine_card" }, false, 400) });
  const main = await open();
  await click(act(main, "new"));
  const form = by(main, "data-routines", "form");
  by(form, "data-routine-field", "name").value = "x";
  by(form, "data-routine-field", "text").value = "keep me";
  await click(act(form, "save"));
  assert(by(main, "data-routines", "form"), "still open");
  assert.strictEqual(text(by(form, "data-routine-field", "text")) || by(form, "data-routine-field", "text").value, "keep me");
});

test("a run's state, the reason in words, who decided and a link to its chat are shown; nothing is invented", async () => {
  const runs = [
    { run_id: "rr-1", routine_id: ROUTINE.id, slot: "2026-11-09T08:00", state: "done", by: "auto3", by_text: "自己動手第 3 項", chat_id: "c-0123456789abcdef", cost_usd: "0.12", reason: "result", at: 1 },
    { run_id: "rr-2", routine_id: ROUTINE.id, slot: "2026-11-08T08:00", state: "skipped", by: null, by_text: null, chat_id: null, cost_usd: null, reason: "daily_limit", at: 1 },
    { run_id: "rr-3", routine_id: ROUTINE.id, slot: "2026-11-07T08:00", state: "uncertain", by: "auto3", by_text: "自己動手第 3 項", chat_id: null, cost_usd: null, reason: "not_found", at: 1 },
  ];
  setServer({ routines: [{ ...ROUTINE, runs }] });
  const main = await open();
  const list = by(main, "data-routine", "runs");
  const items = list.findAll((n) => n.tag === "li");
  assert.strictEqual(items.length, 3);
  assert(text(items[0]).includes("完成") && text(items[0]).includes("自己動手第 3 項") && text(items[0]).includes("US$0.12"));
  assert.strictEqual(items[0].find((n) => n.tag === "a").getAttribute("href"), "#/chat/c-0123456789abcdef");
  assert(text(items[1]).includes("今天的額度用完了"));
  assert(text(items[2]).includes("不確定有沒有送出") && text(items[2]).includes("不會自己再送一次"));
});

test("a file that cannot be read is said, and no routine is drawn", async () => {
  setServer({ routines: [], readable: false });
  const main = await open();
  assert(text(main).includes("讀不出來"));
});

test("the line over every page names the routine and its time and nothing of its text; it is empty when nothing waits", async () => {
  const bar = global.document.createElement("div");
  bar.setAttribute("id", "waiting-bar");
  setServer({ waiting: [WAITING, { ...WAITING, run_id: "rr-bbbbbbbbbbbb", name: "第二件", slot: "2026-11-09T13:00" }] });
  await open("#/routines");
  assert.strictEqual(bar.hidden, false);
  assert.strictEqual(text(bar).includes("等你決定：例行工作「市集日報」08:00到時間了，另外還有 1 件"), true, text(bar));
  assert.strictEqual(attr(by(bar, "data-waiting", "link"), "href"), "#/routines");
  assert(!text(bar).includes("請整理"));
  setServer({ waiting: [] });
  await open("#/routines");
  assert.strictEqual(bar.hidden, true);
  assert.strictEqual(text(bar), "");
});

test("the chat list shows the routine's title where the server sent one", async () => {
  setServer();
  setHandler((url) => {
    const p = url.split("?")[0];
    if (p === "/api/chats") return jsonResponse({ chats: [
      { id: "c-0123456789abcdef", profile_id: "p-writer", name: "文案小編", routine_title: "例行工作：市集日報 11/09 08:00", engine: "claude", turns: 1, spent_usd: "0.10", last_at: 1, open: false, waiting: false },
      { id: "c-fedcba9876543210", profile_id: "p-writer", name: "文案小編", engine: "claude", turns: 1, spent_usd: "0.10", last_at: 1, open: false, waiting: false }],
      cards: [], problems: [], ledger: null, limits: null });
    return null;
  });
  const main = await open("#/chat");
  const rows = main.findAll((n) => attr(n, "data-chat") === "row");
  assert.strictEqual(rows.length, 2);
  assert(text(rows[0]).includes("例行工作：市集日報 11/09 08:00"));
  assert(text(rows[1]).includes("文案小編") && !text(rows[1]).includes("例行工作"));
});

test("「AI 自己做了什麼」 lists a routine VBear started, links to its chat, offers no stop and no withdraw", async () => {
  setServer();
  setHandler((url) => {
    const p = url.split("?")[0];
    if (p === "/api/actions") return jsonResponse({ actions: [{ at: 1794000000, dispatch_id: null, seq: 0, kind: "routine_started", what: "例行工作「市集日報」開始了", by: "auto3", by_text: "自己動手第 3 項", profile_id: null, can_stop: false, can_withdraw: false, routine_id: ROUTINE.id, chat_id: "c-0123456789abcdef" }], unreadable: 0 });
    return null;
  });
  const main = await open("#/actions");
  const row = by(main, "data-action", "row");
  assert(row && text(row).includes("例行工作「市集日報」開始了") && text(row).includes("自己動手第 3 項"));
  assert.strictEqual(attr(row, "data-by"), "auto3");
  assert.strictEqual(by(row, "data-action", "routine-chat").getAttribute("href"), "#/chat/c-0123456789abcdef");
  assert.strictEqual(row.find((n) => n.tag === "button"), null);
  assert(!row.find((n) => n.tag === "a" && String(attr(n, "href")).includes("#/dispatch/")), "no dispatch link for a routine row");
});

// ---- P44-3: waking up -----------------------------------------------------------------------------------------------------
const MISSED = { kind: "routine_missed", run_id: "rr-cccccccccccc", routine_id: ROUTINE.id, name: "市集日報", slot: "2026-11-11T08:00", due_at: 1794100000, count: 3, too_old: false };

test("what a sleep missed is one row with the count, the latest time and the two buttons; it says it is not sent by itself while item 3 is off", async () => {
  setServer({ waiting: [MISSED] });
  const main = await open();
  const row = by(main, "data-routine-missed", ROUTINE.id);
  assert(row, "a missed row");
  const t = text(row);
  for (const s of ["市集日報", "錯過 3 次", "最近一次 11/11 08:00", "Mac 睡著或 VBear 關著", "只做最近一次", "US$0.50", "沒有打開「自己動手」第 3 項"]) assert(t.includes(s), s);
  assert(button(row, "補做") && button(row, "不用了"));
});

test("with item 3 on the row does not say it will not run; over 12 hours it says the person decides", async () => {
  setServer({ waiting: [MISSED], auto: true });
  let t = text(by(await open(), "data-routine-missed", ROUTINE.id));
  assert(!t.includes("不會自己補做"), t);
  setServer({ waiting: [{ ...MISSED, too_old: true }], auto: true });
  t = text(by(await open(), "data-routine-missed", ROUTINE.id));
  assert(t.includes("已經超過 12 小時，不會自己補做，由你決定"), t);
});

test("補做 and 不用了 post the routine's id with run or dismiss, and nothing else", async () => {
  setServer({ waiting: [MISSED] });
  let main = await open();
  await click(act(by(main, "data-routine-missed", ROUTINE.id), "missed-run"));
  main = await open();
  await click(act(by(main, "data-routine-missed", ROUTINE.id), "missed-dismiss"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [
    [`/api/routines/missed/${ROUTINE.id}`, { action: "run" }], [`/api/routines/missed/${ROUTINE.id}`, { action: "dismiss" }]]);
});

test("a reminder and a missed row sit together; the line over every page counts the lost ones apart", async () => {
  const bar = global.document.createElement("div");
  bar.setAttribute("id", "waiting-bar");
  setServer({ waiting: [WAITING, MISSED, { ...MISSED, routine_id: "r-ba9876543210", name: "第二件" }] });
  const main = await open("#/routines");
  assert(by(main, "data-routine-waiting", WAITING.run_id) && by(main, "data-routine-missed", ROUTINE.id) && by(main, "data-routine-missed", "r-ba9876543210"));
  assert.strictEqual(text(bar), "等你決定：例行工作「市集日報」08:00到時間了；VBear 剛才沒在看，錯過了 2 件例行工作 去處理");
  setServer({ waiting: [MISSED] });
  await open("#/routines");
  assert.strictEqual(text(bar), "等你決定：VBear 剛才沒在看，錯過了 1 件例行工作 去處理");
  assert(!text(bar).includes("請整理"));
});

test("the page says VBear must be open and the Mac awake, and the switch for keeping the Mac awake posts only keep_awake", async () => {
  setServer();
  const main = await open();
  assert(text(by(main, "data-routines", "awake-line")).includes("VBear 的視窗要開著、Mac 要醒著，例行工作才會做"));
  const panel = by(main, "data-routines", "awake");
  const box = by(panel, "data-routine-field", "keep-awake");
  assert(box && box.checked === false, "off by default");
  for (const s of ["有工作在跑時不讓 Mac 睡著", "闔上筆電蓋子還是會睡", "不會為了到時間把 Mac 叫醒", "預設是關的"]) assert(text(panel).includes(s), s);
  box.checked = true;
  box.dispatch("change");
  await settle();
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/routines/settings", { keep_awake: true }]]);
});

test("the switch shows what the server says", async () => {
  setServer();
  const real = view;
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    if (p === "/api/routines" && !(opts && opts.method && opts.method !== "GET")) { const v = real(); v.settings.keep_awake = true; return jsonResponse(v); }
    return null;
  });
  const main = await open();
  assert.strictEqual(by(by(main, "data-routines", "awake"), "data-routine-field", "keep-awake").checked, true);
});

test("a run that was a missed time is told in words: how many were lost, or that only the latest is done", async () => {
  setServer({ routines: [{ ...ROUTINE, runs: [
    { run_id: "rr-1", routine_id: ROUTINE.id, slot: "2026-11-11T08:00", state: "waiting", by: null, by_text: null, why: "catch_up", chat_id: null, turn: null, cost_usd: null, reason: "asleep_3", started_at: null, at: 1 },
    { run_id: "rr-2", routine_id: ROUTINE.id, slot: "2026-11-10T08:00", state: "missed", by: null, by_text: null, why: "catch_up", chat_id: null, turn: null, cost_usd: null, reason: "older", started_at: null, at: 1 },
    { run_id: "rr-3", routine_id: ROUTINE.id, slot: "2026-11-09T08:00", state: "missed", by: null, by_text: null, why: "catch_up", chat_id: null, turn: null, cost_usd: null, reason: "superseded", started_at: null, at: 1 }] }] });
  const t = text(by(await open(), "data-routine", "runs"));
  for (const s of ["VBear 沒在看，錯過 3 次", "只補最近一次", "之後的時間已經到了"]) assert(t.includes(s), s);
  assert(!t.includes("asleep_") && !t.includes("superseded"), t);
});

test("the nav has the page, the bar sits over main, and the CSS can hide it", () => {
  assert(/<a href="#\/routines" data-nav="routines">/.test(HTML));
  assert(/id="waiting-bar"[^>]*hidden/.test(HTML));
  assert(HTML.indexOf('id="waiting-bar"') < HTML.indexOf('<main id="main"'));
  assert(/\.waiting-bar\[hidden\]/.test(fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8")));
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, no writes but the routine routes, no screen word 排程/cron/routine", () => {
  assert(BLOCK.length > 1000, "the block is marked in app.js");
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(BLOCK));
  assert(!/api\/config|api\/settings/.test(BLOCK), "never writes the configuration");
  const urls = Array.from(BLOCK.matchAll(/api\.(?:post|get)\(\s*[`"]([^`"]+)/g)).map((m) => m[1].replace(/\$\{[^}]*\}/g, "$"));
  for (const u of urls) assert(/^\/api\/(routines|waiting)/.test(u), u);
  const strings = Array.from(BLOCK.matchAll(/"([^"\n]*[一-鿿][^"\n]*)"|`([^`\n]*[一-鿿][^`\n]*)`/g)).map((m) => m[1] || m[2]).join("\n");
  assert(!/排程|cron|routine/i.test(strings.replace(/\$\{[^}]*\}/g, "")), "GLOSSARY: no 排程 on the screen");
});

(async () => {
  let pass = 0;
  for (const [name, fn] of tests) {
    try { await fn(); pass++; console.log("ok   " + name); }
    catch (e) { console.log("FAIL " + name + "\n     " + (e && e.stack || e)); process.exitCode = 1; }
  }
  console.log(`${pass}/${tests.length} passed`);
  process.exit(process.exitCode || 0);
})();
