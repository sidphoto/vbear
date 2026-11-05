// The start-up page (開始設定): the four tools side by side (MCODE only when it is switched on), what each row says and which
// buttons it has, what the buttons send (a tool and an action, never a command), the way out, the home page's gate (first time,
// upgrade, nothing forced when the server does not say) and the terminal's plain words. The real web/app.js on a synthetic DOM,
// fetch answered by the test.
// Run: node tests/frontend/setup.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, jsonResponse, setHandler } = h;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }
const text = (n) => (n ? n.textContent : "");
const attr = (n, k) => n.getAttribute && n.getAttribute(k);
const byAttr = (root, k, v) => root.findAll((n) => attr(n, k) === v);
global.document.querySelector = () => null;
const realGetById = global.document.getElementById.bind(global.document);
global.document.getElementById = (id) => (id === "scan-status" ? null : realGetById(id));
global.document.hidden = false;

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");
const BLOCK = SRC.slice(SRC.indexOf("// ---------- the start-up page"), SRC.indexOf("// ---------- chat with role cards"));

function row(id, over = {}) {
  const names = { claude: "Claude Code", codex: "Codex CLI", agy: "Antigravity（AGY）", grok: "Grok", mcode: "MCODE" };
  const byStatus = id === "claude" || id === "codex";
  return { id, name: names[id], short: names[id], blurb: `${names[id]} 是誰家的、要什麼方案。`, hidden: id === "mcode",
    installed: false, version: null, install_problem: "not_found", login_by: byStatus ? "status" : "mark", login: byStatus ? "unknown" : "not_marked",
    can_mark: !byStatus, marked_at: null, state: "not_installed", ready: false,
    login_regions: id === "mcode" ? [{ id: "global", label: "國際區" }, { id: "cn", label: "中國區" }] : [], ...over };
}
const installed = (id, over = {}) => row(id, { installed: true, version: "1.2.3", install_problem: "", state: "not_logged_in",
  login: id === "claude" || id === "codex" ? "not_logged_in" : "not_marked", ...over });
const ready = (id) => installed(id, { state: "ready", ready: true, login: id === "claude" || id === "codex" ? "logged_in" : "marked", marked_at: 1.5 });

