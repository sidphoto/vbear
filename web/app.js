"use strict";
/* SID Console for Herdr — UI.
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

// Mirrors TERM_MIN_DIM/TERM_MIN_ROWS in sidconsole/server.py. A terminal
// narrower or shorter than this cannot render anything usable, and since a
// resize is forwarded to the pane it would wreck the native herdr window too.
const TERM_MIN_COLS = 20;
const TERM_MIN_ROWS = 5;
const TERMINAL_VISIBLE_SCREEN_NOTICE = "畫面歷史：此網頁只同步 Herdr 目前可視畫面，不提供回捲歷史；需要較早內容時，請至 Herdr 原生視窗查看。";

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
      // Herdr streams absolute-position redraws of the current screen, not
      // newline/scroll events. xterm therefore cannot build truthful history
      // from this feed; keeping a nominal scrollback buffer would promise a
      // capability the live protocol does not provide.
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
    const res = await fetch(path, { headers: { Accept: "application/json", "X-SID-Console": "1" } });
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-SID-Console": "1" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  },
};

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
function statusBadge(s) { const [l, c] = STATUS[s] || STATUS.unknown; return badge(l, c, `herdr 回報狀態：${s}`); }
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
  catch (e) { D.live = { error: e.message, sessions: [], projects: [], attention: [], usage: { sessions: [] }, herdr: { available: false, problems: [e.message] } }; }
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
      actBadge(s.activation)),
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
          el("div", { class: "card-sub" }, x.role_label_source ? "角色名稱來自 herdr 分頁" : "未命名分頁"))),
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
      el("a", { class: "btn small primary", href: `#/term/${encodeURIComponent(x.pane_id)}`, title: "開啟終端機串流（預設僅觀看，非獨占控制）" }, "開啟終端"),
      el("button", { class: "btn small", on: { click: () => focusTerminal(x) }, title: "只切換 herdr 顯示的分頁，不會對 Agent 送出任何輸入" }, "切換焦點")));
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

async function focusTerminal(x) {
  try {
    const r = await api.post("/api/focus", { target: x.pane_id });
    toast(r.ok ? `已在 herdr 切換到「${x.role_label || x.pane_id}」` : `無法切換：${r.error}`);
  } catch (e) { toast("無法切換：" + e.message); }
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
  return notice("bad", "設定檔（config.json）無法讀取。你原本選的掃描範圍目前不明，所以主控台已關閉所有掃描來源，也不會重新掃描，畫面上是先前的索引。請修復或刪除 ~/.sid-console/config.json 後重新啟動主控台；原檔不會被覆寫。");
}
function herdrNotice() {
  const h = D.live && D.live.herdr;
  if (!h) return null;
  if (!h.available) return notice("warn", ["無法連線到 herdr，工作中的 Terminal 資訊暫不可用。", (h.problems || []).join("；")].join(" "));
  return null;
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
    herdrNotice(),
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
      : emptyState(L.herdr && L.herdr.available ? "目前沒有等你回覆或待查看的工作" : "herdr 未連線，無法判斷", null),
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
  const sel = (label, key, options) => {
    const s = el("select", { "aria-label": label, on: { change: () => { f[key] = s.value; save(); draw(); } } },
      options.map(([v, t]) => el("option", { value: v, selected: f[key] === v }, t)));
    return el("label", null, label, s);
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
    el("h1", null, "技能庫"),
    el("p", { class: "lede" }, "所有已盤點的技能。預設只顯示目前真的能用的；舊版快取、停用與市集副本可從「狀態」切換查看。"),
    corruptNotice(),
    staleNotice(),
    el("div", { class: "search" }, q),
    el("div", { class: "toolbar" },
      sel("狀態", "act", actOptions),
      sel("工具", "tool", [["", "全部"], ["claude", "Claude Code"], ["codex", "Codex CLI"], ["shared", "skills CLI"]]),
      sel("用途", "cat", [["", "全部"], ...D.categories.map((c) => [c.id, c.label])]),
      sel("範圍", "scope", [["", "全部"], ...Object.entries(SCOPE)]),
      sel("我的註記", "mine", [["", "不限"], ["*", "有註記的"], ...myTags.map((t) => [t, "#" + t])]),
      seg, count),
    el("div", { class: "legend", style: "margin-bottom:12px" },
      el("span", null, "用途分類為", el("b", null, "自動整理"), "（依描述關鍵字），滑過標籤可看到命中的字。")),
    out);
  draw();
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
            el("a", { class: "btn small primary", href: `#/term/${encodeURIComponent(x.pane_id)}`, style: "margin-right:6px", title: "開啟終端機串流" }, "終端"),
            el("button", { class: "btn small", on: { click: () => focusTerminal(x) } }, "切換")))))))
    : el("div", { class: "grid" }, sessions.map(sessionCard));

  const seg = el("div", { class: "seg", role: "group", "aria-label": "顯示方式" },
    [["card", "角色卡"], ["list", "表格"]].map(([v, t]) => el("button", { type: "button", "aria-pressed": String(tview === v), on: { click: () => { store.set("teamView", v); viewTeam(); } } }, t)));

  setKids(main, 
    el("h1", null, "Agent 團隊"),
    el("p", { class: "lede" }, "上半部是現在正在工作的 Terminal；下半部是可以重複使用的角色設定。兩者不同：一個角色可以同時有多個工作階段。"),
    herdrNotice(),
    el("section", { class: "section" },
      sectionHead("工作中的 Terminal", `${sessions.length} 個，來自 herdr`, seg),
      sessions.length ? liveBlock : emptyState("沒有工作中的 Agent", L.herdr && L.herdr.available ? "在 herdr 中啟動 Claude Code 或 Codex 後會出現在這裡" : "herdr 未連線")),
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
          el("dt", null, "工作中"), el("dd", null, r.kind === "cli" ? `${sessions.length} 個 Terminal` : "herdr 目前無法辨識子代理的執行個體")),
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
    el("p", { class: "lede" }, "依工作目錄的 git 儲存庫歸類。專案是目標與資料歸屬；herdr 的 workspace 是實際工作的畫面，兩者不一定一一對應。"),
    herdrNotice(),
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
        el("span", { class: "small muted" }, "herdr workspace "), el("b", null, ws),
        el("ul", { class: "tree" }, list.map((s) => el("li", { class: "row" },
          el("b", null, s.role_label || s.pane_id), statusBadge(s.status), el("span", { class: "tag" }, TOOL[s.agent] || s.agent),
          (s.skills_used || []).slice(0, 3).map(usedChip),
          el("button", { class: "btn small", on: { click: () => focusTerminal(s) } }, "切換"))))))) : el("p", { class: "small muted" }, "沒有工作中的 Terminal。"),
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
            el("li", null, "「切到這個 Terminal」只切換 herdr 的畫面，不會送出任何輸入給 Agent。"))),
        advanced ? el("div", { class: "panel pad" },
          el("h2", { style: "margin-bottom:8px" }, "診斷"),
          el("dl", { class: "kv small" },
            el("dt", null, "herdr"), el("dd", { class: "mono" }, (D.live && D.live.herdr && D.live.herdr.version) || "未連線", " ", home(c.herdr_binary || "")),
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

async function viewTerminal(paneId) {
  const token = seq;
  cleanupActiveTerminal();
  await Promise.all([loadStatic(), loadLive()]);
  const main = claim(token);
  if (token !== seq) return;

  const session = (D.live.sessions || []).find((s) => s.pane_id === paneId);
  const roleName = session ? (session.role_label || session.agent || paneId) : paneId;
  const toolName = session ? (TOOL[session.agent] || session.agent) : "Terminal";
  const project = session ? (D.live.projects || []).find((p) => p.project_id === session.project_id) : null;

  let mode = "observe";
  let connState = "connecting";
  let closedReason = "";
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
    if (mode === "control") {
      notices.push(notice("warn", "⚠️ 目前處於接管控制模式。請注意：接管取得的是共享輸入通道，不會鎖定原生 Herdr 視窗。兩端輸入可能交錯送出，操作 Agent 時請留意。"));
    }
    if (connState === "closed") {
      notices.push(notice("info", `終端機連線已關閉${closedReason ? "：" + closedReason : ""}。如需重新開啟請點選右上方「重新連線」。`));
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
    if (shouldShowTerminalRetryAction({ isDisposed, termReady, connState })) {
      actions.push(el("button", { class: "btn small primary", type: "button", on: { click: manualReconnect } }, "重新連線"));
    }
    actions.push(el("button", { class: "btn small", type: "button", on: { click: () => focusTerminal({ pane_id: paneId, role_label: roleName }) }, title: "在 herdr 視窗聚焦此 Terminal" }, "在 herdr 切換焦點"));
    actions.push(el("a", { class: "btn small", href: "#/team" }, "返回團隊"));
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
          el("div", null, "重要提醒：接管操作為共享輸入通道，不會鎖定原生 Herdr 視窗。原生視窗與瀏覽器均可打字，兩端輸入可能會互相交錯。若 Agent 正在執行任務，請避免非預期的干擾。")),
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
          toast("已接管終端操作（兩端可同時輸入）");
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
          "X-SID-Console": "1",
        },
        signal,
      });

      if (!res.ok) {
        if (res.status === 404) {
          connState = "closed";
          closedReason = "此 Terminal 不存在或該 Pane 已結束 (404)";
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

  setKids(main,
    crumbs([["Agent 團隊", "#/team"], [`終端機 (${paneId})`]]),
    el("div", { class: "term-head" },
      el("div", { class: "term-meta" },
        el("div", { class: "row" },
          el("h1", null, roleName),
          toolTag(session ? session.agent : "terminal"),
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
      el("span", null, el("b", null, "觀看模式"), "：預設唯讀轉送畫面，不攔截鍵盤，亦不對 Agent 送出輸入"),
      el("span", null, el("b", null, "接管操作"), "：經確認後可由瀏覽器打字，但非獨占控制，原生 Herdr 視窗仍可同時操作"),
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

async function viewWorkbench(initialPaneId, initialTaskId) {
  const token = seq;
  cleanupActiveTerminal();
  const [staticData, liveData, tasksRes, templatesRes, govRes] = await Promise.all([
    loadStatic(),
    loadLive(),
    api.get("/api/tasks").catch(() => ({ ok: false, tasks: [] })),
    api.get("/api/task-templates").catch(() => ({ ok: false, templates: {} })),
    api.get("/api/governance").catch(() => ({ ok: false })),
  ]);

  const main = claim(token);
  if (token !== seq) return;

  const sessions = (D.live && D.live.sessions) || [];
  let tasksList = (tasksRes && tasksRes.tasks) || [];
  const templates = (templatesRes && templatesRes.templates) || {};
  const govData = govRes || {};

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
  let rightCollapsed = store.get("wb:right_collapsed", false);
  let focusMode = false;
  let activeTab = "task"; // "task" | "agent" | "project" | "global"

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
          el("dt", null, "已用技能"), el("dd", null, skillsUsed.length ? skillsUsed.join("、") : "無")),
        el("div", { class: "row", style: "margin-top:4px" },
          el("button", {
            class: "btn small",
            type: "button",
            on: { click: () => focusTerminal({ pane_id: activePaneId, role_label: roleName }) },
            title: "在 herdr 視窗聚焦此 Terminal",
          }, "在 herdr 切換焦點")));
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
        notices.push(notice("warn", "⚠️ 目前處於接管控制模式。請注意：接管取得的是共享輸入通道，不會鎖定原生 Herdr 視窗。兩端輸入可能交錯送出，操作 Agent 時請留意。"));
      }
      if (connState === "closed") {
        notices.push(notice("info", `終端機連線已關閉${closedReason ? "：" + closedReason : ""}。如需重新開啟請點選右上方「重新連線」。`));
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
      if (shouldShowTerminalRetryAction({ isDisposed, termReady, connState })) {
        actions.push(el("button", { class: "btn small primary", type: "button", on: { click: manualReconnect } }, "重新連線"));
      }
      actions.push(el("button", {
        class: "btn small",
        type: "button",
        on: { click: () => setFocusMode(!focusMode) },
        title: focusMode ? "退出專注模式 (Esc)" : "開啟專注模式 (收合側欄)",
      }, focusMode ? "退出專注" : "⛶ 專注模式"));

      actions.push(el("a", { class: "btn small", href: `#/term/${encodeURIComponent(currentPane)}`, title: "以獨立視窗開啟" }, "獨立視窗"));
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
            el("div", null, "重要提醒：接管操作為共享輸入通道，不會鎖定原生 Herdr 視窗。原生視窗與瀏覽器均可打字，兩端輸入可能會互相交錯。若 Agent 正在執行任務，請避免非預期的干擾。")),
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
            toast("已接管終端操作（兩端可同時輸入）");
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
            "X-SID-Console": "1",
          },
          signal,
        });

        if (!res.ok) {
          if (res.status === 404) {
            connState = "closed";
            closedReason = "此 Terminal 不存在或該 Pane 已結束 (404)";
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
          el("span", null, el("b", null, "接管操作"), "：經確認後可由瀏覽器打字，但非獨占控制，原生 Herdr 視窗仍可同時操作"),
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

  // Right Tab: [A] Agent Profile
  function renderAgentTabContent() {
    const activeSession = sessions.find((s) => s.pane_id === activePaneId);
    const content = el("div", { class: "wb-tab-content" });
    if (!activeSession) {
      return append(content, emptyState("目前沒有選取中的 Agent", null));
    }
    const roleName = activeSession.role_label || activeSession.agent || activePaneId;
    const skillsUsed = activeSession.skills_used || [];

    return append(content,
      el("div", { class: "row", style: "justify-content:space-between" },
        el("h3", { style: "margin:0" }, roleName),
        prov({ origin: "runtime", detail: "執行觀察 · 唯讀" })),
      el("dl", { class: "kv small" },
        el("dt", null, "職業角色"), el("dd", null, activeSession.agent),
        el("dt", null, "模型大腦"), el("dd", { class: "mono" }, activeSession.model || "—"),
        el("dt", null, "已用裝備"), el("dd", null, skillsUsed.length ? skillsUsed.join("、") : "無")),
      el("div", { class: "notice info", style: "font-size:12.5px" },
        el("span", { class: "ico" }, "ℹ"),
        el("div", null, "A 層於本階段管理角色身分、模型與武器裝備（Skill Loadout）觀察，為唯讀資訊展示。"))
    );
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
    else if (top === "workbench") await viewWorkbench(parts[1] ? decodeURIComponent(parts[1]) : null, params.task);
    else if (top === "skills" && parts[1]) await viewSkillDetail(parts[1]);
    else if (top === "skills") await viewSkills(params);
    else if (top === "team" && parts[1] === "role") await viewRole(parts[2]);
    else if (top === "team") await viewTeam();
    else if (top === "projects") await viewProjects(parts[1]);
    else if (top === "settings") await viewSettings();
    else if (top === "term" && parts[1]) await viewTerminal(decodeURIComponent(parts[1]));
    else setKids($main(), emptyState("找不到這個頁面", null));
  } catch (e) {
    setKids($main(), notice("bad", "載入失敗：" + e.message));
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
  if (liveTick) liveTimer = setInterval(() => { if (!document.hidden) liveTick(); }, 5000);
}

setTheme(store.get("theme", "auto"));
// Coming back from herdr to this tab: refresh at once instead of waiting.
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
route();

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
