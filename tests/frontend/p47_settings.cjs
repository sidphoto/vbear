// Rule 15d: only the person's Save writes a limit or enables a scheduled routine.
// Uses the real page on the existing synthetic DOM; no daemon, browser or AI tool.
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
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
  state = { daily: 3, ledger: true, lamp: "green", spent: "0.42", advanced: false, auto: false, routines: [], post: null, ...over }; calls = [];
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0], method = opts.method || "GET", body = opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body]);
    if (p === "/api/overview") return jsonResponse({ totals: { active: 0 }, sources: [], facts: {}, problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ sessions: [], projects: [], attention: [], usage: { sessions: [] } });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: state.advanced }, state_dir: "/fictional" });
    if (p === "/api/settings/autonomy") return jsonResponse({ autonomy: {}, items: [], never: [] });
    if (p === "/api/meetings/ledger") return state.ledger ? jsonResponse({ spent_usd: state.spent, daily_usd: state.daily, ...(state.lamp === undefined ? {} : { lamp: state.lamp }) }) : jsonResponse({ error: "讀取失敗" }, false, 503);
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

// P48-6: the guard is shown to catch the real page going wrong, not a local lambda. The page (web/app.js) is copied with one change that makes it
// write on its own or skip the person's yes, and this very file is run against that copy: it must fail. The copy with no change must pass, so a
// failure is the change's. (The copy lives in a folder this test makes in the temp folder and removes.)
const IS_MUTANT_RUN = process.env.P48_MUTANT === "1";
const ROOT = path.join(__dirname, "..", "..");
const MUTANTS = [
  ["the enabled routine's Save no longer asks (item 3 on)", "enabled.checked && cur.autonomy.routines === true && !(await confirmInPage(", "false && !(await confirmInPage("],
  ["the card's 開啟 switch no longer asks (item 3 on)", "if (turnOn && cur.autonomy.routines === true && !(await confirmInPage(`開啟「${r.name}」`", "if (false && !(await confirmInPage(`開啟「${r.name}」`"],
  ["a choice of the limit writes it at once", "button.addEventListener(\"click\", () => { if (!busy) { selected = key; sync();", "button.addEventListener(\"click\", () => { if (!busy) { selected = key; sync(); api.post(\"/api/setup/daily-limit\", { daily_usd: Number(key) || 1 });"],
  ["the settings page writes the limit as it loads", "  summaryText();\n  const limits = el(\"details\"", "  summaryText(); api.post(\"/api/setup/daily-limit\", { daily_usd: day });\n  const limits = el(\"details\""],
  ["the limits are open at first", "open: !!params && params.open === \"limits\" }, summary", "open: true }, summary"],
];
function runOnCopy(change) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "p48m-"));
  try {
    fs.mkdirSync(path.join(dir, "web"));
    fs.mkdirSync(path.join(dir, "tests", "frontend", "lib"), { recursive: true });
    let src = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
    if (change) {
      assert.strictEqual(src.split(change[1]).length - 1, 1, `the change to try is found in app.js once: ${change[0]}`);
      src = src.replace(change[1], () => change[2]);
    }
    fs.writeFileSync(path.join(dir, "web", "app.js"), src);
    for (const f of fs.readdirSync(path.join(__dirname, "lib"))) fs.copyFileSync(path.join(__dirname, "lib", f), path.join(dir, "tests", "frontend", "lib", f));
    fs.copyFileSync(__filename, path.join(dir, "tests", "frontend", "p47_settings.cjs"));
    return spawnSync(process.execPath, [path.join(dir, "tests", "frontend", "p47_settings.cjs")], { env: { ...process.env, P48_MUTANT: "1" }, encoding: "utf8", timeout: 240000 });
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
}
if (!IS_MUTANT_RUN) {
  test("15d guard: the copy of the page with no change passes this file", () => {
    const r = runOnCopy(null);
    assert.strictEqual(r.status, 0, `${r.stdout}\n${r.stderr}`);
  });
  for (const change of MUTANTS) {
    test(`15d guard: this file fails on the page when ${change[0]}`, () => {
      const r = runOnCopy(change);
      assert.notStrictEqual(r.status, 0, "the changed page was not caught");
      assert(/FAIL - /.test(r.stdout), `it failed by a test, not by a crash:\n${r.stdout.slice(-600)}\n${r.stderr.slice(-300)}`);
    });
  }
}

