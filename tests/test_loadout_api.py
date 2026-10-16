"""GET /api/agent-profiles/<id>/loadout (design game-ui 4.1, 4.4, 6, 8): the role card's data.

It is read only and starts nothing: the tests below make every way of starting something fail loudly, then ask
for the loadout with and without an index in memory.
"""

from __future__ import annotations

import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-loadout-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import agent_launch, agent_profiles, index as index_mod, server  # noqa: E402
from vbear import runtime as rt_mod  # noqa: E402
from vbear.config import state_dir  # noqa: E402
from vbear.index import Store  # noqa: E402
from vbear.runtime import cli_versions  # noqa: E402


def _static(**kw):
    skills = [
        {"skill_id": "s-code", "name": "code-review", "invoke_name": "code-review", "tool": "claude",
         "scope": "user", "activation": "active", "path": "/skills/code-review/SKILL.md",
         "description": {"value": "<img src=x onerror=alert(1)> reviews diffs", "origin": "author", "detail": "front matter"},
         "when_to_use": {"value": None, "origin": "missing", "detail": "作者沒有提供"},
         "categories": [{"label": "審查", "keyword": "review"}],
         "referenced_files": [{"ref": "a.py", "status": "present"}, {"ref": "b.sh", "status": "missing"}],
         "missing_files": ["b.sh"], "warnings": ["w1"]},
    ]
    roles = [{"role_id": "r-1", "name": "後端工匠", "tool": "claude", "kind": "subagent",
              "description": {"value": "寫後端", "origin": "author", "detail": "x"},
              "capabilities": {"value": None, "origin": "missing", "detail": ""},
              "suitable_tasks": {"value": ["小功能"], "origin": "derived", "detail": "x"}}]
    d = {"index_version": index_mod.INDEX_VERSION, "generated_at": 1791770000.0, "skills": skills, "roles": roles}
    d.update(kw)
    return d


def _fresh(static=None, live=None, verification=None):
    sd = state_dir()
    if sd.exists():
        shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True, exist_ok=True)
    os.chmod(sd, 0o700)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    c = server.Console.__new__(server.Console)
    c.port = httpd.server_address[1]
    c.store = Store()
    c.store._static = static
    c.store._static_stamp = None
    c.store._live = live
    c.lock = threading.Lock()
    c.auth_token = None
    c.runtime = rt_mod.get_runtime()

    class Verifier:
        def status(self_inner):
            return dict(verification or {"running": False})

    c.claude_verifier = Verifier()
    httpd.RequestHandlerClass = server.make_handler(c)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return c, httpd


