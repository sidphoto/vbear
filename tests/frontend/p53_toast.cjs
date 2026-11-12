// P53 (v0.25.0, from the review of v0.23.0): the toast (#toast) is above everything that can be open when it shows: the waiting bar, the phone drawer's backdrop (50)
// and drawer (60), the dialogs' backdrop (100), the skill tip (120). Reads web/style.css as text (or the file named by P53_CSS, for the bad sample). NOT a browser test.
//
// Run: node tests/frontend/p53_toast.cjs   (exit code 0 = pass)
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

let passed = 0;
const test = (name, fn) => { fn(); passed += 1; console.log("ok - " + name); };
const CSS = fs.readFileSync(process.env.P53_CSS || path.join(__dirname, "..", "..", "web", "style.css"), "utf8");

// the value of the last z-index declared for a selector (rules for exactly that selector, outside of any @media)
const lastZ = (selector) => {
  const esc = selector.replace(/[.#[\]="$^*+?()|\\-]/g, "\\$&");
  const found = [...CSS.matchAll(new RegExp("(?:^|\\n)" + esc + "\\s*\\{([^}]*)\\}", "g"))].map((m) => (/z-index:\s*(-?\d+)/.exec(m[1]) || [])[1]).filter(Boolean);
  return found.length ? Number(found[found.length - 1]) : null;
};

test("the toast has a z-index of its own", () => {
  assert.notStrictEqual(lastZ("#toast"), null, "#toast has no z-index");
});

test("the toast is above the drawer, its backdrop, the dialogs and the skill tip", () => {
  const toast = lastZ("#toast");
  assert.ok(toast > 120, "toast " + toast);
  assert.ok(toast > lastZ(".modal-backdrop"), ".modal-backdrop");
  assert.ok(toast > lastZ(".skill-tip"), ".skill-tip");
  assert.ok(toast > lastZ(".waiting-bar"), ".waiting-bar");
  const drawer = /\.side-panel \{[^}]*z-index:\s*(\d+)/.exec(CSS);
  const backdrop = /\.nav-backdrop \{[^}]*z-index:\s*(\d+)/.exec(CSS);
  assert.ok(drawer && toast > Number(drawer[1]), "drawer");
  assert.ok(backdrop && toast > Number(backdrop[1]), "backdrop");
});

test("the toast still ignores the pointer and stays hidden until .show", () => {
  assert.ok(/#toast \{[^}]*pointer-events:\s*none/.test(CSS));
  assert.ok(/#toast \{[^}]*opacity:\s*0/.test(CSS));
  assert.ok(/#toast\.show \{[^}]*opacity:\s*1/.test(CSS));
});

console.log(`\n${passed} passed`);
