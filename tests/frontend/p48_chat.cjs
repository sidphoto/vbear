// P48-3 (v0.22.0, ADR 0014): the page that makes the CEO loses weight and uses the AI the person picked; the CEO's conversation gets two
// opening choices and, once a plan is there, a hint that offers 「請幕僚長安排」; the page that prepares a chat knows the safety check is running.
// Guard rule 16g lives here: an opening choice only puts words in the box (0 requests), the hint's button is the very function of the 「⋯」
// menu's item and so only asks for the preview (nothing that spends is sent before the dialog's own start), a turn that runs or a card that
// waits hides the hint, and the page that makes the CEO keeps 「每件事先問我」 and (for AGY) the line about Google where they are seen.
// The real web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Nothing here runs a model or opens a browser.
// Run: node tests/frontend/p48_chat.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler, FETCH_LOG } = h;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const SOURCE = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
global.document.querySelector = () => null;
global.document.hidden = false;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const by = (n, k, v) => n.find((x) => x.getAttribute && x.getAttribute(k) === v);
const allBy = (n, k, v) => n.findAll((x) => x.getAttribute && x.getAttribute(k) === v);
const q = (n, key) => by(n, "data-chat", key);
const ceo = (n, key) => by(n, "data-ceo", key);
const CID = "c-0123456789abcdef";
const NEW_ID = "prof-0123456789ab";
const OPENING = "你好，請先問我三個問題，了解我想做什麼。";
const CHOICE_ASK = "請你先問我幾個問題，了解我想做什麼，再幫我整理成一份計畫。";
const CHOICE_HAVE = "我想做的事是：";
const PICK_KEY = "vbear-setup-pick";

// ---- fixtures ---------------------------------------------------------------------------------------------------------

let seqNo = 0;
const rec = (kind, data = {}) => ({ seq: ++seqNo, at: 1790000000 + seqNo, kind, ...data });
const support = (over = {}) => ({ detected: "2.1.318", verified: ["2.1.318"], state: "verified", message: "", policy: { ok: true, found: [], problems: [], reason: "" },
  verify: { running: false }, money: "x", ...over });
const codexSupport = (over = {}) => ({ engine: "codex-chat", state: "ready", installed: true, version: "0.163.0", verified: true, logged_in: true, admin_policy_ok: true,
  why: "", verified_versions: ["0.163.0"], verify: { running: false }, money: "x", ...over });
const agySupport = (over = {}) => ({ engine: "agy-chat", state: "ready", installed: true, version: "1.2.3", verified: true, admin_policy_ok: true,
  why: "", verify: { running: false }, money: "x", ...over });
const newCard = (over = {}) => ({ id: NEW_ID, name: "虛構 CEO", position: "planner", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: true, ...over });
const otherCard = () => ({ id: "emp-2", name: "虛構員工", position: "executor", tool: "claude", engine: "claude-chat", enabled: true, can_chat: true, code: null, reason: null, instructions: false });
const listing = (cardOver = {}, supOver = {}, over = {}) => ({ ok: true, chats: [], more: 0, cards: [newCard(cardOver), otherCard()],
  support: support({ codex: codexSupport(), agy: agySupport(), ...supOver }), limits: { per_turn_usd: "0.5", daily_usd: "3" },
  ledger: { spent_usd: "0.12", daily_usd: "3", lamp: "green", includes: [] }, ledger_error: null, problems: [], scratch: "", ...over });
const detail = (over = {}, cardOver = {}) => ({ ok: true, chat: { id: CID, profile_id: NEW_ID, created_at: 1790000000, engine: "claude-chat" }, card: newCard(cardOver),
  records: [], live: null, runtime: { available: true, message: "" }, next_after: 0, last_seq: 0, more: false, problem: null, ...over });
