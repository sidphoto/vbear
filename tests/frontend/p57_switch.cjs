// P57 (v0.25.1, ADR 0019): an employee whose AI tool cannot chat and which the person cannot fix by themselves (the administrator's policy, or a version VBear does not know)
// gets a way out in the place that says why: a button to let the employee use another AI. The first press only opens a confirmation (who, where the words go, what happens to the
// old chats, which model); only 「確認」 writes, with the ordinary employee write (POST /api/agent-profiles/<id>) and a body that is only `model`.
//
// Guard 21a: the write is sent only from the handler of the confirm button (nothing else in the switch code requests anything; the first press, 「先不要」, a redraw and the 5-second
//            refresh send nothing).
// Guard 21b: the body of that write is only `{ model: { tool, model_id: "" } }` for one of the other tools offered; no other field (name, mode, instructions, skills) is sent.
// Guard 21c: the confirmation always says where the words go from now on (「之後跟他說的話會送到 …」), outside any fold, in the same area as the confirm button.
// Each rule has made-up broken sources/runs that the judges below must catch (see the last tests).
// The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model.
// Run: node tests/frontend/p57_switch.cjs   (exit code 0 = pass)
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
const attr = (n, k, v) => n.find((x) => x.getAttribute && x.getAttribute(k) === v);
const attrs = (n, k, v) => n.findAll((x) => x.getAttribute && x.getAttribute(k) === v);
const sw = (n, key) => attr(n, "data-switch", key);
const sws = (n, key) => attrs(n, "data-switch", key);
const q = (n, key) => attr(n, "data-chat", key);
const writes = () => FETCH_LOG.filter((c) => c.method !== "GET");
const profileWrites = () => FETCH_LOG.filter((c) => c.method === "POST" && /^\/api\/agent-profiles\//.test(c.url.split("?")[0]));

// ---- fixtures ------------------------------------------------------------------------------------------------------
const support = (over = {}) => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" }, verify: { running: false }, money: "x", ...over });
const codexSupport = (over = {}) => ({ engine: "codex-chat", state: "ready", installed: true, version: "0.163.0", verified: true, logged_in: true, admin_policy_ok: true, why: "", verify: { running: false }, money: "x", ...over });
const agySupport = (over = {}) => ({ engine: "agy-chat", state: "ready", installed: true, version: "1.2.3", verified: true, admin_policy_ok: true, why: "", verify: { running: false }, money: "x", ...over });
const POLICY = "這台 Mac 上有管理員政策或系統設定，可能蓋過 VBear 的設定，所以不啟動聊天（虛構來源）。";
const claudeHeld = (over = {}) => ({ state: "policy", message: POLICY, ...over });
const cardOf = (tool, over = {}) => ({ id: "emp-1", name: "虛構總管", position: "planner", tool, engine: tool + "-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true, ...over });
const listing = (cardTool, sup, over = {}) => ({ ok: true, chats: [], more: 0, cards: [cardOf(cardTool)], support: sup, limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["chats"] }, ledger_error: null, problems: [], scratch: "", ...over });
const supOf = (over = {}, extra = {}) => support({ codex: codexSupport(), agy: agySupport(), ...over, ...extra });

let page;
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { list: listing("claude", supOf(claudeHeld())), writeFails: null, writeThrows: false, after: null, ...over };
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
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/chats" && method === "POST") return jsonResponse({ ok: true, chat: { id: "c-3333333333333333", profile_id: JSON.parse(opts.body).profile_id, created_at: 1 } }, true, 201);
    if (method === "POST" && p === "/api/agent-profiles/emp-1") {
      if (page.writeThrows) throw new TypeError("Failed to fetch");
      if (page.writeFails) return jsonResponse({ ok: false, error: page.writeFails }, false, 400);
      const body = JSON.parse(opts.body);
      if (page.after) page.after(body);
      return jsonResponse({ ok: true, profile: { id: "emp-1", model: body.model } });
    }
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "messages") return jsonResponse({ ok: true, turn: 1, cap_usd: "0.5", process: "new" }, true, 202);
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
const main = () => h.dom().mainEl;
// the server's answer after the write: the card now has the tool
const becomes = (tool, sup) => (body) => { page.list = listing(body.model.tool, sup); };

// =====================================================================================================================
// chatPrepState: who can the employee switch to
// =====================================================================================================================
const cardFor = (tool, over) => cardOf(tool, over);
const prepOf = (tool, sup) => app.chatPrepState(cardFor(tool), { support: sup });

test("policy on Claude Code: the other two that can chat or can be made ready are offered, the ones that can chat first; the reason says the next step; the link to the tools page stays", () => {
  const st = prepOf("claude", supOf(claudeHeld()));
  const st2 = prepOf("claude", support({ ...claudeHeld(), codex: codexSupport({ state: "unverified", verified: false }), agy: agySupport() }));
  assert.strictEqual(st.kind, "link");
  assert.strictEqual(st.href, "#/setup");
  assert.strictEqual(st.label, "到 AI 工具看看");
  assert.deepStrictEqual(st.switch.map((o) => [o.tool, o.kind, o.ready]), [["codex", "ready", true], ["agy", "ready", true]], "both ready here (supOf default)");
  assert.deepStrictEqual(st2.switch.map((o) => [o.tool, o.kind, o.ready]), [["agy", "ready", true], ["codex", "unverified", false]], "the one that can chat now goes first");
  assert(st.reason.startsWith("這台電腦的 Claude Code 有管理員設定，VBear 不能用它聊天。"), st.reason);
  assert(st.reason.includes("這不是你能改的；可以讓 虛構總管 改用別家 AI。"), st.reason);
  const [codex] = st.switch;
  assert.strictEqual(codex.label, "OpenAI ChatGPT（Codex）");
  assert.strictEqual(codex.name, "Codex");
  assert.strictEqual(codex.company, "OpenAI");
  assert.strictEqual(codex.word, "可以聊天了");
  assert.strictEqual(st.switch[1].company, "Google");
});

test("the state of each other tool is said as it is: ready, safety check needed, check running, Codex chat login needed; installed-but-blocked and unknown ones are not offered; not installed is listed apart", () => {
  const cases = [
    ["codex ready", { codex: codexSupport() }, "codex", "ready", "可以聊天了"],
    ["codex unverified", { codex: codexSupport({ state: "unverified", verified: false }) }, "codex", "unverified", "第一次聊天前要做一次安全檢查"],
    ["codex running", { codex: codexSupport({ state: "unverified", verified: false, verify: { running: true } }) }, "codex", "running", "安全檢查還在做"],
    ["codex not logged in", { codex: codexSupport({ state: "not_logged_in", logged_in: false }) }, "codex", "login", "還要先登入聊天用的 Codex"],
    ["agy unverified", { agy: agySupport({ state: "unverified", verified: false }) }, "agy", "unverified", "第一次聊天前要做一次安全檢查"],
  ];
  for (const [name, over, tool, kind, word] of cases) {
    const st = prepOf("claude", support({ ...claudeHeld(), codex: codexSupport({ state: "policy" }), agy: agySupport({ state: "unsupported" }), ...over }));
    const hit = st.switch.find((o) => o.tool === tool);
    assert(hit, name);
    assert.strictEqual(hit.kind, kind, name);
    assert.strictEqual(hit.word, word, name);
    assert.strictEqual(st.switch.length, 1, name + ": the other one is blocked and is not offered");
  }
  for (const bad of [{ state: "policy" }, { state: "unsupported" }, { state: "folder" }, { state: "version_unreadable" }, { state: "hooks" }, { state: "weird" }]) {
    const st = prepOf("claude", support({ ...claudeHeld(), codex: codexSupport(bad), agy: agySupport(bad) }));
    assert.deepStrictEqual(st.switch, [], JSON.stringify(bad));
  }
  const gone = prepOf("claude", support({ ...claudeHeld(), codex: codexSupport({ state: "not_installed", installed: false }), agy: agySupport() }));
  assert.deepStrictEqual(gone.switch.map((o) => o.tool), ["agy"]);
  assert.deepStrictEqual(gone.switchMissing.map((o) => o.tool), ["codex"], "listed apart, not a choice");
  assert(!gone.switch.some((o) => o.tool === "codex"));
});

test("nothing to switch to: the old sentence and the old link, word for word, and no switch parts", () => {
  const st = prepOf("claude", support({ ...claudeHeld(), codex: codexSupport({ state: "not_installed", installed: false }), agy: agySupport({ state: "policy" }) }));
  assert.strictEqual(st.kind, "link");
  assert.strictEqual(st.reason, "這台電腦的 Claude Code 有管理員設定，VBear 不能用它聊天。可以到「AI 工具」看看有沒有別的工具能用。");
  assert.deepStrictEqual(st.switch, []);
  assert.strictEqual(st.label, "到 AI 工具看看");
  const none = app.chatPrepState(cardFor("claude"), { support: undefined });
  assert.strictEqual(none.kind, "retry");
  assert(!none.switch || none.switch.length === 0);
});

test("a version VBear does not know: the sentence is unchanged, the other tools are offered with their own lead line", () => {
  const st = prepOf("claude", supOf({ state: "unsupported", detected: "2.1.999", message: "虛構的伺服器句子" }));
  assert.strictEqual(st.kind, "link");
  assert(st.reason.includes("你的 Claude Code 是 2.1.999 版，VBear 還不認得這一版") && st.reason.endsWith("等 VBear 出新版就能用。"), st.reason);
  assert.strictEqual(st.raw, "虛構的伺服器句子");
  assert.deepStrictEqual(st.switch.map((o) => o.tool), ["codex", "agy"]);
  assert.strictEqual(st.switchLead, "現在要聊的話，可以讓 虛構總管 先改用別家 AI：");
  const codexHeld = app.chatPrepState(cardFor("codex"), { support: supOf({ state: "verified" }, { codex: codexSupport({ state: "policy" }) }) });
  assert.deepStrictEqual(app.chatPrepState(cardFor("codex"), { support: support({ codex: codexSupport({ state: "policy" }), agy: agySupport({ state: "unverified", verified: false }) }) }).switch.map((o) => [o.tool, o.kind]), [["claude", "ready"], ["agy", "unverified"]]);
  assert(codexHeld.reason.includes("這台電腦的 Codex 有管理員設定"));
  const agyOld = app.chatPrepState(cardFor("agy"), { support: support({ codex: codexSupport(), agy: agySupport({ state: "unsupported", version: "9.9.9", why: "x" }) }) });
  assert.deepStrictEqual(agyOld.switch.map((o) => o.tool), ["claude", "codex"], "never the tool it already has");
});

test("states that the person can fix or wait out by themselves are not given a switch: unverified, running, not logged in, ready, a read that failed", () => {
  for (const sup of [supOf({ state: "unverified" }), supOf({ state: "unverified", verify: { running: true } }), supOf({ state: "verified" })]) {
    const st = prepOf("claude", sup);
    assert(!st.switch || st.switch.length === 0, st.kind);
  }
  const codex = app.chatPrepState(cardFor("codex"), { support: supOf({}, { codex: codexSupport({ state: "not_logged_in" }) }) });
  assert(!codex.switch || codex.switch.length === 0);
  assert(!app.chatPrepState({ ...cardFor("claude"), can_chat: false, reason: "停用" }, { support: supOf(claudeHeld()) }).switch, "a card that cannot chat has its own page");
});

// =====================================================================================================================
// the page that prepares a chat
// =====================================================================================================================
test("prep page, policy: the options are listed with the state of each, the link to the tools page stays (no longer the main button), and opening the page sends nothing", async () => {
  setPage({ list: listing("claude", supOf(claudeHeld(), { agy: agySupport({ state: "unverified", verified: false }) })) });
  const m = await open("#/chat?profile=emp-1");
  const picks = sws(m, "pick");
  assert.deepStrictEqual(picks.map((b) => b.getAttribute("data-switch-tool")), ["codex", "agy"]);
  assert(picks.every((b) => b.tag === "button"));
  assert.strictEqual(text(picks[0]), "改用 OpenAI ChatGPT（Codex）");
  assert.strictEqual(text(picks[1]), "改用 Google Gemini（AGY）");
  const states = sws(m, "state").map(text);
  assert.deepStrictEqual(states, ["可以聊天了", "第一次聊天前要做一次安全檢查"]);
  assert(text(q(m, "prep-reason")).includes("可以讓 虛構總管 改用別家 AI"), text(q(m, "prep-reason")));
  const link = q(m, "prep-action");
  assert(link && link.tag === "a" && link.getAttribute("href") === "#/setup" && text(link) === "到 AI 工具看看");
  assert(!link.hasClass("primary"), "the way out is the main thing now");
  assert(picks[0].hasClass("primary") && !picks[1].hasClass("primary"), "only the one that can chat now is the main button");
  assert.strictEqual(sw(m, "confirm"), null, "closed");
  assert.deepStrictEqual(writes(), [], "opening the page sends nothing");
});

test("prep page: the first press only opens the confirmation (who, where the words go, the old chats, the model), and sends nothing", async () => {
  setPage();
  const m = await open("#/chat?profile=emp-1");
  FETCH_LOG.length = 0;
  sws(m, "pick")[0].click();
  const c = sw(main(), "confirm");
  assert(c, "the confirmation is open");
  const t = text(c);
  assert(t.includes("虛構總管 之後會改用 OpenAI ChatGPT（Codex） 聊天。"), t);
  assert(t.includes("之後跟他說的話會送到 OpenAI"), t);
  assert(t.includes("原本設定的是 Anthropic"), t);
  assert(t.includes("之前用 Claude Code 聊的對話會留著，可以看，但不能接著聊；要聊請開新對話。"), t);
  assert(t.includes("模型：用 Codex 自己的預設"), t);
  assert(t.includes("名字、說明、技能和其他設定都照舊"), t);
  assert.strictEqual(text(sw(c, "confirm-go")), "確認，改用 Codex");
  assert.strictEqual(text(sw(c, "confirm-cancel")), "先不要");
  assert(!c.find((n) => n.tag === "details"), "nothing of it is folded");
  assert.deepStrictEqual(FETCH_LOG, [], "the first press asked for nothing and wrote nothing");
  assert.strictEqual(global.document.activeElement, c, "the focus is on the confirmation (not on the confirm button)");
});

test("prep page: 「先不要」 closes it and sends nothing; the focus goes back to the button that was pressed", async () => {
  setPage();
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[0].click();
  FETCH_LOG.length = 0;
  sw(sw(main(), "confirm"), "confirm-cancel").click();
  assert.strictEqual(sw(main(), "confirm"), null);
  assert.deepStrictEqual(FETCH_LOG, []);
  assert.strictEqual(global.document.activeElement, sws(main(), "pick")[0]);
});

test("prep page: the 5-second refresh and a redraw do not send anything and do not close an open confirmation", async () => {
  setPage();
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[1].click();
  FETCH_LOG.length = 0;
  await page.tick();
  await settle();
  await page.tick();
  await settle();
  assert(sw(main(), "confirm"), "still open");
  assert(text(sw(main(), "confirm")).includes("Google Gemini（AGY）"), "and still for the same one");
  assert.deepStrictEqual(writes(), []);
  assert(FETCH_LOG.some((c) => c.url.startsWith("/api/chats") && c.method === "GET"), "the refresh did read");
  const enter = sw(main(), "confirm");
  enter.dispatch("keydown", { key: "Enter" });
  await settle();
  assert.deepStrictEqual(writes(), [], "Enter on the area sends nothing");
});

test("prep page: 「確認」 sends exactly one POST with only `model`, then reads again and the page shows the new tool's own state; no check, no chat, no message is started", async () => {
  setPage({ after: null });
  page.after = becomes("codex", supOf(claudeHeld()));
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[0].click();
  FETCH_LOG.length = 0;
  sw(sw(main(), "confirm"), "confirm-go").click();
  await settle(80);
  assert.deepStrictEqual(profileWrites().map((c) => [c.method, c.url, c.body]), [["POST", "/api/agent-profiles/emp-1", { model: { tool: "codex", model_id: "" } }]]);
  assert.strictEqual(writes().length, 1, "that is the only write");
  assert(FETCH_LOG.some((c) => c.method === "GET" && c.url.startsWith("/api/chats")), "read again");
  assert.strictEqual(sw(main(), "confirm"), null);
  assert.strictEqual(sws(main(), "pick").length, 0, "the employee uses Codex now: nothing to switch");
  const act = q(main(), "prep-action");
  assert(act && text(act) === "開始聊天", "Codex can chat: the page offers to start, the person presses it");
  assert.strictEqual(writes().length, 1, "and nothing was started by itself");
});

test("prep page: after the switch to a tool that still needs the safety check, the page shows the existing check button and starts nothing", async () => {
  setPage();
  page.after = becomes("agy", supOf(claudeHeld(), { agy: agySupport({ state: "unverified", verified: false }) }));
  page.list = listing("claude", supOf(claudeHeld(), { agy: agySupport({ state: "unverified", verified: false }) }));
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[1].click();
  assert(text(sw(main(), "confirm")).includes("之後跟他說的話會送到 Google"), "Google, not OpenAI");
  assert(text(sw(main(), "confirm")).includes("AGY 員工會用到你自己裝的 AGY 技能"), "the AGY skills sentence");
  FETCH_LOG.length = 0;
  sw(sw(main(), "confirm"), "confirm-go").click();
  await settle(80);
  assert.deepStrictEqual(profileWrites().map((c) => c.body), [{ model: { tool: "agy", model_id: "" } }]);
  const act = q(main(), "prep-action");
  assert.strictEqual(text(act), "驗證聊天");
  assert(!FETCH_LOG.some((c) => c.url.includes("/chat-support/verify")), "the check is the person's own press");
  assert.strictEqual(writes().length, 1);
});

test("prep page: pressing 「確認」 twice quickly writes once", async () => {
  setPage();
  page.after = becomes("codex", supOf(claudeHeld()));
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[0].click();
  const go = sw(sw(main(), "confirm"), "confirm-go");
  FETCH_LOG.length = 0;
  go.click(); go.click();
  await settle(80);
  assert.strictEqual(profileWrites().length, 1);
});

test("prep page: the server refuses -> the reason in plain words, the employee stays as he was (nothing re-read as changed), the confirmation stays open and can be tried again or closed", async () => {
  setPage({ writeFails: "AI 工具 codex 目前被隱藏，不能選用。" });
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[0].click();
  FETCH_LOG.length = 0;
  sw(sw(main(), "confirm"), "confirm-go").click();
  await settle(80);
  const err = sw(main(), "error");
  assert(err, "an error is shown");
  assert(text(err).includes("AI 工具 codex 目前被隱藏，不能選用。"), text(err));
  assert(text(err).includes("沒有改成") && text(err).includes("Claude Code"), text(err));
  assert.strictEqual(profileWrites().length, 1);
  assert(sw(main(), "confirm"), "still open");
  assert.strictEqual(sw(sw(main(), "confirm"), "confirm-go").disabled, false, "can be pressed again");
  sw(sw(main(), "confirm"), "confirm-cancel").click();
  assert.strictEqual(sw(main(), "confirm"), null);
  assert.strictEqual(sw(main(), "error"), null, "the old error is gone with it");
  assert.strictEqual(profileWrites().length, 1, "closing sent nothing");
});

test("prep page: no answer from the server -> it says it does not know whether the change was made, and to look again; nothing else is sent", async () => {
  setPage({ writeThrows: true });
  const m = await open("#/chat?profile=emp-1");
  sws(m, "pick")[0].click();
  sw(sw(main(), "confirm"), "confirm-go").click();
  await settle(80);
  const err = sw(main(), "error");
  assert(err && text(err).includes("不確定有沒有改成"), text(err));
  assert.strictEqual(profileWrites().length, 1);
});

test("prep page: a version VBear does not know shows the lead line, the options and the server's sentence behind 「技術細節」; and nothing to switch to leaves the old page", async () => {
  setPage({ list: listing("claude", supOf({ state: "unsupported", detected: "2.1.999", message: "虛構的伺服器句子" })) });
  let m = await open("#/chat?profile=emp-1");
  assert(text(sw(m, "lead")).includes("現在要聊的話，可以讓 虛構總管 先改用別家 AI："), text(m));
  assert.strictEqual(sws(m, "pick").length, 2);
  assert(m.find((n) => n.tag === "details" && text(n).includes("虛構的伺服器句子")), "the server's sentence is kept whole");
  assert.deepStrictEqual(writes(), []);
  setPage({ list: listing("claude", support({ ...claudeHeld(), codex: codexSupport({ state: "policy" }), agy: agySupport({ state: "not_installed", installed: false }) })) });
  m = await open("#/chat?profile=emp-1");
  assert.strictEqual(sw(m, "box"), null, "no switch part at all");
  assert.strictEqual(text(q(m, "prep-reason")), "這台電腦的 Claude Code 有管理員設定，VBear 不能用它聊天。可以到「AI 工具」看看有沒有別的工具能用。");
  assert(q(m, "prep-action").hasClass("primary"), "the old page is as it was");
});

test("prep page: a tool that is not installed is one grey line without a button", async () => {
  setPage({ list: listing("claude", support({ ...claudeHeld(), codex: codexSupport(), agy: agySupport({ state: "not_installed", installed: false }) })) });
  const m = await open("#/chat?profile=emp-1");
  assert.deepStrictEqual(sws(m, "pick").map((b) => b.getAttribute("data-switch-tool")), ["codex"]);
  const miss = sws(m, "missing");
  assert.strictEqual(miss.length, 1);
  assert(text(miss[0]).includes("Google Gemini（AGY）") && text(miss[0]).includes("還沒安裝"), text(miss[0]));
  assert.strictEqual(miss[0].find((n) => n.tag === "button"), null);
});

// =====================================================================================================================
// the home page
// =====================================================================================================================
const profile = (id, name, position) => ({ id, name, position, model: { tool: "claude", model_id: "" }, enabled: true, launch_mode: "safe" });
const homeState = (list, over = {}) => ({ profiles: [profile("emp-1", "虛構總管", "planner")], conf: {}, chats: list, lamp: "green", ...over });

test("home, policy: the reason, the options with their states, and the old way (先把聊天準備好) as a plain link; nothing is sent until 「確認」", async () => {
  setPage();
  const ask = app.homeAsk(homeState(listing("claude", supOf(claudeHeld(), { agy: agySupport({ state: "unverified", verified: false }) }))));
  assert(text(ask).includes("虛構總管 現在還不能聊天：這台電腦的 Claude Code 有管理員設定，VBear 不能用它聊天。"), text(ask));
  assert(text(ask).includes("可以讓 虛構總管 改用別家 AI"), text(ask));
  assert.deepStrictEqual(sws(ask, "pick").map((b) => text(b)), ["改用 OpenAI ChatGPT（Codex）", "改用 Google Gemini（AGY）"]);
  const links = ask.findAll((n) => n.tag === "a" && n.getAttribute("href") === "#/chat?profile=emp-1");
  assert.strictEqual(links.length, 1);
  assert(!links[0].hasClass("primary"));
  assert(!attr(ask, "data-home", "ask-input"), "still no box to type in");
  FETCH_LOG.length = 0;
  sws(ask, "pick")[0].click();
  assert(sw(ask, "confirm") && text(sw(ask, "confirm")).includes("之後跟他說的話會送到 OpenAI"));
  assert.deepStrictEqual(FETCH_LOG, []);
  sw(sw(ask, "confirm"), "confirm-cancel").click();
  assert.strictEqual(sw(ask, "confirm"), null);
  assert.deepStrictEqual(FETCH_LOG, []);
});

test("home: 「確認」 writes once with only `model`, then the home page is read again (state.reload); the toast says what changed", async () => {
  setPage();
  let reloaded = 0;
  const ask = app.homeAsk(homeState(listing("claude", supOf(claudeHeld())), { reload: () => { reloaded += 1; } }));
  sws(ask, "pick")[1].click();
  FETCH_LOG.length = 0;
  sw(sw(ask, "confirm"), "confirm-go").click();
  await settle(60);
  assert.deepStrictEqual(profileWrites().map((c) => [c.url, c.body]), [["/api/agent-profiles/emp-1", { model: { tool: "agy", model_id: "" } }]]);
  assert.strictEqual(writes().length, 1);
  assert.strictEqual(reloaded, 1);
  assert(text(h.dom().toastEl).includes("虛構總管") && text(h.dom().toastEl).includes("Google Gemini（AGY）"), text(h.dom().toastEl));
});

test("home: the server refuses -> the reason, no reload, the employee stays", async () => {
  setPage({ writeFails: "角色卡已達上限（虛構）" });
  let reloaded = 0;
  const ask = app.homeAsk(homeState(listing("claude", supOf(claudeHeld())), { reload: () => { reloaded += 1; } }));
  sws(ask, "pick")[0].click();
  sw(sw(ask, "confirm"), "confirm-go").click();
  await settle(60);
  assert(text(sw(ask, "error")).includes("角色卡已達上限（虛構）"));
  assert.strictEqual(reloaded, 0);
  assert(sw(ask, "confirm"), "still open");
});

test("home, a version VBear does not know: same parts; a CEO who can chat has none of it; nothing to switch to keeps the old single reason", () => {
  const unk = app.homeAsk(homeState(listing("claude", supOf({ state: "unsupported", detected: "2.1.999", message: "x" }))));
  assert.strictEqual(sws(unk, "pick").length, 2);
  assert(text(unk).includes("VBear 還不認得這一版"));
  const fine = app.homeAsk(homeState(listing("claude", supOf({ state: "verified" }))));
  assert.strictEqual(sw(fine, "box"), null);
  assert(attr(fine, "data-home", "ask-input"));
  const lone = app.homeAsk(homeState(listing("claude", support({ ...claudeHeld(), codex: codexSupport({ state: "policy" }), agy: agySupport({ state: "policy" }) }))));
  assert.strictEqual(sw(lone, "box"), null);
  assert(attr(lone, "data-home", "ask-prepare"));
  assert(attr(lone, "data-home", "ask-prepare").hasClass("primary"));
});

test("home: after the switch the old Claude chat is not the chat to send into (the server would refuse it: the card changed tool); a new chat is opened for the new tool", async () => {
  const chats = [{ id: "c-0123456789abcdef", profile_id: "emp-1", engine: "claude-chat", created_at: 1, last_at: 5, last_kind: "reply", last_text: "好", turns: 1, spent_usd: "0.01", open: false, waiting: false, problem: null }];
  const fresh = listing("codex", supOf({ state: "verified" }), { chats });
  setPage({ list: fresh });
  const ask = app.homeAsk(homeState(fresh));
  attr(ask, "data-home", "ask-input").value = "整理發票";
  FETCH_LOG.length = 0;
  attr(ask, "data-home", "ask-send").click();
  await settle(60);
  const posts = FETCH_LOG.filter((c) => c.method === "POST").map((c) => c.method + " " + c.url.split("?")[0]);
  assert.deepStrictEqual(posts, ["POST /api/chats", "POST /api/chats/c-3333333333333333/messages"]);
  // a chat of the same engine is still continued
  const same = [{ ...chats[0], engine: "codex-chat" }];
  const fresh2 = listing("codex", supOf({ state: "verified" }), { chats: same });
  setPage({ list: fresh2 });
  const ask2 = app.homeAsk(homeState(fresh2));
  attr(ask2, "data-home", "ask-input").value = "整理發票";
  FETCH_LOG.length = 0;
  attr(ask2, "data-home", "ask-send").click();
  await settle(60);
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.method === "POST").map((c) => c.url.split("?")[0]), ["/api/chats/c-0123456789abcdef/messages"]);
});

