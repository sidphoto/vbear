// P41-1 / P41-3: the group pages: the list with groups among the chats, the dialog for a new group (two or three employees, the words that say what
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
  can: { send: true, why_not_send: null, stop: false, continue: false, drop: false, edit_members: true, delete: true }, ...over });

// P41-3: what the page asks of a member's own chat (the live part: the words being written and the cards that wait) and what it posts
const A_CHAT = "c-" + "a".repeat(16), B_CHAT = "c-" + "b".repeat(16);
const KID = "k-" + "a".repeat(16);
const chatCard = (over = {}) => ({ card_id: KID, token: "t".repeat(32), turn: 1, tool: "Bash", input: { command: "ls -a", description: "list" },
  editable: "command", reason: "Bash 每次都問", expires_in: 290, ...over });
const codexCommand = (over = {}) => chatCard({ tool: "command", editable: "command", reason: "Codex 要執行指令",
  input: { command: "/bin/zsh -lc 'ls -a'", cwd: ".", actions: [{ type: "listFiles", command: "ls -a" }] }, ...over });
const codexFile = (over = {}) => chatCard({ tool: "file_change", editable: "content", reason: "Codex 要改檔案",
  input: { changes: [{ path: "notes.txt", kind: "add", diff: "hello from codex\n" }] }, ...over });
const chatLive = (over = {}) => ({ state: "working", turn: 1, partial: "", partial_truncated: false, model: "haiku", cards: [], ...over });
const chatBody = (live, over = {}) => ({ ok: true, chat: { id: A_CHAT, profile_id: P1, created_at: 1790000000, engine: "claude-chat" },
  card: { id: P1, name: "文案小編", position: "social", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live, runtime: { available: true, message: "" }, next_after: 999999999, last_seq: 5, more: false, problem: null, group: null, ...over });
const CAN_ALL = { send: true, why_not_send: null, stop: false, continue: false, drop: false, edit_members: true, delete: true };
const running = (cur, over = {}) => detail({ group: { id: GID, name: "市集準備", created_at: 1, state: "running", problem: null },
  items: [], round: { n: 1, state: "running", to: "all", how: null, asked: [{ profile_id: P1, state: cur === B_CHAT ? "done" : "answering" }, { profile_id: P2, state: cur === B_CHAT ? "answering" : "waiting" }], pause: null },
  current: { profile_id: cur === B_CHAT ? P2 : P1, chat_id: cur, turn: 1 },
  can: { send: false, why_not_send: "大家回完之前不能再說話；可以按「停止」。", stop: true, continue: false, drop: false, edit_members: false, delete: false }, ...over });
const three = (over = {}) => detail({ members: [
  { ...member(P1, "文案小編"), engine: "claude-chat", can_chat: true, code: null, reason: null },
  { ...member(P2, "會計師"), engine: "claude-chat", can_chat: true, code: null, reason: null },
  { ...member("emp-5", "第五位"), engine: "claude-chat", can_chat: true, code: null, reason: null }], ...over });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), groups: { groups: [], problems: [] }, detail: detail(), detailStatus: 0, sendStatus: 202, sendBody: { round: 2 }, createStatus: 0,
    created: { group: row({ id: GID }), notes: [] }, chats: {}, answerStatus: 200, answerBody: { ok: true }, actionStatus: 0, actionBody: null,
    deleteStatus: 0, deleteBody: null, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/config") return jsonResponse({ ok: true, config: { advanced_mode: true } });   // P47-2: the board is the advanced part of the home page
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/groups" && method === "GET") return jsonResponse(page.groups);
    if (p === "/api/groups" && method === "POST") return page.createStatus ? jsonResponse(page.createBody, false, page.createStatus) : jsonResponse(page.created);
    let m = /^\/api\/chats\/(c-[0-9a-f]{16})$/.exec(p);
    if (m && method === "GET") return page.chats[m[1]] ? jsonResponse(page.chats[m[1]]) : jsonResponse({ error: "找不到這個聊天。", code: "not_found" }, false, 404);
    m = /^\/api\/chats\/(c-[0-9a-f]{16})\/answer$/.exec(p);
    if (m && method === "POST") return page.answerStatus < 400 ? jsonResponse(page.answerBody, true, page.answerStatus) : jsonResponse(page.answerBody, false, page.answerStatus);
    m = /^\/api\/groups\/(g-[0-9a-f]{12})\/(stop|continue|drop|rename|members)$/.exec(p);
    if (m && method === "POST") return page.actionStatus ? jsonResponse(page.actionBody, false, page.actionStatus) : jsonResponse({ ok: true });
    m = /^\/api\/groups\/(g-[0-9a-f]{12})$/.exec(p);
    if (m && method === "DELETE") return page.deleteStatus ? jsonResponse(page.deleteBody, false, page.deleteStatus) : jsonResponse({ ok: true });
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