const live = (over = {}) => ({ state: "idle", turn: null, partial: "", partial_truncated: false, model: "haiku", cards: [], ...over });
const PLAN_REPLY = "我整理好了：\n1. 先列出你每個月的收入\n2. 再把支出分成三類\n3. 最後做一張表\n你覺得怎麼樣？";
const talked = () => [rec("user_message", { turn: 1, text: "我想整理開銷" }), rec("reply", { turn: 1, text: "你每個月大概花多少？" }),
  rec("user_message", { turn: 2, text: "大概三萬" }), rec("reply", { turn: 2, text: PLAN_REPLY, truncated: false })];
const ceoPlan = (over = {}) => ({ ok: true, needed: true, can_create: true, go: null, reason: "", tool: "claude", tool_name: "Claude Code", name: "CEO",
  position: "planner", launch_mode: "safe", instructions: "你是我的 CEO。", opening: OPENING, chat_ready: null, chat_note: "", ...over });

let page;
const streams = [];
function setPage(over = {}) {
  app.D.overview = null; app.D.skills = null; app.D.roles = null;
  global.localStorage._store = {};
  app.ceoDrafts.clear();
  page = { list: listing(), detail: detail(), plan: ceoPlan(), created: { ok: true, chat: { id: CID, profile_id: NEW_ID, created_at: 1 } }, ...over };
  streams.length = 0;
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: 1, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [] });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/translations") return jsonResponse({ counts: {}, jobs: [] });
    if (p === "/api/first-ceo") return jsonResponse(page.plan);
    if (p === "/api/agent-profiles" && method === "POST") return jsonResponse({ ok: true, profile: { id: NEW_ID, name: "CEO" } }, true, 201);
    if (p === "/api/config" && method === "POST") return jsonResponse({ ok: true });
    if (p === "/api/chats" && method === "GET") return jsonResponse(page.list);
    if (p === "/api/chats" && method === "POST") return jsonResponse(page.created, true, 201);
    if (p === "/api/chief/preview") return jsonResponse({ ok: true, preview_id: "p-3", cap_usd: "0.10", day_left_usd: "2.5", sends_to: "Anthropic", blockers: [] });
    if (p === "/api/chief" || p === "/api/dispatch" || p === "/api/memory/suggest" || p === "/api/my-skills/suggest") return jsonResponse({ ok: true, chief: [], dispatch: [], suggestions: [] });
    if (p === "/api/meetings/ledger") return jsonResponse({ ok: true, lamp: "green" });
    const m = /^\/api\/chats\/(c-[0-9a-f]{16})(?:\/([a-z]+))?$/.exec(p);
    if (m && m[2] === "stream") return streamResponse();
    if (m && !m[2] && method === "GET") return jsonResponse(page.detail);
    if (m && m[2] === "messages") return jsonResponse({ ok: true, turn: 1, cap_usd: "0.5", process: "new" }, true, 202);
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
const nonGet = () => FETCH_LOG.filter((c) => c.method !== "GET");
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const inDetails = (node) => { for (let n = node; n; n = n.parentNode) if (n.tag === "details") return n; return null; };
const sentences = (main) => text(main);

// =====================================================================================================================
// the page that makes the CEO
// =====================================================================================================================

test("16g CEO page: only the name, the tool line, 「每件事先問我」 and the two buttons are in view; the explanations are in a closed 「詳細資訊」", async () => {
  setPage({ plan: ceoPlan({ chat_note: "Codex 聊天要用另一份登入。" }) });
  const main = await open("#/ceo");
  const more = ceo(main, "more");
  assert(more && more.tag === "details" && !more.hasAttribute("open"), "a closed details");
  assert(text(more.find((n) => n.tag === "summary")).includes("詳細資訊"));
  for (const key of ["instructions", "limits", "cost", "chat-note"]) {
    const node = ceo(main, key);
    assert(node, key + " is still there");
    assert.strictEqual(inDetails(node), more, key + " is folded");
  }
  for (const key of ["name", "tool", "mode", "create", "later"]) {
    const node = ceo(main, key);
    assert(node, key);
    assert.strictEqual(inDetails(node), null, key + " is in view");
  }
  assert(/每件事先問我/.test(text(ceo(main, "mode"))) && /先問你/.test(text(ceo(main, "mode"))));
  assert.strictEqual(nonGet().length, 0, "showing the page sends nothing");
});

