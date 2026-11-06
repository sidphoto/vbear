"""The Codex chat protocol (P38-1): what VBear writes to ``codex app-server`` 0.163.0 in a chat, how it reads what comes
back, and which file changes it answers itself. Pure: replayed from the recorded transcripts
(tests/codex_chat_fixtures.py); no process is started."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal

from tests import codex_chat_fixtures as ccf
from vbear.runtime import codex_chat_protocol as ccp

THREAD = "00000000-0000-4000-8000-000000000003"


def parsed(line: bytes):
    """One stdin line as VBear writes it: exactly one JSON object and a newline, never a ``jsonrpc`` member."""
    assert line.endswith(b"\n") and line.count(b"\n") == 1, line
    obj = json.loads(line)
    assert "jsonrpc" not in obj
    return obj


class ConstantsTests(unittest.TestCase):
    def test_0_163_0_is_the_recorded_version(self):
        c = ccp.VERSIONS["0.163.0"]
        self.assertEqual(c.version, "0.163.0")
        self.assertEqual(c.allowed_items,
                         frozenset({"commandExecution", "fileChange", "agentMessage", "userMessage", "reasoning",
                                    "plan"}))
        self.assertEqual(c.remote_control_env, ("CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED", "1"))
        self.assertEqual(c.env_keys, ("PATH", "USER", "LOGNAME", "LANG", "CODEX_HOME", "HOME",
                                      "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"))
        self.assertIsNone(ccp.constants_for("0.162.0"))
        self.assertIsNone(ccp.constants_for(None))
        self.assertIs(ccp.constants_for("0.163.0"), c)

    def test_the_notifications_it_knows_are_the_recorded_ones(self):
        known = ccp.VERSIONS["0.163.0"].known_notifications
        recorded = set()
        for name in ccf.NAMES:
            for direction, line in ccf.load(name):
                if direction == "out" and isinstance(line, dict) and "method" in line and "id" not in line:
                    recorded.add(line["method"])
        self.assertTrue(recorded)
        self.assertLessEqual(recorded, known)

    def test_argv_names_every_setting_and_disabled_feature_and_no_other_switch(self):
        argv = ccp.argv_for(ccp.VERSIONS["0.163.0"], "/h/.vbear/chat-work/aaaa")
        self.assertEqual(argv[:3], ["app-server", "--listen", "stdio://"])
        configs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
        disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
        self.assertEqual(configs, [
            'cli_auth_credentials_store="file"', 'web_search="disabled"', "check_for_update_on_startup=false",
            "notify=[]", 'history.persistence="none"', "skills.bundled.enabled=false",
            "skills.include_instructions=false", "project_doc_max_bytes=0",
            "sandbox_workspace_write.network_access=false", "sandbox_workspace_write.exclude_slash_tmp=true",
            "sandbox_workspace_write.exclude_tmpdir_env_var=true", "project_root_markers=[]",
            'projects={"/h/.vbear/chat-work/aaaa"={trust_level="untrusted"}}'])
        self.assertEqual(disabled, [
            "apps", "plugins", "remote_plugin", "hooks", "shell_snapshot", "browser_use", "browser_use_external",
            "computer_use", "image_generation", "memories", "multi_agent", "skill_mcp_dependency_install",
            "tool_suggest", "view_image", "in_app_browser", "goals", "realtime_conversation", "sleep_tool",
            "workspace_dependencies", "worktrees"])
        self.assertEqual(len(argv), 3 + 2 * len(configs) + 2 * len(disabled))
        self.assertNotIn("--strict-config", argv)

    def test_the_trust_setting_is_one_inline_table_that_toml_reads_back_as_the_work_folder(self):
        import tomllib
        c = ccp.VERSIONS["0.163.0"]
        # a dot in the path (~/.vbear) must stay inside one key, which is why it is an inline table and not dotted keys
        for path in ("/h/.vbear/chat-work/aaaa", '/h/we"ird/back\\slash/x', "/h/空白 資料夾/x", "/h/a=b/c.d/e",
                     "/h/\U0001F600/x"):
            argv = ccp.argv_for(c, path)
            value = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"][-1]
            self.assertTrue(value.startswith("projects={"))
            key, _, rest = value.partition("=")
            self.assertEqual(key, "projects")
            self.assertEqual(tomllib.loads(value), {"projects": {path: {"trust_level": "untrusted"}}}, path)

    def test_the_project_root_markers_are_empty_so_the_work_folder_is_the_project_root(self):
        self.assertIn("project_root_markers=[]", ccp.VERSIONS["0.163.0"].config)

    def test_a_work_folder_that_cannot_be_written_safely_is_refused(self):
        c = ccp.VERSIONS["0.163.0"]
        for bad in ("relative/x", "", None, 7, "/h/a\nb", "/h/a\rb", "/h/a\0b", "/h/a\tb", "/h/a\x7fb",
                    "/h/a\ud800b", "/h/a\x1bb"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ccp.argv_for(c, bad)


class LineTests(unittest.TestCase):
    def test_initialize_then_initialized(self):
        self.assertEqual(parsed(ccp.initialize_line(1, "0.13.0")), {
            "method": "initialize", "id": 1,
            "params": {"clientInfo": {"name": "vbear", "title": "VBear", "version": "0.13.0"},
                       "capabilities": {"experimentalApi": False}}})
        self.assertEqual(parsed(ccp.initialized_line()), {"method": "initialized"})

    def test_thread_start_asks_for_every_command_and_the_workspace_write_sandbox(self):
        self.assertEqual(parsed(ccp.thread_start_line(2, cwd="/w/work")), {
            "method": "thread/start", "id": 2,
            "params": {"cwd": "/w/work", "approvalPolicy": "untrusted", "approvalsReviewer": "user",
                       "sandbox": "workspace-write", "ephemeral": False, "serviceName": "vbear"}})
        got = parsed(ccp.thread_start_line(2, cwd="/w/work", model="gpt-6.1-sol", developer_instructions="Be brief."))
        self.assertEqual(got["params"]["model"], "gpt-6.1-sol")
        self.assertEqual(got["params"]["developerInstructions"], "Be brief.")

    def test_thread_resume_carries_the_same_settings_and_the_thread(self):
        got = parsed(ccp.thread_resume_line(3, THREAD, cwd="/w/work", model="gpt-6.1-sol"))
        self.assertEqual(got, {
            "method": "thread/resume", "id": 3,
            "params": {"threadId": THREAD, "cwd": "/w/work", "approvalPolicy": "untrusted",
                       "approvalsReviewer": "user", "sandbox": "workspace-write", "excludeTurns": True,
                       "model": "gpt-6.1-sol"}})

    def test_turn_start_repeats_the_policy_and_the_sandbox_with_no_network(self):
        self.assertEqual(parsed(ccp.turn_start_line(4, THREAD, "hello 你好")), {
            "method": "turn/start", "id": 4,
            "params": {"threadId": THREAD, "input": [{"type": "text", "text": "hello 你好"}],
                       "approvalPolicy": "untrusted",
                       "sandboxPolicy": {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                                         "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}}})
        self.assertEqual(parsed(ccp.turn_start_line(4, THREAD, "x", effort="low"))["params"]["effort"], "low")

    def test_steer_interrupt_mcp_list_and_delete(self):
        self.assertEqual(parsed(ccp.turn_steer_line(5, THREAD, "turn-1", "use this instead")), {
            "method": "turn/steer", "id": 5,
            "params": {"threadId": THREAD, "expectedTurnId": "turn-1",
                       "input": [{"type": "text", "text": "use this instead"}]}})
        self.assertEqual(parsed(ccp.turn_interrupt_line(6, THREAD, "turn-1")), {
            "method": "turn/interrupt", "id": 6, "params": {"threadId": THREAD, "turnId": "turn-1"}})
        self.assertEqual(parsed(ccp.mcp_status_list_line(7, THREAD)), {
            "method": "mcpServerStatus/list", "id": 7, "params": {"detail": None, "threadId": THREAD}})
        self.assertEqual(parsed(ccp.thread_delete_line(8, THREAD)), {
            "method": "thread/delete", "id": 8, "params": {"threadId": THREAD}})

    def test_a_decision_is_an_answer_to_the_servers_request_id_whatever_its_type(self):
        self.assertEqual(parsed(ccp.decision_line(0, "accept")), {"id": 0, "result": {"decision": "accept"}})
        self.assertEqual(parsed(ccp.decision_line("req-1", "decline")),
                         {"id": "req-1", "result": {"decision": "decline"}})
        self.assertEqual(parsed(ccp.decision_line(9, "cancel")), {"id": 9, "result": {"decision": "cancel"}})

    def test_no_decision_but_accept_decline_cancel_can_be_written(self):
        for bad in ("acceptForSession", "acceptWithExecpolicyAmendment", "applyNetworkPolicyAmendment", "allow", "",
                    None, {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["ls"]}}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ccp.decision_line(1, bad)

    def test_the_error_answer_is_a_json_rpc_method_not_found(self):
        self.assertEqual(parsed(ccp.error_line(3, "VBear 不接受這種請求")),
                         {"id": 3, "error": {"code": -32601, "message": "VBear 不接受這種請求"}})
        self.assertEqual(parsed(ccp.error_line("abc", "no", code=-32000))["error"]["code"], -32000)

    def test_a_request_id_must_be_a_number_or_a_plain_string(self):
        for bad in (True, 1.5, None, "", "a b", "x" * 200, ["a"], {"a": 1}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ccp.decision_line(bad, "accept")
            with self.assertRaises(ValueError, msg=repr(bad)):
                ccp.error_line(bad, "no")

    def test_text_that_cannot_be_written_is_refused_and_never_cut(self):
        with self.assertRaises(ValueError):
            ccp.turn_start_line(1, THREAD, "")
        with self.assertRaises(ValueError):
            ccp.turn_start_line(1, THREAD, "x" * (32 * 1024 + 1))
        with self.assertRaises(ValueError):
            ccp.turn_start_line(1, THREAD, "lone \ud800 surrogate")
        with self.assertRaises(ValueError):
            ccp.turn_steer_line(1, THREAD, "t", "")
        with self.assertRaises(ValueError):
            ccp.thread_start_line(1, cwd="relative/work")
        with self.assertRaises(ValueError):
            ccp.thread_start_line(1, cwd="/w", model="bad model;rm")
        with self.assertRaises(ValueError):
            ccp.thread_resume_line(1, "not a thread id", cwd="/w")
        with self.assertRaises(ValueError):
            ccp.turn_start_line(1, "not a thread id", "hi")


class EstimateTests(unittest.TestCase):
    """One turn costs (tokens / 1,000,000) x US$1.00, rounded up to the cent, at least US$0.01 (ADR 0005)."""

    def test_worked_examples(self):
        for tokens, usd in ((1, "0.01"), (0, "0.01"), (19_612, "0.02"), (10_000, "0.01"), (10_001, "0.02"),
                            (20_000, "0.02"), (999_999, "1.00"), (1_000_000, "1.00"), (1_000_001, "1.01"),
                            (2_500_000, "2.50")):
            self.assertEqual(ccp.estimate_usd(tokens), Decimal(usd), tokens)

    def test_the_result_is_a_decimal_in_whole_cents(self):
        got = ccp.estimate_usd(123_456)
        self.assertIsInstance(got, Decimal)
        self.assertEqual(got, got.quantize(Decimal("0.01")))

    def test_no_usable_token_count_is_an_error_for_the_session_to_turn_into_the_turn_cap(self):
        for bad in (None, -1, 1.5, True, "5", 10 ** 13):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ccp.estimate_usd(bad)


class JudgeFileChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="vbj"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(os.path.join(self.work, "sub"))
        self.outside = os.path.join(self.tmp, "outside")
        os.makedirs(self.outside)

    @staticmethod
    def change(path, kind="add", diff="hello\n", **kw):
        return {"path": path, "kind": dict({"type": kind}, **kw), "diff": diff}

    def judge(self, *changes):
        return ccp.judge_file_change(list(changes), self.work)

    def test_a_change_inside_the_work_folder_is_asked_about(self):
        for c in (self.change(os.path.join(self.work, "note.txt")), self.change("note.txt"),
                  self.change(os.path.join(self.work, "sub", "a.txt"), "update", move_path=None),
                  self.change(os.path.join(self.work, "old.txt"), "delete", diff="")):
            j = self.judge(c)
            self.assertEqual(j.action, "ask", (c, j))
            self.assertIsNone(j.editable)

    def test_several_changes_are_asked_about_together_and_one_bad_path_refuses_all(self):
        ok = self.change(os.path.join(self.work, "a.txt"))
        self.assertEqual(self.judge(ok, self.change("b.txt")).action, "ask")
        bad = self.change(os.path.join(self.outside, "x.txt"))
        j = self.judge(ok, bad)
        self.assertEqual(j.action, "deny")
        self.assertTrue(j.reason)

    def test_a_path_outside_the_work_folder_is_refused_with_no_way_to_allow(self):
        for path in (os.path.join(self.outside, "patched.txt"), "../outside/x.txt", "/etc/hosts", self.work,
                     os.path.join(self.work, "..", "outside", "x.txt"), self.tmp):
            self.assertEqual(self.judge(self.change(path)).action, "deny", path)

    def test_a_move_target_outside_is_refused_too(self):
        c = self.change(os.path.join(self.work, "a.txt"), "update", move_path=os.path.join(self.outside, "b.txt"))
        self.assertEqual(self.judge(c).action, "deny")
        c = self.change(os.path.join(self.work, "a.txt"), "update", move_path=os.path.join(self.work, ".git", "b"))
        self.assertEqual(self.judge(c).action, "deny")
        c = self.change(os.path.join(self.work, "a.txt"), "update", move_path="renamed.txt")
        self.assertEqual(self.judge(c).action, "ask")

    def test_codexs_own_folders_and_git_are_refused_at_any_depth(self):
        for rel in (".codex/config.toml", ".agents/skills/x.md", ".git/hooks/pre-commit", "sub/.git/config",
                    "sub/.codex/rules/a.rules", ".Codex/config.toml", ".GIT/HEAD", ".git"):
            self.assertEqual(self.judge(self.change(rel)).action, "deny", rel)
        for rel in (".gitignore", "codex.txt", "sub/.github/ci.yml", "agents/a.md", "a.codex"):
            self.assertEqual(self.judge(self.change(rel)).action, "ask", rel)

    def test_a_link_that_leads_outside_is_followed(self):
        os.symlink(self.outside, os.path.join(self.work, "link"))
        os.symlink(os.path.join(self.outside, "t.txt"), os.path.join(self.work, "file-link"))
        self.assertEqual(self.judge(self.change("link/x.txt")).action, "deny")
        self.assertEqual(self.judge(self.change("file-link")).action, "deny")
        os.symlink(os.path.join(self.work, "sub"), os.path.join(self.work, "inner-link"))
        self.assertEqual(self.judge(self.change("inner-link/x.txt")).action, "ask")

    def test_a_link_into_a_protected_folder_is_refused(self):
        os.makedirs(os.path.join(self.work, ".git"))
        os.symlink(os.path.join(self.work, ".git"), os.path.join(self.work, "g"))
        self.assertEqual(self.judge(self.change("g/config")).action, "deny")

    def test_nothing_to_show_or_too_much_to_show_is_refused(self):
        self.assertEqual(ccp.judge_file_change([], self.work).action, "deny")
        self.assertEqual(ccp.judge_file_change(None, self.work).action, "deny")
        big = self.change("big.txt", diff="x" * ccp.MAX_CARD_BYTES)
        self.assertEqual(self.judge(big).action, "deny")
        fits = self.change("fits.txt", diff="x" * 1000)
        self.assertEqual(self.judge(fits).action, "ask")
        self.assertEqual(ccp.judge_file_change([fits], self.work, max_bytes=500).action, "deny")

    def test_a_change_that_is_not_in_the_recorded_shape_is_refused(self):
        for c in ("not a dict", {"path": "a.txt"}, {"path": 5, "kind": {"type": "add"}, "diff": ""},
                  {"path": "a.txt", "kind": {"type": "chmod"}, "diff": ""},
                  {"path": "a.txt", "kind": "add", "diff": ""},
                  {"path": "a.txt", "kind": {"type": "add"}, "diff": None},
                  {"path": "", "kind": {"type": "add"}, "diff": ""},
                  {"path": "a\0b", "kind": {"type": "add"}, "diff": ""},
                  {"path": "a.txt", "kind": {"type": "update", "move_path": 5}, "diff": ""}):
            self.assertEqual(self.judge(c).action, "deny", c)
        self.assertEqual(ccp.judge_file_change("nope", self.work).action, "deny")


# ---- reading what the server prints -----------------------------------------------------------------------------

def thread_result(thread_id=THREAD, work=ccf.WORK, **over):
    """A thread/start or thread/resume answer as VBear's settings make it, the fields VBear reads only."""
    body = {"thread": {"id": thread_id, "cwd": work}, "model": "gpt-6.1-sol", "cwd": work, "instructionSources": [],
            "approvalPolicy": "untrusted", "approvalsReviewer": "user",
            "sandbox": {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                        "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}}
    body.update(over)
    return {"id": 2, "result": body}


def init_result(**over):
    body = {"userAgent": "vbear/0.163.0 (Mac OS 27.0.0; arm64)", "codexHome": ccf.CODEX_HOME,
            "platformFamily": "unix", "platformOs": "macos"}
    body.update(over)
    return {"id": 1, "result": body}


class Replay:
    """A recorded process replayed into a tracker the way a session drives it: ``expect`` for each request VBear
    writes, ``begin_turn`` before each turn/start, ``approve``/``refuse`` after each decision."""

    def __init__(self, name, *, clean=True, last_total=None, **kw):
        self.name = name
        self.clean = clean
        thread = {"b-resume": "00000000-0000-4000-8000-000000000002"}.get(name)
        self.t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home=ccf.CODEX_HOME,
                                  thread_id=thread, resumed=name == "b-resume", last_total=last_total, **kw)
        self.facts: list[tuple[str, dict]] = []
        self.asked: dict = {}                    # request id -> item id
        self.decisions: list = []                # (request id, decision)
        self.by_turn: list[list] = []

    def run(self, rows=None):
        for direction, line in rows if rows is not None else ccf.linear(self.name, clean_it=self.clean):
            if direction == "in":
                self.write(line)
            elif direction == "out":
                self.feed(line)
        return self

    def write(self, line):
        if ccf.is_request(line) and line["method"] in ccf.KINDS:
            self.t.expect(line["id"], ccf.KINDS[line["method"]])
            if line["method"] == "turn/start":
                self.t.begin_turn()
                self.by_turn.append([])
        elif ccf.is_response(line) and isinstance(line.get("result"), dict) and "decision" in line["result"]:
            if line["id"] not in self.asked:          # the tracker stopped before it: nothing to answer
                return
            self.decisions.append((line["id"], line["result"]["decision"]))
            (self.t.approve if line["result"]["decision"] == "accept" else self.t.refuse)(self.asked[line["id"]])

    def feed(self, line):
        out = self.t.on_message(line)
        self.facts += out
        if self.by_turn:
            self.by_turn[-1] += out
        for kind, data in out:
            if kind == "approval_request":
                self.asked[data["request_id"]] = data["item_id"]
        return out

    def kinds(self):
        return [k for k, _ in self.facts]

    def of(self, kind, facts=None):
        return [d for k, d in (self.facts if facts is None else facts) if k == kind]

    def tokens_by_turn(self):
        return [[d["tokens"] for d in self.of("turn_completed", f)] for f in self.by_turn]


class TrackerRecordingTests(unittest.TestCase):
    """The facts for the three recordings, line by line against the plan's "P38-0 實測事實"."""

    def test_c_a_file_change_in_the_legacy_sandbox(self):
        r = Replay("c-legacy-sandbox").run()
        self.assertNotIn("violation", r.kinds())
        self.assertNotIn("anomaly", [k for k in r.kinds()])
        self.assertEqual(r.of("initialized"), [{}])
        self.assertEqual(r.of("remote_control"), [{"disabled": True}])
        ready = r.of("session_ready")
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["thread_id"], "00000000-0000-4000-8000-000000000002")
        self.assertFalse(ready[0]["resumed"])
        (req,) = r.of("approval_request")
        self.assertEqual(req["kind"], "file_change")
        self.assertEqual(req["action"], "ask")
        self.assertEqual(req["request_id"], 0)
        self.assertEqual(req["item_id"], "exec-00000000-0000-4000-8000-000000000005")
        self.assertEqual(req["changes"], [{"path": ccf.WORK + "/note2.txt", "kind": {"type": "add"},
                                           "diff": "hello\n"}])
        (done,) = r.of("file_change_done")
        self.assertEqual((done["item_id"], done["status"]), (req["item_id"], "completed"))
        self.assertEqual([(d["total_tokens"], d["delta_tokens"]) for d in r.of("usage")],
                         [(18907, 18907), (37869, 18962)])
        (turn,) = r.of("turn_completed")
        self.assertEqual((turn["status"], turn["tokens"], turn["error"], turn["open_items"]),
                         ("completed", 37869, False, 0))
        self.assertEqual([x["phase"] for x in r.of("reply")], ["commentary", "final_answer"])
        self.assertTrue("".join(x["text"] for x in r.of("delta")))
        self.assertEqual(r.t.total_tokens, 37869)

    def test_b_a_resumed_process_does_not_count_the_repeated_total_again(self):
        r = Replay("b-resume").run()
        self.assertNotIn("violation", r.kinds())
        self.assertTrue(r.of("session_ready")[0]["resumed"])
        usage = r.of("usage")
        # The first count after the resume repeats the last total (280,605): no new tokens.
        self.assertEqual([(d["total_tokens"], d["delta_tokens"]) for d in usage],
                         [(280605, 0), (300217, 19612), (319923, 19706), (339708, 19785)])
        self.assertTrue(usage[0]["baseline"])
        self.assertFalse(any(d["baseline"] for d in usage[1:]))
        self.assertEqual(r.tokens_by_turn(), [[19612], [39491]])
        # The file change failed (the permission profile of that recording): a status, not a violation.
        (done,) = r.of("file_change_done")
        self.assertEqual(done["status"], "failed")
        self.assertEqual(r.of("thread_deleted"), [{"thread_id": "00000000-0000-4000-8000-000000000002"}])

    def test_b_with_the_last_total_known_the_repeat_is_nothing_new_either(self):
        r = Replay("b-resume", last_total=280605).run()
        usage = r.of("usage")
        self.assertEqual([d["delta_tokens"] for d in usage], [0, 19612, 19706, 19785])
        self.assertFalse(usage[0]["baseline"])
        self.assertEqual(r.tokens_by_turn(), [[19612], [39491]])

    def test_a_seven_turns_in_one_process(self):
        r = Replay("a").run()
        self.assertNotIn("violation", r.kinds())
        self.assertNotIn("anomaly", r.kinds())
        self.assertEqual(r.tokens_by_turn(), [[18104], [36426], [55308], [37290], [37641], [38012], [57824]])
        reqs = r.of("approval_request")
        self.assertEqual([(q["kind"], q["action"]) for q in reqs],
                         [("command", "ask")] * 4 + [("file_change", "ask"), ("file_change", "deny")] +
                         [("command", "ask")] * 2)
        outside = "/Users/fake-user/projects/outside-fake"
        self.assertEqual([q["command"] for q in reqs if q["kind"] == "command"], [
            "/bin/zsh -lc 'ls -a'", "/bin/zsh -lc 'echo original > shell.txt'",
            "/bin/zsh -lc 'echo changed-by-user > shell.txt'", "/bin/zsh -lc 'rm shell.txt'",
            f"/bin/zsh -lc 'echo x > {outside}/shell-out.txt'", f"/bin/zsh -lc 'cat {outside}/secret.txt'"])
        self.assertEqual([d for _, d in r.decisions],
                         ["accept", "decline", "accept", "decline", "accept", "decline", "accept", "accept"])

    def test_a_the_command_asks_carry_what_a_card_shows(self):
        r = Replay("a").run()
        first = r.of("approval_request")[0]
        self.assertEqual(first["command"], "/bin/zsh -lc 'ls -a'")
        self.assertEqual(first["cwd"], ccf.WORK)
        self.assertEqual(first["actions"], [{"type": "listFiles", "command": "ls -a"}])
        self.assertEqual(first["request_id"], 0)
        self.assertEqual(first["why"], "每個指令都要你允許才會執行")

    def test_a_a_changed_command_comes_back_as_a_new_request_in_the_same_turn(self):
        r = Replay("a").run()
        turn = r.by_turn[2]                                    # "echo original", declined, steered, asked again
        asks = r.of("approval_request", turn)
        self.assertEqual([q["command"] for q in asks],
                         ["/bin/zsh -lc 'echo original > shell.txt'", "/bin/zsh -lc 'echo changed-by-user > shell.txt'"])
        self.assertNotEqual(asks[0]["item_id"], asks[1]["item_id"])
        self.assertNotEqual(asks[0]["request_id"], asks[1]["request_id"])
        self.assertEqual([d for d in r.decisions if d[0] in (asks[0]["request_id"], asks[1]["request_id"])],
                         [(1, "decline"), (2, "accept")])
        self.assertEqual([x["status"] for x in r.of("command_done", turn)], ["declined", "completed"])
        self.assertEqual(r.of("steer_accepted", turn), [{"turn_id": "00000000-0000-4000-8000-000000000011"}])
        self.assertEqual(len(r.of("turn_completed", turn)), 1)

    def test_a_a_declined_command_is_not_a_violation_and_the_file_stays(self):
        r = Replay("a").run()
        turn = r.by_turn[3]
        self.assertEqual([x["status"] for x in r.of("command_done", turn)], ["declined"])

    def test_a_a_file_change_outside_the_work_folder_is_refused_by_vbear_itself(self):
        r = Replay("a").run()
        outside = r.of("approval_request", r.by_turn[5])
        self.assertEqual(len(outside), 1)
        self.assertEqual(outside[0]["action"], "deny")
        self.assertEqual(outside[0]["changes"][0]["path"], "/Users/fake-user/projects/outside-fake/patched.txt")
        self.assertEqual(r.of("file_change_done", r.by_turn[5]),
                         [{"item_id": outside[0]["item_id"], "status": "declined"}])

    def test_a_items_that_never_completed_are_not_a_violation(self):
        # The sandbox stopped both commands of the last turn: they were started, asked about and allowed, and have
        # no item/completed. The turn ends as usual.
        r = Replay("a").run()
        last = r.by_turn[6]
        self.assertEqual(len(r.of("approval_request", last)), 2)
        self.assertEqual(r.of("command_done", last), [])
        (turn,) = r.of("turn_completed", last)
        self.assertEqual((turn["status"], turn["open_items"]), ("completed", 2))
        self.assertNotIn("violation", [k for k, _ in last])

    def test_a_plan_use_is_only_the_window_numbers(self):
        r = Replay("a").run()
        first = r.of("plan_usage")[0]
        self.assertEqual(first, {"primary_pct": 6, "primary_window_min": 300, "primary_resets_at": 1793943244,
                                 "secondary_pct": 27, "secondary_window_min": 10080,
                                 "secondary_resets_at": 1794454231, "reached": None})

    def test_deltas_are_the_replys_pieces_in_order(self):
        r = Replay("a").run()
        first = r.by_turn[0]
        self.assertEqual([d["text"] for d in r.of("delta", first)], ["pine", "apple"])
        self.assertEqual([(d["phase"], d["text"]) for d in r.of("reply", first)], [("final_answer", "pineapple")])

    def test_what_a_persons_own_codex_setup_brings_in_stops_the_chat(self):
        # Without ``clean`` the recordings hold the person's AGENTS.md, five MCP servers and network access.
        for name in ("a", "b-resume", "c-legacy-sandbox"):
            r = Replay(name, clean=False).run()
            violations = r.of("violation")
            self.assertEqual(len(violations), 1, name)
            self.assertTrue(r.t.stopped)
            self.assertEqual(r.facts[-1][0], "violation", name)       # nothing after it is read
            self.assertNotIn("turn_completed", r.kinds(), name)

    def test_nothing_sensitive_is_in_any_fact(self):
        for name in ("a", "b-resume", "c-legacy-sandbox"):
            for clean in (True, False):
                text = json.dumps(Replay(name, clean=clean).run().facts, ensure_ascii=False)
                for secret in ccf.SENSITIVE:
                    self.assertNotIn(secret, text, (name, clean, secret))