// ---- P41-3: the @ buttons, the line about the money, and what is sent -----------------------------------------------

const toButtons = (main) => qa(main, "to-pick");
const pressed = (b) => b.getAttribute("aria-pressed") === "true";
const typeInto = (box, words) => { box.value = words; box.dispatch("input"); };

test("the buttons over the box: 大家 and one @ for each member; 大家 is chosen at the start and says so", async () => {
  setPage();
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(text(q(main, "to-all")), "大家");
  assert.strictEqual(pressed(q(main, "to-all")), true);
  const picks = toButtons(main);
  assert.deepStrictEqual(picks.map(text), ["@文案小編", "@會計師"], "in the order of the answers");
  assert(picks.every((b) => !pressed(b)));
});

test("pointing at someone: 大家 and the @ buttons shut each other out, and the words go to exactly the ones chosen, in the group's order", async () => {
  setPage({ detail: three() });
  const main = await open("#/chat/group/" + GID);
  const pick = (id) => toButtons(main).find((b) => b.getAttribute("data-profile-id") === id);
  pick(P2).click();                                   // the second one first
  assert.strictEqual(pressed(q(main, "to-all")), false, "大家 lets go when someone is pointed at");
  assert.strictEqual(pressed(pick(P2)), true);
  pick("emp-5").click();
  pick(P1).click();
  assert.deepStrictEqual(toButtons(main).map(pressed), [true, true, true]);
  pick(P1).click();                                   // not wanted any more
  q(main, "input").value = "請你們兩位看一下";
  q(main, "send").click();
  await settle();
  assert.deepStrictEqual(posts("/messages").map((x) => x.body), [{ text: "請你們兩位看一下", to: ["emp-2", "emp-5"] }], "the group's order, not the order clicked");
  // 大家 again clears every @
  pick(P1).click();
  q(main, "to-all").click();
  assert.strictEqual(pressed(q(main, "to-all")), true);
  assert(toButtons(main).every((b) => !pressed(b)));
  // taking off the last @ is 大家 again, never "nobody"
  pick(P2).click();
  pick(P2).click();
  assert.strictEqual(pressed(q(main, "to-all")), true);
});

test("pointing at one: the line about the money counts only the one asked, and the send says to whom", async () => {
  setPage();
  const main = await open("#/chat/group/" + GID);
  toButtons(main)[1].click();
  assert.strictEqual(text(q(main, "cost-line")), "這句會請 1 位回答（會計師），最多 US$0.50，今天還剩 US$2.71。");
  q(main, "input").value = "成本大概多少？";
  q(main, "send").click();
  await settle();
  assert.deepStrictEqual(posts("/messages").map((x) => x.body), [{ text: "成本大概多少？", to: [P2] }]);
  assert.strictEqual(pressed(q(main, "to-all")), true, "after the send the choice is 大家 again");
});

test("the line about the money counts three when it is 大家 in a group of three, and warns when the day may not be enough", async () => {
  setPage({ detail: three({ cost: { per_turn_usd: "0.5", day_left_usd: "1.2", lamp: "green", group_today_usd: "0" } }) });
  const main = await open("#/chat/group/" + GID);
  const line = text(q(main, "cost-line"));
  assert(line.startsWith("這句會請 3 位回答（文案小編、會計師、第五位），最多 US$1.50，今天還剩 US$1.20"), line);
  assert(line.includes("可能做到一半碰到每天上限，VBear 會停下來"));
  toButtons(main)[0].click();
  assert(!text(q(main, "cost-line")).includes("碰到每天上限"), "one is within what is left");
});