test("16g CEO page: the line that the talk goes to Google (AGY) is in view too, and only an AGY CEO has it", async () => {
  setPage({ plan: ceoPlan({ tool: "agy", tool_name: "AGY" }), list: listing({ tool: "agy", engine: "agy-chat" }, { agy: agySupport({ state: "unverified", verified: false }) }) });
  let main = await open("#/ceo");
  const note = ceo(main, "agy-note");
  assert(note && text(note).includes("送到 Google"), "the Google line");
  assert.strictEqual(inDetails(note), null, "not folded");
  assert.strictEqual(inDetails(ceo(main, "mode")), null);
  setPage();
  main = await open("#/ceo");
  assert.strictEqual(ceo(main, "agy-note"), null);
});

test("CEO page: it asks for the tool the person picked in the start-up (?tool=), and for none when nothing valid is remembered", async () => {
  setPage();
  await open("#/ceo");
  assert.deepStrictEqual(FETCH_LOG.filter((c) => c.url.startsWith("/api/first-ceo")).map((c) => c.url), ["/api/first-ceo"]);
  for (const pick of ["claude", "codex", "agy"]) {
    setPage({ plan: ceoPlan({ tool: pick, tool_name: pick }) });
    global.localStorage.setItem(PICK_KEY, pick);
    await open("#/ceo");
    assert.deepStrictEqual(FETCH_LOG.filter((c) => c.url.startsWith("/api/first-ceo")).map((c) => c.url), ["/api/first-ceo?tool=" + pick]);
  }
  for (const bad of ["grok", "mcode", "CLAUDE", "claude&x=1", "", "../x"]) {
    setPage();
    global.localStorage.setItem(PICK_KEY, bad);
    await open("#/ceo");
    assert.deepStrictEqual(FETCH_LOG.filter((c) => c.url.startsWith("/api/first-ceo")).map((c) => c.url), ["/api/first-ceo"], "ignored: " + bad);
  }
});

test("CEO page: the tool the person picked is not ready: the reason is shown, nothing can be made, no other tool is offered", async () => {
  setPage({ plan: ceoPlan({ can_create: false, go: "setup", tool: null, tool_name: null, reason: "你選的 Codex 還沒準備好，回開始設定把它準備好，或換一家。" }) });
  global.localStorage.setItem(PICK_KEY, "codex");
  const main = await open("#/ceo");
  assert(text(main).includes("你選的 Codex 還沒準備好"));
  assert.strictEqual(ceo(main, "create"), null);
  assert.strictEqual(ceo(main, "name"), null);
  assert.strictEqual(by(main, "data-ceo", "setup-go").getAttribute("href"), "#/setup");
  assert.strictEqual(nonGet().length, 0);
});

test("CEO page: the tool line says 「可以聊天了」 only when a chat can start, and says the safety check is running when it is", async () => {
  const cases = [
    [{ state: "verified" }, "可以聊天了"],
    [{ state: "unverified", verify: { running: true } }, "還在做"],
    [{ state: "unverified" }, "先做一次安全檢查"],
    [{ state: "policy" }, "管理員設定"],
  ];
  for (const [sup, word] of cases) {
    setPage({ list: listing({}, sup) });
    const main = await open("#/ceo");
    const line = text(ceo(main, "tool"));
    assert(line.includes(word), `${sup.state}/${JSON.stringify(sup.verify)}: ${line}`);
    assert.strictEqual(line.includes("可以聊天了"), sup.state === "verified", line);
    assert(!line.includes("已就緒"), line);
  }
  setPage({ list: null });
  page.list = undefined;
  const main = await open("#/ceo");
  assert(text(ceo(main, "tool")).includes("讀不到"), "a state that could not be read is said so");
});

