// P14 (v0.8.0 last small fixes): 「輪到 你」 without the stray space, template names in Chinese, a terminal that is gone said in
// plain words (the runtime's own sentence kept in a fold), and the ⓘ of a skill card kept inside the card.
// The real web/app.js on a synthetic DOM. Run: node tests/frontend/p14.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app } = h;

const APP_SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const CSS_SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
const text = (n) => (n ? n.textContent : "");
const byData = (root, k, v) => root.findAll((n) => n.getAttribute && n.getAttribute(k) === v);
const CJK_SPACE_CJK = /[一-鿿] [一-鿿]/;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

function flowView(phase, names = {}, over = {}) {
  return {
    id: "flow-000000000001", task_id: "task-1", task_title: "整理首頁文案",
    phase: { key: phase, label: phase, reason: `${phase} 的說明` },
    automation: { mode: "manual" },
    roles: { planner: { name: names.planner || "CEO", family: "anthropic", profile_id: "p-ceo" },
      executor: { name: names.executor || "工匠", family: "anthropic", profile_id: "p-maker" },
      reviewers: [{ name: names.reviewer || "審查員", family: "openai", profile_id: "p-rev" }] },
    ...over,
  };
}
const PHASES = ["planning", "awaiting_approval", "implementing", "needs_fix", "in_review", "review_stale", "awaiting_merge", "review_unverified", "awaiting_push", "done"];

// ---- 2. 「輪到 X」 ----------------------------------------------------------------------------------------------------
test("turnOf: a space only where a Latin name meets the Chinese (輪到你, 輪到工匠, 輪到 CEO)", () => {
  assert.strictEqual(app.turnOf("你"), "輪到你");
  assert.strictEqual(app.turnOf("工匠"), "輪到工匠");
  assert.strictEqual(app.turnOf("CEO"), "輪到 CEO");
  assert.strictEqual(app.turnOf("VBear（自動送審）"), "輪到 VBear（自動送審）");
  assert.strictEqual(app.turnOf("3號審查員"), "輪到 3號審查員");
  assert.strictEqual(app.turnAfter("你"), "你");
  assert.strictEqual(app.turnAfter("工匠"), "工匠");
  assert.strictEqual(app.turnAfter("CEO"), "CEO ");
  assert.strictEqual(app.turnAfter("VBear（自動送審）"), "VBear（自動送審）");
});

test("the next step line, list and note say 輪到你 with no space, for every phase and name", () => {
  const nameSets = [{}, { planner: "規劃師", executor: "Maker", reviewer: "審查員甲" }];
  for (const names of nameSets) for (const phase of PHASES) {
    const flow = flowView(phase, names);
    const lines = [app.nextStepSummary(flow), text(app.nextStepsList(flow, {}))];
    const act = app.nextStepAction(flow, {});
    if (act) lines.push(act.note);
    for (const t of lines) {
      assert(!/輪到 [一-鿿]/.test(t), `${phase}: ${t}`);
      assert(!/[一-鿿] 在終端裡/.test(t), `${phase}: ${t}`);
    }
  }
  assert.strictEqual(app.nextStepSummary(flowView("awaiting_merge")), "下一步：你自己合併（輪到你）");
  assert.strictEqual(app.nextStepSummary(flowView("awaiting_push")), "下一步：你自己上傳到遠端（輪到你）");
  assert.strictEqual(app.nextStepSummary(flowView("implementing")), "下一步：執行者實作（輪到工匠）");
  assert.strictEqual(app.nextStepSummary(flowView("implementing", { executor: "Maker" })), "下一步：執行者實作（輪到 Maker）");
  const list = text(app.nextStepsList(flowView("awaiting_approval"), {}));
  assert(list.includes("輪到你"), list);
  assert(text(app.nextStepsList(flowView("awaiting_push"), {})).includes("接下來：你自己上傳到遠端，輪到你。"));
});

