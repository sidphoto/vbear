"""v0.13 P38-2 over HTTP with the runtime daemon in a thread: the start-up page's "chat login" of Codex
(POST /api/setup/terminals {tool: codex, action: chat_login}), the chat login state in /api/setup/tools, and what
/api/chat-support says about Codex. The Codex is a stand-in file in a temporary PATH folder (it prints a made-up code to
both outputs to show that nothing it prints is kept); the login shell is a stand-in too. No real AI tool is started."""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.test_runtimed_s3 import ServerCase  # noqa: F401  (SetupCase builds on it)
from tests.test_t16_setup import CANARY, SetupCase
from vbear import ai_tool_status, config as cfg
from vbear.runtime import codex_chat_env as env, daemon as d

FAKE_CODEX = r'''#!%(py)s
import os, sys
here = os.path.dirname(os.path.realpath(__file__))
args = sys.argv[1:]
with open(os.path.join(here, "calls.log"), "a") as f:
    f.write("codex " + " ".join(args) + " | CODEX_HOME=" + os.environ.get("CODEX_HOME", "-") + "\n")
if args == ["--version"]:
    print("codex-cli " + open(os.path.join(here, "version-codex")).read().strip())
    sys.exit(0)
print(%(canary)r)
print(%(canary)r, file=sys.stderr)
if args == ["login", "status"]:
    sys.exit(int(open(os.path.join(here, "exit-codex")).read()) if os.path.exists(os.path.join(here, "exit-codex")) else 1)
if args == ["login", "status", "-c", "cli_auth_credentials_store=file"]:
    sys.exit(0 if os.path.exists(os.path.join(os.environ.get("CODEX_HOME", "/nonexistent"), "auth.json")) else 1)
sys.exit(2)
'''


def arch():
    return "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"


