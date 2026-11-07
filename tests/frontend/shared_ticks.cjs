// P43-3: the person's two ticks for the shared folder (ADR 0009 point 2) and the file names under a group's reply. The new-group dialog has
// "讓這幾位都能用共用資料夾" (off unless ticked; a Codex member adds the line that says the files go to OpenAI and the request then carries
// confirm_company), a dispatch's proposal card has "替這次派工的員工打開共用資料夾" (off; lists who is off now and who is new; same for Codex),
// and a reply in a group shows the names of the files that appeared while the employee answered, as text, with no preview and no delete. The real
// web/app.js on a synthetic DOM and a fetch stub; it is NOT a browser test. Every name is made up and a file name could hold markup.
// Run: node tests/frontend/shared_ticks.cjs   (exit code 0 = pass)
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

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const q = (n, key, name) => n.find((x) => attr(x, `data-${key}`) === name);
const qa = (n, key, name) => n.findAll((x) => attr(x, `data-${key}`) === name);
const dialog = () => h.dom().bodyEl.find((n) => n.hasClass && n.hasClass("modal-backdrop"));
const EVIL = "<img src=x onerror=alert(1)>.md";
const SHA = "a".repeat(64);
const DID = "d-0123456789ab";
const posts = (u) => FETCH_LOG.filter((c) => c.method === "POST" && c.url.split("?")[0] === u);

const cards = () => [
  { id: "emp-1", name: "文案小編", tool: "claude", engine: "claude-chat", can_chat: true },
  { id: "emp-2", name: "會計師", tool: "claude", engine: "claude-chat", can_chat: true },
  { id: "emp-4", name: "Codex 員工", tool: "codex", engine: "codex-chat", can_chat: true },
];

// ---- the new-group dialog ---------------------------------------------------------------------------------------------

function pick(dlg, id) {
  const box = qa(dlg, "group", "pick").find((x) => attr(x, "data-profile-id") === id);
  box.checked = true; box.dispatch("change");
}
function openDialog(onCreate) {
  app.openGroupDialog(cards(), { onCreate: onCreate || (async () => ({})) });
  return dialog();
}

test("the dialog has the tick, off, with its words, and a request without it carries nothing about the folder", async () => {
  const bodies = [];
  const dlg = openDialog(async (b) => { bodies.push(b); return {}; });
  const tick = q(dlg, "group", "shared");
  assert(tick, "a tick");
  assert.notStrictEqual(tick.checked, true, "off by default");
  assert(text(dlg).includes(app.GROUP_SHARED_LABEL) && text(dlg).includes("預設不勾"));
  assert(!(q(dlg, "group", "shared-on-note")), "the long words only when ticked");
  pick(dlg, "emp-1"); pick(dlg, "emp-2");
  q(dlg, "group", "create").click();
  await settle();
  assert.deepStrictEqual(bodies, [{ profile_ids: ["emp-1", "emp-2"] }]);
});

test("ticked, the request says shared_folder and the words say every write still asks and nothing is deleted", async () => {
  const bodies = [];
  const dlg = openDialog(async (b) => { bodies.push(b); return {}; });
  pick(dlg, "emp-1"); pick(dlg, "emp-2");
  const tick = q(dlg, "group", "shared");
  tick.checked = true; tick.dispatch("change");
  const note = text(q(dlg, "group", "shared-on-note"));
  assert(note.includes("每一次寫進去都照舊先問你") && note.includes("開新的聊天員工才知道") && note.includes("不會刪任何檔案"));
  assert(!(q(dlg, "group", "shared-codex")), "no Codex member: no OpenAI line");
  q(dlg, "group", "create").click();
  await settle();
  assert.deepStrictEqual(bodies, [{ profile_ids: ["emp-1", "emp-2"], shared_folder: true }]);
});

