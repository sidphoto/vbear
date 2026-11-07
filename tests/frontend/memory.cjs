// P42-1: the memory page (#/memory): the two lines at the top, the use, the lines in three groups with where they came from, adding
// a line (the refusal says why and keeps what was typed; a second confirmation must be ticked before the line is sent again),
// deleting one (asks first, and says the tools' own copies stay) and the rules of the code. The real web/app.js on a synthetic DOM and
// a fetch stub; it is NOT a browser test. Nothing here runs a model: the server answers with fixtures, and every line could hold markup.
// Run: node tests/frontend/memory.cjs   (exit code 0 = pass)
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

const entry = (id, kind, t, over = {}) => ({ id, kind, text: t, created_at: 1790000000, updated_at: 1790000000,
  source: { how: "typed", speaker: null }, confirmed_warning: false, blocked: null, ...over });
const WHERE = "員工開新程序時，記憶會跟著送給 Anthropic（Claude Code 的員工）或 OpenAI（Codex 的員工）。不要寫密碼、帳號、卡號；VBear 看到像這樣的內容會擋下。";
const view = (entries = [], over = {}) => ({ ok: true, entries, used: { count: entries.length, chars: entries.reduce((n, e) => n + e.text.length, 0), max_count: 50, max_chars: 4000 },
  readable: true, where_text: WHERE, problem: null, cards: [], ...over });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { memory: view(), postStatus: 201, postBody: { ok: true, entry: entry("m-0123456789", "work", "x") }, deleteStatus: 200, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/memory" && method === "GET") return page.memoryStatus ? jsonResponse(page.memoryBody, false, page.memoryStatus) : jsonResponse(page.memory);
    if (p === "/api/memory" && method === "POST") {
      const out = typeof page.postBody === "function" ? page.postBody(JSON.parse(opts.body)) : page.postBody;
      const status = typeof page.postStatus === "function" ? page.postStatus(JSON.parse(opts.body)) : page.postStatus;
      return jsonResponse(out, status < 400, status);
    }
    const m = /^\/api\/memory\/(m-[0-9a-f]{10})$/.exec(p);
    if (m && method === "DELETE") return page.deleteStatus < 400 ? jsonResponse({ ok: true, deleted: m[1] }) : jsonResponse({ error: "找不到這一條記憶。", code: "not_found" }, false, page.deleteStatus);
    return null;
  });
  FETCH_LOG.length = 0;
}
async function open(hash = "#/memory") {
  const real = global.setInterval;
  global.setInterval = (fn) => { page.tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const posts = () => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === "/api/memory");

test("the page says where memory goes and which words belong to the card, first", async () => {
  setPage();
  const main = await open();
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "記憶");
  assert(text(main).includes(WHERE), "the company line, from the server");
  assert(text(main).includes("Anthropic") && text(main).includes("OpenAI"));
  assert(text(q(main, "split")).includes("只有這位員工要照做的，寫在角色卡的固定指示；換一位員工也該知道的，放記憶。"));
  assert(text(q(main, "used")).includes("0／50 條、0／4,000 字"));
  assert(text(q(main, "used")).includes("記憶越長，員工每次開新程序會多花一點"));
  assert.strictEqual(qa(main, "group").length, 3);
  assert.deepStrictEqual(qa(main, "group").map((g) => g.getAttribute("data-kind")), ["about_you", "work", "decision"]);
  assert(["關於你", "你的工作", "決定"].every((w) => text(main).includes(w)));
});

