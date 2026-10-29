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
    stream_support: { state: "verified", detected: "2.1.292", supported: ["2.1.292", "2.1.296"], message: "" },
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
let BASE_HANDLER = null;           // the handler reset() installed, for a test that answers a few more addresses
function reset(over = {}) {
  state = { executor: executor(), reports: { ok: true, reports: [], latest_dispatch_id: null }, reviews: { ok: true, reviews: [] },
    gate: gate(), preview: null, accept: null, post: {},
    automation: { ok: true, flow_id: FLOW, mode: "manual", approval_id: null, problem: null, since: null, approval: null,
      step: null },
    storage: { ok: true, limit_bytes: 4294967296, used_bytes: 1048576, problem: "", note: "只有沒有程序在執行的流程才能刪除。",
      flows: [{ flow_id: FLOW, task_id: "task-1", bytes: 1048576, sessions: 1, reviews: 2, has_data: true, held: false,
        deletable: true, reasons: [], note: "" }] }, ...over };
  FETCH_LOG.length = 0;
  setHandler(BASE_HANDLER = (url, opts) => {
    const p = url.split("?")[0];
    const post = (opts.method || "GET") === "POST";
    const answer = (v, st = 200) => jsonResponse(v, st < 400, st);
    if (!post) {
      if (p.endsWith("/executor")) return state.executorError ? answer({ error: state.executorError }, 500) : answer(state.executor);
      if (p.endsWith("/reports")) return answer(state.reports);
      if (p.endsWith("/reviews")) return answer(state.reviews);
      if (p.endsWith("/merge-gate")) return answer(state.gate);
      if (p.endsWith("/api/flows/storage")) return answer(state.storage);
      if (p.endsWith("/automation")) return answer(state.automation);
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

test("a Claude Code version without a verified stream mode is said before start: version, list, what can be done", async () => {
  const hostile = "<img src=x onerror=alert(1)>";
  const message = "Claude Code 2.1.400 的串流模式還沒有通過驗證。VBear 目前支援串流模式的版本：2.1.292、2.1.296。" +
    "處理方式：安裝其中一個支援的版本，或等 VBear 更新、支援 2.1.400。" + hostile;
  const c = await mount({ executor: executor({ can_start: false,
    stream_support: { state: "unverified", detected: "2.1.400", supported: ["2.1.292", "2.1.296"], message } }) });
  const panel = byS2(c.node, "executor");
  const t = text(panel);
  assert(t.includes("2.1.400"), "the detected version");
  assert(t.includes("2.1.292、2.1.296"), "the supported versions");
  assert(t.includes("處理方式：安裝其中一個支援的版本，或等 VBear 更新"), "what can be done");
  assert(t.includes("現在不能啟動：") && t.includes("串流模式還沒有通過驗證"), "and it is among the reasons start is off");
  assert(button(panel, "啟動執行者").disabled, "start is off before anything is pressed");
  assert(t.includes(hostile), "the server's text is data: it is there as text");
  assert.strictEqual(panel.findAll((n) => n.tag === "img").length, 0, "and it made no element");
  assert(!posts().some((x) => x.url.endsWith("/executor")), "nothing was started to learn this");
});

test("a Claude Code version that cannot be read is said as unknown, not as unverified", async () => {
  const c = await mount({ executor: executor({ can_start: false,
    stream_support: { state: "unknown", detected: null, supported: ["2.1.292"],
      message: "讀不到 Claude Code 的版本（找不到），無法確認串流模式是否已通過驗證" } }) });
  const t = text(byS2(c.node, "executor"));
  assert(t.includes("讀不到 Claude Code 的版本（找不到）"));
  assert(!t.includes("還沒有通過驗證。"), "it does not claim the version is unverified");
});

test("a verified version is shown quietly with the supported list", async () => {
  const c = await mount();
  const t = text(byS2(c.node, "executor"));
  assert(t.includes("Claude Code 2.1.292：串流模式已通過驗證"));
  assert(t.includes("2.1.292、2.1.296"));
  assert(!t.includes("處理方式"), "no remedy is offered when nothing is wrong");
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
  button(byS2(c.node, "executor"), "關閉執行者").click();
  await settle();
  button(byS2(c.node, "executor"), "確定").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/executor/close")), "the session was closed");
  assert(reads() > before, "the storage panel was read again after the close");
  c.stop();
});

test("a dispatch that was prepared and not sent can be sent from the session row, in manual mode only", async () => {
  const D = "d2d2d2d2-aaaa-4bbb-8ccc-0123456789ab";
  const withUnsent = (over = {}) => executor({ sessions: [liveSession({
    status: { live: true, state: "idle", responses: 0, total_cost_usd: 0, dispatches: [{ dispatch_id: D, status: "accepted" }], unsent: D } })], ...over });
  const c = await mount({ executor: withUnsent() });
  const panel = byS2(c.node, "executor");
  assert(/已準備好但還沒送出/.test(panel.textContent), "the row says there is an unsent dispatch");
  assert(/不能開啟自動執行/.test(panel.textContent), "and what it blocks");
  FETCH_LOG.length = 0;
  button(panel, "送出這則派工").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/dispatch-send")), "nothing is sent by the first press");
  button(byS2(c.node, "executor"), "確定").click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/dispatch-send"));
  assert(p, "the dispatch was sent");
  assert.deepStrictEqual(p.body, { launch_id: "l-" + "1".repeat(16), dispatch_id: D },
    "only the session and the dispatch id; the text is the server's");
  c.stop();
  // in automatic mode the runner owns dispatches: the notice is not an offer
  const a = await mount({ executor: withUnsent({ automation: { mode: "auto", approval_id: "auto-7", problem: null } }) });
  assert(!/送出這則派工/.test(byS2(a.node, "executor").textContent), "no manual send in automatic mode");
  a.stop();
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

test("an open stop question is not rebuilt away by the timer", async () => {
  const c = await mount();
  button(byS2(c.node, "executor"), "停止這個流程").click();
  await settle();
  assert(text(byS2(c.node, "executor")).includes("確定"), "the question is open");
  state.executor = executor({ accounting: { ...executor().accounting, elapsed_s: 9999, responses: 77 } });
  await c.tick();
  await settle();
  assert(text(byS2(c.node, "executor")).includes("確定"), "a quiet round did not take it away");
  button(byS2(c.node, "executor"), "取消").click();
  await settle();
  state.executor = executor({ accounting: { ...executor().accounting, elapsed_s: 10005 } });
  await c.tick();                                    // answered: rounds are rebuilt again
  await settle();
  assert(text(byS2(c.node, "executor")).includes("10005") || !text(byS2(c.node, "executor")).includes("確定"));
  c.stop();
});

test("a round already on its way does not take an open question away", async () => {
  FETCH_LOG.length = 0;
  const pending = deferredExecutor();
  const c = mountCoordinator(FLOW);
  await settle();
  pending[0](executor());                              // the first round arrives and draws the panels
  await settle();
  const next = c.refresh(false);                       // a quiet round goes out and waits
  await settle();
  button(byS2(c.node, "executor"), "停止這個流程").click();
  await settle();
  assert(text(byS2(c.node, "executor")).includes("確定"), "the question is open");
  pending[1](executor({ accounting: { ...executor().accounting, elapsed_s: 12345 } }));
  await next;
  await settle();
  assert(text(byS2(c.node, "executor")).includes("確定"), "the answer that came meanwhile did not remove it");
  c.stop();
});

test("a manual preview request that was on its way when the mode switched is dropped when it arrives", async () => {
  reset({ executor: executor({ sessions: [liveSession()] }) });
  let release;
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    if ((opts.method || "GET") === "POST" && p.endsWith("/dispatch-preview")) {
      return new Promise((resolve) => { release = () => resolve(jsonResponse({ ok: true, preview_id: "p".repeat(32),
        expires_at: 1791000300, dispatch_id: "x", launch_id: "l-" + "1".repeat(16), text: "手動的文字",
        text_sha256: "f".repeat(64), bytes: 9, rewritten: false, ready: true, not_ready_reason: "" }, true)); });
    }
    if (p.endsWith("/executor")) return jsonResponse(state.executor, true);
    if (p.endsWith("/automation")) return jsonResponse(state.automation, true);
    if (p.endsWith("/reports")) return jsonResponse(state.reports, true);
    if (p.endsWith("/reviews")) return jsonResponse(state.reviews, true);
    if (p.endsWith("/merge-gate")) return jsonResponse(state.gate, true);
    if (p.endsWith("/api/flows/storage")) return jsonResponse(state.storage, true);
    return null;
  });
  const c = mountCoordinator(FLOW);
  await settle();
  find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea").value = "手動的文字";
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  assert(release, "the request is out");
  state.executor = executor({ sessions: [liveSession()], automation: { mode: "auto", approval_id: "auto-7", problem: null } });
  state.automation = { ok: true, flow_id: FLOW, mode: "auto", approval_id: "auto-7", problem: null, since: 1, approval: null,
    step: { step: "first_dispatch", label: "x", after: "y", held: false, hold_reason: "", awaiting_merge: false } };
  await c.refresh(true);                                // the page now knows: automatic
  release();                                            // and the late answer arrives
  await settle();
  const d = byS2(c.node, "dispatch");
  assert(!button(d, "核准並送出"), "no approve button appears");
  assert(find(d, (n) => n.tag === "textarea").disabled, "the controls stay off");
  assert(button(d, "預覽").disabled);
  c.stop();
});

test("the executor panel's stop says when its event could not be written", async () => {
  const c = await mount();
  state.post.hold = [{ ok: true, event_written: false, event_problem: "流程已停止，但「停止」事件無法寫入時間軸（x）" }];
  button(byS2(c.node, "executor"), "停止這個流程").click();
  button(byS2(c.node, "executor"), "確定").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/hold")));
  const toastNode = global.document.getElementById("toast");
  assert(toastNode && String(toastNode.textContent).includes("無法寫入時間軸"), "the answer's problem is shown, not 已停止");
  c.stop();
});

test("a manual preview made before the switch to automatic mode is cleared", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  state.post["dispatch-preview"] = [{ ok: true, preview_id: "p".repeat(32), expires_at: 1791000300, dispatch_id: "x",
    launch_id: "l-" + "1".repeat(16), text: "手動的文字", text_sha256: "f".repeat(64), bytes: 9, rewritten: false,
    ready: true, not_ready_reason: "" }];
  find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea").value = "手動的文字";
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  assert(button(byS2(c.node, "dispatch"), "核准並送出"), "a preview is on screen");
  state.executor = executor({ sessions: [liveSession()], automation: { mode: "auto", approval_id: "auto-7", problem: null } });
  state.automation = { ok: true, flow_id: FLOW, mode: "auto", approval_id: "auto-7", problem: null, since: 1, approval: null,
    step: { step: "first_dispatch", label: "x", after: "y", held: false, hold_reason: "", awaiting_merge: false } };
  await c.refresh(true);
  assert(!button(byS2(c.node, "dispatch"), "核准並送出"), "it cannot be approved any more");
  assert(text(byS2(c.node, "dispatch")).includes("手動派工一律拒絕"));
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
  assert(text(rp).includes("較早的回報，不再核對目前的版本"));
});

test("a refused tool call is shown by count and name, as text, and does not change the turn's verdict", async () => {
  const hostile = "<img src=x onerror=alert(1)>";
  const c = await mount({ reports: { ok: true, latest_dispatch_id: "d", reports: [
    reportEntry({ denials: { count: 3, items: [{ tool_name: "Bash", reason_type: "mode" }, { tool_name: hostile, reason_type: "rule" }] } }),
    reportEntry({ latest: false, usable: false, checks: null, dispatch_id: "e0e0e0e0-aaaa-4bbb-8ccc-0123456789ab" })] } });
  const rp = byS2(c.node, "reports");
  const t = text(rp);
  assert(t.includes("這一輪有 3 次工具呼叫被權限系統擋下"));
  const capped = await mount({ reports: { ok: true, latest_dispatch_id: "d", reports: [
    reportEntry({ denials: { count: 16, at_least: true, items: [{ tool_name: "Bash", reason_type: "mode" }] } })] } });
  assert(text(byS2(capped.node, "reports")).includes("這一輪有至少 16 次工具呼叫被權限系統擋下"), "at the limit it says at least");
  assert(t.includes("Bash／mode"));
  assert(t.includes(hostile), "the name is data: it is there as text");
  assert.strictEqual(rp.findAll((n) => n.tag === "img").length, 0, "and it made no element");
  assert(t.includes("有效回合"), "the turn is still a valid turn");
  assert.strictEqual((t.match(/次工具呼叫被權限系統擋下/g) || []).length, 1, "only the turn that had one says so");
});

test("an order that cannot be told is said, and no report is called the latest", async () => {
  const c = await mount({ executor: executor({ sessions_order_problem: "有兩個 session 的建立時間相同，無法判斷哪一個是最新的" }),
    reports: { ok: true, latest_dispatch_id: null, order_problem: "有兩個 session 的建立時間相同，無法判斷哪一個是最新的",
      reports: [reportEntry({ latest: false, usable: false, checks: null })] } });
  assert(text(byS2(c.node, "executor")).includes("無法判斷執行階段的先後"));
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

test("a review's usage is shown in tokens from the record: complete, partial, and not had (never 0, never a price)", async () => {
  const hostile = "<img src=x onerror=alert(1)>";
  const counts = { input_tokens: 1234567, cached_input_tokens: 1000, cache_write_input_tokens: 0, output_tokens: 456,
    reasoning_output_tokens: 120, total_tokens: 1235023 };
  const c = await mount({ reviews: { ok: true, usage_note: "用量是 Codex 的 rollout 記下的 token 數，VBear 沒有可靠的價格來源，所以不換算成金額；「無法取得」不等於 0。",
    reviews: [
      reviewEntry({ job_id: "r-" + "a".repeat(16), round: 3, usage: { state: "complete", counts, reason: "" } }),
      reviewEntry({ job_id: "r-" + "b".repeat(16), round: 2, usage: { state: "partial", counts: { input_tokens: 90, output_tokens: 5 },
        reason: "審查沒有跑完：這是 rollout 已記下的部分，實際用量不會比這少" } }),
      reviewEntry({ job_id: "r-" + "c".repeat(16), round: 1, usage: { state: "unavailable", counts: null,
        reason: "這份審查紀錄是在 VBear 開始記錄用量之前寫的" + hostile } })] } });
  const panel = byS2(c.node, "reviews");
  const usage = panel.findAll((n) => n.dataset && n.dataset.s2 === "review-usage" || (n._attrs && n._attrs["data-s2"] === "review-usage"));
  const lines = usage.map((n) => text(n));
  assert.strictEqual(lines.length, 3, "one line per review: " + JSON.stringify(lines));
  const [none, part, done] = lines;                 // the panel reverses the order it is given: round 1 comes first
  assert(done.includes("輸入 1,234,567") && done.includes("輸出 456") && done.includes("合計 1,235,023"), done);
  assert(done.includes("其中快取讀取 1,000") && done.includes("其中推理 120"), done);
  assert(part.includes("至少") && part.includes("輸入 90") && part.includes("不會比這少"), part);
  assert(none.includes("無法取得") && !/輸入 0|合計 0/.test(none), "not had is not 0: " + none);
  assert(none.includes(hostile), "the reason is data: text");
  assert.strictEqual(panel.findAll((n) => n.tag === "img").length, 0);
  const t = text(panel);
  assert(t.includes("不換算成金額"), "says why there is no price");
  assert(!/USD|\$/.test(done + part + none), "no money");
});

test("a review that has no usage field yet (still running) shows no usage line", async () => {
  const c = await mount({ reviews: { ok: true, reviews: [reviewEntry({ state: "running", outcome: null, usage: null, result: null, report: null })] } });
  const t = text(byS2(c.node, "reviews"));
  assert(!t.includes("用量"), t);
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
  assert(t.includes("就是被審的版本"));
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

test("an unverified Claude Code version refused at the preview is shown as the server wrote it, as text", async () => {
  const hostile = "<img src=x onerror=alert(1)>";
  const message = "Claude Code 2.1.400 的串流模式還沒有通過驗證。VBear 目前支援串流模式的版本：2.1.292、2.1.296。" +
    "處理方式：安裝其中一個支援的版本，或等 VBear 更新、支援 2.1.400。" + hostile;
  const d = openDialog({ preview: [{ error: message, code: "claude_unverified" }, 409] });
  await settle();
  const m = d.modal();
  const t = text(m);
  assert(t.includes("2.1.400") && t.includes("2.1.292、2.1.296") && t.includes("處理方式"));
  assert(t.includes(hostile));
  assert.strictEqual(m.findAll((n) => n.tag === "img").length, 0);
  assert(button(m, "接受並記錄").disabled, "nothing can be accepted");
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

// ---- automatic mode (S3-5) ---------------------------------------------------------------------------------

const autoPreview = () => preview({
  plan_text: "任務：實作 add()\n目標：完成 add 函式", plan_sha256: "d".repeat(64), plan_bytes: 31,
  auto_text: {
    zh: { version: "2026-10-11.1", title: "核准計畫並開啟自動執行", intro: "核准這份計畫之後，VBear 會自動進行。",
      confirm: "我核准這份計畫，了解並接受自動執行的風險與以上全部殘餘風險",
      sections: ["does", "limits", "accounts", "not_auto", "forwarding", "git_writable", "stop", "residual"].map((id) => ({
        id, title: `區段 ${id}`, body: `內文 ${id}` })) },
    en: { version: "2026-10-11.1", sections: [{ id: "does", title: "What it does", body: "English" }] } },
  fixed_rules: ["連續失敗 1 次就停止（不能調整）"],
});

test("the approval dialog shows the plan, every automatic-mode part, the fixed rule and the same S2 risks", async () => {
  reset();
  state.post["automation-preview"] = [autoPreview()];
  state.post.automation = [{ ok: true, mode: "auto", approval_id: "auto-9" }];
  let done = 0;
  app.openAcceptanceDialog(FLOW, () => { done += 1; }, { auto: true });
  await settle();
  const m = dom().bodyEl.children[dom().bodyEl.children.length - 1];
  const t = text(m);
  assert(posts().some((x) => x.url.endsWith("/automation-preview")), "its own preview route");
  assert(!posts().some((x) => x.url.endsWith("/acceptance-preview")));
  assert(t.includes("核准計畫並開啟自動執行") && t.includes("任務：實作 add()") && t.includes("雜湊（sha256）前 16 碼 dddddddddddddddd"));
  for (const id of ["does", "limits", "accounts", "not_auto", "forwarding", "git_writable", "stop", "residual"]) {
    assert(t.includes(`內文 ${id}`), id);
  }
  assert(t.includes("連續失敗 1 次就停止（不能調整）"));
  for (const s of ["第一項的全文。", "第二項的全文，512 MiB。", "第三項的全文。"]) assert(t.includes(s), s);
  assert(t.includes("a1b2c3d4e5f60718") && t.includes("0f1e2d3c4b5a6978"), "both account prefixes");
  assert.strictEqual(m.findAll((n) => n.tag === "input" && n.dataset && n.dataset.limit).length, 9);
  const accept = button(m, "核准並開啟自動執行");
  assert(accept.disabled, "off until the tick");
  const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
  tick.checked = true;
  tick.dispatch("change");
  assert(!accept.disabled);
  accept.click();
  await settle();
  const p = posts().find((x) => x.url.endsWith("/automation"));
  assert(p, "confirmed");
  assert.deepStrictEqual(p.body, { preview_id: "a".repeat(32) }, "only the preview id");
  assert.strictEqual(done, 1);
});

test("the approval dialog voids its preview when a limit changes, as the S2 one does", async () => {
  reset();
  state.post["automation-preview"] = [autoPreview()];
  app.openAcceptanceDialog(FLOW, () => {}, { auto: true });
  await settle();
  const m = dom().bodyEl.children[dom().bodyEl.children.length - 1];
  const tick = find(m, (n) => n.tag === "input" && n.getAttribute("type") === "checkbox");
  tick.checked = true;
  tick.dispatch("change");
  const i = m.findAll((n) => n.tag === "input" && n.dataset && n.dataset.limit)[0];
  i.value = "2";
  i.dispatch("input");
  assert(button(m, "核准並開啟自動執行").disabled);
  assert(text(m).includes("設定已變更"));
  button(m, "核准並開啟自動執行").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/automation")));
});

test("a manual flow offers the approval; an automatic one shows its step, the stop and (when stopped) the way back", async () => {
  let c = await mount();
  const manual = byS2(c.node, "automation");
  assert(text(manual).includes("手動"));
  assert(button(manual, "核准計畫並開啟自動執行…"));
  c.stop();
  const auto = { ok: true, flow_id: FLOW, mode: "auto", approval_id: "auto-7", problem: null, since: 1791000000,
    approval: { seq: 7, at: 1791000000, auto_text_version: "2026-10-11.1", plan_sha256: "e".repeat(64), plan_bytes: 31,
      limits: {} },
    step: { step: "await_review", label: "等 Codex 審查結束", after: "有效的結論才會被採用", held: false, hold_reason: "",
      awaiting_merge: false } };
  c = await mount({ automation: auto, executor: executor({ automation: { mode: "auto", approval_id: "auto-7", problem: null } }) });
  let panel = byS2(c.node, "automation");
  let t = text(panel);
  assert(t.includes("自動執行中") && t.includes("等 Codex 審查結束") && t.includes("有效的結論才會被採用"));
  assert(t.includes("eeeeeeeeeeeeeeee") && t.includes("auto-7"));
  assert(!button(panel, "切回手動"), "not while it runs");
  button(panel, "停止流程").click();
  await settle();
  assert(!posts().some((x) => x.url.endsWith("/hold")), "a question first");
  button(byS2(c.node, "automation"), "確定").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/hold")));
  c.stop();
  state.automation = { ...auto, step: { ...auto.step, held: true, hold_reason: "自動執行停止：tests failed" } };
  c = await mount({ automation: state.automation, executor: executor({ automation: { mode: "auto", approval_id: "auto-7", problem: null } }) });
  panel = byS2(c.node, "automation");
  t = text(panel);
  assert(t.includes("自動（已停止）") && t.includes("自動執行停止：tests failed") && t.includes("不會自動恢復"));
  button(panel, "切回手動").click();
  await settle();
  assert(posts().some((x) => x.url.endsWith("/automation/disable")));
  c.stop();
});

test("in automatic mode the manual dispatch box, review start and manual acceptance are off and say why", async () => {
  const auto = { ok: true, flow_id: FLOW, mode: "auto", approval_id: "auto-7", problem: null, since: 1, approval: null,
    step: { step: "first_dispatch", label: "x", after: "y", held: false, hold_reason: "", awaiting_merge: false } };
  const c = await mount({ automation: auto, executor: executor({ sessions: [liveSession()],
    automation: { mode: "auto", approval_id: "auto-7", problem: null } }),
    reports: { ok: true, latest_dispatch_id: "d", reports: [reportEntry()] } });
  const dispatch = byS2(c.node, "dispatch");
  assert(text(dispatch).includes("手動派工一律拒絕"));
  assert(find(dispatch, (n) => n.tag === "textarea").disabled);
  assert(button(dispatch, "預覽").disabled);
  const rv = byS2(c.node, "reviews");
  assert(button(rv, "請 Codex 審查最新回報").disabled);
  assert(text(rv).includes("自動執行中，手動審查一律拒絕"));
  assert(button(byS2(c.node, "acceptance"), "重新接受…").disabled);
  c.stop();
});

test("what an automatic event says is shown from its fixed fields", () => {
  const e = (o) => app.flowAutomationDetail(o).join(" | ");
  assert(e({ kind: "automation_mode", mode: "auto", approval_seq: 7 }).includes("auto-7"));
  assert(e({ kind: "automation_mode", mode: "manual", approval_seq: null }).includes("切回手動"));
  assert(e({ kind: "auto_dispatch_intent", dispatch_id: "0b1c2d3e-0000", length: 12, text_sha256: "a".repeat(64) }).includes("12 位元組"));
  const report = e({ kind: "auto_report", dispatch_id: "0b1c2d3e-0000", commit: "b".repeat(40), status: "done",
    tests_result: "passed" });
  assert(report.includes("執行者自述：狀態 done、測試 passed"), "the status and the tests are the executor's words");
  assert(report.includes("VBear 讀檔核對：回報的版本等於工作目錄目前的版本"), "the checks are VBear's own");
  assert(!report.includes("VBear 讀檔核對通過"), "no claim that the executor's fields were read by VBear");
  assert(e({ kind: "auto_review_result", round: 2, commit: "c".repeat(40), verdict: "NEEDS WORK" }).includes("第 2 輪結論：NEEDS WORK"));
  assert(e({ kind: "auto_review_aborted", round: 1, job_id: "r-" + "1".repeat(16) }).includes("該輪無效"));
  const stop = e({ kind: "auto_stopped", reason_code: "tests_not_passed", detail: "測試結果是 failed" });
  assert(stop.includes("tests_not_passed") && stop.includes("測試結果是 failed"));
  assert.deepStrictEqual(app.flowAutomationDetail({ kind: "note" }), []);
});

// ---- storage and deleting a flow (S2c-5) ---------------------------------------------------------------------

test("storage shows size and counts, and deleting takes two steps and names the flow", async () => {
  reset();
  let gone = null;
  const s = app.mountStorage({ afterDelete: (id) => { gone = id; } });
  await settle();
  const t = text(s.node);
  assert(t.includes("1.0 MiB") && t.includes("4.00 GiB") && t.includes("1 個執行階段、2 次審查"), t);
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

// ---- G4: gates, team and the bars of 體力 (design game-ui 4.5, v1.1 #7) --------------------------------------------

function flowFixture(phaseKey, over = {}) {
  const role = (name, family, extra = {}) => ({ name, family, family_label: { anthropic: "Anthropic（Claude）", openai: "OpenAI（Codex）",
    unknown: "不明" }[family] || family, ...extra });
  return { id: FLOW, phase: { key: phaseKey, label: { planning: "計畫中", awaiting_approval: "等核准", implementing: "實作中",
      in_review: "審查第 2 輪", needs_fix: "等修正", awaiting_merge: "審查通過・等合併", review_stale: "審查結果已過期",
      review_unverified: "審查通過・無法核對 HEAD", awaiting_push: "等 push", done: "完成" }[phaseKey] || "？", reason: "" },
    attention: ["awaiting_approval", "awaiting_merge", "awaiting_push"].includes(phaseKey),
    roles: { planner: role("規劃 <img src=x onerror=alert(1)>", "anthropic"),
      executor: role("Claude Code", "anthropic", { model: "haiku", workdir: "/work", session_id: "n-0123456789ab" }),
      reviewers: [{ ...role("Codex", "openai", { model: "gpt-6-luna" }), independent_of_executor: { counted: true, why: "" } },
        { ...role("另一個 Claude", "anthropic"), independent_of_executor: { counted: false, why: "審查者與執行者同為 Anthropic（Claude），不算獨立審查，不算通過" } }] },
    ...over };
}

test("the gates follow the phase: 已過, 目前 with the phase's own words, 未到", () => {
  const cases = { planning: 0, awaiting_approval: 1, implementing: 2, in_review: 3, needs_fix: 3, review_stale: 3,
    review_unverified: 4, awaiting_merge: 4, awaiting_push: 5, done: 6 };
  for (const [key, at] of Object.entries(cases)) {
    const grid = app.flowGateGrid(flowFixture(key));
    const cells = grid.findAll((n) => n.getAttribute && n.getAttribute("data-gate") !== null);
    assert.strictEqual(cells.length, 7, key);
    cells.forEach((c, i) => {
      const want = i < at ? "past" : i === at ? "now" : "next";
      assert.strictEqual(c.getAttribute("data-state"), want, `${key} gate ${i}`);
      const words = text(c);
      assert(words.includes(want === "past" ? "已過" : want === "next" ? "未到" : "目前："), `${key} gate ${i}: ${words}`);
    });
  }
  const now = app.flowGateGrid(flowFixture("needs_fix")).find((n) => n.getAttribute && n.getAttribute("data-state") === "now");
  assert(text(now).includes("目前：等修正"), "the phase's own label is the words of the current gate");
  assert(text(app.flowGateGrid(flowFixture("awaiting_merge"))).includes("等你處理"), "a gate waiting for you says so");
});

test("a phase the gates do not know is not drawn as a gate", () => {
  const grid = app.flowGateGrid(flowFixture("something_new"));
  assert.strictEqual(grid.findAll((n) => n.getAttribute && n.getAttribute("data-gate") !== null).length, 0);
  assert(text(grid).includes("無法對應到關卡"));
});

test("the team: the planner is only a record, each member has name, family and model, reviewers say if they count", () => {
  const team = app.flowTeamSection(flowFixture("in_review"), { label: "執行中", reason: "即時狀態 3 秒前" });
  const t = text(team);
  assert(t.includes("規劃者（只是記錄，VBear 不會啟動）") && t.includes("沒有狀態：只是記錄"));
  assert(t.includes("執行者") && t.includes("執行中：即時狀態 3 秒前") && t.includes("/work") && t.includes("n-0123456789ab"));
  assert(t.includes("審查者 1") && t.includes("審查者 2"));
  assert(t.includes("不同家族，可算獨立審查"));
  assert(t.includes("不算獨立審查：審查者與執行者同為 Anthropic（Claude）"));
  assert(t.includes("OpenAI（Codex）") && t.includes("gpt-6-luna"));
  // a field that was not given reads 未提供 (the other reviewer has no model)
  assert(t.includes("未提供"));
  // the name is a free-typed name, not a tool; the record has no tool field and the card says so
  assert(!t.includes("名稱（工具）"));
  assert(t.includes("名稱") && t.includes("工具未提供（流程記錄沒有這個欄位）"), t);
  // text only: the hostile name is shown as text and builds no element
  assert(t.includes("<img src=x onerror=alert(1)>"));
  assert.strictEqual(team.findAll((n) => n.tag === "img").length, 0);
  const missing = app.flowTeamSection(flowFixture("planning", { roles: { planner: { name: "p", family: "unknown", family_label: "不明" },
    executor: { name: "e", family: "unknown", family_label: "不明" }, reviewers: [{ name: "r", family: "unknown", family_label: "不明" }] } }),
    { label: "狀態未知", reason: "" });
  assert(text(missing).includes("未提供"), "no independence data reads 未提供, not 'independent'");
  assert(!text(missing).includes("可算獨立審查"));
});

test("the limits are bars with the words; what cannot be counted is not drawn as 0", async () => {
  const ex = executor();
  ex.accounting.spent_usd = 7.62; ex.accounting.recorded_usd = 0.12; ex.accounting.unsettled_usd = 7.5;
  const c = await mount({ executor: ex });
  const panel = byS2(c.node, "executor");
  const bars = panel.findAll((n) => n.tag === "progress");
  assert(bars.length >= 5, `a bar for dispatches, responses, cost, reviews and time (got ${bars.length})`);
  const cost = bars.find((b) => (b.getAttribute("aria-label") || "").startsWith("執行者費用"));
  assert.strictEqual(cost.getAttribute("max"), "20");
  assert.strictEqual(cost.getAttribute("value"), "7.62");
  const words = text(panel);
  assert(words.includes("已記錄的花費 USD 0.12（Claude Code 自己回報）"), words);
  assert(words.includes("未結算 USD 7.50（未完成的回合按額度上限計入用量）"));
  assert(words.includes("實際費用尚未知"));
  // the figures are shown to the cent whatever the float digits are (22.3 as 22.299999999999997)
  const fl = await mount({ executor: executor({ accounting: { ...executor().accounting, spent_usd: 22.299999999999997,
    recorded_usd: 22, unsettled_usd: 0.2999999999999972 } }) });
  const flWords = text(byS2(fl.node, "executor"));
  assert(flWords.includes("22.30 USD") && flWords.includes("已記錄的花費 USD 22.00") && flWords.includes("未結算 USD 0.30"), flWords);
  assert(!flWords.includes("22.2999") && !flWords.includes("0.2999"), "no float digits past the cent: " + flWords);
  // a difference that is only float dust is not an unsettled turn
  const dust = await mount({ executor: executor({ accounting: { ...executor().accounting, recorded_usd: 0.3, unsettled_usd: 5e-17 } }) });
  assert(text(byS2(dust.node, "executor")).includes("沒有未結算的回合"));
  // nothing unsettled
  const ok = await mount({ executor: executor({ accounting: { ...executor().accounting, recorded_usd: 0.12, unsettled_usd: 0 } }) });
  assert(text(byS2(ok.node, "executor")).includes("沒有未結算的回合"));
  // an older answer without the split: it is said, nothing is invented
  const old = await mount({ executor: executor() });
  const oldWords = text(byS2(old.node, "executor"));
  assert(oldWords.includes("已記錄的花費：無法核算") && oldWords.includes("未結算：無法核算"));
  // an unknown limit: no bar, and it says it cannot be counted
  const none = await mount({ executor: executor({ accounting: { ...executor().accounting, responses: null } }) });
  const noneWords = text(byS2(none.node, "executor"));
  assert(noneWords.includes("無法核算"));
  const noneBars = byS2(none.node, "executor").findAll((n) => n.tag === "progress");
  assert(!noneBars.some((b) => (b.getAttribute("aria-label") || "").startsWith("執行者模型回應")), "no bar for an unknown value");
  // a time limit that is not a positive number: no bar, 無法核算 (like every other meter)
  const zero = await mount({ executor: executor({ accounting: { ...executor().accounting,
    limits: { ...executor().accounting.limits, max_elapsed_h: 0 } } }) });
  const zeroPanel = byS2(zero.node, "executor");
  assert(!zeroPanel.findAll((n) => n.tag === "progress").some((b) => (b.getAttribute("aria-label") || "").startsWith("經過時間")));
  assert(text(zeroPanel).includes("經過時間") && text(zeroPanel).includes("無法核算"));
  // the time has not started: no bar, 尚未開始
  const fresh = await mount({ executor: executor({ accounting: { ...executor().accounting, elapsed_s: null } }) });
  const freshPanel = byS2(fresh.node, "executor");
  assert(text(freshPanel).includes("尚未開始"));
  assert(!freshPanel.findAll((n) => n.tag === "progress").some((b) => (b.getAttribute("aria-label") || "").startsWith("經過時間")));
});

// ---- P34-3: the executor card's instructions in the dispatch box and in the approval --------------------------------------

const CARD = "prof-aaaaaaaaaaaa";
// the flow page, then the card's instructions, as the server answers them
function cardHandler(roleCard, ins) {
  const base = BASE_HANDLER;
  setHandler((url, opts) => {
    const p = url.split("?")[0];
    if ((opts.method || "GET") === "GET" && p.endsWith(`/api/flows/${FLOW}`)) {
      return jsonResponse({ ok: true, flow: { id: FLOW, roles: { planner: { name: "p", family: "anthropic" },
        executor: roleCard ? { name: "e", family: "anthropic", profile_id: CARD, profile_snapshot: { name: "全端工程師", tool: "claude", model_id: "", revision: "r".repeat(64) } }
          : { name: "e", family: "anthropic" }, reviewers: [] } } }, true);
    }
    if ((opts.method || "GET") === "GET" && p.endsWith(`/api/agent-profiles/${CARD}/instructions`)) return jsonResponse(ins, true);
    return base ? base(url, opts) : null;
  });
}
const toastText = () => { const t = global.document.getElementById("toast"); return t ? String(t.textContent) : ""; };

test("P34-3 dispatch box: 加上職位指示 puts the executor card's instructions first in the box and sends nothing", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  cardHandler(true, { ok: true, id: CARD, name: "全端工程師", source: "default", position: "executor", text: "先寫測試。<b>x</b>" });
  const box = find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea");
  box.value = "請做 add()";
  const btn = button(byS2(c.node, "dispatch"), "加上職位指示");
  assert(btn && !btn.disabled, "the button is there");
  FETCH_LOG.length = 0;
  btn.click();
  await settle();
  assert.strictEqual(box.value, "職位指示（來自角色卡「全端工程師」）：\n先寫測試。<b>x</b>\n\n請做 add()");
  assert(!posts().length, "filling the box sends nothing; the preview and the approval are the dispatch's own");
  assert.strictEqual(byS2(c.node, "dispatch").findAll((n) => n.tag === "b").length, 0, "text, not markup");
  // a second press does not add it twice
  btn.click();
  await settle();
  assert.strictEqual(box.value, "職位指示（來自角色卡「全端工程師」）：\n先寫測試。<b>x</b>\n\n請做 add()");
  assert(toastText().includes("已經加上"), toastText());
  // the preview that follows is the dispatch's own, with the box as it is
  state.post["dispatch-preview"] = [{ ok: true, preview_id: "p".repeat(32), expires_at: 1791000300, dispatch_id: "x",
    launch_id: "l-" + "1".repeat(16), text: box.value, text_sha256: "f".repeat(64), bytes: 9, rewritten: false, ready: true, not_ready_reason: "" }];
  button(byS2(c.node, "dispatch"), "預覽").click();
  await settle();
  const pre = posts().find((x) => x.url.endsWith("/dispatch-preview"));
  assert.strictEqual(pre.body.text, box.value);
  c.stop();
});

test("P34-3 dispatch box: no card on the executor, or a card with no instructions, says so and leaves the box alone", async () => {
  let c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  cardHandler(false, null);
  let box = find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea");
  box.value = "原本的";
  button(byS2(c.node, "dispatch"), "加上職位指示").click();
  await settle();
  assert.strictEqual(box.value, "原本的");
  assert(toastText().includes("沒有放角色卡"), toastText());
  c.stop();
  c = await mount({ executor: executor({ sessions: [liveSession()] }) });
  cardHandler(true, { ok: true, id: CARD, name: "全端工程師", source: "none", position: null, text: null });
  box = find(byS2(c.node, "dispatch"), (n) => n.tag === "textarea");
  box.value = "原本的";
  button(byS2(c.node, "dispatch"), "加上職位指示").click();
  await settle();
  assert.strictEqual(box.value, "原本的");
  assert(toastText().includes("沒有職位指示"), toastText());
  c.stop();
});

test("P34-3 dispatch box: in automatic mode the button is off with the rest of the box", async () => {
  const c = await mount({ executor: executor({ sessions: [liveSession()], automation: { mode: "auto", approval_id: "auto-7", problem: null } }) });
  assert(button(byS2(c.node, "dispatch"), "加上職位指示").disabled);
  c.stop();
});

test("P34-3 approval: the dialog says which card's instructions open the plan, from where, and that only the first dispatch carries them", async () => {
  reset();
  state.post["automation-preview"] = [{ ...autoPreview(), plan_text: "職位指示（來自角色卡「全端工程師」）：\n先寫測試。\n\n任務：實作 add()",
    instructions: { included: true, profile_id: CARD, name: "全端工程師", source: "default", position: "executor", length: 5, changed_since_placed: true, reason: "" } }];
  app.openAcceptanceDialog(FLOW, () => {}, { auto: true });
  await settle();
  const m = dom().bodyEl.children[dom().bodyEl.children.length - 1];
  const note = find(m, (n) => n.getAttribute && n.getAttribute("data-s2-auto-instructions") === "included");
  assert(note, "a note about the instructions is on the approval");
  const t = text(note);
  assert(t.includes("全端工程師") && t.includes("預設（跟著職位）") && t.includes("5 字"), t);
  assert(t.includes("第一則派工") && t.includes("使用者訊息") && t.includes("不是系統提示"), t);
  assert(t.includes("改過") && t.includes("現在的內容"), "the card changed since it was placed, and it says so");
  assert(text(m).includes("職位指示（來自角色卡「全端工程師」）：\n先寫測試。"), "and the text itself is in the plan above");
});

test("P34-3 approval: a card that could not be read says why nothing was added; a flow with no card says nothing", async () => {
  reset();
  state.post["automation-preview"] = [{ ...autoPreview(), instructions: { included: false, profile_id: CARD, name: "全端工程師", source: null,
    position: null, length: 0, changed_since_placed: false, reason: "找不到這個位置上的角色卡（可能已刪除），所以這份計畫沒有帶職位指示" } }];
  app.openAcceptanceDialog(FLOW, () => {}, { auto: true });
  await settle();
  let m = dom().bodyEl.children[dom().bodyEl.children.length - 1];
  const note = find(m, (n) => n.getAttribute && n.getAttribute("data-s2-auto-instructions") === "none");
  assert(note && text(note).includes("找不到這個位置上的角色卡"), "the server's reason");
  m.remove && m.remove();
  reset();
  state.post["automation-preview"] = [{ ...autoPreview(), instructions: null }];
  app.openAcceptanceDialog(FLOW, () => {}, { auto: true });
  await settle();
  m = dom().bodyEl.children[dom().bodyEl.children.length - 1];
  assert(!find(m, (n) => n.getAttribute && n.getAttribute("data-s2-auto-instructions")), "no card, no note");
  const old = { ...autoPreview() };
  delete old.instructions;
  reset();
  state.post["automation-preview"] = [old];
  app.openAcceptanceDialog(FLOW, () => {}, { auto: true });
  await settle();
  m = dom().bodyEl.children[dom().bodyEl.children.length - 1];
  assert(!find(m, (n) => n.getAttribute && n.getAttribute("data-s2-auto-instructions")), "an older server's preview has none either");
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
