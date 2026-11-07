"""P43-2 (ADR 0009): the shared folder in the Codex chat protocol, pure. The setting that adds the writable root to the sandbox, the
turn's ``sandboxPolicy``, the comparison with what ``thread/start`` answers, and the judgement of a file change in the shared
folder. With the folder off every line is the one v0.17.0 wrote. Nothing here starts Codex; paths and names are made up."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from tests import codex_chat_fixtures as ccf
from tests.test_codex_chat_protocol import THREAD, note, parsed, thread_result
from vbear.runtime import codex_chat_protocol as ccp, shared_rules as sr

V = ccp.VERSIONS["0.163.0"]
WORK = "/private/tmp/vbear-fake/work"
SHARED = "/private/tmp/vbear-fake/shared"


def config_values(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]


class RootSettingTests(unittest.TestCase):
    def test_the_setting_is_a_toml_array_of_one_json_string(self):
        self.assertEqual(ccp.shared_root_setting(SHARED), 'sandbox_workspace_write.writable_roots=["/private/tmp/vbear-fake/shared"]')

    def test_a_quote_and_a_backslash_are_escaped_so_the_string_cannot_end_early(self):
        path = '/private/tmp/q"uote\\back/shared'
        setting = ccp.shared_root_setting(path)
        value = setting.split("=", 1)[1]
        self.assertEqual(json.loads(value), [path])
        self.assertIn('\\"', value)
        self.assertIn("\\\\", value)

    def test_a_control_character_or_a_path_that_is_not_absolute_or_not_text_is_refused(self):
        for bad in ("/tmp/a\nb/shared", "/tmp/a\x00b", "/tmp/a\x7fb", "/tmp/a\tb", "shared", "", None, 5, b"/tmp/x", "/tmp/\udcff"):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    ccp.shared_root_setting(bad)

    def test_a_name_with_the_end_markers_is_only_a_string(self):
        path = "/private/tmp/END_VBEAR_SHARED_JSON/shared"
        self.assertEqual(json.loads(ccp.shared_root_setting(path).split("=", 1)[1]), [path])


class ArgvTests(unittest.TestCase):
    def test_off_the_argument_list_is_the_one_of_v0_17_0(self):
        before = ccp.argv_for(V, WORK)
        self.assertEqual(ccp.argv_for(V, WORK, shared=None), before)
        self.assertNotIn("writable_roots", " ".join(before))
        configs = config_values(before)
        self.assertEqual(configs[-1], ccp.project_trust_setting(WORK))

    def test_on_one_more_setting_comes_last_and_nothing_else_changes(self):
        off = ccp.argv_for(V, WORK)
        on = ccp.argv_for(V, WORK, shared=SHARED)
        self.assertEqual(config_values(on)[:-1], config_values(off))
        self.assertEqual(config_values(on)[-1], ccp.shared_root_setting(SHARED))
        self.assertEqual(len(on), len(off) + 2)
        self.assertEqual([a for a in on if a == "--disable"], [a for a in off if a == "--disable"])
        self.assertNotIn("--add-dir", on)
        self.assertEqual(on[:3], ["app-server", "--listen", "stdio://"])

    def test_a_path_that_cannot_be_written_refuses_the_argument_list(self):
        with self.assertRaises(ValueError):
            ccp.argv_for(V, WORK, shared="/tmp/a\nb")


class TurnStartTests(unittest.TestCase):
    def test_off_the_turn_names_no_writable_root(self):
        line = parsed(ccp.turn_start_line(7, THREAD, "hi"))
        self.assertEqual(line["params"]["sandboxPolicy"]["writableRoots"], [])
        self.assertEqual(line, parsed(ccp.turn_start_line(7, THREAD, "hi", writable_roots=None)))
        self.assertEqual(line, parsed(ccp.turn_start_line(7, THREAD, "hi", writable_roots=[])))

    def test_on_the_turn_names_the_shared_folder_and_nothing_else_changes(self):
        off = parsed(ccp.turn_start_line(7, THREAD, "hi"))
        on = parsed(ccp.turn_start_line(7, THREAD, "hi", writable_roots=[SHARED]))
        self.assertEqual(on["params"]["sandboxPolicy"]["writableRoots"], [SHARED])
        on["params"]["sandboxPolicy"]["writableRoots"] = []
        self.assertEqual(on, off)

    def test_the_roots_must_be_a_list_of_absolute_paths(self):
        for bad in ("/x", [1], ["x"], [SHARED, SHARED + "2"], ["/a\nb"], {"a": 1}):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    ccp.turn_start_line(7, THREAD, "hi", writable_roots=bad)


def tracker(roots=None, resumed=False):
    kw = {} if roots is None else {"writable_roots": roots}
    t = ccp.CodexTracker(V, workdir=ccf.WORK, codex_home=ccf.CODEX_HOME, thread_id=THREAD if resumed else None, resumed=resumed, **kw)
    return t


def sandbox_with(roots):
    return {"type": "workspaceWrite", "writableRoots": roots, "networkAccess": False, "excludeTmpdirEnvVar": True,
            "excludeSlashTmp": True}


class AnswerTests(unittest.TestCase):
    def answer(self, t, roots, kind="thread_start"):
        t.expect(2, kind)
        return t.on_message(thread_result(sandbox=sandbox_with(roots)))

    def test_off_an_empty_list_is_right_and_anything_else_stops_the_chat(self):
        self.assertEqual(self.answer(tracker(), [])[0][0], "session_ready")
        for roots in ([SHARED], ["/x"], [[]], None, "", {}):
            with self.subTest(roots=roots):
                t = tracker()
                self.assertEqual([k for k, _ in self.answer(t, roots)], ["violation"])
                self.assertTrue(t.stopped)

    def test_on_exactly_the_shared_folder_is_right(self):
        t = tracker([SHARED])
        self.assertEqual(self.answer(t, [SHARED])[0][0], "session_ready")
        t = tracker([SHARED], resumed=True)
        self.assertEqual(self.answer(t, [SHARED], "thread_resume")[0][0], "session_ready")

    def test_on_an_empty_one_more_or_other_roots_stop_the_chat_and_say_nothing_of_the_paths(self):
        other = "/Users/fake-user"
        cases = {"empty": [], "one more": [SHARED, other], "one more first": [other, SHARED], "other only": [other],
                 "twice": [SHARED, SHARED], "null": None, "a string": SHARED, "a number": [5], "nested": [[SHARED]]}
        for name, roots in cases.items():
            with self.subTest(name=name):
                t = tracker([SHARED])
                out = self.answer(t, roots)
                self.assertEqual([k for k, _ in out], ["violation"], name)
                self.assertTrue(t.stopped)
                self.assertNotIn("fake-user", json.dumps(out))
                self.assertNotIn(SHARED, json.dumps(out))

    def test_a_missing_field_or_an_extra_one_is_still_wrong_with_the_folder_on(self):
        full = sandbox_with([SHARED])
        for name, box in {"no roots": {k: v for k, v in full.items() if k != "writableRoots"},
                          "extra": dict(full, readOnlyAccess={"type": "fullAccess"}),
                          "network": dict(full, networkAccess=True), "slash tmp": dict(full, excludeSlashTmp=False)}.items():
            with self.subTest(name=name):
                t = tracker([SHARED])
                t.expect(2, "thread_start")
                self.assertEqual([k for k, _ in t.on_message(thread_result(sandbox=box))], ["violation"])

    def test_a_later_settings_update_must_keep_the_same_roots(self):
        t = tracker([SHARED])
        self.answer(t, [SHARED])
        ok = note("thread/settings/updated", threadId=THREAD, threadSettings={"sandboxPolicy": sandbox_with([SHARED])})
        self.assertEqual(t.on_message(ok), [])
        bad = note("thread/settings/updated", threadId=THREAD, threadSettings={"sandboxPolicy": sandbox_with([])})
        self.assertEqual([k for k, _ in t.on_message(bad)], ["violation"])
        t = tracker()
        self.answer(t, [])
        bad = note("thread/settings/updated", threadId=THREAD, threadSettings={"sandboxPolicy": sandbox_with([SHARED])})
        self.assertEqual([k for k, _ in t.on_message(bad)], ["violation"])

    def test_the_roots_a_tracker_is_given_must_be_a_list_of_paths(self):
        for bad in ("/x", [1], ["x"], [SHARED, "/y"]):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    tracker(bad)


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="vs2"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work")
        self.shared = os.path.join(self.tmp, "shared")
        self.outside = os.path.join(self.tmp, "outside")
        for p in (self.work, self.shared, self.outside):
            os.mkdir(p)

    def change(self, path, kind="add", **more):
        return {"path": path, "kind": dict({"type": kind}, **more), "diff": "+x\n"}

    def judge(self, *paths, shared="yes", **kw):
        changes = [self.change(p) if isinstance(p, str) else p for p in paths]
        return ccp.judge_file_change(changes, self.work, shared=self.shared if shared == "yes" else shared, **kw)

    def test_a_file_in_the_shared_folder_is_a_card_that_says_who_can_read_it(self):
        j = self.judge(os.path.join(self.shared, "a.md"))
        self.assertEqual(j.action, "ask")
        self.assertIn("共用資料夾", j.reason)
        self.assertIn("讀得到", j.reason)

    def test_the_work_folder_is_as_before(self):
        j = self.judge(os.path.join(self.work, "a.md"))
        self.assertEqual((j.action, j.reason), ("ask", "修改員工工作資料夾裡的檔案，要你允許"))
        self.assertEqual(ccp.judge_file_change([self.change(os.path.join(self.work, "a.md"))], self.work).action, "ask")

    def test_off_the_shared_folder_is_outside_and_refused_as_before(self):
        j = ccp.judge_file_change([self.change(os.path.join(self.shared, "a.md"))], self.work)
        self.assertEqual(j.action, "deny")
        self.assertIn("資料夾以外", j.reason)

    def test_a_path_through_a_link_out_is_refused_with_no_card(self):
        os.symlink(self.outside, os.path.join(self.shared, "out"))
        for rel in ("out/x.txt", "out/sub/x.txt"):
            with self.subTest(rel=rel):
                self.assertEqual(self.judge(os.path.join(self.shared, rel)).action, "deny")

    def test_the_four_protected_names_at_any_depth_in_any_case_are_refused(self):
        for rel in (".git/config", ".codex/x", ".agents/x", ".claude/x", "a/b/.git/x", "A/.GIT/x", ".Codex/x", ".CLAUDE/settings.json", "a/.Agents"):
            with self.subTest(rel=rel):
                self.assertEqual(self.judge(os.path.join(self.shared, rel)).action, "deny")

    def test_the_work_folder_keeps_its_three_protected_names(self):
        for rel in (".git/x", "a/.codex/x", ".agents"):
            self.assertEqual(self.judge(os.path.join(self.work, rel)).action, "deny", rel)

    def test_a_hard_linked_file_is_refused(self):
        target = os.path.join(self.outside, "t.txt")
        with open(target, "w") as f:
            f.write("x")
        os.link(target, os.path.join(self.shared, "h.txt"))
        j = self.judge(os.path.join(self.shared, "h.txt"))
        self.assertEqual(j.action, "deny")
        self.assertIn("硬連結", j.reason)

    def test_the_folder_itself_and_a_sibling_with_the_same_prefix_are_outside(self):
        self.assertEqual(self.judge(self.shared).action, "deny")
        sibling = self.shared + "-more"
        os.mkdir(sibling)
        self.assertEqual(self.judge(os.path.join(sibling, "a.md")).action, "deny")

    def test_a_move_needs_both_ends_to_be_allowed(self):
        move = self.change(os.path.join(self.shared, "a.md"), "update", move_path=os.path.join(self.outside, "a.md"))
        self.assertEqual(self.judge(move).action, "deny")
        move = self.change(os.path.join(self.work, "a.md"), "update", move_path=os.path.join(self.shared, "a.md"))
        self.assertEqual(self.judge(move).action, "ask")
        move = self.change(os.path.join(self.shared, "a.md"), "update", move_path=os.path.join(self.shared, ".git", "a.md"))
        self.assertEqual(self.judge(move).action, "deny")

    def test_one_change_in_each_root_is_still_one_card(self):
        j = self.judge(os.path.join(self.work, "a.md"), os.path.join(self.shared, "b.md"))
        self.assertEqual(j.action, "ask")
        self.assertIn("共用資料夾", j.reason)

    def test_one_bad_change_among_good_ones_refuses_the_whole(self):
        self.assertEqual(self.judge(os.path.join(self.shared, "b.md"), os.path.join(self.outside, "c.md")).action, "deny")

    def test_a_relative_path_is_the_work_folders_and_cannot_climb_into_the_shared_folder_by_name_alone(self):
        # relative to the work folder: ../shared/x lands in the shared folder after the dots are resolved, which is allowed there
        self.assertEqual(self.judge("../shared/x.md").action, "ask")
        self.assertEqual(self.judge("../outside/x.md").action, "deny")

    def test_a_shared_path_that_is_not_a_plain_path_adds_no_root(self):
        for bad in (None, "", "relative", 5):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(self.judge(os.path.join(self.shared, "a.md"), shared=bad).action, "deny")

    def test_the_card_still_has_to_fit(self):
        big = {"path": os.path.join(self.shared, "a.md"), "kind": {"type": "add"}, "diff": "x" * 100}
        self.assertEqual(ccp.judge_file_change([big], self.work, max_bytes=50, shared=self.shared).action, "deny")

    def test_the_shared_rules_decide_what_may_be_written_there(self):
        where = os.path.join(self.shared, ".git", "x")
        self.assertIsNotNone(sr.write_problem(where, self.shared))
        self.assertEqual(self.judge(where).action, "deny")


if __name__ == "__main__":
    unittest.main()