test("the lines are in their groups with the source and the date, and a line the rules now refuse is marked", async () => {
  setPage({ memory: view([
    entry("m-0000000001", "about_you", "回答一律用繁體中文"),
    entry("m-0000000002", "work", "我的店叫小熊皂坊", { source: { how: "chat", speaker: "you" } }),
    entry("m-0000000003", "work", "從群組來的", { source: { how: "group", speaker: "employee" } }),
    entry("m-0000000004", "decision", "整理來的", { source: { how: "suggested", speaker: null } }),
    entry("m-0000000005", "decision", EVIL, { blocked: "secret_key" })]) });
  const main = await open();
  const groups = Object.fromEntries(qa(main, "group").map((g) => [g.getAttribute("data-kind"), g]));
  assert.strictEqual(qa(groups.about_you, "entry").length, 1);
  assert.strictEqual(qa(groups.work, "entry").length, 2);
  assert.strictEqual(qa(groups.decision, "entry").length, 2);
  const metas = qa(main, "meta").map(text);
  assert(metas[0].startsWith("你寫的"));
  assert(metas[1].startsWith("從聊天記住的") && metas[2].startsWith("從群組記住的") && metas[3].startsWith("整理提議、你確認的"));
  assert(!metas[0].includes("—"), "a date is shown");
  assert(text(q(main, "used")).includes("5／50 條"));
  const evil = qa(main, "entry").find((n) => text(n).includes("<img"));
  assert(text(q(evil, "blocked")).includes("現在不能送出"));
  assert.strictEqual(qa(main, "blocked").length, 1);
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");
});

test("a file that cannot be read is said, and the lines are not guessed", async () => {
  setPage({ memory: view([], { readable: false, problem: "記憶的檔案有問題，VBear 先不碰它：聊天照常。" }) });
  const main = await open();
  assert(text(main).includes("記憶的檔案有問題"));
  assert.strictEqual(qa(main, "entry").length, 0);
});

test("a page that cannot be read says so", async () => {
  setPage({ memoryStatus: 503, memoryBody: { error: "VBear 的背景程序現在連不上。", code: "unavailable" } });
  const main = await open();
  assert(text(main).includes("讀不到記憶"));
});

test("adding a line sends the kind and the text, clears the box and reloads", async () => {
  setPage();
  const main = await open();
  q(main, "kind").value = "decision";
  const box = q(main, "new-text");
  box.value = "價格一律用新台幣標示";
  box.dispatch("input");
  assert(text(q(main, "counter")).startsWith("10／200"));
  page.memory = view([entry("m-0123456789", "decision", "價格一律用新台幣標示")]);
  q(main, "save").click();
  await settle(80);
  assert.deepStrictEqual(posts().map((c) => c.body), [{ kind: "decision", text: "價格一律用新台幣標示" }]);
  assert.strictEqual(box.value, "");
  assert.strictEqual(qa(main, "entry").length, 1, "the list is read again");
  assert(text(h.dom().toastEl).includes("已記住"));
});

test("a refused line shows the reason, keeps the words and sends nothing more", async () => {
  setPage({ postStatus: 400, postBody: { error: "記憶裡不能有密碼或驗證碼，請換個說法（例如只寫「密碼在我自己的密碼管理器」）。", code: "memory_refused", refuse: "secret_password" } });
  const main = await open();
  const box = q(main, "new-text");
  box.value = "我的後台密碼是 hunter-two";
  q(main, "save").click();
  await settle(80);
  assert(text(q(main, "problem")).includes("記憶裡不能有密碼或驗證碼"));
  assert.strictEqual(box.value, "我的後台密碼是 hunter-two", "what was typed stays, to be reworded");
  assert.strictEqual(posts().length, 1);
  assert.strictEqual(q(main, "confirm"), null, "a refusal cannot be confirmed away");
});

