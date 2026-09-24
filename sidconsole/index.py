"""Build the console's view of skills, roles, sessions and projects.

Two layers, because they change at different speeds:
  static  - skills, roles, relations. Built by an explicit scan and cached on
            disk; the UI never triggers a file walk while rendering.
  live    - herdr sessions, usage evidence, projects. Cheap and incremental,
            rebuilt on request with a short TTL.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path

from . import categories
from . import config as cfg
from .bridge import herdr
from .model import (
    ACT_ACTIVE, ACT_UNKNOWN, AgentRole, SkillRecord, Sourced, stable_id,
)
from .scan import claude, codex, shared, usage
from .scan.document import MAX_FILE_BYTES

def HOME() -> Path:
    """The current user's home directory.

    Resolved on every call so that tests which mutate ``os.environ['HOME']``
    after import (the standard way this suite isolates each scenario into a
    fake ``HOME``) see the new value instead of the one captured at module
    import time. Outside of tests this is identical to ``Path.home()``.
    """
    return Path.home()
TOOL_LABEL = {"claude": "Claude Code", "codex": "Codex CLI", "shared": "skills CLI"}
LIVE_TTL_S = 3.0
INDEX_VERSION = 1  # bump when the static index shape changes
STALE_AFTER_S = 24 * 3600


# --- static layer ------------------------------------------------------------

def invoke_name(rec: SkillRecord) -> str:
    """The name the tool itself uses when it calls the skill."""
    plugin = rec.origin_package.get("plugin") if rec.origin_package else None
    if rec.tool == "claude" and plugin:
        return f"{plugin.split('@', 1)[0]}:{rec.name}"
    return rec.name


def _project_skill_sources(roots: list[Path]) -> list[tuple[cfg.Source, Path]]:
    found = []
    for root in roots:
        if root == HOME() or HOME().is_relative_to(root):
            continue
        for rel, tool in ((".claude/skills", "claude"), (".agents/skills", "codex"),
                          (".codex/skills", "codex")):
            path = root / rel
            if path.is_dir():
                src = cfg.Source(
                    source_id=f"project:{stable_id(str(path))}", tool=tool, kind="skills",
                    scope="project", path=str(path), label=f"{root.name} 專案技能",
                )
                found.append((src, root))
    return found


def _candidate_project_roots(conf: dict) -> list[Path]:
    """Configured project roots (one level of children) plus git roots of
    recent sessions. Never the whole disk."""
    roots: set[Path] = set()
    for raw in conf.get("project_roots", []):
        base = Path(raw).expanduser()
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    roots.add(child)
        except OSError:
            continue
    return sorted(roots)


def build_static(conf: dict, extra_project_roots: list[Path] | None = None) -> dict:
    started = time.time()
    problems: list[str] = []
    c_facts = claude.load_activation_facts()
    x_facts = codex.load_config_facts()
    problems += c_facts["problems"] + x_facts["problems"]

    skills: list[SkillRecord] = []
    roles: list[AgentRole] = []
    source_rows: list[dict] = []

    for src in cfg.sources_from(conf):
        path = src.resolved()
        row = {"source_id": src.source_id, "label": src.label, "tool": src.tool,
               "kind": src.kind, "path": src.path, "enabled": src.enabled,
               "exists": path.exists(), "count": 0, "scope": src.scope}
        source_rows.append(row)
        if not src.enabled:
            continue
        if not row["exists"]:
            problems.append(f"來源不存在：{src.label}")
            continue
        # Each file is isolated inside the scanners; this is the last line of
        # defence so one broken source cannot abort the whole scan.
        try:
            if src.kind in ("skills", "plugin_cache", "marketplace"):
                if src.tool == "shared":
                    found = shared.scan_skills(src, c_facts)
                elif src.tool == "claude":
                    found = claude.scan_skills(src, c_facts)
                else:
                    found = codex.scan_skills(src, x_facts)
                skills += found
                row["count"] = len(found)
            elif src.kind == "agents":
                found = (claude.scan_agents(src) if src.tool == "claude"
                         else codex.scan_agents(src, x_facts))
                roles += found
                row["count"] = len(found)
        except Exception as exc:
            problems.append(f"掃描來源失敗：{src.label}（{type(exc).__name__}）")

    try:
        roles += claude.scan_plugin_agents(c_facts)
    except Exception as exc:
        problems.append(f"掃描外掛代理失敗（{type(exc).__name__}）")

    roots = _candidate_project_roots(conf) + list(extra_project_roots or [])
    seen_roots: set[str] = set()
    for src, root in _project_skill_sources(sorted(set(roots))):
        if src.path in seen_roots:
            continue
        seen_roots.add(src.path)
        try:
            found = (claude.scan_skills(src, c_facts) if src.tool == "claude"
                     else codex.scan_skills(src, x_facts))
        except Exception as exc:
            problems.append(f"掃描來源失敗：{src.label}（{type(exc).__name__}）")
            continue
        for rec in found:
            rec.scope = "project"
            rec.origin_package = {**rec.origin_package, "project": root.name,
                                  "project_path": str(root)}
            if src.tool == "claude":
                rec.activation, rec.activation_reason = (
                    ACT_ACTIVE, f"專案層技能：在 {root.name} 目錄內啟動 Claude Code 時載入")
            else:
                rec.activation, rec.activation_reason = (
                    ACT_UNKNOWN, "專案層 Codex 技能位置；本機設定未確認 Codex 會載入此路徑")
        skills += found
        source_rows.append({"source_id": src.source_id, "label": src.label, "tool": src.tool,
                            "kind": "skills", "path": src.path, "enabled": True,
                            "exists": True, "count": len(found), "scope": "project",
                            "discovered": True})

    # Same name, different source: keep every copy, cross-reference them.
    by_name: dict[str, list[SkillRecord]] = defaultdict(list)
    for rec in skills:
        by_name[rec.name.lower()].append(rec)
    for group in by_name.values():
        if len(group) > 1:
            ids = [r.skill_id for r in group]
            for rec in group:
                rec.duplicate_of = [i for i in ids if i != rec.skill_id]

    # Main CLI agents as roles, with the skills their load scope gives them.
    for tool in ("claude", "codex"):
        active = [r.skill_id for r in skills if r.tool == tool and r.activation == ACT_ACTIVE]
        if tool == "claude":
            model = _claude_default_model()
        else:
            model = (Sourced.author(x_facts["default_model"], "~/.codex/config.toml: model")
                     if x_facts.get("default_model") else Sourced.missing("config.toml 未設定預設模型"))
        roles.insert(0, AgentRole(
            role_id=f"cli-{tool}",
            name=f"{TOOL_LABEL[tool]} 主代理",
            tool=tool,
            kind="cli",
            description=Sourced.derived(
                f"直接在終端機執行的 {TOOL_LABEL[tool]}。可使用所有位於其載入範圍且未停用的技能。",
                "由 SID Console 依工具類型說明"),
            model=model,
            skill_link_ids=active,
            skill_link_basis="load_scope",
        ))

    # Subagent -> skill links, only where a file actually says so.
    active_names = {r.name.lower(): r.skill_id for r in skills
                    if r.activation == ACT_ACTIVE}
    for role in roles:
        if role.kind != "subagent":
            continue
        declared = _declared_skills(role)
        if declared is not None:
            role.skill_link_ids = [active_names[n] for n in declared if n in active_names]
            role.skill_link_basis = "declared"
        else:
            role.skill_link_basis = "undeclared"

    skills.sort(key=lambda r: (r.activation != ACT_ACTIVE, r.tool, r.name.lower(), r.path))
    return {
        "index_version": INDEX_VERSION,
        "generated_at": time.time(),
        "scan_seconds": round(time.time() - started, 2),
        "sources": source_rows,
        "skills": [s.to_json() | {"invoke_name": invoke_name(s),
                                  "categories": categories.categorize(
                                      s.name, str(s.description.value or ""),
                                      str(s.when_to_use.value or "")[:400])}
                   for s in skills],
        "category_table": categories.public_table(),
        "roles": [r.to_json() for r in roles],
        "problems": problems,
        "facts": {
            "claude_enabled_plugins": c_facts["enabled"],
            "claude_installed_plugins": sorted({v["plugin"] + " " + v["version"]
                                                for v in c_facts["installed"].values()}),
            "codex_default_model": x_facts.get("default_model"),
            "codex_default_effort": x_facts.get("default_effort"),
        },
    }


def _claude_default_model() -> Sourced:
    path = HOME() / ".claude" / "settings.json"
    try:
        model = json.loads(path.read_text(encoding="utf-8")).get("model")
    except (OSError, ValueError):
        model = None
    if model:
        return Sourced.author(str(model), "~/.claude/settings.json: model")
    return Sourced.missing("settings.json 未設定預設模型")


def _declared_skills(role: AgentRole) -> list[str] | None:
    """Skills a subagent file explicitly lists. None when it does not say."""
    if not role.path:
        return None
    path = Path(role.path)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        if path.suffix == ".md":
            from .scan import frontmatter
            meta, _ = frontmatter.parse(frontmatter.split(text)[0])
            value = meta.get("skills")
        else:
            import tomllib
            value = tomllib.loads(text).get("skills")
    except Exception:  # malformed or hostile file: treat as "does not say"
        return None
    if value is None:
        return None
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    if not isinstance(value, list):
        return None
    return [str(v).lower() for v in value if v]


# --- live layer --------------------------------------------------------------

def git_root(path: str) -> Path | None:
    if not path:
        return None
    current = Path(path)
    for _ in range(20):
        # The home directory is never a project, even when it is a git repo
        # (dotfile repos are common); stop before looking at it.
        if current == HOME() or current == current.parent:
            return None
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _project_for(cwd: str) -> tuple[str, str, str, str]:
    """(project_id, name, path, basis)"""
    if not cwd:
        return "unknown", "未知工作目錄", "", "session 未回報工作目錄"
    root = git_root(cwd)
    if root:
        return stable_id("proj", str(root)), root.name, str(root), "git 儲存庫根目錄"
    p = Path(cwd)
    if p == HOME():
        return "home", "家目錄（未指定專案）", str(p), "工作目錄是使用者家目錄"
    return stable_id("proj", str(p)), p.name, str(p), "工作目錄（非 git）"


def _git_branch(root: str) -> str:
    head = Path(root) / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text.rsplit("/", 1)[-1] if text.startswith("ref:") else text[:8]


def _resolve_usage(key: str, skills: list[dict], tool: str) -> tuple[list[str], str, str]:
    """Map a usage key to skill ids. Returns (ids, label, resolution)."""
    kind, _, value = key.partition(":")
    if kind == "path":
        ids = [s["skill_id"] for s in skills if s["path"] == value]
        label = Path(value).parent.name
        return ids, label, "exact" if ids else "unresolved"
    pool = [s for s in skills if s["tool"] == tool]
    exact = [s for s in pool if s["invoke_name"] == value]
    if not exact:
        short = value.split(":")[-1]
        exact = [s for s in pool if s["name"] == short and s["activation"] == ACT_ACTIVE]
    if not exact:
        return [], value, "unresolved"
    active = [s for s in exact if s["activation"] == ACT_ACTIVE] or exact
    return [s["skill_id"] for s in active], value, "exact" if len(active) == 1 else "ambiguous"


_MISSING: tuple = ()  # the stamp of an index file that is not there


def _stamp(st: os.stat_result) -> tuple:
    """Which generation of the index file this is.

    Compared for equality, never by age: a replacement can carry the same or
    an older mtime (copies, restores, coarse clocks) and is still a different
    inode or size. ctime is left out because every private state write
    re-tightens file modes, which moves ctime without changing the content.
    """
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


class Store:
    """Holds the cached static index and a TTL-cached live view.

    Nothing slow runs under a lock that other requests need. herdr calls and
    usage parsing happen outside every lock, so a hung herdr can delay the
    live view but never the skill library:
      _lock       guards the swap of _static / conf (held only for assignments)
      _scan_lock  serialises full scans (first load and rescan)
      _live_cond  single-flight for the live view: one build at a time; other
                  callers reuse the result of that build, or the last one.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._live_cond = threading.Condition()
        self._static: dict | None = None
        self._static_stamp: tuple | None = None  # file _static came from; None = unknown
        self._live: dict | None = None
        self._live_at = 0.0        # monotonic time the cached build finished
        self._live_started = 0.0   # monotonic time the cached build started
        self._live_building = False
        self._live_epoch = 0       # bumped when _static changes; older builds are not cached
        cfg.ensure_state_dir()  # also tightens a state dir made by an older version
        self.conf = cfg.load()

    def _index_stamp(self) -> tuple:
        try:
            return _stamp(cfg.index_path().stat())
        except OSError:
            return _MISSING

    # static
    def static(self) -> dict:
        """The static index, reloaded when index.json is a different file
        (for example after a CLI scan) than the one it was read from."""
        current = self._index_stamp()
        with self._lock:
            if self._static is not None:
                if self._static_stamp is None:  # assigned directly: adopt the file on disk
                    self._static_stamp = current
                if self._static_stamp == current:
                    return self._static
        with self._scan_lock:
            current = self._index_stamp()
            with self._lock:
                if self._static is not None:
                    if self._static_stamp == current:  # another caller reloaded it
                        return self._static
                    if current == _MISSING:
                        # A deleted index is not newer content: keep serving the
                        # one in memory (rendering never starts a scan) until a
                        # new file appears or a rescan runs.
                        self._static_stamp = _MISSING
                        return self._static
            data, stamp = self._load_or_scan()
            self._publish(data, stamp)
            return data

    def set_conf(self, conf: dict) -> None:
        with self._lock:
            self.conf = conf

    def rescan(self) -> dict:
        """Scan again with the configuration on disk.

        Refused while config.json is corrupt: the user's scan scope is then
        unknown, and replacing a good index with a scan of nothing would
        throw away what the console could still show.
        """
        with self._scan_lock:
            conf = cfg.load()
            self.set_conf(conf)
            if conf.get("_corrupt"):
                raise ValueError(cfg.corrupt_message())
            data, stamp = self._scan(conf)
            self._publish(data, stamp)
            return data

    def _publish(self, data: dict, stamp: tuple) -> None:
        """Swap in a static index, then retire live views built on older ones.
        _static is set before the epoch moves; _static_for_live relies on it."""
        with self._lock:
            self._static = data
            self._static_stamp = stamp
        with self._live_cond:
            self._live = None
            self._live_epoch += 1

    def _load_or_scan(self) -> tuple[dict, tuple]:
        """The index on disk, or a fresh scan when there is no usable one,
        with the stamp of the file the data really came from.

        The stamp comes from the open descriptor, so a replacement that lands
        after the read cannot lend its stamp to these bytes: it stays a
        different file and is loaded on the next call.
        """
        try:
            with open(cfg.index_path(), "rb") as fh:
                stamp = _stamp(os.fstat(fh.fileno()))
                data = json.loads(fh.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("index_version") == INDEX_VERSION:
                return data, stamp
        except (OSError, ValueError, RecursionError):
            pass
        with self._lock:
            conf = self.conf
        return self._scan(conf)

    def _scan(self, conf: dict) -> tuple[dict, tuple]:
        extra: list[Path] = []
        if not conf.get("_corrupt"):  # scope unknown: no roots beyond the (empty) config
            snap = herdr.snapshot(conf.get("herdr_bin", ""))
            for agent in snap["agents"]:
                root = git_root(agent.get("foreground_cwd") or agent.get("cwd") or "")
                if root:
                    extra.append(root)
        data = build_static(conf, extra)
        written = cfg.write_private(cfg.index_path(), json.dumps(data, ensure_ascii=False))
        return data, _stamp(written)

    # live
    def live(self, force: bool = False, stale_ok: bool = False) -> dict:
        """The live view, rebuilt at most every LIVE_TTL_S seconds.

        force     the result must come from a herdr call that started after
                  this request (focus validation relies on this).
        stale_ok  any cached view will do; a refresh runs in the background.
                  For pages that only decorate static data with usage.
        While a build is running, other non-forced callers get the previous
        view if there is one; everyone else waits for that build instead of
        calling herdr again.
        """
        asked = time.monotonic()
        with self._live_cond:
            while True:
                cached = self._live
                if force:
                    if cached is not None and self._live_started >= asked:
                        return cached
                elif cached is not None:
                    if time.monotonic() - self._live_at < LIVE_TTL_S:
                        return cached
                    if self._live_building:
                        return cached
                    if stale_ok:
                        self._live_building = True
                        threading.Thread(target=self._build_live, daemon=True,
                                         name="sid-console-live").start()
                        return cached
                if not self._live_building:
                    self._live_building = True
                    break
                self._live_cond.wait()
        return self._build_live()

    def _static_for_live(self) -> tuple[dict, int | None]:
        """The static index and the live epoch it belongs to.

        static() can publish a newer index (its own reload, or a rescan in
        another thread), so the epoch is read on both sides of it and the pair
        is used only if nothing was published in between. _publish sets
        _static before it moves the epoch, so the snapshot is then at least as
        new as that epoch. After a few unlucky tries the build still runs, but
        its result is not cached (epoch None).
        """
        for _ in range(3):
            with self._live_cond:
                epoch = self._live_epoch
            static = self.static()
            with self._live_cond:
                if epoch == self._live_epoch:
                    return static, epoch
        return static, None

    def _build_live(self) -> dict:
        """Run one build; the caller has already set _live_building."""
        data = None
        epoch = None
        try:
            static, epoch = self._static_for_live()
            with self._lock:
                conf = self.conf
            started = time.monotonic()
            data = build_live(conf, static)
            return data
        finally:
            with self._live_cond:
                if data is not None and epoch is not None and epoch == self._live_epoch:
                    self._live = data
                    self._live_started = started
                    self._live_at = time.monotonic()
                self._live_building = False
                self._live_cond.notify_all()


def build_live(conf: dict, static: dict) -> dict:
    snap = herdr.snapshot(conf.get("herdr_bin", ""))
    days = int(conf.get("usage_days", 30))
    use = usage.collect(days) if conf.get("usage_enabled", True) else {
        "sessions": [], "problems": ["使用紀錄掃描已在設定中關閉"], "window_days": days}
    skills = static["skills"]
    known = {sess["session_id"] for sess in use["sessions"]}
    live_ids = [(a.get("agent_session") or {}).get("value", "") for a in snap["agents"]]
    if conf.get("usage_enabled", True):
        use["sessions"] = use["sessions"] + list(
            usage.for_session_ids([i for i in live_ids if i and i not in known]).values())
    tabs = {t["tab_id"]: t for t in snap["tabs"]}
    workspaces = {w["workspace_id"]: w for w in snap["workspaces"]}

    usage_by_id: dict[str, dict] = {}
    usage_rows: list[dict] = []
    for sess in use["sessions"]:
        resolved = []
        for key, info in sess["skills"].items():
            ids, label, how = _resolve_usage(key, skills, sess["tool"])
            resolved.append({"key": key, "label": label, "skill_ids": ids, "resolution": how,
                             "count": info["count"], "last_ts": info["last_ts"],
                             "evidence": info["evidence"]})
        resolved.sort(key=lambda r: r["last_ts"], reverse=True)
        pid, pname, ppath, pbasis = _project_for(sess["cwd"])
        row = {"session_id": sess["session_id"], "tool": sess["tool"], "cwd": sess["cwd"],
               "first_ts": sess["first_ts"], "last_ts": sess["last_ts"],
               "models": sess["models"], "skills": resolved, "project_id": pid}
        usage_rows.append(row)
        usage_by_id[sess["session_id"]] = row

    projects: dict[str, dict] = {}

    def project(pid, name, path, basis):
        if pid not in projects:
            projects[pid] = {"project_id": pid, "name": name, "path": path, "basis": basis,
                             "git_branch": _git_branch(path) if basis.startswith("git") else "",
                             "live_session_ids": [], "workspace_ids": [],
                             "recent_session_ids": [], "last_activity": ""}
        return projects[pid]

    sessions = []
    for agent in snap["agents"]:
        cwd = agent.get("foreground_cwd") or agent.get("cwd") or ""
        ref = agent.get("agent_session") or {}
        sess_id = ref.get("value", "")
        matched = usage_by_id.get(sess_id)
        tab = tabs.get(agent.get("tab_id", ""), {})
        ws = workspaces.get(agent.get("workspace_id", ""), {})
        pid, pname, ppath, pbasis = _project_for(cwd)
        proj = project(pid, pname, ppath, pbasis)
        proj["live_session_ids"].append(agent.get("terminal_id"))
        if ws and ws.get("workspace_id") not in proj["workspace_ids"]:
            proj["workspace_ids"].append(ws.get("workspace_id"))

        tool = {"claude": "claude", "codex": "codex"}.get(agent.get("agent", ""), agent.get("agent", ""))
        role_label = tab.get("label") or agent.get("name") or ""
        sessions.append({
            "terminal_id": agent.get("terminal_id"),
            "agent": agent.get("agent"),
            "tool": tool,
            "supported_tool": tool in ("claude", "codex"),
            "status": agent.get("agent_status", "unknown"),
            "role_label": role_label,
            "role_label_source": "herdr 分頁名稱（使用者命名）" if tab.get("label") else "",
            "title": agent.get("terminal_title_stripped") or "",
            "workspace_id": agent.get("workspace_id"),
            "workspace_label": ws.get("label", ""),
            "tab_id": agent.get("tab_id"),
            "pane_id": agent.get("pane_id"),
            "focused": agent.get("focused", False),
            "cwd": cwd,
            "project_id": pid,
            "session_ref": sess_id,
            "session_source": ref.get("source", ""),
            "usage_matched": matched is not None,
            "models_observed": matched["models"] if matched else {},
            "skills_used": matched["skills"] if matched else [],
            "last_ts": matched["last_ts"] if matched else "",
        })

    for row in usage_rows:
        pid, pname, ppath, pbasis = _project_for(row["cwd"])
        proj = project(pid, pname, ppath, pbasis)
        proj["recent_session_ids"].append(row["session_id"])
        if row["last_ts"] > proj["last_activity"]:
            proj["last_activity"] = row["last_ts"]

    for proj in projects.values():
        used: dict[str, int] = defaultdict(int)
        for sid in proj["recent_session_ids"]:
            for s in usage_by_id[sid]["skills"]:
                used[s["label"]] += s["count"]
        proj["skills_used"] = sorted(used.items(), key=lambda kv: -kv[1])[:20]
        proj["project_skill_ids"] = [s["skill_id"] for s in skills
                                     if s.get("origin_package", {}).get("project_path") == proj["path"]]

    order = {"blocked": 0, "done": 1, "working": 2, "idle": 3}
    attention = [s for s in sessions if s["status"] in ("blocked", "done")]
    attention.sort(key=lambda s: order.get(s["status"], 9))

    return {
        "generated_at": time.time(),
        "herdr": {"available": snap["available"], "version": snap["version"],
                  "binary": snap["binary"], "problems": snap["problems"]},
        "sessions": sessions,
        # Every pane herdr currently has, agent or not. `sessions` above is
        # built from `agent list` and therefore drops a pane the moment its
        # AI agent exits, even though the pane, its shell and its scrollback
        # are all still live. Attach decisions must use this list instead,
        # or the terminal bridge would refuse a pane that plainly exists.
        "panes": [
            {"pane_id": p.get("pane_id"), "terminal_id": p.get("terminal_id"),
             "tab_id": p.get("tab_id"), "workspace_id": p.get("workspace_id"),
             "agent": p.get("agent"), "agent_status": p.get("agent_status", "unknown"),
             "title": p.get("terminal_title_stripped") or "",
             "cwd": p.get("foreground_cwd") or p.get("cwd") or ""}
            for p in snap["panes"]
        ],
        "workspaces": snap["workspaces"],
        "usage": {"window_days": use["window_days"], "sessions": usage_rows,
                  "problems": use["problems"]},
        "projects": sorted(projects.values(),
                           key=lambda p: (not p["live_session_ids"], p["last_activity"] == "",
                                          p["name"].lower())),
        "attention": [s["terminal_id"] for s in attention],
    }
