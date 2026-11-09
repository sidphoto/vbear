"""The AGY chat protocol (P46-1): what VBear writes to ``agy acp`` 1.5.3 in a chat, how it reads what comes back, and which
file changes and reads it answers itself. Pure: replayed from the synthetic transcripts (tests/agy_chat_fixtures.py,
tests/fixtures/agy-chat/); no process is started."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal

from tests import agy_chat_fixtures as fx
from vbear.runtime import agy_chat_protocol as acp

CONSTS = acp.VERSIONS["1.5.3"]
SESSION = fx.SESSION
OTHER_SESSION = fx.OTHER_SESSION


def parsed(line: bytes):
    """One stdin line as VBear writes it: exactly one JSON object and a newline, with ``jsonrpc`` "2.0"."""
    assert line.endswith(b"\n") and line.count(b"\n") == 1, line
    obj = json.loads(line)
    assert obj["jsonrpc"] == "2.0", obj
    return obj


class ConstantsTests(unittest.TestCase):
    def test_1_5_3_is_the_one_version_of_the_table(self):
        c = acp.VERSIONS["1.5.3"]
        self.assertEqual(c.version, "1.5.3")
        self.assertEqual(sorted(acp.VERSIONS), ["1.5.3"])
        self.assertIs(acp.constants_for("1.5.3"), c)
        self.assertIsNone(acp.constants_for("1.5.2"))
        self.assertIsNone(acp.constants_for(None))
        self.assertEqual(c.model_id, "gemini-3.8-flash-high")
        self.assertEqual(c.protocol_version, 1)

    def test_the_environment_is_exactly_six_names(self):
        self.assertEqual(acp.VERSIONS["1.5.3"].env_keys, ("PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME"))

    def test_the_settings_are_the_five_keys_of_the_design(self):
        self.assertEqual(acp.VERSIONS["1.5.3"].settings, {
            "toolPermission": "request-review", "allowNonWorkspaceAccess": False, "enableTerminalSandbox": True,
            "useG1Credits": False, "permissions": {"allow": [], "ask": [], "deny": []}})

    def test_the_settings_file_is_one_fixed_byte_string(self):
        c = acp.VERSIONS["1.5.3"]
        data = acp.settings_bytes(c)
        self.assertIsInstance(data, bytes)
        self.assertEqual(json.loads(data), c.settings)
        self.assertEqual(data, acp.settings_bytes(c))
        self.assertTrue(data.endswith(b"\n"))
        # the caller gets bytes, never the table's own dict to change
        c.settings_copy()["toolPermission"] = "auto"
        self.assertEqual(c.settings["toolPermission"], "request-review")

    def test_the_kinds_it_knows(self):
        c = acp.VERSIONS["1.5.3"]
        self.assertEqual(c.session_updates, frozenset({
            "agent_message_chunk", "agent_thought_chunk", "tool_call", "tool_call_update", "available_commands_update",
            "plan", "current_mode_update", "user_message_chunk", "config_option_update", "session_info_update"}))
        self.assertEqual(c.tool_kinds, frozenset({"read", "edit", "delete", "move", "search", "execute", "think", "fetch",
                                                  "switch_mode", "other"}))
        self.assertEqual(c.allow_option_kind, "allow_once")
        self.assertEqual(c.reject_option_kind, "reject_once")
        self.assertEqual(c.usage_fields, ("inputTokens", "outputTokens", "cachedReadTokens", "cachedWriteTokens",
                                          "thoughtTokens", "totalTokens"))
        self.assertEqual(c.usage_sum_fields, ("inputTokens", "cachedReadTokens", "outputTokens"))

    def test_options_that_are_known_and_never_chosen_are_named_in_one_constant(self):
        self.assertEqual(acp.NEVER_CHOSEN_OPTION_KINDS, frozenset({"allow_always", "reject_always"}))
        c = acp.VERSIONS["1.5.3"]
        self.assertTrue(acp.NEVER_CHOSEN_OPTION_KINDS.isdisjoint({c.allow_option_kind, c.reject_option_kind}))

    def test_what_may_not_be_in_the_home_or_the_work_folder(self):
        c = acp.VERSIONS["1.5.3"]
        self.assertEqual(c.home_forbidden, ("GEMINI.md", "AGENTS.md", "config/hooks.json", "config/skills",
                                            "config/workflows", "config/global_workflows", "config/plugins"))
        # what a real AGY 1.5.3 made in a fresh --gemini-dir (the second real run), one level at a time
        self.assertEqual(c.home_created, (
            "antigravity-cli", "antigravity-cli/annotations", "antigravity-cli/bin", "antigravity-cli/brain",
            "antigravity-cli/builtin", "antigravity-cli/cache", "antigravity-cli/conversation_summaries.db",
            "antigravity-cli/conversations", "antigravity-cli/crashes", "antigravity-cli/implicit", "antigravity-cli/installation_id",
            "antigravity-cli/jetbox_summaries_proto.pb", "antigravity-cli/jetski_state.pbtxt", "antigravity-cli/log",
            "antigravity-cli/settings.json", "config", "config/.migrated", "config/config.json", "config/mcp_config.json",
            "config/projects"))
        self.assertTrue(set(c.home_created).isdisjoint(c.home_forbidden))
        self.assertEqual(c.project_entries, (), "nothing is known to be made inside a project folder yet (a real run must show it)")
        self.assertEqual(c.forbidden_anywhere, ("hooks", "rules", "workflows", "global_workflows", "skills", "plugins", "settings",
                                                "gemini", "agents", "agent", "mcp_config"))
        self.assertEqual(c.workdir_forbidden, (".agents", ".agent", ".gemini", "GEMINI.md", "AGENTS.md"))

    def test_argv_is_the_fixed_tail_and_nothing_else(self):
        c = acp.VERSIONS["1.5.3"]
        self.assertEqual(acp.argv_for(c, "/s/agy-chat-home"),
                         ["acp", "--gemini-dir", "/s/agy-chat-home", "--sandbox", "--disable-telemetry"])
        self.assertEqual(acp.argv_for(c, "/s/agy-chat-home", shared="/s/shared"),
                         ["acp", "--gemini-dir", "/s/agy-chat-home", "--sandbox", "--disable-telemetry",
                          "--add-dir", "/s/shared"])

    def test_a_folder_that_cannot_be_a_command_line_argument_is_refused(self):
        c = acp.VERSIONS["1.5.3"]
        for bad in ("relative/x", "", None, 7, "/h/a\nb", "/h/a\0b", "/h/a\x7fb", "/h/a\ud800b", "-x", "/h/" + "a" * 5000):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.argv_for(c, bad)
            if bad is not None:                  # no shared folder is the ordinary case
                with self.assertRaises(ValueError, msg=repr(bad)):
                    acp.argv_for(c, "/s/agy-chat-home", shared=bad)


class LineTests(unittest.TestCase):
    def test_initialize_declares_no_file_system_and_no_terminal(self):
        self.assertEqual(parsed(acp.initialize_line(1)), {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": 1, "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}})

    def test_session_new_has_no_mcp_server_and_the_system_prompt_in_meta(self):
        self.assertEqual(parsed(acp.session_new_line(2, cwd="/w/work")), {
            "jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "/w/work", "mcpServers": []}})
        got = parsed(acp.session_new_line(2, cwd="/w/work", system_prompt="Be brief. 你好"))
        self.assertEqual(got["params"], {"cwd": "/w/work", "mcpServers": [],
                                         "_meta": {"antigravity": {"systemPrompt": {"append": "Be brief. 你好"}}}})

    def test_session_resume_carries_the_session_and_the_same_prompt(self):
        self.assertEqual(parsed(acp.session_resume_line(3, SESSION, cwd="/w/work")), {
            "jsonrpc": "2.0", "id": 3, "method": "session/resume",
            "params": {"sessionId": SESSION, "cwd": "/w/work", "mcpServers": []}})
        got = parsed(acp.session_resume_line(3, SESSION, cwd="/w/work", system_prompt="Be brief."))
        self.assertEqual(got["params"]["_meta"], {"antigravity": {"systemPrompt": {"append": "Be brief."}}})

    def test_set_model_names_only_the_model_of_the_table(self):
        c = acp.VERSIONS["1.5.3"]
        self.assertEqual(parsed(acp.set_model_line(4, SESSION, c)), {
            "jsonrpc": "2.0", "id": 4, "method": "session/set_model",
            "params": {"sessionId": SESSION, "modelId": "gemini-3.8-flash-high"}})

    def test_prompt_is_one_text_block(self):
        self.assertEqual(parsed(acp.prompt_line(5, SESSION, "hello 你好")), {
            "jsonrpc": "2.0", "id": 5, "method": "session/prompt",
            "params": {"sessionId": SESSION, "prompt": [{"type": "text", "text": "hello 你好"}]}})

    def test_cancel_is_a_notification_without_an_id(self):
        got = parsed(acp.cancel_line(SESSION))
        self.assertEqual(got, {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": SESSION}})
        self.assertNotIn("id", got)

    def test_the_methods_that_would_loosen_the_chat_cannot_be_written(self):
        # no function of the module writes these (tests/test_autonomy_guard.py rule 14h holds the module to it)
        for name in dir(acp):
            lowered = name.lower()
            self.assertNotRegex(lowered, r"set_mode(?!l)")     # set_model is the one that is written
            self.assertNotIn("config_option", lowered)
            self.assertNotIn("session_load", lowered)

    def test_what_cannot_be_written_is_refused(self):
        for bad in ("", "  ", None, 3, "x" * (acp.MAX_TEXT_BYTES + 1), "a\ud800b"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.prompt_line(1, SESSION, bad)
        with self.assertRaises(ValueError):
            acp.prompt_line(True, SESSION, "x")
        with self.assertRaises(ValueError):
            acp.prompt_line(1.5, SESSION, "x")
        for bad in ("not-a-uuid", "", None, 7, SESSION.upper()):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.prompt_line(1, bad, "x")
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.cancel_line(bad)
        for bad in ("relative", "", None, "/w/a\0b", "/w/a\nb"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.session_new_line(1, cwd=bad)
        with self.assertRaises(ValueError):
            acp.session_new_line(1, cwd="/w/work", system_prompt=" ")
        with self.assertRaises(ValueError):
            acp.session_new_line(1, cwd="/w/work", system_prompt="x" * (acp.MAX_INSTRUCTIONS_BYTES + 1))

    def test_request_ids_are_integers_or_plain_strings(self):
        self.assertEqual(parsed(acp.prompt_line("req-1", SESSION, "x"))["id"], "req-1")
        for bad in ("", "a b", "x" * 200, None, [1], {"a": 1}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.prompt_line(bad, SESSION, "x")


OPTIONS = [{"optionId": "allow", "kind": "allow_once"}, {"optionId": "deny", "kind": "reject_once"}]


class AnswerTests(unittest.TestCase):
    def test_allow_selects_the_allow_once_option(self):
        self.assertEqual(parsed(acp.answer_line(7, OPTIONS, "allow")), {
            "jsonrpc": "2.0", "id": 7, "result": {"outcome": {"outcome": "selected", "optionId": "allow"}}})

    def test_deny_selects_the_reject_once_option(self):
        self.assertEqual(parsed(acp.answer_line(7, OPTIONS, "deny"))["result"],
                         {"outcome": {"outcome": "selected", "optionId": "deny"}})

    def test_the_option_ids_are_the_ones_the_agent_gave_not_the_measured_ones(self):
        options = [{"optionId": "opt-yes-1", "kind": "allow_once"}, {"optionId": "opt-no-2", "kind": "reject_once"}]
        self.assertEqual(parsed(acp.answer_line("r", options, "allow"))["result"]["outcome"]["optionId"], "opt-yes-1")
        self.assertEqual(parsed(acp.answer_line("r", options, "deny"))["result"]["outcome"]["optionId"], "opt-no-2")

    def test_cancelled_is_the_cancelled_outcome(self):
        self.assertEqual(parsed(acp.answer_line(7, OPTIONS, "cancelled"))["result"], {"outcome": {"outcome": "cancelled"}})

    def test_an_always_option_is_never_selected_whatever_comes_first_or_last(self):
        for extra in ("allow_always", "reject_always"):
            for position in (0, 1, 2):
                options = list(OPTIONS)
                options.insert(position, {"optionId": f"x-{extra}", "kind": extra})
                for decision in DECISIONS:
                    line = parsed(acp.answer_line(1, options, decision))
                    chosen = line["result"]["outcome"].get("optionId")
                    self.assertNotEqual(chosen, f"x-{extra}", (extra, position, decision))
                    self.assertIn(chosen, (None, "allow", "deny"))

    def test_any_other_kind_is_never_selected(self):
        options = OPTIONS + [{"optionId": "weird", "kind": "allow_for_session"}, {"optionId": "z", "kind": 5}]
        for decision in DECISIONS:
            self.assertNotEqual(parsed(acp.answer_line(1, options, decision))["result"]["outcome"].get("optionId"), "weird")

    def test_deny_without_a_reject_once_option_is_cancelled(self):
        for options in ([{"optionId": "allow", "kind": "allow_once"}], [], [{"optionId": "a", "kind": "reject_always"}],
                        OPTIONS + [{"optionId": "deny2", "kind": "reject_once"}], None, "options", [7]):
            self.assertEqual(parsed(acp.answer_line(1, options, "deny"))["result"], {"outcome": {"outcome": "cancelled"}},
                             options)

    def test_allow_needs_exactly_one_allow_once_and_one_reject_once(self):
        for options in ([{"optionId": "deny", "kind": "reject_once"}], [{"optionId": "allow", "kind": "allow_once"}], [],
                        OPTIONS + [{"optionId": "allow2", "kind": "allow_once"}], OPTIONS + [{"optionId": "d2", "kind": "reject_once"}],
                        [{"optionId": "a", "kind": "allow_always"}, {"optionId": "b", "kind": "reject_always"}], None):
            with self.assertRaises(ValueError, msg=repr(options)):
                acp.answer_line(1, options, "allow")

    def test_the_options_are_judged_ok_the_same_way(self):
        c = acp.VERSIONS["1.5.3"]
        self.assertTrue(acp.options_ok(OPTIONS, c))
        self.assertTrue(acp.options_ok(OPTIONS + [{"optionId": "always", "kind": "allow_always"}], c))
        self.assertFalse(acp.options_ok([OPTIONS[0]], c))
        self.assertFalse(acp.options_ok(OPTIONS + [OPTIONS[0]], c))
        self.assertFalse(acp.options_ok(None, c))

    def test_only_allow_deny_and_cancelled_can_be_written(self):
        for bad in ("allow_always", "reject_always", "accept", "", None, 1, "ALLOW"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.answer_line(1, OPTIONS, bad)

    def test_the_option_id_must_be_a_plain_short_string(self):
        for ident in ("", "a" * 300, 5, None, "has\nnewline"):
            options = [{"optionId": ident, "kind": "allow_once"}, {"optionId": "deny", "kind": "reject_once"}]
            with self.assertRaises(ValueError, msg=repr(ident)):
                acp.answer_line(1, options, "allow")

    def test_an_error_answer_has_the_method_not_found_code(self):
        self.assertEqual(parsed(acp.error_line(9, "VBear 不接受這種請求")), {
            "jsonrpc": "2.0", "id": 9, "error": {"code": -32601, "message": "VBear 不接受這種請求"}})
        with self.assertRaises(ValueError):
            acp.error_line(9, "x", code=True)


DECISIONS = ("allow", "deny", "cancelled")


class EstimateTests(unittest.TestCase):
    """One turn costs (tokens / 1,000,000) x US$1.00, rounded up to the cent, at least US$0.01 (ADR 0005, shared with Codex)."""

    def test_worked_examples(self):
        for tokens, usd in ((1, "0.01"), (0, "0.01"), (19_612, "0.02"), (86_000, "0.09"), (10_000, "0.01"), (10_001, "0.02"),
                            (999_999, "1.00"), (1_000_000, "1.00"), (1_000_001, "1.01"), (2_500_000, "2.50")):
            self.assertEqual(acp.estimate_usd(tokens), Decimal(usd), tokens)

    def test_it_is_the_same_rule_as_codexs_and_the_constant_has_a_neutral_name(self):
        from vbear.runtime import codex_chat_protocol as ccp
        for tokens in (0, 5, 12_345, 987_654, 3_000_001):
            self.assertEqual(acp.estimate_usd(tokens), ccp.estimate_usd(tokens))
        self.assertEqual(ccp.TOKEN_USD_PER_MTOK, Decimal("1.00"))
        self.assertFalse(hasattr(ccp, "CODEX_USD_PER_MTOK"))

    def test_no_usable_token_count_is_an_error_for_the_session_to_turn_into_the_turn_cap(self):
        for bad in (None, -1, 1.5, True, "5", 10 ** 13):
            with self.assertRaises(ValueError, msg=repr(bad)):
                acp.estimate_usd(bad)


class Folders(unittest.TestCase):
    """A real temporary work folder, an outside folder and a shared folder, all under one root (no link leaves it)."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="vba"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.work = os.path.join(self.root, "work")
        self.out = os.path.join(self.root, "outside")
        self.shared = os.path.join(self.root, "shared")
        for d in (self.work, self.out, self.shared):
            os.mkdir(d)

    def touch(self, *parts, text="x"):
        path = os.path.join(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path


class JudgeFileChangeTests(Folders):
    def judge(self, paths, content="hello", **kw):
        return acp.judge_file_change(paths, content, self.work, **kw)

    def test_a_new_file_in_the_work_folder_is_asked(self):
        got = self.judge([os.path.join(self.work, "post.md")])
        self.assertEqual(got.action, "ask")
        self.assertIn("工作資料夾", got.reason)

    def test_an_existing_file_and_a_deep_path_are_asked(self):
        self.touch(self.work, "a", "b", "c.txt")
        self.assertEqual(self.judge([os.path.join(self.work, "a", "b", "c.txt")]).action, "ask")
        self.assertEqual(self.judge([os.path.join(self.work, "new", "deeper", "d.txt")]).action, "ask")

    def test_the_work_folder_itself_and_anything_outside_it_are_refused(self):
        for path in (self.work, os.path.join(self.out, "x.txt"), self.out, "/etc/passwd", self.root,
                     os.path.join(self.work, "..", "outside", "x.txt"), os.path.join(self.work + "-sibling", "x")):
            got = self.judge([path])
            self.assertEqual(got.action, "deny", path)
        self.assertIn("以外", self.judge([os.path.join(self.out, "x.txt")]).reason)

    def test_a_relative_path_is_refused(self):
        for path in ("post.md", "./post.md", "../outside/x", "sub/x"):
            self.assertEqual(self.judge([path]).action, "deny", path)

    def test_a_link_in_the_work_folder_is_followed(self):
        os.symlink(self.out, os.path.join(self.work, "out-link"))
        self.assertEqual(self.judge([os.path.join(self.work, "out-link", "x.txt")]).action, "deny")
        decoy = self.touch(self.out, "decoy.txt")
        os.symlink(decoy, os.path.join(self.work, "file-link"))
        self.assertEqual(self.judge([os.path.join(self.work, "file-link")]).action, "deny")
        os.symlink(os.path.join(self.work, "real"), os.path.join(self.work, "inner-link"))
        self.assertEqual(self.judge([os.path.join(self.work, "inner-link")]).action, "ask")

    def test_the_settings_folders_and_files_of_the_tools_are_refused_at_any_depth_in_any_case(self):
        for part in (".git", ".agents", ".agent", ".gemini", ".codex", ".claude", ".GIT", ".Agents", ".GeMiNi"):
            for rel in (os.path.join(part, "x"), os.path.join("a", part, "x"), os.path.join("a", "b", part, "c", "d"), part):
                got = self.judge([os.path.join(self.work, rel)])
                self.assertEqual(got.action, "deny", rel)
                self.assertIn("聊天裡不能改", got.reason)
        for name in ("GEMINI.md", "AGENTS.md", "gemini.md", "agents.MD", os.path.join("sub", "AGENTS.md")):
            self.assertEqual(self.judge([os.path.join(self.work, name)]).action, "deny", name)
        for name in ("GEMINI.md.bak", "my-AGENTS.md", "agents.txt", ".gitignore", ".agents-notes.txt", "gemini"):
            self.assertEqual(self.judge([os.path.join(self.work, name)]).action, "ask", name)

    def test_a_file_with_another_hard_link_is_refused(self):
        a = self.touch(self.work, "a.txt")
        os.link(a, os.path.join(self.work, "b.txt"))
        got = self.judge([os.path.join(self.work, "a.txt")])
        self.assertEqual(got.action, "deny")
        self.assertIn("硬連結", got.reason)
        self.assertEqual(self.judge([os.path.join(self.work, "c.txt")]).action, "ask")

    def test_one_bad_path_among_good_ones_refuses_all(self):
        good, bad = os.path.join(self.work, "a.txt"), os.path.join(self.work, ".git", "config")
        self.assertEqual(self.judge([good, bad]).action, "deny")
        self.assertEqual(self.judge([good, os.path.join(self.out, "x")]).action, "deny")
        self.assertEqual(self.judge([good, os.path.join(self.work, "b.txt")]).action, "ask")

    def test_no_path_or_a_path_that_is_not_a_usable_string_is_refused(self):
        for paths in ([], None, "path", [None], [""], [7], ["/w/a\0b"], [b"/w/x"], ["/" + "a" * 5000]):
            self.assertEqual(self.judge(paths).action, "deny", paths)

    def test_a_card_that_does_not_fit_is_refused(self):
        path = os.path.join(self.work, "big.txt")
        size = acp.MAX_CARD_BYTES - len(path.encode())
        self.assertEqual(self.judge([path], "x" * size).action, "ask")
        got = self.judge([path], "x" * (size + 1))
        self.assertEqual(got.action, "deny")
        self.assertIn("一張卡放不下", got.reason)
        self.assertEqual(self.judge([path], None).action, "ask")
        self.assertEqual(self.judge([path], "你" * (acp.MAX_CARD_BYTES // 3 + 1)).action, "deny")      # bytes, not characters

    def test_the_shared_folder_is_a_second_root_that_asks_with_its_own_sentence(self):
        got = self.judge([os.path.join(self.shared, "note.md")], shared=self.shared)
        self.assertEqual(got.action, "ask")
        self.assertIn("共用資料夾", got.reason)
        self.assertEqual(self.judge([os.path.join(self.shared, "note.md")]).action, "deny")      # not switched on
        self.assertIn("共用資料夾", self.judge([os.path.join(self.out, "x")], shared=self.shared).reason)

    def test_the_shared_folder_keeps_the_same_protected_names_a_hard_link_rule_and_its_own_edge(self):
        for rel in (".git/x", "a/.agents/x", ".agent", ".gemini/settings.json", ".codex", ".claude", "AGENTS.md", "sub/GEMINI.md"):
            self.assertEqual(self.judge([os.path.join(self.shared, rel)], shared=self.shared).action, "deny", rel)
        a = self.touch(self.shared, "a.txt")
        os.link(a, os.path.join(self.shared, "b.txt"))
        self.assertEqual(self.judge([a], shared=self.shared).action, "deny")
        self.assertEqual(self.judge([self.shared], shared=self.shared).action, "deny")
        os.symlink(self.touch(self.out, "decoy.txt"), os.path.join(self.shared, "link.txt"))
        self.assertEqual(self.judge([os.path.join(self.shared, "link.txt")], shared=self.shared).action, "deny")

    def test_a_shared_argument_that_is_not_a_path_means_no_shared_folder(self):
        for shared in (None, "", "relative", 7):
            self.assertEqual(self.judge([os.path.join(self.shared, "x")], shared=shared).action, "deny")


class JudgeReadTests(Folders):
    def judge(self, paths, **kw):
        return acp.judge_read(paths, self.work, **kw)

    def test_inside_the_work_folder_vbear_says_yes_itself(self):
        self.touch(self.work, "a.txt")
        self.assertEqual(self.judge([os.path.join(self.work, "a.txt")]).action, "allow")
        self.assertEqual(self.judge(["a.txt"]).action, "allow")                       # relative to the work folder
        self.assertEqual(self.judge([os.path.join(self.work, "missing", "x")]).action, "allow")
        self.assertEqual(self.judge([self.work]).action, "allow")

    def test_the_shared_folder_counts_as_inside_only_when_it_is_given(self):
        path = self.touch(self.shared, "note.md")
        self.assertEqual(self.judge([path], shared=self.shared).action, "allow")
        self.assertEqual(self.judge([path]).action, "ask")

    def test_outside_is_asked_with_the_sentence_that_says_it_goes_to_google(self):
        got = self.judge([os.path.join(self.out, "x.txt")])
        self.assertEqual(got.action, "ask")
        self.assertIn("Google", got.reason)
        self.assertEqual(self.judge(["../outside/x.txt"]).action, "ask")
        self.assertEqual(self.judge(["/etc/hosts"]).action, "ask")

    def test_a_link_is_followed_so_a_link_to_the_outside_is_asked(self):
        decoy = self.touch(self.out, "decoy.txt")
        os.symlink(decoy, os.path.join(self.work, "link.txt"))
        self.assertEqual(self.judge([os.path.join(self.work, "link.txt")]).action, "ask")
        self.assertEqual(self.judge(["link.txt"]).action, "ask")

    def test_one_outside_path_among_inside_ones_asks(self):
        self.assertEqual(self.judge([os.path.join(self.work, "a"), os.path.join(self.out, "b")]).action, "ask")

    def test_a_path_that_cannot_be_read_as_a_path_is_refused(self):
        for paths in ([], None, "x", [None], [""], [7], ["a\0b"], ["/" + "a" * 5000]):
            self.assertEqual(self.judge(paths).action, "deny", paths)


class Drive(Folders):
    """A tracker and a player of one synthetic script, driven the way a session drives a real process. Every test of the tracker
    is a ``Drive``: it makes the temporary folders, writes VBear's lines, feeds what the player prints back to the tracker."""

    def drive(self, fixture, vars=None, *, shared=False, session_id=None, resumed=False, consts=CONSTS):
        self.shared_path = self.shared if shared else None
        self.player = fx.Player(fixture, vars, work=self.work, shared=self.shared_path)
        self.t = acp.AgyTracker(consts, workdir=self.work, shared=self.shared_path, session_id=session_id, resumed=resumed)
        self.facts = []
        self.ids = 0
        self.feed(self.player.initial)
        return self

    def feed(self, outs):
        new = []
        for message in outs:
            new += self.t.on_message(message)
        self.facts += new
        return new

    def call(self, kind, build, *args, **kw):
        self.ids += 1
        self.t.expect(self.ids, kind)
        return self.feed(self.player.send(build(self.ids, *args, **kw)))

    def start(self, system_prompt=None):
        """initialize, session/new, session/set_model (or session/resume when the tracker was given a session)."""
        self.call("initialize", acp.initialize_line)
        if self.t.session_id and self.t.resumed:
            self.call("session_resume", acp.session_resume_line, self.t.session_id, cwd=self.work, system_prompt=system_prompt)
        else:
            self.call("session_new", acp.session_new_line, cwd=self.work, system_prompt=system_prompt)
        if self.t.session_id:
            self.call("set_model", acp.set_model_line, self.t.session_id, CONSTS)
        return self

    def prompt(self, text="hello"):
        self.t.begin_turn()
        return self.call("prompt", acp.prompt_line, self.t.session_id, text)

    def answer(self, decision, request=None):
        """Answers the last (or the given) permission request the way a session does: tell the tracker, write the line."""
        request = request or self.requests()[-1]
        self.t.answered(request["request_id"], decision)
        return self.feed(self.player.send(acp.answer_line(request["request_id"], request["options"], decision)))

    def of(self, kind):
        return [d for k, d in self.facts if k == kind]

    def requests(self):
        return self.of("permission_request")

    def kinds(self):
        return [k for k, _ in self.facts]

    def play(self, decision="allow", prompts=1):
        """Start, send ``prompts`` messages and answer every request with ``decision`` (VBear's own refusals with "deny")."""
        self.start()
        for _ in range(prompts):
            self.prompt()
            while self.player.awaiting is not None and "violation" not in self.kinds():
                request = self.requests()[-1]
                self.answer("deny" if request["action"] == "deny" else decision, request)
        return self

    def permission(self, kind="execute", raw_input=None, locations=None, content=None, **more):
        vars = {"KIND": kind}
        if raw_input is not None:
            vars["RAW_INPUT"] = raw_input
        if locations is not None:
            vars["LOCATIONS"] = locations
        if content is not None:
            vars["CONTENT"] = content
        vars.update(more)
        self.drive("permission", vars).start()
        self.prompt()
        return self.requests()[-1]

    def file_request(self, path, kind="edit", text="hello", **more):
        return self.permission(kind, {"Path": path, "Content": text}, [{"path": path}],
                               [{"type": "diff", "path": path, "oldText": None, "newText": text}], **more)


class HandshakeTests(Drive):
    def test_a_new_session_is_started_and_the_model_is_set(self):
        self.drive("text").start()
        self.assertEqual(self.kinds(), ["initialized", "session_ready", "commands", "model_set"])
        self.assertEqual(self.of("initialized"), [{"load_session": True}])
        self.assertEqual(self.of("session_ready"), [{"session_id": SESSION, "resumed": False}])
        self.assertEqual(self.of("commands"), [{"count": 3}])
        self.assertEqual(self.of("model_set"), [{"model": "gemini-3.8-flash-high"}])
        self.assertEqual(self.t.session_id, SESSION)
        self.assertTrue(self.t.ready)

    def test_the_lines_the_player_got_are_the_ones_of_the_design(self):
        self.drive("text").start(system_prompt="Be brief.")
        methods = [m["method"] for m in self.player.seen]
        self.assertEqual(methods, ["initialize", "session/new", "session/set_model"])
        self.assertEqual(self.player.unexpected, [])
        self.assertEqual(self.player.seen[1]["params"]["_meta"]["antigravity"]["systemPrompt"]["append"], "Be brief.")

    def test_nothing_the_agent_says_about_the_person_is_kept(self):
        self.drive("text").start()
        self.prompt()
        text = json.dumps(self.facts, ensure_ascii=False)
        for secret in fx.SENSITIVE:
            self.assertNotIn(secret, text, secret)

    def test_another_protocol_version_stops_the_chat(self):
        for result in ({"protocolVersion": 2, "agentCapabilities": {"sessionCapabilities": {"resume": {}}}},
                       {"protocolVersion": "1", "agentCapabilities": {"sessionCapabilities": {"resume": {}}}},
                       {"protocolVersion": True, "agentCapabilities": {"sessionCapabilities": {"resume": {}}}},
                       {"agentCapabilities": {"sessionCapabilities": {"resume": {}}}}):
            self.drive("text", {"INIT_RESULT": result})
            self.call("initialize", acp.initialize_line)
            self.assertEqual(self.kinds(), ["violation"], result)

    def test_an_agent_that_cannot_resume_stops_the_chat(self):
        for caps in ({}, {"sessionCapabilities": {}}, {"sessionCapabilities": {"load": {}}}, {"sessionCapabilities": []},
                     {"sessionCapabilities": "resume"}):
            self.drive("text", {"INIT_RESULT": {"protocolVersion": 1, "agentCapabilities": caps}})
            self.call("initialize", acp.initialize_line)
            self.assertEqual(self.kinds(), ["violation"], caps)
        self.drive("text", {"INIT_RESULT": {"protocolVersion": 1}})
        self.call("initialize", acp.initialize_line)
        self.assertEqual(self.kinds(), ["violation"])

    def test_a_session_id_that_is_not_a_uuid_stops_the_chat(self):
        for bad in ("not-a-uuid", "", 7, None, SESSION.upper(), "1", ["x"]):
            self.drive("text", {"SESSION_NEW": bad})
            self.call("initialize", acp.initialize_line)
            self.call("session_new", acp.session_new_line, cwd=self.work)
            self.assertIn("violation", self.kinds(), bad)
            self.assertNotIn("session_ready", self.kinds())

    def test_a_mode_other_than_default_or_no_mode_stops_the_chat(self):
        for modes in ({"currentModeId": "accept-edits"}, {"currentModeId": "plan"}, {"currentModeId": "Default"}, {}, None, "default",
                      {"currentModeId": None}):
            self.drive("text", {"MODES": modes})
            self.call("initialize", acp.initialize_line)
            self.call("session_new", acp.session_new_line, cwd=self.work)
            self.assertIn("violation", self.kinds(), modes)
            self.assertNotIn("session_ready", self.kinds())

    def test_a_model_list_without_the_models_id_is_an_invalid_model_and_no_session_is_ready(self):
        for models in ({"availableModels": [{"modelId": "gemini-4-argon-medium"}]}, {"availableModels": []}, {}, None, [],
                       {"availableModels": [{"modelId": "gemini-3.8-flash-high-x"}, {"id": "gemini-3.8-flash-high"}]}):
            self.drive("text", {"MODELS": models})
            self.call("initialize", acp.initialize_line)
            self.call("session_new", acp.session_new_line, cwd=self.work)
            self.assertIn("invalid_model", self.kinds(), models)
            self.assertNotIn("session_ready", self.kinds())
            self.assertNotIn("violation", self.kinds())
            self.assertFalse(self.t.ready)

    def test_set_model_must_answer_an_empty_object(self):
        for result in ({"modelId": "x"}, None, [], "ok", {"models": None}):
            self.drive("text", {"SET_MODEL_RESULT": result}).start()
            self.assertIn("violation", self.kinds(), result)
            self.assertNotIn("model_set", self.kinds())

    def test_no_prompt_before_the_model_is_set(self):
        self.drive("text")
        self.call("initialize", acp.initialize_line)
        self.call("session_new", acp.session_new_line, cwd=self.work)
        with self.assertRaises(ValueError):
            self.t.expect(9, "prompt")
        self.call("set_model", acp.set_model_line, self.t.session_id, CONSTS)
        self.t.expect(9, "prompt")

    def test_a_missing_sign_in_is_a_failed_request_that_says_so(self):
        self.drive("auth-error")
        self.call("initialize", acp.initialize_line)
        self.call("session_new", acp.session_new_line, cwd=self.work)
        self.assertEqual(self.of("request_failed"), [{"kind": "session_new", "code": -32000, "auth_required": True}])
        self.assertNotIn("violation", self.kinds())
        self.assertNotIn("Authentication", json.dumps(self.facts))

    def test_an_unknown_request_kind_and_unknown_ids_are_refused_or_noted(self):
        self.drive("text")
        with self.assertRaises(ValueError):
            self.t.expect(1, "session_load")
        self.assertEqual(self.t.on_message({"jsonrpc": "2.0", "id": 77, "result": {}})[0][0], "anomaly")

    def test_a_resumed_session_keeps_its_id_and_is_set_to_the_model_again(self):
        self.drive("resume", session_id=SESSION, resumed=True).start()
        self.assertEqual(self.kinds(), ["initialized", "session_ready", "commands", "model_set"])
        self.assertEqual(self.of("session_ready"), [{"session_id": SESSION, "resumed": True}])
        self.assertEqual([m["method"] for m in self.player.seen], ["initialize", "session/resume", "session/set_model"])
        self.assertEqual(self.player.seen[1]["params"]["sessionId"], SESSION)
        self.prompt()
        self.assertEqual(self.of("reply")[-1]["text"], "I remember.")
        self.assertNotIn("user_message_chunk", json.dumps(self.facts))

    def test_a_resume_that_names_another_session_stops_the_chat(self):
        self.drive("resume", session_id=SESSION, resumed=True)
        self.call("initialize", acp.initialize_line)
        self.t.expect(50, "session_resume")
        self.feed([{"jsonrpc": "2.0", "id": 50, "result": {"sessionId": OTHER_SESSION, "modes": {"currentModeId": "default"}}}])
        self.assertEqual(self.kinds()[-1], "violation")

    def test_a_resume_that_cannot_find_the_session_is_a_failed_request(self):
        self.drive("resume-missing", session_id=SESSION, resumed=True)
        self.call("initialize", acp.initialize_line)
        self.call("session_resume", acp.session_resume_line, SESSION, cwd=self.work)
        self.assertEqual(self.of("request_failed"), [{"kind": "session_resume", "code": -32602, "auth_required": False}])

    def test_a_resume_needs_the_session_id_and_a_new_session_does_not_take_one(self):
        t = acp.AgyTracker(CONSTS, workdir=self.work)
        with self.assertRaises(ValueError):
            t.expect(1, "session_resume")
        with self.assertRaises(ValueError):
            acp.AgyTracker(CONSTS, workdir=self.work, session_id="nope")
        t2 = acp.AgyTracker(CONSTS, workdir=self.work, session_id=SESSION, resumed=True)
        with self.assertRaises(ValueError):
            t2.expect(1, "session_new")

    def test_an_update_of_another_session_before_the_session_is_known_stops_the_chat(self):
        self.drive("text")
        self.call("initialize", acp.initialize_line)
        self.t.expect(60, "session_new")
        out = self.feed([{"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": OTHER_SESSION, "update": {"sessionUpdate": "plan", "entries": []}}},
            {"jsonrpc": "2.0", "id": 60, "result": {"sessionId": SESSION, "modes": {"currentModeId": "default"},
                                                     "models": {"availableModels": [{"modelId": fx.MODEL}]}}}])
        self.assertEqual([k for k, _ in out], ["violation"])


class TurnTests(Drive):
    def test_a_text_turn_gives_deltas_one_reply_and_the_turns_tokens(self):
        self.drive("text").start()
        self.prompt()
        self.assertEqual([d["text"] for d in self.of("delta")], ["Hello, ", "this is a made-up reply."])
        self.assertEqual(self.of("reply"), [{"text": "Hello, this is a made-up reply."}])
        self.assertEqual(self.of("turn_completed"), [{"stop_reason": "end_turn", "tokens": 86000, "usage_problem": None,
                                                      "open_calls": 0}])
        self.assertEqual(self.kinds()[-2:], ["reply", "turn_completed"])           # the reply is flushed before the end
        self.assertEqual(self.t.thoughts, 1)                                          # a thought is counted, never shown
        self.assertNotIn("made-up thought", json.dumps(self.facts))

    def test_a_second_turn_is_a_new_turn(self):
        self.drive("text").start()
        self.prompt()
        self.prompt("again")
        self.assertEqual([r["text"] for r in self.of("reply")], ["Hello, this is a made-up reply.", "Second made-up reply."])
        self.assertEqual(len(self.of("turn_completed")), 2)

    def test_the_turns_tokens_are_the_total_when_it_is_the_sum_of_the_three(self):
        self.drive("text", {"USAGE": {"inputTokens": 100, "outputTokens": 20, "cachedReadTokens": 7, "cachedWriteTokens": 3,
                                      "thoughtTokens": 5, "totalTokens": 127}}).start()
        self.prompt()
        self.assertEqual(self.of("turn_completed")[0]["tokens"], 127)
        self.assertIsNone(self.of("turn_completed")[0]["usage_problem"])

    def test_a_usage_that_cannot_be_trusted_has_no_tokens_and_says_why(self):
        base = {"inputTokens": 100, "outputTokens": 20, "cachedReadTokens": 7, "cachedWriteTokens": 0, "thoughtTokens": 5,
                "totalTokens": 127}
        cases = {
            "mismatch": [dict(base, totalTokens=128), dict(base, totalTokens=126), dict(base, totalTokens=0)],
            "invalid": [dict(base, totalTokens=127.0), dict(base, totalTokens=True), dict(base, totalTokens="127"),
                        dict(base, inputTokens=-1, totalTokens=26), dict(base, outputTokens=None), dict(base, cachedWriteTokens="0"),
                        dict(base, totalTokens=10 ** 13, inputTokens=10 ** 13 - 27), dict(base, thoughtTokens=1.5)],
            "missing": [None, {}, [], "usage", 5, {"totalTokens": 127}, {k: v for k, v in base.items() if k != "totalTokens"},
                        {k: v for k, v in base.items() if k != "inputTokens"}],
        }
        for problem, usages in cases.items():
            for usage in usages:
                self.drive("text", {"USAGE": usage}).start()
                self.prompt()
                done = self.of("turn_completed")[0]
                self.assertIsNone(done["tokens"], usage)
                self.assertEqual(done["usage_problem"], problem, usage)
                self.assertNotIn("violation", self.kinds())

    def test_a_cancelled_turn_still_has_its_usage(self):
        self.drive("cancel-idle").start()
        self.prompt()
        self.assertEqual(self.of("turn_completed"), [])
        self.feed(self.player.send(acp.cancel_line(SESSION)))
        done = self.of("turn_completed")[0]
        self.assertEqual((done["stop_reason"], done["tokens"]), ("cancelled", 86000))

    def test_stop_reasons_it_knows_and_one_it_does_not(self):
        for reason in ("end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"):
            self.drive("text", {"STOP": reason}).start()
            self.prompt()
            self.assertEqual(self.of("turn_completed")[0]["stop_reason"], reason)
        for reason in ("surprise", None, 3, ""):
            self.drive("text", {"STOP": reason}).start()
            self.prompt()
            self.assertEqual(self.of("turn_completed")[0]["stop_reason"], "?")

    def test_a_prompt_that_fails_is_a_failed_request(self):
        self.drive("text").start()
        self.t.begin_turn()
        self.t.expect(80, "prompt")
        out = self.feed([{"jsonrpc": "2.0", "id": 80, "error": {"code": -32603, "message": "boom with a secret detail"}}])
        self.assertEqual(out, [("request_failed", {"kind": "prompt", "code": -32603, "auth_required": False})])

    def test_the_echo_of_our_message_and_the_option_and_info_updates_are_known_and_keep_nothing(self):
        self.drive("unknown-update").start()
        self.prompt()
        self.assertEqual(self.of("anomaly"), [])
        self.assertNotIn("replayed", json.dumps(self.facts))
        self.assertEqual(self.of("reply")[-1]["text"], "Fine.")
        self.assertNotIn("violation", self.kinds())
        for update in ({"sessionUpdate": "session_info_update", "title": "Made-up title", "updatedAt": "2026-01-01T00:00:00Z"},
                       {"sessionUpdate": "config_option_update", "configOptions": [{"id": "x", "currentValue": "made-up"}]},
                       {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "echo of the message"}}):
            out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": update}})
            self.assertEqual(out, [], update["sessionUpdate"])

    def test_an_unknown_update_and_a_message_that_is_not_text_are_anomalies(self):
        self.drive("text").start()
        self.prompt()
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": SESSION, "update": {"sessionUpdate": "made_up_update", "configOptions": [], "secret": "x"}}})
        self.assertEqual([(k, d["event_type"], d["fields"]) for k, d in out],
                         [("anomaly", "made_up_update", ["configOptions", "secret", "sessionUpdate"])])
        self.assertNotIn("violation", self.kinds())
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": SESSION, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "image", "data": "x"}}}})
        self.assertEqual([k for k, _ in out], ["anomaly"])
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": "x"}})
        self.assertEqual([k for k, _ in out], ["anomaly"])

    def test_a_notification_of_another_method_and_a_malformed_line_are_anomalies_that_stop_nothing(self):
        self.drive("text").start()
        for message in ({"jsonrpc": "2.0", "method": "session/surprise", "params": {"a": 1}}, ["x"], "line", None, 5, {},
                        {"jsonrpc": "2.0", "method": "session/update", "params": "x"},
                        {"jsonrpc": "2.0", "method": "session/update"}):
            out = self.t.on_message(message)
            self.assertEqual([k for k, _ in out], ["anomaly"], message)
        self.assertFalse(self.t.stopped)

    def test_an_anomaly_names_a_method_only_when_it_looks_like_one(self):
        self.drive("text").start()
        out = self.t.on_message({"jsonrpc": "2.0", "method": "x" * 200 + " secret", "params": {"password": 1}})
        self.assertEqual(out[0][1]["event_type"], "?")
        self.assertEqual(out[0][1]["fields"], ["password"])

    def test_a_long_reply_is_cut_and_counted_once(self):
        self.drive("text").start()
        self.t.begin_turn()
        for _ in range(3):
            self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "a" * (acp.MAX_REPLY_TEXT // 2)}}}})
        self.t.expect(90, "prompt")
        out = self.t.on_message({"jsonrpc": "2.0", "id": 90, "result": {"stopReason": "end_turn"}})
        self.assertEqual(len(out[0][1]["text"]), acp.MAX_REPLY_TEXT)
        self.assertEqual(out[0][0], "reply")


class PermissionTests(Drive):
    def test_a_command_is_asked_with_the_whole_command_and_the_options_as_they_came(self):
        req = self.permission("execute", {"CommandLine": "ls -la /made/up"}, TITLE="Run ls")
        self.assertEqual((req["kind"], req["tool_kind"], req["action"]), ("command", "execute", "ask"))
        self.assertEqual(req["command"], "ls -la /made/up")
        self.assertEqual(req["call_id"], "call-1")
        self.assertEqual(req["title"], "Run ls")
        self.assertIn("允許", req["why"])
        self.assertEqual(req["options"], [{"optionId": "allow", "kind": "allow_once"}, {"optionId": "deny", "kind": "reject_once"}])
        self.assertFalse(req["bypass"])
        self.assertEqual(self.t.open_requests(), [req["request_id"]])

    def test_a_long_command_is_not_cut_and_one_that_does_not_fit_a_card_is_refused(self):
        ok = "echo " + "x" * (acp.MAX_CARD_BYTES - 5)
        req = self.permission("execute", {"CommandLine": ok})
        self.assertEqual((req["action"], req["command"]), ("ask", ok))
        req = self.permission("execute", {"CommandLine": ok + "x"})
        self.assertEqual(req["action"], "deny")
        self.assertIn("一張卡放不下", req["why"])

    def test_a_command_request_without_a_command_is_refused(self):
        for raw in ({}, {"CommandLine": ""}, {"CommandLine": "  "}, {"CommandLine": 5}, {"CommandLine": ["ls"]}, "ls -a", ["ls"],
                    {"CommandLine": "ls\0x"}):
            self.assertEqual(self.permission("execute", raw)["action"], "deny", raw)

    def test_allowed_the_command_runs_and_its_result_has_the_exit_code_and_the_output(self):
        req = self.permission("execute", {"CommandLine": "ls -a"}, OUTPUT="a.txt\nb.txt", EXIT_CODE=0)
        self.answer("allow", req)
        self.assertEqual(self.of("tool_result"), [{"call_id": "call-1", "status": "completed", "exit_code": 0,
                                                   "output": "a.txt\nb.txt"}])
        self.assertEqual(self.of("turn_completed")[0]["tokens"], 86000)
        self.assertNotIn("violation", self.kinds())

    def test_a_command_that_failed_is_still_completed_and_carries_its_exit_code(self):
        req = self.permission("execute", {"CommandLine": "false"}, EXIT_CODE=1)
        self.answer("allow", req)
        result = self.of("tool_result")[0]
        self.assertEqual((result["status"], result["exit_code"]), ("completed", 1))
        for bad in ("1", 1.5, True, None, 10 ** 9):
            self.permission("execute", {"CommandLine": "x"}, EXIT_CODE=bad)
            self.answer("allow")
            self.assertIsNone(self.of("tool_result")[0]["exit_code"], bad)

    def test_denied_the_call_fails_and_nothing_stops(self):
        req = self.permission("execute", {"CommandLine": "rm -rf x"})
        self.answer("deny", req)
        self.assertEqual(self.of("tool_result")[0]["status"], "failed")
        self.assertNotIn("violation", self.kinds())
        self.assertEqual(self.player.choices, [("deny", "deny", "reject_once")])
        self.assertEqual(self.t.open_requests(), [])

    def test_the_tool_call_notification_and_the_request_make_one_call(self):
        req = self.permission("execute", {"CommandLine": "ls -a"})
        self.assertEqual([d["call_id"] for d in self.of("tool_call")], ["call-1"])
        self.assertEqual(self.of("tool_call")[0]["summary"], "ls -a")
        self.assertEqual(req["call_id"], "call-1")

    def test_a_request_alone_makes_its_call_known(self):
        self.drive("text").start()
        self.prompt()
        self.t.begin_turn()
        out = self.t.on_message({"jsonrpc": "2.0", "id": 5, "method": "session/request_permission", "params": {
            "sessionId": SESSION, "toolCall": {"toolCallId": "solo-1", "title": "T", "kind": "execute", "status": "pending",
                                               "rawInput": {"CommandLine": "ls"}}, "options": fx_options()}})
        self.assertEqual([k for k, _ in out], ["tool_call", "permission_request"])

    def test_bypass_sandbox_is_refused_with_no_card_for_every_value_that_is_not_false(self):
        for value in (True, "true", 1, "false", 0, None, "", "False", [], {}, 1.0, "no"):
            req = self.permission("execute", {"BypassSandbox": value, "CommandLine": "echo x > /made/up/out"})
            self.assertEqual(req["action"], "deny", repr(value))
            self.assertTrue(req["bypass"], repr(value))
            self.assertEqual(req["why"], acp.REASON_BYPASS)
        for key in ("bypasssandbox", "BYPASSSANDBOX", "bypassSandbox"):
            self.assertEqual(self.permission("execute", {key: True, "CommandLine": "x"})["action"], "deny", key)
        req = self.permission("execute", {"BypassSandbox": False, "CommandLine": "echo x"})
        self.assertEqual((req["action"], req["bypass"]), ("ask", False))

    def test_bypass_sandbox_in_a_file_or_a_read_request_is_refused_too(self):
        path = os.path.join(self.work, "a.txt")
        req = self.permission("edit", {"Path": path, "Content": "x", "BypassSandbox": True}, [{"path": path}])
        self.assertEqual(req["action"], "deny")
        req = self.permission("read", {"Path": path, "BypassSandbox": "true"}, [{"path": path}])
        self.assertEqual(req["action"], "deny")

    def test_the_bypass_flow_over_the_script_the_refusal_is_the_denying_answer(self):
        self.drive("bypass").start()
        self.prompt()
        first = self.requests()[-1]
        self.assertEqual(first["action"], "ask")
        self.answer("allow", first)
        self.assertEqual(self.of("tool_result")[0]["exit_code"], 1)               # the sandbox stopped it
        second = self.requests()[-1]
        self.assertEqual((second["action"], second["bypass"], second["call_id"]), ("deny", True, "call-2"))
        self.answer("deny", second)
        self.assertEqual(self.player.choices[-1], ("deny", "deny", "reject_once"))
        self.assertNotIn("violation", self.kinds())

    def test_a_denied_request_cannot_be_answered_allow(self):
        req = self.permission("execute", {"BypassSandbox": True, "CommandLine": "x"})
        with self.assertRaises(ValueError):
            self.t.answered(req["request_id"], "allow")
        self.t.answered(req["request_id"], "deny")

    def test_a_request_is_answered_once_and_only_when_it_is_open(self):
        req = self.permission("execute", {"CommandLine": "ls"})
        with self.assertRaises(ValueError):
            self.t.answered(999, "allow")
        with self.assertRaises(ValueError):
            self.t.answered(req["request_id"], "always")
        self.t.answered(req["request_id"], "allow")
        with self.assertRaises(ValueError):
            self.t.answered(req["request_id"], "deny")

    def test_a_list_of_options_it_does_not_understand_is_refused_not_guessed(self):
        allow, deny = {"optionId": "a", "kind": "allow_once"}, {"optionId": "d", "kind": "reject_once"}
        for options in ([allow], [deny], [], None, "x", [allow, allow, deny], [allow, deny, deny],
                        [{"optionId": "a", "kind": "allow_always"}, {"optionId": "d", "kind": "reject_always"}],
                        [{"optionId": "", "kind": "allow_once"}, deny], [{"optionId": 1, "kind": "allow_once"}, deny]):
            req = self.permission("execute", {"CommandLine": "ls"}, OPTIONS=options)
            self.assertEqual(req["action"], "deny", options)
            self.assertEqual(req["why"], acp.REASON_OPTIONS)

    def test_an_always_option_next_to_the_two_good_ones_is_ignored(self):
        options = [{"optionId": "yes-always", "kind": "allow_always", "name": "Always"}, {"optionId": "allow", "kind": "allow_once"},
                   {"optionId": "no-always", "kind": "reject_always"}, {"optionId": "deny", "kind": "reject_once"}]
        req = self.permission("execute", {"CommandLine": "ls"}, OPTIONS=options)
        self.assertEqual(req["action"], "ask")
        self.assertEqual({o["kind"] for o in req["options"]}, {"allow_once", "reject_once", "allow_always", "reject_always"})
        self.answer("allow", req)
        self.assertEqual(self.player.choices, [("allow", "allow", "allow_once")])

    def test_the_options_kept_are_ids_and_kinds_only(self):
        req = self.permission("execute", {"CommandLine": "ls"})
        for option in req["options"]:
            self.assertEqual(set(option), {"optionId", "kind"})

    def test_a_request_of_another_session_stops_the_chat_and_names_the_request_to_answer_with_an_error(self):
        self.drive("permission", {"REQ_SESSION": OTHER_SESSION}).start()
        self.prompt()
        violation = self.of("violation")[0]
        self.assertEqual(violation["request_id"], 1)
        self.assertNotIn("permission_request", self.kinds())
        self.assertTrue(self.t.stopped)

    def test_a_request_without_a_session_or_a_tool_call_is_not_taken(self):
        self.drive("text").start()
        self.prompt()
        out = self.t.on_message({"jsonrpc": "2.0", "id": 8, "method": "session/request_permission", "params": {"options": fx_options()}})
        self.assertEqual([k for k, _ in out], ["violation"])
        self.assertEqual(out[0][1]["request_id"], 8)
        self.drive("text").start()
        out = self.t.on_message({"jsonrpc": "2.0", "id": 9, "method": "session/request_permission", "params": {
            "sessionId": SESSION, "options": fx_options()}})
        self.assertEqual([k for k, _ in out], ["permission_request"])
        self.assertEqual((out[0][1]["action"], out[0][1]["call_id"]), ("deny", None))

    # -- files

    def test_a_new_file_in_the_work_folder_is_a_file_card_with_the_diff(self):
        path = os.path.join(self.work, "post.md")
        req = self.file_request(path, text="# made-up post")
        self.assertEqual((req["kind"], req["action"], req["operation"]), ("file_change", "ask", "add"))
        self.assertEqual(req["paths"], [path])
        self.assertEqual(req["content"], "# made-up post")
        self.assertEqual(req["diffs"], [{"path": path, "old_text": None, "new_text": "# made-up post"}])
        self.answer("allow", req)
        self.assertEqual(self.of("tool_result")[0]["status"], "completed")

    def test_an_existing_file_is_a_modification_and_a_delete_and_a_move_say_so(self):
        path = self.touch(self.work, "a.txt")
        req = self.permission("edit", {"Path": path, "Content": "new"}, [{"path": path}],
                              [{"type": "diff", "path": path, "oldText": "x", "newText": "new"}])
        self.assertEqual((req["action"], req["operation"]), ("ask", "modify"))
        req = self.permission("edit", {"Path": path, "Content": "new"}, [{"path": path}])
        self.assertEqual(req["operation"], "modify")
        req = self.permission("delete", {"Path": path}, [{"path": path}])
        self.assertEqual((req["action"], req["operation"]), ("ask", "delete"))
        dest = os.path.join(self.work, "moved.txt")
        req = self.permission("move", {"Path": path, "Destination": dest}, [{"path": path}])
        self.assertEqual((req["action"], req["operation"], req["paths"]), ("ask", "move", [path, dest]))

    def test_outside_the_work_folder_and_the_settings_names_are_refused_with_no_card(self):
        self.touch(self.work, "real.txt")
        os.symlink(self.out, os.path.join(self.work, "out-link"))
        os.symlink(self.touch(self.out, "decoy.txt"), os.path.join(self.work, "decoy-link"))
        shared_file = self.touch(self.shared, "s.txt")
        os.link(shared_file, os.path.join(self.work, "hard.txt"))
        for path in (os.path.join(self.out, "x.txt"), "/etc/made-up.txt", os.path.join(self.work, "out-link", "x.txt"),
                     os.path.join(self.work, "decoy-link"), os.path.join(self.work, "hard.txt"), os.path.join(self.work, ".agents", "skills", "x.md"),
                     os.path.join(self.work, "sub", ".git", "config"), os.path.join(self.work, ".gemini", "settings.json"),
                     os.path.join(self.work, "GEMINI.md"), os.path.join(self.work, "dir", "AGENTS.md"),
                     os.path.join(self.work, ".claude", "x"), os.path.join(self.work, ".codex", "x"), os.path.join(self.work, ".agent", "x")):
            req = self.file_request(path)
            self.assertEqual(req["action"], "deny", path)
            self.assertNotIn("ask", [r["action"] for r in self.requests()])

    def test_the_paths_must_be_given_the_same_everywhere_and_absolute(self):
        a, b = os.path.join(self.work, "a.txt"), os.path.join(self.work, "b.txt")
        cases = {
            "no raw path": ({"Content": "x"}, [{"path": a}], []),
            "no locations": ({"Path": a, "Content": "x"}, [], []),
            "locations differ": ({"Path": a, "Content": "x"}, [{"path": b}], []),
            "an extra location": ({"Path": a, "Content": "x"}, [{"path": a}, {"path": b}], []),
            "diff differs": ({"Path": a, "Content": "x"}, [{"path": a}], [{"type": "diff", "path": b, "oldText": None, "newText": "x"}]),
            "relative": ({"Path": "a.txt", "Content": "x"}, [{"path": "a.txt"}], []),
            "raw path not a string": ({"Path": 7, "Content": "x"}, [{"path": a}], []),
            "location not an object": ({"Path": a, "Content": "x"}, ["a"], []),
            "location path not a string": ({"Path": a, "Content": "x"}, [{"path": 3}], []),
        }
        for why, (raw, locations, content) in cases.items():
            req = self.permission("edit", raw, locations, content)
            self.assertEqual(req["action"], "deny", why)

    def test_a_file_card_that_does_not_fit_is_refused(self):
        path = os.path.join(self.work, "big.txt")
        self.assertEqual(self.file_request(path, text="x" * acp.MAX_CARD_BYTES)["action"], "deny")
        self.assertEqual(self.file_request(path, text="x" * 100)["action"], "ask")

    def test_the_shared_folder_is_a_root_only_when_the_employee_has_it(self):
        path = os.path.join(self.shared, "note.md")
        self.drive("permission").start()
        req = self.file_request(path)
        self.assertEqual(req["action"], "deny")
        self.shared_on = True
        vars = {"KIND": "edit", "RAW_INPUT": {"Path": path, "Content": "x"}, "LOCATIONS": [{"path": path}]}
        self.drive("permission", vars, shared=True).start()
        self.prompt()
        req = self.requests()[-1]
        self.assertEqual(req["action"], "ask")
        self.assertIn("共用資料夾", req["why"])
        vars["RAW_INPUT"]["Path"] = vars["LOCATIONS"][0]["path"] = os.path.join(self.shared, ".git", "x")
        self.drive("permission", vars, shared=True).start()
        self.prompt()
        self.assertEqual(self.requests()[-1]["action"], "deny")


    # -- calls with more than one path (a move names where it goes)

    def test_a_move_is_judged_by_where_it_comes_from_and_where_it_goes(self):
        src = self.touch(self.work, "a.txt")
        for key in ("Destination", "DestinationPath", "destination", "TargetPath", "target", "NewPath", "new_path", "Dest", "dst"):
            inside = os.path.join(self.work, "moved.txt")
            req = self.permission("move", {"Path": src, key: inside}, [{"path": src}, {"path": inside}])
            self.assertEqual((req["action"], req["paths"]), ("ask", [src, inside]), key)
            for bad in (os.path.join(self.out, "x.txt"), os.path.join(self.work, ".git", "x"), os.path.join(self.work, ".agents", "x"),
                        os.path.join(self.work, "GEMINI.md"), "/etc/made-up.txt", "relative.txt"):
                req = self.permission("move", {"Path": src, key: bad}, [{"path": src}])
                self.assertEqual(req["action"], "deny", (key, bad))

    def test_a_move_through_a_link_to_the_outside_is_refused(self):
        src = self.touch(self.work, "a.txt")
        os.symlink(self.out, os.path.join(self.work, "out-link"))
        req = self.permission("move", {"Path": src, "Destination": os.path.join(self.work, "out-link", "x.txt")}, [{"path": src}])
        self.assertEqual(req["action"], "deny")

    def test_a_move_that_names_no_destination_is_refused(self):
        src = self.touch(self.work, "a.txt")
        for raw in ({"Path": src}, {"Path": src, "Destination": ""}, {"Path": src, "Destination": 5}, {"Path": src, "Destination": src},
                    {"Path": src, "Content": "somewhere/else"}):
            req = self.permission("move", raw, [{"path": src}])
            self.assertEqual(req["action"], "deny", raw)

    def test_any_other_path_a_file_call_names_is_judged_too(self):
        a = os.path.join(self.work, "a.txt")
        for kind in ("edit", "delete"):
            req = self.permission(kind, {"Path": a, "Content": "x", "SourcePath": os.path.join(self.out, "o.txt")}, [{"path": a}])
            self.assertEqual(req["action"], "deny", kind)
        req = self.permission("edit", {"Path": a, "Content": "see /etc/hosts and ../x"}, [{"path": a}])
        self.assertEqual(req["action"], "ask")                          # what is written is not a path

    def test_the_locations_may_name_both_ends_of_a_move_but_nothing_else(self):
        src = self.touch(self.work, "a.txt")
        dest = os.path.join(self.work, "b.txt")
        stray = os.path.join(self.work, "c.txt")
        self.assertEqual(self.permission("move", {"Path": src, "Destination": dest}, [{"path": src}, {"path": dest}])["action"], "ask")
        self.assertEqual(self.permission("move", {"Path": src, "Destination": dest}, [{"path": src}, {"path": stray}])["action"], "deny")
        self.assertEqual(self.permission("move", {"Path": src, "Destination": dest}, [{"path": dest}])["action"], "deny")

    def test_the_paths_of_a_read_are_judged_as_a_whole(self):
        inside, outside = self.touch(self.work, "a.txt"), self.touch(self.out, "o.txt")
        req = self.permission("read", {"Path": inside, "OtherPath": outside}, [{"path": inside}])
        self.assertEqual(req["action"], "ask")


    def test_a_file_call_member_that_is_not_on_the_short_list_is_a_possible_path_and_judged_as_one(self):
        a = os.path.join(self.work, "a.txt")
        for key in ("Whatever", "Output", "Link", "x"):
            for bad in (os.path.join(self.out, "o.txt"), "relative.txt", "/etc/made-up.txt", os.path.join(self.work, ".git", "x")):
                for kind in ("edit", "delete", "move"):
                    raw = {"Path": a, "Content": "x", "Destination": os.path.join(self.work, "b.txt"), key: bad}
                    self.assertEqual(self.permission(kind, raw, [{"path": a}])["action"], "deny", (kind, key, bad))
        fine = os.path.join(self.work, "b.txt")
        req = self.permission("edit", {"Path": a, "Content": "x", "Whatever": fine}, [{"path": a}])
        self.assertEqual(req["action"], "ask")

    def test_a_file_call_member_that_cannot_be_read_as_a_path_or_a_plain_number_is_refused(self):
        a = os.path.join(self.work, "a.txt")
        for value in ({"Where": "/etc"}, [{"p": "x"}], [1, 2]):
            self.assertEqual(self.permission("edit", {"Path": a, "Content": "x", "Whatever": value}, [{"path": a}])["action"], "deny", value)
        for key, value in (("Description", "why"), ("Overwrite", True), ("Mode", 420), ("Explanation", "e"), ("Reason", "r")):
            self.assertEqual(self.permission("edit", {"Path": a, "Content": "x", key: value}, [{"path": a}])["action"], "ask", key)

    # -- search

    def test_a_search_request_whose_pattern_member_holds_a_path_is_asked_never_allowed_by_vbear(self):
        inside = self.touch(self.work, "a.txt")
        for key in ("Pattern", "Glob", "IncludePath", "includes", "FileGlob", "ExcludeFolder", "Query"):
            self.assertEqual(self.permission("search", {"Path": inside, key: "*.py"}, [{"path": inside}])["action"], "allow", key)
            for bad in ("/etc/*", "../x", "~/x", "a/b", "{a,../b}"):
                req = self.permission("search", {"Path": inside, key: bad}, [{"path": inside}])
                self.assertEqual(req["action"], "ask", (key, bad))
                req = self.permission("search", {key: [bad]}, [])
                self.assertNotEqual(req["action"], "allow", (key, bad))
        req = self.permission("read", {"Path": inside, "IncludePath": "/etc/hosts"}, [{"path": inside}])
        self.assertEqual(req["action"], "ask")

    def test_a_search_inside_is_asked_instead_when_the_work_folder_has_a_link_to_the_outside(self):
        inside = self.touch(self.work, "a.txt")
        raw = {"Path": inside, "Query": "made-up"}
        self.assertEqual(self.permission("search", raw, [{"path": inside}])["action"], "allow")
        os.symlink(self.out, os.path.join(self.work, "out-link"))
        req = self.permission("search", raw, [{"path": inside}])
        self.assertEqual(req["action"], "ask")
        self.assertEqual(self.permission("read", {"Path": inside}, [{"path": inside}])["action"], "allow")     # a read names its file

    # -- reads, the net, and kinds that are not known

    def test_a_read_inside_is_answered_by_vbear_and_outside_it_asks_and_the_card_says_where_it_goes(self):
        inside = self.touch(self.work, "a.txt")
        req = self.permission("read", {"Path": inside}, [{"path": inside}])
        self.assertEqual((req["kind"], req["action"], req["paths"]), ("read", "allow", [inside]))
        self.answer("allow", req)
        self.assertNotIn("violation", self.kinds())
        outside = self.touch(self.out, "o.txt")
        req = self.permission("read", {"Path": outside}, [{"path": outside}])
        self.assertEqual(req["action"], "ask")
        self.assertIn("Google", req["why"])
        self.answer("allow", req)
        self.assertNotIn("violation", self.kinds())

    def test_a_read_through_a_link_is_judged_by_where_it_ends(self):
        os.symlink(self.touch(self.out, "decoy.txt"), os.path.join(self.work, "link.txt"))
        path = os.path.join(self.work, "link.txt")
        self.assertEqual(self.permission("read", {"Path": path}, [{"path": path}])["action"], "ask")

    def test_a_read_that_names_no_path_is_refused(self):
        for raw, locations in (({}, []), ({"Path": ""}, []), ({"Path": 5}, [{"path": 5}])):
            self.assertEqual(self.permission("read", raw, locations)["action"], "deny", raw)
        self.assertEqual(self.permission("search", {"Query": "x"}, [])["action"], "deny")

    def test_the_net_is_refused_with_no_card(self):
        for raw in ({"Url": "https://example.com/made-up"}, {"URL": "https://example.com"}, {}, {"url": "x", "q": 1}):
            req = self.permission("fetch", raw)
            self.assertEqual((req["action"], req["why"]), ("deny", acp.REASON_NETWORK), raw)
        for kind in ("execute", "read", "other"):
            req = self.permission(kind, {"CommandLine": "ls", "Url": "https://example.com"})
            self.assertEqual((req["action"], req["why"]), ("deny", acp.REASON_NETWORK), kind)

    def test_a_kind_that_is_not_a_file_a_command_or_a_read_is_refused_and_noted(self):
        for kind in ("think", "other", "switch_mode", "surprise", "", None, 5):
            self.drive("permission", {"KIND": kind, "RAW_INPUT": {"Anything": 1}}).start()
            self.prompt()
            req = self.requests()[-1]
            self.assertEqual(req["action"], "deny", kind)
            self.assertEqual(req["tool_kind"], kind if isinstance(kind, str) and kind in CONSTS.tool_kinds else "?", kind)
            self.assertIn("anomaly", self.kinds(), kind)

    def test_what_the_card_shows_is_text_even_when_the_request_is_odd(self):
        req = self.permission("execute", {"CommandLine": "ls", "Extra": {"a": [1]}})
        self.assertEqual((req["action"], req["command"]), ("ask", "ls"))
        self.assertNotIn("Extra", json.dumps(req))
        req = self.permission("execute", {"CommandLine": "ls"}, TITLE=None)
        self.assertEqual(req["title"], "")
        req = self.permission("execute", {"CommandLine": "ls"}, TITLE="t" * 5000)
        self.assertEqual(len(req["title"]), 500)


def fx_options():
    return [{"optionId": "allow", "kind": "allow_once"}, {"optionId": "deny", "kind": "reject_once"}]


class ViolationTests(Drive):
    def violates(self, fixture="no-ask", vars=None):
        self.drive(fixture, vars).start()
        self.prompt()
        return self.of("violation")

    def test_a_tool_that_runs_without_vbears_yes_stops_the_chat_for_every_kind_that_is_not_a_read(self):
        for kind in ("execute", "edit", "delete", "move", "fetch", "other", "think", "switch_mode", "surprise"):
            for first in ("in_progress", "completed"):
                got = self.violates(vars={"KIND": kind, "FIRST": first})
                self.assertEqual(len(got), 1, (kind, first))
                self.assertIn("沒有經過 VBear 的允許", got[0]["message"])
                self.assertTrue(self.t.stopped)
                self.assertNotIn("turn_completed", self.kinds())          # nothing is read after a violation

    def test_a_call_that_is_only_announced_or_that_failed_is_not_a_violation(self):
        for status in ("pending", "failed", None):
            self.drive("text").start()
            self.prompt()
            out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
                "sessionUpdate": "tool_call", "toolCallId": f"c-{status}", "title": "T", "kind": "execute", "status": status,
                "rawInput": {"CommandLine": "ls"}}}})
            self.assertNotIn("violation", [k for k, _ in out], status)

    def test_a_refused_call_that_runs_anyway_is_a_violation(self):
        req = self.permission("execute", {"CommandLine": "ls"})
        self.answer("deny", req)
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "in_progress"}}})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_a_second_request_for_the_same_call_takes_the_first_yes_back(self):
        req = self.permission("execute", {"CommandLine": "ls"})
        self.answer("allow", req)
        self.t.on_message({"jsonrpc": "2.0", "id": 40, "method": "session/request_permission", "params": {
            "sessionId": SESSION, "toolCall": {"toolCallId": "call-1", "title": "T", "kind": "execute", "status": "pending",
                                               "rawInput": {"CommandLine": "rm -rf /made/up"}}, "options": fx_options()}})
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "in_progress"}}})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_what_runs_must_be_what_was_allowed(self):
        req = self.permission("execute", {"CommandLine": "ls -a"})
        self.t.answered(req["request_id"], "allow")                # (the player is not told: the turn stays open)
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "in_progress",
            "rawInput": {"CommandLine": "rm -rf /made/up"}}}})
        self.assertEqual([k for k, _ in out], ["violation"])
        self.assertIn("不同", out[0][1]["message"])
        path = os.path.join(self.work, "a.txt")
        req = self.file_request(path)
        self.t.answered(req["request_id"], "allow")
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "in_progress",
            "locations": [{"path": os.path.join(self.out, "elsewhere.txt")}]}}})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_more_detail_after_the_yes_about_the_same_command_is_fine(self):
        req = self.permission("execute", {"CommandLine": "ls -a"})
        self.t.answered(req["request_id"], "allow")
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "in_progress",
            "rawInput": {"CommandLine": "ls -a", "Description": "lists the folder"}, "title": "Running"}}})
        self.assertEqual(out, [])


    # -- what a yes covers

    def update(self, **fields):
        return self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "call-1", **fields}}})

    def test_a_move_that_goes_somewhere_else_after_the_yes_is_a_violation(self):
        src = self.touch(self.work, "a.txt")
        dest = os.path.join(self.work, "b.txt")
        req = self.permission("move", {"Path": src, "Destination": dest}, [{"path": src}])
        self.t.answered(req["request_id"], "allow")
        self.assertEqual(self.update(status="in_progress", rawInput={"Path": src, "Destination": dest}), [])
        out = self.update(status="in_progress", rawInput={"Path": src, "Destination": os.path.join(self.out, "b.txt")})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_bypass_sandbox_appearing_after_the_yes_is_a_violation_in_any_case_and_for_any_value_but_false(self):
        for key in ("BypassSandbox", "bypasssandbox", "BYPASSSANDBOX"):
            for value in (True, "true", 1, None, "false", 0):
                req = self.permission("execute", {"CommandLine": "ls -a"})
                self.t.answered(req["request_id"], "allow")
                out = self.update(status="in_progress", rawInput={"CommandLine": "ls -a", key: value})
                self.assertEqual([k for k, _ in out], ["violation"], (key, value))
                self.assertIn("沙盒", out[0][1]["message"])

    def test_bypass_sandbox_after_the_yes_is_a_violation_even_in_an_update_that_is_not_running_yet(self):
        req = self.permission("execute", {"CommandLine": "ls -a"})
        self.t.answered(req["request_id"], "allow")
        out = self.update(status="pending", rawInput={"CommandLine": "ls -a", "BypassSandbox": True})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_bypass_sandbox_false_after_the_yes_is_the_same_call_only_if_it_was_there_before(self):
        req = self.permission("execute", {"CommandLine": "ls -a", "BypassSandbox": False})
        self.t.answered(req["request_id"], "allow")
        self.assertEqual(self.update(status="in_progress", rawInput={"CommandLine": "ls -a", "BypassSandbox": False}), [])

    def test_a_new_field_after_the_yes_is_a_violation_unless_it_is_on_the_short_harmless_list(self):
        for extra in ({"Cwd": "/made/up"}, {"Env": {"A": "1"}}, {"Timeout": 5}, {"Content": "x"}, {"SandboxMode": "off"}):
            req = self.permission("execute", {"CommandLine": "ls -a"})
            self.t.answered(req["request_id"], "allow")
            out = self.update(status="in_progress", rawInput={"CommandLine": "ls -a", **extra})
            self.assertEqual([k for k, _ in out], ["violation"], extra)
        for extra in ({"Description": "lists"}, {"explanation": "x"}, {"Reason": "y"}, {"Summary": "z"}, {"Comment": "c"}, {"Title": "t"}):
            req = self.permission("execute", {"CommandLine": "ls -a"})
            self.t.answered(req["request_id"], "allow")
            self.assertEqual(self.update(status="in_progress", rawInput={"CommandLine": "ls -a", **extra}), [], extra)

    def test_a_field_that_changes_value_after_the_yes_is_a_violation(self):
        req = self.permission("execute", {"CommandLine": "ls -a", "Cwd": "/made/up/one"})
        self.t.answered(req["request_id"], "allow")
        out = self.update(status="in_progress", rawInput={"CommandLine": "ls -a", "Cwd": "/made/up/two"})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_an_update_without_a_raw_input_keeps_what_was_allowed(self):
        req = self.permission("execute", {"CommandLine": "ls -a"})
        self.t.answered(req["request_id"], "allow")
        self.assertEqual(self.update(status="in_progress"), [])

    # -- a search that runs by itself

    def search(self, raw, locations=None, first="in_progress"):
        return self.violates(vars={"KIND": "search", "FIRST": first, "RAW_INPUT": raw, "LOCATIONS": locations or []})

    def test_a_search_with_no_path_is_fine_only_when_every_string_is_a_bare_name_and_there_is_no_link_to_the_outside(self):
        self.assertEqual(self.search({"Query": "made-up", "Glob": "*.py"}), [])
        self.assertEqual(self.search({"Query": "made-up", "Limit": 5, "CaseSensitive": True, "Extra": None}), [])

    def test_a_search_whose_strings_hold_a_slash_dots_or_a_tilde_is_a_violation(self):
        for raw in ({"Query": "x", "Glob": "/etc/*"}, {"Query": "x", "Glob": "../*"}, {"Query": "x", "Glob": "~/*"},
                    {"Query": "a/b"}, {"Query": "x", "Directories": ["ok", "../up"]}, {"Query": "x", "Nested": {"Where": "/etc"}},
                    {"Query": ""}, {"Query": "x", "Glob": ""}):
            got = self.search(raw)
            self.assertEqual(len(got), 1, raw)


    def test_a_kind_that_changes_after_the_yes_is_a_violation(self):
        src = self.touch(self.work, "a.txt")
        req = self.permission("execute", {"CommandLine": "ls -a"})
        self.t.answered(req["request_id"], "allow")
        out = self.update(status="in_progress", kind="read", rawInput={"CommandLine": "ls -a"})
        self.assertEqual([k for k, _ in out], ["violation"])
        outside = self.touch(self.out, "o.txt")
        req = self.permission("read", {"Path": outside}, [{"path": outside}])
        self.assertEqual(req["action"], "ask")
        self.t.answered(req["request_id"], "allow")
        out = self.update(status="in_progress", kind="edit", rawInput={"Path": outside, "Content": "x"})
        self.assertEqual([k for k, _ in out], ["violation"])
        req = self.permission("read", {"Path": src}, [{"path": src}])
        self.t.answered(req["request_id"], "allow")
        self.assertEqual([k for k, _ in self.update(status="in_progress", kind="edit")], ["violation"])

    def test_a_search_that_runs_unasked_names_its_places_as_absolute_paths_with_no_pattern_characters(self):
        inside = self.touch(self.work, "a.txt")
        self.assertEqual(self.search({"Query": "made-up", "SearchPath": self.work}), [])
        self.assertEqual(self.search({"Query": "made-up", "Directory": inside}, [{"path": inside}]), [])
        for bad in ("relative", "sub/dir", self.work + "/{a,b}", self.work + "/*", self.work + "/a?", self.work + "/[ab]", "~", "~/x",
                    self.work + "/../x"):
            for key in ("Path", "SearchPath", "Directory", "TargetFolder"):
                self.assertEqual(len(self.search({"Query": "made-up", key: bad})), 1, (key, bad))

    def test_a_search_member_named_like_a_pattern_is_a_pattern_and_never_a_place(self):
        for key in ("Pattern", "Glob", "IncludePath", "includes", "FileGlob"):
            self.assertEqual(self.search({"Query": "made-up", key: "*.py"}), [], key)
            for bad in (self.work, "/etc/*", "../x", "a/b"):
                self.assertEqual(len(self.search({"Query": "made-up", key: bad})), 1, (key, bad))

    def test_a_read_that_runs_unasked_with_a_pattern_member_that_holds_a_path_is_a_violation(self):
        inside = self.touch(self.work, "a.txt")
        for kind in ("read", "search"):
            self.assertEqual(self.violates(vars={"KIND": kind, "RAW_INPUT": {"Path": inside, "IncludePath": "*.py"}, "LOCATIONS": [{"path": inside}]}), [], kind)
            got = self.violates(vars={"KIND": kind, "RAW_INPUT": {"Path": inside, "IncludePath": "/etc/*"}, "LOCATIONS": [{"path": inside}]})
            self.assertEqual(len(got), 1, kind)

    def test_a_search_is_a_violation_when_the_work_folder_has_a_link_to_the_outside_even_with_a_path_inside(self):
        os.symlink(self.out, os.path.join(self.work, "out-link"))
        self.assertEqual(len(self.search({"Query": "made-up"})), 1)
        inside = self.touch(self.work, "a.txt")
        self.assertEqual(len(self.search({"Path": inside, "Query": "made-up"}, [{"path": inside}])), 1)

    def test_a_read_is_not_stopped_by_a_link_that_it_does_not_follow(self):
        os.symlink(self.out, os.path.join(self.work, "out-link"))
        inside = self.touch(self.work, "a.txt")
        got = self.violates(vars={"KIND": "read", "RAW_INPUT": {"Path": inside}, "LOCATIONS": [{"path": inside}]})
        self.assertEqual(got, [])

    def test_an_update_of_a_call_never_seen_that_runs_is_a_violation(self):
        self.drive("text").start()
        self.prompt()
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "ghost", "status": "completed"}}})
        self.assertEqual([k for k, _ in out], ["violation"])

    def test_a_read_that_runs_by_itself_inside_the_work_folder_is_fine(self):
        inside = self.touch(self.work, "a.txt")
        for kind in ("read", "search"):
            got = self.violates(vars={"KIND": kind, "RAW_INPUT": {"Path": inside}, "LOCATIONS": [{"path": inside}]})
            self.assertEqual(got, [], kind)
            self.assertEqual(len(self.of("tool_result")), 1)

    def test_a_search_that_names_no_path_runs_in_the_work_folder_and_is_fine(self):
        self.assertEqual(self.violates(vars={"KIND": "search", "RAW_INPUT": {"Query": "made-up"}, "LOCATIONS": []}), [])

    def test_a_read_that_runs_by_itself_outside_the_work_folder_stops_the_chat(self):
        outside = self.touch(self.out, "o.txt")
        link = os.path.join(self.work, "link.txt")
        os.symlink(outside, link)
        for kind in ("read", "search"):
            for path in (outside, link, "../outside/o.txt", "/etc/hosts"):
                for first in ("in_progress", "completed"):
                    got = self.violates(vars={"KIND": kind, "FIRST": first, "RAW_INPUT": {"Path": path}, "LOCATIONS": [{"path": path}]})
                    self.assertEqual(len(got), 1, (kind, path, first))
                    self.assertIn("工作資料夾", got[0]["message"])

    def test_the_path_may_be_in_the_locations_alone_or_in_the_raw_input_alone(self):
        outside = self.touch(self.out, "o.txt")
        self.assertEqual(len(self.violates(vars={"KIND": "read", "RAW_INPUT": {}, "LOCATIONS": [{"path": outside}]})), 1)
        self.assertEqual(len(self.violates(vars={"KIND": "read", "RAW_INPUT": {"Path": outside}, "LOCATIONS": []})), 1)

    def test_a_read_that_runs_by_itself_and_names_no_path_stops_the_chat(self):
        self.assertEqual(len(self.violates(vars={"KIND": "read", "RAW_INPUT": {}, "LOCATIONS": []})), 1)

    def test_a_read_outside_that_is_only_announced_waits_for_its_request(self):
        outside = self.touch(self.out, "o.txt")
        self.drive("text").start()
        self.prompt()
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call", "toolCallId": "r-1", "title": "Read", "kind": "read", "status": "pending",
            "rawInput": {"Path": outside}, "locations": [{"path": outside}]}}})
        self.assertEqual([k for k, _ in out], ["tool_call"])
        out = self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "r-1", "status": "in_progress"}}})
        self.assertEqual([k for k, _ in out], ["violation"])           # it ran, and nobody was asked

    def test_a_read_outside_that_vbear_allowed_on_a_card_is_fine(self):
        outside = self.touch(self.out, "o.txt")
        req = self.permission("read", {"Path": outside}, [{"path": outside}])
        self.answer("allow", req)
        self.assertNotIn("violation", self.kinds())

    def test_the_shared_folder_counts_as_inside_for_a_read_that_runs_by_itself(self):
        inside = self.touch(self.shared, "s.txt")
        self.drive("no-ask", {"KIND": "read", "RAW_INPUT": {"Path": inside}, "LOCATIONS": [{"path": inside}]}, shared=True).start()
        self.prompt()
        self.assertNotIn("violation", self.kinds())
        self.assertEqual(len(self.violates(vars={"KIND": "read", "RAW_INPUT": {"Path": inside}, "LOCATIONS": [{"path": inside}]})), 1)

    def test_a_mode_other_than_default_stops_the_chat_and_default_does_not(self):
        self.drive("mode-switch").start()
        self.prompt()
        self.assertEqual(len(self.of("violation")), 1)
        self.assertIn("模式", self.of("violation")[0]["message"])
        self.drive("mode-switch", {"MODE": "default"}).start()
        self.prompt()
        self.assertEqual(self.of("violation"), [])
        for mode in (None, 5, "", "Default"):
            self.drive("mode-switch", {"MODE": mode}).start()
            self.prompt()
            self.assertEqual(len(self.of("violation")), 1, mode)

    def test_an_update_of_another_session_stops_the_chat(self):
        self.drive("other-session").start()
        self.prompt()
        self.assertEqual(len(self.of("violation")), 1)
        self.assertIn("別的對話", self.of("violation")[0]["message"])

    def test_nothing_is_read_after_a_violation(self):
        self.drive("mode-switch").start()
        self.prompt()
        self.assertTrue(self.t.stopped)
        self.assertEqual(self.t.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": SESSION, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "x"}}}}), [])

    def test_a_call_that_never_finished_is_not_a_violation_and_is_counted(self):
        self.drive("unfinished").start()
        self.prompt()
        req = self.requests()[-1]
        self.answer("allow", req)
        self.assertEqual(self.of("violation"), [])
        self.assertEqual(self.of("turn_completed")[0]["open_calls"], 1)
        self.assertEqual(self.of("tool_result"), [])

    def test_an_unknown_request_of_the_agent_is_refused_and_noted_by_its_method(self):
        for method in ("fs/read_text_file", "fs/write_text_file", "terminal/create", "session/surprise", "x" * 100):
            self.drive("unknown-request", {"METHOD": method}).start()
            self.prompt()
            req = self.of("unknown_request")[0]
            self.assertEqual(req["refused"], True)
            self.assertEqual(req["method"], method if len(method) < 64 else "?")
            self.assertEqual(self.of("anomaly")[0]["event_type"], req["method"])
            self.feed(self.player.send(acp.error_line(req["request_id"], "VBear 不接受這種請求")))
            self.assertEqual(self.of("turn_completed")[0]["stop_reason"], "end_turn")
            self.assertEqual(self.player.unexpected, [])
            self.assertFalse(self.t.stopped)

    def test_an_unknown_request_with_a_bad_id_is_an_anomaly_only(self):
        self.drive("text").start()
        out = self.t.on_message({"jsonrpc": "2.0", "id": None, "method": "fs/read_text_file", "params": {}})
        self.assertEqual([k for k, _ in out], ["anomaly"])
        out = self.t.on_message({"jsonrpc": "2.0", "id": [1], "method": "fs/read_text_file", "params": {}})
        self.assertEqual([k for k, _ in out], ["anomaly"])

    def test_a_stopped_turn_with_a_request_waiting(self):
        self.drive("cancel").start()
        self.prompt()
        req = self.requests()[-1]
        self.assertEqual(self.t.open_requests(), [req["request_id"]])
        self.feed(self.player.send(acp.cancel_line(SESSION)))
        self.t.answered(req["request_id"], "cancelled")
        self.feed(self.player.send(acp.answer_line(req["request_id"], req["options"], "cancelled")))
        done = self.of("turn_completed")[0]
        self.assertEqual((done["stop_reason"], done["tokens"]), ("cancelled", 86000))
        self.assertEqual(self.t.open_requests(), [])
        self.assertEqual(self.of("violation"), [])
        self.assertEqual(self.player.choices, [("cancelled", None, None)])


class EveryScriptTests(Drive):
    """Whatever a script plays, nothing the person owns reaches a fact, and every fact is plain data."""

    def test_no_fact_of_any_script_holds_the_plan_the_sign_in_methods_or_the_skill_names(self):
        for name in fx.names():
            decision = "allow"
            self.drive(name, session_id=SESSION if name.startswith("resume") else None, resumed=name.startswith("resume"))
            self.start()
            for _ in range(2):
                if not self.t.ready:
                    break
                self.prompt()
                for _ in range(4):
                    if self.player.awaiting is None or self.t.stopped:
                        break
                    request = next((r for r in reversed(self.requests()) if r["request_id"] in self.t.open_requests()), None)
                    if request is None:
                        break
                    self.answer("deny" if request["action"] == "deny" else decision, request)
            text = json.dumps(self.facts, ensure_ascii=False)
            for secret in fx.SENSITIVE:
                self.assertNotIn(secret, text, (name, secret))

    def test_every_script_starts_with_its_synthetic_header_and_none_is_left_unplayed(self):
        for name in fx.names() + ["_handshake-new", "_handshake-resume"]:
            first = json.loads((fx.DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("_synthetic", first, name)
            self.assertIn("Synthetic", first["_synthetic"], name)


if __name__ == "__main__":
    unittest.main()