test("15d: the card's 開啟 asks when item 3 is on (cancel writes nothing, yes writes once), does not ask when it is off, and 關掉 never asks", async () => {
  const off = { id: "r-off", name: "測試工作", profile_id: "p-fiction", text: "測試", days: [0], times: ["08:00"], enabled: false, can_chat: true, next: null, per_run_usd: "0.50", runs: [] };
  server({ auto: true, routines: [off] }); let main = await open("#/routines");
  await click(act(main, "toggle")); assert(dialog(), "asks first"); assert(text(dialog()).includes("每次最多花 US$0.50")); assert.deepStrictEqual(posts(), []);
  await click(button(dialog(), "取消")); assert.deepStrictEqual(posts(), []);
  await click(act(main, "toggle")); await click(button(dialog(), "我了解，開啟"));
  assert.deepStrictEqual(posts(), [["POST", "/api/routines/r-off", { enabled: true }]]);
  server({ auto: false, routines: [off] }); main = await open("#/routines");
  await click(act(main, "toggle")); assert(!dialog(), "item 3 is off: it only reminds, so nothing to ask");
  assert.deepStrictEqual(posts(), [["POST", "/api/routines/r-off", { enabled: true }]]);
  server({ auto: true, routines: [{ ...off, enabled: true, next: { at: 1 } }] }); main = await open("#/routines");
  await click(act(main, "toggle")); assert(!dialog(), "turning off asks nothing");
  assert.deepStrictEqual(posts(), [["POST", "/api/routines/r-off", { enabled: false }]]);
});

test("15d: the routines' own 用量與上限 stays folded, and its 儲存 / 改回預設 inside still write only what the person pressed", async () => {
  server(); const main = await open("#/routines");
  const money = by(main, "data-routines", "money"); assert.strictEqual(money.tag, "details"); assert.strictEqual(attr(money, "open"), null);
  assert.deepStrictEqual(posts(), []);
  const field = by(money, "data-routine-field", "daily"); field.value = "1.25"; field.dispatch("input"); await settle();
  assert.deepStrictEqual(posts(), [], "typing writes nothing");
  await click(act(money, "limit-save")); assert.deepStrictEqual(posts(), [["POST", "/api/routines/settings", { daily_usd: 1.25 }]]);
  await click(act(await open("#/routines"), "limit-default"));
  assert.deepStrictEqual(posts().slice(-1), [["POST", "/api/routines/settings", { daily_usd: null }]]);
});

test("the summary of the limits says 今天已到上限 only when the server's lamp is red, and says nothing about the day when the lamp was not read", async () => {
  const summary = async () => text((by(await open(), "data-settings", "limits")).find((n) => n.tag === "summary"));
  server({ lamp: "red", spent: "0.42" }); assert.strictEqual(await summary(), "用量與上限：每天最多 US$3（今天已到上限）", "the lamp is red though the sum shown is under the limit");
  server({ lamp: "green", spent: "9" }); assert.strictEqual(await summary(), "用量與上限：每天最多 US$3（今天還可以用）", "the lamp is green though the sum shown is over the limit");
  server({ lamp: "yellow" }); assert.strictEqual(await summary(), "用量與上限：每天最多 US$3（今天還可以用）");
  server({ lamp: undefined }); assert.strictEqual(await summary(), "用量與上限：每天最多 US$3", "an answer with no lamp: nothing is said");
  server({ lamp: "purple" }); assert.strictEqual(await summary(), "用量與上限：每天最多 US$3", "a lamp the page does not know: nothing is said");
  server({ ledger: false }); assert.strictEqual(await summary(), "用量與上限：每天最多 US$3", "the ledger could not be read: nothing is said");
});

test("after Save the old lamp is not kept: the summary follows the limit just saved and the lamp read again", async () => {
  server({ lamp: "red" }); const main = await open();
  const summaryOf = () => text(by(main, "data-settings", "limits").find((n) => n.tag === "summary"));
  assert(summaryOf().includes("今天已到上限"));
  state.lamp = "green";                                   // the server now reads the new limit
  await click(by(main, "data-limit-choice", "10")); await click(by(main, "data-limit-save", ""));
  assert.strictEqual(summaryOf(), "用量與上限：每天最多 US$10（今天還可以用）");
});

test("P48-6 資料流向: six plain lines, the folder path only in the advanced mode", async () => {
  server(); let main = await open(); const box = by(main, "data-settings", "dataflow");
  assert.deepStrictEqual(box.findAll((n) => n.tag === "li").map(text), [
    "你的資料都在這台電腦上整理；只有你打開「技能中文化」時，技能的說明會經你自己登入的 AI 工具送到那家公司翻譯。",
    "VBear 只接受這台電腦自己的連線（127.0.0.1）。",
    "技能裡的程式不會被執行，只當文字顯示。",
    "VBear 只寫自己的資料夾。",
    "員工由 VBear 在背後啟動；指令視窗預設只看不打字，你按「接手」才會送出你打的字。",
    "通知只在這台 Mac 上顯示，內容只有件數（要在「通知」打開）。"]);
  server({ advanced: true }); main = await open();
  assert(text(by(main, "data-settings", "dataflow").findAll((n) => n.tag === "li")[3]).startsWith("VBear 只寫自己的資料夾："));
  assert(text(by(main, "data-settings", "dataflow").findAll((n) => n.tag === "li")[3]).includes("/fictional"));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) { try { await fn(); console.log("ok - " + name); } catch (e) { failed++; console.log("FAIL - " + name + "\n" + e.stack); } }
  console.log(`${tests.length - failed}/${tests.length} passed`); process.exit(failed ? 1 : 0);
})();
