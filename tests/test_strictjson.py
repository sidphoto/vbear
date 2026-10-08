"""Strict, bounded JSON and file reading (vbear/strictjson.py, design 2.3)."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from vbear import strictjson as sj

SMALL = sj.Limits(unit_bytes=200, unit_nodes=20, depth=4, file_bytes=400)


class ScanTests(unittest.TestCase):
    def test_counts_structure_outside_strings_only(self):
        self.assertIsNone(sj.scan(b'{"a": "[[[[[[[[,,,,::::"}', SMALL))
        self.assertIsNone(sj.scan(b'{"a\\"[[[[[": 1}', SMALL))           # escaped quote stays in the string
        self.assertIsNone(sj.scan(b'["\\\\", [1]]', SMALL))               # escaped backslash ends the escape

    def test_limits(self):
        self.assertIn("深度", sj.scan(b"[" * 5 + b"]" * 5, SMALL))
        self.assertIsNone(sj.scan(b"[" * 4 + b"]" * 4, SMALL))            # the limit itself is fine
        self.assertIn("節點", sj.scan(b"[" + b"1," * 30 + b"1]", SMALL))
        self.assertIn("bytes", sj.scan(b" " * 201, SMALL))
        self.assertIsNone(sj.scan(b" " * 200, SMALL))
        self.assertIsNotNone(sj.scan("text", SMALL))                      # not bytes

    def test_linear_on_hostile_input(self):
        # Escaped quotes that never close: each would restart a naive string
        # regex from there to the end (quadratic). Must stay fast.
        limits = sj.Limits(4 << 20, 10 ** 9, 64, None)
        for raw in (b'"' + b'\\"' * (1 << 20), b'"' + b"\\" * (2 << 20), b'"' * (2 << 20),
                    b"[" * 64 + b'"' + b"x" * (3 << 20)):
            # CPU time of this thread, not wall clock: quadratic work would
            # take minutes either way, but a loaded machine only delays the
            # wall clock (seen at 4.1 s under the planner's load test).
            t = time.thread_time()
            sj.scan(raw, limits)
            self.assertLess(time.thread_time() - t, 3.0)


class LoadsTests(unittest.TestCase):
    def ok(self, raw, limits=SMALL):
        r = sj.loads(raw, limits)
        self.assertTrue(r.ok, r.problem)
        return r.value

    def bad(self, raw, limits=SMALL):
        r = sj.loads(raw, limits)
        self.assertFalse(r.ok, raw[:40])
        self.assertTrue(r.problem)
        return r.problem

    def test_strict_rules(self):
        self.assertEqual(self.ok(b'{"a": [1, 2.5, "x", null, true]}'), {"a": [1, 2.5, "x", None, True]})
        self.assertIn("重複", self.bad(b'{"a": 1, "a": 2}'))
        self.assertIn("重複", self.bad(b'{"x": {"a": 1, "a": 2}}'))
        for raw in (b"NaN", b"Infinity", b"-Infinity", b'{"a": NaN}', b"[1e400]", b"[-1e400]"):
            self.bad(raw)
        self.bad(b'{"a": "\xff"}')                                         # invalid UTF-8
        self.bad(b'{"a": 1')                                               # truncated
        self.bad(b"")
        self.bad(b"[" + b"9" * 5000 + b"]", sj.Limits(10_000, 10, 4, None))  # int beyond the digit limit

    def test_never_raises(self):
        for raw in (None, 1, "str", [], b"\x00" * 10, bytearray(b"[1]"), b"[" * 10_000):
            r = sj.loads(raw, sj.Limits(1 << 20, 10 ** 6, 10 ** 6, None))
            self.assertIsInstance(r, sj.Parsed)

    def test_deep_input(self):
        deep = b"[" * 100_000 + b"]" * 100_000
        # With the scan's depth check effectively off, whatever the parser
        # does (this Python's C parser copes) comes back as a result.
        self.assertIsInstance(sj.loads(deep, sj.Limits(1 << 20, 10 ** 6, 10 ** 6, None)), sj.Parsed)
        # With the design's limits it is refused before parsing.
        r = sj.loads(deep, sj.CLAUDE_STDOUT)
        self.assertFalse(r.ok)
        self.assertIn("深度", r.problem)

    def test_object_root(self):
        self.assertTrue(sj.loads_object(b"{}", SMALL).ok)
        for raw in (b"[]", b"1", b'"s"', b"null"):
            self.assertFalse(sj.loads_object(raw, SMALL).ok)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbsj-")))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))

    def write(self, name, data: bytes) -> Path:
        p = self.dir / name
        p.write_bytes(data)
        return p

    def test_reads_an_owned_regular_file(self):
        p = self.write("a.json", b'{"k": 1}')
        self.assertEqual(sj.load_owned_object(p, SMALL).value, {"k": 1})

    def test_refusals(self):
        target = self.write("t.json", b"{}")
        (self.dir / "link.json").symlink_to(target)
        os.mkfifo(self.dir / "fifo")
        (self.dir / "dir").mkdir()
        self.write("big.json", b"{" + b" " * 300 + b"}")
        cases = {"missing.json": "不存在", "link.json": "無法開啟", "fifo": "不是一般檔案",
                 "dir": "不是一般檔案", "big.json": "超過"}
        for name, words in cases.items():
            with self.subTest(name=name):
                r = sj.load_owned_object(self.dir / name, SMALL)
                self.assertFalse(r.ok)
                self.assertIn(words, r.problem)
        with self.assertRaises(sj.ReadRefused) as cm:
            sj.read_owned(self.dir / "missing.json", max_bytes=10)
        self.assertTrue(cm.exception.missing)

    def test_growth_after_fstat_is_caught(self):
        p = self.write("g.json", b"x" * 10)
        fd, st = sj.open_owned(p, max_bytes=20)
        try:
            with open(p, "ab") as f:
                f.write(b"y" * 100)                                     # grows after the check
            with self.assertRaises(sj.ReadRefused):
                sj.read_fd(fd, 20)
        finally:
            os.close(fd)

    def test_other_owner_is_refused(self):
        p = self.write("o.json", b"{}")
        real = os.fstat

        def other_owner(fd):
            st = real(fd)
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid + 1, st.st_gid,
                                   st.st_size, st.st_atime, st.st_mtime, st.st_ctime))
        from unittest import mock
        with mock.patch("vbear.strictjson.os.fstat", other_owner):
            r = sj.load_owned_object(p, SMALL)
        self.assertFalse(r.ok)
        self.assertIn("使用者", r.problem)


class LineTests(unittest.TestCase):
    def lines(self, data: bytes, limits=SMALL):
        r, w = os.pipe()
        os.write(w, data)
        os.close(w)
        try:
            return list(sj.iter_json_lines(r, limits))
        finally:
            os.close(r)

    def test_each_line_is_a_unit(self):
        out = self.lines(b'{"a": 1}\n{"b": [2]}\n')
        self.assertEqual([p.value for p in out], [{"a": 1}, {"b": [2]}])

    def test_whole_file_problems(self):
        out = self.lines(b'{"a": 1}\n{"b": 2}')
        self.assertTrue(out[0].ok)
        self.assertFalse(out[-1].ok)
        self.assertIn("換行", out[-1].problem)
        out = self.lines(b'{"a": "' + b"x" * 300 + b'"}\n')
        self.assertIn("超過", out[-1].problem)
        out = self.lines(b'{"a": 1}\n' * 60)                            # 540 bytes > file limit 400
        self.assertFalse(out[-1].ok)
        self.assertIn("檔案超過", out[-1].problem)

    def test_bad_lines_are_failed_results_not_errors(self):
        out = self.lines(b'{"a": NaN}\n[1]\n{"a": 1, "a": 1}\n\n{"ok": 1}\n')
        self.assertEqual([p.ok for p in out], [False, False, False, False, True])

    def test_a_long_line_without_newline_stops_early(self):
        limits = sj.Limits(100, 10, 4, None)
        out = self.lines(b"x" * 1000, limits)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].ok)


class TableTests(unittest.TestCase):
    def test_the_design_table(self):
        MiB, KiB = 1 << 20, 1 << 10
        expected = {
            "CLAUDE_STDOUT": (MiB, 200_000, 64, None), "CODEX_EVENTS": (MiB, 200_000, 64, 8 * MiB),
            "ROLLOUT": (4 * MiB, 500_000, 64, 64 * MiB), "SESSION_LOG": (512 * KiB, 100_000, 32, 16 * MiB),
            "MANIFEST": (64 * KiB, 10_000, 16, 64 * KiB), "AUTH_JSON": (64 * KiB, 1_000, 8, 64 * KiB),
            "CLAUDE_JSON": (16 * MiB, 2_000_000, 64, 16 * MiB), "PREVIEW": (128 * KiB, 10_000, 16, 128 * KiB),
        }
        for name, values in expected.items():
            l = getattr(sj, name)
            self.assertEqual((l.unit_bytes, l.unit_nodes, l.depth, l.file_bytes), values, name)


if __name__ == "__main__":
    unittest.main()
