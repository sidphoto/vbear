"""Recent costs of deleted boards (P48-5). No prompts, replies or personal data.

A tombstone is durable before the original is removed. An interrupted deletion may
count twice; it can never lower the day. Damaged evidence never expires silently.
"""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from decimal import Decimal

from . import config as cfg, meetings as mt, strictjson
from .numbers import finite_real
from .jsonstore import _fsync_dir

DIR = 'spend-keep'
KEEP = 2 * 86400
KINDS = {'meeting': 'm', 'staffing': 's', 'chief': 'cos', 'memory_suggest': 'ms', 'skill_suggest': 'ks'}
NAME_RE = re.compile(r'^(meeting-m|staffing-s|chief-cos|memory_suggest-ms|skill_suggest-ks)-[0-9a-f]{12}\.json\Z')
MAX_FILE = 1 << 20


def _unknown():
    return mt.MeetingError(mt.SPEND_UNKNOWN, '刪除紀錄的花費讀不出來，今天的花費未知；請人工檢查狀態目錄')


def _folder(create=False):
    path = cfg.state_dir() / DIR
    if create:
        cfg.ensure_state_dir()
        path.mkdir(mode=0o700, exist_ok=True)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise _unknown()
    return path


def keep(rec, per_call, kind):
    """Called under the original record's lock, before unlink. Refuse queued work too."""
    if any(t['state'] in ('queued', 'running') for t in rec['turns']):
        raise mt.MeetingError('running', '還在進行，等它結束再刪')
    now = time.time()
    turns = []
    for t in rec['turns']:
        when = t.get('ended_at') or t.get('started_at')
        if when and when >= now - KEEP:
            turns.append({'state': 'done', 'started_at': when, 'ended_at': when,
                          'evidence': {'cost_usd': format(mt.turn_cost(t, per_call(rec, t)), 'f')}})
    if not turns:
        return
    rid = rec['id']
    name = f'{kind}-{rid}.json'
    if kind not in KINDS or not NAME_RE.fullmatch(name):
        raise _unknown()
    tomb = {'v': 1, 'kind': kind, 'id': rid, 'deleted_at': now, 'turns': turns}
    try:
        folder = _folder(create=True)
        # Never replace damaged evidence left by an earlier interrupted deletion.
        if (folder / name).exists() or (folder / name).is_symlink():
            _load(folder / name)
        _write(folder / name, tomb)
    except (OSError, strictjson.ReadRefused) as exc:
        raise mt.MeetingError('storage', '無法保存刪除紀錄的花費，紀錄已保留') from exc


def _write(path, tomb):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(tomb, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _load(path):
    fd, st = strictjson.open_owned(path, max_bytes=MAX_FILE)
    try:
        if st.st_nlink != 1 or st.st_mode & 0o077:
            raise _unknown()
        raw = strictjson.read_fd(fd, MAX_FILE)
    finally:
        os.close(fd)
    parsed = strictjson.loads_object(raw, strictjson.Limits(MAX_FILE, 100000, 12, MAX_FILE))
    if not parsed.ok:
        raise _unknown()
    rec = parsed.value
    if (set(rec) != {'v', 'kind', 'id', 'deleted_at', 'turns'} or type(rec['v']) is not int or rec['v'] != 1
            or not isinstance(rec['kind'], str) or rec['kind'] not in KINDS or path.name != f"{rec['kind']}-{rec['id']}.json"
            or finite_real(rec['deleted_at']) is None
            or not isinstance(rec['turns'], list) or not rec['turns']):
        raise _unknown()
    for t in rec['turns']:
        if (not isinstance(t, dict) or set(t) != {'state', 'started_at', 'ended_at', 'evidence'}
                or t['state'] != 'done' or finite_real(t['started_at']) is None
                or t['ended_at'] != t['started_at'] or not isinstance(t['evidence'], dict)
                or set(t['evidence']) != {'cost_usd'} or mt.money(t['evidence']['cost_usd']) is None):
            raise _unknown()
    return rec


def with_kept(kind, kinds):
    """Append costs after listing their originals, once per shared day.

    Snapshot tombstones in ids(), so concurrent expiry cannot turn a listed file
    into missing evidence in load(). Originals still use their own per-call limits.
    """
    ids, load, per_call = kind
    snapshot = {}

    def all_ids():
        snapshot.clear()
        original = ids()
        try:
            try:
                folder = _folder()
            except FileNotFoundError:
                return original
            for path in sorted(folder.iterdir()):
                if not NAME_RE.fullmatch(path.name):
                    # An atomic write's temporary file is not published evidence.
                    if path.name.endswith('.tmp'):
                        continue
                    raise _unknown()
                rec = _load(path)
                if all(t['ended_at'] < time.time() - KEEP for t in rec['turns']):
                    path.unlink()
                    continue
                if rec['kind'] in kinds:
                    snapshot['keep:' + path.name] = rec
        except (OSError, strictjson.ReadRefused, ValueError, TypeError, KeyError):
            raise _unknown() from None
        return original + list(snapshot)

    def load_one(rid):
        return snapshot[rid] if rid.startswith('keep:') else load(rid)

    def limit(rec, turn):
        return Decimal(0) if 'v' in rec else per_call(rec, turn)

    return all_ids, load_one, limit