def _get(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        finally:
            e.close()


def _profile(**kw):
    body = {"id": "prof-a", "name": "後端工匠", "profession_role_id": "r-1",
            "model": {"tool": "claude", "model_id": ""}, "equipped_skill_ids": ["s-code", "s-gone"],
            "permission_intents": {"read": "allow", "write": "allow", "test": "allow", "deploy": "deny"}}
    body.update(kw)
    return body


class _Helpers:
    def serve(self, **kw):
        c, httpd = _fresh(**kw)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return c, httpd.server_address[1]

    def save(self, c, **kw):
        static = c.store._static
        skills = {s["skill_id"] for s in static["skills"]} | {"s-gone"} if static else set()
        roles = {r["role_id"] for r in static["roles"]} if static else set()
        agent_profiles.save_profile(None, _profile(**kw), known_skills=skills, known_roles=roles)


class LoadoutTests(_Helpers, unittest.TestCase):

    def forbid_everything(self):
        """Every way the loadout could start work fails the test."""
        boom = AssertionError
        patches = [
            mock.patch.object(Store, "_scan", side_effect=boom("scan")),
            mock.patch.object(Store, "_load_or_scan", side_effect=boom("load_or_scan")),
            mock.patch.object(Store, "static", side_effect=boom("Store.static")),
            mock.patch.object(Store, "live", side_effect=boom("Store.live")),
            mock.patch.object(Store, "rescan", side_effect=boom("rescan")),
            mock.patch.object(rt_mod.get_runtime().__class__, "snapshot", side_effect=boom("runtime.snapshot"),
                              create=True),
            mock.patch.object(cli_versions, "probe_version", side_effect=boom("cli probe"), create=True),
            mock.patch("subprocess.run", side_effect=boom("subprocess")),
            mock.patch("subprocess.Popen", side_effect=boom("Popen")),
            mock.patch.object(agent_launch.PreviewStore, "preview", side_effect=boom("preview"), create=True),
            mock.patch("os.listdir", side_effect=boom("listdir")),
            mock.patch("os.scandir", side_effect=boom("scandir")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_it_is_read_only_and_starts_nothing(self):
        c, port = self.serve(static=_static())
        self.save(c)
        self.forbid_everything()
        before = dict(c.store.__dict__)
        status, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertIs(c.store._static, before["_static"])           # nothing was swapped in
        self.assertIsNone(c.store._live)                             # no live view was built

    def test_it_does_not_touch_a_work_directory(self):
        c, port = self.serve(static=_static())
        self.save(c)
        opened = []
        real_open = open

        def spy(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)

        with mock.patch("builtins.open", spy):
            status, _ = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(status, 200)
        for path in opened:
            self.assertNotIn("/projects/", path)
            self.assertTrue(path.startswith(str(FAKE_HOME)) or path.startswith(str(Path(__file__).resolve().parent.parent))
                            or "/lib/python" in path or path.startswith("/dev/") or path.startswith("/private"),
                            path)

    def test_missing_profile_is_404(self):
        c, port = self.serve(static=_static())
        status, body = _get(port, "/api/agent-profiles/nope/loadout")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_a_skill_the_index_does_not_have_is_marked_with_the_index_time(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        by_id = {s["skill_id"]: s for s in body["skills"]["items"]}
        self.assertEqual(by_id["s-gone"]["state"], "not_in_index")
        self.assertEqual(by_id["s-gone"]["note"], "目前索引找不到此技能")
        self.assertEqual(by_id["s-gone"]["indexed_at"], 1791770000.0)
        self.assertEqual(by_id["s-code"]["state"], "in_index")
        self.assertFalse(by_id["s-code"]["effective"])
        self.assertEqual(by_id["s-code"]["referenced_files"],
                         {"count": 2, "present": 1, "missing": 1, "note": "VBear 不會執行這些檔案"})
        self.assertNotIn("executable", json.dumps(by_id["s-code"]))      # no script count (v1.1 #5)

    def test_without_an_index_in_memory_everything_says_not_loaded(self):
        c, port = self.serve(static=None)
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertFalse(body["index"]["loaded"])
        self.assertIsNone(body["index"]["generated_at"])
        self.assertEqual(body["profession"]["state"], "index_not_loaded")
        self.assertTrue(all(s["state"] == "index_not_loaded" for s in body["skills"]["items"]))
        self.assertIsNone(c.store._static)                              # and it did not load one

    def test_the_role_and_the_text_of_a_skill_come_with_their_source(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        prof = body["profession"]
        self.assertEqual(prof["state"], "found")
        self.assertEqual(prof["description"], {"value": "寫後端", "origin": "author", "detail": "x"})
        self.assertEqual(prof["capabilities"]["origin"], "missing")
        self.assertIsNone(prof["capabilities"]["value"])
        self.assertIn("職業只是標籤", prof["label_only"])
        skill = next(s for s in body["skills"]["items"] if s["skill_id"] == "s-code")
        self.assertEqual(skill["when_to_use"]["origin"], "missing")
        # the hostile text is data: it is returned as is, for the page to show with textContent
        self.assertIn("<img", skill["description"]["value"])

    def test_no_attendance_fields(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        text = json.dumps(body, ensure_ascii=False)
        for word in ("出勤", "曾使用", "attendance", "used_count", "times_used", "session_count"):
            self.assertNotIn(word, text)

    def test_observation_states(self):
        live = {"usage": {"window_days": 30, "problems": [], "sessions": [
            {"session_id": "x", "skills": [{"skill_ids": ["s-code"], "count": 2, "last_ts": 1791760000.0}]}]}}
        c, port = self.serve(static=_static(), live=live)
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        obs = next(s for s in body["skills"]["items"] if s["skill_id"] == "s-code")["observed"]
        self.assertEqual((obs["state"], obs["window_days"], obs["source"]), ("observed", 30, "執行觀察"))
        # a view with no usage rows: no record in the window
        c2, port2 = self.serve(static=_static(), live={"usage": {"window_days": 30, "problems": [], "sessions": []}})
        self.save(c2)
        _, body = _get(port2, "/api/agent-profiles/prof-a/loadout")
        obs = next(s for s in body["skills"]["items"] if s["skill_id"] == "s-code")["observed"]
        self.assertEqual(obs["state"], "none")
        # no live view built, or usage scanning off: not available (never "none")
        for live in (None, {"usage": {"window_days": 30, "problems": ["使用紀錄掃描已在設定中關閉"], "sessions": []}}):
            c3, port3 = self.serve(static=_static(), live=live)
            self.save(c3)
            _, body = _get(port3, "/api/agent-profiles/prof-a/loadout")
            obs = next(s for s in body["skills"]["items"] if s["skill_id"] == "s-code")["observed"]
            self.assertEqual(obs["state"], "unavailable")

    def test_armor_is_the_verified_setting_and_says_what_it_does_not_know(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        armor = body["armor"]
        self.assertTrue(armor["applicable"])
        self.assertEqual(armor["basis"], "verified_setting")
        self.assertEqual(armor["preview_decides"], "實際以出發通行證為準")
        self.assertEqual(body["version_status"]["state"], "unknown")
        names = [i["name"] for i in armor["items"]]
        self.assertEqual(names, list(agent_launch.ARMOR_NAMES))
        write = next(i for i in armor["items"] if i["name"] == "Write")
        self.assertEqual(write["level"], agent_launch.PARTIAL)
        self.assertEqual(write["group"], "partial")
        self.assertEqual(write["path_scope"], "產生出發通行證時才知道")
        commit = next(i for i in armor["items"] if i["name"] == "Commit")
        self.assertEqual(commit["group"], "not_blocked")
        self.assertEqual([g["label"] for g in armor["groups"]], ["擋住了", "部分擋住", "沒有專用權限", "沒有擋", "未證明"])

    def test_a_version_this_console_found_unverified_is_shown_so(self):
        c, port = self.serve(static=_static(),
                             verification={"running": False, "result": "failed", "version": "2.1.999"})
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(body["version_status"]["state"], "unverified")
        self.assertEqual(body["version_status"]["version"], "2.1.999")
        self.assertIn("未驗證（Claude Code 2.1.999", body["version_status"]["text"])
        net = next(i for i in body["armor"]["items"] if i["name"] == "Network")
        self.assertEqual(net["group"], "unproven")

    def test_shared_tool_has_no_armor(self):
        c, port = self.serve(static=_static())
        self.save(c, model={"tool": "shared", "model_id": ""})
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertFalse(body["armor"]["applicable"])
        self.assertTrue(any(b["code"] == "tool_not_launchable" for b in body["blockers"]))

    def test_tools_are_the_launch_constants_for_claude_and_unknown_with_a_reason_otherwise(self):
        # office design 3.1: always an object; the Claude lists are the constants the argv is built from
        from vbear.runtime import agent_sessions
        c, port = self.serve(static=_static())
        self.save(c, model={"tool": "claude", "model_id": ""})
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        tools = body["tools"]
        self.assertEqual(set(tools), {"known", "allowed", "blocked", "source"})
        self.assertIs(tools["known"], True)
        self.assertEqual(tools["allowed"], ["Bash"])
        self.assertEqual(tools["blocked"], ["Edit", "Write"])
        self.assertTrue(tools["source"])
        # the same words as the argv of a launch, not a second copy
        argv = agent_sessions.claude_argv({"cli_binary": "/x/claude", "settings_path": "/x/s.json"})
        self.assertEqual(tools["allowed"], argv[argv.index("--tools") + 1].split(","))
        self.assertEqual(tools["blocked"], argv[argv.index("--disallowedTools") + 1].split(","))
        with mock.patch.object(agent_sessions, "CLAUDE_TOOLS_ALLOWED", ("Bash", "Grep")):
            _, changed = _get(port, "/api/agent-profiles/prof-a/loadout")
            argv2 = agent_sessions.claude_argv({"cli_binary": "/x/claude", "settings_path": "/x/s.json"})
        self.assertEqual(changed["tools"]["allowed"], ["Bash", "Grep"])
        self.assertEqual(argv2[argv2.index("--tools") + 1], "Bash,Grep")

    def test_tools_of_other_tools_are_unknown_with_the_constant_reason(self):
        from vbear import loadout
        c, port = self.serve(static=_static())
        self.save(c, model={"tool": "codex", "model_id": ""})
        _, codex = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(codex["tools"], {"known": False, "allowed": [], "blocked": [],
                                          "unknown_reason": loadout.CODEX_NOT_LAUNCHABLE})
        self.assertEqual(codex["tools"]["unknown_reason"], codex["armor"]["launch_note"])
        self.save(c, model={"tool": "shared", "model_id": ""})
        _, shared = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(shared["tools"], {"known": False, "allowed": [], "blocked": [],
                                           "unknown_reason": loadout.TOOLS_ONLY_CLAUDE})
        self.assertEqual(loadout.TOOLS_ONLY_CLAUDE, "VBear 目前只支援用角色卡啟動 Claude Code")
        # a Codex role that is launchable on recorded evidence: the tool list is still not recorded, and says so
        launchable = loadout._tools("codex", False)
        self.assertEqual(launchable, {"known": False, "allowed": [], "blocked": [],
                                      "unknown_reason": loadout.TOOLS_CODEX_NOT_RECORDED})

    def test_tools_are_the_only_new_field(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(set(body), {"ok", "profile", "index", "profession", "skills", "version_status", "tools",
                                     "armor", "blockers", "blockers_note"})

    def snapshot(self):
        """Every file under the state directory: size, mtime and content hash, so that 'nothing changed' is
        a comparison and not a hope."""
        import hashlib
        out = {}
        for path in sorted(state_dir().rglob("*")):
            rel = str(path.relative_to(state_dir()))
            if path.is_file() and not path.is_symlink():
                st = path.stat()
                out[rel] = (st.st_size, st.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
            else:
                out[rel] = ("dir" if path.is_dir() else "other",)
        return out

    def test_a_damaged_profile_file_is_reported_and_left_alone(self):
        import vbear.agent_profiles as ap
        for name, content in (("not json", "{not json"),
                              ("not an object", "[1, 2]"),
                              ("a bad entry", json.dumps({"prof-a": {"id": "prof-a", "name": 5}}))):
            with self.subTest(name):
                c, port = self.serve(static=_static())
                path = ap._path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                before = self.snapshot()
                status, body = _get(port, "/api/agent-profiles/prof-a/loadout")
                after = self.snapshot()
                self.assertEqual(status, 409, body)
                self.assertEqual(body["code"], "profile_store_damaged")
                self.assertIn("角色頁", body["hint"])
                self.assertEqual(after, before, "the read changed the file system")
                self.assertTrue(path.exists(), "the file was moved")
                self.assertFalse(any(".corrupt-" in n for n in after), "a quarantine copy was made")
                self.assertFalse(ap._corrupt_marker_path().exists(), "a marker was written")

    def test_a_marker_left_by_an_earlier_read_is_reported_without_writing(self):
        import vbear.agent_profiles as ap
        c, port = self.serve(static=_static())
        ap._corrupt_marker_path().parent.mkdir(parents=True, exist_ok=True)
        ap._corrupt_marker_path().write_text("{}")
        before = self.snapshot()
        status, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual((status, body["code"]), (409, "profile_store_damaged"))
        self.assertEqual(self.snapshot(), before)

    def test_the_groups_carry_the_original_level_words(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        levels = {g["id"]: g["levels"] for g in body["armor"]["groups"]}
        self.assertEqual(levels["blocked"], [agent_launch.ENFORCED])
        self.assertEqual(levels["partial"], [agent_launch.PARTIAL])
        self.assertEqual(levels["not_granted"], [agent_launch.NOT_GRANTED])
        self.assertEqual(levels["not_blocked"], [agent_launch.INTENT, agent_launch.UNRESTRICTED])
        self.assertEqual(levels["unproven"], [agent_launch.UNVERIFIED, agent_launch.UNKNOWN])
        self.assertEqual(body["armor"]["title"], "防具（以已驗證設定為準）")

    def test_a_codex_role_gets_nothing_from_claude(self):
        # Claude Code was verified in this console; the role is a Codex one.
        static = _static()
        for rec in static["skills"] + static["roles"]:
            rec["tool"] = "codex"                 # the index's own tool field is data; keep the words ours
        c, port = self.serve(static=static, verification={"running": False, "result": "passed", "version": "2.1.296"})
        self.save(c, model={"tool": "codex", "model_id": ""})
        status, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(status, 200)
        text = json.dumps(body, ensure_ascii=False)
        for word in ("Claude", "claude", "2.1.296", "安全模式", "safe-mode", "--safe", "safe_mode"):
            self.assertNotIn(word, text, word)
        self.assertEqual(body["version_status"]["state"], "unknown")
        self.assertIn("Codex", body["version_status"]["text"])
        self.assertEqual(body["profession"]["label_only"], "職業只是標籤，不會把角色指示載入 Codex")
        unproven = next(g for g in body["armor"]["groups"] if g["id"] == "unproven")
        self.assertEqual(unproven["levels"], [agent_launch.UNKNOWN])
        self.assertNotIn("safe_mode", body["skills"])
        self.assertEqual(body["skills"]["note"], "VBear 目前不提供 Codex 角色的受管啟動，已選技能是你的挑選紀錄。")
        self.assertEqual(body["armor"]["launch_note"],
                         "目前無法從 VBear 啟動這個角色（Codex 的互動模式還不能安全地受管啟動）")
        self.assertTrue(any(b["code"] == "codex_interactive_flags_unsupported" for b in body["blockers"]))
        # the armor is the Codex one: evidence for its Network and Filesystem items is what decides them
        items = {i["name"]: i for i in body["armor"]["items"]}
        expected = agent_launch.armor_items("codex", None, True, bool(agent_launch._codex_evidence_reference()))
        for name, it in expected.items():
            self.assertEqual((items[name]["level"], items[name]["note"]), (it["level"], it["note"]))
        self.assertTrue(all(s["effective"] is False for s in body["skills"]["items"]))

    def test_skill_notice_names_the_verified_version_only(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertIn("2.1.296", body["skills"]["safe_mode"])
        self.assertIn("其他版本是否停用技能未驗證", body["skills"]["safe_mode"])
        self.assertTrue(all(s["effective"] is False for s in body["skills"]["items"]))
        self.assertEqual(body["skills"]["title"], "技能卡（收藏中：VBear 啟動時不載入）")

    def test_every_skill_says_whether_it_will_load_and_the_section_says_all_inactive(self):
        """R1: the card draws dashed or solid slots from these two fields, never from the words."""
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        items = body["skills"]["items"]
        self.assertEqual({s["state"] for s in items}, {"in_index", "not_in_index"})
        for s in items:
            self.assertIs(s["will_load"], False, s)
        self.assertIs(body["skills"]["all_inactive"], True)
        # no index in memory: the answer is still a plain no, not a missing field
        c2, port2 = self.serve(static=None)
        self.save(c2)
        _, body = _get(port2, "/api/agent-profiles/prof-a/loadout")
        self.assertTrue(all(s["state"] == "index_not_loaded" and s["will_load"] is False
                            for s in body["skills"]["items"]))
        self.assertIs(body["skills"]["all_inactive"], True)

    def test_will_load_is_false_for_every_tool_and_all_inactive_holds_with_no_skills(self):
        c, port = self.serve(static=_static())
        for tool in ("claude", "codex", "shared"):
            self.save(c, model={"tool": tool, "model_id": ""}, equipped_skill_ids=["s-code"])
            _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
            self.assertEqual([s["will_load"] for s in body["skills"]["items"]], [False], tool)
            self.assertIs(body["skills"]["all_inactive"], True, tool)
            self.assertTrue(all(s["effective"] is False for s in body["skills"]["items"]), tool)
        self.save(c, equipped_skill_ids=[])
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(body["skills"]["items"], [])
        self.assertIs(body["skills"]["all_inactive"], True)

    def test_all_inactive_is_worked_out_from_the_items_not_fixed(self):
        """When a tool one day reports that a skill loads, the section says so and the title stops claiming it."""
        from vbear import loadout
        c, port = self.serve(static=_static())
        self.save(c)
        with mock.patch.object(loadout, "_will_load", side_effect=lambda tool, sid: sid == "s-code"):
            _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        by_id = {s["skill_id"]: s["will_load"] for s in body["skills"]["items"]}
        self.assertEqual(by_id, {"s-code": True, "s-gone": False})
        self.assertIs(body["skills"]["all_inactive"], False)
        self.assertEqual(body["skills"]["title"], "技能卡")


class SkillCardTests(_Helpers, unittest.TestCase):
    """GET /api/skills/<id>?view=card (design game-ui 4.2, 6)."""

    def _static_with_copy(self):
        d = _static()
        d["skills"][0]["inputs"] = {"value": "一段 diff", "origin": "derived", "detail": "章節"}
        d["skills"][0]["outputs"] = {"value": None, "origin": "missing", "detail": ""}
        d["skills"][0]["duplicate_of"] = ["s-market", "s-other-installed"]
        d["skills"].append({"skill_id": "s-market", "name": "code-review", "tool": "claude", "scope": "marketplace",
                            "activation": "not_installed", "path": "/m/SKILL.md"})
        d["skills"].append({"skill_id": "s-other-installed", "name": "code-review", "tool": "claude",
                            "scope": "project", "activation": "active", "path": "/p/SKILL.md"})
        return d

    def forbid(self):
        for p in (mock.patch.object(Store, "_scan", side_effect=AssertionError("scan")),
                  mock.patch.object(Store, "_load_or_scan", side_effect=AssertionError("load_or_scan")),
                  mock.patch.object(Store, "static", side_effect=AssertionError("static")),
                  mock.patch.object(Store, "live", side_effect=AssertionError("live build")),
                  mock.patch.object(Store, "rescan", side_effect=AssertionError("rescan")),
                  mock.patch.object(server.Console, "armory_view", side_effect=AssertionError("armory_view"),
                                    create=True),
                  mock.patch.object(server.Console, "usage_for_skill", side_effect=AssertionError("usage"),
                                    create=True),
                  mock.patch("subprocess.run", side_effect=AssertionError("subprocess")),
                  mock.patch("subprocess.Popen", side_effect=AssertionError("Popen"))):
            p.start()
            self.addCleanup(p.stop)

    def test_card_mode_starts_nothing_and_does_not_read_the_skill_file(self):
        c, port = self.serve(static=self._static_with_copy())
        self.save(c)
        self.forbid()
        opened = []
        real_open = open

        def spy(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)

        with mock.patch("builtins.open", spy):
            status, body = _get(port, "/api/skills/s-code?view=card")
        self.assertEqual(status, 200, body)
        self.assertFalse(any("SKILL.md" in f for f in opened), opened)
        self.assertNotIn("raw", body)
        self.assertNotIn("usage", body)               # the old field is not computed in this mode
        self.assertNotIn("/skills/code-review", json.dumps(body))    # and no path leaves the server

    def test_card_fields(self):
        live = {"usage": {"window_days": 14, "problems": [], "sessions": [
            {"skills": [{"skill_ids": ["s-code"], "last_ts": 1791760000.0}]}]}}
        c, port = self.serve(static=self._static_with_copy(), live=live)
        self.save(c)
        status, body = _get(port, "/api/skills/s-code?view=card")
        self.assertEqual(status, 200)
        sk = body["skill"]
        self.assertEqual(sk["installed"], True)
        self.assertEqual(sk["name"], {"value": "code-review", "origin": "derived", "detail": "技能檔案（掃描整理）"})
        self.assertEqual(sk["missing_files"], {"items": ["b.sh"], "origin": "derived", "detail": "掃描結果"})
        self.assertEqual(sk["warnings"], {"items": ["w1"], "origin": "derived", "detail": "掃描結果"})
        # tool, scope and categories are VBear's own reading: they say so, and a missing one is missing
        self.assertEqual(sk["tool"], {"value": "claude", "origin": "derived", "detail": "掃描位置判讀"})
        self.assertEqual(sk["scope"], {"value": "user", "origin": "derived", "detail": "掃描位置判讀"})
        self.assertEqual((sk["categories"]["value"], sk["categories"]["origin"]), (["審查"], "derived"))
        self.assertEqual(sk["categories"]["matches"], [{"label": "審查", "keyword": "review"}])
        self.assertEqual(sk["referenced_files"]["origin"], "derived")
        self.assertEqual(sk["status_source"]["origin"], "derived")
        self.assertEqual(body["added_to_roles"]["origin"], "user")
        self.assertEqual(body["marketplace_source"]["origin"], "derived")
        self.assertEqual(body["observation"]["origin"], "runtime")
        self.assertEqual(sk["inputs"], {"value": "一段 diff", "origin": "derived", "detail": "章節"})
        self.assertEqual(sk["outputs"]["origin"], "missing")
        self.assertIsNone(sk["outputs"]["value"])
        self.assertEqual(sk["referenced_files"]["count"], 2)
        self.assertEqual(sk["referenced_files"]["items"], [{"ref": "a.py", "status": "present"},
                                                          {"ref": "b.sh", "status": "missing"}])
        self.assertIn("不會執行", sk["referenced_files"]["note"])
        self.assertNotIn("executable", json.dumps(body))
        self.assertEqual(body["added_to_roles"]["items"], [{"id": "prof-a", "name": "後端工匠", "enabled": True}])
        self.assertIs(body["added_to_roles"]["effective"], False)
        self.assertIn("本次不生效", body["added_to_roles"]["note"])
        self.assertEqual(body["observation"]["state"], "observed")
        self.assertEqual(body["observation"]["window_days"], 14)
        # only an uninstalled copy counts as 'the marketplace has another copy'
        self.assertEqual(body["marketplace_copies"], [{"skill_id": "s-market", "tool": "claude", "scope": "marketplace"}])
        self.assertIn("只適用於你自己啟動並載入這張技能的工具", body["effect_note"])

    def test_no_index_in_memory_and_unknown_skill(self):
        c, port = self.serve(static=None)
        status, body = _get(port, "/api/skills/s-code?view=card")
        self.assertEqual((status, body["code"]), (409, "index_not_loaded"))
        self.assertIsNone(c.store._static)
        c2, port2 = self.serve(static=_static())
        status, body = _get(port2, "/api/skills/nope?view=card")
        self.assertEqual((status, body["code"]), (404, "not_in_index"))
        self.assertEqual(body["indexed_at"], 1791770000.0)

    def test_observation_is_not_available_without_a_live_view(self):
        c, port = self.serve(static=_static(), live=None)
        _, body = _get(port, "/api/skills/s-code?view=card")
        self.assertEqual(body["observation"]["state"], "unavailable")

    def test_a_damaged_profile_store_does_not_break_the_card_or_get_touched(self):
        import vbear.agent_profiles as ap
        c, port = self.serve(static=_static())
        path = ap._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken")
        before = path.read_bytes()
        status, body = _get(port, "/api/skills/s-code?view=card")
        self.assertEqual(status, 200)
        self.assertIn("unavailable", body["added_to_roles"])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(ap._corrupt_marker_path().exists())
        self.assertEqual([x.name for x in path.parent.iterdir() if ".corrupt-" in x.name], [])

    def test_a_skill_without_those_fields_has_them_missing_not_guessed(self):
        d = _static()
        d["skills"][0].pop("categories")
        d["skills"][0].pop("referenced_files")
        d["skills"][0]["tool"] = ""
        d["skills"][0]["scope"] = None
        c, port = self.serve(static=d)
        _, body = _get(port, "/api/skills/s-code?view=card")
        sk = body["skill"]
        for field in ("tool", "scope", "categories"):
            self.assertEqual((sk[field]["value"], sk[field]["origin"]), (None, "missing"), field)
        self.assertEqual(sk["referenced_files"]["count"], 0)

    def _assert_no_internals(self, text):
        for needle in ("/", "marker", "corrupt", str(FAKE_HOME), "Traceback", "agent_profiles"):
            self.assertNotIn(needle, text, needle)

    def test_error_answers_carry_no_path_and_the_log_has_the_kind_only(self):
        import io
        import vbear.agent_profiles as ap
        cases = {
            "a marker is there": lambda: (ap._corrupt_marker_path().parent.mkdir(parents=True, exist_ok=True),
                                          ap._corrupt_marker_path().write_text("{}")),
            "the file is a directory": lambda: ap._path().parent.mkdir(parents=True, exist_ok=True)
            or ap._path().mkdir(),
            "the file is broken": lambda: (ap._path().parent.mkdir(parents=True, exist_ok=True),
                                           ap._path().write_text("{broken")),
        }
        for name, make in cases.items():
            with self.subTest(name):
                c, port = self.serve(static=_static())
                make()
                err = io.StringIO()
                with mock.patch("sys.stderr", err):
                    status, loadout_body = _get(port, "/api/agent-profiles/prof-a/loadout")
                    card_status, card = _get(port, "/api/skills/s-code?view=card")
                self.assertEqual(status, 409)
                self.assertEqual(loadout_body["code"], "profile_store_damaged")
                self.assertEqual(loadout_body["error"], "角色資料無法讀取，請到角色頁處理")
                self._assert_no_internals(json.dumps(loadout_body, ensure_ascii=False))
                self.assertEqual(card_status, 200)
                self.assertEqual(card["added_to_roles"]["unavailable"], "角色資料無法讀取，請到角色頁處理")
                self.assertEqual(card["added_to_roles"]["code"], "profile_store_damaged")
                self._assert_no_internals(json.dumps(card["added_to_roles"], ensure_ascii=False))
                log = err.getvalue()
                self.assertIn("profile store unreadable: AgentProfile", log)
                self._assert_no_internals_log(log)

    def _assert_no_internals_log(self, text):
        for needle in ("marker", str(FAKE_HOME), ".json", "Traceback"):
            self.assertNotIn(needle, text, needle)
        self.assertNotIn("/", text)

    def test_without_the_parameter_the_old_detail_answer_is_unchanged(self):
        c, port = self.serve(static=_static())
        self.save(c)
        with mock.patch.object(server.Console, "usage_for_skill", return_value=[], create=True) as usage, \
             mock.patch.object(server.Console, "armory_view", return_value={"skills": []}, create=True):
            status, body = _get(port, "/api/skills/s-code")
        self.assertEqual(status, 200)
        for key in ("skill", "equipped_by", "usage", "raw", "roles", "duplicates"):
            self.assertIn(key, body)
        usage.assert_called()


if __name__ == "__main__":
    unittest.main()