# ---- shapes the recordings do not hold ---------------------------------------------------------------------------

ITEM_CMD = "exec-00000000-0000-4000-8000-0000000000aa"
ITEM_FILE = "exec-00000000-0000-4000-8000-0000000000bb"


def note(method, **params):
    return {"method": method, "params": params}


def item_msg(method, item_type, item_id="item-1", **fields):
    return note(method, threadId=THREAD, turnId="turn-1", item=dict({"type": item_type, "id": item_id}, **fields))


def cmd_request(rid=0, **over):
    params = {"kind": "command", "threadId": THREAD, "turnId": "turn-1", "itemId": ITEM_CMD, "environmentId": "local",
              "command": "/bin/zsh -lc 'ls'", "cwd": ccf.WORK, "commandActions": [], "startedAtMs": 1,
              "proposedExecpolicyAmendment": ["ls"], "availableDecisions": ["accept", "cancel"]}
    params.update(over)
    return {"method": "item/commandExecution/requestApproval", "id": rid, "params": params}


def file_request(rid=1, **over):
    params = {"threadId": THREAD, "turnId": "turn-1", "itemId": ITEM_FILE, "startedAtMs": 1, "reason": None,
              "grantRoot": None}
    params.update(over)
    return {"method": "item/fileChange/requestApproval", "id": rid, "params": params}


