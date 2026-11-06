"""v0.13 P38-2: the Codex that chats has its own login folder, its own pinned binary, its own verified-versions record
and its own administrator-policy list. Everything here uses a stand-in Codex in a temporary HOME; the real Codex is never
started and no real login folder is read."""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if "VBEAR_HOME" not in os.environ:
    _HOME = Path(tempfile.mkdtemp(prefix="vbear-p38-2-"))
    os.environ["HOME"] = str(_HOME)
    os.environ["VBEAR_HOME"] = str(_HOME / ".vbear")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import admin_policy, ai_tools, config as cfg  # noqa: E402
from vbear.runtime import cli_versions, codex_chat_env as env, review_codex  # noqa: E402

HOME_FOLDER = "/tmp/vbear-fake/state/codex-chat-home"


class ChatLoginLineTests(unittest.TestCase):
    def test_the_line_is_fixed_and_names_the_chat_folder_and_the_file_store(self):
        line = ai_tools.command_for("codex", "chat_login", chat_home=HOME_FOLDER)
        self.assertEqual(line, f"CODEX_HOME={HOME_FOLDER} codex login -c cli_auth_credentials_store=file")

    def test_a_folder_with_a_space_or_a_quote_is_quoted_not_split(self):
        line = ai_tools.command_for("codex", "chat_login", chat_home="/tmp/a b/it's/codex-chat-home")
        self.assertTrue(line.startswith("CODEX_HOME='/tmp/a b/it'\"'\"'s/codex-chat-home' codex login "), line)

    def test_only_codex_has_it_and_it_needs_a_plain_absolute_folder_and_no_region(self):
        for tool in ("claude", "agy", "grok", "mcode", "shared", "nope", ["codex"], None):
            self.assertIsNone(ai_tools.command_for(tool, "chat_login", chat_home=HOME_FOLDER), tool)
        self.assertIsNone(ai_tools.command_for("codex", "chat_login"))                      # no folder, no line
        self.assertIsNone(ai_tools.command_for("codex", "chat_login", "global", chat_home=HOME_FOLDER))
        for bad in ("relative/codex-chat-home", "", "/tmp/a\nrm -rf ~", "/tmp/a\x00b", "/tmp/a\tb", 5, None, ["/x"]):
            self.assertIsNone(ai_tools.command_for("codex", "chat_login", chat_home=bad), repr(bad))

    def test_the_other_actions_ignore_the_folder_and_are_unchanged(self):
        self.assertEqual(ai_tools.command_for("codex", "login", chat_home=HOME_FOLDER), "codex login")
        self.assertEqual(ai_tools.command_for("codex", "install"), "curl -fsSL https://chatgpt.com/codex/install.sh | sh")

    def test_the_action_is_listed_and_known_without_a_folder(self):
        self.assertIn("chat_login", ai_tools.SETUP_ACTIONS)
        self.assertTrue(ai_tools.action_known("codex", "chat_login"))
        self.assertTrue(ai_tools.action_known("claude", "install"))
        self.assertFalse(ai_tools.action_known("claude", "chat_login"))
        self.assertFalse(ai_tools.action_known("codex", "chat_login", "cn"))
        self.assertFalse(ai_tools.action_known("codex", "uninstall"))

    def test_the_status_command_of_the_chat_login_is_the_login_status_with_the_file_store(self):
        self.assertEqual(ai_tools.chat_login_status_args("codex"),
                         ("login", "status", "-c", "cli_auth_credentials_store=file"))
        self.assertIsNone(ai_tools.chat_login_status_args("claude"))

    def test_no_command_reaches_the_page_through_the_tool_list(self):
        for row in ai_tools.view(show_hidden=True):
            self.assertNotIn("chat_login", row)
            self.assertFalse({"install_command", "login_command", "status_command"} & set(row))


