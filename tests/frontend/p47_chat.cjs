// P47-4 (v0.21.0, ADR 0013): the chat page loses weight, the permission card speaks plainly, and "建立 CEO，開始聊" opens the conversation.
// Guard rule 15e lives here: what was folded away (the "⋯" menu, the details) still asks before it does anything, every
// warning is still on its card, the company the words go to stays on the line that is always seen, and a send refused for the day's limit says
// so in plain words with a way to the settings while the words stay in the box. The real web/app.js on a synthetic DOM and a fetch
// stub; it is NOT a browser test. Nothing here runs a model or opens a browser.
// Run: node tests/frontend/p47_chat.cjs   (exit code 0 = pass)
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
const SOURCE = fs.readFileSync(path.join(root, "app.js"), "utf8");
const CSS = fs.readFileSync(path.join(root, "style.css"), "utf8");
global.document.querySelector = () => null;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-chat") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-chat") === key);
const menu = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-chat-menu") === key);
const attr = (n, k, v) => n.find((x) => x.getAttribute && x.getAttribute(k) === v);
const CID = "c-0123456789abcdef";
const CID2 = "c-fedcba9876543210";
const KID = "k-" + "a".repeat(16);

// ---- fixtures ------------------------------------------------------------------------------------------------------

let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const card = (over = {}) => ({ card_id: KID, token: "t".repeat(32), turn: 1, tool: "Bash", input: { command: "ls -a", description: "list" },
  editable: "command", reason: "每個指令都要你允許才會執行", expires_in: 290, ...over });
const support = (over = {}) => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" },
  verify: { running: false }, money: "x", ...over });
const codexSupport = (over = {}) => ({ engine: "codex-chat", state: "ready", installed: true, version: "0.163.0", verified: true, logged_in: true, admin_policy_ok: true,
  why: "", verified_versions: ["0.163.0"], verify: { running: false }, money: "聊天用你自己的 ChatGPT 方案，不另外收費。", ...over });
const agySupport = (over = {}) => ({ engine: "agy-chat", state: "ready", installed: true, version: "1.2.3", verified: true, admin_policy_ok: true,
  why: "", verify: { running: false }, money: "AGY 用你的 Google 方案。", ...over });
