// P45-1: the 團隊範本 page (#/templates): four fixed lines, one block for each template with three rows of tick boxes, 全選 and 全不選, ticking across
// templates, the line at the bottom, the preview (the AI tool, the fixed words, who a routine goes to, same names, the limits, a second yes), and the entry
// in the nav and in the card pool. The real web/app.js on a synthetic DOM, fetch answered by the test; every name and text here is made up and the page
// shows them as text only. P45-2 adds the press of 套用 (one post, the answer in the same dialog, a stop in the middle told as one), the 套用紀錄 and
// the dialog of 復原這次套用 (the list first, then 刪掉這些).
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
  const problems = routines.filter((r) => !r.assignee.kind).map((r) => ({ code: "no_assignee", from: r.from, text: `例行工作「${r.name}」還沒有交給任何員工，請在預覽裡選一位。` }));   // the server's own sentence (vbear/templates.py)
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
  state = { builtin: [shop, studio], mine: [], tools: TOOLS_READY, counts: { cards: 2, skills: 1, routines: 0 }, problems: [], mine_readable: true, preview: null, previewFails: null,
    applies: [], apply: null, undoPreview: null, undo: null, profiles: [], catalog: null, ...over };
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
    if (p === "/api/agent-profiles" && method === "GET") {
      return state.profiles === null ? jsonResponse({ error: "讀不到員工", code: "bad_request" }, false, 500) : jsonResponse({ ok: true, profiles: state.profiles });
    }
    if (p === "/api/agent-builder/catalog" && method === "GET") return state.catalog ? jsonResponse({ ok: true, ...state.catalog }) : null;
    if (p === "/api/templates" && method === "GET") {

      return jsonResponse({ ok: true, builtin: state.builtin, mine: state.mine, mine_readable: state.mine_readable, problem: state.mine_readable ? null : "你存的團隊範本的檔案有問題",
        problems: state.problems, applies: state.applies, counts: state.counts, current: { cards: [], skills: [], routines: [] }, limits: {}, tools: state.tools });
    }
    if (p === "/api/templates/preview" && method === "POST") {
      if (state.previewFails) return jsonResponse({ error: state.previewFails, code: "bad_request" }, false, 400);
      return jsonResponse({ ok: true, preview: state.preview ? state.preview(body) : previewOf(body) });
    }
    if (p === "/api/templates/apply" && method === "POST") {
      return state.apply ? state.apply(body) : jsonResponse({ ok: true, apply: appliedOf(body) }, true, 201);
    }
    const undoRoute = p.match(/^\/api\/templates\/applies\/(ta-[0-9a-f]{12})\/(undo-preview|undo)$/);
    if (undoRoute && method === "POST") {
      if (undoRoute[2] === "undo-preview") return jsonResponse({ ok: true, ...(state.undoPreview ? state.undoPreview(undoRoute[1]) : undoPreviewOf(undoRoute[1])) });
      return state.undo ? state.undo(body) : jsonResponse({ ok: true, deleted: [], kept: [], gone: [] });
    }
    return null;
  });
}
const A1 = "ta-0123456789ab";
function appliedOf(body) {
  const items = [];
  body.cards.forEach((c, i) => items.push({ kind: "card", id: `prof-${String(i).padStart(12, "a")}`, from: c.from, state: "made", why: null, name: c.name || "新員工" }));
  body.skills.forEach((x, i) => items.push({ kind: "skill", id: `k-${String(i).padStart(12, "1")}`, from: x.from, state: "made", why: null, name: "新技能" }));
  body.routines.forEach((x, i) => items.push({ kind: "routine", id: `r-${String(i).padStart(12, "2")}`, from: x.from, state: "made", why: null, name: "新定時工作" }));
  const n = (k) => items.filter((i) => i.kind === k).length;
  return { id: A1, at: 1760000000, tool: body.tool, state: "done", undone_at: null, counts: { cards: n("card"), skills: n("skill"), routines: n("routine") },
    left: { cards: n("card"), skills: n("skill"), routines: n("routine") }, items };
}
function undoPreviewOf(id) {
  return { apply: id, delete: [{ kind: "routine", id: "r-111111111111", name: "整理昨天的花費" }, { kind: "skill", id: "k-111111111111", name: "寫商品介紹" }, { kind: "card", id: "prof-aaaaaaaaaaaa", name: "會計" }],
    keep: [{ kind: "card", id: "prof-bbbbbbbbbbbb", name: "商品文案", why: "chatted", text: "你跟他聊過天" }], gone: [{ kind: "skill", id: "k-222222222222", name: null }], unsure: 0,
    notes: [{ code: "terminal", text: "如果你在指令視窗用過這些員工，VBear 看不出來；確定再刪。" }, { code: "skills", text: "VBear 不記錄技能有沒有被用過，只看有沒有改過。" }] };
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
    "團隊範本是一組現成的員工、常用做法和定時工作。勾你要的，按「預覽並套用」看清楚再套用。",
    "套用不用 AI、不花錢。員工一律用「每件事先問我」，跑指令、改檔案照舊每次都問你；記憶和共用資料夾照你平常的設定；定時工作建好是關著的。",
    "每次套用都可以「復原這次套用」：只刪這次建的、你沒改過也沒用過的，改過或用過的會留著並告訴你。團隊範本不會改或刪你原本就有的東西。",
    "團隊範本只存在這台電腦，不會上傳，也不能匯出。"]);
  assert.strictEqual(text(by(main, "data-templates", "ceo-line")), "要用幕僚長分配工作，還需要一位 CEO（到員工頁新增）。");
  const blocks = allBy(main, "data-templates", "block");
  assert.deepStrictEqual(blocks.map((b) => attr(b, "data-template-id")), ["shop", "studio"]);
  assert(text(block(main, "shop")).includes("小店") && text(block(main, "shop")).includes("VBear 內建") && text(block(main, "shop")).includes(shop.about));
  assert.deepStrictEqual(calls.filter((c) => c[0] !== "GET"), [], "nothing is posted when the page opens");
  assert.strictEqual(calls.filter((c) => c[1] === "/api/templates").length, 1);
});