class Drive:
    """A tracker already past the handshake, fed by hand."""

    def __init__(self, *, resumed=False, last_total=None, work=ccf.WORK):
        self.work = work
        self.t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=work, codex_home=ccf.CODEX_HOME,
                                  thread_id=THREAD if resumed else None, resumed=resumed, last_total=last_total)
        self.facts = []
        self.t.expect(1, "initialize")
        self.feed(init_result())
        self.t.expect(2, "thread_resume" if resumed else "thread_start")
        self.feed(thread_result(work=work))

    def feed(self, msg):
        out = self.t.on_message(msg)
        self.facts += out
        return out

    def kinds(self, out):
        return [k for k, _ in out]


def violation_of(msg_or_list, *, setup=None):
    d = Drive()
    if setup:
        setup(d)
    out = []
    for m in msg_or_list if isinstance(msg_or_list, list) else [msg_or_list]:
        out = d.feed(m)
    return d, out


class HandshakeTests(unittest.TestCase):
    def test_a_good_handshake_gives_the_ready_facts_and_nothing_else(self):
        d = Drive()
        self.assertEqual(d.kinds(d.facts), ["initialized", "session_ready"])
        self.assertEqual(d.facts[1][1], {"thread_id": THREAD, "resumed": False, "model": "gpt-6.1-sol"})
        self.assertTrue(d.t.ready)

    def test_codex_home_must_be_the_folder_vbear_gave(self):
        t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home="/tmp/vb-own-home")
        t.expect(1, "initialize")
        (kind, data), = t.on_message(init_result())
        self.assertEqual(kind, "violation")
        self.assertNotIn("fake-user", json.dumps(data))
        self.assertNotIn("vb-own-home", json.dumps(data))
        t2 = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home=ccf.CODEX_HOME)
        t2.expect(1, "initialize")
        self.assertEqual(t2.on_message(init_result(codexHome=None))[0][0], "violation")

    def test_each_departure_from_the_settings_vbear_asked_for_stops_the_chat(self):
        sandbox = thread_result()["result"]["sandbox"]
        cases = {
            "on-request policy": dict(approvalPolicy="on-request"),
            "never policy": dict(approvalPolicy="never"),
            "granular policy": dict(approvalPolicy={"granular": {"rules": True}}),
            "no policy": dict(approvalPolicy=None),
            "auto review": dict(approvalsReviewer="auto_review"),
            "read-only sandbox": dict(sandbox={"type": "readOnly"}),
            "full access": dict(sandbox={"type": "dangerFullAccess"}),
            "network on": dict(sandbox=dict(sandbox, networkAccess=True)),
            "extra roots": dict(sandbox=dict(sandbox, writableRoots=["/Users/fake-user"])),
            # the sandbox must be field for field what VBear asked for: five fields, no more, no less
            "no writableRoots": dict(sandbox={k: v for k, v in sandbox.items() if k != "writableRoots"}),
            "writableRoots null": dict(sandbox=dict(sandbox, writableRoots=None)),
            "writableRoots a string": dict(sandbox=dict(sandbox, writableRoots="")),
            "no networkAccess": dict(sandbox={k: v for k, v in sandbox.items() if k != "networkAccess"}),
            "networkAccess a string": dict(sandbox=dict(sandbox, networkAccess="false")),
            "networkAccess zero": dict(sandbox=dict(sandbox, networkAccess=0)),
            "slash tmp writable": dict(sandbox=dict(sandbox, excludeSlashTmp=False)),
            "no excludeSlashTmp": dict(sandbox={k: v for k, v in sandbox.items() if k != "excludeSlashTmp"}),
            "tmpdir writable": dict(sandbox=dict(sandbox, excludeTmpdirEnvVar=False)),
            "no excludeTmpdirEnvVar": dict(sandbox={k: v for k, v in sandbox.items() if k != "excludeTmpdirEnvVar"}),
            "excludeSlashTmp one": dict(sandbox=dict(sandbox, excludeSlashTmp=1)),
            "extra field": dict(sandbox=dict(sandbox, readOnlyAccess={"type": "fullAccess"})),
            "type of another case": dict(sandbox=dict(sandbox, type="workspacewrite")),
            "sandbox a list": dict(sandbox=[]),
            "no sandbox": dict(sandbox=None),
            "other folder": dict(cwd="/tmp/elsewhere"),
            "instruction source": dict(instructionSources=["/Users/fake-user/.codex/AGENTS.md"]),
            "sources not a list": dict(instructionSources=None),
        }
        for name, over in cases.items():
            t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home=ccf.CODEX_HOME)
            t.expect(2, "thread_start")
            out = t.on_message(thread_result(**over))
            self.assertEqual([k for k, _ in out], ["violation"], name)
            self.assertTrue(t.stopped, name)
            self.assertNotIn("AGENTS", json.dumps(out), name)
            self.assertNotIn("fake-user", json.dumps(out), name)
            self.assertEqual(t.on_message(note("turn/started", threadId=THREAD, turn={"id": "t"})), [], name)

    def test_the_work_folder_may_be_named_through_a_link(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="vbl"))
        self.addCleanup(shutil.rmtree, tmp, True)
        real = os.path.join(tmp, "real")
        os.makedirs(real)
        os.symlink(real, os.path.join(tmp, "via"))
        t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=os.path.join(tmp, "via"), codex_home=ccf.CODEX_HOME)
        t.expect(2, "thread_start")
        self.assertEqual(t.on_message(thread_result(work=real))[0][0], "session_ready")

    def test_a_thread_answer_with_a_bad_or_other_id_is_a_violation(self):
        for bad in (None, "x", "00000000-0000-4000-8000-00000000000G", 5):
            t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home=ccf.CODEX_HOME)
            t.expect(2, "thread_start")
            self.assertEqual(t.on_message(thread_result(thread_id=bad))[0][0], "violation", bad)
        t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home=ccf.CODEX_HOME, thread_id=THREAD,
                             resumed=True)
        t.expect(2, "thread_resume")
        self.assertEqual(t.on_message(thread_result(thread_id="00000000-0000-4000-8000-000000000009"))[0][0],
                         "violation")

    def test_a_second_thread_start_in_one_process_is_a_violation(self):
        d = Drive()
        d.t.expect(5, "thread_start")
        out = d.feed(dict(thread_result(thread_id="00000000-0000-4000-8000-000000000009"), id=5))
        self.assertEqual(d.kinds(out), ["violation"])

    def test_a_thread_started_for_another_thread_is_a_violation(self):
        d, out = violation_of(note("thread/started", thread={"id": "00000000-0000-4000-8000-000000000009"}))
        self.assertEqual(d.kinds(out), ["violation"])
        d, out = violation_of(note("thread/started", thread={"id": THREAD}))
        self.assertEqual(out, [])

    def test_a_thread_started_before_the_answer_must_be_the_answers_thread(self):
        t = ccp.CodexTracker(ccp.VERSIONS["0.163.0"], workdir=ccf.WORK, codex_home=ccf.CODEX_HOME)
        t.expect(2, "thread_start")
        self.assertEqual(t.on_message(note("thread/started", thread={"id": THREAD})), [])
        self.assertEqual(t.on_message(thread_result(thread_id="00000000-0000-4000-8000-000000000009"))[0][0],
                         "violation")

    def test_events_of_another_thread_stop_the_chat(self):
        other = "00000000-0000-4000-8000-000000000009"
        for msg in (note("turn/started", threadId=other, turn={"id": "t"}),
                    note("item/agentMessage/delta", threadId=other, itemId="i", delta="x"),
                    note("thread/tokenUsage/updated", threadId=other, turnId="t",
                         tokenUsage={"total": {"totalTokens": 5}}),
                    cmd_request(threadId=other)):
            d, out = violation_of(msg)
            self.assertEqual(d.kinds(out), ["violation"], msg)

    def test_a_remote_control_that_is_not_disabled_stops_the_chat(self):
        d, out = violation_of(note("remoteControl/status/changed", status="disabled", serverName="fake-host",
                                   installationId="x", environmentId=None))
        self.assertEqual(out, [("remote_control", {"disabled": True})])
        for status in ("enabled", "connecting", None, 0):
            d, out = violation_of(note("remoteControl/status/changed", status=status, serverName="fake-host"))
            self.assertEqual(d.kinds(out), ["violation"], status)
            self.assertNotIn("fake-host", json.dumps(out))

    def test_an_mcp_server_in_any_state_stops_the_chat(self):
        for status in ("starting", "ready", "failed"):
            d, out = violation_of(note("mcpServer/startupStatus/updated", threadId=THREAD, name="fake-mcp-1",
                                       status=status, error=None, failureReason=None))
            self.assertEqual(d.kinds(out), ["violation"], status)
            self.assertNotIn("fake-mcp", json.dumps(out))

    def test_the_mcp_list_must_be_empty(self):
        d = Drive()
        d.t.expect(7, "mcp_list")
        self.assertEqual(d.feed({"id": 7, "result": {"data": []}}), [("mcp_checked", {"count": 0})])
        for result in ({"data": [{"name": "fake-mcp-1"}]}, {"data": None}, {}, None):
            d = Drive()
            d.t.expect(7, "mcp_list")
            out = d.feed({"id": 7, "result": result})
            self.assertEqual(d.kinds(out), ["violation"], result)
            self.assertNotIn("fake-mcp", json.dumps(out))

    def test_the_setting_notifications_cannot_change_what_the_answer_said(self):
        base = {"cwd": ccf.WORK, "approvalPolicy": "untrusted", "approvalsReviewer": "user",
                "sandboxPolicy": thread_result()["result"]["sandbox"], "model": "gpt-6.1-sol", "effort": "low",
                "personality": "pragmatic"}
        d = Drive()
        self.assertEqual(d.feed(note("thread/settings/updated", threadId=THREAD, threadSettings=base)), [])
        # a model or effort change is not a safety setting
        self.assertEqual(d.feed(note("thread/settings/updated", threadId=THREAD,
                                     threadSettings=dict(base, model="gpt-6.1-terra", effort="max"))), [])
        for key, value in (("approvalPolicy", "on-request"), ("approvalPolicy", "never"),
                           ("approvalsReviewer", "auto_review"), ("cwd", "/tmp/elsewhere"),
                           ("sandboxPolicy", {"type": "dangerFullAccess"}),
                           ("sandboxPolicy", dict(base["sandboxPolicy"], networkAccess=True)),
                           ("sandboxPolicy", dict(base["sandboxPolicy"], excludeSlashTmp=False)),
                           ("sandboxPolicy", dict(base["sandboxPolicy"], excludeTmpdirEnvVar=False)),
                           ("sandboxPolicy", dict(base["sandboxPolicy"], networkAccess="false")),
                           ("sandboxPolicy", dict(base["sandboxPolicy"], readOnlyAccess={})),
                           ("sandboxPolicy", {k: v for k, v in base["sandboxPolicy"].items() if k != "writableRoots"}),
                           ("activePermissionProfile", {"id": "other"})):
            d = Drive()
            out = d.feed(note("thread/settings/updated", threadId=THREAD, threadSettings=dict(base, **{key: value})))
            self.assertEqual(d.kinds(out), ["violation"], (key, value))
        d = Drive()
        self.assertEqual(d.kinds(d.feed(note("thread/settings/updated", threadId=THREAD, threadSettings=None))),
                         ["anomaly"])

    def test_an_error_answer_is_a_fact_without_its_message(self):
        d = Drive()
        d.t.expect(9, "turn_steer")
        out = d.feed({"id": 9, "error": {"code": -32600, "message": "expected turn id /Users/fake-user/x"}})
        self.assertEqual(out, [("request_failed", {"kind": "turn_steer", "code": -32600})])
        self.assertNotIn("fake-user", json.dumps(out))

    def test_an_answer_to_nothing_vbear_asked_is_an_anomaly(self):
        d = Drive()
        self.assertEqual(d.kinds(d.feed({"id": 77, "result": {"x": 1}})), ["anomaly"])
        with self.assertRaises(ValueError):
            d.t.expect(1, "model_list")


