// The "this needs Claude Code" note (v0.12 task 7): the one shared note on the pages that only work through Claude Code
// (meetings, staffing meetings, chat, translating skill descriptions). Shown when the start-up status says Claude Code is
// not ready; not shown when it is ready; when the status cannot be read nothing is shown and the page works as before.
// The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/needs_claude.cjs   (exit code 0 = pass)
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
const byAttr = (root, k, v) => root.findAll((n) => attr(n, k) === v);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- the Claude Code note"), SRC.indexOf("// ---------- end of the Claude Code note"));

const row = (id, state, over = {}) => ({ id, name: id, state, ready: state === "ready", installed: state !== "not_installed", ...over });
const statusOf = (claude, extra = []) => ({ ok: true, tools: [claude, row("codex", "ready"), ...extra], any_ready: true, setup_done: true });

let status;       // the body GET /api/setup/tools answers, or null for a failure
let engine;
function setServer(s, eng = "claude") {
  status = s; engine = eng;
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/setup/tools" && method === "GET") return status ? jsonResponse(status) : jsonResponse({ error: "boom" }, false, 500);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/translations") return jsonResponse({ ok: true, engine, entries: {}, counts: {}, job: null });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/meetings") return jsonResponse({ ok: true, meetings: [] });
    if (p === "/api/staffing") return jsonResponse({ ok: true, staffing: [] });
    if (p === "/api/meetings/ledger") return jsonResponse({ ok: true, lamp: "green" });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/chats") return jsonResponse({ ok: true, chats: [], cards: [], support: { state: "verified" }, limits: null, ledger: null });
    return null;
  });
}
async function open(hash) {
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const notes = (main) => byAttr(main, "data-needs-claude", "note");

// every page that works only through Claude Code, and a word that proves the page itself still drew
const PAGES = [["meetings", "#/meetings", "會議"], ["staffing", "#/staffing", "組隊會議"], ["chat", "#/chat", "跟員工聊天"], ["skills (translation)", "#/skills", "技能庫"]];

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("claudeCodeNeed: only a readable list that says Claude Code is not ready counts as needed", () => {
  assert.strictEqual(app.claudeCodeNeed(statusOf(row("claude", "not_installed"))), "needed");
  assert.strictEqual(app.claudeCodeNeed(statusOf(row("claude", "not_logged_in"))), "needed");
  assert.strictEqual(app.claudeCodeNeed(statusOf(row("claude", "ready"))), "ready");
  for (const bad of [null, undefined, {}, { ok: true }, { tools: "x" }, { tools: [] }, { tools: [row("codex", "ready")] }, { tools: [row("claude", "weird")] }, { tools: [null] }]) {
    assert.strictEqual(app.claudeCodeNeed(bad), "unknown", JSON.stringify(bad));
  }
  assert.strictEqual(app.claudeCodeNeed({ tools: [{ id: "claude", state: "ready", ready: false }] }), "unknown", "a list that contradicts itself is not guessed");
});

for (const [name, hash, heading] of PAGES) {
  for (const state of ["not_installed", "not_logged_in"]) {
    test(`${name}: Claude Code ${state} shows the note, the way to get it and a button to ${"#/setup"}`, async () => {
      setServer(statusOf(row("claude", state)));
      const main = await open(hash);
      assert(text(main).includes(heading), "the page itself still drew");
      const n = notes(main);
      assert.strictEqual(n.length, 1, "exactly one note");
      const t = text(n[0]);
      assert(t.includes("這個功能目前需要 Claude Code"), t);
      assert(/Claude/.test(t) && /付費方案/.test(t), "how to get it: a paid Claude plan");
      assert(/開始設定/.test(t) && /安裝/.test(t) && /登入/.test(t), "install and log in on the start-up page");
      const btn = n[0].find((x) => attr(x, "data-needs-claude") === "go");
      assert(btn, "a button");
      assert.strictEqual(attr(btn, "href"), "#/setup");
      assert.strictEqual(text(btn), "到開始設定");
    });
  }
  test(`${name}: Claude Code ready shows no note`, async () => {
    setServer(statusOf(row("claude", "ready")));
    const main = await open(hash);
    assert(text(main).includes(heading));
    assert.strictEqual(notes(main).length, 0);
  });
  test(`${name}: a status that cannot be read shows no note and does not block the page`, async () => {
    setServer(null);
    let main = await open(hash);
    assert(text(main).includes(heading));
    assert.strictEqual(notes(main).length, 0);
    assert(!/載入失敗/.test(text(main)));
    setServer({ ok: true });
    main = await open(hash);
    assert(text(main).includes(heading));
    assert.strictEqual(notes(main).length, 0, "a body without the list says nothing");
  });
}

test("the note is the same component on every page: same title, same way to get it, same button; only one sentence about the page differs", async () => {
  setServer(statusOf(row("claude", "not_installed")));
  const seen = new Set();
  for (const [, hash] of PAGES) {
    const n = notes(await open(hash));
    assert.strictEqual(n.length, 1, hash);
    const t = text(n[0]);
    assert(/^i?這個功能目前需要 Claude Code/.test(t), t);
    seen.add(t.replace(/^i?這個功能目前需要 Claude Code[^。]*。/, ""));
  }
  assert.strictEqual(seen.size, 1, "the rest of the wording is identical everywhere");
});

test("skills page: the note is only for translating with Claude Code, not when the engine is Codex", async () => {
  setServer(statusOf(row("claude", "not_installed")), "codex");
  const main = await open("#/skills");
  assert(text(main).includes("技能庫"));
  assert.strictEqual(notes(main).length, 0);
});

test("chat page: a Codex that has its chat login is a way to chat, so the note about Claude Code is held back; the person's own Codex alone is not", async () => {
  const codexChat = (login) => ({ ok: true, tools: [row("claude", "not_installed"), row("codex", "ready", { chat_login: { state: login, problem: "" } })], any_ready: true, setup_done: true });
  setServer(codexChat("logged_in"));
  let main = await open("#/chat");
  assert(text(main).includes("跟員工聊天"));
  assert.strictEqual(notes(main).length, 0, "Codex can chat");
  setServer(codexChat("not_logged_in"));
  main = await open("#/chat");
  assert.strictEqual(notes(main).length, 1, "its chat login is not done yet");
  assert(text(notes(main)[0]).includes("Codex"), "and the note names Codex as the other way");
  setServer(codexChat("logged_in"));
  main = await open("#/meetings");
  assert.strictEqual(notes(main).length, 1, "meetings are still Claude Code only");
});

test("the note does not turn off the page: forms and buttons keep working as before", async () => {
  setServer(statusOf(row("claude", "not_installed")));
  const main = await open("#/chat");
  assert.strictEqual(notes(main).length, 1);
  assert(byAttr(main, "data-chat", "open").length === 1, "the chat form is still there");
});

test("a quick answer from a page the person already left does not draw into the next page", async () => {
  setServer(statusOf(row("claude", "not_installed")));
  await open("#/meetings");
  const main = await open("#/settings");
  assert.strictEqual(notes(main).length, 0);
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, plain words only", () => {
  assert(BLOCK.length > 200, "the block is marked in app.js");
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(BLOCK));
  assert(!/\bCLI\b|argv|PATH/.test(BLOCK));
  assert(!/api\/setup\/tools\/|localStorage|\.claude|\.codex/.test(BLOCK), "reads the start-up status only; nothing else");
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