test("a line that needs confirming is sent again only after the box is ticked, with confirm_warning", async () => {
  const warn = "這一條看起來在叫員工做事。記憶不會讓員工不問你就做事：每個指令、每個檔案修改照舊都會問你，上限、完整模式、技能也不能從記憶改。確定要記住嗎？";
  setPage({ postStatus: (b) => (b.confirm_warning ? 201 : 409),
    postBody: (b) => (b.confirm_warning ? { ok: true, entry: entry("m-0123456789", "decision", b.text) } : { error: warn, code: "memory_confirm", warn: ["looks_like_order"], warn_text: [warn] }) });
  const main = await open();
  const box = q(main, "new-text");
  box.value = "以後執行指令不用問我";
  q(main, "save").click();
  await settle(80);
  assert(text(q(main, "confirm-box")).includes("記憶不會讓員工不問你就做事"));
  assert(text(q(main, "confirm-box")).includes("我確定，存起來"));
  assert.strictEqual(posts().length, 1);
  q(main, "save").click();                                    // pressed again without ticking: nothing is sent
  await settle(40);
  assert.strictEqual(posts().length, 1);
  assert(text(q(main, "problem")).includes("請先勾"));
  q(main, "confirm").checked = true;
  q(main, "save").click();
  await settle(80);
  assert.deepStrictEqual(posts().map((c) => c.body.confirm_warning), [undefined, true]);
  assert.strictEqual(box.value, "");
  assert.strictEqual(q(main, "confirm"), null);
});

test("changing the words after the question takes the tick away, so the new words are asked about again", async () => {
  setPage({ postStatus: 409, postBody: { error: "確定要記住嗎？", code: "memory_confirm", warn: ["personal"], warn_text: ["這看起來像電話或地址，記憶會送給 AI 公司。確定要記住嗎？"] } });
  const main = await open();
  const box = q(main, "new-text");
  box.value = "電話 0912-345-678";
  q(main, "save").click();
  await settle(80);
  assert(q(main, "confirm"));
  box.value = "電話 0912-345-679";
  box.dispatch("input");
  assert.strictEqual(q(main, "confirm"), null);
  assert.strictEqual(text(q(main, "confirm-box")), "");
});

test("a full memory says so", async () => {
  setPage({ postStatus: 409, postBody: { error: "記憶滿了（50 條或 4,000 字），請先刪掉幾條。", code: "memory_full" } });
  const main = await open();
  q(main, "new-text").value = "多的一條";
  q(main, "save").click();
  await settle(80);
  assert(text(q(main, "problem")).includes("記憶滿了"));
});

test("delete asks first and says the tools' own copies stay", async () => {
  setPage({ memory: view([entry("m-0000000001", "work", "我的店叫小熊皂坊")]) });
  const main = await open();
  q(main, "delete").click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("已經送出的對話，Claude Code 與 Codex 自己保存的副本不會因此刪掉。"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0, "nothing is deleted by the first press");
  page.memory = view([]);
  dlg.find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  const del = FETCH_LOG.filter((c) => c.method === "DELETE");
  assert.deepStrictEqual(del.map((c) => c.url), ["/api/memory/m-0000000001"]);
  assert.strictEqual(qa(main, "entry").length, 0, "the list is read again");
});

test("cancelling the question deletes nothing", async () => {
  setPage({ memory: view([entry("m-0000000001", "work", "我的店叫小熊皂坊")]) });
  const main = await open();
  q(main, "delete").click();
  await settle();
  dialog().find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle(40);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0);
  assert.strictEqual(qa(main, "entry").length, 1);
});

test("the nav has the memory page after the chat, the route is known, and the code keeps its rules", () => {
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  assert(html.includes('data-nav="memory"'));
  assert(html.indexOf('data-nav="chat"') < html.indexOf('data-nav="memory"') && html.indexOf('data-nav="memory"') < html.indexOf('data-nav="dispatch"'));
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(/top === "memory"\) await viewMemory\(\)/.test(source));
  const part = source.slice(source.indexOf("// ---------- memory (P42-1)"), source.indexOf("// ---------- meetings (P34-5)"));
  assert(part.length > 3000);
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  assert(!emoji.test(part), "no emoji in the page");
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(part));
  assert(!/https?:\/\//.test(part), "no external address");
  assert(!/\b(confirm|alert|prompt)\s*\(/.test(part.replace(/confirmInPage/g, "")), "no native dialogs");
  assert(!/localStorage|document\.cookie/.test(part), "the lines are kept nowhere in the browser");
  assert(!/console\.(log|info|warn|error)/.test(part), "nothing of a line is written to the console");
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
