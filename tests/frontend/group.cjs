// P41-1: the group pages: the list with groups among the chats, the dialog for a new group (two or three employees, the words that say what
// is shared and where it goes), one group (the conversation, who is answering, the money, the box that is shut while a round is on) and
// the rules of the code. The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model: the
// server answers with fixtures, and every string a model could hold is tried with markup in it.
// Run: node tests/frontend/group.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const root = path.join(__dirname, "..", "..", "web");
global.document.querySelector = () => null;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-group") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-group") === key);
const EVIL = "<img src=x onerror=alert(1)>";
const noMarkup = (node) => assert.strictEqual(node.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");
const GID = "g-0123456789ab";
const P1 = "emp-1", P2 = "emp-2", P3 = "emp-3", P4 = "emp-4";

// ---- fixtures ---------------------------------------------------------------------------------------------------

const cardsList = () => [
  { id: P1, name: "文案小編", position: "social", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
  { id: P2, name: "會計師", position: "accountant", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
  { id: P3, name: "停用員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: false, can_chat: false, code: "card_disabled", reason: "這張角色卡已停用，啟用之後才能聊天。", instructions: false },
  { id: P4, name: "Codex 員工", position: "pm", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
  { id: "emp-5", name: "第五位", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
];
const support = () => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" },
  verify: { running: false }, money: "x", codex: { engine: "codex-chat", state: "ready", installed: true, version: "0.163.0", verified: true, logged_in: true, admin_policy_ok: true,
    why: "", verified_versions: ["0.163.0"], verify: { running: false }, money: "x" } });
const listing = (over = {}) => ({ ok: true, chats: [], more: 0, cards: cardsList(), support: support(), limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "", ...over });
const member = (id, name, tool = "claude") => ({ profile_id: id, name, tool });
const row = (over = {}) => ({ id: GID, name: "市集準備", members: [member(P1, "文案小編"), member(P2, "會計師")], last_at: 1790000100, last_text: "我想賣手工皂",
  state: "idle", waiting: false, problem: null, ...over });
let n = 0;
const said = (text, over = {}) => ({ seq: ++n, at: 1790000000 + n, kind: "said", round: 1, text, to: "all", to_names: null, ...over });
const reply = (name, text, over = {}) => ({ seq: ++n, at: 1790000000 + n, kind: "reply", round: 1, profile_id: name === "會計師" ? P2 : P1, name, tool: "claude", text,
  unreadable: false, reason: "result", partial: false, cost_usd: "0.12", estimate: false, chat_id: "c-" + "a".repeat(16), turn: 1, ...over });
const detail = (over = {}) => ({ group: { id: GID, name: "市集準備", created_at: 1790000000, state: "idle", problem: null },
  members: [{ ...member(P1, "文案小編"), engine: "claude-chat", can_chat: true, code: null, reason: null },
    { ...member(P2, "會計師"), engine: "claude-chat", can_chat: true, code: null, reason: null }],
  items: [], next_after: 0, last_seq: 0, more: false, round: null, current: null,
  cost: { per_turn_usd: "0.5", day_left_usd: "2.71", lamp: "green", group_today_usd: "0" },
  can: { send: true, why_not_send: null, stop: false, continue: false, drop: false, edit_members: false, delete: false }, ...over });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), groups: { groups: [], problems: [] }, detail: detail(), detailStatus: 0, sendStatus: 202, sendBody: { round: 2 }, createStatus: 0,
    created: { group: row({ id: GID }), notes: [] }, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/groups" && method === "GET") return jsonResponse(page.groups);
    if (p === "/api/groups" && method === "POST") return page.createStatus ? jsonResponse(page.createBody, false, page.createStatus) : jsonResponse(page.created);
    let m = /^\/api\/groups\/(g-[0-9a-f]{12})$/.exec(p);
    if (m && method === "GET") return page.detailStatus ? jsonResponse(page.detailBody, false, page.detailStatus) : jsonResponse(page.detail);
    m = /^\/api\/groups\/(g-[0-9a-f]{12})\/messages$/.exec(p);
    if (m && method === "POST") return page.sendStatus < 400 ? jsonResponse(page.sendBody, true, page.sendStatus) : jsonResponse(page.sendBody, false, page.sendStatus);
    return null;
  });
  FETCH_LOG.length = 0;
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = (fn) => { page.tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const posts = (suffix) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0].endsWith(suffix));
const dialog = () => h.dom().bodyEl.find((nn) => nn.hasClass && nn.hasClass("modal-backdrop"));
const tick = async () => { await page.tick(); await settle(); };

