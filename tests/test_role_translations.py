"""Role-name translations (P30): fake provider only, synthetic HOME/state, never a real CLI."""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from tests import test_translations as fixtures
from tests.test_translations import entry, record
from vbear import config as cfg, server, translations as tr
from vbear.index import Store


def role(**changes):
    data = {"role_id": "r-one", "name": "Brand Guardian", "tool": "codex", "kind": "subagent",
            "path": "/do-not-send/agent.md", "model": "private-model",
            "description": {"value": "Protects the brand voice", "origin": "author", "detail": "private-path"},
            "capabilities": {"value": "private-capabilities", "origin": "author"},
            "suitable_tasks": {"value": "private-tasks", "origin": "author"},
            "limits": {"value": "private-limits", "origin": "author"}}
    data.update(changes)
    return data


def role_entry(rec=None):
    return {"lang": "zh-TW", "source_hash": tr.role_source_hash(rec or role()), "created_at": time.time(),
            "engine": "claude", "model": tr.MODELS["claude"], "cli_version": "2.1.296",
            "name_zh": "品牌守護者", "what": "守護品牌語氣"}


ROLE_RESULT = {"name_zh": "品牌守護者", "what": "守護品牌語氣"}

FAKE_ROLE = '''#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ['--version']:
    print('2.1.296 (Claude Code)')
    sys.exit(0)
assert args[args.index('--tools')+1] == ''
assert '--safe-mode' in args and '--strict-mcp-config' in args
assert args[args.index('--mcp-config')+1] == '{{"mcpServers":{{}}}}'
assert args[args.index('--model')+1] == 'claude-haiku-5-5'
assert args[args.index('--max-budget-usd')+1] == '0.05'
assert '--no-session-persistence' in args
schema = json.loads(args[args.index('--json-schema')+1])
assert schema == {{'type':'object', 'properties':{{k:{{'type':'string'}} for k in ('name_zh','what')}}, 'required':['name_zh','what'], 'additionalProperties':False}}
assert not list(Path.cwd().iterdir())
prompt = sys.stdin.read()
assert '繁體中文（台灣用語，不得使用簡體字）' in prompt and 'BEGIN_UNTRUSTED_JSON_STRING' in prompt
assert '/do-not-send' not in prompt and 'private-' not in prompt and 'codex' not in prompt
{action}
'''