// =====================================================================================================================
// the two opening choices
// =====================================================================================================================

const chosenBox = (main) => q(main, "input");
const choices = (main) => allBy(main, "data-chat", "opening-choice");

test("16g opening choices: shown in an unused CEO chat; a press only changes the words in the box and sends nothing", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const btns = choices(main);
  assert.strictEqual(btns.length, 2);
  assert.deepStrictEqual(btns.map((b) => text(b)), ["請你先問我幾個問題，再幫我整理計畫", "我已經有一件想做的事"]);
  assert.strictEqual(chosenBox(main).value, "");
  FETCH_LOG.length = 0;
  btns[0].click(); await settle();
  assert.strictEqual(chosenBox(main).value, CHOICE_ASK);
  assert.strictEqual(FETCH_LOG.length, 0, "not even a read");
  assert.strictEqual(choices(main).length, 2, "the other choice can still be pressed (the words are still a choice's)");
  choices(main)[1].click(); await settle();
  assert.strictEqual(chosenBox(main).value, CHOICE_HAVE);
  assert.strictEqual(FETCH_LOG.length, 0);
  assert.strictEqual(global.document.activeElement, chosenBox(main), "the box has the focus");
  assert(q(main, "send").disabled === false);
  assert.strictEqual(nonGet().length, 0);
});

test("16g opening choices: the person's own edit to the words hides them, and the person's words are never overwritten", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  const box = chosenBox(main);
  box.value = "我想"; box.dispatch("input"); await settle();
  assert.strictEqual(choices(main).length, 0, "hidden once the words are the person's");
  box.value = ""; box.dispatch("input"); await settle();
  assert.strictEqual(choices(main).length, 2, "an empty box has them again");
  choices(main)[0].click(); await settle();
  box.value = CHOICE_ASK + "（我是家庭主婦）"; box.dispatch("input"); await settle();
  assert.strictEqual(choices(main).length, 0);
  assert.strictEqual(box.value, CHOICE_ASK + "（我是家庭主婦）");
});

test("16g opening choices: not in a chat that is not a CEO's, after a message was sent, or in a group's chat", async () => {
  setPage({ detail: detail({}, { position: "executor" }) });
  let main = await open("#/chat/" + CID);
  assert.strictEqual(choices(main).length, 0, "not a CEO");
  setPage({ detail: detail({ records: [rec("user_message", { turn: 1, text: "你好" })] }) });
  main = await open("#/chat/" + CID);
  assert.strictEqual(choices(main).length, 0, "a message was already sent");
});

test("16g opening choices: a message that goes through (the person's own send) removes them; the press sent only the box", async () => {
  setPage();
  const main = await open("#/chat/" + CID);
  choices(main)[1].click(); await settle();
  chosenBox(main).value = "我想做的事是：整理家裡的開銷";
  chosenBox(main).dispatch("input");
  q(main, "send").click(); await settle(80);
  assert.deepStrictEqual(calls("POST", "/messages").map((c) => c.body), [{ text: "我想做的事是：整理家裡的開銷" }]);
  assert.strictEqual(choices(main).length, 0);
});

test("opening choices: VBear's own opening sentence in the box does not hide them, and a press replaces it", async () => {
  setPage();
  let main = await open("#/ceo");
  ceo(main, "create").click(); await settle(80);
  assert.strictEqual(global.location.hash, "#/chat/" + CID);
  main = await open(global.location.hash);
  assert.strictEqual(chosenBox(main).value, OPENING);
  assert.strictEqual(choices(main).length, 2);
  assert(text(ceo(main, "opening-note")).includes("VBear 先幫你填好"));
  choices(main)[0].click(); await settle();
  assert.strictEqual(chosenBox(main).value, CHOICE_ASK);
  assert(!text(main).includes("VBear 先幫你填好"), "the note about VBear's sentence is gone once the words are not VBear's");
  assert.strictEqual(calls("POST", "/messages").length, 0);
});

