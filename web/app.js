"use strict";
/* VBear — UI.
 * Skill and agent text is untrusted input: everything is rendered through
 * el(), which only ever creates text nodes. There is no innerHTML here.
 */

// ---------- dom + api helpers ----------------------------------------------

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v; // CSSOM: allowed under the strict CSP
      else if (k === "on") for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k in node && typeof v !== "string") node[k] = v;
      else node.setAttribute(k, v === true ? "" : String(v));
    }
  }
  append(node, kids);
  return node;
}
function append(node, ...kids) {
  // Variadic (not just a single array param): renderAgentTabContent,
  // renderProjectTabContent and renderGlobalTabContent all call this as
  // append(content, elA, elB, ...) the same way el()'s own ...kids works —
  // a single-array `kids` parameter silently dropped every argument after
  // the first (or threw, since a lone Node has no .flat()) on every one of
  // those calls. .flat(Infinity) absorbs the extra nesting from `...kids`
  // for existing array-taking call sites (el(), setKids()), so this stays
  // compatible with both calling conventions.
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

// The focusable elements currently inside `container`, in DOM order.
// Recomputed on every Tab press (not cached at dialog-open time) because a
// dialog's own controls can become disabled mid-flight (e.g. a save button
// during submit), which must drop them from the trap immediately.
function getFocusableElements(container) {
  const nodes = container.querySelectorAll('a[href], button, textarea, input, select, [tabindex]');
  return Array.from(nodes).filter((n) => {
    if (n.disabled) return false;
    const ti = n.getAttribute("tabindex");
    if (ti !== null && Number(ti) < 0) return false;
    return true;
  });
}

// Standard modal a11y (L4): the dialog's title must be linked via
// aria-labelledby (each call site sets that itself); Escape closes the
// dialog and focus returns to whatever triggered it; initial focus moves
// into the dialog (respecting a caller that already moved it there itself,
// e.g. confirmBtn.focus(), and falling back to the first focusable element
// otherwise — previously some dialogs, e.g. the task-edit modal, moved focus
// nowhere at all); Tab/Shift-Tab is trapped inside the dialog's focusable
// elements so keyboard focus can never wander behind it; and every other
// direct child of <body> (the app shell, nav, toast region) is marked
// `inert` + aria-hidden for the duration, so neither a screen reader nor
// keyboard-only navigation can reach content behind an open dialog.
// `teardown` is the caller's own removal logic (DOM removal plus clearing
// its local reference); call sites use the function this returns wherever
// they used to call their own close/remove directly, so Escape and every
// other close path go through the same code.
function withModalA11y(modalElem, teardown) {
  const trigger = document.activeElement;

  // Only nodes this dialog *itself* makes inert are recorded, and an
  // already-inert node is left completely alone: it belongs to an outer
  // dialog that is still open, and "restoring" it here would either clear
  // inert out from under that dialog or (the mirror-image bug) write back a
  // snapshot that says "was already inert" and leave the page permanently
  // inert after everything has closed. This delta-only bookkeeping is what
  // makes the strict LIFO unwind in closeOpenModals() correct for nesting.
  const inertedSiblings = [];
  for (const node of Array.from(document.body.children)) {
    if (node === modalElem) continue;
    if (node.hasAttribute("inert")) continue;
    inertedSiblings.push({
      node,
      priorAriaHidden: node.getAttribute("aria-hidden"),
    });
    node.setAttribute("inert", "");
    node.setAttribute("aria-hidden", "true");
  }
  function restoreBackground() {
    for (const { node, priorAriaHidden } of inertedSiblings) {
      node.removeAttribute("inert");
      if (priorAriaHidden === null) node.removeAttribute("aria-hidden");
      else node.setAttribute("aria-hidden", priorAriaHidden);
    }
  }

  // Idempotent, and it deregisters itself. Every close path — Escape, the
  // dialog's own cancel/confirm buttons, and a terminal/view teardown going
  // through closeOpenModals() — funnels through this one function, so a
  // dialog closed by Escape can never be left behind in the registry for a
  // later navigation to "close" a second time (which, with call sites that
  // reuse a single `modalElem` variable, could tear down a *newly reopened*
  // dialog instead of the one that actually closed).
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    const at = openModalCloses.indexOf(close);
    if (at !== -1) openModalCloses.splice(at, 1);
    modalElem.removeEventListener("keydown", onKeyDown);
    restoreBackground();
    teardown();
    if (trigger && typeof trigger.focus === "function") trigger.focus();
  }

  function onKeyDown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "Tab") {
      const focusable = getFocusableElements(modalElem);
      if (focusable.length === 0) {
        e.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const current = document.activeElement;
      if (e.shiftKey) {
        if (current === first || !focusable.includes(current)) {
          e.preventDefault();
          last.focus();
        }
      } else if (current === last || !focusable.includes(current)) {
        e.preventDefault();
        first.focus();
      }
    }
  }
  modalElem.addEventListener("keydown", onKeyDown);

  const focusable = getFocusableElements(modalElem);
  if (!focusable.includes(document.activeElement) && focusable.length > 0) {
    focusable[0].focus();
  }

  openModalCloses.push(close);
  return close;
}

// Every open modal is registered here by withModalA11y itself (registration
// is not something a call site can forget) so that a terminal/view teardown
// — navigating away, switching panes, mid-dialog — can close it the *proper*
// way: through the dialog's own close(), which removes it, restores
// inert/aria-hidden on the rest of the page, and detaches its keydown
// listener. Reaching in and yanking the element out of the DOM directly (as
// terminal/view cleanup used to) skips all of that and permanently leaves
// the rest of the page inert once the dialog is already gone.
//
// A stack, not a single overwritable slot and not an insertion-ordered Set:
// several independently-owned dialogs can be open at once, each having
// inerted whatever was not already inert beneath it, so they must unwind
// innermost-first. Closing them in insertion order would have an outer
// dialog clear inert while an inner one is still open.
const openModalCloses = [];
function closeOpenModals() {
  // LIFO, re-read each iteration because close() splices itself out (and a
  // dialog's teardown is free to close others). The identity check is a
  // belt-and-braces guard against a close() that somehow fails to
  // deregister, so this can never spin forever.
  let guard = openModalCloses.length + 8;
  while (openModalCloses.length > 0 && guard-- > 0) {
    const close = openModalCloses[openModalCloses.length - 1];
    close();
    if (openModalCloses[openModalCloses.length - 1] === close) openModalCloses.pop();
  }
}
function setKids(node, ...kids) { node.replaceChildren(); return append(node, kids); }
const $main = () => document.getElementById("main");
// Navigation sequence: a view that finishes loading after the user has already
// moved on must not paint over the newer page.
let seq = 0;
function claim(token) { return token === seq ? $main() : document.createElement("div"); }

// Typing fires one search after a short pause instead of one per keystroke.
// .now() runs it at once (Enter, example buttons) and drops the pending one.
function debounce(fn, ms = 200) {
  let timer = null;
  const run = () => { clearTimeout(timer); timer = null; fn(); };
  const wrapped = () => { clearTimeout(timer); timer = setTimeout(run, ms); };
  wrapped.now = run;
  wrapped.cancel = () => { clearTimeout(timer); timer = null; };
  return wrapped;
}

function base64ToUint8Array(b64) {
  if (typeof atob === "function") {
    const bin = atob(b64);
    const len = bin.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = bin.charCodeAt(i);
    }
    return bytes;
  }
  if (typeof Buffer !== "undefined") {
    return new Uint8Array(Buffer.from(b64, "base64"));
  }
  throw new Error("No base64 decoder available");
}

function createSSEParser(onEvent, onError, maxBufferSize = 512 * 1024) {
  let buffer = "";
  let eventType = "";
  let dataLines = [];
  let currentEventSize = 0;
  let discardedEvent = false;

  function processLine(line) {
    if (line.endsWith("\r")) line = line.slice(0, -1);
    if (line === "") {
      if (discardedEvent) {
        discardedEvent = false;
        dataLines = [];
        currentEventSize = 0;
        eventType = "";
        return;
      }
      if (dataLines.length > 0) {
        const raw = dataLines.join("\n");
        dataLines = [];
        currentEventSize = 0;
        const type = eventType || "message";
        eventType = "";
        try {
          const data = JSON.parse(raw);
          if (onEvent) onEvent({ type, data, raw });
        } catch (err) {
          if (onError) onError(new Error("SSE JSON parse error: " + err.message));
        }
      }
      eventType = "";
      currentEventSize = 0;
      return;
    }
    if (discardedEvent) return;
    if (line.startsWith(":")) return;
    const colonIdx = line.indexOf(":");
    let field = line;
    let value = "";
    if (colonIdx !== -1) {
      field = line.slice(0, colonIdx);
      value = line.slice(colonIdx + 1);
      if (value.startsWith(" ")) value = value.slice(1);
    }
    if (field === "data") {
      currentEventSize += value.length + 1;
      if (currentEventSize > maxBufferSize) {
        discardedEvent = true;
        dataLines = [];
        currentEventSize = 0;
        eventType = "";
        if (onError) onError(new Error("SSE event size limit exceeded"));
        return;
      }
      dataLines.push(value);
    } else if (field === "event") {
      eventType = value;
    }
  }

  function feed(chunkText) {
    if (!chunkText) return;
    if (buffer.length + chunkText.length > maxBufferSize) {
      buffer = "";
      dataLines = [];
      currentEventSize = 0;
      eventType = "";
      discardedEvent = true;
      if (onError) onError(new Error("SSE buffer limit exceeded"));
      return;
    }
    buffer += chunkText;
    let lineEnd;
    while ((lineEnd = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, lineEnd);
      buffer = buffer.slice(lineEnd + 1);
      processLine(line);
    }
  }

  function flush() {
    if (buffer.length > 0) {
      processLine(buffer);
      buffer = "";
    }
    if (dataLines.length > 0 || discardedEvent) {
      processLine("");
    }
  }

  function reset() {
    buffer = "";
    dataLines = [];
    currentEventSize = 0;
    eventType = "";
    discardedEvent = false;
  }

  return { feed, flush, reset };
}

function createReconnectPolicy(options = {}) {
  const maxRetries = typeof options.maxRetries === "number" ? options.maxRetries : 5;
  const baseDelayMs = typeof options.baseDelayMs === "number" ? options.baseDelayMs : 1000;
  const factor = typeof options.factor === "number" ? options.factor : 1.5;
  const maxDelayMs = typeof options.maxDelayMs === "number" ? options.maxDelayMs : 8000;

  let retryCount = 0;
  let hasReceivedValidFrame = false;

  function recordConnectionSuccess() {
    // Do not reset retryCount here: 200 + immediate EOF loop must not retry forever.
  }

  function recordValidFrame() {
    retryCount = 0;
    hasReceivedValidFrame = true;
  }

  function recordDrop() {
    retryCount++;
    if (retryCount <= maxRetries) {
      const delayMs = Math.min(baseDelayMs * Math.pow(factor, retryCount - 1), maxDelayMs);
      return { shouldRetry: true, attempt: retryCount, maxRetries, delayMs };
    }
    return { shouldRetry: false, attempt: retryCount, maxRetries, delayMs: null };
  }

  function resetManual() {
    retryCount = 0;
    hasReceivedValidFrame = false;
    return { retryCount: 0 };
  }

  return {
    recordConnectionSuccess,
    recordValidFrame,
    recordDrop,
    resetManual,
    canAutoRetry: () => retryCount < maxRetries,
    getRetryCount: () => retryCount,
    isExhausted: () => retryCount >= maxRetries,
    hasValidFrame: () => hasReceivedValidFrame,
  };
}

async function handleTakeoverResponse({ res, isDisposed, paneId, apiPost, onLiveSuccess, onLiveError }) {
  if (isDisposed) {
    if (res && res.ok) {
      try {
        await apiPost(`/api/term/${encodeURIComponent(paneId)}/control`, {
          action: "abandon",
          token: res.token,
        });
      } catch (_) {}
    }
    return { disposed: true, abandoned: Boolean(res && res.ok) };
  }

  if (res && res.ok) {
    if (onLiveSuccess) onLiveSuccess(res);
    return { disposed: false, ok: true, token: res.token };
  }
  if (onLiveError) onLiveError(res);
  return { disposed: false, ok: false };
}

async function handleReleaseAction({ isDisposed, mode, connState, inputBatcher, apiPost, onObserve, onError }) {
  if (inputBatcher) {
    inputBatcher.setEnabled(false);
    inputBatcher.clear();
  }
  try {
    const res = await apiPost({ action: "release" });
    if (onObserve) onObserve(res);
    return { ok: true };
  } catch (err) {
    if (!isDisposed && mode === "control" && connState === "connected" && inputBatcher) {
      inputBatcher.setEnabled(true);
    }
    if (onError) onError(err);
    return { ok: false, error: err };
  }
}

function handleTerminalFrame(msg, { term, reconnectPolicy } = {}) {
  if (!msg || msg.type !== "terminal.frame") return false;
  if (reconnectPolicy && typeof reconnectPolicy.recordValidFrame === "function") {
    reconnectPolicy.recordValidFrame();
  }
  if (msg.full && term && typeof term.scrollToBottom === "function") {
    term.scrollToBottom();
  }
  if (msg.bytes && term && typeof term.write === "function") {
    term.write(base64ToUint8Array(msg.bytes));
  }
  return true;
}

// Mirrors TERM_MIN_DIM/TERM_MIN_ROWS in vbear/server.py. A terminal
// narrower or shorter than this cannot render anything usable, and a resize
// is applied to the session's PTY for every viewer.
const TERM_MIN_COLS = 20;
const TERM_MIN_ROWS = 5;
const TERMINAL_VISIBLE_SCREEN_NOTICE = "畫面歷史：開啟時只重播最近一段輸出，不提供完整的回捲歷史。";

// True only for dimensions worth sending to the server or fitting to.
// fitAddon.fit() measures the canvas, so when it is called before the grid
// has laid out it proposes something degenerate -- a real observed case was
// cols=2 -- and nothing downstream rejected it: the frontend sent cols=2 and
// the backend's lower bound was 1, so the pane really was resized to two
// columns, and every subsequent check of rendering, IME and scrollback was
// measuring a ruined terminal.
function usableTermDims(dims) {
  return Boolean(dims) && dims.cols >= TERM_MIN_COLS && dims.rows >= TERM_MIN_ROWS;
}

// The dimensions to advertise for a pane. Falls back to the standard 80x24
// rather than clamping, so a degenerate measurement yields an ordinary
// terminal that the first real ResizeObserver callback then corrects,
// instead of a technically-valid but unusable 20-column one.
function termDimsForRequest(term) {
  if (term && usableTermDims({ cols: term.cols, rows: term.rows })) {
    return { cols: term.cols, rows: term.rows };
  }
  return { cols: 80, rows: 24 };
}

function initTerminalInstance({ TerminalClass, FitAddonClass, termElem, options = {} }) {
  if (!TerminalClass || !FitAddonClass) {
    return { ok: false, error: "無法載入終端機模組 (xterm.js)", term: null, fitAddon: null };
  }
  let term = null;
  let fitAddon = null;
  try {
    term = new TerminalClass({
      cursorBlink: true,
      allowProposedApi: false,
      linkHandler: null,
      windowOptions: {},
      fontSize: 13,
      fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
      theme: {
        background: "#151917",
        foreground: "#e9ece8",
        cursor: "#7fb8a4",
        selectionBackground: "rgba(47, 93, 80, 0.4)",
      },
      // The stream is a replay of recent output plus live redraws, not a
      // complete history; a nominal scrollback buffer would promise more than
      // the protocol provides.
      scrollback: 0,
      ...options,
    });
    fitAddon = new FitAddonClass();
    term.loadAddon(fitAddon);
    if (termElem) {
      term.open(termElem);
      // Only fit if the element has actually been laid out. Fitting against a
      // zero-width container leaves the terminal at a degenerate size that is
      // then advertised to the server; leaving the xterm default in place is
      // strictly better, because the ResizeObserver registered by the caller
      // fires as soon as the real layout lands and fits properly then.
      if (typeof fitAddon.fit === "function") {
        const dims = typeof fitAddon.proposeDimensions === "function"
          ? fitAddon.proposeDimensions()
          : null;
        // No proposeDimensions (test doubles, older addon): keep the previous
        // unconditional behaviour rather than never fitting at all.
        if (!dims || usableTermDims(dims)) {
          fitAddon.fit();
        }
      }
    }
    return { ok: true, term, fitAddon };
  } catch (err) {
    if (term && typeof term.dispose === "function") {
      try { term.dispose(); } catch (_) {}
    }
    return { ok: false, error: err ? err.message : "終端機初始化失敗", term: null, fitAddon: null };
  }
}

function canStartTerminalStream(state = {}) {
  if (state.isDisposed) return false;
  if (state.termReady === false) return false;
  if (state.termReady === true) return true;
  return Boolean(state.term && state.fitAddon);
}

function shouldShowTerminalRetryAction(state = {}) {
  if (!canStartTerminalStream(state)) return false;
  const s = state.connState;
  return s === "disconnected" || s === "closed" || s === "error";
}

function createInputBatcher(sendFn, options = {}) {
  const delayMs = options.delayMs || 10;
  const maxBatchBytes = options.maxBatchBytes || 3500;
  let queue = [];
  let timer = null;
  let sending = false;
  let currentBytes = 0;
  let enabled = false;

  function setEnabled(val) {
    const next = Boolean(val);
    if (enabled !== next) {
      enabled = next;
      if (!enabled) clear();
    }
  }

  function clear() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    queue = [];
    currentBytes = 0;
  }

  function measureBytes(str) {
    if (typeof TextEncoder !== "undefined") {
      return new TextEncoder().encode(str).length;
    }
    if (typeof Buffer !== "undefined") {
      return Buffer.byteLength(str, "utf8");
    }
    return unescape(encodeURIComponent(str)).length;
  }

  function push(str) {
    if (!enabled || !str) return;
    const strBytes = measureBytes(str);
    if (strBytes > maxBatchBytes) {
      let chunk = "";
      let chunkBytes = 0;
      for (const char of str) {
        const cb = measureBytes(char);
        if (chunkBytes + cb > maxBatchBytes) {
          queue.push(chunk);
          chunk = char;
          chunkBytes = cb;
        } else {
          chunk += char;
          chunkBytes += cb;
        }
      }
      if (chunk) queue.push(chunk);
    } else {
      if (currentBytes + strBytes > maxBatchBytes) {
        flush();
      }
      queue.push(str);
      currentBytes += strBytes;
    }

    if (!timer && queue.length > 0 && !sending) {
      timer = setTimeout(flush, delayMs);
    }
  }

  async function flush() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (!enabled || queue.length === 0 || sending) return;

    let batch = "";
    let batchBytes = 0;
    while (queue.length > 0) {
      const next = queue[0];
      const nextBytes = measureBytes(next);
      if (batchBytes + nextBytes > maxBatchBytes) {
        if (batch.length === 0) {
          batch = queue.shift();
          batchBytes = nextBytes;
        }
        break;
      }
      batch += queue.shift();
      batchBytes += nextBytes;
    }
    currentBytes = Math.max(0, currentBytes - batchBytes);
    sending = true;

    try {
      await sendFn(batch);
    } catch (err) {
      clear();
      if (options.onError) options.onError(err);
    } finally {
      sending = false;
      if (enabled && queue.length > 0) {
        timer = setTimeout(flush, delayMs);
      }
    }
  }

  return {
    push,
    flush,
    clear,
    setEnabled,
    isEnabled: () => enabled,
    getQueueLength: () => queue.length,
  };
}

const api = {
  // opts.timeoutMs: give up after that long (the request is aborted) and
  // throw an error with .timeout set, instead of waiting forever.
  // opts.signal: an AbortSignal of the caller (a page that is left); when it
  // aborts, so does the request, and the error has .aborted set.
  async get(path, opts = {}) {
    const ctl = opts.timeoutMs || opts.signal ? new AbortController() : null;
    const timer = ctl && opts.timeoutMs ? setTimeout(() => ctl.abort(), opts.timeoutMs) : null;
    if (ctl && opts.signal) {
      if (opts.signal.aborted) ctl.abort();
      else opts.signal.addEventListener("abort", () => ctl.abort(), { once: true });
    }
    const timedOut = () => {
      if (opts.signal && opts.signal.aborted) {
        const error = new Error("已取消");
        error.aborted = true;
        return error;
      }
      const error = new Error(`${Math.round(opts.timeoutMs / 1000)} 秒沒有回應，已停止等待`);
      error.timeout = true;
      return error;
    };
    try {
      // The custom header lets the server tell its own page from a cross-site request.
      const res = await fetch(path, { headers: { Accept: "application/json", "X-VBear": "1" }, signal: ctl ? ctl.signal : undefined });
      const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      if (ctl && ctl.signal.aborted) throw timedOut();
      if (res.status === 401 && data.code === "auth_required") authLost();
      if (!res.ok) {
        const error = new Error(data.error || `HTTP ${res.status}`);
        error.status = res.status;
        error.code = data.code;
        error.data = data;
        throw error;
      }
      return data;
    } catch (e) {
      if (ctl && ctl.signal.aborted && !e.timeout && !e.aborted) throw timedOut();
      throw e;
    } finally {
      if (timer) clearTimeout(timer);
    }
  },
  async del(path) {
    const res = await fetch(path, { method: "DELETE", headers: { "X-VBear": "1" } });
    const data = await res.json();
    if (res.status === 401 && data.code === "auth_required") authLost();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-VBear": "1" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (res.status === 401 && data.code === "auth_required") authLost();
    if (!res.ok) {
      const error = new Error(data.error || `HTTP ${res.status}`);
      error.status = res.status;
      error.code = data.code;
      error.data = data;
      throw error;
    }
    return data;
  },
};

// The session cookie stopped working (VBear restarted, or the page was
// opened without going through VBear): stop refreshing and say how to get in.
let authLostShown = false;
// True from the start of the page until the login code in the address (#auth=<token>) has been traded for the session
// cookie. Until then a 401 is expected, so nothing may show "open VBear" or start the router (see bootstrap).
let authPending = false;
function authLost() {
  if (authPending || authLostShown || typeof document === "undefined") return;
  authLostShown = true;
  clearInterval(liveTimer);
  liveTick = null;
  cleanupActiveTerminal();
  setKids($main(), authRequiredView());
}

function authRequiredView() {
  return el("div", { class: "section" },
    el("h1", null, "請從 VBear 開啟"),
    notice("warn", "VBear 只接受從它自己打開的視窗。這個分頁沒有通行證，可能是直接輸入了網址，或 VBear 重新啟動過。"),
    el("p", null, "打開 VBear App，或在終端機執行 ", el("code", null, "python3 -m vbear launch"), "，會自動開一個可以使用的分頁。"));
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

const store = {
  get(k, d) { try { const v = localStorage.getItem("sid:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("sid:" + k, JSON.stringify(v)); } catch { /* optional */ } },
};

// ---------- vocabulary -----------------------------------------------------

const TOOL = { claude: "Claude Code", codex: "Codex CLI", shared: "skills CLI", agy: "Antigravity" };
const ACT = {
  active:        ["可使用", "b-ok", "位於工具的載入範圍，且沒有被停用"],
  disabled:      ["已停用", "b-mute", "已安裝，但被設定關閉"],
  superseded:    ["舊版快取", "b-mute", "舊版本的快取副本，目前安裝的是較新版本"],
  not_installed: ["未安裝", "b-info", "外掛市集中的來源副本，尚未安裝"],
  not_loaded:    ["附帶・不載入", "b-mute", "隨外掛附帶，但不在技能載入路徑"],
  archived:      ["封存", "b-mute", "位於備份或暫存目錄"],
  unknown:       ["無法確認", "b-warn", "沒有任何設定檔能證明它是否被載入"],
};
const SCOPE = { user: "使用者", synced: "雲端同步", plugin: "外掛", marketplace: "外掛市集",
  system: "系統內建", project: "專案", shared: "共用庫", vendor: "匯入" };
// Display values of vbear/activity.py (display_value). Anything else renders
// as unknown: a word the taxonomy does not define is never shown as a state.
const STATUS = {
  "needs-input": ["需要你處理", "b-bad"], waiting: ["等你回覆", "b-warn"], working: ["工作中", "b-info"],
  exited: ["已結束", "b-mute"], unknown: ["狀態未知", "b-mute"],
};
const PROV = {
  author: ["作者說明", "原始檔案中作者寫下的內容"],
  derived: ["自動整理", "由主控台依文件結構或關鍵字整理，不是作者的聲明"],
  runtime: ["執行觀察", "從實際執行紀錄觀察到"],
  missing: ["未提供", "來源沒有提供這項資訊"],
  user: ["我的註記", "你在主控台加上的註記，只存在主控台，不會寫回技能檔"],
};
const BASIS = {
  load_scope: "依載入範圍：技能位於此工具會載入的目錄且未停用",
  declared: "角色檔案中明確宣告",
  undeclared: "角色檔案未宣告技能；是否繼承主代理的技能，本機設定無法確認",
  "claude-subagent": "角色檔案未宣告技能",
  "codex-profile": "角色檔案未宣告技能",
};
const EVIDENCE = {
  explicit: ["已確認使用", "b-ok", "Claude Code 紀錄中有明確的 Skill 呼叫"],
  file_read: ["讀取過技能檔", "b-info", "Codex 在工具呼叫中讀取了此技能的 SKILL.md（Codex 載入技能的方式），強度低於明確呼叫"],
};

function badge(label, cls, title, plain) {
  return el("span", { class: `badge ${cls}${plain ? " plain" : ""}`, title }, label);
}
function actBadge(a) { const [l, c, t] = ACT[a] || ACT.unknown; return badge(l, c, t); }
const ACT_HELP = {
  active: "可使用代表掃描到它位於工具的載入範圍；不代表目前有 Agent 正在使用。",
  disabled: "已安裝但被設定關閉；不會因為出現在清單中就自動啟用。",
  superseded: "這是舊版快取副本；通常有較新版本存在，不能假定它會被實際載入。",
  not_installed: "這是市集可取得的副本，目前尚未安裝到工具的載入範圍。",
  not_loaded: "它隨套件附帶，但不在工具的技能載入路徑。",
  archived: "它位於備份、暫存或封存位置，不是可使用的載入副本。",
  unknown: "掃描到檔案，但現有設定不足以確認工具是否會載入它。",
};
function helpTip(label, hint) {
  return el("span", { class: "armory-tip", "data-tip": hint,
    "aria-label": `${label}說明：${hint}`, tabindex: "0" }, "ⓘ");
}
function activationWithHelp(a) {
  const [label] = ACT[a] || ACT.unknown;
  return el("span", { class: "status-help" }, actBadge(a), helpTip(label, ACT_HELP[a] || ACT_HELP.unknown));
}
// One line on how VBear knows: the arbitrated reason, and which evidence
// decided it. Every state shown carries its source (AGENTS.md: truthful UI).
function activityBasis(act) {
  if (!act) return "沒有任何狀態證據，無法判斷 Agent 是否在工作或等你回覆";
  const decided = (act.evidence || []).find((e) => e.rung === act.decided_by);
  const basis = decided ? `依據：${decided.label}` : "沒有可採用的證據";
  return [act.reason, basis].filter(Boolean).join("｜");
}
function statusBadge(s, act) {
  const [l, c] = STATUS[s] || STATUS.unknown;
  return badge(l, c, activityBasis(act));
}
function toolTag(t) { return el("span", { class: "tag" }, TOOL[t] || t || "未知工具"); }
function prov(src) {
  const origin = (src && src.origin) || "missing";
  const [label, explain] = PROV[origin] || PROV.missing;
  return el("span", { class: `prov ${origin}`, title: `${explain}${src && src.detail ? "｜" + src.detail : ""}` },
    el("b", null, label), src && src.detail ? el("span", null, "· " + src.detail) : null);
}
function fmtTime(v) {
  if (!v) return "—";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  if (isNaN(d)) return "—";
  return d.toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function ago(v) {
  if (!v) return "";
  const t = typeof v === "number" ? v * 1000 : Date.parse(v);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return "剛剛";
  if (s < 3600) return `${Math.round(s / 60)} 分鐘前`;
  if (s < 86400) return `${Math.round(s / 3600)} 小時前`;
  return `${Math.round(s / 86400)} 天前`;
}
function firstSentence(text, max = 150) {
  if (!text) return "";
  const t = String(text).replace(/\s+/g, " ").trim();
  const m = t.match(/^(.{20,}?[。．.!?！？])(\s|$)/);
  const s = m ? m[1] : t;
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}
function home(p) { return p ? String(p).replace(/^\/Users\/[^/]+|^\/home\/[^/]+/, "~") : ""; }
function modelList(models) {
  const entries = Object.entries(models || {}).sort((a, b) => b[1] - a[1]);
  return entries.map(([m]) => m);
}
function initialOf(name) { const c = String(name || "?").trim().replace(/^[^\p{L}\p{N}]+/u, ""); return (c[0] || "?").toUpperCase(); }

// ---------- skill translations (text only, separate from author facts) ------
const T = { entries: {}, counts: {}, job: null, engine: "claude", error: null, loaded: false, listeners: new Set(),
  attempts: {}, ui: { seen: null, seenAt: 0, opened: null } };

function translationOf(id) { return T.entries[id] || { state: "none", entry: null }; }
function translationDescription(s) {
  const t = translationOf(s.skill_id);
  return t.entry ? t.entry.description_zh : (s.description && s.description.value) || "";
}
// The last single-skill job, when it failed and was started from this card (T.attempts); nothing is said about a card
// whose job this page did not start, because the job does not name its skill.
function translationFailureFor(id) {
  const job = T.job;
  if (!job || job.status !== "failed" || T.attempts[job.id] !== id) return null;
  return { message: job.error && job.error.message ? job.error.message : "原因不明" };
}
// What a skill says about itself in the picker: its Chinese "what it does" when a translation exists (marked as machine
// translation, and 過期 when the original changed since), otherwise the original excerpt. -> { zh, text, badge }.
function skillPickText(s) {
  const t = s && s.skill_id ? translationOf(s.skill_id) : { entry: null };
  if (t.entry && t.entry.description_zh) {
    return { zh: true, text: firstSentence(t.entry.description_zh, 90),
      badge: badge(t.state === "stale" ? "過期" : "機器翻譯", t.state === "stale" ? "b-warn" : "b-info",
        t.state === "stale" ? "原文改過，這段翻譯可能已經不準；看原文確認" : "機器翻譯，內容未經 VBear 驗證") };
  }
  return { zh: false, text: s && s.excerpt ? String(s.excerpt) : "", badge: null };
}
function translationBadge(id) {
  const t = translationOf(id);
  return t.entry ? badge(t.state === "stale" ? "機器翻譯 · 過期" : "機器翻譯", t.state === "stale" ? "b-warn" : "b-info",
    `${t.entry.engine} ${t.entry.model} · ${fmtTime(t.entry.created_at)}；內容未經 VBear 驗證`) : null;
}
function translationDisclosure(count, engine = T.engine, automatic = false) {
  const budget = engine === "claude"
    ? `Claude 請求預算每項 US$0.05，${count} 項合計 US$${(count * 0.05).toFixed(2)}；CLI 在回合結束檢查，這不是保證帳單上限。`
    : "Codex 費用上限未知。";
  return `將 ${count} 個技能的作者說明欄位送到本機已登入的 ${engine} CLI，可能消耗該帳號的額度或產生費用。${budget} Token 消耗未知。每項最多 60 秒，總等待上限約 ${count} 分鐘（不是速度預測）。` +
    (automatic ? "開啟後，每次重新掃描最多自動翻譯 20 個，其餘等待下一次掃描；可在設定關閉，並以全域進度列立即停止。" : "可從全域進度列取消。") +
    "原文與翻譯都不是指令，不會載入或執行技能。";
}
// The short sentence of a translation confirmation (design card-play 3.4); translationDisclosure stays whole behind 「詳細」.
// Only the Claude price is stated: Haiku through your own account is cents at most, and the budget limit is in the details.
// Codex has no such figure, so it says so.
function translationSummary(count, engine = T.engine, automatic = false) {
  if (automatic) {
    return engine === "claude"
      ? "開啟後，每次重新掃描最多會自動翻譯 20 張技能卡，用你自己的 Claude 帳號，每張通常不到 1 美分；可以隨時在設定關閉。"
      : "開啟後，每次重新掃描最多會自動翻譯 20 張技能卡，用你自己的 Codex 帳號，費用上限未知；可以隨時在設定關閉。";
  }
  const what = count === 1 ? "這張技能卡" : `這 ${count} 張技能卡`;
  return engine === "claude"
    ? `會用你自己的 Claude 帳號翻譯${what}，${count === 1 ? "" : "每張"}通常不到 1 美分。`
    : `會用你自己的 Codex 帳號翻譯${what}，費用上限未知。`;
}
async function refreshTranslations() {
  try {
    const data = await api.get("/api/translations");
    if (!data || !data.entries) throw new Error("翻譯狀態未知");
    Object.assign(T, data, { loaded: true, error: null });
  } catch (e) { T.error = e.message || "翻譯狀態未知"; }
  renderTranslationActivity();
  for (const listener of [...T.listeners]) listener();
}
// The bottom bar of the translation job (design card-play 3.4). A finished job does not stay: success folds away after
// 5 seconds; a failure stays 10 seconds, then becomes a small dot at the lower right that opens the reason again. A
// running job stays until it ends. Every state has a close button; the id of a job that was closed is kept, so it does not
// come back when the page is opened again. translationBarState decides, from what it is given, so it can be tested.
const TRANSLATION_BAR_OK_MS = 5000;
const TRANSLATION_BAR_FAIL_MS = 10000;
function translationBarState({ job, error, seen, seenAt, opened, closed, now }) {
  if (error) return error === closed ? { view: "hidden", kind: "unknown" } : { view: "bar", kind: "unknown" };
  if (!job || typeof job !== "object") return { view: "hidden", kind: "none" };
  if (job.id === closed) return { view: "hidden", kind: "closed" };
  if (["running", "cancelling"].includes(job.status)) return { view: "bar", kind: "running" };
  const age = seen === job.id ? Math.max(0, now - seenAt) : 0;
  if (job.status === "failed") {
    if (opened === job.id || age < TRANSLATION_BAR_FAIL_MS) return { view: "bar", kind: "failed" };
    return { view: "dot", kind: "failed" };
  }
  return age >= TRANSLATION_BAR_OK_MS ? { view: "hidden", kind: "done" } : { view: "bar", kind: "done" };
}
function closeTranslationBar(key) { store.set("translationClosed", key); renderTranslationActivity(); }
function renderTranslationActivity() {
  let box = document.getElementById("translation-activity");
  if (!box) {
    box = el("aside", { id: "translation-activity", class: "translation-activity", "aria-label": "技能翻譯進度" });
    document.body.append(box);
  }
  const job = T.job;
  const active = job && ["running", "cancelling"].includes(job.status);
  // the first time a finished job is seen, start its clock and come back when it is due to fold
  if (job && !active && !T.error && T.ui.seen !== job.id) {
    T.ui.seen = job.id;
    T.ui.seenAt = Date.now();
    setTimeout(renderTranslationActivity, (job.status === "failed" ? TRANSLATION_BAR_FAIL_MS : TRANSLATION_BAR_OK_MS) + 50);
  }
  const closed = store.get("translationClosed", null);
  const st = translationBarState({ job, error: T.error, seen: T.ui.seen, seenAt: T.ui.seenAt, opened: T.ui.opened, closed, now: Date.now() });
  const focused = box.contains(document.activeElement);
  box.hidden = st.view === "hidden";
  box.className = st.view === "dot" ? "translation-activity translation-dot" : "translation-activity";
  box.setAttribute("data-bar", st.view === "hidden" ? "hidden" : `${st.view}-${st.kind}`);
  if (st.view === "dot") {
    setKids(box, el("button", { class: "translation-dot-btn", type: "button", "aria-label": "翻譯有失敗，點開看原因", title: "翻譯有失敗，點開看原因",
      on: { click: () => { T.ui.opened = job.id; renderTranslationActivity(); } } }, "!"));
    return;
  }
  const status = job && ({ running: "翻譯中", cancelling: "正在停止", completed: "已結束", failed: "失敗", cancelled: "已取消" }[job.status] || "未知");
  const closeKey = T.error ? T.error : job ? job.id : null;
  setKids(box,
    el("span", { role: "status", "aria-live": "polite", "aria-atomic": "true" },
      T.error ? `翻譯狀態未知：${T.error}` : job ? `${job.automatic ? "自動重翻" : "技能翻譯"} ${status} · ${job.done}/${job.total} · 失敗 ${job.failed}` : ""),
    T.waiting ? el("span", { class: "small" }, `${T.waiting} 個等待下次掃描`) : null,
    job && job.error ? el("span", { class: "small", "data-bar": "reason" }, job.error.message) : null,
    active ? el("button", { class: "btn small", type: "button", "aria-disabled": String(job.status === "cancelling"),
      on: { click: async () => { if (job.status === "cancelling") return; await cancelTranslations(); } } }, "停止翻譯") : null,
    closeKey ? el("button", { class: "btn small", type: "button", "data-bar": "close", "aria-label": "關閉翻譯進度",
      on: { click: () => closeTranslationBar(closeKey) } }, "關閉") : null);
  if (focused && box.querySelector("button")) box.querySelector("button").focus();
}
async function cancelTranslations() {
  try { await api.post("/api/translations/batch/cancel", {}); await refreshTranslations(); }
  catch (e) { toast(e.message); }
}
async function startTranslation(id, which) {
  const count = id ? 1 : T.counts[which] || 0;
  if (!count || T.error) return;
  if (!(await confirmInPage("確認送出技能說明", translationSummary(count), "翻成中文", { details: translationDisclosure(count) }))) return;
  try {
    if (id) {
      const r = await api.post(`/api/skills/${encodeURIComponent(id)}/translate`, {});
      // remember which card this job was for, so a failure can be said on that very card
      if (r && r.job && typeof r.job.id === "string") T.attempts[r.job.id] = id;
    } else await api.post("/api/translations/batch", { which });
    await refreshTranslations();
  } catch (e) { toast("無法翻譯：" + e.message); }
}
function translationPanel(id, original) {
  const box = el("section", { class: "translation-panel", "aria-label": "技能中文化" });
  let showOriginal = false;
  let initial = true, signature = "";
  const draw = () => {
    if (!initial && !document.body.contains(box)) { T.listeners.delete(draw); return; }
    initial = false;
    const nextSignature = JSON.stringify([translationOf(id), T.error, T.engine, T.job, showOriginal, translationFailureFor(id)]);
    if (nextSignature === signature) return;
    signature = nextSignature;
    const focused = box.contains(document.activeElement);
    const focusedAction = focused && document.activeElement.getAttribute("data-translation-action");
    const t = translationOf(id), e = t.entry;
    const running = T.job && ["running", "cancelling"].includes(T.job.status);
    const failure = running ? null : translationFailureFor(id);
    const originalView = el("div", { class: "translation-original" }, original);
    originalView.hidden = !!e && !showOriginal;
    setKids(box,
      T.error ? notice("warn", "翻譯狀態未知：" + T.error) : null,
      failure ? el("div", { class: "translation-failure notice warn", "data-translation": "failure" },
        el("span", null, "暫時無法翻譯，原文已保留"), " · ",
        el("button", { class: "btn small", type: "button", "data-translation-action": "retry", on: { click: () => { if (!T.error) startTranslation(id); } } }, "重試"), " · ",
        el("details", { class: "translation-failure-why" }, el("summary", null, "原因"), el("p", { class: "small" }, failure.message))) : null,
      t.state === "stale" ? notice("warn", `原文已變更，舊翻譯可能過期；上次翻譯：${fmtTime(e.created_at)}。請重新翻譯。`) : null,
      e ? translationBadge(id) : null,
      e && !showOriginal ? el("div", { class: "translation-summary" },
        el("h3", null, "中文重點（機器整理，未經驗證）"),
        [["做什麼", "what"], ["何時用", "when"], ["需要什麼", "needs"]].map(([label, key]) =>
          el("p", { class: e.summary[key] === "原文未提供" ? "muted" : null },
            el("strong", null, label + "："), e.summary[key] === "原文未提供" ? "作者未提供此資訊" : e.summary[key])),
        el("p", null, e.description_zh)) : null,
      e ? el("button", { class: "btn small", type: "button", "data-translation-action": "original", "aria-expanded": String(showOriginal), on: { click: () => {
        showOriginal = !showOriginal; draw(); box.querySelector("button").focus();
      } } }, showOriginal ? "返回中文整理" : "看英文原文") : null,
      originalView,
      el("div", { class: "translation-actions" },
        el("button", { class: "btn small", type: "button", "data-translation-action": "translate", "aria-disabled": String(!!running || !!T.error),
          "aria-busy": String(!!running), on: { click: () => { if (!running && !T.error) startTranslation(id); } } },
          running ? "翻譯中…" : e ? "重新翻譯" : "翻成中文"),
        running ? el("button", { class: "btn small", type: "button", "data-translation-action": "cancel", on: { click: cancelTranslations } }, "取消翻譯工作") : null,
        el("span", { class: "small muted" }, `說明文字會送到 ${T.engine}，消耗你的 CLI 帳號額度。`)),
      T.provider === "version_required" ? el("div", { class: "small muted" },
        T.engine === "claude" ? "翻譯前會核對版本；若未通過：這個 Claude Code 版本的翻譯安全邊界還沒驗證。" : "Codex 翻譯安全邊界尚未驗證，目前會拒絕啟動。",
        T.engine === "claude" ? el("button", { class: "btn small", type: "button", on: { click: verifyTranslationBoundary } }, "驗證") : null) : null,
      T.provider === "fake" ? el("p", { class: "small muted" }, "QA 假 CLI 情境：不會呼叫真實模型。") : null);
    if (focused) {
      const target = Array.from(box.querySelectorAll("button")).find(b => b.getAttribute("data-translation-action") === focusedAction);
      (target || box.querySelector("button")).focus();
    }
  };
  T.listeners.add(draw);
  draw();
  return box;
}
function translationToolbar() {
  const box = el("section", { class: "translation-toolbar", "aria-label": "技能庫中文化" });
  let signature = "";
  const draw = () => {
    if (!document.body.contains(box) && !box._translationInitial) { T.listeners.delete(draw); return; }
    box._translationInitial = false;
    const nextSignature = JSON.stringify([T.counts, T.error]);
    if (signature === nextSignature) return;
    signature = nextSignature;
    const details = box.querySelector("details"), expanded = details && details.open;
    const focused = box.contains(document.activeElement);
    const c = T.counts;
    setKids(box,
      el("p", { class: "small", role: "status" }, T.error ? "中文化狀態未知：" + T.error :
        `中文化：已翻 ${c.fresh || 0} · 過期 ${c.stale || 0} · 未翻 ${c.none || 0}`),
      el("details", null, el("summary", null, "批次翻譯"), el("div", { class: "translation-actions" },
        [["stale", "重新翻譯所有過期的"], ["none", "翻譯全部未翻的"]].map(([which, label]) =>
          el("button", { class: "btn small", type: "button", on: { click: () => startTranslation(null, which) } }, `${label}（${c[which] || 0}）`)))));
    box.querySelector("details").open = !!expanded;
    if (focused) box.querySelector("button").focus();
  };
  box._translationInitial = true;
  T.listeners.add(draw); draw(); return box;
}
async function verifyTranslationBoundary() {
  if (!(await confirmInPage("驗證翻譯安全邊界", "會用你自己的 Claude 帳號做一次小型檢查，通常不到 1 美分。", "驗證",
    { details: "將用固定的無害提示檢查目前 Claude Code 版本是否只有 StructuredOutput、沒有 MCP。會花極少量額度；請求預算 US$0.05，這不是保證帳單上限。" }))) return;
  try {
    const result = await api.post("/api/translations/verify", {});
    toast(`Claude Code ${result.version} 翻譯安全邊界驗證通過；翻譯前仍會核對版本。`);
    await refreshTranslations();
  } catch (e) { toast("驗證失敗：" + e.message); }
}
function translationSettings(conf, saveConf) {
  const engine = el("select", { "aria-label": "翻譯引擎", on: { change: async () => {
    const result = await saveConf({ translation_engine: engine.value });
    if (result) { conf = result.config; auto.checked = !!conf.translation_auto; await refreshTranslations(); viewSettings(); }
    else engine.value = conf.translation_engine || "claude";
  } } }, [["claude", "Claude Code（Haiku）"], ["codex", "Codex"]].map(([v, label]) =>
    el("option", { value: v, selected: v === (conf.translation_engine || "claude") }, label)));
  const auto = el("input", { type: "checkbox", checked: !!conf.translation_auto, on: { change: async () => {
    const wanted = auto.checked;
    if (wanted && !(await confirmInPage("開啟原文變更時自動重翻", translationSummary(20, engine.value, true), "同意並開啟",
      { details: translationDisclosure(20, engine.value, true) }))) {
      auto.checked = false; return;
    }
    const result = await saveConf({ translation_auto: wanted, translation_consent_engine: engine.value });
    if (result) { conf = result.config; await refreshTranslations(); }
    auto.checked = !!conf.translation_auto;
  } } });
  return el("section", { class: "panel pad translation-settings" }, el("h2", null, "技能中文化"),
    el("label", null, "使用自己的本機 CLI：", engine),
    el("label", { class: "switch" }, auto, el("span", null, "原文變更時自動重翻（預設關閉）")),
    el("p", { class: "small muted" }, "第一次開啟需確認資料送出、額度與費用。更換引擎會關閉自動重翻，請重新同意。關閉時也會停止目前工作。"),
    el("p", null, `孤兒翻譯：${T.error ? "未知" : T.counts.orphan || 0}`),
    el("button", { class: "btn small", type: "button", on: { click: async () => {
      if (T.error) return;
      if (!(await confirmInPage("檢查孤兒翻譯", `目前有 ${T.counts.orphan || 0} 個索引已找不到的翻譯；只清除快取，不會刪除技能。`, "繼續"))) return;
      if (!(await confirmInPage("最後確認", "確定清除目前索引裡不存在的翻譯快取？", "清除"))) return;
      try { await api.del("/api/translations/orphans"); await refreshTranslations(); viewSettings(); }
      catch (e) { toast(e.message); }
    } } }, "清除孤兒翻譯"),
    el("p", { class: "small muted" }, T.provider === "fake" ? "QA 假 CLI；不打真模型。" : "翻譯前會核對版本。若未通過：這個 Claude Code 版本的翻譯安全邊界還沒驗證。Codex 翻譯仍未開放。"),
    el("p", { class: "small muted" }, "驗證會花極少量額度，只送固定的無害提示，不送技能資料。"),
    conf.translation_engine === "claude" ? el("button", { class: "btn small", type: "button", on: { click: verifyTranslationBoundary } }, "驗證") : null);
}

// ---------- data -----------------------------------------------------------

const D = { overview: null, skills: null, categories: [], roles: null, live: null, config: null, byId: new Map() };

async function loadStatic(force) {
  if (force || !D.overview) D.overview = await api.get("/api/overview");
  if (force || !D.skills) {
    const r = await api.get("/api/skills");
    D.skills = r.skills; D.categories = r.categories || [];
    D.byId = new Map(D.skills.map((s) => [s.skill_id, s]));
  }
  if (force || !D.roles) D.roles = (await api.get("/api/roles")).roles;
  renderScanStatus();
}
async function loadFlows() {
  try { D.flows = await api.get("/api/flows"); }
  catch (e) { D.flows = { error: e.message, flows: [] }; }
  return D.flows;
}

async function loadLive(force, timeoutMs) {
  try { D.live = await api.get("/api/live" + (force ? "?force=1" : ""), { timeoutMs }); }
  catch (e) { D.live = { error: e.message, sessions: [], projects: [], attention: [], usage: { sessions: [] }, runtime: { available: false, problems: [e.message] } }; }
  return D.live;
}

function renderScanStatus() {
  const box = document.getElementById("scan-status");
  if (!box || !D.overview) return;
  setKids(box, 
    el("div", { class: D.overview.stale ? "stale" : null }, `索引更新於 ${ago(D.overview.generated_at)}`, D.overview.stale ? "（已過期）" : ""),
    el("div", null, `${D.overview.totals.active} 個可使用技能`),
    el("button", { class: "btn small", on: { click: rescan } }, "重新掃描"),
  );
}

async function rescan(ev) {
  const btn = ev && ev.currentTarget;
  if (btn) btn.disabled = true;
  try {
    const r = await api.post("/api/rescan");
    await loadStatic(true);
    await loadLive(true);
    toast(`掃描完成（${r.scan_seconds} 秒）`);
    route();
  } catch (e) { toast("掃描失敗：" + e.message); }
  finally { if (btn) btn.disabled = false; }
}

// ---------- search ---------------------------------------------------------

function norm(s) { return String(s || "").toLowerCase(); }
function ann(s) { return s.annotation || {}; }
function displayName(s) { return (ann(s).aliases || [])[0] || s.name; }

function searchSkills(query, pool) {
  const q = norm(query).trim();
  if (!q) return pool.map((s) => ({ s, score: 0, why: [] }));
  const terms = q.split(/[\s,，、]+/).filter(Boolean);
  const catHits = new Set();
  for (const cat of D.categories) {
    if (norm(cat.label).includes(q) || cat.query.some((w) => q.includes(norm(w)) || terms.includes(norm(w)))) catHits.add(cat.id);
  }
  // A category hit counts more when the category is small: "資安" (a few
  // skills) says more about intent than "網站" (many).
  const catSize = new Map();
  for (const s of D.skills) if (s.activation === "active") for (const c of s.categories || []) catSize.set(c.id, (catSize.get(c.id) || 0) + 1);
  const activeTotal = D.skills.filter((s) => s.activation === "active").length || 1;
  const catWeight = (id) => Math.round(20 * (1 + Math.log(activeTotal / Math.max(1, catSize.get(id) || 1))));
  const out = [];
  for (const s of pool) {
    const name = norm(s.name), inv = norm(s.invoke_name);
    const desc = norm(s.description && s.description.value);
    const when = norm(s.when_to_use && s.when_to_use.value);
    const translated = translationOf(s.skill_id);
    const translationText = norm(translated.entry ? [translated.entry.description_zh, ...Object.values(translated.entry.summary)].join(" ") : "");
    let score = 0; const why = [];
    const a = ann(s);
    const aliases = (a.aliases || []).map(norm), tags = (a.tags || []).map(norm), note = norm(a.note);
    if (aliases.some((x) => x === q)) { score += 120; why.push("我的別名"); }
    if (tags.some((x) => x === q)) { score += 60; why.push("我的標籤"); }
    for (const t of terms) {
      if (aliases.some((x) => x.includes(t))) { score += 45; why.push("我的別名"); }
      if (tags.some((x) => x.includes(t))) { score += 30; why.push("我的標籤"); }
      if (note.includes(t)) { score += 10; why.push("我的備註"); }
      if (name === t || inv === t) { score += 100; why.push("名稱相符"); }
      else if (name.includes(t) || inv.includes(t)) { score += 40; why.push("名稱包含"); }
      if (desc.includes(t)) { score += 18; why.push("用途描述"); }
      if (when.includes(t)) { score += 8; why.push("使用時機"); }
      if (translationText.includes(t)) { score += 16; why.push(translated.state === "stale" ? "過期機器翻譯" : "機器翻譯"); }
    }
    for (const c of s.categories || []) if (catHits.has(c.id)) { score += catWeight(c.id); why.push(`用途：${c.label}`); }
    if (score > 0) out.push({ s, score: score + (s.activation === "active" ? 5 : 0), why: [...new Set(why)] });
  }
  return out.sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name));
}

// ---------- components -----------------------------------------------------

function skillCard(s, why) {
  const dups = (s.duplicate_of || []).length;
  return el("a", { class: "card", href: `#/skills/${s.skill_id}` },
    el("div", { class: "card-top" },
      el("div", { style: "min-width:0" },
        el("div", { class: "card-title" }, displayName(s)),
        el("div", { class: "card-sub mono" }, displayName(s) !== s.name ? `原名 ${s.invoke_name}` : s.invoke_name !== s.name ? `呼叫名稱 ${s.invoke_name}` : SCOPE[s.scope] || s.scope)),
      activationWithHelp(s.activation)),
    translationBadge(s.skill_id),
    translationDescription(s)
      ? el("p", { class: "clamp" }, firstSentence(translationDescription(s), 170))
      : el("p", { class: "muted" }, "作者沒有提供用途描述"),
    (ann(s).tags || []).length ? el("div", { class: "chips" }, ann(s).tags.map((t) => el("span", { class: "tag mine", title: "我的標籤" }, "#" + t))) : null,
    el("div", { class: "chips" },
      toolTag(s.tool),
      el("span", { class: "tag" }, SCOPE[s.scope] || s.scope),
      (s.categories || []).slice(0, 2).map((c) => el("span", { class: "tag cat", title: `自動分類：描述中出現「${c.keyword}」` }, c.label)),
      dups ? badge(`同名 ${dups + 1} 份`, "b-warn", "有其他來源使用相同名稱，詳情頁可比較") : null,
      (s.missing_files || []).length ? badge("引用檔缺失", "b-bad", s.missing_files.join(", ")) : null),
    why && why.length ? el("div", { class: "card-sub" }, "符合：" + why.join("、")) : null);
}

function sessionCard(x) {
  const models = modelList(x.models_observed);
  const used = (x.skills_used || []).slice(0, 4);
  const project = (D.live.projects || []).find((p) => p.project_id === x.project_id);
  return el("div", { class: "card" },
    el("div", { class: "card-top" },
      el("div", { class: "who" },
        el("div", { class: "avatar", "aria-hidden": "true" }, initialOf(x.role_label || x.agent)),
        el("div", null,
          el("div", { class: "card-title" }, x.role_label || `${TOOL[x.agent] || x.agent} 工作階段`),
          el("div", { class: "card-sub" }, x.role_label_source ? "角色名稱來自分頁名稱" : "未命名"))),
      statusBadge(x.status, x.activity)),
    x.title ? el("p", { class: "clamp" }, x.title) : null,
    el("dl", { class: "kv small" },
      el("dt", null, "執行工具"), el("dd", null, TOOL[x.agent] || x.agent || "未知"),
      el("dt", null, "狀態依據"), el("dd", { class: "small" }, activityBasis(x.activity)),
      el("dt", null, "本次模型"), el("dd", null,
        models.length ? [models.join("、"), " ", prov({ origin: "runtime", detail: "對話紀錄" })]
          : el("span", { class: "muted" }, x.supported_tool ? (x.usage_matched ? "紀錄中沒有模型資訊" : "找不到對應的對話紀錄") : "此工具不提供可讀紀錄")),
      el("dt", null, "專案"), el("dd", null, project ? el("a", { href: `#/projects/${project.project_id}` }, project.name) : "—"),
      el("dt", null, "本次用過的技能"), el("dd", null,
        used.length ? el("div", { class: "chips" }, used.map((u) => usedChip(u)))
          : el("span", { class: "muted" }, x.usage_matched ? "紀錄中沒有技能使用" : "無紀錄可查"))),
    el("div", { class: "row" },
      el("span", { class: "small muted mono" }, `${x.workspace_label || x.workspace_id} · ${x.pane_id}`),
      el("span", { class: "spacer" }),
      el("a", { class: "btn small primary", href: `#/term/${encodeURIComponent(x.pane_id)}`, title: "開啟終端機串流（預設僅觀看）" }, "開啟終端")));
}

function usedChip(u) {
  const [label, cls, explain] = EVIDENCE[u.evidence] || ["使用紀錄", "b-mute", ""];
  const target = u.skill_ids && u.skill_ids[0];
  const text = `${u.label}${u.count > 1 ? ` ×${u.count}` : ""}`;
  const title = `${label}：${explain}${u.resolution === "ambiguous" ? "（對應到多份同名技能）" : ""}${u.resolution === "unresolved" ? "（索引中找不到對應的技能檔）" : ""}`;
  return target
    ? el("a", { class: `badge ${cls}`, href: `#/skills/${target}`, title }, text)
    : el("span", { class: `badge ${cls}`, title }, text);
}

// Native runtime sessions (pane ids "n-" + 12 hex) can be closed from the
// console. Closing a Profile-managed session also removes its scratch and
// settings once every one of its processes is proven gone; otherwise they are
// kept for review, and the toast says so.
const NATIVE_SESSION_RE = /^n-[0-9a-f]{12}$/;

// In-page confirmation (not window.confirm): a native browser dialog blocks
// the page and cannot be driven by browser automation, which left the close
// button unverifiable in acceptance. Resolves true only on the confirm button.
// opts.details: the long print, kept whole behind a 「詳細」 fold under the short sentence.
function confirmInPage(title, message, confirmLabel, opts = {}) {
  return new Promise((resolve) => {
    const titleId = "modal-confirm-title";
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    const confirmBtn = el("button", { class: "btn primary", type: "button", on: { click: () => finish(true) } }, confirmLabel);
    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => finish(false) } }, "取消");
    const modalElem = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
      el("div", { class: "modal-box" },
        el("h2", { id: titleId }, title),
        el("p", null, message),
        opts && typeof opts.details === "string" && opts.details
          ? el("details", { class: "confirm-details", "data-confirm": "details" }, el("summary", null, "詳細"), el("p", { class: "small" }, opts.details)) : null,
        el("div", { class: "modal-actions" }, cancelBtn, confirmBtn)));
    document.body.append(modalElem);
    // Escape or a view teardown closes the dialog through this teardown: that is a "no".
    const closeModal = withModalA11y(modalElem, () => {
      modalElem.remove();
      if (!settled) { settled = true; resolve(false); }
    });
    cancelBtn.focus();
  });
}
// ---- Skill card (design game-ui 4.2) -----------------------------------------------------------------------
// One dialog for the workbench's role card and the Armory. Its data is GET /api/skills/<id>?view=card, which
// answers from what is already loaded. Every string is set as text; a field that was not provided says so.
function skillObservationText(o) {
  const period = o && typeof o.window_days === "number" ? `最近 ${o.window_days} 天` : "觀察期間：未知";
  if (o && o.state === "observed") return `觀察期間內有紀錄（${period}；來源：執行觀察）`;
  if (o && o.state === "none") return `目前沒有觀察紀錄（${period}；來源：執行觀察）。這不代表沒有用過。`;
  return `觀察資料不可用（${period}；來源：執行觀察）`;
}

// What to say about a skill's installed state: only a not_installed copy is "not installed"; any other state
// that is not an installed one (unknown, archived, not loaded...) is named with its reason, not inferred.
function skillStatusText(sk) {
  const act = sk && sk.activation;
  const label = (ACT[act] || [])[0] || act || "未提供";
  const reason = sk && sk.activation_reason ? "：" + sk.activation_reason : "";
  if (sk && sk.installed) return `已安裝（${label}）${reason}`;
  if (act === "not_installed") return `沒有安裝在這台 Mac（市集上的副本）${reason}`;
  return `${label}${reason}`;
}

// The five armor groups and the level words each holds (agent_launch.ARMOR_GROUPS / ARMOR_GROUP_LEVELS; a test
// compares this table with the server's). Only a frame: the level words and notes are always shown as they are.
const ARMOR_GROUPS_UI = [
  { id: "blocked", label: "擋住了", levels: ["強制（限已測路徑、版本與執行層）"] },
  { id: "partial", label: "部分擋住", levels: ["部分強制"] },
  { id: "not_granted", label: "沒有專用權限", levels: ["不授予"] },
  { id: "not_blocked", label: "沒有擋", levels: ["僅意圖", "未限制"] },
  { id: "unproven", label: "未證明", levels: ["未驗證（此 Claude Code 版本尚未實測）", "未知"] },
];
// A level this table does not know is put in the last group (not proven), never in a protective one.
function armorGroupOf(level) {
  const g = ARMOR_GROUPS_UI.find((x) => x.levels.includes(level));
  return g ? g.id : "unproven";
}

function skillCardField(label, src, extra) {
  const v = src && src.value;
  const has = !(v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length));
  return el("div", { class: "sc-field" },
    el("div", { class: "sc-label" }, label),
    el("div", { class: "sc-value" }, has ? (Array.isArray(v) ? v.map(String).join("、") : String(v)) : null,
      has ? " " : null, prov(src)),
    extra || null);
}

// opts: { profile } when it is opened from a role card (adds 「從這個角色移除」), { onChanged } after a change.
async function openSkillCard(skillId, opts = {}) {
  const titleId = "modal-skill-card-title";
  const body = el("div", { class: "sc-body" }, el("p", { class: "loading" }, "載入技能卡…"));
  const actions = el("div", { class: "modal-actions" });
  const modalElem = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    el("div", { class: "modal-box sc-box" },
      el("h2", { id: titleId }, "技能卡"), body, actions));
  document.body.append(modalElem);
  const closeModal = withModalA11y(modalElem, () => { modalElem.remove(); });
  const backBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "返回");
  setKids(actions, backBtn);
  backBtn.focus();
  let d;
  try {
    await refreshTranslations();
    d = await api.get(`/api/skills/${encodeURIComponent(skillId)}?view=card`);
  } catch (e) {
    setKids(body, notice("bad", "無法顯示技能卡：" + (e && e.message ? e.message : "未知錯誤")));
    return;
  }
  const sk = d.skill || {};
  const refs = sk.referenced_files || {};
  const roles = (d.added_to_roles && d.added_to_roles.items) || [];
  const scopeSrc = sk.scope ? { ...sk.scope, value: SCOPE[sk.scope.value] || sk.scope.value } : null;
  const nameValue = sk.name && typeof sk.name === "object" ? sk.name.value : sk.name;
  const nameText = nameValue ? String(nameValue) : `未提供（ID：${skillId}）`;
  const nameSrc = sk.name && typeof sk.name === "object" ? sk.name : { origin: "missing", detail: "" };
  const listOf = (x) => (x && Array.isArray(x.items) ? x.items : Array.isArray(x) ? x : []);
  const missingFiles = listOf(sk.missing_files);
  const warnings = listOf(sk.warnings);
  const fixed = d.effect_note || "效果是作者的描述，不是 VBear 驗證過的能力，只適用於你自己啟動並載入這張技能的工具";
  setKids(body,
    el("div", { class: "sc-head" },
      el("strong", { class: "sc-name" }, nameText),
      prov(nameSrc),
      badge("本次不生效", "b-mute", "VBear 啟動角色時不會載入這張技能卡")),
    notice("info", fixed),
    skillCardField("類別", sk.categories),
    skillCardField("陣營", sk.tool),
    skillCardField("來源（位置）", scopeSrc),
    translationPanel(skillId, el("div", null,
    skillCardField("效果（技能作者的說明）", sk.description),
    skillCardField("發動時機", sk.when_to_use),
    skillCardField("需要（輸入）", sk.inputs),
    skillCardField("產出", sk.outputs),
    skillCardField("依賴", sk.dependencies))),
    el("div", { class: "sc-field" },
      el("div", { class: "sc-label" }, "引用的檔案"),
      el("div", { class: "sc-value" },
        `共 ${refs.count ?? "未提供"} 個；${refs.note || "VBear 不會執行這些檔案"} `, prov(refs),
        (refs.items || []).length ? el("ul", { class: "sc-refs" }, refs.items.map((r) =>
          el("li", null, el("span", { class: "mono" }, String(r.ref)), " ",
            el("span", { class: "muted" }, r.status === "present" ? "存在" : r.status === "missing" ? "缺少" : "非套件檔案"))))
          : null,
        refs.truncated ? el("p", { class: "rc-note" }, "清單過長，只列出前面的部分。") : null)),
    missingFiles.length ? notice("warn", ["缺少的檔案：" + missingFiles.join("、") + " ", prov(sk.missing_files)]) : null,
    warnings.length ? notice("warn", ["結構檢查：" + warnings.join("；") + " ", prov(sk.warnings)]) : null,
    el("div", { class: "sc-field" },
      el("div", { class: "sc-label" }, "這張卡的狀態"),
      el("ul", { class: "sc-status" },
        el("li", null, skillStatusText(sk) + " ", prov(sk.status_source)),
        el("li", null, ((d.added_to_roles && d.added_to_roles.unavailable)
          ? `已選入哪些角色：無法讀取（${d.added_to_roles.unavailable}）`
          : roles.length ? `已選入 ${roles.length} 個角色：${roles.map((r) => r.name || r.id).join("、")}（本次不生效）`
          : "沒有角色選入這張技能") + " ", prov(d.added_to_roles)),
        el("li", null, "觀察狀態：" + skillObservationText(d.observation) + " ", prov(d.observation)),
        el("li", null, ((d.marketplace_copies || []).length
          ? `市集有其他副本（${d.marketplace_copies.length} 個，尚未安裝）` : "市集沒有找到其他副本") + " ",
          prov(d.marketplace_source)))));
  const kids = [];
  const profile = opts.profile;
  if (profile && (profile.equipped_skill_ids || []).includes(skillId)) {
    kids.push(el("button", { class: "btn", type: "button", on: { click: async () => {
      if (!(await confirmInPage("從這個角色移除",
        `把「${nameText}」從角色「${profile.name || profile.id}」的已選技能移除？這只會改你的挑選紀錄，不會刪除技能。`,
        "移除"))) return;
      try {
        const next = (profile.equipped_skill_ids || []).filter((x) => x !== skillId);
        await api.post(`/api/agent-profiles/${encodeURIComponent(profile.id)}`, { equipped_skill_ids: next });
        toast("已從角色移除");
        closeModal();
        if (typeof opts.onChanged === "function") await opts.onChanged();
      } catch (err) {
        toast("移除失敗：" + err.message);
      }
    } } }, "從這個角色移除"));
  }
  kids.push(el("a", { class: "btn", href: `#/skills/${encodeURIComponent(skillId)}`,
    on: { click: () => closeModal() } }, "打開技能檔案"));
  kids.push(backBtn);
  setKids(actions, ...kids);
}

// Plain-language names for the terminal-title checks of 「驗證這個版本」.
const TITLE_CHECK_TEXT = {
  idle_before_prompt: "送出提示前沒有出現閒置符號 ✳",
  working_after_prompt: "送出後沒有出現工作中的 ◐／◑",
  idle_after_turn: "回合結束後沒有回到 ✳",
  spinner_cadence: "工作中的標題更新間隔超過 5 秒",
  title_check_missing: "報告裡沒有標題檢查",
  not_checked: "那次沒有檢查標題",
};
function titleFailureText(names) {
  const list = Array.isArray(names) ? names : [];
  return list.map((n) => TITLE_CHECK_TEXT[n] || `其他（${n}）`).join("、") || "原因未知";
}

function closeSessionButton(paneId, afterHash = "#/team") {
  if (!NATIVE_SESSION_RE.test(paneId || "")) return null;
  const btn = el("button", { class: "btn small", type: "button",
    title: "結束這個終端裡的程式並關閉它",
    on: { click: async () => {
      if (!(await confirmInPage("關閉終端", "確定要關閉這個終端？裡面正在執行的程式會被結束。", "關閉終端"))) return;
      btn.disabled = true;
      try {
        const r = await api.post(`/api/native/sessions/${encodeURIComponent(paneId)}/close`, {});
        const m = r.managed;
        toast(!m ? "終端已關閉"
          : m.cleaned ? "終端已關閉，暫存區與設定已清除"
          : `終端已關閉；暫存區保留待檢查：${m.retained_reason || "原因未知"}`);
        if (location.hash === afterHash) route();  // no hashchange: re-render in place
        else if (!location.hash.startsWith("#/workbench")) location.hash = afterHash;
      } catch (e) {
        if (e.status === 404) {
          toast("這個終端已不存在或已結束");
          if (!location.hash.startsWith("#/workbench")) location.hash = afterHash;
          return;
        }
        toast("關閉失敗：" + e.message);
        btn.disabled = false;
      }
    } } }, "關閉終端");
  return btn;
}

function roleCard(r) {
  const skills = r.skills || [];
  return el("a", { class: "card", href: `#/team/role/${r.role_id}` },
    el("div", { class: "card-top" },
      el("div", { class: "who" },
        el("div", { class: "avatar", "aria-hidden": "true" }, r.emoji || initialOf(r.name)),
        el("div", null,
          el("div", { class: "card-title" }, r.name),
          el("div", { class: "card-sub" }, r.kind === "cli" ? "主代理（直接執行的工具）" : "子代理／角色設定"))),
      toolTag(r.tool)),
    r.description && r.description.value ? el("p", { class: "clamp" }, firstSentence(r.description.value, 160)) : el("p", { class: "muted" }, "沒有描述"),
    el("div", { class: "stat-line" },
      el("span", null, "預設模型 ", el("b", null, (r.model && r.model.value) || "未指定"),
        r.model && r.model.origin === "derived" ? el("span", { class: "muted", title: r.model.detail }, "（沿用全域預設）") : null),
      el("span", null, "可用技能 ", el("b", null, r.kind === "cli" || r.skill_link_basis === "declared" ? skills.length : "未宣告"))),
    (r.warnings || []).length ? el("div", { class: "chips" }, badge(r.warnings[0], "b-warn")) : null);
}

function emptyState(title, detail) {
  return el("div", { class: "empty-state" }, el("strong", null, title), detail ? el("span", null, detail) : null);
}
function notice(kind, text) {
  const ico = { warn: "!", info: "i", bad: "×" }[kind] || "i";
  return el("div", { class: `notice ${kind}`, role: kind === "bad" ? "alert" : "note" }, el("span", { class: "ico", "aria-hidden": "true" }, ico), el("div", null, text));
}
function staleNotice() {
  if (!D.overview || !D.overview.stale) return null;
  return el("div", { class: `notice warn`, role: "note" }, el("span", { class: "ico", "aria-hidden": "true" }, "!"),
    el("div", null, `技能索引已經 ${ago(D.overview.generated_at).replace("前", "")}沒有更新，新增、移除或升級的技能可能還沒反映。 `,
      el("button", { class: "btn small", on: { click: rescan } }, "立即重新掃描")));
}
function corruptNotice() {
  if (!D.overview || !D.overview.config_corrupt) return null;
  return notice("bad", "設定檔（config.json）無法讀取。你原本選的掃描範圍目前不明，所以主控台已關閉所有掃描來源，也不會重新掃描，畫面上是先前的索引。請修復或刪除 ~/.vbear/config.json 後重新啟動主控台；原檔不會被覆寫。");
}
function runtimeNotice() {
  const h = D.live && D.live.runtime;
  if (!h) return null;
  if (!h.available) return notice("warn", ["無法連線到 VBear runtime，終端的資訊暫時看不到。", (h.problems || []).join("；")].join(" "));
  return null;
}
// One-time notice after a Herdr-era config was switched to native (until acknowledged).
function herdrMigrationNotice() {
  if (!D.overview || !D.overview.herdr_migration_notice) return null;
  const ack = el("button", { class: "btn small", type: "button", on: { click: async () => {
    ack.disabled = true;
    try {
      await api.post("/api/config", { herdr_migration_acknowledged: true });
      D.overview.herdr_migration_notice = false;
      wrap.remove();
    } catch (e) { toast("無法儲存：" + e.message); ack.disabled = false; }
  } } }, "知道了");
  const wrap = el("div", { class: "notice info" },
    el("span", { class: "ico", "aria-hidden": "true" }, "i"),
    el("div", null, "主控台已改用內建的 VBear runtime，不再支援 Herdr，設定已自動切換。在 Herdr 或其他終端自行啟動的 Agent 不會出現在這裡；請從角色卡的「出發通行證」開啟。 ", ack));
  return wrap;
}
function sectionHead(title, sub, action) {
  return el("div", { class: "section-head" },
    el("div", null, el("h2", null, title), sub ? el("p", { class: "small muted" }, sub) : null), action || null);
}

// ---------- views ----------------------------------------------------------

async function viewHome() {
  const token = seq;
  // /api/flows reads live state from the cache /api/live fills, so live goes first.
  const [, , tasksRes, profilesRes, catalogRes, configRes] = await Promise.all([loadStatic(), loadLive().then(() => loadFlows()),
    api.get("/api/tasks").catch(() => null), api.get("/api/agent-profiles").catch(() => null),
    api.get("/api/agent-builder/catalog").catch(() => null), api.get("/api/config").catch(() => null)]);
  const L = D.live;
  const main = claim(token);
  const onboardingHost = el("div", { id: "h-onboarding" });
  const onboardingInput = () => ({
    profiles: profilesRes && Array.isArray(profilesRes.profiles) ? profilesRes.profiles : null,
    catalog: catalogRes && catalogRes.ok ? catalogRes : null,
    tasks: tasksRes && Array.isArray(tasksRes.tasks) ? tasksRes.tasks : null,
    flows: D.flows && !D.flows.error && Array.isArray(D.flows.flows) ? D.flows.flows : null,
    dismissed: configRes && configRes.config && typeof configRes.config.onboarding_dismissed === "boolean" ? configRes.config.onboarding_dismissed : null,
  });
  boardFirstGame = onboardingState(onboardingInput()).mode === "steps";
  const drawOnboarding = () => setKids(onboardingHost, onboardingSection(onboardingState(onboardingInput()), {
    onImport: () => openImportProject({ onCreated: () => route(), onOpenTask: (id) => { location.hash = `#/workbench?task=${encodeURIComponent(id)}`; } }),
    onDismiss: async () => {
      try {
        await api.post("/api/config", { onboarding_dismissed: true });
        configRes.config.onboarding_dismissed = true;
        drawOnboarding();
      } catch (e) { toast("沒有存成：" + e.message); }
    },
  }));
  drawOnboarding();
  const input = el("input", { type: "search", placeholder: "想做什麼？例如：網站安全檢查、做簡報、剪影片、部署…", "aria-label": "用途搜尋技能" });
  const results = el("div", { class: "grid", style: "margin-top:14px" });
  const runSearch = () => {
    const q = input.value.trim();
    if (!q) { setKids(results, ); return; }
    const hits = searchSkills(q, D.skills.filter((s) => s.activation === "active")).slice(0, 6);
    setKids(results, ...(hits.length ? hits.map((h) => skillCard(h.s, h.why)) : [emptyState("沒有找到可使用的技能", "試試別的說法，或到技能庫顯示全部來源")]),
      hits.length ? el("a", { class: "btn", href: `#/skills?q=${encodeURIComponent(q)}`, style: "align-self:start" }, "在技能庫看全部結果 →") : null);
  };
  const searchSoon = debounce(runSearch);
  input.addEventListener("input", searchSoon);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { searchSoon.cancel(); location.hash = `#/skills?q=${encodeURIComponent(input.value.trim())}`; } });
  const examples = ["網站安全", "做簡報", "剪影片", "部署網站", "寫小說", "設計品牌"];

  const board = boardGroups(L, D.flows);
  boardShownKey = boardKey(board, boardKeyContext());
  const recentProjects = (L.projects || []).filter((p) => p.live_session_ids.length || p.last_activity).slice(0, 6);
  const problemSkills = (D.overview.skills_with_problems || []).map((id) => D.byId.get(id)).filter(Boolean);

  setKids(main, 
    el("h1", null, "冒險者大廳"),
    el("p", { class: "lede" }, "這裡看哪些任務在等你、隊伍走到哪一步。"),
    corruptNotice(),
    staleNotice(),
    herdrMigrationNotice(),
    runtimeNotice(),
    onboardingHost,
    el("div", { id: "h-board" }, boardSection(board)),
    taskCardsSection(tasksRes && tasksRes.tasks, { flows: D.flows && !D.flows.error ? D.flows.flows || [] : undefined,
      profiles: profilesRes && Array.isArray(profilesRes.profiles) ? profilesRes.profiles : undefined,
      onCreated: () => route(), onOpenTask: (id) => { location.hash = `#/workbench?task=${encodeURIComponent(id)}`; } }),
    el("section", { class: "section" },
      sectionHead("找技能", "用你的話描述要做的事，不需要記得技能名稱"),
      el("div", { class: "search" }, input),
      el("div", { class: "search-hint" }, el("span", { class: "small muted" }, "試試："),
        examples.map((w) => el("button", { type: "button", on: { click: () => { input.value = w; searchSoon.now(); input.focus(); } } }, w))),
      results),
    el("section", { class: "section" },
      sectionHead("最近的專案", null, el("a", { class: "btn small", href: "#/projects" }, "全部專案")),
      recentProjects.length ? el("div", { class: "grid" }, recentProjects.map(projectCard)) : emptyState("最近沒有工作紀錄", null)),
    problemSkills.length ? el("section", { class: "section" },
      sectionHead("需要留意的技能", "可使用的技能中，結構檢查發現問題的項目"),
      el("div", { class: "grid" }, problemSkills.slice(0, 6).map((s) => skillCard(s)))) : null,
  );
  setTimeout(() => input.focus(), 0);
}

// ---------- the quest board (design lobby v1.2) ------------------------------------------------------------
// The home page's first block. Every card is data VBear already has; nothing here invents progress. The grouping
// is made only in boardGroups, from what the server says (f.attention is the server's own judgement, so the page
// never re-derives it from the phase); boardKey is made of exactly what the board shows, so a 5-second refresh
// repaints only when something visible changed.
const BOARD_IN_PROGRESS_MAX = 4;
let boardShownKey = null;
let boardFirstGame = false;   // set by the home page: the first game is still on, so the workbench button is not the main one

// Whether a flow is waiting for you: the server's own attention flag (it also covers a stopped automatic run and
// a stop at the merge gate, whatever the phase), or a stale review in a manual or stopped-automatic flow, where
// nothing will send it again by itself. One rule for the home board and the office.
function waitsForYou(f) {
  if (!f || f.attention === true) return !!f;
  const a = f.automation;
  return !!(f.phase && f.phase.key === "review_stale" && (!a || a.mode !== "auto" || a.held));
}

function boardGroups(live, flowsData) {
  const L = live || {};
  const runtimeAvailable = !!(L.runtime && L.runtime.available);
  const sessions = Array.isArray(L.sessions) ? L.sessions : [];
  const yourTurnSessions = (Array.isArray(L.attention) ? L.attention : [])
    .map((id) => sessions.find((s) => s.terminal_id === id)).filter(Boolean);
  let error = "";
  let flows = [];
  if (!flowsData) error = "還沒有讀取到流程";
  else if (flowsData.error) error = String(flowsData.error);
  else if (!Array.isArray(flowsData.flows)) error = "流程資料的格式無法辨識";
  else flows = flowsData.flows.filter((f) => f && typeof f === "object");
  // A finished flow is never on the board, even when the server still marks it as needing attention.
  const open = flows.filter((f) => !(f.phase && f.phase.key === "done"));
  const yourTurnFlows = open.filter(waitsForYou);
  const rest = open.filter((f) => !waitsForYou(f));
  return {
    error, yourTurnFlows, yourTurnSessions,
    inProgress: rest.slice(0, BOARD_IN_PROGRESS_MAX),
    moreInProgress: Math.max(0, rest.length - BOARD_IN_PROGRESS_MAX),
    runtimeAvailable,
    allEmpty: !error && flows.length === 0 && yourTurnSessions.length === 0 && runtimeAvailable,
  };
}

// The role cards a flow's team stands on, as far as the card shows them (avatar and name per place).
function boardTeamKey(f) {
  const r = f && f.roles && typeof f.roles === "object" ? f.roles : {};
  const one = (x) => (x ? [x.name || "", x.profile_id || "", teamCardTool(x)] : null);
  return [one(r.planner), one(r.executor), (Array.isArray(r.reviewers) ? r.reviewers : []).map(one)];
}

// What the key reads besides the groups: the live load's error (it rewords the executor column) and the
// projects (an agent card shows its project's name). The page passes them explicitly, so what the key is made
// of is visible at the call site.
function boardKeyContext() {
  return { liveError: liveLoadError(), projects: (D.live && D.live.projects) || [] };
}
// ctx is for the callers (the page passes boardKeyContext()) and for tests; without it the same values are read
// from the page's live data.
function boardKey(g, ctx) {
  const c = ctx || {};
  const liveError = c.liveError !== undefined ? c.liveError : liveLoadError();
  const projects = c.projects || (D.live && D.live.projects) || [];
  const flowFields = (f) => {
    const ph = f.phase || {};
    const a = f.automation || {};
    const r = f.latest_review;
    const roles = f.roles || {};
    const live = flowLiveText(f.executor_live, liveError);
    return [f.id, f.task_title, !!f.task_missing, ph.key, ph.label, ph.reason, f.attention === true, f.attention_reason || "",
      a.mode || "", !!a.held, a.step_label || "", roleText(roles.executor), (roles.reviewers || []).map(roleText),
      live.label, live.reason, r ? [r.verdict, !!r.counts_as_pass, r.commit, r.why || ""] : null,
      f.phase ? flowBindingNote(f) : "", nextStepSummary(f), boardTeamKey(f)];
  };
  const sessionFields = (x) => {
    const project = projects.find((p) => p.project_id === x.project_id);
    return [x.terminal_id, x.status, x.title || "", x.activity || null, x.role_label || "", x.role_label_source || "",
      x.agent || "", x.models_observed || null, x.skills_used || [], !!x.usage_matched, !!x.supported_tool,
      x.workspace_label || "", x.workspace_id || "", x.pane_id || "", x.project_id || "", project ? project.name : null];
  };
  return JSON.stringify({ error: g.error || "", runtime: !!g.runtimeAvailable, liveError: liveError || "",
    more: g.moreInProgress || 0, allEmpty: !!g.allEmpty,
    turn: g.yourTurnFlows.map(flowFields), sessions: g.yourTurnSessions.map(sessionFields),
    progress: g.inProgress.map(flowFields) });
}

// Inline SVG, drawn with the DOM (no innerHTML); decoration only, so it is hidden from assistive technology.
function questIcon(kind) {
  const NS = "http://www.w3.org/2000/svg";
  const make = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const svg = make("svg", { class: "quest-ico", viewBox: "0 0 24 24", width: "14", height: "14", fill: "none",
    stroke: "currentColor", "stroke-width": "2.4", "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true", focusable: "false" });
  svg.append(make("circle", { cx: "12", cy: "12", r: "9" }));
  if (kind === "turn") {   // an exclamation mark: it is your move
    svg.append(make("path", { d: "M12 7.5v5.5" }));
    svg.append(make("path", { d: "M12 16.4v.1" }));
  } else {                 // a clock: it is under way
    svg.append(make("path", { d: "M12 7.5V12l3 2" }));
  }
  return svg;
}

// A flow on the home board. One article with one link (the title, stretched over the card by CSS), so the card
// is clickable as a whole and Tab stops on it once; nothing inside is a link or a control.
function questCard(f, yourTurn) {
  const ph = f.phase || {};
  const a = f.automation || {};
  const rev = f.latest_review;
  const roles = f.roles || {};
  const live = flowLiveText(f.executor_live, liveLoadError());
  const note = f.phase ? flowBindingNote(f) : "";
  const modeLine = yourTurn
    ? (a.mode === "auto" && a.held ? el("div", { class: "stat-line" }, badge("自動（已停止）", "b-warn"),
      a.step_label ? el("span", { class: "small" }, a.step_label) : null) : null)
    : (a.mode === "auto"
      ? el("div", { class: "stat-line" }, badge(a.held ? "自動（已停止）" : "自動執行中", a.held ? "b-warn" : "b-info"),
        a.step_label ? el("span", { class: "small" }, a.step_label) : null)
      : el("div", { class: "small muted" }, "手動模式：VBear 不會替你推進，下一步由你或你啟動的角色處理"));
  return el("article", { class: `card quest ${yourTurn ? "quest-turn" : "quest-going"}`,
    "data-quest": "flow", "data-flow-id": f.id || "" },
    el("div", { class: "card-top" },
      el("div", { style: "min-width:0" },
        el("div", { class: "card-title" },
          el("a", { class: "quest-link", href: `#/flows/${encodeURIComponent(f.id)}` },
            f.task_missing ? "（任務卡已刪除或無法讀取）" : f.task_title)),
        el("div", { class: "card-sub" }, f.attention_reason || ph.reason || "")),
      el("span", { class: `badge ${flowPhaseClass(ph.key)} quest-type`, title: ph.reason || "" },
        questIcon(yourTurn ? "turn" : "going"), ph.label || "階段不明")),
    modeLine,
    el("div", { class: "stat-line" },
      el("span", null, "執行 ", el("b", null, roleText(roles.executor))),
      el("span", null, "終端 ", el("b", { title: live.reason }, live.label))),
    el("div", { class: "stat-line" },
      el("span", null, "審查 ", el("b", null, (roles.reviewers || []).map(roleText).join("、"))),
      rev ? el("span", null, "最新 ", badge(rev.verdict, VERDICT_CLASS[rev.verdict] || "b-mute",
        rev.counts_as_pass ? "算通過" : (rev.why || "")), ` ${shortCommit(rev.commit)}`) : null),
    note ? el("div", { class: "small muted" }, note) : null,
    teamAvatars(f, 1, true),
    questNext(f),
    el("div", { class: "quest-go" }, yourTurn ? "前往處理 →" : "查看流程 →"));
}

// "Next: ... (your turn / a role's turn)" from nextSteps, which reads the phase the server already derived. Nothing
// is said for a phase the table does not know.
function questNext(f) {
  const text = nextStepSummary(f);
  return text ? el("div", { class: "small quest-next", "data-quest": "next" }, text) : null;
}

function boardSection(g, opts = {}) {
  // Someone still on the first game has a bigger next move (the three steps above); the workbench is a plain button then
  const firstGame = opts.firstGame !== undefined ? opts.firstGame === true : boardFirstGame;
  // one node per block: a node has one parent, so a shared one would be taken away from the first block
  const flowsError = () => (g.error ? notice("warn", `讀不到流程：${g.error}`) : null);
  if (g.allEmpty) {
    return el("section", { class: "section", "data-board": "start" },
      sectionHead("任務告示板", "每 5 秒更新"),
      el("div", { class: "empty-state quest-start" },
        el("strong", null, "大廳目前沒有任務。想開始第一個任務？"),
        el("a", { class: firstGame ? "btn" : "btn primary", href: "#/workbench", "data-board": "workbench" }, "到終端工作台"),
        el("span", null, "在那裡挑角色出發；想讓多個角色合作，先按下方「＋ 任務卡（導入專案）」挑一個專案資料夾，再把角色卡放上任務卡的隊伍位置。")));
  }
  const nTurn = g.yourTurnFlows.length;
  const nAgents = g.yourTurnSessions.length;
  const counts = [nTurn ? `${nTurn} 則流程等你` : "", nAgents ? `${nAgents} 個終端在等你` : ""].filter(Boolean).join("・");
  const cards = [...g.yourTurnFlows.map((f) => questCard(f, true)), ...g.yourTurnSessions.map(sessionCard)];
  let turnBody;
  if (cards.length) turnBody = el("div", { class: "grid" }, cards);
  else if (g.error) {
    turnBody = g.runtimeAvailable
      ? emptyState("目前沒有可判斷為在等你的終端", "只有 VBear 受管啟動、且版本已驗證的 Claude Code 能判斷「工作中／等你回覆」；其他終端會顯示「狀態未知」，請到角色卡池查看。")
      : emptyState("VBear runtime 未連線，無法判斷有沒有終端在等你", null);
  } else if (!g.runtimeAvailable) turnBody = emptyState("VBear runtime 未連線，無法判斷有沒有終端在等你", null);
  else turnBody = emptyState("告示板上目前沒有輪到你的任務",
    "只有 VBear 受管啟動、且版本已驗證的 Claude Code 能判斷「工作中／等你回覆」；其他終端會顯示「狀態未知」，請到角色卡池查看。");
  const goingBody = g.inProgress.length
    ? [el("div", { class: "grid" }, g.inProgress.map((f) => questCard(f, false))),
      g.moreInProgress ? el("a", { class: "btn quest-more", href: "#/flows" }, `還有 ${g.moreInProgress} 則 →`) : null]
    : (g.error ? null : emptyState("目前沒有其他進行中的任務", null));
  return [
    el("section", { class: "section", "data-board": "turn" },
      sectionHead("輪到你", `${counts ? counts + "・" : ""}資料來自流程記錄與即時狀態，每 5 秒更新；「狀態未知」的 Agent 請到角色卡池頁查看`),
      flowsError(),
      turnBody),
    el("section", { class: "section", "data-board": "going" },
      sectionHead("其他進行中的任務", null),
      flowsError(),
      goingBody),
  ];
}

// ---------- the first game (design card-play 3.8) -----------------------------------------------------------------
// Three steps for someone who has no team yet: get role cards, bring in a project as a task card, put the team on
// it. Each step is ticked from data the server has (a card of your own, a task card with a folder, a flow with a
// team), never from what the page did. Unknown data (a list that did not load, a config that cannot be read) shows
// nothing instead of a guess.
const ONBOARD_TITLE = "新手第一局";
const ONBOARD_STEPS = [
  { key: "cards", text: "拿角色卡", hint: "用起手牌組一次拿三張，或自己建" },
  { key: "task", text: "導入專案，建立任務卡", hint: "挑一個你電腦上現有的專案資料夾" },
  { key: "team", text: "把隊伍放上任務卡", hint: "規劃、執行、審查各放一張角色卡" },
];

// input: { profiles, catalog, tasks, flows, dismissed }; a list that is not an array, or a dismissed that is not a
// boolean, means it could not be read. -> { mode: "none" | "steps" | "done", steps, next (the one line when done) }.
function onboardingState(input) {
  const i = input && typeof input === "object" ? input : {};
  const readable = Array.isArray(i.profiles) && Array.isArray(i.tasks) && Array.isArray(i.flows) && typeof i.dismissed === "boolean";
  if (!readable || i.dismissed) return { mode: "none", steps: [], next: "" };
  const done = {
    cards: i.profiles.some((p) => p && typeof p === "object" && !isDemoCard(p, i.catalog)),
    task: i.tasks.some((t) => t && typeof t === "object" && typeof t.workdir === "string" && t.workdir !== ""),
    team: i.flows.some((f) => f && typeof f === "object" && f.roles && f.roles.planner && f.roles.executor),
  };
  const firstTask = i.tasks.find((t) => t && typeof t === "object" && typeof t.workdir === "string" && t.workdir !== "" && typeof t.id === "string") || null;
  const steps = ONBOARD_STEPS.map((st, n) => ({ ...st, n: n + 1, done: done[st.key] }));
  const all = steps.every((st) => st.done);
  let next = "";
  if (all) {
    const open = i.flows.filter((f) => f && typeof f === "object" && !(f.phase && f.phase.key === "done"));
    const f = open.find(waitsForYou) || open[0];
    next = f ? nextStepSummary(f) : "";
  }
  return { mode: all ? "done" : "steps", steps, next, firstTaskId: firstTask ? firstTask.id : null };
}

function onboardMark(done) {
  if (done) return passMark("ok");
  const svg = svgEl("svg", { class: "pass-mark pass-mark-todo", viewBox: "0 0 16 16", width: 16, height: 16, "aria-hidden": "true", focusable: "false" });
  svg.append(svgEl("circle", { cx: 8, cy: 8, r: 6.6, fill: "none", stroke: "currentColor", "stroke-width": 1.6 }));
  return svg;
}

// opts: { onImport(), onDismiss() }
function onboardingSection(state, opts = {}) {
  if (!state || state.mode === "none") return null;
  const dismiss = el("button", { class: "btn small", type: "button", "data-onboard": "dismiss",
    on: { click: () => { if (typeof opts.onDismiss === "function") opts.onDismiss(); } } }, "先收起新手引導");
  if (state.mode === "done") {
    return el("section", { class: "section onboard onboard-done", "data-onboarding": "done", "aria-label": ONBOARD_TITLE },
      el("p", { class: "onboard-line" }, "你的小隊已就位", state.next ? ` · ${state.next}` : ""), dismiss);
  }
  const current = state.steps.find((st) => !st.done);
  const action = (st) => {
    if (st.key === "cards") return el("a", { class: "btn small primary", href: "#/team", "data-onboard-go": "cards" }, "到角色卡池");
    if (st.key === "task") return el("button", { class: "btn small primary", type: "button", "data-onboard-go": "task",
      on: { click: () => { if (typeof opts.onImport === "function") opts.onImport(); } } }, "導入專案");
    return state.firstTaskId
      ? el("a", { class: "btn small primary", href: `#/workbench?task=${encodeURIComponent(state.firstTaskId)}`, "data-onboard-go": "team" }, "去放隊伍")
      : null;
  };
  return el("section", { class: "section onboard", "data-onboarding": "steps", "aria-label": ONBOARD_TITLE },
    sectionHead(ONBOARD_TITLE, "三步組好一支隊伍：拿卡、導入專案、把隊伍放上去。", dismiss),
    el("ol", { class: "onboard-steps" }, state.steps.map((st) => el("li", { class: `onboard-step${st.done ? " onboard-done-step" : ""}`,
      "data-step": st.key, "data-done": String(st.done), "aria-current": current && current.key === st.key ? "step" : null },
      onboardMark(st.done),
      el("span", { class: "onboard-text" }, el("strong", null, `${st.n}. ${st.text}`), " ", el("span", { class: "small muted" }, st.hint)),
      el("span", { class: "onboard-state small" }, st.done ? "完成" : "還沒"),
      current && current.key === st.key ? action(st) : null))));
}

// ---------- the office (design office v1.3): data and pure functions ----------------------------------------
// A page that draws what VBear already has: the flows' teams at the station their phase names, the live
// terminals at a desk, the Agent Profiles in a lounge. Everything here is a pure function of what the page has
// loaded, so the model, the key that decides a repaint and the selection that survives it can be tested.

const OFFICE_STATIONS = ["board", "build", "review", "gate"];
const OFFICE_STATION_LABEL = { board: "計畫板", build: "實作區", review: "審查室", gate: "合併關卡" };
// phase -> station. A phase this table does not know goes to the plan board with its own label; done is not shown.
const OFFICE_PHASE_STATION = {
  planning: "board", awaiting_approval: "board",
  implementing: "build", needs_fix: "build",
  in_review: "review", review_stale: "review", review_unverified: "review",
  awaiting_merge: "gate", awaiting_push: "gate",
};
const OFFICE_TEAMS_PER_STATION = 3;
const OFFICE_REVIEWERS_SHOWN = 3;
const OFFICE_LOUNGE_MAX = 24;
const OFFICE_BOUND_FLOWS_SHOWN = 2;
const OFFICE_SPECIES = ["bear", "fox", "robot", "alien"];
const OFFICE_SPECIES_LABEL = { bear: "熊", fox: "狐", robot: "機械人", alien: "外星人" };
const OFFICE_FAMILY_SPECIES = { anthropic: "bear", openai: "robot", google: "fox" };
const OFFICE_TOOL_SPECIES = { claude: "bear", codex: "robot" };
// The camp is the maker of the model; its shirt colour is lighter than every species' fur (tested), so a
// character reads the same whichever species it was given.
const OFFICE_CAMPS = {
  anthropic: { label: "Anthropic", shirt: "#f59e0b", badge: "#fef3c7" },
  openai: { label: "OpenAI", shirt: "#14b8a6", badge: "#ccfbf1" },
  google: { label: "Google", shirt: "#38bdf8", badge: "#e0f2fe" },
  other: { label: "其他", shirt: "#a855f7", badge: "#f3e8ff" },
};
const OFFICE_TOOL_CAMP = { claude: "anthropic", codex: "openai" };
// 16x16 supplied frames. C is the camp shirt; R is its badge.
const OFFICE_SPRITES = {
  "bear": [
    "...KKK....KKK...",
    "..KBBBK..KBBBK..",
    "..KBbBKKKKBbBK..",
    "...KBBBBBBBBK...",
    "..KBBWKBBKWBBK..",
    "..KBBBBbbBBBBK..",
    "..KBBbKKKKbBBK..",
    "...KBBBBBBBBK...",
    "..KCCCCCCCCCCK..",
    ".KCCCCWYYWCCCCK.",
    ".KCCCCCRRCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KBBBBBBBBK...",
    "...KBBK..KBBK...",
    "...KBBK..KBBK...",
    "...KKK....KKK..."
  ],
  "fox": [
    "..KK........KK..",
    ".KFFK......KFFK.",
    ".KFfFK....KFfFK.",
    "..KFFKKKKKKFFK..",
    "..KFFFFFFFFFFK..",
    ".KFFfWKFFKWfFFK.",
    ".KfffFFFFFFfffK.",
    "..KfffKKKKfffK..",
    "..KCCCCCCCCCCK..",
    ".KCCCCCRRCCCCCK.",
    ".KCCCCCCCCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KFFFFFFFFK...",
    "...KFFK..KFFK...",
    "...KFFK..KFFK...",
    "...KKK....KKK..."
  ],
  "robot": [
    ".......KK.......",
    "......KYYK......",
    ".......KK.......",
    "...KKKKKKKKKK...",
    "..KSSSSSSSSSSK..",
    "..KSsWKSSKWsSK..",
    "..KSSSSSSSSSSK..",
    "..KSSKKKKKKSSK..",
    "...KKKKKKKKKK...",
    "..KCCCCCCCCCCK..",
    ".KCCCCCRRCCCCCK.",
    ".KCCCCCCCCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KSSSSSSSSK...",
    "...KSSK..KSSK...",
    "...KKKK..KKKK..."
  ],
  "alien": [
    "...KK......KK...",
    "..KYYK....KYYK..",
    "...KK......KK...",
    "...KKKKKKKKKK...",
    "..KVVVVVVVVVVK..",
    ".KVVWWKVVKKWWVK.",
    ".KVVWWKVVKKWWVK.",
    "..KVVVVVVVVVVK..",
    "...KVVKKKKVVK...",
    "..KCCCCCCCCCCK..",
    ".KCCCCCRRCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KVVVVVVVVK...",
    "...KVVK..KVVK...",
    "...KVVK..KVVK...",
    "...KKK....KKK..."
  ]
};
const OFFICE_SPRITES_WORKING = {
  "bear": [
    "...KKK....KKK...",
    "..KBBBK..KBBBK..",
    "..KBbBKKKKBbBK..",
    "...KBBBBBBBBK...",
    "..KBBWKBBKWBBK..",
    "..KBBBBbbBBBBK..",
    "..KBBbKKKKbBBK..",
    "...KBBBBBBBBK...",
    "..KCCCCCCCCCCK..",
    ".KBBCCWYYWCCBBK.",
    ".KCCCCCRRCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KBBBBBBBBK...",
    "..KBBK....KBBK..",
    "...KK......KK...",
    "................"
  ],
  "fox": [
    "..KK........KK..",
    ".KFFK......KFFK.",
    ".KFfFK....KFfFK.",
    "..KFFKKKKKKFFK..",
    "..KFFFFFFFFFFK..",
    ".KFFfWKFFKWfFFK.",
    ".KfffFFFFFFfffK.",
    "..KfffKKKKfffK..",
    "..KCCCCCCCCCCK..",
    ".KFFCCCRRCCFFCK.",
    ".KCCCCCCCCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KFFFFFFFFK...",
    "..KFFK....KFFK..",
    "...KK......KK...",
    "................"
  ],
  "robot": [
    "......KYYK......",
    ".....KYYYYK.....",
    ".......KK.......",
    "...KKKKKKKKKK...",
    "..KSSSSSSSSSSK..",
    "..KSSWKSSKWSSK..",
    "..KSSSSSSSSSSK..",
    "..KSSKKKKKKSSK..",
    "...KKKKKKKKKK...",
    "..KCCCCCCCCCCK..",
    ".KSSCCCRRCCSSCK.",
    ".KCCCCCCCCCCCCK.",
    "..KCCCCCCCCCCK..",
    "...KSSSSSSSSK...",
    "...KSSK..KSSK...",
    "...KKKK..KKKK..."
  ],
  "alien": [
    "..KYYK....KYYK..",
    ".KYYYYK..KYYYYK.",
    "...KK......KK...",
    "...KKKKKKKKKK...",
    "..KVVVVVVVVVVK..",
    ".KVVWWKVVKKWWVK.",
    ".KVVWWKVVKKWWVK.",
    "..KVVVVVVVVVVK..",
    "...KVVKKKKVVK...",
    "..KCCCCCCCCCCK..",
    ".KVVCCCRRCCVVCK.",
    "..KCCCCCCCCCCK..",
    "...KVVVVVVVVK...",
    "..KVVK....KVVK..",
    "...KK......KK...",
    "................"
  ]
};
const OFFICE_PALETTE = {
  "K": "#18181b",
  "W": "#fafaf9",
  "Y": "#fde047",
  "B": "#78350f",
  "b": "#b45309",
  "F": "#c2410c",
  "f": "#fed7aa",
  "S": "#52525b",
  "s": "#d4d4d8",
  "V": "#4c1d95",
  "v": "#ddd6fe"
};

function officeToolOf(agent) { return agent === "claude" || agent === "codex" ? agent : "other"; }

function stationFor(phaseKey) {
  if (phaseKey === "done") return null;
  return OFFICE_PHASE_STATION[phaseKey] || "board";
}

// An override is accepted only when it is one of the four species the page draws; anything else is ignored.
function speciesFor(who, override) {
  if (typeof override === "string" && OFFICE_SPECIES.includes(override)) return override;
  const w = who || {};
  if (typeof w.family === "string" && OFFICE_FAMILY_SPECIES[w.family]) return OFFICE_FAMILY_SPECIES[w.family];
  if (w.family === undefined && typeof w.tool === "string" && OFFICE_TOOL_SPECIES[w.tool]) return OFFICE_TOOL_SPECIES[w.tool];
  return "alien";
}
function campOf(who) {
  const w = who || {};
  const key = typeof w.family === "string" ? (OFFICE_CAMPS[w.family] ? w.family : "other")
    : (OFFICE_TOOL_CAMP[w.tool] || "other");
  return Object.assign({ key }, OFFICE_CAMPS[key]);
}

// The box-shadow string of a sprite: one 1x1 shadow per pixel, scaled. Cached per species, colours and scale.
const officeShadowCache = new Map();
function spriteShadow(species, palette, scale, working = false) {
  const sp = OFFICE_SPRITES[species] ? species : "alien";
  const pal = palette || {};
  const shirt = pal.shirt || OFFICE_CAMPS.other.shirt;
  const badge = pal.badge || OFFICE_CAMPS.other.badge;
  const px = Number.isInteger(scale) && scale > 0 && scale <= 12 ? scale : 3;
  const key = `${sp}|${shirt}|${badge}|${px}|${working}`;
  const hit = officeShadowCache.get(key);
  if (hit !== undefined) return hit;
  const colors = Object.assign({}, OFFICE_PALETTE, { C: shirt, R: badge });
  const out = [];
  (working ? OFFICE_SPRITES_WORKING : OFFICE_SPRITES)[sp].forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const c = colors[row[x]];
      if (c) out.push(`${x * px}px ${y * px}px 0 0 ${c}`);
    }
  });
  const value = out.join(",");
  officeShadowCache.set(key, value);
  return value;
}

const OFFICE_TOOLS_MISSING = "這份角色卡資料沒有工具欄位（資料來自較舊的版本）";
// The weapons of a profile: read only from loadout.tools, never from the armor's words.
function weaponsFrom(loadout) {
  const t = loadout && typeof loadout === "object" ? loadout.tools : null;
  if (!t || typeof t !== "object" || typeof t.known !== "boolean") {
    return { known: false, allowed: [], blocked: [], source: "", reason: OFFICE_TOOLS_MISSING };
  }
  const list = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === "string") : []);
  if (t.known) {
    return { known: true, allowed: list(t.allowed), blocked: list(t.blocked),
      source: typeof t.source === "string" ? t.source : "", reason: "" };
  }
  return { known: false, allowed: [], blocked: [], source: "",
    reason: typeof t.unknown_reason === "string" && t.unknown_reason ? t.unknown_reason : OFFICE_TOOLS_MISSING };
}

// The chosen skills of a loadout as rows. A skill the index does not have is said so with the index's own
// time: it is not "gone" (it may be installed somewhere the scan does not look, or removed).
function officeSkills(loadout) {
  const sk = loadout && typeof loadout === "object" && loadout.skills && typeof loadout.skills === "object" ? loadout.skills : {};
  const rows = (Array.isArray(sk.items) ? sk.items : []).filter((x) => x && typeof x === "object").map((x) => {
    const id = typeof x.skill_id === "string" ? x.skill_id : "";
    if (x.state === "in_index") {
      return { id, name: x.invoke_name || x.name || id, state: "in_index", text: "" };
    }
    if (x.state === "not_in_index") {
      const when = Number.isFinite(x.indexed_at) ? `（索引時間 ${fmtTime(x.indexed_at)}）` : "";
      return { id, name: id, state: "not_in_index", text: `${x.note || "目前索引找不到此技能"}${when}` };
    }
    return { id, name: id, state: "index_not_loaded", text: "索引尚未載入，無法確認這項技能" };
  });
  return { note: typeof sk.note === "string" ? sk.note : "", rows };
}

function officeMember(role) {
  const r = role && typeof role === "object" ? role : {};
  const family = typeof r.family === "string" ? r.family : "unknown";
  return { name: typeof r.name === "string" && r.name ? r.name : "未提供", family,
    familyLabel: typeof r.family_label === "string" ? r.family_label : family,
    model: typeof r.model === "string" ? r.model : "", species: speciesFor({ family }),
    camp: campOf({ family }).key };
}

// Fixed lines selected from status and evidence, never generated from terminal text.
function personaSpeech(target) {
  const t = target || {};
  const a = t.activity || {};
  const reason = typeof a.reason === "string" ? a.reason : "";
  const result = (sourceLabel, line, why = reason) => ({ sourceLabel, line, reason: why });
  if ((t.key || "").startsWith("flow:")) {
    const auto = t.automation && t.automation.mode === "auto";
    const source = "依據：流程紀錄";
    const lines = {
      in_review: auto ? "任務位於審查階段；自動模式已設定，不代表審查程序正在執行。" : "任務在審查室。手動模式下，VBear 不會替你送審。",
      awaiting_merge: "審查通過，而且就是目前的 commit。VBear 不會替你 merge 或 push，輪到你了！",
      review_stale: "審查過的不是目前的 commit，需要重新審查。",
      awaiting_approval: auto ? "計畫等候核准中；核准前執行者不會開工。" : "計畫等候核准中；手動模式需由你自行在終端執行。",
    };
    const label = ["awaiting_merge", "review_stale"].includes(t.phaseKey) ? source + "＋HEAD 核對"
      : t.phaseKey === "in_review" ? source + (auto ? "（自動模式）" : "（手動記錄）") : source;
    return result(label, lines[t.phaseKey] || `任務目前在${t.stationLabel}：${t.phaseLabel}`, t.phaseReason || "");
  }
  if ((t.key || "").startsWith("profile:")) return result("依據：角色名冊", "名冊角色不在出勤，沒有即時狀態", "");
  if (t.status === "exited") return result("依據：VBear runtime（終端已結束）", "這個終端已經結束了。");
  if (["working", "waiting", "needs-input"].includes(t.status)) {
    if (t.tool === "claude") {
      if (t.status === "working" && a.decided_by === "claude-title") return result(
        "依據：Claude Code 終端標題（開頭的轉圈符號）",
        "我正在終端機裡忙！VBear 依標題第一個字元分類，不把標題文字作為終端標題保存或回傳。");
      if (t.status === "working" && a.decided_by === "claude-stream") return result(
        "依據：Claude Code 串流協定的回合事件", "我正在跑自動派工的這一輪，做完會交回結果。");
      if (t.status === "waiting" && a.decided_by === "claude-title") return result(
        "依據：Claude Code 終端標題（閒置符號 ✳）", "我停下來等你囉（! 輪到你），打開終端機看看我吧。");
      if (t.status === "waiting" && a.decided_by === "claude-stream") return result(
        "依據：Claude Code 串流協定的回合事件", "這一輪背景派工已結束，等待下一則任務。");
    }
    const states = { working: "工作中", waiting: "等你回覆", "needs-input": "需要你處理" };
    return result("依據：VBear runtime 回報的狀態（沒有附上證據來源）",
      `VBear runtime 回報我在${states[t.status]}，但沒有附上是哪一種證據。`);
  }
  return result("依據：沒有可採用的證據", t.tool === "claude"
    ? "VBear 現在看不出我在做什麼（例如版本還沒驗證、或標題超過 5 秒沒更新），所以誠實寫『狀態未知』。"
    : "VBear 目前沒有這個工具的即時狀態來源，所以寫『狀態未知』。");
}

function officeBubble(status) {
  if (status === "exited") return "";
  if (status === "needs-input") return "需要你處理";
  if (status === "waiting") return "等你回覆";
  if (status === "working") return "工作中";
  return "? 狀態未知";
}

// overrides: { <profileId>: species } already read from storage (see officeOverrides).
function officeModel(live, flowsData, profilesData, overrides) {
  const L = live || {};
  const ov = overrides || {};
  const runtimeAvailable = !!(L.runtime && L.runtime.available);
  const sessions = (Array.isArray(L.sessions) ? L.sessions : []).filter((x) => x && typeof x === "object");
  const attention = new Set(Array.isArray(L.attention) ? L.attention : []);
  const errors = { flows: "", profiles: "", live: L.error ? String(L.error) : "", runtime: !runtimeAvailable };
  let flows = [];
  if (!flowsData) errors.flows = "還沒有讀取到流程";
  else if (flowsData.error) errors.flows = String(flowsData.error);
  else if (!Array.isArray(flowsData.flows)) errors.flows = "流程資料的格式無法辨識";
  else flows = flowsData.flows.filter((f) => f && typeof f === "object");
  let profiles = [];
  if (!profilesData) errors.profiles = "還沒有讀取到角色名冊";
  else if (profilesData.error) errors.profiles = String(profilesData.error);
  else if (!Array.isArray(profilesData.profiles)) errors.profiles = "角色名冊的格式無法辨識";
  else profiles = profilesData.profiles.filter((p) => p && typeof p === "object" && typeof p.id === "string");

  // stations: the teams of every open flow; the ones that wait for you are taken first, then the API order
  const open = flows.filter((f) => !(f.phase && f.phase.key === "done"));
  const stationOf = (f) => stationFor(f.phase && f.phase.key) || "board";
  const teamOf = (f) => {
    const ph = f.phase || {};
    const a = f.automation || {};
    const roles = f.roles || {};
    const reviewers = (Array.isArray(roles.reviewers) ? roles.reviewers : []).map(officeMember);
    const station = stationOf(f);
    return {
      key: `flow:${f.id}`, id: f.id, title: f.task_missing ? "" : (f.task_title || ""), taskMissing: !!f.task_missing,
      phaseKey: ph.key || "", phaseLabel: ph.label || "階段不明", phaseReason: ph.reason || "",
      attentionReason: f.attention_reason || "", waits: waitsForYou(f), station, stationLabel: OFFICE_STATION_LABEL[station],
      automation: { mode: a.mode || "", held: !!a.held, stepLabel: a.step_label || "" },
      executor: officeMember(roles.executor), reviewers: reviewers.slice(0, OFFICE_REVIEWERS_SHOWN),
      moreReviewers: Math.max(0, reviewers.length - OFFICE_REVIEWERS_SHOWN),
      sessionId: roles.executor && typeof roles.executor.session_id === "string" ? roles.executor.session_id : "",
      live: f.executor_live && typeof f.executor_live === "object" ? f.executor_live : null,
    };
  };
  const allTeams = open.map(teamOf);
  const stations = {};
  for (const st of OFFICE_STATIONS) {
    const here = allTeams.filter((t) => t.station === st);
    const ordered = [...here.filter((t) => t.waits), ...here.filter((t) => !t.waits)];
    stations[st] = { label: OFFICE_STATION_LABEL[st], teams: ordered.slice(0, OFFICE_TEAMS_PER_STATION),
      more: Math.max(0, ordered.length - OFFICE_TEAMS_PER_STATION) };
  }

  // desks: one per live session; a flow is named on the plate only when its executor is this very row and the
  // live data that says so is current
  const boundTo = (x) => allTeams.filter((t) => {
    if (!t.sessionId || (t.sessionId !== x.pane_id && t.sessionId !== x.terminal_id)) return false;
    const lv = t.live;
    if (!lv || lv.state === "stale" || lv.state === "not_loaded") return false;
    return !(lv.freshness && lv.freshness.state === "invalid");
  });
  const projects = Array.isArray(L.projects) ? L.projects : [];
  const desks = sessions.map((x) => {
    const tool = officeToolOf(x.agent);
    const status = typeof x.status === "string" && STATUS[x.status] ? x.status : "unknown";
    const bound = boundTo(x);
    const project = projects.find((p) => p.project_id === x.project_id);
    return {
      key: `session:${x.terminal_id}`, terminalId: x.terminal_id, paneId: x.pane_id || "", tool,
      toolLabel: TOOL[x.agent] || x.agent || "未知工具", status, ended: status === "exited",
      bubble: officeBubble(status), activity: x.activity || null, name: x.role_label || (TOOL[x.agent] || x.agent || "工作階段"),
      title: x.title || "", projectId: x.project_id || "", project: project ? project.name : "",
      waits: attention.has(x.terminal_id), species: speciesFor({ tool }), camp: campOf({ tool }).key,
      bound: bound.slice(0, OFFICE_BOUND_FLOWS_SHOWN).map((t) => ({ id: t.id, title: t.title, taskMissing: t.taskMissing,
        station: t.station, stationLabel: t.stationLabel })),
      boundMore: Math.max(0, bound.length - OFFICE_BOUND_FLOWS_SHOWN),
    };
  });

  // lounge: the roster of profiles (not attendance)
  const rosterAll = profiles.map((p) => {
    const model = p.model && typeof p.model === "object" ? p.model : {};
    const tool = typeof model.tool === "string" ? model.tool : "";
    return { key: `profile:${p.id}`, id: p.id, name: typeof p.name === "string" && p.name ? p.name : p.id,
      tool, toolLabel: TOOL[tool] || tool || "未知工具", modelId: model.model_id || "",
      species: speciesFor({ tool }, ov[p.id]), overridden: OFFICE_SPECIES.includes(ov[p.id]),
      camp: campOf({ tool }).key };
  });
  const lounge = { items: rosterAll.slice(0, OFFICE_LOUNGE_MAX), more: Math.max(0, rosterAll.length - OFFICE_LOUNGE_MAX),
    total: rosterAll.length };

  const turnFlows = allTeams.filter((t) => t.waits).length;
  const turnSessions = desks.filter((d) => d.waits).length;
  const counts = {
    turn: turnFlows + turnSessions, turnFlows, turnSessions,
    working: runtimeAvailable ? desks.filter((d) => d.status === "working").length : null,
    unknown: runtimeAvailable ? desks.filter((d) => d.status === "unknown").length : null,
    roster: errors.profiles ? null : rosterAll.length,
  };
  const everyoneLoaded = !errors.flows && !errors.profiles && runtimeAvailable;
  const allEmpty = everyoneLoaded && allTeams.length === 0 && desks.length === 0 && rosterAll.length === 0;
  return { stations, desks, lounge, counts, errors, allEmpty, runtimeAvailable, teamsTotal: allTeams.length };
}

// Everything the office shows, so that a refresh repaints only when something visible changed.
function officeKey(model) {
  const m = model;
  const member = (x) => [x.name, x.family, x.familyLabel, x.model, x.species, x.camp];
  const team = (t) => [t.key, t.title, t.taskMissing, t.phaseKey, t.phaseLabel, t.phaseReason, t.waits, t.attentionReason,
    t.automation.mode, t.automation.held, t.automation.stepLabel, member(t.executor), t.reviewers.map(member),
    t.moreReviewers, t.station];
  const desk = (d) => [d.key, d.paneId, d.tool, d.toolLabel, d.status, d.activity, d.name, d.title, d.projectId, d.project,
    d.waits, d.species, d.camp, d.bound.map((b) => [b.id, b.title, b.taskMissing, b.station]), d.boundMore];
  return JSON.stringify({
    errors: m.errors, runtime: m.runtimeAvailable, counts: m.counts, allEmpty: m.allEmpty,
    stations: OFFICE_STATIONS.map((st) => [st, m.stations[st].more, m.stations[st].teams.map(team)]),
    desks: m.desks.map(desk),
    lounge: [m.lounge.more, m.lounge.total, m.lounge.items.map((p) => [p.key, p.name, p.tool, p.modelId, p.species, p.camp])],
  });
}

// All characters and teams of a model by their identity key: { key -> { kind, name, section } }.
function officeIndex(model) {
  const idx = new Map();
  for (const st of OFFICE_STATIONS) {
    for (const t of model.stations[st].teams) {
      idx.set(t.key, { kind: "flow", name: t.taskMissing ? "（任務卡已刪除或無法讀取）" : t.title, section: "stations", station: st });
    }
  }
  for (const d of model.desks) idx.set(d.key, { kind: "session", name: d.name, section: "desks" });
  for (const p of model.lounge.items) idx.set(p.key, { kind: "profile", name: p.name, section: "lounge" });
  return idx;
}

// What happens to the selection after a repaint. prev is the key, or { key, name } so the message can name what
// was there. focusKey is the character to focus; focusSection the heading to focus when the selection is gone
// (never the body).
function restoreSelection(prev, model) {
  const key = typeof prev === "string" ? prev : (prev && prev.key) || "";
  const prevName = prev && typeof prev === "object" && prev.name ? prev.name : "";
  if (!key) return { kept: false, key: "", message: "", focusKey: "", focusSection: "" };
  const idx = officeIndex(model);
  if (idx.has(key)) return { kept: true, key, message: "", focusKey: key, focusSection: "" };
  const kind = key.split(":")[0];
  const section = kind === "flow" ? "stations" : kind === "session" ? "desks" : "lounge";
  const name = prevName || "角色";
  return { kept: false, key: "", message: `剛才選的${name}已不在辦公室`, focusKey: "", focusSection: section };
}

// The phone's list: who waits for you, then the teams by station, then the desks, then the lounge.
function officeList(model) {
  const turn = [];
  for (const st of OFFICE_STATIONS) for (const t of model.stations[st].teams) if (t.waits) turn.push(t.key);
  for (const d of model.desks) if (d.waits) turn.push(d.key);
  return [
    { id: "turn", label: "輪到你", keys: turn },
    ...OFFICE_STATIONS.map((st) => ({ id: `station-${st}`, label: OFFICE_STATION_LABEL[st],
      keys: model.stations[st].teams.map((t) => t.key), more: model.stations[st].more })),
    { id: "desks", label: "辦公桌", keys: model.desks.map((d) => d.key) },
    { id: "lounge", label: "休息室", keys: model.lounge.items.map((p) => p.key), more: model.lounge.more },
  ];
}

const OFFICE_SPECIES_KEY = "office.species.";
// The species a person gave a profile, read defensively: a failed read or an unknown value is no override.
function officeOverrides(profiles, storage) {
  const out = {};
  for (const p of Array.isArray(profiles) ? profiles : []) {
    if (!p || typeof p.id !== "string") continue;
    let v;
    try { v = storage.get(OFFICE_SPECIES_KEY + p.id, null); } catch (_) { v = null; }
    if (typeof v === "string" && OFFICE_SPECIES.includes(v)) out[p.id] = v;
  }
  return out;
}

// ---------- the office (design office v1.3): the page --------------------------------------------------------

let officeTick = null;
// keys whose 「輪到你」 badge was already drawn: only a badge that is new fades in (no repeat on every repaint)
const officeBadgeSeen = new Set();
const OFFICE_MOBILE_QUERY = "(max-width: 820px)";

function officeIsMobile() {
  try { return !!(window.matchMedia && window.matchMedia(OFFICE_MOBILE_QUERY).matches); } catch (_) { return false; }
}

// A 16x16 character: a 1px square whose box-shadows are the pixels. Decoration only; the control around it has the words.
function officeSprite(species, camp, scale, working = false) {
  const c = OFFICE_CAMPS[camp] || OFFICE_CAMPS.other;
  const frame = (active) => el("span", { class: `office-px office-frame-${active ? "working" : "idle"}`,
    style: `width:${scale}px;height:${scale}px;box-shadow:${spriteShadow(species, c, scale, active)}` });
  return el("span", { class: `office-sprite${working ? " office-sprite-working" : ""}`, "aria-hidden": "true",
    style: `width:${16 * scale}px;height:${16 * scale}px` }, frame(false), working ? frame(true) : null);
}

function officeTeamTitle(t) { return t.taskMissing ? "（任務卡已刪除或無法讀取）" : (t.title || "（沒有名稱）"); }

function officeTeamLabel(t) {
  return `${officeTeamTitle(t)}，${t.phaseLabel}，任務在：${t.stationLabel}${t.waits ? "，輪到你" : ""}`;
}
function officeDeskLabel(d) {
  return `${d.name}，${d.ended ? "已結束" : d.bubble.replace(/^\? /, "")}，${d.toolLabel}`;
}
function officeProfileLabel(p) { return `${p.name}，名冊，${p.toolLabel}`; }

// Where a team's mode is said: manual flows say they are recorded by hand; automatic ones use the existing words.
function officeModeText(t) {
  if (t.automation.mode === "auto") {
    return `${t.automation.held ? "自動（已停止）" : "自動執行中"}${t.automation.stepLabel ? "・" + t.automation.stepLabel : ""}`;
  }
  return "手動記錄";
}

function officeTeamButton(t, selected, fresh, onPick) {
  const members = [t.executor, ...t.reviewers];
  return el("button", { type: "button", "data-office-key": t.key, "aria-label": officeTeamLabel(t),
    "aria-pressed": String(selected), on: { click: () => onPick(t.key) },
    class: `office-team${t.waits ? " office-team-waits" : ""}${selected ? " office-selected" : ""}` },
    t.waits ? el("span", { class: `office-turn${fresh ? " office-turn-new" : ""}` },
      el("span", { class: "office-turn-mark", "aria-hidden": "true" }, "!"), "輪到你") : null,
    el("span", { class: "office-members" },
      members.map((mb) => officeSprite(mb.species, mb.camp, 3)),
      t.moreReviewers ? el("span", { class: "office-more-members" }, `+${t.moreReviewers}`) : null),
    el("span", { class: "office-team-title" }, officeTeamTitle(t)),
    el("span", { class: "office-team-phase" }, t.phaseLabel),
    el("span", { class: "office-team-where" }, `任務在：${t.stationLabel}`),
    el("span", { class: "office-team-mode" }, officeModeText(t)));
}

function officeDeskButton(d, selected, fresh, onPick) {
  return el("button", { type: "button", "data-office-key": d.key, "aria-label": officeDeskLabel(d), "aria-pressed": String(selected),
    on: { click: () => onPick(d.key) },
    class: `office-char office-desk-char office-status-${d.status}${d.waits ? " office-waits" : ""}${selected ? " office-selected" : ""}` },
    d.waits ? el("span", { class: `office-turn${fresh ? " office-turn-new" : ""}` },
      el("span", { class: "office-turn-mark", "aria-hidden": "true" }, "!"), "輪到你") : null,
    d.ended ? null : el("span", { class: "office-bubble", "aria-hidden": "true" }, d.bubble),
    officeSprite(d.species, d.camp, 3, d.status === "working"),
    el("span", { class: "office-desk-top", "aria-hidden": "true" }),
    el("span", { class: "office-plate" },
      el("span", { class: "office-plate-name" }, d.name),
      el("span", { class: "office-plate-tool" }, d.ended ? `${d.toolLabel}・已結束` : d.toolLabel),
      d.bound.map((b) => el("span", { class: "office-plate-flow" },
        `流程：${b.taskMissing ? "（任務卡已刪除或無法讀取）" : b.title}（任務在：${b.stationLabel}）`)),
      d.boundMore ? el("span", { class: "office-plate-flow" }, `等 ${d.boundMore} 個`) : null));
}

function officeProfileButton(p, selected, onPick) {
  return el("button", { type: "button", "data-office-key": p.key, "aria-label": officeProfileLabel(p), "aria-pressed": String(selected),
    on: { click: () => onPick(p.key) },
    class: `office-char office-profile-char${selected ? " office-selected" : ""}` },
    officeSprite(p.species, p.camp, 3),
    el("span", { class: "office-plate" },
      el("span", { class: "office-plate-name" }, p.name),
      el("span", { class: "office-plate-tool" }, p.toolLabel)));
}

// ---- the side panel ----

function officeKv(rows) {
  return el("dl", { class: "kv small office-kv" }, rows.flatMap(([k, v]) => [el("dt", null, k), el("dd", null, v)]));
}

function officeArmorCell(it) {
  const strong = it.group === "blocked" || it.group === "partial";
  return el("div", { class: `office-armor-cell ${strong ? "office-armor-solid" : "office-armor-dashed"}` },
    armorShield(it.level), el("strong", null, it.name), " ", el("span", { class: "office-armor-level" }, it.level),
    el("span", { class: "office-armor-note" }, it.note || ""));
}

const WEAPON_LOCKED_NOTE = "鎖住＝VBear 啟動時不開放這個工具；寫檔改由終端指令在限制範圍內進行。";
function officeGear(loadoutState) {
  if (!loadoutState || loadoutState.state === "loading") return el("p", { class: "small muted" }, "載入裝備中…");
  if (loadoutState.state === "error") return notice("warn", `讀不到這個角色的裝備：${loadoutState.error}`);
  const d = loadoutState.data;
  const w = weaponsFrom(d);
  const skills = officeSkills(d);
  const ar = d && d.armor && typeof d.armor === "object" ? d.armor : {};
  const items = Array.isArray(ar.items) ? ar.items : [];
  return [
    el("section", { class: "office-gear", "data-office-gear": "weapons" },
      el("h4", null, "武器（可用工具）"),
      w.known
        ? [el("div", { class: "chips" },
          w.allowed.map((n) => el("span", { class: "tag office-weapon-ok" }, `${n}・可用`)),
          w.blocked.map((n) => el("span", { class: "tag office-weapon-off" }, `${n}・鎖住`))),
        w.blocked.length ? el("p", { class: "small", "data-office-gear": "weapons-note" }, WEAPON_LOCKED_NOTE) : null,
        w.source ? el("p", { class: "small muted" }, w.source) : null]
        : el("p", { class: "small" }, `未知：${w.reason}`)),
    el("section", { class: "office-gear", "data-office-gear": "armor" },
      el("h4", null, "防具"),
      ar.applicable === false ? el("p", { class: "small" }, ar.why || "這個角色沒有防具資料。")
        : (items.length ? el("div", { class: "office-armor" }, items.map(officeArmorCell))
          : el("p", { class: "small muted" }, "沒有防具資料。")),
      el("p", { class: "small muted" }, ar.preview_decides || "實際以出發通行證為準")),
    el("section", { class: "office-gear", "data-office-gear": "skills" },
      el("h4", null, "技能卡"),
      skills.note ? el("p", { class: "small" }, skills.note) : null,
      skills.rows.length ? el("ul", { class: "office-skill-list" }, skills.rows.map((r) =>
        el("li", { class: `office-skill office-skill-${r.state}` }, el("strong", null, r.name),
          r.text ? el("span", { class: "small" }, ` ${r.text}`) : null)))
        : el("p", { class: "small muted" }, "未選任何技能。")),
  ];
}

// Screen text is separate from the drawing so its evidence rules are testable.
function officeStageScreen(target) {
  const t = target || {};
  const neutral = { fill: "#27272a", ink: "#a1a1aa" };
  if ((t.key || "").startsWith("flow:")) return { ...neutral, label: `任務在${t.stationLabel}` };
  if ((t.key || "").startsWith("profile:")) return { ...neutral, label: "名冊" };
  if (t.status === "working") return { fill: "#064e3b", ink: "#34d399", label: "◐ 工作中" };
  if (t.status === "waiting" || t.status === "needs-input") return { fill: "#7f1d1d", ink: "#fca5a5", label: "✳ 輪到你" };
  return { ...neutral, label: t.status === "exited" ? "已結束" : "? 狀態未知" };
}

function officeStageSvg(target) {
  const t = target || {};
  const member = (t.key || "").startsWith("flow:") ? t.executor : t;
  const sp = OFFICE_SPECIES.includes(member.species) ? member.species : "alien";
  const camp = OFFICE_CAMPS[member.camp] || OFFICE_CAMPS.other;
  const screen = officeStageScreen(t);
  const working = (t.key || "").startsWith("session:") && t.status === "working";
  const p = OFFICE_PALETTE;
  const fur = { bear: p.B, fox: p.F, robot: p.S, alien: p.V }[sp];
  const make = (tag, attrs, parent, text) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    if (parent) parent.append(n);
    return n;
  };
  const svg = make("svg", { class: `office-stage-svg office-stage-${sp}`, viewBox: "0 0 360 240", role: "img",
    "aria-label": `${OFFICE_SPECIES_LABEL[sp]}，${member.name || "未知名稱"}，${screen.label}`, focusable: "false" });
  // The character is scaled within the stage, leaving room for a readable monitor.
  const body = make("g", { transform: "translate(0 -5) scale(1 .9)" }, svg);
  const shape = (tag, attrs, parent = body) => make(tag, { stroke: p.K, "stroke-width": 4, ...attrs }, parent);
  shape("rect", { x: 122, y: 135, width: 116, height: 95, rx: sp === "robot" ? 18 : 42, fill: camp.shirt });
  if (sp === "bear") {
    for (const x of [122, 238]) {
      shape("circle", { cx: x, cy: 52, r: 24, fill: fur });
      shape("circle", { cx: x, cy: 52, r: 12, fill: p.b, stroke: "none" });
    }
    shape("rect", { x: 112, y: 45, width: 136, height: 106, rx: 50, fill: fur });
    shape("path", { d: "M152 153 L180 184 L208 153", fill: "none", stroke: p.W, "stroke-width": 10, "stroke-linejoin": "round" });
    shape("circle", { cx: 180, cy: 184, r: 7, fill: p.Y });
    shape("ellipse", { cx: 180, cy: 116, rx: 28, ry: 20, fill: p.b });
    shape("ellipse", { cx: 180, cy: 108, rx: 9, ry: 6, fill: p.K });
  } else if (sp === "fox") {
    shape("polygon", { points: "116,75 104,18 154,50", fill: fur });
    shape("polygon", { points: "244,75 256,18 206,50", fill: fur });
    shape("polygon", { points: "119,61 113,32 139,51", fill: p.f, stroke: "none" });
    shape("polygon", { points: "241,61 247,32 221,51", fill: p.f, stroke: "none" });
    shape("rect", { x: 114, y: 48, width: 132, height: 98, rx: 46, fill: fur });
    shape("path", { d: "M114 105 Q145 146 180 146 Q215 146 246 105 Q220 95 180 115 Q140 95 114 105Z", fill: p.f, stroke: "none" });
    shape("path", { d: "M171 116 L189 116 L180 125Z", fill: p.K });
  } else if (sp === "robot") {
    shape("line", { x1: 180, y1: 20, x2: 180, y2: 45 });
    shape("circle", { cx: 180, cy: 18, r: 9, fill: p.Y });
    shape("rect", { x: 116, y: 42, width: 128, height: 98, rx: 16, fill: fur });
    shape("rect", { x: 128, y: 64, width: 104, height: 44, rx: 8, fill: p.K });
    for (const x of [142, 198]) shape("rect", { x, y: 76, width: 20, height: 18, rx: 3, fill: OFFICE_CAMPS.google.shirt, stroke: "none" });
    shape("rect", { x: 152, y: 118, width: 56, height: 10, rx: 3, fill: p.s, "stroke-width": 2 });
    shape("rect", { x: 155, y: 151, width: 50, height: 26, rx: 4, fill: p.K });
    shape("path", { d: "M163 164h8l4-5 6 10 5-5h10", stroke: camp.badge, fill: "none", "stroke-width": 2 });
  } else {
    for (const [x, to] of [[145, 132], [215, 228]]) {
      shape("line", { x1: x, y1: 50, x2: to, y2: 20 });
      shape("circle", { cx: to, cy: 18, r: 8, fill: p.Y });
    }
    shape("rect", { x: 114, y: 45, width: 132, height: 100, rx: 48, fill: fur });
    for (const x of [150, 210]) shape("ellipse", { cx: x, cy: 94, rx: 16, ry: 20, fill: p.W });
    shape("path", { d: "M166 126 Q180 136 194 126", stroke: p.v, fill: "none", "stroke-width": 3 });
  }
  if (sp !== "robot") for (const x of [152, 208]) {
    shape("circle", { cx: x, cy: 92, r: sp === "alien" ? 7 : 9, fill: p.K });
    shape("circle", { cx: x - 3, cy: 89, r: 3, fill: p.W, stroke: "none" });
  }
  if (sp !== "bear") shape("rect", { x: 171, y: 181, width: 18, height: 9, rx: 3, fill: camp.badge, "stroke-width": 2 });
  const hands = make("g", { class: `office-stage-hands${working ? " office-stage-working" : ""}` }, body);
  for (const x of [118, 242]) shape("ellipse", { cx: x, cy: 215, rx: 16, ry: 13, fill: fur }, hands);
  shape("rect", { x: 40, y: 205, width: 280, height: 14, rx: 4, fill: "#5c4033" }, svg);
  shape("rect", { x: 126, y: 177, width: 108, height: 26, rx: 4, fill: p.s }, svg);
  shape("path", { d: "M135 187h90 M140 195h80", "stroke-width": 2 }, svg);
  shape("rect", { x: 104, y: 137, width: 152, height: 51, rx: 6, fill: p.K }, svg);
  shape("rect", { x: 111, y: 143, width: 138, height: 37, rx: 3, fill: screen.fill, stroke: "none", "data-stage-screen": "1" }, svg);
  make("text", { x: 180, y: 166, "text-anchor": "middle", fill: screen.ink, "font-size": 13, "font-family": "monospace", "font-weight": "bold" }, svg, screen.label);
  return svg;
}

const OFFICE_STAGE_KEY = "office.stage.collapsed";
function officeStageCollapsed(storage) {
  try { return storage.get(OFFICE_STAGE_KEY, false) === true; } catch { return false; }
}
function officeStage(target, storage = store) {
  let collapsed = officeStageCollapsed(storage);
  const content = el("div", { id: "office-stage-container", class: "office-stage-container", hidden: collapsed ? "hidden" : null }, officeStageSvg(target));
  const button = el("button", { type: "button", class: "btn small office-stage-toggle", "data-office-stage-toggle": "1",
    "aria-expanded": String(!collapsed), "aria-controls": "office-stage-container", on: { click: () => {
      collapsed = !collapsed;
      content.hidden = collapsed;
      button.setAttribute("aria-expanded", String(!collapsed));
      button.textContent = collapsed ? "展開角色舞台" : "隱藏角色舞台";
      try { storage.set(OFFICE_STAGE_KEY, collapsed); } catch { /* optional */ }
    } } }, collapsed ? "展開角色舞台" : "隱藏角色舞台");
  return el("section", { class: "office-stage" }, button, content);
}

function officeSpeech(target) {
  const speech = personaSpeech(target);
  return el("section", { class: "office-persona-speech" }, el("h3", null, "角色狀態回報"),
    el("p", { class: "small muted" }, speech.sourceLabel), el("p", null, speech.line),
    speech.reason ? el("details", null, el("summary", null, "VBear 的判斷"), el("p", null, speech.reason)) : null);
}

// The roster card in the panel is the same card as in the card pool: short front, the gear on the back (design card-play
// 3.2). Which face is up is kept in S, so the panel repaints (a late loadout) without turning the card back.
function officeRoleCard(p, S) {
  const list = S.profiles && Array.isArray(S.profiles.profiles) ? S.profiles.profiles : [];
  const full = list.find((x) => x && x.id === p.id);
  const loadoutState = S.loadout && S.loadout.key === p.key ? S.loadout : null;
  const gear = officeGear(loadoutState);
  if (!full) return gear;
  return profileCard(full, { loadout: loadoutState, face: S.face, onFace: (f) => { S.face = f; }, backExtra: gear }).node;
}

function officePanelContent(m, S, handlers) {
  const idx = officeIndex(m);
  const key = S.key;
  if (!key) {
    return [el("h2", { id: "office-panel-title", tabindex: "-1" }, "角色面板"),
      S.notice ? el("p", { class: "office-gone", role: "status" }, S.notice) : null,
      el("p", { class: "small" }, "點一個角色或一隊，這裡會顯示它的位置、狀態和依據。"),
      el("ul", { class: "small office-howto" },
        el("li", null, "工作站：流程的隊伍站在「任務目前在哪一站」；站只表示任務的位置，不表示角色正在做什麼。"),
        el("li", null, "辦公桌：出勤中的終端，頭上的字是它目前的狀態。"),
        el("li", null, "休息室：角色卡名冊，不代表正在出勤；點開看武器、防具和技能卡。"))];
  }
  const kind = key.split(":")[0];
  const head = (name, sub, badgeNode) => el("div", { class: "office-panel-head" },
    el("h2", { id: "office-panel-title", tabindex: "-1" }, name),
    el("div", { class: "small muted" }, sub), badgeNode || null);
  const close = el("button", { type: "button", class: "btn small office-close", "data-office-close": "1",
    on: { click: handlers.close } }, officeIsMobile() ? "返回" : "關閉");
  if (kind === "flow") {
    const t = allOfficeTeams(m).find((x) => x.key === key);
    if (!t) return [close];
    const members = [t.executor, ...t.reviewers];
    return [close, officeStage(t),
      head(officeTeamTitle(t), `${officeModeText(t)}・任務在：${t.stationLabel}`, flowPhaseBadge({ key: t.phaseKey, label: t.phaseLabel, reason: t.phaseReason })),
      t.waits ? el("p", { class: "office-turn office-turn-inline" }, el("span", { class: "office-turn-mark", "aria-hidden": "true" }, "!"), "輪到你") : null,
      officeSpeech(t),
      el("p", null, t.attentionReason || t.phaseReason || "沒有說明"),
      el("p", { class: "small muted" }, "隊伍角色代表流程關卡；即時敲鍵盤動態請見辦公桌出勤角色。"),
      el("h3", null, "隊伍成員"),
      el("ul", { class: "office-members-list" }, members.map((mb, i) => el("li", null,
        officeSprite(mb.species, mb.camp, 2),
        el("span", null, el("strong", null, mb.name), `（${i === 0 ? "執行者" : "審查者"}）`,
          el("span", { class: "small muted" }, ` ${mb.familyLabel}${mb.model ? "・" + mb.model : "・模型未提供"}`))))),
      t.moreReviewers ? el("p", { class: "small muted" }, `還有 ${t.moreReviewers} 位審查者，到流程頁查看。`) : null,
      el("p", { class: "small muted" }, "流程角色只記名稱與模型家族，沒有裝備資料。"),
      el("a", { class: "btn primary office-go", href: `#/flows/${encodeURIComponent(t.id)}` }, "前往流程")];
  }
  if (kind === "session") {
    const d = m.desks.find((x) => x.key === key);
    if (!d) return [close];
    return [close, officeStage(d),
      head(d.name, `${OFFICE_SPECIES_LABEL[d.species]}・${d.toolLabel}・陣營 ${OFFICE_CAMPS[d.camp].label}`, statusBadge(d.status, d.activity)),
      d.waits ? el("p", { class: "office-turn office-turn-inline" }, el("span", { class: "office-turn-mark", "aria-hidden": "true" }, "!"), "輪到你") : null,
      officeSpeech(d),
      officeKv([["標題", d.title || "—"], ["專案", d.project || "—"], ["終端", d.paneId || d.terminalId]]),
      d.bound.length ? el("div", null, el("h3", null, "綁定的流程"), el("ul", null, d.bound.map((b) => el("li", null,
        `${b.taskMissing ? "（任務卡已刪除或無法讀取）" : b.title}（任務在：${b.stationLabel}）`)))) : null,
      el("section", { class: "office-gear" }, el("h4", null, "武器・防具・技能卡"),
        el("p", { class: "small" }, "未知：不是用角色卡啟動的，VBear 看不到它的裝備")),
      d.ended ? null : el("a", { class: "btn primary office-go", href: `#/term/${encodeURIComponent(d.paneId || d.terminalId)}`,
        title: "開啟終端機串流（預設僅觀看）" }, "開啟終端")];
  }
  const p = m.lounge.items.find((x) => x.key === key);
  if (!p) return [close];
  const species = el("select", { "aria-label": "換種族", "data-office-species": "1",
    on: { change: (e) => handlers.species(p.id, e.target.value) } },
    el("option", { value: "" , selected: p.overridden ? null : "selected" }, `依工具（${OFFICE_SPECIES_LABEL[speciesFor({ tool: p.tool })]}）`),
    OFFICE_SPECIES.map((sp) => el("option", { value: sp, selected: p.overridden && p.species === sp ? "selected" : null },
      OFFICE_SPECIES_LABEL[sp])));
  return [close, officeStage(p),
    head(p.name, `${OFFICE_SPECIES_LABEL[p.species]}・${p.toolLabel}${p.modelId ? "・" + p.modelId : ""}・陣營 ${OFFICE_CAMPS[p.camp].label}`,
      badge("名冊", "b-mute", "這是角色設定，不代表正在出勤")),
    el("p", { class: "small" }, "名冊：這是角色設定，不代表正在出勤。"),
    el("p", { class: "small muted" }, personaSpeech(p).line),
    el("label", { class: "office-species" }, "種族 ", species),
    el("p", { class: "small muted" }, "只換名冊上的外觀；出勤的終端與流程角色依工具或模型家族顯示。"),
    officeRoleCard(p, S),
    el("a", { class: "btn primary office-go", href: `#/workbench?profile=${encodeURIComponent(p.id)}` }, "打開角色卡")];
}

function allOfficeTeams(m) { return OFFICE_STATIONS.flatMap((st) => m.stations[st].teams); }

// ---- the counts (header and bottom of the scene) ----

function officeCountsBar(m, pick) {
  const n = (v) => (v === null ? "無法判斷" : String(v));
  const defs = [
    ["turn", "輪到你", n(m.counts.turn)],
    ["working", "工作中", n(m.counts.working)],
    ["unknown", "狀態未知", n(m.counts.unknown)],
    ["roster", "名冊", n(m.counts.roster)],
  ];
  return el("div", { class: "office-counts", role: "group", "aria-label": "計數" },
    defs.map(([kind, label, value]) => el("button", { type: "button", class: `office-count office-count-${kind}`,
      "data-office-count": kind, on: { click: () => pick(kind) } },
    el("span", { class: "office-count-label" }, label), el("strong", { class: "office-count-value" }, value))));
}

// ---- the scene ----

function officeSections(m, S, fresh) {   // S.reloadRoster is set by the view
  const stationsBody = m.errors.flows
    ? notice("warn", `讀不到流程：${m.errors.flows}`)
    : el("div", { class: "office-stations-grid" }, OFFICE_STATIONS.map((st) => {
      const stn = m.stations[st];
      const waits = stn.teams.some((t) => t.waits);
      return el("section", { class: `office-station${waits ? " office-station-waits" : ""}`, "data-station": st },
        el("h3", { class: "office-station-title" }, stn.label),
        stn.teams.length ? stn.teams.map((t) => officeTeamButton(t, S.key === t.key, fresh.has(t.key), (k) => S.select(k)))
          : el("p", { class: "small muted office-empty" }, "這站沒有隊伍"),
        stn.more ? el("a", { class: "btn small office-more", href: "#/flows" }, `這站還有 ${stn.more} 隊 →`) : null);
    }));
  const desksBody = m.errors.runtime
    ? (runtimeNotice() || notice("warn", "無法連線到 VBear runtime，終端的資訊暫時看不到。"))
    : (m.desks.length ? el("div", { class: "office-desks-grid" }, m.desks.map((d) => officeDeskButton(d, S.key === d.key, fresh.has(d.key), (k) => S.select(k))))
      : el("p", { class: "small muted office-empty" }, "目前沒有出勤中的終端"));
  const loungeBody = m.errors.profiles
    ? notice("warn", `讀不到角色名冊：${m.errors.profiles}`)
    : (m.lounge.items.length ? el("div", { class: "office-lounge-grid" }, m.lounge.items.map((p) => officeProfileButton(p, S.key === p.key, (k) => S.select(k))))
      : el("p", { class: "small muted office-empty" }, "名冊裡還沒有角色"));
  return [
    el("section", { class: "office-section", "data-office-section": "stations" },
      el("h2", { id: "office-stations", tabindex: "-1" }, "工作站"),
      el("p", { class: "small muted" }, "任務在哪一站。站只表示任務的位置，不表示角色正在做什麼。"), stationsBody),
    el("section", { class: "office-section", "data-office-section": "desks" },
      el("h2", { id: "office-desks", tabindex: "-1" }, "辦公桌"),
      el("p", { class: "small muted" }, "出勤中的終端，頭上的字是它目前的狀態。"), desksBody),
    el("section", { class: "office-section", "data-office-section": "lounge" },
      el("h2", { id: "office-lounge", tabindex: "-1" }, "休息室"),
      el("p", { class: "small muted" }, "名冊：角色設定，不代表正在出勤。"),
      el("button", { type: "button", class: "btn small office-reload", "data-office-reload": "1",
        on: { click: () => S.reloadRoster() } }, "重新整理名冊"),
      loungeBody,
      m.lounge.more ? el("a", { class: "btn small office-more", href: "#/team" }, `還有 ${m.lounge.more} 個角色 →`) : null),
  ];
}

// ---- the phone's list ----

function officeRows(m) {
  const rows = new Map();
  for (const t of allOfficeTeams(m)) {
    rows.set(t.key, { key: t.key, name: officeTeamTitle(t), species: t.executor.species, camp: t.executor.camp,
      where: `任務在：${t.stationLabel}`, label: officeTeamLabel(t),
      badge: flowPhaseBadge({ key: t.phaseKey, label: t.phaseLabel, reason: t.phaseReason }), waits: t.waits });
  }
  for (const d of m.desks) {
    rows.set(d.key, { key: d.key, name: d.name, species: d.species, camp: d.camp, where: `辦公桌・${d.toolLabel}`,
      label: officeDeskLabel(d), badge: statusBadge(d.status, d.activity), waits: d.waits });
  }
  for (const p of m.lounge.items) {
    rows.set(p.key, { key: p.key, name: p.name, species: p.species, camp: p.camp, where: `休息室・${p.toolLabel}`,
      label: officeProfileLabel(p), badge: badge("名冊", "b-mute", "這是角色設定，不代表正在出勤"), waits: false });
  }
  return rows;
}

function officeListView(m, S) {
  const rows = officeRows(m);
  const flowsBlocked = m.errors.flows;
  return officeList(m).map((g) => {
    const body = [];
    if (g.id.startsWith("station-") && flowsBlocked) {
      if (g.id === "station-board") body.push(notice("warn", `讀不到流程：${flowsBlocked}`));
    } else if (g.id === "desks" && m.errors.runtime) {
      body.push(runtimeNotice() || notice("warn", "無法連線到 VBear runtime，終端的資訊暫時看不到。"));
    } else if (g.id === "lounge" && m.errors.profiles) {
      body.push(notice("warn", `讀不到角色名冊：${m.errors.profiles}`));
    } else if (!g.keys.length) {
      body.push(el("p", { class: "small muted office-empty" }, g.id === "turn" ? "目前沒有輪到你的" : "沒有"));
    } else {
      body.push(el("ul", { class: "office-rows" }, g.keys.map((key) => {
        const r = rows.get(key);
        return el("li", null, el("button", { type: "button", class: `office-row${r.waits ? " office-row-waits" : ""}`,
          "data-office-key": key, "aria-label": r.label, "aria-pressed": String(S.key === key),
          on: { click: () => S.select(key) } },
        officeSprite(r.species, r.camp, 2),
        el("span", { class: "office-row-text" },
          r.waits ? el("span", { class: "office-turn" }, el("span", { class: "office-turn-mark", "aria-hidden": "true" }, "!"), "輪到你") : null,
          el("strong", null, r.name), el("span", { class: "small muted" }, r.where)),
        r.badge));
      })));
    }
    if (g.more) body.push(el("a", { class: "btn small office-more", href: g.id === "lounge" ? "#/team" : "#/flows" },
      g.id === "lounge" ? `還有 ${g.more} 個角色 →` : `這站還有 ${g.more} 隊 →`));
    return el("section", { class: "office-section", "data-office-section": g.id.startsWith("station-") ? "stations" : g.id },
      el("h2", { id: `office-${g.id}`, tabindex: "-1" }, g.label), body);
  });
}

// ---- the view ----

async function readProfiles() {
  try {
    const r = await api.get("/api/agent-profiles");
    return Array.isArray(r.profiles) ? { profiles: r.profiles } : { error: "角色名冊的格式無法辨識", profiles: [] };
  } catch (e) { return { error: e.message, profiles: [] }; }
}

async function viewOffice() {
  const token = seq;
  await loadLive(false, FLOW_LIVE_TIMEOUT_MS);   // first: /api/flows only reads the live cache
  const [, profilesData] = await Promise.all([loadFlows(), readProfiles()]);
  if (token !== seq) return;
  const main = claim(token);
  const S = { key: "", name: "", station: "", notice: "", loadout: null, face: "front", profiles: profilesData, model: null, shownKey: "", mobile: officeIsMobile() };
  const fresh = new Set();
  const statusLine = el("p", { class: "small muted office-status", role: "status", "aria-live": "polite" });
  const root = el("div", { class: "office" });
  const computeModel = () => officeModel(D.live, D.flows, S.profiles, officeOverrides(S.profiles.profiles, store));

  const select = (key) => {
    const idx = officeIndex(S.model);
    if (!idx.has(key)) return;
    if (S.key !== key) S.face = "front";
    S.key = key; S.name = idx.get(key).name; S.station = idx.get(key).station || ""; S.notice = ""; statusLine.textContent = "";
    if (key.startsWith("profile:")) {
      const id = key.slice("profile:".length);
      if (!(S.loadout && S.loadout.key === key)) {
        S.loadout = { key, state: "loading" };
        api.get(`/api/agent-profiles/${encodeURIComponent(id)}/loadout`).then((data) => {
          if (S.key !== key) return;
          S.loadout = { key, state: "ok", data };
          renderPanelOnly();
        }).catch((e) => {
          if (S.key !== key) return;
          S.loadout = { key, state: "error", error: e.message };
          renderPanelOnly();
        });
      }
    } else S.loadout = null;
    render({ focusSpec: officeKeySpec(key), panelFocus: true });
  };
  S.select = select;
  const closePanel = () => {
    const was = S.key;
    S.key = ""; S.name = ""; S.station = ""; S.loadout = null; S.notice = "";
    render({ focusSpec: officeKeySpec(was) });
  };
  const setSpecies = (id, value) => {
    try { store.set(OFFICE_SPECIES_KEY + id, OFFICE_SPECIES.includes(value) ? value : null); } catch (_) { /* optional */ }
    S.model = computeModel();
    S.shownKey = officeKey(S.model);
    render({ focusSpec: officeKeySpec(`profile:${id}`) });
  };
  const pick = (kind) => {
    const m = S.model;
    const teams = allOfficeTeams(m);
    let key = "";
    if (kind === "turn") key = (teams.find((t) => t.waits) || {}).key || (m.desks.find((d) => d.waits) || {}).key || "";
    else if (kind === "working") key = (m.desks.find((d) => d.status === "working") || {}).key || "";
    else if (kind === "unknown") key = (m.desks.find((d) => d.status === "unknown") || {}).key || "";
    else key = (m.lounge.items[0] || {}).key || "";
    if (!key) {
      statusLine.textContent = { turn: "目前沒有輪到你的角色", working: "目前沒有工作中的終端", unknown: "目前沒有狀態未知的終端",
        roster: "名冊裡還沒有角色" }[kind];
      return;
    }
    select(key);
  };
  const handlers = { close: closePanel, species: setSpecies };

  function panelAside() {
    return el("aside", { class: "office-panel", "aria-label": "角色面板", "data-office-panel": S.key ? "open" : "idle" },
      officePanelContent(S.model, S, handlers));
  }
  let panelSlot = null;
  function panelNode() { panelSlot = el("div", { class: "office-panel-slot" }, panelAside()); return panelSlot; }
  // a late answer (the loadout) repaints the panel only: the focus and the scene are left alone
  function renderPanelOnly() {
    if (panelSlot && officeInside(root, panelSlot)) setKids(panelSlot, panelAside()); else render({});
  }
  function render(opts) {
    const m = S.model;
    for (const t of allOfficeTeams(m)) if (t.waits && !officeBadgeSeen.has(t.key)) { fresh.add(t.key); officeBadgeSeen.add(t.key); }
    for (const d of m.desks) if (d.waits && !officeBadgeSeen.has(d.key)) { fresh.add(d.key); officeBadgeSeen.add(d.key); }
    // a badge that went away is forgotten, so a later one fades in again
    for (const k of [...officeBadgeSeen]) {
      if (!allOfficeTeams(m).some((t) => t.key === k && t.waits) && !m.desks.some((d) => d.key === k && d.waits)) officeBadgeSeen.delete(k);
    }
    S.mobile = officeIsMobile();
    const head = el("header", { class: "office-head" },
      el("h1", null, "辦公室"),
      el("p", { class: "small muted" }, "每 5 秒更新・資料來自流程、終端與角色名冊，沒有的就不畫"),
      officeCountsBar(m, pick),
      el("nav", { class: "office-jumps", "aria-label": "跳到" }, S.mobile
        ? [["輪到你", "office-turn"], ["工作站", "office-station-board"], ["辦公桌", "office-desks"], ["休息室", "office-lounge"]]
          .map(([label, id]) => officeJump(label, id))
        : [["工作站", "office-stations"], ["辦公桌", "office-desks"], ["休息室", "office-lounge"]]
          .map(([label, id]) => officeJump(label, id))),
      statusLine);
    let body;
    if (m.allEmpty) {
      body = el("div", { class: "empty-state office-start" },
        el("strong", null, "辦公室目前沒有人。到終端工作台建立角色。"),
        el("a", { class: "btn primary", href: "#/workbench" }, "到終端工作台"));
    } else if (S.mobile) {
      body = S.key ? el("div", { class: "office-mobile-panel" }, panelNode())
        : el("div", { class: "office-list" }, officeListView(m, S));
    } else {
      body = el("div", { class: "office-layout" },
        el("div", { class: "office-scene" }, officeSections(m, S, fresh),
          el("div", { class: "office-counts-foot" }, officeCountsBar(m, pick))),
        panelNode());
    }
    fresh.clear();
    setKids(root, head, body);
    // the focus: back on the control it was on; when that control is gone, on the heading of its area
    // (never left on a removed node, never on the body)
    const o = opts || {};
    if (!(o.focusSpec && officeRestoreFocus(root, o.focusSpec))) {
      if (o.focusSection) officeFocusHeading(root, o.focusSection, S.mobile, o.focusStation);
      else if (o.focusSpec && o.focusSpec.attr === "data-office-key") officeFocusHeading(root, officeSectionOfKey(o.focusSpec.val), S.mobile);
    }
    if (opts && opts.panelFocus && S.mobile && S.key) {
      const title = document.getElementById("office-panel-title");
      if (title && title.focus) title.focus();
    }
  }
  function repaint(m, key) {
    const active = document.activeElement;
    const spec = officeFocusSpec(root, active);
    const inside = !!(active && officeInside(root, active));
    S.model = m;
    S.shownKey = key;
    let focusSpec = spec;
    let focusSection = "";
    let focusStation = "";
    if (S.key) {
      const prev = S.key;
      const r = restoreSelection({ key: S.key, name: S.name }, m);
      if (r.kept) { S.name = officeIndex(m).get(S.key).name; }
      else {
        const station = S.station;
        S.key = ""; S.name = ""; S.station = ""; S.loadout = null; S.notice = r.message;
        // the focus was on the selection, in its panel, or on something that went away with it: the area's heading
        const tied = inside && (!spec || spec.panel || (spec.attr === "data-office-key" && spec.val === prev));
        if (tied) { focusSpec = null; focusSection = r.focusSection; focusStation = station; }
      }
    }
    render({ focusSpec, focusSection, focusStation });
  }
  S.model = computeModel();
  S.shownKey = officeKey(S.model);
  root.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && S.key && !(e.isComposing)) { e.preventDefault(); closePanel(); }
  });
  render({});
  setKids(main, root);

  const onViewport = () => { if (officeIsMobile() !== S.mobile) render({}); };
  let mq = null;
  try { mq = window.matchMedia ? window.matchMedia(OFFICE_MOBILE_QUERY) : null; } catch (_) { mq = null; }
  if (mq && mq.addEventListener) mq.addEventListener("change", onViewport);
  officeTick = async () => {
    await loadLive();
    await loadFlows();
    const m = computeModel();
    const key = officeKey(m);
    if (key === S.shownKey) return;
    repaint(m, key);
  };
  activeViewCleanup = () => {
    officeTick = null;
    if (mq && mq.removeEventListener) mq.removeEventListener("change", onViewport);
  };
  // the roster is read when the page opens and again on request
  S.reloadRoster = async () => {
    S.profiles = await readProfiles();
    const m = computeModel();
    repaint(m, officeKey(m));
  };
}

function officeJump(label, id) {
  return el("a", { class: "office-jump btn small", href: "#/office", "data-office-jump": id,
    on: { click: (e) => {
      e.preventDefault();
      const t = document.getElementById(id);
      if (t) { t.focus(); if (t.scrollIntoView) t.scrollIntoView({ block: "start" }); }
    } } }, label);
}
function officeInside(root, node) {
  for (let n = node; n; n = n.parentNode) if (n === root) return true;
  return false;
}
const OFFICE_FOCUS_ATTRS = ["data-office-key", "data-office-count", "data-office-jump", "data-office-close",
  "data-office-reload", "data-office-species", "data-office-stage-toggle"];
function officeKeySpec(key) { return { attr: "data-office-key", val: key, ordinal: 0, panel: false }; }
function officeAll(root, attr) { return Array.from(root.querySelectorAll(`[${attr}]`)); }
// What the focus is on, as something that can be found again after a repaint (the nodes are new): the
// attribute that names it and its place among those with the same value.
function officeFocusSpec(root, node) {
  if (!node || !node.getAttribute || !officeInside(root, node)) return null;
  const id = node.getAttribute("id");
  if (id === "office-panel-title") return { attr: "id", val: id, ordinal: 0, panel: true };
  for (const attr of OFFICE_FOCUS_ATTRS) {
    const val = node.getAttribute(attr);
    if (val !== null && val !== undefined) {
      const same = officeAll(root, attr).filter((n) => n.getAttribute(attr) === val);
      return { attr, val, ordinal: Math.max(0, same.indexOf(node)),
        panel: attr === "data-office-close" || attr === "data-office-species" || attr === "data-office-stage-toggle" };
    }
  }
  if (id && node.getAttribute("tabindex") === "-1") return { attr: "id", val: id, ordinal: 0, panel: false };
  return null;
}
function officeRestoreFocus(root, spec) {
  let list;
  if (spec.attr === "id") { const n = document.getElementById(spec.val); list = n ? [n] : []; }
  else list = officeAll(root, spec.attr).filter((n) => n.getAttribute(spec.attr) === spec.val);
  const target = list[Math.min(spec.ordinal || 0, list.length - 1)];
  if (target && target.focus) { target.focus(); return true; }
  return false;
}
function officeSectionOfKey(key) {
  const kind = String(key).split(":")[0];
  return kind === "flow" ? "stations" : kind === "session" ? "desks" : "lounge";
}
function officeFocusHeading(root, section, mobile, station) {
  const ids = mobile ? { stations: `office-station-${OFFICE_STATIONS.includes(station) ? station : "board"}`,
    desks: "office-desks", lounge: "office-lounge" }
    : { stations: "office-stations", desks: "office-desks", lounge: "office-lounge" };
  const heading = document.getElementById(ids[section] || ids.stations);
  if (heading && heading.focus) heading.focus();
}

function projectCard(p) {
  const live = (D.live.sessions || []).filter((s) => s.project_id === p.project_id);
  return el("a", { class: "card", href: `#/projects/${p.project_id}` },
    el("div", { class: "card-top" },
      el("div", { style: "min-width:0" },
        el("div", { class: "card-title" }, p.name),
        el("div", { class: "card-sub mono" }, home(p.path) || p.basis)),
      live.length ? badge(`${live.length} 個開啟中的終端`, "b-info") : badge("沒有開啟中的終端", "b-mute")),
    el("div", { class: "stat-line" },
      p.git_branch ? el("span", null, "分支 ", el("b", null, p.git_branch)) : null,
      el("span", null, "近期工作階段 ", el("b", null, p.recent_session_ids.length)),
      p.last_activity ? el("span", null, "最後活動 ", el("b", null, ago(p.last_activity))) : null),
    live.length ? el("div", { class: "chips" }, live.slice(0, 4).map((s) => el("span", { class: "tag" }, s.role_label || TOOL[s.agent] || s.agent))) : null);
}

async function viewSkills(params) {
  const token = seq;
  await loadStatic();
  await refreshTranslations();
  const f = Object.assign({ q: "", tool: "", act: "active", scope: "", cat: "", mine: "", view: store.get("view", "card") }, store.get("skillFilters", {}), params);
  if (params.q !== undefined) f.q = params.q;
  const main = claim(token);

  const q = el("input", { type: "search", value: f.q, placeholder: "搜尋名稱、用途或描述（中英文皆可）", "aria-label": "搜尋技能" });
  const sel = (label, key, options, hint) => {
    const id = `skill-filter-${key}`;
    const s = el("select", { id, "aria-label": label, on: { change: () => { f[key] = s.value; save(); draw(); } } },
      options.map(([v, t]) => el("option", { value: v, selected: f[key] === v }, t)));
    // Keep the focusable help control outside the label: nesting it would make
    // the label activate the select instead of exposing the explanation.
    return el("div", { class: "filter-control" }, el("label", { for: id }, label),
      hint ? helpTip(label, hint) : null, s);
  };
  const seg = el("div", { class: "seg", role: "group", "aria-label": "顯示方式" },
    [["card", "卡片"], ["list", "列表"]].map(([v, t]) => el("button", { type: "button", "aria-pressed": String(f.view === v), on: { click: () => { f.view = v; store.set("view", v); seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.textContent === t))); draw(); } } }, t)));
  const count = el("span", { class: "count", "aria-live": "polite" });
  const out = el("div");
  const save = () => store.set("skillFilters", { tool: f.tool, act: f.act, scope: f.scope, cat: f.cat, mine: f.mine });
  const myTags = [...new Set(D.skills.flatMap((s) => ann(s).tags || []))].sort();

  // Results come in batches so a large library stays quick to paint; the
  // "more" button appends the next batch and a new filter starts over.
  const PAGE = { card: 240, list: 400 };
  let shown = 0;
  let hits = [];
  const card = ({ s, why }) => skillCard(s, why);
  const row = ({ s, why }) => el("tr", null,
    el("td", null, el("a", { href: `#/skills/${s.skill_id}` }, displayName(s)), displayName(s) !== s.name ? el("div", { class: "small muted mono" }, s.name) : null, (ann(s).tags || []).length ? el("div", { class: "chips" }, ann(s).tags.map((t) => el("span", { class: "tag mine" }, "#" + t))) : null, (s.duplicate_of || []).length ? el("div", null, badge(`同名 ${s.duplicate_of.length + 1} 份`, "b-warn")) : null),
    el("td", null, translationBadge(s.skill_id), firstSentence(translationDescription(s), 110) || el("span", { class: "muted" }, "未提供"), why.length ? el("div", { class: "small muted" }, "符合：" + why.join("、")) : null),
    el("td", null, TOOL[s.tool] || s.tool),
    el("td", null, SCOPE[s.scope] || s.scope, s.origin_package && s.origin_package.version ? el("div", { class: "small muted" }, s.origin_package.version) : null),
    el("td", null, actBadge(s.activation)));
  const more = el("button", { type: "button", class: "btn", style: "margin-top:14px", on: { click: showMore } });
  let holder = null;  // grid or tbody that the next batch is appended to

  function showMore() {
    if (token !== seq || !holder) return;
    const batch = hits.slice(shown, shown + PAGE[f.view === "list" ? "list" : "card"]);
    const nodes = batch.map(f.view === "list" ? row : card);
    append(holder, nodes);
    shown += batch.length;
    updateMore();
    // keep keyboard users where the new items start
    const first = nodes[0] && (nodes[0].matches("a") ? nodes[0] : nodes[0].querySelector("a"));
    if (first) first.focus();
  }
  function updateMore() {
    const left = hits.length - shown;
    more.hidden = left <= 0;
    more.textContent = `顯示更多（剩 ${left} 筆）`;
  }

  function draw() {
    let pool = D.skills;
    if (f.tool) pool = pool.filter((s) => s.tool === f.tool);
    if (f.act) pool = pool.filter((s) => s.activation === f.act);
    if (f.scope) pool = pool.filter((s) => s.scope === f.scope);
    if (f.cat) pool = pool.filter((s) => (s.categories || []).some((c) => c.id === f.cat));
    if (f.mine === "*") pool = pool.filter((s) => s.annotation);
    else if (f.mine) pool = pool.filter((s) => (ann(s).tags || []).includes(f.mine));
    hits = searchSkills(f.q, pool);
    shown = 0;
    holder = null;
    count.textContent = `${hits.length} / ${D.skills.length} 個技能紀錄`;
    if (!hits.length) {
      setKids(out, emptyState("沒有符合條件的技能", f.act === "active" ? "目前只顯示「可使用」的技能，可把狀態改成「全部」再找一次" : "試著放寬篩選條件"));
      return;
    }
    if (f.view === "list") {
      holder = el("tbody");
      setKids(out, el("div", { class: "panel table-wrap" }, el("table", { class: "list" },
        el("thead", null, el("tr", null, ["名稱", "用途", "工具", "範圍", "狀態"].map((h) => el("th", { scope: "col" }, h)))),
        holder)), more);
    } else {
      holder = el("div", { class: "grid" });
      setKids(out, holder, more);
    }
    const batch = hits.slice(0, PAGE[f.view === "list" ? "list" : "card"]);
    append(holder, batch.map(f.view === "list" ? row : card));
    shown = batch.length;
    updateMore();
  }
  const search = debounce(() => { f.q = q.value; history.replaceState(null, "", `#/skills${f.q ? "?q=" + encodeURIComponent(f.q) : ""}`); draw(); });
  q.addEventListener("input", search);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) search.now(); });

  const actOptions = [["active", "可使用"], ["", "全部"], ...Object.entries(ACT).filter(([k]) => k !== "active").map(([k, v]) => [k, v[0]])];
  setKids(main, 
    el("div", { class: "row" }, el("h1", null, "技能庫"), el("a", { class: "btn small", href: "#/armory" }, "技能四態總覽")),
    el("p", { class: "lede" }, "這裡是掃描到的技能清單。預設只顯示目前可使用的副本；想看安裝、加入角色與使用證據，請開啟「技能四態總覽」。 ", helpTip("技能庫", "技能庫只盤點掃描到的檔案與載入位置；它不會安裝、啟動或修改任何 Skill。")),
    corruptNotice(),
    staleNotice(),
    translationToolbar(),
    el("div", { class: "search" }, q),
    el("div", { class: "toolbar" },
      sel("狀態", "act", actOptions, "這是掃描到的載入狀態；可使用不代表目前有 Agent 正在使用。"),
      sel("工具", "tool", [["", "全部"], ["claude", "Claude Code"], ["codex", "Codex CLI"], ["shared", "skills CLI"]], "這是 Skill 所屬或可載入它的工具，不是目前正在執行的 Agent。"),
      sel("用途", "cat", [["", "全部"], ...D.categories.map((c) => [c.id, c.label])], "用途由主控台依描述關鍵字自動整理，不是作者的保證。"),
      sel("範圍", "scope", [["", "全部"], ...Object.entries(SCOPE)], "範圍是掃描到檔案的位置，例如使用者、專案、外掛或市集。"),
      sel("我的註記", "mine", [["", "不限"], ["*", "有註記的"], ...myTags.map((t) => [t, "#" + t])], "註記只存在 VBear，不會寫回原本的 Skill 檔案。"),
      seg, count),
    el("div", { class: "legend", style: "margin-bottom:12px" },
      el("span", null, "用途分類為", el("b", null, "自動整理"), "（依描述關鍵字），滑過標籤可看到命中的字。")),
    out);
  draw();
  let translationSignature = JSON.stringify(T.entries);
  const refreshResults = () => {
    if (!document.body.contains(out)) { T.listeners.delete(refreshResults); return; }
    const next = JSON.stringify(T.entries);
    if (next !== translationSignature) { translationSignature = next; draw(); }
  };
  T.listeners.add(refreshResults);
}

async function viewArmory() {
  const token = seq;
  const main = claim(token);
  setKids(main, el("p", { class: "loading" }, "載入技能四態總覽…"));
  let data;
  try { data = await api.get("/api/armory"); await refreshTranslations(); }
  catch (e) { setKids(main, crumbs([["技能庫", "#/skills"], ["四態總覽"]]), notice("bad", e.message)); return; }
  if (token !== seq) return;
  const state = (label, value, source, hint, cls) => el("div", { class: "armory-state" },
    el("div", { class: "armory-label" }, badge(label, cls), helpTip(label, hint)),
    el("span", { class: "small muted" }, "依據：", source), value);
  const rows = data.skills || [];
  setKids(main,
    crumbs([["技能庫", "#/skills"], ["四態總覽"]]),
    el("div", { class: "row" }, el("h1", null, "技能四態總覽"), el("a", { class: "btn small", href: "#/skills" }, "回技能庫")),
    el("p", { class: "lede" }, "四種狀態是唯讀觀察。已安裝、已加入角色與曾觀察到使用是不同事情；沒有證據就顯示未知。"),
    data.unresolved_equipped && data.unresolved_equipped.length
      ? notice("warn", `有 ${data.unresolved_equipped.length} 張角色卡引用的技能卡，目前索引找不到；不會自動刪除。`) : null,
    el("div", { class: "grid armory-grid" }, rows.map((s) => {
      const x = s.states || {}, loaded = x.loaded || {}, equipped = x.equipped || [];
      return el("div", { class: "card" },
        el("div", { class: "card-top" }, el("a", { href: `#/skills/${s.skill_id}`, class: "card-title" }, s.name), actBadge(s.activation)),
        el("div", null, el("button", { class: "btn small", type: "button",
          on: { click: () => openSkillCard(s.skill_id) } }, "技能卡特性")),
        translationBadge(s.skill_id),
        translationOf(s.skill_id).entry ? el("p", { class: "clamp" }, firstSentence(translationDescription(s), 170)) : null,
        el("div", { class: "card-sub mono" }, s.invoke_name || s.skill_id),
        el("div", { class: "armory-states" },
          state("市集可取得", x.available ? badge("可取得", "b-info") : badge("不適用", "b-mute"), s.sources.available,
            "只有市集中的未安裝副本才會顯示「可取得」；這不代表目前可用。", "b-info"),
          state("本機已安裝", x.installed ? badge("已安裝", "b-ok") : badge("未安裝／其他", "b-mute"), s.sources.installed,
            "已安裝代表掃描到本機副本；不代表正在被任何 Agent 使用。", "b-ok"),
          state("已加入角色", equipped.length
            ? el("div", { class: "chips" }, equipped.map((p) => el("a", { class: "tag", href: `#/workbench?profile=${encodeURIComponent(p.id)}` }, p.name || p.id, p.enabled ? null : "（角色卡已停用）")))
            : badge("未加入角色", "b-mute"), s.sources.equipped,
            "加入角色只是你替角色做的挑選紀錄；它不會自動啟動、載入或套用這個 Skill。", "b-accent"),
          state("使用證據", loaded.observed ? badge("曾觀察到使用", "b-warn") : badge("尚無證據", "b-mute"), s.sources.loaded,
            "只有執行紀錄確實觀察到使用時才會顯示；尚無證據不代表沒有載入。", "b-warn")));
    })));
  window.scrollTo(0, 0);
}

async function viewSkillDetail(id) {
  const token = seq;
  await loadStatic();
  await refreshTranslations();
  const main = claim(token);
  setKids(main, el("p", { class: "loading" }, "載入中…"));
  let d;
  try { d = await api.get(`/api/skills/${encodeURIComponent(id)}`); }
  catch (e) { setKids(main, crumbs([["技能庫", "#/skills"]]), notice("bad", e.message)); return; }
  if (token !== seq) return;
  const s = d.skill;
  const pkg = s.origin_package || {};
  const field = (title, src, emptyText) => el("div", { class: "field" },
    el("h3", null, title, prov(src)),
    src && src.value ? el("div", { class: "body" }, String(src.value)) : el("div", { class: "empty" }, emptyText || (src && src.detail) || "未提供"));

  const refs = s.referenced_files || [];
  const refBox = el("div");
  const refList = refs.length ? el("ul", { class: "tree" }, refs.map((r) => el("li", null,
    r.status === "present"
      ? el("button", { class: "btn small", type: "button", on: { click: () => openRef(s.skill_id, r.ref, refBox) } }, r.ref)
      : el("span", { class: "mono" }, r.ref), " ",
    r.status === "present" ? badge("存在", "b-ok") : r.status === "missing" ? badge("缺失", "b-bad", "指向技能內的資料夾，但檔案不存在") : badge("非套件檔案", "b-mute", "不在技能目錄內，可能只是文件中的範例路徑")))) : el("p", { class: "muted small" }, "沒有偵測到引用檔。");

  setKids(main, 
    crumbs([["技能庫", "#/skills"], [s.name]]),
    el("div", { class: "row" }, el("h1", null, (d.annotation && (d.annotation.aliases || [])[0]) || s.name), actBadge(s.activation), toolTag(s.tool)),
    d.annotation && (d.annotation.aliases || [])[0] ? el("p", { class: "small muted" }, "原名：", el("span", { class: "mono" }, s.name)) : null,
    s.invoke_name !== s.name ? el("p", { class: "small muted" }, "在工具中的呼叫名稱：", el("span", { class: "mono" }, s.invoke_name)) : null,
    el("p", { class: "lede" }, s.activation_reason),
    (s.warnings || []).length ? notice("warn", ["結構檢查：", s.warnings.join("；")]) : null,
    (s.missing_files || []).length ? notice("bad", `有 ${s.missing_files.length} 個引用檔缺失：${s.missing_files.join("、")}`) : null,
    el("div", { class: "grid-2 section" },
      el("div", { class: "panel pad" },
        el("h2", { style: "margin-bottom:12px" }, "這個技能能做什麼"),
        translationPanel(s.skill_id, el("div", null,
        field("一句話用途", s.description, "作者沒有提供 description"),
        field("使用時機", s.when_to_use),
        field("需要提供", s.inputs),
        field("預期產出", s.outputs),
        field("相依需求", s.dependencies))),
        (s.categories || []).length ? el("div", { class: "field" }, el("h3", null, "用途分類", prov({ origin: "derived", detail: "描述關鍵字" })),
          el("div", { class: "chips" }, s.categories.map((c) => el("span", { class: "tag cat" }, `${c.label}（命中「${c.keyword}」）`)))) : null),
      el("div", { style: "display:grid;gap:16px;align-content:start" },
        annotationPanel(s, d.annotation_key, d.annotation),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:10px" }, "已插在哪些角色卡上"),
          d.equipped_by && d.equipped_by.length ? el("div", null,
            el("p", { class: "small muted", "data-skill": "equipped-note" }, SKILL_EQUIPPED_NOTE),
            el("ul", { class: "tree", "data-skill": "equipped" }, d.equipped_by.map((p) => el("li", null,
              el("a", { href: `#/workbench?profile=${encodeURIComponent(p.id)}` }, p.name || p.id),
              " ", badge(CARD_SLOT_LABEL.collected + "（這次出發不載入）", "b-mute", CARD_SLOT_NOTE),
              el("span", { class: "small muted" }, `・角色卡本身${p.enabled ? "啟用中" : "已停用"}（你的挑選紀錄）`)))))
            : el("p", { class: "muted small" }, "沒有角色加入此技能。")),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:10px" }, "誰可以使用"),
          d.roles.length ? el("ul", { class: "tree" }, d.roles.map((r) => el("li", null,
            el("a", { href: `#/team/role/${r.role_id}` }, r.name), " ", el("span", { class: "small muted" }, BASIS[r.basis] || r.basis))))
            : el("p", { class: "muted small" }, s.activation === "active" ? "沒有角色宣告使用此技能。" : "此技能目前不在任何工具的載入範圍，沒有角色能直接使用。")),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:10px" }, "使用紀錄"),
          d.usage.length ? el("ul", { class: "tree" }, d.usage.slice(0, 12).map((u) => el("li", null,
            badge((EVIDENCE[u.evidence] || ["紀錄"])[0], (EVIDENCE[u.evidence] || [0, "b-mute"])[1], (EVIDENCE[u.evidence] || [0, 0, ""])[2]),
            " ", `${TOOL[u.tool] || u.tool}・${fmtTime(u.last_ts)}・${u.count} 次`, el("div", { class: "small muted mono" }, home(u.cwd)))))
            : el("p", { class: "muted small" }, `最近 ${(D.live && D.live.usage && D.live.usage.window_days) || 30} 天的紀錄中沒有使用過。`)),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:10px" }, "來源"),
          el("dl", { class: "kv small" },
            el("dt", null, "工具"), el("dd", null, TOOL[s.tool] || s.tool),
            el("dt", null, "範圍"), el("dd", null, SCOPE[s.scope] || s.scope),
            pkg.plugin ? [el("dt", null, "外掛"), el("dd", null, pkg.plugin, pkg.version ? `（${pkg.version}）` : "")] : null,
            pkg.installed_version ? [el("dt", null, "目前安裝版本"), el("dd", null, pkg.installed_version)] : null,
            pkg.commit ? [el("dt", null, "commit"), el("dd", { class: "mono" }, pkg.commit.slice(0, 12))] : null,
            pkg.upstream ? [el("dt", null, "上游"), el("dd", null, pkg.upstream, " ", prov({ origin: "author", detail: pkg.evidence }))] : null,
            pkg.project ? [el("dt", null, "專案"), el("dd", null, pkg.project)] : null,
            pkg.category ? [el("dt", null, "分類資料夾"), el("dd", null, pkg.category)] : null,
            el("dt", null, "檔案位置"), el("dd", { class: "mono" }, home(s.path)),
            el("dt", null, "檔案更新"), el("dd", null, fmtTime(s.mtime)),
            el("dt", null, "掃描時間"), el("dd", null, fmtTime(D.overview.generated_at)))))),
    d.duplicates.length ? el("section", { class: "section" },
      sectionHead(`同名技能（共 ${d.duplicates.length + 1} 份）`, "名稱相同但來源不同。主控台不會把它們合併，請依狀態與來源判斷哪一份會被使用。"),
      el("div", { class: "panel table-wrap" }, el("table", { class: "list" },
        el("thead", null, el("tr", null, ["來源", "範圍", "版本", "狀態", "位置"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", null,
          el("tr", null, el("td", null, el("b", null, "（目前這份）"), " ", TOOL[s.tool]), el("td", null, SCOPE[s.scope] || s.scope), el("td", null, pkg.version || "—"), el("td", null, actBadge(s.activation)), el("td", { class: "mono" }, home(s.path))),
          d.duplicates.map((x) => el("tr", null,
            el("td", null, el("a", { href: `#/skills/${x.skill_id}` }, TOOL[x.tool] || x.tool)),
            el("td", null, SCOPE[x.scope] || x.scope),
            el("td", null, (x.origin_package && x.origin_package.version) || "—"),
            el("td", null, actBadge(x.activation)),
            el("td", { class: "mono" }, home(x.path)))))))) : null,
    el("section", { class: "section" },
      sectionHead("引用檔", "技能文件中提到的相對路徑。只能開啟確認存在於技能目錄內的檔案。"),
      el("div", { class: "panel pad" }, refList, refBox)),
    el("section", { class: "section" },
      el("details", { class: "fold" },
        el("summary", null, "原始 SKILL.md", el("span", { class: "small muted" }, "（以純文字顯示，不執行任何內容）")),
        el("div", { class: "fold-body" }, d.raw_error ? notice("warn", d.raw_error) : el("pre", { class: "raw" }, d.raw)))),
  );
  window.scrollTo(0, 0);
}

function annotationPanel(s, key, a) {
  a = a || {};
  const aliases = el("input", { type: "text", value: (a.aliases || []).join(", "), placeholder: "例如：網站資安健檢", maxlength: 320 });
  const tags = el("input", { type: "text", value: (a.tags || []).join(", "), placeholder: "例如：上線前, 資安", maxlength: 720 });
  const note = el("textarea", { rows: 3, placeholder: "什麼時候用、用過的心得…", maxlength: 2000 }, a.note || "");
  const status = el("span", { class: "small muted", "aria-live": "polite" },
    a.updated_at ? `上次儲存 ${ago(a.updated_at)}` : "尚未加註記");
  const btn = el("button", { class: "btn primary small", type: "submit" }, "儲存註記");
  const form = el("form", { class: "annot", on: { submit: async (e) => {
    e.preventDefault(); btn.disabled = true;
    try {
      const r = await api.post("/api/annotations", { key, aliases: aliases.value, tags: tags.value, note: note.value });
      const saved = r.annotation && Object.keys(r.annotation).length ? r.annotation : null;
      for (const x of D.skills) if (x.annotation_key === key) x.annotation = saved;
      status.textContent = saved ? "已儲存" : "已清除註記";
      toast(saved ? "註記已儲存（只存在主控台）" : "已清除註記");
    } catch (err) { status.textContent = "儲存失敗：" + err.message; }
    finally { btn.disabled = false; }
  } } },
    el("label", null, el("span", null, "易懂名稱", el("small", null, "逗號分隔，第一個會顯示在卡片上")), aliases),
    el("label", null, el("span", null, "我的標籤", el("small", null, "逗號分隔")), tags),
    el("label", null, el("span", null, "備註"), note),
    el("div", { class: "row" }, btn, status));
  return el("div", { class: "panel pad" },
    el("h2", { style: "margin-bottom:4px" }, "我的註記"),
    el("p", { class: "small muted", style: "margin:0 0 10px" }, prov({ origin: "user" }), " 不會修改技能檔。套用到所有 ", el("span", { class: "mono" }, key), " 的副本，外掛升級後仍保留。"),
    form);
}

async function openRef(id, ref, box) {
  setKids(box, el("p", { class: "small muted" }, "載入中…"));
  try {
    const r = await api.get(`/api/skills/${encodeURIComponent(id)}/file?ref=${encodeURIComponent(ref)}`);
    setKids(box, el("h3", { style: "margin:14px 0 8px" }, ref), r.error ? notice("warn", r.error) : el("pre", { class: "raw" }, r.text));
  } catch (e) { setKids(box, notice("bad", e.message)); }
}

function crumbs(items) {
  return el("nav", { class: "crumbs", "aria-label": "路徑" },
    items.map(([t, h], i) => [i ? " / " : "", h ? el("a", { href: h }, t) : el("span", { class: "muted" }, t)]));
}

// ---------- the card pool (design card-play 3.1 to 3.3) ----------------------------------------------------
// A role card is an Agent Profile of the console. The words on screen are the card words (角色卡, 技能卡, 陣營,
// 權限意圖); the API field names are unchanged. Nothing here starts, loads or limits anything: a card is a record.

const CARD_POSITIONS = ["planner", "executor", "reviewer"];
const CARD_POSITION_LABEL = { planner: "規劃", executor: "執行", reviewer: "審查" };
// Where a person suggested a card for is a front-end preference (design 3.3): it is not a profile field.
const CARD_POSITION_KEY = "card.position.";
const CARD_INTENT_KEYS = [["read", "讀取檔案"], ["write", "編輯寫入"], ["test", "執行測試"], ["deploy", "部署上線"]];
const CARD_INTENT_LABEL = { allow: "允許", deny: "拒絕", unspecified: "還沒決定" };
const CARD_TOOL_LABEL = { claude: "Claude Code", codex: "Codex CLI", shared: "共用（skills CLI）" };
const CARD_TOOL_SHORT = { claude: "Claude Code", codex: "Codex", shared: "共用卡" };
// Always beside the intents (design R3): an intent is a team marker, not a limit VBear applies.
const CARD_INTENT_TITLE = "權限意圖（分工記號）";
const CARD_INTENT_NOTE = "權限意圖是隊伍分工的標記，不代表 VBear 已經限制這個程式的真實能力；真正的限制，看出發通行證上的盾牌。";
// Beside the suggested intents, after CARD_INTENT_NOTE (design v1.2 R10): why the suggestions are all the same set.
const CARD_INTENT_LAUNCH_NOTE = "目前 VBear 能啟動的只有這一組權限。想讓規劃者或審查者不改檔案，VBear 現在無法強制，請在任務卡的目標裡寫清楚。";
const CARD_SPECIES_NOTE = "種族只換外觀，不影響能力。";
const CARD_SKILLS_NOTE = "技能卡收藏在角色卡上，只是你的挑選紀錄（收藏中）：這次的安全啟動不會載入它們。";
const CARD_PAGE_SIZE = 48;
const CARD_DEFAULT_DEMO_PREFIX = "demo-";

function cardHas(obj, key) { return Object.prototype.hasOwnProperty.call(obj, key); }

function cardPosition(id) {
  const v = store.get(CARD_POSITION_KEY + id, null);
  return typeof v === "string" && CARD_POSITIONS.includes(v) ? v : null;
}
function setCardPosition(id, position) {
  store.set(CARD_POSITION_KEY + id, CARD_POSITIONS.includes(position) ? position : null);
}

// The suggested intents of a position, from the starter deck the server serves (design 3.3, v1.2 R10). The deck and
// the fallback for no position (or one the deck does not know) both come from the server: the one combination a
// managed launch honours (catalog.verified_intents). The page holds no copy of it; only when the catalog gives none
// are all four deny, which grants nothing.
function cardIntentsOf(src) {
  const out = {};
  for (const [k] of CARD_INTENT_KEYS) {
    if (!src || typeof src !== "object" || (src[k] !== "allow" && src[k] !== "deny")) return null;
    out[k] = src[k];
  }
  return out;
}
function verifiedIntents(catalog) { return cardIntentsOf(catalog && catalog.verified_intents); }
function permissionSuggestion(catalog, position) {
  const deck = catalog && Array.isArray(catalog.starter_deck) ? catalog.starter_deck : [];
  const hit = CARD_POSITIONS.includes(position) ? deck.find((c) => c && c.position === position) : null;
  return (hit && cardIntentsOf(hit.permission_intents)) || verifiedIntents(catalog)
    || { read: "deny", write: "deny", test: "deny", deploy: "deny" };
}

// The light on the card: green only when every intent is decided. It speaks for the intents alone; whether a launch
// can go ahead is what the launch pass says, and the card says so under the light.
function cardLight(p) {
  const intents = p && typeof p.permission_intents === "object" && p.permission_intents ? p.permission_intents : {};
  const undecided = CARD_INTENT_KEYS.filter(([k]) => intents[k] !== "allow" && intents[k] !== "deny").map(([, zh]) => zh);
  return undecided.length
    ? { state: "yellow", undecided, text: "還差一步：權限意圖還沒決定" }
    : { state: "green", undecided: [], text: "可以出發（權限意圖都已決定）" };
}

// Another card already carries this name: a hint only, never a block (design 3.1).
function sameNameCard(profiles, name, selfId) {
  const want = String(name || "").normalize("NFKC").trim().toLowerCase();
  if (!want) return null;
  return (Array.isArray(profiles) ? profiles : []).find((p) => p && p.id !== selfId
    && String(p.name || "").normalize("NFKC").trim().toLowerCase() === want) || null;
}

function isDemoCard(p, catalog) {
  const prefix = catalog && typeof catalog.demo_id_prefix === "string" && catalog.demo_id_prefix
    ? catalog.demo_id_prefix : CARD_DEFAULT_DEMO_PREFIX;
  return Boolean(p && typeof p.id === "string" && p.id.startsWith(prefix));
}

// Sample cards go last; within each group the server's order stays.
function sortCards(profiles, catalog) {
  const list = Array.isArray(profiles) ? profiles : [];
  return [...list.filter((p) => !isDemoCard(p, catalog)), ...list.filter((p) => isDemoCard(p, catalog))];
}

// Skill cards of the other tool's own, or of an unknown source, cannot be inserted: a Codex card does not read a
// Claude skill and the other way round. A shared skill fits any card; a shared card takes only shared skills.
function skillCompatible(skill, tool) {
  const source = skill && skill.tool;
  if (source === "shared") return true;
  return typeof source === "string" && source === tool;
}
function skillIncompatibleNote(tool) {
  return tool === "shared" ? "共用角色卡只能插共用的技能卡" : `${CARD_TOOL_SHORT[tool] || "這個工具"} 不會讀這張卡`;
}

function cardCatalogTools(catalog) {
  const tools = catalog && Array.isArray(catalog.tools) ? catalog.tools.filter((t) => typeof t === "string") : [];
  return tools.length ? tools : ["claude", "codex", "shared"];
}

function cardAvatar(p, scale = 3) {
  const tool = p && p.model && typeof p.model.tool === "string" ? p.model.tool : "";
  const override = store.get(OFFICE_SPECIES_KEY + (p ? p.id : ""), null);
  return officeSprite(speciesFor({ tool }, override), campOf({ tool }).key, scale);
}

function intentChip(k, zh, value) {
  return el("span", { class: "rc-chip" }, `${zh}・${CARD_INTENT_LABEL[value] || CARD_INTENT_LABEL.unspecified}`);
}

// ---- the wizard: name and look, then tool and position, then skill cards ------------------------------------

// opts: { catalog, profiles, existing, start (1-3), openIntents, onSaved(profile) }. The same wizard serves the card
// pool page and the workbench's role tab. Creating and editing are the same three steps.
function openCardWizard(opts) {
  const catalog = opts.catalog || {};
  const profiles = Array.isArray(opts.profiles) ? opts.profiles : [];
  const existing = opts.existing || null;
  const isNew = !existing;
  const tools = cardCatalogTools(catalog);
  const skillCatalog = Array.isArray(catalog.skills) ? catalog.skills : [];
  const skillById = new Map(skillCatalog.map((s) => [s.skill_id, s]));
  const professions = Array.isArray(catalog.professions) ? catalog.professions : [];
  const permissionKeys = CARD_INTENT_KEYS.map(([k]) => k);

  const st = {
    step: Math.min(3, Math.max(1, Number(opts.start) || 1)),
    name: existing ? String(existing.name || "") : "",
    species: existing ? (store.get(OFFICE_SPECIES_KEY + existing.id, null) || "") : "",
    tool: existing && existing.model && tools.includes(existing.model.tool) ? existing.model.tool
      : (tools.includes("claude") ? "claude" : tools[0]),
    position: existing ? cardPosition(existing.id) : null,
    modelId: existing && existing.model ? String(existing.model.model_id || "") : "",
    profession: existing && existing.profession_role_id ? existing.profession_role_id : "",
    // a new card starts from the suggestion for no position (the one combination a launch honours, R10); a card that
    // exists keeps its own choices
    intents: Object.fromEntries(permissionKeys.map((k) => [k,
      existing && existing.permission_intents && ["allow", "deny", "unspecified"].includes(existing.permission_intents[k])
        ? existing.permission_intents[k] : permissionSuggestion(catalog, null)[k]])),
    suggested: isNew,
    // an existing card's intents are its own choice: a position never overwrites them, it only offers its suggestion
    touched: !isNew,
    equipped: new Set(existing ? (existing.equipped_skill_ids || []).filter((x) => typeof x === "string") : []),
    query: "",
    shown: CARD_PAGE_SIZE,
    nameError: "",
    busy: false,
  };
  if (!OFFICE_SPECIES.includes(st.species)) st.species = "";
  let advancedOpen = false;
  let intentsOpen = Boolean(opts.openIntents);
  let removedNote = "";

  const titleId = "card-wizard-title";
  const body = el("div", { class: "cw-body" });
  const stepper = el("ol", { class: "cw-steps", "aria-label": "步驟" });
  const foot = el("div", { class: "modal-actions cw-foot" });
  const heading = el("h2", { id: titleId }, isNew ? "新角色卡" : `編輯角色卡：${existing.name || existing.id}`);
  const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    el("div", { class: "modal-box cw-box" }, heading, stepper, body, foot));
  document.body.append(modal);
  const closeModal = withModalA11y(modal, () => modal.remove());

  const STEP_TITLES = ["名字與外觀", "陣營與位置", "技能卡"];

  function drawStepper() {
    setKids(stepper, STEP_TITLES.map((t, i) => {
      const n = i + 1;
      const btn = el("button", { type: "button", class: "cw-step", "data-step": String(n),
        "aria-current": n === st.step ? "step" : null, "aria-label": `第 ${n} 步，共 3 步：${t}`,
        on: { click: () => goStep(n) } }, el("span", { class: "cw-step-n", "aria-hidden": "true" }, String(n)), t);
      return el("li", { class: n === st.step ? "cw-on" : (n < st.step ? "cw-done" : "") }, btn);
    }));
  }

  function goStep(n) {
    // a step is never entered with the name missing: the error shows at the name field
    if (n > 1 && !st.name.trim()) { st.step = 1; st.nameError = "請先替這張卡取個名字"; draw(); focusName(); return; }
    st.step = n;
    draw();
    // the button that was pressed is gone with the old step: keep the focus inside the dialog, on the step's name
    focusBy("data-step", String(n));
  }
  function focusName() { const f = body.querySelector("input"); if (f) f.focus(); }

  function nameHint() {
    const same = sameNameCard(profiles, st.name, existing ? existing.id : null);
    return same ? `已經有一張叫「${same.name}」的卡（只是提醒，仍然可以用這個名字）。` : "";
  }

  // ---- step 1
  function stepOne() {
    const hint = el("p", { class: "small cw-hint", "data-cw": "same-name", "aria-live": "polite" }, nameHint());
    const err = el("p", { class: "small cw-error", "data-cw": "name-error", role: "alert" }, st.nameError);
    const input = el("input", { type: "text", id: "cw-name", maxlength: "200", value: st.name, autocomplete: "off",
      "aria-describedby": "cw-name-hint cw-name-error", on: {
        input: (e) => { st.name = e.target.value; st.nameError = ""; hint.textContent = nameHint(); err.textContent = ""; },
        keydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); goStep(2); } } } });
    hint.id = "cw-name-hint"; err.id = "cw-name-error";
    const tool = st.tool;
    const camp = campOf({ tool }).key;
    const choices = [["", "依陣營"], ...OFFICE_SPECIES.map((sp) => [sp, OFFICE_SPECIES_LABEL[sp]])];
    const species = el("div", { class: "cw-species", role: "group", "aria-label": "種族（外觀）" },
      choices.map(([v, label]) => {
        const sp = v || speciesFor({ tool });
        return el("button", { type: "button", class: "cw-choice", "data-species": v || "auto",
          "aria-pressed": String(st.species === v), on: { click: () => { st.species = v; draw(); focusBy("data-species", v || "auto"); } } },
          officeSprite(sp, camp, 3), el("span", null, v ? label : `${label}（${OFFICE_SPECIES_LABEL[sp]}）`));
      }));
    return [
      el("label", { class: "cw-field", for: "cw-name" }, el("span", null, "名字"), input, err, hint),
      el("div", { class: "cw-field" }, el("span", { class: "cw-label" }, "種族（外觀）"), species,
        el("p", { class: "small muted" }, CARD_SPECIES_NOTE)),
    ];
  }

  // ---- step 2
  // Why the combination on the screen cannot be launched: asked of the server (agent_launch.intent_blockers) per
  // combination and remembered; the page holds no copy of the rules. The one combination the catalog names as
  // verified needs no question.
  const intentChecks = new Map();
  let intentBox = null;   // the box of the step on the screen; null when the step is not 2
  function intentKey() { return CARD_INTENT_KEYS.map(([k]) => st.intents[k]).join(","); }
  function intentIsVerified() {
    const v = verifiedIntents(catalog);
    return Boolean(v) && CARD_INTENT_KEYS.every(([k]) => st.intents[k] === v[k]);
  }
  function paintIntentCheck() {
    const box = intentBox;
    if (!box) return;
    const key = intentKey();
    const entry = intentChecks.get(key);
    if (intentIsVerified()) { box.setAttribute("hidden", ""); setKids(box); return; }
    box.removeAttribute("hidden");
    if (!entry || entry.state === "loading") {
      setKids(box, el("p", { class: "small muted" }, "檢查這個組合能不能出發…"));
      if (!entry) {
        intentChecks.set(key, { state: "loading" });
        const q = CARD_INTENT_KEYS.map(([k]) => `${k}=${encodeURIComponent(st.intents[k])}`).join("&");
        api.get(`/api/agent-builder/intent-check?${q}`)
          .then((r) => intentChecks.set(key, Array.isArray(r && r.blockers) ? { state: "ok", blockers: r.blockers } : { state: "error" }))
          .catch(() => intentChecks.set(key, { state: "error" }))
          .then(() => { if (intentKey() === key) paintIntentCheck(); });
      }
      return;
    }
    if (entry.state === "error") {
      setKids(box, el("p", { class: "small muted" }, "讀不到這個組合的檢查，實際能不能出發以出發通行證為準。"));
      return;
    }
    const reasons = entry.blockers.map((b) => (b && typeof b.message === "string" ? b.message : "")).filter(Boolean);
    if (!entry.blockers.length) { box.setAttribute("hidden", ""); setKids(box); return; }
    setKids(box, el("div", { class: "notice warn", role: "status" }, el("span", { class: "ico", "aria-hidden": "true" }, "!"),
      el("div", null, el("strong", null, "這個組合目前不能出發"),
        el("ul", { class: "small" }, (reasons.length ? reasons : ["原因未提供"]).map((r) => el("li", null, r))))));
  }

  function applySuggestion() {
    st.intents = permissionSuggestion(catalog, st.position);
    st.suggested = Boolean(st.position);
    st.touched = false;
  }
  function stepTwo() {
    const toolGroup = el("div", { class: "cw-choices", role: "group", "aria-label": "陣營（工具）" },
      tools.map((t) => el("button", { type: "button", class: "cw-choice", "data-tool": t,
        "aria-pressed": String(st.tool === t), on: { click: () => setTool(t) } },
        officeSprite(speciesFor({ tool: t }), campOf({ tool: t }).key, 2),
        el("span", null, CARD_TOOL_LABEL[t] || t))));
    const codexNote = st.tool === "codex" && catalog.codex_installed === false
      ? el("p", { class: "small cw-hint", "data-cw": "codex-missing" },
        "這台電腦找不到 Codex（沒有找到固定版本的安裝）。卡可以先建立。") : null;

    const posChoices = [["", "先不指定"], ...CARD_POSITIONS.map((p) => [p, CARD_POSITION_LABEL[p]])];
    const posGroup = el("div", { class: "cw-choices", role: "group", "aria-label": "建議位置" },
      posChoices.map(([v, label]) => el("button", { type: "button", class: "cw-choice",
        "data-position": v || "none", "aria-pressed": String((st.position || "") === v),
        on: { click: () => setPosition(v || null) } }, el("span", null, label))));

    const rows = CARD_INTENT_KEYS.map(([k, zh]) => {
      const values = ["allow", "deny", ...(st.intents[k] === "unspecified" ? ["unspecified"] : [])];
      const select = el("select", { id: `cw-intent-${k}`, "aria-label": zh, on: { change: (e) => {
        st.intents[k] = e.target.value; st.touched = true; st.suggested = false; draw();
        const again = document.getElementById(`cw-intent-${k}`); if (again) again.focus(); } } },
        values.map((v) => el("option", { value: v }, CARD_INTENT_LABEL[v])));
      select.value = st.intents[k];
      return el("div", { class: "cw-intent-row" }, el("label", { for: `cw-intent-${k}` }, zh), select);
    });
    const undecided = CARD_INTENT_KEYS.some(([k]) => st.intents[k] === "unspecified");
    const summary = el("div", { class: "rc-chips", "data-cw": "intent-summary" },
      CARD_INTENT_KEYS.map(([k, zh]) => intentChip(k, zh, st.intents[k])));
    const applyBtn = st.position && st.touched
      ? el("button", { type: "button", class: "btn small", "data-cw": "apply-suggestion",
        on: { click: () => { applySuggestion(); draw(); } } }, "套用這個位置的建議值") : null;
    const intents = el("details", { class: "cw-details", "data-cw": "intents", open: intentsOpen,
      on: { toggle: (e) => { intentsOpen = e.target.open; } } },
      el("summary", null, "調整權限"),
      el("div", { class: "cw-intent-grid" }, rows), applyBtn);

    const advanced = el("details", { class: "cw-details", "data-cw": "advanced", open: advancedOpen,
      on: { toggle: (e) => { advancedOpen = e.target.open; } } },
      el("summary", null, "進階"),
      el("label", { class: "cw-field", for: "cw-profession" },
        el("span", null, "職業標籤"),
        el("select", { id: "cw-profession", on: { change: (e) => { st.profession = e.target.value; } } },
          el("option", { value: "" }, "（不綁定）"),
          professions.map((r) => el("option", { value: r.role_id || "", selected: st.profession === r.role_id ? "selected" : null },
            `${r.name || r.role_id} (${r.tool || "?"})`))),
        el("small", null, "你電腦裡現成的角色範本，可以不選，只是標籤，不會寫回來源。")),
      el("label", { class: "cw-field", for: "cw-model" },
        el("span", null, "模型 (Model ID)"),
        el("input", { type: "text", id: "cw-model", maxlength: String(catalog.model_id_max_length || 200),
          placeholder: "例如 opus-4.1、gpt-test；留空視為該工具預設", value: st.modelId,
          on: { input: (e) => { st.modelId = e.target.value; } } }),
        el("small", null, `工具 ID：${st.tool}。模型設定只是記錄，不是執行環境。`)));
    const profSelect = advanced.querySelector("select");
    if (profSelect) profSelect.value = st.profession;

    return [
      el("div", { class: "cw-field" }, el("span", { class: "cw-label" }, "陣營"), toolGroup,
        el("p", { class: "small muted" }, "陣營就是這張卡用哪個工具。"), codexNote),
      el("div", { class: "cw-field" }, el("span", { class: "cw-label" }, "建議位置"), posGroup,
        el("p", { class: "small muted" }, "位置只是建議，放上任務卡時仍可以改。")),
      el("div", { class: "cw-field" },
        el("span", { class: "cw-label" }, "權限意圖",
          st.suggested ? el("span", { class: "tag cw-tag", "data-cw": "suggested" }, "建議，可改") : null),
        summary,
        undecided ? el("p", { class: "small cw-error" }, "有權限意圖還沒決定；出發前要先決定。") : null,
        el("p", { class: "small muted", "data-cw": "intent-note" }, CARD_INTENT_NOTE),
        el("p", { class: "small muted", "data-cw": "launch-note" }, CARD_INTENT_LAUNCH_NOTE),
        (intentBox = el("div", { "data-cw": "intent-check", "aria-live": "polite" })), intents),
      advanced,
    ];
  }

  // draw() rebuilds the step, so the control the person was on gets the focus back
  function focusBy(attr, value) {
    const n = [body, stepper, foot].flatMap((part) => Array.from(part.querySelectorAll("button")))
      .find((b) => b.getAttribute(attr) === value);
    if (n) n.focus();
  }

  function setTool(t) {
    st.tool = t;
    // skill cards the new tool does not read leave the card, and the person is told
    const gone = [...st.equipped].filter((sid) => {
      const s = skillById.get(sid);
      return s && !skillCompatible(s, t);
    });
    for (const sid of gone) st.equipped.delete(sid);
    removedNote = gone.length ? `換了陣營，已移除 ${gone.length} 張這個陣營不會讀的技能卡。` : "";
    draw();
    focusBy("data-tool", t);
  }
  function setPosition(v) {
    st.position = v;
    if (!st.touched) applySuggestion();
    draw();
    focusBy("data-position", v || "none");
  }

  // ---- step 3
  function stepThree() {
    const buttons = new Map();
    const countLabel = el("span", { class: "cw-label" });
    const chosenBox = el("div", { class: "cw-chosen", "data-cw": "chosen" });
    const list = el("div", { class: "cw-skill-list" });
    const note = el("p", { class: "small cw-hint", "data-cw": "removed-note", role: "status" }, removedNote);

    function syncChosen() {
      countLabel.textContent = `已插入（${st.equipped.size}）`;
      for (const [sid, b] of buttons) {
        const on = st.equipped.has(sid);
        b.setAttribute("aria-pressed", String(on));
        b.classList.toggle("cw-skill-on", on);
      }
      setKids(chosenBox, st.equipped.size ? [...st.equipped].map((sid) => {
        const s = skillById.get(sid);
        return el("span", { class: "tag cw-chosen-tag", "data-chosen": sid },
          s ? `${CARD_TOOL_SHORT[s.tool] || s.tool || "?"} · ${s.name}` : `${sid}（目前索引找不到）`, " ",
          el("button", { type: "button", class: "cw-x", "aria-label": `移除 ${s ? s.name : sid}`,
            on: { click: () => { st.equipped.delete(sid); syncChosen(); } } }, "移除"));
      }) : el("span", { class: "small muted" }, "還沒有插任何技能卡。這一步可以略過。"));
    }

    function drawList() {
      buttons.clear();
      const q = st.query.trim().toLowerCase();
      const hits = skillCatalog.filter((s) => !q || `${s.name || ""} ${s.excerpt || ""} ${s.tool || ""}`.toLowerCase().includes(q));
      if (!hits.length) {
        setKids(list, el("p", { class: "small muted" }, skillCatalog.length ? "沒有符合的技能卡。" : "目前沒有可用的技能卡。"));
        return;
      }
      const visible = hits.slice(0, st.shown);
      const grid = el("div", { class: "cw-skill-grid", "data-cw": "skill-grid" }, visible.map((s) => {
        const ok = skillCompatible(s, st.tool);
        const pick = skillPickText(s);
        const btn = el("button", { type: "button", class: `cw-skill${ok ? "" : " cw-skill-off"}`,
          "data-skill": s.skill_id, "aria-pressed": String(st.equipped.has(s.skill_id)),
          "aria-disabled": ok ? null : "true", title: ok ? null : skillIncompatibleNote(st.tool),
          on: { click: () => {
            if (!ok) return;
            if (st.equipped.has(s.skill_id)) st.equipped.delete(s.skill_id); else st.equipped.add(s.skill_id);
            syncChosen();
          } } },
          el("strong", null, s.name || s.skill_id),
          el("span", { class: "tag" }, CARD_TOOL_SHORT[s.tool] || s.tool || "?"),
          s.activation === "disabled" ? el("span", { class: "small muted" }, "（停用）") : null,
          pick.badge, pick.text ? el("span", { class: `small cw-skill-ex${pick.zh ? "" : " muted"}`, "data-cw": pick.zh ? "skill-zh" : "skill-en" }, pick.text) : null,
          ok ? null : el("span", { class: "small cw-error", "data-cw": "incompatible" }, skillIncompatibleNote(st.tool)));
        buttons.set(s.skill_id, btn);
        // the original is beside the card, not inside it: a button cannot hold another control
        return el("div", { class: "cw-skill-cell", "data-skill-cell": s.skill_id }, btn,
          pick.zh && s.excerpt ? el("details", { class: "small cw-skill-orig", "data-cw": "skill-orig" }, el("summary", null, "看原文"),
            el("p", { class: "small muted" }, s.excerpt)) : null);
      }));
      const more = hits.length > visible.length
        ? el("button", { type: "button", class: "btn small", "data-cw": "more",
          on: { click: () => { st.shown += CARD_PAGE_SIZE; drawList(); syncChosen(); } } },
          `顯示更多（剩 ${hits.length - visible.length} 張）`) : null;
      setKids(list, grid, more);
    }

    const search = el("input", { type: "search", id: "cw-skill-q", value: st.query, placeholder: "搜尋技能卡",
      "aria-label": "搜尋技能卡", on: { input: (e) => {
        st.query = e.target.value; st.shown = CARD_PAGE_SIZE; drawList(); syncChosen(); } } });
    drawList();
    syncChosen();
    // translations the page has not read yet arrive a moment later; the list is drawn again with them
    if (!T.loaded) refreshTranslations().then(() => { if (modal.contains(list)) { drawList(); syncChosen(); } }).catch(() => {});
    return [
      el("p", { class: "small muted", "data-cw": "skills-note" }, CARD_SKILLS_NOTE),
      removedNote ? note : null,
      el("div", { class: "cw-field" }, countLabel, chosenBox),
      el("div", { class: "cw-field" }, search), list,
    ];
  }

  // ---- footer + save
  function drawFoot() {
    const cancel = el("button", { class: "btn", type: "button", "data-cw": "cancel", on: { click: () => closeModal() } }, "取消");
    const back = st.step > 1 ? el("button", { class: "btn", type: "button", "data-cw": "back",
      on: { click: () => goStep(st.step - 1) } }, "上一步") : null;
    const next = st.step < 3 ? el("button", { class: "btn primary", type: "button", "data-cw": "next",
      on: { click: () => goStep(st.step + 1) } }, "下一步") : null;
    const save = (st.step === 3 || !isNew) ? el("button", { class: `btn${st.step === 3 ? " primary" : ""}`, type: "button",
      "data-cw": "save", disabled: st.busy, on: { click: submit } }, isNew ? "建立" : "儲存修改") : null;
    setKids(foot, cancel, back, next, save);
  }

  function draw() {
    drawStepper();
    intentBox = null;
    const parts = st.step === 1 ? stepOne() : st.step === 2 ? stepTwo() : stepThree();
    setKids(body, ...parts);
    if (st.step === 2) paintIntentCheck();
    drawFoot();
  }

  async function submit() {
    if (st.busy) return;
    const name = st.name.trim();
    if (!name) { st.step = 1; st.nameError = "請先替這張卡取個名字"; draw(); focusName(); return; }
    st.busy = true; drawFoot();
    try {
      const payload = {
        name,
        profession_role_id: st.profession || null,
        model: { tool: st.tool, model_id: st.modelId.trim() },
        equipped_skill_ids: [...st.equipped],
        permission_intents: Object.fromEntries(permissionKeys.map((k) => [k, st.intents[k] || "deny"])),
        enabled: existing ? !!existing.enabled : true,
      };
      const path = existing ? `/api/agent-profiles/${encodeURIComponent(existing.id)}` : "/api/agent-profiles";
      const res = await api.post(path, payload);
      const saved = res.profile;
      setCardPosition(saved.id, st.position);
      store.set(OFFICE_SPECIES_KEY + saved.id, st.species || null);
      toast(existing ? "角色卡已儲存" : "角色卡已建立");
      closeModal();
      if (typeof opts.onSaved === "function") await opts.onSaved(saved);
    } catch (err) {
      toast((isNew ? "建立失敗：" : "儲存失敗：") + err.message);
      st.busy = false; drawFoot();
      focusBy("data-cw", "save");
    }
  }

  draw();
  const first = body.querySelector("input");
  if (first && st.step === 1) first.focus();
  return { close: closeModal, state: st };
}

// ---- the starter deck ---------------------------------------------------------------------------------------

function openStarterDeck(opts) {
  const catalog = opts.catalog || {};
  const profiles = Array.isArray(opts.profiles) ? opts.profiles : [];
  const deck = Array.isArray(catalog.starter_deck) ? catalog.starter_deck : [];
  const codexMissing = catalog.codex_installed === false;
  const rows = deck.map((c) => ({ card: c, name: String(c.name || ""),
    checked: !(c.tool === "codex" && codexMissing), busy: false }));
  let busy = false;
  let message = "";   // what the last attempt did; kept when the buttons are redrawn
  const titleId = "starter-deck-title";
  const list = el("div", { class: "cw-deck" });
  const status = el("p", { class: "small", "aria-live": "polite", "data-cw": "deck-status" });
  const foot = el("div", { class: "modal-actions cw-foot" });
  const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    el("div", { class: "modal-box cw-box" },
      el("h2", { id: titleId }, "用起手牌組開始"),
      el("p", null, "三張現成的角色卡：規劃、執行、審查。名字可以改，建立後也能再編輯。"),
      el("div", { class: "cw-body" }, list, status), foot));
  document.body.append(modal);
  const closeModal = withModalA11y(modal, () => modal.remove());

  function hasReviewerPair() {
    const on = rows.filter((r) => r.checked);
    const exec = on.find((r) => r.card.position === "executor");
    const rev = on.find((r) => r.card.position === "reviewer");
    return !exec || !rev || exec.card.tool !== rev.card.tool;
  }

  function drawRows() {
    setKids(list, rows.map((r, i) => {
      const c = r.card;
      const inputId = `deck-name-${i}`;
      const missing = c.tool === "codex" && codexMissing;
      const hint = el("p", { class: "small cw-hint", "data-cw": "same-name", "aria-live": "polite" });
      const syncHint = () => {
        const same = sameNameCard(profiles, r.name, null);
        hint.textContent = same ? `已經有一張叫「${same.name}」的卡（只是提醒）。` : "";
      };
      syncHint();
      return el("div", { class: "cw-deck-row", "data-deck": c.key },
        el("input", { type: "checkbox", id: `deck-on-${i}`, checked: r.checked, disabled: busy,
          "aria-label": `建立「${r.name || c.name}」`, on: { change: (e) => { r.checked = e.target.checked; drawFoot(); } } }),
        el("div", { class: "cw-deck-main" },
          el("div", { class: "row", style: "gap:8px; align-items:center" },
            officeSprite(speciesFor({ tool: c.tool }), campOf({ tool: c.tool }).key, 2),
            el("span", { class: "tag" }, CARD_POSITION_LABEL[c.position] || "未指定"),
            el("span", { class: "tag" }, CARD_TOOL_LABEL[c.tool] || c.tool)),
          el("label", { class: "cw-field", for: inputId }, el("span", null, "名字"),
            el("input", { type: "text", id: inputId, maxlength: "200", value: r.name, disabled: busy,
              on: { input: (e) => { r.name = e.target.value; syncHint(); drawFoot(); } } })),
          hint,
          missing ? el("p", { class: "small cw-hint", "data-cw": "codex-missing" },
            "這台電腦找不到 Codex。審查位需要和工匠不同陣營的卡，要用這張卡時再勾選。") : null,
          el("details", { class: "cw-details" }, el("summary", null, "看權限建議"),
            el("div", { class: "rc-chips" }, CARD_INTENT_KEYS.map(([k, zh]) => intentChip(k, zh, c.permission_intents[k]))),
            el("p", { class: "small muted" }, CARD_INTENT_NOTE),
            el("p", { class: "small muted", "data-cw": "launch-note" }, CARD_INTENT_LAUNCH_NOTE))));
    }));
  }
  function drawFoot() {
    const n = rows.filter((r) => r.checked).length;
    const ok = n > 0 && rows.filter((r) => r.checked).every((r) => r.name.trim());
    setKids(foot,
      el("button", { class: "btn", type: "button", "data-cw": "cancel", disabled: busy, on: { click: () => closeModal() } }, "取消"),
      el("button", { class: "btn primary", type: "button", "data-cw": "deck-create", disabled: busy || !ok,
        on: { click: create } }, `建立 ${n} 張角色卡`));
    status.textContent = busy ? "" : (message || (hasReviewerPair() ? "" : "審查位需要和工匠不同陣營的卡，審查結果才算數；這兩張現在同一陣營。"));
  }
  async function create() {
    if (busy) return;
    busy = true; message = ""; drawRows(); drawFoot();
    const made = [];
    let failed = null;
    for (const r of rows.filter((x) => x.checked && !x.created)) {
      try {
        const res = await api.post("/api/agent-profiles", {
          name: r.name.trim(), profession_role_id: null, model: { tool: r.card.tool, model_id: "" },
          equipped_skill_ids: [], permission_intents: { ...r.card.permission_intents }, enabled: true });
        setCardPosition(res.profile.id, r.card.position);
        r.created = res.profile; r.checked = false;
        made.push(res.profile);
      } catch (err) { failed = { name: r.name.trim(), message: err.message }; break; }
    }
    busy = false;
    if (failed) {
      message = `${made.length ? `已建立 ${made.length} 張；` : ""}「${failed.name}」建立失敗：${failed.message}`;
      drawRows(); drawFoot();
      const retry = Array.from(foot.querySelectorAll("button")).find((b) => b.getAttribute("data-cw") === "deck-create");
      if (retry) retry.focus();
      if (made.length && typeof opts.onSaved === "function") opts.onSaved(made, { partial: true });
      return;
    }
    toast(`已建立 ${made.length} 張角色卡`);
    closeModal();
    if (typeof opts.onSaved === "function") await opts.onSaved(made, { partial: false });
  }
  drawRows(); drawFoot();
  const firstBox = list.querySelector("input");
  if (firstBox) firstBox.focus();
  return { close: closeModal, rows };
}

// ---- duplicate and delete (shared by the card pool and the workbench) -----------------------------------------

async function duplicateCard(p, onDone) {
  try {
    const res = await api.post(`/api/agent-profiles/${encodeURIComponent(p.id)}/duplicate`, {});
    const pos = cardPosition(p.id);
    if (pos) setCardPosition(res.profile.id, pos);
    toast("已建立副本：" + res.profile.name);
    if (typeof onDone === "function") await onDone(res.profile);
  } catch (err) { toast("複製失敗：" + err.message); }
}
function deleteCard(p, onDone) {
  if (!confirm(`確定要刪除角色卡「${p.name || p.id}」嗎？此動作不可回復。`)) return;
  api.post(`/api/agent-profiles/${encodeURIComponent(p.id)}/delete`, {})
    .then(async () => {
      toast("角色卡已刪除");
      store.set(CARD_POSITION_KEY + p.id, null);
      if (typeof onDone === "function") await onDone(p);
    })
    .catch((err) => toast("刪除失敗：" + err.message));
}

// Pixel art of the cards (art 20261017-cards v0.7.0-art-3, copied in; nothing is read from outside at run time).
// One character per cell, "." is clear. K is the outline: it takes its colour from the theme (style.css, .px-k), light
// #18181b, dark #f8fafc. The other characters are the same in both themes. The red of the vn is not used on a card.
const CARD_PALETTE = {
  K: "#18181b", W: "#fafaf9", Y: "#fde047", B: "#78350f",
  b: "#b45309", F: "#c2410c", f: "#fed7aa", S: "#52525b",
  s: "#d4d4d8", V: "#4c1d95", v: "#ddd6fe", O: "#d97706",
  o: "#ffedd5", T: "#0f766e", t: "#ccfbf1", G: "#0369a1",
  g: "#e0f2fe", P: "#7e22ce", p: "#f3e8ff", N: "#334155",
  n: "#e2e8f0",
};
const CARD_PIXELS = {
  backPattern: ["KKKKKKKKKKKKKKKK", "KnnnnKnnnnKnnnnK", "KnnKnnnnKnnKnnnK", "KnnnKnnYnnnnKnnK", "KKnnnnnnnnKnnnnK", "KnnnnnnnnnnnnnKK", "KnnKnnnnKnnKnnnK", "KnnnnKnnnnKnnnnK", "KKKKKKKKKKKKKKKK", "KnnnnKnnnnKnnnnK", "KnnKnnnnKnnKnnnK", "KnnnKnnYnnnnKnnK", "KKnnnnnnnnKnnnnK", "KnnnnnnnnnnnnnKK", "KnnKnnnnKnnKnnnK", "KKKKKKKKKKKKKKKK"],
  shields: {
    enforced: ["KKKKKKKKKKKK", "KTTTTTTTTTTK", "KTTTTTTTTTTK", "KTTTTTTTTTTK", "KTTTTTTTTTTK", "KTTTTTTTTTTK", ".KTTTTTTTTK.", ".KTTTTTTTTK.", "..KTTTTTTK..", "...KTTTTK...", "....KTTK....", ".....KK....."],
    recorded: ["K.K.K.K.K.K.", "...........K", "K...........", "...........K", "K...........", "...........K", ".K..........", "..........K.", "..K.........", "........K...", "....K.......", ".....KK....."],
    none: ["KKKKKKKKKKKK", "KK.........K", "K.K........K", "K..K.......K", "K...K......K", "K....K.....K", ".K....K...K.", ".K.....K..K.", "..K.....KK..", "...K....KK..", "....K..K..K.", ".....KK....."],
  },
  icons: {
    taskFolder: ["............", ".KKKK.......", "KYYYYK......", "KYYYYKKKKKK.", "KYYYYYYYYYYK", "KYYYYYYYYYYK", "KYYYYYYYYYYK", "KYYYYYYYYYYK", "KYYYYYYYYYYK", "KYYYYYYYYYYK", ".KKKKKKKKKK.", "............"],
    importProject: [".....KK.....", ".....YY.....", ".....YY.....", ".....YY.....", "..KKKYYKKK..", "...KYYYYK...", "....KYYK....", "K....KK....K", "K..........K", "KK........KK", ".KKKKKKKKKK.", "............"],
    emptySlot: ["............", "............", "..KKKKKKKK..", "..KnnnnnnK..", "..KnnKnnnK..", "..KnnKnnnK..", "..KnnKnnnK..", "..KnnKnnnK..", "..KnnnnnnK..", "..KKKKKKKK..", "............", "............"],
  },
};

// The position badge (art v3 positionBadges): a square with a hard 2px border and one Chinese character, drawn in CSS from
// the camp's tokens (--pos-bg, --pos-text, --pos-border in style.css). The 12x12 position pixel maps of v1 and v2 are not used.
const CARD_POSITION_BADGES = {
  planning: { glyph: "規", label: "規劃" },
  execution: { glyph: "執", label: "執行" },
  review: { glyph: "審", label: "審查" },
  unspecified: { glyph: "？", label: "未指定" },
};

// ---- the role card (design card-play 3.2, 3.4) ---------------------------------------------------------------
// One component for the card pool page and the office panel: the front is short, the back holds the detail. Both
// faces are always in the DOM; the one that is turned away is hidden and aria-hidden, so a screen reader reads only
// the face that is up. The card is a record of the console: nothing here starts, loads or limits anything.

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  return node;
}

// The cells of a pixel map as rects into `parent`: runs of one colour become one rect. The outline takes its colour
// from the theme (class px-k), every other colour is fixed.
function cardPixelRects(rows, parent) {
  const w = rows[0].length;
  rows.forEach((row, y) => {
    let x = 0;
    while (x < w) {
      const c = row[x];
      let end = x + 1;
      while (end < w && row[end] === c) end++;
      if (cardHas(CARD_PALETTE, c)) {
        const rect = { x, y, width: end - x, height: 1 };
        parent.append(svgEl("rect", c === "K" ? { ...rect, class: "px-k" } : { ...rect, fill: CARD_PALETTE[c] }));
      }
      x = end;
    }
  });
}

// A pixel map as an SVG, `scale` screen pixels to a cell. Decoration: the words next to it say the same thing.
function cardPixelSvg(rows, scale = 2) {
  const svg = svgEl("svg", { class: "card-px", viewBox: `0 0 ${rows[0].length} ${rows.length}`, width: rows[0].length * scale,
    height: rows.length * scale, "aria-hidden": "true", focusable: "false", "shape-rendering": "crispEdges" });
  cardPixelRects(rows, svg);
  return svg;
}

// group: shields | icons; null for a name the art does not have (the position badge is drawn by positionBadge).
function cardArt(group, name, scale = 2) {
  const set = cardHas(CARD_PIXELS, group) && group !== "backPattern" ? CARD_PIXELS[group] : null;
  if (!set || !cardHas(set, name)) return null;
  return cardPixelSvg(set[name], scale);
}

// The back of a card: the 16x16 pattern repeated along a strip (an SVG pattern, so it tiles at its own size).
let cardPatternSeq = 0;
function cardPatternStrip() {
  const id = `card-back-pattern-${++cardPatternSeq}`;
  const svg = svgEl("svg", { class: "card-pattern", width: "100%", height: 16, "aria-hidden": "true", focusable: "false", "shape-rendering": "crispEdges" });
  const tile = svgEl("pattern", { id, width: 16, height: 16, patternUnits: "userSpaceOnUse" });
  cardPixelRects(CARD_PIXELS.backPattern, tile);
  const defs = svgEl("defs");
  defs.append(tile);
  svg.append(defs, svgEl("rect", { x: 0, y: 0, width: "100%", height: 16, fill: `url(#${id})` }));
  return svg;
}

const CARD_POSITION_BADGE_KEY = { planner: "planning", executor: "execution", reviewer: "review" };
function cardPositionBadgeKey(position) { return cardHas(CARD_POSITION_BADGE_KEY, position) ? CARD_POSITION_BADGE_KEY[position] : "unspecified"; }
// The badge of a suggested position: the square with its one character (decoration, the words next to it say the same)
// and the words. The colours come from the camp frame the badge sits in.
function positionBadge(position) {
  const key = cardPositionBadgeKey(position);
  const b = CARD_POSITION_BADGES[key];
  return el("span", { class: "rcard-pos", "data-pcard": "position", "data-pos": key },
    el("span", { class: "pos-glyph", "aria-hidden": "true" }, b.glyph),
    el("span", { class: "pos-text" }, position ? `${CARD_POSITION_LABEL[position]}位` : "位置未指定"));
}

// The shield of an armor level, by the level word the server sends (agent_launch.py). Only the three levels that have a
// shield get one; partial, unverified, unknown and not-granted get none rather than a shield that says too much.
const ARMOR_LEVEL_SHIELD = {
  "強制（限已測路徑、版本與執行層）": "enforced",
  "僅意圖": "recorded",
  "未限制": "none",
};
function armorShieldKind(level) { return cardHas(ARMOR_LEVEL_SHIELD, level) ? ARMOR_LEVEL_SHIELD[level] : null; }
function armorShield(level) {
  const kind = armorShieldKind(level);
  return kind ? el("span", { class: `armor-shield armor-shield-${kind}`, "data-shield": kind }, cardArt("shields", kind, 2)) : null;
}

// ---- The launch pass (design card-play 3.7, 6.7) -----------------------------------------------------------------------
// The front of the pass is three lines. Each one is worded by the level the preview gives that item, so a check mark
// is only ever drawn for an enforced level; a level this table does not know reads as unknown, never as a protective
// one. The keys are the server's level words (agent_launch.py); a test compares them with its constants.
const PASS_LEVEL_KIND = {
  "強制（限已測路徑、版本與執行層）": "enforced",
  "部分強制": "partial",
  "未驗證（此 Claude Code 版本尚未實測）": "unverified",
  "未知": "unknown",
  "僅意圖": "open",
  "未限制": "open",
  "不授予": "unknown",
};
const PASS_KIND_MARK = { enforced: "ok", partial: "warn", unverified: "warn", unknown: "unknown", open: "bad" };
const PASS_KIND_WORD = { enforced: "已擋住", partial: "部分擋住", unverified: "未實測", unknown: "不明", open: "沒有擋住" };
const PASS_WRITE_TEXT = {
  enforced: (path) => `只能改這個資料夾：${path}`,
  partial: (path) => `大致只能改這個資料夾：${path}（部分擋住）`,
  unverified: () => "設定成只能改這個資料夾，但這個版本還沒實測",
  open: () => "寫入範圍沒有被擋住",
  unknown: () => "寫入範圍不明",
};
const PASS_NETWORK_TEXT = {
  enforced: "擋住網路",
  partial: "部分擋住網路",
  unverified: "設定成不連網，但這個版本還沒實測",
  open: "網路沒有被擋住",
  unknown: "網路防護不明",
};
// Where a launch may work: the folder the server allows (its managed_root), not an assumed home directory. If the page
// was not told, it says that rather than guessing.
function launchRangeText(live) {
  const root = live && typeof live.managed_root === "string" && live.managed_root ? live.managed_root : "";
  return root ? `可以選的範圍：${root} 之內、已經存在的資料夾。` : "可以選的範圍：伺服器允許的資料夾之內、已經存在的資料夾（這次讀不到實際範圍）。";
}
const PASS_WORKDIR_LABEL = "在哪裡做（工作資料夾）";
const PASS_COMMIT_TEXT = "擋不住版本紀錄（commit）";
const PASS_COMMIT_ACK = "我知道這個角色會在這個資料夾建立、修改檔案，也能存下版本紀錄（commit），VBear 擋不住。";
const PASS_SHIELD_LEGEND = [
  ["enforced", "實線盾牌：強制"],
  ["recorded", "虛線盾牌：只是記錄，沒有擋"],
  ["none", "空盾牌：沒擋"],
];
const PASS_LEGEND_NOTE = "部分擋住、未實測、不明的項目不畫盾牌，以文字為準。";
const PASS_DETAILS_LABEL = "看七項細節";

function passKind(level) { return typeof level === "string" && cardHas(PASS_LEVEL_KIND, level) ? PASS_LEVEL_KIND[level] : "unknown"; }

// preview -> { lines: [write, network, commit], workdir, scratch }. Reads derived_labels and canonical_paths only.
// A write line that names a folder it cannot name (no path) falls back to unknown; the commit line is the same
// words whatever its level says.
function passSummary(pv) {
  const labels = pv && pv.derived_labels && typeof pv.derived_labels === "object" ? pv.derived_labels : {};
  const paths = pv && pv.canonical_paths && typeof pv.canonical_paths === "object" ? pv.canonical_paths : {};
  const workdir = typeof paths.workdir === "string" ? paths.workdir : "";
  const scratch = typeof paths.scratch === "string" && paths.scratch ? paths.scratch : null;
  const levelOf = (name) => {
    const lab = cardHas(labels, name) ? labels[name] : null;
    return lab && typeof lab === "object" && typeof lab.level === "string" ? lab.level : null;
  };
  const make = (id, name, kind, text) => {
    const level = levelOf(name);
    return { id, name, level, kind, mark: PASS_KIND_MARK[kind], word: PASS_KIND_WORD[kind], text,
      shield: level === null ? null : armorShieldKind(level) };
  };
  let writeKind = passKind(levelOf("Write"));
  if ((writeKind === "enforced" || writeKind === "partial") && !workdir) writeKind = "unknown";
  const networkKind = passKind(levelOf("Network"));
  return {
    workdir, scratch,
    lines: [
      make("write", "Write", writeKind, PASS_WRITE_TEXT[writeKind](workdir)),
      make("network", "Network", networkKind, PASS_NETWORK_TEXT[networkKind]),
      make("commit", "Commit", "open", PASS_COMMIT_TEXT),
    ],
  };
}

// The mark in front of a line: a circle with a check (enforced), a triangle with an exclamation mark (partial or
// not tested), a circle with a question mark (unknown), a circle with a cross (not blocked). Different shapes, so
// the meaning does not rest on colour; the status word is written beside it too.
function passMark(mark) {
  const svg = svgEl("svg", { class: `pass-mark pass-mark-${mark}`, viewBox: "0 0 16 16", width: 16, height: 16,
    "aria-hidden": "true", focusable: "false" });
  const stroke = { fill: "none", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" };
  if (mark === "ok") svg.append(svgEl("circle", { cx: 8, cy: 8, r: 6.6, ...stroke }), svgEl("path", { d: "M5 8.2l2.2 2.3L11.2 5.8", ...stroke }));
  else if (mark === "warn") svg.append(svgEl("path", { d: "M8 1.8L14.6 13.6H1.4Z", ...stroke }), svgEl("path", { d: "M8 6v3.6M8 11.6v.4", ...stroke }));
  else if (mark === "unknown") svg.append(svgEl("circle", { cx: 8, cy: 8, r: 6.6, ...stroke, "stroke-dasharray": "2 2" }),
    svgEl("path", { d: "M6.2 6.4a1.9 1.9 0 1 1 2.8 1.7c-.6.4-1 .8-1 1.6M8 11.6v.4", ...stroke }));
  else svg.append(svgEl("circle", { cx: 8, cy: 8, r: 6.6, ...stroke }), svgEl("path", { d: "M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8", ...stroke }));
  return svg;
}

function passFront(pv) {
  const s = passSummary(pv);
  return el("section", { class: "pass-front", "data-pass": "front", "aria-label": "這次出發的限制" },
    el("ul", { class: "pass-lines" }, s.lines.map((ln) => el("li", { class: `pass-line pass-${ln.kind}`, "data-pass-line": ln.id, "data-kind": ln.kind },
      passMark(ln.mark),
      el("span", { class: "pass-text" }, ln.text),
      el("span", { class: "pass-word" }, ln.word),
      ln.shield ? armorShield(ln.level) : null))),
    s.scratch ? el("p", { class: "small muted pass-scratch" }, "另有這次出發的暫存區：", el("span", { class: "mono" }, s.scratch)) : null,
    passLegend());
}

function passLegend() {
  return el("div", { class: "pass-legend small muted", "data-pass": "legend" },
    el("span", { class: "pass-legend-title" }, "盾牌圖例："),
    PASS_SHIELD_LEGEND.map(([kind, label]) => el("span", { class: "pass-legend-item" },
      el("span", { class: `armor-shield armor-shield-${kind}`, "data-shield": kind }, cardArt("shields", kind, 2)), label)),
    el("span", { class: "pass-legend-note" }, PASS_LEGEND_NOTE));
}

// What can be done about a reason a launch is not possible. Only a pointer to where it is changed: the rules are the
// server's (launch_blockers), the page does not repeat them. A code with no entry has no fix here.
const PASS_FIXES = {
  intent_unspecified: { act: "intents", label: "現在決定" },
  read_deny_unenforceable: { act: "intents", label: "調整權限意圖" },
  readonly_unverified: { act: "intents", label: "調整權限意圖" },
  test_deny_unenforceable: { act: "intents", label: "調整權限意圖" },
  deploy_not_available: { act: "intents", label: "調整權限意圖" },
  intents_not_supported: { act: "intents", label: "調整權限意圖" },
  tool_not_launchable: { act: "tool", label: "改選陣營" },
  commit_not_enforceable: { act: "commit", label: "回去勾選知悉" },
};
function passFix(code) { return typeof code === "string" && cardHas(PASS_FIXES, code) ? PASS_FIXES[code] : null; }
// A preview that was refused because of the folder (the server answers 400 for a missing, relative or outside folder).
function passFolderFix(err) { return Boolean(err && err.status === 400) ? { act: "folder", label: "換資料夾" } : null; }

// The slots of a card (design 3.4). A slot is solid ("生效中") only when the loadout says will_load for that very
// skill; every other slot is dashed ("收藏中"), also before the loadout is read. The words are never compared.
const CARD_SLOT_LABEL = { collected: "收藏中", active: "生效中" };
const CARD_SLOT_NOTE = "這次的安全啟動不會載入";
// On a skill's page: "收藏中" is how the skill sits on a card (the same word as on the card); 啟用／已停用 is about the card itself.
const SKILL_EQUIPPED_NOTE = "「收藏中」是這張技能卡插在角色卡上的狀態，和卡面一樣：這次出發不會載入它。後面的「啟用中／已停用」只在說那張角色卡本身能不能出發。";
const CARD_SLOTS_SHOWN = 6;
function cardSlotState(item) { return item && item.will_load === true ? "active" : "collected"; }

// loadoutState: { state: "loading" | "ok" | "error", data } or null. rows follow the loadout when it is read (so a skill
// the index does not know is a row too), and the profile's own list before that.
function cardSlots(p, loadoutState, catalog) {
  const sk = loadoutState && loadoutState.state === "ok" && loadoutState.data && typeof loadoutState.data.skills === "object"
    ? loadoutState.data.skills : null;
  const names = new Map((catalog && Array.isArray(catalog.skills) ? catalog.skills : []).map((s) => [s.skill_id, s.invoke_name || s.name]));
  const ids = Array.isArray(p && p.equipped_skill_ids) ? p.equipped_skill_ids.filter((x) => typeof x === "string") : [];
  if (sk && Array.isArray(sk.items)) {
    const rows = sk.items.filter((x) => x && typeof x === "object" && typeof x.skill_id === "string").map((x) => ({
      id: x.skill_id, state: cardSlotState(x), name: x.invoke_name || x.name || names.get(x.skill_id) || x.skill_id,
      missing: x.state === "not_in_index", unread: x.state === "index_not_loaded" }));
    const active = rows.some((r) => r.state === "active");
    return { loaded: true, rows, active,
      allInactive: typeof sk.all_inactive === "boolean" ? sk.all_inactive && !active : null };
  }
  return { loaded: false, rows: ids.map((id) => ({ id, state: "collected", name: names.get(id) || id, missing: false, unread: false })),
    active: false, allInactive: null };
}

// One line on the front of a card about what a start does, made from the same armor items the pass is made from (the loadout's
// armor, built by agent_launch.armor_items). It is never more hopeful than the pass: writing is possible after a start, the
// reach of that writing is worded by the item's own level, and a commit is never said to be stopped (the pass says the
// same). Unreadable armor, a tool with none, or an item missing: no line at all.
const CARD_PASS_WRITE_REACH = { enforced: "（限工作資料夾）", partial: "（範圍只部分擋住）", unverified: "（範圍限制還沒實測）",
  unknown: "（範圍不明）", open: "（範圍沒有被擋住）" };
function cardPassLine(loadoutState) {
  const ar = loadoutState && loadoutState.state === "ok" && loadoutState.data && typeof loadoutState.data.armor === "object"
    ? loadoutState.data.armor : null;
  if (!ar || ar.applicable !== true || !Array.isArray(ar.items)) return null;
  const level = (name) => {
    const it = ar.items.find((x) => x && typeof x === "object" && x.name === name && typeof x.level === "string");
    return it ? it.level : null;
  };
  const write = level("Write");
  const commit = level("Commit");
  if (write === null || commit === null) return null;
  return `出發後可以改檔案${CARD_PASS_WRITE_REACH[passKind(write)]}；擋不住 commit；詳情看出發通行證`;
}

const CARD_CODEX_NOTE = "放在任務卡的審查位時，自動模式會派它在暫存副本裡審查；也可以手動記錄審查結果。";

// What the light says. Yellow is the intents (as cardLight); once they are all decided, green is only for a loadout that
// was read and lists no reason against a launch. Not read yet, not readable, or with reasons: not green.
function cardDeparture(p, loadoutState) {
  const base = cardLight(p);
  if (base.state === "yellow") return { ...base, reasons: [] };
  if (!loadoutState || loadoutState.state === "loading") return { state: "checking", text: "確認出發條件中…", reasons: [] };
  const blockers = loadoutState.state === "ok" && loadoutState.data ? loadoutState.data.blockers : null;
  if (!Array.isArray(blockers)) return { state: "unknown", text: "讀不到出發條件，實際能不能出發以出發通行證為準", reasons: [] };
  const reasons = blockers.map((b) => (b && typeof b.message === "string" ? b.message : "")).filter(Boolean);
  const shown = reasons.length ? reasons : ["原因未提供"];
  // Codex cannot open a terminal from VBear today, but a Codex card on a review place is used by the flow (the automatic
  // review runs it in a scratch copy): when every reason starts with codex_ the light is this fifth, neutral state
  // (design v1.2 R11). Any other reason, even beside those, keeps the red.
  if (blockers.length && blockers.every((b) => b && typeof b.code === "string" && b.code.startsWith("codex_"))) {
    return { state: "codex", text: "不能直接開終端", note: CARD_CODEX_NOTE, reasons: shown };
  }
  if (blockers.length) return { state: "blocked", text: "目前不能出發", reasons: shown };
  return { ...base, reasons: [] };
}

// opts: { catalog, handlers: { launch, decide, edit, duplicate, remove }, loadout, face, onFace(face), backExtra }.
// A button shows only when its handler is given. Returns { node, setLoadout(state) }: a late loadout repaints the parts
// that depend on it and leaves the buttons alone.
function profileCard(p, opts = {}) {
  const catalog = opts.catalog || null;
  const handlers = opts.handlers || {};
  const tool = p.model && typeof p.model.tool === "string" ? p.model.tool : "";
  const camp = campOf({ tool });
  const pos = cardPosition(p.id);
  const demo = isDemoCard(p, catalog);
  const launchOff = p.enabled === false;
  const name = p.name || p.id;
  const intents = p.permission_intents && typeof p.permission_intents === "object" ? p.permission_intents : {};
  let loadoutState = opts.loadout || null;
  let face = opts.face === "back" ? "back" : "front";

  const slotsBox = el("div", { class: "rcard-slots", "data-pcard": "slots" });
  const lightBox = el("div", { "data-pcard": "light", role: "status" });
  const passLineBox = el("p", { class: "small rcard-passline", "data-pcard": "pass-line", hidden: "" });
  const profBox = el("dd", { "data-rc": "profession" });
  const evidenceBox = el("dd", { "data-rc": "evidence" });
  const englishBox = el("dd", { "data-rc": "english" });
  const reasonBox = el("section", { class: "rcard-block", "data-rc": "blockers" });

  const flipButton = (label, aria) => el("button", { type: "button", class: "btn small rcard-flip", "data-pcard": "flip",
    "aria-keyshortcuts": "F", "aria-label": aria, title: `${label}（按 F）`, on: { click: () => setFace(face === "front" ? "back" : "front", true) } }, label);
  const frontFlip = flipButton("翻面", `翻面，看「${name}」的背面`);
  const backFlip = flipButton("翻回正面", `翻回「${name}」的正面`);

  const front = el("div", { class: "rcard-face rcard-front", "data-face": "front", role: "group", "aria-label": `${name} 的正面` },
    el("div", { class: "rcard-head" }, cardAvatar(p),
      el("div", { class: "rcard-title" },
        el("h3", null, name),
        el("div", { class: "chips" },
          el("span", { class: "tag" }, CARD_TOOL_LABEL[tool] || tool || "未知陣營"),
          positionBadge(pos),
          demo ? badge("示範", "b-info", "範例資料，不是你建立的卡") : null,
          launchOff ? badge("停用", "b-mute", "已停用，但保留存檔") : null))),
    slotsBox, lightBox, passLineBox,
    el("p", { class: "small muted", "data-pcard": "roster" }, "名冊，不代表正在出勤"),
    el("div", { class: "rcard-actions" },
      handlers.launch ? el("button", { type: "button", class: "btn small primary", "data-pcard": "launch", disabled: launchOff,
        title: launchOff ? "這張卡已停用" : "先看這次出發會套用什麼，確認後才啟動",
        on: { click: () => handlers.launch(p) } }, "出發") : null,
      handlers.place ? el("button", { type: "button", class: "btn small", "data-pcard": "place",
        title: "把這張卡放進一張任務卡的隊伍（規劃、執行或審查位）",
        on: { click: () => handlers.place(p) } }, "放上任務卡") : null,
      frontFlip));

  const chips = el("div", { class: "rc-chips" }, CARD_INTENT_KEYS.map(([k, zh]) => intentChip(k, zh, intents[k])));
  const back = el("div", { class: "rcard-face rcard-back", "data-face": "back", role: "region", "aria-label": `${name} 的背面`, tabindex: "0" },
    el("div", { class: "rcard-pattern", "aria-hidden": "true" }, cardPatternStrip()),
    el("div", { class: "rcard-back-head" }, el("strong", null, `${name}・背面`), backFlip),
    el("dl", { class: "rcard-dl" },
      el("dt", null, "陣營與模型"),
      el("dd", null, `${CARD_TOOL_LABEL[tool] || tool || "未知陣營"}・${(p.model && p.model.model_id) || "未指定（視為該工具預設值）"}`),
      el("dt", null, "職業標籤"), profBox,
      el("dt", null, "證據來源"), evidenceBox),
    el("section", { class: "rcard-block", "data-rc": "intents" },
      el("h4", null, CARD_INTENT_TITLE),
      el("p", { class: "small" }, "只是記錄，不是授權。"),
      el("p", { class: "small muted", "data-rc": "intent-note" }, CARD_INTENT_NOTE),
      chips),
    reasonBox,
    (handlers.edit || handlers.duplicate || handlers.remove) ? el("div", { class: "rcard-actions" },
      handlers.edit ? el("button", { type: "button", class: "btn small", "data-pcard": "edit", on: { click: () => handlers.edit(p) } }, "編輯") : null,
      handlers.duplicate ? el("button", { type: "button", class: "btn small", "data-pcard": "duplicate", on: { click: () => handlers.duplicate(p) } }, "複製") : null,
      handlers.remove ? el("button", { type: "button", class: "btn small", "data-pcard": "remove", on: { click: () => handlers.remove(p) } }, "刪除") : null) : null,
    opts.backExtra || null,
    el("details", { class: "fold rcard-advanced", "data-rc": "advanced" },
      el("summary", null, "進階"),
      el("dl", { class: "rcard-dl" },
        el("dt", null, "Tool ID"), el("dd", { class: "mono" }, tool || "—"),
        el("dt", null, "Model ID"), el("dd", { class: "mono" }, (p.model && p.model.model_id) || "—"),
        el("dt", null, "角色卡 ID"), el("dd", { class: "mono" }, p.id),
        el("dt", null, "英文說明"), englishBox)));

  const article = el("article", { class: `rcard${demo ? " rcard-demo" : ""}`, "data-profile-id": p.id, "data-camp": camp.key,
    "data-face": face, "aria-label": `角色卡：${name}`,
    on: { keydown: (e) => {
      const t = e.target && e.target.tag ? String(e.target.tag).toUpperCase() : (e.target && e.target.tagName) || "";
      if ((e.key !== "f" && e.key !== "F") || e.ctrlKey || e.metaKey || e.altKey) return;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t) || (e.target && e.target.isContentEditable)) return;
      e.preventDefault();
      setFace(face === "front" ? "back" : "front", true);
    } } }, front, back);

  function reducedMotion() {
    try { return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (_) { return false; }
  }
  function applyFace() {
    const showFront = face === "front";
    for (const [node, shown] of [[front, showFront], [back, !showFront]]) {
      if (shown) node.removeAttribute("hidden"); else node.setAttribute("hidden", "");
      node.setAttribute("aria-hidden", String(!shown));
    }
    article.setAttribute("data-face", face);
  }
  function setFace(next, moveFocus) {
    if (next === face) return;
    face = next;
    applyFace();
    if (typeof opts.onFace === "function") opts.onFace(face);
    if (!reducedMotion()) {
      article.classList.add("rcard-turn");
      setTimeout(() => article.classList.remove("rcard-turn"), 400);
    }
    // the button that was pressed is now hidden: the same button of the face that is up takes the focus
    if (moveFocus) (face === "front" ? frontFlip : backFlip).focus();
  }

  function paint() {
    const slots = cardSlots(p, loadoutState, catalog);
    const shown = slots.rows.slice(0, CARD_SLOTS_SHOWN);
    setKids(slotsBox,
      el("div", { class: "rcard-slots-head small" }, `技能卡 ${slots.rows.length} 張`,
        (p._unresolved && p._unresolved.skills || []).length ? `；${p._unresolved.skills.length} 張目前索引找不到` : ""),
      slots.rows.length
        ? el("ul", { class: "rcard-slot-list" }, shown.map((r) => el("li", { class: `rcard-slot rcard-slot-${r.state}`, "data-slot": r.state },
          el("span", { class: "rcard-slot-name" }, r.name),
          el("span", { class: "rcard-slot-label" }, CARD_SLOT_LABEL[r.state]))),
        slots.rows.length > shown.length ? el("li", { class: "rcard-slot-more small muted" }, `另有 ${slots.rows.length - shown.length} 張`) : null)
        : el("p", { class: "small muted rcard-slot-empty" }, cardArt("icons", "emptySlot", 1), "沒有插技能卡"),
      slots.allInactive === true ? el("p", { class: "small muted", "data-slot-note": "inactive" }, CARD_SLOT_NOTE)
        : slots.loaded ? null : el("p", { class: "small muted" }, "技能卡只是你的挑選紀錄"));

    const passText = cardPassLine(loadoutState);
    if (passText) { passLineBox.removeAttribute("hidden"); setKids(passLineBox, passText); }
    else { passLineBox.setAttribute("hidden", ""); setKids(passLineBox); }

    const dep = cardDeparture(p, loadoutState);
    lightBox.className = `rcard-light rcard-${dep.state}`;
    lightBox.setAttribute("data-light", dep.state);
    setKids(lightBox,
      el("span", { class: "rcard-dot", "aria-hidden": "true" }),
      el("div", null, el("strong", null, dep.text),
        dep.state === "yellow"
          ? (handlers.decide ? el("div", null, el("button", { type: "button", class: "btn small", "data-pcard": "decide",
            on: { click: () => handlers.decide(p) } }, "現在決定")) : null)
          : dep.state === "blocked"
            ? el("div", { class: "small" }, dep.reasons[0], dep.reasons.length > 1 ? `（另有 ${dep.reasons.length - 1} 項，翻到背面看）` : "")
            : dep.state === "codex"
              ? el("div", { class: "small", "data-pcard": "codex-note" }, dep.note,
                el("div", { class: "muted" }, "原因翻到背面看。"))
              : el("div", { class: "small muted" }, "實際能不能出發，以出發通行證為準。")));

    const ld = loadoutState && loadoutState.state === "ok" && loadoutState.data ? loadoutState.data : null;
    const pr = ld && ld.profession && typeof ld.profession === "object" ? ld.profession : null;
    let profText = "載入中…";
    if (loadoutState && loadoutState.state === "error") profText = "讀不到職業標籤";
    else if (pr) {
      profText = pr.state === "found" ? (pr.name || pr.role_id) : pr.state === "none" ? "（未選職業標籤）"
        : pr.state === "not_in_index" ? `${pr.role_id}（目前索引找不到這個職業）` : `${pr.role_id || ""}（索引未載入）`;
    } else if (!loadoutState) profText = p.profession_role_id ? String(p.profession_role_id) : "（未選職業標籤）";
    setKids(profBox, profText, pr ? el("span", { class: "small muted" }, "　只是標籤，不會把角色指示載入工具") : null);
    setKids(evidenceBox, "這張卡的設定：你自己在主控台建立（使用者意圖）",
      pr && pr.state === "found" && pr.description ? el("div", { class: "small" }, "職業標籤的說明：", prov(pr.description)) : null);
    const desc = pr && pr.state === "found" && pr.description ? pr.description.value : null;
    setKids(englishBox, desc ? String(desc) : "—");

    const reasons = dep.state === "blocked" || dep.state === "codex" ? dep.reasons : [];
    if (reasons.length) {
      reasonBox.removeAttribute("hidden");
      setKids(reasonBox, el("h4", null, dep.state === "codex" ? "不能直接開終端的原因" : "目前不能出發的原因"),
        el("ul", { class: "small" }, reasons.map((r) => el("li", null, r))),
        el("p", { class: "small muted" }, ld && ld.blockers_note ? ld.blockers_note : ""));
    } else {
      reasonBox.setAttribute("hidden", "");
      setKids(reasonBox);
    }
  }
  applyFace();
  paint();
  return { node: article, setLoadout(state) { loadoutState = state; paint(); } };
}

// ---- the page: 角色卡池 -------------------------------------------------------------------------------------

// Reads the loadout of each id with at most `limit` requests in flight; gone() stops the queue (the page was left).
function readLoadouts(ids, onState, gone, limit = 4) {
  const queue = [...ids];
  const next = async () => {
    while (queue.length && !gone()) {
      const id = queue.shift();
      let state;
      try {
        state = { state: "ok", data: await api.get(`/api/agent-profiles/${encodeURIComponent(id)}/loadout`) };
      } catch (e) { state = { state: "error", error: e && e.message ? e.message : "未知錯誤" }; }
      if (gone()) return;
      onState(id, state);
    }
  };
  for (let i = 0; i < Math.min(limit, queue.length); i++) next();
}

async function viewTeam() {
  const token = seq;
  const [, , profilesRes, catalogRes] = await Promise.all([loadStatic(), loadLive(),
    api.get("/api/agent-profiles").then((r) => ({ ok: true, profiles: (r && r.profiles) || [] }))
      .catch((e) => ({ ok: false, error: e.message, profiles: [] })),
    api.get("/api/agent-builder/catalog").then((r) => (r && r.ok ? r : null)).catch(() => null)]);
  const main = claim(token);
  const L = D.live;
  const catalog = catalogRes;
  const profiles = sortCards(profilesRes.profiles, catalog);
  const tview = store.get("teamView", "card");
  const filter = cardHas(CARD_TOOL_LABEL, store.get("teamCardTool", "")) ? store.get("teamCardTool", "") : "";
  const sessions = [...L.sessions].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9));
  const cli = D.roles.filter((r) => r.kind === "cli");
  const subs = D.roles.filter((r) => r.kind !== "cli");

  const refresh = () => viewTeam();
  const handlers = {
    edit: (p) => openCardWizard({ catalog, profiles, existing: p, onSaved: refresh }),
    decide: (p) => openCardWizard({ catalog, profiles, existing: p, start: 2, openIntents: true, onSaved: refresh }),
    duplicate: (p) => duplicateCard(p, refresh),
    remove: (p) => deleteCard(p, refresh),
    launch: (p) => { location.hash = `#/workbench?profile=${encodeURIComponent(p.id)}&launch=1`; },
    place: (p) => openPlaceDialog(p, { profiles }),
  };
  const needCatalog = (fn) => () => {
    if (!catalog) { toast("角色卡目錄尚未就緒，請稍後再試"); return; }
    fn();
  };
  const hasOwnCard = profiles.some((p) => !isDemoCard(p, catalog));
  const actions = el("div", { class: "pool-actions" },
    el("button", { type: "button", class: "btn primary", "data-pool": "new",
      on: { click: needCatalog(() => openCardWizard({ catalog, profiles, existing: null, onSaved: refresh })) } }, "＋ 新角色卡"),
    !hasOwnCard && profilesRes.ok
      ? el("button", { type: "button", class: "btn", "data-pool": "starter",
        on: { click: needCatalog(() => openStarterDeck({ catalog, profiles, onSaved: refresh })) } }, "用起手牌組開始") : null);

  const shown = filter ? profiles.filter((p) => p.model && p.model.tool === filter) : profiles;
  const filterBar = el("div", { class: "seg", role: "group", "aria-label": "依陣營篩選" },
    [["", "全部"], ...Object.entries(CARD_TOOL_LABEL)].map(([v, t]) => el("button", { type: "button", "data-filter": v || "all",
      "aria-pressed": String(filter === v), on: { click: () => { store.set("teamCardTool", v); viewTeam(); } } }, t)));

  // each card reads its own loadout (a read-only answer from memory), four at a time; the page does not wait for them
  const cards = new Map(shown.map((p) => [p.id, profileCard(p, { catalog, handlers })]));
  readLoadouts(shown.map((p) => p.id), (id, state) => { const c = cards.get(id); if (c) c.setLoadout(state); }, () => token !== seq);

  const poolBody = !profilesRes.ok
    ? notice("bad", "無法讀取角色卡：" + profilesRes.error)
    : !profiles.length
      ? emptyState("還沒有角色卡", "按「＋ 新角色卡」自己做一張，或用起手牌組一次拿三張。")
      : shown.length
        ? el("div", { class: "grid pool-grid" }, shown.map((p) => cards.get(p.id).node))
        : emptyState("這個陣營還沒有角色卡", null);

  const liveBlock = tview === "list"
    ? el("div", { class: "panel table-wrap" }, el("table", { class: "list" },
        el("thead", null, el("tr", null, ["名稱", "工具", "狀態", "本次模型", "專案", "本次用過的技能", ""].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", null, sessions.map((x) => el("tr", null,
          el("td", null, el("b", null, x.role_label || "未命名"), el("div", { class: "small muted mono" }, x.pane_id)),
          el("td", null, TOOL[x.agent] || x.agent),
          el("td", null, statusBadge(x.status, x.activity)),
          el("td", null, modelList(x.models_observed).join("、") || el("span", { class: "muted" }, "未知")),
          el("td", null, ((L.projects || []).find((p) => p.project_id === x.project_id) || {}).name || "—"),
          el("td", null, (x.skills_used || []).length ? el("div", { class: "chips" }, x.skills_used.slice(0, 3).map(usedChip)) : el("span", { class: "muted" }, "—")),
          el("td", null,
            el("a", { class: "btn small primary", href: `#/term/${encodeURIComponent(x.pane_id)}`, title: "開啟終端機串流" }, "終端")))))))
    : el("div", { class: "grid" }, sessions.map(sessionCard));

  const seg = el("div", { class: "seg", role: "group", "aria-label": "顯示方式" },
    [["card", "卡片"], ["list", "表格"]].map(([v, t]) => el("button", { type: "button", "aria-pressed": String(tview === v), on: { click: () => { store.set("teamView", v); viewTeam(); } } }, t)));

  setKids(main,
    el("h1", null, "角色卡池"),
    el("p", { class: "lede" }, "這裡收集你的角色卡。每張卡是一份可以重複使用的角色設定；開啟中的終端在下方，兩者不同：一張卡可以同時有多個終端。"),
    runtimeNotice(),
    el("section", { class: "section" },
      sectionHead("我的角色卡", `${profiles.length} 張`, el("div", { class: "pool-tools" }, filterBar)),
      actions,
      poolBody),
    el("section", { class: "section" },
      sectionHead("開啟中的終端", `${sessions.length} 個，由 VBear runtime 管理`, seg),
      sessions.length ? liveBlock : emptyState("沒有開啟中的終端", L.runtime && L.runtime.available ? "從角色卡按「出發」，確認後會出現在這裡" : "VBear runtime 未連線")),
    el("details", { class: "fold section", "data-pool": "templates" },
      el("summary", null, "你電腦裡現成的角色範本（職業標籤）", el("span", { class: "small muted", style: "font-weight:400" }, `${cli.length + subs.length} 個`)),
      el("div", { class: "fold-body" },
        el("p", { class: "small muted" }, "這些是掃描到的唯讀設定，只能當作職業標籤，不會寫回來源。"),
        sectionHead("主代理", "直接在終端機執行的工具本身"),
        el("div", { class: "grid" }, cli.map(roleCard)),
        sectionHead("角色設定（子代理）", `${subs.length} 個設定檔`),
        subs.length ? el("div", { class: "grid" }, subs.map(roleCard)) : emptyState("沒有找到子代理設定", "可在設定頁確認掃描來源"))),
    el("div", { class: "legend section" },
      el("span", null, el("b", null, "本次模型"), "：從對話紀錄觀察到的實際模型"),
      el("span", null, el("b", null, "預設模型"), "：設定檔中的預設值，實際執行可能不同")),
  );
}
const STATUS_ORDER = { "needs-input": 0, waiting: 1, working: 2, unknown: 3, exited: 4 };

async function viewRole(id) {
  const token = seq;
  await Promise.all([loadStatic(), loadLive()]);
  const r = D.roles.find((x) => x.role_id === id);
  const main = claim(token);
  if (!r) { setKids(main, crumbs([["角色卡池", "#/team"]]), notice("bad", "找不到這個角色（索引可能已更新）")); return; }
  const sessions = r.kind === "cli" ? D.live.sessions.filter((s) => s.agent === r.tool) : [];
  const field = (title, src) => src && (src.value || src.origin !== "missing")
    ? el("div", { class: "field" }, el("h3", null, title, prov(src)), src.value ? el("div", { class: "body" }, String(src.value)) : el("div", { class: "empty" }, src.detail)) : null;
  const skills = r.skills || [];
  const q = el("input", { type: "search", placeholder: "在這個角色的技能中搜尋", "aria-label": "搜尋角色技能" });
  const PAGE_SIZE = 120;
  let shown = 0;
  let hits = [];
  const card = ({ s, why }) => skillCard(s, why);
  const more = el("button", { type: "button", class: "btn", style: "margin-top:14px", on: { click: showMore } });
  let holder = null;
  const list = el("div", null);

  function showMore() {
    if (token !== seq || !holder) return;
    const batch = hits.slice(shown, shown + PAGE_SIZE);
    const nodes = batch.map(card);
    append(holder, nodes);
    shown += batch.length;
    updateMore();
    const first = nodes[0] && (nodes[0].matches("a") ? nodes[0] : nodes[0].querySelector("a"));
    if (first) first.focus();
  }

  function updateMore() {
    const left = hits.length - shown;
    more.hidden = left <= 0;
    more.textContent = `顯示更多（剩 ${left} 筆）`;
  }

  const draw = () => {
    const pool = skills.map((x) => D.byId.get(x.skill_id)).filter(Boolean);
    hits = searchSkills(q.value, pool);
    shown = 0;
    holder = null;
    if (!hits.length) {
      setKids(list, emptyState("沒有符合的技能", null));
      return;
    }
    holder = el("div", { class: "grid" });
    setKids(list, holder, more);
    const batch = hits.slice(0, PAGE_SIZE);
    append(holder, batch.map(card));
    shown = batch.length;
    updateMore();
  };
  const search = debounce(draw, 200);
  q.addEventListener("input", search);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) search.now(); });

  setKids(main, 
    crumbs([["角色卡池", "#/team"], [r.name]]),
    el("div", { class: "row" }, el("div", { class: "avatar", "aria-hidden": "true" }, r.emoji || initialOf(r.name)), el("h1", null, r.name), toolTag(r.tool)),
    el("p", { class: "lede" }, r.kind === "cli" ? "主代理：直接在終端機執行的工具。" : "角色設定：可以被主代理委派工作的子代理。"),
    (r.warnings || []).map((w) => notice("warn", w)),
    el("div", { class: "grid-2 section" },
      el("div", { class: "panel pad" },
        el("h2", { style: "margin-bottom:12px" }, "工作範疇"),
        field("說明", r.description), field("能力", r.capabilities), field("適合的工作", r.suitable_tasks), field("限制", r.limits),
        !r.capabilities?.value && !r.limits?.value && r.kind !== "cli" ? el("p", { class: "small muted" }, "設定檔沒有另外寫明能力與限制。") : null),
      el("div", { class: "panel pad" },
        el("h2", { style: "margin-bottom:12px" }, "模型與執行"),
        el("dl", { class: "kv small" },
          el("dt", null, "預設模型"), el("dd", null, (r.model && r.model.value) || "未指定", " ", prov(r.model)),
          el("dt", null, "設定檔"), el("dd", { class: "mono" }, r.path ? home(r.path) : "（工具本身，沒有單一設定檔）"),
          el("dt", null, "開啟中"), el("dd", null, r.kind === "cli" ? `${sessions.length} 個終端` : "目前無法辨識子代理的執行個體")),
        sessions.length ? el("ul", { class: "tree", style: "margin-top:12px" }, sessions.map((s) => el("li", null,
          el("b", null, s.role_label || s.pane_id), " ", statusBadge(s.status, s.activity), " ",
          el("span", { class: "small muted" }, modelList(s.models_observed).join("、") || "模型未知")))) : null)),
    el("section", { class: "section" },
      sectionHead(`可用技能（${r.kind === "cli" || r.skill_link_basis === "declared" ? skills.length : "未宣告"}）`, BASIS[r.skill_link_basis] || ""),
      skills.length ? [el("div", { class: "search", style: "margin-bottom:12px" }, q), list]
        : emptyState(r.skill_link_basis === "declared" ? "宣告的技能都不在可使用清單中" : "這個角色的設定檔沒有宣告技能", "主控台不會替它猜測；若它會繼承主代理的技能，需要在設定檔中寫明才能確認")),
  );
  if (skills.length) draw();
}

async function viewProjects(id) {
  const token = seq;
  await Promise.all([loadStatic(), loadLive()]);
  const L = D.live;
  const main = claim(token);
  const projects = L.projects || [];
  if (id) {
    const p = projects.find((x) => x.project_id === id);
    if (!p) { setKids(main, crumbs([["專案", "#/projects"]]), notice("bad", "找不到這個專案")); return; }
    setKids(main, crumbs([["專案", "#/projects"], [p.name]]), projectDetail(p));
    return;
  }
  const active = projects.filter((p) => p.live_session_ids.length);
  const rest = projects.filter((p) => !p.live_session_ids.length);
  setKids(main, 
    el("h1", null, "專案"),
    el("p", { class: "lede" }, "依工作目錄的 git 儲存庫歸類。專案是目標與資料歸屬；開啟中的終端依工作目錄對應到專案。"),
    runtimeNotice(),
    el("section", { class: "section" },
      sectionHead("有開啟中終端的專案", `${active.length} 個專案`),
      active.length ? el("div", { style: "display:grid;gap:12px" }, active.map((p) => projectFold(p, true))) : emptyState("目前沒有開啟中終端的專案", null)),
    el("section", { class: "section" },
      sectionHead("最近有紀錄", `最近 ${L.usage.window_days} 天的工作階段`),
      rest.length ? el("div", { style: "display:grid;gap:12px" }, rest.map((p) => projectFold(p, false))) : emptyState("沒有其他紀錄", null)));
}

function projectFold(p, open) {
  const L = D.live;
  const live = L.sessions.filter((s) => s.project_id === p.project_id);
  const byWs = new Map();
  for (const s of live) { const k = s.workspace_label || s.workspace_id; if (!byWs.has(k)) byWs.set(k, []); byWs.get(k).push(s); }
  return el("details", { class: "fold", open },
    el("summary", null, p.name,
      live.length ? badge(`${live.length} 個開啟中的終端`, "b-info") : null,
      el("span", { class: "small muted", style: "font-weight:400" }, p.last_activity ? `・${ago(p.last_activity)}` : ""),
      el("span", { class: "spacer" }), el("a", { class: "btn small", href: `#/projects/${p.project_id}` }, "詳情")),
    el("div", { class: "fold-body" },
      el("div", { class: "small muted mono", style: "margin-bottom:8px" }, home(p.path), p.git_branch ? ` · ${p.git_branch}` : ""),
      live.length ? el("ul", { class: "tree" }, [...byWs.entries()].map(([ws, list]) => el("li", null,
        el("span", { class: "small muted" }, "群組 "), el("b", null, ws),
        el("ul", { class: "tree" }, list.map((s) => el("li", { class: "row" },
          el("b", null, s.role_label || s.pane_id), statusBadge(s.status, s.activity), el("span", { class: "tag" }, TOOL[s.agent] || s.agent),
          (s.skills_used || []).slice(0, 3).map(usedChip),
          el("a", { class: "btn small", href: `#/term/${encodeURIComponent(s.pane_id)}` }, "開啟"))))))) : el("p", { class: "small muted" }, "沒有開啟中的終端。"),
      p.skills_used.length ? el("div", { class: "chips", style: "margin-top:10px" }, el("span", { class: "small muted" }, "近期用過："),
        p.skills_used.slice(0, 8).map(([name, n]) => el("span", { class: "tag" }, `${name} ×${n}`))) : null));
}

function projectDetail(p) {
  const L = D.live;
  const live = L.sessions.filter((s) => s.project_id === p.project_id);
  const recent = L.usage.sessions.filter((s) => s.project_id === p.project_id).sort((a, b) => (b.last_ts > a.last_ts ? 1 : -1));
  const projSkills = (p.project_skill_ids || []).map((i) => D.byId.get(i)).filter(Boolean);
  return el("div", null,
    el("h1", null, p.name),
    el("p", { class: "lede" }, el("span", { class: "mono" }, home(p.path)), p.git_branch ? `　分支 ${p.git_branch}` : "", `　（判斷依據：${p.basis}）`),
    el("section", { class: "section" },
      sectionHead("開啟中的終端", `${live.length} 個`),
      live.length ? el("div", { class: "grid" }, live.map(sessionCard)) : emptyState("目前沒有", null)),
    projSkills.length ? el("section", { class: "section" },
      sectionHead("專案專屬技能", "放在這個專案目錄裡的技能"),
      el("div", { class: "grid" }, projSkills.map((s) => skillCard(s)))) : null,
    el("section", { class: "section" },
      sectionHead("近期工作階段", `${recent.length} 個（最近 ${L.usage.window_days} 天）`),
      recent.length ? el("div", { class: "panel table-wrap" }, el("table", { class: "list" },
        el("thead", null, el("tr", null, ["時間", "工具", "模型", "用過的技能", "工作階段"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", null, recent.slice(0, 50).map((s) => el("tr", null,
          el("td", null, fmtTime(s.last_ts)),
          el("td", null, TOOL[s.tool] || s.tool),
          el("td", null, modelList(s.models).join("、") || el("span", { class: "muted" }, "—")),
          el("td", null, s.skills.length ? el("div", { class: "chips" }, s.skills.slice(0, 4).map(usedChip)) : el("span", { class: "muted" }, "—")),
          el("td", { class: "mono small" }, s.session_id.slice(0, 8))))))) : emptyState("沒有紀錄", null)));
}

// The lobby's 新手第一局 can be put away from the lobby (config key onboarding_dismissed); this brings it back.
function onboardingSettings(conf, saveConf) {
  const dismissed = conf.onboarding_dismissed === true;
  const btn = el("button", { class: "btn small", type: "button", "data-onboard": dismissed ? "show" : "hide", on: { click: async () => {
    const r = await saveConf({ onboarding_dismissed: !dismissed }, dismissed ? "大廳會再顯示新手第一局" : "大廳不再顯示新手第一局");
    if (r) viewSettings();
  } } }, dismissed ? "重新顯示大廳的新手第一局" : "不要再顯示新手第一局");
  return el("section", { class: "panel pad onboard-settings", "data-settings": "onboarding" },
    el("h2", null, ONBOARD_TITLE),
    el("p", { class: "small muted" }, dismissed ? "目前已收起。" : "大廳最上方的三步進度：拿角色卡、導入專案、把隊伍放上任務卡。三步都完成後會收成一行。"),
    btn);
}

async function viewSettings() {
  const token = seq;
  await loadStatic();
  await refreshTranslations();
  const main = claim(token);
  const c = await api.get("/api/config");
  if (token !== seq) return;
  const conf = c.config;
  const advanced = !!conf.advanced_mode;
  const sources = D.overview.sources;

  const saveConf = async (body, msg) => {
    try {
      const r = await api.post("/api/config", body);
      toast(msg || "已儲存");
      if (r.rescan_needed) toast("已儲存，重新掃描後生效");
      return r;
    } catch (e) { toast("儲存失敗：" + e.message); }
  };

  const srcRow = (s) => el("label", { class: "switch" },
    s.discovered ? el("input", { type: "checkbox", checked: true, disabled: true, title: "由專案目錄自動發現" })
      : el("input", { type: "checkbox", checked: s.enabled, on: { change: (e) => saveConf({ source_enabled: { [s.source_id]: e.target.checked } }, "已更新來源") } }),
    el("div", null,
      el("div", { class: "t" }, s.label, " ", el("span", { class: "tag" }, TOOL[s.tool] || s.tool), " ",
        s.exists ? el("span", { class: "small muted" }, `${s.count} 項`) : badge("路徑不存在", "b-warn")),
      advanced ? el("div", { class: "small muted mono" }, home(s.path)) : null));

  setKids(main, 
    el("h1", null, "設定"),
    el("p", { class: "lede" }, "選擇要盤點的來源。主控台只讀取你選的位置，不會修改任何技能或角色檔案。"),
    c.corrupt ? corruptNotice() || notice("bad", "設定檔（config.json）無法讀取，設定暫時無法儲存。") : null,
    translationSettings(conf, saveConf),
    onboardingSettings(conf, saveConf),
    el("div", { class: "grid-2" },
      el("div", { class: "panel pad" },
        el("h2", { style: "margin-bottom:6px" }, "掃描來源"),
        el("div", null, sources.filter((s) => !s.discovered).map(srcRow)),
        sources.some((s) => s.discovered) ? [el("h3", { style: "margin:14px 0 4px" }, "自動發現的專案技能"), sources.filter((s) => s.discovered).map(srcRow)] : null,
        el("div", { class: "row", style: "margin-top:12px" }, el("button", { class: "btn primary", on: { click: rescan } }, "重新掃描"))),
      el("div", { style: "display:grid;gap:16px;align-content:start" },
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:6px" }, "使用紀錄"),
          el("label", { class: "switch" },
            el("input", { type: "checkbox", checked: conf.usage_enabled !== false, on: { change: (e) => saveConf({ usage_enabled: e.target.checked }).then(() => loadLive(true)) } }),
            el("div", null, el("div", { class: "t" }, "讀取對話紀錄中的技能與模型"),
              el("div", { class: "small muted" }, "只擷取技能名稱、模型名稱、工作階段 ID、工作目錄與時間。對話內容、工具輸出與檔案內容不會被讀出或保存。"))),
          el("label", { class: "switch" },
            el("span", { style: "width:17px" }),
            el("div", null, el("div", { class: "t" }, "紀錄範圍"),
              el("select", { on: { change: (e) => saveConf({ usage_days: Number(e.target.value) }).then(() => loadLive(true)) } },
                [7, 14, 30, 60, 90].map((n) => el("option", { value: n, selected: Number(conf.usage_days || 30) === n }, `最近 ${n} 天`)))))),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:6px" }, "顯示"),
          el("label", { class: "switch" },
            el("input", { type: "checkbox", checked: advanced, on: { change: (e) => saveConf({ advanced_mode: e.target.checked }).then(viewSettings) } }),
            el("div", null, el("div", { class: "t" }, "進階模式"), el("div", { class: "small muted" }, "顯示檔案路徑與診斷資訊。機密值在任何模式下都不會顯示。"))),
          el("label", { class: "switch" },
            el("span", { style: "width:17px" }),
            el("div", null, el("div", { class: "t" }, "外觀"),
              el("select", { on: { change: (e) => setTheme(e.target.value) } },
                [["auto", "跟隨系統"], ["light", "淺色"], ["dark", "深色"]].map(([v, t]) => el("option", { value: v, selected: store.get("theme", "auto") === v }, t)))))),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:8px" }, "資料流向"),
          el("ul", { class: "small", style: "margin:0;padding-left:18px;color:var(--ink-2)" },
            el("li", null, "所有掃描都在這台電腦上完成；技能翻譯若啟用，會經你的本機 CLI 將作者說明送到模型服務。"),
            el("li", null, "網頁伺服器只接受本機（127.0.0.1）連線。"),
            el("li", null, "技能內的腳本不會被執行；原始內容以純文字顯示。"),
            el("li", null, "主控台只寫入自己的狀態目錄", advanced ? [": ", el("span", { class: "mono" }, home(c.state_dir))] : "", "。"),
            el("li", null, "角色由主控台內建的 VBear runtime 啟動與管理；開啟終端預設只觀看，接管後才會送出輸入。"))),
        advanced ? el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:8px" }, "診斷"),
          el("dl", { class: "kv small" },
            el("dt", null, "VBear runtime"), el("dd", { class: "mono" }, (D.live && D.live.runtime && D.live.runtime.version) || "未連線", " ", home(c.runtime_socket || "")),
            el("dt", null, "Claude 外掛"), el("dd", null, (D.overview.facts.claude_installed_plugins || []).join("、") || "—"),
            el("dt", null, "外掛啟用"), el("dd", { class: "mono" }, JSON.stringify(D.overview.facts.claude_enabled_plugins || {})),
            el("dt", null, "Codex 預設模型"), el("dd", null, D.overview.facts.codex_default_model || "—", D.overview.facts.codex_default_effort ? `（${D.overview.facts.codex_default_effort}）` : ""),
            el("dt", null, "上次掃描"), el("dd", null, `${fmtTime(D.overview.generated_at)}，耗時 ${D.overview.scan_seconds} 秒`),
            el("dt", null, "掃描問題"), el("dd", null, (D.overview.problems || []).join("；") || "無"))) : null)),
  );
}

function setTheme(v) {
  store.set("theme", v);
  if (v === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", v);
}

let activeTerminalCleanup = null;
function cleanupActiveTerminal() {
  // Close any open modal (e.g. a takeover confirmation) through its own
  // registered teardown before the terminal's own cleanup runs, rather than
  // the terminal cleanup reaching in and removing the modal element itself.
  closeOpenModals();
  if (activeTerminalCleanup) {
    try { activeTerminalCleanup(); } catch (e) { /* ignore */ }
    activeTerminalCleanup = null;
  }
}

// Owned by whichever view last set it (currently only viewWorkbench, for its
// window-level Escape-exits-focus-mode listener); route() clears it before
// entering any view so a view that is navigated away from cannot leak a
// stale window listener holding its old DOM/closures alive (L1).
let activeViewCleanup = null;
let flowCoordinator = null;    // the flow page's S2 panels, for the page's own timer (S2c-4)
function cleanupActiveView() {
  flowCoordinator = null;
  // Close any open modal (e.g. a task create/edit dialog) through its own
  // registered teardown before the view's own cleanup runs. This lives in
  // its own composable registry (openModalCloses), not folded into this
  // single activeViewCleanup slot, precisely so that opening a modal from
  // within a view can never silently overwrite (and thereby lose) whatever
  // cleanup the view itself already registered here.
  closeOpenModals();
  if (activeViewCleanup) {
    try { activeViewCleanup(); } catch (e) { /* ignore */ }
    activeViewCleanup = null;
  }
}

// Flows (stage 1): a board of multi-agent work. It only shows and records:
// every event comes from a form and is labelled 「手動記錄（未驗證）」, phases
// are derived by the server, and nothing here starts, sends or runs anything.
// The flows pages wait this long for /api/live before showing flows without
// live state. A cached view answers at once and a first build takes seconds;
// past this the page should not stay empty because the runtime hangs.
const FLOW_LIVE_TIMEOUT_MS = 10000;
const FLOW_ATTENTION = new Set(["awaiting_approval", "awaiting_merge", "awaiting_push", "review_unverified"]);
function flowPhaseClass(key) {
  if (key === "done") return "b-ok";
  if (key === "review_stale" || key === "needs_fix") return "b-bad";
  if (FLOW_ATTENTION.has(key)) return "b-warn";
  if (key === "in_review" || key === "implementing") return "b-info";
  return "b-mute";
}
function flowPhaseBadge(phase) {
  return badge(phase.label, flowPhaseClass(phase.key), phase.reason || "");
}
// 任務進度 (design game-ui 4.5): the phase VBear already derives, drawn as a row of gates. The words are the
// phase's own; a gate is 已過 / 目前 / 未到 by position only (it does not claim an approval was recorded).
const FLOW_GATES = ["計畫", "核准", "實作", "審查", "合併（你來）", "push（你來）", "完成"];
const FLOW_PHASE_GATE = { planning: 0, awaiting_approval: 1, implementing: 2, in_review: 3, needs_fix: 3,
  review_stale: 3, review_unverified: 4, awaiting_merge: 4, awaiting_push: 5, done: 6 };
function flowGateGrid(f) {
  const at = FLOW_PHASE_GATE[f.phase && f.phase.key];
  if (at === undefined) {
    return el("section", { class: "section", "data-flow": "gates" }, sectionHead("任務進度", null),
      el("p", { class: "small muted" }, "目前的階段無法對應到關卡，只顯示上方的階段文字。"));
  }
  return el("section", { class: "section", "data-flow": "gates" }, sectionHead("任務進度", f.phase.label),
    el("ol", { class: "fg-grid" }, FLOW_GATES.map((name, i) => {
      const state = i < at ? "past" : i === at ? "now" : "next";
      return el("li", { class: `fg-cell fg-${state}`, "data-gate": String(i), "data-state": state,
        "aria-current": state === "now" ? "step" : null },
        el("strong", null, name),
        el("span", { class: "fg-state" }, state === "past" ? "已過" : state === "next" ? "未到"
          : `目前：${f.phase.label}${f.attention ? "（等你處理）" : ""}`));
    })),
    el("p", { class: "small muted" }, "關卡只依事件推導出的階段排位；「已過」不代表當時有記錄到核准。"));
}

// The tool of a role is known only when the role was filled from a card (its snapshot says); a hand-written role has none.
function flowRoleToolText(role) {
  const tool = role && role.profile_snapshot && role.profile_snapshot.tool;
  return tool && cardHas(CARD_TOOL_LABEL, tool) ? `${CARD_TOOL_LABEL[tool]}（放上隊伍時的角色卡：${role.profile_snapshot.name}）`
    : "未提供（流程記錄沒有這個欄位）";
}

// 隊伍: planner, executor and reviewers as small cards. The planner is only a record; VBear never starts one.
function flowTeamSection(f, liveText) {
  const card = (kind, role, rows) => el("li", { class: "team-card" },
    el("h4", null, kind),
    el("dl", { class: "rc-dl" },
      el("dt", null, "名稱"), el("dd", null, role && role.name ? String(role.name) : "未提供"),
      el("dt", null, "工具"), el("dd", null, flowRoleToolText(role)),
      el("dt", null, "家族（模型出自哪一家）"), el("dd", null, role && role.family_label ? role.family_label : "未提供"),
      el("dt", null, "模型"), el("dd", null, role && role.model ? String(role.model) : "未提供"),
      rows));
  const row = (label, value, cls) => [el("dt", null, label), el("dd", { class: cls || null }, value)];
  const ex = f.roles.executor;
  const planner = card("規劃者（只是記錄，VBear 不會啟動）", f.roles.planner,
    row("狀態", "沒有狀態：只是記錄，不是 VBear 啟動的角色"));
  const executor = card("執行者", ex, [
    ...row("狀態", `${liveText.label}${liveText.reason ? "：" + liveText.reason : ""}`),
    ...row("工作目錄", ex.workdir || "（未設定，無法核對 HEAD）", "mono flow-path"),
    ...(ex.session_id ? row("session", ex.session_id, "mono") : [])]);
  const reviewers = (f.roles.reviewers || []).map((r, i) => {
    const ind = r.independent_of_executor;
    return card(`審查者 ${i + 1}`, r, [
      ...row("狀態", "審查的進度與結果見下方「審查輪次」"),
      ...row("與執行者", !ind ? "未提供" : ind.counted ? "不同家族，可算獨立審查"
        : `不算獨立審查：${ind.why || "原因未提供"}`)]);
  });
  return el("section", { class: "section", "data-flow": "team" }, sectionHead("隊伍明細", "上面的「隊伍」是放卡的地方；這裡是流程記錄的角色資料。"),
    el("ul", { class: "team-grid" }, [planner, executor, ...reviewers]));
}

// The executor's live state as shown. If this page's own /api/live load
// failed or timed out, nothing from the server's cache is shown as current.
function flowLiveText(ex, liveError) {
  if (liveError) return { label: "即時狀態未載入", reason: `這次讀取即時狀態失敗：${liveError}` };
  const fr = ex && ex.freshness;
  const age = fr && fr.state === "fresh" && Number.isSafeInteger(fr.age_s) && fr.age_s >= 0 ? `即時狀態 ${fr.age_s} 秒前` : "";
  return { label: ex ? ex.label : "狀態未知", reason: [ex && ex.reason, age].filter(Boolean).join("・") };
}
function liveLoadError() { return D.live && D.live.error ? D.live.error : ""; }
function shortCommit(c) { return typeof c === "string" ? c.slice(0, 7) : "—"; }
function roleText(r) {
  return r ? [r.name, r.family_label, r.model].filter(Boolean).join("・") : "—";
}
const VERDICT_CLASS = { PASS: "b-ok", NEEDS_WORK: "b-warn", BLOCKED: "b-bad" };

function flowCard(f) {
  const rev = f.latest_review;
  return el("a", { class: "card", href: `#/flows/${encodeURIComponent(f.id)}` },
    el("div", { class: "card-top" },
      el("div", { style: "min-width:0" },
        el("div", { class: "card-title" }, f.task_missing ? "（任務卡已刪除或無法讀取）" : f.task_title),
        el("div", { class: "card-sub" }, f.attention_reason || f.phase.reason)),
      flowPhaseBadge(f.phase)),
    f.automation && f.automation.mode === "auto"
      ? el("div", { class: "stat-line" }, badge(f.automation.held ? "自動（已停止）" : "自動執行中",
        f.automation.held ? "b-warn" : "b-info"),
      f.automation.step_label ? el("span", { class: "small" }, f.automation.step_label) : null) : null,
    el("div", { class: "stat-line" },
      el("span", null, "執行 ", el("b", null, roleText(f.roles.executor))),
      el("span", null, "終端 ", el("b", { title: flowLiveText(f.executor_live, liveLoadError()).reason },
        flowLiveText(f.executor_live, liveLoadError()).label))),
    el("div", { class: "stat-line" },
      el("span", null, "審查 ", el("b", null, f.roles.reviewers.map(roleText).join("、"))),
      rev ? el("span", null, "最新 ", badge(rev.verdict, VERDICT_CLASS[rev.verdict] || "b-mute",
        rev.counts_as_pass ? "算通過" : (rev.why || "")), ` ${shortCommit(rev.commit)}`) : null),
    flowBindingNote(f) ? el("div", { class: "small muted" }, flowBindingNote(f)) : null);
}

// The binding's own line, unless the phase reason already says the same.
function flowBindingNote(f) {
  return f.binding && f.binding.detail && f.binding.detail !== f.phase.reason ? f.binding.detail : "";
}

function flowNotice() {
  return notice("info", "流程的事件有兩種：你用表單手動記錄的（未驗證），和自動執行時 VBear 自己寫入的稽核事件；任務進度由 VBear 依這兩種事件與即時資料推導。" +
    "手動模式下，VBear 不會為流程派工；開啟自動執行之後，VBear 只會照你核准的計畫派工、送審、轉送審查意見。" +
    "不論哪種模式，VBear 都不會執行 git，也不會啟動規劃者；這一頁和首頁一樣會讀取即時狀態，可能因此啟動 VBear 自己的 runtime。");
}

function familyOptions(families, selected) {
  return families.map((f) => el("option", { value: f.key, selected: f.key === selected ? "selected" : null }, f.label));
}

function roleInputs(prefix, families, role, opts = {}) {
  const name = el("input", { type: "text", class: "input", "aria-label": `${prefix}名稱`, value: role ? role.name : "",
    maxlength: "80", placeholder: "名稱，例如 Codex" });
  const family = el("select", { "aria-label": `${prefix}模型家族` }, familyOptions(families, role ? role.family : "unknown"));
  const model = el("input", { type: "text", class: "input", "aria-label": `${prefix}模型`, value: role && role.model ? role.model : "",
    maxlength: "80", placeholder: "模型（選填）" });
  const extra = {};
  const fields = [el("b", null, prefix), name, family, model];
  if (opts.executor) {
    const sessions = ((D.live && D.live.panes) || []);
    extra.session = el("select", { "aria-label": "執行者的終端" },
      el("option", { value: "" }, "（不綁定終端）"),
      sessions.map((p) => el("option", { value: p.pane_id, selected: role && role.session_id === p.pane_id ? "selected" : null },
        `${p.pane_id}・${p.title || p.agent || "terminal"}`)));
    extra.workdir = el("input", { type: "text", class: "input mono", "aria-label": "執行者的工作目錄",
      value: role && role.workdir ? role.workdir : "", placeholder: "工作目錄（絕對路徑，用來核對 HEAD）" });
    fields.push(extra.session, extra.workdir);
  }
  const read = () => {
    const r = { name: name.value.trim(), family: family.value };
    if (model.value.trim()) r.model = model.value.trim();
    if (opts.executor) {
      if (extra.session.value) r.session_id = extra.session.value;
      if (extra.workdir.value.trim()) r.workdir = extra.workdir.value.trim();
    }
    return r;
  };
  return { node: el("div", { class: "flow-role-row" }, fields), read };
}

async function viewFlows() {
  const token = seq;
  await loadLive(false, FLOW_LIVE_TIMEOUT_MS);   // first: /api/flows only reads the live cache
  const [data, tasksRes] = await Promise.all([loadFlows(), api.get("/api/tasks").catch(() => ({ tasks: [] }))]);
  const main = claim(token);
  if (token !== seq) return;
  const used = new Set((data.flows || []).map((f) => f.task_id));
  const free = (tasksRes.tasks || []).filter((t) => !used.has(t.id));
  const families = data.families || [];
  const taskSel = el("select", { "aria-label": "任務卡" },
    free.length ? free.map((t) => el("option", { value: t.id }, t.title)) : el("option", { value: "" }, "（沒有尚未建立流程的任務卡）"));
  const planner = roleInputs("規劃", families, null);
  const executor = roleInputs("執行", families, null, { executor: true });
  const reviewerRows = [roleInputs("審查 1", families, null), roleInputs("審查 2", families, null)];
  const submit = el("button", { class: "btn primary", type: "submit", disabled: free.length ? null : "disabled" }, "建立流程");
  const form = el("form", { class: "flow-form", on: { submit: async (ev) => {
    ev.preventDefault();
    if (!taskSel.value) { toast("請先選一張任務卡"); return; }
    const reviewers = reviewerRows.map((r) => r.read()).filter((r) => r.name);
    submit.disabled = true;
    try {
      const r = await api.post("/api/flows", { task_id: taskSel.value,
        roles: { planner: planner.read(), executor: executor.read(), reviewers } });
      location.hash = `#/flows/${encodeURIComponent(r.flow.id)}`;
    } catch (e) { toast("無法建立流程：" + e.message); submit.disabled = false; }
  } } },
    planner.node, executor.node, reviewerRows.map((r) => r.node),
    el("p", { class: "small muted" }, "審查者與執行者必須是不同模型家族，審查結果才算通過；家族「其他」或「不明」也不算。"),
    submit);
  // the cards go on the task card's places (design 3.5); typing the names by hand is the "advanced" way
  const boardHost = el("div", { "data-flow": "board-host" });
  const mountBoard = () => {
    const t = free.find((x) => x.id === taskSel.value);
    setKids(boardHost, t ? teamSection(t, { gone: () => token !== seq, onSaved: () => route() })
      : emptyState("沒有可以建立隊伍的任務卡", "每張任務卡只有一個流程；先用「＋ 任務卡（導入專案）」建一張新的。"));
  };
  taskSel.addEventListener("change", mountBoard);
  mountBoard();
  const list = data.flows || [];
  setKids(main,
    el("h1", null, "流程"),
    el("p", { class: "lede" }, "多個角色合作完成一張任務卡：誰規劃、誰執行、誰審查，進行到哪一步，等誰處理。"),
    flowNotice(),
    data.error ? notice("bad", "流程無法讀取：" + data.error) : null,
    el("section", { class: "section" },
      sectionHead("進行中的流程", `${list.length} 個`),
      list.length ? el("div", { class: "grid" }, list.map(flowCard)) : emptyState("還沒有流程", "在下方選一張任務卡建立。")),
    el("section", { class: "section" },
      sectionHead("建立流程", null, el("button", { type: "button", class: "btn small", "data-act": "import", on: { click: () => openImportProject({
        onCreated: () => route(), onOpenTask: (id) => { location.hash = `#/workbench?task=${encodeURIComponent(id)}`; } }) } },
        cardArt("icons", "importProject", 1), "＋ 任務卡（導入專案）")),
      el("label", { class: "small" }, "任務卡（一張任務卡對應一個流程）"), taskSel,
      boardHost,
      el("details", { class: "fold ts-manual", "data-flow": "manual" }, el("summary", null, "進階：手動填寫"),
        el("div", { class: "cw-body" }, el("p", { class: "small muted" }, "不挑角色卡，自己打名字、家族和模型。這樣記下的角色沒有對應的角色卡。"), form))),
    mountStorage().node);
}

const FLOW_SOURCE_TITLES = {
  manual: "由表單記錄，VBear 沒有核對",
  console: "由主控台依預覽紀錄或你在畫面上的操作寫入",
  automation: "由自動執行寫入：意圖 → daemon 動作 → 結果。哪些欄位是執行者自述、哪些是 VBear 讀檔核對，在該筆事件裡分開標明",
};

// What an automatic-mode event says, as lines (every value was checked by the server before it was stored).
function flowAutomationDetail(e) {
  const id = (v) => (typeof v === "string" ? v.slice(0, 8) : "");
  switch (e.kind) {
    case "automation_mode": return [e.mode === "auto" ? `切到自動執行（核准 auto-${e.approval_seq}）` : "切回手動"];
    case "auto_dispatch_intent": return [`派工 ${id(e.dispatch_id)}・${e.length} bytes・sha256 ${String(e.text_sha256).slice(0, 12)}…`];
    case "auto_dispatch_sent": return [`派工 ${id(e.dispatch_id)} 已送出`];
    case "auto_report": return [
      `派工 ${id(e.dispatch_id)}：`,
      `執行者自述：狀態 ${e.status}、測試 ${e.tests_result}、head ${shortCommit(e.commit)}`,
      "VBear 讀檔核對：head 等於工作目錄目前的 commit、commit 物件存在（沒有全部通過就不會有這一筆）"];
    case "auto_review_intent": return [`第 ${e.round} 輪審查（commit ${shortCommit(e.commit)}）`];
    case "auto_review_started": return [`第 ${e.round} 輪審查已啟動（${e.job_id}）`];
    case "auto_review_result": return [`第 ${e.round} 輪結論：${e.verdict}（commit ${shortCommit(e.commit)}）`];
    case "auto_review_aborted": return [`第 ${e.round} 輪被停止中止，該輪無效（${e.job_id}）`];
    case "auto_stopped": return [`原因代碼 ${e.reason_code}`, e.detail];
    default: return [];
  }
}

function flowEventBody(kind, values) {
  // Only the fields the server accepts for this kind are sent.
  const body = { kind, note: values.note || "" };
  if (kind === "executor_report" || kind === "review_result") body.commit = (values.commit || "").trim().toLowerCase();
  if (kind === "review_result") {
    body.verdict = values.verdict;
    body.reviewer = Number.parseInt(values.reviewer, 10);
  }
  return body;
}

async function viewFlowDetail(flowId) {
  const token = seq;
  await loadLive(false, FLOW_LIVE_TIMEOUT_MS);   // first: /api/flows only reads the live cache
  let res;
  try { res = await api.get(`/api/flows/${encodeURIComponent(flowId)}`); }
  catch (e) {
    const main = claim(token);
    setKids(main, crumbs([["流程", "#/flows"], ["找不到"]]), notice("bad", "無法讀取這個流程：" + e.message));
    return;
  }
  const meta = D.flows && D.flows.kinds ? D.flows : await loadFlows();
  const tasksRes = await api.get("/api/tasks").catch(() => ({ tasks: [] }));
  const main = claim(token);
  if (token !== seq) return;
  const f = res.flow;
  const flowTask = ((tasksRes && tasksRes.tasks) || []).find((t) => t.id === f.task_id)
    || { id: f.task_id, title: f.task_title || f.task_id, workdir: null };
  const kindSel = el("select", { "aria-label": "事件種類" }, (meta.kinds || []).map((k) => el("option", { value: k.key }, k.label)));
  const commit = el("input", { type: "text", class: "input mono", "aria-label": "commit", placeholder: "完整的 40 或 64 碼 commit", maxlength: "64" });
  const verdict = el("select", { "aria-label": "審查結論" }, (meta.verdicts || []).map((v) => el("option", { value: v }, v)));
  const reviewer = el("select", { "aria-label": "審查者" }, f.roles.reviewers.map((r, i) => el("option", { value: String(i) }, roleText(r))));
  const note = el("textarea", { class: "input", "aria-label": "備註", maxlength: "2000", rows: "3", placeholder: "備註（選填）" });
  const commitRow = el("label", { class: "small" }, "commit ", commit);
  const reviewRow = el("div", { class: "row" }, el("label", { class: "small" }, "審查者 ", reviewer), el("label", { class: "small" }, "結論 ", verdict));
  const syncFields = () => {
    const k = kindSel.value;
    commitRow.hidden = !(k === "executor_report" || k === "review_result");
    reviewRow.hidden = k !== "review_result";
  };
  kindSel.addEventListener("change", syncFields);
  syncFields();
  const add = el("button", { class: "btn primary", type: "submit" }, "記錄事件");
  const form = el("form", { class: "flow-form", on: { submit: async (ev) => {
    ev.preventDefault();
    add.disabled = true;
    try {
      await api.post(`/api/flows/${encodeURIComponent(f.id)}/events`, flowEventBody(kindSel.value,
        { commit: commit.value, verdict: verdict.value, reviewer: reviewer.value, note: note.value }));
      toast("已記錄（手動記錄，未驗證）");
      route();
    } catch (e) { toast("無法記錄：" + e.message); add.disabled = false; }
  } } }, el("label", { class: "small" }, "事件 ", kindSel), commitRow, reviewRow, note,
    el("p", { class: "small muted" }, "這筆會標示為「手動記錄（未驗證）」。記錄事件只會寫入流程紀錄，不會派工、輸入指令或執行 git。"), add);

  // The VBear-managed executor, reviews and merge gate (S2c-4). It stops its
  // own refreshing when the page is left (cleanupActiveView).
  const coordinator = mountCoordinator(f.id);
  activeViewCleanup = () => coordinator.stop();
  flowCoordinator = coordinator;
  const rounds = f.rounds || [];
  const roundTable = rounds.length ? el("div", { class: "table-scroll" }, el("table", { class: "flow-rounds" },
    el("thead", null, el("tr", null, ["輪次", "回報的 commit", "審查者", "家族", "結論", "算通過", "說明"].map((h) => el("th", null, h)))),
    el("tbody", null, rounds.flatMap((rnd) => (rnd.reviews.length ? rnd.reviews : [null]).map((rv, i) =>
      el("tr", null,
        el("td", null, i === 0 ? `第 ${rnd.round} 輪` : ""),
        el("td", { class: "mono" }, i === 0 ? shortCommit(rnd.commit) : ""),
        el("td", null, rv ? rv.reviewer : "（尚未審查）"),
        el("td", null, rv ? (D.flows.families || []).find((x) => x.key === rv.family)?.label || rv.family : ""),
        el("td", null, rv ? badge(rv.verdict, VERDICT_CLASS[rv.verdict] || "b-mute") : ""),
        el("td", null, rv ? (rv.counts_as_pass ? "是" : "否") : ""),
        el("td", { class: "small" }, rv ? rv.why : ""))))))) : emptyState("還沒有執行者回報", "執行者回報 commit 後，審查結果會依輪次列在這裡。");
  const timeline = el("ol", { class: "flow-timeline" }, (f.events || []).map((e) => el("li", null,
    el("div", { class: "row" }, el("b", null, e.label),
      badge(e.source_label, e.source === "manual" ? "b-mute" : (e.source === "automation" ? "b-info" : "b-ok"),
        FLOW_SOURCE_TITLES[e.source] || ""),
      el("span", { class: "small muted" }, fmtTime(e.at))),
    e.commit ? el("div", { class: "small mono" }, `commit ${shortCommit(e.commit)}`) : null,
    e.verdict && e.reviewer ? el("div", { class: "small" }, `${e.reviewer.name}：${e.verdict}`) : null,
    flowAutomationDetail(e).map((line) => el("div", { class: "small" }, line)),
    e.note ? el("div", { class: "small" }, e.note) : null)));

  setKids(main,
    crumbs([["流程", "#/flows"], [f.task_missing ? f.id : f.task_title]]),
    el("div", { class: "row", style: "justify-content:space-between" },
      el("h1", null, f.task_missing ? "（任務卡已刪除或無法讀取）" : f.task_title), flowPhaseBadge(f.phase)),
    flowNotice(),
    f.attention ? notice("warn", "等你處理：" + (f.attention_reason || f.phase.reason))
      : f.phase.key === "review_stale" ? notice("warn", f.phase.reason) : el("p", { class: "lede" }, f.phase.reason),
    flowBindingNote(f) ? el("p", { class: "small muted" }, flowBindingNote(f)) : null,
    (f.warnings || []).map((w) => notice("warn", w)),
    flowGateGrid(f),
    teamSection(flowTask, { flow: f, hideOpen: true, gone: () => token !== seq, onSaved: () => route(),
      onRecord: () => { const box = document.querySelector('[data-flow="record"]'); if (box && box.scrollIntoView) box.scrollIntoView({ block: "start" }); } }),
    flowTeamSection(f, flowLiveText(f.executor_live, liveLoadError())),
    coordinator.node,
    el("section", { class: "section" }, sectionHead("審查輪次", `${rounds.length} 輪`), roundTable,
      (f.stray_reviews || []).length ? notice("info", `另有 ${f.stray_reviews.length} 筆審查的 commit 不是最新一次回報的 commit，未列入輪次。`) : null),
    el("section", { class: "section" }, sectionHead("時間軸", `${(f.events || []).length} 筆`),
      (f.events || []).length ? timeline : emptyState("還沒有事件", null)),
    el("section", { class: "section", "data-flow": "record" }, sectionHead("手動記錄事件", null), form));
}

// ---------- the VBear-managed executor, reviews and merge gate (S2c-4) ------------
//
// Everything the server or a reviewer wrote is shown with textContent (el()
// only ever makes text nodes): a review report is "plain_text" and stays
// plain text here, whatever it contains. Every action goes through the
// server's preview-then-approve routes; nothing is sent from the browser
// that the server did not store first. The buttons are hints: the server and
// the daemon decide again, and what they say is shown as it is.

const S2_ACCEPTANCE = {
  none: ["尚未接受風險", "b-mute", "還沒有接受殘餘風險，不能由 VBear 啟動執行者或 Codex 審查。"],
  valid: ["風險已接受", "b-ok", ""],
  stale: ["接受已失效", "b-warn", ""],
  unknown: ["無法確認接受", "b-warn", ""],
};
const S2_REVIEW_OUTCOME = {
  valid: ["有效", "b-ok"], invalid: ["無效", "b-bad"], manual_review: ["待人工處理", "b-warn"],
};
const S2_VERDICT_CLASS = { PASS: "b-ok", "NEEDS WORK": "b-warn", BLOCKED: "b-bad" };
const S2_SESSION_STATE = {
  idle: "閒置（可派工）", turn_running: "執行中", running: "執行中", finishing: "收尾中", uncertain: "狀態不確定",
  error: "錯誤", exited: "已結束", starting: "啟動中",
};

function s2Url(flowId, suffix) { return `/api/flows/${encodeURIComponent(flowId)}/${suffix}`; }

// One GET that cannot take the page down: {ok, data} or {ok:false, message}.
const S2_REQUEST_TIMEOUT_MS = 15000;
async function s2Get(path, signal) {
  try { return { ok: true, data: await api.get(path, { timeoutMs: S2_REQUEST_TIMEOUT_MS, signal }) }; }
  catch (e) { return { ok: false, message: e.message, status: e.status }; }
}

async function s2Load(flowId, signal) {
  const [executor, reports, reviews, gate, automationState] = await Promise.all([
    s2Get(s2Url(flowId, "executor"), signal), s2Get(s2Url(flowId, "reports"), signal),
    s2Get(s2Url(flowId, "reviews"), signal), s2Get(s2Url(flowId, "merge-gate"), signal),
    s2Get(s2Url(flowId, "automation"), signal)]);
  return { executor, reports, reviews, gate, automation: automationState };
}

function s2Pre(text, cls) {
  return el("pre", { class: `s2-plain ${cls || ""}`.trim(), tabindex: "0" }, text == null ? "" : String(text));
}

function s2Copy(text, label) {
  return el("button", { class: "btn small", type: "button", on: { click: async () => {
    try { await navigator.clipboard.writeText(text); toast("已複製"); }
    catch (_) { toast("無法複製，請手動選取"); }
  } } }, label || "複製");
}

// Two-step confirmation on the button itself (no browser dialogs). While one is asking it carries the class
// "s2-asking", and the quiet refresh looks for that class in the page itself (no counter that could be left
// behind): it does not rebuild the panels under an open question.
function s2QuestionOpen(root) {
  if (!root) return false;
  if (typeof root.querySelector === "function") {
    try { if (root.querySelector(".s2-asking")) return true; } catch (_) { /* fall through */ }
  }
  return typeof root.find === "function" ? !!root.find((n) => n.hasClass && n.hasClass("s2-asking")) : false;
}

function s2Confirm(label, question, action, cls) {
  const host = el("span", { class: "s2-confirm" });
  const ask = () => {
    host.classList.add("s2-asking");
    const done = () => host.classList.remove("s2-asking");
    const yes = el("button", { class: "btn small bad", type: "button", on: { click: async () => {
      yes.disabled = true;
      try { await action(); } finally { done(); setKids(host, btn); }
    } } }, "確定");
    const no = el("button", { class: "btn small", type: "button", on: { click: () => { done(); setKids(host, btn); } } }, "取消");
    setKids(host, el("span", { class: "small" }, question + " "), yes, no);
    no.focus();
  };
  const btn = el("button", { class: `btn small ${cls || ""}`.trim(), type: "button", on: { click: ask } }, label);
  host.append(btn);
  return host;
}

// A meter: the words (always), and a bar when both numbers are known. A number that could not be had is not
// drawn as an empty bar (that would read as 0): it says it cannot be counted.
function s2Meter(label, used, limit, unit, why, fmt) {
  const known = typeof used === "number" && typeof limit === "number" && Number.isFinite(used) && Number.isFinite(limit) && limit > 0;
  const over = known && used >= limit;
  const show = (v) => (v === null || v === undefined ? "?" : fmt && typeof v === "number" && Number.isFinite(v) ? fmt(v) : String(v));
  return el("li", { class: "s2-meter" }, `${label}：`, el("b", { class: over ? "s2-over" : "" }, `${show(used)}${unit || ""}`),
    ` ／ 上限 ${show(limit)}${unit || ""}`,
    known ? el("progress", { class: "s2-bar", max: String(limit), value: String(Math.min(used, limit)),
      "aria-label": `${label}：已用 ${show(used)}${unit || ""}，上限 ${show(limit)}${unit || ""}` })
      : el("span", { class: "small muted" }, ` 無法核算${why ? "：" + why : "（用量或上限不明）"}`));
}

// The executor's cost: the figure the limit reads, split into what the CLI recorded and what is counted on
// top of it for turns that have no result, and the plain statement that the real cost is not known.
function s2CostMeter(acct) {
  // Every dollar figure is shown to the cent: the parts are floats that add up to the figure only at that scale.
  const cents = (v) => v.toFixed(2);
  const li = s2Meter("執行者費用", acct.spent_usd, acct.limits.executor_budget_usd, " USD", undefined, cents);
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const rec = num(acct.recorded_usd), uns = num(acct.unsettled_usd);
  li.append(
    el("div", { class: "small s2-cost-split" },
      rec === null ? "已記錄的花費：無法核算" : `已記錄的花費 USD ${cents(rec)}（CLI 回報）`,
      uns === null ? "；未結算：無法核算"
        : (Math.round(uns * 100) > 0 ? `；未結算 USD ${cents(uns)}（未完成的回合按額度上限計入用量）` : "；沒有未結算的回合")),
    el("div", { class: "small muted" }, "實際費用尚未知；這裡的數字是用量，不是帳單。"));
  return li;
}

// ---- the risk acceptance dialog ----------------------------------------------------------------

// opts.auto: the approval of a plan and the switch to automatic mode (S3 design 9): the same dialog, with the plan
// text and the automatic-mode text added, and its own preview and confirmation routes.
function openAcceptanceDialog(flowId, onDone, opts = {}) {
  const auto = !!opts.auto;
  const previewPath = auto ? "automation-preview" : "acceptance-preview";
  const confirmPath = auto ? "automation" : "acceptance";
  let modal; let previewId = null; let current = null; let fields = null;
  const body = el("div", { class: "s2-accept-body" });
  const problem = el("div", { class: "s2-accept-problem", role: "alert" });   // what the server said to the last confirmation
  const status = el("p", { class: "small muted", role: "status" }, "正在讀取…");
  const accept = el("button", { class: "btn primary", type: "button", disabled: true, on: { click: submit } },
    auto ? "核准並開啟自動執行" : "接受並記錄");
  const cancel = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
  const again = el("button", { class: "btn", type: "button", on: { click: () => load(null) } }, "重新預覽");
  modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "s2-accept-title" },
    el("div", { class: "modal-box", style: "max-width: 760px; max-height: 88vh; overflow-y: auto;" },
      el("h2", { id: "s2-accept-title" }, auto ? "核准計畫並開啟自動執行" : "接受殘餘風險"), status, problem, body,
      el("div", { class: "modal-actions" }, cancel, again, accept)));
  document.body.append(modal);
  const closeModal = withModalA11y(modal, () => modal.remove());
  cancel.focus();

  const num = (v) => (typeof v === "number" ? String(v) : "");
  async function load(over) {
    previewId = null;
    accept.disabled = true;
    setKids(problem);
    setKids(status, "正在讀取…");
    try {
      const res = await api.post(s2Url(flowId, previewPath), over || {});
      current = res;
      previewId = res.preview_id;
      render(res);
      setKids(status, `這份預覽只能用一次，5 分鐘內有效（到 ${fmtTime(res.expires_at)}）。接受的是下面這一組值；` +
        "任何一項在你按下之前改變，就必須重新預覽。");
    } catch (e) {
      current = null;
      setKids(body);
      if (e.code === "needs_login" && e.data) {
        setKids(status, "");
        setKids(body, notice("warn", e.message),
          el("p", null, "請在終端機自己執行下面這行指令（VBear 不會替你登入，也不會讀取憑證）："),
          s2Pre(e.data.login_command), s2Copy(e.data.login_command),
          el("p", { class: "small muted" }, `設定目錄：${e.data.codex_home}。登入完成後按「重新預覽」。`));
      } else {
        setKids(status, "");
        setKids(body, notice("bad", e.message));
      }
    }
  }
  function render(res) {
    const v = res.values;
    // Whatever is changed here, the preview that is still held is for the OLD values: it is voided at once, the
    // box is cleared and "accept" stays off until a new preview of the new values has been made.
    const check = el("input", { type: "checkbox", id: "s2-accept-check", on: { change: () => {
      accept.disabled = !(check.checked && previewId);
    } } });
    const voided = () => {
      previewId = null;
      check.checked = false;
      check.disabled = true;
      accept.disabled = true;
      setKids(problem, notice("warn", "設定已變更，這份預覽已作廢。請按「套用並重新預覽」，檢查新的預覽後再接受。"));
    };
    const changed = { input: voided, change: voided };
    fields = { limits: [], model: null, review: null };
    const limitRows = v.limits.map((x) => {
      const input = el("input", { type: "number", class: "input s2-limit", "aria-label": x.label,
        value: String(x.value), min: "1", max: String(x.cap), step: x.name === "executor_budget_usd" ? "0.01" : "1",
        dataset: { limit: x.name }, on: changed });
      input.value = String(x.value);
      fields.limits.push({ name: x.name, input });
      return el("tr", null, el("td", null, x.label), el("td", null, input, ` ${x.unit}`),
        el("td", { class: "small muted" }, `預設 ${x.default}，上限 ${x.cap}`));
    });
    const modelIn = el("input", { type: "text", class: "input mono", value: v.executor_model, list: "s2-exec-models",
      "aria-label": "執行者模型（完整的 Claude 模型 id）", spellcheck: "false", on: changed });
    modelIn.value = v.executor_model;
    fields.model = modelIn;
    const lists = el("datalist", { id: "s2-exec-models" }, (res.suggested_executor_models || []).map((m) => el("option", { value: m })));
    const reviewIn = el("select", { "aria-label": "審查模型", on: { change: voided } },
      (res.review_models || [v.review_model]).map(
        (m) => el("option", { value: m, selected: m === v.review_model }, m)));
    reviewIn.value = v.review_model;
    fields.review = reviewIn;
    const zh = res.risk_text.zh;
    const az = auto ? res.auto_text.zh : null;
    const autoParts = auto ? [
      el("p", null, az.intro),
      el("h3", null, "這份計畫（核准的就是這一份）"),
      s2Pre(res.plan_text),
      el("p", { class: "small muted" }, `計畫文字 ${res.plan_bytes} bytes，sha256 前 16 碼 ${String(res.plan_sha256).slice(0, 16)}；` +
        "核准之後任務卡再改，不會影響已核准的這一份。"),
      az.sections.map((s, i) => el("section", { class: "s2-risk", "data-s2-auto": s.id },
        el("h3", null, `${String.fromCharCode(65 + i)}. ${s.title}`), el("p", { class: "s2-risk-body" }, s.body))),
      el("h3", null, "固定規則"),
      el("ul", { class: "small" }, (res.fixed_rules || []).map((r) => el("li", null, r))),
      el("details", { class: "s2-risk-en" }, el("summary", null, "English text (same version)"),
        res.auto_text.en.sections.map((s, i) => el("section", { class: "s2-risk" },
          el("h3", null, `${String.fromCharCode(65 + i)}. ${s.title}`), el("p", { class: "s2-risk-body" }, s.body)))),
      el("p", { class: "small muted" }, `自動執行文字版本 ${az.version}`),
      el("h3", null, "第 2 階段的殘餘風險（同時接受）"),
    ] : [];
    setKids(body,
      el("p", null, auto ? "" : zh.intro),
      autoParts,
      zh.items.map((it, i) => el("section", { class: "s2-risk" }, el("h3", null, `${i + 1}. ${it.title}`),
        el("p", { class: "s2-risk-body" }, it.body))),
      el("details", { class: "s2-risk-en" }, el("summary", null, "English text (same version)"),
        res.risk_text.en.items.map((it, i) => el("section", { class: "s2-risk" }, el("h3", null, `${i + 1}. ${it.title}`),
          el("p", { class: "s2-risk-body" }, it.body)))),
      el("p", { class: "small muted" }, `風險文字版本 ${v.text_version}`),
      el("h3", null, "這次接受涵蓋的設定"),
      el("dl", { class: "kv small" },
        el("dt", null, "Codex 版本"), el("dd", { class: "mono" }, v.codex_version),
        el("dt", null, "審查模型"), el("dd", null, reviewIn),
        el("dt", null, "Claude Code 版本"), el("dd", { class: "mono" }, v.executor_claude_version),
        el("dt", null, "執行者模型"), el("dd", null, modelIn, lists),
        el("dt", null, "執行者的 Claude 帳號指紋（前 16 碼）"), el("dd", { class: "mono" }, v.executor_account),
        el("dt", null, "審查者的 Codex 帳號指紋（前 16 碼）"), el("dd", { class: "mono" }, v.review_account),
        el("dt", null, "指紋金鑰 id"), el("dd", { class: "mono" }, v.login_key_id)),
      el("h3", null, "體力（停損設定，全部九項）", " ", teamInfo("stamina", "體力")),
      el("div", { class: "table-scroll" }, el("table", { class: "s2-limits" }, el("tbody", null, limitRows))),
      el("p", { class: "small" }, "改了模型或體力設定，要按「套用並重新預覽」才會產生新的預覽。",
        " ", el("button", { class: "btn small", type: "button", on: { click: () => {
          const limits = {};
          body.querySelectorAll("input").forEach((i) => {
            const name = i.dataset && i.dataset.limit;
            if (name) limits[name] = Number(i.value);
          });
          load({ executor_model: modelIn.value.trim(), review_model: reviewIn.value, limits });
        } } }, "套用並重新預覽")),
      el("label", { class: "s2-check" }, check, " ", auto ? az.confirm : zh.confirm));
  }
  // The values on the screen against the ones this preview is of. A field set by a script (no input event) is
  // caught here: nothing is sent, a new preview is asked for (Codex S2c-4 round 2).
  function screenDiffers() {
    if (!current || !fields || !current.values) return true;
    const v = current.values;
    if (!fields.model || fields.model.value.trim() !== v.executor_model) return true;
    if (!fields.review || fields.review.value !== v.review_model) return true;
    const want = new Map((v.limits || []).map((x) => [x.name, x.value]));
    if (fields.limits.length !== want.size) return true;
    return fields.limits.some((f) => !want.has(f.name) || Number(f.input.value) !== want.get(f.name)
      || f.input.value.trim() === "");
  }
  async function submit() {
    if (!previewId) return;
    if (screenDiffers()) {
      previewId = null;
      accept.disabled = true;
      setKids(problem, notice("warn", "畫面上的設定和這份預覽不一致，沒有送出。請按「套用並重新預覽」，檢查新的預覽後再接受。"));
      return;
    }
    accept.disabled = true;
    try {
      await api.post(s2Url(flowId, confirmPath), { preview_id: previewId });
      toast(auto ? "已核准計畫並開啟自動執行；接著請啟動執行者" : "已記錄風險接受");
      closeModal();
      if (onDone) onDone();
    } catch (e) {
      setKids(status, "");
      previewId = null;
      setKids(problem, notice(e.status === 409 ? "warn" : "bad", e.message +
        (e.status === 409 ? "（這份預覽已作廢，請重新預覽）" : "")));
    }
  }
  load(null);
  return closeModal;
}

// ---- the panels -------------------------------------------------------------------------------------

function s2AcceptancePanel(flowId, ex, refresh) {
  const a = ex.acceptance || { state: "none" };
  const [label, cls, tip] = S2_ACCEPTANCE[a.state] || S2_ACCEPTANCE.unknown;
  const v = a.values;
  return el("section", { class: "section s2-panel", "data-s2": "acceptance" },
    sectionHead(["風險接受", " ", teamInfo("risk", "風險接受")], null, el("div", { class: "row" }, badge(label, cls, tip),
      el("button", { class: "btn small primary", type: "button",
        disabled: ex.automation && ex.automation.mode === "auto",
        title: ex.automation && ex.automation.mode === "auto" ? "自動執行中；要改體力設定或重新接受，先停止流程並切回手動" : "",
        on: { click: () => openAcceptanceDialog(flowId, refresh) } },
        a.state === "valid" ? "重新接受…" : "接受殘餘風險…"))),
    a.reason ? notice(a.state === "valid" ? "info" : "warn", a.reason) : (tip ? el("p", { class: "small muted" }, tip) : null),
    v ? el("dl", { class: "kv small" },
      el("dt", null, "記錄於"), el("dd", null, fmtTime(a.accepted_at)),
      el("dt", null, "風險文字版本"), el("dd", { class: "mono" }, v.text_version),
      el("dt", null, "Codex／審查模型"), el("dd", { class: "mono" }, `${v.codex_version}／${v.review_model}`),
      el("dt", null, "Claude Code／執行者模型"), el("dd", { class: "mono" }, `${v.executor_claude_version}／${v.executor_model}`),
      el("dt", null, "帳號指紋（前 16 碼）"), el("dd", { class: "mono" }, `執行者 ${v.executor_account}　審查者 ${v.review_account}`)) : null);
}

// ---- automatic mode (S3 design 7, 9) ---------------------------------------------------------------------------

function s2AutomationPanel(flowId, au, refresh) {
  if (!au.ok) {
    return el("section", { class: "section s2-panel", "data-s2": "automation" }, sectionHead("自動執行", null),
      notice("bad", "無法讀取自動執行的狀態：" + au.message));
  }
  const a = au.data;
  const step = a.step;
  if (a.mode !== "auto") {
    return el("section", { class: "section s2-panel", "data-s2": "automation" },
      sectionHead("自動執行", "核准計畫之後，VBear 自己派工、審查、轉送審查意見，停在合併關卡。",
        el("div", { class: "row" }, badge("手動", "b-mute"),
          el("button", { class: "btn small primary", type: "button",
            on: { click: () => openAcceptanceDialog(flowId, refresh, { auto: true }) } }, "核准計畫並開啟自動執行…"))),
      el("p", { class: "small muted" },
        "開啟前會完整顯示計畫全文、體力（停損設定）、使用的帳號與全部風險；開啟後手動派工與手動審查會被拒絕。啟動執行者仍由你按。"));
  }
  const held = step && step.held;
  const disable = held ? el("button", { class: "btn small", type: "button", on: { click: async (ev) => {
    ev.target.disabled = true;
    try {
      const r = await api.post(s2Url(flowId, "automation/disable"), {});
      toast(r.event_written === false ? r.event_problem : "已切回手動");
    } catch (e) { toast("無法切回手動：" + e.message); }
    refresh();
  } } }, "切回手動") : null;
  const stop = !held ? s2Confirm("停止流程", "停止後不再派工或審查；執行者正在進行的一輪會自己跑完。", async () => {
    try {
      const r = await api.post(s2Url(flowId, "hold"), {});
      if (r && r.event_written === false) toast(r.event_problem);
      else toast("已停止");
    } catch (e) { toast("無法停止：" + e.message); }
    refresh();
  }, "bad") : null;
  const ap = a.approval;
  return el("section", { class: "section s2-panel", "data-s2": "automation" },
    sectionHead("自動執行", null, el("div", { class: "row" },
      badge(held ? "自動（已停止）" : "自動執行中", held ? "b-warn" : "b-info"), stop, disable)),
    a.problem ? notice("bad", "自動執行的模式紀錄不可信：" + a.problem) : null,
    held ? notice("warn", `已停止：${step.hold_reason || "原因不明"}。停止後不會自動恢復；要繼續請在下面的執行者面板按「繼續」，` +
      "或先切回手動。執行者正在進行的一輪可能還會繼續執行並寫入工作目錄，直到它自己結束，或你關閉 session。") : null,
    step ? el("div", null, el("p", null, el("b", null, "目前步驟："), step.label),
      el("p", { class: "small muted" }, "接著：" + step.after)) : null,
    step && step.awaiting_merge ? notice("info", "審查通過，各項核對成立：到下面「合併與 push 關卡」取得指令，由你自己執行。") : null,
    ap ? el("dl", { class: "kv small" },
      el("dt", null, "核准於"), el("dd", null, fmtTime(ap.at)),
      el("dt", null, "核准的計畫"), el("dd", { class: "mono" }, `${ap.plan_bytes} bytes・sha256 ${String(ap.plan_sha256).slice(0, 16)}…`),
      el("dt", null, "自動執行文字版本"), el("dd", { class: "mono" }, ap.auto_text_version),
      el("dt", null, "核准 id"), el("dd", { class: "mono" }, a.approval_id)) : null,
    el("p", { class: "small muted" }, "用量與體力（停損設定）見下面的「串流執行者」；固定規則：連續失敗 1 次就停止。"));
}

// Whether the Claude Code this machine would run has a verified stream mode, shown before the executor is started.
// The message is the server's (it names the detected version, the supported list and what can be done); text only.
function s2StreamSupport(ss) {
  if (!ss) return null;
  if (ss.state === "verified") {
    return el("p", { class: "small muted", "data-s2": "stream-support" },
      `Claude Code ${ss.detected}：串流模式已通過驗證（VBear 支援串流模式的版本：${(ss.supported || []).join("、")}）。`);
  }
  return el("div", { "data-s2": "stream-support" }, notice("warn", ss.message || "無法確認 Claude Code 的串流模式是否已通過驗證"));
}

function s2ExecutorPanel(flowId, ex, refresh) {
  const sessions = (ex.sessions || []).slice().reverse();
  const live = sessions.find((s) => s.manifest_state === "running" || s.manifest_state === "launching");
  const start = el("button", { class: "btn small primary", type: "button", disabled: !ex.can_start, on: { click: async (ev) => {
    ev.target.disabled = true;
    try { await api.post(s2Url(flowId, "executor"), {}); toast("已啟動執行者"); } catch (e) { s2Fail("無法啟動：", e); }
    refresh();
  } } }, "啟動執行者");
  const why = [];
  if (!ex.can_start) {
    if (ex.acceptance.state !== "valid") why.push("需要有效的風險接受");
    if (ex.stream_support && ex.stream_support.state === "unverified") why.push("這個 Claude Code 版本的串流模式還沒有通過驗證");
    if (ex.stream_support && ex.stream_support.state === "unknown") why.push("讀不到 Claude Code 的版本");
    if (ex.hold && ex.hold.held) why.push("流程已停止");
    if (live) why.push("已有執行中的 session");
    if (ex.workdir_problem) why.push(ex.workdir_problem);
    if (ex.unresolved_failure) why.push("有尚未「繼續」的失敗");
    if (!ex.accounting || !ex.accounting.ok) why.push("用量無法核算");
  }
  const held = ex.hold && ex.hold.held;
  const stop = held ? el("button", { class: "btn small primary", type: "button", on: { click: async (ev) => {
    ev.target.disabled = true;
    try { await api.post(s2Url(flowId, "continue"), {}); toast("已繼續"); } catch (e) { toast("無法繼續：" + e.message); }
    refresh();
  } } }, "繼續")
    : s2Confirm("停止這個流程", "停止後不會再派工或審查；進行中的審查會被結束。", async () => {
      try {
        const r = await api.post(s2Url(flowId, "hold"), {});
        toast(r && r.event_written === false ? r.event_problem : "已停止");
      } catch (e) { toast("無法停止：" + e.message); }
      refresh();
    });
  const acct = ex.accounting;
  const sessionRows = sessions.map((s) => {
    const st = s.status || {};
    const closeBtn = (s.manifest_state === "running" || s.manifest_state === "launching") && st.live
      ? s2Confirm("關閉 session", "確定要關閉這個執行者 session？", async () => {
        try { await api.post(s2Url(flowId, "executor/close"), { launch_id: s.launch_id }); toast("已要求關閉"); }
        catch (e) { toast("無法關閉：" + e.message); }
        refresh();
      }) : null;
    // A dispatch that was prepared and not sent (the console lost the daemon after the prepare, or the send was
    // refused for a reason that has passed): the way out is to send THAT one, or to close the session. In
    // automatic mode the runner owns dispatches and the daemon would refuse a manual send.
    const unsent = st.live && st.unsent && !(ex.automation && ex.automation.mode === "auto") ? st.unsent : null;
    const sendBtn = unsent
      ? s2Confirm("送出這則派工", "送出的就是你當時在預覽裡核准的那一份內容。", async () => {
        try {
          await api.post(s2Url(flowId, "dispatch-send"), { launch_id: s.launch_id, dispatch_id: unsent });
          toast("已送出");
        } catch (e) { toast("無法送出：" + e.message); }
        refresh();
      }, "primary") : null;
    return el("li", { class: "s2-session" },
      el("div", { class: "row" }, el("b", { class: "mono" }, s.launch_id),
        badge(S2_SESSION_STATE[st.state] || (s.manifest_state === "ended" ? "已結束" : (s.manifest_state || "?")),
          st.live ? "b-info" : "b-mute"),
        s.manifest_state === "manual_review" ? badge("待人工處理", "b-warn", s.retained_reason || "") : null,
        closeBtn),
      el("div", { class: "small muted" }, `${s.model_id || ""}　Claude Code ${s.cli_version || "?"}　` +
        `回應 ${st.responses ?? "?"}　費用 ${st.total_cost_usd ?? "?"} USD`),
      s.status_problem ? notice("warn", s.status_problem) : null,
      unsent ? el("div", { class: "s2-unsent" },
        notice("warn", `有一則派工（${String(unsent).slice(0, 8)}…）已準備好但還沒送出；在它送出或這個 session 關閉之前，不能再準備新的派工，也不能開啟自動執行。`),
        el("div", { class: "row" }, sendBtn)) : null,
      st.journal_problem ? notice("bad", "日誌有問題：" + st.journal_problem) : null,
      s.worst_case ? notice("warn", s.worst_case.text) : null);
  });
  return el("section", { class: "section s2-panel", "data-s2": "executor" },
    sectionHead(["串流執行者", " ", teamInfo("executor", "串流執行者")], "由 VBear 啟動的 Claude Code；你逐則核准派工。", el("div", { class: "row" }, start, stop)),
    s2StreamSupport(ex.stream_support),
    why.length ? el("p", { class: "small muted" }, "現在不能啟動：" + why.join("；") + "。") : null,
    held ? notice("warn", `流程已停止：${ex.hold.reason || "（沒有說明）"}${ex.hold.at ? `（${fmtTime(ex.hold.at)}）` : ""}`) : null,
    ex.sessions_problem ? notice("bad", "無法列出 session：" + ex.sessions_problem) : null,
    ex.sessions_order_problem ? notice("warn", "無法判斷 session 的先後：" + ex.sessions_order_problem + "。在這之前不會判定哪一份回報是最新的。") : null,
    acct && acct.ok ? el("ul", { class: "small s2-meters" },
      s2Meter("派工", acct.dispatches, acct.limits.max_dispatches, " 則"),
      s2Meter("執行者模型回應", acct.responses, acct.limits.executor_total_max_responses),
      s2CostMeter(acct),
      s2Meter("審查", acct.reviews, acct.limits.max_reviews, " 次"),
      el("li", { class: "s2-meter" }, `經過時間：${acct.elapsed_s == null ? "尚未開始" : (acct.elapsed_s / 3600).toFixed(2) + " 小時"}` +
        ` ／ 上限 ${acct.limits.max_elapsed_h} 小時`,
        acct.elapsed_s == null ? null
          : (typeof acct.elapsed_s === "number" && Number.isFinite(acct.elapsed_s) && acct.elapsed_s >= 0
             && typeof acct.limits.max_elapsed_h === "number" && Number.isFinite(acct.limits.max_elapsed_h)
             && acct.limits.max_elapsed_h > 0)
            ? el("progress", { class: "s2-bar", max: String(acct.limits.max_elapsed_h),
              value: String(Math.min(acct.elapsed_s / 3600, acct.limits.max_elapsed_h)),
              "aria-label": `經過時間：${(acct.elapsed_s / 3600).toFixed(2)} 小時，上限 ${acct.limits.max_elapsed_h} 小時` })
            : el("span", { class: "small muted" }, " 無法核算（用量或上限不明）")))
      : (acct ? notice("bad", `用量無法核算（${acct.code}）：${acct.message}`) : null),
    (ex.failures || []).length ? el("div", null, el("h3", null, "失敗"),
      el("ul", { class: "small" }, ex.failures.map((f) => el("li", null,
        badge(f.released ? "已繼續" : "未繼續", f.released ? "b-mute" : "b-warn"), ` ${f.kind === "review" ? "審查 " + f.job_id : "session " + f.launch_id}：${f.why}`)))) : null,
    sessions.length ? el("ul", { class: "s2-sessions" }, sessionRows) : emptyState("還沒有執行者 session", null));
}

function s2DispatchComposer(flowId, getExecutor, refresh) {
  const text = el("textarea", { class: "input", rows: "5", maxlength: "60000", "aria-label": "派工內容",
    placeholder: "寫下要請執行者做的事（會先預覽，核准後才送出）" });
  const out = el("div", { class: "s2-preview" });
  const previewBtn = el("button", { class: "btn small primary", type: "button", on: { click: doPreview } }, "預覽");
  const autoNote = el("div", { class: "s2-auto-note" });
  const node = el("section", { class: "section s2-panel", "data-s2": "dispatch" },
    sectionHead("派工", "每一則都要你核准；送出的就是預覽裡顯示的那一份。"), autoNote, text,
    el("div", { class: "row" }, previewBtn), out);
  // In automatic mode the dispatches are the runner's: a manual one is refused by the server and the daemon, so
  // the box says so instead of offering it.
  let automatic = false;
  function setAutomatic(on) {
    if (on === automatic) return;
    automatic = on;
    generation += 1;                            // a preview request already on its way is void
    text.disabled = on;
    previewBtn.disabled = on;
    if (on) setKids(out);                       // a preview made before the switch can no longer be approved here
    setKids(autoNote, on ? notice("info", "自動執行中：派工由 VBear 依核准的計畫進行，手動派工一律拒絕。" +
      "要手動派工，請先停止流程並切回手動。") : null);
  }
  function target() {
    const ex = getExecutor();
    const live = ((ex && ex.sessions) || []).filter((s) => s.manifest_state === "running" && s.status && s.status.live);
    return live.length ? live[live.length - 1].launch_id : null;
  }
  let generation = 0;                           // bumped when the mode switches: an answer from before is dropped
  async function doPreview() {
    const launch = target();
    if (!launch) { toast("目前沒有執行中的執行者 session"); return; }
    previewBtn.disabled = true;
    const mine = generation;
    try {
      const pre = await api.post(s2Url(flowId, "dispatch-preview"), { launch_id: launch, text: text.value });
      if (mine === generation && !automatic) showPreview(pre);
    } catch (e) { if (mine === generation && !automatic) setKids(out, notice("bad", e.message)); }
    if (mine === generation && !automatic) previewBtn.disabled = false;
  }
  function showPreview(pre) {
    const approve = el("button", { class: "btn small primary", type: "button", disabled: !pre.ready, on: { click: async () => {
      approve.disabled = true;
      try {
        await api.post(s2Url(flowId, "dispatch"), { preview_id: pre.preview_id });
        toast("已送出");
        text.value = "";
        setKids(out);
      } catch (e) {
        setKids(out, notice(e.status === 409 ? "warn" : "bad", e.message + (e.status === 409 ? "（這份預覽已作廢，請重新預覽）" : "")));
      }
      refresh();
    } } }, "核准並送出");
    const drop = el("button", { class: "btn small", type: "button", on: { click: () => setKids(out) } }, "放棄這份預覽");
    setKids(out,
      el("p", { class: "small" }, `將送出的內容（${pre.bytes} bytes，sha256 ${pre.text_sha256.slice(0, 12)}…）：`),
      pre.rewritten ? notice("info", "有不可見或控制字元，已改寫成可見的 \\uXXXX（設計 3.3），下面就是實際送出的內容。") : null,
      s2Pre(pre.text),
      pre.ready ? null : notice("warn", "現在還不能送出：" + pre.not_ready_reason),
      el("p", { class: "small muted" }, `這份預覽只能用一次，到 ${fmtTime(pre.expires_at)} 前有效。`),
      el("div", { class: "row" }, approve, drop));
  }
  return { node, setAutomatic, setText(t) { text.value = t; text.focus(); }, hasText: () => text.value.length > 0 };
}

function s2ReportsPanel(rp) {
  if (!rp.ok) return el("section", { class: "section s2-panel", "data-s2": "reports" }, sectionHead("執行者回報", null),
    notice("bad", "無法讀取回報：" + rp.message));
  const entries = (rp.data.reports || []).slice().reverse();
  return el("section", { class: "section s2-panel", "data-s2": "reports" },
    sectionHead("執行者回報", "左邊是執行者自己說的；右邊是 VBear 自己讀檔核對的結果。"),
    rp.data.order_problem ? notice("warn", "無法判定最新的回報：" + rp.data.order_problem + "。不會啟動審查。") : null,
    entries.length ? el("ul", { class: "s2-reports" }, entries.map((e) => {
      const r = e.report;
      return el("li", { class: "s2-report" },
        el("div", { class: "row" }, el("b", { class: "mono" }, shortCommit(e.dispatch_id)),
          badge(e.valid ? "有效回合" : (e.status === "ended" ? "回合無效" : e.status), e.valid ? "b-ok" : "b-mute"),
          e.latest ? badge(e.usable ? "可用來啟動審查" : "核對沒有全部通過", e.usable ? "b-ok" : "b-warn") : null),
        (e.reasons || []).length ? el("div", { class: "small" }, "原因：" + e.reasons.join("；")) : null,
        e.denials && e.denials.count > 0 ? el("div", { class: "small s2-denials" },
          `這一輪有${e.denials.at_least ? "至少 " : " "}${e.denials.count} 次工具呼叫被權限系統擋下（工具：${
            (e.denials.items || []).map((x) => `${x.tool_name}／${x.reason_type}`).join("、") || "不明"}）。`
          + "被擋下的嘗試沒有執行；回合是否有效、審查與合併關卡不受影響，請在合併前自己看一下。") : null,
        r ? el("div", { class: "s2-cols" },
          el("div", null, el("h4", null, "執行者自述"),
            el("dl", { class: "kv small" },
              el("dt", null, "狀態"), el("dd", null, r.status),
              el("dt", null, "head"), el("dd", { class: "mono" }, r.head),
              el("dt", null, "測試"), el("dd", null, `${r.tests.result}：${r.tests.command}`),
              el("dt", null, "測試摘要"), el("dd", null, s2Pre(r.tests.summary)),
              el("dt", null, "備註"), el("dd", null, s2Pre(r.notes)))),
          el("div", null, el("h4", null, "VBear 讀檔核對"),
            e.checks ? el("ul", { class: "s2-checks" }, e.checks.map((c) => el("li", null,
              badge(c.ok === true ? "通過" : (c.ok === false ? "不符" : "讀不到"),
                c.ok === true ? "b-ok" : (c.ok === false ? "b-bad" : "b-warn")), ` ${c.label}`,
              c.detail ? el("span", { class: "small muted" }, `（${c.detail}）`) : null)))
              : el("p", { class: "small muted" }, "較早的回報，不再核對目前的 HEAD。"))) : null);
    })) : emptyState("還沒有回報", "派工並等執行者回合結束後，有效的回報會顯示在這裡。"));
}

// What a review used, in tokens, from the record (never a price). "unavailable" is said as such: it is not 0.
const S2_USAGE_LABELS = [["input_tokens", "輸入"], ["cached_input_tokens", "其中快取讀取"],
  ["cache_write_input_tokens", "寫入快取"], ["output_tokens", "輸出"], ["reasoning_output_tokens", "其中推理"],
  ["total_tokens", "合計"]];
function s2UsageLine(u) {
  if (!u) return null;
  if (u.state === "unavailable" || !u.counts) {
    return el("p", { class: "small muted", "data-s2": "review-usage" }, `用量：無法取得（${u.reason || "原因不明"}）`);
  }
  const n = (v) => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const known = S2_USAGE_LABELS.filter(([k]) => Object.prototype.hasOwnProperty.call(u.counts, k)).map(([k, l]) => `${l} ${n(u.counts[k])}`);
  const other = Object.keys(u.counts).filter((k) => !S2_USAGE_LABELS.some(([x]) => x === k)).sort().map((k) => `${k} ${n(u.counts[k])}`);
  return el("p", { class: "small", "data-s2": "review-usage" },
    `用量（token${u.state === "partial" ? "，至少" : ""}）：${known.concat(other).join("　")}`,
    u.state === "partial" ? el("span", { class: "muted" }, `　${u.reason}`) : null);
}

function s2ReviewsPanel(flowId, ex, rp, rv, composer, refresh) {
  if (!rv.ok) return el("section", { class: "section s2-panel", "data-s2": "reviews" }, sectionHead("Codex 審查", null),
    notice("bad", "無法讀取審查：" + rv.message));
  const reviews = (rv.data.reviews || []).slice().reverse();
  const latest = rp && rp.ok ? (rp.data.reports || []).find((e) => e.latest) : null;
  const running = reviews.find((x) => ["prepared", "launching", "running"].includes(x.state));
  const why = [];
  if (ex && ex.acceptance && ex.acceptance.state !== "valid") why.push("風險接受目前不算數");
  if (ex && ex.hold && ex.hold.held) why.push("流程已停止");
  if (ex && ex.automation && ex.automation.mode === "auto") why.push("自動執行中，手動審查一律拒絕");
  if (!latest) why.push("還沒有有效的執行者回報");
  else if (!latest.usable) why.push("最新回報的讀檔核對沒有全部通過");
  if (running) why.push("已有審查在進行");
  const start = el("button", { class: "btn small primary", type: "button", disabled: why.length > 0, on: { click: async (ev) => {
    ev.target.disabled = true;
    try { const r = await api.post(s2Url(flowId, "review"), {}); toast(`已啟動第 ${r.round} 輪審查`); }
    catch (e) { s2Fail("無法啟動審查：", e); }
    refresh();
  } } }, "請 Codex 審查最新回報");
  const items = reviews.map((x) => {
    const [oLabel, oCls] = S2_REVIEW_OUTCOME[x.outcome] || [x.outcome ? x.outcome : x.state, "b-info"];
    const res = x.result || {};
    const rep = x.report;
    const cancel = running && running.job_id === x.job_id
      ? s2Confirm("取消審查", "取消後這次審查無效，流程會停止。", async () => {
        try { await api.post(s2Url(flowId, "review/cancel"), { job_id: x.job_id }); toast("已要求取消"); }
        catch (e) { toast("無法取消：" + e.message); }
        refresh();
      }) : null;
    const forward = rep && rep.usable ? el("button", { class: "btn small", type: "button", on: { click: async () => {
      try {
        const d = await api.get(s2Url(flowId, `reviews/${encodeURIComponent(x.job_id)}/draft`));
        composer.setText(d.text);
        toast("已放進派工框；請檢查、預覽並核准後才會送出");
      } catch (e) { toast("無法轉送：" + e.message); }
    } } }, "把意見轉給執行者…") : null;
    return el("li", { class: "s2-review" },
      el("div", { class: "row" }, el("b", null, `第 ${x.round} 輪`), el("span", { class: "mono small" }, shortCommit(x.commit)),
        badge(oLabel, oCls), res.verdict ? badge(res.verdict, S2_VERDICT_CLASS[res.verdict] || "b-mute") : null,
        x.live ? badge(`進行中：回應 ${x.live.responses_seen ?? "?"}`, "b-info") : null, cancel, forward),
      (x.invalid_reasons || []).length ? el("div", { class: "small" }, "無效的原因：" + x.invalid_reasons.join("；")) : null,
      x.retained_reason ? notice("warn", "待人工處理：" + x.retained_reason) : null,
      x.record && x.record !== "complete" && x.record !== "none" ? notice("warn", "審查紀錄：" + x.record) : null,
      res.base_is_ancestor !== undefined && res.base_is_ancestor !== null
        ? el("p", { class: "small" }, `BASE_IS_ANCESTOR：${res.base_is_ancestor ? "yes" : "no"}　`,
          el("span", { class: "muted" }, res.base_is_ancestor_note || "")) : null,
      s2UsageLine(x.usage),
      rep && rep.text ? el("details", { class: "s2-report-text", open: x.outcome === "valid" && !running },
        el("summary", null, `審查者的報告（純文字顯示${rep.usable ? "" : "；這次審查無效，僅供參考"}）`),
        s2Pre(rep.text)) : (rep && rep.problem ? el("p", { class: "small muted" }, rep.problem) : null));
  });
  return el("section", { class: "section s2-panel", "data-s2": "reviews" },
    sectionHead("Codex 審查", "審查者寫的內容一律以純文字顯示；BASE_IS_ANCESTOR 是審查者自行回報的，VBear 沒有獨立驗證。", start),
    why.length ? el("p", { class: "small muted" }, "現在不能啟動審查：" + why.join("；") + "。") : null,
    reviews.some((x) => x.usage) && rv.data.usage_note ? el("p", { class: "small muted" }, rv.data.usage_note) : null,
    items.length ? el("ul", { class: "s2-reviews" }, items) : emptyState("還沒有審查", null));
}

function s2GatePanel(g) {
  if (!g.ok) return el("section", { class: "section s2-panel", "data-s2": "gate" }, sectionHead("合併與 push 關卡", null),
    notice("bad", "無法讀取關卡：" + g.message));
  const d = g.data;
  return el("section", { class: "section s2-panel", "data-s2": "gate" },
    sectionHead("合併與 push 關卡", d.note, badge(d.open ? "條件都符合" : "尚未符合", d.open ? "b-ok" : "b-mute")),
    el("ul", { class: "s2-checks" }, d.conditions.map((c) => el("li", null,
      badge(c.ok === true ? "符合" : (c.ok === false ? "不符" : "不明"), c.ok === true ? "b-ok" : (c.ok === false ? "b-bad" : "b-warn")),
      ` ${c.label}`, c.detail ? el("span", { class: "small muted" }, `（${c.detail}）`) : null))),
    d.open ? el("div", null, el("h3", null, "指令（由你自己執行；VBear 不會執行 git）"),
      d.commands.length ? el("ol", { class: "s2-commands" }, d.commands.map((c) => el("li", null,
        el("div", { class: "small" }, c.label), s2Pre(c.command, "mono"), s2Copy(c.command))))
        : notice("info", d.commands_note || "沒有可給的指令。")) : null,
    el("h3", null, "目前本機的狀態（讀檔所得）"),
    el("ul", { class: "small" }, (d.after || []).map((a) => el("li", null, a.text,
      a.is_reviewed_commit ? el("span", null, " ", badge("就是被審的 commit", "b-ok")) : null,
      a.caveat ? el("span", { class: "muted" }, `（${a.caveat}）`) : null))));
}


// ---- what flows keep on disk, and deleting a flow (S2c-5) ---------------------------------------------------------
//
// The sizes and the reasons come from the server (which reads the same files the daemon will re-check);
// "deletable" is only a hint for the button. The daemon decides again, and says why when it refuses.

function s2Bytes(n) {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "未知";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1073741824) return `${(n / 1048576).toFixed(1)} MiB`;
  return `${(n / 1073741824).toFixed(2)} GiB`;
}

// A failed action; a full quota points at the place where old flows can be deleted.
function s2Fail(prefix, e) {
  const hint = e && e.data && e.data.storage ? "（保存的資料已滿：請到「流程」頁下方的「保存的資料」刪除不再需要的舊流程）" : "";
  toast(prefix + e.message + hint);
}

// onlyFlowId: show just that flow (its own page); otherwise every flow that keeps data.
function mountStorage(opts = {}) {
  const body = el("div", { class: "s2-storage-body" });
  let alive = true;
  const leaving = new AbortController();
  async function load() {
    let res;
    try { res = await api.get("/api/flows/storage", { timeoutMs: S2_REQUEST_TIMEOUT_MS, signal: leaving.signal }); }
    catch (e) { if (alive) setKids(body, notice("bad", "無法讀取保存的資料：" + e.message)); return; }
    if (!alive) return;
    let items = res.flows || [];
    if (opts.onlyFlowId) items = items.filter((x) => x.flow_id === opts.onlyFlowId);
    else items = items.filter((x) => x.has_data || x.bytes == null || !x.deletable);
    const full = typeof res.used_bytes === "number" && res.used_bytes >= res.limit_bytes * 0.9;
    const rows = items.map((x) => {
      const del = s2Confirm("刪除這個流程…",
        `刪除「${x.task_id}」這個流程的全部資料（${s2Bytes(x.bytes)}：日誌、派工全文、審查紀錄）與流程紀錄，無法復原。`,
        async () => {
          try {
            const r = await api.post(`/api/flows/${encodeURIComponent(x.flow_id)}/delete`, { flow_id: x.flow_id });
            toast(`已刪除，釋出 ${s2Bytes(r.bytes)}`);
            if (opts.afterDelete) opts.afterDelete(x.flow_id);
          } catch (e) { toast("無法刪除：" + e.message); }
          load();
        }, "bad");
      const button = x.deletable ? del : null;
      return el("li", { class: "s2-storage-item" },
        el("div", { class: "row" }, el("b", { class: "mono" }, x.flow_id), el("span", { class: "small" }, `任務 ${x.task_id}`),
          badge(s2Bytes(x.bytes), x.bytes == null ? "b-warn" : "b-mute"),
          x.has_data ? el("span", { class: "small muted" }, `${x.sessions} 個 session、${x.reviews} 次審查`) : el("span", { class: "small muted" }, "沒有保存的資料"),
          x.held ? badge("已停止", "b-warn") : null,
          x.deleting ? badge("上次刪除沒有完成", "b-warn", "再按一次刪除即可完成") : null, button),
        x.reasons && x.reasons.length
          ? el("ul", { class: "small s2-reasons" }, x.reasons.map((r) => el("li", null, r))) : null,
        x.note ? el("p", { class: "small muted" }, x.note) : null);
    });
    setKids(body,
      el("p", { class: "small" }, `VBear 保存的資料 ${s2Bytes(res.used_bytes)} ／ 上限 ${s2Bytes(res.limit_bytes)}。` +
        "資料會一直保存，直到你刪除流程。"),
      res.problem ? notice("bad", res.problem) : null,
      full ? notice("warn", "保存的資料快滿了，滿了之後不能再啟動執行者或審查。請刪除不再需要的舊流程。") : null,
      el("p", { class: "small muted" }, res.note),
      rows.length ? el("ul", { class: "s2-storage" }, rows) : emptyState("沒有保存的資料", null));
  }
  const refresh = el("button", { class: "btn small", type: "button", on: { click: load } }, "重新整理");
  const node = el("section", { class: "section s2-panel", "data-s2": "storage" },
    sectionHead(opts.onlyFlowId ? "這個流程保存的資料" : "保存的資料", null, refresh), body);
  load();
  return { node, reload: load, stop() { alive = false; leaving.abort(); } };
}

// ---- the section the flow page mounts ------------------------------------------------------------------------

function mountCoordinator(flowId) {
  const data = el("div", { class: "s2-data" });
  let last = null; let state = null; let composer = null; let alive = true;
  let inflight = false; let again = false; let seq = 0;
  let keptKey = null;                            // what decides what the flow keeps: not the clock or the counters
  const leaving = new AbortController();         // the page is left: whatever is on its way is cancelled
  const getExecutor = () => (state && state.executor.ok ? state.executor.data : null);
  const host = el("div", { class: "s2", "data-s2": "root" });
  // One round at a time: a timer tick that finds one running is dropped, an action's refresh is remembered and
  // runs right after it; every round has a number and only the newest answer is applied (Codex S2c-4 review).
  async function refresh(force) {
    if (!alive) return;
    if (inflight) {
      if (force) again = true;
      return;
    }
    inflight = true;
    const mine = ++seq;
    try {
      const next = await s2Load(flowId, leaving.signal);
      if (!alive || mine !== seq) return;
      if (!force && s2QuestionOpen(host)) return;               // asked while this round was on its way
      const key = JSON.stringify(next);
      if (!force && key === last) return;
      last = key;
      state = next;
      let parts = [];
      try {
        parts.push(s2AutomationPanel(flowId, next.automation, () => refresh(true)));
        composer.setAutomatic(next.executor.ok && next.executor.data.automation
          && next.executor.data.automation.mode === "auto");
        if (next.executor.ok) {
          parts.push(s2AcceptancePanel(flowId, next.executor.data, () => refresh(true)),
            s2ExecutorPanel(flowId, next.executor.data, () => refresh(true)));
        } else {
          parts.push(el("section", { class: "section s2-panel" }, sectionHead("串流執行者", null),
            notice("bad", "無法讀取執行者狀態：" + next.executor.message)));
        }
        parts.push(s2ReportsPanel(next.reports),
          s2ReviewsPanel(flowId, getExecutor(), next.reports, next.reviews, composer, () => refresh(true)),
          s2GatePanel(next.gate));
      } catch (e) {
        // an answer in a shape this page does not know: say so, never leave a half page or a dead refresh
        parts = [notice("bad", "無法顯示伺服器的回應（格式不符）：" + (e && e.message ? e.message : String(e)))];
      }
      setKids(data, parts);
      // What is kept (and whether the flow can be deleted) follows the sessions, the reviews and the stop
      // marker: a session that was closed makes the delete button appear without a manual refresh (AGY QA).
      // Elapsed time and the usage counters change every round and say nothing about that, so they do not
      // count (the inventory is a disk walk).
      const kept = JSON.stringify([
        next.executor.ok ? [(next.executor.data.sessions || []).map((s) => [s.launch_id, s.manifest_state,
          s.status && s.status.live]), next.executor.data.hold && next.executor.data.hold.held] : null,
        next.reviews.ok ? (next.reviews.data.reviews || []).map((r) => [r.job_id, r.state, r.outcome]) : null,
        next.automation && next.automation.ok ? next.automation.data.mode : null]);
      const reloadStorage = keptKey !== null && (force || kept !== keptKey);   // an action's own refresh counts
      keptKey = kept;
      if (reloadStorage && storage) storage.reload();
    } finally {
      inflight = false;
      if (again && alive) {
        again = false;
        refresh(true);
      }
    }
  }
  composer = s2DispatchComposer(flowId, getExecutor, () => refresh(true));
  // deleting this flow, from its own page; afterwards there is nothing here to show
  const storage = mountStorage({ onlyFlowId: flowId, afterDelete: () => { location.hash = "#/flows"; } });
  host.append(el("div", { class: "section" }, el("h2", null, "VBear 管理的執行與審查"),
    el("p", { class: "small muted" }, "以下由 VBear 的背景程序執行。手動模式下，風險接受與每一則派工都先預覽、再由你核准；" +
      "自動執行模式下，派工與審查由 VBear 依你核准的計畫進行，每個動作都有稽核事件。「手動記錄事件」那一區沒有改變，仍然只是記錄。")),
    data, composer.node, storage.node);
  refresh(true);
  return {
    node: host, refresh, composer,
    // quiet refresh for the timer: not while a dialog is open or the user is in a field of the panels
    tick() {
      if (typeof document !== "undefined" && document.querySelector && document.querySelector(".modal-backdrop")) return Promise.resolve();
      if (s2QuestionOpen(host)) return Promise.resolve();    // a question is open: the panels stay as they are
      return refresh(false);
    },
    stop() { alive = false; leaving.abort(); storage.stop(); },
  };
}

// Built-in terminals: the user's own login shell, opened from VBear. They are
// ordinary terminals under the user's account (no sandbox), unlike Profile-
// managed Agent launches, and the UI says so wherever they appear.
const SHELL_NOTE = "一般終端機：以你的帳號直接執行，不受沙盒限制（跟受管的 Agent 不同）。";

function shellPanes(panes = (D.live && D.live.panes) || []) {
  return panes.filter((p) => p.kind === "shell" && !p.exited);
}

function shellLabel(p, home = D.live && D.live.home) {
  const trim = (x) => (x.length > 1 ? x.replace(/\/+$/, "") : x);
  const cwd = trim((p && p.cwd) || "");
  if (!cwd || (home && cwd === trim(home))) return "~";
  return cwd.split("/").filter(Boolean).pop() || "/";
}

// Tab names: the folder name, numbered when several terminals share it.
function shellTabLabels(panes, home) {
  const seen = new Map();
  const total = new Map();
  for (const p of panes) { const l = shellLabel(p, home); total.set(l, (total.get(l) || 0) + 1); }
  return panes.map((p) => {
    const l = shellLabel(p, home);
    const n = (seen.get(l) || 0) + 1;
    seen.set(l, n);
    return total.get(l) > 1 ? `${l} (${n})` : l;
  });
}

async function openShellTerminal(dir) {
  const cwd = (dir || "").trim() || "~";
  const r = await api.post("/api/native/terminals", { cwd });
  store.set("terminal.lastDir", cwd);
  location.hash = `#/term/${encodeURIComponent(r.session.session_id)}`;
}

function newTerminalForm() {
  const input = el("input", { type: "text", class: "input mono", value: store.get("terminal.lastDir", "~"),
    "aria-label": "資料夾", placeholder: "~/projects/app", spellcheck: "false", autocomplete: "off" });
  const btn = el("button", { class: "btn primary", type: "submit" }, "開啟終端機");
  const form = el("form", { class: "row new-term-form", on: { submit: async (ev) => {
    ev.preventDefault();
    btn.disabled = true;
    try { await openShellTerminal(input.value); }
    catch (e) { toast("無法開啟終端機：" + e.message); btn.disabled = false; }
  } } }, el("label", { class: "small" }, "資料夾"), input, btn);
  return form;
}

async function viewTerminals() {
  const token = seq;
  await loadLive();
  const main = claim(token);
  if (token !== seq) return;
  const panes = shellPanes();
  setKids(main,
    el("h1", null, "終端機"),
    el("p", { class: "lede" }, "在指定資料夾開啟你的登入 shell，直接打字使用。關掉這個頁面或主控台，終端機會繼續執行，回來就能接著用。"),
    runtimeNotice(),
    notice("info", SHELL_NOTE),
    el("section", { class: "section" },
      sectionHead("開新的終端機", "資料夾必須在你的家目錄內"),
      newTerminalForm()),
    el("section", { class: "section" },
      sectionHead("開著的終端機", `${panes.length} 個`),
      panes.length
        ? el("ul", { class: "term-list" }, panes.map((p) => el("li", { class: "row" },
            el("a", { class: "btn small primary", href: `#/term/${encodeURIComponent(p.pane_id)}` }, "開啟"),
            el("b", null, shellLabel(p)),
            el("span", { class: "small muted mono" }, p.cwd || ""),
            closeSessionButton(p.pane_id, "#/terminals"))))
        : emptyState("還沒有開著的終端機", "在上方選一個資料夾，按「開啟終端機」。")));
}

async function viewTerminal(paneId) {
  const token = seq;
  cleanupActiveTerminal();
  await Promise.all([loadStatic(), loadLive()]);
  const main = claim(token);
  if (token !== seq) return;

  const session = (D.live.sessions || []).find((s) => s.pane_id === paneId);
  const pane = (D.live.panes || []).find((p) => p.pane_id === paneId);
  // A built-in terminal is the user's own shell: it takes input as soon as it
  // connects (no takeover dialog) and is labelled as unsandboxed.
  const isShell = Boolean(pane && pane.kind === "shell");
  const backHash = isShell ? "#/terminals" : "#/team";
  const roleName = isShell ? `終端機 · ${shellLabel(pane)}`
    : session ? (session.role_label || session.agent || paneId) : paneId;
  const toolName = session ? (TOOL[session.agent] || session.agent) : "終端";
  const project = session ? (D.live.projects || []).find((p) => p.project_id === session.project_id) : null;

  let mode = "observe";
  let connState = "connecting";
  let closedReason = "";
  let sessionGone = false;  // the runtime answered 404: nothing left to reconnect to or close
  let errorMsg = "";
  let retryTimer = null;
  let resizeTimer = null;
  let abortController = null;
  let term = null;
  let fitAddon = null;
  let resizeObserver = null;
  let modalElem = null;
  let isDisposed = false;
  let termReady = false;
  let pendingTakeover = null;
  // The current control session's token (set on a successful takeover,
  // cleared whenever we drop back to observe). Unmounting/switching away
  // while in control must abandon *this* token, not send an unconditional
  // release — release() has no token and always acts on whatever session is
  // currently installed, so it would steal control back from a newer
  // takeover (e.g. another tab) that raced in after ours (L2/token safety).
  let controlToken = null;
  let autoTakeoverDone = false;

  const reconnectPolicy = createReconnectPolicy({
    maxRetries: 5,
    baseDelayMs: 1000,
    factor: 1.5,
    maxDelayMs: 8000,
  });

  const modeBadge = el("span");
  const connBadge = el("span");
  const bannerWrap = el("div", { class: "term-warning-box" });
  const actionWrap = el("div", { class: "term-toolbar" });
  const dimInfo = el("span", { class: "term-dim-info" }, "—");
  const termElem = el("div", { class: "term-container", role: "region", "aria-label": `終端 ${paneId}` });
  const termWrap = el("div", { class: "term-container-wrap" }, termElem);

  const inputBatcher = createInputBatcher(async (text) => {
    if (isDisposed || mode !== "control") return;
    await api.post(`/api/term/${encodeURIComponent(paneId)}/input`, { text });
  }, {
    onError: (err) => {
      if (isDisposed) return;
      toast("鍵盤輸入傳送失敗，已捨棄未送出之內容（不自動重播）：" + (err ? err.message : "網路錯誤"));
    },
  });

  function updateUI() {
    if (token !== seq || isDisposed) return;

    if (mode === "control") {
      setKids(modeBadge, badge("操作控制中 (Control)", "b-ok", "目前可由此網頁終端輸入"));
    } else {
      setKids(modeBadge, badge("僅觀看 (Observe)", "b-info", "目前為觀看模式，無法鍵盤輸入"));
    }

    if (connState === "connected") {
      setKids(connBadge, badge("連線正常", "b-ok"));
    } else if (connState === "connecting") {
      setKids(connBadge, badge("連線中…", "b-warn"));
    } else if (connState === "disconnected") {
      setKids(connBadge, badge("連線中斷", "b-bad"));
    } else if (connState === "closed") {
      setKids(connBadge, badge("已結束", "b-mute"));
    } else if (connState === "error") {
      setKids(connBadge, badge("錯誤", "b-bad"));
    }

    const notices = [];
    if (isShell) {
      notices.push(notice("info", SHELL_NOTE + " 同一個終端機在另一個分頁打開時，輸入會移到那邊；這裡按「接管操作」可以拿回來。"));
    } else if (mode === "control") {
      notices.push(notice("warn", "⚠️ 目前處於接管控制模式：你在這裡輸入的內容會直接送給 Agent。其他分頁接管時，這裡會自動改回僅觀看。"));
    }
    if (connState === "closed") {
      notices.push(notice("info", `終端機連線已關閉${closedReason ? "：" + closedReason : ""}${sessionGone
        ? (isShell ? "需要新的終端機時，請到「終端機」頁開啟。" : "需要新的終端時，請從角色卡的「出發通行證」開啟。")
        : "如需重新開啟請點選右上方「重新連線」。"}`));
    } else if (connState === "disconnected") {
      const attempts = reconnectPolicy.getRetryCount();
      const waitText = reconnectPolicy.canAutoRetry()
        ? `將於稍後自動重試（第 ${attempts}/5 次）...`
        : "已達最大重試次數，請手動點選「重新連線」。";
      notices.push(notice("bad", `與伺服器終端串流中斷。${waitText}`));
    } else if (connState === "error") {
      notices.push(notice("bad", `連線錯誤：${errorMsg || "無法連接終端串流"}`));
    }
    setKids(bannerWrap, notices);

    const actions = [];
    if (connState === "connected") {
      if (mode === "observe") {
        actions.push(el("button", { class: "btn small primary", type: "button", on: { click: promptTakeover } }, "接管操作"));
      } else {
        actions.push(el("button", { class: "btn small", type: "button", on: { click: doRelease } }, "釋放控制"));
      }
    }
    if (!sessionGone && shouldShowTerminalRetryAction({ isDisposed, termReady, connState })) {
      actions.push(el("button", { class: "btn small primary", type: "button", on: { click: manualReconnect } }, "重新連線"));
    }
    if (!sessionGone) actions.push(closeSessionButton(paneId, backHash));
    actions.push(el("a", { class: "btn small", href: backHash }, isShell ? "所有終端機" : "返回團隊"));
    setKids(actionWrap, actions);

    if (term) {
      dimInfo.textContent = `${term.cols} × ${term.rows}`;
    }
  }

  function promptTakeover() {
    if (modalElem) return;
    const confirmBtn = el("button", { class: "btn primary", type: "button", on: { click: () => onConfirm() } }, "確認接管操作");
    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    modalElem = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-takeover-title" },
      el("div", { class: "modal-box" },
        el("h2", { id: "modal-takeover-title" }, "確認接管終端操作"),
        el("p", null, "您即將接管此終端的鍵盤輸入控制。"),
        el("div", { class: "notice warn", style: "margin: 4px 0" },
          el("span", { class: "ico", "aria-hidden": "true" }, "!"),
          el("div", null, "重要提醒：接管後由這個分頁送出鍵盤輸入；同一時間只有一個分頁能控制，其他分頁接管時這裡會自動改回僅觀看。若 Agent 正在執行任務，請避免非預期的干擾。")),
        el("p", { class: "small muted" }, "接管後您隨時可以點選「釋放控制」回到僅觀看狀態。"),
        el("div", { class: "modal-actions" }, cancelBtn, confirmBtn)));
    document.body.append(modalElem);

    // withModalA11y must capture document.activeElement (the opener) before
    // focus moves into the dialog below — otherwise it would capture
    // confirmBtn itself and Escape/close would try to refocus an element
    // that's about to be removed instead of restoring focus to the opener.
    // It also registers this dialog so terminal/view cleanup closes it
    // through this same teardown (removes it, restores background
    // inert/aria-hidden) instead of yanking modalElem out of the DOM.
    const closeModal = withModalA11y(modalElem, () => {
      if (modalElem) {
        modalElem.remove();
        modalElem = null;
      }
    });
    confirmBtn.focus();

    async function onConfirm() {
      confirmBtn.disabled = true;
      let res;
      try {
        pendingTakeover = api.post(`/api/term/${encodeURIComponent(paneId)}/control`, {
          action: "takeover",
          ...termDimsForRequest(term),
        });
        res = await pendingTakeover;
      } catch (err) {
        if (!isDisposed) {
          toast("接管失敗：" + err.message);
          confirmBtn.disabled = false;
        }
        return;
      } finally {
        pendingTakeover = null;
      }

      await handleTakeoverResponse({
        res,
        isDisposed,
        paneId,
        apiPost: (path, body) => api.post(path, body),
        onLiveSuccess: (r) => {
          mode = "control";
          controlToken = r.token;
          inputBatcher.setEnabled(true);
          toast("已接管終端操作（其他分頁會改回僅觀看）");
          closeModal();
          updateUI();
          if (term) term.focus();
        },
        onLiveError: (r) => {
          toast("接管失敗：" + (r?.error || "未知錯誤"));
          confirmBtn.disabled = false;
        },
      });
    }
  }

  // Built-in terminals only: take input control right after the stream
  // connects, once per page visit. Same API as the dialog, without the dialog.
  async function autoTakeover() {
    autoTakeoverDone = true;
    let res;
    try {
      pendingTakeover = api.post(`/api/term/${encodeURIComponent(paneId)}/control`, {
        action: "takeover",
        ...termDimsForRequest(term),
      });
      res = await pendingTakeover;
    } catch (err) {
      if (!isDisposed) toast("無法取得輸入控制：" + err.message);
      return;
    } finally {
      pendingTakeover = null;
    }
    await handleTakeoverResponse({
      res,
      isDisposed,
      paneId,
      apiPost: (path, body) => api.post(path, body),
      onLiveSuccess: (r) => {
        mode = "control";
        controlToken = r.token;
        inputBatcher.setEnabled(true);
        updateUI();
        if (term) term.focus();
      },
      onLiveError: (r) => toast("無法取得輸入控制：" + (r?.error || "未知錯誤")),
    });
  }

  async function doRelease() {
    await handleReleaseAction({
      isDisposed,
      mode,
      connState,
      inputBatcher,
      apiPost: (body) => api.post(`/api/term/${encodeURIComponent(paneId)}/control`, body),
      onObserve: () => {
        mode = "observe";
        controlToken = null;
        toast("已釋放操作控制，切換為僅觀看模式");
        updateUI();
      },
      onError: (err) => {
        toast("釋放控制失敗，維持操作模式：" + (err ? err.message : "網路錯誤"));
        updateUI();
      },
    });
  }

  function onStreamDrop(reason) {
    if (isDisposed || connState === "closed") return;
    connState = "disconnected";
    if (mode === "control") {
      mode = "observe";
      controlToken = null;
      inputBatcher.setEnabled(false);
    }
    inputBatcher.clear();
    updateUI();

    const dropInfo = reconnectPolicy.recordDrop();
    if (dropInfo.shouldRetry) {
      clearTimeout(retryTimer);
      retryTimer = setTimeout(() => {
        if (!isDisposed && connState === "disconnected") {
          startStream();
        }
      }, dropInfo.delayMs);
    } else {
      updateUI();
    }
  }

  function manualReconnect() {
    if (!canStartTerminalStream({ isDisposed, termReady })) return;
    clearTimeout(retryTimer);
    reconnectPolicy.resetManual();
    startStream();
  }

  async function startStream() {
    if (!canStartTerminalStream({ isDisposed, termReady })) return;
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    connState = "connecting";
    updateUI();

    abortController = new AbortController();
    const signal = abortController.signal;
    const { cols, rows } = termDimsForRequest(term);
    const url = `/api/term/${encodeURIComponent(paneId)}/stream?cols=${cols}&rows=${rows}`;

    try {
      const res = await fetch(url, {
        method: "GET",
        headers: {
          Accept: "text/event-stream",
          "X-VBear": "1",
        },
        signal,
      });

      if (!res.ok) {
        if (res.status === 404) {
          connState = "closed";
          sessionGone = true;
          closedReason = "此終端已不存在（已關閉或從未存在）。";
        } else if (res.status === 429) {
          connState = "error";
          errorMsg = "終端連線已達上限（最多 4 個），請關閉其他終端分頁 (429)";
        } else if (res.status === 403) {
          connState = "error";
          errorMsg = "權限不足 (403)";
        } else {
          connState = "error";
          errorMsg = `連線失敗 (HTTP ${res.status})`;
        }
        updateUI();
        return;
      }

      connState = "connected";
      reconnectPolicy.recordConnectionSuccess();
      updateUI();
      if (isShell && !autoTakeoverDone && mode === "observe") autoTakeover();

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8", { stream: true });
      const parser = createSSEParser(
        (event) => {
          if (isDisposed) return;
          const msg = event.data;
          if (!msg) return;
          if (msg.type === "terminal.frame") {
            handleTerminalFrame(msg, { term, reconnectPolicy });
          } else if (msg.type === "terminal.closed") {
            connState = "closed";
            closedReason = msg.reason || "終端機已結束";
            if (mode === "control") {
              mode = "observe";
              controlToken = null;
              inputBatcher.setEnabled(false);
            }
            inputBatcher.clear();
            updateUI();
          }
        },
        (err) => {
          console.warn("SSE parse error:", err);
        }
      );

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          parser.feed(decoder.decode(value, { stream: true }));
        }
      }
      const rem = decoder.decode();
      if (rem) parser.feed(rem);
      parser.flush();

      if (connState !== "closed" && !signal.aborted && !isDisposed) {
        onStreamDrop("伺服器連線已中斷 (EOF)");
      }
    } catch (err) {
      if (signal.aborted || isDisposed) return;
      onStreamDrop(err.message);
    }
  }

  function handleResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(async () => {
      if (isDisposed || !term || !fitAddon || !termElem.parentElement) return;
      const dims = fitAddon.proposeDimensions();
      if (!usableTermDims(dims)) return;
      if (dims.cols === term.cols && dims.rows === term.rows) return;
      fitAddon.fit();
      dimInfo.textContent = `${term.cols} × ${term.rows}`;
      if (mode === "control" && connState === "connected") {
        try {
          await api.post(`/api/term/${encodeURIComponent(paneId)}/control`, {
            action: "resize",
            cols: term.cols,
            rows: term.rows,
          });
        } catch (e) {
          console.warn("Resize POST failed:", e);
        }
      }
    }, 150);
  }

  const shellTabs = isShell
    ? el("nav", { class: "term-tabs", "aria-label": "開著的終端機" },
        ((tabs) => tabs.map((p, i) => el("a", { class: "term-tab", href: `#/term/${encodeURIComponent(p.pane_id)}`,
          title: p.cwd || "", "aria-current": p.pane_id === paneId ? "page" : null },
          shellTabLabels(tabs, D.live.home)[i])))(shellPanes()),
        el("a", { class: "term-tab term-tab-new", href: "#/terminals", title: "開新的終端機" }, "＋"))
    : null;

  setKids(main,
    isShell ? crumbs([["終端機", "#/terminals"], [shellLabel(pane)]])
      : crumbs([["角色卡池", "#/team"], [`終端機 (${paneId})`]]),
    shellTabs,
    el("div", { class: "term-head" },
      el("div", { class: "term-meta" },
        el("div", { class: "row" },
          el("h1", null, roleName),
          isShell ? badge("一般終端機", "b-warn", SHELL_NOTE) : toolTag(session ? session.agent : "terminal"),
          modeBadge,
          connBadge),
        el("p", { class: "small muted mono", style: "margin:0" },
          `Pane ID: ${paneId}`,
          project ? ` · 專案: ${project.name}` : "",
          " · 尺寸: ", dimInfo)),
      actionWrap),
    bannerWrap,
    termWrap,
    el("div", { class: "legend section" },
      isShell ? null : el("span", null, el("b", null, "觀看模式"), "：預設唯讀轉送畫面，不攔截鍵盤，亦不對 Agent 送出輸入"),
      isShell ? null : el("span", null, el("b", null, "接管操作"), "：經確認後可由瀏覽器打字；同一時間只有一個分頁能控制"),
      el("span", { class: "term-history-notice" }, TERMINAL_VISIBLE_SCREEN_NOTICE))
  );

  activeTerminalCleanup = () => {
    isDisposed = true;
    termReady = false;
    // Abandon (not release!) our control session on the server before
    // tearing down the stream, so navigating away while controlling cannot
    // leave the pane orphaned in control mode for anyone else who opens it
    // (L2). This is token-guarded (M3/H3): release() has no token and
    // unconditionally hands whatever session is *currently* installed back
    // to observe, so if a newer takeover (another tab, or a fresh takeover
    // right here) already replaced ours by the time this runs, release()
    // would silently steal that session back to observe. abandon(token)
    // only stops the session if it still matches the one we took over —
    // otherwise it is a safe no-op. Best effort either way: if this fails,
    // the server-side stream disconnect (close_if_current) still releases
    // whatever session this stream's SSE connection was actually watching.
    if (mode === "control") {
      mode = "observe";
      const tokenToAbandon = controlToken;
      controlToken = null;
      api.post(`/api/term/${encodeURIComponent(paneId)}/control`,
        { action: "abandon", token: tokenToAbandon }).catch(() => {});
    }
    reconnectPolicy.resetManual();
    clearTimeout(retryTimer);
    clearTimeout(resizeTimer);
    inputBatcher.setEnabled(false);
    inputBatcher.clear();
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    // Any open takeover modal is already closed by this point: cleanupActiveTerminal()
    // calls closeOpenModals() before invoking this callback, which runs the
    // modal's own registered teardown (removes it, restores background
    // inert/aria-hidden) rather than this code reaching in directly.
    if (term) {
      try { term.dispose(); } catch (_) {}
      term = null;
    }
    window.removeEventListener("resize", handleResize);
  };

  const TerminalClass = (typeof window !== "undefined" && window.Terminal) || (typeof Terminal !== "undefined" && Terminal) || null;
  const FitAddonClass = (typeof window !== "undefined" && (window.FitAddon?.FitAddon || window.FitAddon)) || (typeof FitAddon !== "undefined" && (FitAddon.FitAddon || FitAddon)) || null;

  const termInit = initTerminalInstance({
    TerminalClass,
    FitAddonClass,
    termElem,
  });

  if (!termInit.ok) {
    termReady = false;
    connState = "error";
    errorMsg = termInit.error;
    setKids(termElem,
      el("div", { class: "notice bad", role: "alert", style: "margin: 16px" },
        el("span", { class: "ico", "aria-hidden": "true" }, "✕"),
        el("div", null,
          el("b", null, "終端機載入失敗"),
          el("p", { class: "small", style: "margin: 4px 0 0" }, termInit.error))));
    updateUI();
    return;
  }

  term = termInit.term;
  fitAddon = termInit.fitAddon;
  termReady = true;
  dimInfo.textContent = `${term.cols} × ${term.rows}`;

  term.onData((data) => {
    if (mode === "control" && connState === "connected") {
      inputBatcher.push(data);
    }
  });

  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(termWrap);
  }
  window.addEventListener("resize", handleResize);

  updateUI();
  startStream();
}

// ---------- Phase B1-B4: Unified Workbench, Tasks & Governance -------------

function computeTaskProvenance(prov = {}, rawStatus = "draft", closure = null) {
  const agent = (prov && prov.agent) || "pending";
  const tests = (prov && prov.tests) || "untested";
  const human = (prov && prov.human) || "pending";
  // No authenticated verifier exists anywhere in this console (mirrors
  // tasks.py H1): this is an honestly-named *assertion* — tests and human
  // approval were both set through this same unauthenticated UI/API — never
  // a governed or cryptographically verified fact. Nothing here computes or
  // exposes a "verified" boolean; that field is only ever hardcoded false
  // on the backend. Both results must also still refer to the commit the
  // workdir is on now; only the server can read that, so its
  // verification_asserted flag is required as well (tasks._derive).
  const bothAsserted = (tests === "passed" && human === "approved");
  const verificationAsserted = bothAsserted && Boolean(prov && prov.verification_asserted === true);
  const reason = closure && closure.reason;
  let derivedStatus = "draft";
  if (verificationAsserted) {
    derivedStatus = "verification_asserted";
  } else if (bothAsserted) {
    derivedStatus = "verification_stale";
  } else if (agent === "completed" && reason === "handed_off_to") {
    derivedStatus = "handed_off";
  } else if (agent === "completed" && ["superseded", "canceled", "denied"].includes(reason)) {
    derivedStatus = "closed";
  } else if (agent === "completed") {
    derivedStatus = "agent_completed";
  } else if (agent === "in_progress") {
    derivedStatus = "in_progress";
  } else if (agent === "blocked") {
    derivedStatus = "blocked";
  } else if (["draft", "in_progress"].includes(rawStatus)) {
    // Mirrors tasks.CLIENT_ASSERTABLE_STATUSES: completed and blocked come
    // only from the agent field, which requires a closure reason.
    // "verification_asserted" is deliberately excluded here too (mirrors
    // tasks.py H1): it must only ever be derived from verificationAsserted
    // above, never accepted as a raw status string, or a stale/forged
    // rawStatus could render a verification-looking badge for a task that
    // isn't.
    derivedStatus = rawStatus;
  }
  return { agent, tests, human, verificationAsserted, derivedStatus };
}

const TASK_STATUS_LABELS = {
  draft: ["草稿", "b-mute", "還沒有人把這張任務卡標成「執行中」；這只是標記，不代表有沒有人在做"],
  in_progress: ["執行中", "b-info", "Agent 或開發者正在進行此任務"],
  agent_completed: ["待驗收 (Agent回報完成)", "b-warn", "Agent 已回報完成，但尚未通過測試驗證與人類核准"],
  verification_asserted: ["聲稱驗證通過 (Verification Asserted)", "b-ok", "此主控台無身份驗證：僅代表自動化測試與介面核准兩欄皆已透過本頁/API 自我回報為通過，並非經授權之正式驗證"],
  blocked: ["等待回覆 / 阻塞", "b-bad", "任務遭遇問題等待指示"],
  verification_stale: ["結果對應的版本已變更", "b-warn", "測試或核准記錄時的 commit 與目前不同（或無法確認）；需要重新測試與核准"],
  handed_off: ["已交接", "b-mute", "已交給下一位；後續請看接手的任務卡"],
  closed: ["已結案（未完成）", "b-mute", "取消、拒絕執行或被其他任務取代"],
};
// tasks.CLOSURE_REASONS, in the order offered.
const CLOSURE_REASONS = {
  completed: [["no_follow_on", "完成，沒有後續"], ["handed_off_to", "交給下一位"],
    ["superseded", "被其他任務取代"], ["canceled", "取消"], ["denied", "拒絕執行"]],
  blocked: [["blocked_on", "卡在某人或某事"], ["escalation", "已上報"]],
};
const CLOSURE_NEEDS_TARGET = new Set(["handed_off_to", "blocked_on", "escalation"]);
const CLOSURE_LABEL = Object.fromEntries([...CLOSURE_REASONS.completed, ...CLOSURE_REASONS.blocked]);
const PICKUP = {
  closed: ["已結案", "b-mute"], blocked: ["阻塞中", "b-bad"], unclaimed: ["尚未認領", "b-warn"],
  working: ["處理中", "b-info"], parked: ["停在等你", "b-warn"], stalled: ["中斷", "b-bad"],
  unknown: ["處理狀態未知", "b-mute"],
};
const BINDING = {
  current: ["對應目前版本", "b-ok"], stale: ["版本已變更", "b-warn"], mismatch: ["測試與核准版本不同", "b-warn"],
  unknown: ["無法確認版本", "b-warn"], unbound: ["未綁定版本", "b-mute"], none: ["尚無結果", "b-mute"],
};
// A badge alone says little to someone new: these two get a sentence beside them (draft, and nobody has picked it up).
// "draft" is what a card derives to when nobody marked it in progress: it says nothing about whether work has begun.
const TASK_STATUS_EXPLAIN = { draft: "草稿：還沒有人把這張任務卡標成「執行中」。這只是標記，不代表沒人在做；做到哪一步，看下方的隊伍與下一步。" };
const PICKUP_EXPLAIN = { unclaimed: "尚未認領：還沒有把這張任務卡關聯到任何終端（關聯只是追蹤記錄，不會把內容送進終端）。" };
function taskStatusExplain(status, pickup) {
  const out = [];
  if (cardHas(TASK_STATUS_EXPLAIN, status)) out.push(TASK_STATUS_EXPLAIN[status]);
  const state = pickup && typeof pickup === "object" ? pickup.state : "";
  if (typeof state === "string" && cardHas(PICKUP_EXPLAIN, state)) out.push(PICKUP_EXPLAIN[state]);
  return out;
}
function pickupBadge(p) {
  const [label, cls] = PICKUP[(p && p.state)] || PICKUP.unknown;
  return badge(label, cls, `處理狀態（由關聯終端即時推算，不是誰填的）：${(p && p.detail) || "沒有資料"}`);
}
function bindingBadge(b) {
  const [label, cls] = BINDING[(b && b.state)] || BINDING.unknown;
  return badge(label, cls, (b && b.detail) || "");
}

function taskStatusBadge(status) {
  const [label, cls, title] = TASK_STATUS_LABELS[status] || TASK_STATUS_LABELS.draft;
  return badge(label, cls, title);
}

// The workbench stacks its columns at 900px and narrower (style.css); there the right column is far down the page.
function workbenchStacked() {
  try { return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 900px)").matches; }
  catch (_) { return false; }
}

async function viewWorkbench(initialPaneId, initialTaskId, initialProfileId, autoLaunch = false, initialStep = "") {
  const token = seq;
  cleanupActiveTerminal();
  const [staticData, liveData, tasksRes, templatesRes, govRes,
          profilesRes, catalogRes] = await Promise.all([
    loadStatic(),
    loadLive(),
    api.get("/api/tasks").catch(() => ({ ok: false, tasks: [] })),
    api.get("/api/task-templates").catch(() => ({ ok: false, templates: {} })),
    api.get("/api/governance").catch(() => ({ ok: false })),
    api.get("/api/agent-profiles").catch(() => ({ ok: false, profiles: [] })),
    api.get("/api/agent-builder/catalog").catch(() => ({ ok: false })),
  ]);

  const main = claim(token);
  if (token !== seq) return;

  const sessions = (D.live && D.live.sessions) || [];
  let tasksList = (tasksRes && tasksRes.tasks) || [];
  const templates = (templatesRes && templatesRes.templates) || {};
  const govData = govRes || {};
  // Agent Profile state (Phase C). The list is owned by the local mutation
  // helpers below so editing/duplicating/deleting re-renders the right
  // panel without a full viewWorkbench() round-trip. The catalog is
  // fetched once on view mount and reused for every editor modal: the
  // tools/permission enums never change inside a single tab lifetime and
  // a re-fetch is wasted bandwidth.
  let agentProfiles = (profilesRes && profilesRes.profiles) || [];
  let agentBuilderCatalog = (catalogRes && catalogRes.ok) ? catalogRes : null;

  // Determine active pane ID
  let activePaneId = initialPaneId;
  if (!activePaneId && sessions.length > 0) {
    activePaneId = sessions[0].pane_id;
  }

  // Determine active task ID
  let activeTaskId = initialTaskId;
  if (!activeTaskId && activePaneId) {
    const matched = tasksList.find((t) => t.associated_pane_id === activePaneId);
    if (matched) activeTaskId = matched.id;
  }
  if (!activeTaskId && tasksList.length > 0) {
    activeTaskId = tasksList[0].id;
  }

  // Layout states
  let leftCollapsed = store.get("wb:left_collapsed", false);
  // An Armory/Profile deep link must reveal its target, even if this browser
  // previously remembered the right column as collapsed.
  let rightCollapsed = (initialProfileId || initialTaskId) ? false : store.get("wb:right_collapsed", false);
  let focusMode = false;
  let activeTab = initialProfileId ? "agent" : "task"; // "task" | "agent" | "project" | "global"

  const shell = el("div", { class: "wb-shell" });
  const leftCol = el("div", { class: "wb-col wb-left side-col" });
  const centerCol = el("div", { class: "wb-col wb-term-center" });
  const rightCol = el("div", { class: "wb-col wb-right side-col" });
  shell.append(leftCol, centerCol, rightCol);

  // Persistent reopen controls (M3): rendered once, independent of
  // activePaneId or collapsed/mobile state, so a collapsed column can always
  // be reopened — the in-column "◀"/"▶" collapse buttons disappear along
  // with their column (`.wb-col.collapsed{display:none}`) and the terminal's
  // own toolbar toggle only exists once a pane is loaded, so neither can be
  // the only way back.
  const leftToggleBtn = el("button", {
    class: "btn small wb-col-toggle",
    type: "button",
    on: { click: toggleLeft },
  });
  const rightToggleBtn = el("button", {
    class: "btn small wb-col-toggle",
    type: "button",
    on: { click: toggleRight },
  });
  const toolbar = el("div", { class: "wb-toolbar" }, leftToggleBtn, rightToggleBtn);

  function syncLayoutClasses() {
    if (leftCollapsed) {
      shell.classList.add("left-collapsed");
      leftCol.classList.add("collapsed");
      leftCol.classList.remove("mobile-show");
      leftToggleBtn.textContent = "► 展開左欄";
      leftToggleBtn.setAttribute("aria-pressed", "false");
    } else {
      shell.classList.remove("left-collapsed");
      leftCol.classList.remove("collapsed");
      leftCol.classList.add("mobile-show");
      leftToggleBtn.textContent = "◄ 收合左欄";
      leftToggleBtn.setAttribute("aria-pressed", "true");
    }
    if (rightCollapsed) {
      shell.classList.add("right-collapsed");
      rightCol.classList.add("collapsed");
      rightCol.classList.remove("mobile-show");
      rightToggleBtn.textContent = "任務與隊伍 ◄";
      rightToggleBtn.setAttribute("aria-pressed", "false");
    } else {
      shell.classList.remove("right-collapsed");
      rightCol.classList.remove("collapsed");
      rightCol.classList.add("mobile-show");
      rightToggleBtn.textContent = "任務與隊伍 ►";
      rightToggleBtn.setAttribute("aria-pressed", "true");
    }
    if (focusMode) {
      shell.classList.add("focus-mode");
      toolbar.classList.add("hidden");
    } else {
      shell.classList.remove("focus-mode");
      toolbar.classList.remove("hidden");
    }
  }

  function toggleLeft() {
    leftCollapsed = !leftCollapsed;
    store.set("wb:left_collapsed", leftCollapsed);
    syncLayoutClasses();
    window.dispatchEvent(new Event("resize"));
  }

  function toggleRight() {
    rightCollapsed = !rightCollapsed;
    store.set("wb:right_collapsed", rightCollapsed);
    syncLayoutClasses();
    window.dispatchEvent(new Event("resize"));
  }

  function setFocusMode(enable) {
    focusMode = Boolean(enable);
    syncLayoutClasses();
    window.dispatchEvent(new Event("resize"));
  }

  // Handle Esc key to exit focus mode. Owned exclusively by this view: no
  // other cleanup (e.g. the terminal pane's own teardown) may add or remove
  // this listener, and this view removes it itself when navigated away from
  // (via activeViewCleanup, invoked by route()) so it cannot leak or fire
  // against a stale, unmounted shell (L1).
  function onKeyDown(e) {
    if (e.key === "Escape" && focusMode) {
      setFocusMode(false);
    }
  }
  window.addEventListener("keydown", onKeyDown);
  activeViewCleanup = () => {
    window.removeEventListener("keydown", onKeyDown);
  };

  // ---------- Left Column: Agents & Sessions ----------
  function renderLeftColumn() {
    setKids(leftCol);
    const sessionItems = sessions.map((sess) => {
      const isActive = sess.pane_id === activePaneId;
      const roleName = sess.role_label || sess.agent || sess.pane_id;
      return el("div", {
        class: `wb-session-item${isActive ? " active" : ""}`,
        role: "button",
        tabindex: "0",
        "aria-pressed": isActive ? "true" : "false",
        on: {
          click: () => switchPane(sess.pane_id),
          keydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); switchPane(sess.pane_id); } },
        },
      },
        el("div", { class: "wb-session-title" },
          el("span", { style: "font-weight:650" }, roleName),
          statusBadge(sess.status, sess.activity)),
        el("div", { class: "wb-session-sub" },
          toolTag(sess.agent),
          el("span", { class: "mono small" }, sess.pane_id)));
    });

    const activeSession = sessions.find((s) => s.pane_id === activePaneId);
    let agentDetails = null;
    if (activeSession) {
      const roleName = activeSession.role_label || activeSession.agent || activePaneId;
      const skillsUsed = activeSession.skills_used || [];
      agentDetails = el("div", { class: "wb-panel", style: "margin-top: 4px" },
        el("div", { class: "wb-panel-head" },
          el("h3", { class: "wb-panel-title" }, "這個終端的資訊"),
          prov({ origin: "runtime", detail: "執行觀察" })),
        el("dl", { class: "kv small" },
          el("dt", null, "角色名稱"), el("dd", { style: "font-weight:600" }, roleName),
          el("dt", null, "執行工具"), el("dd", null, toolTag(activeSession.agent)),
          el("dt", null, "模型"), el("dd", { class: "mono" }, activeSession.model || "—"),
          el("dt", null, "已用技能"), el("dd", null, skillsUsed.length ? skillsUsed.join("、") : "無")));
    }

    setKids(leftCol,
      el("div", { class: "wb-panel" },
        el("div", { class: "wb-panel-head" },
          el("h2", { class: "wb-panel-title" }, `開啟中的終端 (${sessions.length})`),
          el("button", {
            class: "btn small",
            type: "button",
            title: "收合左欄",
            "aria-label": "收合左側欄",
            on: { click: toggleLeft },
          }, "◀")),
        sessions.length ? el("div", { class: "wb-session-list" }, sessionItems)
                        : emptyState("目前沒有開啟中的終端", null)),
      agentDetails
    );
  }

  // ---------- Center Column: Reusable Terminal Widget ----------
  let termController = null;

  function switchPane(newPaneId) {
    if (newPaneId === activePaneId) return;
    cleanupActiveTerminal();
    activePaneId = newPaneId;
    // Update active task association if matched
    const matched = tasksList.find((t) => t.associated_pane_id === activePaneId);
    if (matched) activeTaskId = matched.id;
    renderLeftColumn();
    renderCenterColumn();
    renderRightColumn();
  }

  function renderCenterColumn() {
    cleanupActiveTerminal();
    setKids(centerCol);

    const focusBanner = el("div", { class: "wb-focus-banner" },
      el("span", null, "⛶ 專注模式開啟中（側欄已收合，按 Esc 退出）"),
      el("button", { class: "btn small primary", type: "button", on: { click: () => setFocusMode(false) } }, "退出專注"));

    if (!activePaneId) {
      setKids(centerCol,
        focusBanner,
        el("div", { class: "wb-panel pad" },
          emptyState("尚未選取終端", "請由左側選一個開啟中的終端，或從角色卡出發開一個新的。")));
      return;
    }

    const currentPane = activePaneId;
    const session = sessions.find((s) => s.pane_id === currentPane);
    const roleName = session ? (session.role_label || session.agent || currentPane) : currentPane;
    const toolName = session ? (TOOL[session.agent] || session.agent) : "終端";
    const project = session ? (D.live.projects || []).find((p) => p.project_id === session.project_id) : null;

    let mode = "observe";
    let connState = "connecting";
    let closedReason = "";
    let sessionGone = false;  // the runtime answered 404: nothing left to reconnect to or close
    let errorMsg = "";
    let retryTimer = null;
    let resizeTimer = null;
    let abortController = null;
    let term = null;
    let fitAddon = null;
    let resizeObserver = null;
    let modalElem = null;
    let isDisposed = false;
    let termReady = false;
    let pendingTakeover = null;
    // See the matching comment in viewTerminal(): the current control
    // session's token, needed so cleanup can send a token-guarded abandon
    // instead of an unconditional release (L2/token safety).
    let controlToken = null;

    const reconnectPolicy = createReconnectPolicy({
      maxRetries: 5,
      baseDelayMs: 1000,
      factor: 1.5,
      maxDelayMs: 8000,
    });

    const modeBadge = el("span");
    const connBadge = el("span");
    const bannerWrap = el("div", { class: "term-warning-box" });
    const actionWrap = el("div", { class: "term-toolbar" });
    const dimInfo = el("span", { class: "term-dim-info" }, "—");
    const termElem = el("div", { class: "term-container", role: "region", "aria-label": `終端 ${currentPane}` });
    const termWrap = el("div", { class: "term-container-wrap" }, termElem);

    const inputBatcher = createInputBatcher(async (text) => {
      if (isDisposed || mode !== "control") return;
      await api.post(`/api/term/${encodeURIComponent(currentPane)}/input`, { text });
    }, {
      onError: (err) => {
        if (isDisposed) return;
        toast("鍵盤輸入傳送失敗，已捨棄未送出內容：" + (err ? err.message : "網路錯誤"));
      },
    });

    function updateUI() {
      if (token !== seq || isDisposed) return;

      if (mode === "control") {
        setKids(modeBadge, badge("操作控制中 (Control)", "b-ok", "目前可由此網頁終端輸入"));
      } else {
        setKids(modeBadge, badge("僅觀看 (Observe)", "b-info", "目前為觀看模式，無法鍵盤輸入"));
      }

      if (connState === "connected") {
        setKids(connBadge, badge("連線正常", "b-ok"));
      } else if (connState === "connecting") {
        setKids(connBadge, badge("連線中…", "b-warn"));
      } else if (connState === "disconnected") {
        setKids(connBadge, badge("連線中斷", "b-bad"));
      } else if (connState === "closed") {
        setKids(connBadge, badge("已結束", "b-mute"));
      } else if (connState === "error") {
        setKids(connBadge, badge("錯誤", "b-bad"));
      }

      const notices = [];
      if (mode === "control") {
        notices.push(notice("warn", "⚠️ 目前處於接管控制模式：你在這裡輸入的內容會直接送給 Agent。其他分頁接管時，這裡會自動改回僅觀看。"));
      }
      if (connState === "closed") {
        notices.push(notice("info", `終端機連線已關閉${closedReason ? "：" + closedReason : ""}${sessionGone
        ? "需要新的終端時，請從角色卡的「出發通行證」開啟。"
        : "如需重新開啟請點選右上方「重新連線」。"}`));
      } else if (connState === "disconnected") {
        const attempts = reconnectPolicy.getRetryCount();
        const waitText = reconnectPolicy.canAutoRetry()
          ? `將於稍後自動重試（第 ${attempts}/5 次）...`
          : "已達最大重試次數，請手動點選「重新連線」。";
        notices.push(notice("bad", `與伺服器終端串流中斷。${waitText}`));
      } else if (connState === "error") {
        notices.push(notice("bad", `連線錯誤：${errorMsg || "無法連接終端串流"}`));
      }
      setKids(bannerWrap, notices);

      const actions = [];
      // Panel toggle buttons when collapsed
      if (leftCollapsed) {
        actions.push(el("button", { class: "btn small", type: "button", on: { click: toggleLeft }, title: "展開左欄" }, "◄ 左欄"));
      }
      if (connState === "connected") {
        if (mode === "observe") {
          actions.push(el("button", { class: "btn small primary", type: "button", on: { click: promptTakeover } }, "接管操作"));
        } else {
          actions.push(el("button", { class: "btn small", type: "button", on: { click: doRelease } }, "釋放控制"));
        }
      }
      if (!sessionGone && shouldShowTerminalRetryAction({ isDisposed, termReady, connState })) {
        actions.push(el("button", { class: "btn small primary", type: "button", on: { click: manualReconnect } }, "重新連線"));
      }
      actions.push(el("button", {
        class: "btn small",
        type: "button",
        on: { click: () => setFocusMode(!focusMode) },
        title: focusMode ? "退出專注模式 (Esc)" : "開啟專注模式 (收合側欄)",
      }, focusMode ? "退出專注" : "⛶ 專注模式"));

      actions.push(el("a", { class: "btn small", href: `#/term/${encodeURIComponent(currentPane)}`, title: "以獨立視窗開啟" }, "獨立視窗"));
      if (!sessionGone) actions.push(closeSessionButton(currentPane));
      if (rightCollapsed) {
        actions.push(el("button", { class: "btn small", type: "button", on: { click: toggleRight }, title: "展開任務與隊伍" }, "任務與隊伍 ►"));
      }
      setKids(actionWrap, actions);

      if (term) {
        dimInfo.textContent = `${term.cols} × ${term.rows}`;
      }
    }

    function promptTakeover() {
      if (modalElem) return;
      const confirmBtn = el("button", { class: "btn primary", type: "button", on: { click: () => onConfirm() } }, "確認接管操作");
      const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
      modalElem = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "wb-modal-takeover-title" },
        el("div", { class: "modal-box" },
          el("h2", { id: "wb-modal-takeover-title" }, "確認接管終端操作"),
          el("p", null, "您即將接管此終端的鍵盤輸入控制。"),
          el("div", { class: "notice warn", style: "margin: 4px 0" },
            el("span", { class: "ico", "aria-hidden": "true" }, "!"),
            el("div", null, "重要提醒：接管後由這個分頁送出鍵盤輸入；同一時間只有一個分頁能控制，其他分頁接管時這裡會自動改回僅觀看。若 Agent 正在執行任務，請避免非預期的干擾。")),
          el("p", { class: "small muted" }, "接管後您隨時可以點選「釋放控制」回到僅觀看狀態。"),
          el("div", { class: "modal-actions" }, cancelBtn, confirmBtn)));
      document.body.append(modalElem);

      // Same ordering fix as the standalone terminal view's promptTakeover:
      // capture the opener via withModalA11y before moving focus into the
      // dialog, so close/Escape restores focus to the opener, not confirmBtn.
      // Registration (done inside withModalA11y) lets terminal/view cleanup
      // close this dialog through its own teardown instead of reaching in
      // and removing modalElem directly.
      const closeModal = withModalA11y(modalElem, () => {
        if (modalElem) {
          modalElem.remove();
          modalElem = null;
        }
      });
      confirmBtn.focus();

      async function onConfirm() {
        confirmBtn.disabled = true;
        let res;
        try {
          pendingTakeover = api.post(`/api/term/${encodeURIComponent(currentPane)}/control`, {
            action: "takeover",
            ...termDimsForRequest(term),
          });
          res = await pendingTakeover;
        } catch (err) {
          if (!isDisposed) {
            toast("接管失敗：" + err.message);
            confirmBtn.disabled = false;
          }
          return;
        } finally {
          pendingTakeover = null;
        }

        await handleTakeoverResponse({
          res,
          isDisposed,
          paneId: currentPane,
          apiPost: (path, body) => api.post(path, body),
          onLiveSuccess: (r) => {
            mode = "control";
            controlToken = r.token;
            inputBatcher.setEnabled(true);
            toast("已接管終端操作（其他分頁會改回僅觀看）");
            closeModal();
            updateUI();
            if (term) term.focus();
          },
          onLiveError: (r) => {
            toast("接管失敗：" + (r?.error || "未知錯誤"));
            confirmBtn.disabled = false;
          },
        });
      }
    }

    async function doRelease() {
      await handleReleaseAction({
        isDisposed,
        mode,
        connState,
        inputBatcher,
        apiPost: (body) => api.post(`/api/term/${encodeURIComponent(currentPane)}/control`, body),
        onObserve: () => {
          mode = "observe";
          controlToken = null;
          toast("已釋放操作控制，切換為僅觀看模式");
          updateUI();
        },
        onError: (err) => {
          toast("釋放控制失敗，維持操作模式：" + (err ? err.message : "網路錯誤"));
          updateUI();
        },
      });
    }

    function onStreamDrop(reason) {
      if (isDisposed || connState === "closed") return;
      connState = "disconnected";
      if (mode === "control") {
        mode = "observe";
        controlToken = null;
        inputBatcher.setEnabled(false);
      }
      inputBatcher.clear();
      updateUI();

      const dropInfo = reconnectPolicy.recordDrop();
      if (dropInfo.shouldRetry) {
        clearTimeout(retryTimer);
        retryTimer = setTimeout(() => {
          if (!isDisposed && connState === "disconnected") {
            startStream();
          }
        }, dropInfo.delayMs);
      } else {
        updateUI();
      }
    }

    function manualReconnect() {
      if (!canStartTerminalStream({ isDisposed, termReady })) return;
      clearTimeout(retryTimer);
      reconnectPolicy.resetManual();
      startStream();
    }

    async function startStream() {
      if (!canStartTerminalStream({ isDisposed, termReady })) return;
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
      connState = "connecting";
      updateUI();

      abortController = new AbortController();
      const signal = abortController.signal;
      const { cols, rows } = termDimsForRequest(term);
      const url = `/api/term/${encodeURIComponent(currentPane)}/stream?cols=${cols}&rows=${rows}`;

      try {
        const res = await fetch(url, {
          method: "GET",
          headers: {
            Accept: "text/event-stream",
            "X-VBear": "1",
          },
          signal,
        });

        if (!res.ok) {
          if (res.status === 404) {
            connState = "closed";
            sessionGone = true;
            closedReason = "此終端已不存在（已關閉或從未存在）。";
          } else if (res.status === 429) {
            connState = "error";
            errorMsg = "終端連線已達上限（最多 4 個），請關閉其他終端分頁 (429)";
          } else if (res.status === 403) {
            connState = "error";
            errorMsg = "權限不足 (403)";
          } else {
            connState = "error";
            errorMsg = `連線失敗 (HTTP ${res.status})`;
          }
          updateUI();
          return;
        }

        connState = "connected";
        reconnectPolicy.recordConnectionSuccess();
        updateUI();

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8", { stream: true });
        const parser = createSSEParser(
          (event) => {
            if (isDisposed) return;
            const msg = event.data;
            if (!msg) return;
            if (msg.type === "terminal.frame") {
              handleTerminalFrame(msg, { term, reconnectPolicy });
            } else if (msg.type === "terminal.closed") {
              connState = "closed";
              closedReason = msg.reason || "終端機已結束";
              if (mode === "control") {
                mode = "observe";
                controlToken = null;
                inputBatcher.setEnabled(false);
              }
              inputBatcher.clear();
              updateUI();
            }
          },
          (err) => {
            console.warn("SSE parse error:", err);
          }
        );

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value) {
            parser.feed(decoder.decode(value, { stream: true }));
          }
        }
        const rem = decoder.decode();
        if (rem) parser.feed(rem);
        parser.flush();

        if (connState !== "closed" && !signal.aborted && !isDisposed) {
          onStreamDrop("伺服器連線已中斷 (EOF)");
        }
      } catch (err) {
        if (signal.aborted || isDisposed) return;
        onStreamDrop(err.message);
      }
    }

    function handleResize() {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(async () => {
        if (isDisposed || !term || !fitAddon || !termElem.parentElement) return;
        const dims = fitAddon.proposeDimensions();
        if (!usableTermDims(dims)) return;
        if (dims.cols === term.cols && dims.rows === term.rows) return;
        fitAddon.fit();
        dimInfo.textContent = `${term.cols} × ${term.rows}`;
        if (mode === "control" && connState === "connected") {
          try {
            await api.post(`/api/term/${encodeURIComponent(currentPane)}/control`, {
              action: "resize",
              cols: term.cols,
              rows: term.rows,
            });
          } catch (e) {
            console.warn("Resize POST failed:", e);
          }
        }
      }, 150);
    }

    setKids(centerCol,
      focusBanner,
      el("div", { class: "wb-panel" },
        el("div", { class: "term-head" },
          el("div", { class: "term-meta" },
            el("div", { class: "row" },
              el("h1", { style: "font-size: 20px" }, roleName),
              toolTag(session ? session.agent : "terminal"),
              modeBadge,
              connBadge),
            el("p", { class: "small muted mono", style: "margin:0" },
              `Pane ID: ${currentPane}`,
              project ? ` · 專案: ${project.name}` : "",
              " · 尺寸: ", dimInfo)),
          actionWrap),
        bannerWrap,
        termWrap,
        el("div", { class: "legend section", style: "margin-top:8px" },
          el("span", null, el("b", null, "觀看模式"), "：預設唯讀轉送畫面，不攔截鍵盤，亦不對 Agent 送出輸入"),
          el("span", null, el("b", null, "接管操作"), "：經確認後可由瀏覽器打字；同一時間只有一個分頁能控制"),
          el("span", { class: "term-history-notice" }, TERMINAL_VISIBLE_SCREEN_NOTICE)))
    );

    activeTerminalCleanup = () => {
      isDisposed = true;
      termReady = false;
      // Abandon (not release!) our control session on the server before
      // tearing down the stream, so a pane switch or navigation while
      // controlling cannot leave the pane orphaned in control mode for
      // anyone else who opens it (L2). Token-guarded (M3/H3): unlike
      // release() (no token, always acts on whatever session is *currently*
      // installed), abandon(token) only stops the session if it still
      // matches the one this view took over — a no-op otherwise, so a newer
      // takeover that raced in (another tab, or a fresh takeover on this
      // same pane) is never silently stolen back to observe. Best effort
      // either way: if this fails, the server-side stream disconnect
      // (close_if_current) still releases whatever session this stream's
      // SSE connection was actually watching.
      if (mode === "control") {
        mode = "observe";
        const tokenToAbandon = controlToken;
        controlToken = null;
        api.post(`/api/term/${encodeURIComponent(currentPane)}/control`,
          { action: "abandon", token: tokenToAbandon }).catch(() => {});
      }
      reconnectPolicy.resetManual();
      clearTimeout(retryTimer);
      clearTimeout(resizeTimer);
      inputBatcher.setEnabled(false);
      inputBatcher.clear();
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
      if (resizeObserver) {
        resizeObserver.disconnect();
        resizeObserver = null;
      }
      // Any open takeover modal is already closed by this point: cleanupActiveTerminal()
      // calls closeOpenModals() before invoking this callback, which runs the
      // modal's own registered teardown (removes it, restores background
      // inert/aria-hidden) rather than this code reaching in directly.
      if (term) {
        try { term.dispose(); } catch (_) {}
        term = null;
      }
      window.removeEventListener("resize", handleResize);
    };

    const TerminalClass = (typeof window !== "undefined" && window.Terminal) || (typeof Terminal !== "undefined" && Terminal) || null;
    const FitAddonClass = (typeof window !== "undefined" && (window.FitAddon?.FitAddon || window.FitAddon)) || (typeof FitAddon !== "undefined" && (FitAddon.FitAddon || FitAddon)) || null;

    const termInit = initTerminalInstance({
      TerminalClass,
      FitAddonClass,
      termElem,
    });

    if (!termInit.ok) {
      termReady = false;
      connState = "error";
      errorMsg = termInit.error;
      setKids(termElem,
        el("div", { class: "notice bad", role: "alert", style: "margin: 16px" },
          el("span", { class: "ico", "aria-hidden": "true" }, "✕"),
          el("div", null,
            el("b", null, "終端機載入失敗"),
            el("p", { class: "small", style: "margin: 4px 0 0" }, termInit.error))));
      updateUI();
      return;
    }

    term = termInit.term;
    fitAddon = termInit.fitAddon;
    termReady = true;
    dimInfo.textContent = `${term.cols} × ${term.rows}`;

    term.onData((data) => {
      if (mode === "control" && connState === "connected") {
        inputBatcher.push(data);
      }
    });

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(termWrap);
    }
    window.addEventListener("resize", handleResize);

    updateUI();
    startStream();
  }

  // ---------- Right Column: Tasks & Governance (G/P/A/T) ----------
  // [key, label] for the G/P/A/T tabs, in display order. Driving both the
  // tablist and the ARIA wiring (ids, aria-controls/-labelledby, roving
  // tabindex, arrow-key navigation) from one list keeps the WAI-ARIA tabs
  // pattern (L4) from drifting out of sync across the two.
  const RIGHT_TABS = [
    ["task", "[T] 任務卡"],
    ["agent", "角色"],
    ["project", "[P] 專案契約"],
    ["global", "[G] 全域底線"],
  ];

  function renderRightColumn() {
    setKids(rightCol);

    function selectTab(key, focusButton) {
      activeTab = key;
      renderRightColumn();
      if (focusButton) {
        const btn = document.getElementById(`wb-tab-${key}`);
        if (btn) btn.focus();
      }
    }

    const tabButtons = RIGHT_TABS.map(([key, label], i) => el("button", {
      id: `wb-tab-${key}`,
      class: `wb-tab-btn${activeTab === key ? " active" : ""}`,
      type: "button",
      role: "tab",
      "aria-selected": activeTab === key ? "true" : "false",
      "aria-controls": `wb-tabpanel-${key}`,
      tabindex: activeTab === key ? "0" : "-1",
      on: {
        click: () => selectTab(key, false),
        keydown: (e) => {
          if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
          e.preventDefault();
          let idx = i;
          if (e.key === "ArrowRight") idx = (i + 1) % RIGHT_TABS.length;
          else if (e.key === "ArrowLeft") idx = (i - 1 + RIGHT_TABS.length) % RIGHT_TABS.length;
          else if (e.key === "Home") idx = 0;
          else if (e.key === "End") idx = RIGHT_TABS.length - 1;
          selectTab(RIGHT_TABS[idx][0], true);
        },
      },
    }, label));

    const tabsHeader = el("div", { class: "wb-tabs", role: "tablist", "aria-label": "背景資料與任務分頁" }, tabButtons);

    let tabBody;
    if (activeTab === "task") {
      tabBody = renderTaskTabContent();
    } else if (activeTab === "agent") {
      tabBody = renderAgentTabContent();
    } else if (activeTab === "project") {
      tabBody = renderProjectTabContent();
    } else {
      tabBody = renderGlobalTabContent();
    }
    tabBody.id = `wb-tabpanel-${activeTab}`;
    tabBody.setAttribute("role", "tabpanel");
    tabBody.setAttribute("aria-labelledby", `wb-tab-${activeTab}`);
    tabBody.setAttribute("tabindex", "0");

    setKids(rightCol,
      el("div", { class: "wb-panel" },
        el("div", { class: "wb-panel-head" },
          el("h2", { class: "wb-panel-title" }, "背景資料與任務"),
          el("button", {
            class: "btn small",
            type: "button",
            title: "收合任務與隊伍",
            "aria-label": "收合右側欄",
            on: { click: toggleRight },
          }, "▶")),
        tabsHeader,
        tabBody)
    );
  }

  // Right Tab: [T] Task Card
  function renderTaskTabContent() {
    const taskContent = el("div", { class: "wb-tab-content" });

    // Task selector & create button
    const taskOptions = tasksList.map((t) => el("option", { value: t.id, selected: t.id === activeTaskId }, t.title));
    const selectElem = el("select", {
      style: "flex:1",
      on: {
        change: (e) => {
          activeTaskId = e.target.value;
          renderRightColumn();
        },
      },
    },
      tasksList.length ? taskOptions : el("option", { value: "" }, "（無任務卡）")
    );

    const selectorRow = el("div", { class: "row", style: "margin-bottom: 4px" },
      selectElem,
      el("button", { class: "btn small primary", type: "button", on: { click: promptCreateTask } }, "＋ 任務卡"));

    const activeTask = tasksList.find((t) => t.id === activeTaskId);
    if (!activeTask) {
      setKids(taskContent,
        selectorRow,
        emptyState("尚未選取或建立任務卡", "點選上方「＋ 任務卡」，挑一個你電腦上現有的專案資料夾。")
      );
      return taskContent;
    }

    const taskProv = activeTask.provenance || {};
    const { agent, tests, human, verificationAsserted, derivedStatus } = computeTaskProvenance(taskProv, activeTask.status, activeTask.closure);

    const folderBlock = taskFolderBlock(activeTask, { onChanged: (updated) => { Object.assign(activeTask, updated); renderRightColumn(); } });

    // Tracking association status. With no terminal chosen there is nothing to link to, and nothing is said to be linked.
    const link = taskTerminalLink(activeTask, activePaneId);
    const isAssociatedWithCurrent = link.state === "linked";
    const trackingBox = el("div", { class: "notice info", style: "font-size:12.5px; padding: 8px 10px;", "data-wb": "tracking" },
      el("div", null,
        el("div", { style: "font-weight:700; margin-bottom:2px", "data-wb": "tracking-state" }, link.text),
        el("div", { class: "small muted" }, TRACKING_NOTE),
        el("div", { class: "small muted", style: "color:var(--warn); margin-top:2px" }, TRACKING_RESTART_NOTE)),
      link.state === "none" ? null : el("button", {
        class: `btn small ${isAssociatedWithCurrent ? "" : "primary"}`,
        type: "button",
        style: "margin-left:auto; flex-shrink:0;",
        on: {
          click: async () => {
            const nextPane = isAssociatedWithCurrent ? null : activePaneId;
            try {
              const res = await api.post(`/api/tasks/${encodeURIComponent(activeTask.id)}`, {
                associated_pane_id: nextPane,
              });
              // Trust what the server actually stored, not what was asked
              // for (M1): a failed or partial update must not leave the UI
              // showing an association the backend didn't record.
              Object.assign(activeTask, res.task);
              toast(isAssociatedWithCurrent ? "已解除終端的追蹤關聯" : "已將任務卡與目前的終端關聯（僅追蹤）");
              renderRightColumn();
            } catch (err) {
              toast("關聯更新失敗：" + err.message);
            }
          },
        },
      }, isAssociatedWithCurrent ? "解除關聯" : "關聯目前的終端"));

    // Status Provenance Box
    const provBox = el("div", { class: "wb-provenance-box" },
      el("div", { class: "wb-provenance-head" },
        el("span", null, "狀態依據（誰說了算）"),
        taskStatusBadge(derivedStatus)),
      el("div", { class: "wb-provenance-row" },
        el("span", null, "1. 自我回報狀態 (Self-Reported)：",
          taskProv.agent_set_at ? el("span", { class: "small muted" }, ` · 最後更新 ${fmtTime(taskProv.agent_set_at)}`) : null),
        el("select", {
          on: {
            change: async (e) => {
              const newAgent = e.target.value;
              if (CLOSURE_REASONS[newAgent]) {
                // Completing or blocking says what follows (tasks.py closure
                // obligation). Cancelling the dialog re-renders, which puts
                // the select back on the stored value.
                promptClosure(activeTask, newAgent);
                return;
              }
              try {
                const updated = await api.post(`/api/tasks/${encodeURIComponent(activeTask.id)}`, {
                  provenance: { ...taskProv, agent: newAgent },
                });
                Object.assign(activeTask, updated.task);
                renderRightColumn();
              } catch (err) { toast("更新失敗：" + err.message); }
            },
          },
        },
          [["pending", "待執行 (pending)"], ["in_progress", "執行中 (in_progress)"], ["completed", "已回報完成 (completed)"], ["blocked", "阻塞 (blocked)"]]
            .map(([v, l]) => el("option", { value: v, selected: agent === v }, l)))),
      el("div", { class: "wb-provenance-row" },
        el("span", null, "2. 自動化測試驗證：",
          taskProv.tests_set_at ? el("span", { class: "small muted" }, ` · 最後更新 ${fmtTime(taskProv.tests_set_at)}`) : null),
        el("select", {
          on: {
            change: async (e) => {
              const newTests = e.target.value;
              try {
                const updated = await api.post(`/api/tasks/${encodeURIComponent(activeTask.id)}`, {
                  provenance: { ...taskProv, tests: newTests },
                });
                Object.assign(activeTask, updated.task);
                renderRightColumn();
              } catch (err) { toast("更新失敗：" + err.message); }
            },
          },
        },
          [["untested", "未測試 (untested)"], ["passed", "通過 (passed)"], ["failed", "失敗 (failed)"]]
            .map(([v, l]) => el("option", { value: v, selected: tests === v }, l)))),
      el("div", { class: "wb-provenance-row" },
        el("span", null, "3. 介面操作者核准 (未經身份驗證)：",
          taskProv.human_set_at ? el("span", { class: "small muted" }, ` · 最後更新 ${fmtTime(taskProv.human_set_at)}`) : null),
        el("select", {
          on: {
            change: async (e) => {
              const newHuman = e.target.value;
              try {
                const updated = await api.post(`/api/tasks/${encodeURIComponent(activeTask.id)}`, {
                  provenance: { ...taskProv, human: newHuman },
                });
                Object.assign(activeTask, updated.task);
                renderRightColumn();
              } catch (err) { toast("更新失敗：" + err.message); }
            },
          },
        },
          [["pending", "審查中 (pending)"], ["approved", "核准 (approved)"], ["rejected", "退回 (rejected)"]]
            .map(([v, l]) => el("option", { value: v, selected: human === v }, l)))),
      closureRow(activeTask),
      el("div", { class: "wb-provenance-row" },
        el("span", null, "4. 結果對應的版本：", bindingBadge(activeTask.verification_binding)),
        el("span", { class: "small muted" }, (activeTask.verification_binding && activeTask.verification_binding.detail) || "")),
      el("div", { class: "small muted", style: "border-top: 1px dashed var(--line); padding-top:6px" },
        verificationAsserted
          ? el("span", { style: "color:var(--ok); font-weight:700" }, "✓ 測試與介面核准兩欄皆已自我回報為通過（聲稱驗證通過，非經授權之正式驗證）")
          : el("span", { style: "color:var(--warn)" }, "⚠️ 依治理規定：本主控台無身份驗證，任何情況下皆不可標記為正式 Verified，僅能在測試與核准皆通過後顯示「聲稱驗證通過」")),
      el("div", { class: "small muted", style: "padding-top:2px" },
        "ℹ️ 誠實揭露：本主控台無使用者身份驗證，以上三欄僅為透過此網頁/API 自行填寫之回報值（自我回報），並非經密碼學或帳號驗證之真實人類審查記錄。")
    );

    // 6 Core Fields
    function renderField(label, listOrStr) {
      if (!listOrStr || (Array.isArray(listOrStr) && listOrStr.length === 0)) {
        return null;
      }
      const content = Array.isArray(listOrStr)
        ? el("ul", { style: "margin:0; padding-left:18px" }, listOrStr.map((item) => el("li", null, item)))
        : el("div", null, listOrStr);
      return el("div", { class: "wb-field-group" },
        el("div", { class: "wb-field-label" }, label),
        el("div", { class: "wb-field-val" }, content));
    }

    // Steps list
    const stepsItems = (activeTask.steps || []).map((step, idx) => {
      const isDone = Boolean(step.done);
      return el("div", { class: `wb-step-item${isDone ? " done" : ""}` },
        el("input", {
          type: "checkbox",
          checked: isDone,
          on: {
            change: async (e) => {
              const newSteps = [...activeTask.steps];
              newSteps[idx] = { ...step, done: e.target.checked };
              try {
                const res = await api.post(`/api/tasks/${encodeURIComponent(activeTask.id)}`, {
                  steps: newSteps,
                });
                activeTask.steps = res.task.steps;
                renderRightColumn();
              } catch (err) {
                toast("更新步驟失敗：" + err.message);
              }
            },
          },
        }),
        el("span", null, step.title || step.text || `步驟 ${idx + 1}`));
    });

    const stepsSection = stepsItems.length
      ? el("div", { class: "wb-field-group" },
          el("div", { class: "wb-field-label" }, `進度步驟 (${stepsItems.filter((_, i) => activeTask.steps[i]?.done).length}/${stepsItems.length})`),
          el("div", { class: "wb-field-val" }, stepsItems))
      : null;

    // Artifacts list
    const artifactsItems = (activeTask.artifacts || []).map((art) => el("li", null, el("span", { class: "mono small" }, art)));
    const artifactsSection = artifactsItems.length
      ? el("div", { class: "wb-field-group" },
          el("div", { class: "wb-field-label" }, "產出成品 (Artifacts)"),
          el("div", { class: "wb-field-val" }, el("ul", { style: "margin:0; padding-left:18px" }, artifactsItems)))
      : null;

    const actionRow = el("div", { class: "row", style: "margin-top:8px" },
      el("button", { class: "btn small", type: "button", on: { click: () => promptEditTask(activeTask) } }, "編輯任務"),
      el("button", {
        class: "btn small", type: "button", disabled: agent === "completed",
        title: agent === "completed" ? "已結案的任務卡不能再交接" : "結束這張卡並建立接手的新卡（同一次寫入）",
        on: { click: () => promptHandoff(activeTask) },
      }, "交接給…"),
      el("button", { class: "btn small", type: "button", on: { click: () => promptDeleteTask(activeTask) } }, "刪除任務"));

    setKids(taskContent,
      selectorRow,
      el("div", { class: "wb-task-head" },
        el("h3", { class: "wb-task-title" }, activeTask.title),
        el("div", { class: "row small muted" },
          badge(activeTask.template, "b-info", "任務範本"),
          taskStatusBadge(derivedStatus),
          pickupBadge(activeTask.pickup),
          activeTask.owner ? el("span", { class: "tag", title: "交接時指定的接手對象" }, `接手：${activeTask.owner}`) : null,
          prov({ origin: "user", detail: "本機任務卡 · 僅追蹤" })),
        taskStatusExplain(derivedStatus, activeTask.pickup).map((t) => el("p", { class: "small muted", "data-wb": "status-explain" }, t))),
      folderBlock,
      teamSection(activeTask, { profiles: agentProfiles, catalog: agentBuilderCatalog, gone: () => token !== seq }),
      chainRow(activeTask),
      trackingBox,
      provBox,
      renderField("目標 (Goal)", activeTask.goal),
      renderField("範圍 (Scope)", activeTask.scope),
      renderField("範圍外 (Out of Scope)", activeTask.out_of_scope),
      renderField("交付物 (Deliverables)", activeTask.deliverables),
      renderField("驗收條件 (Acceptance Criteria)", activeTask.acceptance_criteria),
      renderField("實測證據 (Evidence)", activeTask.evidence),
      stepsSection,
      artifactsSection,
      actionRow
    );

    return taskContent;
  }

  // Right Tab: [A] Agent Profile (Phase C — full Agent Builder).
  // Strictly distinct from AgentRole (read-only catalog the scanner picked
  // up from `~/.codex/agents`, `~/.claude/agents`, plugin caches, etc).
  // Equipped Skill Loadout here is never Loaded: saving a profile never
  // starts, restarts, or injects anything into a running session. The
  // permission_intents values are intent-only — they are not enforced.
  let selectedProfileId = initialProfileId || null;

  async function reloadAgentProfiles() {
    try {
      const res = await api.get("/api/agent-profiles");
      agentProfiles = (res && res.profiles) || [];
    } catch (err) {
      toast("載入角色卡失敗：" + err.message);
      agentProfiles = [];
    }
    // If the previously selected one is gone (deleted from elsewhere),
    // drop the selection rather than rendering a phantom.
    if (selectedProfileId && !agentProfiles.find((p) => p.id === selectedProfileId)) {
      selectedProfileId = null;
    }
  }

  async function ensureCatalog() {
    if (agentBuilderCatalog) return agentBuilderCatalog;
    try {
      const res = await api.get("/api/agent-builder/catalog");
      agentBuilderCatalog = res && res.ok ? res : null;
    } catch {
      agentBuilderCatalog = null;
    }
    return agentBuilderCatalog;
  }

  function profileSummary(p) {
    const tools = (agentBuilderCatalog && agentBuilderCatalog.tools) || [];
    const profs = (agentBuilderCatalog && agentBuilderCatalog.professions) || [];
    const profession = p.profession_role_id
      ? (profs.find((r) => r.role_id === p.profession_role_id) || {}).name
        || p.profession_role_id
      : "（未選職業標籤）";
    const tool = p.model && p.model.tool;
    const toolLabel = (tool === "claude" && "Claude Code")
                    || (tool === "codex" && "Codex CLI")
                    || (tool === "shared" && "skills CLI")
                    || tool || "？";
    return { profession, toolLabel };
  }

  function renderAgentProfileListItem(p) {
    const { profession, toolLabel } = profileSummary(p);
    const unresolved = (p._unresolved && p._unresolved.skills) || [];
    const item = el("button", {
      class: "wb-list-item",
      type: "button",
      "aria-pressed": String(p.id === selectedProfileId),
      style: "text-align:left; padding:8px; margin-bottom:4px;",
      on: { click: () => {
        selectedProfileId = p.id;
        renderRightColumn();
      } },
    },
      el("div", { class: "row", style: "justify-content:space-between" },
        el("strong", null, p.name || p.id),
        p.enabled ? badge("啟用", "b-ok plain", "這張角色卡仍可使用")
                  : badge("停用", "b-mute plain", "已停用，但保留存檔")),
      el("div", { class: "small muted" },
        `${profession} · ${toolLabel}`),
      el("div", { class: "small muted mono" }, p.id),
      unresolved.length ? el("div", { class: "small", style: "color:#b85" },
        `目前索引找不到 ${unresolved.length} 張技能卡`) : null
    );
    return item;
  }

  function renderAgentProfileDetail(p) {
    // Why this role cannot be launched, right under the button that opens the check (it comes with the card's
    // data, so it fills when that arrives)
    const launchLine = el("div", { class: "rc-launch-line", "data-rc": "launch-line", "aria-live": "polite" });
    return append(el("div", { class: "wb-tab-content" }),
      el("div", { class: "row wb-profile-head", style: "justify-content:space-between" },
        el("h3", { style: "margin:0" }, p.name || p.id),
        el("div", { class: "wb-profile-actions" },
          el("button", { class: "btn small primary", type: "button",
            title: "先看這次啟動實際會套用什麼，確認後才啟動",
            on: { click: () => promptAgentLaunch(p) } }, "出發通行證"),
          el("button", { class: "btn small", type: "button",
            on: { click: () => promptAgentProfileEditor(p) } }, "編輯"),
          el("button", { class: "btn small", type: "button",
            on: { click: () => duplicateCard(p, async (copy) => {
              await reloadAgentProfiles();
              selectedProfileId = copy.id;
              renderRightColumn();
            }) } }, "複製"),
          el("button", { class: "btn small", type: "button",
            on: { click: () => promptDeleteAgentProfile(p) } }, "刪除"),
          el("button", { class: "btn small", type: "button",
            on: { click: async () => {
              try {
                const next = { ...p, enabled: !p.enabled };
                await api.post(`/api/agent-profiles/${encodeURIComponent(p.id)}`,
                  { enabled: next.enabled });
                p.enabled = next.enabled;
                toast(next.enabled ? "已啟用" : "已停用");
                renderRightColumn();
              } catch (err) {
                toast("更新失敗：" + err.message);
              }
            } } }, p.enabled ? "停用" : "啟用"))),
      launchLine,
      renderRoleCard(p, (d) => setKids(launchLine, ...launchLineParts(d))));
  }

  // 「目前無法從 VBear 啟動這個角色」 and the reasons, as the loadout carries them.
  function launchLineParts(d) {
    const note = d && d.armor && typeof d.armor.launch_note === "string" ? d.armor.launch_note : "";
    const reasons = ((d && d.blockers) || []).map((b) => (b && b.message ? String(b.message) : "")).filter(Boolean);
    if (!note && !reasons.length) return [];
    const kids = [];
    if (note) kids.push(el("strong", null, note));
    else kids.push(el("strong", null, "目前無法出發的原因："));
    if (reasons.length) kids.push(el("ul", { class: "small" }, reasons.map((r) => el("li", null, r))));
    return [notice("warn", kids)];
  }

  // ---- Role card (design game-ui 4.1) ----------------------------------------------------------------------
  // Everything below comes from GET /api/agent-profiles/<id>/loadout, which answers from what is already
  // loaded. Every string from the scan, from the profile or from an agent is set with textContent (el + text
  // children); a value that was not provided reads 未提供 / 未知 / 未載入, never a guess.
  const ARMOR_NAME_ZH = { Read: "讀取", Write: "寫入", Test: "測試", Commit: "commit", Deploy: "部署",
    Network: "網路", Filesystem: "檔案系統" };
  const ARMOR_GROUP_HELP = {
    blocked: "這幾項已實測確實擋住（限已測的路徑、版本與執行層）。",
    partial: "只擋住一部分；沒擋住的部分寫在每一項的說明裡。",
    not_granted: "VBear 沒有給這項專用權限，不代表已阻止透過其他工具做到。",
    not_blocked: "這幾項沒有被擋住：只是意圖，或沒有限制。",
    unproven: "尚未驗證或不知道，不能當成有保護。",
  };

  function rcText(v) {
    if (v === null || v === undefined || v === "") return null;
    if (Array.isArray(v)) return v.map((x) => String(x)).join("、") || null;
    return String(v);
  }

  // A value with where it came from; absent reads 未提供.
  function rcSourced(src) {
    const text = src ? rcText(src.value) : null;
    return el("span", null, text === null ? null : text + " ", prov(src));
  }

  function rcObservation(o) { return skillObservationText(o); }

  let rcProfile = null;
  let rcChanged = async () => {};

  // The badge follows the loadout's will_load of this skill, never the words around it (design card-play R1).
  function rcSkillBadge(sk) {
    return cardSlotState(sk) === "active"
      ? badge(CARD_SLOT_LABEL.active, "b-ok", "這個版本的 loadout 明確回報會載入這張技能卡")
      : badge("本次不生效", "b-mute", "VBear 啟動角色時不會載入這張技能卡");
  }

  function rcSkillCard(sk) {
    const head = el("div", { class: "rc-skill-head" },
      el("strong", null, sk.name ? String(sk.name) : `未提供（ID：${sk.skill_id}）`),
      rcSkillBadge(sk));
    if (sk.state === "not_in_index") {
      return el("li", { class: "rc-skill rc-warn" },
        el("div", { class: "rc-skill-head" }, el("strong", { class: "mono" }, sk.skill_id),
          rcSkillBadge(sk)),
        el("p", null, `${sk.note || "目前索引找不到此技能"}（索引時間：${fmtTime(sk.indexed_at)}）`));
    }
    if (sk.state === "index_not_loaded") {
      return el("li", { class: "rc-skill rc-warn" },
        el("div", { class: "rc-skill-head" }, el("strong", { class: "mono" }, sk.skill_id),
          rcSkillBadge(sk)),
        el("p", null, "索引未載入，無法顯示這張技能卡的內容。"));
    }
    const refs = sk.referenced_files || {};
    const cats = (sk.categories || []).map((c) => c && c.label).filter(Boolean);
    return el("li", { class: "rc-skill" }, head,
      el("dl", { class: "rc-dl" },
        el("dt", null, "效果（技能作者的說明，只適用於你自己啟動並載入這張技能的工具）"),
        el("dd", null, rcSourced(sk.description)),
        el("dt", null, "時機"), el("dd", null, rcSourced(sk.when_to_use)),
        el("dt", null, "類別"), el("dd", null, cats.length ? cats.join("、") : el("span", { class: "muted" }, "未提供")),
        el("dt", null, "工具"), el("dd", null, rcText(sk.tool) || "未提供"),
        el("dt", null, "引用檔案"),
        el("dd", null, `共 ${refs.count ?? "未提供"} 個（存在 ${refs.present ?? "未提供"}、缺少 ${refs.missing ?? "未提供"}）；VBear 不會執行這些檔案`),
        el("dt", null, "觀察狀態"), el("dd", null, rcObservation(sk.observed))),
      (sk.warnings || []).length ? el("p", { class: "rc-note" }, "結構檢查：" + sk.warnings.join("；")) : null,
      el("button", { class: "btn small rc-open", type: "button",
        on: { click: () => openSkillCard(sk.skill_id, { profile: rcProfile, onChanged: rcChanged }) } },
        "技能卡特性"));
  }

  function rcArmorGroup(group, items) {
    const mine = items.filter((it) => it.group === group.id);
    return el("section", { class: "rc-armor-group", "data-armor-group": group.id },
      el("h5", null, group.levels && group.levels.length ? `${group.label} · ${group.levels.join("、")}` : group.label),
      el("p", { class: "rc-armor-sum" }, ARMOR_GROUP_HELP[group.id] || ""),
      mine.length ? mine.map((it) => el("div", { class: "rc-armor-item" },
        el("div", { class: "rc-armor-name" },
          el("strong", null, it.name), ` ${ARMOR_NAME_ZH[it.name] ? "（" + ARMOR_NAME_ZH[it.name] + "）" : ""}`),
        el("div", { class: "rc-armor-level" }, armorShield(it.level), it.level),
        el("p", null, it.note),
        (it.path_scope !== "不適用" || it.evidence_refs !== "不適用")
          ? el("p", { class: "rc-note" }, `範圍：${it.path_scope}；證據：${it.evidence_refs}`) : null,
        it.unknown_reason ? el("p", { class: "rc-note" }, `未知或未測：${it.unknown_reason}`) : null))
        : el("p", { class: "rc-note" }, "（目前沒有項目）"));
  }

  // The sentence comes from the server, which knows which tool's data it is (a Codex card never carries a
  // Claude version).
  function rcVersionLine(v) {
    return v && typeof v.text === "string" && v.text ? v.text : "未知";
  }

  function roleCardParts(p, d) {
    const { toolLabel } = profileSummary(p);
    const pr = d.profession || {};
    const prName = pr.state === "found" ? (pr.name || pr.role_id)
      : pr.state === "none" ? "（未選職業標籤）"
      : pr.state === "not_in_index" ? `${pr.role_id}（目前索引找不到這個職業）`
      : `${pr.role_id || ""}（索引未載入）`;
    const idx = d.index || {};
    const info = el("section", { class: "rc-block", "data-rc": "info" },
      el("div", { class: "rc-sub" }, "角色卡・", el("span", { class: "mono" }, p.id)),
      el("dl", { class: "rc-dl" },
        el("dt", null, "職業標籤"), el("dd", null, prName),
        el("dt", null, "陣營"), el("dd", null, toolLabel),
        el("dt", null, "模型 (Model ID)"),
        el("dd", { class: "mono" }, rcText((d.profile || {}).model_id) || "（未指定，視為該工具預設值；非執行環境）"),
        el("dt", null, "版本驗證狀態"), el("dd", null, rcVersionLine(d.version_status)),
        el("dt", null, "狀態"), el("dd", null, p.enabled ? "啟用" : "停用"),
        el("dt", null, "索引時間"), el("dd", null, idx.loaded ? fmtTime(idx.generated_at) : "索引未載入"),
        el("dt", null, "更新時間"), el("dd", null, fmtTime(p.updated_at || p.created_at))));

    let features;
    if (pr.state === "found") {
      features = el("section", { class: "rc-block", "data-rc": "profession" },
        el("h4", null, "職業特性"),
        el("dl", { class: "rc-dl" },
          el("dt", null, "說明"), el("dd", null, rcSourced(pr.description)),
          el("dt", null, "擅長"), el("dd", null, rcSourced(pr.capabilities)),
          el("dt", null, "適合的工作"), el("dd", null, rcSourced(pr.suitable_tasks))),
        el("p", { class: "rc-note" }, pr.label_only || "職業只是標籤，不會把角色指示載入工具"));
    } else {
      features = el("section", { class: "rc-block", "data-rc": "profession" },
        el("h4", null, "職業特性"),
        el("p", { class: "rc-note" }, pr.state === "none" ? "未選職業標籤。"
          : pr.state === "not_in_index" ? "目前索引找不到這個職業，無法顯示特性。"
          : "索引未載入，無法顯示職業特性。"),
        el("p", { class: "rc-note" }, pr.label_only || "職業只是標籤，不會把角色指示載入工具"));
    }

    const sk = d.skills || {};
    const skills = el("section", { class: "rc-block", "data-rc": "skills" },
      el("h4", null, sk.title || "技能卡（收藏中：VBear 啟動時不載入）"),
      el("p", { class: "rc-note" }, sk.note || ""),
      sk.safe_mode ? el("p", { class: "rc-note" }, sk.safe_mode) : null,
      (sk.items || []).length ? el("ul", { class: "rc-skills" }, sk.items.map(rcSkillCard))
        : el("p", { class: "rc-note" }, "未選任何技能。"));

    const ar = d.armor || {};
    let armor;
    if (!ar.applicable) {
      armor = el("section", { class: "rc-block", "data-rc": "armor" },
        el("h4", null, "防具"), notice("warn", ar.why || "這個角色沒有防具資料。"));
    } else {
      armor = el("section", { class: "rc-block", "data-rc": "armor" },
        el("h4", null, (ar.title || "防具") + " ", el("strong", { class: "rc-decides" }, ar.preview_decides || "實際以出發通行證為準")),
        el("p", { class: "rc-note" }, ar.basis_note || ""),
        ar.launch_note ? notice("warn", ar.launch_note) : null,
        el("div", { class: "rc-armor-grid" }, (ar.groups || []).map((g) => rcArmorGroup(g, ar.items || []))));
    }

    const intents = d.profile && d.profile.permission_intents || {};
    const intentLabel = CARD_INTENT_LABEL;
    const KEYS = CARD_INTENT_KEYS;
    const expect = el("section", { class: "rc-block", "data-rc": "intents" },
      el("h4", null, CARD_INTENT_TITLE),
      el("p", { class: "rc-note" }, (d.profile && d.profile.intents_note) || "只是記錄，不會變成實際權限"),
      el("p", { class: "rc-note", "data-rc": "intent-note" }, CARD_INTENT_NOTE),
      el("div", { class: "rc-chips" }, KEYS.map(([k, zh]) =>
        el("span", { class: "rc-chip" }, `${zh}・${intentLabel[intents[k]] || intentLabel.unspecified}`))));

    const blockers = (d.blockers || []).length ? el("section", { class: "rc-block", "data-rc": "blockers" },
      el("h4", null, "目前無法出發的原因"),
      el("ul", null, d.blockers.map((b) => el("li", null, b && b.message ? String(b.message) : "未知原因"))),
      el("p", { class: "rc-note" }, d.blockers_note || "")) : null;

    return [info, features, skills, armor, expect, blockers];
  }

  function renderRoleCard(p, onLoadout) {
    const box = el("div", { class: "rc", "data-role-card": p.id });
    rcProfile = p;
    rcChanged = async () => { await reloadAgentProfiles(); renderRightColumn(); };
    setKids(box, el("p", { class: "loading" }, "載入角色卡…"));
    api.get(`/api/agent-profiles/${encodeURIComponent(p.id)}/loadout`)
      .then((d) => { setKids(box, ...roleCardParts(p, d)); if (typeof onLoadout === "function") onLoadout(d); })
      .catch((e) => setKids(box, notice("bad", "無法載入角色卡：" + (e && e.message ? e.message : "未知錯誤"))));
    return box;
  }

  // The editor is the same wizard as the card pool page (see openCardWizard); this tab only says what to do after a save.
  function openProfileWizard(existingProfile) {
    return (async () => {
      const catalog = await ensureCatalog();
      if (!catalog) {
        toast("無法載入角色卡目錄");
        return;
      }
      openCardWizard({ catalog, profiles: agentProfiles, existing: existingProfile || null, onSaved: async (saved) => {
        await reloadAgentProfiles();
        selectedProfileId = saved.id;
        renderRightColumn();
      } });
    })();
  }
  function renderAgentProfileEditor() { return openProfileWizard(null); }
  function promptAgentProfileEditor(existingProfile) { return openProfileWizard(existingProfile); }

  // Profile-managed launch (R3 S0): preview what will actually apply, then
  // confirm. The labels come from the server and describe this one launch;
  // they are not Profile settings and none of them is an unbypassable boundary.
  function promptAgentLaunch(p, launchOpts = {}) {
    const titleId = "modal-agent-launch-title";
    let current = null;   // the preview the confirm button refers to
    let busy = false;
    let ackBox = null;    // "I know this Claude Code version is unverified" (only for such previews)
    const liveHome = D.live && typeof D.live.home === "string" ? D.live.home : "";
    const workdirInput = el("input", { type: "text", class: "input", id: "agent-launch-workdir",
      placeholder: `資料夾的絕對路徑，例如 ${liveHome || "/Users/you"}/projects/demo`, autocomplete: "off" });
    if (typeof launchOpts.workdir === "string") workdirInput.value = launchOpts.workdir;
    const openFolderPicker = () => openFolderDialog({
      title: "挑資料夾", useLabel: "用這個資料夾出發",
      onUse: (path) => { workdirInput.value = path; invalidate("輸入已變更，請重新產生預覽。"); } });
    // What the server takes (it checks the folder again when the preview is made): an existing folder inside the home directory.
    const workdirRange = el("p", { class: "small muted", id: "agent-launch-range" },
      launchRangeText(D.live),
      launchOpts.workdirNote ? ` ${launchOpts.workdirNote}` : "");
    const pickBtn = el("button", { class: "btn small", type: "button", "data-act": "pick-folder", on: { click: openFolderPicker } }, "挑資料夾…");
    const commitBox = el("input", { type: "checkbox", id: "agent-launch-commit" });
    if (launchOpts.commit === true) commitBox.checked = true;
    const out = el("div", { class: "agent-launch-preview", "aria-live": "polite" });
    const previewBtn = el("button", { class: "btn", type: "button", on: { click: () => doPreview() } }, "產生預覽");
    const confirmBtn = el("button", { class: "btn primary", type: "button", on: { click: () => doLaunch() } }, "確認啟動");
    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    confirmBtn.disabled = true;

    const why = el("p", { class: "small agent-launch-why", "aria-live": "polite" });
    let lastPreview = null;   // the latest answer, launchable or not, for saying why the button is off

    // The dialog speaks for the tool of the profile: only a Claude Code launch has a version to verify and a
    // terminal title to check; a Codex preview shows what it returned (its reasons and its evidence); any
    // other tool (shared) has no launch, so it shows only what the preview returned, in no tool's words.
    const tool = p.model && p.model.tool;
    const isClaude = tool === "claude";
    const isCodex = tool === "codex";
    const cliName = isClaude ? "Claude Code" : isCodex ? "Codex CLI" : "";
    function needsAck(pv) { return Boolean(isClaude && pv && pv.cli && pv.cli.verified === false); }
    // Why 確認啟動 is off, in words (design 4.3): the button is never off without a reason beside it.
    function whyOff() {
      if (busy) return "";
      if (!current) {
        if (lastPreview && !lastPreview.launchable) {
          const reasons = (lastPreview.reasons || []).map((r) => r && r.message).filter(Boolean);
          return "現在不能出發：" + (reasons.join("；") || "這張角色卡目前無法啟動") + "。";
        }
        return "現在不能出發：還沒有產生這次的預覽。先填「在哪裡做」的資料夾、勾選 commit 的知悉，再按「產生預覽」。";
      }
      if (needsAck(current) && !(ackBox && ackBox.checked)) {
        return "現在不能出發：還沒有勾選「我知道這個版本未驗證，仍要啟動」。";
      }
      return "";
    }
    function syncConfirm() {
      confirmBtn.disabled = !current || (needsAck(current) && !(ackBox && ackBox.checked));
      why.textContent = whyOff();
    }

    function invalidate(message) {
      current = null;
      lastPreview = null;
      ackBox = null;
      confirmBtn.disabled = true;
      setKids(out, message ? el("p", { class: "small muted" }, message) : null);
      why.textContent = busy ? "" : whyOff();
    }
    workdirInput.addEventListener("input", () => invalidate("輸入已變更，請重新產生預覽。"));
    commitBox.addEventListener("change", () => invalidate("輸入已變更，請重新產生預覽。"));

    const modalElem = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
      el("div", { class: "modal-box modal-wide" },
        el("h2", { id: titleId }, `出發通行證：${p.name || p.id}`),
        el("p", { class: "small muted" },
          "出發前先看這張通行證：這次出發實際會套上的限制，和它擋不到的地方。確認後才會啟動角色。"),
        el("label", { class: "small", for: "agent-launch-workdir" }, PASS_WORKDIR_LABEL),
        el("div", { class: "row fp-paste" }, workdirInput, pickBtn),
        workdirRange,
        el("label", { class: "row small", for: "agent-launch-commit", style: "gap:8px; align-items:flex-start" },
          commitBox,
          el("span", null, PASS_COMMIT_ACK, el("span", { class: "small muted" }, " 不勾選就無法啟動。"))),
        out,
        why,
        el("div", { class: "modal-actions" }, cancelBtn, previewBtn, confirmBtn)));
    document.body.append(modalElem);
    const closeModal = withModalA11y(modalElem, () => modalElem.remove());
    workdirInput.focus();
    why.textContent = whyOff();

    // A reason it cannot go, with the button that leads to where it is changed (PASS_FIXES). The editor closes when
    // the card is saved and this pass opens again, on the same folder, with a new preview: the fix returns here.
    function fixRole(openIntents) {
      return async () => {
        const catalog = await ensureCatalog();
        if (!catalog) { toast("無法載入角色卡目錄"); return; }
        openCardWizard({ catalog, profiles: agentProfiles, existing: p, start: 2, openIntents, onSaved: async (saved) => {
          await reloadAgentProfiles();
          const fresh = agentProfiles.find((x) => x.id === saved.id) || saved;
          renderRightColumn();
          closeModal();
          promptAgentLaunch(fresh, { workdir: workdirInput.value, commit: commitBox.checked, autoPreview: true });
        } });
      };
    }
    function fixAction(fix) {
      if (!fix) return null;
      const run = fix.act === "intents" ? fixRole(true) : fix.act === "tool" ? fixRole(false)
        : fix.act === "commit" ? () => { commitBox.focus(); }
        : fix.act === "folder" ? openFolderPicker : null;
      return run ? el("button", { class: "btn small", type: "button", "data-pass-fix": fix.act, on: { click: run } }, fix.label) : null;
    }
    function reasonItem(r) {
      return el("li", { "data-reason": r && r.code ? r.code : "" }, r && r.message ? r.message : "原因不明", " ",
        fixAction(passFix(r && r.code)));
    }

    function renderPreview(pv) {
      const kids = [];
      if (!pv.launchable) {
        kids.push(el("div", { class: "notice warn", "data-pass": "blocked" },
          el("span", { class: "ico", "aria-hidden": "true" }, "!"),
          el("div", null,
            el("strong", null, "這張角色卡目前無法啟動"),
            el("ul", { class: "small pass-reasons" }, (pv.reasons || []).map(reasonItem)))));
      } else {
        kids.push(passFront(pv));
        kids.push(el("dl", { class: "kv small" },
          el("dt", null, "CLI"), el("dd", { class: "mono" }, `${cliName ? cliName + " " : ""}${pv.cli.version} · ${pv.cli.binary}`),
          el("dt", null, "版本驗證"),
          el("dd", null, isCodex ? "以 VBear 已記錄的證據為準（見下方各項的證據欄）"
            : !isClaude ? "不適用"
            : pv.cli.verified === true ? "已驗證" : pv.cli.verified === false ? "未驗證（見下方）" : "未知"),
          el("dt", null, PASS_WORKDIR_LABEL), el("dd", { class: "mono" }, pv.canonical_paths.workdir),
          el("dt", null, "本次暫存區"), el("dd", { class: "mono" }, pv.canonical_paths.scratch),
          el("dt", null, "預覽有效至"), el("dd", null, new Date(pv.expires_at * 1000).toLocaleTimeString())));
        if (isCodex) kids.push(codexEvidenceNote(pv));
        else if (!isClaude) { /* another tool: nothing about a version or a title to say */ }
        else if (needsAck(pv)) kids.push(unverifiedBox(pv));
        else if (pv.cli && pv.cli.activity_verified === false) kids.push(activityUnverifiedBox(pv));
      }
      // The concrete bypass (e.g. "!" shell commands in the terminal) comes from
      // the server's labels; show each distinct text once instead of per label. It stays on the front of the pass.
      const bypasses = [...new Set(Object.values(pv.derived_labels || {})
        .map((lab) => lab && lab.bypass).filter((b) => typeof b === "string" && b))];
      if (bypasses.length) {
        kids.push(el("div", { class: "notice warn agent-launch-bypass" },
          el("span", { class: "ico", "aria-hidden": "true" }, "!"),
          el("div", { class: "small" }, el("strong", null, "可繞過："), bypasses.join(" "))));
      }
      // The seven labels of THIS preview, in the five groups; a group is only a frame, every item keeps its
      // level words, note and limits, and an empty group says so. They are the full text behind the three lines.
      const scopeText = (v) => Array.isArray(v) ? (v.filter(Boolean).join("、") || "不適用") : (v || "不適用");
      const items = Object.entries(pv.derived_labels || {}).map(([name, lab]) => ({
        name, level: lab.level, group: armorGroupOf(lab.level), note: lab.note,
        path_scope: scopeText(lab.path_scope), evidence_refs: scopeText(lab.evidence_refs),
        unknown_reason: lab.unknown_reason && lab.unknown_reason !== "none" && lab.unknown_reason !== lab.note
          ? lab.unknown_reason : null }));
      // the groups with the level words this tool can show (the server knows; the table is the fallback)
      const groups = Array.isArray(pv.armor_groups) && pv.armor_groups.length ? pv.armor_groups
        : ARMOR_GROUPS_UI.map((g) => ({ ...g, levels: g.levels.filter((lv) => isClaude || !/Claude/.test(lv)) }));
      kids.push(el("details", { class: "pass-details", "data-pass": "details" },
        el("summary", null, PASS_DETAILS_LABEL),
        el("h4", { class: "agent-launch-h" }, "七項標示（這次出發通行證的實際標示）"),
        el("p", { class: "small muted" },
          "以下七項是這次啟動的實際套用程度，由設定與實測證據推導，不是角色卡的設定值。" +
          "使用者在進階終端仍可自行改變 CLI 行為，沒有一項是不可繞過的邊界。"),
        el("div", { class: "rc-armor-grid agent-launch-labels", "data-armor": "preview" },
          groups.map((g) => rcArmorGroup(g, items))),
        chosenSkillsList()));
      setKids(out, ...kids);
    }

    // The profile's chosen skills as a list that is only a record: they do not go with the launch.
    function chosenSkillsList() {
      const ids = (p.equipped_skill_ids || []).filter((x) => typeof x === "string");
      const catalog = (agentBuilderCatalog && agentBuilderCatalog.skills) || [];
      const gone = new Set((p._unresolved && p._unresolved.skills) || []);
      return el("section", { class: "rc-block", "data-launch": "chosen-skills" },
        el("h4", null, "技能卡清單（收藏中），本次不會載入"),
        el("p", { class: "rc-note" }, "這是你替這張角色卡收藏的清單，只是紀錄；這次出發不會把這些技能帶上。"),
        ids.length ? el("ul", null, ids.map((sid) => {
          const rec = catalog.find((x) => x.skill_id === sid);
          const name = rec && rec.name ? String(rec.name) : `未提供（ID：${sid}）`;
          return el("li", null, name, gone.has(sid) ? "（目前索引找不到此技能）" : "");
        })) : el("p", { class: "rc-note" }, "沒有插任何技能卡。"));
    }

    // A Codex preview: no version to verify and no title check here; the evidence is on each label.
    function codexEvidenceNote(pv) {
      return el("div", { class: "notice info" },
        el("span", { class: "ico", "aria-hidden": "true" }, "i"),
        el("div", { class: "small" },
          el("strong", null, `Codex CLI ${pv.cli.version}`),
          el("p", { style: "margin:4px 0" },
            "VBear 對 Codex 只依已記錄的證據標示防具；沒有證據的項目標為「未知」。每一項的證據在下方的「證據」欄。")));
    }

    // Claude Code updates itself often; a release nobody verified yet may still
    // run, but only after the user says so, and it can be verified from here.
    // 「驗證這個版本」: one run checks the launch boundary and the terminal
    // title; the two results are shown separately when it ends.
    function verifyControl(pv, label = "驗證這個版本") {
      const verifyBtn = el("button", { class: "btn small", type: "button", on: { click: () => doVerify() } },
        label);
      const progress = el("p", { class: "small muted", "aria-live": "polite" });
      async function doVerify() {
        verifyBtn.disabled = true;
        progress.textContent = "正在驗證…（約 1–3 分鐘）";
        try {
          const r = await api.post("/api/native/claude-verification", { version: pv.cli.version });
          if (r.already_verified) { progress.textContent = "這個版本已驗證過。"; return doPreview(); }
          for (;;) {
            await new Promise((res) => setTimeout(res, 3000));
            if (!modalElem.isConnected) return;
            const { status } = await api.get("/api/native/claude-verification");
            if (status.running) {
              progress.textContent = `正在驗證（${status.step === "interactive" ? "2/2 互動模式" : "1/2 無頭模式"}）…`;
              continue;
            }
            if (status.result === "passed") {
              const lines = verificationLines(pv.cli.version, status);
              toast(lines.join("；"));
              await doPreview();  // labels and the notice now follow this machine's record
              setKids(out, ...[el("div", { class: "notice info small" }, lines.map((l) => el("div", null, l)))]
                .concat([...out.childNodes]));
              return;
            }
            progress.textContent = "驗證沒有通過：" + (status.message || "原因未知") + "。";
            verifyBtn.disabled = false;
            return;
          }
        } catch (err) {
          progress.textContent = "無法驗證：" + err.message;
          verifyBtn.disabled = false;
        }
      }
      return { verifyBtn, progress };
    }

    function verificationLines(version, status) {
      return [
        `啟動邊界：Claude Code ${version} 通過`,
        status.title_result === "passed"
          ? "終端標題：通過，這台 Mac 可以判斷「工作中／等你回覆」"
          : `終端標題：沒有通過（${titleFailureText(status.title_failed)}），狀態會維持「未知」`,
      ];
    }

    // Launch boundary verified, terminal title not: launching needs nothing
    // extra, but VBear cannot tell working from waiting until it is verified.
    function activityUnverifiedBox(pv) {
      const lastFailure = Array.isArray(pv.cli.activity_last_failure) && pv.cli.activity_last_failure.length
        ? pv.cli.activity_last_failure : null;
      const { verifyBtn, progress } = verifyControl(pv, lastFailure ? "再驗證一次" : "驗證這個版本");
      return el("div", { class: "notice info" },
        el("span", { class: "ico", "aria-hidden": "true" }, "i"),
        el("div", { class: "small" },
          el("strong", null, "出發後 VBear 暫時看不出它在忙還是在等你"),
          el("p", { class: "small muted", style: "margin:4px 0" }, `原因：Claude Code ${pv.cli.version} 的「忙／等你」判斷方式還沒有在這台 Mac 驗證過。`),
          el("p", { style: "margin:4px 0" },
            "可以照常啟動；只是啟動後，VBear 會把它的狀態顯示為「未知」。驗證會同時檢查啟動邊界與終端標題。"),
          lastFailure ? el("p", { class: "agent-launch-last-failure", style: "margin:4px 0" },
            `上一次在這台 Mac 驗證時，啟動邊界通過，但終端標題沒有通過：${titleFailureText(lastFailure)}。` +
            "這可能是當時 Claude 的畫面沒有照預期切換，可以再試一次。") : null,
          el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:6px" }, verifyBtn,
            el("span", { class: "muted" }, lastFailure
              ? "再驗證一次約用 2 次模型呼叫（Haiku，用你的 Claude 帳號）。"
              : "會用你的 Claude 帳號做 2 次小型模型呼叫（Haiku）。")),
          progress));
    }

    function unverifiedBox(pv) {
      ackBox = el("input", { type: "checkbox", id: "agent-launch-unverified", on: { change: syncConfirm } });
      const { verifyBtn, progress } = verifyControl(pv);
      return el("div", { class: "notice warn" },
        el("span", { class: "ico", "aria-hidden": "true" }, "!"),
        el("div", { class: "small" },
          el("strong", null, `Claude Code ${pv.cli.version} 還沒有驗證過`),
          el("p", { style: "margin:4px 0" },
            "VBear 會套用和已驗證版本相同的沙盒設定，但沒有實測過這個版本是否真的遵守，所以下方的權限標示為「未驗證」。"),
          el("label", { class: "row", for: "agent-launch-unverified", style: "gap:8px; align-items:flex-start" },
            ackBox, el("span", null, "我知道這個版本未驗證，仍要啟動。")),
          el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:6px" }, verifyBtn,
            el("span", { class: "muted" }, "會用你的 Claude 帳號做 2 次小型模型呼叫（Haiku）；通過後這個版本就算已驗證。")),
          progress));
    }

    async function doPreview() {
      if (busy) return;
      busy = true;
      previewBtn.disabled = true;
      invalidate("正在產生預覽…");
      try {
        const res = await api.post("/api/native/agent-previews", {
          profile_id: p.id, workdir: workdirInput.value.trim(), commit: !!commitBox.checked });
        current = res.preview.launchable ? res.preview : null;
        lastPreview = res.preview;
        renderPreview(res.preview);
        syncConfirm();
      } catch (err) {
        invalidate("無法產生預覽：" + err.message);
        const fix = fixAction(passFolderFix(err));
        if (fix) out.append(fix);
      } finally {
        busy = false;
        previewBtn.disabled = false;
        syncConfirm();   // the reason line is empty while busy; say it now
        // Disabling the focused button moved focus to <body>, outside the dialog,
        // so Escape no longer reached it (S0 browser QA). Put focus back inside.
        const active = document.activeElement;
        if (!active || active === document.body || !modalElem.contains(active)) {
          previewBtn.focus();  // not the confirm button: a stray Enter must not launch
        }
      }
    }

    if (launchOpts.autoPreview === true && workdirInput.value.trim()) doPreview();

    async function doLaunch() {
      if (busy || !current) return;
      busy = true;
      confirmBtn.disabled = true;
      const pv = current;
      current = null;  // a preview is single use, whatever the outcome
      try {
        const res = await api.post("/api/native/agent-launches", {
          preview_id: pv.preview_id, expected_settings_digest: pv.settings_digest, user_confirmed: true,
          ...(needsAck(pv) ? { accept_unverified_cli: Boolean(ackBox && ackBox.checked) } : {}) });
        toast("已啟動（由角色卡啟動，VBear 管理）");
        if (launchOpts.fromTask && launchOpts.fromTask.step && res.launch && res.launch.session) {
          launchMemoAdd(launchOpts.fromTask.id, { step: launchOpts.fromTask.step, session_id: res.launch.session.session_id, name: p.name || p.id });
        }
        closeModal();
        location.hash = `#/term/${encodeURIComponent(res.launch.session.session_id)}`;
      } catch (err) {
        invalidate("啟動未完成：" + err.message + "　請重新產生預覽。");
      } finally {
        busy = false;
      }
    }
  }

  function promptDeleteAgentProfile(p) {
    deleteCard(p, async () => {
      await reloadAgentProfiles();
      if (selectedProfileId === p.id) selectedProfileId = null;
      renderRightColumn();
    });
  }

  function renderAgentTabContent() {
    const content = el("div", { class: "wb-tab-content wb-agent-builder" });
    const header = el("div", { class: "row", style: "justify-content:space-between" },
      el("h3", { style: "margin:0" }, "角色卡"),
      prov({ origin: "user", detail: "主控台儲存的角色卡 · 與掃描到的角色範本不同" }));
    const createBtn = el("button", { class: "btn primary", type: "button", "data-wb": "new-card",
      on: { click: () => renderAgentProfileEditor() } }, "＋ 新角色卡");

    const sub = el("div", { class: "small muted", style: "margin: 4px 0;" },
      "角色卡是你自選陣營、職業標籤與技能卡的設定組合，");
    const sub2 = el("div", { class: "small muted", style: "margin-bottom: 8px;" },
      "與掃描到的角色範本（唯讀）並存。技能卡僅為挑選紀錄（收藏中）。");

    const selected = agentProfiles.find((p) => p.id === selectedProfileId);

    const split = el("div", { class: "wb-split" });
    // Sizing lives in style.css (.wb-agent-builder container query) so the
    // split can stack when the right column is narrow; inline min-width here
    // previously crushed the detail column to ~40px (Gate 7 finding).
    const listCol = el("div", { class: "wb-col-left" });
    const detailCol = el("div", { class: "wb-col-right" });

    if (agentProfiles.length === 0) {
      setKids(listCol, emptyState("尚未建立任何角色卡", null));
    } else {
      setKids(listCol,
        el("div", { class: "wb-list" }, agentProfiles.map(renderAgentProfileListItem)));
    }
    if (selected) {
      setKids(detailCol, renderAgentProfileDetail(selected));
    } else {
      setKids(detailCol,
        emptyState("請從左側選取一張角色卡，或建立新的", null),
        el("div", { class: "notice info", style: "font-size:12.5px; margin-top:8px;" },
          el("span", { class: "ico", "aria-hidden": "true" }, "i"),
          el("div", null,
            "角色卡只會寫入主控台狀態目錄 (",
            el("code", null, "~/.vbear/agent_profiles.json"),
            ")，",
            "絕對不會寫入 ~/.codex、~/.claude、第三方技能/角色來源或外掛市集。")));
    }
    split.append(listCol, detailCol);

    return append(content,
      header,
      createBtn,
      sub,
      sub2,
      el("div", { class: "small muted", style: "margin-bottom: 8px;" },
        "儲存後不會啟動、重啟或注入任何東西；權限意圖只是記錄，不是授權。"),
      split);
  }

  // Right Tab: [P] Project Contract Skeleton
  function renderProjectTabContent() {
    const content = el("div", { class: "wb-tab-content" });
    const pData = govData.project || {};
    const contract = pData.contract || {};

    return append(content,
      el("div", { class: "row", style: "justify-content:space-between" },
        el("h3", { style: "margin:0" }, "專案契約 (Project Contract)"),
        prov({ origin: "derived", detail: "專案契約骨架 · 唯讀展示" })),
      el("div", { class: "notice info", style: "font-size:12.5px" },
        el("span", { class: "ico" }, "ℹ"),
        el("div", null, pData.description || "專案邊界與建置契約骨架展示。")),
      el("dl", { class: "kv small" },
        el("dt", null, "技術架構"), el("dd", null, contract.stack || "—"),
        el("dt", null, "執行邊界"), el("dd", null, contract.runtime || "—"),
        el("dt", null, "安全規範"), el("dd", null, contract.security || "—"),
        el("dt", null, "驗證指令"), el("dd", { class: "mono small" }, contract.tests || "—"),
        el("dt", null, "約束條款"), el("dd", null, contract.boundaries || "—"))
    );
  }

  // Right Tab: [G] Global Governance Skeleton
  function renderGlobalTabContent() {
    const content = el("div", { class: "wb-tab-content" });
    const gData = govData.global || {};
    const categories = gData.categories || [];

    const catBlocks = categories.map((cat) => {
      const rules = (cat.rules || []).map((r) => el("div", { style: "margin-bottom:6px" },
        el("div", { class: "row", style: "font-weight:600; font-size:13px" },
          el("span", { class: "mono" }, r.id),
          el("span", null, r.name),
          badge(r.type, "b-bad plain", "強制規則")),
        el("div", { class: "small muted" }, r.description)));
      return el("div", { class: "wb-field-group" },
        el("div", { class: "wb-field-label" }, cat.name),
        el("div", { class: "wb-field-val" }, rules));
    });

    return append(content,
      el("div", { class: "row", style: "justify-content:space-between" },
        el("h3", { style: "margin:0" }, "全域底線 (Global Governance)"),
        prov({ origin: "derived", detail: "全域規則骨架 · 唯讀展示" })),
      el("div", { class: "notice warn", style: "font-size:12.5px" },
        el("span", { class: "ico" }, "!"),
        el("div", null, govData.notice || "G/P 層於本階段為唯讀介面骨架展示，尚未進行全域治理遷移，無 Policy Compiler 或自動注入。")),
      catBlocks
    );
  }

  // ---------- Task Modals ----------
  // What follows a completed or blocked card (tasks.py closure), and where
  // the work went if it was handed off.
  function closureRow(task) {
    const c = task.closure;
    if (task.legacy_status) {
      // tasks.LEGACY_RAW_STATUSES: say what the old card claimed instead of
      // silently showing it as a draft.
      const [label] = TASK_STATUS_LABELS[task.legacy_status] || [task.legacy_status];
      return el("div", { class: "wb-provenance-row small", style: "color:var(--warn)" },
        `⚠️ 舊資料：這張卡以前直接標成「${label}」，但 Agent 回報狀態沒有跟著改；現在的狀態改依 Agent 回報、測試與核准判斷。` +
        "要標成完成或阻塞，請在第 1 欄重新選擇並附上結案理由。");
    }
    if (!c) {
      return task.closure_missing
        ? el("div", { class: "wb-provenance-row small", style: "color:var(--warn)" },
          "⚠️ 缺少結案理由：這張卡在規則加入前就已回報完成或阻塞。")
        : null;
    }
    const successor = c.successor && tasksList.find((t) => t.id === c.successor);
    return el("div", { class: "wb-provenance-row" },
      el("span", null, "結案理由：", el("b", null, CLOSURE_LABEL[c.reason] || c.reason),
        c.target ? `（對象：${c.target}）` : "",
        c.set_at ? el("span", { class: "small muted" }, ` · ${fmtTime(c.set_at)}`) : null),
      el("span", { class: "small muted" }, c.note || "",
        successor ? el("button", {
          class: "btn small", type: "button",
          on: { click: () => { activeTaskId = successor.id; renderRightColumn(); } },
        }, `開啟接手的卡：${successor.title}`) : null));
  }

  // The cards this one was handed down from, oldest first (tasks.py
  // chain_of_record; only handoff_task() writes it).
  function chainRow(task) {
    const chain = task.chain_of_record || [];
    if (!chain.length) return null;
    return el("div", { class: "row small muted", style: "flex-wrap:wrap; gap:4px; margin:4px 0" },
      "交接鏈：",
      chain.map((id) => {
        const t = tasksList.find((x) => x.id === id);
        return [t
          ? el("button", { class: "btn small", type: "button", on: { click: () => { activeTaskId = id; renderRightColumn(); } } }, t.title)
          : el("span", { class: "mono", title: "這張卡已不在清單中" }, id), " → "];
      }),
      el("b", null, "本卡"));
  }

  function promptClosure(task, agent) {
    const reasons = CLOSURE_REASONS[agent];
    const reasonSelect = el("select", null, reasons.map(([v, l]) => el("option", { value: v }, l)));
    const targetInput = el("input", { type: "text", placeholder: "交給誰、卡在誰或上報給誰" });
    const noteInput = el("textarea", { rows: "2", placeholder: "補充說明（選填）" });
    const targetLabel = el("label", null, "對象 *", targetInput);
    const syncTarget = () => { targetLabel.style.display = CLOSURE_NEEDS_TARGET.has(reasonSelect.value) ? "" : "none"; };
    reasonSelect.addEventListener("change", syncTarget);
    syncTarget();
    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    const saveBtn = el("button", { class: "btn primary", type: "button", on: { click: submit } }, "確定");
    const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "task-closure-modal-title" },
      el("div", { class: "modal-box", style: "max-width: 480px;" },
        el("h2", { id: "task-closure-modal-title" }, agent === "completed" ? "回報完成：接下來是什麼？" : "阻塞：在等誰？"),
        el("p", { class: "small muted" }, "標成「已回報完成」或「阻塞」時要說明後續，任務才不會停在沒人接手的狀態。"),
        el("div", { class: "wb-form" }, el("label", null, "結案理由", reasonSelect), targetLabel, el("label", null, "說明", noteInput)),
        el("div", { class: "modal-actions" }, cancelBtn, saveBtn)));
    document.body.append(modal);
    const closeModal = withModalA11y(modal, () => { modal.remove(); renderRightColumn(); });
    reasonSelect.focus();

    async function submit() {
      const reason = reasonSelect.value;
      const target = targetInput.value.trim();
      if (CLOSURE_NEEDS_TARGET.has(reason) && !target) {
        toast("這個結案理由需要填寫對象");
        targetInput.focus();
        return;
      }
      saveBtn.disabled = true;
      try {
        const res = await api.post(`/api/tasks/${encodeURIComponent(task.id)}`, {
          provenance: { ...(task.provenance || {}), agent },
          closure: { reason, target: target || null, note: noteInput.value.trim() },
        });
        Object.assign(task, res.task);
        closeModal();
      } catch (err) {
        toast("更新失敗：" + err.message);
        saveBtn.disabled = false;
      }
    }
  }

  function promptHandoff(task) {
    const toInput = el("input", { type: "text", placeholder: "接手的角色、Agent 或人（必填）" });
    const titleInput = el("input", { type: "text", value: `交接：${task.title}` });
    const noteInput = el("textarea", { rows: "3", placeholder: "交接說明：做到哪、還缺什麼、怎麼驗證（選填）" });
    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    const saveBtn = el("button", { class: "btn primary", type: "button", on: { click: submit } }, "交接");
    const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "task-handoff-modal-title" },
      el("div", { class: "modal-box", style: "max-width: 520px;" },
        el("h2", { id: "task-handoff-modal-title" }, "交接任務卡"),
        el("p", { class: "small muted" }, "這張卡會標成「已交接」，同時建立一張接手的新卡：目標、範圍、驗收條件與工作目錄沿用，狀態證明從頭開始，並記下交接鏈。"),
        el("div", { class: "wb-form" },
          el("label", null, "交給 *", toInput), el("label", null, "新卡標題", titleInput), el("label", null, "說明", noteInput)),
        el("div", { class: "modal-actions" }, cancelBtn, saveBtn)));
    document.body.append(modal);
    const closeModal = withModalA11y(modal, () => modal.remove());
    toInput.focus();

    async function submit() {
      const to = toInput.value.trim();
      if (!to) {
        toast("請填寫接手的對象");
        toInput.focus();
        return;
      }
      saveBtn.disabled = true;
      try {
        const res = await api.post(`/api/tasks/${encodeURIComponent(task.id)}/handoff`, {
          to, title: titleInput.value.trim(), note: noteInput.value.trim(),
        });
        Object.assign(task, res.from);
        tasksList.unshift(res.to);
        activeTaskId = res.to.id;
        toast(`已交接給 ${to}`);
        closeModal();
        renderRightColumn();
      } catch (err) {
        toast("交接失敗：" + err.message);
        saveBtn.disabled = false;
      }
    }
  }

  // A new task card is made by importing a folder (one card, one folder); the picker and the form are shared with the lobby.
  function promptCreateTask() {
    return openImportProject({
      paneId: activePaneId,
      onCreated: (task) => {
        tasksList.unshift(task);
        activeTaskId = task.id;
        renderRightColumn();
      },
      onOpenTask: (id) => {
        if (tasksList.some((t) => t.id === id)) { activeTaskId = id; renderRightColumn(); }
        else location.hash = `#/workbench?task=${encodeURIComponent(id)}`;
      },
    });
  }

  function promptEditTask(task) {
    let modal;
    const titleInput = el("input", { type: "text", value: task.title || "", required: true });
    const goalInput = el("textarea", { rows: "3" }, task.goal || "");
    const scopeInput = el("textarea", { rows: "2" }, (task.scope || []).join("\n"));
    const outOfScopeInput = el("textarea", { rows: "2" }, (task.out_of_scope || []).join("\n"));
    const deliverablesInput = el("textarea", { rows: "2" }, (task.deliverables || []).join("\n"));
    const criteriaInput = el("textarea", { rows: "2" }, (task.acceptance_criteria || []).join("\n"));
    const evidenceInput = el("textarea", { rows: "2" }, (task.evidence || []).join("\n"));
    const workdirInput = el("input", { type: "text", value: task.workdir || "", placeholder: "/Users/you/project（選填）" });

    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    const saveBtn = el("button", { class: "btn primary", type: "button", on: { click: submitSave } }, "儲存修改");

    modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "task-edit-modal-title" },
      el("div", { class: "modal-box", style: "max-width: 620px; max-height: 85vh; overflow-y: auto;" },
        el("h2", { id: "task-edit-modal-title" }, "編輯任務卡"),
        el("div", { class: "wb-form" },
          el("label", null, "任務標題 *", titleInput),
          el("label", null, "目標 (Goal)", goalInput),
          el("label", null, "範圍 (Scope，每行一項)", scopeInput),
          el("label", null, "範圍外 (Out of Scope，每行一項)", outOfScopeInput),
          el("label", null, "交付物 (Deliverables，每行一項)", deliverablesInput),
          el("label", null, "驗收條件 (Acceptance Criteria，每行一項)", criteriaInput),
          el("label", null, "實測證據 (Evidence，每行一項)", evidenceInput),
          el("label", null, "工作目錄（改了之後，既有的測試與核准仍對應原本的 commit）", workdirInput),
          el("button", { class: "btn small", type: "button", "data-act": "pick-folder", on: { click: () => openFolderDialog({
            title: "挑資料夾", useLabel: "用這個資料夾", onUse: (path) => { workdirInput.value = path; } }) } }, "挑資料夾…")),
        el("div", { class: "modal-actions" }, cancelBtn, saveBtn)));
    document.body.append(modal);

    // withModalA11y registers this dialog, so view cleanup (navigating away
    // mid-dialog) closes it the proper way instead of leaving it orphaned
    // with the rest of the page still marked inert.
    const closeModal = withModalA11y(modal, () => modal.remove());

    async function submitSave() {
      const title = titleInput.value.trim();
      if (!title) {
        toast("請填寫任務標題");
        titleInput.focus();
        return;
      }
      saveBtn.disabled = true;
      try {
        const payload = {
          title,
          goal: goalInput.value.trim(),
          scope: scopeInput.value.trim(),
          out_of_scope: outOfScopeInput.value.trim(),
          deliverables: deliverablesInput.value.trim(),
          acceptance_criteria: criteriaInput.value.trim(),
          evidence: evidenceInput.value.trim(),
          workdir: workdirInput.value.trim() || null,
        };
        const res = await api.post(`/api/tasks/${encodeURIComponent(task.id)}`, payload);
        Object.assign(task, res.task);
        toast("任務卡已儲存");
        closeModal();
        renderRightColumn();
      } catch (err) {
        toast("儲存失敗：" + err.message);
        saveBtn.disabled = false;
      }
    }
  }

  function promptDeleteTask(task) {
    if (!confirm(`確定要刪除任務卡「${task.title}」嗎？此動作不可回復。`)) return;
    api.post(`/api/tasks/${encodeURIComponent(task.id)}/delete`)
      .then(() => {
        tasksList = tasksList.filter((t) => t.id !== task.id);
        activeTaskId = tasksList.length ? tasksList[0].id : null;
        toast("任務卡已刪除");
        renderRightColumn();
      })
      .catch((err) => toast("刪除失敗：" + err.message));
  }

  // Initial layout assembly
  syncLayoutClasses();
  renderLeftColumn();
  renderCenterColumn();
  renderRightColumn();

  setKids(main,
    crumbs([["角色卡池", "#/team"], ["終端工作台"]]),
    toolbar,
    shell
  );
  // On a phone the columns stack and the terminals come first. Coming in from a task card (its 打開), the person wants
  // the task card and its team, so the page starts there; only when the address names a task, and only when stacked.
  if (initialTaskId && workbenchStacked()) {
    setTimeout(() => { if (token === seq && rightCol.scrollIntoView) rightCol.scrollIntoView({ block: "start" }); }, 0);
  }

  // 「出發」 on a card of the card pool lands here with the launch pass already open; the address is cleaned at
  // once so that a later re-render of the page does not open it again.
  if (autoLaunch && initialProfileId) {
    const target = agentProfiles.find((p) => p.id === initialProfileId);
    try { history.replaceState(null, "", `#/workbench?profile=${encodeURIComponent(initialProfileId)}`); } catch (_) { /* optional */ }
    const fromTask = initialTaskId ? tasksList.find((t) => t.id === initialTaskId) : null;
    if (target && target.enabled !== false) {
      promptAgentLaunch(target, fromTask && fromTask.workdir
        ? { workdir: fromTask.workdir, workdirNote: `已帶入任務卡「${fromTask.title || fromTask.id}」的資料夾，可以改。`,
            // which step of which task card this start is for: kept only as a note on that card after the terminal opens
            fromTask: { id: fromTask.id, step: cardHas(NEXT_STEP_ASK, initialStep) ? initialStep : "" } } : {});
    }
    else if (target) toast("這張角色卡已停用，不能出發");
    else toast("找不到這張角色卡，可能已經刪除");
  }
}

// ---------- team slots: put role cards on a task card (design card-play 3.5) ----------------------------------------
// A task card has three places for role cards: planning, execution, review (and a dashed second review place). A card
// put there is copied into the flow's role (name, family, model) with a note of which card it was and the card's
// revision at that moment; nothing follows the card afterwards, and nothing here starts or sends anything. The only
// rule enforced on screen is the one the server already enforces for a review: it counts when the reviewer's and the
// executor's model families are both known and different.

const TEAM_TOOL_FAMILY = { claude: "anthropic", codex: "openai", shared: "unknown" };
const TEAM_FAMILY_LABEL = { anthropic: "Anthropic（Claude）", openai: "OpenAI（Codex）", google: "Google（Gemini）",
  minimax: "MiniMax", other: "其他", unknown: "不明" };
const TEAM_SLOTS = [
  { key: "planner", label: "規劃位", short: "規劃", position: "planner" },
  { key: "executor", label: "執行位", short: "執行", position: "executor" },
  { key: "reviewer1", label: "審查位", short: "審查 1", position: "reviewer" },
  { key: "reviewer2", label: "第二位審查", short: "審查 2", position: "reviewer", optional: true },
];
const TEAM_ROLE_NAME_MAX = 80;
const TEAM_DRAFT_KEY = "team.draft.";
const TEAM_DRAG_TYPE = "text/x-vbear-card";
const TEAM_MENU_MAX = 48;
const TEAM_TRAY_MAX = 24;
const SLOT_REVIEW_SELF = "同一張卡不能審查自己";
const SLOT_REVIEW_NEEDS_DIFF = "這個位置需要和執行位不同陣營的卡，審查結果才算數";
const TEAM_SAVE_NOTE = "儲存會在時間軸記一筆「角色變更」；換掉隊伍之後，先前由自動審查留下的結果可能不再算數。";
// One fixed sentence per term the next-steps list uses (design 3.5): the words come from what the console already says.
const TEAM_INFO = {
  risk: "接受殘餘風險是你自己做的一筆記錄。沒有有效的接受，VBear 不會啟動執行者，也不會啟動 Codex 審查；接受不會讓 VBear 多擋住什麼，" +
    "它只是承認還有這些風險，完整清單在接受視窗裡。",
  stamina: "體力是停損設定：經過時間、執行者額度（USD）等的上限，到了上限 VBear 就停止這個流程。九項的預設與上限都列在接受視窗裡，" +
    "你可以調低，不能超過上限。固定規則：連續失敗 1 次就停止。",
  executor: "串流執行者是由 VBear 啟動的 Claude Code。派工要先預覽、由你核准才會送出；沒有有效的風險接受就不能啟動。",
};
function teamInfo(key, label) { return helpTip(label, TEAM_INFO[key]); }

function teamFamily(tool) {
  return typeof tool === "string" && cardHas(TEAM_TOOL_FAMILY, tool) ? TEAM_TOOL_FAMILY[tool] : "unknown";
}
// The family of a card or of a role: a role carries its own `family`; a role card is read from its tool.
function teamCardFamily(card) {
  if (!card || typeof card !== "object") return "unknown";
  if (typeof card.family === "string" && cardHas(TEAM_FAMILY_LABEL, card.family)) return card.family;
  const tool = card.model && typeof card.model === "object" ? card.model.tool : card.tool;
  return teamFamily(tool);
}
// The tool of a card or a role, for its look: a card says it; a role filled from a card says it in its snapshot; a
// hand-written role only has a family, and the two families that have a tool here map back to it.
const TEAM_FAMILY_TOOL = { anthropic: "claude", openai: "codex" };
function teamCardTool(card) {
  if (!card || typeof card !== "object") return "";
  if (card.profile_snapshot && typeof card.profile_snapshot.tool === "string") return card.profile_snapshot.tool;
  const tool = card.model && typeof card.model === "object" ? card.model.tool : card.tool;
  if (typeof tool === "string") return tool;
  return typeof card.family === "string" && cardHas(TEAM_FAMILY_TOOL, card.family) ? TEAM_FAMILY_TOOL[card.family] : "";
}

// The red the person sees on a place the moment a card lands on it. Only a review place can be wrong: the card's family
// and the executor's decide whether the review counts, exactly as the server judges a review. The place is still
// allowed (it is a record); it just says plainly that the result will not count. null means nothing to say.
function slotProblem(slot, card, team) {
  if (typeof slot !== "string" || !slot.startsWith("reviewer") || !card) return null;
  const rf = teamCardFamily(card);
  const executor = team && team.executor ? team.executor : null;
  // the very same card in the execution place and a review place: it would review its own work, whatever its family
  if (executor && typeof card.profile_id === "string" && card.profile_id && executor.profile_id === card.profile_id) {
    return { code: "same_card", text: SLOT_REVIEW_SELF, why: "這張卡已經放在執行位" };
  }
  if (rf === "unknown" || rf === "other") {
    return { code: "reviewer_family_unknown", text: SLOT_REVIEW_NEEDS_DIFF,
      why: "這張卡的陣營是「共用」或不明，審查結果不算數" };
  }
  if (!executor) return null;
  const ef = teamCardFamily(executor);
  if (ef === "unknown" || ef === "other") {
    return { code: "executor_family_unknown", text: SLOT_REVIEW_NEEDS_DIFF,
      why: "執行位的陣營是「共用」或不明，審查結果不算數" };
  }
  if (ef === rf) {
    return { code: "same_family", text: SLOT_REVIEW_NEEDS_DIFF,
      why: `審查位和執行位同為 ${TEAM_FAMILY_LABEL[rf]}` };
  }
  return null;
}

// A role as the flow stores it, made from a role card. The family comes from the card's tool (claude is anthropic, codex
// is openai, shared is unknown); the revision is the one the server showed for the card. opts.keep is the role that was
// in the place before: an executor keeps its session and folder when only the card changes; opts.workdir is the folder
// to start from when there is none.
function roleFromCard(p, opts = {}) {
  const tool = p && p.model && typeof p.model.tool === "string" ? p.model.tool : "";
  const name = String((p && p.name) || (p && p.id) || "").trim();
  const role = { name: name.slice(0, TEAM_ROLE_NAME_MAX) || "未命名", family: teamFamily(tool) };
  const modelId = p && p.model && typeof p.model.model_id === "string" ? p.model.model_id : "";
  if (modelId && modelId.length <= TEAM_ROLE_NAME_MAX) role.model = modelId;
  if (p && typeof p.id === "string" && typeof p.revision === "string" && /^[0-9a-f]{64}$/.test(p.revision)
      && cardHas(TEAM_TOOL_FAMILY, tool) && name) {
    role.profile_id = p.id;
    role.profile_snapshot = { name, tool, model_id: modelId, revision: p.revision };
  }
  const keep = opts.keep && typeof opts.keep === "object" ? opts.keep : null;
  if (opts.executor) {
    if (keep && keep.session_id) role.session_id = keep.session_id;
    const wd = (keep && keep.workdir) || opts.workdir;
    if (typeof wd === "string" && wd) role.workdir = wd;
  }
  return role;
}

// The places as { planner, executor, reviewer1, reviewer2 } from a flow's roles; a place with nobody is null.
function teamSlotsFromRoles(roles) {
  const out = { planner: null, executor: null, reviewer1: null, reviewer2: null };
  if (!roles || typeof roles !== "object") return out;
  if (roles.planner) out.planner = { ...roles.planner };
  if (roles.executor) out.executor = { ...roles.executor };
  const revs = Array.isArray(roles.reviewers) ? roles.reviewers : [];
  if (revs[0]) out.reviewer1 = { ...revs[0] };
  if (revs[1]) out.reviewer2 = { ...revs[1] };
  return out;
}
const TEAM_ROLE_KEYS = ["name", "family", "model", "profile_id", "profile_snapshot"];
function teamRoleBody(entry, executor) {
  const out = {};
  for (const k of TEAM_ROLE_KEYS.concat(executor ? ["session_id", "workdir"] : [])) {
    if (entry[k] !== undefined && entry[k] !== null && entry[k] !== "") out[k] = entry[k];
  }
  return out;
}
// What is still missing for a team the server will take: a planner, an executor and at least one reviewer.
function teamMissing(slots) {
  const out = [];
  if (!slots.planner) out.push("規劃位");
  if (!slots.executor) out.push("執行位");
  if (!slots.reviewer1) out.push("審查位");
  return out;
}
// The body for the server. The empty second review place is never sent and never counts (design 3.5). null while a
// required place is empty.
function teamRolesBody(slots) {
  if (teamMissing(slots).length) return null;
  const reviewers = [slots.reviewer1, slots.reviewer2].filter(Boolean).map((r) => teamRoleBody(r, false));
  return { planner: teamRoleBody(slots.planner, false), executor: teamRoleBody(slots.executor, true), reviewers };
}
function teamProblems(slots) {
  const out = {};
  for (const key of ["reviewer1", "reviewer2"]) {
    const p = slots[key] ? slotProblem(key, slots[key], slots) : null;
    if (p) out[key] = p;
  }
  return out;
}

// Has the card moved on since it was put here? The record keeps what it was; the page only tells (design 3.5).
function teamCardState(entry, profiles) {
  if (!entry || !entry.profile_id || !entry.profile_snapshot) return { state: "manual" };
  const current = (Array.isArray(profiles) ? profiles : []).find((p) => p && p.id === entry.profile_id);
  if (!current) return { state: "gone" };
  if (typeof current.revision !== "string" || !current.revision) return { state: "unknown", current };
  return current.revision === entry.profile_snapshot.revision ? { state: "same", current } : { state: "changed", current };
}

// The draft of a task that has no flow yet: only card ids, so a deleted card simply is not there when it is read back.
function teamDraftRead(taskId, profiles, workdir) {
  const raw = store.get(TEAM_DRAFT_KEY + taskId, null);
  const out = { planner: null, executor: null, reviewer1: null, reviewer2: null };
  if (!raw || typeof raw !== "object") return out;
  for (const key of Object.keys(out)) {
    const id = raw[key];
    const p = typeof id === "string" ? (profiles || []).find((x) => x && x.id === id) : null;
    if (p) out[key] = roleFromCard(p, { executor: key === "executor", workdir });
  }
  return out;
}
function teamDraftWrite(taskId, slots) {
  const ids = {};
  for (const key of Object.keys(slots)) if (slots[key] && slots[key].profile_id) ids[key] = slots[key].profile_id;
  store.set(TEAM_DRAFT_KEY + taskId, Object.keys(ids).length ? ids : null);
}

// ---- the next steps (design 3.5) ----------------------------------------------------------------------------------
const NEXT_PHASE_STEP = { planning: "plan", awaiting_approval: "approve", implementing: "implement", needs_fix: "implement",
  in_review: "review", review_stale: "review", awaiting_merge: "merge", review_unverified: "merge", awaiting_push: null, done: null };
const NEXT_STEP_TEXT = { plan: "規劃者提出計畫", approve: "你核准計畫", risk: "你接受風險", implement: "執行者實作",
  review: "審查者檢查", merge: "你自己合併" };

// The steps of a flow, read from the phase the server already derived. A step is past, now or next by its place in the
// list only: it does not say that anything was recorded. Step 3 exists only in automatic mode. After step 6 comes the
// push, which is also yours; it is said as a line after the list because the list has six steps.
function nextSteps(flow) {
  const f = flow && typeof flow === "object" ? flow : {};
  const roles = f.roles && typeof f.roles === "object" ? f.roles : {};
  const roleName = (r) => (r && typeof r.name === "string" && r.name ? r.name : "未命名");
  const auto = Boolean(f.automation && f.automation.mode === "auto");
  const reviewers = (Array.isArray(roles.reviewers) ? roles.reviewers : []).map(roleName);
  const who = {
    plan: roleName(roles.planner), approve: "你", risk: "你", implement: roleName(roles.executor),
    review: auto ? `VBear 送審，${reviewers.join("、") || "審查者"}審查` : (reviewers.join("、") || "審查者"), merge: "你",
  };
  const turn = { ...who, review: auto ? "VBear（自動送審）" : who.review };
  const keys = ["plan", "approve", ...(auto ? ["risk"] : []), "implement", "review", "merge"];
  const phaseKey = f.phase && typeof f.phase.key === "string" ? f.phase.key : "";
  const known = cardHas(NEXT_PHASE_STEP, phaseKey);
  const currentKey = known ? NEXT_PHASE_STEP[phaseKey] : null;
  const at = currentKey ? keys.indexOf(currentKey) : -1;
  const allPast = known && !currentKey;
  const steps = keys.map((key, i) => ({
    n: i + 1, key, text: NEXT_STEP_TEXT[key], who: who[key],
    state: !known ? "next" : allPast || i < at ? "past" : i === at ? "now" : "next",
  }));
  const reason = f.phase && typeof f.phase.reason === "string" ? f.phase.reason : "";
  return { steps, current: at, known, turn: at >= 0 ? turn[keys[at]] : (phaseKey === "awaiting_push" ? "你" : null),
    reason, after: phaseKey === "awaiting_push" ? { text: "你自己 push", who: "你" } : null };
}

// ---- doing the next step from the page (P7 #2) -------------------------------------------------------------------
// What can be done for the step that is now. A step done by a role card gets a button that starts that card through the
// ordinary launch pass (the same path as a team place's own 出發 button), so nothing starts without the pass and a click.
// In manual mode VBear does not move the flow on: the sentence says that, and where to record the step.
// What was done for a step by a launch the page just made is kept as a short note: only VBear's own launch result,
// never a guess about which terminal belongs to which card.
const NEXT_STEP_ASK = { plan: "提出計畫", implement: "動手實作", review: "做審查" };
const NEXT_STEP_RECORD = { plan: "計畫已提交", implement: "執行者回報", review: "審查結果" };
const STEP_OF_SLOT = { planner: "plan", executor: "implement", reviewer1: "review", reviewer2: "review" };
const LAUNCH_MEMO_KEY = "task.launched.";
const LAUNCH_MEMO_MAX = 8;
const LAUNCH_MEMO_MS = 24 * 3600 * 1000;

function launchMemoRead(taskId, now = Date.now()) {
  const raw = store.get(LAUNCH_MEMO_KEY + taskId, []);
  return (Array.isArray(raw) ? raw : []).filter((e) => e && typeof e === "object" && typeof e.session_id === "string"
    && typeof e.step === "string" && Number.isFinite(e.at) && now - e.at >= 0 && now - e.at < LAUNCH_MEMO_MS);
}
function launchMemoAdd(taskId, entry, now = Date.now()) {
  if (typeof taskId !== "string" || !taskId || !entry || typeof entry.session_id !== "string" || !cardHas(NEXT_STEP_ASK, entry.step)) return;
  const kept = launchMemoRead(taskId, now).filter((e) => e.session_id !== entry.session_id);
  kept.push({ step: entry.step, session_id: entry.session_id, name: String(entry.name || "").slice(0, TEAM_ROLE_NAME_MAX), at: now });
  store.set(LAUNCH_MEMO_KEY + taskId, kept.slice(-LAUNCH_MEMO_MAX));
}

// -> null, or { step, ask, turn, manual, launches: [{name, profile_id}], note, record, recordWords }.
// opts.profiles: the cards as the pool has them; a card that is gone or switched off gets no button.
function nextStepAction(flow, opts = {}) {
  const ns = nextSteps(flow);
  if (!ns.known || ns.current < 0) return null;
  const step = ns.steps[ns.current];
  if (!cardHas(NEXT_STEP_ASK, step.key)) return null;
  const roles = flow.roles && typeof flow.roles === "object" ? flow.roles : {};
  const auto = Boolean(flow.automation && flow.automation.mode === "auto");
  const holders = step.key === "plan" ? [roles.planner] : step.key === "implement" ? [roles.executor]
    : (Array.isArray(roles.reviewers) ? roles.reviewers : []);
  // in automatic mode VBear starts the executor and sends the review itself; only the planner is always yours to start
  const startable = step.key === "plan" || !auto;
  const profiles = Array.isArray(opts.profiles) ? opts.profiles : null;
  const launches = !startable ? [] : holders
    .filter((r) => r && typeof r.profile_id === "string" && r.profile_id)
    .filter((r) => !profiles || profiles.some((c) => c && c.id === r.profile_id && c.enabled !== false))
    .map((r) => ({ name: String(r.name || "未命名"), profile_id: r.profile_id }));
  const recordWords = NEXT_STEP_RECORD[step.key];
  return { step: step.key, ask: NEXT_STEP_ASK[step.key], turn: ns.turn, manual: !auto, launches, recordWords,
    note: auto ? "" : `手動模式下，VBear 不會自動推進。${ns.turn} 在終端裡完成這一步後，回到這裡記錄（例如『記錄：${recordWords}』）。` };
}

// The action under the next-steps list. opts: { task, profiles, compact (the lobby's card: buttons and the note only),
// onRecord (on the flow's own page: jumps to the form; elsewhere it links to that page), onFlowPage (already there) }.
function nextStepActionNode(flow, opts = {}) {
  const act = nextStepAction(flow, opts);
  if (!act) return null;
  const taskId = opts.task && opts.task.id ? opts.task.id : flow.task_id;
  const launchHref = (l) => `#/workbench?task=${encodeURIComponent(taskId)}&profile=${encodeURIComponent(l.profile_id)}&launch=1&step=${act.step}`;
  const memo = taskId ? launchMemoRead(taskId).filter((e) => e.step === act.step) : [];
  const kids = [];
  if (act.launches.length) {
    kids.push(el("div", { class: "ns-launch row" }, act.launches.map((l) =>
      el("a", { class: "btn small primary", "data-ns": "launch", "data-profile": l.profile_id, href: launchHref(l),
        title: "先看這次出發會套用什麼，確認後才啟動；資料夾會帶入這張任務卡的" }, `讓 ${l.name} 出發`))));
  }
  if (memo.length) {
    const last = memo[memo.length - 1];
    kids.push(el("p", { class: "small ns-launched", "data-ns": "launched" },
      `已開啟 ${memo.length} 個終端；接下來在終端裡請它${act.ask}。`, " ",
      el("a", { href: `#/term/${encodeURIComponent(last.session_id)}` }, "打開終端")));
  }
  if (act.note && !opts.compact) {
    kids.push(el("p", { class: "small ns-manual", "data-ns": "manual" }, act.note, " ",
      typeof opts.onRecord === "function"
        ? el("button", { type: "button", class: "btn small", "data-ns": "record", on: { click: opts.onRecord } }, "到下方記錄")
        : opts.onFlowPage ? null      // already on the flow's page, with nothing to jump to: no link to where it is
        : el("a", { class: "btn small", "data-ns": "record", href: `#/flows/${encodeURIComponent(flow.id)}` }, "到流程頁記錄")));
  }
  return kids.length ? el("div", { class: "ns-action", "data-ns": "action" }, kids) : null;
}

function nextStepsList(flow, opts = {}) {
  const ns = nextSteps(flow);
  if (!ns.known) {
    return el("div", { class: "ns", "data-ns": "list" },
      el("p", { class: "small muted" }, "目前的階段無法對應到步驟，只顯示階段文字。"));
  }
  const items = ns.steps.map((s) => el("li", { class: `ns-step ns-${s.state}`, "data-step": s.key, "data-state": s.state,
    "aria-current": s.state === "now" ? "step" : null },
    s.state === "now" ? el("strong", null, s.text) : el("span", null, s.text),
    s.key === "risk" ? teamInfo("risk", "風險接受") : null,
    s.key === "implement" ? teamInfo("executor", "串流執行者") : null,
    el("span", { class: "ns-who small muted" }, `（${s.who}）`),
    s.state === "now" ? el("span", { class: "ns-turn tag", "data-ns": "turn" }, `輪到 ${ns.turn}`) : null,
    s.state === "now" && ns.reason ? el("div", { class: "small ns-reason" }, ns.reason) : null));
  return el("div", { class: "ns", "data-ns": "list" },
    el("ol", { class: "ns-list" }, items),
    nextStepActionNode(flow, opts),
    ns.after ? el("p", { class: "small ns-after", "data-ns": "after" }, `接下來：${ns.after.text}（輪到 ${ns.after.who}）。`,
      ns.reason ? el("span", { class: "muted" }, ` ${ns.reason}`) : null) : null);
}

// The small heads of a role card on a task card (design 3.8): who is in the team, as pixel avatars.
// compact: only the place under each avatar (the name stays in the tooltip); the board's card already names its roles.
function teamAvatars(flow, scale = 2, compact = false) {
  const roles = flow && flow.roles && typeof flow.roles === "object" ? flow.roles : null;
  if (!roles) return null;
  const list = [["規劃", roles.planner], ["執行", roles.executor],
    ...(Array.isArray(roles.reviewers) ? roles.reviewers : []).map((r, i) => [`審查${i + 1}`, r])].filter(([, r]) => r);
  return el("div", { class: compact ? "team-avatars team-avatars-compact" : "team-avatars", "data-team": "avatars" }, list.map(([label, r]) => {
    const tool = teamCardTool(r);
    return el("span", { class: "team-avatar", title: `${label}：${r.name || ""}`, "data-position": label },
      cardAvatar({ id: r.profile_id || "", model: { tool } }, scale), el("span", { class: "small" }, compact ? label : `${label}・${r.name || ""}`));
  }));
}

// ---- the board ----------------------------------------------------------------------------------------------------

// opts: { task, flow (the saved flow view, or null), profiles, catalog, gitState ("git" | "nogit" | null),
//         onSaved(flowView), onNeedCatalog }. Returns { node, state }.
function teamBoard(opts) {
  const task = opts.task;
  const profiles = Array.isArray(opts.profiles) ? opts.profiles : [];
  const catalog = opts.catalog || null;
  const cards = sortCards(profiles, catalog);
  let flow = opts.flow || null;
  let slots = flow ? teamSlotsFromRoles(flow.roles) : teamDraftRead(task.id, profiles, task.workdir);
  let dirty = false;
  let busy = false;
  let selected = null;       // a card id picked in the tray (touch: pick a card, then a place)
  let openKey = null;        // the place whose card list is open
  let query = "";
  let focusKey = null;
  const focusRefs = new Map();   // place key -> its button; "search" -> the open list's search box
  const errors = {};
  let boardError = "";
  const host = el("section", { class: "section team-board", "data-team": "board" });

  const cardById = (id) => profiles.find((p) => p && p.id === id) || null;
  const slotDef = (key) => TEAM_SLOTS.find((s) => s.key === key);
  const clearErrors = () => { for (const k of Object.keys(errors)) delete errors[k]; boardError = ""; };

  function place(key, p) {
    if (!p) return;
    const prev = slots[key];
    slots[key] = roleFromCard(p, { executor: key === "executor", keep: prev, workdir: key === "executor" ? task.workdir : undefined });
    delete errors[key];
    boardError = "";
    dirty = true;
    selected = null;
    openKey = null;
    focusKey = key;
    if (!flow) teamDraftWrite(task.id, slots);
    paint();
  }
  function clearSlot(key) {
    slots[key] = null;
    delete errors[key];
    dirty = true;
    openKey = null;
    focusKey = key;
    if (!flow) teamDraftWrite(task.id, slots);
    paint();
  }

  // The server's words name the place when they can ("planner：…", "reviewers[1]：…"); a folder or session complaint
  // belongs to the executor; anything else stays under the buttons.
  function showError(message) {
    clearErrors();
    const text = String(message || "未知錯誤");
    const m = /^(planner|executor|reviewers\[(\d)\])：/.exec(text);
    if (m) errors[m[1] === "planner" ? "planner" : m[1] === "executor" ? "executor" : `reviewer${Number(m[2]) + 1}`] = text;
    else if (/工作目錄|session/.test(text)) errors.executor = text;
    else boardError = text;
  }

  async function save() {
    const body = teamRolesBody(slots);
    if (!body || busy) return;
    busy = true;
    clearErrors();
    paint();
    try {
      const res = flow
        ? await api.post(`/api/flows/${encodeURIComponent(flow.id)}/roles`, { roles: body })
        : await api.post("/api/flows", { task_id: task.id, roles: body });
      if (!flow) store.set(TEAM_DRAFT_KEY + task.id, null);
      toast(flow ? "已儲存隊伍" : "已建立隊伍");
      busy = false;
      dirty = false;
      if (res && res.flow) { flow = res.flow; slots = teamSlotsFromRoles(flow.roles); }
      paint();
      if (opts.onSaved) opts.onSaved(res && res.flow);
    } catch (e) {
      busy = false;
      showError(e && e.message);
      paint();
    }
  }

  // the card changed since it was put here: take the current one, in that place only
  async function refreshSlot(key, current) {
    const wasDirty = dirty;
    slots[key] = roleFromCard(current, { executor: key === "executor", keep: slots[key], workdir: key === "executor" ? task.workdir : undefined });
    dirty = true;
    if (!flow) teamDraftWrite(task.id, slots);
    if (wasDirty || !flow) { toast(flow ? "已換成最新的設定；按「儲存隊伍」才會寫入" : "已換成最新的設定"); paint(); return; }
    await save();
  }

  function cardChip(p) {
    const tool = p.model && p.model.tool;
    const on = selected === p.id;
    return el("button", { type: "button", class: `ts-chip${on ? " ts-chip-on" : ""}`, "data-card": p.id, draggable: "true",
      "aria-pressed": String(on), title: "拖到位置上；或先點這張卡，再點位置",
      on: {
        click: () => { selected = on ? null : p.id; openKey = null; paint(); },
        dragstart: (e) => {
          if (e.dataTransfer) {
            try { e.dataTransfer.setData(TEAM_DRAG_TYPE, p.id); e.dataTransfer.setData("text/plain", p.id); e.dataTransfer.effectAllowed = "copy"; } catch (_) { /* some browsers refuse */ }
          }
        },
      } },
      cardAvatar(p, 2), el("span", { class: "ts-chip-name" }, p.name || p.id),
      el("span", { class: "tag" }, CARD_TOOL_SHORT[tool] || tool || "?"));
  }

  function menuFor(key) {
    const def = slotDef(key);
    const q = query.trim().toLowerCase();
    const matches = cards.filter((p) => !q || String(p.name || "").toLowerCase().includes(q));
    const search = el("input", { type: "search", class: "input", "aria-label": "用名字找角色卡", placeholder: "用名字找角色卡", value: query,
      on: { input: (e) => { query = e.target.value; focusKey = "search"; paint(); } } });
    focusRefs.set("search", search);
    const rows = matches.slice(0, TEAM_MENU_MAX).map((p) => {
      const trial = { ...slots, [key]: roleFromCard(p, { executor: key === "executor" }) };
      const problem = slotProblem(key, trial[key], trial);
      const suggested = cardPosition(p.id) === def.position;
      return el("li", null, el("button", { type: "button", class: "ts-pick", "data-pick": p.id, on: { click: () => place(key, p) } },
        cardAvatar(p, 2),
        el("span", { class: "ts-pick-body" },
          el("strong", null, p.name || p.id),
          el("span", { class: "small muted" }, `${CARD_TOOL_SHORT[p.model && p.model.tool] || "?"}${suggested ? "・你建議放這裡" : ""}${p.enabled === false ? "・已停用" : ""}`),
          problem ? el("span", { class: "small ts-pick-warn" }, "放這裡審查不算數：" + problem.why) : null)));
    });
    return el("div", { class: "ts-menu", "data-menu": key },
      el("div", { class: "small muted" }, "從角色卡池挑"), search,
      rows.length ? el("ul", { class: "ts-menu-list" }, rows) : el("p", { class: "small muted" }, cards.length ? "沒有符合的角色卡" : "角色卡池是空的，先到「角色卡池」拿幾張卡"),
      matches.length > TEAM_MENU_MAX ? el("p", { class: "small muted" }, `還有 ${matches.length - TEAM_MENU_MAX} 張，輸入名字縮小範圍`) : null);
  }

  function slotNode(def, problems) {
    const entry = slots[def.key];
    const problem = problems[def.key] || null;
    const state = teamCardState(entry, profiles);
    const err = errors[def.key] || "";
    const isOpen = openKey === def.key;
    const armed = selected !== null;
    const body = entry
      ? el("span", { class: "ts-card" },
          cardAvatar({ id: entry.profile_id || "", model: { tool: teamCardTool(entry) } }, 3),
          el("span", { class: "ts-card-text" },
            el("strong", { "data-ts": "name" }, entry.name),
            el("span", { class: "small muted" }, [CARD_TOOL_SHORT[teamCardTool(entry)] || null, TEAM_FAMILY_LABEL[entry.family] || entry.family,
              entry.model || null].filter(Boolean).join("・"))))
      : el("span", { class: "ts-empty" }, cardArt("icons", "emptySlot", 2), def.optional ? "＋ 第二位審查（選填）" : "＋ 放一張角色卡");
    const button = el("button", { type: "button", class: "ts-body", "data-act": "slot",
      "aria-expanded": String(isOpen), "aria-label": entry ? `${def.label}：${entry.name}，按 Enter 換一張` : `${def.label}：空的，按 Enter 挑一張`,
      on: { click: () => {
        if (selected) { place(def.key, cardById(selected)); return; }
        openKey = isOpen ? null : def.key; query = ""; focusKey = def.key; paint();
      } } }, body);
    focusRefs.set(def.key, button);
    const li = el("li", { class: `team-slot${entry ? " ts-filled" : " ts-vacant"}${def.optional ? " ts-optional" : ""}${armed ? " ts-armed" : ""}${problem ? " ts-bad" : ""}`,
      "data-slot": def.key, "data-state": entry ? (problem ? "problem" : "filled") : "empty",
      on: {
        dragover: (e) => { if (e.preventDefault) e.preventDefault(); },
        drop: (e) => {
          if (e.preventDefault) e.preventDefault();
          let id = "";
          try { id = e.dataTransfer ? (e.dataTransfer.getData(TEAM_DRAG_TYPE) || e.dataTransfer.getData("text/plain")) : ""; } catch (_) { id = ""; }
          const p = cardById(id);
          if (p) place(def.key, p);
        },
        keydown: (e) => { if (e.key === "Escape" && openKey === def.key) { openKey = null; focusKey = def.key; paint(); } },
      } },
      el("div", { class: "ts-head" }, el("strong", null, def.label),
        el("span", { class: "small muted" }, def.position === "reviewer" ? "要和執行位不同陣營" : `建議放「${def.short}」位的卡`)),
      button,
      entry ? el("div", { class: "ts-tools" },
        el("button", { type: "button", class: "btn small", "data-act": "clear", on: { click: () => clearSlot(def.key) } }, "拿下來"),
        // from a place, the launch check opens with this task card's folder already in it (design 3.6); not while there
        // are changes that only exist on this page, and not for a card that is gone
        entry.profile_id && state.state !== "gone" && (!flow || !dirty)
          ? el("a", { class: "btn small", "data-act": "launch", title: "先看這次出發會套用什麼，確認後才啟動；資料夾會帶入這張任務卡的",
              href: `#/workbench?task=${encodeURIComponent(task.id)}&profile=${encodeURIComponent(entry.profile_id)}&launch=1&step=${STEP_OF_SLOT[def.key]}` }, "出發") : null) : null,
      problem ? el("p", { class: "ts-problem small", "data-slot-problem": problem.code, role: "status" }, el("strong", null, "不算數："), problem.text, el("span", { class: "muted" }, `（${problem.why}）`)) : null,
      entry && state.state === "changed"
        ? el("p", { class: "ts-stale small", "data-slot-stale": "changed" },
            `${entry.profile_snapshot.name} 的設定在放上隊伍後改過了 · `,
            el("button", { type: "button", class: "btn small", "data-act": "refresh", on: { click: () => refreshSlot(def.key, state.current) } }, "更新成最新")) : null,
      entry && state.state === "gone"
        ? el("p", { class: "ts-stale small", "data-slot-stale": "gone" }, "這張角色卡已經不在角色卡池了；隊伍裡保留的是放上時的紀錄。") : null,
      entry && state.state === "manual"
        ? el("p", { class: "small muted", "data-slot-stale": "manual" }, "手動填寫的角色，沒有對應的角色卡。") : null,
      err ? el("p", { class: "ts-error small", "data-slot-error": def.key, role: "alert" }, err) : null,
      isOpen ? menuFor(def.key) : null);
    return li;
  }

  function paint() {
    focusRefs.clear();
    const problems = teamProblems(slots);
    const missing = teamMissing(slots);
    const complete = missing.length === 0;
    const noGit = opts.gitState === "nogit";
    const save1 = el("button", { type: "button", class: "btn primary", "data-act": "save", disabled: !complete || busy || (flow && !dirty),
      on: { click: save } }, busy ? "儲存中…" : flow ? "儲存隊伍" : "建立隊伍");
    const tray = cards.length
      ? el("div", { class: "ts-tray", "data-team": "tray" },
          el("div", { class: "small muted" }, "角色卡池：拖到位置上，或先點一張卡再點位置"),
          el("div", { class: "ts-chips" }, cards.slice(0, TEAM_TRAY_MAX).map(cardChip)),
          cards.length > TEAM_TRAY_MAX ? el("p", { class: "small muted" }, `還有 ${cards.length - TEAM_TRAY_MAX} 張，點位置用名字找`) : null)
      : el("div", { class: "ts-tray" }, el("p", { class: "small muted" }, "角色卡池是空的。"),
          el("a", { class: "btn small", href: "#/team" }, "到角色卡池拿卡"));
    setKids(host,
      sectionHead("隊伍", flow ? "任務卡上的隊伍；換掉卡之後按「儲存隊伍」才會寫入。" : "把角色卡放上來：規劃、執行、審查各一位（第二位審查選填）。"),
      selected ? el("p", { class: "small ts-armed-note", role: "status" }, `已拿起「${(cardById(selected) || {}).name || ""}」，點一個位置放下去。`,
        el("button", { type: "button", class: "btn small", on: { click: () => { selected = null; paint(); } } }, "放開")) : null,
      el("ul", { class: "team-slots" }, TEAM_SLOTS.map((d) => slotNode(d, problems))),
      noGit ? el("p", { class: "small ts-nogit", "data-team": "nogit" }, badge(NO_GIT_BADGE, "b-warn", NO_GIT_NOTE), " ", NO_GIT_NOTE) : null,
      tray,
      el("div", { class: "ts-actions" }, save1,
        !complete ? el("span", { class: "small muted", "data-team": "missing" }, `還差：${missing.join("、")}`) : null,
        flow && !dirty ? el("span", { class: "small muted" }, "沒有未儲存的改動") : null),
      el("p", { class: "small muted" }, flow ? TEAM_SAVE_NOTE : "建立之後，這張任務卡就有流程；沒放滿三個必填位置之前不會送出。"),
      boardError ? el("p", { class: "ts-error small", "data-team": "error", role: "alert" }, boardError) : null);
    if (focusKey) {
      const node = focusRefs.get(focusKey);
      focusKey = null;
      if (node && typeof node.focus === "function") node.focus();
    }
  }

  paint();
  return { node: host, state: { get slots() { return slots; }, get dirty() { return dirty; }, get flow() { return flow; } },
    place, save, clearSlot };
}

// The team of one task card, loaded on its own: the flow of this task (if any), the cards, and whether the folder has
// version history (the review of a folder without it never counts; the board says so beside the review places).
// opts may carry flow, profiles, catalog to skip a request the caller already made.
function teamSection(task, opts = {}) {
  const box = el("div", { class: "team-section", "data-team": "section" }, el("p", { class: "small muted" }, "讀取隊伍…"));
  const gone = typeof opts.gone === "function" ? opts.gone : () => false;
  let preset = opts;      // what the caller already has is used once; a reload after a save asks the server again
  async function load() {
    const have = preset;
    preset = {};
    const [flowsRes, profilesRes, catalog, info] = await Promise.all([
      have.flow !== undefined ? { flows: have.flow ? [have.flow] : [] } : api.get("/api/flows").catch((e) => ({ error: e.message, flows: [] })),
      have.profiles ? { profiles: have.profiles } : api.get("/api/agent-profiles").catch((e) => ({ error: e.message, profiles: [] })),
      have.catalog !== undefined ? have.catalog : api.get("/api/agent-builder/catalog").then((r) => (r && r.ok ? r : null)).catch(() => null),
      task.workdir ? api.get(folderInspectUrl(task.workdir)).catch(() => null) : null,
    ]);
    if (gone()) return;
    const flow = ((flowsRes && flowsRes.flows) || []).find((f) => f.task_id === task.id) || null;
    const gitState = info && info.exists !== false ? (folderVerdict(info).noGit ? "nogit" : "git") : null;
    const board = teamBoard({ task, flow, profiles: (profilesRes && profilesRes.profiles) || [], catalog, gitState, onSaved: () => { load(); if (opts.onSaved) opts.onSaved(); } });
    setKids(box,
      flowsRes && flowsRes.error ? notice("warn", "讀不到流程：" + flowsRes.error) : null,
      profilesRes && profilesRes.error ? notice("warn", "讀不到角色卡：" + profilesRes.error) : null,
      flow ? el("section", { class: "section", "data-team": "next" }, sectionHead("下一步", flow.phase ? flow.phase.label : null,
        opts.hideOpen ? null : el("a", { class: "btn small", href: `#/flows/${encodeURIComponent(flow.id)}` }, "打開流程")),
        nextStepsList(flow, { task, profiles: (profilesRes && profilesRes.profiles) || [], onRecord: opts.onRecord, onFlowPage: Boolean(opts.hideOpen) })) : null,
      board.node);
  }
  load().catch((e) => setKids(box, notice("bad", "讀不到隊伍：" + (e && e.message || ""))));
  return box;
}

// "放上任務卡" on a role card: pick the task card, pick the place, put it there. A task that already has a flow is
// saved at once (the dialog is the confirmation, and it shows what the save does); one that has none gets a draft that
// the board on its own page finishes.
function openPlaceDialog(p, opts = {}) {
  const profiles = Array.isArray(opts.profiles) && opts.profiles.length ? opts.profiles : [p];
  const st = { tasks: null, flows: [], taskId: null, slot: null, busy: false, error: "", loadError: "" };
  const titleId = "place-dialog-title";
  const body = el("div", { class: "cw-body" });
  const foot = el("div", { class: "modal-actions cw-foot" });
  const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    el("div", { class: "modal-box cw-box" }, el("h2", { id: titleId }, `放上任務卡：${p.name || p.id}`), body, foot));
  document.body.append(modal);
  const close = withModalA11y(modal, () => modal.remove());

  const task = () => (st.tasks || []).find((t) => t.id === st.taskId) || null;
  const flowOf = (t) => st.flows.find((f) => t && f.task_id === t.id) || null;
  const slotsOf = (t) => {
    const f = flowOf(t);
    return f ? teamSlotsFromRoles(f.roles) : teamDraftRead(t.id, profiles, t.workdir);
  };

  async function go() {
    const t = task();
    if (!t || !st.slot || st.busy) return;
    const slots = slotsOf(t);
    slots[st.slot] = roleFromCard(p, { executor: st.slot === "executor", keep: slots[st.slot], workdir: t.workdir });
    const flow = flowOf(t);
    st.error = "";
    if (!flow) {
      teamDraftWrite(t.id, slots);
      const missing = teamMissing(slots);
      toast(missing.length ? `已放進「${t.title || t.id}」的草稿，還差：${missing.join("、")}` : "三個必填位置都有卡了，到任務卡上按「建立隊伍」");
      close();
      location.hash = `#/workbench?task=${encodeURIComponent(t.id)}`;
      return;
    }
    st.busy = true;
    draw();
    try {
      await api.post(`/api/flows/${encodeURIComponent(flow.id)}/roles`, { roles: teamRolesBody(slots) });
      toast(`已放上「${t.title || t.id}」的${(TEAM_SLOTS.find((s) => s.key === st.slot) || {}).label || "位置"}`);
      close();
      if (opts.onPlaced) opts.onPlaced();
      location.hash = `#/workbench?task=${encodeURIComponent(t.id)}`;
    } catch (e) {
      st.busy = false;
      st.error = e && e.message ? e.message : "未知錯誤";
      draw();
    }
  }

  function draw() {
    const t = task();
    const open = (st.tasks || []);
    const rows = open.map((x) => el("li", null, el("button", { type: "button", class: "fp-item", "data-place-task": x.id, "aria-pressed": String(x.id === st.taskId),
      on: { click: () => { st.taskId = x.id; st.slot = null; st.error = ""; draw(); } } },
      el("strong", null, x.title || "（沒有名稱）"),
      el("span", { class: "small muted fp-path" }, x.workdir ? `${folderBaseName(x.workdir)}・${x.workdir}` : "還沒有資料夾"),
      el("span", { class: "small" }, flowOf(x) ? "已有隊伍，放上去會直接儲存" : "還沒有隊伍，會先放進草稿"))));
    const slots = t ? slotsOf(t) : null;
    const slotRows = t ? TEAM_SLOTS.map((d) => {
      const there = slots[d.key];
      const trial = { ...slots, [d.key]: roleFromCard(p, { executor: d.key === "executor" }) };
      const problem = slotProblem(d.key, trial[d.key], trial);
      return el("li", null, el("button", { type: "button", class: "fp-item", "data-place-slot": d.key, "aria-pressed": String(d.key === st.slot),
        on: { click: () => { st.slot = d.key; st.error = ""; draw(); } } },
        el("strong", null, d.label),
        el("span", { class: "small muted" }, there ? `現在是「${there.name}」，會換成這張` : "目前是空的"),
        problem ? el("span", { class: "small ts-pick-warn" }, `${problem.text}（${problem.why}）`) : null));
    }) : [];
    setKids(body,
      el("p", { class: "small muted" }, "挑一張任務卡，再挑它的一個位置。放上去只是把這張卡的名字、陣營和模型記進隊伍，不會啟動任何東西。"),
      st.loadError ? notice("bad", st.loadError) : null,
      st.tasks === null ? el("p", { class: "small muted" }, "讀取任務卡…")
        : open.length ? el("ul", { class: "fp-items", "data-place": "tasks" }, rows)
          : emptyState("沒有未結案的任務卡", "先到大廳按「＋ 任務卡（導入專案）」，挑一個資料夾。"),
      t ? el("div", { "data-place": "slots" }, el("h3", null, "放在哪個位置"), el("ul", { class: "fp-items ts-slotlist" }, slotRows)) : null,
      t && flowOf(t) ? el("p", { class: "small muted" }, TEAM_SAVE_NOTE) : null,
      st.error ? el("p", { class: "ts-error small", "data-place": "error", role: "alert" }, st.error) : null);
    const go1 = el("button", { type: "button", class: "btn primary", "data-act": "place", disabled: !t || !st.slot || st.busy, on: { click: go } },
      st.busy ? "放上去…" : "放上去");
    setKids(foot, el("button", { type: "button", class: "btn", on: { click: close } }, "取消"), go1);
  }
  draw();
  Promise.all([api.get("/api/tasks"), api.get("/api/flows").catch(() => ({ flows: [] }))]).then(([tr, fr]) => {
    st.tasks = ((tr && tr.tasks) || []).filter((x) => x && x.status !== "closed" && x.status !== "handed_off");
    st.flows = (fr && fr.flows) || [];
    if (opts.taskId && st.tasks.some((x) => x.id === opts.taskId)) st.taskId = opts.taskId;
    draw();
  }).catch((e) => { st.tasks = []; st.loadError = "讀不到任務卡：" + (e && e.message || ""); draw(); });
  return { modal, close, state: st };
}

// One line for a flow's next step, for the front of a task card: 「下一步：執行者實作（輪到 工匠）」.
function nextStepSummary(flow) {
  const ns = nextSteps(flow);
  if (!ns.known) return "";
  if (ns.current >= 0) return `下一步：${ns.steps[ns.current].text}（輪到 ${ns.turn}）`;
  if (ns.after) return `下一步：${ns.after.text}（輪到 ${ns.after.who}）`;
  return "這個流程的步驟都走完了";
}

// Is the task card linked to the terminal that is open? Only a chosen terminal can be linked to: with none chosen the
// answer is "none", never "linked" (null === null must not read as a link). The link is a tracking record only.
const TRACKING_NOTE = "追蹤關聯：任務卡和終端只是在主控台裡互相記一筆，不會把任務卡的內容送進終端。";
const TRACKING_RESTART_NOTE = "提醒：改了任務卡的內容之後，要讓角色讀到新內容，必須重新啟動角色（新開一個終端）。";
function taskTerminalLink(task, paneId) {
  if (typeof paneId !== "string" || !paneId) return { state: "none", text: "目前沒有可關聯的終端" };
  if (task && task.associated_pane_id === paneId) return { state: "linked", text: "已與目前的終端關聯（僅追蹤記錄）" };
  return { state: "unlinked", text: "尚未與目前的終端關聯" };
}

// ---------- task cards are folders (design card-play 3.6) ---------------------------------------------------
// One task card is one folder. What is known about the folder comes from GET /api/folders/inspect, which is
// read-only on the server (a few stats and the repository's HEAD, no git process, no walk). Nothing here writes into
// a folder. Terminals are counted by their working directory only: nothing says which role card opened one.

const NO_GIT_BADGE = "沒有版本紀錄";
const NO_GIT_NOTE = "這個資料夾還沒有版本紀錄（git）。任務卡可以建立，也能從這裡出發；但隊伍的審查結果要綁定 commit，在這個資料夾裡不會算數，合併關卡也用不了。";
const FOLDER_BROWSER_NOTE = "瀏覽器拿不到完整路徑，請從清單選或貼上。";
const FOLDER_FINDER_TIP = "在 Finder 對資料夾按右鍵，按住 Option，選『拷貝\"…\"為路徑名稱』，再貼到這裡";
const FOLDER_TERMINAL_NOTE = "只依終端目前的工作目錄比對，只含 VBear 認得的 Claude Code、Codex 終端；不代表它們是哪張角色卡開的。";
const FOLDER_REFUSED_MESSAGE = "這個位置不能當成專案";
// Mirrors vbear/folders.py SENSITIVE_HOME_DIRS (a test keeps the two equal): only used to leave such places out of the
// lists of folders; the server is the one that refuses them.
const FOLDER_REFUSED_HOME_DIRS = [".ssh", ".gnupg", ".aws", ".config", ".vbear", ".claude", ".codex", ".gemini", "Library"];
const FOLDER_SEEN_MAX = 24;
const FOLDER_RECENT_MAX = 10;
const FOLDER_OPEN_TASK_MAX = 6;

// "~" and "~/x" in the pasted text mean the home directory; the server only takes absolute paths.
function expandHome(text, home) {
  const t = String(text === undefined || text === null ? "" : text).trim();
  if (typeof home !== "string" || !home) return t;
  if (t === "~") return home;
  if (t.startsWith("~/")) return home.replace(/\/+$/, "") + t.slice(1);
  return t;
}

// Does pasted text look like one absolute path (or "~/…")? Then it is checked at once; anything else waits for the button.
// Only a look at the text: the server is the one that judges the path.
function folderLooksLikePath(text) {
  if (typeof text !== "string") return false;
  const t = text.trim();
  if (!t || t.length > 1024 || /[\u0000-\u001f]/.test(t)) return false;
  return t.startsWith("/") || t.startsWith("~/") || t === "~";
}

function folderBaseName(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : String(path || "");
}

function folderRefusedPath(path, home) {
  if (typeof path !== "string" || typeof home !== "string" || !home) return false;
  const base = home.replace(/\/+$/, "");
  if (path === base) return true;
  return FOLDER_REFUSED_HOME_DIRS.some((d) => {
    const bad = `${base}/${d}`.toLowerCase();
    const low = path.toLowerCase();
    return low === bad || low.startsWith(bad + "/");
  });
}

// The three places a folder can come from (design 3.6 step 1): projects VBear saw on this computer (the index's
// projects, with the basis it gives), folders used recently (the config's recent_folders), and a pasted path.
function folderSources(live, conf) {
  const L = live && typeof live === "object" ? live : {};
  const home = typeof L.home === "string" ? L.home : "";
  const seen = [];
  for (const p of Array.isArray(L.projects) ? L.projects : []) {
    if (!p || typeof p.path !== "string" || !p.path.startsWith("/") || p.path === home) continue;
    if (p.project_id === "home" || p.project_id === "unknown" || folderRefusedPath(p.path, home)) continue;
    if (seen.some((s) => s.path === p.path)) continue;
    seen.push({ name: String(p.name || folderBaseName(p.path)), path: p.path, basis: String(p.basis || "") });
    if (seen.length >= FOLDER_SEEN_MAX) break;
  }
  const recent = [];
  for (const path of conf && Array.isArray(conf.recent_folders) ? conf.recent_folders : []) {
    if (typeof path !== "string" || !path.startsWith("/") || recent.some((r) => r.path === path)) continue;
    recent.push({ name: folderBaseName(path), path });
    if (recent.length >= FOLDER_RECENT_MAX) break;
  }
  return { seen, recent };
}

// "1 個等你回覆、1 個工作中、1 個已結束": the statuses the live view already gives, counted.
function folderTerminalStatusText(items) {
  const counts = new Map();
  for (const it of Array.isArray(items) ? items : []) {
    const key = it && Object.prototype.hasOwnProperty.call(STATUS, it.status) ? it.status : "unknown";
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return Object.keys(STATUS_ORDER).filter((k) => counts.has(k)).map((k) => `${counts.get(k)} 個${STATUS[k][0]}`).join("、");
}

// The headline for the terminals of a folder: a count by working directory, never a claim about what they do.
function folderTerminalHeadline(terminals) {
  if (!terminals || terminals.known !== true) return "這個資料夾的終端數暫時讀不到";
  return `這個資料夾目前有 ${terminals.count} 個終端`;
}

// What the folder is, as far as the answer shows: usable (an existing folder) or the reason it is not.
function folderVerdict(info) {
  if (!info || info.ok !== true) return { usable: false, kind: "error", text: "無法檢查這個資料夾" };
  if (!info.exists) return { usable: false, kind: "missing", text: "找不到這個資料夾" };
  if (!info.is_dir) return { usable: false, kind: "notdir", text: "這不是資料夾" };
  const git = info.git || {};
  return { usable: true, kind: git.is_repo ? "git" : "nogit", noGit: !git.is_repo, text: "" };
}

function folderGitLine(git) {
  if (!git || !git.is_repo) return null;
  if (!git.commit) return `已找到 git 儲存庫，但讀不到目前的版本：${git.error || "原因不明"}`;
  const branch = git.branch ? `分支 ${git.branch}` : "不在任何分支上（HEAD 分離）";
  return `${branch} · HEAD ${git.short || String(git.commit).slice(0, 8)}`;
}

function folderOpenTasks(info) {
  const t = info && info.tasks;
  return t && t.known === true && Array.isArray(t.items) ? t.items : [];
}

// A native folder chooser exists only in the app window (WKWebView message handler vbearPickFolder). The page asks
// with a short request id and hears back through window.__vbearFolderPicked; the path it gets is only text, and is
// checked by the server (inspect) like any other.
let folderPickSeq = 0;
const folderPickPending = new Map();
function folderBridge() {
  try {
    const h = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.vbearPickFolder;
    return h && typeof h.postMessage === "function" ? h : null;
  } catch (_) { return null; }
}
function nativeFolderPick() {
  const bridge = folderBridge();
  if (!bridge) return null;
  return () => new Promise((resolve) => {
    const requestId = `pick-${Date.now().toString(36)}-${(++folderPickSeq).toString(36)}`;
    folderPickPending.set(requestId, resolve);
    try { bridge.postMessage({ requestId }); } catch (_) { folderPickPending.delete(requestId); resolve({ status: "cancel" }); }
  });
}
function folderPicked(reply) {
  if (!reply || typeof reply !== "object" || typeof reply.requestId !== "string") return;
  const done = folderPickPending.get(reply.requestId);
  if (!done) return;                        // not an answer to anything this page asked
  folderPickPending.delete(reply.requestId);
  const status = reply.status === "ok" || reply.status === "busy" ? reply.status : "cancel";
  const path = status === "ok" && typeof reply.path === "string" && reply.path.length <= 1024 ? reply.path : "";
  done(status === "ok" && !path ? { status: "cancel" } : { status, path });
}
if (typeof window !== "undefined") window.__vbearFolderPicked = folderPicked;

function folderInspectUrl(path) { return `/api/folders/inspect?path=${encodeURIComponent(path)}`; }

// The facts about a folder, as a list. Terminals open into a list of statuses; nothing here says what they work on.
function folderFacts(info) {
  const v = folderVerdict(info);
  if (!v.usable) return notice("warn", v.text);
  const git = info.git || {};
  const rows = [];
  rows.push(el("dt", null, "資料夾"), el("dd", null, el("strong", null, info.name || folderBaseName(info.path)),
    el("div", { class: "small mono fp-path" }, info.path)));
  rows.push(el("dt", null, "版本紀錄"), el("dd", null, v.noGit
    ? [badge(NO_GIT_BADGE, "b-warn", NO_GIT_NOTE), el("p", { class: "small muted fp-nogit" }, NO_GIT_NOTE)]
    : el("span", null, folderGitLine(git))));
  rows.push(el("dt", null, "專案技能"), el("dd", null, info.project_skill_count === null || info.project_skill_count === undefined
    ? "技能索引還沒載入，數量未知" : `${info.project_skill_count} 張`));
  const term = info.terminals || {};
  const termList = term.known === true && term.count > 0
    ? el("details", { class: "fp-terms" }, el("summary", null, "各是什麼狀態"),
        el("p", { class: "small" }, folderTerminalStatusText(term.items) + (term.items.length < term.count ? `（只列出前 ${term.items.length} 個的狀態）` : "")),
        el("ul", { class: "small fp-term-list" }, term.items.map((t) => el("li", null,
          badge((STATUS[t.status] || STATUS.unknown)[0], (STATUS[t.status] || STATUS.unknown)[1]),
          t.title ? ` ${t.title}` : ""))))
    : null;
  rows.push(el("dt", null, "終端"), el("dd", null, folderTerminalHeadline(term), termList,
    el("p", { class: "small muted" }, FOLDER_TERMINAL_NOTE)));
  const open = folderOpenTasks(info);
  rows.push(el("dt", null, "未結案的任務卡"), el("dd", null, info.tasks && info.tasks.known === true
    ? (open.length ? open.map((t) => el("div", null, t.title || t.id)) : "沒有")
    : "暫時讀不到任務卡"));
  return el("dl", { class: "kv fp-facts" }, rows);
}

// The picker: three ways to a folder, then the facts about the one chosen. The dialog that hosts it learns each
// answer through `onResult(info, helpers)` (info is null while there is no usable answer) and keeps its buttons in
// its own footer, so they stay in view; `renderNote(info)` may add a sentence under the facts. The picker itself
// never creates or saves anything.
function folderPicker(opts) {
  const live = opts.live || D.live || {};
  const home = typeof live.home === "string" ? live.home : "";
  const lists = el("div", { class: "fp-lists" });
  const result = el("div", { class: "fp-result", "aria-live": "polite" });
  const input = el("input", { type: "text", class: "input mono", "aria-label": "資料夾的絕對路徑", autocomplete: "off",
    placeholder: `貼上資料夾的路徑，例如 ${home || "/Users/you"}/projects/demo` });
  let newest = 0;                           // only the newest answer is drawn
  let lastChecked = "";                     // a pasted path is checked once, not again for the same text
  const hints = el("div", { class: "fp-hints" });
  let sourcesEmpty = false;

  function list(title, items, withBasis) {
    return el("section", { class: "fp-list" }, el("h3", { class: "fp-h" }, title),
      items.length ? el("ul", { class: "fp-items" }, items.map((it) => el("li", null,
        el("button", { type: "button", class: "fp-item", "data-path": it.path,
          on: { click: () => inspect(it.path) } },
          el("strong", null, it.name), el("span", { class: "small mono fp-path" }, it.path),
          withBasis && it.basis ? el("span", { class: "small muted" }, `依據：${it.basis}`) : null))))
        : el("p", { class: "small muted" }, "沒有"));
  }

  async function inspect(raw) {
    const mine = ++newest;
    const path = expandHome(raw, home);
    if (!path) { setKids(result); report(null); return; }
    input.value = path;
    lastChecked = path;
    setKids(result, el("p", { class: "small muted" }, "檢查中…"));
    report(null);
    let info = null;
    let problem = "";
    try { info = await api.get(folderInspectUrl(path)); }
    catch (e) { problem = e && e.message ? e.message : "無法檢查這個資料夾"; }
    if (mine !== newest) return;
    if (problem) { setKids(result, notice("bad", problem)); return; }
    const v = folderVerdict(info);
    setKids(result, folderFacts(info), v.usable && opts.renderNote ? opts.renderNote(info) : null);
    report(v.usable ? info : null);
    if (result.scrollIntoView) result.scrollIntoView({ block: "nearest" });
  }
  // "檢查" is the main button until there is a usable answer; then the dialog's own next button takes over
  function report(info) {
    if (checkBtn) checkBtn.classList.toggle("primary", !info);
    if (opts.onResult) opts.onResult(info, { inspect, clear });
  }
  function clear() { newest++; input.value = ""; lastChecked = ""; setKids(result); report(null); input.focus(); }
  // The config (recent folders) arrives after the dialog is open; the lists are drawn again with it.
  function setConf(conf) {
    const sources = folderSources(live, conf);
    sourcesEmpty = sources.seen.length === 0 && sources.recent.length === 0;
    setKids(lists, list("VBear 在你電腦上看到的專案", sources.seen, true), list("最近用過", sources.recent, false));
    drawHints();
  }
  // Right beside the box: how to get a folder's path when both lists are empty, and why a browser cannot pick one.
  function drawHints() {
    setKids(hints,
      sourcesEmpty ? el("p", { class: "small fp-finder-tip", "data-fp": "finder-tip" }, FOLDER_FINDER_TIP) : null,
      native ? null : el("p", { class: "small muted fp-browser-note", "data-fp": "browser-note" }, FOLDER_BROWSER_NOTE));
  }
  let checkBtn = null;
  const native = nativeFolderPick();
  setConf(opts.conf);

  const pickBtn = native ? el("button", { type: "button", class: "btn", on: { click: async () => {
    pickBtn.disabled = true;
    try {
      const r = await native();
      if (r.status === "ok") inspect(r.path);
      else if (r.status === "busy") toast("選擇資料夾的視窗已經開著了");
    } finally { pickBtn.disabled = false; }
  } } }, "選擇資料夾…") : null;
  const check = () => inspect(input.value);
  checkBtn = el("button", { type: "button", class: "btn primary", "data-act": "check", on: { click: check } }, "檢查");
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); check(); } });
  // a pasted path is read after the box has taken it; once, and only when it looks like an absolute path
  input.addEventListener("paste", () => {
    setTimeout(() => {
      const v = input.value.trim();
      if (folderLooksLikePath(v) && v !== lastChecked) inspect(v);
    }, 0);
  });

  const node = el("div", { class: "fp" },
    lists,
    el("section", { class: "fp-list" }, el("h3", { class: "fp-h" }, "貼上路徑"),
      el("div", { class: "row fp-paste" }, input, checkBtn, pickBtn),
      hints),
    result);
  if (opts.initialPath) inspect(opts.initialPath);
  return { node, inspect, clear, setConf, input, checkBtn };
}

// A dialog that only picks a folder (the launch check, a task card that has no folder yet).
function openFolderDialog(opts) {
  const titleId = "folder-dialog-title";
  let close = () => {};
  const foot = el("div", { class: "modal-actions cw-foot" });
  const cancel = el("button", { type: "button", class: "btn", on: { click: () => close() } }, "取消");
  setKids(foot, cancel);
  const picker = folderPicker({ onResult: (info) => {
    setKids(foot, cancel, info ? el("button", { type: "button", class: "btn primary", "data-act": "use", on: { click: async () => {
      try { await opts.onUse(info.path, info); close(); } catch (e) { toast((opts.failure || "無法使用這個資料夾") + "：" + e.message); }
    } } }, opts.useLabel || "使用這個資料夾") : null);
  } });
  const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    el("div", { class: "modal-box cw-box" },
      el("h2", { id: titleId }, opts.title || "挑資料夾"),
      el("div", { class: "cw-body" }, picker.node),
      foot));
  document.body.append(modal);
  close = withModalA11y(modal, () => modal.remove());
  picker.input.focus();
  api.get("/api/config").then((r) => picker.setConf(r && r.config)).catch(() => {});
  return { modal, picker, close: () => close() };
}

// Import a project: pick a folder, see what is in it, then fill in the card. A folder that already has an unfinished
// card offers that card first; a folder without git history is allowed, and says what that costs.
function openImportProject(opts = {}) {
  let templates = {};
  const st = { step: 1, info: null, title: "", goal: "", template: "custom", more: {}, busy: false };
  const titleId = "import-project-title";
  const body = el("div", { class: "cw-body" });
  const foot = el("div", { class: "modal-actions cw-foot" });
  const stepper = el("ol", { class: "cw-steps", "aria-label": "步驟" });
  const modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    el("div", { class: "modal-box cw-box" }, el("h2", { id: titleId, class: "cw-title-icon" }, cardArt("icons", "importProject", 2), "新任務卡：導入專案"), stepper, body, foot));
  document.body.append(modal);
  const close = withModalA11y(modal, () => modal.remove());
  const STEPS = ["挑資料夾", "填寫任務卡"];

  function drawStepper() {
    setKids(stepper, STEPS.map((t, i) => el("li", { class: i + 1 === st.step ? "cw-on" : (i + 1 < st.step ? "cw-done" : "") },
      el("span", { class: "cw-step", "aria-current": i + 1 === st.step ? "step" : null, "aria-label": `第 ${i + 1} 步，共 ${STEPS.length} 步：${t}` },
        el("span", { class: "cw-step-n", "aria-hidden": "true" }, String(i + 1)), t))));
  }

  function openCard(id) {
    close();
    if (opts.onOpenTask) opts.onOpenTask(id);
    else location.hash = `#/workbench?task=${encodeURIComponent(id)}`;
  }

  let found = null;            // the usable answer about the chosen folder, with the helpers of the picker
  const footStep1 = () => {
    if (!found) return [el("button", { type: "button", class: "btn", on: { click: close } }, "取消")];
    const { info, helpers } = found;
    const v = folderVerdict(info);
    const open = folderOpenTasks(info);
    const go = () => { st.info = info; st.title = st.title || info.name || ""; st.step = 2; draw(); };
    const buttons = [el("button", { type: "button", class: "btn", on: { click: close } }, "取消")];
    if (open.length) {
      buttons.push(el("button", { type: "button", class: "btn primary", "data-act": "open-card", on: { click: () => openCard(open[0].id) } },
        open.length === 1 ? "打開那張卡" : `打開那張卡（${open[0].title || open[0].id}）`));
      for (const t of open.slice(1, FOLDER_OPEN_TASK_MAX)) {
        buttons.push(el("button", { type: "button", class: "btn", "data-act": "open-card-more", on: { click: () => openCard(t.id) } }, `打開「${t.title || t.id}」`));
      }
      buttons.push(el("button", { type: "button", class: "btn", "data-act": "new-anyway", on: { click: go } }, "仍要建一張新的"));
    } else {
      buttons.push(el("button", { type: "button", class: "btn primary", "data-act": "next", on: { click: go } }, v.noGit ? "仍要建立" : "下一步：填寫任務卡"));
    }
    buttons.push(el("button", { type: "button", class: "btn", "data-act": "change", on: { click: () => helpers.clear() } }, "換資料夾"));
    return buttons;
  };
  const picker = folderPicker({ initialPath: opts.startPath || "",
    renderNote: (info) => folderOpenTasks(info).length
      ? notice("info", `這個資料夾已經有 ${folderOpenTasks(info).length} 張未結案的任務卡。要接著做，請打開那張卡。`) : null,
    onResult: (info, helpers) => { found = info ? { info, helpers } : null; if (st.step === 1) setKids(foot, footStep1()); } });

  function field(label, control) { return el("label", { class: "cw-field" }, el("span", null, label), control); }

  function stepTwo() {
    const info = st.info;
    const title = el("input", { type: "text", value: st.title, required: true, "aria-label": "任務標題", placeholder: "這張任務卡要做什麼" });
    title.addEventListener("input", () => { st.title = title.value; });
    const goal = el("textarea", { rows: "3", placeholder: "完成這張任務卡的主要目標（選填）" }, st.goal);
    goal.addEventListener("input", () => { st.goal = goal.value; });
    const lines = ["scope", "out_of_scope", "deliverables", "acceptance_criteria", "evidence"];
    const LABELS = { scope: "範圍（每行一項）", out_of_scope: "範圍外（每行一項）", deliverables: "交付物（每行一項）",
      acceptance_criteria: "驗收條件（每行一項）", evidence: "實測證據（每行一項）" };
    const areas = {};
    for (const k of lines) {
      areas[k] = el("textarea", { rows: "2" }, st.more[k] || "");
      areas[k].addEventListener("input", () => { st.more[k] = areas[k].value; });
    }
    const tmpl = el("select", { "aria-label": "任務範本" }, Object.keys(templates).map((k) =>
      el("option", { value: k, selected: k === st.template }, String((templates[k] && templates[k].title) || k))));
    tmpl.addEventListener("change", () => {
      st.template = tmpl.value;
      const t = templates[tmpl.value] || {};
      if (t.goal) { st.goal = t.goal; goal.value = t.goal; }
      for (const k of lines) if (Array.isArray(t[k])) { st.more[k] = t[k].join("\n"); areas[k].value = st.more[k]; }
    });
    setKids(body,
      el("div", { class: "notice info" }, el("span", { class: "ico", "aria-hidden": "true" }, "i"), el("div", null,
        el("strong", null, info.name || folderBaseName(info.path)), " ", el("span", { class: "small mono" }, info.path),
        folderVerdict(info).noGit ? el("div", null, badge(NO_GIT_BADGE, "b-warn", NO_GIT_NOTE), el("p", { class: "small" }, NO_GIT_NOTE)) : null)),
      field("任務標題 *", title), field("目標", goal),
      el("details", { class: "cw-details" }, el("summary", null, "更多"),
        el("div", { class: "cw-body" }, field("任務範本", tmpl), lines.map((k) => field(LABELS[k], areas[k])))));
    const create = el("button", { type: "button", class: "btn primary", "data-act": "create", on: { click: submit } }, "建立任務卡");
    create.disabled = st.busy;
    setKids(foot, el("button", { type: "button", class: "btn", on: { click: close } }, "取消"),
      el("button", { type: "button", class: "btn", "data-act": "back", on: { click: () => { st.step = 1; draw(); } } }, "上一步"), create);
    title.focus();

    async function submit() {
      const text = st.title.trim();
      if (!text) { toast("請填寫任務標題"); title.focus(); return; }
      st.busy = true;
      create.disabled = true;
      try {
        const payload = { title: text, template: st.template, goal: st.goal.trim(), workdir: st.info.path,
          associated_pane_id: opts.paneId || null };
        for (const k of lines) payload[k] = (st.more[k] || "").trim();
        const res = await api.post("/api/tasks", payload);
        toast("任務卡已建立");
        close();
        if (opts.onCreated) opts.onCreated(res.task);
      } catch (e) {
        toast("建立失敗：" + e.message);
        st.busy = false;
        create.disabled = false;
      }
    }
  }

  function draw() {
    drawStepper();
    if (st.step === 1) {
      setKids(body, el("p", { class: "small muted" }, "一張任務卡就是一個資料夾。挑一個你電腦上現有的專案，VBear 只會讀它的基本資訊，不會寫入、也不會在裡面執行 git。"), picker.node);
      setKids(foot, footStep1());
    } else {
      stepTwo();
    }
  }
  draw();
  picker.input.focus();
  api.get("/api/config").then((r) => picker.setConf(r && r.config)).catch(() => {});
  api.get("/api/task-templates").then((r) => {
    if (r && r.templates && typeof r.templates === "object") { templates = r.templates; if (st.step === 2) draw(); }
  }).catch(() => {});
  return { modal, close, picker, state: st };
}

// The front of a task card's folder: name and path at once, then the facts when the server has answered.
// A card made before folders were required has none; it says so and offers to pick one.
function taskFolderBlock(task, opts = {}) {
  const box = el("div", { class: "tf-block" });
  if (!task.workdir) {
    setKids(box, el("p", { class: "small tf-none" }, "還沒有資料夾 · ",
      el("button", { type: "button", class: "btn small", "data-act": "pick-folder", on: { click: () => openFolderDialog({
        title: `選資料夾：${task.title || task.id}`, useLabel: "設為這張任務卡的資料夾",
        onUse: async (path) => {
          const res = await api.post(`/api/tasks/${encodeURIComponent(task.id)}`, { workdir: path });
          if (opts.onChanged) opts.onChanged(res.task);
        } }) } }, "選資料夾")));
    return box;
  }
  const head = el("div", { class: "tf-head" }, cardArt("icons", "taskFolder", 2),
    el("div", { class: "tf-name" }, el("strong", null, folderBaseName(task.workdir)), el("span", { class: "small mono fp-path" }, task.workdir)));
  const detail = el("div", { class: "tf-detail small muted" }, "讀取資料夾資訊…");
  setKids(box, head, detail);
  api.get(folderInspectUrl(task.workdir)).then((info) => {
    const v = folderVerdict(info);
    if (!v.usable) { setKids(detail, notice("warn", v.kind === "missing" ? "這個資料夾已經不存在或搬走了" : v.text)); return; }
    const git = info.git || {};
    const term = info.terminals || {};
    setKids(detail,
      v.noGit
        ? el("div", { class: "tf-git" }, badge(NO_GIT_BADGE, "b-warn", NO_GIT_NOTE), el("span", { class: "small muted" }, NO_GIT_NOTE))
        : el("div", { class: "tf-git small" }, folderGitLine(git)),
      el("div", { class: "tf-terms small" }, folderTerminalHeadline(term),
        term.known === true && term.count > 0
          ? el("details", { class: "fp-terms" }, el("summary", null, "各是什麼狀態"),
              el("p", { class: "small" }, folderTerminalStatusText(term.items)),
              el("p", { class: "small muted" }, FOLDER_TERMINAL_NOTE))
          : null),
      info.project_skill_count === null || info.project_skill_count === undefined ? null
        : el("div", { class: "tf-skills small" }, `專案技能 ${info.project_skill_count} 張`));
  }).catch((e) => {
    setKids(detail, notice("warn", e && e.status === 403 ? `${e.message}（請換一個資料夾）` : "讀不到這個資料夾的資訊：" + (e && e.message || "")));
  });
  return box;
}

function taskFrontCard(task, opts = {}) {
  // the team and the next step, only when the flows were read: not knowing is not "no team"
  const flow = Array.isArray(opts.flows) ? opts.flows.find((f) => f && f.task_id === task.id) || null : undefined;
  return el("article", { class: "tf-card card", "data-task": task.id },
    el("div", { class: "tf-title" }, el("strong", null, task.title || "（沒有名稱）"), taskStatusBadge(task.status)),
    taskStatusExplain(task.status, task.pickup).map((t) => el("p", { class: "small muted", "data-tf": "status-explain" }, t)),
    taskFolderBlock(task, opts),
    flow ? el("div", { class: "tf-team", "data-tf": "team" }, teamAvatars(flow),
        nextStepSummary(flow) ? el("div", { class: "small", "data-tf": "next" }, nextStepSummary(flow)) : null,
        nextStepActionNode(flow, { task, profiles: opts.profiles, compact: true }))
      : flow === null ? el("div", { class: "tf-team small muted", "data-tf": "team" }, "還沒有隊伍 · ",
          el("a", { href: `#/workbench?task=${encodeURIComponent(task.id)}` }, "把角色卡放上去")) : null,
    el("div", { class: "tf-actions" },
      el("a", { class: "btn small", href: `#/workbench?task=${encodeURIComponent(task.id)}` }, "打開")));
}

// The lobby's section of task cards: the unfinished ones, newest first.
function taskCardsSection(tasksList, opts = {}) {
  const open = (Array.isArray(tasksList) ? tasksList : []).filter((t) => t && t.status !== "closed" && t.status !== "handed_off");
  const add = el("button", { type: "button", class: "btn primary small", "data-act": "import", on: { click: () => openImportProject({
    onCreated: opts.onCreated, onOpenTask: opts.onOpenTask }) } }, "＋ 任務卡（導入專案）");
  return el("section", { class: "section", id: "h-tasks" },
    sectionHead("任務卡", "一張任務卡就是一個資料夾：把你電腦上現有的專案導入，就能在這裡管理。", add),
    open.length
      ? el("div", null,
          el("div", { class: "grid" }, open.slice(0, FOLDER_OPEN_TASK_MAX).map((t) => taskFrontCard(t, opts))),
          open.length > FOLDER_OPEN_TASK_MAX
            ? el("p", { class: "small muted tf-more" }, `還有 ${open.length - FOLDER_OPEN_TASK_MAX} 張未結案的任務卡，`,
                el("a", { href: "#/workbench" }, "到終端工作台的「任務卡」分頁看全部"), "。") : null)
      : emptyState("還沒有任務卡", "按「＋ 任務卡（導入專案）」，挑一個你電腦上現有的專案資料夾。"));
}

// ---------- router ---------------------------------------------------------

// The phone menu (design card-play 3.9, #11): at 720px and narrower the nav folds behind one button that names the page
// you are on, instead of a row that scrolls sideways. The button only toggles a class; the CSS does the folding, so a
// wide window never sees it.
function navPageName(top) {
  const link = Array.from(document.querySelectorAll("[data-nav]")).find((a) => a.dataset && a.dataset.nav === top);
  if (!link) return "";
  const kids = link.childNodes ? Array.from(link.childNodes) : [];
  const own = kids.filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();
  return own || String(link.textContent || "").replace(/^\S\s*/, "").trim();
}
function setNavMenu(open) {
  const side = document.querySelector("nav.side");
  const btn = document.getElementById("nav-toggle");
  if (side && side.classList) side.classList.toggle("nav-open", !!open);
  if (btn) btn.setAttribute("aria-expanded", String(!!open));
}
function syncNavMenu(top) {
  const label = document.getElementById("nav-toggle-label");
  const name = navPageName(top);
  if (label) label.textContent = name ? `選單：${name}` : "選單";
  setNavMenu(false);   // going to a page puts the menu away
}
function wireNavMenu() {
  const btn = document.getElementById("nav-toggle");
  if (!btn || !btn.addEventListener) return;
  btn.addEventListener("click", () => setNavMenu(btn.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && btn.getAttribute("aria-expanded") === "true") { setNavMenu(false); if (btn.focus) btn.focus(); }
  });
}

let liveTimer = null;
let liveTick = null;
let routedHash = null;
function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = raw.split("?");
  const params = Object.fromEntries(new URLSearchParams(qs || ""));
  return { parts: path.split("/").filter(Boolean), params };
}

async function route() {
  seq += 1;
  cleanupActiveTerminal();
  cleanupActiveView();
  routedHash = location.hash;
  const { parts, params } = parseHash();
  const top = parts[0] || "home";
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === top) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  syncNavMenu(top);
  clearInterval(liveTimer);
  try {
    if (top === "home") await viewHome();
    else if (top === "workbench") await viewWorkbench(parts[1] ? decodeURIComponent(parts[1]) : null, params.task, params.profile, params.launch === "1", params.step);
    else if (top === "armory") await viewArmory();
    else if (top === "skills" && parts[1]) await viewSkillDetail(parts[1]);
    else if (top === "skills") await viewSkills(params);
    else if (top === "team" && parts[1] === "role") await viewRole(parts[2]);
    else if (top === "team") await viewTeam();
    else if (top === "projects") await viewProjects(parts[1]);
    else if (top === "settings") await viewSettings();
    else if (top === "term" && parts[1]) await viewTerminal(decodeURIComponent(parts[1]));
    else if (top === "terminals") await viewTerminals();
    else if (top === "office") await viewOffice();
    else if (top === "flows" && parts[1]) await viewFlowDetail(decodeURIComponent(parts[1]));
    else if (top === "flows") await viewFlows();
    else setKids($main(), emptyState("找不到這個頁面", null));
  } catch (e) {
    setKids($main(), e.status === 401 ? authRequiredView() : notice("bad", "載入失敗：" + e.message));
  }
  if (authLostShown) return;   // the login page is up: nothing here should keep asking the server every few seconds
  // Live pages refresh their data quietly; they re-render only when nothing
  // is focused inside main, so typing and scrolling are never interrupted.
  // Home refreshes only its attention block, so the search box keeps focus.
  liveTick = null;
  if (top === "home") {
    liveTick = async () => {
      await loadLive();
      await loadFlows();
      const box = document.getElementById("h-board");
      if (!box) return;
      const g = boardGroups(D.live, D.flows);
      const key = boardKey(g, boardKeyContext());
      if (key === boardShownKey) return;
      boardShownKey = key;
      setKids(box, boardSection(g));
    };
  }
  if (top === "team" || top === "projects") {
    liveTick = async () => {
      const before = JSON.stringify(D.live && D.live.sessions.map((s) => [s.terminal_id, s.status, s.skills_used.length]));
      await loadLive();
      const after = JSON.stringify(D.live.sessions.map((s) => [s.terminal_id, s.status, s.skills_used.length]));
      const busy = $main().contains(document.activeElement) && document.activeElement !== $main();
      if (before !== after && !busy) { const y = scrollY; await route(); scrollTo(0, y); }
    };
  }
  if (top === "office") liveTick = officeTick;
  if (top === "flows" && parts[1]) {
    // the executor, reviews and gate change without the user doing anything: refresh them quietly
    liveTick = async () => { if (flowCoordinator) await flowCoordinator.tick(); };
  }
  if (top === "terminals") {
    liveTick = async () => {
      const ids = () => JSON.stringify(shellPanes().map((p) => p.pane_id));
      const before = ids();
      await loadLive();
      const busy = $main().contains(document.activeElement) && document.activeElement !== $main();
      if (before !== ids() && !busy) { const y = scrollY; await route(); scrollTo(0, y); }
    };
  }
  if (liveTick) liveTimer = setInterval(() => { if (!document.hidden) liveTick(); }, 5000);
}

setTheme(store.get("theme", "auto"));
setInterval(() => { if (!document.hidden && !authLostShown && !authPending) refreshTranslations(); }, 2500);
// Coming back to this tab: refresh at once instead of waiting.
document.addEventListener("visibilitychange", () => { if (!document.hidden && liveTick && !authPending) liveTick(); });
// The skip link moves focus only; it must not become a route ("#main" is not a page).
function skipToMain(e) {
  if (e) e.preventDefault();
  const main = $main();
  main.focus({ preventScroll: true });
  main.scrollIntoView({ block: "start" });
}
document.querySelector("a.skip").addEventListener("click", skipToMain);
wireNavMenu();
window.addEventListener("hashchange", () => {
  if (authPending) return;   // bootstrap routes to the address as it is once the login code is traded
  if (location.hash === "#main" && routedHash !== null) {  // reached without the click handler
    history.replaceState(null, "", routedHash || location.pathname + location.search);
    skipToMain();
    return;
  }
  scrollTo(0, 0); route(); document.getElementById("main").focus({ preventScroll: true });
});
if (location.hash === "#main") history.replaceState(null, "", location.pathname + location.search);

// Opening VBear (launcher, app) lands here with #auth=<token> once; trade it
// for the HttpOnly session cookie and drop it from the address bar at once.
// The exchange comes first and the router waits for it: while the code is being traded the page has no session, so
// every other request (the translation poll, a nav click, a tab coming back to the front) is held back instead of
// meeting a 401 and putting up "open VBear" on a page that is about to log in. authPending is set before the first
// await, so no timer or event can run in between.
async function bootstrap() {
  const m = /^#auth=([A-Za-z0-9_-]{20,200})$/.exec(location.hash || "");
  if (m) {
    authPending = true;
    history.replaceState(null, "", location.pathname + location.search + "#/");
    try { await api.post("/api/auth", { token: m[1] }); }
    catch (_) { /* the first API call then shows how to open VBear */ }
    finally { authPending = false; }
  }
  route();
}
bootstrap();

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
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
    STATUS,
    statusBadge,
    activityBasis,
    computeTaskProvenance,
    taskStatusBadge,
    taskStatusExplain,
    TASK_STATUS_LABELS,
    viewWorkbench,
    viewTeam,
    openCardWizard,
    openStarterDeck,
    permissionSuggestion,
    cardLight,
    sameNameCard,
    isDemoCard,
    sortCards,
    skillCompatible,
    skillIncompatibleNote,
    cardPosition,
    setCardPosition,
    profileCard,
    cardSlots,
    cardSlotState,
    cardDeparture,
    cardArt,
    cardPixelSvg,
    cardPatternStrip,
    cardPositionBadgeKey,
    positionBadge,
    armorShieldKind,
    readLoadouts,
    officeRoleCard,
    CARD_PIXELS,
    CARD_PALETTE,
    CARD_POSITION_BADGES,
    CARD_SLOT_LABEL,
    CARD_INTENT_NOTE,
    viewTerminal,
    shellPanes,
    shellLabel,
    shellTabLabels,
    titleFailureText,
    flowPhaseClass,
    flowEventBody,
    flowBindingNote,
    flowLiveText,
    flowGateGrid,
    flowTeamSection,
    viewOffice,
    waitsForYou,
    stationFor,
    speciesFor,
    campOf,
    spriteShadow,
    weaponsFrom,
    officeSkills,
    officeModel,
    officeKey,
    officeIndex,
    officeList,
    officeOverrides,
    restoreSelection,
    OFFICE_SPECIES,
    OFFICE_SPRITES,
    OFFICE_SPRITES_WORKING,
    personaSpeech,
    officeStageScreen,
    officeStageSvg,
    officeStage,
    officeStageCollapsed,
    officePanelContent,
    officeSprite,
    officeDeskButton,
    officeProfileButton,
    officeTeamButton,
    OFFICE_PALETTE,
    OFFICE_CAMPS,
    boardGroups,
    boardKey,
    boardKeyContext,
    boardSection,
    questCard,
    flowCard,
    sessionCard,
    api,
    mountCoordinator,
    mountStorage,
    flowAutomationDetail,
    openAcceptanceDialog,
    cleanupActiveView,
    cleanupActiveTerminal,
    // Exported so the modal registry's two subtle invariants can be tested
    // directly rather than only through whichever dialogs happen to exist:
    // (a) every close path deregisters, so a dialog closed by Escape is
    // never torn down a second time by a later navigation, and (b) stacked
    // dialogs unwind innermost-first without leaving the page inert.
    withModalA11y,
    closeOpenModals,
    route,
    NO_GIT_BADGE,
    NO_GIT_NOTE,
    FOLDER_BROWSER_NOTE,
    FOLDER_TERMINAL_NOTE,
    FOLDER_REFUSED_HOME_DIRS,
    expandHome,
    folderBaseName,
    folderSources,
    folderTerminalStatusText,
    folderTerminalHeadline,
    folderVerdict,
    folderGitLine,
    folderOpenTasks,
    folderPicked,
    folderPicker,
    folderFacts,
    openFolderDialog,
    openImportProject,
    taskFolderBlock,
    taskFrontCard,
    taskCardsSection,
    TEAM_SLOTS,
    TEAM_INFO,
    SLOT_REVIEW_NEEDS_DIFF,
    SLOT_REVIEW_SELF,
    TEAM_SAVE_NOTE,
    teamFamily,
    teamCardFamily,
    slotProblem,
    roleFromCard,
    teamSlotsFromRoles,
    teamMissing,
    teamRolesBody,
    teamProblems,
    teamCardState,
    teamDraftRead,
    teamDraftWrite,
    nextSteps,
    nextStepsList,
    nextStepAction,
    nextStepActionNode,
    cardPassLine,
    skillPickText,
    launchRangeText,
    launchMemoRead,
    launchMemoAdd,
    taskTerminalLink,
    folderLooksLikePath,
    nextStepSummary,
    teamAvatars,
    teamBoard,
    teamSection,
    openPlaceDialog,
    flowRoleToolText,
    navPageName,
    setNavMenu,
    syncNavMenu,
    passSummary,
    passFront,
    passMark,
    passFix,
    passFolderFix,
    passKind,
    PASS_COMMIT_ACK,
    onboardingState,
    onboardingSection,
    onboardingSettings,
    questNext,
    boardTeamKey,
    ONBOARD_STEPS,
  };
}