class ItemTests(unittest.TestCase):
    def test_item_kinds_a_chat_does_not_open_stop_it(self):
        for typ in ("mcpToolCall", "webSearch", "collabAgentToolCall", "dynamicToolCall", "imageView",
                    "imageGeneration", "hookPrompt", "functionCallOutput", "sleep", "enteredReviewMode", "?"):
            for method in ("item/started", "item/completed"):
                d, out = violation_of(item_msg(method, typ, server="fake-mcp-1"))
                self.assertEqual(d.kinds(out), ["violation"], (typ, method))
                self.assertNotIn("fake-mcp", json.dumps(out))
        for typ in ("userMessage", "reasoning", "plan"):
            d, out = violation_of(item_msg("item/started", typ))
            self.assertEqual(out, [], typ)

    def test_a_command_that_completed_without_vbears_yes_stops_the_chat(self):
        d, out = violation_of([item_msg("item/started", "commandExecution", ITEM_CMD, status="inProgress"),
                               item_msg("item/completed", "commandExecution", ITEM_CMD, status="completed",
                                        exitCode=0, aggregatedOutput="x")])
        self.assertEqual(d.kinds(out), ["violation"])

    def test_a_declined_command_that_completed_anyway_stops_the_chat(self):
        d = Drive()
        d.feed(cmd_request())
        d.t.refuse(ITEM_CMD)
        out = d.feed(item_msg("item/completed", "commandExecution", ITEM_CMD, status="completed", exitCode=0))
        self.assertEqual(d.kinds(out), ["violation"])

    def test_an_allowed_command_completes_and_its_output_is_passed_on(self):
        d = Drive()
        d.feed(cmd_request())
        d.t.approve(ITEM_CMD)
        out = d.feed(item_msg("item/completed", "commandExecution", ITEM_CMD, status="completed", exitCode=0,
                              aggregatedOutput="a\nb\n"))
        self.assertEqual(out, [("command_done", {"item_id": ITEM_CMD, "status": "completed", "exit_code": 0,
                                                 "output": "a\nb\n"})])

    def test_a_declined_or_failed_item_without_a_yes_is_fine(self):
        for status in ("declined", "failed"):
            d, out = violation_of(item_msg("item/completed", "commandExecution", "c1", status=status))
            self.assertEqual(d.kinds(out), ["command_done"], status)
            d, out = violation_of(item_msg("item/completed", "fileChange", "f1", status=status, changes=[]))
            self.assertEqual(d.kinds(out), ["file_change_done"], status)

    def test_an_unknown_status_without_a_yes_stops_the_chat(self):
        for status in ("inProgress", "weird", None):
            d, out = violation_of(item_msg("item/completed", "fileChange", "f1", status=status, changes=[]))
            self.assertEqual(d.kinds(out), ["violation"], status)

    def test_a_file_change_that_completed_with_other_paths_than_the_card_showed_stops_the_chat(self):
        shown = [{"path": ccf.WORK + "/a.txt", "kind": {"type": "add"}, "diff": "x\n"}]
        for completed, bad in ((shown, False),
                               ([{"path": ccf.WORK + "/a.txt", "kind": {"type": "add"}, "diff": "other text\n"}], False),
                               ([{"path": ccf.WORK + "/b.txt", "kind": {"type": "add"}, "diff": "x\n"}], True),
                               (shown + [{"path": "/tmp/z", "kind": {"type": "add"}, "diff": ""}], True)):
            d = Drive()
            d.feed(item_msg("item/started", "fileChange", ITEM_FILE, status="inProgress", changes=shown))
            (_, req), = d.feed(file_request())
            self.assertEqual(req["action"], "ask")
            d.t.approve(ITEM_FILE)
            out = d.feed(item_msg("item/completed", "fileChange", ITEM_FILE, status="completed", changes=completed))
            self.assertEqual(d.kinds(out), ["violation" if bad else "file_change_done"], completed)

    def test_a_patch_update_replaces_the_changes_the_card_will_show(self):
        d = Drive()
        d.feed(item_msg("item/started", "fileChange", ITEM_FILE, status="inProgress", changes=[
            {"path": ccf.WORK + "/a.txt", "kind": {"type": "add"}, "diff": "x\n"}]))
        d.feed(note("item/fileChange/patchUpdated", threadId=THREAD, turnId="turn-1", itemId=ITEM_FILE,
                    changes=[{"path": "/etc/hosts", "kind": {"type": "add"}, "diff": "y\n"}]))
        (_, req), = d.feed(file_request())
        self.assertEqual(req["action"], "deny")
        self.assertEqual(req["changes"][0]["path"], "/etc/hosts")

    def test_open_items_are_counted_when_the_turn_ends_and_forgotten_after(self):
        d = Drive()
        d.feed(item_msg("item/started", "commandExecution", "c1", status="inProgress"))
        d.feed(item_msg("item/started", "commandExecution", "c2", status="inProgress"))
        d.feed(item_msg("item/started", "agentMessage", "m1", text="", phase="final_answer"))
        d.feed(item_msg("item/completed", "agentMessage", "m1", text="ok", phase="final_answer"))
        (_, done), = d.feed(note("turn/completed", threadId=THREAD, turn={"id": "t1", "status": "completed",
                                                                         "error": None}))
        self.assertEqual(done["open_items"], 2)
        (_, again), = d.feed(note("turn/completed", threadId=THREAD, turn={"id": "t2", "status": "completed",
                                                                          "error": None}))
        self.assertEqual(again["open_items"], 0)

    def test_a_turn_that_ended_in_an_error_or_was_interrupted_says_so(self):
        d = Drive()
        (_, done), = d.feed(note("turn/completed", threadId=THREAD, turn={"id": "t1", "status": "failed",
                                                                         "error": {"message": "boom"}}))
        self.assertEqual((done["status"], done["error"]), ("failed", True))
        self.assertNotIn("boom", json.dumps(done))
        (_, done), = d.feed(note("turn/completed", threadId=THREAD, turn={"id": "t1", "status": "interrupted",
                                                                         "error": None}))
        self.assertEqual((done["status"], done["error"]), ("interrupted", False))
        (_, done), = d.feed(note("turn/completed", threadId=THREAD, turn={"id": "t1", "status": "mystery"}))
        self.assertEqual(done["status"], "?")


