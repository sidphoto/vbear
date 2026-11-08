// P45-3: saving the person's own team templates on the 團隊範本 page: the 「你現在的」 block (for saving only), the 存成團隊範本 button and its dialog
// (what is ticked in the blocks and in 「你現在的」, the fixed words, a refusal, a second yes, what the answer says was left out), 改名 and 刪除 of a
// saved one, and a file that cannot be read. The real web/app.js on a synthetic DOM, fetch answered by the test; every name and text is made up and the
// page shows them as text only.
// Run: node tests/frontend/templates_mine.cjs   (exit code 0 = pass)
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

const card = (key, name, position, model, instructions) => ({ key, name, position, claude_model: model, instructions });
const shop = {
  id: "shop", name: "小店", builtin: true, about: "一個人開網路或實體小店。",
  cards: [card("service", "客服", null, "haiku", "你是客服。"), card("accounting", "會計", "accountant", "haiku", "你是會計。")],
  skills: [{ key: "reply", name: "回覆客人詢問", text: "請幫我回覆。" }],
  routines: [{ key: "spend", name: "整理昨天的花費", text: "請整理。", days: [0, 1, 2, 3, 4, 5, 6], times: ["09:00"], who: "accounting" }],
};
const mineOne = { id: "tm-0123456789ab", name: "我的店", builtin: false, cards: [card("boss", "店長", null, null, "你是店長的小幫手。")],
  skills: [{ key: "daily", name: "每日小結", text: "請寫小結。" }], routines: [] };
const NOW = {
  cards: [{ id: "prof-aaaaaaaaaaaa", name: "虛構會計", position: "accountant", tool: "claude", can_chat: true },
    { id: "prof-bbbbbbbbbbbb", name: "<b>粗體員工</b>", position: null, tool: "codex", can_chat: true }],
  skills: [{ id: "k-aaaaaaaaaaaa", name: "虛構技能" }, { id: "k-bbbbbbbbbbbb", name: "<script>alert(1)</script>" }],
  routines: [{ id: "r-aaaaaaaaaaaa", name: "虛構例行" }],
};
const TOOLS_READY = { claude: { ready: true, why: "" }, codex: { ready: true, why: "" }, default: "claude" };

