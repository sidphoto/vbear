// P34-5: the meeting pages. The meetings page (list, new meeting, preview, one meeting with its evidence and the
// chairman's desk), the bubbles and the meeting room of the office, the home page's "your turn", the entry on a task
// card, and "write the decision into the task card". The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a
// browser test. Nothing here runs a model: the server answers with fixtures.
// Run: node tests/frontend/meetings.cjs   (exit code 0 = pass)
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
const q = (n, key) => n.find((x) => x.getAttribute && x.getAttribute("data-mt") === key);
const qa = (n, key) => n.findAll((x) => x.getAttribute && x.getAttribute("data-mt") === key);
const byClass = (n, c) => n.findAll((x) => x.hasClass && x.hasClass(c));
const clone = (x) => JSON.parse(JSON.stringify(x));
const EVIL = "<img src=x onerror=alert(1)>";

// ---- fixtures ---------------------------------------------------------------------------------------------------

const MID = "m-0123456789ab";
const MID2 = "m-ba9876543210";
const people = () => [
  { profile_id: "ceo", name: "執行長卡", position: "planner", tool: "claude", model_used: "opus", revision: "r1", proxy: false },
  { profile_id: "law", name: "法務卡", position: "legal", tool: "claude", model_used: "sonnet", revision: "r2", proxy: false },
  { profile_id: "art", name: "藝術卡", position: "art", tool: "agy", model_used: "sonnet", revision: "r3", proxy: true },
];
const evidence = (over = {}) => ({ cli_version: "2.1.296", model_reported: "claude-sonnet-x", tools_reported: ["StructuredOutput"],
  mcp_servers_reported: [], exit_code: 0, duration_ms: 4200, cost_usd: "0.0412", cost_source: "cli", ...over });
const opinion = (over = {}) => ({ stance: "支持", summary: "可以做", points: ["第一點"], risks: [], needs_chairman: false, ...over });
const decision = (over = {}) => ({ decision: "先做草稿", rationale: "風險低", dissent_addressed: ["法務的顧慮已處理"],
  actions: [{ type: "寫草稿", text: "寫三則貼文草稿" }], escalate: false, escalate_reason: "", follow_up_topics: ["下週的預算"], ...over });
const turn = (seq, profile_id, kind, state, over = {}) => ({ seq, profile_id, kind, state, attempts: 1, started_at: 1790000000 + seq,
  ended_at: state === "queued" || state === "running" ? null : 1790000010 + seq, prompt_sha256: "a".repeat(64),
  evidence: state === "done" ? evidence() : null, output: null, error_code: null, ...over });
function meeting(over = {}) {
  return { id: MID, topic: "下個月的貼文", context: "補充說明", flags_by_chairman: [], created_at: 1790000000,
    participants: people(), limits: { per_call_usd: "0.20", meeting_usd: "1.50" },
    turns: [turn(1, "law", "opinion", "done", { output: opinion() }), turn(2, "art", "opinion", "done", { output: opinion({ stance: "有條件支持" }) }),
      turn(3, "ceo", "decision", "done", { output: decision() })],
    status: "decided", major: false, rules: [], chairman: { state: "not_needed", at: null, note: "", label: "主控台記錄（未驗證身分）" },
    spent_usd: "0.1236", retryable: [], ...over };
}
const summary = (m) => ({ id: m.id, topic: m.topic, created_at: m.created_at, status: m.status, major: m.major,
  chairman_state: m.chairman.state, spent_usd: m.spent_usd, task_id: m.task_id || null, participants: m.participants.length });
const ledger = (over = {}) => ({ spent_usd: "0.50", daily_usd: "3.00", per_call_usd: "0.20", meeting_usd: "1.50", lamp: "green",
  running: null, blocked: false, note: "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。", ...over });
const cardOf = (id, name, position, tool = "claude", over = {}) => ({ id, name, position, enabled: true, model: { tool, model_id: "" }, ...over });
const task = (over = {}) => ({ id: "task-1", title: "貼文任務", goal: "寫貼文", scope: [], out_of_scope: [], deliverables: [], acceptance_criteria: [],
  evidence: [], status: "draft", workdir: "/tmp/x", provenance: {}, steps: [], artifacts: [], ...over });

let page;
function setPage(over = {}) {
  // the app already ran once when it was loaded (against no server): its static data is read again from the stub
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  page = { meetings: [], details: {}, ledger: ledger(), profiles: [cardOf("ceo", "執行長卡", "planner"), cardOf("law", "法務卡", "legal"),
    cardOf("art", "藝術卡", "art", "agy"), cardOf("old", "停用的 PM", "pm", "claude", { enabled: false })], tasks: [task()],
  preview: null, previewStatus: 200, verifyStatus: 200, verifyError: "", meetingsError: "", ...over };
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: page.profiles });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: page.tasks });
    if (p === "/api/config") return jsonResponse({ ok: true, config: {} });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: false });
    if (p === "/api/meetings" && method === "GET") return page.meetingsError ? jsonResponse({ error: page.meetingsError }, false, 500) : jsonResponse({ meetings: page.meetings });
    if (p === "/api/meetings/ledger") return jsonResponse(page.ledger);
    if (p === "/api/meetings/preview") return page.previewStatus === 200 ? jsonResponse(page.preview) : jsonResponse(page.preview, false, page.previewStatus);
    if (p === "/api/meetings" && method === "POST") return jsonResponse(page.details[MID] || meeting(), true, 202);
    const m = /^\/api\/meetings\/(m-[0-9a-f]{12})(?:\/([a-z-]+))?$/.exec(p);
    if (m && !m[2] && method === "GET") return page.details[m[1]] ? jsonResponse(page.details[m[1]]) : jsonResponse({ error: "找不到這場會議" }, false, 404);
    if (m && m[2] === "chairman") return jsonResponse(page.details[m[1]]);
    if (m && m[2] === "retry-preview") return jsonResponse(page.retryPreview);
    if (m && m[2] === "retry") return jsonResponse(page.details[m[1]], true, 202);
    if (p === "/api/meetings/verify") return page.verifyStatus === 200 ? jsonResponse({ version: "2.1.296", passed_at: 1790000000 })
      : jsonResponse({ code: "boundary_unverified", error: page.verifyError }, false, page.verifyStatus);
    // what the real server says to the translations' check when Codex is the translation engine: a meeting must not use it
    if (p === "/api/translations/verify") return jsonResponse({ code: "boundary_unverified", error: "這個 Claude Code 版本的翻譯安全邊界還沒驗證；Codex 翻譯仍未開放" }, false, 409);
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
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
const posts = (suffix) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.endsWith(suffix));
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));

// ---- the bubbles: a closed table made from the record --------------------------------------------------------------