test("opening note: words the person typed earlier (back from the prepare page) are said to be theirs, not VBear's", async () => {
  setPage();
  app.ceoDrafts.set(CID, "幫我整理下載資料夾");
  const main = await open("#/chat/" + CID);
  assert.strictEqual(chosenBox(main).value, "幫我整理下載資料夾");
  const note = text(ceo(main, "opening-note"));
  assert(note.includes("你剛才打的字") && note.includes("還沒送出") && note.includes("送出"), note);
  assert(!note.includes("VBear 先幫你填好"), note);
  assert.strictEqual(choices(main).length, 0, "the person's words are not a choice's");
  chosenBox(main).value = "改過了"; chosenBox(main).dispatch("input"); await settle();
  assert.strictEqual(ceo(main, "opening-note"), null, "the line is only for the words as they were");
});

// =====================================================================================================================
// 「請幕僚長安排」 hint
// =====================================================================================================================

test("ceoPlanShaped: the literal rule, one case at a time", () => {
  const u = (t) => ({ kind: "user_message", text: t });
  const r = (t) => ({ kind: "reply", text: t });
  const list3 = "好的：\n1. 甲\n2. 乙\n3. 丙";
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r(list3)]), true);
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("一、甲\n二、乙\n三、丙")]), true, "一、");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("1、甲\n2、乙\n3、丙")]), true, "1、");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("- 甲\n- 乙\n- 丙")]), true, "-");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("• 甲\n• 乙\n• 丙")]), true, "bullet");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("・甲\n・乙\n・丙")]), true, "middle dot");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("1. 甲\n2. 乙")]), false, "two lines are not enough");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r("---\n---\n---")]), false, "rules are not a list");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("1.5 億\n2.5 億\n3.5 億\n你覺得呢")]), false, "numbers are not a list");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r(list3)]), false, "only one message of the person's");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r(list3), u("d")]), false, "the last is the person's");
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), r(list3), { kind: "tool_call", text: "x" }]), true, "a tool line in between is not a message");
  assert.strictEqual(app.ceoPlanShaped([]), false);
  assert.strictEqual(app.ceoPlanShaped(null), false);
  assert.strictEqual(app.ceoPlanShaped([u("a"), r("b"), u("c"), { kind: "reply", text: 5 }]), false);
});

const hint = (main) => q(main, "chief-hint");

test("16g hint: shown under the plan; its button asks only for the preview, in the same way as the 「⋯」 item, and nothing that spends is sent", async () => {
  setPage({ detail: detail({ records: talked() }) });
  let main = await open("#/chat/" + CID);
  const box = hint(main);
  assert(box, "the hint is there");
  assert(text(box).includes("計畫整理好了嗎？") && text(box).includes("你確認了才會做"), text(box));
  assert(!/已經|完成了|寫完/.test(text(box)), "it asks, it does not say the plan is done");
  assert.strictEqual(text(q(main, "chief-hint-go")), "請幕僚長安排");
  assert.strictEqual(text(q(main, "chief-hint-no")), "先不用");
  assert.strictEqual(nonGet().length, 0, "showing it sends nothing");
  FETCH_LOG.length = 0;
  q(main, "chief-hint-go").click(); await settle(80);
  const viaHint = FETCH_LOG.map((c) => c.method + " " + c.url);
  const dlg = dialog();
  assert(dlg && /US\$0\.10/.test(text(dlg)) && /Anthropic/.test(text(dlg)), "the dialog with the cost and where the words go");
  assert.deepStrictEqual(viaHint, ["GET /api/chief/preview?chat_id=" + CID]);
  assert.strictEqual(nonGet().length, 0, "before the dialog's own start: not one POST");
  dlg.find((n) => n.tag === "button" && n.hasClass("btn") && !n.hasClass("primary") && /取消/.test(text(n))).click(); await settle();
  // the menu item does exactly the same
  FETCH_LOG.length = 0;
  q(main, "more").click();
  by(main, "data-chat-menu", "chief").click(); await settle(80);
  assert.deepStrictEqual(FETCH_LOG.map((c) => c.method + " " + c.url), viaHint, "the same requests as the menu item");
  assert(dialog(), "and the same dialog");
});