class ApprovalRequestTests(unittest.TestCase):
    def test_a_command_is_asked_about_with_the_whole_command(self):
        d = Drive()
        long = "echo " + "x" * 5000
        (kind, req), = d.feed(cmd_request(7, command=long, commandActions=[
            {"type": "unknown", "command": long}, {"type": "search", "command": "rg a", "query": "a", "path": None}],
            reason="needs a look"))
        self.assertEqual(kind, "approval_request")
        self.assertEqual((req["request_id"], req["kind"], req["action"]), (7, "command", "ask"))
        self.assertEqual(req["command"], long)
        self.assertEqual(req["codex_reason"], "needs a look")
        self.assertEqual([a["type"] for a in req["actions"]], ["unknown", "search"])
        self.assertEqual(d.t.requests, {7: ITEM_CMD})

    def test_a_request_id_may_be_a_string(self):
        d = Drive()
        (_, req), = d.feed(cmd_request("req-9"))
        self.assertEqual(req["request_id"], "req-9")
        ccp.decision_line(req["request_id"], "accept")

    def test_a_command_that_needs_the_network_or_is_not_a_command_is_refused(self):
        d = Drive()
        (_, req), = d.feed(cmd_request(networkApprovalContext={"host": "example.invalid", "protocol": "https"}))
        self.assertEqual(req["action"], "deny")
        self.assertIn("連網", req["why"])
        (_, req), = d.feed(cmd_request(2, kind="writeStdin"))
        self.assertEqual(req["action"], "deny")
        (_, req), = d.feed(cmd_request(3, command=None))
        self.assertEqual(req["action"], "deny")
        (_, req), = d.feed(cmd_request(4, itemId=None))
        self.assertEqual(req["action"], "deny")

    def test_no_amendment_the_server_proposes_becomes_part_of_a_fact(self):
        d = Drive()
        (_, req), = d.feed(cmd_request(proposedExecpolicyAmendment=["ls", "-a"],
                                       proposedNetworkPolicyAmendments=[{"host": "example.invalid", "action": "allow"}],
                                       availableDecisions=["accept", {"acceptWithExecpolicyAmendment": {
                                           "execpolicy_amendment": ["ls", "-a"]}}, "cancel"]))
        text = json.dumps(req)
        for word in ("Amendment", "amendment", "example.invalid", "availableDecisions", "execpolicy"):
            self.assertNotIn(word, text)

    def test_a_file_change_is_asked_about_with_its_changes_found_by_item_id(self):
        d = Drive()
        changes = [{"path": ccf.WORK + "/note.txt", "kind": {"type": "add"}, "diff": "hello\n"}]
        d.feed(item_msg("item/started", "fileChange", ITEM_FILE, status="inProgress", changes=changes))
        (kind, req), = d.feed(file_request(5, reason="because"))
        self.assertEqual((kind, req["kind"], req["action"], req["item_id"], req["request_id"]),
                         ("approval_request", "file_change", "ask", ITEM_FILE, 5))
        self.assertEqual(req["changes"], changes)
        self.assertEqual(req["codex_reason"], "because")

    def test_a_file_change_with_no_item_or_outside_or_in_a_protected_folder_is_refused(self):
        d = Drive()
        (_, req), = d.feed(file_request())
        self.assertEqual((req["action"], req["changes"]), ("deny", []))
        for path in ("/Users/fake-user/outside/x.txt", ccf.WORK + "/.codex/config.toml", ccf.WORK + "/.git/hooks/h",
                     ccf.WORK + "/.agents/a.md", ccf.WORK + "/../x.txt"):
            d = Drive()
            d.feed(item_msg("item/started", "fileChange", ITEM_FILE, status="inProgress", changes=[
                {"path": path, "kind": {"type": "add"}, "diff": "x"}]))
            (_, req), = d.feed(file_request())
            self.assertEqual(req["action"], "deny", path)
            self.assertTrue(req["why"], path)

    def test_a_file_change_that_asks_for_a_whole_folder_is_refused(self):
        d = Drive()
        d.feed(item_msg("item/started", "fileChange", ITEM_FILE, status="inProgress", changes=[
            {"path": ccf.WORK + "/a.txt", "kind": {"type": "add"}, "diff": "x"}]))
        (_, req), = d.feed(file_request(grantRoot=ccf.WORK))
        self.assertEqual(req["action"], "deny")

    def test_a_file_change_too_big_for_a_card_is_refused(self):
        d = Drive()
        d.feed(item_msg("item/started", "fileChange", ITEM_FILE, status="inProgress", changes=[
            {"path": ccf.WORK + "/big.txt", "kind": {"type": "add"}, "diff": "x" * 20000}]))
        (_, req), = d.feed(file_request())
        self.assertEqual(req["action"], "deny")

    def test_every_other_server_request_is_known_by_name_and_to_be_answered_with_an_error(self):
        d = Drive()
        for i, method in enumerate(sorted(ccp.VERSIONS["0.163.0"].refused_requests)):
            (kind, data), = d.feed({"method": method, "id": 100 + i, "params": {"x": 1}})
            self.assertEqual((kind, data), ("unknown_request", {"request_id": 100 + i, "method": method,
                                                                "refused": True}))
            self.assertEqual(parsed(ccp.error_line(data["request_id"], "VBear 不接受這種請求"))["id"], 100 + i)
        self.assertEqual(sorted(ccp.VERSIONS["0.163.0"].refused_requests), [
            "account/chatgptAuthTokens/refresh", "applyPatchApproval", "attestation/generate", "execCommandApproval",
            "item/permissions/requestApproval", "item/tool/call", "item/tool/requestUserInput",
            "mcpServer/elicitation/request"])

    def test_a_request_of_an_unknown_kind_is_answered_with_an_error_too(self):
        d = Drive()
        (kind, data), = d.feed({"method": "item/brand/new", "id": "abc-1", "params": {"secret": "s"}})
        self.assertEqual((kind, data), ("unknown_request", {"request_id": "abc-1", "method": "item/brand/new",
                                                            "refused": False}))
        (kind, data), = d.feed({"method": "bad method!", "id": 3, "params": {}})
        self.assertEqual(data["method"], "?")
        self.assertEqual(d.t.stopped, False)

    def test_a_request_whose_id_cannot_be_answered_is_an_anomaly(self):
        d = Drive()
        for rid in (None, True, 1.5, [1], {"a": 1}, "has space"):
            out = d.feed({"method": "item/tool/call", "id": rid, "params": {}})
            self.assertEqual(d.kinds(out), ["anomaly"], rid)

    def test_a_resolved_request_is_forgotten(self):
        d = Drive()
        d.feed(cmd_request(4))
        self.assertIn(4, d.t.requests)
        self.assertEqual(d.feed(note("serverRequest/resolved", threadId=THREAD, requestId=4)),
                         [("request_resolved", {"request_id": 4})])
        self.assertNotIn(4, d.t.requests)


