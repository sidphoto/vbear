// S2c-4: the flow page's VBear-managed panels: the risk-acceptance dialog, the executor, the dispatch composer,
// reports, reviews and the merge gate. The real web/app.js on a synthetic DOM, fetch answered by the test.
// Run: node tests/frontend/coordinator.cjs   (exit code 0 = pass)
"use strict";

const assert = require("assert");
const h = require("./lib/s2_harness.cjs");
const { app, SyntheticNode, FETCH_LOG, jsonResponse, setHandler } = h;
const { mountCoordinator, openAcceptanceDialog } = app;

const FLOW = "flow-0123456789ab";
const COMMIT = "a".repeat(40);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(n = 40) { for (let i = 0; i < n; i++) await Promise.resolve(); await sleep(5); for (let i = 0; i < n; i++) await Promise.resolve(); }

Object.defineProperty(global, "navigator", { value: { clipboard: { _last: null, async writeText(t) { this._last = t; } } }, configurable: true });
global.document.querySelector = () => null;

// ---- fixtures -----------------------------------------------------------------------------------------------
function executor(over = {}) {
  return {
    ok: true, flow_id: FLOW,
    acceptance: { state: "valid", reason: "", accepted_at: 1791000000, values: {
      text_version: "2026-10-11.1", codex_version: "0.160.0", review_model: "gpt-6-luna",
      executor_claude_version: "2.1.292", executor_model: "claude-haiku-4-5-20251001",
      executor_account: "a1b2c3d4e5f60718", review_account: "0f1e2d3c4b5a6978", login_key_id: "c".repeat(16), limits: [] } },
    hold: { held: false, reason: "", at: null }, workdir: "/work", workdir_problem: null,
    accounting: { ok: true, started_at: 1791000000, elapsed_s: 600, dispatches: 1, responses: 5, spent_usd: 0.12, reviews: 0,
      limits: { max_dispatches: 20, executor_total_max_responses: 1000, executor_budget_usd: 20, max_reviews: 6, max_elapsed_h: 8 },
      remaining: {} },
    failures: [], unresolved_failure: null, sessions: [], sessions_problem: null, current_launch_id: null, can_start: true,
    ...over,
  };
}
const liveSession = (over = {}) => ({
  launch_id: "l-" + "1".repeat(16), manifest_state: "running", model_id: "claude-haiku-4-5-20251001", cli_version: "2.1.292",
  status: { live: true, state: "idle", responses: 5, total_cost_usd: 0.12, dispatches: [] }, status_problem: null,
  worst_case: null, retained_reason: null, ...over,
});
const reportEntry = (over = {}) => ({
  launch_id: "l-" + "1".repeat(16), dispatch_id: "d1d1d1d1-aaaa-4bbb-8ccc-0123456789ab", status: "ended", valid: true,
  reasons: [], latest: true, usable: true,
  report: { v: 1, dispatch_id: "d1d1d1d1-aaaa-4bbb-8ccc-0123456789ab", status: "done", head: COMMIT,
    tests: { command: "python3 -m unittest", result: "passed", summary: "ok" }, notes: "做完了" },
  checks: [{ id: "head_is_current", ok: true, label: "回報的 head 等於任務工作目錄目前的 commit", detail: "" },
    { id: "commit_exists", ok: true, label: "回報的 commit 物件存在", detail: "" }],
  ...over,
});
const reviewEntry = (over = {}) => ({
  job_id: "r-" + "2".repeat(16), round: 1, commit: COMMIT, state: "cleaned", outcome: "valid", record: "complete",
  invalid_reasons: null, retained_reason: null, live: null,
  result: { valid: true, verdict: "NEEDS WORK", base_is_ancestor: true, reasons: [],
    base_is_ancestor_note: "審查者自行回報的結果，VBear 沒有獨立驗證。" },
  report: { format: "plain_text", text: "有一個問題。\nREVIEWED_COMMIT: " + COMMIT + "\nVERDICT: NEEDS WORK", problem: "", usable: true },
  ...over,
});
const gate = (over = {}) => ({
  ok: true, flow_id: FLOW, open: false, workdir: "/work", commit: null, note: "VBear 不執行 git：以下指令由你自己決定要不要執行、怎麼執行。",
  conditions: [{ id: "review_pass", ok: false, label: "最新一輪審查有效而且是 PASS", detail: "還沒有審查" }],
  commands: [], commands_note: null,
  after: [{ ref: "refs/heads/main", text: "本機 refs/heads/main 目前指向 " + COMMIT, commit: COMMIT, is_reviewed_commit: false, caveat: null }],
  ...over,
});

