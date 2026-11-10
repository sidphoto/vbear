// P44-1: the skills page (#/my-skills), 「用技能」 beside the box of a chat and of a group (it only puts the words in the box: nothing is
// sent), 「存成技能」 beside a spoken line (an employee's words need a tick), and the rules of the code. The real web/app.js on a synthetic
// DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model: the server answers with fixtures, and every name and text
// could hold markup. A skill is only the words the person sends: nothing posts to a chat before the person's own press of 送出.
// Run: node tests/frontend/my_skills.cjs   (exit code 0 = pass)
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
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-skill") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-skill") === key);
const EVIL = "<img src=x onerror=alert(1)>";
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const CID = "c-0123456789abcdef";
const GID = "g-0123456789ab";
const P1 = "emp-1";
const STEPS = "第一步：整理昨天的銷售。\n第二步：寫成一段話。";

let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const skill = (id, name, t, over = {}) => ({ id, name, text: t, source: { how: "typed" }, created_at: 1790000000, updated_at: 1790000000, ...over });
const book = (skills = [], over = {}) => ({ ok: true, skills, used: { count: skills.length }, limits: { max_skills: 100, max_name: 40, max_text: 4000 },
  readable: true, problem: null, ...over });
const chatDetail = (records, over = {}) => ({ ok: true, chat: { id: CID, profile_id: P1, created_at: 1790000000, engine: "claude-chat" },
  card: { id: P1, name: "文案小編", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records, live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const chatList = () => ({ ok: true, chats: [], more: 0, cards: [], support: {}, limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "" });
const said = (t, over = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind: "said", round: 2, text: t, to: "all", to_names: null, ...over });
const groupReply = (t, over = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind: "reply", round: 2, profile_id: P1, name: "文案小編", tool: "claude", text: t,
  unreadable: false, reason: "result", partial: false, cost_usd: "0.12", estimate: false, chat_id: CID, turn: 3, ...over });
const groupDetail = (items) => ({ group: { id: GID, name: "市集準備", created_at: 1790000000, state: "idle", problem: null },
  members: [{ profile_id: P1, name: "文案小編", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null }],
  items, next_after: 0, last_seq: 0, more: false, round: null, current: null,
  cost: { per_turn_usd: "0.5", day_left_usd: "2.71", lamp: "green", group_today_usd: "0" },
  can: { send: true, why_not_send: null, stop: false, continue: false, drop: false, edit_members: true, delete: true } });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { book: book(), bookStatus: 0, bookBody: null, postStatus: 201, postBody: { ok: true, skill: skill("k-0123456789ab", "x", "y") }, deleteStatus: 200,
    editStatus: 200, editBody: { ok: true, skill: skill("k-0000000001ab", "x", "y") }, detail: chatDetail([]), group: groupDetail([]), ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/agent-profiles" && method === "GET") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(chatList());
    if (p === "/api/groups" && method === "GET") return jsonResponse({ groups: [], problems: [] });
    if (p === "/api/memory" && method === "GET") return jsonResponse({ ok: true, entries: [], used: { count: 0 }, readable: true, cards: [] });
    if (p === "/api/my-skills" && method === "GET") return page.bookStatus ? jsonResponse(page.bookBody || { error: "x", code: "unavailable" }, false, page.bookStatus) : jsonResponse(page.book);
    if (p === "/api/my-skills" && method === "POST") {
      const b = JSON.parse(opts.body);
      const status = typeof page.postStatus === "function" ? page.postStatus(b) : page.postStatus;
      const out = typeof page.postBody === "function" ? page.postBody(b) : page.postBody;
      return jsonResponse(out, status < 400, status);
    }
    let m = /^\/api\/my-skills\/(k-[0-9a-f]{12})$/.exec(p);
    if (m && method === "POST") {
      const b = JSON.parse(opts.body);
      const status = typeof page.editStatus === "function" ? page.editStatus(b) : page.editStatus;
      const out = typeof page.editBody === "function" ? page.editBody(b) : page.editBody;
      return jsonResponse(out, status < 400, status);
    }
    m = /^\/api\/my-skills\/(k-[0-9a-f]{12})\/delete$/.exec(p);
    if (m && method === "POST") return page.deleteStatus < 400 ? jsonResponse({ ok: true, deleted: m[1] }) : jsonResponse({ error: "找不到這個技能。", code: "not_found" }, false, page.deleteStatus);
    m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (m && !m[2] && method === "GET") return jsonResponse(page.detail);
    m = /^\/api\/groups\/(g-[0-9a-f]{12})$/.exec(p);
    if (m && method === "GET") return jsonResponse(page.group);
    if (page.suggest) { const got = page.suggest(p, method, opts && opts.body ? JSON.parse(opts.body) : null); if (got) return got; }
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
const skillPosts = () => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0].startsWith("/api/my-skills"));
const sendsToAChat = () => FETCH_LOG.filter((c) => c.method !== "GET" && /\/api\/(chats|groups)\//.test(c.url) && /\/messages/.test(c.url));
const saveButtons = (main) => qa(main, "save-line");

// ---- the page ---------------------------------------------------------------------------------------------------

test("the page says first what a skill is and that it is not a skill card, and has a link in the navigation", async () => {
  setPage();
  const main = await open("#/my-skills");
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "常用做法");
  assert(text(main).includes("這裡是你存在 VBear 的做法。用的時候會變成你對員工說的話；員工照舊每個指令、每個檔案修改都會問你。"));
  assert(text(q(main, "not-cards")).includes("『AI 工具的外掛清單』列的是 AI 工具自己的技能檔，是另一回事。"));
  assert.strictEqual(q(main, "not-cards").find((n) => n.tag === "a").getAttribute("href"), "#/skills");
  assert(text(q(main, "none")).includes("還沒有存任何常用做法"));
  assert(text(q(main, "used")).includes("0／100"));
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  // (P47-1) the page has no item of its own in the menu now: it is a page of 工作 and lights that item
  assert(/<a href="#\/work" data-nav="work">[^<]*<span aria-hidden="true">[^<]*<\/span>工作<\/a>/.test(html));
  const appSrc = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(/"my-skills": "work"/.test(appSrc.slice(appSrc.indexOf("const NAV_PARENT = {"), appSrc.indexOf("const ADVANCED_NAV"))), "lights 工作");
});

