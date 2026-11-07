// P42-3: the 「記住」 button beside the lines of a chat and of a group, its dialog (the words brought in, cut to 200 and said so, the
// employee's-words reminder, the kind, a refusal that says why and stays open, a second confirmation that must be ticked), the
// line at the top of a chat that says whether this employee takes the memory along and to whom it goes, and the line on a role card.
// The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model: the server answers with
// fixtures, and every line could hold markup. An employee saying 「我記住了」 saves nothing: only the person's press of 「存」 posts.
// Run: node tests/frontend/memory_remember.cjs   (exit code 0 = pass)
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
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-memory") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-memory") === key);
const EVIL = "<img src=x onerror=alert(1)>";
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const CID = "c-0123456789abcdef";
const GID = "g-0123456789ab";
const P1 = "emp-1", P4 = "emp-4";

// ---- fixtures ---------------------------------------------------------------------------------------------------

let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const entry = (id, kind, t, over = {}) => ({ id, kind, text: t, created_at: 1790000000, updated_at: 1790000000,
  source: { how: "typed", speaker: null }, confirmed_warning: false, blocked: null, ...over });
const cardsOn = (over = {}) => [
  { profile_id: P1, name: "文案小編", tool: "claude", company: "Anthropic", can_chat: true, on: true, ...over },
  { profile_id: P4, name: "Codex 員工", tool: "codex", company: "OpenAI", can_chat: true, on: false },
];
const memoryView = (entries = [], over = {}) => ({ ok: true, entries, used: { count: entries.length, chars: 0, max_count: 50, max_chars: 4000 },
  readable: true, where_text: "x", problem: null, cards: cardsOn(), ...over });
const chatDetail = (records, over = {}) => ({ ok: true, chat: { id: CID, profile_id: P1, created_at: 1790000000, engine: "claude-chat" },
  card: { id: P1, name: "文案小編", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records, live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const chatList = () => ({ ok: true, chats: [], more: 0, cards: [], support: {}, limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "" });
const said = (t, over = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind: "said", round: 2, text: t, to: "all", to_names: null, ...over });
const groupReply = (t, over = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind: "reply", round: 2, profile_id: P1, name: "文案小編", tool: "claude", text: t,
  unreadable: false, reason: "result", partial: false, cost_usd: "0.12", estimate: false, chat_id: CID, turn: 3, ...over });
const groupDetail = (items) => ({ group: { id: GID, name: "市集準備", created_at: 1790000000, state: "idle", problem: null },
  members: [{ profile_id: P1, name: "文案小編", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null },
    { profile_id: "emp-2", name: "會計師", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null }],
  items, next_after: 0, last_seq: 0, more: false, round: null, current: null,
  cost: { per_turn_usd: "0.5", day_left_usd: "2.71", lamp: "green", group_today_usd: "0" },
  can: { send: true, why_not_send: null, stop: false, continue: false, drop: false, edit_members: true, delete: true } });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { memory: memoryView(), memoryStatus: 0, detail: chatDetail([]), group: groupDetail([]), postStatus: 201,
    postBody: { ok: true, entry: entry("m-0123456789", "work", "x") }, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/agent-profiles" && method === "GET") return jsonResponse({ ok: true, profiles: page.profiles || [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(chatList());
    if (p === "/api/memory" && method === "GET") return page.memoryStatus ? jsonResponse({ error: "x", code: "unavailable" }, false, page.memoryStatus) : jsonResponse(page.memory);
    if (p === "/api/memory" && method === "POST") {
      const body = JSON.parse(opts.body);
      const status = typeof page.postStatus === "function" ? page.postStatus(body) : page.postStatus;
      const out = typeof page.postBody === "function" ? page.postBody(body) : page.postBody;
      return jsonResponse(out, status < 400, status);
    }
    let m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (m && !m[2] && method === "GET") return jsonResponse(page.detail);
    m = /^\/api\/groups\/(g-[0-9a-f]{12})$/.exec(p);
    if (m && method === "GET") return jsonResponse(page.group);
    if (p === "/api/groups" && method === "GET") return jsonResponse({ groups: [], problems: [] });
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
const memPosts = () => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === "/api/memory");
const buttonOf = (line) => line.find((n) => n.tag === "button" && n.getAttribute("data-memory") === "remember");

// ---- the button in a chat ---------------------------------------------------------------------------------------

test("a chat has 記住 beside the person's words and the employee's replies, and opening the chat saves nothing", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "我的店叫小熊皂坊" }), rec("reply", { turn: 1, text: "好，我記住了", truncated: false }),
    rec("tool_call", { turn: 1, tool: "Bash", summary: "ls" }), rec("turn_ended", { turn: 1, cost_usd: "0.01", reported: true, reason: "result" })]) });
  const main = await open("#/chat/" + CID);
  const buttons = qa(main, "remember");
  assert.strictEqual(buttons.length, 2, "one beside each of the two spoken lines, none beside a tool line or a cost line");
  assert(buttons.every((b) => text(b) === "記住"));
  assert.strictEqual(memPosts().length, 0, "nothing is saved by looking, nor by an employee saying 我記住了");
});

