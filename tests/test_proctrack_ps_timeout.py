"""proctrack's ``ps`` fallback: a bounded subprocess, and a timeout is "cannot read the table" (fail closed)."""

import subprocess
import unittest
from unittest import mock

from vbear.runtime import proctrack


class PsFallbackTests(unittest.TestCase):
    def test_the_timeout_is_passed_and_a_timeout_is_unavailable_not_empty(self):
        seen = {}

        def run(cmd, **kw):
            seen.update(kw)
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        with mock.patch.object(proctrack.subprocess, "run", run):
            with self.assertRaises(proctrack.ProcessTableUnavailable):
                proctrack._table_ps(0.5)
            self.assertEqual(seen["timeout"], 0.5)
            with self.assertRaises(proctrack.ProcessTableUnavailable):
                proctrack._table_ps()                              # the default bound stays
            self.assertEqual(seen["timeout"], proctrack.PS_TIMEOUT)

    def test_process_table_hands_the_timeout_to_the_fallback_only(self):
        with mock.patch.object(proctrack, "SOURCE", "ps"), \
                mock.patch.object(proctrack, "_table_ps", return_value=[]) as ps:
            proctrack.process_table(0.5)
            ps.assert_called_once_with(0.5)
        with mock.patch.object(proctrack, "SOURCE", "libproc"), \
                mock.patch.object(proctrack, "_table_libproc", return_value=[]) as lp, \
                mock.patch.object(proctrack, "_table_ps") as ps:
            proctrack.process_table(0.5)
            lp.assert_called_once_with()
            ps.assert_not_called()


if __name__ == "__main__":
    unittest.main()
