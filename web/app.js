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
  async get(path) {
    // The custom header lets the server tell its own page from a cross-site request.
    const res = await fetch(path, { headers: { Accept: "application/json", "X-VBear": "1" } });
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (res.status === 401 && data.code === "auth_required") authLost();
    if (!res.ok) {
      const error = new Error(data.error || `HTTP ${res.status}`);
      error.status = res.status;
      throw error;
    }
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
      throw error;
    }
    return data;
  },
};

// The session cookie stopped working (VBear restarted, or the page was
// opened without going through VBear): stop refreshing and say how to get in.
let authLostShown = false;
function authLost() {
  if (authLostShown || typeof document === "undefined") return;
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
const STATUS = {
  blocked: ["等你回覆", "b-bad"], done: ["完成・待查看", "b-warn"], working: ["工作中", "b-info"],
  idle: ["待命", "b-ok"], unknown: ["狀態未知", "b-mute"],
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
function statusBadge(s) {
  const [l, c] = STATUS[s] || STATUS.unknown;
  return badge(l, c, s === "unknown" ? "VBear runtime 無法從終端判斷 Agent 是否在工作或等你回覆" : `回報狀態：${s}`);
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
async function loadLive(force) {
  try { D.live = await api.get("/api/live" + (force ? "?force=1" : "")); }
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
    s.description && s.description.value
      ? el("p", { class: "clamp" }, firstSentence(s.description.value, 170))
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
      statusBadge(x.status)),
    x.title ? el("p", { class: "clamp" }, x.title) : null,
    el("dl", { class: "kv small" },
      el("dt", null, "執行工具"), el("dd", null, TOOL[x.agent] || x.agent || "未知"),
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
function confirmInPage(title, message, confirmLabel) {
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
function closeSessionButton(paneId, afterHash = "#/team") {
  if (!NATIVE_SESSION_RE.test(paneId || "")) return null;
  const btn = el("button", { class: "btn small", type: "button",
    title: "結束這個 Terminal 裡的程式並關閉 session",
    on: { click: async () => {
      if (!(await confirmInPage("關閉 Session", "確定要關閉這個 Terminal？裡面正在執行的程式會被結束。", "關閉 Session"))) return;
      btn.disabled = true;
      try {
        const r = await api.post(`/api/native/sessions/${encodeURIComponent(paneId)}/close`, {});
        const m = r.managed;
        toast(!m ? "Session 已關閉"
          : m.cleaned ? "Session 已關閉，暫存區與設定已清除"
          : `Session 已關閉；暫存區保留待檢查：${m.retained_reason || "原因未知"}`);
        if (location.hash === afterHash) route();  // no hashchange: re-render in place
        else if (!location.hash.startsWith("#/workbench")) location.hash = afterHash;
      } catch (e) {
        if (e.status === 404) {
          toast("Session 已不存在或已結束");
          if (!location.hash.startsWith("#/workbench")) location.hash = afterHash;
          return;
        }
        toast("關閉失敗：" + e.message);
        btn.disabled = false;
      }
    } } }, "關閉 Session");
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
  if (!h.available) return notice("warn", ["無法連線到 VBear runtime，工作中的 Terminal 資訊暫不可用。", (h.problems || []).join("；")].join(" "));
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
    el("div", null, "主控台已改用內建的 VBear runtime，不再支援 Herdr，設定已自動切換。在 Herdr 或其他終端自行啟動的 Agent 不會出現在這裡；請從 Agent Profile 的「預覽並啟動」開啟。 ", ack));
  return wrap;
}
function sectionHead(title, sub, action) {
  return el("div", { class: "section-head" },
    el("div", null, el("h2", null, title), sub ? el("p", { class: "small muted" }, sub) : null), action || null);
}

// ---------- views ----------------------------------------------------------

async function viewHome() {
  const token = seq;
  await Promise.all([loadStatic(), loadLive()]);
  const L = D.live;
  const main = claim(token);
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

  const recentProjects = (L.projects || []).filter((p) => p.live_session_ids.length || p.last_activity).slice(0, 6);
  const problemSkills = (D.overview.skills_with_problems || []).map((id) => D.byId.get(id)).filter(Boolean);

  setKids(main, 
    el("h1", null, "我的工作台"),
    el("p", { class: "lede" }, "先看需要你處理的事，再找適合這次任務的技能。"),
    corruptNotice(),
    staleNotice(),
    herdrMigrationNotice(),
    runtimeNotice(),
    el("section", { class: "section", id: "h-att-wrap" }, attentionSection()),
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

function attentionSection() {
  const L = D.live;
  const attention = (L.attention || []).map((id) => L.sessions.find((s) => s.terminal_id === id)).filter(Boolean);
  return [
    sectionHead("需要你處理", attention.length ? `${attention.length} 個 Terminal 在等你・每 5 秒更新` : "每 5 秒更新"),
    attention.length ? el("div", { class: "grid" }, attention.map(sessionCard))
      : emptyState(L.runtime && L.runtime.available ? "目前沒有可判斷為等你回覆的工作" : "VBear runtime 未連線，無法判斷",
        L.runtime && L.runtime.available ? "VBear runtime 無法從終端判斷 Agent 是否在等你，狀態會顯示「狀態未知」；請到 Agent 團隊查看工作中的 Terminal。" : null),
  ];
}

function projectCard(p) {
  const live = (D.live.sessions || []).filter((s) => s.project_id === p.project_id);
  return el("a", { class: "card", href: `#/projects/${p.project_id}` },
    el("div", { class: "card-top" },
      el("div", { style: "min-width:0" },
        el("div", { class: "card-title" }, p.name),
        el("div", { class: "card-sub mono" }, home(p.path) || p.basis)),
      live.length ? badge(`${live.length} 個工作中`, "b-info") : badge("無工作中", "b-mute")),
    el("div", { class: "stat-line" },
      p.git_branch ? el("span", null, "分支 ", el("b", null, p.git_branch)) : null,
      el("span", null, "近期工作階段 ", el("b", null, p.recent_session_ids.length)),
      p.last_activity ? el("span", null, "最後活動 ", el("b", null, ago(p.last_activity))) : null),
    live.length ? el("div", { class: "chips" }, live.slice(0, 4).map((s) => el("span", { class: "tag" }, s.role_label || TOOL[s.agent] || s.agent))) : null);
}

async function viewSkills(params) {
  const token = seq;
  await loadStatic();
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
    el("td", null, firstSentence(s.description && s.description.value, 110) || el("span", { class: "muted" }, "未提供"), why.length ? el("div", { class: "small muted" }, "符合：" + why.join("、")) : null),
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
    el("div", { class: "row" }, el("h1", null, "技能庫"), el("a", { class: "btn small", href: "#/armory" }, "Armory 四態總覽")),
    el("p", { class: "lede" }, "這裡是掃描到的 Skill 清單。預設只顯示目前可使用的副本；想看安裝、裝備與使用證據，請開啟 Armory。 ", helpTip("技能庫", "技能庫只盤點掃描到的檔案與載入位置；它不會安裝、啟動或修改任何 Skill。")),
    corruptNotice(),
    staleNotice(),
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
}

async function viewArmory() {
  const token = seq;
  const main = claim(token);
  setKids(main, el("p", { class: "loading" }, "載入 Armory…"));
  let data;
  try { data = await api.get("/api/armory"); }
  catch (e) { setKids(main, crumbs([["技能庫", "#/skills"], ["Armory"]]), notice("bad", e.message)); return; }
  if (token !== seq) return;
  const state = (label, value, source, hint, cls) => el("div", { class: "armory-state" },
    el("div", { class: "armory-label" }, badge(label, cls), helpTip(label, hint)),
    el("span", { class: "small muted" }, "依據：", source), value);
  const rows = data.skills || [];
  setKids(main,
    crumbs([["技能庫", "#/skills"], ["Armory"]]),
    el("div", { class: "row" }, el("h1", null, "VBear Armory"), el("a", { class: "btn small", href: "#/skills" }, "回技能庫")),
    el("p", { class: "lede" }, "四種狀態是唯讀觀察。已安裝、已裝備與曾觀察到使用是不同事情；沒有證據就顯示未知。"),
    data.unresolved_equipped && data.unresolved_equipped.length
      ? notice("warn", `有 ${data.unresolved_equipped.length} 筆 Profile 引用找不到對應技能；不會自動刪除。`) : null,
    el("div", { class: "grid armory-grid" }, rows.map((s) => {
      const x = s.states || {}, loaded = x.loaded || {}, equipped = x.equipped || [];
      return el("div", { class: "card" },
        el("div", { class: "card-top" }, el("a", { href: `#/skills/${s.skill_id}`, class: "card-title" }, s.name), actBadge(s.activation)),
        el("div", { class: "card-sub mono" }, s.invoke_name || s.skill_id),
        el("div", { class: "armory-states" },
          state("市集可取得", x.available ? badge("可取得", "b-info") : badge("不適用", "b-mute"), s.sources.available,
            "只有市集中的未安裝副本才會顯示「可取得」；這不代表目前可用。", "b-info"),
          state("本機已安裝", x.installed ? badge("已安裝", "b-ok") : badge("未安裝／其他", "b-mute"), s.sources.installed,
            "已安裝代表掃描到本機副本；不代表正在被任何 Agent 使用。", "b-ok"),
          state("已裝備到 Profile", equipped.length
            ? el("div", { class: "chips" }, equipped.map((p) => el("a", { class: "tag", href: `#/workbench?profile=${encodeURIComponent(p.id)}` }, p.name || p.id, p.enabled ? null : "（已停用）")))
            : badge("未裝備", "b-mute"), s.sources.equipped,
            "裝備是 Profile 的使用者意圖；它不會自動啟動、載入或套用這個 Skill。", "b-accent"),
          state("使用證據", loaded.observed ? badge("曾觀察到使用", "b-warn") : badge("尚無證據", "b-mute"), s.sources.loaded,
            "只有執行紀錄確實觀察到使用時才會顯示；尚無證據不代表沒有載入。", "b-warn")));
    })));
  window.scrollTo(0, 0);
}

async function viewSkillDetail(id) {
  const token = seq;
  await loadStatic();
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
        field("一句話用途", s.description, "作者沒有提供 description"),
        field("使用時機", s.when_to_use),
        field("需要提供", s.inputs),
        field("預期產出", s.outputs),
        field("相依需求", s.dependencies),
        (s.categories || []).length ? el("div", { class: "field" }, el("h3", null, "用途分類", prov({ origin: "derived", detail: "描述關鍵字" })),
          el("div", { class: "chips" }, s.categories.map((c) => el("span", { class: "tag cat" }, `${c.label}（命中「${c.keyword}」）`)))) : null),
      el("div", { style: "display:grid;gap:16px;align-content:start" },
        annotationPanel(s, d.annotation_key, d.annotation),
        el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:10px" }, "被哪些 Agent Profile 裝備"),
          d.equipped_by && d.equipped_by.length ? el("ul", { class: "tree" }, d.equipped_by.map((p) => el("li", null,
            el("a", { href: `#/workbench?profile=${encodeURIComponent(p.id)}` }, p.name || p.id),
            " ", p.enabled ? badge("啟用", "b-ok") : badge("已停用", "b-mute"),
            el("span", { class: "small muted" }, "・主控台 Profile（使用者意圖）"))))
            : el("p", { class: "muted small" }, "沒有 Agent Profile 裝備此技能。")),
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

async function viewTeam() {
  const token = seq;
  await Promise.all([loadStatic(), loadLive()]);
  const main = claim(token);
  const L = D.live;
  const tview = store.get("teamView", "card");
  const sessions = [...L.sessions].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9));
  const cli = D.roles.filter((r) => r.kind === "cli");
  const subs = D.roles.filter((r) => r.kind !== "cli");

  const liveBlock = tview === "list"
    ? el("div", { class: "panel table-wrap" }, el("table", { class: "list" },
        el("thead", null, el("tr", null, ["角色", "工具", "狀態", "本次模型", "專案", "本次用過的技能", ""].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", null, sessions.map((x) => el("tr", null,
          el("td", null, el("b", null, x.role_label || "未命名"), el("div", { class: "small muted mono" }, x.pane_id)),
          el("td", null, TOOL[x.agent] || x.agent),
          el("td", null, statusBadge(x.status)),
          el("td", null, modelList(x.models_observed).join("、") || el("span", { class: "muted" }, "未知")),
          el("td", null, ((L.projects || []).find((p) => p.project_id === x.project_id) || {}).name || "—"),
          el("td", null, (x.skills_used || []).length ? el("div", { class: "chips" }, x.skills_used.slice(0, 3).map(usedChip)) : el("span", { class: "muted" }, "—")),
          el("td", null,
            el("a", { class: "btn small primary", href: `#/term/${encodeURIComponent(x.pane_id)}`, title: "開啟終端機串流" }, "終端")))))))
    : el("div", { class: "grid" }, sessions.map(sessionCard));

  const seg = el("div", { class: "seg", role: "group", "aria-label": "顯示方式" },
    [["card", "角色卡"], ["list", "表格"]].map(([v, t]) => el("button", { type: "button", "aria-pressed": String(tview === v), on: { click: () => { store.set("teamView", v); viewTeam(); } } }, t)));

  setKids(main, 
    el("h1", null, "Agent 團隊"),
    el("p", { class: "lede" }, "上半部是現在正在工作的 Terminal；下半部是可以重複使用的角色設定。兩者不同：一個角色可以同時有多個工作階段。"),
    runtimeNotice(),
    el("section", { class: "section" },
      sectionHead("工作中的 Terminal", `${sessions.length} 個，由 VBear runtime 管理`, seg),
      sessions.length ? liveBlock : emptyState("沒有工作中的 Agent", L.runtime && L.runtime.available ? "從工作台「[A] 角色裝備」的 Agent Profile 按「預覽並啟動」後會出現在這裡" : "VBear runtime 未連線")),
    el("section", { class: "section" },
      sectionHead("主代理", "直接在終端機執行的工具本身"),
      el("div", { class: "grid" }, cli.map(roleCard))),
    el("section", { class: "section" },
      sectionHead("角色設定（子代理）", `${subs.length} 個設定檔`),
      subs.length ? el("div", { class: "grid" }, subs.map(roleCard)) : emptyState("沒有找到子代理設定", "可在設定頁確認掃描來源")),
    el("div", { class: "legend section" },
      el("span", null, el("b", null, "本次模型"), "：從對話紀錄觀察到的實際模型"),
      el("span", null, el("b", null, "預設模型"), "：設定檔中的預設值，實際執行可能不同")),
  );
}
const STATUS_ORDER = { blocked: 0, done: 1, working: 2, idle: 3, unknown: 4 };

async function viewRole(id) {
  const token = seq;
  await Promise.all([loadStatic(), loadLive()]);
  const r = D.roles.find((x) => x.role_id === id);
  const main = claim(token);
  if (!r) { setKids(main, crumbs([["Agent 團隊", "#/team"]]), notice("bad", "找不到這個角色（索引可能已更新）")); return; }
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
    crumbs([["Agent 團隊", "#/team"], [r.name]]),
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
          el("dt", null, "工作中"), el("dd", null, r.kind === "cli" ? `${sessions.length} 個 Terminal` : "目前無法辨識子代理的執行個體")),
        sessions.length ? el("ul", { class: "tree", style: "margin-top:12px" }, sessions.map((s) => el("li", null,
          el("b", null, s.role_label || s.pane_id), " ", statusBadge(s.status), " ",
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
    el("p", { class: "lede" }, "依工作目錄的 git 儲存庫歸類。專案是目標與資料歸屬；工作中的 Terminal 依工作目錄對應到專案。"),
    runtimeNotice(),
    el("section", { class: "section" },
      sectionHead("有 Agent 正在工作", `${active.length} 個專案`),
      active.length ? el("div", { style: "display:grid;gap:12px" }, active.map((p) => projectFold(p, true))) : emptyState("目前沒有工作中的專案", null)),
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
      live.length ? badge(`${live.length} 個工作中`, "b-info") : null,
      el("span", { class: "small muted", style: "font-weight:400" }, p.last_activity ? `・${ago(p.last_activity)}` : ""),
      el("span", { class: "spacer" }), el("a", { class: "btn small", href: `#/projects/${p.project_id}` }, "詳情")),
    el("div", { class: "fold-body" },
      el("div", { class: "small muted mono", style: "margin-bottom:8px" }, home(p.path), p.git_branch ? ` · ${p.git_branch}` : ""),
      live.length ? el("ul", { class: "tree" }, [...byWs.entries()].map(([ws, list]) => el("li", null,
        el("span", { class: "small muted" }, "群組 "), el("b", null, ws),
        el("ul", { class: "tree" }, list.map((s) => el("li", { class: "row" },
          el("b", null, s.role_label || s.pane_id), statusBadge(s.status), el("span", { class: "tag" }, TOOL[s.agent] || s.agent),
          (s.skills_used || []).slice(0, 3).map(usedChip),
          el("a", { class: "btn small", href: `#/term/${encodeURIComponent(s.pane_id)}` }, "開啟"))))))) : el("p", { class: "small muted" }, "沒有工作中的 Terminal。"),
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
      sectionHead("工作中的 Terminal", `${live.length} 個`),
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

async function viewSettings() {
  const token = seq;
  await loadStatic();
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
            el("li", null, "所有掃描都在這台電腦上完成，主控台不連線到任何外部服務。"),
            el("li", null, "網頁伺服器只接受本機（127.0.0.1）連線。"),
            el("li", null, "技能內的腳本不會被執行；原始內容以純文字顯示。"),
            el("li", null, "主控台只寫入自己的狀態目錄", advanced ? [": ", el("span", { class: "mono" }, home(c.state_dir))] : "", "。"),
            el("li", null, "Agent 由主控台內建的 VBear runtime 啟動與管理；開啟終端預設只觀看，接管後才會送出輸入。"))),
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
function cleanupActiveView() {
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
  const toolName = session ? (TOOL[session.agent] || session.agent) : "Terminal";
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
  const termElem = el("div", { class: "term-container", role: "region", "aria-label": `Terminal ${paneId}` });
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
        ? (isShell ? "需要新的終端機時，請到「終端機」頁開啟。" : "需要新的 Terminal 時，請從 Agent Profile 的「預覽並啟動」開啟。")
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
        el("p", null, "您即將接管此 Terminal 的鍵盤輸入控制。"),
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
          closedReason = "此 Terminal 已不存在（已關閉或從未存在）。";
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
      : crumbs([["Agent 團隊", "#/team"], [`終端機 (${paneId})`]]),
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

function computeTaskProvenance(prov = {}, rawStatus = "draft") {
  const agent = (prov && prov.agent) || "pending";
  const tests = (prov && prov.tests) || "untested";
  const human = (prov && prov.human) || "pending";
  // No authenticated verifier exists anywhere in this console (mirrors
  // tasks.py H1): this is an honestly-named *assertion* — tests and human
  // approval were both set through this same unauthenticated UI/API — never
  // a governed or cryptographically verified fact. Nothing here computes or
  // exposes a "verified" boolean; that field is only ever hardcoded false
  // on the backend.
  const verificationAsserted = (tests === "passed" && human === "approved");
  let derivedStatus = "draft";
  if (verificationAsserted) {
    derivedStatus = "verification_asserted";
  } else if (agent === "completed") {
    derivedStatus = "agent_completed";
  } else if (agent === "in_progress") {
    derivedStatus = "in_progress";
  } else if (agent === "blocked") {
    derivedStatus = "blocked";
  } else if (["draft", "in_progress", "blocked", "agent_completed"].includes(rawStatus)) {
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
  draft: ["草稿", "b-mute", "尚未開始執行"],
  in_progress: ["執行中", "b-info", "Agent 或開發者正在進行此任務"],
  agent_completed: ["待驗收 (Agent回報完成)", "b-warn", "Agent 已回報完成，但尚未通過測試驗證與人類核准"],
  verification_asserted: ["聲稱驗證通過 (Verification Asserted)", "b-ok", "此主控台無身份驗證：僅代表自動化測試與介面核准兩欄皆已透過本頁/API 自我回報為通過，並非經授權之正式驗證"],
  blocked: ["等待回覆 / 阻塞", "b-bad", "任務遭遇問題等待指示"],
};

function taskStatusBadge(status) {
  const [label, cls, title] = TASK_STATUS_LABELS[status] || TASK_STATUS_LABELS.draft;
  return badge(label, cls, title);
}

async function viewWorkbench(initialPaneId, initialTaskId, initialProfileId) {
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
  let rightCollapsed = initialProfileId ? false : store.get("wb:right_collapsed", false);
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
      rightToggleBtn.textContent = "右欄 ◄";
      rightToggleBtn.setAttribute("aria-pressed", "false");
    } else {
      shell.classList.remove("right-collapsed");
      rightCol.classList.remove("collapsed");
      rightCol.classList.add("mobile-show");
      rightToggleBtn.textContent = "右欄 ►";
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
          statusBadge(sess.status)),
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
          el("h3", { class: "wb-panel-title" }, "當前 Agent 資訊"),
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
          el("h2", { class: "wb-panel-title" }, `執行中 Agent (${sessions.length})`),
          el("button", {
            class: "btn small",
            type: "button",
            title: "收合左欄",
            "aria-label": "收合左側欄",
            on: { click: toggleLeft },
          }, "◀")),
        sessions.length ? el("div", { class: "wb-session-list" }, sessionItems)
                        : emptyState("目前沒有運行中的 Agent", null)),
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
          emptyState("尚未選取 Terminal", "請由左側選取一個工作中的 Agent 或建立新工作階段。")));
      return;
    }

    const currentPane = activePaneId;
    const session = sessions.find((s) => s.pane_id === currentPane);
    const roleName = session ? (session.role_label || session.agent || currentPane) : currentPane;
    const toolName = session ? (TOOL[session.agent] || session.agent) : "Terminal";
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
    const termElem = el("div", { class: "term-container", role: "region", "aria-label": `Terminal ${currentPane}` });
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
        ? "需要新的 Terminal 時，請從 Agent Profile 的「預覽並啟動」開啟。"
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
        actions.push(el("button", { class: "btn small", type: "button", on: { click: toggleRight }, title: "展開右欄" }, "右欄 ►"));
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
          el("p", null, "您即將接管此 Terminal 的鍵盤輸入控制。"),
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
            closedReason = "此 Terminal 已不存在（已關閉或從未存在）。";
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
    ["agent", "[A] 角色裝備"],
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

    const tabsHeader = el("div", { class: "wb-tabs", role: "tablist", "aria-label": "Context 治理與任務分頁" }, tabButtons);

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
          el("h2", { class: "wb-panel-title" }, "Context 治理與任務"),
          el("button", {
            class: "btn small",
            type: "button",
            title: "收合右欄",
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
      el("button", { class: "btn small primary", type: "button", on: { click: promptCreateTask } }, "＋ 新增"));

    const activeTask = tasksList.find((t) => t.id === activeTaskId);
    if (!activeTask) {
      setKids(taskContent,
        selectorRow,
        emptyState("尚未選取或建立任務卡", "點選上方「＋ 新增」建立一個新的 Task Card。")
      );
      return taskContent;
    }

    const taskProv = activeTask.provenance || {};
    const { agent, tests, human, verificationAsserted, derivedStatus } = computeTaskProvenance(taskProv, activeTask.status);

    // Tracking association status
    const isAssociatedWithCurrent = (activeTask.associated_pane_id === activePaneId);
    const trackingBox = el("div", { class: "notice info", style: "font-size:12.5px; padding: 8px 10px;" },
      el("div", null,
        el("div", { style: "font-weight:700; margin-bottom:2px" },
          isAssociatedWithCurrent ? "✓ 已與當前 Terminal 關聯 (僅追蹤記錄)" : "尚未與當前 Terminal 關聯"),
        el("div", { class: "small muted" }, "ℹ️ 追蹤關聯 (Tracking Only)：此任務與 Session 僅供主控台追蹤記錄，絕非 Context 注入。"),
        el("div", { class: "small muted", style: "color:var(--warn); margin-top:2px" }, "⚠️ 未來規則提示：若變更 Task Card 並欲套用為 Effective Context，必須重新啟動 Agent Session。")),
      el("button", {
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
              toast(isAssociatedWithCurrent ? "已解除 Terminal 追蹤關聯" : "已將任務與當前 Terminal 關聯 (僅追蹤)");
              renderRightColumn();
            } catch (err) {
              toast("關聯更新失敗：" + err.message);
            }
          },
        },
      }, isAssociatedWithCurrent ? "解除關聯" : "關聯此 Terminal"));

    // Status Provenance Box
    const provBox = el("div", { class: "wb-provenance-box" },
      el("div", { class: "wb-provenance-head" },
        el("span", null, "狀態證明 (Status Provenance)"),
        taskStatusBadge(derivedStatus)),
      el("div", { class: "wb-provenance-row" },
        el("span", null, "1. 自我回報狀態 (Self-Reported)：",
          taskProv.agent_set_at ? el("span", { class: "small muted" }, ` · 最後更新 ${fmtTime(taskProv.agent_set_at)}`) : null),
        el("select", {
          on: {
            change: async (e) => {
              const newAgent = e.target.value;
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
      el("button", { class: "btn small", type: "button", on: { click: () => promptDeleteTask(activeTask) } }, "刪除任務"));

    setKids(taskContent,
      selectorRow,
      el("div", { class: "wb-task-head" },
        el("h3", { class: "wb-task-title" }, activeTask.title),
        el("div", { class: "row small muted" },
          badge(activeTask.template, "b-info", "任務範本"),
          taskStatusBadge(derivedStatus),
          prov({ origin: "user", detail: "本機任務卡 · 僅追蹤" }))),
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
      toast("載入 Agent Profile 失敗：" + err.message);
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
      : "（未選職業）";
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
        p.enabled ? badge("啟用", "b-ok plain", "此 Profile 仍可載入")
                  : badge("停用", "b-mute plain", "已停用，但保留存檔")),
      el("div", { class: "small muted" },
        `${profession} · ${toolLabel}`),
      el("div", { class: "small muted mono" }, p.id),
      unresolved.length ? el("div", { class: "small", style: "color:#b85" },
        `⚠ ${unresolved.length} 項技能已從掃描結果中消失`) : null
    );
    return item;
  }

  function renderAgentProfileDetail(p) {
    const { profession } = profileSummary(p);
    const skills = p.equipped_skill_ids || [];
    const unresolved = (p._unresolved && p._unresolved.skills) || [];
    const unresolvedSet = new Set(unresolved);
    const intentValues = ["allow", "deny", "unspecified"];
    const intentLabels = { allow: "允許意圖", deny: "拒絕意圖", unspecified: "未定" };
    const intentBadgeClass = { allow: "b-ok", deny: "b-bad", unspecified: "b-mute" };

    const permRows = (agentBuilderCatalog && agentBuilderCatalog.permission_keys
                      || ["read", "write", "test", "deploy"]).map((k) => {
      const v = (p.permission_intents && p.permission_intents[k]) || "unspecified";
      const safe = intentValues.includes(v) ? v : "unspecified";
      return el("div", { class: "row", style: "justify-content:space-between; padding:2px 0;" },
        el("span", { class: "mono" }, k),
        el("span", null,
          badge(intentLabels[safe], `${intentBadgeClass[safe]} plain`,
                "僅為意圖記錄，不會實際執行為 CLI 權限")));
    });

    const skillList = skills.length
      ? skills.map((sid) => {
          const isUnresolved = unresolvedSet.has(sid);
          return el("li", { class: "small mono" },
            sid,
            isUnresolved ? el("span", { class: "b-warn small", style: "margin-left:6px;" },
                "⚠ 已不存在") : null);
        })
      : [el("li", { class: "small muted" }, "未裝備任何技能")];

    return append(el("div", { class: "wb-tab-content" }),
      el("div", { class: "row wb-profile-head", style: "justify-content:space-between" },
        el("h3", { style: "margin:0" }, p.name || p.id),
        el("div", { class: "wb-profile-actions" },
          el("button", { class: "btn small primary", type: "button",
            title: "先看這次啟動實際會套用什麼，確認後才啟動",
            on: { click: () => promptAgentLaunch(p) } }, "預覽並啟動"),
          el("button", { class: "btn small", type: "button",
            on: { click: () => promptAgentProfileEditor(p) } }, "編輯"),
          el("button", { class: "btn small", type: "button",
            on: { click: async () => {
              try {
                const res = await api.post(`/api/agent-profiles/${encodeURIComponent(p.id)}/duplicate`, {});
                toast("已建立副本：" + res.profile.name);
                await reloadAgentProfiles();
                selectedProfileId = res.profile.id;
                renderRightColumn();
              } catch (err) {
                toast("複製失敗：" + err.message);
              }
            } } }, "複製"),
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
      el("dl", { class: "kv small" },
        el("dt", null, "Profile ID"),
          el("dd", { class: "mono" }, p.id),
        el("dt", null, "職業角色"),
          el("dd", null, profession),
        el("dt", null, "模型工具"),
          el("dd", null, (p.model && p.model.tool) || "—"),
        el("dt", null, "模型設定 (Model ID)"),
          el("dd", { class: "mono" }, (p.model && p.model.model_id) || "（未指定，視為該工具預設值；非執行環境）"),
        el("dt", null, "更新時間"),
          el("dd", null, fmtTime(p.updated_at || p.created_at))),
      el("div", { class: "wb-field-group" },
        el("div", { class: "wb-field-label" }, "已裝備技能 (Equipped Skill Loadout)"),
        el("ul", { class: "wb-field-val", style: "list-style: disc inside; padding-left: 4px;" }, skillList)),
      el("div", { class: "wb-field-group" },
        el("div", { class: "wb-field-label" }, "權限意圖 (Permission Intents · 僅意圖)"),
        el("div", { class: "wb-field-val" }, permRows)),
      el("div", { class: "notice info", style: "font-size:12.5px" },
        el("span", { class: "ico" }, "ℹ"),
        el("div", null,
          "Equipped Skill Loadout ≠ 已進入任何執行中的 session。儲存 Profile 不會啟動、",
          "重啟或注入任何東西。權限意圖僅為意圖記錄，不會實際執行為 CLI 工具權限。"))
    );
  }

  function renderAgentProfileEditor(isNew) {
    // Opens the editor modal. isNew=true is a Create; otherwise Edit.
    // The editor pulls the catalog fresh if it's missing — the profile
    // picker is useless without it.
    return (async () => {
      const catalog = await ensureCatalog();
      if (!catalog) {
        toast("無法載入 Agent Builder 目錄");
        return;
      }
      promptAgentProfileEditor(null, catalog);
    })();
  }

  function promptAgentProfileEditor(existingProfile, catalogArg) {
    const catalog = catalogArg || agentBuilderCatalog;
    if (!catalog) {
      toast("Agent Builder 目錄尚未就緒，請稍候再試");
      return;
    }
    const isNew = !existingProfile;
    const initial = existingProfile || {
      name: "",
      profession_role_id: null,
      model: { tool: (catalog.tools && catalog.tools[0]) || "claude", model_id: "" },
      equipped_skill_ids: [],
      permission_intents: { read: "unspecified", write: "unspecified",
                            test: "unspecified", deploy: "unspecified" },
      enabled: true,
    };

    const nameInput = el("input", { type: "text", maxlength: "200",
      value: initial.name || "" });
    const profSelect = el("select", null,
      el("option", { value: "" }, "（不綁定職業角色）"),
      (catalog.professions || []).map((r) => {
        const opt = el("option", { value: r.role_id || "" },
          `${r.name || r.role_id} (${r.tool || "?"})`);
        if (initial.profession_role_id === r.role_id) opt.setAttribute("selected", "selected");
        return opt;
      }));
    if (!initial.profession_role_id) profSelect.value = "";

    const toolSelect = el("select", null,
      (catalog.tools || []).map((t) => {
        const opt = el("option", { value: t }, t);
        if (initial.model && initial.model.tool === t) opt.setAttribute("selected", "selected");
        return opt;
      }));
    if (initial.model && initial.model.tool) toolSelect.value = initial.model.tool;

    const modelIdInput = el("input", { type: "text",
      placeholder: "例如 opus-4.1、gpt-test；留空視為該工具預設",
      maxlength: String(catalog.model_id_max_length || 200),
      value: (initial.model && initial.model.model_id) || "" });

    // Skill Loadout picker: select with multi-select + a move-in button +
    // remove buttons on the equipped list. Multi-select native is keyboard
    // accessible (Shift/Ctrl+Arrow), so we keep it.
    const skillOptions = catalog.skills || [];
    const skillById = new Map(skillOptions.map((s) => [s.skill_id, s]));
    const equippedIds = new Set(initial.equipped_skill_ids || []);

    const skillPicker = el("select", { size: "8", multiple: "multiple",
      "aria-label": "可加入裝備的技能", style: "width: 100%;" },
      skillOptions.map((s) => el("option", { value: s.skill_id },
        `${s.tool} · ${s.name}${s.activation === "disabled" ? "（停用）" : ""}`)));
    const equippedList = el("ul", { class: "wb-equipped",
      "aria-label": "已裝備技能", style: "list-style: none; padding-left: 0;" });

    function rebuildEquippedList() {
      setKids(equippedList,
        Array.from(equippedIds).length
          ? Array.from(equippedIds).map((sid) => {
              const s = skillById.get(sid);
              const label = s ? `${s.tool} · ${s.name}` : `${sid}（已不存在）`;
              return el("li", { class: "row", style: "justify-content:space-between; padding:2px 4px;" },
                el("span", { class: "small mono" }, label),
                el("button", { class: "btn small", type: "button",
                  on: { click: () => {
                    equippedIds.delete(sid);
                    rebuildEquippedList();
                  } } }, "移除"));
            })
          : [el("li", { class: "small muted", style: "padding:4px;" },
              "未加入任何技能。Equipped ≠ Loaded，僅為意圖記錄")]);
    }
    rebuildEquippedList();

    const addBtn = el("button", { class: "btn small", type: "button",
      on: { click: () => {
        for (const opt of Array.from(skillPicker.selectedOptions)) {
          if (!equippedIds.has(opt.value)) equippedIds.add(opt.value);
        }
        rebuildEquippedList();
      } } }, "加入裝備 →");

    const permissionKeys = catalog.permission_keys || ["read", "write", "test", "deploy"];
    const permissionValues = catalog.permission_values || ["allow", "deny", "unspecified"];
    const intentLabels = { allow: "允許意圖", deny: "拒絕意圖", unspecified: "未定" };
    const intentExplanations = {
      allow: "代表此 Profile 的意圖為允許此操作；並非實際授權",
      deny: "代表此 Profile 的意圖為拒絕此操作；並非實際撤銷授權",
      unspecified: "尚未設定意圖",
    };
    const permSelects = {};
    const permRows = permissionKeys.map((k) => {
      const sel = el("select", null,
        permissionValues.map((v) => {
          const opt = el("option", { value: v }, intentLabels[v] || v);
          if ((initial.permission_intents || {})[k] === v) opt.setAttribute("selected", "selected");
          return opt;
        }));
      sel.value = (initial.permission_intents && initial.permission_intents[k]) || "unspecified";
      permSelects[k] = sel;
      const explain = () => intentExplanations[
        sel.value in intentExplanations ? sel.value : "unspecified"];
      const explainEl = el("span", { class: "small muted" }, explain());
      // Keep the explanation in sync with the current choice (Gate 7 residual).
      sel.addEventListener("change", () => { explainEl.textContent = explain(); });
      return el("div", { class: "row", style: "justify-content:space-between; padding:2px 0;" },
        el("span", null, k, " ", explainEl),
        sel);
    });

    const cancelBtn = el("button", { class: "btn", type: "button",
      on: { click: () => closeModal() } }, "取消");
    const saveBtn = el("button", { class: "btn primary", type: "button",
      on: { click: submitSave } }, isNew ? "建立 Profile" : "儲存修改");

    const disclosures = (catalog.disclosures || []).map((line) =>
      el("li", { class: "small" }, line));

    const modal = el("div", { class: "modal-backdrop", role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "agent-profile-modal-title" },
      el("div", { class: "modal-box", style: "max-width: 720px; max-height: 85vh; overflow-y: auto;" },
        el("h2", { id: "agent-profile-modal-title" },
          isNew ? "建立 Agent Profile" : `編輯 Agent Profile：${existingProfile.name || existingProfile.id}`),
        el("div", { class: "wb-form" },
          el("label", null, "名稱 *", nameInput),
          el("label", null, "職業角色 (僅選用掃描器找到的角色，不會寫回來源)",
            profSelect),
          el("label", null, "模型工具 (Tool ID)", toolSelect),
          el("label", null, "模型設定 (Model ID · 非執行環境)", modelIdInput),
          el("fieldset", { style: "border: 1px solid var(--border, #ccc); padding: 8px; margin: 6px 0;" },
            el("legend", null, "Skill Loadout (裝備清單)"),
            el("div", { class: "small muted", style: "margin-bottom:4px;" },
              "Equipped Skill Loadout ≠ 已進入任何 session；儲存 Profile 不會注入或啟動技能"),
            el("select", null, skillPicker.options
              ? [] : []), // placeholder so the multi-select stays mounted
            skillPicker,
            el("div", { style: "margin: 6px 0;" }, addBtn),
            equippedList),
          el("fieldset", { style: "border: 1px solid var(--border, #ccc); padding: 8px; margin: 6px 0;" },
            el("legend", null, "Permission Intents (意圖 · 僅記錄)"),
            el("div", { class: "small muted", style: "margin-bottom:6px;" },
              "僅為意圖記錄，不會實際執行為底層 CLI 工具權限；數值僅 allow / deny / unspecified"),
            permRows)),
        el("div", { class: "notice info", style: "font-size:12.5px" },
          el("span", { class: "ico" }, "ℹ"),
          el("div", null,
            el("strong", null, "邊界揭露："),
            el("ul", { style: "margin: 4px 0 0 0; padding-left: 16px;" }, disclosures))),
        el("div", { class: "modal-actions" }, cancelBtn, saveBtn)));
    document.body.append(modal);
    const closeModal = withModalA11y(modal, () => modal.remove());
    nameInput.focus();

    async function submitSave() {
      const name = nameInput.value.trim();
      if (!name) {
        toast("請填寫 Profile 名稱");
        nameInput.focus();
        return;
      }
      saveBtn.disabled = true;
      try {
        const payload = {
          name,
          profession_role_id: profSelect.value || null,
          model: { tool: toolSelect.value, model_id: modelIdInput.value.trim() },
          equipped_skill_ids: Array.from(equippedIds),
          permission_intents: permissionKeys.reduce((acc, k) => {
            acc[k] = permSelects[k].value || "unspecified";
            return acc;
          }, {}),
          enabled: existingProfile ? !!existingProfile.enabled : true,
        };
        const path = existingProfile
          ? `/api/agent-profiles/${encodeURIComponent(existingProfile.id)}`
          : `/api/agent-profiles`;
        const res = await api.post(path, payload);
        toast(existingProfile ? "Profile 已儲存" : "Profile 已建立");
        await reloadAgentProfiles();
        selectedProfileId = res.profile.id;
        closeModal();
        renderRightColumn();
      } catch (err) {
        toast((isNew ? "建立失敗：" : "儲存失敗：") + err.message);
        saveBtn.disabled = false;
      }
    }
  }

  // Profile-managed launch (R3 S0): preview what will actually apply, then
  // confirm. The labels come from the server and describe this one launch;
  // they are not Profile settings and none of them is an unbypassable boundary.
  function promptAgentLaunch(p) {
    const titleId = "modal-agent-launch-title";
    let current = null;   // the preview the confirm button refers to
    let busy = false;
    let ackBox = null;    // "I know this Claude Code version is unverified" (only for such previews)
    const workdirInput = el("input", { type: "text", class: "input", id: "agent-launch-workdir",
      placeholder: "家目錄內的資料夾絕對路徑，例如 /Users/you/projects/demo", autocomplete: "off" });
    const commitBox = el("input", { type: "checkbox", id: "agent-launch-commit" });
    const out = el("div", { class: "agent-launch-preview", "aria-live": "polite" });
    const previewBtn = el("button", { class: "btn", type: "button", on: { click: () => doPreview() } }, "產生預覽");
    const confirmBtn = el("button", { class: "btn primary", type: "button", on: { click: () => doLaunch() } }, "確認啟動");
    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    confirmBtn.disabled = true;

    function needsAck(pv) { return Boolean(pv && pv.cli && pv.cli.verified === false); }
    function syncConfirm() {
      confirmBtn.disabled = !current || (needsAck(current) && !(ackBox && ackBox.checked));
    }

    function invalidate(message) {
      current = null;
      ackBox = null;
      confirmBtn.disabled = true;
      setKids(out, message ? el("p", { class: "small muted" }, message) : null);
    }
    workdirInput.addEventListener("input", () => invalidate("輸入已變更，請重新產生預覽。"));
    commitBox.addEventListener("change", () => invalidate("輸入已變更，請重新產生預覽。"));

    const modalElem = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
      el("div", { class: "modal-box modal-wide" },
        el("h2", { id: titleId }, `預覽並啟動：${p.name || p.id}`),
        el("p", { class: "small muted" },
          "啟動前先顯示這次實際會套用的設定與每一項權限的套用程度。確認後才會啟動 Agent。"),
        el("label", { class: "small", for: "agent-launch-workdir" }, "工作目錄"),
        workdirInput,
        el("label", { class: "row small", for: "agent-launch-commit", style: "gap:8px; align-items:flex-start" },
          commitBox,
          el("span", null, "我知道這個設定無法阻止 commit（工作目錄的 .git 在可寫範圍內）。不勾選就無法啟動。")),
        out,
        el("div", { class: "modal-actions" }, cancelBtn, previewBtn, confirmBtn)));
    document.body.append(modalElem);
    const closeModal = withModalA11y(modalElem, () => modalElem.remove());
    workdirInput.focus();

    function renderPreview(pv) {
      const kids = [];
      if (!pv.launchable) {
        kids.push(el("div", { class: "notice warn" },
          el("span", { class: "ico", "aria-hidden": "true" }, "!"),
          el("div", null,
            el("strong", null, "這個 Profile 目前無法啟動"),
            el("ul", { class: "small" }, (pv.reasons || []).map((r) => el("li", null, r.message))))));
      } else {
        kids.push(el("dl", { class: "kv small" },
          el("dt", null, "CLI"), el("dd", { class: "mono" }, `${pv.cli.version} · ${pv.cli.binary}`),
          el("dt", null, "工作目錄"), el("dd", { class: "mono" }, pv.canonical_paths.workdir),
          el("dt", null, "本次暫存區"), el("dd", { class: "mono" }, pv.canonical_paths.scratch),
          el("dt", null, "預覽有效至"), el("dd", null, new Date(pv.expires_at * 1000).toLocaleTimeString())));
        if (needsAck(pv)) kids.push(unverifiedBox(pv));
      }
      kids.push(el("p", { class: "small muted" },
        "以下七項是這次啟動的實際套用程度，由設定與實測證據推導，不是 Profile 的設定值。" +
        "使用者在進階終端仍可自行改變 CLI 行為，沒有一項是不可繞過的邊界。"));
      // The concrete bypass (e.g. "!" shell commands in the terminal) comes from
      // the server's labels; show each distinct text once instead of per label.
      const bypasses = [...new Set(Object.values(pv.derived_labels || {})
        .map((lab) => lab && lab.bypass).filter((b) => typeof b === "string" && b))];
      if (bypasses.length) {
        kids.push(el("div", { class: "notice warn agent-launch-bypass" },
          el("span", { class: "ico", "aria-hidden": "true" }, "!"),
          el("div", { class: "small" }, el("strong", null, "可繞過："), bypasses.join(" "))));
      }
      kids.push(el("div", { class: "agent-launch-labels" },
        Object.entries(pv.derived_labels || {}).map(([name, lab]) =>
          el("div", { class: "agent-launch-label" },
            el("div", { class: "row", style: "justify-content:space-between" },
              el("strong", null, name),
              badge(lab.level, "b-mute plain", "套用程度")),
            el("div", { class: "small" }, lab.note),
            lab.unknown_reason && lab.unknown_reason !== "none" && lab.unknown_reason !== lab.note
              ? el("div", { class: "small muted" }, `未知或未測：${lab.unknown_reason}`) : null))));
      setKids(out, ...kids);
    }

    // Claude Code updates itself often; a release nobody verified yet may still
    // run, but only after the user says so, and it can be verified from here.
    function unverifiedBox(pv) {
      ackBox = el("input", { type: "checkbox", id: "agent-launch-unverified", on: { change: syncConfirm } });
      const verifyBtn = el("button", { class: "btn small", type: "button", on: { click: () => doVerify() } },
        "驗證這個版本");
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
              toast(`Claude Code ${pv.cli.version} 驗證通過`);
              return doPreview();  // labels are now backed by this machine's evidence
            }
            progress.textContent = "驗證沒有通過：" + (status.message || "原因未知") + "。仍可勾選上方選項後啟動。";
            verifyBtn.disabled = false;
            return;
          }
        } catch (err) {
          progress.textContent = "無法驗證：" + err.message;
          verifyBtn.disabled = false;
        }
      }
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
        renderPreview(res.preview);
        syncConfirm();
      } catch (err) {
        invalidate("無法產生預覽：" + err.message);
      } finally {
        busy = false;
        previewBtn.disabled = false;
        // Disabling the focused button moved focus to <body>, outside the dialog,
        // so Escape no longer reached it (S0 browser QA). Put focus back inside.
        const active = document.activeElement;
        if (!active || active === document.body || !modalElem.contains(active)) {
          previewBtn.focus();  // not the confirm button: a stray Enter must not launch
        }
      }
    }

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
        toast("已啟動（Profile 受管）");
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
    if (!confirm(`確定要刪除 Agent Profile「${p.name || p.id}」嗎？此動作不可回復。`)) return;
    api.post(`/api/agent-profiles/${encodeURIComponent(p.id)}/delete`, {})
      .then(async () => {
        toast("Profile 已刪除");
        await reloadAgentProfiles();
        if (selectedProfileId === p.id) selectedProfileId = null;
        renderRightColumn();
      })
      .catch((err) => toast("刪除失敗：" + err.message));
  }

  function renderAgentTabContent() {
    const content = el("div", { class: "wb-tab-content wb-agent-builder" });
    const header = el("div", { class: "row", style: "justify-content:space-between" },
      el("h3", { style: "margin:0" }, "Agent Builder"),
      prov({ origin: "user", detail: "主控台儲存的 Profile · 與 AgentRole 不同" }));
    const createBtn = el("button", { class: "btn primary", type: "button",
      on: { click: () => renderAgentProfileEditor(true) } }, "+ 建立 Agent Profile");

    const sub = el("div", { class: "small muted", style: "margin: 4px 0;" },
      "Profile 是一份使用你自選職業、模型工具與裝備清單的設定組合，");
    const sub2 = el("div", { class: "small muted", style: "margin-bottom: 8px;" },
      "與掃描到的 AgentRole 名單（只讀）並存。Equipped Skill Loadout 僅為意圖，");

    const selected = agentProfiles.find((p) => p.id === selectedProfileId);

    const split = el("div", { class: "wb-split" });
    // Sizing lives in style.css (.wb-agent-builder container query) so the
    // split can stack when the right column is narrow; inline min-width here
    // previously crushed the detail column to ~40px (Gate 7 finding).
    const listCol = el("div", { class: "wb-col-left" });
    const detailCol = el("div", { class: "wb-col-right" });

    if (agentProfiles.length === 0) {
      setKids(listCol, emptyState("尚未建立任何 Profile", null));
    } else {
      setKids(listCol,
        el("div", { class: "wb-list" }, agentProfiles.map(renderAgentProfileListItem)));
    }
    if (selected) {
      setKids(detailCol, renderAgentProfileDetail(selected));
    } else {
      setKids(detailCol,
        emptyState("請從左側選取一個 Profile，或建立新的", null),
        el("div", { class: "notice info", style: "font-size:12.5px; margin-top:8px;" },
          el("span", { class: "ico" }, "ℹ"),
          el("div", null,
            "Profile 只會寫入主控台狀態目錄 (",
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
        "儲存後不會啟動、重啟或注入任何東西；權限意圖僅為意圖記錄。"),
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
  function promptCreateTask() {
    let modal;
    const titleInput = el("input", { type: "text", placeholder: "輸入任務標題 (必填)", required: true });
    const tmplSelect = el("select", {
      on: {
        change: (e) => {
          const t = templates[e.target.value] || {};
          if (t.goal) goalInput.value = t.goal;
          if (t.scope) scopeInput.value = (t.scope || []).join("\n");
          if (t.out_of_scope) outOfScopeInput.value = (t.out_of_scope || []).join("\n");
          if (t.deliverables) deliverablesInput.value = (t.deliverables || []).join("\n");
          if (t.acceptance_criteria) criteriaInput.value = (t.acceptance_criteria || []).join("\n");
          if (t.evidence) evidenceInput.value = (t.evidence || []).join("\n");
        },
      },
    }, Object.keys(templates).map((k) => el("option", { value: k }, `${templates[k].title || k} (${k})`)));

    const defaultTmpl = templates["custom"] || {};
    const goalInput = el("textarea", { rows: "3", placeholder: "完成此任務的主要目標" }, defaultTmpl.goal || "");
    const scopeInput = el("textarea", { rows: "2", placeholder: "允許變更的檔案或模組 (每行一項)" }, (defaultTmpl.scope || []).join("\n"));
    const outOfScopeInput = el("textarea", { rows: "2", placeholder: "不可變更的範圍 (每行一項)" }, (defaultTmpl.out_of_scope || []).join("\n"));
    const deliverablesInput = el("textarea", { rows: "2", placeholder: "預期交付之成果物 (每行一項)" }, (defaultTmpl.deliverables || []).join("\n"));
    const criteriaInput = el("textarea", { rows: "2", placeholder: "驗收標準 (每行一項)" }, (defaultTmpl.acceptance_criteria || []).join("\n"));
    const evidenceInput = el("textarea", { rows: "2", placeholder: "驗證證據 (每行一項)" }, (defaultTmpl.evidence || []).join("\n"));

    const cancelBtn = el("button", { class: "btn", type: "button", on: { click: () => closeModal() } }, "取消");
    const saveBtn = el("button", { class: "btn primary", type: "button", on: { click: submitSave } }, "建立任務卡");

    modal = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "task-create-modal-title" },
      el("div", { class: "modal-box", style: "max-width: 620px; max-height: 85vh; overflow-y: auto;" },
        el("h2", { id: "task-create-modal-title" }, "建立新任務卡 (Task Card)"),
        el("div", { class: "wb-form" },
          el("label", null, "任務範本", tmplSelect),
          el("label", null, "任務標題 *", titleInput),
          el("label", null, "目標 (Goal)", goalInput),
          el("label", null, "範圍 (Scope，每行一項)", scopeInput),
          el("label", null, "範圍外 (Out of Scope，每行一項)", outOfScopeInput),
          el("label", null, "交付物 (Deliverables，每行一項)", deliverablesInput),
          el("label", null, "驗收條件 (Acceptance Criteria，每行一項)", criteriaInput),
          el("label", null, "實測證據 (Evidence，每行一項)", evidenceInput)),
        el("div", { class: "modal-actions" }, cancelBtn, saveBtn)));
    document.body.append(modal);

    // Capture the opener via withModalA11y before moving focus into the
    // dialog, so close/Escape restores focus to whatever opened the modal,
    // not to titleInput (which is about to be removed with the dialog).
    // withModalA11y also registers this dialog, so view cleanup (navigating
    // away mid-dialog) closes it the proper way instead of leaving it
    // orphaned with the rest of the page still marked inert.
    const closeModal = withModalA11y(modal, () => modal.remove());
    titleInput.focus();

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
          template: tmplSelect.value,
          goal: goalInput.value.trim(),
          scope: scopeInput.value.trim(),
          out_of_scope: outOfScopeInput.value.trim(),
          deliverables: deliverablesInput.value.trim(),
          acceptance_criteria: criteriaInput.value.trim(),
          evidence: evidenceInput.value.trim(),
          associated_pane_id: activePaneId || null,
        };
        const res = await api.post("/api/tasks", payload);
        tasksList.unshift(res.task);
        activeTaskId = res.task.id;
        toast("任務卡建立成功");
        closeModal();
        renderRightColumn();
      } catch (err) {
        toast("建立失敗：" + err.message);
        saveBtn.disabled = false;
      }
    }
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
          el("label", null, "實測證據 (Evidence，每行一項)", evidenceInput)),
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
    crumbs([["Agent 團隊", "#/team"], ["終端工作台"]]),
    toolbar,
    shell
  );
}