test("the line about the CEO is shown only when the employees were read and none of them is a CEO", async () => {
  const ceoLine = (m) => m.find((n) => n.getAttribute && n.getAttribute("data-templates") === "ceo-line");
  setServer({ profiles: [] });
  assert(ceoLine(await open()), "no employee at all: said");
  setServer({ profiles: [{ id: "p-1", name: "工程師", position: "executor" }] });
  assert(ceoLine(await open()), "employees but no CEO: said");
  setServer({ profiles: [{ id: "p-1", name: "工程師", position: "executor" }, { id: "p-2", name: "小執", position: "planner" }] });
  assert(!ceoLine(await open()), "a CEO is there: not said");
  setServer({ profiles: null });
  assert(!ceoLine(await open()), "the employees could not be read: not said");
  assert.strictEqual(calls.filter((c) => c[0] !== "GET").length, 0);
});

test("each block has three rows with a tick box for every item, and the facts of each", async () => {
  setServer();
  const main = await open();
  const b = block(main, "shop");
  assert.deepStrictEqual(["cards", "skills", "routines"].map((k) => allBy(b, "data-tpl-pick", k).length), [3, 3, 2]);
  assert.deepStrictEqual(["cards", "skills", "routines"].map((k) => allBy(block(main, "studio"), "data-tpl-pick", k).length), [2, 1, 1]);
  const t = text(b);
  for (const s of ["客服", "商品文案", "會計", "社群媒體經理", "會計師", "建議模型 sonnet", "沒有指定職位", "回覆客人詢問", "整理昨天的花費", "每天　09:00", "交給：會計", "每週五　10:00", "交給：商品文案"]) assert(t.includes(s), s);
  assert(text(by(b, "data-tpl-text", "cards")).includes("你是客服。"));
  assert(allBy(b, "data-tpl-text", "skills").map(text).some((x) => x.includes("（貼在這裡）")), "the full text of a skill is there to open");
  assert(allBy(b, "data-tpl-pick", "cards").every((x) => x.checked === false), "nothing is ticked at first");
});

test("the line at the bottom counts what is ticked, across templates, and 預覽並套用 waits for a tick", async () => {
  setServer();
  const main = await open();
  const foot = by(main, "data-templates", "foot");
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：0 位員工、0 個常用做法、0 件定時工作");
  assert.strictEqual(action(foot, "preview").disabled, true);
  await tick(main, "cards", "shop", "copy");
  await tick(main, "cards", "studio", "accounting");
  await tick(main, "skills", "shop", "product");
  await tick(main, "routines", "studio", "todo");
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：2 位員工、1 個常用做法、1 件定時工作");
  assert.strictEqual(action(foot, "preview").disabled, false);
  await tick(main, "cards", "shop", "copy", false);
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：1 位員工、1 個常用做法、1 件定時工作");
});

