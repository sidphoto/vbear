// P47-1 (ADR 0013): the table of words (WORDS), the plain words for what the server and the screen say (PLAIN_ERRORS, plainWords),
// the notice of a spending limit that stopped something (limitReachedNotice), and toast()/notice() using them.
// Runs the real code of web/app.js (the slice from el() on, in a vm) with the focus-aware synthetic DOM. NOT a browser test.
//
// Run: node tests/frontend/p47_words.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");
const { createHarness } = require("./lib/focus_harness.cjs");

const ROOT = path.join(__dirname, "..", "..");
const APP_SRC = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
const H = createHarness();
const { walk } = H;

let passed = 0;
process.on("unhandledRejection", (e) => { console.error(`FAIL (unhandled) ${e && e.message || e}`); process.exitCode = 1; });
async function test(name, fn) {
  try { await fn(); passed += 1; console.log(`ok ${name}`); }
  catch (e) { console.error(`FAIL ${name}\n${e && e.stack || e}`); process.exitCode = 1; }
}
const textOf = (n) => (n ? n.textContent : "");
const { ctx, body } = H.context({});
const evalIn = (code) => vm.runInContext(code, ctx);
const WORDS = evalIn("WORDS");
const toastText = () => textOf(walk(body).find((n) => n.getAttribute && n.getAttribute("id") === "toast"));
const attr = (n, k) => (n.getAttribute ? n.getAttribute(k) : null);
const fold = (n) => walk(n).find((x) => attr(x, "data-plain") === "tech");

// every sentence below is one the server or the screen really says (a Python test finds the server's in the Python sources)
const RUNTIME_DOWN = [
  "VBear runtime 背景程序無法連線（FileNotFoundError）",
  "VBear runtime 背景程序無法連線（ConnectionRefusedError）",
  "VBear runtime 背景程序無法使用（TimeoutError）",
  "無法連線到 VBear runtime，終端的資訊暫時看不到。",
  "無法連線到 VBear runtime，終端的資訊暫時看不到。 VBear runtime 背景程序沒有在執行",
  "VBear runtime 背景程序無法啟動或連線",
  "VBear runtime 未連線，無法確認關聯的終端",
  "VBear runtime 無法連線：[Errno 2] No such file or directory",
  "VBear runtime 未啟動或無法連線：[Errno 61] Connection refused",
];
const LIMIT = [
  "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算。",
  "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算",
  "今天剩下的額度不到 US$0.01，不送出。",
  "額度用完（亮紅燈）",
  "額度不夠，沒有送出。",
];
const ENGLISH = /[A-Za-z]{4,}/;

