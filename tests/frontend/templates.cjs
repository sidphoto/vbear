// P45-1: the 團隊範本 page (#/templates): four fixed lines, one block for each template with three rows of tick boxes, 全選 and 全不選, ticking across
// templates, the line at the bottom, the preview (the AI tool, the fixed words, who a routine goes to, same names, the limits, a second yes), and the entry
// in the nav and in the card pool. The real web/app.js on a synthetic DOM, fetch answered by the test; every name and text here is made up and the page
// shows them as text only. Nothing is applied in this batch: the only POST is the preview.
// Run: node tests/frontend/templates.cjs   (exit code 0 = pass)
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
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const ROOT = path.join(__dirname, "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- team templates (v0.19, P45-1)"), SRC.indexOf("// ---------- end of team templates"));
const HTML = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");

const card = (key, name, position, model, instructions) => ({ key, name, position, claude_model: model, instructions });
const shop = {
  id: "shop", name: "小店", builtin: true, about: "一個人開網路或實體小店：回覆客人、寫商品介紹、記帳。",
  cards: [card("service", "客服", null, "haiku", "你是客服。"), card("copy", "商品文案", "social", "sonnet", "你是文案。"), card("accounting", "會計", "accountant", "haiku", "你是會計。")],
  skills: [{ key: "reply", name: "回覆客人詢問", text: "請幫我回覆。\n（貼在這裡）" }, { key: "product", name: "寫商品介紹", text: "請寫介紹。" }, { key: "daybook", name: "整理一天的帳", text: "請整理帳。" }],
  routines: [{ key: "spend", name: "整理昨天的花費", text: "請整理。", days: [0, 1, 2, 3, 4, 5, 6], times: ["09:00"], who: "accounting" },
    { key: "promo", name: "想下週的促銷", text: "請想促銷。", days: [4], times: ["10:00"], who: "copy" }],
};
const studio = {
  id: "studio", name: "接案工作室", builtin: true, about: "接案。",
  cards: [card("assistant", "專案助理", "pm", "haiku", "你是助理。"), card("accounting", "會計", "accountant", "haiku", "你是會計。")],
  skills: [{ key: "quote", name: "寫報價單草稿", text: "請寫報價。" }],
  routines: [{ key: "todo", name: "整理本週待辦", text: "請整理待辦。", days: [0], times: ["09:00"], who: "assistant" }],
};
const TOOLS_READY = { claude: { ready: true, why: "" }, codex: { ready: true, why: "" }, default: "claude" };