let state;
let calls;
function setServer(over = {}) {
  state = { builtin: [shop], mine: [], current: NOW, mine_readable: true, save: null, ...over };
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
        problems: [], applies: [], counts: { cards: 2, skills: 2, routines: 1 }, current: state.current,
        limits: { max_mine: 20, max_name: 40, per_template: { cards: 12, skills: 24, routines: 12 }, per_apply: { cards: 12, skills: 24, routines: 12 } }, tools: TOOLS_READY });
    }
    if (p === "/api/templates/mine" && method === "POST") {
      if (state.save) return state.save(body);
      return jsonResponse({ ok: true, template: { id: "tm-ffffffffffff", name: body.name, builtin: false, cards: [], skills: [], routines: [] }, notes: [] }, true, 201);
    }
    const found = /^\/api\/templates\/mine\/(tm-[0-9a-f]{12})(\/delete)?$/.exec(p);
    if (found && method === "POST") {
      if (state.edit) return state.edit(found[2] ? "delete" : "rename", body);
      return jsonResponse(found[2] ? { ok: true, deleted: found[1] } : { ok: true, template: { ...mineOne, name: body.name } });
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
const dialogs = () => h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop"));
const dialog = () => dialogs()[0];
const by = (root, key, value) => root.find((n) => attr(n, key) === value);
const allBy = (root, key, value) => root.findAll((n) => attr(n, key) === value);
const action = (root, name) => root.find((n) => n.tag === "button" && attr(n, "data-tpl-action") === name);
const click = async (node) => { assert(node, "a button"); assert(!node.disabled, "the button can be pressed"); node.dispatch("click"); await settle(); };
const tickNow = async (root, kind, id, on = true) => {
  const box = root.find((n) => attr(n, "data-tpl-now") === kind && attr(n, "data-tpl-id") === id);
  assert(box, `now box ${kind} ${id}`);
  box.checked = on; box.dispatch("change"); await settle();
};
const tickBlock = async (root, kind, template, key, on = true) => {
  const box = root.find((n) => attr(n, "data-tpl-pick") === kind && attr(n, "data-tpl-template") === template && attr(n, "data-tpl-key") === key);
  assert(box, `box ${kind} ${template}/${key}`);
  box.checked = on; box.dispatch("change"); await settle();
};
const nameBox = (d) => by(d, "data-tpl-save", "name");
const typeName = (d, value) => { const b = nameBox(d); b.value = value; b.dispatch("input"); b.dispatch("change"); };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("「你現在的」 lists what the person has, with a tick box each, and says it is only for saving", async () => {
  setServer();
  const main = await open();
  const now = by(main, "data-templates", "now");
  assert(now, "the block is there");
  assert.strictEqual(text(by(now, "data-templates", "now-line")), "這一區只給「存成團隊範本」用：這些已經在你這裡了，套用時不會再建一次。");
  assert.deepStrictEqual(["cards", "skills", "routines"].map((k) => allBy(now, "data-tpl-now", k).length), [2, 2, 1]);
  assert.strictEqual(allBy(now, "data-tpl-pick", "cards").length, 0, "they can not be ticked for applying: no apply tick box here");
  const t = text(now);
  for (const s of ["虛構會計", "會計師", "虛構技能", "虛構例行", "<b>粗體員工</b>", "<script>alert(1)</script>"]) assert(t.includes(s), s);
  assert.strictEqual(now.findAll((n) => ["b", "script"].includes(n.tag)).length, 0, "a name stays a name");
  assert.deepStrictEqual(calls.filter((c) => c[0] !== "GET"), []);
});

test("a person with nothing yet is told so, and the blocks of the page do not count the ticks of 「你現在的」", async () => {
  setServer({ current: { cards: [], skills: [], routines: [] } });
  const main = await open();
  assert.strictEqual(text(by(main, "data-templates", "now-empty")), "你現在還沒有員工、技能或例行工作。");
  assert.strictEqual(action(by(main, "data-templates", "foot"), "save").disabled, true);
});

test("the buttons wait for a tick, in the blocks or in 「你現在的」, and the line at the bottom counts only the blocks", async () => {
  setServer();
  const main = await open();
  const foot = by(main, "data-templates", "foot");
  const nowSave = action(by(main, "data-templates", "now"), "save-now");
  assert.strictEqual(action(foot, "save").disabled, true);
  assert.strictEqual(nowSave.disabled, true);
  assert.strictEqual(text(by(main, "data-templates", "now-count")), "你現在的，已勾：0 位員工、0 個技能、0 件例行工作");
  await tickNow(main, "cards", "prof-aaaaaaaaaaaa");
  assert.strictEqual(action(foot, "save").disabled, false);
  assert.strictEqual(nowSave.disabled, false);
  assert.strictEqual(text(by(main, "data-templates", "now-count")), "你現在的，已勾：1 位員工、0 個技能、0 件例行工作");
  assert.strictEqual(text(by(foot, "data-templates", "count")), "已勾：0 位員工、0 個技能、0 件例行工作", "the apply line is only for the blocks");
  assert.strictEqual(action(foot, "preview").disabled, true, "ticking something that is already there never makes it appliable");
  await tickNow(main, "cards", "prof-aaaaaaaaaaaa", false);
  assert.strictEqual(action(foot, "save").disabled, true);
  await tickBlock(main, "skills", "shop", "reply");
  assert.strictEqual(action(foot, "save").disabled, false, "a tick in a block is enough");
});

test("the dialog posts what is ticked in the blocks first and what the person has after, with the name, and says what was saved", async () => {
  setServer({ mine: [mineOne] });
  state.save = (body) => jsonResponse({ ok: true, template: { id: "tm-ffffffffffff", name: body.name, builtin: false, cards: [card("a", "客服", null, null, null), card("card_1", "虛構會計", "accountant", "haiku", "x")],
    skills: [], routines: [] }, notes: [{ code: "full_mode_saved_safe", kind: "cards", index: 1, text: "完整模式不會存進團隊範本：這位員工存下來沒有出發模式，套用時一律是安全模式。" }] }, true, 201);
  const main = await open();
  await tickBlock(main, "cards", "shop", "service");
  await tickBlock(main, "skills", "tm-0123456789ab", "daily");
  await tickNow(main, "cards", "prof-aaaaaaaaaaaa");
  await tickNow(main, "routines", "r-aaaaaaaaaaaa");
  await click(action(by(main, "data-templates", "foot"), "save"));
  const d = dialog();
  assert(d && attr(d, "data-templates") === "save", "the dialog is open");
  assert.strictEqual(text(by(d, "data-templates", "save-summary")).split("。")[0], "這次會存：2 位員工、1 個技能、1 件例行工作");
  assert.deepStrictEqual(allBy(d, "data-tpl-save-item", "cards").map(text), ["客服", "虛構會計"]);
  assert.deepStrictEqual(allBy(d, "data-tpl-save-item", "skills").map(text), ["每日小結"]);
  assert.deepStrictEqual(allBy(d, "data-tpl-save-item", "routines").map(text), ["虛構例行"]);
  typeName(d, "  我的新店  ");
  await click(action(d, "save-go"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/templates/mine", {
    name: "我的新店",
    cards: [{ from: { template: "shop", key: "service" } }, { profile_id: "prof-aaaaaaaaaaaa" }],
    skills: [{ from: { template: "tm-0123456789ab", key: "daily" } }],
    routines: [{ routine_id: "r-aaaaaaaaaaaa" }] }]]);
  const after = dialog();
  assert(text(after).includes("已存成團隊範本「我的新店」：2 位員工、0 個技能、0 件例行工作。"));
  assert.strictEqual(text(by(after, "data-tpl-save-note", "full_mode_saved_safe")), "完整模式不會存進團隊範本：這位員工存下來沒有出發模式，套用時一律是安全模式。");
  assert(calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length >= 2, "the page was read again behind the dialog");
  await click(action(after, "save-close"));
  assert.strictEqual(dialogs().length, 0);
});

