// P19 #1: where the keyboard focus is when a dialog has loaded or redrawn itself.
// Runs the real openSkillCard() / openCardWizard() / openPlaceDialog() from web/app.js against a synthetic DOM that
// moves the focus the way a browser does (lib/focus_harness.cjs). It is NOT a browser test; the headless Chrome run is
// in the P19 report.
//
// Run: node tests/frontend/p19.cjs   (exit code 0 = pass)
"use strict";
const assert = require("assert");
const { createHarness } = require("./lib/focus_harness.cjs");

const H = createHarness();
const { doc, json, slow, tick, walk, button, dialogs, press } = H;

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log(`ok ${name}`); }
  catch (e) { console.error(`FAIL ${name}\n${e && e.stack || e}`); process.exitCode = 1; }
}

const miss = () => ({ value: null, origin: "missing", detail: "" });
const skillBody = (id, name) => ({ ok: true, index: { loaded: true, generated_at: 1 },
  skill: { skill_id: id, name: { value: name, origin: "author", detail: "x" }, tool: miss(), scope: miss(), activation: "active",
    installed: true, activation_reason: "r", status_source: { origin: "derived", detail: "d" },
    description: miss(), when_to_use: miss(), inputs: miss(), outputs: miss(), dependencies: miss(),
    categories: { value: null, origin: "missing", detail: "", matches: [] },
    referenced_files: { count: 0, items: [], truncated: false, note: "n", origin: "derived", detail: "x" },
    missing_files: { items: [], origin: "derived", detail: "d" }, warnings: { items: [], origin: "derived", detail: "d" } },
  added_to_roles: { items: [], effective: false, note: "n", origin: "user", detail: "d" },
  observation: { state: "unavailable", window_days: null, source: "s", origin: "runtime", detail: "d" },
  marketplace_copies: [], marketplace_source: { origin: "derived", detail: "d" }, effect_note: "e" });
const translations = () => json({ entries: {}, counts: { fresh: 0, stale: 0, none: 0, orphan: 0 }, job: null, engine: "claude" });

// An "opener": a button on the page that has the focus, and opens the skill card when it is pressed.
function withOpener(ctx, body, main, skillId, opts) {
  const opener = ctx.el("button", { type: "button", class: "btn small" }, "技能卡特性");
  main.append(opener);
  let opened = null;
  opener.addEventListener("click", () => { opened = ctx.openSkillCard(skillId, opts); });
  opener.focus();
  opener.click();
  return { opener, opened: () => opened };
}
const inside = (root, node) => Boolean(node) && root.contains(node);

