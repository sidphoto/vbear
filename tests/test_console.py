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
        status, data, _ = self.req("/api/focus", "POST", body={"target": "w1:p1; rm -rf /"},
                                   headers={"X-SID-Console": "1"})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])

    def test_config_only_accepts_known_keys(self):
        _, data, _ = self.req("/api/config", "POST", headers={"X-SID-Console": "1"},
                              body={"usage_days": 9999, "host": "0.0.0.0", "port": 1})
        self.assertEqual(data["config"]["usage_days"], 365)
        self.assertEqual(data["config"]["host"], cfg.DEFAULT_HOST)
        self.assertEqual(data["config"]["port"], cfg.DEFAULT_PORT)


def tearDownModule():
    shutil.rmtree(FAKE_HOME, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