test("a bubble comes from the record only, from a closed table", () => {
  assert.strictEqual(typeof app.meetingBubble, "function");
  const table = new Set(app.MEETING_BUBBLES);
  const expectOpinion = { queued: "等發言", running: "發言中", failed: "失敗", blocked: "卡住" };
  for (const [state, label] of Object.entries(expectOpinion)) assert.strictEqual(app.meetingBubble(turn(1, "law", "opinion", state), {}), label);
  const stances = { 支持: "支持", 反對: "反對", 有條件支持: "有條件支持", 需要更多資訊: "要更多資訊" };
  for (const [stance, label] of Object.entries(stances)) {
    assert.strictEqual(app.meetingBubble(turn(1, "law", "opinion", "done", { output: opinion({ stance }) }), {}), label);
  }
  assert.strictEqual(app.meetingBubble(turn(1, "law", "opinion", "skipped", { error_code: "budget" }), {}), "額度不夠沒發言");
  assert.strictEqual(app.meetingBubble(turn(3, "ceo", "decision", "running"), {}), "整理意見中");
  assert.strictEqual(app.meetingBubble(turn(3, "ceo", "decision", "done", { output: decision() }), { major: false, chairmanState: "not_needed" }), "已決定");
  assert.strictEqual(app.meetingBubble(turn(3, "ceo", "decision", "done", { output: decision() }), { major: true, chairmanState: "pending" }), "交董事長");
  // whatever the record holds, nothing outside the table is ever shown (a stance or a state this page does not know included)
  const states = ["queued", "running", "done", "failed", "blocked", "skipped", "cancelled", "interrupted", "new-state", undefined];
  const stancesAll = ["支持", "反對", "有條件支持", "需要更多資訊", EVIL, undefined];
  for (const kind of ["opinion", "decision", "other"]) for (const state of states) for (const s of stancesAll) for (const code of [null, "budget", EVIL]) {
    for (const ctx of [{}, { major: true, chairmanState: "pending" }, { major: true, chairmanState: "approved" }, { major: true, chairmanState: "rejected" }]) {
      const label = app.meetingBubble({ kind, state, error_code: code, output: { stance: s } }, ctx);
      assert(table.has(label), JSON.stringify({ kind, state, s, code, label }));
    }
  }
  assert.strictEqual(app.meetingBubble(null, {}), "狀態不明");
  assert.strictEqual(app.meetingBubble(turn(1, "law", "opinion", "done", { output: opinion({ stance: "隨便" }) }), {}), "狀態不明");
});

test("seats: one per person, the chair last, a spoken-for card marked, the label names its record", () => {
  const seats = app.meetingSeats(meeting());
  assert.deepStrictEqual(seats.map((s) => s.profileId), ["law", "art", "ceo"]);
  assert.deepStrictEqual(seats.map((s) => s.bubble), ["支持", "有條件支持", "已決定"]);
  assert.deepStrictEqual(seats.map((s) => s.proxy), [false, true, false]);
  assert.deepStrictEqual(seats.map((s) => s.seq), [1, 2, 3]);
  assert.strictEqual(seats[0].positionLabel, "法務經理");
  assert.strictEqual(seats[2].positionLabel, "CEO");
  assert(seats[0].label.includes("依據：會議紀錄 " + MID + " 第 1 位"), seats[0].label);
  assert(seats[1].label.includes("代發言"), seats[1].label);
  assert(!seats[0].label.includes("代發言"));
  assert.notStrictEqual(seats[1].species, "");
  const node = app.meetingSeatNode(seats[1], { href: "#/meetings/" + MID });
  assert.strictEqual(node.tag, "a");
  assert.strictEqual(node.getAttribute("href"), "#/meetings/" + MID);
  assert.strictEqual(node.getAttribute("aria-label"), seats[1].label);
  assert(text(node).includes("代發言"));
  assert(text(node).includes("有條件支持"));
  // a person whose turn is missing from the record is not given a made-up bubble
  const broken = clone(meeting());
  broken.turns = broken.turns.slice(0, 1);
  const s2 = app.meetingSeats(broken);
  assert.deepStrictEqual(s2.map((s) => s.bubble), ["支持", "狀態不明", "狀態不明"]);
});

// ---- ledger, status words, the room's pick, the chairman's desk -------------------------------------------------

test("the ledger lamp: green says nothing, yellow warns, red stops new meetings and says why", () => {
  const g = app.meetingLamp(ledger());
  assert.deepStrictEqual([g.key, g.canOpen, g.warn], ["green", true, false]);
  const y = app.meetingLamp(ledger({ lamp: "yellow", spent_usd: "2.50" }));
  assert.deepStrictEqual([y.key, y.canOpen, y.warn], ["yellow", true, true]);
  assert(y.text.includes("2.50") && y.text.includes("3.00") && y.text.includes("80%"), y.text);
  const r = app.meetingLamp(ledger({ lamp: "red", spent_usd: "3.00" }));
  assert.deepStrictEqual([r.key, r.canOpen], ["red", false]);
  assert(r.text.includes("不能開新的會議") && r.text.includes("重試"), r.text);
  const b = app.meetingLamp(ledger({ blocked: true }));
  assert.strictEqual(b.canOpen, false);
  assert(b.text.includes("無法確認"), b.text);
  const none = app.meetingLamp(null);
  assert.strictEqual(none.key, "unknown");
  assert.strictEqual(none.canOpen, false, "an unreadable ledger does not open a meeting");
  assert(app.meetingLamp(ledger({ lamp: "purple" })).key === "unknown");
  assert(g.text.includes("估值"), "the estimate note is always there");
});

test("status words, and the meetings that wait for the chairman", () => {
  assert.strictEqual(app.meetingStatusText("waiting_chairman"), "輪到你：董事長核准");
  assert.strictEqual(app.meetingStatusText("decided"), "CEO 已決定");
  assert.strictEqual(app.meetingStatusText("running"), "進行中");
  assert.strictEqual(app.meetingStatusText("rejected"), "董事長已否決");
  assert.strictEqual(app.meetingStatusText("approved"), "董事長已核准");
  assert.strictEqual(app.meetingStatusText("nonsense"), "狀態不明");
  const list = { meetings: [summary(meeting({ id: MID, status: "waiting_chairman", major: true })), summary(meeting({ id: MID2, status: "decided" })),
    { id: "m-aaaaaaaaaaaa", blocked: true, error: "壞了" }] };
  assert.deepStrictEqual(app.meetingsNeedingYou(list).map((m) => m.id), [MID]);
  assert.deepStrictEqual(app.meetingsNeedingYou(null), []);
  assert.deepStrictEqual(app.meetingsNeedingYou({ meetings: "x" }), []);
});

test("the meeting room shows the newest meeting that is running or waits, and counts the rest", () => {
  const a = meeting({ id: MID, status: "waiting_chairman", major: true, created_at: 100 });
  const b = meeting({ id: MID2, status: "running", created_at: 200 });
  const c = meeting({ id: "m-cccccccccccc", status: "decided", created_at: 300 });
  const d = meeting({ id: "m-dddddddddddd", status: "waiting_chairman", major: true, created_at: 50 });
  const list = { meetings: [c, b, a, d].map(summary) };
  const pick = app.meetingRoomPick(list);
  assert.strictEqual(pick.id, b.id);
  assert.strictEqual(pick.more, 2);
  assert.strictEqual(pick.waiting, 2);
  assert.strictEqual(pick.firstWaitingId, a.id, "the newest of the waiting ones");
  const model = app.meetingRoomModel(list, b);
  assert.strictEqual(model.id, b.id);
  assert.strictEqual(model.more, 2);
  assert.strictEqual(model.seats.length, 3);
  assert.strictEqual(model.waiting, 2);
  assert.strictEqual(app.meetingRoomPick({ meetings: [summary(c)] }).id, null);
  assert.strictEqual(app.meetingRoomModel({ meetings: [summary(c)] }, null).seats.length, 0);
  assert.strictEqual(app.meetingRoomModel({ meetings: [summary(c)] }, null).empty, true);
  assert.strictEqual(app.meetingRoomModel(null, null).error !== "", true, "no list is not 'no meetings'");
  assert.strictEqual(app.meetingRoomModel({ meetings: "x" }, null).error !== "", true);
  assert.strictEqual(app.meetingRoomPick({ meetings: [{ id: "m-eeeeeeeeeeee", blocked: true, error: "壞了" }] }).blocked, 1);
});