test("16g hint: not shown while a turn runs, while a card waits, with a refused plan, after 「先不用」, or when the plan is not the last thing said", async () => {
  const cardWaiting = { card_id: "k-" + "a".repeat(16), token: "t".repeat(32), turn: 3, tool: "Bash", input: { command: "ls", description: "x" }, editable: "command", reason: "x", expires_in: 200 };
  const cases = [
    ["a turn runs", detail({ records: talked(), live: live({ state: "working", turn: 3 }) })],
    ["a card waits", detail({ records: talked(), live: live({ state: "waiting", turn: 3, cards: [cardWaiting] }) })],
    ["only one message of the person's", detail({ records: talked().slice(2) })],
    ["the last is the person's", detail({ records: [...talked(), rec("user_message", { turn: 3, text: "好" })] })],
    ["not a list", detail({ records: [...talked().slice(0, 3), rec("reply", { turn: 2, text: "好的，我來想想看。", truncated: false })] })],
    ["the chat is cut short", detail({ records: talked(), more: true })],
    ["not a CEO", detail({ records: talked() }, { position: "executor" })],
  ];
  for (const [name, d] of cases) {
    setPage({ detail: d });
    const main = await open("#/chat/" + CID);
    assert.strictEqual(hint(main), null, name);
  }
  setPage({ detail: detail({ records: talked() }) });
  const main = await open("#/chat/" + CID);
  assert(hint(main));
  q(main, "chief-hint-no").click(); await settle();
  assert.strictEqual(hint(main), null, "dismissed");
  assert.strictEqual(nonGet().length, 0, "dismissing sends nothing");
});

test("hint: appears when the CEO's reply with the list arrives and goes while the person's next turn runs", async () => {
  setPage({ detail: detail({ records: talked().slice(0, 3) }) });
  const main = await open("#/chat/" + CID);
  assert.strictEqual(hint(main), null);
  streams[0].push({ ok: true, records: [rec("reply", { turn: 2, text: PLAN_REPLY, truncated: false })], live: live(), card: newCard() });
  await settle(80);
  assert(hint(main), "the hint came with the reply");
  streams[0].push({ ok: true, records: [rec("user_message", { turn: 3, text: "再加一件事" })], live: live({ state: "working", turn: 3 }), card: newCard() });
  await settle(80);
  assert.strictEqual(hint(main), null, "gone while the next turn runs");
});

// =====================================================================================================================
// the page that prepares a chat knows the safety check is running
// =====================================================================================================================

test("chatPrepState: a safety check that is running is its own state, for each of the three AI tools; a finished or failed one is back to 'verify'", () => {
  const cardFor = (engine) => ({ id: "x", name: "虛構", can_chat: true, engine });
  const data = (over) => ({ support: { ...support(), codex: codexSupport(), agy: agySupport(), ...over } });
  const run = { running: true };
  const cases = [
    ["claude-chat", data({ state: "unverified", verify: run }), "Claude Code"],
    ["codex-chat", data({ codex: codexSupport({ state: "unverified", verified: false, verify: run }) }), "Codex"],
    ["agy-chat", data({ agy: agySupport({ state: "unverified", verified: false, verify: run }) }), "AGY"],
  ];
  for (const [engine, d, tool] of cases) {
    const st = app.chatPrepState(cardFor(engine), d);
    assert.strictEqual(st.kind, "running", engine);
    assert(st.reason.includes(tool + "的聊天安全檢查還在做") && st.reason.includes("通常要幾分鐘") && st.reason.includes("自動開始和 虛構 的對話"), st.reason);
    assert(!st.verify && !st.href, "no button, no link: " + engine);
    const idle = JSON.parse(JSON.stringify(d));
    const part = engine === "claude-chat" ? idle.support : engine === "codex-chat" ? idle.support.codex : idle.support.agy;
    part.verify = { running: false, result: "failed", message: "x" };
    assert.strictEqual(app.chatPrepState(cardFor(engine), idle).kind, "verify", engine + " failed");
  }
  // a tool that is already good, or held back by an administrator, is not "running" whatever the verify field says
  assert.strictEqual(app.chatPrepState(cardFor("claude-chat"), data({ state: "verified", verify: run })).kind, "start");
  assert.strictEqual(app.chatPrepState(cardFor("claude-chat"), data({ state: "policy", verify: run })).kind, "link");
});

