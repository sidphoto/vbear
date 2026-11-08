// The 「自己動手」 section of the settings page (v0.15 P40-2): only the two items that work in this version, each off until the
// person has pressed 「我了解，打開」 in a dialog that says what it does and what it costs at most; the other three items
// are one sentence; the three things that stay forbidden are said. The words are the plan's (P40), word for word.
// The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/autonomy.cjs   (exit code 0 = pass)
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
const START = "// ---------- the 「自己動手」 settings";
const BLOCK = SRC.slice(SRC.indexOf(START), SRC.indexOf("// ---------- end of the 「自己動手」 settings"));

// the plan's words (plan.md, P40 「自己動手」), and the table the server sends
const TITLE_1 = "幕僚長可以自己建新員工";
const EFFECT_1 = "幕僚長提議要新員工時，VBear 不等你確認就建好（一律安全模式），你可以在「AI 自己做了什麼」撤回。";
const TITLE_2 = "幕僚長可以自己派工給員工";
const EFFECT_2 = "幕僚長的提議一到就開始派工，不再停在提議卡；員工照舊每個指令都問你。提議要新員工（而第 1 項沒勾）、VBear 拿掉了東西、或幕僚長有問題要問你時，還是會停下來等你。";
const TITLE_3 = "例行工作可以自己啟用、定時執行";
const EFFECT_3 = "例行工作到時間時 VBear 自己開始；Mac 醒來或 VBear 打開時，12 小時內錯過的也自己補做一次（每次醒來最多 3 件）。不勾時，到時間只提醒你，由你按「現在開始」。員工要跑指令、改檔案時照舊問你；你不在電腦前時，卡片 5 分鐘沒人按就當作拒絕。例行工作不會自己建立或啟用，只有你能。";
const TITLE_5 = "碰到上限暫停的工作，倒數結束後自動接續";
const EFFECT_5 = "派工碰到每天上限或 AI 工具的方案用量上限暫停時，到了恢復時間 VBear 自己按「繼續」（每份派工最多 3 次，全部加起來每天最多 5 次）。被打斷的那一步不會重做，下一步會被告知上一步可能不完整。AI 工具沒說恢復時間時（Claude Code 目前都沒說）不會自己接續；群組不會自己接續。";
const LATER = "第 4 項（不必每次問）會在之後的版本加入。";
const NEVER = ["AI 不能自己調高每天的花費上限。", "AI 不能自己讓員工用完整模式出發。", "AI 不能自己從網路安裝新技能。"];
const ITEMS = [
  { id: 1, adr: "0003", key: "create_cards", active: true, title: TITLE_1, effect: EFFECT_1 },
  { id: 2, adr: "0003", key: "dispatch", active: true, title: TITLE_2, effect: EFFECT_2 },
  { id: 3, adr: "0003", key: "routines", active: true, title: TITLE_3, effect: EFFECT_3 },
  { id: 4, adr: "0003", key: null, active: false, title: "員工在安全模式裡跑指令、改檔案時不必每次問", effect: "還沒有；聊天照舊每個指令、每個檔案修改都問你。" },
  { id: 5, adr: "0003", key: "auto_continue", active: true, title: TITLE_5, effect: EFFECT_5 },
];