let state;
function reset(over = {}) {
  state = { executor: executor(), reports: { ok: true, reports: [], latest_dispatch_id: null }, reviews: { ok: true, reviews: [] },
    gate: gate(), preview: null, accept: null, post: {},
    storage: { ok: true, limit_bytes: 4294967296, used_bytes: 1048576, problem: "", note: "只有沒有程序在執行的流程才能刪除。",
      flows: [{ flow_id: FLOW, task_id: "task-1", bytes: 1048576, sessions: 1, reviews: 2, has_data: true, held: false,
        deletable: true, reasons: [], note: "" }] }, ...over };
  FETCH_LOG.length = 0;
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    const post = (opts.method || "GET") === "POST";
    const answer = (v, st = 200) => jsonResponse(v, st < 400, st);
    if (!post) {
      if (p.endsWith("/executor")) return state.executorError ? answer({ error: state.executorError }, 500) : answer(state.executor);
      if (p.endsWith("/reports")) return answer(state.reports);
      if (p.endsWith("/reviews")) return answer(state.reviews);
      if (p.endsWith("/merge-gate")) return answer(state.gate);
      if (p.endsWith("/api/flows/storage")) return answer(state.storage);
      const m = /\/reviews\/(r-[0-9a-f]{16})\/draft$/.exec(p);
      if (m) return answer({ ok: true, text: "DRAFT\n" + m[1], truncated: false, format: "plain_text" });
      return null;
    }
    const key = p.replace(/^.*\/api\/flows\/[^/]+\//, "");
    if (state.post[key]) return answer(...[].concat(state.post[key]));
    return answer({ ok: true });
  });
}
const posts = () => FETCH_LOG.filter((x) => x.method === "POST");
const find = (node, pred) => node.find(pred);
const byS2 = (root, name) => find(root, (n) => n.getAttribute && n.getAttribute("data-s2") === name);
const button = (root, text) => find(root, (n) => n.tag === "button" && n.textContent.includes(text));
const text = (n) => (n ? n.textContent : "");

async function mount(over) {
  reset(over);
  const c = mountCoordinator(FLOW);
  await settle();
  return c;
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- tests -------------------------------------------------------------------------------------------------

test("the panels are mounted and say what they show", async () => {
  const c = await mount();
  for (const name of ["acceptance", "executor", "reports", "reviews", "gate", "dispatch"]) assert(byS2(c.node, name), name);
  assert(text(byS2(c.node, "acceptance")).includes("風險已接受"));
  assert(text(byS2(c.node, "acceptance")).includes("a1b2c3d4e5f60718"));            // only the first 16 digits exist here
  assert(!/[0-9a-f]{64}/.test(text(c.node)));
});

test("a failed read is said in its own panel and the others still show", async () => {
  const c = await mount({ executorError: "背景程序沒有回應" });
  assert(text(c.node).includes("無法讀取執行者狀態"));
  assert(text(c.node).includes("背景程序沒有回應"));
  assert(byS2(c.node, "gate"));
});

test("start is offered only when the server says so, and posts nothing but an empty request", async () => {
  let c = await mount({ executor: executor({ can_start: false, acceptance: { state: "none", reason: "還沒有接受殘餘風險" } }) });
  const off = button(byS2(c.node, "executor"), "啟動執行者");
  assert(off.disabled, "disabled without an acceptance");
  assert(text(byS2(c.node, "executor")).includes("需要有效的風險接受"));
  c = await mount();
  const on = button(byS2(c.node, "executor"), "啟動執行者");
  assert(!on.disabled);
  on.click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/executor"));
  assert(p && JSON.stringify(p.body) === "{}", "an empty request: the model and version come from the acceptance");
});

test("a stopped flow shows why, and continue is the way out", async () => {
  const c = await mount({ executor: executor({ hold: { held: true, reason: "failure: session l-x: 回合沒有結果", at: 1791000100 }, can_start: false }) });
  const ex = byS2(c.node, "executor");
  assert(text(ex).includes("流程已停止：failure: session l-x: 回合沒有結果"));
  const cont = button(ex, "繼續");
  assert(cont && !cont.disabled);
  cont.click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/continue")));
});

test("closing a session reads the stored-data panel again, so its delete button follows", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  const reads = () => FETCH_LOG.filter((x) => x.url.endsWith("/api/flows/storage")).length;
  const before = reads();
  assert(before >= 1, "read once when the page was drawn");
  button(byS2(c.node, "executor"), "關閉 session").click();
  await settle();
  button(byS2(c.node, "executor"), "確定").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/executor/close")), "the session was closed");
  assert(reads() > before, "the storage panel was read again after the close");
  c.stop();
});

test("only what the flow keeps reloads the stored-data panel, not the clock", async () => {
  const ex = executor({ sessions: [liveSession()] });
  const c = await mount({ executor: ex });
  const reads = () => FETCH_LOG.filter((x) => x.url.endsWith("/api/flows/storage")).length;
  const first = reads();
  for (let i = 1; i <= 3; i += 1) {                 // the elapsed time and the counters move every round
    state.executor = executor({ sessions: [liveSession({ status: { live: true, state: "idle", responses: 5 + i,
      total_cost_usd: 0.12 + i / 100, dispatches: [] } })] });
    state.executor.accounting.elapsed_s = 600 + i * 5;
    state.executor.accounting.responses = 5 + i;
    await c.refresh(false);
  }
  assert.strictEqual(reads(), first, "no inventory for numbers that only count up");
  state.executor = executor({ sessions: [liveSession({ manifest_state: "ended", status: { live: false, state: "exited",
    dispatches: [] } })] });
  await c.refresh(false);
  assert.strictEqual(reads(), first + 1, "a session that ended does");
  state.executor = executor({ sessions: [liveSession({ manifest_state: "ended", status: { live: false, state: "exited",
    dispatches: [] } })], hold: { held: true, reason: "x", at: 1 } });
  await c.refresh(false);
  assert.strictEqual(reads(), first + 2, "so does a stop");
  c.stop();
});