// ---- the task note -----------------------------------------------------------------------------------------------

test("the note for a task card is made from the decision, and only a decision that may go in is offered", () => {
  const ok = meeting({ task_id: "task-1" });
  const note = app.meetingTaskNote(ok);
  assert(note.includes(MID) && note.includes("先做草稿") && note.includes("風險低") && note.includes("寫草稿") && note.includes("寫三則貼文草稿"), note);
  assert(note.length <= 2000);
  const long = clone(ok);
  long.turns[2].output.rationale = "長".repeat(5000);
  assert(app.meetingTaskNote(long).length <= 2000);
  assert.strictEqual(app.meetingTaskNoteOffer(ok).ok, true);
  assert.strictEqual(app.meetingTaskNoteOffer(meeting({ status: "approved", major: true, chairman: { state: "approved" } })).ok, true);
  for (const status of ["running", "waiting_chairman", "rejected", "cancelled", "incomplete"]) {
    const o = app.meetingTaskNoteOffer(meeting({ status, major: status === "waiting_chairman" }));
    assert.strictEqual(o.ok, false, status);
    assert(o.why.length > 0);
  }
  const waiting = app.meetingTaskNoteOffer(meeting({ status: "waiting_chairman", major: true }));
  assert(waiting.why.includes("董事長"), waiting.why);
});

// ---- the home page -----------------------------------------------------------------------------------------------

test("home: a meeting that waits for the chairman is on the 'your turn' board, and only that one", async () => {
  const wait = meeting({ id: MID, topic: "要花錢的事 " + EVIL, status: "waiting_chairman", major: true,
    chairman: { state: "pending", at: null, note: "", label: "主控台記錄（未驗證身分）" } });
  const done = meeting({ id: MID2, status: "decided" });
  setPage({ meetings: [wait, done].map(summary) });
  const g = app.boardGroups({ runtime: { available: true } }, { flows: [] }, { meetings: [wait, done].map(summary) });
  assert.deepStrictEqual(g.yourTurnMeetings.map((m) => m.id), [MID]);
  assert.strictEqual(g.allEmpty, false, "a waiting meeting is not 'nothing for you'");
  assert.strictEqual(app.boardGroups({ runtime: { available: true } }, { flows: [] }, { meetings: [summary(done)] }).allEmpty, true);
  assert.strictEqual(app.boardGroups({ runtime: { available: true } }, { flows: [] }).yourTurnMeetings.length, 0, "the third argument is optional");
  const main = await open("#/");
  const card = q(main, "board-card");
  assert(card, "a card on the board: " + text(main).slice(0, 600));
  assert.strictEqual(card.getAttribute("href") || (card.find((n) => n.tag === "a") || card).getAttribute("href"), "#/meetings/" + MID);
  assert(text(card).includes("要花錢的事"));
  assert(text(card).includes(EVIL), "the topic is text, not markup");
  // the total can hold a worst-case cost (a call that reported nothing): the card does not call all of it the CLI's figure
  assert(text(card).includes("沒有回報的呼叫以每次上限計"), text(card));
  assert.strictEqual(main.findAll((n) => n.tag === "img").length, 0);
  assert(text(main).includes("1 場會議等你"));
  // the board's key changes when a meeting joins it, so the 5-second refresh repaints
  const k0 = app.boardKey(app.boardGroups({ runtime: { available: true } }, { flows: [] }, { meetings: [] }), { liveError: "", projects: [] });
  const k1 = app.boardKey(g, { liveError: "", projects: [] });
  assert.notStrictEqual(k0, k1);
});

// ---- the meetings page: the list and the new meeting --------------------------------------------------------------

test("the meetings page: the lamp, the list of meetings, and the way to a new one", async () => {
  const a = meeting({ id: MID, status: "waiting_chairman", major: true, topic: "A " + EVIL });
  const b = meeting({ id: MID2, status: "decided", topic: "B", created_at: 1790000999 });
  setPage({ meetings: [a, b].map(summary), ledger: ledger({ lamp: "yellow", spent_usd: "2.50" }) });
  const main = await open("#/meetings");
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "會議");
  const lamp = q(main, "lamp");
  assert.strictEqual(lamp.getAttribute("data-lamp"), "yellow");
  assert(text(lamp).includes("2.50") && text(lamp).includes("80%"));
  const rows = qa(main, "meeting-row");
  assert.strictEqual(rows.length, 2);
  assert(text(rows[0]).includes("B") || text(rows[1]).includes("B"));
  const links = rows.map((r) => r.find((n) => n.tag === "a").getAttribute("href")).sort();
  assert.deepStrictEqual(links, ["#/meetings/" + MID, "#/meetings/" + MID2]);
  const waitRow = rows.find((r) => text(r).includes("輪到你：董事長核准"));
  assert(waitRow, "the waiting meeting says whose turn it is");
  assert(text(waitRow).includes(EVIL));
  assert.strictEqual(main.findAll((n) => n.tag === "img").length, 0);
  assert(q(main, "topic") && q(main, "preview"), "the new-meeting form");
});

test("a damaged meeting stays in the list as blocked", async () => {
  setPage({ meetings: [{ id: MID, blocked: true, error: "會議紀錄無法安全讀寫" }] });
  const main = await open("#/meetings");
  const row = qa(main, "meeting-row")[0];
  assert(row);
  assert(text(row).includes("無法讀取") && text(row).includes(MID), text(row));
});

test("red lamp: no new meeting can be previewed, and the page says why", async () => {
  setPage({ ledger: ledger({ lamp: "red", spent_usd: "3.00" }) });
  const main = await open("#/meetings");
  assert.strictEqual(q(main, "lamp").getAttribute("data-lamp"), "red");
  assert(text(q(main, "lamp")).includes("不能開新的會議"));
  assert.strictEqual(q(main, "preview").disabled, true);
  assert(text(main).includes("今日額度已用完"));
});

function fill(main, { topic = "下個月的貼文", chair = "ceo", speakers = ["law"], flags = [], taskId = "" } = {}) {
  q(main, "topic").value = topic;
  q(main, "chair").value = chair;
  for (const cb of qa(main, "speaker")) cb.checked = speakers.includes(cb.getAttribute("data-profile"));
  for (const cb of qa(main, "flag")) cb.checked = flags.includes(cb.getAttribute("data-flag"));
  q(main, "task").value = taskId;
}
const previewOf = (over = {}) => ({ preview_id: "p-1", startable: true, blockers: [], topic: "下個月的貼文", context: "", flags: [], task: null,
  participants: [{ profile_id: "law", name: "法務卡", position: "legal", tool: "claude", model: "sonnet", model_used: "sonnet", proxy: false,
    instructions: "你是法務經理 " + EVIL, prompt: "給法務的完整 prompt " + EVIL, prompt_sha256: "b".repeat(64), dynamic: false },
  { profile_id: "art", name: "藝術卡", position: "art", tool: "agy", model: "sonnet", model_used: "sonnet", proxy: true,
    instructions: "你是藝術總監", prompt: "給藝術的 prompt", prompt_sha256: "c".repeat(64), dynamic: false }],
  chair: { profile_id: "ceo", name: "執行長卡", position: "planner", tool: "claude", model: "opus", model_used: "opus", proxy: false,
    instructions: "你是 CEO", prompt: "給 CEO 的 prompt", prompt_sha256: "d".repeat(64), dynamic: true },
  calls: 3, reserve_usd: "0.60", limits: { per_call_usd: "0.20", meeting_usd: "1.50", daily_usd: "3.00" },
  today: { spent_usd: "0.50", daily_usd: "3.00", lamp: "green" }, cli: { version: "2.1.296", verified: true },
  disclosure: "開始後，下面每一段文字會用你的 Claude 帳號送到 Anthropic。", cost_note: "金額是 Claude Code 回報的估值；訂閱方案不等於實際帳單。",
  rules: [{ id: "R1", text: "規則一" }], ...over });

