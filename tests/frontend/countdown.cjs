// P44-4: the countdown of a paused dispatch or group (ADR 0010 point 6): the line on the dispatch page and the group page, the rows in the
// line over every page, and the 「自己動手第 5 項」 rows of 「AI 自己做了什麼」. The real web/app.js on a synthetic DOM, fetch answered by the
// test; the words of the countdown come from the server and the page sets them (and every name) as text only. No model runs.
// Run: node tests/frontend/countdown.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const attr = (n, k) => n && n.getAttribute && n.getAttribute(k);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- the countdown (v0.18, P44-4"), SRC.indexOf("// ---------- end of the countdown"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const by = (key, value) => (n) => attr(n, key) === value;
const find = (root, key, value) => root.find(by(key, value));
const EVIL = "<img src=x onerror=alert(1)>";
const DID = "d-0123456789ab";
const GID = "g-0123456789ab";
const P1 = "emp-1", P2 = "emp-2";

const COUNTING = { state: "counting", until: 1790100000, text: "還有 2 小時 5 分可以繼續（11/09 00:00）" };
const READY = { state: "ready", until: 1790100000, text: "可以繼續了（11/09 00:00 恢復）" };
const UNKNOWN = { state: "unknown", until: null, text: "AI 工具沒說什麼時候恢復" };

const step = (seq, state) => ({ seq, who: "C1", name: "文案小編", profile_id: P1, chat_id: state === "pending" ? null : "c-" + String(seq).repeat(16),
  text: "第 " + seq + " 步要送的話", state, turn: state === "pending" ? null : 1, cost_usd: null, ended_reason: state === "ended" ? "result" : null });
const dview = (pause, over = {}) => ({ id: DID, chief_id: "cos-0123456789ab", chat_id: "c-" + "0".repeat(16), created_at: 1790000200, state: "paused",
  started_by: "you", started_by_text: "你確認的", summary: "分兩步", questions: [], notes: [], team: [], tools: ["claude"], proposal_sha: "a".repeat(64), edited: false,
  task_id: null, created_cards: [], steps: [step(1, "ended"), step(2, "pending")],
  plan: { title: "週末市集擺攤", goal: "準備手工皂攤位", deliverables: [], new_cards: [], steps: [{ who: "C1", text: "x", name: "文案小編" }, { who: "C1", text: "y", name: "文案小編" }] },
  cost: { steps: 2, per_turn_usd: "0.5", max_usd: "1", day_left_usd: "2" }, pause, events: [],
  can: { confirm: false, dismiss: false, stop: true, continue: true, delete: false, withdraw: [] }, ...over });
const gdetail = (pause) => ({ group: { id: GID, name: "市集準備", created_at: 1, state: "paused", problem: null },
  members: [{ profile_id: P1, name: "文案小編", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null },
    { profile_id: P2, name: "會計師", tool: "claude", engine: "claude-chat", can_chat: true, code: null, reason: null }],
  items: [], next_after: 0, last_seq: 0, more: false,
  round: { n: 1, state: "paused", to: "all", how: null, asked: [{ profile_id: P1, state: "done" }, { profile_id: P2, state: "waiting" }], pause }, current: null,
  cost: { per_turn_usd: "0.5", day_left_usd: "2.71", lamp: "green", group_today_usd: "0" },
  can: { send: false, why_not_send: "停在這裡", stop: true, continue: true, drop: true, edit_members: false, delete: false } });

let S;
function serve(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  S = { dview: null, gdetail: null, waiting: [], actions: { actions: [], unreadable: 0 }, ...over };
  FETCH_LOG.length = 0;
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [], sources: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false, onboarding_dismissed: true, setup_done: true, welcome_seen: true }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/waiting") return jsonResponse({ ok: true, waiting: S.waiting });
    if (p === "/api/actions") return jsonResponse(S.actions);
    if (p === "/api/meetings/ledger") return jsonResponse({ ok: true, spent_usd: "0.29", daily_usd: "3", lamp: "green", blocked: false });
    if (p === "/api/chats" && method === "GET") return jsonResponse({ ok: true, chats: [], more: 0, cards: [], support: {}, limits: { per_turn_usd: "0.5", daily_usd: "3" },
      ledger: { spent_usd: "0.1", daily_usd: "3", lamp: "green" }, problems: [] });
    if (p === "/api/groups" && method === "GET") return jsonResponse({ groups: [], problems: [] });
    let m = /^\/api\/dispatch\/(d-[0-9a-f]{12})$/.exec(p);
    if (m && method === "GET") return S.dview ? jsonResponse(S.dview) : jsonResponse({ error: "找不到這份派工" }, false, 404);
    m = /^\/api\/groups\/(g-[0-9a-f]{12})$/.exec(p);
    if (m && method === "GET") return S.gdetail ? jsonResponse(S.gdetail) : jsonResponse({ error: "沒有" }, false, 404);
    return null;
  });
}
async function open(hash) {
  const real = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = real; }
  return h.dom().mainEl;
}
const bar = () => { const b = global.document.createElement("div"); b.setAttribute("id", "waiting-bar"); return b; };