test("stopping takes two steps and cancel does nothing", async () => {
  const c = await mount();
  const ex = byS2(c.node, "executor");
  button(ex, "停止這個流程").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/hold")), "one click is a question, not a stop");
  assert(text(byS2(c.node, "executor")).includes("確定"));
  button(byS2(c.node, "executor"), "取消").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/hold")));
  button(byS2(c.node, "executor"), "停止這個流程").click();
  button(byS2(c.node, "executor"), "確定").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/hold")));
});

test("the worst-case statement is shown as the server wrote it", async () => {
  const wc = { text: "上一輪沒有結果，費用未知，以最壞情況計入（回應數 200、USD 20.0）。要繼續就需要重新接受風險，必要時調高額度。" };
  const c = await mount({ executor: executor({ sessions: [liveSession({ manifest_state: "manual_review", status: { live: false, state: "error", dispatches: [] }, worst_case: wc, retained_reason: "x" })] }) });
  assert(text(byS2(c.node, "executor")).includes(wc.text));
});

test("limits are counted against their caps and the one that is reached is marked", async () => {
  const ex = executor();
  ex.accounting.dispatches = 20;
  const c = await mount({ executor: ex });
  const meters = byS2(c.node, "executor");
  assert(text(meters).includes("派工：20 則 ／ 上限 20 則"));
  assert(find(meters, (n) => n.tag === "b" && n.hasClass("s2-over")), "reached limit is marked");
});

test("the dispatch composer shows exactly what will be sent and approves only the preview id", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  state.post["dispatch-preview"] = [{ ok: true, preview_id: "p".repeat(32), expires_at: 1791000300, dispatch_id: "d".repeat(8) + "-aaaa-4bbb-8ccc-0123456789ab",
    launch_id: "l-" + "1".repeat(16), text: "請完成工作\\u0001", text_sha256: "f".repeat(64), bytes: 20, rewritten: true, ready: true, not_ready_reason: "" }];
  const box = find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea");
  box.value = "請完成工作\u0001";
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  const pre = posts().find((x) => x.url.endsWith("/dispatch-preview"));
  assert.deepStrictEqual(pre.body, { launch_id: "l-" + "1".repeat(16), text: "請完成工作\u0001" });
  const shown = byS2(c.node, "dispatch");
  assert(text(shown).includes("請完成工作\\u0001"), "the rewritten text is what is shown");
  assert(text(shown).includes("已改寫成可見的"));
  button(shown, "核准並送出").click();
  await settle();
  const ap = posts().find((x) => x.url.endsWith("/dispatch"));
  assert.deepStrictEqual(ap.body, { preview_id: "p".repeat(32) });                 // no text, no launch id
});

test("a session that is not ready can be previewed but not approved", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  state.post["dispatch-preview"] = [{ ok: true, preview_id: "q".repeat(32), expires_at: 1791000300, dispatch_id: "x", launch_id: "l-" + "1".repeat(16),
    text: "t", text_sha256: "f".repeat(64), bytes: 1, rewritten: false, ready: false, not_ready_reason: "session 現在是「turn_running」" }];
  find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea").value = "t";
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  assert(button(byS2(c.node, "dispatch"), "核准並送出").disabled);
  assert(text(byS2(c.node, "dispatch")).includes("現在還不能送出"));
});

test("with no live session there is nothing to preview against", async () => {
  const c = await mount();
  find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea").value = "t";
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/dispatch-preview")));
});

test("an approval the server refuses (409) says the preview is void", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  state.post["dispatch-preview"] = [{ ok: true, preview_id: "r".repeat(32), expires_at: 1791000300, dispatch_id: "x", launch_id: "l-" + "1".repeat(16),
    text: "t", text_sha256: "f".repeat(64), bytes: 1, rewritten: false, ready: true, not_ready_reason: "" }];
  state.post["dispatch"] = [{ error: "現在不能派工：session 不是 idle", code: "conflict" }, 409];
  find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea").value = "t";
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  button(byS2(c.node, "dispatch"), "核准並送出").click();
  await settle();
  assert(text(byS2(c.node, "dispatch")).includes("現在不能派工"));
  assert(text(byS2(c.node, "dispatch")).includes("這份預覽已作廢"));
});

test("reports keep the executor's words and VBear's checks apart", async () => {
  const c = await mount({ reports: { ok: true, latest_dispatch_id: "d", reports: [
    reportEntry(), reportEntry({ latest: false, usable: false, checks: null, dispatch_id: "e0e0e0e0-aaaa-4bbb-8ccc-0123456789ab" })] } });
  const rp = byS2(c.node, "reports");
  const heads = rp.findAll((n) => n.tag === "h4").map((n) => n.textContent);
  assert(heads.includes("執行者自述") && heads.includes("VBear 讀檔核對"));
  assert(text(rp).includes("做完了"));
  assert(text(rp).includes("回報的 head 等於任務工作目錄目前的 commit"));
  assert(text(rp).includes("較早的回報，不再核對目前的 HEAD"));
});