test("a @名字 at the start of the words chooses that button, only for a name that is exactly a member's; taking it away goes back to 大家", async () => {
  setPage({ detail: three() });
  const main = await open("#/chat/group/" + GID);
  const box = q(main, "input");
  typeInto(box, "@會計師 成本大概多少？");
  assert.deepStrictEqual(toButtons(main).map(pressed), [false, true, false]);
  assert.strictEqual(pressed(q(main, "to-all")), false);
  typeInto(box, "@會計師 @文案小編 你們兩位看一下");
  assert.deepStrictEqual(toButtons(main).map(pressed), [true, true, false]);
  typeInto(box, "@不存在的人 你好");
  assert.strictEqual(pressed(q(main, "to-all")), true, "a name that is nobody's chooses nobody");
  typeInto(box, "請問 @會計師 這個多少？");
  assert.strictEqual(pressed(q(main, "to-all")), true, "only at the start");
  typeInto(box, "@會計師 好");
  typeInto(box, "沒有點名了");
  assert.strictEqual(pressed(q(main, "to-all")), true, "the words no longer point at anyone");
  assert(toButtons(main).every((b) => !pressed(b)));
  // what the person pressed by hand is not taken away by the typing
  toButtons(main)[0].click();
  typeInto(box, "沒有點名，但我自己按了");
  assert.deepStrictEqual(toButtons(main).map(pressed), [true, false, false]);
  typeInto(box, "@會計師 好");
  q(main, "send").click();
  await settle();
  assert.deepStrictEqual(posts("/messages").map((x) => x.body), [{ text: "@會計師 好", to: [P2] }], "the server is told in `to`, never by reading the words");
});

test("a red lamp: the box cannot send and says why, whatever the server's can.send says", async () => {
  setPage({ detail: detail({ cost: { per_turn_usd: "0.5", day_left_usd: "0", lamp: "red", group_today_usd: "1.5" } }) });
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "send").disabled, true);
  assert(text(q(main, "send-note")).includes("亮紅燈"));
  q(main, "input").value = "還是想送";
  q(main, "send").click();
  await settle();
  assert.strictEqual(posts("/messages").length, 0);
});

// ---- P41-3: the employee who is answering, and the card that asks the person ---------------------------------------------

test("the one answering is named, and the words being written show as text", async () => {
  setPage({ detail: running(A_CHAT), chats: { [A_CHAT]: chatBody(chatLive({ partial: "我先準備" + EVIL })) } });
  const main = await open("#/chat/group/" + GID);
  assert(text(q(main, "answering")).includes("文案小編正在回答"));
  assert(text(q(main, "live")).includes("我先準備"));
  noMarkup(main);
  const gets = FETCH_LOG.filter((c) => c.method === "GET" && c.url.split("?")[0] === "/api/chats/" + A_CHAT);
  assert(gets.length >= 1 && gets.every((c) => c.url.endsWith("?after=999999999")), "only the live part is asked for, not the whole record");
});

test("nothing asks for a chat when no one is answering", async () => {
  setPage();
  await open("#/chat/group/" + GID);
  assert.strictEqual(FETCH_LOG.filter((c) => c.url.startsWith("/api/chats/")).length, 0);
});

test("a card that waits is drawn under the name of the employee who asks, as the same card as in a one-to-one chat", async () => {
  setPage({ detail: running(B_CHAT), chats: { [B_CHAT]: chatBody(chatLive({ state: "waiting_for_you", cards: [chatCard()] }), { chat: { id: B_CHAT, profile_id: P2, created_at: 1, engine: "claude-chat" } }) } });
  const main = await open("#/chat/group/" + GID);
  const c = q(main, "card-box");
  assert(c, "the card is on the page");
  assert(text(c).includes("會計師想執行指令（Bash）"), text(c));
  assert(text(c).includes("ls -a") && text(c).includes("要你決定"));
  assert(c.find((x) => x.getAttribute && x.getAttribute("data-chat") === "live-card"), "it is chatCardNode's card");
  assert.strictEqual(text(c.find((x) => x.getAttribute && x.getAttribute("data-chat") === "allow")), "允許這一次");
  assert(c.find((x) => x.getAttribute && x.getAttribute("data-chat") === "deny"));
});

