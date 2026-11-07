// P43-1: the shared folder page (#/shared): where the folder is, what is in it (names, sizes, times), the button that opens it in Finder,
// one switch per employee (Claude Code only so far; turning one on asks first and says what goes to which company), the refusals in words, and
// the rules of the code. The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. The page sends a card id and
// on/off or nothing at all: never a path. Every name here is made up, and a file name could hold markup.
// Run: node tests/frontend/shared.cjs   (exit code 0 = pass)
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
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-shared") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-shared") === key);
const EVIL = "<img src=x onerror=alert(1)>.md";
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));

const CARDS = () => [
  { profile_id: "emp-1", name: "小編", tool: "claude", company: "Anthropic", can_chat: true, on: false, verified: null },
  { profile_id: "emp-2", name: "資料員", tool: "claude", company: "Anthropic", can_chat: true, on: true, verified: null },
  { profile_id: "emp-4", name: "會計師", tool: "codex", company: "OpenAI", can_chat: true, on: false, verified: null },
  { profile_id: "emp-5", name: "舊員工", tool: "gemini", company: null, can_chat: false, on: false, verified: null },
];
const file = (name, size, over = {}) => ({ name, size, mtime: 1790000000, link: false, ...over });
const view = (over = {}) => ({ ok: true, where_text: "~/.vbear/shared", exists: true, problem: null, readable: true,
  used: { bytes: 0, entries: 0, max_bytes: 1073741824, max_entries: 10000, over: false }, links: 0, files: [], cards: CARDS(), ...over });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { shared: view(), getStatus: 0, getBody: null, cardsStatus: 200, cardsBody: { ok: true, profile_id: "emp-1", on: true }, revealStatus: 200, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/shared" && method === "GET") return page.getStatus ? jsonResponse(page.getBody, false, page.getStatus) : jsonResponse(page.shared);
    if (p === "/api/shared/cards" && method === "POST") return page.cardsStatus < 400 ? jsonResponse(page.cardsBody) : jsonResponse(page.cardsBody, false, page.cardsStatus);
    if (p === "/api/shared/reveal" && method === "POST") return page.revealStatus < 400 ? jsonResponse({ ok: true, revealed: true }) : jsonResponse({ error: "沒能用 Finder 打開共用資料夾。", code: "reveal_failed" }, false, page.revealStatus);
    return null;
  });
  FETCH_LOG.length = 0;
}
async function open(hash = "#/shared") {
  const real = global.setInterval;
  global.setInterval = (fn) => { page.tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const posts = (u) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === u);

test("the page says what the folder is, that every write asks, that VBear reads nothing, and where the files go", async () => {
  setPage();
  const main = await open();
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "共用資料夾");
  assert(text(main).includes("一位員工寫進去，另一位讀得到"));
  assert(text(main).includes("每位員工預設都是關的"));
  assert(text(q(main, "notes")).includes("每一次都會先問你"));
  assert(text(q(main, "notes")).includes("VBear 自己不會讀、不會刪"));
  assert(text(q(main, "read-note")).includes("內容就會送給它的 AI 公司") && text(q(main, "read-note")).includes("Anthropic"));
  assert(text(q(main, "limit-note")).includes("1 GiB") && text(q(main, "limit-note")).includes("1 萬"));
  assert(text(q(main, "change-note")).includes("下一則訊息"));
  assert.strictEqual(text(q(main, "where")), "~/.vbear/shared");
});

test("each employee has a switch only when its tool has the folder; Codex and a tool that cannot chat say why", async () => {
  setPage();
  const main = await open();
  const cards = qa(main, "card");
  assert.strictEqual(cards.length, 4);
  assert.strictEqual(q(cards[0], "card-switch").checked, false);
  assert.strictEqual(q(cards[1], "card-switch").checked, true);
  assert(text(q(cards[1], "company")).includes("讀到的檔案會送給 Anthropic"));
  assert(text(q(cards[0], "company")).includes("打開後"));
  assert.strictEqual(q(cards[2], "card-switch"), null, "Codex has none until it is verified");
  assert(text(q(cards[2], "unsupported")).includes("還不能用共用資料夾"));
  assert.strictEqual(q(cards[3], "card-switch"), null);
  assert(text(q(cards[3], "unsupported")).includes("還不能聊天"));
});

test("the files are listed by name, size and time; markup in a name stays text; links are said", async () => {
  setPage({ shared: view({ used: { bytes: 2500, entries: 3, max_bytes: 1073741824, max_entries: 10000, over: false }, links: 1,
    files: [file("報價.md", 1500), file(EVIL, 1000), file("捷徑", 0, { link: true })] }) });
  const main = await open();
  const names = qa(main, "file-name").map(text);
  assert.deepStrictEqual(names, ["報價.md", EVIL, "捷徑"]);
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
  assert(text(q(main, "used")).includes("3／10,000 個項目") && text(q(main, "used")).includes("2.4 KB"));
  assert(text(q(main, "links")).includes("1 個連結"));
  assert.strictEqual(qa(main, "link").length, 1);
});

test("an empty folder, a folder not made yet and a full folder are each said", async () => {
  setPage({ shared: view({ exists: false }) });
  let main = await open();
  assert(text(main).includes("還沒有這個資料夾"));
  assert(text(q(main, "empty")).includes("還沒有檔案"));
  setPage({ shared: view({ used: { bytes: 2000000000, entries: 3, max_bytes: 1073741824, max_entries: 10000, over: true } }) });
  main = await open();
  assert(text(q(main, "used")).includes("已經超過上限"));
});