let page;
let calls;
function setPage(over = {}) {
  page = { tools: ["claude", "codex", "agy", "grok"].map((i) => row(i)), setup_done: false, ...over };
  calls = [];
  setHandler((url, opts = {}) => {
    const p = url.split("?")[0];
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push([method, p, body]);
    if (p === "/api/overview") return jsonResponse({ ok: true, totals: { active: 0 }, generated_at: Date.now() / 1000, stale: false, skills_with_problems: [] });
    if (p === "/api/skills") return jsonResponse({ skills: [], categories: [] });
    if (p === "/api/roles") return jsonResponse({ roles: [] });
    if (p === "/api/live") return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], panes: [], usage: { sessions: [] } });
    if (p === "/api/flows") return jsonResponse({ ok: true, flows: [] });
    if (p === "/api/setup/tools" && method === "GET") return jsonResponse({ ok: true, any_ready: page.tools.some((t) => t.ready), ...page });
    if (p === "/api/setup/terminals") return jsonResponse({ ok: true, session: { session_id: "n-0123456789ab" }, command: "x" });
    if (p.startsWith("/api/setup/tools/") && p.endsWith("/marker")) {
      const id = p.split("/")[4];
      page.tools = page.tools.map((t) => (t.id === id ? (body.done ? ready(id) : installed(id)) : t));
      return jsonResponse({ ok: true });
    }
    if (p === "/api/setup/daily-limit") return jsonResponse({ ok: true, daily_usd: 3, choices: [1, 3, 10] });
    if (p === "/api/setup/settle") return page.settle ? jsonResponse(page.settle) : jsonResponse({ ok: true, setup_done: false, setup_notice: false, upgraded: false });
    if (p === "/api/config" && method === "POST") return jsonResponse({ ok: true, config: body });
    if (p === "/api/config") return jsonResponse({ ok: true, config: page.config || {} });
    if (p === "/api/tasks") return jsonResponse({ ok: true, tasks: [] });
    if (p === "/api/agent-profiles") return jsonResponse({ ok: true, profiles: [] });
    if (p === "/api/agent-builder/catalog") return jsonResponse({ ok: true });
    return null;
  });
}
let tick = null;
async function open(hash) {
  const realSetInterval = global.setInterval;
  tick = null;
  global.setInterval = (fn) => { tick = fn; return 0; };
  global.location.hash = hash;
  try { await app.route(); await settle(); } finally { global.setInterval = realSetInterval; }
  return h.dom().mainEl;
}
const cards = (main) => main.findAll((n) => attr(n, "data-tool"));
const acts = (card) => card.findAll((n) => attr(n, "data-setup-act")).map((n) => [attr(n, "data-setup-act"), text(n)]);
const click = async (node) => { node.dispatch("click"); await settle(); };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("setupToolView: not installed, not logged in and ready say it in plain words with the next button", () => {
  let v = app.setupToolView(row("claude"));
  assert.deepStrictEqual([v.label, v.cls], ["還沒安裝", "b-warn"]);
  assert.deepStrictEqual(v.buttons.map((b) => [b.kind, b.label]), [["install", "安裝"]]);
  v = app.setupToolView(installed("claude"));
  assert.strictEqual(v.label, "還沒登入");
  assert.deepStrictEqual(v.buttons.map((b) => b.kind), ["login"], "Claude Code checks itself: no 「我登入好了」");
  assert(/自己更新/.test(v.note));
  v = app.setupToolView(installed("agy"));
  assert.deepStrictEqual(v.buttons.map((b) => [b.kind, b.label]), [["login", "登入"], ["mark", "我登入好了"]]);
  assert(/我登入好了/.test(v.note));
  v = app.setupToolView(ready("claude"));
  assert.deepStrictEqual([v.label, v.cls, v.buttons.length], ["就緒", "b-ok", 0]);
  v = app.setupToolView(ready("grok"));
  assert.deepStrictEqual(v.buttons.map((b) => b.kind), ["unmark"]);
  assert(/沒辦法自己確認/.test(v.note), "a self-reported state is not shown as verified");
  v = app.setupToolView(installed("codex", { login: "unknown" }));
  assert(/查不出/.test(v.note) && /重新檢查/.test(v.note));
  v = app.setupToolView(row("grok", { install_problem: "version_unreadable" }));
  assert(/讀不出它的版本/.test(v.note));
  assert.strictEqual(app.setupToolView(null).label, "未知");
});

test("MCODE's login is two buttons, one per region", () => {
  const v = app.setupToolView(installed("mcode"));
  assert.deepStrictEqual(v.buttons.map((b) => [b.key, b.label, b.region || ""]),
    [["login-global", "登入（國際區）", "global"], ["login-cn", "登入（中國區）", "cn"], ["mark", "我登入好了", ""]]);
});