test("the skills are listed with the name, the first 80 characters, where they came from and when; markup stays text", async () => {
  const long = "字".repeat(100);
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS), skill("k-000000000002", EVIL, long, { source: { how: "reply", chat_id: CID } }),
    skill("k-000000000003", "整理的", EVIL, { source: { how: "suggested", suggestion_id: "ks-0123456789ab" } })]) });
  const main = await open("#/my-skills");
  const rows = qa(main, "item");
  assert.strictEqual(rows.length, 3);
  assert.deepStrictEqual(rows.map((r) => text(q(r, "title"))), ["市集日報", EVIL, "整理的"]);
  assert.strictEqual(text(q(rows[0], "preview")), "第一步：整理昨天的銷售。 第二步：寫成一段話。");
  assert.strictEqual(text(q(rows[1], "preview")), "字".repeat(80) + "…");
  assert(text(q(rows[0], "meta")).startsWith("你寫的"));
  assert(text(q(rows[1], "meta")).startsWith("從員工說的話存的"));
  assert(text(q(rows[2], "meta")).startsWith("整理提議、你確認的"));
  assert(text(q(main, "used")).includes("3／100"));
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");
});

test("a file that cannot be read is said, with no form and no guessed list; a page that cannot be asked says so", async () => {
  setPage({ book: book([], { readable: false, problem: "技能的檔案有問題，VBear 先不碰它。" }) });
  let main = await open("#/my-skills");
  assert(text(main).includes("技能的檔案有問題"));
  assert.strictEqual(qa(main, "item").length, 0);
  assert.strictEqual(qa(main, "save").length, 0, "nothing to save into");
  setPage({ bookStatus: 503, bookBody: { error: "VBear 的背景程式現在連不上。", code: "unavailable" } });
  main = await open("#/my-skills");
  assert(text(main).includes("讀不到常用做法"));
});

test("adding sends the name and the text as typed, clears the form and reloads", async () => {
  setPage();
  const main = await open("#/my-skills");
  q(main, "name").value = "市集日報";
  q(main, "text").value = STEPS;
  q(main, "text").dispatch("input");
  assert(text(q(main, "counter")).includes("名稱 4／40 字、內容 23／4000 字"), text(q(main, "counter")));
  page.book = book([skill("k-0123456789ab", "市集日報", STEPS)]);
  q(main, "save").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => [c.url, c.body]), [["/api/my-skills", { name: "市集日報", text: STEPS }]]);
  assert.strictEqual(qa(main, "item").length, 1);
  assert.strictEqual(q(main, "name").value, "", "the form is empty again");
  assert(text(h.dom().toastEl).includes("已存成常用做法"));
});