test("全選 ticks everything in one block only, 全不選 clears it and leaves the other block's ticks", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "studio", "assistant");
  await click(action(block(main, "shop"), "all"));
  assert.strictEqual(text(by(main, "data-templates", "count")), "已勾：4 位員工、3 個常用做法、2 件定時工作");
  assert(allBy(block(main, "shop"), "data-tpl-pick", "cards").every((x) => x.checked === true));
  assert.strictEqual(allBy(block(main, "studio"), "data-tpl-pick", "cards").filter((x) => x.checked).length, 1);
  await click(action(block(main, "shop"), "none"));
  assert.strictEqual(text(by(main, "data-templates", "count")), "已勾：1 位員工、0 個常用做法、0 件定時工作");
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
  assert.strictEqual(text(by(d, "data-templates", "summary")), "這次會建：2 位員工、1 個常用做法、1 件定時工作。");
  assert.strictEqual(text(by(d, "data-templates", "after")), "套用後：員工 4/500、常用做法 2/100、定時工作 1/20");
  assert.deepStrictEqual(allBy(d, "data-tpl-preview", "card").length, 2);
  assert.strictEqual(by(d, "data-tpl-to", "shop/spend").value, "card:shop/accounting");
});

// P48-6: the preview dialog (names in the .input style, 沒有指定職位, the model's own label when the catalog has one) and the page's models
const CATALOG_WITH_LABEL = { model_options: { claude: { latest: [], listed: [{ value: "sonnet", label: "索奈（測試用名稱）" }], observed: [], problem: "" }, codex: { latest: [], listed: [], observed: [], problem: "" } } };
const CATALOG_PLAIN = { model_options: { claude: { latest: [{ value: "sonnet", label: "sonnet" }, { value: "haiku", label: "haiku" }], listed: [], observed: [], problem: "" } } };
test("P48-6: the preview's name box has the .input style, a card without a position says 沒有指定職位, never 未指定", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await tick(main, "cards", "shop", "copy");
  await click(action(main, "preview"));
  const d = dialog();
  const names = allBy(d, "data-tpl-name", "shop/service").concat(allBy(d, "data-tpl-name", "shop/copy"));
  assert.strictEqual(names.length, 2);
  for (const input of names) assert(input.hasClass("input"), "the name box is in the .input style");
  const t = text(by(d, "data-templates", "preview-cards"));
  assert(t.includes("沒有指定職位"), t);
  assert(!t.includes("未指定"), t);
  assert(!text(main).includes("未指定"), "the page itself never says 未指定 either");
});

test("P48-6: the model is said with the label the catalog gives it, as it is when there is no label or no catalog, and the labels are only read", async () => {
  setServer({ catalog: CATALOG_WITH_LABEL });
  let main = await open();
  assert(text(block(main, "shop")).includes("建議模型 索奈（測試用名稱）"), "the template's own card line");
  assert(text(block(main, "shop")).includes("建議模型 haiku"), "a model with no label stays as it is");
  await tick(main, "cards", "shop", "copy");
  await click(action(main, "preview"));
  const line = text(by(dialog(), "data-templates", "preview-cards"));
  assert(line.includes("索奈（測試用名稱）") && !line.includes("sonnet"), line);
  assert.deepStrictEqual(posts().map((c) => c[1]), ["/api/templates/preview"]);
  setServer({ catalog: CATALOG_PLAIN });
  main = await open();
  assert(text(block(main, "shop")).includes("建議模型 sonnet"));
  setServer({ catalog: null });                        // the catalog could not be read: the names as they are, nothing guessed
  main = await open();
  await tick(main, "cards", "shop", "copy");
  await click(action(main, "preview"));
  assert(text(by(dialog(), "data-templates", "preview-cards")).includes("sonnet"));
  assert(text(block(main, "shop")).includes("建議模型 sonnet"));
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
    "員工一律用「每件事先問我」：跑指令、改檔案照舊每次都問你。團隊範本不會建出「完全交給他（有風險）」的員工。",
    "記憶照你平常的設定（Claude Code 的員工帶記憶，Codex 的員工不帶，因為記憶會送到 OpenAI）；共用資料夾都關著。要改，到記憶頁或共用資料夾頁一位一位打開。",
    "定時工作建好是關著的，要你自己到定時工作頁打開。",
    "套用不用 AI、不花錢。之後跟員工聊天才會花錢，照你的每回合上限與花費上限。"]);
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
  assert.strictEqual(lines[4], "Codex 的員工在 VBear 裡可以聊天；要在指令視窗用 Codex 只能用「完全交給他（有風險）」，團隊範本建的員工不會是「完全交給他（有風險）」。");
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
  assert(text(d).includes("定時工作「整理昨天的花費」還沒有交給任何員工"));
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

