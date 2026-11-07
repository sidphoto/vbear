// P43-4: what the other pages say about the shared folder: the line on a role card's back, the line on a chat page (and the check of an AI
// tool's version when it is missing, started only after a yes), the notice about a chat that is not as it was started (it now names the shared
// folder, and says that the switch works from the next word while what the employee knows follows the chat's start), and the mark on a
// group's member. The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model or a check:
// the server answers with fixtures, and every name could hold markup. The shared folder's own page is tests/frontend/shared.cjs.
// Run: node tests/frontend/shared_pages.cjs   (exit code 0 = pass)
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
const attr = (n, k) => n && n.getAttribute && n.getAttribute(k);
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-shared") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-shared") === key);
const EVIL = "<img src=x onerror=alert(1)>";
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const CID = "c-0123456789abcdef";
const NEW_CID = "c-fedcba9876543210";
const GID = "g-0123456789ab";
const P1 = "emp-1", P2 = "emp-2", P4 = "emp-4";

// ---- fixtures ---------------------------------------------------------------------------------------------------

const sharedCards = (over = {}) => [
  { profile_id: P1, name: "文案小編", tool: "claude", company: "Anthropic", can_chat: true, on: true, verified: true, ...over },
  { profile_id: P2, name: "會計師", tool: "claude", company: "Anthropic", can_chat: true, on: false, verified: true },
  { profile_id: P4, name: "Codex 員工", tool: "codex", company: "OpenAI", can_chat: true, on: false, verified: null },
  { profile_id: "emp-5", name: "舊員工", tool: "gemini", company: null, can_chat: false, on: false, verified: null },
];
const sharedView = (cards = sharedCards()) => ({ ok: true, where_text: "~/.vbear/shared", exists: true, problem: null, readable: true,
  used: { bytes: 0, entries: 0, max_bytes: 1073741824, max_entries: 10000, over: false }, links: 0, files: [], cards });
const mem = (over = {}) => ({ on: true, count: 3, readable: true, changed: false, started_with_memory: true, ...over });
const sh = (over = {}) => ({ on: true, usable: true, code: null, ...over });
const chatDetail = (over = {}) => ({ ok: true, chat: { id: CID, profile_id: P1, created_at: 1790000000, engine: "claude-chat" },
  card: { id: P1, name: "文案小編", position: "pm", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null },
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null,
  memory: mem(), shared: sh(), ...over });
const chatList = () => ({ ok: true, chats: [], more: 0, cards: [], support: { state: "verified", verify: { running: false }, policy: { ok: true, found: [], problems: [], reason: "" }, money: "x" },
  limits: { per_turn_usd: "0.5", daily_usd: "3" }, ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "" });
const groupDetail = () => ({ group: { id: GID, name: "市集準備", created_at: 1790000000, state: "idle", problem: null },
  members: [{ profile_id: P1, name: "文案小編", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null },
    { profile_id: P2, name: "會計師", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null },
    { profile_id: P4, name: EVIL, tool: "codex", engine: "codex-chat", can_chat: true, code: null, reason: null }],
  items: [], next_after: 0, last_seq: 0, more: false, round: null, current: null,
  cost: { per_turn_usd: "0.5", day_left_usd: "2.71", lamp: "green", group_today_usd: "0" },
  can: { send: true, why_not_send: null, stop: false, continue: false, drop: false, edit_members: true, delete: true } });