test("the dispatch page says how long is left beside the sentence, and that item 5 does it only when ticked", async () => {
  serve({ dview: dview({ reason: "daily_limit", until: 1790100000, text: "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；到時候按「繼續」接著做第 2 步。", countdown: COUNTING }) });
  const main = await open("#/dispatch/" + DID);
  const line = find(main, "data-countdown", "counting");
  assert(line, "a countdown line");
  assert(text(line).includes("還有 2 小時 5 分可以繼續（11/09 00:00）"), text(line));
  assert(text(line).includes("第 5 項") && text(line).includes("沒勾") && text(line).includes("你按"), text(line));
  assert(find(main, "data-dispatch", "pause").find(by("data-countdown", "counting")), "inside the pause notice");
  assert(find(main, "data-dispatch", "continue"), "the button is there before the time: the person may press 繼續 any time");
});

test("after the time it says it can go on", async () => {
  serve({ dview: dview({ reason: "daily_limit", until: 1790100000, text: "x", countdown: READY }) });
  const main = await open("#/dispatch/" + DID);
  assert(text(find(main, "data-countdown", "ready")).includes("可以繼續了（11/09 00:00 恢復）"));
});

test("a time the AI tool did not give: no countdown, and it says VBear does not go on by itself", async () => {
  serve({ dview: dview({ reason: "plan_limit", until: null, text: "Claude Code 的方案用量到了上限，恢復時間未知。", countdown: UNKNOWN }) });
  const main = await open("#/dispatch/" + DID);
  const line = find(main, "data-countdown", "unknown");
  assert(text(line).includes("AI 工具沒說什麼時候恢復"));
  assert(text(line).includes("不會自己接續"), text(line));
});

test("a pause that needs a look has no countdown line", async () => {
  serve({ dview: dview({ reason: "uncertain", until: null, text: "VBear 不確定剛才有沒有建好。", countdown: null }) });
  const main = await open("#/dispatch/" + DID);
  assert.strictEqual(find(main, "data-countdown", "counting"), null);
  assert.strictEqual(main.find((n) => attr(n, "data-countdown") !== null && attr(n, "data-countdown") !== undefined && attr(n, "data-countdown") !== ""), null);
});

test("an old server's pause (no countdown field at all) is drawn as before", async () => {
  serve({ dview: dview({ reason: "daily_limit", until: 1790100000, text: "今天的花費到了每天上限。" }) });
  const main = await open("#/dispatch/" + DID);
  assert(text(find(main, "data-dispatch", "pause")).includes("今天的花費到了每天上限。"));
  assert.strictEqual(main.find((n) => attr(n, "data-countdown")), null);
});

test("the group page counts down too, and says a group does not go on by itself", async () => {
  serve({ gdetail: gdetail({ reason: "daily_limit", until: 1790100000, text: "今天的花費到了每天上限 US$3，本機明天 0:00 重新計算；還有 1 位沒回答。", countdown: COUNTING }) });
  const main = await open("#/chat/group/" + GID);
  const line = find(main, "data-countdown", "counting");
  assert(line, "a countdown line on the group page");
  assert(text(line).includes("還有 2 小時 5 分可以繼續（11/09 00:00）") && text(line).includes("群組不會自己接續"), text(line));
  assert(!text(line).includes("第 5 項"), "item 5 does not apply to a group");
  assert(find(main, "data-group", "continue"), "the person's button is as it was");
});

test("the line over every page lists a dispatch and a group that wait for a limit, with the server's words, a link each, and nothing of their text", async () => {
  const b = bar();
  serve({ dview: dview(null, { state: "running" }),
    waiting: [{ kind: "dispatch_resume", dispatch_id: DID, name: "週末市集擺攤", reason: "daily_limit", state: "counting", until: 1790100000, text: COUNTING.text },
      { kind: "group_resume", group_id: GID, name: "市集準備", state: "ready", until: 1790100000, text: READY.text }] });
  await open("#/dispatch/" + DID);
  assert.strictEqual(b.hidden, false);
  const t = text(b);
  assert(t.includes("等你決定：分配工作「週末市集擺攤」還有 2 小時 5 分可以繼續（11/09 00:00）"), t);
  assert(t.includes("另外還有 1 件"), t);
  assert.strictEqual(attr(find(b, "data-waiting", "resume-link"), "href"), "#/dispatch/" + DID);
});