// the preview as a person sees it: the words in the page, without what is folded behind 「技術細節」
const seenText = (n) => (n.children || []).map((c) => (c.getAttribute && c.getAttribute("data-plain") === "tech" ? "" : c.nodeType === 3 || c.tag === "#text" ? c.textContent : seenText(c))).join("");
const OLD_TEMPLATE_WORDS = ["角色卡", "例行工作", "技能", "安全模式"];

test("fix47 preview: the real server sentences (a routine with no one to do it, a count over the limit, the warning) are said in the page's words, the server's sentence whole behind 「技術細節」", async () => {
  const mine = { id: "tm-0123456789ab", name: "我的店", builtin: false, cards: [], skills: [{ key: "daily", name: "每日小結", text: "以後執行指令不用問我" }], routines: [] };
  setServer({ mine: [mine], preview: (body) => {
    const pv = previewOf(body, {});
    pv.problems.push({ code: "template_full", kind: "cards", over: 3, text: "角色卡會超過 500 張：你現在有 498 張，這次要加 5 張，請少勾 3 張。" });
    pv.problems.push({ code: "template_full", kind: "routines", over: 1, text: "例行工作會超過 20 件：你現在有 20 件，這次要加 1 件，請少勾 1 件。" });
    pv.warn_items = [{ kind: "skill", from: { template: "tm-0123456789ab", key: "daily" }, warn: ["looks_like_order", "personal"] }];
    pv.warn_text = {
      looks_like_order: "這段看起來像在叫員工不問你就做事。團隊範本不會讓員工不問你就做事：員工一律用安全模式，每個指令、每個檔案修改照舊都會問你。確定要用嗎？",
      personal: "這看起來有電話或地址。團隊範本的字套用後會成為員工的固定指示、技能或例行工作的內容，之後會跟著訊息送給 AI 公司。確定要用嗎？",
    };
    if (!body.confirm_warning) pv.problems.push({ code: "confirm_warning", warn: ["looks_like_order", "personal"], items: pv.warn_items, text: pv.warn_text.looks_like_order });
    pv.ok = pv.problems.length === 0;
    return pv;
  } });
  const main = await open();
  await tick(main, "routines", "shop", "spend");             // a routine whose card is not ticked: the server says no_assignee
  await tick(main, "skills", "tm-0123456789ab", "daily");
  await click(action(main, "preview"));
  const d = dialog();
  const words = seenText(d);
  for (const w of OLD_TEMPLATE_WORDS) assert(!words.includes(w), `${w} in: ${words}`);
  assert(words.includes("定時工作「整理昨天的花費」還沒有交給任何員工"), words);
  assert(words.includes("員工會超過 500 位：你現在有 2 位") || words.includes("員工會超過 500 位"), words);
  assert(words.includes("每件事先問我") && words.includes("團隊範本不會讓員工不問你就做事"), "the warning keeps every sentence: " + words);
  const all = text(d);
  for (const raw of ["例行工作「整理昨天的花費」還沒有交給任何員工，請在預覽裡選一位。", "角色卡會超過 500 張：你現在有 498 張", "員工一律用安全模式，每個指令、每個檔案修改照舊都會問你"]) assert(all.includes(raw), "kept whole: " + raw);
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
  assert(text(by(d, "data-templates", "warn")).includes("常用做法：每日小結"));
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

const closeDialogs = () => h.dom().bodyEl.children.slice().forEach((n) => { if (n.hasClass && n.hasClass("modal-backdrop")) n.remove(); });
const applyRow = (id = A1, over = {}) => ({ id, at: 1760000000, tool: "claude", state: "done", undone_at: null, counts: { cards: 2, skills: 1, routines: 1 }, left: { cards: 2, skills: 1, routines: 1 },
  items: [{ kind: "card", id: "prof-aaaaaaaaaaaa", from: { template: "shop", key: "accounting" }, state: "made", why: null, name: "會計" },
    { kind: "card", id: "prof-bbbbbbbbbbbb", from: { template: "shop", key: "copy" }, state: "made", why: null, name: "商品文案" },
    { kind: "skill", id: "k-111111111111", from: { template: "shop", key: "product" }, state: "made", why: null, name: "寫商品介紹" },
    { kind: "routine", id: "r-111111111111", from: { template: "shop", key: "spend" }, state: "made", why: null, name: "整理昨天的花費" }], ...over });

test("the apply button waits for a preview with nothing in the way, and one press posts the same body once and says what was made in the same dialog", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "accounting");
  await tick(main, "skills", "shop", "product");
  await tick(main, "routines", "shop", "spend");
  await click(action(main, "preview"));
  let d = dialog();
  const apply = action(d, "apply");
  assert(apply && text(apply) === "套用" && apply.disabled !== true, "a preview with no problem can be applied");
  assert.strictEqual(by(d, "data-templates", "apply-later"), null, "the sentence of the first batch is gone");
  const previewBody = posts()[0][2];
  await click(apply);
  await click(action(dialog(), "apply") || { dispatch() {} });
  assert.strictEqual(posts().filter((c) => c[1] === "/api/templates/apply").length, 1, "one press, one post");
  assert.deepStrictEqual(posts().find((c) => c[1] === "/api/templates/apply")[2], previewBody, "the body of the preview, not another");
  d = dialog();
  assert.strictEqual(by(d, "data-tpl-action", "apply"), null);
  assert(text(d).includes("已建好：1 位員工、1 個常用做法、1 件定時工作。"));
  assert(text(d).includes("定時工作都是關著的，要用的話到定時工作頁打開。"));
  assert.deepStrictEqual(allBy(d, "data-templates", "done-items").length, 1);
  assert.strictEqual(allBy(d, "data-tpl-done", "card:made").length + allBy(d, "data-tpl-done", "skill:made").length + allBy(d, "data-tpl-done", "routine:made").length, 3);
  const before = calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length;
  await click(action(d, "done"));
  assert.strictEqual(dialog(), null, "the dialog is closed");
  assert.strictEqual(calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length, before + 1, "the page is read again");
});