test("the page lists the four tools side by side, with a sentence, a state, a version and the places for later tasks", async () => {
  setPage({ tools: [installed("claude", { version: "2.1.318" }), ready("codex"), row("agy"), installed("grok")] });
  const main = await open("#/setup");
  assert.strictEqual(text(main.find((n) => n.tag === "h1")), "開始設定");
  const cs = cards(main);
  assert.deepStrictEqual(cs.map((c) => attr(c, "data-tool")), ["claude", "codex", "agy", "grok"]);
  assert.deepStrictEqual(cs.map((c) => attr(c, "data-state")), ["not_logged_in", "ready", "not_installed", "not_logged_in"]);
  assert(text(cs[0]).includes("還沒登入") && text(cs[0]).includes("版本 2.1.318"));
  assert(text(cs[1]).includes("就緒"));
  assert(text(cs[2]).includes("還沒安裝"));
  assert(text(cs[0]).includes("Claude Code 是誰家的、要什麼方案。"), "one plain sentence from the server");
  assert.deepStrictEqual(acts(cs[0]), [["login", "登入"]]);
  assert.deepStrictEqual(acts(cs[1]), []);
  assert.deepStrictEqual(acts(cs[2]), [["install", "安裝"]]);
  assert.deepStrictEqual(acts(cs[3]), [["login", "登入"], ["mark", "我登入好了"]]);
  assert.strictEqual(byAttr(main, "data-setup-slot", "try").length, 4, "a place for 「試一下」 in every card");
  assert.strictEqual(byAttr(main, "data-setup-slot", "daily-limit").length, 1);
  const slots = byAttr(main, "data-setup-slot", "try");
  assert(text(slots[0]).includes("試一下"), "an installed tool has 「試一下」 in its place (task 4)");
  assert(!text(slots[2]), "a tool that is not installed has nothing in its place");
});

test("MCODE is not on the page unless the server lists it, and when it does it is a fifth row with its two login buttons", async () => {
  setPage();
  let main = await open("#/setup");
  assert(!cards(main).some((c) => attr(c, "data-tool") === "mcode"));
  setPage({ tools: ["claude", "codex", "agy", "grok"].map((i) => row(i)).concat([installed("mcode")]) });
  main = await open("#/setup");
  const cs = cards(main);
  assert.deepStrictEqual(cs.map((c) => attr(c, "data-tool")), ["claude", "codex", "agy", "grok", "mcode"]);
  assert.deepStrictEqual(acts(cs[4]), [["login-global", "登入（國際區）"], ["login-cn", "登入（中國區）"], ["mark", "我登入好了"]]);
});

test("a button sends only the tool and the action (and the region), then the person is taken to the terminal", async () => {
  setPage({ tools: [row("claude"), installed("codex"), row("agy"), row("grok"), installed("mcode")] });
  let main = await open("#/setup");
  let cs = cards(main);
  await click(byAttr(cs[0], "data-setup-act", "install")[0]);
  assert.deepStrictEqual(calls.filter((c) => c[1] === "/api/setup/terminals").map((c) => c[2]), [{ tool: "claude", action: "install" }]);
  assert.strictEqual(global.location.hash, "#/term/n-0123456789ab");
  main = await open("#/setup");
  cs = cards(main);
  await click(byAttr(cs[1], "data-setup-act", "login")[0]);
  await click(byAttr(cs[4], "data-setup-act", "login-cn")[0]);
  await click(byAttr(cs[4], "data-setup-act", "login-global")[0]);
  const posted = calls.filter((c) => c[1] === "/api/setup/terminals").map((c) => c[2]).slice(1);
  assert.deepStrictEqual(posted, [{ tool: "codex", action: "login" }, { tool: "mcode", action: "login", region: "cn" },
    { tool: "mcode", action: "login", region: "global" }]);
  for (const c of calls.filter((x) => x[1] === "/api/setup/terminals")) {
    assert.deepStrictEqual(Object.keys(c[2]).filter((k) => !["tool", "action", "region"].includes(k)), [], "no command, no folder");
  }
});

test("after 安裝, a tool that is still not found says VBear may need to be opened again", async () => {
  app.setupOpened.clear();
  setPage();
  let main = await open("#/setup");
  assert(!text(cards(main)[0]).includes("重新打開 VBear"), "not before the person pressed 安裝");
  await click(byAttr(cards(main)[0], "data-setup-act", "install")[0]);
  main = await open("#/setup");
  assert(text(cards(main)[0]).includes("可能要重新打開 VBear"));
  assert(!text(cards(main)[1]).includes("可能要重新打開 VBear"), "only the tool that was installed from here");
  app.setupOpened.clear();
});

