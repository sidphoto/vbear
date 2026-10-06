// Phase D1 usability: Skills Library must explain scanner vocabulary without writes.
"use strict";
const fs = require("fs"), path = require("path"), assert = require("assert");
const app = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
for (const text of [
  "技能庫只盤點掃描到的檔案與載入位置；它不會安裝、啟動或修改任何 Skill。",
  "可使用不代表目前有 Agent 正在使用。",
  "這是 Skill 所屬或可載入它的工具，不是目前正在執行的 Agent。",
  "註記只存在 VBear，不會寫回原本的 Skill 檔案。",
  "已安裝但被設定關閉",
  "這是舊版快取副本",
]) assert(app.includes(text), `missing Skills Library explanation: ${text}`);
assert(app.includes("function helpTip(label, hint)"), "shared accessible help tip missing");
assert(app.includes('class: "filter-control"'), "filter help must sit outside the label");
assert(app.includes('el("label", { for: id }, label)'), "filter label must use for/id association");
assert(app.includes("activationWithHelp(s.activation)"), "skill cards must expose status explanation");
assert(css.includes(".armory-tip:focus-visible::after"), "keyboard focus tooltip missing");
console.log("ok Skills Library Chinese explanations and accessible status help");
