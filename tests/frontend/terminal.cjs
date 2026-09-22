// Tests the terminal frontend components, streaming SSE parser, UTF-8/base64 decoding,
// input batching/gating/no-replay, takeover warning, release, cleanup, reconnect policy,
// initialization gate, and race condition handling.
// Run: node tests/frontend/terminal.cjs   (exit code 0 = pass)
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const appSource = fs.readFileSync(path.join(__dirname, "..", "..", "web", "app.js"), "utf8");

// Minimal synthetic DOM globals required when app.js evaluates top-level in Node
class SyntheticNode {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; }
  append() {}
  replaceChildren() {}
  setAttribute() {}
  removeAttribute() {}
  addEventListener() {}
  removeEventListener() {}
  focus() {}
  scrollIntoView() {}
}
global.Node = SyntheticNode;
global.fetch = async () => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: async () => ({ skills: [], roles: [], sessions: [], usage: { sessions: [] } }),
});
global.document = {
  createElement: (tag) => new SyntheticNode(tag),
  createTextNode: (text) => Object.assign(new SyntheticNode("#text"), { textContent: text }),
  getElementById: (id) => new SyntheticNode(id),
  querySelectorAll: () => [],
  querySelector: () => new SyntheticNode(""),
  documentElement: { setAttribute: () => {}, removeAttribute: () => {} },
  addEventListener: () => {},
};
global.window = {
  addEventListener: () => {},
  removeEventListener: () => {},
  scrollTo: () => {},
};
global.location = { hash: "", pathname: "/", search: "" };
global.history = { replaceState: () => {} };
global.localStorage = { getItem: () => null, setItem: () => {} };

let app;
try {
  app = require("../../web/app.js");
} catch (e) {
  assert.fail("Failed to load web/app.js: " + e.stack);
}

const {
  base64ToUint8Array,
  createSSEParser,
  createInputBatcher,
  createReconnectPolicy,
  handleTakeoverResponse,
  handleReleaseAction,
  handleTerminalFrame,
  initTerminalInstance,
  usableTermDims,
  termDimsForRequest,
  canStartTerminalStream,
  shouldShowTerminalRetryAction,
  parseHash,
} = app;

assert.strictEqual(typeof base64ToUint8Array, "function");
assert.strictEqual(typeof createSSEParser, "function");
assert.strictEqual(typeof createInputBatcher, "function");
assert.strictEqual(typeof createReconnectPolicy, "function");
assert.strictEqual(typeof handleTakeoverResponse, "function");
assert.strictEqual(typeof handleReleaseAction, "function");
assert.strictEqual(typeof initTerminalInstance, "function");
assert.strictEqual(typeof usableTermDims, "function");
assert.strictEqual(typeof termDimsForRequest, "function");
assert.strictEqual(typeof canStartTerminalStream, "function");
assert.strictEqual(typeof shouldShowTerminalRetryAction, "function");
assert.strictEqual(typeof parseHash, "function");

