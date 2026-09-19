// Runs the real viewRole() and DOM/debounce helpers from web/app.js against a
// minimal synthetic DOM and a controllable clock. It checks behaviour (paging,
// focus, debounce, Enter, IME), not source text. It is NOT a browser test:
// real keyboard focus, CSS, screen readers and actual IME input are untested.
// Run: node tests/frontend/role_skills.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
let active = null, now = 0, next = 1;
const timers = new Map();

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.style = {}; this.dataset = {}; this.value = ""; this.hidden = false; }
  append(n) { this.children.push(n); }
  replaceChildren() { this.children = []; }
  setAttribute(k, v) { this[k] = v; }
  addEventListener(k, f) { this.listeners[k] = f; }
  matches(s) { return this.tag === s; }
  querySelector(s) { return walk(this).find((n) => n.tag === s) || null; }
  focus() { active = this; }
}
function walk(n) { return n.children.flatMap((c) => [c, ...walk(c)]); }

const main = new Node("main");
const context = {
  Node, console,
  document: {
    createElement: (t) => new Node(t),
    createTextNode: (t) => Object.assign(new Node("#text"), { textContent: t }),
    getElementById: () => main,
  },
  setTimeout(f, ms) { const id = next++; timers.set(id, { at: now + ms, f }); return id; },
  clearTimeout: (id) => timers.delete(id),
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("function el("), source.indexOf("const api =")), context);
vm.runInContext(`
const D={roles:[{role_id:'r',name:'Test',kind:'subagent',tool:'claude',skill_link_basis:'declared',skills:[]}],live:{sessions:[]},byId:new Map()};
for(let i=0;i<250;i++){const s={skill_id:String(i),name:'skill-'+i};D.roles[0].skills.push(s);D.byId.set(s.skill_id,s);}
const loadStatic=async()=>{},loadLive=async()=>{},BASIS={};
const crumbs=()=>null,notice=()=>null,prov=()=>null,toolTag=()=>null,sectionHead=()=>null,initialOf=()=>'',home=x=>x;
let searches=0;
function searchSkills(q,pool){searches++;return pool.filter(s=>s.name.includes(q)).map(s=>({s,why:''}));}
function skillCard(s){const a=el('a',{href:'#'+s.skill_id});a.skillId=s.skill_id;return a;}
function emptyState(){return el('p',null,'empty');}
` + source.slice(source.indexOf("async function viewRole("), source.indexOf("async function viewProjects(")), context);

const evaluate = (s) => vm.runInContext(s, context);
function tick(ms) { now += ms; for (const [id, t] of [...timers]) if (t.at <= now) { timers.delete(id); t.f(); } }
function links() { return walk(main).filter((n) => n.tag === "a"); }

(async () => {
  await evaluate("viewRole('r')");
  const q = walk(main).find((n) => n.tag === "input");
  const more = walk(main).find((n) => n.tag === "button");

  assert.equal(links().length, 120, "first batch");
  assert.equal(more.hidden, false);
  more.listeners.click();
  assert.equal(links().length, 240, "second batch");
  assert.equal(active.skillId, "120", "focus moves to the first new item");
  more.listeners.click();
  assert.equal(links().length, 250, "all items");
  assert.equal(active.skillId, "240");
  assert.equal(more.hidden, true, "more button hidden when everything is shown");
  console.log("ok paging 120 -> 240 -> 250, focus, more hidden");

  q.value = "skill-249"; q.listeners.input(); tick(100); q.listeners.input(); tick(199);
  assert.equal(links().length, 250, "no search before 200ms of quiet");
  tick(1);
  assert.equal(links().length, 1, "search reaches an item beyond the first batch");
  console.log("ok debounce restarts on each input");

  q.value = "skill-"; q.listeners.input();
  let before = evaluate("searches");
  q.listeners.keydown({ key: "Enter", isComposing: false });
  assert.equal(links().length, 120, "Enter searches at once");
  tick(300);
  assert.equal(evaluate("searches"), before + 1, "Enter cancels the pending debounced search");
  console.log("ok Enter searches immediately without a duplicate");

  q.value = "skill-24"; q.listeners.input();
  before = evaluate("searches");
  q.listeners.keydown({ key: "Enter", isComposing: true });
  assert.equal(evaluate("searches"), before, "Enter while an IME is composing does not search");
  tick(200);
  assert.equal(evaluate("searches"), before + 1, "the debounced search still runs after composing");
  console.log("ok IME composition Enter ignored");

  q.value = "no-match"; q.listeners.input(); tick(200);
  assert.equal(links().length, 0);
  assert(!walk(main).includes(more), "no more button on an empty result");
  q.value = "skill-"; q.listeners.input(); tick(200);
  assert.equal(links().length, 120, "clearing back restores the first batch");
  console.log("ok empty result then recovery");
})().catch((e) => { console.error(e); process.exitCode = 1; });