test("prepare page, running: no button, the words say what is happening, a link to all chats, and nothing is sent", async () => {
  setPage({ list: listing({}, { state: "unverified", verify: { running: true } }) });
  const main = await open("#/chat?profile=" + NEW_ID);
  assert(text(q(main, "prep-reason")).includes("聊天安全檢查還在做"), text(q(main, "prep-reason")));
  assert(text(q(main, "prep-reason")).includes("自動開始和 虛構 CEO 的對話"));
  assert.strictEqual(allBy(main, "data-chat", "prep-action").length, 0, "no button to press again");
  assert.strictEqual(main.findAll((n) => n.tag === "button").length, 0, "no button at all");
  assert(by(main, "href", "#/chat"), "the link to all the chats");
  assert(q(main, "prep-running"));
  assert.strictEqual(nonGet().length, 0);
});

test("prepare page, running -> passed: the conversation opens by itself with the opening sentence in the box, and nothing is sent", async () => {
  setPage({ list: listing({}, { state: "unverified", verify: { running: true } }) });
  app.ceoDrafts.set(NEW_ID, OPENING);
  let main = await open("#/chat?profile=" + NEW_ID);
  assert.strictEqual(calls("POST", "/api/chats").length, 0);
  page.list = listing({}, { state: "verified", verify: { running: false, result: "passed" } });
  await page.tick(); await settle(80);
  assert.strictEqual(global.location.hash, "#/chat/" + CID, "opened by itself");
  assert.deepStrictEqual(calls("POST", "/api/chats").map((c) => c.body), [{ profile_id: NEW_ID }]);
  main = await open(global.location.hash);
  assert.strictEqual(chosenBox(main).value, OPENING, "the opening sentence is in the box");
  assert.strictEqual(calls("POST", "/messages").length, 0, "no message was sent");
  assert.strictEqual(calls("POST", "/api/chat-support/verify").length, 0);
});

test("prepare page, running -> failed: back to the one button that asks first, the reason in plain words, and a later pass does not open the chat by itself", async () => {
  setPage({ list: listing({}, { state: "unverified", verify: { running: true } }) });
  let main = await open("#/chat?profile=" + NEW_ID);
  page.list = listing({}, { state: "unverified", verify: { running: false, result: "failed", message: "聊天驗證：bash_asks 沒有通過" } });
  await page.tick(); await settle(80);
  main = h.dom().mainEl;
  const actions = allBy(main, "data-chat", "prep-action");
  assert.strictEqual(actions.length, 1);
  assert.strictEqual(text(actions[0]), "先做一次安全檢查");
  assert(text(q(main, "prep-result")).includes("沒有通過"), "the server's sentence about the failure");
  assert.strictEqual(calls("POST", "/api/chat-support/verify").length, 0, "asking again is the person's press");
  page.list = listing({}, { state: "verified" });
  await page.tick(); await settle(80);
  assert.strictEqual(global.location.hash, "#/chat?profile=" + NEW_ID, "it did not open by itself: the person did not ask for this one");
  assert.strictEqual(calls("POST", "/api/chats").length, 0);
});

// =====================================================================================================================
// 16g as checks on the source, each with a small sample that must trip it (so the check is known to be able to fail)
// =====================================================================================================================