// ---- the list ------------------------------------------------------------------------------------------------------

test("groups and chats are one list, the newest first; a group says 群組, how many, and whether it waits for the person", async () => {
  setPage({ list: listing({ chats: [
    { id: "c-" + "a".repeat(16), profile_id: P1, engine: "claude-chat", created_at: 1789999000, last_at: 1790000050, last_kind: "reply", last_text: "舊的一對一", turns: 1, spent_usd: "0.1", open: false, waiting: false, problem: null },
    { id: "c-" + "b".repeat(16), profile_id: P2, engine: "claude-chat", created_at: 1789990000, last_at: 1790000300, last_kind: "reply", last_text: "最新的一對一", turns: 1, spent_usd: "0.1", open: false, waiting: false, problem: null }] }),
    groups: { groups: [row({ waiting: true, state: "running" }), row({ id: "g-fedcba987654", name: "另一個群組", last_at: 1790000200, state: "paused" })], problems: [] } });
  const main = await open("#/chat");
  const lines = main.findAll((x) => x.hasClass && x.hasClass("mt-row"));
  assert.strictEqual(lines.length, 4);
  const order = lines.map((l) => text(l));
  assert(order[0].includes("最新的一對一") && order[1].includes("另一個群組") && order[2].includes("市集準備") && order[3].includes("舊的一對一"), order.join(" | "));
  const g = qa(main, "row");
  assert.strictEqual(g.length, 2);
  const mine = g.find((x) => x.getAttribute("data-group-id") === GID);
  assert(text(q(mine, "tag")) === "群組" && text(q(mine, "count")) === "2 人");
  assert(text(mine).includes("等你") && text(mine).includes("文案小編、會計師"));
  assert.strictEqual(mine.find((x) => x.tag === "a").getAttribute("href"), "#/chat/group/" + GID);
  assert(text(g.find((x) => x.getAttribute("data-group-id") === "g-fedcba987654")).includes("暫停了"));
});

test("a group the server cannot read is in the list as read-only and a failing groups route does not break the chat list", async () => {
  setPage({ groups: { groups: [row({ state: "readonly", problem: "第 3 筆：seq 不連續" })], problems: [] } });
  const main = await open("#/chat");
  assert(text(qa(main, "row")[0]).includes("紀錄有問題"));
  setPage({ groups: { error: "x" } });
  const again = await open("#/chat");
  assert(again.find((x) => x.getAttribute && x.getAttribute("data-chat") === "open"), "the chat form is still there");
  assert.strictEqual(qa(again, "row").length, 0);
});

// ---- the dialog ----------------------------------------------------------------------------------------------------

test("the new-group button needs two employees who can chat", async () => {
  setPage({ list: listing({ cards: cardsList().slice(0, 1) }) });
  let main = await open("#/chat");
  assert.strictEqual(q(main, "new").disabled, true);
  setPage();
  main = await open("#/chat");
  assert.notStrictEqual(q(main, "new").disabled, true);
});

test("the dialog: two or three employees, one that cannot chat is shut with its reason, what is shared is said, and nothing is made until the press", async () => {
  setPage();
  const main = await open("#/chat");
  q(main, "new").click();
  await settle();
  const dlg = dialog();
  assert(dlg, "a dialog");
  assert(text(q(dlg, "share-note")).includes("員工看不到彼此的檔案") && text(q(dlg, "share-note")).includes("只看得到群組裡的對話"));
  const picks = qa(dlg, "pick");
  assert.strictEqual(picks.length, 5);
  const byId = (id) => picks.find((x) => x.getAttribute("data-profile-id") === id);
  assert.strictEqual(byId(P3).disabled, true, "the disabled card cannot be picked");
  assert(text(dlg).includes("不能加入：這張角色卡已停用"));
  assert.strictEqual(q(dlg, "create").disabled, true);
  assert(text(q(dlg, "count-note")).includes("要選 2 到 3 位"));
  byId(P1).checked = true; byId(P1).dispatch("change");
  assert.strictEqual(q(dlg, "create").disabled, true, "one is not a group");
  byId(P2).checked = true; byId(P2).dispatch("change");
  assert.strictEqual(q(dlg, "create").disabled, false);
  assert.strictEqual(text(q(dlg, "count-note")), "已選 2 位。");
  assert(!text(q(dlg, "mixed-box")).includes("Anthropic"), "two Claude Code employees: nothing goes to a second company");
  assert(q(dlg, "name").getAttribute("placeholder").includes("文案小編、會計師"), "the default name is the members' names");
  byId("emp-5").checked = true; byId("emp-5").dispatch("change");
  assert.strictEqual(byId(P4).disabled, true, "a fourth cannot be picked");
  assert.strictEqual(q(dlg, "create").disabled, false);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "nothing is made before the press");
});

