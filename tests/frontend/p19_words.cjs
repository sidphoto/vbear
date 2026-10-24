// P19 #2: what the server and the runtime say when a terminal, a takeover, a close, a handoff or a link to a task card does
// not work: said in plain words first, with the original kept (a fold 「技術細節」 in a notice; in brackets in a toast).
// Runs the real code of web/app.js (the slice from el() on, in a vm) with the focus-aware synthetic DOM. NOT a browser test.
//
// Run: node tests/frontend/p19_words.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");
const { createHarness } = require("./lib/focus_harness.cjs");

const ROOT = path.join(__dirname, "..", "..");
const APP_SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const H = createHarness();
const { json, tick, walk, button, dialogs } = H;

let passed = 0;
process.on("unhandledRejection", (e) => { console.error(`FAIL (unhandled) ${e && e.message || e}`); process.exitCode = 1; });
async function test(name, fn) {
  try { await fn(); passed += 1; console.log(`ok ${name}`); }
  catch (e) { console.error(`FAIL ${name}\n${e && e.stack || e}`); process.exitCode = 1; }
}
const textOf = (n) => (n ? n.textContent : "");
const toastText = (body) => textOf(walk(body).find((n) => n.getAttribute && n.getAttribute("id") === "toast"));
const fresh = (routes = {}) => H.context(routes);
const evalIn = (ctx, code) => vm.runInContext(code, ctx);

// every sentence below is one the server or the runtime really sends (a test further down finds each one in the Python sources)
const KNOWN = [
  // raw, what the plain words must say (a part of them), whether it is "gone"
  ["沒有這個 session（或正在關閉）", "這個終端已經不存在了（可能已關閉）。", true],
  ["目前沒有這個 Terminal", "這個終端已經不存在了（可能已關閉）。", true],
  ["此 session 已達連線上限（4）", "連線數已滿", false],
  ["同時開啟的 Terminal 過多，請先關閉其他分頁", "連線數已滿", false],
  ["目前不是這個 Terminal 的操作者", "你現在不是這個終端的操作者", false],
  ["缺少輸入內容", "沒有內容可以送出", false],
  ["單次輸入過長", "一次輸入的內容太長", false],
  ["VBear runtime 背景程序無法啟動或連線", "VBear 的背景程序現在連不上", false],
  ["VBear runtime 無法連線：[Errno 2] No such file or directory", "VBear 的背景程序現在連不上", false],
  ["VBear runtime 未啟動或無法連線：[Errno 61] Connection refused", "VBear 的背景程序現在連不上", false],
  ["無法連線到 runtime", "VBear 的背景程序現在連不上", false],
  ["背景程序正在關閉，不接受新的 session", "正在關閉", false],
  ["無效的 session id", "編號對不上", false],
  ["需要從 VBear 開啟（執行 python3 -m vbear launch 或打開 VBear App）", "沒有 VBear 的通行證", false],
  ["forbidden", "擋下了這個要求", false],
  ["invalid host", "擋下了這個要求", false],
  ["內部錯誤：TypeError", "內部錯誤", false],
  ["HTTP 502", "沒有說明的錯誤", false],
  ["Failed to fetch", "連不上 VBear", false],
  ["Load failed", "連不上 VBear", false],
  ["NetworkError when attempting to fetch resource.", "連不上 VBear", false],
  ["網路錯誤", "連不上 VBear", false],
  ["找不到此任務卡", "找不到這張任務卡", false],
  ["交接必須填寫接手的對象", "交接要寫明交給誰", false],
  ["此任務卡已結案，不能再交接；請從最新的一張接續", "已經結案，不能再交接", false],
  ["任務卡已達上限 500 筆", "任務卡的數量已經到上限", false],
  ["任務儲存鎖定逾時（可能有其他程序正在寫入），請稍後再試", "任務卡儲存區現在讀寫不了", false],
  ["無法安全讀取任務儲存檔案 /x/tasks.json：boom；為避免資料遺失，讀寫已暫停", "任務卡儲存區現在讀寫不了", false],
  ["leader 尚未結束", "主程式還沒結束", false],
  ["leader 的 process group 仍有程序", "還有程式在跑", false],
  ["仍有已觀測的後代程序存活", "還有沒結束的", false],
  ["無法取得程序表或有無法確認身分的後代", "查不到有哪些程式在跑", false],
  ["無法證明程序已全部結束", "沒辦法證明", false],
  ["leader 已被回收，不再送訊號，交人工確認程序群組", "沒辦法確認主程式那一組", false],
  ["leader 已不是未回收的子程序，不再送訊號，交人工確認", "沒辦法確認主程式那一組", false],
  ["leader 在回收前已失去，交人工確認", "沒辦法確認主程式那一組", false],
  ["launch 目錄身分與 manifest 不符", "記錄和實際內容對不上", false],
  ["暫存區位置與核准樣式不符", "記錄和實際內容對不上", false],
  ["暫存區 inode 與 manifest 不符", "記錄和實際內容對不上", false],
  ["暫存區刪除後仍存在", "沒刪乾淨", false],
  ["launch 目錄刪除後仍存在", "沒刪乾淨", false],
  ["清理檢查失敗：[Errno 13] Permission denied", "清理前的檢查沒通過", false],
  ["manifest 無法讀取：boom", "清理前的檢查沒通過", false],
  ["資料夾必須在你的家目錄內", "不在你的家目錄裡", false],
  ["找不到這個資料夾", "找不到這個資料夾", false],
  ["資料夾必須是絕對路徑，或以 ~ 開頭", "從 / 或 ~ 開頭", false],
];
// something the page has never been told about: only the general sentence, and nothing guessed from it
const UNKNOWN = ["mode 必須是 observe 或 control", "Traceback (most recent call last): boom", "ECONNRESET", "無法啟動：[Errno 2] No such file or directory",
  "找不到可執行的指令：zsh", "something nobody has seen", "HTTP 200 but weird", "disk full"];