let state;
let calls;
function previewOf(body, over = {}) {
  const all = state.builtin.concat(state.mine);
  const find = (kind, ref) => all.find((t) => t.id === ref.template)[kind].find((x) => x.key === ref.key);
  const cards = body.cards.map((c) => {
    const it = find("cards", c.from);
    return { from: c.from, name: c.name === undefined ? it.name : c.name, default_name: it.name, position: it.position, claude_model: it.claude_model,
      model_id: body.tool === "claude" && it.claude_model ? it.claude_model : "", instructions_head: (it.instructions || "").slice(0, 80), instructions_cut: false,
      same_in_batch: false, same_existing: false };
  });
  const routines = body.routines.map((r) => {
    const it = find("routines", r.from);
    let assignee = { kind: null, card: null, profile_id: null, name: null };
    if (r.to && r.to.profile_id) assignee = { kind: "existing", card: null, profile_id: r.to.profile_id, name: "老員工" };
    else {
      const ref = r.to && r.to.card ? r.to.card : it.who ? { template: r.from.template, key: it.who } : null;
      const c = ref && cards.find((x) => x.from.template === ref.template && x.from.key === ref.key);
      if (c) assignee = { kind: "card", card: c.from, profile_id: null, name: c.name };
    }
    return { from: r.from, name: it.name, days: it.days, times: it.times, assignee };
  });
  const problems = routines.filter((r) => !r.assignee.kind).map((r) => ({ code: "no_assignee", from: r.from, text: `例行工作「${r.name}」還沒有交給任何員工，請在預覽裡選一位。` }));
  const now = state.counts;
  const after = (k, add, max) => ({ now: now[k], add, after: now[k] + add, max });
  const pv = { tool: body.tool, cards, skills: body.skills.map((s) => ({ from: s.from, name: find("skills", s.from).name })), routines,
    warn_text: {}, choices: { cards: cards.map((c) => ({ template: c.from.template, key: c.from.key, name: c.name })), existing: [{ profile_id: "p-old", name: "老員工" }] },
    after: { cards: after("cards", cards.length, 500), skills: after("skills", body.skills.length, 100), routines: after("routines", routines.length, 20) },
    notes: [], warn_items: [], problems, ok: problems.length === 0, ...over };
  pv.ok = pv.problems.length === 0;
  return pv;
}
function setServer(over = {}) {
  state = { builtin: [shop, studio], mine: [], tools: TOOLS_READY, counts: { cards: 2, skills: 1, routines: 0 }, problems: [], mine_readable: true, preview: null, previewFails: null, ...over };
  calls = [];
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body]);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [], sources: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/waiting") return jsonResponse({ waiting: [] });
    if (p === "/api/templates" && method === "GET") {
      return jsonResponse({ ok: true, builtin: state.builtin, mine: state.mine, mine_readable: state.mine_readable, problem: state.mine_readable ? null : "你存的團隊範本的檔案有問題",
        problems: state.problems, applies: [], counts: state.counts, current: { cards: [], skills: [], routines: [] }, limits: {}, tools: state.tools });
    }
    if (p === "/api/templates/preview" && method === "POST") {
      if (state.previewFails) return jsonResponse({ error: state.previewFails, code: "bad_request" }, false, 400);
      return jsonResponse({ ok: true, preview: state.preview ? state.preview(body) : previewOf(body) });
    }
    return null;
  });
}
async function open(hash = "#/templates") {
  const realSetInterval = global.setInterval;
  global.setInterval = () => 0;
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const posts = () => calls.filter((c) => c[0] === "POST");
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const by = (root, key, value) => root.find((n) => attr(n, key) === value);
const allBy = (root, key, value) => root.findAll((n) => attr(n, key) === value);
const block = (main, id) => by(main, "data-template-id", id);
const tick = async (root, kind, template, key, on = true) => {
  const box = root.find((n) => attr(n, "data-tpl-pick") === kind && attr(n, "data-tpl-template") === template && attr(n, "data-tpl-key") === key);
  assert(box, `box ${kind} ${template}/${key}`);
  box.checked = on;
  box.dispatch("change");
  await settle();
};
const click = async (node) => { assert(node, "a button"); node.dispatch("click"); await settle(); };
const action = (root, name) => root.find((n) => n.tag === "button" && attr(n, "data-tpl-action") === name);

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("the page: the title, the four fixed lines word for word, one block for each template in order, and nothing posted", async () => {
  setServer();
  const main = await open();
  assert(text(main.find((n) => n.tag === "h1")).includes("團隊範本"));
  const li = by(main, "data-templates", "lines").findAll((n) => n.tag === "li").map(text);
  assert.deepStrictEqual(li, [
    "團隊範本是一組現成的員工、技能和例行工作。勾你要的，按「預覽並套用」看清楚再套用。",
    "套用不用 AI、不花錢。員工一律用安全模式，跑指令、改檔案照舊每次都問你；記憶和共用資料夾照你平常的設定；例行工作建好是關著的。",
    "每次套用都可以「復原這次套用」：只刪這次建的、你沒改過也沒用過的，改過或用過的會留著並告訴你。團隊範本不會改或刪你原本就有的東西。",
    "團隊範本只存在這台電腦，不會上傳，也不能匯出。"]);
  assert.strictEqual(text(by(main, "data-templates", "ceo-line")), "要用幕僚長派工，還需要一位 CEO（到角色卡池建）。");
  const blocks = allBy(main, "data-templates", "block");
  assert.deepStrictEqual(blocks.map((b) => attr(b, "data-template-id")), ["shop", "studio"]);
  assert(text(block(main, "shop")).includes("小店") && text(block(main, "shop")).includes("VBear 內建") && text(block(main, "shop")).includes(shop.about));
  assert.deepStrictEqual(calls.filter((c) => c[0] !== "GET"), [], "nothing is posted when the page opens");
  assert.strictEqual(calls.filter((c) => c[1] === "/api/templates").length, 1);
});

test("each block has three rows with a tick box for every item, and the facts of each", async () => {
  setServer();
  const main = await open();
  const b = block(main, "shop");
  assert.deepStrictEqual(["cards", "skills", "routines"].map((k) => allBy(b, "data-tpl-pick", k).length), [3, 3, 2]);
  assert.deepStrictEqual(["cards", "skills", "routines"].map((k) => allBy(block(main, "studio"), "data-tpl-pick", k).length), [2, 1, 1]);
  const t = text(b);
  for (const s of ["客服", "商品文案", "會計", "社群媒體經理", "會計師", "建議模型 sonnet", "未指定", "回覆客人詢問", "整理昨天的花費", "每天　09:00", "交給：會計", "每週五　10:00", "交給：商品文案"]) assert(t.includes(s), s);
  assert(text(by(b, "data-tpl-text", "cards")).includes("你是客服。"));
  assert(allBy(b, "data-tpl-text", "skills").map(text).some((x) => x.includes("（貼在這裡）")), "the full text of a skill is there to open");
  assert(allBy(b, "data-tpl-pick", "cards").every((x) => x.checked === false), "nothing is ticked at first");
});

test("the line at the bottom counts what is ticked, across templates, and 預覽並套用 waits for a tick", async () => {
  setServer();
  const main = await open();
  const foot = by(main, "data-templates", "foot");
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：0 位員工、0 個技能、0 件例行工作");
  assert.strictEqual(action(foot, "preview").disabled, true);
  await tick(main, "cards", "shop", "copy");
  await tick(main, "cards", "studio", "accounting");
  await tick(main, "skills", "shop", "product");
  await tick(main, "routines", "studio", "todo");
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：2 位員工、1 個技能、1 件例行工作");
  assert.strictEqual(action(foot, "preview").disabled, false);
  await tick(main, "cards", "shop", "copy", false);
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：1 位員工、1 個技能、1 件例行工作");
});

test("全選 ticks everything in one block only, 全不選 clears it and leaves the other block's ticks", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "studio", "assistant");
  await click(action(block(main, "shop"), "all"));
  assert.strictEqual(text(by(main, "data-templates", "count")), "已勾：4 位員工、3 個技能、2 件例行工作");
  assert(allBy(block(main, "shop"), "data-tpl-pick", "cards").every((x) => x.checked === true));
  assert.strictEqual(allBy(block(main, "studio"), "data-tpl-pick", "cards").filter((x) => x.checked).length, 1);
  await click(action(block(main, "shop"), "none"));
  assert.strictEqual(text(by(main, "data-templates", "count")), "已勾：1 位員工、0 個技能、0 件例行工作");
});