test("the dialog: a Codex employee with a Claude Code one says the words go to both companies", async () => {
  setPage();
  const main = await open("#/chat");
  q(main, "new").click();
  await settle();
  const dlg = dialog();
  const byId = (id) => qa(dlg, "pick").find((x) => x.getAttribute("data-profile-id") === id);
  byId(P1).checked = true; byId(P1).dispatch("change");
  byId(P4).checked = true; byId(P4).dispatch("change");
  const mixed = text(q(dlg, "mixed-box"));
  for (const w of ["Claude Code", "Codex", "Anthropic", "OpenAI", "同時送給"]) assert(mixed.includes(w), w);
  assert(mixed.includes(app.GROUP_MIXED_NOTE));
  byId(P4).checked = false; byId(P4).dispatch("change");
  assert.strictEqual(text(q(dlg, "mixed-box")), "");
});

test("making the group sends the ids in the order picked in the list and the name only when one was typed, and opens the group", async () => {
  setPage();
  const main = await open("#/chat");
  q(main, "new").click();
  await settle();
  let dlg = dialog();
  const byId = (id) => qa(dlg, "pick").find((x) => x.getAttribute("data-profile-id") === id);
  byId(P2).checked = true; byId(P2).dispatch("change");
  byId(P1).checked = true; byId(P1).dispatch("change");
  q(dlg, "create").click();
  await settle();
  assert.deepStrictEqual(posts("/api/groups").map((x) => x.body), [{ profile_ids: [P1, P2] }], "the group's order is the list's, and no name was typed");
  assert.strictEqual(global.location.hash, "#/chat/group/" + GID);
  setPage();
  const again = await open("#/chat");
  q(again, "new").click();
  await settle();
  dlg = dialog();
  const by2 = (id) => qa(dlg, "pick").find((x) => x.getAttribute("data-profile-id") === id);
  by2(P1).checked = true; by2(P1).dispatch("change");
  by2(P2).checked = true; by2(P2).dispatch("change");
  const name = q(dlg, "name");
  name.value = "  市集準備  ";
  q(dlg, "create").click();
  await settle();
  assert.deepStrictEqual(posts("/api/groups").map((x) => x.body), [{ profile_ids: [P1, P2], name: "市集準備" }]);
});

test("a group the server refuses stays in the dialog with the server's words", async () => {
  setPage({ createStatus: 409, createBody: { code: "card_disabled", error: "這張角色卡已停用，啟用之後才能聊天。" } });
  const main = await open("#/chat");
  q(main, "new").click();
  await settle();
  const dlg = dialog();
  const byId = (id) => qa(dlg, "pick").find((x) => x.getAttribute("data-profile-id") === id);
  byId(P1).checked = true; byId(P1).dispatch("change");
  byId(P2).checked = true; byId(P2).dispatch("change");
  q(dlg, "create").click();
  await settle();
  assert(dialog(), "still open");
  assert(text(q(dialog(), "error")).includes("已停用"));
  assert.notStrictEqual(global.location.hash, "#/chat/group/" + GID);
});

// ---- one group -----------------------------------------------------------------------------------------------------

