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
        status, _, _ = self.req("/api/focus", "POST", body={"target": "w1:p1; rm -rf /"},
                                headers={"X-SID-Console": "1"})
        self.assertEqual(status, 400)

    def test_config_only_accepts_known_keys(self):
        _, data, _ = self.req("/api/config", "POST", headers={"X-SID-Console": "1"},
                              body={"usage_days": 9999, "host": "0.0.0.0", "port": 1})
        self.assertEqual(data["config"]["usage_days"], 365)
        self.assertEqual(data["config"]["host"], cfg.DEFAULT_HOST)
        self.assertEqual(data["config"]["port"], cfg.DEFAULT_PORT)


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


def tearDownModule():
    shutil.rmtree(FAKE_HOME, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
