"""P48-5 / 16f: deleted records still count. No daemon or real CLI."""
import fcntl
import os
import stat
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import chief, meetings as mt, staffing as st, memory_suggest as ms, skillbook_suggest as ks, spend_keep
from vbear.meeting_runner import MeetingRunner
from tests.test_meetings import record, evidence
from tests.test_staffing import staffing_record
from tests import test_chief as chief_fixtures

CASES = ((mt, mt.MeetingStore), (st, st.StaffingStore), (chief, chief.ChiefStore),
         (ms, ms.SuggestStore), (ks, ks.SuggestStore))


class SpendKeepTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v48-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / 'h' / '.vbear'
        self.base.mkdir(parents=True, mode=0o700)
        p = mock.patch.dict(os.environ, HOME=str(self.base.parent), VBEAR_HOME=str(self.base), VBEAR_RUNTIME_AUTOSTART='0')
        p.start()
        self.addCleanup(p.stop)
        self.now = 1800000000.0
        clock = mock.patch('time.time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.runner = MeetingRunner(clock=lambda: self.now)

    def make(self, mod, store_cls, state='cancelled'):
        if mod is mt:
            rec = record(now=self.now)
        elif mod is st:
            rec = staffing_record(now=self.now)
        elif mod is chief:
            rec = chief_fixtures.TheRecord().new()
        else:
            args = dict(chat_id='c-0123456789abcdef', engine='claude-chat',
                        read=dict(count=2, omitted=0, bytes=30, sha256='a'*64),
                        limits=dict(per_call_usd=Decimal('.1'), total_usd=Decimal('.1')), now=self.now)
            if mod is ms:
                args.update(memory_count=0, inputs='b'*64)
            rec = mod.new_record(('ms-' if mod is ms else 'ks-')+'0123456789ab', **args)
        for t in rec['turns']:
            t.update(state=state)
        # Interrupted/cancelled attempts may already have incurred cost.
        rec['turns'][0].update(attempts=1, started_at=self.now, ended_at=self.now,
                               prompt_sha256='a'*64, evidence=evidence('0.037'))
        store = store_cls(rec['id'])
        with store.locked():
            store.save(rec)
        return rec, store

    def assert_kept(self, mod, store_cls):
        rec, store = self.make(mod, store_cls)
        before = self.runner._day()
        self.assertGreater(before, 0)
        mod.delete(rec['id'])
        self.assertFalse(store.path().exists())
        self.assertGreaterEqual(self.runner._day(), before)
        self.assertEqual(self.runner.ledger({})['spent_usd'], mt.fmt(before))

    def test_each_delete_keeps_the_day_and_ledger(self):
        for mod, store_cls in CASES:
            with self.subTest(kind=mod.__name__):
                self.assert_kept(mod, store_cls)

    def test_queued_and_running_cannot_be_deleted(self):
        for mod, store_cls in CASES:
            for state in ('queued', 'running'):
                with self.subTest(kind=mod.__name__, state=state):
                    rec, store = self.make(mod, store_cls, state)
                    with self.assertRaises(mt.MeetingError) as got:
                        mod.delete(rec['id'])
                    self.assertEqual(got.exception.code, 'running')
                    self.assertTrue(store.path().exists())

    def test_bad_tombstone_makes_day_unknown_and_blocks_spending(self):
        for mod, store_cls in CASES:
            with self.subTest(kind=mod.__name__):
                rec, _ = self.make(mod, store_cls)
                mod.delete(rec['id'])
        files = list((self.base / 'spend-keep').glob('*.json'))
        self.assertEqual(len(files), 5)
        for path in files:
            with self.subTest(tombstone=path.name):
                saved = path.read_text()
                path.write_text('{broken')
                with self.assertRaises(mt.MeetingError) as got:
                    self.runner._day()
                self.assertEqual(got.exception.code, mt.SPEND_UNKNOWN)
                with self.assertRaises(mt.MeetingError) as blocked:
                    self.runner._blockers(Decimal('.1'), Decimal('1'), mt.DEFAULT_LIMITS)
                self.assertEqual(blocked.exception.code, mt.SPEND_UNKNOWN)
                path.write_text(saved)

    def test_private_and_expired_tombstones_are_removed(self):
        for mod, store_cls in CASES:
            rec, _ = self.make(mod, store_cls)
            mod.delete(rec['id'])
        folder = self.base / 'spend-keep'
        files = list(folder.glob('*.json'))
        self.assertEqual(len(files), 5)
        self.assertTrue(all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files))
        self.now += 3 * 86400
        with mock.patch('time.time', return_value=self.now):
            self.assertEqual(self.runner._day(), 0)
        self.assertEqual(list(folder.iterdir()), [])

    def test_failed_keep_write_preserves_original(self):
        for mod, store_cls in CASES:
            rec, store = self.make(mod, store_cls)
            with mock.patch('vbear.spend_keep._write', side_effect=OSError('fake disk failure')):
                with self.assertRaises(mt.MeetingError):
                    mod.delete(rec['id'])
            self.assertTrue(store.path().exists())

    def temp_file(self, rec):
        folder = spend_keep._folder(create=True)
        kind = next(kind for kind, prefix in spend_keep.KINDS.items() if rec['id'].startswith(prefix + '-'))
        fd, name = tempfile.mkstemp(dir=folder, prefix=f"{kind}-{rec['id']}.json.", suffix='.tmp')
        os.close(fd)
        os.utime(name, (self.now, self.now))
        return Path(name)

    def test_interrupted_temp_and_hidden_files_keep_original_cost_known(self):
        for mod, store_cls in CASES:
            with self.subTest(kind=mod.__name__):
                rec, store = self.make(mod, store_cls)
                before = self.runner._day()
                path = self.temp_file(rec)
                path.write_text('{interrupted')
                os.utime(path, (self.now, self.now))
                self.assertEqual(self.runner._day(), before)
                for name in ('.DS_Store', '.fictional-metadata'):
                    (path.parent / name).write_bytes(b'not a tombstone')
                self.assertTrue(store.path().exists())
                self.assertGreater(before, 0)
                self.assertEqual(self.runner._day(), before)
                self.assertEqual(self.runner.ledger({})['spent_usd'], mt.fmt(before))
                self.assertTrue(path.exists())

    def test_only_exact_atomic_temp_names_are_ignored(self):
        rec, _ = self.make(mt, mt.MeetingStore)
        path = self.temp_file(rec)
        for name in ('unrecognized.tmp', f"meeting-{rec['id']}.json.tmp",
                     f"meeting-{rec['id']}.json.abcdefg.tmp",
                     f"meeting-{rec['id']}.json.abcdefghi.tmp",
                     f"meeting-{rec['id']}.json.ABCDEFGH.tmp",
                     f"meeting-{rec['id']}.json.abcdefgh.tmp.extra",
                     'meeting-s-0123456789ab.json.abcdefgh.tmp', 'unrecognized.json'):
            with self.subTest(name=name):
                bad = path.parent / name
                bad.write_text('{broken')
                try:
                    with self.assertRaises(mt.MeetingError) as got:
                        self.runner._day()
                    self.assertEqual(got.exception.code, mt.SPEND_UNKNOWN)
                    with self.assertRaises(mt.MeetingError) as blocked:
                        self.runner._blockers(Decimal('.1'), Decimal('1'), mt.DEFAULT_LIMITS)
                    self.assertEqual(blocked.exception.code, mt.SPEND_UNKNOWN)
                    self.assertTrue(bad.exists())
                finally:
                    bad.unlink()

    def test_stale_temp_cleanup_preserves_original_and_active_temp(self):
        rec, store = self.make(mt, mt.MeetingStore)
        before = self.runner._day()
        fresh, stale, active = (self.temp_file(rec) for _ in range(3))
        old = self.now - 86401
        os.utime(fresh, (self.now, self.now))
        for path in (stale, active):
            os.utime(path, (old, old))
        with active.open('r') as out:
            fcntl.flock(out.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.runner._day(), before)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(active.exists())
        self.assertEqual(self.runner._day(), before)
        self.assertFalse(active.exists())
        self.assertTrue(store.path().exists())

    def test_writer_holds_temp_lock_until_publication(self):
        rec, store = self.make(mt, mt.MeetingStore)
        before = self.runner._day()
        replace = os.replace

        def scan_before_publish(src, dst):
            path = Path(src)
            old = self.now - 86401
            os.utime(path, (old, old))
            with path.open('r') as reader:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(reader.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.runner._day(), before)
            self.assertTrue(path.exists())
            self.assertTrue(store.path().exists())
            return replace(src, dst)

        with mock.patch.object(spend_keep.os, 'replace', side_effect=scan_before_publish):
            mt.delete(rec['id'])
        self.assertEqual(self.runner._day(), before)
        self.assertFalse(store.path().exists())

    def test_temp_cleanup_refusal_does_not_make_original_cost_unknown(self):
        rec, _ = self.make(mt, mt.MeetingStore)
        before = self.runner._day()
        path = self.temp_file(rec)
        old = self.now - 86401
        os.utime(path, (old, old))
        with mock.patch.object(Path, 'unlink', side_effect=PermissionError('fake cleanup refusal')):
            self.assertEqual(self.runner._day(), before)
        self.assertTrue(path.exists())

    def test_temp_cleanup_never_removes_symlink_hardlink_or_public_file(self):
        rec, _ = self.make(mt, mt.MeetingStore)
        before = self.runner._day()
        target = self.base / 'fictional-source'
        target.write_text('keep this')
        link, hardlink, public = (self.temp_file(rec) for _ in range(3))
        link.unlink()
        link.symlink_to(target)
        hardlink.unlink()
        os.link(target, hardlink)
        public.chmod(0o644)
        old = self.now - 86401
        for path in (target, public):
            os.utime(path, (old, old))
        self.assertEqual(self.runner._day(), before)
        self.assertTrue(link.is_symlink())
        self.assertTrue(hardlink.exists())
        self.assertTrue(public.exists())
        self.assertEqual(target.read_text(), 'keep this')

    def test_every_board_counts_kept_spend(self):
        from vbear.staffing_runner import StaffingRunner
        from vbear.chief_runner import ChiefRunner
        from vbear.memory_suggest_runner import MemorySuggestRunner
        from vbear.skillbook_suggest_runner import SkillSuggestRunner
        for mod, store_cls in CASES:
            rec, _ = self.make(mod, store_cls)
            mod.delete(rec['id'])
        for cls in (MeetingRunner, StaffingRunner, ChiefRunner, MemorySuggestRunner, SkillSuggestRunner):
            with self.subTest(board=cls.__name__):
                board = cls(clock=lambda: self.now)
                self.assertEqual(board._day(), Decimal('.185'))

    def test_delete_routes_return_409_and_ledger_keeps_cost_without_a_server(self):
        from vbear.server import make_handler
        console = mock.Mock()
        console.meeting_runner.return_value = self.runner
        console.store.conf = {}
        handler = object.__new__(make_handler(console))
        handler._json = lambda body, status=200: (status, body)
        for mod, store_cls, method, runner_attr in (
                (mt, mt.MeetingStore, '_meeting_call', 'meeting_runner'),
                (st, st.StaffingStore, '_staffing_call', 'staffing_runner'),
                (ms, ms.SuggestStore, '_suggest_call', 'memory_suggest_runner'),
                (ks, ks.SuggestStore, '_skill_suggest_call', 'skill_suggest_runner')):
            with self.subTest(kind=mod.__name__):
                rec, store = self.make(mod, store_cls, 'running')
                runner = mock.Mock()
                runner.delete.side_effect = lambda rid, m=mod: m.delete(rid)
                getattr(console, runner_attr).return_value = runner
                handler._staffing_sources = lambda conf: None
                handler._memory_suggest_sources = lambda conf: None
                handler._skill_suggest_sources = lambda conf: None
                status, body = getattr(handler, method)('delete', rec['id'])
                self.assertEqual(status, 409)
                self.assertEqual(set(body), {'code', 'error'})
                self.assertEqual(body['code'], 'running')
                self.assertTrue(store.path().exists())
        console.meeting_runner.return_value = self.runner
        # Finish the synthetic running records before deleting them.
        for mod, store_cls in CASES:
            rec, _ = self.make(mod, store_cls)
            before = handler._meeting_call('ledger')[1]['spent_usd']
            mod.delete(rec['id'])
            self.assertEqual(handler._meeting_call('ledger')[1]['spent_usd'], before)

    def test_unreadable_unsafe_and_malformed_tombstones_are_unknown(self):
        import json
        from vbear import spend_keep
        rec, _ = self.make(ms, ms.SuggestStore)
        ms.delete(rec['id'])
        path = next((self.base / 'spend-keep').glob('*.json'))
        original = path.read_text()
        bad_values = [[], {'v': 1}, {**json.loads(original), 'kind': []},
                      {**json.loads(original), 'turns': []},
                      {**json.loads(original), 'deleted_at': True}]
        for bad in bad_values:
            with self.subTest(value=bad):
                path.write_text(json.dumps(bad))
                with self.assertRaises(mt.MeetingError) as got:
                    self.runner._day()
                self.assertEqual(got.exception.code, mt.SPEND_UNKNOWN)
        path.write_text(original)
        path.chmod(0o644)
        with self.assertRaises(mt.MeetingError):
            self.runner._day()
        path.chmod(0o600)
        with mock.patch.object(spend_keep.strictjson, 'open_owned', side_effect=PermissionError('fake refusal')):
            with self.assertRaises(mt.MeetingError) as got:
                self.runner._day()
        self.assertEqual(got.exception.code, mt.SPEND_UNKNOWN)
        path.unlink()
        path.symlink_to(self.base / 'missing-fictional-file')
        with self.assertRaises(mt.MeetingError):
            self.runner._day()

    def test_next_day_no_longer_counts_and_expiry_keeps_bad_evidence(self):
        for mod, store_cls in CASES:
            rec, _ = self.make(mod, store_cls)
            mod.delete(rec['id'])
        self.now += 86400
        self.assertEqual(self.runner._day(), 0)
        path = next((self.base / 'spend-keep').glob('*.json'))
        path.write_text('{broken')
        self.now += 3 * 86400
        with mock.patch('time.time', return_value=self.now):
            with self.assertRaises(mt.MeetingError):
                self.runner._day()
        self.assertTrue(path.exists())

    def test_deletion_while_listing_a_later_kind_cannot_erase_the_cost(self):
        for mod, store_cls in ((ms, ms.SuggestStore), (ks, ks.SuggestStore)):
            with self.subTest(kind=mod.__name__):
                rec, _ = self.make(mod, store_cls)
                before = self.runner._day()
                original_ids = mod.record_ids
                removed = False

                def ids_during_delete():
                    nonlocal removed
                    if not removed:
                        removed = True
                        mod.delete(rec['id'])
                    return original_ids()

                with mock.patch.object(mod, 'record_ids', side_effect=ids_during_delete):
                    self.assertGreaterEqual(self.runner._day(), before)