test("a group page shows the members in the order of the answers, the conversation with who said what, and what each reply cost", async () => {
  n = 0;
  setPage({ detail: detail({ items: [said("我想在週末市集賣手工皂"), reply("文案小編", "我先準備攤位照片"),
    reply("會計師", "成本大概三千", { tool: "codex", estimate: true, cost_usd: "0.01" }), { seq: ++n, at: 1, kind: "round_ended", round: 1, how: "done" }], next_after: n }) });
  const main = await open("#/chat/group/" + GID);
  const seats = qa(main, "member");
  assert.deepStrictEqual(seats.map((x) => x.getAttribute("data-profile-id")), [P1, P2], "the order of the answers");
  assert(text(seats[0]).includes("文案小編") && text(seats[0]).includes("Claude Code") && text(seats[1]).includes("會計師"));
  const said1 = q(main, "said");
  assert(text(said1).includes("你對大家說") && text(said1).includes("我想在週末市集賣手工皂") && said1.hasClass("chat-me"));
  const replies = qa(main, "reply");
  assert.strictEqual(replies.length, 2);
  assert(text(replies[0]).includes("文案小編（Claude Code）") && replies[0].hasClass("chat-them"));
  assert(text(qa(replies[0], "cost")[0]).includes("US$0.12（Claude Code 回報的估值）"));
  assert(text(qa(replies[1], "cost")[0]).includes("估計 US$0.01，不是帳單"));
  assert(text(main).includes("群組：你說話，被叫到的員工輪流回答，員工動手前都會問你。"));
  assert(text(main).includes("員工看不到彼此的檔案，只看得到群組裡的對話。"));
  assert.strictEqual(qa(main, "round-ended").length, 0, "a round that ended the normal way needs no line");
});

test("what a model wrote is text, whatever it holds", async () => {
  n = 0;
  setPage({ detail: detail({ items: [said(EVIL), reply("文案小編", EVIL + "\n<script>1</script>"), reply("會計師", "x", { name: EVIL })], next_after: n }) });
  const main = await open("#/chat/group/" + GID);
  noMarkup(main);
  assert(text(qa(main, "reply")[0]).includes(EVIL));
});

test("a reply that did not end the normal way, one that cannot be read and an empty one are said so", async () => {
  n = 0;
  setPage({ detail: detail({ items: [reply("文案小編", "說到一半", { partial: true, reason: "timeout" }), reply("會計師", null, { unreadable: true }), reply("文案小編", "")], next_after: n }) });
  const main = await open("#/chat/group/" + GID);
  const r = qa(main, "reply");
  assert(text(r[0]).includes("沒有正常做完") && text(r[0]).includes("說到一半"));
  assert(text(r[1]).includes("讀不到這則回覆"));
  assert(text(r[2]).includes("沒有文字回覆"));
});

test("grey lines: a skipped employee, a pause, a stop and a drop are in the server's words; a line of a kind this page does not know is not drawn", async () => {
  n = 0;
  setPage({ detail: detail({ items: [
    { seq: ++n, at: 1, kind: "skipped", round: 1, profile_id: P1, name: "文案小編", reason: "busy", text: "文案小編正在別的地方工作，這次沒有回答。" },
    { seq: ++n, at: 1, kind: "paused", round: 1, reason: "daily_limit", until: 1790090000, text: "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；還有 1 位沒回答。" },
    { seq: ++n, at: 1, kind: "round_ended", round: 1, how: "stopped" }, { seq: ++n, at: 1, kind: "round_ended", round: 2, how: "dropped" },
    { seq: ++n, at: 1, kind: "member_added", profile_id: P2, name: "會計師" }, { seq: ++n, at: 1, kind: "renamed", name: "新名字" },
    { seq: ++n, at: 1, kind: "something_new", text: "不認得" }], next_after: n }) });
  const main = await open("#/chat/group/" + GID);
  const body = text(q(main, "skipped")) + text(q(main, "paused")) + qa(main, "round-ended").map(text).join("");
  for (const w of ["正在別的地方工作", "每天上限 US$3", "你按了停止", "你選了「不用了」"]) assert(body.includes(w), w);
  assert(text(q(main, "member_added")).includes("會計師加入了群組") && text(q(main, "renamed")).includes("新名字"));
  assert(!text(main).includes("不認得"));
});