let state;
let calls;
function view() {
  return { ok: true, autonomy: { ...state.autonomy }, items: ITEMS, later_note: LATER, never: NEVER,
    limits: { chief_call_usd: 0.3, per_turn_usd: 0.5, daily_usd: 3 } };
}
function setServer(over = {}) {
  state = { autonomy: { create_cards: false, dispatch: false, routines: false, auto_continue: false }, getFails: false, post: null, ...over };
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
    if (p === "/api/settings/autonomy" && method === "GET") return state.getFails ? jsonResponse({ error: "壞了" }, false, 500) : jsonResponse(view());
    if (p === "/api/settings/autonomy" && method === "POST") {
      if (state.post) return state.post(body);
      state.autonomy = { create_cards: body.create_cards, dispatch: body.dispatch, routines: body.routines, auto_continue: body.auto_continue };
      return jsonResponse(view());
    }
    return null;
  });
}
async function open() {
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = "#/settings";
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const section = (main) => main.find((n) => attr(n, "data-settings") === "autonomy");
const boxes = (main) => section(main).findAll((n) => n.tag === "input" && attr(n, "type") === "checkbox");
const box = (main, key) => section(main).find((n) => attr(n, "data-autonomy") === key && n.tag === "input");
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const button = (root, label) => root.find((n) => n.tag === "button" && text(n) === label);
const tick = async (node, on) => { node.checked = on; node.dispatch("change"); await settle(); };
const posts = () => calls.filter((c) => c[0] === "POST");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("the section lists exactly the four items that work, in order, with the plan's words, all off", async () => {
  setServer();
  const main = await open();
  assert(section(main), "the section is on the settings page");
  assert(text(section(main).find((n) => n.tag === "h2")).includes("自己動手"));
  assert.deepStrictEqual(boxes(main).map((b) => attr(b, "data-autonomy")), ["create_cards", "dispatch", "routines", "auto_continue"]);
  assert(boxes(main).every((b) => !b.checked), "off by default");
  const t = text(section(main));
  for (const s of [TITLE_1, EFFECT_1, TITLE_2, EFFECT_2, TITLE_3, EFFECT_3, TITLE_5, EFFECT_5]) assert(t.includes(s), s);
  assert(t.indexOf(TITLE_1) < t.indexOf(TITLE_2) && t.indexOf(TITLE_2) < t.indexOf(TITLE_3) && t.indexOf(TITLE_3) < t.indexOf(TITLE_5));
});

test("the one item that is not here (4) is one sentence and no tick box, and its words are not listed", async () => {
  setServer();
  const main = await open();
  const t = text(section(main));
  assert(t.includes(LATER), t);
  assert(!t.includes(ITEMS[3].title), "not listed: " + ITEMS[3].title);
  assert.strictEqual(boxes(main).length, 4);
});

test("the three things that stay forbidden are said, and the section does not offer them", async () => {
  setServer();
  const main = await open();
  const t = text(section(main));
  for (const s of NEVER) assert(t.includes(s), s);
  assert(/全部.*勾/.test(t) || /就算/.test(t), "says it holds even when everything is ticked: " + t);
});

test("a tick that the server holds is shown as ticked, the other is not", async () => {
  setServer({ autonomy: { create_cards: false, dispatch: true } });
  const main = await open();
  assert.strictEqual(box(main, "create_cards").checked, false);
  assert.strictEqual(box(main, "dispatch").checked, true);
});

test("ticking opens a dialog first: nothing is sent until 「我了解，打開」", async () => {
  setServer();
  const main = await open();
  await tick(box(main, "create_cards"), true);
  const d = dialog();
  assert(d, "a dialog opened");
  assert.strictEqual(posts().length, 0, "nothing sent yet");
  const t = text(d);
  assert(t.includes(TITLE_1), t);
  assert(t.includes(EFFECT_1), t);
  assert(t.includes("US$0.30"), "what the chief of staff costs at most: " + t);
  assert(t.includes("US$0.50"), "what a step costs at most: " + t);
  assert(t.includes("US$3.00") && t.includes("每天上限"), "and the day they all share: " + t);
  assert(t.includes("AI 自己做了什麼") && /停止|撤回/.test(t), t);
  for (const s of NEVER) assert(t.includes(s), s);
  assert(button(d, "我了解，打開"), "the button says what it does");
  assert(button(d, "取消"));
  await (async () => { button(d, "我了解，打開").dispatch("click"); await settle(); })();
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/settings/autonomy", { create_cards: true, dispatch: false, routines: false, auto_continue: false }]]);
  assert.strictEqual(box(main, "create_cards").checked, true);
  assert.strictEqual(box(main, "dispatch").checked, false);
  assert(!posts().some((c) => c[1] === "/api/config"), "never through the config route");
});

test("the second item's dialog has its own words and sends both values", async () => {
  setServer({ autonomy: { create_cards: true, dispatch: false } });
  const main = await open();
  await tick(box(main, "dispatch"), true);
  const d = dialog();
  assert(text(d).includes(TITLE_2) && text(d).includes(EFFECT_2));
  button(d, "我了解，打開").dispatch("click");
  await settle();
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ create_cards: true, dispatch: true, routines: false, auto_continue: false }]);
});