test("the preview posts the tick as it is, with no name and no routine owner the person did not choose, and nothing else is posted", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "accounting");
  await tick(main, "cards", "studio", "accounting");
  await tick(main, "skills", "shop", "reply");
  await tick(main, "routines", "shop", "spend");
  await click(action(main, "preview"));
  assert(dialog(), "the dialog is open");
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/templates/preview", {
    tool: "claude",
    cards: [{ from: { template: "shop", key: "accounting" } }, { from: { template: "studio", key: "accounting" } }],
    skills: [{ from: { template: "shop", key: "reply" } }],
    routines: [{ from: { template: "shop", key: "spend" } }] }]]);
  const d = dialog();
  assert.strictEqual(text(by(d, "data-templates", "summary")), "這次會建：2 位員工、1 個技能、1 件例行工作。");
  assert.strictEqual(text(by(d, "data-templates", "after")), "套用後：員工 4/500、技能 2/100、例行工作 1/20");
  assert.deepStrictEqual(allBy(d, "data-tpl-preview", "card").length, 2);
  assert.strictEqual(by(d, "data-tpl-to", "shop/spend").value, "card:shop/accounting");
});

test("the preview's fixed words, word for word, and the tool choice with Claude Code first", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const d = dialog();
  assert.strictEqual(text(by(d, "data-templates", "tool-label")), "這次的員工都用：");
  const radios = allBy(d, "data-tpl-tool", "claude").concat(allBy(d, "data-tpl-tool", "codex"));
  assert.strictEqual(radios.length, 2);
  assert.strictEqual(by(d, "data-tpl-tool", "claude").checked, true);
  assert.strictEqual(by(d, "data-tpl-tool", "codex").checked, false);
  assert(text(by(d, "data-templates", "tool")).includes("Claude Code") && text(by(d, "data-templates", "tool")).includes("Codex"));
  assert.deepStrictEqual(by(d, "data-templates", "fixed").findAll((n) => n.tag === "li").map(text), [
    "員工一律用安全模式：跑指令、改檔案照舊每次都問你。團隊範本不會建出完整模式的員工。",
    "記憶照你平常的設定（Claude Code 的員工帶記憶，Codex 的員工不帶，因為記憶會送到 OpenAI）；共用資料夾都關著。要改，到記憶頁或共用資料夾頁一位一位打開。",
    "例行工作建好是關著的，要你自己到例行工作頁打開。",
    "套用不用 AI、不花錢。之後跟員工聊天才會花錢，照你的每回合上限與每天上限。"]);
  assert.strictEqual(by(d, "data-templates", "tool-not-ready"), null);
});