test("a Codex member and the tick: the line says the files go to OpenAI and the request carries confirm_company; unticked, it does not", async () => {
  const bodies = [];
  const dlg = openDialog(async (b) => { bodies.push(b); return {}; });
  pick(dlg, "emp-1"); pick(dlg, "emp-4");
  assert(!(q(dlg, "group", "shared-codex")), "the line waits for the tick");
  const tick = q(dlg, "group", "shared");
  tick.checked = true; tick.dispatch("change");
  assert.strictEqual(text(q(dlg, "group", "shared-codex")), app.GROUP_SHARED_CODEX_NOTE);
  assert(text(q(dlg, "group", "shared-codex")).includes("OpenAI"));
  tick.checked = false; tick.dispatch("change");
  assert(!(q(dlg, "group", "shared-codex")));
  q(dlg, "group", "create").click();
  await settle();
  assert.deepStrictEqual(bodies, [{ profile_ids: ["emp-1", "emp-4"] }], "no tick, no confirmation either");
  const again = openDialog(async (b) => { bodies.push(b); return {}; });
  pick(again, "emp-1"); pick(again, "emp-4");
  const t2 = q(again, "group", "shared");
  t2.checked = true; t2.dispatch("change");
  q(again, "group", "create").click();
  await settle();
  assert.deepStrictEqual(bodies[1], { profile_ids: ["emp-1", "emp-4"], shared_folder: true, confirm_company: true });
});

test("the server's refusal stays in the dialog in its words", async () => {
  const dlg = openDialog(async () => { throw Object.assign(new Error("Codex 員工讀到的共用資料夾檔案會送到 OpenAI，要先確認。"), { status: 409 }); });
  pick(dlg, "emp-1"); pick(dlg, "emp-2");
  q(dlg, "group", "create").click();
  await settle();
  assert(dialog(), "still open");
  assert(text(q(dialog(), "group", "error")).includes("要先確認"));
});

// ---- the proposal card ------------------------------------------------------------------------------------------------

const dview = (over = {}) => ({ id: DID, chief_id: "cos-0123456789ab", chat_id: "c-0123456789abcdef", created_at: 1790000200, state: "proposed", started_by: null,
  started_by_text: null, summary: "我建議找文案小編和一位新的會計師。", questions: [], notes: [],
  team: [{ who: "C1", why: "會寫文案", kind: "existing", name: "文案小編" }, { who: "N1", why: "算成本", kind: "new", name: "會計師" }],
  tools: ["claude", "codex"], proposal_sha: SHA, edited: false, task_id: null, created_cards: [], steps: [],
  plan: { title: "週末市集擺攤", goal: "準備手工皂攤位", deliverables: ["攤位介紹"],
    new_cards: [{ ref: "N1", name: "會計師", position: "accountant", tool: "claude", model_alias: "haiku" }],
    steps: [{ who: "C1", text: "請寫攤位介紹", name: "文案小編" }, { who: "N1", text: "請算成本", name: "會計師" }] },
  cost: { steps: 2, per_turn_usd: "0.5", max_usd: "1", day_left_usd: "2.71" }, pause: null, events: [],
  can: { confirm: true, dismiss: true, stop: false, continue: false, delete: true, withdraw: [] },
  shared: { people: [{ who: "C1", name: "文案小編", on: false, company: "Anthropic", usable: true }] }, ...over });

async function card(v, opts = {}) {
  FETCH_LOG.length = 0;
  setHandler((url, o = {}) => {
    const p = url.split("?")[0];
    if (p === `/api/dispatch/${DID}/confirm`) return jsonResponse({ ...v, state: "running", shared: { opened: [] } });
    return null;
  });
  const node = app.proposalCard(v, opts);
  await settle();
  return node;
}
const confirmBody = () => posts(`/api/dispatch/${DID}/confirm`)[0].body;
const press = async (node) => { q(node, "dispatch", "confirm").click(); await settle(); };

test("the card offers the tick, off, and says who is off now and who is new", async () => {
  const node = await card(dview());
  const tick = q(node, "dispatch", "shared");
  assert(tick, "a tick");
  assert.notStrictEqual(tick.checked, true);
  assert(text(node).includes(app.DISPATCH_SHARED_LABEL) && text(node).includes("預設不勾"));
  const who = text(q(node, "dispatch", "shared-who"));
  assert(who.includes("文案小編") && who.includes("會計師（新建）"), who);
  assert(!(q(node, "dispatch", "shared-note")));
});

test("without the tick the confirmation is exactly what it was", async () => {
  const node = await card(dview());
  await press(node);
  assert.deepStrictEqual(Object.keys(confirmBody()).sort(), ["goal", "new_cards", "proposal_sha", "steps", "title"]);
});

test("with the tick the confirmation carries shared_folder, and the words say every write still asks and only names are handed on", async () => {
  const node = await card(dview());
  const tick = q(node, "dispatch", "shared");
  tick.checked = true; tick.dispatch("change");
  const note = text(q(node, "dispatch", "shared-note"));
  assert(note.includes("每一次寫進去都照舊先問你") && note.includes("只有檔名"), note);
  assert(!(q(node, "dispatch", "shared-codex")));
  await press(node);
  const body = confirmBody();
  assert.strictEqual(body.shared_folder, true);
  assert.strictEqual("confirm_company" in body, false);
  assert.strictEqual(body.proposal_sha, SHA);
});