class StateCase(unittest.TestCase):
    """A temporary HOME and state folder for every test (the real ones are never touched)."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbc38-")))
        self.addCleanup(self._rm)
        self.home = self.tmp / "h"
        self.state = self.home / ".vbear"
        self.state.mkdir(parents=True, mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "VBEAR_HOME": str(self.state),
                                             "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)

    def _rm(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class VerifiedVersionsTests(StateCase):
    def record(self, version="0.163.0", *, report=None, passed=True, mode="codex-chat", rec_version=None):
        out = self.tmp / "report.json"
        if report is None:
            report = {"mode": mode, "passed": passed, "codex_version": rec_version or version}
        out.write_text(json.dumps(report))
        out.chmod(0o600)
        cfg.write_private(self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE, json.dumps({"versions": {
            version: {"passed": True, "verified_at": "2026-11-06T00:00:00+0000", "report": str(out)}}}))

    def test_nothing_is_built_in_and_the_file_name_is_its_own(self):
        self.assertEqual(cli_versions.CODEX_CHAT_VERIFIED_VERSIONS, ())
        self.assertEqual(cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE, "codex-chat-verified.json")
        self.assertEqual(cli_versions.codex_chat_verified_versions(), ())

    def test_a_version_counts_only_with_its_own_report_that_passed(self):
        self.record()
        self.assertEqual(cli_versions.codex_chat_verified_versions(), ("0.163.0",))

    def test_a_report_of_another_mode_version_or_a_failure_does_not_count(self):
        for kw in ({"mode": "chat"}, {"mode": "stream"}, {"passed": False}, {"rec_version": "0.164.0"},
                   {"report": {"mode": "codex-chat", "passed": True}},
                   {"report": {"mode": "codex-chat", "passed": True, "claude_version": "0.163.0"}}):
            with self.subTest(kw=kw):
                self.record(**kw)
                self.assertEqual(cli_versions.codex_chat_verified_versions(), (), kw)

    def test_a_missing_report_or_a_bad_version_name_does_not_count(self):
        self.record()
        Path(self.tmp / "report.json").unlink()
        self.assertEqual(cli_versions.codex_chat_verified_versions(), ())
        self.record(version="latest")
        self.assertEqual(cli_versions.codex_chat_verified_versions(), ())

    def test_the_claude_chat_record_is_not_mixed_up_with_it(self):
        self.record()
        self.assertEqual(cli_versions.chat_verified_versions(), ())

    def test_the_text_for_an_unverified_version_names_the_way_to_verify(self):
        self.assertIn("0.163.0", cli_versions.codex_chat_unverified_text("0.163.0"))
        self.assertIn("驗證", cli_versions.codex_chat_unverified_text("0.163.0"))
        self.record()
        self.assertIn("已通過的版本：0.163.0", cli_versions.codex_chat_unverified_text("0.164.0"))


class AdminPolicyTests(StateCase):
    def test_0_163_0_has_a_source_list_and_it_is_the_codex_one(self):
        self.assertIn("0.163.0", admin_policy.CODEX_SOURCES)
        self.assertEqual(admin_policy.CODEX_SOURCES["0.163.0"], admin_policy.CODEX_SOURCES["0.160.0"])

    def test_the_policy_folder_in_the_root_refuses_and_a_clean_root_passes(self):
        root = self.tmp / "root"
        root.mkdir()
        self.assertTrue(admin_policy.check_codex("0.163.0", str(root)).ok)
        (root / "etc" / "codex").mkdir(parents=True)
        check = admin_policy.check_codex("0.163.0", str(root))
        self.assertFalse(check.ok)
        self.assertEqual(check.found, ["/etc/codex"])

    def test_a_version_without_a_list_cannot_chat(self):
        self.assertFalse(admin_policy.check_codex("0.164.0", str(self.tmp)).ok)


CANARY = "FAKE-LOGIN-CODE-000-NOT-REAL"

FAKE_CODEX = r'''#!%(py)s
import os, sys, time
args = sys.argv[1:]
with open(%(log)r, "a") as f:
    f.write(" ".join(args) + " | CODEX_HOME=" + os.environ.get("CODEX_HOME", "-") + " | HOME=" + os.environ.get("HOME", "-")
            + " | KEYS=" + ",".join(sorted(os.environ)) + "\n")
if args == ["--version"]:
    print(%(version_line)r)
    sys.exit(0)
print(%(canary)r)
print(%(canary)r, file=sys.stderr)
if args == ["login", "status", "-c", "cli_auth_credentials_store=file"]:
    if os.path.exists(os.path.join(os.path.dirname(%(log)r), "slow")):
        time.sleep(30)
    sys.exit(0 if os.path.exists(os.path.join(os.environ["CODEX_HOME"], "auth.json")) else 1)
sys.exit(2)
'''


def arch() -> str:
    return "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"


class CodexCase(StateCase):
    """A stand-in Codex under the fake HOME, in the place the vendor's installer puts the real one."""

    def setUp(self):
        super().setUp()
        self.log = self.tmp / "calls.log"
        # the cache of the chat state is off here: these tests change a stand-in and look again at once
        patch = mock.patch.object(env, "CACHE_TTL_S", 0.0)
        patch.start()
        self.addCleanup(patch.stop)
        self.root = self.tmp / "root"                     # the administrator policy is looked for here, not in "/"
        self.root.mkdir()

    def install(self, version="0.163.0", version_line=None):
        folder = self.home / ".codex" / "packages" / "standalone" / "releases" / f"{version}-{arch()}-apple-darwin" / "bin"
        folder.mkdir(parents=True, exist_ok=True)
        exe = folder / "codex"
        exe.write_text(FAKE_CODEX % {"py": sys.executable, "log": str(self.log), "canary": CANARY,
                                     "version_line": version_line or f"codex-cli {version}"})
        exe.chmod(0o755)
        return exe

    def verify(self, *versions):
        report = self.tmp / "report.json"
        entries = {}
        for v in versions:
            report.write_text(json.dumps({"mode": "codex-chat", "passed": True, "codex_version": v}))
            path = self.tmp / f"report-{v}.json"
            path.write_text(report.read_text())
            path.chmod(0o600)
            entries[v] = {"passed": True, "verified_at": "2026-11-06T00:00:00+0000", "report": str(path)}
        cfg.write_private(self.state / cli_versions.LOCAL_CODEX_CHAT_VERIFIED_FILE, json.dumps({"versions": entries}))

    def login(self):
        (env.ensure_chat_home(self.state) / "auth.json").write_text("{}")

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class ChatHomeTests(CodexCase):
    def test_it_lives_in_the_state_folder_under_its_own_name_not_the_reviews(self):
        self.assertEqual(env.chat_home_path(self.state), self.state / "codex-chat-home")
        self.assertNotEqual(env.chat_home_path(self.state), review_codex.codex_home_path(self.state))

    def test_ensure_makes_a_private_empty_folder_and_leaves_one_that_is_right(self):
        path = env.ensure_chat_home(self.state)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(list(path.iterdir()), [])
        (path / "auth.json").write_text("{}")
        self.assertEqual(env.ensure_chat_home(self.state), path)
        self.assertTrue((path / "auth.json").exists())

    def test_a_wrong_mode_a_link_or_a_plain_file_is_refused_not_repaired(self):
        path = self.state / "codex-chat-home"
        path.mkdir(mode=0o755)
        path.chmod(0o755)
        with self.assertRaises(review_codex.CodexRefused) as cm:
            env.ensure_chat_home(self.state)
        self.assertEqual(cm.exception.code, "unsafe_path")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
        path.rmdir()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        path.symlink_to(elsewhere)
        with self.assertRaises(review_codex.CodexRefused):
            env.ensure_chat_home(self.state)
        path.unlink()
        path.write_text("x")
        with self.assertRaises(review_codex.CodexRefused):
            env.ensure_chat_home(self.state)

    def test_a_state_folder_kept_behind_a_link_is_resolved_once_and_the_folder_is_made_at_the_real_place(self):
        real = self.tmp / "realstate"
        real.mkdir(mode=0o700)
        link = self.tmp / "linkstate"
        link.symlink_to(real)
        path = env.ensure_chat_home(link)
        self.assertEqual(path, real / "codex-chat-home")
        self.assertTrue(path.is_dir() and not path.is_symlink())

    def test_a_config_rules_or_agents_file_makes_it_unusable_whatever_it_is(self):
        for name, make in (("config.toml", lambda p: p.write_text("")), ("rules", lambda p: p.mkdir()),
                           ("AGENTS.md", lambda p: p.write_text("be nice")),
                           ("config.toml", lambda p: p.symlink_to(self.tmp / "nowhere")),
                           ("rules", lambda p: p.write_text(""))):
            with self.subTest(name=name):
                home = env.ensure_chat_home(self.state)
                make(home / name)
                with self.assertRaises(review_codex.CodexRefused) as cm:
                    env.check_chat_home(self.state)
                self.assertEqual(cm.exception.code, "foreign_settings")
                self.assertIn(name, str(cm.exception))
                with self.assertRaises(review_codex.CodexRefused):
                    env.ensure_chat_home(self.state)
                if (home / name).is_dir() and not (home / name).is_symlink():
                    (home / name).rmdir()
                else:
                    (home / name).unlink()
        env.check_chat_home(self.state)                      # clean again

    def test_the_config_file_refusal_says_in_plain_words_it_may_be_an_older_codex_s_trust_entry_and_where_to_move_it(self):
        home = env.ensure_chat_home(self.state)
        (home / "config.toml").write_text('[projects."/x"]\ntrust_level = "trusted"\n')
        with self.assertRaises(review_codex.CodexRefused) as cm:
            env.check_chat_home(self.state)
        text = str(cm.exception)
        for word in ("config.toml", "舊版", "信任", "codex-chat-home", "移走", "不會替你刪"):
            self.assertIn(word, text)
        self.assertEqual(env.home_state(self.state)[0], "refused")
        self.assertTrue((home / "config.toml").exists(), "never removed by VBear")
        (home / "config.toml").unlink()
        (home / "rules").mkdir()
        with self.assertRaises(review_codex.CodexRefused) as cm:
            env.check_chat_home(self.state)
        self.assertNotIn("舊版", str(cm.exception), "only the config file may be an older Codex's own")

    def test_the_files_codex_itself_writes_are_fine(self):
        home = env.ensure_chat_home(self.state)
        (home / "auth.json").write_text("{}")
        (home / "sessions" / "2026" / "11").mkdir(parents=True)
        (home / "sessions" / "2026" / "11" / "rollout-x.jsonl").write_text("{}\n")
        env.check_chat_home(self.state)

    def test_over_512_mib_is_a_refusal_and_so_is_a_size_that_cannot_be_counted(self):
        self.assertEqual(env.HOME_LIMIT, 512 << 20)
        home = env.ensure_chat_home(self.state)
        (home / "big").write_bytes(b"x" * 4096)
        with mock.patch.object(env, "HOME_LIMIT", 4095):
            with self.assertRaises(review_codex.CodexRefused) as cm:
                env.check_chat_home(self.state)
        self.assertEqual(cm.exception.code, "too_big")
        with mock.patch.object(env.review_codex, "home_size", return_value=None):
            with self.assertRaises(review_codex.CodexRefused) as cm:
                env.check_chat_home(self.state)
        self.assertEqual(cm.exception.code, "too_big")
        env.check_chat_home(self.state)

    def test_a_folder_that_is_not_there_yet_is_missing_not_unsafe(self):
        self.assertEqual(env.home_state(self.state), ("missing", ""))
        env.ensure_chat_home(self.state)
        self.assertEqual(env.home_state(self.state), ("ok", ""))
        (self.state / "codex-chat-home" / "config.toml").write_text("")
        state, why = env.home_state(self.state)
        self.assertEqual(state, "refused")
        self.assertIn("config.toml", why)