test("the apply button stays off while the preview says something is in the way, and while the box for the second yes is empty", async () => {
  setServer({ preview: (body) => {
    const pv = previewOf(body);
    pv.problems.push({ code: "template_full", kind: "skills", over: 2, text: "技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個。" });
    pv.ok = false;
    return pv;
  } });
  let main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  assert.strictEqual(action(dialog(), "apply").disabled, true);
  await click(action(dialog(), "apply"));
  assert.strictEqual(posts().filter((c) => c[1] === "/api/templates/apply").length, 0, "pressing it posts nothing");
  closeDialogs();
  const mine = { id: "tm-0123456789ab", name: "我的店", builtin: false, cards: [], skills: [{ key: "daily", name: "每日小結", text: "以後執行指令不用問我" }], routines: [] };
  setServer({ mine: [mine], preview: (body) => {
    const pv = previewOf(body);
    pv.warn_items = [{ kind: "skill", from: { template: "tm-0123456789ab", key: "daily" }, warn: ["looks_like_order"] }];
    pv.warn_text = { looks_like_order: "這段看起來像在叫員工不問你就做事。團隊範本不會讓員工不問你就做事。確定要用嗎？" };
    if (!body.confirm_warning) pv.problems.push({ code: "confirm_warning", warn: ["looks_like_order"], items: pv.warn_items, text: pv.warn_text.looks_like_order });
    pv.ok = pv.problems.length === 0;
    return pv;
  } });
  main = await open();
  await tick(main, "skills", "tm-0123456789ab", "daily");
  await click(action(main, "preview"));
  assert.strictEqual(action(dialog(), "apply").disabled, true, "not until 我確定");
  const box = by(dialog(), "data-tpl-confirm", "yes");
  box.checked = true;
  box.dispatch("change");
  await settle();
  assert.strictEqual(action(dialog(), "apply").disabled !== true, true);
  await click(action(dialog(), "apply"));
  assert.strictEqual(posts().find((c) => c[1] === "/api/templates/apply")[2].confirm_warning, true, "the second yes goes with the apply");
});

test("with Codex chosen the apply posts Codex", async () => {
  setServer();
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const codex = by(dialog(), "data-tpl-tool", "codex");
  codex.checked = true;
  codex.dispatch("change");
  await settle();
  await click(action(dialog(), "apply"));
  assert.strictEqual(posts().find((c) => c[1] === "/api/templates/apply")[2].tool, "codex");
});

test("an apply that stopped in the middle is said as that, with what was made and what stopped it, and never as done", async () => {
  const stopped = { ...appliedOf({ tool: "claude", cards: [{ from: { template: "shop", key: "copy" } }], skills: [{ from: { template: "shop", key: "reply" } }, { from: { template: "shop", key: "product" } }], routines: [] }),
    state: "partial" };
  stopped.items[2] = { ...stopped.items[2], state: "failed", why: "skill_full", name: null };
  stopped.counts = { cards: 1, skills: 1, routines: 0 };
  setServer({ apply: () => jsonResponse({ error: "建到一半停下了：已建好 1 位員工、1 個技能、0 件定時工作；可以按「復原這次套用」。", code: "template_partial", apply: stopped }, false, 409) });
  const main = await open();
  await tick(main, "cards", "shop", "copy");
  await tick(main, "skills", "shop", "reply");
  await tick(main, "skills", "shop", "product");
  await click(action(main, "preview"));
  await click(action(dialog(), "apply"));
  const d = dialog();
  assert(text(d).includes("建到一半停下了：已建好 1 位員工、1 個技能、0 件定時工作；可以按「復原這次套用」。"));
  assert(!text(d).includes("已建好：1 位員工"), "not told as done");
  assert.deepStrictEqual(allBy(d, "data-templates", "done-items")[0].findAll((n) => n.tag === "li").map(text), ["員工：新員工　已建好", "常用做法：新技能　已建好", "常用做法：寫商品介紹　停在這裡"]);
  assert(action(d, "done"));
});

