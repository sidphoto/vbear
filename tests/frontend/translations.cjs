// Real translation components in a synthetic DOM. Browser layout is left to AGY.
"use strict";
const fs = require("fs"), vm = require("vm"), assert = require("assert"), path = require("path");
const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
let active = null;
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.attrs = {}; this.hidden = false; this.value=""; this.checked=false; this.selected=false; }
  append(child) { if (child.parent) child.parent.children = child.parent.children.filter(x => x !== child); this.children.push(child); child.parent = this; if(this.tag === "select" && child.selected) this.value=child.value; }
  replaceChildren() { for (const c of this.children) c.parent = null; this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = v; if(k === "value") this.value=v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(k, fn) { this.listeners[k] = fn; }
  contains(node) { return this === node || this.children.some(c => c.contains(node)); }
  querySelectorAll(selector) { return walk(this).filter(n => n.tag === selector); }
  querySelector(selector) { return walk(this).find(n => n.tag === selector) || null; }
  focus() { active = this; }
  get textContent() { return this.tag === "#text" ? this.text : this.children.map(c => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(); this.text = String(v); }
}
function walk(n) { return [n, ...n.children.flatMap(walk)]; }
const body = new Node("body");
const document = { body, createElement: t => new Node(t), createTextNode: t => Object.assign(new Node("#text"), {text:String(t)}),
  getElementById: id => walk(body).find(n => n.id === id), get activeElement() { return active; } };
const calls = [], confirmations = [], answers = [];
let postResult = () => ({});
let view = { entries: {}, counts: {fresh:0, stale:0, none:1, orphan:1}, job:null, engine:"claude", provider:"fake" };
const ctx = { Node, document, console, setTimeout, clearTimeout,
  api: {get:async url => {calls.push(["GET",url]);return structuredClone(view);},
    post:async (url,b) => {calls.push(["POST",url,b]); return postResult(url);}, del:async url => {calls.push(["DELETE",url]);return {};}},
  badge: label => { const n = new Node("span"); n.append(document.createTextNode(label));return n; },
  fmtTime: x => `time:${x}`, notice: (kind,text) => {const n=new Node("p");n.append(document.createTextNode(text));return n;},
  toast: text => calls.push(["toast", text]),
  confirmInPage: async (title,text,label,opts) => {confirmations.push([title,text,label,opts]);return answers.shift() ?? true;},
  store: { _v: {}, get(k, d) { return Object.prototype.hasOwnProperty.call(this._v, k) ? this._v[k] : d; }, set(k, v) { this._v[k] = v; } },
  viewSettings: () => calls.push(["settings"]),
};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf("function el("), source.indexOf("const api =")), ctx);
vm.runInContext(source.slice(source.indexOf("// ---------- skill translations"), source.indexOf("// ---------- data")), ctx);
vm.runInContext(`const D={skills:[],categories:[]};` + source.slice(source.indexOf("function norm("), source.indexOf("// ---------- components")), ctx);
const run = s => vm.runInContext(s, ctx);
const findButton = (node, text) => walk(node).find(n => n.tag === "button" && n.textContent.includes(text));
const translated = {description_zh:"<img src=x onerror=alert(1)>中文審查",summary:{what:"安全審查",when:"原文未提供",needs:"原文未提供"},engine:"claude",model:"haiku",created_at:1};