const mk = (id, tool, name) => ({ id, name, enabled: true, model: { tool }, position: "pm" });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { shared: sharedView(), sharedStatus: 0, detail: chatDetail(), group: groupDetail(), profiles: [], sendStatus: 202, sendBody: { ok: true },
    verifyStatus: 202, createStatus: 201, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/agent-profiles" && method === "GET") return jsonResponse({ ok: true, profiles: page.profiles });
    if (p === "/api/shared" && method === "GET") return page.sharedStatus ? jsonResponse({ error: "x", code: "unavailable" }, false, page.sharedStatus) : jsonResponse(page.shared);
    if (p === "/api/chats" && method === "GET") return jsonResponse(chatList());
    if (p === "/api/chats" && method === "POST") return jsonResponse({ chat: { id: NEW_CID, profile_id: JSON.parse(opts.body).profile_id, created_at: 1790000100, engine: "claude-chat" } }, true, 201);
    if (p === "/api/chat-support/verify" && method === "POST") {
      return page.verifyStatus < 400 ? jsonResponse({ status: { running: true } }, true, page.verifyStatus) : jsonResponse({ error: "沒能開始檢查。", code: "unavailable" }, false, page.verifyStatus);
    }
    let m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (m && m[2] === "messages" && method === "POST") {
      return page.sendStatus < 400 ? jsonResponse(page.sendBody, true, page.sendStatus) : jsonResponse(page.sendBody, false, page.sendStatus);
    }
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
const posts = (u) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === u);
const notGets = () => FETCH_LOG.filter((c) => c.method !== "GET");

// ---- the line on a role card -----------------------------------------------------------------------------------

test("the role card says whether this employee may use the shared folder, and the shared folder page changes it", () => {
  const line = app.sharedCardLine;
  assert.strictEqual(typeof line, "function");
  const on = line(sharedCards()[0]);
  assert(text(on).includes("這位員工能用共用資料夾") && on.find((n) => n.tag === "a").getAttribute("href") === "#/shared");
  assert(text(on.find((n) => n.tag === "a")).includes("到共用資料夾頁改"));
  assert(text(line(sharedCards()[1])).includes("這位員工不能用共用資料夾"));
  assert(text(line(sharedCards()[2])).includes("這位員工不能用共用資料夾"), "a Codex employee is off like the others");
  assert(text(line(sharedCards()[3])).includes("還不能聊天，用不到共用資料夾"));
  assert(text(line({ profile_id: "x", can_chat: true, company: "Someone", on: false })).includes("還不能用共用資料夾"));
  assert.strictEqual(text(line(null)), "", "no answer, no line");
});

test("the card pool puts the line on the back of each employee's card, from the shared page's own answer, and looking posts nothing", async () => {
  setPage({ profiles: [mk(P1, "claude", "文案小編"), mk(P4, "codex", "Codex 員工")] });
  const main = await open("#/team");
  const lines = qa(main, "card-line");
  assert.strictEqual(lines.length, 2);
  assert(text(lines[0]).includes("這位員工能用共用資料夾") && text(lines[1]).includes("這位員工不能用共用資料夾"));
  assert.strictEqual(notGets().length, 0, "looking changes nothing");
  setPage({ profiles: [mk(P1, "claude", "文案小編")], sharedStatus: 503 });
  const again = await open("#/team");
  assert.strictEqual(qa(again, "card-line").length, 0, "no answer, no line");
});

// ---- the line on a chat page ------------------------------------------------------------------------------------

test("a chat with an employee that is on says so, that the files are data and every write asks, and has no check", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const line = q(main, "chat-line");
  assert(line && text(line).includes("這位員工能用共用資料夾") && text(line).includes("是資料") && text(line).includes("每一次都會問你"));
  assert.strictEqual(line.find((n) => n.tag === "a").getAttribute("href"), "#/shared");
  assert.strictEqual(q(main, "chat-problem"), null);
  assert.strictEqual(q(main, "check"), null);
});

test("a chat with an employee that is off says it cannot use the shared folder", async () => {
  setPage({ detail: chatDetail({ shared: sh({ on: false, usable: false }) }) });
  const main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-line")).includes("這位員工不能用共用資料夾"));
  assert.strictEqual(q(main, "check"), null);
});

test("an older server that sends no shared field: no line at all", async () => {
  const d = chatDetail(); delete d.shared;
  setPage({ detail: d });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(q(main, "chat-line"), null);
  assert(main.find((n) => attr(n, "data-memory") === "chat-state"), "the memory line is still there");
});