test("the fixed words of the dialog are there word for word, and say nothing is uploaded, no mode is kept, and the limits", async () => {
  setServer();
  const main = await open();
  await tickNow(main, "skills", "k-aaaaaaaaaaaa");
  await click(action(by(main, "data-templates", "now"), "save-now"));
  const d = dialog();
  const lines = by(d, "data-templates", "save-fixed").findAll((n) => n.tag === "li").map(text);
  assert.deepStrictEqual(lines, [
    "存的是現在這一刻的複本：之後你改了原本的員工、技能或例行工作，這個團隊範本不會跟著變。",
    "員工只存名字、職位、你寫在卡上的固定指示和 Claude 的模型。不存 AI 工具、技能卡、記憶、共用資料夾和聊天紀錄；完整模式的員工存下來也不帶出發模式，套用時一律是安全模式。",
    "例行工作存名稱、內容、星期和時間，還有交給誰（那位員工也一起存才有，沒有的話套用時再選）；存下來沒有開關，套用時一律是關著的。技能存名稱和內容。",
    "存之前每段字都會用和記憶、技能同一組規則檢查：有金鑰、密碼這類字不能存，像是叫員工不問你就做事的字要你多確認一次。",
    "團隊範本只存在這台電腦，不會上傳，也不能匯出。"]);
  assert(text(by(d, "data-templates", "save-summary")).includes("最多存 20 個團隊範本，一個最多 12 位員工、24 個技能、12 件例行工作。"));
  assert.deepStrictEqual(posts(), [], "opening the dialog posts nothing");
  await click(action(d, "cancel"));
  assert.strictEqual(dialogs().length, 0);
  assert.deepStrictEqual(posts(), []);
});

test("a refusal is said with the place it points at, the words are not repeated, and nothing is shown as saved", async () => {
  setServer();
  state.save = () => jsonResponse({ error: "第 1 個技能的內容有像金鑰或登入用代碼的東西，不能存進團隊範本。", code: "template_refused", kind: "skills", index: 0, field: "text", refuse: "secret_key" }, false, 400);
  const main = await open();
  await tickNow(main, "skills", "k-aaaaaaaaaaaa");
  await click(action(by(main, "data-templates", "foot"), "save"));
  const d = dialog();
  typeName(d, "x");
  await click(action(d, "save-go"));
  const t = text(dialog());
  assert(t.includes("第 1 個技能的內容有像金鑰或登入用代碼的東西，不能存進團隊範本。（技能：虛構技能）"), t);
  assert(!t.includes("已存成"));
  assert(action(dialog(), "save-go"), "the person can fix it and try again");
});