class BinaryTests(CodexCase):
    def test_nothing_installed(self):
        self.assertEqual(env.installed_versions(), [])
        self.assertIsNone(env.pinned_binary())

    def test_installed_but_not_verified_is_not_pinned_yet_is_listed(self):
        self.install()
        self.assertEqual(env.installed_versions(), ["0.163.0"])
        self.assertIsNone(env.pinned_binary())

    def test_the_newest_installed_version_that_is_verified_is_pinned(self):
        for v in ("0.160.0", "0.163.0", "0.170.0"):
            self.install(v)
        self.verify("0.160.0", "0.163.0")
        binary, version = env.pinned_binary()
        self.assertEqual(version, "0.163.0")
        self.assertEqual(binary, str(self.home / ".codex/packages/standalone/releases" / f"0.163.0-{arch()}-apple-darwin/bin/codex"))
        self.assertEqual(env.installed_versions(), ["0.160.0", "0.163.0", "0.170.0"])

    def test_a_verified_version_that_is_not_installed_is_not_pinned(self):
        self.install("0.160.0")
        self.verify("0.163.0")
        self.assertIsNone(env.pinned_binary())

    def test_a_binary_that_is_a_link_or_not_executable_is_skipped_for_the_next_older_one(self):
        self.install("0.160.0")
        newer = self.install("0.163.0")
        self.verify("0.160.0", "0.163.0")
        newer.chmod(0o644)
        self.assertEqual(env.pinned_binary()[1], "0.160.0")
        newer.chmod(0o755)
        self.assertEqual(env.pinned_binary()[1], "0.163.0")
        real = newer.with_name("real")
        newer.rename(real)
        newer.symlink_to(real)
        self.assertEqual(env.pinned_binary()[1], "0.160.0")

    def test_folders_that_are_not_releases_of_this_machine_are_ignored(self):
        releases = self.home / ".codex/packages/standalone/releases"
        for name in ("0.163.0-x86_64-pc-windows", "latest", "0.163-aarch64-apple-darwin", "0.163.0-sparc-apple-darwin",
                     "../0.163.0", "0.163.0-" + arch() + "-apple-darwin.bak"):
            if "/" not in name:
                (releases / name).mkdir(parents=True, exist_ok=True)
        (releases / "stray-file").write_text("x")
        self.assertEqual(env.installed_versions(), [])