test("the form chooses a CEO card and one card per position, and a stopped card cannot be chosen", async () => {
  setPage();
  const main = await open("#/meetings");
  const chairOptions = q(main, "chair").findAll((n) => n.tag === "option").map((n) => n.getAttribute("value"));
  assert(chairOptions.includes("ceo"));
  assert(!chairOptions.includes("law"), "only CEO cards can chair");
  const speakers = qa(main, "speaker");
  assert.deepStrictEqual(speakers.map((s) => s.getAttribute("data-profile")).sort(), ["art", "law"], "the stopped PM card is not offered");
  const art = speakers.find((s) => s.getAttribute("data-profile") === "art");
  assert(text(art.parentNode).includes("代發言"), "a card of another tool is said to be spoken for by Claude");
  assert.strictEqual(qa(main, "flag").length, 6);
  assert.deepStrictEqual(qa(main, "flag").map((f) => f.getAttribute("data-flag")), ["publish", "spend", "delete", "legal", "deploy", "personal"]);
});

test("preview shows every instruction and prompt in full as text, and 'start' sends only the preview id", async () => {
  setPage({ preview: previewOf() });
  const main = await open("#/meetings");
  fill(main, { speakers: ["law", "art"], flags: ["spend"] });
  q(main, "preview").click();
  await settle();
  const pre = posts("/api/meetings/preview");
  assert.strictEqual(pre.length, 1);
  assert.deepStrictEqual(pre[0].body, { topic: "下個月的貼文", chair_profile_id: "ceo", speaker_profile_ids: ["law", "art"], flags: ["spend"] });
  const dlg = dialog();
  assert(dlg, "a dialog");
  const all = text(dlg);
  for (const piece of ["給法務的完整 prompt", "給藝術的 prompt", "給 CEO 的 prompt", "你是法務經理", "你是 CEO", "2.1.296", "0.60", "送到 Anthropic",
    "估值", "代發言", "已通過無工具安全檢查"]) assert(all.includes(piece), piece);
  assert(all.includes(EVIL), "markup in the text stays text");
  assert.strictEqual(dlg.findAll((n) => n.tag === "img").length, 0);
  assert(qa(dlg, "prompt").length >= 3);
  q(dlg, "start").click();
  await settle();
  const start = FETCH_LOG.filter((c) => c.method === "POST" && c.url === "/api/meetings");
  assert.strictEqual(start.length, 1);
  assert.deepStrictEqual(start[0].body, { preview_id: "p-1" });
  assert.strictEqual(global.location.hash, "#/meetings/" + MID);
});

test("an unverified Claude Code version shows 'check first' and no start button; the check is the tool-less one, of Claude", async () => {
  setPage({ preview: previewOf({ startable: false, preview_id: null, cli: { version: "2.1.999", verified: false },
    blockers: [{ code: "boundary_unverified", message: "這個 Claude Code 版本還沒通過無工具安全檢查，請先檢查" }] }) });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  const dlg = dialog();
  assert(text(dlg).includes("還沒通過無工具安全檢查"));
  assert.strictEqual(q(dlg, "start"), null, "nothing to start");
  const verify = q(dlg, "verify");
  assert(verify, "the check button");
  assert(text(verify).includes("無工具安全檢查"));
  page.preview = previewOf();
  FETCH_LOG.length = 0;
  verify.click();
  await settle();
  // the check uses the person's Claude account: like the settings page, it asks in the page first
  assert.strictEqual(posts("/verify").length, 0, "nothing is sent by the first click");
  const ask = h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("aria-labelledby") === "modal-confirm-title");
  assert(ask, "a confirmation in the page");
  assert(text(ask).includes("無工具安全檢查") && text(ask).includes("不到 1 美分") && text(ask).includes("驗證翻譯安全邊界"), text(ask));
  assert(text(ask).includes("不論翻譯引擎選哪一個，這裡都檢查 Claude Code") && text(ask).includes("不會改你的翻譯設定"), text(ask));
  ask.find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  // the meetings' own check, always of Claude: the translations' one checks the translation engine, which may be Codex
  assert.deepStrictEqual(posts("/api/meetings/verify").map((c) => c.body), [{}]);
  assert.strictEqual(posts("/api/translations/verify").length, 0);
  assert.strictEqual(posts("/api/config").length, 0, "the translation settings are not changed to make the check pass");
  assert(text(h.dom().toastEl).includes("Claude Code 2.1.296 通過無工具安全檢查"), text(h.dom().toastEl));
  assert.strictEqual(posts("/api/meetings/preview").length, 1, "the preview is made again after the check");
});

test("a failed tool-less check says the server's reason and makes no new preview", async () => {
  const reason = "這個 Claude Code 版本沒有通過無工具安全檢查（版本或檢查的回應看不懂，或它回報的不是只有 StructuredOutput、沒有 MCP），會議仍然不能開始";
  setPage({ verifyStatus: 409, verifyError: reason, preview: previewOf({ startable: false, preview_id: null, cli: { version: "2.1.999", verified: false },
    blockers: [{ code: "boundary_unverified", message: "這個 Claude Code 版本還沒通過無工具安全檢查，請先檢查" }] }) });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  FETCH_LOG.length = 0;
  q(dialog(), "verify").click();
  await settle();
  const ask = h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("aria-labelledby") === "modal-confirm-title");
  ask.find((n) => n.tag === "button" && n.hasClass("primary")).click();
  await settle(80);
  assert.strictEqual(posts("/api/meetings/verify").length, 1);
  assert(text(h.dom().toastEl).includes("檢查失敗：" + reason), text(h.dom().toastEl));
  assert(!text(h.dom().toastEl).includes("Codex"), "not the translations' wording");
  assert.strictEqual(posts("/api/meetings/preview").length, 0, "nothing passed, so nothing is previewed again");
});

test("a preview without a version does not say Claude Code was not found: the reason is the server's blocker", async () => {
  // the server leaves the version out whenever the provider check fails (not found, not checked, storage): only its blocker says which
  setPage({ preview: previewOf({ startable: false, preview_id: null, cli: { version: null, verified: false },
    blockers: [{ code: "boundary_unverified", message: "這個 Claude Code 版本還沒通過無工具安全檢查，請先檢查" }] }) });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  const all = text(dialog());
  assert(!all.includes("找不到版本"), all.slice(0, 400));
  assert(all.includes("沒有讀到已通過無工具安全檢查的版本"), all.slice(0, 400));
  assert(all.includes("這個 Claude Code 版本還沒通過無工具安全檢查"), "the blocker itself is shown");
});

test("the preview opens at its top: the title has the keyboard, not the buttons below the full texts", async () => {
  // the first button is under every prompt: focusing it would scroll the blockers and the money out of view
  setPage({ preview: previewOf({ startable: false, preview_id: null, blockers: [{ code: "budget", message: "預留超過每日上限" }] }) });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  const title = dialog().find((n) => n.tag === "h2");
  assert.strictEqual(global.document.activeElement, title, "focus: " + (global.document.activeElement && global.document.activeElement.tag));
  assert.strictEqual(title.getAttribute("tabindex"), "-1", "reachable by script, not a Tab stop");
});