test("「我登入好了」marks the tool, the row becomes ready, and the mark can be taken back", async () => {
  setPage({ tools: [installed("claude"), installed("codex"), installed("agy"), installed("grok")] });
  const main = await open("#/setup");
  await click(byAttr(cards(main)[2], "data-setup-act", "mark")[0]);
  assert.deepStrictEqual(calls.filter((c) => c[1].endsWith("/marker")), [["POST", "/api/setup/tools/agy/marker", { done: true }]]);
  const agy = cards(main)[2];
  assert.strictEqual(attr(agy, "data-state"), "ready");
  assert(text(agy).includes("就緒"));
  await click(byAttr(agy, "data-setup-act", "unmark")[0]);
  assert.deepStrictEqual(calls.filter((c) => c[1].endsWith("/marker")).pop(), ["POST", "/api/setup/tools/agy/marker", { done: false }]);
  assert.strictEqual(attr(cards(main)[2], "data-state"), "not_logged_in");
});

test("you can leave only when a tool is ready; leaving saves the mark and goes to the lobby; the page can be come back to", async () => {
  setPage({ tools: [installed("claude"), row("codex"), row("agy"), row("grok")] });
  let main = await open("#/setup");
  let leave = byAttr(main, "data-setup", "leave")[0];
  assert.strictEqual(leave.disabled, true);
  assert(text(main).includes("要先有一個 AI 工具就緒"));
  assert(text(main).includes("目前還沒有就緒的 AI 工具"));
  setPage({ tools: [ready("claude"), row("codex"), row("agy"), row("grok")] });
  main = await open("#/setup");
  leave = byAttr(main, "data-setup", "leave")[0];
  assert.notStrictEqual(leave.disabled, true);
  assert(!text(main).includes("目前還沒有就緒的 AI 工具"));
  await click(leave);
  assert.deepStrictEqual(calls.filter((c) => c[1] === "/api/config" && c[0] === "POST").map((c) => c[2]), [{ setup_done: true }]);
  assert.strictEqual(global.location.hash, "#/");
  // a person who already finished may go back and leave again without a ready tool (nothing is saved twice)
  setPage({ tools: [row("claude"), row("codex"), row("agy"), row("grok")], setup_done: true });
  main = await open("#/setup");
  leave = byAttr(main, "data-setup", "leave")[0];
  assert.notStrictEqual(leave.disabled, true);
  await click(leave);
  assert.deepStrictEqual(calls.filter((c) => c[1] === "/api/config" && c[0] === "POST"), []);
});

test("recheck asks again; the quiet refresh repaints only when something changed", async () => {
  setPage({ tools: [installed("claude"), row("codex"), row("agy"), row("grok")] });
  const main = await open("#/setup");
  assert(tick, "the page registered a refresh");
  const firstCard = cards(main)[0];
  const n = () => calls.filter((c) => c[1] === "/api/setup/tools" && c[0] === "GET").length;
  const before = n();
  await tick(); await settle();
  assert.strictEqual(n(), before + 1);
  assert.strictEqual(cards(main)[0], firstCard, "nothing changed: not repainted");
  page.tools = [ready("claude"), row("codex"), row("agy"), row("grok")];
  await tick(); await settle();
  assert.strictEqual(attr(cards(main)[0], "data-state"), "ready", "Claude Code became ready by itself");
  await click(byAttr(main, "data-setup", "recheck")[0]);
  assert.strictEqual(n(), before + 3);
});

test("the route and the nav: #/setup is a page, the nav and the settings page lead to it", async () => {
  setPage();
  const main = await open("#/setup");
  assert(byAttr(main, "data-setup", "page").length === 1);
  const html = fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8");
  assert(/<a href="#\/setup" data-nav="setup">[^<]*<span aria-hidden="true">[^<]*<\/span>開始設定<\/a>/.test(html));
  assert(html.indexOf('data-nav="setup"') < html.indexOf('data-nav="office"'), "near the top of the nav");
  const link = app.setupSettings ? app.setupSettings() : null;
  assert(!link || attr(link.find((n) => attr(n, "data-setup") === "open"), "href") === "#/setup");
});

