"""HTTP boundary tests, a fake-only worker and synthetic HOME/state."""
import json
import os
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


class TranslationApiTests(fixtures.TranslationTests):
    # Inherit only the shared environment helpers, not the unit cases.
    def setUp(self):
        super().setUp()
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = 'synthetic-test-token'
        c.store = Store()
        c.store._static = {"skills": [record()], "roles": []}
        c.store.set_conf(cfg.load())
        c.translations = tr.TranslationManager(lambda engine, rec, cancel: entry(rec))
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, method='GET', body=None, headers=None):
        hdr = {'Authorization': 'Bearer synthetic-test-token', 'X-VBear': '1',
               'Origin': f'http://127.0.0.1:{self.console.port}', 'Content-Type': 'application/json'}
        if headers:
            hdr.update(headers)
        req = urllib.request.Request(f'http://127.0.0.1:{self.console.port}' + path,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def test_api_reads_never_scan_or_start_and_do_not_export_original(self):
        with mock.patch.object(Store, 'static', side_effect=AssertionError('no scan')), \
             mock.patch('subprocess.Popen', side_effect=AssertionError('no CLI')):
            status, view = self.call('/api/translations')
        self.assertEqual(status, 200, view)
        self.assertEqual(view['counts']['none'], 1)
        self.assertNotIn('Review changes', json.dumps(view))
        self.assertIsNone(self.console.translations.job)

    def test_api_single_batch_cancel_orphans_and_invalid_input(self):
        status, result = self.call('/api/skills/s-one/translate', 'POST', {})
        self.assertEqual(status, 202, result)
        self.wait(self.console.translations)
        self.assertEqual(self.call('/api/translations/batch')[1]['counts']['fresh'], 1)
        self.assertEqual(self.call('/api/translations/batch', 'POST', {'which': []})[0], 400)
        self.assertEqual(self.call('/api/translations/batch', 'POST', [1])[0], 400)
        self.assertEqual(self.call('/api/skills/missing/translate', 'POST', {})[0], 404)
        self.assertEqual(self.call('/api/translations/batch/cancel', 'POST', {})[0], 200)
        self.console.store._static['skills'] = []
        self.assertEqual(self.call('/api/translations')[1]['counts']['orphan'], 1)
        self.assertEqual(self.call('/api/translations/orphans', 'DELETE')[1]['deleted'], 1)

    def test_api_token_origin_host_fetch_site_and_body_limit(self):
        for path, method in (('/api/translations/batch', 'POST'), ('/api/translations/verify', 'POST'), ('/api/translations/orphans', 'DELETE')):
            self.assertEqual(self.call(path, method, {}, {'Authorization': 'Bearer bad'})[0], 401)
            self.assertEqual(self.call(path, method, {}, {'Origin': 'http://evil.example'})[0], 403)
            self.assertEqual(self.call(path, method, {}, {'X-VBear': ''})[0], 403)
            self.assertEqual(self.call(path, method, {}, {'Host': 'evil.example'})[0], 421)
        self.assertEqual(self.call('/api/translations', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.call('/api/translations/batch', 'POST', {'x': 'a' * 66000})[0], 413)
        self.assertIsNone(self.console.translations.job)

    def test_api_verify_uses_explicit_post_and_rejects_body_overrides(self):
        with mock.patch.object(tr, "verify_boundary", return_value={"version": "2.1.301", "passed_at": 1}) as verify:
            status, data = self.call('/api/translations/verify', 'POST', {})
            self.assertEqual(status, 200, data)
            verify.assert_called_once_with("claude")
            for body in ({"engine": "claude"}, {"version": "2.1.301"}, []):
                self.assertEqual(self.call('/api/translations/verify', 'POST', body)[0], 400)
            self.assertEqual(verify.call_count, 1)
            self.call('/api/translations/verify')
            self.assertEqual(verify.call_count, 1)

    def test_api_config_consent_validation_engine_change_and_disable(self):
        self.assertEqual(self.call('/api/config', 'POST', {'translation_auto': True})[0], 400)
        self.assertEqual(self.call('/api/config', 'POST', {'translation_auto': 'yes'})[0], 400)
        self.assertEqual(self.call('/api/config', 'POST', {'translation_engine': []})[0], 400)
        status, data = self.call('/api/config', 'POST', {'translation_auto': True, 'translation_consent_engine': 'claude'})
        self.assertEqual(status, 200, data)
        self.assertTrue(cfg.load()['translation_auto'])
        self.assertFalse(self.call('/api/config', 'POST', {'translation_engine': 'codex'})[1]['config']['translation_auto'])
        self.assertEqual(self.call('/api/config', 'POST', {'translation_auto': True, 'translation_consent_engine': 'claude'})[0], 400)
        self.assertEqual(self.call('/api/config', 'POST', {'translation_auto': True, 'translation_consent_engine': 'codex'})[0], 200)
        self.assertEqual(self.call('/api/config', 'POST', {'translation_auto': False})[0], 200)
        self.assertTrue(self.console.translations.cancel_event.is_set())

    def test_api_cache_errors_are_fixed_private_classifications(self):
        cfg.write_private(cfg.state_dir() / 'translations.json', '{bad')
        status, data = self.call('/api/translations')
        self.assertEqual(status, 503)
        self.assertEqual(data['code'], 'storage')
        self.assertNotIn(str(self.root), data['error'])

for _name in list(fixtures.TranslationTests.__dict__):
    if _name.startswith("test_") and _name not in TranslationApiTests.__dict__:
        setattr(TranslationApiTests, _name, None)