test("the third item (routines) has its own dialog words and sends all four values", async () => {
  setServer();
  const main = await open();
  await tick(box(main, "routines"), true);
  const d = dialog();
  assert(text(d).includes(TITLE_3) && text(d).includes(EFFECT_3));
  assert(text(d).includes("另外在「例行工作」頁設定"), "says where the routines' own daily limit is set");
  assert.strictEqual(posts().length, 0);
  button(d, "我了解，打開").dispatch("click");
  await settle();
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ create_cards: false, dispatch: false, routines: true, auto_continue: false }]);
  assert.strictEqual(box(main, "routines").checked, true);
});

test("the fifth item (auto_continue) has its own dialog words, says the limits, and sends all four values", async () => {
  setServer();
  const main = await open();
  await tick(box(main, "auto_continue"), true);
  const d = dialog();
  assert(text(d).includes(TITLE_5) && text(d).includes(EFFECT_5));
  assert(text(d).includes("每份派工最多自己接續 3 次") && text(d).includes("每天") && text(d).includes("10 分鐘"), "says the limits it keeps: " + text(d));
  assert(text(d).includes("群組"), "says a group never goes on by itself");
  assert.strictEqual(posts().length, 0);
  button(d, "我了解，打開").dispatch("click");
  await settle();
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ create_cards: false, dispatch: false, routines: false, auto_continue: true }]);
  assert.strictEqual(box(main, "auto_continue").checked, true);
});

test("cancelling leaves the tick off and sends nothing", async () => {
  setServer();
  const main = await open();
  await tick(box(main, "dispatch"), true);
  button(dialog(), "取消").dispatch("click");
  await settle();
  assert.strictEqual(posts().length, 0);
  assert.strictEqual(box(main, "dispatch").checked, false);
  assert.strictEqual(dialog(), null, "the dialog is gone");
});

test("turning one off needs no dialog and sends at once", async () => {
  setServer({ autonomy: { create_cards: true, dispatch: true } });
  const main = await open();
  await tick(box(main, "create_cards"), false);
  assert.strictEqual(dialog(), null);
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ create_cards: false, dispatch: true, routines: false, auto_continue: false }]);
  assert.strictEqual(box(main, "create_cards").checked, false);
  assert.strictEqual(box(main, "dispatch").checked, true);
});

test("a refusal from the server leaves the tick as it was and does not claim it is on", async () => {
  setServer({ post: () => jsonResponse({ error: "設定檔壞了" }, false, 409) });
  const main = await open();
  await tick(box(main, "create_cards"), true);
  button(dialog(), "我了解，打開").dispatch("click");
  await settle();
  assert.strictEqual(posts().length, 1);
  assert.strictEqual(box(main, "create_cards").checked, false);
});

test("when the setting cannot be read the section says unknown and offers no tick box", async () => {
  setServer({ getFails: true });
  const main = await open();
  assert(section(main), "the section is still there");
  assert.strictEqual(boxes(main).length, 0);
  assert(text(section(main)).includes("未知"), text(section(main)));
});

test("the section links to 「AI 自己做了什麼」 (#/actions), whether or not the setting could be read", async () => {
  for (const over of [{}, { getFails: true }]) {
    setServer(over);
    const main = await open();
    const link = section(main).find((n) => n.tag === "a" && attr(n, "data-autonomy") === "actions-link");
    assert(link, JSON.stringify(over));
    assert.strictEqual(attr(link, "href"), "#/actions");
    assert(text(link).includes("AI 自己做了什麼"));
  }
});

test("looking at the page writes nothing", async () => {
  setServer();
  await open();
  assert.strictEqual(posts().length, 0);
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, never writes through /api/config", () => {
  assert(BLOCK.length > 300, "the block is marked in app.js");
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(BLOCK));
  assert(!/api\/config/.test(BLOCK));
  assert(BLOCK.includes("我了解，打開"));
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