test("a refusal says why and keeps the words; a second yes must be ticked before the same words are sent again", async () => {
  const warn = "這段看起來像在叫員工不問你就做事。確定要存嗎？";
  setPage({ postStatus: (b) => (/密碼/.test(b.text) ? 400 : b.confirm_warning ? 201 : 409),
    postBody: (b) => (/密碼/.test(b.text) ? { error: "技能裡不能有密碼或驗證碼，請換個說法。", code: "skill_refused", refuse: "secret_password", field: "text" }
      : b.confirm_warning ? { ok: true, skill: skill("k-0123456789ab", b.name, b.text) } : { error: warn, code: "confirm_warning", warn: ["looks_like_order"], warn_text: [warn] }) });
  const main = await open("#/my-skills");
  q(main, "name").value = "快";
  q(main, "text").value = "後台密碼是 hunter-two";
  q(main, "save").click();
  await settle(80);
  assert(text(q(main, "problem")).includes("技能裡不能有密碼"));
  assert.strictEqual(q(main, "text").value, "後台密碼是 hunter-two", "the words stay");
  assert.strictEqual(q(main, "confirm"), null, "a refusal cannot be ticked away");
  q(main, "text").value = "以後不用問我";
  q(main, "text").dispatch("input");
  q(main, "save").click();
  await settle(80);
  assert(text(q(main, "confirm-box")).includes(warn));
  q(main, "save").click();
  await settle(40);
  assert.strictEqual(skillPosts().length, 2, "not sent again without the tick");
  assert(text(q(main, "problem")).includes("請先勾"));
  q(main, "confirm").checked = true;
  q(main, "save").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => c.body.confirm_warning), [undefined, undefined, true]);
});

test("changed words are asked about again: the tick goes away when the text is edited", async () => {
  const warn = "確定要存嗎？";
  setPage({ postStatus: 409, postBody: { error: warn, code: "confirm_warning", warn: ["personal"], warn_text: [warn] } });
  const main = await open("#/my-skills");
  q(main, "name").value = "n"; q(main, "text").value = "電話 0912-345-678";
  q(main, "save").click();
  await settle(80);
  assert(q(main, "confirm"));
  q(main, "text").value = "電話 0912-345-679";
  q(main, "text").dispatch("input");
  assert.strictEqual(q(main, "confirm"), null);
});

test("a full book says so in the form", async () => {
  setPage({ postStatus: 409, postBody: { error: "技能滿了（最多 100 個），請先刪掉幾個。", code: "skill_full" } });
  const main = await open("#/my-skills");
  q(main, "name").value = "n"; q(main, "text").value = "t";
  q(main, "save").click();
  await settle(80);
  assert(text(q(main, "problem")).includes("技能滿了"));
});

test("changing sends only what changed (and nothing when nothing did); cancel sends nothing", async () => {
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS)]) });
  const main = await open("#/my-skills");
  qa(main, "edit")[0].click();
  await settle();
  let row = qa(main, "item")[0];
  assert.strictEqual(q(row, "name").value, "市集日報");
  assert.strictEqual(q(row, "text").value, STEPS);
  q(row, "save").click();
  await settle(40);
  assert.strictEqual(skillPosts().length, 0, "nothing changed, nothing sent");
  assert.strictEqual(q(qa(main, "item")[0], "text"), null, "the form closes");
  qa(main, "edit")[0].click();
  await settle();
  row = qa(main, "item")[0];
  q(row, "name").value = "市集日報（新）";
  q(row, "save").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => [c.url, c.body]), [["/api/my-skills/k-000000000001", { name: "市集日報（新）" }]]);
  assert(text(h.dom().toastEl).includes("已改"));
  qa(main, "edit")[0].click();
  await settle();
  q(qa(main, "item")[0], "text").value = "改了一半";
  q(qa(main, "item")[0], "cancel").click();
  await settle();
  assert.strictEqual(skillPosts().length, 1);
  assert(text(qa(main, "item")[0]).includes("第一步"));
});

test("delete asks first, then posts an empty body to the delete address once", async () => {
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS)]) });
  const main = await open("#/my-skills");
  qa(main, "delete")[0].click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("刪除這個常用做法"));
  assert.strictEqual(skillPosts().length, 0, "pressing 刪 deletes nothing");
  dlg.find((n) => n.tag === "button" && text(n) === "取消").click();
  await settle();
  assert.strictEqual(skillPosts().length, 0);
  qa(main, "delete")[0].click();
  await settle();
  page.book = book([]);
  dialog().find((n) => n.tag === "button" && text(n) === "刪除").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => [c.url, c.body]), [["/api/my-skills/k-000000000001/delete", {}]]);
  assert.strictEqual(qa(main, "item").length, 0);
});