const cardsList = () => [
  { id: "emp-1", name: "虛構員工", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
  { id: "emp-4", name: "Codex 員工", position: "executor", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
  { id: "emp-5", name: "AGY 員工", position: "reviewer", tool: "agy", engine: "agy-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
];
const listing = (over = {}) => ({ ok: true, chats: [], more: 0, cards: cardsList(), support: support({ codex: codexSupport(), agy: agySupport() }),
  limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["meetings", "staffing", "chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const cardOf = (id) => cardsList().find((c) => c.id === id);
const detail = (over = {}) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" }, card: cardOf("emp-1"),
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const detailFor = (id, cid, over = {}) => detail({ chat: { id: cid, profile_id: id, created_at: 1790000000, engine: cardOf(id).engine }, card: cardOf(id), ...over });
const live = (over = {}) => ({ state: "idle", turn: null, partial: "", partial_truncated: false, model: "haiku", cards: [], ...over });

let page;
const streams = [];
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), detail: detail(), sendStatus: 202, sendBody: { ok: true, turn: 1, cap_usd: "0.5", process: "new" },
    answerStatus: 200, answerBody: { ok: true }, streamMode: "ok", created: { ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1 } },
    verifyStatus: 202, extra: null, ...over };
  streams.length = 0;
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (page.extra) { const r = page.extra(p, method, opts); if (r) return r; }
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/chats" && method === "POST") return page.createStatus ? jsonResponse(page.createBody, false, page.createStatus) : jsonResponse(page.created, true, 201);
    if (p === "/api/chat-support/verify") return jsonResponse(page.verifyBody || { ok: true, status: { running: true } }, page.verifyStatus < 400, page.verifyStatus);
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return streamResponse();
    if (m && !m[2] && method === "GET") return jsonResponse(page.detail);
    if (m && !m[2] && method === "DELETE") return jsonResponse({ ok: true, deleted: m[1] });
    if (m && m[2] === "messages") return page.sendStatus < 400 ? jsonResponse(page.sendBody, true, page.sendStatus) : jsonResponse(page.sendBody, false, page.sendStatus);
    if (m && m[2] === "answer") return jsonResponse(page.answerBody);
    if (m && m[2] === "stop") return jsonResponse({ ok: true, stopped: true });
    return null;
  });
  FETCH_LOG.length = 0;
}
function streamResponse() {
  const enc = new TextEncoder();
  const queue = [];
  let wake = null, ended = false;
  const s = {
    push(obj) { queue.push(enc.encode("data: " + JSON.stringify(obj) + "\n\n")); if (wake) { wake(); wake = null; } },
    end() { ended = true; if (wake) { wake(); wake = null; } },
  };
  streams.push(s);
  return { ok: true, status: 200, headers: { get: () => "text/event-stream" }, body: { getReader: () => ({
    async read() {
      for (;;) {
        if (queue.length) return { done: false, value: queue.shift() };
        if (ended) return { done: true };
        await new Promise((r) => { wake = r; });
      }
    } }) } };
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = (fn) => { page.tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const calls = (method, suffix) => FETCH_LOG.filter((c) => c.method === method && c.url.split("?")[0].endsWith(suffix));
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const isOpen = (d) => !!d && (d.hasAttribute("open") || d.open === true);
const wordsOf = (n) => text(n);

// =====================================================================================================================
// the head: one line that is always seen, and the rest behind 「詳細資訊」
// =====================================================================================================================

test("the head is the employee's name, the 「⋯」 button, and one line: position, AI tool, asks first, and which company the words go to", async () => {
  for (const [id, cid, tool, company, position] of [["emp-1", CID, "Claude Code", "Anthropic", "CEO"], ["emp-4", CID2, "Codex", "OpenAI", "全端工程師"], ["emp-5", "c-1111111111111111", "AGY", "Google", "獨立審查"]]) {
    setPage({ detail: detailFor(id, cid) });
    const main = await open("#/chat/" + cid);
    const line = q(main, "line");
    assert(line, "the one line is there: " + id);
    const words = text(line);
    for (const w of [position, tool, "每件事先問你", "對話會送到 " + company]) assert(words.includes(w), `${id}: ${w} in ${words}`);
    assert(!/planner|executor|reviewer/.test(words), "no English position code: " + words);
    assert(!/職位：/.test(words));
    const head = main.find((n) => n.hasClass && n.hasClass("chat-head"));
    assert(head.contains(line) && !head.findAll((n) => n.tag === "details").some((d) => d.contains(line)), "the line is not inside the folded part");
    assert.strictEqual(text(head.find((n) => n.tag === "h1")), cardOf(id).name);
    assert(q(head, "more"), "the 「⋯」 button is in the head");
  }
});

test("「詳細資訊」 is closed and holds the limits, the tool's note, the memory line and the shared folder line, with the money rule's words", async () => {
  for (const [id, cid, noteKey, rule] of [["emp-1", CID, "plain-note", "員工只能在自己的工作資料夾裡讀寫"], ["emp-4", CID2, "codex-note", "不是帳單"], ["emp-5", "c-1111111111111111", "agy-note", "不是帳單"]]) {
    setPage({ detail: detailFor(id, cid, { memory: { on: true, count: 2, readable: true }, shared: { on: true, usable: true, code: null } }) });
    const main = await open("#/chat/" + cid);
    const d = q(main, "details");
    assert(d && d.tag === "details", "a details element: " + id);
    assert(!isOpen(d), "closed at first");
    assert.strictEqual(text(d.find((n) => n.tag === "summary")), "詳細資訊");
    const inside = text(d);
    for (const w of ["每回合最多 US$0.5", "今天已花 US$0.12", "花費上限 US$3", rule]) assert(inside.includes(w), `${id}: ${w}`);
    assert(d.find((n) => n.getAttribute && n.getAttribute("data-chat") === noteKey) || id === "emp-1", "the note of the tool is in the details: " + noteKey);
    assert(d.find((n) => n.getAttribute && n.getAttribute("data-memory") === "chat-state"), "the memory line is in the details");
    assert(d.find((n) => n.getAttribute && n.getAttribute("data-shared") === "chat-line"), "the shared folder line is in the details");
    assert(!text(q(main, "line")).includes("US$"), "no money on the line that is always seen");
  }
});

test("a Codex chat's and an AGY chat's whole notes (the ones that warn) stay in the details, sentence for sentence", async () => {
  setPage({ detail: detailFor("emp-4", CID2) });
  let main = await open("#/chat/" + CID2);
  const codex = text(q(q(main, "details"), "codex-note"));
  for (const w of ["每個指令都會先問你", "沒有「以後都允許」", "指令可以讀到你電腦上工作資料夾以外的檔案", "每個指令你都要看清楚才按允許", "Codex 不回報金額", "不是帳單"]) assert(codex.includes(w), w);
  setPage({ detail: detailFor("emp-5", "c-1111111111111111") });
  main = await open("#/chat/c-1111111111111111");
  const agy = text(q(q(main, "details"), "agy-note"));
  for (const w of ["每個指令都會先問你", "沒有「以後都允許」", "不能連網", "讀到的內容會送到 Google", "一回合有可能超過花費上限", "不是帳單"]) assert(agy.includes(w), w);
});

// =====================================================================================================================
// the 「⋯」 menu
// =====================================================================================================================

test("「⋯」 is a menu button: closed at first, opens on a press, and the CEO's menu has the chief of staff, a plain chat's has not", async () => {
  setPage();
  let main = await open("#/chat/" + CID);                       // emp-1 is a CEO
  const more = q(main, "more");
  assert.strictEqual(more.getAttribute("aria-haspopup"), "menu");
  assert.strictEqual(more.getAttribute("aria-expanded"), "false");
  assert(/^[^\u{1F300}-\u{1FAFF}]*$/u.test(text(more)));
  const list = q(main, "more-menu");
  assert.strictEqual(list.getAttribute("role"), "menu");
  assert.strictEqual(list.hidden, true);
  for (const k of ["chief", "memory", "skill", "dispatch", "actions", "delete"]) assert(menu(main, k), "CEO menu item " + k);
  assert.strictEqual(menu(main, "delete").getAttribute("data-chat"), "delete", "the delete item keeps data-chat=delete");
  assert.deepStrictEqual(qa(main, "delete").length, 1, "one delete button on the page");
  more.click();
  assert.strictEqual(list.hidden, false);
  assert.strictEqual(more.getAttribute("aria-expanded"), "true");
  assert.strictEqual(h.dom().bodyEl && global.document.activeElement, menu(main, "chief"), "the first item takes the focus");
  more.click();
  assert.strictEqual(list.hidden, true);
  setPage({ detail: detailFor("emp-4", CID2) });
  main = await open("#/chat/" + CID2);
  assert(!menu(main, "chief"), "only a CEO has 「請幕僚長安排」");
  for (const k of ["memory", "skill", "dispatch", "actions", "delete"]) assert(menu(main, k), "item " + k);
  const labels = ["chief", "memory", "skill", "dispatch", "actions", "delete"].map((k) => { const n = menu(main, k); return n ? text(n) : ""; }).join("|");
  assert(labels.includes("整理要記住的事") && labels.includes("整理成常用做法") && labels.includes("所有分配工作") && labels.includes("AI 自己做了什麼") && labels.includes("刪除這個對話"), labels);
  assert(!labels.includes("派工") && !labels.includes("技能"), labels);
});

test("「⋯」: Escape closes it and the focus goes back to the button; the arrow keys move through the items", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const more = q(main, "more");
  const list = q(main, "more-menu");
  more.click();
  const items = qa(list, "x").length || list.findAll((n) => n.getAttribute && n.getAttribute("role") === "menuitem");
  const all = list.findAll((n) => n.getAttribute && n.getAttribute("role") === "menuitem");
  assert(all.length >= 6, "items are menuitems");
  assert.strictEqual(global.document.activeElement, all[0]);
  list.dispatch("keydown", { key: "ArrowDown" });
  assert.strictEqual(global.document.activeElement, all[1]);
  list.dispatch("keydown", { key: "ArrowUp" });
  assert.strictEqual(global.document.activeElement, all[0]);
  list.dispatch("keydown", { key: "End" });
  assert.strictEqual(global.document.activeElement, all[all.length - 1]);
  list.dispatch("keydown", { key: "Escape" });
  assert.strictEqual(list.hidden, true);
  assert.strictEqual(more.getAttribute("aria-expanded"), "false");
  assert.strictEqual(global.document.activeElement, more);
  void items;
});

// =====================================================================================================================
// 15e: what was folded away still asks before it does anything
// =====================================================================================================================

test("15e: the delete item asks first (cost stays, tool copy), Cancel sends no DELETE, the second press sends one", async () => {
  setPage({ detail: detailFor("emp-4", CID2) });
  const main = await open("#/chat/" + CID2);
  q(main, "more").click();
  menu(main, "delete").click();
  await settle();
  const dlg = dialog();
  assert(dlg, "a confirmation");
  assert(text(dlg).includes("已花的錢仍算在今天的") && text(dlg).includes("codex-chat-home"), text(dlg));
  assert(/刪除這個對話|刪除對話/.test(text(dlg)) && !text(dlg).includes("刪除聊天"), text(dlg));
  dlg.find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle();
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0, "cancel: no DELETE");
  menu(h.dom().mainEl, "delete").click();
  await settle();
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 1);
});

