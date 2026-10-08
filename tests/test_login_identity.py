"""Login fingerprints and the HMAC key (vbear/login_identity.py, design 5.1
and 2.1). Every auth.json and .claude.json here is synthetic; the real files
are never read."""

import hashlib
import hmac
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import login_identity as li
from vbear import strictjson

NAN = float("nan")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbli-")))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state = self.dir / "state"
        self.state.mkdir(mode=0o700)
        self.codex_home = self.dir / "codex-home"
        self.codex_home.mkdir(mode=0o700)

    def key(self):
        return li.create_login_key(self.state, valid_acceptances=0)

    def auth(self, data, raw: bytes | None = None):
        p = self.codex_home / "auth.json"
        if p.exists() or p.is_symlink():
            p.unlink()
        p.write_bytes(raw if raw is not None else json.dumps(data).encode())
        return p

    def claude(self, data, raw: bytes | None = None):
        p = self.dir / ".claude.json"
        if p.exists():
            p.unlink()
        p.write_bytes(raw if raw is not None else json.dumps(data).encode())
        return p


class KeyTests(Base):
    def test_created_once_owner_only_and_identified(self):
        k = self.key()
        path = self.state / li.KEY_NAME
        st = path.stat()
        self.assertEqual((stat.S_IMODE(st.st_mode), st.st_size), (0o600, 32))
        self.assertEqual(k.key_id, hashlib.sha256(path.read_bytes()).hexdigest()[:16])
        self.assertEqual(li.load_login_key(self.state).key_id, k.key_id)
        self.assertEqual(self.key().key_id, k.key_id)              # a working key is never replaced
        self.assertNotIn(k.secret.hex(), repr(k))
        self.assertEqual([p.name for p in self.state.iterdir()], [li.KEY_NAME])   # no temp left behind

    def test_not_created_while_an_acceptance_is_valid(self):
        with self.assertRaises(li.KeyUnavailable):
            li.create_login_key(self.state, valid_acceptances=1)
        self.assertFalse((self.state / li.KEY_NAME).exists())
        k = self.key()
        self.assertEqual(li.create_login_key(self.state, valid_acceptances=3).key_id, k.key_id)
        for bad in (True, -1, "0", 1.0, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                li.create_login_key(self.state, valid_acceptances=bad)

    def test_damaged_key_voids_and_is_replaced_only_on_a_new_acceptance(self):
        k = self.key()
        path = self.state / li.KEY_NAME
        damage = {
            "missing": lambda: path.unlink(),
            "short": lambda: path.write_bytes(b"x" * 31),
            "long": lambda: path.write_bytes(b"x" * 33),
            "mode": lambda: path.chmod(0o644),
            "symlink": lambda: (path.unlink(), (self.dir / "k").write_bytes(b"x" * 32), path.symlink_to(self.dir / "k")),
            "directory": lambda: (path.unlink(), path.mkdir()),
            "fifo": lambda: (path.unlink(), os.mkfifo(path)),
        }
        for name, apply in damage.items():
            with self.subTest(damage=name):
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                elif path.exists() or path.is_symlink():
                    path.unlink()
                k = self.key()
                apply()
                with self.assertRaises(li.KeyUnavailable):
                    li.load_login_key(self.state)
                with self.assertRaises(li.KeyUnavailable):
                    li.create_login_key(self.state, valid_acceptances=1)
                if name != "directory":
                    new = li.create_login_key(self.state, valid_acceptances=0)
                    self.assertNotEqual(new.key_id, k.key_id)
                    self.assertFalse((self.state / li.KEY_NAME).is_symlink())

    def test_other_owner(self):
        self.key()
        real = os.fstat

        def other(fd):
            st = real(fd)
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid + 1, st.st_gid,
                                   st.st_size, st.st_atime, st.st_mtime, st.st_ctime))
        with mock.patch("vbear.login_identity.os.fstat", other):
            with self.assertRaises(li.KeyUnavailable):
                li.load_login_key(self.state)