test("an apply the server refuses stays in the preview with the reason, and nothing is told as made", async () => {
  setServer({ apply: () => jsonResponse({ error: "技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個。", code: "template_full" }, false, 409) });
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  await click(action(dialog(), "apply"));
  const d = dialog();
  assert(text(d).includes("技能會超過 100 個"));
  assert(action(d, "apply") && action(d, "apply").disabled !== true, "it can be tried again");
  assert.strictEqual(by(d, "data-templates", "done-items"), null);
});

test("the record of the applies: one row for each with the count, the tool, the state and the template each thing came from, and 復原這次套用 only while something is left", async () => {
  const hostile = applyRow("ta-aaaaaaaaaaaa", { items: [{ kind: "card", id: "prof-aaaaaaaaaaaa", from: { template: "shop", key: "accounting" }, state: "made", why: null, name: "<img src=x onerror=alert(1)>" },
    { kind: "skill", id: "k-111111111111", from: { template: "tm-0123456789ab", key: "gone" }, state: "made", why: null, name: null },
    { kind: "routine", id: "r-111111111111", from: { template: "shop", key: "spend" }, state: "deleted", why: null, name: null }] });
  const all = applyRow("ta-bbbbbbbbbbbb", { state: "partial", left: { cards: 0, skills: 0, routines: 0 }, undone_at: 1760000100, tool: "codex" });
  const cut = applyRow("ta-cccccccccccc", { state: "interrupted" });
  setServer({ applies: [hostile, all, cut] });
  const main = await open();
  const section = by(main, "data-templates", "applies");
  assert.strictEqual(text(section.find((n) => n.tag === "h2")), "套用紀錄");
  assert.strictEqual(text(by(section, "data-templates", "applies-limit")), "只能復原最近 50 次套用；更早的東西照樣留著，要刪請到各自的頁面。");
  const rows = allBy(section, "data-tpl-apply-status", "done").concat(allBy(section, "data-tpl-apply-status", "partial"), allBy(section, "data-tpl-apply-status", "interrupted"));
  assert.strictEqual(rows.length, 3);
  const r1 = allBy(section, "data-tpl-apply", "ta-aaaaaaaaaaaa").find((n) => n.tag === "li");
  assert(text(r1).includes("建了 2 位員工、1 個常用做法、1 件定時工作") && text(r1).includes("Claude Code") && text(r1).includes("完成"));
  assert(text(r1).includes("<img src=x onerror=alert(1)>") && text(r1).includes("來自：小店") && text(r1).includes("來自：（團隊範本已刪除）") && text(r1).includes("（已刪掉）"));
  assert.strictEqual(section.findAll((n) => n.tag === "img").length, 0, "a name is text");
  assert(action(r1, "undo"), "something is left, so it can be undone");
  const r2 = allBy(section, "data-tpl-apply", "ta-bbbbbbbbbbbb").find((n) => n.tag === "li");
  assert.strictEqual(action(r2, "undo"), null, "nothing left, nothing to undo");
  assert(text(r2).includes("建到一半停下了") && text(r2).includes("Codex") && by(r2, "data-tpl-apply-undone", "yes"));
  const r3 = allBy(section, "data-tpl-apply", "ta-cccccccccccc").find((n) => n.tag === "li");
  assert.strictEqual(text(by(r3, "data-tpl-apply-note", "interrupted")), "這次套用中斷了，最後一個常用做法或定時工作可能已經建好但沒記到，復原不會刪它；請到常用做法頁、定時工作頁看看。");
});

test("with no apply yet the record says so, and nothing can be undone", async () => {
  setServer();
  const main = await open();
  assert.strictEqual(text(by(main, "data-templates", "applies-none")), "還沒有套用過。");
  assert.strictEqual(action(main, "undo"), null);
});