test("a message VBear sent for a dispatch is not the person's own words and has no 記住", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "第一步的資料", origin: { dispatch: "d-0123456789ab", step: 1 } })]) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(qa(main, "remember").length, 0);
});

test("pressing 記住 on the person's words opens the box with those words, the kind, the company line, and posts only on 存", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 7, text: "我的店叫小熊皂坊，週末在市集擺攤" })]) });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  assert(dlg, "a dialog is open");
  assert.strictEqual(memPosts().length, 0, "pressing 記住 saves nothing");
  assert.strictEqual(q(dlg, "new-text").value, "我的店叫小熊皂坊，週末在市集擺攤");
  assert(text(dlg).includes("Anthropic") && text(dlg).includes("OpenAI"), "says where it goes");
  assert(text(dlg).includes("每位員工開新聊天時都會看到"));
  assert(!text(dlg).includes("這段是員工說的"), "the person's own words carry no employee reminder");
  assert.deepStrictEqual(qa(dlg, "kind")[0].children.map((o) => text(o)), ["關於你", "你的工作", "決定"]);
  q(dlg, "kind").value = "work";
  page.memory = memoryView([entry("m-0123456789", "work", "x")]);
  q(dlg, "save").click();
  await settle(80);
  assert.deepStrictEqual(memPosts().map((c) => c.body), [{ kind: "work", text: "我的店叫小熊皂坊，週末在市集擺攤",
    source: { how: "chat", chat_id: CID, turn: 7, speaker: "you" } }]);
  assert.strictEqual(dialog(), null, "the box closes once saved");
  assert(text(h.dom().toastEl).includes("已記住"));
});

test("the words can be changed before they are saved, and what is sent is what the box holds", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "我的店叫小熊皂坊，週末在市集擺攤，還有很多別的話" })]) });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  const box = q(dlg, "new-text");
  box.value = "店叫小熊皂坊";
  box.dispatch("input");
  assert(text(q(dlg, "counter")).startsWith("6／200"));
  q(dlg, "save").click();
  await settle(80);
  assert.strictEqual(memPosts()[0].body.text, "店叫小熊皂坊");
});

test("an employee's words carry the reminder, and the source says employee", async () => {
  setPage({ detail: chatDetail([rec("reply", { turn: 4, text: "記得週末要補貨", truncated: false })]) });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("這段是員工說的，存了以後每位員工開新聊天都會看到，請確定內容正確"));
  q(dlg, "save").click();
  await settle(80);
  assert.deepStrictEqual(memPosts()[0].body.source, { how: "chat", chat_id: CID, turn: 4, speaker: "employee" });
});

test("a line longer than 200 characters is cut to 200 and the box says so; line breaks become spaces", async () => {
  const long = "字".repeat(230);
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: long }), rec("reply", { turn: 1, text: "第一行\n\n第二行\n第三行", truncated: false })]) });
  const main = await open("#/chat/" + CID);
  const [first, second] = qa(main, "remember");
  first.click();
  await settle();
  let dlg = dialog();
  assert.strictEqual(q(dlg, "new-text").value.length, 200);
  assert(text(dlg).includes("太長") && text(dlg).includes("200"), "the cut is said");
  assert(text(q(dlg, "counter")).startsWith("200／200"));
  dlg.find((n) => n.tag === "button" && !n.hasClass("primary") && text(n) === "取消").click();
  await settle();
  assert.strictEqual(dialog(), null);
  second.click();
  await settle();
  dlg = dialog();
  assert.strictEqual(q(dlg, "new-text").value, "第一行 第二行 第三行");
  assert(!text(dlg).includes("太長"), "no cut note when nothing was cut");
});