class EncodingTests(unittest.TestCase):
    def test_length_prefixed_and_unambiguous(self):
        m = li.encode_message(b"p", ("ab", "c"))
        self.assertEqual(m, b"p\x00" + b"\x00\x00\x00\x02ab" + b"\x00\x00\x00\x01c")
        self.assertNotEqual(m, li.encode_message(b"p", ("a", "bc")))
        self.assertNotEqual(li.encode_message(b"p", ("",)), li.encode_message(b"p", ()))
        self.assertEqual(li.encode_message(b"p", ("é",))[2:6], (2).to_bytes(4, "big"))   # UTF-8 length


class CodexTests(Base):
    def test_chatgpt_and_apikey(self):
        k = self.key()
        self.auth({"auth_mode": "chatgpt", "tokens": {"account_id": "acct-1", "id_token": "secret"}})
        a = li.codex_login_fingerprint(self.codex_home, k)
        self.assertTrue(a.ok, a.problem)
        expected = hmac.new(k.secret, li.encode_message(li.CODEX_PREFIX, ("chatgpt", "acct-1")),
                            hashlib.sha256).hexdigest()
        self.assertEqual((a.hmac, a.display, a.key_id), (expected, expected[:16], k.key_id))
        self.assertNotIn("acct-1", repr(a))
        self.auth({"auth_mode": "chatgpt", "tokens": {"account_id": "acct-2"}})
        self.assertNotEqual(li.codex_login_fingerprint(self.codex_home, k).hmac, a.hmac)
        self.auth({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test"})
        b = li.codex_login_fingerprint(self.codex_home, k)
        self.assertTrue(b.ok)
        self.assertNotEqual(b.hmac, a.hmac)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), [li.KEY_NAME])   # nothing written

    def test_unavailable(self):
        k = self.key()
        cases = [
            ({"auth_mode": "chatgpt"}, None),
            ({"auth_mode": "chatgpt", "tokens": "x"}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": ""}}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": "aé"}}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": "a\nb"}}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": "a" * 513}}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": 5}}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": True}}, None),
            ({"auth_mode": "chatgpt", "tokens": {"account_id": ["a"]}}, None),
            ({"auth_mode": "apikey"}, None),
            ({"auth_mode": "apikey", "tokens": {"account_id": "a"}}, None),
            ({"auth_mode": "other", "OPENAI_API_KEY": "k"}, None),
            ({"OPENAI_API_KEY": "k"}, None),
            ([], None),
            (None, b'{"auth_mode": "chatgpt", "auth_mode": "apikey", "OPENAI_API_KEY": "k"}'),
            (None, b'{"auth_mode": "apikey", "OPENAI_API_KEY": NaN}'),
            (None, b'{"auth_mode": "apikey", "OPENAI_API_KEY": "k"'),
            (None, b"\xff\xfe"),
            (None, b'{"auth_mode": "apikey", "OPENAI_API_KEY": "k", "x": ' + b"[" * 9 + b"]" * 9 + b"}"),
            (None, b'{"auth_mode": "apikey", "OPENAI_API_KEY": "k", "x": [' + b"1," * 1000 + b"1]}"),
            (None, b'{"auth_mode": "apikey", "OPENAI_API_KEY": "k", "pad": "' + b"x" * (64 << 10) + b'"}'),
        ]
        for data, raw in cases:
            with self.subTest(case=(repr(data) if raw is None else repr(raw[:50]))):
                self.auth(data, raw)
                r = li.codex_login_fingerprint(self.codex_home, k)
                self.assertFalse(r.ok)
                self.assertEqual(r.hmac, "")
                self.assertTrue(r.problem)

    def test_file_refusals(self):
        k = self.key()
        self.assertFalse(li.codex_login_fingerprint(self.codex_home, k).ok)          # missing
        real = self.dir / "elsewhere.json"
        real.write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "k"}))
        (self.codex_home / "auth.json").symlink_to(real)
        self.assertFalse(li.codex_login_fingerprint(self.codex_home, k).ok)          # symlink
        (self.codex_home / "auth.json").unlink()
        os.mkfifo(self.codex_home / "auth.json")
        self.assertFalse(li.codex_login_fingerprint(self.codex_home, k).ok)          # FIFO, no hang

    def test_never_raises(self):
        for home in (None, 5, "", "/no/such", "\0"):
            self.assertFalse(li.codex_login_fingerprint(home, self.key()).ok)