const between = (src, from, to) => { const a = src.indexOf(from); if (a < 0) return ""; const b = src.indexOf(to, a + from.length); return src.slice(a, b < 0 ? undefined : b); };
const rules16g = {
  // the opening choices only set the words in the box: no request in the code that handles them
  choicesOnlyWords(src) {
    const body = between(src, "// ---------- CEO opening choices", "// ---------- end of CEO opening choices");
    return body.length > 200 && !/\bapi\.|fetch\(|location\.hash|\.click\(\)/.test(body) && /input\.value\s*=/.test(body);
  },
  // the hint's button is the menu item's function, and the hint's code asks nothing itself
  hintIsTheMenuItem(src) {
    const body = between(src, "// ---------- the hint to ask the chief of staff", "// ---------- end of the hint");
    return body.length > 200 && /"chief-hint-go"/.test(body) && /on: \{ click: \(\) => chief\.open\(\) \}/.test(body) && !/\bapi\.|fetch\(/.test(body);
  },
  // no hint while a turn is open or a card waits
  hintWaitsForQuiet(src) {
    const body = between(src, "const hintWanted = () => {", "};");
    return /turnOpen\(\)/.test(body) && /cards/.test(body) && /ceoPlanShaped\(/.test(body);
  },
  // the page that makes the CEO keeps the mode line and the line about Google out of the folded part
  ceoSafetyInView(src) {
    const page = between(src, "async function viewCeo() {", "// ---------- end of the first CEO");
    const folded = between(page, "const more = el(\"details\"", "setKids(main, head, el(\"p\", { class: \"lede\" }");
    return folded.length > 100 && !/CEO_MODE|CEO_AGY_NOTE|"data-ceo": "mode"|"data-ceo": "agy-note"/.test(folded) && /CEO_LIMITS/.test(folded)
      && /CEO_MODE/.test(page.slice(page.indexOf(folded) + folded.length)) && /CEO_AGY_NOTE/.test(page.slice(page.indexOf(folded) + folded.length));
  },
};
const ruleNames16g = Object.keys(rules16g);

test("16g: the rules hold on the real source", () => {
  for (const name of ruleNames16g) assert.strictEqual(rules16g[name](SOURCE), true, name);
});

test("16g: each rule trips on a small sample that breaks it (so it can fail)", () => {
  const swap = (a, b) => { const r = SOURCE.replace(a, b); assert.notStrictEqual(r, SOURCE, "the sample really changes the source: " + a); return r; };
  const broken = {
    choicesOnlyWords: swap("// ---------- end of CEO opening choices", "void api.post(\"/api/chats/x/messages\", {});\n// ---------- end of CEO opening choices"),
    hintIsTheMenuItem: swap("on: { click: () => chief.open() } }, \"請幕僚長安排\"", "on: { click: () => api.post(\"/api/chief\", {}) } }, \"請幕僚長安排\""),
    hintWaitsForQuiet: swap("view.more === true || turnOpen()) return false;", "view.more === true) return false;"),
    ceoSafetyInView: swap("const more = el(\"details\", { class: \"fold ceo-more\", \"data-ceo\": \"more\" },", "const more = el(\"details\", { class: \"fold ceo-more\", \"data-ceo\": \"more\" }, el(\"p\", null, CEO_MODE),"),
  };
  for (const name of ruleNames16g) assert.strictEqual(rules16g[name](broken[name]), false, name + " trips");
});

test("the new code obeys the product rules: no innerHTML, no emoji, no outside address, only el() text", () => {
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}]/u;
  for (const [from, to] of [["// ---------- CEO opening choices", "// ---------- end of CEO opening choices"], ["// ---------- the hint to ask the chief of staff", "// ---------- end of the hint"],
    ["async function viewCeo() {", "// ---------- end of the first CEO"]]) {
    const part = between(SOURCE, from, to);
    assert(part.length > 200, from);
    assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(part) && !emoji.test(part) && !/https?:\/\//.test(part), from);
  }
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