test("saying no to the tool-less check sends nothing", async () => {
  setPage({ preview: previewOf({ startable: false, preview_id: null, cli: { version: "2.1.999", verified: false },
    blockers: [{ code: "boundary_unverified", message: "這個 Claude Code 版本還沒通過無工具安全檢查，請先檢查" }] }) });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  FETCH_LOG.length = 0;
  q(dialog(), "verify").click();
  await settle();
  const ask = h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop") && n.getAttribute("aria-labelledby") === "modal-confirm-title");
  assert(ask, "a confirmation in the page");
  ask.find((n) => n.tag === "button" && !n.hasClass("primary")).click();
  await settle(80);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0);
});

test("a budget blocker is shown and cannot be started", async () => {
  setPage({ preview: previewOf({ startable: false, preview_id: null, blockers: [{ code: "budget", message: "預留 0.60 美元超過這場會議剩下的額度 0.40" }] }) });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  assert(text(dialog()).includes("預留 0.60 美元超過"));
  assert.strictEqual(q(dialog(), "start"), null);
});

test("a refused preview says what the server said and opens nothing", async () => {
  setPage({ preview: { code: "bad_request", error: "主席必須是 CEO 職位的角色卡" }, previewStatus: 400 });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  assert.strictEqual(dialog(), null);
  assert(text(h.dom().toastEl).includes("主席必須是 CEO 職位的角色卡"));
});

test("the form needs a topic, a chair and a speaker before it asks the server", async () => {
  setPage({ preview: previewOf() });
  const main = await open("#/meetings");
  fill(main, { topic: "  ", speakers: ["law"] });
  q(main, "preview").click();
  await settle();
  assert.strictEqual(posts("/api/meetings/preview").length, 0);
  fill(main, { speakers: [] });
  q(main, "preview").click();
  await settle();
  assert.strictEqual(posts("/api/meetings/preview").length, 0);
});

test("the task card entry opens the form with that card chosen", async () => {
  setPage();
  const main = await open("#/meetings?task=task-1");
  assert.strictEqual(q(main, "task").value, "task-1");
});

test("P35-4 a staffing proposal brings its staff: they are ticked in the form, the rest is the person's, nothing is sent", async () => {
  setPage();
  const main = await open("#/meetings?task=task-1&speakers=law,art,old,ceo,gone");
  const ticked = qa(main, "speaker").filter((b) => b.checked).map((b) => b.getAttribute("data-profile"));
  assert.deepStrictEqual(ticked, ["law", "art"]);
  const note = q(main, "speakers-note");
  assert(note && text(note).includes("組隊提案帶來的 5 位") && text(note).includes("3 位不在可以發言的清單裡"), text(note));
  assert.strictEqual(q(main, "topic").value, "", "the topic is the person's to write");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "no preview is asked by itself");
  const plain = await open("#/meetings?task=task-1");
  assert.deepStrictEqual(qa(plain, "speaker").filter((b) => b.checked).length, 0);
  assert.strictEqual(q(plain, "speakers-note"), null);
});

// ---- one meeting -------------------------------------------------------------------------------------------------

function detail(m) { page.details[m.id] = m; return m; }

test("one meeting: every turn with its words, evidence and cost, all as text", async () => {
  setPage();
  const m = detail(meeting({ task_id: "task-1", topic: "主題 " + EVIL }));
  m.turns[0].output = opinion({ summary: "摘要 " + EVIL, points: ["要點 " + EVIL], risks: [{ level: "中", text: "風險 " + EVIL, source: "個資法第 6 條" }] });
  m.turns[1].evidence = evidence({ cost_usd: "0.2000", cost_source: "worst_case", duration_ms: null, tools_reported: null, mcp_servers_reported: null });
  const main = await open("#/meetings/" + MID);
  const all = text(main);
  assert.strictEqual(main.findAll((n) => n.tag === "img").length, 0);
  assert(all.includes(EVIL));
  for (const piece of ["摘要", "要點", "風險", "個資法第 6 條", "先做草稿", "風險低", "法務的顧慮已處理", "寫三則貼文草稿", "下週的預算", "2.1.296", "claude-sonnet-x",
    "0.0412", "Claude Code 回報", "0.2000", "最壞情況", "0.1236"]) assert(all.includes(piece), piece);
  const seats = qa(main, "seat");
  assert.strictEqual(seats.length, 3);
  assert(text(seats[1]).includes("代發言"));
  // "this run checked: only StructuredOutput, no MCP" only where the record holds exactly that
  const checked = qa(main, "checked");
  assert.strictEqual(checked.length, 2, "the third person's record does not say what was checked");
  assert(text(checked[0]).includes("本次確認：只有 StructuredOutput、沒有 MCP"));
  const unchecked = text(seats[1]);
  assert(!unchecked.includes("本次確認：只有 StructuredOutput"), "no claim without the record");
  assert(unchecked.includes("沒有紀錄"), unchecked);
});

test("a failed speaker shows the reason and can be tried again after its own preview", async () => {
  setPage();
  const m = detail(meeting({ status: "waiting_chairman", major: true, retryable: [2], chairman: { state: "pending", at: null, note: "", label: "x" } }));
  m.turns[1] = turn(2, "art", "opinion", "failed", { error_code: "timeout", attempts: 1, evidence: null });
  page.retryPreview = { preview_id: "rp-1", startable: true, blockers: [], meeting_id: MID, seq: 2, participant: { ...people()[2], instructions: "指示" },
    prompt: "重試的 prompt " + EVIL, prompt_sha256: "e".repeat(64), calls: 2, reserve_usd: "0.40", decision_again: true, attempt: 2,
    today: { spent_usd: "0.5", daily_usd: "3.00", lamp: "green" }, cli: { version: "2.1.296", verified: true }, disclosure: "送到 Anthropic", cost_note: "估值" };
  const main = await open("#/meetings/" + MID);
  const seat = qa(main, "seat")[1];
  assert(text(seat).includes("失敗"));
  assert(text(seat).includes("逾時"), text(seat));
  assert.strictEqual(qa(main, "retry").length, 1);
  qa(main, "retry")[0].click();
  await settle();
  assert.deepStrictEqual(posts("/retry-preview")[0].body, { seq: 2 });
  assert(text(dialog()).includes("重試的 prompt"));
  assert(text(dialog()).includes("2 次呼叫") || text(dialog()).includes("CEO 會重問"), text(dialog()));
  q(dialog(), "start").click();
  await settle();
  assert.deepStrictEqual(posts("/retry")[0].body, { preview_id: "rp-1" });
});

test("a code the page does not know is shown as it is, never guessed", async () => {
  setPage();
  const m = detail(meeting({ status: "incomplete" }));
  m.turns[0] = turn(1, "law", "opinion", "failed", { error_code: "brand_new_code", evidence: null });
  const main = await open("#/meetings/" + MID);
  assert(text(qa(main, "seat")[0]).includes("brand_new_code"));
});