// ---- 用技能 -----------------------------------------------------------------------------------------------------

const useBtn = (main) => qa(main, "use")[0];
const chatInput = (main) => main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "input");
const groupInput = (main) => main.find((n) => n.getAttribute && n.getAttribute("data-group") === "input");

test("a chat has 用常用做法 beside the send button; picking a skill puts its words in the box and sends nothing", async () => {       // (P47-4) the button's words
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS), skill("k-000000000002", EVIL, "第二個")]) });
  const main = await open("#/chat/" + CID);
  assert(useBtn(main), "the button is there");
  assert.strictEqual(text(useBtn(main)), "用常用做法");
  useBtn(main).click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("這裡不會送出任何東西"));
  assert.deepStrictEqual(qa(dlg, "choice").map((c) => text(c.find((n) => n.tag === "strong"))), ["市集日報", EVIL]);
  assert.strictEqual(dlg.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "a name stays text");
  assert.strictEqual(chatInput(main).value, "");
  qa(dlg, "pick")[0].click();
  await settle();
  assert.strictEqual(chatInput(main).value, STEPS, "the words, as saved, line breaks kept");
  assert.strictEqual(dialog(), null, "the picker closes");
  assert.strictEqual(sendsToAChat().length, 0, "nothing was sent");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0, "no request but reads");
  assert.strictEqual(h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop")), null);
});

test("what is already in the box stays: the skill comes after it, with a blank line", async () => {
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS)]) });
  const main = await open("#/chat/" + CID);
  chatInput(main).value = "請幫我處理今天的：  \n";
  useBtn(main).click();
  await settle();
  qa(dialog(), "pick")[0].click();
  await settle();
  assert.strictEqual(chatInput(main).value, "請幫我處理今天的：\n\n" + STEPS);
});

test("words that would not fit the box are not put in, and the person is told", async () => {
  setPage({ book: book([skill("k-000000000001", "長的", "字".repeat(3000))]) });
  const main = await open("#/chat/group/" + GID);
  groupInput(main).value = "字".repeat(1500);
  useBtn(main).click();
  await settle();
  qa(dialog(), "pick")[0].click();
  await settle();
  assert.strictEqual(groupInput(main).value, "字".repeat(1500), "unchanged");
  assert(dialog(), "the picker stays so another can be chosen");
  assert(text(h.dom().toastEl).includes("放不下"));
});

test("a group has 用技能 too, and it puts the words in the group's box without sending", async () => {
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS)]) });
  const main = await open("#/chat/group/" + GID);
  assert(useBtn(main));
  useBtn(main).click();
  await settle();
  qa(dialog(), "pick")[0].click();
  await settle();
  assert.strictEqual(groupInput(main).value, STEPS);
  assert.strictEqual(sendsToAChat().length, 0);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method !== "GET").length, 0);
});

test("with no skills the picker says so and points to the skills page; a book that cannot be read is said", async () => {
  setPage();
  let main = await open("#/chat/" + CID);
  useBtn(main).click();
  await settle();
  assert(text(dialog()).includes("還沒有存任何常用做法"));
  assert.strictEqual(dialog().find((n) => n.tag === "a").getAttribute("href"), "#/my-skills");
  assert.strictEqual(qa(dialog(), "pick").length, 0);
  dialog().find((n) => n.tag === "button" && text(n) === "取消").click();
  await settle();
  setPage({ book: book([], { readable: false, problem: "技能的檔案有問題，VBear 先不碰它。" }) });
  main = await open("#/chat/" + CID);
  useBtn(main).click();
  await settle();
  assert(text(dialog()).includes("技能的檔案有問題"));
  dialog().find((n) => n.tag === "button" && text(n) === "取消").click();
  await settle();
  setPage({ bookStatus: 503 });
  main = await open("#/chat/" + CID);
  useBtn(main).click();
  await settle();
  assert(text(dialog()).includes("讀不到常用做法"));
});

test("a chat a group opened has no box and so no 用技能", async () => {
  setPage({ detail: chatDetail([], { group: { id: GID, name: "市集準備" } }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(useBtn(main), undefined);
});

// ---- 存成技能 ---------------------------------------------------------------------------------------------------

test("a chat has 存成常用做法 beside 記住 on each spoken line, and opening the chat saves nothing", async () => {       // (P47-4) the button's words
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "第一步先整理" }), rec("reply", { turn: 1, text: "好", truncated: false }),
    rec("tool_call", { turn: 1, tool: "Bash", summary: "ls" })]) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(saveButtons(main).length, 2);
  assert(saveButtons(main).every((b) => text(b) === "存成常用做法"));
  assert.strictEqual(skillPosts().length, 0);
});

