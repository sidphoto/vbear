"""Game-UI QA harness (design game-ui 8; segments G1-G4): a throwaway console in a temporary state directory
and a temporary HOME, with the synthetic Claude and Codex of the flow tests. No model, no real account, no
network; nothing under the real ~/.vbear, ~/.claude, ~/.codex or ~/.claude.json is read or written.

  python3 -m unittest tests.qa_game_ui.Check -v
      builds the same environment, asserts it holds what the checklist below needs, and ends.
  VBEAR_QA_SERVE=1 python3 -m unittest tests.qa_game_ui.Serve -v
      the same environment left running for a person or a browser tool. serve.log (the terminal) prints the
      login URL and the item-by-item checklist. Stop with Ctrl-C (or set VBEAR_QA_SECONDS).
      Optional VBEAR_QA_NO_MANUAL=1: a purely automatic flow: nothing is recorded by hand and the executor role
      names no work directory, so the page's phase and its HEAD check come from the automatic events and the
      task's directory alone.
      Optional VBEAR_QA_DEMO=1: the same environment with demo names (「示範」), no HTML probe skill and no
      skill the index cannot find, and no work directory on the executor role: nothing on the screens is a path
      of this machine. It is what the README's screenshots are taken from (docs/images/).
      Optional VBEAR_QA_LOBBY=1: more flows for the home page's quest board (one waits for approval, one waits
      for a merge, four more are being worked on by hand, next to the automatic one, so 「還有 1 則」 shows). VBEAR_QA_LOBBY=empty
      builds no flow and starts no executor, so the board is in its first-run state (no flow, no session,
      nothing waiting for you); the two role cards stay.
      Optional VBEAR_QA_FRESH=1: a user who has just installed VBear: no demo role cards, no task cards, no
      flows and no session (the skills stay, except the HTML probe skill, which is for security checks). It implies the empty lobby and wins over VBEAR_QA_LOBBY=1 and
      VBEAR_QA_OFFICE; it combines with VBEAR_QA_TRANSLATE, VBEAR_QA_CODEX_BLOCKED and VBEAR_QA_DEMO.
      Optional VBEAR_QA_OFFICE=1: the pixel office (#/office) with what design office 6 asks for: six flows
      spread over the four stations (plan board, build area, review room, merge gate) next to the automatic
      one, four synthetic live sessions (two working, waiting for you, state unknown; the first working one is the
      executor of a flow, so its desk plate names it) and three profiles (Claude, Codex, and one whose chosen skill
      the index cannot find). VBEAR_QA_OFFICE=stress: every station full with a "more" link (20 flows), ten
      sessions and 33 profiles (the environment's two, the one whose skill is missing, and thirty more; the lounge
      shows 24 and links to the rest).
      Optional VBEAR_QA_CODEX_BLOCKED=1: leave the Codex checks as they really are (no synthetic evidence), so
      the Codex role cannot be launched from VBear: its card and the 出發通行證 dialog then show the reason.
      Without it the synthetic Codex evidence is on and its preview is launchable, which shows the evidence
      lines of the Codex labels.
      Optional VBEAR_QA_TRANSLATE=1: seed fresh/stale/none/orphan translations and inject a process-local fake
      translation CLI for both engine selectors, and point 「驗證」 (verify_boundary) at it. No real CLI or
      model is ever used. VBEAR_QA_TRANSLATE=fail is the same with a CLI whose every translation fails (the
      「驗證」 probe still passes): it shows the failure on the skill card and the bar's fold into a dot.
      Optional VBEAR_QA_RUN=1: also start the runner thread, so the flow goes on by itself (the first review is
      NEEDS WORK, a helper commits the "fix", the second says PASS, the merge gate opens). Without it the flow
      stays exactly as built: automatic mode on, one review round done, the runner idle.

What is built (everything synthetic, all under one temporary directory printed in the log):
  * Claude role「QA 後端工匠（Claude）」: four selected skills; one is not in the current index (a profile
    that still names a skill that is gone), one has an HTML-like name and description (must show as text).
  * Codex role「QA 審查員（Codex）」, with one selected skill.
  * One flow in automatic mode, the executor started, one review round done (NEEDS WORK). Unless
    VBEAR_QA_NO_MANUAL=1 the harness also records by hand: plan submitted, approved, work started, the report
    and the review (and names the work directory on the executor role).
"""

from __future__ import annotations

import json
import copy
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_automation_runner import RunnerCase
from tests.test_runtimed_managed import FAKE_CLI, FAKE_CODEX_CLI
from vbear import agent_launch, agent_profiles, flows, tasks, translations
from vbear import config as cfg

