// P51-2 (v0.24.0 極簡對話 2, ADR 0016): the small button at the left of the box that says whom you are talking to, and changes it. It lists the employees from data the
// page already has (the home page's read of the employees and GET /api/chats; the chat page's one read when it was opened), so opening it asks for nothing. Those who can chat
// are the options (the one you talk to is marked); those who cannot are below, grey, each with one sentence why, and a press goes to the page that prepares them (it selects
// nothing). On the home page a pick only changes who the send button sends to (the same openChatWith as for the CEO); on a chat page a pick goes to that employee's page and
// takes the words not yet sent along; choosing sends nothing and writes nothing (guard 18b is on the source in tests/test_autonomy_guard.py, here it is on the page).
// The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model.
// Run: node tests/frontend/p51_who.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
global.document.querySelector = () => null;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const attr = (n, k, v) => n.find((x) => x.getAttribute && x.getAttribute(k) === v);
const attrs = (n, k, v) => n.findAll((x) => x.getAttribute && x.getAttribute(k) === v);
const q = (n, key) => attr(n, "data-chat", key);
const who = (n) => attr(n, "data-ask", "who");
const options = (n) => attrs(n, "data-ask", "who-option");
const pop = (n) => { const l = attr(n, "role", "listbox"); return l ? l.parentNode : null; };
const laters = (n) => attrs(n, "data-ask", "who-later");
const CID = "c-0123456789abcdef";
const CID2 = "c-2222222222222222";