test("an order that cannot be told is said, and no report is called the latest", async () => {
  const c = await mount({ executor: executor({ sessions_order_problem: "有兩個 session 的建立時間相同，無法判斷哪一個是最新的" }),
    reports: { ok: true, latest_dispatch_id: null, order_problem: "有兩個 session 的建立時間相同，無法判斷哪一個是最新的",
      reports: [reportEntry({ latest: false, usable: false, checks: null })] } });
  assert(text(byS2(c.node, "executor")).includes("無法判斷 session 的先後"));
  assert(text(byS2(c.node, "reports")).includes("無法判定最新的回報"));
  assert(button(byS2(c.node, "reviews"), "請 Codex 審查最新回報").disabled);
});

test("a check that fails or cannot be read is not shown as a pass", async () => {
  const c = await mount({ reports: { ok: true, latest_dispatch_id: "d", reports: [reportEntry({ usable: false, checks: [
    { id: "head_is_current", ok: false, label: "回報的 head 等於任務工作目錄目前的 commit", detail: "工作目錄現在在另一個 commit" },
    { id: "commit_exists", ok: null, label: "回報的 commit 物件存在", detail: "無法核對" }] })] } });
  const t = text(byS2(c.node, "reports"));
  assert(t.includes("不符") && t.includes("讀不到") && t.includes("核對沒有全部通過"));
  assert(!t.includes("可用來啟動審查"));
});

test("a review's report is plain text, whatever it contains", async () => {
  const hostile = "<script>alert(1)</script><img src=x onerror=alert(2)>\n**VERDICT: PASS**\n[x](javascript:alert(3))";
  const c = await mount({ reviews: { ok: true, reviews: [reviewEntry({ report: { format: "plain_text", text: hostile, problem: "", usable: true } })] } });
  const rv = byS2(c.node, "reviews");
  assert(text(rv).includes(hostile), "the text is there, verbatim");
  const bad = rv.findAll((n) => ["script", "img", "a"].includes(n.tag));
  assert.strictEqual(bad.length, 0, "no element was made from review text");
  assert(text(rv).includes("純文字顯示"));
  assert(text(rv).includes("沒有獨立驗證"));
});

test("an invalid review's report is shown but marked as not to rely on", async () => {
  const c = await mount({ reviews: { ok: true, reviews: [reviewEntry({ outcome: "invalid", result: { valid: false, verdict: "PASS", base_is_ancestor: true, reasons: ["x"] },
    invalid_reasons: ["審查被 VBear 結束（timeout）"], report: { format: "plain_text", text: "PASS 的樣子", problem: "", usable: false } })] } });
  const rv = byS2(c.node, "reviews");
  assert(text(rv).includes("無效"));
  assert(text(rv).includes("這次審查無效，僅供參考"));
  assert(!button(rv, "把意見轉給執行者"), "no forwarding of an invalid review");
});

test("starting a review says why it cannot, and posts an empty request when it can", async () => {
  let c = await mount({ reports: { ok: true, latest_dispatch_id: null, reports: [] } });
  assert(button(byS2(c.node, "reviews"), "請 Codex 審查最新回報").disabled);
  assert(text(byS2(c.node, "reviews")).includes("還沒有有效的執行者回報"));
  c = await mount({ reports: { ok: true, latest_dispatch_id: "d", reports: [reportEntry()] } });
  const b = button(byS2(c.node, "reviews"), "請 Codex 審查最新回報");
  assert(!b.disabled);
  b.click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/review"));
  assert.deepStrictEqual(p.body, {});
});

test("a running review shows its progress and can be cancelled in two steps", async () => {
  const job = "r-" + "3".repeat(16);
  const c = await mount({ reports: { ok: true, latest_dispatch_id: "d", reports: [reportEntry()] },
    reviews: { ok: true, reviews: [reviewEntry({ job_id: job, state: "running", outcome: null, result: null, report: null, live: { responses_seen: 4, elapsed_s: 30 } })] } });
  const rv = byS2(c.node, "reviews");
  assert(text(rv).includes("進行中：回應 4"));
  assert(button(rv, "請 Codex 審查最新回報").disabled);
  button(rv, "取消審查").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/review/cancel")));
  button(byS2(c.node, "reviews"), "確定").click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/review/cancel"));
  assert.deepStrictEqual(p.body, { job_id: job });
});

test("forwarding an opinion only fills the composer; nothing is sent", async () => {
  const c = await mount({ reviews: { ok: true, reviews: [reviewEntry()] } });
  const before = posts().length;
  button(byS2(c.node, "reviews"), "把意見轉給執行者").click();
  await settle();
  assert.strictEqual(posts().length, before, "no POST: a draft is not a dispatch");
  const box = find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea");
  assert(box.value.startsWith("DRAFT\nr-"));
});

test("the merge gate shows the commands only when it is open, as text with a copy button", async () => {
  let c = await mount();
  assert(text(byS2(c.node, "gate")).includes("尚未符合"));
  assert(!byS2(c.node, "gate").findAll((n) => n.tag === "pre").length, "no commands while closed");
  const cmd = `git -C '/work' merge --ff-only ${COMMIT}`;
  c = await mount({ gate: gate({ open: true, commit: COMMIT, commands: [{ label: "只接受快轉合併", command: cmd }], conditions: [
    { id: "review_pass", ok: true, label: "最新一輪審查有效而且是 PASS", detail: "" }] }) });
  const g = byS2(c.node, "gate");
  assert(text(g).includes("條件都符合"));
  assert(text(g).includes(cmd));
  assert(text(g).includes("VBear 不會執行 git"));
  button(g, "複製").click();
  await settle();
  assert.strictEqual(global.navigator.clipboard._last, cmd);
  assert(!posts().length, "copying posts nothing");
});