test("an unsafe folder and a full folder are said in the server's words, with no check button", async () => {
  setPage({ detail: chatDetail({ shared: sh({ usable: false, code: "shared_unsafe" }) }) });
  let main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-problem")).includes("位置不安全"));
  assert.strictEqual(q(main, "check"), null);
  setPage({ detail: chatDetail({ shared: sh({ usable: false, code: "shared_full" }) }) });
  main = await open("#/chat/" + CID);
  assert(text(q(main, "chat-problem")).includes("超過 1 GiB 或 1 萬個檔案") && text(q(main, "chat-problem")).includes("把這位員工的共用資料夾關掉"));
  assert.strictEqual(q(main, "check"), null);
});

// The 「檢查」 for a version not checked with the shared folder is P43-2's single note on the chat page; tests/frontend/chat.cjs covers it.

test("a send that is refused with shared_unverified brings the same words and the check button", async () => {
  setPage({ sendStatus: 409, sendBody: { error: "這個 AI 工具的版本還沒檢查過共用資料夾。按「檢查」。你的訊息還沒有送出。", code: "shared_unverified" } });
  const main = await open("#/chat/" + CID);
  const chk = () => main.find((x) => x.getAttribute && x.getAttribute("data-chat") === "shared-check");
  assert.strictEqual(chk(), null);
  const input = main.find((n) => n.tag === "textarea" && attr(n, "data-chat") === "input");
  input.value = "你好";
  main.find((n) => n.tag === "button" && attr(n, "data-chat") === "send").click();
  await settle(80);
  assert(chk(), "the button is there (P43-2's note)");
  assert(text(q(main, "chat-problem")).includes("還要檢查一次共用資料夾"));
});

test("the notice about a chat not as it was started now names the shared folder, offers a new chat, and says what follows the switch", async () => {
  setPage({ detail: chatDetail({ memory: mem({ changed: true }), shared: sh() }) });
  const main = await open("#/chat/" + CID);
  const box = main.find((n) => attr(n, "data-memory") === "chat-changed");
  assert(box, "the notice");
  assert(text(box).includes("記憶、這位員工的固定指示或共用資料夾") && text(box).includes("還是用開始時的內容") && text(box).includes("請開新聊天"));
  const more = q(box, "changed-shared");
  assert(more, "the sentence about the shared folder");
  assert(text(more).includes("能不能寫進共用資料夾，從下一句話起就照現在的開關") && text(more).includes("員工知不知道有這個資料夾，要看聊天是什麼時候開始的"));
  assert(main.find((n) => n.tag === "button" && attr(n, "data-memory") === "new-chat"));
  main.find((n) => n.tag === "button" && attr(n, "data-memory") === "new-chat").click();
  await settle(60);
  assert.deepStrictEqual(posts("/api/chats").map((c) => c.body), [{ profile_id: P1 }]);
});

test("a chat that is as it was started says nothing of change, and a server without the shared field keeps the old words", async () => {
  setPage({ detail: chatDetail({ memory: mem({ changed: false }) }) });
  let main = await open("#/chat/" + CID);
  assert.strictEqual(main.find((n) => attr(n, "data-memory") === "chat-changed"), null);
  const d = chatDetail({ memory: mem({ changed: true }) }); delete d.shared;
  setPage({ detail: d });
  main = await open("#/chat/" + CID);
  const box = main.find((n) => attr(n, "data-memory") === "chat-changed");
  assert(text(box).includes("你改過記憶（或這位員工的固定指示），這個聊天還是用開始時的內容。要用新的，請開新聊天。"));
  assert.strictEqual(q(box, "changed-shared"), null);
});

test("a chat a group opened shows the line and no new-chat button", async () => {
  setPage({ detail: chatDetail({ memory: mem({ changed: true }), group: { id: GID, name: "虛構群組" } }) });
  const main = await open("#/chat/" + CID);
  assert(q(main, "chat-line"));
  assert.strictEqual(main.find((n) => n.tag === "button" && attr(n, "data-memory") === "new-chat"), null);
});

// ---- the mark on a group's member -------------------------------------------------------------------------------