test("choosing Codex asks again with Codex and adds the one more line", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const codex = by(dialog(), "data-tpl-tool", "codex");
  codex.checked = true;
  codex.dispatch("change");
  await settle();
  assert.strictEqual(posts().length, 2);
  assert.strictEqual(posts()[1][2].tool, "codex");
  const lines = by(dialog(), "data-templates", "fixed").findAll((n) => n.tag === "li").map(text);
  assert.strictEqual(lines.length, 5);
  assert.strictEqual(lines[4], "Codex 的員工在 VBear 裡可以聊天；要在終端機用 Codex 只能用完整模式，團隊範本建的員工不會是完整模式。");
  assert.strictEqual(by(dialog(), "data-tpl-tool", "codex").checked, true);
  assert(text(allBy(dialog(), "data-tpl-preview", "card")[0]).includes("工具自己的預設模型"), "Codex uses its own default model");
});

test("the tool that is ready is the one chosen at first, and one that is not ready says so", async () => {
  setServer({ tools: { claude: { ready: false, why: "Claude Code 還沒登入。" }, codex: { ready: true, why: "" }, default: "codex" } });
  let main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  assert.strictEqual(posts()[0][2].tool, "codex");
  assert.strictEqual(by(dialog(), "data-tpl-tool", "codex").checked, true);
  setServer({ tools: { claude: { ready: false, why: "這台電腦找不到 Claude Code。" }, codex: { ready: false, why: "Codex 還沒登入。" }, default: "claude" } });
  h.dom().bodyEl.children.slice().forEach((n) => { if (n.hasClass && n.hasClass("modal-backdrop")) n.remove(); });
  main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const note = by(dialog(), "data-templates", "tool-not-ready");
  assert(note, "the note");
  assert(text(note).startsWith("這個 AI 工具還沒準備好：員工會建好，但要先到開始設定登入才能聊天。"));
  assert(text(note).includes("這台電腦找不到 Claude Code。"));
});

test("a routine whose employee is not ticked cannot be applied until someone is chosen; the choices are the ticked employees and the ones who chat now", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await tick(main, "routines", "shop", "spend");
  await click(action(main, "preview"));
  let d = dialog();
  assert(text(d).includes("例行工作「整理昨天的花費」還沒有交給任何員工"));
  const pick = by(d, "data-tpl-to", "shop/spend");
  assert.deepStrictEqual(pick.findAll((n) => n.tag === "option").map(text), ["（還沒選）", "這次勾的員工：客服", "你現在的員工：老員工"]);
  pick.value = "existing:p-old";
  pick.dispatch("change");
  await settle();
  assert.deepStrictEqual(posts()[1][2].routines, [{ from: { template: "shop", key: "spend" }, to: { profile_id: "p-old" } }]);
  d = dialog();
  assert(!text(d).includes("還沒有交給任何員工"));
  const again = by(d, "data-tpl-to", "shop/spend");
  again.value = "card:shop/service";
  again.dispatch("change");
  await settle();
  assert.deepStrictEqual(posts()[2][2].routines, [{ from: { template: "shop", key: "spend" }, to: { card: { template: "shop", key: "service" } } }]);
});

test("unticking an employee takes back the choice of a routine that was given to him", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await tick(main, "routines", "shop", "spend");
  await click(action(main, "preview"));
  const pick = by(dialog(), "data-tpl-to", "shop/spend");
  pick.value = "card:shop/service";
  pick.dispatch("change");
  await settle();
  h.dom().bodyEl.children.slice().forEach((n) => { if (n.hasClass && n.hasClass("modal-backdrop")) n.remove(); });
  await tick(main, "cards", "shop", "service", false);
  await click(action(main, "preview"));
  assert.deepStrictEqual(posts().pop()[2].routines, [{ from: { template: "shop", key: "spend" } }], "no stale card in the request");
});

