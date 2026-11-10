// P47-5 (v0.21.0, ADR 0013): the sweep of the words. Every word the table `WORDS` says to stop saying (`wordsToAvoid("all")`) is gone from the
// pages a person sees in the normal mode, and the advanced pages changed their titles (`wordsToAvoid("title")`) and nothing else.
// Two looks at the same thing:
//   1. the source: every string of web/app.js (comments are not strings) and the text of web/index.html is read, and the strings of the
//      functions that draw a normal page must not hold a word to avoid. The functions of the advanced pages (指令視窗, 工作台, 流程, 專案資料夾,
//      AI 工具的外掛清單, 員工詳細資料, 組隊會議) and of the office (the one page that keeps the game's words) are listed by name below, each
//      with the reason; a name that is no longer a function of app.js fails (so a rename cannot switch the look off silently).
//   2. the screen: the pages are drawn in the normal mode against a synthetic DOM and a fetch stub, their words are collected (the text of the
//      page, the hover text and labels, the dialogs that open), and none of them holds a word to avoid. The advanced pages are drawn too, and
//      their title is the new one.
// Not a browser test; nothing here runs a model, opens a browser or reaches a network.
//
// Run: node tests/frontend/p47_sweep.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;

const ROOT = path.join(__dirname, "..", "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const HTML = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log(`ok   - ${name}`); }
  catch (e) { console.log(`FAIL - ${name}`); console.log(e && e.stack || e); process.exitCode = 1; }
}

// ---- the words ------------------------------------------------------------------------------------------------------

const AVOID = app.wordsToAvoid("all");
const AVOID_TITLE = app.wordsToAvoid("title");

// Each word is looked for as it is written, except where the same letters sit inside another word that is fine:
//  - 用技能 (the button 「用技能」 became 「用常用做法」) is also inside 可用技能 and 使用技能, which are the plain words for the plugins of an AI tool;
//  - the English names of the tools (Bash, Edit, Write, Read, Grep, Glob) are looked for as whole English words (Global is not Glob);
//  - 沙盒 is fine in 保護範圍（沙盒）: the first time a person meets the word, the new word comes with the old one in brackets (the plan, the glossary).
const OWN_REGEX = {
  "用技能": /(?<![可使])用技能/,
};
function termRegex(term) {
  if (OWN_REGEX[term]) return OWN_REGEX[term];
  if (/^[A-Za-z_ ]+$/.test(term)) return new RegExp(`(?<![A-Za-z_])${term}(?![A-Za-z_])`);
  return new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
}
function foldAllowed(s) { return s.replace(/保護範圍（沙盒）/g, "保護範圍"); }
function hits(s, list = AVOID) {
  const t = foldAllowed(String(s));
  return list.filter((w) => termRegex(w.term).test(t)).map((w) => w.term);
}

// ---- the tokenizer: the strings of the source, with the line each starts on (comments and regular expressions are skipped) --------------------