(async () => {
  // ---------------------------------------------------------------- 1. the skill card
  await test("skill card: after it has loaded, the focus is on a button in the window", async () => {
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": () => json(skillBody("s-1", "alpha")) });
    withOpener(ctx, body, main, "s-1");
    await tick();
    const modal = dialogs(body)[0];
    assert.ok(modal, "the window is open");
    assert.ok(walk(modal).some((n) => (n.textContent || "").includes("alpha")), "the skill has loaded");
    assert.strictEqual(doc.activeElement.tag, "button", "the focus is on a button");
    assert.ok(inside(modal, doc.activeElement), "the button is in the window, not on the page body");
  });

  await test("skill card: when the load fails, the focus is also on a button in the window", async () => {
    const { ctx, body, main } = H.context({ "GET /api/translations": translations,
      "GET /api/skills/s-1?view=card": () => json({ error: "索引未載入，無法顯示技能卡", code: "index_not_loaded" }, 409) });
    withOpener(ctx, body, main, "s-1");
    await tick();
    const modal = dialogs(body)[0];
    assert.ok(walk(modal).some((n) => (n.textContent || "").includes("無法顯示技能卡")), "the failure is said");
    assert.strictEqual(doc.activeElement.tag, "button");
    assert.ok(inside(modal, doc.activeElement));
  });

  await test("skill card: Esc closes it after the load, and the focus goes back to the button that opened it", async () => {
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": () => json(skillBody("s-1", "alpha")) });
    const { opener } = withOpener(ctx, body, main, "s-1");
    await tick();
    assert.strictEqual(dialogs(body).length, 1);
    press("Escape");
    assert.strictEqual(dialogs(body).length, 0, "Esc closed the window");
    assert.strictEqual(doc.activeElement, opener, "the focus is back on the opener");
  });

  await test("skill card: Esc also closes it when the load failed", async () => {
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": () => json({ error: "x" }, 500) });
    const { opener } = withOpener(ctx, body, main, "s-1");
    await tick();
    press("Escape");
    assert.strictEqual(dialogs(body).length, 0);
    assert.strictEqual(doc.activeElement, opener);
  });

  await test("skill card: a person who moved the focus inside the window while it loaded keeps it there", async () => {
    const slowCard = slow(skillBody("s-1", "alpha"));
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": slowCard });
    withOpener(ctx, body, main, "s-1");
    await tick();
    const modal = dialogs(body)[0];
    const heading = walk(modal).find((n) => n.tag === "h2");
    heading.setAttribute("tabindex", "-1");
    heading.focus();   // the person moved on, to somewhere else in the window
    slowCard.release();
    await tick();
    assert.ok(walk(modal).some((n) => (n.textContent || "").includes("alpha")), "the skill has loaded");
    assert.strictEqual(doc.activeElement, heading, "the load did not take the focus away from where the person put it");
  });

  await test("skill card: closed before a slow load ends, the window is not touched and the focus does not move", async () => {
    const slowCard = slow(skillBody("s-1", "alpha"));
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": slowCard });
    const { opener } = withOpener(ctx, body, main, "s-1");
    await tick();
    const modal = dialogs(body)[0];
    const loadingText = modal.textContent;
    press("Escape");
    assert.strictEqual(doc.activeElement, opener, "closed: the focus is on the opener");
    const elsewhere = ctx.el("button", { type: "button" }, "別處");
    main.append(elsewhere);
    elsewhere.focus();   // the person went on with the page
    slowCard.release();
    await tick();
    assert.strictEqual(dialogs(body).length, 0, "no window came back");
    assert.strictEqual(doc.activeElement, elsewhere, "the late answer did not move the focus");
    assert.strictEqual(modal.textContent, loadingText, "the closed window was not drawn into");
  });

  await test("skill card: closed before a slow load fails, the failure is not drawn into the closed window either", async () => {
    const slowFail = slow({ error: "索引未載入" }, 409);
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": slowFail });
    const { opener } = withOpener(ctx, body, main, "s-1");
    await tick();
    const modal = dialogs(body)[0];
    const loadingText = modal.textContent;
    press("Escape");
    slowFail.release();
    await tick();
    assert.strictEqual(doc.activeElement, opener);
    assert.strictEqual(modal.textContent, loadingText);
  });

  await test("skill card: when the opener is gone from the page, closing puts the focus on the main region of the page", async () => {
    const { ctx, body, main } = H.context({ "GET /api/translations": translations, "GET /api/skills/s-1?view=card": () => json(skillBody("s-1", "alpha")) });
    const { opener } = withOpener(ctx, body, main, "s-1");
    await tick();
    opener.remove();   // the page behind the window was redrawn and the button went with it
    press("Escape");
    assert.strictEqual(dialogs(body).length, 0);
    assert.strictEqual(doc.activeElement, main, "not <body>: Tab would start from the top of the page");
  });

  await test("skill card: taking a skill off a role redraws the card behind it; the focus then goes to the main region, not <body>", async () => {
    const posts = [];
    const { ctx, body, main } = H.context({ "GET /api/translations": translations,
      "GET /api/skills/s-1?view=card": () => json(skillBody("s-1", "alpha")),
      "POST /api/agent-profiles/p-1": (_u, o) => { posts.push(JSON.parse(o.body)); return json({ ok: true }); } });
    const profile = { id: "p-1", name: "Mine", equipped_skill_ids: ["s-1"] };
    let opener;
    const redraw = async () => {   // what a role card does after the change: its rows are drawn again
      opener.remove();
      opener = ctx.el("button", { type: "button" }, "技能卡特性");
      main.append(opener);
    };
    ({ opener } = withOpener(ctx, body, main, "s-1", { profile, onChanged: redraw }));
    await tick();
    const modal = dialogs(body)[0];
    button(modal, "從這個角色移除").click();
    await tick();
    const confirmBox = dialogs(body)[1];
    assert.ok(confirmBox, "the confirmation is asked in the page");
    button(confirmBox, "移除").click();
    await tick(10);
    assert.deepStrictEqual(posts, [{ equipped_skill_ids: [] }]);
    assert.strictEqual(dialogs(body).length, 0, "both windows are closed");
    assert.strictEqual(doc.activeElement, main, "the old opener is gone with the redraw; the focus is on the main region");
  });

  // ---------------------------------------------------------------- 2. the same fault in other dialogs
  const mkCard = (id, name, tool, extra = {}) => ({ id, name, profession_role_id: null, model: { tool, model_id: "" }, equipped_skill_ids: [],
    permission_intents: { read: "allow", write: "deny", test: "deny", deploy: "deny" }, enabled: true, created_at: 1, updated_at: 1,
    revision: "1".repeat(64), _unresolved: { profession: false, skills: [] }, ...extra });

  await test("card wizard, skills step: taking a skill off the card with its 移除 button leaves the focus in the window", async () => {
    const { ctx, body } = H.context({ "GET /api/translations": translations });
    const catalog = { ok: true, tools: ["claude", "codex", "shared"], permission_keys: ["read", "write", "test", "deploy"],
      permission_values: ["allow", "deny", "unspecified"], model_id_max_length: 200, professions: [],
      skills: [1, 2, 3].map((i) => ({ skill_id: `s-${i}`, name: `skill-${i}`, tool: "shared", scope: "user", activation: "active", excerpt: "x" })),
      verified_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } };
    const existing = mkCard("p-1", "Mine", "claude", { equipped_skill_ids: ["s-1", "s-2", "s-3"] });
    ctx.openCardWizard({ catalog, profiles: [existing], existing, start: 3 });
    await tick();
    const modal = dialogs(body)[0];
    const chips = () => walk(modal).filter((n) => n.tag === "button" && (n.getAttribute("aria-label") || "").startsWith("移除 "));
    assert.strictEqual(chips().length, 3);
    chips()[1].focus();            // the keyboard is on the second chip's 移除
    chips()[1].click();
    assert.strictEqual(chips().length, 2);
    assert.ok(inside(modal, doc.activeElement), "the focus did not fall to <body>");
    assert.strictEqual(doc.activeElement, chips()[1], "it is on the chip that took the place of the one removed");
    chips()[1].click();            // the last chip of the row goes: the focus goes to the one before it
    assert.strictEqual(doc.activeElement, chips()[0]);
    chips()[0].click();            // none is left: the search box
    assert.strictEqual(chips().length, 0);
    assert.strictEqual(doc.activeElement.getAttribute("id"), "cw-skill-q");
    press("Escape");
    assert.strictEqual(dialogs(body).length, 0, "and Esc still closes the window");
  });

  await test("card wizard, skills step: choosing a skill with the mouse or keyboard does not move the focus", async () => {
    const { ctx, body } = H.context({ "GET /api/translations": translations });
    const catalog = { ok: true, tools: ["claude", "codex", "shared"], permission_keys: ["read", "write", "test", "deploy"],
      permission_values: ["allow", "deny", "unspecified"], model_id_max_length: 200, professions: [],
      skills: [{ skill_id: "s-1", name: "skill-1", tool: "shared", scope: "user", activation: "active", excerpt: "x" }],
      verified_intents: { read: "allow", write: "allow", test: "allow", deploy: "deny" } };
    const existing = mkCard("p-1", "Mine", "claude");
    ctx.openCardWizard({ catalog, profiles: [existing], existing, start: 3 });
    await tick();
    const modal = dialogs(body)[0];
    const pick = walk(modal).find((n) => n.tag === "button" && n.getAttribute("data-skill") === "s-1");
    pick.focus();
    pick.click();
    assert.strictEqual(doc.activeElement, pick, "the button that was pressed keeps the focus");
  });

  const PLACE_TASKS = [{ id: "task-1", title: "整理文案", status: "in_progress", workdir: "/tmp/demo-folder", created_at: 1 },
    { id: "task-2", title: "寫測試", status: "in_progress", workdir: "/tmp/demo-two", created_at: 2 }];
  const placeRoutes = { "GET /api/tasks": () => json({ ok: true, tasks: PLACE_TASKS }), "GET /api/flows": () => json({ ok: true, flows: [] }) };

  await test("place dialog: choosing a task card, then a place, with the keyboard keeps the focus on the row that was pressed", async () => {
    const { ctx, body } = H.context(placeRoutes);
    ctx.openPlaceDialog(mkCard("p-ceo", "CEO", "claude"), { profiles: [mkCard("p-ceo", "CEO", "claude")] });
    await tick();
    const modal = dialogs(body)[0];
    const rowOf = (attr, v) => walk(modal).find((n) => n.tag === "button" && n.getAttribute(attr) === v);
    rowOf("data-place-task", "task-2").focus();
    rowOf("data-place-task", "task-2").click();
    assert.strictEqual(rowOf("data-place-task", "task-2").getAttribute("aria-pressed"), "true", "the task card is chosen");
    assert.strictEqual(doc.activeElement, rowOf("data-place-task", "task-2"), "the focus is on the redrawn row of that task card");
    rowOf("data-place-slot", "executor").focus();
    rowOf("data-place-slot", "executor").click();
    assert.strictEqual(rowOf("data-place-slot", "executor").getAttribute("aria-pressed"), "true");
    assert.strictEqual(doc.activeElement, rowOf("data-place-slot", "executor"));
    press("Escape");
    assert.strictEqual(dialogs(body).length, 0);
  });

  await test("place dialog: the list arriving from the server does not take the focus from where the person put it", async () => {
    const tasks = slow({ ok: true, tasks: PLACE_TASKS });
    const { ctx, body } = H.context({ ...placeRoutes, "GET /api/tasks": tasks });
    ctx.openPlaceDialog(mkCard("p-ceo", "CEO", "claude"), { profiles: [mkCard("p-ceo", "CEO", "claude")] });
    await tick();
    const modal = dialogs(body)[0];
    const cancel = walk(modal).find((n) => n.tag === "button" && n.textContent === "取消");
    cancel.focus();
    tasks.release();
    await tick();
    assert.ok(walk(modal).some((n) => n.getAttribute && n.getAttribute("data-place-task") === "task-1"), "the list has arrived");
    assert.strictEqual(doc.activeElement, walk(modal).find((n) => n.tag === "button" && n.textContent === "取消"),
      "the footer was drawn again; the focus is on its 取消 button as before, not on <body>");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL P19 FRONTEND TESTS PASSED");
})();