async function runAllTests() {
  console.log("Starting frontend terminal test suite...");

  // 1. Verify absence of EventSource and presence of custom header in stream request
  assert.strictEqual(
    appSource.includes("new EventSource"),
    false,
    "web/app.js must NEVER instantiate EventSource"
  );
  assert.strictEqual(
    appSource.includes("EventSource("),
    false,
    "web/app.js must not call EventSource"
  );
  assert(
    appSource.includes('"X-SID-Console": "1"'),
    "Stream request must send X-SID-Console: 1 custom header"
  );
  assert(
    appSource.includes('Accept: "text/event-stream"'),
    "Stream request must send Accept: text/event-stream"
  );
  console.log("ok: Category 1 - No EventSource and custom header enforcement verified");

  // 2. base64ToUint8Array multi-byte UTF-8, ANSI escape sequences, and binary data
  {
    const text = "Hello, 繁體中文與 Terminal! \u001b[32mPASS\u001b[0m \u001b[2J";
    const b64 = Buffer.from(text, "utf8").toString("base64");
    const bytes = base64ToUint8Array(b64);
    const roundtrip = Buffer.from(bytes).toString("utf8");
    assert.strictEqual(roundtrip, text, "base64ToUint8Array preserves multi-byte UTF-8 and ANSI sequences");
    console.log("ok: Category 2 - base64ToUint8Array UTF-8 & ANSI byte preservation verified");
  }

  // 3. SSE Parser: Chunking, CRLF/LF, Keepalives, Multi-line, and Event Memory Bounding
  {
    const events = [];
    const errors = [];
    const parser = createSSEParser(
      (ev) => events.push(ev),
      (err) => errors.push(err),
      500 // 500 byte test buffer limit
    );

    // 3a. Single event and split chunks
    parser.feed('data: {"type":"ter');
    assert.strictEqual(events.length, 0);
    parser.feed('minal.frame","seq":1}\n\n');
    assert.strictEqual(events.length, 1);
    assert.strictEqual(events[0].data.seq, 1);

    // 3b. CRLF and keepalive comments
    events.length = 0;
    parser.feed(": keepalive\r\n\r\n");
    assert.strictEqual(events.length, 0);
    parser.feed(': comment\r\ndata: {"type":"terminal.frame","seq":2}\r\n\r\n');
    assert.strictEqual(events.length, 1);
    assert.strictEqual(events[0].data.seq, 2);

    // 3c. Many small data lines exceeding event memory bound, and recovery on next valid event
    events.length = 0;
    errors.length = 0;
    // Feed 60 lines of "data: 0123456789\n" (each ~16 chars = ~960 chars > 500 byte limit)
    for (let i = 0; i < 60; i++) {
      parser.feed("data: 0123456789\n");
    }
    // Limit exceeded error must be reported ONCE
    assert.strictEqual(errors.length, 1, `Expected 1 error for event size limit, got ${errors.length}`);
    assert(errors[0].message.includes("event size limit exceeded"));
    assert.strictEqual(events.length, 0, "Oversized event must not be dispatched");

    // Close the oversized event boundary with empty line
    parser.feed("\n");
    assert.strictEqual(events.length, 0);

    // Next valid event must parse and dispatch cleanly (recovery)
    errors.length = 0;
    parser.feed('data: {"type":"terminal.frame","seq":3,"recovered":true}\n\n');
    assert.strictEqual(events.length, 1, "Next valid event recovered and dispatched");
    assert.strictEqual(events[0].data.seq, 3);
    assert.strictEqual(events[0].data.recovered, true);
    assert.strictEqual(errors.length, 0);

    // 3d. Huge chunk exceeding buffer bound
    errors.length = 0;
    parser.feed("x".repeat(600));
    assert.strictEqual(errors.length, 1);
    assert(errors[0].message.includes("buffer limit exceeded"));

    console.log("ok: Category 3 - SSE event memory bounding, reporting once, and recovery verified");
  }

  // 4. Bounded Reconnect Policy & Consecutive Failure Limiting
  {
    const policy = createReconnectPolicy({
      maxRetries: 3,
      baseDelayMs: 100,
      factor: 2.0,
      maxDelayMs: 1000,
    });

    assert.strictEqual(policy.canAutoRetry(), true);
    assert.strictEqual(policy.getRetryCount(), 0);

    // Simulate 200 OK + immediate EOF loop
    // 1st attempt: 200 received (success), then drop
    policy.recordConnectionSuccess(); // Must NOT reset retryCount
    const drop1 = policy.recordDrop();
    assert.strictEqual(drop1.shouldRetry, true);
    assert.strictEqual(drop1.attempt, 1);
    assert.strictEqual(drop1.delayMs, 100);

    // 2nd attempt: 200 received, then drop
    policy.recordConnectionSuccess();
    const drop2 = policy.recordDrop();
    assert.strictEqual(drop2.shouldRetry, true);
    assert.strictEqual(drop2.attempt, 2);
    assert.strictEqual(drop2.delayMs, 200);

    // 3rd attempt: 200 received, then drop
    policy.recordConnectionSuccess();
    const drop3 = policy.recordDrop();
    assert.strictEqual(drop3.shouldRetry, true);
    assert.strictEqual(drop3.attempt, 3);
    assert.strictEqual(drop3.delayMs, 400);

    // 4th attempt: budget exceeded (maxRetries = 3)
    policy.recordConnectionSuccess();
    const drop4 = policy.recordDrop();
    assert.strictEqual(drop4.shouldRetry, false, "Consecutive 200+EOF loop must exhaust retry budget");
    assert.strictEqual(policy.isExhausted(), true);
    assert.strictEqual(policy.canAutoRetry(), false);

    // Receiving valid frame resets the budget
    policy.recordValidFrame();
    assert.strictEqual(policy.getRetryCount(), 0, "Valid frame resets retry budget");
    assert.strictEqual(policy.canAutoRetry(), true);
    assert.strictEqual(policy.hasValidFrame(), true);

    // Exhaust again and test manual reset
    policy.recordDrop();
    policy.recordDrop();
    policy.recordDrop();
    policy.recordDrop();
    assert.strictEqual(policy.isExhausted(), true);
    policy.resetManual();
    assert.strictEqual(policy.getRetryCount(), 0, "Manual reset restores retry budget");
    assert.strictEqual(policy.canAutoRetry(), true);

    console.log("ok: Category 4 - Bounded reconnect consecutive failure and budget policy verified");
  }

  // 5. Input Batcher: Gating, Byte Cap, Error Callback & No Replay
  {
    const sent = [];
    const errors = [];
    let shouldFail = false;

    const batcher = createInputBatcher(
      async (text) => {
        if (shouldFail) throw new Error("Connection failed");
        sent.push(text);
      },
      {
        delayMs: 10,
        maxBatchBytes: 50,
        onError: (err) => errors.push(err),
      }
    );

    // 5a. Gating: disabled batcher drops input
    batcher.push("ignore-me");
    await new Promise((r) => setTimeout(r, 25));
    assert.strictEqual(sent.length, 0);

    // 5b. Enabled batcher batches keystrokes
    batcher.setEnabled(true);
    batcher.push("abc");
    batcher.push("def");
    await new Promise((r) => setTimeout(r, 30));
    assert.strictEqual(sent.length, 1);
    assert.strictEqual(sent[0], "abcdef");

    // 5c. Byte capping: text > maxBatchBytes splits into chunks <= 50 bytes
    sent.length = 0;
    const longString = "k".repeat(120);
    batcher.push(longString);
    await new Promise((r) => setTimeout(r, 80));
    assert(sent.length >= 3, `Expected split batches >= 3, got ${sent.length}`);
    assert.strictEqual(sent.join(""), longString);
    for (const chunk of sent) {
      assert(chunk.length <= 50, "Batch respects maxBatchBytes");
    }

    // 5d. Send failure triggers onError, clears queue, and NEVER replays dropped input
    sent.length = 0;
    errors.length = 0;
    shouldFail = true;

    batcher.push("lost-input-do-not-replay");
    await new Promise((r) => setTimeout(r, 30));

    assert.strictEqual(sent.length, 0, "No successful send on failure");
    assert.strictEqual(errors.length, 1, "onError callback invoked once on failure");
    assert(errors[0].message.includes("Connection failed"));

    // Restore network and send new input
    shouldFail = false;
    batcher.push("fresh-input");
    await new Promise((r) => setTimeout(r, 30));

    assert.strictEqual(sent.length, 1);
    assert.strictEqual(sent[0], "fresh-input", "Failed input was dropped and NOT replayed");

    console.log("ok: Category 5 - Input batcher gating, capping, failure notification & no-replay verified");
  }

  // 6. Release Action State Transition and Failure Recovery
  {
    let mode = "control";
    let connState = "connected";
    let inputEnabled = true;
    const fakeBatcher = {
      setEnabled: (v) => { inputEnabled = v; },
      clear: () => {},
    };

    // 6a. Successful release transitions to observe
    let releaseCalls = [];
    const okResult = await handleReleaseAction({
      isDisposed: false,
      mode,
      connState,
      inputBatcher: fakeBatcher,
      apiPost: async (body) => { releaseCalls.push(body); return { ok: true }; },
      onObserve: () => { mode = "observe"; },
      onError: () => {},
    });
    assert.strictEqual(okResult.ok, true);
    assert.strictEqual(mode, "observe");
    assert.strictEqual(inputEnabled, false);
    assert.strictEqual(releaseCalls[0].action, "release");

    // 6b. Failed release recovers input enabled state if view is live and connected
    mode = "control";
    inputEnabled = true;
    let errorReported = null;
    const failResult = await handleReleaseAction({
      isDisposed: false,
      mode,
      connState: "connected",
      inputBatcher: fakeBatcher,
      apiPost: async () => { throw new Error("500 Server Error"); },
      onObserve: () => { mode = "observe"; },
      onError: (err) => { errorReported = err; },
    });
    assert.strictEqual(failResult.ok, false);
    assert.strictEqual(mode, "control", "Mode remains control on release failure");
    assert.strictEqual(inputEnabled, true, "Input batcher re-enabled on release failure to prevent lockup");
    assert(errorReported && errorReported.message.includes("500"));

    console.log("ok: Category 6 - Release action success and failure recovery verified");
  }

  // 7. Takeover / Navigation Race and Deferred Promise Ordering
  {
    // 7a. Normal takeover success when view is live
    let liveSuccessCalled = false;
    const normalResult = await handleTakeoverResponse({
      res: { ok: true, mode: "control" },
      isDisposed: false,
      paneId: "p1",
      apiPost: async () => {},
      onLiveSuccess: () => { liveSuccessCalled = true; },
      onLiveError: () => {},
    });
    assert.strictEqual(normalResult.disposed, false);
    assert.strictEqual(normalResult.ok, true);
    assert.strictEqual(liveSuccessCalled, true);

    // 7b. Takeover completes AFTER route cleanup has disposed the view
    let releaseSent = [];
    let liveSuccessCalledDisposed = false;

    const disposedResult = await handleTakeoverResponse({
      res: { ok: true, mode: "control", token: "tok_test_abc123" },
      isDisposed: true, // Disposed during in-flight POST
      paneId: "p1",
      apiPost: async (path, body) => { releaseSent.push({ path, body }); },
      onLiveSuccess: () => { liveSuccessCalledDisposed = true; },
      onLiveError: () => {},
    });

    assert.strictEqual(disposedResult.disposed, true);
    assert.strictEqual(disposedResult.abandoned, true);
    assert.strictEqual(liveSuccessCalledDisposed, false, "Must not invoke live success on disposed view");
    assert.strictEqual(releaseSent.length, 1, "Best-effort abandon must be sent for orphaned control session");
    assert.strictEqual(releaseSent[0].body.action, "abandon");
    assert.strictEqual(releaseSent[0].body.token, "tok_test_abc123", "Abandon must include expected session token");

    // 7c. Takeover error on disposed view sends nothing
    releaseSent = [];
    const disposedErrorResult = await handleTakeoverResponse({
      res: { ok: false, error: "conflict" },
      isDisposed: true,
      paneId: "p1",
      apiPost: async (path, body) => { releaseSent.push({ path, body }); },
      onLiveSuccess: () => {},
      onLiveError: () => {},
    });
    assert.strictEqual(disposedErrorResult.disposed, true);
    assert.strictEqual(disposedErrorResult.abandoned, false);
    assert.strictEqual(releaseSent.length, 0);

    console.log("ok: Category 7 - Takeover navigation race and deferred cleanup verified");
  }

  // 8. Terminal Readiness Decision Gate & Initialization Safety
  {
    // 8a. Executable behavior coverage for canStartTerminalStream decision logic
    assert.strictEqual(
      canStartTerminalStream({ isDisposed: true, termReady: true }),
      false,
      "Disposed view cannot start terminal stream"
    );
    assert.strictEqual(
      canStartTerminalStream({ isDisposed: false, termReady: false }),
      false,
      "Unready terminal cannot start terminal stream"
    );
    assert.strictEqual(
      canStartTerminalStream({ isDisposed: false, termReady: true }),
      true,
      "Ready live terminal can start terminal stream"
    );
    assert.strictEqual(
      canStartTerminalStream({ isDisposed: false, term: {}, fitAddon: {} }),
      true,
      "Initialized term and fitAddon instances satisfy readiness"
    );
    assert.strictEqual(
      canStartTerminalStream({ isDisposed: false, term: null, fitAddon: {} }),
      false,
      "Missing term instance fails readiness"
    );
    assert.strictEqual(
      canStartTerminalStream({ isDisposed: false, term: {}, fitAddon: null }),
      false,
      "Missing fitAddon instance fails readiness"
    );

    // 8b. Executable behavior coverage for retry-action rendering decision
    // When terminal is not ready (missing or failed init), retry button MUST NOT be shown
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: false, connState: "error" }),
      false,
      "Must not show retry action when terminal is unready even in error state"
    );
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: false, connState: "disconnected" }),
      false,
      "Must not show retry action when terminal is unready in disconnected state"
    );
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: false, connState: "closed" }),
      false,
      "Must not show retry action when terminal is unready in closed state"
    );
    // When terminal is ready, retry button is available for error, disconnected, and closed states
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: true, connState: "error" }),
      true,
      "Shows retry action when terminal is ready and state is error"
    );
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: true, connState: "disconnected" }),
      true,
      "Shows retry action when terminal is ready and state is disconnected"
    );
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: true, connState: "closed" }),
      true,
      "Shows retry action when terminal is ready and state is closed"
    );
    assert.strictEqual(
      shouldShowTerminalRetryAction({ isDisposed: false, termReady: true, connState: "connected" }),
      false,
      "Does not show retry action when already connected"
    );

    // 8c. Missing globals fails gracefully
    const missingRes = initTerminalInstance({
      TerminalClass: null,
      FitAddonClass: null,
      termElem: new SyntheticNode("div"),
    });
    assert.strictEqual(missingRes.ok, false);
    assert(missingRes.error.includes("無法載入終端機模組"));

    // 8d. Faulty constructor disposes and returns error
    let disposed = false;
    class CrashingTerminal {
      constructor() { throw new Error("Canvas context creation failed"); }
      dispose() { disposed = true; }
    }
    class DummyAddon {}
    const crashRes = initTerminalInstance({
      TerminalClass: CrashingTerminal,
      FitAddonClass: DummyAddon,
      termElem: new SyntheticNode("div"),
    });
    assert.strictEqual(crashRes.ok, false);
    assert(crashRes.error.includes("Canvas context creation failed"));

    // 8e. Valid instantiation applies security options
    let instantiatedOptions = null;
    let openedElem = null;
    let fitted = false;
    class ValidTerminal {
      constructor(opts) { instantiatedOptions = opts; }
      loadAddon() {}
      open(el) { openedElem = el; }
      dispose() {}
    }
    class ValidFitAddon {
      fit() { fitted = true; }
    }
    const elem = new SyntheticNode("div");
    const validRes = initTerminalInstance({
      TerminalClass: ValidTerminal,
      FitAddonClass: ValidFitAddon,
      termElem: elem,
    });
    assert.strictEqual(validRes.ok, true);
    assert.strictEqual(openedElem, elem);
    assert.strictEqual(fitted, true);
    assert.strictEqual(instantiatedOptions.allowProposedApi, false);
    assert.strictEqual(instantiatedOptions.linkHandler, null);
    assert.deepStrictEqual(instantiatedOptions.windowOptions, {});

    // 8f. Source integration check: proving startStream, manualReconnect, and UI consult readiness gate
    assert(
      appSource.includes("async function startStream() {\n    if (!canStartTerminalStream({ isDisposed, termReady })) return;"),
      "startStream must check canStartTerminalStream gate before streaming"
    );
    assert(
      appSource.includes("function manualReconnect() {\n    if (!canStartTerminalStream({ isDisposed, termReady })) return;"),
      "manualReconnect must check canStartTerminalStream gate before reconnecting"
    );
    assert(
      appSource.includes("if (shouldShowTerminalRetryAction({ isDisposed, termReady, connState })) {"),
      "updateUI must consult shouldShowTerminalRetryAction before rendering retry button"
    );
    assert(
      appSource.includes("if (!termInit.ok) {\n    termReady = false;\n    connState = \"error\";"),
      "viewTerminal must mark termReady=false on init failure"
    );
    assert(
      appSource.includes("term = termInit.term;\n  fitAddon = termInit.fitAddon;\n  termReady = true;"),
      "viewTerminal must mark termReady=true on init success"
    );
    assert(
      appSource.includes("activeTerminalCleanup = () => {\n    isDisposed = true;\n    termReady = false;"),
      "activeTerminalCleanup must mark termReady=false on disposal"
    );

    console.log("ok: Category 8 - Terminal readiness gate, initialization safety, and source integration verified");
  }

  // 9. Contract Checks: Backend Resize, Takeover Warning, and Hash Routing
  {
    // 9a. Resize POST contract: must use POST /api/term/<pane>/control with action: "resize"
    assert(
      appSource.includes('api.post(`/api/term/${encodeURIComponent(paneId)}/control`,'),
      "Resize must target /control endpoint"
    );
    assert(
      appSource.includes('action: "resize",\n            cols: term.cols,\n            rows: term.rows,'),
      "Resize must payload action: resize with cols and rows"
    );

    // 9b. Takeover warning text verifies shared input channel
    assert(
      appSource.includes("重要提醒：接管操作為共享輸入通道，不會鎖定原生 Herdr 視窗。原生視窗與瀏覽器均可打字，兩端輸入可能會互相交錯。"),
      "Takeover warning must explicitly describe shared non-exclusive input"
    );

    // 9c. Safe hash routing
    global.location.hash = "#/term/w1%3ApA";
    const p1 = parseHash();
    assert.strictEqual(p1.parts[0], "term");
    assert.strictEqual(decodeURIComponent(p1.parts[1]), "w1:pA");

    global.location.hash = "#/term/agent-pane%201";
    const p2 = parseHash();
    assert.strictEqual(p2.parts[0], "term");
    assert.strictEqual(decodeURIComponent(p2.parts[1]), "agent-pane 1");

    console.log("ok: Category 9 - Backend resize contract, takeover warning & hash routing verified");
  }

  // 10. Safe Full-Frame Resynchronization without term.reset() destruction
  {
    // 10a. Full frame preserves alternate buffer and normal scrollback
    const writtenBytes = [];
    let scrolledToBottom = false;
    let validFrameRecorded = false;
    let resetCalled = false;

    const fakeTerm = {
      reset: () => { resetCalled = true; },
      scrollToBottom: () => { scrolledToBottom = true; },
      write: (data) => { writtenBytes.push(data); },
    };

    const fakePolicy = {
      recordValidFrame: () => { validFrameRecorded = true; },
    };

    const sampleB64 = Buffer.from("Hello Redraw", "utf8").toString("base64");
    const ok = handleTerminalFrame({
      type: "terminal.frame",
      full: true,
      bytes: sampleB64,
    }, { term: fakeTerm, reconnectPolicy: fakePolicy });

    assert.strictEqual(ok, true);
    assert.strictEqual(validFrameRecorded, true, "Valid frame must be recorded in reconnect policy");
    assert.strictEqual(scrolledToBottom, true, "Full frame must scroll to bottom");
    assert.strictEqual(resetCalled, false, "Must NOT call term.reset() on full frame (destroys alt buffer and wipes scrollback)");
    assert.strictEqual(writtenBytes.length, 1);
    assert.strictEqual(Buffer.from(writtenBytes[0]).toString("utf8"), "Hello Redraw");

    // 10b. Real xterm instance verification: alternate buffer and scrollback preserved across full frame
    const { Terminal } = require("../../web/vendor/xterm/xterm.js");
    const realTerm = new Terminal({ scrollback: 1000, rows: 10, cols: 40 });
    for (let i = 1; i <= 20; i++) {
      realTerm.write(`line ${i}\r\n`);
    }

    await new Promise((resolve) => {
      realTerm.write("\x1b[?1049h", () => {
        assert.strictEqual(realTerm.buffer.active.type, "alternate");
        const normalLinesBefore = realTerm.buffer.normal.length;
        assert.strictEqual(normalLinesBefore, 21);

        const fullAnsi = Buffer.from("\x1b[2J\x1b[1;1HRedrawn in Alternate Screen", "utf8").toString("base64");
        handleTerminalFrame({
          type: "terminal.frame",
          full: true,
          bytes: fullAnsi,
        }, { term: realTerm, reconnectPolicy: fakePolicy });

        assert.strictEqual(realTerm.buffer.active.type, "alternate", "Alternate buffer must be preserved across full frame");
        assert.strictEqual(realTerm.buffer.normal.length, 21, "Normal buffer scrollback must NOT be wiped by full frame");

        // 10c. Same-pane continuity: simulate full reconnect sequence where Herdr full frame
        // omits DECSET 1049, followed by application exiting alternate buffer (\x1b[?1049l)
        const herdrRealisticFullFrame = Buffer.from(
          "\x1b[?2026h\x1b[?25l\x1b]8;;\x1b\\\x1b[2J\x1b[1;1H\x1b[0;39;49m=== SAME PANE RECONNECT REDRAW ===\x1b[0m\x1b[?25h",
          "utf8"
        ).toString("base64");

        handleTerminalFrame({
          type: "terminal.frame",
          full: true,
          bytes: herdrRealisticFullFrame,
        }, { term: realTerm, reconnectPolicy: fakePolicy });

        assert.strictEqual(realTerm.buffer.active.type, "alternate", "Buffer must remain alternate after Herdr reconnect frame");
        assert.strictEqual(realTerm.buffer.normal.length, 21, "Normal buffer scrollback preserved during reconnect");

        // When application in the same pane later exits alternate buffer
        realTerm.write("\x1b[?1049l", () => {
          assert.strictEqual(realTerm.buffer.active.type, "normal", "Exiting alternate screen restores normal buffer");
          assert.strictEqual(realTerm.buffer.normal.length, 21, "Original normal scrollback lines are intact");
          assert.strictEqual(realTerm.buffer.normal.getLine(9).translateToString(true), "line 10");
          resolve();
        });
      });
    });

    console.log("ok: Category 10 - Safe full-frame resynchronization (same-pane continuity & scrollback preserved) verified");
  }

  // 11. Degenerate terminal dimensions never reach the server or the pane
  {
    // 11a. The predicate itself: a pre-layout measurement is not usable.
    assert.strictEqual(usableTermDims({ cols: 2, rows: 37 }), false, "cols=2 (the observed pre-layout fit) must be rejected");
    assert.strictEqual(usableTermDims({ cols: 0, rows: 0 }), false);
    assert.strictEqual(usableTermDims({ cols: 80, rows: 1 }), false, "a 1-row terminal is unusable too");
    assert.strictEqual(usableTermDims(null), false);
    assert.strictEqual(usableTermDims(undefined), false);
    assert.strictEqual(usableTermDims({ cols: 80, rows: 24 }), true);
    assert.strictEqual(usableTermDims({ cols: 20, rows: 5 }), true, "the floor itself is allowed");

    // 11b. What gets advertised: fall back to 80x24 rather than clamping, so a
    // degenerate measurement yields an ordinary terminal that the first real
    // ResizeObserver callback corrects, not a valid-but-unusable 20-column one.
    assert.deepStrictEqual(termDimsForRequest({ cols: 2, rows: 37 }), { cols: 80, rows: 24 });
    assert.deepStrictEqual(termDimsForRequest(null), { cols: 80, rows: 24 });
    assert.deepStrictEqual(termDimsForRequest({ cols: 120, rows: 40 }), { cols: 120, rows: 40 });

    // 11c. init must not fit against a container that has not been laid out.
    // This is the actual bug: term.open() followed by an immediate fit() inside
    // a three-column grid that had not resolved yet measured a near-zero width.
    let fittedEarly = false;
    class DegenerateFitAddon {
      fit() { fittedEarly = true; }
      proposeDimensions() { return { cols: 2, rows: 37 }; }
    }
    class CountingTerminal {
      constructor() { this.cols = 80; this.rows = 24; }
      loadAddon() {}
      open() {}
      dispose() {}
    }
    const degenerateRes = initTerminalInstance({
      TerminalClass: CountingTerminal,
      FitAddonClass: DegenerateFitAddon,
      termElem: new SyntheticNode("div"),
    });
    assert.strictEqual(degenerateRes.ok, true, "init still succeeds; only the fit is skipped");
    assert.strictEqual(fittedEarly, false, "must NOT fit when proposeDimensions() is degenerate");

    // A laid-out container still fits, so this is not simply "never fit".
    let fittedReal = false;
    class RealFitAddon {
      fit() { fittedReal = true; }
      proposeDimensions() { return { cols: 120, rows: 40 }; }
    }
    initTerminalInstance({
      TerminalClass: CountingTerminal,
      FitAddonClass: RealFitAddon,
      termElem: new SyntheticNode("div"),
    });
    assert.strictEqual(fittedReal, true, "a real layout must still be fitted");

    // 11d. Neither terminal implementation may advertise term.cols directly:
    // that is what sent cols=2 to the server. The workbench terminal and the
    // standalone one are separate implementations, so both are checked.
    assert.strictEqual(
      /cols:\s*term\s*\?\s*term\.cols\s*:\s*80/.test(appSource),
      false,
      "takeover/stream must not send term.cols unchecked; use termDimsForRequest()"
    );
    assert.strictEqual(
      (appSource.match(/const \{ cols, rows \} = termDimsForRequest\(term\);/g) || []).length,
      2,
      "both the workbench and standalone stream URLs must use termDimsForRequest()"
    );
    assert.strictEqual(
      (appSource.match(/\.\.\.termDimsForRequest\(term\),/g) || []).length,
      2,
      "both takeover payloads must use termDimsForRequest()"
    );
    assert.strictEqual(
      (appSource.match(/if \(!usableTermDims\(dims\)\) return;/g) || []).length,
      2,
      "both handleResize implementations must gate on usableTermDims()"
    );

    console.log("ok: Category 11 - Degenerate terminal dimensions never reach the server or the pane");
  }

  console.log("\nALL FRONTEND TESTS PASSED (11/11 categories verified)");
}

runAllTests()
  .then(() => {
    process.exit(0);
  })
  .catch((err) => {
    console.error("Test failure:", err);
    process.exit(1);
  });
