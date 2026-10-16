"""GET /api/folders/inspect, the folder rules behind it, and the config keys task cards add
(`recent_folders`, `onboarding_dismissed`).

Boots a real `vbear.server.Console` on loopback in a temporary HOME. The endpoint is read-only: no
process (git included), no tree walk, no write; a place that must never be a project is refused the
same way whether or not it exists.

Run: python3 -m unittest tests.test_folders_api -v
"""

from __future__ import annotations

import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"  # never spawn a runtime daemon from tests
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

if "VBEAR_HOME" in os.environ:
    FAKE_HOME = Path(os.environ["HOME"])
else:
    FAKE_HOME = Path(tempfile.mkdtemp(prefix="vbear-folders-"))
    os.environ["HOME"] = str(FAKE_HOME)
    os.environ["VBEAR_HOME"] = str(FAKE_HOME / ".vbear")
os.environ["PATH"] = "/usr/bin:/bin"
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import config as cfg  # noqa: E402
from vbear import folders, server, tasks  # noqa: E402
from vbear import runtime as rt_mod  # noqa: E402
from vbear.index import Store  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


def _console(token=None):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    c = server.Console.__new__(server.Console)
    c.port = port
    c.store = Store()
    c.lock = threading.Lock()
    c.auth_token = token
    c.runtime = rt_mod.get_runtime()
    c.managed_root = FAKE_HOME
    httpd.RequestHandlerClass = server.make_handler(c)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return c, httpd, port


def _call(port, method, path, body=None, headers=None):
    h = dict(headers or {})
    data = None
    if method != "GET":
        h.setdefault("X-VBear", "1")
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, None
        finally:
            e.close()


def _inspect(port, path):
    return _call(port, "GET", "/api/folders/inspect?path=" + urllib.parse.quote(path, safe=""))


