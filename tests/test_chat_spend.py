"""The chats share the day's limit with the meetings and the staffing meetings (P36-1): the boards count a chat's
turns (a running one at its cap), and the ledger says it includes them. Synthetic HOME and VBEAR_HOME; no CLI runs."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import meeting_runner as mr, staffing_runner as sr
from vbear.runtime import chat_store as cs


class SharedDayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbsp-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        chat = cs.create(self.base, "emp-1", now=time.time())
        log = cs.ChatLog(self.base, chat["id"])
        try:
            for n, cost in ((1, "0.12"), (2, None)):
                log.append("user_message", {"turn": n, "text": "hi"}, now=time.time())
                log.append("turn_started", {"turn": n, "cap_usd": "0.3"}, now=time.time())
                if cost:
                    log.append("turn_ended", {"turn": n, "cost_usd": cost, "reported": True, "total_usd": 0.12,
                                              "reason": "result", "subtype": "success", "is_error": False},
                               now=time.time())
        finally:
            log.close()

    def test_both_boards_count_the_chats(self):
        meetings = mr.MeetingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        staffing = sr.StaffingRunner(provider=lambda e: ("x", "0"), call=lambda s, c: None)
        for runner in (meetings, staffing):
            self.assertEqual(runner._day(), Decimal("0.42"), runner)          # 0.12 spent, 0.30 running at its cap
        ledger = meetings.ledger({})
        self.assertEqual((ledger["spent_usd"], ledger["includes"]), ("0.42", ["meetings", "staffing", "chats"]))
        self.assertEqual(ledger["lamp"], "green")


if __name__ == "__main__":
    unittest.main()
