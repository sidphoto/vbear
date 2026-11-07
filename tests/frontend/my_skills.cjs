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
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "技能");
  assert(text(main).includes("這裡是你存在 VBear 的做法。用的時候會變成你對員工說的話；員工照舊每個指令、每個檔案修改都會問你。"));
  assert(text(q(main, "not-cards")).includes("『技能庫』列的是 AI 工具自己的技能檔，是另一回事。"));
  assert.strictEqual(q(main, "not-cards").find((n) => n.tag === "a").getAttribute("href"), "#/skills");
  assert(text(q(main, "none")).includes("還沒有存任何技能"));
  assert(text(q(main, "used")).includes("0／100"));
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  assert(/<a href="#\/my-skills" data-nav="my-skills">[^<]*<span aria-hidden="true">[^<]*<\/span>技能<\/a>/.test(html));
  assert(html.indexOf('data-nav="shared"') < html.indexOf('data-nav="my-skills"'), "below the shared folder");
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
  setPage({ bookStatus: 503, bookBody: { error: "VBear 的背景程序現在連不上。", code: "unavailable" } });
  main = await open("#/my-skills");
  assert(text(main).includes("讀不到技能"));
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
  assert(text(h.dom().toastEl).includes("已存成技能"));
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
  assert(text(dlg).includes("刪除這個技能"));
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

test("a chat has 用技能 beside the send button; picking a skill puts its words in the box and sends nothing", async () => {
  setPage({ book: book([skill("k-000000000001", "市集日報", STEPS), skill("k-000000000002", EVIL, "第二個")]) });
  const main = await open("#/chat/" + CID);
  assert(useBtn(main), "the button is there");
  assert.strictEqual(text(useBtn(main)), "用技能");
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
  assert(text(dialog()).includes("還沒有存任何技能"));
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
  assert(text(dialog()).includes("讀不到技能"));
});

test("a chat a group opened has no box and so no 用技能", async () => {
  setPage({ detail: chatDetail([], { group: { id: GID, name: "市集準備" } }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(useBtn(main), undefined);
});

// ---- 存成技能 ---------------------------------------------------------------------------------------------------

test("a chat has 存成技能 beside 記住 on each spoken line, and opening the chat saves nothing", async () => {
  setPage({ detail: chatDetail([rec("user_message", { turn: 1, text: "第一步先整理" }), rec("reply", { turn: 1, text: "好", truncated: false }),
    rec("tool_call", { turn: 1, tool: "Bash", summary: "ls" })]) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(saveButtons(main).length, 2);
  assert(saveButtons(main).every((b) => text(b) === "存成技能"));
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
  assert(dlg && text(dlg).includes("存成技能"));
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
  assert(text(h.dom().toastEl).includes("已存成技能"));
});

test("an employee's words: the reminder is there from the start and nothing is sent before 我確定 is ticked", async () => {
  setPage({ detail: chatDetail([rec("reply", { turn: 4, text: "照這樣做：先查庫存", truncated: false })]) });
  const main = await open("#/chat/" + CID);
  saveButtons(main)[0].click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("這段是員工寫的，存成技能後，你用它時會變成你對員工說的話。"));
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
  const nav = html.split("\n").find((line) => line.includes('data-nav="my-skills"'));
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
