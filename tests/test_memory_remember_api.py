"""P42-3: a line the person remembers from a group (the 「記住」 button beside a line of the group page) is saved with where it came
from: ``source = {how: "group", group_id, turn, speaker}``. The server checks that the group is there (P42-2 owns that check and the
``source`` field of POST /api/memory), so these tests wait for it: they are skipped until ``memory.edit`` exists, which P42-2 adds
together with it, and then they must pass. The groups are the real ones over a fake daemon (tests/group_fixtures.py); no CLI runs
and nothing leaves the machine; HOME and VBEAR_HOME are synthetic and short; the lines are made up."""
import unittest

from tests import test_group_api as tga
from vbear import memory

NEEDS_P42_2 = unittest.skipUnless(hasattr(memory, "edit"), "waits for P42-2: the source field of POST /api/memory")


class RememberFromGroupTests(unittest.TestCase):
    setUp = tga.GroupApiTests.setUp           # the console, the fake daemon and the cards of the group tests, without their tests
    call = tga.GroupApiTests.call
    make = tga.GroupApiTests.make
    config_bytes = tga.GroupApiTests.config_bytes

    def remember(self, gid, **over):
        source = {"how": "group", "group_id": gid, "turn": 1, "speaker": "you", **over}
        return self.call("/api/memory", "POST", {"kind": "work", "text": "我們週末在市集擺攤（虛構）", "source": source})

    @NEEDS_P42_2
    def test_a_line_from_a_group_is_saved_with_the_group_and_who_spoke(self):
        gid, _ = self.make(name="市集準備")
        before = self.config_bytes()
        for speaker in ("you", "employee"):
            status, out = self.remember(gid, speaker=speaker)
            self.assertEqual(status, 201, out)
            self.assertEqual((out["entry"]["source"]["how"], out["entry"]["source"]["group_id"], out["entry"]["source"]["speaker"]),
                             ("group", gid, speaker))
        status, view = self.call("/api/memory")
        self.assertEqual([e["source"]["how"] for e in view["entries"]], ["group", "group"])
        self.assertEqual(self.config_bytes(), before, "remembering a line changes no setting")

    @NEEDS_P42_2
    def test_a_group_that_is_not_there_is_refused(self):
        status, out = self.remember("g-000000000000")
        self.assertEqual(status, 400, out)
        self.assertEqual(self.call("/api/memory")[1]["entries"], [])