test("15e: 「整理要記住的事」, 「整理成常用做法」 and 「請幕僚長安排」 only ask for a preview and open the dialog that says the cost and where the words go; nothing that spends is sent", async () => {
  const spendCalls = ["/api/memory/suggest", "/api/my-skills/suggest", "/api/chief", "/api/dispatch", "/api/memory", "/api/my-skills"];
  setPage({ extra: (p, method) => {
    if (p === "/api/memory/suggest/preview") return jsonResponse({ ok: true, preview_id: "p-1", messages: 4, memory_lines: 0, cap_usd: "0.10", day_left_usd: "2.5", sends_to: "Anthropic", blockers: [] });
    if (p === "/api/my-skills/suggest/preview") return jsonResponse({ ok: true, preview_id: "p-2", messages: 4, cap_usd: "0.10", day_left_usd: "2.5", sends_to: "Anthropic", blockers: [] });
    if (p === "/api/chief/preview") return jsonResponse({ ok: true, preview_id: "p-3", cap_usd: "0.10", day_left_usd: "2.5", sends_to: "Anthropic", blockers: [] });
    if ((p === "/api/memory/suggest" || p === "/api/my-skills/suggest" || p === "/api/chief" || p === "/api/dispatch") && method === "GET") return jsonResponse({ ok: true, suggestions: [], chief: [], dispatch: [] });
    return null;
  } });
  const main = await open("#/chat/" + CID);
  FETCH_LOG.length = 0;
  for (const [k, previewPath, dialogKey] of [["memory", "/api/memory/suggest/preview", ["data-msuggest", "dialog"]], ["skill", "/api/my-skills/suggest/preview", ["data-ksuggest", "dialog"]], ["chief", "/api/chief/preview", null]]) {
    q(main, "more").click();
    menu(main, k).click();
    await settle(80);
    const dlg = dialog();
    assert(dlg, k + ": the dialog opened");
    assert(FETCH_LOG.some((c) => c.url.split("?")[0] === previewPath), k + ": the preview was asked for");
    assert(/US\$0\.10/.test(text(dlg)) && /Anthropic/.test(text(dlg)), k + ": cost and company are in the dialog: " + text(dlg).slice(0, 200));
    void dialogKey;
    const cancel = dlg.find((n) => n.tag === "button" && n.hasClass("btn") && !n.hasClass("primary") && /取消/.test(text(n)));
    cancel.click();
    await settle();
  }
  const spent = FETCH_LOG.filter((c) => c.method !== "GET" && !c.url.split("?")[0].endsWith("/preview"));
  assert.deepStrictEqual(spent.map((c) => c.method + " " + c.url), [], "no request that spends or saves: " + JSON.stringify(spendCalls));
});

test("15e: the dispatch list and what the AI did on its own are links in the menu to the pages that already exist", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  assert.strictEqual(menu(main, "dispatch").getAttribute("href"), "#/dispatch");
  assert.strictEqual(menu(main, "actions").getAttribute("href"), "#/actions");
  assert(text(menu(main, "dispatch")).includes("所有分配工作"));
});

test("15e: a send refused for the day's limit (red or budget) says so in plain words, gives 「到設定調高」, and the words stay in the box", async () => {
  for (const [code, sentence] of [["red", "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算。"], ["budget", "今天剩下的額度不到 US$0.01，不送出。"]]) {
    setPage({ sendStatus: 409, sendBody: { error: sentence, code } });
    const main = await open("#/chat/" + CID);
    const box = q(main, "input");
    box.value = "請幫我整理下載資料夾";
    q(main, "send").click();
    await settle();
    const lim = attr(h.dom().mainEl, "data-limit", "reached");
    assert(lim, code + ": a limit notice");
    assert(text(lim).includes("今天的用量到你設的上限了") && text(lim).includes("沒有花錢") && text(lim).includes("明天 0 點"), text(lim));
    const go = attr(lim, "data-limit", "go");
    assert.strictEqual(go.getAttribute("href"), "#/settings?open=limits");
    assert.strictEqual(text(go), "到設定調高");
    assert(text(lim.find((n) => n.tag === "details")).includes(sentence), "the server's sentence is in the technical details, whole");
    assert.strictEqual(box.value, "請幫我整理下載資料夾", "the words are kept");
    assert.strictEqual(calls("POST", "/messages").length, 1, "one request, nothing sent again by itself");
    assert.strictEqual(calls("PATCH", "").length + FETCH_LOG.filter((c) => /daily-limit|\/api\/config/.test(c.url)).length, 0, "the page raised no limit");
  }
  setPage({ sendStatus: 409, sendBody: { error: "員工還在處理上一則訊息。", code: "busy" } });
  const main = await open("#/chat/" + CID);
  q(main, "input").value = "x";
  q(main, "send").click();
  await settle();
  assert(!attr(h.dom().mainEl, "data-limit", "reached"), "other refusals are not dressed as the limit");
});

test("the composer: sticky at the bottom with the safe-area, one row of send and 「用常用做法」, stop only while a turn runs, no delete button", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const comp = main.find((n) => n.hasClass && n.hasClass("chat-composer"));
  assert(comp);
  const row = comp.find((n) => n.hasClass && n.hasClass("row"));
  assert.strictEqual(text(q(row, "send")), "送出");
  assert.strictEqual(text(attr(row, "data-skill", "use")), "用常用做法");
  assert.strictEqual(q(row, "stop").hidden, true, "stop is hidden while no turn runs");
  assert(!qa(comp, "delete").length, "no delete button beside send");
  assert(!text(comp).includes("刪除"));
  const at = CSS.indexOf("/* P47-4 chat");
  const block = CSS.slice(at, CSS.indexOf("/* ---- groups", at));
  assert(block.length > 50, "the P47-4 css block");
  assert(/\.chat-composer[^{]*\{[^}]*position:\s*sticky[^}]*bottom:\s*0[^}]*\}/.test(block), "sticky bottom");
  assert(/env\(safe-area-inset-bottom\)/.test(block), "safe area");
  setPage({ detail: detail({ live: live({ state: "working", turn: 1 }) }) });
  const busy = await open("#/chat/" + CID);
  assert.strictEqual(q(busy, "stop").hidden, false);
});