class ClaudeTests(Base):
    ACCOUNT = {"accountUuid": "11111111-2222-3333-4444-555555555555",
               "organizationUuid": "66666666-7777-8888-9999-000000000000"}

    def test_fingerprint_uses_only_the_two_ids(self):
        k = self.key()
        a = li.claude_login_fingerprint(self.claude({"oauthAccount": {**self.ACCOUNT, "emailAddress": "a@x"},
                                                     "projects": {"/p": {"x": 1}}}), k)
        self.assertTrue(a.ok, a.problem)
        b = li.claude_login_fingerprint(self.claude({"oauthAccount": {**self.ACCOUNT, "emailAddress": "b@y"}}), k)
        self.assertEqual(a.hmac, b.hmac)                                         # email not part of it
        c = li.claude_login_fingerprint(self.claude({"oauthAccount": {**self.ACCOUNT, "organizationUuid": "o2"}}), k)
        self.assertNotEqual(a.hmac, c.hmac)
        self.assertEqual(len(a.display), 16)
        expected = hmac.new(k.secret, li.encode_message(li.CLAUDE_PREFIX, tuple(self.ACCOUNT.values())),
                            hashlib.sha256).hexdigest()
        self.assertEqual(a.hmac, expected)

    def test_codex_and_claude_prefixes_differ(self):
        k = self.key()
        self.assertNotEqual(li.encode_message(li.CODEX_PREFIX, ("a", "b")),
                            li.encode_message(li.CLAUDE_PREFIX, ("a", "b")))

    def test_unavailable(self):
        k = self.key()
        cases = [{}, {"oauthAccount": None}, {"oauthAccount": []},
                 {"oauthAccount": {"accountUuid": self.ACCOUNT["accountUuid"]}},
                 {"oauthAccount": {**self.ACCOUNT, "accountUuid": ""}},
                 {"oauthAccount": {**self.ACCOUNT, "accountUuid": "x" * 129}},
                 {"oauthAccount": {**self.ACCOUNT, "organizationUuid": 7}},
                 {"oauthAccount": {**self.ACCOUNT, "organizationUuid": "中"}}]
        for data in cases:
            with self.subTest(data=repr(data)[:60]):
                self.assertFalse(li.claude_login_fingerprint(self.claude(data), k).ok)
        for raw in (b'{"oauthAccount": {"accountUuid": "a", "accountUuid": "b", "organizationUuid": "o"}}',
                    b'{"x": Infinity}', b"[]"):
            with self.subTest(raw=raw[:40]):
                self.assertFalse(li.claude_login_fingerprint(self.claude(None, raw), k).ok)
        self.assertFalse(li.claude_login_fingerprint(self.dir / "missing.json", k).ok)

    def test_limits_from_the_table(self):
        k = self.key()
        small = strictjson.Limits(200, 10, 3, 200)
        with mock.patch.object(strictjson, "CLAUDE_JSON", small):
            ok = self.claude({"oauthAccount": {"accountUuid": "a", "organizationUuid": "o"}})
            self.assertTrue(li.claude_login_fingerprint(ok, k).ok)
            for data in ({"oauthAccount": {"accountUuid": "a", "organizationUuid": "o"}, "pad": "x" * 300},
                         {"oauthAccount": {"accountUuid": "a", "organizationUuid": "o"}, "d": [[[[1]]]]},
                         {"oauthAccount": {"accountUuid": "a", "organizationUuid": "o"}, "n": list(range(20))}):
                with self.subTest(data=repr(data)[:40]):
                    self.assertFalse(li.claude_login_fingerprint(self.claude(data), k).ok)

    def test_size_limit_is_checked_before_reading(self):
        k = self.key()
        p = self.dir / ".claude.json"
        with open(p, "wb") as f:
            f.truncate(strictjson.CLAUDE_JSON.file_bytes + 1)                   # sparse, nothing to read
        r = li.claude_login_fingerprint(p, k)
        self.assertFalse(r.ok)
        self.assertIn("超過", r.problem)


if __name__ == "__main__":
    unittest.main()