class LoginStateTests(CodexCase):
    def test_it_is_the_exit_code_of_the_status_command_with_the_chat_folder_and_nothing_else(self):
        exe = self.install()
        home = env.ensure_chat_home(self.state)
        self.assertEqual(env.login_state(str(exe), home), "not_logged_in")
        (home / "auth.json").write_text("{}")
        self.assertEqual(env.login_state(str(exe), home), "logged_in")
        line = self.calls()[-1]
        self.assertTrue(line.startswith("login status -c cli_auth_credentials_store=file | "), line)
        self.assertIn(f"CODEX_HOME={home} ", line)

    def test_codex_does_not_get_the_real_home_or_any_environment_beyond_the_fixed_ones(self):
        exe = self.install()
        home = env.ensure_chat_home(self.state)
        env.login_state(str(exe), home)
        line = self.calls()[-1]
        self.assertNotIn(f"HOME={self.home} ", line)
        keys = line.split("KEYS=")[1].split(",")
        self.assertEqual(set(keys) - {"__CF_USER_TEXT_ENCODING"}, {"PATH", "USER", "LOGNAME", "LANG", "CODEX_HOME", "HOME"}, keys)

    def test_a_status_command_that_cannot_answer_is_unknown_not_a_login(self):
        exe = self.install()
        home = env.ensure_chat_home(self.state)
        (home / "auth.json").write_text("{}")
        (self.tmp / "slow").write_text("")
        with mock.patch.object(env, "STATUS_TIMEOUT_S", 0.5):
            self.assertEqual(env.login_state(str(exe), home), "unknown")
        self.assertEqual(env.login_state(str(self.tmp / "no-such-codex"), home), "unknown")

    def test_what_the_command_prints_is_not_kept_anywhere(self):
        exe = self.install()
        home = env.ensure_chat_home(self.state)
        env.login_state(str(exe), home)
        for p in self.tmp.rglob("*"):
            if p.is_file() and p != self.log and not p.name.startswith("codex"):
                self.assertNotIn(CANARY.encode(), p.read_bytes(), p)


