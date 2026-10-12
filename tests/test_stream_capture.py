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
        self.sandbox = self.tmp / "_sandbox"
        (self.sandbox / "e2e-real").mkdir(parents=True)
        (self.tmp / "elsewhere").mkdir()

    def refused(self, path):
        with self.assertRaises(SystemExit):
            self.cap.check_out(str(path), self.sandbox)

    def test_a_new_file_under_the_sandbox_is_accepted_and_opened_owner_only_without_following_links(self):
        out = self.cap.check_out(str(self.sandbox / "e2e-real" / "raw.jsonl"), self.sandbox)
        self.assertEqual(out, self.sandbox / "e2e-real" / "raw.jsonl")
        self.assertFalse(out.exists())                           # checking creates nothing
        fd = self.cap.open_out(out)
        os.close(fd)
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        with self.assertRaises(FileExistsError):                 # never an existing file, even one it just made
            self.cap.open_out(out)

    def test_outside_the_sandbox_is_refused(self):
        self.refused(self.tmp / "elsewhere" / "raw.jsonl")
        self.refused(self.tmp / "raw.jsonl")
        self.refused(self.sandbox / "e2e-real" / ".." / ".." / "raw.jsonl")        # a way out by ".."
        self.refused(self.sandbox.parent / "_sandbox-other" / "raw.jsonl")          # a similar name

    def test_a_directory_link_that_leaves_the_sandbox_is_refused(self):
        (self.sandbox / "linkdir").symlink_to(self.tmp / "elsewhere")
        self.refused(self.sandbox / "linkdir" / "raw.jsonl")

    def test_anything_already_there_is_refused(self):
        existing = self.sandbox / "e2e-real" / "old.jsonl"
        existing.write_text("old")
        os.chmod(existing, 0o644)
        self.refused(existing)
        self.assertEqual(existing.read_text(), "old")             # untouched, permissions included
        self.assertEqual(stat.S_IMODE(os.stat(existing).st_mode), 0o644)
        dangling = self.sandbox / "e2e-real" / "dangling.jsonl"
        dangling.symlink_to(self.tmp / "elsewhere" / "target")
        self.refused(dangling)
        with self.assertRaises(OSError):                          # and the open itself does not follow it
            self.cap.open_out(dangling)
        self.assertFalse((self.tmp / "elsewhere" / "target").exists())


if __name__ == "__main__":
    unittest.main()