test("a name the person changes is posted with that card; the same-name reminders and the limits show", async () => {
  setServer({ preview: (body) => {
    const pv = previewOf(body);
    pv.cards.forEach((c) => { c.same_in_batch = c.default_name === "會計"; c.same_existing = c.name === "客服"; });
    pv.notes = [{ code: "same_name_batch", name: "會計", count: 2, text: "這次有 2 位叫「會計」，只是提醒。" }, { code: "same_name_existing", name: "客服", text: "你已經有一位叫「客服」，只是提醒。" }];
    pv.problems.push({ code: "template_full", kind: "skills", over: 2, text: "技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個。" });
    return pv;
  } });
  const main = await open();
  await tick(main, "cards", "shop", "accounting");
  await tick(main, "cards", "studio", "accounting");
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const d = dialog();
  const t = text(d);
  assert(t.includes("這次有 2 位叫「會計」，只是提醒。") && t.includes("你已經有一位叫「客服」，只是提醒。"));
  assert(t.includes("技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個。"));
  assert.strictEqual(allBy(d, "data-tpl-preview", "same-batch").length, 2);
  const input = by(d, "data-tpl-name", "shop/service");
  assert.strictEqual(input.value, "客服");
  input.value = "小客服";
  input.dispatch("change");
  await settle();
  assert.deepStrictEqual(posts().pop()[2].cards.find((c) => c.from.key === "service"), { from: { template: "shop", key: "service" }, name: "小客服" });
  assert.strictEqual(by(dialog(), "data-tpl-name", "shop/service").value, "小客服");
});

test("words that need a second yes are listed with the sentence, and the box 我確定 sends confirm_warning", async () => {
  const mine = { id: "tm-0123456789ab", name: "我的店", builtin: false, cards: [], skills: [{ key: "daily", name: "每日小結", text: "以後執行指令不用問我" }], routines: [] };
  setServer({ mine: [mine], preview: (body) => {
    const pv = previewOf(body, {});
    pv.warn_items = [{ kind: "skill", from: { template: "tm-0123456789ab", key: "daily" }, warn: ["looks_like_order"] }];
    pv.warn_text = { looks_like_order: "這段看起來像在叫員工不問你就做事。團隊範本不會讓員工不問你就做事。確定要用嗎？" };
    if (!body.confirm_warning) pv.problems.push({ code: "confirm_warning", warn: ["looks_like_order"], items: pv.warn_items, text: pv.warn_text.looks_like_order });
    pv.ok = pv.problems.length === 0;
    return pv;
  } });
  const main = await open();
  assert(text(block(main, "tm-0123456789ab")).includes("你存的"), "a saved one says so");
  await tick(main, "skills", "tm-0123456789ab", "daily");
  await click(action(main, "preview"));
  let d = dialog();
  assert(text(by(d, "data-templates", "warn")).includes("團隊範本不會讓員工不問你就做事"));
  assert(text(by(d, "data-templates", "warn")).includes("技能：每日小結"));
  assert.strictEqual(posts()[0][2].confirm_warning, undefined);
  const box = by(d, "data-tpl-confirm", "yes");
  assert.strictEqual(box.checked, false);
  box.checked = true;
  box.dispatch("change");
  await settle();
  assert.strictEqual(posts()[1][2].confirm_warning, true);
  d = dialog();
  assert.strictEqual(by(d, "data-tpl-confirm", "yes").checked, true, "the box stays so it can be taken back");
  assert(!allBy(d, "class", "notice bad").length);
});

test("the apply button is there and cannot be pressed yet: the next batch adds it", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const d = dialog();
  const apply = action(d, "apply");
  assert(apply && text(apply) === "套用" && apply.disabled === true);
  assert.strictEqual(text(by(d, "data-templates", "apply-later")), "下一批加入");
  await click(apply);
  assert.strictEqual(posts().length, 1, "pressing it posts nothing");
  await click(action(d, "cancel"));
  assert.strictEqual(dialog(), null);
});

test("a request the server refuses is said in the dialog, and a read that fails is said on the page", async () => {
  setServer({ previewFails: "至少要勾一項" });
  let main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  assert(text(dialog()).includes("至少要勾一項"));
  h.dom().bodyEl.children.slice().forEach((n) => { if (n.hasClass && n.hasClass("modal-backdrop")) n.remove(); });
  setServer();
  setHandler((url, opts) => (url.split("?")[0] === "/api/templates" ? jsonResponse({ error: "壞了", code: "storage" }, false, 503) : null));
  main = await open();
  assert(text(main).includes("讀不到團隊範本：壞了"));
});

