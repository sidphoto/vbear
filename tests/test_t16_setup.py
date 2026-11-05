"""v0.12 task 3: the start-up page's server side (status of each AI tool, the "I have logged in" mark, the install and
login terminals).

Over HTTP with the runtime daemon in a thread (tests/test_runtimed_s3.ServerCase). Each AI tool is a stand-in file named
after it in a temporary folder: it prints its version in the form the vendor's does, and answers the status command with
an exit code the test sets (it also prints a made-up code to both outputs, to show nothing of that is kept). The login
shell is a stand-in that writes the first line it is typed to a file. No AI tool is started, nothing is installed and
nothing leaves this computer.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_runtimed_s3 import ServerCase
from vbear import ai_tool_status, ai_tools, config as cfg
from vbear.runtime import daemon as d

CANARY = "FAKE-LOGIN-CODE-000-NOT-REAL"

VERSION_LINES = {
    "claude": "2.1.318 (Claude Code)",
    "codex": "codex-cli 0.163.0",
    "agy": "1.5.0",
    "grok": "grok 0.2.101 (5bc4b5dfadcf)",
    "mcode": "0.5.2",
}

FAKE_TOOL = r'''#!%(py)s
import os, sys
here = os.path.dirname(os.path.realpath(__file__))
name = %(name)r
with open(os.path.join(here, "calls.log"), "a") as f:
    f.write(name + " " + " ".join(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if args == ["--version"]:
    line = open(os.path.join(here, "version-" + name)).read() if os.path.exists(os.path.join(here, "version-" + name)) else %(version)r
    print(line)
    sys.exit(0)
print(%(canary)r)
print(%(canary)r, file=sys.stderr)
status = {"claude": ["auth", "status"], "codex": ["login", "status"]}.get(name)
if args == status:
    code_file = os.path.join(here, "exit-" + name)
    sys.exit(int(open(code_file).read()) if os.path.exists(code_file) else 1)
sys.exit(2)
'''

FAKE_SHELL = r'''#!%(py)s
import os, sys, time
with open(%(out)r, "w") as f:
    f.write(sys.stdin.readline())
    f.write("ARGV " + " ".join(sys.argv[1:]) + "\n")
    f.write("CWD " + os.getcwd() + "\n")
time.sleep(600)
'''


class SetupCase(ServerCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(os.path.realpath(self.tmp))
        self.fakehome = self.tmp / "home"
        self.fakehome.mkdir()
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        self.env2 = mock.patch.dict(os.environ, {"HOME": str(self.fakehome), "PATH": f"{self.bindir}:/usr/bin:/bin"})
        self.env2.start()
        # no real AI tool of this machine may be found, whatever is installed in the usual system folders
        self.syspath = mock.patch.object(d, "SYSTEM_EXTRA_PATH", ())
        self.syspath.start()
        self.typed = self.tmp / "typed.txt"
        shell = self.tmp / "fakeshell"
        shell.write_text(FAKE_SHELL % {"py": sys.executable, "out": str(self.typed)})
        shell.chmod(0o700)
        self.shell_patch = mock.patch("vbear.runtime.daemon.login_shell", return_value=str(shell))
        self.shell_patch.start()
        self.shell = str(shell)

    def tearDown(self):
        for s in self.sessions():
            try:
                d.rpc("close", base=self.home, session_id=s["session_id"], timeout=15.0)
            except OSError:
                pass
        self.shell_patch.stop()
        self.syspath.stop()
        self.env2.stop()
        super().tearDown()

    # --- stand-ins ---
    def install(self, name, folder=None, version=None):
        folder = Path(folder) if folder else self.bindir
        folder.mkdir(parents=True, exist_ok=True)
        exe = folder / name
        exe.write_text(FAKE_TOOL % {"py": sys.executable, "name": name, "version": VERSION_LINES[name] if version is None else version,
                                    "canary": CANARY})
        exe.chmod(0o700)
        return folder

    def set_exit(self, name, code, folder=None):
        (Path(folder) if folder else self.bindir).joinpath("exit-" + name).write_text(str(code))

    def calls(self):
        p = self.bindir / "calls.log"
        return p.read_text().splitlines() if p.exists() else []

    # --- requests ---
    def tools(self, **kw):
        st, r = self.req("GET", "/api/setup/tools", **kw)
        self.assertEqual(st, 200, r)
        return {row["id"]: row for row in r["tools"]}, r

    def sessions(self):
        try:
            return d.rpc("list", base=self.home, timeout=15.0)["result"]["sessions"]
        except OSError:
            return []

    def typed_line(self):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            try:
                text = self.typed.read_text()
                if text.count("\n") >= 3:
                    return text.splitlines()
            except OSError:
                pass
            time.sleep(0.03)
        self.fail("the stand-in shell was never typed a line")


class StateTests(SetupCase):
    def test_nothing_installed_every_listed_tool_says_not_installed(self):
        tools, body = self.tools()
        self.assertEqual(list(tools), ["claude", "codex", "agy", "grok"])          # MCODE is hidden until it is switched on
        for row in tools.values():
            self.assertEqual((row["installed"], row["state"]), (False, "not_installed"), row)
            self.assertIsNone(row["version"])
            self.assertTrue(row["blurb"])
        self.assertIs(body["any_ready"], False)
        self.assertIs(body["setup_done"], False)

    def test_installed_but_not_logged_in_claude_and_codex_follow_their_status_command(self):
        for name in ("claude", "codex", "agy", "grok"):
            self.install(name)
        tools, _ = self.tools()
        for name in ("claude", "codex", "agy", "grok"):
            self.assertEqual((tools[name]["installed"], tools[name]["state"]), (True, "not_logged_in"), name)
            self.assertEqual(tools[name]["version"], VERSION_LINES[name].split(" ")[0 if name in ("claude", "agy") else 1])
        self.assertEqual((tools["claude"]["login_by"], tools["agy"]["login_by"]), ("status", "mark"))
        self.assertIs(tools["claude"]["can_mark"], False)
        self.assertIs(tools["agy"]["can_mark"], True)
        # the status command was run for claude and codex only, with the words the registry holds
        calls = self.calls()
        self.assertIn("claude auth status", calls)
        self.assertIn("codex login status", calls)
        self.assertNotIn("agy login status", calls)
        self.assertFalse([c for c in calls if c.startswith(("agy ", "grok ")) and "--version" not in c], calls)

    def test_logged_in_means_the_status_commands_exit_code_is_zero_and_nothing_else(self):
        self.install("claude")
        self.install("codex")
        self.set_exit("claude", 0)
        self.set_exit("codex", 3)
        tools, body = self.tools()
        self.assertEqual((tools["claude"]["state"], tools["claude"]["login"]), ("ready", "logged_in"))
        self.assertEqual((tools["codex"]["state"], tools["codex"]["login"]), ("not_logged_in", "not_logged_in"))
        self.assertIs(body["any_ready"], True)
        self.set_exit("codex", 0)
        self.assertEqual(self.tools()[0]["codex"]["state"], "ready")

    def test_a_status_command_that_cannot_answer_is_not_a_login(self):
        self.install("claude")
        self.set_exit("claude", 0)
        with mock.patch.object(ai_tool_status, "STATUS_TIMEOUT_S", 0.4):
            slow = self.bindir / "claude"
            slow.write_text(slow.read_text().replace("if args == status:", "if args == status:\n    import time; time.sleep(5)"))
            tools, _ = self.tools()
        self.assertEqual(tools["claude"]["state"], "not_logged_in")
        self.assertEqual(tools["claude"]["login"], "unknown")

    def test_the_mark_is_the_only_evidence_for_agy_grok_and_mcode(self):
        for name in ("agy", "grok"):
            self.install(name)
        st, r = self.req("POST", "/api/setup/tools/agy/marker", {"done": True})
        self.assertEqual(st, 200, r)
        tools, body = self.tools()
        self.assertEqual((tools["agy"]["state"], tools["agy"]["login"]), ("ready", "marked"))
        self.assertIsNotNone(tools["agy"]["marked_at"])
        self.assertEqual((tools["grok"]["state"], tools["grok"]["login"]), ("not_logged_in", "not_marked"))
        self.assertIs(body["any_ready"], True)
        st, r = self.req("POST", "/api/setup/tools/agy/marker", {"done": False})
        self.assertEqual(st, 200, r)
        tools, _ = self.tools()
        self.assertEqual(tools["agy"]["state"], "not_logged_in")
        self.assertIsNone(tools["agy"]["marked_at"])

    def test_a_mark_does_not_make_a_tool_that_is_not_installed_ready(self):
        self.req("POST", "/api/setup/tools/grok/marker", {"done": True})
        tools, _ = self.tools()
        self.assertEqual(tools["grok"]["state"], "not_installed")
        self.install("grok")
        self.assertEqual(self.tools()[0]["grok"]["state"], "ready")

    def test_only_the_tools_without_a_status_command_can_be_marked(self):
        for name, code in (("claude", 400), ("codex", 400), ("shared", 404), ("nope", 404)):
            st, r = self.req("POST", f"/api/setup/tools/{name}/marker", {"done": True})
            self.assertEqual(st, code, (name, r))
        for bad in ({}, {"done": "yes"}, {"done": 1}, {"done": True, "x": 1}):
            st, r = self.req("POST", "/api/setup/tools/agy/marker", bad)
            self.assertEqual(st, 400, (bad, r))

    def test_the_marker_file_holds_only_the_tool_id_and_the_time(self):
        self.req("POST", "/api/setup/tools/agy/marker", {"done": True})
        self.req("POST", "/api/setup/tools/grok/marker", {"done": True})
        files = [p for p in Path(os.environ["VBEAR_HOME"]).glob("*marks*.json")]
        self.assertEqual(len(files), 1, files)
        data = json.loads(files[0].read_text())
        self.assertEqual(sorted(data), ["agy", "grok"])
        for entry in data.values():
            self.assertEqual(list(entry), ["at"])
            self.assertIsInstance(entry["at"], float)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)

    def test_a_version_that_cannot_be_read_is_not_installed(self):
        for name, version in (("claude", "hello"), ("codex", "1.2.3"), ("agy", "v1.5.0"), ("grok", ""), ("mcode", "mcode 0.5.2")):
            self.install(name, version=version)
        self.req("POST", "/api/config", {"show_mcode": True})
        tools, _ = self.tools()
        for name in ("claude", "codex", "agy", "grok", "mcode"):
            self.assertEqual((tools[name]["installed"], tools[name]["state"]), (False, "not_installed"), name)
            self.assertEqual(tools[name]["install_problem"], "version_unreadable", name)

    def test_the_vendors_own_folders_are_searched(self):
        self.install("grok", folder=self.fakehome / ".grok" / "bin")
        self.install("agy", folder=self.fakehome / ".local" / "bin")
        tools, _ = self.tools()
        self.assertTrue(tools["grok"]["installed"])
        self.assertTrue(tools["agy"]["installed"])

    def test_mcode_is_listed_only_while_it_is_switched_on(self):
        self.install("mcode")
        self.assertNotIn("mcode", self.tools()[0])
        st, _ = self.req("POST", "/api/config", {"show_mcode": True})
        self.assertEqual(st, 200)
        tools, _ = self.tools()
        self.assertEqual(list(tools), ["claude", "codex", "agy", "grok", "mcode"])
        self.assertEqual(tools["mcode"]["state"], "not_logged_in")
        self.assertEqual([r["id"] for r in tools["mcode"]["login_regions"]], ["global", "cn"])
        self.assertEqual([r["label"] for r in tools["mcode"]["login_regions"]], ["國際區", "中國區"])
        self.req("POST", "/api/config", {"show_mcode": False})
        self.assertNotIn("mcode", self.tools()[0])

    def test_the_status_output_is_never_kept_or_served(self):
        self.install("claude")
        self.install("codex")
        self.set_exit("claude", 0)
        st, raw = self.raw_get("/api/setup/tools")
        self.assertEqual(st, 200)
        self.assertNotIn(CANARY, raw)
        self.req("POST", "/api/setup/settle", {})
        for root in (Path(os.environ["VBEAR_HOME"]), self.fakehome):
            for p in root.rglob("*"):
                if p.is_file():
                    self.assertNotIn(CANARY.encode(), p.read_bytes(), p)

    def raw_get(self, path):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", "X-VBear": "1"})
        r = c.getresponse()
        out = r.status, r.read().decode()
        c.close()
        return out

    def test_the_login_folders_of_the_tools_are_never_opened(self):
        locked = []
        for name in (".claude", ".codex", ".gemini", ".config"):
            p = self.fakehome / name
            p.mkdir()
            (p / "auth.json").write_text("{}")
            p.chmod(0)
            locked.append(p)
        try:
            for name in ("claude", "codex", "agy"):
                self.install(name)
            self.set_exit("claude", 0)
            tools, _ = self.tools()
            self.assertEqual(tools["claude"]["state"], "ready")
        finally:
            for p in locked:
                p.chmod(0o700)
        src = Path(ai_tool_status.__file__).read_text()
        for word in (".claude", ".codex", ".gemini", "auth.json", ".config", "keychain", "credentials"):
            self.assertNotIn(word, src, word)

    def test_the_page_needs_the_console_header_to_write(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("POST", "/api/setup/terminals", body=json.dumps({"tool": "claude", "action": "install"}),
                  headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        c.close()
        self.assertEqual(self.sessions(), [])


class TerminalTests(SetupCase):
    def open(self, **body):
        return self.req("POST", "/api/setup/terminals", body)

    def test_each_tool_and_action_types_its_own_fixed_line_into_a_login_shell(self):
        cases = [("claude", "install", None, "curl -fsSL https://claude.ai/install.sh | bash"),
                 ("claude", "login", None, "claude auth login"),
                 ("codex", "install", None, "curl -fsSL https://chatgpt.com/codex/install.sh | sh"),
                 ("codex", "login", None, "codex login"),
                 ("agy", "install", None, "curl -fsSL https://antigravity.google/cli/install.sh | bash"),
                 ("agy", "login", None, "agy"),
                 ("grok", "install", None, "curl -fsSL https://x.ai/cli/install.sh | bash"),
                 ("grok", "login", None, "grok login")]
        self.req("POST", "/api/config", {"show_mcode": True})
        cases += [("mcode", "install", None, "curl -fsSL https://filecdn.minimax.chat/public/install.sh | bash"),
                  ("mcode", "login", "global", "mcode login --region global"),
                  ("mcode", "login", "cn", "mcode login --region cn")]
        for tool, action, region, line in cases:
            with self.subTest(tool=tool, action=action, region=region):
                if self.typed.exists():
                    self.typed.unlink()
                body = {"tool": tool, "action": action}
                if region:
                    body["region"] = region
                st, r = self.open(**body)
                self.assertEqual(st, 200, r)
                self.assertEqual(r["command"], line)
                self.assertEqual(r["session"]["setup"], {"tool": tool, "action": action, "region": region, "command": line})
                self.assertEqual(r["session"]["kind"], "shell")
                self.assertEqual(r["session"]["argv"], [self.shell, "-l"])
                typed = self.typed_line()
                self.assertEqual(typed[0], line)
                self.assertEqual(typed[1], "ARGV -l")
                self.assertEqual(typed[2], "CWD " + str(self.fakehome))
                d.rpc("close", base=self.home, session_id=r["session"]["session_id"], timeout=15.0)

    def test_the_terminal_is_listed_with_which_tool_and_what_it_is_for(self):
        st, r = self.open(tool="grok", action="login")
        self.assertEqual(st, 200, r)
        panes = self.console.runtime.list_sessions()["panes"]
        mine = [p for p in panes if p["pane_id"] == r["session"]["session_id"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["kind"], "shell")
        self.assertEqual(mine[0]["setup"], {"tool": "grok", "action": "login", "region": None, "command": "grok login"})
        plain = [p for p in panes if p["pane_id"] != r["session"]["session_id"]]
        self.assertEqual(plain, [])

    def test_the_browser_cannot_name_a_command_a_folder_or_anything_else(self):
        for extra in ({"command": "rm -rf ~"}, {"argv": ["/bin/sh"]}, {"cwd": "/"}, {"env": {"PATH": "/x"}}, {"line": "x"},
                      {"kind": "shell"}, {"shell": "/bin/sh"}, {"setup": {"tool": "claude"}}):
            with self.subTest(extra=extra):
                st, r = self.open(tool="claude", action="install", **extra)
                self.assertEqual(st, 400, r)
        self.assertEqual(self.sessions(), [])

    def test_only_a_listed_tool_and_a_listed_action_open_a_terminal(self):
        bad = [{}, {"tool": "claude"}, {"action": "install"}, {"tool": "claude", "action": "uninstall"},
               {"tool": "claude", "action": "install; rm -rf ~"}, {"tool": "shared", "action": "install"},
               {"tool": "nope", "action": "install"}, {"tool": ["claude"], "action": "install"},
               {"tool": "claude", "action": ["install"]}, {"tool": "claude", "action": "login", "region": "global"},
               {"tool": "claude", "action": "install", "region": "cn"}, {"tool": 5, "action": 6}]
        for body in bad:
            with self.subTest(body=body):
                st, r = self.open(**body)
                self.assertEqual(st, 400, r)
        self.assertEqual(self.sessions(), [])

    def test_mcode_needs_a_region_and_the_switch(self):
        st, r = self.open(tool="mcode", action="install")
        self.assertEqual(st, 400, r)
        self.assertIn("顯示 MCODE", r["error"])
        self.req("POST", "/api/config", {"show_mcode": True})
        for body in ({"tool": "mcode", "action": "login"}, {"tool": "mcode", "action": "login", "region": "mars"},
                     {"tool": "mcode", "action": "login", "region": "GLOBAL"}):
            st, r = self.open(**body)
            self.assertEqual(st, 400, (body, r))
        self.assertEqual(self.sessions(), [])

    def test_the_size_can_be_given_but_only_as_numbers(self):
        st, r = self.open(tool="claude", action="install", cols=100, rows=30)
        self.assertEqual(st, 200, r)
        self.assertEqual((r["session"]["cols"], r["session"]["rows"]), (100, 30))
        st, r = self.open(tool="claude", action="install", cols="wide")
        self.assertEqual(st, 400, r)

    def test_the_existing_routes_still_cannot_do_this_for_the_browser(self):
        st, r = self.req("POST", "/api/native/terminals", {"cwd": "~", "command": "claude auth login"})
        self.assertEqual(st, 400, r)
        st, r = self.req("POST", "/api/native/terminals", {"cwd": "~", "setup": {"tool": "claude", "action": "install"}})
        self.assertEqual(st, 400, r)

    def test_the_daemon_takes_no_line_only_a_tool_and_an_action(self):
        base = {"tool": "claude", "action": "install"}
        for extra in ({"command": "x"}, {"argv": ["/bin/sh"]}, {"line": "x"}, {"cwd": "/"}):
            r = d.rpc("open_setup", base=self.home, timeout=15.0, **base, **extra)
            self.assertFalse(r["ok"], extra)
            self.assertEqual(r["error"]["code"], "bad_request")
        for bad in ({"tool": "shared", "action": "install"}, {"tool": "claude", "action": "format"},
                    {"tool": "mcode", "action": "login"}, {"tool": "claude", "action": "install", "region": "cn"}):
            r = d.rpc("open_setup", base=self.home, timeout=15.0, **bad)
            self.assertFalse(r["ok"], bad)
        r = d.rpc("open", base=self.home, timeout=15.0, argv=["/bin/sh"], cwd=str(self.fakehome), kind="setup")
        self.assertFalse(r["ok"])
        self.assertEqual(self.sessions(), [])


class SettleTests(SetupCase):
    """The first-time and the upgrade rule: the person is sent to the start-up page unless a tool is already ready."""

    def conf(self):
        return self.req("GET", "/api/config")[1]["config"]

    def test_the_marks_start_false(self):
        c = self.conf()
        self.assertIs(c["setup_done"], False)
        self.assertIs(c["setup_notice"], False)

    def test_nothing_ready_leaves_the_person_in_the_start_up(self):
        st, r = self.req("POST", "/api/setup/settle", {})
        self.assertEqual(st, 200, r)
        self.assertEqual((r["setup_done"], r["setup_notice"], r["upgraded"]), (False, False, False))
        self.assertIs(self.conf()["setup_done"], False)

    def test_a_ready_tool_already_there_counts_as_done_and_says_so_once(self):
        self.install("claude")
        self.set_exit("claude", 0)
        st, r = self.req("POST", "/api/setup/settle", {})
        self.assertEqual((r["setup_done"], r["setup_notice"], r["upgraded"]), (True, True, True))
        self.assertEqual((self.conf()["setup_done"], self.conf()["setup_notice"]), (True, True))
        st, r = self.req("POST", "/api/setup/settle", {})                    # asked again: nothing new
        self.assertEqual((r["setup_done"], r["setup_notice"], r["upgraded"]), (True, True, False))
        st, r = self.req("POST", "/api/config", {"setup_notice": False})
        self.assertEqual(st, 200, r)
        st, r = self.req("POST", "/api/setup/settle", {})
        self.assertEqual((r["setup_done"], r["setup_notice"], r["upgraded"]), (True, False, False))

    def test_a_person_who_finished_is_not_touched_again(self):
        self.req("POST", "/api/config", {"setup_done": True})
        self.install("claude")
        self.set_exit("claude", 0)
        st, r = self.req("POST", "/api/setup/settle", {})
        self.assertEqual((r["setup_done"], r["setup_notice"], r["upgraded"]), (True, False, False))
        self.assertEqual(self.calls(), [])                                   # and no tool was even asked

    def test_the_two_marks_must_be_real_booleans(self):
        for key in ("setup_done", "setup_notice"):
            for bad in ("yes", 1, None):
                st, r = self.req("POST", "/api/config", {key: bad})
                self.assertEqual(st, 400, (key, bad, r))
            self.assertEqual(self.req("POST", "/api/config", {key: True})[0], 200)

    def test_a_hidden_tool_that_is_switched_off_does_not_count(self):
        self.install("mcode")
        self.req("POST", "/api/setup/tools/mcode/marker", {"done": True})   # refused: it is not listed
        st, r = self.req("POST", "/api/setup/settle", {})
        self.assertEqual(r["setup_done"], False)


class RegistryRowTests(unittest.TestCase):
    def test_the_report_leaves_out_the_commands(self):
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-vbear-home"}), \
                mock.patch.object(d, "SYSTEM_EXTRA_PATH", ()):
            rows = ai_tool_status.report({}, marks={})
        self.assertEqual([r["id"] for r in rows], ["claude", "codex", "agy", "grok"])
        blob = json.dumps(rows)
        for word in ("curl", "install.sh", "auth login", "auth status"):
            self.assertNotIn(word, blob)

    def test_the_version_pattern_reads_the_first_line_only(self):
        self.assertEqual(ai_tool_status.parse_version("claude", "2.1.318 (Claude Code)\n"), "2.1.318")
        self.assertEqual(ai_tool_status.parse_version("grok", "grok 0.2.101 (5bc4b5dfadcf)\nextra\n"), "0.2.101")
        self.assertIsNone(ai_tool_status.parse_version("claude", "banner\n2.1.318 (Claude Code)\n"))
        self.assertIsNone(ai_tool_status.parse_version("claude", ""))
        self.assertIsNone(ai_tool_status.parse_version("shared", "1.2.3"))
        self.assertIsNone(ai_tool_status.parse_version("claude", "9" * 5000))


if __name__ == "__main__":
    unittest.main()