// ---- fixtures ------------------------------------------------------------------------------------------------------
const cardsList = () => [
  { id: "emp-1", name: "虛構總管", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true },
  { id: "emp-2", name: "虛構會計", position: "executor", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
  { id: "emp-3", name: "虛構寫手", position: "executor", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
  { id: "emp-4", name: "停用員工", position: "pm", tool: "claude", engine: "claude-chat", enabled: false, can_chat: false, code: "card_disabled", reason: "這張角色卡已停用，啟用之後才能聊天。", instructions: false },
  { id: "emp-5", name: "虛構審查", position: "reviewer", tool: "agy", engine: "agy-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false },
];
const support = () => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" }, verify: { running: false }, money: "x",
  codex: { engine: "codex-chat", state: "ready", installed: true, version: "0.163.0", verified: true, logged_in: true, admin_policy_ok: true, why: "", verify: { running: false }, money: "x" },
  agy: { engine: "agy-chat", state: "unverified", installed: true, version: "1.2.3", verified: false, admin_policy_ok: true, why: "", verify: { running: false }, money: "x" } });
const chatRow = (id, profileId, over = {}) => ({ id, profile_id: profileId, engine: "claude-chat", created_at: 1000, last_at: 2000, last_kind: "reply", last_text: "好", turns: 1, spent_usd: "0.01", open: false, waiting: false, problem: null, ...over });
const listing = (over = {}) => ({ ok: true, chats: [chatRow(CID, "emp-1", { last_at: 3000 }), chatRow(CID2, "emp-2", { last_at: 2500 })], more: 0, cards: cardsList(), support: support(),
  limits: { per_turn_usd: "0.5", daily_usd: "3" }, ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const live = (over = {}) => ({ state: "idle", turn: null, partial: "", partial_truncated: false, model: "haiku", cards: [], ...over });
const detail = (over = {}) => ({ ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" }, card: cardsList()[0],
  records: [], live: live(), runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing(), detail: detail(), listFails: false, ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/routines") return jsonResponse({ routines: [], readable: true });
    if (p === "/api/chats" && method === "GET") return page.listFails ? jsonResponse({ error: "壞了" }, false, 500) : jsonResponse(page.list);
    if (p === "/api/chats" && method === "POST") return jsonResponse({ ok: true, chat: { id: "c-3333333333333333", profile_id: JSON.parse(opts.body).profile_id, created_at: 1 } }, true, 201);
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return { ok: false, status: 503, headers: { get: () => "" }, json: async () => ({}) };
    if (m && !m[2] && method === "GET") return jsonResponse(m[1] === CID2 ? detail({ chat: { id: CID2, profile_id: "emp-2", created_at: 1, engine: "claude-chat" }, card: cardsList()[1] }) : page.detail);
    if (m && m[2] === "messages") return jsonResponse({ ok: true, turn: 1, cap_usd: "0.5", process: "new" }, true, 202);
    return null;
  });
  FETCH_LOG.length = 0;
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const writes = () => FETCH_LOG.filter((c) => c.method !== "GET");

// ---- the chat page ---------------------------------------------------------------------------------------------------

test("the chat page has the small button at the left of the box with the name of the one you talk to; the list is closed and opening it asks for nothing", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const b = who(main);
  assert(b && b.tag === "button", "the button");
  const box = main.find((n) => n.hasClass && n.hasClass("home-box"));
  const bar = box.find((n) => n.hasClass && n.hasClass("home-box-bar"));
  assert(bar.contains(b), "in the bar of the box");
  assert(text(b).includes("虛構總管"), text(b));
  assert.strictEqual(b.getAttribute("aria-haspopup"), "listbox");
  assert.strictEqual(b.getAttribute("aria-expanded"), "false");
  assert(/虛構總管/.test(b.getAttribute("aria-label")), "a screen reader is told whom the words go to");
  const list = pop(main);
  assert(list && list.hidden === true, "closed");
  const before = FETCH_LOG.length;
  b.click();
  assert.strictEqual(b.getAttribute("aria-expanded"), "true");
  assert.strictEqual(list.hidden, false);
  assert.strictEqual(FETCH_LOG.length, before, "opening the list asked for nothing");
});

test("the list: the employees who can chat are options (the one you talk to is selected), the others are below, grey, each with why and a link to the page that prepares them", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  who(main).click();
  const opts = options(main);
  assert.deepStrictEqual(opts.map((o) => o.getAttribute("data-profile-id")), ["emp-1", "emp-2", "emp-3"], "server order, ready ones only");
  assert(opts.every((o) => o.getAttribute("role") === "option"));
  assert.deepStrictEqual(opts.map((o) => o.getAttribute("aria-selected")), ["true", "false", "false"]);
  assert(text(opts[0]).includes("虛構總管") && text(opts[0]).includes("CEO") && text(opts[0]).includes("Claude Code"), text(opts[0]));
  assert(text(opts[2]).includes("Codex"));
  const later = laters(main);
  assert.deepStrictEqual(later.map((o) => o.getAttribute("data-profile-id")), ["emp-4", "emp-5"]);
  for (const l of later) { assert.strictEqual(l.tag, "a"); assert.strictEqual(l.getAttribute("href"), "#/chat?profile=" + l.getAttribute("data-profile-id")); assert(l.hasClass("who-later")); }
  assert(text(later[0]).includes("這張角色卡已停用，啟用之後才能聊天。"), "the reason in plain words: " + text(later[0]));
  assert(text(later[1]).includes("AGY") && text(later[1]).includes("虛構審查"), text(later[1]));
  assert(!later.some((l) => l.getAttribute("role") === "option"), "not an option: a press goes to the preparation page, it selects nothing");
  assert(pop(main).hasClass("who-pop"), "the list is in its pop-up");
});

test("keyboard: the list takes the focus when it opens, the arrows move between the entries, Esc closes it and gives the focus back to the button, Tab closes it", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const b = who(main);
  b.click();
  const entries = [...options(main), ...laters(main)];
  assert.strictEqual(global.document.activeElement, entries[0], "the first (the one you talk to) has the focus");
  const list = pop(main);
  list.dispatch("keydown", { key: "ArrowDown" });
  assert.strictEqual(global.document.activeElement, entries[1]);
  list.dispatch("keydown", { key: "End" });
  assert.strictEqual(global.document.activeElement, entries[entries.length - 1]);
  list.dispatch("keydown", { key: "ArrowDown" });
  assert.strictEqual(global.document.activeElement, entries[0], "it wraps");
  list.dispatch("keydown", { key: "Escape" });
  assert.strictEqual(pop(main).hidden, true);
  assert.strictEqual(b.getAttribute("aria-expanded"), "false");
  assert.strictEqual(global.document.activeElement, b);
  b.click();
  list.dispatch("keydown", { key: "Tab" });
  assert.strictEqual(pop(main).hidden, true);
});