test("a group marks the members that may use the shared folder, and an employee's name with markup stays text", async () => {
  setPage({ shared: sharedView([...sharedCards().slice(0, 3)].map((c) => (c.profile_id === P4 ? { ...c, on: true, verified: false } : c))) });
  const main = await open("#/chat/group/" + GID);
  const members = main.findAll((n) => attr(n, "data-group") === "member");
  assert.strictEqual(members.length, 3);
  assert(q(members[0], "member-mark") && text(q(members[0], "member-mark")) === "共用資料夾");
  assert.strictEqual(q(members[1], "member-mark"), null);
  assert(q(members[2], "member-mark"), "a Codex employee that is on is marked too");
  assert.strictEqual(main.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
  assert.strictEqual(notGets().length, 0, "looking changes nothing");
});

test("a group whose shared answer cannot be read has no marks and still opens", async () => {
  setPage({ sharedStatus: 503 });
  const main = await open("#/chat/group/" + GID);
  assert.strictEqual(main.findAll((n) => attr(n, "data-group") === "member").length, 3);
  assert.strictEqual(qa(main, "member-mark").length, 0);
});

// ---- the rules of the code --------------------------------------------------------------------------------------

test("the new code has no markup setting, no emoji, no outside address, no console output and sends no path", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  const part = source.slice(source.indexOf("// ---------- the shared folder (P43-1"), source.indexOf("// ---------- meetings (P34-5)"));
  const changed = source.slice(source.indexOf("function memoryChangedNote"), source.indexOf("async function viewMemory"));
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}]/u;
  for (const code of [part, changed]) {
    assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(code));
    assert(!emoji.test(code));
    assert(!/https?:\/\//.test(code));
    assert(!/console\.(log|info|warn|error)/.test(code));
  }
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  assert(!/@import|url\(\s*["']?https?:/.test(css), "no outside address in the style sheet");
  // P43-5: the merge kept one check for a version not checked with the folder (the chat page's note, data-chat="shared-check"). The second
  // one the shared-folder line used to carry (sharedStartCheck and a `check` hook) was taken out, so no code is left that nobody calls.
  assert(!/sharedStartCheck/.test(source), "no second check function");
  assert(!/data-shared": "check"/.test(source), "the shared-folder line has no check button of its own");
  const asks = source.match(/api\.post\("\/api\/chat-support\/verify"[^)]*\)/g) || [];
  const mine = asks.filter((a) => /shared: true/.test(a));
  assert.strictEqual(mine.length, 1, "exactly one place asks for the check with the folder: " + asks.join(" | "));
  assert(/\{ engine: codex \? "codex" : "claude", shared: true \}/.test(mine[0]), "it sends an engine and shared: true and nothing else");
});

test("a chat that needs the check shows exactly one note and one button, whether the server said so or a send was refused", async () => {
  const buttons = (main) => main.findAll((n) => n.tag === "button" && (attr(n, "data-chat") === "shared-check" || attr(n, "data-shared") === "check"));
  setPage({ detail: chatDetail({ shared: sh({ usable: false, code: "shared_unverified" }) }) });
  let main = await open("#/chat/" + CID);
  assert.strictEqual(buttons(main).length, 1, "the server's code");
  assert.strictEqual(qa(main, "shared-unverified").length, 0, "(a data-shared line, not the chat note)");
  assert(main.find((n) => attr(n, "data-chat") === "shared-unverified"), "it is P43-2's note");
  const line = q(main, "chat-problem");
  assert(line && text(line).includes("還要檢查一次共用資料夾"), "the shared-folder line says it in words, without a button");
  setPage({ sendStatus: 409, sendBody: { error: "還沒檢查。", code: "shared_unverified" } });
  main = await open("#/chat/" + CID);
  const input = main.find((n) => n.tag === "textarea" && attr(n, "data-chat") === "input");
  input.value = "你好";
  main.find((n) => n.tag === "button" && attr(n, "data-chat") === "send").click();
  await settle(80);
  assert.strictEqual(buttons(main).length, 1, "a refused send");
  assert.strictEqual(main.findAll((n) => attr(n, "data-chat") === "shared-unverified").length, 1, "and one note");
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