test("pressing 允許這一次 posts that one answer to the chat of the one who asked, with the one-use token, and only that", async () => {
  setPage({ detail: running(A_CHAT), chats: { [A_CHAT]: chatBody(chatLive({ state: "waiting_for_you", cards: [chatCard()] })) } });
  const main = await open("#/chat/group/" + GID);
  for (let i = 0; i < 4; i++) await tick();
  assert.strictEqual(FETCH_LOG.filter((c) => c.url.endsWith("/answer")).length, 0, "looking at the page never answers a card");
  const live = q(main, "card-box");
  live.find((x) => x.getAttribute("data-chat") === "allow").click();
  await settle();
  const answers = FETCH_LOG.filter((c) => c.method === "POST" && c.url.endsWith("/answer"));
  assert.deepStrictEqual(answers.map((x) => [x.url, x.body]), [["/api/chats/" + A_CHAT + "/answer", { card_id: KID, token: "t".repeat(32), decision: "allow" }]]);
  for (let i = 0; i < 3; i++) await tick();
  assert.strictEqual(FETCH_LOG.filter((c) => c.url.endsWith("/answer")).length, 1, "and not again");
});

test("拒絕 and 改內容再允許 post what the person pressed and wrote, nothing else", async () => {
  setPage({ detail: running(A_CHAT), chats: { [A_CHAT]: chatBody(chatLive({ state: "waiting_for_you", cards: [chatCard()] })) } });
  const main = await open("#/chat/group/" + GID);
  q(main, "card-box").find((x) => x.getAttribute("data-chat") === "modify").click();
  await settle();
  const area = q(main, "card-box").find((x) => x.getAttribute("data-chat") === "edit");
  area.value = "ls";
  area.dispatch("input");
  q(main, "card-box").find((x) => x.getAttribute("data-chat") === "allow-edited").click();
  await settle();
  assert.deepStrictEqual(posts("/answer").map((x) => x.body), [{ card_id: KID, token: "t".repeat(32), decision: "modify", value: "ls" }]);
  q(main, "card-box").find((x) => x.getAttribute("data-chat") === "deny").click();
  await settle();
  assert.deepStrictEqual(posts("/answer").map((x) => x.body)[1], { card_id: KID, token: "t".repeat(32), decision: "deny" });
});

test("a Codex command card in the group has the warning about the sandbox, a Codex file card does not, and neither has a way to allow more than one", async () => {
  setPage({ detail: running(A_CHAT), chats: { [A_CHAT]: chatBody(chatLive({ state: "waiting_for_you", cards: [codexCommand()] })) } });
  let main = await open("#/chat/group/" + GID);
  const cmd = q(main, "card-box");
  assert(text(cmd).includes("可能在沙盒外執行"), "the warning stays");
  assert(text(cmd).includes("/bin/zsh -lc 'ls -a'"));
  setPage({ detail: running(A_CHAT), chats: { [A_CHAT]: chatBody(chatLive({ state: "waiting_for_you", cards: [codexFile()] })) } });
  main = await open("#/chat/group/" + GID);
  const file = q(main, "card-box");
  assert(file && text(file).includes("notes.txt"));
  assert(!text(file).includes("沙盒外"), "a file card has no such warning");
  const labels = main.findAll((x) => x.tag === "button").map(text).join("|");
  assert(!/都允許|全部允許|以後都|這一輪都|大家都|一次允許/.test(labels), labels);
});

test("a card the server refuses to take stays, with the server's sentence, and can be tried again", async () => {
  setPage({ detail: running(A_CHAT), chats: { [A_CHAT]: chatBody(chatLive({ state: "waiting_for_you", cards: [chatCard()] })) },
    answerStatus: 409, answerBody: { code: "expired", error: "這張卡片已經過期，視為拒絕。" } });
  const main = await open("#/chat/group/" + GID);
  q(main, "card-box").find((x) => x.getAttribute("data-chat") === "allow").click();
  await settle();
  assert(text(h.dom().toastEl).includes("過期"));
  const again = q(main, "card-box").find((x) => x.getAttribute("data-chat") === "allow");
  assert.strictEqual(again.disabled, false);
});

// ---- P41-3: stop, and a pause with 「繼續」 and 「不用了」 ----------------------------------------------------------------

const pausedView = (can) => detail({ group: { id: GID, name: "市集準備", created_at: 1, state: "paused", problem: null },
  round: { n: 1, state: "paused", to: "all", how: null, asked: [{ profile_id: P1, state: "done" }, { profile_id: P2, state: "waiting" }],
    pause: { reason: "daily_limit", until: 1790090000, text: "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；還有 1 位沒回答。" } },
  can: { send: false, why_not_send: "這一句停在這裡；請按「繼續」或「不用了」。", stop: true, continue: true, drop: true, edit_members: false, delete: false, ...can } });