test("no 「輪到 」 is composed anywhere in the page by joining a space to a name", () => {
  const bad = APP_SRC.split("\n").filter((l) => /^\s*(?!\/\/)(?!function turnOf).*輪到 \$\{/.test(l));
  assert.deepStrictEqual(bad, [], "use turnOf(): " + bad.join(" | "));
  assert(!/\$\{ns\.turn\} 在/.test(APP_SRC), "use turnAfter()");
});

// ---- 3. template names ------------------------------------------------------------------------------------------
test("templateName: every template key has a Chinese name; the stored value is not changed; an unknown key shows as stored", () => {
  const keys = ["bug_fix", "feature", "review", "test", "research", "refactor", "docs", "investigation", "custom"];
  assert.deepStrictEqual(Object.keys(app.TEMPLATE_NAMES).sort(), [...keys].sort());
  for (const k of keys) {
    const t = app.templateName(k);
    assert(/[一-鿿]/.test(t), `${k} -> ${t}`);
    assert.notStrictEqual(t, k);
  }
  assert.strictEqual(app.templateName("custom"), "自訂");
  assert.strictEqual(app.templateName("some_new_key"), "some_new_key", "not guessed");
  assert.strictEqual(app.templateName(undefined), "");
  assert.strictEqual(app.templateName("toString"), "toString", "inherited names are not template names");
});

test("the task card's badge is drawn from templateName, and keeps the key in its tooltip", () => {
  assert(APP_SRC.includes('badge(templateName(activeTask.template), "b-info"'));
  assert(!/badge\(activeTask\.template,/.test(APP_SRC));
});

// ---- 4. a terminal that is gone ----------------------------------------------------------------------------------------
const RAW_GONE = "terminal attach failed: 沒有這個 session（或正在關閉）";
test("terminalClosedView: the known attach failures are said in plain words, the original is kept", () => {
  const gone = app.terminalClosedView(RAW_GONE);
  assert.strictEqual(gone.text, "這個終端已經不存在了（可能已關閉）。");
  assert.strictEqual(gone.gone, true);
  assert.strictEqual(gone.detail, RAW_GONE);
  const full = app.terminalClosedView("terminal attach failed: 此 session 已達連線上限（4）");
  assert(full.text.includes("連線數已滿"), full.text);
  assert.strictEqual(full.gone, false);
  assert.strictEqual(full.detail, "terminal attach failed: 此 session 已達連線上限（4）");
});

test("terminalClosedView: an attach failure it does not know gets a general line and no guess; other reasons pass through", () => {
  const odd = app.terminalClosedView("terminal attach failed: mode 必須是 observe 或 control");
  assert.strictEqual(odd.text, "沒能連上這個終端。");
  assert.strictEqual(odd.gone, false);
  assert.strictEqual(odd.detail, "terminal attach failed: mode 必須是 observe 或 control");
  assert.deepStrictEqual({ ...app.terminalClosedView("終端機已結束") }, { text: "終端機已結束", gone: false, detail: "" });
  assert.deepStrictEqual({ ...app.terminalClosedView("") }, { text: "", gone: false, detail: "" });
  assert.deepStrictEqual({ ...app.terminalClosedView(undefined) }, { text: "", gone: false, detail: "" });
});

test("terminalClosedNotice: plain sentence on top, the runtime's own sentence only inside 「技術細節」", () => {
  const n = app.terminalClosedNotice(RAW_GONE, true, "需要新的終端時，請從角色卡的「出發通行證」開啟。");
  const tech = byData(n, "data-term", "tech")[0];
  assert(tech, "a fold with the details");
  assert.strictEqual(text(tech.find((x) => x.tag === "summary")), "技術細節");
  assert(text(tech).includes(RAW_GONE), "the original is in the fold");
  const outside = text(n).replace(text(tech), "");
  assert(outside.includes("終端機連線已關閉：這個終端已經不存在了（可能已關閉）。需要新的終端時，請從角色卡的「出發通行證」開啟。"), outside);
  assert(!outside.includes("attach failed"), "the English sentence is not in the main text");
  assert(!outside.includes("重新連線"), "nothing to reconnect to");
  // a reason that is not an attach failure has no fold and keeps the reconnect line when the session is not gone
  const plain = app.terminalClosedNotice("終端機已結束", false, "x");
  assert.strictEqual(byData(plain, "data-term", "tech").length, 0);
  assert.strictEqual(text(plain), "i終端機連線已關閉：終端機已結束。如需重新開啟請點選右上方「重新連線」。", "(the first character is the notice icon)");
});

test("both terminal pages mark a vanished session as gone and use the shared notice", () => {
  assert.strictEqual((APP_SRC.match(/terminalClosedNotice\(closedReason, sessionGone,/g) || []).length, 2);
  assert.strictEqual((APP_SRC.match(/if \(terminalClosedView\(msg\.reason\)\.gone\) sessionGone = true;/g) || []).length, 2);
  assert(!APP_SRC.includes('"：" + closedReason'), "the raw reason is no longer put on the screen directly");
});

// ---- 5. the ⓘ stays inside the card ------------------------------------------------------------------------------------
test("a card's status badge and ⓘ do not shrink: the title column gives way instead", () => {
  assert(/\.card-top > \.status-help \{[^}]*flex: none;/.test(CSS_SRC));
  assert(/\.card-title \{[^}]*word-break: break-word;/.test(CSS_SRC), "the title can still break anywhere");
  assert(/<div style="min-width:0">|style: "min-width:0"/.test(APP_SRC) || APP_SRC.includes('"min-width:0"'), "the title column can shrink");
});

(async () => {
  const timer = setTimeout(() => { console.error("TIMEOUT"); process.exit(2); }, 120000);
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name); console.log(e && e.stack || e); }
  }
  clearTimeout(timer);
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