PROBE = "<img src=x onerror=alert(document.domain)>"
GHOST_SKILL_ID = "ghost-0000000000000000"          # no such skill in the index: "the index cannot find it"
GOOD = {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"}
DEMO = os.environ.get("VBEAR_QA_DEMO") == "1"
CLAUDE_PROFILE, CODEX_PROFILE = ("demo-claude-role", "demo-codex-role") if DEMO else ("qa-claude-role", "qa-codex-role")
CLAUDE_NAME, CODEX_NAME = ("後端工匠（示範）", "審查員（示範）") if DEMO else ("QA 後端工匠（Claude）", "QA 審查員（Codex）")
FLOW_NAMES = (("規劃者（示範）", "執行者（示範）", "審查者（示範）") if DEMO
              else ("QA 規劃者", "QA 執行者（Claude）", "QA 審查者（Codex）"))
SOURCES = ("claude-user-skills", "claude-user-agents", "codex-skills", "codex-agents")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _Env(RunnerCase):
    """RunnerCase gives: a real daemon, the synthetic stream CLI and Codex, a real git work directory, a console
    on a free port with login required (self.token), and the flow (self.fid). setUp of the bases already put
    HOME and VBEAR_HOME in a temporary directory."""

    def build(self) -> None:
        self.no_manual = os.environ.get("VBEAR_QA_NO_MANUAL") == "1"
        self.assertTrue(str(self.home).startswith(str(self.tmp)), "HOME must be the temporary one")
        self.assertEqual(os.environ["HOME"], str(self.home))
        self.assertEqual(os.environ["VBEAR_HOME"], str(self.base))
        self.fresh = os.environ.get("VBEAR_QA_FRESH") == "1"
        self.empty = self.fresh or os.environ.get("VBEAR_QA_LOBBY") == "empty"
        self._skills_and_roles()
        if not self.fresh:
            self._profiles()
        self._launch_environment()
        if self.empty:
            # no demo flow means no demo executor either: its managed session is what the lobby would still list
            self._clear_demo()
        else:
            self._flow()
            self._lobby()
            self._office()
        self._translations()

    # ---- the index: skills and professions, as files in the temporary HOME

    def _skills_and_roles(self) -> None:
        sk = self.home / ".claude" / "skills"
        _write(sk / "code-review" / "SKILL.md",
               "---\nname: code-review\ndescription: Review a diff and list the risky lines.\n---\n"
               "# Code review\n\nUse when a change is ready.\n\nUses `scripts/lint.sh` and `notes/checklist.md`.\n")
        (sk / "code-review" / "scripts").mkdir(exist_ok=True)           # the directory exists, the file does not
        (sk / "code-review" / "notes").mkdir(exist_ok=True)
        _write(sk / "code-review" / "notes" / "checklist.md", "- read the diff\n")
        _write(sk / "test-writer" / "SKILL.md",
               "---\nname: test-writer\ndescription: Write the missing unit tests for a function.\n---\n"
               "# Test writer\n\nUse after a function is written.\n")
        if DEMO:
            _write(sk / "doc-helper" / "SKILL.md",
                   "---\nname: doc-helper\ndescription: Draft short documentation for a finished change.\n---\n"
                   "# Doc helper\n\nUse when a change is merged.\n")
        elif not self.fresh:
            # the name and description are HTML-like text: every screen must show them as text, never run them.
            # It is a probe for security checks: a "new user" environment (FRESH) does not carry it
            _write(sk / "html-probe" / "SKILL.md",
                   f"---\nname: {json.dumps(PROBE)}\ndescription: {json.dumps('probe ' + PROBE + ' end')}\n---\n"
                   "# Probe\n\nA skill whose name and description look like markup.\n")
        _write(sk / "spare-skill" / "SKILL.md",
               "---\nname: spare-skill\ndescription: A skill no role selected.\n---\n# Spare\n")
        _write(self.home / ".claude" / "agents" / "qa-backend.md",
               "---\nname: qa-backend\ndescription: Writes small backend features.\nmodel: sonnet\n---\n"
               "You write backend code.\n")
        _write(self.home / ".codex" / "config.toml", 'model = "gpt-6-luna"\n')
        _write(self.home / ".codex" / "skills" / "codex-triage" / "SKILL.md",
               "---\nname: codex-triage\ndescription: Sort incoming review comments.\n---\n# Triage\n")
        _write(self.home / ".codex" / "agents" / "qa-reviewer.toml",
               'description = "Reviews a diff"\nmodel = "gpt-6-luna"\n'
               'developer_instructions = """\nReview the diff.\n"""\n')
        conf = cfg.load()
        for src in conf["sources"]:
            src["enabled"] = src["source_id"] in SOURCES
        conf.update(project_roots=[], usage_enabled=False)
        cfg.save(conf)
        self.console.store.set_conf(cfg.load())
        self.index = self.console.store.rescan()
        self.skill_ids = {s["name"]: s["skill_id"] for s in self.index["skills"]}
        self.role_ids = {r["name"]: r["role_id"] for r in self.index["roles"]}

    def _profiles(self) -> None:
        by_dir = {Path(s["path"]).parent.name: s["skill_id"] for s in self.index["skills"]}
        roles = {Path(r["path"]).stem: r["role_id"] for r in self.index["roles"]}
        known_skills = set(by_dir.values()) | {GHOST_SKILL_ID}
        known_roles = set(roles.values())
        agent_profiles.save_profile(CLAUDE_PROFILE, {
            "name": CLAUDE_NAME, "profession_role_id": roles["qa-backend"],
            "model": {"tool": "claude", "model_id": ""}, "enabled": True,
            "equipped_skill_ids": ([by_dir["code-review"], by_dir["test-writer"], by_dir["doc-helper"]] if DEMO
                                   else [by_dir["code-review"], by_dir["test-writer"], by_dir["html-probe"],
                                         GHOST_SKILL_ID]),
            "permission_intents": dict(GOOD)}, known_skills=known_skills, known_roles=known_roles)
        agent_profiles.save_profile(CODEX_PROFILE, {
            "name": CODEX_NAME, "profession_role_id": roles["qa-reviewer"],
            "model": {"tool": "codex", "model_id": ""}, "enabled": True,
            "equipped_skill_ids": [by_dir["codex-triage"]],
            "permission_intents": dict(GOOD)}, known_skills=known_skills, known_roles=known_roles)

    def _translations(self):
        if os.environ.get("VBEAR_QA_TRANSLATE") not in ("1", "fail"):
            return
        fails = os.environ.get("VBEAR_QA_TRANSLATE") == "fail"
        # This executable is always generated under the synthetic HOME. The
        # provider injection is process-local, not a product config/env bypass.
        fake = self.tmp / "qa-translation-cli"
        fake.write_text("#!" + sys.executable + "\n" + "FAILS = " + repr(fails) + "\n" + r'''import json, sys, time
from pathlib import Path
a = sys.argv[1:]
if a == ["--version"]:                          # translations.claude_identity()
    print("2.1.296 (Claude Code)")
    sys.exit(0)
assert not list(Path.cwd().iterdir())
engine = "codex" if a[0] == "exec" else "claude"
if engine == "claude":
    assert a[a.index("--tools") + 1] == ""
    assert "--safe-mode" in a and "--strict-mcp-config" in a
    schema = json.loads(a[a.index("--json-schema") + 1])
    assert sorted(schema["required"]) == ["description_zh", "needs", "what", "when"]
else:
    assert a[a.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in a and "mcp" in a
prompt = sys.stdin.read()
if "--verbose" in a:                            # the boundary probe (the settings page's 「驗證」)
    assert a[a.index("--output-format") + 1] == "stream-json"
    print(json.dumps({"type": "system", "subtype": "init", "tools": ["StructuredOutput"], "mcp_servers": []}))
    sys.exit(0)
if FAILS:                                       # VBEAR_QA_TRANSLATE=fail: every translation fails, the probe above still passes
    sys.stderr.write("synthetic failure\n")
    sys.exit(3)
payload = prompt.split("BEGIN_UNTRUSTED_JSON_STRING\n", 1)[1].split("\nEND_UNTRUSTED_JSON_STRING", 1)[0]
fields = json.loads(json.loads(payload))
time.sleep(0.6)
result = {"what": "QA 假翻譯：整理技能說明", "when": "原文未提供", "needs": "原文未提供",
          "description_zh": "QA 假 CLI 中文說明：" + str(fields.get("name") or "未提供") + " <img src=x onerror=alert(1)>"}
if engine == "claude":                          # since 4e8902e: structured_output, never the free-text "result"
    print(json.dumps({"type": "result", "is_error": False, "structured_output": result}))
else:
    print(json.dumps(result))
''', encoding="utf-8")
        fake.chmod(0o700)
        provider = lambda engine: (str(fake), "2.1.296" if engine == "claude" else "0.160.0")
        # 「驗證」 (verify_boundary) looks up the claude binary itself: point it at the fake, for this process only
        p = mock.patch.object(translations, "claude_identity", return_value=(str(fake), "2.1.296"))
        p.start()
        self.addCleanup(p.stop)
        manager = self.console.translations
        manager.run = lambda engine, record, cancel: translations.run_cli(engine, record, cancel, provider=provider)
        rows = {s["name"]: s for s in self.index["skills"]}
        def seed(rec):
            return {"lang": "zh-TW", "source_hash": translations.source_hash(rec), "created_at": time.time(),
                    "engine": "claude", "model": translations.MODELS["claude"], "cli_version": "2.1.296",
                    "summary": {"what": "QA 假翻譯：審查變更", "when": translations.MISSING, "needs": translations.MISSING},
                    "description_zh": "QA 假翻譯：檢查變更的風險"}
        fresh = rows["code-review"]
        manager.store.put(fresh["skill_id"], seed(fresh))
        stale = copy.deepcopy(rows["test-writer"])
        stale["description"] = {"value": "Old description before author update", "origin": "author"}
        manager.store.put(stale["skill_id"], seed(stale))
        manager.store.put("qa-translation-orphan", seed(fresh))

    # ---- 出發通行證 needs a CLI to look at: the synthetic ones, pinned for this process only

    def _launch_environment(self) -> None:
        self.qa_work = self.tmp / "qa-workdir"
        self.qa_work.mkdir()
        (self.qa_work / "fake-mode").write_text("none")
        claude = self.tmp / "qa-claude"
        claude.write_text(FAKE_CLI % {"py": sys.executable, "version": "2.1.286"}, encoding="utf-8")
        claude.chmod(0o700)
        codex = self.tmp / "qa-codex"
        codex.write_text(FAKE_CODEX_CLI % {"py": sys.executable}, encoding="utf-8")
        codex.chmod(0o700)
        self.codex_blocked = os.environ.get("VBEAR_QA_CODEX_BLOCKED") == "1"
        patches = [mock.patch("vbear.runtime.native._pinned_claude_binary", return_value=str(claude)),
                   mock.patch("vbear.runtime.native._pinned_codex_binary", return_value=str(codex))]
        if not self.codex_blocked:                  # the synthetic Codex evidence (otherwise: as it really is)
            patches += [mock.patch.object(agent_launch.cli_versions, "CODEX_INTERACTIVE_FLAGS_SUPPORTED", True),
                        mock.patch.object(agent_launch, "_codex_evidence_reference",
                                          return_value=".local/qa-synthetic/codex-acceptance.json")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.console.managed_root = self.tmp

    # ---- the flow: automatic mode on, the executor started, one review round done

    def _flow(self) -> None:
        with flows.store.locked():
            data = flows.store.load()
            roles = data[self.fid]["roles"]
            roles["planner"]["name"], roles["executor"]["name"] = FLOW_NAMES[0], FLOW_NAMES[1]
            if not self.no_manual and not DEMO:               # a demo shows no path of this machine
                roles["executor"]["workdir"] = str(self.work)
            roles["reviewers"][0]["name"] = FLOW_NAMES[2]
            flows.store.save(data)
        # what the user records by hand; without it the phase comes from the automatic events alone
        if not self.no_manual:
            for kind in ("plan_submitted", "plan_approved", "implementation_started"):
                flows.append_event(self.fid, {"kind": kind, "note": "QA"})
        self.enable()
        self.start_executor()
        self.commit_work("first")
        self.fake_mode("needs_work")
        # the report is recorded by hand right after the runner's own (before any review of it: the same
        # fact, one round), and the verdict by hand right after the runner's
        self.run_until(lambda: "auto_report" in self.kinds(), "the executor's report")
        if not self.no_manual:
            flows.append_event(self.fid, {"kind": "executor_report", "commit": self.commit, "note": "QA"})
        self.run_until(lambda: "auto_review_result" in self.kinds(), "the first review's result")
        if not self.no_manual:
            flows.append_event(self.fid, {"kind": "review_result", "commit": self.commit, "verdict": "NEEDS_WORK",
                                          "reviewer": 0, "note": "QA"})

    # ---- the home page's quest board: more flows, or none

    def _clear_demo(self) -> None:
        """VBEAR_QA_LOBBY=empty / VBEAR_QA_FRESH=1: RunnerCase.setUp made a task and a flow; remove them before
        anything starts, so there is no session, no flow and nothing waiting for you. FRESH also removes the task
        cards (and _profiles never ran: no role cards): a user who has just installed VBear."""
        flows.delete_flow(self.fid)
        if self.fresh:
            for task in tasks.list_tasks():
                tasks.delete_task(task["id"])

    def _lobby(self) -> None:
        mode = os.environ.get("VBEAR_QA_LOBBY", "")
        if mode != "1":
            return
        add = self._add_flow
        names = ("整理首頁文案", "補上登入流程的測試", "更新安裝說明", "調整深色主題的對比", "修正列表的排序", "改寫設定頁的說明")
        plan = [{"kind": "plan_submitted"}]
        approved = plan + [{"kind": "plan_approved"}, {"kind": "implementation_started"}]
        add(names[0], plan)                                                     # 等核准: waits for you
        add(names[1], approved + [{"kind": "executor_report", "commit": self.commit},
                                  {"kind": "review_result", "commit": self.commit, "verdict": "PASS", "reviewer": 0}],
            workdir=str(self.work))                                              # 等合併: waits for you
        for title in names[2:]:
            add(title, approved)                                                 # worked on by hand

    def _add_flow(self, title, events, workdir=None, session_id=None):
        """One more flow (a task card and its flow) with the main flow's roles, and the events recorded by hand."""
        import copy
        base_roles = copy.deepcopy(flows.get_flow(self.fid)["roles"])
        base_roles["executor"].pop("session_id", None)
        tid = tasks.save_task(None, {"title": title, "workdir": str(self.work), "goal": "（示範）" + title,
                                     "acceptance_criteria": ["相關測試通過"]})["id"]
        roles = base_roles
        if workdir:
            roles["executor"]["workdir"] = workdir
        else:
            roles["executor"].pop("workdir", None)
        if session_id:
            roles["executor"]["session_id"] = session_id
        fid = flows.create_flow({"task_id": tid, "roles": roles}, lambda t: True)["id"]
        for body in events:
            flows.append_event(fid, {"note": "QA", **body})
        return fid

    # ---- the pixel office: flows at every station, synthetic live sessions, a roster of profiles

    def _office(self) -> None:
        mode = os.environ.get("VBEAR_QA_OFFICE", "")
        if mode not in ("1", "stress"):
            return
        stress = mode == "stress"
        plan = [{"kind": "plan_submitted"}]
        approved = plan + [{"kind": "plan_approved"}, {"kind": "implementation_started"}]
        reported = approved + [{"kind": "executor_report", "commit": self.commit}]
        passed = reported + [{"kind": "review_result", "commit": self.commit, "verdict": "PASS", "reviewer": 0}]
        merged = passed + [{"kind": "merge_done"}]
        work = str(self.work)
        working_session = "n-5eed00000001"     # the id shape of a native session; the first synthetic row
        if stress:
            for i in range(5):
                self._add_flow(f"計畫板的任務 {i + 1}", plan if i % 2 else [])
                self._add_flow(f"實作區的任務 {i + 1}", approved, session_id=working_session if i == 0 else None)
                self._add_flow(f"審查室的任務 {i + 1}", reported, workdir=work)
                self._add_flow(f"合併關卡的任務 {i + 1}", passed if i < 3 else merged, workdir=work)
            rows = [("claude", "working", f"示範工人 {i + 1}") for i in range(4)] + \
                [("claude", "waiting", f"等你的工人 {i + 1}") for i in range(3)] + \
                [("codex", "needs-input", "需要你處理的審查員"), ("codex", "unknown", "狀態未知的審查員"),
                 ("shared", "unknown", "別的工具")]
        else:
            self._add_flow("設計新的設定頁", [])                                  # plan board
            self._add_flow("整理首頁文案", plan)                                  # plan board, waits for you
            self._add_flow("更新安裝說明", approved, session_id=working_session)  # build area, bound to a desk
            self._add_flow("修正列表的排序", approved)                            # build area
            self._add_flow("補上登入流程的測試", reported, workdir=work)          # review room
            self._add_flow("調整深色主題的對比", passed, workdir=work)            # merge gate, waits for you
            self._add_flow("發佈說明", merged, workdir=work)                      # merge gate, awaiting push
            rows = [("claude", "working", "實作者"), ("claude", "waiting", "等你回覆的審查前檢查"),
                    ("codex", "unknown", "不確定的終端"), ("claude", "working", "沒有附上證據來源的實作者")]
        agents = []
        for i, (tool, status, label) in enumerate(rows):
            tid = f"n-5eed{i + 1:08x}"
            # Keep a known status without a source in both scenarios to exercise neutral speech.
            source = ("claude-title" if status == "working" else "claude-stream") if tool == "claude" else None
            if label == "沒有附上證據來源的實作者":
                source = None
            reason = {"working": "標題顯示工作中（示範資料）" if source else "工作中，但未附上證據來源（示範資料）",
                      "waiting": "這一輪已結束，等待下一則派工（示範資料）",
                      "needs-input": "停在確認視窗，等你處理；未附上證據來源（示範資料）",
                      "unknown": "沒有已驗證的狀態訊號（示範資料）"}[status]
            act = {"session": "present", "activity": status if status in ("working", "waiting") else "unknown",
                   "needs_input": {"count": 1 if status == "needs-input" else 0,
                                   "reason": reason if status == "needs-input" else None},
                   "needs_input_evidence": None, "resumability": "unknown", "display": status,
                   "reason": reason, "decided_by": source, "evidence": []}
            if source:
                act["evidence"].append({"rung": source,
                                        "label": "終端標題（示範資料）" if source == "claude-title" else "串流協定（示範資料）",
                                        "trust": "authoritative", "value": status, "note": reason,
                                        "since": None, "observed_at": None})
            agents.append({"terminal_id": tid, "pane_id": tid, "agent": tool, "agent_status": status, "activity": act,
                           "tab_id": f"qa-tab-{i}", "workspace_id": "qa-ws", "foreground_cwd": str(self.qa_work),
                           "cwd": str(self.qa_work), "terminal_title_stripped": f"{label}（示範）", "name": label,
                           "agent_session": {}, "focused": False})
        runtime = self.console.store.runtime
        real = runtime.snapshot

        def snapshot(*a, **k):
            snap = dict(real(*a, **k))
            snap["agents"] = list(snap.get("agents") or []) + agents
            snap["tabs"] = list(snap.get("tabs") or []) + [
                {"tab_id": a["tab_id"], "label": a["name"], "workspace_id": a["workspace_id"]} for a in agents]
            return snap
        patcher = mock.patch.object(runtime, "snapshot", snapshot)
        patcher.start()
        self.addCleanup(patcher.stop)
        # profiles: the two of the environment, one whose chosen skill the index cannot find, and in the stress
        # case thirty more (a roster longer than the lounge shows)
        by_dir = {Path(s["path"]).parent.name: s["skill_id"] for s in self.index["skills"]}
        known = set(by_dir.values()) | {GHOST_SKILL_ID}
        agent_profiles.save_profile("demo-ghost-role", {
            "name": "技能找不到的角色（示範）", "model": {"tool": "claude", "model_id": ""}, "enabled": True,
            "equipped_skill_ids": [by_dir["code-review"], GHOST_SKILL_ID],
            "permission_intents": dict(GOOD)}, known_skills=known, known_roles=set())
        if stress:
            for i in range(30):
                tool = ("claude", "codex", "shared")[i % 3]
                agent_profiles.save_profile(f"demo-roster-{i + 1:02d}", {
                    "name": f"示範角色 {i + 1}", "model": {"tool": tool, "model_id": ""}, "enabled": True,
                    "equipped_skill_ids": [by_dir["code-review"]] if tool != "shared" else [],
                    "permission_intents": dict(GOOD)}, known_skills=known, known_roles=set())

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#auth={self.token}"

    def api(self, path):
        st, body = self.call(path)
        self.assertEqual(st, 200, body)
        return body


@unittest.skipIf(DEMO, "Check asserts the default environment (the probe skill, the missing skill); not the demo one")
class Check(_Env):
    def test_the_environment_holds_what_the_checklist_needs(self):
        self.build()
        # the Claude role: four selected skills, one the index cannot find, one whose name is markup
        d = self.api(f"/api/agent-profiles/{CLAUDE_PROFILE}/loadout")
        items = d["skills"]["items"]
        self.assertEqual([i["state"] for i in items], ["in_index", "in_index", "in_index", "not_in_index"])
        self.assertEqual(items[3]["skill_id"], GHOST_SKILL_ID)
        self.assertIn(PROBE, [i.get("name") for i in items])
        self.assertEqual(d["profession"]["state"], "found")
        listing = self.api("/api/agent-profiles")["profiles"]
        mine = next(p for p in listing if p["id"] == CLAUDE_PROFILE)
        self.assertEqual(mine["_unresolved"]["skills"], [GHOST_SKILL_ID])
        # the Codex role: one skill, and its own card (not a Claude one)
        c = self.api(f"/api/agent-profiles/{CODEX_PROFILE}/loadout")
        self.assertEqual(len(c["skills"]["items"]), 1)
        self.assertEqual(c["profile"]["tool"], "codex")
        # the skill card with a missing file and the probe's structure warning
        card = self.api(f"/api/skills/{items[0]['skill_id']}?view=card")
        self.assertEqual(card["skill"]["missing_files"]["items"], ["scripts/lint.sh"])
        probe = self.api(f"/api/skills/{items[2]['skill_id']}?view=card")
        self.assertTrue(probe["skill"]["warnings"]["items"])
        # 出發通行證 is launchable for the Claude role and has its seven labels; the preview starts nothing
        st, r = self.call("/api/native/agent-previews", "POST",
                          {"profile_id": CLAUDE_PROFILE, "workdir": str(self.qa_work), "commit": True})
        self.assertEqual(st, 200, r)
        self.assertTrue(r["preview"]["launchable"], r["preview"]["reasons"])
        self.assertEqual(len(r["preview"]["derived_labels"]), 7)
        self.assertEqual(r["preview"]["cli"]["version"], "2.1.286")
        # the Codex role's check: launchable with the synthetic evidence, or blocked with its own reasons; never
        # a word about Claude in what it returns
        st, cr = self.call("/api/native/agent-previews", "POST",
                           {"profile_id": CODEX_PROFILE, "workdir": str(self.qa_work), "commit": True})
        self.assertEqual(st, 200, cr)
        pv = cr["preview"]
        self.assertEqual(pv["launchable"], not self.codex_blocked, pv["reasons"])
        if self.codex_blocked:
            self.assertIn("codex_interactive_flags_unsupported", [x["code"] for x in pv["reasons"]])
            self.assertTrue(c["armor"]["launch_note"])
        else:
            self.assertEqual(pv["cli"]["version"], "0.159.2")
        self.assertNotIn("Claude", json.dumps(pv["armor_groups"], ensure_ascii=False))
        # the flow: automatic mode, one automatic review round (NEEDS WORK), the user's own records after it
        self.assertEqual(self.api(f"/api/flows/{self.fid}/automation")["mode"], "auto")
        self.assertEqual(self.kinds().count("auto_review_result"), 1)
        flow = self.api(f"/api/flows/{self.fid}")["flow"]
        self.assertEqual(flow["phase"]["key"], "needs_fix")
        self.assertEqual(len(flow["rounds"]), 1)
        if self.no_manual:
            self.assertIsNone(flow["roles"]["executor"].get("workdir"))
            self.assertEqual([e["source"] for e in flow["events"] if e["source"] == "manual"], [])
        else:
            self.assertEqual(flow["roles"]["executor"]["workdir"], str(self.work))
        self.assertTrue(flow["roles"]["reviewers"][0]["independent_of_executor"]["counted"])


@unittest.skipIf(DEMO, "CheckOffice builds its own scenarios")
class CheckOffice(_Env):
    """The two office scenarios hold what design office 6 asks for (the browser checks are the checklist)."""

    STATION = {"planning": "board", "awaiting_approval": "board", "implementing": "build", "needs_fix": "build",
               "in_review": "review", "review_stale": "review", "review_unverified": "review",
               "awaiting_merge": "gate", "awaiting_push": "gate"}

    def office(self, mode):
        with mock.patch.dict(os.environ, {"VBEAR_QA_OFFICE": mode}):
            self.build()
        # one /api/live first: the flows' view reads the live cache that it fills
        live = self.api("/api/live?force=1")
        flow_list = self.api("/api/flows")["flows"]
        profiles = self.api("/api/agent-profiles")["profiles"]
        return live, flow_list, profiles

    def test_the_general_office(self):
        live, flow_list, profiles = self.office("1")
        stations = {}
        for f in flow_list:
            stations.setdefault(self.STATION.get(f["phase"]["key"], "board"), []).append(f)
        self.assertEqual({k: len(v) for k, v in stations.items()}, {"board": 2, "build": 3, "review": 1, "gate": 2})
        self.assertGreaterEqual(len(flow_list), 6)
        # the ones that wait for you: the approval and the two at the gate
        waiting = sorted(f["task_title"] for f in flow_list if f["attention"])
        self.assertEqual(waiting, sorted(["發佈說明", "整理首頁文案", "調整深色主題的對比"]))
        sessions = {x["terminal_id"]: x for x in live["sessions"] if x["terminal_id"].startswith("n-5eed")}
        self.assertEqual(sorted(x["status"] for x in sessions.values()), ["unknown", "waiting", "working", "working"])
        self.assertEqual(sessions["n-5eed00000001"]["activity"]["decided_by"], "claude-title")
        self.assertEqual(sessions["n-5eed00000002"]["activity"]["decided_by"], "claude-stream")
        self.assertIsNone(sessions["n-5eed00000004"]["activity"]["decided_by"])
        for row in sessions.values():
            act = row["activity"]
            self.assertEqual(act["display"], row["status"])
            self.assertTrue(act["reason"])
            if act["decided_by"]:
                self.assertEqual(act["evidence"][0]["rung"], act["decided_by"])
                self.assertEqual(act["evidence"][0]["value"], row["status"])
        self.assertIn("n-5eed00000002", live["attention"])
        # the working session is the executor of one flow, and the live view says it is there
        bound = [f for f in flow_list if f["roles"]["executor"].get("session_id") == "n-5eed00000001"]
        self.assertEqual([f["task_title"] for f in bound], ["更新安裝說明"])
        self.assertEqual(bound[0]["executor_live"]["state"], "working")
        names = {p["id"] for p in profiles}
        self.assertTrue({CLAUDE_PROFILE, CODEX_PROFILE, "demo-ghost-role"} <= names)
        loadout = self.api("/api/agent-profiles/demo-ghost-role/loadout")
        self.assertTrue(any(i["state"] == "not_in_index" for i in loadout["skills"]["items"]))
        self.assertTrue(loadout["tools"]["known"])

    def test_the_crowded_office(self):
        live, flow_list, profiles = self.office("stress")
        stations = {}
        for f in flow_list:
            stations.setdefault(self.STATION.get(f["phase"]["key"], "board"), []).append(f)
        for st in ("board", "build", "review", "gate"):
            self.assertGreater(len(stations[st]), 3, st)
        self.assertEqual(len([x for x in live["sessions"] if x["terminal_id"].startswith("n-5eed")]), 10)
        self.assertGreater(len(profiles), 24)


class CheckCodexBlocked(Check):
    """The Codex checks as they really are: the role cannot be launched, and says why."""

    def setUp(self):
        p = mock.patch.dict(os.environ, {"VBEAR_QA_CODEX_BLOCKED": "1"})
        p.start()
        self.addCleanup(p.stop)
        super().setUp()


class CheckPurelyAutomatic(Check):
    """The same environment with nothing recorded by hand: the phase must still be 「等修正」, from the runner's
    own events alone."""

    def setUp(self):
        p = mock.patch.dict(os.environ, {"VBEAR_QA_NO_MANUAL": "1"})
        p.start()
        self.addCleanup(p.stop)
        super().setUp()


@unittest.skipUnless(os.environ.get("VBEAR_QA_SERVE") == "1", "set VBEAR_QA_SERVE=1 to leave the console running")
class Serve(_Env):
    def test_serve(self):
        self.build()
        seconds = float(os.environ.get("VBEAR_QA_SECONDS", "3600"))
        stop = threading.Event()
        started = False
        if os.environ.get("VBEAR_QA_RUN") == "1":
            started = self.console.runner.start()

            def autopilot():
                fixed = False
                while not stop.is_set():
                    try:
                        events = flows.get_flow(self.fid)["events"]
                        if not fixed and any(e["kind"] == "auto_review_result" and e["verdict"] == "NEEDS WORK"
                                             for e in events):
                            self.commit_work("fix")
                            self.fake_mode("ok")
                            fixed = True
                    except Exception:
                        pass
                    time.sleep(0.3)
            threading.Thread(target=autopilot, daemon=True).start()
        print(CHECKLIST.format(url=self.url(), base=self.base, home=self.home, work=self.qa_work,
                               fid=self.fid, claude=CLAUDE_PROFILE, codex=CODEX_PROFILE, probe=PROBE,
                               manual=("nothing recorded by hand (VBEAR_QA_NO_MANUAL=1): the phase comes from "
                                       "the automatic events; the executor role names no directory, so HEAD is "
                                       "checked in the task's directory" if self.no_manual
                                       else "the harness recorded by hand: plan, approval, start, report, review "
                                            "NEEDS_WORK; the executor role names the work directory"),
                               runner="running (VBEAR_QA_RUN=1)" if started else "idle (flow stays as built)"),
              flush=True)
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            self.console.runner.stop()


CHECKLIST = """
VBear game-UI QA console (synthetic Claude/Codex, temporary HOME and state; nothing real is touched)
  login   {url}
  state   {base}
  home    {home}
  workdir {work}      <- type this folder in the 出發通行證 dialog
  flow    #/flows/{fid}      runner: {runner}
  roles   #/workbench?profile={claude}   (Claude)     #/workbench?profile={codex}   (Codex)
  theme   設定 (#/settings) -> 顯示 -> 外觀: 淺色 / 深色 / 跟隨系統. Check every item below in light AND dark,
          and at a narrow window (about 390 px wide).
  Ctrl-C to stop

Every screen must treat the text {probe} as plain text: no image, no alert, the characters visible.

== 0. 角色卡池 (#/team; use VBEAR_QA_FRESH=1 to see it empty)
  [ ] Title 「角色卡池」; buttons 「＋ 新角色卡」 and (only without a card of your own) 「用起手牌組開始」.
  [ ] 起手牌組: three rows (規劃 CEO, 執行 工匠, 審查 審查員), names editable; with no Codex found the reviewer is
      unticked and says 「這台電腦找不到 Codex」. 「建立 N 張角色卡」 makes ordinary cards.
  [ ] ＋ 新角色卡: three steps (名字與外觀 / 陣營與位置 / 技能卡), 上一步/下一步/建立 always in view (also at 390 px).
      A new card starts from the one set of intents a launch can honour (讀取/編輯/測試 允許, 部署 拒絕), tagged
      「建議，可改」, with the sentence that an intent is not a limit VBear applies and the sentence that this
      is the only set VBear can launch today. Changing an intent to another combination shows
      「這個組合目前不能出發」 with the server's reasons right there. A skill of the other tool is greyed with
      「… 不會讀這張卡」.
  [ ] A card with an undecided intent shows 「還差一步：權限意圖還沒決定」 and 「現在決定」; a decided one says
      「可以出發（權限意圖都已決定）」 and 「實際能不能出發，以出發通行證為準」. 「名冊，不代表正在出勤」 on every card.
  [ ] 出發 opens 出發通行證 in the workbench for that card. 「你電腦裡現成的角色範本（職業標籤）」 is folded.
  [ ] The card is two faces. 翻面 (or the F key with the focus on a card button) shows the back: 陣營與模型, 職業標籤,
      證據來源, 權限意圖 with 「只是記錄，不是授權」 and the sentence that an intent is not a limit, 編輯／複製／刪除,
      and Tool ID / Model ID only under 「進階」. The focus lands on 翻回正面; a screen reader reads one face only.
      With reduced motion the card turns without animation.
  [ ] The skill slots are dashed with 「收藏中」 and the line 「這次的安全啟動不會載入」 (nothing is solid 「生效中」
      today: the server says will_load false for every skill). With VBEAR_QA_CODEX_BLOCKED=1 the Codex card's light
      is the neutral 「不能直接開終端」 (a half-filled ring, blue) with the review-place sentence on the front and
      every original reason on the back; a card with any other reason (e.g. 編輯寫入 拒絕) is the red
      「目前不能出發」. Position badges are a square with one character (規／執／審／？); the shields are flat-topped.
  [ ] 辦公室 (#/office, VBEAR_QA_OFFICE=1): a roster character's panel shows the same card, a short front; the weapons,
      armor (with a shield by 強制／僅意圖／未限制 only) and skills are on the back, which scrolls with the panel.

== 0b. 任務卡＝資料夾 (大廳「任務卡」, 流程 -> 建立流程, 工作台 -> 右側「任務卡」分頁; type folders under {home})
  [ ] 大廳 has the section 「任務卡」 with 「＋ 任務卡（導入專案）」; a card shows the folder name and path, 「分支 … · HEAD …」,
      「這個資料夾目前有 N 個終端」 (open 「各是什麼狀態」: statuses only, no 「在工作」) and 「專案技能 N 張」.
  [ ] 導入專案: step 1 lists 「VBear 在你電腦上看到的專案」 (with 依據), 「最近用過」 and 「貼上路徑」 (~/ works); in a browser it
      says 「瀏覽器拿不到完整路徑，請從清單選或貼上。」 and has no 選擇資料夾… button. The buttons stay in view (also at 390 px).
  [ ] A folder with no .git: the badge 「沒有版本紀錄」 and the whole sentence about commits; buttons 「仍要建立」 and 「換資料夾」.
      The card made from it shows the same badge on its front (lobby and workbench).
  [ ] A folder that already has an unfinished card: 「打開那張卡」 is the main button, 「仍要建一張新的」 the other.
  [ ] {home}/.ssh, the home folder itself, and a folder outside the home: the server's refusal in words, nothing to continue
      with; a missing folder says so. Step 2: title (the folder's name), goal, and 「更多」 (Chinese template names).
  [ ] A card made before folders were required says 「還沒有資料夾 · 」 with 「選資料夾」.
  [ ] 出發通行證 shows 「可以選的範圍：{home} 之內、已經存在的資料夾。」 and a 「挑資料夾…」 button that fills the field.

== 0c. 隊伍 (任務卡的「隊伍」: 工作台 -> 右側「任務卡」分頁, 流程頁, 流程 -> 建立流程; 角色卡池 -> 「放上任務卡」)
  [ ] 任務卡有四個位置：規劃位、執行位、審查位，加一個虛線的「第二位審查（選填）」。點位置開「從角色卡池挑」清單（可用名字找、Esc
      關閉）；也可以把下方的卡拖到位置上，或（手機）先點卡再點位置。「拿下來」清掉一個位置。
  [ ] 把和執行位同陣營的卡放上審查位：位置立刻變紅（還有粗邊和「不算數：」字樣），寫「這個位置需要和執行位不同陣營的卡，審查結果才算數」
      和原因；仍然放得上去。共用卡放審查位、或執行位是共用卡，也是同一句。清單裡每張卡在點下去之前就先標出來。
  [ ] 沒放滿規劃、執行、審查各一位，「建立隊伍」是灰的並寫「還差：…」；空的第二位審查不送出。已有流程的任務卡：「儲存隊伍」要有改動才亮，
      旁邊說明儲存會在時間軸記一筆「角色變更」。伺服器的拒絕寫在出問題的那個位置上，不只是 toast。
  [ ] 角色卡池的卡正面有「放上任務卡」：挑任務卡 → 挑位置 → 「放上去」。任務卡已有流程就直接儲存；沒有就放進草稿，跳到那張任務卡，
      草稿重新整理後還在。非 git 資料夾的隊伍旁有「沒有版本紀錄」和那整句。
  [ ] 把角色卡改過（例如編輯權限意圖）再開流程頁：那個位置寫「CEO 的設定在放上隊伍後改過了 · 更新成最新」，按了才更新；卡刪掉則寫
      「這張角色卡已經不在角色卡池了」；手動填寫的角色寫「手動填寫的角色，沒有對應的角色卡」。
  [ ] 「下一步」清單（任務卡分頁與流程頁）：目前這一步加粗並標「輪到 X」，原本的階段原因留在步驟旁；自動模式多一步「你接受風險」；
      push 在六步之後另寫一行。「風險接受」「串流執行者」「體力」旁有 ⓘ 說明。大廳的任務卡正面有隊伍小頭像和「下一步：…（輪到 …）」。

== 0d. 出發通行證、新手第一局、手機選單、翻譯、登入碼 (VBEAR_QA_FRESH=1 看新手第一局；VBEAR_QA_TRANSLATE=fail 看翻譯失敗)
  [ ] 角色卡的「出發」開「出發通行證：名稱」（不再有「出發前檢查」）。產生預覽後正面只有三行：寫入、網路、commit，各有圖形（勾／驚嘆號／
      問號／叉，形狀不同）和一個狀態字（已擋住／部分擋住／未實測／不明／沒有擋住）。只有「強制」那一級才是勾；commit 一行永遠是
      「擋不住版本紀錄（commit）」。盾牌圖例寫「實線盾牌：強制、虛線盾牌：只是記錄、空盾牌：沒擋」，並說部分擋住、未實測、不明不畫盾牌。
  [ ] 「看七項細節」收合，展開是原本的七項（五組）、可繞過說明在正面。勾選文字是「我知道這個角色會在這個資料夾建立、修改檔案，也能存下
      版本紀錄（commit），VBear 擋不住。」
  [ ] 擋住時每個原因旁有修正按鈕：權限意圖未決定 →「現在決定」開角色卡編輯（步驟 2、權限展開），存檔後回到同一張通行證（資料夾和勾選都在，
      自動重新產生預覽）；資料夾被拒絕 →「換資料夾」；commit 未勾 →「回去勾選知悉」只把焦點移過去，不替你勾。
  [ ] 大廳（VBEAR_QA_FRESH=1）最上方「新手第一局」三步：拿角色卡、導入專案、把隊伍放上任務卡。只有第一個未完成的步驟有按鈕；各步依真實資料
      打勾（示範卡不算）。三步完成後收成一行「你的小隊已就位 · 下一步：…」。「先不要」收起；設定頁可重新顯示。
  [ ] 告示板上的流程卡有隊伍小頭像和「下一步：…（輪到 …）」；副標是「這裡看哪些任務在等你、隊伍走到哪一步。」
  [ ] 390 px 寬：導覽收成一個「選單：目前頁名」按鈕（不橫向捲動），展開後是直向清單，Esc 或換頁收起。
  [ ] 技能卡翻譯確認：主文「會用你自己的 Claude 帳號翻譯這張技能卡，通常不到 1 美分。」，「詳細」展開才是預算與逾時全文。
      翻譯進度列：成功 5 秒後收起；失敗 10 秒後變右下角小圓點，點開看原因；都有關閉鈕。失敗時那張技能卡上寫
      「暫時無法翻譯，原文已保留 · 重試 · 原因」。
  [ ] 用 #auth=<登入碼> 開啟：網址立即清成 #/，交換完成前沒有任何其他請求，不會閃過「請從 VBear 開啟」。

== 1. 角色卡 (工作台 -> 右側「角色」分頁 -> pick 「QA 後端工匠（Claude）」)
  [ ] 資料區：職業標籤=qa-backend; 陣營=Claude Code; 版本驗證狀態 has a sentence from the
      server (not blank); 狀態=啟用; 索引時間 is a time.
  [ ] 職業特性：說明/擅長/適合的工作 each carries a source tag; 未提供 (not 未知) where the author said nothing;
      the fixed note that a profession is only a label.
  [ ] 技能卡（收藏中：VBear 啟動時不載入）：4 rows. 3 are found, 1 says the index cannot find it. The list header on
      the left side says 「目前索引找不到 1 張技能卡」. The probe skill shows its name as text.
  [ ] 防具：seven items in five groups; each group header carries a level word; the heading says the preview
      decides (實際以出發通行證為準); no value is printed as "安全" or a bare "OK".
  [ ] 權限意圖：讀取檔案・允許 編輯寫入・允許 執行測試・允許 部署上線・拒絕; the note says it is only a record and
      that it does not mean VBear limits the program's real abilities.
  [ ] Switch to 「QA 審查員（Codex）」: the card has no Claude-specific wording; its skill list has 1 row.
      With VBEAR_QA_CODEX_BLOCKED=1 the line 「目前無法從 VBear 啟動這個角色…」 is right under the row of
      buttons (above the card), with the reasons; without it this role is launchable on synthetic evidence
      and the line is absent.

== 2. 技能卡 (角色卡的「技能卡特性」按鈕, or 技能庫 -> Armory)
  [ ] code-review: 名稱 with source tag; 類別; 工具; 來源（位置）; 效果 (author text, tagged 作者); 發動時機
      (未提供 if absent); 引用的檔案 lists notes/checklist.md as 存在 and scripts/lint.sh as 缺少; the warning
      box 「缺少的檔案：scripts/lint.sh」 carries a source tag.
  [ ] The probe skill: name and description show as text; 結構檢查 warns that the front-matter name differs
      from the folder name (html-probe).
  [ ] 這張卡的狀態: installed wording, 已選入 1 個角色（本次不生效）, 觀察狀態 (with its period), market copies.
  [ ] The fixed sentence: the effect is the author's description, not verified by VBear; badge 本次不生效.
  [ ] Actions: 從這個角色移除 asks a confirmation in the page (no browser dialog) and changes only the
      selected list; 打開技能檔案; 返回. After a removal, re-add is NOT offered here (use the editor).
  [ ] A skill the index cannot find: its row on the role card says so; no card is invented for it.

== 3. 出發通行證 (角色卡右上「出發通行證」; workdir above; tick the commit box; 產生預覽)
  [ ] Button and dialog title both read 「出發通行證」 (no 「預覽並啟動」 anywhere).
  [ ] Seven labels in five groups (讀取 / 寫入與測試 / 提交與部署 / 網路 / 檔案範圍); each has level, note,
      bypass, evidence; a label that is not enforced is not worded as enforced.
  [ ] 技能卡清單（收藏中），本次不會載入 appears once.
  [ ] The version-verification row names the CLI version (2.1.286) and whether it is verified.
  [ ] The line beside 確認啟動 says why it is off, until a preview exists. Do not press 確認啟動 unless you
      want a (synthetic) session to open.
  [ ] Codex role: the dialog says 「Codex CLI 0.159.2」; there is no 「驗證這個版本」 button, no 「工作中／等你回覆」
      notice, no mention of Claude or Haiku; the group 「未證明」 lists only 「未知」; each label's 證據 column
      shows the evidence reference (launchable run) or the reasons are listed and 確認啟動 stays off with
      「現在不能出發：…」 (VBEAR_QA_CODEX_BLOCKED=1).
  [ ] Skill card, 從這個角色移除: the question names the skill ( 「未提供（ID：…）」 when it has no name), never
      「[object Object]」.

== 4. 隊伍與任務 (流程 -> the flow)
  [ ] 任務進度: seven gates 計畫/核准/實作/審查/合併（你來）/push（你來）/完成. The phase is 「等修正」
      ({manual}), so 計畫/核准/實作 read 已過, 審查 reads 目前：等修正, the rest 未到.
      With VBEAR_QA_RUN=1 the flow reaches the merge gate: the phase becomes 審查通過・等合併 and the line
      「以任務工作目錄核對」 appears when the role names no directory.
  [ ] 隊伍: 規劃者 card says it is only a record and VBear does not launch it; 執行者 card has its live
      state (this flow's executor is not bound to a terminal session, so it reads 未綁定 session), the work
      directory (the temporary one; 「（未設定，無法核對 HEAD）」 with VBEAR_QA_NO_MANUAL=1) and the session; the 審查者 card says it counts as independent of the
      executor (different families). A field that is not there reads 未提供.
  [ ] 體力 (limits): each limit is a bar plus numbers; nothing unknown is drawn as an empty bar (it says
      無法核算); elapsed time has a bar.
  [ ] Cost: 已記錄的花費（CLI 回報）and 未結算 are two numbers; the line 「實際費用尚未知；這裡的數字是用量，
      不是帳單。」 is present.
  [ ] 審查輪次: 1 round, verdict NEEDS WORK, the commit it reviewed.
  [ ] In automatic mode the dispatch box, review start and manual acceptance are off and say why.
  [ ] 停止流程 asks twice; after it, the gates and the team still render.

== 5. 冒險者大廳 (the first page; the nav's first item is 「冒險者大廳」, the title is 「冒險者大廳」)
  Start with VBEAR_QA_LOBBY=1 for the full board, and with VBEAR_QA_LOBBY=empty for the first-run state.
  [ ] 「輪到你」 comes first: the flows waiting for you (VBEAR_QA_LOBBY=1: 「等核准」 and 「審查通過・等合併」),
      then an Agent that waits for you if there is one. Each flow card has one link (its title), the whole
      card is clickable, Tab stops on the card once and shows a focus ring; the type label is the phase's own
      words; the hint reads 「前往處理 →」. The cards have a 2px frame and a bar on the left, and the words
      come with them (colour is not the only sign).
  [ ] 「其他進行中的任務」: at most 4 cards, then 「還有 N 則 →」 to the flows page. The automatic flow says
      「自動執行中」 with its step; a manual one says 「手動模式：VBear 不會替你推進…」. The hint reads 「查看流程 →」.
      A flow that is 完成 is on neither list.
  [ ] The small line beside 「輪到你」 says where the data comes from, that it refreshes every 5 seconds and
      where an Agent whose state is unknown is to be looked at.
  [ ] Wait more than 5 seconds with the search box focused and some text typed: the box keeps its focus and
      text while the board changes (stop the runner or record an event by hand to see a change).
  [ ] VBEAR_QA_LOBBY=empty: one start block: 「大廳目前沒有任務。想開始第一個任務？」, one link 「到終端工作台」
      and the sentence that a task card must be added first; no terminal is listed (no 「等你回覆」 session).
  [ ] VBEAR_QA_FRESH=1: the same board, and also no role card (角色卡池 is empty) and no task card.
  [ ] Break the flows file (or stop the console's runtime) and look: 「讀不到流程：…」 in both blocks, never
      「沒有任務」; with the runtime away and no flow card, 「…無法判斷有沒有 Agent 在等你」.
  [ ] 390 px wide: one column, no sideways scroll, every card still one tap; light and dark both readable.

== 6. 辦公室 (#/office; start with VBEAR_QA_OFFICE=1 for the full office, =stress for the crowded one)
  [ ] 工作站: four stations (計畫板, 實作區, 審查室, 合併關卡). A team is the executor and the reviewer(s) drawn as
      characters with the task name, the phase's own words and 「任務在：<站>」; no character has its own
      status bubble. A team that waits for you has a red 「輪到你」 badge with words and its station has a thick
      frame; nothing else is red. With =stress every station shows 3 and 「這站還有 N 隊 →」.
  [ ] 辦公桌: one desk per live session (two working, waiting, unknown); the bubble above always has words
      (「工作中」「等你回覆」「? 狀態未知」). The desk of the working session names its flow:
      「流程：更新安裝說明（任務在：實作區）」. A session that waits for you has the red badge.
      Select 「沒有附上證據來源的實作者」: its screen says 「◐ 工作中」 and speech uses the neutral runtime
      report with 「沒有附上證據來源」; it must not say 「狀態未知」.
  [ ] 休息室: the roster of profiles (「名冊：角色設定，不代表正在出勤」), at most 24, then 「還有 N 個角色 →」.
  [ ] Click a profile: the panel shows 武器 (Claude: Bash 可用, Edit／Write 鎖住; Codex: 未知 with the reason),
      防具 (solid frame = enforced or partly, dashed = intent only / not limited, each with its words) and 技能卡
      (the skill the index cannot find says 「目前索引找不到此技能（索引時間 …）」, never 「已消失」). It reads the loadout
      once. 換種族 changes only the roster's picture and survives a reload.
  [ ] Click a team: its task, the reason in the phase's words, the members (name, family, model), and the line that
      flow roles have no gear. Click a desk: 「未知：不是用 Profile 啟動的，VBear 看不到它的裝備」 and 開啟終端.
  [ ] The four counts (輪到你 / 工作中 / 狀態未知 / 名冊) at the top and at the foot; a click selects the first one
      and moves the focus to it; with none it says so.
  [ ] Keyboard: Tab goes through every team and character (one stop each), Enter opens the panel, Esc closes it and
      the focus returns to the character; the jump links move the focus to the area headings.
  [ ] Wait 5 seconds with a character selected: the selection and the focus stay. Stop the session (or delete the
      flow): the panel returns with 「剛才選的…已不在辦公室」 and the focus is on an area heading, not on the page.
  [ ] 390 px: no scene, a list (輪到你 → the stations → 辦公桌 → 休息室), a row opens a full panel with 返回.
  [ ] prefers-reduced-motion: the 「輪到你」 badge does not fade in. Light and dark are both readable.
"""




CHECKLIST += """

== 7. 技能中文化（VBEAR_QA_TRANSLATE=1） ==
  [ ] 技能庫：code-review 是機器翻譯；test-writer 標過期；其他技能可按翻成中文。
  [ ] 搜尋「檢查變更的風險」能找到英文技能，結果標明機器翻譯／過期機器翻譯。
  [ ] Armory、工作台的技能卡和技能詳細頁：中文整理預設顯示；看作者原文切換完整說明欄位。
  [ ] 未提供的時機／需求顯示作者未提供；HTML 探針只顯示文字，不產生圖片或執行。
  [ ] 批次過期／未翻：確認資料送出、帳號額度、預算非保證上限、Token 未知與等待上限後才執行。
  [ ] 全域列顯示進度，切到其他頁與重新整理後仍能停止。設定開啟自動重翻需確認；關閉即取消。
  [ ] 設定改 Codex 後自動重翻關閉；此情境仍只執行 qa-translation-cli。
  [ ] 設定兩次確認才清除 1 個孤兒。取消任一步都保留；清除後重新讀取數量是 0。
  [ ] 原文更新：編輯上列 synthetic HOME/.claude/skills/code-review/SKILL.md 的 description，
      按重新掃描後看過期；重新翻譯後恢復。不要修改真實 HOME 任何檔案。
  [ ] 1280／390 px、淺／深色、鍵盤操作、console 無錯誤及截圖，均由 AGY 實際驗證。
"""


class TranslationCheck(_Env):
    def test_fake_translation_scenario(self):
        with mock.patch.dict(os.environ, {"VBEAR_QA_TRANSLATE": "1"}):
            self.build()
        view = self.api("/api/translations")
        self.assertEqual(view["provider"], "fake")
        self.assertEqual(view["counts"]["fresh"], 1)
        self.assertEqual(view["counts"]["stale"], 1)
        self.assertEqual(view["counts"]["orphan"], 1)
        self.assertGreater(view["counts"]["none"], 0)
        status, result = self.call("/api/translations/batch", "POST", {"which": "stale"})
        self.assertEqual(status, 202, result)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            view = self.api("/api/translations")
            if view["job"]["status"] not in ("running", "cancelling"):
                break
            time.sleep(0.05)
        self.assertEqual(view["job"]["status"], "completed", view)
        self.assertEqual(view["job"]["failed"], 0, view)
        self.assertEqual(view["counts"]["stale"], 0)
        self.assertEqual(view["counts"]["fresh"], 2)
        self.assertEqual(self.call("/api/config", "POST", {"translation_engine": "codex"})[0], 200)
        codex_id = self.skill_ids["spare-skill"]
        self.assertEqual(self.call(f"/api/skills/{codex_id}/translate", "POST", {})[0], 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            view = self.api("/api/translations")
            if view["job"]["status"] not in ("running", "cancelling"):
                break
            time.sleep(0.05)
        self.assertEqual(view["job"]["status"], "completed", view)
        self.assertEqual(view["entries"][codex_id]["entry"]["engine"], "codex")
        status, result = self.call("/api/translations/orphans", "DELETE")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(self.api("/api/translations")["counts"]["orphan"], 0)
        source = self.home / ".claude/skills/code-review/SKILL.md"
        source.write_text(source.read_text().replace("Review a diff and list the risky lines.", "Review the changed author text."))
        self.assertEqual(self.call("/api/rescan", "POST", {})[0], 200)
        self.assertEqual(self.api("/api/translations")["counts"]["stale"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