test("every code the back end ends a turn with has plain words; no cost is claimed that the record does not hold", async () => {
  // the codes are read from the back end's own source, so a new one there fails here until it has words
  const src = (f) => fs.readFileSync(path.join(__dirname, "..", "..", "vbear", f), "utf8");
  const codes = new Set(["invalid_output"]);   // meetings.OutputError's default
  const grab = (s, re) => { for (const m of s.matchAll(re)) codes.add(m[1]); };
  grab(src("headless_cli.py"), /HeadlessError\("([a-z_]+)"/g);
  const runner = src("meeting_runner.py") + src("board_engine.py");  // the engine under the runner ends the turns
  for (const re of [/HeadlessError\("([a-z_]+)"/g, /CallFailed\("([a-z_]+)"/g, /_end\(mid, [^,]+, "[a-z]+", "([a-z_]+)"/g, /\bcode = "([a-z_]+)"/g,
    /\bstop = "([a-z_]+)"/g, /error_code="([a-z_]+)"/g]) grab(runner, re);
  grab(src("meetings.py"), /OutputError\("([a-z_]+)"/g);
  for (const code of ["timeout", "cli_failed", "tools_not_clean", "not_traditional", "internal", "restart", "budget", "no_opinions"]) {
    assert(codes.has(code), "the scan finds " + code);
  }
  assert.strictEqual(typeof app.MEETING_ERROR_TEXT, "object");
  for (const code of codes) assert(Object.prototype.hasOwnProperty.call(app.MEETING_ERROR_TEXT, code), "no words for " + code);
  setPage();
  const m = detail(meeting({ status: "incomplete", major: true, chairman: { state: "pending", at: null, note: "", label: "x" } }));
  m.turns[0] = turn(1, "law", "opinion", "failed", { error_code: "not_traditional", evidence: evidence() });
  m.turns[1] = turn(2, "art", "opinion", "interrupted", { error_code: "restart", attempts: 0, evidence: null });
  m.turns[2] = turn(3, "ceo", "decision", "interrupted", { error_code: "restart", attempts: 0, evidence: null });
  const main = await open("#/meetings/" + MID);
  const seats = qa(main, "seat");
  assert(text(seats[0]).includes("簡體"), text(seats[0]));
  const reason = text(q(seats[1], "reason"));
  assert(reason.includes("主控台重新啟動"), reason);
  assert(!reason.includes("最壞情況"), "a turn that never ran is not said to be charged: " + reason);
});

test("once the chairman has decided, a failed speaker is not offered a retry, and the page says why", async () => {
  setPage();
  for (const state of ["approved", "rejected"]) {
    const m = detail(meeting({ status: state, major: true, retryable: [2], chairman: { state, at: 1790009999, note: "", label: "x" } }));
    m.turns[1] = turn(2, "art", "opinion", "failed", { error_code: "timeout", evidence: null });
    const main = await open("#/meetings/" + MID);
    assert.strictEqual(qa(main, "retry").length, 0, state);
    assert(text(qa(main, "seat")[1]).includes("董事長已經決定"), text(qa(main, "seat")[1]));
  }
});

test("the form goes by the position stored on the card (what the server checks), not a note kept only in this browser", async () => {
  setPage({ profiles: [cardOf("ceo", "執行長卡", "planner"), cardOf("law", "法務卡", "legal"), cardOf("old-pm", "舊位置的 PM", "records"),
    { id: "note-ceo", name: "只有備註的 CEO", enabled: true, model: { tool: "claude", model_id: "" } },
    { id: "note-pm", name: "只有備註的 PM", enabled: true, model: { tool: "claude", model_id: "" } }] });
  app.setCardPosition("note-ceo", "planner");
  app.setCardPosition("note-pm", "pm");
  try {
    const main = await open("#/meetings");
    const chairOptions = q(main, "chair").findAll((n) => n.tag === "option").map((n) => n.getAttribute("value"));
    assert.deepStrictEqual(chairOptions, ["ceo"], "a card whose CEO position is only a browser note cannot chair: the server would refuse it");
    assert.deepStrictEqual(qa(main, "speaker").map((s) => s.getAttribute("data-profile")).sort(), ["law", "old-pm"],
      "a retired id counts as its successor, as on the server");
    const note = q(main, "note-only");
    assert(note, "the page says why two cards are missing");
    assert(text(note).includes("2 張") && text(note).includes("這個瀏覽器"), text(note));
  } finally {
    app.setCardPosition("note-ceo", null);
    app.setCardPosition("note-pm", null);
  }
});

test("the chairman's desk: approve or reject with a note, marked as an unverified console record", async () => {
  setPage();
  detail(meeting({ status: "waiting_chairman", major: true, rules: [{ id: "R3", text: "出現關鍵字" }],
    chairman: { state: "pending", at: null, note: "", label: "主控台記錄（未驗證身分）" } }));
  const main = await open("#/meetings/" + MID);
  const desk = q(main, "chairman");
  assert(desk);
  assert(text(desk).includes("輪到你：董事長核准"));
  assert(text(desk).includes("主控台記錄（未驗證身分）"));
  assert(text(desk).includes("R3") && text(desk).includes("出現關鍵字"), "why it came to the chairman");
  assert(q(main, "approve") && q(main, "reject"));
  q(main, "chairman-note").value = "同意，但先小量";
  page.details[MID] = meeting({ status: "approved", major: true, chairman: { state: "approved", at: 1790009999, note: "同意，但先小量", label: "主控台記錄（未驗證身分）" } });
  q(main, "approve").click();
  await settle();
  const sent = posts("/chairman");
  assert.strictEqual(sent.length, 1);
  assert.deepStrictEqual(sent[0].body, { decision: "approve", note: "同意，但先小量" });
  assert(text(h.dom().mainEl).includes("董事長已核准"));
});

test("a decision that needs no approval says 'the CEO has decided' and the chairman can still reject it", async () => {
  setPage();
  detail(meeting());
  const main = await open("#/meetings/" + MID);
  assert(text(main).includes("CEO 已決定"));
  assert.strictEqual(q(main, "approve"), null, "nothing to approve");
  const reject = q(main, "reject");
  assert(reject);
  page.details[MID] = meeting({ status: "rejected", chairman: { state: "rejected", at: 1, note: "", label: "主控台記錄（未驗證身分）" } });
  reject.click();
  await settle();
  assert.deepStrictEqual(posts("/chairman")[0].body, { decision: "reject", note: "" });
  assert(text(h.dom().mainEl).includes("董事長已否決"));
});

test("a running meeting can be cancelled and is read again; nothing can be decided meanwhile", async () => {
  setPage();
  const m = detail(meeting({ status: "running" }));
  m.turns[2] = turn(3, "ceo", "decision", "queued");
  m.turns[1] = turn(2, "art", "opinion", "running");
  m.chairman = { state: "pending", at: null, note: "", label: "x" };
  const main = await open("#/meetings/" + MID);
  assert(q(main, "cancel"));
  assert.strictEqual(q(main, "approve"), null);
  assert.strictEqual(q(main, "reject"), null);
  assert.strictEqual(q(main, "delete"), null, "a running meeting is not deleted");
  assert(typeof page.tick === "function", "a running meeting is refreshed by itself");
  q(main, "cancel").click();
  await settle();
  assert.strictEqual(posts("/cancel").length, 1);
});

test("write into the task card: offered only for a decision that may go in; it opens the card with the note, saving is the person's", async () => {
  setPage();
  detail(meeting({ task_id: "task-1" }));
  const main = await open("#/meetings/" + MID);
  const write = q(main, "write-task");
  assert(write, "offered");
  FETCH_LOG.length = 0;
  write.click();
  assert.strictEqual(global.location.hash, "#/workbench?task=task-1&meeting=" + MID);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0, "nothing is written by the click");
  // waiting for the chairman: the offer is a sentence, not a button
  detail(meeting({ id: MID2, status: "waiting_chairman", major: true, task_id: "task-1" }));
  const main2 = await open("#/meetings/" + MID2);
  assert.strictEqual(q(main2, "write-task"), null);
  assert(text(q(main2, "write-task-why")).includes("董事長"));
});

test("a meeting without a task card lets the person pick one first", async () => {
  setPage({ tasks: [task(), task({ id: "task-2", title: "另一張" })] });
  detail(meeting());
  const main = await open("#/meetings/" + MID);
  const pick = q(main, "write-task-pick");
  assert(pick, "a picker of task cards");
  assert.strictEqual(q(main, "write-task").disabled, true, "no card picked yet");
  pick.value = "task-2";
  pick.dispatch("change");
  assert.strictEqual(q(main, "write-task").disabled, false);
  q(main, "write-task").click();
  assert.strictEqual(global.location.hash, "#/workbench?task=task-2&meeting=" + MID);
});

test("the follow-up topics only fill the form; a meeting is never opened by itself", async () => {
  setPage();
  detail(meeting());
  const main = await open("#/meetings/" + MID);
  const follow = qa(main, "follow-up");
  assert.strictEqual(follow.length, 1);
  FETCH_LOG.length = 0;
  follow[0].click();
  assert(global.location.hash.startsWith("#/meetings?"), global.location.hash);
  assert(decodeURIComponent(global.location.hash).includes("下週的預算"));
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST").length, 0);
  const main2 = await open(global.location.hash);
  assert.strictEqual(q(main2, "topic").value, "下週的預算");
});

test("deleting a meeting asks first", async () => {
  setPage();
  detail(meeting());
  const main = await open("#/meetings/" + MID);
  q(main, "delete").click();
  await settle();
  assert(dialog(), "a confirmation");
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "DELETE").length, 0);
});

test("a meeting that cannot be read says so", async () => {
  setPage();
  const main = await open("#/meetings/" + MID);
  assert(text(main).includes("找不到這場會議"));
});

// ---- the task card and the workbench -----------------------------------------------------------------------------

test("a task card in the lobby links to a meeting about it", () => {
  const node = app.taskFrontCard(task(), { flows: [], profiles: [], tasks: [task()] });
  const link = node.find((n) => n.tag === "a" && n.getAttribute("href") === "#/meetings?task=task-1");
  assert(link, "開會討論");
  assert(text(link).includes("開會討論"));
});

test("the workbench's task tab lists the meetings of that card and opens the editor with the note", async () => {
  setPage({ meetings: [meeting({ task_id: "task-1", topic: "這張卡的會議 " + EVIL }), meeting({ id: MID2, task_id: "task-9", topic: "別張卡" })].map(summary) });
  detail(meeting({ task_id: "task-1" }));
  const main = await open("#/workbench?task=task-1");
  const block = q(main, "task-meetings");
  assert(block, "related meetings");
  assert(text(block).includes("這張卡的會議") && !text(block).includes("別張卡"));
  assert(text(block).includes(EVIL));
  assert(block.find((n) => n.tag === "a" && n.getAttribute("href") === "#/meetings?task=task-1"), "a new meeting about it");
  // arriving from a meeting: the editor opens with the note in the goal, and nothing is saved
  FETCH_LOG.length = 0;
  const main2 = await open("#/workbench?task=task-1&meeting=" + MID);
  const edit = dialog();
  assert(edit, "the editor is open");
  const goal = edit.findAll((n) => n.tag === "textarea")[0];
  assert(goal.textContent.includes("寫貼文"), "the old goal stays");
  assert(goal.textContent.includes("先做草稿") && goal.textContent.includes(MID), goal.textContent);
  assert.strictEqual(FETCH_LOG.filter((c) => c.method === "POST" && c.url.startsWith("/api/tasks")).length, 0, "saving is the person's");
});

test("arriving with a meeting that may not go in opens nothing", async () => {
  setPage();
  detail(meeting({ task_id: "task-1", status: "waiting_chairman", major: true }));
  await open("#/workbench?task=task-1&meeting=" + MID);
  assert.strictEqual(dialog(), null);
  assert(text(h.dom().toastEl).includes("董事長"), "the toast says why: " + text(h.dom().toastEl));
});

// ---- the office --------------------------------------------------------------------------------------------------

test("the office's meeting room: seats with bubbles from the record, the chairman's desk, a link for the rest", async () => {
  const run = meeting({ id: MID, status: "running", topic: "進行中 " + EVIL });
  run.turns[2] = turn(3, "ceo", "decision", "queued");
  run.turns[1] = turn(2, "art", "opinion", "running");
  const wait = meeting({ id: MID2, status: "waiting_chairman", major: true, created_at: 1 });
  setPage({ meetings: [run, wait].map(summary) });
  detail(run); detail(wait);
  const main = await open("#/office");
  const room = main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "meeting-room");
  assert(room, "a meeting room");
  assert.strictEqual(text(room.find((n) => n.tag === "h2")), "會議室");
  const seats = byClass(room, "mt-seat");
  assert.strictEqual(seats.length, 3);
  assert.deepStrictEqual(seats.map((s) => text(byClass(s, "mt-bubble")[0])), ["支持", "發言中", "等發言"]);
  assert(seats.every((s) => (s.getAttribute("aria-label") || "").includes("依據：會議紀錄 " + MID)));
  assert(text(room).includes(EVIL));
  assert.strictEqual(room.findAll((n) => n.tag === "img").length, 0);
  const desk = q(room, "chairman-desk");
  assert(desk);
  assert(text(desk).includes("1"), "one waits for the chairman");
  assert(desk.find((n) => n.tag === "a" && n.getAttribute("href") === "#/meetings/" + MID2));
  assert(text(room).includes("還有 1 場"));
  const heads = main.findAll((n) => n.tag === "h2").map(text);
  assert.deepStrictEqual(heads.slice(0, 4), ["工作站", "辦公桌", "會議室", "休息室"]);
});

test("the office says so when the meetings could not be read, and when there are none", async () => {
  setPage();
  page.meetings = [];
  let main = await open("#/office");
  const room = main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "meeting-room");
  assert(text(room).includes("目前沒有進行中或等你核准的會議"));
  assert(room.find((n) => n.tag === "a" && n.getAttribute("href") === "#/meetings"));
  setHandler((url) => (url.split("?")[0] === "/api/meetings" ? jsonResponse({ error: "壞了" }, false, 500) : null));
  main = await open("#/office");
  const room2 = main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "meeting-room");
  assert(text(room2).includes("讀不到會議"), text(room2));
});