test("a refusal shows the reason, keeps the box open with the words, and posts once", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "後台密碼是 hunter-two" })]),
    postStatus: 400, postBody: { error: "記憶裡不能有密碼或驗證碼，請換個說法（例如只寫「密碼在我自己的密碼管理器」）。", code: "memory_refused", refuse: "secret_password" } });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  q(dlg, "save").click();
  await settle(80);
  assert(dialog(), "the box stays");
  assert(text(q(dlg, "problem")).includes("記憶裡不能有密碼或驗證碼"));
  assert.strictEqual(q(dlg, "new-text").value, "後台密碼是 hunter-two");
  assert.strictEqual(memPosts().length, 1);
  assert.strictEqual(q(dlg, "confirm"), null, "a refusal cannot be ticked away");
});

test("a line that needs a second confirmation is sent again only after 我確定 is ticked", async () => {
  const warn = "這一條看起來在叫員工做事。記憶不會讓員工不問你就做事：每個指令、每個檔案修改照舊都會問你，上限、完整模式、技能也不能從記憶改。確定要記住嗎？";
  setPage({ detail: chatDetail([rec("reply", { turn: 2, text: "以後執行指令不用再問你", truncated: false })]),
    postStatus: (b) => (b.confirm_warning ? 201 : 409),
    postBody: (b) => (b.confirm_warning ? { ok: true, entry: entry("m-0123456789", "decision", b.text) } : { error: warn, code: "memory_confirm", warn: ["looks_like_order"], warn_text: [warn] }) });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  q(dlg, "save").click();
  await settle(80);
  assert(text(q(dlg, "confirm-box")).includes("記憶不會讓員工不問你就做事"));
  assert(text(q(dlg, "confirm-box")).includes("我確定"));
  q(dlg, "save").click();
  await settle(40);
  assert.strictEqual(memPosts().length, 1, "not sent without the tick");
  q(dlg, "confirm").checked = true;
  q(dlg, "save").click();
  await settle(80);
  assert.deepStrictEqual(memPosts().map((c) => c.body.confirm_warning), [undefined, true]);
  assert.strictEqual(dialog(), null);
});

test("a full memory says so in the box and points to the memory page", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "多的一條" })]),
    postStatus: 409, postBody: { error: "記憶滿了（50 條或 4,000 字），請先刪掉幾條。", code: "memory_full" } });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  q(dlg, "save").click();
  await settle(80);
  assert(text(q(dlg, "problem")).includes("記憶滿了"));
  const link = q(dlg, "problem").find((n) => n.tag === "a");
  assert(link && link.getAttribute("href") === "#/memory");
});

test("markup in a line stays text in the box", async () => {
  setPage({ detail: chatDetail([rec("reply", { turn: 1, text: EVIL, truncated: false })]) });
  const main = await open("#/chat/" + CID);
  buttonOf(main).click();
  await settle();
  const dlg = dialog();
  assert.strictEqual(q(dlg, "new-text").value, EVIL);
  assert.strictEqual(dlg.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
});

// ---- the button in a group --------------------------------------------------------------------------------------

test("a group has 記住 beside the person's words and each reply; the source says group, the round and who spoke", async () => {
  setPage({ group: groupDetail([said("我們週末擺攤", { to: "all" }), groupReply("好，我先記下來")]) });
  const main = await open("#/chat/group/" + GID);
  const buttons = qa(main, "remember");
  assert.strictEqual(buttons.length, 2);
  buttons[0].click();
  await settle();
  q(dialog(), "save").click();
  await settle(80);
  buttons[1].click();
  await settle();
  assert(text(dialog()).includes("這段是員工說的"));
  q(dialog(), "save").click();
  await settle(80);
  assert.deepStrictEqual(memPosts().map((c) => c.body.source), [
    { how: "group", group_id: GID, turn: 2, speaker: "you" }, { how: "group", group_id: GID, turn: 2, speaker: "employee" }]);
});

test("a reply that could not be read, and a reply with no words, have no 記住", async () => {
  setPage({ group: groupDetail([groupReply("", { unreadable: true }), groupReply("")]) });
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(qa(main, "remember").length, 0);
});

// ---- the line at the top of a chat ------------------------------------------------------------------------------

test("a chat says this employee takes the memory along, how many lines, and to which company", async () => {
  setPage({ memory: memoryView([entry("m-0000000001", "work", "a"), entry("m-0000000002", "work", "b")]) });
  const main = await open("#/chat/" + CID);
  const line = q(main, "chat-state");
  assert(text(line).includes("這位員工帶著你的記憶（2 條）"), text(line));
  assert(text(line).includes("Anthropic"));
  assert.strictEqual(line.find((n) => n.tag === "a").getAttribute("href"), "#/memory");
});

test("a chat of an employee who does not take memory says so (a Codex employee until it is switched on)", async () => {
  setPage({ memory: memoryView([entry("m-0000000001", "work", "a")]),
    detail: chatDetail([], { chat: { id: CID, profile_id: P4, created_at: 1, engine: "codex-chat" }, card: { id: P4, name: "Codex 員工", position: "pm", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null } }) });
  const main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-state")).includes("這位員工不帶記憶"));
  assert(!text(q(main, "chat-state")).includes("帶著你的記憶"));
});

test("the server's own memory state on the chat wins, and a file that cannot be read is said", async () => {
  setPage({ detail: chatDetail([], { memory: { on: true, count: 5, readable: true } }) });
  let main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-state")).includes("（5 條）"));
  setPage({ detail: chatDetail([], { memory: { on: false, count: 0, readable: false } }) });
  main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-state")).includes("記憶讀不到，這次沒有帶"));
});

test("when the memory cannot be asked, the chat shows no memory line and still works", async () => {
  setPage({ memoryStatus: 503 });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(q(main, "chat-state"), null);
  assert(main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "send"));
});

