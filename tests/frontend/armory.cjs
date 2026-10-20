// Phase D1 Armory UI: verifies honest state wording and Profile deep links.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert");
const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.style = {}; this.dataset = {}; }
  // like the real DOM: a node has one parent, so adding it here takes it away from the old one
  append(n) {
    if (n && n.parent) { const i = n.parent.children.indexOf(n); if (i >= 0) n.parent.children.splice(i, 1); }
    if (n && typeof n === "object") n.parent = this;
    this.children.push(n);
  }
  replaceChildren(...n) { this.children = n; }
  contains(node) { return this === node || this.children.some(c => c instanceof Node && c.contains(node)); }
  setAttribute(k, v) { this[k] = v; } addEventListener(k, f) { this.listeners[k] = f; }
}
function walk(n) { return [n, ...(n.children || []).flatMap(walk)]; }
const main = new Node("main");
const context = { Node, console, main, window: { scrollTo() {} }, store: { get: (_k, d) => d, set() {} }, document: {
  createElement: t => new Node(t), createTextNode: t => Object.assign(new Node("#text"), { textContent: String(t) }),
  getElementById: () => main,
} };
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("function el("), source.indexOf("const api =")), context);
vm.runInContext(`
seq=1; function claim(){ return main; }
function crumbs(){ return null; } function notice(){ return null; }
function badge(label){ return el('span', null, label); } function actBadge(a){ return badge(a); }
function campKeyOf(s){ return s && s.tool === 'claude' ? 'anthropic' : s && s.tool === 'codex' ? 'openai' : 'other'; }
function helpTip(label, hint){ return el('span', {class:'armory-tip', 'data-tip':hint, 'aria-label':label+'說明：'+hint, tabindex:'0'}, 'ⓘ'); }
const api={get:async()=>({skills:[{skill_id:'s1',name:'Installed & equipped',invoke_name:'s1',activation:'active',states:{available:false,installed:true,equipped:[{id:'p1',name:'Disabled Profile',enabled:false}],loaded:{observed:false,evidence:[]}},sources:{available:'掃描（marketplace 副本）',installed:'掃描',equipped:'主控台角色卡（使用者意圖）',loaded:'未知（沒有執行觀察）'}}],unresolved_equipped:[{skill_id:'gone'}]})};
` + source.slice(source.indexOf("// ---------- skill translations"), source.indexOf("// ---------- data")) + source.slice(source.indexOf("async function viewArmory("), source.indexOf("async function viewSkillDetail(")), context);
(async () => {
  await vm.runInContext("viewArmory()", context);
  const nodes = walk(main), text = nodes.map(n => n.textContent || "").join(" ");
  assert(text.includes("尚無證據"), "no runtime evidence must say no evidence");
  for (const label of ["市集可取得", "本機已安裝", "收藏在角色卡上", "使用證據"]) {
    assert(text.includes(label), `missing Chinese-first Armory label: ${label}`);
  }
  assert(nodes.some(n => n["data-tip"] && n["data-tip"].includes("不代表正在被任何 Agent 使用")), "focus tooltip data missing");
  assert(!nodes.some(n => n.title), "CSS tooltip must not retain a duplicate native title");
  const styles = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
  assert(styles.includes(".armory-tip:focus-visible::after"), "keyboard focus must reveal the tooltip");
  assert(styles.includes(".status-help .armory-tip::after"), "right-edge status tooltip must anchor inward");
  const links = nodes.filter(n => n.tag === "a");
  assert(links.some(a => a.href === "#/workbench?profile=p1"), "equipped Profile must deep-link to workbench");
  assert(source.includes('let activeTab = initialProfileId ? "agent" : "task"'), "profile deep link must select the Agent Builder tab");
  assert(source.includes('let rightCollapsed = (initialProfileId || initialTaskId) ? false'), "profile deep link must reveal the right column");
  assert(text.includes("已停用"), "disabled Profile must remain visible");
  assert(nodes.some(n => n.tag === "button" && walk(n).some(c => c.textContent === "技能卡特性")), "each Armory card opens the skill card");
  console.log("ok armory honest loaded state and profile deep link");
})().catch(e => { console.error(e); process.exitCode = 1; });
