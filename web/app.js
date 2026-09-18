"use strict";
/* SID Herdr Console — UI.
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
function append(node, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
function setKids(node, ...kids) { node.replaceChildren(); return append(node, kids); }
const $main = () => document.getElementById("main");

const api = {
  async get(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
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
    for (const t of terms) {
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
        el("div", { class: "card-title" }, s.name),
        el("div", { class: "card-sub mono" }, s.invoke_name !== s.name ? `呼叫名稱 ${s.invoke_name}` : SCOPE[s.scope] || s.scope)),
      actBadge(s.activation)),
    s.description && s.description.value
      ? el("p", { class: "clamp" }, firstSentence(s.description.value, 170))
      : el("p", { class: "muted" }, "作者沒有提供用途描述"),
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
      el("button", { class: "btn small", on: { click: () => focusTerminal(x) }, title: "只切換 herdr 顯示的分頁，不會對 Agent 送出任何輸入" }, "切到這個 Terminal")));
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
  await Promise.all([loadStatic(), loadLive()]);
  const L = D.live;
  const main = $main();
  const input = el("input", { type: "search", placeholder: "想做什麼？例如：網站安全檢查、做簡報、剪影片、部署…", "aria-label": "用途搜尋技能" });
  const results = el("div", { class: "grid", style: "margin-top:14px" });
  const runSearch = () => {
    const q = input.value.trim();
    if (!q) { setKids(results, ); return; }
    const hits = searchSkills(q, D.skills.filter((s) => s.activation === "active")).slice(0, 6);
    setKids(results, ...(hits.length ? hits.map((h) => skillCard(h.s, h.why)) : [emptyState("沒有找到可使用的技能", "試試別的說法，或到技能庫顯示全部來源")]),
      hits.length ? el("a", { class: "btn", href: `#/skills?q=${encodeURIComponent(q)}`, style: "align-self:start" }, "在技能庫看全部結果 →") : null);
  };
  input.addEventListener("input", runSearch);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") location.hash = `#/skills?q=${encodeURIComponent(input.value.trim())}`; });
  const examples = ["網站安全", "做簡報", "剪影片", "部署網站", "寫小說", "設計品牌"];

  const attention = (L.attention || []).map((id) => L.sessions.find((s) => s.terminal_id === id)).filter(Boolean);
  const recentProjects = (L.projects || []).filter((p) => p.live_session_ids.length || p.last_activity).slice(0, 6);
  const problemSkills = (D.overview.skills_with_problems || []).map((id) => D.byId.get(id)).filter(Boolean);

  setKids(main, 
    el("h1", null, "我的工作台"),
    el("p", { class: "lede" }, "先看需要你處理的事，再找適合這次任務的技能。"),
    staleNotice(),
    herdrNotice(),
    el("section", { class: "section", "aria-labelledby": "h-att" },
      sectionHead("需要你處理", attention.length ? `${attention.length} 個 Terminal 在等你` : null),
      attention.length ? el("div", { class: "grid", id: "h-att" }, attention.map(sessionCard))
        : emptyState(L.herdr && L.herdr.available ? "目前沒有等你回覆或待查看的工作" : "herdr 未連線，無法判斷", null)),
    el("section", { class: "section" },
      sectionHead("找技能", "用你的話描述要做的事，不需要記得技能名稱"),
      el("div", { class: "search" }, input),
      el("div", { class: "search-hint" }, el("span", { class: "small muted" }, "試試："),
        examples.map((w) => el("button", { type: "button", on: { click: () => { input.value = w; runSearch(); input.focus(); } } }, w))),
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
  await loadStatic();
  const f = Object.assign({ q: "", tool: "", act: "active", scope: "", cat: "", view: store.get("view", "card") }, store.get("skillFilters", {}), params);
  if (params.q !== undefined) f.q = params.q;
  const main = $main();

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
  const save = () => store.set("skillFilters", { tool: f.tool, act: f.act, scope: f.scope, cat: f.cat });

  function draw() {
    let pool = D.skills;
    if (f.tool) pool = pool.filter((s) => s.tool === f.tool);
    if (f.act) pool = pool.filter((s) => s.activation === f.act);
    if (f.scope) pool = pool.filter((s) => s.scope === f.scope);
    if (f.cat) pool = pool.filter((s) => (s.categories || []).some((c) => c.id === f.cat));
    const hits = searchSkills(f.q, pool);
    count.textContent = `${hits.length} / ${D.skills.length} 個技能紀錄`;
    if (!hits.length) {
      setKids(out, emptyState("沒有符合條件的技能", f.act === "active" ? "目前只顯示「可使用」的技能，可把狀態改成「全部」再找一次" : "試著放寬篩選條件"));
      return;
    }
    if (f.view === "list") {
      setKids(out, el("div", { class: "panel table-wrap" }, el("table", { class: "list" },
        el("thead", null, el("tr", null, ["名稱", "用途", "工具", "範圍", "狀態"].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", null, hits.slice(0, 400).map(({ s, why }) => el("tr", null,
          el("td", null, el("a", { href: `#/skills/${s.skill_id}` }, s.name), (s.duplicate_of || []).length ? el("div", null, badge(`同名 ${s.duplicate_of.length + 1} 份`, "b-warn")) : null),
          el("td", null, firstSentence(s.description && s.description.value, 110) || el("span", { class: "muted" }, "未提供"), why.length ? el("div", { class: "small muted" }, "符合：" + why.join("、")) : null),
          el("td", null, TOOL[s.tool] || s.tool),
          el("td", null, SCOPE[s.scope] || s.scope, s.origin_package && s.origin_package.version ? el("div", { class: "small muted" }, s.origin_package.version) : null),
          el("td", null, actBadge(s.activation))))))));
    } else {
      setKids(out, el("div", { class: "grid" }, hits.slice(0, 240).map(({ s, why }) => skillCard(s, why))),
        hits.length > 240 ? el("p", { class: "small muted" }, `只顯示前 240 筆，請用搜尋或篩選縮小範圍。`) : null);
    }
  }
  q.addEventListener("input", () => { f.q = q.value; history.replaceState(null, "", `#/skills${f.q ? "?q=" + encodeURIComponent(f.q) : ""}`); draw(); });

  const actOptions = [["active", "可使用"], ["", "全部"], ...Object.entries(ACT).filter(([k]) => k !== "active").map(([k, v]) => [k, v[0]])];
  setKids(main, 
    el("h1", null, "技能庫"),
    el("p", { class: "lede" }, "所有已盤點的技能。預設只顯示目前真的能用的；舊版快取、停用與市集副本可從「狀態」切換查看。"),
    staleNotice(),
    el("div", { class: "search" }, q),
    el("div", { class: "toolbar" },
      sel("狀態", "act", actOptions),
      sel("工具", "tool", [["", "全部"], ["claude", "Claude Code"], ["codex", "Codex CLI"], ["shared", "skills CLI"]]),
      sel("用途", "cat", [["", "全部"], ...D.categories.map((c) => [c.id, c.label])]),
      sel("範圍", "scope", [["", "全部"], ...Object.entries(SCOPE)]),
      seg, count),
    el("div", { class: "legend", style: "margin-bottom:12px" },
      el("span", null, "用途分類為", el("b", null, "自動整理"), "（依描述關鍵字），滑過標籤可看到命中的字。")),
    out);
  draw();
}

async function viewSkillDetail(id) {
  await loadStatic();
  const main = $main();
  setKids(main, el("p", { class: "loading" }, "載入中…"));
  let d;
  try { d = await api.get(`/api/skills/${encodeURIComponent(id)}`); }
  catch (e) { setKids(main, crumbs([["技能庫", "#/skills"]]), notice("bad", e.message)); return; }
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
    el("div", { class: "row" }, el("h1", null, s.name), actBadge(s.activation), toolTag(s.tool)),
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
  await Promise.all([loadStatic(), loadLive()]);
  const main = $main();
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
          el("td", null, el("button", { class: "btn small", on: { click: () => focusTerminal(x) } }, "切換")))))))
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
  await Promise.all([loadStatic(), loadLive()]);
  const r = D.roles.find((x) => x.role_id === id);
  const main = $main();
  if (!r) { setKids(main, crumbs([["Agent 團隊", "#/team"]]), notice("bad", "找不到這個角色（索引可能已更新）")); return; }
  const sessions = r.kind === "cli" ? D.live.sessions.filter((s) => s.agent === r.tool) : [];
  const field = (title, src) => src && (src.value || src.origin !== "missing")
    ? el("div", { class: "field" }, el("h3", null, title, prov(src)), src.value ? el("div", { class: "body" }, String(src.value)) : el("div", { class: "empty" }, src.detail)) : null;
  const skills = r.skills || [];
  const q = el("input", { type: "search", placeholder: "在這個角色的技能中搜尋", "aria-label": "搜尋角色技能" });
  const list = el("div", { class: "grid" });
  const draw = () => {
    const pool = skills.map((x) => D.byId.get(x.skill_id)).filter(Boolean);
    const hits = searchSkills(q.value, pool);
    setKids(list, ...(hits.length ? hits.slice(0, 120).map((h) => skillCard(h.s, h.why)) : [emptyState("沒有符合的技能", null)]));
  };
  q.addEventListener("input", draw);

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
  await Promise.all([loadStatic(), loadLive()]);
  const L = D.live;
  const main = $main();
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
  await loadStatic();
  const main = $main();
  const c = await api.get("/api/config");
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

// ---------- router ---------------------------------------------------------

let liveTimer = null;
function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = raw.split("?");
  const params = Object.fromEntries(new URLSearchParams(qs || ""));
  return { parts: path.split("/").filter(Boolean), params };
}

async function route() {
  const { parts, params } = parseHash();
  const top = parts[0] || "home";
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === top) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  clearInterval(liveTimer);
  try {
    if (top === "home") await viewHome();
    else if (top === "skills" && parts[1]) await viewSkillDetail(parts[1]);
    else if (top === "skills") await viewSkills(params);
    else if (top === "team" && parts[1] === "role") await viewRole(parts[2]);
    else if (top === "team") await viewTeam();
    else if (top === "projects") await viewProjects(parts[1]);
    else if (top === "settings") await viewSettings();
    else setKids($main(), emptyState("找不到這個頁面", null));
  } catch (e) {
    setKids($main(), notice("bad", "載入失敗：" + e.message));
  }
  // Live pages refresh their data quietly; they re-render only when nothing
  // is focused inside main, so typing and scrolling are never interrupted.
  if (top === "team" || top === "projects") {
    liveTimer = setInterval(async () => {
      if (document.hidden) return;
      const before = JSON.stringify(D.live && D.live.sessions.map((s) => [s.terminal_id, s.status, s.skills_used.length]));
      await loadLive();
      const after = JSON.stringify(D.live.sessions.map((s) => [s.terminal_id, s.status, s.skills_used.length]));
      const busy = $main().contains(document.activeElement) && document.activeElement !== $main();
      if (before !== after && !busy) { const y = scrollY; await route(); scrollTo(0, y); }
    }, 5000);
  }
}

setTheme(store.get("theme", "auto"));
window.addEventListener("hashchange", () => { scrollTo(0, 0); route(); document.getElementById("main").focus({ preventScroll: true }); });
route();