test("the cost line: the number asked times the per-turn limit, rounded up, what is left rounded down, and a warning when it may not be enough", () => {
  const ok = app.groupCostText(["文案小編", "會計師"], "0.5", "2.71");
  assert.strictEqual(ok.text, "這句會請 2 位回答（文案小編、會計師），最多 US$1.00，今天還剩 US$2.71。");
  assert.strictEqual(ok.over, false);
  const over = app.groupCostText(["甲", "乙", "丙"], "0.5", "1.2");
  assert.strictEqual(over.over, true);
  assert(over.text.includes("最多 US$1.50") && over.text.includes("今天還剩 US$1.20") && over.text.includes("碰到每天上限"));
  const none = app.groupCostText(["甲", "乙"], null, null);
  assert(none.text.includes("未知"));
  assert.strictEqual(app.groupCostText(["甲", "乙"], "0.333", "0.999").text.includes("US$0.67"), true, "up");
  assert(app.groupCostText(["甲", "乙"], "0.333", "0.999").text.includes("今天還剩 US$0.99"), "down");
});

test("the box says what the send will cost, and the send sends the words to everyone and nothing else", async () => {
  n = 0;
  setPage();
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(text(q(main, "cost-line")), "這句會請 2 位回答（文案小編、會計師），最多 US$1.00，今天還剩 US$2.71。");
  assert.strictEqual(text(q(main, "to-all")), "大家");
  const input = q(main, "input");
  assert.strictEqual(input.disabled, false);
  input.value = "我想在週末市集賣手工皂";
  q(main, "send").click();
  await settle();
  assert.deepStrictEqual(posts("/messages").map((x) => x.body), [{ text: "我想在週末市集賣手工皂", to: "all" }]);
  assert.strictEqual(input.value, "", "the words are cleared once sent");
});

test("a round on: the box is shut with the reason, the one who is answering is named, and new items are added once, never twice", async () => {
  n = 0;
  const base = detail({ group: { id: GID, name: "市集準備", created_at: 1, state: "running", problem: null },
    items: [said("第一句")], next_after: 1, round: { n: 1, state: "running", to: "all", how: null, asked: [{ profile_id: P1, state: "answering" }, { profile_id: P2, state: "waiting" }], pause: null },
    current: { profile_id: P1, chat_id: "c-" + "a".repeat(16), turn: 1 },
    can: { send: false, why_not_send: "大家回完之前不能再說話；可以按「停止」。", stop: false, continue: false, drop: false, edit_members: false, delete: false } });
  setPage({ detail: base });
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "input").disabled, true);
  assert.strictEqual(q(main, "send").disabled, true);
  assert(text(q(main, "send-note")).includes("大家回完之前不能再說話"));
  assert(text(q(main, "answering")).includes("文案小編正在回答"));
  assert(qa(main, "member").map(text).join("").includes("正在回答") && qa(main, "member").map(text).join("").includes("還沒輪到"));
  // the next look: the first reply arrived and the second is asked
  page.detail = { ...base, items: [reply("文案小編", "我先準備攤位照片")], next_after: 2, last_seq: 2,
    round: { ...base.round, asked: [{ profile_id: P1, state: "done" }, { profile_id: P2, state: "answering" }] }, current: { profile_id: P2, chat_id: "c-" + "b".repeat(16), turn: 1 } };
  await tick();
  assert.strictEqual(qa(main, "reply").length, 1);
  assert(text(q(main, "answering")).includes("會計師正在回答"));
  await tick();
  assert.strictEqual(qa(main, "reply").length, 1, "an item the page already has is not added again");
  assert.strictEqual(qa(main, "said").length, 1);
  const lastGet = FETCH_LOG.filter((c) => c.method === "GET" && c.url.includes("/api/groups/" + GID)).pop();
  assert(lastGet.url.endsWith("after=2"), lastGet.url);
  // the round ends: the box opens again
  page.detail = { ...base, items: [{ seq: 3, at: 1, kind: "round_ended", round: 1, how: "done" }], next_after: 3, last_seq: 3, round: { ...base.round, state: "idle" }, current: null,
    group: { ...base.group, state: "idle" }, can: { ...base.can, send: true, why_not_send: null } };
  await tick();
  assert.strictEqual(q(main, "input").disabled, false);
  assert.strictEqual(q(main, "answering"), null);
});