test("a message VBear sent for a dispatch has no 存成技能", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "第一步的資料", origin: { dispatch: "d-0123456789ab", step: 1 } })]) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(saveButtons(main).length, 0);
});

test("the person's words: the box brings them in, wants a name, and posts only on 存, with where they came from", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 7, text: STEPS })]) });
  const main = await open("#/chat/" + CID);
  saveButtons(main)[0].click();
  await settle();
  const dlg = dialog();
  assert(dlg && text(dlg).includes("存成常用做法"));
  assert.strictEqual(skillPosts().length, 0, "pressing the button saves nothing");
  assert.strictEqual(q(dlg, "text").value, STEPS);
  assert.strictEqual(q(dlg, "name").value, "");
  assert(!text(dlg).includes("這段是員工寫的"), "no employee reminder for the person's own words");
  assert.strictEqual(q(dlg, "confirm"), null);
  q(dlg, "name").value = "市集日報";
  q(dlg, "save").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => c.body), [{ name: "市集日報", text: STEPS, source: { how: "said", chat_id: CID } }]);
  assert.strictEqual(dialog(), null, "the box closes once saved");
  assert(text(h.dom().toastEl).includes("已存成常用做法"));
});

test("an employee's words: the reminder is there from the start and nothing is sent before 我確定 is ticked", async () => {
  setPage({ detail: chatDetail([rec("reply", { turn: 4, text: "照這樣做：先查庫存", truncated: false })]) });
  const main = await open("#/chat/" + CID);
  saveButtons(main)[0].click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("這段是員工寫的，存成常用做法後，你用它時會變成你對員工說的話。"));
  assert(q(dlg, "confirm"), "the box is there at once");
  q(dlg, "name").value = "查庫存";
  q(dlg, "save").click();
  await settle(40);
  assert.strictEqual(skillPosts().length, 0, "not sent without the tick");
  assert(text(q(dlg, "problem")).includes("請先勾"));
  q(dlg, "confirm").checked = true;
  q(dlg, "save").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => c.body), [{ name: "查庫存", text: "照這樣做：先查庫存", confirm_warning: true,
    source: { how: "reply", chat_id: CID } }]);
});

test("a refusal in the box stays in the box with the words; the tick of an employee's words is not lost", async () => {
  setPage({ detail: chatDetail([rec("reply", { turn: 4, text: "後台密碼是 hunter-two", truncated: false })]),
    postStatus: 400, postBody: { error: "技能裡不能有密碼或驗證碼，請換個說法。", code: "skill_refused", refuse: "secret_password", field: "text" } });
  const main = await open("#/chat/" + CID);
  saveButtons(main)[0].click();
  await settle();
  const dlg = dialog();
  q(dlg, "name").value = "n";
  q(dlg, "confirm").checked = true;
  q(dlg, "save").click();
  await settle(80);
  assert(dialog());
  assert(text(q(dlg, "problem")).includes("技能裡不能有密碼"));
  assert.strictEqual(q(dlg, "text").value, "後台密碼是 hunter-two");
  assert(q(dlg, "confirm"), "the box is still there");
});

test("words longer than 4,000 characters are cut and the box says so", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "字".repeat(4300) })]) });
  const main = await open("#/chat/" + CID);
  saveButtons(main)[0].click();
  await settle();
  const dlg = dialog();
  assert.strictEqual(Array.from(q(dlg, "text").value).length, 4000);
  assert(text(q(dlg, "cut-note")).includes("太長") && text(q(dlg, "cut-note")).includes("4000"));
});

test("a group has 存成技能 on the person's words and on each reply, with the group in the source", async () => {
  setPage({ group: groupDetail([said("我們週末擺攤"), groupReply("好，我先做")]) });
  const main = await open("#/chat/group/" + GID);
  const buttons = saveButtons(main);
  assert.strictEqual(buttons.length, 2);
  buttons[0].click();
  await settle();
  q(dialog(), "name").value = "擺攤";
  q(dialog(), "save").click();
  await settle(80);
  buttons[1].click();
  await settle();
  assert(text(dialog()).includes("這段是員工寫的"));
  q(dialog(), "name").value = "先做";
  q(dialog(), "confirm").checked = true;
  q(dialog(), "save").click();
  await settle(80);
  assert.deepStrictEqual(skillPosts().map((c) => c.body.source), [{ how: "said", group_id: GID }, { how: "reply", group_id: GID }]);
});