(async () => {
  await run("refreshTranslations()");
  let original = new Node("div"); original.append(document.createTextNode("English author fields"));
  ctx.original = original;
  let panel = run("translationPanel('s', original)"); body.append(panel);
  assert(panel.textContent.includes("翻成中文"));
  assert(!original.parent.hidden, "none shows original");
  await findButton(panel,"翻成中文").listeners.click();
  await new Promise(r=>setImmediate(r));
  assert(calls.some(c=>c[0]==="POST" && c[1]==="/api/skills/s/translate"));
  // the short sentence on top, the whole print behind 「詳細」
  assert.equal(confirmations.at(-1)[1],"會用你自己的 Claude 帳號翻譯這張技能卡，通常不到 1 美分。");
  assert(confirmations.at(-1)[3].details.includes("帳號的額度"));
  assert(confirmations.at(-1)[3].details.includes("不是保證帳單上限"));
  assert(confirmations.at(-1)[3].details.includes("每項最多 60 秒"));

  view.entries.s = {state:"fresh",entry:translated}; view.counts={fresh:1,stale:0,none:0,orphan:1};
  await run("refreshTranslations()");
  assert(panel.textContent.includes("中文重點"));
  assert(panel.textContent.includes("作者未提供此資訊"));
  assert(panel.textContent.includes("<img src=x onerror=alert(1)>"));
  assert(!walk(panel).some(n=>n.tag==="img"),"hostile output stays text");
  assert(original.parent.hidden,"all explanation fields hidden under Chinese view");
  assert(!findButton(panel,"看新的作者原文"),"the old label is gone");
  const toggle=findButton(panel,"看英文原文"); await toggle.listeners.click();
  assert(!original.parent.hidden); assert.equal(findButton(panel,"返回中文整理").getAttribute("aria-expanded"),"true");
  await findButton(panel,"返回中文整理").listeners.click();
  assert(original.parent.hidden);

  view.entries.s.state="stale";view.counts={fresh:0,stale:1,none:7,orphan:1};
  await run("refreshTranslations()");
  assert(panel.textContent.includes("原文已變更，舊翻譯可能過期"));
  assert(panel.textContent.includes("上次翻譯：time:1"));
  assert(panel.textContent.includes("機器翻譯 · 過期"));
  const toolbar=run("translationToolbar()");body.append(toolbar);
  assert(toolbar.textContent.includes("已翻 0 · 過期 1 · 未翻 7"));
  assert(findButton(toolbar,"翻譯全部未翻的（7）"));
  toolbar.querySelector("details").open=true;
  await run("refreshTranslations()");
  assert(toolbar.querySelector("details").open,"poll preserves expanded batch actions");
  await findButton(toolbar,"翻譯全部未翻的（7）").listeners.click();
  assert.equal(confirmations.at(-1)[1],"會用你自己的 Claude 帳號翻譯這 7 張技能卡，每張通常不到 1 美分。");
  assert(confirmations.at(-1)[3].details.includes("US$0.35"));
  assert(calls.some(c=>c[1]==="/api/translations/batch" && c[2].which==="none"));
  run("D.skills=[{skill_id:'s',name:'review',activation:'active'}]");
  const hits=run("searchSkills('安全審查', D.skills)");
  assert.equal(hits.length,1);assert(hits[0].why.includes("過期機器翻譯"));

  findButton(panel,"重新翻譯").focus();
  view.job={id:"job",status:"running",automatic:true,done:1,total:3,failed:0};
  await run("refreshTranslations()");
  const translating=findButton(panel,"翻譯中…");
  assert.equal(translating.getAttribute("aria-disabled"),"true");
  assert.equal(translating.getAttribute("aria-busy"),"true");
  assert(!translating.disabled,"busy is focusable");
  assert.equal(active,translating,"busy update retains focus on the translation action");
  assert(document.getElementById("translation-activity").textContent.includes("自動重翻 翻譯中 · 1/3"));
  body.replaceChildren(); // route change; status is recovered from server, not page-local state
  await run("refreshTranslations()");
  await findButton(body,"停止翻譯").listeners.click();
  assert(calls.some(c=>c[1]==="/api/translations/batch/cancel"));

  view.provider="version_required"; view.job=null;
  await run("refreshTranslations()");
  const pendingPanel=run("translationPanel('s', original)"); body.append(pendingPanel);
  assert(pendingPanel.textContent.includes("這個 Claude Code 版本的翻譯安全邊界還沒驗證"));
  assert(findButton(pendingPanel,"驗證"));
  assert(!pendingPanel.textContent.includes("無工具"));
  const beforeVerify = calls.filter(c=>c[1]==="/api/translations/verify").length;
  answers.push(false); await run("verifyTranslationBoundary()");
  assert.equal(calls.filter(c=>c[1]==="/api/translations/verify").length,beforeVerify);
  answers.push(true); await run("verifyTranslationBoundary()");
  assert(calls.some(c=>c[0]==="POST" && c[1]==="/api/translations/verify"));
  assert(confirmations.at(-1)[3].details.includes("極少量額度"));
  assert(confirmations.at(-1)[3].details.includes("不是保證帳單上限"));
  const saves=[];
  ctx.save=async b=>{saves.push(b);return {config:{translation_engine:"claude",translation_auto:b.translation_auto||false}};};
  const settings=run("translationSettings({translation_engine:'claude',translation_auto:false},save)");body.append(settings);
  assert(findButton(settings,"驗證"));
  assert(settings.textContent.includes("極少量額度"));
  const codexSettings=run("translationSettings({translation_engine:'codex',translation_auto:false},save)");
  assert(!findButton(codexSettings,"驗證"));
  const beforeEngineChange=calls.filter(c=>c[0]==="settings").length;
  settings.querySelector("select").value="codex";
  await settings.querySelector("select").listeners.change();
  assert.equal(calls.filter(c=>c[0]==="settings").length,beforeEngineChange+1,"engine change redraws verification availability");
  settings.querySelector("select").value="claude"; saves.length=0;
  const auto=walk(settings).find(n=>n.tag==="input");auto.checked=true;answers.push(false);
  await auto.listeners.change(); assert.equal(auto.checked,false); assert.equal(saves.length,0);
  auto.checked=true; answers.push(true);await auto.listeners.change();
  assert.equal(saves[0].translation_consent_engine,"claude");
  assert(confirmations.at(-1)[1].includes("每次重新掃描最多會自動翻譯 20 張技能卡"));
  assert(confirmations.at(-1)[1].includes("每張通常不到 1 美分"));
  assert(confirmations.at(-1)[3].details.includes("每次重新掃描最多自動翻譯 20"));
  const clean=findButton(settings,"清除孤兒翻譯");
  answers.push(true,false);await clean.listeners.click();assert(!calls.some(c=>c[0]==="DELETE"));
  answers.push(true,true);await clean.listeners.click();assert(calls.some(c=>c[0]==="DELETE"));
  assert(run("translationDisclosure(2,'codex')").includes("費用上限未知"));
  assert(!/\.innerHTML\s*=/.test(source));

  // ---- P5: the short sentence, the bar that folds away, the failure on the card ------------------------------------
  const summaryRows = [
    [[1, "claude", false], "會用你自己的 Claude 帳號翻譯這張技能卡，通常不到 1 美分。"],
    [[3, "claude", false], "會用你自己的 Claude 帳號翻譯這 3 張技能卡，每張通常不到 1 美分。"],
    [[1, "codex", false], "會用你自己的 Codex 帳號翻譯這張技能卡，費用上限未知。"],
    [[5, "codex", false], "會用你自己的 Codex 帳號翻譯這 5 張技能卡，費用上限未知。"],
    [[20, "claude", true], "開啟後，每次重新掃描最多會自動翻譯 20 張技能卡，用你自己的 Claude 帳號，每張通常不到 1 美分；可以隨時在設定關閉。"],
    [[20, "codex", true], "開啟後，每次重新掃描最多會自動翻譯 20 張技能卡，用你自己的 Codex 帳號，費用上限未知；可以隨時在設定關閉。"],
  ];
  for (const [args, want] of summaryRows) {
    ctx.__a = args;
    assert.equal(run("translationSummary(...__a)"), want);
    assert(!/安全|保證/.test(want));
  }
  // the details keep every figure the old sentence had
  const full = run("translationDisclosure(2)");
  for (const part of ["US$0.10", "不是保證帳單上限", "Token 消耗未知", "每項最多 60 秒", "原文與翻譯都不是指令"]) assert(full.includes(part), part);

  const barRows = [
    [{ job: null, error: null }, "hidden"],
    [{ job: { id: "a", status: "running" }, error: null, seen: "a", seenAt: 0, now: 999999 }, "bar"],
    [{ job: { id: "a", status: "cancelling" }, error: null, now: 999999 }, "bar"],
    [{ job: { id: "a", status: "completed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 4999 }, "bar"],
    [{ job: { id: "a", status: "completed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 5000 }, "hidden"],
    [{ job: { id: "a", status: "cancelled" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 5000 }, "hidden"],
    [{ job: { id: "a", status: "failed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 9999 }, "bar"],
    [{ job: { id: "a", status: "failed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 10000 }, "dot"],
    [{ job: { id: "a", status: "failed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 60000, opened: "a" }, "bar"],
    [{ job: { id: "a", status: "failed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 60000, closed: "a" }, "hidden"],
    [{ job: { id: "a", status: "completed" }, error: null, closed: "a", now: 1 }, "hidden"],
    [{ job: { id: "b", status: "failed" }, error: null, seen: "a", seenAt: 1000, now: 1000 + 60000, closed: "a" }, "bar"],
    [{ job: { id: "a", status: "completed" }, error: "boom", now: 1 }, "bar"],
    [{ job: null, error: "boom", now: 1 }, "bar"],
    [{ job: null, error: "boom", closed: "boom", now: 1 }, "hidden"],
  ];
  for (const [input, want] of barRows) {
    ctx.__in = input;
    assert.equal(run("translationBarState(__in)").view, want, JSON.stringify(input));
  }

  // the bar, with a clock the test holds
  let clock = 1000000;
  const timers = [];
  ctx.Date = { now: () => clock };
  ctx.setTimeout = (fn, ms) => { timers.push([fn, ms]); return timers.length; };
  const bar = () => document.getElementById("translation-activity");
  const attr = (n, k) => n.getAttribute(k);
  const press = async (root, text) => { const b = findButton(root, text); assert(b, text); await b.listeners.click(); await new Promise((r) => setImmediate(r)); };
  view.job = { id: "j-ok", status: "completed", automatic: false, done: 2, total: 2, failed: 0, error: null };
  await run("refreshTranslations()");
  assert.equal(attr(bar(), "data-bar"), "bar-done");
  assert(!bar().hidden && bar().textContent.includes("技能翻譯 已結束 · 2/2 · 失敗 0"));
  assert(findButton(bar(), "關閉"), "a close button on success");
  assert(timers.some(([, ms]) => ms >= 5000 && ms < 6000), "it comes back to fold after 5 seconds");
  clock += 5100; run("renderTranslationActivity()");
  assert(bar().hidden, "success folds away after 5 seconds");
  assert.equal(attr(bar(), "data-bar"), "hidden");

  view.job = { id: "j-bad", status: "failed", automatic: false, done: 1, total: 1, failed: 1, error: { code: "cli_failed", message: "CLI 執行失敗，請自行檢查登入與額度" } };
  await run("refreshTranslations()");
  assert.equal(attr(bar(), "data-bar"), "bar-failed");
  assert(bar().textContent.includes("技能翻譯 失敗 · 1/1 · 失敗 1") && bar().textContent.includes("CLI 執行失敗，請自行檢查登入與額度"), "the reason is on the bar");
  assert(findButton(bar(), "關閉"));
  assert(timers.some(([, ms]) => ms >= 10000 && ms < 11000), "it comes back to fold after 10 seconds");
  clock += 9000; run("renderTranslationActivity()");
  assert.equal(attr(bar(), "data-bar"), "bar-failed", "still a bar before 10 seconds");
  clock += 1200; run("renderTranslationActivity()");
  assert.equal(attr(bar(), "data-bar"), "dot-failed", "a small dot after 10 seconds");
  const dot = walk(bar()).find((n) => n.tag === "button");
  assert.equal(bar().className, "translation-activity translation-dot");
  assert.equal(attr(dot, "aria-label"), "翻譯有失敗，點開看原因");
  assert(!bar().textContent.includes("CLI 執行失敗"), "the reason is not shown while it is a dot");
  await dot.listeners.click();
  assert.equal(attr(bar(), "data-bar"), "bar-failed", "the dot opens the reason again");
  assert(bar().textContent.includes("CLI 執行失敗，請自行檢查登入與額度"));
  clock += 60000; await run("refreshTranslations()");
  assert.equal(attr(bar(), "data-bar"), "bar-failed", "an opened reason stays until it is closed");
  await press(bar(), "關閉");
  assert(bar().hidden, "closed");
  assert.equal(run("store.get('translationClosed', null)"), "j-bad", "the closed job is remembered");
  await run("refreshTranslations()");
  assert(bar().hidden, "and it does not come back on the next poll");
  view.job = { id: "j-bad-2", status: "failed", automatic: false, done: 1, total: 1, failed: 1, error: { code: "cli_failed", message: "又失敗了" } };
  await run("refreshTranslations()");
  assert(!bar().hidden && bar().textContent.includes("又失敗了"), "a new job shows again");

  view.job = { id: "j-run", status: "running", automatic: false, done: 0, total: 3, failed: 0, error: null };
  await run("refreshTranslations()");
  assert.equal(attr(bar(), "data-bar"), "bar-running");
  clock += 600000; run("renderTranslationActivity()");
  assert.equal(attr(bar(), "data-bar"), "bar-running", "a running job never folds");
  assert(findButton(bar(), "停止翻譯") && findButton(bar(), "關閉"));

  // a failure is said on the card the job was started from, and only there
  view.job = null; view.entries = {}; view.counts = { fresh: 0, stale: 0, none: 2, orphan: 0 };
  await run("refreshTranslations()");
  const panelS = run("translationPanel('s', original)"); body.append(panelS);
  const panelOther = run("translationPanel('other', original)"); body.append(panelOther);
  postResult = (url) => (url === "/api/skills/s/translate" ? { job: { id: "j-card" } } : {});
  answers.push(true);
  await findButton(panelS, "翻成中文").listeners.click();
  await new Promise((r) => setImmediate(r));
  view.job = { id: "j-card", status: "failed", automatic: false, done: 1, total: 1, failed: 1, error: { code: "cli_failed", message: "CLI 執行失敗，請自行檢查登入與額度" } };
  await run("refreshTranslations()");
  const failure = (panel) => walk(panel).find((n) => n.getAttribute && n.getAttribute("data-translation") === "failure");
  assert(failure(panelS), "the card says it failed");
  assert(failure(panelS).textContent.includes("暫時無法翻譯，原文已保留"));
  assert(failure(panelS).textContent.includes("重試") && failure(panelS).textContent.includes("原因"));
  assert(failure(panelS).textContent.includes("CLI 執行失敗，請自行檢查登入與額度"), "the reason is inside the card's 原因 fold");
  assert(walk(failure(panelS)).some((n) => n.tag === "details"), "the reason is a fold");
  assert(!failure(panelOther), "another card says nothing: the job does not name its skill");
  assert(panelS.textContent.includes("English author fields") || !original.parent.hidden, "the original is kept in view");
  const postsBefore = calls.filter((c) => c[1] === "/api/skills/s/translate").length;
  answers.push(true);
  await findButton(failure(panelS), "重試").listeners.click();
  await new Promise((r) => setImmediate(r));
  assert.equal(calls.filter((c) => c[1] === "/api/skills/s/translate").length, postsBefore + 1, "重試 asks to translate this card again");
  assert.equal(confirmations.at(-1)[1], "會用你自己的 Claude 帳號翻譯這張技能卡，通常不到 1 美分。");
  // while a job runs, or after another job replaced it, the failure line is gone
  view.job = { id: "j-next", status: "running", automatic: false, done: 0, total: 1, failed: 0, error: null };
  await run("refreshTranslations()");
  assert(!failure(panelS), "a running job replaces the failure");
  view.job = { id: "j-other", status: "failed", automatic: false, done: 1, total: 1, failed: 1, error: { code: "cli_failed", message: "x" } };
  await run("refreshTranslations()");
  assert(!failure(panelS), "a failed job this card did not start is not its failure");

  console.log("ok translations: states, text safety, original toggle, search, counts, costs, consent, progress, cancellation, two-step cleanup");
})().catch(e=>{console.error(e);process.exitCode=1;});
