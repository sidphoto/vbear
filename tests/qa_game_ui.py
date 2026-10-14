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
      deletes the flow instead, so the board is in its first-run state (no flow, no waiting Agent).
      Optional VBEAR_QA_CODEX_BLOCKED=1: leave the Codex checks as they really are (no synthetic evidence), so
      the Codex role cannot be launched from VBear: its card and the 出發前檢查 dialog then show the reason.
      Without it the synthetic Codex evidence is on and its preview is launchable, which shows the evidence
      lines of the Codex labels.
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
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_automation_runner import RunnerCase
from tests.test_runtimed_managed import FAKE_CLI, FAKE_CODEX_CLI
from vbear import agent_launch, agent_profiles, flows, tasks
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
        self._skills_and_roles()
        self._profiles()
        self._launch_environment()
        self._flow()
        self._lobby()

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
        else:
            # the name and description are HTML-like text: every screen must show them as text, never run them
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

    # ---- 出發前檢查 needs a CLI to look at: the synthetic ones, pinned for this process only

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

    def _lobby(self) -> None:
        mode = os.environ.get("VBEAR_QA_LOBBY", "")
        if mode == "empty":
            flows.delete_flow(self.fid)
            return
        if mode != "1":
            return
        import copy
        base_roles = copy.deepcopy(flows.get_flow(self.fid)["roles"])
        base_roles["executor"].pop("session_id", None)
        names = ("整理首頁文案", "補上登入流程的測試", "更新安裝說明", "調整深色主題的對比", "修正列表的排序", "改寫設定頁的說明")

        def add(title, events, workdir=None):
            tid = tasks.save_task(None, {"title": title, "workdir": str(self.work), "goal": "（示範）" + title,
                                         "acceptance_criteria": ["相關測試通過"]})["id"]
            roles = copy.deepcopy(base_roles)
            if workdir:
                roles["executor"]["workdir"] = workdir
            else:
                roles["executor"].pop("workdir", None)
            fid = flows.create_flow({"task_id": tid, "roles": roles}, lambda t: True)["id"]
            for body in events:
                flows.append_event(fid, {"note": "QA", **body})
            return fid

        plan = [{"kind": "plan_submitted"}]
        approved = plan + [{"kind": "plan_approved"}, {"kind": "implementation_started"}]
        add(names[0], plan)                                                     # 等核准: waits for you
        add(names[1], approved + [{"kind": "executor_report", "commit": self.commit},
                                  {"kind": "review_result", "commit": self.commit, "verdict": "PASS", "reviewer": 0}],
            workdir=str(self.work))                                              # 等合併: waits for you
        for title in names[2:]:
            add(title, approved)                                                 # worked on by hand

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
        # 出發前檢查 is launchable for the Claude role and has its seven labels; the preview starts nothing
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
  workdir {work}      <- type this folder in the 出發前檢查 dialog
  flow    #/flows/{fid}      runner: {runner}
  roles   #/workbench?profile={claude}   (Claude)     #/workbench?profile={codex}   (Codex)
  theme   設定 (#/settings) -> 顯示 -> 外觀: 淺色 / 深色 / 跟隨系統. Check every item below in light AND dark,
          and at a narrow window (about 390 px wide).
  Ctrl-C to stop

Every screen must treat the text {probe} as plain text: no image, no alert, the characters visible.

== 1. 角色卡 (工作台 -> 右側「角色」分頁 -> pick 「QA 後端工匠（Claude）」)
  [ ] 資料區：職業=qa-backend; 工具（遊戲用語：陣營）=Claude Code; 版本驗證狀態 has a sentence from the
      server (not blank); 狀態=啟用; 索引時間 is a time.
  [ ] 職業特性：說明/擅長/適合的工作 each carries a source tag; 未提供 (not 未知) where the author said nothing;
      the fixed note that a profession is only a label.
  [ ] 已選技能（VBear 啟動時不載入）：4 rows. 3 are found, 1 says the index cannot find it. The list header on
      the left side says 「目前索引找不到 1 項已選技能」. The probe skill shows its name as text.
  [ ] 防具：seven items in five groups; each group header carries a level word; the heading says the preview
      decides (實際以出發前檢查為準); no value is printed as "安全" or a bare "OK".
  [ ] 你的期望（意圖）：讀取・允許 寫入・允許 測試・允許 部署・拒絕; the note says it is only a record.
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

== 3. 出發前檢查 (角色卡右上「出發前檢查」; workdir above; tick the commit box; 產生預覽)
  [ ] Button and dialog title both read 「出發前檢查」 (no 「預覽並啟動」 anywhere).
  [ ] Seven labels in five groups (讀取 / 寫入與測試 / 提交與部署 / 網路 / 檔案範圍); each has level, note,
      bypass, evidence; a label that is not enforced is not worded as enforced.
  [ ] 已選清單，本次不會載入 appears once.
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
      and the sentence that a task card must be added first.
  [ ] Break the flows file (or stop the console's runtime) and look: 「讀不到流程：…」 in both blocks, never
      「沒有任務」; with the runtime away and no flow card, 「…無法判斷有沒有 Agent 在等你」.
  [ ] 390 px wide: one column, no sideways scroll, every card still one tap; light and dark both readable.
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)