test("a reply that could not be read, and one with no words, have no 存成技能", async () => {
  setPage({ group: groupDetail([groupReply("", { unreadable: true }), groupReply("")]) });
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(saveButtons(main).length, 0);
});

// ---- 整理成技能 (P44-5) -----------------------------------------------------------------------------------------

const SID = "ks-0123456789ab";
const kq = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-ksuggest") === key);
const kqa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-ksuggest") === key);
const kdialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("data-ksuggest") === "dialog");
const sdialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("data-skill") === "dialog");
const kpreview = (over = {}) => ({ preview_id: "pv-" + "0".repeat(16), ok: true, blockers: [], chat_id: CID, messages: 6, omitted_messages: 0, bytes: 900,
  cap_usd: "0.1", day_left_usd: "2.71", today: { spent_usd: "0.29", daily_usd: "3", lamp: "green" }, sends_to: "Anthropic", engine: "claude-chat",
  notice: null, save_note: "整理只是提議：不會自己存。它會放進「存成常用做法」的視窗，你看過、可以改，按「存」才會存。", cli: { version: "2.1.318", verified: true },
  disclosure: "開始後，你和這位員工最近的對話（最多 20 則、12 KiB）會用你的 Claude 帳號送到 Anthropic（由本機的 Claude Code 送出）。",
  cost_note: "金額是 Claude Code 回報的估值。", ...over });
const kitem = (over = {}) => ({ index: 0, name: "市集日報", text: STEPS, note: "根據你前面說的步驟", refuse: null, refuse_text: null, warn: [], warn_text: [], saved: false, ...over });
const kview = (over = {}) => ({ id: SID, created_at: 1790000100, chat_id: CID, engine: "claude-chat", status: "ready", state: "done", error_code: null, attempts: 1,
  spent_usd: "0.02", cost_source: "cli", limits: { per_call_usd: "0.1", total_usd: "0.1" }, read: { count: 6 }, sends_to: "Anthropic", items: [kitem()],
  saved: false, dismissed: false, outcome: "ready", ...over });
let K;
function suggestPage(over = {}) {
  K = { preview: kpreview(), view: kview(), list: [], saved: 0, ...over };
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "每天早上整理銷售" })]),
    postStatus: 201, postBody: (b) => ({ ok: true, skill: skill("k-0123456789ab", b.name, b.text, { source: b.source }) }),
    suggest: (p, method, body) => {
      if (p === "/api/my-skills/suggest/preview" && method === "POST") return jsonResponse(K.preview);
      if (p === "/api/my-skills/suggest" && method === "GET") return jsonResponse({ suggestions: K.list });
      if (p === "/api/my-skills/suggest" && method === "POST") return jsonResponse({ id: SID, suggestion: kview({ status: "running", state: "running", items: [], outcome: "pending" }) }, true, 202);
      const m = /^\/api\/my-skills\/suggest\/(ks-[0-9a-f]{12})(?:\/(saved|dismiss|cancel))?$/.exec(p);
      if (m && !m[2] && method === "GET") return jsonResponse(K.view);
      if (m && m[2] === "saved") { K.saved += 1; return jsonResponse(kview({ saved: true, items: [kitem({ saved: true })] })); }
      if (m && m[2] === "dismiss") return jsonResponse(kview({ dismissed: true }));
      if (m && m[2] === "cancel") return jsonResponse(kview({ status: "cancelled", state: "cancelled", items: [] }));
      return null;
    } });
}
async function kopen() {
  const real = global.setInterval;
  const ticks = [];
  global.setInterval = (fn) => { ticks.push(fn); return ticks.length; };
  global.location.hash = "#/chat/" + CID;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  page.ticks = ticks;
  return h.dom().mainEl;
}
const ktick = async () => { for (const fn of page.ticks) await fn(); await settle(); };
async function kstarted() {
  const main = await kopen();
  kq(main, "open").click();
  await settle(80);
  kq(kdialog(), "start").click();
  await settle(80);
  return main;
}
async function kready(over = {}) {
  suggestPage(over);
  const main = await kstarted();
  await ktick();
  return main;
}
const skillWrites = () => FETCH_LOG.filter((c) => c.method === "POST" && /^\/api\/my-skills(\/k-[0-9a-f]{12}(\/delete)?)?$/.test(c.url.split("?")[0]));
const ksuggestCalls = () => FETCH_LOG.filter((c) => c.url.startsWith("/api/my-skills/suggest")).map((c) => `${c.method} ${c.url.split("?")[0]}`);