test("a pick on the chat page goes to that employee's last chat and takes the unsent words; it sends nothing and writes nothing", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  q(main, "input").value = "請幫我記帳";
  who(main).click();
  FETCH_LOG.length = 0;
  options(main)[1].click();
  assert.strictEqual(global.location.hash, "#/chat/" + CID2);
  assert.strictEqual(app.ceoDrafts.get(CID2), "請幫我記帳", "the words wait for that chat's box");
  assert.deepStrictEqual(FETCH_LOG.map((c) => c.method + " " + c.url), [], "choosing asked for nothing at all");
  const next = await open("#/chat/" + CID2);
  assert.strictEqual(q(next, "input").value, "請幫我記帳", "in the box of the other employee's page");
  assert.deepStrictEqual(writes(), [], "and still nothing was sent");
  assert(text(who(next)).includes("虛構會計"), "the button says who you talk to now");
});

test("an employee with no chat yet: the pick goes to the page that opens it (nothing is created by the pick); the words wait under that employee", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  q(main, "input").value = "寫一篇貼文";
  who(main).click();
  FETCH_LOG.length = 0;
  options(main)[2].click();
  assert.strictEqual(global.location.hash, "#/chat?profile=emp-3");
  assert.strictEqual(app.ceoDrafts.get("emp-3"), "寫一篇貼文");
  assert.deepStrictEqual(FETCH_LOG.map((c) => c.method + " " + c.url), []);
  app.ceoDrafts.delete("emp-3");
});

test("with no words in the box a pick keeps nothing; picking the one you already talk to only closes the list", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  who(main).click();
  FETCH_LOG.length = 0;
  const hash = global.location.hash;
  options(main)[0].click();
  assert.strictEqual(global.location.hash, hash, "nowhere to go");
  assert.strictEqual(pop(main).hidden, true);
  who(main).click();
  options(main)[1].click();
  assert.strictEqual(app.ceoDrafts.has(CID2), false, "no empty words kept");
  assert.deepStrictEqual(FETCH_LOG, []);
});

test("an employee who cannot chat yet: the entry is a link to the preparation page; a press keeps the words for them and selects nothing", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  q(main, "input").value = "稍後再說的話";
  who(main).click();
  FETCH_LOG.length = 0;
  const l = laters(main)[0];
  const hash = global.location.hash;
  l.click();
  assert.strictEqual(app.ceoDrafts.get("emp-4"), "稍後再說的話");
  assert.strictEqual(global.location.hash, hash, "the link's own navigation does it; the handler picks nobody");
  assert(text(who(main)).includes("虛構總管"), "still talking to the same one");
  assert.deepStrictEqual(FETCH_LOG, []);
  app.ceoDrafts.delete("emp-4");
});

test("no list, no button: when the page could not read the employees, and on a chat a routine opened or a group's", async () => {
  setPage({ listFails: true });
  const failed = await open("#/chat/" + CID);
  assert(q(failed, "input"), "the page itself still works");
  assert.strictEqual(who(failed), null, "no data, no button");
  setPage({ detail: detail({ routine_title: "每天早上的摘要" }) });
  const routine = await open("#/chat/" + CID);
  assert.strictEqual(who(routine), null, "a routine's chat");
  setPage({ detail: detail({ group: { id: "g-0123456789ab", name: "虛構群組" } }) });
  const group = await open("#/chat/" + CID);
  assert.strictEqual(who(group), null, "a group's chat has no box and no button");
});