test("the look: the block has its own rules, buttons fill the row at 400px, and the words wrap", () => {
  assert(/\.switch-tool\b[^{]*\{/.test(CSS), "block rule");
  assert(/@media \(max-width: 520px\)\s*\{[^}]*\.switch-tool/.test(CSS) || /@media \(max-width: 520px\)[^@]*\.switch-tool \.btn\s*\{[^}]*(flex|width)/.test(CSS), "narrow rule");
  assert(/\.switch-tool[^{]*\{[^}]*overflow-wrap:\s*anywhere/.test(CSS), "wraps");
});

// =====================================================================================================================
// guard 21: judges and their bad samples
// =====================================================================================================================
const START = "// ---- P57 switch tool";
const END = "// ---- end of P57 switch tool";
function regionOf(src) { const a = src.indexOf(START), b = src.indexOf(END); return a >= 0 && b > a ? src.slice(a, b) : null; }
function noComments(s) { return s.split("\n").map((l) => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n"); }
function fnBody(src, name) {
  const m = new RegExp("(?:^|\\n)(?:async )?function " + name + "\\(").exec(src);
  if (!m) return null;
  const start = src.indexOf("{", src.indexOf(")", m.index + m[0].length - 1));
  let depth = 0;
  for (let i = start; i < src.length; i++) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") { depth -= 1; if (depth === 0) return noComments(src.slice(start + 1, i)); }
  }
  return null;
}
const REQUEST = /\bapi\.(?:post|get|put|del|delete|patch)\(|\bfetch\(|XMLHttpRequest|sendBeacon/g;
// 21a on the source
function judge21aSource(src) {
  const out = [];
  const reg = regionOf(src);
  if (!reg) return ["no switch-tool region"];
  const code = noComments(reg);
  const confirm = fnBody(code, "switchToolConfirm");
  if (confirm === null) return ["no switchToolConfirm function"];
  const inAll = (code.match(REQUEST) || []).length;
  const inConfirm = (confirm.match(/\bapi\.post\(/g) || []).length;
  if (inConfirm !== 1) out.push("the confirm function must make exactly one write, makes " + inConfirm);
  if (inAll !== inConfirm) out.push("a request outside the confirm function in the switch code");
  const calls = (noComments(src).match(/switchToolConfirm\(/g) || []).length;
  const wired = (noComments(src).match(/"data-switch": "confirm-go"[^\n]*on: \{ click: \(\) => switchToolConfirm\(/g) || []).length;
  if (calls !== 2 || wired !== 1) out.push("switchToolConfirm must be called only by the click of the confirm button");
  for (const name of ["chatSwitchOptions", "switchToolNode", "switchToolConfirmNode", "switchToolHost"]) {
    const b = fnBody(code, name);
    if (b === null) out.push("no " + name);
    else if (REQUEST.test(b) || /\blocation\b|localStorage|\.click\(/.test(b)) out.push(name + " reaches out");
    REQUEST.lastIndex = 0;
  }
  return out;
}
// 21b on the source
function judge21bSource(src) {
  const reg = regionOf(src);
  if (!reg) return ["no switch-tool region"];
  const confirm = fnBody(noComments(reg), "switchToolConfirm");
  if (confirm === null) return ["no switchToolConfirm function"];
  const posts = confirm.match(/api\.post\([^;]*\);/g) || [];
  if (posts.length !== 1) return ["not exactly one write"];
  const ok = /^api\.post\(`\/api\/agent-profiles\/\$\{encodeURIComponent\([\w.]+\)\}`,\s*\{\s*model:\s*\{\s*tool:\s*[\w.]+,\s*model_id:\s*""\s*\}\s*\}\);$/.test(posts[0].replace(/\s+/g, " ").replace("{ model", "{ model"));
  return ok ? [] : ["the body is not only { model: { tool, model_id: \"\" } }: " + posts[0]];
}
// 21b on a run: the log of the writes
function judge21b(log, { tool, current }) {
  const out = [];
  const w = log.filter((c) => c.method !== "GET");
  if (w.length !== 1) return ["expected exactly one write, got " + w.length];
  const [c] = w;
  if (!/^\/api\/agent-profiles\/[A-Za-z0-9_-]+$/.test(c.url)) out.push("wrong path " + c.url);
  if (JSON.stringify(Object.keys(c.body || {})) !== '["model"]') out.push("body has more than model: " + JSON.stringify(c.body));
  const m = c.body && c.body.model;
  if (!m || JSON.stringify(Object.keys(m).sort()) !== '["model_id","tool"]') out.push("model has other keys");
  else {
    if (m.model_id !== "") out.push("model_id is not the tool default");
    if (m.tool !== tool) out.push("another tool than the one confirmed");
    if (m.tool === current) out.push("the tool it already has");
  }
  return out;
}
// 21a on a run: nothing is written before the confirm press
function judge21a(log, { confirmed }) {
  const w = log.filter((c) => c.method !== "GET");
  if (!confirmed) return w.length ? ["a write before the confirm press"] : [];
  return w.length === 1 ? [] : ["expected exactly one write after the confirm press, got " + w.length];
}
// 21c on the source and on a drawn confirmation
function judge21cSource(src) {
  const reg = regionOf(src);
  if (!reg) return ["no switch-tool region"];
  const code = noComments(reg);
  const out = [];
  const b = fnBody(code, "switchToolConfirmNode");
  if (b === null) return ["no switchToolConfirmNode"];
  if (!/switchFlowText\(/.test(b)) out.push("the confirmation does not say where the words go");
  if (/"details"|\bsummary\b/.test(b)) out.push("the confirmation holds a fold");
  if (!/"data-switch": "confirm-go"/.test(b)) out.push("the confirm button is not in the same area as the sentence");
  const f = fnBody(code, "switchFlowText");
  if (f === null || !/之後跟他說的話會送到/.test(f)) out.push("switchFlowText does not carry the sentence");
  return out;
}
function judge21c(confirmNode, { company }) {
  const out = [];
  const t = text(confirmNode);
  if (!t.includes("之後跟他說的話會送到 " + company)) out.push("the sentence with " + company + " is missing");
  if (!sw(confirmNode, "confirm-go")) out.push("no confirm button in the area");
  if (confirmNode.find((n) => n.tag === "details" || n.tag === "summary")) out.push("folded");
  return out;
}

const GOOD = `${START} (v0.25.1) ----
function chatSwitchOptions(card, data) { return []; }
function switchFlowText(company, old) { return \`之後跟他說的話會送到 \${company}\`; }
function switchToolConfirmNode(ui, ctx, opt) { return el("div", null, switchFlowText("x"), el("button", { type: "button", "data-switch": "confirm-go", on: { click: () => switchToolConfirm(ui, ctx, opt) } }, "確認")); }
function switchToolNode(ui, ctx) { return el("div"); }
function switchToolHost(card, options) { return el("div"); }
async function switchToolConfirm(ui, ctx, opt) {
  try {
    await api.post(\`/api/agent-profiles/\${encodeURIComponent(ctx.card.id)}\`, { model: { tool: opt.tool, model_id: "" } });
  } catch (e) { ui.error = e; }
}
${END} ----
`;
const BUTTON_LINE = 'el("button", { type: "button", "data-switch": "confirm-go", on: { click: () => switchToolConfirm(ui, ctx, opt) } }, "確認")';

test("the real page: guards 21a, 21b and 21c hold on web/app.js", () => {
  assert.deepStrictEqual(judge21aSource(SOURCE), []);
  assert.deepStrictEqual(judge21bSource(SOURCE), []);
  assert.deepStrictEqual(judge21cSource(SOURCE), []);
  assert.deepStrictEqual(judge21aSource(GOOD), []);
  assert.deepStrictEqual(judge21bSource(GOOD), []);
  assert.deepStrictEqual(judge21cSource(GOOD), []);
});

test("21a judge catches: a second request in the switch code, a write outside the confirm function, a second way to call it, a missing region", () => {
  assert(judge21aSource(GOOD.replace("function switchToolNode(ui, ctx) { return el(\"div\"); }", "function switchToolNode(ui, ctx) { api.post(\"/api/agent-profiles/x\", {}); return el(\"div\"); }")).some((m) => /outside|reaches/.test(m)));
  assert(judge21aSource(GOOD.replace("function chatSwitchOptions(card, data) { return []; }", "function chatSwitchOptions(card, data) { return api.get(\"/api/chats\"); }")).length, "an extra read is caught too");
  assert(judge21aSource(GOOD.replace("catch (e) { ui.error = e; }", "catch (e) { ui.error = e; }\n  await api.post(`/api/agent-profiles/${x}`, { model: {} });")).some((m) => /exactly one/.test(m)));
  assert(judge21aSource(GOOD.replace(BUTTON_LINE, 'el("input", { on: { keydown: () => switchToolConfirm(ui, ctx, opt) } })')).some((m) => /only by the click/.test(m)));
  assert(judge21aSource(GOOD + "setTimeout(() => switchToolConfirm(a, b, c), 5);").some((m) => /only by the click/.test(m)));
  assert(judge21aSource(GOOD.replace("function switchToolNode(ui, ctx) { return el(\"div\"); }", "function switchToolNode(ui, ctx) { location.hash = '#/x'; return el(\"div\"); }")).some((m) => /reaches/.test(m)));
  assert(judge21aSource("nothing").length);
  assert(judge21a([{ method: "POST", url: "/api/agent-profiles/emp-1", body: {} }], { confirmed: false }).length, "a write before the press");
  assert(judge21a([], { confirmed: true }).length, "no write after the press");
  assert(judge21a([{ method: "POST" }, { method: "POST" }], { confirmed: true }).length, "two writes");
  assert.deepStrictEqual(judge21a([{ method: "POST" }], { confirmed: true }), []);
  assert.deepStrictEqual(judge21a([{ method: "GET" }], { confirmed: false }), []);
});

test("21b judge catches: another field in the body, a model id, a different tool, more than one write, a write to the wrong path", () => {
  assert(judge21bSource(GOOD.replace("{ model: { tool: opt.tool, model_id: \"\" } }", "{ model: { tool: opt.tool, model_id: \"\" }, enabled: true }")).length);
  assert(judge21bSource(GOOD.replace("{ model: { tool: opt.tool, model_id: \"\" } }", "{ name: ctx.card.name, model: { tool: opt.tool, model_id: \"\" } }")).length);
  assert(judge21bSource(GOOD.replace("model_id: \"\"", "model_id: \"gpt-x\"")).length);
  assert(judge21bSource(GOOD.replace("{ model: { tool: opt.tool, model_id: \"\" } }", "{ model: { tool: opt.tool, model_id: \"\" }, equipped_skill_ids: [] }")).length);
  const good = { method: "POST", url: "/api/agent-profiles/emp-1", body: { model: { tool: "codex", model_id: "" } } };
  assert.deepStrictEqual(judge21b([good], { tool: "codex", current: "claude" }), []);
  assert(judge21b([{ ...good, body: { ...good.body, enabled: true } }], { tool: "codex", current: "claude" }).some((m) => /more than model/.test(m)));
  assert(judge21b([{ ...good, body: { model: { tool: "codex", model_id: "gpt-x" } } }], { tool: "codex", current: "claude" }).some((m) => /default/.test(m)));
  assert(judge21b([{ ...good, body: { model: { tool: "agy", model_id: "" } } }], { tool: "codex", current: "claude" }).some((m) => /another tool/.test(m)));
  assert(judge21b([{ ...good, body: { model: { tool: "claude", model_id: "" } } }], { tool: "claude", current: "claude" }).some((m) => /already has/.test(m)));
  assert(judge21b([good, good], { tool: "codex", current: "claude" }).some((m) => /exactly one/.test(m)));
  assert(judge21b([{ ...good, url: "/api/agent-profiles" }], { tool: "codex", current: "claude" }).some((m) => /wrong path/.test(m)));
  assert(judge21b([{ ...good, body: { model: { tool: "codex", model_id: "", extra: 1 } } }], { tool: "codex", current: "claude" }).some((m) => /other keys/.test(m)));
});

test("21c judge catches: a confirmation without the sentence, with the wrong company, inside a fold, or without the confirm button", async () => {
  assert(judge21cSource(GOOD.replace("switchFlowText(\"x\")", "\"nothing\"")).some((m) => /where the words go/.test(m)));
  assert(judge21cSource(GOOD.replace("function switchToolConfirmNode(ui, ctx, opt) { return el(\"div\", null,", "function switchToolConfirmNode(ui, ctx, opt) { return el(\"div\", null, el(\"details\", null, switchFlowText(\"x\")),")).some((m) => /fold/.test(m)));
  assert(judge21cSource(GOOD.replace("\"data-switch\": \"confirm-go\", ", "")).length);
  assert(judge21cSource(GOOD.replace("之後跟他說的話會送到", "之後會送到")).some((m) => /carry the sentence/.test(m)));
  // runs
  setPage();
  await open("#/chat?profile=emp-1");
  sws(main(), "pick")[0].click();
  const c = sw(main(), "confirm");
  assert.deepStrictEqual(judge21c(c, { company: "OpenAI" }), []);
  assert(judge21c(c, { company: "Google" }).some((m) => /Google/.test(m)), "the wrong company is caught");
  const fake = new h.SyntheticNode("div");
  fake.append(new h.SyntheticNode("#text").withText("之後跟他說的話會送到 OpenAI"));
  assert(judge21c(fake, { company: "OpenAI" }).some((m) => /confirm button/.test(m)));
  const folded = new h.SyntheticNode("div");
  const det = new h.SyntheticNode("details");
  det.append(new h.SyntheticNode("#text").withText("之後跟他說的話會送到 OpenAI"));
  const go = new h.SyntheticNode("button"); go.setAttribute("data-switch", "confirm-go");
  folded.append(det, go);
  assert(judge21c(folded, { company: "OpenAI" }).some((m) => /folded/.test(m)));
});

test("21b/21a on a real run: the pressed tool is the one in the body, and nothing was written before the press", async () => {
  setPage();
  page.after = becomes("codex", supOf(claudeHeld()));
  await open("#/chat?profile=emp-1");
  assert.deepStrictEqual(judge21a(FETCH_LOG, { confirmed: false }), []);
  sws(main(), "pick")[0].click();
  assert.deepStrictEqual(judge21a(FETCH_LOG, { confirmed: false }), []);
  sw(sw(main(), "confirm"), "confirm-go").click();
  await settle(80);
  assert.deepStrictEqual(judge21a(FETCH_LOG, { confirmed: true }), []);
  assert.deepStrictEqual(judge21b(FETCH_LOG, { tool: "codex", current: "claude" }), []);
});

test("the product code has no innerHTML and no emoji in the new region", () => {
  const reg = regionOf(SOURCE);
  assert(reg, "region");
  assert(!/innerHTML|outerHTML|insertAdjacentHTML/.test(reg));
  assert(!/\p{Extended_Pictographic}/u.test(reg), "no emoji");
  assert(!/https?:\/\//.test(reg), "no external address");
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