class ChatLoginCase(SetupCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(env, "CACHE_TTL_S", 0.0)
        patch.start()
        self.addCleanup(patch.stop)
        root = self.tmp / "policy-root"                   # no administrator policy anywhere unless a test makes one
        root.mkdir()
        self.policy_root = root
        patch = mock.patch.object(env, "POLICY_ROOT", str(root))
        patch.start()
        self.addCleanup(patch.stop)
        self.state = Path(os.path.realpath(self.home))
        self.chat_home = self.state / "codex-chat-home"

    def install_codex(self, version="0.163.0", *, release=True):
        """On the PATH (what the start-up page finds) and, with ``release``, in the vendor's own releases folder (what the
        chat pins)."""
        text = FAKE_CODEX % {"py": sys.executable, "canary": CANARY}
        (self.bindir / "version-codex").write_text(version)
        exe = self.bindir / "codex"
        exe.write_text(text)
        exe.chmod(0o700)
        if release:
            folder = self.fakehome / ".codex/packages/standalone/releases" / f"{version}-{arch()}-apple-darwin/bin"
            folder.mkdir(parents=True, exist_ok=True)
            pinned = folder / "codex"
            pinned.write_text(text.replace("os.path.dirname(os.path.realpath(__file__))", repr(str(self.bindir))))
            pinned.chmod(0o755)

    def verify(self, version="0.163.0"):
        report = self.tmp / f"report-{version}.json"
        report.write_text(json.dumps({"mode": "codex-chat", "passed": True, "codex_version": version}))
        report.chmod(0o600)
        cfg.write_private(self.state / "codex-chat-verified.json", json.dumps({"versions": {version: {
            "passed": True, "verified_at": "2026-11-06T00:00:00+0000", "report": str(report)}}}))

    def log_in_chat(self):
        env.ensure_chat_home(self.state)
        (self.chat_home / "auth.json").write_text("{}")

    def row(self):
        return self.tools()[0]["codex"]

    def raw_get(self, path):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", "X-VBear": "1"})
        r = c.getresponse()
        out = r.status, r.read().decode()
        c.close()
        return out


class ChatLoginTerminalTests(ChatLoginCase):
    def open(self, **body):
        return self.req("POST", "/api/setup/terminals", {"tool": "codex", "action": "chat_login", **body})

    def test_the_terminal_gets_the_one_fixed_line_with_the_chat_folder_and_the_folder_is_made_private(self):
        st, r = self.open()
        self.assertEqual(st, 200, r)
        line = f"CODEX_HOME={self.chat_home} codex login -c cli_auth_credentials_store=file"
        self.assertEqual(r["command"], line)
        self.assertEqual(r["session"]["setup"], {"tool": "codex", "action": "chat_login", "region": None, "command": line})
        self.assertEqual(r["session"]["kind"], "shell")
        self.assertEqual(r["session"]["argv"], [self.shell, "-l"])
        typed = self.typed_line()
        self.assertEqual((typed[0], typed[1], typed[2]), (line, "ARGV -l", "CWD " + str(self.fakehome)))
        self.assertEqual(stat.S_IMODE(self.chat_home.stat().st_mode), 0o700)
        self.assertEqual(list(self.chat_home.iterdir()), [])

    def test_it_is_not_the_reviews_folder_and_the_plain_login_line_is_unchanged(self):
        st, r = self.req("POST", "/api/setup/terminals", {"tool": "codex", "action": "login"})
        self.assertEqual((st, r["command"]), (200, "codex login"))
        self.assertFalse(self.chat_home.exists(), "only the chat login makes the chat folder")
        self.assertFalse((self.state / "codex-home").exists())

    def test_the_browser_cannot_name_a_folder_a_command_or_anything_else(self):
        for extra in ({"home": "/tmp/x"}, {"chat_home": "/tmp/x"}, {"codex_home": "/tmp/x"}, {"command": "rm -rf ~"},
                      {"env": {"CODEX_HOME": "/tmp/x"}}, {"cwd": "/"}, {"argv": ["/bin/sh"]}, {"region": "global"}):
            with self.subTest(extra=extra):
                st, r = self.open(**extra)
                self.assertEqual(st, 400, r)
        self.assertEqual(self.sessions(), [])
        self.assertFalse(self.chat_home.exists())

    def test_the_daemon_takes_no_folder_either(self):
        for extra in ({"home": "/tmp/x"}, {"chat_home": "/tmp/x"}, {"command": "x"}):
            r = d.rpc("open_setup", base=self.home, timeout=15.0, tool="codex", action="chat_login", **extra)
            self.assertFalse(r["ok"], extra)
            self.assertEqual(r["error"]["code"], "bad_request")
        self.assertEqual(self.sessions(), [])

    def test_no_other_tool_has_it(self):
        for tool in ("claude", "agy", "grok", "shared", "nope"):
            st, r = self.req("POST", "/api/setup/terminals", {"tool": tool, "action": "chat_login"})
            self.assertEqual(st, 400, (tool, r))
        self.assertEqual(self.sessions(), [])
        self.assertFalse(self.chat_home.exists())

    def test_a_folder_with_someone_elses_settings_is_not_logged_in_to(self):
        self.chat_home.mkdir(mode=0o700)
        (self.chat_home / "config.toml").write_text("model = 'x'\n")
        st, r = self.open()
        self.assertEqual(st, 400, r)
        self.assertIn("config.toml", r["error"])
        self.assertEqual(self.sessions(), [])

    def test_a_folder_that_is_a_link_or_open_to_others_is_refused(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        self.chat_home.symlink_to(elsewhere)
        self.assertEqual(self.open()[0], 400)
        self.chat_home.unlink()
        self.chat_home.mkdir()
        self.chat_home.chmod(0o755)
        self.assertEqual(self.open()[0], 400)
        self.assertEqual(stat.S_IMODE(self.chat_home.stat().st_mode), 0o755, "an existing folder is not repaired")
        self.assertEqual(self.sessions(), [])

    def test_a_hidden_tool_rule_and_the_header_rule_still_apply(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("POST", "/api/setup/terminals", body=json.dumps({"tool": "codex", "action": "chat_login"}),
                  headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        c.close()
        self.assertFalse(self.chat_home.exists())


class ChatLoginStateRowTests(ChatLoginCase):
    def test_the_codex_row_says_whether_the_chat_login_exists_and_the_others_have_no_such_field(self):
        self.install_codex()
        self.install("claude")
        tools, _ = self.tools()
        self.assertEqual(tools["codex"]["chat_login"], {"state": "not_logged_in", "problem": ""})
        self.assertNotIn("chat_login", tools["claude"])
        self.log_in_chat()
        self.assertEqual(self.row()["chat_login"], {"state": "logged_in", "problem": ""})

    def test_it_is_apart_from_the_login_of_the_persons_own_codex(self):
        self.install_codex()
        (self.bindir / "exit-codex").write_text("0")
        row = self.row()
        self.assertEqual((row["state"], row["chat_login"]["state"]), ("ready", "not_logged_in"))
        self.log_in_chat()
        (self.bindir / "exit-codex").write_text("1")
        row = self.row()
        self.assertEqual((row["state"], row["chat_login"]["state"]), ("not_logged_in", "logged_in"))

    def test_a_codex_that_is_not_installed_has_no_chat_login_state_to_ask(self):
        self.assertEqual(self.row()["chat_login"], {"state": "unknown", "problem": ""})

    def test_a_folder_with_settings_in_it_is_a_problem_in_words(self):
        self.install_codex()
        env.ensure_chat_home(self.state)
        (self.chat_home / "rules").mkdir()
        cl = self.row()["chat_login"]
        self.assertEqual(cl["state"], "folder_problem")
        self.assertIn("rules", cl["problem"])
        self.assertNotIn(str(self.state), cl["problem"])

    def test_the_status_look_makes_no_folder_and_stores_no_output(self):
        self.install_codex()
        self.row()
        self.assertFalse(self.chat_home.exists())
        for root in (self.state, self.fakehome):
            for p in root.rglob("*"):
                if p.is_file() and p.name not in ("calls.log", "codex"):
                    self.assertNotIn(CANARY.encode(), p.read_bytes(), p)
        st, raw = self.raw_get("/api/setup/tools")
        self.assertNotIn(CANARY, raw)
        self.assertNotIn(str(self.state), raw)

    def test_the_status_command_run_for_it_is_the_login_status_with_the_file_store_on_the_chat_folder(self):
        self.install_codex()
        self.log_in_chat()
        self.row()
        calls = [c for c in (self.bindir / "calls.log").read_text().splitlines() if "cli_auth_credentials_store" in c]
        self.assertEqual(calls, [f"codex login status -c cli_auth_credentials_store=file | CODEX_HOME={self.chat_home}"])


class ChatSupportTests(ChatLoginCase):
    def support(self):
        st, r = self.req("GET", "/api/chat-support")
        self.assertEqual(st, 200, r)
        return r["support"]["codex"]

    def test_not_installed(self):
        c = self.support()
        self.assertEqual((c["state"], c["installed"], c["verified"], c["logged_in"]), ("not_installed", False, False, None))

    def test_installed_but_not_verified(self):
        self.install_codex()
        c = self.support()
        self.assertEqual((c["state"], c["installed"], c["version"], c["verified"]), ("unverified", True, "0.163.0", False))
        self.assertIn("驗證", c["why"])

    def test_before_and_after_the_chat_login(self):
        self.install_codex()
        self.verify()
        c = self.support()
        self.assertEqual((c["state"], c["verified"], c["logged_in"], c["admin_policy_ok"]), ("not_logged_in", True, False, True))
        self.assertIn("讓聊天用的 Codex 登入", c["why"])
        self.log_in_chat()
        c = self.support()
        self.assertEqual((c["state"], c["logged_in"], c["why"]), ("ready", True, ""))

    def test_an_administrator_policy_blocks_it(self):
        self.install_codex()
        self.verify()
        self.log_in_chat()
        (self.policy_root / "etc" / "codex").mkdir(parents=True)
        c = self.support()
        self.assertEqual((c["state"], c["admin_policy_ok"]), ("policy", False))
        self.assertIn("/etc/codex", c["why"])

    def test_settings_in_the_chat_folder_block_it(self):
        self.install_codex()
        self.verify()
        self.log_in_chat()
        (self.chat_home / "config.toml").write_text("")
        c = self.support()
        self.assertEqual(c["state"], "folder")
        self.assertIn("config.toml", c["why"])

    def test_the_claude_part_of_the_answer_is_still_there_and_nothing_private_is_served(self):
        self.install_codex()
        self.verify()
        self.log_in_chat()
        st, raw = self.raw_get("/api/chat-support")
        self.assertEqual(st, 200)
        body = json.loads(raw)
        self.assertIn("state", body["support"])
        self.assertIn("detected", body["support"])
        for secret in (CANARY, str(self.state), str(self.fakehome), "auth.json"):
            self.assertNotIn(secret, raw)

    def test_the_list_of_chats_carries_it_too(self):
        st, r = self.req("GET", "/api/chats")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["support"]["codex"]["state"], "not_installed")


if __name__ == "__main__":
    unittest.main()