test("an office with no card, flow or terminal still shows a meeting that waits for the chairman", async () => {
  // P34-5 r1: the empty state used to replace the whole office, the meeting room with it
  const wait = meeting({ id: MID2, status: "waiting_chairman", major: true });
  setPage({ profiles: [], meetings: [summary(wait)] });
  detail(wait);
  let main = await open("#/office");
  assert(text(main).includes("名冊上沒有角色卡，也沒有流程或終端"), text(main).slice(0, 400));
  assert(!text(main).includes("辦公室目前沒有人"), "people still sit in the meeting room");
  const room = main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "meeting-room");
  assert(room, "the meeting room is kept");
  const desk = q(room, "chairman-desk");
  assert(desk && desk.find((n) => n.tag === "a" && n.getAttribute("href") === "#/meetings/" + MID2));
  assert.strictEqual(byClass(room, "mt-seat").length, 3, "the seats come from the record, not from the roster");
  // meetings that cannot be read are not claimed to be none
  setPage({ profiles: [], meetingsError: "壞了" });
  main = await open("#/office");
  assert(text(main).includes("名冊上沒有角色卡，也沒有流程或終端"), "the empty branch: " + text(main).slice(0, 400));
  assert(!text(main).includes("辦公室目前沒有人"));
  const unread = main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "meeting-room");
  assert(unread && text(unread).includes("讀不到會議"), text(main).slice(0, 400));
  // with no meeting either, it is the plain empty state
  setPage({ profiles: [], meetings: [] });
  main = await open("#/office");
  assert(text(main).includes("辦公室目前沒有人。到終端工作台建立角色。"));
  assert.strictEqual(main.find((n) => n.getAttribute && n.getAttribute("data-office-section") === "meeting-room"), null);
});