test("the list is only drawn from cards of the page's read: with no card in the answer there is no button", async () => {
  setPage({ list: listing({ cards: [] }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(who(main), null);
});

// ---- the box (shared with the home page) -------------------------------------------------------------------------------

test("the box of the chat page is the home box: the text above, the send button at the right with stop beside it, the small buttons at the left; Cmd/Ctrl+Enter sends and a plain Enter does not", async () => {
  setPage({ detail: detail({ live: live({ state: "working", turn: 1 }) }) });
  const main = await open("#/chat/" + CID);
  const box = main.find((n) => n.hasClass && n.hasClass("home-box"));
  assert(box && box.hasClass("chat-box"), "the same class as the home page's box");
  assert(box.contains(q(main, "input")) && box.contains(q(main, "send")) && box.contains(q(main, "stop")));
  assert(q(main, "send").hasClass("home-send"), "the same send button style");
  const bar = box.find((n) => n.hasClass && n.hasClass("home-box-bar"));
  const left = bar.find((n) => n.hasClass && n.hasClass("chat-box-left"));
  const right = bar.find((n) => n.hasClass && n.hasClass("chat-box-right"));
  assert(left.contains(who(main)) && left.contains(attr(main, "data-skill", "use")), "who and 「用常用做法」 at the left");
  assert(right.contains(q(main, "stop")) && right.contains(q(main, "send")) && right.children.indexOf(q(main, "stop")) < right.children.indexOf(q(main, "send")), "stop is beside send");
  assert(bar.children.indexOf(left) < bar.children.indexOf(right));
  const input = q(main, "input");
  assert.strictEqual(input.getAttribute("rows"), "2");
  input.value = "你好";
  const sent = (e) => { FETCH_LOG.length = 0; input.dispatch("keydown", e); return FETCH_LOG.filter((c) => c.method === "POST").length; };
  assert.strictEqual(sent({ key: "Enter" }), 0);
  assert.strictEqual(sent({ key: "Enter", shiftKey: true }), 0);
  assert.strictEqual(sent({ key: "a", metaKey: true }), 0);
  assert.strictEqual(sent({ key: "Enter", isComposing: true, metaKey: true }), 0, "an IME's Enter");
  assert.strictEqual(FETCH_LOG.length, 0);
  assert.strictEqual(sent({ key: "Enter", ctrlKey: true }), 1, "Ctrl+Enter sends once");
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
  const part = css.slice(css.indexOf("/* P51-2"));
  assert(css.indexOf("/* P51-2") > css.indexOf("/* P50-3"), "the css of the shared box is only added at the end of the file");
  assert(/\.chat-composer \.home-box textarea\s*\{/.test(part) && /\.chat-box-bar\b/.test(part) && /\.chat-box-right\b/.test(part));
});

test("the two opening choices of a CEO's chat are the home page's small pills, and still only put words in the box", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const choices = attrs(main, "data-chat", "opening-choice");
  assert.strictEqual(choices.length, 2);
  for (const c of choices) assert(c.hasClass("home-example") && !c.hasClass("btn"), "the home page's example pill");
  FETCH_LOG.length = 0;
  choices[1].click();
  assert.strictEqual(q(main, "input").value, "我想做的事是：");
  assert.strictEqual(FETCH_LOG.length, 0);
  assert.strictEqual(global.document.activeElement, q(main, "input"));
});

// ---- the home page -----------------------------------------------------------------------------------------------------

const profile = (id, name, position) => ({ id, name, position, model: { tool: "claude", model_id: "" }, enabled: true, launch_mode: "safe" });
const homeState = (over = {}) => ({ profiles: [profile("emp-1", "虛構總管", "planner"), profile("emp-2", "虛構會計", "executor")], conf: {}, chats: listing(), lamp: "green", ...over });
const homeInput = (n) => attr(n, "data-home", "ask-input");
const homeSend = (n) => attr(n, "data-home", "ask-send");

test("home: the button says the CEO by default; opening the list asks for nothing; a pick changes who the box is for and nothing else (no request, nothing sent)", () => {
  setPage();
  const ask = app.homeAsk(homeState());
  const b = who(ask);
  assert(b && text(b).includes("虛構總管"));
  const input = homeInput(ask);
  assert.strictEqual(input.getAttribute("aria-label"), "要對 CEO 說的話");
  b.click();
  assert.deepStrictEqual(options(ask).map((o) => o.getAttribute("data-profile-id")), ["emp-1", "emp-2", "emp-3"]);
  input.value = "整理發票";
  FETCH_LOG.length = 0;
  options(ask)[1].click();
  assert.deepStrictEqual(FETCH_LOG, [], "a pick makes no request");
  assert(text(who(ask)).includes("虛構會計"));
  assert.strictEqual(input.getAttribute("aria-label"), "要對 虛構會計 說的話");
  assert(/虛構會計/.test(input.getAttribute("placeholder")) && !/CEO/.test(input.getAttribute("placeholder")));
  assert.strictEqual(input.value, "整理發票", "the words are kept");
  assert.strictEqual(attrs(ask, "data-ask", "who-option").find((o) => o.getAttribute("aria-selected") === "true").getAttribute("data-profile-id"), "emp-2");
  assert.strictEqual(pop(ask).hidden, true, "the list closes");
});

test("home: after a pick the send button sends to that employee by the same road as for the CEO (a chat is opened if there is none, then the one message); a reload goes back to the CEO", async () => {
  setPage({ list: listing({ chats: [chatRow(CID, "emp-1")] }) });
  const ask = app.homeAsk(homeState({ chats: listing({ chats: [chatRow(CID, "emp-1")] }) }));
  who(ask).click();
  options(ask)[1].click();
  homeInput(ask).value = "整理發票";
  FETCH_LOG.length = 0;
  homeSend(ask).click();
  await settle(60);
  const posts = FETCH_LOG.filter((c) => c.method === "POST");
  assert.deepStrictEqual(posts.map((c) => c.method + " " + c.url.split("?")[0]), ["POST /api/chats", "POST /api/chats/c-3333333333333333/messages"]);
  assert.deepStrictEqual(posts[0].body, { profile_id: "emp-2" });
  assert.deepStrictEqual(posts[1].body, { text: "整理發票" });
  assert.strictEqual(global.location.hash, "#/chat/c-3333333333333333");
  const fresh = app.homeAsk(homeState());
  assert(text(who(fresh)).includes("虛構總管"), "a new page starts with the CEO again");
});

test("home: the sentence under the box follows the employee; the CEO's own wording stays for the CEO", () => {
  setPage();
  const ask = app.homeAsk(homeState());
  assert(text(ask).includes("CEO 要動手前都會先問你。"));
  who(ask).click();
  options(ask)[1].click();
  assert(text(ask).includes("虛構會計 要動手前都會先問你。") && !text(ask).includes("CEO 要動手前都會先問你。"), text(ask));
  who(ask).click();
  options(ask)[0].click();
  assert(text(ask).includes("CEO 要動手前都會先問你。"));
});

test("home: one who cannot chat is a link to the preparation page; with no cards read there is no button; a CEO who cannot chat still gets the old single reason", () => {
  setPage();
  const ask = app.homeAsk(homeState());
  who(ask).click();
  assert.deepStrictEqual(laters(ask).map((l) => l.getAttribute("href")), ["#/chat?profile=emp-4", "#/chat?profile=emp-5"]);
  const none = app.homeAsk(homeState({ chats: { ...listing(), cards: undefined } }));
  assert.strictEqual(who(none), null, "no data, no button");
  const stuck = app.homeAsk(homeState({ chats: listing({ cards: cardsList().map((c) => (c.id === "emp-1" ? { ...c, can_chat: false, reason: "這張角色卡已停用，啟用之後才能聊天。" } : c)) }) }));
  assert(attr(stuck, "data-home", "ask-prepare") && !who(stuck));
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