def _make_repo(path: Path, branch="main"):
    (path / ".git" / "refs" / "heads").mkdir(parents=True)
    (path / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    (path / ".git" / "refs" / "heads" / branch).write_text(SHA + "\n")


class InspectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.console, cls.httpd, cls.port = _console()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        shutil.rmtree(cfg.state_dir(), ignore_errors=True)
        cfg.ensure_state_dir()
        self.work = FAKE_HOME / "work"
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir()
        self.console.store._static = None
        self.console.store._live = None

    def test_git_repository(self):
        repo = self.work / "proj"
        _make_repo(repo)
        status, out = _inspect(self.port, str(repo))
        self.assertEqual(status, 200)
        self.assertTrue(out["ok"] and out["exists"] and out["is_dir"])
        self.assertEqual(out["name"], "proj")
        self.assertEqual(out["path"], os.path.realpath(repo))
        self.assertTrue(out["git"]["is_repo"])
        self.assertEqual(out["git"]["branch"], "main")
        self.assertEqual(out["git"]["commit"], SHA)
        self.assertEqual(out["git"]["short"], SHA[:8])
        self.assertIsNone(out["git"]["error"])
        self.assertEqual(out["git"]["root"], os.path.realpath(repo))

    def test_summary_only_no_file_contents(self):
        repo = self.work / "proj"
        _make_repo(repo)
        (repo / "secret.txt").write_text("TOP-SECRET-CONTENT")
        status, out = _inspect(self.port, str(repo))
        self.assertEqual(status, 200)
        self.assertNotIn("TOP-SECRET-CONTENT", json.dumps(out))
        self.assertEqual(set(out), {"ok", "path", "name", "exists", "is_dir", "git",
                                    "project_skill_count", "terminals", "tasks"})

    def test_detached_head_has_no_branch(self):
        repo = self.work / "proj"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text(SHA + "\n")
        status, out = _inspect(self.port, str(repo))
        self.assertEqual(status, 200)
        self.assertTrue(out["git"]["is_repo"])
        self.assertIsNone(out["git"]["branch"])
        self.assertEqual(out["git"]["short"], SHA[:8])

    def test_repository_without_commit_keeps_the_reason(self):
        repo = self.work / "proj"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        status, out = _inspect(self.port, str(repo))
        self.assertEqual(status, 200)
        self.assertTrue(out["git"]["is_repo"])
        self.assertIsNone(out["git"]["commit"])
        self.assertTrue(out["git"]["error"])

    def test_not_a_git_repository(self):
        plain = self.work / "plain"
        plain.mkdir()
        status, out = _inspect(self.port, str(plain))
        self.assertEqual(status, 200)
        self.assertTrue(out["exists"] and out["is_dir"])
        self.assertFalse(out["git"]["is_repo"])
        self.assertIsNone(out["git"]["root"])
        self.assertIsNone(out["git"]["commit"])
        self.assertIsNone(out["git"]["error"])   # "no repository" is the answer, not a fault

    def test_subfolder_of_a_repository_names_the_root(self):
        repo = self.work / "proj"
        _make_repo(repo)
        (repo / "sub").mkdir()
        status, out = _inspect(self.port, str(repo / "sub"))
        self.assertEqual(status, 200)
        self.assertTrue(out["git"]["is_repo"])
        self.assertEqual(out["git"]["root"], os.path.realpath(repo))

    def test_missing_folder_is_a_plain_answer(self):
        status, out = _inspect(self.port, str(self.work / "nope"))
        self.assertEqual(status, 200)
        self.assertFalse(out["exists"])
        self.assertNotIn("git", out)

    def test_a_file_is_not_a_folder(self):
        f = self.work / "a.txt"
        f.write_text("x")
        status, out = _inspect(self.port, str(f))
        self.assertEqual(status, 200)
        self.assertTrue(out["exists"])
        self.assertFalse(out["is_dir"])
        self.assertNotIn("git", out)

    def test_malformed_requests(self):
        for path in ("relative/dir", "~/work", "", "   ", "file://" + str(self.work), "/" + "a" * 1100,
                     str(self.work) + "\x00x"):
            status, out = _inspect(self.port, path)
            self.assertEqual(status, 400, path[:30])
            self.assertIn("error", out)
        for query in ("", "?path=", "?path=/a&path=/b", "?path=/a&x=1", "?x=1"):
            status, _ = _call(self.port, "GET", "/api/folders/inspect" + query)
            self.assertEqual(status, 400, query)

    def test_requires_login(self):
        c, httpd, port = _console(token="t" * 32)
        try:
            self.assertEqual(_inspect(port, str(self.work))[0], 401)
            status, out = _call(port, "GET", "/api/folders/inspect?path=" + urllib.parse.quote(str(self.work)),
                                headers={"Authorization": "Bearer " + "t" * 32})
            self.assertEqual(status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_post_is_not_a_route(self):
        status, _ = _call(self.port, "POST", "/api/folders/inspect", {"path": str(self.work)})
        self.assertEqual(status, 404)

    # --- places that may never be a project --------------------------------------------------

    def test_the_refused_list_is_the_designed_one(self):
        self.assertEqual(folders.SENSITIVE_HOME_DIRS,
                         (".ssh", ".gnupg", ".aws", ".config", ".vbear", ".claude", ".codex", ".gemini", "Library"))

    def test_sensitive_locations_and_home_are_refused_whether_or_not_they_exist(self):
        for name in folders.SENSITIVE_HOME_DIRS:
            real = FAKE_HOME / name
            existed = real.exists()
            if not existed:
                real.mkdir()
            try:
                answers = []
                for suffix in ("", "/sub/dir", "/does-not-exist"):
                    (real / "sub" / "dir").mkdir(parents=True, exist_ok=True)
                    status, out = _inspect(self.port, str(real) + suffix)
                    self.assertEqual(status, 403, name + suffix)
                    answers.append(out)
                    self.assertNotIn("exists", out)
                self.assertEqual(answers[0], answers[1])
                self.assertEqual(answers[0], answers[2])  # same words for a missing and an existing place
            finally:
                if not existed:
                    shutil.rmtree(real, ignore_errors=True)
            # the same name, not created at all
            gone = FAKE_HOME / name
            if not gone.exists():
                self.assertEqual(_inspect(self.port, str(gone))[0], 403, name)
        self.assertEqual(_inspect(self.port, str(FAKE_HOME))[0], 403)
        self.assertEqual(_inspect(self.port, str(FAKE_HOME) + "/")[0], 403)
        self.assertEqual(_inspect(self.port, str(FAKE_HOME) + "/work/..")[0], 403)

    def test_refusal_does_not_say_whether_the_place_exists(self):
        (FAKE_HOME / ".ssh").mkdir(exist_ok=True)
        try:
            a = _inspect(self.port, str(FAKE_HOME / ".ssh" / "id_x"))
            b = _inspect(self.port, str(FAKE_HOME / ".aws" / "id_x"))
        finally:
            shutil.rmtree(FAKE_HOME / ".ssh", ignore_errors=True)
        self.assertEqual(a[0], 403)
        self.assertEqual(b[0], 403)
        self.assertEqual(a[1]["error"], folders.REFUSED)
        self.assertEqual(b[1]["error"], folders.REFUSED)

    def test_case_variants_of_a_refused_name_are_refused(self):
        for variant in (".SSH", ".Ssh", "LIBRARY", "library"):
            self.assertEqual(_inspect(self.port, str(FAKE_HOME / variant / "x"))[0], 403, variant)

    def test_symlink_into_a_refused_place_is_refused(self):
        target = FAKE_HOME / ".ssh"
        target.mkdir(exist_ok=True)
        (target / "keys").mkdir(exist_ok=True)
        link = self.work / "innocent"
        try:
            os.symlink(target, link)
            self.assertEqual(_inspect(self.port, str(link))[0], 403)
            self.assertEqual(_inspect(self.port, str(link / "keys"))[0], 403)
            link2 = self.work / "innocent2"
            os.symlink(FAKE_HOME, link2)           # a link to the home directory itself
            self.assertEqual(_inspect(self.port, str(link2))[0], 403)
        finally:
            shutil.rmtree(target, ignore_errors=True)

    def test_symlink_to_an_ordinary_folder_is_followed(self):
        real = self.work / "real"
        _make_repo(real)
        link = self.work / "alias"
        os.symlink(real, link)
        status, out = _inspect(self.port, str(link))
        self.assertEqual(status, 200)
        self.assertEqual(out["path"], os.path.realpath(real))
        self.assertTrue(out["git"]["is_repo"])

    def test_a_refused_place_reached_through_a_relocated_link(self):
        # ~/.config pointing somewhere else (dotfile managers do this): the place it points to is refused too
        elsewhere = self.work / "dotfiles"
        (elsewhere / "app").mkdir(parents=True)
        cfgdir = FAKE_HOME / ".config"
        existed = cfgdir.exists()
        if existed:
            self.skipTest(".config exists in the test home")
        os.symlink(elsewhere, cfgdir)
        try:
            self.assertEqual(_inspect(self.port, str(cfgdir / "app"))[0], 403)
            self.assertEqual(_inspect(self.port, str(elsewhere / "app"))[0], 403)
        finally:
            os.unlink(cfgdir)

    def test_outside_the_home_directory_is_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="vbear-outside-"))
        try:
            status, out = _inspect(self.port, str(outside))
            self.assertEqual(status, 403)
            self.assertNotIn("exists", out)
            self.assertEqual(_inspect(self.port, str(FAKE_HOME.parent))[0], 403)
            self.assertEqual(_inspect(self.port, "/")[0], 403)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_a_managed_root_above_the_home_directory_keeps_both_refusals(self):
        # the QA console keeps its project next to a temporary home: the range is the root, the refusals are the home's
        root = Path(tempfile.mkdtemp(prefix="vbear-root-"))
        try:
            home = root / "home"
            (home / ".ssh").mkdir(parents=True)
            (home / "proj").mkdir()
            (root / "work").mkdir()
            ok = folders.inspect_folder(str(root / "work"), home=home, root=root)
            self.assertTrue(ok["exists"])
            self.assertTrue(folders.inspect_folder(str(home / "proj"), home=home, root=root)["exists"])
            for refused in (home, home / ".ssh", home / ".ssh" / "x", root, root / ".ssh", root / ".aws" / "k"):
                with self.assertRaises(folders.FolderError, msg=str(refused)) as cm:
                    folders.inspect_folder(str(refused), home=home, root=root)
                self.assertEqual(cm.exception.status, 403)
            with self.assertRaises(folders.FolderError) as cm:
                folders.inspect_folder(str(root.parent), home=home, root=root)
            self.assertEqual(cm.exception.status, 403)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_state_directory_elsewhere_in_home_is_refused(self):
        state = FAKE_HOME / "custom-state"
        state.mkdir(exist_ok=True)
        with mock.patch.dict(os.environ, {"VBEAR_HOME": str(state)}):
            self.assertEqual(_inspect(self.port, str(state))[0], 403)
            self.assertEqual(_inspect(self.port, str(state / "sub"))[0], 403)
        shutil.rmtree(state, ignore_errors=True)

    # --- read-only, bounded ---------------------------------------------------------------

    def test_starts_no_process_and_does_not_walk_the_tree(self):
        repo = self.work / "proj"
        _make_repo(repo)
        for i in range(30):
            (repo / f"dir{i}").mkdir()
        boom = AssertionError("not allowed in the folder summary")
        with mock.patch("subprocess.Popen", side_effect=boom), mock.patch("subprocess.run", side_effect=boom), \
                mock.patch("os.system", side_effect=boom), mock.patch("os.walk", side_effect=boom), \
                mock.patch("os.scandir", side_effect=boom), mock.patch("os.listdir", side_effect=boom), \
                mock.patch.object(Path, "iterdir", side_effect=boom), mock.patch.object(Path, "glob", side_effect=boom), \
                mock.patch.object(Path, "rglob", side_effect=boom):
            out = folders.inspect_folder(str(repo), home=FAKE_HOME)
        self.assertTrue(out["git"]["is_repo"])

    def test_the_number_of_stats_does_not_grow_with_the_folder(self):
        small, big = self.work / "small", self.work / "big"
        _make_repo(small)
        _make_repo(big)
        for i in range(300):
            (big / f"f{i}.txt").write_text("x")
            (big / f"d{i}").mkdir()

        def count(path):
            calls = []
            real_stat, real_lstat = os.stat, os.lstat

            def stat(*a, **k):
                calls.append(1)
                return real_stat(*a, **k)

            def lstat(*a, **k):
                calls.append(1)
                return real_lstat(*a, **k)
            with mock.patch("os.stat", stat), mock.patch("os.lstat", lstat):
                folders.inspect_folder(str(path), home=FAKE_HOME)
            return len(calls)
        self.assertEqual(count(small), count(big))

    def test_writes_nothing(self):
        repo = self.work / "proj"
        _make_repo(repo)
        state = cfg.state_dir()

        def snapshot():
            return sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in state.iterdir())
        before = snapshot()
        before_repo = sorted(p.name for p in repo.rglob("*"))
        with mock.patch.object(cfg, "write_private", side_effect=AssertionError("write")), \
                mock.patch.object(cfg, "save", side_effect=AssertionError("write")):
            status, _ = _inspect(self.port, str(repo))
        self.assertEqual(status, 200)
        self.assertEqual(snapshot(), before)
        self.assertEqual(sorted(p.name for p in repo.rglob("*")), before_repo)

    # --- what it reports from memory ----------------------------------------------------------

    def test_project_skill_count_comes_from_the_loaded_index_only(self):
        repo = self.work / "proj"
        _make_repo(repo)
        root = os.path.realpath(repo)
        skills = [{"skill_id": f"s{i}", "origin_package": {"project_path": root}} for i in range(3)]
        skills += [{"skill_id": "other", "origin_package": {"project_path": root + "2"}},
                   {"skill_id": "user", "origin_package": {}}, {"skill_id": "bare"}]
        self.console.store._static = {"skills": skills}
        with mock.patch.object(Store, "static", side_effect=AssertionError("must not scan or load")):
            out = _inspect(self.port, str(repo))[1]
        self.assertEqual(out["project_skill_count"], 3)
        self.console.store._static = None
        out = _inspect(self.port, str(repo))[1]
        self.assertIsNone(out["project_skill_count"])          # unknown, not zero

    def test_subfolder_counts_the_skills_of_its_repository(self):
        repo = self.work / "proj"
        _make_repo(repo)
        (repo / "pkg").mkdir()
        self.console.store._static = {"skills": [
            {"skill_id": "a", "origin_package": {"project_path": os.path.realpath(repo)}}]}
        self.assertEqual(_inspect(self.port, str(repo / "pkg"))[1]["project_skill_count"], 1)

    def test_terminals_are_counted_by_working_directory_only(self):
        repo = self.work / "proj"
        _make_repo(repo)
        real = os.path.realpath(repo)

        def sess(i, cwd, status="working", title=""):
            return {"terminal_id": f"t{i}", "tool": "claude", "status": status, "cwd": cwd, "title": title,
                    "role_label": "CEO"}
        self.console.store._live = {"sessions": [
            sess(1, real), sess(2, real + "/src", "waiting", "x" * 200), sess(3, real + "2"),
            sess(4, str(self.work)), sess(5, "", "exited"), {"terminal_id": "t6"}, "junk", sess(7, real, "exited")]}
        out = _inspect(self.port, str(repo))[1]["terminals"]
        self.assertTrue(out["known"])
        self.assertEqual(out["count"], 3)
        self.assertEqual([i["terminal_id"] for i in out["items"]], ["t1", "t2", "t7"])
        self.assertEqual([i["status"] for i in out["items"]], ["working", "waiting", "exited"])
        self.assertLessEqual(len(out["items"][1]["title"]), folders.TERMINAL_TITLE_CHARS)
        self.assertNotIn("role_label", out["items"][0])        # nothing says which role card it was
        self.console.store._live = None
        self.assertEqual(_inspect(self.port, str(repo))[1]["terminals"], {"known": False, "count": 0, "items": []})

    def test_terminal_list_is_capped(self):
        repo = self.work / "proj"
        _make_repo(repo)
        real = os.path.realpath(repo)
        self.console.store._live = {"sessions": [
            {"terminal_id": f"t{i}", "status": "working", "cwd": real} for i in range(folders.MAX_LISTED + 10)]}
        out = _inspect(self.port, str(repo))[1]["terminals"]
        self.assertEqual(out["count"], folders.MAX_LISTED + 10)
        self.assertEqual(len(out["items"]), folders.MAX_LISTED)

    def test_unfinished_task_cards_for_this_folder(self):
        repo = self.work / "proj"
        _make_repo(repo)
        real = os.path.realpath(repo)
        rows = {
            "a": {"id": "a", "title": "open one", "workdir": real, "provenance": {}},
            "b": {"id": "b", "title": "closed", "workdir": real, "provenance": {"agent": "completed"},
                  "closure": {"reason": "superseded"}},
            "c": {"id": "c", "title": "handed off", "workdir": real, "provenance": {"agent": "completed"},
                  "closure": {"reason": "handed_off_to"}},
            "d": {"id": "d", "title": "completed but not closed", "workdir": real,
                  "provenance": {"agent": "completed"}},
            "e": {"id": "e", "title": "elsewhere", "workdir": real + "2", "provenance": {}},
            "f": {"id": "f", "title": "no folder", "workdir": None, "provenance": {}},
        }
        out = folders.inspect_folder(real, home=FAKE_HOME, task_rows=rows)["tasks"]
        self.assertEqual([t["id"] for t in out["items"]], ["a", "d"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(folders.inspect_folder(real, home=FAKE_HOME)["tasks"], {"known": False, "items": []})

    def test_task_cards_through_the_api(self):
        repo = self.work / "proj"
        _make_repo(repo)
        status, made = _call(self.port, "POST", "/api/tasks", {"title": "T1", "workdir": str(repo)})
        self.assertEqual(status, 200, made)
        out = _inspect(self.port, str(repo))[1]["tasks"]
        self.assertTrue(out["known"])
        self.assertEqual([t["title"] for t in out["items"]], ["T1"])

    def test_damaged_task_store_does_not_fail_the_summary(self):
        repo = self.work / "proj"
        _make_repo(repo)
        with mock.patch.object(tasks, "load_all", side_effect=tasks.TaskStorageError("damaged")):
            status, out = _inspect(self.port, str(repo))
        self.assertEqual(status, 200)
        self.assertEqual(out["tasks"], {"known": False, "items": []})


class PageMirrorTests(unittest.TestCase):
    def test_the_page_leaves_out_the_same_places_the_server_refuses(self):
        import re
        source = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
        match = re.search(r"const FOLDER_REFUSED_HOME_DIRS = \[([^\]]*)\];", source)
        self.assertIsNotNone(match)
        listed = tuple(re.findall(r'"([^"]+)"', match.group(1)))
        self.assertEqual(listed, folders.SENSITIVE_HOME_DIRS)

    def test_the_api_is_documented(self):
        doc = (Path(__file__).resolve().parent.parent / "docs" / "SECURITY-MODEL.md").read_text(encoding="utf-8")
        self.assertIn("/api/folders/inspect", doc)
        self.assertIn("vbearPickFolder", doc)


class RecentFoldersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.console, cls.httpd, cls.port = _console()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        shutil.rmtree(cfg.state_dir(), ignore_errors=True)
        cfg.ensure_state_dir()
        self.work = FAKE_HOME / "work2"
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir()
        tpath = tasks._path()
        if tpath.exists():
            tpath.unlink()

    def _recent(self):
        return cfg.load()["recent_folders"]

    def test_defaults(self):
        self.assertEqual(cfg.DEFAULT_CONFIG["recent_folders"], [])
        self.assertIs(cfg.DEFAULT_CONFIG["onboarding_dismissed"], False)
        cfg.config_path().write_text(json.dumps({"version": 1, "port": 7799}))   # a config from before
        conf = cfg.load()
        self.assertEqual(conf["recent_folders"], [])
        self.assertIs(conf["onboarding_dismissed"], False)

    def test_both_keys_are_writable_through_the_config_api(self):
        self.assertIn("recent_folders", server.CONFIG_WRITABLE)
        self.assertIn("onboarding_dismissed", server.CONFIG_WRITABLE)
        status, out = _call(self.port, "POST", "/api/config",
                            {"recent_folders": ["/a/b", "/c"], "onboarding_dismissed": True})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["config"]["recent_folders"], ["/a/b", "/c"])
        self.assertIs(out["config"]["onboarding_dismissed"], True)
        self.assertEqual(self._recent(), ["/a/b", "/c"])

    def test_recent_folders_holds_at_most_ten(self):
        ten = [f"/p/{i}" for i in range(10)]
        self.assertEqual(_call(self.port, "POST", "/api/config", {"recent_folders": ten})[0], 200)
        self.assertEqual(_call(self.port, "POST", "/api/config", {"recent_folders": ten + ["/p/10"]})[0], 400)
        self.assertEqual(self._recent(), ten)

    def test_recent_folders_validation(self):
        bad = ["relative/path", "", 5, None, ["/a"], "/a\x00b", "/" + "a" * 1100, "~/x"]
        for item in bad:
            status, _ = _call(self.port, "POST", "/api/config", {"recent_folders": [item]})
            self.assertEqual(status, 400, repr(item)[:30])
        for whole in ("/a", {"x": 1}, 7, None):
            self.assertEqual(_call(self.port, "POST", "/api/config", {"recent_folders": whole})[0], 400)
        self.assertEqual(self._recent(), [])

    def test_recent_folders_drops_repeats(self):
        status, out = _call(self.port, "POST", "/api/config", {"recent_folders": ["/a", "/b", "/a"]})
        self.assertEqual(status, 200)
        self.assertEqual(out["config"]["recent_folders"], ["/a", "/b"])

    def test_onboarding_dismissed_must_be_a_boolean(self):
        for value in ("yes", 1, 0, None, [], {}):
            self.assertEqual(_call(self.port, "POST", "/api/config", {"onboarding_dismissed": value})[0], 400,
                             repr(value))
        self.assertIs(cfg.load()["onboarding_dismissed"], False)
        self.assertEqual(_call(self.port, "POST", "/api/config", {"onboarding_dismissed": True})[0], 200)
        self.assertEqual(_call(self.port, "POST", "/api/config", {"onboarding_dismissed": False})[0], 200)
        self.assertIs(cfg.load()["onboarding_dismissed"], False)

    def test_creating_a_task_card_remembers_its_folder_newest_first(self):
        folders_made = []
        for i in range(12):
            d = self.work / f"f{i}"
            d.mkdir()
            folders_made.append(str(d))
            status, _ = _call(self.port, "POST", "/api/tasks", {"title": f"t{i}", "workdir": str(d)})
            self.assertEqual(status, 200)
        recent = self._recent()
        self.assertEqual(len(recent), folders.MAX_RECENT_FOLDERS)
        self.assertEqual(recent, list(reversed(folders_made))[:10])
        # using an older one again moves it to the front without duplicating it
        _call(self.port, "POST", "/api/tasks", {"title": "again", "workdir": folders_made[5]})
        again = self._recent()
        self.assertEqual(again[0], folders_made[5])
        self.assertEqual(len(again), len(set(again)))

    def test_a_task_card_without_a_folder_changes_nothing(self):
        _call(self.port, "POST", "/api/config", {"recent_folders": ["/keep"]})
        self.assertEqual(_call(self.port, "POST", "/api/tasks", {"title": "no folder"})[0], 200)
        self.assertEqual(self._recent(), ["/keep"])

    def test_editing_a_task_card_does_not_remember_a_folder(self):
        d = self.work / "edit"
        d.mkdir()
        _, made = _call(self.port, "POST", "/api/tasks", {"title": "t"})
        _call(self.port, "POST", f"/api/tasks/{made['task']['id']}", {"workdir": str(d)})
        self.assertEqual(self._recent(), [])

    def test_a_corrupt_config_is_left_alone(self):
        d = self.work / "x"
        d.mkdir()
        cfg.config_path().write_text("{not json")
        before = cfg.config_path().read_bytes()
        self.console.remember_folder(str(d))
        self.assertEqual(cfg.config_path().read_bytes(), before)

    def test_remembering_never_raises(self):
        for value in (None, 5, "", "relative", "/a\x00b", ["x"]):
            self.console.remember_folder(value)
        with mock.patch.object(cfg, "save", side_effect=OSError("disk")):
            self.console.remember_folder(str(self.work))   # swallowed

    def test_launch_folder_is_remembered_once_when_the_launch_is_confirmed(self):
        c = self.console
        c.note_preview_folder("p-1", str(self.work))
        c.note_preview_folder(None, str(self.work))
        c.note_preview_folder("p-2", None)
        self.assertEqual(c.take_preview_folder("p-1"), str(self.work))
        self.assertIsNone(c.take_preview_folder("p-1"))      # only once
        self.assertIsNone(c.take_preview_folder("p-2"))
        self.assertIsNone(c.take_preview_folder(["p-1"]))

    def test_notes_for_unconfirmed_previews_are_bounded(self):
        c = self.console
        for i in range(200):
            c.note_preview_folder(f"p-{i}", "/x")
        self.assertLessEqual(len(c.__dict__["_preview_folders"]), 64)
        self.assertIsNone(c.take_preview_folder("p-0"))
        self.assertEqual(c.take_preview_folder("p-199"), "/x")

    def test_helper_functions(self):
        self.assertEqual(folders.remembered(["/a", "/b"], "/b"), ["/b", "/a"])
        self.assertEqual(folders.remembered([], "/a"), ["/a"])
        many = [f"/{i}" for i in range(10)]
        self.assertEqual(folders.remembered(many, "/new")[0], "/new")
        self.assertEqual(len(folders.remembered(many, "/new")), 10)
        self.assertEqual(folders.remembered(["/a", 5, None], "/b"), ["/b", "/a"])


if __name__ == "__main__":
    unittest.main()
