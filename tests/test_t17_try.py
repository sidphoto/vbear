"""v0.12 task 4: 「試一下」 (try it) on the start-up page, and the short cache of the tools' state.

Over HTTP with the runtime daemon in a thread (tests/test_runtimed_s3.ServerCase), as test_t16_setup does. Each AI tool is a
stand-in file named after it: it records the argv it was started with, the folder it was started in, the few environment
names it saw and what came on its stdin; what it does is set by a file next to it (mode-<name>). No AI tool is started,
nothing is installed and nothing leaves this computer. Every reply a stand-in prints is made up.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests.test_t16_setup import CANARY, VERSION_LINES, SetupCase
from vbear import ai_tool_status, config as cfg, setup_try, try_spend

REPLY = "FAKE-MODEL-REPLY-777-NOT-REAL"

TRY_TOOL = r'''#!%(py)s
import json, os, subprocess, sys, time
here = os.path.dirname(os.path.realpath(__file__))
name = %(name)r
args = sys.argv[1:]
def mode():
    p = os.path.join(here, "mode-" + name)
    return open(p).read().strip() if os.path.exists(p) else "ok"
if args == ["--version"]:
    with open(os.path.join(here, "calls.log"), "a") as f:
        f.write(name + " --version\n")
    print(%(version)r)
    sys.exit(0)
status = {"claude": ["auth", "status"], "codex": ["login", "status"]}.get(name)
if args == status:
    with open(os.path.join(here, "calls.log"), "a") as f:
        f.write(name + " " + " ".join(args) + "\n")
    sys.exit(0)
stdin = sys.stdin.read()
with open(os.path.join(here, "tries.jsonl"), "a") as f:
    f.write(json.dumps({"tool": name, "argv": args, "cwd": os.getcwd(), "env": sorted(os.environ), "stdin": stdin,
                        "home": os.environ.get("HOME"), "ppid_group": os.getpgrp() == os.getpid()}) + "\n")
m = mode()
if m == "fail":
    print("Not logged in. " + %(canary)r, file=sys.stderr)
    sys.exit(1)
if m == "empty":
    sys.exit(0)
if m == "huge":
    sys.stdout.write("x" * (3 << 20))
    sys.exit(0)
if m == "hang" or m == "child":
    if m == "child":
        kid = subprocess.Popen(["sleep", "60"])
        with open(os.path.join(here, "child.pid"), "w") as f:
            f.write(str(kid.pid))
    time.sleep(120)
    sys.exit(0)
if name == "claude":
    out = {"type": "result", "is_error": False, "result": %(reply)r, "session_id": "FAKE-SESSION-ID"}
    if m.startswith("cost:"):
        out["total_cost_usd"] = float(m.split(":")[1])
    if m == "errorjson":
        out["is_error"] = True
    if m == "notjson":
        print("this is not json")
        sys.exit(0)
    print(json.dumps(out))
else:
    print(%(reply)r)
sys.exit(0)
'''

EXPECTED_ARGV = {
    "claude": ["-p", "--safe-mode", "--setting-sources", "", "--tools", "", "--strict-mcp-config", "--mcp-config",
               '{"mcpServers":{}}', "--model", "claude-haiku-5-5", "--output-format", "json", "--max-budget-usd", "0.02",
               "--no-session-persistence"],
    "codex": ["--ask-for-approval", "never", "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
              "--ephemeral", "--sandbox", "read-only", "-c", 'web_search="disabled"', "--disable", "shell_tool",
              "--cd", "<SCRATCH>", "-"],
    "agy": ["-p", "請只回答 OK", "--output-format", "text", "--disable-slash-commands"],
    "grok": ["-p", "請只回答 OK", "--output-format", "plain", "--max-turns", "1", "--disable-web-search", "--no-memory", "--no-plan",
             "--no-subagents", "--cwd", "<SCRATCH>"],
    "mcode": ["exec", "請只回答 OK", "--cwd", "<SCRATCH>", "--timeout", "60s", "--max-steps", "1", "--permission", "off",
              "--output-format", "text"],
}
SENTENCE = "請只回答 OK"
ALL = ("claude", "codex", "agy", "grok", "mcode")


class TryCase(SetupCase):
    def setUp(self):
        super().setUp()
        self.req("POST", "/api/config", {"show_mcode": True})
        self.scratch_root = self.tmp / "scratch"
        self.scratch_root.mkdir()
        self.tmpdir = mock.patch.dict(os.environ, {"TMPDIR": str(self.scratch_root)})
        self.tmpdir.start()
        import tempfile
        self._old_tempdir, tempfile.tempdir = tempfile.tempdir, None

    def tearDown(self):
        import tempfile
        tempfile.tempdir = self._old_tempdir
        pid = self.bindir / "child.pid"
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        self.tmpdir.stop()
        super().tearDown()

    def install_try(self, name, mode=None):
        self.bindir.mkdir(parents=True, exist_ok=True)
        exe = self.bindir / name
        exe.write_text(TRY_TOOL % {"py": sys.executable, "name": name, "version": VERSION_LINES[name], "canary": CANARY,
                                   "reply": REPLY})
        exe.chmod(0o700)
        if mode:
            (self.bindir / f"mode-{name}").write_text(mode)

    def tries(self):
        p = self.bindir / "tries.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def try_it(self, tool, confirmed=True, **extra):
        body = dict(extra)
        if confirmed:
            body["confirmed"] = True
        return self.req("POST", f"/api/setup/tools/{tool}/try", body, timeout=40)

    def set_limits(self, daily):
        st, r = self.req("POST", "/api/config", {"meeting_limits": {"per_call_usd": 0.01, "meeting_usd": 0.01, "daily_usd": daily}})
        self.assertEqual(st, 200, r)

    def ledger(self):
        st, r = self.req("GET", "/api/meetings/ledger")
        self.assertEqual(st, 200, r)
        return r


class ArgvTests(TryCase):
    def test_each_tool_is_started_with_its_own_headless_call_and_nothing_else(self):
        for name in ALL:
            self.install_try(name)
            st, r = self.try_it(name)
            self.assertEqual((st, r.get("success"), r.get("result")), (200, True, "success"), (name, r))
        got = {t["tool"]: t for t in self.tries()}
        self.assertEqual(sorted(got), sorted(ALL))
        for name in ALL:
            t = got[name]
            scratch = t["cwd"]
            self.assertTrue(os.path.basename(scratch).startswith("vbear-setup-try-"), scratch)
            self.assertEqual([a if a != scratch else "<SCRATCH>" for a in t["argv"]], EXPECTED_ARGV[name], name)
            self.assertTrue(t["ppid_group"], "started in its own process group")
            self.assertFalse(os.path.exists(scratch), "the scratch folder is gone afterwards")
        # the sentence is the fixed one; claude and codex read it on stdin, the others take it in the argv
        self.assertEqual(got["claude"]["stdin"], SENTENCE)
        self.assertEqual(got["codex"]["stdin"], SENTENCE)
        for name in ("agy", "grok", "mcode"):
            self.assertEqual(got[name]["stdin"], "")
            self.assertIn(SENTENCE, got[name]["argv"])

    def test_codex_gets_its_approval_option_before_exec_because_exec_has_none(self):
        # `codex --help` lists -a/--ask-for-approval as a top-level option; `codex exec --help` does not list it
        from vbear import setup_try
        argv = setup_try.argv_for("codex", "/fake/codex", "/fake/scratch")
        self.assertEqual(argv[:4], ["/fake/codex", "--ask-for-approval", "never", "exec"])
        self.assertEqual(argv.count("--ask-for-approval"), 1)

    def test_the_tool_sees_a_plain_environment_and_no_folder_of_the_person(self):
        self.install_try("grok")
        os.environ["SOME_SECRET_TOKEN"] = "FAKE-SECRET-VALUE"
        try:
            self.assertEqual(self.try_it("grok")[0], 200)
        finally:
            del os.environ["SOME_SECRET_TOKEN"]
        env = set(self.tries()[0]["env"])
        self.assertLessEqual(env, {"PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR", "PWD", "SHLVL", "_", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"})
        self.assertNotIn("SOME_SECRET_TOKEN", env)

    def test_claude_asks_for_no_tools_and_loads_no_settings_and_a_small_budget(self):
        argv = EXPECTED_ARGV["claude"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--safe-mode", argv)
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.02")
        self.assertEqual(setup_try.argv_for("claude", "/x/claude", "/s")[1:], argv)


class ResultTests(TryCase):
    def test_success(self):
        self.install_try("agy")
        st, r = self.try_it("agy")
        self.assertEqual((st, r["ok"], r["success"], r["result"]), (200, True, True, "success"))
        self.assertIn("回應了", r["message"])

    def test_a_tool_that_fails_reads_as_probably_not_logged_in(self):
        self.install_try("grok", "fail")
        st, r = self.try_it("grok")
        self.assertEqual((st, r["success"], r["result"]), (200, False, "not_logged_in"))
        self.assertIn("還沒登入", r["message"])
        self.assertIn("登入", r["message"])
        self.assertNotIn(CANARY, json.dumps(r, ensure_ascii=False), "what the tool said is never passed on")

    def test_a_tool_that_does_not_answer_in_time_is_stopped(self):
        self.install_try("codex", "hang")
        with mock.patch.object(setup_try, "TRY_TIMEOUT_S", 1.0):
            t0 = time.monotonic()
            st, r = self.try_it("codex")
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual((st, r["success"], r["result"]), (200, False, "timeout"))
        self.assertIn("沒有回應", r["message"])

    def test_the_whole_process_group_is_ended_after_a_timeout(self):
        self.install_try("mcode", "child")
        with mock.patch.object(setup_try, "TRY_TIMEOUT_S", 1.5):
            st, r = self.try_it("mcode")
        self.assertEqual(r["result"], "timeout")
        pid = int((self.bindir / "child.pid").read_text())
        end = time.monotonic() + 3
        alive = True
        while time.monotonic() < end and alive:
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive, "the child the tool started is gone")

    def test_a_tool_that_is_not_there_is_not_found_and_costs_nothing(self):
        st, r = self.try_it("agy")
        self.assertEqual((st, r["success"], r["result"]), (200, False, "not_found"))
        self.assertIn("找不到", r["message"])
        self.assertIn("安裝", r["message"])
        self.assertEqual(self.ledger()["spent_usd"], "0")
        self.assertEqual(self.tries(), [])

    def test_an_answer_that_cannot_be_read_is_an_odd_answer(self):
        for name, mode in (("agy", "empty"), ("grok", "huge"), ("claude", "notjson"), ("mcode", "empty")):
            self.install_try(name, mode)
            st, r = self.try_it(name)
            self.assertEqual((st, r["success"], r["result"]), (200, False, "bad_reply"), (name, r))
            self.assertIn("看不懂", r["message"])
        self.install_try("claude", "errorjson")
        self.assertEqual(self.try_it("claude")[1]["result"], "bad_reply")

    def test_the_model_s_words_are_never_kept_or_served(self):
        for name in ("claude", "codex", "grok"):
            self.install_try(name)
        bodies = [json.dumps(self.try_it(n)[1], ensure_ascii=False) for n in ("claude", "codex", "grok")]
        for b in bodies:
            self.assertNotIn(REPLY, b)
            self.assertNotIn("FAKE-SESSION-ID", b)
        for root in (Path(os.environ["VBEAR_HOME"]), self.fakehome, self.scratch_root):
            for p in root.rglob("*"):
                if p.is_file():
                    data = p.read_bytes()
                    self.assertNotIn(REPLY.encode(), data, p)
                    self.assertNotIn(b"FAKE-SESSION-ID", data, p)
                    self.assertNotIn(CANARY.encode(), data, p)

    def test_the_spend_file_holds_only_tool_times_and_money(self):
        self.install_try("claude", "cost:0.0042")
        self.try_it("claude")
        data = json.loads(try_spend.store.path().read_text())
        self.assertEqual(len(data), 1)
        (entry,) = data.values()
        self.assertEqual(sorted(entry), ["cap_usd", "ended_at", "evidence", "started_at", "state", "tool"])
        self.assertEqual(list(entry["evidence"]), ["cost_usd"])
        self.assertEqual(oct(try_spend.store.path().stat().st_mode & 0o777), "0o600")


class RequestTests(TryCase):
    def test_a_try_needs_the_confirmation_and_nothing_starts_without_it(self):
        self.install_try("agy")
        st, r = self.try_it("agy", confirmed=False)
        self.assertEqual(st, 409, r)
        self.assertIn("US$0.01", r["error"])
        st, r = self.req("POST", "/api/setup/tools/agy/try", {"confirmed": "yes"})
        self.assertEqual(st, 400, r)
        self.assertEqual(self.tries(), [])
        self.assertEqual(self.ledger()["spent_usd"], "0")

    def test_other_fields_unknown_tools_and_a_hidden_tool_are_refused(self):
        self.install_try("agy")
        self.install_try("mcode")
        st, r = self.try_it("agy", command="rm -rf /")
        self.assertEqual(st, 400, r)
        self.assertEqual(self.try_it("nope")[0], 404)
        self.assertEqual(self.try_it("shared")[0], 404)
        self.req("POST", "/api/config", {"show_mcode": False})
        self.assertEqual(self.try_it("mcode")[0], 400)
        self.assertEqual(self.tries(), [])

    def test_the_page_needs_the_console_header(self):
        import http.client
        self.install_try("agy")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("POST", "/api/setup/tools/agy/try", body=json.dumps({"confirmed": True}),
                  headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        c.close()
        self.assertEqual(self.tries(), [])

    def test_only_one_try_runs_at_a_time(self):
        self.install_try("grok", "hang")
        self.install_try("agy")
        with mock.patch.object(setup_try, "TRY_TIMEOUT_S", 3.0):
            box = {}
            t = threading.Thread(target=lambda: box.update(r=self.try_it("grok")))
            t.start()
            end = time.monotonic() + 5
            while time.monotonic() < end and not self.tries():
                time.sleep(0.02)
            st, r = self.try_it("agy")
            t.join(20)
        self.assertEqual(st, 409, r)
        self.assertIn("正在試", r["error"])
        self.assertEqual(box["r"][1]["result"], "timeout")
        self.assertEqual([x["tool"] for x in self.tries()], ["grok"])


class SpendTests(TryCase):
    def test_a_tool_with_no_cost_to_report_is_booked_at_one_cent_and_claude_at_what_it_reported(self):
        self.install_try("agy")
        self.install_try("claude", "cost:0.0042")
        self.try_it("agy")
        self.assertEqual(self.ledger()["spent_usd"], "0.01")
        self.try_it("claude")
        self.assertEqual(self.ledger()["spent_usd"], "0.0142")

    def test_claude_without_a_reported_cost_is_booked_at_one_cent(self):
        self.install_try("claude")
        self.try_it("claude")
        self.assertEqual(self.ledger()["spent_usd"], "0.01")

    def test_a_failed_try_that_started_a_program_is_booked_too(self):
        self.install_try("grok", "fail")
        self.try_it("grok")
        self.assertEqual(self.ledger()["spent_usd"], "0.01")

    def test_when_the_daily_limit_is_used_up_nothing_is_started(self):
        self.install_try("agy")
        self.install_try("grok")
        self.set_limits(0.015)
        st, r = self.try_it("agy")
        self.assertEqual((st, r["success"]), (200, True))
        st, r = self.try_it("grok")
        self.assertEqual(st, 409, r)
        self.assertIn("每天上限", r["error"])
        self.assertIn("US$0.015", r["error"])
        self.assertEqual([t["tool"] for t in self.tries()], ["agy"])
        self.assertEqual(self.ledger()["spent_usd"], "0.01")

    def test_a_limit_of_one_cent_allows_exactly_one_try(self):
        self.install_try("agy")
        self.set_limits(0.01)
        self.assertEqual(self.try_it("agy")[0], 200)
        self.assertEqual(self.try_it("agy")[0], 409)

    def test_a_spend_record_that_cannot_be_read_stops_the_try(self):
        self.install_try("agy")
        cfg.ensure_state_dir()
        try_spend.store.path().write_text("this is not json")
        st, r = self.try_it("agy")
        self.assertEqual(st, 409, r)
        self.assertEqual(self.tries(), [])

    def test_a_turn_still_running_counts_at_its_cap(self):
        self.install_try("agy")
        self.set_limits(0.015)
        try_spend.start("grok", time.time())
        st, r = self.try_it("agy")
        self.assertEqual(st, 409, r)

    def test_staffing_meetings_and_chats_see_the_same_day(self):
        self.install_try("agy")
        self.try_it("agy")
        self.assertEqual(self.console.staffing_runner()._day(), Decimal("0.01"))
        self.assertEqual(self.console.meeting_runner()._day(), Decimal("0.01"))
        from vbear.runtime import daemon_chat

        class Fake:
            base = str(self.home)
        self.assertEqual(daemon_chat.ChatOps._chat_day_spent(Fake(), time.time()), Decimal("0.01"))

    def test_old_turns_are_dropped_and_do_not_count_today(self):
        old = time.time() - 5 * 86400
        tid = try_spend.start("agy", old)
        try_spend.finish(tid, "done", Decimal("0.01"), old + 1)
        self.assertEqual(try_spend.record("try")["turns"][0]["tool"], "agy")
        self.assertEqual(self.ledger()["spent_usd"], "0")
        try_spend.start("grok", time.time())          # writing again prunes what is older than the days kept
        self.assertEqual([t["tool"] for t in try_spend.record("try")["turns"]], ["grok"])


class CacheTests(TryCase):
    def setUp(self):
        super().setUp()
        self.ttl = mock.patch.object(ai_tool_status, "CACHE_TTL_S", 30.0)
        self.ttl.start()

    def tearDown(self):
        self.ttl.stop()
        super().tearDown()

    def version_calls(self):
        p = self.bindir / "calls.log"
        return [c for c in (p.read_text().splitlines() if p.exists() else []) if c.endswith("--version")]

    def test_the_state_is_read_once_in_a_while_not_at_every_poll(self):
        self.install_try("claude")
        for _ in range(4):
            self.tools()
        self.assertEqual(self.version_calls(), ["claude --version"])

    def test_the_cache_runs_out(self):
        self.install_try("claude")
        self.tools()
        with mock.patch.object(ai_tool_status, "CACHE_TTL_S", 0.0):
            self.tools()
        self.assertEqual(len(self.version_calls()), 2)

    def test_the_recheck_forces_a_fresh_look_and_needs_the_console_header(self):
        self.install_try("claude")
        self.tools()
        st, r = self.req("GET", "/api/setup/tools?force=1")
        self.assertEqual(st, 200, r)
        self.assertEqual(len(self.version_calls()), 2)
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("GET", "/api/setup/tools?force=1", headers={"Host": f"127.0.0.1:{self.port}"})
        resp = c.getresponse()
        resp.read()
        c.close()
        self.assertEqual(resp.status, 403)

    def test_a_tool_that_appears_is_seen_after_a_forced_look_and_not_before(self):
        tools, _ = self.tools()
        self.assertFalse(tools["agy"]["installed"])
        self.install_try("agy")
        self.assertFalse(self.tools()[0]["agy"]["installed"], "cached")
        st, r = self.req("GET", "/api/setup/tools?force=1")
        self.assertTrue({row["id"]: row for row in r["tools"]}["agy"]["installed"])

    def test_the_mark_shows_at_once(self):
        self.install_try("agy")
        self.assertEqual(self.tools()[0]["agy"]["state"], "not_logged_in")
        self.req("POST", "/api/setup/tools/agy/marker", {"done": True})
        self.assertEqual(self.tools()[0]["agy"]["state"], "ready")
        self.req("POST", "/api/setup/tools/agy/marker", {"done": False})
        self.assertEqual(self.tools()[0]["agy"]["state"], "not_logged_in")

    def test_a_try_makes_the_next_look_fresh(self):
        self.install_try("agy")
        self.tools()
        before = len(self.version_calls())
        self.try_it("agy")
        self.tools()
        self.assertEqual(len(self.version_calls()), before + 1)

    def test_a_terminal_for_install_or_login_makes_the_next_look_fresh(self):
        self.install_try("agy")
        self.tools()
        before = len(self.version_calls())
        st, r = self.req("POST", "/api/setup/terminals", {"tool": "agy", "action": "login"})
        self.assertEqual(st, 200, r)
        self.tools()
        self.assertEqual(len(self.version_calls()), before + 1)

    def test_a_different_search_path_is_not_served_from_the_cache(self):
        self.install_try("agy")
        self.assertTrue(self.tools()[0]["agy"]["installed"])
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            self.assertFalse(self.tools()[0]["agy"]["installed"])

    def test_the_cache_holds_no_output_of_a_tool(self):
        self.install_try("claude")
        self.tools()
        for value in ai_tool_status._cache.values():
            self.assertNotIn(CANARY, json.dumps(value, default=str))


if __name__ == "__main__":
    unittest.main()
