"""P45-4: reading a suggestion's record while another thread replaces it.

A record is replaced whole (``os.replace`` of a temporary file). A reader that opens the file just before the replace holds the old,
complete file whose link count has gone to 0. That is not a hard link and must read; a file with two names (a real hard link) is still
refused. This was the cause of the rare ``SuggestError: ... 有多個連結`` in ``test_memory_suggest`` ``test_two_at_once_are_refused`` on a busy machine.

Seams: ``MemorySuggest``'s and ``SkillSuggest``'s record stores, read through ``load()``. The replace happens at the one moment that matters,
between the open and the look at the link count, by a wrapper around the opener. Every name here is made up."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import config as cfg, memory_suggest as ms, skillbook_suggest as ks, strictjson

MS_ID = "ms-" + "0" * 12
KS_ID = "ks-" + "0" * 12


class ReadRace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbr-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        (home / ".vbear").mkdir(parents=True, mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)

    def stores(self):
        return (("memory", ms.SuggestStore(MS_ID)), ("skill", ks.SuggestStore(KS_ID)))

    def replaced_after_open(self, store, text):
        """The opener, but the file is replaced by another complete one after it was opened and before its link count is looked at."""
        real = strictjson.open_owned

        def racing(path, **kw):
            fd, _ = real(path, **kw)
            cfg.write_private(Path(path), text)
            return fd, os.fstat(fd)
        return mock.patch.object(strictjson, "open_owned", racing)

    def test_a_record_replaced_while_it_is_being_opened_is_read_whole(self):
        for label, store in self.stores():
            with self.subTest(label):
                store._make_folder()
                cfg.write_private(store.path(), '{"old": true}')
                with self.replaced_after_open(store, '{"new": true}'):
                    self.assertEqual(store._read_raw(), '{"old": true}', "the file that was opened is complete, and it is the old one")

    def test_a_file_with_two_names_is_still_refused(self):
        for label, store in self.stores():
            with self.subTest(label):
                store._make_folder()
                cfg.write_private(store.path(), "{}")
                twin = store.path().with_name("twin.json")
                os.link(store.path(), twin)
                self.addCleanup(twin.unlink)
                with self.assertRaises(OSError) as got:
                    store._read_raw()
                self.assertIn("連結", str(got.exception))


if __name__ == "__main__":
    unittest.main()