test("a pause says why and, because the buttons for it are not here yet, says so", async () => {
  n = 0;
  setPage({ detail: detail({ group: { id: GID, name: "市集準備", created_at: 1, state: "paused", problem: null },
    round: { n: 1, state: "paused", to: "all", how: null, asked: [{ profile_id: P1, state: "done" }, { profile_id: P2, state: "waiting" }],
      pause: { reason: "daily_limit", until: 1790090000, text: "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；還有 1 位沒回答。" } },
    can: { send: false, why_not_send: "大家回完之前不能再說話；可以按「停止」。", stop: false, continue: false, drop: false, edit_members: false, delete: false } }) });
  const main = await open("#/chat/group/" + GID);
  assert(text(main).includes("本機明天 0:00 重新計算；還有 1 位沒回答"));
  assert(text(q(main, "stuck")).includes("按鈕這一版還沒有"));
  const buttons = main.findAll((x) => x.tag === "button").map(text);
  assert.deepStrictEqual(buttons.filter((b) => /繼續|不用了|停止/.test(b)), [], "no button that does nothing");
});

test("a red lamp and a log with a problem shut the box and say why", async () => {
  setPage({ detail: detail({ cost: { per_turn_usd: "0.5", day_left_usd: "0", lamp: "red", group_today_usd: "1.5" },
    can: { send: false, why_not_send: "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算。", stop: false, continue: false, drop: false, edit_members: false, delete: false } }) });
  let main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "send").disabled, true);
  assert(text(q(main, "send-note")).includes("亮紅燈"));
  assert(text(q(main, "spent")).includes("US$1.5"));
  setPage({ detail: detail({ group: { id: GID, name: "市集準備", created_at: 1, state: "readonly", problem: "第 3 筆：seq 不連續" },
    can: { send: false, why_not_send: "群組紀錄有問題，不能再送訊息。", stop: false, continue: false, drop: false, edit_members: false, delete: false } }) });
  main = await open("#/chat/group/" + GID);
  assert(text(main).includes("群組紀錄有問題，不能再送訊息"));
  assert.strictEqual(q(main, "input").disabled, true);
});

test("a send the server refuses keeps the words in the box and shows the server's sentence", async () => {
  setPage({ sendStatus: 409, sendBody: { code: "round_open", error: "大家回完之前不能再說話；可以按「停止」" } });
  const main = await open("#/chat/group/" + GID);
  const input = q(main, "input");
  input.value = "再說一句";
  q(main, "send").click();
  await settle();
  assert.strictEqual(input.value, "再說一句");
  assert(text(q(main, "send-note")).includes("大家回完之前不能再說話"));
});

test("a group that is not there, and an id that is not one", async () => {
  setPage({ detailStatus: 404, detailBody: { code: "not_found", error: "找不到這個群組" } });
  let main = await open("#/chat/group/" + GID);
  assert(text(main).includes("找不到這個群組"));
  setPage();
  main = await open("#/chat/group/not-a-group");
  assert(text(main).includes("找不到這個群組"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.url.includes("/api/groups/")).length, 0, "an id that is not one is not asked for");
});

test("leaving the page stops the polling", async () => {
  setPage();
  const cleared = [];
  const realClear = global.clearInterval;
  global.clearInterval = (t) => { cleared.push(t); };
  try {
    await open("#/chat/group/" + GID);
    await open("#/chat");
  } finally { global.clearInterval = realClear; }
  assert(cleared.length >= 1);
});

// ---- the rules of the code -----------------------------------------------------------------------------------------

test("source: built with el(), no innerHTML, no emoji, no outside resource, never answers an employee's card or writes a setting", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const start = source.indexOf("// ---------- groups (v0.16, P41-1");
  const end = source.indexOf("// ---------- the chief of staff and the dispatch (v0.15, P40-5)");
  assert(start > 0 && end > start);
  const block = source.slice(start, end);
  assert(block.length > 5000);
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(block));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u.test(block), "no emoji");
  assert(!/https?:\/\//.test(block), "no outside address");
  assert(!/\/answer|acceptForSession|都允許|大家都允許|以後都允許/.test(block), "no way to answer a card, and no allow-all");
  assert(!/\/api\/config|\/api\/setup|\/api\/settings|\/api\/native/.test(block), "no setting is written from here");
  assert(!/method: "(PUT|PATCH)"/.test(block));
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  assert(!emoji.test(css));
  for (const sel of [".group-members", ".group-avatar", ".group-pick"]) assert(css.includes(sel), sel);
});

// ---- run ---------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  await settle();     // the page's first route ran against no server when the app was loaded; let it finish
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
