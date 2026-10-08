"""Which account a reviewer or executor would run as, without keeping it.

A risk acceptance (design 10) is bound to the Codex login the reviewer uses
and the Claude login the executor uses; signing in to another account must
make the acceptance stale. What is kept is only an HMAC of the identity:

  * the key is 32 random bytes in ``<state>/codex-login-key`` (0600, owned
    by this user, exactly 32 bytes); its id is the first 16 hex digits of
    its sha256 and is recorded with every acceptance;
  * the message is unambiguous: a fixed prefix, a 0 byte, then each field
    as a 4-byte big-endian UTF-8 length followed by the bytes;
  * account ids, API keys, tokens and the key itself stay in memory and are
    never written to a file, an event or a log.

Codex (design 5.1): ``<CODEX_HOME>/auth.json``, ``auth_mode`` with
``tokens.account_id`` (chatgpt) or ``OPENAI_API_KEY`` (apikey).
Claude (design 2.1): ``~/.claude.json``, ``oauthAccount.accountUuid`` and
``oauthAccount.organizationUuid``; nothing else in that file is kept.

Anything missing, malformed, unreadable or over a limit gives
"無法取得" (``Fingerprint.ok`` False); no acceptance can be built on it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import strictjson

KEY_NAME = "codex-login-key"
KEY_BYTES = 32
KEY_MODE = 0o600
CODEX_PREFIX = b"vbear-codex-login-v1"
CLAUDE_PREFIX = b"vbear-claude-login-v1"
CODEX_MODES = ("chatgpt", "apikey")
CODEX_IDENTITY_MAX = 512
CLAUDE_IDENTITY_MAX = 128
DISPLAY_DIGITS = 16


class KeyUnavailable(Exception):
    """The key is missing, damaged or unreadable: every acceptance made with
    it is void, and a new one is created only when the user accepts again."""


@dataclass(frozen=True)
class LoginKey:
    secret: bytes = b""
    key_id: str = ""

    def __repr__(self):                     # never print the secret
        return f"LoginKey(key_id={self.key_id!r})"


@dataclass(frozen=True)
class Fingerprint:
    ok: bool
    hmac: str = ""            # full HMAC-SHA256, hex; what an acceptance stores
    display: str = ""         # first 16 hex digits, for the screen
    key_id: str = ""
    problem: str = ""         # why it could not be obtained


def _key_id(secret: bytes) -> str:
    return hashlib.sha256(secret).hexdigest()[:16]


def key_path(state_dir) -> Path:
    return Path(state_dir) / KEY_NAME


def load_login_key(state_dir) -> LoginKey:
    """The existing key, checked: opened without following a symlink, a
    regular file owned by this user, mode 0600, exactly 32 bytes."""
    path = key_path(state_dir)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise KeyUnavailable("登入指紋金鑰不存在") from exc
    except OSError as exc:
        raise KeyUnavailable(f"無法開啟登入指紋金鑰（{exc.strerror or type(exc).__name__}）") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise KeyUnavailable("登入指紋金鑰不是一般檔案")
        if st.st_uid != os.geteuid():
            raise KeyUnavailable("登入指紋金鑰不是目前的使用者擁有")
        if stat.S_IMODE(st.st_mode) != KEY_MODE:
            raise KeyUnavailable("登入指紋金鑰的權限不是 0600")
        if st.st_size != KEY_BYTES:
            raise KeyUnavailable("登入指紋金鑰的長度不對")
        try:
            secret = strictjson.read_fd(fd, KEY_BYTES)
        except strictjson.ReadRefused as exc:
            raise KeyUnavailable("登入指紋金鑰的長度不對") from exc
        if len(secret) != KEY_BYTES:
            raise KeyUnavailable("登入指紋金鑰的長度不對")
    finally:
        os.close(fd)
    return LoginKey(secret, _key_id(secret))


def create_login_key(state_dir, *, valid_acceptances: int) -> LoginKey:
    """A new key, written atomically. Only when no acceptance is still valid
    (design 5.1): with a working key that is never the case unless nothing
    was accepted yet, and then the working key is returned unchanged; a key
    is never swapped behind an acceptance that relies on it. When the key is
    missing or damaged, every acceptance made with it is already void
    (their key id can no longer match), so the caller passes 0 and a new key
    replaces the unusable one."""
    if not isinstance(valid_acceptances, int) or isinstance(valid_acceptances, bool) or valid_acceptances < 0:
        raise ValueError("valid_acceptances 必須是非負整數")
    try:
        existing = load_login_key(state_dir)
    except KeyUnavailable:
        existing = None
    if existing is not None:
        return existing
    if valid_acceptances:
        raise KeyUnavailable("還有有效的接受時不能建立新的登入指紋金鑰")
    directory = Path(state_dir)
    secret = os.urandom(KEY_BYTES)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=KEY_NAME + ".", suffix=".tmp")
    try:
        os.fchmod(fd, KEY_MODE)
        view = memoryview(secret)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, key_path(directory))
    except BaseException:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return load_login_key(directory)


def encode_message(prefix: bytes, fields) -> bytes:
    """``prefix`` + 0 byte + for each field: 4-byte big-endian UTF-8 length
    and the bytes. Distinct field lists never encode to the same bytes."""
    out = bytearray(prefix)
    out.append(0)
    for field in fields:
        data = field.encode("utf-8")
        out += len(data).to_bytes(4, "big")
        out += data
    return bytes(out)


def _identity_ok(value, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= limit
            and all(0x20 <= ord(ch) <= 0x7E for ch in value))


def _fingerprint(key: LoginKey, prefix: bytes, fields) -> Fingerprint:
    digest = hmac.new(key.secret, encode_message(prefix, fields), hashlib.sha256).hexdigest()
    return Fingerprint(True, digest, digest[:DISPLAY_DIGITS], key.key_id)


def codex_login_fingerprint(codex_home, key: LoginKey) -> Fingerprint:
    """From ``<codex_home>/auth.json``. Never raises."""
    try:
        parsed = strictjson.load_owned_object(Path(codex_home) / "auth.json", strictjson.AUTH_JSON)
        if not parsed.ok:
            return Fingerprint(False, problem=f"auth.json：{parsed.problem}")
        data = parsed.value
        mode = data.get("auth_mode")
        if mode == "chatgpt":
            tokens = data.get("tokens")
            identity = tokens.get("account_id") if isinstance(tokens, dict) else None
        elif mode == "apikey":
            identity = data.get("OPENAI_API_KEY")
        else:
            return Fingerprint(False, problem="auth.json 的 auth_mode 不是 chatgpt 或 apikey")
        del data, parsed
        if not _identity_ok(identity, CODEX_IDENTITY_MAX):
            return Fingerprint(False, problem="auth.json 缺少可用的帳號識別值")
        return _fingerprint(key, CODEX_PREFIX, (mode, identity))
    except Exception as exc:
        return Fingerprint(False, problem=f"無法取得（{type(exc).__name__}）")


def claude_login_fingerprint(claude_json, key: LoginKey) -> Fingerprint:
    """From ``~/.claude.json`` (the path is passed in). Never raises."""
    try:
        parsed = strictjson.load_owned_object(Path(claude_json), strictjson.CLAUDE_JSON)
        if not parsed.ok:
            return Fingerprint(False, problem=f".claude.json：{parsed.problem}")
        account = parsed.value.get("oauthAccount")
        del parsed
        if not isinstance(account, dict):
            return Fingerprint(False, problem=".claude.json 沒有 claude.ai 登入資料")
        uuid, org = account.get("accountUuid"), account.get("organizationUuid")
        del account
        if not (_identity_ok(uuid, CLAUDE_IDENTITY_MAX) and _identity_ok(org, CLAUDE_IDENTITY_MAX)):
            return Fingerprint(False, problem=".claude.json 缺少可用的帳號識別值")
        return _fingerprint(key, CLAUDE_PREFIX, (uuid, org))
    except Exception as exc:
        return Fingerprint(False, problem=f"無法取得（{type(exc).__name__}）")