test("a meeting joining or changing repaints the office (it is in the repaint key)", () => {
  const a = app.meetingRoomModel({ meetings: [summary(meeting({ status: "running" }))] }, meeting({ status: "running" }));
  const b = app.meetingRoomModel({ meetings: [summary(meeting({ status: "running" }))] }, (() => { const m = meeting({ status: "running" }); m.turns[0].state = "failed"; return m; })());
  assert.notStrictEqual(app.meetingRoomKey(a), app.meetingRoomKey(b));
  assert.strictEqual(app.meetingRoomKey(a), app.meetingRoomKey(clone(a)));
});

// ---- P35-3: how fast a meeting is, and why it costs money (the chairman's decisions 7 and 8) -------------------------

const speedOf = (over = {}) => ({ speaker_effort: "low", chair_effort: "medium", max_minutes: 15, chair_reserve_minutes: 3,
  labels: { speaker_effort: "低", chair_effort: "中" }, note: "伺服器的說明", ...over });

test("the preview says the effort is low or medium only, each person's effort, and the time the meeting has", async () => {
  const pv = previewOf({ speed: speedOf() });
  pv.participants = pv.participants.map((p) => ({ ...p, effort: "low" }));
  pv.chair = { ...pv.chair, effort: "medium" };
  setPage({ preview: pv });
  const main = await open("#/meetings");
  fill(main, { speakers: ["law", "art"] });
  q(main, "preview").click();
  await settle();
  const dlg = dialog();
  const speed = q(dlg, "speed");
  assert(speed, "a line on the speed");
  for (const piece of ["思考強度：低／中（會議為了快，不提供高）", "發言者低", "CEO 中", "最多 15 分鐘", "最後 3 分鐘留給 CEO"]) {
    assert(text(speed).includes(piece), piece + " | " + text(speed));
  }
  const efforts = qa(dlg, "effort").map(text);
  assert.deepStrictEqual(efforts, ["思考強度 低", "思考強度 低", "思考強度 中"]);
  // a value the page does not know is not shown as one it does
  const odd = previewOf({ speed: speedOf({ speaker_effort: "high", labels: { speaker_effort: "高", chair_effort: "中" } }) });
  odd.participants = odd.participants.map((p) => ({ ...p, effort: "high" }));
  page.preview = odd;
  dlg.remove();
  q(main, "preview").click();
  await settle();
  const again = dialog();
  assert(!text(again).includes("思考強度 高") && !text(q(again, "speed")).includes("發言者高"), text(again));
  assert(text(q(again, "speed")).includes("未知"), text(q(again, "speed")));
});

test("a preview from a server that sends no speed claims none", async () => {
  setPage({ preview: previewOf() });
  const main = await open("#/meetings");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  assert.strictEqual(q(dialog(), "speed"), null);
  assert.strictEqual(qa(dialog(), "effort").length, 0);
});

test("why a meeting costs money is said where the money is: an estimate from the tokens; a subscription uses its quota", async () => {
  assert.strictEqual(typeof app.MEETING_MONEY_WHY, "string");
  for (const piece of ["Claude Code", "token", "估值", "訂閱", "使用額度", "不是另外扣款"]) assert(app.MEETING_MONEY_WHY.includes(piece), piece);
  setPage({ preview: previewOf() });
  let main = await open("#/meetings");
  assert(text(q(main, "money-why")).includes("不是另外扣款"), "on the meetings page");
  fill(main, {});
  q(main, "preview").click();
  await settle();
  assert(text(q(dialog(), "money-why")).includes("不是另外扣款"), "in the preview");
  dialog().remove();
  detail(meeting());
  main = await open("#/meetings/" + MID);
  assert(text(q(main, "money-why")).includes("不是另外扣款"), "on a meeting");
});

test("a running meeting shows the time left by the console's clock, and the speakers' share of it", async () => {
  assert.strictEqual(typeof app.meetingClockText, "function");
  const clock = { started_at: 1790000000, deadline_at: 1790000900, speakers_until: 1790000720, max_minutes: 15, remaining_s: 600.4 };
  const words = app.meetingClockText(clock);
  for (const piece of ["剩下 10 分 00 秒", "最多 15 分鐘", "最後 3 分鐘留給 CEO", "發言者還有 7 分 00 秒", "主控台"]) assert(words.includes(piece), piece + " | " + words);
  const late = app.meetingClockText({ ...clock, remaining_s: 100 });
  assert(late.includes("剩下 1 分 40 秒") && late.includes("發言時間已到"), late);
  for (const bad of [null, {}, { ...clock, remaining_s: "600" }, { ...clock, max_minutes: 15.5 }, { ...clock, deadline_at: null }]) {
    assert.strictEqual(app.meetingClockText(bad), null, JSON.stringify(bad));
  }
  setPage();
  const m = detail(meeting({ status: "running", clock }));
  m.turns[2] = turn(3, "ceo", "decision", "queued");
  const main = await open("#/meetings/" + MID);
  assert(text(q(main, "clock")).includes("剩下 10 分 00 秒"), text(main));
  detail(meeting());
  const done = await open("#/meetings/" + MID);
  assert.strictEqual(q(done, "clock"), null, "a meeting that is not running here has no clock");
});

test("a speaker the meeting's clock skipped reads 時間到沒發言", () => {
  assert(app.MEETING_BUBBLES.includes("時間到沒發言"));
  assert.strictEqual(app.meetingBubble(turn(1, "law", "opinion", "skipped", { error_code: "time_up" }), {}), "時間到沒發言");
  // the CEO's turn the clock stopped is a failure that may be retried, not "did not speak"
  assert.strictEqual(app.meetingBubble(turn(3, "ceo", "decision", "failed", { error_code: "time_up" }), {}), "失敗");
});

// ---- navigation, wording, rules of the code -------------------------------------------------------------------------

test("the nav has the meetings, and the code keeps its rules", () => {
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  assert(html.includes('data-nav="meetings"'));
  assert(html.indexOf('data-nav="office"') < html.indexOf('data-nav="meetings"') && html.indexOf('data-nav="meetings"') < html.indexOf('data-nav="terminals"'));
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(source));
  assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u.test(fs.readFileSync(path.join(root, "style.css"), "utf8")));
  const css = fs.readFileSync(path.join(root, "style.css"), "utf8");
  assert(css.includes(".mt-seat") && css.includes(".mt-bubble"));
  assert(/prefers-reduced-motion/.test(css));
});

test("the tool-less check button says what it is", () => {
  const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert(source.includes("無工具安全檢查"));
});

// ---- run ---------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