test("a folder that is not safe is said, with nothing listed and nothing offered to fix it", async () => {
  setPage({ shared: view({ problem: "shared_unsafe", files: [file("a.md", 1)] }) });
  const main = await open();
  assert(text(main).includes("VBear 不會用它，也不會自己修或刪"));
  assert.strictEqual(qa(main, "file").length, 0);
  assert.strictEqual(q(main, "used"), null);
});

test("settings that cannot be read are said and nobody is guessed on", async () => {
  setPage({ shared: view({ readable: false, cards: CARDS().map((c) => ({ ...c, on: false })) }) });
  const main = await open();
  assert(text(main).includes("所有員工都當成不能用"));
  assert(qa(main, "card").every((c) => !q(c, "card-switch") || q(c, "card-switch").checked === false));
});

test("a page that cannot be read says so", async () => {
  setPage({ getStatus: 503, getBody: { error: "VBear 的背景程序現在連不上。", code: "unavailable" } });
  const main = await open();
  assert(text(main).includes("讀不到共用資料夾"));
});

test("switching an employee on asks first, says who reads what, and 取消 leaves it off and posts nothing", async () => {
  setPage();
  const main = await open();
  const sw = q(qa(main, "card")[0], "card-switch");
  sw.checked = true; sw.dispatch("change");
  await settle();
  const dlg = dialog();
  assert(dlg);
  assert(text(dlg).includes("小編") && text(dlg).includes("Anthropic") && text(dlg).includes("每一次都會先問你"));
  assert.strictEqual(posts("/api/shared/cards").length, 0);
  dlg.find((n) => n.tag === "button" && text(n) === "取消").click();
  await settle(80);
  assert.strictEqual(posts("/api/shared/cards").length, 0);
  assert.strictEqual(q(qa(main, "card")[0], "card-switch").checked, false, "the switch goes back");
});

test("after yes the card id and on are posted, and nothing else: never a path", async () => {
  setPage();
  const main = await open();
  const sw = q(qa(main, "card")[0], "card-switch");
  sw.checked = true; sw.dispatch("change");
  await settle();
  page.shared = view({ cards: CARDS().map((c) => (c.profile_id === "emp-1" ? { ...c, on: true } : c)) });
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.deepStrictEqual(posts("/api/shared/cards").map((c) => c.body), [{ profile_id: "emp-1", on: true }]);
  assert.strictEqual(q(qa(main, "card")[0], "card-switch").checked, true);
});

test("switching off posts at once without a question", async () => {
  setPage();
  const main = await open();
  const sw = q(qa(main, "card")[1], "card-switch");
  sw.checked = false; sw.dispatch("change");
  await settle(80);
  assert.strictEqual(dialog(), null);
  assert.deepStrictEqual(posts("/api/shared/cards").map((c) => c.body), [{ profile_id: "emp-2", on: false }]);
});

test("a refusal puts the switch back to what the server says and shows the words", async () => {
  setPage({ cardsStatus: 409, cardsBody: { error: "共用資料夾的位置不安全（可能被換成連結或權限被改過），VBear 不會用它。", code: "shared_unsafe" } });
  const main = await open();
  const sw = q(qa(main, "card")[0], "card-switch");
  sw.checked = true; sw.dispatch("change");
  await settle();
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.strictEqual(q(qa(main, "card")[0], "card-switch").checked, false);
  assert(text(h.dom().toastEl).includes("位置不安全"));
});

test("the Finder button posts an empty body, and a failure is said", async () => {
  setPage();
  let main = await open();
  q(main, "reveal").click();
  await settle(80);
  assert.deepStrictEqual(posts("/api/shared/reveal").map((c) => c.body), [{}]);
  assert(text(h.dom().toastEl).includes("已在 Finder 打開"));
  setPage({ revealStatus: 502 });
  main = await open();
  q(main, "reveal").click();
  await settle(80);
  assert(text(h.dom().toastEl).includes("沒能用 Finder 打開"));
});

test("the nav has the page after the memory, the route is known, and the code keeps its rules", () => {
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  assert(/data-nav="shared"><span aria-hidden="true">[^<]*<\/span>共用資料夾<\/a>/.test(html));
  assert(html.indexOf('data-nav="memory"') < html.indexOf('data-nav="shared"') && html.indexOf('data-nav="shared"') < html.indexOf('data-nav="dispatch"'));
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(/top === "shared"\) await viewShared\(\)/.test(source));
  const part = source.slice(source.indexOf("// ---------- the shared folder (P43-1"), source.indexOf("// ---------- meetings (P34-5)"));
  assert(part.length > 3000);
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}]/u;
  assert(!emoji.test(part), "no emoji in the page");
  assert(!emoji.test(html.split('data-nav="shared"')[1].split("</li>")[0]), "no emoji in the nav");
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(part));
  assert(!/https?:\/\//.test(part), "no external address");
  assert(!/\b(confirm|alert|prompt)\s*\(/.test(part.replace(/confirmInPage/g, "")), "no native dialogs");
  assert(!/localStorage|document\.cookie/.test(part));
  assert(!/console\.(log|info|warn|error)/.test(part), "no file name is written to the console");
  assert(!/\bpath\b\s*:|folder\s*:|dir\s*:/.test(part.replace(/\/\/.*$/gm, "")), "the page sends no path");
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