// ---------- router ---------------------------------------------------------

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
  clearInterval(liveTimer);
  try {
    if (top === "home") await viewHome();
    else if (top === "workbench") await viewWorkbench(parts[1] ? decodeURIComponent(parts[1]) : null, params.task, params.profile);
    else if (top === "armory") await viewArmory();
    else if (top === "skills" && parts[1]) await viewSkillDetail(parts[1]);
    else if (top === "skills") await viewSkills(params);
    else if (top === "team" && parts[1] === "role") await viewRole(parts[2]);
    else if (top === "team") await viewTeam();
    else if (top === "projects") await viewProjects(parts[1]);
    else if (top === "settings") await viewSettings();
    else if (top === "term" && parts[1]) await viewTerminal(decodeURIComponent(parts[1]));
    else if (top === "terminals") await viewTerminals();
    else setKids($main(), emptyState("找不到這個頁面", null));
  } catch (e) {
    setKids($main(), e.status === 401 ? authRequiredView() : notice("bad", "載入失敗：" + e.message));
  }
  // Live pages refresh their data quietly; they re-render only when nothing
  // is focused inside main, so typing and scrolling are never interrupted.
  // Home refreshes only its attention block, so the search box keeps focus.
  liveTick = null;
  if (top === "home") {
    liveTick = async () => {
      const before = JSON.stringify(D.live.attention);
      await loadLive();
      const box = document.getElementById("h-att-wrap");
      if (box && JSON.stringify(D.live.attention) !== before) setKids(box, attentionSection());
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
// Coming back to this tab: refresh at once instead of waiting.
document.addEventListener("visibilitychange", () => { if (!document.hidden && liveTick) liveTick(); });
// The skip link moves focus only; it must not become a route ("#main" is not a page).
function skipToMain(e) {
  if (e) e.preventDefault();
  const main = $main();
  main.focus({ preventScroll: true });
  main.scrollIntoView({ block: "start" });
}
document.querySelector("a.skip").addEventListener("click", skipToMain);
window.addEventListener("hashchange", () => {
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
async function bootstrap() {
  const m = /^#auth=([A-Za-z0-9_-]{20,200})$/.exec(location.hash || "");
  if (m) {
    history.replaceState(null, "", location.pathname + location.search + "#/");
    try { await api.post("/api/auth", { token: m[1] }); }
    catch (_) { /* the first API call then shows how to open VBear */ }
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
    computeTaskProvenance,
    taskStatusBadge,
    TASK_STATUS_LABELS,
    viewWorkbench,
    viewTerminal,
    shellPanes,
    shellLabel,
    shellTabLabels,
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
  };
}
