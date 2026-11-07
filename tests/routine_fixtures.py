"""P44-2: what the routine tests share. A fake runtime daemon (the dispatch tests' ``FakeDaemon``: chats are real records in the state
folder; a turn ends when a test says so), two role cards, the real ``ChatService`` over it, and a clock a test moves by hand (a
Monday morning in New York, so the days of the week and the zone are never the machine's). No CLI runs, nothing leaves the machine,
nothing waits for real time; HOME and VBEAR_HOME are synthetic and short. Every name and text here is made up."""
from __future__ import annotations

import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from tests.test_dispatch_runner import FakeDaemon
from vbear import agent_profiles as ap, chat_service, config as cfg, routine_runner as rrun, routines as rt
from vbear.runtime import chat_store as cs

NY = ZoneInfo("America/New_York")
HEAD = {"state": "ready"}


def at(y, mo, d, h=0, mi=0, s=0, tz=NY) -> float:
    return datetime.datetime(y, mo, d, h, mi, s, tzinfo=tz).timestamp()


MONDAY_0759 = at(2026, 11, 9, 7, 59, 0)


class RoutineBase(unittest.TestCase):
    TZ = NY

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbr-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.writer, self.accountant = card("文案小編", "social"), card("會計師", "accountant")
        self.now = [MONDAY_0759]
        self.daemon = FakeDaemon(clock=lambda: self.now[0])
        self.service = chat_service.ChatService(self.daemon, claude=lambda: (sys.executable, "2.1.318", ""), codex=lambda: dict(HEAD),
                                                codex_binary=lambda: (sys.executable, "0.163.0"))
        self.service.restart_pause = 0
        self.conf: dict = {}
        self.lamp = ["green"]
        self.ledger_error = [None]
        self.runner = rrun.RoutineRunner(chats=lambda: self.service, ledger=self.ledger, conf=lambda: self.conf,
                                         clock=lambda: self.now[0], tz=self.TZ)
        self.addCleanup(self.runner.close)

    # -- the world a test sets up ---------------------------------------------------------------------------------

    def ledger(self):
        if self.ledger_error[0] is not None:
            raise self.ledger_error[0]
        return {"lamp": self.lamp[0], "daily_usd": "3", "spent_usd": "0.5"}

    def item3(self, on=True):
        self.conf = {"autonomy": {"create_cards": False, "dispatch": False, "routines": on, "auto_continue": False}}

    def routine(self, enabled=True, **over) -> dict:
        body = {"name": "市集日報", "profile_id": self.writer, "text": "請整理昨天的銷售。", "days": [0, 1, 2, 3, 4], "times": ["08:00"],
                "enabled": enabled}
        body.update(over)
        return rt.create(body, self.service.cards(), now=self.now[0])["routine"]

    def tick(self) -> dict:
        return self.runner.tick()

    def tick_to(self, hour, minute, second=0, day=(2026, 11, 9)) -> dict:
        """Move the clock to a time of Monday 2026-11-09 (New York) and run one pass."""
        self.go_to(at(*day, hour, minute, second))
        return self.runner.tick()

    def tick_after(self, seconds: float) -> dict:
        self.advance(seconds)
        return self.runner.tick()

    def restart(self) -> None:
        """The console is stopped and started again: a new runner over the same records and the same chats, remembering nothing."""
        self.runner.close()
        self.runner = rrun.RoutineRunner(chats=lambda: self.service, ledger=self.ledger, conf=lambda: self.conf,
                                         clock=lambda: self.now[0], tz=self.TZ)
        self.addCleanup(self.runner.close)

    def chat_files(self) -> list:
        return cs.list_ids(cfg.state_dir())

    def advance(self, seconds: float) -> None:
        self.now[0] += seconds

    def go_to(self, ts: float) -> None:
        self.now[0] = ts

    # -- what a test reads -----------------------------------------------------------------------------------------

    def runs(self, routine_id=None) -> list:
        runs, problem = rt.read_runs()
        self.assertIsNone(problem)
        return [r for r in runs if routine_id is None or r["routine_id"] == routine_id]

    def states(self, routine_id=None) -> list:
        return [r["state"] for r in self.runs(routine_id)]

    def sent(self) -> list:
        return self.daemon.sent
