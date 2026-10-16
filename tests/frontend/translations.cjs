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
let view = { entries: {}, counts: {fresh:0, stale:0, none:1, orphan:1}, job:null, engine:"claude", provider:"fake" };
const ctx = { Node, document, console, setTimeout, clearTimeout,
  api: {get:async url => {calls.push(["GET",url]);return structuredClone(view);},
    post:async (url,b) => {calls.push(["POST",url,b]); return {};}, del:async url => {calls.push(["DELETE",url]);return {};}},
  badge: label => { const n = new Node("span"); n.append(document.createTextNode(label));return n; },
  fmtTime: x => `time:${x}`, notice: (kind,text) => {const n=new Node("p");n.append(document.createTextNode(text));return n;},
  toast: text => calls.push(["toast", text]),
  confirmInPage: async (title,text) => {confirmations.push([title,text]);return answers.shift() ?? true;},
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
  assert(confirmations.at(-1)[1].includes("帳號的額度"));
  assert(confirmations.at(-1)[1].includes("不是保證帳單上限"));

  view.entries.s = {state:"fresh",entry:translated}; view.counts={fresh:1,stale:0,none:0,orphan:1};
  await run("refreshTranslations()");
  assert(panel.textContent.includes("中文重點"));
  assert(panel.textContent.includes("作者未提供此資訊"));
  assert(panel.textContent.includes("<img src=x onerror=alert(1)>"));
  assert(!walk(panel).some(n=>n.tag==="img"),"hostile output stays text");
  assert(original.parent.hidden,"all explanation fields hidden under Chinese view");
  const toggle=findButton(panel,"看新的作者原文"); await toggle.listeners.click();
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
  assert(confirmations.at(-1)[1].includes("US$0.35"));
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

  const saves=[];
  ctx.save=async b=>{saves.push(b);return {config:{translation_engine:"claude",translation_auto:b.translation_auto||false}};};
  const settings=run("translationSettings({translation_engine:'claude',translation_auto:false},save)");body.append(settings);
  const auto=walk(settings).find(n=>n.tag==="input");auto.checked=true;answers.push(false);
  await auto.listeners.change(); assert.equal(auto.checked,false); assert.equal(saves.length,0);
  auto.checked=true; answers.push(true);await auto.listeners.change();
  assert.equal(saves[0].translation_consent_engine,"claude");
  assert(confirmations.at(-1)[1].includes("每次重新掃描最多自動翻譯 20"));
  const clean=findButton(settings,"清除孤兒翻譯");
  answers.push(true,false);await clean.listeners.click();assert(!calls.some(c=>c[0]==="DELETE"));
  answers.push(true,true);await clean.listeners.click();assert(calls.some(c=>c[0]==="DELETE"));
  assert(run("translationDisclosure(2,'codex')").includes("費用上限未知"));
  assert(!/\.innerHTML\s*=/.test(source));
  console.log("ok translations: states, text safety, original toggle, search, counts, costs, consent, progress, cancellation, two-step cleanup");
})().catch(e=>{console.error(e);process.exitCode=1;});