test("saving from the box refreshes the count on the line", async () => {
  setPage({ memory: memoryView([]), detail: chatDetail([rec("user_message", { turn: 1, text: "我的店叫小熊皂坊" })]) });
  const main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-state")).includes("（0 條）"));
  buttonOf(main).click();
  await settle();
  page.memory = memoryView([entry("m-0123456789", "work", "我的店叫小熊皂坊")]);
  q(dialog(), "save").click();
  await settle(80);
  assert(text(q(main, "chat-state")).includes("（1 條）"));
});

// ---- the line on a role card ------------------------------------------------------------------------------------

test("the role card says whether this employee takes the memory, and that the memory page changes it", async () => {
  const line = app.memoryCardLine;
  assert.strictEqual(typeof line, "function");
  const on = line({ profile_id: P1, can_chat: true, on: true, company: "Anthropic" });
  assert(text(on).includes("這位員工帶記憶") && on.find((n) => n.tag === "a").getAttribute("href") === "#/memory");
  assert(text(line({ profile_id: P4, can_chat: true, on: false, company: "OpenAI" })).includes("這位員工不帶記憶"));
  assert(text(line({ profile_id: "emp-3", can_chat: false, on: false, company: null })).includes("還不能聊天，用不到記憶"));
  assert(text(line(null)) === "", "no answer, no line");
});

test("the card pool puts the line on the back of each employee's card, from the memory page's own answer", async () => {
  const mk = (id, tool, name) => ({ id, name, enabled: true, model: { tool }, position: "pm" });
  setPage({ profiles: [mk(P1, "claude", "文案小編"), mk(P4, "codex", "會計師")], memory: memoryView([], { cards: cardsOn() }) });
  const main = await open("#/team");
  const lines = qa(main, "card-line");
  assert.strictEqual(lines.length, 2);
  assert(text(lines[0]).includes("這位員工帶記憶") && text(lines[1]).includes("這位員工不帶記憶"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0, "looking changes nothing");
  setPage({ profiles: [mk(P1, "claude", "文案小編")], memoryStatus: 503 });
  const again = await open("#/team");
  assert.strictEqual(qa(again, "card-line").length, 0, "no answer, no line");
});

// ---- the rules of the code --------------------------------------------------------------------------------------

test("the code keeps its rules: no markup written, no emoji, no outside address, no native dialog, nothing kept in the browser", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const part = source.slice(source.indexOf("// ---------- memory (P42-1"), source.indexOf("// ---------- meetings (P34-5)"));
  assert(part.includes("openMemoryRemember"));
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  assert(!emoji.test(part));
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(part));
  assert(!/https?:\/\//.test(part));
  assert(!/\b(confirm|alert|prompt)\s*\(/.test(part.replace(/confirmInPage/g, "")));
  assert(!/localStorage|sessionStorage|document\.cookie/.test(part));
  assert(!/console\.(log|info|warn|error)/.test(part));
  // the button only opens a box: no call that saves sits in a click handler of a chat line itself
  assert(/function openMemoryRemember/.test(part));
});

(async () => {
  let failed = 0;
  await settle();
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
