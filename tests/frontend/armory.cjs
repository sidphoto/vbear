// Phase D1 Armory UI: verifies honest state wording and Profile deep links.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert");
const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.style = {}; this.dataset = {}; }
  append(n) { this.children.push(n); } replaceChildren(...n) { this.children = n; }
  setAttribute(k, v) { this[k] = v; } addEventListener(k, f) { this.listeners[k] = f; }
}
function walk(n) { return [n, ...(n.children || []).flatMap(walk)]; }
const main = new Node("main");
const context = { Node, console, main, window: { scrollTo() {} }, document: {
  createElement: t => new Node(t), createTextNode: t => Object.assign(new Node("#text"), { textContent: String(t) }),
  getElementById: () => main,
} };
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("function el("), source.indexOf("const api =")), context);
vm.runInContext(`
seq=1; function claim(){ return main; }
function crumbs(){ return null; } function notice(){ return null; }
function badge(label){ return el('span', null, label); } function actBadge(a){ return badge(a); }
const api={get:async()=>({skills:[{skill_id:'s1',name:'Installed & equipped',invoke_name:'s1',activation:'active',states:{available:false,installed:true,equipped:[{id:'p1',name:'Disabled Profile',enabled:false}],loaded:{observed:false,evidence:[]}},sources:{available:'掃描（marketplace 副本）',installed:'掃描',equipped:'主控台 Profile（使用者意圖）',loaded:'未知（沒有執行觀察）'}}],unresolved_equipped:[{skill_id:'gone'}]})};
` + source.slice(source.indexOf("async function viewArmory("), source.indexOf("async function viewSkillDetail(")), context);
(async () => {
  await vm.runInContext("viewArmory()", context);
  const nodes = walk(main), text = nodes.map(n => n.textContent || "").join(" ");
  const links = nodes.filter(n => n.tag === "a");
  assert(text.includes("未知"), "no runtime evidence must say unknown");
  assert(links.some(a => a.href === "#/workbench?profile=p1"), "equipped Profile must deep-link to workbench");
  assert(source.includes('let activeTab = initialProfileId ? "agent" : "task"'), "profile deep link must select the Agent Builder tab");
  assert(source.includes('let rightCollapsed = initialProfileId ? false'), "profile deep link must reveal the right column");
  assert(text.includes("已停用"), "disabled Profile must remain visible");
  console.log("ok armory honest loaded state and profile deep link");
})().catch(e => { console.error(e); process.exitCode = 1; });
