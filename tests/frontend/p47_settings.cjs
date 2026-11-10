// Rule 15d: only the person's Save writes a limit or enables a scheduled routine.
// Uses the real page on the existing synthetic DOM; no daemon, browser or AI tool.
"use strict";
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler } = h;
const attr = (n, k) => n.getAttribute && n.getAttribute(k);
const by = (n, k, v) => n.find((x) => attr(x, k) === v);
const text = (n) => n ? n.textContent : "";
async function settle() { for (let i = 0; i < 60; i++) await Promise.resolve(); await new Promise((r) => setTimeout(r, 5)); }
async function click(n) { assert(n, "control exists"); n.dispatch("click"); await settle(); }
global.document.querySelector = () => null;
const realId = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => id === "scan-status" ? null : realId(id);
let calls, state;
function server(over = {}) {
  state = { daily: 3, ledger: true, advanced: false, auto: false, routines: [], post: null, ...over }; calls = [];
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0], method = opts.method || "GET", body = opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body]);
    if (p === "/api/overview") return jsonResponse({ totals: { active: 0 }, sources: [], facts: {}, problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ sessions: [], projects: [], attention: [], usage: { sessions: [] } });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: state.advanced }, state_dir: "/fictional" });
    if (p === "/api/settings/autonomy") return jsonResponse({ autonomy: {}, items: [], never: [] });
    if (p === "/api/meetings/ledger") return state.ledger ? jsonResponse({ spent_usd: "0.42", daily_usd: state.daily, lamp: "green" }) : jsonResponse({ error: "讀取失敗" }, false, 503);
    if (p === "/api/setup/daily-limit") {
      if (method === "GET") return jsonResponse({ daily_usd: state.daily });
      if (state.post) return state.post(body);
      state.daily = body.daily_usd; return jsonResponse({ daily_usd: body.daily_usd, changed: [] });
    }
    if (p === "/api/routines" && method === "GET") return jsonResponse({ routines: state.routines, cards: [{ id: "p-fiction", name: "測試員工", can_chat: true }], waiting: [], settings: { daily_usd: 1.5 }, today: {}, limits: { per_turn_usd: "0.50" }, autonomy: { routines: state.auto } });
    if (method === "POST" && p.startsWith("/api/routines")) return jsonResponse({ ok: true });
    if (p === "/api/waiting") return jsonResponse({ waiting: [] });
    return null;
  });
}
async function open(hash = "#/settings") {
  const interval = global.setInterval; global.setInterval = () => 0; global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = interval; }
  return h.dom().mainEl;
}
const posts = () => calls.filter(([m]) => m === "POST");
const tests = [], test = (n, f) => tests.push([n, f]);

test("15d: settings load is read-only, limits folded, URL opens them and usage stays inside", async () => {
  server(); let main = await open(); let limits = by(main, "data-settings", "limits");
  assert(limits && limits.tag === "details"); assert.strictEqual(attr(limits, "open"), null);
  assert(!text(limits.find((n) => n.tag === "summary")).includes("0.42"));
  assert(text(limits).includes("US$0.42")); assert.deepStrictEqual(posts(), []);
  main = await open("#/settings?open=limits"); limits = by(main, "data-settings", "limits"); assert.strictEqual(attr(limits, "open"), "");
});

test("15d: choosing and typing never post; Save sends only daily_usd once", async () => {
  server(); const main = await open();
  await click(by(main, "data-limit-choice", "10")); assert.deepStrictEqual(posts(), []);
  await click(by(main, "data-limit-choice", "custom")); const input = by(main, "data-limit-input", "");
  input.value = "5.25"; input.dispatch("input"); await settle(); assert.deepStrictEqual(posts(), []);
  await click(by(main, "data-limit-save", "")); assert.deepStrictEqual(posts(), [["POST", "/api/setup/daily-limit", { daily_usd: 5.25 }]]);
  assert(text(by(main, "data-limit-result", "")).includes("US$5.25"));
});

// Counterexamples for rule 15d: out-of-range drafts and cancelled auto-start must write nothing.
test("15d: invalid custom amounts are refused locally; boundary amounts can be saved", async () => {
  for (const raw of ["0", "0.001", "50.01", "-1", "", "abc", "1.234"]) {
    server(); const main = await open(); await click(by(main, "data-limit-choice", "custom"));
    by(main, "data-limit-input", "").value = raw;
    await click(by(main, "data-limit-save", ""));
    assert.deepStrictEqual(posts(), [], raw); assert(text(by(main, "data-limit-result", "")).includes("0.01–50"));
  }
  for (const raw of ["0.01", "50"]) {
    server(); const main = await open(); await click(by(main, "data-limit-choice", "custom")); by(main, "data-limit-input", "").value = raw;
    await click(by(main, "data-limit-save", "")); assert.strictEqual(posts()[0][2].daily_usd, Number(raw));
  }
});