class TokenTests(unittest.TestCase):
    def usage(self, d, total, turn="turn-1"):
        return d.feed(note("thread/tokenUsage/updated", threadId=THREAD, turnId=turn, tokenUsage={
            "total": {"totalTokens": total, "inputTokens": total}, "last": {"totalTokens": 1},
            "modelContextWindow": 475000}))

    def test_a_new_thread_counts_from_nothing(self):
        d = Drive()
        d.t.begin_turn()
        self.assertEqual(self.usage(d, 18_104), [("usage", {"total_tokens": 18104, "delta_tokens": 18104,
                                                             "baseline": False})])
        self.usage(d, 36_298)
        self.assertEqual(d.t.turn_tokens, 36_298)
        d.t.begin_turn()
        self.assertEqual(d.t.turn_tokens, 0)
        self.usage(d, 54_530)
        self.assertEqual(d.t.turn_tokens, 18_232)
        self.assertEqual(d.t.total_tokens, 54_530)

    def test_a_resumed_thread_with_a_known_total_counts_only_the_new_tokens(self):
        d = Drive(resumed=True, last_total=280_605)
        d.t.begin_turn()
        self.assertEqual(self.usage(d, 280_605)[0][1]["delta_tokens"], 0)
        self.assertEqual(self.usage(d, 300_217)[0][1]["delta_tokens"], 19_612)
        self.assertEqual(d.t.turn_tokens, 19_612)

    def test_a_resumed_thread_with_no_known_total_takes_the_first_count_as_a_starting_line(self):
        d = Drive(resumed=True)
        d.t.begin_turn()
        (_, first), = self.usage(d, 280_605)
        self.assertEqual((first["delta_tokens"], first["baseline"]), (0, True))
        self.assertEqual(d.t.turn_tokens, 0)
        self.usage(d, 300_217)
        self.assertEqual(d.t.turn_tokens, 19_612)

    def test_a_total_that_goes_back_is_not_trusted_for_the_turn(self):
        d = Drive(last_total=1000)
        d.t.begin_turn()
        (_, got), = self.usage(d, 500)
        self.assertIsNone(got["delta_tokens"])
        self.assertIsNone(d.t.turn_tokens)
        (_, done), = d.feed(note("turn/completed", threadId=THREAD, turn={"id": "t", "status": "completed"}))
        self.assertIsNone(done["tokens"])
        d.t.begin_turn()                                     # the next turn counts again from the new total
        self.usage(d, 700)
        self.assertEqual(d.t.turn_tokens, 200)

    def test_a_count_that_is_not_a_number_is_an_anomaly(self):
        d = Drive()
        for bad in (None, "5", True, -1, 1.5, 10 ** 15):
            out = self.usage(d, bad)
            self.assertEqual(d.kinds(out), ["anomaly"], bad)
        out = d.feed(note("thread/tokenUsage/updated", threadId=THREAD, turnId="t", tokenUsage=None))
        self.assertEqual(d.kinds(out), ["anomaly"])
        self.assertEqual(d.t.turn_tokens, 0)