// =====================================================================================================================
// the permission card: plain words, the same buttons, every warning
// =====================================================================================================================

const stripTech = (n) => text(n).split("技術細節").join("");
const nodeWithoutTech = (n) => {
  // the words of the card without what sits in its 「技術細節」 fold
  const tech = n.findAll((x) => x.tag === "details");
  const all = text(n);
  return tech.reduce((acc, d) => acc.split(text(d)).join(""), all);
};
const ENGLISH_TOOLS = /\b(Bash|Edit|Write|Read|Grep|Glob)\b/;

test("a Claude card says what the employee wants to do in plain words, with no English tool name outside 「技術細節」, and the English name is in it", () => {
  const cases = [["Bash", "執行指令", { command: "ls -a" }], ["Edit", "修改檔案", { file_path: "/tmp/x/a.md", old_string: "王小明 0912", new_string: "王小明 0912-345-678" }],
    ["Write", "建立或覆蓋檔案", { file_path: "/tmp/x/b.md", content: "hello" }], ["Read", "讀取檔案", { file_path: "/tmp/x/c.md" }],
    ["Grep", "搜尋檔案內容", { pattern: "abc", path: "/tmp/x" }], ["Glob", "找檔名", { pattern: "*.md" }]];
  for (const [tool, plain, input] of cases) {
    const node = app.chatCardNode(card({ tool, input, editable: tool === "Bash" ? "command" : tool === "Edit" ? "new_string" : null }), { who: "虛構員工", edit: { open: false }, onAnswer: () => {}, redraw: () => {} });
    const visible = nodeWithoutTech(node);
    assert(visible.includes(`虛構員工想${plain}`), `${tool}: ${visible}`);
    assert(!ENGLISH_TOOLS.test(visible), `${tool}: no English tool name in ${visible}`);
    assert(!ENGLISH_TOOLS.test(node.getAttribute("aria-label")), "nor in the label read aloud: " + node.getAttribute("aria-label"));
    const tech = q(node, "card-tech");
    assert(tech && tech.tag === "details" && !isOpen(tech), tool + ": a closed technical fold");
    assert(text(tech).includes("技術細節") && text(tech).includes(tool), tool + ": " + text(tech));
  }
  const edit = app.chatCardNode(card({ tool: "Edit", input: { file_path: "/tmp/x/a.md", old_string: "王小明", new_string: "王小明 0912" }, editable: "new_string" }), { who: "虛構員工", edit: { open: false }, onAnswer: () => {}, redraw: () => {} });
  const rows = text(edit);
  assert(rows.includes("原本的內容") && rows.includes("改成") && !rows.includes("原本的字串"), rows);
  const write = app.chatCardNode(card({ tool: "Write", input: { file_path: "/a", content: "x" }, editable: "content" }), { who: "虛構員工", edit: { open: false }, onAnswer: () => {}, redraw: () => {} });
  assert(text(write).includes("要寫入的內容"));
  const grep = app.chatCardNode(card({ tool: "Grep", input: { pattern: "abc", description: "找" }, editable: null }), { who: "虛構員工", edit: { open: false }, onAnswer: () => {}, redraw: () => {} });
  assert(text(grep).includes("要找的字") && text(grep).includes("員工的說明"), text(grep));
});

test("15e: a card has exactly 「允許這一次」, 「改內容再允許」 (when there is something to change) and 「拒絕」; there is no 'allow from now on'", () => {
  const buttonsOf = (n) => n.findAll((x) => x.tag === "button").map((b) => text(b));
  const with_edit = app.chatCardNode(card({ tool: "Bash" }), { who: "虛構員工", edit: { open: false }, onAnswer: () => {}, redraw: () => {} });
  assert.deepStrictEqual(buttonsOf(with_edit), ["允許這一次", "改內容再允許", "拒絕"]);
  const nothing = app.chatCardNode(card({ tool: "Read", input: { file_path: "/a" }, editable: null }), { who: "虛構員工", onAnswer: () => {} });
  assert.deepStrictEqual(buttonsOf(nothing), ["允許這一次", "拒絕"]);
  const codex = app.chatCardNode(card({ tool: "command", editable: "command", input: { command: "ls", cwd: "." } }), { engine: "codex-chat", who: "虛構員工", edit: { open: false }, onAnswer: () => {}, redraw: () => {} });
  assert.deepStrictEqual(buttonsOf(codex), ["允許這一次", "改內容再問", "拒絕"]);
  for (const n of [with_edit, nothing, codex]) assert(!/以後都允許|永遠允許|一律允許|都允許/.test(text(n)), text(n));
});