test("a second yes: the save waits for 我確定, then posts the same again with confirm_warning", async () => {
  setServer();
  let n = 0;
  state.save = (body) => {
    n += 1;
    if (!body.confirm_warning) return jsonResponse({ error: "這段看起來像在叫員工不問你就做事。", code: "confirm_warning", warn: ["looks_like_order"], warn_text: ["這段看起來像在叫員工不問你就做事。確定要存進團隊範本嗎？"], items: [{ kind: "skills", index: 0, field: "text", warn: ["looks_like_order"] }] }, false, 409);
    return jsonResponse({ ok: true, template: { id: "tm-ffffffffffff", name: body.name, builtin: false, cards: [], skills: [{ key: "a", name: "虛構技能", text: "x" }], routines: [] }, notes: [] }, true, 201);
  };
  const main = await open();
  await tickNow(main, "skills", "k-aaaaaaaaaaaa");
  await click(action(by(main, "data-templates", "foot"), "save"));
  typeName(dialog(), "要確認的");
  await click(action(dialog(), "save-go"));
  const warn = by(dialog(), "data-templates", "save-warn");
  assert(warn && text(warn).includes("確定要存進團隊範本嗎？") && text(warn).includes("技能：虛構技能"));
  assert.strictEqual(action(dialog(), "save-go").disabled, true, "waits for the yes");
  const box = by(warn, "data-tpl-save", "confirm");
  box.checked = true; box.dispatch("change"); await settle();
  assert.strictEqual(action(dialog(), "save-go").disabled, false);
  await click(action(dialog(), "save-go"));
  assert.strictEqual(n, 2);
  assert.strictEqual(posts()[0][2].confirm_warning, undefined);
  assert.strictEqual(posts()[1][2].confirm_warning, true);
  assert(text(dialog()).includes("已存成團隊範本「要確認的」"));
});

test("a full list (409) is said in the dialog", async () => {
  setServer();
  state.save = () => jsonResponse({ error: "你存的團隊範本滿了（最多 20 個），請先刪掉幾個。", code: "mine_full" }, false, 409);
  const main = await open();
  await tickNow(main, "skills", "k-aaaaaaaaaaaa");
  await click(action(by(main, "data-templates", "foot"), "save"));
  typeName(dialog(), "多的");
  await click(action(dialog(), "save-go"));
  assert(text(dialog()).includes("你存的團隊範本滿了（最多 20 個），請先刪掉幾個。"));
});

test("when the file of the saved ones can not be read, saving is off and the page says so; the built-in blocks stay", async () => {
  setServer({ mine_readable: false });
  const main = await open();
  assert(text(main).includes("你存的團隊範本的檔案有問題"));
  await tickNow(main, "cards", "prof-aaaaaaaaaaaa");
  await tickBlock(main, "cards", "shop", "service");
  assert.strictEqual(action(by(main, "data-templates", "foot"), "save").disabled, true);
  assert.strictEqual(action(by(main, "data-templates", "now"), "save-now").disabled, true);
  assert.strictEqual(action(by(main, "data-templates", "foot"), "preview").disabled, false, "the built-in ones can still be applied");
});

test("a saved block has 改名 and 刪除, a built-in one has none", async () => {
  setServer({ mine: [mineOne] });
  const main = await open();
  const own = by(main, "data-template-id", "tm-0123456789ab");
  assert(action(own, "rename") && action(own, "delete"));
  assert(!action(by(main, "data-template-id", "shop"), "rename"));
  assert(!action(by(main, "data-template-id", "shop"), "delete"));
  assert(text(main).includes("你存的團隊範本"));
  assert(text(own).includes("你存的"));
});