test("the local refs are labelled as what they are", async () => {
  const c = await mount({ gate: gate({ after: [
    { ref: "refs/heads/main", text: "本機 refs/heads/main 目前指向 " + COMMIT, commit: COMMIT, is_reviewed_commit: true, caveat: null },
    { ref: "refs/remotes/origin/main", text: "本機 refs/remotes/origin/main 目前指向：未知（這個本機 ref 不存在）", commit: null, is_reviewed_commit: false, caveat: "這是本機記下的位置，不代表遠端現在的狀態" }] }) });
  const t = text(byS2(c.node, "gate"));
  assert(t.includes("本機 refs/heads/main 目前指向 " + COMMIT));
  assert(t.includes("就是被審的 commit"));
  assert(t.includes("未知（這個本機 ref 不存在）"));
  assert(t.includes("不代表遠端現在的狀態"));
});

test("a refresh with nothing new leaves the page alone, and one with news keeps what the user typed", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  const box = find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea");
  box.value = "我正在打的字";
  const dataBefore = c.node.find((n) => n.hasClass && n.hasClass("s2-data")).children.slice();
  await c.refresh(false);
  const dataSame = c.node.find((n) => n.hasClass && n.hasClass("s2-data")).children;
  assert.strictEqual(dataSame[0], dataBefore[0], "unchanged data: the same nodes");
  state.executor = executor({ sessions: [liveSession({ status: { live: true, state: "turn_running", responses: 6, total_cost_usd: 0.2, dispatches: [] } })] });
  await c.refresh(false);
  assert.notStrictEqual(c.node.find((n) => n.hasClass && n.hasClass("s2-data")).children[0], dataBefore[0], "changed data: re-rendered");
  assert.strictEqual(find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea").value, "我正在打的字", "the composer is not rebuilt");
  assert(text(byS2(c.node, "executor")).includes("執行中"));
});

test("a stopped panel stops refreshing", async () => {
  const c = await mount();
  const n = FETCH_LOG.length;
  c.stop();
  await c.refresh(true);
  assert.strictEqual(FETCH_LOG.length, n, "nothing is fetched after stop()");
});

test("a dialog is never refreshed under the user", async () => {
  const c = await mount();
  const n = FETCH_LOG.length;
  global.document.querySelector = (sel) => (sel === ".modal-backdrop" ? new SyntheticNode("div") : null);
  await c.tick();
  global.document.querySelector = () => null;
  assert.strictEqual(FETCH_LOG.length, n);
});

// ---- the acceptance dialog ----------------------------------------------------------------------------------

const preview = (over = {}) => ({
  ok: true, preview_id: "a".repeat(32), expires_at: 1791000300, ttl_s: 300,
  risk_text: {
    zh: { version: "2026-10-11.1", lang: "zh", title: "接受殘餘風險", intro: "下列三項殘餘風險無法由設計消除。", confirm: "我了解並接受以上殘餘風險",
      items: [{ id: "tools", title: "Codex 的工具集合無法事先證明", body: "第一項的全文。" }, { id: "limits", title: "上限的強度不一", body: "第二項的全文，512 MiB。" },
        { id: "managed", title: "伺服器管理設定", body: "第三項的全文。" }] },
    en: { version: "2026-10-11.1", lang: "en", title: "Accept", intro: "x", confirm: "ok", items: [{ id: "tools", title: "T", body: "English one." }] },
  },
  values: { text_version: "2026-10-11.1", codex_version: "0.160.0", review_model: "gpt-6-luna", executor_claude_version: "2.1.292",
    executor_model: "claude-haiku-4-5-20251001", executor_account: "a1b2c3d4e5f60718", review_account: "0f1e2d3c4b5a6978",
    login_key_id: "c".repeat(16), limits: [
      ["max_reviews", "審查次數", "次", 6, 6, 10], ["max_dispatches", "派工則數", "則", 20, 20, 40], ["review_max_responses", "單次審查回應數", "次", 300, 300, 600],
      ["executor_turn_max_responses", "執行者每輪回應數", "次", 200, 200, 400], ["executor_total_max_responses", "執行者總回應數", "次", 1000, 1000, 2000],
      ["review_timeout_min", "審查逾時", "分鐘", 45, 45, 90], ["executor_turn_timeout_min", "一輪逾時", "分鐘", 60, 60, 180],
      ["max_elapsed_h", "經過時間", "小時", 8, 8, 24], ["executor_budget_usd", "執行者額度", "USD", 20, 20, 100]]
      .map(([name, label, unit, value, def, cap]) => ({ name, label, unit, value, default: def, cap })) },
  suggested_executor_models: ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"], review_models: ["gpt-6-luna", "gpt-6.1-sol"],
  ...over,
});
function openDialog(handlers = {}) {
  reset();
  state.post["acceptance-preview"] = handlers.preview;
  state.post["acceptance"] = handlers.confirm;
  let done = 0;
  openAcceptanceDialog(FLOW, () => { done += 1; });
  return { done: () => done, modal: () => dom().bodyEl.children[dom().bodyEl.children.length - 1] };
}
const dom = h.dom;