test("a pause says why and has 繼續（請剩下的人回答）, 不用了 and 停止; each posts to its own route, with an empty body", async () => {
  setPage({ detail: pausedView() });
  const main = await open("#/chat/group/" + GID);
  assert(text(main).includes("本機明天 0:00 重新計算；還有 1 位沒回答"));
  assert.strictEqual(text(q(main, "continue")), "繼續（請剩下的人回答）");
  assert.strictEqual(text(q(main, "drop")), "不用了");
  assert.strictEqual(text(q(main, "stop")), "停止");
  assert.strictEqual(q(main, "stuck"), null, "the note that the buttons were not there yet is gone");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "nothing is sent by looking");
  q(main, "continue").click();
  await settle();
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "POST").map((c) => [c.url, c.body]), [["/api/groups/" + GID + "/continue", {}]]);
  q(main, "drop").click();
  await settle();
  q(main, "stop").click();
  await settle();
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "POST").map((c) => c.url.split("/").pop()), ["continue", "drop", "stop"]);
});

test("a button is only there when the server says the action is possible", async () => {
  setPage({ detail: pausedView({ continue: false, drop: false, stop: false }) });
  let main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "continue"), null);
  assert.strictEqual(q(main, "drop"), null);
  assert.strictEqual(q(main, "stop"), null);
  setPage({ detail: running(A_CHAT) });
  main = await open("#/chat/group/" + GID);
  assert.strictEqual(text(q(main, "stop")), "停止", "停止 is there while someone is answering");
  assert.strictEqual(q(main, "continue"), null, "and there is nothing to continue");
  setPage({ detail: detail() });
  main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "stop"), null, "nothing is going on: nothing to stop");
});

test("an action the server refuses shows the server's sentence and leaves the page as it was", async () => {
  setPage({ detail: pausedView(), actionStatus: 409, actionBody: { code: "not_paused", error: "這一輪已經不是暫停的了。" } });
  const main = await open("#/chat/group/" + GID);
  q(main, "continue").click();
  await settle();
  assert(text(h.dom().toastEl).includes("已經不是暫停"));
  assert(q(main, "continue"), "still there");
});

// ---- P41-3: rename, who is in the group, delete -------------------------------------------------------------------------

test("rename: the box starts from the name, 存 posts the new name, and it is only there when members may be changed", async () => {
  setPage();
  let main = await open("#/chat/group/" + GID);
  q(main, "rename").click();
  const box = q(main, "rename-input");
  assert.strictEqual(box.value, "市集準備");
  box.value = "  週末市集  ";
  q(main, "rename-save").click();
  await settle();
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "POST").map((c) => [c.url, c.body]), [["/api/groups/" + GID + "/rename", { name: "週末市集" }]]);
  setPage({ detail: running(A_CHAT) });
  main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "rename"), null);
  assert(text(q(main, "edit-note")).includes("不能"), "and it says why");
});

test("rename: the path at the top follows the new name the next time the page reads the group (P41-4, not only the title)", async () => {
  setPage();
  const main = await open("#/chat/group/" + GID);
  const path0 = () => text(main.find((x) => x.hasClass && x.hasClass("crumbs")));
  assert(path0().includes("市集準備"), path0());
  page.detail = detail({ group: { id: GID, name: "週末市集", created_at: 1790000000, state: "idle", problem: null } });
  await tick();
  assert(path0().includes("週末市集") && !path0().includes("市集準備"), path0());
  assert(path0().startsWith("聊天"), "the first step of the path is still the chat page");
});

test("who is in the group: remove one (never below two), add one who can chat (never above three), each as its own press", async () => {
  setPage({ detail: three() });
  let main = await open("#/chat/group/" + GID);
  q(main, "people").click();
  await settle();
  const rm = (id) => qa(main, "remove").find((b) => b.getAttribute("data-profile-id") === id);
  assert.strictEqual(qa(main, "remove").length, 3);
  assert.strictEqual(q(main, "add-pick").disabled, true, "three is the most: no one can be added");
  rm(P2).click();
  await settle();
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "POST").map((c) => [c.url, c.body]), [["/api/groups/" + GID + "/members", { add: [], remove: [P2] }]]);
  setPage();
  main = await open("#/chat/group/" + GID);
  q(main, "people").click();
  await settle();
  assert(qa(main, "remove").every((b) => b.disabled === true), "two is the least: no one can be removed");
  assert(text(q(main, "people-note")).includes("至少要 2 位"));
  const pick = q(main, "add-pick");
  const options = pick.findAll((x) => x.tag === "option").map((o) => o.getAttribute("value"));
  assert(options.includes(P4) && options.includes("emp-5"), options.join(","));
  assert(!options.includes(P1) && !options.includes(P2), "who is in already is not offered");
  assert(!options.includes(P3), "who cannot chat is not offered");
  pick.value = P4;
  pick.dispatch("change");
  q(main, "add").click();
  await settle();
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "POST").map((c) => [c.url, c.body]), [["/api/groups/" + GID + "/members", { add: [P4], remove: [] }]]);
});