test("復原這次套用 first posts for the list and shows it: what goes, what stays and why, what is gone, and the two notes word for word; nothing is deleted yet", async () => {
  setServer({ applies: [applyRow()] });
  const main = await open();
  await click(action(main, "undo"));
  assert.deepStrictEqual(posts(), [["POST", `/api/templates/applies/${A1}/undo-preview`, {}]]);
  const d = dialog();
  assert.strictEqual(text(d.find((n) => n.tag === "h2")), "復原這次套用");
  assert.deepStrictEqual(allBy(d, "data-templates", "undo-delete")[0].findAll((n) => n.tag === "li").map(text), ["定時工作：整理昨天的花費", "常用做法：寫商品介紹", "員工：會計"]);
  assert.deepStrictEqual(allBy(d, "data-templates", "undo-keep")[0].findAll((n) => n.tag === "li").map(text), ["員工：商品文案　你跟他聊過天"]);
  assert.deepStrictEqual(allBy(d, "data-templates", "undo-gone")[0].findAll((n) => n.tag === "li").map(text), ["常用做法：（沒有名字）　你自己刪掉了"]);
  assert.deepStrictEqual(allBy(d, "data-tpl-undo-note", "terminal").concat(allBy(d, "data-tpl-undo-note", "skills")).map(text),
    ["如果你在指令視窗用過這些員工，VBear 看不出來；確定再刪。", "VBear 不記錄技能有沒有被用過，只看有沒有改過。"]);
  const confirm = action(d, "undo-confirm");
  assert(text(confirm) === "刪掉這些" && confirm.disabled !== true);
  assert(action(d, "undo-cancel"));
});

test("刪掉這些 posts exactly the ids of the list, once, then says what was deleted and what stayed; 完成 reads the page again", async () => {
  setServer({ applies: [applyRow()], undo: () => jsonResponse({ ok: true, deleted: [{ kind: "routine", id: "r-111111111111", name: "整理昨天的花費" }, { kind: "skill", id: "k-111111111111", name: "寫商品介紹" }, { kind: "card", id: "prof-aaaaaaaaaaaa", name: "會計" }],
    kept: [{ kind: "card", id: "prof-bbbbbbbbbbbb", name: "商品文案", why: "chatted", text: "你跟他聊過天" }], gone: [] }) });
  const main = await open();
  await click(action(main, "undo"));
  const press = action(dialog(), "undo-confirm");
  await click(press);
  await click(action(dialog(), "undo-confirm") || { dispatch() {} });
  const undos = posts().filter((c) => c[1] === `/api/templates/applies/${A1}/undo`);
  assert.deepStrictEqual(undos.map((c) => c[2]), [{ delete: ["r-111111111111", "k-111111111111", "prof-aaaaaaaaaaaa"] }], "only what the list said, once");
  const d = dialog();
  assert.strictEqual(text(by(d, "data-templates", "undo-summary")), "已刪掉 3 項；留著 1 項。");
  assert.deepStrictEqual(allBy(d, "data-templates", "undo-kept")[0].findAll((n) => n.tag === "li").map(text), ["員工：商品文案　你跟他聊過天"]);
  const before = calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length;
  await click(action(d, "undo-done"));
  assert.strictEqual(dialog(), null);
  assert.strictEqual(calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length, before + 1);
});

test("cancelling the list deletes nothing; a list with nothing to delete cannot be pressed; an error is said", async () => {
  setServer({ applies: [applyRow()] });
  let main = await open();
  await click(action(main, "undo"));
  await click(action(dialog(), "undo-cancel"));
  assert.strictEqual(dialog(), null);
  assert.strictEqual(posts().filter((c) => c[1].endsWith("/undo")).length, 0);
  setServer({ applies: [applyRow()], undoPreview: (id) => ({ ...undoPreviewOf(id), delete: [], notes: [] }) });
  main = await open();
  await click(action(main, "undo"));
  assert.strictEqual(action(dialog(), "undo-confirm").disabled, true);
  assert.strictEqual(text(by(dialog(), "data-templates", "undo-nothing")), "沒有可以刪的。");
  closeDialogs();
  setServer({ applies: [applyRow()], undo: () => jsonResponse({ error: "技能的檔案有問題", code: "skills_unreadable" }, false, 503) });
  main = await open();
  await click(action(main, "undo"));
  await click(action(dialog(), "undo-confirm"));
  assert(text(dialog()).includes("技能的檔案有問題"));
  assert(action(dialog(), "undo-confirm"), "the list is still there");
});