test("the dialog shows every item in full and the values the acceptance binds", async () => {
  const d = openDialog({ preview: [preview()] });
  await settle();
  const m = d.modal();
  const t = text(m);
  for (const s of ["第一項的全文。", "第二項的全文，512 MiB。", "第三項的全文。", "0.160.0", "gpt-6-luna", "2.1.292", "a1b2c3d4e5f60718", "0f1e2d3c4b5a6978", "2026-10-11.1"]) {
    assert(t.includes(s), s);
  }
  assert.strictEqual(m.findAll((n) => n.tag === "input" && n.dataset && n.dataset.limit).length, 9, "all nine limits");
  assert(t.includes("預設 6，上限 10"));
  assert(!/[0-9a-f]{64}/.test(t));
});

test("the confirm button needs the box ticked, and posts only the preview id", async () => {
  const d = openDialog({ preview: [preview()], confirm: [{ ok: true, flow: {} }] });
  await settle();
  const m = d.modal();
  const accept = button(m, "接受並記錄");
  assert(accept.disabled, "nothing is recorded without the tick");
  const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
  tick.checked = true;
  tick.dispatch("change");
  assert(!accept.disabled);
  accept.click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/acceptance"));
  assert.deepStrictEqual(p.body, { preview_id: "a".repeat(32) });
  assert.strictEqual(d.done(), 1);
});

test("a login that is missing says what to run, and offers no acceptance", async () => {
  const d = openDialog({ preview: [{ error: "VBear 專用的 Codex 設定目錄還沒有可用的登入", code: "needs_login",
    login_command: "CODEX_HOME=/s/codex-home /pinned/codex login -c cli_auth_credentials_store=file", codex_home: "/s/codex-home" }, 409] });
  await settle();
  const m = d.modal();
  assert(text(m).includes("CODEX_HOME=/s/codex-home /pinned/codex login -c cli_auth_credentials_store=file"));
  assert(text(m).includes("VBear 不會替你登入，也不會讀取憑證"));
  assert(button(m, "接受並記錄").disabled);
});

test("a conflict at confirmation voids the preview and says so", async () => {
  const d = openDialog({ preview: [preview()], confirm: [{ error: "預覽之後下列內容已改變，請重新預覽：login_fingerprint", code: "conflict" }, 409] });
  await settle();
  const m = d.modal();
  const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
  tick.checked = true;
  tick.dispatch("change");
  button(m, "接受並記錄").click();
  await settle();
  assert(text(m).includes("login_fingerprint"));
  assert(text(m).includes("這份預覽已作廢"));
  assert(button(m, "接受並記錄").disabled, "cannot be confirmed again without a new preview");
  assert.strictEqual(d.done(), 0);
});

test("changed limits and models are sent to a new preview, never to the confirmation", async () => {
  const d = openDialog({ preview: [preview()], confirm: [{ ok: true }] });
  await settle();
  const m = d.modal();
  const inputs = m.findAll((n) => n.tag === "input" && n.dataset && n.dataset.limit);
  inputs.find((i) => i.dataset.limit === "max_reviews").value = "3";
  button(m, "套用並重新預覽").click();
  await settle();
  const previews = posts().filter((x) => x.url.endsWith("/acceptance-preview"));
  assert.strictEqual(previews.length, 2);
  assert.strictEqual(previews[1].body.limits.max_reviews, 3);
  assert.strictEqual(typeof previews[1].body.executor_model, "string");
  assert(!posts().some((x) => x.url.endsWith("/acceptance")), "nothing recorded by applying");
});

test("changing any setting voids the preview: the box is cleared and accepting sends nothing", async () => {
  for (const which of ["limit", "model", "review"]) {
    const d = openDialog({ preview: [preview()], confirm: [{ ok: true }] });
    await settle();
    const m = d.modal();
    const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
    tick.checked = true;
    tick.dispatch("change");
    const accept = button(m, "接受並記錄");
    assert(!accept.disabled, "ticked: accept is on");
    if (which === "limit") {
      const i = m.findAll((n) => n.tag === "input" && n.dataset && n.dataset.limit)[0];
      i.value = "3";
      i.dispatch("input");
    } else if (which === "model") {
      const i = find(m, (n) => n.tag === "input" && n.getAttribute("list") === "s2-exec-models");
      i.value = "claude-sonnet-5-5";
      i.dispatch("input");
    } else {
      const sel = find(m, (n) => n.tag === "select");
      sel.value = "gpt-6.1-sol";
      sel.dispatch("change");
    }
    assert(accept.disabled, `${which}: accept is off`);
    assert(!tick.checked && tick.disabled, `${which}: the tick is cleared and cannot be set`);
    assert(text(m).includes("設定已變更，這份預覽已作廢"), which);
    accept.click();
    await settle();
    assert(!posts().some((x) => x.url.endsWith("/acceptance")), `${which}: nothing is sent`);
    // a new preview of the new values is what can be accepted
    button(m, "套用並重新預覽").click();
    await settle();
    assert(!text(m).includes("設定已變更"), `${which}: the notice goes with the new preview`);
    assert(button(m, "接受並記錄").disabled, `${which}: still off until the tick`);
    FETCH_LOG.length = 0;
  }
});