class PlanUseTests(unittest.TestCase):
    def test_only_the_window_numbers_and_the_reached_kind_are_kept(self):
        d = Drive()
        limits = {"limitId": "fake-limit", "limitName": "n", "planType": "fake_plan",
                  "credits": {"hasCredits": True, "unlimited": False, "balance": "12.5"},
                  "primary": {"usedPercent": 7, "windowDurationMins": 300, "resetsAt": 1793943244},
                  "secondary": {"usedPercent": 27, "windowDurationMins": 10080, "resetsAt": 1794454231},
                  "rateLimitReachedType": "workspace_member_usage_limit_reached", "individualLimit": None}
        (kind, got), = d.feed(note("account/rateLimits/updated", rateLimits=limits))
        self.assertEqual(kind, "plan_usage")
        self.assertEqual(got, {"primary_pct": 7, "primary_window_min": 300, "primary_resets_at": 1793943244,
                               "secondary_pct": 27, "secondary_window_min": 10080,
                               "secondary_resets_at": 1794454231, "reached": "workspace_member_usage_limit_reached"})
        text = json.dumps(got)
        for word in ("fake-limit", "fake_plan", "12.5", "credits"):
            self.assertNotIn(word, text)

    def test_missing_windows_and_odd_values_are_none_or_question_marks(self):
        d = Drive()
        (_, got), = d.feed(note("account/rateLimits/updated", rateLimits={
            "primary": None, "secondary": {"usedPercent": "x", "windowDurationMins": None, "resetsAt": -1},
            "rateLimitReachedType": "something_new"}))
        self.assertEqual(got, {"primary_pct": None, "primary_window_min": None, "primary_resets_at": None,
                               "secondary_pct": None, "secondary_window_min": None, "secondary_resets_at": None,
                               "reached": "?"})
        self.assertEqual(d.kinds(d.feed(note("account/rateLimits/updated", rateLimits=None))), ["anomaly"])

    def test_the_account_notification_makes_no_fact(self):
        d = Drive()
        self.assertEqual(d.feed(note("account/updated", authMode="chatgpt", planType="fake_plan")), [])