function literals(src) {
  const out = [];
  const n = src.length;
  let i = 0, line = 1, prev = "";
  const regexOK = () => prev === "" || /[(,=:[!&|?{};+\-*%<>~^]$/.test(prev) || /(?:return|typeof|case|in|of)$/.test(prev);
  function str(j) {
    const q = src[j]; const L = line; let k = j + 1, buf = "";
    while (k < n && src[k] !== q) { if (src[k] === "\\") { buf += src[k + 1]; k += 2; continue; } buf += src[k]; k++; }
    out.push({ text: buf, line: L });
    return k + 1;
  }
  function tpl(j) {
    let k = j, buf = "", L = line;
    while (k < n) {
      const c = src[k];
      if (c === "\\") { buf += src[k + 1]; if (src[k + 1] === "\n") line++; k += 2; continue; }
      if (c === "`") { out.push({ text: buf, line: L }); return k + 1; }
      if (c === "$" && src[k + 1] === "{") { out.push({ text: buf, line: L }); buf = ""; k = expr(k + 2); L = line; continue; }
      if (c === "\n") line++;
      buf += c; k++;
    }
    return k;
  }
  function expr(j) {
    let depth = 1;
    while (j < n) {
      const c = src[j];
      if (c === "\n") { line++; j++; continue; }
      if (c === "{") { depth++; j++; continue; }
      if (c === "}") { depth--; j++; if (depth === 0) return j; continue; }
      if (c === "'" || c === '"') { j = str(j); continue; }
      if (c === "`") { j = tpl(j + 1); continue; }
      if (c === "/" && src[j + 1] === "/") { while (j < n && src[j] !== "\n") j++; continue; }
      if (c === "/" && src[j + 1] === "*") { const e = src.indexOf("*/", j + 2); for (let k = j; k < e; k++) if (src[k] === "\n") line++; j = e + 2; continue; }
      j++;
    }
    return j;
  }
  while (i < n) {
    const c = src[i];
    if (c === "\n") { line++; i++; continue; }
    if (c === "/" && src[i + 1] === "/") { while (i < n && src[i] !== "\n") i++; continue; }
    if (c === "/" && src[i + 1] === "*") { const e = src.indexOf("*/", i + 2); for (let k = i; k < e; k++) if (src[k] === "\n") line++; i = e + 2; continue; }
    if (c === "'" || c === '"') { i = str(i); prev = "s"; continue; }
    if (c === "`") { i = tpl(i + 1); prev = "s"; continue; }
    if (c === "/" && regexOK()) {
      let k = i + 1, cls = false;
      while (k < n) { const d = src[k]; if (d === "\\") { k += 2; continue; } if (d === "[") cls = true; else if (d === "]") cls = false; else if (d === "/" && !cls) break; else if (d === "\n") break; k++; }
      i = k + 1; while (/[a-z]/.test(src[i] || "")) i++;
      prev = "r"; continue;
    }
    if (!/\s/.test(c)) prev = (prev + c).slice(-8);
    i++;
  }
  return out;
}

// the top-level function or constant a line belongs to (a declaration that starts in column 0)
function ownerTable(src) {
  const tops = [];
  src.split("\n").forEach((l, ix) => {
    const m = /^(?:async )?function\*? ?([A-Za-z0-9_$]+)|^(?:const|let|var) ([A-Za-z0-9_$]+) =/.exec(l);
    if (m) tops.push([ix + 1, m[1] || m[2]]);
  });
  return (ln) => { let o = "?"; for (const [l, nm] of tops) { if (l <= ln) o = nm; else break; } return o; };
}

// ---- who may keep the old words ------------------------------------------------------------------------------------------------------------

// The table of the words and the table of the sentences that are turned into plain words say the old words on purpose.
const WORD_TABLES = ["WORDS", "PLAIN_ERRORS"];

// A page of the advanced part changes its menu name and its title and nothing else this version (plan, decision 9; ADR 0013); the office keeps
// the game's words (ceo-plan: "遊戲說法只留在辦公室頁"). Every function that draws only such a page, and the constants only they use, is here.
const ADVANCED_OWNERS = {
  "指令視窗 (#/terminals, #/term)": ["linkLaunchedTerminal", "takeoverReminderLines", "TERMINAL_WORDS", "TERM_GENERAL", "SHELL_NOTE",
    "viewTerminals", "TERM_BACK_ROLE_LABEL", "TERM_BACK_TASK_LABEL", "viewTerminal", "rolePasteControl", "TASK_STATUS_LABELS", "TASK_STATUS_EXPLAIN",
    "PICKUP_EXPLAIN", "handoffReminder"],
  "工作台 (#/workbench)": ["viewWorkbench", "TEAM_SLOTS", "SLOT_REVIEW_NEEDS_DIFF", "TEAM_INFO", "slotProblem", "nextStepActionNode", "NEXT_APPROVE_RECORD_ASK",
    "nextStepYourTurn", "teamBoard", "teamSection", "openPlaceDialog", "NO_TERMINAL_TEXT", "TRACKING_NOTE", "TRACKING_RESTART_NOTE", "NO_GIT_NOTE",
    "FOLDER_TERMINAL_NOTE", "folderFacts", "openImportProject", "taskFolderBlock", "taskFrontCard", "taskCardsSection"],
  "流程 (#/flows)": ["flowRoleToolText", "flowCard", "flowNotice", "viewFlows", "FLOW_SOURCE_TITLES", "flowAutomationDetail", "viewFlowDetail",
    "S2_REVIEW_OUTCOME", "S2_SESSION_STATE", "s2InstructionsNote", "openAcceptanceDialog", "s2AutomationPanel", "s2ExecutorPanel", "s2DispatchComposer",
    "s2ReportsPanel", "s2ReviewsPanel", "mountStorage", "mountCoordinator"],
  "專案資料夾 (#/projects)": ["viewProjects", "projectDetail", "projectCard", "sessionCard"],
  "AI 工具的外掛清單 (#/skills, #/armory)": ["PROV", "viewSkills", "viewArmory", "viewSkillDetail", "annotationPanel", "openSkillCard", "roleCard"],
  "員工詳細資料 (#/team)": ["viewTeam", "viewRole", "profileCard"],
  "組隊會議 (#/staffing)": ["STAFFING_FLAG_TEXT", "staffingPreviewFacts", "staffingForm", "viewStaffing", "staffingProposalNode", "STAFFING_DRAFT_NOTE",
    "STAFFING_SWAP_NOTE", "staffingAdoptPlan", "staffingAdoptSection", "viewStaffingDetail", "staffingTaskTitle", "staffingListNode", "taskStaffingBlock",
    "taskMeetingsBlock"],
  "辦公室 (#/office): 遊戲說法只留在這一頁": ["OFFICE_TOOLS_MISSING", "personaSpeech", "officeModel", "officeIndex", "officeTeamTitle", "officeProfileLabel",
    "officeDeskButton", "officeGear", "officeStageScreen", "officePanelContent", "officeCountsBar", "officeSections", "officeRows", "officeListView",
    "readProfiles", "viewOffice"],
};
const ADVANCED = new Map();
for (const [why, names] of Object.entries(ADVANCED_OWNERS)) for (const nm of names) ADVANCED.set(nm, why);

// A sentence that has to keep a word to avoid, written down one by one: the function it is in, the word, a part of the sentence, and why.
const EXCEPTIONS = [
  { owner: "runtimeNotice", term: "VBear runtime", part: "無法連線到 VBear runtime",
    why: "the sentence PLAIN_ERRORS knows (runtime_down): notice() turns it into plain words and keeps this one whole in 「技術細節」; changing it would switch that off" },
  { owner: "CARD_POSITION_TABLE", term: "陣營", part: "不同陣營的模型檢查程式",
    why: "the table mirrors the back end's POSITION_TABLE word for word (test_p34_positions holds the two together; Python is not changed here); cardDutyText says 「AI 工具」 when the sentence is drawn" },
  { owner: "cardDutyText", term: "陣營", part: "不同陣營的模型",
    why: "the one word it swaps: the sentence it receives is the back end's, which still says 陣營" },
  { owner: "passSummary", term: "Write", part: "Write",
    why: "the server's own name of a guard (levelOf looks it up in the pass); it is a key, never drawn" },
  { owner: "cardPassLine", term: "Write", part: "Write",
    why: "the server's own name of a guard (level looks it up in the pass); it is a key, never drawn" },
];

const hasFn = (name) => new RegExp(`^(?:async )?function\\*? ?${name}\\b|^(?:const|let|var) ${name} =`, "m").test(SOURCE);

// ---- rendering ------------------------------------------------------------------------------------------------------------------------

const wordsOfTree = (root) => {
  const out = [];
  const visit = (n) => {
    if (!n || typeof n !== "object") return;
    if (n.tag === "#text") { out.push(n._text || ""); return; }
    for (const k of ["title", "aria-label", "placeholder", "alt", "aria-description"]) { const v = n.getAttribute && n.getAttribute(k); if (v) out.push(v); }
    if (n.tag === "input" || n.tag === "textarea") { if (n.value) out.push(String(n.value)); }
    for (const c of n.children || []) visit(c);
  };
  visit(root);
  return out.join("\n");
};

(async () => {
  // ---- the source ----------------------------------------------------------------------------------------------------------------------
  await test("the functions of the advanced pages named here are still functions of app.js", () => {
    const missing = [...ADVANCED.keys()].filter((nm) => !hasFn(nm));
    assert.deepStrictEqual(missing, [], `renamed or gone: ${missing.join(", ")}`);
  });

  await test("the table has words to avoid for the normal pages and for the titles", () => {
    assert.ok(AVOID.length >= 40, `${AVOID.length} words to avoid`);
    assert.ok(AVOID_TITLE.length >= 4, `${AVOID_TITLE.length} words to avoid in a title`);
    assert.ok(AVOID.some((w) => w.term === "角色卡") && AVOID.some((w) => w.term === "派工") && AVOID.some((w) => w.term === "任務卡"));
  });

  await test("source: no string that a normal page can say holds a word to avoid", () => {
    const owner = ownerTable(SOURCE);
    const bad = [];
    for (const lit of literals(SOURCE)) {
      const o = owner(lit.line);
      if (WORD_TABLES.includes(o) || ADVANCED.has(o)) continue;
      const found = hits(lit.text);
      if (!found.length) continue;
      if (EXCEPTIONS.some((e) => e.owner === o && found.includes(e.term) && lit.text.includes(e.part))) continue;
      bad.push(`${lit.line} ${o} [${found.join(",")}] ${lit.text.slice(0, 70).replace(/\n/g, " ")}`);
    }
    assert.deepStrictEqual(bad, [], `${bad.length} strings still say an old word:\n${bad.join("\n")}`);
  });

  await test("source: the menu and the page shell (index.html) say none of the old words", () => {
    const visible = HTML.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<style[\s\S]*?<\/style>/g, "").replace(/<[^>]*>/g, "\n");
    assert.deepStrictEqual(hits(visible).concat(hits(visible, AVOID_TITLE)), []);
  });

  await test("source: the exceptions each give a reason and still match something", () => {
    for (const e of EXCEPTIONS) {
      assert.ok(e.owner && e.term && e.part && e.why, `an exception is complete: ${JSON.stringify(e)}`);
      assert.ok(literals(SOURCE).some((l) => l.text.includes(e.part)), `still there: ${e.part}`);
    }
  });

  // ---- the screen ---------------------------------------------------------------------------------------------------------------------
  // One stub answers every read of the pages with a small, ordinary company (two employees, one chat, one routine, one skill...). A route
  // the stub does not know answers an empty list, which is what a new person sees. The pages are drawn in the normal mode (advanced_mode off).
  const CID = "c-0123456789abcdef";
  const EMP = [
    { id: "emp-1", name: "虛構 CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true,
      permission_mode: "safe", species: "fox", skills: [], model: "" },
    { id: "emp-2", name: "虛構工程師", position: "executor", tool: "codex", engine: "codex-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false,
      permission_mode: "full", species: "cat", skills: [], model: "" },
  ];
  const ROUTINES_VIEW = { routines: [{ id: "r-0123456789ab", name: "市集日報", profile_id: "emp-1", text: "請整理昨天的銷售。", days: [0, 1, 2, 3, 4], times: ["08:00"], enabled: true,
      enabled_at: 1, created_at: 1, updated_at: 1, profile_name: "虛構 CEO", can_chat: true, next: { slot: "2026-11-09T08:00", at: 1794000000 }, per_run_usd: "0.50", runs: [] }],
    readable: true, problem: null, waiting: [], cards: [{ id: "emp-1", name: "虛構 CEO", can_chat: true, reason: null }],
    settings: { daily_usd: "1.50", daily_usd_set: null, default_usd: "1.50", keep_awake: false, problem: null },
    today: { routine_spent_usd: "0.20", routine_limit_usd: "1.50", day_usd: "3.00", day_left_usd: "2.50", lamp: "green" },
    autonomy: { routines: { enabled: false } }, limits: { per_turn_usd: "0.50", max_routines: 20, max_enabled: 10 } };
  const support = { detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" }, verify: { running: false }, money: "x" };
  const chatList = { ok: true, chats: [{ id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat", title: "第一次聊天", last_at: 1790000100 }], more: 0, cards: EMP, support, limits: { per_turn_usd: "0.5", daily_usd: "3" },
    ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: ["meetings", "staffing", "chats"] }, ledger_error: null, problems: [], scratch: "" };
  const chatDetail = { ok: true, chat: { id: CID, profile_id: "emp-1", created_at: 1790000000, engine: "claude-chat" }, card: EMP[0], records: [], live: null,
    runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null };
  function serve(over = {}) {
    app.D.overview = null; app.D.skills = null; app.D.roles = null;
    FETCH_LOG.length = 0;
    setHandler((url, opts) => {
      const p = url.split("?")[0];
      const method = (opts && opts.method) || "GET";
      if (over[p]) { const r = over[p](method, opts); if (r) return r; }
      if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false }, state_dir: "/x", runtime_socket: "" });
      if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [], sources: [] });
      if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
      if (p === "/api/roles") return jsonResponse({ roles: [] });
      if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
      if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: EMP });
      if (p === "/api/routines" && method === "GET") return jsonResponse(ROUTINES_VIEW);
      if (p === "/api/my-skills" && method === "GET") return jsonResponse({ ok: true, readable: true, problem: null, used: { count: 1 }, limits: { max_skills: 100, max_name: 40, max_text: 4000 },
        skills: [{ id: "k-0123456789ab", name: "市集日報", text: "請整理昨天的銷售。", source: { how: "typed" }, created_at: 1790000000, updated_at: 1790000000 }] });
      if (p === "/api/meetings/ledger") return jsonResponse({ ok: true, spent_usd: "0.29", daily_usd: "3", lamp: "green", blocked: false });
      if (p === "/api/chats" && method === "GET") return jsonResponse(chatList);
      if (p === `/api/chats/${CID}` && method === "GET") return jsonResponse(chatDetail);
      if (p === `/api/chats/${CID}/stream`) return { ok: true, status: 200, headers: { get: () => "text/event-stream" }, body: { getReader: () => ({ read: () => new Promise(() => {}) }) } };
      return jsonResponse({ ok: true, items: [], list: [], flows: [], tasks: [], projects: [], profiles: [], routines: [], meetings: [], chats: [], skills: [], actions: [], counts: {}, jobs: [], waiting: [] });
    });
  }
  async function drawPage(hash) {
    const real = global.setInterval;
    global.setInterval = () => 0;
    global.location.hash = hash;
    try { await app.route(); await settle(); } finally { global.setInterval = real; }
    return h.dom().mainEl;
  }
  const NORMAL_PAGES = ["#/", "#/employees", "#/work", "#/settings", "#/chat", `#/chat/${CID}`, "#/ceo", "#/setup", "#/welcome", "#/memory", "#/shared",
    "#/my-skills", "#/dispatch", "#/actions", "#/routines", "#/meetings", "#/templates"];

  await test("screen: the normal pages, drawn, say none of the old words (text, labels, hover text)", async () => {
    serve();
    const bad = [];
    for (const hash of NORMAL_PAGES) {
      const main = await drawPage(hash);
      const words = wordsOfTree(main);
      assert.ok(words.length > 4, `${hash} drew something`);
      const found = hits(words);
      if (found.length) bad.push(`${hash}: ${found.join(", ")}`);
    }
    assert.deepStrictEqual(bad, []);
  });

  await test("screen: the sidebar and the page shell hold none of the old words", async () => {
    serve();
    await drawPage("#/");
    const shell = h.dom().bodyEl;
    const found = hits(wordsOfTree(shell)).concat(hits(wordsOfTree(shell), AVOID_TITLE));
    assert.deepStrictEqual(found.filter((t) => t !== "出發通行證"), [], "the sidebar says the new names");
  });

  await test("screen: the advanced pages are named with the new words in the title", async () => {
    serve();
    for (const [hash, title] of [["#/terminals", "指令視窗"], ["#/workbench", "工作台"], ["#/flows", "流程"], ["#/projects", "專案資料夾"], ["#/skills", "AI 工具的外掛清單"], ["#/team", "員工詳細資料"]]) {
      const main = await drawPage(hash);
      // the page's title is its h1; the workbench has none and names itself in the path at the top (the last step)
      const h1 = main.find((n) => n.tag === "h1");
      const crumbs = main.find((n) => n.hasClass && n.hasClass("crumbs"));
      const named = h1 ? text(h1) : crumbs ? text(crumbs.findAll((n) => n.tag === "span" || n.tag === "a").pop() || crumbs) : "";
      assert.ok(named, `${hash} names itself`);
      assert.ok(named === title || (!h1 && text(crumbs).includes(title)), `${hash}: ${named}`);
      assert.deepStrictEqual(hits(named, AVOID_TITLE), [], `${hash}: the title is not an old word`);
    }
  });

  await test("screen: a dialog that opens from a normal page (the new employee) says none of the old words", async () => {
    serve();
    await drawPage("#/employees");
    const add = h.dom().mainEl.find((n) => n.tag === "button" && /新增員工/.test(text(n)));
    assert.ok(add, "the button to add an employee");
    add.dispatch("click");
    await settle();
    const dlg = h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
    assert.ok(dlg, "the dialog is open");
    assert.deepStrictEqual(hits(wordsOfTree(dlg)), []);
  });

  // ---- the plain-words rule that is for the normal pages only -------------------------------------------------------------------------------
  await test("manual_review: the plain words are for the normal pages; an advanced page keeps what the server said", async () => {
    serve();
    const sentence = "這個流程停在 manual_review，原因不明";
    await drawPage("#/chat");
    const normal = app.plainWords(sentence);
    assert.strictEqual(normal.known, true, "on a normal page the sentence is turned into plain words");
    assert.ok(normal.text.includes("要你檢查") && !normal.text.includes("manual_review"), normal.text);
    assert.strictEqual(normal.detail, sentence, "the original is kept whole");
    for (const hash of ["#/flows", "#/terminals", "#/workbench", "#/projects", "#/skills", "#/team"]) {
      await drawPage(hash);
      const w = app.plainWords(sentence);
      assert.strictEqual(w.known, false, `${hash}: an advanced page leaves the sentence as it is`);
      assert.strictEqual(w.text, sentence, hash);
    }
    await drawPage("#/employees");
    assert.strictEqual(app.plainWords(sentence).known, true, "back on a normal page it applies again");
  });

  await test("source: the CEO's lobby door is gone", () => {
    assert.ok(!/function ceoLobbyDoor\b/.test(SOURCE) && !/ceoLobbyDoor\(/.test(SOURCE));
  });

  // ---- the matching itself ------------------------------------------------------------------------------------------------------------
  await test("the matching: a word is found, 可用技能 and Global and 保護範圍（沙盒） are not", () => {
    assert.deepStrictEqual(hits("這張角色卡"), ["角色卡"]);
    assert.deepStrictEqual(hits("按「用技能」"), ["用技能"]);
    assert.deepStrictEqual(hits("可用技能與使用技能"), []);
    assert.deepStrictEqual(hits("Global Governance"), []);
    assert.deepStrictEqual(hits("執行 Bash 指令"), ["Bash"]);
    assert.deepStrictEqual(hits("在保護範圍（沙盒）外執行"), []);
    assert.deepStrictEqual(hits("在沙盒外執行"), ["沙盒"]);
    assert.deepStrictEqual(hits("存成常用做法"), []);
  });

  console.log(`\n${passed} passed`);
  process.exit(process.exitCode || 0);
})();