const ENGLISH = /[A-Za-z]{3,}/;

(async () => {
  const { ctx } = fresh();
  let GENERAL = {};
  try { GENERAL = evalIn(ctx, "TERM_GENERAL"); } catch (_) { /* not defined: the tests below say so one by one */ }

  await test("every sentence the server or the runtime sends is said in plain words, and the original is kept beside it", () => {
    for (const [raw, plain, gone] of KNOWN) {
      const w = ctx.terminalWords(raw, "一般句。");
      assert.strictEqual(w.known, true, raw);
      assert.ok(w.text.includes(plain), `${raw} -> ${w.text}`);
      assert.strictEqual(w.detail, raw, `${raw}: the original is kept whole`);
      assert.strictEqual(w.gone, gone, raw);
      assert.ok(!ENGLISH.test((w.text + w.next).replace(/VBear|App|Agent/g, "")), `the plain words hold no English: ${w.text}${w.next}`);
      assert.ok(w.next === "" || /[。]$/.test(w.next), `${raw}: the next step is a sentence`);
    }
  });

  await test("the sentences it knows are real: each is found in the Python code of the server or the runtime", () => {
    const sources = [];
    const walkDir = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { if (e.name !== "__pycache__") walkDir(p); } else if (e.name.endsWith(".py")) sources.push(fs.readFileSync(p, "utf8")); } };
    walkDir(path.join(ROOT, "vbear"));
    const all = sources.join("\n");
    const fromServer = ["沒有這個 session（或正在關閉）", "目前沒有這個 Terminal", "此 session 已達連線上限", "同時開啟的 Terminal 過多，請先關閉其他分頁",
      "目前不是這個 Terminal 的操作者", "缺少輸入內容", "單次輸入過長", "VBear runtime 背景程序無法啟動或連線", "VBear runtime 無法連線：",
      "VBear runtime 未啟動或無法連線：", "無法連線到 runtime", "背景程序正在關閉，不接受新的 session", "無效的 session id", "需要從 VBear 開啟（執行 python3 -m vbear launch",
      "\"forbidden\"", "\"invalid host\"", "內部錯誤：", "找不到此任務卡", "交接必須填寫接手的對象", "此任務卡已結案，不能再交接；請從最新的一張接續",
      "任務卡已達上限", "任務儲存鎖定逾時", "無法安全讀取任務儲存檔案", "leader 尚未結束", "leader 的 process group 仍有程序", "仍有已觀測的後代程序存活",
      "無法取得程序表或有無法確認身分的後代", "無法證明程序已全部結束", "leader 已被回收，不再送訊號，交人工確認程序群組", "leader 已不是未回收的子程序，不再送訊號，交人工確認",
      "leader 在回收前已失去，交人工確認", "launch 目錄身分與 manifest 不符", "暫存區位置與核准樣式不符", "暫存區 inode 與 manifest 不符", "暫存區刪除後仍存在",
      "launch 目錄刪除後仍存在", "清理檢查失敗：", "manifest 無法讀取：", "資料夾必須在你的家目錄內", "找不到這個資料夾", "資料夾必須是絕對路徑，或以 ~ 開頭"];
    for (const s of fromServer) assert.ok(all.includes(s), `not in the Python sources: ${s}`);
  });

  await test("a sentence it does not know gets the general sentence, no guess, and the original is still kept", () => {
    for (const raw of UNKNOWN) {
      const w = ctx.terminalWords(raw, GENERAL.takeover);
      assert.strictEqual(w.known, false, raw);
      assert.strictEqual(w.text, GENERAL.takeover, raw);
      assert.strictEqual(w.next, "");
      assert.strictEqual(w.detail, raw);
      assert.strictEqual(w.gone, false);
    }
    const none = ctx.terminalWords("", GENERAL.takeover);
    assert.deepStrictEqual({ text: none.text, detail: none.detail, known: none.known }, { text: GENERAL.takeover, detail: "", known: false });
    assert.strictEqual(ctx.terminalWords(undefined, "x").text, "x");
    assert.strictEqual(ctx.terminalWords({ message: "disk full" }, "x").detail, "disk full", "an Error is read by its message");
    const net = new Error("Failed to fetch"); net.name = "TypeError";
    assert.strictEqual(ctx.terminalWords(net, "x").known, true);
  });

  await test("the general sentences name what failed and none of them guesses a cause", () => {
    const keys = Object.keys(GENERAL).sort();
    assert.deepStrictEqual(keys, ["autoTakeover", "close", "handoff", "input", "link", "open", "release", "stream", "takeover"].sort());
    for (const k of keys) {
      assert.ok(/[。）]$/.test(GENERAL[k]), `${k}: ${GENERAL[k]}`);
      assert.ok(!ENGLISH.test(GENERAL[k]), `${k}: no English`);
      assert.ok(!/因為|可能是|應該是|大概/.test(GENERAL[k]), `${k}: no cause is guessed`);
    }
    assert.strictEqual(GENERAL.takeover, "沒能接手這個終端。");
  });

  await test("a toast says the plain words first and keeps the original in brackets after them", () => {
    const known = ctx.terminalFailureLine("目前沒有這個 Terminal", GENERAL.takeover);
    assert.ok(known.startsWith("這個終端已經不存在了（可能已關閉）。要繼續的話，請重新開啟一個終端。"), known);
    assert.ok(known.endsWith("（原文：目前沒有這個 Terminal）"), known);
    const odd = ctx.terminalFailureLine("Traceback boom", GENERAL.takeover);
    assert.strictEqual(odd, "沒能接手這個終端。（原文：Traceback boom）");
    assert.strictEqual(ctx.terminalFailureLine("", GENERAL.takeover), "沒能接手這個終端。", "nothing in brackets when there is no original");
    for (const [raw] of KNOWN) {
      const main = ctx.terminalFailureLine(raw, "x").split("（原文：")[0];
      assert.ok(!ENGLISH.test(main.replace(/VBear|App|Agent/g, "")), `the main sentence holds no English: ${main}`);
    }
  });

  await test("a notice says the plain words and keeps the original only inside the fold 「技術細節」", () => {
    for (const raw of ["目前沒有這個 Terminal", "ECONNRESET", "VBear runtime 無法連線：[Errno 2] No such file or directory"]) {
      const n = ctx.terminalFailureNotice(raw, GENERAL.takeover);
      const fold = walk(n).find((x) => x.getAttribute && x.getAttribute("data-term") === "tech");
      assert.ok(fold, "a fold");
      assert.strictEqual(textOf(walk(fold).find((x) => x.tag === "summary")), "技術細節");
      assert.ok(textOf(fold).includes(raw), "the original is in the fold");
      const outside = textOf(n).replace(textOf(fold), "");
      assert.ok(!outside.includes(raw), "and not outside it");
      assert.ok(!ENGLISH.test(outside.replace(/VBear|App|Agent/g, "")), outside);
    }
    const none = ctx.terminalFailureNotice("", GENERAL.takeover);
    assert.ok(!walk(none).some((x) => x.getAttribute && x.getAttribute("data-term") === "tech"), "no fold when there is nothing to keep");
  });

  await test("the closed-terminal line of P14 says what it said before, from the same table", () => {
    const gone = ctx.terminalClosedView("terminal attach failed: 沒有這個 session（或正在關閉）");
    assert.deepStrictEqual({ ...gone }, { text: "這個終端已經不存在了（可能已關閉）。", gone: true, detail: "terminal attach failed: 沒有這個 session（或正在關閉）" });
    assert.strictEqual(ctx.terminalClosedView("terminal attach failed: mode 必須是 observe 或 control").text, "沒能連上這個終端。");
    assert.strictEqual(ctx.terminalClosedView("終端機已結束").text, "終端機已結束");
    assert.ok(!/terminalClosedView[^]{0,400}沒有這個 session/.test(APP_SRC.slice(APP_SRC.indexOf("function terminalClosedView("), APP_SRC.indexOf("function terminalClosedNotice("))),
      "terminalClosedView keeps no copy of the table");
  });

  // ---- real triggers --------------------------------------------------------------------------------------------------
  await test("closing a terminal that fails: the toast says it in plain words with the original in brackets", async () => {
    for (const [status, reply, expect] of [[400, { error: "無效的 session id" }, "這個終端的編號對不上"], [500, { error: "內部錯誤：TypeError" }, "內部錯誤"],
      [400, { error: "weird english failure" }, "沒能關閉這個終端。（原文：weird english failure）"], [503, { error: "VBear runtime 背景程序無法啟動或連線" }, "VBear 的背景程序現在連不上"]]) {
      const { ctx: c, body, main } = fresh({ "POST /api/native/sessions/n-0123456789ab/close": () => json(reply, status) });
      main.append(c.closeSessionButton("n-0123456789ab"));
      button(main, "關閉終端").click(); await tick();
      button(dialogs(body)[0], "關閉終端").click(); await tick();
      const t = toastText(body);
      assert.ok(t.includes(expect), t);
      assert.ok(t.includes(`（原文：${reply.error}）`), `the original is in the toast: ${t}`);
      assert.ok(!t.startsWith("關閉失敗："), "the old lead with the raw sentence is gone");
    }
  });

  await test("closing a managed terminal whose scratch is kept: the reason is said in plain words, the original stays", async () => {
    for (const [reason, plain] of [["仍有已觀測的後代程序存活", "它啟動的程式裡還有沒結束的"], ["leader 尚未結束", "終端裡的主程式還沒結束"], ["something unknown", "沒能確認原因"], [null, "原因未知"]]) {
      const { ctx: c, body, main } = fresh({ "POST /api/native/sessions/n-0123456789ab/close": () => json({ ok: true, closed: "n-0123456789ab", managed: { launch_id: "l-1", cleaned: false, retained_reason: reason } }) });
      main.append(c.closeSessionButton("n-0123456789ab"));
      button(main, "關閉終端").click(); await tick();
      button(dialogs(body)[0], "關閉終端").click(); await tick();
      const t = toastText(body);
      assert.ok(t.startsWith("終端已關閉；暫存區保留待檢查。"), t);
      assert.ok(t.includes(plain), t);
      if (reason) assert.ok(t.endsWith(`（原文：${reason}）`), t);
      else assert.ok(!t.includes("原文"), t);
    }
  });

  await test("a terminal opened for a task card but not recorded on it: plain words, the original kept, the terminal still usable", async () => {
    for (const [reply, status, plain] of [[{ error: "找不到此任務卡" }, 404, "找不到這張任務卡"], [{ error: "disk exploded" }, 500, null]]) {
      const { ctx: c } = fresh({ "POST /api/tasks/task-1": () => json(reply, status) });
      const r = await c.linkLaunchedTerminal({ id: "task-1", title: "整理文案" }, "n-0123456789ab");
      assert.strictEqual(r.linked, false);
      assert.ok(r.message.startsWith("終端已開啟，但沒能記到任務卡上。"), r.message);
      if (plain) assert.ok(r.message.includes(plain), r.message);
      assert.ok(r.message.includes(`（原文：${reply.error}）`), r.message);
      assert.ok(r.message.includes("終端可以照常使用"), r.message);
      assert.ok(!/上：/.test(r.message), "the raw sentence is not joined on with a colon");
    }
  });

  await test("opening a terminal that fails: plain words in the toast, the original in brackets", async () => {
    const { ctx: c, body } = fresh({ "POST /api/native/terminals": () => json({ error: "VBear runtime 無法連線：[Errno 2] No such file or directory" }, 503) });
    const form = c.newTerminalForm();
    form.dispatch("submit", {});
    await tick();
    const t = toastText(body);
    assert.ok(t.startsWith("VBear 的背景程序現在連不上"), t);
    assert.ok(t.endsWith("（原文：VBear runtime 無法連線：[Errno 2] No such file or directory）"), t);
  });

  await test("the takeover reminder shows what went wrong inside the dialog, with the fold, and clears it on the next try", async () => {
    const { ctx: c, body, main } = fresh();
    let attempts = 0;
    main.append(c.el("button", { type: "button" }, "opener"));
    const r = c.openTakeoverReminder({ titleId: "t", paneId: "n-0123456789ab", session: null, pane: null, readData: async () => ({ tasks: [], flows: [] }),
      onConfirm: async ({ confirmBtn, showProblem }) => {
        attempts += 1;
        if (attempts === 1) { showProblem(c.terminalFailureNotice("目前沒有這個 Terminal", evalIn(c, "TERM_GENERAL").takeover)); confirmBtn.disabled = false; }
      } });
    await tick();
    const modal = dialogs(body)[0];
    r.confirmBtn.click(); await tick();
    const shown = walk(modal).find((n) => n.getAttribute && n.getAttribute("data-takeover") === "problem");
    assert.ok(shown && textOf(shown).includes("這個終端已經不存在了（可能已關閉）。"), "the problem is in the dialog");
    assert.ok(textOf(shown).includes("目前沒有這個 Terminal") && walk(shown).some((n) => n.tag === "details"), "with the original in the fold");
    r.confirmBtn.click(); await tick();
    assert.strictEqual(textOf(walk(modal).find((n) => n.getAttribute && n.getAttribute("data-takeover") === "problem")), "", "cleared when asked again");
  });

  // ---- every place goes through the one table --------------------------------------------------------------------------
  await test("no call site puts a raw message in front of the person any more", () => {
    const forbidden = [
      /toast\("接手失敗：" \+/, /toast\("無法取得輸入控制：" \+/, /toast\("釋放控制失敗，維持操作模式：" \+/, /toast\("鍵盤輸入傳送失敗[^"]*" \+/,
      /toast\("關閉失敗：" \+/, /toast\("交接失敗：" \+/, /toast\("關聯更新失敗：" \+/, /toast\("無法開啟終端機：" \+/,
      /沒能記到任務卡上：\$\{/, /暫存區保留待檢查：\$\{m\.retained_reason/, /連線失敗 \(HTTP/, /權限不足 \(403\)/, /\(429\)/,
    ];
    for (const re of forbidden) assert.ok(!re.test(APP_SRC), `still there: ${re}`);
    const count = (re) => (APP_SRC.match(re) || []).length;
    const uses = (key) => count(new RegExp(`terminalFailure(?:Line|Notice)\\([^\\n]*TERM_GENERAL\\.${key}\\b`, "g"));
    assert.strictEqual(uses("takeover"), 2, "the takeover dialog of both terminal pages");
    assert.strictEqual(uses("autoTakeover"), 2, "the automatic takeover of both");
    assert.strictEqual(uses("release"), 2, "改成只觀看 of both");
    assert.strictEqual(uses("input"), 2, "typing of both");
    assert.strictEqual(uses("stream"), 2, "the stream notice of both");
    assert.strictEqual(uses("close"), 1, "closing a terminal");
    assert.strictEqual(uses("handoff"), 1, "the handoff");
    assert.strictEqual(uses("link"), 1, "the 關聯目前的終端 button");
    assert.strictEqual(uses("open"), 1, "opening a terminal");
    assert.strictEqual(count(/terminalWords\(/g) >= 4, true, "and the helpers themselves, the closed line and the retained reason read the table");
    assert.strictEqual(count(/showProblem\(terminalFailureNotice\(/g), 2, "the dialog of both terminal pages");
    assert.strictEqual(count(/\berrorMsg = termInit\.error;/g), 2, "errorMsg keeps only the page's own text (the terminal module did not start)");
    assert.strictEqual(count(/\berrorMsg = /g), 4, "and nothing else is put in it: two declarations, two of those");
  });

  console.log(`\n${passed} passed`);
  if (process.exitCode) process.exit(process.exitCode);
  console.log("ALL P19 WORDS FRONTEND TESTS PASSED");
})();