// ---- storage and deleting a flow (S2c-5) ---------------------------------------------------------------------

test("storage shows size and counts, and deleting takes two steps and names the flow", async () => {
  reset();
  let gone = null;
  const s = app.mountStorage({ afterDelete: (id) => { gone = id; } });
  await settle();
  const t = text(s.node);
  assert(t.includes("1.0 MiB") && t.includes("4.00 GiB") && t.includes("1 個 session、2 次審查"), t);
  button(s.node, "刪除這個流程…").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/delete")), "one click is a question");
  assert(text(s.node).includes("無法復原"));
  button(s.node, "取消").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/delete")));
  button(s.node, "刪除這個流程…").click();
  button(s.node, "確定").click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/delete"));
  assert(p && p.url.includes(FLOW), "the delete of this flow");
  assert.deepStrictEqual(p.body, { flow_id: FLOW });
  assert.strictEqual(gone, FLOW);
  s.stop();
});

test("a flow that cannot go is shown with the reasons and no delete button", async () => {
  reset({ storage: { ok: true, limit_bytes: 4294967296, used_bytes: 2000000000, problem: "", note: "n", flows: [
    { flow_id: FLOW, task_id: "task-1", bytes: 1000, sessions: 1, reviews: 0, has_data: true, held: true, deletable: false,
      reasons: ["串流 session l-1111111111111111 仍在執行"], note: "" },
    { flow_id: "flow-ffffffffffff", task_id: "t2", bytes: null, sessions: 0, reviews: 0, has_data: false, held: false,
      deletable: false, reasons: ["session l-x 的 manifest 無法讀取，無法判斷哪些資料屬於這個流程"], note: "" }] } });
  const s = app.mountStorage();
  await settle();
  const t = text(s.node);
  assert(t.includes("仍在執行") && t.includes("無法判斷哪些資料屬於這個流程") && t.includes("未知"));
  assert.strictEqual(s.node.findAll((n) => n.tag === "button" && n.textContent.includes("刪除這個流程")).length, 0);
  s.stop();
});

test("a nearly full quota says so; a flow's own page shows only that flow", async () => {
  reset({ storage: { ok: true, limit_bytes: 4294967296, used_bytes: 4200000000, problem: "", note: "n", flows: [
    { flow_id: FLOW, task_id: "task-1", bytes: 10, sessions: 1, reviews: 0, has_data: true, held: false, deletable: true, reasons: [], note: "" },
    { flow_id: "flow-ffffffffffff", task_id: "t2", bytes: 99, sessions: 1, reviews: 0, has_data: true, held: false, deletable: true, reasons: [], note: "" }] } });
  const all = app.mountStorage();
  await settle();
  assert(text(all.node).includes("快滿了"));
  assert.strictEqual(all.node.findAll((n) => n.tag === "li" && n.hasClass("s2-storage-item")).length, 2);
  const one = app.mountStorage({ onlyFlowId: FLOW });
  await settle();
  assert.strictEqual(one.node.findAll((n) => n.tag === "li" && n.hasClass("s2-storage-item")).length, 1);
  all.stop(); one.stop();
});

test("a refused deletion is said and the list is read again", async () => {
  reset();
  state.post["delete"] = [{ error: "不能刪除：串流 session l-1111111111111111 仍在執行", code: "not_deletable" }, 409];
  const s = app.mountStorage();
  await settle();
  const reads = FETCH_LOG.filter((x) => x.url.endsWith("/api/flows/storage")).length;
  button(s.node, "刪除這個流程…").click();
  button(s.node, "確定").click();
  await settle();
  assert(FETCH_LOG.filter((x) => x.url.endsWith("/api/flows/storage")).length > reads, "read again after the answer");
  s.stop();
});

test("a value set by a script without any event is caught before sending", async () => {
  for (const which of ["limit", "model", "review"]) {
    const d = openDialog({ preview: [preview()], confirm: [{ ok: true }] });
    await settle();
    const m = d.modal();
    const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
    tick.checked = true;
    tick.dispatch("change");
    if (which === "limit") m.findAll((n) => n.tag === "input" && n.dataset && n.dataset.limit)[3].value = "399";
    else if (which === "model") find(m, (n) => n.tag === "input" && n.getAttribute("list") === "s2-exec-models").value = "claude-opus-5-5";
    else find(m, (n) => n.tag === "select").value = "gpt-6.1-sol";      // value only: no input/change event
    const accept = button(m, "接受並記錄");
    assert(!accept.disabled, "the page has not noticed");
    accept.click();
    await settle();
    assert(!posts().some((x) => x.url.endsWith("/acceptance")), `${which}: nothing is sent`);
    assert(text(m).includes("畫面上的設定和這份預覽不一致"), which);
    assert(accept.disabled, `${which}: accept goes off until a new preview`);
    FETCH_LOG.length = 0;
  }
  // and the values as they were are sent, of course
  const d = openDialog({ preview: [preview()], confirm: [{ ok: true }] });
  await settle();
  const m = d.modal();
  const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
  tick.checked = true;
  tick.dispatch("change");
  button(m, "接受並記錄").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/acceptance")));
});