test("a one-to-one chat has 整理成常用做法 (an item of the 「⋯」 menu); opening it asks nothing, a group's chat has none", async () => {
  suggestPage();
  const main = await kopen();
  const btn = kq(main, "open");
  assert(text(btn).startsWith("整理成常用做法"), text(btn));
  assert(text(btn).includes("Anthropic"));         // (P47-4) the sentence that stood on the desk stands under the item
  assert(text(btn).includes("US$0.10"));
  assert.deepStrictEqual(ksuggestCalls().filter((c) => c.startsWith("POST")), []);
  setPage({ detail: chatDetail([], { group: { id: GID, name: "市集準備" } }) });
  assert(!kq(await kopen(), "open"));
});

test("the preview says what is read, the most it costs, what is left and that it goes to Anthropic; nothing is started by opening it", async () => {
  suggestPage();
  const main = await kopen();
  kq(main, "open").click();
  await settle(80);
  const d = kdialog();
  const t = text(d);
  for (const word of ["6 則", "US$0.10", "US$2.71", "Anthropic", "不會自己存", "最多 20 則"]) assert(t.includes(word), word);
  assert(t.includes("你的記憶和其他常用做法，都不會送出"), "neither the memory nor the other skills are sent");
  assert.deepStrictEqual(ksuggestCalls(), ["GET /api/my-skills/suggest", "POST /api/my-skills/suggest/preview"]);
  const pv = FETCH_LOG.find((c) => c.url === "/api/my-skills/suggest/preview");
  assert.deepStrictEqual(pv.body, { chat_id: CID });
  assert(kq(d, "start"));
});

test("a Codex chat's notice is shown, and without Claude Code the dialog says it is needed and has no start button", async () => {
  suggestPage({ preview: kpreview({ engine: "codex-chat", notice: "這是和 Codex 員工的對話，也會送給 Anthropic（Claude Code）整理。" }) });
  let main = await kopen();
  kq(main, "open").click();
  await settle(80);
  assert(text(kdialog()).includes("Codex 員工"));
  suggestPage({ preview: kpreview({ ok: false, preview_id: null, blockers: [{ code: "cli_not_found", message: "這個功能目前需要 Claude Code" }] }) });
  main = await kopen();
  kq(main, "open").click();
  await settle(80);
  const d = h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("data-ksuggest") === "dialog").pop();
  assert(text(d).includes("這個功能目前需要 Claude Code"));
  assert(text(d).includes("存成常用做法"), "the per-line 存成常用做法 still works");
  assert(!kq(d, "start"));
});

test("starting posts the preview id; the result is a card with the name, the words and the note as text, and nothing is saved yet", async () => {
  const main = await kready({ view: kview({ items: [kitem({ name: EVIL, text: EVIL + "\n第二步", note: EVIL })] }) });
  assert.deepStrictEqual(FETCH_LOG.find((c) => c.method === "POST" && c.url === "/api/my-skills/suggest").body, { preview_id: "pv-" + "0".repeat(16) });
  const card = kq(main, "card");
  assert(card);
  assert.strictEqual(text(kq(card, "name")), EVIL);
  assert.strictEqual(text(kq(card, "text")), EVIL + "\n第二步");
  assert(text(kq(card, "note")).includes(EVIL));
  assert(text(card).includes("預設沒存"));
  assert.strictEqual(card.findAll((n) => n.tag === "img").length, 0, "markup stays text");
  assert.deepStrictEqual(skillWrites(), [], "no skill is saved by the suggestion");
});

test("放進存成技能 opens the box with the name and the words filled in; it posts only on 存, with how suggested and the id, then marks it saved", async () => {
  const main = await kready();
  kq(main, "use").click();
  await settle(40);
  const box = sdialog();
  assert(box);
  assert.strictEqual(q(box, "name").value, "市集日報");
  assert.strictEqual(q(box, "text").value, STEPS);
  assert.deepStrictEqual(skillWrites(), [], "opening the box saves nothing");
  q(box, "name").value = "市集日報（我改的）";
  q(box, "save").click();
  await settle(120);
  assert.deepStrictEqual(skillWrites().map((c) => [c.url, c.body]),
    [["/api/my-skills", { name: "市集日報（我改的）", text: STEPS, source: { how: "suggested", suggestion_id: SID } }]]);
  assert.strictEqual(K.saved, 1, "the suggestion is marked saved");
  assert(!sdialog(), "the box closes");
  assert.strictEqual(kq(main, "card"), null, "a saved suggestion's card goes away");
});

