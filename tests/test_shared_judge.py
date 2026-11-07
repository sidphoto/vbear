"""P43-1 (ADR 0009): what VBear's own judgement (chat_protocol.judge) does with the shared folder as a second root, and the
``.claude`` rule that now looks at any depth of the work folder. Writes into the shared folder are always a card (nothing is
allowed by VBear itself); a path through a link out, a protected name, a hard-linked file: refused with no card. Reads in the shared
folder follow the work folder's rule, with the links looked for in the root the path is in. Everything lives in a temporary folder."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import leftover
from vbear.runtime import chat_protocol as cp


class SharedJudgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vsj-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(leftover.assert_clean, self.tmp)
        self.work = self.tmp / "work"
        self.shared = self.tmp / "shared"
        self.outside = self.tmp / "outside"
        for d in (self.work, self.shared, self.outside):
            d.mkdir()
        self.w, self.s = str(self.work), str(self.shared)

    def j(self, tool, shared="yes", **inp):
        return cp.judge(tool, inp, self.w, shared=self.s if shared == "yes" else None)


class WriteTests(SharedJudgeCase):
    def test_a_write_in_the_shared_folder_is_a_card_with_its_own_words_and_the_same_editable_field(self):
        for tool, field in (("Write", "content"), ("Edit", "new_string")):
            j = self.j(tool, file_path=f"{self.s}/price.md", content="x", old_string="a", new_string="b")
            self.assertEqual((j.action, j.editable), ("ask", field), tool)
            self.assertIn("共用資料夾", j.reason)
            self.assertIn("其他", j.reason)

    def test_in_a_subfolder_and_by_a_relative_path_from_the_work_folder(self):
        self.assertEqual(self.j("Write", file_path=f"{self.s}/a/b/c.md", content="x").action, "ask")
        self.assertEqual(self.j("Write", file_path="../shared/c.md", content="x").action, "ask")

    def test_the_work_folder_is_as_it_was(self):
        j = self.j("Write", file_path=f"{self.w}/a.txt", content="x")
        self.assertEqual((j.action, j.editable), ("ask", "content"))
        self.assertIn("工作資料夾", j.reason)
        self.assertNotIn("共用", j.reason)

    def test_with_the_folder_off_a_write_there_is_refused_as_before(self):
        j = self.j("Write", shared=None, file_path=f"{self.s}/price.md", content="x")
        self.assertEqual(j.action, "deny")
        self.assertIn("以外", j.reason)

    def test_the_shared_folder_itself_other_folders_and_a_name_beside_it_are_refused(self):
        for path in (self.s, str(self.tmp / "shared2" / "a"), f"{self.s}-x/a", f"{self.outside}/a", "/etc/x", f"{self.s}/../outside/a",
                     "../outside/a"):
            for tool in ("Write", "Edit"):
                j = self.j(tool, file_path=path, content="x", old_string="a", new_string="b")
                self.assertEqual(j.action, "deny", (tool, path))
                self.assertTrue(j.reason)

    def test_a_link_to_the_outside_is_refused_with_no_card(self):
        os.symlink(self.outside, self.shared / "out")
        (self.outside / "x.txt").write_text("fictional")
        for path in (f"{self.s}/out/x.txt", f"{self.s}/out/new.txt"):
            for tool in ("Write", "Edit"):
                self.assertEqual(self.j(tool, file_path=path, content="x", old_string="a", new_string="b").action, "deny", (tool, path))

    def test_a_file_that_is_a_link_to_a_file_outside_is_refused(self):
        (self.outside / "x.txt").write_text("fictional")
        os.symlink(self.outside / "x.txt", self.shared / "x.txt")
        self.assertEqual(self.j("Write", file_path=f"{self.s}/x.txt", content="x").action, "deny")

    def test_a_link_to_a_file_inside_is_followed_and_asked_about(self):
        (self.shared / "real.md").write_text("x")
        os.symlink(self.shared / "real.md", self.shared / "alias.md")
        self.assertEqual(self.j("Write", file_path=f"{self.s}/alias.md", content="x").action, "ask")

    def test_a_link_from_the_shared_folder_into_the_work_folder_is_a_work_folder_write(self):
        os.symlink(self.work, self.shared / "w")
        j = self.j("Write", file_path=f"{self.s}/w/a.txt", content="x")
        self.assertEqual(j.action, "ask")
        self.assertIn("工作資料夾", j.reason)

    def test_a_link_from_the_work_folder_into_the_shared_folder_is_a_shared_write(self):
        os.symlink(self.shared, self.work / "s")
        j = self.j("Write", file_path=f"{self.w}/s/a.md", content="x")
        self.assertEqual(j.action, "ask")
        self.assertIn("共用資料夾", j.reason)

    def test_the_protected_names_at_any_depth_of_the_shared_folder(self):
        for name in (".git", ".codex", ".agents", ".claude", ".GIT", ".Claude"):
            for path in (f"{self.s}/{name}/x", f"{self.s}/a/b/{name}/x", f"{self.s}/{name}"):
                for tool in ("Write", "Edit"):
                    with self.subTest(path=path, tool=tool):
                        self.assertEqual(self.j(tool, file_path=path, content="x", old_string="a", new_string="b").action, "deny")

    def test_a_folder_that_is_a_protected_name_reached_through_a_link_is_still_refused(self):
        (self.shared / ".git").mkdir()
        os.symlink(self.shared / ".git", self.shared / "plain")
        self.assertEqual(self.j("Write", file_path=f"{self.s}/plain/config", content="x").action, "deny")

    def test_a_file_with_more_than_one_hard_link_is_refused_a_new_or_single_one_is_asked(self):
        a = self.shared / "a.md"
        a.write_text("x")
        os.link(a, self.shared / "b.md")
        (self.outside / "o.md").write_text("fictional")
        os.link(self.outside / "o.md", self.shared / "o.md")
        for name in ("a.md", "b.md", "o.md"):
            self.assertEqual(self.j("Write", file_path=f"{self.s}/{name}", content="x").action, "deny", name)
        (self.shared / "single.md").write_text("x")
        self.assertEqual(self.j("Write", file_path=f"{self.s}/single.md", content="x").action, "ask")
        self.assertEqual(self.j("Write", file_path=f"{self.s}/new.md", content="x").action, "ask")

    def test_no_path_is_refused(self):
        self.assertEqual(self.j("Write", content="x").action, "deny")
        self.assertEqual(self.j("Write", file_path="", content="x").action, "deny")
        self.assertEqual(self.j("Write", file_path="a\0b", content="x").action, "deny")


class ClaudeFolderAtAnyDepthTests(SharedJudgeCase):
    def test_the_work_folders_dot_claude_is_refused_at_any_depth_and_in_any_case(self):
        for path in (".claude/settings.json", "a/.claude/settings.json", "a/b/.Claude/x", "a/.CLAUDE", ".claude"):
            for tool in ("Write", "Edit"):
                for shared in ("yes", None):
                    with self.subTest(path=path, tool=tool, shared=shared):
                        j = self.j(tool, shared=shared, file_path=f"{self.w}/{path}", content="x", old_string="a", new_string="b")
                        self.assertEqual(j.action, "deny")
                        self.assertIn(".claude", j.reason.casefold())

    def test_other_dot_names_in_the_work_folder_are_not_changed_by_this(self):
        for path in (".git/config", ".codex/x", "a.claude", ".claudex/y", "notes/.gitignore"):
            self.assertEqual(self.j("Write", shared=None, file_path=f"{self.w}/{path}", content="x").action, "ask", path)


class ReadTests(SharedJudgeCase):
    def test_reads_in_the_shared_folder_are_allowed_by_vbear_itself(self):
        (self.shared / "sub").mkdir()
        for tool, inp in (("Read", {"file_path": f"{self.s}/a.md"}), ("Read", {"file_path": "../shared/a.md"}),
                          ("Grep", {"pattern": "x", "path": self.s}), ("Grep", {"pattern": "a/b", "path": f"{self.s}/sub", "glob": "*.md"}),
                          ("Glob", {"pattern": "*.md", "path": self.s})):
            j = cp.judge(tool, inp, self.w, shared=self.s)
            self.assertEqual((j.action, j.editable), ("allow", None), (tool, inp))

    def test_with_the_folder_off_a_read_there_asks_as_before(self):
        for tool, inp in (("Read", {"file_path": f"{self.s}/a.md"}), ("Grep", {"pattern": "x", "path": self.s})):
            self.assertEqual(cp.judge(tool, inp, self.w).action, "ask", (tool, inp))
            self.assertEqual(cp.judge(tool, inp, self.w, shared=None).action, "ask", (tool, inp))

    def test_a_path_in_neither_root_asks_and_so_does_a_mix(self):
        (self.outside / "a").write_text("x")
        for tool, inp in (("Read", {"file_path": f"{self.outside}/a"}), ("Read", {"file_path": "/etc/hosts"}),
                          ("Grep", {"pattern": "x", "path": str(self.tmp)}), ("Glob", {"pattern": "*.md", "path": f"{self.s}/../outside"})):
            self.assertEqual(cp.judge(tool, inp, self.w, shared=self.s).action, "ask", (tool, inp))

    def test_a_pattern_with_a_path_still_asks_in_the_shared_folder(self):
        for pattern in ("../**/*.env", "/etc/*", "**/*.md", "sub/*.md", "~/x", ""):
            self.assertEqual(cp.judge("Glob", {"pattern": pattern, "path": self.s}, self.w, shared=self.s).action, "ask", pattern)

    def test_a_link_out_of_the_shared_folder_makes_a_read_there_ask(self):
        os.symlink(self.outside, self.shared / "out")
        for tool, inp in (("Read", {"file_path": f"{self.s}/a.md"}), ("Grep", {"pattern": "x", "path": self.s}),
                          ("Glob", {"pattern": "*.md", "path": self.s})):
            j = cp.judge(tool, inp, self.w, shared=self.s)
            self.assertEqual(j.action, "ask", (tool, inp))
            self.assertIn("共用資料夾", j.reason)

    def test_a_link_out_of_the_shared_folder_does_not_make_a_read_in_the_work_folder_ask(self):
        os.symlink(self.outside, self.shared / "out")
        self.assertEqual(cp.judge("Read", {"file_path": f"{self.w}/a.txt"}, self.w, shared=self.s).action, "allow")

    def test_a_link_out_of_the_work_folder_does_not_make_a_read_in_the_shared_folder_ask(self):
        os.symlink(self.outside, self.work / "out")
        self.assertEqual(cp.judge("Read", {"file_path": f"{self.w}/a.txt"}, self.w, shared=self.s).action, "ask")
        self.assertEqual(cp.judge("Read", {"file_path": f"{self.s}/a.md"}, self.w, shared=self.s).action, "allow")

    def test_a_link_that_stays_inside_the_shared_folder_is_fine(self):
        (self.shared / "sub").mkdir()
        os.symlink(self.shared / "sub", self.shared / "in")
        self.assertEqual(cp.judge("Read", {"file_path": f"{self.s}/in/a.md"}, self.w, shared=self.s).action, "allow")

    def test_a_link_in_the_work_folder_to_the_shared_folder_leads_out_of_the_work_folder(self):
        os.symlink(self.shared, self.work / "s")
        self.assertEqual(cp.judge("Read", {"file_path": f"{self.w}/a.txt"}, self.w, shared=self.s).action, "ask")

    def test_the_default_path_of_a_search_is_the_work_folder_and_it_is_judged_there(self):
        self.assertEqual(cp.judge("Grep", {"pattern": "x"}, self.w, shared=self.s).action, "allow")
        os.symlink(self.shared, self.work / "s")
        self.assertEqual(cp.judge("Grep", {"pattern": "x"}, self.w, shared=self.s).action, "ask")


class TrackerTests(SharedJudgeCase):
    """A read that Claude Code did by itself (it never asked) is judged by the tracker the way VBear would have judged it: it
    knows the shared folder too, so a read VBear would have allowed there is not taken for a call that ran without its yes."""

    SID = "11111111-2222-4333-8444-555555555555"

    def run_call(self, tool, inp, shared):
        t = cp.ChatTracker(cp.constants_for("2.1.318"), session_id=self.SID, workdir=self.w, init_request_id="init-1", shared=shared)
        t.on_event({"type": "assistant", "session_id": self.SID, "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "tu1", "name": tool, "input": inp}]}})
        return t.on_event({"type": "user", "session_id": self.SID, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "fictional"}]}})

    def kinds(self, out):
        return [k for k, _ in out]

    def test_a_read_in_the_shared_folder_that_vbear_would_have_allowed_is_not_a_violation(self):
        out = self.run_call("Read", {"file_path": f"{self.s}/a.md"}, self.s)
        self.assertEqual(self.kinds(out), ["tool_result"])

    def test_without_the_shared_folder_it_is_one(self):
        out = self.run_call("Read", {"file_path": f"{self.s}/a.md"}, None)
        self.assertEqual(self.kinds(out), ["tool_result", "violation"])

    def test_a_read_in_the_shared_folder_that_vbear_would_have_asked_about_is_a_violation(self):
        os.symlink(self.outside, self.shared / "out")
        out = self.run_call("Read", {"file_path": f"{self.s}/a.md"}, self.s)
        self.assertEqual(self.kinds(out), ["tool_result", "violation"])

    def test_a_write_in_the_shared_folder_that_ran_unasked_is_a_violation(self):
        out = self.run_call("Write", {"file_path": f"{self.s}/a.md", "content": "x"}, self.s)
        self.assertEqual(self.kinds(out), ["tool_result", "violation"])


if __name__ == "__main__":
    unittest.main()
