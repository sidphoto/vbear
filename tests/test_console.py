"""SID Console tests. Standard library only: python3 -m unittest discover -s tests

Every test runs against a synthetic HOME, so nothing on the real machine is
read. herdr is made unavailable on purpose to check the "unknown" paths.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ORIGINAL_PATH = os.environ.get("PATH", "")
FAKE_HOME = Path(tempfile.mkdtemp(prefix="sidconsole-test-"))
os.environ["HOME"] = str(FAKE_HOME)
os.environ["SID_CONSOLE_HOME"] = str(FAKE_HOME / ".sid-console")
os.environ["PATH"] = "/usr/bin:/bin"  # no herdr on PATH
os.environ.pop("HERDR_BIN_PATH", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def write(rel, text):
    path = FAKE_HOME / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def skill(name, desc="Does a thing.", body="", extra=""):
    return f"---\nname: {name}\ndescription: {desc}\n{extra}---\n\n# {name}\n{body}\n"


def build_fixture():
    # Claude user skills
    write(".claude/skills/alpha/SKILL.md", skill(
        "alpha", "Security review for websites.",
        "## When to use\nBefore launch.\n\n## Output\nA findings report.\n\n"
        "See [guide](references/guide.md) and [gone](references/missing.md) and `example/out.md`.\n"
        "api_key: sk-THIS-SHOULD-NOT-SHOW\n"))
    write(".claude/skills/alpha/references/guide.md", "guide text")
    write(".claude/skills/nodesc/SKILL.md", "---\nname: nodesc\n---\nbody\n")
    write(".claude/skills/.trash/old/SKILL.md", skill("old"))
    # Claude plugins: two cached versions, one installed + enabled, one disabled plugin
    cache = ".claude/plugins/cache/acme/tool"
    write(f"{cache}/1.0.0/skills/deploy/SKILL.md", skill("deploy", "Deploy apps."))
    write(f"{cache}/2.0.0/skills/deploy/SKILL.md", skill("deploy", "Deploy apps v2."))
    write(f"{cache}/2.0.0/.claude/skills/devonly/SKILL.md", skill("devonly"))
    write(f"{cache}/2.0.0/.claude-plugin/plugin.json",
          json.dumps({"name": "tool", "agents": ["./agents/helper.md"]}))
    write(f"{cache}/2.0.0/agents/helper.md", "---\nname: helper\ndescription: Helps.\n---\n")
    write(".claude/plugins/cache/other/mem/3.0.0/skills/remember/SKILL.md", skill("remember"))
    write(".claude/plugins/installed_plugins.json", json.dumps({"version": 2, "plugins": {
        "tool@acme": [{"installPath": str(FAKE_HOME / cache / "2.0.0"), "version": "2.0.0",
                       "gitCommitSha": "abc123"}],
        "mem@other": [{"installPath": str(FAKE_HOME / ".claude/plugins/cache/other/mem/3.0.0"),
                       "version": "3.0.0"}]}}))
    write(".claude/settings.json", json.dumps({"model": "opus",
          "enabledPlugins": {"tool@acme": True, "mem@other": False}}))
    write(".claude/agents/writer.md", "---\nname: Writer\ndescription: Writes.\nskills: alpha\n---\n")
    # Codex
    write(".codex/skills/alpha/SKILL.md", skill("alpha", "Codex copy of alpha."))
    write(".codex/skills/off/SKILL.md", skill("off"))
    write(".codex/skills/.system/builtin/SKILL.md", skill("builtin"))
    write(".codex/config.toml", 'model = "gpt-test"\n[skills]\nconfig = [\n'
          f'  {{ path = "{FAKE_HOME}/.codex/skills/off/SKILL.md", enabled = false }},\n]\n')
    write(".codex/agents/reviewer.toml", 'name = "Reviewer"\ndescription = "Reviews."\n'
          'developer_instructions = """\nCapabilities:\n- Review diffs.\n\nLimits:\n- No merges.\n"""\n')
    # Usage logs
    write(".claude/projects/-p/sess-1.jsonl", "\n".join(json.dumps(x) for x in [
        {"sessionId": "sess-1", "cwd": "/tmp", "timestamp": "2026-09-01T00:00:00Z",
         "message": {"role": "user", "content": "SECRET PROMPT TEXT"}},
        {"sessionId": "sess-1", "cwd": "/tmp", "timestamp": "2026-09-01T00:01:00Z",
         "message": {"model": "claude-x", "content": [
             {"type": "tool_use", "name": "Skill", "input": {"skill": "alpha"}}]}},
    ]))
    os.utime(FAKE_HOME / ".claude/projects/-p/sess-1.jsonl")
    write(".codex/sessions/2026/09/01/rollout-x-cdx-1.jsonl", "\n".join(json.dumps(x) for x in [
        {"type": "session_meta", "timestamp": "2026-09-01T00:00:00Z",
         "payload": {"id": "cdx-1", "cwd": "/tmp"}},
        {"type": "turn_context", "timestamp": "2026-09-01T00:00:01Z", "payload": {"model": "gpt-a"}},
        {"type": "response_item", "timestamp": "2026-09-01T00:00:02Z",
         "payload": {"type": "custom_tool_call", "name": "exec",
                     "input": f"cat {FAKE_HOME}/.codex/skills/alpha/SKILL.md"}},
    ]))


build_fixture()

from sidconsole import config as cfg  # noqa: E402
from sidconsole.index import Store  # noqa: E402
from sidconsole.scan import document, frontmatter, usage  # noqa: E402


class FrontMatterTests(unittest.TestCase):
    def test_nested_lists_and_block_scalars(self):
        text = ("name: x\ndescription: >\n  folded\n  text\nmeta:\n  author: a\n"
                "tags: [a, \"b, c\"]\nitems:\n  - one\n  - two\n")
        data, warnings = frontmatter.parse(text)
        self.assertEqual(warnings, [])
        self.assertEqual(data["description"], "folded text")
        self.assertEqual(data["meta"], {"author": "a"})
        self.assertEqual(data["tags"], ["a", "b, c"])
        self.assertEqual(data["items"], ["one", "two"])

    def test_missing_front_matter_is_reported(self):
        raw = document.read_skill_file(write("x/SKILL.md", "no front matter"))
        self.assertTrue(any("front matter" in w for w in raw["warnings"]))

    def test_redaction(self):
        self.assertNotIn("sk-123", document.redact("token: sk-123"))


class ScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Store().rescan()
        cls.skills = cls.data["skills"]

    def find(self, name, tool=None, version=None):
        return [s for s in self.skills if s["name"] == name
                and (tool is None or s["tool"] == tool)
                and (version is None or s["origin_package"].get("version") == version)]

    def test_trash_is_not_scanned(self):
        self.assertEqual(self.find("old"), [])

    def test_plugin_versions_and_enable_state(self):
        self.assertEqual(self.find("deploy", version="2.0.0")[0]["activation"], "active")
        old = self.find("deploy", version="1.0.0")[0]
        self.assertEqual(old["activation"], "superseded")
        self.assertIn("2.0.0", old["activation_reason"])
        self.assertEqual(self.find("remember")[0]["activation"], "disabled")
        self.assertEqual(self.find("devonly")[0]["activation"], "not_loaded")
        self.assertEqual(self.find("deploy", version="2.0.0")[0]["invoke_name"], "tool:deploy")

    def test_codex_enable_state(self):
        self.assertEqual(self.find("off", "codex")[0]["activation"], "disabled")
        self.assertEqual(self.find("builtin", "codex")[0]["scope"], "system")

    def test_same_name_different_sources_are_kept_apart(self):
        copies = self.find("alpha")
        self.assertEqual({s["tool"] for s in copies}, {"claude", "codex"})
        for s in copies:
            self.assertEqual(len(s["duplicate_of"]), 1)

    def test_provenance_is_never_invented(self):
        alpha = self.find("alpha", "claude")[0]
        self.assertEqual(alpha["description"]["origin"], "author")
        self.assertEqual(alpha["when_to_use"]["origin"], "derived")
        self.assertEqual(alpha["outputs"]["origin"], "derived")
        self.assertEqual(alpha["inputs"]["origin"], "missing")
        nodesc = self.find("nodesc")[0]
        self.assertEqual(nodesc["description"]["origin"], "missing")
        self.assertTrue(any("description" in w for w in nodesc["warnings"]))

    def test_reference_classification(self):
        refs = {r["ref"]: r["status"] for r in self.find("alpha", "claude")[0]["referenced_files"]}
        self.assertEqual(refs["references/guide.md"], "present")
        self.assertEqual(refs["references/missing.md"], "missing")
        self.assertEqual(refs["example/out.md"], "unresolved")

    def test_roles_and_links(self):
        roles = {r["name"]: r for r in self.data["roles"]}
        self.assertEqual(roles["Writer"]["skill_link_basis"], "declared")
        self.assertEqual(len(roles["Writer"]["skill_link_ids"]), 1)
        self.assertEqual(roles["Reviewer"]["capabilities"]["origin"], "author")
        self.assertEqual(roles["Reviewer"]["model"]["origin"], "derived")
        self.assertEqual(roles["Reviewer"]["skill_link_basis"], "undeclared")
        self.assertIn("tool:helper", roles)
        cli = roles["Claude Code 主代理"]
        active_claude = {s["skill_id"] for s in self.skills
                         if s["tool"] == "claude" and s["activation"] == "active"}
        self.assertEqual(set(cli["skill_link_ids"]), active_claude)


class IndexCacheTests(unittest.TestCase):
    def test_old_index_format_triggers_rescan(self):
        cfg.index_path().parent.mkdir(parents=True, exist_ok=True)
        cfg.index_path().write_text(json.dumps({"skills": [], "roles": []}), encoding="utf-8")
        data = Store().static()
        self.assertTrue(data["skills"])
        self.assertEqual(data["index_version"], 1)


class UsageTests(unittest.TestCase):
    def test_usage_extracts_identifiers_only(self):
        result = usage.collect(3650)
        by_id = {s["session_id"]: s for s in result["sessions"]}
        self.assertEqual(by_id["sess-1"]["models"], {"claude-x": 1})
        self.assertEqual(by_id["sess-1"]["skills"]["name:alpha"]["evidence"], "explicit")
        self.assertEqual(by_id["cdx-1"]["models"], {"gpt-a": 1})
        self.assertIn(f"path:{FAKE_HOME}/.codex/skills/alpha/SKILL.md", by_id["cdx-1"]["skills"])
        cache = (FAKE_HOME / ".sid-console" / "usage-cache.json").read_text()
        self.assertNotIn("SECRET PROMPT TEXT", cache)
        self.assertNotIn("SECRET PROMPT TEXT", json.dumps(result))

    def test_herdr_unavailable_is_reported_not_guessed(self):
        live = Store().live(force=True)
        self.assertFalse(live["herdr"]["available"])
        self.assertEqual(live["sessions"], [])
        self.assertTrue(live["herdr"]["problems"])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from sidconsole.server import Console, make_handler
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = cls.httpd.server_address[1]
        cls.console = Console(port)
        cls.httpd.RequestHandlerClass = make_handler(cls.console)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, method="GET", headers=None, body=None):
        r = urllib.request.Request(self.base + path, method=method, headers=headers or {},
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"null"), resp.headers
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None, e.headers

    def test_stale_index_is_flagged(self):
        self.assertFalse(self.req("/api/overview")[1]["stale"])
        self.console.store.static()["generated_at"] -= 2 * 86400
        self.assertTrue(self.req("/api/overview")[1]["stale"])
        self.req("/api/rescan", "POST", body={}, headers={"X-SID-Console": "1"})
        self.assertFalse(self.req("/api/overview")[1]["stale"])

    def test_annotations_never_touch_skill_files(self):
        import hashlib
        def snapshot():
            out = {}
            for root in (".claude", ".codex", ".agents"):
                for p in (FAKE_HOME / root).rglob("*"):
                    if p.is_file():
                        out[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            return out
        before = snapshot()
        _, data, _ = self.req("/api/skills")
        claude_alpha = next(s for s in data["skills"] if s["name"] == "alpha" and s["tool"] == "claude")
        codex_alpha = next(s for s in data["skills"] if s["name"] == "alpha" and s["tool"] == "codex")
        self.assertNotEqual(claude_alpha["annotation_key"], codex_alpha["annotation_key"])
        hdr = {"X-SID-Console": "1"}
        status, saved, _ = self.req("/api/annotations", "POST", headers=hdr, body={
            "key": claude_alpha["annotation_key"], "aliases": "網站健檢，資安", "tags": ["上線前"] * 3 + ["x" * 99],
            "note": "n" * 5000})
        self.assertEqual(status, 200)
        a = saved["annotation"]
        self.assertEqual(a["aliases"], ["網站健檢", "資安"])
        self.assertEqual(a["tags"], ["上線前", "x" * 60])
        self.assertEqual(len(a["note"]), 2000)
        _, data, _ = self.req("/api/skills")
        by_id = {s["skill_id"]: s for s in data["skills"]}
        self.assertEqual(by_id[claude_alpha["skill_id"]]["annotation"]["aliases"][0], "網站健檢")
        self.assertIsNone(by_id[codex_alpha["skill_id"]]["annotation"])
        _, detail, _ = self.req(f"/api/skills/{claude_alpha['skill_id']}")
        self.assertEqual(detail["annotation"]["tags"], ["上線前", "x" * 60])
        # empty annotation clears it
        self.req("/api/annotations", "POST", headers=hdr, body={"key": claude_alpha["annotation_key"]})
        _, detail, _ = self.req(f"/api/skills/{claude_alpha['skill_id']}")
        self.assertIsNone(detail["annotation"])
        self.assertEqual(self.req("/api/annotations", "POST", headers=hdr, body={"key": "bad"})[0], 400)
        self.assertEqual(self.req("/api/annotations", "POST", body={"key": "claude:alpha", "tags": "x"})[0], 403)
        self.assertEqual(before, snapshot())

    def test_bad_host_rejected(self):
        self.assertEqual(self.req("/api/skills", headers={"Host": "evil.example"})[0], 421)

    def test_post_requires_header_and_same_origin(self):
        self.assertEqual(self.req("/api/rescan", "POST", body={})[0], 403)
        self.assertEqual(self.req("/api/rescan", "POST", body={},
                                  headers={"X-SID-Console": "1", "Origin": "https://evil"})[0], 403)
        self.assertEqual(self.req("/api/rescan", "POST", body={}, headers={"X-SID-Console": "1"})[0], 200)

    def test_detail_redacts_and_restricts_files(self):
        _, data, headers = self.req("/api/skills")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        alpha = next(s for s in data["skills"] if s["name"] == "alpha" and s["tool"] == "claude")
        _, detail, _ = self.req(f"/api/skills/{alpha['skill_id']}")
        self.assertNotIn("sk-THIS-SHOULD-NOT-SHOW", detail["raw"])
        self.assertEqual(detail["usage"][0]["evidence"], "explicit")
        ok = self.req(f"/api/skills/{alpha['skill_id']}/file?ref=references/guide.md")
        self.assertEqual(ok[1]["text"], "guide text")
        for ref in ("../../../../etc/passwd", "references/missing.md", "SKILL.md"):
            self.assertEqual(self.req(f"/api/skills/{alpha['skill_id']}/file?ref={ref}")[0], 403)

    def test_focus_validates_target(self):
        status, _, _ = self.req("/api/focus", "POST", body={"target": "w1:p1; rm -rf /"},
                                headers={"X-SID-Console": "1"})
        self.assertEqual(status, 400)

    def test_config_only_accepts_known_keys(self):
        _, data, _ = self.req("/api/config", "POST", headers={"X-SID-Console": "1"},
                              body={"usage_days": 9999, "host": "0.0.0.0", "port": 1})
        self.assertEqual(data["config"]["usage_days"], 365)
        self.assertEqual(data["config"]["host"], cfg.DEFAULT_HOST)
        self.assertEqual(data["config"]["port"], cfg.DEFAULT_PORT)

    def test_role_skills_paging_and_debounce(self):
        """Runs tests/frontend/role_skills.cjs: the real viewRole() against a
        synthetic DOM and clock (behaviour, not a browser test)."""
        import subprocess
        node = shutil.which("node", path=os.environ.get("SID_TEST_NODE_PATH", ORIGINAL_PATH))
        if not node:
            self.skipTest("node is not installed")
        script = Path(__file__).resolve().parent / "frontend" / "role_skills.cjs"
        proc = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok IME composition Enter ignored", proc.stdout)

    def test_invalid_content_length_returns_400(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.console.port)
        conn.putrequest("POST", "/api/focus")
        conn.putheader("Host", f"127.0.0.1:{self.console.port}")
        conn.putheader("X-SID-Console", "1")
        conn.putheader("Content-Length", "invalid")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_stalled_client_is_dropped(self):
        """A client that stops mid-headers is disconnected by the socket
        timeout, and the server keeps answering others meanwhile."""
        import socket
        import time
        handler = self.httpd.RequestHandlerClass
        self.assertEqual(handler.timeout, 15.0)
        handler.timeout = 0.5  # same mechanism, shorter wait for the test
        try:
            conn = socket.create_connection(("127.0.0.1", self.console.port), timeout=5)
            conn.sendall(b"GET /api/config HTTP/1.1\r\nHost: 127.0.0.1\r\n")  # never finished
            self.assertEqual(self.req("/api/config")[0], 200)
            started = time.monotonic()
            self.assertEqual(conn.recv(1024), b"")  # closed by the server
            self.assertLess(time.monotonic() - started, 4)
            conn.close()
        finally:
            handler.timeout = 15.0

    def test_launch_identifies_sid_console(self):
        """launch() decides through is_sid_console(); test that function."""
        import http.server
        from sidconsole.__main__ import is_sid_console

        def fake(server_name, body):
            class FakeHandler(http.server.BaseHTTPRequestHandler):
                server_version = server_name
                sys_version = ""
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                def log_message(self, *a): pass
            srv = http.server.HTTPServer(("127.0.0.1", 0), FakeHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            return f"http://127.0.0.1:{srv.server_address[1]}/"

        good_shape = b'{"config": {}, "state_dir": "/x"}'
        self.assertTrue(is_sid_console(self.base + "/"))
        self.assertFalse(is_sid_console(fake("SIDConsole/0.1", b'{"unrelated": true}')))
        self.assertFalse(is_sid_console(fake("nginx", good_shape)))  # right shape, other server
        self.assertFalse(is_sid_console(fake("SIDConsole/0.1", b'{"config": [], "state_dir": 1}')))
        self.assertFalse(is_sid_console(fake("SIDConsole/0.1", b"not json")))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertFalse(is_sid_console(self.base + "/"))

    def test_corrupt_config_prevents_overwrite_and_backs_up(self):
        cpath = cfg.config_path()
        bakpath = cpath.with_suffix(".json.bak")
        original = cpath.read_text(encoding="utf-8")
        try:
            cpath.write_text("{broken json", encoding="utf-8")
            self.assertTrue(cfg.is_corrupt())
            loaded = cfg.load()
            self.assertTrue(loaded.get("_corrupt"))
            self.assertTrue(bakpath.exists())
            with self.assertRaises(ValueError):
                cfg.save(loaded)
            # POST /api/config should return 400
            status, _, _ = self.req("/api/config", "POST", headers={"X-SID-Console": "1"}, body={"usage_days": 30})
            self.assertEqual(status, 400)
            self.assertEqual(cpath.read_text(encoding="utf-8"), "{broken json")
        finally:
            cpath.write_text(original, encoding="utf-8")
            bakpath.unlink(missing_ok=True)

    def test_server_reloads_index_when_disk_mtime_changes(self):
        self.console.store.static()
        idx_path = cfg.index_path()
        original = idx_path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            data["skills"].append({"name": "cli-added-skill", "skill_id": "test:cli-added", "tool": "claude"})
            idx_path.write_text(json.dumps(data), encoding="utf-8")
            reloaded = self.console.store.static()
            self.assertTrue(any(s.get("name") == "cli-added-skill" for s in reloaded.get("skills", [])))
        finally:
            idx_path.write_text(original, encoding="utf-8")
            self.console.store.static()



# --- hardening (T5 review M1-M3, L1-L5) -------------------------------------
#
# Hostile inputs live under FAKE_HOME/hostile, outside every default source,
# and are scanned through an explicit Source so the tests above are unaffected.

from unittest import mock  # noqa: E402

from sidconsole import annotations  # noqa: E402
from sidconsole.bridge import herdr  # noqa: E402
from sidconsole.index import build_static  # noqa: E402
from sidconsole.scan import claude  # noqa: E402

HOSTILE = FAKE_HOME / "hostile"
SECRETS = ("sk-live-FRONTMATTER", "CAMELSECRET", "ACCESSSECRET", "NESTEDSECRET", "JSONSECRET",
           "BEARERSECRET", "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV", "ghp_ABCDEFGHIJKLMNOPQRSTUVWX12",
           "AKIAABCDEFGHIJKLMNOP", "xoxb-123456789012-abcdef", "MIIEPEMBODY", "hunter2",
           "OUTSIDE-SECRET")


def deep_dashes(levels: int) -> str:
    return "a:\n" + "".join(" " * i + "-\n" for i in range(1, levels + 1))


def build_hostile_fixture():
    skills = HOSTILE / "skills"
    (skills / "good").mkdir(parents=True, exist_ok=True)
    (skills / "good" / "SKILL.md").write_text(skill("good", "A normal skill."), encoding="utf-8")
    # M1: nesting deep enough to exhaust Python's recursion limit
    (skills / "deep").mkdir(exist_ok=True)
    (skills / "deep" / "SKILL.md").write_text("---\n" + deep_dashes(1100) + "---\nbody\n",
                                              encoding="utf-8")
    # M2: secrets in front matter, body and a referenced file
    (skills / "evil" / "refs").mkdir(parents=True, exist_ok=True)
    (skills / "evil" / "SKILL.md").write_text(
        "---\nname: evil\ndescription: Evil skill.\nauthor: Jane Doe\n"
        "api_key: sk-live-FRONTMATTER\napiKey: CAMELSECRET\naccess_token: ACCESSSECRET\n"
        "env:\n  API_TOKEN: NESTEDSECRET\n---\n# Evil\nSee [data](refs/data.txt).\n"
        '"api_key": "JSONSECRET",\nAuthorization: Bearer BEARERSECRET\n'
        "Use sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV or ghp_ABCDEFGHIJKLMNOPQRSTUVWX12.\n"
        "AWS AKIAABCDEFGHIJKLMNOP slack xoxb-123456789012-abcdef\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEPEMBODY\n-----END RSA PRIVATE KEY-----\n"
        "## Setup password=hunter2\n", encoding="utf-8")
    (skills / "evil" / "refs" / "data.txt").write_text(
        "password = hunter2\n-----BEGIN PRIVATE KEY-----\nMIIEPEMBODY\n-----END PRIVATE KEY-----\n",
        encoding="utf-8")
    # M3: SKILL.md symlinked to a file outside the source root
    (HOSTILE / "outside").mkdir(exist_ok=True)
    (HOSTILE / "outside" / "secret.txt").write_text(
        "---\nname: leaked\ndescription: OUTSIDE-SECRET\n---\nOUTSIDE-SECRET\n", encoding="utf-8")
    (skills / "linked").mkdir(exist_ok=True)
    link = skills / "linked" / "SKILL.md"
    if not link.is_symlink():
        link.symlink_to(HOSTILE / "outside" / "secret.txt")
    # legal: a SKILL.md symlinked to another file inside the same root
    (skills / "inside").mkdir(exist_ok=True)
    inner = skills / "inside" / "SKILL.md"
    if not inner.is_symlink():
        inner.symlink_to(skills / "good" / "SKILL.md")
    # L1: oversized file
    (skills / "huge").mkdir(exist_ok=True)
    (skills / "huge" / "SKILL.md").write_text(
        skill("huge", "HUGE-DESCRIPTION") + "x" * (300 * 1024), encoding="utf-8")
    # legal: a source root that is itself a symlink (like a linked plugin cache)
    real_root = HOSTILE / "real-root" / "linkedroot"
    real_root.mkdir(parents=True, exist_ok=True)
    (real_root / "SKILL.md").write_text(skill("linkedroot", "Through a symlinked root."),
                                        encoding="utf-8")
    alias = HOSTILE / "alias-root"
    if not alias.is_symlink():
        alias.symlink_to(HOSTILE / "real-root")


def hostile_source(path) -> cfg.Source:
    return cfg.Source("hostile", "claude", "skills", "user", str(path), label="hostile")


def hostile_conf(path=None) -> dict:
    conf = cfg.load()
    conf["sources"] = [vars(hostile_source(path or HOSTILE / "skills"))]
    conf["project_roots"] = []
    return conf


class _HostileBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_hostile_fixture()

    def scan(self, path=None):
        return {r.name: r for r in claude.scan_skills(
            hostile_source(path or HOSTILE / "skills"), claude.load_activation_facts())}


class DepthLimitTests(_HostileBase):  # M1
    def test_deep_block_nesting_is_bounded(self):
        data, warnings = frontmatter.parse(deep_dashes(3000))
        self.assertIn("a", data)
        self.assertTrue(any("巢狀" in w for w in warnings))

    def test_deep_inline_nesting_is_bounded(self):
        data, warnings = frontmatter.parse("x: " + "[" * 3000 + "]" * 3000)
        self.assertTrue(any("巢狀" in w for w in warnings))

    def test_one_bad_skill_does_not_stop_the_scan(self):
        real_parse = frontmatter.parse

        def exploding(text):
            if "name: good" in text:
                raise RuntimeError("boom")
            return real_parse(text)

        with mock.patch.object(frontmatter, "parse", exploding):
            recs = self.scan()
        self.assertIn("evil", recs)
        self.assertTrue(any("RuntimeError" in w for w in recs["good"].warnings))
        data = build_static(hostile_conf())  # the deep file is scanned for real here
        self.assertIn("good", {s["name"] for s in data["skills"]})
        deep = next(s for s in data["skills"] if s["name"] == "deep")
        self.assertTrue(deep["warnings"])

    def test_role_file_with_deep_nesting_is_skipped_not_fatal(self):
        agents = HOSTILE / "agents"
        agents.mkdir(exist_ok=True)
        (agents / "deep.md").write_text("---\n" + deep_dashes(300) + "---\n", encoding="utf-8")
        (agents / "ok.md").write_text("---\nname: ok\ndescription: fine\n---\n", encoding="utf-8")
        src = cfg.Source("ha", "claude", "agents", "user", str(agents))
        names = {r.name for r in claude.scan_agents(src)}
        self.assertIn("ok", names)


class SizeAndSpeedTests(_HostileBase):  # L1
    def test_oversized_skill_is_not_parsed(self):
        rec = self.scan()["huge"]
        self.assertTrue(any("256KB" in w for w in rec.warnings))
        self.assertNotIn("HUGE-DESCRIPTION", json.dumps(rec.to_json()))

    def test_many_list_items_parse_in_linear_time(self):
        import time
        text = "items:\n" + "".join(f"  - key{i}: v\n    other: x\n" for i in range(40000))
        started = time.time()
        data, warnings = frontmatter.parse(text)
        self.assertEqual(len(data["items"]), 40000)
        self.assertEqual(data["items"][7], {"key7": "v", "other": "x"})
        self.assertLess(time.time() - started, 3.0)


class RedactionTests(_HostileBase):  # M2
    def test_front_matter_secret_keys_are_masked(self):
        rec = self.scan()["evil"]
        text = json.dumps(rec.to_json(), ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertEqual(rec.frontmatter["author"], "Jane Doe")
        self.assertEqual(rec.frontmatter["api_key"], document.REDACTED)
        self.assertEqual(rec.frontmatter["apiKey"], document.REDACTED)

    def test_patterns(self):
        cases = {
            '"api_key": "JSONSECRET", "x": 1': "JSONSECRET",
            "Authorization: Bearer BEARERSECRET": "BEARERSECRET",
            "curl -H 'Authorization: Bearer abc.def-123'": "abc.def-123",
            "export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx": "sk-proj",
            "token sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV end": "sk-ant-api03",
            "use sk-abcdefghijklmnopqrstuvwxyz0123 now": "sk-abcdefghij",
            "gho_ABCDEFGHIJKLMNOPQRSTUVWX12 / github_pat_11ABCDEFGHIJKLMNOPQRSTUV": "_ABCDEFGHIJ",
            "key AKIAABCDEFGHIJKLMNOP": "AKIAABCDEFGHIJKLMNOP",
            "xoxp-123456789012-abc": "xoxp-1234",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\nBBBB\n-----END OPENSSH PRIVATE KEY-----": "BBBB",
            "client_secret: |\n  multi\n  line\nnext: ok": "multi",
        }
        for text, secret in cases.items():
            self.assertNotIn(secret, document.redact(text), text)

    def test_prose_is_left_alone(self):
        for text in ("author: Jane Doe", "bearer authentication is used", "pip install sk-learn",
                     "keywords: a, b", "url: https://example.com/token", "The key: fast"):
            self.assertEqual(document.redact(text), text)


class SymlinkTests(_HostileBase):  # M3
    def test_skill_md_symlinked_outside_root_is_not_read(self):
        recs = self.scan()
        rec = recs["linked"]
        self.assertNotIn("leaked", recs)
        self.assertTrue(any("符號連結" in w for w in rec.warnings))
        self.assertNotIn("OUTSIDE-SECRET", json.dumps(recs["linked"].to_json()))
        self.assertNotIn("OUTSIDE-SECRET", json.dumps(build_static(hostile_conf())))

    def test_symlinks_inside_the_root_still_work(self):
        recs = self.scan()
        self.assertEqual(recs["good"].description.value, "A normal skill.")
        inside = [r for r in recs.values() if r.path.endswith("inside/SKILL.md")]
        self.assertEqual(inside[0].description.value, "A normal skill.")
        through = self.scan(HOSTILE / "alias-root")
        self.assertEqual(through["linkedroot"].description.value, "Through a symlinked root.")


class TargetTests(unittest.TestCase):  # L2
    def test_target_shape(self):
        for bad in ("p1\n", "-h", "--help", "", "a b", "x" * 65, "w1:p1;rm"):
            self.assertEqual(herdr.focus(bad)["error"], "無效的目標識別碼", repr(bad))
        for good in ("p1", "w1:p1", "t_2-3"):
            self.assertNotEqual(herdr.focus(good).get("error"), "無效的目標識別碼")


class HardenedServerTests(_HostileBase):  # M2/M3 read path, L2, L3, L4
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from http.server import ThreadingHTTPServer
        from sidconsole.server import Console, make_handler
        cls.herdr_log = HOSTILE / "herdr-argv.log"
        fake = HOSTILE / "bin" / "herdr"
        fake.parent.mkdir(exist_ok=True)
        fake.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> "{cls.herdr_log}"\n'
            'case "$1 $2" in\n'
            ' "agent list") echo \'{"result":{"agents":[{"terminal_id":"t1","pane_id":"p1",'
            '"agent":"claude","agent_status":"working","cwd":"/tmp"}]}}\';;\n'
            ' "workspace list") echo \'{"result":{"workspaces":[]}}\';;\n'
            ' "tab list") echo \'{"result":{"tabs":[]}}\';;\n'
            ' "agent focus") echo \'{"result":{"ok":true}}\';;\n'
            " *) echo '{}';;\nesac\n", encoding="utf-8")
        fake.chmod(0o755)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = cls.httpd.server_address[1]
        cls.console = Console(port)
        cls.conf = hostile_conf()
        cls.conf["herdr_bin"] = str(fake)
        cls.console.store._static = build_static(cls.conf)
        cls.httpd.RequestHandlerClass = make_handler(cls.console)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    req = ServerTests.req
    H = {"X-SID-Console": "1"}

    def setUp(self):
        # a config POST replaces store.conf with the saved file; restore ours
        self.console.store.conf = json.loads(json.dumps(self.conf))
        self.console.store._live = None

    def skill_id(self, name):
        return next(s["skill_id"] for s in self.console.store.static()["skills"] if s["name"] == name)

    def test_api_output_has_no_secrets(self):
        for path in ("/api/skills", f"/api/skills/{self.skill_id('evil')}",
                     f"/api/skills/{self.skill_id('evil')}/file?ref=refs/data.txt",
                     f"/api/skills/{self.skill_id('linked')}"):
            status, data, _ = self.req(path)
            self.assertEqual(status, 200, path)
            text = json.dumps(data, ensure_ascii=False)
            for secret in SECRETS:
                self.assertNotIn(secret, text, path)
        _, detail, _ = self.req(f"/api/skills/{self.skill_id('evil')}")
        self.assertIn("Evil skill.", detail["raw"])

    def test_detail_rechecks_symlink_at_read_time(self):
        victim = HOSTILE / "skills" / "flip"
        victim.mkdir(exist_ok=True)
        (victim / "SKILL.md").write_text(skill("flip"), encoding="utf-8")
        self.console.store._static = build_static(self.console.store.conf)
        (victim / "SKILL.md").unlink()
        (victim / "SKILL.md").symlink_to(HOSTILE / "outside" / "secret.txt")
        try:
            _, detail, _ = self.req(f"/api/skills/{self.skill_id('flip')}")
            self.assertEqual(detail["raw"], "")
            self.assertIn("符號連結", detail["raw_error"])
        finally:
            (victim / "SKILL.md").unlink()
            shutil.rmtree(victim)
            self.console.store._static = build_static(self.console.store.conf)

    def test_focus_only_accepts_live_panes(self):
        self.herdr_log.write_text("", encoding="utf-8")
        status, data, _ = self.req("/api/focus", "POST", headers=self.H, body={"target": "p1"})
        self.assertEqual((status, data["ok"]), (200, True))
        for bad in ("p2", "--help", "p1\n", ["p1"]):
            status, _, _ = self.req("/api/focus", "POST", headers=self.H, body={"target": bad})
            self.assertEqual(status, 400, repr(bad))
        calls = self.herdr_log.read_text(encoding="utf-8")
        self.assertIn("agent focus p1", calls)
        self.assertNotIn("p2", calls)
        self.assertNotIn("--help", calls)

    def test_cross_site_reads_are_refused(self):
        for site in ("cross-site", "same-site"):
            for path in ("/api/skills", "/api/config", "/api/live?force=1"):
                self.assertEqual(self.req(path, headers={"Sec-Fetch-Site": site})[0], 403, (site, path))
        for site in ("same-origin", "none"):
            self.assertEqual(self.req("/api/skills", headers={"Sec-Fetch-Site": site})[0], 200)
        page = urllib.request.Request(self.base + "/", headers={"Sec-Fetch-Site": "cross-site"})
        with urllib.request.urlopen(page) as resp:  # opening the page itself stays allowed
            self.assertEqual(resp.status, 200)
        self.assertEqual(self.req("/api/config")[0], 200)  # launcher health check: no header

    def test_forced_live_refresh_needs_header(self):
        self.herdr_log.write_text("", encoding="utf-8")
        self.assertEqual(self.req("/api/live?force=1")[0], 403)
        self.assertEqual(self.herdr_log.read_text(encoding="utf-8"), "")
        self.assertEqual(self.req("/api/live?force=1", headers=dict(self.H, **{
            "Sec-Fetch-Site": "same-origin"}))[0], 200)
        self.assertEqual(self.req("/api/live")[0], 200)

    def test_config_input_validation(self):
        home = str(FAKE_HOME)
        for body in ({"language": "xx"}, {"language": {"x": [1]}}, {"project_roots": ["/"]},
                     {"project_roots": [home]}, {"project_roots": ["~"]},
                     {"project_roots": [str(FAKE_HOME.parent)]}, {"project_roots": ["relative/dir"]},
                     {"project_roots": "/tmp"}, {"project_roots": [1]},
                     {"project_roots": ["/tmp"] * 21}):
            status, _, _ = self.req("/api/config", "POST", headers=self.H, body=body)
            self.assertEqual(status, 400, body)
        conf = json.loads(cfg.config_path().read_text(encoding="utf-8"))
        self.assertEqual(conf["language"], "zh-TW")
        status, data, _ = self.req("/api/config", "POST", headers=self.H,
                                   body={"project_roots": ["~/projects", f"{home}/work"],
                                         "language": "zh-TW"})
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["project_roots"], ["~/projects", f"{home}/work"])

    def test_annotation_keys_must_exist(self):
        status, _, _ = self.req("/api/annotations", "POST", headers=self.H,
                                body={"key": "claude:no-such-skill", "note": "x"})
        self.assertEqual(status, 400)
        status, _, _ = self.req("/api/annotations", "POST", headers=self.H,
                                body={"key": "claude:good", "note": "fine"})
        self.assertEqual(status, 200)
        self.req("/api/annotations", "POST", headers=self.H, body={"key": "claude:good"})

    def test_annotation_total_is_capped(self):
        filler = {f"claude:s{i}": {"note": "n"} for i in range(annotations.MAX_ENTRIES)}
        cfg.write_private(cfg.state_dir() / "annotations.json", json.dumps(filler))
        try:
            with self.assertRaises(ValueError):
                annotations.save("claude:good", {"note": "one too many"})
            annotations.save("claude:s0", {"note": "update in place is fine"})
        finally:
            (cfg.state_dir() / "annotations.json").unlink()


class StatePermissionTests(unittest.TestCase):  # L5
    def test_state_dir_and_files_are_owner_only(self):
        import stat
        state = cfg.state_dir()
        state.mkdir(parents=True, exist_ok=True)
        os.chmod(state, 0o755)
        loose = state / "server.log"
        loose.write_text("old log", encoding="utf-8")
        os.chmod(loose, 0o644)
        Store().rescan()
        cfg.save(cfg.load())
        usage.collect(3650)
        annotations.save("claude:alpha", {"note": "perm"})
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
        for name in ("config.json", "index.json", "usage-cache.json", "annotations.json", "server.log"):
            self.assertEqual(stat.S_IMODE((state / name).stat().st_mode), 0o600, name)
        annotations.save("claude:alpha", {})
        with cfg.open_private_log(state / "fresh.log") as out:
            out.write(b"x")
        self.assertEqual(stat.S_IMODE((state / "fresh.log").stat().st_mode), 0o600)

    def test_temp_names_are_unique(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(str(src))
            return real_replace(src, dst)

        with mock.patch("os.replace", spy):
            cfg.write_private(cfg.state_dir() / "t.json", "1")
            cfg.write_private(cfg.state_dir() / "t.json", "2")
        self.assertEqual(len(set(seen)), 2)
        self.assertEqual((cfg.state_dir() / "t.json").read_text(), "2")
        self.assertEqual(list(cfg.state_dir().glob("*.tmp")), [])
        (cfg.state_dir() / "t.json").unlink()


class SlowHerdrTests(_HostileBase):  # AGY A1: a hung herdr must not stall the console
    DELAY = 1.0  # seconds each fake herdr subcommand takes

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import time
        from http.server import ThreadingHTTPServer
        from sidconsole.server import Console, make_handler
        cls.time = time
        cls.log = HOSTILE / "slow-herdr.log"
        fake = HOSTILE / "bin" / "slow-herdr"
        fake.parent.mkdir(exist_ok=True)
        fake.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> "{cls.log}"\n'
            f"sleep {cls.DELAY}\n"
            'case "$1 $2" in\n'
            ' "agent list") echo \'{"result":{"agents":[{"terminal_id":"t1","pane_id":"p1",'
            '"agent":"claude","agent_status":"working","cwd":"/tmp"}]}}\';;\n'
            ' "workspace list") echo \'{"result":{"workspaces":[]}}\';;\n'
            ' "tab list") echo \'{"result":{"tabs":[]}}\';;\n'
            ' "--version ") echo herdr-slow;;\n'
            " *) echo '{}';;\nesac\n", encoding="utf-8")
        fake.chmod(0o755)
        cls.fake = str(fake)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = cls.httpd.server_address[1]
        cls.console = Console(port)
        cls.httpd.RequestHandlerClass = make_handler(cls.console)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    req = ServerTests.req

    def setUp(self):
        conf = hostile_conf()
        conf["herdr_bin"] = self.fake
        conf["usage_enabled"] = False
        self.store = self.console.store
        self.store.conf = conf
        self.store._static = build_static(conf)
        self.store._live = None
        self.log.write_text("", encoding="utf-8")

    def rounds(self):
        return self.log.read_text(encoding="utf-8").count("agent list")

    def timed(self, fn):
        start = self.time.monotonic()
        result = fn()
        return result, self.time.monotonic() - start

    def in_background(self, fn, n=1):
        threads = [threading.Thread(target=fn, daemon=True) for _ in range(n)]
        for t in threads:
            t.start()
        return threads

    def test_skill_library_answers_while_herdr_is_slow(self):
        threads = self.in_background(lambda: self.store.live(force=True))
        self.time.sleep(0.3)  # the live build is now inside herdr
        _, took = self.timed(self.store.static)
        self.assertLess(took, 0.5)
        (status, data, _), took = self.timed(lambda: self.req("/api/skills"))
        self.assertEqual(status, 200)
        self.assertTrue(data["skills"])
        self.assertLess(took, 1.0)
        for t in threads:
            t.join(10)

    def test_snapshot_calls_run_in_parallel(self):
        snap, took = self.timed(lambda: herdr.snapshot(self.fake))
        self.assertTrue(snap["available"])
        self.assertEqual(snap["version"], "herdr-slow")
        self.assertEqual(len(snap["agents"]), 1)
        self.assertLess(took, 2 * self.DELAY)  # serial would be 4 x DELAY
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(calls), ["--version", "agent list", "tab list", "workspace list"])

    def test_concurrent_live_requests_share_one_herdr_round(self):
        results = []
        _, took = self.timed(lambda: [t.join(10) for t in self.in_background(
            lambda: results.append(self.store.live()), n=6)])
        self.assertEqual(len(results), 6)
        self.assertEqual(self.rounds(), 1)
        self.assertLess(took, 2 * self.DELAY)
        self.assertTrue(all(r is results[0] for r in results))

    def test_stale_view_is_served_while_one_refresh_runs(self):
        self.store.live()
        self.store._live_at -= 60  # expire the cache
        self.log.write_text("", encoding="utf-8")
        builder = self.in_background(self.store.live)
        self.time.sleep(0.3)
        results = []
        _, took = self.timed(lambda: [t.join(10) for t in self.in_background(
            lambda: results.append(self.store.live()), n=5)])
        self.assertLess(took, 0.5)
        self.assertEqual(len(results), 5)
        for t in builder:
            t.join(10)
        self.assertEqual(self.rounds(), 1)

    def test_forced_refresh_uses_a_snapshot_taken_after_the_request(self):
        self.store.live()
        self.log.write_text("", encoding="utf-8")
        results = []
        threads = self.in_background(lambda: results.append(self.store.live(force=True)), n=4)
        for t in threads:
            t.join(15)
        self.assertEqual(len(results), 4)
        self.assertLessEqual(self.rounds(), 2)  # never one round per request
        self.assertGreaterEqual(self.rounds(), 1)

    def test_skill_detail_does_not_wait_for_herdr_when_a_view_exists(self):
        self.store.live()
        self.store._live_at -= 60
        self.log.write_text("", encoding="utf-8")
        sid = next(s["skill_id"] for s in self.store.static()["skills"] if s["name"] == "good")
        (status, _, _), took = self.timed(lambda: self.req(f"/api/skills/{sid}"))
        self.assertEqual(status, 200)
        self.assertLess(took, 0.5)
        self.time.sleep(2 * self.DELAY + 0.5)  # let the background refresh finish
        self.assertEqual(self.rounds(), 1)


# --- review fixes R1-R4 (.local/reviews/20260919-180318-summary.md) ----------
#
# Each test gets its own state directory, so the index and config written here
# never meet the ones the tests above rely on. Races are forced with Events,
# never with sleeps, and every thread is joined with a timeout.

import stat  # noqa: E402

from sidconsole import index as index_mod  # noqa: E402


def marker_index(marker: str) -> dict:
    return {"index_version": index_mod.INDEX_VERSION, "generated_at": 0, "scan_seconds": 0,
            "marker": marker, "skills": [], "roles": [], "sources": [], "problems": []}


def post_json(base: str, path: str, body: dict):
    r = urllib.request.Request(base + path, method="POST", data=json.dumps(body).encode(),
                               headers={"X-SID-Console": "1"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        with e:
            return e.code, json.loads(e.read())


class _IsolatedState(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(dir=FAKE_HOME, prefix="state-"))
        os.chmod(self.state, 0o700)
        env = mock.patch.dict(os.environ, {"SID_CONSOLE_HOME": str(self.state)})
        env.start()
        self.addCleanup(env.stop)


class IndexGenerationTests(_IsolatedState):  # R1
    """The index in memory is always paired with the file it was read from."""

    def setUp(self):
        super().setUp()
        cfg.save({**cfg.DEFAULT_CONFIG, "sources": [], "project_roots": []})
        scan = mock.patch.object(index_mod, "build_static",
                                 side_effect=lambda conf, extra=None: marker_index("scanned"))
        self.scan = scan.start()
        self.addCleanup(scan.stop)
        self.publish("A")
        self.store = Store()

    def publish(self, marker):
        """What a CLI `scan` does: replace index.json atomically."""
        cfg.write_private(cfg.index_path(), json.dumps(marker_index(marker)))

    def test_replacement_after_read_is_not_stamped_onto_the_old_payload(self):
        real = self.store._load_or_scan

        def read_then_replace():
            loaded = real()
            self.publish("B")  # a CLI scan lands between the read and publication
            return loaded

        with mock.patch.object(self.store, "_load_or_scan", side_effect=read_then_replace):
            self.assertEqual(self.store.static()["marker"], "A")  # what was actually read
        self.assertEqual(self.store.static()["marker"], "B")
        self.publish("C")  # the same race on a reload of an already cached index
        with mock.patch.object(self.store, "_load_or_scan", side_effect=read_then_replace):
            self.assertEqual(self.store.static()["marker"], "C")
        self.assertEqual(self.store.static()["marker"], "B")

    def test_replacement_after_rescan_write_is_not_stamped_onto_the_scan(self):
        self.assertEqual(self.store.static()["marker"], "A")
        real_write = cfg.write_private

        def write_then_replace(path, text):
            written = real_write(path, text)
            if Path(path) == cfg.index_path():
                real_write(path, json.dumps(marker_index("B")))  # a CLI scan right after ours
            return written

        with mock.patch.object(cfg, "write_private", side_effect=write_then_replace):
            self.assertEqual(self.store.rescan()["marker"], "scanned")
        self.assertEqual(self.store.static()["marker"], "B")

    def test_replacement_with_same_or_older_mtime_is_loaded(self):
        self.assertEqual(self.store.static()["marker"], "A")
        first = cfg.index_path().stat()
        for marker, shift in (("same-mtime", 0), ("older-mtime", -10**9)):
            self.publish(marker)
            os.utime(cfg.index_path(), ns=(first.st_atime_ns, first.st_mtime_ns + shift))
            self.assertEqual(self.store.static()["marker"], marker)
        # same inode rewritten in place with its mtime put back: the size still differs
        before = cfg.index_path().stat()
        cfg.index_path().write_text(json.dumps(marker_index("in-place-longer")), encoding="utf-8")
        os.utime(cfg.index_path(), ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(cfg.index_path().stat().st_ino, before.st_ino)
        self.assertEqual(self.store.static()["marker"], "in-place-longer")

    def test_deleted_index_keeps_the_loaded_one_without_scanning(self):
        self.assertEqual(self.store.static()["marker"], "A")
        epoch = self.store._live_epoch
        cfg.index_path().unlink()
        for _ in range(2):
            self.assertEqual(self.store.static()["marker"], "A")
        self.scan.assert_not_called()  # rendering never starts a scan
        self.assertFalse(cfg.index_path().exists())
        self.assertEqual(self.store._live_epoch, epoch)
        self.publish("B")
        self.assertEqual(self.store.static()["marker"], "B")

    def test_own_writes_do_not_trigger_a_reload(self):
        data = self.store.rescan()
        epoch = self.store._live_epoch
        # every private state write re-tightens the files in the state dir
        # (chmod), which changes index.json's ctime but not its content
        cfg.write_private(cfg.state_dir() / "usage-cache.json", "{}")
        self.assertIs(self.store.static(), data)
        self.assertEqual(self.store._live_epoch, epoch)


class LiveEpochTests(_IsolatedState):  # R2
    """A live view is cached only under the epoch its static index belongs to,
    so a cached view's static is at least as new as the one published for that
    epoch. static() and live() may still briefly return different generations
    while a publish is in progress; that is not what these tests claim."""

    def setUp(self):
        super().setUp()
        cfg.save({**cfg.DEFAULT_CONFIG, "sources": [], "project_roots": []})
        cfg.write_private(cfg.index_path(), json.dumps(marker_index("old")))
        for name, fake in (("build_static", lambda conf, extra=None: marker_index("new")),
                           ("build_live", lambda conf, static: {"marker": static["marker"]})):
            patcher = mock.patch.object(index_mod, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = Store()
        self.assertEqual(self.store.static()["marker"], "old")

    def live_in_background(self):
        out = []
        thread = threading.Thread(target=lambda: out.append(self.store.live()), daemon=True)
        thread.start()
        return thread, out

    def finish(self, thread):
        thread.join(10)
        self.assertFalse(thread.is_alive(), "live build did not finish (deadlock?)")

    def test_rescan_between_snapshot_and_epoch_is_not_cached(self):
        real_static = self.store.static
        paused, resume = threading.Event(), threading.Event()

        def static_then_pause():
            snap = real_static()
            if not paused.is_set():  # only the first call stops
                paused.set()
                if not resume.wait(10):
                    raise RuntimeError("barrier timed out")
            return snap

        with mock.patch.object(self.store, "static", side_effect=static_then_pause):
            thread, out = self.live_in_background()
            self.assertTrue(paused.wait(10))
            self.store.rescan()  # publishes "new" and bumps the epoch
            resume.set()
            self.finish(thread)
        self.assertEqual(self.store.static()["marker"], "new")
        cached = self.store._live
        self.assertTrue(cached is None or cached["marker"] == "new", cached)
        self.assertEqual(self.store.live()["marker"], "new")
        self.assertEqual(out[0]["marker"], "new")

    def test_rescan_during_build_is_not_cached(self):
        building, resume = threading.Event(), threading.Event()

        def slow_build(conf, static):
            building.set()
            if not resume.wait(10):
                raise RuntimeError("barrier timed out")
            return {"marker": static["marker"]}

        with mock.patch.object(index_mod, "build_live", side_effect=slow_build):
            thread, out = self.live_in_background()
            self.assertTrue(building.wait(10))
            self.store.rescan()
            resume.set()
            self.finish(thread)
        self.assertEqual(out[0]["marker"], "old")  # it started before the rescan
        self.assertIsNone(self.store._live)
        self.assertEqual(self.store.live()["marker"], "new")

    def test_reload_found_by_the_build_is_cached(self):
        cfg.write_private(cfg.index_path(), json.dumps(marker_index("cli")))  # an external scan
        first = self.store.live()
        self.assertEqual(first["marker"], "cli")
        self.assertIs(self.store.live(), first)  # cached, not rebuilt


class CorruptConfigBackupTests(_IsolatedState):  # R3, R4
    RAW = b'{"sources": [\xff\xfe broken'  # neither JSON nor UTF-8

    def setUp(self):
        super().setUp()
        self.conf = cfg.config_path()
        self.bak = self.state / "config.json.bak"
        self.outside = Path(tempfile.mkdtemp(dir=FAKE_HOME, prefix="outside-")) / "target"
        self.corrupt(self.RAW)

    def corrupt(self, raw: bytes):
        self.raw = raw
        self.conf.write_bytes(raw)
        os.chmod(self.conf, 0o600)

    def refusal(self) -> str:
        with self.assertRaises(ValueError) as caught:
            cfg.save({"version": 1})
        return str(caught.exception)

    def assert_untouched(self):
        self.assertEqual(self.conf.read_bytes(), self.raw)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(list(self.state.glob("*.tmp")), [])

    def test_backup_is_owner_only_under_a_loose_umask(self):
        self.corrupt(b"{broken json")
        old = os.umask(0o022)
        try:
            self.assertTrue(cfg.load()["_corrupt"])
        finally:
            os.umask(old)
        self.assertFalse(self.bak.is_symlink())
        self.assertEqual(stat.S_IMODE(self.bak.stat().st_mode), 0o600)
        self.assertEqual(self.bak.read_bytes(), b"{broken json")
        self.assert_untouched()

    def test_backup_keeps_the_exact_bytes(self):
        self.assertTrue(cfg.load()["_corrupt"])
        self.assertEqual(self.bak.read_bytes(), self.RAW)
        self.assertIn("已備份至 config.json.bak", self.refusal())
        self.assert_untouched()

    def test_dangling_backup_symlink_is_not_followed(self):
        self.corrupt(b"{broken json")
        self.bak.symlink_to(self.outside)
        cfg.load()
        msg = self.refusal()
        self.assertTrue(self.bak.is_symlink())
        self.assertFalse(self.outside.exists())
        self.assertNotIn("已備份", msg)
        self.assert_untouched()

    def test_backup_symlink_to_a_file_is_not_followed(self):
        self.corrupt(b"{broken json")
        self.outside.write_bytes(b"unrelated")
        self.bak.symlink_to(self.outside)
        cfg.load()
        msg = self.refusal()
        self.assertTrue(self.bak.is_symlink())
        self.assertEqual(self.outside.read_bytes(), b"unrelated")
        self.assertNotIn("已備份", msg)
        self.assert_untouched()

    def test_older_backup_is_kept_and_not_reported_as_current(self):
        self.bak.write_bytes(b"older backup")
        cfg.load()
        msg = self.refusal()
        self.assertEqual(self.bak.read_bytes(), b"older backup")
        self.assertNotIn("已備份", msg)
        self.assertIn("config.json.bak", msg)
        self.assert_untouched()

    def test_existing_identical_backup_is_reported(self):
        self.bak.write_bytes(self.RAW)
        self.assertIn("已備份至 config.json.bak", self.refusal())
        self.assertEqual(self.bak.read_bytes(), self.RAW)

    def test_failed_backup_is_reported(self):
        os.chmod(self.state, 0o500)  # nothing new can be created in the state dir
        try:
            self.assertTrue(cfg.load()["_corrupt"])
            msg = self.refusal()
        finally:
            os.chmod(self.state, 0o700)
        self.assertFalse(os.path.lexists(self.bak))
        self.assertNotIn("已備份", msg)
        self.assert_untouched()

    def test_unreadable_config_is_reported(self):
        os.chmod(self.conf, 0)
        try:
            self.assertTrue(cfg.is_corrupt())
            self.assertTrue(cfg.load()["_corrupt"])
            msg = self.refusal()
        finally:
            os.chmod(self.conf, 0o600)
        self.assertFalse(os.path.lexists(self.bak))
        self.assertNotIn("已備份", msg)
        self.assert_untouched()

    def test_api_reports_backup_truthfully(self):
        from http.server import ThreadingHTTPServer
        from sidconsole.server import Console, make_handler
        self.bak.write_bytes(b"older backup")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        console = Console(httpd.server_address[1])
        httpd.RequestHandlerClass = make_handler(console)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.port}"
        try:
            status, body = post_json(base, "/api/config", {"usage_days": 30})
            self.assertEqual(status, 400)
            self.assertNotIn("已備份", body["error"])
            self.assertEqual(self.bak.read_bytes(), b"older backup")
            self.bak.unlink()  # once the old backup is gone, this file gets its own
            status, body = post_json(base, "/api/config", {"usage_days": 30})
            self.assertEqual(status, 400)
            self.assertIn("已備份至 config.json.bak", body["error"])
            self.assertEqual(self.bak.read_bytes(), self.RAW)
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assert_untouched()


class CorruptConfigScopeTests(_IsolatedState):  # F3, F4
    """A config that cannot be read never widens what is scanned."""

    def good_index(self):
        data = build_static({**cfg.DEFAULT_CONFIG, "sources": [], "project_roots": []})
        data["marker"] = "good"
        cfg.write_private(cfg.index_path(), json.dumps(data))
        return data

    def test_deep_nesting_counts_as_corrupt(self):
        cfg.config_path().write_text("[" * 200000, encoding="utf-8")
        self.assertTrue(cfg.is_corrupt())
        self.assertTrue(cfg.load()["_corrupt"])
        Store()  # starting the console must not crash

    def test_corrupt_config_turns_every_source_off(self):
        cfg.config_path().write_text("{broken", encoding="utf-8")
        conf = cfg.load()
        self.assertTrue(conf["_corrupt"])
        self.assertTrue(conf["sources"])
        self.assertFalse(any(src["enabled"] for src in conf["sources"]))
        self.assertEqual(conf["project_roots"], [])

    def test_rescan_is_refused_and_the_index_kept(self):
        self.good_index()
        before = cfg.index_path().read_bytes()
        cfg.config_path().write_text("{broken", encoding="utf-8")
        store = Store()
        with mock.patch.object(index_mod, "build_static") as scan:
            with self.assertRaises(ValueError):
                store.rescan()
            scan.assert_not_called()
        self.assertEqual(cfg.index_path().read_bytes(), before)
        self.assertEqual(store.static()["marker"], "good")

    def test_corrupt_config_does_not_add_herdr_project_roots(self):
        cfg.config_path().write_text("{broken", encoding="utf-8")
        store = Store()
        with mock.patch.object(index_mod.herdr, "snapshot") as snap, \
                mock.patch.object(index_mod, "build_static", return_value=marker_index("x")) as scan:
            store.static()  # no index on disk: first load scans
        snap.assert_not_called()
        conf, extra = scan.call_args[0]
        self.assertFalse(any(src["enabled"] for src in conf["sources"]))
        self.assertEqual(extra, [])

    def test_server_reports_corrupt_config(self):
        from http.server import ThreadingHTTPServer
        from sidconsole.server import Console, make_handler
        self.good_index()
        cfg.config_path().write_text("{broken", encoding="utf-8")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        console = Console(httpd.server_address[1])
        httpd.RequestHandlerClass = make_handler(console)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/api/config") as resp:
            view = json.loads(resp.read())
        self.assertTrue(view["corrupt"])
        self.assertNotIn("_corrupt", view["config"])  # internal flag stays internal
        with urllib.request.urlopen(base + "/api/overview") as resp:
            self.assertTrue(json.loads(resp.read())["config_corrupt"])
        status, body = post_json(base, "/api/rescan", {})
        self.assertEqual(status, 409)
        self.assertIn("設定檔已損毀", body["error"])


class RequestBodyTests(unittest.TestCase):  # Content-Length strictness, whole-body deadline
    setUpClass = classmethod(ServerTests.setUpClass.__func__)
    tearDownClass = classmethod(ServerTests.tearDownClass.__func__)
    req = ServerTests.req

    def raw_post(self, length_header, body=b""):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.console.port, timeout=10)
        conn.putrequest("POST", "/api/config")
        conn.putheader("Host", f"127.0.0.1:{self.console.port}")
        conn.putheader("X-SID-Console", "1")
        conn.putheader("Content-Length", length_header)
        conn.endheaders(body)
        resp = conn.getresponse()
        status = resp.status
        conn.close()
        return status

    def test_only_plain_digits_are_a_length(self):
        for bad in ("+5", "1_0", "-1", "0x10", "5 5", "9" * 20):
            self.assertEqual(self.raw_post(bad), 400, bad)
        self.assertEqual(self.raw_post("2", b"{}"), 200)

    def test_oversized_body_is_rejected_not_ignored(self):
        self.assertEqual(self.raw_post(str(64 * 1024 + 1)), 413)

    def test_trickled_body_hits_the_total_deadline(self):
        import socket
        import time
        from sidconsole import server as server_mod
        with mock.patch.object(server_mod, "BODY_DEADLINE_S", 0.6):
            conn = socket.create_connection(("127.0.0.1", self.console.port), timeout=10)
            conn.sendall((f"POST /api/config HTTP/1.1\r\nHost: 127.0.0.1:{self.console.port}\r\n"
                          "X-SID-Console: 1\r\nContent-Length: 20\r\n\r\n").encode())
            started = time.monotonic()
            reply = b""
            try:
                for _ in range(20):  # one byte every 0.2s: each read is fast, the total is not
                    conn.sendall(b" ")
                    time.sleep(0.2)
            except OSError:
                pass  # the server closed the connection while we were still sending
            try:
                reply = conn.recv(4096)
            except OSError:
                pass
            conn.close()
        self.assertLess(time.monotonic() - started, 3.5)
        self.assertNotIn(b"200 OK", reply)
        self.assertEqual(self.req("/api/config")[0], 200)  # still serving


class UnreadSkillStateTests(_HostileBase):  # C2
    def test_unread_skill_is_not_called_usable(self):
        recs = self.scan()
        for name in ("huge", "linked"):
            self.assertEqual(recs[name].activation, "unknown", name)
            self.assertIn("無法確認", recs[name].activation_reason)
        self.assertEqual(recs["good"].activation, "active")

    def test_states_that_already_say_unusable_are_kept(self):
        from sidconsole.model import ACT_DISABLED, unread_activation
        self.assertEqual(unread_activation(ACT_DISABLED, "off", "too big"), (ACT_DISABLED, "off"))


class SecretNameTests(unittest.TestCase):  # C3
    def test_names_that_hold_secrets(self):
        for name in ("api_key", "apiKey", "ANTHROPIC_API_KEY", "access_token", "password",
                     "client_secret", "private_key", "token", "authToken"):
            self.assertTrue(document.secret_key_name(name), name)

    def test_names_that_only_describe_a_secret(self):
        for name in ("max_tokens", "maxTokens", "token_count", "primary_key", "sort_key",
                     "token_file", "api_key_env", "secret_name", "password_min_length"):
            self.assertFalse(document.secret_key_name(name), name)

    def test_describing_names_still_hide_secret_looking_values(self):
        """A describing name is no excuse: only harmless values stay visible."""
        text = document.redact("secret_file: hunter2\ndb_password_env: hunter2\n"
                               "token_type: opaque-value\npassword_min_length: 12")
        self.assertNotIn("hunter2", text)
        self.assertNotIn("opaque-value", text)
        self.assertIn("password_min_length: 12", text)
        self.assertEqual(document.redact_value("secret_file", "hunter2"), document.REDACTED)
        self.assertEqual(document.redact_value("max_tokens", 4096), 4096)
        self.assertEqual(document.redact_value("primary_key", "id"), "id")

    def test_credentials_hidden_in_paths_urls_and_subkeys(self):
        """Reported by the independent review of 304fb89."""
        for name, value in (("token_url", "https://admin:hunter2@api.internal.corp/v1"),
                            ("api_key_url", "http://u:hunter2@h/x"),
                            ("sub_key", "supersecretpassword"),
                            ("secret_name", ".k9Px9qZsecret"),
                            ("token_file", "/AAAABBBBCCCCDDDD+base64key==")):
            self.assertTrue(document.secret_value_for(name, value), f"{name}: {value}")
            self.assertNotIn(value, document.redact(f"{name}: {value}"))
        for name, value in (("token_url", "https://api.test/v1"), ("token_file", "~/.config/t"),
                            ("secret_file", "/etc/app/secrets.json"), ("max_tokens", "4096")):
            self.assertIn(value, document.redact(f"{name}: {value}"), name)

    def test_values_are_still_caught_by_shape(self):
        text = document.redact("api_key_env: OPENAI_KEY\ntoken_file: sk-ant-abcdefghijklmnopqrstuv\n"
                               "max_tokens: 4096\ntoken_url: https://x.test/?token=s3cr3tvalue")
        self.assertIn("api_key_env: OPENAI_KEY", text)
        self.assertIn("max_tokens: 4096", text)
        self.assertNotIn("sk-ant-", text)
        self.assertNotIn("s3cr3tvalue", text)


def tearDownModule():
    shutil.rmtree(FAKE_HOME, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