test("15e: every warning of a card is on the same card, sentence for sentence (the names changed, no sentence left out)", () => {
  const on = (n, ...words) => { const t = text(n); for (const w of words) assert(t.includes(w), w + " in " + t); };
  const codexCmd = app.chatCardNode(card({ tool: "command", editable: "command", input: { command: "ls", cwd: "." } }), { engine: "codex-chat", who: "A", edit: { open: true, text: "x" }, onAnswer: () => {}, redraw: () => {} });
  on(codexCmd, app.CHAT_CODEX_SANDBOX_WARNING, app.CHAT_ASK_AGAIN);
  const agyCmd = app.chatCardNode(card({ tool: "command", editable: "command", input: { command: "ls", cwd: "." } }), { engine: "agy-chat", who: "A", edit: { open: true, text: "x" }, onAnswer: () => {}, redraw: () => {} });
  on(agyCmd, app.CHAT_AGY_SANDBOX_WARNING, app.CHAT_AGY_ASK_AGAIN);
  const agyRead = app.chatCardNode(card({ tool: "read", editable: null, input: { paths: ["/tmp/x/outside.md"] } }), { engine: "agy-chat", who: "A", onAnswer: () => {} });
  on(agyRead, app.CHAT_AGY_READ_WARNING, app.CHAT_AGY_READ_NOTE);
  for (const [name, w] of [["CHAT_CODEX_SANDBOX_WARNING", app.CHAT_CODEX_SANDBOX_WARNING], ["CHAT_AGY_SANDBOX_WARNING", app.CHAT_AGY_SANDBOX_WARNING], ["CHAT_AGY_READ_WARNING", app.CHAT_AGY_READ_WARNING],
    ["CHAT_AGY_READ_NOTE", app.CHAT_AGY_READ_NOTE], ["CHAT_ASK_AGAIN", app.CHAT_ASK_AGAIN], ["CHAT_AGY_ASK_AGAIN", app.CHAT_AGY_ASK_AGAIN]]) assert(typeof w === "string" && w.length > 10, name);
  // the facts the warnings carry: nothing was weakened
  assert(/保護範圍（沙盒）外執行/.test(app.CHAT_CODEX_SANDBOX_WARNING) && app.CHAT_CODEX_SANDBOX_WARNING.includes("也能連網") && app.CHAT_CODEX_SANDBOX_WARNING.includes("只允許你看得懂、確定沒問題的指令"));
  assert(app.CHAT_AGY_SANDBOX_WARNING.includes("不能連網") && app.CHAT_AGY_SANDBOX_WARNING.includes("只允許你看得懂、確定沒問題的指令"));
  assert(app.CHAT_AGY_READ_WARNING.includes("送到 Google") && app.CHAT_AGY_READ_WARNING.includes("只允許你確定可以給它看的檔案"));
  assert(app.CHAT_ASK_AGAIN.includes("再按一次允許") && app.CHAT_AGY_ASK_AGAIN.includes("再按一次允許"));
  assert(app.CHAT_AGY_READ_NOTE.includes("只能允許或拒絕"));
});

test("the records of the transcript say the tool in plain words too", () => {
  const t = (rec) => text(app.chatLine({ seq: 1, at: 1790000000, ...rec }, { who: "虛構員工" }));
  assert(t({ kind: "tool_call", tool: "Bash", summary: "ls" }).includes("執行指令") && !ENGLISH_TOOLS.test(t({ kind: "tool_call", tool: "Bash", summary: "ls" })));
  assert(t({ kind: "card", card_id: KID, tool: "Edit" }).includes("虛構員工想修改檔案"), t({ kind: "card", card_id: KID, tool: "Edit" }));
  assert(t({ kind: "denied", tool: "Write", reason: "outside", summary: "x" }).includes("建立或覆蓋檔案"));
  assert(!ENGLISH_TOOLS.test(t({ kind: "auto_allowed", tool: "Read", summary: "x", reason: "folder" }).replace("folder", "")), "auto allowed read");
});

// =====================================================================================================================
// the lines of a chat: who speaks, what the money looks like, the buttons that wait for a hover
// =====================================================================================================================

test("the employee's own name is over what the employee says; a message VBear sent for a distributed job says so in the new words", async () => {
  seqNo = 0;
  const records = [rec("user_message", { turn: 1, text: "你好" }), rec("reply", { turn: 1, text: "你好，我是虛構員工。", truncated: false }),
    rec("user_message", { turn: 2, text: "第二步", origin: { dispatch: "d-0123456789ab", step: 2 } })];
  setPage({ detail: detail({ records, last_seq: 3, next_after: 3 }) });
  const main = await open("#/chat/" + CID);
  const log = q(main, "log");
  const who = (n) => text(n.find((x) => x.hasClass && x.hasClass("chat-who")));
  const [me, them, sent] = log.children;
  assert(who(me).startsWith("你・"));
  assert(who(them).startsWith("虛構員工・"), who(them));
  assert(who(sent).startsWith("VBear 依分配工作送出"), who(sent));
  assert(!text(main).includes("依派工"), "the old word is gone");
});

test("each spoken line can take the focus (tabindex 0), and its two buttons are in the page all the time, with the new words", async () => {
  seqNo = 0;
  const records = [rec("user_message", { turn: 1, text: "你好" }), rec("reply", { turn: 1, text: "我是虛構員工", truncated: false })];
  setPage({ detail: detail({ records, last_seq: 2, next_after: 2 }) });
  const main = await open("#/chat/" + CID);
  for (const li of q(main, "log").children) {
    assert.strictEqual(li.getAttribute("tabindex"), "0");
    const buttons = li.findAll((x) => x.tag === "button").map((b) => text(b));
    assert.deepStrictEqual(buttons, ["記住", "存成常用做法"]);
    assert(li.find((x) => x.getAttribute && x.getAttribute("data-memory") === "remember") && li.find((x) => x.getAttribute && x.getAttribute("data-skill") === "save-line"), "the data-* are kept");
  }
  const at = CSS.indexOf("/* P47-4 chat");
  const block = CSS.slice(at, CSS.indexOf("/* ---- groups", at));
  assert(/\.chat-msg:hover \.chat-remember/.test(block) && /\.chat-msg:focus-within \.chat-remember/.test(block) && /\.chat-msg:focus \.chat-remember/.test(block), "shown on hover and on focus");
  assert(/\.chat-msg \.chat-remember\s*\{[^}]*opacity:\s*0/.test(block) && !/\.chat-msg \.chat-remember\s*\{[^}]*display:\s*none/.test(block), "hidden by opacity, never display none (a keyboard still reaches it)");
});