test("a new Codex employee: the line about OpenAI shows with the tick and the confirmation carries confirm_company", async () => {
  const v = dview({ plan: { ...dview().plan, new_cards: [{ ref: "N1", name: "會計師", position: "accountant", tool: "codex", model_alias: "" }] } });
  const node = await card(v);
  const tick = q(node, "dispatch", "shared");
  assert(!(q(node, "dispatch", "shared-codex")), "the line waits for the tick");
  tick.checked = true; tick.dispatch("change");
  assert(text(q(node, "dispatch", "shared-codex")).includes("OpenAI"));
  await press(node);
  assert.strictEqual(confirmBody().confirm_company, true);
  assert.strictEqual(confirmBody().shared_folder, true);
});

test("an existing Codex employee that is off counts the same way", async () => {
  const v = dview({ shared: { people: [{ who: "C1", name: "Codex 員工", on: false, company: "OpenAI", usable: true }] } });
  const node = await card(v);
  const tick = q(node, "dispatch", "shared");
  tick.checked = true; tick.dispatch("change");
  assert(q(node, "dispatch", "shared-codex"));
  await press(node);
  assert.strictEqual(confirmBody().confirm_company, true);
});

test("an employee who has the folder already is not listed, and with nobody to open there is no tick at all", async () => {
  const v = dview({ plan: { ...dview().plan, new_cards: [], steps: [{ who: "C1", text: "請寫", name: "文案小編" }] },
    team: [{ who: "C1", why: "x", kind: "existing", name: "文案小編" }], shared: { people: [{ who: "C1", name: "文案小編", on: true, company: "Anthropic", usable: true }] } });
  const node = await card(v);
  assert(!(q(node, "dispatch", "shared")));
  await press(node);
  assert.strictEqual("shared_folder" in confirmBody(), false);
});

test("an employee whose AI tool cannot use the folder yet is not offered", async () => {
  const v = dview({ plan: { ...dview().plan, new_cards: [], steps: [{ who: "C1", text: "請寫", name: "x" }] },
    shared: { people: [{ who: "C1", name: "x", on: false, company: "OpenAI", usable: false }] } });
  const node = await card(v);
  assert(!(q(node, "dispatch", "shared")));
});

test("a server that sends nothing about the folder gets no tick, and the card works as before", async () => {
  const v = dview(); delete v.shared;
  const node = await card(v);
  assert(!(q(node, "dispatch", "shared")));
  await press(node);
  assert.strictEqual("shared_folder" in confirmBody(), false);
});

test("the tick follows the draft: a step handed to someone else changes who is listed, and a ticked box then unticked sends nothing", async () => {
  const v = dview({ team: [{ who: "C1", why: "a", kind: "existing", name: "文案小編" }, { who: "C2", why: "b", kind: "existing", name: "會計師" }],
    plan: { ...dview().plan, new_cards: [], steps: [{ who: "C1", text: "請寫", name: "文案小編" }] },
    shared: { people: [{ who: "C1", name: "文案小編", on: false, company: "Anthropic", usable: true }, { who: "C2", name: "會計師", on: false, company: "Anthropic", usable: true }] } });
  const node = await card(v);
  assert(text(q(node, "dispatch", "shared-who")).includes("文案小編") && !text(q(node, "dispatch", "shared-who")).includes("會計師"));
  const who = q(node, "dispatch", "step-who");
  who.value = "C2"; who.dispatch("change");
  await settle();
  assert(text(q(node, "dispatch", "shared-who")).includes("會計師") && !text(q(node, "dispatch", "shared-who")).includes("文案小編"));
  const tick = q(node, "dispatch", "shared");
  tick.checked = true; tick.dispatch("change");
  q(node, "dispatch", "shared").checked = false; q(node, "dispatch", "shared").dispatch("change");
  await press(node);
  assert.strictEqual("shared_folder" in confirmBody(), false);
});