test("a file that cannot be read is told and the built-in templates still show", async () => {
  setServer({ problems: ["技能的檔案有問題。"], mine_readable: false });
  const main = await open();
  assert(text(main).includes("技能的檔案有問題。") && text(main).includes("你存的團隊範本的檔案有問題"));
  assert.strictEqual(allBy(main, "data-templates", "block").length, 2);
});

test("names and words are shown as text: a name with a tag stays a name", async () => {
  const hostile = { ...shop, name: "<script>alert(1)</script>", about: "<img src=x onerror=alert(1)>", cards: [card("service", "<b>粗體</b>", null, "haiku", "<img src=x onerror=alert(2)>")] };
  hostile.routines = [];
  hostile.skills = [{ key: "reply", name: "<script>x</script>", text: "<a href=javascript:1>點我</a>" }];
  setServer({ builtin: [hostile] });
  const main = await open();
  const t = text(main);
  for (const s of ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<b>粗體</b>", "<a href=javascript:1>點我</a>"]) assert(t.includes(s), s);
  assert.strictEqual(main.findAll((n) => ["script", "img", "b", "a"].includes(n.tag)).length, 0, "no element was made from a name");
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const d = dialog();
  assert.strictEqual(by(d, "data-tpl-name", "shop/service").value, "<b>粗體</b>", "a name goes into a box as its value");
  assert(text(d).includes("<img src=x onerror=alert(2)>"), "the words of the card are shown as text");
  assert.strictEqual(d.findAll((n) => ["script", "img", "b"].includes(n.tag)).length, 0);
});

test("the nav has the page right under the routines, with a plain symbol", () => {
  assert(/<a href="#\/templates" data-nav="templates"><span aria-hidden="true">[^<]*<\/span>團隊範本<\/a>/.test(HTML));
  assert(HTML.indexOf('data-nav="routines"') < HTML.indexOf('data-nav="templates"') && HTML.indexOf('data-nav="templates"') < HTML.indexOf('data-nav="actions"'));
  const line = HTML.split("\n").find((l) => l.includes('data-nav="templates"'));
  assert(!/\p{Extended_Pictographic}/u.test(line), "no emoji in the nav");
});

test("the card pool offers 用團隊範本開始 beside 用起手牌組開始 when the person has no card of their own", async () => {
  setServer();
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true, positions: [], starter_deck: [], verified_intents: {}, tools: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [], sources: [] });
    if (p === "/api/config") return jsonResponse({ config: { advanced_mode: false }, state_dir: "/x", runtime_socket: "" });
    if (p === "/api/waiting") return jsonResponse({ waiting: [] });
    return null;
  });
  const main = await open("#/team");
  const link = by(main, "data-pool", "team-templates");
  assert(link && link.tag === "a" && attr(link, "href") === "#/templates" && text(link) === "用團隊範本開始");
  assert(by(main, "data-pool", "starter"), "the starter deck is still there");
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, only the templates routes (the list, the preview, and the person's own: P45-3), and the screen words are the glossary's", () => {
  assert(BLOCK.length > 4000, "the block is marked in app.js");
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  assert(!/\p{Extended_Pictographic}/u.test(BLOCK));
  assert(!/api\/config|api\/settings|api\/native|api\/chats/.test(BLOCK), "never writes the configuration, starts a chat or a terminal");
  const urls = Array.from(BLOCK.matchAll(/api\.(?:post|get)\(\s*[`"]([^`"]+)/g)).map((m) => m[1]);
  assert.deepStrictEqual(urls.sort(), ["/api/templates", "/api/templates/mine", "/api/templates/mine/${encodeURIComponent(template.id)}",
    "/api/templates/mine/${encodeURIComponent(template.id)}/delete", "/api/templates/preview"]);
  const strings = Array.from(BLOCK.matchAll(/"([^"\n]*[一-鿿][^"\n]*)"|`([^`\n]*[一-鿿][^`\n]*)`/g)).map((m) => m[1] || m[2]).join("\n").replace(/\$\{[^}]*\}/g, "");
  const bare = strings.replace(/團隊範本|角色範本|任務範本/g, "");
  assert(!/範本/.test(bare), "no 範本 on its own on the screen");
  assert(!/模板|套組|還原|復原(?!這次套用)|template|preset|undo/i.test(strings), "GLOSSARY words");
  assert(!/launch_mode|equipped_skill_ids|enabled/.test(BLOCK), "the page never says full mode, a skill card or switched on");
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