test("15e: a turn that ended well writes no words and keeps the money and the 'estimate, not a bill' behind 「詳細資訊」; a stop or an error still says why", async () => {
  seqNo = 0;
  const records = [rec("process_started", { mode: "new", budget_usd: "0.5", instructions: true }),
    rec("turn_ended", { turn: 1, cost_usd: "0.0123", reported: true, total_usd: 0.0123, reason: "result", subtype: "success", is_error: false }),
    rec("turn_ended", { turn: 2, cost_usd: "0.5", reported: false, total_usd: 0.5, reason: "stopped", subtype: "x", is_error: true }),
    rec("turn_ended", { turn: 3, cost_usd: "0.2", reported: true, total_usd: 0.2, reason: "limit", subtype: "x", is_error: true })];
  setPage({ detail: detail({ records, last_seq: 4, next_after: 4 }) });
  const main = await open("#/chat/" + CID);
  const rows = q(main, "log").children;
  const [started, ok, stopped, limit] = rows;
  const visible = (li) => nodeWithoutTech(li).split(text(li.find((x) => x.tag === "details"))).join("").replace("詳細資訊", "");
  assert.strictEqual(visible(ok).trim(), "", "a turn that ended well writes nothing: " + visible(ok));
  assert(visible(stopped).includes("你按了停止"), visible(stopped));
  assert(visible(limit).includes("用量到了這回合的上限"), visible(limit));
  for (const li of [ok, stopped, limit]) {
    const d = li.find((x) => x.tag === "details");
    assert(d && !isOpen(d), "folded");
    assert(!visible(li).includes("US$"), "no money in view: " + visible(li));
  }
  assert(text(ok).includes("US$0.0123") && text(ok).includes("Claude Code 回報的估值"), "the money is in the page: " + text(ok));
  assert(text(stopped).includes("US$0.5") && text(stopped).includes("按上限"), text(stopped));
  const sv = visible(started);
  assert(sv.includes("員工上線") && !sv.includes("US$") && !sv.includes("角色卡"), sv);
  assert(text(started).includes("這次最多可花 US$0.5"), "the most it may cost is still in the page: " + text(started));
  // the estimate is said for Codex and AGY as well, folded the same way
  const codexRec = app.chatLine({ seq: 5, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.03", reported: false, estimate: true, tokens: 30000, reason: "result" }, { engine: "codex-chat" });
  assert(text(codexRec).includes("不是帳單") && !visible(codexRec).includes("US$"));
  const agyRec = app.chatLine({ seq: 5, at: 1, kind: "turn_ended", turn: 1, cost_usd: "0.03", reported: false, estimate: true, tokens: 30000, reason: "result" }, { engine: "agy-chat" });
  assert(text(agyRec).includes("不是帳單") && text(agyRec).includes("Google 方案"));
});

test("the chat list shows no money on its rows and puts the long explanation and the day's total behind 「了解更多」, closed even on the first visit", async () => {
  global.localStorage._store = {};
  seqNo = 0;
  const chats = [{ id: CID, profile_id: "emp-1", name: "虛構員工", engine: "claude-chat", created_at: 1790000000, last_at: 1790000100, turns: 2, spent_usd: "0.0345", open: false, waiting: false, last_text: "你好", last_kind: "user" }];
  setPage({ list: listing({ chats }) });
  const main = await open("#/chat");
  const row = main.find((n) => n.getAttribute && n.getAttribute("data-chat") === "row");
  assert(row && !text(row).includes("US$") && !text(row).includes("估值") && text(row).includes("2 回合"), text(row));
  const more = q(main, "more-info");
  assert(more && more.tag === "details" && !isOpen(more), "closed at first");
  assert(text(more.find((n) => n.tag === "summary")).includes("了解更多"));
  const inside = text(more);
  assert(inside.includes("今天已花 US$0.12") && inside.includes("會花錢") && inside.includes("不會自己動手"), "the explainer and the day's total are in it");
  assert(!isOpen(q(main, "intro")) , "the explainer is closed on the first visit, too");
  assert.strictEqual(global.localStorage.getItem("vbear-chat-intro-seen"), null, "nothing is remembered in the browser");
  const outside = text(main).split(inside).join("");
  assert(!outside.includes("US$"), "no money outside the folded part: " + outside.slice(0, 300));
  assert(!/角色卡|額度|沙盒/.test(outside), outside);
});

// =====================================================================================================================
// 「建立 CEO，開始聊」 opens the conversation; when the AI tool cannot chat yet, one reason and one action
// =====================================================================================================================

const OPENING = "你好，請先問我三個問題，了解我想做什麼。";
const NEW_ID = "prof-0123456789ab";
const ceoPlan = (over = {}) => ({ ok: true, needed: true, can_create: true, go: null, reason: "", tool: "claude", tool_name: "Claude Code", name: "CEO",
  position: "planner", launch_mode: "safe", instructions: "你是我的 CEO。", opening: OPENING, chat_ready: null, chat_note: "", ...over });
const newCard = (over = {}) => ({ id: NEW_ID, name: "CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true, ...over });
const ceoExtra = (over = {}) => (p, method) => {
  if (p === "/api/first-ceo") return jsonResponse(ceoPlan(over));
  if (p === "/api/agent-profiles" && method === "POST") return jsonResponse({ ok: true, profile: { id: NEW_ID, name: "CEO" } }, true, 201);
  if (p === "/api/config" && method === "POST") return jsonResponse({ ok: true });
  return null;
};
const prepList = (cardOver, supOver = {}) => listing({ cards: [newCard(cardOver)], support: support({ codex: codexSupport(), agy: agySupport(), ...supOver }) });
async function press(key, root) { q(root || h.dom().mainEl, key).click(); await settle(80); }

test("CEO: 「建立 CEO，開始聊」 makes the employee and opens the conversation; the opening sentence is only in the box, and nothing is sent", async () => {
  setPage({ extra: ceoExtra(), created: { ok: true, chat: { id: CID, profile_id: NEW_ID, created_at: 1 } }, detail: detail({ card: newCard(), chat: { id: CID, profile_id: NEW_ID, created_at: 1, engine: "claude-chat" } }) });
  let main = await open("#/ceo");
  const go = main.find((n) => n.getAttribute && n.getAttribute("data-ceo") === "create");
  assert.strictEqual(text(go), "建立 CEO，開始聊");
  go.click();
  await settle(80);
  assert.strictEqual(global.location.hash, "#/chat/" + CID, "straight into the conversation");
  assert.strictEqual(calls("POST", "/api/agent-profiles").length, 1);
  assert.strictEqual(calls("POST", "/api/chats").length, 1);
  main = await open(global.location.hash);
  assert.strictEqual(q(main, "input").value, OPENING, "the opening sentence is in the box");
  assert.strictEqual(calls("POST", "/messages").length, 0, "pressing nothing sends nothing");
  assert(text(main).includes("按「送出」才會真的送出"), "and it says so");
});

test("CEO: the page no longer says 'the assignment feature is not there yet'; it says where it is and that the CEO proposes and you confirm", async () => {
  setPage({ extra: ceoExtra() });
  const main = await open("#/ceo");
  const all = text(main);
  assert(!all.includes("功能還沒有") && !all.includes("角色卡") && !all.includes("安全模式") && !all.includes("大廳"), all);
  assert(all.includes("請幕僚長安排") && all.includes("你確認") && all.includes("每件事先問我"), all);
  assert(text(main.find((n) => n.getAttribute && n.getAttribute("data-ceo") === "later")).includes("首頁"));
});

test("CEO: when the AI tool cannot chat yet the person lands on one page with one reason and one action, not on the list with the long explanation", async () => {
  setPage({ extra: ceoExtra(), createStatus: 409, createBody: { ok: false, error: "這個 Claude Code 版本還沒通過聊天驗證。", code: "unverified" },
    list: prepList({ can_chat: true }, { state: "unverified", message: "還沒有通過驗證" }) });
  let main = await open("#/ceo");
  main.find((n) => n.getAttribute && n.getAttribute("data-ceo") === "create").click();
  await settle(80);
  assert.strictEqual(global.location.hash, "#/chat?profile=" + NEW_ID);
  main = await open(global.location.hash);
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "準備和 CEO 聊天");
  assert(q(main, "prep-reason") && text(q(main, "prep-reason")).length > 5 && text(q(main, "prep-reason")).length < 80, text(q(main, "prep-reason")));
  const actions = main.findAll((n) => n.getAttribute && n.getAttribute("data-chat") === "prep-action");
  assert.strictEqual(actions.length, 1, "exactly one action");
  assert.strictEqual(text(actions[0]), "先做一次安全檢查");
  const more = q(main, "prep-more");
  assert(more && more.tag === "details" && !isOpen(more), "the explanation is folded");
  assert(text(more).includes("聊天怎麼運作") || text(more).includes("會花錢"));
  const outside = text(main).split(text(more)).join("");
  assert(!outside.includes("會花錢") && !outside.includes("不會自己動手"), "the long explainer is not in view: " + outside);
  assert.strictEqual(calls("POST", "/api/chat-support/verify").length, 0);
});

test("CEO: the safety check asks first (it uses the person's own login, under US$0.05, a few minutes); a no sends nothing; a yes starts it once, and when it passes the conversation opens by itself with the opening in the box", async () => {
  setPage({ extra: ceoExtra(), createStatus: 409, createBody: { ok: false, error: "x", code: "unverified" }, list: prepList({}, { state: "unverified", message: "還沒有通過驗證" }) });
  let main = await open("#/ceo");
  main.find((n) => n.getAttribute && n.getAttribute("data-ceo") === "create").click();
  await settle(80);
  main = await open(global.location.hash);
  await press("prep-action", main);
  const dlg = dialog();
  assert(dlg, "a confirmation");
  assert(text(dlg).includes("US$0.05") && text(dlg).includes("幾分鐘") && text(dlg).includes("你自己的登入"), text(dlg));
  assert.strictEqual(calls("POST", "/api/chat-support/verify").length, 0, "asking sends nothing");
  dlg.find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle();
  assert.strictEqual(calls("POST", "/api/chat-support/verify").length, 0, "no sends nothing");
  await press("prep-action", h.dom().mainEl);
  page.list = prepList({}, { state: "unverified", verify: { running: true } });
  dialog().find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.deepStrictEqual(calls("POST", "/api/chat-support/verify").map((c) => c.body), [{ version: "2.1.318" }]);
  assert(q(h.dom().mainEl, "prep-running"), "it says the check is running");
  assert.strictEqual(calls("POST", "/api/chats").length, 1, "no conversation was opened while it runs (only the one that failed before)");
  page.list = prepList({});
  page.created = { ok: true, chat: { id: CID, profile_id: NEW_ID, created_at: 1 } };
  page.createStatus = null;
  page.detail = detail({ card: newCard(), chat: { id: CID, profile_id: NEW_ID, created_at: 1, engine: "claude-chat" } });
  await page.tick();
  await settle(80);
  assert.strictEqual(global.location.hash, "#/chat/" + CID, "it opened by itself");
  const chat = await open(global.location.hash);
  assert.strictEqual(q(chat, "input").value, OPENING);
  assert.strictEqual(calls("POST", "/messages").length, 0, "nothing was sent");
});

test("the page for a chat that cannot start yet: each reason has one action in plain words (Codex login, AGY check, a tool that is not set up, a card that cannot chat)", async () => {
  const cases = [
    ["codex not logged in", prepList({ id: "emp-4", tool: "codex", engine: "codex-chat", name: "Codex 員工" }, { codex: codexSupport({ state: "not_logged_in", logged_in: false, why: "聊天用的 Codex 還沒登入。" }) }), "emp-4", "到 AI 工具登入聊天用的 Codex", "#/setup"],
    ["codex not installed", prepList({ id: "emp-4", tool: "codex", engine: "codex-chat", name: "Codex 員工" }, { codex: codexSupport({ state: "not_installed", installed: false, why: "沒有找到 Codex。" }) }), "emp-4", "到 AI 工具看看", "#/setup"],
    ["claude version unreadable", prepList({}, { state: "unknown", detected: null, message: "讀不到版本" }), NEW_ID, "到 AI 工具看看", "#/setup"],
    ["agy unverified", prepList({ id: "emp-5", tool: "agy", engine: "agy-chat", name: "AGY 員工" }, { agy: agySupport({ state: "unverified", verified: false }) }), "emp-5", "驗證聊天", null],
    ["card cannot chat", prepList({ can_chat: false, enabled: false, code: "card_disabled", reason: "這位員工已停用，啟用之後才能聊天。" }), NEW_ID, "到員工頁看看", "#/employees"],
  ];
  for (const [name, list, id, label, href] of cases) {
    setPage({ list });
    const main = await open("#/chat?profile=" + id);
    const actions = main.findAll((n) => n.getAttribute && n.getAttribute("data-chat") === "prep-action");
    assert.strictEqual(actions.length, 1, name + ": one action");
    assert.strictEqual(text(actions[0]), label, name);
    if (href) assert.strictEqual(actions[0].getAttribute("href"), href, name);
    assert(text(q(main, "prep-reason")).length > 4, name);
    assert.strictEqual(calls("POST", "/api/chat-support/verify").length + calls("POST", "/api/chats").length, 0, name + ": opening the page sends nothing");
  }
  setPage({ list: prepList({}, { state: "verified" }) });
  const main = await open("#/chat?profile=" + NEW_ID);
  assert.strictEqual(text(q(main, "prep-action")), "開始聊天");
  assert.strictEqual(calls("POST", "/api/chats").length, 0, "even when ready, the page does not open a conversation by itself");
});

test("15e: a day at its limit keeps the conversation from starting, says so in plain words, and shows the way to the settings", async () => {
  setPage({ list: listing({ cards: [newCard()], ledger: { spent_usd: "3", daily_usd: "3", lamp: "red", includes: [] } }) });
  const main = await open("#/chat?profile=" + NEW_ID);
  assert(attr(main, "data-limit", "reached") && attr(attr(main, "data-limit", "reached"), "data-limit", "go").getAttribute("href") === "#/settings?open=limits");
  assert.strictEqual(q(main, "prep-action").disabled, true);
});

// =====================================================================================================================
// 15e as checks on the source, each with a small sample that must trip it (so the check is known to be able to fail)
// =====================================================================================================================

const between = (src, from, to) => { const a = src.indexOf(from); if (a < 0) return ""; const b = src.indexOf(to, a + from.length); return src.slice(a, b < 0 ? undefined : b); };
const rules15e = {
  // the delete item asks (confirmInPage) before it deletes
  deleteAsks(src) {
    const body = between(src, "const deleteThisChat = async () => {", "const menuItems");
    const ask = body.indexOf("confirmInPage("), del = body.indexOf("api.del(");
    return ask >= 0 && del > ask && /if \(!\(await confirmInPage\([\s\S]*\)\)\) return;/.test(body);
  },
  // the items of the menu only open the dialogs that were always there; the desks' openDialog asks only for the preview before the dialog
  menuOnlyOpens(src) {
    const menu = between(src, "const menuItems = inGroup", "const more = inGroup");
    const presses = [...menu.matchAll(/onPress: ([^,}]+)/g)].map((m) => m[1].trim());
    const allowed = ["() => chief.open()", "() => suggest.open()", "() => skillDesk.open()", "deleteThisChat"];
    if (!presses.every((x) => allowed.includes(x))) return false;
    const desks = [["function chiefDesk(", "openChiefDialog(pv", "/api/chief/preview"], ["function memorySuggestDesk(", "openMemorySuggestDialog(pv", "/api/memory/suggest/preview"],
      ["function skillSuggestDesk(", "openSkillSuggestDialog(pv", "/api/my-skills/suggest/preview"]];
    return desks.every(([a, b, preview]) => {
      const open = between(between(src, a, "\n}\n"), "async function openDialog() {", b);
      const apis = [...open.matchAll(/api\.(get|post|del|patch)\(([^,)]+)/g)].map((m) => m[2]);
      return apis.length === 1 && apis[0].includes(preview);
    });
  },
  // a card has the three buttons it always had and no way to allow for good; its warnings are on it
  cardKeepsWarnings(src) {
    const body = between(src, "function chatCardNode(card, opts) {", "// ---- the support notice");
    const keys = [...body.matchAll(/"data-chat": "(allow-edited|cancel-edit|allow|modify|deny)"/g)].map((m) => m[1]).sort().join();
    if (keys !== "allow,allow-edited,cancel-edit,deny,modify") return false;
    if (/以後都允許|永遠允許|一律允許|always|remember/i.test(body.replace(/\/\/[^\n]*/g, ""))) return false;
    return ["CHAT_CODEX_SANDBOX_WARNING", "CHAT_AGY_SANDBOX_WARNING", "CHAT_AGY_READ_WARNING", "CHAT_AGY_READ_NOTE", "CHAT_ASK_AGAIN", "CHAT_AGY_ASK_AGAIN"].every((c) => body.includes(c));
  },
  // a send refused for the limit is dressed by limitReachedNotice and the box is cleared only after a send that went through
  limitSaid(src) {
    // the chat page's send is the one right before its stop (the home page has a send of its own earlier in the file)
    const stopAt = src.indexOf("async function stop() {");
    const body = stopAt < 0 ? "" : src.slice(src.lastIndexOf("async function send() {", stopAt), stopAt);
    const clears = [...body.matchAll(/input\.value = ""/g)].length;
    const catchAt = body.indexOf("} catch (e) {");
    return body.includes("limitReachedNotice(") && clears === 1 && body.indexOf('input.value = ""') < catchAt && body.slice(catchAt).indexOf('input.value') < 0;
  },
  // the line that is always seen says the company; it is not behind the details
  companyOnTheLine(src) {
    const body = between(src, "function chatHeadLine(", "// P47-4: the 「⋯」 menu");
    return /對話會送到/.test(body) && /chatCompanyOf\(/.test(body);
  },
};
const ruleNames = Object.keys(rules15e);

test("15e: the rules hold on the real source", () => {
  for (const name of ruleNames) assert.strictEqual(rules15e[name](SOURCE), true, name);
});

test("15e: each rule trips on a small sample that breaks it (so it can fail)", () => {
  const broken = {
    deleteAsks: SOURCE.replace("if (!(await confirmInPage(\"刪除這個對話\"", "if (!(await Promise.resolve(\"刪除這個對話\""),
    menuOnlyOpens: SOURCE.replace("onPress: () => suggest.open() }", "onPress: () => api.post(\"/api/memory/suggest\", {}) }"),
    cardKeepsWarnings: SOURCE.replace("card.tool === \"command\" ? el(\"p\", { class: \"small\", \"data-chat\": \"sandbox-warning\", role: \"note\" }, agy ? CHAT_AGY_SANDBOX_WARNING : CHAT_CODEX_SANDBOX_WARNING) : null,", "null,"),
    limitSaid: SOURCE.replace("setKids(limitBox, limitReachedNotice(e.message))", "setKids(limitBox, null)"),
    companyOnTheLine: SOURCE.replace("`對話會送到 ${chatCompanyOf(engine || (c && c.tool))}`", "\"\""),
  };
  for (const name of ruleNames) {
    assert.notStrictEqual(broken[name], SOURCE, name + ": the sample really changes the source");
    assert.strictEqual(rules15e[name](broken[name]), false, name + " trips");
  }
  // an extra button with the forbidden words trips the card rule too
  const withAlways = SOURCE.replace("\"拒絕\")),\n    // P47-4: the tool's own", "\"拒絕\"), el(\"button\", { type: \"button\", \"data-chat\": \"always\" }, \"以後都允許\")),\n    // P47-4: the tool's own");
  assert.notStrictEqual(withAlways, SOURCE);
  assert.strictEqual(rules15e.cardKeepsWarnings(withAlways), false);
});

test("15e: the page and the rule's words obey the product rules: no innerHTML, no emoji, no outside address, only el() text", () => {
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(SOURCE));
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}]/u;
  const chatPart = between(SOURCE, "chat with role cards (P36-2)", "// ---------- meetings (P34-5)");
  assert(chatPart.length > 5000 && !emoji.test(chatPart));
  assert(!/https?:\/\//.test(chatPart));
  const at = CSS.indexOf("/* P47-4 chat");
  const block = CSS.slice(at, CSS.indexOf("/* ---- groups", at));
  assert(!emoji.test(block) && !/https?:|@import|url\(/.test(block));
});

// ---- run ---------------------------------------------------------------------------------------------------------

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