test("a group alone links to the group, and routine reminders and these share the line", async () => {
  const b = bar();
  serve({ dview: dview(null, { state: "running" }),
    waiting: [{ kind: "group_resume", group_id: GID, name: "市集準備", state: "ready", until: 1790100000, text: READY.text }] });
  await open("#/dispatch/" + DID);
  assert(text(b).includes("等你決定：群組「市集準備」可以繼續了（11/09 00:00 恢復）"), text(b));
  assert.strictEqual(attr(find(b, "data-waiting", "resume-link"), "href"), "#/chat/group/" + GID);
  const both = [{ kind: "routine_due", run_id: "rr-aaaaaaaaaaaa", routine_id: "r-0123456789ab", name: "市集日報", slot: "2026-11-09T08:00", due_at: 1 },
    { kind: "group_resume", group_id: GID, name: "市集準備", state: "unknown", until: null, text: UNKNOWN.text }];
  serve({ dview: dview(null, { state: "running" }), waiting: both });
  await open("#/dispatch/" + DID);
  assert(text(b).includes("定時工作「市集日報」08:00到時間了") && text(b).includes("群組「市集準備」AI 工具沒說什麼時候恢復"), text(b));
  assert.strictEqual(attr(find(b, "data-waiting", "link"), "href"), "#/routines");
});

test("a name is text: markup in it stays text", async () => {
  const b = bar();
  serve({ dview: dview(null, { state: "running" }), waiting: [{ kind: "dispatch_resume", dispatch_id: DID, name: EVIL, reason: "daily_limit", state: "ready", until: 1, text: READY.text }] });
  await open("#/dispatch/" + DID);
  assert(text(b).includes(EVIL));
  assert.strictEqual(b.findAll((n) => n.tag === "img" || n.tag === "script").length, 0);
});

test("nothing waits: the line is hidden", async () => {
  const b = bar();
  serve({ dview: dview(null, { state: "running" }), waiting: [] });
  await open("#/dispatch/" + DID);
  assert.strictEqual(b.hidden, true);
  assert.strictEqual(text(b), "");
});

test("a row the page does not know is ignored, not drawn", async () => {
  const b = bar();
  serve({ dview: dview(null, { state: "running" }), waiting: [{ kind: "something_new", name: "x", text: "y" }, { kind: "dispatch_resume", name: 5 }, null] });
  await open("#/dispatch/" + DID);
  assert.strictEqual(b.hidden, true);
});

test("「AI 自己做了什麼」 marks an item 5 press as the one VBear did by itself", async () => {
  serve({ actions: { unreadable: 0, actions: [
    { at: 1790000900, dispatch_id: DID, seq: 6, kind: "continued", what: "恢復時間到了，VBear 自己按了「繼續」", by: "auto5", by_text: "自己動手第 5 項", profile_id: null, can_stop: false, can_withdraw: false },
    { at: 1790000800, dispatch_id: DID, seq: 4, kind: "continued", what: "繼續派工", by: "you", by_text: "你按的", profile_id: null, can_stop: false, can_withdraw: false }] } });
  const main = await open("#/actions");
  const rows = main.findAll(by("data-action", "row"));
  assert.strictEqual(rows.length, 2);
  assert(text(rows[0]).includes("自己動手第 5 項") && text(rows[0]).includes("自己按了「繼續」"), text(rows[0]));
  const badge = (r) => r.find((n) => n.hasClass && n.hasClass("badge") && /第 5 項|你按的/.test(text(n)));
  assert(badge(rows[0]).hasClass("b-warn"), "the person is shown it was not their press");
  assert(badge(rows[1]).hasClass("b-ok"));
  assert.strictEqual(attr(rows[0].find((n) => n.tag === "a"), "href"), "#/dispatch/" + DID);
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, no request of its own", () => {
  assert(BLOCK.length > 300, "the block is marked in app.js");
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/u.test(BLOCK));
  assert(!/api\.(post|get)\(/.test(BLOCK), "the block draws what it is given");
  assert(!/排程|cron|routine|自動重試/.test(BLOCK.replace(/routine_due/g, "")), "the words of the glossary");
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