test("delete asks first with the words of the plan, deletes only on the second press, and goes back to the list", async () => {
  setPage();
  const main = await open("#/chat/group/" + GID);
  q(main, "delete").click();
  await settle();
  const dlg = dialog();
  assert(dlg, "a question first");
  assert(text(dlg).includes("會刪掉群組和群組裡每位員工的對話紀錄；已經花的錢照記。Codex 自己保存的對話副本不會被刪。"), text(dlg));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0, "nothing is deleted by the first press");
  dlg.find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").map((c) => c.url), ["/api/groups/" + GID]);
  assert.strictEqual(global.location.hash, "#/chat");
});

test("delete: the server's refusal is shown, and the button is not there while a round is on", async () => {
  setPage({ deleteStatus: 409, deleteBody: { code: "busy", error: "有員工還在回覆。請先按停止。" } });
  let main = await open("#/chat/group/" + GID);
  q(main, "delete").click();
  await settle();
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert(text(h.dom().toastEl).includes("請先按停止"));
  assert.notStrictEqual(global.location.hash, "#/chat");
  setPage({ detail: running(A_CHAT) });
  main = await open("#/chat/group/" + GID);
  assert.strictEqual(q(main, "delete"), null);
});

// ---- P41-3: the line at the top, the lobby, a member's own chat ---------------------------------------------------------

test("the line that tells a group from a meeting from a dispatch is at the top of the page, with the way to each", async () => {
  setPage();
  const main = await open("#/chat/group/" + GID);
  const what = q(main, "what");
  assert(text(what).startsWith("群組：你說話，被叫到的員工輪流回答，員工動手前都會問你。"));
  for (const w of ["會議", "派工", "幕僚長"]) assert(text(what).includes(w), w);
  const links = what.findAll((x) => x.tag === "a").map((a) => a.getAttribute("href"));
  assert.deepStrictEqual(links, ["#/meetings", "#/dispatch"]);
  const all = main.findAll((x) => x.getAttribute && x.getAttribute("data-group"));
  const first = all.find((x) => ["what", "members", "status"].includes(x.getAttribute("data-group")));
  assert.strictEqual(first.getAttribute("data-group"), "what", "before everything else on the page");
});

test("the lobby: a group that waits for your card and a group that is paused are on 輪到你, one card each, and a group that waits for nothing is not", async () => {
  const rows = { groups: [row({ waiting: true, state: "running" }), row({ id: "g-fedcba987654", name: "暫停的群組", state: "paused" }),
    row({ id: "g-111111111111", name: "安靜的群組", state: "idle" }), row({ id: "g-222222222222", name: "壞掉的群組", state: "readonly", waiting: false })], problems: [] };
  const board = app.boardGroups({ runtime: { available: true }, sessions: [], attention: [] }, { flows: [] }, { meetings: [] }, { staffing: [] }, { dispatch: [] }, rows);
  assert.deepStrictEqual(board.yourTurnGroups.map((g) => g.id), [GID, "g-fedcba987654"]);
  assert.strictEqual(board.allEmpty, false);
  const section = app.boardSection(board);
  const turn = (Array.isArray(section) ? section : [section])[0];
  const cards = turn.findAll((x) => x.getAttribute && x.getAttribute("data-group") === "board-card");
  assert.strictEqual(cards.length, 2);
  assert(text(cards[0]).includes("市集準備") && text(cards[0]).includes("等你按允許"));
  assert(text(cards[1]).includes("暫停的群組") && text(cards[1]).includes("繼續") && text(cards[1]).includes("不用了"));
  assert.strictEqual(cards[0].find((x) => x.tag === "a").getAttribute("href"), "#/chat/group/" + GID);
  assert(text(turn).includes("1 個群組等你按允許") && text(turn).includes("1 個群組暫停"));
  const none = app.boardGroups({ runtime: { available: true }, sessions: [], attention: [] }, { flows: [] }, {}, {}, {}, { groups: [row({ state: "idle" })] });
  assert.strictEqual(none.yourTurnGroups.length, 0);
  assert.strictEqual(app.boardGroups({ runtime: { available: true } }, { flows: [] }, {}, {}, {}, { error: "壞了" }).groupsError, "壞了");
  assert.strictEqual(app.boardGroups({ runtime: { available: true } }, { flows: [] }, {}, {}, {}, undefined).groupsError, "");
});