test("a refused proposal says why; the box still opens so the words can be changed, and the server's refusal stays in the box", async () => {
  const main = await kready({ view: kview({ items: [kitem({ refuse: "secret_key", refuse_text: "這看起來像金鑰或登入用的代碼，技能裡不能有。" })] }) });
  assert(text(kq(main, "card")).includes("這看起來像金鑰或登入用的代碼，技能裡不能有。"));
  kq(main, "use").click();
  await settle(40);
  assert(sdialog());
});

test("a proposal that reads like an order carries the server's warning on the card", async () => {
  const main = await kready({ view: kview({ items: [kitem({ warn: ["looks_like_order"], warn_text: ["這段看起來像在叫員工不問你就做事。"] })] }) });
  assert(text(kq(main, "card")).includes("這段看起來像在叫員工不問你就做事。"));
});

test("nothing worth keeping says so and can be closed; 不用了 posts an empty dismiss and the card goes away", async () => {
  const main = await kready({ view: kview({ items: [] }) });
  assert(text(kq(main, "card")).includes("沒有值得存成常用做法"));
  kq(main, "dismiss").click();
  await settle(40);
  assert(ksuggestCalls().includes(`POST /api/my-skills/suggest/${SID}/dismiss`));
  assert.deepStrictEqual(FETCH_LOG.find((c) => c.url.endsWith("/dismiss")).body, {});
  assert.strictEqual(kq(main, "card"), null);
});

test("a failed run says so with its code and nothing to save; a running one has 取消", async () => {
  suggestPage({ view: kview({ status: "failed", state: "failed", error_code: "invalid_output", items: [], outcome: "pending" }) });
  const main = await kstarted();
  assert(kq(main, "run"), "running at first");
  assert(kq(main, "cancel"));
  await ktick();
  assert(text(kq(main, "run")).includes("這次整理沒有成功"));
  assert(text(kq(main, "run")).includes("invalid_output"));
  assert.strictEqual(kq(main, "card"), null);
});

test("the code of the suggestions keeps its rules: no markup written, no emoji, no outside address, no native dialog, nothing kept, no send, nothing saved by itself", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const part = source.slice(source.indexOf("// ---------- skill suggestions (v0.18, P44-5"), source.indexOf("// ---------- end of skill suggestions"));
  assert(part.length > 3000, "the block is there");
  assert(!/\p{Extended_Pictographic}/u.test(part), "no emoji");
  assert(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(part));
  assert(!/https?:\/\//.test(part));
  assert(!/\b(confirm|alert|prompt)\s*\(/.test(part.replace(/confirmInPage/g, "")));
  assert(!/localStorage|sessionStorage|document\.cookie/.test(part));
  assert(!/console\.(log|info|warn|error)/.test(part));
  assert(!/\/api\/(chats|groups|config|settings|native|agent-profiles|memory)|\/messages|\/answer|api\.(patch|del)\(/.test(part));
  // the only route of the skills the block names is the suggestions' own; saving goes through openSkillSave (the person's press of 存)
  assert(!/["'`]\/api\/my-skills["'`]/.test(part), "the block never posts to the skills route itself");
  assert(/openSkillSave\(/.test(part));
  assert(!/\.click\(\)|\.submit\(\)/.test(part));
});

// ---- the rules of the code --------------------------------------------------------------------------------------

test("the code keeps its rules: no markup written, no emoji, no outside address, no native dialog, nothing kept in the browser, no send", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const part = source.slice(source.indexOf("// ---------- my skills (P44-1"), source.indexOf("// ---------- end of my skills"));
  assert(part.length > 3000, "the block is there");
  assert(!/\p{Extended_Pictographic}/u.test(part), "no emoji");
  assert(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(part));
  assert(!/https?:\/\//.test(part));
  assert(!/\b(confirm|alert|prompt)\s*\(/.test(part.replace(/confirmInPage/g, "")));
  assert(!/localStorage|sessionStorage|document\.cookie/.test(part));
  assert(!/console\.(log|info|warn|error)/.test(part));
  // 用技能 puts words in a box and nothing more: the block never reaches a chat, a group, a setting, or an answer to a card
  assert(!/\/api\/(chats|groups|config|settings|native|agent-profiles|memory)|\/messages|\/answer|api\.(patch|del)\(/.test(part));
  assert(!/\.click\(\)|\.submit\(\)/.test(part), "no pressing of the send button for the person");
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  const nav = html.split("\n").find((line) => line.includes('data-nav="work"'));
  assert(nav && !/\p{Extended_Pictographic}/u.test(nav), "no emoji in the navigation line");
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
