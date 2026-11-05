"""One chat process's own rules, without the daemon's loop (P36-1): what an answer does at the very moment a card
expires, before any timer has run, and that the live view always fits one reply. The process is a harmless child that only reads its stdin; nothing is written to
it (the queued lines are looked at instead). Synthetic VBEAR_HOME; no CLI runs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear.runtime import chat_session as csess
from vbear.runtime import chat_store as cs

NOW = 1000.0                       # monotonic, as the daemon passes it


class ProcessCase(unittest.TestCase):
    """A ChatProcess in turn 1 with one Bash card waiting."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcs-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        chat = cs.create(self.base, "emp-1", now=time.time())
        self.chat_id = chat["id"]
        log = cs.ChatLog(self.base, self.chat_id)
        proc = subprocess.Popen([sys.executable, "-I", "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.addCleanup(self._end, proc, log)
        manifest = {"launch_id": "chat-test", "cli_version": "2.1.318", "model_id": "claude-haiku-5-5",
                    "claude_session_id": chat["claude_session_id"],
                    "canonical_workspace": cs.ensure_work_dir(self.base, "emp-1"), "budget_usd": "0.5"}
        self.p = csess.ChatProcess(
            sid="s-test", chat_id=self.chat_id, profile_id="emp-1", manifest=manifest, proc=proc, log=log,
            last_total=None, next_turn=1, now=NOW, leader_start=None, logger=lambda *a, **k: None,
            watch=lambda *a: None, unwatch=lambda *a: None, card_ttl=300.0, init_deadline=30.0, turn_timeout=600.0,
            idle_timeout=600.0, close_grace=5.0, close_below=Decimal("0.01"))
        self.p.state = "idle"
        self.p.turn = csess.Turn(1, Decimal("0.5"), NOW, b"", True)
        self.p._on_permission({"request_id": "req-1", "tool": "Bash", "input": {"command": "echo fictional"},
                               "tool_use_id": "toolu_1"}, NOW)
        [self.card] = self.p.cards.values()

    @staticmethod
    def _end(proc, log):
        proc.kill()
        proc.wait(5)
        for f in (proc.stdin, proc.stdout, proc.stderr):
            f.close()
        log.close()

    def queued(self):
        return [json.loads(line) for line in self.p.out]

    def decisions(self):
        ev = cs.read_events(self.base, self.chat_id)
        return [r["decision"] for r in ev.records if r["kind"] == "card_decision"]



class AnswerClockTests(ProcessCase):
    def test_an_answer_at_the_expiry_is_refused_before_any_timer_runs(self):
        c = self.card
        code, message = self.p.answer(c.card_id, c.token, "allow", None, c.expires)
        self.assertEqual(code, "expired")
        self.assertIn("過期", message)
        self.assertEqual(self.p.cards, {})
        [line] = self.queued()
        self.assertEqual(line["response"]["response"], {"behavior": "deny", "message": csess.EXPIRED})
        self.assertEqual(self.decisions(), ["expired"])
        self.assertEqual(self.p.answer(c.card_id, c.token, "allow", None, c.expires)[0], "gone")
        # The deny is taken as written, as the daemon's loop would have done: otherwise the write deadline, which reads
        # the real monotonic clock, would compare it with this test's made-up one.
        self.p.out.clear()
        self.p.write_since = None
        self.p._timers(c.expires + 1)                         # the timer finds nothing more to refuse
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.decisions(), ["expired"])

    def test_an_answer_just_before_the_expiry_is_taken(self):
        c = self.card
        self.assertEqual(self.p.answer(c.card_id, c.token, "allow", None, c.expires - 0.001), (None, ""))
        [line] = self.queued()
        self.assertEqual(line["response"]["response"]["behavior"], "allow")
        self.assertEqual(self.decisions(), ["allow"])


class LiveViewTests(ProcessCase):
    def test_the_budgets_leave_room_in_one_reply(self):
        from vbear.runtime import daemon as d, daemon_chat as dc
        self.assertLessEqual(csess.CARDS_SHOW_TOTAL + (2 << 10), csess.LIVE_MAX)          # the cards and the rest
        self.assertLessEqual(csess.LIVE_MAX + (16 << 10), dc.REPLY_BUDGET)    # records always get some room
        self.assertLessEqual(dc.REPLY_BUDGET + (4 << 10), d.MAX_LINE)       # and the envelope fits

    def test_a_reply_being_written_never_breaks_the_view(self):
        self.p.partial = "\ud800" + "\x01" * 9000 + "end"                   # a lone surrogate, 6-byte escapes
        view = self.p.live_view(NOW)
        self.assertLessEqual(csess._size(view), csess.LIVE_MAX)
        self.assertTrue(view["partial_truncated"])
        self.assertTrue(view["partial"].endswith("end"))
        self.assertEqual(view["cards"][0]["input"], {"command": "echo fictional"})


if __name__ == "__main__":
    unittest.main()