test("改名 posts only the new name and the page is read again", async () => {
  setServer({ mine: [mineOne] });
  const main = await open();
  await click(action(by(main, "data-template-id", "tm-0123456789ab"), "rename"));
  const d = dialog();
  const input = by(d, "data-tpl-rename", "name");
  assert.strictEqual(input.value, "我的店");
  input.value = "新名字"; input.dispatch("input");
  await click(action(d, "rename-go"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/templates/mine/tm-0123456789ab", { name: "新名字" }]]);
  assert.strictEqual(dialogs().length, 0);
  assert(calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length >= 2);
});

test("改名 that needs a second yes asks for it, and a refusal stays in the dialog", async () => {
  setServer({ mine: [mineOne] });
  state.edit = (what, body) => (body.confirm_warning ? jsonResponse({ ok: true, template: { ...mineOne, name: body.name } })
    : jsonResponse({ error: "確定要存進團隊範本嗎？", code: "confirm_warning", warn: ["looks_like_order"], warn_text: ["確定要存進團隊範本嗎？"] }, false, 409));
  const main = await open();
  await click(action(by(main, "data-template-id", "tm-0123456789ab"), "rename"));
  by(dialog(), "data-tpl-rename", "name").value = "不用問的店";
  await click(action(dialog(), "rename-go"));
  assert(text(dialog()).includes("確定要存進團隊範本嗎？"));
  assert.strictEqual(action(dialog(), "rename-go").disabled, true);
  const box = by(dialog(), "data-tpl-rename", "confirm");
  box.checked = true; box.dispatch("change"); await settle();
  await click(action(dialog(), "rename-go"));
  assert.deepStrictEqual(posts().map((c) => c[2]), [{ name: "不用問的店" }, { name: "不用問的店", confirm_warning: true }]);
  assert.strictEqual(dialogs().length, 0);
});

test("刪除 asks first, says only the template goes, posts an empty body, and then the page is read again; 取消 posts nothing", async () => {
  setServer({ mine: [mineOne] });
  const main = await open();
  const del = () => action(by(h.dom().mainEl, "data-template-id", "tm-0123456789ab"), "delete");
  await click(del());
  let d = dialog();
  assert(text(d).includes("刪除「我的店」") && text(d).includes("只刪這個團隊範本。用它建過的員工、技能、例行工作，和它是從哪裡存來的，都不會動。"));
  await click(d.find((n) => n.tag === "button" && text(n) === "取消"));
  assert.deepStrictEqual(posts(), []);
  await click(del());
  d = dialog();
  await click(d.find((n) => n.tag === "button" && text(n) === "刪除"));
  assert.deepStrictEqual(posts().map((c) => [c[1], c[2]]), [["/api/templates/mine/tm-0123456789ab/delete", {}]]);
  assert(calls.filter((c) => c[1] === "/api/templates" && c[0] === "GET").length >= 2);
});

test("a name with a tag stays a name in the dialog, and nothing is built from it", async () => {
  setServer();
  const main = await open();
  await tickNow(main, "cards", "prof-bbbbbbbbbbbb");
  await tickNow(main, "skills", "k-bbbbbbbbbbbb");
  await click(action(by(main, "data-templates", "foot"), "save"));
  const d = dialog();
  assert(text(d).includes("<b>粗體員工</b>") && text(d).includes("<script>alert(1)</script>"));
  assert.strictEqual(d.findAll((n) => ["b", "script"].includes(n.tag)).length, 0);
});

test("source: the saving code posts only to the person's own routes, never builds markup, and never says a word of the glossary's avoid list", () => {
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(BLOCK));
  const mine = BLOCK.slice(BLOCK.indexOf("// ---- the person's own team templates (P45-3)"));
  assert(mine.length > 3000, "the P45-3 part is marked");
  const urls = Array.from(BLOCK.matchAll(/api\.(?:post|get)\(\s*[`"]([^`"]+)/g)).map((m) => m[1]).filter((u) => u !== "/api/templates" && u !== "/api/templates/preview");
  assert.deepStrictEqual(urls.sort(), ["/api/templates/mine", "/api/templates/mine/${encodeURIComponent(template.id)}", "/api/templates/mine/${encodeURIComponent(template.id)}/delete"]);
  assert(!/export|匯入|上傳|下載/.test(mine.replace(/不能匯出|不會上傳/g, "")), "no way to export, import, upload or download");
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
