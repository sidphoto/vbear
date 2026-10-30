// P35-1: which skill a card of each camp can take and which the card wizard lists, as web/app.js decides it
// (skillCompatible, skillPickPlan), against the table vbear/skill_fit.py is held to as well (tests/skill_fit_cases.json).
// A change here without the same change in Python (or the other way round) fails one of the two tests.
//
// Run: node tests/frontend/skill_fit.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs"), vm = require("vm"), assert = require("assert"), path = require("path");
const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "../skill_fit_cases.json"), "utf8"));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf("const CARD_TOOL_SHORT"), source.indexOf("function cardCatalogTools(")), ctx);
const run = (s) => vm.runInContext(s, ctx);

let pass = 0, fail = 0;
function test(name, fn) {
  try { fn(); pass += 1; console.log(`ok - ${name}`); } catch (err) { fail += 1; console.log(`FAIL - ${name}\n${err.stack}`); }
}

test("the states never listed are the table's", () => {
  assert.deepStrictEqual([...run("SKILL_NEVER_LISTED")].sort(), cases.never_listed);
});

test("every camp takes exactly the skills of the table", () => {
  for (const tool of cases.tools) {
    const got = cases.skills.filter((s) => run("skillCompatible")(s, tool)).map((s) => s.skill_id).sort();
    assert.deepStrictEqual(got, cases.expect[tool].compatible, tool);
  }
});

test("every camp lists exactly the skills of the table, one of each name", () => {
  for (const tool of cases.tools) {
    // Array.from: the page's arrays come from another realm, and deepStrictEqual compares the prototype too
    const got = Array.from(run("skillPickPlan")(cases.skills, tool).listed, (e) => e.skill.skill_id).sort();
    assert.deepStrictEqual(got, cases.expect[tool].listed, tool);
  }
});

test("the table is not empty in any direction", () => {
  for (const tool of cases.tools) {
    const { compatible, listed } = cases.expect[tool];
    assert.ok(listed.length > 0 && listed.length < compatible.length && compatible.length < cases.skills.length, tool);
  }
});

console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