test("a refusal of the confirmation shows in the card in the server's words", async () => {
  FETCH_LOG.length = 0;
  setHandler((url) => (url.split("?")[0] === `/api/dispatch/${DID}/confirm`
    ? jsonResponse({ code: "shared_confirm", error: "Codex 員工讀到的共用資料夾檔案會送到 OpenAI，要先確認。", warn: ["send_to_openai"] }, false, 409) : null));
  const node = app.proposalCard(dview(), { onRefresh() {} });
  q(node, "dispatch", "shared").checked = true;
  await press(node);
  assert(text(q(node, "dispatch", "error")).includes("要先確認"));
});

// ---- under a reply in a group -----------------------------------------------------------------------------------------

const reply = (changes, over = {}) => ({ seq: 3, at: 1790000300, kind: "reply", round: 1, profile_id: "emp-1", name: "文案小編", tool: "claude", text: "寫好了",
  unreadable: false, reason: "result", partial: false, cost_usd: "0.12", estimate: false, chat_id: "c-" + "a".repeat(16), turn: 1, shared_changes: changes, ...over });

test("a reply lists the file names that appeared meanwhile, as text, with no preview and no delete", async () => {
  const node = app.groupItemNode(reply({ names: ["價目表.md", EVIL, "sub/a.txt"], cut: false, unavailable: false }));
  const line = q(node, "group", "shared-changes");
  assert(line, "a line");
  assert(text(line).includes("不一定是他做的"));
  for (const name of ["價目表.md", EVIL, "sub/a.txt"]) assert(text(line).includes(name), name);
  assert.strictEqual(node.findAll((n) => n.tag === "img" || n.tag === "script").length, 0, "markup stays text");
  assert.strictEqual(node.findAll((n) => n.tag === "a").length, 0, "a name is not a link");
  const buttons = line.findAll((n) => n.tag === "button");
  assert.deepStrictEqual(buttons.map((b) => text(b)), ["在 Finder 打開"], "nothing to delete or preview");
});

test("more than ten names say how many more, and a cut list says only the first fifty are listed", async () => {
  const names = Array.from({ length: 14 }, (_, i) => `f${String(i).padStart(2, "0")}.md`);
  const line = q(app.groupItemNode(reply({ names, cut: true, unavailable: false })), "group", "shared-changes");
  assert(text(line).includes("f09.md") && !text(line).includes("f10.md"));
  assert(text(line).includes("還有 4 個") && text(line).includes("只列了前 50 個"));
});

test("a comparison that could not be made is said, and a reply with no change shows nothing", async () => {
  assert(text(q(app.groupItemNode(reply({ names: [], cut: false, unavailable: true })), "group", "shared-changes")).includes("沒有比對"));
  assert(!(q(app.groupItemNode(reply({ names: [], cut: false, unavailable: false })), "group", "shared-changes")));
  const plain = reply(undefined); delete plain.shared_changes;
  assert(!(q(app.groupItemNode(plain), "group", "shared-changes")));
});

test("the Finder button posts an empty body", async () => {
  FETCH_LOG.length = 0;
  setHandler((url) => (url.split("?")[0] === "/api/shared/reveal" ? jsonResponse({ ok: true, revealed: true }) : null));
  const line = q(app.groupItemNode(reply({ names: ["a.md"], cut: false, unavailable: false })), "group", "shared-changes");
  line.find((n) => n.tag === "button").click();
  await settle();
  assert.deepStrictEqual(posts("/api/shared/reveal").map((c) => c.body), [{}]);
});

// ---- the code ---------------------------------------------------------------------------------------------------------

test("the code of the ticks and of the names has no innerHTML, no emoji, no outside address and sends no path", async () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
  const parts = [source.slice(source.indexOf("// P43-3: under a reply"), source.indexOf("// The list's line for a group.")),
    source.slice(source.indexOf("// P43-3: the person's tick on the proposal card"), source.indexOf("function proposalDraft(v)")),
    source.slice(source.indexOf("// who the tick would open"), source.indexOf("  const derive = () => {\n    drawShared();"))];
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}]/u;
  for (const part of parts) {
    assert(part.length > 300);
    assert(!emoji.test(part));
    assert(!/\.innerHTML\s*=|insertAdjacentHTML\s*\(/.test(part));
    assert(!/https?:\/\//.test(part));
    assert(!/console\.(log|info|warn|error)/.test(part));
  }
});

(async () => {
  let failed = 0;
  await settle();
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
    for (const d of h.dom().bodyEl.findAll((n) => n.hasClass && n.hasClass("modal-backdrop"))) { try { d.remove(); } catch (_) { /* gone */ } }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
