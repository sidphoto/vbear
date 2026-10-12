"""tools/stream_capture.py: where its raw lines may go. No model is called and no CLI is started: only the output
guard is exercised (S3 real end-to-end review, 2026-10-12)."""

import importlib.util
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "stream_capture.py"


def load():
    spec = importlib.util.spec_from_file_location("stream_capture_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OutputGuardTests(unittest.TestCase):
    def setUp(self):
        self.cap = load()
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcap-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "worktree"
        self.root.mkdir()
        (self.tmp / "elsewhere").mkdir()
        self.fds = []

    def tearDown(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass

    def dirfd(self):
        fd = self.cap.open_capture_dir(self.root)
        self.fds.append(fd)
        return fd

    def test_the_directory_is_made_owner_only_and_the_file_is_new_owner_only(self):
        fd = self.dirfd()
        made = self.root / "_sandbox" / "captures"
        self.assertTrue(made.is_dir())
        self.assertEqual(stat.S_IMODE(os.stat(made).st_mode), 0o700)
        out = self.cap.create_capture(fd, "raw.jsonl")
        self.fds.append(out)
        self.assertEqual(stat.S_IMODE(os.stat(made / "raw.jsonl").st_mode), 0o600)
        with self.assertRaises(SystemExit):                      # never an existing file, even one it just made
            self.cap.create_capture(fd, "raw.jsonl")

    def test_only_a_plain_file_name_is_accepted(self):
        fd = self.dirfd()
        for bad in ("", "a/b", "../x", "/etc/passwd", ".hidden", "x" * 80, "a b", "..", "a\x00b"):
            with self.subTest(name=bad):
                with self.assertRaises(SystemExit):
                    self.cap.create_capture(fd, bad)

    def test_an_existing_file_or_link_is_refused_and_left_alone(self):
        fd = self.dirfd()
        captures = self.root / "_sandbox" / "captures"
        (captures / "old.jsonl").write_text("old")
        os.chmod(captures / "old.jsonl", 0o644)
        with self.assertRaises(SystemExit):
            self.cap.create_capture(fd, "old.jsonl")
        self.assertEqual((captures / "old.jsonl").read_text(), "old")
        self.assertEqual(stat.S_IMODE(os.stat(captures / "old.jsonl").st_mode), 0o644)
        (captures / "dangling.jsonl").symlink_to(self.tmp / "elsewhere" / "target")
        with self.assertRaises(SystemExit):
            self.cap.create_capture(fd, "dangling.jsonl")
        self.assertFalse((self.tmp / "elsewhere" / "target").exists())

    def test_a_link_in_place_of_a_directory_is_not_followed(self):
        (self.root / "_sandbox").symlink_to(self.tmp / "elsewhere")
        with self.assertRaises(OSError):
            self.cap.open_capture_dir(self.root)
        self.assertEqual(os.listdir(self.tmp / "elsewhere"), [])

    def test_replacing_the_directory_by_a_link_after_the_check_writes_nothing_outside(self):
        fd = self.dirfd()                                        # checked and held
        captures = self.root / "_sandbox" / "captures"
        moved = self.root / "_sandbox" / "captures-moved"
        os.rename(captures, moved)                               # the race: the checked directory is swapped
        captures.symlink_to(self.tmp / "elsewhere")              # for a link that leaves the worktree
        out = self.cap.create_capture(fd, "raw.jsonl")
        self.fds.append(out)
        os.write(out, b"x")
        self.assertEqual(os.listdir(self.tmp / "elsewhere"), [])         # nothing went through the link
        self.assertEqual(os.listdir(moved), ["raw.jsonl"])               # it went where the descriptor points


class InputGuardTests(unittest.TestCase):
    """--text-file and --repo name an earlier run's own files: below _sandbox, reached without following a link at
    any level, a bounded regular file."""

    def setUp(self):
        self.cap = load()
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcap-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "worktree"
        (self.root / "_sandbox" / "runs").mkdir(parents=True)
        (self.tmp / "elsewhere").mkdir()
        (self.tmp / "elsewhere" / "t.txt").write_text("OUTSIDE")

    def load(self, path):
        return self.cap.load_text_file(str(path), self.root)

    def test_the_text_file_is_read_with_the_id_it_names(self):
        d = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
        f = self.root / "_sandbox" / "runs" / "text.txt"
        f.write_text('task\n{"v":1,"dispatch_id":"' + d + '","status":"x"}\n')
        text, found = self.load(f)
        self.assertEqual(found, d)
        self.assertIn("task", text)
        f.write_text("no id here")
        self.assertEqual(self.load(f)[1], None)

    def test_outside_the_sandbox_is_refused(self):
        for path in (self.tmp / "elsewhere" / "t.txt", self.root / "README.md",
                     self.root / "_sandbox" / ".." / "x", self.root / "_sandbox", Path("/etc/hosts")):
            with self.subTest(path=str(path)):
                with self.assertRaises(SystemExit):
                    self.load(path)

    def test_a_link_at_any_level_is_refused_and_nothing_outside_is_read(self):
        outside = self.tmp / "elsewhere"
        # the file itself
        (self.root / "_sandbox" / "runs" / "link.txt").symlink_to(outside / "t.txt")
        # a directory in the middle
        (self.root / "_sandbox" / "dirlink").symlink_to(outside)
        with self.assertRaises(SystemExit):
            self.load(self.root / "_sandbox" / "runs" / "link.txt")
        with self.assertRaises(SystemExit):
            self.load(self.root / "_sandbox" / "dirlink" / "t.txt")
        # _sandbox itself a link to a directory outside the worktree
        shutil.rmtree(self.root / "_sandbox")
        (self.root / "_sandbox").symlink_to(outside)
        with self.assertRaises(SystemExit):
            self.load(self.root / "_sandbox" / "t.txt")
        with self.assertRaises(SystemExit):
            self.cap.verified_repo(str(self.root / "_sandbox"), self.root)

    def test_too_large_or_not_a_file_is_refused(self):
        big = self.root / "_sandbox" / "runs" / "big.txt"
        big.write_text("x" * (self.cap.TEXT_MAX + 1))
        with self.assertRaises(SystemExit):
            self.load(big)
        with self.assertRaises(SystemExit):                      # a directory
            self.load(self.root / "_sandbox" / "runs")

    def test_the_repository_directory_is_verified_the_same_way(self):
        repo = self.root / "_sandbox" / "runs" / "toy"
        repo.mkdir()
        path, ident = self.cap.verified_repo(str(repo), self.root)
        self.assertEqual(path, repo)
        self.assertEqual(ident, (os.stat(repo).st_dev, os.stat(repo).st_ino))
        (self.root / "_sandbox" / "runs" / "toylink").symlink_to(self.tmp / "elsewhere")
        with self.assertRaises(SystemExit):
            self.cap.verified_repo(str(self.root / "_sandbox" / "runs" / "toylink"), self.root)
        with self.assertRaises(SystemExit):
            self.cap.verified_repo(str(self.tmp / "elsewhere"), self.root)

    def test_the_base_is_a_hex_commit(self):
        for good in ("abcdef1", "a" * 40):
            self.assertTrue(self.cap.BASE_RE.match(good))
        for bad in ("", "abc", "g" * 10, "a" * 41, "HEAD", "-x", "abc def", "abcdef1\n"):
            self.assertFalse(self.cap.BASE_RE.match(bad), bad)


if __name__ == "__main__":
    unittest.main()