(async () => {
  // ---- WORDS ----------------------------------------------------------------------------------------------------
  await test("WORDS: every entry says what to use, what not to say, and where (all / title / new)", () => {
    const keys = Object.keys(WORDS);
    assert.ok(keys.length >= 40, `the whole table: ${keys.length}`);
    for (const k of keys) {
      const w = WORDS[k];
      assert.ok(typeof w.use === "string" && w.use.length > 0, `${k}: use`);
      assert.ok(Array.isArray(w.avoid) && w.avoid.every((t) => typeof t === "string" && t), `${k}: avoid`);
      assert.ok(Array.isArray(w.loose) && w.loose.every((t) => typeof t === "string" && t), `${k}: loose`);
      assert.ok(["all", "title", "new"].includes(w.scope), `${k}: scope ${w.scope}`);
      if (w.scope === "new") assert.strictEqual(w.avoid.length, 0, `${k}: a new word has nothing to avoid`);
    }
  });

  await test("WORDS: the words of the table of the plan are there, with their words to avoid", () => {
    const want = {
      home: ["首頁", "冒險者大廳"], employee: ["員工", "角色卡"], employeeList: ["我的員工", "角色卡池"], newEmployee: ["新增員工", "起手牌組"],
      startWork: ["開始工作", "出發"], preflight: ["開始前的檢查", "出發通行證"], tool: ["用哪個 AI", "陣營"], look: ["外觀", "種族"],
      safeMode: ["每件事先問我", "安全模式"], fullMode: ["完全交給他（有風險）", "完整模式"], sandbox: ["保護範圍", "沙盒"], project: ["專案", "任務卡"],
      addFolder: ["加入一個資料夾", "導入專案"], terminal: ["指令視窗", "終端機"], pluginList: ["AI 工具的外掛清單", "技能庫"], recipe: ["常用做法", "存成技能"],
      assign: ["分配工作", "派工"], routine: ["定時工作", "例行工作"], spendLimit: ["花費上限", "每天上限"], limitReached: ["今天的用量到你設的上限了", "額度已用完"],
      toolBash: ["執行指令", "Bash"], toolEdit: ["修改檔案", "Edit"], toolWrite: ["建立或覆蓋檔案", "Write"], toolRead: ["讀取檔案", "Read"],
      toolGrep: ["搜尋檔案內容", "Grep"], toolGlob: ["找檔名", "Glob"], oldText: ["原本的內容", "原本的字串"], history: ["對話紀錄", "工作階段"],
      deleteChat: ["刪除這個對話", "刪除這個聊天"], runtime: ["VBear 的背景程式", "VBear runtime"], aiTool: ["AI 工具", "Agent CLI"],
      manualReview: ["要你檢查", "待人工處理"], orphan: ["找不到原技能的翻譯", "孤兒翻譯"], console: ["VBear", "主控台"], brandSub: ["你的 AI 員工", "技能與團隊主控台"],
      advancedMode: ["進階模式"], waiting: ["等你決定"], limits: ["用量與上限"],
    };
    for (const [k, [use, avoid]] of Object.entries(want)) {
      assert.ok(WORDS[k], `${k} is in the table`);
      assert.strictEqual(WORDS[k].use, use, k);
      if (avoid) assert.ok(WORDS[k].avoid.includes(avoid), `${k} avoids ${avoid}`);
    }
    assert.strictEqual(WORDS.terminal.scope, "title", "the engineering pages change their menu name and h1 only");
    assert.strictEqual(WORDS.employee.scope, "all");
  });

  await test("WORDS: no new word is in its own avoid list, nor in the avoid list of any other word", () => {
    const avoid = [];
    for (const [k, w] of Object.entries(WORDS)) for (const t of w.avoid) avoid.push([k, t]);
    for (const [k, w] of Object.entries(WORDS)) {
      assert.ok(!w.avoid.includes(w.use), `${k}: ${w.use} is its own avoid`);
      for (const [other, t] of avoid) assert.ok(!w.use.includes(t), `${k}: the new word 「${w.use}」 holds 「${t}」, a word to avoid (${other})`);
    }
  });

  await test("wordsToAvoid(scope) lists the literal words of that scope for a sweep, and the words of the other scopes are not in it", () => {
    const all = evalIn('wordsToAvoid("all")');
    const title = evalIn('wordsToAvoid("title")');
    assert.ok(all.some((x) => x.term === "角色卡" && x.use === "員工" && x.key === "employee"));
    assert.ok(all.some((x) => x.term === "派工" && x.use === "分配工作"));
    assert.ok(title.some((x) => x.term === "終端機" && x.use === "指令視窗"));
    assert.ok(!all.some((x) => x.term === "終端機"), "an advanced page keeps its body: only the title changes");
    assert.strictEqual(evalIn('wordsToAvoid("new")').length, 0);
    assert.ok(all.every((x) => x.term && x.use && x.key));
  });

  // ---- plainWords ---------------------------------------------------------------------------------------------------
  await test("plainWords: the sentences of the runtime being down are said in plain words, whole, and the original is kept whole", () => {
    for (const raw of RUNTIME_DOWN) {
      const w = evalIn(`plainWords(${JSON.stringify(raw)})`);
      assert.strictEqual(w.known, true, raw);
      assert.strictEqual(w.detail, raw, "the original, whole");
      assert.ok(w.text.includes("VBear 的背景程式"), w.text);
      assert.ok(!/runtime|背景程序|Errno|FileNotFoundError|ConnectionRefused/.test(w.text + w.next), `the plain words hold no engineering word: ${w.text}${w.next}`);
      assert.ok(!ENGLISH.test((w.text + w.next).replace(/VBear/g, "")), w.text);
      assert.ok(w.next.length > 0, "and what to do next");
    }
  });

  await test("plainWords: the Agent CLI version check, manual_review and the orphan translation", () => {
    const v = evalIn('plainWords("Agent CLI 版本檢查回傳失敗")');
    assert.strictEqual(v.known, true);
    assert.ok(v.text.includes("AI 工具") && !/Agent CLI/.test(v.text + v.next), v.text);
    assert.strictEqual(v.detail, "Agent CLI 版本檢查回傳失敗");
    for (const raw of ["Agent CLI 版本檢查逾時", "Agent CLI 版本檢查失敗", "Agent CLI 版本檢查無法執行"]) assert.strictEqual(evalIn(`plainWords(${JSON.stringify(raw)}).known`), true, raw);
    const m = evalIn('plainWords("審查需要人工處理（manual_review）")');
    assert.strictEqual(m.known, true);
    assert.ok(m.text.includes("要你檢查") && !/manual_review|人工處理/.test(m.text), m.text);
    assert.ok(m.next.includes("先停下來等你看"));
    assert.strictEqual(m.detail, "審查需要人工處理（manual_review）");
    const rest = evalIn('plainWords("這個聊天之前的程序還沒確認結束（pid 12），需要人工處理")');
    assert.ok(rest.text.includes("pid 12") && rest.text.includes("要你檢查"), "the rest of the sentence stays: " + rest.text);
    assert.strictEqual(evalIn('plainWords("manual_review").text'), "要你檢查");
    assert.strictEqual(evalIn('plainWords("待人工處理：留下的暫存區").text'), "要你檢查：留下的暫存區");
    const o = evalIn('plainWords("孤兒翻譯：3")');
    assert.strictEqual(o.text, "找不到原技能的翻譯：3");
    assert.strictEqual(o.detail, "", "a change of word only: nothing to hide, so no 技術細節");
    assert.strictEqual(o.known, true);
  });

  await test("plainWords: the sentences of the spending limit stopping something become the one limit sentence", () => {
    for (const raw of LIMIT) {
      const w = evalIn(`plainWords(${JSON.stringify(raw)})`);
      assert.strictEqual(w.known, true, raw);
      assert.strictEqual(w.limit, true, raw);
      assert.strictEqual(w.text, evalIn("LIMIT_REACHED_TEXT"));
      assert.strictEqual(w.detail, raw);
    }
    const text = evalIn("LIMIT_REACHED_TEXT");
    for (const need of ["今天的用量到你設的上限了", "沒有送出", "沒有花錢", "明天 0 點", "調高上限"]) assert.ok(text.includes(need), need);
    assert.ok(!/額度|亮紅燈/.test(text), "and none of the old words");
  });

  await test("plainWords: a sentence it does not know comes back as it was, not known, with no guess at a cause", () => {
    for (const raw of ["weird english failure", "Traceback boom", "磁碟滿了", "VBear runtime 5/6 版本是 0.20.0", "依據：VBear runtime（終端已結束）", "ECONNRESET", "FileNotFoundError", "[Errno 2] No such file or directory"]) {
      const w = evalIn(`plainWords(${JSON.stringify(raw)})`);
      assert.deepStrictEqual({ ...w }, { text: raw, next: "", detail: "", known: false, limit: false }, raw);
    }
    assert.deepStrictEqual({ ...evalIn('plainWords("")') }, { text: "", next: "", detail: "", known: false, limit: false });
    assert.deepStrictEqual({ ...evalIn("plainWords(null)") }, { text: "", next: "", detail: "", known: false, limit: false });
    assert.deepStrictEqual({ ...evalIn("plainWords(undefined)") }, { text: "", next: "", detail: "", known: false, limit: false });
  });

  await test("plainWords: an Error or a server answer that carries the sentence is read too", () => {
    assert.strictEqual(evalIn('plainWords(new Error("VBear runtime 背景程序無法連線（FileNotFoundError）")).known'), true);
    assert.strictEqual(evalIn('plainWords({ error: "今天剩下的額度不到 US$0.01，不送出。" }).limit'), true);
    assert.strictEqual(evalIn('plainWords({ error: "x" }).known'), false);
    assert.strictEqual(evalIn("plainWords(42).known"), false);
  });

  await test("PLAIN_ERRORS: every entry has a key and a regex; no entry is only a wish (it says plain words, or swaps some, or is a limit)", () => {
    const table = evalIn("PLAIN_ERRORS");
    assert.ok(table.length >= 6);
    const keys = new Set();
    for (const e of table) {
      assert.ok(e.key && !keys.has(e.key), `a key, once: ${e.key}`);
      keys.add(e.key);
      assert.ok(e.re instanceof RegExp || (e.re && typeof e.re.test === "function"), e.key);
      assert.ok(e.limit === true || typeof e.text === "string" || Array.isArray(e.swaps), `${e.key} says something`);
      if (typeof e.text === "string") assert.ok(!/[A-Za-z]{4,}/.test(e.text.replace(/VBear/g, "")), `${e.key}: ${e.text}`);
    }
  });

  await test("the sentences it knows are real: each server sentence is found in the Python code (the server's words are not changed)", () => {
    const sources = [];
    const walkDir = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { if (e.name !== "__pycache__") walkDir(p); } else if (e.name.endsWith(".py")) sources.push(fs.readFileSync(p, "utf8")); } };
    walkDir(path.join(ROOT, "vbear"));
    const all = sources.join("\n");
    const fromServer = ["VBear runtime 背景程序無法連線（", "VBear runtime 背景程序無法使用（", "VBear runtime 背景程序無法啟動或連線", "VBear runtime 背景程序沒有在執行",
      "VBear runtime 未連線，無法確認關聯的終端", "VBear runtime 無法連線：", "VBear runtime 未啟動或無法連線：", "與 VBear runtime 的連線中斷",
      "Agent CLI 版本檢查回傳失敗", "Agent CLI 版本檢查逾時", "Agent CLI 版本檢查失敗", "Agent CLI 版本檢查無法執行",
      "manual_review", "，需要人工處理", "（需要人工處理）", "等待人工處理（manual_review）",
      "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算", "今天剩下的額度不到 US$0.01，不送出。"];
    for (const f of fromServer) assert.ok(all.includes(f), `not in the Python sources: ${f}`);
    // and each real sentence of those is caught by the table (the table is not narrower than the server)
    for (const f of ["VBear runtime 背景程序無法連線（OSError）", "VBear runtime 背景程序無法使用（OSError）", "VBear runtime 背景程序無法啟動或連線", "VBear runtime 背景程序沒有在執行",
      "VBear runtime 未連線，無法確認關聯的終端", "與 VBear runtime 的連線中斷（未收到結束訊息，Terminal 本身可能仍在執行）",
      "Agent CLI 版本檢查逾時", "Agent CLI 版本檢查無法執行", "只有沒有程序在執行、也沒有等待人工處理（manual_review）的流程才能刪除。",
      "審查需要人工處理（manual_review）", "串流 session s1 需要人工處理（manual_review）"]) assert.strictEqual(evalIn(`plainWords(${JSON.stringify(f)}).known`), true, f);
    assert.strictEqual(evalIn('plainWords("只有沒有程序在執行、也沒有等待人工處理（manual_review）的流程才能刪除。").text'), "只有沒有程序在執行、也沒有要你檢查的流程才能刪除。");
  });

  // ---- plainNotice / notice / toast -------------------------------------------------------------------------------------
  await test("plainNotice: the plain words in the box, the original only behind 「技術細節」", () => {
    for (const raw of [...RUNTIME_DOWN, "Agent CLI 版本檢查回傳失敗", "審查需要人工處理（manual_review）"]) {
      const n = evalIn(`plainNotice("warn", ${JSON.stringify(raw)})`);
      const f = fold(n);
      assert.ok(f, `a fold: ${raw}`);
      assert.strictEqual(textOf(walk(f).find((x) => x.tag === "summary")), "技術細節");
      assert.ok(textOf(f).includes(raw), "the original is in the fold");
      const outside = textOf(n).replace(textOf(f), "");
      assert.ok(!outside.includes(raw), `and not outside it: ${outside}`);
      assert.ok(!/runtime|背景程序|Errno|manual_review|Agent CLI/.test(outside), outside);
    }
    const odd = evalIn('plainNotice("bad", "Traceback boom")');
    assert.ok(!fold(odd), "no fold for a sentence that is not known");
    assert.strictEqual(textOf(odd).replace(/^[!i×]/, ""), "Traceback boom");
  });

  await test("notice(kind, text): a string is said in plain words; nodes and lists are the caller's own words and are not touched", () => {
    const known = evalIn('notice("warn", "VBear runtime 背景程序無法連線（FileNotFoundError）")');
    assert.ok(textOf(known).includes("VBear 的背景程式"));
    assert.ok(fold(known));
    assert.ok(known.className.includes("notice") && known.className.includes("warn"));
    assert.strictEqual(known.getAttribute("role"), "note");
    assert.strictEqual(evalIn('notice("bad", "VBear runtime 背景程序無法連線（x）")').getAttribute("role"), "alert", "the kind and role are kept");
    assert.strictEqual(textOf(evalIn('notice("info", "一句沒人認得的話")')).replace(/^[!i×]/, ""), "一句沒人認得的話");
    const list = evalIn('notice("warn", ["VBear runtime 背景程序無法連線（x）", " ", "第二句"])');
    assert.ok(textOf(list).includes("VBear runtime 背景程序無法連線（x）"), "a list is not translated");
    assert.ok(!fold(list));
    const limit = evalIn('notice("warn", "今天剩下的額度不到 US$0.01，不送出。")');
    assert.strictEqual(limit.getAttribute("data-limit"), "reached", "a limit sentence in a notice gets the limit notice");
  });

  await test("toast(msg): a string is said in plain words with the original in brackets; a line that carries its original already is left alone", () => {
    evalIn('toast("VBear runtime 背景程序無法連線（FileNotFoundError）")');
    let t = toastText();
    assert.ok(t.startsWith("VBear 的背景程式沒有在跑"), t);
    assert.ok(t.endsWith("（原文：VBear runtime 背景程序無法連線（FileNotFoundError））"), t);
    evalIn('toast("一句沒人認得的話")');
    assert.strictEqual(toastText(), "一句沒人認得的話");
    const already = "這個終端的連線數已滿，暫時連不上。（原文：VBear runtime 背景程序無法連線）";
    evalIn(`toast(${JSON.stringify(already)})`);
    assert.strictEqual(toastText(), already, "the terminal words (P19) are not translated twice");
    evalIn('toast("今天剩下的額度不到 US$0.01，不送出。")');
    t = toastText();
    assert.ok(t.startsWith("今天的用量到你設的上限了") && t.includes("調高上限") && t.endsWith("（原文：今天剩下的額度不到 US$0.01，不送出。）"), t);
    evalIn('toast("已清除孤兒翻譯 3 筆")');
    assert.strictEqual(toastText(), "已清除找不到原技能的翻譯 3 筆", "a change of word has no brackets");
  });

  await test("the terminal words (TERMINAL_WORDS) are still their own table: its toast and notice come out as before", () => {
    const line = evalIn('terminalFailureLine("目前沒有這個 Terminal", "x")');
    assert.ok(line.startsWith("這個終端已經不存在了") && line.endsWith("（原文：目前沒有這個 Terminal）"), line);
    const n = evalIn('terminalFailureNotice("VBear runtime 無法連線：[Errno 2] No such file or directory", "x")');
    const f = walk(n).find((x) => attr(x, "data-term") === "tech");
    assert.ok(f && textOf(f).includes("[Errno 2]"));
    assert.ok(textOf(n).includes("VBear 的背景程序現在連不上"), "the terminal's own plain words");
  });

  // ---- limitReachedNotice ---------------------------------------------------------------------------------------------
  await test("limitReachedNotice: the plain sentence, a button to the settings' limits, the original in 技術細節; data-limit=reached", () => {
    const raw = "今天的額度已用完（亮紅燈），今天不能再送訊息，本機日期隔天才會重算。";
    const n = evalIn(`limitReachedNotice(${JSON.stringify(raw)})`);
    assert.strictEqual(n.getAttribute("data-limit"), "reached");
    assert.ok(n.className.includes("notice"));
    const go = walk(n).find((x) => x.tag === "a" && attr(x, "data-limit") === "go");
    assert.ok(go, "a button to go");
    assert.strictEqual(go.getAttribute("href"), "#/settings?open=limits");
    assert.strictEqual(textOf(go), "到設定調高");
    assert.ok(go.className.includes("btn"));
    const f = fold(n);
    assert.ok(f && textOf(f).includes(raw));
    const outside = textOf(n).replace(textOf(f), "");
    assert.ok(outside.includes("今天的用量到你設的上限了") && outside.includes("明天 0 點") && !outside.includes("亮紅燈"), outside);
    assert.ok(!/US\$\d/.test(outside), "no money on the screen: the limit is in the settings");
  });

  await test("limitReachedNotice: no original, no fold; another first sentence for a place where it is not one message; the link stays", () => {
    const bare = evalIn("limitReachedNotice()");
    assert.ok(!fold(bare));
    assert.ok(walk(bare).some((x) => x.tag === "a" && x.getAttribute("href") === "#/settings?open=limits"));
    const other = evalIn('limitReachedNotice("daily_limit", { text: "今天的用量到你設的上限了，這件定時工作先不開始。明天 0 點會重新算。", kind: "info" })');
    assert.ok(textOf(other).includes("這件定時工作先不開始"));
    assert.ok(!textOf(other).includes("所以這則沒有送出"), "the message sentence is replaced");
    assert.ok(other.className.includes("info"));
    assert.ok(walk(other).some((x) => x.tag === "a" && x.getAttribute("href") === "#/settings?open=limits"), "still a way to the limit");
    assert.ok(fold(other) && textOf(fold(other)).includes("daily_limit"));
  });

  await test("a limit stopping something never raises the limit and sends nothing: the notice and the words make no request", async () => {
    evalIn('limitReachedNotice("今天剩下的額度不到 US$0.01，不送出。")');
    evalIn('plainNotice("warn", "額度用完（亮紅燈）")');
    await H.tick();
    assert.strictEqual(ctx.calls.length, 0, "no request at all");
  });

  // ---- the source ---------------------------------------------------------------------------------------------------------
  await test("source: the plain words use no innerHTML, no emoji and no outside resource", () => {
    const part = APP_SRC.slice(APP_SRC.indexOf("// ---------- plain words (v0.21"), APP_SRC.indexOf("// ---------- end of plain words"));
    assert.ok(part.length > 3000);
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(part));
    assert.ok(!/https?:\/\//.test(part));
    assert.ok(!/\p{Extended_Pictographic}/u.test(part));
  });

  await test("source: the new section is in the vocabulary region and is exported for the other tests", () => {
    const at = APP_SRC.indexOf("// ---------- plain words (v0.21");
    assert.ok(at > APP_SRC.indexOf("// ---------- vocabulary") && at < APP_SRC.indexOf("const TOOL = {"), "in the vocabulary region");
    const exported = APP_SRC.slice(APP_SRC.indexOf("module.exports = {"));
    for (const name of ["WORDS", "PLAIN_ERRORS", "plainWords", "plainNotice", "limitReachedNotice", "wordsToAvoid"]) assert.ok(exported.includes(`    ${name},`), name);
  });

  console.log(`\n${passed} passed`);
})();