test("unknown ledger never becomes zero; privacy stays visible, advanced sections follow the display switch", async () => {
  server({ ledger: false }); let main = await open();
  assert(text(by(main, "data-settings", "limits")).includes("讀不到今天的用量"));
  assert(!text(main).includes("今天已花 US$0")); assert(text(main).includes("使用紀錄"));
  assert(!by(main, "data-settings-advanced", ""));
  for (const label of ["技能中文化", "掃描來源", "新手第一局", "診斷"]) assert(!main.find((n) => /^h[123]$/.test(n.tag) && text(n) === label), label);
  server({ advanced: true }); main = await open();
  const advanced = by(main, "data-settings-advanced", ""); assert(advanced);
  for (const label of ["技能中文化", "掃描來源", "新手第一局", "診斷"]) assert(text(advanced).includes(label), label);
});

const act = (main, v) => by(main, "data-routine-action", v);
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const button = (root, label) => root.find((n) => n.tag === "button" && text(n) === label);
test("15d: new routines default to all seven days and enabled, but only remind when item 3 is off", async () => {
  server(); const main = await open("#/routines"); assert.deepStrictEqual(posts(), []);
  const money = by(main, "data-routines", "money"); assert.strictEqual(money.tag, "details"); assert.strictEqual(attr(money, "open"), null);
  await click(act(main, "new")); const form = by(main, "data-routines", "form");
  assert(form.findAll((n) => attr(n, "data-routine-day") !== null && n.tag === "input").every((n) => n.checked));
  assert(by(form, "data-routine-field", "enabled").checked); assert(text(form).includes("只會到時間提醒你"));
  const fields = form.findAll((n) => attr(n, "data-routine-field") !== null);
  assert.deepStrictEqual(fields.slice(0, 2).map((n) => attr(n, "data-routine-field")), ["name", "enabled"]);
  await click(act(main, "save")); assert(!dialog());
  assert.deepStrictEqual(posts()[0][2].days, [0, 1, 2, 3, 4, 5, 6]); assert.strictEqual(posts()[0][2].enabled, true);
});

test("15d: enabled routine Save asks before POST when item 3 is on, cancel writes nothing, accept once", async () => {
  server({ auto: true }); const main = await open("#/routines"); await click(act(main, "new"));
  await click(act(main, "save")); assert(dialog()); assert(text(dialog()).includes("每次最多花 US$0.50")); assert.deepStrictEqual(posts(), []);
  await click(button(dialog(), "取消")); assert.deepStrictEqual(posts(), []);
  await click(act(main, "save")); await click(button(dialog(), "我了解，開啟")); assert.strictEqual(posts().length, 1);
});


test("Save shows each lowered limit and never claims a refused write succeeded", async () => {
  server({ post: () => jsonResponse({ daily_usd: 1, changed: [{ limit: "chat_per_turn_usd", from: 4, to: 1 }, { limit: "meeting_usd", from: 2, to: 1 }] }) });
  let main = await open(); await click(by(main, "data-limit-choice", "1")); await click(by(main, "data-limit-save", ""));
  let result = text(by(main, "data-limit-result", ""));
  for (const phrase of ["調低", "聊天每回合", "每場會議", "US$4", "US$2", "US$1"]) assert(result.includes(phrase), phrase);
  assert(text(by(main, "data-settings", "limits").find((n) => n.tag === "summary")).includes("US$1"));
  server({ post: () => jsonResponse({ error: "磁碟寫不進去" }, false, 503) });
  main = await open(); await click(by(main, "data-limit-choice", "1")); await click(by(main, "data-limit-save", ""));
  result = text(by(main, "data-limit-result", "")); assert(result.includes("磁碟寫不進去")); assert(!result.includes("已設定"));
  assert(text(by(main, "data-limit-current", "")).includes("US$3"));
});

test("enabled edits ask too, disabled saves do not; card cost and run cost stay inside details", async () => {
  const routine = { id: "r-fiction", name: "測試工作", profile_id: "p-fiction", text: "測試", days: [0], times: ["08:00"], enabled: true, can_chat: true, next: { at: 1 }, per_run_usd: "0.50", runs: [{ slot: "2026-01-01T08:00", state: "skipped", reason: "routine_limit", cost_usd: "0.10" }] };
  server({ auto: true, routines: [routine] }); let main = await open("#/routines");
  assert(text(by(main, "data-routine", "details")).includes("US$0.50"));
  assert(!text(by(main, "data-routine", "next")).includes("US$"));
  assert.strictEqual(attr(by(main, "data-limit", "go"), "href"), "#/settings?open=limits");
  await click(act(main, "edit")); await click(act(main, "save")); assert(dialog()); assert.deepStrictEqual(posts(), []);
  await click(button(dialog(), "取消")); by(main, "data-routine-field", "enabled").checked = false;
  await click(act(main, "save")); assert(!dialog()); assert.strictEqual(posts()[0][2].enabled, false);
});

test("15d guard rejects illustrative automatic POST traces", () => {
  const assertReadOnly = (trace) => assert.deepStrictEqual(trace.filter(([method]) => method !== "GET"), []);
  assertReadOnly([["GET", "/api/config"]]);
  for (const path of ["/api/setup/daily-limit", "/api/routines"]) assert.throws(() => assertReadOnly([["POST", path, {}]]), assert.AssertionError);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) { try { await fn(); console.log("ok - " + name); } catch (e) { failed++; console.log("FAIL - " + name + "\n" + e.stack); } }
  console.log(`${tests.length - failed}/${tests.length} passed`); process.exit(failed ? 1 : 0);
})();