test("names in the list of the undo are text", async () => {
  setServer({ applies: [applyRow()], undoPreview: (id) => ({ ...undoPreviewOf(id), delete: [{ kind: "card", id: "prof-aaaaaaaaaaaa", name: "<script>alert(1)</script>" }],
    keep: [{ kind: "skill", id: "k-111111111111", name: "<img src=x onerror=alert(2)>", why: "changed", text: "你改過" }] }) });
  const main = await open();
  await click(action(main, "undo"));
  const d = dialog();
  assert(text(d).includes("<script>alert(1)</script>") && text(d).includes("<img src=x onerror=alert(2)>"));
  assert.strictEqual(d.findAll((n) => ["script", "img"].includes(n.tag)).length, 0);
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

test("(P47-1) the page is a page of the 員工 item of the menu (it lights it), with a plain symbol", () => {
  assert(/<a href="#\/employees" data-nav="employees"><span aria-hidden="true">[^<]*<\/span>員工<\/a>/.test(HTML));
  const appSrc = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  assert(/\btemplates: "employees"/.test(appSrc.slice(appSrc.indexOf("const NAV_PARENT = {"), appSrc.indexOf("const ADVANCED_NAV"))), "the team templates light 員工");
  const line = HTML.split("\n").find((l) => l.includes('data-nav="employees"'));
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
  assert.deepStrictEqual(urls.sort(), ["/api/agent-builder/catalog", "/api/agent-profiles", "/api/templates", "/api/templates/applies/${encodeURIComponent(apply.id)}/undo", "/api/templates/applies/${encodeURIComponent(apply.id)}/undo-preview",
    "/api/templates/apply", "/api/templates/mine", "/api/templates/mine/${encodeURIComponent(template.id)}",
    "/api/templates/mine/${encodeURIComponent(template.id)}/delete", "/api/templates/preview"], "the routes of the page: the list, the preview, the apply, the two of 復原這次套用, the person's own team templates, the read of the employees (for the line about the CEO), and the read of the catalog (P48-6: the labels of the models, read only)");
  const strings = Array.from(BLOCK.matchAll(/"([^"\n]*[一-鿿][^"\n]*)"|`([^`\n]*[一-鿿][^`\n]*)`/g)).map((m) => m[1] || m[2]).join("\n").replace(/\$\{[^}]*\}/g, "");
  const bare = strings.replace(/團隊範本|角色範本|任務範本/g, "");
  assert(!/範本/.test(bare), "no 範本 on its own on the screen");
  assert(!/模板|套組|還原|復原(?!這次套用|不會刪它|最近 50 次套用)|template|preset|undo/i.test(strings), "GLOSSARY words");
  assert(!/launch_mode|equipped_skill_ids|enabled/.test(BLOCK), "the page never says full mode, a skill card or switched on");
});

test("AGY: the third choice shows only when the server offers it, adds its own lines, and asks again with agy; an AGY not yet checked says so", async () => {
  setServer({ tools: { ...TOOLS_READY, agy: { ready: true, why: "", chat_verified: true }, default: "claude" } });
  const main = await open();
  await tick(main, "cards", "shop", "service");
  await click(action(main, "preview"));
  const radios = ["claude", "codex", "agy"].map((k) => allBy(dialog(), "data-tpl-tool", k).length);
  assert.deepStrictEqual(radios, [1, 1, 1]);
  assert(text(by(dialog(), "data-templates", "tool")).includes("AGY"));
  let lines = by(dialog(), "data-templates", "fixed").findAll((n) => n.tag === "li").map(text);
  assert.strictEqual(lines.length, 4, "no AGY line until AGY is chosen");
  const agy = by(dialog(), "data-tpl-tool", "agy");
  agy.checked = true;
  agy.dispatch("change");
  await settle();
  assert.strictEqual(posts()[posts().length - 1][2].tool, "agy");
  lines = by(dialog(), "data-templates", "fixed").findAll((n) => n.tag === "li").map(text);
  assert.strictEqual(lines.length, 5);
  for (const w of ["AGY 的員工預設不帶記憶", "送到 Google", "AGY 技能", "「完全交給他（有風險）」"]) assert(lines[4].includes(w), w);
  assert.strictEqual(by(dialog(), "data-tpl-tool", "agy").checked, true);
  h.dom().bodyEl.children.slice().forEach((n) => { if (n.hasClass && n.hasClass("modal-backdrop")) n.remove(); });
  setServer({ tools: { ...TOOLS_READY, agy: { ready: true, why: "", chat_verified: false }, default: "agy" } });
  const again = await open();
  await tick(again, "cards", "shop", "service");
  await click(action(again, "preview"));
  assert.strictEqual(by(dialog(), "data-tpl-tool", "agy").checked, true, "the default can be AGY");
  const more = by(dialog(), "data-templates", "fixed").findAll((n) => n.tag === "li").map(text);
  assert.strictEqual(more.length, 6);
  assert(more[5].includes("還沒通過聊天驗證") && more[5].includes("驗證聊天") && more[5].includes("Google 方案"), more[5]);
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