test("the lobby's key changes when a group begins to wait, so the board repaints", () => {
  const live = { runtime: { available: true }, sessions: [], attention: [] };
  const key = (groups) => app.boardKey(app.boardGroups(live, { flows: [] }, {}, {}, {}, { groups }), { liveError: "", projects: [] });
  assert.notStrictEqual(key([row({ state: "idle" })]), key([row({ state: "paused" })]));
  assert.notStrictEqual(key([row({ state: "running", waiting: false })]), key([row({ state: "running", waiting: true })]));
});

test("the home page asks for the groups and puts the ones that wait on the board", async () => {
  setPage({ groups: { groups: [row({ waiting: true, state: "running" })], problems: [] } });
  const main = await open("#/");
  assert(FETCH_LOG.some((c) => c.url === "/api/groups"), "the lobby reads the groups");
  assert(q(main, "board-card"), "a card on the board (the advanced part of the home page)");
  const row0 = main.find((x) => x.getAttribute && x.getAttribute("data-home-row") === "group_waiting");
  assert(row0, "and a row of 等你決定, the first thing on the page");
});

test("a member's own chat opened by its address says it belongs to the group, links to it, and has no box to talk in", async () => {
  const body = chatBody(null, { group: { id: GID, name: "市集準備" } });
  setPage({ chats: { [A_CHAT]: body } });
  const main = await open("#/chat/" + A_CHAT);
  const note = main.find((x) => x.getAttribute && x.getAttribute("data-chat") === "group-note");
  assert(note && text(note).includes("這是群組「市集準備」裡的對話"), note ? text(note) : "no note");
  assert.strictEqual(note.find((x) => x.tag === "a").getAttribute("href"), "#/chat/group/" + GID);
  assert.strictEqual(main.find((x) => x.getAttribute && x.getAttribute("data-chat") === "input"), null);
  assert.strictEqual(main.find((x) => x.getAttribute && x.getAttribute("data-chat") === "send"), null);
  assert.strictEqual(main.find((x) => x.getAttribute && x.getAttribute("data-chat") === "delete"), null);
  const plain = chatBody(null, { group: null });
  setPage({ chats: { [A_CHAT]: plain } });
  await open("#/chat/" + A_CHAT);
  assert(h.dom().mainEl.find((x) => x.getAttribute && x.getAttribute("data-chat") === "input"), "an ordinary chat keeps its box");
});


// ---- the rules of the code -----------------------------------------------------------------------------------------

test("source: built with el(), no innerHTML, no emoji, no outside resource; the only way to answer a card is the one function the card's own buttons call, and nothing writes a setting", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const start = source.indexOf("// ---------- groups (v0.16, P41-1");
  const end = source.indexOf("// ---------- the chief of staff and the dispatch (v0.15, P40-5)");
  assert(start > 0 && end > start);
  const block = source.slice(start, end);
  assert(block.length > 5000);
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(block));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u.test(block), "no emoji");
  assert(!/https?:\/\//.test(block), "no outside address");
  assert(!/acceptForSession|都允許|全部允許|以後都允許|這一輪都/.test(block), "no allow-all of any kind");
  // the card is answered in one place: groupAnswerCard posts to the chat's own route, and the only caller is chatCardNode's onAnswer
  assert.strictEqual((block.match(/\/answer/g) || []).length, 1, "one place posts an answer");
  const fn = block.slice(block.indexOf("async function groupAnswerCard"));
  assert(fn.indexOf("/answer") > 0 && fn.indexOf("/answer") < fn.indexOf("\n  }\n"), "and it is that function");
  assert.strictEqual((block.match(/onAnswer: /g) || []).length, 1, "only the card's buttons are wired to it");
  assert.strictEqual((block.match(/groupAnswerCard\(/g) || []).length, 2, "its definition and the one call inside the button's handler");
  assert(!/decision: "(allow|deny|modify)"/.test(block), "the decision is whatever the card's button passed, never a value of this page");
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