class StatusTests(CodexCase):
    def status(self):
        return env.status(self.state, root=str(self.root))

    def test_not_installed(self):
        st = self.status()
        self.assertEqual((st["state"], st["installed"], st["verified"], st["logged_in"]), ("not_installed", False, False, None))
        self.assertTrue(st["why"])
        self.assertEqual(self.calls(), [], "nothing was started")

    def test_installed_but_not_verified_starts_nothing_and_names_the_way_to_verify(self):
        self.install()
        st = self.status()
        self.assertEqual((st["state"], st["installed"], st["version"], st["verified"]), ("unverified", True, "0.163.0", False))
        self.assertIn("驗證", st["why"])
        self.assertEqual(self.calls(), [])

    def test_verified_but_not_logged_in_to_the_chat_folder(self):
        self.install()
        self.verify("0.163.0")
        st = self.status()
        self.assertEqual((st["state"], st["verified"], st["logged_in"], st["admin_policy_ok"]), ("not_logged_in", True, False, True))
        self.assertIn("登入", st["why"])
        self.assertFalse((self.state / "codex-chat-home").exists(), "a status look makes no folder")

    def test_logged_in_and_everything_else_in_order_is_ready(self):
        self.install()
        self.verify("0.163.0")
        self.login()
        st = self.status()
        self.assertEqual((st["state"], st["logged_in"], st["why"]), ("ready", True, ""))
        self.assertEqual(st["version"], "0.163.0")
        self.assertEqual(st["verified_versions"], ["0.163.0"])

    def test_an_administrator_policy_refuses_and_says_which_source(self):
        self.install()
        self.verify("0.163.0")
        self.login()
        (self.root / "etc" / "codex").mkdir(parents=True)
        st = self.status()
        self.assertEqual((st["state"], st["admin_policy_ok"]), ("policy", False))
        self.assertIn("/etc/codex", st["why"])

    def test_a_config_file_in_the_chat_folder_refuses(self):
        self.install()
        self.verify("0.163.0")
        self.login()
        (self.state / "codex-chat-home" / "config.toml").write_text("")
        st = self.status()
        self.assertEqual(st["state"], "folder")
        self.assertIn("config.toml", st["why"])

    def test_a_version_that_does_not_print_exactly_its_own_name_is_not_ready(self):
        self.install(version_line="codex-cli 0.163.1")
        self.verify("0.163.0")
        self.login()
        st = self.status()
        self.assertEqual(st["state"], "version_unreadable")
        self.install(version_line="hello")
        self.assertEqual(self.status()["state"], "version_unreadable")

    def test_the_answer_carries_no_path_and_no_login_output(self):
        self.install()
        self.verify("0.163.0")
        self.login()
        text = json.dumps(self.status())
        self.assertNotIn(str(self.home), text)
        self.assertNotIn(CANARY, text)
        self.assertNotIn("auth.json", text)

    def test_a_short_look_is_kept_and_forget_reads_again(self):
        self.install()
        self.verify("0.163.0")
        with mock.patch.object(env, "CACHE_TTL_S", 60.0):
            env.invalidate()
            self.assertEqual(self.status()["state"], "not_logged_in")
            n = len(self.calls())
            self.login()
            self.assertEqual(self.status()["state"], "not_logged_in")
            self.assertEqual(len(self.calls()), n)
            env.invalidate()
            self.assertEqual(self.status()["state"], "ready")
            self.assertEqual(env.status(self.state, root=str(self.root), force=True)["state"], "ready")


if __name__ == "__main__":
    unittest.main()