class UnknownTests(unittest.TestCase):
    def test_a_notification_of_an_unknown_kind_is_an_anomaly_of_its_names_only(self):
        d = Drive()
        (kind, data), = d.feed(note("thread/brand/new", secret="s3cret", other={"a": 1}))
        self.assertEqual(kind, "anomaly")
        self.assertEqual(data, {"event_type": "thread/brand/new", "fields": ["other", "secret"]})
        self.assertNotIn("s3cret", json.dumps(data))
        self.assertFalse(d.t.stopped)

    def test_known_notifications_that_say_nothing_make_no_fact(self):
        d = Drive()
        for method in ("turn/moderationMetadata", "thread/status/changed", "thread/readState/changed",
                       "turn/diff/updated", "item/reasoning/textDelta", "item/commandExecution/outputDelta"):
            self.assertEqual(d.feed(note(method, threadId=THREAD, metadata={"prompt": {"omnimod": "x"}})), [], method)

    def test_an_error_notification_is_a_fact_without_its_message(self):
        d = Drive()
        out = d.feed(note("error", threadId=THREAD, turnId="t", willRetry=True,
                          error={"message": "oops /Users/fake-user/x", "codexErrorInfo": None}))
        self.assertEqual(out, [("turn_error", {"will_retry": True})])

    def test_junk_never_raises(self):
        d = Drive()
        junk = [None, 5, "x", [], {}, {"method": None}, {"method": 5, "id": 1}, {"id": 1}, {"result": 1},
                {"method": "item/started", "params": None}, {"method": "item/started", "params": {"item": 5}},
                {"method": "item/started", "params": {"item": {"id": 5, "type": "agentMessage"}}},
                {"method": "item/completed", "params": {"item": {"id": "i", "type": "fileChange", "status": "completed",
                                                                  "changes": "no"}}},
                {"method": "turn/started", "params": {"turn": []}}, {"method": "turn/completed", "params": {}},
                {"method": "item/agentMessage/delta", "params": {"itemId": "i", "delta": 5}},
                {"method": "serverRequest/resolved", "params": {"requestId": []}},
                {"method": "thread/deleted", "params": {"threadId": 5}},
                {"method": "item/fileChange/requestApproval", "id": 1, "params": {"itemId": []}},
                {"method": "item/commandExecution/requestApproval", "id": 2, "params": {"commandActions": "x"}},
                {"method": "thread/tokenUsage/updated", "params": {"tokenUsage": {"total": []}}},
                {"method": "remoteControl/status/changed", "params": []}]
        for msg in junk:
            d.t.stopped = False
            out = d.feed(msg)
            self.assertIsInstance(out, list, msg)


if __name__ == "__main__":
    unittest.main()