test("home: a person who has not finished and has no ready tool is sent to the start-up", async () => {
  setPage({ config: { setup_done: false, onboarding_dismissed: true } });
  const main = await open("#/");
  assert.strictEqual(global.location.hash, "#/setup");
  assert(calls.some((c) => c[1] === "/api/setup/settle" && c[0] === "POST"));
  assert(!text(main).includes("冒險者大廳"), "the lobby was not drawn first");
});

test("home: an upgrader with a ready tool stays on the lobby and is told once", async () => {
  setPage({ config: { setup_done: false, onboarding_dismissed: true }, settle: { ok: true, setup_done: true, setup_notice: true, upgraded: true } });
  const main = await open("#/");
  assert.strictEqual(global.location.hash, "#/");
  const note = byAttr(main, "data-setup", "upgrade-notice")[0];
  assert(note && text(note).includes(app.SETUP_UPGRADE_NOTICE) && attr(note.find((n) => n.tag === "a"), "href") === "#/setup");
  assert.deepStrictEqual(calls.filter((c) => c[1] === "/api/config" && c[0] === "POST").map((c) => c[2]), [{ setup_notice: false }], "the notice is put away at once");
  // and a person who finished long ago sees nothing and nothing is asked
  setPage({ config: { setup_done: true, setup_notice: false, onboarding_dismissed: true } });
  const again = await open("#/");
  assert.strictEqual(byAttr(again, "data-setup", "upgrade-notice").length, 0);
  assert(!calls.some((c) => c[1].startsWith("/api/setup/")), "no tool was asked");
});

test("home: the server saying nothing (no setup_done, no config, a failed settle) forces nobody anywhere", async () => {
  for (const config of [{ onboarding_dismissed: true }, undefined]) {
    setPage({ config });
    await open("#/");
    assert.strictEqual(global.location.hash, "#/", JSON.stringify(config));
    assert(!calls.some((c) => c[1] === "/api/setup/settle"));
  }
  setPage({ config: { setup_done: false, onboarding_dismissed: true } });
  const inner = global.fetch;
  global.fetch = async (url, opts) => (String(url) === "/api/setup/settle" ? jsonResponse({ error: "boom" }, false, 500) : inner(url, opts));
  try { await open("#/"); } finally { global.fetch = inner; }
  assert.strictEqual(global.location.hash, "#/");
});

test("the first game stays on the lobby, after the start-up (the lobby is where it is drawn)", async () => {
  setPage({ config: { setup_done: true, onboarding_dismissed: false }, tools: [ready("claude")] });
  const main = await open("#/");
  assert.strictEqual(global.location.hash, "#/");
  assert(text(main).includes("冒險者大廳") && text(main).includes("新手第一局"), "the first game is still on the lobby");
});

test("the terminal of the start-up page is named after the tool and the action, and explained in plain words", () => {
  let w = app.setupTerminalWords({ tool: "claude", action: "install", region: null });
  assert.strictEqual(w.title, "Claude Code 安裝");
  assert(w.lines.some((l) => /不用打任何字/.test(l)) && w.lines.some((l) => /重新打開 VBear/.test(l)));
  w = app.setupTerminalWords({ tool: "mcode", action: "login", region: "cn" });
  assert.strictEqual(w.title, "MCODE 登入");
  assert(w.lines.some((l) => /瀏覽器/.test(l)) && w.lines.some((l) => /我登入好了/.test(l)));
  assert.strictEqual(app.setupTerminalWords(null).title, "");
});