test("leaving the page cancels what is on its way", async () => {
  reset();
  const signals = [];
  setHandler((url, opts) => {
    signals.push(opts.signal);
    return new Promise(() => {});                    // never answers
  });
  const c = mountCoordinator(FLOW);
  await settle();
  assert(signals.length >= 4 && signals.every((x) => x && !x.aborted), "four reads on their way");
  c.stop();
  assert(signals.every((x) => x.aborted), "all of them are cancelled when the page is left");
  const s = app.mountStorage();
  await settle();
  const sig = signals[signals.length - 1];
  assert(!sig.aborted);
  s.stop();
  assert(sig.aborted, "the storage list too");
});

// ---- refresh rounds ----------------------------------------------------------------------------------------

function deferredExecutor() {
  const pending = [];
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    if ((opts.method || "GET") === "GET" && p.endsWith("/executor")) {
      return new Promise((resolve) => pending.push((data) => resolve(jsonResponse(data, true))));
    }
    if ((opts.method || "GET") === "GET" && p.endsWith("/reports")) return jsonResponse({ ok: true, reports: [], latest_dispatch_id: null }, true);
    if ((opts.method || "GET") === "GET" && p.endsWith("/reviews")) return jsonResponse({ ok: true, reviews: [] }, true);
    if ((opts.method || "GET") === "GET" && p.endsWith("/merge-gate")) return jsonResponse(gate(), true);
    return null;
  });
  return pending;
}

test("a tick that finds a round running is dropped; no requests pile up", async () => {
  FETCH_LOG.length = 0;
  const pending = deferredExecutor();
  const c = mountCoordinator(FLOW);
  await settle();
  assert.strictEqual(pending.length, 1, "the first round is waiting on a slow executor read");
  const n = FETCH_LOG.length;
  await c.tick();
  await c.tick();
  await c.refresh(false);
  assert.strictEqual(FETCH_LOG.length, n, "no new requests while a round is running");
  pending[0](executor());
  await settle();
  assert(text(byS2(c.node, "acceptance")).includes("風險已接受"));
  const next = c.tick();                             // the round is over: the next one runs
  await settle();
  assert.strictEqual(pending.length, 2);
  pending[1](executor());
  await next;
});

test("an action's refresh is not lost while a round is running, and it shows the newer state", async () => {
  FETCH_LOG.length = 0;
  const pending = deferredExecutor();
  const c = mountCoordinator(FLOW);
  await settle();
  const old = executor({ sessions: [liveSession({ status: { live: true, state: "idle", responses: 1, total_cost_usd: 0.01, dispatches: [] } })] });
  const fresh = executor({ sessions: [liveSession({ status: { live: true, state: "turn_running", responses: 9, total_cost_usd: 0.5, dispatches: [] } })] });
  c.refresh(true);                                   // an action finished while the first round is still waiting
  await settle();
  assert.strictEqual(pending.length, 1, "still one request: it is remembered, not sent");
  pending[0](old);                                   // the slow, older answer arrives
  await settle();
  assert.strictEqual(pending.length, 2, "and then the remembered round runs");
  pending[1](fresh);
  await settle();
  const t = text(byS2(c.node, "executor"));
  assert(t.includes("執行中") && !t.includes("閒置"), "the page ends on the newer state");
});

test("a stopped page applies nothing that arrives late", async () => {
  FETCH_LOG.length = 0;
  const pending = deferredExecutor();
  const c = mountCoordinator(FLOW);
  await settle();
  c.stop();
  pending[0](executor());
  await settle();
  assert.strictEqual(byS2(c.node, "acceptance"), null, "nothing was drawn");
});

test("each read has a time limit", async () => {
  reset();
  const seen = [];
  const inner = FETCH_LOG;                            // reset() installed the handler; wrap it to look at the options
  setHandler((url, opts) => {
    seen.push(!!opts.signal);
    const p = url.split("?")[0];
    if (p.endsWith("/executor")) return jsonResponse(executor(), true);
    if (p.endsWith("/reports")) return jsonResponse({ ok: true, reports: [], latest_dispatch_id: null }, true);
    if (p.endsWith("/reviews")) return jsonResponse({ ok: true, reviews: [] }, true);
    return jsonResponse(gate(), true);
  });
  const c = mountCoordinator(FLOW);
  await settle();
  assert(inner && seen.length >= 4 && seen.every(Boolean), "every GET carries an abort signal");
  c.stop();
});

test("an answer in a shape the page does not know is said, not a crash", async () => {
  reset();
  setHandler(() => null);                             // every read answers {ok: true}
  const c = mountCoordinator(FLOW);
  await settle();
  assert(text(c.node).includes("無法顯示伺服器的回應"));
  state.executor = executor();
  setHandler((url) => {
    const p = url.split("?")[0];
    if (p.endsWith("/executor")) return jsonResponse(executor(), true);
    if (p.endsWith("/reports")) return jsonResponse({ ok: true, reports: [], latest_dispatch_id: null }, true);
    if (p.endsWith("/reviews")) return jsonResponse({ ok: true, reviews: [] }, true);
    return jsonResponse(gate(), true);
  });
  await c.refresh(true);
  assert(text(byS2(c.node, "acceptance")).includes("風險已接受"), "and it recovers on the next round");
  c.stop();
});

// ---- run ------------------------------------------------------------------------------------------------------

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   - " + name); }
    catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack ? e.stack : e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