class RoleTranslationTests(fixtures.TranslationTests):
    def fake_role(self, action=None):
        script = self.root / "fake-role-cli"
        if action is None:
            action = "print(json.dumps(" + repr({"type": "result", "is_error": False, "structured_output": ROLE_RESULT}) + "))"
        script.write_text(FAKE_ROLE.format(python=sys.executable, action=action))
        script.chmod(0o700)
        return lambda engine: (str(script), "2.1.296")

    def test_only_name_and_author_description_are_sent(self):
        fields = tr.role_source_fields(role())
        self.assertEqual(set(fields), {"name", "description"})
        self.assertEqual(fields, {"name": "Brand Guardian", "description": "Protects the brand voice"})
        derived = tr.role_source_fields(role(description={"value": "guessed", "origin": "derived"}))
        self.assertEqual(derived, {"name": "Brand Guardian", "description": None})
        missing = tr.role_source_fields(role(description={"value": None, "origin": "missing"}))
        self.assertIsNone(missing["description"])
        prompt = tr.role_prompt_for(role())
        for secret in ("/do-not-send", "private-", "codex", "subagent", "r-one"):
            self.assertNotIn(secret, prompt)
        self.assertIn("Brand Guardian", prompt)
        self.assertIn("Protects the brand voice", prompt)

    def test_source_is_redacted_and_hash_follows_the_sent_fields_only(self):
        secret = "sk-ant-api03-" + "A" * 40
        fields = tr.role_source_fields(role(description={"value": "use key " + secret, "origin": "author"}))
        self.assertNotIn(secret, json.dumps(fields))
        base = tr.role_source_hash(role())
        self.assertEqual(base, tr.role_source_hash(role(path="/elsewhere", tool="claude", capabilities={"value": "x", "origin": "author"})))
        self.assertNotEqual(base, tr.role_source_hash(role(name="Other")))
        self.assertNotEqual(base, tr.role_source_hash(role(description={"value": "changed", "origin": "author"})))
        self.assertEqual(tr.role_source_hash(role(description={"value": "guess", "origin": "derived"})),
                         tr.role_source_hash(role(description={"value": None, "origin": "missing"})))

    def test_result_validation_rejects_bad_shapes(self):
        src = tr.role_source_fields(role())
        self.assertEqual(tr.validate_role_result(dict(ROLE_RESULT), src), ROLE_RESULT)
        bad = [{"name_zh": "品牌守護者"}, {"what": "守護品牌語氣"}, {**ROLE_RESULT, "extra": "x"},
               {**ROLE_RESULT, "name_zh": "字" * 31}, {**ROLE_RESULT, "what": "字" * 51},
               {**ROLE_RESULT, "name_zh": ""}, {**ROLE_RESULT, "what": "  "}, {**ROLE_RESULT, "name_zh": 5},
               [], "text", None]
        for value in bad:
            with self.assertRaises(tr.TranslationError, msg=repr(value)) as cm:
                tr.validate_role_result(value, src)
            self.assertEqual(cm.exception.code, "invalid_output")
        for value in ({**ROLE_RESULT, "name_zh": "品牌审查者"}, {**ROLE_RESULT, "what": "这是设计"}):
            with self.assertRaises(tr.TranslationError) as cm:
                tr.validate_role_result(value, src)
            self.assertEqual(cm.exception.code, "not_traditional")
        edge = tr.validate_role_result({"name_zh": "字" * 30, "what": "字" * 50}, src)
        self.assertEqual((len(edge["name_zh"]), len(edge["what"])), (30, 50))

    def test_missing_description_forces_what_to_the_missing_marker(self):
        src = tr.role_source_fields(role(description={"value": None, "origin": "missing"}))
        self.assertEqual(tr.validate_role_result(dict(ROLE_RESULT), src)["what"], tr.MISSING)
        src = tr.role_source_fields(role(description={"value": "model guess", "origin": "derived"}))
        self.assertEqual(tr.validate_role_result(dict(ROLE_RESULT), src)["what"], tr.MISSING)

    def test_result_text_is_redacted(self):
        secret = "sk-ant-api03-" + "B" * 24
        out = tr.validate_role_result({"name_zh": "品牌", "what": secret}, tr.role_source_fields(role()))
        self.assertNotIn(secret, json.dumps(out))

    def test_states(self):
        rec, ent = role(), role_entry()
        self.assertEqual(tr.role_translation_state(rec, None), "none")
        self.assertEqual(tr.role_translation_state(rec, ent), "fresh")
        self.assertEqual(tr.role_translation_state(role(name="Changed"), ent), "stale")
        self.assertEqual(tr.role_translation_state(None, ent), "orphan")
        self.assertEqual(tr.role_translation_state(None, None), "none")

    def test_fake_cli_end_to_end_uses_the_role_schema(self):
        result = tr.run_role_cli("claude", role(), threading.Event(), provider=self.fake_role())
        self.assertEqual((result["name_zh"], result["what"]), ("品牌守護者", "守護品牌語氣"))
        self.assertEqual(result["source_hash"], tr.role_source_hash(role()))
        self.assertEqual(tr.role_entry_problem("r-one", result), None)
        bare = role(description={"value": None, "origin": "missing"})
        self.assertEqual(tr.run_role_cli("claude", bare, threading.Event(), provider=self.fake_role())["what"], tr.MISSING)

    def test_fake_cli_bad_output_is_refused(self):
        for payload in ({"type": "result", "is_error": False, "structured_output": {"name_zh": "x"}},
                        {"type": "result", "is_error": False, "result": json.dumps(ROLE_RESULT)},
                        {"type": "result", "is_error": False, "structured_output": {**ROLE_RESULT, "what": "字" * 51}}):
            action = "print(json.dumps(" + repr(payload) + "))"
            with self.assertRaises(tr.TranslationError) as cm:
                tr.run_role_cli("claude", role(), threading.Event(), provider=self.fake_role(action))
            self.assertEqual(cm.exception.code, "invalid_output")

    def test_skill_argv_is_unchanged_and_schema_can_be_passed(self):
        default = tr.translation_argv("claude", "bin", "/tmp/x")
        self.assertEqual(json.loads(default[default.index("--json-schema") + 1]), tr.RESULT_SCHEMA)
        custom = tr.translation_argv("claude", "bin", "/tmp/x", tr.ROLE_RESULT_SCHEMA)
        self.assertEqual(json.loads(custom[custom.index("--json-schema") + 1]), tr.ROLE_RESULT_SCHEMA)
        self.assertEqual([a for a in custom if a != custom[custom.index("--json-schema") + 1]],
                         [a for a in default if a != default[default.index("--json-schema") + 1]])

    def test_role_cache_is_a_separate_file_and_skill_cache_still_reads(self):
        skills = tr.TranslationManager(lambda e, r, c: entry(r))
        saved = entry()
        skills.store.put("s-one", saved)
        roles = tr.RoleTranslationManager(lambda e, r, c: role_entry(r))
        self.assertEqual(roles.store.load_entries(), {})
        roles.start({"r-one": role()}, "claude")
        self.wait(roles)
        self.assertTrue((cfg.state_dir() / "role-translations.json").exists())
        self.assertEqual(set(skills.store.load_entries()), {"s-one"})
        self.assertEqual(set(roles.store.load_entries()), {"r-one"})
        raw = json.loads((cfg.state_dir() / "translations.json").read_text())
        self.assertEqual(set(raw["entries"]), {"s-one"})
        self.assertEqual(skills.store.load_entries()["s-one"], saved)

    def test_skill_entries_are_not_valid_role_entries_and_back(self):
        self.assertIsNotNone(tr.role_entry_problem("k", entry()))
        self.assertIsNotNone(tr.entry_problem("k", role_entry()))
        cfg.write_private(cfg.state_dir() / "role-translations.json", json.dumps({"version": 1, "entries": {"k": entry()}}))
        with self.assertRaises(tr.StoreError):
            tr.RoleTranslationManager().store.load_entries()
        # a damaged role cache never touches the skill cache
        self.assertEqual(tr.TranslationManager().store.load_entries(), {})

    def test_role_cache_envelope_and_entry_checks(self):
        store = tr.RoleTranslationStore()
        store.put("r-one", role_entry())
        self.assertEqual(store.load_entries()["r-one"]["name_zh"], "品牌守護者")
        path = cfg.state_dir() / "role-translations.json"
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        for change in ({"name_zh": "字" * 31}, {"what": "字" * 51}, {"lang": "en"}, {"extra": 1}, {"name_zh": "品牌审查"}):
            self.assertIsNotNone(tr.role_entry_problem("r-one", {**role_entry(), **change}), change)
        self.assertIsNotNone(tr.role_entry_problem("r-one", {k: v for k, v in role_entry().items() if k != "what"}))

    def test_worker_lock_is_shared_between_skill_and_role_jobs(self):
        started = threading.Event()
        def slow(engine, rec, cancel):
            started.set()
            cancel.wait(2)
            return role_entry(rec) if "role_id" in rec else entry(rec)
        skills, roles = tr.TranslationManager(slow), tr.RoleTranslationManager(slow)
        skills.start({"s": record()}, "claude")
        self.assertTrue(started.wait(1))
        with self.assertRaises(tr.TranslationError) as cm:
            roles.start({"r-one": role()}, "claude")
        self.assertEqual(cm.exception.code, "busy")
        skills.cancel()
        self.wait(skills)
        started.clear()
        roles.start({"r-one": role()}, "claude")
        self.assertTrue(started.wait(1))
        with self.assertRaises(tr.TranslationError) as cm:
            skills.start({"s": record()}, "claude")
        self.assertEqual(cm.exception.code, "busy")
        with self.assertRaises(tr.TranslationError) as cm:
            roles.start({"r-one": role()}, "claude")
        self.assertEqual(cm.exception.code, "busy")
        roles.cancel()
        self.assertEqual(self.wait(roles)["status"], "cancelled")
        self.assertEqual(roles.store.load_entries(), {})

    def test_role_manager_never_translates_on_scan(self):
        manager = tr.RoleTranslationManager(lambda e, r, c: self.fail("no automatic translation"))
        manager.after_scan({"roles": [role()]}, {"translation_auto": True})
        self.assertIsNone(manager.job)

    def test_production_role_manager_refuses_before_any_subprocess(self):
        manager = tr.RoleTranslationManager()
        with mock.patch.object(tr, "claude_identity", return_value=("fake", "2.1.296")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("no real CLI")):
            with self.assertRaises(tr.TranslationError) as cm:
                manager.start({"r-one": role()}, "claude")
            self.assertEqual(cm.exception.code, "boundary_unverified")
        with mock.patch.object(tr.shutil, "which", return_value=None), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("no real CLI")):
            with self.assertRaises(tr.TranslationError) as cm:
                manager.start({"r-one": role()}, "claude")
            self.assertEqual(cm.exception.code, "cli_not_found")
        self.assertIsNone(manager.job)

    def test_failed_role_job_reports_a_fixed_error(self):
        def run(engine, rec, cancel):
            raise tr.TranslationError("invalid_output")
        manager = tr.RoleTranslationManager(run)
        manager.start({"r-one": role()}, "claude")
        job = self.wait(manager)
        self.assertEqual((job["status"], job["failed"], job["error"]["code"]), ("failed", 1, "invalid_output"))
        self.assertEqual(manager.store.load_entries(), {})


