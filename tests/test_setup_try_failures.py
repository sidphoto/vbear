"""P57 follow-up: 「試一下」 no longer says "not logged in" for every failed exit.

The tail of the tool's error output (at most 4 KiB) is read for one thing, which of a few well-known failures it was, and
dropped. Over HTTP with the runtime daemon in a thread, as tests/test_t17_try.py does; every tool is a stand-in file and
every line it prints is made up (the Codex lines are de-identified copies of what Codex 0.167.0 printed with an empty
home folder: no id, no host, no request number).

Guard rule 21d (tests/test_autonomy_guard.py, ``SetupTryStderrRules``, reads the sources): what the tool printed on its error
output never leaves; ``test_nothing_the_tool_printed_is_in_the_result_a_log_or_a_file`` below is its run-time half.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_t17_try import TRY_TOOL, TryCase
from vbear import setup_try

# What Codex 0.167.0 printed (stderr) when it had no login at all: many connection retries, then the answer of the server.
CODEX_EMPTY_HOME = (
    "2026-01-01T00:00:00.000000Z ERROR codex_api::endpoint::responses_websocket: failed to connect to Responses WebSocket stage=Unknown\n"
    "ERROR: Reconnecting... 2/5\n"
    "2026-01-01T00:00:01.000000Z ERROR codex_api::endpoint::responses_websocket: failed to connect to Responses WebSocket stage=Unknown\n"
    "ERROR: Reconnecting... 3/5\n"
    "warning: Falling back from WebSockets to HTTPS transport. unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, url: wss://example.invalid/v1/responses, cf-ray: abc123-XXX\n"
    "ERROR: Reconnecting... 1/5\n"
    "ERROR: unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, url: https://example.invalid/v1/responses, cf-ray: abc123-XXX, request id: req_0000\n"
)
SECRET = "FAKE-ACCOUNT-DETAIL-do-not-keep-42"

# the stand-in learns modes: "err:<exit code>" prints the file stderr-<name> to its error output and exits;
# "flood:<exit code>" prints 4 MiB of error output and then the file; "flood-fail" the 4 MiB only, then exits 1; "flood-ok" floods and then answers;
# "flood-hang" floods and then does not answer
EXTRA = r'''
if m.startswith("err:") or m.startswith("flood:") or m in ("flood-ok", "flood-hang", "flood-fail"):
    if m.startswith("flood"):
        for _ in range(4096):
            sys.stderr.write("E" * 1023 + "\n")
        sys.stderr.flush()
    p = os.path.join(here, "stderr-" + name)
    if os.path.exists(p) and (m.startswith("err:") or m.startswith("flood:")):
        sys.stderr.write(open(p).read())
        sys.stderr.flush()
    if m == "flood-hang":
        time.sleep(120)
    if m == "flood-ok":
        print("fine")
        sys.exit(0)
    sys.exit(1 if m == "flood-fail" else int(m.split(":")[1]))
'''
EARLY = r'''
if mode() == "early":
    sys.stderr.write(open(os.path.join(here, "stderr-" + name)).read())
    sys.exit(1)
'''


class FailureCase(TryCase):
    def install_try(self, name, mode=None):
        self.bindir.mkdir(parents=True, exist_ok=True)
        script = TRY_TOOL.replace("m = mode()\n", "m = mode()\n" + EXTRA, 1).replace("stdin = sys.stdin.read()\n", EARLY + "stdin = sys.stdin.read()\n", 1)
        from tests.test_t16_setup import CANARY, VERSION_LINES
        from tests.test_t17_try import REPLY
        exe = self.bindir / name
        exe.write_text(script % {"py": __import__("sys").executable, "name": name, "version": VERSION_LINES[name], "canary": CANARY, "reply": REPLY})
        exe.chmod(0o700)
        if mode:
            (self.bindir / f"mode-{name}").write_text(mode)

    def fail_with(self, name, text, code=1, mode=None):
        self.install_try(name, mode or f"err:{code}")
        (self.bindir / f"stderr-{name}").write_text(text)
        st, r = self.try_it(name)
        self.assertEqual(st, 200, r)
        return r


class ClassifyTests(unittest.TestCase):
    """The words, with no program started."""

    def c(self, text, tool="codex"):
        return setup_try.classify_failure(tool, text.encode("utf-8") if isinstance(text, str) else text)

    def test_the_real_codex_sample_with_no_login_is_not_logged_in(self):
        self.assertEqual(self.c(CODEX_EMPTY_HOME), "not_logged_in")

    def test_each_login_phrase(self):
        for text in ("unexpected status 401 Unauthorized", "ERROR: 401 unauthorized", "Missing bearer or basic authentication",
                     "Error: Not logged in", "not logged in. Run the tool again", "Authentication required",
                     "please run `tool login` first", "Please run the-tool auth login"):
            self.assertEqual(self.c(text), "not_logged_in", text)

    def test_each_limit_phrase(self):
        for text in ("You have hit your usage limit. Try again later.", "rate limit exceeded", "HTTP 429 Too Many Requests",
                     "unexpected status 429", "quota exceeded for this plan", "Usage Limit reached"):
            self.assertEqual(self.c(text), "limit", text)

    def test_each_network_phrase(self):
        for text in ("failed to connect to Responses WebSocket stage=Unknown", "dns error: failed to lookup address information",
                     "Could not resolve host: example.invalid", "error: connection refused", "request timed out",
                     "unable to connect to the server", "network is unreachable", "Can't connect to the server"):
            self.assertEqual(self.c(text), "network", text)

    def test_everything_else_is_failed(self):
        for text in ("", "something odd happened", "panic: index out of range", "ERROR: Reconnecting... 2/5", "unauthorized",
                     "Unauthorized access to the folder", "error 4010", "request id: req_4011abc", "cf-ray: a40129xz-TPE",
                     "quotation mark missing", "429x", "the limit of the file name"):
            self.assertEqual(self.c(text), "failed", text)

    def test_priority_login_then_limit_then_network_then_failed(self):
        self.assertEqual(self.c("failed to connect\nfailed to connect\nunexpected status 401 Unauthorized"), "not_logged_in")
        self.assertEqual(self.c("timed out\nunexpected status 401 Unauthorized\ntimed out"), "not_logged_in")
        self.assertEqual(self.c("unexpected status 401 Unauthorized\n429 Too Many Requests"), "not_logged_in")
        self.assertEqual(self.c("failed to connect\nfailed to connect\nusage limit reached"), "limit")
        self.assertEqual(self.c("429 Too Many Requests\ntimed out"), "limit")
        self.assertEqual(self.c("timed out\nsomething odd"), "network")

    def test_the_other_tools_have_no_phrase_of_their_own(self):
        # no sample of Claude Code, AGY, Grok or MCODE was seen: without one of the general phrases above they are just failed
        for tool in ("claude", "agy", "grok", "mcode"):
            self.assertEqual(self.c("some message only this tool prints", tool), "failed", tool)
            self.assertEqual(self.c("", tool), "failed", tool)
            self.assertEqual(self.c(b"\xff\xfe\x00 odd bytes", tool), "failed", tool)

    def test_a_cut_multibyte_character_does_not_break_it(self):
        raw = ("好" * 3000).encode("utf-8")[1:] + b"\nunexpected status 401 Unauthorized"
        self.assertEqual(self.c(raw), "not_logged_in")


class ResultOverHttpTests(FailureCase):
    def test_the_real_codex_sample_is_not_logged_in_with_its_exit_code(self):
        r = self.fail_with("codex", CODEX_EMPTY_HOME)
        self.assertEqual((r["success"], r["result"], r["exit_code"]), (False, "not_logged_in", 1))
        self.assertIn("還沒登入", r["message"])

    def test_a_limit_a_network_problem_and_an_unknown_failure_each_have_their_own_words(self):
        r = self.fail_with("codex", "You have hit your usage limit.\n", 1)
        self.assertEqual((r["result"], r["exit_code"]), ("limit", 1))
        self.assertIn("用量到上限", r["message"])
        self.assertNotIn("登入", r["message"])
        r = self.fail_with("codex", "failed to connect to Responses WebSocket\n", 1)
        self.assertEqual(r["result"], "network")
        self.assertIn("連不上", r["message"])
        self.assertIn("網路", r["message"])
        self.assertNotIn("請先按「登入」", r["message"])
        r = self.fail_with("codex", "no idea what this is\n", 2)
        self.assertEqual((r["result"], r["exit_code"]), ("failed", 2))
        self.assertIn("原因 VBear 看不出來", r["message"])
        self.assertIn("可以再試一次", r["message"])
        self.assertIn("先登入", r["message"])
        self.assertNotIn("請先按「登入」", r["message"], "it does not tell the person to log in when it does not know")

    def test_a_failure_with_no_output_at_all_is_failed_and_still_booked(self):
        self.assertEqual(self.ledger()["spent_usd"], "0")
        r = self.fail_with("grok", "", 3)
        self.assertEqual((r["result"], r["exit_code"]), ("failed", 3))
        self.assertEqual(r["spent_usd"], "0.01")
        self.assertEqual(self.ledger()["spent_usd"], "0.01", "a try that started a program is booked even when it fails, as before")

    def test_success_and_the_other_results_carry_no_exit_code_of_a_failure(self):
        self.install_try("agy")
        r = self.try_it("agy")[1]
        self.assertEqual(r["result"], "success")
        self.assertIsNone(r["exit_code"])
        self.install_try("codex", "hang")
        with mock.patch.object(setup_try, "TRY_TIMEOUT_S", 1.0):
            r = self.try_it("codex")[1]
        self.assertEqual(r["result"], "timeout")
        self.assertIsNone(r["exit_code"])

    def test_the_old_stand_in_that_says_not_logged_in_is_still_not_logged_in(self):
        TryCase.install_try(self, "grok", "fail")
        r = self.try_it("grok")[1]
        self.assertEqual((r["result"], r["exit_code"]), ("not_logged_in", 1))

    def test_the_tool_that_ends_before_it_reads_the_sentence(self):
        r = self.fail_with("codex", CODEX_EMPTY_HOME, mode="early")
        self.assertEqual(r["result"], "not_logged_in")
        self.assertEqual(r["exit_code"], 1)

    def test_a_flood_of_error_output_is_neither_a_deadlock_nor_a_wrong_answer(self):
        r = self.fail_with("codex", CODEX_EMPTY_HOME, mode="flood:1")
        self.assertEqual(r["result"], "not_logged_in", "the last 4 KiB hold the server's answer")
        self.install_try("grok", "flood-fail")
        r = self.try_it("grok")[1]
        self.assertEqual((r["result"], r["exit_code"]), ("failed", 1), "a flood of one letter has nothing to recognise")
        self.install_try("agy", "flood-ok")
        r = self.try_it("agy")[1]
        self.assertEqual((r["success"], r["result"]), (True, "success"))

    def test_the_login_line_at_the_end_of_a_flood_is_still_seen(self):
        self.install_try("codex", "err:1")
        # a very long error output that ends with the answer of the server
        (self.bindir / "stderr-codex").write_text("E" * (1 << 20) + "\n" + CODEX_EMPTY_HOME)
        self.assertEqual(self.try_it("codex")[1]["result"], "not_logged_in")

    def test_the_time_limit_is_the_same_with_a_flood(self):
        self.install_try("codex", "flood-hang")
        with mock.patch.object(setup_try, "TRY_TIMEOUT_S", 1.5):
            t0 = time.monotonic()
            r = self.try_it("codex")[1]
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(r["result"], "timeout")

    def test_nothing_the_tool_printed_is_in_the_result_a_log_or_a_file(self):
        text = CODEX_EMPTY_HOME + f"user detail {SECRET}\nunexpected status 401 Unauthorized\n"
        with self.assertLogs(level="DEBUG") as logs:
            import logging
            logging.getLogger("probe").debug("probe")        # assertLogs needs one record
            r = self.fail_with("codex", text)
        self.assertEqual(r["result"], "not_logged_in")
        body = json.dumps(r, ensure_ascii=False)
        for needle in (SECRET, "Missing bearer", "responses_websocket", "Unauthorized", "example.invalid", "cf-ray", "req_0000"):
            self.assertNotIn(needle, body, needle)
        self.assertEqual(sorted(r), ["exit_code", "message", "ok", "result", "spent_usd", "success", "tool"])
        self.assertTrue(all(SECRET not in line for line in logs.output))
        # no file this program wrote (the state folder, the scratch root, the home folder) holds a word of it
        hits = []
        for base, _dirs, files in os.walk(self.tmp):
            if os.path.realpath(base).startswith(os.path.realpath(self.bindir)):
                continue                                  # the stand-in tool and its own made-up input
            for f in files:
                try:
                    data = Path(base, f).read_bytes()
                except OSError:
                    continue
                if SECRET.encode() in data or b"Missing bearer" in data:
                    hits.append(os.path.join(base, f))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