test("a start-up terminal is listed and tabbed under the tool and the action, a plain one as before", () => {
  const setup = { tool: "grok", action: "login", region: null, command: "grok login" };
  assert.strictEqual(app.shellLabel({ pane_id: "n-0123456789ab", kind: "shell", cwd: "/home/u", setup }, "/home/u"), "Grok 登入");
  assert.strictEqual(app.shellLabel({ pane_id: "n-0123456789ab", kind: "shell", cwd: "/home/u/app", setup: null }, "/home/u"), "app");
  assert.strictEqual(app.shellLabel({ pane_id: "n-0123456789ab", kind: "shell", cwd: "/home/u" }, "/home/u"), "~");
  const panes = [{ kind: "shell", exited: false, setup }, { kind: "shell", exited: false }, { kind: "shell", exited: true, setup }];
  assert.strictEqual(app.shellPanes(panes).length, 2, "it is a shell terminal like the others, so it can be closed and listed");
});

test("the terminal page of a start-up terminal says in plain words what is happening and leads back to the start-up page", async () => {
  setPage();
  const inner = global.fetch;
  const setup = { tool: "claude", action: "install", region: null, command: "curl -fsSL https://claude.ai/install.sh | bash" };
  global.fetch = async (url, opts) => {
    if (String(url).split("?")[0] === "/api/live") {
      return jsonResponse({ runtime: { available: true, problems: [] }, sessions: [], attention: [], projects: [], usage: { sessions: [] }, home: "/home/u",
        panes: [{ pane_id: "n-0123456789ab", terminal_id: "n-0123456789ab", kind: "shell", cwd: "/home/u", exited: false, setup }] });
    }
    return inner(url, opts);
  };
  try {
    const main = await open("#/term/n-0123456789ab");
    const t = text(main);
    assert(t.includes("Claude Code 安裝"), "named after the tool and the action");
    assert(t.includes("官方安裝指令") && t.includes("你不用打任何字"), "what happens, in plain words");
    const back = byAttr(main, "data-term", "back-setup")[0];
    assert(back && attr(back, "href") === "#/setup" && text(back) === "回開始設定");
    assert(byAttr(main, "data-setup", "terminal-note").length === 1);
  } finally { global.fetch = inner; }
});

test("source: built with el(), no innerHTML, no emoji, no outside resource, and none of the words a first-time person cannot read", () => {
  assert(BLOCK.length > 4000);
  assert(!/innerHTML|insertAdjacentHTML/.test(BLOCK));
  assert(!/\p{Extended_Pictographic}/u.test(BLOCK));
  assert(!/https?:\/\//.test(BLOCK));
  const strings = (BLOCK.match(/"[^"\n]*[一-鿿][^"\n]*"|`[^`\n]*[一-鿿][^`\n]*`/g) || []).join("\n");
  assert(strings.length > 500);
  assert(!/\bCLI\b|argv|\bPATH\b/.test(strings), "the words of the glossary only");
  assert(!/innerHTML/.test(fs.readFileSync(path.join(__dirname, "..", "..", "web", "index.html"), "utf8")));
});

test("style: the cards follow the theme variables, wrap on a narrow screen and have no outside resource", () => {
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "web", "style.css"), "utf8");
  const part = css.slice(css.indexOf("/* the start-up page"));
  for (const sel of [".setup-list", ".setup-tool", ".setup-head", ".setup-actions", ".setup-text"]) assert(part.includes(sel), sel);
  assert(/\.setup-tool\s*\{[^}]*var\(--panel\)[^}]*var\(--line-2\)|\.setup-tool\s*\{[^}]*var\(--line-2\)[^}]*var\(--panel\)/.test(part));
  assert(!/#[0-9a-fA-F]{3,6}\b/.test(part), "colours come from the theme variables, so light and dark both read");
  assert(/@media \(max-width: 520px\)/.test(part) && /flex-wrap:\s*wrap/.test(part) && /overflow-wrap:\s*anywhere/.test(part));
  assert(!/url\(|@import|https?:\/\//.test(part));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