class RoleTranslationApiTests(fixtures.TranslationTests):
    def setUp(self):
        super().setUp()
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = 'synthetic-test-token'
        c.store = Store()
        c.store._static = {"skills": [record()], "roles": [role(), role(role_id="r-two", name="Trend Researcher",
                           description={"value": None, "origin": "missing"})]}
        c.store.set_conf(cfg.load())
        c.translations = tr.TranslationManager(lambda engine, rec, cancel: entry(rec))
        c.role_translations = tr.RoleTranslationManager(lambda engine, rec, cancel: role_entry(rec))
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    call = __import__("tests.test_translations_api", fromlist=["x"]).TranslationApiTests.call

    def test_view_reads_the_loaded_index_without_scanning_or_starting(self):
        with mock.patch.object(Store, 'static', side_effect=AssertionError('no scan')), \
             mock.patch('subprocess.Popen', side_effect=AssertionError('no CLI')):
            status, view = self.call('/api/role-translations')
        self.assertEqual(status, 200, view)
        self.assertEqual(view['counts']['none'], 2)
        self.assertEqual(view['provider'], 'fake')
        self.assertNotIn('Protects the brand voice', json.dumps(view))
        self.assertIsNone(self.console.role_translations.job)

    def test_the_tools_own_main_agents_are_not_listed_to_translate_or_sent(self):
        # cli-claude / cli-codex are VBear's own names with its own Chinese; the author wrote nothing to translate
        self.console.store._static["roles"] += [
            role(role_id="cli-codex", name="Codex 主代理", kind="cli", description={"value": "VBear's own words", "origin": "derived"}),
            role(role_id="cli-claude", name="Claude Code 主代理", tool="claude", kind="cli",
                 description={"value": "VBear's own words", "origin": "derived"})]
        view = self.call('/api/role-translations')[1]
        self.assertEqual(view['counts']['none'], 2, view)
        status, result = self.call('/api/role-translations/batch', 'POST', {})
        self.assertEqual((status, result['job']['total']), (202, 2), result)
        self.wait(self.console.role_translations)
        view = self.call('/api/role-translations')[1]
        self.assertEqual(sorted(view['entries']), ['r-one', 'r-two'])
        self.assertEqual(view['counts']['fresh'], 2)

    def test_batch_success_then_fresh_and_skill_view_unchanged(self):
        status, result = self.call('/api/role-translations/batch', 'POST', {})
        self.assertEqual(status, 202, result)
        self.assertEqual(result['job']['total'], 2)
        self.wait(self.console.role_translations)
        view = self.call('/api/role-translations')[1]
        self.assertEqual(view['counts']['fresh'], 2)
        self.assertEqual(view['entries']['r-one']['entry']['name_zh'], '品牌守護者')
        self.assertEqual(self.call('/api/translations')[1]['counts']['none'], 1)
        status, again = self.call('/api/role-translations/batch', 'POST', {'which': 'none'})
        self.assertEqual((status, again['job']['total']), (202, 0))

    def test_batch_validation(self):
        for body in ({'which': []}, {'which': 'all'}, {'x': 1}, [1]):
            self.assertEqual(self.call('/api/role-translations/batch', 'POST', body)[0], 400, body)
        self.assertIsNone(self.console.role_translations.job)

    def test_busy_with_a_role_job_and_with_a_skill_job(self):
        started = threading.Event()
        def slow(engine, rec, cancel):
            started.set()
            cancel.wait(2)
            return entry(rec)
        self.console.translations = tr.TranslationManager(slow)
        self.assertEqual(self.call('/api/skills/s-one/translate', 'POST', {})[0], 202)
        self.assertTrue(started.wait(1))
        status, data = self.call('/api/role-translations/batch', 'POST', {})
        self.assertEqual((status, data['code']), (409, 'busy'))
        self.call('/api/translations/batch/cancel', 'POST', {})
        self.wait(self.console.translations)

        started.clear()
        self.console.role_translations = tr.RoleTranslationManager(lambda e, r, c: (started.set(), c.wait(2), role_entry(r))[2])
        self.assertEqual(self.call('/api/role-translations/batch', 'POST', {})[0], 202)
        self.assertTrue(started.wait(1))
        for path in ('/api/role-translations/batch', '/api/translations/batch'):
            status, data = self.call(path, 'POST', {})
            self.assertEqual((status, data['code']), (409, 'busy'), path)
        self.assertEqual(self.call('/api/role-translations/batch/cancel', 'POST', {})[0], 200)
        self.wait(self.console.role_translations)

    def test_production_manager_reports_cli_not_found_and_boundary_unverified(self):
        self.console.role_translations = tr.RoleTranslationManager()
        view = self.call('/api/role-translations')[1]
        self.assertEqual(view['provider'], 'version_required')
        with mock.patch.object(tr.shutil, 'which', return_value=None), mock.patch('subprocess.Popen', side_effect=AssertionError('no CLI')):
            status, data = self.call('/api/role-translations/batch', 'POST', {})
        self.assertEqual((status, data['code']), (409, 'cli_not_found'))
        self.assertIn('Claude Code', data['error'])
        with mock.patch.object(tr, 'claude_identity', return_value=('fake', '2.1.296')), mock.patch('subprocess.Popen', side_effect=AssertionError('no CLI')):
            status, data = self.call('/api/role-translations/batch', 'POST', {})
        self.assertEqual((status, data['code']), (409, 'boundary_unverified'))
        self.assertIsNone(self.console.role_translations.job)

    def test_unloaded_index_and_damaged_cache_have_fixed_errors(self):
        self.console.store._static = None
        status, data = self.call('/api/role-translations')
        self.assertEqual((status, data['code']), (404, 'not_found'))
        self.console.store._static = {"skills": [], "roles": [role()]}
        cfg.write_private(cfg.state_dir() / 'role-translations.json', '{bad')
        status, data = self.call('/api/role-translations')
        self.assertEqual((status, data['code']), (503, 'storage'))
        self.assertNotIn(str(self.root), data['error'])

    def test_token_origin_host_fetch_site_and_body_limit(self):
        for path, method in (('/api/role-translations/batch', 'POST'), ('/api/role-translations/batch/cancel', 'POST')):
            self.assertEqual(self.call(path, method, {}, {'Authorization': 'Bearer bad'})[0], 401)
            self.assertEqual(self.call(path, method, {}, {'Origin': 'http://evil.example'})[0], 403)
            self.assertEqual(self.call(path, method, {}, {'X-VBear': ''})[0], 403)
            self.assertEqual(self.call(path, method, {}, {'Host': 'evil.example'})[0], 421)
        self.assertEqual(self.call('/api/role-translations', headers={'Authorization': 'Bearer bad'})[0], 401)
        self.assertEqual(self.call('/api/role-translations', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.call('/api/role-translations/batch', 'POST', {'x': 'a' * 66000})[0], 413)
        self.assertIsNone(self.console.role_translations.job)

    def test_changing_the_engine_cancels_a_role_job(self):
        self.call('/api/config', 'POST', {'translation_engine': 'codex'})
        self.assertTrue(self.console.role_translations.cancel_event.is_set())


for _cls in (RoleTranslationTests, RoleTranslationApiTests):
    for _name in list(fixtures.TranslationTests.__dict__):
        if _name.startswith("test_") and _name not in _cls.__dict__:
            setattr(_cls, _name, None)
