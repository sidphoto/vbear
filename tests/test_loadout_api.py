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


class LoadoutTests(unittest.TestCase):
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
        self.assertEqual(armor["preview_decides"], "實際以出發前檢查為準")
        self.assertEqual(body["version_status"]["state"], "unknown")
        names = [i["name"] for i in armor["items"]]
        self.assertEqual(names, list(agent_launch.ARMOR_NAMES))
        write = next(i for i in armor["items"] if i["name"] == "Write")
        self.assertEqual(write["level"], agent_launch.PARTIAL)
        self.assertEqual(write["group"], "partial")
        self.assertEqual(write["path_scope"], "出發前檢查時才知道")
        commit = next(i for i in armor["items"] if i["name"] == "Commit")
        self.assertEqual(commit["group"], "not_blocked")
        self.assertEqual([g["label"] for g in armor["groups"]], ["擋住了", "部分擋住", "沒有專用權限", "沒有擋", "未證明"])

    def test_a_version_this_console_found_unverified_is_shown_so(self):
        c, port = self.serve(static=_static(),
                             verification={"running": False, "result": "failed", "version": "2.1.999"})
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertEqual(body["version_status"], {"state": "unverified", "version": "2.1.999",
                                                  "source": "這個主控台剛驗證過的結果"})
        net = next(i for i in body["armor"]["items"] if i["name"] == "Network")
        self.assertEqual(net["group"], "unproven")

    def test_shared_tool_has_no_armor(self):
        c, port = self.serve(static=_static())
        self.save(c, model={"tool": "shared", "model_id": ""})
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertFalse(body["armor"]["applicable"])
        self.assertTrue(any(b["code"] == "tool_not_launchable" for b in body["blockers"]))

    def test_skill_notice_names_the_verified_version_only(self):
        c, port = self.serve(static=_static())
        self.save(c)
        _, body = _get(port, "/api/agent-profiles/prof-a/loadout")
        self.assertIn("2.1.296", body["skills"]["safe_mode"])
        self.assertIn("其他版本是否停用技能未驗證", body["skills"]["safe_mode"])
        self.assertTrue(all(s["effective"] is False for s in body["skills"]["items"]))
        self.assertEqual(body["skills"]["title"], "已選技能（VBear 啟動時不載入）")


if __name__ == "__main__":
    unittest.main()
